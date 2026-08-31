#!/usr/bin/env python3
"""Next-day entry with a fixed risk:reward exit, on the backfilled signals.

    .venv/Scripts/python.exe backtest/backfill_scans.py --days 90
    .venv/Scripts/python.exe backtest/run_rr.py --rr 3

Rules, and what each one assumes:

  Entry   the OPEN of the session AFTER the signal. The signal is only known once
          the signal session has closed, so the next open is the first price
          actually tradeable. No same-day fill.
  Risk    entry minus the SuperTrend line AS IT STOOD ON THE SIGNAL DAY. That
          level is known when the decision is made; using the entry day's own
          SuperTrend would read a value that is not final until that day closes.
  Target  entry + rr x risk.
  Exit    the first bar whose low <= stop or high >= target. When one bar touches
          BOTH, the stop is taken - the daily bar does not say which came first,
          and assuming the target would flatter every result.
  Gaps    if the entry bar opens beyond either level the trade exits at that
          open, for better or worse, rather than at the notional level.

Results are reported in R (multiples of the initial risk) so trades on different
symbols and prices are comparable, and in percent after commission.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily

WARMUP_DAYS = 400


def run_one(sig: pd.Series, bars: pd.DataFrame, rr: float, max_hold: int,
            commission: float) -> dict | None:
    """Simulate a single signal. Returns None when it was not tradeable."""
    after = bars[bars.index > sig["date"]]
    if after.empty:
        return None
    entry_bar = after.index[0]
    entry = float(after.iloc[0]["Open"])
    stop = float(sig["stop"])
    if not np.isfinite(entry) or not np.isfinite(stop) or entry <= stop:
        # Entry already at or below the stop leaves no risk to size against.
        return None

    risk = entry - stop
    target = entry + rr * risk
    fee = commission / 100.0

    held = after if max_hold <= 0 else after.iloc[:max_hold]
    exit_price, exit_date, reason = None, None, ""
    for ts, b in held.iterrows():
        o, h, l = float(b["Open"]), float(b["High"]), float(b["Low"])
        if ts == entry_bar:
            # The entry bar itself can still gap straight through a level.
            if o <= stop:
                exit_price, exit_date, reason = o, ts, "gap through stop"
                break
            if o >= target:
                exit_price, exit_date, reason = o, ts, "gap through target"
                break
        if l <= stop:
            exit_price, exit_date, reason = (o if o <= stop else stop), ts, "stop"
            break
        if h >= target:
            exit_price, exit_date, reason = (o if o >= target else target), ts, "target"
            break
    if exit_price is None:
        exit_price, exit_date, reason = float(held.iloc[-1]["Close"]), held.index[-1], \
            ("time exit" if max_hold > 0 else "still open")

    gross = (exit_price / entry - 1.0) * 100.0
    net = gross - 2 * fee * 100.0
    return {
        "ticker": sig["ticker"], "signal_date": sig["date"].date(),
        "entry_date": entry_bar.date(), "entry": round(entry, 4),
        "stop": round(stop, 4), "target": round(target, 4),
        "exit_date": exit_date.date(), "exit": round(exit_price, 4),
        "reason": reason, "bars_held": int(held.index.get_loc(exit_date)) + 1,
        "risk_pct": round(100 * risk / entry, 2),
        "R": round((exit_price - entry) / risk, 3),
        "return_pct": round(net, 2),
        "rs_rank": sig.get("rs_rank", np.nan),
    }


def summarise(t: pd.DataFrame, label: str, risk_frac: float = 0.01) -> dict:
    """Headline stats over RESOLVED trades only.

    A trade still open at the end of the data has not said what it is yet -
    counting its mark-to-market as a result would let the window's end decide the
    verdict. They are reported separately as `open`.

    Equity assumes a fixed fraction of capital risked per trade (default 1%), so
    the multiplier is prod(1 + risk_frac * R). Compounding percent returns instead
    would imply putting 100% of capital into each of many OVERLAPPING trades,
    which is not a portfolio anyone could run.
    """
    n_open = int((t.reason == "still open").sum()) if len(t) else 0
    t = t[t.reason != "still open"] if len(t) else t
    if t.empty:
        return {"setup": label, "resolved": 0, "open": n_open}
    wins, losses = t[t.R > 0].R, t[t.R <= 0].R
    gw, gl = wins.sum(), abs(losses.sum())
    eq = (1 + risk_frac * t.sort_values("exit_date").R).cumprod()
    return {
        "setup": label,
        "resolved": len(t),
        "open": n_open,
        "win_%": round(100 * len(wins) / len(t), 1),
        "avg_R": round(t.R.mean(), 2),
        "total_R": round(t.R.sum(), 1),
        "PF": round(gw / gl, 2) if gl > 0 else np.inf,
        "avg_ret_%": round(t.return_pct.mean(), 2),
        "med_hold": int(t.bars_held.median()),
        "hit_target_%": round(100 * t.reason.str.contains("target").mean(), 1),
        "equity_x": round(float(eq.iloc[-1]), 3),
        "max_dd_%": round(float((eq / eq.cummax() - 1).min() * 100), 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals", default="scans/history/_signals.csv")
    ap.add_argument("--rr", type=float, default=3.0, help="reward:risk multiple")
    ap.add_argument("--rr-sweep", default="1,2,3,5",
                    help="comma-separated multiples to compare, '' to skip")
    ap.add_argument("--max-hold", type=int, default=0,
                    help="max bars to hold, 0 = until stop or target")
    ap.add_argument("--commission", type=float, default=0.1, help="%% per side")
    ap.add_argument("--min-rs-rank", type=float, default=None,
                    help="only take signals at or above this relative-strength rank")
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--risk-frac", type=float, default=0.01,
                    help="fraction of capital risked per trade for the equity curve")
    ap.add_argument("--outdir", default="results/rr")
    args = ap.parse_args()

    sig = pd.read_csv(args.signals, parse_dates=["date"])
    if args.min_rs_rank is not None:
        before = len(sig)
        sig = sig[sig.rs_rank >= args.min_rs_rank]
        print(f"relative-strength filter >= {args.min_rs_rank}: "
              f"{len(sig)} of {before} signals kept")
    if sig.empty:
        print("no signals", file=sys.stderr)
        return 1

    start = (sig.date.min() - pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")
    bars = {}
    for t in sorted(sig.ticker.unique()):
        try:
            bars[t] = load_daily(t, start, None, args.cache_dir)
        except Exception:  # noqa: BLE001
            bars[t] = pd.DataFrame()

    rrs = [args.rr] if not args.rr_sweep else \
        sorted({float(x) for x in args.rr_sweep.split(",") if x.strip()} | {args.rr})

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rows, summaries = None, []
    for rr in rrs:
        trades = []
        untradeable = 0
        for _, s in sig.iterrows():
            b = bars.get(s.ticker)
            if b is None or b.empty:
                untradeable += 1
                continue
            r = run_one(s, b, rr, args.max_hold, args.commission)
            if r is None:
                untradeable += 1
                continue
            trades.append(r)
        t = pd.DataFrame(trades)
        summaries.append({**summarise(t, f"{rr:g}:1", args.risk_frac), "skipped": untradeable})
        t.to_csv(out / f"trades_rr{rr:g}.csv", index=False, encoding="utf-8")
        if rr == args.rr:
            rows = t

    s = pd.DataFrame(summaries)
    print(f"\n=== next-day entry, fixed risk:reward — {len(sig)} signals ===\n")
    print(s.to_string(index=False))

    if rows is not None and not rows.empty:
        print(f"\n--- {args.rr:g}:1 exit reasons ---")
        print(rows.reason.value_counts().to_string())
        print(f"\n--- best and worst trades at {args.rr:g}:1 ---")
        cols = ["ticker", "signal_date", "entry_date", "exit_date", "reason",
                "risk_pct", "R", "return_pct", "bars_held"]
        print(pd.concat([rows.nlargest(5, "R"), rows.nsmallest(5, "R")])[cols]
              .to_string(index=False))
    (out / "summary.csv").write_text(s.to_csv(index=False), encoding="utf-8")
    print(f"\nwrote {out}/trades_rr*.csv and summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
