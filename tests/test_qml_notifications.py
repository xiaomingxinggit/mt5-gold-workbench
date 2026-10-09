"""Visible result notifications preserve the status bar and normal UI input."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench.infrastructure.journal_db import JournalRepository
from mt5_workbench.ui import qml_bridge as bridge_module
from mt5_workbench.ui.qml_trade_bridge import QmlTradingBridge


class FakeApi:
    current = SimpleNamespace(login=101, server="test-server", currency="USC")

    def account_info(self):
        return self.current

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def order_send(self, *_args, **_kwargs):
        raise AssertionError("Notification tests must not send trades")


class QmlNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = JournalRepository(Path(self.temp.name) / "journal")
        self.bridge = QmlTradingBridge(autoconnect=False, start_timer=False,
                                       journal_repository=self.repo, api=FakeApi())
        self.addCleanup(self.bridge.close)
        self.bridge.account = FakeApi.current
        self.bridge.connected = True
        self.bridge._set_state(theme="light", connection={"connected": True, "locked": False})
        self.engine = QQmlApplicationEngine()
        self.warnings = []
        self.engine.warnings.connect(lambda items: self.warnings.extend(str(item) for item in items))
        qml_dir = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml"
        self.engine.rootContext().setContextProperty("bridge", self.bridge)
        self.engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
        self.assertEqual(len(self.engine.rootObjects()), 1)
        self.window = self.engine.rootObjects()[0]
        self.addCleanup(self.window.close)
        self.addCleanup(self.app.clipboard().clear)
        QTest.qWait(20)
        self.host = self.window.findChild(QQuickItem, "toastHost")

    def items(self, name, parent=None):
        parent = self.window.contentItem() if parent is None else parent
        found = [parent] if parent.objectName() == name else []
        for child in parent.childItems():
            found.extend(self.items(name, child))
        return found

    def click(self, item):
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(20)

    def test_share_shows_success_and_each_repeat_appears_with_status_bar_preserved(self):
        post_id = self.repo.create_post((101, "test-server"), "观察行情")
        post = self.repo.list_posts((101, "test-server")).posts[0]
        self.bridge._set_state(page="journal", journal={**self.bridge.state["journal"],
                               "posts": [bridge_module._journal_post(post)], "canPublish": True})
        QTest.qWait(20)
        for count in (1, 2):
            self.click(self.items("journalShare")[0])
            self.assertEqual(self.host.property("count"), count)
            self.assertIn("已复制到剪贴板", self.window.property("statusText"))
            self.assertFalse(self.app.clipboard().image().isNull())
        toast = self.items("notificationToast")[-1]
        self.assertEqual(toast.property("level"), "success")
        self.assertIn("已复制到剪贴板", toast.property("message"))
        self.assertEqual(toast.property("tone").name(), "#087f73")
        self.assertTrue(toast.isVisible())
        self.assertEqual(self.warnings, [])

    def test_failed_operation_shows_red_toast_and_remains_in_status_bar(self):
        self.bridge.perform("journalShare", {"postId": 0})
        self.app.processEvents()
        toast = self.items("notificationToast")[0]
        self.assertEqual(toast.property("level"), "error")
        self.assertEqual(toast.property("tone").name(), "#c4475c")
        self.assertIn("分享失败", toast.property("message"))
        self.assertEqual(self.window.property("statusText"), toast.property("message"))
        self.assertEqual(toast.findChild(QObject, "notificationExpiry").property("interval"), 7000)
        self.click(self.items("notificationClose", toast)[0])
        self.assertEqual(self.host.property("count"), 0)
        self.assertIn("分享失败", self.window.property("statusText"))

    def test_auto_dismiss_does_not_clear_status_and_hover_pauses_expiry(self):
        self.bridge._set_status("配置已复制到剪贴板")
        self.app.processEvents()
        toast = self.items("notificationToast")[0]
        timer = toast.findChild(QObject, "notificationExpiry")
        self.assertEqual(timer.property("interval"), 4000)
        timer.setProperty("interval", 80)
        point = toast.mapToScene(QPointF(20, 20)).toPoint()
        QTest.mouseMove(self.window, point)
        QTest.qWait(120)
        self.assertEqual(self.host.property("count"), 1)
        QTest.mouseMove(self.window, QPointF(5, 5).toPoint())
        QTest.qWait(150)
        self.assertEqual(self.host.property("count"), 0)
        self.assertEqual(self.window.property("statusText"), "配置已复制到剪贴板")

    def test_background_diagnostics_are_deduplicated_until_recovery(self):
        data = {**self.bridge.state["overview"], "errors": ["历史读取失败"]}
        self.bridge._set_state(overview=data)
        for loading in (True, False, True, False):
            self.bridge._set_state(overview={**data, "loading": loading})
        self.bridge._set_status("交易概览已更新", notify=False)
        self.app.processEvents()
        self.assertEqual(self.host.property("count"), 1)
        self.bridge._set_state(overview={**data, "errors": []})
        self.bridge._set_state(overview=data)
        self.app.processEvents()
        self.assertEqual(self.host.property("count"), 2)
        self.bridge._set_state(market={"bid": None, "stale": True, "message": "报价读取失败"})
        self.app.processEvents()
        self.assertEqual(self.items("notificationToast")[-1].property("level"), "error")

    def test_toasts_stay_above_modal_and_do_not_take_input_focus(self):
        self.bridge._set_state(page="journal")
        self.app.processEvents()
        view = self.window.findChild(QQuickItem, "journalView")
        view.setProperty("composing", True)
        self.app.processEvents()
        editor = self.window.findChild(QQuickItem, "journalBodyEditor")
        self.assertIsNotNone(editor)
        editor.forceActiveFocus()
        focused = self.window.activeFocusItem()
        self.bridge._set_status("图片已添加")
        self.app.processEvents()
        self.assertEqual(self.window.activeFocusItem(), focused)
        self.bridge._set_state(confirmation={"token": "preview", "title": "确认操作", "rows": [], "columns": []})
        self.bridge._set_status("操作未完成", level="error")
        self.app.processEvents()
        toast = self.items("notificationToast")[-1]
        self.assertTrue(toast.isVisible())
        self.assertGreater(self.host.z(), 100)
        self.assertLessEqual(toast.mapToScene(QPointF(toast.width(), 0)).x(), self.window.width())
        self.click(self.items("notificationClose", toast)[0])
        self.assertEqual(self.window.property("confirmationToken"), "preview")
        self.assertEqual(self.host.property("count"), 1)
        self.assertEqual(self.warnings, [])

    def test_manual_refresh_reports_success_while_automatic_refresh_stays_quiet(self):
        self.repo.create_post((101, "test-server"), "行情观察")

        def finish():
            deadline = time.monotonic() + 2
            while self.bridge._jobs and time.monotonic() < deadline:
                self.bridge._consume_results()
                QTest.qWait(10)
            self.assertFalse(self.bridge._jobs)

        with patch.object(bridge_module, "sync_closed_positions", return_value=SimpleNamespace(errors=())), \
                patch.object(bridge_module, "load_open_positions", return_value=()):
            self.bridge.refresh_journal(force=True)
            finish()
            self.assertEqual(self.host.property("count"), 0)
            self.bridge.perform("journalRefresh", {})
            finish()
            self.assertEqual(self.host.property("count"), 1)
            self.assertEqual(self.items("notificationToast")[0].property("level"), "success")
            self.assertEqual(self.window.property("statusText"), "行情日志已更新")


if __name__ == "__main__":
    unittest.main()
