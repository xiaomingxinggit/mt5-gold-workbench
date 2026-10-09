"""Read-only ATR and daily true-range references from completed MT5 bars.

ATR uses the simple average of N true ranges, as in MetaQuotes' MT5 ATR.
Annual candles are synthesized only from twelve consecutive monthly bars.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import fsum
from typing import Any

import MetaTrader5 as mt5

from mt5_workbench.services.dashboard_data import _field, _finite_number


@dataclass(frozen=True)
class Bar:
    time: datetime
    high: float
    low: float
    close: float


def _read_bars(symbol: str, timeframe: int, count: int, api: Any) -> tuple[Bar, ...]:
    # MT5 index zero is the forming bar. Do not let partial periods lower ATR.
    rates = api.copy_rates_from_pos(symbol, timeframe, 1, count)
    if rates is None:
        raise RuntimeError(f"行情读取失败：{api.last_error()}")
    bars: dict[int, Bar] = {}
    for row in rates:
        stamp = _finite_number(_field(row, "time"))
        values = [_finite_number(_field(row, name)) for name in ("open", "high", "low", "close")]
        if stamp is None or stamp <= 0 or any(v is None or v <= 0 for v in values):
            raise ValueError("历史 K 线包含无效数值")
        opened, high, low, closed = values
        if high < max(opened, closed) or low > min(opened, closed):
            raise ValueError("历史 K 线价格范围无效")
        if int(stamp) in bars:
            raise ValueError("历史 K 线时间重复")
        try:
            instant = datetime.fromtimestamp(stamp, timezone.utc)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("历史 K 线时间无效") from exc
        bars[int(stamp)] = Bar(instant, high, low, closed)
    return tuple(bars[key] for key in sorted(bars))


def _true_ranges(bars: tuple[Bar, ...]) -> list[tuple[Bar, float]]:
    return [(bar, max(bar.high - bar.low, abs(bar.high - previous.close),
                      abs(bar.low - previous.close)))
            for previous, bar in zip(bars, bars[1:])]


def _annual_bars(months: tuple[Bar, ...], current_year: int) -> tuple[Bar, ...]:
    grouped: dict[int, list[Bar]] = {}
    for bar in months:
        if bar.time.year < current_year:
            grouped.setdefault(bar.time.year, []).append(bar)
    result = []
    for year, rows in sorted(grouped.items()):
        if [row.time.month for row in rows] == list(range(1, 13)):
            result.append(Bar(datetime(year, 1, 1, tzinfo=timezone.utc),
                              max(row.high for row in rows), min(row.low for row in rows),
                              rows[-1].close))
    return tuple(result)


def _atr_row(key: str, label: str, bars: tuple[Bar, ...], period: int,
             point: float | None, *, reason: str = "") -> dict[str, Any]:
    value = None
    if not reason and len(bars) >= period + 1:
        recent = bars[-period - 1:]
        if key == "year" and any(b.time.year != a.time.year + 1
                                  for a, b in zip(recent, recent[1:])):
            reason = "年线历史不连续"
        elif key == "month" and any((b.time.year * 12 + b.time.month)
                                    != (a.time.year * 12 + a.time.month + 1)
                                    for a, b in zip(recent, recent[1:])):
            reason = "月线历史不连续"
        else:
            value = fsum(tr for _, tr in _true_ranges(recent)) / period
    elif not reason:
        reason = f"数据不足：需 {period + 1} 根已收盘 K 线，已有 {len(bars)} 根"
    return {"key": key, "label": label, "price": value,
            "points": value / point if value is not None and point else None,
            "samples": period if value is not None else 0,
            "lastBar": bars[-1].time.isoformat() if bars else "", "reason": reason}


def _shift_month(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def _daily_references(bars: tuple[Bar, ...], point: float | None,
                      error: str) -> list[dict[str, Any]]:
    ranges = _true_ranges(bars)
    # Anchor to the last completed trading day, so weekends do not shrink the sample.
    end = bars[-1].time.date() + timedelta(days=1) if bars else None
    result = []
    for key, label in (("year", "近一年"), ("month", "近一个月"),
                       ("week", "近一周"), ("day", "最近交易日")):
        start = (None if end is None else _shift_month(end, -12) if key == "year"
                 else _shift_month(end, -1) if key == "month"
                 else end - timedelta(days=7 if key == "week" else 1))
        samples = [(bar, tr) for bar, tr in ranges if start <= bar.time.date() < end] if start else []
        covered = bool(samples and bars[0].time.date() < start)
        value = fsum(tr for _, tr in samples) / len(samples) if covered and not error else None
        result.append({"key": key, "label": label, "price": value,
                       "points": value / point if value is not None and point else None,
                       "samples": len(samples), "start": start.isoformat() if start else "",
                       "end": (end - timedelta(days=1)).isoformat() if end else "",
                       "reason": error or ("" if covered else "历史不足，无法覆盖完整区间")})
    return result


def load_indicator_reference(symbol: str, *, api: Any = mt5, period: int = 14,
                             now: datetime | None = None) -> dict[str, Any]:
    if type(period) is not int or not 1 <= period <= 100:
        raise ValueError("ATR 周期必须是 1–100 的整数")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must include a timezone")
    current = current.astimezone(timezone.utc)
    errors = []
    point = _finite_number(_field(api.symbol_info(symbol), "point"))
    if point is None or point <= 0:
        point = None
    series, failures = {}, {}
    for key, name, count in (("day", "D1", 400), ("week", "W1", period + 1),
                             ("month", "MN1", (period + 2) * 12)):
        try:
            series[key] = _read_bars(symbol, getattr(api, "TIMEFRAME_" + name), count, api)
            failures[key] = ""
        except (RuntimeError, ValueError) as exc:
            series[key], failures[key] = (), str(exc)
            errors.append(f"{name}：{exc}")
    series["year"] = _annual_bars(series["month"], current.year)
    failures["year"] = failures["month"]
    if series["year"] and series["year"][-1].time.year != current.year - 1:
        failures["year"] = "缺少上一完整年份的月线数据"
    return {"loading": False, "symbol": symbol, "period": period, "point": point,
            "atr": [_atr_row(key, label, series[key], period, point, reason=failures[key])
                    for key, label in (("year", "年"), ("month", "月"), ("week", "周"), ("day", "日"))],
            "dailyAverages": _daily_references(series["day"], point, failures["day"]),
            "errors": errors, "updatedAt": current.isoformat()}
