#!/usr/bin/env python3
"""Render a scan CSV as a one-or-two page PDF.

    .venv/Scripts/python.exe backtest/report_pdf.py                    # newest scan
    .venv/Scripts/python.exe backtest/report_pdf.py --date 2026-09-01

Reads what backtest/scan_daily.py wrote rather than recomputing anything, so the
PDF cannot disagree with the CSV beside it, and any past scan can be re-rendered
without refetching a single bar.

Layout follows what you do with it at 07:00, in order: exits first, because a
disarm is the only thing that must be acted on before the open; then new arms;
then the watch list sorted by how close each is to its trigger. Anything not
actionable - stale data, a stop too tight to size - is at the back with the
reason stated rather than dropped, so a name that vanishes from the list is
never a mystery.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d1d5db")
BAND = colors.HexColor("#f3f4f6")
RED = colors.HexColor("#b91c1c")
GREEN = colors.HexColor("#15803d")

# "Rank" first, because it is the column that says whether a row is worth acting
# on at all - 1 is the best record on the list, and a name near the bottom will
# lose nearly every slot contest.
COLS = [("rank", "Rank", 14), ("ticker", "Symbol", 20), ("close", "Close", 19),
        ("trigger", "Trigger", 19), ("to_trigger_pct", "To trig %", 19),
        ("stop", "Stop", 19), ("risk_pct", "Risk %", 17), ("shares", "Shares", 17),
        ("cost", "Cost", 19), ("to_disarm_pct", "Cushion %", 20),
        ("note", "Note", 24)]


def fmt(v, col: str) -> str:
    if pd.isna(v):
        return "-"
    if col in ("shares", "rank"):
        return f"{int(v):,}"
    if col in ("cost",):
        return f"{int(v):,}"
    if col in ("to_trigger_pct", "risk_pct", "to_disarm_pct"):
        return f"{v:+.2f}" if col == "to_disarm_pct" else f"{v:.2f}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def table_for(df: pd.DataFrame, style_extra=None) -> Table:
    head = [Paragraph(f"<b>{lbl}</b>", CELL_H) for _, lbl, _ in COLS]
    body = [[Paragraph(fmt(r[c], c), CELL) for c, _, _ in COLS]
            for _, r in df.iterrows()]
    t = Table([head] + body, colWidths=[w * mm for _, _, w in COLS],
              repeatRows=1, hAlign="LEFT")
    st = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
    ]
    if style_extra:
        st += style_extra
    t.setStyle(TableStyle(st))
    return t


def build(scan: Path, out: Path, cfg: dict, positions: pd.DataFrame | None,
          label: str = "") -> Path:
    df = pd.read_csv(scan)
    for c in ("stale",):
        if c in df:
            df[c] = df[c].astype(bool)
    asof = df.session.mode().iat[0]

    live = df[~df.stale] if "stale" in df else df
    behind = df[df.stale] if "stale" in df else df.iloc[0:0]
    disarm = live[live.state == "DISARMED"].sort_values("ticker")
    new_arm = live[live.state == "NEW ARM"].sort_values("to_trigger_pct")
    armed = live[live.state == "ARMED"].sort_values("to_trigger_pct")
    # Tradeable means a stop exists and is wide enough to size against; the rest
    # are listed after, with the reason, rather than silently dropped.
    ready = armed[armed.shares.notna()]
    blocked = armed[armed.shares.isna()]

    doc = SimpleDocTemplate(
        str(out), pagesize=landscape(A4),
        leftMargin=12 * mm, rightMargin=12 * mm,
        topMargin=11 * mm, bottomMargin=11 * mm,
        title=f"SuperTrend Breakout {label} {asof}".replace("  ", " "),
        author="supertrend_Stocks")

    S = []
    # The book's name goes in the title, because two of these arrive each morning
    # and a reader must be able to tell them apart at a glance.
    S.append(Paragraph("SuperTrend Breakout"
                       + (f" &mdash; {label}" if label else ""), H1))
    S.append(Paragraph(
        f"Session scanned <b>{asof}</b>  &nbsp;|&nbsp;  generated "
        f"{pd.Timestamp.now():%Y-%m-%d %H:%M}  &nbsp;|&nbsp;  {len(df)} symbols", SUB))
    S.append(Paragraph(
        "Gate: daily close above EMA50 <i>and</i> EMA200. Trigger: first 1h close "
        "above the previous completed daily high. Stop: 1h SuperTrend(3, ATR10) at "
        "entry. Breakeven at 1R, half out at 1.5R, remainder on the breakeven stop "
        "until the gate disarms.", SUB))

    eq = cfg.get("equity")
    if eq:
        S.append(Paragraph(
            f"Equity {eq:,.0f}  &nbsp;|&nbsp;  risk {cfg.get('risk_frac', 0):.2%} per "
            f"trade  &nbsp;|&nbsp;  {cfg.get('max_slots', '-')} slots  &nbsp;|&nbsp;  "
            f"max {cfg.get('max_position_pct', 100):.0f}% of equity in one position",
            SUB))
    S.append(Spacer(1, 5 * mm))

    counts = (f"<b>{len(disarm)}</b> to exit &nbsp;&nbsp; <b>{len(new_arm)}</b> newly "
              f"armed &nbsp;&nbsp; <b>{len(ready)}</b> watching &nbsp;&nbsp; "
              f"<b>{len(blocked) + len(behind)}</b> not actionable")
    S.append(Paragraph(counts, BIG))
    S.append(Spacer(1, 4 * mm))

    def section(title, part, note=None, colour=None):
        S.append(Paragraph(title, H2))
        if note:
            S.append(Paragraph(note, SUB))
        if part.empty:
            S.append(Paragraph("Nothing today.", MUTED_P))
        else:
            extra = [("TEXTCOLOR", (0, 1), (0, -1), colour)] if colour else None
            S.append(table_for(part, extra))
        S.append(Spacer(1, 5 * mm))

    section(f"Exit now - gate lost ({len(disarm)})", disarm,
            "The daily close fell below one of the two averages. Close any open "
            "position in these; the strategy holds nothing through a disarm.", RED)
    section(f"Newly armed today ({len(new_arm)})", new_arm,
            "Cleared both averages on the session just closed. In play from today.",
            GREEN)
    section(f"Armed and waiting ({len(ready)})", ready,
            "Sorted by distance to the trigger. The trigger is yesterday's high and "
            "Ordered by rank, which is how the book allocates slots: rank 1 has the "
            "best record on this universe. The trigger is yesterday's high and it "
            "stands all day. Shares are sized on the indicative stop, which will "
            "have moved by the time a breakout actually fires.")

    if len(blocked) or len(behind):
        S.append(PageBreak())
        S.append(Paragraph("Not actionable", H1))
        S.append(Spacer(1, 3 * mm))
        section(f"Armed, but no size ({len(blocked)})", blocked,
                "Armed on the daily, but no usable stop this morning: either the 1h "
                "SuperTrend is above price (a downtrend, so no long stop to quote) "
                "or the stop is nearer than the minimum risk the backtest enforces.")
        section(f"Stale data ({len(behind)})", behind,
                "The newest bar for these is behind the session the rest of the "
                "watchlist reached - usually an exchange holiday. Their gate was "
                "computed on older data, so no instruction is issued for them.")

    if positions is not None and not positions.empty:
        S.append(Paragraph("Open paper positions", H2))
        cols = [c for c in positions.columns][:9]
        head = [Paragraph(f"<b>{c}</b>", CELL_H) for c in cols]
        body = [[Paragraph(str(r[c]), CELL) for c in cols]
                for _, r in positions.iterrows()]
        t = Table([head] + body, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        S.append(t)

    doc.build(S)
    return out


styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Title"], fontName="Helvetica-Bold",
                    fontSize=17, leading=20, alignment=TA_LEFT, spaceAfter=1,
                    textColor=INK)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                    fontSize=11.5, leading=14, textColor=INK, spaceAfter=1)
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontName="Helvetica",
                     fontSize=7.6, leading=10, textColor=MUTED)
BIG = ParagraphStyle("BIG", parent=styles["Normal"], fontName="Helvetica",
                     fontSize=11, leading=14, textColor=INK)
CELL = ParagraphStyle("CELL", parent=styles["Normal"], fontName="Helvetica",
                      fontSize=7.6, leading=9.5)
CELL_H = ParagraphStyle("CELLH", parent=CELL, textColor=INK)
MUTED_P = ParagraphStyle("MP", parent=SUB, fontSize=8.5, leading=11)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None, help="scan date; default is the newest")
    ap.add_argument("--scans", default="scans")
    ap.add_argument("--config", default="paper/config.json")
    ap.add_argument("--positions", default="paper/open_positions.csv")
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--label", default="", help="book name, shown in the heading")
    ap.add_argument("--prefix", default="supertrend",
                    help="filename prefix, so two books do not overwrite "
                         "each other's PDF")
    args = ap.parse_args()

    sd = Path(args.scans)
    if args.date:
        scan = sd / f"{args.date}.csv"
    else:
        found = sorted(sd.glob("20*.csv"))
        if not found:
            print(f"no scans in {sd}")
            return 1
        scan = found[-1]
    if not scan.exists():
        print(f"no such scan: {scan}")
        return 1

    cfg = {}
    if Path(args.config).exists():
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    pos = None
    pp = Path(args.positions)
    if pp.exists():
        try:
            pos = pd.read_csv(pp)
        except Exception:  # noqa: BLE001
            pos = None

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"{args.prefix}_{scan.stem}.pdf"
    build(scan, pdf, cfg, pos, args.label)
    print(f"wrote {pdf}  ({pdf.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
