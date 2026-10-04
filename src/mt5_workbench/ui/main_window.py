"""PySide6 application shell and MT5 UI orchestration."""

from __future__ import annotations

import argparse
from queue import Empty, Queue
import sqlite3
import sys
from threading import Event, Thread
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import MetaTrader5 as mt5
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QScrollArea, QStackedWidget, QTableWidget, QVBoxLayout, QWidget,
)

from mt5_workbench.config import DEFAULT_SYMBOL
from mt5_workbench.domain.account_policy import is_usc_account
from mt5_workbench.domain.position_optimizer import Optimization, optimize
from mt5_workbench.infrastructure.journal_db import JournalRepository
from mt5_workbench.infrastructure.market import orders, positions, symbol_and_tick
from mt5_workbench.services.account_controls import close_request, execute_batch, load_targets
from mt5_workbench.services.dashboard_data import DashboardData, load_dashboard
from mt5_workbench.services.order_analytics import load_order_analytics
from mt5_workbench.services.ema_monitor import fetch_m1_ema_snapshot
from mt5_workbench.services.journal_positions import load_open_positions, sync_closed_positions
from mt5_workbench.services.trade_execution import (
    build_requests, check_requests, existing_duplicates, send_checked,
)
from mt5_workbench.ui.components import button, icon, label, make_table, fill_table
from mt5_workbench.ui.dialogs.account_lock import AccountLockDialog
from mt5_workbench.ui.pages.controls import ControlsPage
from mt5_workbench.ui.pages.dashboard import DashboardPage
from mt5_workbench.ui.pages.ema_monitor import EmaMonitorPage
from mt5_workbench.ui.pages.journal import MarketJournalPage
from mt5_workbench.ui.pages.optimizer import MODES, OptimizerPage
from mt5_workbench.ui.pages.overview import OrdersPage
from mt5_workbench.ui.theme import (
    FONT_FAMILIES, FONT_SIZES, MAX_CONTENT_WIDTH, MIN_WINDOW_SIZE, SHELL_GAP,
    THEMES, WINDOW_GUTTER,
    load_theme, save_theme, style_sheet,
)


def state_directory(kind: str) -> Path:
    base = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[3])
    return base / "state" / kind


class _JournalSyncCancelled(RuntimeError):
    """Stop a superseded background reconciliation between MT5 calls."""


class _CancellableJournalApi:
    """Keep a stale worker from starting another MT5 read after cancellation."""

    def __init__(self, api, cancelled: Event):
        self._api = api
        self._cancelled = cancelled

    def __getattr__(self, name: str):
        member = getattr(self._api, name)
        if name not in {"account_info", "positions_get", "history_deals_get"}:
            return member

        def guarded(*args, **kwargs):
            if self._cancelled.is_set():
                raise _JournalSyncCancelled("行情日志同步已取消")
            value = member(*args, **kwargs)
            if self._cancelled.is_set():
                raise _JournalSyncCancelled("行情日志同步已取消")
            return value

        return guarded


def _run_journal_sync(repo: JournalRepository, account_key: tuple[int, str],
                      generation: int, cancelled: Event, results: Queue) -> None:
    """Worker thread: never touches a Qt widget or the MainWindow."""
    result = None
    error = ""
    try:
        if cancelled.is_set():
            raise _JournalSyncCancelled("行情日志同步已取消")
        result = sync_closed_positions(repo, account_key,
                                       api=_CancellableJournalApi(mt5, cancelled))
    except Exception as exc:
        # A worker exception must always reach the GUI thread so the single
        # in-flight slot can be released and a later refresh can retry.
        error = str(exc)
    results.put((generation, account_key, result, error))



class MainWindow(QMainWindow):
    def __init__(self, symbol_name: str = DEFAULT_SYMBOL,
                 terminal_path: str | None = None, *,
                 autoconnect: bool = True, start_timer: bool = True,
                 journal_repository: JournalRepository | None = None):
        super().__init__()
        self.symbol_name = symbol_name
        self.terminal_path = terminal_path
        self.theme = load_theme()
        self.palette = THEMES[self.theme]
        self.connected = False
        self.initialized = False
        self.account = None
        self.symbol = None
        self.tick = None
        self.dashboard_data: DashboardData | None = None
        self.result: Optimization | None = None
        self.result_account: tuple[int, str] | None = None
        self.suggested_types: tuple[str, ...] = ()
        self.account_lock: AccountLockDialog | None = None
        self.active_dialog: QDialog | None = None
        self._closing = False
        self.last_books = 0.0
        self.last_dashboard = 0.0
        self.last_analytics = 0.0
        self.last_journal_sync = 0.0
        self.journal_account_key: tuple[int, str] | None = None
        self.journal_error = ""
        self._journal_sync_generation = 0
        self._journal_sync_thread: Thread | None = None
        self._journal_sync_cancel: Event | None = None
        self._journal_sync_results: Queue = Queue()
        self._journal_sync_pending = None
        if journal_repository is not None:
            self.journal_repo = journal_repository
        else:
            try:
                self.journal_repo = JournalRepository(state_directory("journal"))
            except (OSError, sqlite3.Error) as exc:
                self.journal_repo = None
                self.journal_error = f"本地日志无法打开：{exc}"
        self.fullscreen = False
        self.setWindowTitle("MT5 黄金交易工作台")
        self.setMinimumSize(*MIN_WINDOW_SIZE)
        self.resize(1500, 950)
        self._build_shell()
        self._apply_theme()
        self._journal_sync_poll = QTimer(self)
        self._journal_sync_poll.setInterval(100)
        self._journal_sync_poll.timeout.connect(self._consume_journal_sync_result)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        if start_timer:
            self.timer.start()
        if autoconnect:
            QTimer.singleShot(0, self.connect)

    def _build_shell(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        shell = QVBoxLayout(central)
        shell.setContentsMargins(WINDOW_GUTTER, WINDOW_GUTTER,
                                 WINDOW_GUTTER, WINDOW_GUTTER)
        shell.setSpacing(SHELL_GAP)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        header_layout.setSpacing(12)
        brand = label("MT5", size=FONT_SIZES["brand"], bold=True)
        header_layout.addWidget(brand)
        header_layout.addWidget(label("黄金交易工作台", kind="muted"))
        header_layout.addStretch()
        self.connection_badge = label("● 未连接", kind="danger")
        header_layout.addWidget(self.connection_badge)
        self.theme_button = button("日间", self.theme, "sun")
        self.theme_button.clicked.connect(self.toggle_theme)
        header_layout.addWidget(self.theme_button)
        self.fullscreen_button = button("全屏", self.theme, "fullscreen")
        self.fullscreen_button.clicked.connect(self.toggle_fullscreen)
        header_layout.addWidget(self.fullscreen_button)
        self.reconnect_button = button("重新连接", self.theme, "refresh")
        self.reconnect_button.clicked.connect(self.connect)
        header_layout.addWidget(self.reconnect_button)
        shell.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(SHELL_GAP)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        self.sidebar = sidebar
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(11, 24, 11, 20)
        side.setSpacing(6)
        self.workspace_caption = label("工作区", kind="muted")
        side.addWidget(self.workspace_caption)
        self.nav: dict[str, QPushButton] = {}
        for key, title, graphic in (
                ("dashboard", "总览看板", "dashboard"),
                ("orders", "交易概览", "orders"),
                ("journal", "行情日志", "journal"),
                ("optimizer", "下单管理", "allocation"),
                ("controls", "控制面板", "controls"),
                ("monitor", "行情监听", "chart-line")):
            control = button(title, self.theme, graphic, "nav")
            control.setCheckable(True)
            control.clicked.connect(lambda _checked=False, page=key: self.show_page(page))
            side.addWidget(control)
            self.nav[key] = control
        self.nav["dashboard"].setChecked(True)
        self.side_symbol_label = label("观察品种", kind="muted")
        self.side_symbol = label(self.symbol_name, size=15, bold=True)
        side.addSpacing(28)
        side.addWidget(self.side_symbol_label)
        side.addWidget(self.side_symbol)
        side.addStretch()
        self.side_note = label("交易操作需预览确认\n下单管理仅发 LIMIT 挂单", kind="muted")
        side.addWidget(self.side_note)
        body.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.pages: dict[str, QWidget] = {}
        self.dashboard = DashboardPage(self.symbol_name, self.palette, self.theme)
        self.order_page = OrdersPage(self.symbol_name, self.palette)
        self.journal = MarketJournalPage(self.palette)
        self.optimizer = OptimizerPage(self.palette, self.theme)
        self.controls = ControlsPage(self.symbol_name, self.palette)
        self.monitor = EmaMonitorPage(self.symbol_name, self.palette)
        for key, page in (("dashboard", self.dashboard), ("orders", self.order_page),
                           ("journal", self.journal),
                           ("optimizer", self.optimizer), ("controls", self.controls),
                           ("monitor", self.monitor)):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            page.setMaximumWidth(MAX_CONTENT_WIDTH)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            self.pages[key] = scroll
        self.current_page = "dashboard"
        body.addWidget(self.stack, 1)
        shell.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 8, 24, 9)
        self.status_label = label("等待连接 MT5", kind="muted", size=FONT_SIZES["caption"])
        footer_layout.addWidget(self.status_label, 1)
        self.refresh_note = label("报价/监听 1 秒 · 持仓 5 秒 · 订单 30 秒 · 图表 60 秒",
                                  kind="muted", size=FONT_SIZES["caption"])
        footer_layout.addWidget(self.refresh_note)
        shell.addWidget(footer)

        self.order_page.refresh_requested.connect(self.refresh_order_analytics)
        self.journal.refresh_requested.connect(lambda: self.refresh_journal(force_sync=True))
        self.journal.year_requested.connect(self._journal_year_requested)
        self.journal.page_requested.connect(self._journal_page_requested)
        self.journal.publish_requested.connect(self.publish_journal)
        self.journal.delete_requested.connect(self.delete_journal_post)
        self.controls.refresh_requested.connect(self.refresh_controls)
        self.controls.preview_requested.connect(self.preview_control)
        self.monitor.refresh_requested.connect(self.refresh_monitor)
        self.monitor.tolerance_changed.connect(self._monitor_tolerance_changed)
        self.optimizer.calculate_requested.connect(self.calculate)
        self.optimizer.preview_requested.connect(self.preview_orders)
        self.optimizer.copy_requested.connect(self.copy_result)
        self.optimizer.inputs_changed.connect(self.invalidate_result)
        full_action = QAction(self)
        full_action.setShortcut("F11")
        full_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(full_action)
        exit_action = QAction(self)
        exit_action.setShortcut("Escape")
        exit_action.triggered.connect(self.exit_fullscreen)
        self.addAction(exit_action)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        compact = self.width() < 1380
        self.sidebar.setFixedWidth(156 if compact else 215)
        self.workspace_caption.setVisible(not compact)
        self.side_symbol_label.setVisible(not compact)
        self.side_symbol.setVisible(not compact)
        self.side_note.setVisible(not compact)
        self.refresh_note.setVisible(not compact)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        base_font = QFont()
        base_font.setFamilies(FONT_FAMILIES)
        base_font.setPixelSize(FONT_SIZES["body"])
        app.setFont(base_font)
        app.setStyleSheet(style_sheet(self.palette))
        self.theme_button.setText("日间" if self.theme == "dark" else "夜间")
        self.theme_button.setIcon(icon("sun" if self.theme == "dark" else "moon", self.theme))
        self.fullscreen_button.setIcon(icon("exit-fullscreen" if self.fullscreen
                                           else "fullscreen", self.theme))
        self.reconnect_button.setIcon(icon("refresh", self.theme))
        for key, graphic in (("dashboard", "dashboard"), ("orders", "orders"),
                              ("journal", "journal"),
                              ("optimizer", "allocation"), ("controls", "controls"),
                              ("monitor", "chart-line")):
            selected = "-active" if self.current_page == key else ""
            self.nav[key].setIcon(icon(graphic + selected, self.theme, 24))
        self.dashboard.set_palette(self.palette, self.theme)
        self.order_page.set_palette(self.palette)
        self.journal.set_palette(self.palette)
        self.optimizer.set_palette(self.palette, self.theme)
        self.controls.set_palette(self.palette)
        self.monitor.set_palette(self.palette)

    def toggle_theme(self) -> None:
        if self.account_lock is not None or (self.connected and not self.check_account_access()):
            return
        self.theme = "light" if self.theme == "dark" else "dark"
        self.palette = THEMES[self.theme]
        saved = save_theme(self.theme)
        self._apply_theme()
        if not saved:
            self.status_label.setText("主题已切换，但偏好设置未能保存")

    def toggle_fullscreen(self) -> None:
        if self.account_lock is not None or (self.connected and not self.check_account_access()):
            return
        self.fullscreen = not self.fullscreen
        if self.fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()
        self.fullscreen_button.setText("退出全屏" if self.fullscreen else "全屏")
        self.fullscreen_button.setIcon(icon("exit-fullscreen" if self.fullscreen
                                           else "fullscreen", self.theme))

    def exit_fullscreen(self) -> None:
        if self.fullscreen:
            self.toggle_fullscreen()

    def show_page(self, name: str) -> None:
        if self.account_lock is not None or (self.connected and not self.check_account_access()):
            return
        self.current_page = name
        self.stack.setCurrentWidget(self.pages[name])
        for key, control in self.nav.items():
            control.setChecked(key == name)
        self._apply_theme()
        if name == "dashboard" and self.connected and self.tick is not None and (
                time.monotonic() - self.last_dashboard >= 60):
            self.refresh_dashboard_data()
        if name == "orders" and self.connected and time.monotonic() - self.last_analytics >= 30:
            self.refresh_order_analytics()
        if name == "journal":
            self.refresh_journal(force_sync=True)
        if name == "controls" and self.connected:
            self.refresh_controls()
        if name == "monitor" and self.connected:
            self.refresh_monitor()

    def _shutdown(self) -> None:
        self._cancel_journal_sync()
        if self.initialized:
            mt5.shutdown()
            self.initialized = False

    def _clear_session(self, note: str) -> None:
        self._cancel_journal_sync()
        self.connected = False
        self.account = None
        self.symbol = None
        self.tick = None
        self.dashboard_data = None
        self.last_books = self.last_dashboard = self.last_analytics = 0.0
        self.last_journal_sync = 0.0
        self.connection_badge.setText("● 未连接")
        self.connection_badge.setObjectName("danger")
        self.connection_badge.style().unpolish(self.connection_badge)
        self.connection_badge.style().polish(self.connection_badge)
        self.dashboard.clear(note)
        self.order_page.clear(note)
        self.controls.clear(note)
        self.monitor.clear(note)
        self.journal.set_can_publish(False)
        self.journal.set_notice(note)
        self.invalidate_result("连接已断开，请重新连接并计算。")
        self.status_label.setText(note)

    def _lock_unsupported(self, account) -> None:
        self._shutdown()
        self._clear_session("仅支持 USC 美分账户；当前账户已锁定")
        self.journal.dismiss_composer()
        if self.active_dialog is not None:
            self.active_dialog.reject()
            self.active_dialog = None
        if self.account_lock is None:
            self.account_lock = AccountLockDialog(self, account)
        else:
            self.account_lock.update_account(account)
        self.account_lock.show()
        self.account_lock.raise_()
        self.account_lock.activateWindow()

    def _dismiss_lock(self) -> None:
        dialog = self.account_lock
        self.account_lock = None
        if dialog is not None:
            dialog.accept()
            dialog.deleteLater()

    def check_account_access(self) -> bool:
        if not self.connected or self.account is None:
            return False
        terminal = mt5.terminal_info()
        current = mt5.account_info()
        if current is not None and not is_usc_account(current):
            self._lock_unsupported(current)
            return False
        if terminal is None or not terminal.connected or current is None:
            self._clear_session("MT5 连接中断，请重新连接")
            return False
        if (current.login, current.server) != (self.account.login, self.account.server):
            self.journal.dismiss_composer()
            self._shutdown()
            self._clear_session("账户已切换，请重新连接")
            return False
        return True

    def connect(self) -> None:
        self._shutdown()
        self.connected = False
        try:
            ready = (mt5.initialize(self.terminal_path) if self.terminal_path
                     else mt5.initialize())
            if not ready:
                raise RuntimeError(f"MT5 初始化失败：{mt5.last_error()}")
            self.initialized = True
            terminal = mt5.terminal_info()
            account = mt5.account_info()
            if account is not None and not is_usc_account(account):
                self._lock_unsupported(account)
                return
            if terminal is None or not terminal.connected or account is None:
                raise RuntimeError("MT5 客户端未连接交易服务器或未登录账户")
            self.account = account
            self.journal_account_key = (account.login, account.server)
            self.connected = True
            self.connection_badge.setText("● 已连接")
            self.connection_badge.setObjectName("positive")
            self.connection_badge.style().unpolish(self.connection_badge)
            self.connection_badge.style().polish(self.connection_badge)
            self.status_label.setText(f"已连接 · {account.server}")
            self.refresh(force=True)
            if self.connected:
                self._dismiss_lock()
        except (RuntimeError, ValueError, OSError) as exc:
            self._shutdown()
            self._clear_session(str(exc))
            if self.account_lock is not None:
                self.account_lock.note.setText(f"重新检查失败：{exc}")

    def poll(self) -> None:
        if self.connected:
            try:
                self.refresh()
            except (RuntimeError, ValueError, OSError) as exc:
                self.status_label.setText(f"刷新失败：{exc}")
                if self.current_page == "monitor":
                    self.monitor.set_snapshot({"status": "error", "reason": f"行情刷新失败：{exc}"})

    def refresh(self, *, force: bool = False) -> None:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if account is not None and not is_usc_account(account):
            self._lock_unsupported(account)
            return
        if terminal is None or not terminal.connected or account is None:
            self._clear_session("MT5 连接中断，请点击重新连接")
            return
        if self.account is not None and (account.login, account.server) != (
                self.account.login, self.account.server):
            self._cancel_journal_sync()
            self.journal.dismiss_composer()
            if self.active_dialog is not None:
                self.active_dialog.reject()
                self.active_dialog = None
            self.dashboard_data = None
            self.last_dashboard = self.last_analytics = 0.0
            self.order_page.clear("账户已切换，正在读取新账户的记录")
            self.monitor.clear("账户已切换，正在读取新账户的行情")
            self.invalidate_result("账户已切换，请重新计算配置。")
            self.status_label.setText("账户已切换，原交易预览已取消")
        self.account = account
        self.journal_account_key = (account.login, account.server)
        self.dashboard.set_account(account)
        now = time.monotonic()
        if force or now - self.last_books >= 5:
            self.refresh_books()
            if self.current_page == "controls":
                self.refresh_controls()
            if not self.connected:
                return
            self.last_books = time.monotonic()
        if self.current_page == "orders" and (force or now - self.last_analytics >= 30):
            self.refresh_order_analytics()
            if not self.connected:
                return
        if self.current_page == "journal" and (
                force or (self._journal_sync_thread is None
                          and now - self.last_journal_sync >= 30)):
            self.refresh_journal(force_sync=True)
            if not self.connected:
                return
        try:
            symbol, tick = symbol_and_tick(self.symbol_name)
        except (RuntimeError, ValueError, OSError) as exc:
            self.symbol = self.tick = None
            self.dashboard_data = None
            self.last_dashboard = 0.0
            self.dashboard.clear_market()
            self.monitor.set_snapshot({"status": "error", "reason": f"行情读取失败：{exc}"})
            self.dashboard.dashboard_note.setText(f"行情读取失败：{exc}")
            self.status_label.setText(f"行情读取失败：{exc}")
            return
        self.symbol, self.tick = symbol, tick
        self.dashboard.set_tick(symbol, tick,
                                self.dashboard_data.previous_close if self.dashboard_data else None,
                                terminal.trade_allowed)
        if force or (self.current_page == "dashboard" and now - self.last_dashboard >= 60):
            self.refresh_dashboard_data()
        if self.current_page == "monitor" and self.connected:
            self.refresh_monitor()
        if self.connected:
            self.check_account_access()

    def refresh_books(self) -> None:
        if not self.check_account_access():
            return
        active = positions(self.symbol_name)
        pending = orders(self.symbol_name)
        if not self.check_account_access():
            return
        self.dashboard.set_books(active, pending)

    def _monitor_tolerance_changed(self, _value: float) -> None:
        if self.current_page == "monitor" and self.connected:
            self.refresh_monitor()

    def refresh_monitor(self) -> None:
        """Read one M1 EMA snapshot for the visible, authorised account."""
        if not self.connected or self.account is None:
            self.monitor.clear("请先连接 USC 美分账户")
            return
        if not self.check_account_access():
            return
        identity = (self.account.login, self.account.server)
        try:
            snapshot = fetch_m1_ema_snapshot(
                self.symbol_name, tolerance_points=self.monitor.tolerance_points)
        except (RuntimeError, ValueError, OSError) as exc:
            self.monitor.set_snapshot({"status": "error", "reason": f"EMA 行情读取失败：{exc}"})
            return
        if not self.check_account_access():
            return
        if (self.account.login, self.account.server) != identity:
            self.monitor.clear("账户已切换，请重新读取行情")
            return
        self.monitor.set_snapshot(snapshot)

    def refresh_dashboard_data(self) -> None:
        if self.account is None or self.tick is None or not self.check_account_access():
            return
        try:
            data = load_dashboard(self.symbol_name, self.account, self.tick)
        except (RuntimeError, ValueError, OSError) as exc:
            self.dashboard.dashboard_note.setText(f"图表读取失败：{exc}")
            return
        if not self.check_account_access():
            return
        self.dashboard_data = data
        self.last_dashboard = time.monotonic()
        self.dashboard.set_data(data, self.symbol.digits if self.symbol else 3)
        if self.symbol is not None and self.tick is not None:
            terminal = mt5.terminal_info()
            self.dashboard.set_tick(self.symbol, self.tick, data.previous_close,
                                    bool(terminal and terminal.trade_allowed))

    def refresh_order_analytics(self) -> None:
        if not self.connected or self.account is None:
            self.order_page.clear("请先连接 MT5")
            return
        if not self.check_account_access():
            return
        symbol, days = self.order_page.filters()
        identity = (self.account.login, self.account.server)
        try:
            data = load_order_analytics(self.account, symbol=symbol, days=days)
            current = mt5.account_info()
            if current is not None and not is_usc_account(current):
                self._lock_unsupported(current)
                return
            if current is None or (current.login, current.server) != identity:
                raise RuntimeError("读取期间账户已切换，已丢弃本次订单数据")
        except (RuntimeError, ValueError, OSError) as exc:
            self.order_page.clear(f"订单读取失败：{exc}")
            self.last_analytics = time.monotonic()
            return
        self.order_page.set_data(data, self.account)
        self.last_analytics = time.monotonic()
        self.status_label.setText("交易概览已更新" if not data.errors else
                                  "交易概览已更新，部分 MT5 数据不可用")

    def _journal_page_requested(self, page_number: int) -> None:
        self.refresh_journal(page=page_number)

    def _journal_year_requested(self, year: int) -> None:
        """Change the contribution calendar without another MT5 read."""
        repo = self.journal_repo
        account_key = self.journal_account_key
        if repo is None or account_key != self.journal.activity_account_key:
            return
        try:
            years = repo.available_years(account_key)
            if year != date.today().year and year not in years:
                raise ValueError("该年份没有本账户日志")
            activity = repo.activity_year(account_key, year)
            self.journal.set_year_activity(year, activity, years)
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.journal.set_notice(f"按年份读取记录轨迹失败：{exc}")

    def _cancel_journal_sync(self) -> None:
        """Invalidate in-flight results without waiting for a blocking MT5 call."""
        self._journal_sync_generation += 1
        if self._journal_sync_cancel is not None:
            self._journal_sync_cancel.set()
        self.last_journal_sync = 0.0

    def _start_journal_sync(self, account_key: tuple[int, str]) -> bool:
        """At most one background reconciliation may run for this window."""
        if self._closing or self.journal_repo is None or self._journal_sync_thread is not None:
            return False
        cancelled = Event()
        generation = self._journal_sync_generation
        thread = Thread(
            target=_run_journal_sync,
            args=(self.journal_repo, account_key, generation, cancelled,
                  self._journal_sync_results),
            name="mt5-journal-sync", daemon=True,
        )
        self._journal_sync_cancel = cancelled
        self._journal_sync_thread = thread
        self.last_journal_sync = time.monotonic()
        try:
            thread.start()
        except RuntimeError:
            self._journal_sync_cancel = None
            self._journal_sync_thread = None
            self.last_journal_sync = 0.0
            raise
        self._journal_sync_poll.start()
        return True

    def _consume_journal_sync_result(self) -> None:
        """Apply completed worker data only on the GUI thread and to its account."""
        if self._journal_sync_pending is None:
            try:
                self._journal_sync_pending = self._journal_sync_results.get_nowait()
            except Empty:
                return
        thread = self._journal_sync_thread
        if thread is not None and thread.is_alive():
            return
        generation, account_key, result, error = self._journal_sync_pending
        self._journal_sync_pending = None
        self._journal_sync_thread = None
        self._journal_sync_cancel = None
        self._journal_sync_poll.stop()
        if self._closing:
            return
        current_key = ((self.account.login, self.account.server)
                       if self.account is not None else None)
        if (generation != self._journal_sync_generation or not self.connected
                or current_key != account_key or self.journal_account_key != account_key):
            # A different account may have become visible while the old worker
            # finished.  Its next reconciliation starts only after this one ends.
            if self.connected and self.current_page == "journal" and current_key is not None:
                self.refresh_journal(force_sync=True)
            return
        if not self.check_account_access() or generation != self._journal_sync_generation:
            return
        self.last_journal_sync = time.monotonic()
        if self.current_page == "journal":
            self.refresh_journal()
        if error:
            self.journal.set_notice(f"持仓结果核对失败：{error}")
        elif result is not None and result.errors:
            self.journal.set_notice("；".join(result.errors))

    def refresh_journal(self, *, force_sync: bool = False,
                        page: int | None = None) -> None:
        """Read the local feed and reconcile linked positions when MT5 is ready."""
        repo = self.journal_repo
        if repo is None:
            self.journal.set_can_publish(False)
            self.journal.set_notice(self.journal_error or "本地日志不可用")
            return
        account_key = self.journal_account_key
        active = ()
        positions_current = False
        errors: list[str] = []
        can_publish = False
        if self.connected and self.account is not None and self.check_account_access():
            account_key = (self.account.login, self.account.server)
            self.journal_account_key = account_key
            can_publish = True
            try:
                active = load_open_positions(account_key, self.symbol_name)
                positions_current = True
                if force_sync or time.monotonic() - self.last_journal_sync >= 30:
                    self._start_journal_sync(account_key)
            except (RuntimeError, ValueError, OSError) as exc:
                errors.append(f"持仓同步失败：{exc}")
                if not self.check_account_access():
                    can_publish = False
        try:
            page_number = page if page is not None else self.journal.current_page
            feed = repo.list_posts(account_key, page_number, 10)
            if feed.page > max(1, feed.total_pages):
                feed = repo.list_posts(account_key, max(1, feed.total_pages), 10)
            activity = repo.activity(account_key, 365)
            years = repo.available_years(account_key)
            selected_year = (self.journal.selected_year
                             if account_key == self.journal.activity_account_key
                             else date.today().year)
            year_activity = repo.activity_year(account_key, selected_year)
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.journal.set_can_publish(False)
            self.journal.set_notice(f"读取本地日志失败：{exc}")
            return
        if account_key is None:
            account_label = "连接 USC 账户后查看本机日志"
        else:
            account_label = f"账户 {account_key[0]} · {account_key[1]}"
            if not self.connected:
                account_label += " · 离线浏览"
        self.journal.set_content(feed, activity, active, account_label,
                                 positions_current=positions_current,
                                 year_activity=year_activity,
                                 available_years=years,
                                 account_key=account_key,
                                 selected_year=selected_year)
        self.journal.set_can_publish(can_publish)
        self.journal.set_notice("；".join(errors) if errors else
                                ("MT5 未连接，暂不能发帖或更新持仓结果" if not self.connected
                                 else ""))

    def publish_journal(self, body: str, image_paths: tuple[str, ...],
                        position_ids: tuple[int, ...]) -> None:
        """Save a post only after rechecking its selected live positions."""
        if self.journal_repo is None:
            self.journal.publish_failed(self.journal_error or "本地日志不可用")
            return
        if not self.check_account_access():
            self.journal.publish_failed("请先连接 USC 美分账户")
            return
        account_key = (self.account.login, self.account.server)
        try:
            if len(set(position_ids)) != len(position_ids):
                raise ValueError("关联持仓不能重复")
            selected = ()
            if position_ids:
                live = load_open_positions(account_key, self.symbol_name)
                by_id = {item.position_id: item for item in live}
                missing = set(position_ids) - by_id.keys()
                if missing:
                    raise ValueError("选中的持仓已变化或平仓，请刷新后重新选择")
                selected = tuple(by_id[position_id] for position_id in position_ids)
            if not self.check_account_access():
                raise RuntimeError("账户已切换，发帖已取消")
            self.journal_repo.create_post(
                account_key, body, tuple(Path(path) for path in image_paths), selected)
        except (OSError, sqlite3.Error, RuntimeError, ValueError) as exc:
            self.journal.publish_failed(str(exc))
            return
        self.journal.publish_succeeded()
        self.refresh_journal(page=1)
        self.status_label.setText("行情日志已保存到本机")

    def delete_journal_post(self, post_id: int) -> None:
        """Delete a local post after an explicit confirmation."""
        if self.connected and not self.check_account_access():
            return
        if self.journal_repo is None or self.journal_account_key is None:
            self.journal.set_notice("当前没有可编辑的本地账户日志")
            return
        answer = QMessageBox.question(
            self, "删除行情日志", "删除这篇帖子及其本地图片？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.journal_repo.delete_post(self.journal_account_key, post_id)
        except (OSError, sqlite3.Error, ValueError) as exc:
            self.journal.set_notice(f"删除失败：{exc}")
            return
        if deleted:
            self.refresh_journal()
            self.status_label.setText("本地帖子已删除")
        else:
            self.journal.set_notice("帖子不存在或不属于当前账户")

    def refresh_controls(self) -> None:
        if not self.connected or self.account is None:
            self.controls.clear()
            return
        if not self.check_account_access():
            return
        scope = self.controls.scope()
        try:
            active = load_targets("close", scope, self.symbol_name)
            pending = load_targets("remove", scope, self.symbol_name)
        except (RuntimeError, ValueError, OSError) as exc:
            self.controls.clear(f"目标读取失败：{exc}")
            return
        if self.check_account_access():
            self.controls.set_data(self.account, active, pending)

    def invalidate_result(self, message: str = "参数已修改，请重新计算配置。") -> None:
        self.result = None
        self.result_account = None
        self.suggested_types = ()
        self.optimizer.clear(message)

    def _suggested_type(self, entry_price: Decimal, side: str) -> str:
        if self.tick is None:
            return "等待报价"
        if side == "SELL":
            return ("SELL LIMIT" if entry_price > Decimal(str(self.tick.ask))
                    else "不可作为 LIMIT")
        return ("BUY LIMIT" if entry_price < Decimal(str(self.tick.bid))
                else "不可作为 LIMIT")

    def calculate(self) -> None:
        if not self.check_account_access():
            self.optimizer.clear("请先连接 USC 美分账户")
            return
        try:
            current = mt5.account_info()
            if current is None or (current.login, current.server) != (
                    self.account.login, self.account.server):
                raise RuntimeError("账户已切换，请等待工作台重新核对账户")
            if not is_usc_account(current):
                self._lock_unsupported(current)
                return
            symbol = mt5.symbol_info(self.symbol_name)
            if symbol is None:
                raise RuntimeError(f"找不到品种 {self.symbol_name}")
            low, high, stop, target, budget, usage, levels, mode, weights = (
                self.optimizer.read_inputs())
            result = optimize(symbol, current.currency, low, high, stop, budget,
                              levels=levels, mode=mode, weights=weights,
                              budget_usage_percent=usage, take_profit=target)
            self.result = result
            self.result_account = (current.login, current.server)
            self.suggested_types = tuple(
                self._suggested_type(entry.price, result.side)
                for entry in result.entries)
            comparisons = []
            for display, other_mode in MODES.items():
                try:
                    other = optimize(
                        symbol, current.currency, low, high, stop, budget,
                        levels=levels, mode=other_mode,
                        weights=weights if other_mode == "weighted" else None,
                        budget_usage_percent=usage, take_profit=target)
                    comparisons.append(f"{display.split(' · ')[0]} {other.total_volume} 手")
                except (ValueError, RuntimeError, InvalidOperation):
                    continue
            quote_stale = self.tick is None or time.time() - self.tick.time_msc / 1000 > 15
            if quote_stale:
                warning = "最近报价已过期；挂单类型仅供参考。未计入滑点、跳空、手续费和保证金限制。"
            elif any(item not in {"BUY LIMIT", "SELL LIMIT"}
                     for item in self.suggested_types):
                warning = "部分档位不是有效的 LIMIT 候选；请调整目标价或误差度并重新计算。"
            else:
                warning = "全部档位按当前报价可作为 LIMIT 候选；未计入滑点、跳空、手续费和保证金限制。"
            can_preview = (not quote_stale and
                           all(item in {"BUY LIMIT", "SELL LIMIT"}
                               for item in self.suggested_types))
            if can_preview:
                try:
                    build_requests(result, symbol, self.tick, current)
                except (ValueError, RuntimeError) as exc:
                    can_preview = False
                    warning = f"当前不满足 LIMIT 挂单条件：{exc}。测算结果仅供查看。"
            self.optimizer.set_result(
                result, self.suggested_types,
                "同一风险上限对照：" + "   /   ".join(comparisons), warning, stop,
                can_preview=can_preview)
            self.status_label.setText("LIMIT 下单方案已计算；没有向 MT5 发送订单")
        except (ValueError, RuntimeError, OSError, InvalidOperation) as exc:
            self.invalidate_result(f"无法计算：{exc}")

    def copy_result(self) -> None:
        if self.result is None or not self.check_account_access():
            return
        first = self.result.entries[0]
        stop = (first.price + first.stop_distance if self.result.side == "SELL"
                else first.price - first.stop_distance)
        lines = [
            f"{self.symbol_name} {self.result.side} LIMIT 下单方案",
            f"入场区间 {self.result.range_low}～{self.result.range_high}",
            f"预算 {self.result.budget_usd:.2f} USD × "
            f"{self.result.budget_usage_percent:g}% = "
            f"风险上限 {self.result.risk_cap_usd:.2f} USD · "
            f"总手数 {self.result.total_volume} lot · "
            f"估算风险 {self.result.total_risk_usd:.2f} USD",
            f"统一止损 {stop} · 统一止盈 "
            f"{self.result.take_profit if self.result.take_profit is not None else '未设置'}",
        ]
        for kind, item in zip(self.suggested_types, self.result.entries):
            lines.append(f"{kind} @ {item.price} · {item.volume} lot · "
                         f"风险 {item.risk_usd:.2f} USD")
        lines.append("仅供测算；未提交 MT5 订单。")
        QApplication.clipboard().setText("\n".join(lines))
        self.status_label.setText("配置已复制到剪贴板")

    def _fresh_order_plan(self):
        if self.result is None or self.result_account is None:
            raise RuntimeError("请先计算 LIMIT 下单方案")
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or not terminal.connected or not terminal.trade_allowed:
            raise RuntimeError("MT5 终端未连接或未允许自动交易")
        if account is None or (account.login, account.server) != self.result_account:
            raise RuntimeError("账户已切换，请重新计算")
        if not is_usc_account(account):
            self._lock_unsupported(account)
            raise RuntimeError("仅支持 USC 美分账户，请在 MT5 中切换账户")
        symbol, tick = symbol_and_tick(self.symbol_name)
        low, high, stop, target, budget, usage, levels, mode, weights = (
            self.optimizer.read_inputs())
        current_result = optimize(
            symbol, account.currency, low, high, stop, budget,
            levels=levels, mode=mode, weights=weights,
            budget_usage_percent=usage, take_profit=target)
        if current_result != self.result:
            raise RuntimeError("品种参数或测算结果已变化，请重新计算")
        requests = build_requests(current_result, symbol, tick, account)
        duplicates = existing_duplicates(requests)
        if duplicates:
            raise RuntimeError(f"已有相同挂单 {duplicates}，请先核对 MT5")
        return account, symbol, tick, current_result, requests

    def _confirm(self, title: str, heading: str, details: str,
                 columns: tuple[str, ...], rows, warning: str,
                 confirm_text: str, *, danger: bool = False) -> bool:
        values = tuple(rows)
        dialog = QDialog(self)
        self.active_dialog = dialog
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.resize(850, max(470, min(640, 370 + len(values) * 42)))
        dialog.setMinimumSize(690, 470)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(label(heading, kind="pageTitle"))
        layout.addWidget(label(details, kind="muted", wrap=True))
        table = make_table(columns, 190)
        fill_table(table, values)
        layout.addWidget(table, 1)
        layout.addWidget(label(warning, kind="warning", wrap=True))
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = button("取消", self.theme, "cancel")
        cancel.clicked.connect(dialog.reject)
        actions.addWidget(cancel)
        approve = button(confirm_text, self.theme, "confirm",
                         "danger" if danger else "primary")
        approve.clicked.connect(dialog.accept)
        actions.addWidget(approve)
        layout.addLayout(actions)
        try:
            return dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            if self.active_dialog is dialog:
                self.active_dialog = None
            dialog.deleteLater()

    def preview_orders(self) -> None:
        if not self.check_account_access():
            return
        try:
            account, symbol, tick, result, requests = self._fresh_order_plan()
            check_requests(requests)
        except (ValueError, RuntimeError, OSError, InvalidOperation) as exc:
            if self.account_lock is None:
                QMessageBox.critical(self, "无法预览挂单", str(exc))
            self.status_label.setText(f"挂单预检未通过：{exc}")
            return
        stop = requests[0]["sl"]
        target = requests[0]["tp"] or "—"
        rows = (
            ("SELL LIMIT" if result.side == "SELL" else "BUY LIMIT",
             request["price"], request["volume"], stop, target,
             f"{entry.risk_usd:.2f}")
            for request, entry in zip(requests, result.entries))
        approved = self._confirm(
            "确认发送 LIMIT 挂单", "发送挂单前核对",
            f"账户 {account.login} · {account.server} · {account.currency}   "
            f"品种 {symbol.name}   Bid {tick.bid:.{symbol.digits}f} / "
            f"Ask {tick.ask:.{symbol.digits}f}\n"
            f"入场区间 {result.range_low}～{result.range_high} · "
            f"{result.side} LIMIT · {len(requests)} 笔 · 总手数 "
            f"{result.total_volume} lot · 估算止损风险 "
            f"{result.total_risk_usd:.2f} USD / 上限 {result.risk_cap_usd:.2f} USD",
            ("类型", "入场价", "手数", "统一止损", "统一止盈", "风险 USD"),
            rows,
            "确认后将发送真实挂单。所有档位已通过 order_check；挂单长期有效（GTC）。"
            "实际成交、跳空和手续费可能使亏损超过估算，已有仓位风险未计入。"
            "失败时停止剩余挂单，且不会自动重试。",
            "确认发送")
        if not approved or not self.check_account_access():
            return
        try:
            fresh_account, _symbol, _tick, fresh_result, fresh_requests = (
                self._fresh_order_plan())
            if fresh_requests != requests or fresh_result != result:
                raise RuntimeError("报价或挂单配置已变化，请重新预览")
            sent = send_checked(fresh_account, fresh_requests,
                                state_directory("executions"))
            tickets = ", ".join(str(row["order"]) for row in sent)
            self.invalidate_result("挂单已发送；请在总览看板核对挂单。")
            self.refresh(force=True)
            self.status_label.setText(f"已提交 {len(sent)} 笔 LIMIT 挂单：{tickets}")
            QMessageBox.information(self, "挂单已提交",
                                    f"已提交 {len(sent)} 笔挂单。\n订单号：{tickets}\n"
                                    "请在 MT5 中核对实际状态。")
        except (ValueError, RuntimeError, OSError, InvalidOperation) as exc:
            self.invalidate_result("发送中止；请核对 MT5 挂单及本地发送记录。")
            self.status_label.setText(f"发送中止：{exc}")
            try:
                self.refresh(force=True)
            except (ValueError, RuntimeError, OSError):
                pass
            if self.account_lock is None:
                QMessageBox.critical(self, "挂单未全部提交", str(exc))

    def preview_control(self, kind: str) -> None:
        if not self.check_account_access():
            return
        title = "全部平仓" if kind == "close" else "删除所有挂单"
        try:
            if kind not in {"close", "remove"}:
                raise ValueError("未知控制操作")
            account = mt5.account_info()
            if account is None or (account.login, account.server) != (
                    self.account.login, self.account.server):
                raise RuntimeError("账户已切换，请刷新后重试")
            if not is_usc_account(account):
                self._lock_unsupported(account)
                return
            scope = self.controls.scope()
            targets = load_targets(kind, scope, self.symbol_name)
            if not targets:
                QMessageBox.information(self, title, "所选范围内没有需要处理的目标。")
                return
            deviation = self.controls.deviation() if kind == "close" else 0
            if kind == "close":
                for target in targets:
                    close_request(target, deviation)
        except (ValueError, RuntimeError, OSError) as exc:
            self.controls.set_status(f"{title}预览失败：{exc}")
            if self.account_lock is None:
                QMessageBox.critical(self, f"无法预览{title}", str(exc))
            return
        rows = (
            (row.ticket, row.symbol,
             ("BUY" if row.type == mt5.POSITION_TYPE_BUY else "SELL")
             if kind == "close" else ORDER_NAMES.get(row.type, str(row.type)),
             row.volume if kind == "close" else row.volume_initial,
             row.price_open, row.sl or "—")
            for row in targets)
        volume = sum(row.volume if kind == "close" else row.volume_initial
                     for row in targets)
        approved = self._confirm(
            f"确认{title}", f"确认{title}",
            f"账户 {account.login} · {account.server} · {account.currency}   "
            f"范围 {self.symbol_name if scope == 'symbol' else '整个账户 · 所有品种'}\n"
            f"将处理 {len(targets)} 笔 · 共 {volume:g} 手" +
            (f" · 最大偏差 {deviation} 点" if kind == "close" else ""),
            ("Ticket", "品种", "方向 / 类型", "手数", "价格", "止损"), rows,
            ("确认后将按市价逐笔平仓；最终成交价可能不同，现有挂单仍可能成交。"
             if kind == "close" else
             "确认后将逐笔撤销挂单；若撤销前成交，该笔可能无法删除。") +
            "若中途失败，后续目标停止处理且不会自动重试。",
            f"确认{title}", danger=kind == "close")
        if not approved or not self.check_account_access():
            return
        try:
            completed = execute_batch(kind, scope, self.symbol_name, account,
                                      targets, deviation,
                                      state_directory("controls"))
            self.refresh(force=True)
            self.refresh_controls()
            note = f"{title}已完成：{len(completed)} 笔；请在 MT5 核对实际状态。"
            self.controls.set_status(note)
            self.status_label.setText(note)
            QMessageBox.information(self, title, note)
        except (ValueError, RuntimeError, OSError) as exc:
            try:
                self.refresh(force=True)
                self.refresh_controls()
            except (ValueError, RuntimeError, OSError):
                pass
            note = f"{title}已停止：{exc}；可能已有部分请求执行，请先核对 MT5 和本地记录。"
            self.controls.set_status(note)
            self.status_label.setText(note)
            if self.account_lock is None:
                QMessageBox.critical(self, f"{title}已停止", note)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._closing = True
        self.timer.stop()
        self._journal_sync_poll.stop()
        self._cancel_journal_sync()
        self.journal.dismiss_composer()
        if self.active_dialog is not None:
            self.active_dialog.reject()
            self.active_dialog = None
        if self.account_lock is not None:
            self._dismiss_lock()
        self._shutdown()
        super().closeEvent(event)



def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, choices=[DEFAULT_SYMBOL])
    parser.add_argument("--terminal", help="可选的 terminal64.exe 路径")
    return parser.parse_args()



def main() -> int:
    args = parse_args()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("MT5 黄金交易工作台")
    window = MainWindow(args.symbol, args.terminal)
    window.show()
    return app.exec()


App = MainWindow


if __name__ == "__main__":
    sys.exit(main())
