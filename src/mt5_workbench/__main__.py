"""Run the desktop workbench with ``python -m mt5_workbench``."""

from __future__ import annotations

import sys

from mt5_workbench.ui.main_window import main


if __name__ == "__main__":
    sys.exit(main())
