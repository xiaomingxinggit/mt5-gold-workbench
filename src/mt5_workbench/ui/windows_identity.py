"""Give Windows a stable app identity instead of grouping us with Python."""

from __future__ import annotations

import ctypes
import logging
import sys


APP_USER_MODEL_ID = "MT5Workbench.Desktop"


def configure_taskbar_identity() -> bool | None:
    """Call before QApplication creates windows; keep the ID across releases.

    None means the platform has no Windows taskbar. Identity registration is
    cosmetic: a Windows API failure is reported without preventing startup.
    """
    if sys.platform != "win32":
        return None
    try:
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        set_app_id = shell.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long  # signed 32-bit HRESULT on Windows
        result = set_app_id(APP_USER_MODEL_ID)
        if result < 0:
            logging.getLogger(__name__).warning(
                "Windows taskbar identity registration failed: HRESULT 0x%08X",
                result & 0xFFFFFFFF)
            return False
        return True
    except (AttributeError, OSError) as exc:
        logging.getLogger(__name__).warning("Cannot register Windows taskbar identity: %s", exc)
        return False
