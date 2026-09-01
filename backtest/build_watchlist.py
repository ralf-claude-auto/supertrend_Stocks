#!/usr/bin/env python3
"""Build a liquid-universe watchlist from index constituents, verified against data.

    .venv/Scripts/python.exe backtest/build_watchlist.py

Constituent lists are pasted in below rather than scraped at runtime: index
membership changes slowly, and a backtest universe that silently shifts under you
is worse than one that is explicit and dated. Every symbol is then CHECKED against
Yahoo - it must download, carry enough history for the MA, and clear a median
dollar-volume floor - so a wrong or delisted ticker is dropped rather than
quietly producing an empty series in the middle of a run.

Sources, fetched 2026-09-01:
  Nasdaq-100  stockanalysis.com/list/nasdaq-100-stocks/
  DAX 40      en.wikipedia.org/wiki/DAX

Membership drifts. Re-run this when it matters and the report will show what
changed. Note the universe is TODAY's membership applied to past data, so it
carries survivorship bias: names that fell out of the index are absent, and the
survivors did better than the index average by construction.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from data import load_daily

NASDAQ_100 = """
NVDA AAPL GOOGL MSFT AMZN AVGO META TSLA MU WMT AMD ASML INTC PLTR CSCO COST
LRCX AMAT NFLX PANW ARM AMGN TXN SNDK LIN KLAC CRWD TMUS PEP STX SHOP GILD
MRVL QCOM ADI WDC BKNG VRTX ISRG SBUX FTNT PDD ADBE ADP ABNB APP DASH MELI
CEG INTU CMCSA CSX MNST CDNS MAR DDOG REGN CTAS SNPS MDLZ LITE ROST WBD ORLY
AEP HON PCAR BKR MPWR FANG FAST NXPI NBIS ADSK TER MSTR WDAY ALAB CCEP XEL
TRI EXC CRWV PAYX PYPL KDP IDXX AXON FER ROP TTWO ODFL MCHP RKLB DXCM ALNY
GEHC KHC CPRT
""".split()

# GOOG is dropped: same company as GOOGL, and holding both would put two
# positions on one business. AIR is taken on XETRA rather than Paris so it sits
# in the German session and is measured against the DAX like its peers.
DAX_40 = """
ADS.DE AIR.DE ALV.DE BAS.DE BAYN.DE BEI.DE BMW.DE BNR.DE CBK.DE CON.DE DTG.DE
DBK.DE DB1.DE DHL.DE DTE.DE EOAN.DE FRE.DE FME.DE G1A.DE HNR1.DE HEI.DE
HEN3.DE IFX.DE MBG.DE MRK.DE MTX.DE MUV2.DE PAH3.DE QIA.DE RHM.DE RWE.DE
SAP.DE G24.DE SIE.DE ENR.DE SHL.DE SY1.DE VOW3.DE VNA.DE ZAL.DE
""".split()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="watchlists/nq100_dax40.txt")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--min-bars", type=int, default=400,
                    help="daily bars needed for the MA200 plus a usable window")
    ap.add_argument("--min-dollar-vol", type=float, default=5e6,
                    help="floor on median daily turnover, in the listing currency")
    ap.add_argument("--cache-dir", default="data_cache")
    args = ap.parse_args()

    universe = [(t, "NQ100") for t in NASDAQ_100] + [(t, "DAX40") for t in DAX_40]
    seen, rows, dropped = set(), [], []

    print(f"checking {len(universe)} symbols...\n")
    for t, idx in universe:
        if t in seen:
            dropped.append((t, idx, "duplicate"))
            continue
        seen.add(t)
        try:
            d = load_daily(t, args.start, None, args.cache_dir)
        except Exception as exc:  # noqa: BLE001
            dropped.append((t, idx, f"download failed: {str(exc)[:40]}"))
            continue
        if d.empty:
            dropped.append((t, idx, "no data"))
            continue
        if len(d) < args.min_bars:
            dropped.append((t, idx, f"only {len(d)} bars"))
            continue
        dv = float((d["Close"] * d["Volume"]).median())
        if dv < args.min_dollar_vol:
            dropped.append((t, idx, f"median turnover {dv/1e6:.1f}M below floor"))
            continue
        rows.append({"ticker": t, "index": idx, "bars": len(d),
                     "median_turnover_m": round(dv / 1e6, 1),
                     "last": round(float(d["Close"].iloc[-1]), 2)})

    keep = pd.DataFrame(rows).sort_values(["index", "median_turnover_m"],
                                          ascending=[True, False])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = [
        f"# Nasdaq-100 + DAX 40, verified {pd.Timestamp.today().date()}.",
        "# Built by backtest/build_watchlist.py - every symbol downloaded, checked",
        f"# for >= {args.min_bars} daily bars and median turnover >= "
        f"{args.min_dollar_vol/1e6:.0f}M in its own currency.",
        "# TODAY's membership applied to past data, so it carries survivorship bias.",
        f"# {len(keep)} symbols: {int((keep['index']=='NQ100').sum())} Nasdaq-100, "
        f"{int((keep['index']=='DAX40').sum())} DAX.",
    ]
    out.write_text("\n".join(header + list(keep.ticker)) + "\n", encoding="utf-8")

    print(keep.groupby("index").agg(symbols=("ticker", "size"),
                                    median_turnover_m=("median_turnover_m", "median"),
                                    min_turnover_m=("median_turnover_m", "min")).to_string())
    print(f"\nkept {len(keep)}, dropped {len(dropped)}")
    for t, idx, why in dropped:
        print(f"  {t:10s} {idx:6s} {why}")
    print(f"\nleast liquid kept:")
    print(keep.nsmallest(8, "median_turnover_m")[
        ["ticker", "index", "median_turnover_m", "bars"]].to_string(index=False))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
