"""Account-independent release checks, with all Qt state changes on the UI thread."""

from queue import Empty, Queue
from threading import Thread

from PySide6.QtCore import QObject, QTimer, Signal

from mt5_workbench.services.app_updates import check_for_updates, initial_update_state


class UpdateController(QObject):
    changed = Signal("QVariantMap")
    notice = Signal(str, str)

    def __init__(self, parent=None, *, checker=None):
        super().__init__(parent)
        self.state = initial_update_state()
        self._checker = checker or check_for_updates
        self._queue = Queue()
        self._closed = False
        self._last_notified = ""
        self._manual = False
        self._periodic = QTimer(self)
        self._periodic.setInterval(6 * 60 * 60 * 1000)
        self._periodic.timeout.connect(self.check)
        self._startup = QTimer(self)
        self._startup.setSingleShot(True)
        self._startup.timeout.connect(self.check)
        self._drain = QTimer(self)
        self._drain.setInterval(100)
        self._drain.timeout.connect(self._consume)

    def start(self):
        self._startup.start(3000)
        self._periodic.start()

    def check(self, manual=False):
        if self._closed or self.state["busy"]:
            return
        self._manual = manual
        self.state = {**self.state, "busy": True, "message": "正在检查 GitHub 正式发布版本…"}
        self.changed.emit(self.state)
        checker, queue = self._checker, self._queue

        def run():
            try:
                result = checker()
            except Exception:
                result = {**initial_update_state(), "status": "error",
                          "message": "检查更新失败，请稍后重试。"}
            queue.put(result)

        Thread(target=run, name="github-release-check", daemon=True).start()
        self._drain.start()

    def _consume(self):
        if self._closed:
            return
        try:
            result = self._queue.get_nowait()
        except Empty:
            return
        self._drain.stop()
        self.state = {**result, "busy": False}
        self.changed.emit(self.state)
        if result["available"] and result["latestVersion"] != self._last_notified:
            self._last_notified = result["latestVersion"]
            self.notice.emit(result["message"], "success")
        elif self._manual:
            self.notice.emit(result["message"], "warning" if result["status"] == "error" else "success")

    def close(self):
        self._closed = True
        self._startup.stop()
        self._periodic.stop()
        self._drain.stop()
