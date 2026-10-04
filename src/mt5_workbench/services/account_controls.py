"""Confirmed bulk MT5 position close and pending-order cancellation."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import MetaTrader5 as mt5

from mt5_workbench.domain.account_policy import is_usc_account


MAX_QUOTE_AGE_SECONDS = 15
FILL_FOK_FLAG = 1
FILL_IOC_FLAG = 2
MAGIC = 2601002


def require_account(expected, *, api=mt5):
    if not is_usc_account(expected):
        raise RuntimeError("仅支持 USC 美分账户，操作已停止")
    terminal = api.terminal_info()
    current = api.account_info()
    if terminal is None or not terminal.connected or not terminal.trade_allowed:
        raise RuntimeError("MT5 终端未连接或未启用算法交易")
    if current is None or not current.trade_allowed or not current.trade_expert:
        raise RuntimeError("账户未允许程序交易")
    if (current.login, current.server) != (expected.login, expected.server):
        raise RuntimeError("MT5 账户已切换，操作已停止")
    if not is_usc_account(current):
        raise RuntimeError("当前账户不是 USC 美分账户，操作已停止")
    return current


def load_targets(kind: str, scope: str, symbol_name: str, *, api=mt5):
    if kind not in {"close", "remove"} or scope not in {"symbol", "account"}:
        raise ValueError("控制面板操作或范围无效")
    arguments = {"symbol": symbol_name} if scope == "symbol" else {}
    rows = (api.positions_get(**arguments) if kind == "close"
            else api.orders_get(**arguments))
    if rows is None:
        raise RuntimeError(f"无法读取持仓或挂单：{api.last_error()}")
    return tuple(sorted(rows, key=lambda row: row.ticket))


def target_signature(kind: str, rows) -> tuple:
    if kind == "close":
        return tuple((row.ticket, row.symbol, row.type, str(row.volume),
                      str(row.price_open)) for row in rows)
    if kind == "remove":
        return tuple((row.ticket, row.symbol, row.type, str(row.volume_initial),
                      str(row.price_open), str(row.sl), str(row.tp)) for row in rows)
    raise ValueError("未知操作")


def _fill_policy(symbol):
    flags = symbol.filling_mode
    if flags & FILL_FOK_FLAG:
        return mt5.ORDER_FILLING_FOK
    if flags & FILL_IOC_FLAG:
        return mt5.ORDER_FILLING_IOC
    if symbol.trade_exemode != mt5.SYMBOL_TRADE_EXECUTION_MARKET:
        return mt5.ORDER_FILLING_RETURN
    raise ValueError(f"{symbol.name} 没有可用的平仓成交模式")


def close_request(position, deviation_points: int, *, api=mt5, now=None):
    if not isinstance(deviation_points, int) or not 1 <= deviation_points <= 1000:
        raise ValueError("最大偏差点数必须是 1～1000 的整数")
    symbol = api.symbol_info(position.symbol)
    tick = api.symbol_info_tick(position.symbol)
    if symbol is None or tick is None:
        raise RuntimeError(f"无法读取 {position.symbol} 的品种或报价")
    now = time.time() if now is None else now
    if now - tick.time_msc / 1000 > MAX_QUOTE_AGE_SECONDS or tick.time_msc / 1000 > now + 5:
        raise RuntimeError(f"{position.symbol} 报价已过期")
    if tick.bid <= 0 or tick.ask <= 0 or tick.ask < tick.bid:
        raise RuntimeError(f"{position.symbol} 报价无效")
    if symbol.trade_mode not in {mt5.SYMBOL_TRADE_MODE_CLOSEONLY,
                                 mt5.SYMBOL_TRADE_MODE_FULL}:
        raise RuntimeError(f"{position.symbol} 当前不允许平仓")
    if position.type == mt5.POSITION_TYPE_BUY:
        order_type, price = mt5.ORDER_TYPE_SELL, tick.bid
    elif position.type == mt5.POSITION_TYPE_SELL:
        order_type, price = mt5.ORDER_TYPE_BUY, tick.ask
    else:
        raise ValueError(f"持仓 {position.ticket} 的方向无效")
    if position.volume <= 0:
        raise ValueError(f"持仓 {position.ticket} 手数无效")
    request = {"action": mt5.TRADE_ACTION_DEAL,
               "symbol": position.symbol,
               "volume": float(position.volume),
               "type": order_type,
               "position": position.ticket,
               "deviation": deviation_points,
               "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": _fill_policy(symbol),
               "magic": MAGIC,
               "comment": "MT5 panel close"}
    if symbol.trade_exemode != mt5.SYMBOL_TRADE_EXECUTION_MARKET:
        request["price"] = price
    return request


def remove_request(order):
    return {"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket,
            "magic": MAGIC, "comment": "MT5 panel remove"}


def _write_record(path: Path, record: dict):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def execute_batch(kind: str, scope: str, symbol_name: str, expected_account,
                  preview_rows, deviation_points: int, record_dir: Path,
                  *, api=mt5) -> tuple[dict, ...]:
    """Execute only the previewed targets, one by one; never auto retry."""
    if kind not in {"close", "remove"} or not preview_rows:
        raise ValueError("没有可处理的目标")
    require_account(expected_account, api=api)
    current_rows = load_targets(kind, scope, symbol_name, api=api)
    if target_signature(kind, current_rows) != target_signature(kind, preview_rows):
        raise RuntimeError("持仓或挂单已变化，请重新预览")
    if kind == "close":
        requests = [close_request(row, deviation_points, api=api) for row in current_rows]
        for index, request in enumerate(requests, 1):
            checked = api.order_check(request)
            if checked is None or checked.retcode != 0:
                detail = api.last_error() if checked is None else f"{checked.retcode} {checked.comment}"
                raise RuntimeError(f"第 {index} 笔平仓预检未通过：{detail}")

    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid4().hex}.json"
    record = {"kind": kind, "scope": scope, "symbol": symbol_name,
              "account": expected_account.login, "server": expected_account.server,
              "targets": target_signature(kind, current_rows),
              "results": [], "status": "started"}
    _write_record(record_path, record)
    for index, preview_row in enumerate(current_rows, 1):
        try:
            require_account(expected_account, api=api)
        except RuntimeError:
            record["status"] = "stopped_account_invalid"
            _write_record(record_path, record)
            raise
        live_rows = load_targets(kind, scope, symbol_name, api=api)
        live = next((row for row in live_rows if row.ticket == preview_row.ticket), None)
        if live is None or target_signature(kind, (live,)) != target_signature(kind, (preview_row,)):
            record["status"] = "stopped_changed"
            _write_record(record_path, record)
            raise RuntimeError(f"第 {index} 笔目标已变化；已停止，先核对 MT5")
        if kind == "close":
            request = close_request(live, deviation_points, api=api)
            checked = api.order_check(request)
            if checked is None or checked.retcode != 0:
                record["status"] = "stopped_check"
                _write_record(record_path, record)
                raise RuntimeError(f"第 {index} 笔平仓预检失败；已停止，先核对 MT5")
        else:
            request = remove_request(live)
        try:
            result = api.order_send(request)
        except Exception as exc:
            record["results"].append({"ticket": live.ticket, "error": str(exc)})
            record["status"] = "stopped_uncertain"
            _write_record(record_path, record)
            raise RuntimeError(f"第 {index} 笔发送状态不确定；已停止，先核对 MT5") from exc
        row = {"ticket": live.ticket, "symbol": live.symbol,
               "volume": getattr(live, "volume", getattr(live, "volume_initial", None)),
               "retcode": getattr(result, "retcode", None),
               "order": getattr(result, "order", None),
               "deal": getattr(result, "deal", None),
               "comment": getattr(result, "comment", "无返回结果")}
        record["results"].append(row)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            record["status"] = "stopped_uncertain"
            _write_record(record_path, record)
            raise RuntimeError(f"第 {index} 笔返回失败或状态不确定：{row}；已停止，先核对 MT5")
        record["status"] = "partial" if index < len(current_rows) else "done"
        _write_record(record_path, record)
    return tuple(record["results"])
