"""Responsive, read-only Qt charts for the MT5 workbench.

The widgets accept snapshots from dashboard_data, order_analytics and
position_optimizer. They deliberately have no MetaTrader5 dependency.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import ceil, isfinite
from typing import Any

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from mt5_workbench.ui.theme import FONT_FAMILIES, FONT_SIZES, THEMES


_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
_CENTER = Qt.AlignmentFlag.AlignCenter


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _money_tick(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if absolute >= 10_000:
        return f"{value / 1_000:.1f}k"
    if absolute >= 100:
        return f"{value:,.0f}"
    if absolute >= 10:
        return f"{value:,.1f}"
    return f"{value:,.2f}"


def _volume_tick(value: float) -> str:
    if value >= 10_000:
        return f"{value / 1000:.1f}k"
    if value >= 100:
        return f"{value:,.0f}"
    if value >= 1:
        return f"{value:.1f}"
    if value >= 0.01:
        return f"{value:.2f}"
    return f"{value:.4f}" if value > 0 else "0"


def _indexes(count: int, desired: int) -> list[int]:
    if count <= 0:
        return []
    steps = min(count, desired)
    if steps == 1:
        return [count - 1]
    return sorted({round(i * (count - 1) / (steps - 1)) for i in range(steps)})


def _day_label(value: Any) -> str:
    return value.strftime("%m/%d") if isinstance(value, (date, datetime)) else ""


class _Chart(QWidget):
    """Shared drawing primitives. Coordinates use logical Qt pixels."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(parent)
        self._colors: dict[str, str] = {}
        self.set_palette(palette)
        self.setMinimumSize(160, 100)

    def set_palette(self, palette: Mapping[str, str]) -> None:
        self._colors = {**THEMES["dark"], **dict(palette)}
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(480, 250)

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), QColor(self._colors["surface"]))
        font = QFont()
        font.setFamilies(FONT_FAMILIES)
        font.setPixelSize(FONT_SIZES["caption"])
        painter.setFont(font)
        self._paint(painter, self.width(), self.height())

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        raise NotImplementedError

    def _color(self, name: str) -> QColor:
        return QColor(self._colors[name])

    def _line(self, painter: QPainter, x1: float, y1: float,
              x2: float, y2: float, color: str, width: float = 1,
              dashed: bool = False) -> None:
        pen = QPen(self._color(color), width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def _rect(self, painter: QPainter, x: float, y: float,
              width: float, height: float, color: str) -> None:
        if width > 0 and height > 0:
            painter.fillRect(QRectF(x, y, width, height), self._color(color))

    def _text(self, painter: QPainter, x: float, y: float,
              width: float, height: float, value: Any,
              color: str = "muted", align: Any = _LEFT,
              bold: bool = False) -> None:
        font = QFont()
        font.setFamilies(FONT_FAMILIES)
        font.setPixelSize(FONT_SIZES["caption"])
        font.setBold(bold)
        painter.setFont(font)
        painter.setPen(self._color(color))
        painter.drawText(QRectF(x, y, width, height), align, str(value))

    def _empty(self, painter: QPainter, width: int, height: int,
               message: str) -> None:
        self._text(painter, 0, 0, width, height, message,
                   align=_CENTER)


class CandleChart(_Chart):
    """M5 candles with price and UTC time axes."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(palette, parent)
        self._candles: tuple[Any, ...] = ()
        self._digits = 3

    def set_data(self, candles: Sequence[Any], digits: int = 3) -> None:
        self._candles = tuple(candles or ())
        self._digits = max(0, min(int(digits), 8))
        self.update()

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        if width < 240 or height < 120:
            self._empty(painter, width, height, "扩大窗口以查看图表")
            return
        valid: list[tuple[Any, float, float, float, float]] = []
        for row in self._candles:
            values = tuple(_number(_field(row, key)) for key in
                           ("open", "high", "low", "close"))
            opened, high, low, closed = values
            if (None not in values and low <= min(opened, closed)
                    and high >= max(opened, closed)
                    and isinstance(_field(row, "time"), datetime)):
                valid.append((row, opened, high, low, closed))
        if not valid:
            self._empty(painter, width, height, "暂无 M5 K 线数据")
            return

        left, right, top, bottom = 14.0, width - 82.0, 17.0, height - 32.0
        plot_w, plot_h = right - left, bottom - top
        if plot_w < 80 or plot_h < 50:
            self._empty(painter, width, height, "扩大窗口以查看图表")
            return
        visible = valid[-max(1, int(plot_w // 9)):]
        low_price = min(row[3] for row in visible)
        high_price = max(row[2] for row in visible)
        span = high_price - low_price
        pad = span * 0.09 if span else max(abs(high_price) * 0.0001, 0.01)
        low_price -= pad
        high_price += pad
        span = high_price - low_price

        def y_for(value: float) -> float:
            return bottom - (value - low_price) / span * plot_h

        for index in range(5):
            fraction = index / 4
            y = top + fraction * plot_h
            price = high_price - fraction * span
            self._line(painter, left, y, right, y, "chart_grid")
            self._text(painter, right + 7, y - 9, 73, 18,
                       f"{price:.{self._digits}f}")

        slot = plot_w / len(visible)
        body_w = max(2.0, min(slot * 0.64, 12.0))
        for index, (row, opened, high, low, closed) in enumerate(visible):
            x = left + (index + 0.5) * slot
            color = "chart_up" if closed >= opened else "chart_down"
            self._line(painter, x, y_for(high), x, y_for(low), color)
            body_top = y_for(max(opened, closed))
            body_bottom = y_for(min(opened, closed))
            if body_bottom - body_top < 2:
                body_top -= 1
                body_bottom += 1
            body = QRectF(x - body_w / 2, body_top,
                          body_w, body_bottom - body_top)
            painter.setPen(QPen(self._color(color), 1))
            painter.setBrush(self._color(color if _field(row, "is_complete", True)
                                      else "surface"))
            painter.drawRect(body)

        label_count = max(2, min(5, int(plot_w // 110) + 1))
        last_date = _field(visible[-1][0], "time").date()
        for index in _indexes(len(visible), label_count):
            stamp = _field(visible[index][0], "time")
            label = (stamp.strftime("%m/%d %H:%M") if stamp.date() != last_date
                     else stamp.strftime("%H:%M"))
            x = left + (index + 0.5) * slot
            self._text(painter, x - 46, bottom + 7, 92, 20, label,
                       align=_CENTER)
        self._text(painter, right + 5, bottom + 7, 70, 20, "UTC")


class DailyPnlChart(_Chart):
    """Daily realized P&L in the supplied account currency."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(palette, parent)
        self._rows: tuple[Any, ...] = ()
        self._currency = "USC"

    def set_data(self, rows: Sequence[Any], currency: str = "USC") -> None:
        self._rows = tuple(rows or ())
        self._currency = str(currency)
        self.update()

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        if width < 240 or height < 120:
            self._empty(painter, width, height, "扩大窗口以查看图表")
            return
        valid = [(row, value) for row in self._rows
                 if (value := _number(_field(row, "amount"))) is not None]
        if not valid:
            self._empty(painter, width, height, "暂无已实现盈亏数据")
            return
        left, right, top, bottom = 14.0, width - 72.0, 31.0, height - 32.0
        plot_w, plot_h = right - left, bottom - top
        if plot_w < 80 or plot_h < 50:
            self._empty(painter, width, height, "扩大窗口以查看图表")
            return
        visible = valid[-max(1, int(plot_w // 10)):]
        values = [amount for _, amount in visible]
        low, high = min(0.0, min(values)), max(0.0, max(values))
        if low == high:
            low, high = -1.0, 1.0
        else:
            pad = (high - low) * 0.08
            low = min(0.0, low - pad)
            high = max(0.0, high + pad)

        def y_for(value: float) -> float:
            return bottom - (value - low) / (high - low) * plot_h

        for index in range(5):
            value = high - index * (high - low) / 4
            y = y_for(value)
            self._line(painter, left, y, right, y, "chart_grid")
            self._text(painter, right + 7, y - 9, 65, 18, _money_tick(value))
        zero_y = y_for(0)
        self._line(painter, left, zero_y, right, zero_y, "muted")
        self._text(painter, left, 4, 220, 20, f"单位 {self._currency}")

        slot = plot_w / len(visible)
        bar_w = max(2.0, min(slot * 0.7, 18.0))
        for index, (_, amount) in enumerate(visible):
            if amount == 0:
                continue
            x = left + (index + 0.5) * slot
            endpoint = y_for(amount)
            self._rect(painter, x - bar_w / 2, min(endpoint, zero_y),
                       bar_w, max(1.0, abs(endpoint - zero_y)),
                       "positive" if amount > 0 else "negative")
        count = max(2, min(5, int(plot_w // 100) + 1))
        for index in _indexes(len(visible), count):
            x = left + (index + 0.5) * slot
            self._text(painter, x - 34, bottom + 7, 68, 20,
                       _day_label(_field(visible[index][0], "day")), align=_CENTER)
        if all(value == 0 for value in values):
            self._text(painter, left, top + plot_h * 0.25, plot_w, 24,
                       "所选期间无已实现盈亏", align=_CENTER)


class ExecutionChart(_Chart):
    """Daily BUY/SELL lots or daily deal counts.

    Pass ``unit='deals'`` for an account-wide scope where lot sizes across
    symbols cannot be compared; any other unit draws separate lot bars.
    """

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(palette, parent)
        self._rows: tuple[Any, ...] = ()
        self._unit = "lots"

    def set_data(self, rows: Sequence[Any], unit: str = "lots") -> None:
        self._rows = tuple(rows or ())
        self._unit = str(unit)
        self.update()

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        if width < 270 or height < 150:
            self._empty(painter, width, height, "扩大窗口以查看成交分布")
            return
        valid: list[tuple[Any, float, float, int]] = []
        for row in self._rows:
            buy = _number(_field(row, "buy_lots"))
            sell = _number(_field(row, "sell_lots"))
            try:
                deals = int(_field(row, "deal_count"))
            except (TypeError, ValueError, OverflowError):
                continue
            if buy is not None and sell is not None and buy >= 0 and sell >= 0 and deals >= 0:
                valid.append((row, buy, sell, deals))
        count_mode = self._unit.lower() in {"deals", "count", "笔"}
        active = (any(deals > 0 for _, _, _, deals in valid) if count_mode else
                  any(buy > 0 or sell > 0 for _, buy, sell, _ in valid))
        if not active:
            self._empty(painter, width, height, "所选期间无成交")
            return
        left, right, top, bottom = 18.0, width - 68.0, 39.0, height - 33.0
        plot_w, plot_h = right - left, bottom - top
        if plot_w < 140 or plot_h < 70:
            self._empty(painter, width, height, "扩大窗口以查看成交分布")
            return
        visible = valid[-max(1, int(plot_w // 12)):]
        peak = (max(deals for _, _, _, deals in visible) if count_mode else
                max(max(buy, sell) for _, buy, sell, _ in visible))
        if count_mode:
            step = max(1, ceil(peak / 4))
            ceiling = (ceil(peak / step) + 1) * step
            ticks = list(range(0, ceiling + 1, step))
        else:
            ceiling = peak * 1.12
            ticks = [ceiling * index / 4 for index in range(5)]

        def y_for(value: float) -> float:
            return bottom - value / ceiling * plot_h

        title = ("成交笔数 · 笔" if count_mode else
                 f"成交手数 · {'lot' if self._unit == 'lots' else self._unit}")
        self._text(painter, left, 8, 190, 19, title)
        if not count_mode:
            legend_x = max(left + 98, right - 100)
            self._rect(painter, legend_x, 11, 9, 9, "chart_up")
            self._text(painter, legend_x + 14, 7, 38, 18, "BUY", "text")
            self._rect(painter, legend_x + 56, 11, 9, 9, "chart_down")
            self._text(painter, legend_x + 70, 7, 40, 18, "SELL", "text")
        for value in reversed(ticks):
            y = y_for(value)
            self._line(painter, left, y, right, y, "chart_grid")
            label = str(int(value)) if count_mode else _volume_tick(value)
            self._text(painter, right + 7, y - 9, 60, 18, label)
        slot = plot_w / len(visible)
        bar_w = max(2.0, min(slot * (0.55 if count_mode else 0.31),
                             16.0 if count_mode else 10.0))
        for index, (_, buy, sell, deals) in enumerate(visible):
            x = left + (index + 0.5) * slot
            if count_mode and deals:
                self._rect(painter, x - bar_w / 2, y_for(deals), bar_w,
                           bottom - y_for(deals), "chart_line")
            elif not count_mode:
                if buy:
                    self._rect(painter, x - bar_w - 1, y_for(buy), bar_w,
                               bottom - y_for(buy), "chart_up")
                if sell:
                    self._rect(painter, x + 1, y_for(sell), bar_w,
                               bottom - y_for(sell), "chart_down")
        for index in _indexes(len(visible), max(2, min(6, int(plot_w // 90) + 1))):
            x = left + (index + 0.5) * slot
            self._text(painter, x - 34, bottom + 8, 68, 20,
                       _day_label(_field(visible[index][0], "day")), align=_CENTER)


class StatusChart(_Chart):
    """Counts and shares of historical order terminal states."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(palette, parent)
        self._rows: tuple[Any, ...] = ()

    def set_data(self, rows: Sequence[Any]) -> None:
        self._rows = tuple(rows or ())
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(480, max(150, len(self._rows) * 28 + 24))

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        if width < 270 or height < 150:
            self._empty(painter, width, height, "扩大窗口以查看订单状态")
            return
        rows: list[tuple[str, int]] = []
        for row in self._rows:
            try:
                count = int(_field(row, "count"))
            except (TypeError, ValueError, OverflowError):
                continue
            if count > 0:
                rows.append((str(_field(row, "label", "")), count))
        if not rows:
            self._empty(painter, width, height, "所选期间无历史订单")
            return
        total = sum(count for _, count in rows)
        top, bottom = 13.0, height - 12.0
        row_h = (bottom - top) / len(rows)
        if row_h < 23:
            self._empty(painter, width, height, "扩大窗口以查看全部订单状态")
            return
        label_w = max(58, min(96, int(width * 0.21)))
        plot_left, plot_right = label_w + 14.0, width - 103.0
        plot_w = plot_right - plot_left
        if plot_w < 95:
            self._empty(painter, width, height, "扩大窗口以查看订单状态")
            return
        fills = ("accent", "accent_alt", "warning", "negative",
                 "chart_up", "chart_down")
        for index, (label, count) in enumerate(rows):
            center = top + (index + 0.5) * row_h
            bar_half = max(4.0, min(8.0, row_h * 0.22))
            self._text(painter, 3, center - 11, plot_left - 15, 22,
                       label, "text", _RIGHT)
            self._rect(painter, plot_left, center - bar_half, plot_w,
                       bar_half * 2, "surface_alt")
            self._rect(painter, plot_left, center - bar_half,
                       plot_w * count / total, bar_half * 2,
                       fills[index % len(fills)])
            self._text(painter, plot_right + 10, center - 11, 92, 22,
                       f"{count}  ·  {count / total:.0%}", "text", bold=True)


class CashflowChart(_Chart):
    """Cumulative trading cash flow with a daily peak drawdown strip."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(palette, parent)
        self._rows: tuple[Any, ...] = ()
        self._currency = "USC"
        self._valid_rows: list[tuple[Any, float, float]] = []
        self._hover_index: int | None = None
        self._hover_bounds: tuple[float, float, float, float] | None = None
        self.setMouseTracking(True)

    def set_data(self, rows: Sequence[Any], currency: str = "USC") -> None:
        self._rows = tuple(rows or ())
        self._currency = str(currency)
        self._hover_index = None
        self._hover_bounds = None
        QToolTip.hideText()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(600, 300)

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        self._hover_bounds = None
        self._valid_rows = []
        if width < 290 or height < 210:
            self._empty(painter, width, height, "扩大窗口以查看现金流曲线")
            return
        for row in self._rows:
            cumulative = _number(_field(row, "cumulative"))
            drawdown = _number(_field(row, "drawdown"))
            if cumulative is not None and drawdown is not None:
                self._valid_rows.append((row, cumulative, abs(drawdown)))
        if not self._valid_rows:
            self._empty(painter, width, height, "所选期间无交易现金流数据")
            return
        rows = self._valid_rows
        left, right = 18.0, width - 75.0
        line_top = 38.0
        dd_top = float(int(height * 0.72))
        line_bottom = dd_top - 20.0
        dd_bottom = height - 33.0
        line_h = line_bottom - line_top
        dd_h = dd_bottom - dd_top - 16.0
        if right - left < 135 or line_h < 75 or dd_h < 14:
            self._empty(painter, width, height, "扩大窗口以查看现金流曲线")
            return
        self._hover_bounds = (left, right, line_top, dd_bottom)
        cash_values = [value for _, value, _ in rows]
        low = min(0.0, min(cash_values))
        high = max(0.0, max(cash_values))
        if low == high:
            low, high = -1.0, 1.0
        else:
            pad = (high - low) * 0.09
            low -= pad
            high += pad

        def y_for(value: float) -> float:
            return line_bottom - (value - low) / (high - low) * line_h

        def x_for(index: int) -> float:
            return ((left + right) / 2 if len(rows) == 1 else
                    left + index * (right - left) / (len(rows) - 1))

        self._text(painter, left, 8, 230, 20,
                   f"累计交易净现金流 · {self._currency}")
        legend_x = max(left + 146, right - 127)
        if legend_x + 127 < width - 4:
            self._line(painter, legend_x, 16, legend_x + 16, 16,
                       "chart_line", 2)
            self._text(painter, legend_x + 21, 7, 43, 18, "累计", "text")
            self._line(painter, legend_x + 68, 16, legend_x + 84, 16,
                       "muted", dashed=True)
            self._text(painter, legend_x + 89, 7, 42, 18, "峰值", "text")
        for index in range(5):
            value = high - index * (high - low) / 4
            y = y_for(value)
            self._line(painter, left, y, right, y, "chart_grid")
            self._text(painter, right + 7, y - 9, 68, 18, _money_tick(value))
        self._line(painter, left, y_for(0), right, y_for(0), "muted", dashed=True)

        running_peak = 0.0
        cash_points: list[tuple[float, float]] = []
        peak_points: list[tuple[float, float]] = []
        for index, (_, cumulative, _) in enumerate(rows):
            running_peak = max(running_peak, cumulative)
            cash_points.append((x_for(index), y_for(cumulative)))
            peak_points.append((x_for(index), y_for(running_peak)))
        for points, color, pen_w, dashed in ((peak_points, "muted", 1, True),
                                             (cash_points, "chart_line", 2, False)):
            for first, second in zip(points, points[1:]):
                self._line(painter, *first, *second, color, pen_w, dashed)
        last_x, last_y = cash_points[-1]
        painter.setPen(QPen(self._color("surface"), 1))
        painter.setBrush(self._color("chart_line"))
        painter.drawEllipse(QPointF(last_x, last_y), 3, 3)

        max_dd = max(drawdown for _, _, drawdown in rows)
        self._text(painter, left, dd_top - 22, 160, 20, "每日现金流回撤")
        if max_dd > 0:
            self._text(painter, right - 180, dd_top - 22, 180, 20,
                       f"最大 {_money_tick(max_dd)} {self._currency}",
                       "negative", _RIGHT)
        self._line(painter, left, dd_top + 1, right, dd_top + 1, "chart_grid")
        if max_dd > 0:
            slot = (right - left) / len(rows)
            bar_w = max(1.0, min(10.0, slot * 0.68))
            for index, (_, _, drawdown) in enumerate(rows):
                if drawdown > 0:
                    self._rect(painter, x_for(index) - bar_w / 2, dd_top + 1,
                               bar_w, drawdown / max_dd * dd_h, "negative")
        else:
            self._text(painter, left, dd_top + 5, right - left, dd_h,
                       "无回撤", align=_CENTER)
        for index in _indexes(len(rows),
                              max(2, min(6, int((right - left) // 100) + 1))):
            x = x_for(index)
            self._text(painter, x - 34, dd_bottom + 5, 68, 20,
                       _day_label(_field(rows[index][0], "day")), align=_CENTER)
        if self._hover_index is not None and self._hover_index < len(rows):
            x, y = cash_points[self._hover_index]
            self._line(painter, x, line_top, x, dd_bottom,
                       "border", dashed=True)
            painter.setPen(QPen(self._color("surface"), 1))
            painter.setBrush(self._color("chart_line"))
            painter.drawEllipse(QPointF(x, y), 4, 4)

    def mouseMoveEvent(self, event: Any) -> None:
        bounds = self._hover_bounds
        if bounds is None or not self._valid_rows:
            return
        left, right, top, bottom = bounds
        x, y = event.position().x(), event.position().y()
        if not (left <= x <= right and top <= y <= bottom):
            if self._hover_index is not None:
                self._hover_index = None
                QToolTip.hideText()
                self.update()
            return
        index = (0 if len(self._valid_rows) == 1 else
                 round((x - left) / (right - left) * (len(self._valid_rows) - 1)))
        index = max(0, min(index, len(self._valid_rows) - 1))
        if index == self._hover_index:
            return
        self._hover_index = index
        row, cumulative, drawdown = self._valid_rows[index]
        day = _field(row, "day")
        day_text = day.strftime("%Y-%m-%d") if isinstance(day, (date, datetime)) else "—"
        daily = _number(_field(row, "daily_cashflow"))
        daily_text = f"{daily:+,.2f}" if daily is not None else "—"
        QToolTip.showText(event.globalPosition().toPoint(),
                          f"{day_text}\n当日净额  {daily_text} {self._currency}\n"
                          f"累计净额  {cumulative:+,.2f} {self._currency}\n"
                          f"当日回撤  {drawdown:,.2f} {self._currency}", self)
        self.update()

    def leaveEvent(self, event: Any) -> None:
        self._hover_index = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)


class AllocationChart(_Chart):
    """Risk allocation by proposed entry, measured against the full budget."""

    def __init__(self, palette: Mapping[str, str], parent: QWidget | None = None):
        super().__init__(palette, parent)
        self._entries: tuple[Any, ...] = ()
        self._budget_usd: float | None = None

    def set_data(self, entries: Sequence[Any], budget_usd: Any) -> None:
        self._entries = tuple(entries or ())
        self._budget_usd = _number(budget_usd)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(480, max(110, 20 + len(self._entries) * 31))

    def _paint(self, painter: QPainter, width: int, height: int) -> None:
        if width < 270 or height < 100:
            self._empty(painter, width, height, "扩大窗口以查看风险分配")
            return
        if not self._entries or self._budget_usd is None or self._budget_usd <= 0:
            self._empty(painter, width, height, "暂无 LIMIT 下单方案")
            return
        rows: list[tuple[str, float]] = []
        for entry in self._entries:
            risk = _number(_field(entry, "risk_usd"))
            if risk is not None and risk >= 0:
                rows.append((str(_field(entry, "price", "—")), risk))
        if not rows:
            self._empty(painter, width, height, "暂无 LIMIT 下单方案")
            return
        row_h = min(34.0, (height - 18.0) / len(rows))
        if row_h < 15:
            self._empty(painter, width, height, "扩大窗口以查看全部档位")
            return
        left, right = 88.0, width - 104.0
        plot_w = right - left
        if plot_w < 78:
            self._empty(painter, width, height, "扩大窗口以查看风险分配")
            return
        bar_h = min(22.0, row_h - 6.0)
        for index, (price, risk) in enumerate(rows):
            y = 9.0 + index * row_h + (row_h - bar_h) / 2
            self._text(painter, 3, y - 1, 78, bar_h + 2,
                       price, "muted")
            self._rect(painter, left, y, plot_w, bar_h, "surface_alt")
            self._rect(painter, left, y,
                       plot_w * min(1.0, risk / self._budget_usd), bar_h,
                       "accent" if index == len(rows) - 1 else "accent_alt")
            self._text(painter, right + 8, y - 1, 95, bar_h + 2,
                       f"{risk:.2f} USD", "text", _RIGHT)


__all__ = ["CandleChart", "DailyPnlChart", "CashflowChart",
           "ExecutionChart", "StatusChart", "AllocationChart"]
