"""Local Forex analysis server with paper-only order handling."""

import json
import logging
import math
import os
import sys
import threading
import time
from dataclasses import fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests

from ai_engine import AITradingEngine
from brokers import MT5ReadOnlyAdapter, PaperBroker
from forex_data import ForexDataClient
from identity import IdentityStore
from indicators import compute_all_indicators
from portfolio import PortfolioManager
from smc_analysis import SMCAnalyzer, SMCConfig


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ForexTradingServer")

PAIRS = ("EUR/USD", "GBP/USD", "USD/JPY", "GBP/JPY")
TIMEFRAME_INTERVALS = {
    "H4": "4h",
    "H1": "1h",
    "M15": "15min",
    "M5": "5min",
}
LIVE_ORDER_SUBMISSION_ENABLED = False
MARKET_DATA_MAX_AGE_SECONDS = 300


class AccountContext:
    def __init__(self, user, portfolio, settings, identity_store):
        self.user = user
        self.portfolio = portfolio
        self.settings = settings
        self.identity_store = identity_store
        self.lock = threading.RLock()
        self.broker = PaperBroker(
            portfolio,
            order_store=identity_store,
            user_id=user["id"],
            persist_callback=self.persist,
        )

    def persist(self):
        self.settings["mode"] = self.settings.get("mode", "analysis")
        self.identity_store.save_account_state(
            self.user["id"],
            self.portfolio.export_state(),
            self.settings,
        )


class BotState:
    def __init__(
        self,
        data_client=None,
        ai_engine=None,
        identity_store=None,
    ):
        self.is_running = True
        self.data_client = data_client or ForexDataClient()
        self.ai_engine = ai_engine or AITradingEngine()
        self.identity_store = identity_store or IdentityStore()
        self.market_data = {
            symbol: {
                "candles": pd.DataFrame(),
                "enriched_data": pd.DataFrame(),
                "current_price": 0.0,
                "last_update": 0.0,
                "error": None,
            }
            for symbol in PAIRS
        }
        self.latest_ai_decisions = {
            symbol: self._waiting_decision()
            for symbol in PAIRS
        }
        self.lock = threading.RLock()
        self._accounts = {}
        self._accounts_lock = threading.RLock()
        self._stop_event = threading.Event()

    @staticmethod
    def _waiting_decision():
        return {
            "signal": "HOLD",
            "confidence": 0.0,
            "suggested_allocation_pct": 0.01,
            "stop_loss_price": 0.0,
            "take_profit_price": 0.0,
            "risk_reward_ratio": 0.0,
            "rationale": "Waiting for market data and analysis.",
        }

    def account_for(self, user):
        user_id = user["id"]
        with self._accounts_lock:
            if user_id not in self._accounts:
                portfolio_state, settings = (
                    self.identity_store.read_account_state(user_id)
                )
                portfolio = (
                    PortfolioManager.from_state(portfolio_state)
                    if portfolio_state
                    else PortfolioManager(initial_balance=10000.0)
                )
                settings = settings or {}
                if settings.get("mode") not in {"analysis", "assisted"}:
                    settings["mode"] = "analysis"
                self._accounts[user_id] = AccountContext(
                    user,
                    portfolio,
                    settings,
                    self.identity_store,
                )
            return self._accounts[user_id]

    def refresh_market_data(self, symbol):
        if symbol not in PAIRS:
            raise ValueError(f"Unsupported Forex pair: {symbol}")

        candles = self.data_client.get_candles(
            symbol=symbol,
            interval="1min",
            outputsize=100,
        )
        if candles.empty:
            raise RuntimeError(f"No market candles returned for {symbol}.")

        enriched = compute_all_indicators(candles)
        if enriched.empty:
            raise RuntimeError(f"Could not calculate indicators for {symbol}.")

        price = float(enriched.iloc[-1]["close"])
        if not math.isfinite(price) or price <= 0:
            raise RuntimeError(f"Invalid latest market price for {symbol}.")

        with self.lock:
            self.market_data[symbol] = {
                "candles": candles,
                "enriched_data": enriched,
                "current_price": price,
                "last_update": time.time(),
                "error": None,
            }
        return price

    def refresh_all_market_data(self):
        successful = 0
        for symbol in PAIRS:
            try:
                self.refresh_market_data(symbol)
                successful += 1
            except (
                RuntimeError,
                ValueError,
                OSError,
                requests.exceptions.RequestException,
            ) as error:
                with self.lock:
                    self.market_data[symbol]["error"] = str(error)
                logger.warning("Market refresh failed for %s: %s", symbol, error)
        return successful

    @staticmethod
    def _indicator_summary(enriched, price):
        latest = enriched.iloc[-1]

        def finite_value(name, fallback):
            value = latest.get(name, fallback)
            try:
                value = float(value)
            except (TypeError, ValueError):
                return fallback
            return value if math.isfinite(value) else fallback

        return {
            "rsi": finite_value("rsi_14", 50.0),
            "ema_9": finite_value("ema_9", price),
            "ema_21": finite_value("ema_21", price),
            "ema_50": finite_value("ema_50", price),
            "macd": finite_value("macd", 0.0),
            "macd_signal": finite_value("macd_signal", 0.0),
            "macd_hist": finite_value("macd_hist", 0.0),
            "bb_upper": finite_value("bb_upper", price * 1.01),
            "bb_lower": finite_value("bb_lower", price * 0.99),
            "atr": finite_value("atr_14", price * 0.001),
            "trend_summary": (
                "Bullish"
                if finite_value("ema_9", price)
                > finite_value("ema_21", price)
                else "Bearish"
            ),
        }

    def analyze(self, symbol):
        if symbol not in PAIRS:
            raise ValueError(f"Unsupported Forex pair: {symbol}")
        with self.lock:
            data = self.market_data[symbol]
            if data["enriched_data"].empty:
                raise RuntimeError(f"No market data is available for {symbol}.")
            enriched = data["enriched_data"]
            price = data["current_price"]
            indicators = self._indicator_summary(enriched, price)

        decision = self.ai_engine.analyze_market(symbol, price, indicators)
        with self.lock:
            self.latest_ai_decisions[symbol] = decision
        return {
            "symbol": symbol,
            "price": price,
            "decision": decision,
            "execution": None,
            "live_execution_enabled": LIVE_ORDER_SUBMISSION_ENABLED,
        }

    def get_pair_payload(self, symbol):
        with self.lock:
            data = self.market_data[symbol]
            enriched = data["enriched_data"]
            if enriched.empty:
                return {
                    "symbol": symbol,
                    "price": None,
                    "indicators": {},
                    "ai_decision": self.latest_ai_decisions[symbol],
                    "last_update": None,
                    "error": data["error"],
                }

            latest = enriched.iloc[-1]
            price = data["current_price"]

            def value(name):
                result = latest.get(name)
                try:
                    result = float(result)
                except (TypeError, ValueError):
                    return None
                return result if math.isfinite(result) else None

            return {
                "symbol": symbol,
                "price": price,
                "last_update": data["last_update"],
                "error": data["error"],
                "indicators": {
                    "rsi": value("rsi_14"),
                    "ema_9": value("ema_9"),
                    "ema_21": value("ema_21"),
                    "macd": value("macd"),
                    "atr": value("atr_14"),
                },
                "ai_decision": self.latest_ai_decisions[symbol],
            }

    def market_loop(self):
        while not self._stop_event.is_set():
            if self.is_running:
                try:
                    successful = self.refresh_all_market_data()
                    logger.info(
                        "Market refresh complete: %s/%s pairs",
                        successful,
                        len(PAIRS),
                    )
                    self._check_paper_positions()
                except Exception:
                    logger.exception("Unexpected market-loop failure.")
            self._stop_event.wait(60)

    def _check_paper_positions(self):
        with self._accounts_lock:
            accounts = list(self._accounts.values())
        with self.lock:
            prices = {
                symbol: data["current_price"]
                for symbol, data in self.market_data.items()
                if data["current_price"] > 0
            }
        for account in accounts:
            with account.lock:
                changed = False
                for symbol, price in prices.items():
                    if account.portfolio.check_stop_loss_take_profit(
                        symbol,
                        price,
                    ):
                        changed = True
                if changed:
                    account.persist()

    def create_manual_paper_order(
        self,
        user,
        symbol,
        side,
        stop_loss,
        take_profit,
        confirmation,
        idempotency_key,
    ):
        if LIVE_ORDER_SUBMISSION_ENABLED:
            return {
                "status": "disabled",
                "reason": "Live order submission is disabled.",
                "confirmed": False,
            }
        if symbol not in PAIRS:
            raise ValueError(f"Unsupported Forex pair: {symbol}")
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if confirmation is not True:
            raise ValueError("Explicit confirmation is required.")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("A non-empty idempotency_key is required.")

        try:
            stop_loss = float(stop_loss)
            take_profit = float(take_profit)
        except (TypeError, ValueError) as error:
            raise ValueError("Valid stop-loss and take-profit are required.") from error
        if (
            not math.isfinite(stop_loss)
            or not math.isfinite(take_profit)
            or stop_loss <= 0
            or take_profit <= 0
        ):
            raise ValueError("Valid stop-loss and take-profit are required.")

        with self.lock:
            data = self.market_data[symbol]
            price = data["current_price"]
            updated_at = data["last_update"]
        if (
            price <= 0
            or not updated_at
            or time.time() - updated_at > MARKET_DATA_MAX_AGE_SECONDS
        ):
            return {
                "status": "rejected",
                "reason": "No sufficiently recent market price is available.",
                "confirmed": False,
            }

        account = self.account_for(user)
        with account.lock:
            if account.settings.get("mode", "analysis") != "assisted":
                return {
                    "status": "rejected",
                    "reason": (
                        "Manual paper orders require assisted mode. "
                        "No live orders are available."
                    ),
                    "confirmed": False,
                }
            signal = {
                "signal": side,
                "confidence": 1.0,
                "suggested_allocation_pct": 0.01,
                "stop_loss_price": stop_loss,
                "take_profit_price": take_profit,
                "risk_reward_ratio": 1.5,
                "rationale": "Manually confirmed paper order.",
            }
            result = account.broker.submit_order(
                symbol,
                signal,
                price,
                idempotency_key.strip(),
            )
            if result.get("status") == "executed":
                account.persist()
            return result

    def analyze_smc(self, symbol, config_data):
        if symbol not in PAIRS:
            raise ValueError(f"Unsupported Forex pair: {symbol}")
        if not isinstance(config_data, dict):
            raise ValueError("config must be an object.")

        allowed = {field.name for field in fields(SMCConfig)}
        unknown = set(config_data).difference(allowed)
        if unknown:
            raise ValueError(
                f"Unknown SMC configuration fields: {sorted(unknown)}"
            )

        config = SMCConfig(**config_data)
        analyzer = SMCAnalyzer(config)
        frames = {
            name: self.data_client.get_candles(
                symbol=symbol,
                interval=interval,
                outputsize=200,
            )
            for name, interval in TIMEFRAME_INTERVALS.items()
        }
        report = analyzer.analyze(symbol, frames)
        report["data_source"] = self.data_client.mode
        report["simulated_data_warning"] = (
            "Market candles are simulated and are not live prices."
            if self.data_client.mode == "simulated"
            else None
        )
        return report


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "AITradingBot/1.0"
    state = None

    def log_message(self, format_string, *args):
        logger.info("%s - %s", self.address_string(), format_string % args)

    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin")
        allowed_origin = os.getenv(
            "CORS_ALLOWED_ORIGIN",
            "http://localhost:8081",
        )
        if origin and origin == allowed_origin:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, Authorization",
        )
        self.end_headers()

    def _write_json(self, data, status=200):
        self._set_headers(status)
        body = json.dumps(
            data,
            allow_nan=False,
            default=self._json_default,
        ).encode("utf-8")
        self.wfile.write(body)

    @staticmethod
    def _json_default(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        if hasattr(value, "item"):
            return value.item()
        return str(value)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length.") from error
        if length < 0 or length > 1024 * 1024:
            raise ValueError("Request body exceeds the allowed size.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def _user(self):
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return self.state.identity_store.authenticate(token)

    def _require_user(self):
        user = self._user()
        if user is None:
            self._write_json({"error": "Authentication required."}, 401)
        return user

    @staticmethod
    def _symbol_from(payload, query, default="EUR/USD"):
        symbol = payload.get("symbol") or query.get("symbol", [default])[0]
        if symbol not in PAIRS:
            raise ValueError(f"Unsupported Forex pair: {symbol}")
        return symbol

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/health":
            self._write_json({
                "status": "online",
                "market_data_mode": self.state.data_client.mode,
                "execution_mode": "paper",
                "live_execution_enabled": LIVE_ORDER_SUBMISSION_ENABLED,
            })
            return

        user = self._require_user()
        if user is None:
            return

        if path in {"/", "/api/status"}:
            requested_symbol = query.get("symbol", ["EUR/USD"])[0]
            if requested_symbol not in PAIRS:
                requested_symbol = "EUR/USD"
            account = self.state.account_for(user)
            with self.state.lock, account.lock:
                prices = {
                    symbol: data["current_price"]
                    for symbol, data in self.state.market_data.items()
                    if data["current_price"] > 0
                }
                summary = account.portfolio.get_summary(prices)
                markets = {
                    symbol: self.state.get_pair_payload(symbol)
                    for symbol in PAIRS
                }
                selected = markets[requested_symbol]
                mode = account.settings.get("mode", "analysis")
            self._write_json({
                "status": "online",
                "bot_active": self.state.is_running,
                "trading_mode": mode,
                "execution_mode": "paper",
                "live_execution_enabled": LIVE_ORDER_SUBMISSION_ENABLED,
                "market_data_mode": self.state.data_client.mode,
                "broker": "MT5 read-only diagnostics only; status not checked",
                "selected_symbol": requested_symbol,
                "symbol": requested_symbol,
                "current_price": selected["price"],
                "portfolio": summary,
                "ai_decision": selected["ai_decision"],
                "indicators": selected["indicators"],
                "markets": markets,
                "timestamp": time.time(),
            })
            return

        if path == "/api/markets":
            self._write_json({
                "status": "online",
                "market_data_mode": self.state.data_client.mode,
                "execution_mode": "paper",
                "markets": {
                    symbol: self.state.get_pair_payload(symbol)
                    for symbol in PAIRS
                },
                "timestamp": time.time(),
            })
            return

        if path == "/api/candles":
            try:
                symbol = self._symbol_from({}, query)
            except ValueError as error:
                self._write_json({"error": str(error)}, 400)
                return
            with self.state.lock:
                candles = (
                    self.state.market_data[symbol]["candles"]
                    .tail(50)
                    .to_dict(orient="records")
                )
            self._write_json({"symbol": symbol, "candles": candles})
            return

        if path == "/api/trades":
            account = self.state.account_for(user)
            with account.lock:
                trades = list(account.portfolio.trade_history)
            self._write_json({"trades": trades})
            return

        if path == "/api/broker/status":
            adapter = MT5ReadOnlyAdapter()
            try:
                status = adapter.connect()
                if not status.get("connected"):
                    self._write_json({
                        "connected": False,
                        "live_execution_enabled": False,
                        "reason": status.get("reason", "MT5 is unavailable."),
                    }, 503)
                    return
                self._write_json({
                    "connected": True,
                    "server": status.get("server"),
                    "currency": status.get("currency"),
                    "live_execution_enabled": False,
                    "message": (
                        "MT5 account is linked for read-only diagnostics. "
                        "Order submission remains disabled."
                    ),
                })
            except RuntimeError as error:
                logger.warning("Read-only MT5 check failed: %s", error)
                self._write_json({
                    "connected": False,
                    "live_execution_enabled": False,
                    "reason": str(error),
                }, 503)
            finally:
                adapter.close()
            return

        self._write_json({"error": "Not found."}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            payload = self._read_json()
        except ValueError as error:
            self._write_json({"error": str(error)}, 400)
            return

        if path in {"/api/auth/register", "/api/auth/login"}:
            try:
                if path.endswith("/register"):
                    result = self.state.identity_store.register(
                        payload.get("email"),
                        payload.get("password"),
                    )
                else:
                    result = self.state.identity_store.login(
                        payload.get("email"),
                        payload.get("password"),
                    )
                self._write_json(result)
            except ValueError as error:
                self._write_json({"error": str(error)}, 401)
            return

        user = self._require_user()
        if user is None:
            return

        if path == "/api/auth/logout":
            header = self.headers.get("Authorization", "")
            token = header.partition(" ")[2]
            self.state.identity_store.revoke(token)
            self._write_json({"status": "ok"})
            return

        if path == "/api/mode":
            mode = payload.get("mode")
            if mode not in {"analysis", "assisted"}:
                self._write_json({
                    "error": "mode must be analysis or assisted."
                }, 400)
                return
            account = self.state.account_for(user)
            with account.lock:
                account.settings["mode"] = mode
                account.persist()
            self._write_json({
                "mode": mode,
                "execution_mode": "paper",
                "live_execution_enabled": LIVE_ORDER_SUBMISSION_ENABLED,
            })
            return

        if path == "/api/analyze":
            try:
                symbol = self._symbol_from(payload, query)
                self.state.refresh_market_data(symbol)
                result = self.state.analyze(symbol)
            except ValueError as error:
                self._write_json({"error": str(error)}, 400)
                return
            except (
                RuntimeError,
                OSError,
                requests.exceptions.RequestException,
            ) as error:
                logger.warning("Analysis unavailable for %s: %s", symbol, error)
                self._write_json({"error": str(error)}, 503)
                return
            self._write_json({
                "status": "success",
                "symbol": symbol,
                "trading_mode": self.state.account_for(user).settings.get(
                    "mode", "analysis"
                ),
                "execution_mode": "paper",
                "ai_decision": result["decision"],
                "analysis": result,
            })
            return

        if path == "/api/smc/analyze":
            try:
                symbol = self._symbol_from(payload, query)
                config = payload.get("config", {})
                report = self.state.analyze_smc(symbol, config)
            except ValueError as error:
                self._write_json({"error": str(error)}, 400)
                return
            except (
                RuntimeError,
                OSError,
                requests.exceptions.RequestException,
            ) as error:
                logger.warning("SMC analysis unavailable: %s", error)
                self._write_json({"error": str(error)}, 503)
                return
            self._write_json(report)
            return

        if path == "/api/trade/manual":
            try:
                symbol = self._symbol_from(payload, query)
                result = self.state.create_manual_paper_order(
                    user=user,
                    symbol=symbol,
                    side=str(payload.get("side", "")).upper(),
                    stop_loss=payload.get("stop_loss_price"),
                    take_profit=payload.get("take_profit_price"),
                    confirmation=payload.get("confirm"),
                    idempotency_key=payload.get("idempotency_key"),
                )
            except ValueError as error:
                self._write_json({"error": str(error)}, 400)
                return
            self._write_json(result)
            return

        if path == "/api/risk/reset":
            account = self.state.account_for(user)
            with account.lock:
                result = account.portfolio.reset_consecutive_loss_lockout(
                    confirmed=payload.get("confirm") is True
                )
                if result.get("status") == "reset":
                    account.persist()
            status = 200 if result.get("status") == "reset" else 400
            self._write_json(result, status)
            return

        if path == "/api/bot/toggle":
            self.state.is_running = not self.state.is_running
            self._write_json({
                "bot_active": self.state.is_running,
                "execution_mode": "paper",
                "live_execution_enabled": LIVE_ORDER_SUBMISSION_ENABLED,
            })
            return

        self._write_json({"error": "Not found."}, 404)


def run_server(port=None, host=None, bot_state=None):
    bot_state = bot_state or state or BotState()
    port = int(
        port
        if port is not None
        else os.getenv("BOT_PORT") or os.getenv("PORT", "8080")
    )
    host = host or os.getenv(
        "BOT_BIND_HOST",
        "0.0.0.0" if os.getenv("PORT") or os.getenv("RENDER") else "127.0.0.1",
    )

    class BoundRequestHandler(RequestHandler):
        state = bot_state

    httpd = ThreadingHTTPServer((host, port), BoundRequestHandler)
    thread = threading.Thread(
        target=bot_state.market_loop,
        name="market-data-loop",
        daemon=True,
    )
    thread.start()
    logger.info(
        "Forex analysis server listening on %s:%s; paper-only execution",
        host,
        port,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server shutting down.")
    finally:
        bot_state._stop_event.set()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


state = None


if __name__ == "__main__":
    selected_port = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run_server(port=selected_port)
