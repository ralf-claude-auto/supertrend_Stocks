# Stock_Supertrend — SuperTrend AI + 200 MA Backtest

Backtests this daily-timeframe strategy on a TradingView watchlist
(German + US stocks):

- **Filter:** close above the 200-day simple moving average
- **Buy:** SuperTrend AI (LuxAlgo-style k-means clustering) crosses **up** (bullish flip)
- **Sell:** SuperTrend AI crosses **down** (bearish flip)
- Long only, daily bars, signals executed on the closing price of the signal bar

There are two ways to run the backtest — inside TradingView (per symbol) and
in Python (whole watchlist at once). Both use the same logic and the same
default parameters as LuxAlgo's SuperTrend AI: ATR length 10, factor range
1–5 step 0.5, performance memory 10, "Best" cluster.

---

## 0. What the current Pine strategy does

`pine/supertrend_mtf_strategy.pine` (Pine **v6**) is the one to use. On top of the
original long-only rules it adds:

- **Two selectable engines.** *Adaptive (k-means)* is the SuperTrend AI clustering
  from before; *Classic* is a single `ta.supertrend` at a fixed factor. Both publish
  the same 0-9 signal strength, so the strength filter means the same thing either
  way and the two are directly comparable.
- **A short side with its own parameters** — own MA length and type, own minimum
  strength, own MA exit. It is *not* forced to mirror the long side. Shorts are OFF
  by default, and `Stop-and-reverse` controls whether a flip may close one side and
  open the other on the same bar.
- **A higher-timeframe filter.** Trend strength via ADX (with optional DI
  agreement) and momentum via RSI / ROC / MACD histogram, both pulled from a
  configurable HTF (default weekly). `Use only CLOSED higher-timeframe bars` is on
  by default so the filter cannot repaint.
- **A status table** (top right) showing the live HTF readings and whether longs
  and shorts currently pass — so you can see *why* a flip was skipped. Rejected
  flips are also marked on the chart with grey crosses.

The defaults reproduce the old long-only behaviour, plus the HTF filter.

## 0b. Daily scan — new signals, uptrending, downtrending

```bash
.venv/Scripts/python.exe backtest/scan_daily.py --watchlist watchlists/fox.txt
```

Writes `scans/<date>.md` and `scans/<date>.csv`, and prints four lists — **NEW
SIGNAL** (flipped bullish on the latest bar, above the MA), **NEW EXIT** (flipped
bearish), **UPTRENDING** (holding a bullish SuperTrend above the MA) and
**DOWNTRENDING** — each sorted by relative strength, strongest first.

Relative strength is the symbol's 60-day return minus its benchmark's: **^GDAXI for
German listings, SPY for US**. Because it is benchmark-relative, a German and a US
name can be ranked against each other directly. `rs_rank` is the percentile within
that day's scan.

Run it **after the close** — Yahoo publishes end-of-day bars, so intraday it just
repeats yesterday. The header states which close the data is from. Benchmarks are
refetched every run, and any symbol whose cache is older than the benchmark is
refetched too, so the scan cannot silently report a stale day.

Note that relative strength is used here to *rank and classify*, not to gate
entries — as an entry filter it tested worse than no filter at all (FINDINGS.md
section 5b). `--rs` on `run_backtest.py` enables the gate if you want to re-test it.

## 0c. Daily list history and the risk:reward backtests

```bash
# rebuild the SIGNAL / LONG / SHORT lists for every past session
.venv/Scripts/python.exe backtest/backfill_scans.py --days 90

# next-day entry, stop at the SuperTrend, target at rr x risk
.venv/Scripts/python.exe backtest/run_rr.py --rr 3

# same signals, but time the entry on a 1h MA cross instead
.venv/Scripts/python.exe backtest/run_rr_1h.py --rr 3

# daily signal ARMS the stock; the 1h SuperTrend executes entries while armed
.venv/Scripts/python.exe backtest/run_armed_1h.py --rr 3 --stop hourly
```

`run_armed_1h.py` is the best of the three. The daily signal arms a stock and it
stays armed until the daily SuperTrend breaks or price closes below the MA, so an
entry is not restricted to the day after the signal. Every bullish flip of the
SAME SuperTrend on 1h bars is an entry while armed, and the 1h SuperTrend at entry
is the stop - roughly 3% rather than the daily line's ~14%.

Use `--stop hourly`. With `--stop daily` the stop sits on the daily SuperTrend,
which is the very line whose break disarms the position, so it is almost never
reached (11 of 644 exits) and every R is measured against risk that is never
actually taken. It reports a profit factor above 5 and means nothing.

The run also re-tests the trades under a `max_open` position limit, because the
unconstrained figures assume every signal is funded the instant it fires.

**A slot limit is first-come-first-served, not a ranking.** With `max_open 10` you
hold the first ten signals that fired, not the ten strongest names. Selecting by
relative strength instead was tested and is worse: gating on the top half or top
third of RS lowers average R, total R and drawdown at every cap. At 10 slots,
first-come gives avg R 0.59 / 372R / -13.2% drawdown against 0.45 / 273R / -20.2%
for the top-half gate. Rotation - swapping the weakest open position for a
stronger new signal - earns more total R (571R) only by carrying more risk
(-19.2%) and far more churn. This matches the earlier result in FINDINGS.md
section 5b: relative strength is a good way to decide what to LOOK at and a bad
way to decide what to TRADE.

`backfill_scans.py` writes one CSV per session plus `_signals.csv`, which feeds
both backtests. Use a long window (`--days 1825`) for the backtests: over 90 days
most 3:1 trades have not resolved yet, and a trade that has not resolved cannot
be counted.

Both backtests report in **R** (multiples of the initial risk) over RESOLVED
trades only, and the equity curve assumes a fixed fraction of capital risked per
trade (1% by default) rather than compounding percent returns, which would imply
putting all capital into each of many overlapping positions.

**Note the hourly limit**: Yahoo serves ~730 days of 1h bars, so `run_rr_1h.py`
covers roughly two years while `run_rr.py` covers five. It prints a daily
next-open baseline over the SAME signals so the two are comparable.

## 0d. Paper log — forward testing, no broker

```bash
.venv/Scripts/python.exe backtest/paper_log.py     # run after the close, daily
```

First run writes `paper/config.json` and starts the log from that day. Every later
run replays the whole period and rewrites `paper/log.md`, `open_positions.csv`,
`trades.csv` and `equity.csv`.

It **replays** rather than keeping a running position file. The strategy is
deterministic and causal, so replaying the same rules over the same bars always
reaches the same decisions, and the run is idempotent - execute it twice, or skip
a week, and the result is identical. A mutable state file would drift on a missed
or interrupted run.

Positions are sized from current equity: `shares = risk_frac x equity / risk per
share`, so a 0.33% risk on 16,900 puts about 56 at risk per trade whatever the
share price. One position per symbol; slots are first-come-first-served.

Nothing here places an order - it produces the list you would place, with share
counts, stop and target. Use it to build an out-of-sample record before committing
capital: the backtest is in-sample by construction and its window was a favourable
one.

## 1. Backtest inside TradingView (per symbol)

1. Open TradingView, set the chart to **1D**.
2. Open the **Pine Editor**, paste the contents of
   [`pine/supertrend_ai_200ma_strategy.pine`](pine/supertrend_ai_200ma_strategy.pine),
   click **Add to chart**.
3. Open the **Strategy Tester** tab.
4. Click through the symbols of your **FOX** watchlist — the tester
   recomputes per symbol (net profit, win rate, profit factor, drawdown,
   trade list).

Settings you can change in the strategy's gear menu:
- Factor range / step, performance memory, cluster (Best/Average/Worst)
- **Minimum Signal Strength (0–9)** — filter out weak flips (0 = take all)
- SMA length (default 200) and an optional extra exit when close drops
  below the SMA
- Backtest start/end date, commission (default 0.1% per side)

The strategy warns on the chart if the timeframe is not 1D.

> Note: TradingView cannot auto-run a strategy across a whole watchlist on a
> free/Pro plan — that's what the Python runner below is for.

## 2. Batch backtest in Python (whole watchlist)

### Get your FOX watchlist out of TradingView

In TradingView: watchlist panel → watchlist menu (top right) →
**Export list...** → save the `.txt` file as `watchlists/fox.txt`
(overwrite the sample). The export format
(`XETR:SAP,NASDAQ:AAPL,...` with `###Section` headers) is parsed directly;
German exchange prefixes (XETR, GETTEX, FWB, ...) are mapped to the right
Yahoo Finance suffixes automatically. Plain one-ticker-per-line files
(`SAP.DE`, `AAPL`) work too.

### Run

```bash
pip install -r requirements.txt
python backtest/run_backtest.py --watchlist watchlists/fox.txt --start 2018-01-01
```

Output:
- Console: one summary line per symbol
- `results/report.md` — per-symbol table + aggregate stats
- `results/trades.csv` — every trade (entry/exit date & price, return,
  exit reason, signal strength)

### Options — every flag mirrors a Pine input

The Python runner implements the **same strategy** as
`pine/supertrend_mtf_strategy.pine`, so a setting you like in the Strategy Tester
can be reproduced across the whole watchlist. `--help` lists everything; the
groups are:

```bash
# engine
--engine adaptive|classic   --atr-length 10   --classic-factor 3
--min-mult 1 --max-mult 5 --step 0.5 --perf-alpha 10 --from-cluster best

# long side
--no-long   --long-ma-length 200   --long-ma-type sma|ema
--long-min-strength 0   --long-exit-below-ma

# short side (independent — not mirrored)
--short   --short-ma-length 200   --short-ma-type sma|ema
--short-min-strength 0   --short-exit-above-ma   --no-reverse

# higher-timeframe filter
--no-htf   --htf W        # D, W, M, 2W, 3M, 12M
--no-htf-adx --adx-length 14 --adx-smooth 14 --adx-min 20 --no-adx-di
--no-htf-mom --mom-mode rsi|roc|macd --rsi-length 14
--rsi-long-min 50 --rsi-short-max 50 --roc-length 10
--macd-fast 12 --macd-slow 26 --macd-signal 9
--zero-long-min 0 --zero-short-max 0
```

`--ma-length`, `--min-strength` and `--exit-below-ma` still work as aliases for
their long-side equivalents.

```bash
# classic SuperTrend, long AND short, no higher-timeframe filter
python backtest/run_backtest.py --watchlist watchlists/fox.txt \
    --engine classic --classic-factor 3 --short --no-htf
```

**On the higher-timeframe filter and repainting.** Each HTF bar is labelled with
its period end, and a daily bar may only read HTF labels strictly earlier than
itself — so during the current week you see last week's closed reading, matching
the Pine default (`Use only CLOSED higher-timeframe bars`). The forming-bar mode
is deliberately not implemented here: reproducing it in a batch backtest means
letting a bar read an aggregate its own future contributed to.

Verified against Pine on XETR:HAG — weekly ADX 12.75 / 12.7, DI+ 27.56 / 27.5,
DI- 16.66 / 16.7, RSI 56.32 / 56.16 (the small RSI gap is Yahoo's adjusted feed
vs TradingView's, not the logic).

Data is daily OHLC from Yahoo Finance (auto-adjusted), cached in
`data_cache/` — delete that folder to force fresh downloads.

## Repository layout

```
pine/supertrend_mtf_strategy.pine        TradingView strategy (Pine v6) — CURRENT
pine/supertrend_ai_200ma_strategy.pine   older long-only version (Pine v5)
backtest/supertrend_ai.py                SuperTrend AI (k-means) indicator port
backtest/engine.py                       long-only backtest engine
backtest/data.py                         watchlist parsing + data download/cache
backtest/run_backtest.py                 CLI batch runner
watchlists/fox.txt                       your FOX watchlist (sample included)
```

## Notes on methodology

- The SuperTrend AI logic is a re-implementation of the clustering concept
  from LuxAlgo's open-source "SuperTrend AI (Clustering)" indicator: a bank
  of SuperTrends (factors 1–5) is scored by exponentially weighted
  directional performance, k-means (k=3) clusters the scores each bar, and
  the mean factor of the chosen cluster drives the live SuperTrend.
  Small numeric differences vs. the original TradingView indicator are
  possible (data feed, warmup length), but signals should match closely.
- Fills are on the **close of the signal bar** (like
  `process_orders_on_close=true` in Pine). No slippage is modeled beyond
  the commission setting.
- German symbols use the XETRA feed (`.DE`); results in EUR, US results in
  USD — per-symbol returns are percentage-based so they aggregate fine.
