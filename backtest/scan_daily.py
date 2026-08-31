#!/usr/bin/env python3
"""Daily scan: new signals, uptrending and downtrending stocks, ranked by
relative strength against the DAX (German listings) or SPY (US listings).

    .venv/Scripts/python.exe backtest/scan_daily.py --watchlist watchlists/fox.txt

Lists produced, each sorted by relative strength, strongest first:

  NEW SIGNAL     SuperTrend flipped bullish on the latest bar with price above
                 the trend MA — today's fresh entries.
  NEW EXIT       Flipped bearish on the latest bar — today's exits.
  UPTRENDING     Already in a bullish SuperTrend above the MA. Positions to hold.
  DOWNTRENDING   Bearish SuperTrend, or price below the MA.

Relative strength is used here to RANK and CLASSIFY, not to gate entries. Tested
as an entry filter it reduced the number of symbols left in profit (110-symbol
test, 2018+: 74 without it against 70/62/56 with it) — see FINDINGS.md. As a
sort key for deciding what to look at first, it is exactly the right tool: the
list is benchmark-relative, so a German and a US name can be compared directly.

Data is only as fresh as the last daily close Yahoo has published, which is
printed in the header. Run it after the close, not intraday.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily, parse_watchlist
from relative_strength import RsParams, benchmark_for, load_benchmarks, rs_frame
from run_backtest import to_markdown_table
from supertrend_ai import SuperTrendParams, supertrend

WARMUP_DAYS = 900  # enough for MA200 plus the RS lookback


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--as-of", default=None,
                    help="run the scan as if it were this date (YYYY-MM-DD)")
    ap.add_argument("--engine", choices=["adaptive", "classic"], default="classic")
    ap.add_argument("--classic-factor", type=float, default=3.0)
    ap.add_argument("--atr-length", type=int, default=10)
    ap.add_argument("--ma-length", type=int, default=200)
    ap.add_argument("--rs-roc-length", type=int, default=60,
                    help="lookback for the relative-strength ranking")
    ap.add_argument("--benchmark-de", default="^GDAXI")
    ap.add_argument("--benchmark-us", default="SPY")
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--refresh", action="store_true",
                    help="force a refetch of every symbol, not just the stale ones")
    ap.add_argument("--include-today", action="store_true",
                    help="include a bar dated today. OFF by default: while a market "
                         "is open Yahoo returns a PARTIAL bar for today, and a "
                         "SuperTrend flip computed on it can vanish by the close. "
                         "Use only after every market in the list has closed.")
    ap.add_argument("--outdir", default="scans")
    args = ap.parse_args()

    tickers = parse_watchlist(args.watchlist)
    rsp = RsParams(mode="roc_diff", roc_length=args.rs_roc_length,
                   benchmark_de=args.benchmark_de, benchmark_us=args.benchmark_us)
    stp = SuperTrendParams(engine=args.engine, atr_length=args.atr_length,
                           classic_factor=args.classic_factor)

    end = args.as_of
    start = (pd.Timestamp(args.as_of or date.today()) -
             pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")

    # Fetch the benchmarks first and unconditionally: their newest bar defines what
    # "current" means, and any symbol whose cache ends earlier is refetched. Without
    # this the scan would keep reporting last week's close, since the cache has no
    # notion of age.
    for name in {benchmark_for(t, rsp) for t in tickers}:  # noqa: B020
        (Path(args.cache_dir) / f"{name.replace('^', '_')}.csv").unlink(missing_ok=True)
    benches = load_benchmarks(tickers, rsp, load_daily, start, end, args.cache_dir)

    fresh = max((b.index.max() for b in benches.values() if not b.empty), default=None)
    if fresh is not None:
        print(f"benchmarks current to {fresh.date()} — refetching any symbol older than that")
    stale_after = None if args.refresh else fresh

    rows, skipped = [], []
    for t in tickers:
        try:
            df = load_daily(t, start, end, args.cache_dir,
                            stale_after=None if args.refresh else stale_after)
        except Exception as exc:  # noqa: BLE001
            skipped.append((t, str(exc)[:60]))
            continue
        if df.empty or len(df) < args.ma_length + 20:
            skipped.append((t, f"only {len(df)} bars"))
            continue
        bench_name = benchmark_for(t, rsp)
        bench = benches.get(bench_name)
        if bench is None or bench.empty:
            skipped.append((t, f"benchmark {bench_name} unavailable"))
            continue

        if not args.include_today:
            # Drop a bar dated today: while the session is open it is incomplete,
            # so any signal from it can reverse before the close.
            df = df[df.index.date < date.today()]
            if df.empty or len(df) < args.ma_length + 20:
                skipped.append((t, "no completed bars"))
                continue

        res = supertrend(df, stp)
        ma = df["Close"].rolling(args.ma_length).mean()
        rs = rs_frame(df, bench, rsp)

        i = -1
        close = float(df["Close"].iloc[i])
        os_now = int(res.trend.iloc[i])
        # Bars since the most recent flip, for "how mature is this trend".
        flips = res.trend.ne(res.trend.shift(1))
        flips.iloc[0] = True
        days_in = int(len(res.trend) - 1 - np.max(np.flatnonzero(flips.to_numpy())))

        stop = float(res.trailing_stop.iloc[i])
        rows.append({
            "ticker": t,
            "bench": bench_name,
            "close": round(close, 2),
            "rs_diff": round(float(rs["rs_diff"].iloc[i]), 1)
            if pd.notna(rs["rs_diff"].iloc[i]) else np.nan,
            "trend": "up" if os_now == 1 else "down",
            "days_in_trend": days_in,
            "vs_ma_pct": round(100 * (close / float(ma.iloc[i]) - 1), 1)
            if pd.notna(ma.iloc[i]) else np.nan,
            "stop": round(stop, 2) if pd.notna(stop) else np.nan,
            "stop_dist_pct": round(100 * (close - stop) / close, 1)
            if pd.notna(stop) else np.nan,
            "strength": int(res.signal_strength.iloc[i]),
            "_new_up": bool(res.buy.iloc[i]),
            "_new_down": bool(res.sell.iloc[i]),
            "_above_ma": bool(pd.notna(ma.iloc[i]) and close > float(ma.iloc[i])),
            "_last_bar": df.index[i].date(),
        })

    if not rows:
        print("No symbols could be scanned.", file=sys.stderr)
        return 1

    d = pd.DataFrame(rows)
    # Rank on benchmark-relative performance, so German and US names compare.
    d["rs_rank"] = d["rs_diff"].rank(pct=True, ascending=True).mul(100).round(0)
    d = d.sort_values("rs_diff", ascending=False)

    # Symbols do not all end on the same bar: German listings often lag the US
    # ones by a day on Yahoo. Dating the whole scan by the freshest symbol hides
    # that, so carry each row's own last bar and flag the ones behind. This has to
    # happen BEFORE the lists are sliced off, or the slices lack the columns.
    d["last_bar"] = d["_last_bar"]
    asof = d["_last_bar"].max()
    d["stale"] = np.where(d["_last_bar"] < asof, "!", "")
    cols = ["ticker", "bench", "last_bar", "stale", "close", "rs_diff", "rs_rank",
            "days_in_trend", "vs_ma_pct", "stop", "stop_dist_pct", "strength"]

    new_sig = d[d._new_up & d._above_ma]
    new_exit = d[d._new_down]
    uptrend = d[(d.trend == "up") & d._above_ma & ~d._new_up]
    downtrend = d[(d.trend == "down") | ~d._above_ma]

    def section(title: str, sub: pd.DataFrame, note: str = "") -> list[str]:
        out = [f"## {title} — {len(sub)}", ""]
        if note:
            out += [note, ""]
        out += [to_markdown_table(sub[cols]) if len(sub) else "_none_", ""]
        return out

    lines = [
        f"# Daily scan — {asof}",
        "",
        f"- Watchlist: `{args.watchlist}` — {len(d)} symbols scanned, {len(skipped)} skipped",
        f"- Signal: {args.engine} SuperTrend"
        + (f" factor {args.classic_factor}" if args.engine == "classic" else "")
        + f", ATR {args.atr_length}, trend MA{args.ma_length}",
        f"- Relative strength: {args.rs_roc_length}-day return minus the benchmark's "
        f"({args.benchmark_de} for German listings, {args.benchmark_us} for US), in "
        f"percentage points. `rs_rank` is the percentile within this scan.",
        f"- Latest close in the data: **{asof}**. Yahoo publishes end-of-day, so run "
        f"this after the close; intraday it repeats yesterday.",
        f"- Rows marked `!` in the `stale` column end on an EARLIER bar than {asof} "
        f"(German listings often lag the US ones by a day on Yahoo) - their signal "
        f"is that bar's, not today's.",
        "",
        "Every list is sorted by relative strength, strongest first.",
        "",
    ]
    lines += section("NEW SIGNAL — flipped bullish on the latest bar, above the MA", new_sig)
    lines += section("NEW EXIT — flipped bearish on the latest bar", new_exit)
    lines += section("UPTRENDING — holding a bullish SuperTrend above the MA", uptrend)
    lines += section("DOWNTRENDING — bearish SuperTrend, or below the MA", downtrend)
    if skipped:
        lines += ["## Skipped", ""] + [f"- `{t}` — {why}" for t, why in skipped] + [""]

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{asof}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    d[cols + ["trend"]].to_csv(out / f"{asof}.csv", index=False, encoding="utf-8")

    print(f"\n=== DAILY SCAN {asof} — {len(d)} symbols ===\n")
    for title, sub in (("NEW SIGNAL", new_sig), ("NEW EXIT", new_exit)):
        print(f"{title} ({len(sub)}):")
        print(sub[cols].to_string(index=False) if len(sub) else "  none")
        print()
    print(f"UPTRENDING ({len(uptrend)})  top 15 by relative strength:")
    print(uptrend[cols].head(15).to_string(index=False))
    print(f"\nDOWNTRENDING ({len(downtrend)})  weakest 15:")
    print(downtrend[cols].tail(15).to_string(index=False))
    print(f"\nWrote {md} and {out / f'{asof}.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
