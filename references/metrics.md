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
12. Fundamental score (pillars, weights, bands, caps, confidence)

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
  several share classes) or when the price history has a one-day fall of more than 50% or rise of
  more than 100% (possibly an
  unadjusted split).

**Forward EV/EBITDA on next-12-month EBITDA** (not for banks and insurers): the same method with
EV = price x diluted shares + net debt + minority interest of the latest reported fiscal year on
each day, and NTM EBITDA (reported, else FMP `ebitdaAvg`). Price = (multiple x EBITDA used - net
debt - minority interest) / today's shares. It looks through leverage and tax, so it cross-checks
the P/E rows; a large gap between the two usually means changing leverage, tax or
below-EBITDA costs (depreciation, interest, stock comp). The report flags a gap above 10% between
FMP's EBITDA estimate for the last reported year and the reported figure (adjusted EBITDA).

**Volatility range to each fiscal year end:** lognormal around today's price with no drift,
price x e^(+/-z x sigma x sqrt(T)), T = years to that fiscal year end (1 year, "In 12 months", when there are no
estimates); z = 1 gives the 68% range, z = 1.96 the 95% range. sigma = the standard deviation of
the last year's daily log returns x sqrt(252), or the annual implied volatility given with `--iv`
(the "Implied vol %" box in the UI). Options-implied volatility is the market's own forward
estimate and usually beats realized; read it from a broker (at-the-money, expiry near the horizon).
Real returns have fat tails, so moves beyond the 95% range happen more often than 1 in 20. It
describes how much the price moves, not what the company is worth.

**Other rows:**
- DCF (Now): the "reasonable range" from the DCF section (discount +/-1pt, growth +/-2pt), base case as mid.
- Analyst targets (In 12 months): FMP `price-target-consensus` low / consensus / high (12-month targets;
  sell-side targets are mostly forward EPS x a chosen multiple, so they overlap the P/E rows).
- Trading range (Past 52 weeks): lowest and highest daily close over the last 365 days.

**Names:** every row is a method (Forward P/E, Forward EV/EBITDA, DCF, Analyst targets, Trading range,
Volatility) plus a horizon (Past 52 weeks, Now, In 12 months, FY<year> end), in separate columns. Rows
are sorted by the horizon's date, so they come grouped by horizon in time order; the UI chart uses the
same names and groups.

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

## 12. Fundamental score

`scripts/score.py` turns the numbers above into one score from -2 to +2 and a label, on the same
scale and with the same five labels as the technical-analysis scorecard. The rules are fixed and
deterministic: Python computes the score, and the write-up explains it without changing it. Rules
version 1.2 (`RULES_VERSION`). The report's "Fundamental score" section and the UI's score card show
the same numbers with every weight and band.

**Formula:** score = 0.35 x valuation + 0.25 x quality + 0.20 x growth + 0.20 x financial health.
Each pillar is the weighted mean of its indicators, and each indicator maps one number to -2..+2
through fixed cut points (four for most; the current ratio has two and scores -1..+1, and Altman Z
uses its zones). A value exactly on a cut point takes the band of higher values: exactly the
25th percentile scores +1, not +2.

Valuation carries the largest weight because it decides whether the price is a good entry, and the
forward P/E position (where today's multiple sits in its own 3-year range: below the 45th
percentile scores +1, below the 25th +2) is its largest indicator. It is still well under half the total, so cheapness alone
cannot make a weak business score high, and the value-trap cap below stops that case outright.

**Labels:** above +1.2 Bullish, above +0.4 Moderately bullish, -0.4 to +0.4 Neutral, below -0.4
Moderately bearish, below -1.2 Bearish. A score exactly on a bound takes the label nearer Neutral
(+0.40 is Neutral, -1.20 is Moderately bearish). It is a rule-based label, not a recommendation.

**Two views** (shown beside the total; they do not change it, the label or the caps): business
quality = quality, growth and financial health at their total weights (25 : 20 : 20, so 38% / 31% /
31%), and price attractiveness = the valuation pillar, each -2..+2. Their signs place the stock in
one of four quadrants: good business at a good price, good business priced high, cheap but a weak
business, weak business priced high (0 counts as the good side). A total of +0.5 can be a strong
business that is expensive or a weak one that is cheap; the two views tell them apart.

### Indicators and bands

Bands read `<cut: score / from to to: score / ... / >=cut: score`; `pt` is percentage points.

| Pillar | Indicator | Computed as | Bands |
|---|---|---|---|
| Valuation | Forward P/E vs its 3-year range | percentile of today's next-12-month P/E among the last 3 years' daily values (section 8) | <25%: +2 / 25% to 45%: +1 / 45% to 55%: 0 / 55% to 75%: -1 / >=75%: -2 |
| Valuation | Forward EV/EBITDA vs its 3-year range | the same on next-12-month EV/EBITDA | <25%: +2 / 25% to 45%: +1 / 45% to 55%: 0 / 55% to 75%: -1 / >=75%: -2 |
| Valuation | Trailing fallback for both | trailing (TTM) multiple / median of its fiscal-year-end multiples - 1, at least 3 years | <-25%: +2 / -25% to -10%: +1 / -10% to 10%: 0 / 10% to 25%: -1 / >=25%: -2 |
| Valuation | P/B vs its fiscal-year-end median | the same on P/B (banks and insurers) | <-25%: +2 / -25% to -10%: +1 / -10% to 10%: 0 / 10% to 25%: -1 / >=25%: -2 |
| Valuation | Reverse DCF: implied minus expected growth | FCF growth the price implies (section 7) minus the lower of analysts' revenue growth for the two fiscal years ahead and historical revenue CAGR (the CAGR alone without estimates); +2 when the price implies FCF shrinking more than 50% a year, -2 above 100% a year | <-5pt: +2 / -5pt to -2pt: +1 / -2pt to 2pt: 0 / 2pt to 8pt: -1 / >=8pt: -2 |
| Valuation | DCF value vs price | DCF value per share / price - 1 (margin of safety) | <-30%: -2 / -30% to -10%: -1 / -10% to 10%: 0 / 10% to 30%: +1 / >=30%: +2 |
| Valuation | P/E vs industry | company P/E / industry P/E - 1 (sector P/E when there is no industry P/E) | <-30%: +2 / -30% to -10%: +1 / -10% to 25%: 0 / 25% to 60%: -1 / >=60%: -2 |
| Quality | ROIC (median) | median over the fiscal years in the report | <5%: -2 / 5% to 8%: -1 / 8% to 12%: 0 / 12% to 20%: +1 / >=20%: +2 |
| Quality | ROE (median) | the same on ROE (banks, insurers and utilities) | <5%: -2 / 5% to 8%: -1 / 8% to 11%: 0 / 11% to 15%: +1 / >=15%: +2 |
| Quality | ROIC / ROE change over 3 years | latest minus three fiscal years earlier (at least 4 years), each value clipped to +/-50% | <-5pt: -2 / -5pt to -2pt: -1 / -2pt to 2pt: 0 / 2pt to 5pt: +1 / >=5pt: +2 |
| Quality | Operating margin change over 3 years | latest minus three fiscal years earlier (at least 4 years) | <-5pt: -2 / -5pt to -2pt: -1 / -2pt to 2pt: 0 / 2pt to 5pt: +1 / >=5pt: +2 |
| Quality | Gross margin stability | standard deviation of yearly gross margin, at least 3 years | <1.5pt: +2 / 1.5pt to 3pt: +1 / 3pt to 5pt: 0 / 5pt to 8pt: -1 / >=8pt: -2 |
| Quality | FCF / net income | median of the last 3 fiscal years; -2 when the last year's FCF is negative | <0.5x: -2 / 0.5x to 0.8x: -1 / 0.8x to 1x: 0 / 1x to 1.2x: +1 / >=1.2x: +2 |
| Quality | Stock comp % revenue | last fiscal year | <2%: +2 / 2% to 5%: +1 / 5% to 10%: 0 / 10% to 20%: -1 / >=20%: -2 |
| Growth | Revenue CAGR | over the fiscal years in the report | <0%: -2 / 0% to 3%: -1 / 3% to 8%: 0 / 8% to 15%: +1 / >=15%: +2 |
| Growth | Revenue growth, last FY | last fiscal year vs the one before | <0%: -2 / 0% to 3%: -1 / 3% to 8%: 0 / 8% to 15%: +1 / >=15%: +2 |
| Growth | Expected revenue growth | analysts' average for the fiscal year in progress and the next; the first year's growth starts from the analysts' own figure for the last reported year when it is more than 5% off the reported one (another revenue basis, such as net revenue at banks and exchanges) | <0%: -2 / 0% to 3%: -1 / 3% to 8%: 0 / 8% to 15%: +1 / >=15%: +2 |
| Growth | Expected EPS growth next FY | analysts' EPS next year / this year - 1 (same basis on both sides); historical EPS CAGR without usable estimates | <0%: -2 / 0% to 5%: -1 / 5% to 10%: 0 / 10% to 20%: +1 / >=20%: +2 |
| Health | Net debt / EBITDA | last fiscal year; EBITDA not positive scores -2 with net debt, 0 with net cash | <0x: +2 / 0x to 1x: +1 / 1x to 2.5x: 0 / 2.5x to 4x: -1 / >=4x: -2 |
| Health | Net debt / EBITDA, REITs | as above | <0x: +2 / 0x to 4x: +1 / 4x to 6x: 0 / 6x to 8x: -1 / >=8x: -2 |
| Health | Net debt / EBITDA, utilities | as above | <3x: +2 / 3x to 4.5x: +1 / 4.5x to 6.5x: 0 / 6.5x to 8x: -1 / >=8x: -2 |
| Health | Interest coverage | EBIT / interest expense, last fiscal year; no interest expense scores +2 only when debt is zero or there is net cash | <2x: -2 / 2x to 4x: -1 / 4x to 8x: 0 / 8x to 20x: +1 / >=20x: +2 |
| Health | Interest coverage, REITs | EBITDA / interest, since a REIT's EBIT is after heavy property depreciation | <2x: -2 / 2x to 3x: -1 / 3x to 4x: 0 / 4x to 6x: +1 / >=6x: +2 |
| Health | Interest coverage, utilities | EBIT / interest | <1.5x: -2 / 1.5x to 2x: -1 / 2x to 3x: 0 / 3x to 4.5x: +1 / >=4.5x: +2 |
| Health | Altman Z zone | section 6 zones: safe +1, grey 0, distress -1, Z and Z'' both in distress -2 | zones, not cut points |
| Health | Piotroski F-score | section 6, rescaled to 9 when only 7 or 8 tests have data (fewer: missing) | <2: -2 / 2 to 4: -1 / 4 to 7: 0 / 7 to 8: +1 / >=8: +2 |
| Health | Current ratio | last fiscal year; below 1 scores 0 instead of -1 with net cash or an FCF margin of 10% or more | <1x: -1 / 1x to 1.5x: 0 / >=1.5x: +1 |
| Health | Share count change per year | median of the yearly changes in diluted shares, so one year's all-share acquisition does not decide it | <-2%: +2 / -2% to -0.5%: +1 / -0.5% to 1%: 0 / 1% to 3%: -1 / >=3%: -2 |
| Health | Equity / assets | last fiscal year (banks and insurers) | <5%: -2 / 5% to 7%: -1 / 7% to 10%: 0 / 10% to 13%: +1 / >=13%: +2 |

### Weights by company type

The company type is the report's sector classification. Banks and insurers are the Financial
Services sector plus bank, insurance and capital-markets industries, except fee-based ones
(exchanges, financial data providers, insurance brokers), which are scored like other companies
without Altman Z and the current ratio.
Mortgage REITs lend against their balance sheet, so they join banks and insurers. Other REIT
industries are REITs; real-estate developers and services firms are scored like other companies.
Utilities are the Utilities sector except independent power producers. Weights are shares of their
pillar. n/a means a general indicator the type does not use: it is listed as not applicable and
carries no weight. A dash means an indicator of another type's set, which is not listed at all.

| Pillar | Indicator | General | Banks & insurers | REITs | Utilities | Fee-based financials |
|---|---|---|---|---|---|---|
| Valuation | Forward P/E vs its 3-year range | 30% | 40% | 30% | 30% | 30% |
| Valuation | Forward EV/EBITDA vs its 3-year range | 20% | n/a | 20% | 20% | 20% |
| Valuation | Reverse DCF: implied minus expected growth | 20% | n/a | 20% | 20% | 20% |
| Valuation | DCF value vs price | 15% | n/a | 15% | 15% | 15% |
| Valuation | P/E vs industry | 15% | 30% | 15% | 15% | 15% |
| Valuation | P/B vs its fiscal-year-end median | - | 30% | - | - | - |
| Quality | ROIC (median) | 30% | n/a | n/a | n/a | 30% |
| Quality | ROIC change over 3 years | 15% | n/a | 25% | n/a | 15% |
| Quality | Operating margin change over 3 years | 15% | n/a | 30% | 20% | 15% |
| Quality | Gross margin stability (std. dev.) | 10% | n/a | 25% | 10% | 10% |
| Quality | FCF / net income (3-yr median) | 20% | n/a | n/a | n/a | 20% |
| Quality | Stock comp % revenue | 10% | 20% | 20% | 15% | 10% |
| Quality | ROE (median) | - | 50% | - | 35% | - |
| Quality | ROE change over 3 years | - | 30% | - | 20% | - |
| Growth | Revenue CAGR | 35% | 35% | 35% | 35% | 35% |
| Growth | Revenue growth, last FY | 25% | 25% | 25% | 25% | 25% |
| Growth | Expected revenue growth (analysts) | 20% | 20% | 20% | 20% | 20% |
| Growth | Expected EPS growth next FY (analysts) | 20% | 20% | 20% | 20% | 20% |
| Financial health | Net debt / EBITDA | 25% | n/a | 30% | 30% | 30% |
| Financial health | Interest coverage (EBIT / interest) | 20% | n/a | 25% | 25% | 25% |
| Financial health | Altman Z zone | 15% | n/a | n/a | n/a | n/a |
| Financial health | Piotroski F-score (of 9) | 20% | 40% | 25% | 25% | 25% |
| Financial health | Current ratio | 10% | n/a | n/a | n/a | n/a |
| Financial health | Share count change per year (median) | 10% | 25% | 20% | 20% | 20% |
| Financial health | Equity / assets | - | 35% | - | - | - |

Why: EV, FCF, gross margin, DCF, Altman Z and the current ratio mean little for a balance sheet of
loans or policies. For REITs, property depreciation makes ROIC level, FCF / net income and EBIT
misleading. Utilities fund capex with debt and new shares, so FCF is often negative by design and
leverage runs higher; their ROE is what regulators set returns on. Exchanges, data providers and
insurance brokers hold clearing margin or client money on their balance sheet, which swells current
assets and liabilities alike, so Altman Z and the current ratio say nothing about their health.

### Missing data and fallbacks

An indicator that cannot be computed (no data, a loss, a skipped DCF, too short a history) scores
0 and keeps its weight. That pulls its pillar toward 0 and lowers the data coverage, instead of
letting one surviving indicator decide the pillar. Not applicable (above) is different: no weight.

The forward-multiple positions have fallbacks and stops, checked in this order:
- Statements in another currency than the price (many ADRs): the EV/EBITDA position is missing,
  since EV adds a price-currency market cap to statement-currency debt. The forward P/E position is
  kept when its range exists, since a percentile against its own history is not moved by the
  exchange rate's level.
- Forward range available, today's next-12-month figure usable, and analysts' EPS (or EBITDA) for
  the last reported year within 10% of the reported figure: the forward position is used.
- A loss (or negative EBITDA) expected in the fiscal year in progress or the next: missing.
- Share counts not on today's basis or a one-day price fall of more than 50% or rise of more than
  100%, anywhere in the fiscal years the trailing history uses (the forward range checks only its 3
  years): missing, with no fallback, since the trailing history has the same problem. P/B as well.
  The share count is off when it moves outside 0.55x to 1.8x between two fiscal years (an
  unadjusted split) or between the latest fiscal year and today (an ADR ratio, several share
  classes). Steady issuance or buybacks over the years do not count, since each year's multiple
  uses its own share count.
- Otherwise (no forward range, no usable figure for today, or analysts' figures more than 10% from
  reported ones, usually adjusted non-GAAP, so the range's history would mix two bases): the trailing
  multiple vs its fiscal-year-end median, when at least 3 years exist and currencies match.

With statements and price in different currencies, every ratio that mixes the two is left out as
missing: the DCF, the reverse DCF, P/E vs industry, P/B and the trailing fallbacks. Altman uses Z''
only (book equity instead of market cap), and the value range does not use the DCF.

### Caps

Two caps hold the total, not the pillars, so the pillar table still shows what each pillar scored.
When the score is already below the cap, the cap is listed but changes nothing.
- **Value trap:** valuation +1.0 or more while the mean of quality and growth is -0.5 or less. The
  total is held at +0.4 (Neutral) at most: cheap stocks are often cheap for a reason.
- **Red lines** (total at most +0.4): interest covered less than 1.5x (EBIT; EBITDA for REITs) in
  each of the last two fiscal years, with net debt; free cash flow negative two years running with
  net debt (operating cash flow for REITs and utilities, which fund growth capex with debt and
  shares); Altman Z and Z'' both in the distress zone (general companies only, and not when
  currencies differ). For banks and insurers the only red line is equity not positive. The coverage
  and cash-flow red lines need two years so that one year's one-off charge does not trip them; the
  Altman one uses the latest fiscal year.

**Growth slowdown** (an indicator rule, not a cap): the forward P/E and EV/EBITDA positions score at
most +1 (instead of +2) when historical EPS CAGR is above 15% and next year's expected EPS growth is
under half of it. A cheap multiple after fast growth often prices a slowdown that lasts. It is listed
as a conflict and does not by itself change the confidence.

### Confidence

- **Data coverage:** the pillar-weighted share of indicator weight that had data.
- **Pillar agreement:** the weight of pillars beyond +/-0.25 on the same side as the total. When the
  total is Neutral (within +/-0.4), the weight of pillars within +/-0.5 instead.
- **Valuation methods agreeing:** among valuation indicators scoring +/-1 or more (at least two), the
  share on the valuation pillar's side. Measured only when that pillar is beyond +/-0.25.
- **High:** coverage 85% or more, agreement 70% or more, methods agreeing at least 2 of 3 (or not
  measured), and none of the issues below. **Low:** coverage under 60%, agreement under 50%, or fewer
  than 3 fiscal years. Otherwise **medium**.
- **Issues** (each rules out high): fewer than 4 fiscal years; analysts' EPS more than 10% above
  reported (adjusted basis); statements and price in different currencies; operating margin possibly
  at a cyclical peak; data from a third-party proxy; a red-line or value-trap cap triggered.

### Conflicts

Listed with the score and never change it: value trap; quality premium (quality +1 or more with
valuation -1 or less: a good business already priced as one); relative methods (multiples vs own
history and industry) and absolute methods (DCF, reverse DCF) each averaging +/-1 or more on
opposite sides; growth slowdown; cheap against the industry while the industry's own P/E sits in
the top fifth of its history; adjusted EPS; a possible cyclical peak (latest operating margin at
least 5 points above its median and at least 1.5x it, over 4 or more years, while analysts expect
EPS to fall); optimistic estimates (next year's expected EPS growth 10 points or more above the
historical EPS CAGR); a currency mismatch; each red line.

### Value range

Today's next-12-month EPS x the 25th percentile / median / 75th percentile of the 3-year forward
P/E (the "Forward P/E, Now" rows of section 8). The DCF reasonable range replaces it when there is
no forward range or analysts' EPS is more than 10% from reported (adjusted EPS times multiples built
on reported EPS would run high), and nothing is shown when currencies differ as well. It shows where the price would be if the multiple returned to its own
history, not a target.

### Not scored

Analyst price targets (optimistic, and mostly forward EPS x a chosen multiple, so they repeat the
forward P/E), the 52-week and volatility ranges (how the price moves, not what the company is
worth), peers (auto-peers can include foreign listings) and macro releases (context; rates already
enter through the DCF's Treasury-linked discount rate).

### Known limits

- Thresholds are rules of thumb for US companies, set by hand rather than fitted to past returns.
  That keeps them explainable and avoids overfitting, but they are not calibrated.
- Cyclicals at peak earnings: margins, growth and the DCF look best just before the cycle turns.
  The cyclical-peak check flags it and rules out high confidence but does not change the score;
  read energy, materials and semiconductors with section 10.
- A single year's one-off charge still moves the trend and coverage indicators and the Altman
  zone; only the coverage and cash-flow red lines require two years.
- The reverse DCF shares the section 7 model's horizon, terminal growth and discount rate.

### Rule changes

- **1.2:** analysts' estimates count for less. Within growth, expected revenue growth goes from 30%
  to 20% and history gains it (revenue CAGR 35%, last FY 25%). The reverse DCF compares the implied
  growth with the lower of expected and historical revenue growth. Optimistic estimates are listed
  as a conflict. Why: one consensus fed five indicators (both forward positions, the reverse DCF and
  both expected-growth indicators), and on the first real-data run a single jump in the consensus
  (JPMorgan and ICE, +12% to +14% in one fiscal year) moved growth and valuation together.
- **1.1:** fee-based financials as their own type; expected revenue growth from the analysts' own
  basis; share-basis check between consecutive years only; dilution as the median yearly change.
  Each fixed a wrong score on the first real-data run.

To change a rule, edit the weights (`PILLAR_WEIGHTS`, `WEIGHTS`), the cut points (`BANDS`) or the
named thresholds at the top of `score.py`, bump `RULES_VERSION`, and update this section;
`tests/test_score.py` checks that the band and weight tables here match the code. Check the change on
real data with `scripts/score_batch.py --file references/validation-set.txt`, run before and after
(`--compare <earlier output folder>` lists the stocks whose score or label moved).
