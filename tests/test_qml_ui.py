"""Offline Qt Quick integration smoke test for every workbench page."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "FluentWinUI3")

from PySide6.QtCore import QPointF, QUrl, QMetaObject, Q_ARG, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from mt5_workbench.ui.qml_bridge import PAGE_NAMES
from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge


def visual_find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = visual_find(child, name)
        if found is not None:
            return found
    return None


class QmlUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def test_seven_pages_theme_and_window_size_load_without_mt5(self):
        bridge = QmlTradingBridge(autoconnect=False, start_timer=False,
                                  journal_repository=object())
        bridge._set_state(theme="light")
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
            bridge.perform("navigate", {"page": "optimizer"})
            self.app.processEvents()
            entry_view = window.findChild(QQuickItem, "orderEntryView")
            self.assertEqual(entry_view.property("currentTab"), 0)
            basic_view = window.findChild(QQuickItem, "basicOrderEntryView")
            volume_field = visual_find(window.contentItem(), "basicOrderField_volume")
            stop_field = visual_find(window.contentItem(), "basicOrderField_sl")
            preview_button = window.findChild(QQuickItem, "basicOrderPreviewButton")
            self.assertEqual(volume_field.property("text"), "0.5")
            self.assertIn("止损", stop_field.property("placeholderText"))
            bridge._set_state(connection={"connected": True, "locked": False})
            QMetaObject.invokeMethod(basic_view, "updateField",
                                     Q_ARG("QVariant", "price"), Q_ARG("QVariant", "4190"))
            for stop, enabled in (("", False), ("  ", False), ("0", False),
                                  ("-1", False), ("NaN", False), ("Infinity", False),
                                  ("4180", True), ("", False)):
                QMetaObject.invokeMethod(basic_view, "updateField",
                                         Q_ARG("QVariant", "sl"), Q_ARG("QVariant", stop))
                self.app.processEvents()
                self.assertEqual(preview_button.property("enabled"), enabled)
            QMetaObject.invokeMethod(basic_view, "updateField",
                                     Q_ARG("QVariant", "volume"), Q_ARG("QVariant", "0.01"))
            self.app.processEvents()
            self.assertEqual(volume_field.property("text"), "0.01")
            bridge._set_state(account={"login": 202, "server": "test-server"},
                              connection={"connected": False, "locked": False})
            self.app.processEvents()
            self.assertEqual(volume_field.property("text"), "0.5")
            self.assertEqual(stop_field.property("text"), "")
            self.assertFalse(preview_button.property("enabled"))
            for width in (1200, 1440, 2560):
                window.setWidth(width)
                self.app.processEvents()
                form_card = window.findChild(QQuickItem, "basicOrderFormCard")
                market_card = window.findChild(QQuickItem, "basicOrderMarketCard")
                self.assertGreater(form_card.width(), 300)
                form_pos = form_card.mapToScene(QPointF(0, 0))
                market_pos = market_card.mapToScene(QPointF(0, 0))
                if width == 1200:
                    self.assertGreater(market_pos.y(), form_pos.y())
                else:
                    self.assertAlmostEqual(form_pos.y(), market_pos.y(), delta=2)
                self.assertLessEqual(market_pos.x() + market_card.width(), width - 20)
            QMetaObject.invokeMethod(entry_view, "selectTab", Q_ARG("QVariant", 1))
            self.app.processEvents()
            self.assertEqual(entry_view.property("currentTab"), 1)
            mode_selector = window.findChild(QQuickItem, "entryModeSelector")
            self.assertIsNotNone(mode_selector)
            self.assertEqual(mode_selector.property("displayText"),
                             "加权分配 · 自定义风险比例")
            self.assertEqual(mode_selector.property("contentItem").property("color").name(),
                             "#172a40")
            self.assertEqual(mode_selector.property("background").property("color").name(),
                             "#edf2f8")
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
            self.assertEqual(mode_selector.property("contentItem").property("color").name(),
                             "#f3f7fb")
            self.assertEqual(mode_selector.property("background").property("color").name(),
                             "#1d2e45")
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
            bridge.perform("navigate", {"page": "controls"})
            for width in (1200, 2560):
                window.setWidth(width)
                self.app.processEvents()
                breakeven = window.findChild(QQuickItem, "controlBreakevenCard")
                batch_stops = window.findChild(QQuickItem, "controlBatchStopsCard")
                self.assertIsNotNone(breakeven)
                self.assertIsNotNone(batch_stops)
                be_pos = breakeven.mapToScene(QPointF(0, 0))
                batch_pos = batch_stops.mapToScene(QPointF(0, 0))
                if width == 1200:
                    self.assertAlmostEqual(be_pos.x(), batch_pos.x(), delta=2)
                    self.assertGreater(batch_pos.y(), be_pos.y())
                else:
                    self.assertAlmostEqual(be_pos.y(), batch_pos.y(), delta=2)
                    self.assertGreater(batch_pos.x(), be_pos.x())
            self.assertFalse(window.grabWindow().isNull())
            bridge._set_state(controls={"accountLabel": "账户 101 · fake · USC", "loading": False,
                "positions": [{"ticket": str(ticket), "symbol": "XAUUSDc", "side": "BUY",
                    "volume": "0.01", "openPrice": "4000", "sl": "—", "tp": "4250", "profit": "0"}
                    for ticket in (123, 124)], "orders": []})
            self.app.processEvents()
            control_view = window.findChild(QQuickItem, "controlView")
            first_check = visual_find(window.contentItem(), "controlPositionCheck_123")
            self.assertEqual(first_check.parentItem().parentItem().property("color").name(), "#172438")
            select_all = window.findChild(QQuickItem, "controlSelectAllPositions")
            self.assertEqual(control_view.property("selectedTickets").toVariant(), ["123", "124"])
            for item, expected in ((first_check, ["124"]), (select_all, ["123", "124"]), (select_all, [])):
                point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
                QTest.mouseClick(window, Qt.LeftButton, Qt.NoModifier, point)
                self.app.processEvents()
                self.assertEqual(control_view.property("selectedTickets").toVariant(), expected)
                if expected == ["124"]:
                    snapshot = bridge.state["controls"]
                    bridge._set_state(controls={**snapshot, "loading": True})
                    self.app.processEvents()
                    self.assertEqual(control_view.property("selectedTickets").toVariant(), ["124"])
                    bridge._set_state(controls={**snapshot, "loading": False,
                        "positions": [{**row, "profit": "25.50"} for row in snapshot["positions"]]})
                    self.app.processEvents()
                    self.assertEqual(control_view.property("selectedTickets").toVariant(), ["124"])
                    row = visual_find(window.contentItem(), "controlPositionRow_0")
                    texts = [cell.property("text") for layout in row.childItems()
                             for cell in layout.childItems() if cell.inherits("QQuickText")]
                    self.assertIn("25.50", texts)
            bridge._set_state(confirmation={"token": "preview-only", "selectable": True,
                "selectedTickets": ["123", "124"], "columns": ["Ticket", "品种", "止盈"],
                "rows": [["123", "XAUUSDc BUY", "4250"], ["124", "XAUUSDc BUY", "4250"]]})
            self.app.processEvents()
            self.assertIsNotNone(visual_find(window.contentItem(), "protectionConfirmCheck_123"))
            bridge._set_state(confirmation={})
            window.close()
        finally:
            bridge.close()


if __name__ == "__main__":
    unittest.main()
