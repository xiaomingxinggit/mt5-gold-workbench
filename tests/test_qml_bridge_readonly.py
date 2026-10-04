"""Offline, no-trade checks for the Qt Quick MT5 state bridge."""

from __future__ import annotations

import os
import time
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mt5_workbench.ui import qml_bridge as bridge_module


def account(login: int = 101, currency: str = "USC") -> SimpleNamespace:
    return SimpleNamespace(login=login, server="test-server", currency=currency,
                           name="Test", balance=10000, equity=10000, profit=0,
                           margin=0, margin_free=10000, margin_level=0)


def analytics() -> SimpleNamespace:
    return SimpleNamespace(
        pending_count=1, pending_lots=0.01, position_count=0,
        position_lots=0, deal_count=0, buy_lots=0, sell_lots=0,
        traded_lots=0, net_trading_cashflow=0,
        account_max_drawdown=0, account_current_drawdown=0,
        account_curve=(), daily_execution=(), pending_orders=(),
        recent_orders=(), recent_deals=(), status_counts=(), errors=(),
        as_of=None,
    )


class FakeApi:
    def __init__(self):
        self.current = account()
        self.shutdown_count = 0

    def account_info(self):
        return self.current

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def shutdown(self):
        self.shutdown_count += 1

    def last_error(self):
        return (0, "ok")

    def positions_get(self, **_kwargs):
        return ()

    def orders_get(self, **_kwargs):
        return ()


class QmlBridgeReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_bridge(self):
        api = FakeApi()
        bridge = bridge_module.QmlBridge(autoconnect=False, start_timer=False,
                                         journal_repository=object(), api=api)
        bridge.account = api.current
        bridge.connected = True
        bridge._set_state(connection={"connected": True, "locked": False,
                                      "message": "已连接"},
                          account=bridge_module._account_map(api.current))
        self.addCleanup(bridge.close)
        return bridge, api

    def pump(self, bridge, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            bridge._consume_results()
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def test_overview_navigation_never_waits_for_history(self):
        bridge, _api = self.make_bridge()
        started, release = Event(), Event()
        self.addCleanup(release.set)

        def slow_load(*_args, **_kwargs):
            started.set()
            release.wait(2)
            return analytics()

        with patch.object(bridge_module, "load_order_analytics", side_effect=slow_load):
            began = time.monotonic()
            bridge.perform("navigate", {"page": "orders"})
            self.assertLess(time.monotonic() - began, 0.5)
            self.assertEqual(bridge.state["page"], "orders")
            self.assertTrue(bridge.state["overview"]["loading"])
            self.assertTrue(self.pump(bridge, started.is_set))
            release.set()
            self.assertTrue(self.pump(bridge, lambda: not bridge.state["overview"]["loading"]))
            self.assertEqual(bridge.state["overview"]["metrics"]["pendingCount"], 1)

    def test_account_switch_discards_inflight_history(self):
        bridge, api = self.make_bridge()
        started, release = Event(), Event()
        self.addCleanup(release.set)

        def slow_load(*_args, **_kwargs):
            started.set()
            release.wait(2)
            return analytics()

        with patch.object(bridge_module, "load_order_analytics", side_effect=slow_load):
            bridge.perform("navigate", {"page": "orders"})
            self.assertTrue(self.pump(bridge, started.is_set))
            api.current = account(202)
            self.assertFalse(bridge.check_account_access())
            release.set()
            self.assertTrue(self.pump(bridge, lambda: not bridge._jobs))
            self.assertFalse(bridge.state["connection"]["connected"])
            self.assertEqual(bridge.state["overview"]["metrics"], {})

    def test_non_usc_account_locks_all_page_actions(self):
        bridge, api = self.make_bridge()
        api.current = account(currency="USD")
        self.assertFalse(bridge.check_account_access())
        self.assertTrue(bridge.state["connection"]["locked"])
        bridge.perform("navigate", {"page": "orders"})
        self.assertEqual(bridge.state["page"], "dashboard")

    def test_live_books_are_read_only_and_account_scoped(self):
        bridge, api = self.make_bridge()
        api.positions_get = lambda **_kwargs: (
            SimpleNamespace(ticket=1, symbol="XAUUSDc", type=0, volume=0.01,
                            price_open=4200, price_current=4201, sl=4190,
                            tp=4220, profit=100),)
        api.orders_get = lambda **_kwargs: ()
        bridge.refresh_books()
        self.assertTrue(self.pump(bridge, lambda: len(bridge.state["dashboard"]["positions"]) == 1))
        self.assertEqual(bridge.state["dashboard"]["positions"][0]["volume"], 0.01)
        self.assertEqual(bridge.state["dashboard"]["orders"], [])


if __name__ == "__main__":
    unittest.main()
