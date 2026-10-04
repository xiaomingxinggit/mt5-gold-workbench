"""Account admission rule for this USC cent-account workbench."""

from __future__ import annotations


def is_usc_currency(currency) -> bool:
    return str(currency or "").strip().upper() == "USC"


def is_usc_account(account) -> bool:
    return is_usc_currency(getattr(account, "currency", None))
