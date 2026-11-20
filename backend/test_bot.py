"""
Unit test and validation script for AI Trading Bot.
"""
import unittest
import pandas as pd
import numpy as np

from indicators import compute_all_indicators
from portfolio import PortfolioManager
from ai_engine import AITradingEngine

class TestTradingBot(unittest.TestCase):

    def setUp(self):
        # Create synthetic market candle data
        dates = pd.date_range("2026-01-01", periods=60, freq="1min")
        prices = np.linspace(65000, 68000, 60) + np.random.normal(0, 50, 60)
        self.df = pd.DataFrame({
            "time": dates,
            "open": prices - 10,
            "high": prices + 25,
            "low": prices - 25,
            "close": prices,
            "volume": np.random.uniform(5, 50, 60)
        })

    def test_indicators_computation(self):
        enriched = compute_all_indicators(self.df)
        self.assertIn("rsi_14", enriched.columns)
        self.assertIn("ema_9", enriched.columns)
        self.assertIn("ema_21", enriched.columns)
        self.assertIn("macd", enriched.columns)
        self.assertIn("bb_upper", enriched.columns)
        self.assertIn("atr_14", enriched.columns)
        
        # Test RSI range
        latest_rsi = enriched["rsi_14"].iloc[-1]
        self.assertTrue(0 <= latest_rsi <= 100)

    def test_portfolio_execution(self):
        pm = PortfolioManager(initial_balance=10000.0)
        
        # Test Buy execution
        buy_signal = {
            "signal": "BUY",
            "confidence": 0.85,
            "suggested_allocation_pct": 0.05,
            "stop_loss_price": 60000.0,
            "take_profit_price": 75000.0,
            "rationale": "Bullish momentum breakout"
        }
        res = pm.execute_signal("BTC/USDT", buy_signal, current_price=67000.0)
        self.assertEqual(res["status"], "executed")
        self.assertIn("BTC/USDT", pm.positions)
        self.assertLess(pm.cash, 10000.0)

        # Test Stop Loss trigger
        sl_res = pm.check_stop_loss_take_profit("BTC/USDT", current_price=59900.0)
        self.assertIsNotNone(sl_res)
        self.assertNotIn("BTC/USDT", pm.positions)
        self.assertEqual(len(pm.trade_history), 2)

    def test_ai_engine(self):
        engine = AITradingEngine()
        engine.client = None
        ind = {"rsi": 28.0, "ema_9": 67500.0, "ema_21": 67000.0, "macd_hist": 12.5, "atr": 250.0}
        result = engine.analyze_market("BTC/USDT", 67200.0, ind)
        self.assertIn("signal", result)
        self.assertIn(result["signal"], ["BUY", "SELL", "HOLD"])
        self.assertIn("confidence", result)

if __name__ == "__main__":
    unittest.main()