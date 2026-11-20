import unittest

from forex_data import ForexDataClient
from indicators import compute_all_indicators


class TestForexPairs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = ForexDataClient(mode="simulated")

    def test_all_four_forex_pairs(self):
        pairs = [
            "EUR/USD",
            "GBP/USD",
            "USD/JPY",
            "GBP/JPY",
        ]

        for pair in pairs:
            with self.subTest(pair=pair):

                df = self.client.get_candles(
                    symbol=pair,
                    interval="1min",
                    outputsize=100,
                )

                # Enough candles received
                self.assertGreaterEqual(
                    len(df),
                    50,
                    f"{pair}: not enough candles",
                )

                # OHLC columns exist and contain valid numbers
                for column in ["open", "high", "low", "close"]:
                    self.assertIn(
                        column,
                        df.columns,
                        f"{pair}: missing {column}",
                    )

                    self.assertTrue(
                        df[column].notna().all(),
                        f"{pair}: {column} contains missing values",
                    )

                    self.assertTrue(
                        df[column].apply(
                            lambda x: isinstance(x, (int, float))
                        ).all(),
                        f"{pair}: {column} contains non-numeric values",
                    )

                # Candles are chronological
                self.assertTrue(
                    df["datetime"].is_monotonic_increasing,
                    f"{pair}: candles are not chronological",
                )

                # Calculate indicators
                df = compute_all_indicators(df)

                required_indicators = [
                    "ema_9",
                    "ema_21",
                    "ema_50",
                    "rsi_14",
                    "macd",
                    "macd_signal",
                    "macd_hist",
                    "bb_upper",
                    "bb_middle",
                    "bb_lower",
                    "atr_14",
                ]

                for indicator in required_indicators:
                    self.assertIn(
                        indicator,
                        df.columns,
                        f"{pair}: missing indicator {indicator}",
                    )

                # Latest RSI must be valid
                latest = df.iloc[-1]

                self.assertTrue(
                    0 <= latest["rsi_14"] <= 100,
                    f"{pair}: invalid RSI",
                )

                # ATR must be positive
                self.assertGreater(
                    latest["atr_14"],
                    0,
                    f"{pair}: ATR is not positive",
                )

                print(
                    f"\n{pair}: "
                    f"{len(df)} candles | "
                    f"Price={latest['close']} | "
                    f"RSI={latest['rsi_14']:.2f} | "
                    f"ATR={latest['atr_14']:.6f}"
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)