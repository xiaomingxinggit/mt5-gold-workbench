"""Read-only XAUUSDc M1 EMA market snapshot for the experimental monitor.

MT5 calls can block, so the caller controls polling and must avoid overlapping
requests. An alignment is shown only for fresh quotes and a current M1 bar.
It describes the proximity of four averages, never a reversal prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from math import isfinite
from types import MappingProxyType
from typing import Any, Mapping

import MetaTrader5 as mt5

from mt5_workbench.domain.ema_monitor import (
    MIN_M1_BARS,
    evaluate_m1_ema_alignment,
)


_EMPTY_EMAS: Mapping[int, Decimal] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class EmaMonitorSnapshot:
    """A single observation; times are UTC and prices are account-symbol prices."""

    bid: float | None
    ask: float | None
    ema_values: Mapping[int, Decimal]
    ema_spread_points: Decimal | None
    tolerance_points: Decimal
    aligned: bool
    bar_time: datetime | None
    observed_at: datetime
    quote_age_seconds: float | None
    reason: str
    includes_forming_bar: bool
    status: str  # live, stale, waiting, error


def _field(row: Any, name: str, default: Any = None) -> Any:
    """Read named tuples, NumPy structured rows, dictionaries and fake rows."""
    try:
        return row[name]
    except (TypeError, ValueError, KeyError, IndexError):
        return getattr(row, name, default)


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if isfinite(result) else None


def _tolerance(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("EMA 允许偏差点数必须是非负有限数字") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("EMA 允许偏差点数必须是非负有限数字")
    return result


def _snapshot(*, observed_at: datetime, tolerance_points: Decimal,
              status: str, reason: str, bid: float | None = None,
              ask: float | None = None, bar_time: datetime | None = None,
              quote_age_seconds: float | None = None,
              ema_values: Mapping[int, Decimal] = _EMPTY_EMAS,
              ema_spread_points: Decimal | None = None,
              aligned: bool = False,
              includes_forming_bar: bool = False) -> EmaMonitorSnapshot:
    return EmaMonitorSnapshot(
        bid=bid, ask=ask,
        ema_values=MappingProxyType(dict(ema_values)),
        ema_spread_points=ema_spread_points,
        tolerance_points=tolerance_points,
        aligned=aligned if status == "live" else False,
        bar_time=bar_time, observed_at=observed_at,
        quote_age_seconds=quote_age_seconds,
        reason=reason, includes_forming_bar=includes_forming_bar,
        status=status,
    )


def fetch_m1_ema_snapshot(
    symbol: str = "XAUUSDc", *, api: Any = mt5, now: datetime | None = None,
    tolerance_points: object = 5, max_quote_age_seconds: float = 15,
    max_bar_age_seconds: float = 90,
) -> EmaMonitorSnapshot:
    """Read the latest tick and 200 M1 rates; never send or inspect orders.

    The newest M1 rate (position zero in MT5) is the still-forming bar. The
    service sorts rates by UTC opening time before evaluating the EMAs and
    requires at least 180 distinct M1 bars ending in the current minute.
    A missing, delayed, or future quote/bar never produces an aligned signal.
    """
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("now 必须带时区")
    observed_at = observed_at.astimezone(timezone.utc)
    tolerance = _tolerance(tolerance_points)
    if not (isfinite(max_quote_age_seconds) and max_quote_age_seconds > 0):
        raise ValueError("报价时效必须大于 0")
    if not (isfinite(max_bar_age_seconds) and max_bar_age_seconds > 0):
        raise ValueError("K 线时效必须大于 0")

    try:
        info = api.symbol_info(symbol)
        tick = api.symbol_info_tick(symbol)
        rates = api.copy_rates_from_pos(symbol, api.TIMEFRAME_M1, 0, 200)
    except Exception as exc:
        if now is None:
            observed_at = datetime.now(timezone.utc)
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="error", reason=f"MT5 行情读取失败：{exc}")
    # Judge freshness at the end of the MT5 reads. A slow rates request must
    # not make a tick captured before it look current when the UI receives it.
    if now is None:
        observed_at = datetime.now(timezone.utc)
    if info is None:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="error", reason=f"品种 {symbol} 不可用")
    point = _finite_float(_field(info, "point"))
    if point is None or point <= 0:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="error", reason="品种点值不可用")

    bid = _finite_float(_field(tick, "bid"))
    ask = _finite_float(_field(tick, "ask"))
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting", reason="等待有效报价")
    tick_msc = _finite_float(_field(tick, "time_msc"))
    tick_sec = (_finite_float(_field(tick, "time"))
                if tick_msc is None or tick_msc <= 0 else tick_msc / 1000)
    if tick_sec is None or tick_sec <= 0:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="stale", reason="报价没有有效时间戳",
                         bid=bid, ask=ask)
    quote_age = observed_at.timestamp() - tick_sec

    if rates is None or len(rates) == 0:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting", reason="等待 1 分钟 K 线",
                         bid=bid, ask=ask, quote_age_seconds=quote_age)
    bars: list[tuple[int, Any]] = []
    for row in rates:
        time_value = _finite_float(_field(row, "time"))
        close = _field(row, "close")
        if (time_value is None or time_value <= 0 or not time_value.is_integer()
                or int(time_value) % 60 != 0):
            return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                             status="waiting", reason="1 分钟 K 线时间不完整",
                             bid=bid, ask=ask, quote_age_seconds=quote_age)
        bars.append((int(time_value), close))
    bars.sort(key=lambda item: item[0])
    # MT5 may omit minutes with no ticks, including around a market break.
    # Gaps are acceptable; duplicate timestamps would weight a minute twice.
    if any(newer[0] == older[0] for older, newer in zip(bars, bars[1:])):
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting", reason="1 分钟 K 线时间重复",
                         bid=bid, ask=ask, quote_age_seconds=quote_age)
    try:
        bar_time = datetime.fromtimestamp(bars[-1][0], timezone.utc)
    except (OverflowError, OSError, ValueError):
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting", reason="1 分钟 K 线时间无效",
                         bid=bid, ask=ask, quote_age_seconds=quote_age)

    if len(bars) < MIN_M1_BARS:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting",
                         reason=f"需要至少 {MIN_M1_BARS} 根 1 分钟 K 线，当前 {len(bars)} 根",
                         bid=bid, ask=ask, bar_time=bar_time,
                         quote_age_seconds=quote_age)
    bar_age = (observed_at - bar_time).total_seconds()
    if bar_age > max_bar_age_seconds or bar_age < -5:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="stale", reason="1 分钟 K 线已延迟",
                         bid=bid, ask=ask, bar_time=bar_time,
                         quote_age_seconds=quote_age)
    current_minute = int(observed_at.timestamp()) // 60 * 60
    tick_minute = int(tick_sec) // 60 * 60
    if bars[-1][0] != current_minute or bars[-1][0] != tick_minute:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting", reason="等待当前分钟的 K 线",
                         bid=bid, ask=ask, bar_time=bar_time,
                         quote_age_seconds=quote_age)
    if quote_age > max_quote_age_seconds or quote_age < -5:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="stale", reason="报价已延迟",
                         bid=bid, ask=ask, bar_time=bar_time,
                         quote_age_seconds=quote_age)

    try:
        result = evaluate_m1_ema_alignment(
            [close for _, close in bars], point=point,
            tolerance_points=tolerance, includes_forming_bar=True)
    except ValueError as exc:
        return _snapshot(observed_at=observed_at, tolerance_points=tolerance,
                         status="waiting", reason=f"1 分钟 K 线数据无效：{exc}",
                         bid=bid, ask=ask, bar_time=bar_time,
                         quote_age_seconds=quote_age)
    return _snapshot(
        observed_at=observed_at, tolerance_points=tolerance,
        status="live", reason=("EMA 已靠拢；当前 K 线尚未收盘"
                               if result.aligned else "EMA 尚未靠拢"),
        bid=bid, ask=ask, bar_time=bar_time,
        quote_age_seconds=quote_age, ema_values=result.ema_values,
        ema_spread_points=result.ema_spread_points,
        aligned=result.aligned, includes_forming_bar=True,
    )
