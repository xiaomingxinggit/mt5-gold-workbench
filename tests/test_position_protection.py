"""Offline-only tests: the fake API never connects to an MT5 terminal."""

from __future__ import annotations

import json
import time
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import MetaTrader5 as mt5

from mt5_workbench.services.position_protection import (
    execute_protection_batch, load_targets, prepare_protection, target_signature,
)


def position(ticket=11, *, side=mt5.POSITION_TYPE_BUY, symbol="XAUUSDc",
             opened=4200.0, sl=0.0, tp=0.0):
    return SimpleNamespace(ticket=ticket, symbol=symbol, type=side, volume=0.01,
                           price_open=opened, sl=sl, tp=tp)


class FakeMT5:
    def __init__(self):
        self.account = SimpleNamespace(login=123, server="fake", currency="USC",
                                       trade_allowed=True, trade_expert=True)
        self.terminal = SimpleNamespace(connected=True, trade_allowed=True)
        self.positions = [position()]
        self.symbols = {"XAUUSDc": SimpleNamespace(
            name="XAUUSDc", point=0.01, digits=2, trade_tick_size=0.01,
            trade_stops_level=0, trade_freeze_level=0,
            trade_mode=mt5.SYMBOL_TRADE_MODE_FULL, order_mode=127,
        )}
        self.ticks = {"XAUUSDc": SimpleNamespace(
            bid=4205.0, ask=4205.2, time_msc=int(time.time() * 1000),
        )}
        self.checked = []
        self.sent = []
        self.profit_calls = []
        self.check_retcode = 0
        self.send_retcode = mt5.TRADE_RETCODE_DONE
        self.check_hook = None
        self.send_hook = None

    def terminal_info(self):
        return self.terminal

    def account_info(self):
        return self.account

    def positions_get(self, **kwargs):
        return tuple(row for row in self.positions
                     if "symbol" not in kwargs or row.symbol == kwargs["symbol"])

    def symbol_info(self, name):
        return self.symbols.get(name)

    def symbol_info_tick(self, name):
        return self.ticks.get(name)

    def order_calc_profit(self, order_type, symbol, volume, opened, closed):
        self.profit_calls.append((order_type, symbol, volume, opened, closed))
        direction = 1 if order_type == mt5.ORDER_TYPE_BUY else -1
        # 100 oz per lot, USC 100 per USD: 0.01 lot earns USC 100 for $1.
        return round(direction * (closed - opened) * volume * 100 * 100, 6)

    def order_check(self, request):
        self.checked.append(dict(request))
        if self.check_hook:
            self.check_hook(request)
        return SimpleNamespace(retcode=self.check_retcode, comment="fake check")

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.send_hook:
            self.send_hook(request)
        if self.send_retcode == mt5.TRADE_RETCODE_DONE:
            for row in self.positions:
                if row.ticket == request["position"]:
                    row.sl, row.tp = request["sl"], request["tp"]
        return SimpleNamespace(retcode=self.send_retcode, order=0,
                               deal=0, comment="fake sent")

    def last_error(self):
        return "fake MT5 error"


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeMT5()

    def _rows(self, scope="symbol"):
        return load_targets(scope, "XAUUSDc", api=self.api)

    def test_buy_and_sell_lock_one_usd_gross_using_order_calc_profit(self):
        buy = prepare_protection("breakeven", self._rows(), api=self.api)[0]
        self.assertEqual(buy.new_sl, Decimal("4201.00"))
        self.assertEqual(buy.expected_profit_usc, Decimal("100.0"))
        self.assertEqual(buy.request, {"action": mt5.TRADE_ACTION_SLTP,
                                       "position": 11, "symbol": "XAUUSDc",
                                       "sl": 4201.0, "tp": 0.0})
        self.assertTrue(all(call[0] == mt5.ORDER_TYPE_BUY for call in self.api.profit_calls))
        self.assertLessEqual(len(self.api.profit_calls), 5)
        self.api.positions = [position(12, side=mt5.POSITION_TYPE_SELL)]
        self.api.ticks["XAUUSDc"].bid = 4194.8
        self.api.ticks["XAUUSDc"].ask = 4195.0
        self.api.profit_calls.clear()
        sell = prepare_protection("breakeven", self._rows(), api=self.api)[0]
        self.assertEqual(sell.new_sl, Decimal("4199.00"))
        self.assertEqual(sell.expected_profit_usc, Decimal("100.0"))
        self.assertTrue(all(call[0] == mt5.ORDER_TYPE_SELL for call in self.api.profit_calls))
        self.assertLessEqual(len(self.api.profit_calls), 5)

    def test_tick_size_alignment_and_broker_distance(self):
        symbol = self.api.symbols["XAUUSDc"]
        symbol.trade_tick_size = 0.25
        plan = prepare_protection("breakeven", self._rows(), api=self.api)[0]
        self.assertEqual(plan.new_sl, Decimal("4201.00"))
        symbol.trade_stops_level = 400  # $4 plus one tick; no space for $1 lock.
        with self.assertRaisesRegex(ValueError, "浮盈不足"):
            prepare_protection("breakeven", self._rows(), api=self.api)
        symbol.trade_stops_level = 0
        symbol.trade_freeze_level = 400
        with self.assertRaisesRegex(ValueError, "浮盈不足"):
            prepare_protection("breakeven", self._rows(), api=self.api)

    def test_no_worsening_an_existing_better_stop(self):
        self.api.positions[0].sl = 4202.0
        plans = prepare_protection("breakeven", self._rows(), api=self.api)
        self.assertEqual(plans, ())
        self.assertEqual(self.api.sent, [])

    def test_insufficient_profit_blocks_entire_preview(self):
        self.api.positions.append(position(12, opened=4205.0))
        with self.assertRaisesRegex(ValueError, "持仓 12.*浮盈不足"):
            prepare_protection("breakeven", self._rows(), api=self.api)
        self.assertEqual(self.api.sent, [])

    def test_batch_absolute_price_preserves_blank_field_and_rejects_mixed_symbols(self):
        self.api.positions[0].sl = 4190.0
        plan = prepare_protection("batch", self._rows(), tp=Decimal("4210.00"), api=self.api)[0]
        self.assertEqual((plan.new_sl, plan.new_tp), (Decimal("4190.0"), Decimal("4210.00")))
        self.assertEqual((plan.request["sl"], plan.request["tp"]), (4190.0, 4210.0))
        with self.assertRaisesRegex(ValueError, "tick size"):
            prepare_protection("batch", self._rows(), tp=Decimal("4210.001"), api=self.api)
        self.api.positions.append(position(13, symbol="EURUSDc"))
        with self.assertRaisesRegex(ValueError, "多个品种"):
            prepare_protection("batch", self._rows("account"), tp=Decimal("4210"), api=self.api)

    def test_batch_checks_quote_side_and_distance(self):
        with self.assertRaisesRegex(ValueError, "tick size"):
            prepare_protection("batch", self._rows(), sl=Decimal("1e1000"), api=self.api)
        with self.assertRaisesRegex(ValueError, "止损价距 Bid"):
            prepare_protection("batch", self._rows(), sl=Decimal("4205"), api=self.api)
        with self.assertRaisesRegex(ValueError, "止盈价距 Bid"):
            prepare_protection("batch", self._rows(), tp=Decimal("4205"), api=self.api)
        self.api.ticks["XAUUSDc"].time_msc -= 20_000
        with self.assertRaisesRegex(RuntimeError, "报价已过期"):
            prepare_protection("batch", self._rows(), sl=Decimal("4190"), api=self.api)

    def test_snapshot_includes_both_protective_levels(self):
        before = target_signature(self._rows())
        self.api.positions[0].tp = 4210.0
        self.assertNotEqual(before, target_signature(self._rows()))
        with_tp = target_signature(self._rows())
        self.api.positions[0].identifier = 999
        self.assertNotEqual(with_tp, target_signature(self._rows()))

    def test_confirmed_send_once_and_audit(self):
        rows = self._rows()
        plans = prepare_protection("breakeven", rows, api=self.api)
        with TemporaryDirectory() as directory:
            result = execute_protection_batch(
                "breakeven", "symbol", "XAUUSDc", self.api.account,
                rows, plans, Path(directory), api=self.api,
            )
            self.assertEqual(len(result), 1)
            self.assertEqual(len(self.api.checked), 1)
            self.assertEqual(len(self.api.sent), 1)
            self.assertEqual(self.api.sent[0]["action"], mt5.TRADE_ACTION_SLTP)
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "done")
            self.assertEqual(record["results"][0]["ticket"], 11)

    def test_changed_target_or_quote_blocks_before_send(self):
        rows = self._rows()
        plans = prepare_protection("breakeven", rows, api=self.api)
        self.api.positions[0].sl = 4190.0
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "已变化"):
                execute_protection_batch("breakeven", "symbol", "XAUUSDc",
                                         self.api.account, rows, plans, Path(directory), api=self.api)
            self.assertEqual(self.api.sent, [])
        self.api.positions[0].sl = 0
        self.api.ticks["XAUUSDc"].bid = 4200.5
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex((ValueError, RuntimeError), "浮盈不足|报价已变化"):
                execute_protection_batch("breakeven", "symbol", "XAUUSDc",
                                         self.api.account, rows, plans, Path(directory), api=self.api)
            self.assertEqual(self.api.sent, [])

    def test_non_usc_and_check_failure_never_send(self):
        rows = self._rows()
        plans = prepare_protection("breakeven", rows, api=self.api)
        self.api.account = SimpleNamespace(**{**vars(self.api.account), "currency": "USD"})
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "USC"):
                execute_protection_batch("breakeven", "symbol", "XAUUSDc",
                                         self.api.account, rows, plans, Path(directory), api=self.api)
            self.assertEqual(self.api.sent, [])
        self.api.account.currency = "USC"
        self.api.check_retcode = 10016
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "order_check"):
                execute_protection_batch("breakeven", "symbol", "XAUUSDc",
                                         self.api.account, rows, plans, Path(directory), api=self.api)
            self.assertEqual(self.api.sent, [])
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "stopped_check")

    def test_request_mutation_does_not_change_send_and_failure_stops_batch(self):
        self.api.positions.append(position(12))
        rows = self._rows()
        plans = prepare_protection("breakeven", rows, api=self.api)
        self.api.check_hook = lambda request: request.update(action=mt5.TRADE_ACTION_DEAL)
        self.api.send_retcode = 10016
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "发送失败"):
                execute_protection_batch("breakeven", "symbol", "XAUUSDc",
                                         self.api.account, rows, plans, Path(directory), api=self.api)
            self.assertEqual(len(self.api.sent), 1)
            self.assertEqual(self.api.sent[0]["action"], mt5.TRADE_ACTION_SLTP)
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "stopped_uncertain")

    def test_account_switch_between_positions_stops_remaining(self):
        self.api.positions.append(position(12))
        rows = self._rows()
        plans = prepare_protection("breakeven", rows, api=self.api)
        first_account = self.api.account
        self.api.send_hook = lambda _request: setattr(self.api, "account", replace_account(first_account, "USD"))
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "USC"):
                execute_protection_batch("breakeven", "symbol", "XAUUSDc",
                                         first_account, rows, plans, Path(directory), api=self.api)
            self.assertEqual(len(self.api.sent), 1)
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "stopped_check")


def replace_account(account, currency):
    return SimpleNamespace(**{**vars(account), "currency": currency})


if __name__ == "__main__":
    unittest.main()
