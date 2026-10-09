"""Offline integration and responsive rendering for the reference page."""
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench.ui import qml_bridge
from test_indicator_reference import FakeApi, NOW
from test_qml_bridge_readonly import FakeApi as AccountApi
from test_qml_ui import visual_find
from mt5_workbench.services.indicator_reference import load_indicator_reference


class QmlIndicatorReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def make_bridge(self):
        api = AccountApi()
        bridge = qml_bridge.QmlBridge(api=api, autoconnect=False, start_timer=False,
                                      journal_repository=object())
        self.addCleanup(bridge.close)
        bridge.account, bridge.connected = api.current, True
        bridge._set_state(connection={"connected": True, "locked": False})
        return bridge, api

    def pump(self, bridge):
        deadline = time.monotonic() + 2
        while bridge._jobs and time.monotonic() < deadline:
            bridge._consume_results()
            QTest.qWait(10)
        self.assertFalse(bridge._jobs)

    def test_navigation_background_refresh_period_and_session_reset(self):
        bridge, _ = self.make_bridge()
        data = load_indicator_reference("XAUUSDc", api=FakeApi(), now=NOW)
        with patch.object(qml_bridge, "load_indicator_reference", return_value=data) as loader:
            bridge.perform("navigate", {"page": "indicators"})
            self.assertEqual(bridge.state["page"], "indicators")
            self.assertTrue(bridge.state["indicators"]["loading"])
            self.pump(bridge)
            self.assertEqual(bridge.state["indicators"]["dailyAverages"][0]["points"], 2000)
            for value in (0, 101, True, "1.5", "NaN"):
                bridge.perform("indicatorPeriod", {"period": value})
                self.assertEqual(bridge.state["indicators"]["period"], 14)
            bridge.perform("indicatorPeriod", {"period": 7})
            self.pump(bridge)
            self.assertEqual(loader.call_args.kwargs["period"], 7)
            bridge._clear_session("断线")
            self.assertEqual(bridge.state["indicators"]["atr"], [])
            self.assertEqual(bridge.state["indicators"]["dailyAverages"], [])

    def test_populated_layout_target_ratio_and_themes_without_qml_errors(self):
        bridge = qml_bridge.QmlBridge(autoconnect=False, start_timer=False, journal_repository=object())
        self.addCleanup(bridge.close)
        data = load_indicator_reference("XAUUSDc", api=FakeApi(), now=NOW)
        bridge._set_state(page="indicators", indicators=data)
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(error.toString() for error in errors))
        qml_dir = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml"
        engine.rootContext().setContextProperty("bridge", bridge)
        engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
        self.assertEqual(len(engine.rootObjects()), 1)
        window = engine.rootObjects()[0]
        try:
            view = window.findChild(QQuickItem, "indicatorReferenceView")
            target = window.findChild(QQuickItem, "indicatorTargetInput")
            summary = window.findChild(QQuickItem, "indicatorTargetSummary")
            target.setProperty("text", "5")
            self.app.processEvents()
            self.assertIn("25.0%", summary.property("text"))
            self.assertIn("5.000", summary.property("text"))
            self.assertNotIn("点", summary.property("text"))
            self.assertEqual(visual_find(window.contentItem(), "indicatorAtrPrice_day").property("text"), "20.000")
            self.assertEqual(visual_find(window.contentItem(), "indicatorAveragePrice_week").property("text"), "20.000")
            bridge._set_state(indicators={**data, "point": None})
            self.app.processEvents()
            self.assertIn("25.0%", summary.property("text"))
            for theme in ("light", "dark"):
                bridge._set_state(theme=theme)
                for width, height in ((1200, 800), (1440, 900), (2560, 1440)):
                    window.resize(width, height)
                    QTest.qWait(30)
                    first = visual_find(window.contentItem(), "indicatorAtrCard_year")
                    last = visual_find(window.contentItem(), "indicatorAtrCard_day")
                    self.assertGreater(first.width(), 180)
                    self.assertLessEqual(last.mapToScene(QPointF(last.width(), 0)).x(), width - 20)
                    if width == 1200:
                        self.assertGreater(last.mapToScene(QPointF(0, 0)).y(), first.mapToScene(QPointF(0, 0)).y())
                    else:
                        self.assertAlmostEqual(last.mapToScene(QPointF(0, 0)).y(), first.mapToScene(QPointF(0, 0)).y(), delta=2)
                    self.assertFalse(window.grabWindow().isNull())
            self.assertEqual(warnings, [])
            screenshot_dir = os.environ.get("INDICATOR_SCREENSHOT_DIR")
            if screenshot_dir:
                path = Path(screenshot_dir)
                path.mkdir(parents=True, exist_ok=True)
                for theme in ("light", "dark"):
                    bridge._set_state(theme=theme)
                    window.resize(1440, 1200)
                    QTest.qWait(80)
                    window.grabWindow().save(str(path / f"indicators-{theme}.png"))
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
