#!/usr/bin/env python3
"""Batch backtest of the SuperTrend MTF strategy over a TradingView watchlist.

Every flag mirrors an input of pine/supertrend_mtf_strategy.pine, so a Pine
setting you like can be reproduced here across the whole list.

Examples:
    # defaults: adaptive engine, longs only, weekly ADX+RSI filter
    python backtest/run_backtest.py --watchlist watchlists/fox.txt --start 2018-01-01

    # classic SuperTrend, long AND short, no HTF filter
    python backtest/run_backtest.py --watchlist watchlists/fox.txt \
        --engine classic --classic-factor 3 --short --no-htf

Outputs a per-symbol summary (console + markdown report) and a trades CSV.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from data import load_daily, parse_watchlist
from engine import SideParams, StrategyParams, run_backtest
from htf import HtfParams
from relative_strength import RsParams, benchmark_for, load_benchmarks, rs_frame
from supertrend_ai import SuperTrendParams

WARMUP_DAYS = 450  # calendar days of extra history so the MA/ATR are warm at start


def to_markdown_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    rows = [[("" if pd.isna(v) else str(v)) for v in rec] for rec in df.itertuples(index=False)]
    widths = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    fmt = lambda vals: "| " + " | ".join(v.ljust(w) for v, w in zip(vals, widths)) + " |"
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    return "\n".join([fmt(cols), sep] + [fmt(r) for r in rows])


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", required=True, help="Watchlist file (TradingView export or one ticker per line)")
    ap.add_argument("--start", default="2018-01-01", help="Backtest start date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="Backtest end date (default: today)")

    g = ap.add_argument_group("engine")
    g.add_argument("--engine", choices=["adaptive", "classic"], default="adaptive",
                   help="adaptive = k-means SuperTrend AI, classic = fixed factor")
    g.add_argument("--atr-length", type=int, default=10)
    g.add_argument("--classic-factor", type=float, default=3.0, help="classic engine only")
    g.add_argument("--min-mult", type=float, default=1.0, help="adaptive factor range min")
    g.add_argument("--max-mult", type=float, default=5.0, help="adaptive factor range max")
    g.add_argument("--step", type=float, default=0.5, help="adaptive factor step")
    g.add_argument("--perf-alpha", type=float, default=10.0)
    g.add_argument("--from-cluster", default="best", choices=["best", "average", "worst"])
    g.add_argument("--max-iter", type=int, default=1000)

    g = ap.add_argument_group("long side")
    g.add_argument("--no-long", dest="long_enabled", action="store_false", help="disable longs")
    g.add_argument("--long-ma-length", "--ma-length", dest="long_ma_length", type=int, default=200)
    g.add_argument("--long-ma-type", choices=["sma", "ema"], default="sma")
    g.add_argument("--long-min-strength", "--min-strength", dest="long_min_strength",
                   type=int, default=0, help="0-9, 0 = off")
    g.add_argument("--long-exit-below-ma", "--exit-below-ma", dest="long_ma_exit",
                   action="store_true", help="also exit longs on a cross under the MA")

    g = ap.add_argument_group("short side (independent parameters)")
    g.add_argument("--short", dest="short_enabled", action="store_true", help="enable shorts")
    g.add_argument("--short-ma-length", type=int, default=200)
    g.add_argument("--short-ma-type", choices=["sma", "ema"], default="sma")
    g.add_argument("--short-min-strength", type=int, default=0, help="0-9, 0 = off")
    g.add_argument("--short-exit-above-ma", dest="short_ma_exit", action="store_true",
                   help="also exit shorts on a cross over the MA")
    g.add_argument("--no-reverse", dest="allow_reverse", action="store_false",
                   help="a flip may not close one side and open the other on the same bar")

    g = ap.add_argument_group("higher-timeframe filter")
    g.add_argument("--no-htf", dest="htf_enabled", action="store_false", help="disable the HTF filter")
    g.add_argument("--htf", default="W", help="higher timeframe: D, W, M, 2W, 3M, 12M")
    g.add_argument("--no-htf-adx", dest="use_adx", action="store_false")
    g.add_argument("--adx-length", type=int, default=14)
    g.add_argument("--adx-smooth", type=int, default=14)
    g.add_argument("--adx-min", type=float, default=20.0)
    g.add_argument("--no-adx-di", dest="adx_need_di", action="store_false",
                   help="do not require DI+ > DI- for longs / DI- > DI+ for shorts")
    g.add_argument("--no-htf-mom", dest="use_mom", action="store_false")
    g.add_argument("--mom-mode", choices=["rsi", "roc", "macd"], default="rsi")
    g.add_argument("--rsi-length", type=int, default=14)
    g.add_argument("--rsi-long-min", type=float, default=50.0)
    g.add_argument("--rsi-short-max", type=float, default=50.0)
    g.add_argument("--roc-length", type=int, default=10)
    g.add_argument("--macd-fast", type=int, default=12)
    g.add_argument("--macd-slow", type=int, default=26)
    g.add_argument("--macd-signal", type=int, default=9)
    g.add_argument("--zero-long-min", type=float, default=0.0, help="ROC/MACD long threshold")
    g.add_argument("--zero-short-max", type=float, default=0.0, help="ROC/MACD short threshold")

    g = ap.add_argument_group("relative strength vs benchmark (DAX / SPY)")
    g.add_argument("--rs", dest="rs_enabled", action="store_true",
                   help="require relative strength vs the symbol's benchmark")
    g.add_argument("--rs-mode", choices=["ratio_ma", "roc_diff"], default="ratio_ma")
    g.add_argument("--rs-ma-length", type=int, default=50, help="ratio_ma: SMA of the RS ratio")
    g.add_argument("--rs-roc-length", type=int, default=60, help="roc_diff: lookback")
    g.add_argument("--rs-long-min", type=float, default=0.0, help="roc_diff: min outperformance (pts)")
    g.add_argument("--rs-short-max", type=float, default=0.0, help="roc_diff: max underperformance (pts)")
    g.add_argument("--benchmark-de", default="^GDAXI")
    g.add_argument("--benchmark-us", default="SPY")

    g = ap.add_argument_group("output")
    g.add_argument("--commission", type=float, default=0.1, help="commission per side in %%")
    g.add_argument("--cache-dir", default="data_cache")
    g.add_argument("--report", default="results/report.md")
    g.add_argument("--trades-csv", default="results/trades.csv")
    return ap


def describe(args) -> list[str]:
    """The settings block for the report — every knob that shaped these numbers."""
    if args.engine == "classic":
        eng = f"classic SuperTrend, ATR {args.atr_length}, factor {args.classic_factor}"
    else:
        eng = (f"adaptive k-means, ATR {args.atr_length}, factors "
               f"{args.min_mult}-{args.max_mult} step {args.step}, perf alpha "
               f"{args.perf_alpha}, cluster '{args.from_cluster}'")
    sides = []
    if args.long_enabled:
        sides.append(f"LONG (close > {args.long_ma_type.upper()}{args.long_ma_length}, "
                     f"min strength {args.long_min_strength}"
                     f"{', MA exit' if args.long_ma_exit else ''})")
    if args.short_enabled:
        sides.append(f"SHORT (close < {args.short_ma_type.upper()}{args.short_ma_length}, "
                     f"min strength {args.short_min_strength}"
                     f"{', MA exit' if args.short_ma_exit else ''})")
    if args.htf_enabled:
        parts = []
        if args.use_adx:
            parts.append(f"ADX({args.adx_length},{args.adx_smooth}) >= {args.adx_min}"
                         f"{' with DI agreement' if args.adx_need_di else ''}")
        if args.use_mom:
            if args.mom_mode == "rsi":
                parts.append(f"RSI({args.rsi_length}) >= {args.rsi_long_min} long "
                             f"/ <= {args.rsi_short_max} short")
            elif args.mom_mode == "roc":
                parts.append(f"ROC({args.roc_length}) >= {args.zero_long_min} long "
                             f"/ <= {args.zero_short_max} short")
            else:
                parts.append(f"MACD hist({args.macd_fast},{args.macd_slow},{args.macd_signal}) "
                             f">= {args.zero_long_min} long / <= {args.zero_short_max} short")
        htf = f"{args.htf} bars (closed only), " + " and ".join(parts) if parts else f"{args.htf} (nothing enabled)"
    else:
        htf = "off"
    return [
        f"- Engine: {eng}",
        f"- Sides: {' + '.join(sides) if sides else 'NONE ENABLED'}"
        f"{'' if args.allow_reverse else '  (stop-and-reverse off)'}",
        f"- Higher-timeframe filter: {htf}",
        (f"- Relative strength: {args.rs_mode} vs {args.benchmark_de} (German) / "
         f"{args.benchmark_us} (US)" + (f", MA{args.rs_ma_length}" if args.rs_mode == "ratio_ma"
          else f", ROC{args.rs_roc_length} >= {args.rs_long_min}")
         if args.rs_enabled else "- Relative strength: off"),
        f"- Commission: {args.commission}% per side, 100% of equity per trade",
    ]


def main() -> int:
    args = build_parser().parse_args()

    params = StrategyParams(
        st=SuperTrendParams(
            engine=args.engine, atr_length=args.atr_length,
            classic_factor=args.classic_factor, min_mult=args.min_mult,
            max_mult=args.max_mult, step=args.step, perf_alpha=args.perf_alpha,
            from_cluster=args.from_cluster, max_iter=args.max_iter),
        long=SideParams(enabled=args.long_enabled, ma_length=args.long_ma_length,
                        ma_type=args.long_ma_type, min_strength=args.long_min_strength,
                        ma_exit=args.long_ma_exit),
        short=SideParams(enabled=args.short_enabled, ma_length=args.short_ma_length,
                         ma_type=args.short_ma_type, min_strength=args.short_min_strength,
                         ma_exit=args.short_ma_exit),
        htf=HtfParams(
            enabled=args.htf_enabled, timeframe=args.htf, use_adx=args.use_adx,
            adx_length=args.adx_length, adx_smooth=args.adx_smooth,
            adx_min=args.adx_min, adx_need_di=args.adx_need_di,
            use_mom=args.use_mom, mom_mode=args.mom_mode, rsi_length=args.rsi_length,
            rsi_long_min=args.rsi_long_min, rsi_short_max=args.rsi_short_max,
            roc_length=args.roc_length, macd_fast=args.macd_fast,
            macd_slow=args.macd_slow, macd_signal=args.macd_signal,
            zero_long_min=args.zero_long_min, zero_short_max=args.zero_short_max),
        rs=RsParams(enabled=args.rs_enabled, mode=args.rs_mode,
                    ma_length=args.rs_ma_length, roc_length=args.rs_roc_length,
                    long_min=args.rs_long_min, short_max=args.rs_short_max,
                    benchmark_de=args.benchmark_de, benchmark_us=args.benchmark_us),
        allow_reverse=args.allow_reverse,
        commission_pct=args.commission)

    if not args.long_enabled and not args.short_enabled:
        print("Both sides are disabled - nothing to test.", file=sys.stderr)
        return 1
    try:
        params.htf.rule  # validate the timeframe before any downloads happen
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    tickers = parse_watchlist(args.watchlist)
    if not tickers:
        print(f"No tickers found in {args.watchlist}", file=sys.stderr)
        return 1
    print(f"Backtesting {len(tickers)} symbols from {args.watchlist} "
          f"({args.start} -> {args.end or 'today'})")
    for line in describe(args):
        print("  " + line[2:])
    print()

    trade_start = pd.Timestamp(args.start)
    dl_start = (trade_start - pd.Timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")
    benches = load_benchmarks(tickers, params.rs, load_daily, dl_start,
                              args.end, args.cache_dir) if args.rs_enabled else {}
    min_bars = max(args.long_ma_length if args.long_enabled else 0,
                   args.short_ma_length if args.short_enabled else 0) + 20

    summaries, all_trades = [], []
    for ticker in tickers:
        try:
            df = load_daily(ticker, dl_start, args.end, args.cache_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"  {ticker:12s} data error: {exc}")
            summaries.append({"ticker": ticker, "error": str(exc)})
            continue
        if df.empty or len(df) < min_bars:
            print(f"  {ticker:12s} skipped: not enough data ({len(df)} bars)")
            summaries.append({"ticker": ticker, "error": "insufficient data"})
            continue

        rf = None
        if args.rs_enabled:
            b = benches.get(benchmark_for(ticker, params.rs))
            if b is None or b.empty:
                print(f"  {ticker:12s} skipped: benchmark unavailable")
                summaries.append({"ticker": ticker, "error": "benchmark unavailable"})
                continue
            rf = rs_frame(df, b, params.rs)

        result = run_backtest(ticker, df, params, trade_start=trade_start, rs_frame=rf)
        s = result.summary()
        summaries.append(s)
        print(f"  {ticker:12s} trades={s['trades']:3d} (L{s['longs']}/S{s['shorts']})  "
              f"win={s['win_rate_pct']}%  PF={s['profit_factor']}  "
              f"strat={s['strategy_return_pct']}%  B&H={s['buy_hold_return_pct']}%  "
              f"maxDD={s['max_drawdown_pct']}%")

        for t in result.trades:
            all_trades.append({
                "ticker": ticker,
                "direction": t.direction,
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
    trades_df.to_csv(args.trades_csv, index=False, encoding="utf-8")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)

    ok = summary_df[summary_df.get("error", "").fillna("") == ""] if "error" in summary_df else summary_df
    lines = [
        "# SuperTrend MTF — Backtest Report",
        "",
        f"- Watchlist: `{args.watchlist}` ({len(tickers)} symbols)",
        f"- Window: {args.start} -> {args.end or 'today'} (daily bars)",
        *describe(args),
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
            f"- Closed trades: {int(ok['trades'].sum())} "
            f"({int(ok['longs'].sum())} long / {int(ok['shorts'].sum())} short)",
            "",
        ]
    Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {args.report}")
    print(f"Trades written to {args.trades_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
