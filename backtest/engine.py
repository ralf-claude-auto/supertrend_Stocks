"""Backtest engine — long and short, signal-on-close execution.

Mirrors pine/supertrend_mtf_strategy.pine (process_orders_on_close = true):

  LONG   SuperTrend flips bullish  AND close > long MA   AND strength >= min
         AND the higher-timeframe filter passes for longs
  SHORT  SuperTrend flips bearish  AND close < short MA  AND strength >= min
         AND the higher-timeframe filter passes for shorts

Long and short carry independent parameters. Exits are evaluated before entries
on the same bar, so a flip can close one side and open the other when
allow_reverse is set — the Pine "Stop-and-reverse" input.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from htf import HtfParams, htf_filter
from relative_strength import RsParams
from supertrend_ai import SuperTrendParams, supertrend


@dataclass
class SideParams:
    """One side of the strategy. Long and short each get their own."""
    enabled: bool = True
    ma_length: int = 200
    ma_type: str = "sma"       # sma | ema
    min_strength: int = 0      # 0-9, 0 = off
    ma_exit: bool = False      # long: exit on cross under MA; short: cross over


@dataclass
class StrategyParams:
    st: SuperTrendParams = field(default_factory=SuperTrendParams)
    long: SideParams = field(default_factory=lambda: SideParams(enabled=True))
    short: SideParams = field(default_factory=lambda: SideParams(enabled=False))
    htf: HtfParams = field(default_factory=HtfParams)
    # Relative strength vs a benchmark. rs_frame must be supplied by the caller
    # when enabled - the engine cannot download the benchmark itself.
    rs: RsParams = field(default_factory=lambda: RsParams(enabled=False))
    allow_reverse: bool = True
    commission_pct: float = 0.1  # per side, in percent


@dataclass
class Trade:
    entry_date: pd.Timestamp
    entry_price: float
    direction: str = "long"       # long | short
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    strength: int = 0

    @property
    def return_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        if self.direction == "long":
            return (self.exit_price / self.entry_price - 1.0) * 100.0
        # Short: profit when price falls, measured on the position's notional.
        return (self.entry_price - self.exit_price) / self.entry_price * 100.0


@dataclass
class BacktestResult:
    ticker: str
    trades: list[Trade]
    equity: pd.Series
    buy_hold_return_pct: float
    error: str = ""

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if t.exit_price is not None]

    def summary(self) -> dict:
        closed = self.closed
        rets = np.array([t.return_pct for t in closed]) if closed else np.array([])
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        total_return = (self.equity.iloc[-1] / self.equity.iloc[0] - 1) * 100 if len(self.equity) else np.nan
        dd = (self.equity / self.equity.cummax() - 1).min() * 100 if len(self.equity) else np.nan
        gross_win = wins.sum() if wins.size else 0.0
        gross_loss = -losses.sum() if losses.size else 0.0
        return {
            "ticker": self.ticker,
            "trades": len(closed),
            "longs": sum(1 for t in closed if t.direction == "long"),
            "shorts": sum(1 for t in closed if t.direction == "short"),
            "open_trade": any(t.exit_price is None for t in self.trades),
            "win_rate_pct": round(100 * wins.size / rets.size, 1) if rets.size else np.nan,
            "avg_trade_pct": round(rets.mean(), 2) if rets.size else np.nan,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (np.inf if gross_win > 0 else np.nan),
            "strategy_return_pct": round(total_return, 1),
            "buy_hold_return_pct": round(self.buy_hold_return_pct, 1),
            "max_drawdown_pct": round(dd, 1),
            "error": self.error,
        }


def _ma(close: pd.Series, length: int, kind: str) -> pd.Series:
    if kind == "ema":
        return close.ewm(span=length, adjust=False, min_periods=length).mean()
    return close.rolling(length).mean()


def run_backtest(ticker: str, df: pd.DataFrame, params: StrategyParams,
                 trade_start: pd.Timestamp | None = None,
                 st_result=None, htf_frame: pd.DataFrame | None = None,
                 rs_frame: pd.DataFrame | None = None) -> BacktestResult:
    """Run the strategy on daily OHLC data.

    df should include warmup history before trade_start; trades are only taken
    from trade_start onward.

    st_result / htf_frame let a caller pass in an already-computed SuperTrend or
    HTF filter. Neither depends on the side settings, so a grid search over many
    configurations computes each once per symbol instead of once per run. They
    MUST correspond to params.st / params.htf — nothing here re-validates that.
    """
    res = supertrend(df, params.st) if st_result is None else st_result
    close = df["Close"]
    strength = res.signal_strength

    ma_long = _ma(close, params.long.ma_length, params.long.ma_type)
    ma_short = _ma(close, params.short.ma_length, params.short.ma_type)
    htf = htf_filter(df, params.htf) if htf_frame is None else htf_frame

    if params.rs.enabled:
        if rs_frame is None:
            raise ValueError("params.rs.enabled but no rs_frame supplied - "
                             "the caller must load the benchmark and pass it in")
        rs_long, rs_short = rs_frame["ok_long"], rs_frame["ok_short"]
    else:
        rs_long = rs_short = pd.Series(True, index=df.index)

    long_sig = (res.buy & (close > ma_long)
                & (strength >= params.long.min_strength)
                & htf["ok_long"] & rs_long) \
        if params.long.enabled else pd.Series(False, index=df.index)
    short_sig = (res.sell & (close < ma_short)
                 & (strength >= params.short.min_strength)
                 & htf["ok_short"] & rs_short) \
        if params.short.enabled else pd.Series(False, index=df.index)

    cross_under = (close < ma_long) & (close.shift(1) >= ma_long.shift(1))
    cross_over = (close > ma_short) & (close.shift(1) <= ma_short.shift(1))
    long_ma_exit = cross_under if params.long.ma_exit else pd.Series(False, index=df.index)
    short_ma_exit = cross_over if params.short.ma_exit else pd.Series(False, index=df.index)

    in_window = (df.index >= trade_start) if trade_start is not None \
        else np.ones(len(df), dtype=bool)

    fee = params.commission_pct / 100.0
    trades: list[Trade] = []
    position: Trade | None = None
    equity: list[float] = []
    eq = 1.0
    idx = df.index

    def mark(price: float) -> float:
        """Equity including the open position's mark-to-market."""
        if position is None:
            return eq
        if position.direction == "long":
            return eq * (price / position.entry_price)
        # A 100%-of-equity short: 1 + (entry - price)/entry. Floored at zero —
        # a short that more than doubles against you is a wipeout, not negative
        # equity.
        return eq * max(2.0 - price / position.entry_price, 0.0)

    for i in range(len(df)):
        c = close.iloc[i]
        closed_this_bar = False

        if position is not None:
            if position.direction == "long":
                hit = bool(res.sell.iloc[i]) or bool(long_ma_exit.iloc[i])
                reason = "ST flip" if bool(res.sell.iloc[i]) else "below MA"
            else:
                hit = bool(res.buy.iloc[i]) or bool(short_ma_exit.iloc[i])
                reason = "ST flip" if bool(res.buy.iloc[i]) else "above MA"
            if hit:
                position.exit_date = idx[i]
                position.exit_price = c
                position.exit_reason = reason
                eq = mark(c) * (1 - fee)
                trades.append(position)
                position = None
                closed_this_bar = True

        if position is None and in_window[i] and not (closed_this_bar and not params.allow_reverse):
            if bool(long_sig.iloc[i]) and not np.isnan(ma_long.iloc[i]):
                position = Trade(entry_date=idx[i], entry_price=c, direction="long",
                                 strength=int(strength.iloc[i]))
                eq *= (1 - fee)
            elif bool(short_sig.iloc[i]) and not np.isnan(ma_short.iloc[i]):
                position = Trade(entry_date=idx[i], entry_price=c, direction="short",
                                 strength=int(strength.iloc[i]))
                eq *= (1 - fee)

        equity.append(mark(c))

    if position is not None:
        trades.append(position)  # still open

    equity_s = pd.Series(equity, index=idx)
    if trade_start is not None:
        equity_s = equity_s[equity_s.index >= trade_start]
        window_close = close[close.index >= trade_start]
    else:
        window_close = close
    bh = (window_close.iloc[-1] / window_close.iloc[0] - 1) * 100 if len(window_close) else np.nan

    return BacktestResult(ticker=ticker, trades=trades, equity=equity_s,
                          buy_hold_return_pct=bh)
