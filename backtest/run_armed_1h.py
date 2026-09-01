#!/usr/bin/env python3
"""Daily signal ARMS a stock; the 1h SuperTrend executes entries while it stays armed.

    .venv/Scripts/python.exe backtest/run_armed_1h.py --rr 3

The daily chart decides WHETHER a stock is tradeable, the hourly chart decides
WHEN to be in it:

  ARM      a daily SIGNAL - the daily SuperTrend flips bullish with close above
           the trend MA.
  STAY     armed for as long as BOTH hold: the daily SuperTrend is still bullish
           AND close is still above the MA.
  DISARM   the first daily bar where the SuperTrend breaks or close closes below
           the MA. Any open position is closed on that bar.
  ENTER    each bullish flip of the SAME SuperTrend computed on 1h bars, while
           armed. Not just the day after the signal - the window can span weeks,
           and by default a new flip after an exit re-enters.
  EXIT     target, stop, or disarm, whichever comes first.

This differs from run_rr_1h.py in two ways that matter: the entry trigger is the
SuperTrend itself rather than an MA cross, and the opportunity does not expire
after a fixed window - a stock that never sets up in the first few days can still
be taken later while its daily trend holds.

--stop hourly sizes risk from the 1h SuperTrend at entry, which is far tighter
than the daily line and so changes what a given R is worth; --stop daily keeps the
daily line, matching the other backtests. Both are reported.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily, load_intraday, parse_watchlist
from relative_strength import (RsParams, benchmark_for, load_benchmarks,
                               rs_frame)
from run_rr import summarise
from supertrend_ai import SuperTrendParams, supertrend


def armed_windows(df: pd.DataFrame, stp: SuperTrendParams, ma_len: int,
                  mode: str = "supertrend", ema_fast: int = 50, ema_slow: int = 200,
                  buffer_pct: float = 0.5, entry_buffer_pct: float = 0.5,
                  require_stack: bool = False):
    """(arm_date, disarm_date, daily_stop) per armed window.

    mode="supertrend"  the daily SuperTrend flips bullish while close > SMA(ma_len).
                       Arming needs a FLIP, so a stock already trending does not
                       re-arm until it breaks and turns again.
    mode="ema"         close above both EMAs, and entry_buffer_pct clear of the
                       fast one. The window is HELD until close falls buffer_pct
                       below either average. Asymmetric on purpose - see below.

    Either way the window ends at the first bar where its condition fails, and the
    daily SuperTrend value at the arm bar is returned for the --stop daily option.
    """
    res = supertrend(df, stp)
    close = df["Close"]

    if mode == "ema":
        ef = close.ewm(span=ema_fast, adjust=False, min_periods=ema_fast).mean()
        es = close.ewm(span=ema_slow, adjust=False, min_periods=ema_slow).mean()
        # HYSTERESIS, asymmetric on both sides.
        #
        # ENTRY needs close a clear entry_buffer_pct ABOVE the fast EMA, not merely
        # touching it, so a bar that grazes the average does not arm the stock.
        # HOLDING tolerates a dip of buffer_pct BELOW either average before
        # disarming. Without that the gate flickers - at buffer 0 the median armed
        # window was six days against 33 for the SuperTrend gate.
        #
        # The two bands together leave a dead zone: once price falls through the
        # lower band it cannot re-arm until it clears the upper one. That costs
        # armed time, which is why a wider buffer reduces total return even as it
        # cuts churn - 1% buffer measured 18,040 armed days against 22,507 at zero.
        #
        # `stacked` (fast EMA above slow) is available but OFF by default: tested at
        # 1101.6R -> 1011.0R total with identical average R, so it removed ~8% of
        # trades without improving the rest.
        lo = 1.0 - buffer_pct / 100.0
        hi = 1.0 + entry_buffer_pct / 100.0
        stacked = (ef > es) if require_stack else pd.Series(True, index=close.index)
        arm_cond  = (close > ef * hi) & (close > es) & stacked
        hold_cond = (close > ef * lo) & (close > es * lo) & stacked
        ok = hold_cond
        starts = arm_cond & ~hold_cond.shift(1, fill_value=False)
    elif mode == "supertrend":
        ma = close.rolling(ma_len).mean()
        ok = (res.trend == 1) & (close > ma)
        starts = pd.Series(res.buy.to_numpy() & ok.to_numpy(), index=df.index)
    else:
        raise ValueError(f"unknown arm mode {mode!r} (supertrend | ema)")

    out = []
    consumed_to = -1
    for i in np.flatnonzero(starts.to_numpy()):
        # With hysteresis the arm condition can go false and true again while the
        # hold condition never lapses. Skipping starts inside an open window stops
        # that producing overlapping windows and double entries.
        if i <= consumed_to:
            continue
        j = i + 1
        while j < len(df) and bool(ok.iloc[j]):
            j += 1
        consumed_to = j
        out.append((df.index[i], df.index[j] if j < len(df) else None,
                    float(res.trailing_stop.iloc[i])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--rr", type=float, default=3.0)
    ap.add_argument("--stop", choices=["daily", "hourly", "both"], default="both")
    ap.add_argument("--classic-factor", type=float, default=3.0)
    ap.add_argument("--atr-length", type=int, default=10)
    ap.add_argument("--ma-length", type=int, default=200)
    ap.add_argument("--arm-mode", choices=["supertrend", "ema"], default="supertrend",
                    help="supertrend: daily ST flip above the SMA. "
                         "ema: close above BOTH EMAs, no SuperTrend involved")
    ap.add_argument("--ema-fast", type=int, default=50)
    ap.add_argument("--ema-slow", type=int, default=200)
    ap.add_argument("--ema-buffer", type=float, default=0.5,
                    help="stay armed until close is this %% BELOW either EMA "
                         "(0 = disarm on the first tick under)")
    ap.add_argument("--ema-entry-buffer", type=float, default=0.5,
                    help="arm only when close is this %% ABOVE the fast EMA")
    ap.add_argument("--ema-stacked", action="store_true",
                    help="also require the fast EMA above the slow (tested neutral)")
    ap.add_argument("--one-per-window", action="store_true",
                    help="take only the first hourly entry per armed window")
    ap.add_argument("--commission", type=float, default=0.1)
    ap.add_argument("--risk-frac", type=float, default=0.01)
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--outdir", default="results/armed_1h")
    args = ap.parse_args()

    stp = SuperTrendParams(engine="classic", classic_factor=args.classic_factor,
                           atr_length=args.atr_length)
    tickers = parse_watchlist(args.watchlist)
    fee = args.commission / 100.0
    modes = ["daily", "hourly"] if args.stop == "both" else [args.stop]

    rsp = RsParams(mode="roc_diff", roc_length=60)
    benches = load_benchmarks(tickers, rsp, load_daily, "2022-01-01", None,
                              args.cache_dir)

    print(f"loading {len(tickers)} symbols (daily + 1h)...")
    per_mode = {m: [] for m in modes}
    windows_total = armed_no_entry = 0
    rs_by_symbol = {}

    for t in tickers:
        try:
            d = load_daily(t, "2022-01-01", None, args.cache_dir)
            h = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            continue
        if d.empty or len(d) < args.ma_length + 20 or h.empty:
            continue

        bench = benches.get(benchmark_for(t, rsp))
        if bench is not None and not bench.empty:
            rs_by_symbol[t] = rs_frame(d, bench, rsp)["rs_diff"]

        hres = supertrend(h, stp)          # the SAME SuperTrend, on 1h bars
        hflip = hres.buy.to_numpy()
        wins = armed_windows(d, stp, args.ma_length, args.arm_mode,
                             args.ema_fast, args.ema_slow, args.ema_buffer,
                             args.ema_entry_buffer, args.ema_stacked)

        for arm, disarm, dstop in wins:
            # Only windows the hourly history actually covers can be tested.
            if arm < h.index.min():
                continue
            windows_total += 1
            end = disarm if disarm is not None else h.index.max()
            # From the day AFTER the arm, never the arming session itself. `arm` is
            # a daily bar stamped at midnight, so `h.index > arm` would admit that
            # day's own hourly bars - hours before its close confirmed the daily
            # signal. That is lookahead, and it flattered the result badly: those
            # entries averaged +1.05R against +0.50R for the rest, 14% of all profit
            # from 6.9% of trades.
            seg = h[(h.index.normalize() > arm) & (h.index <= end)]
            if seg.empty:
                continue
            flips = seg.index[hflip[h.index.searchsorted(seg.index)]]
            if len(flips) == 0:
                armed_no_entry += 1
                continue

            for mode in modes:
                taken = 0
                cursor = seg.index[0]
                for ft in flips:
                    if ft < cursor:
                        continue
                    entry = float(h.loc[ft, "Close"])
                    stop = dstop if mode == "daily" else float(hres.trailing_stop.loc[ft])
                    if not np.isfinite(stop) or entry <= stop:
                        continue
                    risk = entry - stop
                    target = entry + args.rr * risk
                    fwd = h[(h.index > ft) & (h.index <= end)]
                    xp = xt = None
                    reason = "disarm"
                    for ts, b in fwd.iterrows():
                        lo, hi, o = float(b["Low"]), float(b["High"]), float(b["Open"])
                        if lo <= stop:
                            xp, xt, reason = (o if o <= stop else stop), ts, "stop"
                            break
                        if hi >= target:
                            xp, xt, reason = (o if o >= target else target), ts, "target"
                            break
                    if xp is None:
                        if fwd.empty:
                            continue
                        xp, xt = float(fwd.iloc[-1]["Close"]), fwd.index[-1]
                        reason = "disarm" if disarm is not None else "still open"
                    per_mode[mode].append({
                        "ticker": t, "arm_date": arm.date(),
                        "entry_date": ft, "entry": round(entry, 4),
                        "stop": round(stop, 4), "target": round(target, 4),
                        "exit_date": xt, "exit": round(xp, 4), "reason": reason,
                        "bars_held": int(fwd.index.get_loc(xt)) + 1,
                        "risk_pct": round(100 * risk / entry, 2),
                        "R": round((xp - entry) / risk, 3),
                        "return_pct": round((xp / entry - 1) * 100 - 2 * fee * 100, 2),
                    })
                    taken += 1
                    cursor = xt
                    if args.one_per_window:
                        break

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for mode in modes:
        t = pd.DataFrame(per_mode[mode])
        t.to_csv(out / f"trades_stop_{mode}.csv", index=False, encoding="utf-8")
        rows.append({**summarise(t, f"1h ST entry, {mode} stop", args.risk_frac),
                     "med_risk_%": round(t.risk_pct.median(), 2) if len(t) else np.nan})
    s = pd.DataFrame(rows)

    print(f"\narmed windows covered by 1h data: {windows_total}   "
          f"of which never produced an hourly entry: {armed_no_entry} "
          f"({100*armed_no_entry/max(windows_total,1):.0f}%)")
    print(f"\n=== {args.rr:g}:1 exit — daily arms, 1h SuperTrend executes ===\n")
    print(s.to_string(index=False))
    s.to_csv(out / "summary.csv", index=False, encoding="utf-8")

    for mode in modes:
        t = pd.DataFrame(per_mode[mode])
        if len(t):
            print(f"\n--- {mode} stop: exit reasons ---")
            print(t.reason.value_counts().to_string())

    # A portfolio can only hold so many positions at once. The figures above assume
    # every signal is funded the instant it fires, which at a ~3% stop and 1% risk
    # is ~30% of capital per position - twenty of those is six times the account.
    # Re-run the same trades through a slot limit so the result describes something
    # an account could actually have done.
    # Cross-sectional relative-strength rank: percentile of each symbol's 60-day
    # excess return against its benchmark, among the symbols trading that day. This
    # is what lets "the 10 best RS names" mean anything.
    rs_wide = pd.DataFrame(rs_by_symbol)
    rs_rank = rs_wide.rank(axis=1, pct=True).mul(100)

    def rank_at(ticker: str, when) -> float:
        """RS rank on the last COMPLETED daily bar before this entry."""
        if ticker not in rs_rank.columns:
            return np.nan
        col = rs_rank[ticker].dropna()
        prior = col[col.index < pd.Timestamp(when).normalize()]
        return float(prior.iloc[-1]) if len(prior) else np.nan

    print("\n=== the same trades under a concurrent-position limit ===")
    print("FCFS takes whatever fires first. RS-gate only takes names already in the")
    print("top half / third by relative strength. Rotate lets a stronger signal")
    print("replace the weakest open position when every slot is full.\n")
    for mode in modes:
        t = pd.DataFrame(per_mode[mode])
        t = t[t.reason != "still open"]
        if t.empty:
            continue
        t = t.sort_values("entry_date").copy()
        t["rs_rank"] = [rank_at(r.ticker, r.entry_date) for r in t.itertuples()]
        t.to_csv(out / f"trades_stop_{mode}.csv", index=False, encoding="utf-8")

        rows = []
        for cap in (5, 10, 20, 10 ** 9):
            for policy in ("fcfs", "rs50", "rs67", "rotate"):
                if policy != "fcfs" and cap > 10 ** 8:
                    continue  # a gate without a slot limit is a different question
                floor = {"rs50": 50.0, "rs67": 67.0}.get(policy)
                open_pos, taken = [], []       # open_pos: (exit_date, rs_rank, idx)
                for i, r in enumerate(t.itertuples()):
                    open_pos = [p for p in open_pos if p[0] > r.entry_date]
                    if floor is not None and not (r.rs_rank >= floor):
                        continue
                    if len(open_pos) >= cap:
                        if policy != "rotate" or not np.isfinite(r.rs_rank):
                            continue
                        weakest = min(open_pos, key=lambda p: (p[1] if np.isfinite(p[1]) else -1))
                        if not (r.rs_rank > (weakest[1] if np.isfinite(weakest[1]) else -1)):
                            continue
                        open_pos.remove(weakest)   # swap out the weakest name
                    open_pos.append((r.exit_date, r.rs_rank, i))
                    taken.append(r)
                if not taken:
                    continue
                k = pd.DataFrame(taken)
                eq = (1 + args.risk_frac * k.sort_values("exit_date").R).cumprod()
                rows.append({"stop": mode,
                             "max_open": "none" if cap > 10 ** 8 else cap,
                             "policy": policy,
                             "trades": len(k),
                             "taken_%": round(100 * len(k) / len(t), 1),
                             "avg_R": round(k.R.mean(), 2),
                             "total_R": round(k.R.sum(), 1),
                             "equity_x": round(float(eq.iloc[-1]), 2),
                             "max_dd_%": round(float((eq / eq.cummax() - 1).min() * 100), 1)})
        print(pd.DataFrame(rows).to_string(index=False))

    print(f"\nwrote {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
