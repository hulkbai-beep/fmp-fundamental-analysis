# Metrics reference

How `analyze.py` computes each number, rough benchmarks, and when a metric misleads.
Benchmarks are rules of thumb for US companies; always prefer peer and own-history context.

## Contents
1. Growth
2. Profitability & returns
3. Balance sheet & liquidity
4. Cash flow quality & capital allocation
5. Valuation multiples
6. Quality scores (Piotroski, Altman)
7. DCF and reverse DCF (rate-linked discount rate)
8. Price range by method (forward P/E and EV/EBITDA, DCF, analyst targets, volatility)
9. Industry, sector and rates context
10. Sector cheat sheet
11. Known approximations in the script

---

## 1. Growth

| Metric | Formula | Notes |
|---|---|---|
| YoY growth | this year / last year - 1 | Shown as n/a when the prior value is zero or negative |
| CAGR | (last / first)^(1/years) - 1 | n/a if either end is <= 0 |

Rough read on revenue CAGR: >15% fast, 8-15% solid, 3-8% mature, <3% stagnant.
EPS growing faster than revenue = margin expansion and/or buybacks; check which one.
Acquisitions inflate revenue growth; look for jumps in goodwill.

## 2. Profitability & returns

| Metric | Formula |
|---|---|
| Gross / operating / net / EBITDA / FCF margin | item / revenue |
| ROE | net income / average shareholders' equity (n/a if equity <= 0) |
| ROA | net income / average total assets |
| ROIC | operating income x (1 - effective tax rate) / average invested capital |
| Invested capital | total debt + shareholders' equity - cash & short-term investments |

Effective tax rate = tax / pre-tax income when between 0 and 50%, otherwise 21%.

Benchmarks:
- ROIC: >15% strong (often a moat signal), 8-15% adequate, <8% likely below cost of capital.
  A net-cash company can show extreme ROIC because invested capital is tiny; that is real but
  sensitive to small changes.
- ROE is inflated by leverage and by buybacks shrinking equity. Prefer ROIC for comparisons.
- Gross margin typical ranges: software 70-85%, semis 45-65%, consumer brands 40-60%,
  industrials 25-40%, retail 20-40%, grocery/distribution 10-25%.
- Operating margin: >25% exceptional, 15-25% strong, 5-15% average, <5% thin.

## 3. Balance sheet & liquidity

| Metric | Formula | Rough read |
|---|---|---|
| Net debt | total debt - cash & ST investments | negative = net cash |
| Net debt / EBITDA | | <1x low, 1-3x moderate, >3x high (utilities/REITs run higher) |
| Debt / equity | total debt / equity | meaningless when equity <= 0 |
| Current ratio | current assets / current liabilities | <1 can be fine for cash-rich firms with fast inventory turns |
| Quick ratio | (current assets - inventory) / current liabilities | |
| Interest coverage | EBIT / interest expense | >8x comfortable, 3-8x okay, <3x tight |

Negative equity is common at heavy repurchasers (buybacks reduce equity); it is a concern only
when it comes from accumulated losses.

## 4. Cash flow quality & capital allocation

| Metric | Formula | Rough read |
|---|---|---|
| FCF | operating cash flow - capex | |
| FCF / net income | | >=1.0 high quality; persistently <0.8 investigate |
| Capex % revenue | | asset-light <5%; manufacturing/telecom 10%+ |
| Stock comp % revenue | | >10% is a material hidden cost to shareholders |
| Share count YoY | diluted weighted shares | falling = net buybacks; >2%/yr rising = dilution |
| Shareholder yield | (dividends + buybacks - stock issued) / market cap | |

Red flags for earnings quality: FCF well below net income for several years; receivables or
inventory growing much faster than revenue; repeated "one-off" charges.

## 5. Valuation multiples

| Multiple | Formula |
|---|---|
| P/E | market cap / net income (only when NI > 0) |
| P/S | market cap / revenue |
| P/B | market cap / shareholders' equity |
| EV | market cap + total debt - cash & ST investments + minority interest |
| EV/EBITDA, EV/Sales | EV / item |
| P/FCF, FCF yield | market cap / FCF, FCF / market cap |
| PEG | P/E / (EPS CAGR x 100) |

- "Now" uses TTM fundamentals when quarterly data is available, otherwise the last fiscal year.
- "History" values use the closing price on each fiscal-year-end date with that year's numbers;
  with 5 years of data this is a coarse range, not a precise percentile.
- PEG ~1 is the classic "fair" heuristic; it breaks down for cyclical or very slow growers.
- FCF yield vs the 10-year Treasury yield is a useful sanity check for mature companies.
- Multiples above ~60x usually reflect depressed earnings; use P/S or EV/Sales instead.

## 6. Quality scores

**Piotroski F-score** (latest fiscal year vs prior; 1 point each):
1. ROA > 0  2. Operating cash flow > 0  3. ROA improved  4. Cash flow > net income
5. Long-term debt / assets fell  6. Current ratio improved  7. No net share dilution
8. Gross margin improved  9. Asset turnover improved.
Read: 7-9 strong and improving, 4-6 neutral, 0-3 weak. It measures *change*, so a great but
stable company can score only 5-6; do not treat a middling score as a negative by itself.

**Altman Z (original, manufacturers):** 1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 Sales/TA.
Zones: >2.99 safe, 1.81-2.99 grey, <1.81 distress.
**Z'' (non-manufacturers / services):** 6.56 WC/TA + 3.26 RE/TA + 6.72 EBIT/TA + 1.05 BookEquity/TL.
Zones: >2.6 safe, 1.1-2.6 grey, <1.1 distress.
Use Z'' for software/services. Neither applies to banks or insurers. Large buybacks can push
retained earnings negative and depress both scores without real distress.

## 7. DCF and reverse DCF

Model: starting FCF grows at `g` for years 1-5, fades linearly to terminal growth over years
6-10, then a Gordon-growth terminal value. Enterprise value - net debt - minority interest =
equity value, divided by current shares (market cap / price).

Defaults: terminal growth 2.5%, `g` = historical revenue CAGR clamped to 0-15%, and a
rate-linked discount rate (CAPM):

    discount = 10Y Treasury yield + beta x US equity risk premium, kept within 7-13%,
               rounded to 0.1%

- 10Y yield: latest `treasury-rates` row (its date is printed). Beta: the FMP profile (1.0 if
  missing or not positive). Risk premium: FMP `market-risk-premium`, United States
  `totalEquityRiskPremium` (recently around 4-5%).
- Example: 10Y 5.19% + 1.2 x 4.46% = 10.54%, used as 10.5%. When the 10-year moves 1 point, the
  default discount rate moves 1 point too, unless it sits at the 7% floor or the 13% cap (at a 10Y
  of 5.19% and an ERP of 4.46%, roughly beta below 0.4 or above 1.75), where it moves partly or not
  at all; the DCF table says when the rate was capped. Long-duration (high-growth, low current
  FCF) valuations move most.
- If either input is unavailable the script falls back to a fixed 9% and says so; `--no-market`
  also uses 9%. When CAPM is used, the report also shows the base case at 9% for comparison.
- CAPM is a convention, not a fact. Beta is noisy (measured on past prices) and ignores
  leverage changes and business shifts. Override with `--discount` when it misstates risk.
- CAPM gives a cost of equity, while the DCF discounts free cash flow to the whole firm. For
  companies with little debt the two are close; for heavily indebted ones the blended cost of
  capital (WACC) is lower, so consider a lower `--discount` and say so.

Choosing a discount rate by hand (rough guide): very stable mega-cap 7.5-8.5%; typical large cap
8.5-10%; cyclical, levered or small cap 10-12%+; add roughly the change in the 10-year yield
when rates have moved a lot. Terminal growth should not exceed long-run nominal GDP (about 2-3%)
and must stay below the discount rate.

Reading the output:
- If terminal value is >75% of the total, the result is dominated by far-future assumptions.
- The sensitivity grid shows how fragile the value is; report the range, not a point.
- Reverse DCF gives the FCF growth the current price requires. Compare it with historical
  revenue/FCF growth and analyst revenue growth: a price that needs far more growth than the
  company has delivered is priced for perfection; one that needs much less may be mispriced
  (or the market expects a decline - find out why).
- DCF is not applicable when FCF is negative, and not meaningful for banks/insurers.

## 8. Price range by method

The "Price range" section puts several independent ranges side by side (the UI draws them as a
bar chart with the current price as a dashed line). None of them is a forecast. The forward
multiple and volatility ranges are given at three points: **now**, the **end of the current fiscal
year** and the **end of the next fiscal year**.

**Forward P/E on next-12-month EPS** (FMP `analyst-estimates`):
- Forward P/E is computed for every trading day of the last 3 years: close / next-12-month (NTM)
  EPS. NTM EPS = w x EPS of the fiscal year in progress + (1 - w) x EPS of the following year,
  w = days left in the year in progress / 365.25. Years already reported use the reported diluted
  EPS, so the history shows what the market paid for the earnings the company went on to deliver;
  other years use the analysts' average. Days where either year's EPS is <= 0 are left out; at
  least ~6 months of usable days are needed.
- Why NTM and not one fiscal year: with a single year's EPS the multiple jumps down at every fiscal
  year end and drifts up through the year (the price looks a year ahead, the denominator does not).
  For a company growing EPS 70% a year that sawtooth spans ~1.7x, so the percentiles mix early-year
  and late-year multiples, and applying the median to next year's EPS overstates the price by up
  to a third. NTM blending is how published forward P/E histories (FactSet, Bloomberg "BF") are built.
- Rows: Low / Base / High = EPS used x the 25th-percentile / median / 75th-percentile NTM P/E.
  *Now* uses today's NTM EPS (the weights are printed). At a fiscal year end the next 12 months are
  exactly the following fiscal year, so the *FY end* rows use that year's average estimate: the
  current-year-end row uses next year's EPS, the next-year-end row uses the year after (fewer
  analysts; the report says how many). *At today's P/E* = EPS used x today's NTM P/E: where the
  price would be if the multiple stays where it is (earnings growth only, no re-rating). The
  report prints today's NTM P/E and its percentile: Base assumes the multiple returns to its
  median, which is a re-rating call when today sits far from it (a growth slowdown usually
  compresses the multiple; say so rather than treating Base as fair value).
- Why forward and not trailing P/E: for a fast grower the trailing P/E is inflated by earnings
  that lag the price (in 2023 NVDA often traded above 100x trailing earnings but below 45x the
  earnings it delivered that fiscal year), and multiplying that by future EPS counts the growth twice.
- Why 3 years: it reflects the current rate and growth regime and keeps one old earnings trough
  from dominating the percentiles. The report warns when the 75th percentile is more than 1.6x
  the 25th (an earnings trough or a re-rating); then lean on the Base column.
- Caveats: the multiple is the company's own recent history, so a business whose growth or risk
  has changed may not return to it (forward P/E rises with expected growth and falls with risk,
  leverage and rates). Analyst EPS is often on an adjusted (non-GAAP) basis while history uses
  reported EPS; the report flags a gap above 5% between FMP's estimate row for the last reported
  year and the reported figure. Weak guide for REITs (net income understates cash earnings) and for
  cyclicals at peak or trough earnings.
- Safety checks: the range is skipped when a reported year's diluted share count is outside
  0.55-1.8x today's (market cap / price; a split the statements do not reflect, an ADR ratio or
  several share classes) or when the price history has a one-day move above 50% (possibly an
  unadjusted split).

**Forward EV/EBITDA on next-12-month EBITDA** (not for banks and insurers): the same method with
EV = price x diluted shares + net debt + minority interest of the latest reported fiscal year on
each day, and NTM EBITDA (reported, else FMP `ebitdaAvg`). Price = (multiple x EBITDA used - net
debt - minority interest) / today's shares. It looks through leverage and tax, so it cross-checks
the P/E rows; a large gap between the two usually means changing leverage, tax or
below-EBITDA costs (depreciation, interest, stock comp). The report flags a gap above 10% between
FMP's EBITDA estimate for the last reported year and the reported figure (adjusted EBITDA).

**Volatility range to each fiscal year end:** lognormal around today's price with no drift,
price x e^(+/-z x sigma x sqrt(T)), T = years to that fiscal year end (1 year when there are no
estimates); z = 1 gives the 68% range, z = 1.96 the 95% range. sigma = the standard deviation of
the last year's daily log returns x sqrt(252), or the annual implied volatility given with `--iv`
(the "Implied vol %" box in the UI). Options-implied volatility is the market's own forward
estimate and usually beats realized; read it from a broker (at-the-money, expiry near the horizon).
Real returns have fat tails, so moves beyond the 95% range happen more often than 1 in 20. It
describes how much the price moves, not what the company is worth.

**Other rows:**
- DCF: the "reasonable range" from the DCF section (discount +/-1pt, growth +/-2pt), base case as mid.
- Analyst price targets: FMP `price-target-consensus` low / consensus / high (12-month targets;
  sell-side targets are mostly forward EPS x a chosen multiple, so they overlap the P/E rows).
- 52-week closing range: lowest and highest daily close over the last 365 days.

Reading it: the valuation rows (forward P/E, EV/EBITDA, DCF) say where the price "should" be; the
volatility rows say how far it typically moves by then. Where the price sits against the forward
rows says what the market already expects (above the High rows = priced for a higher multiple or
faster earnings growth than usual). Agreement between methods matters more than any single row; a
DCF far below the P/E rows usually means the DCF growth or discount inputs are conservative for
this business (pass analyst revenue growth with `--growth` to test it), or the multiple is rich -
say which you think it is.

## 9. Industry, sector and rates context

**Industry / sector P/E** (FMP `historical-industry-pe`, `historical-sector-pe`):
- An aggregate P/E of the companies in that group listed on one exchange (the company's own
  exchange, e.g. NASDAQ; the report names it), daily. It is not a market-cap-weighted index:
  small or loss-making members can push it around, so it often differs from S&P 500 sector P/Es
  quoted elsewhere (FactSet, for example, uses forward earnings).
- "Percentile in hist." = share of daily readings in the available history (up to 5 years) at or
  below today's. Above ~80% means the group is expensive versus its own recent past.
- "Now" shows "negative" when the group is loss-making in aggregate (its P/E is below zero), and
  "n/a (last DATE)" when FMP has no reading in the last 10 days; history uses positive readings only.
- Company vs industry premium is computed on the company's current P/E (TTM where available).
  Company history in the same table uses fiscal-year-end P/Es, so it has far fewer points.

**Industry / sector returns** (FMP `historical-*-performance`): FMP gives the equal-weighted
average daily % change of the group; the script compounds it into 1M / 3M / YTD / 1Y returns.
Equal weighting means a group can lag SPY simply because its mega-caps outperformed.

**Treasury curve** (`treasury-rates`, yields in % converted to fractions):
- 10Y-2Y and 10Y-3M spreads below zero = an inverted curve. Inversions have preceded most US
  recessions, with long and variable lags; the re-steepening after an inversion has often come
  closer to the downturn. Treat it as background, not a signal.
- Rate sensitivity by business: long-duration growth stocks (high P/E, low FCF yield) to the 10Y;
  banks' net interest margin to the curve's slope; REITs, homebuilders and utilities to long
  yields and mortgage rates; companies with floating-rate or near-term maturing debt to
  short-term rates (check interest coverage and net debt/EBITDA).

**Inflation and Fed data** (economic calendar): actual vs consensus vs previous for CPI, PPI and
PCE (headline and core), payrolls, GDP and Fed rate decisions. PPI running above CPI points to
margin pressure for companies that cannot pass costs on; check the gross-margin trend.
`economic-indicators` CPI is the index level (1982-84 = 100), so it only gives month-on-month.

## 10. Sector cheat sheet

| Sector | Focus on | Discount |
|---|---|---|
| Software / internet | revenue growth, gross margin, FCF margin, SBC, Rule of 40 (growth % + FCF margin %) | EV/EBITDA when margins are depressed |
| Semiconductors | cycle position, gross margin trend, inventory, capex | trailing P/E at cycle peaks/troughs |
| Consumer staples | pricing power (gross margin stability), ROIC, dividend coverage | high growth assumptions |
| Industrials | margins through the cycle, backlog, ROIC, leverage | single-year multiples |
| Energy / materials | through-cycle FCF, balance sheet, capex discipline | peak-cycle P/E (use `--fcf-base avg3`) |
| Banks | ROE vs cost of equity, P/B, book-value growth, credit quality | EV, FCF, gross margin, DCF |
| Insurers | combined ratio, ROE, P/B, reserve quality | EV, FCF, DCF |
| REITs | OCF as FFO proxy, occupancy, leverage, dividend coverage | net-income P/E |
| Utilities | regulated ROE, dividend yield, leverage (net debt/EBITDA 5-6x is normal) | high growth assumptions |

## 11. Known approximations in the script

- Historical market cap = fiscal-year-end price x that year's weighted diluted shares.
- TTM = sum of the last four quarters (EPS summed); balance sheet = latest quarter.
- Forward P/E and EV/EBITDA history for the price range uses reported EPS / EBITDA for years
  already reported (hindsight, not what analysts expected at the time) and today's analyst averages
  for the rest; EV uses each year-end's share count and net debt.
- Peer table always uses the last fiscal year for every company so the rows are comparable.
- Industry/sector returns compound FMP's equal-weighted average daily change; they ignore dividends
  (so does the company and SPY comparison, which uses closing prices).
- FMP standardizes statements; unusual items (e.g. lease liabilities inside debt, one-off gains)
  can differ from company-reported non-GAAP figures. Verify key numbers against the 10-K when a
  decision depends on them.
