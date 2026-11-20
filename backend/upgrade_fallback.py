from pathlib import Path

path = Path("ai_engine.py")
text = path.read_text(encoding="utf-8")

start = text.index("    def _fallback_rule_based(")

new_function = '''    def _fallback_rule_based(
        self,
        ind: dict,
        price: float,
    ) -> dict:
        """
        Deterministic Forex fallback used when Gemini is unavailable.

        Uses trend, momentum, RSI and ATR together. It is intentionally
        conservative and never places broker orders by itself.
        """

        rsi = float(ind.get("rsi", 50))
        ema_9 = float(ind.get("ema_9", price))
        ema_21 = float(ind.get("ema_21", price))
        ema_50 = float(ind.get("ema_50", price))
        macd_hist = float(ind.get("macd_hist", 0))
        atr = abs(float(ind.get("atr", price * 0.001)))

        if atr <= 0:
            atr = price * 0.001

        signal = "HOLD"
        confidence = 0.5
        stop_loss = price
        take_profit = price

        bullish_trend = ema_9 > ema_21 > ema_50
        bearish_trend = ema_9 < ema_21 < ema_50
        bullish_momentum = macd_hist > 0
        bearish_momentum = macd_hist < 0

        if bullish_trend and bullish_momentum:
            signal = "BUY"

            if 45 <= rsi <= 70:
                confidence = 0.82
                rationale = (
                    "Bullish trend is supported by EMA 9/21/50 alignment "
                    "and positive MACD momentum, with RSI still below the "
                    "overbought zone."
                )
            elif rsi > 70:
                confidence = 0.70
                rationale = (
                    "Bullish trend is supported by EMA 9/21/50 alignment "
                    "and positive MACD momentum, but RSI is overbought, "
                    "so confidence is reduced because the move is extended."
                )
            else:
                confidence = 0.75
                rationale = (
                    "Bullish trend and positive MACD support a BUY, while "
                    "RSI provides less confirmation than the primary trend "
                    "signals."
                )

            stop_loss = price - (2 * atr)
            take_profit = price + (3 * atr)

        elif bearish_trend and bearish_momentum:
            signal = "SELL"

            if 30 <= rsi <= 55:
                confidence = 0.82
                rationale = (
                    "Bearish trend is supported by EMA 9/21/50 alignment "
                    "and negative MACD momentum, with RSI still above the "
                    "oversold zone."
                )
            elif rsi < 30:
                confidence = 0.70
                rationale = (
                    "Bearish trend is supported by EMA 9/21/50 alignment "
                    "and negative MACD momentum, but RSI is oversold, so "
                    "confidence is reduced because the move is extended."
                )
            else:
                confidence = 0.75
                rationale = (
                    "Bearish trend and negative MACD support a SELL, while "
                    "RSI provides less confirmation than the primary trend "
                    "signals."
                )

            stop_loss = price + (2 * atr)
            take_profit = price - (3 * atr)

        else:
            rationale = (
                "Trend and momentum signals are mixed, so the deterministic "
                "Forex fallback remains in HOLD."
            )

        return {
            "signal": signal,
            "confidence": confidence,
            "suggested_allocation_pct": 0.05,
            "stop_loss_price": stop_loss,
            "take_profit_price": take_profit,
            "risk_reward_ratio": 1.5,
            "rationale": rationale,
        }
'''

path.write_text(text[:start] + new_function + "\n", encoding="utf-8")
print("Fallback upgraded successfully.")