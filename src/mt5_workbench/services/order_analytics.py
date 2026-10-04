"""Read-only order and execution analytics from an attached MT5 terminal.

An order is a request; a deal is an execution.  Historical order states are
counted separately from BUY/SELL deal volume.  Monetary values are in the
account currency (USC for a cent account), not automatically USD.

MT5 reference: orders_get, positions_get, history_orders_get,
history_deals_get, Order Properties and Deal Properties at mql5.com/en/docs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

import MetaTrader5 as mt5


@dataclass(frozen=True)
class OrderRecord:
    ticket: int
    symbol: str
    type_label: str
    status_label: str
    created_at: datetime | None  # UTC
    done_at: datetime | None  # UTC; None for active orders
    volume_initial: float | None  # lots
    volume_current: float | None  # remaining lots
    price_open: float | None
    sl: float | None
    tp: float | None
    comment: str


@dataclass(frozen=True)
class DealRecord:
    ticket: int
    order_ticket: int | None
    symbol: str
    side_label: str  # execution direction; may close an opposite position
    entry_label: str
    executed_at: datetime  # UTC
    volume: float | None  # lots
    price: float | None
    profit: Decimal | None  # account currency
    swap: Decimal | None
    commission: Decimal | None
    fee: Decimal | None
    cashflow: Decimal | None  # sum of four fields, if each is available


@dataclass(frozen=True)
class DailyExecution:
    day: date  # display timezone
    buy_lots: float  # BUY deals, including exits of SELL positions
    sell_lots: float  # SELL deals, including exits of BUY positions
    deal_count: int


@dataclass(frozen=True)
class DailyAccountCashflow:
    day: date  # display timezone
    daily_cashflow: Decimal  # account currency; trading activity only
    cumulative: Decimal  # starts at zero on the first day of this window
    drawdown: Decimal  # positive amount below the highest daily cumulative value


@dataclass(frozen=True)
class OrderStatusCount:
    label: str
    count: int


@dataclass(frozen=True)
class OrderAnalytics:
    currency: str
    scope_symbol: str | None  # None means the entire account
    as_of: datetime  # UTC
    lookback_days: int
    pending_orders: tuple[OrderRecord, ...]
    recent_orders: tuple[OrderRecord, ...]  # historical, most recently done first
    recent_deals: tuple[DealRecord, ...]  # BUY/SELL deals, newest first
    daily_execution: tuple[DailyExecution, ...]
    account_curve: tuple[DailyAccountCashflow, ...]  # all symbols, irrespective of scope_symbol
    account_max_drawdown: Decimal | None  # account currency, within this window
    account_current_drawdown: Decimal | None  # account currency, last daily point
    status_counts: tuple[OrderStatusCount, ...]  # historical orders only
    pending_count: int | None
    pending_lots: float | None
    position_count: int | None
    position_lots: float | None
    deal_count: int | None  # BUY/SELL executions only
    buy_lots: float | None
    sell_lots: float | None
    traded_lots: float | None
    net_trading_cashflow: Decimal | None
    pending_available: bool
    positions_available: bool
    history_orders_available: bool
    history_deals_available: bool
    errors: tuple[str, ...]


def _field(row: Any, name: str, default: Any = None) -> Any:
    try:
        return row[name]
    except (TypeError, ValueError, KeyError, IndexError):
        return getattr(row, name, default)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _nonnegative(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result >= 0 else None


def _positive_price(value: Any) -> float | None:
    result = _number(value)
    return result if result is not None and result > 0 else None


def _money(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _utc_timestamp(row: Any, name: str) -> datetime | None:
    milliseconds = _number(_field(row, f"{name}_msc"))
    seconds = (milliseconds / 1000 if milliseconds is not None and milliseconds > 0
               else _number(_field(row, name)))
    if seconds is None or seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _last_error(api: Any) -> str:
    try:
        return str(api.last_error())
    except Exception:
        return "未知 MT5 错误"


def _read_rows(api: Any, label: str, method: str, errors: list[str],
               *args: Any, **kwargs: Any) -> tuple[Any, ...] | None:
    try:
        rows = getattr(api, method)(*args, **kwargs)
    except Exception as exc:
        errors.append(f"{label}读取异常：{exc}")
        return None
    if rows is None:
        errors.append(f"{label}读取失败：{_last_error(api)}")
        return None
    return tuple(rows)


def _enum_map(api: Any, prefix: str, names: tuple[tuple[str, str], ...]) -> dict[int, str]:
    result = {}
    for suffix, label in names:
        value = getattr(api, f"{prefix}{suffix}", None)
        if isinstance(value, int):
            result[value] = label
    return result


def _order_record(row: Any, type_names: dict[int, str],
                  state_names: dict[int, str]) -> OrderRecord | None:
    try:
        ticket = int(_field(row, "ticket"))
    except (TypeError, ValueError, OverflowError):
        return None
    if ticket <= 0:
        return None
    raw_type, raw_state = _field(row, "type"), _field(row, "state")
    return OrderRecord(
        ticket=ticket,
        symbol=str(_field(row, "symbol", "") or ""),
        type_label=type_names.get(raw_type, f"类型 {raw_type}"),
        status_label=state_names.get(raw_state, f"状态 {raw_state}"),
        created_at=_utc_timestamp(row, "time_setup"),
        done_at=_utc_timestamp(row, "time_done"),
        volume_initial=_nonnegative(_field(row, "volume_initial")),
        volume_current=_nonnegative(_field(row, "volume_current")),
        price_open=_positive_price(_field(row, "price_open")),
        sl=_positive_price(_field(row, "sl")),
        tp=_positive_price(_field(row, "tp")),
        comment=str(_field(row, "comment", "") or ""),
    )


def _deal_record(row: Any, *, buy_type: int, sell_type: int,
                 entry_names: dict[int, str]) -> DealRecord | None:
    try:
        ticket = int(_field(row, "ticket"))
    except (TypeError, ValueError, OverflowError):
        return None
    executed_at = _utc_timestamp(row, "time")
    if ticket <= 0 or executed_at is None:
        return None
    try:
        order_ticket = int(_field(row, "order"))
        if order_ticket <= 0:
            order_ticket = None
    except (TypeError, ValueError, OverflowError):
        order_ticket = None
    values = tuple(_money(_field(row, name)) for name in
                   ("profit", "swap", "commission", "fee"))
    cashflow = sum(values, Decimal("0")) if all(value is not None for value in values) else None
    kind = _field(row, "type")
    return DealRecord(
        ticket=ticket, order_ticket=order_ticket,
        symbol=str(_field(row, "symbol", "") or ""),
        side_label="BUY" if kind == buy_type else "SELL" if kind == sell_type else "未知",
        entry_label=entry_names.get(_field(row, "entry"), "未知"),
        executed_at=executed_at,
        volume=_nonnegative(_field(row, "volume")),
        price=_positive_price(_field(row, "price")),
        profit=values[0], swap=values[1],
        commission=values[2], fee=values[3], cashflow=cashflow,
    )


def _summed_volume(rows: tuple[Any, ...], field_name: str) -> float | None:
    values = [_nonnegative(_field(row, field_name)) for row in rows]
    return round(sum(values), 8) if all(value is not None for value in values) else None


def _aware_now(now: datetime | None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return current.astimezone(timezone.utc)


_ORDER_TYPES = (
    ("BUY", "BUY"), ("SELL", "SELL"),
    ("BUY_LIMIT", "BUY LIMIT"), ("SELL_LIMIT", "SELL LIMIT"),
    ("BUY_STOP", "BUY STOP"), ("SELL_STOP", "SELL STOP"),
    ("BUY_STOP_LIMIT", "BUY STOP LIMIT"),
    ("SELL_STOP_LIMIT", "SELL STOP LIMIT"), ("CLOSE_BY", "CLOSE BY"),
)
_ORDER_STATES = (
    ("STARTED", "待受理"), ("PLACED", "已挂单"),
    ("PARTIAL", "部分成交"), ("FILLED", "已成交"),
    ("CANCELED", "已取消"), ("REJECTED", "已拒绝"),
    ("EXPIRED", "已过期"), ("REQUEST_ADD", "提交中"),
    ("REQUEST_MODIFY", "修改中"), ("REQUEST_CANCEL", "撤销中"),
)
_COMMISSION_SUFFIXES = (
    "COMMISSION", "COMMISSION_DAILY", "COMMISSION_MONTHLY",
    "COMMISSION_AGENT_DAILY", "COMMISSION_AGENT_MONTHLY",
)
_DEAL_ENTRIES = (
    ("IN", "开仓"), ("OUT", "平仓"),
    ("INOUT", "反手"), ("OUT_BY", "对冲平仓"),
)


def load_order_analytics(account: Any, *, symbol: str | None = None,
                         api: Any = mt5, now: datetime | None = None,
                         display_tz: tzinfo | None = None,
                         days: int = 30, max_recent_orders: int = 100,
                         max_recent_deals: int = 100) -> OrderAnalytics:
    """Collect order data without changing MT5 state.

    The time window covers ``days`` calendar dates in ``display_tz``, through
    ``now``.  Historical orders and deals are independent; if either call fails,
    its metrics are unavailable rather than misleading zeros.  A deal's type
    describes execution direction, which is not necessarily position direction.

    ``net_trading_cashflow`` adds profit, swap, commission and fee from BUY/SELL
    deals and attributable standalone commission deals.  This is not a closed
    trade win rate or realized P&L of fully closed positions: entry commissions
    can occur while positions remain open.  Symbol-scoped standalone commissions
    with no symbol/order/position link cannot be allocated and are omitted.

    ``account_curve`` always covers every symbol.  It excludes deposits and
    withdrawals, includes standalone commission records, and starts at zero at
    the beginning of the selected window.  Drawdowns use daily cumulative
    amounts and the zero baseline; they are account-currency amounts, not
    percentages or changes in actual account equity.
    """
    if days < 1 or days > 365:
        raise ValueError("days must be between 1 and 365")
    if max_recent_orders < 1:
        raise ValueError("max_recent_orders must be positive")
    if max_recent_deals < 1:
        raise ValueError("max_recent_deals must be positive")
    if symbol is not None:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a nonempty string or None")
        symbol = symbol.strip()
    current = _aware_now(now)
    zone = display_tz or datetime.now().astimezone().tzinfo or timezone.utc
    local_today = current.astimezone(zone).date()
    first_day = local_today - timedelta(days=days - 1)
    start = datetime.combine(first_day, time.min, tzinfo=zone).astimezone(timezone.utc)
    errors: list[str] = []

    active_args = {"symbol": symbol} if symbol is not None else {}
    active_rows = _read_rows(api, "当前挂单", "orders_get", errors, **active_args)
    position_rows = _read_rows(api, "当前持仓", "positions_get", errors, **active_args)
    history_rows = _read_rows(api, "历史订单", "history_orders_get", errors,
                              start, current, **({"group": symbol} if symbol else {}))
    deal_rows = _read_rows(api, "历史成交", "history_deals_get", errors, start, current)

    type_names = _enum_map(api, "ORDER_TYPE_", _ORDER_TYPES)
    state_names = _enum_map(api, "ORDER_STATE_", _ORDER_STATES)
    pending_types = {value for suffix in (
        "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP",
        "BUY_STOP_LIMIT", "SELL_STOP_LIMIT")
        if isinstance(value := getattr(api, f"ORDER_TYPE_{suffix}", None), int)}
    pending_orders: tuple[OrderRecord, ...] = ()
    pending_count = pending_lots = None
    if active_rows is not None:
        selected = tuple(row for row in active_rows
                         if (symbol is None or _field(row, "symbol") == symbol)
                         and _field(row, "type") in pending_types)
        pending_count = len(selected)
        pending_lots = _summed_volume(selected, "volume_current")
        if pending_lots is None:
            errors.append("部分挂单缺少有效剩余手数，挂单总手数不可用")
        parsed = (_order_record(row, type_names, state_names) for row in selected)
        pending_orders = tuple(sorted((row for row in parsed if row is not None),
                                      key=lambda row: row.created_at or datetime.min.replace(tzinfo=timezone.utc),
                                      reverse=True))
        if len(pending_orders) != pending_count:
            errors.append("部分挂单缺少有效订单编号，未显示在明细中")

    position_count = position_lots = None
    if position_rows is not None:
        selected = tuple(row for row in position_rows
                         if symbol is None or _field(row, "symbol") == symbol)
        position_count = len(selected)
        position_lots = _summed_volume(selected, "volume")
        if position_lots is None:
            errors.append("部分持仓缺少有效手数，持仓总手数不可用")

    recent_orders: tuple[OrderRecord, ...] = ()
    status_counts: tuple[OrderStatusCount, ...] = ()
    if history_rows is not None:
        by_ticket: dict[int, OrderRecord] = {}
        for raw in history_rows:
            if symbol is not None and _field(raw, "symbol") != symbol:
                continue
            order = _order_record(raw, type_names, state_names)
            if order is None:
                continue
            event_time = order.done_at or order.created_at
            if event_time is None or not start <= event_time <= current:
                continue
            previous = by_ticket.get(order.ticket)
            if previous is None or ((order.done_at or order.created_at) >
                                    (previous.done_at or previous.created_at)):
                by_ticket[order.ticket] = order
        rows = sorted(by_ticket.values(),
                      key=lambda row: row.done_at or row.created_at,
                      reverse=True)
        recent_orders = tuple(rows[:max_recent_orders])
        counts: dict[str, int] = {}
        for order in rows:
            counts[order.status_label] = counts.get(order.status_label, 0) + 1
        labels = [label for _, label in _ORDER_STATES]
        status_counts = tuple(OrderStatusCount(label, counts[label])
                              for label in labels if counts.get(label, 0))
        status_counts += tuple(OrderStatusCount(label, count)
                               for label, count in sorted(counts.items()) if label not in labels)

    daily_execution: tuple[DailyExecution, ...] = ()
    account_curve: tuple[DailyAccountCashflow, ...] = ()
    account_max_drawdown = account_current_drawdown = None
    recent_deals: tuple[DealRecord, ...] = ()
    deal_count = buy_lots = sell_lots = traded_lots = net_trading_cashflow = None
    if deal_rows is not None:
        buy_type = getattr(api, "DEAL_TYPE_BUY", None)
        sell_type = getattr(api, "DEAL_TYPE_SELL", None)
        commission_types = {getattr(api, f"DEAL_TYPE_{suffix}")
                            for suffix in _COMMISSION_SUFFIXES
                            if hasattr(api, f"DEAL_TYPE_{suffix}")}
        amounts = {first_day + timedelta(days=offset): [0.0, 0.0, 0]
                   for offset in range(days)}
        account_amounts = {day: Decimal("0") for day in amounts}
        account_money_valid = True
        selected_deals: list[tuple[Any, date]] = []
        commissions: list[tuple[Any, date]] = []
        linked_orders: set[int] = set()
        linked_positions: set[int] = set()
        seen_tickets: set[int] = set()
        skipped_volume = 0
        for raw in deal_rows:
            kind = _field(raw, "type")
            account_trade = kind in (buy_type, sell_type) or kind in commission_types
            timestamp = _utc_timestamp(raw, "time")
            if timestamp is None:
                if account_trade:
                    account_money_valid = False
                continue
            if not start <= timestamp <= current:
                continue
            day = timestamp.astimezone(zone).date()
            if day not in amounts:
                continue
            ticket = _field(raw, "ticket")
            if ticket is not None:
                try:
                    ticket = int(ticket)
                except (TypeError, ValueError, OverflowError):
                    ticket = None
            if ticket is not None and ticket > 0:
                if ticket in seen_tickets:
                    continue
                seen_tickets.add(ticket)
            if account_trade:
                components = tuple(_money(_field(raw, name)) for name in
                                   ("profit", "swap", "commission", "fee"))
                if any(component is None for component in components):
                    account_money_valid = False
                else:
                    account_amounts[day] += sum(components, Decimal("0"))
            if kind in (buy_type, sell_type):
                if symbol is not None and _field(raw, "symbol") != symbol:
                    continue
                volume = _nonnegative(_field(raw, "volume"))
                if volume is None:
                    skipped_volume += 1
                else:
                    bucket = amounts[day]
                    bucket[0 if kind == buy_type else 1] += volume
                    bucket[2] += 1
                selected_deals.append((raw, day))
                for field, target in (("order", linked_orders),
                                      ("position_id", linked_positions)):
                    try:
                        value = int(_field(raw, field, 0))
                    except (TypeError, ValueError, OverflowError):
                        value = 0
                    if value > 0:
                        target.add(value)
            elif kind in commission_types:
                commissions.append((raw, day))

        cash_rows = list(selected_deals)
        entry_names = _enum_map(api, "DEAL_ENTRY_", _DEAL_ENTRIES)
        parsed_deals = (_deal_record(raw, buy_type=buy_type,
                                     sell_type=sell_type,
                                     entry_names=entry_names)
                        for raw, _ in selected_deals)
        all_recent_deals = sorted((row for row in parsed_deals if row is not None),
                                  key=lambda row: (row.executed_at, row.ticket),
                                  reverse=True)
        recent_deals = tuple(all_recent_deals[:max_recent_deals])
        if len(all_recent_deals) != len(selected_deals):
            errors.append("部分成交缺少有效成交编号或时间，未显示在成交明细中")
        for raw, day in commissions:
            if symbol is None or _field(raw, "symbol") == symbol:
                cash_rows.append((raw, day))
                continue
            order_id = _field(raw, "order", 0)
            position_id = _field(raw, "position_id", 0)
            if ((isinstance(order_id, int) and order_id in linked_orders) or
                    (isinstance(position_id, int) and position_id in linked_positions)):
                cash_rows.append((raw, day))

        total_money = Decimal("0")
        valid_money = True
        for raw, _ in cash_rows:
            for name in ("profit", "swap", "commission", "fee"):
                amount = _money(_field(raw, name))
                if amount is None:
                    valid_money = False
                else:
                    total_money += amount
        if not valid_money:
            errors.append("部分成交缺少有效资金字段，交易现金流不可用")
        if skipped_volume:
            errors.append(f"{skipped_volume} 笔成交缺少有效手数，成交量指标不可用")

        if not skipped_volume:
            daily_execution = tuple(
                DailyExecution(day, round(values[0], 8), round(values[1], 8), values[2])
                for day, values in amounts.items())
            deal_count = sum(row.deal_count for row in daily_execution)
            buy_lots = round(sum(row.buy_lots for row in daily_execution), 8)
            sell_lots = round(sum(row.sell_lots for row in daily_execution), 8)
        traded_lots = round(buy_lots + sell_lots, 8) if buy_lots is not None and sell_lots is not None else None
        net_trading_cashflow = total_money if valid_money else None
        if account_money_valid:
            cumulative = peak = max_drawdown = Decimal("0")
            points: list[DailyAccountCashflow] = []
            for day, amount in account_amounts.items():
                cumulative += amount
                peak = max(peak, cumulative)
                drawdown = peak - cumulative
                max_drawdown = max(max_drawdown, drawdown)
                points.append(DailyAccountCashflow(day, amount, cumulative, drawdown))
            account_curve = tuple(points)
            account_max_drawdown = max_drawdown
            account_current_drawdown = points[-1].drawdown
        else:
            errors.append("部分全账户成交缺少有效时间或资金字段，账户曲线及回撤不可用")

    return OrderAnalytics(
        currency=str(_field(account, "currency", "") or ""),
        scope_symbol=symbol, as_of=current, lookback_days=days,
        pending_orders=pending_orders, recent_orders=recent_orders,
        recent_deals=recent_deals,
        daily_execution=daily_execution, account_curve=account_curve,
        account_max_drawdown=account_max_drawdown,
        account_current_drawdown=account_current_drawdown,
        status_counts=status_counts,
        pending_count=pending_count, pending_lots=pending_lots,
        position_count=position_count, position_lots=position_lots,
        deal_count=deal_count, buy_lots=buy_lots, sell_lots=sell_lots,
        traded_lots=traded_lots, net_trading_cashflow=net_trading_cashflow,
        pending_available=active_rows is not None,
        positions_available=position_rows is not None,
        history_orders_available=history_rows is not None,
        history_deals_available=deal_rows is not None,
        errors=tuple(errors),
    )
