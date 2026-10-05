"""Read-only MT5 and local journal state for the Qt Quick application.

The bridge owns no widgets. Slow history queries run on daemon workers and their
results are applied only on the GUI thread, after checking the account identity.
Trading actions are deliberately delegated to a subclass through
``_perform_protected``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

import MetaTrader5 as mt5
from PySide6.QtCore import QObject, Property, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from mt5_workbench.config import DEFAULT_SYMBOL
from mt5_workbench.domain.account_policy import is_usc_account
from mt5_workbench.domain.journal import BEIJING_TZ, beijing_time
from mt5_workbench.infrastructure.journal_db import (
    JournalRepository, MAX_IMAGES, MAX_IMAGE_BYTES,
)
from mt5_workbench.services.dashboard_data import load_dashboard
from mt5_workbench.services.ema_monitor import fetch_m1_ema_snapshot
from mt5_workbench.services.journal_positions import (
    load_open_positions, sync_closed_positions,
)
from mt5_workbench.services.order_analytics import load_order_analytics
from mt5_workbench.ui.theme import load_theme, save_theme


PAGE_NAMES = frozenset({"dashboard", "orders", "journal", "optimizer", "controls", "monitor"})
DEFAULT_REFRESH_INTERVALS = {"quote": 1, "positions": 5, "orders": 30}
MAX_REFRESH_SECONDS = 3600
READ_ONLY_CALLS = frozenset({
    "account_info", "terminal_info", "symbol_info", "symbol_info_tick",
    "copy_rates_from_pos", "positions_get", "orders_get",
    "history_orders_get", "history_deals_get", "last_error",
})


def _state_directory(kind: str) -> Path:
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[3])
    return base / "state" / kind


def _refresh_settings_path() -> Path:
    return _state_directory("refresh_intervals.json")


def _load_refresh_intervals() -> dict[str, int]:
    """Load read-only polling preferences, ignoring invalid saved values."""
    result = dict(DEFAULT_REFRESH_INTERVALS)
    try:
        saved = json.loads(_refresh_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return result
    if not isinstance(saved, dict):
        return result
    for kind in result:
        value = saved.get(kind)
        if type(value) is int and 1 <= value <= MAX_REFRESH_SECONDS:
            result[kind] = value
    return result


def _save_refresh_intervals(intervals: dict[str, int]) -> bool:
    """Persist polling preferences atomically without changing theme settings."""
    path = _refresh_settings_path()
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".refresh_intervals-",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(intervals, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        return True
    except OSError:
        return False
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _usd(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else number / 100


def _iso(value: datetime | date | None) -> str:
    return value.isoformat() if value is not None else ""


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _account_map(account: Any) -> dict[str, Any]:
    return {
        "login": _row_value(account, "login", 0),
        "server": str(_row_value(account, "server", "") or ""),
        "currency": str(_row_value(account, "currency", "") or ""),
        "name": str(_row_value(account, "name", "") or ""),
        "balance": _number(_row_value(account, "balance")),
        "equity": _number(_row_value(account, "equity")),
        "profit": _number(_row_value(account, "profit")),
        "marginFree": _number(_row_value(account, "margin_free")),
        "marginLevel": _number(_row_value(account, "margin_level")),
        "leverage": _row_value(account, "leverage"),
    }


def _empty_state(symbol: str, theme: str) -> dict[str, Any]:
    today = datetime.now(BEIJING_TZ).date()
    current_year = today.year
    return {
        "theme": theme,
        "page": "dashboard",
        "fullscreen": False,
        "refreshIntervals": dict(DEFAULT_REFRESH_INTERVALS),
        "connection": {"connected": False, "locked": False, "message": "正在连接 MT5"},
        "account": {},
        "basicOrder": {},
        "market": {"symbol": symbol, "bid": None, "ask": None,
                   "spreadPoints": None, "time": "", "change": None,
                   "changePct": None, "stale": True},
        "dashboard": {"loading": False, "candles": [], "dailyPnl": [],
                      "positions": [], "orders": [], "metrics": {},
                      "errors": [], "updatedAt": ""},
        "overview": {"loading": False, "scope": "symbol", "days": 30,
                     "metrics": {}, "accountCurve": [], "dailyExecution": [],
                     "pendingOrders": [], "recentOrders": [], "recentDeals": [],
                     "statusCounts": [], "errors": [], "asOf": ""},
        "journal": {"loading": False, "accountLabel": "请连接 USC 账户",
                    "canPublish": False, "notice": "", "total": 0,
                    "recent30": 0, "activeDays": 0, "year": current_year,
                    "years": [current_year], "yearTotal": 0, "heatmap": {},
                    "posts": [], "page": 1, "totalPages": 1,
                    "positions": [], "draftImages": [], "publishedRevision": 0,
                    "replyDraftImages": {}, "replyPublishedRevision": 0,
                    "replyPublishedPostId": 0, "today": today.isoformat()},
        "optimizer": {},
        "controls": {},
        "monitor": {"loading": False, "status": "waiting", "reason": "等待 MT5 连接",
                    "bid": None, "ask": None, "quoteAgeSeconds": None,
                    "emaValues": {}, "emaSpreadPoints": None,
                    "tolerancePoints": 5, "barTime": "", "observedAt": "",
                    "history": [], "includesFormingBar": False},
        "confirmation": {},
        "status": "等待 MT5 连接",
    }


class _Cancelled(RuntimeError):
    pass


class _GuardedReadOnlyApi:
    """Fail closed if a worker outlives its expected USC account."""

    def __init__(self, api: Any, cancelled: Event, identity: tuple[int, str]):
        self._api = api
        self._cancelled = cancelled
        self._identity = identity

    def verify(self) -> None:
        if self._cancelled.is_set():
            raise _Cancelled("读取已取消")
        account = self._api.account_info()
        if (account is None or not is_usc_account(account)
                or (_row_value(account, "login"), _row_value(account, "server"))
                != self._identity):
            self._cancelled.set()
            raise _Cancelled("读取期间 MT5 账户已切换")

    def __getattr__(self, name: str) -> Any:
        member = getattr(self._api, name)
        if not callable(member):
            return member
        if name not in READ_ONLY_CALLS:
            raise RuntimeError(f"后台读取不得调用 MT5 写入接口：{name}")

        def guarded(*args: Any, **kwargs: Any) -> Any:
            self.verify()
            result = member(*args, **kwargs)
            self.verify()
            return result

        return guarded


@dataclass
class _Job:
    thread: Thread
    cancelled: Event
    generation: int
    key: tuple[Any, ...]


def _order_row(row: Any) -> dict[str, Any]:
    return {
        "ticket": row.ticket, "symbol": row.symbol,
        "type": row.type_label, "status": row.status_label,
        "createdAt": _iso(row.created_at), "doneAt": _iso(row.done_at),
        "volumeInitial": row.volume_initial, "volumeCurrent": row.volume_current,
        "priceOpen": row.price_open, "sl": row.sl, "tp": row.tp,
        "comment": row.comment,
    }


def _deal_row(row: Any) -> dict[str, Any]:
    return {
        "ticket": row.ticket, "orderTicket": row.order_ticket,
        "symbol": row.symbol, "side": row.side_label, "entry": row.entry_label,
        "executedAt": _iso(row.executed_at), "volume": row.volume,
        "price": row.price, "profit": _number(row.profit),
        "swap": _number(row.swap), "commission": _number(row.commission),
        "fee": _number(row.fee), "cashflow": _number(row.cashflow),
    }


def _position_row(row: Any) -> dict[str, Any]:
    account_key = row.account_key or (0, "")
    return {
        "positionId": row.position_id, "ticket": row.ticket,
        "symbol": row.symbol, "side": row.side,
        "volume": _number(row.volume), "priceOpen": _number(row.price_open),
        "openedAt": _iso(row.opened_at), "sl": _number(row.sl),
        "tp": _number(row.tp), "floatingUsd": _usd(row.floating_usc),
        "accountLabel": f"{account_key[0]} · {account_key[1]}",
    }


def _journal_timestamp(value: datetime) -> dict[str, str]:
    local = beijing_time(value)
    return {"createdAt": local.isoformat(), "dateKey": local.date().isoformat(),
            "dateLabel": f"{local.year}年{local.month}月{local.day}日",
            "timeLabel": local.strftime("%H:%M")}


def _journal_post(row: Any) -> dict[str, Any]:
    linked = []
    for position in row.positions:
        entry = _position_row(position)
        entry.update({"status": position.status,
                      "resultUsd": _usd(position.result_usc),
                      "closedAt": _iso(position.closed_at)})
        linked.append(entry)
    return {
        "id": row.id, "accountLogin": row.account_key[0],
        **_journal_timestamp(row.created_at), "body": row.body,
        "images": [QUrl.fromLocalFile(str(path)).toString() for path in row.images],
        "positions": linked,
        "replies": [{"id": reply.id, **_journal_timestamp(reply.created_at),
                     "body": reply.body,
                     "images": [QUrl.fromLocalFile(str(path)).toString()
                                for path in reply.images]}
                    for reply in row.replies],
    }


class QmlBridge(QObject):
    """One state snapshot and one action entrypoint for the QML frontend."""

    stateChanged = Signal()
    sectionChanged = Signal(str, "QVariant")

    def __init__(self, symbol_name: str = DEFAULT_SYMBOL,
                 terminal_path: str | None = None, *, autoconnect: bool = True,
                 start_timer: bool = True,
                 journal_repository: JournalRepository | None = None,
                 api: Any = None, parent: QObject | None = None):
        super().__init__(parent)
        self.symbol_name = symbol_name
        self.terminal_path = terminal_path
        self._api = mt5 if api is None else api
        self.connected = False
        self.initialized = False
        self.account = None
        self.symbol = None
        self.tick = None
        self.journal_account_key: tuple[int, str] | None = None
        self._state = _empty_state(symbol_name, load_theme())
        self._owned_draft_images: set[Path] = set()
        self._state["refreshIntervals"] = _load_refresh_intervals()
        self._closing = False
        self._reconnect_pending = False
        self._jobs: dict[str, _Job] = {}
        self._generations: dict[str, int] = {}
        self._pending_jobs: dict[str, tuple[tuple[Any, ...], Callable[[Any], dict[str, Any]]]] = {}
        self._results: Queue[tuple[str, int, tuple[Any, ...], dict[str, Any] | None, str]] = Queue()
        self._result_waiting: dict[str, tuple[str, int, tuple[Any, ...], dict[str, Any] | None, str]] = {}
        self._last_requested: dict[str, float] = {}
        self._last_quote_at = 0.0
        try:
            self.journal_repo = (journal_repository if journal_repository is not None
                                 else JournalRepository(_state_directory("journal")))
            self.journal_error = ""
        except (OSError, sqlite3.Error) as exc:
            self.journal_repo = None
            self.journal_error = f"本地日志无法打开：{exc}"
            self._set_state(journal={**self._state["journal"], "notice": self.journal_error})
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.poll)
        if start_timer:
            self._timer.start()
        self._results_timer = QTimer(self)
        self._results_timer.setInterval(80)
        self._results_timer.timeout.connect(self._consume_results)
        if autoconnect:
            QTimer.singleShot(0, self.connect)

    @Property("QVariantMap", notify=stateChanged)
    def state(self) -> dict[str, Any]:
        return self._state

    def _set_state(self, **sections: Any) -> None:
        """Publish changed sections from the GUI thread in a single QML update."""
        changed = {name: value for name, value in sections.items()
                   if self._state.get(name) != value}
        if changed:
            if "journal" in changed:
                retained = {Path(str(row.get("path", ""))) for row in
                            changed["journal"].get("draftImages", [])}
                retained.update(Path(str(row.get("path", "")))
                                for draft in changed["journal"].get("replyDraftImages", {}).values()
                                for row in draft)
                for path in self._owned_draft_images - retained:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self._owned_draft_images.intersection_update(retained)
            self._state = {**self._state, **changed}
            for name, value in changed.items():
                self.sectionChanged.emit(name, value)
            self.stateChanged.emit()

    def _set_status(self, message: str) -> None:
        self._set_state(status=message)

    def _identity(self) -> tuple[int, str] | None:
        if self.account is None:
            return None
        return (_row_value(self.account, "login"), _row_value(self.account, "server"))

    def _cancel_jobs(self) -> None:
        for kind, job in self._jobs.items():
            self._generations[kind] = self._generations.get(kind, 0) + 1
            job.cancelled.set()
        self._pending_jobs.clear()
        self._last_requested.clear()
        self._last_quote_at = 0.0

    def _clear_session(self, message: str, *, locked: bool = False,
                       current_account: Any = None) -> None:
        self._cancel_jobs()
        self.connected = False
        self.account = None
        self.symbol = None
        self.tick = None
        self.journal_account_key = None
        clean = _empty_state(self.symbol_name, self._state["theme"])
        clean["page"] = self._state["page"]
        clean["fullscreen"] = self._state["fullscreen"]
        clean["refreshIntervals"] = self._state["refreshIntervals"]
        clean["connection"] = {
            "connected": False, "locked": locked, "message": message,
            "currentAccount": (_account_map(current_account)
                               if current_account is not None else {}),
        }
        clean["status"] = message
        self._set_state(**clean)

    def check_account_access(self) -> bool:
        """Check the live terminal and revoke access when the USC identity changes."""
        if not self.connected or self.account is None:
            return False
        try:
            terminal = self._api.terminal_info()
            current = self._api.account_info()
        except Exception as exc:
            self._clear_session(f"MT5 账户读取失败：{exc}")
            return False
        if current is not None and not is_usc_account(current):
            self._clear_session("仅支持 USC 美分账户；当前账户已锁定",
                                locked=True, current_account=current)
            return False
        if terminal is None or not _row_value(terminal, "connected", False) or current is None:
            self._clear_session("MT5 连接中断，请重新连接")
            return False
        if (_row_value(current, "login"), _row_value(current, "server")) != self._identity():
            self._clear_session("MT5 账户已切换，请重新连接")
            return False
        self.account = current
        self._set_state(account=_account_map(current))
        return True

    def connect(self) -> None:
        """Reconnect to the selected local MT5 terminal (no trading calls)."""
        if self._closing:
            return
        self._cancel_jobs()
        if self._jobs:
            self._reconnect_pending = True
            self._set_status("正在等待当前读取结束，然后重新连接…")
            self._results_timer.start()
            return
        self._reconnect_pending = False
        self.connected = False
        self._set_state(connection={"connected": False, "locked": False,
                                    "message": "正在连接 MT5"}, status="正在连接 MT5…")
        try:
            if self.initialized:
                self._api.shutdown()
                self.initialized = False
            ready = (self._api.initialize(self.terminal_path) if self.terminal_path
                     else self._api.initialize())
            if not ready:
                raise RuntimeError(f"MT5 初始化失败：{self._api.last_error()}")
            self.initialized = True
            terminal = self._api.terminal_info()
            account = self._api.account_info()
            if account is not None and not is_usc_account(account):
                self._clear_session("仅支持 USC 美分账户；当前账户已锁定",
                                    locked=True, current_account=account)
                return
            if terminal is None or not _row_value(terminal, "connected", False) or account is None:
                raise RuntimeError("MT5 客户端未连接交易服务器或未登录账户")
            self.account = account
            self.journal_account_key = self._identity()
            self.connected = True
            self._set_state(connection={"connected": True, "locked": False,
                                        "message": "已连接"},
                            account=_account_map(account),
                            status=f"已连接 · {_row_value(account, 'server', '')}")
            self.poll(force=True)
        except (RuntimeError, ValueError, OSError, Exception) as exc:
            self._clear_session(str(exc))

    def _quote(self) -> None:
        """The small one-second quote/account read; history remains off-thread."""
        try:
            symbol = self._api.symbol_info(self.symbol_name)
            if symbol is None:
                raise RuntimeError(f"品种 {self.symbol_name} 不可用")
            if (not _row_value(symbol, "visible", True)
                    and not self._api.symbol_select(self.symbol_name, True)):
                raise RuntimeError(f"无法在市场报价中显示 {self.symbol_name}")
            tick = self._api.symbol_info_tick(self.symbol_name)
            bid, ask = _number(_row_value(tick, "bid")), _number(_row_value(tick, "ask"))
            if bid is None or ask is None or bid <= 0 or ask < bid:
                raise RuntimeError("当前报价不可用")
            self.symbol, self.tick = symbol, tick
            point = _number(_row_value(symbol, "point"))
            prior = self._state["dashboard"].get("previousClose")
            change = bid - prior if prior and prior > 0 else None
            stamp = (_number(_row_value(tick, "time_msc")) or 0) / 1000
            if stamp <= 0:
                stamp = _number(_row_value(tick, "time")) or 0
            quote_time = (datetime.fromtimestamp(stamp, timezone.utc).isoformat()
                          if stamp > 0 else "")
            self._set_state(market={
                "symbol": self.symbol_name, "bid": bid, "ask": ask,
                "spreadPoints": round((ask - bid) / point, 1) if point and point > 0 else None,
                "time": quote_time, "change": change,
                "changePct": change / prior * 100 if change is not None else None,
                "stale": (not quote_time or time.time() - stamp > 15),
            })
        except (RuntimeError, ValueError, OSError, OverflowError) as exc:
            self.symbol = self.tick = None
            self._set_state(market={**self._state["market"], "stale": True,
                                    "bid": None, "ask": None, "message": str(exc)})

    def poll(self, *, force: bool = False) -> None:
        if self._closing:
            return
        if self._reconnect_pending:
            if not self._jobs:
                self.connect()
            return
        if not self.connected or not self.check_account_access():
            return
        now = time.monotonic()
        intervals = self._state["refreshIntervals"]
        if force or now - self._last_quote_at >= intervals["quote"]:
            self._last_quote_at = now
            self._quote()
        else:
            market = self._state["market"]
            quote_time = market.get("time", "")
            if quote_time and not market.get("stale"):
                try:
                    expired = time.time() - datetime.fromisoformat(quote_time).timestamp() > 15
                except (ValueError, TypeError, OverflowError):
                    expired = True
                if expired:
                    self._set_state(market={**market, "stale": True})
        page = self._state["page"]
        if page == "dashboard":
            positions_due = (force or now - self._last_requested.get("book_positions", 0)
                             >= intervals["positions"])
            orders_due = (force or now - self._last_requested.get("book_orders", 0)
                          >= intervals["orders"])
            if positions_due or orders_due:
                self.refresh_books(force=force, include_positions=positions_due,
                                   include_orders=orders_due)
        page_intervals = {"dashboard": 60, "orders": intervals["orders"],
                          "journal": 30, "monitor": intervals["quote"]}
        if page in page_intervals and (force or now - self._last_requested.get(page, 0)
                                       >= page_intervals[page]):
            self._refresh_page(page, force=force)

    def _request_job(self, kind: str, key: tuple[Any, ...],
                     loader: Callable[[Any], dict[str, Any]], *, force: bool = False) -> None:
        if not self.connected or self._closing or self._identity() is None:
            return
        current = self._jobs.get(kind)
        if current is not None:
            if current.key == key and not force and kind not in self._pending_jobs:
                return
            if self._pending_jobs.get(kind, (None,))[0] == key:
                return
            self._generations[kind] = self._generations.get(kind, 0) + 1
            current.cancelled.set()
            self._pending_jobs[kind] = (key, loader)
        else:
            self._start_job(kind, key, loader)
        self._last_requested[kind] = time.monotonic()
        if kind != "books":
            section_name = "overview" if kind == "orders" else kind
            section = {**self._state[section_name], "loading": True}
            self._set_state(**{section_name: section})

    def _start_job(self, kind: str, key: tuple[Any, ...],
                   loader: Callable[[Any], dict[str, Any]]) -> None:
        generation = self._generations.get(kind, 0) + 1
        self._generations[kind] = generation
        cancelled = Event()
        identity = self._identity()
        if identity is None:
            return

        def run() -> None:
            result = None
            error = ""
            try:
                api = _GuardedReadOnlyApi(self._api, cancelled, identity)
                api.verify()
                result = loader(api)
                api.verify()
            except Exception as exc:
                error = str(exc)
            self._results.put((kind, generation, key, result, error))

        thread = Thread(target=run, name=f"mt5-qml-{kind}", daemon=True)
        self._jobs[kind] = _Job(thread, cancelled, generation, key)
        try:
            thread.start()
        except RuntimeError as exc:
            self._jobs.pop(kind, None)
            self._set_status(f"{kind} 读取无法启动：{exc}")
            return
        self._results_timer.start()

    def _consume_results(self) -> None:
        while True:
            try:
                item = self._results.get_nowait()
            except Empty:
                break
            self._result_waiting[item[0]] = item
        for kind, item in tuple(self._result_waiting.items()):
            job = self._jobs.get(kind)
            if job is not None and job.thread.is_alive():
                continue
            self._result_waiting.pop(kind, None)
            self._jobs.pop(kind, None)
            if self._closing:
                continue
            pending = self._pending_jobs.pop(kind, None)
            if pending is not None and self.connected:
                key, loader = pending
                if key[0] == self._identity():
                    self._start_job(kind, key, loader)
                continue
            _, generation, key, data, error = item
            if (generation != self._generations.get(kind)
                    or key[0] != self._identity() or not self.connected):
                continue
            if not self.check_account_access():
                continue
            if error:
                section_name = ("overview" if kind == "orders" else
                                "dashboard" if kind == "books" else kind)
                updated = {**self._state[section_name]}
                if kind != "books":
                    updated["loading"] = False
                    updated["errors"] = [error]
                    if kind == "controls":
                        updated["status"] = f"目标读取失败：{error}"
                    elif kind == "journal":
                        updated["notice"] = f"行情日志读取失败：{error}"
                    elif kind == "monitor":
                        updated["status"] = "error"
                        updated["reason"] = error
                else:
                    updated["bookError"] = error
                self._set_state(**{section_name: updated})
                self._set_status(f"{kind} 读取失败：{error}")
                continue
            if data is not None:
                if kind == "monitor":
                    data["history"] = self._monitor_history(data)
                if kind == "journal":
                    # A worker snapshot may predate edits made in the composer.
                    current_journal = self._state["journal"]
                    data["draftImages"] = current_journal.get("draftImages", [])
                    data["publishedRevision"] = current_journal.get("publishedRevision", 0)
                    data["replyDraftImages"] = current_journal.get("replyDraftImages", {})
                    data["replyPublishedRevision"] = current_journal.get("replyPublishedRevision", 0)
                    data["replyPublishedPostId"] = current_journal.get("replyPublishedPostId", 0)
                if kind == "orders":
                    self._set_state(overview=data)
                elif kind == "books":
                    self._set_state(dashboard={**self._state["dashboard"], **data})
                elif kind == "dashboard":
                    self._set_state(dashboard={**self._state["dashboard"], **data})
                else:
                    self._set_state(**{kind: data})
                if kind == "dashboard":
                    now = time.monotonic()
                    if now - self._last_quote_at >= self._state["refreshIntervals"]["quote"]:
                        self._last_quote_at = now
                        self._quote()
                self._set_status({"dashboard": "总览看板已更新",
                                  "orders": "交易概览已更新",
                                  "journal": "行情日志已更新",
                                  "books": "当前持仓与挂单已更新",
                                  "monitor": "实验行情已更新"}.get(kind, "已更新"))
        if not self._jobs and not self._result_waiting:
            self._results_timer.stop()
            if self._reconnect_pending:
                QTimer.singleShot(0, self.connect)

    def _monitor_history(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        history = list(self._state["monitor"].get("history", []))
        if data.get("status") == "live":
            history.append({"observedAt": data.get("observedAt", ""),
                            "barTime": data.get("barTime", ""),
                            "spreadPoints": data.get("emaSpreadPoints")})
        return history[-60:]

    def refresh_books(self, *, force: bool = False,
                      include_positions: bool = True,
                      include_orders: bool = True) -> None:
        """Read the due XAUUSDc book sections without polling both at once."""
        if not include_positions and not include_orders:
            return
        if not self.connected or not self.check_account_access():
            return
        identity, symbol = self._identity(), self.symbol_name

        def load(api: Any) -> dict[str, Any]:
            active = api.positions_get(symbol=symbol) if include_positions else ()
            pending = api.orders_get(symbol=symbol) if include_orders else ()
            if (include_positions and active is None) or (include_orders and pending is None):
                raise RuntimeError(f"当前持仓或挂单读取失败：{api.last_error()}")
            buy_type = getattr(api, "POSITION_TYPE_BUY", 0)
            order_types = {
                getattr(api, f"ORDER_TYPE_{name}", None): name.replace("_", " ")
                for name in ("BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP",
                             "BUY_STOP_LIMIT", "SELL_STOP_LIMIT")
            }
            result: dict[str, Any] = {"bookError": ""}
            if include_positions:
                result["positions"] = [
                    {"ticket": _row_value(row, "ticket"), "symbol": _row_value(row, "symbol"),
                     "side": "BUY" if _row_value(row, "type") == buy_type else "SELL",
                     "volume": _number(_row_value(row, "volume")),
                     "priceOpen": _number(_row_value(row, "price_open")),
                     "currentPrice": _number(_row_value(row, "price_current")),
                     "sl": _number(_row_value(row, "sl")),
                     "tp": _number(_row_value(row, "tp")),
                     "profit": _number(_row_value(row, "profit"))}
                    for row in active]
            if include_orders:
                result["orders"] = [
                    {"ticket": _row_value(row, "ticket"), "symbol": _row_value(row, "symbol"),
                     "type": order_types.get(_row_value(row, "type"), "PENDING"),
                     "volume": _number(_row_value(row, "volume_current")),
                     "priceOpen": _number(_row_value(row, "price_open")),
                     "sl": _number(_row_value(row, "sl")),
                     "tp": _number(_row_value(row, "tp"))}
                    for row in pending]
            return result

        self._request_job("books", (identity, include_positions, include_orders),
                          load, force=force)
        requested_at = time.monotonic()
        if include_positions:
            self._last_requested["book_positions"] = requested_at
        if include_orders:
            self._last_requested["book_orders"] = requested_at

    def _refresh_page(self, page: str, *, force: bool = False) -> None:
        if not self.connected or not self.check_account_access():
            return
        identity = self._identity()
        if page == "dashboard":
            if self.tick is None:
                return
            account, tick, symbol = self.account, self.tick, self.symbol_name

            def load(api: Any) -> dict[str, Any]:
                data = load_dashboard(symbol, account, tick, api=api,
                                      include_books=False)
                return {
                    "loading": False, "candles": [
                        {"time": _iso(row.time), "open": row.open, "high": row.high,
                         "low": row.low, "close": row.close, "volume": row.tick_volume,
                         "complete": row.is_complete} for row in data.candles],
                    "dailyPnl": [{"day": _iso(row.day), "amount": _number(row.amount)}
                                 for row in data.daily_pnl],
                    "previousClose": data.previous_close, "dayChange": data.day_change,
                    "dayChangePct": data.day_change_pct,
                    "metrics": {"realizedToday": _number(data.realized_today),
                                "realized30d": _number(data.realized_30d),
                                "positionsCount": data.positions_count,
                                "ordersCount": data.orders_count,
                                "balance": data.balance, "equity": data.equity,
                                "floatingPnl": data.floating_pnl,
                                "marginUsed": data.margin_used,
                                "marginLevelPct": data.margin_level_pct},
                    "errors": list(data.errors), "updatedAt": _iso(datetime.now(timezone.utc)),
                }

            self._request_job("dashboard", (identity,), load, force=force)
        elif page == "orders":
            overview = self._state["overview"]
            scope, days = overview.get("scope", "symbol"), int(overview.get("days", 30))
            symbol = self.symbol_name if scope == "symbol" else None
            account = self.account

            def load(api: Any) -> dict[str, Any]:
                data = load_order_analytics(account, symbol=symbol, days=days, api=api)
                return {
                    "loading": False, "scope": scope, "days": days,
                    "metrics": {
                        "pendingCount": data.pending_count, "pendingLots": data.pending_lots,
                        "positionCount": data.position_count, "positionLots": data.position_lots,
                        "dealCount": data.deal_count, "buyLots": data.buy_lots,
                        "sellLots": data.sell_lots, "tradedLots": data.traded_lots,
                        "netTradingCashflow": _number(data.net_trading_cashflow),
                        "maxDrawdown": _number(data.account_max_drawdown),
                        "currentDrawdown": _number(data.account_current_drawdown),
                    },
                    "accountCurve": [
                        {"day": _iso(row.day), "dailyCashflow": _number(row.daily_cashflow),
                         "cumulative": _number(row.cumulative),
                         "drawdown": _number(row.drawdown)} for row in data.account_curve],
                    "dailyExecution": [
                        {"day": _iso(row.day), "buyLots": row.buy_lots,
                         "sellLots": row.sell_lots, "dealCount": row.deal_count}
                        for row in data.daily_execution],
                    "pendingOrders": [_order_row(row) for row in data.pending_orders],
                    "recentOrders": [_order_row(row) for row in data.recent_orders],
                    "recentDeals": [_deal_row(row) for row in data.recent_deals],
                    "statusCounts": [{"label": row.label, "count": row.count}
                                     for row in data.status_counts],
                    "errors": list(data.errors), "asOf": _iso(data.as_of),
                }

            self._request_job("orders", (identity, scope, days), load, force=force)
        elif page == "journal":
            self.refresh_journal(force=force)
        elif page == "monitor":
            tolerance = self._state["monitor"]["tolerancePoints"]
            symbol = self.symbol_name

            def load(api: Any) -> dict[str, Any]:
                snapshot = fetch_m1_ema_snapshot(symbol, api=api,
                                                 tolerance_points=tolerance)
                return {
                    "loading": False, "status": snapshot.status,
                    "reason": snapshot.reason, "bid": snapshot.bid,
                    "ask": snapshot.ask,
                    "quoteAgeSeconds": snapshot.quote_age_seconds,
                    "emaValues": {str(period): _number(value)
                                  for period, value in snapshot.ema_values.items()},
                    "emaSpreadPoints": _number(snapshot.ema_spread_points),
                    "tolerancePoints": _number(snapshot.tolerance_points),
                    "barTime": _iso(snapshot.bar_time),
                    "observedAt": _iso(snapshot.observed_at),
                    "history": [],
                    "includesFormingBar": snapshot.includes_forming_bar,
                    "aligned": snapshot.aligned,
                }

            self._request_job("monitor", (identity, tolerance), load, force=force)

    def refresh_journal(self, *, force: bool = False) -> None:
        """Load account-scoped posts, heatmap, and linked position outcomes."""
        repo = self.journal_repo
        if repo is None:
            self._set_state(journal={**self._state["journal"],
                                     "notice": self.journal_error or "本地日志不可用"})
            return
        if not self.connected or not self.check_account_access():
            return
        account_key = self._identity()
        if account_key is None:
            return
        self.journal_account_key = account_key
        snapshot = self._state["journal"]
        page = max(1, int(snapshot.get("page", 1)))
        year = int(snapshot.get("year", datetime.now(BEIJING_TZ).year))
        draft_images = list(snapshot.get("draftImages", []))
        symbol = self.symbol_name

        def load(api: Any) -> dict[str, Any]:
            errors: list[str] = []
            active = ()
            try:
                # The service verifies the USC account around each MT5 read.
                sync_result = sync_closed_positions(repo, account_key, api=api)
                errors.extend(sync_result.errors)
                active = load_open_positions(account_key, symbol, api=api)
            except (RuntimeError, ValueError, OSError) as exc:
                errors.append(f"持仓结果核对失败：{exc}")
            feed = repo.list_posts(account_key, page, 10)
            if feed.page > max(1, feed.total_pages):
                feed = repo.list_posts(account_key, max(1, feed.total_pages), 10)
            trailing = repo.activity(account_key, 365)
            today = datetime.now(BEIJING_TZ).date()
            years = sorted({today.year, year, *repo.available_years(account_key)},
                           reverse=True)
            annual = repo.activity_year(account_key, year)
            recent30 = sum(count for day, count in trailing.items()
                           if today - timedelta(days=29) <= day <= today)
            return {
                "loading": False,
                "accountLabel": f"账户 {account_key[0]} · {account_key[1]}",
                "canPublish": True, "notice": "；".join(errors),
                "total": feed.total, "recent30": recent30,
                "activeDays": sum(1 for count in trailing.values() if count),
                "year": year, "years": years, "yearTotal": sum(annual.values()),
                "heatmap": {_iso(day): count for day, count in annual.items()},
                "posts": [_journal_post(post) for post in feed.posts],
                "page": feed.page, "totalPages": max(1, feed.total_pages),
                "positions": [_position_row(position) for position in active],
                "draftImages": draft_images,
                "publishedRevision": snapshot.get("publishedRevision", 0),
                "replyDraftImages": snapshot.get("replyDraftImages", {}),
                "replyPublishedRevision": snapshot.get("replyPublishedRevision", 0),
                "replyPublishedPostId": snapshot.get("replyPublishedPostId", 0),
                "today": today.isoformat(),
            }

        self._request_job("journal", (account_key, page, year), load, force=force)

    @Slot(result=bool)
    def hasJournalImageOnClipboard(self) -> bool:
        """Let the composer intercept Ctrl+V only for an actual image."""
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData() if clipboard is not None else None
        return bool(mime is not None and mime.hasImage())

    def _journal_draft_images(self, post_id: int = 0) -> list[dict[str, str]]:
        journal = self._state["journal"]
        return list(journal.get("replyDraftImages", {}).get(str(post_id), [])
                    if post_id else journal.get("draftImages", []))

    def _set_journal_draft_images(self, images: list[dict[str, str]], post_id: int = 0) -> None:
        journal = dict(self._state["journal"])
        if post_id:
            drafts = dict(journal.get("replyDraftImages", {}))
            if images:
                drafts[str(post_id)] = images
            else:
                drafts.pop(str(post_id), None)
            journal["replyDraftImages"] = drafts
        else:
            journal["draftImages"] = images
        self._set_state(journal=journal)

    def _check_journal_image_target(self, post_id: int) -> bool:
        if self.journal_repo is None:
            self._set_status(self.journal_error or "本地日志不可用")
            return False
        if not self.check_account_access():
            return False
        if post_id < 0 or (post_id and not self.journal_repo.has_post(self._identity(), post_id)):
            self._set_status("帖子不存在或不属于当前账户")
            return False
        return True

    def _choose_journal_images(self, post_id: int = 0) -> None:
        if not self._check_journal_image_target(post_id):
            return
        account_key = self._identity()
        names, _ = QFileDialog.getOpenFileNames(
            None, "选择回复图片" if post_id else "选择日志图片", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
        if not self._check_journal_image_target(post_id) or self._identity() != account_key:
            return
        draft = self._journal_draft_images(post_id)
        selected = {image["path"] for image in draft}
        for name in names:
            path = Path(name).resolve()
            if str(path) in selected:
                continue
            if len(draft) >= MAX_IMAGES:
                self._set_status(f"每条回复最多 {MAX_IMAGES} 张图片" if post_id
                                 else f"每篇日志最多附带 {MAX_IMAGES} 张图片")
                break
            try:
                self.journal_repo._check_image(path)
            except (OSError, ValueError) as exc:
                self._set_status(f"无法添加图片：{exc}")
                continue
            draft.append({"path": str(path), "name": path.name,
                          "url": QUrl.fromLocalFile(str(path)).toString()})
            selected.add(str(path))
        self._set_journal_draft_images(draft, post_id)

    def _paste_journal_image(self, post_id: int = 0) -> None:
        if not self._check_journal_image_target(post_id):
            return
        draft = self._journal_draft_images(post_id)
        if len(draft) >= MAX_IMAGES:
            self._set_status(f"每条回复最多 {MAX_IMAGES} 张图片" if post_id
                             else f"每篇日志最多附带 {MAX_IMAGES} 张图片")
            return
        account_key = self._identity()
        if account_key is None:
            return
        clipboard = QGuiApplication.clipboard()
        image = clipboard.image() if clipboard is not None else None
        if image is None or image.isNull():
            self._set_status("剪贴板里没有可粘贴的图片")
            return
        if image.width() * image.height() > 40_000_000:
            self._set_status("图片尺寸过大，最多 4000 万像素")
            return

        # Drafts are local, account-scoped files. The repository copies them
        # into its permanent image store only after publication succeeds.
        login, server = account_key
        server_key = sha256(server.encode("utf-8")).hexdigest()[:16]
        path = self.journal_repo.base_dir / "drafts" / str(login) / server_key / f"{uuid4().hex}.png"
        added = False
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not image.save(str(path), "PNG"):
                raise ValueError("剪贴板图片无法保存")
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("单张图片不得超过 8 MiB")
            self.journal_repo._check_image(path)
            if not self._check_journal_image_target(post_id) or self._identity() != account_key:
                return
            self._owned_draft_images.add(path)
            draft.append({"path": str(path), "name": "粘贴的图片.png",
                          "url": QUrl.fromLocalFile(str(path)).toString()})
            self._set_journal_draft_images(draft, post_id)
            self._set_status("已从剪贴板添加图片")
            added = True
        except (OSError, ValueError) as exc:
            self._set_status(f"无法粘贴图片：{exc}")
        finally:
            if not added:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    @Slot(str, "QVariantMap")
    def perform(self, action: str, payload: dict[str, Any]) -> None:
        """Dispatch a QML action. A subclass owns every account mutation."""
        values = dict(payload or {})
        if action == "reconnect":
            self.connect()
            return
        if self._state["connection"].get("locked"):
            self._set_status("仅支持 USC 美分账户；请切换账户后重新连接")
            return
        if action == "navigate":
            page = str(values.get("page", ""))
            if page not in PAGE_NAMES:
                self._set_status("页面不存在")
                return
            self._set_state(page=page)
            if self.connected:
                self._refresh_page(page)
            elif page == "journal" and self.journal_repo is None:
                self._set_status(self.journal_error)
            return
        if action == "toggleTheme":
            theme = "light" if self._state["theme"] == "dark" else "dark"
            self._set_state(theme=theme)
            if not save_theme(theme):
                self._set_status("主题已切换，但偏好设置未能保存")
            return
        if action == "toggleFullscreen":
            self._set_state(fullscreen=not self._state["fullscreen"])
            return
        if action == "setRefreshInterval":
            kind = str(values.get("kind", ""))
            seconds = values.get("seconds")
            if (kind not in DEFAULT_REFRESH_INTERVALS or isinstance(seconds, bool)
                    or not isinstance(seconds, (int, float))
                    or not math.isfinite(seconds) or int(seconds) != seconds
                    or not 1 <= seconds <= MAX_REFRESH_SECONDS):
                self._set_status("刷新间隔必须是 1–3600 秒的整数")
                return
            seconds = int(seconds)
            updated = {**self._state["refreshIntervals"], kind: seconds}
            self._set_state(refreshIntervals=updated)
            label = {"quote": "报价", "positions": "持仓", "orders": "订单"}[kind]
            self._set_status(f"{label}刷新间隔已设为 {seconds} 秒")
            if not _save_refresh_intervals(updated):
                self._set_status("刷新间隔已生效，但保存失败；重启后将恢复原设置")
            return
        if action == "refresh":
            page = str(values.get("page") or self._state["page"])
            if page in PAGE_NAMES:
                if page == "controls":
                    self._refresh_page(page, force=True)
                    return
                self.poll(force=(page == self._state["page"]))
                if page != self._state["page"]:
                    self._refresh_page(page, force=True)
            return
        if action == "overviewFilters":
            scope = str(values.get("scope", "symbol"))
            try:
                days = int(values.get("days", 30))
            except (ValueError, TypeError):
                days = 0
            if scope not in {"symbol", "account"} or not 1 <= days <= 365:
                self._set_status("交易概览筛选条件无效")
                return
            self._set_state(overview={**self._state["overview"],
                                      "scope": scope, "days": days})
            self._refresh_page("orders", force=True)
            return
        if action in {"journalRefresh", "journalPage", "journalYear"}:
            journal = dict(self._state["journal"])
            if action == "journalPage":
                try:
                    page = int(values.get("page", 1))
                except (ValueError, TypeError):
                    page = 0
                if page < 1 or page > max(1, journal.get("totalPages", 1)):
                    return
                journal["page"] = page
            elif action == "journalYear":
                try:
                    year = int(values.get("year", 0))
                except (ValueError, TypeError):
                    year = 0
                if year not in journal.get("years", []):
                    return
                journal["year"] = year
            self._set_state(journal=journal)
            self.refresh_journal(force=True)
            return
        if action in {"journalChooseImages", "journalPasteImage", "journalRemoveImage",
                      "journalDiscardReply"}:
            try:
                post_id = int(values.get("postId", 0))
                if action == "journalChooseImages":
                    self._choose_journal_images(post_id)
                elif action == "journalPasteImage":
                    self._paste_journal_image(post_id)
                elif action == "journalDiscardReply":
                    if post_id > 0:
                        self._set_journal_draft_images([], post_id)
                else:
                    target = str(values.get("path", ""))
                    draft = [image for image in self._journal_draft_images(post_id)
                             if image.get("path") != target]
                    self._set_journal_draft_images(draft, post_id)
            except (ValueError, TypeError, OSError, sqlite3.Error) as exc:
                self._set_status(f"图片操作未完成：{exc}")
            return
        if action == "monitorTolerance":
            value = _number(values.get("points"))
            if value is None or not 0 <= value <= 1000:
                self._set_status("EMA 允许偏差点数必须在 0–1000 之间")
                return
            self._set_state(monitor={**self._state["monitor"],
                                     "tolerancePoints": value})
            self._refresh_page("monitor", force=True)
            return
        if action == "monitorRefresh":
            self._refresh_page("monitor", force=True)
            return
        self._perform_protected(action, values)

    def _perform_protected(self, action: str, payload: dict[str, Any]) -> None:
        """Override to implement write actions with a fresh USC account check."""
        self._set_status(f"当前版本尚未提供操作：{action}")

    def shutdown(self) -> None:
        """Stop timers and discard background results during app teardown."""
        self._closing = True
        self._timer.stop()
        self._results_timer.stop()
        self._cancel_jobs()
        for path in self._owned_draft_images:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self._owned_draft_images.clear()
        if self.initialized and not self._jobs:
            self._api.shutdown()
            self.initialized = False

    def close(self) -> None:
        """Convenient Qt aboutToQuit hook."""
        self.shutdown()
