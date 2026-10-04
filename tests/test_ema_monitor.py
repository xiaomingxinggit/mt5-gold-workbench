from decimal import Decimal
import unittest

from mt5_workbench.domain.ema_monitor import (
    MIN_M1_BARS,
    evaluate_m1_ema_alignment,
)


class EmaMonitorTests(unittest.TestCase):
    def test_flat_closes_align_all_four_emas(self):
        result = evaluate_m1_ema_alignment([4200] * MIN_M1_BARS,
                                            point="0.01", tolerance_points=1)
        self.assertTrue(result.aligned)
        self.assertEqual(result.emas, {7: Decimal(4200), 14: Decimal(4200),
                                       30: Decimal(4200), 60: Decimal(4200)})
        self.assertEqual(result.spread_points, 0)
        self.assertEqual(result.bars_used, MIN_M1_BARS)
        self.assertFalse(result.includes_forming_bar)

    def test_trending_closes_are_not_aligned_at_small_tolerance(self):
        closes = [Decimal(4200) + Decimal(index) / 10
                  for index in range(MIN_M1_BARS)]
        result = evaluate_m1_ema_alignment(closes, point="0.01",
                                            tolerance_points=5)
        self.assertFalse(result.aligned)
        self.assertGreater(result.ema7, result.ema14)
        self.assertGreater(result.ema14, result.ema30)
        self.assertGreater(result.ema30, result.ema60)
        self.assertEqual(result.spread_price / Decimal("0.01"),
                         result.spread_points)

    def test_threshold_is_inclusive_and_forming_bar_is_identified(self):
        closes = [4200] * MIN_M1_BARS
        closes[-1] = 4201
        probe = evaluate_m1_ema_alignment(closes, point="0.01",
                                           tolerance_points=0,
                                           includes_forming_bar=True)
        self.assertFalse(probe.aligned)
        at_boundary = evaluate_m1_ema_alignment(
            closes, point="0.01", tolerance_points=probe.spread_points,
            includes_forming_bar=True)
        self.assertTrue(at_boundary.aligned)
        self.assertTrue(at_boundary.includes_forming_bar)

    def test_rejects_insufficient_history_and_invalid_inputs(self):
        with self.assertRaisesRegex(ValueError, "至少需要 180"):
            evaluate_m1_ema_alignment([4200] * 179, point="0.01")
        for bad in (0, -1, "NaN", "Infinity", "not a number"):
            with self.subTest(point=bad), self.assertRaises(ValueError):
                evaluate_m1_ema_alignment([4200] * 180, point=bad)
        for bad in (-1, "NaN", "Infinity", "not a number"):
            with self.subTest(tolerance=bad), self.assertRaises(ValueError):
                evaluate_m1_ema_alignment([4200] * 180, point="0.01",
                                           tolerance_points=bad)
        with self.assertRaisesRegex(ValueError, "收盘价"):
            evaluate_m1_ema_alignment([4200] * 179 + [float("nan")],
                                       point="0.01")


if __name__ == "__main__":
    unittest.main()
