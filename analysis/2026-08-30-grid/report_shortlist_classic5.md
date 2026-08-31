# SuperTrend MTF — Backtest Report

- Watchlist: `C:\Users\ralf\Stock_Supertrend\watchlists\trending_shortlist.txt` (25 symbols)
- Window: 2018-01-01 -> today (daily bars)
- Engine: classic SuperTrend, ATR 10, factor 5.0
- Sides: LONG (close > SMA200, min strength 0)
- Higher-timeframe filter: off
- Relative strength: off
- Commission: 0.1% per side, 100% of equity per trade

## Per-symbol results

| ticker  | trades | longs | shorts | open_trade | win_rate_pct | avg_trade_pct | profit_factor | strategy_return_pct | buy_hold_return_pct | max_drawdown_pct | error |
| ------- | ------ | ----- | ------ | ---------- | ------------ | ------------- | ------------- | ------------------- | ------------------- | ---------------- | ----- |
| AMD     | 9      | 9     | 0      | True       | 66.7         | 22.9          | 4.77          | 714.2               | 4140.3              | -57.4            |       |
| ASML.AS | 14     | 14    | 0      | False      | 50.0         | 11.96         | 4.29          | 224.4               | 1006.8              | -35.6            |       |
| BWXT    | 12     | 12    | 0      | False      | 50.0         | 6.4           | 2.54          | 66.6                | 179.9               | -39.3            |       |
| DELL    | 9      | 9     | 0      | True       | 55.6         | 15.76         | 4.32          | 767.5               | 2071.1              | -37.6            |       |
| GE      | 5      | 5     | 0      | True       | 80.0         | 50.95         | 22.08         | 340.5               | 323.2               | -24.7            |       |
| HIMS    | 7      | 7     | 0      | False      | 57.1         | 18.62         | 2.92          | 90.1                | 194.3               | -67.2            |       |
| HOOD    | 5      | 5     | 0      | False      | 80.0         | 54.23         | 16.48         | 520.7               | 199.4               | -29.8            |       |
| IBKR    | 9      | 9     | 0      | True       | 66.7         | 12.35         | 5.47          | 194.2               | 578.3               | -28.7            |       |
| MBB.DE  | 10     | 10    | 0      | True       | 50.0         | 3.62          | 1.47          | 9.8                 | 131.0               | -44.2            |       |
| MRNA    | 5      | 5     | 0      | True       | 60.0         | 38.39         | 5.92          | 165.6               | 641.9               | -58.9            |       |
| MSFT    | 12     | 12    | 0      | True       | 75.0         | 7.26          | 10.07         | 147.2               | 553.7               | -16.7            |       |
| MU      | 10     | 10    | 0      | False      | 60.0         | 35.1          | 10.49         | 870.9               | 2090.6              | -39.2            |       |
| NOV.DE  | 11     | 11    | 0      | False      | 63.6         | 14.58         | 16.37         | 277.9               | 773.8               | -20.8            |       |
| NVDA    | 12     | 12    | 0      | False      | 41.7         | 45.62         | 8.25          | 932.6               | 4319.5              | -46.0            |       |
| PLTR    | 5      | 5     | 0      | True       | 40.0         | 62.59         | 9.35          | 326.4               | 1860.9              | -34.9            |       |
| QQQ     | 15     | 15    | 0      | False      | 73.3         | 6.11          | 7.64          | 125.8               | 377.4               | -11.9            |       |
| RDNT    | 7      | 7     | 0      | False      | 85.7         | 39.38         | 13.31         | 618.7               | 642.4               | -47.9            |       |
| RHM.DE  | 12     | 12    | 0      | False      | 50.0         | 29.72         | 6.9           | 702.4               | 1191.4              | -35.8            |       |
| RKLB    | 5      | 5     | 0      | False      | 40.0         | 11.21         | 2.49          | 32.0                | 560.8               | -52.7            |       |
| SMCI    | 11     | 11    | 0      | True       | 63.6         | 26.06         | 10.74         | 493.0               | 1628.7              | -61.1            |       |
| SPY     | 13     | 13    | 0      | True       | 69.2         | 4.88          | 5.66          | 73.8                | 226.1               | -10.6            |       |
| SZG.DE  | 7      | 7     | 0      | True       | 28.6         | 0.79          | 1.09          | -13.9               | 35.8                | -53.5            |       |
| TSLA    | 17     | 17    | 0      | False      | 41.2         | 11.95         | 2.07          | 88.8                | 1532.1              | -71.7            |       |
| VERX    | 3      | 3     | 0      | False      | 100.0        | 20.26         | inf           | 70.5                | -40.6               | -33.2            |       |
| VRSN    | 11     | 11    | 0      | True       | 27.3         | 0.67          | 1.18          | -3.5                | 171.5               | -46.2            |       |

## Aggregate

- Symbols tested: 25
- Median strategy return: 194.2% (median buy & hold: 578.3%)
- Symbols beating buy & hold: 3 / 25
- Closed trades: 236 (236 long / 0 short)
