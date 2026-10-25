---
name: fmp-fundamental-analysis
description: Fundamental analysis of US-listed stocks using the Financial Modeling Prep (FMP) API - growth, profitability, ROIC, balance-sheet strength, cash-flow quality, valuation vs history, peers and its industry/sector, Piotroski/Altman scores, DCF (discount rate linked to Treasury yields) and reverse DCF - plus a rates & macro dashboard (Treasury curve, Fed funds, CPI/PPI/PCE releases, FOMC dates, sector P/E and returns). Use this skill whenever the user asks about a company's fundamentals, financial statements, earnings quality, moat, valuation, intrinsic value, whether a stock is cheap/expensive/undervalued, how its sector or industry is doing, or about interest rates, Treasury yields, inflation data or the Fed in relation to stocks - including Chinese requests such as 基本面, 财报, 估值, 护城河, 现金流, 值不值得买, 贵不贵, 板块, 行业, 利率, 国债, 收益率, 美联储, 加息, 降息, CPI, PPI, PCE, 宏观 - even if they do not mention FMP.
---

# FMP Fundamental Analysis

The bundled script does every calculation; your job is interpretation. Never compute ratios
in your head and never state a number that is not in the script output (or a figure the user
gave you). If something is missing, say it is missing.

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
ticker and sees the same analysis `analyze.py` produces (standard library only). It reads `setx`
values from the Windows user environment and applies the proxy TLS rule above on its own.
A button in the top-right corner switches the page between Chinese (default) and English; the
translation happens only in the browser, so numbers and `analyze.py` output are unchanged.
This is for the user's own browsing; when you analyse a stock, still run `scripts/analyze.py`.

## Workflow

1. **Identify the ticker(s).** Use US tickers. The FMP Starter plan covers US listings only;
   for Hong Kong / A-share / other foreign names suggest the US ADR if one exists, otherwise
   say the plan does not cover it.
2. **Run the analysis** (paths are relative to this skill's directory):
   ```
   python scripts/analyze.py TICKER
   ```
   Useful options:
   | Option | When to use |
   |---|---|
   | `--peers MSFT,GOOGL` | User names companies to compare, or auto-peers are unavailable/poor |
   | `--peers none` | Skip peers to save time/API calls |
   | `--fcf-base avg3` | Cyclical business or a lumpy latest year |
   | `--growth 0.06` | Historical revenue CAGR is a poor guide (recent acquisition, slowdown, guidance) |
   | `--discount 0.10` | Override the default rate-linked discount rate (see step 4) |
   | `--iv 0.45` | User has the stock's options-implied volatility (annual, 0.45 = 45%); the volatility ranges then use it instead of the past year's realized volatility |
   | `--macro` | User asks how rates, inflation or the Fed affect the stock, or wants the backdrop in the report |
   | `--no-market` | Skip Treasury / sector / industry data (fixed 9% discount, no sector section; cannot be combined with `--macro`); only if those calls fail or the user wants the old behaviour |
   | `--no-insider` | Skip the insider-trades section (the score does not use it); to save API calls or if the endpoint fails |
   | `--json out.json` | User wants the raw numbers |
   | `--contract out.json` | Another tool or skill will consume the result: writes the fa-1.0 contract (see below) |
   | `--refresh` | User says data looks stale or a company just reported |
3. **Check the header and "Data notes"** first: which fiscal years, whether TTM was available,
   the sector note, the Treasury date, and which endpoints the plan skipped. Mention material
   gaps in the report.
4. **Sanity-check the DCF inputs.** The default discount rate is CAPM: the latest 10-year
   Treasury yield + the company's beta x FMP's US equity risk premium, kept within 7-13%
   (the DCF table prints the inputs and the Treasury date; it falls back to a fixed 9% when the
   rates data is unavailable). The report also shows the base case at the old fixed 9%. Override
   with `--discount` when beta misstates the risk (a beta near 0 or above 2, heavy leverage, a
   recent IPO, a business in transition) and say why. If the default growth or starting FCF is
   unreasonable for this business, re-run with explicit `--growth` / `--fcf-base` and say which
   assumptions you changed and why. Two runs with clearly stated assumptions beat one opaque run.
5. **Interpret** using the rules below. For thresholds, formula definitions and sector caveats,
   read `references/metrics.md` (read it at least once per conversation before writing the
   first report).
6. **Write the report** in the user's language using the template below.

## Interpretation rules

- **Context beats thresholds.** Judge every metric against the company's own history, its peers,
  and its industry. A 40% gross margin is excellent for a retailer and weak for software.
- **Trends matter more than levels.** Expanding margins and rising ROIC usually say more than a
  single year's figure.
- **Earnings quality:** FCF persistently below net income, rising receivables/inventory, or
  heavy stock-based comp mean reported profits overstate owner earnings.
- **Valuation is a range, never a point.** Present the DCF sensitivity range and lead with the
  reverse DCF: "the price assumes X% growth; history delivered Y%; analysts expect Z%" is the
  most honest valuation statement you can make.
- **Price range: show it when the user asks where the price could go.** The "Price range"
  section gives forward P/E and EV/EBITDA ranges now, at the end of the current fiscal year and at
  the end of the next one (next-12-month EPS / EBITDA x the 25th / 50th / 75th percentile of the
  company's own 3-year next-12-month multiple), next to the DCF range, analyst targets, the 52-week
  range and volatility ranges (68% and 95%) to the same fiscal year ends. Present them as ranges
  with their basis: the multiple rows are valuations, the volatility rows are how far the price
  typically moves by then. Point out where the methods agree or disagree, and mention the
  adjusted-EPS/EBITDA and wide-history notes when the report prints them. Say where today's forward
  P/E sits in its history: when it is near the bottom because growth is slowing, the Base row
  assumes a re-rating the market may not give ("At today's P/E" shows the no-re-rating case).
  If the user has the options-implied volatility, re-run with `--iv`. None of them is a forecast
  or a target.
- **Automated flags are prompts, not verdicts.** Explain each relevant one, and drop flags that
  are artifacts (for example, negative equity caused by buybacks at a highly profitable company,
  or a current ratio below 1 at a company with strong cash generation).
- **Industry and sector context** (the "Sector & industry context" section): compare the
  company's P/E with its industry and sector *and* with where those groups sit in their own
  history. A stock at a premium to an industry trading in the top decile of its history is a
  different story from a premium to a cheap industry. FMP's industry/sector P/E is an aggregate
  of one exchange's listed companies (the report names the exchange), not a market-cap-weighted
  index, and loss-makers and tiny companies can skew it; use it for direction and relative
  position, not as a precise benchmark. Returns for industry/sector are equal-weighted averages;
  a company beating its industry but lagging SPY (or the reverse) is worth one sentence.
- **Insider trades are an observation, not a signal to act on** (the "Insider trades" section; not
  scored). Mention open-market purchases, above all cluster buying (3+ insiders within 90 days) or a
  large CEO/CFO purchase, as a reason to look closer, with the dates and amounts. Do not read routine
  sales as bearish: most are diversification, taxes or pre-planned 10b5-1 sales, and at mega-caps
  insiders almost only sell. Say nothing about the section when it shows no purchases and ordinary
  sales.
- **Rates and macro are context, not timing.** Use them to explain sensitivity (long-duration
  growth stocks to the 10-year yield, banks to the curve shape, REITs/homebuilders to mortgage
  rates, heavy borrowers to refinancing costs, input-cost-heavy businesses to PPI), always with
  the data date. Never turn a CPI print, a Fed decision or a curve inversion into a call on when
  to buy or sell.
- **Special sectors:** the script detects these and prints a sector note.
  - Banks / insurers: ignore EV multiples, FCF, DCF, gross margin and Altman Z. Focus on ROE,
    P/B, P/E, book-value growth and leverage.
  - REITs: use operating cash flow / P/FCF as an FFO proxy; higher leverage is normal.
  - Utilities (not independent power producers): negative FCF and net debt of 5-6x EBITDA are
    normal; judge earnings growth, interest cover and leverage against other utilities.
  - Exchanges, financial data providers and insurance brokers are fee-based and analysed like
    other companies, not as banks or insurers, except that Altman Z and the current ratio are
    ignored (clearing margin and client money swell the balance sheet); so are real-estate developers and services firms,
    not as REITs. Mortgage REITs lend against their balance sheet and are analysed like banks.
- **Fundamental score: a summary of the numbers, not a verdict.** The report opens with a
  rule-based score (its rules version is printed): valuation 35%, quality 25%, growth 20% and
  financial health 20%, each pillar -2..+2 from fixed indicator bands, with a label on the
  technical scorecard's scale (Bullish / Moderately bullish / Neutral / Moderately bearish /
  Bearish), a confidence level and two views beside it (business quality and price attractiveness,
  with the quadrant they fall in). Quote it as printed and never adjust it or compute another.
  Explain what drives it: the pillars and the two or three indicators with the largest
  contributions, any cap (a value trap or a balance-sheet red line holds it at Neutral, +0.4, at most), the
  conflicts it lists, and what the confidence line flags (missing data counts as 0, so thin data
  pulls the score toward Neutral). When an input is distorted for this company (a one-off charge,
  negative equity from buybacks, a cyclical at peak margins, a recent acquisition), say so and
  which way it biases the score. The bands and rules are in `references/metrics.md` section 12.
- **No buy/sell instructions.** Frame the conclusion as quality + valuation (for example,
  "high-quality business priced for roughly its historical growth"), state what would change
  the view, and leave the decision to the user.

## Report template

Use headers and short tables; keep it skimmable. Numbers come from the script output.

1. **Bottom line** - open with the fundamental score, label and confidence (for example
   "+0.9, Moderately bullish, confidence medium"), then 3 to 5 sentences: business quality,
   growth, financial strength, valuation vs history/peers/DCF, and the one or two things that
   matter most.
2. **Business snapshot** - what the company does, scale, sector context.
3. **Growth** - revenue/EPS/FCF trajectory and its drivers; acceleration or deceleration.
4. **Profitability & moat signals** - margins, ROIC/ROE and their trend.
5. **Balance sheet & cash flow quality** - leverage, liquidity, FCF conversion, dilution, capital allocation.
6. **Valuation** - multiples vs own history, peers and industry/sector, analyst view if
   available, DCF range and reverse DCF with the assumptions spelled out (including the
   discount rate's 10Y yield, beta and risk premium), and the price range table (forward
   multiples now and at the fiscal year ends, the volatility ranges and the other methods) as a short table.
   If `--macro` was used, add a short **Rates & macro backdrop** paragraph after it: the facts
   that matter for this business, with dates.
7. **Risks & red flags** - the material ones only, each with why it matters.
8. **What to watch** - the specific metrics or events that would confirm or break the thesis.
9. **Data notes** - source (FMP, and whether it came through a third-party proxy), period basis
   (TTM or fiscal year), Treasury/macro data dates, any data the plan did not include, and a
   one-line reminder that this is analysis, not investment advice.

For a quick question ("is NVDA expensive?"), answer directly in a few paragraphs drawing on the
relevant sections instead of the full template.

## Comparing several companies

Run `analyze.py` on the main ticker with `--peers` listing the others; the peer table puts them
side by side on the same last-fiscal-year basis. If the user wants full depth on each, run the
script once per ticker (the cache makes repeat runs cheap) and compare in one summary table.

## Rates, macro and sector questions

For questions that are not about one company ("现在利率怎么样", "哪些板块强", "下周有什么数据"):
```
python scripts/macro.py              Treasury curve (now, 1M/3M/1Y ago, 10Y-2Y and 10Y-3M spreads),
                                     Fed funds, unemployment, CPI index, latest key US releases
                                     (CPI, PPI, PCE, payrolls, GDP, Fed decisions: actual vs
                                     consensus vs previous) and the next three weeks' schedule
python scripts/macro.py --sectors    add every sector's P/E vs its history and 1M/3M/YTD/1Y returns vs SPY
python scripts/macro.py --events     add every high/medium-impact US event in the window
```
State the date of each figure. Year-over-year inflation readings come from the economic
calendar's latest release rows (the index levels from economic-indicators give only month on
month). Event times are UTC. Same rule as above: describe the backdrop and what it means for
valuations or specific sectors; do not forecast the Fed or the market.

## S&P 500 earnings context: FactSet Earnings Insight

FactSet publishes a free weekly *Earnings Insight* report (usually on Fridays) with S&P 500
blended earnings and revenue growth, beat rates, guidance, forward P/E vs its 5- and 10-year
averages, sector growth and bottom-up targets. When the user asks about the overall market's
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

Fundamentals answer *what* is worth owning; technical analysis answers *when*. If the user has a
technical-analysis skill available, offer to run it on the same ticker after this report.

## Contract for other tools (fa-1.0)

Tools that build on this skill (a decision engine, a screener) read the **fa-1.0 contract**, not the full
`--json` file, whose layout is internal and may change. `--contract out.json` writes it from a run;
`python scripts/contract.py full.json [-o out.json]` builds it from a saved `--json` file.
`contracts/fa-1.0.schema.json` describes every field: the score, pillars and caps, every indicator, the
valuation bands and ranges, analysts' next two years, insider activity and the data dates (`as_of` is the
price's trading day, `statements_through` the latest statement period). The contract selects facts and
judges nothing. Its fields are only ever added; renaming or removing one means fa-2.0, and
`tests/test_contract.py` checks the output against the schema.

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
| "Skipped (not in your FMP plan)" | Expected on Starter for peers / estimates / quarterly data; the analysis still works from annual statements |
| Price/market cap looks stale | Data notes say "Price from the company profile": the quote was unavailable, re-run with `--refresh` |
| `python` not found on Windows | Use `py scripts/analyze.py ...` |
| `certificate verification failed` (proxy) | Proxy certificate not trusted; the user may set `FMP_TLS_VERIFY=0` |
| `Could not find a working request format` (proxy) | Token or address wrong, or the proxy uses another path/auth scheme: set `FMP_PATH_PREFIX` / `FMP_AUTH_STYLE` from the proxy's docs |
| `cannot reach ... no response within 30s` | Proxy slow or down: retry in a few minutes; if it keeps happening set `FMP_TIMEOUT=60` and/or `FMP_MAX_WORKERS=2` |
| Proxy worked before, now `key rejected` | Run `fmp_client.py check` to re-detect; the token may have expired |
| "Treasury yields unavailable" / "risk premium unavailable" | treasury-rates (no reading in the last 10 days) or market-risk-premium failed; run `fmp_client.py check`. If the DCF table says "fixed default", the DCF used 9% |
| Industry or sector rows show n/a | FMP has no aggregate for that industry name on that exchange; rely on the sector row and peers |
