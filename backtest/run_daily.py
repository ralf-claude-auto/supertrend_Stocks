#!/usr/bin/env python3
"""Drive the morning run for every book in paper/systems.json.

    .venv/Scripts/python.exe backtest/run_daily.py
    .venv/Scripts/python.exe backtest/run_daily.py --only index --no-send

For each system, in order: scan its universe, replay its paper book, render its
PDF, send it. Two systems means two reports, each self-contained - a separate
universe, priority ranking, equity curve and scan output, sharing nothing but the
price cache. Adding a third book is an entry in systems.json and no code change.

WHY A PYTHON DRIVER rather than more lines in the .cmd: each step has to run per
system and the failure rules differ between them. A failed scan means everything
downstream for that book is untrustworthy, so it is skipped; a failed paper log
only costs the open-positions table, so the report is still worth sending; a
failed delivery is an error because a report that silently fails to send is worse
than none - you sit waiting for a list that was never coming. One book failing
never stops the other from running.

Exit status is 0 only if every system completed and every configured channel
delivered, so the scheduled task shows red when something needs looking at.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv/Scripts/python.exe"


def run(step: str, cmd: list[str]) -> bool:
    """One subprocess. Output is inherited so it lands in cron.log unchanged."""
    print(f"\n--- {step} ---", flush=True)
    r = subprocess.run([str(PY)] + cmd, cwd=ROOT)
    if r.returncode != 0:
        print(f"[FAIL] {step} exited {r.returncode}", flush=True)
        return False
    return True


def wanted_intraday(systems: list[dict]) -> set[str]:
    """Symbols whose 1h bars are worth a paced request this morning.

    Armed names, because those are the only ones that can be entered today and
    the stop is quoted from the 1h SuperTrend; plus anything currently held,
    whose stop has to be tested against bars that actually exist. Everything else
    on the watchlist cannot trade today, so its hourly series can wait.
    """
    import csv

    want: set[str] = set()
    for s in systems:
        scans = sorted(Path(ROOT / s["scans"]).glob("20*.csv"))
        if scans:
            with scans[-1].open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("state") in ("ARMED", "NEW ARM"):
                        want.add(row["ticker"])
        pos = ROOT / s["dir"] / "open_positions.csv"
        if pos.exists():
            with pos.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if row.get("ticker"):
                        want.add(row["ticker"])
    return want


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default="paper/systems.json")
    ap.add_argument("--only", default=None, help="run just this system by name")
    ap.add_argument("--no-send", action="store_true", help="build but do not send")
    ap.add_argument("--no-refresh", action="store_true",
                    help="skip the IB data refresh and use the cache as it is")
    ap.add_argument("--status", action="store_true",
                    help="pass through to paper_log: do not refresh data")
    args = ap.parse_args()

    spec = json.loads((ROOT / args.systems).read_text(encoding="utf-8"))
    systems = [s for s in spec["systems"]
               if args.only is None or s["name"] == args.only]
    if not systems:
        print(f"no system matched --only {args.only}")
        return 1

    print(f"===== run_daily {datetime.now():%Y-%m-%d %H:%M} - "
          f"{len(systems)} system(s): {', '.join(s['name'] for s in systems)} =====")

    failed = []

    # Refresh the price cache from IB first, once for the union of every
    # watchlist, so both books see the same bars. Deliberately NOT fatal: if the
    # gateway is down the books still run against whatever is cached, and the
    # staleness guard keeps anything too old out of the actionable lists. A
    # missing gateway should degrade the data, not cancel the morning.
    dr = spec.get("data_refresh", {})
    refresh_on = dr.get("enabled") and not args.no_refresh

    def ib(step: str, extra: list[str]) -> bool:
        cmd = ["backtest/ibkr_refresh.py",
               "--host", str(dr.get("host", "127.0.0.1")),
               "--port", str(dr.get("port", 4001)),
               "--client-id", str(dr.get("client_id", 17)),
               "--daily-years", dr.get("daily_years", "5 Y"),
               "--daily-what", dr.get("daily_what", "TRADES"),
               "--intraday-days", dr.get("intraday_days", "30 D")] + extra
        if run(step, cmd):
            return True
        print(f"[WARN] {step} failed - continuing on the existing cache", flush=True)
        failed.append("ibkr_refresh")
        return False

    # PHASE 1 - daily bars for every symbol. The gate needs all of them, and
    # nothing is known about today until it has been computed.
    if refresh_on:
        ib("IB daily refresh",
           ["--no-intraday"]
           + (["--skip-current"] if dr.get("skip_current") else [])
           + sum([["--watchlist", s["watchlist"]] for s in systems], []))

    # PHASE 2 - scan, which is what tells us which symbols are actually armed.
    scanned = []
    for s in systems:
        name, d = s["name"], s["dir"]
        print(f"\n=========== {name}  ({s['label']}) - scan ===========", flush=True)
        if run(f"{name}: scan", [
            "backtest/scan_daily.py",
            "--watchlist", s["watchlist"],
            "--outdir", s["scans"],
            "--config", f"{d}/config.json",
        ]):
            scanned.append(s)
        else:
            # Nothing downstream can be trusted without a scan, so skip this book
            # entirely rather than send a report built on yesterday's file.
            failed.append(f"{name}:scan")

    # PHASE 3 - hourly bars, but only for symbols that are armed or held. The 1h
    # series is used for one thing, the stop, and a symbol that is not armed
    # cannot be entered today - so fetching its hourly bars buys nothing and
    # costs a paced request. That is ~60 symbols instead of ~235, which is the
    # difference between a 50-minute morning and an 80-minute one.
    if refresh_on and scanned:
        want = wanted_intraday(scanned)
        if want:
            print(f"\n[phase 3] {len(want)} symbols armed or held, "
                  f"fetching their 1h bars", flush=True)
            ib("IB intraday refresh",
               ["--intraday-only", "--symbols", ",".join(sorted(want))])
            # Re-scan so the stops quoted in the report come from the bars just
            # fetched rather than from yesterday's. No downloads: everything the
            # scan needs is now cached.
            for s in scanned:
                run(f"{s['name']}: rescan on fresh 1h", [
                    "backtest/scan_daily.py",
                    "--watchlist", s["watchlist"],
                    "--outdir", s["scans"],
                    "--config", f"{s['dir']}/config.json",
                ])

    # PHASE 4 - the books, reports and delivery.
    for s in scanned:
        name, d = s["name"], s["dir"]
        print(f"\n=========== {name}  ({s['label']}) - report ===========", flush=True)

        if not run(f"{name}: paper log", [
            "backtest/paper_log.py",
            "--config", f"{d}/config.json",
            "--outdir", d,
            "--label", s["label"],
        ] + (["--status"] if args.status else [])):
            # Survivable: the report loses its open-positions table and nothing
            # else, so it is still worth building and sending.
            print(f"[WARN] {name}: report will omit open positions", flush=True)
            failed.append(f"{name}:paper_log")

        if not run(f"{name}: pdf", [
            "backtest/report_pdf.py",
            "--scans", s["scans"],
            "--config", f"{d}/config.json",
            "--positions", f"{d}/open_positions.csv",
            "--label", s["label"],
            "--prefix", name,
        ]):
            failed.append(f"{name}:pdf")
            continue

        if args.no_send:
            print(f"[INFO] {name}: --no-send, PDF written only", flush=True)
            continue
        if not (ROOT / "paper/delivery.json").exists():
            print(f"[INFO] {name}: paper/delivery.json absent, not sent", flush=True)
            continue
        if not run(f"{name}: deliver", [
            "backtest/deliver.py", "--prefix", name, "--scans", s["scans"],
        ]):
            failed.append(f"{name}:deliver")

    print(f"\n===== done {datetime.now():%Y-%m-%d %H:%M} =====")
    if failed:
        print(f"FAILED STEPS: {', '.join(failed)}")
        return 1
    print("all systems completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
