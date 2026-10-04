"""Read-only market and account views."""

from datetime import datetime, timezone

import MetaTrader5 as mt5


def symbol_and_tick(name: str):
    symbol = mt5.symbol_info(name)
    if symbol is None:
        raise ValueError(f"Symbol {name!r} does not exist in this MT5 terminal")
    if not symbol.visible and not mt5.symbol_select(name, True):
        raise ValueError(f"Cannot add {name} to Market Watch: {mt5.last_error()}")
    tick = mt5.symbol_info_tick(name)
    if tick is None or tick.bid <= 0 or tick.ask <= 0 or tick.ask < tick.bid:
        raise ValueError(f"No valid quote for {name}: {mt5.last_error()}")
    return symbol, tick


def quote_line(name: str, tick, digits: int) -> str:
    timestamp = datetime.fromtimestamp(tick.time_msc / 1000, timezone.utc).astimezone()
    return (f"{name} {timestamp.isoformat(timespec='milliseconds')} "
            f"Bid={tick.bid:.{digits}f} Ask={tick.ask:.{digits}f}")


def positions(name: str):
    rows = mt5.positions_get(symbol=name)
    if rows is None:
        raise RuntimeError(f"positions_get failed: {mt5.last_error()}")
    return rows


def orders(name: str):
    rows = mt5.orders_get(symbol=name)
    if rows is None:
        raise RuntimeError(f"orders_get failed: {mt5.last_error()}")
    return rows
