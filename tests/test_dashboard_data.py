from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from mt5_workbench.services.dashboard_data import fetch_candles, fetch_daily_realized, load_dashboard


NOW = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
CHINA = timezone(timedelta(hours=8))


def deal(at, kind, *, profit=0, swap=0, commission=0, fee=0):
    return SimpleNamespace(time=int(at.timestamp()), time_msc=int(at.timestamp() * 1000),
                           type=kind, profit=profit, swap=swap,
                           commission=commission, fee=fee)


class FakeMT5:
    TIMEFRAME_M5 = 5
    TIMEFRAME_D1 = 1440
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1
    DEAL_TYPE_BALANCE = 2
    DEAL_TYPE_COMMISSION = 7

    def __init__(self):
        start = NOW - timedelta(minutes=10)
        self.m5 = [
            {"time": int(start.timestamp()), "open": 4199, "high": 4201,
             "low": 4198, "close": 4200, "tick_volume": 100},
            {"time": int((NOW - timedelta(minutes=2)).timestamp()),
             "open": 4200, "high": 4202, "low": 4199, "close": 4201,
             "tick_volume": 12},
        ]
        self.d1 = [{"close": 4190}]
        self.deals = []
        self.positions = [SimpleNamespace(ticket=123)]
        self.orders = []
        self.calls = []

    def copy_rates_from_pos(self, symbol, timeframe, offset, count):
        self.calls.append(("copy_rates_from_pos", symbol, timeframe, offset, count))
        return self.m5 if timeframe == self.TIMEFRAME_M5 else self.d1

    def history_deals_get(self, start, end):
        self.calls.append(("history_deals_get", start, end))
        return self.deals

    def positions_get(self, *, symbol):
        self.calls.append(("positions_get", symbol))
        return self.positions

    def orders_get(self, *, symbol):
        self.calls.append(("orders_get", symbol))
        return self.orders

    def symbol_info(self, symbol):
        self.calls.append(("symbol_info", symbol))
        return SimpleNamespace(point=0.001)

    def last_error(self):
        return (1, "mock failure")


class DashboardDataTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeMT5()
        self.account = SimpleNamespace(currency="USC", balance=10000, equity=10030,
                                       profit=30, margin=250, margin_level=4012)
        self.tick = SimpleNamespace(bid=4201, ask=4201.12)

    def test_snapshot_includes_market_and_account_metrics(self):
        snapshot = load_dashboard("XAUUSDc", self.account, self.tick,
                                  api=self.api, now=NOW, display_tz=CHINA)
        self.assertEqual(len(snapshot.candles), 2)
        self.assertEqual(snapshot.candles[0].time.tzinfo, timezone.utc)
        self.assertTrue(snapshot.candles[0].is_complete)
        self.assertFalse(snapshot.candles[1].is_complete)
        self.assertEqual(snapshot.previous_close, 4190)
        self.assertEqual(snapshot.day_change, 11)
        self.assertAlmostEqual(snapshot.day_change_pct, 11 / 4190 * 100)
        self.assertEqual(snapshot.spread_points, 120)
        self.assertEqual(snapshot.positions_count, 1)
        self.assertEqual(snapshot.orders_count, 0)
        self.assertEqual(snapshot.floating_pnl, 30)
        self.assertEqual(snapshot.margin_level_pct, 4012)
        self.assertEqual(snapshot.currency, "USC")
        self.assertEqual(snapshot.realized_today, Decimal("0"))
        self.assertTrue(snapshot.history_available)
        self.assertEqual(len(snapshot.daily_pnl), 30)
        self.assertEqual(snapshot.errors, ())
        self.assertEqual(self.api.calls[0],
                         ("copy_rates_from_pos", "XAUUSDc", self.api.TIMEFRAME_M5, 0, 72))
        self.assertEqual(self.api.calls[1],
                         ("copy_rates_from_pos", "XAUUSDc", self.api.TIMEFRAME_D1, 1, 1))
        self.assertFalse(any(name in ("order_send", "order_check")
                             for name, *_ in self.api.calls))

    def test_realized_pnl_uses_local_day_and_excludes_deposits(self):
        self.api.deals = [
            deal(datetime(2026, 9, 30, 15, 30, tzinfo=timezone.utc), 0,
                 profit=100, swap=-1, commission=-2, fee=-0.5),
            deal(datetime(2026, 9, 30, 16, 30, tzinfo=timezone.utc), 1,
                 profit=-10, commission=-1),
            deal(datetime(2026, 9, 30, 17, 0, tzinfo=timezone.utc), 2,
                 profit=100000),
            deal(datetime(2026, 9, 30, 17, 30, tzinfo=timezone.utc), 7,
                 profit=-3),
        ]
        rows = fetch_daily_realized(api=self.api, now=NOW, display_tz=CHINA)
        self.assertEqual(rows[-2].amount, Decimal("96.5"))
        self.assertEqual(rows[-1].amount, Decimal("-14"))
        self.assertEqual(rows[-1].day.isoformat(), "2026-10-01")
        call = next(call for call in self.api.calls if call[0] == "history_deals_get")
        self.assertEqual(call[1], datetime(2026, 9, 1, 16, tzinfo=timezone.utc))
        self.assertEqual(call[2], NOW)

    def test_history_failure_is_not_a_zero_pnl(self):
        self.api.deals = None
        snapshot = load_dashboard("XAUUSDc", self.account, self.tick,
                                  api=self.api, now=NOW, display_tz=CHINA)
        self.assertFalse(snapshot.history_available)
        self.assertEqual(snapshot.daily_pnl, ())
        self.assertIsNone(snapshot.realized_today)
        self.assertIsNone(snapshot.realized_30d)
        self.assertIn("历史成交读取失败", " ".join(snapshot.errors))

    def test_empty_successful_history_means_zero_pnl(self):
        rows = fetch_daily_realized(api=self.api, now=NOW, display_tz=CHINA)
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(row.amount == 0 for row in rows))

    def test_partial_snapshot_keeps_available_sources(self):
        self.api.m5 = None
        self.api.d1 = []
        self.api.positions = None
        snapshot = load_dashboard("XAUUSDc", self.account, self.tick,
                                  api=self.api, now=NOW, display_tz=CHINA)
        self.assertEqual(snapshot.candles, ())
        self.assertIsNone(snapshot.day_change_pct)
        self.assertIsNone(snapshot.positions_count)
        self.assertEqual(snapshot.orders_count, 0)
        self.assertTrue(snapshot.history_available)
        self.assertEqual(len(snapshot.errors), 3)

    def test_candles_drop_invalid_bars_and_sort(self):
        self.api.m5 = [self.api.m5[1], {"time": 1, "open": 20, "high": 19,
                                        "low": 18, "close": 20, "tick_volume": 1},
                       self.api.m5[0]]
        bars = fetch_candles("XAUUSDc", api=self.api, now=NOW)
        self.assertEqual([bar.close for bar in bars], [4200, 4201])

    def test_naive_now_is_rejected(self):
        with self.assertRaises(ValueError):
            fetch_daily_realized(api=self.api, now=datetime(2026, 10, 1))


if __name__ == "__main__":
    unittest.main()
