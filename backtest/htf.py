"""Higher-timeframe trend-strength and momentum filter.

Mirrors the HTF block of pine/supertrend_mtf_strategy.pine: ADX/DI for trend
strength and RSI / ROC / MACD-histogram for momentum, computed on a higher
timeframe and mapped back onto the daily bars.

Non-repainting by construction
------------------------------
The Pine script defaults to `Use only CLOSED higher-timeframe bars`, i.e.
`request.security(..., expr[1], lookahead_off)`. The equivalent here: each HTF
bar is labelled with its period END, and a daily bar may only see HTF labels
STRICTLY earlier than itself. So during the current week you see last week's
closed reading, never the one the week is still forming — which is exactly the
value that would not have been knowable at the time.

The forming-bar mode (`htfConfirm = false` in Pine) is deliberately NOT
implemented: reproducing it in a batch backtest means letting a bar see an
aggregate its own future contributed to, which is the classic repaint. Ask for
it and you get the confirmed behaviour plus a warning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Pine timeframe string -> pandas resample rule
_TF_RULE = {
    "D": "D",
    "W": "W",
    "M": "ME",
    "2W": "2W",
    "3M": "QE",
    "12M": "YE",
}


@dataclass
class HtfParams:
    enabled: bool = True
    timeframe: str = "W"
    confirmed: bool = True

    use_adx: bool = True
    adx_length: int = 14
    adx_smooth: int = 14
    adx_min: float = 20.0
    adx_need_di: bool = True

    use_mom: bool = True
    mom_mode: str = "rsi"  # rsi | roc | macd
    rsi_length: int = 14
    rsi_long_min: float = 50.0
    rsi_short_max: float = 50.0
    roc_length: int = 10
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    zero_long_min: float = 0.0
    zero_short_max: float = 0.0

    @property
    def rule(self) -> str:
        tf = self.timeframe.strip().upper()
        if tf not in _TF_RULE:
            raise ValueError(
                f"unsupported higher timeframe {self.timeframe!r} - "
                f"use one of {sorted(_TF_RULE)}")
        return _TF_RULE[tf]

    @property
    def mom_long_min(self) -> float:
        return self.rsi_long_min if self.mom_mode == "rsi" else self.zero_long_min

    @property
    def mom_short_max(self) -> float:
        return self.rsi_short_max if self.mom_mode == "rsi" else self.zero_short_max


def _rma(s: pd.Series, length: int) -> pd.Series:
    """Wilder's smoothing — Pine's ta.rma."""
    return s.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _true_range(h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = (h.iloc[0] - l.iloc[0]) if len(h) else np.nan
    return tr


def adx_di(h: pd.Series, l: pd.Series, c: pd.Series, length: int, smooth: int):
    """ADX, DI+ and DI- exactly as the Pine f_adx() helper computes them."""
    up = h.diff()
    down = -l.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    plus_dm = pd.Series(plus_dm, index=h.index)
    minus_dm = pd.Series(minus_dm, index=h.index)

    trur = _rma(_true_range(h, l, c), length)
    plus = 100 * _rma(plus_dm, length) / trur
    minus = 100 * _rma(minus_dm, length) / trur
    total = plus + minus
    adx = 100 * _rma((plus - minus).abs() / total.where(total != 0, 1.0), smooth)
    return adx, plus, minus


def rsi(c: pd.Series, length: int) -> pd.Series:
    delta = c.diff()
    gain = _rma(delta.clip(lower=0), length)
    loss = _rma((-delta).clip(lower=0), length)
    rs = gain / loss
    return 100 - 100 / (1 + rs)


def roc(c: pd.Series, length: int) -> pd.Series:
    return (c / c.shift(length) - 1.0) * 100.0


def macd_hist(c: pd.Series, fast: int, slow: int, signal: int) -> pd.Series:
    ema_f = c.ewm(span=fast, adjust=False).mean()
    ema_s = c.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    return macd - macd.ewm(span=signal, adjust=False).mean()


def resample_htf(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate daily OHLC into higher-timeframe bars labelled by period END."""
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    cols = {k: v for k, v in agg.items() if k in df.columns}
    out = df.resample(rule, label="right", closed="right").agg(cols)
    return out.dropna(subset=[c for c in ("High", "Low", "Close") if c in out])


def _map_back(htf_values: pd.DataFrame, daily_index: pd.Index) -> pd.DataFrame:
    """Project HTF values onto daily bars, seeing only STRICTLY earlier labels.

    Using searchsorted(side="left") gives, for each daily date, the count of HTF
    labels before it — so `pos` indexes the last label that had already closed.
    A plain reindex(method="ffill") would instead let a daily bar read an HTF bar
    labelled with that same date, which on a daily HTF is same-bar lookahead.
    """
    if htf_values.empty:
        return pd.DataFrame(np.nan, index=daily_index, columns=htf_values.columns)
    pos = htf_values.index.searchsorted(daily_index, side="left") - 1
    arr = htf_values.to_numpy(dtype=float)
    out = np.full((len(daily_index), arr.shape[1]), np.nan)
    valid = pos >= 0
    out[valid] = arr[pos[valid]]
    return pd.DataFrame(out, index=daily_index, columns=htf_values.columns)


def htf_filter(df: pd.DataFrame, p: HtfParams) -> pd.DataFrame:
    """Return per-daily-bar columns: adx, di_plus, di_minus, mom, ok_long, ok_short."""
    idx = df.index
    if not p.enabled:
        ones = pd.Series(True, index=idx)
        return pd.DataFrame({
            "adx": np.nan, "di_plus": np.nan, "di_minus": np.nan, "mom": np.nan,
            "ok_long": ones, "ok_short": ones,
        }, index=idx)

    if not p.confirmed:
        print("  warning: htf confirmed=False is not supported in the batch "
              "backtest (it would repaint) - using closed HTF bars instead")

    h = resample_htf(df, p.rule)
    adx, di_p, di_m = adx_di(h["High"], h["Low"], h["Close"], p.adx_length, p.adx_smooth)

    if p.mom_mode == "rsi":
        mom = rsi(h["Close"], p.rsi_length)
    elif p.mom_mode == "roc":
        mom = roc(h["Close"], p.roc_length)
    elif p.mom_mode == "macd":
        mom = macd_hist(h["Close"], p.macd_fast, p.macd_slow, p.macd_signal)
    else:
        raise ValueError(f"unknown momentum mode {p.mom_mode!r} (rsi | roc | macd)")

    vals = _map_back(pd.DataFrame({"adx": adx, "di_plus": di_p,
                                   "di_minus": di_m, "mom": mom}), idx)

    # NaN during HTF warmup compares False everywhere, which blocks entries —
    # the same effect Pine's nz()/na() guards have.
    if p.use_adx:
        adx_ok = vals["adx"] >= p.adx_min
        adx_long = adx_ok & ((vals["di_plus"] > vals["di_minus"]) if p.adx_need_di else True)
        adx_short = adx_ok & ((vals["di_minus"] > vals["di_plus"]) if p.adx_need_di else True)
    else:
        adx_long = adx_short = pd.Series(True, index=idx)

    if p.use_mom:
        mom_long = vals["mom"] >= p.mom_long_min
        mom_short = vals["mom"] <= p.mom_short_max
    else:
        mom_long = mom_short = pd.Series(True, index=idx)

    vals["ok_long"] = adx_long & mom_long
    vals["ok_short"] = adx_short & mom_short
    return vals
