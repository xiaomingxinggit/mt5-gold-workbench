"""Read-only MT5 position snapshots and journal result reconciliation.

The journal links a position's stable ``identifier`` (``DEAL_POSITION_ID``),
not its possibly changing ticket. All money in this module is in the MT5
account currency, USC. No trading function is called here.

Reference: https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import MetaTrader5 as mt5

from mt5_workbench.domain.journal import PositionSnapshot


JOURNAL_SYMBOL = "XAUUSDc"


@dataclass(frozen=True)
class JournalSyncResult:
    """Number of journal links updated and recoverable MT5 read errors."""

    updated_count: int
    errors: tuple[str, ...] = ()


def _field(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 无效") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} 无效")
    return result


def _optional_price(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    price = _decimal(value, field_name)
    return price if price > 0 else None


def _utc_time(row: Any, name: str) -> datetime:
    milliseconds = _field(row, f"{name}_msc")
    parsed_milliseconds = (_decimal(milliseconds, f"{name}_msc")
                           if milliseconds is not None else Decimal("0"))
    seconds = (parsed_milliseconds / 1000 if parsed_milliseconds > 0
               else _decimal(_field(row, name), name))
    if seconds <= 0:
        raise ValueError(f"{name} 无效")
    try:
        return datetime.fromtimestamp(float(seconds), timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"{name} 无效") from exc


def _last_error(api: Any) -> str:
    try:
        return str(api.last_error())
    except Exception:
        return "未知 MT5 错误"


def _require_account(account_key: tuple[int, str], api: Any) -> None:
    if (not isinstance(account_key, tuple) or len(account_key) != 2
            or not isinstance(account_key[0], int) or account_key[0] <= 0
            or not isinstance(account_key[1], str) or not account_key[1]):
        raise ValueError("行情日志的账户标识无效")
    try:
        account = api.account_info()
    except Exception as exc:
        raise RuntimeError(f"无法读取 MT5 账户：{exc}") from exc
    if account is None:
        raise RuntimeError(f"无法读取 MT5 账户：{_last_error(api)}")
    if str(_field(account, "currency", "")).strip().upper() != "USC":
        raise RuntimeError("行情日志仅支持 USC 美分账户")
    if (_field(account, "login"), _field(account, "server")) != account_key:
        raise RuntimeError("MT5 账户已切换，行情日志读取已停止")


def _position_id(row: Any) -> int:
    identifier = _field(row, "identifier")
    try:
        raw_id = (identifier if identifier is not None and int(identifier) > 0
                  else _field(row, "ticket"))
        position_id = int(raw_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("MT5 持仓编号无效") from exc
    if position_id <= 0:
        raise ValueError("MT5 持仓编号无效")
    return position_id


def _position_snapshot(row: Any, api: Any,
                       account_key: tuple[int, str] | None = None) -> PositionSnapshot:
    symbol = str(_field(row, "symbol", ""))
    if symbol != JOURNAL_SYMBOL:
        raise ValueError(f"行情日志只支持 {JOURNAL_SYMBOL} 持仓")
    position_type = _field(row, "type")
    if position_type == getattr(api, "POSITION_TYPE_BUY", 0):
        side = "BUY"
    elif position_type == getattr(api, "POSITION_TYPE_SELL", 1):
        side = "SELL"
    else:
        raise ValueError("MT5 持仓方向无效")
    try:
        ticket = int(_field(row, "ticket"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("MT5 持仓订单号无效") from exc
    volume = _decimal(_field(row, "volume"), "持仓手数")
    price_open = _decimal(_field(row, "price_open"), "开仓价")
    if ticket <= 0 or volume <= 0 or price_open <= 0:
        raise ValueError("MT5 持仓数据无效")
    # MT5's current position exposes profit and swap, but not commission.
    floating_usc = (_decimal(_field(row, "profit"), "浮动盈亏")
                    + _decimal(_field(row, "swap", 0), "浮动隔夜费"))
    return PositionSnapshot(
        position_id=_position_id(row),
        ticket=ticket,
        symbol=symbol,
        side=side,
        volume=volume,
        price_open=price_open,
        opened_at=_utc_time(row, "time"),
        sl=_optional_price(_field(row, "sl"), "止损价"),
        tp=_optional_price(_field(row, "tp"), "止盈价"),
        floating_usc=floating_usc,
        account_key=account_key,
    )


def load_open_positions(account_key: tuple[int, str], symbol: str = JOURNAL_SYMBOL,
                        *, api: Any = mt5) -> tuple[PositionSnapshot, ...]:
    """Read current XAUUSDc positions from the expected USC account."""
    if symbol != JOURNAL_SYMBOL:
        raise ValueError(f"行情日志只支持 {JOURNAL_SYMBOL}")
    _require_account(account_key, api)
    try:
        rows = api.positions_get(symbol=JOURNAL_SYMBOL)
    except Exception as exc:
        _require_account(account_key, api)
        raise RuntimeError(f"读取持仓异常：{exc}") from exc
    _require_account(account_key, api)
    if rows is None:
        raise RuntimeError(f"读取持仓失败：{_last_error(api)}")
    return tuple(sorted((_position_snapshot(row, api, account_key) for row in rows),
                        key=lambda item: (item.opened_at, item.position_id)))


def _deal_cashflow(deal: Any) -> Decimal:
    return sum((_decimal(_field(deal, name), f"历史{name}")
                for name in ("profit", "swap", "commission", "fee")), Decimal("0"))


def _validated_deals(position_id: int, deals: tuple[Any, ...]
                     ) -> tuple[tuple[datetime, Any], ...]:
    ordered = []
    for deal in deals:
        deal_position = _field(deal, "position_id")
        if deal_position is not None and int(deal_position) != position_id:
            raise ValueError("历史成交的持仓编号不匹配")
        deal_symbol = _field(deal, "symbol")
        if deal_symbol is not None and deal_symbol != JOURNAL_SYMBOL:
            raise ValueError("历史成交的品种不匹配")
        ordered.append((_utc_time(deal, "time"), deal))
    return tuple(sorted(ordered, key=lambda pair: pair[0]))


def _link_result(link: Any, ordered: tuple[tuple[datetime, Any], ...],
                 current: PositionSnapshot | None, api: Any
                 ) -> tuple[Decimal, datetime] | None:
    """Resolve the stage captured by a post, never a later reversed stage.

    A netting reversal keeps POSITION_IDENTIFIER. If the post was made after a
    reversal, the reversal deal mixes the old close with the new opening fee;
    its new-stage cashflow cannot be allocated reliably, so leave it pending.
    """
    linked_at = _field(link, "linked_at") or _field(link, "opened_at")
    if linked_at is None:
        raise ValueError("关联时间缺失")
    linked_at = linked_at.astimezone(timezone.utc)
    reversal_entry = getattr(api, "DEAL_ENTRY_INOUT", 2)
    exit_entries = {getattr(api, "DEAL_ENTRY_OUT", 1), reversal_entry,
                    getattr(api, "DEAL_ENTRY_OUT_BY", 3)}
    for index, (when, deal) in enumerate(ordered):
        if _field(deal, "entry") != reversal_entry:
            continue
        if when <= linked_at:
            return None
        # Use deal order as the boundary. A later new-stage deal can share the
        # same second when the broker provides no millisecond timestamp.
        stage = ordered[:index + 1]
        return sum((_deal_cashflow(item) for _time, item in stage),
                   Decimal("0")), when
    if current is not None:
        return None
    exits = [when for when, deal in ordered if _field(deal, "entry") in exit_entries]
    if not exits:
        return None
    return sum((_deal_cashflow(deal) for _when, deal in ordered),
               Decimal("0")), max(exits)


def sync_closed_positions(repo: Any, account_key: tuple[int, str],
                          *, api: Any = mt5) -> JournalSyncResult:
    """Resolve journal links whose positions fully closed since posting.

    A partial close keeps the position open and must not finalize a post. MT5
    history errors leave the link pending for a later refresh.
    """
    _require_account(account_key, api)
    links = repo.open_links(account_key)
    try:
        rows = api.positions_get(symbol=JOURNAL_SYMBOL)
    except Exception as exc:
        _require_account(account_key, api)
        return JournalSyncResult(0, (f"读取持仓异常：{exc}",))
    _require_account(account_key, api)
    if rows is None:
        return JournalSyncResult(0, (f"读取持仓失败：{_last_error(api)}",))

    if any(_field(row, "symbol") != JOURNAL_SYMBOL for row in rows):
        return JournalSyncResult(0, ("MT5 返回的持仓品种与 XAUUSDc 不符",))
    try:
        active = {_position_id(row): _position_snapshot(row, api, account_key)
                  for row in rows}
    except ValueError as exc:
        return JournalSyncResult(0, (f"MT5 持仓数据无效：{exc}",))
    errors: list[str] = []
    by_id: dict[int, list[Any]] = {}
    for link in links:
        if _field(link, "symbol") != JOURNAL_SYMBOL:
            errors.append(f"关联持仓 {_field(link, 'position_id')} 不是 {JOURNAL_SYMBOL}")
            continue
        if _field(link, "account_key") not in (None, account_key):
            errors.append(f"关联持仓 {_field(link, 'position_id')} 的账户不匹配")
            continue
        try:
            position_id = int(_field(link, "position_id"))
        except (TypeError, ValueError, OverflowError):
            errors.append("行情日志存在无效持仓编号")
            continue
        if position_id <= 0:
            errors.append("行情日志存在无效持仓编号")
            continue
        by_id.setdefault(position_id, []).append(link)

    resolved: list[tuple[int, int, Decimal, datetime]] = []
    unverified: list[tuple[int, int]] = []
    for position_id, group in by_id.items():
        current = active.get(position_id)
        changed = [link for link in group if current is None or
                   current.ticket != _field(link, "ticket") or
                   current.side != _field(link, "side")]
        if not changed:
            continue
        try:
            deals = api.history_deals_get(position=position_id)
        except Exception as exc:
            _require_account(account_key, api)
            errors.append(f"持仓 {position_id} 的历史成交读取异常：{exc}")
            unverified.extend((int(_field(link, "post_id")), position_id)
                              for link in changed)
            continue
        _require_account(account_key, api)
        if deals is None:
            errors.append(f"持仓 {position_id} 的历史成交读取失败：{_last_error(api)}")
            unverified.extend((int(_field(link, "post_id")), position_id)
                              for link in changed)
            continue
        try:
            ordered = _validated_deals(position_id, tuple(deals))
        except (TypeError, ValueError) as exc:
            errors.append(f"持仓 {position_id} 的历史成交无效：{exc}")
            unverified.extend((int(_field(link, "post_id")), position_id)
                              for link in changed)
            continue
        for link in changed:
            post_id = int(_field(link, "post_id"))
            try:
                result = _link_result(link, ordered, current, api)
            except (TypeError, ValueError, AttributeError) as exc:
                errors.append(f"持仓 {position_id} 的历史成交无效：{exc}")
                continue
            if result is not None:
                resolved.append((post_id, position_id, *result))
            else:
                unverified.append((post_id, position_id))
                if current is None and not any(
                        _field(deal, "entry") == getattr(api, "DEAL_ENTRY_INOUT", 2)
                        for _when, deal in ordered):
                    errors.append(f"持仓 {position_id} 尚无平仓成交，稍后重试")

    # Complete all MT5 reads and verify identity again before touching SQLite.
    _require_account(account_key, api)
    updated_count = 0
    for post_id, position_id in unverified:
        try:
            _require_account(account_key, api)
            repo.mark_unverified(account_key, post_id, position_id)
        except Exception as exc:
            errors.append(f"持仓 {position_id} 的状态更新失败：{exc}")
    for post_id, position_id, result_usc, closed_at in resolved:
        try:
            _require_account(account_key, api)
            updated_count += repo.close_link(account_key, post_id, position_id,
                                             result_usc, closed_at)
        except Exception as exc:
            errors.append(f"持仓 {position_id} 的行情日志更新失败：{exc}")
    return JournalSyncResult(updated_count, tuple(errors))
