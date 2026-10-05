"""Validate a manually sized single LIMIT order without a sizing budget."""

from __future__ import annotations

import math
import time
from decimal import Decimal

import MetaTrader5 as mt5

from mt5_workbench.domain.account_policy import is_usc_account
from mt5_workbench.domain.position_optimizer import money
from mt5_workbench.services.trade_execution import (
    MAGIC, MAX_QUOTE_AGE_SECONDS, ORDER_MODE_LIMIT, ORDER_MODE_SL, ORDER_MODE_TP,
)


def basic_fields(payload: dict) -> dict[str, str]:
    return {key: str(payload.get(key, "")).strip()
            for key in ("side", "price", "volume", "sl", "tp")}


def build_basic_request(fields: dict, account, symbol, tick, *, api=mt5,
                        now: float | None = None) -> tuple[dict, Decimal | None]:
    """Return one validated pending request and its optional SL risk in USD."""
    if not is_usc_account(account):
        raise ValueError("仅支持 USC 美分账户")
    if not account.trade_allowed or not account.trade_expert:
        raise ValueError("账户未允许程序交易")
    if symbol.name != "XAUUSDc":
        raise ValueError("仅支持 XAUUSDc")
    if symbol.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
        raise ValueError("该品种当前不允许完整交易")
    if not symbol.order_mode & ORDER_MODE_LIMIT:
        raise ValueError("该品种不支持 LIMIT 挂单")
    now = time.time() if now is None else now
    if (not all(math.isfinite(float(value)) for value in (tick.bid, tick.ask, tick.time_msc))
            or tick.bid <= 0 or tick.ask < tick.bid
            or not -5 <= now - tick.time_msc / 1000 <= MAX_QUOTE_AGE_SECONDS):
        raise ValueError("报价无效或已过期，请等待新报价")
    side = fields["side"]
    if side not in {"BUY", "SELL"}:
        raise ValueError("仅允许买入限价或卖出限价")
    price = money(fields["price"], "限价")
    volume = money(fields["volume"], "手数")
    sl = money(fields["sl"], "止损价") if fields["sl"] else Decimal(0)
    tp = money(fields["tp"], "止盈价") if fields["tp"] else Decimal(0)
    if not all(math.isfinite(float(value)) for value in (price, volume, sl, tp)):
        raise ValueError("价格或手数超出有效范围")
    step = money(symbol.trade_tick_size or symbol.point, "价格步进")
    lot_step = money(symbol.volume_step, "手数步进")
    minimum, maximum = Decimal(str(symbol.volume_min)), Decimal(str(symbol.volume_max))
    if not minimum <= volume <= maximum or (volume - minimum) % lot_step:
        raise ValueError(f"手数必须在 {minimum}～{maximum} 之间，步进 {lot_step}")
    if any(value % step for value in (price, sl, tp)):
        raise ValueError(f"价格必须符合品种步进 {step}")
    volume_limit = Decimal(str(getattr(symbol, "volume_limit", 0) or 0))
    if volume_limit and volume > volume_limit:
        raise ValueError("手数超过品种方向总量限制")
    distance = Decimal(str(symbol.trade_stops_level)) * Decimal(str(symbol.point))
    if side == "BUY":
        if price >= Decimal(str(tick.bid)) - distance:
            raise ValueError("买入限价必须低于当前 Bid，并满足最小挂单距离")
        if sl and sl >= price - distance:
            raise ValueError("买入止损必须低于限价，并满足最小距离")
        if tp and tp <= price + distance:
            raise ValueError("买入止盈必须高于限价，并满足最小距离")
    else:
        if price <= Decimal(str(tick.ask)) + distance:
            raise ValueError("卖出限价必须高于当前 Ask，并满足最小挂单距离")
        if sl and sl <= price + distance:
            raise ValueError("卖出止损必须高于限价，并满足最小距离")
        if tp and tp >= price - distance:
            raise ValueError("卖出止盈必须低于限价，并满足最小距离")
    if sl and not symbol.order_mode & ORDER_MODE_SL:
        raise ValueError("该品种不支持挂单止损")
    if tp and not symbol.order_mode & ORDER_MODE_TP:
        raise ValueError("该品种不支持挂单止盈")
    risk = None
    if sl:
        profit = api.order_calc_profit(
            mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
            symbol.name, float(volume), float(price), float(sl),
        )
        if profit is None or not math.isfinite(float(profit)) or profit >= 0:
            raise ValueError("MT5 无法核对止损风险")
        risk = -Decimal(str(profit)) / 100
    return {
        "action": mt5.TRADE_ACTION_PENDING, "symbol": symbol.name,
        "type": mt5.ORDER_TYPE_BUY_LIMIT if side == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT,
        "volume": float(volume), "price": float(price), "sl": float(sl), "tp": float(tp),
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_RETURN,
        "magic": MAGIC, "comment": "MT5 basic limit",
    }, risk
