from pathlib import Path

path = Path("server.py")
text = path.read_text(encoding="utf-8")

old = '''            with state.lock:
                price = state.market_data[symbol]["current_price"]

                if price <= 0:
                    result = {
                        "status": "skipped",
                        "reason": f"No live price available for {symbol}",
                    }
                else:
                    signal_data = {
                        "signal": side,
                        "confidence": 1.0,
                        "suggested_allocation_pct": payload.get(
                            "allocation",
                            0.01,
                        ),
                        "rationale": "Manual paper trade from dashboard.",
                    }

                    result = state.portfolio.execute_signal(
                        symbol,
                        signal_data,
                        price,
                    )

            self._write_json(result)
            return
'''

new = '''            with state.lock:
                price = state.market_data[symbol]["current_price"]

                if price <= 0:
                    result = {
                        "status": "skipped",
                        "reason": f"No live price available for {symbol}",
                    }
                else:
                    stop_loss = payload.get("stop_loss_price")
                    take_profit = payload.get("take_profit_price")

                    if stop_loss is None or take_profit is None:
                        result = {
                            "status": "rejected",
                            "reason": (
                                "Manual trades require an explicit "
                                "stop_loss_price and take_profit_price."
                            ),
                        }
                    else:
                        signal_data = {
                            "signal": side,
                            "confidence": 1.0,
                            "suggested_allocation_pct": payload.get(
                                "allocation",
                                0.01,
                            ),
                            "stop_loss_price": float(stop_loss),
                            "take_profit_price": float(take_profit),
                            "risk_reward_ratio": 1.5,
                            "rationale": "Manual trade request.",
                        }

                        # Every execution path must pass through the
                        # broker-aware MT5 risk gate first.
                        risk_check = state.check_mt5_risk_gate(
                            symbol=symbol,
                            decision=signal_data,
                            price=price,
                        )

                        if not risk_check.get("safe"):
                            result = {
                                "status": "rejected",
                                "reason": (
                                    "MT5 risk gate rejected the "
                                    "manual trade."
                                ),
                                "mt5_risk_check": risk_check,
                            }
                        else:
                            result = state.portfolio.execute_signal(
                                symbol,
                                signal_data,
                                price,
                            )

                            result["mt5_risk_check"] = risk_check

            self._write_json(result)
            return
'''

if old not in text:
    raise SystemExit(
        "Exact manual-trade block was not found. "
        "No changes were made."
    )

backup = Path("server_before_execution_safety.py")

if not backup.exists():
    backup.write_text(text, encoding="utf-8")

path.write_text(
    text.replace(old, new),
    encoding="utf-8",
)

print("Execution safety upgrade applied successfully.")
print("Backup:", backup)