"""Read-only Qt trading overview for MT5 order analytics.

The page renders data supplied by its owner.  It never connects to MT5 or
changes orders; ``refresh_requested`` merely asks the owner to fetch data.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mt5_workbench.ui.widgets.charts import CashflowChart, ExecutionChart, StatusChart
from mt5_workbench.ui.theme import FONT_CSS, FONT_SIZES

if TYPE_CHECKING:
    from mt5_workbench.services.order_analytics import DealRecord, OrderAnalytics, OrderRecord


_EMPTY_DETAIL = "选择挂单、成交或历史订单，查看完整信息。"


def _number(value: Any, places: int = 4) -> str:
    if value is None:
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        return "—"
    if not isfinite(amount):
        return "—"
    return f"{amount:,.{places}f}".rstrip("0").rstrip(".")


def _money(value: Any, currency: str = "", *, signed: bool = False) -> str:
    if value is None:
        return "—"
    try:
        amount = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return "—"
    if not amount.is_finite():
        return "—"
    formatted = f"{amount:+,.2f}" if signed else f"{amount:,.2f}"
    return f"{formatted} {currency}".strip()


def _local_time(value: datetime | None, *, full_date: bool = False) -> str:
    if value is None:
        return "—"
    try:
        local = value.astimezone()
    except (ValueError, OverflowError, OSError):
        return "—"
    return local.strftime("%Y-%m-%d %H:%M:%S" if full_date else "%m-%d %H:%M:%S")


def _account_field(account: Any, name: str) -> Any:
    if account is None:
        return None
    if isinstance(account, dict):
        return account.get(name)
    return getattr(account, name, None)


def _label(text: str, role: str = "body", *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setProperty("role", role)
    label.setWordWrap(wrap)
    return label


def _card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("ordersCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 22, 24, 24)
    layout.setSpacing(16)
    return frame, layout


def _metric(title: str, note: str = "") -> tuple[QFrame, QLabel, QLabel]:
    frame = QFrame()
    frame.setObjectName("ordersMetric")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 15, 18, 16)
    layout.setSpacing(5)
    layout.addWidget(_label(title, "metric-title"))
    value = _label("—", "metric-value")
    value.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(value)
    note_label = _label(note, "caption", wrap=True)
    layout.addWidget(note_label)
    return frame, value, note_label


class OrdersPage(QWidget):
    """Trading overview with scope filters and three read-only record tables."""

    refresh_requested = Signal()

    def __init__(self, symbol_name: str, palette: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ordersPage")
        self.symbol_name = symbol_name
        self._palette = dict(palette)
        self._data: OrderAnalytics | None = None
        self._focus: tuple[str, str] | None = None
        self._records: dict[str, dict[str, Any]] = {
            "pending": {}, "deals": {}, "history": {},
        }
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumWidth(800)

        main = QVBoxLayout(self)
        main.setContentsMargins(24, 24, 24, 32)
        main.setSpacing(20)

        title_row = QHBoxLayout()
        title_row.setSpacing(16)
        title_row.addWidget(_label("交易概览", "page-title"))
        title_row.addStretch(1)
        title_row.addWidget(_label("● 只读分析", "readonly"))
        main.addLayout(title_row)
        main.addWidget(_label(
            "查看账户交易现金流、当前挂单与实际成交；数据由 MT5 读取。",
            "subtitle", wrap=True))

        filter_card, filter_layout = _card()
        controls = QBoxLayout(QBoxLayout.LeftToRight)
        controls.setSpacing(16)
        scope_controls = QHBoxLayout()
        scope_controls.setSpacing(14)
        scope_controls.addWidget(_label("分析范围", "control-label"))
        self.symbol_radio = QRadioButton(symbol_name)
        self.account_radio = QRadioButton("整个账户")
        self.symbol_radio.setChecked(True)
        scope_controls.addWidget(self.symbol_radio)
        scope_controls.addWidget(self.account_radio)
        scope_controls.addStretch(1)
        period_controls = QHBoxLayout()
        period_controls.setSpacing(12)
        period_controls.addWidget(_label("时间范围", "control-label"))
        self.period_combo = QComboBox()
        for days in (7, 30, 90):
            self.period_combo.addItem(f"近 {days} 日", days)
        self.period_combo.setCurrentIndex(1)
        self.period_combo.setMinimumWidth(108)
        period_controls.addWidget(self.period_combo)
        period_controls.addStretch(1)
        self.refresh_button = QPushButton("立即刷新")
        self.refresh_button.setObjectName("ordersRefresh")
        self.refresh_button.setCursor(Qt.PointingHandCursor)
        period_controls.addWidget(self.refresh_button)
        controls.addLayout(scope_controls, 1)
        controls.addLayout(period_controls)
        self.filter_controls = controls
        filter_layout.addLayout(controls)
        self.scope_note = _label("连接 MT5 后读取订单记录。", "caption", wrap=True)
        self.updated_label = _label("尚未更新", "caption")
        filter_layout.addWidget(self.scope_note)
        filter_layout.addWidget(self.updated_label)
        main.addWidget(filter_card)

        account_card, account_layout = _card()
        account_header = QHBoxLayout()
        account_header.addWidget(_label("账户资金表现", "section-title"))
        account_header.addStretch(1)
        self.curve_period = _label("等待账户成交历史", "caption")
        account_header.addWidget(self.curve_period)
        account_layout.addLayout(account_header)
        self.account_note = _label(
            "余额与净值来自当前账户；曲线从所选期间起点 0 开始累计。",
            "caption", wrap=True)
        account_layout.addWidget(self.account_note)
        account_grid = QGridLayout()
        account_grid.setHorizontalSpacing(12)
        account_grid.setVerticalSpacing(12)
        self.balance_card, self.balance_value, self.balance_note = _metric(
            "当前余额", "账户实时快照")
        self.equity_card, self.equity_value, self.equity_note = _metric(
            "当前净值", "含持仓浮盈亏")
        self.account_net_card, self.account_net_value, _ = _metric(
            "全账户期间交易现金流", "所选期间逐日累计")
        self.max_drawdown_card, self.max_drawdown_value, _ = _metric(
            "按日最大回撤", "交易现金流口径")
        self.current_drawdown_card, self.current_drawdown_value, _ = _metric(
            "当前距峰值", "交易现金流口径")
        self.account_cards = (
            self.balance_card, self.equity_card, self.account_net_card,
            self.max_drawdown_card, self.current_drawdown_card,
        )
        self.account_grid = account_grid
        account_layout.addLayout(account_grid)
        self.curve_chart = CashflowChart(self._palette, account_card)
        self.curve_chart.setMinimumHeight(280)
        account_layout.addWidget(self.curve_chart)
        self.daily_note = _label("盈利日与亏损日将在读取后显示。", "caption", wrap=True)
        account_layout.addWidget(self.daily_note)
        self.curve_note = _label(
            "曲线仅统计交易资金变动，不含出入金与持仓浮盈亏；并非历史账户权益曲线。",
            "caption", wrap=True)
        account_layout.addWidget(self.curve_note)
        main.addWidget(account_card)

        self.count_grid = QGridLayout()
        self.count_grid.setHorizontalSpacing(12)
        self.count_grid.setVerticalSpacing(12)
        self.count_cards: list[QFrame] = []
        self.count_values: dict[str, QLabel] = {}
        self.count_notes: dict[str, QLabel] = {}
        for key, title, note in (
            ("pending", "当前挂单", "有效挂单"),
            ("positions", "当前持仓", "活动仓位"),
            ("history", "期间历史订单", "请求与状态"),
            ("deals", "实际成交笔数", "BUY / SELL 成交"),
            ("cashflow", "范围内交易净现金流", "含成交相关费用"),
            ("protection", "挂单止损覆盖", "设置止损 / 全部挂单"),
        ):
            card, value, note_label = _metric(title, note)
            self.count_cards.append(card)
            self.count_values[key] = value
            self.count_notes[key] = note_label
        main.addLayout(self.count_grid)

        self.chart_row = QBoxLayout(QBoxLayout.LeftToRight)
        self.chart_row.setSpacing(16)
        flow_card, flow_layout = _card()
        self.flow_note = _label("等待成交历史", "caption", wrap=True)
        flow_layout.addWidget(_label("每日实际成交", "section-title"))
        flow_layout.addWidget(self.flow_note)
        self.execution_chart = ExecutionChart(self._palette, flow_card)
        self.execution_chart.setMinimumHeight(240)
        flow_layout.addWidget(self.execution_chart)
        state_card, state_layout = _card()
        self.state_note = _label("等待订单历史", "caption", wrap=True)
        state_layout.addWidget(_label("历史订单状态", "section-title"))
        state_layout.addWidget(self.state_note)
        self.status_chart = StatusChart(self._palette, state_card)
        self.status_chart.setMinimumHeight(240)
        state_layout.addWidget(self.status_chart)
        self.chart_row.addWidget(flow_card, 1)
        self.chart_row.addWidget(state_card, 1)
        main.addLayout(self.chart_row)

        self.volume_note = _label("成交量与挂单量将在读取后显示。", "caption", wrap=True)
        main.addWidget(self.volume_note)
        self.error_label = _label("", "error", wrap=True)
        self.error_label.hide()
        main.addWidget(self.error_label)

        self.pending_table, self.pending_note = self._add_table(
            main, "当前有效挂单", "pending",
            ("订单号", "品种", "类型", "初始手数", "剩余手数", "委托价", "止损", "止盈", "创建时间"),
            (108, 96, 120, 88, 88, 98, 98, 98, 140), 192)
        self.deals_table, self.deals_note = self._add_table(
            main, "最近实际成交", "deals",
            ("成交号", "关联订单", "品种", "方向", "开平", "手数", "成交价", "净现金流", "成交时间"),
            (108, 108, 96, 70, 80, 78, 98, 135, 140), 240)
        self.history_table, self.history_note = self._add_table(
            main, "期间历史订单", "history",
            ("订单号", "品种", "类型", "状态", "初始手数", "剩余手数", "委托价", "完成时间"),
            (108, 96, 120, 98, 88, 88, 98, 140), 240)

        detail_card, detail_layout = _card()
        detail_layout.addWidget(_label("选中记录详情", "section-title"))
        self.detail_label = _label(_EMPTY_DETAIL, "detail", wrap=True)
        self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_label.setMinimumHeight(58)
        detail_layout.addWidget(self.detail_label)
        main.addWidget(detail_card)

        self.symbol_radio.toggled.connect(self._scope_changed)
        self.account_radio.toggled.connect(self._scope_changed)
        self.period_combo.currentIndexChanged.connect(self._period_changed)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self._metric_columns = 0
        self._account_columns = 0
        self._reflow()
        self.set_palette(self._palette)
        self.clear()

    def _add_table(self, root: QVBoxLayout, title: str, kind: str,
                   headers: tuple[str, ...], widths: tuple[int, ...],
                   height: int) -> tuple[QTableWidget, QLabel]:
        card, layout = _card()
        header_row = QHBoxLayout()
        header_row.addWidget(_label(title, "section-title"))
        header_row.addStretch(1)
        note = _label("等待读取", "caption")
        header_row.addWidget(note)
        layout.addLayout(header_row)
        table = QTableWidget(0, len(headers), card)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setShowGrid(False)
        table.setFocusPolicy(Qt.StrongFocus)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        table.setMinimumHeight(height)
        table.setMaximumHeight(height)
        table.itemSelectionChanged.connect(lambda k=kind, t=table: self._selected(k, t))
        layout.addWidget(table)
        root.addWidget(card)
        return table, note

    def _scope_changed(self, checked: bool) -> None:
        if checked:
            self.refresh_requested.emit()

    def _period_changed(self, _index: int) -> None:
        self.refresh_requested.emit()

    def filters(self) -> tuple[str | None, int]:
        """Return symbol scope and requested calendar-day window."""
        days = self.period_combo.currentData()
        return (self.symbol_name if self.symbol_radio.isChecked() else None,
                int(days) if days in (7, 30, 90) else 30)

    def set_data(self, data: OrderAnalytics, account: Any = None) -> None:
        """Render a previously loaded, possibly partial, analytics snapshot."""
        self._data = data
        currency = data.currency or "USC"
        scope = data.scope_symbol or "整个账户"
        login = _account_field(account, "login")
        server = _account_field(account, "server")
        identity = " · ".join(str(part) for part in (login, server) if part not in (None, ""))
        prefix = f"账户 {identity} · " if identity else ""
        self.scope_note.setText(
            f"{prefix}分析范围 {scope} · 近 {data.lookback_days} 个本地日 · 账户币种 {currency}")
        self.updated_label.setText(
            f"读取于 {_local_time(data.as_of, full_date=True)}"
            + (" · 部分数据不可用" if data.errors else " · 数据已更新"))
        self.curve_period.setText(f"全账户 · 近 {data.lookback_days} 日 · {currency}")
        self.balance_value.setText(_money(_account_field(account, "balance"), currency))
        self.equity_value.setText(_money(_account_field(account, "equity"), currency))
        self.account_net_value.setText(
            _money(data.account_curve[-1].cumulative, currency, signed=True)
            if data.account_curve else "—")
        self.max_drawdown_value.setText(_money(data.account_max_drawdown, currency))
        self.current_drawdown_value.setText(_money(data.account_current_drawdown, currency))
        self.account_note.setText(
            "当前余额和净值来自账户快照；下方曲线始终汇总全账户，"
            "并从期间起点 0 开始累计。")
        if data.account_curve:
            amounts = [row.daily_cashflow for row in data.account_curve]
            active = [amount for amount in amounts if amount != 0]
            if active:
                self.daily_note.setText(
                    f"盈利日 {sum(amount > 0 for amount in amounts)} · "
                    f"亏损日 {sum(amount < 0 for amount in amounts)} · "
                    f"最佳交易日 {_money(max(active), currency, signed=True)} · "
                    f"最差交易日 {_money(min(active), currency, signed=True)}")
            else:
                self.daily_note.setText("所选期间无交易现金流变动。")
        else:
            self.daily_note.setText(
                "账户交易日表现不可用。" if data.history_deals_available
                else "历史成交读取失败，账户交易日表现不可用。")

        history_count = sum(row.count for row in data.status_counts)
        protected = (sum(row.sl is not None for row in data.pending_orders)
                     if data.pending_available else None)
        self.count_values["pending"].setText(
            f"{data.pending_count} 笔" if data.pending_count is not None else "—")
        self.count_values["positions"].setText(
            f"{data.position_count} 笔" if data.position_count is not None else "—")
        self.count_values["history"].setText(
            f"{history_count} 笔" if data.history_orders_available else "—")
        self.count_values["deals"].setText(
            f"{data.deal_count} 笔" if data.deal_count is not None else "—")
        self.count_values["cashflow"].setText(
            _money(data.net_trading_cashflow, currency, signed=True))
        self.count_values["protection"].setText(
            f"{protected} / {data.pending_count} 笔"
            if protected is not None and data.pending_count is not None else "—")
        self.count_notes["cashflow"].setText(f"{scope} · 含成交相关费用")
        self.flow_note.setText(
            "成交笔数 · 全账户" if data.scope_symbol is None else
            "BUY / SELL 成交手数 · lot" if data.history_deals_available else
            "历史成交读取失败")
        if not data.history_deals_available:
            self.flow_note.setText("历史成交读取失败")
        self.state_note.setText(
            f"{history_count} 笔历史订单" if data.history_orders_available
            else "历史订单读取失败")
        if data.scope_symbol is None:
            self.volume_note.setText(
                "全账户汇总不同品种的订单与成交笔数；不同品种的手数不能直接相加比较。"
                "交易净现金流包含成交相关费用，不等同于已平仓交易利润。")
        elif all(value is not None for value in
                 (data.pending_lots, data.buy_lots, data.sell_lots)):
            self.volume_note.setText(
                f"{scope} 当前挂单剩余 {_number(data.pending_lots)} lot · "
                f"期间 BUY 成交 {_number(data.buy_lots)} lot / "
                f"SELL 成交 {_number(data.sell_lots)} lot。"
                "成交方向不等同于持仓方向；交易净现金流包含成交相关费用。")
        else:
            self.volume_note.setText(
                "部分手数数据不可用；交易净现金流包含成交相关费用，"
                "不等同于已平仓交易利润。")

        self.error_label.setText(" · ".join(data.errors))
        self.error_label.setVisible(bool(data.errors))
        self.curve_chart.set_data(
            data.account_curve if data.history_deals_available else (), currency)
        self.execution_chart.set_data(
            data.daily_execution if data.history_deals_available else (),
            "deals" if data.scope_symbol is None else "lots")
        self.status_chart.set_data(
            data.status_counts if data.history_orders_available else ())

        self.pending_note.setText(
            f"{data.pending_count} 笔 · 按创建时间倒序"
            if data.pending_available else "读取失败")
        self.deals_note.setText(
            f"显示最近 {len(data.recent_deals)} / 共 {data.deal_count} 笔 · {currency}"
            if data.history_deals_available and data.deal_count is not None else
            "成交笔数不可用" if data.history_deals_available else "读取失败")
        self.history_note.setText(
            f"显示最近 {len(data.recent_orders)} / 共 {history_count} 笔"
            if data.history_orders_available else "读取失败")
        self._records = {
            "pending": {str(row.ticket): row for row in data.pending_orders},
            "deals": {str(row.ticket): row for row in data.recent_deals},
            "history": {str(row.ticket): row for row in data.recent_orders},
        }
        self._populate(self.pending_table, data.pending_orders, self._pending_cells)
        self._populate(self.deals_table, data.recent_deals,
                       lambda row: self._deal_cells(row, currency))
        self._populate(self.history_table, data.recent_orders, self._history_cells)
        self._restore_detail()

    @staticmethod
    def _pending_cells(row: OrderRecord) -> tuple[str, ...]:
        return (str(row.ticket), row.symbol, row.type_label,
                _number(row.volume_initial), _number(row.volume_current),
                _number(row.price_open, 8), _number(row.sl, 8),
                _number(row.tp, 8), _local_time(row.created_at))

    @staticmethod
    def _history_cells(row: OrderRecord) -> tuple[str, ...]:
        return (str(row.ticket), row.symbol, row.type_label, row.status_label,
                _number(row.volume_initial), _number(row.volume_current),
                _number(row.price_open, 8), _local_time(row.done_at))

    @staticmethod
    def _deal_cells(row: DealRecord, currency: str) -> tuple[str, ...]:
        return (str(row.ticket), str(row.order_ticket) if row.order_ticket else "—",
                row.symbol, row.side_label, row.entry_label,
                _number(row.volume), _number(row.price, 8),
                _money(row.cashflow, currency, signed=True),
                _local_time(row.executed_at))

    @staticmethod
    def _populate(table: QTableWidget, rows: tuple[Any, ...],
                  cells: Any) -> None:
        table.blockSignals(True)
        try:
            table.clearSelection()
            table.setRowCount(len(rows))
            for row_index, row in enumerate(rows):
                for column, value in enumerate(cells(row)):
                    item = QTableWidgetItem(value)
                    if column == 0 or (value and value[0].isdigit()
                                       and column not in (1, 2, 3, 4)):
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(row_index, column, item)
        finally:
            table.blockSignals(False)

    def _selected(self, kind: str, table: QTableWidget) -> None:
        index = table.currentRow()
        if index < 0 or not table.selectedItems():
            return
        item = table.item(index, 0)
        if item is None:
            return
        ticket = item.text()
        record = self._records[kind].get(ticket)
        if record is None:
            return
        self._focus = (kind, ticket)
        for other in (self.pending_table, self.deals_table, self.history_table):
            if other is not table:
                other.blockSignals(True)
                other.clearSelection()
                other.blockSignals(False)
        self._render_detail(kind, record)

    def _render_detail(self, kind: str, row: Any) -> None:
        currency = self._data.currency if self._data else ""
        if kind == "deals":
            self.detail_label.setText(
                f"成交 {row.ticket} · 订单 {row.order_ticket or '—'} · "
                f"{row.symbol} · {row.side_label} · {row.entry_label}\n"
                f"时间 {_local_time(row.executed_at, full_date=True)}   "
                f"手数 {_number(row.volume)} lot   "
                f"成交价 {_number(row.price, 8)}\n"
                f"利润 {_money(row.profit, currency, signed=True)}   "
                f"隔夜费 {_money(row.swap, currency, signed=True)}   "
                f"佣金 {_money(row.commission, currency, signed=True)}   "
                f"手续费 {_money(row.fee, currency, signed=True)}   "
                f"合计 {_money(row.cashflow, currency, signed=True)}")
        else:
            self.detail_label.setText(
                f"订单 {row.ticket} · {row.symbol} · {row.type_label} · {row.status_label}\n"
                f"委托 {_local_time(row.created_at, full_date=True)}   "
                f"完成 {_local_time(row.done_at, full_date=True)}   "
                f"初始 {_number(row.volume_initial)} lot   "
                f"剩余 {_number(row.volume_current)} lot\n"
                f"委托价 {_number(row.price_open, 8)}   "
                f"止损 {_number(row.sl, 8)}   止盈 {_number(row.tp, 8)}   "
                f"备注 {row.comment or '—'}")

    def _restore_detail(self) -> None:
        if self._focus is None:
            self.detail_label.setText(_EMPTY_DETAIL)
            return
        kind, ticket = self._focus
        record = self._records.get(kind, {}).get(ticket)
        if record is None:
            self._focus = None
            self.detail_label.setText(_EMPTY_DETAIL)
            return
        table = {"pending": self.pending_table, "deals": self.deals_table,
                 "history": self.history_table}[kind]
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None and item.text() == ticket:
                table.blockSignals(True)
                table.selectRow(row)
                table.blockSignals(False)
                break
        self._render_detail(kind, record)

    def clear(self, message: str = "连接 MT5 后读取订单记录。") -> None:
        """Discard account data, including selection and displayed money values."""
        self._data = None
        self._focus = None
        self._records = {"pending": {}, "deals": {}, "history": {}}
        self.scope_note.setText(message)
        self.updated_label.setText("尚未更新")
        self.curve_period.setText("等待账户成交历史")
        self.account_note.setText(
            "余额与净值来自当前账户；曲线从所选期间起点 0 开始累计。")
        for value in (self.balance_value, self.equity_value,
                      self.account_net_value, self.max_drawdown_value,
                      self.current_drawdown_value, *self.count_values.values()):
            value.setText("—")
        self.count_notes["cashflow"].setText("含成交相关费用")
        self.daily_note.setText("盈利日与亏损日将在读取后显示。")
        self.flow_note.setText("等待成交历史")
        self.state_note.setText("等待订单历史")
        self.volume_note.setText("成交量与挂单量将在读取后显示。")
        self.error_label.clear()
        self.error_label.hide()
        for table in (self.pending_table, self.deals_table, self.history_table):
            table.blockSignals(True)
            table.setRowCount(0)
            table.blockSignals(False)
        self.pending_note.setText("等待读取")
        self.deals_note.setText("等待读取")
        self.history_note.setText("等待读取")
        self.detail_label.setText(_EMPTY_DETAIL)
        self.curve_chart.set_data((), "USC")
        self.execution_chart.set_data((), "lots")
        self.status_chart.set_data(())

    def set_palette(self, palette: dict[str, str]) -> None:
        """Apply the current application theme to the page and its charts."""
        self._palette = dict(palette)
        p = self._palette
        self.setStyleSheet(f"""
            QWidget#ordersPage {{ background: {p['bg']}; color: {p['text']};
                font-family: {FONT_CSS}; font-size: {FONT_SIZES['body']}px; }}
            QFrame#ordersCard {{ background: {p['surface']};
                border: 1px solid {p['border']}; border-radius: 12px; }}
            QFrame#ordersMetric {{ background: {p['surface_alt']};
                border: 0; border-radius: 10px; }}
            QLabel {{ color: {p['text']}; background: transparent; border: none; }}
            QLabel[role="page-title"] {{ font-size: {FONT_SIZES['page']}px; font-weight: 700; }}
            QLabel[role="section-title"] {{ font-size: {FONT_SIZES['section']}px; font-weight: 700; }}
            QLabel[role="metric-title"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['caption']}px; font-weight: 700; }}
            QLabel[role="metric-value"] {{ font-size: {FONT_SIZES['metric']}px; font-weight: 700; }}
            QLabel[role="control-label"] {{ font-size: {FONT_SIZES['body']}px;
                font-weight: 700; }}
            QLabel[role="caption"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['caption']}px; }}
            QLabel[role="subtitle"] {{ color: {p['muted']};
                font-size: {FONT_SIZES['subtitle']}px; }}
            QLabel[role="readonly"] {{ color: {p['positive']};
                background: {p['selected']}; border-radius: 7px;
                font-size: {FONT_SIZES['caption']}px;
                font-weight: 700; padding: 6px 10px; }}
            QLabel[role="error"] {{ color: {p['warning']};
                font-size: {FONT_SIZES['caption']}px; }}
            QLabel[role="detail"] {{ color: {p['text']};
                font-size: {FONT_SIZES['body']}px; }}
            QRadioButton {{ color: {p['text']}; spacing: 8px;
                font-size: {FONT_SIZES['body']}px; }}
            QRadioButton::indicator {{ width: 16px; height: 16px; }}
            QComboBox {{ background: {p['surface_alt']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 8px;
                padding: 7px 11px; min-height: 24px;
                font-size: {FONT_SIZES['body']}px; }}
            QComboBox QAbstractItemView {{ background: {p['surface']};
                color: {p['text']}; selection-background-color: {p['selected']}; }}
            QPushButton#ordersRefresh {{ background: {p['accent']};
                color: {p['on_accent']}; border: none; border-radius: 8px;
                font-size: {FONT_SIZES['body']}px;
                font-weight: 700; padding: 9px 16px; }}
            QPushButton#ordersRefresh:hover {{ background: {p['chart_up']}; }}
            QTableWidget {{ background: {p['surface']}; color: {p['text']};
                alternate-background-color: {p['surface_alt']};
                gridline-color: {p['border']}; border: none;
                selection-background-color: {p['selected']};
                selection-color: {p['text']}; font-size: {FONT_SIZES['body']}px; }}
            QTableWidget::item {{ padding: 7px 10px; border: none; }}
            QHeaderView::section {{ background: {p['surface_alt']};
                color: {p['muted']}; border: none;
                border-bottom: 1px solid {p['border']};
                padding: 9px 10px; font-size: {FONT_SIZES['caption']}px;
                font-weight: 700; }}
        """)
        self.curve_chart.set_palette(p)
        self.execution_chart.set_palette(p)
        self.status_chart.set_palette(p)

    def resizeEvent(self, event: Any) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        width = self.width()
        account_columns = 5 if width >= 1420 else 3
        if account_columns != self._account_columns:
            for card in self.account_cards:
                self.account_grid.removeWidget(card)
            for index, card in enumerate(self.account_cards):
                self.account_grid.addWidget(
                    card, index // account_columns, index % account_columns)
            for column in range(5):
                self.account_grid.setColumnStretch(
                    column, 1 if column < account_columns else 0)
            self._account_columns = account_columns
        columns = 3 if width < 1420 else 6
        if columns != self._metric_columns:
            for card in self.count_cards:
                self.count_grid.removeWidget(card)
            for index, card in enumerate(self.count_cards):
                self.count_grid.addWidget(card, index // columns, index % columns)
            for column in range(6):
                self.count_grid.setColumnStretch(column, 1 if column < columns else 0)
            self._metric_columns = columns
        self.chart_row.setDirection(
            QBoxLayout.TopToBottom if width < 930 else QBoxLayout.LeftToRight)
        self.filter_controls.setDirection(
            QBoxLayout.TopToBottom if width < 1000 else QBoxLayout.LeftToRight)
