"""Pure, read-only M1 EMA alignment calculation for the experimental monitor.

Callers supply M1 closing prices in chronological order. They decide whether
the last value is the still-forming bar or the latest completed bar. Alignment
describes only the distance among averages; it does not predict a reversal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence


EMA_PERIODS = (7, 14, 30, 60)
MIN_M1_BARS = 180  # Three times the longest EMA period for a practical warmup.


@dataclass(frozen=True)
class EmaAlignment:
    ema7: Decimal
    ema14: Decimal
    ema30: Decimal
    ema60: Decimal
    spread_price: Decimal
    spread_points: Decimal
    tolerance_points: Decimal
    aligned: bool
    bars_used: int
    includes_forming_bar: bool

    @property
    def emas(self) -> dict[int, Decimal]:
        return {7: self.ema7, 14: self.ema14, 30: self.ema30, 60: self.ema60}

    @property
    def ema_values(self) -> dict[int, Decimal]:
        return self.emas

    @property
    def ema_spread_points(self) -> Decimal:
        return self.spread_points


def _number(value: object, name: str, *, allow_zero: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{name} 必须是有限数字") from exc
    if not number.is_finite() or (number < 0 if allow_zero else number <= 0):
        requirement = "非负" if allow_zero else "大于 0"
        raise ValueError(f"{name} 必须是{requirement}的有限数字")
    return number


def _ema(closes: Sequence[Decimal], period: int) -> Decimal:
    # The initial SMA is a reproducible seed. Additional bars reduce its
    # influence before the latest value is used for alignment.
    average = sum(closes[:period], Decimal(0)) / Decimal(period)
    alpha = Decimal(2) / Decimal(period + 1)
    for close in closes[period:]:
        average += alpha * (close - average)
    return average


def evaluate_m1_ema_alignment(
    closes: Sequence[object],
    *,
    point: object,
    tolerance_points: object = 5,
    includes_forming_bar: bool = False,
) -> EmaAlignment:
    """Compare M1 EMA 7/14/30/60 using a maximum-spread tolerance.

    ``closes`` must contain at least 180 available M1 bars, oldest first.
    The caller may include the current, incomplete bar as the last close and
    then set ``includes_forming_bar=True``. A new tick can change that result.
    ``point`` is the MT5 symbol point (for example, ``symbol_info.point``).
    The result is aligned when max(EMA) - min(EMA) <= point * tolerance.
    """
    if len(closes) < MIN_M1_BARS:
        raise ValueError(f"至少需要 {MIN_M1_BARS} 根 1 分钟 K 线，当前只有 {len(closes)} 根")
    point_value = _number(point, "品种点值")
    tolerance = _number(tolerance_points, "EMA 允许偏差点数", allow_zero=True)
    prices = tuple(_number(value, f"第 {index} 根收盘价")
                   for index, value in enumerate(closes, start=1))

    values = {period: _ema(prices, period) for period in EMA_PERIODS}
    spread = max(values.values()) - min(values.values())
    spread_points = spread / point_value
    return EmaAlignment(
        ema7=values[7], ema14=values[14], ema30=values[30], ema60=values[60],
        spread_price=spread, spread_points=spread_points,
        tolerance_points=tolerance, aligned=spread_points <= tolerance,
        bars_used=len(prices), includes_forming_bar=bool(includes_forming_bar),
    )
