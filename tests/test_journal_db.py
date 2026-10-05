from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import replace
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage

from mt5_workbench.domain.journal import BEIJING_TZ, PositionSnapshot
from mt5_workbench.infrastructure.journal_db import JournalRepository


ACCOUNT_A = (100001, "Demo-Server")
ACCOUNT_B = (100002, "Demo-Server")
ACCOUNT_C = (100001, "Other-Demo-Server")


def snapshot(position_id: int) -> PositionSnapshot:
    return PositionSnapshot(
        position_id=position_id,
        ticket=position_id + 100,
        symbol="XAUUSDc",
        side="buy",
        volume=Decimal("0.01"),
        price_open=Decimal("4200.50"),
        opened_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        sl=Decimal("4190"),
        tp=None,
        floating_usc=Decimal("25.2"),
    )


class JournalRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = JournalRepository(self.root / "journal")

    def test_post_image_position_close_and_delete(self):
        image = self.root / "chart.png"
        self.assertTrue(QImage(2, 2, QImage.Format.Format_RGB32).save(str(image)))
        post_id = self.repo.create_post(
            ACCOUNT_A, "  今日关注黄金  ", [image], [snapshot(13), snapshot(14)],
        )
        image.unlink()
        page = self.repo.list_posts(ACCOUNT_A)
        self.assertEqual((page.total, page.page, page.total_pages), (1, 1, 1))
        self.assertEqual(page.posts[0].body, "今日关注黄金")
        self.assertEqual(len(page.posts[0].positions), 2)
        self.assertTrue(page.posts[0].images[0].is_file())
        self.assertEqual(page.posts[0].positions[0].price_open, Decimal("4200.50"))
        self.assertEqual(page.posts[0].positions[0].account_key, ACCOUNT_A)
        copied_image = page.posts[0].images[0]

        closed_at = datetime(2026, 10, 5, tzinfo=timezone.utc)
        self.assertEqual(self.repo.close_position(
            ACCOUNT_A, 13, Decimal("-125.75"), closed_at,
        ), 1)
        self.assertEqual(self.repo.close_position(
            ACCOUNT_A, 13, Decimal("0"), closed_at,
        ), 0)
        positions = self.repo.list_posts(ACCOUNT_A).posts[0].positions
        self.assertEqual(positions[0].status, "closed")
        self.assertEqual(positions[0].result_usc, Decimal("-125.75"))
        self.assertEqual(positions[1].status, "open")
        self.assertEqual(len(self.repo.open_links(ACCOUNT_A)), 1)

        self.assertTrue(self.repo.delete_post(ACCOUNT_A, post_id))
        self.assertFalse(copied_image.exists())
        self.assertEqual(self.repo.list_posts(ACCOUNT_A).total, 0)
        self.assertEqual(self.repo.open_links(ACCOUNT_A), ())
        self.assertFalse(self.repo.delete_post(ACCOUNT_A, post_id))

    def test_same_position_can_be_attached_to_multiple_posts(self):
        self.repo.create_post(ACCOUNT_A, "first", positions=[snapshot(13)])
        self.repo.create_post(ACCOUNT_A, "second", positions=[snapshot(13)])
        self.repo.create_post(ACCOUNT_B, "another account", positions=[snapshot(13)])
        self.repo.create_post(ACCOUNT_C, "same login on another server",
                              positions=[snapshot(13)])
        self.assertEqual(len(self.repo.open_links(ACCOUNT_A)), 2)
        self.assertEqual(self.repo.close_position(
            ACCOUNT_A, 13, Decimal("100"), datetime.now(timezone.utc),
        ), 2)
        self.assertEqual(self.repo.open_links(ACCOUNT_A), ())
        self.assertEqual(len(self.repo.open_links(ACCOUNT_B)), 1)
        self.assertEqual(len(self.repo.open_links(ACCOUNT_C)), 1)

    def test_account_isolation_pagination_and_activity(self):
        for i in range(12):
            self.repo.create_post(ACCOUNT_A, f"post {i}")
        other = self.repo.create_post(ACCOUNT_B, "other")
        page1 = self.repo.list_posts(ACCOUNT_A, page_size=5)
        page3 = self.repo.list_posts(ACCOUNT_A, page=3, page_size=5)
        page4 = self.repo.list_posts(ACCOUNT_A, page=4, page_size=5)
        self.assertEqual((page1.total, page1.total_pages, len(page1.posts)), (12, 3, 5))
        self.assertEqual([p.body for p in page3.posts], ["post 1", "post 0"])
        self.assertEqual(page4.posts, ())
        self.assertEqual(self.repo.list_posts(ACCOUNT_B).posts[0].id, other)
        self.assertEqual(self.repo.list_posts(None).posts, ())
        self.assertFalse(self.repo.delete_post(ACCOUNT_A, other))
        self.assertEqual(self.repo.activity(ACCOUNT_A, days=7)[datetime.now(BEIJING_TZ).date()], 12)
        self.assertEqual(sum(self.repo.activity(None, days=7).values()), 0)

    def test_calendar_year_activity_and_available_years_are_account_scoped(self):
        leap_day = self.repo.create_post(ACCOUNT_A, "leap day")
        another_leap_day = self.repo.create_post(ACCOUNT_A, "same day")
        new_year = self.repo.create_post(ACCOUNT_A, "new year")
        other_login = self.repo.create_post(ACCOUNT_B, "other login")
        other_server = self.repo.create_post(ACCOUNT_C, "other server")
        with closing(sqlite3.connect(self.repo.db_path)) as db, db:
            db.executemany(
                "UPDATE posts SET created_at=? WHERE id=?",
                [
                    ("2024-02-29T10:00:00+08:00", leap_day),
                    ("2024-02-29T11:00:00+08:00", another_leap_day),
                    ("2025-01-01T00:00:00+08:00", new_year),
                    ("2024-12-31T23:59:00+08:00", other_login),
                    ("2023-07-01T09:00:00+08:00", other_server),
                ],
            )

        self.assertEqual(self.repo.available_years(ACCOUNT_A), (2025, 2024))
        self.assertEqual(self.repo.available_years(ACCOUNT_B), (2024,))
        self.assertEqual(self.repo.available_years(ACCOUNT_C), (2023,))
        self.assertEqual(self.repo.available_years(None), ())

        leap_activity = self.repo.activity_year(ACCOUNT_A, 2024)
        self.assertEqual(len(leap_activity), 366)
        self.assertEqual(leap_activity[date(2024, 2, 29)], 2)
        self.assertEqual(leap_activity[date(2024, 12, 31)], 0)
        self.assertEqual(sum(leap_activity.values()), 2)
        regular_activity = self.repo.activity_year(ACCOUNT_A, 2025)
        self.assertEqual(len(regular_activity), 365)
        self.assertEqual(regular_activity[date(2025, 1, 1)], 1)
        self.assertEqual(sum(self.repo.activity_year(None, 2024).values()), 0)

    def test_calendar_year_activity_rejects_invalid_years(self):
        for year in (True, 0, 10000, "2024"):
            with self.subTest(year=year), self.assertRaises(ValueError):
                self.repo.activity_year(ACCOUNT_A, year)

    def test_calendar_uses_beijing_day_across_utc_midnight_and_new_year(self):
        before = self.repo.create_post(ACCOUNT_A, "before midnight")
        after = self.repo.create_post(ACCOUNT_A, "after midnight")
        with closing(sqlite3.connect(self.repo.db_path)) as db, db:
            db.executemany("UPDATE posts SET created_at=? WHERE id=?", [
                ("2025-12-31T15:59:59.999999+00:00", before),
                ("2025-12-31T16:00:00+00:00", after),
            ])
        self.assertEqual(self.repo.available_years(ACCOUNT_A), (2026, 2025))
        self.assertEqual(self.repo.activity_year(ACCOUNT_A, 2025)[date(2025, 12, 31)], 1)
        self.assertEqual(self.repo.activity_year(ACCOUNT_A, 2026)[date(2026, 1, 1)], 1)
        self.assertEqual(sum(self.repo.activity_year(ACCOUNT_A, 2026).values()), 1)

    def test_replies_and_images_persist_under_parent_account_and_delete_with_post(self):
        image = self.root / "reply.png"
        self.assertTrue(QImage(2, 2, QImage.Format.Format_RGB32).save(str(image)))
        post_id = self.repo.create_post(ACCOUNT_A, "post", [image])
        first = self.repo.create_reply(ACCOUNT_A, post_id, "  follow up  ", [image])
        second = self.repo.create_reply(ACCOUNT_A, post_id, "", [image])
        reopened = JournalRepository(self.repo.base_dir)
        post = reopened.list_posts(ACCOUNT_A).posts[0]
        self.assertEqual([r.id for r in post.replies], [first, second])
        self.assertEqual([r.body for r in post.replies], ["follow up", ""])
        self.assertEqual(post.created_at.utcoffset(), timedelta(hours=8))
        self.assertEqual(post.replies[0].created_at.utcoffset(), timedelta(hours=8))
        saved = [*post.images, *(r.images[0] for r in post.replies)]
        self.assertTrue(all(path.is_file() for path in saved))
        self.assertEqual(reopened.list_posts(ACCOUNT_B).posts, ())
        self.assertFalse(reopened.delete_post(ACCOUNT_B, post_id))
        self.assertTrue(all(path.is_file() for path in saved))
        self.assertTrue(reopened.delete_post(ACCOUNT_A, post_id))
        self.assertTrue(all(not path.exists() for path in saved))
        with closing(sqlite3.connect(self.repo.db_path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM post_replies").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reply_images").fetchone()[0], 0)

    def test_invalid_or_other_account_reply_keeps_database_and_image_store_unchanged(self):
        post_id = self.repo.create_post(ACCOUNT_A, "post")
        image = self.root / "reply.png"
        self.assertTrue(QImage(2, 2, QImage.Format.Format_RGB32).save(str(image)))
        for key, target, body, images in (
            (ACCOUNT_B, post_id, "wrong login", [image]),
            (ACCOUNT_C, post_id, "wrong server", [image]),
            (ACCOUNT_A, post_id + 1, "missing post", [image]),
            (ACCOUNT_A, post_id, "", []),
            (ACCOUNT_A, post_id, "x" * 2101, [image]),
            (ACCOUNT_A, post_id, "too many images", [image] * 5),
        ):
            with self.subTest(key=key, target=target, body=body[:20]), self.assertRaises(ValueError):
                self.repo.create_reply(key, target, body, images)
        self.assertEqual(self.repo.list_posts(ACCOUNT_A).posts[0].replies, ())
        self.assertEqual(list(self.repo.images_dir.iterdir()), [])
        # A parent can disappear after the initial check and image copying.
        with patch.object(self.repo, "has_post", return_value=True), self.assertRaises(ValueError):
            self.repo.create_reply(ACCOUNT_A, post_id + 1, "parent removed", [image])
        self.assertEqual(list(self.repo.images_dir.iterdir()), [])

    def test_data_survives_reopening_database(self):
        post_id = self.repo.create_post(ACCOUNT_A, "persistent", positions=[snapshot(33)])
        reopened = JournalRepository(self.root / "journal")
        page = reopened.list_posts(ACCOUNT_A)
        self.assertEqual(page.posts[0].id, post_id)
        self.assertEqual(page.posts[0].positions[0].position_id, 33)

    def test_invalid_inputs_leave_no_posts_or_images(self):
        invalid = self.root / "fake.png"
        invalid.write_text("not a PNG", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.repo.create_post(ACCOUNT_A, "text", [invalid])
        with self.assertRaises(ValueError):
            self.repo.create_post(ACCOUNT_A, "x" * 2101)
        with self.assertRaises(ValueError):
            self.repo.create_post(ACCOUNT_A, "")
        with self.assertRaises(ValueError):
            self.repo.create_post(ACCOUNT_A, "text", positions=[snapshot(1), snapshot(1)])
        with self.assertRaises(ValueError):
            self.repo.list_posts(ACCOUNT_A, page=0)
        valid = self.root / "valid.png"
        self.assertTrue(QImage(2, 2, QImage.Format.Format_RGB32).save(str(valid)))
        with self.assertRaises(ValueError):
            self.repo.create_post(
                ACCOUNT_A, "text", [valid],
                [replace(snapshot(1), volume=Decimal("NaN"))],
            )
        self.assertEqual(self.repo.list_posts(ACCOUNT_A).total, 0)
        self.assertEqual(list(self.repo.images_dir.iterdir()), [])

    def test_account_bound_link_cannot_be_saved_under_another_account(self):
        linked = replace(snapshot(13), account_key=ACCOUNT_A)
        with self.assertRaisesRegex(ValueError, "不属于当前账户"):
            self.repo.create_post(ACCOUNT_B, "错误账户", positions=[linked])
        self.assertEqual(self.repo.list_posts(ACCOUNT_B).total, 0)

    def test_corrupt_picture_is_rejected_after_header_check(self):
        image = self.root / "broken.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"broken")
        with self.assertRaisesRegex(ValueError, "无法完整读取"):
            self.repo.create_post(ACCOUNT_A, "坏图", [image])
        self.assertEqual(self.repo.list_posts(ACCOUNT_A).total, 0)

    def test_old_links_are_migrated_with_post_account(self):
        post_id = self.repo.create_post(ACCOUNT_A, "旧日志", positions=[snapshot(13)])
        with closing(sqlite3.connect(self.repo.db_path)) as db, db:
            db.execute("DROP TABLE position_links")
            db.execute("""
                CREATE TABLE position_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL,
                    position_id INTEGER NOT NULL,
                    ticket INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    price_open TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    sl TEXT, tp TEXT, floating_usc TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
                    result_usc TEXT, closed_at TEXT,
                    UNIQUE(post_id, position_id)
                )
            """)
            db.execute("""
                INSERT INTO position_links (
                    post_id, position_id, ticket, symbol, side, volume,
                    price_open, opened_at, floating_usc, status)
                VALUES (?, 13, 113, 'XAUUSDc', 'BUY', '0.01', '4200',
                        '2026-10-04T00:00:00+00:00', '25', 'open')
            """, (post_id,))
        reopened = JournalRepository(self.root / "journal")
        link = reopened.open_links(ACCOUNT_A)[0]
        self.assertEqual(link.account_key, ACCOUNT_A)
        self.assertEqual(link.post_id, post_id)
        self.assertIsNotNone(link.linked_at)
        self.assertEqual(reopened.mark_unverified(ACCOUNT_A, post_id, 13), 1)
        self.assertEqual(reopened.open_links(ACCOUNT_A)[0].status, "unverified")


if __name__ == "__main__":
    unittest.main()
