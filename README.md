# Unicorn Trader — SuperTrend AI + 200 MA Backtest

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

Useful options:

```bash
python backtest/run_backtest.py --watchlist watchlists/fox.txt \
    --start 2015-01-01 --end 2025-12-31 \
    --min-strength 4 \        # only take signals with strength >= 4
    --exit-below-ma \         # additionally exit when close crosses under SMA200
    --commission 0.1          # % per side
```

Data is daily OHLC from Yahoo Finance (auto-adjusted), cached in
`data_cache/` — delete that folder to force fresh downloads.

## Repository layout

```
pine/supertrend_ai_200ma_strategy.pine   TradingView strategy (Pine v6)
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
