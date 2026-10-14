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
7. DCF and reverse DCF
8. Sector cheat sheet
9. Known approximations in the script

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

Defaults: discount rate 9%, terminal growth 2.5%, `g` = historical revenue CAGR clamped to 0-15%.

Choosing a discount rate (rough guide): very stable mega-cap 7.5-8.5%; typical large cap 8.5-10%;
cyclical, levered or small cap 10-12%+. Terminal growth should not exceed long-run nominal GDP
(about 2-3%).

Reading the output:
- If terminal value is >75% of the total, the result is dominated by far-future assumptions.
- The sensitivity grid shows how fragile the value is; report the range, not a point.
- Reverse DCF gives the FCF growth the current price requires. Compare it with historical
  revenue/FCF growth and analyst revenue growth: a price that needs far more growth than the
  company has delivered is priced for perfection; one that needs much less may be mispriced
  (or the market expects a decline - find out why).
- DCF is not applicable when FCF is negative, and not meaningful for banks/insurers.

## 8. Sector cheat sheet

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

## 9. Known approximations in the script

- Historical market cap = fiscal-year-end price x that year's weighted diluted shares.
- TTM = sum of the last four quarters (EPS summed); balance sheet = latest quarter.
- Peer table always uses the last fiscal year for every company so the rows are comparable.
- FMP standardizes statements; unusual items (e.g. lease liabilities inside debt, one-off gains)
  can differ from company-reported non-GAAP figures. Verify key numbers against the 10-K when a
  decision depends on them.
