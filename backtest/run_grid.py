#!/usr/bin/env python3
"""Grid search of SuperTrend MTF configurations across a whole watchlist.

Answers two questions at once:

  1. WHICH CONFIG works best — ranked by how many symbols it leaves in profit,
     which is the stated goal, with median return / profit factor / beat-buy-&-hold
     alongside so a config that wins on count but loses on size is visible.

  2. WHICH SYMBOLS TREND — for each symbol, the share of configurations that end
     profitable. A name that pays under most settings is genuinely trending; one
     that only pays under a single lucky combination is noise, and one that pays
     under none can be dropped from the list.

The expensive parts (the adaptive k-means SuperTrend, and each HTF filter) do not
depend on the side/strength settings, so they are computed ONCE per symbol and
shared across every configuration that uses them.

    python backtest/run_grid.py --watchlist watchlists/fox.txt --start 2018-01-01
"""

from __future__ import annotations

import argparse
import itertools
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily, parse_watchlist
from engine import SideParams, StrategyParams, run_backtest
from htf import HtfParams, htf_filter
from run_backtest import WARMUP_DAYS, to_markdown_table
from supertrend_ai import SuperTrendParams, supertrend

# ── The grid ────────────────────────────────────────────────────────────────
# Keys are short labels that end up in the report; keep them stable so runs can
# be compared across sessions.
ENGINES = {
    "adaptive":  SuperTrendParams(engine="adaptive"),
    "classic1.5": SuperTrendParams(engine="classic", classic_factor=1.5),
    "classic2":  SuperTrendParams(engine="classic", classic_factor=2.0),
    "classic3":  SuperTrendParams(engine="classic", classic_factor=3.0),
    "classic4":  SuperTrendParams(engine="classic", classic_factor=4.0),
}

HTFS = {
    "none":      HtfParams(enabled=False),
    "W-adx+rsi": HtfParams(timeframe="W", use_adx=True,  use_mom=True),
    "W-adx":     HtfParams(timeframe="W", use_adx=True,  use_mom=False),
    "W-rsi":     HtfParams(timeframe="W", use_adx=False, use_mom=True),
    "M-adx+rsi": HtfParams(timeframe="M", use_adx=True,  use_mom=True),
}

SIDES = {
    "long":       (True, False),
    "long+short": (True, True),
}

STRENGTHS = [0, 4]


def config_label(eng: str, htf: str, side: str, strength: int) -> str:
    # " / " and not " | " — these labels land in a markdown table column, and a
    # pipe inside a cell splits it into bogus extra columns.
    return f"{eng} / {htf} / {side} / str>={strength}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", required=True)
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--ma-length", type=int, default=200)
    ap.add_argument("--commission", type=float, default=0.1)
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--outdir", default="results/grid")
    ap.add_argument("--min-bars", type=int, default=400,
                    help="skip symbols with fewer daily bars than this")
    args = ap.parse_args()

    tickers = parse_watchlist(args.watchlist)
    combos = list(itertools.product(ENGINES, HTFS, SIDES, STRENGTHS))
    print(f"{len(tickers)} symbols x {len(combos)} configurations "
          f"= {len(tickers) * len(combos):,} backtests\n")

    trade_start = pd.Timestamp(args.start)
    dl_start = (trade_start - pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")

    rows: list[dict] = []
    skipped: list[tuple[str, str]] = []
    t0 = time.time()

    for n, ticker in enumerate(tickers, 1):
        try:
            df = load_daily(ticker, dl_start, args.end, args.cache_dir)
        except Exception as exc:  # noqa: BLE001
            skipped.append((ticker, f"data error: {exc}"))
            print(f"[{n:3d}/{len(tickers)}] {ticker:12s} SKIP  data error")
            continue
        if df.empty or len(df) < args.min_bars:
            skipped.append((ticker, f"insufficient data ({len(df)} bars)"))
            print(f"[{n:3d}/{len(tickers)}] {ticker:12s} SKIP  {len(df)} bars")
            continue

        # Compute the expensive pieces once for this symbol.
        st_cache = {k: supertrend(df, p) for k, p in ENGINES.items()}
        htf_cache = {k: htf_filter(df, p) for k, p in HTFS.items()}

        wins = 0
        for eng, htf, side, strength in combos:
            long_on, short_on = SIDES[side]
            params = StrategyParams(
                st=ENGINES[eng],
                long=SideParams(enabled=long_on, ma_length=args.ma_length,
                                min_strength=strength),
                short=SideParams(enabled=short_on, ma_length=args.ma_length,
                                 min_strength=strength),
                htf=HTFS[htf],
                commission_pct=args.commission)
            r = run_backtest(ticker, df, params, trade_start=trade_start,
                             st_result=st_cache[eng], htf_frame=htf_cache[htf])
            s = r.summary()
            if s["trades"] == 0:
                continue  # a config that never traded is not evidence either way
            rows.append({
                "ticker": ticker, "engine": eng, "htf": htf, "side": side,
                "min_strength": strength,
                "config": config_label(eng, htf, side, strength),
                "trades": s["trades"], "longs": s["longs"], "shorts": s["shorts"],
                "win_rate_pct": s["win_rate_pct"], "profit_factor": s["profit_factor"],
                "return_pct": s["strategy_return_pct"],
                "buy_hold_pct": s["buy_hold_return_pct"],
                "max_dd_pct": s["max_drawdown_pct"],
            })
            if s["strategy_return_pct"] > 0:
                wins += 1
        print(f"[{n:3d}/{len(tickers)}] {ticker:12s} {len(df):5d} bars  "
              f"profitable in {wins}/{len(combos)} configs")

    if not rows:
        print("No results.", file=sys.stderr)
        return 1

    raw = pd.DataFrame(rows)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    raw.to_csv(out / "grid_raw.csv", index=False, encoding="utf-8")

    tested = raw["ticker"].nunique()

    # ── Ranking 1: configurations, by symbols left in profit ────────────────
    recs = []
    for cfg, g in raw.groupby("config"):
        recs.append({
            "config": cfg,
            "symbols": len(g),
            "in_profit": int((g["return_pct"] > 0).sum()),
            "in_profit_pct": round(100 * (g["return_pct"] > 0).mean(), 1),
            "beat_b&h": int((g["return_pct"] > g["buy_hold_pct"]).sum()),
            "median_return_pct": round(g["return_pct"].median(), 1),
            "mean_return_pct": round(g["return_pct"].mean(), 1),
            "median_pf": round(g["profit_factor"].replace([float("inf")], float("nan")).median(), 2),
            "median_dd_pct": round(g["max_dd_pct"].median(), 1),
            "avg_trades": round(g["trades"].mean(), 1),
        })
    by_cfg = pd.DataFrame(recs).sort_values(
        ["in_profit", "median_return_pct"], ascending=False).reset_index(drop=True)
    by_cfg.to_csv(out / "grid_by_config.csv", index=False, encoding="utf-8")

    # ── Ranking 2: symbols, by how consistently they trend ───────────────────
    recs = []
    for tkr, g in raw.groupby("ticker"):
        best = g.loc[g["return_pct"].idxmax()]
        recs.append({
            "ticker": tkr,
            "configs": len(g),
            "profitable_in": int((g["return_pct"] > 0).sum()),
            "robustness_pct": round(100 * (g["return_pct"] > 0).mean(), 1),
            "median_return_pct": round(g["return_pct"].median(), 1),
            "best_return_pct": round(float(best["return_pct"]), 1),
            "best_config": best["config"],
            "buy_hold_pct": round(float(best["buy_hold_pct"]), 1),
            "beat_b&h_in": int((g["return_pct"] > g["buy_hold_pct"]).sum()),
        })
    by_sym = pd.DataFrame(recs).sort_values(
        ["robustness_pct", "median_return_pct"], ascending=False).reset_index(drop=True)
    by_sym.to_csv(out / "grid_by_symbol.csv", index=False, encoding="utf-8")

    # ── Report ──────────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    top_cfg = by_cfg.head(20)
    trenders = by_sym[by_sym["robustness_pct"] >= 70]
    duds = by_sym[by_sym["robustness_pct"] < 30]

    lines = [
        "# SuperTrend MTF — configuration grid",
        "",
        f"- Watchlist: `{args.watchlist}` — {tested} symbols with usable data "
        f"({len(skipped)} skipped)",
        f"- Window: {args.start} -> {args.end or 'today'}, daily bars, "
        f"MA{args.ma_length}, {args.commission}% commission per side",
        f"- Grid: {len(ENGINES)} engines x {len(HTFS)} HTF filters x {len(SIDES)} "
        f"side modes x {len(STRENGTHS)} strength floors = {len(combos)} configurations",
        f"- {len(raw):,} symbol/config results that placed at least one trade "
        f"({elapsed/60:.1f} min)",
        "",
        "Ranked by the stated goal: the number of symbols left **in profit**.",
        "",
        "## Best configurations",
        "",
        to_markdown_table(top_cfg),
        "",
        "## Best trending stocks",
        "",
        f"`robustness_pct` is the share of the {len(combos)} configurations in which the "
        "symbol ends profitable. High means the symbol trends and the exact settings "
        "barely matter; low means any profit came from one lucky combination.",
        "",
        f"### Trends reliably (profitable in >= 70% of configurations) — {len(trenders)} symbols",
        "",
        to_markdown_table(trenders.head(60)),
        "",
        f"### Candidates to drop (profitable in < 30% of configurations) — {len(duds)} symbols",
        "",
        to_markdown_table(duds[["ticker", "configs", "profitable_in", "robustness_pct",
                                "median_return_pct", "best_return_pct", "buy_hold_pct"]]),
        "",
    ]
    if skipped:
        lines += ["## Skipped symbols", ""]
        lines += [f"- `{t}` — {why}" for t, why in skipped]
        lines += [""]

    (out / "grid_report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\n{'='*78}\nTOP 10 CONFIGURATIONS (by symbols in profit)\n{'='*78}")
    print(by_cfg.head(10).to_string(index=False))
    print(f"\n{'='*78}\nTOP 20 TRENDING STOCKS (by robustness across configs)\n{'='*78}")
    print(by_sym.head(20).to_string(index=False))
    print(f"\nWrote {out}/grid_report.md, grid_by_config.csv, grid_by_symbol.csv, grid_raw.csv")
    print(f"Elapsed {elapsed/60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
