#!/usr/bin/env python3
"""Forward paper-trading log for the armed-window strategy. No broker involved.

    .venv/Scripts/python.exe backtest/paper_log.py            # daily, after the close
    .venv/Scripts/python.exe backtest/paper_log.py --status   # no data refresh

First run writes paper/config.json and starts the log from today. Every later run
replays the whole period from that start date and rewrites the outputs.

Why replay instead of keeping a running position file: the strategy is
deterministic and causal, so replaying the same rules over the same bars always
reaches the same decisions. A mutable state file would instead accumulate drift
whenever a run was missed, repeated, or interrupted, and would silently keep a
position that a data revision says should have stopped out. Replay is idempotent -
run it twice, or skip a week, and the result is identical either way.

Positions are sized from the CURRENT equity: shares = (risk_frac x equity) / risk
per share. Nothing here places an order; it produces the list you would place.

Outputs, under paper/:
    open_positions.csv   what would be held right now, with shares and stop
    trades.csv           every closed paper trade
    equity.csv           the equity curve
    log.md               a dated report, newest actions first
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

# The Windows console is cp1252; an em dash in a report line should not
# be able to abort a run. Files are written as UTF-8 regardless.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import load_daily, load_intraday, parse_watchlist
from relative_strength import RsParams, benchmark_for, load_benchmarks, rs_frame
from run_armed_1h import armed_windows
from supertrend_ai import SuperTrendParams, supertrend

CFG = Path("paper/config.json")


def load_config(args) -> dict:
    if CFG.exists():
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
    else:
        cfg = {
            "start": args.start or str(date.today()),
            "equity": args.equity,
            "risk_frac": args.risk_frac,
            "max_slots": args.max_slots,
            "rr": args.rr,
            "watchlist": args.watchlist,
            "classic_factor": args.classic_factor,
            "atr_length": args.atr_length,
            "ma_length": args.ma_length,
            "max_position_pct": args.max_position_pct,
        }
        CFG.parent.mkdir(parents=True, exist_ok=True)
        CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"created {CFG} - the log starts {cfg['start']}\n")
    # Explicit flags still override, so settings can be changed deliberately.
    for k, v in (("equity", args.equity), ("risk_frac", args.risk_frac),
                 ("max_slots", args.max_slots), ("rr", args.rr),
                 ("max_position_pct", args.max_position_pct)):
        if v is not None:
            cfg[k] = v
    # Persist the derived default so the ceiling is visible and editable in
    # config.json rather than an invisible fallback in the code.
    if not cfg.get("max_position_pct"):
        cfg["max_position_pct"] = round(100.0 / max(cfg["max_slots"], 1), 2)
    return cfg


def simulate(cfg: dict, cache_dir: str, refresh: bool) -> tuple:
    stp = SuperTrendParams(engine="classic", classic_factor=cfg["classic_factor"],
                           atr_length=cfg["atr_length"])
    tickers = parse_watchlist(cfg["watchlist"])
    start = pd.Timestamp(cfg["start"])
    rsp = RsParams(mode="roc_diff", roc_length=60)
    benches = load_benchmarks(tickers, rsp, load_daily, "2022-01-01", None, cache_dir)

    candidates = []
    for t in tickers:
        try:
            d = load_daily(t, "2022-01-01", None, cache_dir)
            h = load_intraday(t, "1h")
        except Exception:  # noqa: BLE001
            continue
        if d.empty or len(d) < cfg["ma_length"] + 20 or h.empty:
            continue
        # Completed bars only: an open session gives a partial bar whose signal
        # can vanish by the close.
        d = d[d.index.date < date.today()]
        h = h[h.index.date < date.today()]
        if d.empty or h.empty:
            continue

        bench = benches.get(benchmark_for(t, rsp))
        rs = rs_frame(d, bench, rsp)["rs_diff"] if bench is not None and not bench.empty \
            else pd.Series(dtype=float)
        hres = supertrend(h, stp)
        hflip = hres.buy.to_numpy()

        for arm, disarm, _dstop in armed_windows(d, stp, cfg["ma_length"]):
            end = disarm if disarm is not None else h.index.max()
            if end < start:
                continue
            # From the day AFTER the arm, never the arming session itself: `arm` is
            # stamped at midnight, so a plain `>` would admit that day's own hourly
            # bars, hours before its close confirmed the daily signal.
            seg = h[(h.index.normalize() > arm) & (h.index > start) & (h.index <= end)]
            if seg.empty:
                continue
            for ft in seg.index[hflip[h.index.searchsorted(seg.index)]]:
                entry = float(h.loc[ft, "Close"])
                stop = float(hres.trailing_stop.loc[ft])
                if not np.isfinite(stop) or entry <= stop:
                    continue
                risk = entry - stop
                target = entry + cfg["rr"] * risk
                fwd = h[(h.index > ft) & (h.index <= end)]
                xp = xt = None
                reason = "open"
                for ts, b in fwd.iterrows():
                    lo, hi, o = float(b["Low"]), float(b["High"]), float(b["Open"])
                    if lo <= stop:
                        xp, xt, reason = (o if o <= stop else stop), ts, "stop"
                        break
                    if hi >= target:
                        xp, xt, reason = (o if o >= target else target), ts, "target"
                        break
                if xp is None and disarm is not None and not fwd.empty:
                    xp, xt, reason = float(fwd.iloc[-1]["Close"]), fwd.index[-1], "disarm"
                last = float(h["Close"].iloc[-1])
                rsv = rs[rs.index < ft.normalize()]
                candidates.append({
                    "ticker": t, "arm_date": arm.date(), "entry_time": ft,
                    "entry": entry, "stop": stop, "target": target,
                    "risk_per_share": risk, "risk_pct": 100 * risk / entry,
                    "exit_time": xt, "exit": xp, "reason": reason,
                    "mark": last if xp is None else xp,
                    "rs_diff": round(float(rsv.iloc[-1]), 1) if len(rsv) else np.nan,
                })

    cand = pd.DataFrame(candidates)
    if cand.empty:
        return cand, cand, pd.Series(dtype=float)
    cand = cand.sort_values("entry_time").reset_index(drop=True)

    # First-come-first-served slot allocation, chronologically. RS-ranked selection
    # was tested and is worse on every metric (see README / FINDINGS.md).
    #
    # One position per symbol at a time. An armed window can produce several 1h
    # flips while the first is still open, and taking each of them stacks the same
    # name - a 3-month replay ended up holding SIX2.DE twice, 18% of equity in one
    # stock. The backtest never did this because it advanced a cursor past each
    # exit; the same constraint is enforced here explicitly.
    open_pos, taken_idx = [], []   # open_pos: (exit_time, ticker)
    for i, r in enumerate(cand.itertuples()):
        open_pos = [p for p in open_pos if pd.isna(p[0]) or p[0] > r.entry_time]
        if any(p[1] == r.ticker for p in open_pos):
            continue
        if len(open_pos) >= cfg["max_slots"]:
            continue
        open_pos.append((r.exit_time if pd.notna(r.exit_time) else pd.Timestamp.max,
                         r.ticker))
        taken_idx.append(i)
    taken = cand.loc[taken_idx].copy()

    # Size each entry off the equity at that moment, so wins compound.
    eq = float(cfg["equity"])
    curve, rows = [], []
    # Cap each position's NOTIONAL, not just its risk. Sizing by risk alone means a
    # tight stop buys a huge position: SIX2.DE's 1.77% stop produced 18.6% of equity
    # in one name, and six of those would be 112% of capital - on margin without
    # ever deciding to be. The default ceiling is an equal-weight slice
    # (100 / max_slots), which guarantees a fully-invested book is never leveraged.
    # A capped position simply risks less than risk_frac, which is the safe
    # direction to err.
    max_pos_pct = cfg.get("max_position_pct") or (100.0 / max(cfg["max_slots"], 1))
    for r in taken.sort_values("entry_time").itertuples():
        shares = int((cfg["risk_frac"] * eq) / r.risk_per_share) if r.risk_per_share > 0 else 0
        cap_shares = int((max_pos_pct / 100.0 * eq) / r.entry) if r.entry > 0 else 0
        capped = shares > cap_shares
        shares = min(shares, cap_shares)
        rec = {
            "ticker": r.ticker, "entry_time": r.entry_time, "entry": round(r.entry, 4),
            "shares": shares, "notional": round(shares * r.entry, 2),
            "stop": round(r.stop, 4), "target": round(r.target, 4),
            "risk_pct": round(r.risk_pct, 2), "risk_eur": round(shares * r.risk_per_share, 2),
            "capped": capped,
            "reason": r.reason, "rs_diff": r.rs_diff,
            "exit_time": r.exit_time, "exit": None if pd.isna(r.exit) else round(r.exit, 4),
            "R": round((r.mark - r.entry) / r.risk_per_share, 2),
            "pnl": round(shares * (r.mark - r.entry), 2),
            "mark": round(r.mark, 4),
        }
        if r.reason != "open":
            eq += rec["pnl"]
            curve.append({"date": r.exit_time, "equity": round(eq, 2)})
        rows.append(rec)

    res = pd.DataFrame(rows)
    closed = res[res.reason != "open"].copy()
    open_now = res[res.reason == "open"].copy()
    return closed, open_now, pd.DataFrame(curve)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--start", default=None, help="log start date (first run only)")
    ap.add_argument("--equity", type=float, default=None, help="starting equity")
    ap.add_argument("--risk-frac", type=float, default=None, help="risk per trade, e.g. 0.0033")
    ap.add_argument("--max-slots", type=int, default=None)
    ap.add_argument("--max-position-pct", type=float, default=None,
                    help="ceiling on one position as %% of equity "
                         "(default: an equal-weight slice, 100 / max_slots)")
    ap.add_argument("--rr", type=float, default=None)
    ap.add_argument("--classic-factor", type=float, default=3.0)
    ap.add_argument("--atr-length", type=int, default=10)
    ap.add_argument("--ma-length", type=int, default=200)
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--status", action="store_true", help="do not refresh data")
    ap.add_argument("--replay-from", default=None,
                    help="answer 'what would be open now if I had started on DATE' "
                         "without touching the saved config or the live log")
    ap.add_argument("--outdir", default="paper")
    args = ap.parse_args()
    if not CFG.exists():
        args.equity = args.equity if args.equity is not None else 16900.0
        args.risk_frac = args.risk_frac if args.risk_frac is not None else 0.0033
        args.max_slots = args.max_slots if args.max_slots is not None else 6
        args.rr = args.rr if args.rr is not None else 3.0
    cfg = load_config(args)
    if args.replay_from:
        # A what-if: override the start in memory only. Writing it would silently
        # restart the live forward record from a backdated day.
        cfg = {**cfg, "start": args.replay_from}
        print(f"REPLAY what-if from {cfg['start']} - the saved log is untouched\n")
    else:
        CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    closed, open_now, curve = simulate(cfg, args.cache_dir, not args.status)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for df, name in ((closed, "trades.csv"), (open_now, "open_positions.csv"),
                     (curve, "equity.csv")):
        df.to_csv(out / name, index=False, encoding="utf-8")

    eq0 = float(cfg["equity"])
    eq = float(curve.equity.iloc[-1]) if len(curve) else eq0
    open_pnl = float(open_now.pnl.sum()) if len(open_now) else 0.0
    wins = closed[closed.R > 0] if len(closed) else closed

    hdr = [
        f"# Paper log — {cfg['start']} to {date.today()}",
        "",
        f"- Rules: daily SuperTrend(classic {cfg['classic_factor']}) arms while above "
        f"SMA{cfg['ma_length']}; entry on a 1h SuperTrend flip; stop at the 1h "
        f"SuperTrend; target {cfg['rr']:g}R; exit on stop, target or disarm",
        f"- Sizing: {cfg['risk_frac']*100:.2f}% of equity risked per trade, position "
        f"capped at {cfg.get('max_position_pct') or (100.0/max(cfg['max_slots'],1)):.1f}% "
        f"of equity, max {cfg['max_slots']} open, first-come-first-served",
        f"- Starting equity {eq0:,.2f}  ->  realised {eq:,.2f} "
        f"({100*(eq/eq0-1):+.2f}%), open P&L {open_pnl:+,.2f}",
        f"- Closed {len(closed)}"
        + (f", win rate {100*len(wins)/len(closed):.0f}%, total {closed.R.sum():+.1f}R"
           if len(closed) else ""),
        "",
        "## Open positions",
        "",
    ]
    cols_o = ["ticker", "entry_time", "entry", "shares", "notional", "stop",
              "target", "mark", "R", "pnl", "risk_pct", "rs_diff"]
    hdr += [open_now[cols_o].to_markdown(index=False) if len(open_now) else "_none_", ""]
    hdr += ["## Closed trades", ""]
    cols_c = ["ticker", "entry_time", "exit_time", "reason", "entry", "exit",
              "shares", "R", "pnl"]
    hdr += [closed.sort_values("exit_time", ascending=False)[cols_c].to_markdown(index=False)
            if len(closed) else "_none_", ""]
    (out / "log.md").write_text("\n".join(hdr), encoding="utf-8")

    print(f"\n=== PAPER LOG  {cfg['start']} -> {date.today()} ===")
    print(f"  equity {eq0:,.2f} -> {eq:,.2f} ({100*(eq/eq0-1):+.2f}%)  "
          f"open P&L {open_pnl:+,.2f}   slots {len(open_now)}/{cfg['max_slots']}")
    if len(closed):
        print(f"  closed {len(closed)}  win {100*len(wins)/len(closed):.0f}%  "
              f"total {closed.R.sum():+.1f}R")
    print(f"\nOPEN ({len(open_now)}):")
    print(open_now[cols_o].to_string(index=False) if len(open_now) else "  none")
    if len(closed):
        print(f"\nCLOSED ({len(closed)}), most recent first:")
        print(closed.sort_values("exit_time", ascending=False)[cols_c]
              .head(15).to_string(index=False))
    print(f"\nwrote {out}/log.md, open_positions.csv, trades.csv, equity.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
