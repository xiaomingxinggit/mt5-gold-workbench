"""Preview and explicitly confirm protective SL/TP changes to MT5 positions.

The one-click protection target is *gross* profit in account currency: on a
USC account, USD 1 means USC 100. Commission and swap are not included.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path

import MetaTrader5 as mt5

from mt5_workbench.domain.account_policy import is_usc_account


MAX_QUOTE_AGE_SECONDS = 15
ORDER_MODE_SL = 16
ORDER_MODE_TP = 32
MAX_PROFIT_SEARCH_STEPS = 48
PROTECTION_REQUEST_INTERVAL_SECONDS = 2.0


@dataclass(frozen=True)
class ProtectionPlan:
    ticket: int
    symbol: str
    side: str
    volume: Decimal
    price_open: Decimal
    old_sl: Decimal
    old_tp: Decimal
    new_sl: Decimal
    new_tp: Decimal
    expected_profit_usc: Decimal | None
    request: dict


def _decimal(value, label: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(f"{label} 必须是有效数字") from exc
    if not number.is_finite():
        raise ValueError(f"{label} 必须是有限数字")
    return number


def _positive(value, label: str) -> Decimal:
    number = _decimal(value, label)
    if number <= 0:
        raise ValueError(f"{label} 必须大于 0")
    return number


def _side(position) -> str:
    if position.type == mt5.POSITION_TYPE_BUY:
        return "BUY"
    if position.type == mt5.POSITION_TYPE_SELL:
        return "SELL"
    raise ValueError(f"持仓 {position.ticket} 的方向无效")


def _kind(kind: str) -> str:
    if kind == "breakeven":
        return kind
    if kind in {"batch", "bulk"}:
        return "batch"
    raise ValueError("持仓保护操作无效")


def _account(expected=None, *, api=mt5):
    if expected is not None and not is_usc_account(expected):
        raise RuntimeError("仅支持 USC 美分账户，操作已停止")
    terminal = api.terminal_info()
    current = api.account_info()
    if terminal is None or not getattr(terminal, "connected", False) or not getattr(terminal, "trade_allowed", False):
        raise RuntimeError("MT5 终端未连接或未启用算法交易")
    if current is None or not getattr(current, "trade_allowed", False) or not getattr(current, "trade_expert", False):
        raise RuntimeError("账户未允许程序交易")
    if expected is not None:
        if (current.login, current.server) != (expected.login, expected.server):
            raise RuntimeError("MT5 账户已切换，操作已停止")
    if not is_usc_account(current):
        raise RuntimeError("当前账户不是 USC 美分账户，操作已停止")
    return current


def _market(symbol_name: str, *, api=mt5):
    symbol = api.symbol_info(symbol_name)
    tick = api.symbol_info_tick(symbol_name)
    if symbol is None or tick is None:
        raise RuntimeError(f"无法读取 {symbol_name} 的品种或报价")
    quote_time = _decimal(getattr(tick, "time_msc", 0), "报价时间") / Decimal(1000)
    now = Decimal(str(time.time()))
    if now - quote_time > MAX_QUOTE_AGE_SECONDS or quote_time > now + 5:
        raise RuntimeError(f"{symbol_name} 报价已过期或时间异常")
    bid = _positive(tick.bid, "Bid")
    ask = _positive(tick.ask, "Ask")
    if ask < bid:
        raise RuntimeError(f"{symbol_name} 报价无效")
    if getattr(symbol, "trade_mode", None) not in {
        mt5.SYMBOL_TRADE_MODE_FULL, mt5.SYMBOL_TRADE_MODE_CLOSEONLY,
    }:
        raise RuntimeError(f"{symbol_name} 当前不允许修改持仓保护价")
    point = _positive(symbol.point, "品种 point")
    step = _positive(getattr(symbol, "trade_tick_size", 0) or symbol.point, "品种 tick size")
    try:
        digits = int(symbol.digits)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{symbol_name} 报价精度无效") from exc
    if digits < 0 or digits > 12 or step % (Decimal(10) ** -digits):
        raise ValueError(f"{symbol_name} tick size 与 digits 不兼容")
    stops = _decimal(getattr(symbol, "trade_stops_level", 0) or 0, "stops level")
    freeze = _decimal(getattr(symbol, "trade_freeze_level", 0) or 0, "freeze level")
    if stops < 0 or freeze < 0:
        raise ValueError(f"{symbol_name} 停损或冻结距离无效")
    # One tick beyond the larger broker boundary avoids equality at a freeze
    # boundary and also keeps stops strictly on the protective side of quote.
    margin = max(stops, freeze) * point + step
    return symbol, bid, ask, step, digits, margin


def _index(price: Decimal, step: Decimal, rounding) -> int:
    return int((price / step).to_integral_value(rounding=rounding))


def _price(index: int, step: Decimal, digits: int) -> Decimal:
    return (Decimal(index) * step).quantize(Decimal(10) ** -digits)


def _validate_price(value: Decimal, step: Decimal, digits: int, label: str) -> None:
    try:
        finite_for_mt5 = math.isfinite(float(value))
    except (OverflowError, ValueError):
        finite_for_mt5 = False
    if (not finite_for_mt5 or value <= 0 or value % step
            or value != value.quantize(Decimal(10) ** -digits)):
        raise ValueError(f"{label} 必须是符合品种 tick size / digits 的正数价格")


def _validate_levels(side: str, sl: Decimal, tp: Decimal, bid: Decimal,
                     ask: Decimal, margin: Decimal, ticket: int) -> None:
    if side == "BUY":
        if sl and not sl <= bid - margin:
            raise ValueError(f"持仓 {ticket} 止损价距 Bid 不足或方向错误")
        if tp and not tp >= bid + margin:
            raise ValueError(f"持仓 {ticket} 止盈价距 Bid 不足或方向错误")
    else:
        if sl and not sl >= ask + margin:
            raise ValueError(f"持仓 {ticket} 止损价距 Ask 不足或方向错误")
        if tp and not tp <= ask - margin:
            raise ValueError(f"持仓 {ticket} 止盈价距 Ask 不足或方向错误")


def _profit(position, side: str, exit_price: Decimal, *, api=mt5) -> Decimal:
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    value = api.order_calc_profit(order_type, position.symbol, float(position.volume),
                                  float(position.price_open), float(exit_price))
    if value is None:
        raise RuntimeError(f"持仓 {position.ticket} 无法计算收益：{api.last_error()}")
    result = _decimal(value, "计算收益")
    return result


def _breakeven_stop(position, side: str, target_usc: Decimal, bid: Decimal,
                    ask: Decimal, step: Decimal, digits: int, margin: Decimal,
                    *, api=mt5) -> tuple[Decimal, Decimal]:
    opened = _positive(position.price_open, "开仓价")
    if side == "BUY":
        low = _index(opened, step, ROUND_FLOOR) + 1
        high = _index(bid - margin, step, ROUND_FLOOR)
        if low > high:
            raise ValueError(f"持仓 {position.ticket} 当前浮盈不足，无法锁定目标利润")
        furthest = _price(high, step, digits)
    else:
        low = _index(ask + margin, step, ROUND_CEILING)
        high = _index(opened, step, ROUND_CEILING) - 1
        if low > high:
            raise ValueError(f"持仓 {position.ticket} 当前浮盈不足，无法锁定目标利润")
        furthest = _price(low, step, digits)
    max_profit = _profit(position, side, furthest, api=api)
    if max_profit < target_usc:
        raise ValueError(f"持仓 {position.ticket} 当前浮盈不足，无法锁定 {target_usc} USC")
    open_profit = _profit(position, side, opened, api=api)
    if max_profit <= open_profit:
        raise RuntimeError(f"持仓 {position.ticket} 收益计算结果异常")

    # order_calc_profit is usually linear in price. Estimate first, check the
    # adjacent tick, and fall back to a bounded binary search if needed.
    ratio = (target_usc - open_profit) / (max_profit - open_profit)
    estimate = opened + ratio * (furthest - opened)
    if side == "BUY":
        candidate = min(high, max(low, _index(estimate, step, ROUND_CEILING)))
    else:
        candidate = min(high, max(low, _index(estimate, step, ROUND_FLOOR)))
    first, last = low, high

    candidate_profit = _profit(position, side, _price(candidate, step, digits), api=api)
    if side == "BUY":
        if candidate_profit >= target_usc:
            previous = candidate - 1
            if previous < low or _profit(position, side, _price(previous, step, digits), api=api) < target_usc:
                return _price(candidate, step, digits), candidate_profit
            last = previous
        else:
            first = candidate + 1
        for _ in range(MAX_PROFIT_SEARCH_STEPS):
            if first >= last:
                break
            mid = (first + last) // 2
            if _profit(position, side, _price(mid, step, digits), api=api) >= target_usc:
                last = mid
            else:
                first = mid + 1
        if first < last:
            raise RuntimeError(f"持仓 {position.ticket} 收益求价未在上限内收敛")
        answer = first
    else:
        if candidate_profit >= target_usc:
            next_index = candidate + 1
            if next_index > high or _profit(position, side, _price(next_index, step, digits), api=api) < target_usc:
                return _price(candidate, step, digits), candidate_profit
            first = next_index
        else:
            last = candidate - 1
        for _ in range(MAX_PROFIT_SEARCH_STEPS):
            if first >= last:
                break
            mid = (first + last + 1) // 2
            if _profit(position, side, _price(mid, step, digits), api=api) >= target_usc:
                first = mid
            else:
                last = mid - 1
        if first < last:
            raise RuntimeError(f"持仓 {position.ticket} 收益求价未在上限内收敛")
        answer = first
    stop = _price(answer, step, digits)
    profit = _profit(position, side, stop, api=api)
    if profit < target_usc:
        raise RuntimeError(f"持仓 {position.ticket} 收益计算结果不稳定")
    return stop, profit


def _inputs(kind: str, amount_usd, sl, tp):
    kind = _kind(kind)
    if kind == "breakeven":
        if sl is not None or tp is not None:
            raise ValueError("推保本不能同时指定批量止盈止损价")
        amount = _positive(1 if amount_usd is None else amount_usd, "锁定利润 USD")
        return kind, amount * 100, None, None
    if amount_usd is not None:
        raise ValueError("批量设置不能指定推保本利润")
    stop = None if sl is None else _positive(sl, "止损价")
    take = None if tp is None else _positive(tp, "止盈价")
    if stop is None and take is None:
        raise ValueError("请填写止盈价或止损价")
    return kind, None, stop, take


def target_signature(rows) -> tuple:
    """Snapshot every target, including SL/TP, before a confirmed change."""
    result = tuple(sorted((int(row.ticket), str(row.symbol), int(row.type),
                           str(_decimal(row.volume, "手数")),
                           str(_decimal(row.price_open, "开仓价")),
                           str(_decimal(getattr(row, "sl", 0) or 0, "止损价")),
                           str(_decimal(getattr(row, "tp", 0) or 0, "止盈价")),
                           getattr(row, "identifier", None),
                           getattr(row, "time_update_msc", None))
                          for row in rows))
    if len({item[0] for item in result}) != len(result):
        raise ValueError("持仓 ticket 重复")
    return result


def load_targets(scope: str, symbol_name: str, *, api=mt5) -> tuple:
    if scope not in {"symbol", "account"}:
        raise ValueError("持仓保护范围无效")
    rows = api.positions_get(**({"symbol": symbol_name} if scope == "symbol" else {}))
    if rows is None:
        raise RuntimeError(f"无法读取持仓：{api.last_error()}")
    rows = tuple(sorted(rows, key=lambda row: row.ticket))
    target_signature(rows)
    return rows


def select_targets(rows, tickets=None) -> tuple:
    """Resolve an explicit selection; closed/missing tickets never become all."""
    rows = tuple(rows)
    if tickets is None:
        return rows
    if not isinstance(tickets, (list, tuple)) or not tickets:
        raise ValueError("请至少勾选一笔持仓")
    try:
        requested = tuple(int(str(ticket)) for ticket in tickets)
    except (ValueError, TypeError) as exc:
        raise ValueError("持仓选择无效") from exc
    if any(ticket <= 0 for ticket in requested) or len(set(requested)) != len(requested):
        raise ValueError("持仓选择无效或重复")
    selected = tuple(row for row in rows if row.ticket in requested)
    if {row.ticket for row in selected} != set(requested):
        raise RuntimeError("勾选持仓已关闭或不在当前范围，请刷新后重新选择")
    return selected


def prepare_protection(kind: str, positions, *, amount_usd=None, sl=None,
                       tp=None, api=mt5) -> tuple[ProtectionPlan, ...]:
    """Build preview-only plans. No order_check or order_send is called."""
    kind, target_usc, bulk_sl, bulk_tp = _inputs(kind, amount_usd, sl, tp)
    _account(api=api)
    positions = tuple(sorted(positions, key=lambda row: row.ticket))
    if not positions:
        raise ValueError("所选范围内没有持仓")
    target_signature(positions)
    if kind == "batch" and len({row.symbol for row in positions}) != 1:
        raise ValueError("账户范围包含多个品种，不能使用统一绝对价格批量设置")
    plans = []
    for position in positions:
        side = _side(position)
        volume = _positive(position.volume, "手数")
        opened = _positive(position.price_open, "开仓价")
        old_sl = _decimal(getattr(position, "sl", 0) or 0, "原止损价")
        old_tp = _decimal(getattr(position, "tp", 0) or 0, "原止盈价")
        if old_sl < 0 or old_tp < 0:
            raise ValueError(f"持仓 {position.ticket} 原止盈止损价无效")
        symbol, bid, ask, step, digits, margin = _market(position.symbol, api=api)
        order_mode = getattr(symbol, "order_mode", 0)
        if kind == "breakeven":
            if not order_mode & ORDER_MODE_SL:
                raise ValueError(f"{position.symbol} 不支持止损")
            if old_sl and ((side == "BUY" and old_sl > opened)
                           or (side == "SELL" and old_sl < opened)):
                if _profit(position, side, old_sl, api=api) >= target_usc:
                    continue
            new_sl, expected_profit = _breakeven_stop(
                position, side, target_usc, bid, ask, step, digits, margin, api=api,
            )
            if old_sl and ((side == "BUY" and old_sl >= new_sl)
                           or (side == "SELL" and old_sl <= new_sl)):
                continue
            new_tp = old_tp
        else:
            new_sl = old_sl if bulk_sl is None else bulk_sl
            new_tp = old_tp if bulk_tp is None else bulk_tp
            expected_profit = None
            if new_sl == old_sl and new_tp == old_tp:
                continue
            if new_sl != old_sl and not order_mode & ORDER_MODE_SL:
                raise ValueError(f"{position.symbol} 不支持止损")
            if new_tp != old_tp and not order_mode & ORDER_MODE_TP:
                raise ValueError(f"{position.symbol} 不支持止盈")
        if new_sl:
            _validate_price(new_sl, step, digits, "止损价")
        if new_tp:
            _validate_price(new_tp, step, digits, "止盈价")
        _validate_levels(side, new_sl, new_tp, bid, ask, margin, position.ticket)
        request = {"action": mt5.TRADE_ACTION_SLTP, "position": int(position.ticket),
                   "symbol": str(position.symbol), "sl": float(new_sl),
                   "tp": float(new_tp)}
        plans.append(ProtectionPlan(
            int(position.ticket), str(position.symbol), side, volume, opened,
            old_sl, old_tp, new_sl, new_tp, expected_profit, request,
        ))
    return tuple(plans)


def _write_record(path: Path, record: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def execute_protection_batch(kind: str, scope: str, symbol_name: str,
                             expected_account, preview_rows, preview_plans,
                             record_dir: Path, *, amount_usd=None, sl=None,
                             tp=None, selected_tickets=None, cancelled=None,
                             progress=None, request_interval_seconds=PROTECTION_REQUEST_INTERVAL_SECONDS,
                             wait_fn=time.sleep, api=mt5) -> tuple[dict, ...]:
    """Execute one confirmed preview, stop at first failure, never retry."""
    canonical_kind, _, _, _ = _inputs(kind, amount_usd, sl, tp)
    preview_rows = tuple(preview_rows)
    preview_plans = tuple(preview_plans)
    if not preview_rows or not preview_plans:
        raise ValueError("没有可修改的持仓")
    if not math.isfinite(request_interval_seconds) or request_interval_seconds < 0:
        raise ValueError("发送间隔无效")

    def check_cancelled():
        if cancelled is not None and cancelled.is_set():
            raise RuntimeError("批量修改已停止；已发送的修改请在 MT5 核对")

    check_cancelled()
    _account(expected_account, api=api)
    current_rows = select_targets(load_targets(scope, symbol_name, api=api), selected_tickets)
    snapshot = target_signature(preview_rows)
    if target_signature(current_rows) != snapshot:
        raise RuntimeError("持仓或止盈止损价已变化，请重新预览")
    fresh_plans = prepare_protection(canonical_kind, current_rows, amount_usd=amount_usd,
                                     sl=sl, tp=tp, api=api)
    if fresh_plans != preview_plans:
        raise RuntimeError("保护价或报价已变化，请重新预览")
    if not fresh_plans:
        raise ValueError("没有可修改的持仓")
    check_cancelled()

    record_dir = Path(record_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    identity = {"account": expected_account.login, "server": expected_account.server,
                "kind": canonical_kind, "scope": scope, "symbol": symbol_name,
                "targets": snapshot, "requests": [plan.request for plan in fresh_plans]}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
    record_path = record_dir / f"protection-{digest}.json"
    record = {**identity, "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "results": [], "status": "reserved"}
    try:
        with record_path.open("x", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RuntimeError("此保护配置已有执行记录，请先核对 MT5，避免重复发送") from exc

    original_by_ticket = {row.ticket: row for row in preview_rows}
    for index, preview_plan in enumerate(fresh_plans, 1):
        try:
            if index > 1 and request_interval_seconds:
                if cancelled is not None:
                    cancelled.wait(request_interval_seconds)
                else:
                    wait_fn(request_interval_seconds)
            check_cancelled()
            _account(expected_account, api=api)
            live_rows = load_targets(scope, symbol_name, api=api)
            live = next((row for row in live_rows if row.ticket == preview_plan.ticket), None)
            original = original_by_ticket[preview_plan.ticket]
            if live is None or target_signature((live,)) != target_signature((original,)):
                raise RuntimeError(f"第 {index} 笔持仓或止盈止损价已变化，请核对 MT5")
            live_plans = prepare_protection(canonical_kind, (live,), amount_usd=amount_usd,
                                            sl=sl, tp=tp, api=api)
            if len(live_plans) != 1 or live_plans[0] != preview_plan:
                raise RuntimeError(f"第 {index} 笔保护价或报价已变化，请核对 MT5")
            request = dict(preview_plan.request)
            checked = api.order_check(dict(request))
            if checked is None or getattr(checked, "retcode", None) != 0:
                detail = api.last_error() if checked is None else f"{checked.retcode} {getattr(checked, 'comment', '')}"
                raise ValueError(f"第 {index} 笔 order_check 未通过：{detail}")
            # A check call can take time; catch an account switch and a changed
            # ticket before the irreversible send. Send a fresh dict in case
            # the API mutated the order_check argument.
            _account(expected_account, api=api)
            last_rows = load_targets(scope, symbol_name, api=api)
            last = next((row for row in last_rows if row.ticket == preview_plan.ticket), None)
            if last is None or target_signature((last,)) != target_signature((original,)):
                raise RuntimeError(f"第 {index} 笔持仓或止盈止损价已变化，请核对 MT5")
            check_cancelled()
        except Exception as exc:
            record["status"] = "stopped_check"
            record["results"].append({"ticket": preview_plan.ticket, "error": str(exc)})
            _write_record(record_path, record)
            error_type = ValueError if isinstance(exc, ValueError) else RuntimeError
            raise error_type(f"已完成 {index - 1}/{len(fresh_plans)} 笔；{exc}") from exc
        try:
            result = api.order_send(dict(request))
        except Exception as exc:
            record["results"].append({"ticket": preview_plan.ticket, "error": str(exc)})
            record["status"] = "stopped_uncertain"
            _write_record(record_path, record)
            raise RuntimeError(f"第 {index} 笔发送状态不确定；已停止，先核对 MT5") from exc
        row = {"ticket": preview_plan.ticket, "symbol": preview_plan.symbol,
               "sl": request["sl"], "tp": request["tp"],
               "retcode": getattr(result, "retcode", None),
               "order": getattr(result, "order", None),
               "deal": getattr(result, "deal", None),
               "comment": getattr(result, "comment", "无返回结果")}
        record["results"].append(row)
        if result is None or getattr(result, "retcode", None) != mt5.TRADE_RETCODE_DONE:
            limited = result is not None and result.retcode == mt5.TRADE_RETCODE_TOO_MANY_REQUESTS
            record["status"] = "stopped_rate_limit" if limited else "stopped_uncertain"
            _write_record(record_path, record)
            if limited:
                raise RuntimeError(f"已完成 {index - 1}/{len(fresh_plans)} 笔；服务器限制请求频率（10024）。"
                                   f"持仓 {preview_plan.ticket} 修改被拒绝，后续已停止；稍后刷新并重新预览未完成的持仓。")
            raise RuntimeError(f"第 {index} 笔发送失败或状态不确定：{row}；已停止，先核对 MT5")
        record["status"] = "partial" if index < len(fresh_plans) else "done"
        _write_record(record_path, record)
        if progress is not None:
            progress(index, len(fresh_plans), preview_plan.ticket)
    return tuple(record["results"])
