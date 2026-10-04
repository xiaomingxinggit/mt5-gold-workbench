"""Local market journal: activity, short posts and a draft composer.

The view never accesses MT5 or SQLite. Its owner supplies account-scoped data
and handles publish/delete signals after validating the current account.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from mt5_workbench.ui.theme import FONT_FAMILY, FONT_SIZES

if TYPE_CHECKING:
    from mt5_workbench.domain.journal import JournalPage, PositionSnapshot


_MAX_IMAGES = 4
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_BODY = 2100
_MAX_LINKED_POSITIONS = 20
_IMAGE_FILTER = "图片 (*.png *.jpg *.jpeg *.webp *.gif);;所有文件 (*)"


def _field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _plain(text: str, role: str = "body", *, wrap: bool = False) -> QLabel:
    item = QLabel(text)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setProperty("role", role)
    item.setWordWrap(wrap)
    return item


def _decimal_text(value: Any, places: int = 2, *, signed: bool = False) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    if not amount.is_finite():
        return "—"
    return f"{amount:+,.{places}f}" if signed else f"{amount:,.{places}f}"


def _datetime_text(value: Any) -> str:
    if not isinstance(value, datetime):
        return "—"
    try:
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return "—"


def _pnl_text(value: Any) -> str:
    try:
        usc = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    if not usc.is_finite():
        return "—"
    usd = usc / Decimal("100")
    return f"{usc:+,.2f} USC  /  {usd:+,.2f} USD"


def _pnl_role(value: Any) -> str:
    try:
        return "positive" if Decimal(str(value)) >= 0 else "negative"
    except (InvalidOperation, TypeError, ValueError):
        return "muted"


class ActivityHeatmap(QWidget):
    """A compact, accessible 365-day contribution grid."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = dict(palette)
        self._activity: dict[date, int] = {}
        self._today = date.today()
        self._first = self._today - timedelta(days=364)
        self._grid_start = self._first - timedelta(days=self._first.weekday())
        self._weeks = ((self._today - self._grid_start).days // 7) + 1
        self._cells: list[tuple[date, QRectF]] = []
        self.setMouseTracking(True)
        self.setFixedHeight(184)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("过去 365 天发帖贡献图")

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        self.update()

    def set_activity(self, activity: Mapping[date, int]) -> None:
        self._today = date.today()
        self._first = self._today - timedelta(days=364)
        self._grid_start = self._first - timedelta(days=self._first.weekday())
        self._weeks = ((self._today - self._grid_start).days // 7) + 1
        clean: dict[date, int] = {}
        for day, count in activity.items():
            if isinstance(day, date) and not isinstance(day, datetime):
                try:
                    clean[day] = max(0, int(count))
                except (TypeError, ValueError, OverflowError):
                    pass
        self._activity = clean
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(760, 184)

    def _geometry(self) -> tuple[int, int, int, int]:
        # A small square remains legible at 1200 px; wide layouts use up to 15 px.
        available = max(0, self.width() - 50)
        gap = 3 if available >= 700 else 2
        cell = max(7, min(15, (available - gap * (self._weeks - 1)) // self._weeks))
        grid_width = self._weeks * cell + (self._weeks - 1) * gap
        x0 = max(38, (self.width() - (28 + grid_width)) // 2 + 28)
        return x0, 32, cell, gap

    def paintEvent(self, _event) -> None:
        p = self._palette
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(p["muted"]))
        font = QFont(FONT_FAMILY)
        font.setPixelSize(FONT_SIZES["caption"])
        painter.setFont(font)
        x0, y0, cell, gap = self._geometry()
        painter.drawText(x0 - 28, y0 + cell + 1, "一")
        painter.drawText(x0 - 28, y0 + 3 * (cell + gap) + cell + 1, "三")
        painter.drawText(x0 - 28, y0 + 5 * (cell + gap) + cell + 1, "五")

        last_month: int | None = None
        self._cells = []
        for week in range(self._weeks):
            first_day = self._grid_start + timedelta(days=week * 7)
            if self._first <= first_day <= self._today and first_day.month != last_month:
                month_x = x0 + week * (cell + gap)
                painter.setPen(QColor(p["muted"]))
                painter.drawText(month_x, 19, f"{first_day.month}月")
                last_month = first_day.month
            for weekday in range(7):
                day = first_day + timedelta(days=weekday)
                if day < self._first or day > self._today:
                    continue
                count = self._activity.get(day, 0)
                if count == 0:
                    color = QColor(p["surface_alt"])
                else:
                    # Stable bands keep colors meaningful between refreshes.
                    opacity = 72 if count == 1 else 120 if count <= 3 else 185 if count <= 6 else 255
                    color = QColor(p["accent"])
                    color.setAlpha(opacity)
                rect = QRectF(x0 + week * (cell + gap), y0 + weekday * (cell + gap), cell, cell)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 2, 2)
                self._cells.append((day, rect))

        legend_y = y0 + 7 * (cell + gap) + 10
        painter.setPen(QColor(p["muted"]))
        painter.drawText(x0, legend_y + 10, "少")
        for index, opacity in enumerate((0, 72, 120, 185, 255)):
            color = QColor(p["surface_alt"] if not opacity else p["accent"])
            if opacity:
                color.setAlpha(opacity)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x0 + 23 + index * 19, legend_y, 13, 13), 2, 2)
        painter.setPen(QColor(p["muted"]))
        painter.drawText(x0 + 124, legend_y + 10, "多")
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        point = event.position()
        for day, rect in self._cells:
            if rect.contains(point):
                count = self._activity.get(day, 0)
                QToolTip.showText(event.globalPosition().toPoint(),
                                  f"{day.isoformat()} · {count} 篇记录", self)
                return
        QToolTip.hideText()

    def leaveEvent(self, event) -> None:
        QToolTip.hideText()
        super().leaveEvent(event)


class _ImageThumb(QLabel):
    def __init__(self, path: Path, palette: Mapping[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        self._palette = dict(palette)
        self.setFixedSize(176, 132)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击预览图片")
        self.setProperty("role", "image")
        self._render()

    def _render(self) -> None:
        pixmap = QPixmap(str(self.path))
        if pixmap.isNull():
            self.setText("图片暂不可用")
            self.setProperty("role", "missing-image")
            return
        self.setPixmap(pixmap.scaled(self.size() - QSize(8, 8),
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pixmap = QPixmap(str(self.path))
        if pixmap.isNull():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.path.name)
        dialog.resize(860, 650)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        view = QLabel()
        view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view.setPixmap(pixmap.scaled(QSize(800, 570),
                                    Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(view, 1)
        close = QPushButton("关闭")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()


class PublishDialog(QDialog):
    """Draft editor; emits a request and waits for explicit persistence feedback."""

    submitted = Signal(str, tuple, tuple)

    def __init__(self, palette: Mapping[str, str], positions: tuple[PositionSnapshot, ...],
                 account_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = dict(palette)
        self._positions = positions
        self._image_paths: list[Path] = []
        self._busy = False
        self._allowed = True
        self.setWindowTitle("发布行情日志")
        self.setMinimumSize(680, 620)
        self.resize(780, 710)
        self.setModal(True)
        self.setObjectName("journalComposer")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 22)
        root.setSpacing(14)
        root.addWidget(_plain("发布行情日志", "dialog-title"))
        root.addWidget(_plain(f"仅保存在本地 · {account_label}", "caption"))
        root.addWidget(_plain("记录想法", "field-label"))
        self.body = QPlainTextEdit()
        self.body.setPlaceholderText("写下此刻的行情观察、开仓依据或复盘想法…")
        self.body.setMinimumHeight(140)
        self.body.setMaximumHeight(220)
        self.body.textChanged.connect(self._update_counter)
        root.addWidget(self.body)
        self.counter = _plain(f"还可输入 {_MAX_BODY} 字", "caption")
        root.addWidget(self.counter, 0, Qt.AlignmentFlag.AlignRight)

        image_header = QHBoxLayout()
        image_header.addWidget(_plain("添加图片", "field-label"))
        image_header.addStretch(1)
        self.add_image_button = QPushButton("选择图片")
        self.add_image_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_image_button.clicked.connect(self._choose_images)
        image_header.addWidget(self.add_image_button)
        root.addLayout(image_header)
        root.addWidget(_plain("最多 4 张，单张不超过 8 MiB；图片会复制到本地日志目录。", "caption"))
        self.image_row = QHBoxLayout()
        self.image_row.setSpacing(10)
        self.image_row.addStretch(1)
        root.addLayout(self.image_row)

        root.addWidget(_plain("关联当前持仓（可多选）", "field-label"))
        root.addWidget(_plain("最多关联 20 笔；平仓后更新最终盈亏，不关联也可以发布。", "caption"))
        self.position_list = QListWidget()
        self.position_list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.position_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.position_list.setMinimumHeight(92)
        self.position_list.setMaximumHeight(170)
        if positions:
            for position in positions:
                ticket = _field(position, "ticket", _field(position, "position_id", "—"))
                side = _field(position, "side", "—")
                symbol = _field(position, "symbol", "—")
                volume = _decimal_text(_field(position, "volume"), 2)
                floating = _decimal_text(_field(position, "floating_usc"), signed=True)
                item = QListWidgetItem(
                    f"#{ticket}  ·  {side} {symbol}  ·  {volume} lot  ·  浮动 {floating} USC")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, int(_field(position, "position_id")))
                self.position_list.addItem(item)
        else:
            item = QListWidgetItem("当前没有可关联的持仓")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.position_list.addItem(item)
        root.addWidget(self.position_list)
        root.addStretch(1)
        self.notice = _plain("", "error", wrap=True)
        self.notice.hide()
        root.addWidget(self.notice)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.submit_button = QPushButton("发布到本地")
        self.submit_button.setObjectName("primary")
        self.submit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.submit_button.clicked.connect(self._submit)
        buttons.addWidget(self.submit_button)
        root.addLayout(buttons)
        self.set_palette(palette)

    @property
    def image_paths(self) -> tuple[str, ...]:
        return tuple(str(path) for path in self._image_paths)

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        p = self._palette
        check_icon = (Path(__file__).resolve().parents[1] / "resources" / "icons" /
                      "check-light-16.png").as_posix()
        self.setStyleSheet(f"""
            QDialog#journalComposer {{ background: {p['bg']}; color: {p['text']};
                font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZES['body']}px; }}
            QDialog#journalComposer QLabel[role="dialog-title"] {{ color: {p['text']};
                font-size: 22px; font-weight: 700; }}
            QDialog#journalComposer QLabel[role="field-label"] {{ color: {p['text']};
                font-size: {FONT_SIZES['body']}px; font-weight: 700; }}
            QDialog#journalComposer QLabel[role="caption"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['caption']}px; }}
            QDialog#journalComposer QLabel[role="error"] {{ color: {p['negative']};
                font-size: {FONT_SIZES['caption']}px; }}
            QDialog#journalComposer QPlainTextEdit,
            QDialog#journalComposer QListWidget {{ background: {p['surface']};
                color: {p['text']}; border: 1px solid {p['border']}; border-radius: 9px;
                padding: 10px; selection-background-color: {p['selected']}; }}
            QDialog#journalComposer QPlainTextEdit:focus,
            QDialog#journalComposer QListWidget:focus {{ border-color: {p['accent']}; }}
            QDialog#journalComposer QListWidget::item {{ padding: 7px 5px; }}
            QDialog#journalComposer QListWidget::indicator {{ width: 16px; height: 16px;
                border: 1px solid {p['muted']}; border-radius: 4px;
                background: {p['surface_alt']}; }}
            QDialog#journalComposer QListWidget::indicator:checked {{
                border-color: {p['accent']}; background: {p['accent']};
                image: url("{check_icon}"); }}
        """)

    def _update_counter(self) -> None:
        count = len(self.body.toPlainText().strip())
        remaining = _MAX_BODY - count
        self.counter.setText(f"还可输入 {remaining} 字" if remaining >= 0 else f"已超出 {-remaining} 字")
        self.counter.setProperty("role", "error" if count > _MAX_BODY else "caption")
        self.counter.style().unpolish(self.counter)
        self.counter.style().polish(self.counter)

    def _choose_images(self) -> None:
        remaining = _MAX_IMAGES - len(self._image_paths)
        if remaining <= 0:
            self._show_error("每篇最多添加 4 张图片。")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "选择图片", "", _IMAGE_FILTER)
        if not paths:
            return
        requested = [Path(raw) for raw in paths if Path(raw) not in self._image_paths]
        if len(requested) > remaining:
            self._show_error(f"还可以添加 {remaining} 张图片，请减少选择数量。")
            return
        for path in requested:
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                self._show_error(f"不支持的图片格式：{path.name}")
                return
            try:
                size = path.stat().st_size
            except OSError:
                self._show_error(f"无法读取图片：{path.name}")
                return
            if size > _MAX_IMAGE_BYTES:
                self._show_error(f"图片超过 8 MiB：{path.name}")
                return
            if QPixmap(str(path)).isNull():
                self._show_error(f"不是可读取的图片：{path.name}")
                return
        self._image_paths.extend(requested)
        self._show_error("")
        self._render_images()

    def _render_images(self) -> None:
        while self.image_row.count():
            child = self.image_row.takeAt(0)
            if child.widget() is not None:
                child.widget().hide()
                child.widget().deleteLater()
        for path in self._image_paths:
            box = QWidget()
            layout = QVBoxLayout(box)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(3)
            thumb = _ImageThumb(path, self._palette, box)
            thumb.setFixedSize(116, 82)
            thumb._render()
            layout.addWidget(thumb)
            remove = QPushButton("移除")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.clicked.connect(lambda _checked=False, p=path: self._remove_image(p))
            layout.addWidget(remove)
            self.image_row.addWidget(box)
        self.image_row.addStretch(1)
        self.add_image_button.setEnabled(len(self._image_paths) < _MAX_IMAGES)

    def _remove_image(self, path: Path) -> None:
        self._image_paths.remove(path)
        self._render_images()

    def _show_error(self, message: str) -> None:
        self.notice.setText(message)
        self.notice.setVisible(bool(message))

    def _submit(self) -> None:
        if self._busy:
            return
        body = self.body.toPlainText().strip()
        if not body:
            self._show_error("请先写下日志内容。")
            self.body.setFocus()
            return
        if len(body) > _MAX_BODY:
            self._show_error(f"正文最多 {_MAX_BODY} 字。")
            self.body.setFocus()
            return
        selected = tuple(
            int(self.position_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.position_list.count())
            if self.position_list.item(index).checkState() == Qt.CheckState.Checked
        )
        if len(selected) > _MAX_LINKED_POSITIONS:
            self._show_error(f"每篇最多关联 {_MAX_LINKED_POSITIONS} 笔持仓。")
            return
        self._busy = True
        self.submit_button.setEnabled(False)
        self.submit_button.setText("正在保存…")
        self._show_error("")
        self.submitted.emit(body, self.image_paths, selected)

    def publish_succeeded(self) -> None:
        self._busy = False
        self.accept()

    def publish_failed(self, message: str) -> None:
        self._busy = False
        self.submit_button.setEnabled(self._allowed)
        self.submit_button.setText("发布到本地")
        self._show_error(message or "保存失败，请重试。")

    def set_can_publish(self, allowed: bool) -> None:
        self._allowed = bool(allowed)
        self.submit_button.setEnabled(self._allowed and not self._busy)
        if not allowed:
            self._show_error("当前账户不可发布；请连接 USC 账户后重试。")


class MarketJournalPage(QWidget):
    """Read-only activity/feed view with explicit local publish request signals."""

    publish_requested = Signal(str, tuple, tuple)
    refresh_requested = Signal()
    page_requested = Signal(int)
    delete_requested = Signal(int)

    @property
    def current_page(self) -> int:
        return self._page

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("journalPage")
        self._palette = dict(palette)
        self._positions: tuple[PositionSnapshot, ...] = ()
        self._account_label = "账户未连接"
        self._composer: PublishDialog | None = None
        self._can_publish = False
        self._positions_current = False
        self._page = 1
        self._total_pages = 1
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(800)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 32)
        root.setSpacing(20)

        top = QHBoxLayout()
        top.setSpacing(12)
        headline = QVBoxLayout()
        headline.setSpacing(7)
        headline.addWidget(_plain("行情日志", "page-title"))
        headline.addWidget(_plain("记录市场判断和持仓过程，平仓后自动补上最终结果。", "subtitle", wrap=True))
        top.addLayout(headline, 1)
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        top.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        self.publish_button = QPushButton("写一条日志")
        self.publish_button.setObjectName("primary")
        self.publish_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.publish_button.clicked.connect(self.open_composer)
        top.addWidget(self.publish_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(top)

        self.account_note = _plain("账户未连接 · 仅保存在本地", "caption")
        root.addWidget(self.account_note)
        self.notice = _plain("", "notice", wrap=True)
        self.notice.hide()
        root.addWidget(self.notice)

        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(12)
        self.summary_grid.setVerticalSpacing(12)
        self.summary_values: list[QLabel] = []
        for index, (title, detail) in enumerate((
            ("累计日志", "当前账户的全部记录"),
            ("过去 30 天", "最近的市场观察"),
            ("活跃天数", "过去 365 天"),
        )):
            box = QFrame()
            box.setObjectName("journalMetric")
            stack = QVBoxLayout(box)
            stack.setContentsMargins(18, 16, 18, 16)
            stack.setSpacing(5)
            stack.addWidget(_plain(title, "metric-title"))
            value = _plain("—", "metric-value")
            stack.addWidget(value)
            stack.addWidget(_plain(detail, "caption"))
            self.summary_values.append(value)
            self.summary_grid.addWidget(box, 0, index)
        root.addLayout(self.summary_grid)

        activity_card = QFrame()
        activity_card.setObjectName("journalCard")
        activity_layout = QVBoxLayout(activity_card)
        activity_layout.setContentsMargins(20, 18, 20, 19)
        activity_layout.setSpacing(11)
        activity_header = QHBoxLayout()
        activity_header.addWidget(_plain("记录轨迹", "section-title"))
        activity_header.addStretch(1)
        self.activity_summary = _plain("过去 365 天 0 篇", "caption")
        activity_header.addWidget(self.activity_summary)
        activity_layout.addLayout(activity_header)
        activity_layout.addWidget(_plain("每个方块代表一天；悬停可查看当日记录数。", "caption"))
        self.heatmap = ActivityHeatmap(palette)
        activity_layout.addWidget(self.heatmap)
        root.addWidget(activity_card)

        feed_header = QHBoxLayout()
        feed_header.addWidget(_plain("最新记录", "section-title"))
        feed_header.addStretch(1)
        self.page_note = _plain("共 0 篇", "caption")
        feed_header.addWidget(self.page_note)
        root.addLayout(feed_header)
        self.feed = QVBoxLayout()
        self.feed.setSpacing(14)
        root.addLayout(self.feed)

        pagination = QHBoxLayout()
        pagination.addStretch(1)
        self.previous_button = QPushButton("上一页")
        self.previous_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.previous_button.clicked.connect(lambda: self.page_requested.emit(self._page - 1))
        pagination.addWidget(self.previous_button)
        self.current_page_label = _plain("1 / 1", "caption")
        pagination.addWidget(self.current_page_label)
        self.next_button = QPushButton("下一页")
        self.next_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_button.clicked.connect(lambda: self.page_requested.emit(self._page + 1))
        pagination.addWidget(self.next_button)
        root.addLayout(pagination)
        root.addStretch(1)
        self.set_can_publish(False)
        self.set_content(None, {}, (), "账户未连接")
        self.set_palette(palette)

    def set_content(self, page: JournalPage | None, activity: Mapping[date, int],
                    positions: tuple[PositionSnapshot, ...], account_label: str,
                    *, positions_current: bool = True) -> None:
        self._positions = positions
        self._positions_current = positions_current
        self._account_label = account_label
        self.account_note.setText(f"{account_label} · 数据仅保存在本地")
        posts = tuple(_field(page, "posts", ()) or ())
        total = max(0, int(_field(page, "total", 0) or 0))
        self._page = max(1, int(_field(page, "page", 1) or 1))
        self._total_pages = max(1, int(_field(page, "total_pages", 1) or 1))
        self.page_note.setText(f"共 {total} 篇 · 每页 10 篇")
        self.current_page_label.setText(f"{self._page} / {self._total_pages}")
        self.previous_button.setEnabled(self._page > 1)
        self.next_button.setEnabled(self._page < self._total_pages)
        today = date.today()
        recent = sum(max(0, int(count)) for day, count in activity.items()
                     if isinstance(day, date) and not isinstance(day, datetime)
                     and today - timedelta(days=29) <= day <= today)
        annual = {day: max(0, int(count)) for day, count in activity.items()
                  if isinstance(day, date) and not isinstance(day, datetime)
                  and today - timedelta(days=364) <= day <= today}
        self.summary_values[0].setText(str(total))
        self.summary_values[1].setText(str(recent))
        self.summary_values[2].setText(str(sum(1 for count in annual.values() if count)))
        self.activity_summary.setText(f"过去 365 天 {sum(annual.values())} 篇")
        self.heatmap.set_activity(annual)
        self._clear_feed()
        if not posts:
            empty = QFrame()
            empty.setObjectName("journalCard")
            layout = QVBoxLayout(empty)
            layout.setContentsMargins(24, 34, 24, 34)
            layout.setSpacing(8)
            title = "还没有行情日志" if total == 0 else "这一页没有记录"
            layout.addWidget(_plain(title, "empty-title"), 0, Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(_plain("写下第一条行情观察，或等待本地记录加载。", "caption"),
                             0, Qt.AlignmentFlag.AlignHCenter)
            self.feed.addWidget(empty)
        else:
            for post in posts:
                self.feed.addWidget(self._post_card(post))

    def _clear_feed(self) -> None:
        while self.feed.count():
            child = self.feed.takeAt(0)
            if child.widget() is not None:
                child.widget().hide()
                child.widget().deleteLater()

    def _post_card(self, post: Any) -> QWidget:
        card = QFrame()
        card.setObjectName("journalPost")
        stack = QVBoxLayout(card)
        stack.setContentsMargins(21, 19, 21, 20)
        stack.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(10)
        account_key = _field(post, "account_key", ()) or ()
        login = account_key[0] if len(account_key) > 0 else "—"
        header.addWidget(_plain(f"账户 {login}", "post-author"))
        header.addWidget(_plain(_datetime_text(_field(post, "created_at")), "caption"))
        header.addStretch(1)
        delete = QPushButton("删除")
        delete.setObjectName("journalDelete")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.clicked.connect(lambda _checked=False, post_id=int(_field(post, "id")):
                               self.delete_requested.emit(post_id))
        header.addWidget(delete)
        stack.addLayout(header)
        body = _plain(str(_field(post, "body", "")), "post-body", wrap=True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        stack.addWidget(body)
        image_paths = tuple(_field(post, "images", ()) or ())[:_MAX_IMAGES]
        if image_paths:
            row = QHBoxLayout()
            row.setSpacing(10)
            for path in image_paths:
                row.addWidget(_ImageThumb(Path(path), self._palette, card))
            row.addStretch(1)
            stack.addLayout(row)
        linked = tuple(_field(post, "positions", ()) or ())
        if linked:
            stack.addWidget(_plain(f"关联持仓 · {len(linked)}", "caption"))
            for position in linked:
                stack.addWidget(self._position_row(position))
        return card

    def _position_row(self, position: Any) -> QWidget:
        box = QFrame()
        box.setObjectName("journalPosition")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)
        ticket = _field(position, "ticket", _field(position, "position_id", "—"))
        symbol = _field(position, "symbol", "—")
        side = _field(position, "side", "—")
        volume = _decimal_text(_field(position, "volume"), 2)
        name = _plain(f"#{ticket} · {side} {symbol} · {volume} lot", "position-name")
        identity = _field(position, "account_key")
        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(3)
        details.addWidget(name)
        if isinstance(identity, tuple) and len(identity) == 2:
            details.addWidget(_plain(f"账户 {identity[0]} · {identity[1]}", "caption"))
        layout.addLayout(details, 1)
        closed_result = _field(position, "result_usc")
        status = str(_field(position, "status", "open")).lower()
        if closed_result is not None or status == "closed":
            result = closed_result
            prefix = "已平仓 · 最终 "
        elif status == "unverified":
            result = _field(position, "floating_usc")
            prefix = "持仓已变化，结果待核实 · 发布时浮动 "
        elif not self._positions_current:
            result = _field(position, "floating_usc")
            prefix = "状态待同步 · 发布时浮动 "
        else:
            result = _field(position, "floating_usc")
            prefix = "持仓中 · 发布时浮动 "
        amount = _plain(prefix + _pnl_text(result), _pnl_role(result))
        amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(amount)
        return box

    def set_notice(self, message: str) -> None:
        self.notice.setText(message)
        self.notice.setVisible(bool(message))

    def set_can_publish(self, allowed: bool) -> None:
        self._can_publish = bool(allowed)
        self.publish_button.setEnabled(self._can_publish)
        self.publish_button.setToolTip("" if allowed else "请连接 USC 账户后发布")
        if self._composer is not None:
            self._composer.set_can_publish(self._can_publish)

    def open_composer(self) -> None:
        if not self._can_publish:
            return
        if self._composer is not None:
            self._composer.raise_()
            self._composer.activateWindow()
            return
        dialog = PublishDialog(self._palette, self._positions, self._account_label, self)
        self._composer = dialog
        dialog.submitted.connect(self.publish_requested.emit)
        dialog.finished.connect(lambda _result: self._clear_composer(dialog))
        dialog.show()

    def _clear_composer(self, dialog: PublishDialog) -> None:
        if self._composer is dialog:
            self._composer = None
        dialog.deleteLater()

    def publish_succeeded(self) -> None:
        if self._composer is not None:
            self._composer.publish_succeeded()

    def publish_failed(self, message: str) -> None:
        if self._composer is not None:
            self._composer.publish_failed(message)
        else:
            self.set_notice(message)

    def dismiss_composer(self) -> None:
        """Close the draft when an account-level lock takes precedence."""
        if self._composer is not None:
            self._composer.reject()

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        p = self._palette
        self.heatmap.set_palette(palette)
        if self._composer is not None:
            self._composer.set_palette(palette)
        self.setStyleSheet(f"""
            QWidget#journalPage {{ background: {p['bg']}; color: {p['text']};
                font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZES['body']}px; }}
            QWidget#journalPage QLabel {{ background: transparent; }}
            QWidget#journalPage QLabel[role="page-title"] {{ color: {p['text']};
                font-size: {FONT_SIZES['page']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="subtitle"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['subtitle']}px; }}
            QWidget#journalPage QLabel[role="section-title"] {{ color: {p['text']};
                font-size: {FONT_SIZES['section']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="metric-title"],
            QWidget#journalPage QLabel[role="caption"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['caption']}px; }}
            QWidget#journalPage QLabel[role="metric-value"] {{ color: {p['text']};
                font-size: {FONT_SIZES['metric']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="post-author"],
            QWidget#journalPage QLabel[role="empty-title"] {{ color: {p['text']};
                font-size: 14px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="post-body"] {{ color: {p['text']};
                font-size: 14px; }}
            QWidget#journalPage QLabel[role="position-name"] {{ color: {p['text']};
                font-size: {FONT_SIZES['caption']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="positive"] {{ color: {p['positive']};
                font-size: {FONT_SIZES['caption']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="negative"] {{ color: {p['negative']};
                font-size: {FONT_SIZES['caption']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="muted"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['caption']}px; font-weight: 700; }}
            QWidget#journalPage QLabel[role="notice"] {{ color: {p['warning']};
                background: {p['surface_alt']}; border-radius: 8px;
                padding: 10px 13px; font-size: {FONT_SIZES['caption']}px; }}
            QFrame#journalCard, QFrame#journalPost, QFrame#journalMetric {{
                background: {p['surface']}; border: 1px solid {p['border']};
                border-radius: 12px; }}
            QFrame#journalPosition {{ background: {p['surface_alt']};
                border: 0; border-radius: 8px; }}
            QWidget#journalPage QLabel[role="image"],
            QWidget#journalPage QLabel[role="missing-image"] {{
                background: {p['surface_alt']}; color: {p['muted']};
                border: 1px solid {p['border']}; border-radius: 8px; }}
            QWidget#journalPage QPushButton#journalDelete {{ background: transparent;
                color: {p['muted']}; border: 1px solid transparent; padding: 5px 9px;
                min-height: 14px; font-size: {FONT_SIZES['caption']}px; }}
            QWidget#journalPage QPushButton#journalDelete:hover {{ color: {p['negative']};
                background: {p['hover']}; }}
        """)
