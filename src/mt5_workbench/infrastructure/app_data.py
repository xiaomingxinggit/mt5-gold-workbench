"""Initialize permanent user storage and copy legacy data before loading the UI."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from mt5_workbench.config import legacy_state_directory, state_directory

SUBDIRECTORIES = ("executions", "controls", "journal/images", "journal/drafts")


def _copy_file(source, destination):
    """SQLite backup includes committed WAL data without editing the old DB."""
    source, destination = Path(source), Path(destination)
    if source.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
        return shutil.copy2(source, destination)
    deadline = time.monotonic() + 15

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise RuntimeError("旧日志数据库正被占用，请关闭旧版工作台后重试。")

    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as old:
        with closing(sqlite3.connect(destination)) as new:
            old.backup(new, pages=128, progress=progress)
            if new.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("旧日志数据库校验失败，已保留原数据。")
    return str(destination)


def _validate_images(directory: Path, legacy: Path):
    for database in directory.rglob("*.sqlite3"):
        with closing(sqlite3.connect(database)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ("post_images", "reply_images"):
                if table in tables:
                    for (filename,) in db.execute(f"SELECT filename FROM {table}"):
                        relative = database.parent.relative_to(directory) / "images" / Path(filename).name
                        if (legacy / relative).is_file() and not (directory / relative).is_file():
                            raise RuntimeError("日志图片复制不完整，已保留原数据，请重试。")


def _preserve_execution_records(legacy: Path, destination: Path):
    """Keep duplicate-send reservations even if user storage already exists."""
    for source in (legacy / "executions").rglob("*.json"):
        target = destination / "executions" / source.relative_to(legacy / "executions")
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".import-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle, source.open("rb") as original:
                shutil.copyfileobj(original, handle)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)


def prepare_state_directory(*, destination: Path | None = None,
                            legacy: Path | None = None, migrate: bool = True) -> Path:
    """Copy first-run state atomically; keep originals and existing user data."""
    destination = Path(destination if destination is not None else state_directory()).resolve()
    legacy = Path(legacy if legacy is not None else legacy_state_directory()).resolve()
    has_legacy = migrate and legacy.is_dir() and legacy != destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and any(destination.iterdir()):
        for subdirectory in SUBDIRECTORIES:
            (destination / subdirectory).mkdir(parents=True, exist_ok=True)
        if has_legacy:
            _preserve_execution_records(legacy, destination)
        return destination

    staging = Path(tempfile.mkdtemp(prefix=".state-migration-", dir=destination.parent))
    try:
        if has_legacy:
            shutil.copytree(legacy, staging, dirs_exist_ok=True, copy_function=_copy_file,
                            ignore=shutil.ignore_patterns("*-wal", "*-shm"))
            _validate_images(staging, legacy)
        for subdirectory in SUBDIRECTORIES:
            (staging / subdirectory).mkdir(parents=True, exist_ok=True)
        (staging / "storage.json").write_text(json.dumps({
            "schema": 1, "createdAt": datetime.now(timezone.utc).isoformat(),
            "migratedFrom": str(legacy) if has_legacy else "",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        if destination.exists():
            destination.rmdir()
        staging.rename(destination)
    finally:
        # Only remove the task-created staging folder inside the application root.
        if (staging.exists() and staging.resolve().parent == destination.parent.resolve()
                and staging.name.startswith(".state-migration-")):
            shutil.rmtree(staging)
    return destination
