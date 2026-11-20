"""
Forex Portfolio and Paper Trading Manager.

This module supports both LONG (BUY) and SHORT (SELL) Forex positions.

It is paper trading only. No real broker orders are sent.

The risk engine is deterministic:
- Maximum risk per trade
- Maximum allocation per trade
- Maximum simultaneous positions
- Daily loss protection
- Maximum drawdown protection

IMPORTANT:
The current P&L calculation is still a simplified price-movement model.
It is NOT yet a broker-accurate Forex pip/lot/account-currency model.
"""

from datetime import datetime, timezone
import math


class PortfolioManager:
    def __init__(
        self,
        initial_balance: float = 10000.0,
        max_risk_per_trade_pct: float = 0.0025,
        max_allocation_per_trade_pct: float = 0.05,
        max_daily_loss_pct: float = 0.005,
        max_drawdown_pct: float = 0.10,
        max_open_positions: int = 2,
        fee_rate: float = 0.001,
        loss_cooldown_minutes: int = 30,
        max_daily_entries: int = 5,
        entry_cooldown_seconds: int = 60,
    ):
        self.initial_balance = initial_balance
        self.cash = initial_balance

        # symbol -> position
        self.positions = {}

        self.trade_history = []

        # Deterministic risk controls.
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_allocation_per_trade_pct = (
            max_allocation_per_trade_pct
        )
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_drawdown_pct = max_drawdown_pct
        self.max_open_positions = max_open_positions
        self.max_daily_entries = max(1, int(max_daily_entries))
        self.entry_cooldown_seconds = max(0, int(entry_cooldown_seconds))

        self.fee_rate = fee_rate

        # Track the equity high-water mark for drawdown protection.
        self.peak_equity = initial_balance

        # Track the UTC date used for daily loss protection.
        self.risk_day = self._today_utc()

        # Realized P&L accumulated during the current UTC day.
        self.daily_realized_pnl = 0.0
        self.consecutive_losses = 0
        self.loss_cooldown_minutes = max(0, int(loss_cooldown_minutes))
        self.last_loss_time = None
        self.daily_start_equity = initial_balance
        self.last_entry_time = {}

    def _now(self):
        """Return a timezone-aware UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def _today_utc(self):
        """Return today's UTC date as YYYY-MM-DD."""
        return datetime.now(timezone.utc).date().isoformat()

    def _reset_daily_risk_if_needed(self, equity):
        """Reset daily realized P&L when a new UTC day begins."""
        today = self._today_utc()

        if today != self.risk_day:
            self.risk_day = today
            self.daily_realized_pnl = 0.0
            self.daily_start_equity = equity

    def _update_peak_equity(self, equity: float):
        """Update the account equity high-water mark."""
        if equity > self.peak_equity:
            self.peak_equity = equity

    def _risk_status(self, current_prices: dict) -> dict:
        """
        Calculate deterministic account-level risk status.
        """

        equity = self.get_equity(current_prices)
        self._reset_daily_risk_if_needed(equity)

        self._update_peak_equity(equity)

        daily_loss_limit = self.daily_start_equity * self.max_daily_loss_pct

        drawdown_limit = (
            self.peak_equity
            * self.max_drawdown_pct
        )

        daily_equity_pnl = equity - self.daily_start_equity
        daily_loss_exceeded = daily_equity_pnl <= -daily_loss_limit
        daily_entries = sum(
            trade.get("action") == "OPEN"
            and str(trade.get("time", "")).startswith(self.risk_day)
            for trade in self.trade_history
        )

        drawdown_exceeded = (
            equity <= self.peak_equity - drawdown_limit
        )

        return {
            "equity": round(equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "daily_realized_pnl": round(
                self.daily_realized_pnl,
                2,
            ),
            "daily_equity_pnl": round(daily_equity_pnl, 2),
            "daily_start_equity": round(self.daily_start_equity, 2),
            "daily_loss_limit": round(
                daily_loss_limit,
                2,
            ),
            "drawdown_limit": round(
                drawdown_limit,
                2,
            ),
            "daily_loss_exceeded": daily_loss_exceeded,
            "daily_entries": daily_entries,
            "max_daily_entries": self.max_daily_entries,
            "entry_cooldown_seconds": self.entry_cooldown_seconds,
            "daily_entry_limit_exceeded": daily_entries >= self.max_daily_entries,
            "drawdown_exceeded": drawdown_exceeded,
            "consecutive_losses": self.consecutive_losses,
            "consecutive_loss_limit": 2,
            "consecutive_loss_lockout": self.consecutive_losses >= 2,
            "loss_cooldown_minutes": self.loss_cooldown_minutes,
            "loss_cooldown_active": self._loss_cooldown_active(),
        }

    def _loss_cooldown_active(self):
        if self.last_loss_time is None or self.loss_cooldown_minutes == 0:
            return False
        elapsed = (datetime.now(timezone.utc) - self.last_loss_time).total_seconds()
        return elapsed < self.loss_cooldown_minutes * 60

    def reset_consecutive_loss_lockout(self, confirmed: bool) -> dict:
        """Require an explicit confirmation to clear the loss-streak lock."""
        if not confirmed:
            return {
                "status": "rejected",
                "reason": "Explicit confirmation is required.",
            }
        previous_losses = self.consecutive_losses
        self.consecutive_losses = 0
        return {
            "status": "reset",
            "previous_consecutive_losses": previous_losses,
            "message": (
                "Loss-streak lockout reset. Daily-loss and drawdown "
                "limits remain in force."
            ),
        }

    def export_state(self) -> dict:
        return {
            "initial_balance": self.initial_balance,
            "cash": self.cash,
            "positions": self.positions,
            "trade_history": self.trade_history,
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_allocation_per_trade_pct": self.max_allocation_per_trade_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_open_positions": self.max_open_positions,
            "fee_rate": self.fee_rate,
            "peak_equity": self.peak_equity,
            "risk_day": self.risk_day,
            "daily_realized_pnl": self.daily_realized_pnl,
            "consecutive_losses": self.consecutive_losses,
            "loss_cooldown_minutes": self.loss_cooldown_minutes,
            "max_daily_entries": self.max_daily_entries,
            "last_loss_time": (
                self.last_loss_time.isoformat()
                if self.last_loss_time else None
            ),
            "daily_start_equity": self.daily_start_equity,
            "last_entry_time": {
                symbol: value.isoformat()
                for symbol, value in self.last_entry_time.items()
            },
        }

    @classmethod
    def from_state(cls, value):
        allowed = {
            "initial_balance",
            "max_risk_per_trade_pct",
            "max_allocation_per_trade_pct",
            "max_daily_loss_pct",
            "max_drawdown_pct",
            "max_open_positions",
            "fee_rate",
            "loss_cooldown_minutes",
            "max_daily_entries",
            "entry_cooldown_seconds",
        }
        portfolio = cls(**{
            key: value[key] for key in allowed if key in value
        })
        portfolio.cash = float(value.get("cash", portfolio.initial_balance))
        portfolio.positions = value.get("positions", {})
        portfolio.trade_history = value.get("trade_history", [])
        portfolio.peak_equity = float(
            value.get("peak_equity", portfolio.initial_balance)
        )
        portfolio.risk_day = value.get("risk_day", portfolio.risk_day)
        portfolio.daily_realized_pnl = float(
            value.get("daily_realized_pnl", 0.0)
        )
        portfolio.consecutive_losses = int(
            value.get("consecutive_losses", 0)
        )
        portfolio.daily_start_equity = float(
            value.get("daily_start_equity", portfolio.initial_balance)
        )
        loss_time = value.get("last_loss_time")
        portfolio.last_loss_time = (
            datetime.fromisoformat(loss_time) if loss_time else None
        )
        portfolio.last_entry_time = {
            symbol: datetime.fromisoformat(timestamp)
            for symbol, timestamp in value.get("last_entry_time", {}).items()
        }
        return portfolio

    @staticmethod
    def _currencies(symbol: str) -> set:
        parts = symbol.split("/")
        return set(parts) if len(parts) == 2 else set()

    def get_equity(self, current_prices: dict) -> float:
        """
        Calculate simulated account equity.

        Positions are marked to market using price movement.

        This remains a simplified paper-trading calculation and is
        not yet a broker-accurate Forex P&L engine.
        """

        equity = self.cash

        for symbol, position in self.positions.items():

            current_price = current_prices.get(
                symbol,
                position["entry_price"],
            )

            entry_price = position["entry_price"]
            invested_usd = position["invested_usd"]
            direction = position["direction"]

            if direction == "LONG":
                price_change_pct = (
                    (current_price - entry_price)
                    / entry_price
                )
            else:
                price_change_pct = (
                    (entry_price - current_price)
                    / entry_price
                )

            unrealized_pnl = (
                invested_usd * price_change_pct
            )

            equity += invested_usd + unrealized_pnl

        return round(equity, 2)

    def execute_signal(
        self,
        symbol: str,
        signal_data: dict,
        current_price: float,
    ) -> dict:
        """
        Execute BUY, SELL or HOLD in paper trading.

        BUY opens a LONG position.
        SELL opens a SHORT position.

        Risk controls are deterministic and cannot be overridden
        by Gemini.
        """

        signal = str(
            signal_data.get("signal", "HOLD")
        ).upper()

        try:
            confidence = float(
                signal_data.get("confidence", 0.0)
            )
        except (TypeError, ValueError):
            confidence = 0.0
        if not math.isfinite(confidence):
            confidence = 0.0

        # --------------------------------------------------
        # Basic signal validation
        # --------------------------------------------------

        if signal == "HOLD":
            return {
                "status": "skipped",
                "reason": "Signal is HOLD",
            }

        if signal not in {"BUY", "SELL"}:
            return {
                "status": "skipped",
                "reason": f"Invalid signal: {signal}",
            }

        try:
            current_price = float(current_price)
        except (TypeError, ValueError):
            current_price = 0.0

        if not math.isfinite(current_price) or current_price <= 0:
            return {
                "status": "blocked",
                "reason": "Invalid current price",
            }

        # Confidence gate.
        if confidence < 0.65:
            return {
                "status": "skipped",
                "reason": (
                    f"Signal is {signal} with "
                    f"confidence {confidence:.2f}"
                ),
            }

        requested_direction = (
            "LONG" if signal == "BUY" else "SHORT"
        )

        # --------------------------------------------------
        # Existing position handling
        # --------------------------------------------------

        if symbol in self.positions:

            existing = self.positions[symbol]

            if existing["direction"] == requested_direction:
                return {
                    "status": "skipped",
                    "reason": (
                        f"Already holding {requested_direction} "
                        f"position"
                    ),
                }

            # Opposite signal closes current position first.
            close_result = self._close_position(
                symbol=symbol,
                current_price=current_price,
                rationale=signal_data.get(
                    "rationale",
                    "Opposite signal",
                ),
            )

            if close_result["status"] != "executed":
                return close_result

        # --------------------------------------------------
        # Account-level risk protection
        # --------------------------------------------------

        risk_status = self._risk_status({
            symbol: current_price,
        })

        if risk_status["daily_loss_exceeded"]:
            return {
                "status": "blocked",
                "reason": (
                    "Daily loss limit reached. "
                    "New trades are blocked."
                ),
                "risk": risk_status,
            }

        if risk_status["daily_entry_limit_exceeded"]:
            return {
                "status": "blocked",
                "reason": (
                    "Daily entry limit reached. New entries are suspended "
                    "until the next UTC risk day."
                ),
                "risk": risk_status,
            }

        if risk_status["drawdown_exceeded"]:
            return {
                "status": "blocked",
                "reason": (
                    "Maximum drawdown reached. "
                    "New trades are blocked."
                ),
                "risk": risk_status,
            }

        if risk_status["consecutive_loss_lockout"]:
            return {
                "status": "blocked",
                "reason": (
                    "Two consecutive losing trades triggered a lockout. "
                    "A deliberate risk reset is required."
                ),
                "risk": risk_status,
            }

        if risk_status["loss_cooldown_active"]:
            remaining = max(
                1,
                int(
                    self.loss_cooldown_minutes
                    - (
                        datetime.now(timezone.utc) - self.last_loss_time
                    ).total_seconds() // 60
                ),
            )
            return {
                "status": "blocked",
                "reason": (
                    f"Loss cooldown active for approximately {remaining} "
                    "more minute(s)."
                ),
                "risk": risk_status,
            }

        # Maximum simultaneous positions.
        if (
            symbol not in self.positions
            and len(self.positions)
            >= self.max_open_positions
        ):
            return {
                "status": "blocked",
                "reason": (
                    "Maximum simultaneous positions reached."
                ),
            }

        requested_currencies = self._currencies(symbol)
        for open_symbol in self.positions:
            if open_symbol != symbol and requested_currencies.intersection(
                self._currencies(open_symbol)
            ):
                return {
                    "status": "blocked",
                    "reason": (
                        f"Correlated currency exposure with {open_symbol} "
                        "is not allowed in the local paper risk profile."
                    ),
                }

        previous_entry = self.last_entry_time.get(symbol)
        if previous_entry is not None and self.entry_cooldown_seconds > 0:
            elapsed = (
                datetime.now(timezone.utc) - previous_entry
            ).total_seconds()
            if elapsed < self.entry_cooldown_seconds:
                return {
                    "status": "blocked",
                    "reason": (
                        "A fresh confirmation is required; repeated entries "
                        "on this pair are limited to one per minute."
                    ),
                }

        # --------------------------------------------------
        # Validate entry
        # --------------------------------------------------

        # --------------------------------------------------
        # Validate stop loss and take profit
        # --------------------------------------------------

        try:
            stop_loss = float(
                signal_data.get(
                    "stop_loss_price",
                    0,
                )
            )
        except (TypeError, ValueError):
            stop_loss = 0.0

        try:
            take_profit = float(
                signal_data.get(
                    "take_profit_price",
                    0,
                )
            )
        except (TypeError, ValueError):
            take_profit = 0.0

        if (
            not math.isfinite(stop_loss)
            or not math.isfinite(take_profit)
            or stop_loss <= 0
            or take_profit <= 0
        ):
            return {
                "status": "blocked",
                "reason": (
                    "Valid stop-loss and take-profit "
                    "prices are required."
                ),
            }

        # Directional safety checks.
        if requested_direction == "LONG":

            if stop_loss >= current_price:
                return {
                    "status": "blocked",
                    "reason": (
                        "LONG trade requires stop loss "
                        "below entry price."
                    ),
                }

            if take_profit <= current_price:
                return {
                    "status": "blocked",
                    "reason": (
                        "LONG trade requires take profit "
                        "above entry price."
                    ),
                }

        else:

            if stop_loss <= current_price:
                return {
                    "status": "blocked",
                    "reason": (
                        "SHORT trade requires stop loss "
                        "above entry price."
                    ),
                }

            if take_profit >= current_price:
                return {
                    "status": "blocked",
                    "reason": (
                        "SHORT trade requires take profit "
                        "below entry price."
                    ),
                }

        # --------------------------------------------------
        # Deterministic risk-based position sizing
        # --------------------------------------------------

        stop_distance_pct = abs(current_price - stop_loss) / current_price

        if stop_distance_pct <= 0:
            return {
                "status": "blocked",
                "reason": "Stop-loss distance is zero.",
            }

        equity = risk_status["equity"]

        risk_budget_usd = (
            equity
            * self.max_risk_per_trade_pct
        )

        # Simplified price-movement model:
        #
        # If the stop represents a 0.5% adverse move,
        # the position notional required to lose 1% of
        # account equity at the stop is approximately:
        #
        # risk budget / stop distance.
        #
        # This is NOT broker-accurate Forex lot sizing yet.
        risk_based_trade_amount = (
            risk_budget_usd
            / stop_distance_pct
        )

        # Apply the absolute allocation cap.
        allocation_cap_usd = (
            equity
            * self.max_allocation_per_trade_pct
        )

        trade_amount_usd = min(
            risk_based_trade_amount,
            allocation_cap_usd,
            self.cash,
        )

        if trade_amount_usd < 10:
            return {
                "status": "skipped",
                "reason": (
                    "Calculated trade size is below "
                    "the minimum paper-trade amount."
                ),
            }

        # --------------------------------------------------
        # Paper-trading fee
        # --------------------------------------------------

        opening_fee = (
            trade_amount_usd * self.fee_rate
        )

        total_required = (
            trade_amount_usd + opening_fee
        )

        if self.cash < total_required:
            return {
                "status": "skipped",
                "reason": (
                    "Insufficient cash for trade "
                    "and opening fee."
                ),
            }

        # Reserve capital AND opening fee.
        self.cash -= total_required

        # --------------------------------------------------
        # Create position
        # --------------------------------------------------

        position = {
            "symbol": symbol,
            "direction": requested_direction,
            "entry_price": current_price,
            "invested_usd": trade_amount_usd,
            "fee": opening_fee,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "opened_at": self._now(),
            "ai_confidence": confidence,
            "rationale": signal_data.get(
                "rationale",
                "",
            ),
            "risk_budget_usd": risk_budget_usd,
            "stop_distance_pct": stop_distance_pct,
        }

        self.positions[symbol] = position
        self.last_entry_time[symbol] = datetime.now(timezone.utc)

        record = {
            "id": len(self.trade_history) + 1,
            "time": self._now(),
            "action": "OPEN",
            "symbol": symbol,
            "type": signal,
            "direction": requested_direction,
            "price": current_price,
            "usd_value": round(
                trade_amount_usd,
                2,
            ),
            "fee": round(
                opening_fee,
                4,
            ),
            "risk_budget_usd": round(
                risk_budget_usd,
                2,
            ),
            "stop_distance_pct": round(
                stop_distance_pct * 100,
                4,
            ),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "confidence": confidence,
            "rationale": signal_data.get(
                "rationale",
                "",
            ),
        }

        self.trade_history.insert(
            0,
            record,
        )

        return {
            "status": "executed",
            "trade": record,
        }

    def _close_position(
        self,
        symbol: str,
        current_price: float,
        rationale: str,
    ) -> dict:
        """Close an existing paper Forex position."""

        if symbol not in self.positions:
            return {
                "status": "skipped",
                "reason": "No position to close",
            }

        position = self.positions.pop(symbol)

        entry_price = position["entry_price"]
        invested_usd = position["invested_usd"]
        direction = position["direction"]
        opening_fee = position.get("fee", 0.0)

        if direction == "LONG":
            price_change_pct = (
                (current_price - entry_price)
                / entry_price
            )
        else:
            price_change_pct = (
                (entry_price - current_price)
                / entry_price
            )

        gross_pnl = (
            invested_usd * price_change_pct
        )

        gross_value = (
            invested_usd + gross_pnl
        )

        closing_fee = (
            gross_value * self.fee_rate
        )

        net_pnl = (
            gross_pnl
            - opening_fee
            - closing_fee
        )

        # Return the reserved capital plus net P&L.
        self.cash += (
            invested_usd
            + net_pnl
        )

        self.daily_realized_pnl += net_pnl
        if net_pnl < 0:
            self.consecutive_losses += 1
            self.last_loss_time = datetime.now(timezone.utc)
        elif net_pnl > 0:
            self.consecutive_losses = 0

        pnl_pct = (
            (net_pnl / invested_usd) * 100
            if invested_usd
            else 0.0
        )

        record = {
            "id": len(self.trade_history) + 1,
            "time": self._now(),
            "symbol": symbol,
            "type": (
                "SELL"
                if direction == "LONG"
                else "BUY"
            ),
            "action": "CLOSE",
            "direction": direction,
            "price": current_price,
            "usd_value": round(
                gross_value,
                2,
            ),
            "opening_fee": round(
                opening_fee,
                4,
            ),
            "closing_fee": round(
                closing_fee,
                4,
            ),
            "fee": round(
                opening_fee + closing_fee,
                4,
            ),
            "realized_pnl": round(
                net_pnl,
                2,
            ),
            "realized_pnl_pct": round(
                pnl_pct,
                2,
            ),
            "rationale": rationale,
        }

        self.trade_history.insert(
            0,
            record,
        )

        return {
            "status": "executed",
            "trade": record,
        }

    def check_stop_loss_take_profit(
        self,
        symbol: str,
        current_price: float,
    ) -> dict | None:
        """
        Check SL/TP for both LONG and SHORT positions.
        """

        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        direction = position["direction"]

        stop_loss = position.get("stop_loss")
        take_profit = position.get("take_profit")

        trigger_reason = None

        if direction == "LONG":

            if (
                stop_loss
                and stop_loss > 0
                and current_price <= stop_loss
            ):
                trigger_reason = (
                    f"LONG stop loss triggered at "
                    f"{current_price:.5f} "
                    f"(SL: {stop_loss:.5f})"
                )

            elif (
                take_profit
                and take_profit > 0
                and current_price >= take_profit
            ):
                trigger_reason = (
                    f"LONG take profit triggered at "
                    f"{current_price:.5f} "
                    f"(TP: {take_profit:.5f})"
                )

        elif direction == "SHORT":

            if (
                stop_loss
                and stop_loss > 0
                and current_price >= stop_loss
            ):
                trigger_reason = (
                    f"SHORT stop loss triggered at "
                    f"{current_price:.5f} "
                    f"(SL: {stop_loss:.5f})"
                )

            elif (
                take_profit
                and take_profit > 0
                and current_price <= take_profit
            ):
                trigger_reason = (
                    f"SHORT take profit triggered at "
                    f"{current_price:.5f} "
                    f"(TP: {take_profit:.5f})"
                )

        if trigger_reason:
            return self._close_position(
                symbol=symbol,
                current_price=current_price,
                rationale=trigger_reason,
            )

        return None

    def get_summary(
        self,
        current_prices: dict,
    ) -> dict:
        """Return the current paper-trading account summary."""

        equity = self.get_equity(current_prices)

        self._update_peak_equity(equity)

        risk_status = self._risk_status(
            current_prices
        )

        total_pnl = (
            equity - self.initial_balance
        )

        total_pnl_pct = (
            total_pnl
            / self.initial_balance
            * 100
        )

        completed_trades = [
            trade
            for trade in self.trade_history
            if trade.get("action") == "CLOSE"
        ]

        wins = [
            trade
            for trade in completed_trades
            if trade.get("realized_pnl", 0) > 0
        ]

        win_rate = (
            len(wins)
            / len(completed_trades)
            * 100
            if completed_trades
            else 0.0
        )
        realized_results = [
            float(trade.get("realized_pnl", 0.0))
            for trade in completed_trades
        ]
        gross_wins = sum(value for value in realized_results if value > 0)
        gross_losses = abs(sum(value for value in realized_results if value < 0))
        profit_factor = (
            gross_wins / gross_losses if gross_losses > 0 else None
        )

        active_positions = []

        for symbol, position in self.positions.items():

            current_price = current_prices.get(
                symbol,
                position["entry_price"],
            )

            entry_price = position["entry_price"]

            invested_usd = position["invested_usd"]

            if position["direction"] == "LONG":
                price_change_pct = (
                    (current_price - entry_price)
                    / entry_price
                )
            else:
                price_change_pct = (
                    (entry_price - current_price)
                    / entry_price
                )

            unrealized_pnl = (
                invested_usd
                * price_change_pct
            )

            current_value = (
                invested_usd
                + unrealized_pnl
            )

            active_positions.append({
                **position,
                "current_price": current_price,
                "current_value": round(
                    current_value,
                    2,
                ),
                "unrealized_pnl": round(
                    unrealized_pnl,
                    2,
                ),
                "unrealized_pnl_pct": round(
                    price_change_pct * 100,
                    2,
                ),
            })

        return {
            "initial_balance": self.initial_balance,
            "cash": round(
                self.cash,
                2,
            ),
            "equity": equity,
            "peak_equity": round(
                self.peak_equity,
                2,
            ),
            "total_pnl": round(
                total_pnl,
                2,
            ),
            "total_pnl_pct": round(
                total_pnl_pct,
                2,
            ),
            "daily_realized_pnl": round(
                self.daily_realized_pnl,
                2,
            ),
            "expectancy_per_trade": round(
                sum(realized_results) / len(realized_results),
                2,
            ) if realized_results else 0.0,
            "profit_factor": profit_factor,
            "current_drawdown_pct": round(
                max(0.0, (self.peak_equity - equity) / self.peak_equity * 100),
                2,
            ) if self.peak_equity else 0.0,
            "max_risk_per_trade_pct": (
                self.max_risk_per_trade_pct
            ),
            "max_daily_loss_pct": (
                self.max_daily_loss_pct
            ),
            "max_drawdown_pct": (
                self.max_drawdown_pct
            ),
            "max_open_positions": (
                self.max_open_positions
            ),
            "win_rate": round(
                win_rate,
                1,
            ),
            "total_trades": len(
                completed_trades
            ),
            "active_positions": active_positions,
            "recent_trades": self.trade_history[:10],
            "risk_status": risk_status,
        }