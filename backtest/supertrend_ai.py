"""SuperTrend AI (k-means clustering) — Python port of the strategy logic.

Mirrors the Pine Script in pine/supertrend_ai_200ma_strategy.pine:
a bank of SuperTrends with factors from min_mult to max_mult is scored by
an exponentially weighted directional performance measure; each bar the
scores are clustered with k-means (k=3) and the mean factor of the chosen
cluster drives the live SuperTrend.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class SuperTrendParams:
    engine: str = "adaptive"      # adaptive | classic
    atr_length: int = 10
    classic_factor: float = 3.0   # engine="classic" only
    min_mult: float = 1.0
    max_mult: float = 5.0
    step: float = 0.5
    perf_alpha: float = 10.0
    from_cluster: str = "best"  # best | average | worst
    max_iter: int = 1000

    @property
    def factors(self) -> np.ndarray:
        n = int(round((self.max_mult - self.min_mult) / self.step)) + 1
        return self.min_mult + self.step * np.arange(n)


# Kept so older callers/scripts importing the previous name still work.
SuperTrendAIParams = SuperTrendParams


@dataclass
class SuperTrendAIResult:
    trend: pd.Series          # 1 bullish / 0 bearish (adaptive supertrend)
    trailing_stop: pd.Series  # the supertrend line
    target_factor: pd.Series  # factor chosen by clustering per bar
    signal_strength: pd.Series  # int 0..9 (perf index * 10)
    buy: pd.Series            # bool, trend flip 0 -> 1
    sell: pd.Series           # bool, trend flip 1 -> 0


def _rma(values: np.ndarray, length: int) -> np.ndarray:
    """Wilder's smoothing, as used by Pine's ta.atr."""
    out = np.full_like(values, np.nan, dtype=float)
    alpha = 1.0 / length
    prev = np.nan
    started = False
    running = 0.0
    count = 0
    for i, v in enumerate(values):
        if np.isnan(v):
            out[i] = prev if started else np.nan
            continue
        if not started:
            running += v
            count += 1
            if count == length:
                prev = running / length
                out[i] = prev
                started = True
        else:
            prev = alpha * v + (1 - alpha) * prev
            out[i] = prev
    return out


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    prev_close = np.concatenate(([np.nan], close[:-1]))
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]
    return _rma(tr, length)


def _ema(values: np.ndarray, length: int) -> np.ndarray:
    out = np.full_like(values, np.nan, dtype=float)
    alpha = 2.0 / (length + 1)
    prev = np.nan
    for i, v in enumerate(values):
        if np.isnan(v):
            out[i] = prev
            continue
        prev = v if np.isnan(prev) else alpha * v + (1 - alpha) * prev
        out[i] = prev
    return out


def _kmeans_1d(perfs: np.ndarray, factors: np.ndarray, max_iter: int):
    """3-cluster 1-D k-means seeded at the 25/50/75 percentiles.

    Returns (cluster_factor_means, cluster_perf_means) ordered worst->best,
    entries are np.nan for empty clusters.
    """
    centroids = np.percentile(perfs, [25, 50, 75])
    assign = None
    for _ in range(max_iter):
        dist = np.abs(perfs[:, None] - centroids[None, :])
        new_assign = np.argmin(dist, axis=1)
        if assign is not None and np.array_equal(new_assign, assign):
            break
        assign = new_assign
        for j in range(3):
            members = perfs[assign == j]
            if members.size:
                centroids[j] = members.mean()

    factor_means = np.full(3, np.nan)
    perf_means = np.full(3, np.nan)
    for j in range(3):
        mask = assign == j
        if mask.any():
            factor_means[j] = factors[mask].mean()
            perf_means[j] = perfs[mask].mean()
    return factor_means, perf_means


def _classic_supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                        atr: np.ndarray, factor: float):
    """Pine's ta.supertrend, step for step.

    Returns (line, direction) where direction is -1 in an uptrend and +1 in a
    downtrend — the same convention ta.supertrend uses, which the Pine strategy
    then normalises to os = 1 bullish / 0 bearish.

    Note this band logic is NOT the same as the simpler trailing rule the
    adaptive factor bank below uses; it is reproduced faithfully so the Classic
    engine matches what TradingView draws.
    """
    n = len(close)
    hl2 = (high + low) / 2.0
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    line = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)

    for i in range(n):
        if np.isnan(atr[i]):
            continue
        ub = hl2[i] + factor * atr[i]
        lb = hl2[i] - factor * atr[i]
        prev_upper = upper[i - 1] if i > 0 and not np.isnan(upper[i - 1]) else 0.0
        prev_lower = lower[i - 1] if i > 0 and not np.isnan(lower[i - 1]) else 0.0
        c1 = close[i - 1] if i > 0 else np.nan

        lower[i] = lb if (lb > prev_lower or (not np.isnan(c1) and c1 < prev_lower)) else prev_lower
        upper[i] = ub if (ub < prev_upper or (not np.isnan(c1) and c1 > prev_upper)) else prev_upper

        prev_line = line[i - 1] if i > 0 else np.nan
        if i == 0 or np.isnan(atr[i - 1]):
            direction[i] = 1
        elif not np.isnan(prev_line) and prev_line == prev_upper:
            direction[i] = -1 if close[i] > upper[i] else 1
        else:
            direction[i] = 1 if close[i] < lower[i] else -1
        line[i] = lower[i] if direction[i] == -1 else upper[i]

    return line, direction


def supertrend_classic(df: pd.DataFrame, p: SuperTrendParams) -> SuperTrendAIResult:
    """Classic SuperTrend at a fixed factor, with the SAME 0-9 signal strength.

    The strength is the identical exponentially weighted directional performance
    index the adaptive engine publishes, just computed on the single classic
    line — so `--long-min-strength` means the same thing on both engines and the
    two are directly comparable.
    """
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    n = len(df)

    atr = _atr(high, low, close, p.atr_length)
    line, direction = _classic_supertrend(high, low, close, atr, p.classic_factor)

    denom = _ema(np.abs(np.diff(close, prepend=np.nan)), int(p.perf_alpha))
    alpha_perf = 2.0 / (p.perf_alpha + 1.0)
    perf = 0.0
    perf_idx = np.full(n, np.nan)
    for i in range(n):
        c1 = close[i - 1] if i > 0 else np.nan
        l1 = line[i - 1] if i > 0 else np.nan
        diff = 0.0 if (np.isnan(c1) or np.isnan(l1)) else np.sign(c1 - l1)
        ret = (close[i] - c1) if not np.isnan(c1) else 0.0
        perf += alpha_perf * (ret * diff - perf)
        if not np.isnan(denom[i]) and denom[i]:
            perf_idx[i] = max(perf, 0.0) / denom[i]

    os_arr = np.where(direction < 0, 1, 0)
    os_s = pd.Series(os_arr, index=df.index)
    strength = pd.Series(np.nan_to_num(perf_idx * 10).astype(int), index=df.index).clip(0, 9)
    return SuperTrendAIResult(
        trend=os_s,
        trailing_stop=pd.Series(line, index=df.index),
        target_factor=pd.Series(p.classic_factor, index=df.index),
        signal_strength=strength,
        buy=(os_s == 1) & (os_s.shift(1) == 0),
        sell=(os_s == 0) & (os_s.shift(1) == 1),
    )


def supertrend(df: pd.DataFrame, p: SuperTrendParams) -> SuperTrendAIResult:
    """Dispatch to the configured engine."""
    if p.engine == "classic":
        return supertrend_classic(df, p)
    if p.engine == "adaptive":
        return supertrend_ai(df, p)
    raise ValueError(f"unknown engine {p.engine!r} (adaptive | classic)")


def supertrend_ai(df: pd.DataFrame, params: SuperTrendParams | None = None) -> SuperTrendAIResult:
    """Compute the adaptive SuperTrend on OHLC daily data.

    df needs columns: High, Low, Close (index = dates, ascending).
    """
    p = params or SuperTrendAIParams()
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    n = len(df)
    hl2 = (high + low) / 2.0

    atr = _atr(high, low, close, p.atr_length)
    factors = p.factors
    nf = len(factors)

    # Per-factor supertrend state
    uppers = np.full(nf, np.nan)
    lowers = np.full(nf, np.nan)
    outputs = np.full(nf, np.nan)
    trends = np.zeros(nf, dtype=int)
    perfs = np.zeros(nf)

    cluster_idx = {"worst": 0, "average": 1, "best": 2}[p.from_cluster.lower()]
    denom = _ema(np.abs(np.diff(close, prepend=np.nan)), int(p.perf_alpha))

    target_factor = np.full(n, np.nan)
    perf_idx_arr = np.full(n, np.nan)
    os_arr = np.zeros(n, dtype=int)
    ts_arr = np.full(n, np.nan)

    a_upper = np.nan
    a_lower = np.nan
    a_os = 0
    alpha_perf = 2.0 / (p.perf_alpha + 1.0)

    for i in range(n):
        if np.isnan(atr[i]):
            continue
        c = close[i]
        c1 = close[i - 1] if i > 0 else np.nan

        # --- update factor bank ---
        ups = hl2[i] + atr[i] * factors
        dns = hl2[i] - atr[i] * factors
        for k in range(nf):
            trends[k] = 1 if (not np.isnan(uppers[k]) and c > uppers[k]) else (
                0 if (not np.isnan(lowers[k]) and c < lowers[k]) else trends[k])
            uppers[k] = min(ups[k], uppers[k]) if (not np.isnan(c1) and not np.isnan(uppers[k]) and c1 < uppers[k]) else ups[k]
            lowers[k] = max(dns[k], lowers[k]) if (not np.isnan(c1) and not np.isnan(lowers[k]) and c1 > lowers[k]) else dns[k]
            diff = 0.0
            if not np.isnan(c1) and not np.isnan(outputs[k]):
                diff = np.sign(c1 - outputs[k])
            ret = (c - c1) if not np.isnan(c1) else 0.0
            perfs[k] += alpha_perf * (ret * diff - perfs[k])
            outputs[k] = lowers[k] if trends[k] == 1 else uppers[k]

        # --- k-means over factor performances ---
        factor_means, perf_means = _kmeans_1d(perfs, factors, p.max_iter)
        tf = factor_means[cluster_idx]
        if np.isnan(tf):
            tf = target_factor[i - 1] if i > 0 else np.nan
        target_factor[i] = tf
        if not np.isnan(perf_means[cluster_idx]) and denom[i] and not np.isnan(denom[i]):
            perf_idx_arr[i] = max(perf_means[cluster_idx], 0.0) / denom[i]

        # --- adaptive supertrend with clustered factor ---
        if np.isnan(tf):
            continue
        up = hl2[i] + atr[i] * tf
        dn = hl2[i] - atr[i] * tf
        a_upper = min(up, a_upper) if (not np.isnan(c1) and not np.isnan(a_upper) and c1 < a_upper) else up
        a_lower = max(dn, a_lower) if (not np.isnan(c1) and not np.isnan(a_lower) and c1 > a_lower) else dn
        a_os = 1 if c > a_upper else (0 if c < a_lower else a_os)
        os_arr[i] = a_os
        ts_arr[i] = a_lower if a_os == 1 else a_upper

    os_s = pd.Series(os_arr, index=df.index)
    strength = pd.Series(np.nan_to_num(perf_idx_arr * 10).astype(int), index=df.index).clip(0, 9)
    # Raw flips only. The strength filter moved to the engine, because long and
    # short now carry their own minimum and it must not be baked in here.
    buy = (os_s == 1) & (os_s.shift(1) == 0)
    sell = (os_s == 0) & (os_s.shift(1) == 1)

    return SuperTrendAIResult(
        trend=os_s,
        trailing_stop=pd.Series(ts_arr, index=df.index),
        target_factor=pd.Series(target_factor, index=df.index),
        signal_strength=strength,
        buy=buy,
        sell=sell,
    )
