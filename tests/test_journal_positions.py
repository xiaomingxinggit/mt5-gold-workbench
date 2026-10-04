"""Read-only MT5 journal position linkage and result reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import unittest

from mt5_workbench.domain.journal import PositionLink
from mt5_workbench.services.journal_positions import (
    load_open_positions, sync_closed_positions,
)


ACCOUNT_KEY = (100001, "Demo-Server")


def _position(identifier=1001, ticket=2002, **changes):
    values = dict(identifier=identifier, ticket=ticket, symbol="XAUUSDc", type=1,
                  volume=0.01, price_open=4200.0, time=1_700_000_000,
                  sl=4220.0, tp=4180.0, profit=125.5, swap=-0.5)
    values.update(changes)
    return SimpleNamespace(**values)


def _deal(ticket, entry, *, time=1_700_000_100, profit=0, swap=0,
          commission=0, fee=0, position_id=1001):
    return SimpleNamespace(ticket=ticket, entry=entry, time=time,
                           position_id=position_id, symbol="XAUUSDc",
                           profit=profit, swap=swap, commission=commission,
                           fee=fee)


def _link(position_id=1001, post_id=1):
    return PositionLink(position_id=position_id, ticket=2002, symbol="XAUUSDc",
                        side="SELL", volume=Decimal("0.01"),
                        price_open=Decimal("4200"),
                        opened_at=datetime.fromtimestamp(1_700_000_000, timezone.utc),
                        account_key=ACCOUNT_KEY, post_id=post_id,
                        linked_at=datetime.fromtimestamp(1_700_000_050, timezone.utc))


class FakeMT5:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    DEAL_ENTRY_IN = 0
    DEAL_ENTRY_OUT = 1
    DEAL_ENTRY_INOUT = 2
    DEAL_ENTRY_OUT_BY = 3

    def __init__(self, positions=(), deals=()):
        self.positions = positions
        self.deals = deals
        self.account_sequence = []
        self.position_calls = []
        self.history_calls = []

    def account_info(self):
        if self.account_sequence:
            return self.account_sequence.pop(0)
        return SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1],
                               currency="USC")

    def positions_get(self, **kwargs):
        self.position_calls.append(kwargs)
        return self.positions

    def history_deals_get(self, **kwargs):
        self.history_calls.append(kwargs)
        return self.deals

    def last_error(self):
        return (-1, "offline")


class FakeRepo:
    def __init__(self, links):
        self.links = links
        self.closed = []
        self.unverified = []

    def open_links(self, account_key):
        assert account_key == ACCOUNT_KEY
        return self.links

    def close_link(self, account_key, post_id, position_id, result_usc, closed_at):
        assert account_key == ACCOUNT_KEY
        self.closed.append((post_id, position_id, result_usc, closed_at))
        return 1

    def mark_unverified(self, account_key, post_id, position_id):
        assert account_key == ACCOUNT_KEY
        self.unverified.append((post_id, position_id))
        return 1


class JournalPositionTests(unittest.TestCase):
    def test_load_uses_stable_identifier_and_usc_amounts(self):
        api = FakeMT5(positions=(_position(),))
        positions = load_open_positions(ACCOUNT_KEY, api=api)
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].position_id, 1001)
        self.assertEqual(positions[0].ticket, 2002)
        self.assertEqual(positions[0].account_key, ACCOUNT_KEY)
        self.assertEqual(positions[0].side, "SELL")
        self.assertEqual(positions[0].floating_usc, Decimal("125.0"))
        self.assertEqual(positions[0].opened_at,
                         datetime.fromtimestamp(1_700_000_000, timezone.utc))
        self.assertEqual(api.position_calls, [{"symbol": "XAUUSDc"}])

    def test_load_rejects_other_symbol_and_account_switch(self):
        api = FakeMT5(positions=(_position(),))
        with self.assertRaisesRegex(ValueError, "XAUUSDc"):
            load_open_positions(ACCOUNT_KEY, "EURUSD", api=api)
        self.assertEqual(api.position_calls, [])
        api.account_sequence = [
            SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1], currency="USC"),
            SimpleNamespace(login=999, server=ACCOUNT_KEY[1], currency="USC"),
        ]
        with self.assertRaisesRegex(RuntimeError, "账户已切换"):
            load_open_positions(ACCOUNT_KEY, api=api)

    def test_load_falls_back_to_ticket_when_identifier_is_zero(self):
        api = FakeMT5(positions=(_position(identifier=0, ticket=2002,
                                           time_msc=1_700_000_000_500),))
        positions = load_open_positions(ACCOUNT_KEY, api=api)
        self.assertEqual(positions[0].position_id, 2002)
        self.assertEqual(positions[0].opened_at.microsecond, 500_000)

    def test_sync_does_not_finalize_active_partially_closed_position(self):
        api = FakeMT5(positions=(_position(volume=0.005),))
        repo = FakeRepo((_link(),))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 0)
        self.assertEqual(result.errors, ())
        self.assertEqual(api.history_calls, [])
        self.assertEqual(repo.closed, [])

    def test_sync_sums_all_cashflow_once_for_multiple_posts(self):
        api = FakeMT5(deals=(
            _deal(11, 0, commission=-1.0),
            _deal(12, 1, profit=12.0, swap=-2.0, commission=-1.2, fee=-0.3),
        ))
        repo = FakeRepo((_link(post_id=1), _link(post_id=2)))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 2)
        self.assertEqual(result.errors, ())
        self.assertEqual(api.history_calls, [{"position": 1001}])
        self.assertEqual(repo.closed,
                         [(1, 1001, Decimal("7.5"),
                           datetime.fromtimestamp(1_700_000_100, timezone.utc)),
                          (2, 1001, Decimal("7.5"),
                           datetime.fromtimestamp(1_700_000_100, timezone.utc))])

    def test_sync_preserves_link_when_history_unavailable_or_no_exit(self):
        api = FakeMT5(deals=None)
        repo = FakeRepo((_link(),))
        failed = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(failed.updated_count, 0)
        self.assertIn("读取失败", failed.errors[0])
        self.assertEqual(repo.closed, [])
        api.deals = (_deal(11, api.DEAL_ENTRY_IN),)
        pending = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(pending.updated_count, 0)
        self.assertIn("尚无平仓成交", pending.errors[0])
        self.assertEqual(repo.closed, [])

    def test_sync_never_finalizes_when_positions_read_fails(self):
        api = FakeMT5(positions=None, deals=(_deal(12, 1, profit=2),))
        repo = FakeRepo((_link(),))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 0)
        self.assertIn("读取持仓失败", result.errors[0])
        self.assertEqual(api.history_calls, [])
        self.assertEqual(repo.closed, [])

    def test_sync_account_switch_after_history_never_writes(self):
        api = FakeMT5(deals=(_deal(11, 0), _deal(12, 1, profit=2)))
        api.account_sequence = [
            SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1], currency="USC"),
            SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1], currency="USC"),
            SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1], currency="USC"),
            SimpleNamespace(login=ACCOUNT_KEY[0], server=ACCOUNT_KEY[1], currency="USD"),
        ]
        repo = FakeRepo((_link(),))
        with self.assertRaisesRegex(RuntimeError, "USC"):
            sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(repo.closed, [])

    def test_netting_reversal_closes_only_the_original_stage(self):
        api = FakeMT5(
            positions=(_position(ticket=3003, type=0),),
            deals=(
                _deal(11, FakeMT5.DEAL_ENTRY_IN, time=1_700_000_000,
                      commission=-1),
                _deal(12, FakeMT5.DEAL_ENTRY_OUT, time=1_700_000_080,
                      profit=2),
                _deal(13, FakeMT5.DEAL_ENTRY_INOUT, time=1_700_000_100,
                      profit=5, commission=-1),
                _deal(14, FakeMT5.DEAL_ENTRY_OUT, time=1_700_000_200,
                      profit=-7),
            ),
        )
        repo = FakeRepo((_link(),))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(repo.closed[0][2], Decimal("5"))
        self.assertEqual(repo.closed[0][3],
                         datetime.fromtimestamp(1_700_000_100, timezone.utc))
        self.assertEqual(repo.unverified, [])

    def test_same_second_new_stage_deal_is_excluded_after_reversal(self):
        api = FakeMT5(deals=(
            _deal(11, FakeMT5.DEAL_ENTRY_IN, time=1_700_000_000),
            _deal(12, FakeMT5.DEAL_ENTRY_INOUT, time=1_700_000_100,
                  profit=5),
            _deal(13, FakeMT5.DEAL_ENTRY_OUT, time=1_700_000_100,
                  profit=-8),
        ))
        repo = FakeRepo((_link(),))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(repo.closed[0][2], Decimal("5"))

    def test_post_on_reversed_stage_stays_unverified_when_result_ambiguous(self):
        api = FakeMT5(deals=(
            _deal(11, FakeMT5.DEAL_ENTRY_IN, time=1_700_000_000,
                  commission=-1),
            _deal(12, FakeMT5.DEAL_ENTRY_INOUT, time=1_700_000_100,
                  profit=5, commission=-1),
            _deal(13, FakeMT5.DEAL_ENTRY_OUT, time=1_700_000_200,
                  profit=3),
        ))
        first = _link(post_id=1)
        second = PositionLink(
            position_id=1001, ticket=3003, symbol="XAUUSDc", side="BUY",
            volume=Decimal("0.01"), price_open=Decimal("4205"),
            opened_at=datetime.fromtimestamp(1_700_000_100, timezone.utc),
            linked_at=datetime.fromtimestamp(1_700_000_150, timezone.utc),
            account_key=ACCOUNT_KEY, post_id=2,
        )
        repo = FakeRepo((first, second))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(repo.closed[0][0], 1)
        self.assertEqual(repo.unverified, [(2, 1001)])

    def test_link_from_another_account_is_never_reconciled(self):
        api = FakeMT5(deals=(_deal(11, FakeMT5.DEAL_ENTRY_OUT,
                                   profit=3),))
        foreign = PositionLink(
            position_id=1001, ticket=2002, symbol="XAUUSDc", side="SELL",
            volume=Decimal("0.01"), price_open=Decimal("4200"),
            opened_at=datetime.fromtimestamp(1_700_000_000, timezone.utc),
            account_key=(999, "other"), post_id=1,
        )
        repo = FakeRepo((foreign,))
        result = sync_closed_positions(repo, ACCOUNT_KEY, api=api)
        self.assertEqual(result.updated_count, 0)
        self.assertIn("账户不匹配", result.errors[0])
        self.assertEqual(api.history_calls, [])


if __name__ == "__main__":
    unittest.main()
