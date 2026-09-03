#!/usr/bin/env python3
"""Daily scan for the SuperTrend Breakout strategy.

    .venv/Scripts/python.exe backtest/scan_daily.py --watchlist watchlists/fox.txt

THE STRATEGY, and nothing else. The daily SuperTrend gate, the relative-strength
ranking and the up/down trend lists that earlier versions of this file produced
are gone: every one of them was measured and none improved the result, so the
scan now reports exactly what is traded.

  FILTER (daily)  close above BOTH the EMA50 and the EMA200. A stock that clears
                  it is ARMED. Losing either average disarms it, and that is also
                  the exit for an open position.
  TRIGGER (1h)    the first 1h close above the PREVIOUS completed daily high.
                  Re-entry is allowed while the window stays armed.
  STOP            the 1h SuperTrend at the moment of entry, fixed.
  MANAGE          breakeven at 1R, half out at 1.5R, remainder on the breakeven
                  stop until the gate disarms.

WHY 07:00 AND WHAT IT SEES. Run at 07:00 local, every session this needs is
already closed and published: XETRA settled at 17:30 yesterday, New York at 22:00
yesterday. So both markets contribute a COMPLETE previous-day candle and the two
lists are computed on the same footing. Any bar dated today is dropped - while a
market is open Yahoo serves a partial bar, and a gate computed on one can reverse
by the close.

That also fixes what "the previous daily high" means. The trigger level published
this morning is YESTERDAY's high, and it stands all day: it does not creep upward
as today's session prints. It is the same level the Pine study draws, because the
study reads the daily series as expr[1] for exactly this reason.

The stop level shown is an ESTIMATE. The real stop is the 1h SuperTrend at the
moment of the breakout, which has not happened yet; what is printed is where that
line sits on the most recent completed 1h bar. It moves during the session. Treat
it as a size guide, not as an order.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import load_daily, load_intraday, parse_watchlist
from supertrend_ai import SuperTrendParams, supertrend

WARMUP_DAYS = 500          # EMA200 needs far less, but a long tail costs nothing

# A cache missing the PREVIOUS BUSINESS DAY is refetched. This was four calendar
# days and that was too loose to be safe: at 07:00 it let a German file that
# stopped on Monday pass as current on Wednesday, and a gate recomputed on the
# older bar reported nine spurious DISARMS - which in this report means "exit
# your position". Anything still behind after the refetch is reported as STALE
# and kept out of the actionable lists rather than acted on.


def gate_frame(d: pd.DataFrame, fast: int, slow: int) -> pd.DataFrame:
    c = d["Close"]
    ef = c.ewm(span=fast, adjust=False).mean()
    es = c.ewm(span=slow, adjust=False).mean()
    return pd.DataFrame({"close": c, "ema_fast": ef, "ema_slow": es,
                         "armed": (c > ef) & (c > es), "high": d["High"]},
                        index=d.index)


def scan_one(t: str, args, stale: pd.Timestamp) -> dict | None:
    """One symbol's state on the last COMPLETED daily bar."""
    try:
        # An explicit start matters. yfinance given start=None returns about a
        # month, nowhere near the EMA200 warmup, so the first refetch after a
        # cache went stale would silently drop the symbol out of the scan.
        d = load_daily(t, args.start, None, args.cache_dir, stale_after=stale)
    except Exception:  # noqa: BLE001
        return None
    if d.empty or len(d) < args.ema_slow + 10:
        return None

    cutoff = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp(date.today())
    d = d[d.index < cutoff]           # never today's partial bar
    if len(d) < args.ema_slow + 10:
        return None

    g = gate_frame(d, args.ema_fast, args.ema_slow)
    last, prev = g.iloc[-1], g.iloc[-2]

    row = {
        "ticker": t,
        "session": g.index[-1].date().isoformat(),
        "close": round(float(last.close), 2),
        "ema_fast": round(float(last.ema_fast), 2),
        "ema_slow": round(float(last.ema_slow), 2),
        "armed": bool(last.armed),
        "was_armed": bool(prev.armed),
        # The trigger is yesterday's HIGH and it stands all day.
        "trigger": round(float(last.high), 2),
        "to_trigger_pct": round(100 * (last.high - last.close) / last.close, 2),
        # How much cushion before the gate fails, i.e. how far from an exit.
        "to_disarm_pct": round(100 * (last.close - max(last.ema_fast, last.ema_slow))
                               / last.close, 2),
    }
    row["state"] = ("NEW ARM"  if row["armed"] and not row["was_armed"] else
                    "DISARMED" if row["was_armed"] and not row["armed"] else
                    "ARMED"    if row["armed"] else "flat")

    # The 1h SuperTrend, for an indicative stop and therefore a size. Only worth
    # downloading for names that are actually armed.
    row["stop"] = np.nan
    row["risk_pct"] = np.nan
    row["st_line"] = np.nan
    row["note"] = ""
    if row["armed"]:
        try:
            h = load_intraday(t, "1h", cache_dir=args.intraday_dir, stale_after=stale)
        except Exception:  # noqa: BLE001
            h = pd.DataFrame()
        if not h.empty and len(h) > 60:
            hp = SuperTrendParams(engine="classic", classic_factor=args.h_factor,
                                  atr_length=args.h_atr)
            line = supertrend(h, hp).trailing_stop
            st = float(line.iloc[-1])
            if np.isfinite(st):
                row["st_line"] = round(st, 2)
                if st < row["trigger"]:
                    row["stop"] = round(st, 2)
                    row["risk_pct"] = round(
                        100 * (row["trigger"] - st) / row["trigger"], 2)
                else:
                    # Line above price = 1h downtrend. By the time a breakout
                    # actually fires the line will have flipped below; there is
                    # simply no long stop to quote this morning.
                    row["note"] = "1h bearish"
        else:
            row["note"] = "no 1h data"
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", default="watchlists/fox.txt")
    ap.add_argument("--as-of", default=None, help="run as if it were this date")
    ap.add_argument("--ema-fast", type=int, default=50)
    ap.add_argument("--ema-slow", type=int, default=200)
    ap.add_argument("--h-factor", type=float, default=3.0)
    ap.add_argument("--h-atr", type=int, default=10)
    ap.add_argument("--start", default="2021-01-01",
                    help="history start, must comfortably cover the slow EMA")
    ap.add_argument("--min-risk-pct", type=float, default=0.3,
                    help="skip entries whose stop is nearer than this %% of price")
    ap.add_argument("--config", default="paper/config.json",
                    help="equity and risk, for the position-size column")
    ap.add_argument("--positions", default=None,
                    help="this book's open_positions.csv, so a name already held "
                         "is not listed again as a fresh candidate. Defaults to "
                         "the file sitting beside --config")
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--intraday-dir", default="data_cache/intraday")
    ap.add_argument("--outdir", default="scans")
    args = ap.parse_args()

    cfg = {}
    cp = Path(args.config)
    if cp.exists():
        cfg = json.loads(cp.read_text(encoding="utf-8"))
    equity = float(cfg.get("equity", 0) or 0)
    risk_frac = float(cfg.get("risk_frac", 0) or 0)
    max_slots = int(cfg.get("max_slots", 0) or 0)
    max_pos_pct = float(cfg.get("max_position_pct", 100) or 100)

    # Anything whose last bar predates this is refetched rather than trusted. A
    # scan that silently serves a stale cache is worse than one that fails.
    ref = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp(date.today())
    stale = (ref - pd.tseries.offsets.BDay(1)).normalize()

    tickers = parse_watchlist(args.watchlist)
    print(f"scanning {len(tickers)} symbols, gate EMA{args.ema_fast}/EMA{args.ema_slow}...")
    rows, failed = [], []
    for t in tickers:
        r = scan_one(t, args, stale)
        if r is None:
            failed.append(t)
            continue
        rows.append(r)

    if not rows:
        print("no symbols returned data")
        return 1

    df = pd.DataFrame(rows)
    # "session", not "asof": DataFrame.asof is a method, and a column of
    # that name is shadowed by it on attribute access.
    asof = df.session.mode().iat[0]

    # Any symbol whose newest bar is behind the session most of the watchlist
    # reached. A holiday on one exchange does this legitimately, so it is not an
    # error - but its gate was computed on older data, so it must not issue an
    # instruction. Held out of the actionable lists and reported separately.
    df["stale"] = df.session < asof

    # The backtest skips entries whose stop sits nearer than this, because R
    # divides by that distance and a near-zero one produces a meaningless
    # multiple and an enormous position. The scan has to apply the same rule or
    # it would publish trades the tested strategy would never have taken.
    tight = np.isfinite(df.risk_pct) & (df.risk_pct < args.min_risk_pct)
    df.loc[tight, "note"] = "stop too tight"
    df.loc[tight, ["stop", "risk_pct"]] = np.nan

    # Position size, on the indicative stop. Two caps, whichever binds first: the
    # per-trade risk fraction, and a ceiling on any one position's share of
    # equity so a very tight stop cannot swallow the account.
    def size(r):
        if not (equity > 0 and risk_frac > 0) or not np.isfinite(r.stop):
            return np.nan
        risk_per_share = r.trigger - r.stop
        if risk_per_share <= 0:
            return np.nan
        by_risk = equity * risk_frac / risk_per_share
        by_cap = equity * max_pos_pct / 100.0 / r.trigger
        return int(min(by_risk, by_cap))

    df["shares"] = df.apply(size, axis=1)
    df["cost"] = (df.shares * df.trigger).round(0)

    # A share count that rounds to zero is not a trade. It happens when the risk
    # budget buys less than one share - a high-priced name with a wide stop, like
    # MELI at 2,010 with a 59-point stop against 0.33% of 16,900. Listing it as a
    # candidate is worse than omitting it: it reads as actionable every morning
    # and never is. Marked and moved out of the tradeable list, with the reason,
    # rather than silently dropped - the name is still armed, just not for this
    # account size.
    unsizeable = df.shares.notna() & (df.shares < 1)
    df.loc[unsizeable, "note"] = "risk budget < 1 share"
    df.loc[unsizeable, ["shares", "cost"]] = np.nan

    # The priority rank the paper book uses to decide which of the day's
    # candidates gets a slot. Shown because without it every armed name looks
    # equally worth taking: CMCSA and NVDA sit side by side in the list, and
    # nothing on the page says one is 117th of 134 on its own record while the
    # other is near the top. A symbol ranked near the bottom will lose almost
    # every slot contest, so seeing it here means "armed", not "take this".
    # 1 is best. Unranked symbols have too little history to score.
    df["rank"] = np.nan
    pf = Path(cfg.get("priority_file") or "")
    if pf.exists():
        try:
            pr = pd.read_csv(pf)
            order = (pr.sort_values(pr.columns[1], ascending=False)
                       .reset_index(drop=True))
            rmap = {t: i + 1 for i, t in enumerate(order.iloc[:, 0])}
            df["rank"] = df.ticker.map(rmap)
        except Exception:  # noqa: BLE001
            pass

    # Names already in the book. DBK.DE showed why this matters: it broke out on
    # 09-02, the book bought it at 15:00, and the next morning's scan listed it
    # under "armed, waiting for breakout" with a fresh share count - identical to
    # a name you own nothing of. Both statements were true (35.38 really is
    # today's trigger) and together they read as "buy this", which is how you end
    # up holding it twice. The scan had no idea the book existed.
    #
    # The file is written by paper_log AFTER this runs, so it is yesterday's -
    # which is exactly right: it is what you are holding when you read the report.
    pos_path = Path(args.positions) if args.positions else cp.parent / "open_positions.csv"
    held: set[str] = set()
    if pos_path.exists():
        try:
            held = set(pd.read_csv(pos_path).ticker.astype(str))
        except Exception:  # noqa: BLE001
            held = set()
    df["held"] = df.ticker.isin(held)
    # A held name keeps its real gate state in the CSV but is routed to its own
    # section, so it can never be read as something to open.
    df.loc[df.held & (df.state == "ARMED"), "state"] = "HELD"

    # Written only once every column exists. This used to be written before the
    # held/HELD columns were computed, so report_pdf - which renders from this
    # file, not from memory - never saw them and kept listing open positions as
    # fresh candidates even after the console output stopped doing so.
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    csv_path = out / f"{asof}.csv"
    df.sort_values(["state", "to_trigger_pct"]).to_csv(csv_path, index=False,
                                                       encoding="utf-8")

    # Stale symbols are held out of every actionable list. Their gate was
    # computed on older data, so a DISARM from one would be an instruction to
    # exit a position on evidence that does not exist yet.
    live = df[~df.stale]
    new_arm = live[live.state == "NEW ARM"].sort_values(
        ["rank", "to_trigger_pct"], na_position="last")
    disarm = live[live.state == "DISARMED"].sort_values("ticker")
    armed = live[live.state == "ARMED"].sort_values(
        ["rank", "to_trigger_pct"], na_position="last")
    holding = live[live.state == "HELD"].sort_values("ticker")
    behind = df[df.stale].sort_values(["session", "ticker"])

    print(f"\nsession scanned: {asof}   symbols: {len(df)}"
          + (f"   no data: {len(failed)}" if failed else ""))
    print(f"  DISARMED today (exit any open position): {len(disarm)}")
    print(f"  NEW ARM today:                           {len(new_arm)}")
    print(f"  already armed and waiting:               {len(armed)}")
    if len(holding):
        print(f"  already HELD (do not re-enter):          {len(holding)}")
    if len(behind):
        print(f"  STALE, not actionable:                   {len(behind)}")
    if max_slots:
        print(f"  slots: {max_slots}, risk {risk_frac:.2%} of {equity:,.0f}")

    cols = ["rank", "ticker", "close", "trigger", "to_trigger_pct", "stop",
            "risk_pct", "shares", "cost", "to_disarm_pct", "note"]
    for label, part in (("DISARMED - EXIT", disarm), ("NEW ARM", new_arm),
                        ("ARMED, WAITING FOR BREAKOUT", armed),
                        ("ALREADY HELD - do not re-enter", holding),
                        ("STALE - data behind, no instruction", behind)):
        if part.empty:
            continue
        print(f"\n=== {label} ({len(part)}) ===")
        print(part[cols].to_string(index=False))

    md = out / f"{asof}.md"
    with md.open("w", encoding="utf-8") as f:
        f.write(f"# SuperTrend Breakout - scan for {asof}\n\n")
        f.write(f"Gate: close above EMA{args.ema_fast} and EMA{args.ema_slow}. "
                f"Trigger: first 1h close above the previous daily high. "
                f"Stop: 1h SuperTrend({args.h_factor:g}, ATR{args.h_atr}) at entry.\n\n")
        for label, part in (("Disarmed - exit", disarm), ("New arm", new_arm),
                            ("Armed, waiting", armed),
                            ("Already held - do not re-enter", holding),
                            ("Stale - data behind, no instruction", behind)):
            f.write(f"\n## {label} ({len(part)})\n\n")
            f.write("none\n" if part.empty
                    else part[cols].to_markdown(index=False) + "\n")
    print(f"\nwrote {csv_path} and {md}")
    if failed:
        print(f"no data for {len(failed)}: {', '.join(failed[:12])}"
              + (" ..." if len(failed) > 12 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
