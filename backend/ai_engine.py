"""
Forex AI Trading Engine using Google Gemini.

The AI analyzes Forex technical indicators and returns a structured
trade decision. It does NOT determine the actual money risked per trade.
That will be handled by the deterministic risk engine later.
"""

import json
import logging
import os

from google import genai


logger = logging.getLogger(__name__)


class AITradingEngine:
    """AI decision engine for Forex markets."""

    def __init__(self, model_name: str = "gemini-3.6-flash"):
        self.model_name = model_name
        self.client = None

        api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        if not api_key:
            logger.info(
                "Gemini API key is not configured; using the local "
                "deterministic analysis fallback."
            )
            return

        try:
            self.client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.warning(
                f"Could not initialize Gemini Client automatically: {e}"
            )

    def analyze_market(
        self,
        symbol: str,
        current_price: float,
        indicators_summary: dict,
    ) -> dict:
        """
        Analyze Forex market conditions and return a structured
        trading decision.
        """

        if not self.client:
            return self._fallback_rule_based(
                indicators_summary,
                current_price,
            )

        prompt = f"""
You are an institutional Forex algorithmic trader and risk manager.

Analyze the following technical market data for the Forex pair
{symbol}.

Current price: {current_price}

Technical indicators:
- RSI (14): {indicators_summary.get('rsi', 'N/A')}
- EMA 9: {indicators_summary.get('ema_9', 'N/A')}
- EMA 21: {indicators_summary.get('ema_21', 'N/A')}
- EMA 50: {indicators_summary.get('ema_50', 'N/A')}
- MACD Line: {indicators_summary.get('macd', 'N/A')}
- MACD Signal: {indicators_summary.get('macd_signal', 'N/A')}
- MACD Histogram: {indicators_summary.get('macd_hist', 'N/A')}
- Bollinger Upper: {indicators_summary.get('bb_upper', 'N/A')}
- Bollinger Lower: {indicators_summary.get('bb_lower', 'N/A')}
- ATR (14): {indicators_summary.get('atr', 'N/A')}
- Recent Trend: {indicators_summary.get('trend_summary', 'Neutral')}

Forex-specific instructions:

1. Evaluate the market using trend, momentum, volatility, and
   overbought/oversold conditions.

2. BUY means the base currency is expected to strengthen against
   the quote currency.

3. SELL means the base currency is expected to weaken against
   the quote currency.

4. HOLD when the technical evidence is insufficient or conflicting.

5. Use ATR to help estimate sensible stop-loss and take-profit
   distances for the current pair.

6. Do not assume that different Forex pairs have the same price
   scale. EUR/USD and GBP/USD have different price precision from
   USD/JPY and GBP/JPY.

7. Do not recommend excessive leverage.

8. Do not determine the actual account money at risk. A separate
   deterministic risk-management system will calculate position
   size later.

Return STRICT JSON only.
Do not use markdown.
Do not include code fences.

Schema:

{{
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "suggested_allocation_pct": <float between 0.01 and 0.05>,
  "stop_loss_price": <float>,
  "take_profit_price": <float>,
  "risk_reward_ratio": <float>,
  "rationale": "<concise explanation>"
}}
"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )

            raw_text = response.text.strip()

            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]

            if raw_text.startswith("```"):
                raw_text = raw_text[3:]

            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            data = json.loads(raw_text.strip())

            return self._validate_ai_response(
                data,
                symbol,
                current_price,
            )

        except Exception as e:
            logger.error(f"Error calling Gemini AI: {e}")

            return self._fallback_rule_based(
                indicators_summary,
                current_price,
            )

    def _validate_ai_response(
        self,
        data: dict,
        symbol: str,
        price: float,
    ) -> dict:
        """Validate and normalize Gemini's response."""

        valid_signals = {"BUY", "SELL", "HOLD"}

        signal = str(
            data.get("signal", "HOLD")
        ).upper()

        if signal not in valid_signals:
            signal = "HOLD"

        try:
            confidence = float(
                data.get("confidence", 0.5)
            )
        except (TypeError, ValueError):
            confidence = 0.5

        confidence = max(
            0.0,
            min(1.0, confidence),
        )

        try:
            allocation = float(
                data.get(
                    "suggested_allocation_pct",
                    0.05,
                )
            )
        except (TypeError, ValueError):
            allocation = 0.05

        allocation = max(
            0.01,
            min(0.05, allocation),
        )

        try:
            stop_loss = float(
                data["stop_loss_price"]
            )
        except (KeyError, TypeError, ValueError):
            stop_loss = price

        try:
            take_profit = float(
                data["take_profit_price"]
            )
        except (KeyError, TypeError, ValueError):
            take_profit = price

        try:
            risk_reward = float(
                data.get("risk_reward_ratio", 1.5)
            )
        except (TypeError, ValueError):
            risk_reward = 1.5

        rationale = str(
            data.get(
                "rationale",
                "No rationale provided.",
            )
        )

        # Basic directional sanity checks.
        # BUY should normally have SL below entry and TP above entry.
        if signal == "BUY":
            if stop_loss >= price or take_profit <= price:
                signal = "HOLD"
                confidence = min(confidence, 0.5)

        # SELL should normally have SL above entry and TP below entry.
        elif signal == "SELL":
            if stop_loss <= price or take_profit >= price:
                signal = "HOLD"
                confidence = min(confidence, 0.5)

        return {
            "signal": signal,
            "confidence": confidence,
            "suggested_allocation_pct": allocation,
            "stop_loss_price": stop_loss,
            "take_profit_price": take_profit,
            "risk_reward_ratio": risk_reward,
            "rationale": rationale,
        }

    def _fallback_rule_based(
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
