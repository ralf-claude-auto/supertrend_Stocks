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
from run_rr import summarise
from supertrend_ai import SuperTrendParams, supertrend


def armed_windows(df: pd.DataFrame, stp: SuperTrendParams, ma_len: int):
    """(arm_date, disarm_date, daily_stop) per window that STARTS with a signal."""
    res = supertrend(df, stp)
    ma = df["Close"].rolling(ma_len).mean()
    ok = (res.trend == 1) & (df["Close"] > ma)
    out = []
    for i in np.flatnonzero(res.buy.to_numpy() & ok.to_numpy()):
        # Walk forward to the first bar where the arm condition fails.
        j = i + 1
        while j < len(df) and bool(ok.iloc[j]):
            j += 1
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

    print(f"loading {len(tickers)} symbols (daily + 1h)...")
    per_mode = {m: [] for m in modes}
    windows_total = armed_no_entry = 0

    for t in tickers:
        try:
            d = load_daily(t, "2022-01-01", None, args.cache_dir)
            h = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            continue
        if d.empty or len(d) < args.ma_length + 20 or h.empty:
            continue

        hres = supertrend(h, stp)          # the SAME SuperTrend, on 1h bars
        hflip = hres.buy.to_numpy()
        wins = armed_windows(d, stp, args.ma_length)

        for arm, disarm, dstop in wins:
            # Only windows the hourly history actually covers can be tested.
            if arm < h.index.min():
                continue
            windows_total += 1
            end = disarm if disarm is not None else h.index.max()
            seg = h[(h.index > arm) & (h.index <= end)]
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
    print("\n=== the same trades under a concurrent-position limit ===")
    for mode in modes:
        t = pd.DataFrame(per_mode[mode])
        t = t[t.reason != "still open"]
        if t.empty:
            continue
        t = t.sort_values("entry_date")
        rows = []
        for cap in (5, 10, 20, 10 ** 9):
            open_until, taken = [], []
            for _, r in t.iterrows():
                open_until = [x for x in open_until if x > r.entry_date]
                if len(open_until) >= cap:
                    continue
                open_until.append(r.exit_date)
                taken.append(r)
            k = pd.DataFrame(taken)
            eq = (1 + args.risk_frac * k.sort_values("exit_date").R).cumprod()
            rows.append({"stop": mode,
                         "max_open": "none" if cap > 10 ** 8 else cap,
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
