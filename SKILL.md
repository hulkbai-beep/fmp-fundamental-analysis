---
name: fmp-fundamental-analysis
description: Fundamental analysis of US-listed stocks using the Financial Modeling Prep (FMP) API - growth, profitability, ROIC, balance-sheet strength, cash-flow quality, valuation vs history and peers, Piotroski/Altman scores, DCF and reverse DCF. Use this skill whenever the user asks about a company's fundamentals, financial statements, earnings quality, moat, valuation, intrinsic value, whether a stock is cheap/expensive/undervalued, or wants to compare companies - including Chinese requests such as 基本面, 财报, 估值, 护城河, 现金流, 值不值得买, 贵不贵 - even if they do not mention FMP.
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

**This machine:** `54.236.92.205` is a **third-party FMP API proxy, not FMP's official
server** (`FMP_BASE_URL` points to it). Data arriving through it is resold FMP data and must be
labelled as coming from a third-party FMP proxy in every report's Data notes. The user has chosen
to skip certificate verification for this proxy, whose certificate fails verification. Whenever you run a script in this skill
against that proxy, set `FMP_TLS_VERIFY=0` for that process only (PowerShell: `$env:FMP_TLS_VERIFY = '0'`;
bash: `FMP_TLS_VERIFY=0 python ...`). Do not use `setx`. Do not apply this to any other host.

### Local UI (for the user, optional)

`python ui/server.py` serves a browser page at http://127.0.0.1:8765 where the user enters a
ticker and sees the same analysis `analyze.py` produces (standard library only). It reads `setx`
values from the Windows user environment and applies the proxy TLS rule above on its own.
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
   | `--discount 0.10` | Riskier business (high beta, leverage, small cap); 0.08 for very stable ones |
   | `--json out.json` | User wants the raw numbers, or another tool/skill will consume them |
   | `--refresh` | User says data looks stale or a company just reported |
3. **Check the header and "Data notes"** first: which fiscal years, whether TTM was available,
   the sector note, and which endpoints the plan skipped. Mention material gaps in the report.
4. **Sanity-check the DCF inputs.** If the default growth or starting FCF is unreasonable for
   this business, re-run with explicit `--growth` / `--fcf-base` / `--discount` and say which
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
- **Automated flags are prompts, not verdicts.** Explain each relevant one, and drop flags that
  are artifacts (for example, negative equity caused by buybacks at a highly profitable company,
  or a current ratio below 1 at a company with strong cash generation).
- **Special sectors:** the script detects these and prints a sector note.
  - Banks / insurers: ignore EV multiples, FCF, DCF, gross margin and Altman Z. Focus on ROE,
    P/B, P/E, book-value growth and leverage.
  - REITs: use operating cash flow / P/FCF as an FFO proxy; higher leverage is normal.
- **No buy/sell instructions.** Frame the conclusion as quality + valuation (for example,
  "high-quality business priced for roughly its historical growth"), state what would change
  the view, and leave the decision to the user.

## Report template

Use headers and short tables; keep it skimmable. Numbers come from the script output.

1. **Bottom line** - 3 to 5 sentences: business quality, growth, financial strength,
   valuation vs history/peers/DCF, and the one or two things that matter most.
2. **Business snapshot** - what the company does, scale, sector context.
3. **Growth** - revenue/EPS/FCF trajectory and its drivers; acceleration or deceleration.
4. **Profitability & moat signals** - margins, ROIC/ROE and their trend.
5. **Balance sheet & cash flow quality** - leverage, liquidity, FCF conversion, dilution, capital allocation.
6. **Valuation** - multiples vs own history and peers, analyst view if available, DCF range and
   reverse DCF with the assumptions spelled out.
7. **Risks & red flags** - the material ones only, each with why it matters.
8. **What to watch** - the specific metrics or events that would confirm or break the thesis.
9. **Data notes** - source (FMP, and whether it came through a third-party proxy), period basis
   (TTM or fiscal year), any data the plan did not include, and a one-line reminder that this is
   analysis, not investment advice.

For a quick question ("is NVDA expensive?"), answer directly in a few paragraphs drawing on the
relevant sections instead of the full template.

## Comparing several companies

Run `analyze.py` on the main ticker with `--peers` listing the others; the peer table puts them
side by side on the same last-fiscal-year basis. If the user wants full depth on each, run the
script once per ticker (the cache makes repeat runs cheap) and compare in one summary table.

## Combining with technical analysis

Fundamentals answer *what* is worth owning; technical analysis answers *when*. If the user has a
technical-analysis skill available, offer to run it on the same ticker after this report.

## Raw data for anything else

For data the analysis does not cover, call any FMP stable endpoint directly:
```
python scripts/fmp_client.py get key-metrics symbol=AAPL period=annual limit=5
python scripts/fmp_client.py get ratios symbol=AAPL period=annual limit=5
```
Responses are cached under `~/.cache/fmp-fundamentals` (fundamentals 7 days, prices 12 hours);
`python scripts/fmp_client.py clear-cache` empties it.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `API key problem` | `FMP_API_KEY` missing or wrong; see Setup |
| `does not cover TICKER` | Non-US symbol on a US-only plan; use the ADR or another source |
| "Skipped (not in your FMP plan)" | Expected on Starter for peers / estimates / quarterly data; the analysis still works from annual statements |
| Price/market cap looks stale | Re-run with `--refresh` |
| `python` not found on Windows | Use `py scripts/analyze.py ...` |
| `certificate verification failed` (proxy) | Proxy certificate not trusted; the user may set `FMP_TLS_VERIFY=0` |
| `Could not find a working request format` (proxy) | Token or address wrong, or the proxy uses another path/auth scheme: set `FMP_PATH_PREFIX` / `FMP_AUTH_STYLE` from the proxy's docs |
| Proxy worked before, now `key rejected` | Run `fmp_client.py check` to re-detect; the token may have expired |
