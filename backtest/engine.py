"""Backtest engine: long-only, signal-on-close execution (mirrors the Pine
strategy's process_orders_on_close=true behaviour).

Rules:
  BUY  : SuperTrend AI flips bullish AND close > SMA(200)
  SELL : SuperTrend AI flips bearish (optionally also close crossing under SMA)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from supertrend_ai import SuperTrendAIParams, supertrend_ai


@dataclass
class StrategyParams:
    st: SuperTrendAIParams = field(default_factory=SuperTrendAIParams)
    ma_length: int = 200
    exit_below_ma: bool = False
    commission_pct: float = 0.1  # per side, in percent


@dataclass
class Trade:
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    strength: int = 0

    @property
    def return_pct(self) -> float | None:
        if self.exit_price is None:
            return None
        return (self.exit_price / self.entry_price - 1.0) * 100.0


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
        # Max drawdown on equity
        if len(self.equity):
            dd = (self.equity / self.equity.cummax() - 1).min() * 100
        else:
            dd = np.nan
        gross_win = wins.sum() if wins.size else 0.0
        gross_loss = -losses.sum() if losses.size else 0.0
        return {
            "ticker": self.ticker,
            "trades": len(closed),
            "open_trade": any(t.exit_price is None for t in self.trades),
            "win_rate_pct": round(100 * wins.size / rets.size, 1) if rets.size else np.nan,
            "avg_trade_pct": round(rets.mean(), 2) if rets.size else np.nan,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (np.inf if gross_win > 0 else np.nan),
            "strategy_return_pct": round(total_return, 1),
            "buy_hold_return_pct": round(self.buy_hold_return_pct, 1),
            "max_drawdown_pct": round(dd, 1),
            "error": self.error,
        }


def run_backtest(ticker: str, df: pd.DataFrame, params: StrategyParams,
                 trade_start: pd.Timestamp | None = None) -> BacktestResult:
    """Run the strategy on daily OHLC data.

    df should include warmup history before trade_start; trades are only
    taken from trade_start onward.
    """
    res = supertrend_ai(df, params.st)
    close = df["Close"]
    ma = close.rolling(params.ma_length).mean()

    buy = res.buy & (close > ma)
    sell = res.sell.copy()
    if params.exit_below_ma:
        cross_under = (close < ma) & (close.shift(1) >= ma.shift(1))
        sell = sell | cross_under

    if trade_start is not None:
        in_window = df.index >= trade_start
    else:
        in_window = np.ones(len(df), dtype=bool)

    fee = params.commission_pct / 100.0
    trades: list[Trade] = []
    position: Trade | None = None
    equity = []
    eq = 1.0
    entry_close = np.nan

    idx = df.index
    for i in range(len(df)):
        c = close.iloc[i]
        if position is None:
            if bool(buy.iloc[i]) and in_window[i] and not np.isnan(ma.iloc[i]):
                position = Trade(entry_date=idx[i], entry_price=c,
                                 strength=int(res.signal_strength.iloc[i]))
                entry_close = c
                eq *= (1 - fee)
        else:
            if bool(sell.iloc[i]):
                position.exit_date = idx[i]
                position.exit_price = c
                position.exit_reason = "ST flip" if bool(res.sell.iloc[i]) else "below MA"
                trades.append(position)
                eq *= (c / entry_close) * (1 - fee)
                position = None
                entry_close = np.nan
            # mark-to-market handled below
        if position is not None and not np.isnan(entry_close):
            equity.append(eq * (c / entry_close))
        else:
            equity.append(eq)

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
