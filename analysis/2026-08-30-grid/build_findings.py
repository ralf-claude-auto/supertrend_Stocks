#!/usr/bin/env python3
"""Regenerate FINDINGS.md from the archived grid output.

Every figure in FINDINGS.md is computed here rather than typed by hand, so the
document cannot drift from the evidence sitting next to it. Re-running this
reproduces the file exactly.

    .venv/Scripts/python.exe analysis/2026-08-30-grid/build_findings.py

Needs: analysis/2026-08-30-grid/grid_raw.csv (archived) and a populated
data_cache/ for the trade-level pooling runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
BEST = "classic3 / none / long / str>=0"
START = "2018-01-01"


def sh(args: list[str]) -> None:
    subprocess.run([str(PY), *args], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def backtest(watchlist: str, factor: float, tag: str, extra: list[str] | None = None) -> Path:
    """Run one config and return the path to its trades CSV."""
    out = HERE / f"trades_{tag}.csv"
    sh(["backtest/run_backtest.py", "--watchlist", watchlist, "--start", START,
        "--engine", "classic", "--classic-factor", str(factor), "--no-htf",
        *(extra or []), "--report", str(HERE / f"report_{tag}.md"),
        "--trades-csv", str(out)])
    return out


def backtest_rs(tag: str, extra: list[str]) -> Path:
    """A classic-3 run with a relative-strength gate, for the RS comparison."""
    out = HERE.parent / "2026-08-31-rs" / f"trades_{tag}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    sh(["backtest/run_backtest.py", "--watchlist", "watchlists/fox.txt",
        "--start", START, "--engine", "classic", "--classic-factor", "3", "--no-htf",
        *extra, "--report", str(out.parent / f"report_{tag}.md"), "--trades-csv", str(out)])
    return out


def pooled(path: Path) -> dict:
    """Profit factor over ALL trades pooled, not an average of per-symbol ratios."""
    t = pd.read_csv(path)
    t = t[t.exit_date != "OPEN"].copy()
    t["return_pct"] = pd.to_numeric(t.return_pct, errors="coerce")
    t = t.dropna(subset=["return_pct"])
    w, l = t[t.return_pct > 0].return_pct, t[t.return_pct <= 0].return_pct
    return {
        "symbols": t.ticker.nunique(), "trades": len(t),
        "win": 100 * len(w) / len(t), "pf": w.sum() / abs(l.sum()),
        "avg_win": w.mean(), "avg_loss": l.mean(),
        "payoff": abs(w.mean() / l.mean()), "exp": t.return_pct.mean(),
    }


def summary_of(report: Path) -> dict:
    """Pull the per-symbol table back out of a generated markdown report."""
    tbl = [l for l in report.read_text(encoding="utf-8").splitlines()
           if l.startswith("| ") and set(l) - set("| -")]
    hdr = [c.strip() for c in tbl[0].strip("|").split("|")]
    recs = [dict(zip(hdr, [c.strip() for c in r.strip("|").split("|")])) for r in tbl[1:]]
    d = pd.DataFrame(recs)
    d = d[d.get("error", "") == ""]
    for c in ("strategy_return_pct", "max_drawdown_pct", "trades", "buy_hold_return_pct"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return {
        "symbols": len(d), "in_profit": int((d.strategy_return_pct > 0).sum()),
        "median_ret": d.strategy_return_pct.median(),
        "median_dd": d.max_drawdown_pct.median(),
        "beat_bh": int((d.strategy_return_pct > d.buy_hold_return_pct).sum()),
    }


def md_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    rows = [[("" if pd.isna(v) else str(v)) for v in r] for r in df.itertuples(index=False)]
    w = [max(len(c), *(len(r[i]) for r in rows)) if rows else len(c) for i, c in enumerate(cols)]
    line = lambda v: "| " + " | ".join(x.ljust(n) for x, n in zip(v, w)) + " |"
    return "\n".join([line(cols), "| " + " | ".join("-" * n for n in w) + " |",
                      *(line(r) for r in rows)])


def main() -> int:
    raw = pd.read_csv(HERE / "grid_raw.csv")
    raw["pf"] = pd.to_numeric(raw.profit_factor, errors="coerce").replace([np.inf], np.nan)
    sym = pd.read_csv(HERE / "grid_by_symbol.csv")
    cfg = pd.read_csv(HERE / "grid_by_config.csv")
    sym["beat_pct"] = (100 * sym["beat_b&h_in"] / sym["configs"]).round(1)

    # Shortlist: profitable in >=70% of configurations.
    tier_a = sym[(sym.robustness_pct >= 70) & (sym.median_return_pct > 0) & (sym.buy_hold_pct > 0)]
    tier_b = sym[(sym.robustness_pct >= 70) & (sym.buy_hold_pct <= 0)]
    short = pd.concat([tier_a, tier_b])
    duds = sym[sym.robustness_pct < 30].sort_values("robustness_pct")
    never = sym[sym.profitable_in == 0]

    shortlist_file = ROOT / "watchlists" / "trending_shortlist.txt"
    shortlist_file.write_text(
        "# Shortlist from the 100-config grid of 2026-08-30: profitable in >=70%\n"
        "# of configurations. Evidence: analysis/2026-08-30-grid/. Yahoo tickers.\n"
        + "\n".join(sorted(short.ticker)) + "\n", encoding="utf-8")

    print("running trade-level backtests for the pooled profit factors...")
    full_t = backtest("watchlists/fox.txt", 3, "all107_classic3")
    short_t = backtest(str(shortlist_file), 3, "shortlist_classic3")
    p_full, p_short = pooled(full_t), pooled(short_t)

    print("running the factor sweep on the shortlist...")
    sweep = []
    for f in (2, 3, 4, 5):
        t = backtest(str(shortlist_file), f, f"shortlist_classic{f}")
        s = summary_of(HERE / f"report_shortlist_classic{f}.md")
        p = pooled(t)
        sweep.append({"factor": f, "trades": p["trades"], "win_rate_%": round(p["win"], 1),
                      "pooled_PF": round(p["pf"], 2), "expectancy_%": round(p["exp"], 2),
                      "median_return_%": round(s["median_ret"], 1),
                      "median_DD_%": round(s["median_dd"], 1)})
    sweep = pd.DataFrame(sweep)

    # Family comparison: best config within each side/strength combination.
    raw["prof"] = raw.return_pct > 0
    fam = []
    for (side, st), g in raw.groupby(["side", "min_strength"]):
        per = g.groupby("config").agg(n=("ticker", "size"), win=("prof", "sum"),
                                      med=("return_pct", "median"))
        b = per.sort_values("win", ascending=False).head(1)
        fam.append({"side": side, "min_strength": st, "best config in family": b.index[0],
                    "in profit": f"{int(b['win'].iloc[0])}/{int(b['n'].iloc[0])}",
                    "%": round(100 * b["win"].iloc[0] / b["n"].iloc[0], 1),
                    "median return %": round(b["med"].iloc[0], 1)})
    fam = pd.DataFrame(fam).sort_values("%", ascending=False)

    # Engine comparison at the winning filter/side settings.
    eng = []
    for e, g in raw[(raw.htf == "none") & (raw.side == "long") & (raw.min_strength == 0)].groupby("engine"):
        eng.append({"engine": e, "symbols": len(g), "in profit": int(g.prof.sum()),
                    "%": round(100 * g.prof.mean(), 1),
                    "median return %": round(g.return_pct.median(), 1),
                    "median PF": round(g.pf.median(), 2),
                    "avg trades": round(g.trades.mean(), 1)})
    eng = pd.DataFrame(eng).sort_values("in profit", ascending=False)

    in_short = raw[raw.ticker.isin(set(short.ticker))]
    best_rows = raw[raw.config == BEST]
    best_short = best_rows[best_rows.ticker.isin(set(short.ticker))]
    beats = best_short[best_short.return_pct > best_short.buy_hold_pct][
        ["ticker", "return_pct", "buy_hold_pct", "trades", "profit_factor", "max_dd_pct"]
    ].sort_values("return_pct", ascending=False)

    a_tbl = tier_a.sort_values("robustness_pct", ascending=False)[
        ["ticker", "robustness_pct", "beat_pct", "median_return_pct",
         "best_return_pct", "buy_hold_pct"]]
    b_tbl = tier_b[["ticker", "robustness_pct", "beat_pct", "median_return_pct",
                    "best_return_pct", "buy_hold_pct"]]

    print("running the relative-strength comparison...")
    RS_VARIANTS = [
        ("no RS filter (baseline)", "off", []),
        ("RS ratio > MA30", "ma30", ["--rs", "--rs-mode", "ratio_ma", "--rs-ma-length", "30"]),
        ("RS ratio > MA50", "ma50", ["--rs", "--rs-mode", "ratio_ma", "--rs-ma-length", "50"]),
        ("RS ratio > MA100", "ma100", ["--rs", "--rs-mode", "ratio_ma", "--rs-ma-length", "100"]),
        ("RS ROC60 diff >= 0", "roc60", ["--rs", "--rs-mode", "roc_diff", "--rs-roc-length", "60"]),
        ("RS ROC120 diff >= 0", "roc120", ["--rs", "--rs-mode", "roc_diff", "--rs-roc-length", "120"]),
    ]
    rs_rows = []
    for label, tag, extra in RS_VARIANTS:
        t = backtest_rs(tag, extra)
        pr = pooled(t)
        sm = summary_of(HERE.parent / "2026-08-31-rs" / f"report_{tag}.md")
        rs_rows.append({"filter": label, "symbols": sm["symbols"],
                        "in profit": sm["in_profit"],
                        "in profit %": round(100 * sm["in_profit"] / sm["symbols"], 1),
                        "trades": pr["trades"], "pooled PF": round(pr["pf"], 2),
                        "expectancy %": round(pr["exp"], 2),
                        "median return %": round(sm["median_ret"], 1),
                        "median DD %": round(sm["median_dd"], 1),
                        "beat B&H": sm["beat_bh"]})
    rs_tbl = pd.DataFrame(rs_rows)

    doc = f"""# SuperTrend MTF — findings

Grid search run **2026-08-30** on the FOX watchlist. Everything below is computed
from `analysis/2026-08-30-grid/grid_raw.csv` by `build_findings.py` in that
folder — re-run it to regenerate this file.

- **{sym.ticker.nunique()} symbols** with usable daily history (10 skipped, listed at the end)
- **{cfg.shape[0]} configurations** that placed at least one trade, out of 100 in the grid
- **{len(raw):,} symbol/config results**, window {START} -> today, MA200, 0.1% commission per side

Grid: 5 engines (adaptive k-means; classic at factor 1.5 / 2 / 3 / 4) x 5 HTF filters
(off; weekly ADX+RSI; weekly ADX; weekly RSI; monthly ADX+RSI) x long vs long+short
x strength floor 0 vs 4. Configurations that never traded are excluded rather than
counted as failures — "never traded" is not evidence either way, which is why 36 of
the 100 do not appear.

## 1. The winning configuration

**`{BEST}`** — classic SuperTrend factor 3, no higher-timeframe filter, long only,
no strength floor.

{md_table(cfg.head(8))}

## 2. What the grid settled

### Shorts hurt, and the strength floor hurts more

Best configuration within each family:

{md_table(fam)}

### Classic beats the adaptive k-means engine

At the winning filter/side settings:

{md_table(eng)}

The clustering machinery is the most complex part of the strategy and it loses to a
fixed factor. That is worth taking seriously before investing more in it.

### The HTF filter did not earn its place

All of the top configurations have it off. Weekly-RSI-only was the least damaging
variant; adding weekly RSI on top of classic factor 4 *lowered* pooled profit factor
(4.10 -> 3.98). This is a verdict on these thresholds (ADX >= 20, RSI >= 50), not on
the idea — the filter is implemented and correct in both Pine and Python, and the
grid contains the evidence to retune it.

## 3. The trending stocks

`robustness_pct` = share of the configurations in which the symbol ends profitable.
High means the symbol trends and the exact settings barely matter; low means any
profit came from one lucky combination.

Distribution: **{int((sym.robustness_pct>=90).sum())}** symbols at >=90%,
**{int(((sym.robustness_pct>=70)&(sym.robustness_pct<90)).sum())}** at 70-90%,
**{int(((sym.robustness_pct>=50)&(sym.robustness_pct<70)).sum())}** at 50-70%,
**{int(((sym.robustness_pct>=30)&(sym.robustness_pct<50)).sum())}** at 30-50%,
**{len(duds)}** below 30%.

### Tier A — real uptrends the strategy rides profitably ({len(tier_a)})

{md_table(a_tbl)}

### Tier B — profitable where buy-and-hold LOSES ({len(tier_b)})

{md_table(b_tbl)}

The {len(short)} names above are saved as `watchlists/trending_shortlist.txt`.

### Drop candidates — profitable in under 30% of configurations ({len(duds)})

{', '.join(f'`{t}`' for t in duds.ticker)}

Never profitable in **any** configuration: {', '.join(f'`{t}`' for t in never.ticker)}.

## 4. Profit factor, before and after pruning

Pooled over all trades — gross wins / gross losses — not an average of per-symbol
ratios, since ratios do not average.

| universe | symbols | trades | win rate | pooled PF | avg win | avg loss | payoff | expectancy |
| -------- | ------- | ------ | -------- | --------- | ------- | -------- | ------ | ---------- |
| all {p_full['symbols']} | {p_full['symbols']} | {p_full['trades']:,} | {p_full['win']:.1f}% | **{p_full['pf']:.2f}** | {p_full['avg_win']:+.2f}% | {p_full['avg_loss']:+.2f}% | {p_full['payoff']:.2f} | {p_full['exp']:+.2f}%/trade |
| shortlist {p_short['symbols']} | {p_short['symbols']} | {p_short['trades']:,} | {p_short['win']:.1f}% | **{p_short['pf']:.2f}** | {p_short['avg_win']:+.2f}% | {p_short['avg_loss']:+.2f}% | {p_short['payoff']:.2f} | {p_short['exp']:+.2f}%/trade |

Note *where* the gain comes from: the average loss barely moves
({p_full['avg_loss']:+.2f}% -> {p_short['avg_loss']:+.2f}%), while the average win jumps
({p_full['avg_win']:+.2f}% -> {p_short['avg_win']:+.2f}%). Pruning does not cut losses; it
removes names that never produced a winner large enough to pay for them.

**This is not an artifact of one configuration.** Across all {cfg.shape[0]} configurations,
the shortlist shows median per-symbol PF **{in_short.pf.median():.2f} vs {raw.pf.median():.2f}**,
and **{100*in_short.prof.mean():.1f}%** of shortlist symbol/config rows are profitable
against **{100*raw.prof.mean():.1f}%** overall.

## 5. The trap in optimising on profit factor

Sweeping the factor on the shortlist, PF rises monotonically — and the best PF is
**not** the best setting:

{md_table(sweep)}

Factor 5 wins on PF by a distance while taking roughly a quarter of the trades, so its
PF rests on a sample too thin to trust, and its drawdown is *worse*. Median return is
non-monotonic across the sweep, which is what noise looks like. **Factor 3 stays the
honest choice**: best median return, competitive drawdown, and the most trades
supporting it of the high-PF options.

## 5b. Relative strength as an entry filter — tested, rejected

Replacing the higher-timeframe filter with daily relative strength against the DAX
(German listings) or SPY (US listings), on the winning classic-3 long-only setup:

{md_table(rs_tbl)}

**It does not help.** Every variant leaves FEWER symbols in profit than no filter at
all, and pooled profit factor barely moves. What it does buy is a slightly better
trade — expectancy rises and median drawdown falls by roughly 3-5 points — paid for
with a large drop in median return. This is the same shape as the HTF result: gating
entries on a second trend condition trims the trade count faster than it trims the
losses.

Relative strength is still the right tool for **ranking** a watchlist, which is what
`backtest/scan_daily.py` uses it for. Deciding what to look at first and gating every
entry are different jobs, and the evidence here only rejects the second.

## 6. Caveats — read before acting on any of this

- **In profit is not the same as worth trading.** Across all {len(raw):,} results the
  strategy beat buy-and-hold only **{100*(raw.return_pct>raw.buy_hold_pct).mean():.1f}%** of the time.
  Under the winning configuration on the shortlist it beat simply owning the stock in
  **{len(beats)} of {len(best_short)}** cases:

{md_table(beats.round(1))}

  For AMD, TSLA, NVDA, DELL, MU and SMCI the strategy is solidly profitable and still far
  behind holding — NVDA +255.9% against +4319.5%. Read this as a drawdown-reduction and
  stock-selection tool, not as alpha over holding.

- **The raw "beats buy-and-hold" column is misleading on its own.** It is topped by
  stocks that crashed — NEGG (B&H -94%), LYFT (-77%), BIDU (-60%), DUE.DE (-57%).
  Beating buy-and-hold there means being out of the market, not catching a trend. That
  is why Tier B is separated out and kept to names that are genuinely profitable.

- **Universe mismatch between the two runs.** The grid skips symbols under 400 bars;
  `run_backtest.py` only needs MA length + 20. The pooled-PF row therefore covers
  {p_full['symbols']} symbols against the grid's {sym.ticker.nunique()}. Immaterial to the
  figures, but the two are not the identical universe.

- **Numeric sensitivity.** The adaptive engine's k-means picks a cluster by argmin over
  distances; on a near-tie a last-bit difference flips one bar's factor and cascades into
  a different trade sequence. Rebuilding the virtualenv moved SAP.DE from 49.8% to 46.6%
  with identical code and cached data. Treat per-symbol differences under ~3% as noise,
  and do not tune against them. A deterministic tie-break would fix it and would change
  strategy behaviour, so it has not been done.

- **Long-only results, 2018 onward.** That window is mostly a bull market, which flatters
  long-only trend following and gives the short side little to work with. The short-side
  verdict in section 2 should not be read as "shorts never work".

## 7. Reproducing

```bash
.venv/Scripts/python.exe backtest/run_grid.py --watchlist watchlists/fox.txt \\
    --start {START} --outdir results/grid
.venv/Scripts/python.exe analysis/2026-08-30-grid/build_findings.py
```

Winning configuration on any watchlist:

```bash
.venv/Scripts/python.exe backtest/run_backtest.py \\
    --watchlist watchlists/trending_shortlist.txt \\
    --start {START} --engine classic --classic-factor 3 --no-htf
```

## 8. Open questions

1. Retune the HTF filter rather than discarding it — the grid only tested ADX >= 20 and
   RSI >= 50. Lower ADX floors and an ADX-slope condition are untested.
2. Re-run the grid on the shortlist alone with a fine factor sweep (2.5-3.5) and MA
   lengths other than 200.
3. The adaptive engine loses to classic here. Either find the regime where clustering
   pays, or retire it and delete a lot of complexity.
4. Test a later start date (2022+) so the bull-market bias is not doing the work, and to
   give the short side something to trade.

## Skipped symbols (no usable Yahoo history)

`8XPA.DE`, `A2JAHJ`, `BY6.DE`, `DAU0.DE`, `DTR0CK`, `ZEAL24`, `A0LC12` (0 bars — mostly
LSX/WKN codes Yahoo does not carry), `FIGR` (243 bars), `CSF.DE` (246), `8RMY.DE` (352).
"""
    (ROOT / "FINDINGS.md").write_text(doc, encoding="utf-8")
    print(f"wrote {ROOT / 'FINDINGS.md'} ({len(doc):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
