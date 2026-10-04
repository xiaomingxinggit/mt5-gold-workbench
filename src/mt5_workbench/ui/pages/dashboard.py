"""Live quote, account, chart and open-book dashboard page."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import MetaTrader5 as mt5
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QTableWidget, QVBoxLayout,
    QWidget,
)

from mt5_workbench.services.dashboard_data import DashboardData
from mt5_workbench.ui.components import card, chart_card, fill_table, label, make_table, metric_card
from mt5_workbench.ui.widgets.charts import CandleChart, DailyPnlChart

ORDER_NAMES = {
    mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
    mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
    mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
    mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
}


class DashboardPage(QWidget):
    def __init__(self, symbol_name: str, palette: dict[str, str], theme: str):
        super().__init__()
        self.symbol_name = symbol_name
        self.palette = palette
        self.theme = theme
        self._compact_metrics = False
        self._compact_charts = False
        self._compact_books = False
        self._market_color_key = "muted"
        self._change_color_key = "muted"
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 32)
        outer.setSpacing(18)
        heading = QHBoxLayout()
        heading.setSpacing(16)
        identity = QVBoxLayout()
        identity.setSpacing(5)
        identity.addWidget(label("总览看板", kind="pageTitle"))
        self.account_text = label("账户尚未连接", kind="muted", wrap=True)
        identity.addWidget(self.account_text)
        heading.addLayout(identity, 1)
        heading.addStretch()
        self.market_state = label("等待 MT5 行情", kind="positive")
        heading.addWidget(self.market_state, alignment=Qt.AlignmentFlag.AlignTop)
        outer.addLayout(heading)

        quote = card()
        quote_layout = QHBoxLayout(quote)
        quote_layout.setContentsMargins(22, 19, 22, 20)
        quote_layout.setSpacing(18)
        symbol_box = QVBoxLayout()
        symbol_box.setSpacing(5)
        symbol_box.addWidget(label("市场快照", kind="muted"))
        symbol_box.addWidget(label(symbol_name, size=18, bold=True))
        self.day_change = label("—", kind="positive")
        self.quote_time = label("等待报价", kind="muted")
        symbol_box.addWidget(self.day_change)
        symbol_box.addWidget(self.quote_time)
        quote_layout.addLayout(symbol_box, 4)
        self.bid = self._quote_value(quote_layout, "BID · 卖出")
        self.ask = self._quote_value(quote_layout, "ASK · 买入")
        self.spread = self._quote_value(quote_layout, "点差")
        outer.addWidget(quote)

        outer.addWidget(label("账户概况", kind="sectionTitle"))
        metrics = QVBoxLayout()
        metrics.setSpacing(12)
        self.metric_row = QHBoxLayout()
        self.metric_row.setSpacing(12)
        self.metric_second_row = QHBoxLayout()
        self.metric_second_row.setSpacing(12)
        self.metric_values: dict[str, QLabel] = {}
        self.metric_boxes: list[QFrame] = []
        for key, caption in (
                ("equity", "账户净值"), ("balance", "账户余额"),
                ("floating", "浮动盈亏"), ("margin", "可用保证金"),
                ("margin_level", "保证金水平")):
            box, value = metric_card(caption)
            self.metric_boxes.append(box)
            self.metric_values[key] = value
            self.metric_row.addWidget(box, 1)
        metrics.addLayout(self.metric_row)
        metrics.addLayout(self.metric_second_row)
        outer.addLayout(metrics)

        outer.addWidget(label("行情与收益", kind="sectionTitle"))
        charts = QGridLayout()
        charts.setHorizontalSpacing(12)
        charts.setVerticalSpacing(12)
        self.charts_layout = charts
        self.candles = CandleChart(palette)
        self.pnl = DailyPnlChart(palette)
        self.candle_box, _ = chart_card("黄金价格 · 5 分钟 K 线", self.candles,
                                   theme, "candles", "最近 72 根 · MT5")
        self.pnl_box, self.pnl_note = chart_card("近 30 日已实现净损益", self.pnl,
                                             theme, "bar-chart", "等待成交历史")
        charts.addWidget(self.candle_box, 0, 0)
        charts.addWidget(self.pnl_box, 0, 1)
        charts.setColumnStretch(0, 3)
        charts.setColumnStretch(1, 2)
        outer.addLayout(charts)
        self.dashboard_note = label("连接 MT5 后读取图表与账户历史", kind="muted", wrap=True)
        outer.addWidget(self.dashboard_note)

        outer.addWidget(label("实时敞口", kind="sectionTitle"))
        books = QGridLayout()
        books.setHorizontalSpacing(12)
        books.setVerticalSpacing(12)
        self.books_layout = books
        self.position_table = make_table(("Ticket", "方向", "手数", "开仓价", "现价",
                                          "止损", "止盈", "浮盈亏"), 215)
        self.order_table = make_table(("Ticket", "类型", "手数", "挂单价", "止损", "止盈"), 215)
        self.position_box, self.position_note = self._table_card("当前持仓 · XAUUSDc",
                                                                   self.position_table)
        self.order_box, self.order_note = self._table_card("当前挂单 · XAUUSDc",
                                                              self.order_table)
        books.addWidget(self.position_box, 0, 0)
        books.addWidget(self.order_box, 0, 1)
        books.setColumnStretch(0, 3)
        books.setColumnStretch(1, 2)
        outer.addLayout(books)
        outer.addStretch()
        self._reflow()

    def _quote_value(self, row: QHBoxLayout, caption: str) -> QLabel:
        group = QVBoxLayout()
        group.setSpacing(7)
        group.addWidget(label(caption, kind="muted"))
        value = label("—", kind="metricValue")
        group.addWidget(value)
        row.addLayout(group, 2)
        return value

    def _table_card(self, title: str, table: QTableWidget) -> tuple[QFrame, QLabel]:
        box = card()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 17, 18, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.addWidget(label(title, kind="sectionTitle"))
        header.addStretch()
        count = label("0 笔", kind="muted")
        header.addWidget(count)
        layout.addLayout(header)
        layout.addWidget(table)
        return box, count

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self) -> None:
        """Give tables their full column width at the minimum window size."""
        compact_metrics = self.width() < 1140
        compact_charts = self.width() < 930
        compact_books = self.width() < 1180
        if compact_metrics != self._compact_metrics:
            self._compact_metrics = compact_metrics
            for box in self.metric_boxes[3:]:
                self.metric_row.removeWidget(box)
                self.metric_second_row.removeWidget(box)
                (self.metric_second_row if compact_metrics else self.metric_row).addWidget(box, 1)
        if compact_charts != self._compact_charts:
            self._compact_charts = compact_charts
            self.charts_layout.removeWidget(self.pnl_box)
            self.charts_layout.addWidget(self.pnl_box, 1 if compact_charts else 0,
                                         0 if compact_charts else 1)
            self.charts_layout.setColumnStretch(0, 1 if compact_charts else 3)
            self.charts_layout.setColumnStretch(1, 0 if compact_charts else 2)
        if compact_books != self._compact_books:
            self._compact_books = compact_books
            self.books_layout.removeWidget(self.order_box)
            self.books_layout.addWidget(self.order_box, 1 if compact_books else 0,
                                        0 if compact_books else 1)
            self.books_layout.setColumnStretch(0, 1 if compact_books else 3)
            self.books_layout.setColumnStretch(1, 0 if compact_books else 2)

    def set_account(self, account) -> None:
        self.account_text.setText(
            f"账户 {account.login} · {account.name} · {account.server} · {account.currency}")
        for key, value in (("equity", account.equity), ("balance", account.balance),
                           ("floating", account.profit),
                           ("margin", account.margin_free)):
            sign = "+" if key == "floating" else ""
            self.metric_values[key].setText(f"{value:{sign},.2f} {account.currency}")
        level = account.margin_level if account.margin > 0 else None
        self.metric_values["margin_level"].setText(
            f"{level:,.1f}%" if level else "—")

    def set_tick(self, symbol, tick, previous_close: float | None = None,
                 trade_allowed: bool = True) -> None:
        self.bid.setText(f"{tick.bid:.{symbol.digits}f}")
        self.ask.setText(f"{tick.ask:.{symbol.digits}f}")
        self.spread.setText(f"{(tick.ask - tick.bid) / symbol.point:.1f} pt")
        quote_time = datetime.fromtimestamp(tick.time_msc / 1000, timezone.utc).astimezone()
        age = max(0.0, time.time() - tick.time_msc / 1000)
        self.quote_time.setText(f"报价时间 {quote_time:%H:%M:%S} · 距今 {age:.1f} 秒")
        self.market_state.setText("● 报价延迟" if age > 15 else
                                  ("● 实时 · 算法交易关闭" if not trade_allowed else "● 实时行情"))
        self._market_color_key = "warning" if age > 15 or not trade_allowed else "positive"
        if previous_close:
            change = tick.bid - previous_close
            percent = change / previous_close * 100
            self.day_change.setText(
                f"较昨收 {change:+.{symbol.digits}f} ({percent:+.2f}%)")
            self._change_color_key = "positive" if change >= 0 else "negative"
        else:
            self.day_change.setText("昨收数据不可用")
            self._change_color_key = "muted"
        self._apply_status_colors()

    def set_data(self, data: DashboardData, digits: int = 3) -> None:
        self.candles.set_data(data.candles, digits=digits)
        self.pnl.set_data(data.daily_pnl, currency=data.currency)
        if data.realized_30d is None:
            self.pnl_note.setText("成交历史不可用")
        else:
            self.pnl_note.setText(
                f"30 日 {data.realized_30d:+,.2f} {data.currency} · "
                f"今日 {data.realized_today:+,.2f} {data.currency}")
        self.dashboard_note.setText(" · ".join(data.errors) if data.errors else
                                    "K 线每 60 秒更新；盈亏按账户币种统计，不含当前浮动盈亏。")

    def set_books(self, active, pending) -> None:
        self.position_note.setText(f"{len(active)} 笔")
        self.order_note.setText(f"{len(pending)} 笔")
        fill_table(self.position_table, (
            (row.ticket, "BUY" if row.type == mt5.POSITION_TYPE_BUY else "SELL",
             f"{row.volume:g}", row.price_open, row.price_current,
             row.sl or "—", row.tp or "—", f"{row.profit:,.2f}")
            for row in active))
        fill_table(self.order_table, (
            (row.ticket, ORDER_NAMES.get(row.type, str(row.type)),
             f"{row.volume_initial:g}", row.price_open,
             row.sl or "—", row.tp or "—") for row in pending))

    def clear(self, message: str = "连接 MT5 后读取行情") -> None:
        self.account_text.setText("账户尚未连接")
        self.clear_market("● 未连接")
        for item in self.metric_values.values():
            item.setText("—")
        self.candles.set_data(())
        self.pnl.set_data(())
        self.pnl_note.setText("等待成交历史")
        self.dashboard_note.setText(message)
        self.set_books((), ())

    def clear_market(self, state: str = "● 行情暂不可用") -> None:
        self.market_state.setText(state)
        self.day_change.setText("—")
        self._market_color_key = "muted"
        self._change_color_key = "muted"
        self._apply_status_colors()
        self.quote_time.setText("报价不可用")
        for item in (self.bid, self.ask, self.spread):
            item.setText("—")

    def set_palette(self, palette: dict[str, str], theme: str) -> None:
        self.palette = palette
        self.theme = theme
        self.candles.set_palette(palette)
        self.pnl.set_palette(palette)
        self._apply_status_colors()

    def _apply_status_colors(self) -> None:
        self.market_state.setStyleSheet(f"color: {self.palette[self._market_color_key]};")
        self.day_change.setStyleSheet(f"color: {self.palette[self._change_color_key]};")
