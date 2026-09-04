#!/usr/bin/env python3
"""Check what the STRATEGY reads, not what the fetcher wrote.

    .venv/Scripts/python.exe backtest/verify_data.py
    .venv/Scripts/python.exe backtest/verify_data.py --sample 12   # also re-ask IB

Three bugs in a row got past me because I verified the writing side and stopped.
ibkr_refresh reported "228 refreshed, 0 failed" every time and was telling the
truth; the data was then replaced before anything computed a signal on it. What
matters is the value load_daily hands back to scan_daily, so that is what this
checks - through load_daily itself, with the scan's exact arguments.

The three paths, all of which produced a confident wrong answer:

  1. --skip-current trusted the cache's own last DATE. Yahoo writes a row for the
     session in progress, so a partial bar looked like a finished one and the
     symbol was skipped.
  2. the .meta RANGE check. IB serves 5 years, the scan asks for 2021-01-01, so
     every IB file looked too short and was refetched from Yahoo - undoing a
     40-minute conversion within minutes of it finishing.
  3. the STALENESS check, a separate trigger from 2. With the gateway down and
     IB's newest US bar a day behind, 166 of 228 symbols were refetched from
     Yahoo and put back on adjusted prices.

Each looked fixed because the one path I tested was. So this asserts on the end
state instead of on any path: is what the strategy reads raw, current, and the
same thing IB would serve if asked again right now?

Exit status is non-zero if anything fails, so it can gate the morning run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import load_daily, parse_watchlist

PROV = Path("data_cache/ibkr_provenance.json")


def ema(s: pd.Series, span: int) -> float:
    return float(s.ewm(span=span, adjust=False).mean().iloc[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", action="append", default=[])
    ap.add_argument("--start", default="2021-01-01",
                    help="must match what scan_daily passes, or this proves nothing")
    ap.add_argument("--sample", type=int, default=0,
                    help="re-ask IB for this many symbols and compare EMA200. The "
                         "only check that can catch a cache that is internally "
                         "consistent but on the wrong price convention")
    ap.add_argument("--tolerance", type=float, default=0.5,
                    help="max %% difference in EMA200 against a fresh IB fetch")
    ap.add_argument("--port", type=int, default=4001)
    ap.add_argument("--client-id", type=int, default=41)
    args = ap.parse_args()

    prov = {}
    if PROV.exists():
        prov = json.loads(PROV.read_text(encoding="utf-8"))
    if not prov:
        print("no data_cache/ibkr_provenance.json - nothing has been IB-sourced yet")
        return 1

    seen, tickers = set(), []
    for w in (args.watchlist or ["watchlists/nq100_dax40.txt", "watchlists/fox.txt"]):
        for t in parse_watchlist(w):
            if t not in seen:
                seen.add(t)
                tickers.append(t)

    rows, problems = [], []
    for t in tickers:
        claimed = prov.get(t)
        if not claimed:
            continue                      # never IB-sourced; not this check's business
        try:
            d = load_daily(t, args.start, None, "data_cache")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{t}: load_daily raised {exc}")
            continue
        if d.empty:
            problems.append(f"{t}: load_daily returned nothing")
            continue
        first, last = d.index.min().date(), d.index.max().date()
        # The tell for a Yahoo overwrite: the file starts EARLIER than IB's five
        # years, because Yahoo was asked for --start and gave it.
        looks_yahoo = str(first) < "2021-06-01"
        behind = str(last) < str(claimed)
        if looks_yahoo:
            problems.append(f"{t}: reads back Yahoo-shaped (starts {first}), "
                            f"IB wrote through {claimed}")
        if behind:
            problems.append(f"{t}: reads back {last}, IB wrote {claimed}")
        rows.append({"ticker": t, "bars": len(d), "first": first, "last": last,
                     "ib_wrote": claimed, "ok": not (looks_yahoo or behind)})

    df = pd.DataFrame(rows)
    print(f"checked {len(df)} IB-sourced symbols through load_daily(start={args.start!r})")
    if len(df):
        print(f"  reading back correctly: {int(df.ok.sum())}")
        print(f"  WRONG                 : {int((~df.ok).sum())}")
        print(f"  bar counts: min {df.bars.min()}, median {int(df.bars.median())}, "
              f"max {df.bars.max()}")
        print(f"  last sessions: {df.last.value_counts().head(4).to_dict()}")

    # The convention check. A cache can be internally consistent, current, and
    # still be adjusted rather than raw - which is invisible until the number is
    # compared against the source.
    if args.sample and len(df):
        print(f"\nre-asking IB for {args.sample} symbols and comparing EMA200 "
              f"(tolerance {args.tolerance}%):")
        try:
            from ib_async import IB, Stock
            cons = json.loads(
                Path("data_cache/ibkr_contracts.json").read_text(encoding="utf-8"))
            ib = IB()
            ib.connect("127.0.0.1", args.port, clientId=args.client_id, timeout=15)
        except Exception as exc:  # noqa: BLE001
            print(f"  cannot reach IB ({exc}) - convention NOT verified")
            problems.append("convention check skipped: IB unreachable")
            ib = None
        if ib is not None:
            for t in df.sample(min(args.sample, len(df)), random_state=0).ticker:
                c = cons.get(t)
                if not c:
                    continue
                con = Stock(conId=c["conId"], exchange="SMART", symbol=c["symbol"],
                            currency=c["currency"])
                try:
                    bars = ib.reqHistoricalData(
                        con, endDateTime="", durationStr="5 Y", barSizeSetting="1 day",
                        whatToShow="TRADES", useRTH=True, formatDate=1)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {t:10s} IB fetch failed: {str(exc)[:50]}")
                    continue
                if not bars:
                    continue
                live = pd.Series([b.close for b in bars],
                                 index=pd.to_datetime([b.date for b in bars]))
                cache = load_daily(t, args.start, None, "data_cache")["Close"]
                common = cache.index.intersection(live.index)
                if len(common) < 250:
                    print(f"  {t:10s} only {len(common)} shared bars, skipped")
                    continue
                a, b = ema(cache.loc[common], 200), ema(live.loc[common], 200)
                diff = 100 * abs(a - b) / b if b else 999
                ok = diff <= args.tolerance
                print(f"  {t:10s} cache {a:9.2f}  IB {b:9.2f}  diff {diff:5.2f}%  "
                      f"{'ok' if ok else 'MISMATCH - wrong price convention?'}")
                if not ok:
                    problems.append(f"{t}: EMA200 {a:.2f} vs IB {b:.2f} ({diff:.2f}%)")
            ib.disconnect()

    if problems:
        print(f"\n{len(problems)} PROBLEM(S):")
        for p in problems[:25]:
            print(f"  {p}")
        if len(problems) > 25:
            print(f"  ... and {len(problems) - 25} more")
        return 1
    print("\nall good: what the strategy reads is raw, current, and matches IB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
