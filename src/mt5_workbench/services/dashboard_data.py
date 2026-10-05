"""Read-only MT5 snapshots for the account and market dashboard.

The caller controls the refresh interval. This module never places, changes, or
removes orders. Money from deal history is reported in the account currency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from decimal import Decimal
from math import isfinite
from typing import Any

import MetaTrader5 as mt5


@dataclass(frozen=True)
class Candle:
    time: datetime  # UTC opening time
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    is_complete: bool


@dataclass(frozen=True)
class DailyPnl:
    day: date  # display timezone
    amount: Decimal  # account currency, net of commission/swap/fee


@dataclass(frozen=True)
class DashboardData:
    symbol: str
    currency: str
    candles: tuple[Candle, ...]
    daily_pnl: tuple[DailyPnl, ...]
    previous_close: float | None
    day_change: float | None
    day_change_pct: float | None
    bid: float | None
    ask: float | None
    spread_points: float | None
    balance: float | None
    equity: float | None
    floating_pnl: float | None
    margin_used: float | None
    margin_level_pct: float | None
    positions_count: int | None
    orders_count: int | None
    realized_today: Decimal | None
    realized_30d: Decimal | None
    history_available: bool
    errors: tuple[str, ...]


def _field(row: Any, name: str, default: Any = None) -> Any:
    """Read MT5 named tuples, NumPy structured rows, and test mappings."""
    try:
        return row[name]
    except (TypeError, ValueError, KeyError, IndexError):
        return getattr(row, name, default)


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _error(api: Any) -> str:
    try:
        return str(api.last_error())
    except Exception:
        return "unknown MT5 error"


def fetch_candles(symbol: str, *, api: Any = mt5, count: int = 72,
                  now: datetime | None = None) -> tuple[Candle, ...]:
    """Return valid M5 bars oldest first, including the still forming bar."""
    if count < 1:
        raise ValueError("count must be positive")
    current = _aware_now(now)
    rates = api.copy_rates_from_pos(symbol, api.TIMEFRAME_M5, 0, count)
    if rates is None:
        raise RuntimeError(f"M5 行情读取失败：{_error(api)}")
    candles: dict[int, Candle] = {}
    for row in rates:
        timestamp = _finite_number(_field(row, "time"))
        values = [_finite_number(_field(row, key)) for key in
                  ("open", "high", "low", "close")]
        if timestamp is None or timestamp <= 0 or any(v is None or v <= 0 for v in values):
            continue
        opened, high, low, closed = values
        if high < max(opened, closed) or low > min(opened, closed) or high < low:
            continue
        volume = _field(row, "tick_volume", 0)
        bar_time = datetime.fromtimestamp(timestamp, timezone.utc)
        candles[int(timestamp)] = Candle(
            time=bar_time, open=opened, high=high, low=low, close=closed,
            tick_volume=max(0, int(volume or 0)),
            is_complete=bar_time + timedelta(minutes=5) <= current)
    return tuple(candles[key] for key in sorted(candles))


def fetch_previous_close(symbol: str, *, api: Any = mt5) -> float | None:
    """Previous completed D1 close, suitable for a day change indicator."""
    rates = api.copy_rates_from_pos(symbol, api.TIMEFRAME_D1, 1, 1)
    if rates is None:
        raise RuntimeError(f"昨日收盘价读取失败：{_error(api)}")
    if len(rates) == 0:
        return None
    close = _finite_number(_field(rates[-1], "close"))
    return close if close is not None and close > 0 else None


def fetch_daily_realized(*, api: Any = mt5, now: datetime | None = None,
                         display_tz: tzinfo | None = None,
                         days: int = 30) -> tuple[DailyPnl, ...]:
    """Net trading deal cash flow per local day; excludes deposits/withdrawals.

    BUY/SELL entry commissions are included, even when the position remains
    open. An empty *successful* history response gives zero-filled days; an MT5
    failure raises so a dashboard does not mistake missing data for zero P&L.
    """
    if days < 1:
        raise ValueError("days must be positive")
    current = _aware_now(now)
    zone = display_tz or datetime.now().astimezone().tzinfo or timezone.utc
    local_today = current.astimezone(zone).date()
    first_day = local_today - timedelta(days=days - 1)
    start = datetime.combine(first_day, time.min, tzinfo=zone).astimezone(timezone.utc)
    deals = api.history_deals_get(start, current)
    if deals is None:
        raise RuntimeError(f"历史成交读取失败：{_error(api)}")
    amounts = {first_day + timedelta(days=offset): Decimal("0")
               for offset in range(days)}
    trading_types = {api.DEAL_TYPE_BUY, api.DEAL_TYPE_SELL}
    # Some brokers post commissions as separate account deals rather than in
    # the BUY/SELL deal's commission field.
    commission_types = {
        getattr(api, name) for name in (
            "DEAL_TYPE_COMMISSION", "DEAL_TYPE_COMMISSION_DAILY",
            "DEAL_TYPE_COMMISSION_MONTHLY", "DEAL_TYPE_COMMISSION_AGENT_DAILY",
            "DEAL_TYPE_COMMISSION_AGENT_MONTHLY") if hasattr(api, name)
    }
    for deal in deals:
        if _field(deal, "type") not in trading_types | commission_types:
            continue
        timestamp_msc = _finite_number(_field(deal, "time_msc"))
        timestamp = ((timestamp_msc / 1000) if timestamp_msc is not None and timestamp_msc > 0
                     else _finite_number(_field(deal, "time")))
        if timestamp is None:
            continue
        day = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(zone).date()
        if day not in amounts:
            continue
        net = Decimal("0")
        for field in ("profit", "swap", "commission", "fee"):
            value = _finite_number(_field(deal, field, 0))
            if value is not None:
                net += Decimal(str(value))
        amounts[day] += net
    return tuple(DailyPnl(day, amount) for day, amount in amounts.items())


def load_dashboard(symbol: str, account: Any, tick: Any, *, api: Any = mt5,
                   now: datetime | None = None,
                   display_tz: tzinfo | None = None,
                   include_books: bool = True) -> DashboardData:
    """Build a partial snapshot when one read-only MT5 source is unavailable."""
    current = _aware_now(now)
    errors: list[str] = []
    candles: tuple[Candle, ...] = ()
    daily_pnl: tuple[DailyPnl, ...] = ()
    previous_close = None
    history_available = False
    try:
        candles = fetch_candles(symbol, api=api, now=current)
        if not candles:
            errors.append("M5 行情暂无数据")
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        previous_close = fetch_previous_close(symbol, api=api)
        if previous_close is None:
            errors.append("昨日收盘价暂无数据")
    except RuntimeError as exc:
        errors.append(str(exc))
    try:
        daily_pnl = fetch_daily_realized(api=api, now=current,
                                         display_tz=display_tz)
        history_available = True
    except RuntimeError as exc:
        errors.append(str(exc))

    counts: list[int | None] = [None, None]
    if include_books:
        for index, (label, getter, kwargs) in enumerate(
                (("持仓", api.positions_get, {"symbol": symbol}),
                 ("挂单", api.orders_get, {"symbol": symbol}))):
            rows = getter(**kwargs)
            counts[index] = len(rows) if rows is not None else None
            if rows is None:
                errors.append(f"{label}读取失败：{_error(api)}")

    bid, ask = _finite_number(_field(tick, "bid")), _finite_number(_field(tick, "ask"))
    point = _finite_number(_field(api.symbol_info(symbol), "point"))
    valid_quote = bid is not None and ask is not None and bid > 0 and ask >= bid
    if not valid_quote:
        bid, ask = None, None
        errors.append("当前报价不可用")
    spread_points = (round((ask - bid) / point, 1) if valid_quote and point and point > 0
                     else None)
    day_change = bid - previous_close if bid is not None and previous_close else None
    day_change_pct = day_change / previous_close * 100 if day_change is not None else None

    margin_used = _finite_number(_field(account, "margin"))
    equity = _finite_number(_field(account, "equity"))
    margin_level_pct = (_finite_number(_field(account, "margin_level"))
                        if margin_used is not None and margin_used > 0 else None)
    if margin_level_pct is None and margin_used and margin_used > 0 and equity is not None:
        margin_level_pct = equity / margin_used * 100
    realized_today = daily_pnl[-1].amount if history_available else None
    realized_30d = sum((row.amount for row in daily_pnl), Decimal("0")) if history_available else None
    return DashboardData(
        symbol=symbol, currency=str(_field(account, "currency", "")),
        candles=candles, daily_pnl=daily_pnl, previous_close=previous_close,
        day_change=day_change, day_change_pct=day_change_pct,
        bid=bid, ask=ask, spread_points=spread_points,
        balance=_finite_number(_field(account, "balance")), equity=equity,
        floating_pnl=_finite_number(_field(account, "profit")),
        margin_used=margin_used, margin_level_pct=margin_level_pct,
        positions_count=counts[0], orders_count=counts[1],
        realized_today=realized_today, realized_30d=realized_30d,
        history_available=history_available, errors=tuple(errors))


def _aware_now(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return current.astimezone(timezone.utc)
