"""Offline Qt Quick integration smoke test for every workbench page."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QPointF, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from mt5_workbench.ui.qml_bridge import PAGE_NAMES
from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge


class QmlUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def test_six_pages_theme_and_window_size_load_without_mt5(self):
        bridge = QmlTradingBridge(autoconnect=False, start_timer=False,
                                  journal_repository=object())
        engine = QQmlApplicationEngine()
        qml_dir = Path(__file__).resolve().parents[1] / "src" / "mt5_workbench" / "ui" / "qml"
        engine.addImportPath(str(qml_dir))
        engine.rootContext().setContextProperty("bridge", bridge)
        engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
        try:
            self.assertEqual(len(engine.rootObjects()), 1)
            window = engine.rootObjects()[0]
            self.assertEqual(window.minimumWidth(), 1200)
            self.assertEqual(window.minimumHeight(), 800)
            for page in PAGE_NAMES:
                bridge.perform("navigate", {"page": page})
                self.app.processEvents()
                self.assertEqual(window.property("page"), page)
            bridge._set_state(
                dashboard={**bridge.state["dashboard"],
                           "candles": [{"time": "2026-10-05T00:00:00+00:00",
                                        "open": 4200.0, "high": 4201.0,
                                        "low": 4199.0, "close": 4200.5}]},
                overview={**bridge.state["overview"],
                          "accountCurve": [{"day": "2026-10-05", "cumulative": 12.5}]},
            )
            bridge.perform("navigate", {"page": "dashboard"})
            bridge._set_state(theme="dark")
            self.app.processEvents()
            self.assertEqual(window.property("themeName"), "dark")
            for width, height in ((1200, 800), (1440, 900), (2560, 1440)):
                window.resize(width, height)
                bridge.perform("navigate", {"page": "journal"})
                self.app.processEvents()
                self.assertEqual(window.width(), width)
                self.assertEqual(window.height(), height)
                calendar = window.findChild(QQuickItem, "journalHeatmapCard")
                months = window.findChild(QQuickItem, "journalHeatmapMonths")
                grid = window.findChild(QQuickItem, "journalHeatmapGrid")
                first_metric = window.findChild(QQuickItem, "journalFirstMetricCard")
                last_metric = window.findChild(QQuickItem, "journalLastMetricCard")
                year_selector = window.findChild(QQuickItem, "journalYearSelector")
                title = window.findChild(QQuickItem, "journalHeatmapTitle")
                self.assertIsNotNone(calendar)
                self.assertIsNotNone(months)
                self.assertIsNotNone(grid)
                self.assertIsNotNone(first_metric)
                self.assertIsNotNone(last_metric)
                self.assertIsNotNone(year_selector)
                self.assertIsNotNone(title)
                card_left = calendar.mapToScene(QPointF(0, 0)).x()
                card_right = card_left + calendar.width()
                grid_left = grid.mapToScene(QPointF(0, 0)).x()
                grid_right = grid_left + grid.width()
                self.assertAlmostEqual(card_left,
                                       first_metric.mapToScene(QPointF(0, 0)).x(), delta=2)
                self.assertAlmostEqual(card_right,
                                       last_metric.mapToScene(QPointF(0, 0)).x() + last_metric.width(), delta=2)
                self.assertAlmostEqual(months.width(), grid.width(), delta=2)
                self.assertAlmostEqual(months.mapToScene(QPointF(0, 0)).x(),
                                       grid.mapToScene(QPointF(0, 0)).x(), delta=3)
                self.assertLessEqual(grid_right, card_right - 8)
                self.assertAlmostEqual(grid_left - card_left, card_right - grid_right,
                                       delta=24)
                self.assertAlmostEqual(year_selector.mapToScene(QPointF(0, 0)).x()
                                       + year_selector.width(), card_right - 22, delta=3)
                self.assertAlmostEqual(title.mapToScene(QPointF(0, 0)).x(),
                                       card_left + 22, delta=3)
            bridge._set_state(journal={**bridge.state["journal"],
                                       "year": 2012, "years": [2012]})
            self.app.processEvents()
            journal_view = window.findChild(QQuickItem, "journalView")
            self.assertEqual(journal_view.property("calendarWeeks"), 54)
            bridge.perform("navigate", {"page": "orders"})
            self.app.processEvents()
            drawdown = window.findChild(QQuickItem, "tradeDrawdownCard")
            statuses = window.findChild(QQuickItem, "tradeStatusCard")
            self.assertIsNotNone(drawdown)
            self.assertIsNotNone(statuses)
            self.assertAlmostEqual(drawdown.mapToScene(QPointF(0, 0)).y(),
                                   statuses.mapToScene(QPointF(0, 0)).y(), delta=2)
            self.assertAlmostEqual(drawdown.height(), statuses.height(), delta=2)
            self.assertFalse(window.grabWindow().isNull())
            window.close()
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
