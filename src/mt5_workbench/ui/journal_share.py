"""Lay out a published journal entry as a standalone clipboard image."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any, Mapping

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import (
    QAbstractTextDocumentLayout, QColor, QFont, QImage, QImageReader,
    QPainter, QPalette, QTextBlockFormat, QTextCursor, QTextDocument, QTextOption,
)

from mt5_workbench.domain.journal import beijing_time
from mt5_workbench.ui.theme import FONT_FAMILY


_WIDTH = 1080
_MARGIN = 56
_CONTENT_WIDTH = _WIDTH - 2 * _MARGIN
_MAX_HEIGHT = 24000
_TEXT = "#182D3A"
_MUTED = "#667A86"
_ACCENT = "#087F73"


@dataclass
class _Block:
    y: int
    height: int
    content: QTextDocument | QImage | None
    color: str = _TEXT
    inset: int = 0
    background: bool = False


class _Layout:
    def __init__(self) -> None:
        self.y = _MARGIN
        self.blocks: list[_Block] = []

    def _append(self, block: _Block, gap: int) -> None:
        if block.y + block.height + gap + _MARGIN > _MAX_HEIGHT:
            raise ValueError("日志内容过长，无法生成单张分享图片")
        self.blocks.append(block)
        self.y += block.height + gap

    def text(self, value: str, size: int = 28, *, color: str = _TEXT,
             bold: bool = False, gap: int = 24, background: bool = False) -> None:
        if not value:
            return
        inset = 20 if background else 0
        document = QTextDocument()
        document.setDocumentMargin(0)
        font = QFont(FONT_FAMILY)
        font.setPixelSize(size)
        font.setBold(bold)
        document.setDefaultFont(font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        # Plain text preserves literal markup and never fetches remote resources.
        document.setPlainText(value)
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)
        document.setTextWidth(_CONTENT_WIDTH - 2 * inset)
        height = math.ceil(document.size().height()) + 2 * inset
        self._append(_Block(self.y, height, document, color, inset, background), gap)

    def divider(self) -> None:
        self._append(_Block(self.y, 2, None), 28)

    def image(self, source: str) -> None:
        url = QUrl(source)
        if not url.isLocalFile():
            raise ValueError("分享图片必须来自本地日志")
        reader = QImageReader(url.toLocalFile())
        reader.setAutoTransform(True)
        if reader.size().isValid():
            reader.setScaledSize(reader.size().scaled(
                QSize(_CONTENT_WIDTH, 4096), Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
        if image.isNull():
            raise ValueError("日志图片缺失或无法读取，请检查图片后重试")
        image = image.scaled(QSize(_CONTENT_WIDTH, 4096),
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self._append(_Block(self.y, image.height(), image), 24)

    def render(self) -> QImage:
        image = QImage(_WIDTH, self.y + _MARGIN, QImage.Format.Format_RGB32)
        if image.isNull():
            raise ValueError("分享图片生成失败，内存不足")
        image.fill(QColor("#FFFFFF"))
        painter = QPainter(image)
        if not painter.isActive():
            raise ValueError("分享图片生成失败")
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.fillRect(0, 0, _WIDTH, 8, QColor(_ACCENT))
            for block in self.blocks:
                if isinstance(block.content, QTextDocument):
                    if block.background:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QColor("#F2F6F7"))
                        painter.drawRoundedRect(
                            QRectF(_MARGIN, block.y, _CONTENT_WIDTH, block.height), 12, 12)
                    painter.save()
                    painter.translate(_MARGIN + block.inset, block.y + block.inset)
                    context = QAbstractTextDocumentLayout.PaintContext()
                    context.palette.setColor(QPalette.ColorRole.Text, QColor(block.color))
                    block.content.documentLayout().draw(painter, context)
                    painter.restore()
                elif isinstance(block.content, QImage):
                    # Center the complete source image without cropping tall charts.
                    x = _MARGIN + (_CONTENT_WIDTH - block.content.width()) / 2
                    painter.drawImage(QPointF(x, block.y), block.content)
                else:
                    painter.fillRect(_MARGIN, block.y, _CONTENT_WIDTH, 2, QColor("#E4ECEF"))
        finally:
            painter.end()
        return image


def _timestamp(post: Mapping[str, Any]) -> str:
    value = post.get("createdAt")
    if value:
        return beijing_time(datetime.fromisoformat(str(value))).strftime("%Y-%m-%d %H:%M")
    return f"{post.get('dateLabel', '')} {post.get('timeLabel', '')}".strip()


def _amount(value: Any) -> str:
    try:
        amount = float(value)
    except (ValueError, TypeError, OverflowError):
        return "—"
    return f"{amount:+,.2f}" if math.isfinite(amount) else "—"


def render_journal_share(post: Mapping[str, Any]) -> QImage:
    """Render the bridge's published post, including linked positions and replies.

    Raises ValueError instead of silently truncating content or omitting an image.
    The caller replaces the clipboard only after rendering completes successfully.
    """
    layout = _Layout()
    layout.text("行情日志", 46, bold=True, gap=12)
    layout.text(_timestamp(post) + " · 北京时间", 23, color=_MUTED, gap=30)
    layout.divider()
    layout.text(str(post.get("body") or ""), gap=30)
    for source in post.get("images", []):
        layout.image(str(source))
    positions = post.get("positions", [])
    if positions:
        layout.divider()
        layout.text(f"关联持仓 · {len(positions)}", 26, bold=True, gap=18)
        for position in positions:
            status = position.get("status", "open")
            if status == "closed":
                result = "已平仓 · 最终 " + _amount(position.get("resultUsd")) + " USD"
            elif status == "unverified":
                result = "持仓已变化，结果待核实"
            else:
                result = "持仓中 · 发布时浮动 " + _amount(position.get("floatingUsd")) + " USD"
            label = (f"#{position.get('ticket', '—')} · {position.get('side', '—')} "
                     f"{position.get('symbol', '—')} · {position.get('volume', '—')} lot")
            layout.text(label + "\n" + result, 24, background=True, gap=16)
    replies = post.get("replies", [])
    if replies:
        layout.divider()
        layout.text(f"后续回复 · {len(replies)}", 26, bold=True, gap=24)
        for index, reply in enumerate(replies):
            if index:
                layout.divider()
            layout.text(_timestamp(reply) + " · 北京时间", 22, color=_MUTED, gap=16)
            layout.text(str(reply.get("body") or ""), 26)
            for source in reply.get("images", []):
                layout.image(str(source))
    layout.divider()
    layout.text("MT5 WORKBENCH  /  行情记录", 20, color=_MUTED, gap=0)
    return layout.render()
