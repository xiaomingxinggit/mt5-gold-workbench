"""Local market journal records, independent of MT5 and the Qt interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path


AccountKey = tuple[int, str]


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """The position facts retained when a post is published."""

    position_id: int
    ticket: int
    symbol: str
    side: str
    volume: Decimal
    price_open: Decimal
    opened_at: datetime
    sl: Decimal | None = None
    tp: Decimal | None = None
    floating_usc: Decimal = Decimal("0")
    account_key: AccountKey | None = None


@dataclass(frozen=True, slots=True)
class PositionLink(PositionSnapshot):
    post_id: int = 0
    status: str = "open"
    result_usc: Decimal | None = None
    closed_at: datetime | None = None
    linked_at: datetime | None = None  # The post's publication time, for reversal boundaries.


@dataclass(frozen=True, slots=True)
class JournalPost:
    id: int
    account_key: AccountKey
    body: str
    created_at: datetime
    images: tuple[Path, ...]
    positions: tuple[PositionLink, ...]


@dataclass(frozen=True, slots=True)
class JournalPage:
    posts: tuple[JournalPost, ...]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return (self.total + self.page_size - 1) // self.page_size
