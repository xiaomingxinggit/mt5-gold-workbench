"""Qt Quick entry point for the modern MT5 workbench."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from mt5_workbench.config import DEFAULT_SYMBOL
from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, choices=[DEFAULT_SYMBOL])
    parser.add_argument("--terminal", help="可选的 terminal64.exe 路径")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    # Set the Qt Quick Controls style before loading any Controls QML type.
    QQuickStyle.setStyle("FluentWinUI3")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MT5 黄金交易工作台")
    bridge = QmlTradingBridge(args.symbol, args.terminal)
    engine = QQmlApplicationEngine()
    qml_dir = Path(__file__).resolve().parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.rootContext().setContextProperty("bridge", bridge)
    app.aboutToQuit.connect(bridge.close)
    engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
    if not engine.rootObjects():
        bridge.close()
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
