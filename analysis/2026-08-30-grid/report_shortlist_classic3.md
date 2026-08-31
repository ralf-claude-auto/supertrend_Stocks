# SuperTrend MTF — Backtest Report

- Watchlist: `C:\Users\ralf\Stock_Supertrend\watchlists\trending_shortlist.txt` (25 symbols)
- Window: 2018-01-01 -> today (daily bars)
- Engine: classic SuperTrend, ATR 10, factor 3.0
- Sides: LONG (close > SMA200, min strength 0)
- Higher-timeframe filter: off
- Relative strength: off
- Commission: 0.1% per side, 100% of equity per trade

## Per-symbol results

| ticker  | trades | longs | shorts | open_trade | win_rate_pct | avg_trade_pct | profit_factor | strategy_return_pct | buy_hold_return_pct | max_drawdown_pct | error |
| ------- | ------ | ----- | ------ | ---------- | ------------ | ------------- | ------------- | ------------------- | ------------------- | ---------------- | ----- |
| AMD     | 24     | 24    | 0      | False      | 54.2         | 7.22          | 2.22          | 173.7               | 4140.3              | -34.9            |       |
| ASML.AS | 24     | 24    | 0      | True       | 58.3         | 6.21          | 3.75          | 209.8               | 1006.8              | -23.9            |       |
| BWXT    | 24     | 24    | 0      | False      | 54.2         | 0.36          | 1.11          | -4.3                | 179.9               | -35.2            |       |
| DELL    | 14     | 14    | 0      | True       | 50.0         | 9.03          | 3.53          | 635.1               | 2071.1              | -28.1            |       |
| GE      | 19     | 19    | 0      | False      | 31.6         | 5.9           | 2.36          | 97.5                | 323.2               | -32.8            |       |
| HIMS    | 15     | 15    | 0      | False      | 46.7         | 8.35          | 2.47          | 131.8               | 194.3               | -47.6            |       |
| HOOD    | 9      | 9     | 0      | True       | 66.7         | 30.39         | 7.12          | 426.1               | 199.4               | -34.2            |       |
| IBKR    | 20     | 20    | 0      | True       | 60.0         | 7.87          | 4.94          | 250.3               | 578.3               | -25.0            |       |
| MBB.DE  | 17     | 17    | 0      | False      | 23.5         | 3.37          | 1.97          | 39.5                | 131.0               | -29.9            |       |
| MRNA    | 15     | 15    | 0      | True       | 46.7         | 12.69         | 3.62          | 171.2               | 641.9               | -47.7            |       |
| MSFT    | 23     | 23    | 0      | False      | 52.2         | 3.48          | 2.44          | 87.8                | 553.7               | -20.8            |       |
| MU      | 27     | 27    | 0      | False      | 33.3         | 4.27          | 1.67          | 43.4                | 2090.6              | -70.1            |       |
| NOV.DE  | 29     | 29    | 0      | True       | 51.7         | 4.86          | 2.7           | 184.8               | 773.8               | -25.2            |       |
| NVDA    | 26     | 26    | 0      | True       | 53.8         | 7.25          | 2.95          | 255.9               | 4319.5              | -41.4            |       |
| PLTR    | 12     | 12    | 0      | False      | 58.3         | 20.96         | 7.37          | 441.0               | 1860.9              | -43.2            |       |
| QQQ     | 28     | 28    | 0      | True       | 50.0         | 2.95          | 2.45          | 89.5                | 377.4               | -19.1            |       |
| RDNT    | 19     | 19    | 0      | True       | 47.4         | 9.61          | 2.92          | 283.8               | 642.4               | -36.2            |       |
| RHM.DE  | 23     | 23    | 0      | False      | 30.4         | 14.23         | 4.82          | 552.8               | 1191.4              | -36.6            |       |
| RKLB    | 8      | 8     | 0      | False      | 62.5         | 51.96         | 7.32          | 599.8               | 560.8               | -43.5            |       |
| SMCI    | 20     | 20    | 0      | False      | 65.0         | 14.32         | 3.49          | 411.5               | 1628.7              | -67.9            |       |
| SPY     | 32     | 32    | 0      | True       | 46.9         | 0.52          | 1.25          | 4.1                 | 226.1               | -25.9            |       |
| SZG.DE  | 14     | 14    | 0      | True       | 64.3         | 12.88         | 7.06          | 360.1               | 35.8                | -30.0            |       |
| TSLA    | 21     | 21    | 0      | False      | 33.3         | 17.32         | 3.43          | 473.5               | 1532.1              | -57.2            |       |
| VERX    | 7      | 7     | 0      | False      | 57.1         | 8.02          | 2.3           | 48.9                | -40.6               | -38.6            |       |
| VRSN    | 19     | 19    | 0      | True       | 52.6         | 2.99          | 2.12          | 60.6                | 171.5               | -25.8            |       |

## Aggregate

- Symbols tested: 25
- Median strategy return: 184.8% (median buy & hold: 578.3%)
- Symbols beating buy & hold: 4 / 25
- Closed trades: 489 (489 long / 0 short)
