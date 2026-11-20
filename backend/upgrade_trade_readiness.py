from pathlib import Path

path = Path("mt5_risk.py")
text = path.read_text(encoding="utf-8")

marker = "    def check_risk(\n"

if marker not in text:
    raise RuntimeError(
        "Could not find check_risk() in mt5_risk.py"
    )

method = r'''
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

'''

text = text.replace(marker, method + marker, 1)

path.write_text(text, encoding="utf-8")

print("Trade-readiness method added successfully.")