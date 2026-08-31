#!/usr/bin/env python3
"""Rebuild the daily long / signal / short lists for every past session.

    .venv/Scripts/python.exe backtest/backfill_scans.py --days 90

Writes, under scans/history/:
    <date>.csv     the full classified list for that session
    _signals.csv   every NEW SIGNAL across the window - the input for run_rr.py
    _summary.md    signals per day, and per symbol, over the window

Why this is not just scan_daily.py in a loop: every series used here is CAUSAL —
the classic SuperTrend is computed forward bar by bar, the MA is a trailing
window, and relative strength is a trailing return difference. Each bar's value
therefore depends only on bars at or before it, so the whole history can be
computed ONCE per symbol and then sliced at each past date without leaking
future information. Re-running the scanner per day would download the same data
90 times to reach the identical answer.

The one genuinely cross-sectional figure, the relative-strength rank, is computed
within each day across the symbols that had a bar that day.
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
from supertrend_ai import SuperTrendParams, supertrend

WARMUP_DAYS = 900


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--days", type=int, default=90, help="calendar days to cover")
    ap.add_argument("--engine", choices=["adaptive", "classic"], default="classic")
    ap.add_argument("--classic-factor", type=float, default=3.0)
    ap.add_argument("--atr-length", type=int, default=10)
    ap.add_argument("--ma-length", type=int, default=200)
    ap.add_argument("--rs-roc-length", type=int, default=60)
    ap.add_argument("--benchmark-de", default="^GDAXI")
    ap.add_argument("--benchmark-us", default="SPY")
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--outdir", default="scans/history")
    ap.add_argument("--include-today", action="store_true",
                    help="include a bar dated today (partial while a market is open)")
    args = ap.parse_args()

    tickers = parse_watchlist(args.watchlist)
    rsp = RsParams(mode="roc_diff", roc_length=args.rs_roc_length,
                   benchmark_de=args.benchmark_de, benchmark_us=args.benchmark_us)
    stp = SuperTrendParams(engine=args.engine, atr_length=args.atr_length,
                           classic_factor=args.classic_factor)

    start = (pd.Timestamp(date.today()) - pd.Timedelta(days=WARMUP_DAYS + args.days)
             ).strftime("%Y-%m-%d")
    window_start = pd.Timestamp(date.today()) - pd.Timedelta(days=args.days)

    benches = load_benchmarks(tickers, rsp, load_daily, start, None, args.cache_dir)

    frames, skipped = [], []
    for t in tickers:
        try:
            df = load_daily(t, start, None, args.cache_dir)
        except Exception as exc:  # noqa: BLE001
            skipped.append((t, str(exc)[:60]))
            continue
        if df.empty or len(df) < args.ma_length + 20:
            skipped.append((t, f"only {len(df)} bars"))
            continue
        bench = benches.get(benchmark_for(t, rsp))
        if bench is None or bench.empty:
            skipped.append((t, "benchmark unavailable"))
            continue
        if not args.include_today:
            df = df[df.index.date < date.today()]
            if len(df) < args.ma_length + 20:
                skipped.append((t, "no completed bars"))
                continue

        res = supertrend(df, stp)
        ma = df["Close"].rolling(args.ma_length).mean()
        rs = rs_frame(df, bench, rsp)
        above = df["Close"] > ma

        f = pd.DataFrame({
            "date": df.index,
            "ticker": t,
            "bench": benchmark_for(t, rsp),
            "close": df["Close"].round(4),
            "open": df["Open"].round(4) if "Open" in df else np.nan,
            "high": df["High"].round(4),
            "low": df["Low"].round(4),
            "ma": ma.round(4),
            "stop": res.trailing_stop.round(4),
            "trend": np.where(res.trend == 1, "up", "down"),
            "new_up": res.buy.to_numpy(),
            "new_down": res.sell.to_numpy(),
            "above_ma": above.to_numpy(),
            "rs_diff": rs["rs_diff"].round(2).to_numpy(),
            "strength": res.signal_strength.to_numpy(),
        })
        frames.append(f[f["date"] >= window_start])

    if not frames:
        print("nothing to backfill", file=sys.stderr)
        return 1

    d = pd.concat(frames, ignore_index=True)
    # Classification, matching scan_daily.py exactly.
    d["klass"] = np.where(d.new_up & d.above_ma, "SIGNAL",
                 np.where((d.trend == "up") & d.above_ma, "LONG", "SHORT"))
    # Relative-strength rank within each session.
    d["rs_rank"] = d.groupby("date")["rs_diff"].rank(pct=True).mul(100).round(0)
    d = d.sort_values(["date", "rs_diff"], ascending=[True, False])

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.csv"):
        old.unlink()

    cols = ["ticker", "bench", "klass", "close", "ma", "stop", "trend",
            "rs_diff", "rs_rank", "strength"]
    sessions = sorted(d["date"].unique())
    for s in sessions:
        day = d[d["date"] == s]
        day[cols].to_csv(out / f"{pd.Timestamp(s).date()}.csv",
                         index=False, encoding="utf-8")

    sig = d[d.klass == "SIGNAL"].copy()
    sig[["date", "ticker", "bench", "close", "ma", "stop", "rs_diff", "rs_rank",
         "strength"]].to_csv(out / "_signals.csv", index=False, encoding="utf-8")

    per_day = d.groupby("date")["klass"].value_counts().unstack(fill_value=0)
    for c in ("SIGNAL", "LONG", "SHORT"):
        if c not in per_day:
            per_day[c] = 0
    per_sym = sig.groupby("ticker").size().sort_values(ascending=False)

    lines = [
        f"# Daily lists — last {args.days} days",
        "",
        f"- Watchlist `{args.watchlist}`, {d.ticker.nunique()} symbols, "
        f"{len(sessions)} sessions from {pd.Timestamp(sessions[0]).date()} "
        f"to {pd.Timestamp(sessions[-1]).date()}",
        f"- Signal: {args.engine}"
        + (f" factor {args.classic_factor}" if args.engine == "classic" else "")
        + f", ATR {args.atr_length}, trend SMA{args.ma_length}",
        f"- SIGNAL = SuperTrend flipped bullish that session with close above the MA; "
        f"LONG = already bullish and above the MA; SHORT = everything else",
        f"- **{len(sig)} signals** over the window, {len(sig)/max(len(sessions),1):.1f} per session",
        "",
        "## Signals per session",
        "",
        "| date | SIGNAL | LONG | SHORT |",
        "| ---- | ------ | ---- | ----- |",
    ]
    for s, r in per_day.iterrows():
        lines.append(f"| {pd.Timestamp(s).date()} | {int(r['SIGNAL'])} | "
                     f"{int(r['LONG'])} | {int(r['SHORT'])} |")
    lines += ["", "## Signals per symbol", "",
              ", ".join(f"`{k}` {v}" for k, v in per_sym.items()) or "_none_", ""]
    if skipped:
        lines += ["## Skipped", ""] + [f"- `{t}` — {w}" for t, w in skipped] + [""]
    (out / "_summary.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"{d.ticker.nunique()} symbols x {len(sessions)} sessions "
          f"({pd.Timestamp(sessions[0]).date()} -> {pd.Timestamp(sessions[-1]).date()})")
    print(f"  SIGNAL {int(per_day['SIGNAL'].sum()):5d}   "
          f"LONG {int(per_day['LONG'].sum()):6d}   SHORT {int(per_day['SHORT'].sum()):6d}")
    print(f"  {len(sig)} signals, {len(sig)/max(len(sessions),1):.1f} per session, "
          f"across {sig.ticker.nunique()} symbols")
    print(f"\nwrote {len(sessions)} day files + _signals.csv + _summary.md to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
