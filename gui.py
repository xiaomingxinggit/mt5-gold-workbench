"""Compatibility launcher for the installed ``mt5_workbench`` package."""

from __future__ import annotations

import sys
from pathlib import Path

# Keep the historical source-checkout command working before editable install.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from mt5_workbench.ui.main_window import App, MainWindow, main, state_directory


if __name__ == "__main__":
    sys.exit(main())
