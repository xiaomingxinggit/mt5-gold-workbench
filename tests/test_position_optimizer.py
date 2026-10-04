from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mt5_workbench.domain.position_optimizer import optimize


def cent_account_profit(_side, _symbol, volume, entry, stop):
    return -abs(stop - entry) * volume * 100


class PositionOptimizerTests(unittest.TestCase):
    def setUp(self):
        self.symbol = SimpleNamespace(name="XAUUSDc", trade_tick_size=0.001,
                                      point=0.001, volume_min=0.01,
                                      volume_max=200.0, volume_step=0.01,
                                      volume_limit=0.0)
        self.args = (self.symbol, "USC", 4200, 4210, 4220, 30)

    def test_weighted_three_levels(self):
        result = optimize(*self.args, mode="weighted", levels=3,
                          weights=(Decimal(1), Decimal(2), Decimal(3)),
                          profit_fn=cent_account_profit)
        self.assertEqual([row.price for row in result.entries],
                         [Decimal(4200), Decimal(4205), Decimal(4210)])
        self.assertEqual([row.volume for row in result.entries],
                         [Decimal("0.23"), Decimal("0.64"), Decimal("1.43")])
        self.assertEqual(result.budget_usage_percent, Decimal("95"))
        self.assertEqual(result.risk_cap_usd, Decimal("28.5"))
        self.assertEqual(result.total_risk_usd, Decimal("28.500"))
        self.assertEqual(result.unused_usd, Decimal("1.500"))
        self.assertEqual(result.total_volume, Decimal("2.30"))

    def test_non_usc_account_cannot_calculate(self):
        profit = Mock(side_effect=cent_account_profit)
        with self.assertRaisesRegex(ValueError, "USC 美分账户"):
            optimize(self.symbol, "USD", 4200, 4210, 4220, 30,
                     mode="max_lots_single", profit_fn=profit)
        profit.assert_not_called()

    def test_max_lots_tradeoff(self):
        ladder = optimize(*self.args, mode="max_lots_ladder", levels=3,
                          profit_fn=cent_account_profit)
        single = optimize(*self.args, mode="max_lots_single", levels=3,
                          profit_fn=cent_account_profit)
        self.assertEqual(ladder.total_volume, Decimal("2.83"))
        self.assertEqual(single.total_volume, Decimal("2.85"))
        self.assertLessEqual(ladder.total_risk_usd, Decimal("28.5"))
        self.assertLessEqual(single.total_risk_usd, Decimal("28.5"))

    def test_stop_must_be_outside_range(self):
        with self.assertRaisesRegex(ValueError, "止损必须"):
            optimize(self.symbol, "USC", 4200, 4210, 4205, 30,
                     profit_fn=cent_account_profit)

    def test_minimum_lot_budget_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "最小手数"):
            optimize(self.symbol, "USC", 4200, 4210, 4220, 0.1,
                     mode="max_lots_ladder", profit_fn=cent_account_profit)

    def test_buy_single_uses_endpoint_closest_to_stop(self):
        result = optimize(self.symbol, "USC", 4200, 4210, 4190, 30,
                          mode="max_lots_single", profit_fn=cent_account_profit)
        self.assertEqual(result.side, "BUY")
        self.assertEqual(result.entries[0].price, Decimal(4200))
        self.assertEqual(result.total_volume, Decimal("2.85"))

    def test_usage_percentage_applies_to_every_mode(self):
        for mode in ("weighted", "equal_risk", "max_lots_ladder", "max_lots_single"):
            with self.subTest(mode=mode):
                result = optimize(*self.args, mode=mode, levels=3,
                                  weights=(1, 2, 3) if mode == "weighted" else None,
                                  budget_usage_percent="80%",
                                  profit_fn=cent_account_profit)
                self.assertEqual(result.risk_cap_usd, Decimal("24"))
                self.assertLessEqual(result.total_risk_usd, result.risk_cap_usd)
                self.assertGreaterEqual(result.unused_usd, Decimal("6"))

    def test_usage_percentage_validation(self):
        for percent in (0, -5, 101, "NaN"):
            with self.subTest(percent=percent), self.assertRaises(ValueError):
                optimize(*self.args, mode="max_lots_single",
                         budget_usage_percent=percent,
                         profit_fn=cent_account_profit)

    def test_100_percent_is_supported(self):
        result = optimize(*self.args, mode="max_lots_single",
                          budget_usage_percent=100,
                          profit_fn=cent_account_profit)
        self.assertEqual(result.total_volume, Decimal("3.00"))
        self.assertEqual(result.total_risk_usd, Decimal("30.00"))

    def test_weight_count_must_match_levels(self):
        with self.assertRaisesRegex(ValueError, "3 个正数权重"):
            optimize(*self.args, levels=3, mode="weighted", weights=(1, 2),
                     profit_fn=cent_account_profit)

    def test_optional_take_profit_keeps_risk_sizing_and_checks_side(self):
        without_target = optimize(*self.args, mode="max_lots_single",
                                  profit_fn=cent_account_profit)
        with_target = optimize(*self.args, mode="max_lots_single",
                               take_profit="4190", profit_fn=cent_account_profit)
        self.assertEqual(with_target.take_profit, Decimal("4190"))
        self.assertEqual(with_target.total_volume, without_target.total_volume)
        self.assertEqual(with_target.total_risk_usd, without_target.total_risk_usd)
        self.assertIsNone(without_target.take_profit)
        with self.assertRaisesRegex(ValueError, "低于区间起点"):
            optimize(*self.args, mode="max_lots_single", take_profit="4200",
                     profit_fn=cent_account_profit)
        with self.assertRaisesRegex(ValueError, "高于区间终点"):
            optimize(self.symbol, "USC", 4200, 4210, 4190, 30,
                     mode="max_lots_single", take_profit="4210",
                     profit_fn=cent_account_profit)

    def test_take_profit_uses_symbol_price_step(self):
        with self.assertRaisesRegex(ValueError, "最小跳动"):
            optimize(*self.args, mode="max_lots_single",
                     take_profit="4190.0005", profit_fn=cent_account_profit)


if __name__ == "__main__":
    unittest.main()
