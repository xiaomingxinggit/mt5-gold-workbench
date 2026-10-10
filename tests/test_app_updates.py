"""Release detection is offline-testable and independent of trading/account state."""

import io
import json
import os
from threading import Event
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mt5_workbench import __version__
from mt5_workbench.services import app_updates as updates
from mt5_workbench.ui.qml_bridge import QmlBridge
from mt5_workbench.ui.update_controller import UpdateController
from pathlib import Path


def release(version=None):
    if version is None:
        major, minor, patch = updates.version_tuple(__version__)
        version = f"{major}.{minor}.{patch + 1}"
    return {"tag_name": "v" + version, "draft": False, "prerelease": False,
            "html_url": updates.RELEASES_URL + "/tag/v" + version,
            "body": "新增功能\n修复问题",
            "assets": [{"name": updates.EXE_NAME, "state": "uploaded", "size": 1234,
                        "browser_download_url": updates.RELEASES_URL + "/download/v" + version + "/" + updates.EXE_NAME}]}


class ReleaseTests(unittest.TestCase):
    def test_numeric_versions_and_only_newer_stable_releases(self):
        self.assertTrue(updates.parse_release(release("0.10.0"), "0.9.9")["available"])
        for version in ("0.2.0", "0.1.0"):
            result = updates.parse_release(release(version), "0.2.0")
            self.assertEqual(result["status"], "current")
            self.assertFalse(result["available"])
        for flag in ("draft", "prerelease"):
            payload = release()
            payload[flag] = True
            with self.assertRaises(ValueError):
                updates.parse_release(payload)
        for tag in ("v0.2.1-rc.1", "latest", "v01.2.3", "1.2", None):
            payload = release()
            payload["tag_name"] = tag
            with self.assertRaises(ValueError):
                updates.parse_release(payload)

    def test_missing_or_incomplete_exe_does_not_offer_download(self):
        for assets in ([], [{"name": "source.zip"}],
                       [{**release()["assets"][0], "state": "new"}],
                       [{**release()["assets"][0], "size": 0}],
                       [{**release()["assets"][0], "browser_download_url": "https://example.com/app.exe"}]):
            result = updates.parse_release({**release(), "assets": assets})
            self.assertEqual(result["status"], "pending")
            self.assertFalse(result["available"])
            self.assertEqual(result["downloadUrl"], "")

    def test_untrusted_urls_and_oversized_or_malformed_responses(self):
        for page in ("http://github.com/" + updates.REPOSITORY + "/releases/tag/v0.2.1",
                     updates.RELEASES_URL + "/tag/v0.2.1?redirect=other",
                     "https://github.com.evil.com/a", "https://github.com/other/repo/releases/tag/v0.2.1"):
            with self.assertRaises(ValueError):
                updates.parse_release({**release(), "html_url": page})
        for body in (b"not-json", b"[]", b"x" * (updates.MAX_RESPONSE_BYTES + 1)):
            result = updates.check_for_updates(opener=Mock(return_value=io.BytesIO(body)))
            self.assertEqual(result["status"], "error")
            self.assertFalse(result["available"])

    def test_network_errors_are_distinguished_from_no_release(self):
        for code, status in ((404, "unpublished"), (403, "error"), (429, "error"), (500, "error")):
            result = updates.check_for_updates(opener=Mock(side_effect=HTTPError(updates.API_URL, code, "error", {}, None)))
            self.assertEqual(result["status"], status)
            self.assertTrue(result["checkedAt"])
        result = updates.check_for_updates(opener=Mock(side_effect=URLError("offline")))
        self.assertEqual(result["status"], "error")
        opener = Mock(return_value=io.BytesIO(json.dumps(release()).encode()))
        result = updates.check_for_updates(opener=opener)
        self.assertTrue(result["available"])
        self.assertEqual(opener.call_args.kwargs["timeout"], 10)
        self.assertEqual(opener.call_args.args[0].full_url, updates.API_URL)
        self.assertNotIn("Authorization", opener.call_args.args[0].headers)


class UpdateUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle("FluentWinUI3")
        cls.app = QApplication.instance() or QApplication([])

    def await_result(self, controller):
        for _ in range(100):
            QTest.qWait(20)
            if not controller.state["busy"]:
                return
        self.fail("release worker did not finish")

    def test_checks_do_not_block_and_close_discards_pending_result(self):
        gate = Event()
        checker = Mock(side_effect=lambda: (gate.wait(2), updates.parse_release(release()))[1])
        controller = UpdateController(checker=checker)
        self.addCleanup(controller.close)
        controller.check()
        controller.check()
        self.assertTrue(controller.state["busy"])
        self.app.processEvents()
        self.assertEqual(checker.call_count, 1)
        changed = Mock()
        controller.changed.connect(changed)
        controller.close()
        gate.set()
        QTest.qWait(150)
        controller._consume()
        changed.assert_not_called()

    def test_manual_check_works_when_account_locked_and_update_survives_reset(self):
        api = Mock()
        bridge = QmlBridge(autoconnect=False, start_timer=False, journal_repository=object(), api=api)
        self.addCleanup(bridge.close)
        bridge._clear_session("账户锁定", locked=True)
        bridge.updates._checker = Mock(return_value=updates.parse_release(release()))
        bridge.perform("checkUpdates", {})
        self.await_result(bridge.updates)
        self.assertTrue(bridge.state["updates"]["available"])
        bridge._clear_session("断线")
        self.assertTrue(bridge.state["updates"]["available"])
        with patch("mt5_workbench.ui.qml_bridge.QDesktopServices.openUrl", return_value=True) as browser:
            bridge.perform("downloadUpdate", {"url": "https://example.com"})
            self.assertEqual(browser.call_args.args[0].toString(), release()["assets"][0]["browser_download_url"])
        self.assertEqual(api.mock_calls, [])
        with patch("mt5_workbench.ui.qml_bridge.QDesktopServices.openUrl", return_value=True) as browser:
            bridge._clear_session("账户锁定", locked=True)
            bridge.perform("openDataDirectory", {})
            self.assertTrue(browser.call_args.args[0].isLocalFile())

    def test_automatic_checks_notify_once_and_failures_stay_quiet(self):
        checker = Mock(return_value=updates.parse_release(release()))
        controller = UpdateController(checker=checker)
        self.addCleanup(controller.close)
        notice = Mock()
        controller.notice.connect(notice)
        controller.start()
        self.assertEqual(controller._periodic.interval(), 6 * 60 * 60 * 1000)
        self.assertTrue(controller._startup.isActive())
        controller._startup.start(1)
        QTest.qWait(30)
        self.await_result(controller)
        notice.assert_called_once()
        controller.check()
        self.await_result(controller)
        notice.assert_called_once()
        checker.side_effect = RuntimeError("offline")
        controller.check()
        self.await_result(controller)
        self.assertEqual(controller.state["status"], "error")
        notice.assert_called_once()

    def test_settings_update_state_and_buttons_load_without_qml_warnings(self):
        bridge = QmlBridge(autoconnect=False, start_timer=False, journal_repository=object(), api=Mock())
        self.addCleanup(bridge.close)
        engine = QQmlApplicationEngine()
        warnings = []
        engine.warnings.connect(lambda values: warnings.extend(value.toString() for value in values))
        qml_dir = Path(__file__).resolve().parents[1] / "src/mt5_workbench/ui/qml"
        engine.addImportPath(str(qml_dir))
        engine.rootContext().setContextProperty("bridge", bridge)
        engine.load(QUrl.fromLocalFile(str(qml_dir / "App.qml")))
        self.assertEqual(len(engine.rootObjects()), 1)
        window = engine.rootObjects()[0]
        try:
            bridge.perform("navigate", {"page": "settings"})
            bridge._set_state(updates=updates.parse_release(release()))
            QTest.qWait(30)
            button = window.findChild(QQuickItem, "downloadUpdateButton")
            self.assertTrue(button.isVisible())
            self.assertEqual(window.property("updateData")["currentVersion"], __version__)
            for width, height in ((1200, 800), (1440, 900), (2560, 1440)):
                window.resize(width, height)
                QTest.qWait(20)
                self.assertFalse(window.grabWindow().isNull())
            self.assertEqual(warnings, [])
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
