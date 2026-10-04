"""SQLite-backed, account-scoped storage for the local market journal."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3
from typing import Iterator, Sequence
from uuid import uuid4

from PySide6.QtGui import QImage

from mt5_workbench.domain.journal import (
    AccountKey,
    JournalPage,
    JournalPost,
    PositionLink,
    PositionSnapshot,
)


MAX_POST_LENGTH = 2100
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_LINKED_POSITIONS = 20
MAX_PAGE_SIZE = 100

_IMAGE_TYPES = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
    ".gif": "gif",
}

_LINKS_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS position_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
        account_login INTEGER NOT NULL,
        account_server TEXT NOT NULL,
        position_id INTEGER NOT NULL,
        ticket INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        volume TEXT NOT NULL,
        price_open TEXT NOT NULL,
        opened_at TEXT NOT NULL,
        sl TEXT,
        tp TEXT,
        floating_usc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('open', 'unverified', 'closed')),
        result_usc TEXT,
        closed_at TEXT,
        linked_at TEXT NOT NULL,
        UNIQUE(post_id, position_id)
    )
"""

_LINKS_COLUMNS = (
    "id, post_id, account_login, account_server, position_id, ticket, symbol, "
    "side, volume, price_open, opened_at, sl, tp, floating_usc, status, "
    "result_usc, closed_at, linked_at"
)


def _image_format(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"
    return None


def _validate_account(account_key: AccountKey) -> AccountKey:
    if (
        not isinstance(account_key, tuple)
        or len(account_key) != 2
        or not isinstance(account_key[0], int)
        or isinstance(account_key[0], bool)
        or account_key[0] <= 0
        or not isinstance(account_key[1], str)
        or not account_key[1].strip()
    ):
        raise ValueError("账号标识必须包含有效的登录号和服务器名称")
    return account_key[0], account_key[1].strip()


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise ValueError("时间必须是 datetime")
    # MT5 history usually arrives as UTC. Naive values are interpreted as local
    # time, matching datetime.astimezone() and the desktop's journal calendar.
    return value.astimezone().isoformat(timespec="microseconds")


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    number = Decimal(value)
    if not number.is_finite():
        raise ValueError("数值必须为有限数字")
    return str(number)


def _read_position(row: sqlite3.Row) -> PositionLink:
    return PositionLink(
        position_id=row["position_id"],
        ticket=row["ticket"],
        symbol=row["symbol"],
        side=row["side"],
        volume=Decimal(row["volume"]),
        price_open=Decimal(row["price_open"]),
        opened_at=datetime.fromisoformat(row["opened_at"]),
        sl=Decimal(row["sl"]) if row["sl"] is not None else None,
        tp=Decimal(row["tp"]) if row["tp"] is not None else None,
        floating_usc=Decimal(row["floating_usc"]),
        account_key=(row["account_login"], row["account_server"]),
        post_id=row["post_id"],
        status=row["status"],
        result_usc=Decimal(row["result_usc"]) if row["result_usc"] is not None else None,
        closed_at=(datetime.fromisoformat(row["closed_at"])
                   if row["closed_at"] is not None else None),
        linked_at=datetime.fromisoformat(row["linked_at"]),
    )


class JournalRepository:
    """The only persistence boundary for journal posts and linked positions.

    A repository directory contains ``journal.sqlite3`` and copied pictures in
    ``images/``. Account login and server jointly scope every write and read.
    Passing ``None`` to the two feed queries produces an empty disconnected view.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.images_dir = self.base_dir / "images"
        self.db_path = self.base_dir / "journal.sqlite3"
        self.images_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_login INTEGER NOT NULL,
                    account_server TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE INDEX IF NOT EXISTS ix_posts_account_created
                    ON posts(account_login, account_server, id DESC)
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS post_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    filename TEXT NOT NULL UNIQUE,
                    UNIQUE(post_id, ordinal)
                )
            """)
            existing = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='position_links'"
            ).fetchone()
            if existing is None:
                db.execute(_LINKS_TABLE_DDL)
            else:
                columns = {row["name"] for row in db.execute(
                    "PRAGMA table_info(position_links)")}
                required = {"account_login", "account_server", "linked_at"}
                if not required.issubset(columns) or "'unverified'" not in existing["sql"]:
                    self._migrate_links(db, columns)
            db.execute("""
                CREATE INDEX IF NOT EXISTS ix_links_open
                    ON position_links(account_login, account_server, status, position_id)
            """)

    @staticmethod
    def _migrate_links(db: sqlite3.Connection, columns: set[str]) -> None:
        """Preserve existing links while adding account identity and sync state."""
        account_login = ("old.account_login" if "account_login" in columns
                         else "post.account_login")
        account_server = ("old.account_server" if "account_server" in columns
                          else "post.account_server")
        linked_at = ("old.linked_at" if "linked_at" in columns
                     else "post.created_at")
        db.execute("ALTER TABLE position_links RENAME TO position_links_legacy")
        db.execute(_LINKS_TABLE_DDL)
        db.execute(f"""
            INSERT INTO position_links ({_LINKS_COLUMNS})
            SELECT old.id, old.post_id, {account_login}, {account_server},
                   old.position_id, old.ticket, old.symbol, old.side, old.volume,
                   old.price_open, old.opened_at, old.sl, old.tp,
                   old.floating_usc, old.status, old.result_usc,
                   old.closed_at, {linked_at}
            FROM position_links_legacy AS old
            JOIN posts AS post ON post.id=old.post_id
        """)
        db.execute("DROP TABLE position_links_legacy")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA busy_timeout = 10000")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _check_image(source: Path) -> tuple[Path, str]:
        source = Path(source).expanduser()
        if not source.is_file():
            raise ValueError(f"图片不存在：{source}")
        expected = _IMAGE_TYPES.get(source.suffix.lower())
        if expected is None:
            raise ValueError("仅支持 PNG、JPEG、WebP 和 GIF 图片")
        size = source.stat().st_size
        if not 0 < size <= MAX_IMAGE_BYTES:
            raise ValueError("单张图片不得超过 8 MiB")
        with source.open("rb") as stream:
            actual = _image_format(stream.read(16))
        if actual != expected:
            raise ValueError("图片内容与扩展名不符")
        image = QImage.fromData(source.read_bytes())
        if (image.isNull() or image.width() * image.height() > 40_000_000):
            raise ValueError("图片无法完整读取或尺寸过大")
        return source, source.suffix.lower()

    def create_post(
        self,
        account_key: AccountKey,
        body: str,
        image_sources: Sequence[Path] = (),
        positions: Sequence[PositionSnapshot] = (),
    ) -> int:
        login, server = _validate_account(account_key)
        if not isinstance(body, str):
            raise ValueError("帖子内容必须是文字")
        body = body.strip()
        if len(body) > MAX_POST_LENGTH:
            raise ValueError(f"帖子内容最多 {MAX_POST_LENGTH} 字")
        if not body and not image_sources:
            raise ValueError("请输入内容或添加图片")
        if len(image_sources) > MAX_IMAGES:
            raise ValueError(f"每篇帖子最多 {MAX_IMAGES} 张图片")
        if len(positions) > MAX_LINKED_POSITIONS:
            raise ValueError(f"每篇帖子最多关联 {MAX_LINKED_POSITIONS} 笔持仓")
        if len({p.position_id for p in positions}) != len(positions):
            raise ValueError("同一笔持仓不能重复关联")
        if any(p.account_key is not None and p.account_key != (login, server)
               for p in positions):
            raise ValueError("关联持仓不属于当前账户")
        checked = [self._check_image(path) for path in image_sources]
        copied: list[str] = []
        try:
            for source, suffix in checked:
                filename = f"{uuid4().hex}{suffix}"
                destination = self.images_dir / filename
                # 'xb' refuses to overwrite an existing file, including an
                # improbable UUID collision. Copying is complete before commit.
                with source.open("rb") as inp, destination.open("xb") as out:
                    copied.append(filename)
                    shutil.copyfileobj(inp, out)
                if destination.stat().st_size > MAX_IMAGE_BYTES:
                    raise ValueError("单张图片不得超过 8 MiB")
                # Recheck the copied bytes as the original can change between
                # the first validation and the copy.
                self._check_image(destination)
            now = datetime.now().astimezone().isoformat(timespec="microseconds")
            with self._connection() as db:
                cursor = db.execute(
                    "INSERT INTO posts(account_login, account_server, body, created_at) "
                    "VALUES (?, ?, ?, ?)", (login, server, body, now),
                )
                post_id = int(cursor.lastrowid)
                db.executemany(
                    "INSERT INTO post_images(post_id, ordinal, filename) VALUES (?, ?, ?)",
                    [(post_id, i, filename) for i, filename in enumerate(copied)],
                )
                db.executemany("""
                    INSERT INTO position_links(
                        post_id, account_login, account_server, position_id,
                        ticket, symbol, side, volume, price_open, opened_at,
                        sl, tp, floating_usc, linked_at, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """, [
                    (
                        post_id, login, server, int(p.position_id), int(p.ticket),
                        p.symbol, p.side, _decimal(p.volume), _decimal(p.price_open),
                        _timestamp(p.opened_at), _decimal(p.sl), _decimal(p.tp),
                        _decimal(p.floating_usc), now,
                    ) for p in positions
                ])
            return post_id
        except Exception:
            for filename in copied:
                (self.images_dir / filename).unlink(missing_ok=True)
            raise

    def list_posts(
        self,
        account_key: AccountKey | None,
        page: int = 1,
        page_size: int = 10,
    ) -> JournalPage:
        if not isinstance(page, int) or page < 1:
            raise ValueError("页码必须大于零")
        if not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"每页数量必须在 1 到 {MAX_PAGE_SIZE} 之间")
        if account_key is None:
            return JournalPage((), 0, page, page_size)
        login, server = _validate_account(account_key)
        with self._connection() as db:
            total = db.execute(
                "SELECT COUNT(*) FROM posts WHERE account_login=? AND account_server=?",
                (login, server),
            ).fetchone()[0]
            rows = db.execute("""
                SELECT * FROM posts
                WHERE account_login=? AND account_server=?
                ORDER BY id DESC LIMIT ? OFFSET ?
            """, (login, server, page_size, (page - 1) * page_size)).fetchall()
            ids = [row["id"] for row in rows]
            images: dict[int, list[Path]] = {post_id: [] for post_id in ids}
            links: dict[int, list[PositionLink]] = {post_id: [] for post_id in ids}
            if ids:
                placeholders = ",".join("?" for _ in ids)
                for image in db.execute(
                    f"SELECT post_id, filename FROM post_images "
                    f"WHERE post_id IN ({placeholders}) ORDER BY ordinal", ids,
                ):
                    images[image["post_id"]].append(
                        self.images_dir / Path(image["filename"]).name
                    )
                for link in db.execute(
                    f"SELECT * FROM position_links "
                    f"WHERE post_id IN ({placeholders}) ORDER BY id", ids,
                ):
                    owner = next(row for row in rows if row["id"] == link["post_id"])
                    if (link["account_login"], link["account_server"]) == (
                            owner["account_login"], owner["account_server"]):
                        links[link["post_id"]].append(_read_position(link))
        posts = tuple(
            JournalPost(
                id=row["id"], account_key=(row["account_login"], row["account_server"]),
                body=row["body"], created_at=datetime.fromisoformat(row["created_at"]),
                images=tuple(images[row["id"]]), positions=tuple(links[row["id"]]),
            ) for row in rows
        )
        return JournalPage(posts, total, page, page_size)

    def activity(
        self, account_key: AccountKey | None, days: int = 365,
    ) -> dict[date, int]:
        if not isinstance(days, int) or not 1 <= days <= 3660:
            raise ValueError("统计天数必须在 1 到 3660 之间")
        today = date.today()
        start = today - timedelta(days=days - 1)
        counts = {start + timedelta(days=offset): 0 for offset in range(days)}
        if account_key is None:
            return counts
        login, server = _validate_account(account_key)
        with self._connection() as db:
            rows = db.execute("""
                SELECT substr(created_at, 1, 10) AS post_date, COUNT(*) AS count
                FROM posts WHERE account_login=? AND account_server=?
                  AND substr(created_at, 1, 10) >= ?
                GROUP BY post_date
            """, (login, server, start.isoformat())).fetchall()
        for row in rows:
            day = date.fromisoformat(row["post_date"])
            if day in counts:
                counts[day] = row["count"]
        return counts

    def open_links(self, account_key: AccountKey) -> tuple[PositionLink, ...]:
        login, server = _validate_account(account_key)
        with self._connection() as db:
            rows = db.execute("""
                SELECT link.* FROM position_links AS link
                JOIN posts AS post ON post.id = link.post_id
                WHERE post.account_login=? AND post.account_server=?
                  AND link.account_login=post.account_login
                  AND link.account_server=post.account_server
                  AND link.status IN ('open', 'unverified')
                ORDER BY link.id
            """, (login, server)).fetchall()
        return tuple(_read_position(row) for row in rows)

    def close_position(
        self,
        account_key: AccountKey,
        position_id: int,
        result_usc: Decimal,
        closed_at: datetime,
    ) -> int:
        login, server = _validate_account(account_key)
        value = _decimal(result_usc)
        if value is None:
            raise ValueError("平仓结果不能为空")
        timestamp = _timestamp(closed_at)
        with self._connection() as db:
            cursor = db.execute("""
                UPDATE position_links SET status='closed', result_usc=?, closed_at=?
                WHERE position_id=? AND account_login=? AND account_server=?
                  AND status IN ('open', 'unverified') AND post_id IN (
                    SELECT id FROM posts WHERE account_login=? AND account_server=?
                )
            """, (value, timestamp, int(position_id), login, server,
                  login, server))
            return cursor.rowcount

    def close_link(self, account_key: AccountKey, post_id: int,
                   position_id: int, result_usc: Decimal,
                   closed_at: datetime) -> int:
        login, server = _validate_account(account_key)
        value = _decimal(result_usc)
        if value is None:
            raise ValueError("平仓结果不能为空")
        with self._connection() as db:
            cursor = db.execute("""
                UPDATE position_links
                SET status='closed', result_usc=?, closed_at=?
                WHERE post_id=? AND position_id=? AND account_login=?
                  AND account_server=? AND status IN ('open', 'unverified')
                  AND post_id IN (SELECT id FROM posts WHERE account_login=?
                                  AND account_server=?)
            """, (value, _timestamp(closed_at), int(post_id), int(position_id),
                  login, server, login, server))
            return cursor.rowcount

    def mark_unverified(self, account_key: AccountKey, post_id: int,
                        position_id: int) -> int:
        login, server = _validate_account(account_key)
        with self._connection() as db:
            cursor = db.execute("""
                UPDATE position_links SET status='unverified'
                WHERE post_id=? AND position_id=? AND account_login=?
                  AND account_server=? AND status='open'
                  AND post_id IN (SELECT id FROM posts WHERE account_login=?
                                  AND account_server=?)
            """, (int(post_id), int(position_id), login, server,
                  login, server))
            return cursor.rowcount

    def delete_post(self, account_key: AccountKey, post_id: int) -> bool:
        login, server = _validate_account(account_key)
        with self._connection() as db:
            images = db.execute("""
                SELECT filename FROM post_images WHERE post_id=? AND post_id IN (
                    SELECT id FROM posts WHERE account_login=? AND account_server=?
                )
            """, (int(post_id), login, server)).fetchall()
            cursor = db.execute("""
                DELETE FROM posts WHERE id=? AND account_login=? AND account_server=?
            """, (int(post_id), login, server))
            deleted = bool(cursor.rowcount)
        if deleted:
            for row in images:
                (self.images_dir / Path(row["filename"]).name).unlink(missing_ok=True)
        return deleted
