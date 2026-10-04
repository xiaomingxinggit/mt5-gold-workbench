"""Offline tests for the read-only M1 EMA observation service."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mt5_workbench.services import ema_monitor as ema_service
from mt5_workbench.services.ema_monitor import fetch_m1_ema_snapshot


NOW = datetime(2026, 10, 4, 10, 5, 20, tzinfo=timezone.utc)
MINUTE = NOW.replace(second=0, microsecond=0)


def rates(count=200, *, last_minute=MINUTE, close=4200.0):
    first = last_minute - timedelta(minutes=count - 1)
    return [{"time": int((first + timedelta(minutes=i)).timestamp()),
             "close": close} for i in range(count)]


class FakeApi:
    TIMEFRAME_M1 = 1

    def __init__(self, *, now=NOW, rates_data=None, bid=4200.0,
                 ask=4200.2, point=0.01, quote_age=1):
        self.calls = []
        self.info = SimpleNamespace(point=point)
        self.tick = SimpleNamespace(
            bid=bid, ask=ask,
            time_msc=int((now - timedelta(seconds=quote_age)).timestamp() * 1000))
        self.rates_data = rates() if rates_data is None else rates_data

    def symbol_info(self, symbol):
        self.calls.append(("symbol_info", symbol))
        return self.info

    def symbol_info_tick(self, symbol):
        self.calls.append(("symbol_info_tick", symbol))
        return self.tick

    def copy_rates_from_pos(self, symbol, timeframe, offset, count):
        self.calls.append(("copy_rates_from_pos", symbol, timeframe, offset,
                           count))
        return self.rates_data


class EmaMonitorServiceTests(unittest.TestCase):
    def test_flat_current_m1_is_live_and_mapping_is_immutable(self):
        api = FakeApi(rates_data=list(reversed(rates())))
        result = fetch_m1_ema_snapshot(api=api, now=NOW)
        self.assertEqual(result.status, "live")
        self.assertTrue(result.aligned)
        self.assertTrue(result.includes_forming_bar)
        self.assertEqual(result.bar_time, MINUTE)
        self.assertEqual(result.observed_at, NOW)
        self.assertEqual(result.quote_age_seconds, 1)
        self.assertEqual(result.ema_spread_points, Decimal("0"))
        self.assertEqual(result.ema_values[7], Decimal("4200.0"))
        with self.assertRaises(TypeError):
            result.ema_values[7] = Decimal(0)
        self.assertEqual(api.calls, [
            ("symbol_info", "XAUUSDc"),
            ("symbol_info_tick", "XAUUSDc"),
            ("copy_rates_from_pos", "XAUUSDc", api.TIMEFRAME_M1, 0, 200),
        ])

    def test_trending_prices_are_live_but_not_aligned(self):
        rows = rates()
        for i, row in enumerate(rows):
            row["close"] += i / 10
        result = fetch_m1_ema_snapshot(api=FakeApi(rates_data=rows), now=NOW)
        self.assertEqual(result.status, "live")
        self.assertFalse(result.aligned)
        self.assertGreater(result.ema_spread_points, 5)

    def test_delayed_quote_never_signals_even_with_flat_emas(self):
        result = fetch_m1_ema_snapshot(api=FakeApi(quote_age=16), now=NOW)
        self.assertEqual(result.status, "stale")
        self.assertFalse(result.aligned)
        self.assertIn("报价", result.reason)

    def test_slow_mt5_read_checks_freshness_when_call_finishes(self):
        class Clock(datetime):
            times = iter((NOW, NOW + timedelta(seconds=20)))

            @classmethod
            def now(cls, tz=None):
                return next(cls.times)

        with patch.object(ema_service, "datetime", Clock):
            result = fetch_m1_ema_snapshot(api=FakeApi())
        self.assertEqual(result.status, "stale")
        self.assertFalse(result.aligned)
        self.assertEqual(result.quote_age_seconds, 21)

    def test_stale_bar_never_signals(self):
        old = MINUTE - timedelta(minutes=2)
        result = fetch_m1_ema_snapshot(
            api=FakeApi(rates_data=rates(last_minute=old)), now=NOW)
        self.assertEqual(result.status, "stale")
        self.assertFalse(result.aligned)
        self.assertEqual(result.bar_time, old)

    def test_previous_minute_bar_waits_even_within_age_limit(self):
        previous = MINUTE - timedelta(minutes=1)
        result = fetch_m1_ema_snapshot(
            api=FakeApi(rates_data=rates(last_minute=previous)), now=NOW)
        self.assertEqual(result.status, "waiting")
        self.assertFalse(result.aligned)
        self.assertIn("当前分钟", result.reason)

    def test_missing_minutes_in_history_do_not_block_ema(self):
        first = MINUTE - timedelta(minutes=200)
        rows = [{"time": int((first + timedelta(minutes=i)).timestamp()),
                 "close": 4200.0} for i in range(201) if i != 51]
        result = fetch_m1_ema_snapshot(api=FakeApi(rates_data=rows), now=NOW)
        self.assertEqual(result.status, "live")
        self.assertTrue(result.aligned)

    def test_insufficient_duplicate_or_invalid_rates_never_signal(self):
        invalid = [
            rates(count=179),
            rates()[:-1] + [rates()[-2]],
            rates()[:-1] + [{"time": int(MINUTE.timestamp()),
                             "close": float("nan")}],
        ]
        for rows in invalid:
            with self.subTest(rows=len(rows), last=rows[-1]):
                result = fetch_m1_ema_snapshot(
                    api=FakeApi(rates_data=rows), now=NOW)
                self.assertEqual(result.status, "waiting")
                self.assertFalse(result.aligned)

    def test_missing_symbol_or_tick_does_not_signal(self):
        api = FakeApi()
        api.info = None
        result = fetch_m1_ema_snapshot(api=api, now=NOW)
        self.assertEqual(result.status, "error")
        self.assertFalse(result.aligned)
        api = FakeApi()
        api.tick = None
        result = fetch_m1_ema_snapshot(api=api, now=NOW)
        self.assertEqual(result.status, "waiting")
        self.assertFalse(result.aligned)

    def test_invalid_tolerance_and_naive_now_fail_before_mt5_call(self):
        api = FakeApi()
        with self.assertRaises(ValueError):
            fetch_m1_ema_snapshot(api=api, tolerance_points="NaN")
        with self.assertRaises(ValueError):
            fetch_m1_ema_snapshot(api=api, now=NOW.replace(tzinfo=None))
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
