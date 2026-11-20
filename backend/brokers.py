"""Broker adapter contracts and paper implementation.

The MT5 adapter below is account/read-only only; live order submission is
intentionally not implemented or enabled.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
import importlib
import threading


class BrokerAdapter(ABC):
    @abstractmethod
    def connect(self):
        raise NotImplementedError

    @abstractmethod
    def account_info(self):
        raise NotImplementedError

    @abstractmethod
    def positions(self):
        raise NotImplementedError

    @abstractmethod
    def history(self):
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, symbol, signal, price, idempotency_key):
        raise NotImplementedError


class PaperBroker(BrokerAdapter):
    def __init__(
        self,
        portfolio,
        order_store=None,
        user_id=None,
        persist_callback=None,
    ):
        self.portfolio = portfolio
        self.order_store = order_store
        self.user_id = user_id
        self.persist_callback = persist_callback
        self.connected = True
        self._orders = {}
        self._lock = threading.Lock()

    def connect(self):
        return {"connected": True, "mode": "paper"}

    def account_info(self):
        prices = {
            symbol: position["entry_price"]
            for symbol, position in self.portfolio.positions.items()
        }
        summary = self.portfolio.get_summary(prices)
        return {
            "balance": summary["cash"],
            "equity": summary["equity"],
            "currency": "USD",
            "source": "simulated",
        }

    def positions(self):
        return list(self.portfolio.positions.values())

    def history(self):
        return list(self.portfolio.trade_history)

    def submit_order(self, symbol, signal, price, idempotency_key):
        if not idempotency_key:
            return {"status": "rejected", "reason": "Idempotency key required."}
        with self._lock:
            if self.order_store is not None:
                reservation = self.order_store.begin_paper_order(
                    self.user_id,
                    idempotency_key,
                )
                if not reservation["new"]:
                    if reservation["result"] is not None:
                        return {
                            **reservation["result"],
                            "duplicate": True,
                        }
                    return {
                        "status": "uncertain",
                        "reason": (
                            "An order with this key is already pending. "
                            "Check account positions and history before "
                            "attempting any new request."
                        ),
                        "confirmed": False,
                    }
            if idempotency_key in self._orders:
                return {
                    **self._orders[idempotency_key],
                    "duplicate": True,
                }
            result = self.portfolio.execute_signal(symbol, signal, price)
            if result.get("status") == "executed":
                result = {
                    **result,
                    "broker": "paper",
                    "broker_order_id": f"paper-{result['trade']['id']}",
                    "confirmed": True,
                }
                if self.persist_callback is not None:
                    self.persist_callback()
            if self.order_store is not None:
                self.order_store.complete_paper_order(
                    self.user_id,
                    idempotency_key,
                    result,
                )
            self._orders[idempotency_key] = result
            return result


class MT5ReadOnlyAdapter(BrokerAdapter):
    """Uses the installed terminal session; never accepts/stores passwords."""

    def __init__(self):
        self._mt5 = None

    def close(self):
        if self._mt5 is not None:
            self._mt5.shutdown()
            self._mt5 = None

    def connect(self):
        try:
            self._mt5 = importlib.import_module("MetaTrader5")
        except ImportError as error:
            raise RuntimeError(
                "Install the official MetaTrader5 Python package on a "
                "supported Windows installation to use read-only MT5."
            ) from error
        if not self._mt5.initialize():
            return {
                "connected": False,
                "reason": str(self._mt5.last_error()),
            }
        account = self._mt5.account_info()
        if account is None:
            self._mt5.shutdown()
            raise RuntimeError(
                f"MT5 terminal has no verified account: "
                f"{self._mt5.last_error()}"
            )
        return {
            "connected": True,
            "login": int(account.login),
            "server": str(account.server),
            "currency": str(account.currency),
            "balance": float(account.balance),
            "equity": float(account.equity),
            "live_execution_enabled": False,
        }

    def account_info(self):
        if self._mt5 is None:
            raise RuntimeError("Connect to the MT5 terminal first.")
        account = self._mt5.account_info()
        if account is None:
            raise RuntimeError(f"MT5 account read failed: {self._mt5.last_error()}")
        return {
            "login": int(account.login),
            "server": str(account.server),
            "currency": str(account.currency),
            "balance": float(account.balance),
            "equity": float(account.equity),
            "source": "mt5_read_only",
        }

    def positions(self):
        if self._mt5 is None:
            raise RuntimeError("Connect to the MT5 terminal first.")
        rows = self._mt5.positions_get()
        if rows is None:
            raise RuntimeError(f"MT5 position read failed: {self._mt5.last_error()}")
        return [row._asdict() for row in rows]

    def history(self):
        if self._mt5 is None:
            raise RuntimeError("Connect to the MT5 terminal first.")
        end = datetime.now(timezone.utc)
        rows = self._mt5.history_deals_get(
            end - timedelta(days=365), end
        )
        if rows is None:
            raise RuntimeError(f"MT5 history read failed: {self._mt5.last_error()}")
        return [row._asdict() for row in rows]

    def submit_order(self, symbol, signal, price, idempotency_key):
        return {
            "status": "disabled",
            "reason": (
                "Live order submission is disabled. Read-only MT5 "
                "connectivity is not an execution adapter."
            ),
            "confirmed": False,
        }
