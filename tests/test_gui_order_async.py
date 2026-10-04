"""Offline checks for responsive, account-safe trading overview refreshes."""

from __future__ import annotations

import os
import time
import unittest
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mt5_workbench.ui import main_window as gui


def _account(login: int, currency: str = "USC") -> SimpleNamespace:
    return SimpleNamespace(
        login=login, server="test-server", currency=currency, name="test",
        balance=10000, equity=10000, margin_free=10000, profit=0,
        margin=0, margin_level=0,
    )


def _result(name: str) -> SimpleNamespace:
    # Rendering is patched in these tests; the identity is what matters.
    return SimpleNamespace(name=name, errors=())


class AsyncOrderOverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _window(self) -> gui.MainWindow:
        window = gui.MainWindow(autoconnect=False, start_timer=False)
        window.show()
        self.app.processEvents()
        window.connected = True
        window.account = _account(101)
        terminal_patch = patch.object(
            gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True))
        account_patch = patch.object(
            gui.mt5, "account_info", side_effect=lambda: window.account)
        terminal_patch.start()
        account_patch.start()
        self.addCleanup(terminal_patch.stop)
        self.addCleanup(account_patch.stop)

        def close() -> None:
            window._closing = True
            if window.account_lock is not None:
                window.account_lock.hide()
            with patch.object(gui.mt5, "shutdown"):
                window.close()
            self.app.processEvents()

        self.addCleanup(close)
        return window

    def _pump_until(self, predicate, timeout: float = 3.0,
                    window: gui.MainWindow | None = None) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if window is not None:
                window._consume_order_analytics_result()
            if predicate():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        if window is not None:
            window._consume_order_analytics_result()
        return bool(predicate())

    def test_opening_trade_overview_does_not_wait_for_slow_history(self) -> None:
        window = self._window()
        started = Event()
        release = Event()
        self.addCleanup(release.set)
        data = _result("history")

        def slow_load(_account, *, symbol, days, api=None):
            started.set()
            release.wait(2.0)
            return data

        with (
            patch.object(window, "check_account_access", return_value=True),
            patch.object(gui, "load_order_analytics", side_effect=slow_load),
            patch.object(window.order_page, "set_data") as render,
        ):
            before = time.monotonic()
            window.show_page("orders")
            elapsed = time.monotonic() - before
            self.assertEqual(window.current_page, "orders")
            self.assertLess(elapsed, 1.0, "切页不能等待 MT5 历史记录读取")
            self.assertTrue(self._pump_until(started.is_set, 1.0, window))
            render.assert_not_called()
            release.set()
            self.assertTrue(self._pump_until(lambda: render.call_count == 1,
                                             window=window))
            render.assert_called_once_with(data, window.account)

    def test_repeated_refresh_is_single_flight_and_uses_latest_filter(self) -> None:
        window = self._window()
        started = Event()
        release = Event()
        self.addCleanup(release.set)
        calls: list[tuple[int, int]] = []
        active = 0
        max_active = 0
        lock = Lock()
        latest = _result("latest")

        def load(account, *, symbol, days, api=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
                calls.append((account.login, days))
                call_number = len(calls)
            try:
                if call_number == 1:
                    started.set()
                    release.wait(2.0)
                    return _result("superseded")
                return latest
            finally:
                with lock:
                    active -= 1

        with (
            patch.object(window, "check_account_access", return_value=True),
            patch.object(gui, "load_order_analytics", side_effect=load),
            patch.object(window.order_page, "set_data") as render,
        ):
            window.refresh_order_analytics()
            self.assertTrue(self._pump_until(started.is_set, 1.0, window))
            window.order_page.period_combo.setCurrentIndex(2)  # 90 days
            for _ in range(4):
                window.refresh_order_analytics()
            self.assertEqual(len(calls), 1, "在途读取期间不可重入 MT5 历史接口")
            release.set()
            self.assertTrue(self._pump_until(lambda: len(calls) == 2,
                                             window=window))
            self.assertTrue(self._pump_until(lambda: render.call_count >= 1,
                                             window=window))
            self.assertEqual(calls, [(101, 30), (101, 90)])
            self.assertEqual(max_active, 1)
            self.assertIs(render.call_args.args[0], latest)

    def test_old_account_result_is_discarded_after_account_switch(self) -> None:
        window = self._window()
        old_account = window.account
        new_account = _account(202)
        first_started = Event()
        first_release = Event()
        self.addCleanup(first_release.set)
        old_result = _result("old-account")
        new_result = _result("new-account")
        calls: list[int] = []

        def load(account, *, symbol, days, api=None):
            calls.append(account.login)
            if account.login == old_account.login:
                first_started.set()
                first_release.wait(2.0)
                return old_result
            return new_result

        with (
            patch.object(window, "check_account_access", return_value=True),
            patch.object(gui, "load_order_analytics", side_effect=load),
            patch.object(window.order_page, "set_data") as render,
        ):
            window.refresh_order_analytics()
            self.assertTrue(self._pump_until(first_started.is_set, 1.0, window))
            window.account = new_account
            window.refresh_order_analytics()
            first_release.set()
            self.assertTrue(self._pump_until(lambda: new_account.login in calls,
                                             window=window))
            self.assertTrue(self._pump_until(lambda: render.call_count >= 1,
                                             window=window))
            self.assertNotIn(old_result, [call.args[0] for call in render.call_args_list])
            self.assertIs(render.call_args.args[0], new_result)
            self.assertIs(render.call_args.args[1], new_account)

    def test_non_usc_account_never_starts_history_worker(self) -> None:
        window = self._window()
        with (
            patch.object(gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(gui.mt5, "account_info", return_value=_account(101, "USD")),
            patch.object(gui.mt5, "shutdown"),
            patch.object(gui, "load_order_analytics") as read_history,
        ):
            window.refresh_order_analytics()
            self.app.processEvents()
            self.assertFalse(window.connected)
            self.assertIsNotNone(window.account_lock)
            read_history.assert_not_called()

    def test_worker_stops_before_next_history_call_after_account_switch(self) -> None:
        current = [_account(101)]
        calls: list[str] = []
        api = SimpleNamespace(
            account_info=lambda: current[0],
            orders_get=lambda: calls.append("orders") or (),
            history_orders_get=lambda: calls.append("history") or (),
        )
        cancelled = Event()
        guarded = gui._CancellableOrderApi(api, cancelled, (101, "test-server"))
        self.assertEqual(guarded.orders_get(), ())
        current[0] = _account(202)
        with self.assertRaises(gui._OrderAnalyticsCancelled):
            guarded.history_orders_get()
        self.assertEqual(calls, ["orders"])
        self.assertTrue(cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
