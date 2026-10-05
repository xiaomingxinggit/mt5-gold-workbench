"""Offline checks for editable Qt Quick polling intervals."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench.ui import qml_bridge


class RefreshIntervalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_preferences_save_reload_and_survive_session_clear(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "refresh_intervals.json"
            with patch.object(qml_bridge, "_refresh_settings_path", return_value=path):
                bridge = qml_bridge.QmlBridge(
                    autoconnect=False, start_timer=False, journal_repository=object(),
                )
                try:
                    self.assertEqual(bridge.state["refreshIntervals"],
                                     {"quote": 1, "positions": 5, "orders": 30})
                    # QML JavaScript numbers may arrive as an integral float.
                    bridge.perform("setRefreshInterval", {"kind": "positions", "seconds": 7.0})
                    self.assertEqual(bridge.state["refreshIntervals"]["positions"], 7)
                    bridge._clear_session("测试断线")
                    self.assertEqual(bridge.state["refreshIntervals"]["positions"], 7)
                finally:
                    bridge.close()

                reloaded = qml_bridge.QmlBridge(
                    autoconnect=False, start_timer=False, journal_repository=object(),
                )
                try:
                    self.assertEqual(reloaded.state["refreshIntervals"]["positions"], 7)
                finally:
                    reloaded.close()

    def test_invalid_values_never_replace_valid_intervals(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "refresh_intervals.json"
            with patch.object(qml_bridge, "_refresh_settings_path", return_value=path):
                bridge = qml_bridge.QmlBridge(
                    autoconnect=False, start_timer=False, journal_repository=object(),
                )
                try:
                    expected = dict(bridge.state["refreshIntervals"])
                    for kind, value in (("orders", 0), ("orders", 3601),
                                        ("quote", True), ("quote", 1.5),
                                        ("positions", "2"), ("unknown", 8)):
                        bridge.perform("setRefreshInterval", {"kind": kind,
                                                              "seconds": value})
                        self.assertEqual(bridge.state["refreshIntervals"], expected)
                    self.assertFalse(path.exists())
                finally:
                    bridge.close()

    def test_poll_uses_independent_quote_positions_and_order_intervals(self) -> None:
        bridge = qml_bridge.QmlBridge(
            autoconnect=False, start_timer=False, journal_repository=object(),
        )
        self.addCleanup(bridge.close)
        bridge.connected = True
        bridge._set_state(refreshIntervals={"quote": 4, "positions": 10,
                                            "orders": 45})
        bridge._last_quote_at = 98
        bridge._last_requested.update({"book_positions": 95, "book_orders": 95,
                                       "dashboard": 99,
                                       "orders": 175})
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote") as quote,
              patch.object(bridge, "refresh_books") as books,
              patch.object(bridge, "_refresh_page") as page,
              patch.object(qml_bridge.time, "monotonic", return_value=100)):
            bridge.poll()
            quote.assert_not_called()
            books.assert_not_called()
            page.assert_not_called()

        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote") as quote,
              patch.object(bridge, "refresh_books") as books,
              patch.object(bridge, "_refresh_page") as page,
              patch.object(qml_bridge.time, "monotonic", return_value=105)):
            bridge.poll()
            quote.assert_called_once_with()
            books.assert_called_once_with(force=False, include_positions=True,
                                          include_orders=False)
            page.assert_not_called()

        bridge._last_requested["book_positions"] = 140
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote"),
              patch.object(bridge, "refresh_books") as books,
              patch.object(bridge, "_refresh_page"),
              patch.object(qml_bridge.time, "monotonic", return_value=145)):
            bridge.poll()
            books.assert_called_once_with(force=False, include_positions=False,
                                          include_orders=True)

        bridge._set_state(page="orders")
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote"),
              patch.object(bridge, "_refresh_page") as page,
              patch.object(qml_bridge.time, "monotonic", return_value=200)):
            bridge.poll()
            page.assert_not_called()
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote"),
              patch.object(bridge, "_refresh_page") as page,
              patch.object(qml_bridge.time, "monotonic", return_value=220)):
            bridge.poll()
            page.assert_called_once_with("orders", force=False)

    def test_book_fetch_only_reads_the_due_section(self) -> None:
        class FakeBookApi:
            POSITION_TYPE_BUY = 0

            def __init__(self) -> None:
                self.position_reads = 0
                self.order_reads = 0

            def positions_get(self, **_kwargs):
                self.position_reads += 1
                return (SimpleNamespace(ticket=7, symbol="XAUUSDc", type=0,
                                        volume=0.01, price_open=4200,
                                        price_current=4201, sl=4190, tp=4220,
                                        profit=100),)

            def orders_get(self, **_kwargs):
                self.order_reads += 1
                return ()

        api = FakeBookApi()
        bridge = qml_bridge.QmlBridge(
            autoconnect=False, start_timer=False, journal_repository=object(),
        )
        self.addCleanup(bridge.close)
        bridge.account = SimpleNamespace(login=1, server="test", currency="USC")
        bridge.connected = True
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_request_job") as request):
            bridge.refresh_books(include_positions=True, include_orders=False)
            loader = request.call_args.args[2]
            positions = loader(api)
            self.assertIn("positions", positions)
            self.assertNotIn("orders", positions)
            self.assertEqual((api.position_reads, api.order_reads), (1, 0))

            bridge.refresh_books(include_positions=False, include_orders=True)
            loader = request.call_args.args[2]
            orders = loader(api)
            self.assertNotIn("positions", orders)
            self.assertIn("orders", orders)
            self.assertEqual((api.position_reads, api.order_reads), (1, 1))

    def test_experiment_monitor_uses_quote_interval(self) -> None:
        bridge = qml_bridge.QmlBridge(
            autoconnect=False, start_timer=False, journal_repository=object(),
        )
        self.addCleanup(bridge.close)
        bridge.connected = True
        bridge._set_state(page="monitor", refreshIntervals={"quote": 12,
                           "positions": 5, "orders": 30})
        bridge._last_quote_at = 100
        bridge._last_requested["monitor"] = 100
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote") as quote,
              patch.object(bridge, "_refresh_page") as refresh,
              patch.object(qml_bridge.time, "monotonic", return_value=111)):
            bridge.poll()
            quote.assert_not_called()
            refresh.assert_not_called()
        with (patch.object(bridge, "check_account_access", return_value=True),
              patch.object(bridge, "_quote") as quote,
              patch.object(bridge, "_refresh_page") as refresh,
              patch.object(qml_bridge.time, "monotonic", return_value=112)):
            bridge.poll()
            quote.assert_called_once_with()
            refresh.assert_called_once_with("monitor", force=False)

    def test_footer_click_opens_editor_and_applies_setting(self) -> None:
        def find_visual(item: QQuickItem, name: str) -> QQuickItem | None:
            if item.objectName() == name:
                return item
            for child in item.childItems():
                found = find_visual(child, name)
                if found is not None:
                    return found
            return None

        with TemporaryDirectory() as directory:
            path = Path(directory) / "refresh_intervals.json"
            with patch.object(qml_bridge, "_refresh_settings_path", return_value=path):
                bridge = qml_bridge.QmlBridge(
                    autoconnect=False, start_timer=False, journal_repository=object(),
                )
                engine = QQmlApplicationEngine()
                qml_dir = Path(__file__).resolve().parents[1] / "src" / "mt5_workbench" / "ui" / "qml"
                engine.rootContext().setContextProperty("bridge", bridge)
                engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
                try:
                    self.assertEqual(len(engine.rootObjects()), 1)
                    window = engine.rootObjects()[0]
                    self.app.processEvents()
                    chip = find_visual(window.contentItem(), "refreshChip_positions")
                    self.assertIsNotNone(chip)
                    editor = window.findChild(QObject, "refreshIntervalDialog")
                    self.assertIsNotNone(editor)
                    point = chip.mapToScene(QPointF(chip.width() / 2, chip.height() / 2))
                    QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
                    self.app.processEvents()
                    self.assertTrue(editor.property("visible"))
                    self.assertEqual(editor.property("kind"), "positions")
                    field = editor.findChild(QObject, "refreshIntervalSeconds")
                    self.assertIsNotNone(field)
                    field.setProperty("text", "9")
                    self.assertTrue(QMetaObject.invokeMethod(editor, "apply"))
                    self.app.processEvents()
                    self.assertEqual(bridge.state["refreshIntervals"]["positions"], 9)
                    self.assertEqual(qml_bridge._load_refresh_intervals()["positions"], 9)
                    window.close()
                finally:
                    bridge.close()


if __name__ == "__main__":
    unittest.main()
