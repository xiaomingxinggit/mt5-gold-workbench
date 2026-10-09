"""Persistent application system preferences, independent of MT5 access."""

from datetime import datetime, timedelta, timezone
import json
import locale
import os
from pathlib import Path
import platform
import sys
import tempfile

from mt5_workbench.config import TEXT_ENCODING, state_directory


DEFAULT_TIME_ZONE = "UTC+08:00"
TIME_ZONES = ["local", "UTC"] + [
    f"UTC{'+' if hour >= 0 else '-'}{abs(hour):02d}:00"
    for hour in range(-12, 15) if hour != 0
]


def settings_path() -> Path:
    return state_directory("system_settings.json")


def load_time_zone() -> str:
    try:
        saved = json.loads(settings_path().read_text(encoding=TEXT_ENCODING))
        if isinstance(saved, dict) and saved.get("timeZone") in TIME_ZONES:
            return saved["timeZone"]
    except (OSError, ValueError, UnicodeError):
        pass
    return DEFAULT_TIME_ZONE


def save_time_zone(name: str) -> bool:
    if name not in TIME_ZONES:
        return False
    path = settings_path()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding=TEXT_ENCODING, dir=path.parent,
            prefix=".system_settings-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"timeZone": name, "textEncoding": TEXT_ENCODING}, stream,
                      ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def clock_snapshot(name: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone()
    offset = (0 if name == "UTC" else
              int(local.utcoffset().total_seconds() / 60) if name == "local" else
              int(name[4:6]) * 60 * (1 if name[3] == "+" else -1))
    zone = timezone(timedelta(minutes=offset))
    selected = now.astimezone(zone)
    label = selected.strftime("UTC%z")
    label = label[:-2] + ":" + label[-2:]
    return {
        "systemTime": local.strftime("%Y-%m-%d %H:%M:%S"),
        "systemTimeZone": local.strftime("%Z (UTC%z)"),
        "displayTime": selected.strftime("%Y-%m-%d %H:%M:%S"),
        "utcTime": now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "timeZone": name, "timeZoneLabel": label, "offsetMinutes": offset,
    }


def system_snapshot(name: str, terminal_path: str | None, symbol: str) -> dict:
    return {
        **clock_snapshot(name), "timeZoneChoices": TIME_ZONES,
        "textEncoding": TEXT_ENCODING.upper(), "systemEncoding": locale.getencoding(),
        "pythonUtf8Mode": bool(sys.flags.utf8_mode),
        "platform": f"{platform.system()} {platform.release()}",
        "pythonVersion": platform.python_version(),
        "stateDirectory": str(state_directory()),
        "journalDirectory": str(state_directory("journal")),
        "terminalPath": terminal_path or "自动连接本机 MT5 客户端",
        "symbol": symbol, "accountCurrency": "USC", "currencyRatio": "100 USC = 1 USD",
    }
