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
