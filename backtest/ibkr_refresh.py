#!/usr/bin/env python3
"""Fill the price cache from Interactive Brokers instead of Yahoo.

    .venv/Scripts/python.exe backtest/ibkr_refresh.py --watchlist watchlists/nq100_dax40.txt
    .venv/Scripts/python.exe backtest/ibkr_refresh.py --symbols HEN3.DE,SAP.DE --verbose
    .venv/Scripts/python.exe backtest/ibkr_refresh.py --check          # connection only

This writes the SAME cache files backtest/data.py already reads - data_cache/<t>.csv
and data_cache/intraday/<t>_1h.csv, identical columns and index names - so nothing
downstream changes. Run it before the scan and the rest of the pipeline simply
finds fresher data. If the gateway is down it exits non-zero having changed
nothing, and the pipeline carries on against whatever Yahoo last gave it. The
data source is swapped underneath the system rather than threaded through it.

WHY. Yahoo served a 2026-09-02 daily bar for German symbols at 07:56 and had
withdrawn it by 09:00, which left 30 DAX names stale and unactionable in the same
run where the other book still had them. IB has that bar, has today's, and is the
venue the orders would go to - so the data and the execution finally agree.

ADJUSTMENT, which is the trap here. The Yahoo cache is split- and
dividend-ADJUSTED. IB serves adjusted daily bars only as ADJUSTED_LAST, and its
intraday bars are always unadjusted TRADES. Appending unadjusted bars onto an
adjusted history puts the two halves on different scales, and across a split that
is not a rounding difference - it is a fabricated gap of exactly the split ratio,
which the SuperTrend would read as a real move. So every merge re-checks the
overlapping bars and refuses to splice when the scales disagree, refetching the
whole series instead.

PACING. IB allows roughly 60 historical requests per ten minutes, and one symbol
needs one request per timeframe. A 136-symbol universe is therefore about 35
minutes of wall clock at the limit, which is why this runs at 07:00 unattended
and writes the cache as it goes: a run that is interrupted keeps everything it
already fetched, and the next run continues from there.

SETUP, once: install IB Gateway, enable API access in Configure > Settings > API
(Socket port 4001 live / 4002 paper, 'Enable ActiveX and Socket Clients' on, add
127.0.0.1 to trusted IPs). The gateway logs out daily, so an unattended 07:00 job
needs IBC (github.com/IbcAlpha/IBC) to log it back in.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import parse_watchlist

CONTRACTS = Path("data_cache/ibkr_contracts.json")
# Read by report_pdf so the morning PDF states where its bars came from. Without
# it a gateway that quietly logged out overnight looks exactly like a good day:
# the reports still arrive, on stale numbers, and nothing says so.
STATUS = Path("data_cache/ibkr_status.json")
DAILY_DIR = Path("data_cache")
INTRA_DIR = Path("data_cache/intraday")

# Yahoo suffix -> (IB primary exchange, currency). Yahoo is the naming the
# watchlists are written in, so the mapping lives here rather than in them.
EXCHANGE = {
    ".DE": ("IBIS", "EUR"),      # Xetra
    ".AS": ("AEB", "EUR"),       # Euronext Amsterdam
    ".PA": ("SBF", "EUR"),       # Euronext Paris
    ".MI": ("BVME", "EUR"),
    ".L":  ("LSE", "GBP"),
    ".SW": ("EBS", "CHF"),
    ".VI": ("VSE", "EUR"),
    ".CO": ("CPH", "DKK"),
    ".ST": ("SFB", "SEK"),
    ".HE": ("HEX", "EUR"),
    ".OL": ("OSE", "NOK"),
    ".MC": ("BM", "EUR"),
    ".BR": ("ENEXT.BE", "EUR"),
    ".LS": ("BVLP", "EUR"),
}


class Pacer:
    """Keeps historical requests under IB's ~60 per ten minutes.

    Tracks actual send times rather than sleeping a fixed amount, so a run that
    is already slow for other reasons is not delayed twice over.
    """

    def __init__(self, limit: int = 55, window: float = 600.0):
        self.limit, self.window, self.sent = limit, window, []

    def wait(self) -> None:
        now = time.time()
        self.sent = [t for t in self.sent if now - t < self.window]
        if len(self.sent) >= self.limit:
            sleep = self.window - (now - self.sent[0]) + 1
            if sleep > 0:
                print(f"    [pacing] {sleep:.0f}s to stay under "
                      f"{self.limit}/{self.window/60:.0f}min", flush=True)
                time.sleep(sleep)
        self.sent.append(time.time())


def ib_contract(ticker: str):
    """A Yahoo-style ticker as an IB Stock contract."""
    from ib_async import Stock

    t = ticker.upper()
    for suf, (exch, ccy) in EXCHANGE.items():
        if t.endswith(suf):
            return Stock(t[: -len(suf)], "SMART", ccy, primaryExchange=exch)
    # Bare tickers are US. Yahoo writes share classes with a hyphen (BRK-B),
    # IB with a space (BRK B).
    return Stock(t.replace("-", " "), "SMART", "USD")


def resolve(ib, ticker: str, cache: dict, verbose: bool) -> object | None:
    """Qualified contract for a ticker, with the conId remembered between runs."""
    from ib_async import Stock

    if ticker in cache and cache[ticker]:
        c = cache[ticker]
        return Stock(conId=c["conId"], exchange="SMART", symbol=c["symbol"],
                     currency=c["currency"])
    try:
        det = ib.reqContractDetails(ib_contract(ticker))
    except Exception as exc:  # noqa: BLE001
        if verbose:
            print(f"    {ticker}: contract lookup failed ({exc})")
        return None
    if not det:
        cache[ticker] = None          # remembered so it is not retried daily
        return None
    c = det[0].contract
    cache[ticker] = {"conId": c.conId, "symbol": c.symbol, "currency": c.currency,
                     "exchange": c.primaryExchange or c.exchange}
    return c


def bars_to_frame(bars, index_name: str) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "when": b.date, "Open": float(b.open), "High": float(b.high),
        "Low": float(b.low), "Close": float(b.close),
        "Volume": float(b.volume) if b.volume and b.volume > 0 else 0.0,
    } for b in bars])
    df["when"] = pd.to_datetime(df["when"])
    if getattr(df["when"].dt, "tz", None) is not None:
        # The cache stores naive LOCAL exchange time; see load_intraday's note on
        # why tz-aware stamps cannot round-trip through CSV across a DST change.
        df["when"] = df["when"].dt.tz_localize(None)
    df = df.set_index("when").sort_index()
    df.index.name = index_name
    return df[["Open", "High", "Low", "Close", "Volume"]]


def scales_agree(old: pd.DataFrame, new: pd.DataFrame, tol: float = 0.02) -> bool:
    """Do two series price the same bars the same way?

    Compares closes on the timestamps they share. A split between an adjusted
    history and an unadjusted refresh shows up here as a ratio far from 1 - and
    splicing across that would invent a move of exactly the split ratio.
    """
    common = old.index.intersection(new.index)
    if len(common) < 3:
        return True                    # nothing to contradict
    a, b = old.loc[common, "Close"], new.loc[common, "Close"]
    ok = (a > 0) & (b > 0)
    if ok.sum() < 3:
        return True
    return bool((((a[ok] / b[ok]) - 1.0).abs() < tol).mean() > 0.9)


def fetch(ib, contract, duration: str, bar_size: str, what: str, pacer: Pacer):
    pacer.wait()
    return ib.reqHistoricalData(contract, endDateTime="", durationStr=duration,
                                barSizeSetting=bar_size, whatToShow=what,
                                useRTH=True, formatDate=1)


def write_daily(ticker: str, df: pd.DataFrame, start_meta: str) -> None:
    safe = ticker.replace("/", "_").replace("^", "_")
    df.to_csv(DAILY_DIR / f"{safe}.csv")
    (DAILY_DIR / f"{safe}.meta").write_text(start_meta, encoding="utf-8")


def merge_into(path: Path, new: pd.DataFrame, index_name: str) -> tuple[pd.DataFrame, str]:
    """New bars over whatever is cached, refusing an inconsistent splice."""
    if not path.exists() or new.empty:
        return new, "fresh"
    try:
        old = pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception:  # noqa: BLE001
        return new, "fresh"
    if not pd.api.types.is_datetime64_any_dtype(old.index) or old.empty:
        return new, "fresh"
    if not scales_agree(old, new):
        # Adjusted history vs unadjusted refresh, i.e. a split in between. The
        # cached part is on a dead scale; keeping any of it would fabricate a gap.
        return new, "rescaled (split detected, old history dropped)"
    merged = pd.concat([old[~old.index.isin(new.index)], new]).sort_index()
    merged.index.name = index_name
    return merged, "merged"


def write_status(**kw) -> None:
    """Record how this pass went, accumulating within the same day.

    The morning makes two passes - daily for everything, then hourly for what is
    armed - and a plain overwrite would leave the report describing only the
    second. So same-day passes are summed, and `ok` is true only if every pass
    was: one failed leg has to be able to spoil the whole morning's claim, or the
    warning it exists to raise never appears.
    """
    now = datetime.now()
    kw["when"] = now.isoformat(timespec="seconds")
    kw["passes"] = [kw.get("pass_kind", "?")]
    try:
        if STATUS.exists():
            prev = json.loads(STATUS.read_text(encoding="utf-8"))
            if str(prev.get("when", ""))[:10] == now.date().isoformat():
                kw["refreshed"] = kw.get("refreshed", 0) + prev.get("refreshed", 0)
                kw["failed"] = kw.get("failed", 0) + prev.get("failed", 0)
                kw["unmapped"] = kw.get("unmapped", 0) + prev.get("unmapped", 0)
                kw["ok"] = bool(kw.get("ok")) and bool(prev.get("ok", True))
                kw["passes"] = prev.get("passes", []) + kw["passes"]
                if not kw.get("reason") and prev.get("reason"):
                    kw["reason"] = prev["reason"]
    except Exception:  # noqa: BLE001
        pass
    try:
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(json.dumps(kw, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watchlist", action="append", default=[],
                    help="may be given more than once; the union is fetched")
    ap.add_argument("--symbols", default=None, help="comma-separated, overrides --watchlist")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4001,
                    help="4001 live gateway, 4002 paper, 7496/7497 for TWS")
    ap.add_argument("--client-id", type=int, default=17,
                    help="must differ from any other API client on the gateway")
    ap.add_argument("--daily-years", default="3 Y")
    ap.add_argument("--intraday-days", default="30 D",
                    help="short by design: it is merged onto the existing history, "
                         "and a shorter window is one cheap request per symbol")
    ap.add_argument("--no-intraday", action="store_true")
    ap.add_argument("--intraday-only", action="store_true",
                    help="skip the daily pass. Used for the second phase of the "
                         "morning run, once the scan has said which symbols are "
                         "actually armed and therefore need a current stop")
    ap.add_argument("--skip-current", action="store_true",
                    help="skip symbols whose cache already reaches the last "
                         "completed session. Makes a re-run, or a resumed run "
                         "after an interruption, cost almost nothing - which "
                         "matters because a full pass is ~470 paced requests")
    ap.add_argument("--check", action="store_true", help="connect, report, exit")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    try:
        from ib_async import IB
    except ImportError:
        print("ib_async is not installed: .venv/Scripts/python.exe -m pip install ib_async")
        return 2

    ib = IB()
    try:
        ib.connect(args.host, args.port, clientId=args.client_id, timeout=15)
    except Exception as exc:  # noqa: BLE001
        write_status(ok=False, reason=f"gateway unreachable at "
                                      f"{args.host}:{args.port}", refreshed=0)
        print(f"cannot reach IB Gateway at {args.host}:{args.port} ({exc})")
        print("  Is the gateway running and logged in, with the API enabled?")
        print("  Configure > Settings > API > Enable ActiveX and Socket Clients,")
        print("  socket port 4001 (live) or 4002 (paper), 127.0.0.1 trusted.")
        return 1
    print(f"connected to IB at {args.host}:{args.port} "
          f"(server {ib.client.serverVersion()})")
    if args.check:
        ib.disconnect()
        return 0

    if args.symbols:
        tickers = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        seen, tickers = set(), []
        for w in (args.watchlist or ["watchlists/nq100_dax40.txt"]):
            for t in parse_watchlist(w):
                if t not in seen:
                    seen.add(t)
                    tickers.append(t)

    cache = {}
    if CONTRACTS.exists():
        try:
            cache = json.loads(CONTRACTS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cache = {}

    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    INTRA_DIR.mkdir(parents=True, exist_ok=True)
    pacer = Pacer()
    ok = skipped = failed = 0
    started = time.time()

    # The last session that must be present for a cache to count as current.
    # Compared on the last USABLE bar for the same reason load_daily does it: a
    # row can exist with all-NaN prices and be dropped by every reader.
    cutoff = (pd.Timestamp.now().normalize() - pd.tseries.offsets.BDay(1))

    def is_current(t: str) -> bool:
        safe = t.replace("/", "_").replace("^", "_")
        f = DAILY_DIR / f"{safe}.csv"
        if not f.exists():
            return False
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            df = df.dropna(subset=["High", "Low", "Close"])
            return len(df) > 0 and df.index.max() >= cutoff
        except Exception:  # noqa: BLE001
            return False

    if args.skip_current and not args.intraday_only:
        before = len(tickers)
        tickers = [t for t in tickers if not is_current(t)]
        print(f"--skip-current: {before - len(tickers)} already reach "
              f"{cutoff.date()}, {len(tickers)} to fetch")

    if not tickers:
        # Still a healthy outcome, and it must say so: this is the normal result
        # of --skip-current when the cache is already current, and leaving the
        # status unwritten would make the report claim the data source is
        # unknown when in fact everything needed is present.
        print("nothing to fetch - cache already current")
        write_status(ok=True, refreshed=0, unmapped=0, failed=0,
                     pass_kind=("1h" if args.intraday_only else
                                "daily" if args.no_intraday else "daily+1h")
                               + " (already current)",
                     note="cache already current, nothing to fetch")
        ib.disconnect()
        return 0
    per = 0 if args.intraday_only else 1
    per += 0 if args.no_intraday else 1
    est = len(tickers) * max(per, 1) / 55 * 10
    what = ("1h " + args.intraday_days if args.intraday_only else
            "daily " + args.daily_years +
            ("" if args.no_intraday else f" + 1h {args.intraday_days}"))
    print(f"refreshing {len(tickers)} symbols ({what})"
          f" - roughly {est:.0f} min at IB's pacing limit")
    for i, t in enumerate(tickers, 1):
        contract = resolve(ib, t, cache, args.verbose)
        if contract is None:
            print(f"  [{i:3d}/{len(tickers)}] {t:10s} no IB contract")
            skipped += 1
            continue
        safe = t.replace("/", "_").replace("^", "_")
        try:
            note = ""
            if not args.intraday_only:
                # ADJUSTED_LAST to match the adjusted convention the cache is in.
                bars = fetch(ib, contract, args.daily_years, "1 day",
                             "ADJUSTED_LAST", pacer)
                d = bars_to_frame(bars, "Date")
                if d.empty:
                    print(f"  [{i:3d}/{len(tickers)}] {t:10s} no daily bars")
                    failed += 1
                    continue
                merged, how = merge_into(DAILY_DIR / f"{safe}.csv", d, "Date")
                write_daily(t, merged, str(merged.index.min().date()))
                note = f"daily {len(merged)} to {merged.index.max().date()} ({how})"

            if not args.no_intraday:
                # Intraday is TRADES only - IB serves no adjusted intraday - so
                # merge_into's scale check is what stands between a split and a
                # fabricated gap in the hourly series.
                hb = fetch(ib, contract, args.intraday_days, "1 hour",
                           "TRADES", pacer)
                h = bars_to_frame(hb, "Datetime")
                if not h.empty:
                    hp = INTRA_DIR / f"{safe}_1h.csv"
                    hm, hhow = merge_into(hp, h, "Datetime")
                    hm.to_csv(hp)
                    note += (", " if note else "") +                         f"1h {len(hm)} to {hm.index.max()} ({hhow})"
            print(f"  [{i:3d}/{len(tickers)}] {t:10s} {note}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i:3d}/{len(tickers)}] {t:10s} FAILED {str(exc)[:80]}")
            failed += 1
        finally:
            # Written every symbol, so an interrupted run keeps its lookups.
            CONTRACTS.write_text(json.dumps(cache, indent=1), encoding="utf-8")

    ib.disconnect()
    mins = (time.time() - started) / 60
    # `ok` means the gateway answered and this pass ran to the end - NOT that
    # every symbol yielded bars. A permanently delisted ticker is unmappable
    # forever, and letting that set ok=False would print a red data warning on
    # every report every day until you stopped believing it. Real fetch errors
    # are counted separately and do surface.
    write_status(ok=True, refreshed=ok, unmapped=skipped, failed=failed,
                 minutes=round(mins, 1), symbols=len(tickers),
                 pass_kind="1h" if args.intraday_only else
                           ("daily" if args.no_intraday else "daily+1h"))
    print(f"\ndone in {mins:.1f} min: {ok} refreshed, {skipped} unmapped, "
          f"{failed} failed")
    # Only a fetch that errored is a failure worth a non-zero exit. Unmappable
    # symbols are a permanent property of the watchlist, not a fault of this run.
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
