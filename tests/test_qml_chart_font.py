"""Exercise Canvas font parsing with real chart data and no MT5 connection."""

from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QUrl, qInstallMessageHandler
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class QmlChartFontTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_populated_charts_do_not_report_invalid_font_families(self):
        # Windows offscreen does not enumerate system fonts. Register YaHei so
        # Context2D validates the actual family instead of accepting a fallback.
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc"
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        if font_id < 0:
            self.skipTest("Microsoft YaHei font file is unavailable")
        messages = []
        previous_handler = qInstallMessageHandler(
            lambda kind, context, message: messages.append(message))
        engine = QQmlApplicationEngine()
        qml_dir = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml"
        try:
            engine.loadData(b'''
                import QtQuick
                import QtQuick.Window
                Window {
                    id: root
                    visible: true
                    width: 1200; height: 800
                    property bool dark: false
                    property string chartMode: "line"
                    Theme { id: theme; dark: root.dark }
                    DataChart {
                        anchors.fill: parent
                        ui: theme
                        mode: root.chartMode
                        points: [
                            {day: "2026-10-01", cumulative: 12,
                             open: 4200, high: 4202, low: 4199, close: 4201},
                            {day: "2026-10-02", cumulative: -5,
                             open: 4201, high: 4203, low: 4198, close: 4199}
                        ]
                    }
                }
            ''', QUrl.fromLocalFile(str(qml_dir / "ChartFontTest.qml")))
            self.assertEqual(len(engine.rootObjects()), 1, messages)
            window = engine.rootObjects()[0]
            self.assertIsInstance(window, QQuickWindow)
            for dark in (False, True):
                window.setProperty("dark", dark)
                for width, height in ((1200, 800), (2560, 1440)):
                    window.resize(width, height)
                    for mode in ("line", "bars", "candles"):
                        window.setProperty("chartMode", mode)
                        QTest.qWait(50)
                        self.assertFalse(window.grabWindow().isNull())
            self.assertEqual(
                [message for message in messages
                 if "Context2D" in message and "font families" in message], [])
            self.assertEqual([message for message in messages if "Error:" in message], [])
        finally:
            for window in engine.rootObjects():
                window.close()
            del engine
            qInstallMessageHandler(previous_handler)
            QFontDatabase.removeApplicationFont(font_id)


if __name__ == "__main__":
    unittest.main()
