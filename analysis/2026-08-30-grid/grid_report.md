# SuperTrend MTF — configuration grid

- Watchlist: `watchlists/fox.txt` — 107 symbols with usable data (10 skipped)
- Window: 2018-01-01 -> today, daily bars, MA200, 0.1% commission per side
- Grid: 5 engines x 5 HTF filters x 2 side modes x 2 strength floors = 100 configurations
- 6,306 symbol/config results that placed at least one trade (8.8 min)

Ranked by the stated goal: the number of symbols left **in profit**.

## Best configurations

| config                                 | symbols | in_profit | in_profit_pct | beat_b&h | median_return_pct | mean_return_pct | median_pf | median_dd_pct | avg_trades |
| -------------------------------------- | ------- | --------- | ------------- | -------- | ----------------- | --------------- | --------- | ------------- | ---------- |
| classic3 / none / long / str>=0        | 107     | 74        | 69.2          | 26       | 24.2              | 70.2            | 1.57      | -42.5         | 18.0       |
| classic4 / none / long / str>=0        | 107     | 69        | 64.5          | 27       | 26.4              | 81.3            | 1.88      | -42.0         | 12.0       |
| classic4 / W-rsi / long / str>=0       | 107     | 66        | 61.7          | 26       | 13.4              | 56.3            | 1.51      | -35.6         | 8.9        |
| classic2 / none / long / str>=0        | 107     | 66        | 61.7          | 25       | 12.7              | 122.6           | 1.36      | -43.2         | 31.6       |
| classic1.5 / W-rsi / long / str>=0     | 107     | 65        | 60.7          | 27       | 6.4               | 103.2           | 1.29      | -37.6         | 35.0       |
| adaptive / W-rsi / long / str>=0       | 107     | 64        | 59.8          | 23       | 17.5              | 57.5            | 1.46      | -39.6         | 20.1       |
| classic1.5 / none / long / str>=0      | 107     | 64        | 59.8          | 27       | 7.0               | 68.2            | 1.29      | -44.9         | 45.4       |
| adaptive / none / long / str>=0        | 107     | 60        | 56.1          | 24       | 10.8              | 78.8            | 1.34      | -43.9         | 27.9       |
| classic3 / M-adx+rsi / long / str>=0   | 99      | 57        | 57.6          | 18       | 10.6              | 41.0            | 1.56      | -33.0         | 10.3       |
| classic2 / W-rsi / long / str>=0       | 107     | 57        | 53.3          | 24       | 4.5               | 199.7           | 1.25      | -39.0         | 23.3       |
| classic1.5 / W-adx / long / str>=0     | 107     | 57        | 53.3          | 28       | 2.2               | 47.9            | 1.26      | -33.4         | 25.4       |
| adaptive / W-adx+rsi / long / str>=0   | 106     | 56        | 52.8          | 23       | 3.0               | 36.5            | 1.3       | -34.7         | 12.4       |
| classic1.5 / W-adx+rsi / long / str>=0 | 107     | 56        | 52.3          | 28       | 0.6               | 80.6            | 1.23      | -33.5         | 23.7       |
| classic2 / W-adx / long / str>=0       | 107     | 55        | 51.4          | 26       | 1.3               | 97.0            | 1.18      | -35.5         | 16.8       |
| classic2 / W-adx+rsi / long / str>=0   | 106     | 55        | 51.9          | 25       | 0.8               | 154.5           | 1.21      | -34.1         | 15.8       |
| adaptive / M-adx+rsi / long / str>=0   | 100     | 54        | 54.0          | 16       | 5.4               | 32.7            | 1.31      | -33.8         | 16.0       |
| classic1.5 / M-adx+rsi / long / str>=0 | 100     | 54        | 54.0          | 19       | 3.6               | 27.9            | 1.23      | -34.0         | 27.3       |
| classic3 / W-rsi / long / str>=0       | 107     | 54        | 50.5          | 23       | 1.0               | 41.1            | 1.28      | -37.4         | 12.9       |
| adaptive / W-adx / long / str>=0       | 107     | 53        | 49.5          | 23       | 0.0               | 39.9            | 1.23      | -36.9         | 13.3       |
| classic4 / W-adx / long / str>=0       | 106     | 53        | 50.0          | 24       | -0.8              | 33.2            | 1.16      | -29.1         | 4.3        |

## Best trending stocks

`robustness_pct` is the share of the 100 configurations in which the symbol ends profitable. High means the symbol trends and the exact settings barely matter; low means any profit came from one lucky combination.

### Trends reliably (profitable in >= 70% of configurations) — 25 symbols

| ticker  | configs | profitable_in | robustness_pct | median_return_pct | best_return_pct | best_config                                  | buy_hold_pct | beat_b&h_in |
| ------- | ------- | ------------- | -------------- | ----------------- | --------------- | -------------------------------------------- | ------------ | ----------- |
| RKLB    | 60      | 60            | 100.0          | 203.9             | 1234.1          | classic3 / W-rsi / long+short / str>=0       | 560.8        | 7           |
| HOOD    | 60      | 59            | 98.3           | 148.5             | 426.1           | classic3 / none / long / str>=0              | 199.4        | 23          |
| GE      | 60      | 58            | 96.7           | 73.2              | 307.8           | classic4 / W-rsi / long+short / str>=0       | 323.2        | 0           |
| MRNA    | 59      | 57            | 96.6           | 180.6             | 2795.2          | classic2 / none / long / str>=0              | 641.9        | 22          |
| HIMS    | 60      | 57            | 95.0           | 73.6              | 462.1           | classic1.5 / W-adx / long+short / str>=0     | 194.3        | 13          |
| AMD     | 60      | 56            | 93.3           | 164.0             | 1185.2          | classic2 / W-rsi / long+short / str>=0       | 4140.3       | 0           |
| TSLA    | 60      | 56            | 93.3           | 161.7             | 624.3           | classic3 / W-rsi / long / str>=0             | 1532.1       | 0           |
| MSFT    | 60      | 56            | 93.3           | 45.5              | 137.8           | classic4 / none / long / str>=0              | 553.7        | 0           |
| DELL    | 60      | 55            | 91.7           | 139.0             | 985.7           | classic4 / none / long / str>=0              | 2071.1       | 0           |
| QQQ     | 60      | 55            | 91.7           | 21.4              | 92.3            | adaptive / none / long+short / str>=0        | 377.4        | 0           |
| PLTR    | 60      | 54            | 90.0           | 148.2             | 547.4           | classic4 / none / long / str>=0              | 1860.9       | 0           |
| MU      | 60      | 51            | 85.0           | 49.4              | 475.0           | adaptive / W-rsi / long / str>=0             | 2090.6       | 0           |
| ASML.AS | 60      | 50            | 83.3           | 42.4              | 217.0           | adaptive / none / long / str>=0              | 1006.8       | 0           |
| MBB.DE  | 60      | 49            | 81.7           | 55.0              | 199.7           | classic1.5 / M-adx+rsi / long+short / str>=0 | 131.0        | 7           |
| SMCI    | 60      | 47            | 78.3           | 157.3             | 827.8           | classic4 / none / long / str>=0              | 1628.7       | 0           |
| NVDA    | 60      | 47            | 78.3           | 84.3              | 350.7           | classic4 / none / long+short / str>=0        | 4319.5       | 0           |
| SPY     | 60      | 47            | 78.3           | 8.2               | 44.0            | adaptive / none / long / str>=0              | 226.1        | 0           |
| VERX    | 60      | 46            | 76.7           | 18.9              | 81.2            | classic2 / none / long+short / str>=0        | -40.6        | 60          |
| RHM.DE  | 60      | 45            | 75.0           | 107.6             | 1093.2          | classic4 / none / long+short / str>=0        | 1191.4       | 0           |
| SZG.DE  | 60      | 45            | 75.0           | 55.8              | 424.8           | classic1.5 / none / long+short / str>=0      | 35.8         | 36          |
| NOV.DE  | 60      | 45            | 75.0           | 31.8              | 221.0           | classic2 / none / long+short / str>=0        | 773.8        | 0           |
| RDNT    | 60      | 44            | 73.3           | 28.4              | 386.5           | classic4 / none / long / str>=0              | 642.4        | 0           |
| IBKR    | 60      | 43            | 71.7           | 18.8              | 250.3           | classic3 / none / long / str>=0              | 578.3        | 0           |
| BWXT    | 60      | 42            | 70.0           | 12.4              | 73.7            | classic1.5 / none / long / str>=0            | 179.9        | 0           |
| VRSN    | 60      | 42            | 70.0           | 5.2               | 64.5            | classic1.5 / none / long / str>=0            | 171.5        | 0           |

### Candidates to drop (profitable in < 30% of configurations) — 40 symbols

| ticker  | configs | profitable_in | robustness_pct | median_return_pct | best_return_pct | buy_hold_pct |
| ------- | ------- | ------------- | -------------- | ----------------- | --------------- | ------------ |
| DLTR    | 57      | 17            | 29.8           | -16.6             | 75.0            | 18.0         |
| LHX     | 60      | 17            | 28.3           | -8.8              | 54.3            | 116.8        |
| APH     | 60      | 17            | 28.3           | -11.6             | 76.2            | 678.1        |
| BC8.DE  | 60      | 17            | 28.3           | -27.3             | 89.3            | 82.6         |
| WH      | 60      | 16            | 26.7           | -10.2             | 24.8            | 42.6         |
| B       | 60      | 16            | 26.7           | -17.1             | 146.0           | 263.7        |
| HPE     | 59      | 15            | 25.4           | -14.7             | 34.7            | 362.9        |
| BIDU    | 60      | 15            | 25.0           | -13.4             | 85.1            | -59.9        |
| CRNC    | 54      | 13            | 24.1           | -35.5             | 83.0            | -66.7        |
| MTX.DE  | 60      | 14            | 23.3           | -18.6             | 29.2            | 162.8        |
| PUM.DE  | 60      | 14            | 23.3           | -20.8             | 79.1            | -19.3        |
| HBH.DE  | 60      | 14            | 23.3           | -23.6             | 38.9            | 40.4         |
| NOC     | 60      | 13            | 21.7           | -23.0             | 33.3            | 105.2        |
| HLT     | 60      | 13            | 21.7           | -28.2             | 43.0            | 316.1        |
| LUV     | 56      | 12            | 21.4           | -14.4             | 14.6            | -33.3        |
| ODD     | 53      | 11            | 20.8           | -32.1             | 62.7            | -69.8        |
| KO      | 60      | 12            | 20.0           | -9.8              | 15.6            | 156.0        |
| CERT    | 50      | 10            | 20.0           | -15.2             | 69.1            | -78.1        |
| ABBV    | 60      | 12            | 20.0           | -24.5             | 95.1            | 274.1        |
| AIR.DE  | 60      | 12            | 20.0           | -24.6             | 23.1            | 175.9        |
| IBM     | 60      | 11            | 18.3           | -21.2             | 39.7            | 131.1        |
| V       | 60      | 10            | 16.7           | -24.3             | 33.8            | 254.4        |
| TIMA.DE | 60      | 10            | 16.7           | -26.6             | 67.8            | 185.9        |
| LYFT    | 53      | 8             | 15.1           | -14.9             | 24.8            | -77.4        |
| LMT     | 60      | 9             | 15.0           | -17.4             | 28.0            | 121.8        |
| RBC     | 60      | 9             | 15.0           | -26.2             | 24.5            | 320.7        |
| DUK     | 60      | 8             | 13.3           | -16.2             | 38.1            | 105.6        |
| TOST    | 60      | 8             | 13.3           | -21.4             | 44.4            | -43.8        |
| GMED    | 60      | 7             | 11.7           | -18.6             | 21.1            | 92.2         |
| DUE.DE  | 60      | 6             | 10.0           | -16.6             | 16.8            | -57.1        |
| ARQT    | 60      | 6             | 10.0           | -34.8             | 157.7           | 9.1          |
| DE      | 60      | 5             | 8.3            | -24.5             | 31.7            | 351.9        |
| PEGA    | 60      | 4             | 6.7            | -40.0             | 33.9            | 53.7         |
| EVTL    | 39      | 2             | 5.1            | -42.6             | 40.5            | -99.3        |
| SIX2.DE | 60      | 3             | 5.0            | -28.0             | 18.0            | 28.5         |
| XPEV    | 60      | 3             | 5.0            | -46.6             | 25.1            | -45.7        |
| DBX     | 53      | 2             | 3.8            | -32.3             | 10.8            | 25.4         |
| ASAN    | 52      | 2             | 3.8            | -41.4             | 10.5            | -64.6        |
| KTN.DE  | 58      | 0             | 0.0            | -32.7             | -6.0            | 39.1         |
| 22UA.DE | 44      | 0             | 0.0            | -36.4             | -19.0           | 26.5         |

## Skipped symbols

- `8XPA.DE` — insufficient data (0 bars)
- `A2JAHJ` — insufficient data (0 bars)
- `BY6.DE` — insufficient data (0 bars)
- `DAU0.DE` — insufficient data (0 bars)
- `DTR0CK` — insufficient data (0 bars)
- `ZEAL24` — insufficient data (0 bars)
- `FIGR` — insufficient data (243 bars)
- `8RMY.DE` — insufficient data (352 bars)
- `A0LC12` — insufficient data (0 bars)
- `CSF.DE` — insufficient data (246 bars)
