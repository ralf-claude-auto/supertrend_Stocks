"""Data loading: TradingView watchlist parsing + daily OHLC download with caching.

Supports the plain-text export TradingView produces via
Watchlist menu -> "Export list..." — comma-separated EXCHANGE:SYMBOL entries,
optionally with ###Section headers — as well as simple one-symbol-per-line
files using Yahoo Finance notation (AAPL, SAP.DE, ...).
"""

from __future__ import annotations

import json
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
    # Euronext spans Amsterdam/Paris/Brussels/Lisbon and the export does not say
    # which. Amsterdam (.AS) is the right guess for the names that show up here
    # (ASML); check any other EURONEXT symbol before trusting its data.
    "EURONEXT": ".AS",
    # Deliberately NOT mapped: LSX (Lang & Schwarz). Yahoo has no LSX feed and its
    # entries are WKN-style codes, so they are reported as unmapped and skipped
    # rather than silently guessed into a wrong listing.
}


# A plausible Yahoo ticker: letters/digits plus . - ^ = (BRK-B, SAP.DE, ^GDAXI, EURUSD=X)
_TICKER_RE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.\-^=]{0,14}$")


def parse_watchlist(path: str | Path) -> list[str]:
    """Return Yahoo-Finance-style tickers from a watchlist file.

    Handles both shapes the README documents:
      - a hand-edited file, where a whole LINE starting with "#" is a comment
      - a raw TradingView export, which is one long comma-separated line with
        "###Section" headers sitting INLINE between the symbols

    So "#" comments out a whole line only when the line starts with it; inside a
    line it only drops the comma-separated chunk it begins. Cutting each line at
    its first "#" instead swallows every symbol after an inline "###USA" header —
    on a real export that is three quarters of the list.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    tickers: list[str] = []
    unmapped: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        for chunk in line.split(","):
            item = chunk.strip()
            if not item or item.startswith("#"):
                continue
            if ":" in item:
                exchange, symbol = item.split(":", 1)
                suffix = _EXCHANGE_SUFFIX.get(exchange.upper())
                if suffix is None:
                    # Fall back to the bare symbol, but say so — a bare ticker can
                    # silently resolve to a DIFFERENT security on another exchange.
                    unmapped.add(exchange.upper())
                    suffix = ""
                item = symbol + suffix
            if not _TICKER_RE.match(item):
                continue
            tickers.append(item)
    if unmapped:
        print(f"  warning: unmapped exchange prefix(es) {sorted(unmapped)} - those "
              f"symbols fall back to the bare ticker and may not resolve on Yahoo")
    # de-dupe, keep order
    seen: set[str] = set()
    out = []
    for t in tickers:
        if t.upper() not in seen:
            seen.add(t.upper())
            out.append(t)
    return out


# Yahoo suffix -> TradingView exchange prefix. The inverse of _EXCHANGE_SUFFIX
# above, kept beside it so the two cannot drift apart. Used to turn a report row
# into a chart link.
_TV_PREFIX = {
    ".DE": "XETR", ".F": "FWB", ".SG": "SWB", ".HM": "HAM", ".DU": "DUS",
    ".MU": "MUN", ".BE": "BER", ".AS": "EURONEXT", ".PA": "EURONEXT",
    ".BR": "EURONEXT", ".LS": "EURONEXT", ".MI": "MIL", ".L": "LSE",
    ".SW": "SIX", ".VI": "VIE", ".CO": "OMXCOP", ".ST": "OMXSTO",
    ".HE": "OMXHEX", ".OL": "OSL", ".MC": "BME",
}


def tv_symbol(ticker: str) -> str:
    """A Yahoo-style ticker as TradingView writes it.

    German listings need the exchange or TradingView may resolve them to a
    different venue - XETR:HBH is not the same series as TRADEGATE:HBH, and the
    gate is computed on the XETRA one. US tickers are left bare, which
    TradingView resolves to the primary listing.
    """
    t = ticker.upper()
    for suf, pre in _TV_PREFIX.items():
        if t.endswith(suf):
            return f"{pre}:{t[: -len(suf)]}"
    return t


_IB_PROV: dict | None = None


def _ib_written(ticker: str) -> bool:
    """Did backtest/ibkr_refresh.py write this symbol's daily cache?

    Read once per process. Absent file means no IB anywhere, and every caller
    falls back to the ordinary Yahoo path unchanged.
    """
    global _IB_PROV
    if _IB_PROV is None:
        try:
            _IB_PROV = json.loads(
                Path("data_cache/ibkr_provenance.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            _IB_PROV = {}
    return bool(_IB_PROV.get(ticker))


def load_daily(ticker: str, start: str | None, end: str | None,
               cache_dir: str | Path = "data_cache",
               stale_after: pd.Timestamp | None = None) -> pd.DataFrame:
    """Daily OHLC for one ticker via yfinance, cached as CSV.

    Returns a DataFrame with columns Open, High, Low, Close, Volume and a
    DatetimeIndex, or an empty DataFrame on failure.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = ticker.replace("/", "_").replace("^", "_")
    cache_file = cache_dir / f"{safe}.csv"

    # The cache is keyed on the ticker alone, so it must record WHICH range it
    # holds. Without this a short-range fetch silently overwrites a long-range
    # cache and every later backtest quietly loses its early history — that is
    # exactly how a 900-day scanner run truncated the benchmarks to 2024 and made
    # the relative-strength backtests block every entry before then.
    meta_file = cache_dir / f"{safe}.meta"
    use_cache = cache_file.exists()
    if use_cache:
        try:
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        except Exception:  # noqa: BLE001 - unreadable cache: refetch
            cached, use_cache = None, False

    # A file IB wrote is never replaced by Yahoo - not for being short, and not
    # for being stale either. Staleness is a SEPARATE trigger from the range
    # check, and closing only the range one left this hole: with the gateway down
    # on 2026-09-04, IB's newest US bar was 09-02, the scan wanted 09-03, and 166
    # of 228 symbols were quietly refetched from Yahoo - putting adjusted prices
    # back under a system that had just been converted to raw ones.
    #
    # Old data of the right convention beats fresh data of the wrong one. Held
    # back, the symbol simply reports its true last session and scan_daily's own
    # staleness guard keeps it out of the actionable lists, so the failure is
    # visible and issues no instruction. Refetched, it would silently produce a
    # confident instruction computed on a different price series.
    ib_authoritative = use_cache and _ib_written(ticker)

    if use_cache and stale_after is not None and not ib_authoritative:
        # A daily scan must not keep reporting last week.
        #
        # Compared on the last USABLE bar, not on the raw index. Yahoo sometimes
        # writes a row for a session it has volume but no prices for - all-NaN
        # OHLC - and the dropna at the end of this function removes it. Testing
        # the index alone therefore called such a file fresh and then handed back
        # data a day older than it claimed, which is exactly how a stale German
        # cache produced nine phantom DISARMS in the 07:00 scan.
        usable = cached.dropna(subset=["High", "Low", "Close"])
        last = usable.index.max() if len(usable) else pd.NaT
        use_cache = pd.notna(last) and last >= stale_after

    # A file IB wrote is AUTHORITATIVE and must never be replaced on range
    # grounds. IB serves five years; the scan asks for 2021-01-01; the range test
    # below therefore judged every IB file "too short" and refetched it from
    # Yahoo - silently converting the whole cache back to adjusted prices after
    # each conversion, which is why a 40-minute IB pass kept having no effect.
    if ib_authoritative:
        pass
    elif use_cache and start is not None and meta_file.exists():
        # Refetch when this file was built from a LATER start than we now need.
        # Compared on the requested start, not the first bar present, so a young
        # listing is not refetched forever just because it IPO'd late.
        try:
            prev = pd.Timestamp(meta_file.read_text(encoding="utf-8").strip())
            use_cache = prev <= pd.Timestamp(start)
        except Exception:  # noqa: BLE001
            use_cache = False

    if use_cache:
        df = cached
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
        if start is not None:
            meta_file.write_text(str(pd.Timestamp(start).date()), encoding="utf-8")

    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    return df.dropna(subset=["High", "Low", "Close"])

def load_intraday(ticker: str, interval: str = "1h", days: int = 720,
                  cache_dir: str | Path = "data_cache/intraday",
                  stale_after: pd.Timestamp | None = None) -> pd.DataFrame:
    """Intraday OHLC via yfinance, cached per (ticker, interval).

    Yahoo serves at most ~730 days of hourly history, so `days` is clamped: any
    study built on this is bounded by that, not by the daily cache's reach.

    `stale_after` forces a refetch when the cached file's last bar is older than
    the given timestamp. Without it a cache file, once written, is never renewed -
    harmless for a backtest over fixed history, silently fatal for a daily run,
    which would go on reporting last week's stop levels forever.

    The index is returned TIMEZONE-NAIVE in the exchange's own local time. Hourly
    bars come back tz-aware (and German and US symbols carry different zones), and
    comparing those against a tz-naive daily signal date raises; normalising once
    here keeps every caller from having to think about it.
    """
    import yfinance as yf

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = ticker.replace("/", "_").replace("^", "_")
    cache_file = cache_dir / f"{safe}_{interval}.csv"

    df = None
    if cache_file.exists():
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            # Written by an older version that stored tz-AWARE stamps. A single
            # file spans a DST change, so its offsets are mixed (+02:00 and
            # +01:00) and pandas cannot give them one dtype - it hands back
            # strings, and every later date comparison raises. Refetch and store
            # naive local time instead of trying to repair it.
            df = None
        elif stale_after is not None:
            # Last usable bar, for the same reason as load_daily above.
            u = df.dropna(subset=["High", "Low", "Close"]) if "Close" in df else df
            lastb = u.index.max() if len(u) else pd.NaT
            if pd.isna(lastb) or lastb < stale_after:
                df = None   # cached bars too old for a live scan

    if df is None:
        df = yf.download(ticker, period=f"{min(days, 730)}d", interval=interval,
                         auto_adjust=True, progress=False)
        if df is None or df.empty:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]]
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        df.to_csv(cache_file)  # naive local time, so the round trip is stable

    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    return df.dropna(subset=["High", "Low", "Close"]).sort_index()
