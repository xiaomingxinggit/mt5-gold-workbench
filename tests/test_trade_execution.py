from decimal import Decimal
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import unittest

import MetaTrader5 as mt5

from mt5_workbench.domain.position_optimizer import Entry, Optimization
from mt5_workbench.services.trade_execution import (
    build_requests, check_requests, plan_key, send_checked,
)


def tiny_plan():
    entry = Entry(Decimal("4200"), Decimal("0.01"), Decimal("10"), Decimal("0.10"))
    return Optimization("SELL", "max_lots_single", Decimal("1"), Decimal("95"),
                        Decimal("0.95"), Decimal("0.01"), Decimal("0.10"),
                        Decimal("0.90"), (entry,))


def context():
    account = SimpleNamespace(login=123, server="test", currency="USC",
                              trade_allowed=True, trade_expert=True)
    symbol = SimpleNamespace(name="XAUUSDc", trade_mode=mt5.SYMBOL_TRADE_MODE_FULL,
                             order_mode=127, point=0.001, trade_tick_size=0.001,
                             trade_stops_level=0, volume_min=0.01,
                             volume_max=200, volume_step=0.01, volume_limit=0)
    tick = SimpleNamespace(bid=4190.0, ask=4190.2, time_msc=1_000_000)
    return account, symbol, tick


class FakeAPI:
    def __init__(self, account, *, check_retcode=0):
        self.account = account
        self.check_retcode = check_retcode
        self.sent = []
        self.checked = []
        self.order_reads = 0

    def account_info(self):
        return self.account

    def orders_get(self, **_kwargs):
        self.order_reads += 1
        return ()

    def order_check(self, request):
        self.checked.append(request)
        return SimpleNamespace(retcode=self.check_retcode, comment="checked")

    def order_send(self, request):
        self.sent.append(request)
        return SimpleNamespace(retcode=mt5.TRADE_RETCODE_PLACED,
                               order=456, deal=0, comment="placed")


class TradeExecutionTests(unittest.TestCase):
    def setUp(self):
        self.account, self.symbol, self.tick = context()
        self.request = build_requests(tiny_plan(), self.symbol, self.tick,
                                      self.account, now=1000)[0]

    def test_minimum_lot_limit_request(self):
        self.assertEqual(self.request["volume"], 0.01)
        self.assertEqual(self.request["type"], mt5.ORDER_TYPE_SELL_LIMIT)
        self.assertEqual(self.request["sl"], 4210.0)
        self.assertEqual(self.request["tp"], 0.0)
        self.assertEqual(self.request["type_filling"], mt5.ORDER_FILLING_RETURN)
        self.assertEqual(self.request["type_time"], mt5.ORDER_TIME_GTC)

    def test_stale_quote_and_invalid_limit_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "报价已过期"):
            build_requests(tiny_plan(), self.symbol, self.tick, self.account, now=1100)
        self.tick.ask = 4200.1
        with self.assertRaisesRegex(ValueError, "SELL LIMIT"):
            build_requests(tiny_plan(), self.symbol, self.tick, self.account, now=1000)

    def test_non_cent_account_cannot_build_requests(self):
        usd_account = SimpleNamespace(**{**vars(self.account), "currency": "USD"})
        with self.assertRaisesRegex(ValueError, "仅支持 USC"):
            build_requests(tiny_plan(), self.symbol, self.tick, usd_account, now=1000)

    def test_take_profit_is_sent_for_minimum_lot_buy_and_sell(self):
        sell = build_requests(replace(tiny_plan(), take_profit=Decimal("4190")),
                              self.symbol, self.tick, self.account, now=1000)[0]
        self.assertEqual((sell["volume"], sell["tp"]), (0.01, 4190.0))
        self.assertNotEqual(plan_key(self.account, (sell,)),
                            plan_key(self.account, (self.request,)))

        buy_entry = Entry(Decimal("4200"), Decimal("0.01"),
                          Decimal("10"), Decimal("0.10"))
        buy = replace(tiny_plan(), side="BUY", entries=(buy_entry,),
                      take_profit=Decimal("4215"))
        self.tick.bid, self.tick.ask = 4210.0, 4210.2
        buy_request = build_requests(buy, self.symbol, self.tick,
                                     self.account, now=1000)[0]
        self.assertEqual(buy_request["type"], mt5.ORDER_TYPE_BUY_LIMIT)
        self.assertEqual((buy_request["sl"], buy_request["tp"]), (4190.0, 4215.0))

    def test_take_profit_respects_broker_support_and_stop_distance(self):
        plan = replace(tiny_plan(), take_profit=Decimal("4199.5"))
        self.symbol.order_mode = 127 - 32
        with self.assertRaisesRegex(ValueError, "不支持挂单止盈"):
            build_requests(plan, self.symbol, self.tick, self.account, now=1000)
        self.symbol.order_mode = 127
        self.symbol.trade_stops_level = 1000
        with self.assertRaisesRegex(ValueError, "到止盈价的距离不足"):
            build_requests(plan, self.symbol, self.tick, self.account, now=1000)

    def test_check_failure_never_sends(self):
        api = FakeAPI(self.account, check_retcode=10019)
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "order_check"):
                send_checked(self.account, (self.request,), Path(directory), api=api)
            self.assertEqual(api.sent, [])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_only_pending_buy_or_sell_limit_requests_can_be_checked_or_sent(self):
        invalid = (
            {**self.request, "action": mt5.TRADE_ACTION_DEAL},
            {**self.request, "action": mt5.TRADE_ACTION_REMOVE},
            {**self.request, "type": mt5.ORDER_TYPE_BUY},
            {**self.request, "type": mt5.ORDER_TYPE_SELL},
            {**self.request, "type": mt5.ORDER_TYPE_BUY_STOP},
            {**self.request, "type": mt5.ORDER_TYPE_SELL_STOP},
            {**self.request, "type": mt5.ORDER_TYPE_BUY_STOP_LIMIT},
            {**self.request, "type": mt5.ORDER_TYPE_SELL_STOP_LIMIT},
        )
        for request in invalid:
            with self.subTest(action=request["action"], order_type=request["type"]):
                api = FakeAPI(self.account)
                with self.assertRaisesRegex(ValueError, "仅允许 BUY LIMIT 或 SELL LIMIT"):
                    check_requests((request,), api=api)
                with TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ValueError, "仅允许 BUY LIMIT 或 SELL LIMIT"):
                        send_checked(self.account, (request,), Path(directory), api=api)
                    self.assertEqual(list(Path(directory).iterdir()), [])
                self.assertEqual((api.order_reads, api.checked, api.sent), (0, [], []))

    def test_mixed_batch_is_rejected_before_checking_first_limit_order(self):
        api = FakeAPI(self.account)
        invalid = {**self.request, "type": mt5.ORDER_TYPE_SELL_STOP}
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "第 2 档仅允许"):
                send_checked(self.account, (self.request, invalid),
                             Path(directory), api=api)
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual((api.order_reads, api.checked, api.sent), (0, [], []))

    def test_missing_or_invalid_stop_blocks_entire_limit_batch_before_api_calls(self):
        for order_type in (mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT):
            for stop in (None, "", "bad", 0, -1, float("nan"), float("inf")):
                with self.subTest(order_type=order_type, stop=stop):
                    request = {**self.request, "type": order_type}
                    if stop is None:
                        request.pop("sl")
                    else:
                        request["sl"] = stop
                    requests = (self.request, request)
                    api = FakeAPI(self.account)
                    with self.assertRaisesRegex(ValueError, "第 2 档限价单必须设置有效止损价"):
                        check_requests(requests, api=api)
                    with TemporaryDirectory() as directory:
                        with self.assertRaisesRegex(ValueError, "第 2 档限价单必须设置有效止损价"):
                            send_checked(self.account, requests, Path(directory), api=api)
                        self.assertEqual(list(Path(directory).iterdir()), [])
                    self.assertEqual((api.order_reads, api.checked, api.sent), (0, [], []))

    def test_check_api_cannot_mutate_the_request_that_is_sent(self):
        class MutatingCheckAPI(FakeAPI):
            def order_check(self, request):
                checked = super().order_check(request)
                request["action"] = mt5.TRADE_ACTION_DEAL
                request["type"] = mt5.ORDER_TYPE_SELL
                return checked

        api = MutatingCheckAPI(self.account)
        with TemporaryDirectory() as directory:
            send_checked(self.account, (self.request,), Path(directory), api=api)
        self.assertEqual(api.sent[0]["action"], mt5.TRADE_ACTION_PENDING)
        self.assertEqual(api.sent[0]["type"], mt5.ORDER_TYPE_SELL_LIMIT)
        self.assertEqual(self.request["type"], mt5.ORDER_TYPE_SELL_LIMIT)

    def test_non_cent_account_cannot_send_even_with_existing_requests(self):
        usd_account = SimpleNamespace(**{**vars(self.account), "currency": "USD"})
        for expected, live in ((usd_account, usd_account), (self.account, usd_account)):
            api = FakeAPI(live)
            with TemporaryDirectory() as directory:
                with self.assertRaisesRegex(RuntimeError, "USC 美分账户"):
                    send_checked(expected, (self.request,), Path(directory), api=api)
                self.assertEqual(api.checked, [])
                self.assertEqual(api.sent, [])
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_currency_switch_stops_remaining_requests(self):
        class SwitchingAPI(FakeAPI):
            def order_send(self, request):
                result = super().order_send(request)
                self.account = SimpleNamespace(**{**vars(self.account), "currency": "USD"})
                return result

        api = SwitchingAPI(self.account)
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "不再是 USC"):
                send_checked(self.account, (self.request, self.request),
                             Path(directory), api=api)
            self.assertEqual(len(api.sent), 1)
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "stopped_account_changed")

    def test_send_once_and_block_duplicate_plan(self):
        api = FakeAPI(self.account)
        with TemporaryDirectory() as directory:
            rows = send_checked(self.account, (self.request,), Path(directory), api=api)
            self.assertEqual(rows[0]["order"], 456)
            self.assertEqual([row["volume"] for row in api.sent], [0.01])
            record = json.loads(next(Path(directory).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "placed")
            with self.assertRaisesRegex(RuntimeError, "发送记录"):
                send_checked(self.account, (self.request,), Path(directory), api=api)
            self.assertEqual(len(api.sent), 1)


if __name__ == "__main__":
    unittest.main()
