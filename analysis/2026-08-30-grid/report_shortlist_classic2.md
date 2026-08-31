# SuperTrend MTF — Backtest Report

- Watchlist: `C:\Users\ralf\Stock_Supertrend\watchlists\trending_shortlist.txt` (25 symbols)
- Window: 2018-01-01 -> today (daily bars)
- Engine: classic SuperTrend, ATR 10, factor 2.0
- Sides: LONG (close > SMA200, min strength 0)
- Higher-timeframe filter: off
- Relative strength: off
- Commission: 0.1% per side, 100% of equity per trade

## Per-symbol results

| ticker  | trades | longs | shorts | open_trade | win_rate_pct | avg_trade_pct | profit_factor | strategy_return_pct | buy_hold_return_pct | max_drawdown_pct | error |
| ------- | ------ | ----- | ------ | ---------- | ------------ | ------------- | ------------- | ------------------- | ------------------- | ---------------- | ----- |
| AMD     | 44     | 44    | 0      | True       | 45.5         | 6.1           | 2.3           | 335.3               | 4140.3              | -41.4            |       |
| ASML.AS | 48     | 48    | 0      | False      | 43.8         | 2.17          | 1.82          | 99.4                | 1006.8              | -32.8            |       |
| BWXT    | 38     | 38    | 0      | False      | 50.0         | 0.88          | 1.36          | 16.3                | 179.9               | -32.6            |       |
| DELL    | 41     | 41    | 0      | True       | 48.8         | 3.71          | 2.13          | 140.3               | 2071.1              | -46.3            |       |
| GE      | 34     | 34    | 0      | False      | 44.1         | 4.57          | 2.8           | 212.6               | 323.2               | -28.5            |       |
| HIMS    | 23     | 23    | 0      | True       | 47.8         | 10.41         | 2.7           | 308.7               | 194.3               | -55.7            |       |
| HOOD    | 14     | 14    | 0      | True       | 57.1         | 16.07         | 4.43          | 298.7               | 199.4               | -39.4            |       |
| IBKR    | 38     | 38    | 0      | True       | 55.3         | 3.29          | 2.45          | 164.6               | 578.3               | -29.7            |       |
| MBB.DE  | 26     | 26    | 0      | False      | 46.2         | 4.24          | 2.53          | 112.4               | 131.0               | -51.2            |       |
| MRNA    | 21     | 21    | 0      | True       | 61.9         | 18.36         | 5.13          | 2795.2              | 641.9               | -44.9            |       |
| MSFT    | 45     | 45    | 0      | False      | 48.9         | 1.6           | 1.78          | 64.5                | 553.7               | -23.2            |       |
| MU      | 45     | 45    | 0      | True       | 33.3         | 2.87          | 1.68          | 73.5                | 2090.6              | -56.7            |       |
| NOV.DE  | 46     | 46    | 0      | True       | 43.5         | 3.09          | 2.37          | 188.9               | 773.8               | -25.1            |       |
| NVDA    | 44     | 44    | 0      | True       | 45.5         | 4.62          | 2.41          | 241.3               | 4319.5              | -64.6            |       |
| PLTR    | 26     | 26    | 0      | False      | 53.8         | 5.36          | 2.4           | 156.1               | 1860.9              | -41.1            |       |
| QQQ     | 49     | 49    | 0      | False      | 46.9         | 0.99          | 1.66          | 36.9                | 377.4               | -21.7            |       |
| RDNT    | 38     | 38    | 0      | True       | 44.7         | 3.35          | 1.99          | 164.7               | 642.4               | -32.0            |       |
| RHM.DE  | 37     | 37    | 0      | False      | 35.1         | 6.15          | 2.86          | 284.4               | 1191.4              | -44.5            |       |
| RKLB    | 18     | 18    | 0      | False      | 61.1         | 9.75          | 2.86          | 167.7               | 560.8               | -48.0            |       |
| SMCI    | 38     | 38    | 0      | True       | 31.6         | 5.62          | 2.05          | 150.6               | 1628.7              | -55.3            |       |
| SPY     | 53     | 53    | 0      | False      | 47.2         | 0.41          | 1.35          | 7.6                 | 226.1               | -23.9            |       |
| SZG.DE  | 26     | 26    | 0      | True       | 57.7         | 6.27          | 3.06          | 234.3               | 35.8                | -34.3            |       |
| TSLA    | 36     | 36    | 0      | False      | 41.7         | 7.79          | 2.64          | 435.2               | 1532.1              | -41.0            |       |
| VERX    | 12     | 12    | 0      | False      | 41.7         | 3.94          | 2.36          | 41.6                | -40.6               | -33.2            |       |
| VRSN    | 30     | 30    | 0      | True       | 40.0         | 2.07          | 2.02          | 55.6                | 171.5               | -32.9            |       |

## Aggregate

- Symbols tested: 25
- Median strategy return: 164.6% (median buy & hold: 578.3%)
- Symbols beating buy & hold: 5 / 25
- Closed trades: 870 (870 long / 0 short)
