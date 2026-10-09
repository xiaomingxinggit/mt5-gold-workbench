"""Application-wide defaults and local state location."""

from pathlib import Path
import sys

DEFAULT_SYMBOL = "XAUUSDc"
TEXT_ENCODING = "utf-8"
DEFAULT_REFRESH_INTERVALS = {"quote": 1, "positions": 5, "orders": 30}
MAX_REFRESH_SECONDS = 3600


def state_directory(kind: str = "") -> Path:
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[2])
    return base / "state" / kind
