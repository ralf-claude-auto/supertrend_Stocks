"""Daily relative strength against a benchmark.

German listings are measured against the DAX, US listings against SPY. This
replaces the higher-timeframe ADX/momentum filter, which the 2026-08-30 grid
found did not earn its place (see FINDINGS.md section 2).

Two modes:

  ratio_ma   RS ratio = close / benchmark close. Long needs the ratio ABOVE its
             own moving average, i.e. the stock is outperforming its benchmark
             relative to its own recent norm. This is the Mansfield-style
             reading and is the default: it is scale-free and reacts to a change
             in leadership rather than to the absolute size of a move.

  roc_diff   Stock ROC(n) minus benchmark ROC(n), in percentage points. Simpler
             and directly comparable across symbols, which makes it the useful
             one for RANKING a watchlist.

Both are computed on the daily bars — no resampling, so nothing here can repaint.
The benchmark is reindexed onto the stock's own calendar with a forward fill,
because German and US sessions differ on holidays; a missing benchmark day uses
the last close that had actually printed, never a later one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Yahoo suffix -> benchmark. Bare tickers (no dot) are US.
_GERMAN_SUFFIXES = (".DE", ".F", ".SG", ".HM", ".DU", ".MU", ".BE")


@dataclass
class RsParams:
    enabled: bool = True
    mode: str = "ratio_ma"          # ratio_ma | roc_diff
    ma_length: int = 50             # ratio_ma: SMA length of the RS ratio
    roc_length: int = 60            # roc_diff: lookback on both legs
    long_min: float = 0.0           # roc_diff: required outperformance, in points
    short_max: float = 0.0          # roc_diff: required underperformance
    benchmark_de: str = "^GDAXI"
    benchmark_us: str = "SPY"
    benchmark_other: str = "SPY"    # anything that is neither German nor bare-US


def benchmark_for(ticker: str, p: RsParams) -> str:
    """Which index this symbol is judged against."""
    t = ticker.upper()
    if t.endswith(_GERMAN_SUFFIXES):
        return p.benchmark_de
    if "." not in t:
        return p.benchmark_us
    return p.benchmark_other


def align_benchmark(bench: pd.DataFrame, index: pd.Index) -> pd.Series:
    """Benchmark closes on the stock's own trading calendar.

    Forward fill only: on a day the benchmark did not trade, the most recent
    printed close is used. Never interpolates forward from a later bar.
    """
    return bench["Close"].reindex(index.union(bench.index)).ffill().reindex(index)


def rs_frame(df: pd.DataFrame, bench: pd.DataFrame, p: RsParams) -> pd.DataFrame:
    """Per-bar RS columns: rs, rs_ref, rs_diff, ok_long, ok_short.

    rs_diff is always populated (stock ROC minus benchmark ROC over roc_length)
    so a watchlist can be RANKED even when the gating mode is ratio_ma.
    """
    idx = df.index
    close = df["Close"]
    bclose = align_benchmark(bench, idx)

    ratio = close / bclose
    ratio_ma = ratio.rolling(p.ma_length).mean()
    roc_s = (close / close.shift(p.roc_length) - 1.0) * 100.0
    roc_b = (bclose / bclose.shift(p.roc_length) - 1.0) * 100.0
    diff = roc_s - roc_b

    out = pd.DataFrame({
        "rs": ratio,
        "rs_ref": ratio_ma,
        "rs_diff": diff,
        "bench_close": bclose,
    }, index=idx)

    if not p.enabled:
        out["ok_long"] = True
        out["ok_short"] = True
        return out

    if p.mode == "ratio_ma":
        out["ok_long"] = ratio > ratio_ma
        out["ok_short"] = ratio < ratio_ma
    elif p.mode == "roc_diff":
        out["ok_long"] = diff >= p.long_min
        out["ok_short"] = diff <= p.short_max
    else:
        raise ValueError(f"unknown RS mode {p.mode!r} (ratio_ma | roc_diff)")

    # NaN during warmup compares False, which blocks entries until RS is defined.
    out["ok_long"] = out["ok_long"].fillna(False)
    out["ok_short"] = out["ok_short"].fillna(False)
    return out


def load_benchmarks(tickers: list[str], p: RsParams, load, start, end, cache_dir) -> dict:
    """Download/cache every benchmark the given tickers need, once each."""
    wanted = sorted({benchmark_for(t, p) for t in tickers})
    out = {}
    for b in wanted:
        try:
            d = load(b, start, end, cache_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"  warning: benchmark {b} failed to load ({exc}) - "
                  f"symbols using it will be skipped")
            d = pd.DataFrame()
        if d.empty:
            print(f"  warning: benchmark {b} returned no data - "
                  f"symbols using it will be skipped")
        out[b] = d
    return out
