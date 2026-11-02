# Metrics reference

How `analyze.py` computes each figure of the report and of the fa-2.0 document, the conventions behind the
standard models, and when a measure misleads. Since v2.0 the skill gives facts only: no score, no thresholds for
good or bad, no price levels or price ranges (section 12 says where the fundamental score's rules went). Read every
figure against the company's own history, its peers and its industry.

## Contents
1. Growth
2. Profitability & returns
3. Balance sheet & liquidity
4. Cash flow quality & capital allocation
5. Valuation multiples and their history
6. Quality scores (Piotroski, Altman)
7. DCF and reverse DCF (rate-linked discount rate)
8. Forward multiples and their 3-year distribution
9. Industry, sector and rates context
10. Company types (measures that do not apply)
11. Known approximations in the script
12. Fundamental score (moved to the decision engine)

---

## 1. Growth

| Metric | Formula | Notes |
|---|---|---|
| YoY growth | this year / last year - 1 | Shown as n/a when the prior value is zero or negative |
| CAGR | (last / first)^(1/years) - 1 | n/a if either end is <= 0; years = the fiscal years shown - 1 |

EPS growing faster than revenue comes from a wider net margin, a falling share count, or both; the margins and the
share count rows show which. Acquisitions add revenue that is not organic growth; a jump in goodwill & intangibles
marks one.

## 2. Profitability & returns

| Metric | Formula |
|---|---|
| Gross / operating / net / EBITDA / FCF margin | item / revenue |
| R&D % revenue | R&D expense / revenue |
| ROE | net income / average shareholders' equity (n/a if equity <= 0) |
| ROA | net income / average total assets |
| ROIC | operating income x (1 - effective tax rate) / average invested capital |
| Invested capital | total debt + shareholders' equity - cash & short-term investments |

Effective tax rate = tax / pre-tax income when between 0 and 50%, otherwise 21%. The averages use this year's and
last year's balance (the first year shown, and the TTM, use one balance).

- ROE rises with leverage and with buybacks that shrink equity; ROIC counts debt and equity together, so leverage
  moves it less.
- A net-cash company can show an extreme ROIC because its invested capital is tiny; that is real but sensitive to
  small changes in that capital.
- Margins differ widely by industry (software runs far higher gross margins than retail or distribution), so set
  them against the peers and the company's own history.

## 3. Balance sheet & liquidity

| Metric | Formula | Notes |
|---|---|---|
| Net debt | total debt - cash & ST investments | negative = net cash |
| Net debt / EBITDA | | n/a when EBITDA <= 0; utilities and REITs typically carry more |
| Debt / equity | total debt / equity | n/a when equity <= 0 |
| Current ratio | current assets / current liabilities | below 1 is common where customers pay before suppliers are paid (fast inventory turns) |
| Quick ratio | (current assets - inventory) / current liabilities | |
| Interest coverage | EBIT / interest expense | n/a without interest expense |

Negative equity comes either from buybacks (which reduce equity) or from accumulated losses; retained earnings and
the buyback history show which.

## 4. Cash flow quality & capital allocation

| Metric | Formula | Notes |
|---|---|---|
| FCF | operating cash flow - capex | |
| FCF / net income | | above 1: cash earnings exceed reported ones; below 1: part of the profit did not turn into cash |
| Capex % revenue | | low for asset-light businesses, high for manufacturing and telecom |
| Stock comp % revenue | | a non-cash cost that dilutes shareholders; FCF does not deduct it |
| Share count YoY | diluted weighted shares | falling = net buybacks; rising = net issuance |
| Shareholder yield | (dividends + buybacks - stock issued) / market cap | |

Reported and cash earnings drift apart when receivables or inventory grow faster than revenue, when capex runs
above depreciation, or when charges called one-off recur; the FCF / net income row shows the gap year by year.

## 5. Valuation multiples and their history

| Multiple | Formula |
|---|---|
| P/E | market cap / net income (only when NI > 0) |
| P/S | market cap / revenue |
| P/B | market cap / shareholders' equity |
| EV | market cap + total debt - cash & ST investments + minority interest |
| EV/EBITDA, EV/Sales | EV / item |
| P/FCF, FCF yield | market cap / FCF, FCF / market cap |
| Earnings yield, dividend yield | net income / market cap, dividends paid / market cap |

- "Now" uses TTM fundamentals when quarterly data is available, otherwise the last fiscal year (the Data basis line
  says which), with today's price and market cap.
- "History" values use the closing price on each fiscal-year-end date with that year's numbers (market cap = that
  price x that year's diluted shares). Median and range use the positive values; "Now vs median" = now / median - 1.
  With 5 years of data this is a coarse range, not a precise percentile.
- The history is marked not comparable when the share counts do not match today's basis or the price history has a
  one-day jump: the checks of section 8, run over every fiscal year shown.
- Earnings multiples above ~60x often come from depressed earnings; P/S and EV/Sales do not depend on earnings.

## 6. Quality scores

**Piotroski F-score** (latest fiscal year vs prior; 1 point each):
1. ROA > 0  2. Operating cash flow > 0  3. ROA improved  4. Cash flow > net income
5. Long-term debt / assets fell  6. Current ratio improved  7. No net share dilution (diluted shares up 0.5% at most)
8. Gross margin improved  9. Asset turnover improved.
ROA and asset turnover use the total assets at the start of the year. The score counts the tests that pass out of
the tests that have data (the report prints both). It measures *change* on the year before, so a company whose
levels hold steady fails the "improved" tests.

**Altman Z (original, manufacturers):** 1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MVE/TL + 1.0 Sales/TA.
Zones: >2.99 safe, 1.81-2.99 grey, <1.81 distress.
**Z'' (non-manufacturers / services):** 6.56 WC/TA + 3.26 RE/TA + 6.72 EBIT/TA + 1.05 BookEquity/TL.
Zones: >2.6 safe, 1.1-2.6 grey, <1.1 distress.
The zones are Altman's published cut-offs. MVE is today's market cap; the other items are the latest fiscal
year's. Z'' is Altman's version for non-manufacturers and services: it drops sales / assets and uses book equity
instead of market value; the report shows both. Neither was built for banks or insurers, and fa-2.0 marks Altman
not meaningful for every company type except general (section 10). Large buybacks can push retained earnings
negative, which lowers both scores while the cash flows stay the same.

## 7. DCF and reverse DCF

Model: starting FCF grows at `g` for years 1-5, fades linearly to terminal growth over years
6-10, then a Gordon-growth terminal value. Enterprise value - net debt - minority interest =
equity value, divided by current shares (market cap / price). Net debt and minority interest are those of the
valuation basis period (TTM or the latest fiscal year).

Defaults: starting FCF = the valuation basis period's FCF (`--fcf-base avg3`: the average of the last 3 fiscal
years), terminal growth 2.5%, `g` = historical revenue CAGR clamped to 0-15% (5% without a usable revenue history),
and a rate-linked discount rate (CAPM):

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
  also uses 9%.
- CAPM is a convention, not a fact. Beta is noisy (measured on past prices) and ignores
  leverage changes and business shifts. Override with `--discount` when it misstates risk.
- CAPM gives a cost of equity, while the DCF discounts free cash flow to the whole firm. For
  companies with little debt the two are close; for heavily indebted ones the blended cost of
  capital (WACC) is lower, so consider a lower `--discount` and say so.

Choosing a discount rate by hand (rough guide): very stable mega-cap 7.5-8.5%; typical large cap
8.5-10%; cyclical, levered or small cap 10-12%+; add roughly the change in the 10-year yield
when rates have moved a lot. Terminal growth should not exceed long-run nominal GDP (about 2-3%)
and must stay below the discount rate.

The output:
- Value per share for the base case, and the range: the lowest and highest values of the grid cells within 1
  point of the base discount rate and 2 points of the base growth.
- Sensitivity grid: discount rates from 2 points below to 2 points above the base in 1-point steps (leaving out any
  rate not more than 0.5 point above the terminal growth) against growth for years 1-5 from 4 points below to 4
  points above the base in 2-point steps.
- If terminal value is >75% of the total, the result is dominated by far-future assumptions; the grid shows how
  much the value moves with its two main inputs, so report the range with the base case.
- Reverse DCF: the growth `g` for years 1-5 at which the model's value per share equals today's price, with the same
  discount rate, fade and terminal growth. It is searched between -50% and +100% a year; outside that range the
  report says so. It states what the price assumes; set it beside the historical revenue / FCF growth and the
  analysts' revenue growth as facts.
- No DCF when the starting FCF is not positive or for a financial company (section 10); a value per share that is
  not positive means net debt exceeds the discounted cash flows. fa-2.0 status codes: `fcf_not_positive`,
  `skipped_financial`, `invalid_inputs` (the discount rate must exceed the terminal growth), `value_not_positive`;
  for the reverse DCF `below_range`, `above_range`, `not_computable` and `no_dcf`.
- The value is the model's output for these inputs, not a fair value or a target; the report never sets it against
  the price.

## 8. Forward multiples and their 3-year distribution

The report's "Forward multiples" section and fa-2.0's `valuation.forward` and `valuation.forward_band`. They are
statistics of the multiples: the skill never turns them into prices.

**Forward multiples now** (FMP `analyst-estimates`):
- Forward P/E on each of the next two fiscal years' consensus EPS: price / that year's average EPS estimate (years
  that have not ended; a year that has ended but is not reported yet is listed in the consensus, not used here).
- Forward P/E on next-12-month (NTM) EPS: price / NTM EPS. NTM EPS = w x EPS of the fiscal year in progress +
  (1 - w) x EPS of the following year, w = days left in the year in progress / 365.25 (the report prints the
  weights).
- Forward EV/EBITDA on NTM EBITDA, blended the same way from the analysts' `ebitdaAvg` (not for financial
  companies): EV = today's market cap + net debt + minority interest of the valuation basis period.

**The 3-year distribution:**
- Forward P/E is computed for every trading day of the last 3 years: close / NTM EPS of that day. Years
  already reported use the reported diluted EPS, so the history shows what the market paid for the earnings the
  company went on to deliver; other years use the analysts' average. Days where either year's EPS is <= 0 are left
  out; at least 120 usable trading days (about 6 months) are needed.
- Forward EV/EBITDA is computed the same way, with EV = close x diluted shares + net debt + minority interest of the
  latest fiscal year that had ended by that day, and NTM EBITDA (reported, else FMP `ebitdaAvg`).
- Percentiles: the 10th, 25th, 50th (median), 75th and 90th of the daily values, by linear interpolation between
  the sorted values (Python `statistics.quantiles(values, n=20, method="inclusive")`, the same as Excel's
  PERCENTILE.INC). Today's percentile = the share of the days whose value is at or below today's; the report says
  "below every day" at 0 and "above every day" at 1. The trading days counted and the first and last date are
  printed.
- Why NTM and not one fiscal year: with a single year's EPS the multiple jumps down at every fiscal
  year end and drifts up through the year (the price looks a year ahead, the denominator does not).
  For a company growing EPS 70% a year that sawtooth spans ~1.7x, so the percentiles would mix early-year
  and late-year multiples. NTM blending is how published forward P/E histories (FactSet, Bloomberg "BF") are built.
- Why forward and not trailing P/E: for a fast grower the trailing P/E is inflated by earnings
  that lag the price (in 2023 NVDA often traded above 100x trailing earnings but below 45x the
  earnings it delivered that fiscal year).
- Why 3 years: it reflects the current rate and growth regime and keeps one old earnings trough
  from dominating the percentiles.
- Caveats: the distribution is the company's own recent history, not a forecast; a business whose growth or risk
  has changed trades on another multiple (forward P/E rises with expected growth and falls with risk, leverage and
  rates). Analyst EPS is often on an adjusted (non-GAAP) basis while the history uses reported EPS; the report
  notes a gap above 5% between FMP's estimate row for the last reported year and the reported figure (above 10% for
  EBITDA, where adjusted figures often leave out stock-based compensation). For REITs net income is after property
  depreciation (P/E is marked not meaningful, section 10); for cyclicals, earnings at a peak or trough move the
  multiple the opposite way to the price.
- Checks: no distribution when the share counts do not match today's basis, that is when the diluted share count
  moves outside 0.55x-1.8x between two fiscal years in the window (a split the statements do not reflect) or
  between the latest fiscal year and today's market cap / price (an ADR ratio, several share classes), or when the
  price history has a one-day fall of more than 50% or rise of more than 100% (possibly an unadjusted split).
  Steady issuance or buybacks do not count, since each year's multiple uses its own share count. The same checks
  over every fiscal year shown decide whether the fiscal-year-end history of section 5 is comparable.
- fa-2.0 status codes (`forward_band.status`): `ok`, `no_estimates` (it needs the estimates of the current and the
  next fiscal year), `share_basis`, `price_jump`, `short_history`; for each multiple also `now_not_positive` (the
  distribution exists but today's NTM figure is not positive), `not_applicable` (EV multiples for a financial
  company, or no net debt or share count) and `ebitda_not_positive`.

## 9. Industry, sector and rates context

**Industry / sector P/E** (FMP `historical-industry-pe`, `historical-sector-pe`):
- An aggregate P/E of the companies in that group listed on one exchange (the company's own
  exchange, e.g. NASDAQ; the report names it), daily. It is not a market-cap-weighted index:
  small or loss-making members can push it around, so it often differs from S&P 500 sector P/Es
  quoted elsewhere (FactSet, for example, uses forward earnings).
- "Percentile in hist." = share of daily readings in the available history (up to 5 years) at or
  below today's.
- "Now" shows "negative" when the group is loss-making in aggregate (its P/E is below zero), and
  "n/a (last DATE)" when FMP has no reading in the last 10 days; history uses positive readings only. "1y ago" is
  the reading on or just before the same day a year earlier.
- Company vs industry premium = company P/E / group P/E - 1, on the company's current P/E (TTM where available).
  Company history in the same table uses fiscal-year-end P/Es, so it has far fewer points.

**Industry / sector returns** (only with `--macro`, and in `macro.py --sectors`; FMP `historical-*-performance`):
FMP gives the equal-weighted average daily % change of the group; the script compounds it into 1M / 3M / YTD / 1Y
returns (30 and 91 days back, from the last year end, 365 days back). Equal weighting means a group can lag SPY
simply because its mega-caps outperformed.

**Treasury curve** (`treasury-rates`, yields in % converted to fractions):
- 10Y-2Y and 10Y-3M spreads below zero = an inverted curve. Inversions have preceded most US
  recessions, with long and variable lags; the re-steepening after an inversion has often come
  closer to the downturn. Treat it as background, not a signal.
- Rate sensitivity by business: long-duration growth stocks (high P/E, low FCF yield) to the 10Y;
  banks' net interest margin to the curve's slope; REITs, homebuilders and utilities to long
  yields and mortgage rates; companies with floating-rate or near-term maturing debt to
  short-term rates (check interest coverage and net debt/EBITDA).

**Inflation and Fed data** (economic calendar): actual vs consensus vs previous for CPI, PPI and
PCE (headline and core), payrolls, GDP and Fed rate decisions. When PPI runs above CPI, input costs are rising
faster than consumer prices; the gross-margin trend shows whether a company passed them on.
`economic-indicators` CPI is the index level (1982-84 = 100), so it only gives month-on-month.

## 10. Company types (measures that do not apply)

`analyze.py` sorts each company by its FMP sector and industry (`company.kind` in fa-2.0). For a type other than
general, the report's "Company type" note names the measures that are not meaningful for it
(`company.not_meaningful`); their values are still computed and shown.

| Type (`company.kind`) | Which companies | Not meaningful | Why |
|---|---|---|---|
| `financial` | the Financial Services sector (except the fee-based industries below), bank, insurance and capital-markets industries, and mortgage REITs | gross margin, EV/EBITDA, EV / sales, free cash flow, DCF, Altman Z | a balance sheet of loans or policies, where debt and cash are the business itself; no DCF and no forward EV/EBITDA are computed |
| `fee_financial` | exchanges, financial data providers, insurance brokers | Altman Z, current ratio | clearing margin and client money swell current assets and liabilities alike; otherwise analysed like other companies |
| `reit` | REIT industries except mortgage REITs | P/E, Altman Z | net income is after property depreciation, so it understates cash earnings |
| `utility` | the Utilities sector except independent power producers | Altman Z | capex above operating cash flow, funded with debt and new shares, is how the business runs; net debt of 5-6x EBITDA is typical |
| `general` | every other company, including real-estate developers and services firms and independent power producers | - | |

Altman Z is marked not meaningful (`models.altman.status`) for every type except general.

## 11. Known approximations in the script

- Historical market cap = fiscal-year-end price x that year's weighted diluted shares.
- TTM = sum of the last four quarters (EPS summed); balance sheet = latest quarter. It is used only when the latest
  quarter ends after the last fiscal year.
- The forward-multiple distribution uses reported EPS / EBITDA for years already reported (hindsight, not what
  analysts expected at the time) and today's analyst averages for the rest; EV uses each year-end's share count and
  net debt.
- Altman Z uses today's market cap with the latest fiscal year's balance sheet.
- Peer table always uses the last fiscal year for every company, this company's own row included, so the rows are
  comparable; it can differ from the "Now" of the valuation section, which uses TTM figures when there are some.
- Industry/sector returns compound FMP's equal-weighted average daily change; they ignore dividends
  (so does the company and SPY comparison, which uses closing prices).
- FMP standardizes statements; unusual items (e.g. lease liabilities inside debt, one-off gains)
  can differ from company-reported non-GAAP figures. Verify key numbers against the 10-K when a
  decision depends on them.

## 12. Fundamental score (moved to the decision engine)

Before v2.0 this section held the rules of the skill's own fundamental score. v2.0 computes no score: the score and
its rules moved to the decision engine `investment-final-plan`, which computes it from the fa-2.0 document with a
frozen copy of the skill's last scoring code (`ifp/fundamental_view.py`, rules 1.3). The rules are documented in
[docs/fundamental-score-1.3.md](https://github.com/hulkbai-beep/investment-final-plan/blob/main/docs/fundamental-score-1.3.md),
which holds this section as it was at commit `8c5ceed`; the section numbers in it refer to this file at that commit.
