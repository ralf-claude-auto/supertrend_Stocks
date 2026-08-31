#!/usr/bin/env python3
"""Daily signal, hourly MA trigger, fixed risk:reward exit.

    .venv/Scripts/python.exe backtest/run_rr_1h.py --rr 3

The daily SuperTrend signal decides WHAT to buy; a moving-average cross on the
1-hour chart decides WHEN. The question is whether timing the entry on a lower
timeframe beats simply buying the next daily open.

  Trigger  the first 1h bar after the signal session whose close crosses UP
           through the MA - it must come from BELOW, so this is a pullback entry.
           Signals that never pull back inside the trigger window are skipped, and
           that skip rate is reported: a trigger that misses the runaway moves can
           look good on the trades it does take while losing the ones that mattered.
  Entry    the close of that 1h bar.
  Risk     entry minus the daily SuperTrend line as it stood on the SIGNAL DAY -
           the same stop the daily test uses, so the two are comparable.
  Exit     first 1h bar with low <= stop or high >= target. Hourly bars resolve
           the order of touches far better than daily ones, so the "both in one
           bar" ambiguity that forces a pessimistic assumption on the daily test
           barely arises here.

The same signals are also run through the daily next-open rule over the SAME
window, because the hourly test is limited to roughly 2 years by Yahoo's intraday
history and comparing it against the 5-year daily figures would not be honest.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily, load_intraday
from run_rr import run_one, summarise


def ma_of(close: pd.Series, kind: str, length: int) -> pd.Series:
    if kind == "ema":
        return close.ewm(span=length, adjust=False, min_periods=length).mean()
    return close.rolling(length).mean()


def run_one_1h(sig: pd.Series, h: pd.DataFrame, ma: pd.Series, rr: float,
               window_bars: int, commission: float) -> dict | None:
    """One signal, entered on the first hourly cross up through the MA."""
    after = h[h.index > pd.Timestamp(sig["date"]) + pd.Timedelta(days=1)]
    if after.empty:
        return None
    scan = after.iloc[:window_bars]
    m = ma.reindex(scan.index)
    c = scan["Close"]
    prev_below = (c.shift(1) <= m.shift(1))
    cross = (c > m) & prev_below
    hits = scan.index[cross.fillna(False).to_numpy()]
    if len(hits) == 0:
        return {"_no_trigger": True}

    entry_ts = hits[0]
    entry = float(scan.loc[entry_ts, "Close"])
    stop = float(sig["stop"])
    if not np.isfinite(entry) or not np.isfinite(stop) or entry <= stop:
        return None
    risk = entry - stop
    target = entry + rr * risk
    fee = commission / 100.0

    held = h[h.index > entry_ts]
    exit_price, exit_ts, reason = None, None, ""
    for ts, b in held.iterrows():
        lo, hi, o = float(b["Low"]), float(b["High"]), float(b["Open"])
        if lo <= stop:
            exit_price, exit_ts, reason = (o if o <= stop else stop), ts, "stop"
            break
        if hi >= target:
            exit_price, exit_ts, reason = (o if o >= target else target), ts, "target"
            break
    if exit_price is None:
        if held.empty:
            return None
        exit_price, exit_ts, reason = float(held.iloc[-1]["Close"]), held.index[-1], "still open"

    gross = (exit_price / entry - 1.0) * 100.0
    return {
        "ticker": sig["ticker"], "signal_date": pd.Timestamp(sig["date"]).date(),
        "entry_date": entry_ts, "entry": round(entry, 4),
        "stop": round(stop, 4), "target": round(target, 4),
        "exit_date": exit_ts, "exit": round(exit_price, 4), "reason": reason,
        "bars_held": int(held.index.get_loc(exit_ts)) + 1,
        "trigger_bars": int(scan.index.get_loc(entry_ts)) + 1,
        "risk_pct": round(100 * risk / entry, 2),
        "R": round((exit_price - entry) / risk, 3),
        "return_pct": round(gross - 2 * fee * 100.0, 2),
        "rs_rank": sig.get("rs_rank", np.nan),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--signals", default="scans/history_5y/_signals.csv")
    ap.add_argument("--rr", type=float, default=3.0)
    ap.add_argument("--mas", default="ema20,sma20,ema50,sma50",
                    help="comma-separated <kind><length> to sweep")
    ap.add_argument("--trigger-window", type=int, default=35,
                    help="hourly bars to wait for the cross (~5 sessions)")
    ap.add_argument("--commission", type=float, default=0.1)
    ap.add_argument("--risk-frac", type=float, default=0.01)
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--outdir", default="results/rr_1h")
    args = ap.parse_args()

    sig = pd.read_csv(args.signals, parse_dates=["date"])
    tickers = sorted(sig.ticker.unique())

    print(f"loading 1h history for {len(tickers)} symbols...")
    hourly, daily = {}, {}
    for t in tickers:
        try:
            hourly[t] = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            hourly[t] = pd.DataFrame()
        try:
            daily[t] = load_daily(t, "2022-01-01", None, args.cache_dir)
        except Exception:  # noqa: BLE001
            daily[t] = pd.DataFrame()

    covered = {t: h.index.min() for t, h in hourly.items() if not h.empty}
    if not covered:
        print("no hourly data", file=sys.stderr)
        return 1
    # Filter PER SYMBOL, not against one global cutoff. Yahoo's hourly history
    # starts at a different date per ticker, and taking the latest of them lets a
    # single late listing throw away years of usable signals on every other symbol.
    # All variants still see the identical signal set, so the comparison stays fair.
    usable = sig[sig.apply(
        lambda r: r.ticker in covered and r.date >= covered[r.ticker], axis=1)].copy()
    print(f"hourly coverage begins {min(covered.values()).date()} to "
          f"{max(covered.values()).date()} depending on symbol; "
          f"{len(usable)} of {len(sig)} signals usable\n")

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    summaries = []

    # Daily next-open baseline over the SAME signals, so the comparison is fair.
    base = []
    for _, s in usable.iterrows():
        b = daily.get(s.ticker)
        if b is None or b.empty:
            continue
        r = run_one(s, b, args.rr, 0, args.commission)
        if r:
            base.append(r)
    bt = pd.DataFrame(base)
    summaries.append({**summarise(bt, "daily next open", args.risk_frac),
                      "no_trigger": 0, "taken_%": 100.0})
    bt.to_csv(out / "trades_daily_baseline.csv", index=False, encoding="utf-8")

    for spec in [x.strip() for x in args.mas.split(",") if x.strip()]:
        kind = "ema" if spec.startswith("ema") else "sma"
        length = int(spec[3:])
        trades, no_trig = [], 0
        for _, s in usable.iterrows():
            h = hourly.get(s.ticker)
            if h is None or h.empty:
                continue
            ma = ma_of(h["Close"], kind, length)
            r = run_one_1h(s, h, ma, args.rr, args.trigger_window, args.commission)
            if r is None:
                continue
            if r.get("_no_trigger"):
                no_trig += 1
                continue
            trades.append(r)
        t = pd.DataFrame(trades)
        n_considered = len(t) + no_trig
        summaries.append({
            **summarise(t, f"1h {spec}", args.risk_frac),
            "no_trigger": no_trig,
            "taken_%": round(100 * len(t) / n_considered, 1) if n_considered else 0.0,
        })
        t.to_csv(out / f"trades_1h_{spec}.csv", index=False, encoding="utf-8")

    s = pd.DataFrame(summaries)
    print(f"=== {args.rr:g}:1 exit — daily signal, entry timed on the 1h chart ===\n")
    print(s.to_string(index=False))
    s.to_csv(out / "summary.csv", index=False, encoding="utf-8")
    print(f"\nwrote {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
