#!/usr/bin/env python3
"""Does requiring the INDEX above its own 50-day MA filter out bad trades?

    .venv/Scripts/python.exe backtest/run_index_filter.py --watchlist watchlists/fox.txt

Runs the settled configuration once - EMA50/EMA200 daily gate, entry on the first
1h close above the previous completed daily high, stop at the 1h SuperTrend,
breakeven at 1R, half out at 1.5R - and then splits every trade it produced by
the state of that stock's own benchmark at the moment of entry. German listings
are judged against ^GDAXI, everything else against SPY.

THE TEST IS NOT "are the surviving trades good". Any filter that cuts trade count
makes the survivors look tidier, and a filter that removed trades at random would
still leave a set with roughly the baseline average. What matters is whether the
REMOVED trades are worse than the KEPT ones, so both halves are printed side by
side and the difference between them is the only number worth reading.

Several regime definitions are tested, not just the one asked about, because the
50-day line is an arbitrary place to cut and the neighbouring definitions say
whether the effect is real or an artefact of that particular length:

    sma50     index close above its 50-day simple MA        <- the one asked for
    ema50     the same with an exponential MA
    sma200    the slower, more common regime line
    sma50up   above the 50-day MA *and* that MA rising over 10 sessions
    both      above the 50-day and above the 200-day

No lookahead. The benchmark is read on its last CLOSED daily bar strictly before
the entry hour - the same rule the stock's own daily gate already uses. Reading
the index's own developing session would let a trade see a level that was not
knowable when it was taken, which is exactly the bias this filter would otherwise
be credited with avoiding.
"""

from __future__ import annotations

import argparse
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import load_daily, load_intraday, parse_watchlist
from relative_strength import RsParams, benchmark_for, load_benchmarks
from run_armed_1h import armed_windows, entry_candidates, prior_daily_high
from run_exits import atr_series, simulate
from supertrend_ai import SuperTrendParams, supertrend


def regime_frame(bench: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    """Per-day regime flags for one benchmark, on the benchmark's own calendar."""
    c = bench["Close"]
    sma_f = c.rolling(fast).mean()
    sma_s = c.rolling(slow).mean()
    ema_f = c.ewm(span=fast, adjust=False).mean()
    return pd.DataFrame({
        "sma50":   c > sma_f,
        "ema50":   c > ema_f,
        "sma200":  c > sma_s,
        "sma50up": (c > sma_f) & (sma_f > sma_f.shift(10)),
        "both":    (c > sma_f) & (c > sma_s),
    }, index=bench.index)


def regime_at(reg: pd.DataFrame, ts: pd.Timestamp) -> dict | None:
    """Flags from the last benchmark day that CLOSED before the entry hour.

    searchsorted on the normalised entry date, not on the timestamp: an entry at
    15:00 on day D must not see day D's index close, which prints hours later.
    """
    pos = reg.index.searchsorted(ts.normalize(), side="left") - 1
    if pos < 0:
        return None
    return reg.iloc[pos].to_dict()


def describe(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0, "win_%": np.nan, "avg_R": np.nan,
                "total_R": np.nan, "PF": np.nan, "worst": np.nan}
    wins, losses = t[t.R > 0].R, t[t.R <= 0].R
    return {
        "trades": len(t),
        "win_%": round(100 * len(wins) / len(t), 1),
        "avg_R": round(t.R.mean(), 3),
        "total_R": round(t.R.sum(), 1),
        "PF": round(wins.sum() / abs(losses.sum()), 2) if losses.sum() else np.inf,
        "worst": round(t.R.min(), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--ema-fast", type=int, default=50)
    ap.add_argument("--ema-slow", type=int, default=200)
    ap.add_argument("--h-factor", type=float, default=3.0)
    ap.add_argument("--index-fast", type=int, default=50, help="index MA length")
    ap.add_argument("--index-slow", type=int, default=200)
    ap.add_argument("--first-r", type=float, default=1.5)
    ap.add_argument("--min-risk-pct", type=float, default=0.3)
    ap.add_argument("--one-per-window", action="store_true",
                    help="first breakout per armed window only")
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--outdir", default="results/index_filter")
    args = ap.parse_args()

    # The winning exit scheme from the money-management sweep: SuperTrend stop,
    # breakeven at 1R, half out at 1.5R.
    sim_args = Namespace(rr=3.0, first_r=args.first_r, atr_len=14, atr_mult=2.0,
                         trail_mult=3.0, swing_n=10, stop_pct=2.0,
                         min_risk_pct=args.min_risk_pct)

    stp = SuperTrendParams(engine="classic", classic_factor=3.0, atr_length=10)
    hstp = SuperTrendParams(engine="classic", classic_factor=args.h_factor,
                            atr_length=10)

    tickers = parse_watchlist(args.watchlist)
    rsp = RsParams()
    print(f"loading {len(tickers)} symbols and their benchmarks...")
    benches = load_benchmarks(tickers, rsp, load_daily, "2020-01-01", None,
                              args.cache_dir)
    regimes = {b: regime_frame(d, args.index_fast, args.index_slow)
               for b, d in benches.items() if not d.empty}

    rows = []
    for t in tickers:
        bname = benchmark_for(t, rsp)
        reg = regimes.get(bname)
        if reg is None:
            continue
        try:
            d = load_daily(t, "2022-01-01", None, args.cache_dir)
            h = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            continue
        if d.empty or len(d) < 220 or h.empty:
            continue

        hres = supertrend(h, hstp)
        atr = atr_series(h, sim_args.atr_len)
        pdh = prior_daily_high(d, h)

        for arm, disarm, _ in armed_windows(d, stp, 200, "ema", args.ema_fast,
                                            args.ema_slow, 0.0, 0.0, False):
            end = disarm if disarm is not None else h.index.max()
            if arm < h.index.min():
                continue
            seg = h[(h.index.normalize() > arm) & (h.index <= end)]
            if seg.empty:
                continue
            cands = entry_candidates(seg.index, h, hres, "breakout", pdh)
            cursor = None
            for ts in cands:
                if cursor is not None and ts <= cursor:
                    continue
                i = h.index.get_loc(ts)
                r = simulate(i, h, hres, atr, end, sim_args, "st", "be", "partial")
                if r is None:
                    continue
                R, why, exit_ts = r
                flags = regime_at(reg, ts)
                if flags is None:
                    continue
                rows.append({"ticker": t, "bench": bname, "entry_time": ts,
                             "R": round(R, 3), "reason": why, **flags})
                cursor = exit_ts
                if args.one_per_window:
                    break

    trades = pd.DataFrame(rows)
    if trades.empty:
        print("no trades")
        return 1

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out / "trades.csv", index=False, encoding="utf-8")

    base = describe(trades)
    print(f"\n=== baseline: no index filter, {base['trades']} trades ===")
    print(pd.DataFrame([base]).to_string(index=False))

    tests = ["sma50", "ema50", "sma200", "sma50up", "both"]
    cmp_rows = []
    for k in tests:
        kept, cut = trades[trades[k]], trades[~trades[k]]
        dk, dc = describe(kept), describe(cut)
        cmp_rows.append({
            "index filter": k,
            "kept": dk["trades"], "kept_avgR": dk["avg_R"], "kept_win%": dk["win_%"],
            "kept_PF": dk["PF"], "kept_totR": dk["total_R"],
            "cut": dc["trades"], "cut_avgR": dc["avg_R"], "cut_win%": dc["win_%"],
            "cut_totR": dc["total_R"],
            # The whole question, in one column: how much better the kept trades
            # are than the ones the filter threw away.
            "edge_R": round(dk["avg_R"] - dc["avg_R"], 3)
                      if np.isfinite(dk["avg_R"]) and np.isfinite(dc["avg_R"]) else np.nan,
        })
    cmp = pd.DataFrame(cmp_rows).sort_values("edge_R", ascending=False)
    print(f"\n=== kept vs cut, by index regime at entry ===")
    print("edge_R > 0 means the filter removed trades that were worse than average.\n")
    print(cmp.to_string(index=False))
    cmp.to_csv(out / "summary.csv", index=False, encoding="utf-8")

    # Per benchmark: SPY and the DAX spent different amounts of time above their
    # own 50-day line, so a filter can look good overall purely by cutting one
    # market harder than the other.
    print(f"\n=== sma50 filter, split by benchmark ===")
    per = []
    for b in sorted(trades.bench.unique()):
        sub = trades[trades.bench == b]
        for label, part in (("kept", sub[sub.sma50]), ("cut", sub[~sub.sma50])):
            per.append({"bench": b, "half": label, **describe(part)})
    print(pd.DataFrame(per).to_string(index=False))

    print(f"\n=== how the cut trades ended, sma50 ===")
    for label, part in (("kept", trades[trades.sma50]), ("cut", trades[~trades.sma50])):
        if part.empty:
            continue
        mix = part.reason.value_counts(normalize=True).mul(100).round(1)
        print(f"  {label:5s} n={len(part):5d}  " +
              "  ".join(f"{k}={v}%" for k, v in mix.items()))

    print(f"\nwrote {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
