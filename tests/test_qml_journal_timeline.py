"""Account-scoped journal timeline, image preview, and reply interactions."""

from __future__ import annotations

import os
import sqlite3
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench.infrastructure.journal_db import JournalRepository
from mt5_workbench.ui.qml_bridge import _journal_post, _journal_timestamp
from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge


class FakeApi:
    def __init__(self):
        self.current = SimpleNamespace(login=101, server="test-server", currency="USC")

    def account_info(self):
        return self.current

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def order_send(self, *_args, **_kwargs):
        raise AssertionError("Journal interactions must never send trades")


class QmlJournalTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JournalRepository(Path(self.temp.name) / "journal")
        self.api = FakeApi()
        self.key = (101, "test-server")
        self.bridge = QmlTradingBridge(autoconnect=False, start_timer=False,
                                       journal_repository=self.repo, api=self.api)
        self.addCleanup(self.bridge.close)
        self.bridge.connected = True
        self.bridge.account = self.api.current
        self.bridge._set_state(connection={"connected": True, "locked": False})
        self.image = Path(self.temp.name) / "chart.png"
        picture = QImage(320, 180, QImage.Format_ARGB32)
        picture.fill(0xff087f73)
        self.assertTrue(picture.save(str(self.image)))
        self.app.clipboard().setImage(picture)
        self.addCleanup(self.app.clipboard().clear)

    def load_feed(self):
        feed = self.repo.list_posts(self.key)
        self.bridge._set_state(page="journal", journal={
            **self.bridge.state["journal"], "accountLabel": "账户 101 · test-server",
            "canPublish": True, "total": feed.total,
            "posts": [_journal_post(post) for post in feed.posts],
        })

    def open_window(self):
        self.engine = QQmlApplicationEngine()
        self.qml_warnings = []
        self.engine.warnings.connect(lambda items: self.qml_warnings.extend(str(i) for i in items))
        path = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml"
        self.engine.addImportPath(str(path))
        self.engine.rootContext().setContextProperty("bridge", self.bridge)
        self.engine.load(QUrl.fromLocalFile(str(path / "App.qml")))
        self.assertEqual(len(self.engine.rootObjects()), 1)
        self.window = self.engine.rootObjects()[0]
        self.addCleanup(self.window.close)
        self.window.resize(1440, 1400)
        QTest.qWait(50)
        self.view = self.window.findChild(QQuickItem, "journalView")

    def click(self, item):
        self.assertIsNotNone(item)
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(30)

    def items(self, name, parent=None):
        """Repeater delegates belong to the visual tree, not QObject children."""
        parent = self.view if parent is None else parent
        result = [parent] if parent.objectName() == name else []
        for child in parent.childItems():
            result.extend(self.items(name, child))
        return result

    def test_time_format_converts_utc_to_beijing_and_keeps_human_readable_labels(self):
        row = _journal_timestamp(datetime(2025, 12, 31, 16, 40, 56, tzinfo=timezone.utc))
        self.assertEqual(row["dateKey"], "2026-01-01")
        self.assertEqual(row["dateLabel"], "2026年1月1日")
        self.assertEqual(row["timeLabel"], "00:40")
        self.assertTrue(row["createdAt"].endswith("+08:00"))

    def test_timeline_groups_same_day_and_preview_can_switch_zoom_and_close(self):
        older = self.repo.create_post(self.key, "older")
        same_day = self.repo.create_post(self.key, "same day")
        latest = self.repo.create_post(self.key, "latest", [self.image, self.image])
        with closing(sqlite3.connect(self.repo.db_path)) as db, db:
            db.executemany("UPDATE posts SET created_at=? WHERE id=?", [
                ("2026-10-04T23:00:00+08:00", older),
                ("2026-10-05T17:00:00+00:00", same_day),
                ("2026-10-06T02:00:00+08:00", latest),
            ])
        self.load_feed()
        self.open_window()
        self.assertEqual(len(self.items("journalTimelineDay")), 2)
        self.assertEqual(len(self.items("journalTimelinePost")), 3)
        thumbnails = self.items("journalImageThumbnail")
        self.assertEqual(len(thumbnails), 2)
        self.click(thumbnails[0])
        self.assertTrue(self.view.property("imagePreviewOpen"))
        viewer = self.window.findChild(QObject, "journalImageViewer")
        self.assertEqual(viewer.property("currentIndex"), 0)
        self.click(self.window.findChild(QQuickItem, "journalPreviewNext"))
        self.assertEqual(viewer.property("currentIndex"), 1)
        self.click(self.window.findChild(QQuickItem, "journalPreviewZoomIn"))
        self.assertEqual(viewer.property("zoom"), 1.5)
        self.window.setProperty("fullscreen", True)
        QTest.qWait(50)
        QTest.keyClick(self.window, Qt.Key_Escape)
        QTest.qWait(200)
        self.assertFalse(self.view.property("imagePreviewOpen"))
        self.assertTrue(self.window.property("fullscreen"))
        self.assertEqual(self.qml_warnings, [])

    def test_reply_text_and_pasted_image_publish_then_survive_reload(self):
        post_id = self.repo.create_post(self.key, "initial observation", [self.image])
        self.load_feed()
        self.open_window()
        self.click(self.items("journalReplyToggle")[0])
        self.assertEqual(self.view.property("replyingTo"), post_id)
        editor = self.items("journalReplyEditor")[0]
        editor.setProperty("text", "后续观察")
        editor.forceActiveFocus()
        QTest.keyClick(self.window, Qt.Key_V, Qt.ControlModifier)
        QTest.qWait(30)
        draft = self.bridge.state["journal"]["replyDraftImages"][str(post_id)]
        self.assertEqual(len(draft), 1)
        pasted = Path(draft[0]["path"])
        self.assertTrue(pasted.is_file())
        editor = self.items("journalReplyEditor")[0]
        self.assertEqual(editor.property("text"), "后续观察")
        with patch.object(self.bridge, "refresh_journal"):
            self.click(self.items("journalReplyPublish")[0])
        self.assertEqual(self.bridge.state["journal"]["replyDraftImages"], {})
        self.assertFalse(pasted.exists())
        reply = self.repo.list_posts(self.key).posts[0].replies[0]
        self.assertEqual(reply.body, "后续观察")
        self.assertTrue(reply.images[0].is_file())
        self.assertEqual(self.view.property("replyingTo"), 0)
        self.assertEqual(len(self.items("journalReplyCard")), 1)
        self.load_feed()
        QTest.qWait(30)
        self.assertEqual(len(self.items("journalReplyCard")), 1)
        self.assertEqual(self.qml_warnings, [])

    def test_reply_drafts_are_isolated_from_post_draft_and_cleaned_on_account_switch(self):
        post_id = self.repo.create_post(self.key, "post")
        self.load_feed()
        self.bridge.perform("journalPasteImage", {})
        main_path = Path(self.bridge.state["journal"]["draftImages"][0]["path"])
        self.bridge.perform("journalPasteImage", {"postId": post_id})
        reply_path = Path(self.bridge.state["journal"]["replyDraftImages"][str(post_id)][0]["path"])
        self.assertTrue(main_path.is_file())
        self.assertTrue(reply_path.is_file())
        self.bridge.perform("journalDiscardReply", {"postId": post_id})
        self.assertFalse(reply_path.exists())
        self.assertTrue(main_path.is_file())
        self.bridge.perform("journalPasteImage", {"postId": post_id})
        reply_path = Path(self.bridge.state["journal"]["replyDraftImages"][str(post_id)][0]["path"])
        self.api.current = SimpleNamespace(login=202, server="test-server", currency="USC")
        with patch.object(self.bridge, "refresh_journal"):
            self.bridge.perform("journalReplyPublish", {"postId": post_id, "body": "wrong account"})
        self.assertFalse(main_path.exists())
        self.assertFalse(reply_path.exists())
        self.assertEqual(self.bridge.state["journal"]["posts"], [])
        self.assertEqual(self.repo.list_posts(self.key).posts[0].replies, ())

    def test_share_button_copies_the_complete_post_image_without_changing_drafts(self):
        post_id = self.repo.create_post(self.key, "行情观察\n" + "长内容测试 " * 100, [self.image])
        self.repo.create_reply(self.key, post_id, "后续观察", [self.image])
        self.load_feed()
        self.open_window()
        self.bridge.perform("journalPasteImage", {})
        drafts = self.bridge.state["journal"]["draftImages"]
        self.app.clipboard().setText("old clipboard")
        self.click(self.items("journalShare")[0])
        shared = self.app.clipboard().image()
        self.assertFalse(shared.isNull())
        self.assertEqual(shared.width(), 1080)
        self.assertGreater(shared.height(), 1300)
        self.assertIn("已复制到剪贴板", self.bridge.state["status"])
        self.assertEqual(self.bridge.state["journal"]["draftImages"], drafts)
        self.assertTrue(Path(drafts[0]["path"]).is_file())
        self.assertEqual(self.repo.list_posts(self.key).total, 1)
        self.assertEqual(self.qml_warnings, [])

    def test_share_failure_keeps_clipboard_when_attachment_is_missing(self):
        self.repo.create_post(self.key, "观察", [self.image])
        self.load_feed()
        self.repo.list_posts(self.key).posts[0].images[0].unlink()
        self.app.clipboard().setText("keep this")
        self.bridge.perform("journalShare", {"postId": self.bridge.state["journal"]["posts"][0]["id"]})
        self.assertEqual(self.app.clipboard().text(), "keep this")
        self.assertIn("分享失败", self.bridge.state["status"])

    def test_share_rejects_other_accounts_invalid_ids_and_changed_account(self):
        other_id = self.repo.create_post((202, "test-server"), "other account")
        own_id = self.repo.create_post(self.key, "own post")
        self.load_feed()
        self.app.clipboard().setText("keep this")
        for post_id in (other_id, 0, "invalid", 999999):
            with self.subTest(post_id=post_id):
                self.bridge.perform("journalShare", {"postId": post_id})
                self.assertEqual(self.app.clipboard().text(), "keep this")
        self.api.current = SimpleNamespace(login=202, server="test-server", currency="USC")
        self.bridge.perform("journalShare", {"postId": own_id})
        self.assertEqual(self.app.clipboard().text(), "keep this")
        self.assertEqual(self.bridge.state["journal"]["posts"], [])


if __name__ == "__main__":
    unittest.main()
