"""Journal UI contracts: local drafts and account-scoped rendering only."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel

from mt5_workbench.ui.pages.journal import MarketJournalPage
from mt5_workbench.ui.theme import THEMES


def _position(*, closed: bool = False):
    return SimpleNamespace(
        position_id=345, ticket=345, symbol="XAUUSDc", side="BUY",
        volume=Decimal("0.01"), floating_usc=Decimal("75"),
        status="closed" if closed else "open",
        result_usc=Decimal("123") if closed else None,
    )


class MarketJournalPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_feed_shows_closed_position_result_and_pages(self):
        page = MarketJournalPage(THEMES["light"])
        self.addCleanup(page.close)
        post = SimpleNamespace(
            id=9, account_key=(123, "server"), body="复盘这次开仓",
            created_at=datetime.now(timezone.utc), images=(),
            positions=(_position(closed=True),),
        )
        data = SimpleNamespace(posts=(post,), total=23, page=2,
                               page_size=10, total_pages=3)
        page.set_content(data, {date.today(): 2}, (), "账户 123")
        page.set_can_publish(True)
        page.resize(1050, 900)
        page.show()
        self.app.processEvents()

        self.assertEqual(page.current_page, 2)
        self.assertEqual([label.text() for label in page.summary_values], ["23", "2", "1"])
        texts = [label.text() for label in page.findChildren(QLabel) if label.isVisible()]
        self.assertTrue(any("已平仓 · 最终 +123.00 USC" in text and "+1.23 USD" in text
                            for text in texts))
        requests: list[int] = []
        page.page_requested.connect(requests.append)
        page.previous_button.click()
        page.next_button.click()
        self.assertEqual(requests, [1, 3])
        page.resize(1760, 950)
        self.app.processEvents()
        x0, _y0, cell, gap = page.heatmap._geometry()
        grid_width = page.heatmap._weeks * cell + (page.heatmap._weeks - 1) * gap
        self.assertLess(abs((x0 - 28) - (page.heatmap.width() - x0 - grid_width)), 3)

    def test_failed_save_keeps_text_images_and_selected_positions(self):
        page = MarketJournalPage(THEMES["dark"])
        self.addCleanup(page.close)
        page.set_can_publish(True)
        page.set_content(None, {}, (_position(),), "账户 123")
        page.open_composer()
        dialog = page._composer
        self.assertIsNotNone(dialog)
        self.addCleanup(dialog.close)
        dialog.body.setPlainText("测试日志")
        dialog.position_list.item(0).setCheckState(Qt.CheckState.Checked)

        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "note.png"
            self.assertTrue(QImage(2, 2, QImage.Format.Format_RGB32).save(str(image)))
            with patch("mt5_workbench.ui.pages.journal.QFileDialog.getOpenFileNames",
                       return_value=([str(image)], "")):
                dialog._choose_images()
            emitted: list[tuple[str, tuple[str, ...], tuple[int, ...]]] = []
            page.publish_requested.connect(lambda body, paths, positions:
                                           emitted.append((body, paths, positions)))
            dialog._submit()
            self.assertEqual(emitted, [("测试日志", (str(image),), (345,))])
            self.assertFalse(dialog.submit_button.isEnabled())
            page.publish_failed("磁盘暂不可写")
            self.assertTrue(dialog.submit_button.isEnabled())
            self.assertEqual(dialog.body.toPlainText(), "测试日志")
            self.assertEqual(dialog.image_paths, (str(image),))
            self.assertEqual(dialog.position_list.item(0).checkState(), Qt.CheckState.Checked)
            self.assertTrue(dialog.isVisible())
            page.publish_succeeded()
            self.assertFalse(dialog.isVisible())

    def test_empty_position_list_still_allows_a_post(self):
        page = MarketJournalPage(THEMES["light"])
        self.addCleanup(page.close)
        page.set_can_publish(True)
        page.open_composer()
        dialog = page._composer
        self.assertIsNotNone(dialog)
        self.addCleanup(dialog.close)
        dialog.body.setPlainText("仅记录行情")
        emitted = []
        page.publish_requested.connect(lambda *args: emitted.append(args))
        dialog._submit()
        self.assertEqual(emitted, [("仅记录行情", (), ())])

    def test_changed_position_is_not_labeled_as_still_open(self):
        page = MarketJournalPage(THEMES["light"])
        self.addCleanup(page.close)
        changed = _position()
        changed.status = "unverified"
        row = page._position_row(changed)
        self.addCleanup(row.close)
        texts = [label.text() for label in row.findChildren(QLabel)]
        self.assertTrue(any("持仓已变化，结果待核实" in text for text in texts))
        self.assertFalse(any("持仓中" in text for text in texts))

    def test_offline_open_link_is_labeled_for_sync(self):
        page = MarketJournalPage(THEMES["light"])
        self.addCleanup(page.close)
        post = SimpleNamespace(
            id=1, account_key=(123, "server"), body="离线记录",
            created_at=datetime.now(timezone.utc), images=(),
            positions=(_position(),),
        )
        data = SimpleNamespace(posts=(post,), total=1, page=1,
                               page_size=10, total_pages=1)
        page.set_content(data, {}, (), "账户 123 · 离线浏览",
                         positions_current=False)
        texts = [label.text() for label in page.findChildren(QLabel)]
        self.assertTrue(any("状态待同步 · 发布时浮动" in text for text in texts))


if __name__ == "__main__":
    unittest.main()
