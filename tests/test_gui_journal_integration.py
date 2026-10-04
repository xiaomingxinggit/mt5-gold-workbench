"""Main-window journal wiring with a temporary local database and mocked MT5."""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mt5_workbench.domain.journal import PositionSnapshot
from mt5_workbench.infrastructure.journal_db import JournalRepository
from mt5_workbench.ui import main_window as gui


ACCOUNT_KEY = (812345, "test-USC")


def account():
    return SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1],
                           currency="USC", name="demo")


def snapshot(position_id: int) -> PositionSnapshot:
    return PositionSnapshot(
        position_id=position_id, ticket=position_id, symbol="XAUUSDc", side="BUY",
        volume=Decimal("0.01"), price_open=Decimal("4200"),
        opened_at=datetime.now(timezone.utc), floating_usc=Decimal("0"),
    )


class MainWindowJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = JournalRepository(Path(self.directory.name))
        self.window = gui.MainWindow(
            autoconnect=False, start_timer=False, journal_repository=self.repo)
        self.addCleanup(self.window.close)
        self.window.show()
        self.app.processEvents()

    def test_offline_feed_is_account_scoped_and_paginated(self):
        for number in range(12):
            self.repo.create_post(ACCOUNT_KEY, f"行情观察 {number}")
        self.repo.create_post((999999, "other-USC"), "另一账户")
        self.window.journal_account_key = ACCOUNT_KEY
        self.window.show_page("journal")
        self.app.processEvents()
        self.assertEqual(self.window.journal.current_page, 1)
        self.assertEqual(self.window.journal.page_note.text(), "共 12 篇 · 每页 10 篇")
        self.window.journal.next_button.click()
        self.app.processEvents()
        self.assertEqual(self.window.journal.current_page, 2)
        self.assertFalse(self.window.journal.next_button.isEnabled())
        self.assertFalse(self.window.journal.publish_button.isEnabled())
        self.window.journal.refresh_button.click()
        self.assertEqual(self.window.journal.current_page, 2)

    def test_switching_to_empty_account_resets_feed_page(self):
        for number in range(11):
            self.repo.create_post(ACCOUNT_KEY, f"旧账户记录 {number}")
        self.window.journal_account_key = ACCOUNT_KEY
        self.window.show_page("journal")
        self.window.journal.next_button.click()
        self.assertEqual(self.window.journal.current_page, 2)
        self.window.journal_account_key = (999999, "other-USC")
        self.window.refresh_journal()
        self.assertEqual(self.window.journal.current_page, 1)
        self.assertEqual(self.window.journal.current_page_label.text(), "1 / 1")
        self.assertEqual(self.window.journal.page_note.text(), "共 0 篇 · 每页 10 篇")

    def test_publish_rechecks_multiple_live_positions_without_trading(self):
        self.window.connected = True
        self.window.account = account()
        self.window.journal_account_key = ACCOUNT_KEY
        with (
            patch.object(gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(gui.mt5, "account_info", return_value=account()),
            patch.object(gui.mt5, "order_send") as order_send,
            patch.object(gui, "load_open_positions",
                         return_value=(snapshot(7001), snapshot(7002))),
            patch.object(self.window.journal, "publish_succeeded") as succeeded,
            patch.object(self.window, "refresh_journal"),
        ):
            self.window.publish_journal("两笔持仓的行情记录", (), (7001, 7002))
            succeeded.assert_called_once()
            order_send.assert_not_called()
        post = self.repo.list_posts(ACCOUNT_KEY).posts[0]
        self.assertEqual({link.position_id for link in post.positions}, {7001, 7002})
        self.assertEqual(post.body, "两笔持仓的行情记录")

    def test_publish_dialog_saves_through_main_window_signal(self):
        self.window.connected = True
        self.window.account = account()
        self.window.journal_account_key = ACCOUNT_KEY
        with (
            patch.object(gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(gui.mt5, "account_info", return_value=account()),
            patch.object(gui.mt5, "order_send") as order_send,
            patch.object(gui, "load_open_positions", return_value=(snapshot(7001),)),
            patch.object(gui, "sync_closed_positions",
                         return_value=SimpleNamespace(updated_count=0, errors=())),
        ):
            self.window.show_page("journal")
            self.window.journal.open_composer()
            dialog = self.window.journal._composer
            self.assertIsNotNone(dialog)
            dialog.body.setPlainText("通过界面发布的本地记录")
            dialog.position_list.item(0).setCheckState(
                gui.Qt.CheckState.Checked)
            dialog.submit_button.click()
            self.app.processEvents()
            self.assertFalse(dialog.isVisible())
            order_send.assert_not_called()
        page = self.repo.list_posts(ACCOUNT_KEY)
        self.assertEqual(page.total, 1)
        self.assertEqual(page.posts[0].positions[0].position_id, 7001)

    def test_stale_position_rejects_publish_without_losing_draft(self):
        self.window.connected = True
        self.window.account = account()
        with (
            patch.object(gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(gui.mt5, "account_info", return_value=account()),
            patch.object(gui, "load_open_positions", return_value=()),
            patch.object(self.window.journal, "publish_failed") as failed,
        ):
            self.window.publish_journal("旧持仓", (), (7001,))
            failed.assert_called_once()
        self.assertEqual(self.repo.list_posts(ACCOUNT_KEY).total, 0)

    def test_non_usc_lock_closes_journal_composer(self):
        self.window.connected = True
        self.window.account = account()
        self.window.journal.set_can_publish(True)
        self.window.journal.open_composer()
        dialog = self.window.journal._composer
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        other = SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1],
                                currency="USD")
        self.window._lock_unsupported(other)
        self.app.processEvents()
        self.assertFalse(dialog.isVisible())
        self.assertFalse(self.window.connected)
        self.assertTrue(self.window.account_lock.isVisible())

    def test_history_sync_runs_once_in_background_and_discards_old_account_result(self):
        entered = threading.Event()
        release = threading.Event()
        calls = []

        def slow_sync(_repo, account_key, *, api):
            calls.append(account_key)
            if account_key == ACCOUNT_KEY:
                entered.set()
                self.assertTrue(release.wait(3))
                return SimpleNamespace(updated_count=0, errors=("旧账户错误",))
            return SimpleNamespace(updated_count=0, errors=())

        self.window.connected = True
        self.window.account = account()
        self.window.journal_account_key = ACCOUNT_KEY
        self.window.current_page = "journal"
        with (
            patch.object(gui.mt5, "terminal_info", return_value=SimpleNamespace(connected=True)),
            patch.object(gui.mt5, "account_info", side_effect=lambda: self.window.account),
            patch.object(gui, "load_open_positions", return_value=()),
            patch.object(gui, "sync_closed_positions", side_effect=slow_sync),
        ):
            started = time.monotonic()
            self.window.refresh_journal(force_sync=True)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(entered.wait(1))
            self.window.refresh_journal(force_sync=True)
            self.assertEqual(calls, [ACCOUNT_KEY])
            self.window._cancel_journal_sync()
            self.window.account = SimpleNamespace(login=999999, server="other-USC",
                                                  currency="USC")
            self.window.journal_account_key = (999999, "other-USC")
            release.set()
            self.window._journal_sync_thread.join(timeout=3)
            self.window._consume_journal_sync_result()
            self.assertNotIn("旧账户错误", self.window.journal.notice.text())


if __name__ == "__main__":
    unittest.main()
