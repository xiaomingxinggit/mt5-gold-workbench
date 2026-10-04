import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import MetaTrader5 as mt5

from mt5_workbench.services.account_controls import close_request, execute_batch, load_targets, remove_request


class FakeMT5:
    def __init__(self):
        self.account = SimpleNamespace(login=123, server="test", trade_allowed=True,
                                       trade_expert=True, currency="USC")
        self.terminal = SimpleNamespace(connected=True, trade_allowed=True)
        self.positions = [SimpleNamespace(ticket=11, symbol="XAUUSDc",
                                          type=mt5.POSITION_TYPE_BUY,
                                          volume=0.01, price_open=4200.0)]
        self.orders = [SimpleNamespace(ticket=22, symbol="XAUUSDc",
                                       type=mt5.ORDER_TYPE_BUY_LIMIT,
                                       volume_initial=0.01, price_open=4190.0,
                                       sl=4180.0, tp=0.0)]
        self.symbol = SimpleNamespace(name="XAUUSDc", trade_mode=mt5.SYMBOL_TRADE_MODE_FULL,
                                      trade_exemode=mt5.SYMBOL_TRADE_EXECUTION_MARKET,
                                      filling_mode=3)
        self.tick = SimpleNamespace(bid=4200.0, ask=4200.2,
                                    time_msc=int(time.time() * 1000))
        self.sent = []
        self.check_retcode = 0
        self.send_error = False

    def terminal_info(self):
        return self.terminal

    def account_info(self):
        return self.account

    def positions_get(self, **kwargs):
        return tuple(row for row in self.positions
                     if "symbol" not in kwargs or row.symbol == kwargs["symbol"])

    def orders_get(self, **kwargs):
        return tuple(row for row in self.orders
                     if "symbol" not in kwargs or row.symbol == kwargs["symbol"])

    def symbol_info(self, _symbol):
        return self.symbol

    def symbol_info_tick(self, _symbol):
        return self.tick

    def order_check(self, _request):
        return SimpleNamespace(retcode=self.check_retcode, comment="checked")

    def order_send(self, request):
        self.sent.append(request)
        if self.send_error:
            raise OSError("simulated connection loss")
        if request["action"] == mt5.TRADE_ACTION_DEAL:
            self.positions.clear()
        else:
            self.orders.clear()
        return SimpleNamespace(retcode=mt5.TRADE_RETCODE_DONE, order=33,
                               deal=44, comment="done")

    def last_error(self):
        return "fake error"


class AccountControlTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeMT5()

    def test_close_request_uses_opposite_side_and_minimum_lot(self):
        request = close_request(self.api.positions[0], 50, api=self.api)
        self.assertEqual(request["volume"], 0.01)
        self.assertEqual(request["type"], mt5.ORDER_TYPE_SELL)
        self.assertEqual(request["position"], 11)
        self.assertEqual(request["type_filling"], mt5.ORDER_FILLING_FOK)
        self.assertNotIn("price", request)

    def test_remove_request_targets_exact_ticket(self):
        self.assertEqual(remove_request(self.api.orders[0])["order"], 22)

    def test_close_once_with_fake_send_and_audit_record(self):
        rows = load_targets("close", "symbol", "XAUUSDc", api=self.api)
        with TemporaryDirectory() as directory:
            result = execute_batch("close", "symbol", "XAUUSDc", self.api.account,
                                   rows, 50, Path(directory), api=self.api)
            self.assertEqual(result[0]["volume"], 0.01)
            self.assertEqual([request["volume"] for request in self.api.sent], [0.01])
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "done")

    def test_cancel_once_with_fake_send(self):
        rows = load_targets("remove", "account", "XAUUSDc", api=self.api)
        with TemporaryDirectory() as directory:
            execute_batch("remove", "account", "XAUUSDc", self.api.account,
                          rows, 0, Path(directory), api=self.api)
            self.assertEqual(len(self.api.sent), 1)
            self.assertEqual(self.api.sent[0]["action"], mt5.TRADE_ACTION_REMOVE)

    def test_non_cent_account_cannot_control_orders(self):
        rows = load_targets("remove", "account", "XAUUSDc", api=self.api)
        expected = self.api.account
        for changed_expected in (True, False):
            self.api.account = SimpleNamespace(**{**vars(expected), "currency": "USD"})
            with TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError, "USC 美分账户"):
                    execute_batch("remove", "account", "XAUUSDc",
                                  self.api.account if changed_expected else expected,
                                  rows, 0, Path(directory), api=self.api)
                self.assertEqual(self.api.sent, [])
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_currency_switch_stops_remaining_control_requests(self):
        second = SimpleNamespace(**{**vars(self.api.orders[0]), "ticket": 23})
        self.api.orders.append(second)
        rows = load_targets("remove", "account", "XAUUSDc", api=self.api)
        expected = self.api.account
        original_send = self.api.order_send

        def switch_after_first(request):
            result = original_send(request)
            self.api.account = SimpleNamespace(**{**vars(expected), "currency": "USD"})
            return result

        self.api.order_send = switch_after_first
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "USC 美分账户"):
                execute_batch("remove", "account", "XAUUSDc", expected,
                              rows, 0, Path(directory), api=self.api)
            self.assertEqual(len(self.api.sent), 1)
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "stopped_account_invalid")

    def test_changed_target_or_failed_check_never_sends(self):
        rows = load_targets("close", "symbol", "XAUUSDc", api=self.api)
        with TemporaryDirectory() as directory:
            self.api.positions[0] = SimpleNamespace(ticket=11, symbol="XAUUSDc",
                                                     type=mt5.POSITION_TYPE_BUY,
                                                     volume=0.02, price_open=4200.0)
            with self.assertRaisesRegex(RuntimeError, "已变化"):
                execute_batch("close", "symbol", "XAUUSDc", self.api.account,
                              rows, 50, Path(directory), api=self.api)
            self.assertEqual(self.api.sent, [])
        rows = load_targets("close", "symbol", "XAUUSDc", api=self.api)
        self.api.check_retcode = 10019
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "预检未通过"):
                execute_batch("close", "symbol", "XAUUSDc", self.api.account,
                              rows, 50, Path(directory), api=self.api)
            self.assertEqual(self.api.sent, [])

    def test_unknown_send_result_is_recorded_without_retry(self):
        rows = load_targets("close", "symbol", "XAUUSDc", api=self.api)
        self.api.send_error = True
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "状态不确定"):
                execute_batch("close", "symbol", "XAUUSDc", self.api.account,
                              rows, 50, Path(directory), api=self.api)
            self.assertEqual([request["volume"] for request in self.api.sent], [0.01])
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "stopped_uncertain")


if __name__ == "__main__":
    unittest.main()
