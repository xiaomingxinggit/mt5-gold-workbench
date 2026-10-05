"""Clipboard-image drafts stay local to the active USC journal account."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench.infrastructure.journal_db import JournalRepository
from mt5_workbench.ui import qml_bridge as bridge_module


def _account(login: int = 101) -> SimpleNamespace:
    return SimpleNamespace(login=login, server="test-server", currency="USC",
                           name="Test", balance=10000, equity=10000, profit=0,
                           margin_free=10000, margin_level=0)


class _FakeApi:
    def __init__(self) -> None:
        self.current = _account()

    def account_info(self):
        return self.current

    def terminal_info(self):
        return SimpleNamespace(connected=True)


class QmlJournalPasteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JournalRepository(Path(self.temp.name) / "journal")
        self.api = _FakeApi()
        self.bridge = bridge_module.QmlBridge(
            autoconnect=False, start_timer=False,
            journal_repository=self.repo, api=self.api,
        )
        self.addCleanup(self.bridge.close)
        self.bridge.account = self.api.current
        self.bridge.connected = True
        self.bridge._set_state(
            connection={"connected": True, "locked": False, "message": "已连接"},
            account=bridge_module._account_map(self.api.current),
        )
        self.clipboard = QApplication.clipboard()
        self.addCleanup(self.clipboard.clear)

    def _copy_image(self) -> None:
        image = QImage(20, 20, QImage.Format_ARGB32)
        image.fill(0xffc87a14)
        self.clipboard.setImage(image)

    def test_paste_draft_is_scoped_and_removed_with_attachment(self) -> None:
        self.clipboard.setText("ordinary text")
        self.assertFalse(self.bridge.hasJournalImageOnClipboard())
        self._copy_image()
        self.assertTrue(self.bridge.hasJournalImageOnClipboard())

        self.bridge.perform("journalPasteImage", {})
        rows = self.bridge.state["journal"]["draftImages"]
        self.assertEqual(len(rows), 1)
        path = Path(rows[0]["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix, ".png")
        self.assertTrue(path.is_relative_to(self.repo.base_dir / "drafts" / "101"))
        self.assertLessEqual(path.stat().st_size, bridge_module.MAX_IMAGE_BYTES)
        self.assertFalse(QImage(str(path)).isNull())

        self.bridge.perform("journalRemoveImage", {"path": str(path)})
        self.assertEqual(self.bridge.state["journal"]["draftImages"], [])
        self.assertFalse(path.exists())

    def test_paste_enforces_four_images_and_account_switch_cleans_drafts(self) -> None:
        self._copy_image()
        for _ in range(5):
            self.bridge.perform("journalPasteImage", {})
        rows = self.bridge.state["journal"]["draftImages"]
        self.assertEqual(len(rows), 4)
        paths = [Path(row["path"]) for row in rows]
        self.assertIn("4 张", self.bridge.state["status"])

        self.api.current = _account(login=202)
        self.assertFalse(self.bridge.check_account_access())
        self.assertEqual(self.bridge.state["journal"]["draftImages"], [])
        self.assertTrue(all(not path.exists() for path in paths))

    def test_pasted_draft_can_be_copied_into_a_published_post(self) -> None:
        self._copy_image()
        self.bridge.perform("journalPasteImage", {})
        draft = Path(self.bridge.state["journal"]["draftImages"][0]["path"])
        self.repo.create_post((101, "test-server"), "截图复盘", (draft,))
        self.bridge._set_state(journal={**self.bridge.state["journal"],
                                        "draftImages": []})
        self.assertFalse(draft.exists())
        post = self.repo.list_posts((101, "test-server")).posts[0]
        self.assertEqual(post.body, "截图复盘")
        self.assertEqual(len(post.images), 1)
        self.assertTrue(post.images[0].is_file())

    def test_oversized_encoded_image_is_rejected_without_orphan_file(self) -> None:
        self._copy_image()
        with patch.object(bridge_module, "MAX_IMAGE_BYTES", 1):
            self.bridge.perform("journalPasteImage", {})
        self.assertEqual(self.bridge.state["journal"]["draftImages"], [])
        self.assertIn("8 MiB", self.bridge.state["status"])
        self.assertEqual(list((self.repo.base_dir / "drafts").rglob("*.png")), [])

    def test_ctrl_v_in_composer_pastes_image_without_text(self) -> None:
        engine = QQmlApplicationEngine()
        qml_dir = (Path(__file__).resolve().parents[1] / "src" / "mt5_workbench"
                   / "ui" / "qml")
        engine.addImportPath(str(qml_dir))
        engine.rootContext().setContextProperty("bridge", self.bridge)
        engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
        self.assertEqual(len(engine.rootObjects()), 1)
        window = engine.rootObjects()[0]
        self.bridge._set_state(page="journal",
                               journal={**self.bridge.state["journal"],
                                        "canPublish": True})
        self.app.processEvents()
        view = window.findChild(QQuickItem, "journalView")
        editor = window.findChild(QQuickItem, "journalBodyEditor")
        self.assertIsNotNone(view)
        self.assertIsNotNone(editor)
        view.setProperty("composing", True)
        window.show()
        editor.forceActiveFocus()
        self.clipboard.setText("普通文字")
        QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(view.property("draftBody"), "普通文字")
        editor.setProperty("text", "")
        self.app.processEvents()
        self._copy_image()
        QTest.keyClick(window, Qt.Key_V, Qt.ControlModifier)
        self.app.processEvents()
        self.assertEqual(len(self.bridge.state["journal"]["draftImages"]), 1)
        self.assertEqual(view.property("draftBody"), "")
        window.close()


if __name__ == "__main__":
    unittest.main()
