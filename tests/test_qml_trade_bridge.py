"""Offline confirmation checks for the Qt Quick trading bridge."""

from __future__ import annotations

import os
import tempfile
from threading import Event
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import MetaTrader5 as mt5
from PySide6.QtWidgets import QApplication

from mt5_workbench.ui import qml_trade_bridge as module


def _account(login: int = 101):
    return SimpleNamespace(
        login=login, server="test-server", currency="USC", name="Test",
        balance=10000, equity=10000, profit=0, margin=0, margin_free=10000,
        margin_level=0, trade_allowed=True, trade_expert=True,
    )


class FakeApi:
    def __init__(self):
        self.current = _account()
        self.sent = []
        self.active_orders = ()
        self.active_positions = ()
        self.symbol = SimpleNamespace(
            name="XAUUSDc", visible=True, point=0.01, trade_tick_size=0.01,
            volume_min=0.01, volume_max=100.0, volume_step=0.01,
            trade_mode=mt5.SYMBOL_TRADE_MODE_FULL,
            order_mode=2 | 16 | 32, trade_stops_level=0, volume_limit=0,
            filling_mode=1, trade_exemode=mt5.SYMBOL_TRADE_EXECUTION_MARKET,
            digits=2,
        )

    def account_info(self):
        return self.current

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=True)

    def symbol_info(self, _name):
        return self.symbol

    def symbol_info_tick(self, _name):
        return SimpleNamespace(bid=4194.9, ask=4195.0,
                               time_msc=int(time.time() * 1000))

    def order_calc_profit(self, _kind, _symbol, volume, entry, stop):
        return -abs(entry - stop) * volume * 100

    def orders_get(self, **_kwargs):
        return self.active_orders

    def positions_get(self, **_kwargs):
        return self.active_positions

    def order_check(self, _request):
        return SimpleNamespace(retcode=0, comment="ok")

    def order_send(self, request):
        self.sent.append(dict(request))
        return SimpleNamespace(retcode=mt5.TRADE_RETCODE_PLACED,
                               order=9000 + len(self.sent), deal=0, comment="ok")

    def last_error(self):
        return (0, "ok")


FIELDS = {
    "budget": "0.11", "usage": "95", "center": "4200", "tolerance": "1",
    "stop": "4205", "takeProfit": "", "levels": "2",
    "mode": "max_lots_ladder", "weights": "1,1",
}


class QmlTradeBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_bridge(self):
        api = FakeApi()
        bridge = module.QmlTradingBridge(
            autoconnect=False, start_timer=False,
            journal_repository=object(), api=api,
        )
        bridge.connected = True
        bridge.account = api.current
        bridge._set_state(connection={"connected": True, "locked": False,
                                      "message": "已连接"})
        # A confirmed operation may request a read-only UI refresh. These
        # tests isolate order_send and do not need a dashboard history worker.
        bridge.poll = lambda **_kwargs: None
        self.addCleanup(bridge.close)
        return bridge, api

    def test_preview_and_cancel_never_send(self):
        bridge, api = self.make_bridge()
        bridge.perform("entryCalculate", FIELDS)
        self.assertTrue(bridge.state["optimizer"]["canPreview"])
        self.assertEqual([row["volume"] for row in bridge.state["optimizer"]["rows"]],
                         ["0.01", "0.01"])
        bridge.perform("entryPreview", FIELDS)
        self.assertTrue(bridge.state["confirmation"]["token"])
        self.assertEqual(api.sent, [])
        bridge.perform("cancelConfirm", {})
        self.assertEqual(bridge.state["confirmation"], {})
        self.assertEqual(api.sent, [])

    def test_confirmation_sends_only_previewed_minimum_lots_once(self):
        bridge, api = self.make_bridge()
        with tempfile.TemporaryDirectory() as temp, patch.object(
                module, "_records_dir", return_value=Path(temp)):
            bridge.perform("entryCalculate", FIELDS)
            bridge.perform("entryPreview", FIELDS)
            token = bridge.state["confirmation"]["token"]
            bridge.perform("confirm", {"token": token})
            self.assertEqual(len(api.sent), 2)
            self.assertTrue(all(row["volume"] == 0.01 for row in api.sent))
            bridge.perform("confirm", {"token": token})
            self.assertEqual(len(api.sent), 2)

    def test_account_switch_after_preview_never_sends(self):
        bridge, api = self.make_bridge()
        bridge.perform("entryCalculate", FIELDS)
        bridge.perform("entryPreview", FIELDS)
        token = bridge.state["confirmation"]["token"]
        api.current = _account(202)
        bridge.perform("confirm", {"token": token})
        self.assertEqual(api.sent, [])
        self.assertFalse(bridge.state["connection"]["connected"])

    def test_basic_preview_cancel_and_optional_protection(self):
        bridge, api = self.make_bridge()
        fields = {"side": "SELL", "price": "4200", "volume": "0.01", "sl": "", "tp": ""}
        bridge.perform("basicPreview", fields)
        preview = bridge.state["confirmation"]
        self.assertEqual(preview["title"], "确认基础限价单")
        self.assertIn("风险未限定", preview["warning"])
        self.assertEqual(api.sent, [])
        bridge.perform("cancelConfirm", {})
        self.assertEqual(api.sent, [])
        bridge.perform("confirm", {"token": preview["token"]})
        self.assertEqual(api.sent, [])

    def test_basic_confirmation_sends_one_minimum_limit_once(self):
        for side, price, sl, tp in (("BUY", "4190", "4180", "4200"),
                                    ("SELL", "4200", "4210", "4190"),
                                    ("SELL", "4200", "", "")):
            with self.subTest(side=side):
                bridge, api = self.make_bridge()
                fields = {"side": side, "price": price, "volume": "0.01", "sl": sl, "tp": tp}
                bridge.perform("basicPreview", fields)
                self.assertEqual(bridge.state["basicOrder"]["risk"],
                                 "0.10 USD" if sl else "未设止损，风险未限定")
                token = bridge.state["confirmation"]["token"]
                self.assertEqual(api.sent, [])
                with tempfile.TemporaryDirectory() as temp, patch.object(
                        module, "_records_dir", return_value=Path(temp)):
                    bridge.perform("confirm", {"token": token})
                    bridge.perform("confirm", {"token": token})
                    self.assertEqual(len(api.sent), 1)
                    self.assertEqual(api.sent[0]["action"], mt5.TRADE_ACTION_PENDING)
                    self.assertEqual(api.sent[0]["volume"], 0.01)
                    self.assertEqual(api.sent[0]["type"], mt5.ORDER_TYPE_BUY_LIMIT
                                     if side == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT)
                    self.assertEqual(api.sent[0]["sl"], float(sl or 0))
                    self.assertEqual(api.sent[0]["tp"], float(tp or 0))

    def test_basic_respects_symbol_constraints_and_account_policy(self):
        for changes in ({"order_mode": 0}, {"order_mode": 2 | 32},
                        {"order_mode": 2 | 16}, {"volume_min": 0.02},
                        {"trade_mode": mt5.SYMBOL_TRADE_MODE_DISABLED},
                        {"trade_stops_level": 500}, {"name": "XAUUSD"}):
            with self.subTest(changes=changes):
                bridge, api = self.make_bridge()
                for key, value in changes.items():
                    setattr(api.symbol, key, value)
                bridge.perform("basicPreview", {"side": "SELL", "price": "4200",
                              "volume": "0.01", "sl": "4210", "tp": "4190"})
                self.assertTrue(bridge.state["basicOrder"]["error"])
                self.assertEqual(bridge.state["confirmation"], {})
                self.assertEqual(api.sent, [])
        bridge, api = self.make_bridge()
        api.current.currency = "USD"
        bridge.perform("basicPreview", {"side": "SELL", "price": "4200",
                      "volume": "0.01", "sl": "4210", "tp": ""})
        self.assertTrue(bridge.state["connection"]["locked"])
        self.assertEqual(api.sent, [])

    def test_basic_confirmation_rechecks_account_quote_and_permissions(self):
        for change in ("account", "quote", "permissions", "expired", "duplicate"):
            with self.subTest(change=change):
                bridge, api = self.make_bridge()
                fields = {"side": "SELL", "price": "4200", "volume": "0.01", "sl": "4210", "tp": ""}
                bridge.perform("basicPreview", fields)
                token = bridge.state["confirmation"]["token"]
                if change == "account":
                    api.current = _account(202)
                elif change == "permissions":
                    api.current.trade_allowed = False
                elif change == "duplicate":
                    api.active_orders = (SimpleNamespace(ticket=88, symbol="XAUUSDc",
                        type=mt5.ORDER_TYPE_SELL_LIMIT, price_open=4200,
                        volume_initial=0.01, sl=4210, tp=0),)
                else:
                    api.symbol_info_tick = lambda _name: SimpleNamespace(
                        bid=4201 if change == "quote" else 4194.9,
                        ask=4202 if change == "quote" else 4195,
                        time_msc=int((time.time() - (60 if change == "expired" else 0)) * 1000))
                bridge.perform("confirm", {"token": token})
                self.assertEqual(api.sent, [])
                self.assertEqual(bridge.state["confirmation"], {})

    def test_basic_field_edit_or_tab_switch_invalidates_confirmation(self):
        for action in ("basicInvalidate", "entryTabChanged"):
            bridge, api = self.make_bridge()
            bridge.perform("basicPreview", {"side": "SELL", "price": "4200",
                                           "volume": "0.01", "sl": "4210", "tp": ""})
            token = bridge.state["confirmation"]["token"]
            bridge.perform(action, {})
            bridge.perform("confirm", {"token": token})
            self.assertEqual(api.sent, [])

    def test_basic_rejects_invalid_inputs_and_server_check_failure(self):
        fields = {"side": "SELL", "price": "4200", "volume": "0.01", "sl": "4210", "tp": "4190"}
        for patch_fields in ({"side": "MARKET"}, {"price": "4190"},
                             {"volume": "0.015"}, {"price": "4200.001"},
                             {"sl": "4190"}, {"tp": "4210"},
                             {"volume": "NaN"}, {"price": "Infinity"}):
            with self.subTest(fields=patch_fields):
                bridge, api = self.make_bridge()
                bridge.perform("basicPreview", {**fields, **patch_fields})
                self.assertEqual(bridge.state["confirmation"], {})
                self.assertTrue(bridge.state["basicOrder"]["error"])
                self.assertEqual(api.sent, [])
        bridge, api = self.make_bridge()
        api.order_check = lambda _request: SimpleNamespace(retcode=10016, comment="invalid stops")
        bridge.perform("basicPreview", fields)
        self.assertEqual(bridge.state["confirmation"], {})
        self.assertEqual(api.sent, [])

    def test_control_preview_never_closes_without_confirmation(self):
        bridge, api = self.make_bridge()
        api.active_positions = (SimpleNamespace(
            ticket=123, symbol="XAUUSDc", type=mt5.POSITION_TYPE_BUY,
            volume=0.01, price_open=4190, sl=4180, profit=40,
        ),)
        bridge.perform("controlsPreview", {"kind": "close", "scope": "symbol",
                                           "deviation": "50"})
        self.assertEqual(bridge.state["confirmation"]["title"], "确认全部平仓")
        self.assertEqual(api.sent, [])
        bridge.perform("cancelConfirm", {})
        self.assertEqual(api.sent, [])

    def test_protection_preview_requires_confirmation_for_minimum_position(self):
        bridge, api = self.make_bridge()
        api.active_positions = (SimpleNamespace(
            ticket=123, symbol="XAUUSDc", type=mt5.POSITION_TYPE_BUY,
            volume=0.01, price_open=4000.0, sl=0.0, tp=0.0,
        ),)
        api.order_calc_profit = lambda kind, _symbol, volume, opened, closed: (
            (closed - opened) if kind == mt5.ORDER_TYPE_BUY else (opened - closed)
        ) * volume * 100

        bridge.perform("previewBreakEven", {"scope": "symbol", "amountUsd": "1"})
        confirmation = bridge.state["confirmation"]
        self.assertEqual(confirmation["title"], "确认一键推保本")
        self.assertEqual(confirmation["rows"][0][-2], "4100.00")
        self.assertEqual(confirmation["rows"][0][-1], "1.00 USD")
        self.assertEqual(api.sent, [])
        bridge.perform("cancelConfirm", {})
        self.assertEqual(api.sent, [])

        bridge.perform("previewBatchStops", {"scope": "symbol", "sl": "4050", "tp": "4250"})
        token = bridge.state["confirmation"]["token"]
        self.assertEqual(api.sent, [])

        def update_stops(request):
            api.sent.append(dict(request))
            current = api.active_positions[0]
            api.active_positions = (SimpleNamespace(**{**vars(current),
                              "sl": request["sl"], "tp": request["tp"]}),)
            return SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE,
                                   order=0, deal=0, comment="done")

        api.order_send = update_stops
        with tempfile.TemporaryDirectory() as temp, patch.object(
                module, "_records_dir", return_value=Path(temp)), patch.object(
                bridge, "_refresh_controls"):
            bridge.perform("confirm", {"token": token})
            self.assertEqual(len(api.sent), 1)
            self.assertEqual(api.sent[0]["action"], mt5.TRADE_ACTION_SLTP)
            self.assertEqual(api.sent[0]["position"], 123)
            self.assertNotIn("volume", api.sent[0])
            bridge.perform("confirm", {"token": token})
            self.assertEqual(len(api.sent), 1)

    def test_control_navigation_keeps_gui_thread_free(self):
        bridge, api = self.make_bridge()
        reading = Event()
        release = Event()

        def slow_positions(**_kwargs):
            reading.set()
            release.wait(3)
            return ()

        api.positions_get = slow_positions
        try:
            start = time.monotonic()
            bridge.perform("navigate", {"page": "controls"})
            self.assertLess(time.monotonic() - start, 0.25)
            self.assertTrue(bridge.state["controls"]["loading"])
            self.assertTrue(reading.wait(1))
            self.assertEqual(api.sent, [])
        finally:
            release.set()
        for _ in range(100):
            bridge._consume_results()
            if not bridge.state["controls"]["loading"]:
                break
            time.sleep(0.01)
        self.assertEqual(bridge.state["controls"]["summary"], "持仓 0 笔 · 挂单 0 笔")

    def test_control_read_error_replaces_loading_status(self):
        bridge, api = self.make_bridge()
        api.positions_get = lambda **_kwargs: None
        bridge.perform("navigate", {"page": "controls"})
        for _ in range(100):
            bridge._consume_results()
            if not bridge.state["controls"]["loading"]:
                break
            time.sleep(0.01)
        self.assertFalse(bridge.state["controls"]["loading"])
        self.assertIn("目标读取失败", bridge.state["controls"]["status"])


if __name__ == "__main__":
    unittest.main()
