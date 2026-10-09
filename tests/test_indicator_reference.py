"""Offline, deterministic checks for ATR and daily volatility references."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

import numpy as np

from mt5_workbench.services.indicator_reference import load_indicator_reference


NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


def bar(day, *, high=110, low=90, close=100, opened=100):
    return {"time": int(day.timestamp()), "open": opened,
            "high": high, "low": low, "close": close}


class FakeApi:
    TIMEFRAME_D1, TIMEFRAME_W1, TIMEFRAME_MN1 = 1, 2, 3

    def __init__(self):
        self.point = 0.01
        self.calls = []
        self.data = {
            1: [bar(NOW - timedelta(days=i)) for i in range(399, 0, -1)
                if (NOW - timedelta(days=i)).weekday() < 5],
            2: [bar(NOW - timedelta(weeks=i)) for i in range(15, 0, -1)],
            3: [bar(datetime(year, month, 1, tzinfo=timezone.utc))
                for year in range(2010, 2027) for month in range(1, 13)
                if datetime(year, month, 1, tzinfo=timezone.utc) < datetime(2026, 10, 1, tzinfo=timezone.utc)],
        }

    def symbol_info(self, symbol):
        return SimpleNamespace(point=self.point)

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        self.calls.append((timeframe, start, count))
        data = self.data[timeframe]
        return data[-count:] if data is not None else None

    def last_error(self):
        return (-1, "history unavailable")


class IndicatorReferenceTests(unittest.TestCase):
    def load(self, api=None, period=14):
        return load_indicator_reference("XAUUSDc", api=api or FakeApi(), now=NOW, period=period)

    def test_all_periods_points_and_completed_reads(self):
        api = FakeApi()
        data = self.load(api)
        self.assertEqual([row["label"] for row in data["atr"]], ["年", "月", "周", "日"])
        for row in data["atr"]:
            self.assertEqual(row["price"], 20)
            self.assertEqual(row["points"], 2000)
            self.assertEqual(row["samples"], 14)
        self.assertTrue(all(start == 1 for _, start, _ in api.calls))
        self.assertTrue(data["atr"][0]["lastBar"].startswith("2025-01-01"))

    def test_gap_and_simple_average_match_mt5(self):
        api = FakeApi()
        api.data[1][-1] = bar(NOW - timedelta(days=1), high=145, low=135, opened=140, close=140)
        daily = self.load(api)["atr"][-1]
        # Latest TR is 45, despite an intraday high-low range of just 10.
        self.assertAlmostEqual(daily["price"], (13 * 20 + 45) / 14)

    def test_daily_averages_use_trading_days_and_calendar_windows(self):
        data = self.load()
        year, month, week, day = data["dailyAverages"]
        self.assertEqual(year["start"], "2025-10-09")
        self.assertEqual(month["start"], "2026-09-09")
        self.assertEqual(week["start"], "2026-10-02")
        self.assertEqual(week["samples"], 5)
        self.assertEqual(day["samples"], 1)
        for row in data["dailyAverages"]:
            self.assertEqual(row["points"], 2000)

    def test_short_history_is_not_zero_or_a_partial_year_average(self):
        api = FakeApi()
        api.data[1] = api.data[1][-10:]
        data = self.load(api)
        self.assertIsNone(data["atr"][-1]["price"])
        self.assertIsNone(data["dailyAverages"][0]["price"])
        self.assertIsNotNone(data["dailyAverages"][-1]["price"])
        self.assertIn("数据不足", data["atr"][-1]["reason"])

    def test_month_failure_preserves_week_and_day(self):
        api = FakeApi()
        api.data[3] = None
        data = self.load(api)
        self.assertIsNone(data["atr"][0]["price"])
        self.assertIsNone(data["atr"][1]["price"])
        self.assertEqual(data["atr"][2]["price"], 20)
        self.assertTrue(data["errors"])

    def test_missing_month_does_not_make_a_shortened_annual_candle(self):
        api = FakeApi()
        api.data[3] = [row for row in api.data[3]
                       if datetime.fromtimestamp(row["time"], timezone.utc).date().isoformat() != "2020-05-01"]
        data = self.load(api)
        self.assertIsNone(data["atr"][0]["price"])
        self.assertTrue(data["atr"][0]["reason"])

    def test_missing_last_year_is_unavailable(self):
        api = FakeApi()
        api.data[3] = [row for row in api.data[3]
                       if datetime.fromtimestamp(row["time"], timezone.utc).year != 2025]
        self.assertIn("上一完整年份", self.load(api)["atr"][0]["reason"])

    def test_invalid_point_preserves_price_but_not_points(self):
        api = FakeApi()
        for point in (0, -1, float("nan"), None):
            api.point = point
            data = self.load(api)
            self.assertEqual(data["atr"][-1]["price"], 20)
            self.assertIsNone(data["atr"][-1]["points"])
            self.assertEqual(data["errors"], [])

    def test_bad_bars_fail_instead_of_silently_changing_sample(self):
        for bad in (float("nan"), -1, 80):
            api = FakeApi()
            api.data[1][-3]["high"] = bad
            data = self.load(api)
            self.assertIsNone(data["atr"][-1]["price"])
            self.assertTrue(all(row["price"] is None for row in data["dailyAverages"]))

    def test_numpy_rows_and_unsorted_input(self):
        api = FakeApi()
        for key in api.data:
            rows = api.data[key]
            api.data[key] = np.array([tuple(row[name] for name in ("time", "open", "high", "low", "close"))
                                     for row in reversed(rows)],
                                    dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8")])
        # Return the whole shuffled selection to exercise sorting in the service.
        api.copy_rates_from_pos = lambda symbol, timeframe, start, count: api.data[timeframe]
        self.assertTrue(all(row["price"] == 20 for row in self.load(api)["atr"]))

    def test_period_validation_and_change(self):
        for period in (0, 101, True, 1.5):
            with self.assertRaises(ValueError):
                self.load(period=period)
        self.assertEqual(self.load(period=1)["atr"][-1]["samples"], 1)

    def test_zero_range_is_a_valid_value(self):
        api = FakeApi()
        api.data[1] = [dict(row, high=100, low=100) for row in api.data[1]]
        self.assertEqual(self.load(api)["atr"][-1]["price"], 0)


if __name__ == "__main__":
    unittest.main()
