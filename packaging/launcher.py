"""Minimal frozen entry point; do not import the legacy QWidget application."""

from mt5_workbench.ui.qml_app import main

if __name__ == "__main__":
    raise SystemExit(main())
