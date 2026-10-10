"""Automatic storage and migration preserve journals and duplicate-send records."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import MetaTrader5 as mt5

from mt5_workbench.infrastructure import app_data
from mt5_workbench.services.trade_execution import plan_key, send_checked


class AppDataTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.legacy = self.root / "old-app/state"
        self.destination = self.root / "user-data/MT5Workbench/state"

    def prepare(self, **kwargs):
        return app_data.prepare_state_directory(destination=self.destination, legacy=self.legacy, **kwargs)

    def write_old(self, name, contents):
        path = self.legacy / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
        return path

    def test_new_user_gets_complete_directories_without_legacy_data(self):
        result = self.prepare()
        self.assertEqual(result, self.destination.resolve())
        for name in app_data.SUBDIRECTORIES:
            self.assertTrue((result / name).is_dir())
        self.assertEqual(json.loads((result / "storage.json").read_text("utf-8"))["migratedFrom"], "")
        self.assertFalse(self.legacy.exists())

    def test_migration_copies_preferences_images_and_committed_wal_database(self):
        self.write_old("system_settings.json", '{"timeZone":"UTC+08:00"}')
        self.write_old("controls/batch.json", '{"status":"done"}')
        image = self.write_old("journal/images/photo.png", "test image")
        database = self.legacy / "journal/journal.sqlite3"
        with closing(sqlite3.connect(database)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE posts (body TEXT)")
            db.execute("CREATE TABLE post_images (filename TEXT)")
            db.execute("INSERT INTO posts VALUES ('中文日志')")
            db.execute("INSERT INTO post_images VALUES ('photo.png')")
            db.commit()
            self.assertTrue(Path(str(database) + "-wal").exists())
            result = self.prepare()
            with closing(sqlite3.connect(result / "journal/journal.sqlite3")) as copied:
                self.assertEqual(copied.execute("SELECT body FROM posts").fetchone()[0], "中文日志")
        self.assertEqual((result / "journal/images/photo.png").read_bytes(), image.read_bytes())
        self.assertEqual((result / "system_settings.json").read_text("utf-8"), '{"timeZone":"UTC+08:00"}')
        self.assertTrue(database.exists())
        self.assertFalse(Path(str(result / "journal/journal.sqlite3") + "-wal").exists())

    def test_migrated_order_reservation_still_blocks_duplicate_send(self):
        account = SimpleNamespace(login=123, server="test", currency="USC")
        request = {"action": mt5.TRADE_ACTION_PENDING,
                   "symbol": "XAUUSDc", "volume": 0.01, "type": mt5.ORDER_TYPE_BUY_LIMIT,
                   "price": 4200.0, "sl": 4190.0, "tp": 0.0}
        filename = plan_key(account, (request,)) + ".json"
        original = self.write_old("executions/" + filename, '{"status":"reserved"}')
        result = self.prepare()
        self.assertEqual((result / "executions" / filename).read_bytes(), original.read_bytes())
        api = Mock()
        api.account_info.return_value = account
        api.orders_get.return_value = ()
        api.order_check.return_value = SimpleNamespace(retcode=0)
        with self.assertRaisesRegex(RuntimeError, "已有发送记录"):
            send_checked(account, (request,), result / "executions", api=api)
        api.order_send.assert_not_called()

    def test_repeated_launch_keeps_current_data_and_imports_missing_reservations(self):
        self.write_old("ui_settings.json", '{"theme":"light"}')
        self.write_old("executions/first.json", '{"status":"reserved"}')
        self.prepare()
        (self.destination / "ui_settings.json").write_text('{"theme":"dark"}', "utf-8")
        (self.destination / "executions/first.json").write_text('{"status":"done"}', "utf-8")
        self.write_old("executions/second.json", '{"status":"reserved"}')
        self.prepare()
        self.assertEqual((self.destination / "ui_settings.json").read_text("utf-8"), '{"theme":"dark"}')
        self.assertEqual((self.destination / "executions/first.json").read_text("utf-8"), '{"status":"done"}')
        self.assertTrue((self.destination / "executions/second.json").is_file())
        self.assertFalse(list(self.destination.rglob(".import-*.tmp")))

    def test_copy_failure_does_not_publish_partial_directory_or_change_original(self):
        original = self.write_old("executions/first.json", '{"status":"reserved"}')
        with patch.object(app_data.shutil, "copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.prepare()
        self.assertFalse(self.destination.exists())
        self.assertEqual(original.read_text("utf-8"), '{"status":"reserved"}')
        self.assertFalse(list(self.destination.parent.glob(".state-migration-*")))
        self.prepare()
        self.assertTrue((self.destination / "executions/first.json").is_file())

    def test_preexisting_missing_image_does_not_block_migration_of_journal(self):
        self.legacy.mkdir(parents=True)
        with closing(sqlite3.connect(self.legacy / "journal.sqlite3")) as db:
            db.execute("CREATE TABLE post_images (filename TEXT)")
            db.execute("INSERT INTO post_images VALUES ('missing.png')")
            db.commit()
        self.prepare()
        self.assertTrue((self.destination / "journal.sqlite3").exists())
        self.assertTrue((self.legacy / "journal.sqlite3").exists())

    def test_copying_an_existing_image_is_verified_before_publishing(self):
        self.write_old("images/photo.png", "test image")
        with closing(sqlite3.connect(self.legacy / "journal.sqlite3")) as db:
            db.execute("CREATE TABLE post_images (filename TEXT)")
            db.execute("INSERT INTO post_images VALUES ('photo.png')")
            db.commit()
        copy_file = app_data._copy_file

        def omit_image(source, destination):
            if Path(source).name == "photo.png":
                return str(destination)
            return copy_file(source, destination)

        with patch.object(app_data, "_copy_file", side_effect=omit_image):
            with self.assertRaisesRegex(RuntimeError, "复制不完整"):
                self.prepare()
        self.assertFalse(self.destination.exists())
        self.assertTrue((self.legacy / "images/photo.png").exists())

    def test_smoke_mode_creates_empty_storage_without_copying_legacy(self):
        self.write_old("system_settings.json", "personal settings")
        self.prepare(migrate=False)
        self.assertFalse((self.destination / "system_settings.json").exists())


if __name__ == "__main__":
    unittest.main()
