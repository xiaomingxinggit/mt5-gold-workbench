"""Read-only XAU position sizing with a fixed stop and optional take profit."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Callable

import MetaTrader5 as mt5

from mt5_workbench.domain.account_policy import is_usc_currency


@dataclass(frozen=True)
class Entry:
    price: Decimal
    volume: Decimal
    stop_distance: Decimal
    risk_usd: Decimal


@dataclass(frozen=True)
class Optimization:
    side: str
    mode: str
    budget_usd: Decimal
    budget_usage_percent: Decimal
    risk_cap_usd: Decimal
    total_volume: Decimal
    total_risk_usd: Decimal
    unused_usd: Decimal
    entries: tuple[Entry, ...]
    take_profit: Decimal | None = None
    range_low: Decimal | None = None
    range_high: Decimal | None = None


def money(value, name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{name} 需要填写数字") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{name} 必须是大于 0 的有限数字")
    return number


def _usd_per_lot(symbol_name: str, side: str, entry: Decimal, stop: Decimal,
                 currency: str, profit_fn: Callable) -> Decimal:
    order_type = mt5.ORDER_TYPE_SELL if side == "SELL" else mt5.ORDER_TYPE_BUY
    value = profit_fn(order_type, symbol_name, 1.0, float(entry), float(stop))
    if value is None or value >= 0:
        raise ValueError(f"MT5 无法核对 {entry} 到止损 {stop} 的亏损")
    if not is_usc_currency(currency):
        raise ValueError("仅支持 USC 美分账户")
    actual = Decimal(str(-value)) / 100
    rule = abs(stop - entry)  # Agreed account rule: 1 lot × price change 1 = 1 USD.
    if abs(actual - rule) > max(Decimal("0.01"), rule * Decimal("0.01")):
        raise ValueError(f"{entry} 的 MT5 风险 {actual:.2f} USD 与约定规则不一致")
    return max(actual, rule)


def _levels(low: Decimal, high: Decimal, tick: Decimal, count: int) -> list[Decimal]:
    if count == 1:
        return [high]
    span = high - low
    prices = []
    for index in range(count):
        raw = low + span * Decimal(index) / Decimal(count - 1)
        price = (raw / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick
        prices.append(price)
    if len(set(prices)) != count:
        raise ValueError("区间太窄，无法生成互不重复的档位；请减少档数")
    return prices


def optimize(
    symbol,
    account_currency: str,
    low,
    high,
    stop,
    budget_usd,
    levels: int = 3,
    mode: str = "weighted",
    weights: tuple[Decimal, ...] | None = None,
    budget_usage_percent=95,
    profit_fn: Callable = mt5.order_calc_profit,
    take_profit=None,
) -> Optimization:
    """Return suggestions only; this module never places or checks orders.

    Modes: weighted, equal_risk, max_lots_ladder, max_lots_single.
    The total risk assumes every suggested entry fills and hits the fixed stop.
    The optional target does not change stop-loss risk or volume sizing.
    """
    if not is_usc_currency(account_currency):
        raise ValueError("仅支持 USC 美分账户")
    low = money(low, "区间起点")
    high = money(high, "区间终点")
    stop = money(stop, "止损价")
    budget = money(budget_usd, "风险预算")
    target = (money(take_profit, "止盈价") if take_profit is not None
              and str(take_profit).strip() else None)
    usage_percent = money(str(budget_usage_percent).strip().removesuffix("%"),
                          "预算使用比例")
    if usage_percent > 100:
        raise ValueError("预算使用比例不能超过 100%")
    risk_cap = budget * usage_percent / 100
    if low >= high:
        raise ValueError("区间起点必须小于终点")
    if stop > high:
        side = "SELL"
    elif stop < low:
        side = "BUY"
    else:
        raise ValueError("止损必须完全位于开仓区间外")
    if target is not None:
        if side == "SELL" and target >= low:
            raise ValueError("SELL 的统一止盈价必须低于区间起点")
        if side == "BUY" and target <= high:
            raise ValueError("BUY 的统一止盈价必须高于区间终点")
    if mode not in {"weighted", "equal_risk", "max_lots_ladder", "max_lots_single"}:
        raise ValueError("未知仓位分配模式")
    if not isinstance(levels, int) or not 2 <= levels <= 12:
        raise ValueError("档数必须在 2～12 之间")

    tick = Decimal(str(symbol.trade_tick_size or symbol.point))
    minimum = Decimal(str(symbol.volume_min))
    maximum = Decimal(str(symbol.volume_max))
    step = Decimal(str(symbol.volume_step))
    if tick <= 0 or minimum <= 0 or maximum < minimum or step <= 0:
        raise ValueError("MT5 品种的价格或手数参数无效")
    if low % tick or high % tick or stop % tick or (target is not None and target % tick):
        raise ValueError(f"价格必须符合品种最小跳动 {tick}")

    prices = ([high if side == "SELL" else low] if mode == "max_lots_single"
              else _levels(low, high, tick, levels))
    costs = [_usd_per_lot(symbol.name, side, price, stop, account_currency, profit_fn)
             for price in prices]
    max_extra_units = int(((maximum - minimum) / step).to_integral_value(rounding=ROUND_FLOOR))
    units = [0] * len(prices)
    base_risk = sum((minimum * cost for cost in costs), Decimal(0))
    if base_risk > risk_cap:
        raise ValueError(f"最小手数配置需要 {base_risk:.2f} USD，超过有效上限 {risk_cap:.2f} USD")

    if mode in {"weighted", "equal_risk"}:
        if mode == "weighted":
            if weights is None or len(weights) != len(prices):
                raise ValueError(f"请输入 {len(prices)} 个正数权重，例如 1,2,3")
            ratios = [money(weight, "档位权重") for weight in weights]
        else:
            ratios = [Decimal(1)] * len(prices)
        ratio_sum = sum(ratios, Decimal(0))
        for index, cost in enumerate(costs):
            target_budget = risk_cap * ratios[index] / ratio_sum
            affordable = (target_budget - minimum * cost) / (step * cost)
            if affordable < 0:
                raise ValueError(f"{prices[index]} 分配的风险不足以覆盖最小手数")
            units[index] = min(max_extra_units,
                               int(affordable.to_integral_value(rounding=ROUND_FLOOR)))
        used = sum(((minimum + step * units[i]) * costs[i]
                    for i in range(len(prices))), Decimal(0))
        # Use a small remainder caused by volume steps without materially changing
        # the equal-risk allocation: at most one extra step at each entry.
        for index in sorted(range(len(prices)), key=lambda i: costs[i]):
            extra = step * costs[index]
            if units[index] < max_extra_units and used + extra <= risk_cap:
                units[index] += 1
                used += extra
    else:
        used = base_risk
        # The closest price to the stop has the lowest loss per lot. Allocate
        # remaining risk there first, respecting the broker's volume step/max.
        for index in sorted(range(len(prices)), key=lambda i: costs[i]):
            extra = step * costs[index]
            affordable = int(((risk_cap - used) / extra).to_integral_value(
                rounding=ROUND_FLOOR))
            added = min(max_extra_units, max(0, affordable))
            units[index] += added
            used += added * extra

    entries = tuple(
        Entry(price=price,
              volume=minimum + step * units[index],
              stop_distance=abs(stop - price),
              risk_usd=(minimum + step * units[index]) * costs[index])
        for index, price in enumerate(prices)
    )
    total_risk = sum((item.risk_usd for item in entries), Decimal(0))
    if total_risk > risk_cap:
        raise RuntimeError("内部风险计算超过有效上限，结果已阻止")
    total_volume = sum((item.volume for item in entries), Decimal(0))
    volume_limit = Decimal(str(getattr(symbol, "volume_limit", 0) or 0))
    if volume_limit and total_volume > volume_limit:
        raise ValueError(f"总手数 {total_volume} 超过品种聚合上限 {volume_limit}")
    return Optimization(side, mode, budget, usage_percent, risk_cap,
                        total_volume, total_risk,
                        budget - total_risk, entries, target, low, high)
