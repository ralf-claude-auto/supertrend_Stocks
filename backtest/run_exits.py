#!/usr/bin/env python3
"""Money-management sweep: initial stop, trailing rule and profit target.

    .venv/Scripts/python.exe backtest/run_exits.py --watchlist watchlists/fox.txt

Entry is fixed at the breakout (first 1h close above the previous completed daily
high, inside an EMA-armed window) so only the exit varies. Every scheme here is a
textbook one rather than something invented for this data:

  INITIAL STOP
    st        the 1h SuperTrend at entry - the project's existing baseline
    atr       entry - k x ATR(1h). The standard volatility stop.
    swing     the lowest low of the last n 1h bars. The classic structure stop.
    pct       a flat percentage. Crude, but it is what many desks actually use.

  TRAILING
    none      the stop never moves
    be        move to breakeven once the trade is +1R. Very widely used, and what
              the MNQ trader in unicorn_trade1 already does.
    chandelier   highest high since entry - k x ATR. Chuck LeBeau's exit, the most
              common ATR trail in use.
    swing     ratchet up to the lowest low of the last n bars, never down.

  TARGET
    rr        a fixed multiple of the initial risk
    none      no target; ride the trail until it is hit or the window disarms
    partial   take half at `first_r`, move the stop to breakeven, trail the rest.
              Scaling out is probably the single most common retail exit.

Ordering rules inside a bar, all chosen against the strategy:
  - the stop is checked BEFORE the target, since a daily-or-hourly bar does not
    say which came first and assuming the target would flatter every result
  - a gap through a level fills at the open, not at the level
  - the trail is updated at the CLOSE of a bar, after that bar's stop test, so a
    stop can never be moved using a high the trade had not yet survived
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import load_daily, load_intraday, parse_watchlist
from run_armed_1h import armed_windows, entry_candidates, prior_daily_high
from supertrend_ai import SuperTrendParams, supertrend


def atr_series(h: pd.DataFrame, length: int) -> pd.Series:
    pc = h["Close"].shift(1)
    tr = pd.concat([h["High"] - h["Low"], (h["High"] - pc).abs(),
                    (h["Low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def initial_stop(kind, entry, i, h, hres, atr, args):
    if kind == "st":
        return float(hres.trailing_stop.iloc[i])
    if kind == "atr":
        a = float(atr.iloc[i])
        return entry - args.atr_mult * a if np.isfinite(a) else np.nan
    if kind == "swing":
        lo = h["Low"].iloc[max(0, i - args.swing_n + 1): i + 1].min()
        return float(lo)
    if kind == "pct":
        return entry * (1.0 - args.stop_pct / 100.0)
    raise ValueError(f"unknown stop {kind!r}")


def simulate(entry_i, h, hres, atr, end_ts, args, stop_kind, trail_kind, target_kind):
    """One trade: returns (total R, reason, exit timestamp), or None if untradeable.

    The exit timestamp matters - the caller uses it to advance past the trade so
    the same armed window cannot open a second overlapping position in the same
    symbol."""
    entry = float(h["Close"].iloc[entry_i])
    stop = initial_stop(stop_kind, entry, entry_i, h, hres, atr, args)
    if not np.isfinite(stop) or stop >= entry:
        return None
    risk = entry - stop
    if 100.0 * risk / entry < args.min_risk_pct:
        return None
    target = entry + args.rr * risk if target_kind == "rr" else (
        entry + args.first_r * risk if target_kind == "partial" else np.inf)

    fwd = h.iloc[entry_i + 1:]
    fwd = fwd[fwd.index <= end_ts]
    if fwd.empty:
        return None

    peak = entry
    half_done = False
    realised = 0.0          # R already banked from the partial
    size = 1.0              # fraction of the position still open

    for k in range(len(fwd)):
        o = float(fwd["Open"].iloc[k]); hi = float(fwd["High"].iloc[k])
        lo = float(fwd["Low"].iloc[k])

        # 1) stop first - the bar does not say which came first
        if lo <= stop:
            px = o if o <= stop else stop
            return realised + size * (px - entry) / risk, "stop", fwd.index[k]

        # 2) then the target
        if hi >= target:
            px = o if o >= target else target
            if target_kind == "rr":
                return realised + size * (px - entry) / risk, "target", fwd.index[k]
            if not half_done:                       # partial: bank half, ride on
                realised += 0.5 * (px - entry) / risk
                size, half_done = 0.5, True
                stop = max(stop, entry)             # rest goes risk-free
                target = np.inf

        # 3) trail on the CLOSE, after this bar's stop test
        peak = max(peak, hi)
        a = float(atr.iloc[entry_i + 1 + k]) if entry_i + 1 + k < len(atr) else np.nan
        if trail_kind == "be" and peak >= entry + risk:
            stop = max(stop, entry)
        elif trail_kind == "chandelier" and np.isfinite(a):
            stop = max(stop, peak - args.trail_mult * a)
        elif trail_kind == "swing":
            j = entry_i + 1 + k
            lows = h["Low"].iloc[max(0, j - args.swing_n + 1): j + 1]
            stop = max(stop, float(lows.min()))

    px = float(fwd["Close"].iloc[-1])
    return realised + size * (px - entry) / risk, "disarm", fwd.index[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--rr", type=float, default=3.0)
    ap.add_argument("--first-r", type=float, default=1.5, help="partial: bank half here")
    ap.add_argument("--atr-len", type=int, default=14)
    ap.add_argument("--atr-mult", type=float, default=2.0)
    ap.add_argument("--trail-mult", type=float, default=3.0)
    ap.add_argument("--swing-n", type=int, default=10)
    ap.add_argument("--stop-pct", type=float, default=2.0)
    ap.add_argument("--h-factor", type=float, default=3.0)
    ap.add_argument("--ema-fast", type=int, default=50)
    ap.add_argument("--ema-slow", type=int, default=200)
    ap.add_argument("--commission", type=float, default=0.1)
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--one-per-window", action="store_true",
                    help="take only the FIRST breakout per armed window. Without "
                         "this a tighter stop exits sooner and takes more re-entries, "
                         "so schemes see different trades and average R is not "
                         "comparable between them")
    ap.add_argument("--min-risk-pct", type=float, default=0.3,
                    help="skip entries whose initial stop is nearer than this %% of "
                         "price. R divides by that distance, so a stop a whisker "
                         "away produces meaningless 200R outliers")
    ap.add_argument("--outdir", default="results/exits")
    args = ap.parse_args()

    stp = SuperTrendParams(engine="classic", classic_factor=3.0, atr_length=10)
    hstp = SuperTrendParams(engine="classic", classic_factor=args.h_factor, atr_length=10)

    # Textbook combinations, not the full cross product: pairing a percentage stop
    # with a chandelier trail, say, tests nothing anyone runs.
    COMBOS = [
        ("st       | none       | 3R",       "st",    "none",       "rr"),
        ("st       | breakeven  | 3R",       "st",    "be",         "rr"),
        ("st       | chandelier | none",     "st",    "chandelier", "none"),
        ("atr2     | none       | 3R",       "atr",   "none",       "rr"),
        ("atr2     | breakeven  | 3R",       "atr",   "be",         "rr"),
        ("atr2     | chandelier | none",     "atr",   "chandelier", "none"),
        ("atr2     | chandelier | 3R",       "atr",   "chandelier", "rr"),
        ("swing10  | none       | 3R",       "swing", "none",       "rr"),
        ("swing10  | swing      | none",     "swing", "swing",      "none"),
        ("swing10  | breakeven  | 3R",       "swing", "be",         "rr"),
        ("pct2     | none       | 3R",       "pct",   "none",       "rr"),
        ("pct2     | breakeven  | 3R",       "pct",   "be",         "rr"),
        ("atr2     | chandelier | partial",  "atr",   "chandelier", "partial"),
        ("swing10  | swing      | partial",  "swing", "swing",      "partial"),
        ("st       | breakeven  | partial",  "st",    "be",         "partial"),
    ]

    tickers = parse_watchlist(args.watchlist)
    print(f"loading {len(tickers)} symbols...")
    results = {c[0]: [] for c in COMBOS}
    n_entries = 0

    for t in tickers:
        try:
            d = load_daily(t, "2022-01-01", None, args.cache_dir)
            h = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            continue
        if d.empty or len(d) < 220 or h.empty:
            continue
        hres = supertrend(h, hstp)
        atr = atr_series(h, args.atr_len)
        pdh = prior_daily_high(d, h)

        for arm, disarm, _ in armed_windows(d, stp, 200, "ema",
                                            args.ema_fast, args.ema_slow, 0.0, 0.0, False):
            end = disarm if disarm is not None else h.index.max()
            if arm < h.index.min():
                continue
            seg = h[(h.index.normalize() > arm) & (h.index <= end)]
            if seg.empty:
                continue
            cands = entry_candidates(seg.index, h, hres, "breakout", pdh)
            if len(cands) == 0:
                continue
            for label, sk, tk, gk in COMBOS:
                cursor = None
                for ts in cands:
                    if cursor is not None and ts <= cursor:
                        continue
                    i = h.index.get_loc(ts)
                    r = simulate(i, h, hres, atr, end, args, sk, tk, gk)
                    if r is None:
                        continue
                    R, why, exit_ts = r
                    results[label].append({"ticker": t, "entry_time": ts,
                                           "R": round(R, 3), "reason": why})
                    if label == COMBOS[0][0]:
                        n_entries += 1
                    cursor = exit_ts   # no overlapping positions in one symbol
                    if args.one_per_window:
                        break

    rows = []
    out = Path(args.outdir); out.mkdir(parents=True, exist_ok=True)
    fee = 2 * args.commission / 100.0
    for label, *_ in COMBOS:
        t = pd.DataFrame(results[label])
        if t.empty:
            continue
        # Full label in the filename: keying on the stop alone made every "st"
        # scheme write to st_<n>.csv and silently overwrite the previous one.
        slug = "_".join(x.strip() for x in label.split("|")).replace(" ", "")
        t.to_csv(out / f"trades_{slug}.csv", index=False, encoding="utf-8")
        wins, losses = t[t.R > 0].R, t[t.R <= 0].R
        rows.append({
            "stop | trail | target": label,
            "trades": len(t),
            "win_%": round(100 * len(wins) / len(t), 1),
            "avg_R": round(t.R.mean(), 3),
            "total_R": round(t.R.sum(), 1),
            "PF": round(wins.sum() / abs(losses.sum()), 2) if losses.sum() else np.inf,
            "med_R": round(t.R.median(), 2),
            "best": round(t.R.max(), 1),
            "worst": round(t.R.min(), 1),
            "stop_%": round(100 * (t.reason == "stop").mean(), 1),
            "target_%": round(100 * (t.reason == "target").mean(), 1),
            "disarm_%": round(100 * (t.reason == "disarm").mean(), 1),
        })
    res = pd.DataFrame(rows).sort_values("avg_R", ascending=False)
    print(f"\n=== breakout entry, {len(res)} exit schemes, "
          f"{n_entries} entries each ===\n")
    print(res.to_string(index=False))
    res.to_csv(out / "summary.csv", index=False, encoding="utf-8")
    print(f"\nwrote {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
