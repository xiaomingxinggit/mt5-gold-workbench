"""Read the active MT5 account and live XAUUSDc quotes. No trading operations."""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

import MetaTrader5 as mt5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="XAUUSDc", help="Exact broker symbol")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    parser.add_argument("--samples", type=int, default=0, help="Stop after N polls (0 = keep running)")
    parser.add_argument("--terminal", help="Optional path to terminal64.exe")
    args = parser.parse_args()
    if args.interval <= 0 or args.samples < 0:
        parser.error("--interval must be positive and --samples cannot be negative")
    return args


def mask_login(login: int) -> str:
    value = str(login)
    return "*" * max(0, len(value) - 4) + value[-4:]


def main() -> int:
    args = parse_args()
    connected = mt5.initialize(args.terminal) if args.terminal else mt5.initialize()
    if not connected:
        print(f"MT5 connection failed: {mt5.last_error()}")
        return 1

    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            print(f"MT5 terminal is not connected to the broker: {mt5.last_error()}")
            return 1

        account = mt5.account_info()
        if account is None:
            print(f"Account read failed: {mt5.last_error()}")
            return 1
        print(f"MT5 terminal: {terminal.name} | {terminal.path}")
        print(
            f"Account: {mask_login(account.login)} | server={account.server} | "
            f"name={account.name} | currency={account.currency}"
        )
        print(
            f"Balance={account.balance:.2f} | equity={account.equity:.2f} | "
            f"margin={account.margin:.2f} | free_margin={account.margin_free:.2f}"
        )

        symbol = mt5.symbol_info(args.symbol)
        if symbol is None:
            matches = mt5.symbols_get(group="*XAUUSD*") or ()
            names = ", ".join(item.name for item in matches[:15]) or "none"
            print(f"Symbol {args.symbol!r} unavailable. XAUUSD matches: {names}")
            return 1
        if not symbol.visible and not mt5.symbol_select(args.symbol, True):
            print(f"Cannot enable {args.symbol} in Market Watch: {mt5.last_error()}")
            return 1

        print(f"Watching {args.symbol} every {args.interval:g}s. Press Ctrl+C to stop.")
        sample = 0
        while args.samples == 0 or sample < args.samples:
            tick = mt5.symbol_info_tick(args.symbol)
            if tick is None:
                print(f"Tick read failed: {mt5.last_error()}")
            else:
                quote_time = datetime.fromtimestamp(tick.time_msc / 1000, tz=timezone.utc)
                age = max(0.0, time.time() - tick.time_msc / 1000)
                print(
                    f"{quote_time.astimezone().isoformat(timespec='milliseconds')} "
                    f"bid={tick.bid:.{symbol.digits}f} "
                    f"ask={tick.ask:.{symbol.digits}f} "
                    f"spread={tick.ask - tick.bid:.{symbol.digits}f} "
                    f"age={age:.1f}s"
                )
            sample += 1
            if args.samples == 0 or sample < args.samples:
                time.sleep(args.interval)
        return 0
    except KeyboardInterrupt:
        print("Stopped.")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
