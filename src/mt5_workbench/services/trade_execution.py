"""Explicitly confirmed MT5 LIMIT orders for a calculated range configuration."""

from __future__ import annotations

import hashlib
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import MetaTrader5 as mt5

from mt5_workbench.domain.account_policy import is_usc_account
from mt5_workbench.domain.position_optimizer import Optimization


MAX_QUOTE_AGE_SECONDS = 15
MAGIC = 2601001
ORDER_MODE_LIMIT = 2  # MQL5 SYMBOL_ORDER_LIMIT; Python package omits this flag.
ORDER_MODE_SL = 16     # MQL5 SYMBOL_ORDER_SL.
ORDER_MODE_TP = 32     # MQL5 SYMBOL_ORDER_TP.
LIMIT_ORDER_TYPES = (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT)


def _number(value) -> Decimal:
    return Decimal(str(value))


def _aligned(value: Decimal, step: Decimal) -> bool:
    return step > 0 and value % step == 0


def _require_limit_requests(requests: tuple[dict, ...]) -> None:
    """Reject every non-LIMIT request before any MT5 check or send call."""
    if not requests:
        raise ValueError("没有可发送的 LIMIT 挂单")
    for index, request in enumerate(requests, 1):
        if (not isinstance(request, dict)
                or request.get("action") != mt5.TRADE_ACTION_PENDING
                or request.get("type") not in LIMIT_ORDER_TYPES):
            raise ValueError(f"第 {index} 档仅允许 BUY LIMIT 或 SELL LIMIT 挂单")


def build_requests(result: Optimization, symbol, tick, account,
                   *, now: float | None = None) -> tuple[dict, ...]:
    """Validate the current market and build pending LIMIT requests only."""
    now = time.time() if now is None else now
    if account is None or symbol is None or tick is None:
        raise ValueError("账户、品种或报价不可用")
    if not is_usc_account(account):
        raise ValueError("仅支持 USC 美分账户")
    if not getattr(account, "trade_allowed", False) or not getattr(account, "trade_expert", False):
        raise ValueError("账户未允许程序交易")
    if getattr(symbol, "trade_mode", None) != mt5.SYMBOL_TRADE_MODE_FULL:
        raise ValueError("该品种当前不允许完整交易")
    if not (getattr(symbol, "order_mode", 0) & ORDER_MODE_LIMIT):
        raise ValueError("该品种不支持 LIMIT 挂单")
    if not (getattr(symbol, "order_mode", 0) & ORDER_MODE_SL):
        raise ValueError("该品种不支持挂单止损")
    if result.take_profit is not None and not (getattr(symbol, "order_mode", 0) & ORDER_MODE_TP):
        raise ValueError("该品种不支持挂单止盈")
    if now - tick.time_msc / 1000 > MAX_QUOTE_AGE_SECONDS or tick.time_msc / 1000 > now + 5:
        raise ValueError("报价已过期或时间异常，请等待新报价")
    if tick.bid <= 0 or tick.ask <= 0 or tick.ask < tick.bid:
        raise ValueError("报价无效")
    if result.total_risk_usd > result.risk_cap_usd or not result.entries:
        raise ValueError("风险上限或档位无效")
    if sum((entry.risk_usd for entry in result.entries), Decimal(0)) != result.total_risk_usd:
        raise ValueError("分档风险与总风险不一致")
    if sum((entry.volume for entry in result.entries), Decimal(0)) != result.total_volume:
        raise ValueError("分档手数与总手数不一致")

    point = _number(symbol.point)
    price_step = _number(symbol.trade_tick_size or symbol.point)
    min_distance = _number(getattr(symbol, "trade_stops_level", 0)) * point
    volume_min = _number(symbol.volume_min)
    volume_max = _number(symbol.volume_max)
    volume_step = _number(symbol.volume_step)
    target = _number(result.take_profit) if result.take_profit is not None else None
    stop = result.entries[0].price + result.entries[0].stop_distance if result.side == "SELL" else result.entries[0].price - result.entries[0].stop_distance
    if result.side not in {"BUY", "SELL"}:
        raise ValueError("交易方向无效")
    if not _aligned(stop, price_step):
        raise ValueError("止损价不符合品种价格步进")
    if target is not None and (not target.is_finite() or target <= 0
                               or not _aligned(target, price_step)):
        raise ValueError("止盈价必须是符合品种价格步进的正数")
    order_type = mt5.ORDER_TYPE_SELL_LIMIT if result.side == "SELL" else mt5.ORDER_TYPE_BUY_LIMIT
    requests = []
    for entry in result.entries:
        entry_stop = entry.price + entry.stop_distance if result.side == "SELL" else entry.price - entry.stop_distance
        if entry_stop != stop:
            raise ValueError("各档止损价不一致")
        if entry.volume < volume_min or entry.volume > volume_max or not _aligned(entry.volume - volume_min, volume_step):
            raise ValueError(f"{entry.price} 的手数不符合品种限制")
        if not _aligned(entry.price, price_step):
            raise ValueError(f"{entry.price} 不符合价格步进")
        if result.side == "SELL":
            if entry.price <= _number(tick.ask) + min_distance:
                raise ValueError(f"{entry.price} 不是当前报价上方有效的 SELL LIMIT")
            if stop <= entry.price + min_distance:
                raise ValueError(f"{entry.price} 到止损价的距离不足")
            if target is not None and target >= entry.price - min_distance:
                raise ValueError(f"{entry.price} 到止盈价的距离不足或方向错误")
        else:
            if entry.price >= _number(tick.bid) - min_distance:
                raise ValueError(f"{entry.price} 不是当前报价下方有效的 BUY LIMIT")
            if stop >= entry.price - min_distance:
                raise ValueError(f"{entry.price} 到止损价的距离不足")
            if target is not None and target <= entry.price + min_distance:
                raise ValueError(f"{entry.price} 到止盈价的距离不足或方向错误")
        requests.append({
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol.name,
            "volume": float(entry.volume),
            "type": order_type,
            "price": float(entry.price),
            "sl": float(stop),
            "tp": float(target) if target is not None else 0.0,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
            "magic": MAGIC,
            "comment": "MT5 range plan",
        })
    volume_limit = _number(getattr(symbol, "volume_limit", 0) or 0)
    if volume_limit and result.total_volume > volume_limit:
        raise ValueError("计划总手数超过品种方向总量限制")
    return tuple(requests)


def plan_key(account, requests: tuple[dict, ...]) -> str:
    identity = {"login": account.login, "server": account.server,
                "orders": [{key: row[key] for key in ("symbol", "volume", "type", "price", "sl", "tp")}
                           for row in requests]}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def _same_order(row, request: dict) -> bool:
    return (row.symbol == request["symbol"] and row.type == request["type"]
            and _number(row.price_open) == _number(request["price"])
            and _number(row.volume_initial) == _number(request["volume"])
            and _number(row.sl) == _number(request["sl"])
            and _number(row.tp) == _number(request["tp"]))


def existing_duplicates(requests: tuple[dict, ...], *, api=mt5) -> tuple[int, ...]:
    _require_limit_requests(requests)
    active = api.orders_get(symbol=requests[0]["symbol"])
    if active is None:
        raise RuntimeError(f"无法读取现有挂单：{api.last_error()}")
    return tuple(row.ticket for row in active if any(_same_order(row, request) for request in requests))


def check_requests(requests: tuple[dict, ...], *, api=mt5) -> None:
    _require_limit_requests(requests)
    for index, request in enumerate(requests, 1):
        checked = api.order_check(dict(request))
        if checked is None or checked.retcode != 0:
            detail = api.last_error() if checked is None else f"{checked.retcode} {checked.comment}"
            raise RuntimeError(f"第 {index} 档 order_check 未通过：{detail}")


def send_checked(account, requests: tuple[dict, ...], ledger_dir: Path,
                 *, api=mt5) -> tuple[dict, ...]:
    """Check all, reserve an audit record, then send once per request.

    Caller must obtain a separate explicit confirmation immediately beforehand.
    Any failed or uncertain result stops the batch; this function never retries.
    """
    _require_limit_requests(requests)
    requests = tuple(dict(request) for request in requests)
    if not is_usc_account(account):
        raise RuntimeError("仅支持 USC 美分账户，已阻止发送")
    current = api.account_info()
    if current is None or current.login != account.login or current.server != account.server:
        raise RuntimeError("MT5 账户已切换，已阻止发送")
    if not is_usc_account(current):
        raise RuntimeError("当前账户不是 USC 美分账户，已阻止发送")
    duplicates = existing_duplicates(requests, api=api)
    if duplicates:
        raise RuntimeError(f"发现相同挂单 {duplicates}，已阻止重复发送")
    check_requests(requests, api=api)
    _require_limit_requests(requests)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    record_path = ledger_dir / f"{plan_key(account, requests)}.json"
    record = {"account": account.login, "server": account.server,
              "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "requests": requests, "results": [], "status": "reserved"}
    try:
        with record_path.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise RuntimeError("此配置已有发送记录；请核对 MT5 挂单，避免重复发送") from exc

    def save():
        temp = record_path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, record_path)

    placed_codes = {mt5.TRADE_RETCODE_PLACED, mt5.TRADE_RETCODE_DONE}
    for index, request in enumerate(requests, 1):
        current = api.account_info()
        if (current is None or current.login != account.login or current.server != account.server
                or not is_usc_account(current)):
            record["status"] = "stopped_account_changed"
            save()
            raise RuntimeError("发送过程中账户已切换或不再是 USC 美分账户，剩余挂单已停止")
        try:
            _require_limit_requests((request,))
        except ValueError:
            record["status"] = "stopped_invalid_request"
            save()
            raise
        result = api.order_send(dict(request))
        row = {"index": index, "retcode": getattr(result, "retcode", None),
               "order": getattr(result, "order", None),
               "deal": getattr(result, "deal", None),
               "comment": getattr(result, "comment", "无返回结果")}
        record["results"].append(row)
        if result is None or result.retcode not in placed_codes or not result.order:
            record["status"] = "stopped_uncertain"
            save()
            raise RuntimeError(f"第 {index} 档发送失败或状态不确定：{row}；请检查 MT5 和发送记录")
        record["status"] = "partial" if index < len(requests) else "placed"
        save()
    return tuple(record["results"])
