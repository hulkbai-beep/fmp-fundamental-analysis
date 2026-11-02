---
name: fmp-fundamental-analysis
description: Fundamental analysis of US-listed stocks using the Financial Modeling Prep (FMP) API - growth, profitability, ROIC, balance-sheet strength, cash-flow quality, valuation vs history, peers and its industry/sector, Piotroski/Altman scores, DCF (discount rate linked to Treasury yields) and reverse DCF - plus a rates & macro dashboard (Treasury curve, Fed funds, CPI/PPI/PCE releases, FOMC dates, sector P/E and returns). Use this skill whenever the user asks about a company's fundamentals, financial statements, earnings quality, moat, valuation, intrinsic value, whether a stock is cheap/expensive/undervalued, how its sector or industry is doing, or about interest rates, Treasury yields, inflation data or the Fed in relation to stocks - including Chinese requests such as 基本面, 财报, 估值, 护城河, 现金流, 值不值得买, 贵不贵, 板块, 行业, 利率, 国债, 收益率, 美联储, 加息, 降息, CPI, PPI, PCE, 宏观 - even if they do not mention FMP.
---

# FMP Fundamental Analysis

The bundled scripts compute every number and present facts and standard models: the statements and standard
ratios, multiples against their own history and the industry / sector, forward multiples and their 3-year
distribution, Piotroski, Altman, DCF and reverse DCF, and the rates & macro backdrop. Your job is to present and
explain those facts. The skill makes no buy / sell / hold decision: that is left to the user, or to the decision
engine (`investment-final-plan`), which computes its own fundamental score from this skill's output. Never compute
ratios in your head and never state a number that is not in the script output (or a figure the user gave you).
If a figure is missing, say it is missing and why.

## What changed in v2.0

v2.0 gives facts and standard models only, as one document (fa-2.0) and the report written from it.

- Removed: the fundamental score (pillars, label, confidence, caps) and the fa-1.1 contract, with
  `scripts/score.py`, `scripts/contract.py`, `contracts/fa-1.1.schema.json`, `scripts/score_batch.py` and
  `references/validation-set.txt`. The score now lives in the decision engine: `investment-final-plan`,
  `ifp/fundamental_view.py`, rules 1.3, documented in
  [docs/fundamental-score-1.3.md](https://github.com/hulkbai-beep/investment-final-plan/blob/main/docs/fundamental-score-1.3.md).
- Removed: price ranges and price levels (forward-multiple ranges in prices, the fiscal-year-end price cards, the
  52-week range), the volatility ranges (`--iv`), analyst price targets and the margin of safety. The forward
  multiples and their 3-year distribution stay as statistics (percentiles and today's percentile); the DCF and
  the reverse DCF stay with every input, never set against the price.
- Removed: insider trades (`scripts/insider.py`, `--no-insider`) and the automated flags; on the local page, the
  K-line (candlestick) chart and the cards of the removed parts.
- Outputs: `--json`, `--facts` and the deprecated `--contract` all write fa-2.0;
  `python scripts/facts.py SAVED.json [-o OUT.json]` converts a result saved by v1.x (it replaces
  `contract.py SAVED.json --facts`).
- Without peers an analysis makes 14 API calls instead of 21, and 25 instead of 27 with `--macro`: insider trades
  and price targets are no longer fetched, and the returns against the industry, sector and S&P 500 and the
  Treasury curve 3M / 1Y ago come only with `--macro`.

If the user asks for the fundamental score, a target price or a price range, say that v2.0 does not produce them
(the score is the decision engine's) and show the facts instead.

## Setup (once per machine)

1. The API key must be in the environment variable `FMP_API_KEY`. Never write the key into
   files in this skill or into chat output.
   - Windows (PowerShell): `setx FMP_API_KEY "your_key"`, then open a new terminal and restart Claude Code.
   - macOS / Linux: add `export FMP_API_KEY="your_key"` to `~/.zshrc` or `~/.bashrc`.
2. Python 3.8+ is the only requirement (standard library only, no pip install).
   On Windows the command is usually `python` (or `py`); elsewhere `python3`.
3. Optional: `python scripts/fmp_client.py check` shows the connection in use and which
   endpoints the plan allows (company data, plus sector/industry and macro data such as
   treasury rates and economic indicators). Run it the first time, or whenever data
   unexpectedly comes back missing.
4. Requests run in parallel (`FMP_MAX_WORKERS`, default 6). If a proxy returns frequent
   HTTP 429 or connection errors, set `FMP_MAX_WORKERS=2` (or `1` for one at a time).

If the script exits with "API key problem", walk the user through step 1.

### Using a third-party FMP proxy

Some services resell FMP access through their own server. Set, in addition to `FMP_API_KEY`
(the token the service issued):

| Variable | Value |
|---|---|
| `FMP_BASE_URL` | the proxy address, e.g. `https://1.2.3.4` |
| `FMP_TLS_VERIFY` | `0` only if the proxy's HTTPS certificate fails verification (typical for a bare IP) |
| `FMP_PATH_PREFIX`, `FMP_AUTH_STYLE` | normally leave unset: the client auto-detects them on first use and saves the result |

The easiest place for these is the `env` block of `~/.claude/settings.json`, never a file inside
this skill. Run `python scripts/fmp_client.py check` once to trigger detection and confirm it works.

When data comes through a proxy, the report's Data notes must say so (the script prints the
route). Treat proxy data as unverified: if a figure looks implausible, say so and suggest checking
the company's filings. With `FMP_TLS_VERIFY=0` the connection can be intercepted; mention that
once if the user asks about the setup, and suggest an official FMP key as the long-term fix.

**This machine:** since 2026-10-18 the user has an **official FMP key** (paid plan) and
`FMP_BASE_URL` is unset, so requests go to `https://financialmodelingprep.com` with certificate
verification on. Do not set `FMP_TLS_VERIFY` or `FMP_BASE_URL`. The old third-party proxy
(`54.236.92.205`) is no longer used; if `check` ever shows that address again, tell the user
`FMP_BASE_URL` is still set instead of turning verification off.

### Local UI (for the user, optional)

`python ui/server.py` serves a browser page at http://127.0.0.1:8765 where the user enters a
ticker and sees the same facts `analyze.py` produces (the same fa-2.0 document and report: a header,
tiles of key figures and the report's sections; standard library only). It reads `setx`
values from the Windows user environment and applies the proxy TLS rule above on its own.
A button in the top-right corner switches the page between Chinese (default) and English; the
translation happens only in the browser, so numbers and `analyze.py` output are unchanged.
This is for the user's own browsing; when you analyse a stock, still run `scripts/analyze.py`.

## Workflow

1. **Identify the ticker(s).** Use US tickers. The FMP Starter plan covers US listings only;
   for Hong Kong / A-share / other foreign names suggest the US ADR if one exists, otherwise
   say the plan does not cover it. Share classes may be typed `BRK.B`, `BRK/B` or `brk b`: the scripts
   turn them into FMP's `BRK-B`. A foreign suffix (`SHOP.TO`, `0700.HK`, `VOD.L`) is refused with a hint.
2. **Run the analysis** (paths are relative to this skill's directory):
   ```
   python scripts/analyze.py TICKER
   ```
   stdout is the report alone; notes go to stderr. Options:
   | Option | When to use |
   |---|---|
   | `--peers MSFT,GOOGL` | User names companies to compare, or auto-peers are unavailable/poor (5 API calls per peer) |
   | `--peers none` | Skip peers to save time/API calls |
   | `--max-peers 5` | Fewer or more automatic peers (default 5) |
   | `--years 5` | Fiscal years of history (default 5, the Starter plan's limit) |
   | `--fcf-base avg3` | Cyclical business or a lumpy latest year |
   | `--growth 0.06` | Historical revenue CAGR is a poor guide (recent acquisition, slowdown, guidance) |
   | `--terminal 0.025` | Another DCF terminal growth (default 2.5%) |
   | `--discount 0.10` | Override the default rate-linked discount rate (see step 4) |
   | `--no-ttm` | Use the last fiscal year instead of the trailing twelve months (3 fewer API calls) |
   | `--macro` | User asks how rates, inflation or the Fed bear on the stock, or wants the backdrop in the report |
   | `--no-market` | Skip Treasury / sector / industry data (fixed 9% discount, no industry & sector P/E; cannot be combined with `--macro`); only if those calls fail or the user wants the fixed rate |
   | `--json out.json` | User wants the numbers, or another tool will read them: writes the fa-2.0 document (see "Output") |
   | `--facts out.json` | The same document (the decision engine passes this name) |
   | `--refresh` | User says data looks stale or a company just reported |

   For one version `--contract out.json` still writes the fa-2.0 document (deprecated: fa-1.1 was removed), and
   `--iv` and `--no-insider` are accepted and ignored (hidden from `--help`); each prints a note to stderr.
3. **Check the header and "Data notes"** first: the Data basis line (fiscal years, statement currency, TTM or not,
   which period the valuation uses, the as-of date), the Company type note if there is one, the price source, the
   Treasury date, a currency mismatch and which endpoints the plan skipped. Mention material gaps in the report.
4. **Sanity-check the DCF inputs.** The default discount rate is CAPM: the latest 10-year
   Treasury yield + the company's beta x FMP's US equity risk premium, kept within 7-13%
   (the DCF table prints the inputs and the Treasury date; it falls back to a fixed 9% when the
   rates data is unavailable). Override with `--discount` when beta misstates the risk (a beta near 0 or above 2, heavy leverage, a
   recent IPO, a business in transition) and say why. If the default growth or starting FCF is
   unreasonable for this business, re-run with explicit `--growth` / `--fcf-base` and say which
   assumptions you changed and why. Two runs with clearly stated assumptions beat one opaque run.
5. **Present the facts** using the rules below. For formulas, how each figure is built and where a measure
   misleads, read `references/metrics.md` (read it at least once per conversation before writing the
   first report).
6. **Write the answer** in the user's language using the template below.

## The report, section by section

The report (`scripts/facts_report.py` renders it from the fa-2.0 document) has these parts, in this order:

- **`# TICKER - Name`**, then one line: sector / industry | exchange | price | market cap | beta, and the
  **Data basis** line: the fiscal years and statement currency, the TTM end date (or "TTM unavailable"), which
  period today's multiples and the DCF use, and the as-of date.
- **Company type** (only for a financial company, a fee-based financial, a REIT or a utility): names the measures
  that are not meaningful for that type; their values are still printed. Say they do not apply rather than
  reading them.
- **1. Growth**: revenue, gross profit, operating income, net income, diluted EPS, free cash flow and diluted shares
  per fiscal year (and TTM), the YoY rows, and the CAGR over the years shown.
- **2. Profitability & returns**: gross, operating, net, EBITDA and FCF margins, R&D % revenue, ROE, ROA, ROIC
  after tax.
- **3. Balance sheet & liquidity**: cash, debt, net debt (negative = net cash), net debt / EBITDA, debt / equity,
  current and quick ratios, interest coverage (EBIT / interest), equity, goodwill & intangibles.
- **4. Cash flow quality & capital allocation**: operating cash flow, capex and capex % revenue, FCF / net income,
  stock comp % revenue, buybacks, dividends, share count change.
- **5. Valuation**: P/E, EV/EBITDA, P/S, P/FCF and P/B now against their values at each fiscal year end (median,
  range, now vs median), then EV, EV / sales and the earnings, FCF, dividend and shareholder yields. A sentence
  says when that history is not comparable (share counts off today's basis, a one-day price jump). "Now vs median"
  is arithmetic, not a prediction that the multiple returns to its median.
- **6. Forward multiples**: forward P/E on each of the next two fiscal years' consensus EPS and on next-12-month EPS
  (the blend weights are printed), forward EV/EBITDA on next-12-month EBITDA (not for financial companies), then
  the 3-year distribution of the daily forward P/E and EV/EBITDA: 10th / 25th / median / 75th / 90th percentile,
  trading days and dates, and today's percentile, or the reason there is none. A note says when the analysts' EPS
  or EBITDA for the last reported year is off the reported figure (an adjusted basis the history does not share).
  These are statistics: never multiply a percentile by EPS or EBITDA to get a price.
- **7. Industry & sector P/E**: the company's P/E (now, its fiscal-year-end median and range) beside FMP's aggregate
  P/E of its industry and sector: now, history median and range, today's percentile in that history, a year ago,
  and the company's premium to each. The aggregates cover one exchange's listed companies (named in the text) and
  are not market-cap weighted, so loss-makers and small companies can move them. With `--no-market` the section
  says the data was skipped.
- **8. Quality scores**: the Piotroski F-score as tests passed out of the tests with data, with each test's pass /
  fail; Altman Z and Z'' with their zones and the published cut-offs, and a note when Altman is not meaningful for
  the company type. The zones (safe / grey / distress) are Altman's published bands: quote them as the model's
  zones. Piotroski counts year-on-year changes, so a company whose levels hold steady fails the "improved" tests.
- **9. DCF**: every input (starting FCF and its basis, growth for years 1-5 and its source, the fade to terminal
  growth, the discount rate and how it was set, net debt, shares), the base-case value per share, the range
  (discount rate +/-1pt, growth +/-2pt), the terminal value's share of the total, the 5x5 sensitivity grid and the
  reverse DCF's implied FCF growth (or why there is none); or the reason there is no DCF (a financial company, FCF
  not positive, invalid inputs). The value is the model's output for those inputs: do not call it a fair value or
  a target, and do not work out its gap to the price.
- **10. Analyst consensus**: per fiscal year the average EPS (low-high), the forward P/E on that year's EPS, revenue
  and its growth, EBITDA and the number of analysts (a year that has ended but is not reported yet is marked);
  then the analysts' figures for the last reported year against the reported ones. As published; v2.0 has no
  price targets.
- **11. Peer comparison** (only with peers): each company's last fiscal year with the same formulas (`*` = this
  company) and the peer median. It can differ from section 5, which uses TTM figures when there are some.
- **Rates & macro backdrop** (only with `--macro`, numbered after the last section: 11, or 12 with peers): the
  Treasury curve now / 1M / 3M / 1Y ago with the 10Y-2Y and 10Y-3M spreads, the US equity risk premium, the Fed
  funds rate, unemployment and the CPI index, the latest key US releases (actual / consensus / previous), the next
  key events, and the 1M / 3M / YTD / 1Y price performance of the company, its industry and sector
  (equal-weighted) and the S&P 500.
- **Data notes**: the data route, the price source and time, the Treasury date and risk premium (or the fixed 9%
  default), a statement / price currency mismatch, endpoints the plan skipped, errors, API calls and the source.

## How to present the facts

- **Facts and models, not decisions.** Say what the figures are and how they changed, with their basis and date.
  Do not give a verdict (buy / sell / hold, cheap / expensive, undervalued / overvalued, attractive), a score, grade
  or label (bullish / bearish), price levels, a price range or a target price, an upside / downside or a margin of
  safety, or readings such as "strong", "weak" or "healthy". The skill has no insider trades, analyst price targets
  or automated flags any more; do not bring them in.
- **Context comes from the data.** Set each figure against the company's own history, its peers and its industry
  / sector, all from the report: "operating margin 33.0% in FY2025, up from 30.0% in FY2021"; "P/E 23.4x against a
  fiscal-year-end median of 27.3x". Describe the direction and size of changes rather than labelling a level.
- **Missing figures.** `n/a` means missing or not applicable, and the report says why in words (no estimates on
  the plan, too little price history, a financial company, FCF not positive, `--no-market`, a skipped endpoint).
  Say the figure is not available and give that reason. Do not estimate, compute or borrow a replacement, and do
  not fill the gap with a figure from memory.
- **Company types.** For a financial company, fee-based financial, REIT or utility, name the measures the Company
  type note marks as not meaningful and leave them out of comparisons. Exchanges, financial data providers and
  insurance brokers are fee-based financials (analysed like other companies except Altman Z and the current
  ratio); mortgage REITs count as financial companies; real-estate developers and services firms are analysed like
  other companies, not as REITs.
- **Earnings and cash.** Show the gap between reported and cash earnings with the figures: FCF / net income by
  year, stock comp % revenue (a cost FCF does not deduct), capex % revenue and the share count change.
- **Valuation facts belong together.** The multiples against their own history and the group; the forward P/E on
  next-12-month EPS and its percentile in the 3-year distribution; the DCF value and range with every input; and
  the reverse DCF beside the record: "the price implies about X% FCF growth a year for 5 years; revenue grew Y% a
  year over FY..-FY..; analysts expect Z% for FY..". Keep each figure with its assumptions.
- **Industry and sector.** Give both the company's premium to its industry and sector and where those groups' P/E
  sits in their own history (the percentile). Say it is FMP's aggregate for one exchange, not an index.
- **Rates and macro are context, not timing.** Use them to explain sensitivity (long-duration
  growth stocks to the 10-year yield, banks to the curve shape, REITs/homebuilders to mortgage
  rates, heavy borrowers to refinancing costs, input-cost-heavy businesses to PPI), always with
  the data date. Never turn a CPI print, a Fed decision or a curve inversion into a call on when
  to buy or sell.
- **"Is it cheap?", "Is it worth buying?", 贵不贵, 值不值得买.** Show the relevant facts: the multiples against
  their history and the group, the forward P/E's percentile in its 3-year distribution, and the DCF and reverse DCF
  with their assumptions. Then say plainly that the skill does not make the decision: buy / sell / hold is the
  user's call, or the decision engine's if they use one. Do not hint at an answer ("looks reasonable", "seems
  stretched").

## Answer template

Use headers and short tables; keep it skimmable. Numbers come from the script output.

1. **Summary of the facts** - 3 to 5 sentences: what the business is, growth, margins and returns, balance sheet
   and cash flow, where the multiples sit against their history and the group, and the DCF and reverse DCF with
   their key inputs. No verdict, score or label.
2. **Business snapshot** - what the company does, scale, sector / industry, the company type if the report notes one.
3. **Growth** - revenue / EPS / FCF over the years and the CAGR; the years that moved most.
4. **Profitability & returns** - margins, ROIC/ROE and their trend.
5. **Balance sheet & cash flow** - leverage, liquidity, coverage; FCF against net income, capex, stock comp,
   buybacks, dividends and dilution.
6. **Valuation facts** - multiples vs own history, peers and industry/sector; the forward multiples and today's
   percentile in their 3-year distribution; the analyst consensus; the DCF value and range with the assumptions
   spelled out (including the discount rate's 10Y yield, beta and risk premium) and the reverse DCF.
   If `--macro` was used, add a short **Rates & macro backdrop** paragraph after it: the facts
   that matter for this business, with dates.
7. **Quality scores** - Piotroski (tests passed, and which failed) and Altman Z / Z'' with their zones and cut-offs.
8. **Limits of the data** - missing figures and why, and the approximations that matter here (estimates on an
   adjusted basis, a currency mismatch, a short history, a DCF dominated by its terminal value).
9. **Data notes** - source (FMP, and whether it came through a third-party proxy), period basis
   (TTM or fiscal year), Treasury/macro data dates, any data the plan did not include, and a
   one-line reminder that these are facts and standard models, not investment advice: the decision is the user's.

For a quick question ("is NVDA expensive?"), answer directly in a few paragraphs with the relevant facts (see the
rule above) instead of the full template.

## Comparing several companies

Run `analyze.py` on the main ticker with `--peers` listing the others; the peer table puts them
side by side on the same last-fiscal-year basis. If the user wants full depth on each, run the
script once per ticker (the cache makes repeat runs cheap) and compare in one summary table.

## Rates, macro and sector questions

For questions that are not about one company ("现在利率怎么样", "哪些板块强", "下周有什么数据"):
```
python scripts/macro.py              Treasury curve (now, 1M/3M/1Y ago, 10Y-2Y and 10Y-3M spreads),
                                     US equity risk premium, Fed funds, unemployment, CPI index,
                                     latest key US releases (CPI, PPI, PCE, payrolls, GDP, Fed
                                     decisions: actual vs consensus vs previous) and the next three
                                     weeks' schedule
python scripts/macro.py --sectors    add every sector's P/E vs its history and 1M/3M/YTD/1Y returns vs SPY
python scripts/macro.py --events     add every high/medium-impact US event in the window
```
State the date of each figure. Year-over-year inflation readings come from the economic
calendar's latest release rows (the index levels from economic-indicators give only month on
month). Event times are UTC. Same rule as above: describe the backdrop, with its dates, and the
standard sensitivities of valuations or specific sectors to it; do not forecast the Fed or the market.

## S&P 500 earnings context: FactSet Earnings Insight

FactSet publishes a free weekly *Earnings Insight* report (usually on Fridays) with S&P 500
blended earnings and revenue growth, beat rates, guidance, forward P/E vs its 5- and 10-year
averages and sector growth. When the user asks about the overall market's
earnings or valuation, or when a sector comparison would benefit from it, read the latest issue:
```
https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_MMDDYY.pdf
```
Try the most recent Friday's date first (for example `EarningsInsight_100926.pdf` for Friday 9 Oct 2026),
then the day before, then the previous week. Quote figures as written and cite the report date
("FactSet Earnings Insight, 9 Oct 2026"). Keep it to the few numbers that matter for the
question; do not reproduce the report. These are market-level figures and a different source
from FMP, so keep them separate from the script's company numbers.

## Combining with technical analysis

This skill describes the business and its valuation in figures; a technical-analysis skill describes the price
action. If the user has one available, offer to run it on the same ticker after this report. Neither makes the
decision: the decision engine (`investment-final-plan`), if the user runs it, reads both.

## Output: one document, fa-2.0

`analyze.py` prints the report and, with `--json PATH` or `--facts PATH` (or the deprecated `--contract PATH`),
writes **fa-2.0**, the one output other tools read; each file written prints `(fa-2.0 written to PATH)` to stderr.
Exit codes: 0 ok; 1 FMP error, a ticker the plan does not cover, or an output file that could not be written; 2 API-key problem or invalid options.

fa-2.0 holds the facts of the analysis with no judgement: the statements and standard ratios per fiscal year (and
TTM), the multiples now, at each fiscal year end and against their own history, the forward multiples and the
3-year distribution of the next-12-month multiples, the industry and sector P/E, the analysts' consensus as
published, the CAPM inputs (10-year Treasury yield, risk premium), the standard models (Piotroski, Altman, a DCF
with every input, the reverse DCF), the peers and the data quality. It has no score, label, flag, price level,
price target or margin of safety. `contracts/fa-2.0.schema.json` describes every field. Per-period data are column
arrays lined up with their `period` array; a value that is missing or does not apply is null, and the block's
`status` code says why. 2.x versions only add fields. The decision engine reads fa-2.0 and computes its own
fundamental score from it.

`python scripts/facts.py SAVED.json [-o OUT.json]` converts a full result saved by `analyze.py --json` of v1.x into
fa-2.0: a file that is already fa-2.x is written back as it is, without `-o` the document goes to stdout, and
anything else (an fa-1.x contract, a file that is not a saved result) is refused with exit 1.
`tests/test_facts.py` checks the schema, that no judgement word appears and that results saved by earlier versions
convert to the same documents as before; `tests/test_cli.py` checks the command line and the converter.

## Raw data for anything else

For data the analysis does not cover, call any FMP stable endpoint directly:
```
python scripts/fmp_client.py get key-metrics symbol=AAPL period=annual limit=5
python scripts/fmp_client.py get ratios symbol=AAPL period=annual limit=5
```
Responses are cached under `~/.cache/fmp-fundamentals` (latest quote 1 minute, fundamentals
7 days, price history and sector data 12 hours, Treasury yields 6 hours, economic calendar 3 hours);
the price comes from the quote, so each run uses the current price;
`python scripts/fmp_client.py clear-cache` empties it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `API key problem` | `FMP_API_KEY` missing or wrong; see Setup |
| `does not cover TICKER` | Non-US symbol on a US-only plan; use the ADR or another source |
| `looks like a non-US listing` | The ticker has a foreign exchange suffix (`SHOP.TO`, `VOD.L`); use the US ticker or ADR |
| "Skipped (not in your FMP plan)" | Expected on Starter for peers / estimates / quarterly data; the analysis still works from annual statements |
| Price/market cap looks stale | Data notes say "Price from the company profile": the quote was unavailable, re-run with `--refresh` |
| `python` not found on Windows | Use `py scripts/analyze.py ...` |
| `certificate verification failed` (proxy) | Proxy certificate not trusted; the user may set `FMP_TLS_VERIFY=0` |
| `Could not find a working request format` (proxy) | Token or address wrong, or the proxy uses another path/auth scheme: set `FMP_PATH_PREFIX` / `FMP_AUTH_STYLE` from the proxy's docs |
| `cannot reach ... no response within 30s` | Proxy slow or down: retry in a few minutes; if it keeps happening set `FMP_TIMEOUT=60` and/or `FMP_MAX_WORKERS=2` |
| Proxy worked before, now `key rejected` | Run `fmp_client.py check` to re-detect; the token may have expired |
| "Treasury yields unavailable" / "risk premium unavailable" | treasury-rates (no reading in the last 10 days) or market-risk-premium failed; run `fmp_client.py check`. If the DCF table says "fixed default", the DCF used 9% |
| Industry or sector rows show n/a | FMP has no aggregate for that industry name on that exchange; the sector row and the peers still give the comparison |
| `(--iv is ignored ...)`, `(--no-insider is ignored ...)`, `(--contract is deprecated ...)` | v2.0 accepts these options for one version and ignores them (`--contract` writes fa-2.0, like `--json`); drop them from scripts |
| `Cannot convert ... to fa-2.0` | `facts.py` takes a full result saved by `analyze.py --json` of v1.x, or an fa-2.x file; an fa-1.x contract is not a saved result and cannot be converted |
