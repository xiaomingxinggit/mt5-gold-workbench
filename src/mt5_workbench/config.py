"""Application-wide defaults and local state location."""

from pathlib import Path
import os
import sys

DEFAULT_SYMBOL = "XAUUSDc"
TEXT_ENCODING = "utf-8"
DEFAULT_REFRESH_INTERVALS = {"quote": 1, "positions": 5, "orders": 30}
MAX_REFRESH_SECONDS = 3600


def state_directory(kind: str = "") -> Path:
    """Stable per-user storage, shared by source and packaged applications."""
    override = os.environ.get("MT5_WORKBENCH_DATA_DIR")
    base = (Path(override).expanduser() if override else
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "MT5Workbench")
    return base / "state" / kind


def legacy_state_directory() -> Path:
    """Previous versions stored state beside their source or executable."""
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2])
    return base / "state"
