# FMP Fundamental Analysis (fmp-fundamental-analysis)

[中文](README.md) | **English**

Fundamental analysis of US stocks using Financial Modeling Prep (FMP) data: the facts and the standard models. It works as a Claude skill, and it can also be run directly from the command line or as a local web page.

What it covers:
- Growth: yearly revenue, profit, EPS and FCF, with CAGR
- Profitability and returns: gross margin, operating margin, ROE, ROIC
- Balance sheet and liquidity: net debt, leverage, current ratio, interest coverage
- Cash flow quality and capital allocation: FCF / net income, stock-based compensation, buybacks, dividends
- Valuation: current multiples against the company's own fiscal-year-end history (5 years by default) and against peers
- Forward multiples: forward P/E on each of the next two fiscal years' EPS and on next-12-month EPS, forward EV/EBITDA, and the 3-year distribution of the daily forward P/E and EV/EBITDA (10th / 25th / median / 75th / 90th percentile and where today sits in it); statistics only, never turned into prices
- Industry and sector P/E: the company's P/E against its industry's and sector's P/E, and where those sit in their own history
- Quality scores: Piotroski F-score, Altman Z (with the published cut-offs)
- DCF and reverse DCF: the discount rate is tied to the 10-year Treasury yield by default (CAPM), with a discount rate × growth sensitivity table
- Analyst consensus: EPS, revenue and EBITDA estimates as published
- Rates and macro backdrop (optional): Treasury yield curve, Fed funds rate, the latest readings of CPI / PPI / PCE / payrolls / Fed decisions, the next three weeks' schedule, and the 1-month / 3-month / year-to-date / 1-year returns of the company, its industry and sector against the S&P 500
- One output for other tools: the fa-2.0 document (`--json` / `--facts`), every field described in `contracts/fa-2.0.schema.json`

All calculations are done by the scripts; Claude presents the results. The skill does not say whether to buy or sell, and neither the report nor fa-2.0 gives a score, price target or price range: the decision is yours, or the decision engine's ([investment-final-plan](https://github.com/hulkbai-beep/investment-final-plan), which computes its own fundamental score from fa-2.0). The local web page also draws the share price and the price range each method gives, on the page only (see Option 3).

> This is an analysis tool, not investment advice. Data may contain errors; verify important figures against the company's filings.

---

## What changed in v2.0

v2.0 gives facts and standard models only. Removed, and what replaces it where something does:
- The fundamental score (pillars, label, confidence, caps) and the fa-1.1 contract, with `scripts/score.py`, `scripts/contract.py`, `contracts/fa-1.1.schema.json`, `scripts/score_batch.py` and `references/validation-set.txt`. The score now lives in the decision engine: investment-final-plan, `ifp/fundamental_view.py`, rules 1.3, documented in [docs/fundamental-score-1.3.md](https://github.com/hulkbai-beep/investment-final-plan/blob/main/docs/fundamental-score-1.3.md).
- Price ranges and price levels in the report and fa-2.0 (forward-multiple ranges in prices, the fiscal-year-end price cards, the 52-week range), the volatility ranges (`--iv`), analyst price targets and the margin of safety. The forward multiples and their 3-year distribution remain as statistics (percentiles and today's percentile); the DCF and the reverse DCF remain, with every input, never set against the price in the report. The local web page works out its own price range by method with `ui/price_range.py` (without analyst targets or `--iv`), shown on the page only.
- Insider trades (`scripts/insider.py`, `--no-insider`) and the automated flags, and on the web page the cards of the score and the flags. The page shows the same facts as the report, and on the page only the share price (K-line) chart and the price range.
- Outputs: `--json`, `--facts` and the deprecated `--contract` all write fa-2.0. `python scripts/facts.py SAVED.json [-o OUT.json]` converts a result saved by `--json` of v1.x (it replaces `contract.py SAVED.json --facts`).
- Without peers an analysis makes 14 API calls instead of 21, and 25 instead of 27 with `--macro`: insider trades and price targets are no longer fetched, and the returns against the industry, sector and S&P 500 and the Treasury curve 3M / 1Y ago come only with `--macro`.

## Folder layout

```
fmp-fundamental-analysis/
├── SKILL.md            # Skill instructions for Claude (workflow, how to present the facts, answer template)
├── README.md           # Usage guide for people (Chinese)
├── README.en.md        # This file: usage guide for people (English)
├── references/
│   └── metrics.md      # How each figure is computed, the standard models, where a measure misleads
├── scripts/
│   ├── fmp_client.py   # FMP API client: connection, cache, rate limiting, plus the check / get commands
│   ├── analyze.py      # Main analysis script: the report on screen, the fa-2.0 document with --json / --facts
│   ├── facts.py        # The fa-2.0 document: statements, ratios, multiples and standard models; converts results saved by v1.x
│   ├── facts_report.py # The report: one fa-2.0 document as markdown (also used by the web page and the decision engine)
│   ├── symbols.py      # Ticker normalisation: BRK.B -> BRK-B, foreign listings refused
│   └── macro.py        # Rates, macro and sector data: a standalone macro dashboard, also used by analyze.py
├── contracts/
│   └── fa-2.0.schema.json  # Every field of fa-2.0 (JSON Schema)
├── ui/
│   ├── server.py       # Local web server
│   ├── price_range.py  # The page's price range: worked out from fa-2.0 and the past year's daily closes, shown on the page only
│   ├── index.html      # Web page
│   └── i18n.js         # Chinese/English toggle and translation tables for the web page
└── tests/              # Offline tests, no API key needed: python -m unittest discover -s tests
    ├── fake_fmp.py     # Offline fake FMP data (eight made-up companies: QUAL, TRAP, BANK, EXCH, UTIL, QTRS, ADJE, REIT) for tests and trying the page
    ├── test_cli.py     # Tests of the command line, the converter, the API calls and the web page's answer
    ├── test_facts.py   # Tests of fa-2.0: the schema, no judgement words, results saved by earlier versions convert as before
    ├── test_facts_report.py  # Tests of the report: its sections, the tables as before, no judgement words, a Chinese translation for every text
    ├── test_docs.py    # Tests of these docs against the code: options, file paths, report sections, the two READMEs
    ├── test_page.py    # Static tests of the web page: what the decision engine relies on, its labels, no removed parts
    ├── test_price_range.py  # Tests of the page's price range: the ranges v1.x showed, no price that is not positive
    ├── test_symbols.py # Tests of the ticker normalisation
    └── data/           # Results and report tables saved by earlier versions, for the tests
```

## Requirements

- Python 3.8 or later, standard library only: **no pip install needed**.
- On Windows the command is usually `python` (use `py` if it is not found); on macOS / Linux use `python3`.

---

## 1. First-time setup

Steps 1-3 below are mostly about Windows; **on a MacBook, go straight to step 4** and follow it step by step.

### 1. Set the API key

The API key is read only from the environment variable `FMP_API_KEY`. Do not write it into any file in this folder.

Windows (PowerShell or CMD):

```bash
setx FMP_API_KEY "your-key"
```

macOS / Linux: add `export FMP_API_KEY="your-key"` to `~/.zshrc` or `~/.bashrc` (detailed Mac steps in step 4).

> `setx` only applies to terminals opened **afterwards**. After setting it, open a new terminal and restart Claude so they can see the new variable.

The scripts connect only to FMP's official API at `https://financialmodelingprep.com`, always with HTTPS certificate verification on; third-party proxies are not supported. `FMP_BASE_URL`, `FMP_TLS_VERIFY`, `FMP_PATH_PREFIX` and `FMP_AUTH_STYLE`, once set for a proxy, are no longer read, so leftovers do no harm.

### 2. Other optional environment variables

| Environment variable | Default | Notes |
|---|---|---|
| `FMP_MAX_PER_MIN` | `280` | Maximum requests per minute |
| `FMP_MAX_WORKERS` | `6` | How many requests run at once. Lower it when FMP often returns 429 or connections fail; `1` sends them one at a time |
| `FMP_TIMEOUT` | `30` | Seconds to wait for each request. Raise to `60` if the network is slow and requests often time out |
| `FMP_CACHE_DIR` | `~/.cache/fmp-fundamentals` | Cache folder |

### 3. Check the connection

```bash
python scripts/fmp_client.py check
```

It shows the address it connects to (FMP's official API, certificate verified), tests about ten single-stock endpoints with AAPL, then tests the sector/industry and macro endpoints (sector performance and P/E, Treasury yields, economic indicators, the economic calendar and so on). Each endpoint shows OK, EMPTY (no data), RESTRICTED (not in your plan) or ERROR. If all single-stock endpoints are OK, setup is done; the sector and macro results tell you which later features your plan supports. With `--peek` (`python scripts/fmp_client.py check --peek`) it also prints the field names and the first and last rows the sector and macro endpoints return, to help diagnose data-format problems.

### 4. Setting up on a MacBook (macOS)

Steps 1-3 above are mostly about Windows. To set everything up from scratch on a Mac, follow these steps. Run the commands in Terminal: press ⌘ + Space and search for "Terminal". macOS uses zsh by default, and its settings file is `~/.zshrc`.

**① Check Python and git**

```bash
python3 --version
git --version
```

Python 3.8 or later is fine. If a window asks to install the "command line developer tools", click Install: it installs both python3 and git. Homebrew works too: `brew install python git`.

**② Download the code**

```bash
mkdir -p ~/Documents/claude
cd ~/Documents/claude
git clone https://github.com/hulkbai-beep/fmp-fundamental-analysis.git
cd fmp-fundamental-analysis
```

If the repository is private, git will ask you to sign in to GitHub. The easiest way is the GitHub CLI: `brew install gh`, then `gh auth login`, then download with `gh repo clone hulkbai-beep/fmp-fundamental-analysis`.

**③ Set the API key**

Open `~/.zshrc` in the nano editor in Terminal, so the key does not end up in your command history. Avoid TextEdit: it can turn the quotes into curly quotes, which breaks the settings:

```bash
nano ~/.zshrc
```

Move to the end of the file with the arrow keys and paste this line, with your real key. Press Ctrl + O and Enter to save, then Ctrl + X to exit:

```bash
export FMP_API_KEY="your-key"
```

Back in Terminal, run `source ~/.zshrc` (or close Terminal and open a new window). Check that it worked (this prints "set", never the key):

```bash
[ -n "$FMP_API_KEY" ] && echo "set" || echo "not set"
```

**④ Check the connection**

```bash
python3 scripts/fmp_client.py check
```

**⑤ Install it as a Claude skill**

```bash
mkdir -p ~/.claude/skills
rsync -a --exclude .git ~/Documents/claude/fmp-fundamental-analysis/ ~/.claude/skills/fmp-fundamental-analysis/
```

When the code changes, run `git pull` in the code folder, then the same `rsync` again. It is the Mac equivalent of robocopy on Windows.

**⑥ Let Claude see the key**

- **Claude Code in Terminal (you type `claude`):** it reads `~/.zshrc`, so step ③ plus a new Terminal window is enough.
- **The Claude desktop app:** an app opened from the Dock or Launchpad may not read `~/.zshrc`. If Claude says `FMP_API_KEY is not set`, also put the values in `~/.claude/settings.json`, then quit the app completely (⌘ + Q) and reopen it:

```json
{
  "env": {
    "FMP_API_KEY": "your-key"
  }
}
```

Open it with `nano ~/.claude/settings.json` (nano creates the file if it does not exist) and save and exit the same way. If the file already has content, merge in just the `"env"` block rather than replacing what is there.

**Other commands on a Mac:** use `python3` wherever this guide says `python`.

---

## 2. Three ways to use it

### Option 1: just ask Claude (recommended)

Once the skill is installed, ask Claude in Chinese or English; there is no need to mention FMP. For example:
- "Analyze AAPL's fundamentals"
- "Is NVDA expensive right now?"
- "Compare the profitability and valuation of MSFT, GOOGL and AMZN"
- "How strong is COST's moat? Is its cash flow quality good?"
- "What are rates and inflation doing right now, and what does that mean for a growth stock like NVDA?"
- "Which sectors have been strong lately? Is tech expensive right now?"

Claude runs `analyze.py` and presents the facts following SKILL.md: a summary of the facts, the business, growth, profitability, balance sheet and cash flow, the valuation facts (multiples against their history and the group, forward multiples, DCF and reverse DCF), quality scores, limits of the data and data notes. It does not say whether to buy or sell: asked "is it expensive?", it shows these facts and leaves the decision to you.

**Note: Claude reads the copy of the skill in `~/.claude/skills/fmp-fundamental-analysis/`.** After changing this folder, sync the changes there for them to take effect. On Windows:

```powershell
robocopy C:\Users\<you>\Documents\claude\fmp-fundamental-analysis C:\Users\<you>\.claude\skills\fmp-fundamental-analysis /E /XD .git
```

On a Mac:

```bash
rsync -a --exclude .git ~/Documents/claude/fmp-fundamental-analysis/ ~/.claude/skills/fmp-fundamental-analysis/
```

### Option 2: command line

From this folder:

```bash
python scripts/analyze.py AAPL
```

On a Mac, use `python3 scripts/analyze.py AAPL`.

The report goes to the screen (stdout, markdown) and notes go to stderr. Its parts, in order:
- `# TICKER - Name`, a line with sector / industry, exchange, price, market cap and beta, a "Data basis" line (fiscal years, statement currency, TTM or not, the period the valuation uses, the as-of date) and, for a financial company, fee-based financial, REIT or utility, a "Company type" note naming the measures that do not apply to it
- `## 1. Growth`, `## 2. Profitability & returns`, `## 3. Balance sheet & liquidity`, `## 4. Cash flow quality & capital allocation`
- `## 5. Valuation` (multiples now against their fiscal-year-end history, EV and yields), `## 6. Forward multiples` (and their 3-year distribution), `## 7. Industry & sector P/E`, `## 8. Quality scores` (Piotroski, Altman), `## 9. DCF` (with the sensitivity grid and the reverse DCF), `## 10. Analyst consensus`
- `## 11. Peer comparison` (only with peers), `Rates & macro backdrop` (only with `--macro`, numbered after the last section) and `## Data notes`

Common options:

| Option | What it does | When to use it |
|---|---|---|
| `--peers MSFT,GOOGL` | Comparison companies, comma-separated (5 API calls each) | You want specific companies, or the automatic peers are a poor fit |
| `--peers none` | No peer comparison | Saves time and API calls |
| `--max-peers 5` | Maximum number of automatic peers (default 5) | |
| `--years 5` | Years of history to fetch (default 5; the Starter plan's limit is 5) | |
| `--discount 0.10` | DCF discount rate. Default = 10-year Treasury yield + beta × US equity risk premium, kept within 7%-13%, rounded to 0.1%; 9% when rates data is unavailable | Beta clearly misstates the risk (recent IPO, heavy debt, business in transition) |
| `--growth 0.06` | DCF growth for years 1-5 (default: historical revenue CAGR, clamped to 0-15%) | Past growth is a poor guide (acquisitions, slowdown, company guidance) |
| `--terminal 0.025` | DCF terminal growth (default 0.025) | |
| `--fcf-base avg3` | Start the DCF from the 3-year average FCF (default `latest`) | Cyclical businesses, or a volatile latest year |
| `--no-ttm` | Skip trailing-twelve-month (TTM) data; saves 3 API calls | |
| `--macro` | Add a "Rates & macro backdrop" section to the report (11 more API calls) | You want to see the rates, inflation and Fed backdrop and the returns against the industry, sector and S&P 500 |
| `--no-market` | Skip Treasury, sector and industry data (fixed 9% discount rate, no industry & sector P/E); saves 4 API calls; cannot be combined with `--macro` | Those endpoints fail, or you want the fixed discount rate |
| `--json out.json` | Also save the fa-2.0 document to a file (see below) | You need the numbers, or another tool will read them |
| `--facts out.json` | The same as `--json` (kept because the decision engine passes it) | |
| `--contract out.json` | Deprecated, for one version: writes the fa-2.0 document too, with a note (the fa-1.1 contract was removed) | Only old scripts still pass it |
| `--refresh` | Ignore the cache and fetch again | Data looks stale, or the company just reported |

Without peers (`--peers none`) an analysis makes 14 API calls: 11 with `--no-ttm`, 10 with `--no-market`, 25 with `--macro`. Peers add 5 calls each, and finding the automatic peers 1 more. `--iv` and `--no-insider` are still accepted for one version and ignored (v2.0 has no volatility range and fetches no insider trades); they print a note and are hidden from `--help`.

Example:

```bash
python scripts/analyze.py MSFT --peers GOOGL,AMZN,ORCL --discount 0.085 --fcf-base avg3
```

Rates and macro on their own (not tied to a stock):

```bash
python scripts/macro.py              # Treasury curve, Fed funds, unemployment, CPI, plus the latest key releases and the next three weeks' schedule
python scripts/macro.py --sectors    # Adds sector P/E (vs its own history) and returns (vs the S&P 500)
python scripts/macro.py --events     # Lists every medium- and high-impact US economic event in the window
```

All times are UTC. Sector and industry P/E and returns are FMP's aggregates of one exchange's listed companies (NASDAQ by default), and the returns are equal-weighted averages of daily changes: good for direction and relative position, not the same as S&P 500 sector indexes.

The fa-2.0 document for other tools:

```bash
python scripts/analyze.py NVDA --json nvda_facts.json      # write it during the analysis (--facts does the same)
python scripts/facts.py nvda_full.json -o nvda_facts.json  # convert a full result saved by --json of v1.x
```

fa-2.0 holds facts only: the statements and standard ratios per fiscal year (and TTM), the multiples now, at each fiscal year end and against their own history, the forward multiples and the 3-year distribution of the next-twelve-month multiples, the industry and sector P/E, the analysts' consensus as published, and Piotroski, Altman, a DCF (every input is a field) and the reverse DCF. It has no score, label, flag, price level, price target or margin of safety; those belong to the tool that makes the decision. Per-period data are column arrays lined up with their `period` array; a value that is missing or does not apply is null, and the block's `status` code says why. `contracts/fa-2.0.schema.json` describes every field; 2.x versions only add fields. Each file written prints `(fa-2.0 written to PATH)` on stderr. Exit codes: 0 ok; 1 FMP error, a ticker that cannot be analysed (not a US listing, not covered by the plan, or no data), a `--peers` entry that is not a US ticker (a peer with no data only gets a "no data" row), or an output file that could not be written; 2 API-key problem or a usage error (an unknown option or value, `--macro` with `--no-market`). `facts.py` writes a file that is already fa-2.x back as it is, prints the document to the screen without `-o`, and refuses anything else (such as an fa-1.x contract) with exit code 1.

Tickers: share classes may be typed `BRK.B`, `BRK/B` or `brk b`; they become FMP's `BRK-B` (`scripts/symbols.py`). A foreign exchange suffix (such as `SHOP.TO` or `0700.HK`) is refused with a hint to use the US ticker or ADR.

Raw data from any FMP endpoint the analysis does not cover:

```bash
python scripts/fmp_client.py get key-metrics symbol=AAPL period=annual limit=5
```

### Option 3: local web UI

Start it:

```bash
python ui/server.py
```

On a Mac, use `python3 ui/server.py`, started from a Terminal window where `~/.zshrc` is already set up. Then open **http://127.0.0.1:8765** in a browser; press Ctrl+C to stop. If the port is taken, pick another: `python ui/server.py --port 9000`. After the code is updated, stop it with Ctrl+C and start it again so the page uses the new code.

- **Reads the `FMP_*` variables saved with `setx` at start-up:** even if the terminal was opened before `setx`.
- **Settings on the page:** ticker, comparison companies, discount rate % (blank = automatic, tied to Treasuries), growth years 1-5 %, terminal growth %, starting FCF (latest or 3-year average), macro backdrop, ignore cache.
- **What the page shows:** the same facts as the report, from the same fa-2.0 document: a header with the company, its price, the day's change and market cap, tiles of key figures, and the report's sections. Data fetched earlier through a third-party proxy gets a notice at the top naming its source.
- **What only the page shows:** the share price over the past year (daily candles with volume, weekly candles when the chart is too narrow, over 3M, 6M, YTD or 1Y; hovering shows a day's open, high, low and close), and the page's "Price range" tab with the "DCF vs price" and "Forward P/E range" tiles in the header. The page's price range goes by method: forward P/E and forward EV/EBITDA (the 25th percentile, median and 75th percentile of the 3-year distribution times the next-12-month estimates now and at each fiscal year end), the DCF, the lowest and highest close of the past 52 weeks, and the range the past year's volatility gives to each fiscal year end. `ui/price_range.py` works them out from fa-2.0 and the daily closes; none is a forecast, and none is written to fa-2.0 or the report. A measure that is not meaningful for the type of company, or a price that is not positive, is left out.
- **Chinese / English toggle:** the "EN / 中文" button at the top right switches the page between Chinese and English; Chinese by default, and the browser remembers your last choice. Translation happens only in the web page, so the numbers do not change; industry names from FMP and a few economic release names without a translation stay in English.
- **Links open directly:** for example `http://127.0.0.1:8765/?symbol=NVDA` analyzes NVDA straight away.
- **Local only:** the page listens on 127.0.0.1, so other devices on your network cannot open it.

The page runs the same analysis as `analyze.py` (the same fa-2.0 document and report), and both share the same cache. For the candles the page makes 1 more API call (the past year's daily open, high, low and close); without them it draws the daily closes.

---

## 3. Cache

- **Location:** `~/.cache/fmp-fundamentals` (on Windows `C:\Users\<username>\.cache\fmp-fundamentals`)
- **Lifetime:** latest quote 1 minute, financial statements 7 days, price history and sector data 12 hours, Treasury yields 6 hours, economic calendar 3 hours
- **Skip the cache:** add `--refresh` on the command line, or tick "Ignore cache" on the web page
- **Clear the cache:**

```bash
python scripts/fmp_client.py clear-cache
```

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `FMP_API_KEY is not set` | The key is not set, or the terminal / Claude was not restarted afterwards. See "Set the API key" |
| `API key problem` / `key rejected` | Wrong or expired key. Set the right key, then open a new terminal / restart Claude. See "Set the API key" |
| `does not cover TICKER` | The plan covers US stocks only. For Hong Kong or mainland China listings, try the US ADR |
| `No profile found for XXX` | Wrong ticker |
| The report shows "Skipped (not in your FMP plan)" | Your plan lacks some endpoints (peers, analyst estimates, quarterly data and so on). The rest of the analysis still works from annual statements |
| Price or market cap looks old | Check where the report's data notes say the price came from: if it says the company profile, the data source gave no latest quote, so add `--refresh` or tick "Ignore cache" on the web page. While the US market is closed the price does not change |
| Windows says `python` is not found | Use `py`, e.g. `py scripts/analyze.py AAPL` |
| A Mac says `command not found: python` | Use `python3` on a Mac |
| On a Mac, Claude says `FMP_API_KEY is not set` although Terminal has it | The Claude desktop app did not read `~/.zshrc`. Also put the key in the `env` block of `~/.claude/settings.json` (step 4 ⑥), then quit the app with ⌘ + Q and reopen it |
| On a Mac, `CERTIFICATE_VERIFY_FAILED` when connecting to FMP's official servers | Python installed from python.org ships without certificates. Open Applications → Python 3.x and double-click `Install Certificates.command` once |
| The web page does not open / the port is taken | Check that `server.py` is still running, or use another port: `--port 9000` |
| Some metrics show n/a or are meaningless for a financial company or REIT | Expected: gross margin, EV multiples and DCF do not apply to banks and insurers. The report's "Company type" note names the measures that do not apply |
| The DCF discount rate says `fixed default` | The Treasury or equity risk premium endpoint returned no data, so the fixed 9% was used this time. Run `fmp_client.py check` to see which endpoint failed |
| The industry row in the industry comparison is n/a | FMP has no aggregate for that industry on that exchange; the sector row and the peer comparison still give a comparison |
| Industry P/E shows `negative` | The industry is loss-making as a whole (aggregate P/E below 0), so there is no industry P/E to compare with |
| A note says `--iv is ignored`, `--no-insider is ignored` or `--contract is deprecated` | v2.0 accepts these options for one version and ignores them (`--contract` writes fa-2.0, like `--json`); remove them from your scripts |
| `Cannot convert ... to fa-2.0` | `facts.py` takes a full result saved by `analyze.py --json` of v1.x, or an fa-2.x file; an fa-1.x contract is not a saved result and cannot be converted |

Metric definitions and formulas: [references/metrics.md](references/metrics.md).
