"""Populated-page theme regression; no terminal or trading API is called."""
from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "FluentWinUI3")

from PySide6.QtCore import QUrl, QMetaObject, Q_ARG, QPointF, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication

from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge
from tests.test_qml_ui import visual_find


def populated_state():
    positions = [{"ticket": 101 + i, "positionId": 101 + i,
                  "symbol": "XAUUSDc", "side": "SELL", "volume": 0.01,
                  "price": 4200 + i, "priceOpen": 4200 + i, "openPrice": 4200 + i,
                  "stop": 4220, "sl": 4220, "tp": 4180,
                  "takeProfit": 4180, "profit": 10 - i * 20,
                  "floatingUsd": 0.1 - i * 0.2} for i in range(2)]
    orders = [{"ticket": 201 + i, "symbol": "XAUUSDc", "type": "SELL LIMIT",
               "volume": 0.01, "volumeCurrent": 0.01, "volumeInitial": 0.01,
               "price": 4210 + i, "priceOpen": 4210 + i,
               "stop": 4220, "sl": 4220, "tp": 4180, "status": "已成交",
               "createdAt": "2026-10-06 10:00"} for i in range(2)]
    curve = [{"day": f"2026-10-{i + 1:02}", "cumulative": i * 25 - (i % 3) * 30,
              "drawdown": -(i % 3) * 30, "dealCount": i % 3, "amount": (i % 3 - 1) * 25}
             for i in range(6)]
    return {
        "account": {"login": 123, "server": "TestServer", "currency": "USC",
                    "balance": 30000, "equity": 30010, "profit": 10,
                    "marginFree": 29000, "marginLevel": 3000},
        "connection": {"connected": True, "locked": False, "message": "已连接"},
        "market": {"symbol": "XAUUSDc", "bid": 4200, "ask": 4200.2,
                   "spreadPoints": 200, "change": -10, "changePct": -0.24,
                   "stale": False, "time": "10:00:00"},
        "dashboard": {"positions": positions, "orders": orders, "dailyPnl": curve,
                      "candles": [{"time": f"10:{i * 5:02}", "open": 4200 + i,
                                   "close": 4201 + i, "high": 4202 + i,
                                   "low": 4199 + i} for i in range(6)]},
        "overview": {"accountCurve": curve, "dailyExecution": curve,
                     "pendingOrders": orders, "recentOrders": orders,
                     "recentDeals": [{"ticket": 301, "executedAt": "10:00",
                                      "side": "SELL", "volume": 0.01,
                                      "price": 4200, "cashflow": -25}],
                     "statusCounts": [{"label": "已成交", "count": 2}],
                     "metrics": {"pendingCount": 2, "positionCount": 2}},
        "controls": {"accountLabel": "测试账户 · USC", "summary": "持仓 2 笔 · 挂单 2 笔",
                     "scope": "symbol", "positions": positions, "orders": orders,
                     "accountKey": "123@TestServer"},
        "optimizer": {"rows": [{"level": i + 1, "type": "SELL LIMIT",
                                "price": 4210 + i, "volume": 0.01,
                                "stopDistance": 10 - i, "riskUsd": 0.1}
                               for i in range(2)], "lot": "0.02", "risk": "0.20 USD"},
        "journal": {"canPublish": True, "accountKey": "123@TestServer",
                    "positions": positions, "total": 1, "recent30": 1, "activeDays": 1,
                    "year": 2026, "years": [2026, 2025], "yearTotal": 1,
                    "heatmap": {"2026-10-06": 1},
                    "posts": [{"id": 1, "dateLabel": "2026-10-06", "timeLabel": "10:00",
                               "body": "测试日志：记录行情与交易过程。", "images": [],
                               "positions": [{**positions[0], "status": "closed", "resultUsd": -0.25}],
                               "replies": [{"id": 1, "body": "测试回复", "dateLabel": "2026-10-06",
                                            "timeLabel": "10:05", "images": []}]}]},
        "monitor": {"status": "EMA 聚拢", "reason": "模拟行情", "bid": 4200,
                    "ask": 4200.2, "emaValues": {str(n): 4200.01 for n in (7, 14, 30, 60)},
                    "emaSpreadPoints": 1, "quoteAgeSeconds": 0.1,
                    "history": [{"time": "10:00", "status": "EMA 聚拢", "spreadPoints": 1}]},
    }


def visual_items(item):
    yield item
    for child in item.childItems():
        yield from visual_items(child)


class QmlThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_populated_pages_dropdowns_and_theme_switch(self):
        bridge = QmlTradingBridge(autoconnect=False, start_timer=False,
                                  journal_repository=object())
        for section, value in populated_state().items():
            bridge._set_state(**{section: {**bridge.state.get(section, {}), **value}})
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        engine.rootContext().setContextProperty("bridge", bridge)
        path = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml/App.qml"
        engine.load(QUrl.fromLocalFile(str(path)))
        try:
            self.assertEqual(len(engine.rootObjects()), 1, warnings)
            window = engine.rootObjects()[0]
            window.resize(2560, 1440)
            find = lambda name: visual_find(window.contentItem(), name)
            entry = find("orderEntryView")
            QMetaObject.invokeMethod(entry, "selectTab", Q_ARG("QVariant", 1))
            bridge._set_state(optimizer=populated_state()["optimizer"])
            find("advancedOrderEntryView").setProperty("resultStale", False)
            journal = find("journalView")
            journal.setProperty("composing", True)
            for theme, surface, alternate, text in (
                ("dark", "#172438", "#1d2e45", "#f3f7fb"),
                ("light", "#ffffff", "#edf2f8", "#172a40"),
                ("dark", "#172438", "#1d2e45", "#f3f7fb"),
            ):
                bridge._set_state(theme=theme)
                for page in ("dashboard", "orders", "journal", "optimizer", "controls", "monitor"):
                    bridge._set_state(page=page)
                    QTest.qWait(30)
                    self.assertFalse(window.grabWindow().isNull())
                    for bar in visual_items(window.contentItem()):
                        if bar.inherits("QQuickScrollBar") and bar.isVisible() and bar.property("ui"):
                            self.assertAlmostEqual(bar.height(), bar.parentItem().height(), delta=1)
                            self.assertAlmostEqual(bar.x() + bar.width(), bar.parentItem().width(), delta=1,
                                                   msg=f"{page}: {bar.parentItem().metaObject().className()}")
                for prefix in ("advancedOrderResultRow_", "controlPendingOrderRow_", "recordRow_当前挂单_"):
                    for index, expected in enumerate((surface, alternate)):
                        row = find(prefix + str(index))
                        self.assertIsNotNone(row, prefix)
                        self.assertEqual(row.property("color").name(), expected)
                for ticket, expected in ((101, surface), (102, alternate)):
                    check = find(f"controlPositionCheck_{ticket}")
                    self.assertEqual(check.parentItem().parentItem().property("color").name(), expected)
                    self.assertEqual(check.property("contentItem").property("color").name(), text)
                columns = []
                for index in (0, 1):
                    row = find(f"controlPositionRow_{index}")
                    cells = [item for item in visual_items(row) if item.inherits("QQuickText")
                             and item.property("text") != "✓" and item.property("text") != ""]
                    columns.append([cell.mapToScene(QPointF(0, 0)).x() for cell in cells])
                self.assertEqual(len(columns[0]), 8)
                for first, second in zip(*columns):
                    self.assertAlmostEqual(first, second, delta=1)
                self.assertEqual(find("journalPositionCheck_101").property("contentItem").property("color").name(), text)
                for page, name in (("orders", "tradePeriodSelector"), ("journal", "journalYearSelector"),
                                   ("optimizer", "entryModeSelector")):
                    bridge._set_state(page=page)
                    QTest.qWait(30)
                    selector = find(name)
                    self.assertEqual(selector.property("contentItem").property("color").name(), text)
                    content = selector.property("contentItem")
                    self.assertGreaterEqual(content.width(), content.implicitWidth(), name)
                    center = selector.mapToScene(QPointF(selector.width() / 2, selector.height() / 2))
                    QTest.mouseClick(window, Qt.LeftButton, pos=center.toPoint())
                    QTest.qWait(30)
                    self.assertEqual(find(name + "PopupBackground").property("color").name(), surface)
                    option = find(name + "Option_0")
                    self.assertIsNotNone(option, name)
                    self.assertEqual(option.property("contentItem").property("color").name(), text)
                    QTest.keyClick(window, Qt.Key_Escape)
                bridge._set_state(confirmation={"token": "test", "title": "测试确认",
                                  "selectable": True, "selectedTickets": ["101"],
                                  "columns": ["Ticket", "价格"], "rows": [["101", "4200"]]})
                QTest.qWait(30)
                self.assertEqual(find("protectionConfirmCheck_101").property("contentItem").property("color").name(), text)
                bridge._set_state(confirmation={})
            # A fixed Theme QObject does not emit uiChanged. Canvas must repaint on darkChanged.
            bridge._set_state(page="dashboard")
            QTest.qWait(50)
            canvas = window.findChild(QQuickItem, "dataChartCanvas")
            meta = canvas.metaObject()
            spy = QSignalSpy(canvas, meta.method(meta.indexOfSignal("painted()")))
            self.assertTrue(spy.isValid())
            bridge._set_state(theme="light")
            QTest.qWait(80)
            self.assertGreater(spy.count(), 0)
            self.assertEqual(warnings, [])
        finally:
            if engine.rootObjects():
                engine.rootObjects()[0].close()
            bridge.close()


if __name__ == "__main__":
    unittest.main()
