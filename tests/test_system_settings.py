"""System preferences persist offline; global display respects date boundaries."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Q_ARG, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench.infrastructure import system_settings
from mt5_workbench.ui import qml_bridge, theme


def visual_find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        result = visual_find(child, name)
        if result is not None:
            return result
    return None


class SystemSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "system_settings.json"
        for module, name, path in (
            (system_settings, "settings_path", self.path),
            (qml_bridge, "_refresh_settings_path", self.path.with_name("refresh.json")),
            (theme, "theme_settings_path", self.path.with_name("theme.json")),
        ):
            patcher = patch.object(module, name, return_value=path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_bridge(self):
        api = Mock()
        bridge = qml_bridge.QmlBridge(autoconnect=False, start_timer=False,
                                      journal_repository=object(), api=api)
        self.addCleanup(bridge.close)
        return bridge, api

    def test_save_reload_and_account_reset_preserve_global_settings(self):
        bridge, api = self.make_bridge()
        self.assertEqual(bridge.state["system"]["timeZone"], "UTC+08:00")
        bridge.perform("setTimeZone", {"timeZone": "UTC-08:00"})
        bridge.perform("setRefreshInterval", {"kind": "orders", "seconds": 17})
        bridge.perform("setTheme", {"theme": "light"})
        bridge._clear_session("断线", locked=True)
        self.assertEqual(bridge.state["system"]["timeZone"], "UTC-08:00")
        reloaded, _ = self.make_bridge()
        self.assertEqual(reloaded.state["system"]["timeZone"], "UTC-08:00")
        self.assertEqual(reloaded.state["refreshIntervals"]["orders"], 17)
        self.assertEqual(reloaded.state["theme"], "light")
        self.assertEqual(json.loads(self.path.read_text("utf-8"))["textEncoding"], "utf-8")
        api.assert_not_called()
        self.assertEqual(api.mock_calls, [])

    def test_invalid_saved_preferences_fall_back_and_invalid_actions_do_not_save(self):
        for contents in ("invalid", "[]", '{"timeZone": []}', '{"timeZone": "Mars"}',
                         '{"timeZone": "UTC+15:00"}'):
            self.path.write_text(contents, encoding="utf-8")
            self.assertEqual(system_settings.load_time_zone(), "UTC+08:00")
        self.path.unlink()
        bridge, _ = self.make_bridge()
        expected = bridge.state["system"]
        for value in (None, [], True, "Mars", "UTC+15:00"):
            bridge.perform("setTimeZone", {"timeZone": value})
            self.assertEqual(bridge.state["system"], expected)
        self.assertFalse(self.path.exists())

    def test_clock_updates_without_mt5_and_handles_midnight(self):
        bridge, api = self.make_bridge()
        stamp = datetime(2026, 1, 1, 0, 15, tzinfo=timezone.utc)
        west = system_settings.clock_snapshot("UTC-08:00", stamp)
        self.assertEqual(west["displayTime"], "2025-12-31 16:15:00")
        self.assertEqual(west["offsetMinutes"], -480)
        east = system_settings.clock_snapshot("UTC+14:00", stamp)
        self.assertEqual(east["displayTime"], "2026-01-01 14:15:00")
        with patch.object(qml_bridge, "clock_snapshot", return_value=east):
            bridge.poll()
        self.assertEqual(bridge.state["system"]["displayTime"], east["displayTime"])
        self.assertEqual(api.mock_calls, [])

    def test_settings_work_when_account_locked_and_save_failure_is_visible(self):
        bridge, api = self.make_bridge()
        bridge._clear_session("账户受限", locked=True)
        bridge.perform("navigate", {"page": "settings"})
        self.assertEqual(bridge.state["page"], "settings")
        with patch.object(qml_bridge, "save_time_zone", return_value=False):
            bridge.perform("setTimeZone", {"timeZone": "UTC"})
        self.assertEqual(bridge.state["system"]["timeZone"], "UTC")
        self.assertIn("保存失败", bridge.state["status"])
        self.assertEqual(bridge.state["notification"]["level"], "warning")
        bridge.perform("setTheme", {"theme": "dark"})
        self.assertEqual(bridge.state["theme"], "dark")
        bridge.perform("setRefreshInterval", {"kind": "quote", "seconds": 4})
        self.assertEqual(bridge.state["refreshIntervals"]["quote"], 4)
        self.assertEqual(api.mock_calls, [])

    def test_qml_settings_controls_timezone_and_layout(self):
        bridge, api = self.make_bridge()
        bridge.perform("navigate", {"page": "settings"})
        bridge._set_state(journal={**bridge.state["journal"], "posts": [
            {"id": 1, "body": "跨日测试", "createdAt": "2026-01-01T00:15:00+00:00",
             "images": [], "positions": [], "replies": []},
        ]})
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda items: warnings.extend(str(item) for item in items))
        directory = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml"
        engine.addImportPath(str(directory))
        engine.rootContext().setContextProperty("bridge", bridge)
        engine.load(QUrl.fromLocalFile(str(directory / "App.qml")))
        self.assertEqual(len(engine.rootObjects()), 1)
        window = engine.rootObjects()[0]
        try:
            QTest.qWait(50)
            selector = window.findChild(QQuickItem, "systemTimeZoneSelector")
            self.assertEqual(selector.property("currentIndex"), system_settings.TIME_ZONES.index("UTC+08:00"))
            QMetaObject.invokeMethod(selector, "activated", Q_ARG("int", system_settings.TIME_ZONES.index("UTC")))
            self.assertEqual(bridge.state["system"]["timeZone"], "UTC")
            for name, seconds in (("quote", 3), ("positions", 9), ("orders", 45)):
                field = visual_find(window.contentItem(), "systemRefreshSeconds_" + name)
                field.setProperty("text", str(seconds))
                button = visual_find(window.contentItem(), "systemRefreshApply_" + name)
                QMetaObject.invokeMethod(button, "clicked")
                self.assertEqual(bridge.state["refreshIntervals"][name], seconds)
            bridge.perform("setTimeZone", {"timeZone": "UTC-08:00"})
            QTest.qWait(30)
            journal = window.findChild(QQuickItem, "journalView")
            group = journal.property("timelineDays").toVariant()[0]
            self.assertEqual(group["key"], "2025-12-31")
            self.assertEqual(group["label"], "2025年12月31日")
            bridge.perform("setTimeZone", {"timeZone": "UTC+08:00"})
            QTest.qWait(30)
            self.assertEqual(journal.property("timelineDays").toVariant()[0]["key"], "2026-01-01")
            for theme_name in ("light", "dark"):
                bridge.perform("setTheme", {"theme": theme_name})
                for width, height in ((1200, 800), (1440, 900), (2560, 1440)):
                    window.resize(width, height)
                    QTest.qWait(30)
                    card = window.findChild(QQuickItem, "systemTimeCard")
                    left = card.mapToScene(QPointF(0, 0)).x()
                    self.assertGreaterEqual(left, 0)
                    self.assertLessEqual(left + card.width(), width - 20)
                    self.assertGreaterEqual(selector.width(), 200)
                    self.assertFalse(window.grabWindow().isNull())
            self.assertEqual(warnings, [])
            self.assertEqual(api.mock_calls, [])
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
