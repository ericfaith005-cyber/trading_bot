"""
MT5 Forex Risk & Safety Layer

READ-ONLY / PRE-TRADE CHECKS ONLY.
This module does NOT send orders.

This module:
- Reads exact Exness MT5 symbol specifications.
- Refreshes and validates live MT5 bid/ask ticks.
- Uses MT5 order_calc_profit() for broker-aware risk calculation.
- Uses MT5 order_calc_margin() for broker-aware margin checks.
- Checks minimum lot risk against the account risk budget.
- Checks spread.
- Checks stop-loss direction.
- Checks account equity and free margin.
- NEVER sends an order.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Dict, Any, Optional

import MetaTrader5 as mt5


# Human-readable bot symbols -> exact Exness MT5 symbols.
MT5_SYMBOLS = {
    "EUR/USD": "EURUSDm",
    "GBP/USD": "GBPUSDm",
    "USD/JPY": "USDJPYm",
    "GBP/JPY": "GBPJPYm",
}


class MT5RiskManager:
    def __init__(
        self,
        max_risk_pct: float = 0.01,
        max_spread_points: int = 50,
        tick_refresh_attempts: int = 5,
        tick_refresh_delay_seconds: float = 0.25,
    ):
        self.max_risk_pct = float(max_risk_pct)
        self.max_spread_points = int(max_spread_points)
        self.tick_refresh_attempts = max(1, int(tick_refresh_attempts))
        self.tick_refresh_delay_seconds = max(
            0.0, float(tick_refresh_delay_seconds)
        )

    def connect(self) -> bool:
        """Connect to the installed MT5 terminal."""
        return bool(mt5.initialize())

    def shutdown(self) -> None:
        """Close the Python MT5 connection."""
        mt5.shutdown()

    def get_mt5_symbol(self, symbol: str) -> str:
        """Convert bot symbol to the exact Exness MT5 symbol."""
        if symbol not in MT5_SYMBOLS:
            raise ValueError(
                f"Unsupported Forex pair: {symbol}"
            )

        return MT5_SYMBOLS[symbol]

    def get_symbol_info(self, symbol: str):
        """Get broker information for one Forex symbol."""
        mt5_symbol = self.get_mt5_symbol(symbol)

        if not mt5.symbol_select(mt5_symbol, True):
            raise RuntimeError(
                f"Could not select MT5 symbol: {mt5_symbol}; "
                f"error={mt5.last_error()}"
            )

        info = mt5.symbol_info(mt5_symbol)

        if info is None:
            raise RuntimeError(
                f"MT5 returned no symbol information for {mt5_symbol}; "
                f"error={mt5.last_error()}"
            )

        return info

    def get_tick(self, symbol: str):
        """
        Get a current, valid MT5 bid/ask tick.

        MT5 can occasionally return a symbol with zero bid/ask immediately
        after selection. We therefore refresh the symbol and retry briefly.

        Read-only: no order is created.
        """
        mt5_symbol = self.get_mt5_symbol(symbol)

        if not mt5.symbol_select(mt5_symbol, True):
            raise RuntimeError(
                f"Could not select MT5 symbol: {mt5_symbol}; "
                f"error={mt5.last_error()}"
            )

        last_bid = 0.0
        last_ask = 0.0

        for attempt in range(1, self.tick_refresh_attempts + 1):
            tick = mt5.symbol_info_tick(mt5_symbol)

            if tick is not None:
                last_bid = float(getattr(tick, "bid", 0.0) or 0.0)
                last_ask = float(getattr(tick, "ask", 0.0) or 0.0)

                if last_bid > 0.0 and last_ask > 0.0:
                    return tick

            # Ask MT5 for recent ticks as a refresh signal. This does not
            # place an order and can wake a newly selected/quiet symbol.
            try:
                utc_now = datetime.now(timezone.utc)
                utc_from = utc_now - timedelta(seconds=10)
                mt5.copy_ticks_from(
                    mt5_symbol,
                    utc_from,
                    10,
                    mt5.COPY_TICKS_ALL,
                )
            except Exception:
                pass

            if (
                attempt < self.tick_refresh_attempts
                and self.tick_refresh_delay_seconds > 0
            ):
                import time
                time.sleep(self.tick_refresh_delay_seconds)

        raise RuntimeError(
            f"MT5 did not provide a valid live tick for {mt5_symbol} "
            f"after {self.tick_refresh_attempts} attempts: "
            f"bid={last_bid}, ask={last_ask}, "
            f"error={mt5.last_error()}"
        )

    def get_entry_price(
        self,
        symbol: str,
        direction: str,
    ) -> float:
        """
        Get the current executable-side broker price.

        BUY  -> ask
        SELL -> bid

        Read-only.
        """
        tick = self.get_tick(symbol)

        direction = direction.upper()

        if direction == "BUY":
            return float(tick.ask)

        if direction == "SELL":
            return float(tick.bid)

        raise ValueError(
            "direction must be BUY or SELL"
        )

    def inspect_symbol(self, symbol: str) -> Dict[str, Any]:
        """
        Return broker specifications and current market data.

        No order is created.
        """
        info = self.get_symbol_info(symbol)
        tick = self.get_tick(symbol)

        spread_price = float(tick.ask) - float(tick.bid)

        return {
            "bot_symbol": symbol,
            "mt5_symbol": self.get_mt5_symbol(symbol),
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "spread_price": spread_price,
            "spread_points": int(round(
                spread_price / float(info.point)
            )),
            "digits": int(info.digits),
            "point": float(info.point),
            "volume_min": float(info.volume_min),
            "volume_max": float(info.volume_max),
            "volume_step": float(info.volume_step),
            "contract_size": float(info.trade_contract_size),
            "trade_tick_size": float(info.trade_tick_size),
            "trade_tick_value": float(info.trade_tick_value),
            "trade_tick_value_profit": float(
                info.trade_tick_value_profit
            ),
            "trade_tick_value_loss": float(
                info.trade_tick_value_loss
            ),
            "trade_mode": int(info.trade_mode),
            "trade_exemode": int(info.trade_exemode),
        }

    def validate_stop_direction(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
    ) -> bool:
        """Check that the stop-loss is on the correct side."""
        direction = direction.upper()

        if direction == "BUY":
            return stop_loss < entry_price

        if direction == "SELL":
            return stop_loss > entry_price

        return False

    def calculate_loss_at_stop(
        self,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float,
        stop_loss: float,
    ) -> float:
        """
        Calculate estimated account-currency loss at the stop
        using MT5's own profit calculation.

        This does NOT place an order.
        """
        mt5_symbol = self.get_mt5_symbol(symbol)

        direction = direction.upper()

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY

        elif direction == "SELL":
            order_type = mt5.ORDER_TYPE_SELL

        else:
            raise ValueError(
                "direction must be BUY or SELL"
            )

        profit = mt5.order_calc_profit(
            order_type,
            mt5_symbol,
            float(volume),
            float(entry_price),
            float(stop_loss),
        )

        if profit is None:
            error = mt5.last_error()

            raise RuntimeError(
                f"order_calc_profit failed: {error}"
            )

        return abs(float(profit))

    def calculate_margin_required(
        self,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float,
    ) -> float:
        """
        Calculate broker-estimated margin for a hypothetical position.

        This is read-only. No order is sent.
        """
        mt5_symbol = self.get_mt5_symbol(symbol)

        direction = direction.upper()

        if direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
        elif direction == "SELL":
            order_type = mt5.ORDER_TYPE_SELL
        else:
            raise ValueError(
                "direction must be BUY or SELL"
            )

        margin = mt5.order_calc_margin(
            order_type,
            mt5_symbol,
            float(volume),
            float(entry_price),
        )

        if margin is None:
            raise RuntimeError(
                f"order_calc_margin failed for {mt5_symbol}: "
                f"{mt5.last_error()}"
            )

        margin = float(margin)

        if margin < 0:
            raise RuntimeError(
                f"MT5 returned invalid negative margin for "
                f"{mt5_symbol}: {margin}"
            )

        return margin

    def calculate_minimum_lot_risk(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
    ) -> Dict[str, Any]:
        """
        Calculate risk and margin for the broker's minimum volume.

        No order is sent.
        """
        info = self.get_symbol_info(symbol)

        minimum_volume = float(info.volume_min)

        loss = self.calculate_loss_at_stop(
            symbol=symbol,
            direction=direction,
            volume=minimum_volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )

        margin = self.calculate_margin_required(
            symbol=symbol,
            direction=direction,
            volume=minimum_volume,
            entry_price=entry_price,
        )

        return {
            "symbol": symbol,
            "mt5_symbol": self.get_mt5_symbol(symbol),
            "minimum_volume": minimum_volume,
            "entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "estimated_loss_at_stop": loss,
            "estimated_margin_required": margin,
        }

    @staticmethod
    def _floor_to_step(
        volume: float,
        volume_min: float,
        volume_step: float,
    ) -> float:
        """Floor a volume to the broker's volume step."""
        if volume < volume_min:
            return 0.0

        volume_d = Decimal(str(volume))
        minimum_d = Decimal(str(volume_min))
        step_d = Decimal(str(volume_step))

        steps = ((volume_d - minimum_d) / step_d).to_integral_value(
            rounding=ROUND_DOWN
        )

        result = minimum_d + (steps * step_d)
        return float(result)

    def calculate_max_safe_volume(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        account_equity: Optional[float] = None,
        free_margin: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Calculate the largest broker-valid volume that satisfies BOTH:

        1. configured maximum loss at stop, and
        2. available free-margin requirement.

        This is a calculation only.
        No order is sent.
        """
        info = self.get_symbol_info(symbol)

        if account_equity is None or free_margin is None:
            account = mt5.account_info()

            if account is None:
                raise RuntimeError(
                    f"Could not read MT5 account: {mt5.last_error()}"
                )

            if account_equity is None:
                account_equity = float(account.equity)

            if free_margin is None:
                free_margin = float(account.margin_free)

        account_equity = float(account_equity)
        free_margin = float(free_margin)

        allowed_risk = account_equity * self.max_risk_pct

        minimum_volume = float(info.volume_min)
        maximum_volume = float(info.volume_max)
        volume_step = float(info.volume_step)

        if minimum_volume <= 0 or volume_step <= 0:
            raise RuntimeError(
                f"Invalid broker volume settings for "
                f"{self.get_mt5_symbol(symbol)}: "
                f"min={minimum_volume}, step={volume_step}"
            )

        minimum_lot_loss = self.calculate_loss_at_stop(
            symbol=symbol,
            direction=direction,
            volume=minimum_volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )

        minimum_lot_margin = self.calculate_margin_required(
            symbol=symbol,
            direction=direction,
            volume=minimum_volume,
            entry_price=entry_price,
        )

        if minimum_lot_loss > allowed_risk:
            return {
                "safe_volume_available": False,
                "max_safe_volume": 0.0,
                "allowed_risk": allowed_risk,
                "free_margin": free_margin,
                "minimum_volume": minimum_volume,
                "minimum_lot_loss": minimum_lot_loss,
                "minimum_lot_margin": minimum_lot_margin,
                "reason": (
                    "Broker minimum volume exceeds "
                    "the configured risk limit."
                ),
            }

        if minimum_lot_margin > free_margin:
            return {
                "safe_volume_available": False,
                "max_safe_volume": 0.0,
                "allowed_risk": allowed_risk,
                "free_margin": free_margin,
                "minimum_volume": minimum_volume,
                "minimum_lot_loss": minimum_lot_loss,
                "minimum_lot_margin": minimum_lot_margin,
                "reason": (
                    "Broker minimum volume requires more "
                    "margin than the available free margin."
                ),
            }

        # Binary-search the broker's discrete volume steps instead of
        # making thousands of order_calc_profit/order_calc_margin calls.
        max_steps = int(
            ((maximum_volume - minimum_volume) / volume_step) + 1e-9
        )

        def candidate_is_safe(candidate_volume: float) -> bool:
            candidate_loss = self.calculate_loss_at_stop(
                symbol=symbol,
                direction=direction,
                volume=candidate_volume,
                entry_price=entry_price,
                stop_loss=stop_loss,
            )

            if candidate_loss > allowed_risk:
                return False

            candidate_margin = self.calculate_margin_required(
                symbol=symbol,
                direction=direction,
                volume=candidate_volume,
                entry_price=entry_price,
            )

            return candidate_margin <= free_margin

        if not candidate_is_safe(minimum_volume):
            return {
                "safe_volume_available": False,
                "max_safe_volume": 0.0,
                "allowed_risk": allowed_risk,
                "free_margin": free_margin,
                "minimum_volume": minimum_volume,
                "minimum_lot_loss": minimum_lot_loss,
                "minimum_lot_margin": minimum_lot_margin,
                "reason": "Minimum volume failed broker safety checks.",
            }

        low = 0
        high = max_steps

        while low < high:
            mid = (low + high + 1) // 2
            candidate = minimum_volume + (mid * volume_step)
            candidate = self._floor_to_step(
                candidate,
                minimum_volume,
                volume_step,
            )

            if candidate > maximum_volume:
                candidate = maximum_volume

            if candidate_is_safe(candidate):
                low = mid
            else:
                high = mid - 1

        safe_volume = minimum_volume + (low * volume_step)
        safe_volume = min(
            maximum_volume,
            self._floor_to_step(
                safe_volume,
                minimum_volume,
                volume_step,
            ),
        )

        safe_loss = self.calculate_loss_at_stop(
            symbol=symbol,
            direction=direction,
            volume=safe_volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )

        safe_margin = self.calculate_margin_required(
            symbol=symbol,
            direction=direction,
            volume=safe_volume,
            entry_price=entry_price,
        )

        return {
            "safe_volume_available": safe_volume >= minimum_volume,
            "max_safe_volume": float(safe_volume),
            "allowed_risk": allowed_risk,
            "free_margin": free_margin,
            "minimum_volume": minimum_volume,
            "minimum_lot_loss": minimum_lot_loss,
            "minimum_lot_margin": minimum_lot_margin,
            "estimated_loss_at_safe_volume": safe_loss,
            "estimated_margin_at_safe_volume": safe_margin,
            "volume_step": volume_step,
        }


    def get_trade_readiness(
        self,
        symbol: str,
        direction: str = "BUY",
        stop_distance: float = None,
    ) -> Dict[str, Any]:
        """
        Read-only broker trade-readiness check.

        Determines whether the broker minimum volume can fit inside
        the configured risk limit using the current live MT5 quote.

        No order is created or sent.
        """

        direction = direction.upper()

        if direction not in {"BUY", "SELL"}:
            raise ValueError(
                "direction must be BUY or SELL"
            )

        if not self.connect():
            return {
                "ready": False,
                "symbol": symbol,
                "reason": "Could not connect to MT5 terminal.",
            }

        account = mt5.account_info()

        if account is None:
            return {
                "ready": False,
                "symbol": symbol,
                "reason": (
                    f"Could not read MT5 account: "
                    f"{mt5.last_error()}"
                ),
            }

        info = self.get_symbol_info(symbol)
        tick = self.get_tick(symbol)

        equity = float(account.equity)
        free_margin = float(account.margin_free)

        allowed_risk = equity * self.max_risk_pct

        if direction == "BUY":
            entry_price = float(tick.ask)
        else:
            entry_price = float(tick.bid)

        # Default diagnostic stop distance:
        # 5 pips for FX pairs quoted to 5 decimals,
        # 0.05 for JPY pairs quoted to 3 decimals.
        if stop_distance is None:
            if info.digits <= 3:
                stop_distance = 0.05
            else:
                stop_distance = 0.00050

        stop_distance = abs(float(stop_distance))

        if direction == "BUY":
            stop_loss = entry_price - stop_distance
        else:
            stop_loss = entry_price + stop_distance

        minimum_volume = float(info.volume_min)

        minimum_lot_loss = self.calculate_loss_at_stop(
            symbol=symbol,
            direction=direction,
            volume=minimum_volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
        )

        minimum_lot_margin = mt5.order_calc_margin(
            (
                mt5.ORDER_TYPE_BUY
                if direction == "BUY"
                else mt5.ORDER_TYPE_SELL
            ),
            self.get_mt5_symbol(symbol),
            minimum_volume,
            entry_price,
        )

        if minimum_lot_margin is None:
            minimum_lot_margin = None
        else:
            minimum_lot_margin = abs(float(minimum_lot_margin))

        risk_ok = minimum_lot_loss <= allowed_risk

        margin_ok = (
            minimum_lot_margin is not None
            and minimum_lot_margin <= free_margin
        )

        spread_points = int(info.spread)
        spread_ok = spread_points <= self.max_spread_points

        trade_mode_available = int(info.trade_mode) != 0

        ready = (
            equity > 0
            and free_margin >= 0
            and risk_ok
            and margin_ok
            and spread_ok
            and trade_mode_available
        )

        if not risk_ok:
            reason = (
                "NOT READY: broker minimum lot risks "
                f"${minimum_lot_loss:.2f}, while the "
                f"configured maximum risk is "
                f"${allowed_risk:.2f}."
            )
        elif not margin_ok:
            reason = (
                "NOT READY: broker minimum lot requires "
                f"${minimum_lot_margin:.2f} margin, but "
                f"only ${free_margin:.2f} is available."
            )
        elif not spread_ok:
            reason = (
                "NOT READY: current spread exceeds the "
                "configured maximum."
            )
        elif not trade_mode_available:
            reason = (
                "NOT READY: broker trading mode is unavailable."
            )
        else:
            reason = (
                "READY: broker minimum lot fits within "
                "the configured risk and margin limits."
            )

        return {
            "ready": ready,
            "symbol": symbol,
            "mt5_symbol": self.get_mt5_symbol(symbol),
            "direction": direction,
            "account_equity": equity,
            "free_margin": free_margin,
            "max_risk_pct": self.max_risk_pct,
            "allowed_risk_usd": allowed_risk,
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "spread_points": spread_points,
            "max_spread_points": self.max_spread_points,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "stop_distance": stop_distance,
            "minimum_volume": minimum_volume,
            "minimum_lot_loss": minimum_lot_loss,
            "minimum_lot_margin": minimum_lot_margin,
            "risk_ok": risk_ok,
            "margin_ok": margin_ok,
            "spread_ok": spread_ok,
            "trade_mode_available": trade_mode_available,
            "reason": reason,
        }

    def check_risk(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        account_equity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Perform deterministic broker-aware pre-trade safety checks.

        IMPORTANT:
        The supplied entry_price is retained for API compatibility, but
        the broker's CURRENT executable-side price is authoritative.

        This function NEVER sends an order.
        """
        direction = direction.upper()

        if direction not in ("BUY", "SELL"):
            raise ValueError(
                "direction must be BUY or SELL"
            )

        info = self.get_symbol_info(symbol)
        tick = self.get_tick(symbol)

        broker_entry_price = (
            float(tick.ask)
            if direction == "BUY"
            else float(tick.bid)
        )

        if account_equity is None:
            account = mt5.account_info()

            if account is None:
                raise RuntimeError(
                    f"Could not read MT5 account: "
                    f"{mt5.last_error()}"
                )

            account_equity = float(account.equity)
            free_margin = float(account.margin_free)
        else:
            account = mt5.account_info()
            free_margin = (
                float(account.margin_free)
                if account is not None
                else 0.0
            )

        account_equity = float(account_equity)

        allowed_risk = (
            account_equity * self.max_risk_pct
        )

        minimum_volume = float(info.volume_min)

        # The AI stop is kept exactly as supplied, but it is validated
        # against the broker's current executable entry price.
        stop_direction_ok = self.validate_stop_direction(
            direction=direction,
            entry_price=broker_entry_price,
            stop_loss=float(stop_loss),
        )

        minimum_lot_loss = None
        minimum_lot_margin = None

        if stop_direction_ok:
            minimum_lot_loss = self.calculate_loss_at_stop(
                symbol=symbol,
                direction=direction,
                volume=minimum_volume,
                entry_price=broker_entry_price,
                stop_loss=float(stop_loss),
            )

            minimum_lot_margin = self.calculate_margin_required(
                symbol=symbol,
                direction=direction,
                volume=minimum_volume,
                entry_price=broker_entry_price,
            )

        spread_price = float(tick.ask) - float(tick.bid)
        spread_points = int(round(
            spread_price / float(info.point)
        ))

        checks = {
            "account_equity_positive": (
                account_equity > 0
            ),

            "free_margin_non_negative": (
                free_margin >= 0
            ),

            "valid_entry": (
                broker_entry_price > 0
            ),

            "valid_stop": (
                float(stop_loss) > 0
            ),

            "stop_direction_valid": (
                stop_direction_ok
            ),

            "minimum_lot_risk_ok": (
                minimum_lot_loss is not None
                and minimum_lot_loss <= allowed_risk
            ),

            "minimum_lot_margin_ok": (
                minimum_lot_margin is not None
                and minimum_lot_margin <= free_margin
            ),

            "spread_ok": (
                spread_points <= self.max_spread_points
            ),

            "trade_mode_available": (
                int(info.trade_mode) != 0
            ),
        }

        sizing = None

        if stop_direction_ok:
            sizing = self.calculate_max_safe_volume(
                symbol=symbol,
                direction=direction,
                entry_price=broker_entry_price,
                stop_loss=float(stop_loss),
                account_equity=account_equity,
                free_margin=free_margin,
            )

        safe = all(checks.values())

        max_safe_volume = 0.0
        estimated_margin_at_safe_volume = None
        estimated_loss_at_safe_volume = None

        if sizing is not None:
            max_safe_volume = float(
                sizing.get("max_safe_volume", 0.0)
            )
            estimated_margin_at_safe_volume = sizing.get(
                "estimated_margin_at_safe_volume"
            )
            estimated_loss_at_safe_volume = sizing.get(
                "estimated_loss_at_safe_volume"
            )

        return {
            "safe": safe,
            "symbol": symbol,
            "mt5_symbol": self.get_mt5_symbol(symbol),
            "direction": direction,
            "account_equity": account_equity,
            "free_margin": free_margin,
            "max_risk_pct": self.max_risk_pct,
            "allowed_risk_usd": allowed_risk,
            "minimum_volume": minimum_volume,
            "maximum_safe_volume": max_safe_volume,
            "entry_price": broker_entry_price,
            "supplied_entry_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "minimum_lot_loss": (
                float(minimum_lot_loss)
                if minimum_lot_loss is not None
                else None
            ),
            "minimum_lot_margin": (
                float(minimum_lot_margin)
                if minimum_lot_margin is not None
                else None
            ),
            "estimated_margin_at_safe_volume": (
                float(estimated_margin_at_safe_volume)
                if estimated_margin_at_safe_volume is not None
                else None
            ),
            "estimated_loss_at_safe_volume": (
                float(estimated_loss_at_safe_volume)
                if estimated_loss_at_safe_volume is not None
                else None
            ),
            "spread_points": spread_points,
            "max_spread_points": self.max_spread_points,
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "checks": checks,
            "sizing": sizing,
        }


def main():
    print("=" * 60)
    print("MT5 FOREX RISK SAFETY TEST")
    print("READ-ONLY — NO ORDERS WILL BE SENT")
    print("=" * 60)

    manager = MT5RiskManager(
        max_risk_pct=0.01,
        max_spread_points=50,
    )

    if not manager.connect():
        print("❌ MT5 connection failed")
        print("Error:", mt5.last_error())
        return

    try:
        account = mt5.account_info()

        if account is None:
            print("❌ Could not read account")
            print("Error:", mt5.last_error())
            return

        print()
        print("ACCOUNT")
        print("-" * 60)
        print("Login:", account.login)
        print("Balance:", account.balance)
        print("Equity:", account.equity)
        print("Free margin:", account.margin_free)
        print("Currency:", account.currency)
        print("Server:", account.server)

        print()
        print("RISK SETTINGS")
        print("-" * 60)
        print("Maximum risk:", manager.max_risk_pct * 100, "%")
        print(
            "Allowed risk:",
            account.equity * manager.max_risk_pct,
            account.currency,
        )
        print(
            "Maximum spread:",
            manager.max_spread_points,
            "points",
        )

        for symbol in MT5_SYMBOLS:
            print()
            print("=" * 60)
            print(symbol)
            print("=" * 60)

            try:
                data = manager.inspect_symbol(symbol)

                print("MT5 symbol:", data["mt5_symbol"])
                print("Bid:", data["bid"])
                print("Ask:", data["ask"])
                print("Spread points:", data["spread_points"])
                print("Minimum lot:", data["volume_min"])
                print("Volume step:", data["volume_step"])
                print("Contract size:", data["contract_size"])
                print("Tick size:", data["trade_tick_size"])
                print("Tick value:", data["trade_tick_value"])

                # Use a small, hypothetical stop only for diagnostics.
                # No order is sent.
                entry = manager.get_entry_price(
                    symbol,
                    "BUY",
                )
                point = data["point"]
                diagnostic_stop = entry - (10 * point)

                risk = manager.check_risk(
                    symbol=symbol,
                    direction="BUY",
                    entry_price=entry,
                    stop_loss=diagnostic_stop,
                )

                print("Hypothetical BUY entry:", risk["entry_price"])
                print("Hypothetical stop:", risk["stop_loss"])
                print("Minimum-lot loss:", risk["minimum_lot_loss"])
                print("Minimum-lot margin:", risk["minimum_lot_margin"])
                print("Maximum safe volume:", risk["maximum_safe_volume"])
                print("Safety result:", risk["safe"])
                print("Checks:", risk["checks"])

            except Exception as exc:
                print("❌ Inspection failed:", exc)

        print()
        print("=" * 60)
        print("SAFETY TEST COMPLETE")
        print("NO ORDERS WERE SENT")
        print("=" * 60)

    finally:
        manager.shutdown()


if __name__ == "__main__":
    main()
