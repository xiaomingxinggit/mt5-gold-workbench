"""Read-only experimental M1 EMA convergence monitor.

The page receives calculated snapshots from its owner. It does not call MT5 or
submit orders. A candidate means the four EMA values are close by the chosen
price tolerance; it is not a prediction of a reversal.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mt5_workbench.ui.theme import FONT_SIZES


_PERIODS = (7, 14, 30, 60)
_MAX_EVENTS = 12


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _label(text: str, *, role: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        label.setProperty("emaRole", role)
    label.setWordWrap(wrap)
    return label


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("emaCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 19, 22, 20)
    layout.setSpacing(12)
    return frame, layout


def _decimal_text(value: Any, places: int = 3) -> str:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "—"
    if not amount.is_finite():
        return "—"
    return f"{amount:,.{places}f}"


def _time_text(value: Any) -> str:
    if not isinstance(value, datetime):
        return "—"
    try:
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "—"


def _age_text(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    if not isfinite(seconds) or seconds < 0:
        return "—"
    return f"{seconds:.1f} 秒"


class EmaMonitorPage(QWidget):
    """A presentation-only M1 EMA 7/14/30/60 convergence screen."""

    refresh_requested = Signal()
    tolerance_changed = Signal(float)

    def __init__(self, symbol_name: str, palette: Mapping[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("emaMonitorPage")
        self.symbol_name = symbol_name
        self._palette = dict(palette)
        self._last_aligned: bool | None = None
        self._event_bars: set[datetime] = set()
        self._events: list[tuple[str, str, str]] = []
        self.setMinimumWidth(800)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        main = QVBoxLayout(self)
        main.setContentsMargins(24, 24, 24, 32)
        main.setSpacing(18)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        heading.addWidget(_label("EMA 行情监听", role="page-title"))
        heading.addStretch(1)
        self.readonly_badge = _label("实验功能 · 只读", role="badge")
        heading.addWidget(self.readonly_badge)
        self.refresh_button = QPushButton("立即刷新")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_requested)
        heading.addWidget(self.refresh_button)
        main.addLayout(heading)
        main.addWidget(_label(
            f"监听 {symbol_name} 的 1 分钟 EMA 7 / 14 / 30 / 60。聚拢仅供观察，不代表价格一定反转。",
            role="subtitle", wrap=True,
        ))

        hero, hero_layout = _card()
        hero.setObjectName("emaHero")
        hero_grid = QGridLayout()
        hero_grid.setHorizontalSpacing(24)
        hero_grid.setVerticalSpacing(10)
        hero_grid.addWidget(_label("当前状态", role="eyebrow"), 0, 0)
        self.state_value = _label("等待行情", role="state")
        hero_grid.addWidget(self.state_value, 1, 0)
        self.state_note = _label("连接 MT5 后开始监听。", role="body", wrap=True)
        hero_grid.addWidget(self.state_note, 2, 0)
        quote_grid = QGridLayout()
        quote_grid.setHorizontalSpacing(28)
        quote_grid.setVerticalSpacing(4)
        quote_grid.addWidget(_label("BID", role="eyebrow"), 0, 0)
        quote_grid.addWidget(_label("ASK", role="eyebrow"), 0, 1)
        self.bid_value = _label("—", role="quote")
        self.ask_value = _label("—", role="quote")
        quote_grid.addWidget(self.bid_value, 1, 0)
        quote_grid.addWidget(self.ask_value, 1, 1)
        quote_grid.addWidget(_label("报价年龄", role="eyebrow"), 2, 0)
        self.age_value = _label("—", role="body")
        quote_grid.addWidget(self.age_value, 2, 1)
        quote_grid.setColumnStretch(0, 1)
        quote_grid.setColumnStretch(1, 1)
        hero_grid.addLayout(quote_grid, 0, 1, 3, 1)
        hero_grid.setColumnStretch(0, 3)
        hero_grid.setColumnStretch(1, 2)
        hero_layout.addLayout(hero_grid)
        self.hero = hero
        self.hero_grid = hero_grid
        main.addWidget(hero)

        self.metrics_grid = QGridLayout()
        self.metrics_grid.setHorizontalSpacing(12)
        self.metrics_grid.setVerticalSpacing(12)
        self.ema_cards: dict[int, QFrame] = {}
        self.ema_values: dict[int, QLabel] = {}
        self.ema_notes: dict[int, QLabel] = {}
        for period in _PERIODS:
            metric = QFrame()
            metric.setObjectName("emaMetric")
            metric_layout = QVBoxLayout(metric)
            metric_layout.setContentsMargins(18, 16, 18, 17)
            metric_layout.setSpacing(6)
            metric_layout.addWidget(_label(f"EMA {period}", role="eyebrow"))
            value = _label("—", role="metric")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            metric_layout.addWidget(value)
            note = _label("M1 · 等待 K 线", role="caption")
            metric_layout.addWidget(note)
            self.ema_cards[period] = metric
            self.ema_values[period] = value
            self.ema_notes[period] = note
        main.addLayout(self.metrics_grid)

        settings, settings_layout = _card()
        settings_title = QHBoxLayout()
        settings_title.addWidget(_label("聚拢判定", role="section-title"))
        settings_title.addStretch(1)
        self.spread_value = _label("EMA 最大差距 —", role="measure")
        settings_title.addWidget(self.spread_value)
        settings_layout.addLayout(settings_title)
        self.rule_note = _label(
            "四条 EMA 的最高值与最低值之差，不超过设定阈值时标记为聚拢候选。形成中的 K 线会变化，候选状态也可能撤回。",
            role="caption", wrap=True,
        )
        settings_layout.addWidget(self.rule_note)
        setting_row = QHBoxLayout()
        setting_row.setSpacing(12)
        setting_row.addWidget(_label("最大允许差距", role="body"))
        self.tolerance_input = QDoubleSpinBox()
        self.tolerance_input.setObjectName("emaTolerance")
        self.tolerance_input.setRange(0.01, 100000.0)
        self.tolerance_input.setDecimals(2)
        self.tolerance_input.setSingleStep(0.5)
        self.tolerance_input.setSuffix(" point")
        self.tolerance_input.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.tolerance_input.setValue(5.0)
        self.tolerance_input.setMinimumWidth(150)
        self.tolerance_input.setAccessibleName("EMA 聚拢最大允许差距，单位 MT5 point")
        self.tolerance_input.valueChanged.connect(self.tolerance_changed)
        setting_row.addWidget(self.tolerance_input)
        setting_row.addWidget(_label("按当前品种的 MT5 point 计", role="caption", wrap=True), 1)
        settings_layout.addLayout(setting_row)
        metadata = QHBoxLayout()
        metadata.setSpacing(28)
        self.bar_time_label = _label("M1 K 线：—", role="caption")
        self.observed_at_label = _label("采集时间：—", role="caption")
        metadata.addWidget(self.bar_time_label)
        metadata.addWidget(self.observed_at_label)
        metadata.addStretch(1)
        settings_layout.addLayout(metadata)
        main.addWidget(settings)

        history, history_layout = _card()
        history_title = QHBoxLayout()
        history_title.addWidget(_label("本次运行发现的聚拢候选", role="section-title"))
        history_title.addStretch(1)
        history_title.addWidget(_label("每根 M1 K 线最多记录一次", role="caption"))
        history_layout.addLayout(history_title)
        self.history_note = _label("尚未发现聚拢候选。", role="caption")
        history_layout.addWidget(self.history_note)
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(("发现时间", "M1 K 线", "EMA 最大差距"))
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history_table.verticalHeader().hide()
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setShowGrid(False)
        self.history_table.setMinimumHeight(134)
        self.history_table.setMaximumHeight(238)
        self.history_table.verticalHeader().setDefaultSectionSize(34)
        history_layout.addWidget(self.history_table)
        main.addWidget(history)
        main.addStretch(1)

        self.set_palette(palette)
        self._render_events()
        self._reflow()

    @property
    def tolerance_points(self) -> float:
        return self.tolerance_input.value()

    def set_snapshot(self, snapshot: Any) -> None:
        """Display one owner-supplied snapshot and record new candidate bars."""
        if snapshot is None:
            self.clear("等待行情数据。")
            return
        ema_values = _field(snapshot, "ema_values", {}) or {}
        bar_kind = ("含当前形成中的 K 线" if _field(snapshot, "includes_forming_bar", True)
                    else "仅使用已收盘 K 线")
        self.rule_note.setText(
            "四条 EMA 的最高值与最低值之差，不超过设定阈值时标记为聚拢候选。"
            + ("形成中的 K 线会变化，候选状态也可能撤回。" if _field(snapshot, "includes_forming_bar", True)
               else "本次只比较已收盘的 K 线。")
        )
        for period in _PERIODS:
            value = ema_values.get(period, ema_values.get(str(period))) if isinstance(ema_values, Mapping) else None
            self.ema_values[period].setText(_decimal_text(value, 5))
            self.ema_notes[period].setText(f"M1 · {bar_kind}")
        self.bid_value.setText(_decimal_text(_field(snapshot, "bid"), 3))
        self.ask_value.setText(_decimal_text(_field(snapshot, "ask"), 3))
        self.age_value.setText(_age_text(_field(snapshot, "quote_age_seconds")))
        bar_time = _field(snapshot, "bar_time")
        observed_at = _field(snapshot, "observed_at")
        self.bar_time_label.setText(f"M1 K 线：{_time_text(bar_time)}")
        self.observed_at_label.setText(f"采集时间：{_time_text(observed_at)}")
        spread = _decimal_text(_field(snapshot, "ema_spread_points"), 4)
        calculated_tolerance = _decimal_text(_field(snapshot, "tolerance_points"), 2)
        self.spread_value.setText(
            f"EMA 最大差距 {spread} / 判定阈值 {calculated_tolerance} point")
        status = str(_field(snapshot, "status", "") or "").lower()
        reason = str(_field(snapshot, "reason", "") or "")
        if status in {"error", "stale", "unavailable", "waiting", "disconnected"}:
            self._set_state("数据暂不可用", reason or "等待新行情。", "warning")
            self._last_aligned = None
            return
        aligned = _field(snapshot, "aligned")
        if aligned is True:
            self._set_state("EMA 聚拢候选", reason or "四条 EMA 已进入设定阈值范围。", "positive")
            if self._last_aligned is not True and isinstance(bar_time, datetime) and bar_time not in self._event_bars:
                self._event_bars.add(bar_time)
                self._events.insert(0, (_time_text(observed_at), _time_text(bar_time), f"{spread} point"))
                del self._events[_MAX_EVENTS:]
                self._render_events()
            self._last_aligned = True
        elif aligned is False:
            self._set_state("等待 EMA 聚拢", reason or "四条 EMA 当前仍有间距。", "neutral")
            self._last_aligned = False
        else:
            self._set_state("等待行情", reason or "等待足够的 1 分钟 K 线。", "neutral")

    def clear(self, message: str = "等待 MT5 连接。") -> None:
        """Remove account-dependent values when data is no longer current."""
        self._set_state("数据暂不可用", message, "warning")
        self.bid_value.setText("—")
        self.ask_value.setText("—")
        self.age_value.setText("—")
        self.spread_value.setText("EMA 最大差距 —")
        self.bar_time_label.setText("M1 K 线：—")
        self.observed_at_label.setText("采集时间：—")
        for value in self.ema_values.values():
            value.setText("—")
        for note in self.ema_notes.values():
            note.setText("M1 · 等待 K 线")
        self.rule_note.setText("四条 EMA 的最高值与最低值之差，不超过设定阈值时标记为聚拢候选。")
        self._last_aligned = None
        self._event_bars.clear()
        self._events.clear()
        self._render_events()

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        p = self._palette
        self.setStyleSheet(f"""
            QFrame#emaHero, QFrame#emaCard {{
                background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px;
            }}
            QFrame#emaMetric {{
                background: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 10px;
            }}
            QLabel[emaRole="page-title"] {{ font-size: {FONT_SIZES['page']}px; font-weight: 700; }}
            QLabel[emaRole="section-title"] {{ font-size: {FONT_SIZES['section']}px; font-weight: 700; }}
            QLabel[emaRole="subtitle"] {{ font-size: {FONT_SIZES['subtitle']}px; color: {p['muted']}; }}
            QLabel[emaRole="eyebrow"], QLabel[emaRole="caption"] {{
                font-size: {FONT_SIZES['caption']}px; color: {p['muted']};
            }}
            QLabel[emaRole="body"], QLabel[emaRole="measure"] {{ font-size: {FONT_SIZES['body']}px; }}
            QLabel[emaRole="measure"] {{ font-weight: 700; color: {p['accent_alt']}; }}
            QLabel[emaRole="state"] {{ font-size: {FONT_SIZES['metric']}px; font-weight: 700; }}
            QLabel[emaRole="metric"], QLabel[emaRole="quote"] {{
                font-size: {FONT_SIZES['metric']}px; font-weight: 700;
            }}
            QLabel[emaRole="badge"] {{
                background: {p['surface_alt']}; color: {p['muted']};
                border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 10px;
                font-size: {FONT_SIZES['caption']}px;
            }}
            QDoubleSpinBox#emaTolerance {{
                background: {p['surface_alt']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 8px;
                padding: 8px 10px; min-height: 18px;
            }}
            QDoubleSpinBox#emaTolerance:focus {{ border-color: {p['accent']}; }}
        """)
        self._style_state(getattr(self, "_state_tone", "neutral"))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        columns = 2 if self.width() < 1200 else 4
        for period in _PERIODS:
            self.metrics_grid.removeWidget(self.ema_cards[period])
        for index, period in enumerate(_PERIODS):
            self.metrics_grid.addWidget(self.ema_cards[period], index // columns, index % columns)
        for column in range(4):
            self.metrics_grid.setColumnStretch(column, 1 if column < columns else 0)

    def _set_state(self, title: str, note: str, tone: str) -> None:
        self.state_value.setText(title)
        self.state_note.setText(note)
        self._state_tone = tone
        self._style_state(tone)

    def _style_state(self, tone: str) -> None:
        color = self._palette["positive" if tone == "positive" else
                              "warning" if tone == "warning" else "text"]
        self.state_value.setStyleSheet(f"color: {color};")

    def _render_events(self) -> None:
        self.history_note.setVisible(not self._events)
        self.history_table.setVisible(bool(self._events))
        self.history_table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            for column, value in enumerate(event):
                item = QTableWidgetItem(value)
                if column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.history_table.setItem(row, column, item)
