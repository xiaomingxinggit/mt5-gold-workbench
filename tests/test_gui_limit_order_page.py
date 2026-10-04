"""Centered LIMIT entry input and risk-cap UI contract (offline only)."""

from __future__ import annotations

import os
import unittest
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mt5_workbench.domain.position_optimizer import optimize
from mt5_workbench.ui.main_window import MainWindow
from mt5_workbench.ui.pages.optimizer import OptimizerPage
from mt5_workbench.ui.theme import THEMES


def cent_profit(_side, _symbol, volume, entry, stop):
    return -abs(stop - entry) * volume * 100


class LimitOrderPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = OptimizerPage(THEMES["light"], "light")
        self.addCleanup(self.page.close)

    def test_center_and_tolerance_generate_three_levels_under_95_percent_cap(self):
        self.page.inputs["center"].setText("4220")
        self.page.inputs["tolerance"].setText("1")
        self.page.inputs["stop"].setText("4224")
        self.page.inputs["budget"].setText("30")
        low, high, stop, target, budget, usage, levels, mode, weights = (
            self.page.read_inputs())
        self.assertEqual((low, high), (Decimal("4219"), Decimal("4221")))
        self.assertEqual((usage, levels, mode, weights),
                         ("95", 3, "weighted", (Decimal(1), Decimal(2), Decimal(3))))
        self.assertIn("4219～4221", self.page.range_hint.text())

        symbol = SimpleNamespace(name="XAUUSDc", trade_tick_size=0.001,
                                 point=0.001, volume_min=0.01, volume_max=200.0,
                                 volume_step=0.01, volume_limit=0.0)
        result = optimize(symbol, "USC", low, high, stop, budget,
                          levels=levels, mode=mode, weights=weights,
                          budget_usage_percent=usage, take_profit=target,
                          profit_fn=cent_profit)
        self.assertEqual([entry.price for entry in result.entries],
                         [Decimal("4219"), Decimal("4220"), Decimal("4221")])
        self.assertEqual(result.risk_cap_usd, Decimal("28.5"))
        self.assertLessEqual(result.total_risk_usd, result.risk_cap_usd)
        self.assertEqual((result.range_low, result.range_high),
                         (Decimal("4219"), Decimal("4221")))
        self.page.set_result(result, ("不可作为 LIMIT",) * 3, "对照", "警告", stop,
                             can_preview=False)
        self.assertFalse(self.page.send_button.isEnabled())
        self.assertIn("入场区间 4219～4221", self.page.info.text())

    def test_invalid_center_or_tolerance_is_rejected(self):
        for center, tolerance, expected in (
            ("", "1", "目标入场价需要填写数字"),
            ("4220", "0", "误差度必须大于 0"),
            ("4220", "4220", "区间起点必须大于 0"),
            ("NaN", "1", "目标入场价必须大于 0"),
        ):
            with self.subTest(center=center, tolerance=tolerance):
                self.page.inputs["center"].setText(center)
                self.page.inputs["tolerance"].setText(tolerance)
                with self.assertRaisesRegex(ValueError, expected):
                    self.page.read_inputs()

    def test_limit_candidate_uses_the_same_quote_side_as_send_validation(self):
        shell = SimpleNamespace(tick=SimpleNamespace(bid=4219.8, ask=4220.2))
        self.assertEqual(MainWindow._suggested_type(shell, Decimal("4220"), "SELL"),
                         "不可作为 LIMIT")
        self.assertEqual(MainWindow._suggested_type(shell, Decimal("4220.3"), "SELL"),
                         "SELL LIMIT")
        self.assertEqual(MainWindow._suggested_type(shell, Decimal("4220"), "BUY"),
                         "不可作为 LIMIT")
        self.assertEqual(MainWindow._suggested_type(shell, Decimal("4219.7"), "BUY"),
                         "BUY LIMIT")


if __name__ == "__main__":
    unittest.main()
