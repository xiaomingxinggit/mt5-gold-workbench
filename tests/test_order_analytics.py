from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from mt5_workbench.services.order_analytics import load_order_analytics


CHINA = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 3, 3, 0, tzinfo=timezone.utc)


def order(ticket, symbol, kind, state, at, *, done=None, initial=0.01,
          remaining=0, price=4200, sl=4190, tp=4210):
    return SimpleNamespace(
        ticket=ticket, symbol=symbol, type=kind, state=state,
        time_setup=int(at.timestamp()), time_setup_msc=int(at.timestamp() * 1000),
        time_done=int(done.timestamp()) if done else 0,
        time_done_msc=int(done.timestamp() * 1000) if done else 0,
        volume_initial=initial, volume_current=remaining,
        price_open=price, sl=sl, tp=tp, comment="test",
    )


def deal(ticket, symbol, kind, at, *, volume=0.01, profit=0,
         commission=0, swap=0, fee=0, order_id=0, position_id=0,
         entry=None, price=4200):
    return SimpleNamespace(
        ticket=ticket, symbol=symbol, type=kind,
        time=int(at.timestamp()), time_msc=int(at.timestamp() * 1000),
        volume=volume, profit=profit, commission=commission, swap=swap,
        fee=fee, order=order_id, position_id=position_id,
        entry=entry, price=price,
    )


class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_STATE_PLACED = 1
    ORDER_STATE_CANCELED = 2
    ORDER_STATE_PARTIAL = 3
    ORDER_STATE_FILLED = 4
    ORDER_STATE_REJECTED = 5
    ORDER_STATE_EXPIRED = 6
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1
    DEAL_TYPE_BALANCE = 2
    DEAL_TYPE_COMMISSION = 7
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3

    def __init__(self):
        self.pending = []
        self.positions = []
        self.history = []
        self.deals = []
        self.calls = []

    def orders_get(self, **kwargs):
        self.calls.append(("orders_get", kwargs))
        if self.pending is None:
            return None
        return [row for row in self.pending
                if not kwargs or row.symbol == kwargs.get("symbol")]

    def positions_get(self, **kwargs):
        self.calls.append(("positions_get", kwargs))
        if self.positions is None:
            return None
        return [row for row in self.positions
                if not kwargs or row.symbol == kwargs.get("symbol")]

    def history_orders_get(self, start, end, **kwargs):
        self.calls.append(("history_orders_get", start, end, kwargs))
        return self.history

    def history_deals_get(self, start, end):
        self.calls.append(("history_deals_get", start, end))
        return self.deals

    def last_error(self):
        return (-1, "fixture failure")


class OrderAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeMT5()
        self.account = SimpleNamespace(currency="USC")

    def load(self, **kwargs):
        return load_order_analytics(self.account, api=self.api, now=NOW,
                                    display_tz=CHINA, **kwargs)

    def test_symbol_scope_separates_orders_from_executions_and_currency(self):
        yesterday = NOW - timedelta(hours=1)
        self.api.pending = [
            order(101, "XAUUSDc", 3, 1, yesterday, initial=0.05,
                  remaining=0.03, tp=4200),
            order(102, "EURUSDc", 2, 1, yesterday, remaining=0.02),
        ]
        self.api.positions = [
            SimpleNamespace(symbol="XAUUSDc", volume=0.02),
            SimpleNamespace(symbol="EURUSDc", volume=0.50),
        ]
        self.api.history = [
            order(201, "XAUUSDc", 3, 4, yesterday, done=yesterday,
                  initial=0.05),
            order(202, "XAUUSDc", 3, 2, yesterday, done=yesterday,
                  initial=0.02),
            order(203, "EURUSDc", 2, 4, yesterday, done=yesterday),
        ]
        self.api.deals = [
            deal(301, "XAUUSDc", 1, yesterday, volume=0.03, profit=5,
                 commission=-0.2, swap=-0.1, fee=-0.05, order_id=201),
            deal(302, "EURUSDc", 0, yesterday, volume=0.50, profit=100),
            deal(303, "XAUUSDc", 2, yesterday, profit=50000),
        ]
        result = self.load(symbol="XAUUSDc", days=7)
        self.assertEqual(result.currency, "USC")
        self.assertEqual(result.scope_symbol, "XAUUSDc")
        self.assertEqual(result.lookback_days, 7)
        self.assertEqual(result.pending_count, 1)
        self.assertEqual(result.pending_lots, 0.03)
        self.assertEqual(result.position_count, 1)
        self.assertEqual(result.position_lots, 0.02)
        self.assertEqual(result.pending_orders[0].type_label, "SELL LIMIT")
        self.assertEqual(result.pending_orders[0].status_label, "已挂单")
        self.assertEqual(result.pending_orders[0].tp, 4200)
        self.assertEqual(result.pending_orders[0].done_at, None)
        self.assertEqual({row.ticket for row in result.recent_orders}, {201, 202})
        self.assertEqual([(row.label, row.count) for row in result.status_counts],
                         [("已成交", 1), ("已取消", 1)])
        self.assertEqual(result.deal_count, 1)
        self.assertEqual(result.buy_lots, 0)
        self.assertEqual(result.sell_lots, 0.03)
        self.assertEqual(result.traded_lots, 0.03)
        self.assertEqual(result.net_trading_cashflow, Decimal("4.65"))
        self.assertEqual(len(result.daily_execution), 7)
        self.assertEqual(result.daily_execution[-1].day.isoformat(), "2026-10-03")
        self.assertEqual(result.daily_execution[-1].sell_lots, 0.03)
        self.assertEqual(result.errors, ())
        self.assertEqual(self.api.calls[0], ("orders_get", {"symbol": "XAUUSDc"}))
        self.assertEqual(self.api.calls[1], ("positions_get", {"symbol": "XAUUSDc"}))
        self.assertEqual(self.api.calls[2][1],
                         datetime(2026, 9, 26, 16, tzinfo=timezone.utc))
        self.assertEqual(self.api.calls[2][3], {"group": "XAUUSDc"})
        self.assertFalse(any(name in ("order_send", "order_check")
                             for name, *_ in self.api.calls))

    def test_all_account_includes_both_symbols_and_standalone_commission(self):
        at = NOW - timedelta(hours=1)
        self.api.pending = [order(1, "XAUUSDc", 3, 1, at, remaining=0.01),
                            order(2, "EURUSDc", 2, 1, at, remaining=0.03)]
        self.api.deals = [
            deal(10, "XAUUSDc", 0, at, volume=0.01, profit=5),
            deal(11, "EURUSDc", 1, at, volume=0.02, profit=-2),
            deal(12, "", 7, at, volume=0, profit=-0.5),
            deal(13, "", 2, at, volume=0, profit=1000),
        ]
        result = self.load()
        self.assertEqual(result.pending_count, 2)
        self.assertEqual(result.pending_lots, 0.04)
        self.assertEqual(result.deal_count, 2)
        self.assertEqual(result.buy_lots, 0.01)
        self.assertEqual(result.sell_lots, 0.02)
        self.assertEqual(result.net_trading_cashflow, Decimal("2.5"))
        self.assertEqual(self.api.calls[0], ("orders_get", {}))
        self.assertEqual(self.api.calls[2][3], {})

    def test_active_market_order_is_not_counted_as_pending(self):
        at = NOW - timedelta(hours=1)
        self.api.pending = [
            order(1, "XAUUSDc", self.api.ORDER_TYPE_BUY, 1, at,
                  remaining=0.01),
            order(2, "XAUUSDc", self.api.ORDER_TYPE_SELL_LIMIT, 1, at,
                  remaining=0.02),
        ]
        result = self.load(symbol="XAUUSDc")
        self.assertEqual(result.pending_count, 1)
        self.assertEqual(result.pending_lots, 0.02)
        self.assertEqual([row.ticket for row in result.pending_orders], [2])

    def test_symbol_cashflow_includes_linked_standalone_commission(self):
        at = NOW - timedelta(hours=1)
        self.api.deals = [
            deal(1, "XAUUSDc", 0, at, profit=10, order_id=21,
                 position_id=31),
            deal(2, "", 7, at, profit=-1, order_id=21),
            deal(3, "", 7, at, profit=-2, position_id=31),
            deal(4, "", 7, at, profit=-20, order_id=99),
        ]
        result = self.load(symbol="XAUUSDc")
        self.assertEqual(result.net_trading_cashflow, Decimal("7"))

    def test_account_curve_uses_all_symbols_local_days_and_cashflow_drawdown(self):
        def local(year, month, day, hour):
            return datetime(year, month, day, hour, tzinfo=CHINA).astimezone(timezone.utc)

        self.api.deals = [
            deal(1, "XAUUSDc", 0, local(2026, 9, 26, 23), profit=500),
            deal(2, "XAUUSDc", 0, local(2026, 9, 27, 1),
                 profit=11, swap=-0.5, commission=-0.25, fee=-0.25),
            deal(3, "EURUSDc", 1, local(2026, 9, 28, 20),
                 profit=-3, swap=-0.5, commission=-0.25, fee=-0.25),
            deal(4, "", 7, local(2026, 9, 30, 0), profit=-2, volume=0),
            deal(5, "XAUUSDc", 0, local(2026, 10, 2, 10),
                 profit=4, commission=-1),
            deal(6, "EURUSDc", 1, local(2026, 10, 3, 9),
                 profit=-11, swap=-0.5, commission=-0.5),
            deal(7, "", self.api.DEAL_TYPE_BALANCE,
                 local(2026, 10, 3, 9), profit=1000, volume=0),
        ]
        result = self.load(symbol="XAUUSDc", days=7)
        self.assertEqual(result.net_trading_cashflow, Decimal("13"))
        self.assertEqual(result.account_curve[0].day.isoformat(), "2026-09-27")
        self.assertEqual(result.account_curve[-1].day.isoformat(), "2026-10-03")
        self.assertEqual(len(result.account_curve), 7)
        self.assertEqual([row.daily_cashflow for row in result.account_curve],
                         [Decimal(value) for value in ("10", "-4", "0", "-2", "0", "3", "-12")])
        self.assertEqual([row.cumulative for row in result.account_curve],
                         [Decimal(value) for value in ("10", "6", "6", "4", "4", "7", "-5")])
        self.assertEqual([row.drawdown for row in result.account_curve],
                         [Decimal(value) for value in ("0", "4", "4", "6", "6", "3", "15")])
        self.assertEqual(result.account_max_drawdown, Decimal("15"))
        self.assertEqual(result.account_current_drawdown, Decimal("15"))

    def test_account_curve_invalid_amount_in_other_symbol_is_unavailable(self):
        at = NOW - timedelta(hours=1)
        other = deal(2, "EURUSDc", 1, at, profit=3)
        del other.fee
        self.api.deals = [deal(1, "XAUUSDc", 0, at, profit=5), other]
        result = self.load(symbol="XAUUSDc", days=7)
        self.assertEqual(result.net_trading_cashflow, Decimal("5"))
        self.assertEqual(result.deal_count, 1)
        self.assertEqual(result.account_curve, ())
        self.assertIsNone(result.account_max_drawdown)
        self.assertIsNone(result.account_current_drawdown)
        self.assertIn("账户曲线及回撤不可用", " ".join(result.errors))

    def test_account_curve_missing_commission_amount_is_unavailable(self):
        at = NOW - timedelta(hours=1)
        commission = deal(2, "", self.api.DEAL_TYPE_COMMISSION,
                          at, profit=-1, volume=0)
        del commission.commission
        self.api.deals = [deal(1, "XAUUSDc", 0, at, profit=5), commission]
        result = self.load(symbol="XAUUSDc", days=7)
        self.assertEqual(result.account_curve, ())
        self.assertIsNone(result.account_max_drawdown)
        self.assertIsNone(result.account_current_drawdown)

    def test_recent_deals_show_entry_type_components_and_newest_first(self):
        base = NOW - timedelta(hours=4)
        self.api.deals = [
            deal(1, "XAUUSDc", 0, base, volume=0.02, profit=0,
                 commission=-0.1, fee=-0.02, order_id=100,
                 entry=self.api.DEAL_ENTRY_IN, price=4201.25),
            deal(2, "XAUUSDc", 1, base + timedelta(hours=1), volume=0.01,
                 profit=3.5, swap=-0.25, order_id=101,
                 entry=self.api.DEAL_ENTRY_OUT, price=4205.75),
            deal(3, "XAUUSDc", 0, base + timedelta(hours=2), volume=0.03,
                 profit=-1, entry=self.api.DEAL_ENTRY_INOUT),
            deal(4, "XAUUSDc", 1, base + timedelta(hours=3),
                 entry=self.api.DEAL_ENTRY_OUT_BY),
            deal(5, "XAUUSDc", 2, base + timedelta(hours=3), profit=9999),
            deal(6, "EURUSDc", 1, base + timedelta(hours=3), profit=9999),
        ]
        result = self.load(symbol="XAUUSDc", max_recent_deals=3)
        self.assertEqual([row.ticket for row in result.recent_deals], [4, 3, 2])
        self.assertEqual([row.entry_label for row in result.recent_deals],
                         ["对冲平仓", "反手", "平仓"])
        self.assertEqual(result.recent_deals[-1].side_label, "SELL")
        self.assertEqual(result.recent_deals[-1].order_ticket, 101)
        self.assertEqual(result.recent_deals[-1].volume, 0.01)
        self.assertEqual(result.recent_deals[-1].price, 4205.75)
        self.assertEqual(result.recent_deals[-1].profit, Decimal("3.5"))
        self.assertEqual(result.recent_deals[-1].swap, Decimal("-0.25"))
        self.assertEqual(result.recent_deals[-1].commission, Decimal("0"))
        self.assertEqual(result.recent_deals[-1].fee, Decimal("0"))
        self.assertEqual(result.recent_deals[-1].cashflow, Decimal("3.25"))
        self.assertEqual(result.recent_deals[-1].executed_at.tzinfo, timezone.utc)
        self.assertEqual(result.deal_count, 4)

    def test_missing_money_component_is_unknown_not_zero(self):
        at = NOW - timedelta(hours=1)
        row = deal(11, "XAUUSDc", 0, at, profit=10, entry=42)
        del row.fee
        self.api.deals = [row]
        result = self.load(symbol="XAUUSDc")
        self.assertEqual(result.recent_deals[0].entry_label, "未知")
        self.assertIsNone(result.recent_deals[0].fee)
        self.assertIsNone(result.recent_deals[0].cashflow)
        self.assertIsNone(result.net_trading_cashflow)
        self.assertIn("资金字段", " ".join(result.errors))

    def test_none_is_unavailable_not_zero_and_other_sources_survive(self):
        at = NOW - timedelta(hours=1)
        self.api.pending = None
        self.api.history = None
        self.api.deals = None
        self.api.positions = [SimpleNamespace(symbol="XAUUSDc", volume=0.1)]
        result = self.load(symbol="XAUUSDc")
        self.assertFalse(result.pending_available)
        self.assertFalse(result.history_orders_available)
        self.assertFalse(result.history_deals_available)
        self.assertTrue(result.positions_available)
        self.assertIsNone(result.pending_count)
        self.assertIsNone(result.deal_count)
        self.assertIsNone(result.net_trading_cashflow)
        self.assertEqual(result.daily_execution, ())
        self.assertEqual(result.account_curve, ())
        self.assertIsNone(result.account_max_drawdown)
        self.assertIsNone(result.account_current_drawdown)
        self.assertEqual(result.recent_deals, ())
        self.assertEqual(result.status_counts, ())
        self.assertEqual(result.position_count, 1)
        self.assertEqual(len(result.errors), 3)

    def test_empty_success_is_zero_and_daily_bins_are_local_dates(self):
        result = self.load(days=7)
        self.assertTrue(result.history_orders_available)
        self.assertTrue(result.history_deals_available)
        self.assertEqual(result.pending_count, 0)
        self.assertEqual(result.deal_count, 0)
        self.assertEqual(result.net_trading_cashflow, Decimal("0"))
        self.assertEqual(result.daily_execution[0].day.isoformat(), "2026-09-27")
        self.assertTrue(all(row.deal_count == 0 for row in result.daily_execution))
        self.assertEqual(len(result.account_curve), 7)
        self.assertTrue(all(row.daily_cashflow == row.cumulative == row.drawdown == 0
                            for row in result.account_curve))
        self.assertEqual(result.account_max_drawdown, Decimal("0"))
        self.assertEqual(result.account_current_drawdown, Decimal("0"))

    def test_history_uses_done_time_sorts_and_deduplicates_ticket(self):
        recent = NOW - timedelta(hours=1)
        old_setup = NOW - timedelta(days=50)
        self.api.history = [
            order(1, "XAUUSDc", 2, 4, old_setup, done=recent),
            order(2, "XAUUSDc", 2, 2, recent, done=recent - timedelta(minutes=1)),
            order(1, "XAUUSDc", 2, 4, old_setup, done=recent),
            order(3, "XAUUSDc", 2, 4, old_setup, done=old_setup),
        ]
        result = self.load(max_recent_orders=1)
        self.assertEqual([row.ticket for row in result.recent_orders], [1])
        self.assertEqual([(row.label, row.count) for row in result.status_counts],
                         [("已成交", 1), ("已取消", 1)])

    def test_invalid_volume_disables_volume_metrics_not_cashflow(self):
        at = NOW - timedelta(hours=1)
        self.api.pending = [order(1, "XAUUSDc", 2, 1, at, remaining=float("nan"))]
        self.api.deals = [deal(2, "XAUUSDc", 0, at, volume=float("nan"), profit=5)]
        result = self.load(symbol="XAUUSDc")
        self.assertEqual(result.pending_count, 1)
        self.assertIsNone(result.pending_lots)
        self.assertIsNone(result.deal_count)
        self.assertIsNone(result.buy_lots)
        self.assertEqual(result.daily_execution, ())
        self.assertEqual(result.net_trading_cashflow, Decimal("5"))
        self.assertEqual(len(result.errors), 2)

    def test_naive_now_and_bad_parameters_rejected(self):
        with self.assertRaises(ValueError):
            load_order_analytics(self.account, api=self.api,
                                 now=datetime(2026, 10, 3))
        with self.assertRaises(ValueError):
            self.load(days=0)
        with self.assertRaises(ValueError):
            self.load(symbol="  ")
        with self.assertRaises(ValueError):
            self.load(max_recent_deals=0)


if __name__ == "__main__":
    unittest.main()
