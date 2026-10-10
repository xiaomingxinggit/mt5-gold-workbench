"""Qt Quick entry point for the modern MT5 workbench."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QFontDatabase
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from mt5_workbench.config import DEFAULT_SYMBOL
from mt5_workbench import __version__
from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, choices=[DEFAULT_SYMBOL])
    parser.add_argument("--terminal", help="可选的 terminal64.exe 路径")
    parser.add_argument("--smoke-test", metavar="DIRECTORY", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["QT_QUICK_BACKEND"] = "software"
    # Set the Qt Quick Controls style before loading any Controls QML type.
    QQuickStyle.setStyle("FluentWinUI3")
    app = QApplication.instance() or QApplication(sys.argv)
    if args.smoke_test:
        # The offscreen Windows plugin does not enumerate installed fonts.
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for font in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
            if (fonts / font).is_file():
                QFontDatabase.addApplicationFont(str(fonts / font))
    app.setApplicationName("MT5 黄金交易工作台")
    app.setApplicationVersion(__version__)
    bridge = QmlTradingBridge(args.symbol, args.terminal,
                              **({"autoconnect": False, "start_timer": False,
                                  "journal_repository": object()} if args.smoke_test else {}))
    engine = QQmlApplicationEngine()
    warnings = []
    if args.smoke_test:
        engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
    qml_dir = Path(__file__).resolve().parent / "qml"
    engine.addImportPath(str(qml_dir))
    engine.rootContext().setContextProperty("bridge", bridge)
    app.aboutToQuit.connect(bridge.close)
    engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
    if not engine.rootObjects():
        bridge.close()
        return 1
    if args.smoke_test:
        def verify():
            output = Path(args.smoke_test).resolve()
            output.mkdir(parents=True, exist_ok=True)
            window = engine.rootObjects()[0]
            bridge.perform("navigate", {"page": "settings"})
            app.processEvents()
            screenshot = window.grabWindow()
            image_ok = not screenshot.isNull() and screenshot.save(str(output / "settings.png"))
            result = {"ok": bool(image_ok and not warnings), "version": __version__,
                      "warnings": warnings, "stateDirectory": bridge.state["system"]["stateDirectory"]}
            (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            app.exit(0 if result["ok"] else 1)
        QTimer.singleShot(1200, verify)
    else:
        bridge.updates.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
