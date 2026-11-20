import os
import time
import random
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd


class ForexDataClient:
    """Client for retrieving Forex candle data from Twelve Data."""

    BASE_URL = "https://api.twelvedata.com/time_series"

    SUPPORTED_PAIRS = {
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "GBP/JPY",
    }
    INTERVAL_SECONDS = {
        "1min": 60,
        "5min": 300,
        "15min": 900,
        "1h": 3600,
        "4h": 14400,
    }

    def __init__(self, mode=None):
        self.mode = (
            mode or os.getenv("MARKET_DATA_MODE", "simulated")
        ).strip().lower()

        if self.mode not in {"simulated", "twelvedata"}:
            raise ValueError(
                "MARKET_DATA_MODE must be 'simulated' or 'twelvedata'."
            )

        self.api_key = os.getenv("TWELVE_DATA_API_KEY")

        if self.mode == "twelvedata" and not self.api_key:
            raise RuntimeError(
                "TWELVE_DATA_API_KEY is not set. "
                "Set it before selecting Twelve Data mode."
            )

        # Network resilience settings.
        self.max_retries = 3
        self.retry_delay_seconds = 2
        self._simulated_prices = {
            ("EUR/USD", "1min"): 1.0850,
            ("GBP/USD", "1min"): 1.2700,
            ("USD/JPY", "1min"): 150.00,
            ("GBP/JPY", "1min"): 190.00,
        }

    def _simulated_candles(self, symbol, outputsize):
        """Create reproducible, clearly simulated OHLC candles."""
        seconds = self.INTERVAL_SECONDS.get("1min")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        minute_seed = int(now.timestamp() // seconds)
        seed = sum(ord(char) for char in symbol) + minute_seed
        rng = random.Random(seed)
        price = self._simulated_prices[(symbol, "1min")]
        volatility = 0.012 if "JPY" in symbol else 0.00012
        rows = []

        for offset in range(outputsize):
            change = rng.gauss(0, volatility)
            open_price = price
            close_price = max(0.0001, open_price + change)
            wick = abs(rng.gauss(0, volatility * 0.35))
            rows.append({
                "datetime": now - timedelta(minutes=outputsize - offset - 1),
                "open": open_price,
                "high": max(open_price, close_price) + wick,
                "low": max(0.0001, min(open_price, close_price) - wick),
                "close": close_price,
                "volume": rng.randint(10, 100),
            })
            price = close_price

        self._simulated_prices[(symbol, "1min")] = price
        return pd.DataFrame(rows)

    def _simulated_interval_candles(self, symbol, interval, outputsize):
        seconds = self.INTERVAL_SECONDS[interval]
        base_prices = {
            "EUR/USD": 1.0850,
            "GBP/USD": 1.2700,
            "USD/JPY": 150.00,
            "GBP/JPY": 190.00,
        }
        now = datetime.now(timezone.utc)
        epoch = int(now.timestamp())
        end = datetime.fromtimestamp(
            epoch - epoch % seconds,
            timezone.utc,
        )
        seed = sum(ord(char) for char in symbol + interval) + epoch // seconds
        rng = random.Random(seed)
        key = (symbol, interval)
        price = self._simulated_prices.get(key, base_prices[symbol])
        one_minute_vol = 0.00012 if "JPY" not in symbol else 0.012
        volatility = one_minute_vol * (seconds / 60) ** 0.5
        candles = []
        for offset in range(outputsize):
            change = rng.gauss(0, volatility)
            open_price = price
            close_price = max(0.0001, open_price + change)
            wick = abs(rng.gauss(0, volatility * 0.35))
            candles.append({
                "datetime": end - timedelta(seconds=seconds * (outputsize-offset-1)),
                "open": open_price,
                "high": max(open_price, close_price) + wick,
                "low": max(0.0001, min(open_price, close_price) - wick),
                "close": close_price,
                "volume": rng.randint(10, 100),
            })
            price = close_price
        self._simulated_prices[key] = price
        return pd.DataFrame(candles)

    def get_candles(
        self,
        symbol="EUR/USD",
        interval="1min",
        outputsize=100,
    ):
        """Fetch Forex OHLC candles and return them as a pandas DataFrame."""

        if symbol not in self.SUPPORTED_PAIRS:
            raise ValueError(
                f"Unsupported Forex pair: {symbol}. "
                f"Supported pairs: {sorted(self.SUPPORTED_PAIRS)}"
            )

        if interval not in self.INTERVAL_SECONDS:
            raise ValueError(f"Unsupported candle interval: {interval}")

        if self.mode == "simulated":
            if interval != "1min":
                return self._simulated_interval_candles(
                    symbol,
                    interval,
                    outputsize,
                )
            return self._simulated_candles(symbol, outputsize)

        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": self.api_key,
        }

        last_error = None

        for attempt in range(1, self.max_retries + 1):

            try:
                response = requests.get(
                    self.BASE_URL,
                    params=params,
                    timeout=15,
                )

                response.raise_for_status()

                data = response.json()

                if data.get("status") == "error":
                    raise RuntimeError(
                        f"Twelve Data error: "
                        f"{data.get('message', 'Unknown error')}"
                    )

                values = data.get("values")

                if not values:
                    raise RuntimeError(
                        f"No candle data returned for {symbol}."
                    )

                df = pd.DataFrame(values)

                df["datetime"] = pd.to_datetime(df["datetime"])

                for column in ["open", "high", "low", "close"]:
                    df[column] = pd.to_numeric(
                        df[column],
                        errors="coerce",
                    )

                if "volume" in df.columns:
                    df["volume"] = pd.to_numeric(
                        df["volume"],
                        errors="coerce",
                    )

                df = (
                    df.sort_values("datetime")
                    .reset_index(drop=True)
                )

                return df

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as error:

                last_error = error

                if attempt < self.max_retries:
                    print(
                        f"Twelve Data connection issue "
                        f"(attempt {attempt}/{self.max_retries}). "
                        f"Retrying in {self.retry_delay_seconds}s..."
                    )

                    time.sleep(self.retry_delay_seconds)

                else:
                    print(
                        "Twelve Data connection failed after "
                        f"{self.max_retries} attempts."
                    )

            except requests.exceptions.HTTPError as error:

                last_error = error

                # HTTP errors such as 429 or 5xx may be temporary.
                status_code = (
                    error.response.status_code
                    if error.response is not None
                    else None
                )

                if (
                    status_code in {429, 500, 502, 503, 504}
                    and attempt < self.max_retries
                ):
                    print(
                        f"Twelve Data returned HTTP {status_code} "
                        f"(attempt {attempt}/{self.max_retries}). "
                        f"Retrying in {self.retry_delay_seconds}s..."
                    )

                    time.sleep(self.retry_delay_seconds)

                else:
                    raise

        raise RuntimeError(
            f"Unable to retrieve Forex data for {symbol} "
            f"after {self.max_retries} attempts."
        ) from last_error


if __name__ == "__main__":
    client = ForexDataClient()

    candles = client.get_candles(
        symbol="EUR/USD",
        interval="1min",
        outputsize=5,
    )

    print("\nEUR/USD — latest candles\n")
    print(candles.to_string(index=False))