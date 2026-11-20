import json
import os
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
import unittest

import pandas as pd

from backtesting import run_backtest
from brokers import MT5ReadOnlyAdapter
from identity import IdentityStore
from server import BotState, LIVE_ORDER_SUBMISSION_ENABLED, RequestHandler


class FixedAI:
    def analyze_market(self, symbol, price, indicators):
        return {
            "signal": "BUY",
            "confidence": 0.9,
            "stop_loss_price": price - 0.01,
            "take_profit_price": price + 0.02,
            "rationale": "test decision",
        }


class FixedData:
    mode = "simulated"

    def get_candles(self, symbol, interval, outputsize):
        closes = [1.1 + index * 0.00001 for index in range(outputsize)]
        return pd.DataFrame({
            "datetime": pd.date_range(
                "2026-01-01",
                periods=outputsize,
                freq="min",
            ),
            "open": [price - 0.00001 for price in closes],
            "high": [price + 0.00002 for price in closes],
            "low": [price - 0.00002 for price in closes],
            "close": closes,
            "volume": [1] * outputsize,
        })


class TestExecutionSafety(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = IdentityStore(
            os.path.join(self.temp_dir.name, "accounts.sqlite3")
        )
        registered = self.store.register(
            "safety@example.com",
            "safety test password",
        )
        self.user = self.store.authenticate(registered["token"])
        self.bot = BotState(
            data_client=FixedData(),
            ai_engine=FixedAI(),
            identity_store=self.store,
        )
        self.bot.market_data["EUR/USD"] = {
            "candles": pd.DataFrame(),
            "enriched_data": pd.DataFrame([{
                "rsi_14": 50.0,
                "ema_9": 1.1,
                "ema_21": 1.09,
                "ema_50": 1.08,
                "macd": 0.01,
                "macd_signal": 0.0,
                "macd_hist": 0.01,
                "bb_upper": 1.12,
                "bb_lower": 1.08,
                "atr_14": 0.01,
            }]),
            "current_price": 1.1,
            "last_update": time.time(),
            "error": None,
        }

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_analysis_never_submits_or_opens_a_position(self):
        result = self.bot.analyze("EUR/USD")

        self.assertEqual(result["decision"]["signal"], "BUY")
        self.assertIsNone(result["execution"])
        self.assertFalse(result["live_execution_enabled"])
        self.assertFalse(LIVE_ORDER_SUBMISSION_ENABLED)
        account = self.bot.account_for(self.user)
        self.assertEqual(account.portfolio.positions, {})

    def test_manual_paper_order_requires_assisted_mode_and_confirmation(self):
        args = {
            "user": self.user,
            "symbol": "EUR/USD",
            "side": "BUY",
            "stop_loss": 1.09,
            "take_profit": 1.12,
            "confirmation": True,
            "idempotency_key": "safe-test-order",
        }
        rejected = self.bot.create_manual_paper_order(**args)
        self.assertEqual(rejected["status"], "rejected")

        account = self.bot.account_for(self.user)
        account.settings["mode"] = "assisted"
        with self.assertRaises(ValueError):
            self.bot.create_manual_paper_order(
                **{**args, "confirmation": False}
            )

        result = self.bot.create_manual_paper_order(**args)
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["broker"], "paper")
        self.assertTrue(result["confirmed"])

        duplicate = self.bot.create_manual_paper_order(**args)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(account.portfolio.trade_history), 1)

    def test_read_only_mt5_adapter_never_submits_orders(self):
        adapter = MT5ReadOnlyAdapter()
        result = adapter.submit_order(
            "EUR/USD",
            "BUY",
            1.1,
            "never-used",
        )

        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["confirmed"])
        adapter.close()

    def test_authenticated_http_api_reports_paper_execution_only(self):
        handler = type(
            "TestRequestHandler",
            (RequestHandler,),
            {"state": self.bot},
        )
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base_url = "http://127.0.0.1:{0}".format(httpd.server_address[1])
        try:
            with urlopen(base_url + "/api/health", timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            self.assertFalse(health["live_execution_enabled"])
            self.assertEqual(health["execution_mode"], "paper")

            login = Request(
                base_url + "/api/auth/login",
                data=json.dumps({
                    "email": "safety@example.com",
                    "password": "safety test password",
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(login, timeout=5) as response:
                token = json.loads(response.read().decode("utf-8"))["token"]
            status_request = Request(
                base_url + "/api/status",
                headers={"Authorization": "Bearer " + token},
            )
            with urlopen(status_request, timeout=5) as response:
                status = json.loads(response.read().decode("utf-8"))
            self.assertEqual(status["execution_mode"], "paper")
            self.assertEqual(status["trading_mode"], "analysis")
            self.assertFalse(status["live_execution_enabled"])

            analyze_request = Request(
                base_url + "/api/analyze?symbol=EUR%2FUSD",
                headers={"Authorization": "Bearer " + token},
                data=b"{}",
                method="POST",
            )
            with urlopen(analyze_request, timeout=5) as response:
                analysis = json.loads(response.read().decode("utf-8"))
            self.assertEqual(analysis["ai_decision"]["signal"], "BUY")
            self.assertEqual(analysis["execution_mode"], "paper")
            self.assertIsNone(analysis["analysis"]["execution"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_backtest_uses_prior_bars_and_never_sends_broker_orders(self):
        candles = pd.DataFrame([
            {"open": 1.10, "high": 1.11, "low": 1.09, "close": 1.10},
            {"open": 1.10, "high": 1.11, "low": 1.095, "close": 1.105},
            {"open": 1.105, "high": 1.12, "low": 1.10, "close": 1.115},
        ])
        history_sizes = []

        def strategy(history, symbol):
            history_sizes.append(len(history))
            if len(history) == 1:
                return {
                    "signal": "BUY",
                    "confidence": 0.9,
                    "stop_loss_price": 1.09,
                    "take_profit_price": 1.12,
                }
            return {"signal": "HOLD", "confidence": 0.0}

        result = run_backtest(candles, strategy)

        self.assertEqual(history_sizes, [1, 2])
        self.assertFalse(result["assumptions"]["broker_orders_sent"])
        self.assertGreaterEqual(len(result["trades"]), 1)


if __name__ == "__main__":
    unittest.main()
