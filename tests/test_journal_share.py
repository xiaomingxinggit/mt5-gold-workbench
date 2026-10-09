"""Sharing preserves readable text, complete attachments and published replies."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument
from PySide6.QtWidgets import QApplication

from mt5_workbench.ui.journal_share import _Layout, render_journal_share


class JournalShareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def post(self, **updates):
        return {"createdAt": "2026-10-06T17:30:00+00:00", "body": "观察行情",
                "images": [], "positions": [], "replies": [], **updates}

    def test_plain_text_wraps_and_preserves_full_post_positions_and_replies(self):
        body = "<b>不是 HTML</b>\n" + "中文与English混排 " * 100 + "正文末尾"
        post = self.post(body=body, positions=[{
            "ticket": 123, "side": "BUY", "symbol": "XAUUSDc", "volume": 0.01,
            "status": "closed", "resultUsd": -12.34,
        }], replies=[{"createdAt": "2026-10-07T02:00:00+08:00", "body": "回复末尾"}])
        documents = []
        original = _Layout.render

        def capture(layout):
            documents.extend(block.content.toPlainText() for block in layout.blocks
                             if isinstance(block.content, QTextDocument))
            return original(layout)

        with patch.object(_Layout, "render", capture):
            image = render_journal_share(post)
        self.assertFalse(image.isNull())
        self.assertGreater(image.height(), 1000)
        self.assertIn(body, documents)
        self.assertIn("2026-10-07 01:30 · 北京时间", documents)
        self.assertIn("回复末尾", documents)
        self.assertTrue(any("#123" in text and "-12.34 USD" in text for text in documents))
        self.assertEqual(image.pixelColor(0, image.height() - 1), QColor("#FFFFFF"))

    def test_full_portrait_and_landscape_images_include_both_edges_in_order(self):
        with TemporaryDirectory() as directory:
            urls = []
            colors = ("#FF0000", "#0000FF", "#00FF00", "#FF00FF")
            for index, (width, height) in enumerate(((1200, 600), (100, 1000))):
                picture = QImage(width, height, QImage.Format.Format_RGB32)
                painter = QPainter(picture)
                painter.fillRect(0, 0, width, height // 2, QColor(colors[index * 2]))
                painter.fillRect(0, height // 2, width, height - height // 2,
                                 QColor(colors[index * 2 + 1]))
                painter.end()
                path = Path(directory) / f"chart {index}.png"
                self.assertTrue(picture.save(str(path)))
                urls.append(QUrl.fromLocalFile(str(path)).toString())
            image = render_journal_share(self.post(images=urls[:1], replies=[{
                "createdAt": "2026-10-07T02:00:00+08:00", "images": urls[1:]}]))
            found = []
            for y in range(image.height()):
                color = image.pixelColor(image.width() // 2, y).name().upper()
                if color in colors and (not found or color != found[-1]):
                    found.append(color)
            self.assertEqual(found, list(colors))

    def test_images_only_post_and_long_unbroken_text_are_supported(self):
        image = render_journal_share(self.post(body="X" * 2100))
        self.assertEqual(image.width(), 1080)
        self.assertGreater(image.height(), 1000)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "only image.png"
            picture = QImage(800, 500, QImage.Format.Format_RGB32)
            picture.fill(QColor("#CCAA22"))
            self.assertTrue(picture.save(str(path)))
            image = render_journal_share(self.post(body="", images=[
                QUrl.fromLocalFile(str(path)).toString()]))
            self.assertGreater(image.height(), 500)

    def test_missing_images_and_excessively_long_threads_fail_without_truncation(self):
        with self.assertRaisesRegex(ValueError, "无法读取"):
            render_journal_share(self.post(images=[QUrl.fromLocalFile(
                str(Path("missing-chart.png").resolve())).toString()]))
        with self.assertRaisesRegex(ValueError, "过长"):
            render_journal_share(self.post(replies=[{"body": "回复\n" * 100}] * 20))


if __name__ == "__main__":
    unittest.main()
