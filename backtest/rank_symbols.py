#!/usr/bin/env python3
"""Score each symbol on what it has actually produced, and cut the watchlist to
the ones worth holding a slot for.

    .venv/Scripts/python.exe backtest/rank_symbols.py --build     # replay, then score
    .venv/Scripts/python.exe backtest/rank_symbols.py            # score cached trades
    .venv/Scripts/python.exe backtest/rank_symbols.py --write-watchlist --keep 40

THE TRAP THIS AVOIDS. Ranking symbols on a backtest and then reporting that
backtest for the survivors is circular: the winners were chosen BECAUSE they won,
so the "filtered" result is guaranteed to look better and means nothing. Every
number here is instead WALK-FORWARD - a symbol is ranked only on trades that
closed before a cut date, and then judged on trades entered after it. If a
ranking has no forward edge it will show none.

WHAT IS ACTUALLY BEING DECIDED. Cutting the universe raises average quality but
throws away opportunities, and those pull in opposite directions. Which one wins
depends entirely on whether slots are scarce: with more simultaneous signals than
slots, discarding the weak half costs nothing because those trades were never
going to be taken anyway - the slot was already full of something better. So the
comparison that decides it is not average R, it is total R AFTER a first-come-
first-served slot simulation at the real slot count. That is what --slots does,
and it is the number to read.

RECENCY. Scored both ways - all history, and the last N months - because
"recently successful" and "successful" are different claims and only measurement
says which travels. The last 6 months wins, which is why it is the default: at 6
slots, ranking by recent_R and keeping the top 40% gained +37R over six
walk-forward cuts, while ranking by all-time total_R LOST 20R.

WHAT THE MEASUREMENTS SAID, so the defaults are not guesses:

  - keeping the top 40% is right; the top 25% is too deep. On average R the
    deeper cut looks better (0.73 against 0.70) but under 6 slots it turned
    418R against a 499R baseline - it beat that baseline in 0 of 6 cuts. Cutting
    past the point where signals still outnumber slots simply starves them.
  - the gain grows with the slot count: roughly nothing at 4 slots, +37R at 6,
    +128R at 10. With few slots the first decent signal fills them anyway.
  - PRIORITY ORDERING is the robust half, and it is worth more than the filter.
    Taking the best-ranked candidate first among those firing on the same DAY -
    which is what a morning list lets you do - gained, at 6 slots:

        109-symbol fox list      +24R    ahead in 5 cuts of 6
        134-symbol NQ100+DAX    +170R    6 of 6
        220-symbol union        +161R    5 of 6

    Positive on every universe tried, which the filter is not. Measured on the
    fox list ALONE it looks like nothing, and an early reading here said exactly
    that; it does not generalise. The effect is mechanical: once symbols
    outnumber slots, first-come-first-served fills the book with whatever fired
    EARLIEST - unrelated to whether it was any good - and then blocks better
    signals for days. A small universe has little to choose between, so the
    effect nearly vanishes there.

  - the FILTER, by contrast, is universe- and metric-dependent. recent_R keeping
    40% gained +37R on the fox list but -10R on the index list, where total_R
    keeping 60% gained +141R instead. Two universes, two different "best"
    metrics, six cuts each: that is not a stable finding, so do not cut deep on
    the strength of it. Prioritise confidently; filter cautiously.

  - expect roughly +30% from prioritisation on a full index universe. The filter
    adds little once ordering is right, and on the index list it subtracted.

A symbol needs --min-trades before it can be ranked at all. Below that, a good
score is noise: two lucky trades is not evidence, and letting a 2-trade symbol
outrank a 30-trade one is the fastest way to build a watchlist out of flukes.
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
from run_armed_1h import armed_windows, entry_candidates, prior_daily_high
from run_exits import atr_series, simulate
from supertrend_ai import SuperTrendParams, supertrend

DEFAULT_TRADES = Path("results/symbol_trades.csv")


# --------------------------------------------------------------------------
# 1. Replay the settled strategy and record every trade with its exit time.
# --------------------------------------------------------------------------
def build_trades(args) -> pd.DataFrame:
    sim = Namespace(rr=3.0, first_r=args.first_r, atr_len=14, atr_mult=2.0,
                    trail_mult=3.0, swing_n=10, stop_pct=2.0,
                    min_risk_pct=args.min_risk_pct)
    stp = SuperTrendParams(engine="classic", classic_factor=3.0, atr_length=10)
    hstp = SuperTrendParams(engine="classic", classic_factor=args.h_factor,
                            atr_length=10)

    rows = []
    tickers = parse_watchlist(args.watchlist)
    print(f"replaying {len(tickers)} symbols...")
    for t in tickers:
        try:
            d = load_daily(t, "2021-01-01", None, args.cache_dir)
            h = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            continue
        if d.empty or len(d) < 220 or h.empty:
            continue
        hres = supertrend(h, hstp)
        atr = atr_series(h, sim.atr_len)
        pdh = prior_daily_high(d, h)

        for arm, disarm, _ in armed_windows(d, stp, 200, "ema", args.ema_fast,
                                            args.ema_slow, 0.0, 0.0, False):
            end = disarm if disarm is not None else h.index.max()
            if arm < h.index.min():
                continue
            seg = h[(h.index.normalize() > arm) & (h.index <= end)]
            if seg.empty:
                continue
            cursor = None
            for ts in entry_candidates(seg.index, h, hres, "breakout", pdh):
                if cursor is not None and ts <= cursor:
                    continue
                i = h.index.get_loc(ts)
                r = simulate(i, h, hres, atr, end, sim, "st", "be", "partial")
                if r is None:
                    continue
                R, why, exit_ts = r
                rows.append({"ticker": t, "entry_time": ts, "exit_time": exit_ts,
                             "R": round(R, 3), "reason": why})
                cursor = exit_ts

    df = pd.DataFrame(rows).sort_values("entry_time")
    out = Path(args.trades_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    print(f"wrote {out}  ({len(df)} trades, {df.ticker.nunique()} symbols)")
    return df


# --------------------------------------------------------------------------
# 2. Scoring.
# --------------------------------------------------------------------------
def score_symbols(past: pd.DataFrame, asof: pd.Timestamp, recent_months: int
                  ) -> pd.DataFrame:
    """Per-symbol scorecard from trades that closed before `asof`."""
    g = past.groupby("ticker").R
    rec = past[past.entry_time >= asof - pd.DateOffset(months=recent_months)]
    q = (past.assign(q=past.entry_time.dt.to_period("Q"))
             .groupby(["ticker", "q"]).R.sum())

    out = pd.DataFrame({
        "trades": g.size(),
        "total_R": g.sum().round(2),
        "avg_R": g.mean().round(3),
        "win_rate": (g.apply(lambda s: 100 * (s > 0).mean())).round(1),
        "best": g.max().round(1),
        "worst": g.min().round(1),
        "recent_R": rec.groupby("ticker").R.sum().round(2),
        "recent_n": rec.groupby("ticker").R.size(),
        # A steady producer beats one that owes everything to a single trade.
        "pos_quarters": (q.groupby("ticker").apply(lambda s: 100 * (s > 0).mean())
                         ).round(0),
        "last_trade": past.groupby("ticker").entry_time.max().dt.date,
    })
    out["recent_R"] = out.recent_R.fillna(0.0)
    out["recent_n"] = out.recent_n.fillna(0).astype(int)
    return out


def rank_key(sc: pd.DataFrame, how: str) -> pd.Series:
    if how == "total_R":
        return sc.total_R
    if how == "recent_R":
        return sc.recent_R
    if how == "avg_R":
        return sc.avg_R
    if how == "blend":
        # Half the whole record, half the recent stretch, as z-scores so the two
        # are on one scale. Rewards a proven symbol that is still working now.
        a = (sc.total_R - sc.total_R.mean()) / (sc.total_R.std() or 1)
        r = (sc.recent_R - sc.recent_R.mean()) / (sc.recent_R.std() or 1)
        return 0.5 * a + 0.5 * r
    raise ValueError(how)


# --------------------------------------------------------------------------
# 3. Slot-constrained replay - the number that actually decides this.
# --------------------------------------------------------------------------
def slot_total(trades: pd.DataFrame, slots: int) -> tuple[float, int]:
    """Total R actually captured with `slots` positions, first-come-first-served.

    One position per symbol at a time, and a trade is only taken if a slot is
    free when it fires. This is what makes cutting the universe nearly free when
    signals outnumber slots: the discarded trades were never going to be taken.
    """
    open_pos, tot, n = [], 0.0, 0
    for r in trades.sort_values("entry_time").itertuples():
        open_pos = [p for p in open_pos if p[0] > r.entry_time]
        if len(open_pos) >= slots or any(p[1] == r.ticker for p in open_pos):
            continue
        xt = r.exit_time if pd.notna(r.exit_time) else pd.Timestamp.max
        open_pos.append((xt, r.ticker))
        tot += r.R
        n += 1
    return tot, n


def walk_forward(t: pd.DataFrame, args) -> pd.DataFrame:
    rows = []
    cuts = pd.date_range(args.wf_start, args.wf_end, freq="3MS")
    for how in ["total_R", "recent_R", "avg_R", "blend"]:
        for frac in (0.25, 0.4, 0.6):
            sel_R = sel_n = all_R = all_n = 0.0
            sel_avg, all_avg, wins, k = [], [], 0, 0
            for cut in cuts:
                past, fut = t[t.exit_time < cut], t[t.entry_time >= cut]
                if len(fut) < 100 or past.empty:
                    continue
                sc = score_symbols(past, cut, args.recent_months)
                sc = sc[sc.trades >= args.min_trades]
                if len(sc) < 12:
                    continue
                keep = set(rank_key(sc, how)
                           .nlargest(max(int(len(sc) * frac), 5)).index)
                f = fut[fut.ticker.isin(keep)]
                a, an = slot_total(f, args.slots)
                b, bn = slot_total(fut, args.slots)
                sel_R += a; sel_n += an; all_R += b; all_n += bn
                sel_avg.append(f.R.mean()); all_avg.append(fut.R.mean())
                wins += a > b; k += 1
            if not k:
                continue
            rows.append({
                "rank_by": how, "keep": f"{frac:.0%}",
                "avgR_sel": round(np.mean(sel_avg), 3),
                "avgR_all": round(np.mean(all_avg), 3),
                f"slot{args.slots}_R_sel": round(sel_R, 0),
                f"slot{args.slots}_R_all": round(all_R, 0),
                "gain_R": round(sel_R - all_R, 0),
                "trades_taken": int(sel_n), "vs_all": int(all_n),
                "beat": f"{wins}/{k}",
            })
    return pd.DataFrame(rows).sort_values("gain_R", ascending=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--build", action="store_true", help="replay before scoring")
    ap.add_argument("--min-trades", type=int, default=5,
                    help="a symbol needs this many before it can be ranked")
    ap.add_argument("--recent-months", type=int, default=6)
    ap.add_argument("--rank-by", default="recent_R",
                    choices=["total_R", "recent_R", "avg_R", "blend"])
    ap.add_argument("--keep", type=int, default=40,
                    help="symbols in the output list. About 40%% of the rankable "
                         "universe; deeper cuts starved the slots in testing")
    ap.add_argument("--slots", type=int, default=6)
    ap.add_argument("--write-watchlist", action="store_true")
    ap.add_argument("--out", default="watchlists/ranked.txt")
    ap.add_argument("--wf-start", default="2024-12-01")
    ap.add_argument("--wf-end", default="2026-03-01")
    ap.add_argument("--ema-fast", type=int, default=50)
    ap.add_argument("--ema-slow", type=int, default=200)
    ap.add_argument("--h-factor", type=float, default=3.0)
    ap.add_argument("--first-r", type=float, default=1.5)
    ap.add_argument("--min-risk-pct", type=float, default=0.3)
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--trades-file", default=str(DEFAULT_TRADES),
                    help="where the replayed trades are cached; give each "
                         "universe its own file so they can be compared")
    ap.add_argument("--scorecard", default="results/symbol_scorecard.csv")
    ap.add_argument("--priority-out", default="paper/priority.csv",
                    help="ticker,score file that paper_log.py reads to take the "
                         "best-ranked candidate first among same-day signals")
    args = ap.parse_args()

    if args.build or not Path(args.trades_file).exists():
        t = build_trades(args)
    else:
        t = pd.read_csv(args.trades_file, parse_dates=["entry_time", "exit_time"])
        print(f"read {args.trades_file}  ({len(t)} trades, {t.ticker.nunique()} symbols) "
              f"- pass --build to replay")
    if t.empty:
        return 1

    print(f"\n=== RANKING COMPARISON, walk-forward ===")
    print("Ranked only on trades CLOSED before each cut, judged on trades entered")
    print(f"after it. slot{args.slots}_R is total R actually captured with "
          f"{args.slots} slots - the number that decides this.\n")
    wf = walk_forward(t, args)
    print(wf.to_string(index=False))

    asof = t.entry_time.max()
    sc = score_symbols(t, asof, args.recent_months)
    ranked = sc[sc.trades >= args.min_trades].copy()
    ranked["score"] = rank_key(ranked, args.rank_by)
    ranked = ranked.sort_values("score", ascending=False)
    thin = sc[sc.trades < args.min_trades]

    Path("results").mkdir(exist_ok=True)
    ranked.to_csv(args.scorecard, encoding="utf-8")

    cols = ["trades", "total_R", "avg_R", "win_rate", "recent_R", "recent_n",
            "pos_quarters", "worst", "last_trade"]
    print(f"\n=== TOP {args.keep} by {args.rank_by} "
          f"(recent = last {args.recent_months} months) ===")
    print(ranked.head(args.keep)[cols].to_string())
    print(f"\n=== BOTTOM 15 - these are what the filter drops ===")
    print(ranked.tail(15)[cols].to_string())
    if len(thin):
        print(f"\n{len(thin)} symbols below --min-trades {args.min_trades}, "
              f"unrankable: {', '.join(thin.index[:15])}"
              + (" ..." if len(thin) > 15 else ""))

    # The priority file paper_log.py reads to order same-day candidates. Written
    # unconditionally: ordering helped on every universe tested, so there is no
    # reason to make it opt-in the way the watchlist cut is.
    pri = ranked[["score"]].copy()
    pri.index.name = "ticker"
    pri.to_csv(args.priority_out, encoding="utf-8")
    print(f"\nwrote {args.priority_out} ({len(pri)} ranked symbols) "
          f"- paper_log.py uses this to break same-day ties")

    if args.write_watchlist:
        keep = list(ranked.head(args.keep).index)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        hdr = [
            f"# Top {len(keep)} of {len(ranked)} rankable symbols, by {args.rank_by}.",
            f"# Generated {pd.Timestamp.now():%Y-%m-%d} from trades through "
            f"{asof:%Y-%m-%d} by backtest/rank_symbols.py.",
            "#",
            "# Ranked on PAST performance, which is only worth doing because the",
            "# walk-forward test above shows the ranking carries forward. Re-run it",
            "# after any material change; a list frozen for a year is a list of",
            "# symbols that USED to work.",
            f"# Unrankable (<{args.min_trades} trades) are excluded, not judged.",
        ]
        out.write_text("\n".join(hdr + keep) + "\n", encoding="utf-8")
        print(f"\nwrote {out} ({len(keep)} symbols)")
    else:
        print("\n(--write-watchlist to save the list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
