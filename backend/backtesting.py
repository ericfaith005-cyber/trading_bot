"""Historical, paper-only backtesting for caller-supplied strategies."""

import math

import pandas as pd

from portfolio import PortfolioManager


def _validate_candles(candles):
    if not isinstance(candles, pd.DataFrame):
        raise TypeError("candles must be a pandas DataFrame.")
    required = {"open", "high", "low", "close"}
    missing = required.difference(candles.columns)
    if missing:
        raise ValueError(f"Missing OHLC columns: {sorted(missing)}")
    if len(candles) < 2:
        raise ValueError("At least two candles are required.")

    frame = candles.copy()
    if "datetime" in frame.columns:
        frame = frame.sort_values("datetime")
    elif "time" in frame.columns:
        frame = frame.sort_values("time")
    frame = frame.reset_index(drop=True)

    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("OHLC candles must contain numeric values.")
    if not frame[["open", "high", "low", "close"]].apply(
        lambda column: column.map(math.isfinite).all()
    ).all():
        raise ValueError("OHLC candles must contain finite values.")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive.")
    if (frame["high"] < frame["low"]).any():
        raise ValueError("Candle high cannot be below candle low.")
    if (
        (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
    ):
        raise ValueError("Candle high/low must contain open and close.")
    return frame


def _bar_exit_price(position, candle):
    direction = position["direction"]
    stop = float(position["stop_loss"])
    target = float(position["take_profit"])
    bar_open = float(candle["open"])
    bar_high = float(candle["high"])
    bar_low = float(candle["low"])

    if direction == "LONG":
        if bar_open <= stop or bar_low <= stop:
            return min(bar_open, stop)
        if bar_open >= target or bar_high >= target:
            return max(bar_open, target)
    else:
        if bar_open >= stop or bar_high >= stop:
            return max(bar_open, stop)
        if bar_open <= target or bar_low <= target:
            return min(bar_open, target)
    return None


def run_backtest(
    candles,
    strategy,
    symbol="EUR/USD",
    initial_balance=10000.0,
    close_at_end=True,
    portfolio_options=None,
):
    """Run a deterministic paper backtest without broker connectivity.

    `strategy(history, symbol)` receives candles strictly before the
    current bar and returns a PortfolioManager-compatible decision.
    Entries are simulated at the current bar open. If both protective
    levels are touched within a bar, the stop is assumed to fill first.
    Forex P&L remains the simplified model used by PortfolioManager.
    """
    if not callable(strategy):
        raise TypeError("strategy must be callable.")
    frame = _validate_candles(candles)
    portfolio = PortfolioManager(
        initial_balance=float(initial_balance),
        **(portfolio_options or {}),
    )

    for index in range(1, len(frame)):
        candle = frame.iloc[index]
        current_price = float(candle["open"])

        if symbol in portfolio.positions:
            position = portfolio.positions[symbol]
            exit_price = _bar_exit_price(position, candle)
            if exit_price is not None:
                portfolio.check_stop_loss_take_profit(symbol, exit_price)

        history = frame.iloc[:index].copy()
        decision = strategy(history, symbol)
        if decision is not None:
            if not isinstance(decision, dict):
                raise TypeError("strategy must return a dict or None.")
            portfolio.execute_signal(symbol, decision, current_price)

        if symbol in portfolio.positions:
            position = portfolio.positions[symbol]
            exit_price = _bar_exit_price(position, candle)
            if exit_price is not None:
                portfolio.check_stop_loss_take_profit(symbol, exit_price)

    final_price = float(frame.iloc[-1]["close"])
    if close_at_end and symbol in portfolio.positions:
        portfolio._close_position(
            symbol,
            final_price,
            "Backtest end-of-data close.",
        )

    summary = portfolio.get_summary({symbol: final_price})
    return {
        "symbol": symbol,
        "bars": len(frame),
        "summary": summary,
        "trades": list(portfolio.trade_history),
        "open_positions": list(portfolio.positions.values()),
        "assumptions": {
            "execution": "paper simulation; entries at next bar open",
            "same_bar_stop_and_target": "stop assumed first",
            "pnl_model": "simplified PortfolioManager price-movement model",
            "broker_orders_sent": False,
        },
    }
