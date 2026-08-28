"""Data loading: TradingView watchlist parsing + daily OHLC download with caching.

Supports the plain-text export TradingView produces via
Watchlist menu -> "Export list..." — comma-separated EXCHANGE:SYMBOL entries,
optionally with ###Section headers — as well as simple one-symbol-per-line
files using Yahoo Finance notation (AAPL, SAP.DE, ...).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

# TradingView exchange prefix -> Yahoo Finance suffix
_EXCHANGE_SUFFIX = {
    # US: no suffix
    "NASDAQ": "", "NYSE": "", "AMEX": "", "BATS": "", "OTC": "",
    "CBOE": "", "ARCA": "",
    # German venues -> XETRA feed on Yahoo
    "XETR": ".DE", "FWB": ".F", "GETTEX": ".DE", "TRADEGATE": ".DE",
    "SWB": ".SG", "HAM": ".HM", "DUS": ".DU", "MUN": ".MU", "BER": ".BE",
}


def parse_watchlist(path: str | Path) -> list[str]:
    """Return Yahoo-Finance-style tickers from a watchlist file."""
    text = Path(path).read_text()
    tickers: list[str] = []
    for chunk in re.split(r"[,\n]", text):
        item = chunk.strip()
        if not item or item.startswith("#"):
            continue
        if ":" in item:
            exchange, symbol = item.split(":", 1)
            suffix = _EXCHANGE_SUFFIX.get(exchange.upper())
            if suffix is None:
                # Unknown exchange: try the raw symbol
                tickers.append(symbol)
            else:
                tickers.append(symbol + suffix)
        else:
            tickers.append(item)
    # de-dupe, keep order
    seen: set[str] = set()
    out = []
    for t in tickers:
        if t.upper() not in seen:
            seen.add(t.upper())
            out.append(t)
    return out


def load_daily(ticker: str, start: str | None, end: str | None,
               cache_dir: str | Path = "data_cache") -> pd.DataFrame:
    """Daily OHLC for one ticker via yfinance, cached as CSV.

    Returns a DataFrame with columns Open, High, Low, Close, Volume and a
    DatetimeIndex, or an empty DataFrame on failure.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = ticker.replace("/", "_").replace("^", "_")
    cache_file = cache_dir / f"{safe}.csv"

    if cache_file.exists():
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
    else:
        import yfinance as yf
        df = yf.download(ticker, start=start, end=end, interval="1d",
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        df.to_csv(cache_file)

    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df.dropna(subset=["High", "Low", "Close"])
