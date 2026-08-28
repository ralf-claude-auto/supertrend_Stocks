#!/usr/bin/env python3
"""Batch backtest: SuperTrend AI + 200 SMA over a TradingView watchlist.

Example:
    python backtest/run_backtest.py --watchlist watchlists/fox.txt \
        --start 2018-01-01 --report results/fox_report.md

Outputs a per-symbol summary (console + markdown report) and a trades CSV.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily, parse_watchlist
from engine import StrategyParams, run_backtest
from supertrend_ai import SuperTrendAIParams

WARMUP_DAYS = 450  # calendar days of extra history so SMA200/ATR are warm at start


def to_markdown_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    rows = [[("" if pd.isna(v) else str(v)) for v in rec] for rec in df.itertuples(index=False)]
    widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    fmt = lambda vals: "| " + " | ".join(v.ljust(w) for v, w in zip(vals, widths)) + " |"
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([fmt(cols), sep] + [fmt(r) for r in rows])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watchlist", required=True, help="Watchlist file (TradingView export or one ticker per line)")
    ap.add_argument("--start", default="2018-01-01", help="Backtest start date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="Backtest end date (default: today)")
    ap.add_argument("--ma-length", type=int, default=200)
    ap.add_argument("--atr-length", type=int, default=10)
    ap.add_argument("--min-mult", type=float, default=1.0)
    ap.add_argument("--max-mult", type=float, default=5.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--perf-alpha", type=float, default=10.0)
    ap.add_argument("--from-cluster", default="best", choices=["best", "average", "worst"])
    ap.add_argument("--min-strength", type=int, default=0, help="Minimum signal strength 0-9 (0 = off)")
    ap.add_argument("--exit-below-ma", action="store_true", help="Also exit when close crosses under the SMA")
    ap.add_argument("--commission", type=float, default=0.1, help="Commission per side in %%")
    ap.add_argument("--cache-dir", default="data_cache")
    ap.add_argument("--report", default="results/report.md")
    ap.add_argument("--trades-csv", default="results/trades.csv")
    args = ap.parse_args()

    params = StrategyParams(
        st=SuperTrendAIParams(
            atr_length=args.atr_length, min_mult=args.min_mult, max_mult=args.max_mult,
            step=args.step, perf_alpha=args.perf_alpha, from_cluster=args.from_cluster,
            min_strength=args.min_strength),
        ma_length=args.ma_length, exit_below_ma=args.exit_below_ma,
        commission_pct=args.commission)

    tickers = parse_watchlist(args.watchlist)
    if not tickers:
        print(f"No tickers found in {args.watchlist}", file=sys.stderr)
        return 1
    print(f"Backtesting {len(tickers)} symbols from {args.watchlist} "
          f"({args.start} -> {args.end or 'today'})\n")

    trade_start = pd.Timestamp(args.start)
    dl_start = (trade_start - pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")

    summaries = []
    all_trades = []
    for ticker in tickers:
        try:
            df = load_daily(ticker, dl_start, args.end, args.cache_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"  {ticker:12s} data error: {exc}")
            summaries.append({"ticker": ticker, "error": str(exc)})
            continue
        if df.empty or len(df) < args.ma_length + 20:
            print(f"  {ticker:12s} skipped: not enough data ({len(df)} bars)")
            summaries.append({"ticker": ticker, "error": "insufficient data"})
            continue

        result = run_backtest(ticker, df, params, trade_start=trade_start)
        s = result.summary()
        summaries.append(s)
        print(f"  {ticker:12s} trades={s['trades']:3d}  win={s['win_rate_pct']}%  "
              f"PF={s['profit_factor']}  strat={s['strategy_return_pct']}%  "
              f"B&H={s['buy_hold_return_pct']}%  maxDD={s['max_drawdown_pct']}%")

        for t in result.trades:
            all_trades.append({
                "ticker": ticker,
                "entry_date": t.entry_date.date(),
                "entry_price": round(t.entry_price, 4),
                "exit_date": t.exit_date.date() if t.exit_date is not None else "OPEN",
                "exit_price": round(t.exit_price, 4) if t.exit_price is not None else "",
                "return_pct": round(t.return_pct, 2) if t.return_pct is not None else "",
                "exit_reason": t.exit_reason,
                "signal_strength": t.strength,
            })

    summary_df = pd.DataFrame(summaries)
    trades_df = pd.DataFrame(all_trades)

    Path(args.trades_csv).parent.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(args.trades_csv, index=False)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)

    ok = summary_df[summary_df.get("error", "").fillna("") == ""] if "error" in summary_df else summary_df
    lines = [
        "# SuperTrend AI + 200 SMA — Backtest Report",
        "",
        f"- Watchlist: `{args.watchlist}` ({len(tickers)} symbols)",
        f"- Window: {args.start} -> {args.end or 'today'} (daily bars)",
        f"- Rules: buy on SuperTrend AI bullish flip while close > SMA({args.ma_length}); "
        f"sell on bearish flip{' or close under SMA' if args.exit_below_ma else ''}",
        f"- SuperTrend AI: ATR {args.atr_length}, factors {args.min_mult}-{args.max_mult} "
        f"step {args.step}, perf alpha {args.perf_alpha}, cluster '{args.from_cluster}', "
        f"min strength {args.min_strength}",
        f"- Commission: {args.commission}% per side, long only, 100% of equity per trade",
        "",
        "## Per-symbol results",
        "",
        to_markdown_table(summary_df),
        "",
    ]
    if len(ok) and "strategy_return_pct" in ok:
        lines += [
            "## Aggregate",
            "",
            f"- Symbols tested: {len(ok)}",
            f"- Median strategy return: {ok['strategy_return_pct'].median():.1f}% "
            f"(median buy & hold: {ok['buy_hold_return_pct'].median():.1f}%)",
            f"- Symbols beating buy & hold: "
            f"{(ok['strategy_return_pct'] > ok['buy_hold_return_pct']).sum()} / {len(ok)}",
            f"- Total closed trades: {int(ok['trades'].sum())}",
            "",
        ]
    Path(args.report).write_text("\n".join(lines))
    print(f"\nReport written to {args.report}")
    print(f"Trades written to {args.trades_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
