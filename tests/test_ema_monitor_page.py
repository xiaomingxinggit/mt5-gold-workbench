"""Behavioral checks for the experimental read-only EMA monitor page."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from mt5_workbench.ui.pages.ema_monitor import EmaMonitorPage
from mt5_workbench.ui.theme import THEMES


def _snapshot(*, aligned: bool = True, minute: int = 0):
    bar_time = datetime(2026, 10, 4, 2, minute, tzinfo=timezone.utc)
    return SimpleNamespace(
        bid=Decimal("4199.120"), ask=Decimal("4199.140"),
        ema_values={7: Decimal("4199.10123"), 14: Decimal("4199.10200"),
                    30: Decimal("4199.10300"), 60: Decimal("4199.10411")},
        ema_spread_points=Decimal("2.88"), tolerance_points=Decimal("5"),
        aligned=aligned, bar_time=bar_time,
        observed_at=bar_time + timedelta(seconds=25),
        quote_age_seconds=0.4, reason="EMA 差距已进入阈值" if aligned else "EMA 差距超过阈值",
        status="live", includes_forming_bar=True,
    )


class EmaMonitorPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_candidate_is_read_only_and_logged_once_per_bar(self):
        page = EmaMonitorPage("XAUUSDc", THEMES["light"])
        self.addCleanup(page.close)
        page.set_snapshot(_snapshot())
        self.assertEqual(page.state_value.text(), "EMA 聚拢候选")
        self.assertEqual(page.ema_values[7].text(), "4,199.10123")
        self.assertEqual(page.history_table.rowCount(), 1)

        page.set_snapshot(_snapshot())
        self.assertEqual(page.history_table.rowCount(), 1)
        page.set_snapshot(_snapshot(aligned=False, minute=1))
        self.assertEqual(page.state_value.text(), "等待 EMA 聚拢")
        page.set_snapshot(_snapshot(minute=2))
        self.assertEqual(page.history_table.rowCount(), 2)

        stale = _snapshot(minute=3)
        stale.status = "stale"
        page.set_snapshot(stale)
        self.assertEqual(page.state_value.text(), "数据暂不可用")
        self.assertEqual(page.history_table.rowCount(), 2)

        page.clear("账户已切换")
        self.assertEqual(page.bid_value.text(), "—")
        self.assertEqual(page.history_table.rowCount(), 0)
        self.assertIn("账户已切换", page.state_note.text())

    def test_threshold_signal_and_snapshot_do_not_revert_user_input(self):
        page = EmaMonitorPage("XAUUSDc", THEMES["dark"])
        self.addCleanup(page.close)
        thresholds: list[float] = []
        refreshes: list[bool] = []
        page.tolerance_changed.connect(thresholds.append)
        page.refresh_requested.connect(lambda: refreshes.append(True))
        page.tolerance_input.setValue(8.5)
        page.set_snapshot(_snapshot())  # This read was calculated at the old threshold.
        page.refresh_button.click()
        self.assertEqual(thresholds, [8.5])
        self.assertEqual(page.tolerance_points, 8.5)
        self.assertEqual(refreshes, [True])

    def test_both_themes_and_narrow_layout(self):
        page = EmaMonitorPage("XAUUSDc", THEMES["light"])
        self.addCleanup(page.close)
        page.resize(900, 740)
        page.show()
        self.app.processEvents()
        self.assertEqual(page.metrics_grid.itemAtPosition(1, 0).widget(), page.ema_cards[30])
        page.set_palette(THEMES["dark"])
        page.resize(1500, 950)
        self.app.processEvents()
        self.assertEqual(page.metrics_grid.itemAtPosition(0, 3).widget(), page.ema_cards[60])


if __name__ == "__main__":
    unittest.main()
