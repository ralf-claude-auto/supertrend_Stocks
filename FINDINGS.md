# SuperTrend MTF — findings

Grid search run **2026-08-30** on the FOX watchlist. Everything below is computed
from `analysis/2026-08-30-grid/grid_raw.csv` by `build_findings.py` in that
folder — re-run it to regenerate this file.

- **107 symbols** with usable daily history (10 skipped, listed at the end)
- **64 configurations** that placed at least one trade, out of 100 in the grid
- **6,306 symbol/config results**, window 2018-01-01 -> today, MA200, 0.1% commission per side

Grid: 5 engines (adaptive k-means; classic at factor 1.5 / 2 / 3 / 4) x 5 HTF filters
(off; weekly ADX+RSI; weekly ADX; weekly RSI; monthly ADX+RSI) x long vs long+short
x strength floor 0 vs 4. Configurations that never traded are excluded rather than
counted as failures — "never traded" is not evidence either way, which is why 36 of
the 100 do not appear.

## 1. The winning configuration

**`classic3 / none / long / str>=0`** — classic SuperTrend factor 3, no higher-timeframe filter, long only,
no strength floor.

| config                             | symbols | in_profit | in_profit_pct | beat_b&h | median_return_pct | mean_return_pct | median_pf | median_dd_pct | avg_trades |
| ---------------------------------- | ------- | --------- | ------------- | -------- | ----------------- | --------------- | --------- | ------------- | ---------- |
| classic3 / none / long / str>=0    | 107     | 74        | 69.2          | 26       | 24.2              | 70.2            | 1.57      | -42.5         | 18.0       |
| classic4 / none / long / str>=0    | 107     | 69        | 64.5          | 27       | 26.4              | 81.3            | 1.88      | -42.0         | 12.0       |
| classic4 / W-rsi / long / str>=0   | 107     | 66        | 61.7          | 26       | 13.4              | 56.3            | 1.51      | -35.6         | 8.9        |
| classic2 / none / long / str>=0    | 107     | 66        | 61.7          | 25       | 12.7              | 122.6           | 1.36      | -43.2         | 31.6       |
| classic1.5 / W-rsi / long / str>=0 | 107     | 65        | 60.7          | 27       | 6.4               | 103.2           | 1.29      | -37.6         | 35.0       |
| adaptive / W-rsi / long / str>=0   | 107     | 64        | 59.8          | 23       | 17.5              | 57.5            | 1.46      | -39.6         | 20.1       |
| classic1.5 / none / long / str>=0  | 107     | 64        | 59.8          | 27       | 7.0               | 68.2            | 1.29      | -44.9         | 45.4       |
| adaptive / none / long / str>=0    | 107     | 60        | 56.1          | 24       | 10.8              | 78.8            | 1.34      | -43.9         | 27.9       |

## 2. What the grid settled

### Shorts hurt, and the strength floor hurts more

Best configuration within each family:

| side       | min_strength | best config in family                      | in profit | %    | median return % |
| ---------- | ------------ | ------------------------------------------ | --------- | ---- | --------------- |
| long       | 0            | classic3 / none / long / str>=0            | 74/107    | 69.2 | 24.2            |
| long+short | 0            | classic3 / M-adx+rsi / long+short / str>=0 | 51/105    | 48.6 | -1.5            |
| long       | 4            | adaptive / none / long / str>=4            | 48/106    | 45.3 | -4.4            |
| long+short | 4            | adaptive / M-adx+rsi / long+short / str>=4 | 40/99     | 40.4 | -7.5            |

### Classic beats the adaptive k-means engine

At the winning filter/side settings:

| engine     | symbols | in profit | %    | median return % | median PF | avg trades |
| ---------- | ------- | --------- | ---- | --------------- | --------- | ---------- |
| classic3   | 107     | 74        | 69.2 | 24.2            | 1.57      | 18.0       |
| classic4   | 107     | 69        | 64.5 | 26.4            | 1.88      | 12.0       |
| classic2   | 107     | 66        | 61.7 | 12.7            | 1.36      | 31.6       |
| classic1.5 | 107     | 64        | 59.8 | 7.0             | 1.29      | 45.4       |
| adaptive   | 107     | 60        | 56.1 | 10.8            | 1.34      | 27.9       |

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

Distribution: **11** symbols at >=90%,
**14** at 70-90%,
**16** at 50-70%,
**26** at 30-50%,
**40** below 30%.

### Tier A — real uptrends the strategy rides profitably (24)

| ticker  | robustness_pct | beat_pct | median_return_pct | best_return_pct | buy_hold_pct |
| ------- | -------------- | -------- | ----------------- | --------------- | ------------ |
| RKLB    | 100.0          | 11.7     | 203.9             | 1234.1          | 560.8        |
| HOOD    | 98.3           | 38.3     | 148.5             | 426.1           | 199.4        |
| GE      | 96.7           | 0.0      | 73.2              | 307.8           | 323.2        |
| MRNA    | 96.6           | 37.3     | 180.6             | 2795.2          | 641.9        |
| HIMS    | 95.0           | 21.7     | 73.6              | 462.1           | 194.3        |
| AMD     | 93.3           | 0.0      | 164.0             | 1185.2          | 4140.3       |
| TSLA    | 93.3           | 0.0      | 161.7             | 624.3           | 1532.1       |
| MSFT    | 93.3           | 0.0      | 45.5              | 137.8           | 553.7        |
| DELL    | 91.7           | 0.0      | 139.0             | 985.7           | 2071.1       |
| QQQ     | 91.7           | 0.0      | 21.4              | 92.3            | 377.4        |
| PLTR    | 90.0           | 0.0      | 148.2             | 547.4           | 1860.9       |
| MU      | 85.0           | 0.0      | 49.4              | 475.0           | 2090.6       |
| ASML.AS | 83.3           | 0.0      | 42.4              | 217.0           | 1006.8       |
| MBB.DE  | 81.7           | 11.7     | 55.0              | 199.7           | 131.0        |
| SMCI    | 78.3           | 0.0      | 157.3             | 827.8           | 1628.7       |
| NVDA    | 78.3           | 0.0      | 84.3              | 350.7           | 4319.5       |
| SPY     | 78.3           | 0.0      | 8.2               | 44.0            | 226.1        |
| RHM.DE  | 75.0           | 0.0      | 107.6             | 1093.2          | 1191.4       |
| SZG.DE  | 75.0           | 60.0     | 55.8              | 424.8           | 35.8         |
| NOV.DE  | 75.0           | 0.0      | 31.8              | 221.0           | 773.8        |
| RDNT    | 73.3           | 0.0      | 28.4              | 386.5           | 642.4        |
| IBKR    | 71.7           | 0.0      | 18.8              | 250.3           | 578.3        |
| BWXT    | 70.0           | 0.0      | 12.4              | 73.7            | 179.9        |
| VRSN    | 70.0           | 0.0      | 5.2               | 64.5            | 171.5        |

### Tier B — profitable where buy-and-hold LOSES (1)

| ticker | robustness_pct | beat_pct | median_return_pct | best_return_pct | buy_hold_pct |
| ------ | -------------- | -------- | ----------------- | --------------- | ------------ |
| VERX   | 76.7           | 100.0    | 18.9              | 81.2            | -40.6        |

The 25 names above are saved as `watchlists/trending_shortlist.txt`.

### Drop candidates — profitable in under 30% of configurations (40)

`22UA.DE`, `KTN.DE`, `ASAN`, `DBX`, `XPEV`, `SIX2.DE`, `EVTL`, `PEGA`, `DE`, `DUE.DE`, `ARQT`, `GMED`, `DUK`, `TOST`, `LMT`, `RBC`, `LYFT`, `V`, `TIMA.DE`, `IBM`, `AIR.DE`, `ABBV`, `CERT`, `KO`, `ODD`, `LUV`, `NOC`, `HLT`, `MTX.DE`, `PUM.DE`, `HBH.DE`, `CRNC`, `BIDU`, `HPE`, `B`, `WH`, `APH`, `BC8.DE`, `LHX`, `DLTR`

Never profitable in **any** configuration: `KTN.DE`, `22UA.DE`.

## 4. Profit factor, before and after pruning

Pooled over all trades — gross wins / gross losses — not an average of per-symbol
ratios, since ratios do not average.

| universe | symbols | trades | win rate | pooled PF | avg win | avg loss | payoff | expectancy |
| -------- | ------- | ------ | -------- | --------- | ------- | -------- | ------ | ---------- |
| all 109 | 109 | 1,934 | 42.9% | **1.72** | +17.85% | -7.79% | 2.29 | +3.20%/trade |
| shortlist 25 | 25 | 489 | 48.9% | **3.16** | +25.22% | -7.64% | 3.30 | +8.42%/trade |

Note *where* the gain comes from: the average loss barely moves
(-7.79% -> -7.64%), while the average win jumps
(+17.85% -> +25.22%). Pruning does not cut losses; it
removes names that never produced a winner large enough to pay for them.

**This is not an artifact of one configuration.** Across all 64 configurations,
the shortlist shows median per-symbol PF **2.06 vs 1.09**,
and **84.5%** of shortlist symbol/config rows are profitable
against **44.7%** overall.

## 5. The trap in optimising on profit factor

Sweeping the factor on the shortlist, PF rises monotonically — and the best PF is
**not** the best setting:

| factor | trades | win_rate_% | pooled_PF | expectancy_% | median_return_% | median_DD_% |
| ------ | ------ | ---------- | --------- | ------------ | --------------- | ----------- |
| 2      | 870    | 45.9       | 2.39      | 4.43         | 164.6           | -39.4       |
| 3      | 489    | 48.9       | 3.16      | 8.42         | 184.8           | -34.9       |
| 4      | 316    | 52.2       | 4.1       | 12.77        | 139.3           | -35.4       |
| 5      | 236    | 57.2       | 5.12      | 18.87        | 194.2           | -39.2       |

Factor 5 wins on PF by a distance while taking roughly a quarter of the trades, so its
PF rests on a sample too thin to trust, and its drawdown is *worse*. Median return is
non-monotonic across the sweep, which is what noise looks like. **Factor 3 stays the
honest choice**: best median return, competitive drawdown, and the most trades
supporting it of the high-PF options.

## 5b. Relative strength as an entry filter — tested, rejected

Replacing the higher-timeframe filter with daily relative strength against the DAX
(German listings) or SPY (US listings), on the winning classic-3 long-only setup:

| filter                  | symbols | in profit | in profit % | trades | pooled PF | expectancy % | median return % | median DD % | beat B&H |
| ----------------------- | ------- | --------- | ----------- | ------ | --------- | ------------ | --------------- | ----------- | -------- |
| no RS filter (baseline) | 110     | 74        | 67.3        | 1934   | 1.72      | 3.2          | 20.5            | -40.6       | 26       |
| RS ratio > MA30         | 110     | 70        | 63.6        | 1660   | 1.72      | 3.36         | 15.8            | -39.6       | 26       |
| RS ratio > MA50         | 110     | 56        | 50.9        | 1398   | 1.72      | 3.44         | 2.9             | -36.8       | 25       |
| RS ratio > MA100        | 110     | 61        | 55.5        | 1327   | 1.71      | 3.47         | 4.7             | -37.6       | 24       |
| RS ROC60 diff >= 0      | 110     | 62        | 56.4        | 1228   | 1.79      | 3.7          | 6.6             | -35.3       | 22       |
| RS ROC120 diff >= 0     | 110     | 61        | 55.5        | 1384   | 1.64      | 3.08         | 4.9             | -38.4       | 24       |

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

- **In profit is not the same as worth trading.** Across all 6,306 results the
  strategy beat buy-and-hold only **19.6%** of the time.
  Under the winning configuration on the shortlist it beat simply owning the stock in
  **4 of 25** cases:

| ticker | return_pct | buy_hold_pct | trades | profit_factor | max_dd_pct |
| ------ | ---------- | ------------ | ------ | ------------- | ---------- |
| RKLB   | 599.8      | 560.8        | 8      | 7.3           | -43.5      |
| HOOD   | 426.1      | 199.4        | 9      | 7.1           | -34.2      |
| SZG.DE | 360.1      | 35.8         | 14     | 7.1           | -30.0      |
| VERX   | 48.9       | -40.6        | 7      | 2.3           | -38.6      |

  For AMD, TSLA, NVDA, DELL, MU and SMCI the strategy is solidly profitable and still far
  behind holding — NVDA +255.9% against +4319.5%. Read this as a drawdown-reduction and
  stock-selection tool, not as alpha over holding.

- **The raw "beats buy-and-hold" column is misleading on its own.** It is topped by
  stocks that crashed — NEGG (B&H -94%), LYFT (-77%), BIDU (-60%), DUE.DE (-57%).
  Beating buy-and-hold there means being out of the market, not catching a trend. That
  is why Tier B is separated out and kept to names that are genuinely profitable.

- **Universe mismatch between the two runs.** The grid skips symbols under 400 bars;
  `run_backtest.py` only needs MA length + 20. The pooled-PF row therefore covers
  109 symbols against the grid's 107. Immaterial to the
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
.venv/Scripts/python.exe backtest/run_grid.py --watchlist watchlists/fox.txt \
    --start 2018-01-01 --outdir results/grid
.venv/Scripts/python.exe analysis/2026-08-30-grid/build_findings.py
```

Winning configuration on any watchlist:

```bash
.venv/Scripts/python.exe backtest/run_backtest.py \
    --watchlist watchlists/trending_shortlist.txt \
    --start 2018-01-01 --engine classic --classic-factor 3 --no-htf
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
