"""Analysis-only SMC evidence extraction; this module never emits orders."""

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class SMCConfig:
    swing_left: Optional[int] = None
    swing_right: Optional[int] = None
    equal_level_tolerance: Optional[float] = None
    sweep_lookback: Optional[int] = None
    displacement_atr_multiple: Optional[float] = None
    fvg_minimum_atr: Optional[float] = None
    order_block_lookback: Optional[int] = None
    swing_lookback: Optional[int] = None
    atr_period: int = 14

    def missing(self):
        return [
            name
            for name, value in self.__dict__.items()
            if value is None
        ]


class SMCAnalyzer:
    TIMEFRAMES = ("H4", "H1", "M15", "M5")

    def __init__(self, config: Optional[SMCConfig] = None):
        self.config = config or SMCConfig()
        for field in (
            "swing_left",
            "swing_right",
            "sweep_lookback",
            "order_block_lookback",
            "swing_lookback",
            "atr_period",
        ):
            value = getattr(self.config, field)
            if value is not None and value < 1:
                raise ValueError(f"{field} must be a positive integer.")
        for field in (
            "equal_level_tolerance",
            "displacement_atr_multiple",
            "fvg_minimum_atr",
        ):
            value = getattr(self.config, field)
            if value is not None and value <= 0:
                raise ValueError(f"{field} must be positive.")
        if (self.config.swing_left is None) != (
            self.config.swing_right is None
        ):
            raise ValueError("swing_left and swing_right must be configured together.")

    @staticmethod
    def _time(row):
        value = row.get("datetime", row.get("time"))
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    def _swings(self, candles):
        left, right = self.config.swing_left, self.config.swing_right
        if not left or not right or len(candles) < left + right + 1:
            return [], []

        highs = []
        lows = []
        for index in range(left, len(candles) - right):
            high = float(candles["high"].iloc[index])
            low = float(candles["low"].iloc[index])
            window_highs = candles["high"].iloc[index-left:index+right+1]
            window_lows = candles["low"].iloc[index-left:index+right+1]
            if high == float(window_highs.max()) and (
                int((window_highs == high).sum()) == 1
            ):
                highs.append({
                    "index": index,
                    "price": high,
                    "time": self._time(candles.iloc[index]),
                })
            if low == float(window_lows.min()) and (
                int((window_lows == low).sum()) == 1
            ):
                lows.append({
                    "index": index,
                    "price": low,
                    "time": self._time(candles.iloc[index]),
                })
        return highs, lows

    def _timeframe(self, timeframe, candles):
        required = {"open", "high", "low", "close"}
        missing_columns = sorted(required.difference(candles.columns))
        if missing_columns:
            return {
                "timeframe": timeframe,
                "status": "invalid_data",
                "missing_columns": missing_columns,
                "evidence": [],
            }

        candles = candles.dropna(subset=list(required)).reset_index(drop=True)
        config_missing = self.config.missing()
        if len(candles) < 3:
            return {
                "timeframe": timeframe,
                "status": "insufficient_data",
                "candle_count": len(candles),
                "evidence": [],
            }

        highs, lows = self._swings(candles)
        evidence = []
        if self.config.swing_left and self.config.swing_right:
            evidence.extend(
                {"type": "swing_high", **item} for item in highs[-5:]
            )
            evidence.extend(
                {"type": "swing_low", **item} for item in lows[-5:]
            )
            close = float(candles["close"].iloc[-1])
            last_high = next((item for item in reversed(highs)
                              if item["index"] < len(candles) - 1), None)
            last_low = next((item for item in reversed(lows)
                             if item["index"] < len(candles) - 1), None)
            prior_high = next(
                (item for item in reversed(highs)
                 if last_high and item["index"] < last_high["index"]),
                None,
            )
            prior_low = next(
                (item for item in reversed(lows)
                 if last_low and item["index"] < last_low["index"]),
                None,
            )
            prior_direction = (
                "bullish"
                if last_high and prior_high and last_low and prior_low
                and last_high["price"] > prior_high["price"]
                and last_low["price"] > prior_low["price"]
                else "bearish"
                if last_high and prior_high and last_low and prior_low
                and last_high["price"] < prior_high["price"]
                and last_low["price"] < prior_low["price"]
                else "unknown"
            )
            if timeframe in {"H4", "H1"} and prior_direction != "unknown":
                evidence.append({
                    "type": "directional_bias",
                    "direction": prior_direction,
                    "basis": "sequence of confirmed swing highs and lows",
                    "latest_swing_high": last_high,
                    "prior_swing_high": prior_high,
                    "latest_swing_low": last_low,
                    "prior_swing_low": prior_low,
                })
            if last_high and close > last_high["price"]:
                direction = "bullish"
                evidence.append({
                    "type": "structure_break",
                    "direction": direction,
                    "level": last_high["price"],
                    "level_time": last_high["time"],
                    "observed_close": close,
                    "time": self._time(candles.iloc[-1]),
                    "classification": (
                        "BOS" if prior_direction == direction
                        else "CHoCH" if prior_direction != "unknown"
                        else "unclassified_prior_structure"
                    ),
                })
            elif last_low and close < last_low["price"]:
                direction = "bearish"
                evidence.append({
                    "type": "structure_break",
                    "direction": direction,
                    "level": last_low["price"],
                    "level_time": last_low["time"],
                    "observed_close": close,
                    "time": self._time(candles.iloc[-1]),
                    "classification": (
                        "BOS" if prior_direction == direction
                        else "CHoCH" if prior_direction != "unknown"
                        else "unclassified_prior_structure"
                    ),
                })

        if self.config.equal_level_tolerance is not None:
            tolerance = self.config.equal_level_tolerance
            for name, levels in (("equal_highs", highs), ("equal_lows", lows)):
                for first, second in zip(levels, levels[1:]):
                    if abs(first["price"] - second["price"]) <= tolerance:
                        evidence.append({
                            "type": name,
                            "first": first,
                            "second": second,
                            "tolerance": tolerance,
                        })

        if self.config.sweep_lookback and highs and lows:
            start = max(0, len(candles) - self.config.sweep_lookback)
            for index in range(start, len(candles)):
                high = float(candles["high"].iloc[index])
                low = float(candles["low"].iloc[index])
                close = float(candles["close"].iloc[index])
                available_highs = [
                    item for item in highs if item["index"] < index
                ]
                available_lows = [
                    item for item in lows if item["index"] < index
                ]
                previous_high = available_highs[-1] if available_highs else None
                previous_low = available_lows[-1] if available_lows else None
                if previous_high and high > previous_high["price"] and close <= previous_high["price"]:
                    evidence.append({
                        "type": "buy_side_liquidity_sweep",
                        "level": previous_high["price"],
                        "time": self._time(candles.iloc[index]),
                        "close_back_below_level": True,
                    })
                if previous_low and low < previous_low["price"] and close >= previous_low["price"]:
                    evidence.append({
                        "type": "sell_side_liquidity_sweep",
                        "level": previous_low["price"],
                        "time": self._time(candles.iloc[index]),
                        "close_back_above_level": True,
                    })

        if (
            self.config.displacement_atr_multiple is not None
            or self.config.fvg_minimum_atr is not None
        ):
            previous_close = candles["close"].shift(1)
            true_range = pd.concat(
                [
                    candles["high"] - candles["low"],
                    (candles["high"] - previous_close).abs(),
                    (candles["low"] - previous_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = true_range.rolling(self.config.atr_period).mean()
            body = candles["close"] - candles["open"]
            displacements = []
            if self.config.displacement_atr_multiple is not None:
                for index in range(len(candles)):
                    average_range = atr.iloc[index]
                    if pd.isna(average_range) or average_range <= 0:
                        continue
                    if abs(float(body.iloc[index])) >= (
                        self.config.displacement_atr_multiple * average_range
                    ):
                        direction = "bullish" if body.iloc[index] > 0 else "bearish"
                        item = {
                            "index": index,
                            "direction": direction,
                            "body": float(abs(body.iloc[index])),
                            "atr": float(average_range),
                            "multiple": float(abs(body.iloc[index]) / average_range),
                            "time": self._time(candles.iloc[index]),
                        }
                        evidence.append({"type": "displacement", **item})
                        displacements.append(item)

            if self.config.fvg_minimum_atr is not None:
                for index in range(2, len(candles)):
                    average_range = atr.iloc[index]
                    if pd.isna(average_range) or average_range <= 0:
                        continue
                    first = candles.iloc[index - 2]
                    third = candles.iloc[index]
                    bull_gap = float(third["low"]) - float(first["high"])
                    bear_gap = float(first["low"]) - float(third["high"])
                    if bull_gap > 0 and bull_gap >= (
                        self.config.fvg_minimum_atr * average_range
                    ):
                        evidence.append({
                            "type": "fair_value_gap",
                            "direction": "bullish",
                            "zone_low": float(first["high"]),
                            "zone_high": float(third["low"]),
                            "size": bull_gap,
                            "atr_multiple": bull_gap / float(average_range),
                            "formed_at": self._time(third),
                        })
                    elif bear_gap > 0 and bear_gap >= (
                        self.config.fvg_minimum_atr * average_range
                    ):
                        evidence.append({
                            "type": "fair_value_gap",
                            "direction": "bearish",
                            "zone_low": float(third["high"]),
                            "zone_high": float(first["low"]),
                            "size": bear_gap,
                            "atr_multiple": bear_gap / float(average_range),
                            "formed_at": self._time(third),
                        })

            if (
                self.config.order_block_lookback
                and self.config.displacement_atr_multiple is not None
            ):
                for impulse in displacements:
                    start = max(
                        0,
                        impulse["index"] - self.config.order_block_lookback,
                    )
                    for index in range(impulse["index"] - 1, start - 1, -1):
                        candle = candles.iloc[index]
                        candle_direction = (
                            "bullish"
                            if candle["close"] > candle["open"]
                            else "bearish"
                            if candle["close"] < candle["open"]
                            else "neutral"
                        )
                        if candle_direction != impulse["direction"] and candle_direction != "neutral":
                            evidence.append({
                                "type": "order_block_candidate",
                                "direction": impulse["direction"],
                                "zone_low": float(candle["low"]),
                                "zone_high": float(candle["high"]),
                                "source_candle_time": self._time(candle),
                                "following_displacement_time": impulse["time"],
                                "validity": (
                                    "candidate_only; mitigation and "
                                    "invalidation rules are unconfigured"
                                ),
                            })
                            break

            if timeframe == "M5" and self.config.swing_lookback:
                recent_breaks = [
                    event for event in evidence
                    if event["type"] == "structure_break"
                    and len(candles) - self.config.swing_lookback
                    <= next(
                        (
                            index for index, row in candles.iterrows()
                            if self._time(row) == event["time"]
                        ),
                        -1,
                    )
                ]
                recent_displacements = {
                    item["time"]: item["direction"] for item in displacements
                }
                for event in recent_breaks:
                    if recent_displacements.get(event["time"]) == event["direction"]:
                        evidence.append({
                            "type": "market_structure_shift_candidate",
                            "direction": event["direction"],
                            "time": event["time"],
                            "structure_break": event,
                            "displacement_confirmed": True,
                        })

        return {
            "timeframe": timeframe,
            "status": "evidence_available" if evidence else (
                "thresholds_unconfigured" if config_missing else "no_evidence_detected"
            ),
            "candle_count": len(candles),
            "unconfigured_parameters": config_missing,
            "evidence": evidence,
        }

    def analyze(self, symbol, candles_by_timeframe):
        """Return descriptive evidence; never infer a trade or probability."""
        results = {
            timeframe: self._timeframe(
                timeframe,
                candles_by_timeframe[timeframe],
            ) if timeframe in candles_by_timeframe else {
                "timeframe": timeframe,
                "status": "data_unavailable",
                "evidence": [],
            }
            for timeframe in self.TIMEFRAMES
        }
        return {
            "symbol": symbol,
            "status": "analysis_only",
            "tradable": False,
            "setup": None,
            "reason": (
                "SMC thresholds are not fully approved; findings are "
                "descriptive and cannot be used as executable signals."
            ),
            "timeframes": results,
        }
