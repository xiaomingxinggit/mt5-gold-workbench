"""Account-gated write actions for the Qt Quick workbench.

Only this bridge reaches services that can send MT5 requests. Every trading
action requires a fresh preview, an explicit confirmation token, and another
account/market check immediately before execution.
"""

from __future__ import annotations

import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from uuid import uuid4

import MetaTrader5 as mt5
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from mt5_workbench.domain.account_policy import is_usc_account
from mt5_workbench.domain.position_optimizer import Optimization, money, optimize
from mt5_workbench.services.account_controls import (
    close_request, execute_batch, load_targets,
)
from mt5_workbench.services.journal_positions import load_open_positions
from mt5_workbench.services.basic_limit_order import basic_fields, build_basic_request
from mt5_workbench.services.position_protection import (
    PROTECTION_REQUEST_INTERVAL_SECONDS, execute_protection_batch, prepare_protection,
    select_targets,
)
from mt5_workbench.services.trade_execution import (
    build_requests, check_requests, existing_duplicates, send_checked,
)
from mt5_workbench.ui.qml_bridge import QmlBridge, _journal_post


def _records_dir(kind: str) -> Path:
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[3])
    return base / "state" / kind


def _plan_fields(payload: dict) -> dict[str, str]:
    names = ("budget", "usage", "center", "tolerance", "stop", "takeProfit",
             "levels", "mode", "weights")
    return {name: str(payload.get(name, "")).strip() for name in names}


class QmlTradingBridge(QmlBridge):
    """Keep the new presentation layer separate from trading safeguards."""

    def __init__(self, *args, **kwargs):
        self._plan: Optimization | None = None
        self._plan_fields: dict[str, str] | None = None
        self._plan_account: tuple[int, str] | None = None
        self._suggested_types: tuple[str, ...] = ()
        self._confirmation: dict | None = None
        self._control_scope = "symbol"
        self._control_result = ""
        self._protection_thread = None
        self._protection_cancel = Event()
        self._protection_events = Queue()
        self._protection_reconnect = False
        self._shutdown_after_protection = False
        super().__init__(*args, **kwargs)
        self._protection_timer = QTimer(self)
        self._protection_timer.setInterval(80)
        self._protection_timer.timeout.connect(self._consume_protection)

    def _clear_session(self, message: str, *, locked: bool = False,
                       current_account=None) -> None:
        self._protection_cancel.set()
        self._control_result = ""
        self._plan = None
        self._plan_fields = None
        self._plan_account = None
        self._suggested_types = ()
        self._confirmation = None
        super()._clear_session(message, locked=locked, current_account=current_account)

    def connect(self) -> None:
        if self._protection_busy():
            self._protection_cancel.set()
            self._protection_reconnect = True
            self._set_status("正在停止批量修改，然后重新连接…")
            return
        self._control_result = ""
        self._plan = None
        self._plan_fields = None
        self._plan_account = None
        self._suggested_types = ()
        self._confirmation = None
        if hasattr(self, "_state"):
            self._set_state(confirmation={})
        super().connect()

    def _refresh_page(self, page: str, *, force: bool = False) -> None:
        if page == "controls":
            try:
                self._refresh_controls(self._control_scope, force=force)
            except (RuntimeError, ValueError, OSError) as exc:
                self._set_state(status=f"控制目标读取失败：{exc}")
            return
        super()._refresh_page(page, force=force)

    def _require_account(self):
        if not self.check_account_access() or self.account is None:
            raise RuntimeError("请先连接 USC 美分账户")
        current = self._api.account_info()
        if current is None or (current.login, current.server) != (
                self.account.login, self.account.server) or not is_usc_account(current):
            raise RuntimeError("账户已切换，请刷新后重试")
        return current

    def _symbol_and_tick(self):
        symbol = self._api.symbol_info(self.symbol_name)
        if symbol is None:
            raise RuntimeError(f"找不到品种 {self.symbol_name}")
        if not symbol.visible and not self._api.symbol_select(self.symbol_name, True):
            raise RuntimeError(f"无法在市场报价中显示 {self.symbol_name}")
        tick = self._api.symbol_info_tick(self.symbol_name)
        if tick is None or tick.bid <= 0 or tick.ask <= 0 or tick.ask < tick.bid:
            raise RuntimeError(f"{self.symbol_name} 报价不可用")
        return symbol, tick

    def _reset_plan(self, message: str = "参数已修改，请重新计算。") -> None:
        self._plan = None
        self._plan_fields = None
        self._plan_account = None
        self._suggested_types = ()
        self._clear_confirmation()
        self._set_state(optimizer={
            "info": message, "lot": "—", "risk": "—", "unused": "—",
            "comparison": "计算后显示不同分配方式的手数。",
            "warning": "测算不包含滑点、跳空、手续费和保证金限制。",
            "rows": [], "canPreview": False,
        })

    def _clear_confirmation(self) -> None:
        self._confirmation = None
        self._set_state(confirmation={})

    def _calculate_result(self, fields: dict[str, str], account, symbol) -> Optimization:
        center = money(fields["center"], "目标入场价")
        tolerance = money(fields["tolerance"], "误差度")
        low, high = center - tolerance, center + tolerance
        if low <= 0:
            raise ValueError("误差度过大，区间起点必须大于 0")
        try:
            levels = int(fields["levels"])
        except ValueError as exc:
            raise ValueError("档数必须是 2～12 的整数") from exc
        mode = fields["mode"] or "weighted"
        weights = None
        if mode == "weighted":
            try:
                weights = tuple(Decimal(piece.strip()) for piece in
                                fields["weights"].split(","))
            except InvalidOperation as exc:
                raise ValueError("权重格式示例：1,2,3") from exc
        return optimize(
            symbol, account.currency, low, high, fields["stop"], fields["budget"],
            levels=levels, mode=mode, weights=weights,
            budget_usage_percent=fields["usage"] or "95",
            take_profit=fields["takeProfit"], profit_fn=self._api.order_calc_profit,
        )

    def _suggestions(self, result: Optimization, tick) -> tuple[str, ...]:
        if result.side == "SELL":
            return tuple("SELL LIMIT" if item.price > Decimal(str(tick.ask))
                         else "不可作为 LIMIT" for item in result.entries)
        return tuple("BUY LIMIT" if item.price < Decimal(str(tick.bid))
                     else "不可作为 LIMIT" for item in result.entries)

    def _calculate(self, payload: dict) -> None:
        self._reset_plan()
        account = self._require_account()
        symbol, tick = self._symbol_and_tick()
        fields = _plan_fields(payload)
        result = self._calculate_result(fields, account, symbol)
        suggestions = self._suggestions(result, tick)
        warning = "未计入滑点、跳空、手续费和保证金限制。"
        can_preview = True
        try:
            build_requests(result, symbol, tick, account)
        except (RuntimeError, ValueError) as exc:
            can_preview = False
            warning = f"当前不满足 LIMIT 挂单条件：{exc}。测算结果仅供查看。"
        if not self.check_account_access():
            raise RuntimeError("账户已切换，测算结果已丢弃")
        comparisons = []
        for title, mode in (("加权", "weighted"), ("等风险", "equal_risk"),
                            ("覆盖区间", "max_lots_ladder"),
                            ("单点开仓", "max_lots_single")):
            try:
                other_fields = dict(fields, mode=mode)
                other = self._calculate_result(other_fields, account, symbol)
                comparisons.append(f"{title} {other.total_volume} 手")
            except (RuntimeError, ValueError, InvalidOperation):
                continue
        self._plan = result
        self._plan_fields = fields
        self._plan_account = (account.login, account.server)
        self._suggested_types = suggestions
        self._set_state(optimizer={
            "info": (f"{result.side} LIMIT · {len(result.entries)} 档 · "
                     f"入场区间 {result.range_low}～{result.range_high} · "
                     f"风险上限 {result.risk_cap_usd:.2f} USD · "
                     f"止损 {fields['stop']} · 止盈 {fields['takeProfit'] or '未设置'}"),
            "lot": f"{result.total_volume} lot",
            "risk": f"{result.total_risk_usd:.2f} USD",
            "unused": f"{result.unused_usd:.2f} USD",
            "comparison": "  /  ".join(comparisons), "warning": warning,
            "rows": [
                {"level": index, "type": kind, "price": str(item.price),
                 "volume": str(item.volume), "stopDistance": str(item.stop_distance),
                 "riskUsd": f"{item.risk_usd:.2f}"}
                for index, (item, kind) in enumerate(zip(result.entries, suggestions), 1)
            ],
            "canPreview": can_preview,
        })
        self._set_state(status="LIMIT 下单方案已计算；没有向 MT5 发送订单")

    def _fresh_order_plan(self, payload: dict):
        fields = _plan_fields(payload)
        if self._plan is None or self._plan_fields != fields or self._plan_account is None:
            raise RuntimeError("参数已变化，请重新计算 LIMIT 下单方案")
        account = self._require_account()
        if (account.login, account.server) != self._plan_account:
            raise RuntimeError("账户已切换，请重新计算")
        terminal = self._api.terminal_info()
        if terminal is None or not terminal.connected or not terminal.trade_allowed:
            raise RuntimeError("MT5 终端未连接或未允许自动交易")
        symbol, tick = self._symbol_and_tick()
        fresh = self._calculate_result(fields, account, symbol)
        if fresh != self._plan:
            raise RuntimeError("品种参数或测算结果已变化，请重新计算")
        requests = build_requests(fresh, symbol, tick, account)
        if existing_duplicates(requests, api=self._api):
            raise RuntimeError("已有相同挂单，请先核对 MT5")
        return account, symbol, tick, fresh, requests

    def _preview_orders(self, payload: dict) -> None:
        account, symbol, tick, result, requests = self._fresh_order_plan(payload)
        check_requests(requests, api=self._api)
        if not self.check_account_access():
            raise RuntimeError("账户已切换，预览已取消")
        token = uuid4().hex
        self._confirmation = {
            "kind": "orders", "token": token, "fields": _plan_fields(payload),
            "account": (account.login, account.server), "requests": requests,
            "result": result,
        }
        self._set_state(confirmation={
            "token": token, "title": "确认发送 LIMIT 挂单",
            "heading": "发送挂单前核对",
            "details": (f"账户 {account.login} · {account.server} · {account.currency}  "
                        f"品种 {symbol.name}  Bid {tick.bid:.{symbol.digits}f} / "
                        f"Ask {tick.ask:.{symbol.digits}f}\n"
                        f"{result.side} LIMIT · {len(requests)} 笔 · 总手数 "
                        f"{result.total_volume} lot · 估算止损风险 "
                        f"{result.total_risk_usd:.2f} / 上限 {result.risk_cap_usd:.2f} USD"),
            "warning": ("确认后将发送真实挂单。实际成交、跳空和手续费可能使亏损超过估算；"
                        "失败时停止剩余挂单，不会自动重试。"),
            "columns": ["类型", "入场价", "手数", "统一止损", "统一止盈", "风险 USD"],
            "rows": [
                ["SELL LIMIT" if result.side == "SELL" else "BUY LIMIT",
                 str(request["price"]), str(request["volume"]), str(request["sl"]),
                 str(request["tp"] or "—"), f"{entry.risk_usd:.2f}"]
                for request, entry in zip(requests, result.entries)
            ],
            "confirmText": "确认发送", "danger": True,
        })

    def _copy_plan(self) -> None:
        result = self._plan
        if result is None or self._plan_fields is None or not self.check_account_access():
            raise RuntimeError("请先计算当前账户的 LIMIT 下单方案")
        fields = self._plan_fields
        lines = [
            f"{self.symbol_name} {result.side} LIMIT 下单方案",
            f"入场区间 {result.range_low}～{result.range_high}",
            f"预算 {result.budget_usd:.2f} USD × {result.budget_usage_percent:g}% "
            f"= 风险上限 {result.risk_cap_usd:.2f} USD",
            f"总手数 {result.total_volume} lot · 估算风险 {result.total_risk_usd:.2f} USD",
            f"统一止损 {fields['stop']} · 统一止盈 {fields['takeProfit'] or '未设置'}",
        ]
        for kind, item in zip(self._suggested_types, result.entries):
            lines.append(f"{kind} @ {item.price} · {item.volume} lot · 风险 {item.risk_usd:.2f} USD")
        lines.append("仅供测算；未提交 MT5 订单。")
        QApplication.clipboard().setText("\n".join(lines))
        self._set_state(status="配置已复制到剪贴板")

    def _basic_request(self, fields: dict):
        account = self._require_account()
        terminal = self._api.terminal_info()
        if terminal is None or not terminal.connected or not terminal.trade_allowed:
            raise RuntimeError("MT5 终端未连接或未允许自动交易")
        symbol, tick = self._symbol_and_tick()
        request, risk = build_basic_request(fields, account, symbol, tick, api=self._api)
        if existing_duplicates((request,), api=self._api):
            raise RuntimeError("已有相同挂单，请先核对 MT5")
        return account, symbol, tick, request, risk

    def _preview_basic_order(self, payload: dict) -> None:
        self._clear_confirmation()
        self._set_state(basicOrder={})
        fields = basic_fields(payload)
        account, symbol, tick, request, risk = self._basic_request(fields)
        check_requests((request,), api=self._api)
        if not self.check_account_access():
            raise RuntimeError("账户已切换，预览已取消")
        token = uuid4().hex
        self._confirmation = {
            "kind": "basic-order", "token": token, "fields": fields,
            "account": (account.login, account.server), "requests": (request,),
        }
        risk_text = f"{risk:.2f} USD" if risk is not None else "未设止损，风险未限定"
        self._set_state(basicOrder={"risk": risk_text, "message": "已通过挂单预检查"},
                        confirmation={
            "token": token, "title": "确认基础限价单", "heading": "发送挂单前核对",
            "details": (f"账户 {account.login} · {account.server} · {account.currency}\n"
                        f"{symbol.name} · Bid {tick.bid:.{symbol.digits}f} / "
                        f"Ask {tick.ask:.{symbol.digits}f} · GTC 长期有效"),
            "warning": ("确认后将发送 1 笔真实 LIMIT 挂单。" +
                        ("未设置止损，亏损风险未限定。" if risk is None else "") +
                        "估算未计入跳空、手续费及隔夜费；失败时不会自动重试。"),
            "columns": ["类型", "限价", "手数", "止损", "止盈", "风险 USD"],
            "rows": [[fields["side"] + " LIMIT", fields["price"], fields["volume"],
                      fields["sl"] or "—", fields["tp"] or "—", risk_text]],
            "confirmText": "确认发送", "danger": True,
        })

    def _refresh_controls(self, scope: str, *, force: bool = False) -> None:
        if self._protection_busy():
            return
        account = self._require_account()
        if scope not in {"symbol", "account"}:
            raise ValueError("操作范围无效")
        self._control_scope = scope
        account_label = f"账户 {account.login} · {account.server} · {account.currency}"
        self._set_state(controls={
            "accountLabel": account_label, "scope": scope,
            "summary": "正在读取持仓与挂单…", "status": self._control_result or "正在读取目标…",
            "positions": [], "orders": [], "canClose": False, "canRemove": False,
            "loading": True, "busy": False,
        })

        def load(api) -> dict:
            active = load_targets("close", scope, self.symbol_name, api=api)
            pending = load_targets("remove", scope, self.symbol_name, api=api)
            return {
                "accountLabel": account_label, "scope": scope,
                "summary": f"持仓 {len(active)} 笔 · 挂单 {len(pending)} 笔",
                "status": self._control_result or "目标已更新", "loading": False, "busy": False,
                "positions": [
                    {"ticket": str(row.ticket), "symbol": row.symbol,
                     "side": "BUY" if row.type == mt5.POSITION_TYPE_BUY else "SELL",
                     "volume": str(row.volume), "openPrice": str(row.price_open),
                     "profit": str(getattr(row, "profit", "—")),
                     "sl": str(getattr(row, "sl", 0) or "—"),
                     "tp": str(getattr(row, "tp", 0) or "—")}
                    for row in active
                ],
                "orders": [
                    {"ticket": str(row.ticket), "symbol": row.symbol,
                     "type": str(row.type), "volume": str(row.volume_initial),
                     "price": str(row.price_open), "stop": str(row.sl or "—")}
                    for row in pending
                ],
                "canClose": bool(active), "canRemove": bool(pending),
            }

        self._request_job("controls", (self._identity(), scope), load, force=force)

    def _preview_control(self, payload: dict) -> None:
        account = self._require_account()
        kind = str(payload.get("kind", ""))
        scope = str(payload.get("scope", self._control_scope))
        if kind not in {"close", "remove"} or scope not in {"symbol", "account"}:
            raise ValueError("控制面板操作或范围无效")
        deviation = int(payload.get("deviation", 50)) if kind == "close" else 0
        rows = load_targets(kind, scope, self.symbol_name, api=self._api)
        if not rows:
            raise ValueError("所选范围内没有需要处理的目标")
        if kind == "close":
            for row in rows:
                close_request(row, deviation, api=self._api)
        if not self.check_account_access():
            raise RuntimeError("账户已切换，预览已取消")
        title = "全部平仓" if kind == "close" else "删除所有挂单"
        token = uuid4().hex
        self._confirmation = {
            "kind": "control", "token": token, "operation": kind, "scope": scope,
            "deviation": deviation, "rows": rows,
            "account": (account.login, account.server),
        }
        self._set_state(confirmation={
            "token": token, "title": f"确认{title}", "heading": f"确认{title}",
            "details": (f"账户 {account.login} · {account.server} · {account.currency}  "
                        f"范围 {self.symbol_name if scope == 'symbol' else '整个账户'}\n"
                        f"将处理 {len(rows)} 笔" +
                        (f" · 最大偏差 {deviation} 点" if kind == "close" else "")),
            "warning": ("确认后按市价逐笔平仓，最终成交价可能不同，现有挂单仍可能成交。"
                        if kind == "close" else
                        "确认后逐笔撤销挂单；若撤销前成交，该笔可能无法删除。") +
                       "失败时停止后续目标，不会自动重试。",
            "columns": ["Ticket", "品种", "方向 / 类型", "手数", "价格", "止损"],
            "rows": [
                [str(row.ticket), row.symbol,
                 ("BUY" if row.type == mt5.POSITION_TYPE_BUY else "SELL")
                 if kind == "close" else str(row.type),
                 str(row.volume if kind == "close" else row.volume_initial),
                 str(row.price_open), str(row.sl or "—")]
                for row in rows
            ],
            "confirmText": f"确认{title}", "danger": kind == "close",
        })

    def _preview_protection(self, action: str, payload: dict) -> None:
        """Show the exact position SL/TP changes before any trading request."""
        self._control_result = ""
        self._clear_confirmation()
        account = self._require_account()
        scope = str(payload.get("scope", self._control_scope))
        if scope not in {"symbol", "account"} or scope != self._control_scope:
            raise ValueError("操作范围已变化，请刷新目标后重试")
        tickets = payload.get("tickets")
        rows = select_targets(load_targets("close", scope, self.symbol_name, api=self._api), tickets)
        if not rows:
            raise ValueError("所选范围内没有持仓")
        kind = "breakeven" if action == "previewBreakEven" else "batch"
        amount_usd = sl = tp = None
        if kind == "breakeven":
            amount_usd = money(payload.get("amountUsd", ""), "每笔目标锁盈")
        else:
            sl_text = str(payload.get("sl", "")).strip()
            tp_text = str(payload.get("tp", "")).strip()
            if not sl_text and not tp_text:
                raise ValueError("请至少填写止损价或止盈价")
            sl = money(sl_text, "止损价") if sl_text else None
            tp = money(tp_text, "止盈价") if tp_text else None
        plans = prepare_protection(kind, rows, amount_usd=amount_usd,
                                   sl=sl, tp=tp, api=self._api)
        if not plans:
            raise ValueError("所选持仓的保护价已满足目标，无需修改")
        if not self.check_account_access():
            raise RuntimeError("账户已切换，预览已取消")
        token = uuid4().hex
        skipped = len(rows) - len(plans)
        self._confirmation = {
            "kind": "protection", "token": token, "operation": kind,
            "scope": scope, "rows": rows, "plans": plans,
            "tickets": tuple(str(row.ticket) for row in rows) if tickets is not None else None,
            "amount_usd": amount_usd, "sl": sl, "tp": tp,
            "account": (account.login, account.server),
        }
        if kind == "breakeven":
            columns = ["Ticket", "品种/方向", "开仓价", "原止损", "新止损", "估算锁盈"]
            display_rows = [
                [str(plan.ticket), f"{plan.symbol} {plan.side}",
                 str(plan.price_open), str(plan.old_sl or "—"),
                 str(plan.new_sl),
                 (f"{Decimal(str(plan.expected_profit_usc)) / 100:.2f} USD"
                  if plan.expected_profit_usc is not None else "—")]
                for plan in plans
            ]
            title = "一键推保本"
            parameter = f"每笔目标锁盈约 {amount_usd} USD"
            warning = ("估算为持仓毛利润，未扣除手续费、隔夜费及实际执行偏差。"
                       "现有更优止损会跳过；确认时会重新核对持仓与报价。")
        else:
            columns = ["Ticket", "品种/方向", "原止损", "新止损", "原止盈", "新止盈"]
            display_rows = [
                [str(plan.ticket), f"{plan.symbol} {plan.side}",
                 str(plan.old_sl or "—"), str(plan.new_sl or "—"),
                 str(plan.old_tp or "—"), str(plan.new_tp or "—")]
                for plan in plans
            ]
            title = "批量设置止盈 / 止损"
            parameter = f"统一止损 {sl if sl is not None else '保持原值'} · 止盈 {tp if tp is not None else '保持原值'}"
            warning = ("统一价格可能改变现有风险；留空的一侧保持原值。"
                       "确认时会重新核对持仓与报价。")
        details = (f"账户 {account.login} · {account.server} · {account.currency}\n"
                   f"范围 {self.symbol_name if scope == 'symbol' else '整个账户'} · 预览 {len(rows)} 笔" +
                   (f" · 已满足目标 {skipped} 笔（无需修改）" if skipped else "") + f"\n{parameter}")
        self._confirmation["detailsBase"] = details
        self._set_state(confirmation={
            "token": token, "title": f"确认{title}", "heading": "勾选需要修改的持仓，并核对修改前后的价格",
            "details": details + f"\n本次勾选 {len(plans)} 笔待修改持仓",
            "warning": warning + "逐笔间隔 2 秒发送；任一笔失败即停止后续操作，不自动重试。",
            "columns": columns, "rows": display_rows,
            "selectable": True, "selectedTickets": [str(plan.ticket) for plan in plans],
            "confirmText": "确认修改止盈止损", "danger": kind == "batch",
        })
        self._confirmation["enabledTickets"] = tuple(str(plan.ticket) for plan in plans)

    def _toggle_protection_ticket(self, payload: dict) -> None:
        preview = self._confirmation
        if preview is None or preview["kind"] != "protection":
            raise RuntimeError("确认信息已失效，请重新预览")
        self._require_account()
        ticket = str(payload.get("ticket", ""))
        if ticket not in {str(plan.ticket) for plan in preview["plans"]}:
            raise ValueError("持仓不在当前预览中")
        enabled = set(preview["enabledTickets"])
        if payload.get("checked") is True:
            enabled.add(ticket)
        elif payload.get("checked") is False:
            enabled.discard(ticket)
        else:
            raise ValueError("持仓选择无效")
        preview["enabledTickets"] = tuple(str(plan.ticket) for plan in preview["plans"]
                                         if str(plan.ticket) in enabled)
        confirmation = dict(self.state["confirmation"])
        confirmation["selectedTickets"] = list(preview["enabledTickets"])
        confirmation["details"] = preview["detailsBase"] + f"\n本次勾选 {len(enabled)} 笔待修改持仓"
        self._set_state(confirmation=confirmation)

    def _publish_journal(self, payload: dict) -> None:
        account = self._require_account()
        if self.journal_repo is None:
            raise RuntimeError("本地日志不可用")
        body = str(payload.get("body", ""))
        position_ids = tuple(int(value) for value in payload.get("positionIds", []))
        if len(set(position_ids)) != len(position_ids):
            raise ValueError("关联持仓不能重复")
        account_key = (account.login, account.server)
        selected = ()
        if position_ids:
            live = load_open_positions(account_key, self.symbol_name, api=self._api)
            by_id = {item.position_id: item for item in live}
            if set(position_ids) - by_id.keys():
                raise ValueError("选中的持仓已变化或平仓，请刷新后重新选择")
            selected = tuple(by_id[position_id] for position_id in position_ids)
        if not self.check_account_access():
            raise RuntimeError("账户已切换，发帖已取消")
        images = self.state.get("journal", {}).get("draftImages", [])
        image_paths = tuple(Path(str(row["path"])) for row in images)
        self.journal_repo.create_post(account_key, body, image_paths, selected)
        journal = dict(self.state.get("journal", {}))
        journal["draftImages"] = []
        journal["publishedRevision"] = journal.get("publishedRevision", 0) + 1
        self._set_state(journal=journal, status="行情日志已保存到本机")
        self.perform("journalRefresh", {})

    def _preview_delete_post(self, payload: dict) -> None:
        account = self._require_account()
        post_id = int(payload.get("postId", 0))
        if post_id <= 0:
            raise ValueError("帖子编号无效")
        token = uuid4().hex
        self._confirmation = {
            "kind": "journal-delete", "token": token, "post_id": post_id,
            "account": (account.login, account.server),
        }
        self._set_state(confirmation={
            "token": token, "title": "删除行情日志", "heading": "删除这篇帖子？",
            "details": f"账户 {account.login} · {account.server} · 帖子 {post_id}",
            "warning": "帖子、回复及其本地图片会被删除，无法撤销。",
            "columns": [], "rows": [], "confirmText": "确认删除", "danger": True,
        })

    def _publish_reply(self, payload: dict) -> None:
        account = self._require_account()
        if self.journal_repo is None:
            raise RuntimeError("本地日志不可用")
        post_id = int(payload.get("postId", 0))
        if post_id <= 0:
            raise ValueError("帖子编号无效")
        images = self._journal_draft_images(post_id)
        account_key = (account.login, account.server)
        if not self.check_account_access():
            raise RuntimeError("账户已切换，回复已取消")
        self.journal_repo.create_reply(
            account_key, post_id, str(payload.get("body", "")),
            tuple(Path(row["path"]) for row in images),
        )
        journal = dict(self.state["journal"])
        drafts = dict(journal.get("replyDraftImages", {}))
        drafts.pop(str(post_id), None)
        journal["replyDraftImages"] = drafts
        journal["replyPublishedRevision"] = journal.get("replyPublishedRevision", 0) + 1
        journal["replyPublishedPostId"] = post_id
        # Invalidate a pre-publication read so it cannot replace these replies.
        self._generations["journal"] = self._generations.get("journal", 0) + 1
        self._set_state(journal=journal, status="回复已保存到本机")
        try:
            feed = self.journal_repo.list_posts(account_key, journal.get("page", 1), 10)
            self._set_state(journal={**self.state["journal"],
                                     "posts": [_journal_post(post) for post in feed.posts]})
        except (OSError, sqlite3.Error) as exc:
            self._set_status(f"回复已保存，列表刷新失败：{exc}")
        self.refresh_journal(force=True)

    def _protection_busy(self) -> bool:
        return self._protection_thread is not None

    def _execute_protection(self, preview, account, *, cancelled=None, progress=None):
        return execute_protection_batch(
            preview["operation"], preview["scope"], self.symbol_name,
            account, preview["rows"], preview["plans"], _records_dir("controls"),
            amount_usd=preview["amount_usd"], sl=preview["sl"], tp=preview["tp"],
            selected_tickets=preview.get("tickets"), cancelled=cancelled, progress=progress,
            request_interval_seconds=PROTECTION_REQUEST_INTERVAL_SECONDS, api=self._api,
        )

    def _start_protection(self, preview, account) -> None:
        """Pace confirmed multi-position writes off the GUI thread."""
        identity = (account.login, account.server)
        self._protection_cancel = Event()
        cancelled = self._protection_cancel
        self._control_result = ""
        self._generations["controls"] = self._generations.get("controls", 0) + 1
        if "controls" in self._jobs:
            self._jobs["controls"].cancelled.set()
        self._pending_jobs.pop("controls", None)
        self._set_state(controls={**self.state["controls"], "busy": True,
                                 "loading": False, "status": f"正在修改 0/{len(preview['plans'])} 笔…"})

        def progress(done, total, ticket):
            self._protection_events.put(("progress", identity,
                                        f"已修改 {done}/{total} 笔 · #{ticket}；逐笔间隔 2 秒"))

        def run():
            try:
                done = self._execute_protection(preview, account, cancelled=cancelled, progress=progress)
                message = f"止盈止损已修改 {len(done)} 笔；请在 MT5 核对实际状态"
            except Exception as exc:
                message = f"批量修改未全部完成：{exc}"
            finally:
                if self._shutdown_after_protection:
                    self._api.shutdown()
            self._protection_events.put(("done", identity, message))

        self._protection_thread = Thread(target=run, name="mt5-protection-writes", daemon=True)
        try:
            self._protection_thread.start()
        except RuntimeError:
            self._protection_thread = None
            self._set_state(controls={**self.state["controls"], "busy": False})
            raise
        self._protection_timer.start()

    def _consume_protection(self) -> None:
        while True:
            try:
                kind, identity, message = self._protection_events.get_nowait()
            except Empty:
                break
            if kind == "done":
                if self._protection_thread is not None and self._protection_thread.is_alive():
                    self._protection_events.put((kind, identity, message))
                    break
                self._protection_thread = None
                self._protection_timer.stop()
            if not self._closing and self.connected and identity == self._identity():
                self._set_state(status=message, controls={**self.state["controls"],
                                                         "busy": kind != "done", "status": message})
                if kind == "done" and self.check_account_access():
                    self._control_result = message
                    self._refresh_controls(self._control_scope, force=True)
            if kind == "done" and self._protection_reconnect and not self._closing:
                self._protection_reconnect = False
                self.connect()

    def shutdown(self) -> None:
        self._protection_cancel.set()
        self._protection_timer.stop()
        if self._protection_thread is not None and self._protection_thread.is_alive() and self.initialized:
            # Let the worker finish its in-flight request before shutting down MT5.
            self._shutdown_after_protection = True
            self.initialized = False
        super().shutdown()

    def _confirm(self, payload: dict) -> None:
        preview = self._confirmation
        if preview is None or str(payload.get("token", "")) != preview["token"]:
            raise RuntimeError("确认信息已失效，请重新预览")
        # Consume the token before any MT5 or file operation so a double click
        # cannot execute the same preview twice.
        self._clear_confirmation()
        account = self._require_account()
        if (account.login, account.server) != preview["account"]:
            raise RuntimeError("账户已切换，操作已取消")
        if preview["kind"] == "orders":
            _account, _symbol, _tick, result, requests = self._fresh_order_plan(preview["fields"])
            if requests != preview["requests"] or result != preview["result"]:
                raise RuntimeError("报价或挂单配置已变化，请重新预览")
            sent = send_checked(account, requests, _records_dir("executions"), api=self._api)
            self._reset_plan("挂单已提交；请在总览看板核对挂单。")
            self._set_state(status=f"已提交 {len(sent)} 笔 LIMIT 挂单；请在 MT5 核对实际状态")
            self.perform("refresh", {})
        elif preview["kind"] == "basic-order":
            _account, _symbol, _tick, request, _risk = self._basic_request(preview["fields"])
            if (request,) != preview["requests"]:
                raise RuntimeError("挂单配置已变化，请重新预览")
            sent = send_checked(account, (request,), _records_dir("executions"), api=self._api)
            self._set_state(basicOrder={"message": "已提交 1 笔 LIMIT 挂单，请在 MT5 核对"},
                            status=f"已提交 {len(sent)} 笔基础 LIMIT 挂单")
            self.perform("refresh", {})
        elif preview["kind"] == "control":
            done = execute_batch(
                preview["operation"], preview["scope"], self.symbol_name,
                account, preview["rows"], preview["deviation"],
                _records_dir("controls"), api=self._api,
            )
            self._set_state(status=f"控制操作完成 {len(done)} 笔；请在 MT5 核对实际状态")
            self._refresh_controls(preview["scope"])
            self.perform("refresh", {})
        elif preview["kind"] == "protection":
            enabled = set(preview["enabledTickets"])
            if not enabled:
                raise ValueError("请至少勾选一笔待修改的持仓")
            preview = {**preview,
                       "plans": tuple(plan for plan in preview["plans"] if str(plan.ticket) in enabled),
                       "rows": tuple(row for row in preview["rows"] if str(row.ticket) in enabled),
                       "tickets": tuple(enabled)}
            if len(preview["plans"]) > 1:
                self._start_protection(preview, account)
                return
            try:
                done = self._execute_protection(preview, account)
            except Exception as exc:
                self._control_result = f"修改未完成：{exc}"
                try:
                    self._refresh_controls(preview["scope"], force=True)
                except (RuntimeError, ValueError):
                    pass
                raise
            self._control_result = f"止盈止损已修改 {len(done)} 笔；请在 MT5 核对实际状态"
            self._set_state(status=self._control_result)
            self._refresh_controls(preview["scope"], force=True)
            self.perform("refresh", {})
        elif preview["kind"] == "journal-delete":
            if self.journal_repo is None or not self.journal_repo.delete_post(
                    (account.login, account.server), preview["post_id"]):
                raise RuntimeError("帖子不存在或不属于当前账户")
            self._set_state(status="本地帖子已删除")
            self._set_journal_draft_images([], preview["post_id"])
            self.perform("journalRefresh", {})

    def _perform_protected(self, action: str, payload: dict) -> None:
        confirming_basic = (action == "confirm" and self._confirmation is not None
                            and self._confirmation["kind"] == "basic-order")
        try:
            if self._protection_busy() and action not in {
                    "journalPublish", "journalDelete", "journalReplyPublish", "cancelConfirm"}:
                raise RuntimeError("正在执行批量修改，请等待完成后再操作")
            if action == "entryCalculate":
                self._calculate(payload)
            elif action == "entryInvalidate":
                self._reset_plan()
            elif action == "entryPreview":
                self._preview_orders(payload)
            elif action == "entryCopy":
                self._copy_plan()
            elif action == "basicPreview":
                self._preview_basic_order(payload)
            elif action == "basicInvalidate":
                self._clear_confirmation()
                self._set_state(basicOrder={})
            elif action == "entryTabChanged":
                self._reset_plan()
                self._set_state(basicOrder={})
            elif action == "controlsRefresh":
                self._refresh_controls(str(payload.get("scope", self._control_scope)), force=True)
            elif action == "controlsPreview":
                self._preview_control(payload)
            elif action in {"previewBreakEven", "previewBatchStops"}:
                self._preview_protection(action, payload)
            elif action == "protectionToggleTicket":
                self._toggle_protection_ticket(payload)
            elif action == "journalPublish":
                self._publish_journal(payload)
            elif action == "journalDelete":
                self._preview_delete_post(payload)
            elif action == "journalReplyPublish":
                self._publish_reply(payload)
            elif action == "confirm":
                self._confirm(payload)
            elif action == "cancelConfirm":
                self._clear_confirmation()
            else:
                raise ValueError(f"未知操作：{action}")
        except (RuntimeError, ValueError, TypeError, OSError, sqlite3.Error,
                InvalidOperation) as exc:
            self._set_state(status=f"操作未完成：{exc}")
            if action == "basicPreview" or confirming_basic:
                self._set_state(basicOrder={"error": str(exc)})
            elif action in {"entryCalculate", "entryPreview"}:
                optimizer = dict(self.state.get("optimizer", {}))
                optimizer["warning"] = str(exc)
                self._set_state(optimizer=optimizer)
            elif action in {"controlsRefresh", "controlsPreview",
                            "previewBreakEven", "previewBatchStops", "confirm"}:
                controls = dict(self.state.get("controls", {}))
                controls["status"] = str(exc)
                self._set_state(controls=controls)
