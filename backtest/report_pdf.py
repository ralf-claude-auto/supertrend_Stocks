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

sys.path.insert(0, str(Path(__file__).parent))
from data import tv_symbol
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
LINK = colors.HexColor("#1d4ed8")

# Set from --tv-chart. Every symbol cell becomes a link to this chart with the
# symbol appended, so a name in the report opens the chart you actually analyse
# in rather than a default one.
TV_BASE = ""


def sym_cell(ticker: str) -> str:
    """A ticker, linked to its TradingView chart when a base URL is configured."""
    if not TV_BASE:
        return str(ticker)
    sep = "&" if "?" in TV_BASE else "?"
    return (f'<a href="{TV_BASE}{sep}symbol={tv_symbol(str(ticker))}" '
            f'color="#1d4ed8">{ticker}</a>')

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
    body = [[Paragraph(sym_cell(r[c]) if c == "ticker" else fmt(r[c], c), CELL)
             for c, _, _ in COLS] for _, r in df.iterrows()]
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
          label: str = "", trades: pd.DataFrame | None = None) -> Path:
    df = pd.read_csv(scan)
    for c in ("stale",):
        if c in df:
            df[c] = df[c].astype(bool)
    asof = df.session.mode().iat[0]

    # Rank is carried on the scan rows; the positions file has no notion of it,
    # so it is looked up here rather than duplicated into the book.
    ranks = dict(zip(df.ticker, df["rank"])) if "rank" in df else {}

    live = df[~df.stale] if "stale" in df else df
    behind = df[df.stale] if "stale" in df else df.iloc[0:0]
    disarm = live[live.state == "DISARMED"].sort_values("ticker")
    new_arm = live[live.state == "NEW ARM"].sort_values("to_trigger_pct")
    armed = live[live.state == "ARMED"].sort_values("to_trigger_pct")
    # Tradeable means a stop exists and is wide enough to size against; the rest
    # are listed after, with the reason, rather than silently dropped.
    ready = armed[armed.shares.notna()]
    blocked = armed[armed.shares.isna()]
    holding = live[live.state == "HELD"].sort_values("ticker")         if "state" in live else live.iloc[0:0]

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

    # Where this morning's bars came from. A gateway that logged out overnight
    # otherwise looks identical to a good day - same reports, same time, older
    # numbers - so it is stated on the page rather than left in a log nobody
    # reads.
    st = Path("data_cache/ibkr_status.json")
    if st.exists():
        try:
            j = json.loads(st.read_text(encoding="utf-8"))
            when = str(j.get("when", ""))[:16].replace("T", " ")
            # Warn on an unreachable gateway or a real fetch error. Unmapped
            # symbols are permanently-delisted watchlist entries and would
            # otherwise raise a warning every single day.
            if j.get("ok") and not j.get("failed"):
                S.append(Paragraph(
                    f"Data: <b>IBKR</b>, refreshed {when} "
                    f"({j.get('refreshed', '?')} symbols"
                    + (f", {j['failed']} failed" if j.get("failed") else "")
                    + ").", SUB))
            else:
                S.append(Paragraph(
                    f"<b>DATA WARNING - {j.get('reason', 'refresh failed')} "
                    f"at {when}.</b> These bars are from the last successful "
                    f"refresh, not from this morning. Anything too old to trust "
                    f"is listed as stale at the back and carries no instruction.",
                    WARN))
        except Exception:  # noqa: BLE001
            pass

    eq = cfg.get("equity")
    if eq:
        S.append(Paragraph(
            f"Equity {eq:,.0f}  &nbsp;|&nbsp;  risk {cfg.get('risk_frac', 0):.2%} per "
            f"trade  &nbsp;|&nbsp;  {cfg.get('max_slots', '-')} slots  &nbsp;|&nbsp;  "
            f"max {cfg.get('max_position_pct', 100):.0f}% of equity in one position",
            SUB))
    S.append(Spacer(1, 5 * mm))

    counts = (f"<b>{len(disarm)}</b> to exit &nbsp;&nbsp; <b>{len(new_arm)}</b> newly "
              f"armed &nbsp;&nbsp; <b>{len(holding)}</b> held &nbsp;&nbsp; "
              f"<b>{len(ready)}</b> watching &nbsp;&nbsp; "
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
    section(f"Already held - do not re-enter ({len(holding)})", holding,
            "These are open in the book. They are still armed, and today's "
            "trigger is shown, but the position exists - so the row is a status, "
            "not an instruction to buy.")
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
        # An explicit column list, not the first N of whatever the CSV happens to
        # hold. Slicing columns put mark, R and pnl - the three that say how the
        # position is actually doing - just past the cut, so the table showed
        # entry and stop and nothing about the outcome.
        p = positions.copy()
        p["rank"] = p.ticker.map(ranks)
        p["pnl_pct"] = (100.0 * p.pnl / p.notional).round(2) if "notional" in p else None
        p = p.sort_values(["rank", "ticker"], na_position="last")

        POS = [("rank", "Rank", 13), ("ticker", "Symbol", 20),
               ("entry_time", "Entered", 26), ("entry", "Entry", 19),
               ("shares", "Shares", 16), ("mark", "Price", 19),
               ("stop", "Stop", 19), ("scale_out", "Scale out", 20),
               ("R", "R", 14), ("pnl", "Open P/L", 18), ("pnl_pct", "P/L %", 17)]

        def posfmt(v, col):
            if pd.isna(v):
                return "-"
            if col == "entry_time":
                return str(v)[:16]
            if col in ("rank", "shares"):
                return f"{int(v):,}"
            if col in ("R", "pnl", "pnl_pct"):
                return f"{v:+,.2f}"
            if isinstance(v, float):
                return f"{v:,.2f}"
            return str(v)

        S.append(Paragraph(f"Open paper positions ({len(p)})", H2))
        S.append(Paragraph(
            "Price is the latest mark, so P/L is what the position is worth now. "
            "Rank is the same one the watch list uses - it decided which of the "
            "day's candidates got this slot.", SUB))
        head = [Paragraph(f"<b>{lbl}</b>", CELL_H) for _, lbl, _ in POS]
        body = [[Paragraph(sym_cell(r[c]) if c == "ticker" else posfmt(r[c], c),
                           CELL) for c, _, _ in POS]
                for _, r in p.iterrows()]
        # Total row: the number you actually want off this table.
        tot = p.pnl.sum() if "pnl" in p else 0.0
        body.append([Paragraph("", CELL)] * 9
                    + [Paragraph(f"<b>{tot:+,.2f}</b>", CELL_H),
                       Paragraph("", CELL)])
        t = Table([head] + body, colWidths=[w * mm for _, _, w in POS],
                  repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, BAND]),
            ("LINEABOVE", (0, -1), (-1, -1), 0.6, INK),
            ("TEXTCOLOR", (9, 1), (9, -1), GREEN if tot >= 0 else RED),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        S.append(t)

    # ---------------------------------------------------------------- closed
    # The realised record, and the only place the book's actual result shows.
    # Open positions say what MIGHT happen; this says what did. Kept in
    # chronological order with a running total, because the question it answers
    # is "how has this book gone since it started", not "what happened today" -
    # newest-first would break the cumulative column into nonsense.
    if trades is not None and not trades.empty:
        tr = trades.copy()
        for c in ("entry_time", "exit_time"):
            tr[c] = pd.to_datetime(tr[c], errors="coerce")
        tr = tr.sort_values("exit_time")
        tr["cum"] = tr.pnl.cumsum()
        tr["held"] = (tr.exit_time - tr.entry_time).dt.total_seconds() / 86400.0

        realised = float(tr.pnl.sum())
        wins = int((tr.R > 0).sum())
        unreal = float(positions.pnl.sum()) if positions is not None and \
            not positions.empty and "pnl" in positions else 0.0

        S.append(Spacer(1, 6 * mm))
        S.append(Paragraph(f"Closed trades ({len(tr)})", H2))
        S.append(Paragraph(
            f"Realised <b>{realised:+,.2f}</b> over {len(tr)} trades, "
            f"{wins} won ({100.0*wins/len(tr):.0f}%), total "
            f"<b>{tr.R.sum():+.2f}R</b>, best {tr.R.max():+.2f}R, "
            f"worst {tr.R.min():+.2f}R. &nbsp; With open positions at "
            f"{unreal:+,.2f}, the book stands at "
            f"<b>{realised + unreal:+,.2f}</b>.", SUB))

        TRD = [("ticker", "Symbol", 20), ("entry_time", "Entered", 25),
               ("exit_time", "Exited", 25), ("held", "Days", 13),
               ("reason", "Exit", 17), ("entry", "Entry", 18),
               ("exit", "Exit px", 18), ("shares", "Shares", 15),
               ("R", "R", 13), ("pnl", "P/L", 17), ("cum", "Cumulative", 21)]

        def trfmt(v, col):
            if pd.isna(v):
                return "-"
            if col in ("entry_time", "exit_time"):
                return f"{v:%m-%d %H:%M}"
            if col == "held":
                return f"{v:.1f}"
            if col == "shares":
                return f"{int(v):,}"
            if col in ("R", "pnl", "cum"):
                return f"{v:+,.2f}"
            if isinstance(v, float):
                return f"{v:,.2f}"
            return str(v)

        head = [Paragraph(f"<b>{lbl}</b>", CELL_H) for _, lbl, _ in TRD]
        body = [[Paragraph(sym_cell(r[c]) if c == "ticker" else trfmt(r[c], c), CELL)
                 for c, _, _ in TRD] for _, r in tr.iterrows()]
        t = Table([head] + body, colWidths=[w * mm for _, _, w in TRD],
                  repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
            ("TEXTCOLOR", (9, 1), (10, -1), GREEN if realised >= 0 else RED),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
        S.append(t)

        # Per symbol, which is the question the ledger cannot answer at a glance:
        # not "how did that trade go" but "is this name worth its slot at all".
        g = tr.groupby("ticker").agg(trades=("R", "size"), won=("R", lambda s: int((s > 0).sum())),
                                     R=("R", "sum"), pnl=("pnl", "sum")).reset_index()
        g = g.sort_values("pnl")
        S.append(Spacer(1, 4 * mm))
        S.append(Paragraph(f"Realised by symbol ({len(g)})", H2))
        SYM = [("ticker", "Symbol", 24), ("trades", "Trades", 18),
               ("won", "Won", 15), ("R", "R", 16), ("pnl", "P/L", 20)]
        head = [Paragraph(f"<b>{lbl}</b>", CELL_H) for _, lbl, _ in SYM]
        body = [[Paragraph(sym_cell(r[c]) if c == "ticker"
                           else (f"{r[c]:+,.2f}" if c in ("R", "pnl") else f"{int(r[c])}"),
                           CELL) for c, _, _ in SYM] for _, r in g.iterrows()]
        t = Table([head] + body, colWidths=[w * mm for _, _, w in SYM],
                  repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BAND]),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4)]))
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
WARN = ParagraphStyle("WARN", parent=SUB, fontSize=8.5, leading=11, textColor=RED)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None, help="scan date; default is the newest")
    ap.add_argument("--scans", default="scans")
    ap.add_argument("--config", default="paper/config.json")
    ap.add_argument("--positions", default="paper/open_positions.csv")
    ap.add_argument("--trades", default=None,
                    help="this book's trades.csv, for the realised P/L ledger. "
                         "Defaults to the file beside --positions")
    ap.add_argument("--outdir", default="reports")
    ap.add_argument("--label", default="", help="book name, shown in the heading")
    ap.add_argument("--tv-chart", default="",
                    help="TradingView chart URL to link symbols to, e.g. "
                         "https://www.tradingview.com/chart/AbCd1234/ - the slug "
                         "of the layout you analyse in. Without it the symbols "
                         "are plain text")
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
    trd = None
    tp = Path(args.trades) if args.trades else pp.parent / "trades.csv"
    if tp.exists():
        try:
            trd = pd.read_csv(tp)
        except Exception:  # noqa: BLE001
            trd = None

    global TV_BASE
    TV_BASE = args.tv_chart.strip()

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / f"{args.prefix}_{scan.stem}.pdf"
    build(scan, pdf, cfg, pos, args.label, trd)
    print(f"wrote {pdf}  ({pdf.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
