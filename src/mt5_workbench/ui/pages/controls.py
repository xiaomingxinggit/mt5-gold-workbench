"""Qt control panel view for confirmed position and pending-order actions.

This widget displays targets and emits preview requests. Account checks,
confirmation, and MT5 execution belong to the application controller.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QBrush, QColor, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mt5_workbench.ui.theme import FONT_FAMILY, FONT_SIZES
from mt5_workbench.ui.components import icon


_ORDER_NAMES = {
    0: "BUY",
    1: "SELL",
    2: "BUY LIMIT",
    3: "SELL LIMIT",
    4: "BUY STOP",
    5: "SELL STOP",
    6: "BUY STOP LIMIT",
    7: "SELL STOP LIMIT",
}


def _value(row: Any, field: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(field, default)
    return getattr(row, field, default)


def _number(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):,.5f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _optional_price(value: Any) -> str:
    return "—" if value is None or value == 0 else _price(value)


class ControlsPage(QWidget):
    """Read-only control targets with explicit requests to preview actions."""

    refresh_requested = Signal()
    preview_requested = Signal(str)  # "close" or "remove"

    def __init__(self, symbol_name: str, palette: Mapping[str, str], parent=None):
        super().__init__(parent)
        self.symbol_name = symbol_name
        self._palette = dict(palette)
        self._loaded = False
        self.setObjectName("controlsPage")

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        body_layout = QVBoxLayout(self)
        body_layout.setContentsMargins(24, 24, 24, 32)
        body_layout.setSpacing(20)

        heading = QHBoxLayout()
        heading.setSpacing(12)
        title_stack = QVBoxLayout()
        title_stack.setSpacing(6)
        title = self._label("控制面板", "controlsTitle")
        subtitle = self._label("先选择范围并核对目标，再确认执行。平仓和撤单会影响真实账户。", "controlsMuted")
        subtitle.setWordWrap(True)
        title_stack.addWidget(title)
        title_stack.addWidget(subtitle)
        heading.addLayout(title_stack, 1)
        self.refresh_button = QPushButton("刷新目标")
        self.refresh_button.setObjectName("controlsRefreshButton")
        self.refresh_button.setMinimumHeight(40)
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self._request_refresh)
        heading.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        body_layout.addLayout(heading)

        scope_card = self._card()
        scope_layout = QVBoxLayout(scope_card)
        scope_layout.setContentsMargins(22, 20, 22, 22)
        scope_layout.setSpacing(12)
        scope_layout.addWidget(self._label("操作范围", "controlsSectionTitle"))
        scope_row = QHBoxLayout()
        scope_row.setSpacing(24)
        self.symbol_radio = QRadioButton(f"仅当前品种 {symbol_name}")
        self.account_radio = QRadioButton("整个账户 · 所有品种")
        self.symbol_radio.setChecked(True)
        self.symbol_radio.toggled.connect(self._scope_changed)
        self.account_radio.toggled.connect(self._scope_changed)
        scope_row.addWidget(self.symbol_radio)
        scope_row.addWidget(self.account_radio)
        scope_row.addStretch(1)
        scope_layout.addLayout(scope_row)
        self.account_label = self._label("账户尚未连接", "controlsMuted")
        self.summary_label = self._label("等待读取持仓和挂单", "controlsSummary")
        scope_layout.addWidget(self.account_label)
        scope_layout.addWidget(self.summary_label)
        body_layout.addWidget(scope_card)

        self.actions_grid = QGridLayout()
        self.actions_grid.setContentsMargins(0, 0, 0, 0)
        self.actions_grid.setHorizontalSpacing(16)
        self.actions_grid.setVerticalSpacing(16)
        self.close_card = self._card()
        self.remove_card = self._card()
        self._build_close_card()
        self._build_remove_card()
        body_layout.addLayout(self.actions_grid)

        self.status_label = self._label("尚未执行控制操作。", "controlsStatus")
        self.status_label.setWordWrap(True)
        body_layout.addWidget(self.status_label)

        self.tables_grid = QGridLayout()
        self.tables_grid.setContentsMargins(0, 0, 0, 0)
        self.tables_grid.setHorizontalSpacing(16)
        self.tables_grid.setVerticalSpacing(16)
        self.position_card, self.position_table = self._table_card(
            "范围内持仓", ("Ticket", "品种", "方向", "手数", "开仓价", "浮盈亏")
        )
        self.order_card, self.order_table = self._table_card(
            "范围内挂单", ("Ticket", "品种", "类型", "手数", "挂单价", "止损")
        )
        body_layout.addLayout(self.tables_grid)
        body_layout.addStretch(1)
        self._action_columns = 0
        self._table_columns = 0
        self._reflow()
        self.set_palette(palette)
        self.clear()

    @staticmethod
    def _label(value: str, name: str) -> QLabel:
        label = QLabel(value)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    @staticmethod
    def _card() -> QFrame:
        card = QFrame()
        card.setObjectName("controlsCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return card

    def _build_close_card(self) -> None:
        layout = QVBoxLayout(self.close_card)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(12)
        layout.addWidget(self._label("全部平仓", "controlsSectionTitle"))
        explanation = self._label("按所选范围逐笔平仓；挂单不会自动撤销。", "controlsMuted")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        field_row = QHBoxLayout()
        field_row.setSpacing(10)
        field_row.addWidget(self._label("最大偏差 · 点", "controlsMuted"))
        self.deviation_input = QLineEdit("50")
        self.deviation_input.setObjectName("controlsDeviation")
        self.deviation_input.setValidator(QIntValidator(1, 1000, self.deviation_input))
        self.deviation_input.setMaximumWidth(95)
        self.deviation_input.setAccessibleName("最大偏差点数，1 到 1000")
        field_row.addWidget(self.deviation_input)
        field_row.addWidget(self._label("1–1000", "controlsMuted"))
        field_row.addStretch(1)
        layout.addLayout(field_row)
        layout.addStretch(1)
        self.close_button = QPushButton("预览全部平仓")
        self.close_button.setObjectName("controlsCloseButton")
        self.close_button.setMinimumHeight(42)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(lambda: self.preview_requested.emit("close"))
        layout.addWidget(self.close_button)

    def _build_remove_card(self) -> None:
        layout = QVBoxLayout(self.remove_card)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(12)
        layout.addWidget(self._label("删除所有挂单", "controlsSectionTitle"))
        explanation = self._label("按所选范围，逐笔撤销仍在等待的挂单。", "controlsMuted")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        warning = self._label("不会平仓；若挂单已成交，撤单无法撤销该持仓。", "controlsWarning")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addStretch(1)
        self.remove_button = QPushButton("预览删除挂单")
        self.remove_button.setObjectName("controlsRemoveButton")
        self.remove_button.setMinimumHeight(42)
        self.remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_button.clicked.connect(lambda: self.preview_requested.emit("remove"))
        layout.addWidget(self.remove_button)

    def _table_card(self, title: str, headings: tuple[str, ...]) -> tuple[QFrame, QTableWidget]:
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 22)
        layout.setSpacing(14)
        layout.addWidget(self._label(title, "controlsSectionTitle"))
        table = QTableWidget(0, len(headings))
        table.setObjectName("controlsTable")
        table.setHorizontalHeaderLabels(headings)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(65)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setMinimumHeight(240)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(table)
        return card, table

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        for grid, widgets, attr, threshold in (
            (self.actions_grid, (self.close_card, self.remove_card),
             "_action_columns", 860),
            (self.tables_grid, (self.position_card, self.order_card),
             "_table_columns", 1180),
        ):
            columns = 2 if self.width() >= threshold else 1
            if columns == getattr(self, attr):
                continue
            for widget in widgets:
                grid.removeWidget(widget)
            for index, widget in enumerate(widgets):
                row, column = (0, index) if columns == 2 else (index, 0)
                grid.addWidget(widget, row, column)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1 if columns == 2 else 0)
            setattr(self, attr, columns)

    def _scope_changed(self, checked: bool) -> None:
        if not checked:
            return
        self._invalidate("范围已更改，正在刷新目标…")
        self.refresh_requested.emit()

    def _request_refresh(self) -> None:
        self._invalidate("正在刷新目标…")
        self.refresh_requested.emit()

    def _invalidate(self, message: str) -> None:
        self._loaded = False
        self.position_table.setRowCount(0)
        self.order_table.setRowCount(0)
        self.summary_label.setText(message)
        self.close_button.setEnabled(False)
        self.remove_button.setEnabled(False)

    def scope(self) -> str:
        return "account" if self.account_radio.isChecked() else "symbol"

    def deviation(self) -> int:
        try:
            value = int(self.deviation_input.text().strip())
        except ValueError as exc:
            raise ValueError("最大偏差点数必须是 1～1000 的整数") from exc
        if not 1 <= value <= 1000:
            raise ValueError("最大偏差点数必须是 1～1000 的整数")
        return value

    def set_data(self, account: Any, positions: Iterable[Any], orders: Iterable[Any]) -> None:
        """Display already-fetched targets for the selected scope."""
        if account is None:
            self.clear()
            return
        currency = str(_value(account, "currency", "")).upper()
        if currency != "USC":
            self.clear("仅支持 USC 美分账户，请在 MT5 中切换账户")
            return
        position_rows = tuple(positions or ())
        order_rows = tuple(orders or ())
        scope_label = "当前品种" if self.scope() == "symbol" else "整个账户"
        login = _value(account, "login", "—")
        server = _value(account, "server", "—")
        was_clear_status = self.status_label.text() == self.account_label.text()
        self.account_label.setText(f"账户 {login} · {server} · {currency} · 范围：{scope_label}")
        if self.scope() == "symbol":
            volume = sum(float(_value(row, "volume", 0) or 0) for row in position_rows)
            self.summary_label.setText(
                f"持仓 {len(position_rows)} 笔 / {volume:g} 手    ·    挂单 {len(order_rows)} 笔"
            )
        else:
            self.summary_label.setText(f"持仓 {len(position_rows)} 笔    ·    挂单 {len(order_rows)} 笔")
        self._fill_positions(position_rows)
        self._fill_orders(order_rows)
        self._loaded = True
        self.close_button.setEnabled(bool(position_rows))
        self.remove_button.setEnabled(bool(order_rows))
        if was_clear_status:
            self.set_status("尚未执行控制操作。")

    def _fill_positions(self, rows: tuple[Any, ...]) -> None:
        self.position_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            direction = "BUY" if _value(row, "type") == 0 else "SELL" if _value(row, "type") == 1 else str(_value(row, "type", "—"))
            profit = _value(row, "profit")
            try:
                profit_text = f"{float(profit):+,.2f}"
            except (TypeError, ValueError, OverflowError):
                profit_text = "—"
            values = (
                _value(row, "ticket", "—"), _value(row, "symbol", "—"), direction,
                _number(_value(row, "volume")), _price(_value(row, "price_open")), profit_text,
            )
            self._set_table_row(self.position_table, index, values)
            if profit_text != "—":
                color = self._palette["negative"] if float(profit) < 0 else self._palette["positive"]
                self.position_table.item(index, 5).setForeground(QBrush(QColor(color)))

    def _fill_orders(self, rows: tuple[Any, ...]) -> None:
        self.order_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            kind = _value(row, "type")
            values = (
                _value(row, "ticket", "—"), _value(row, "symbol", "—"),
                _ORDER_NAMES.get(kind, str(kind) if kind is not None else "—"),
                _number(_value(row, "volume_initial")),
                _price(_value(row, "price_open")), _optional_price(_value(row, "sl")),
            )
            self._set_table_row(self.order_table, index, values)

    @staticmethod
    def _set_table_row(table: QTableWidget, row_index: int, values: tuple[Any, ...]) -> None:
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            alignment = Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignRight if column in (0, 3, 4, 5) else Qt.AlignmentFlag.AlignLeft
            )
            item.setTextAlignment(alignment)
            table.setItem(row_index, column, item)

    def clear(self, message: str = "账户尚未连接") -> None:
        self._invalidate("等待读取持仓和挂单")
        self.account_label.setText(message)
        self.set_status(message)

    def set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._palette = dict(palette)
        p = self._palette
        self.setStyleSheet(f"""
            QWidget#controlsPage {{
                background: {p['bg']}; color: {p['text']};
                font-family: '{FONT_FAMILY}'; font-size: {FONT_SIZES['body']}px;
            }}
            QFrame#controlsCard {{ background: {p['surface']};
                border: 1px solid {p['border']}; border-radius: 12px; }}
            QLabel#controlsTitle {{ color: {p['text']}; font-size: {FONT_SIZES['page']}px; font-weight: 700; }}
            QLabel#controlsSectionTitle {{ color: {p['text']}; font-size: {FONT_SIZES['section']}px; font-weight: 700; }}
            QLabel#controlsMuted {{ color: {p['muted']}; font-size: {FONT_SIZES['caption']}px; }}
            QLabel#controlsSummary {{ color: {p['accent']}; font-size: {FONT_SIZES['subtitle']}px; font-weight: 700; }}
            QLabel#controlsStatus {{ color: {p['muted']}; background: {p['surface_alt']};
                border-radius: 8px; font-size: {FONT_SIZES['caption']}px; padding: 11px 14px; }}
            QLabel#controlsWarning {{ color: {p['warning']}; font-size: {FONT_SIZES['caption']}px; }}
            QRadioButton {{ color: {p['text']}; spacing: 8px; font-size: {FONT_SIZES['body']}px; }}
            QRadioButton::indicator {{ width: 16px; height: 16px; }}
            QLineEdit#controlsDeviation {{ background: {p['surface_alt']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 8px;
                padding: 8px 11px; font-size: {FONT_SIZES['body']}px; }}
            QLineEdit#controlsDeviation:focus {{ border-color: {p['accent']}; }}
            QPushButton {{ border-radius: 8px; padding: 9px 15px;
                font-size: {FONT_SIZES['body']}px; font-weight: 700; }}
            QPushButton#controlsRefreshButton {{ background: {p['surface_alt']}; color: {p['text']};
                border: 1px solid {p['border']}; }}
            QPushButton#controlsRefreshButton:hover {{ background: {p['hover']}; }}
            QPushButton#controlsCloseButton {{ background: {p['surface_alt']};
                color: {p['negative']}; border: 1px solid {p['negative']}; }}
            QPushButton#controlsRemoveButton {{ background: {p['surface_alt']};
                color: {p['warning']}; border: 1px solid {p['warning']}; }}
            QPushButton#controlsCloseButton:hover, QPushButton#controlsRemoveButton:hover {{
                background: {p['hover']}; }}
            QPushButton#controlsCloseButton:disabled, QPushButton#controlsRemoveButton:disabled {{
                background: {p['surface_alt']}; color: {p['disabled']};
                border: 1px solid {p['border']}; }}
            QTableWidget#controlsTable {{ background: {p['surface']}; alternate-background-color: {p['surface_alt']};
                color: {p['text']}; border: 0; outline: 0; font-size: {FONT_SIZES['body']}px; }}
            QTableWidget#controlsTable QHeaderView::section {{ background: {p['surface_alt']};
                color: {p['muted']}; border: 0; border-bottom: 1px solid {p['border']};
                padding: 9px 10px; font-size: {FONT_SIZES['caption']}px; font-weight: 700; }}
            QTableWidget#controlsTable::item {{ padding: 7px 10px; border: none; }}
        """)
        theme = "dark" if p["bg"].lower() == "#0b1220" else "light"
        for button, icon_name in (
            (self.refresh_button, "refresh"),
            (self.close_button, "close"),
            (self.remove_button, "remove"),
        ):
            button.setIcon(icon(icon_name, theme))
            button.setIconSize(QSize(18, 18))
        # Existing rows retain their explicit profit color across theme changes.
        for row in range(self.position_table.rowCount()):
            item = self.position_table.item(row, 5)
            if item is not None:
                try:
                    color = p["negative"] if float(item.text().replace(",", "")) < 0 else p["positive"]
                    item.setForeground(QBrush(QColor(color)))
                except ValueError:
                    pass
