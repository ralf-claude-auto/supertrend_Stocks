# SuperTrend MTF — Backtest Report

- Watchlist: `C:\Users\ralf\Stock_Supertrend\watchlists\trending_shortlist.txt` (25 symbols)
- Window: 2018-01-01 -> today (daily bars)
- Engine: classic SuperTrend, ATR 10, factor 4.0
- Sides: LONG (close > SMA200, min strength 0)
- Higher-timeframe filter: off
- Relative strength: off
- Commission: 0.1% per side, 100% of equity per trade

## Per-symbol results

| ticker  | trades | longs | shorts | open_trade | win_rate_pct | avg_trade_pct | profit_factor | strategy_return_pct | buy_hold_return_pct | max_drawdown_pct | error |
| ------- | ------ | ----- | ------ | ---------- | ------------ | ------------- | ------------- | ------------------- | ------------------- | ---------------- | ----- |
| AMD     | 12     | 12    | 0      | True       | 58.3         | 11.99         | 2.9           | 423.8               | 4140.3              | -47.5            |       |
| ASML.AS | 17     | 17    | 0      | False      | 41.2         | 6.32          | 2.73          | 115.7               | 1006.8              | -29.8            |       |
| BWXT    | 16     | 16    | 0      | False      | 43.8         | 1.79          | 1.71          | 16.3                | 179.9               | -29.4            |       |
| DELL    | 12     | 12    | 0      | True       | 58.3         | 14.73         | 4.33          | 985.7               | 2071.1              | -33.7            |       |
| GE      | 9      | 9     | 0      | True       | 55.6         | 19.19         | 6.06          | 269.9               | 323.2               | -21.2            |       |
| HIMS    | 9      | 9     | 0      | False      | 55.6         | 16.78         | 2.75          | 108.3               | 194.3               | -64.1            |       |
| HOOD    | 6      | 6     | 0      | True       | 83.3         | 37.17         | 16.7          | 327.6               | 199.4               | -30.0            |       |
| IBKR    | 13     | 13    | 0      | True       | 46.2         | 7.13          | 3.51          | 154.5               | 578.3               | -29.4            |       |
| MBB.DE  | 14     | 14    | 0      | False      | 42.9         | 2.66          | 1.55          | 20.3                | 131.0               | -32.6            |       |
| MRNA    | 8      | 8     | 0      | True       | 62.5         | 20.6          | 3.29          | 107.2               | 641.9               | -50.1            |       |
| MSFT    | 15     | 15    | 0      | True       | 73.3         | 5.63          | 4.33          | 137.8               | 553.7               | -18.0            |       |
| MU      | 14     | 14    | 0      | False      | 50.0         | 18.22         | 3.94          | 273.0               | 2090.6              | -60.1            |       |
| NOV.DE  | 20     | 20    | 0      | True       | 55.0         | 5.41          | 3.2           | 120.5               | 773.8               | -27.2            |       |
| NVDA    | 18     | 18    | 0      | True       | 50.0         | 13.85         | 3.41          | 337.7               | 4319.5              | -42.0            |       |
| PLTR    | 8      | 8     | 0      | True       | 37.5         | 36.02         | 15.36         | 547.4               | 1860.9              | -41.3            |       |
| QQQ     | 15     | 15    | 0      | True       | 60.0         | 4.73          | 4.04          | 80.0                | 377.4               | -13.8            |       |
| RDNT    | 7      | 7     | 0      | False      | 71.4         | 30.32         | 9.77          | 386.5               | 642.4               | -30.8            |       |
| RHM.DE  | 16     | 16    | 0      | False      | 31.2         | 23.28         | 5.61          | 666.0               | 1191.4              | -38.2            |       |
| RKLB    | 5      | 5     | 0      | False      | 80.0         | 75.83         | 18.04         | 718.7               | 560.8               | -43.1            |       |
| SMCI    | 13     | 13    | 0      | True       | 61.5         | 28.83         | 11.17         | 827.8               | 1628.7              | -51.8            |       |
| SPY     | 21     | 21    | 0      | True       | 52.4         | 1.81          | 1.91          | 32.6                | 226.1               | -20.7            |       |
| SZG.DE  | 11     | 11    | 0      | True       | 45.5         | 7.25          | 2.74          | 84.1                | 35.8                | -47.0            |       |
| TSLA    | 14     | 14    | 0      | False      | 35.7         | 12.38         | 2.57          | 139.3               | 1532.1              | -63.9            |       |
| VERX    | 5      | 5     | 0      | False      | 80.0         | 8.58          | 3.55          | 42.2                | -40.6               | -35.4            |       |
| VRSN    | 18     | 18    | 0      | True       | 44.4         | 0.49          | 1.12          | -4.8                | 171.5               | -43.4            |       |

## Aggregate

- Symbols tested: 25
- Median strategy return: 139.3% (median buy & hold: 578.3%)
- Symbols beating buy & hold: 4 / 25
- Closed trades: 316 (316 long / 0 short)
