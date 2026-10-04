"""Qt account gating with simulated MT5 responses; these tests never send orders."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mt5_workbench.ui import main_window as qt_gui


def account(currency: str):
    return SimpleNamespace(
        login=123,
        server="test",
        currency=currency,
        name="test",
        balance=10000,
        equity=10000,
        margin_free=10000,
        profit=0,
        margin=0,
        margin_level=0,
    )


class GuiAccountGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt_app = QApplication.instance() or QApplication([])

    def new_window(self):
        window = qt_gui.MainWindow(autoconnect=False, start_timer=False)
        window.show()
        self.qt_app.processEvents()

        def close_window():
            window._closing = True
            if window.account_lock is not None:
                window.account_lock.hide()
            with patch.object(qt_gui.mt5, "shutdown"):
                window.close()
            self.qt_app.processEvents()

        self.addCleanup(close_window)
        return window

    def test_sidebar_names_stay_consistent_when_resized(self):
        window = self.new_window()
        expected = ["总览看板", "交易概览", "行情日志", "下单管理", "控制面板", "实验功能"]
        for width, height in ((1200, 800), (2560, 1440)):
            window.resize(width, height)
            self.qt_app.processEvents()
            self.assertEqual([button.text() for button in window.nav.values()], expected)
            self.assertEqual(window.sidebar.width(), 128 if width < 1380 else 215)
        self.assertEqual((window.minimumWidth(), window.minimumHeight()), (1200, 800))

    def test_non_usc_account_locks_until_rechecked(self):
        current = [account("USD")]
        with (
            patch.object(qt_gui.mt5, "initialize", return_value=True),
            patch.object(qt_gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(qt_gui.mt5, "account_info", side_effect=lambda: current[0]),
            patch.object(qt_gui.mt5, "shutdown") as shutdown,
        ):
            window = self.new_window()
            window.connect()
            self.qt_app.processEvents()
            self.assertFalse(window.connected)
            self.assertIsNone(window.account)
            self.assertIsNotNone(window.account_lock)
            self.assertTrue(window.account_lock.isVisible())
            self.assertEqual(window.account_lock.windowModality().name, "ApplicationModal")
            self.assertEqual(window.current_page, "dashboard")
            window.show_page("orders")
            self.assertEqual(window.current_page, "dashboard")
            self.assertGreaterEqual(shutdown.call_count, 1)

            lock = window.account_lock
            window.connect()
            self.assertIs(window.account_lock, lock)

            current[0] = account("USC")
            with patch.object(window, "refresh"):
                window.connect()
            self.assertTrue(window.connected)
            self.assertIsNone(window.account_lock)
            with patch.object(window, "refresh_order_analytics") as read_history:
                window.show_page("orders")
                read_history.assert_called_once()
            self.assertEqual(window.current_page, "orders")

    def test_running_account_switch_to_usd_locks_before_data_refresh(self):
        with (
            patch.object(qt_gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(qt_gui.mt5, "account_info", return_value=account("USD")),
            patch.object(qt_gui.mt5, "shutdown") as shutdown,
            patch.object(qt_gui, "symbol_and_tick") as quote,
        ):
            window = self.new_window()
            window.connected = True
            window.initialized = True
            window.account = account("USC")
            window.refresh()
            self.assertFalse(window.connected)
            self.assertIsNone(window.account)
            self.assertIsNotNone(window.account_lock)
            self.assertTrue(window.account_lock.isVisible())
            shutdown.assert_called_once()
            quote.assert_not_called()

    def test_manual_order_refresh_locks_before_reading_usd_history(self):
        with (
            patch.object(qt_gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(qt_gui.mt5, "account_info", return_value=account("USD")),
            patch.object(qt_gui.mt5, "shutdown"),
            patch.object(qt_gui, "load_order_analytics") as read_history,
        ):
            window = self.new_window()
            window.connected = True
            window.initialized = True
            window.account = account("USC")
            window.refresh_order_analytics()
            self.assertFalse(window.connected)
            self.assertIsNotNone(window.account_lock)
            read_history.assert_not_called()

    def test_monitor_is_last_page_and_read_only_account_gated(self):
        window = self.new_window()
        self.assertEqual(list(window.nav)[-1], "monitor")
        window.connected = True
        window.account = account("USC")
        snapshot = SimpleNamespace(
            status="live", reason="EMA 尚未靠拢", aligned=False,
            ema_values={7: 4200, 14: 4200, 30: 4200, 60: 4200},
            ema_spread_points=0, bid=4200, ask=4200.2,
            quote_age_seconds=1, bar_time=None, observed_at=None,
            includes_forming_bar=True,
        )
        with (
            patch.object(window, "check_account_access", return_value=True),
            patch.object(qt_gui, "fetch_m1_ema_snapshot", return_value=snapshot) as read,
        ):
            window.show_page("monitor")
            read.assert_called_once_with("XAUUSDc", tolerance_points=5.0)
            self.assertEqual(window.monitor.state_value.text(), "等待 EMA 聚拢")
            self.assertFalse(window.nav["monitor"].icon().isNull())

        with (
            patch.object(qt_gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(qt_gui.mt5, "account_info", return_value=account("USD")),
            patch.object(qt_gui.mt5, "shutdown"),
            patch.object(qt_gui, "fetch_m1_ema_snapshot") as read,
        ):
            window.refresh_monitor()
            read.assert_not_called()
            self.assertFalse(window.connected)
            self.assertEqual(window.monitor.bid_value.text(), "—")

    def test_cancelled_order_preview_never_sends(self):
        window = self.new_window()
        current = account("USC")
        result = SimpleNamespace(
            side="SELL", total_volume=0.01, total_risk_usd=1,
            risk_cap_usd=2, range_low=4200, range_high=4202,
            entries=(SimpleNamespace(risk_usd=1),),
        )
        request = {"price": 4200, "volume": 0.01, "sl": 4220, "tp": 0}
        plan = (current, SimpleNamespace(name="XAUUSDc", digits=3),
                SimpleNamespace(bid=4199, ask=4199.2), result, (request,))
        with (
            patch.object(window, "check_account_access", return_value=True),
            patch.object(window, "_fresh_order_plan", return_value=plan),
            patch.object(qt_gui, "check_requests"),
            patch.object(window, "_confirm", return_value=False),
            patch.object(qt_gui, "send_checked") as send,
        ):
            window.preview_orders()
            send.assert_not_called()

    def test_cancelled_control_preview_never_executes(self):
        window = self.new_window()
        current = account("USC")
        window.connected = True
        window.account = current
        target = SimpleNamespace(ticket=1, symbol="XAUUSDc", type=3,
                                 volume_initial=0.01, price_open=4200,
                                 sl=4220)
        with (
            patch.object(window, "check_account_access", return_value=True),
            patch.object(qt_gui.mt5, "account_info", return_value=current),
            patch.object(qt_gui, "load_targets", return_value=(target,)),
            patch.object(window, "_confirm", return_value=False),
            patch.object(qt_gui, "execute_batch") as execute,
        ):
            window.preview_control("remove")
            execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
