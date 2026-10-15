# FMP Fundamental Analysis (fmp-fundamental-analysis)

[中文](README.md) | **English**

Fundamental analysis of US stocks using Financial Modeling Prep (FMP) data. It works as a Claude skill, and it can also be run directly from the command line or as a local web page.

What it covers:
- Growth: yearly revenue, profit, EPS and FCF, with CAGR
- Profitability and returns: gross margin, operating margin, ROE, ROIC
- Balance sheet and liquidity: net debt, leverage, current ratio, interest coverage
- Cash flow quality and capital allocation: FCF / net income, stock-based compensation, buybacks, dividends
- Valuation: current multiples against the company's own 5-year history and against peers
- Industry and sector context: the company's P/E against its industry's and sector's P/E and their historical percentiles; 1-month / 3-month / year-to-date / 1-year returns of the company, industry and sector against the S&P 500
- Quality scores: Piotroski F-score, Altman Z
- DCF and reverse DCF: the discount rate is tied to the 10-year Treasury yield by default (CAPM), with a discount rate × growth sensitivity table
- Rates and macro backdrop (optional): Treasury yield curve, Fed funds rate, the latest readings of CPI / PPI / PCE / payrolls / Fed decisions, and the next three weeks' schedule
- Analyst estimates and price targets
- Price range: forward P/E and EV/EBITDA ranges at three points, **now**, **the end of the current fiscal year** and **the end of the next fiscal year** (next-12-month EPS / EBITDA × the 25th / 50th / 75th percentile of the company's own 3-year multiple on the same basis); volatility ranges to those two fiscal year ends (68% and 95%, optionally from options-implied volatility); all side by side with the DCF range, analyst price targets and the 52-week range
- Automated flags: positives and concerns, as leads to check, not conclusions

All calculations are done by the scripts; Claude only interprets the results.

> This is an analysis tool, not investment advice. Data may contain errors; verify important figures against the company's filings.

---

## Folder layout

```
fmp-fundamental-analysis/
├── SKILL.md            # Skill instructions for Claude (workflow, interpretation rules, report template)
├── README.md           # Usage guide for people (Chinese)
├── README.en.md        # This file: usage guide for people (English)
├── references/
│   └── metrics.md      # Metric definitions, thresholds, sector caveats
├── scripts/
│   ├── fmp_client.py   # FMP API client: connection, cache, rate limiting, plus the check / get commands
│   ├── analyze.py      # Main analysis script: builds the full report
│   └── macro.py        # Rates, macro and sector data: a standalone macro dashboard, also used by analyze.py
└── ui/
    ├── server.py       # Local web server
    ├── index.html      # Web page
    └── i18n.js         # Chinese/English toggle and translation tables for the web page
```

## Requirements

- Python 3.8 or later, standard library only: **no pip install needed**.
- On Windows the command is usually `python` (use `py` if it is not found); on macOS / Linux use `python3`.

---

## 1. First-time setup

Steps 1-4 below are mostly about Windows; **on a MacBook, go straight to step 5** and follow it step by step.

### 1. Set the API key

The API key is read only from the environment variable `FMP_API_KEY`. Do not write it into any file in this folder.

Windows (PowerShell or CMD):

```bash
setx FMP_API_KEY "your-key"
```

macOS / Linux: add `export FMP_API_KEY="your-key"` to `~/.zshrc` or `~/.bashrc` (detailed Mac steps in step 5).

> `setx` only applies to terminals opened **afterwards**. After setting it, open a new terminal and restart Claude so they can see the new variable.

### 2. Using a third-party FMP proxy (this machine's current setup)

This machine uses a **third-party FMP proxy, not FMP's official servers**:

| Environment variable | Value / notes |
|---|---|
| `FMP_API_KEY` | The token the proxy provider gave you |
| `FMP_BASE_URL` | The proxy address; on this machine `https://54.236.92.205` |
| `FMP_TLS_VERIFY` | `0` turns off HTTPS certificate verification. This proxy is a bare IP address and its certificate does not verify, so it is needed |
| `FMP_PATH_PREFIX`, `FMP_AUTH_STYLE` | Usually not needed: detected automatically on the first connection and saved |

Set the proxy address:

```bash
setx FMP_BASE_URL "https://54.236.92.205"
```

**The risk of `FMP_TLS_VERIFY=0`:** with certificate verification off, the connection can be intercepted by a man in the middle, and your API key travels over it. The current practice is to set it only when needed and only for a single run, never permanently with `setx`:
- Claude handles this automatically when it runs the skill (see SKILL.md).
- The local web page handles it automatically.
- When you run the scripts yourself from the command line, set it by hand (see below).

In the long run, an official FMP key or a proxy with a valid certificate is safer.

Data obtained through the proxy is resold FMP data. The report's Data notes state the data route; be extra careful when a number looks odd.

### 3. Other optional environment variables

| Environment variable | Default | Notes |
|---|---|---|
| `FMP_MAX_PER_MIN` | `280` | Maximum requests per minute |
| `FMP_MAX_WORKERS` | `6` | How many requests run at once. Lower it when the proxy is unstable or often returns 429; `1` sends them one at a time |
| `FMP_TIMEOUT` | `30` | Seconds to wait for each request. Raise to `60` if the proxy is slow and often times out |
| `FMP_CACHE_DIR` | `~/.cache/fmp-fundamentals` | Cache folder |

### 4. Check the connection

```bash
python scripts/fmp_client.py check
```

It shows the current connection (official or proxy, path prefix, auth style, certificate verification), tests a dozen single-stock endpoints with AAPL, then tests the sector/industry and macro endpoints (sector performance and P/E, Treasury yields, economic indicators, the economic calendar and so on). Each endpoint shows OK, EMPTY (no data), RESTRICTED (not in your plan) or ERROR. If all single-stock endpoints are OK, setup is done (except `historical-price-eod/full`, which only feeds the web page's candlestick chart; without it the page draws a line of closing prices); the sector and macro results tell you which later features your plan or proxy supports. With `--peek` (`python scripts/fmp_client.py check --peek`) it also prints the field names and the first and last rows the sector and macro endpoints return, to help diagnose data-format problems.

Checking through the proxy in PowerShell (applies to the current terminal window only):

```powershell
$env:FMP_TLS_VERIFY = '0'; python scripts/fmp_client.py check
```

### 5. Setting up on a MacBook (macOS)

Steps 1-4 above are mostly about Windows. To set everything up from scratch on a Mac, follow these steps. Run the commands in Terminal: press ⌘ + Space and search for "Terminal". macOS uses zsh by default, and its settings file is `~/.zshrc`.

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

**③ Set the API key and proxy address**

Open `~/.zshrc` in the nano editor in Terminal, so the key does not end up in your command history. Avoid TextEdit: it can turn the quotes into curly quotes, which breaks the settings:

```bash
nano ~/.zshrc
```

Move to the end of the file with the arrow keys and paste these two lines, with your real key. Press Ctrl + O and Enter to save, then Ctrl + X to exit:

```bash
export FMP_API_KEY="your-key"
export FMP_BASE_URL="https://54.236.92.205"
```

Back in Terminal, run `source ~/.zshrc` (or close Terminal and open a new window). Check that it worked (this prints "set", never the key):

```bash
[ -n "$FMP_API_KEY" ] && echo "set" || echo "not set"
```

Do **not** put `FMP_TLS_VERIFY=0` in `~/.zshrc`; add it to each run instead (next step).

**④ Check the connection**

```bash
FMP_TLS_VERIFY=0 python3 scripts/fmp_client.py check
```

`FMP_TLS_VERIFY=0` in front of a command applies to that command only, like `$env:FMP_TLS_VERIFY = '0'; ...` on Windows.

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
    "FMP_API_KEY": "your-key",
    "FMP_BASE_URL": "https://54.236.92.205"
  }
}
```

Open it with `nano ~/.claude/settings.json` (nano creates the file if it does not exist) and save and exit the same way. If the file already has content, merge in just the `"env"` block rather than replacing what is there.

**Other commands on a Mac:** use `python3` wherever this guide says `python`, and write PowerShell's `$env:FMP_TLS_VERIFY = '0'; python ...` as `FMP_TLS_VERIFY=0 python3 ...`.

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

Claude runs `analyze.py` and writes a report from the template in SKILL.md: conclusion, growth, profitability, balance sheet, cash flow, valuation, risks, things to watch and data notes.

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

When going through the third-party proxy, turn off certificate verification first in PowerShell (current terminal window only):

```powershell
$env:FMP_TLS_VERIFY = '0'; python scripts/analyze.py AAPL
```

On a Mac:

```bash
FMP_TLS_VERIFY=0 python3 scripts/analyze.py AAPL
```

Common options:

| Option | What it does | When to use it |
|---|---|---|
| `--peers MSFT,GOOGL` | Comparison companies, comma-separated | You want specific companies, or the automatic peers are a poor fit |
| `--peers none` | No peer comparison | Saves time and API calls |
| `--max-peers 5` | Maximum number of automatic peers (default 5) | |
| `--years 5` | Years of history to fetch (default 5; the Starter plan's limit is 5) | |
| `--discount 0.10` | DCF discount rate. Default = 10-year Treasury yield + beta × US equity risk premium, kept within 7%-13%, rounded to 0.1%; 9% when rates data is unavailable | Beta clearly misstates the risk (recent IPO, heavy debt, business in transition) |
| `--growth 0.06` | DCF growth for years 1-5 (default: historical revenue CAGR, clamped to 0-15%) | Past growth is a poor guide (acquisitions, slowdown, company guidance) |
| `--terminal 0.025` | DCF terminal growth (default 0.025) | |
| `--fcf-base avg3` | Start the DCF from the 3-year average FCF (default `latest`) | Cyclical businesses, or a volatile latest year |
| `--iv 0.45` | Use this annual implied volatility for the price-range volatility ranges (0.45 = 45%; default: the past year's realized volatility); "Implied vol %" on the web page | You have the stock's options-implied volatility from your broker |
| `--no-ttm` | Skip trailing-twelve-month (TTM) data; saves 3 API calls | |
| `--macro` | Add a "Rates & macro backdrop" section to the report (6 more API calls) | You want to see how rates, inflation and the Fed bear on the company |
| `--no-market` | Skip Treasury, sector and industry data (fixed 9% discount rate, no industry section); saves 9 API calls; cannot be combined with `--macro` | Those endpoints fail, or you want the old behaviour |
| `--json out.json` | Also save every computed number to a JSON file | You need the raw numbers, or another tool will use them |
| `--refresh` | Ignore the cache and fetch again | Data looks stale, or the company just reported |

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

All times are UTC. Sector and industry P/E and returns are FMP's equal-weighted aggregates per exchange (NASDAQ by default): good for direction and relative position, not the same as S&P 500 sector indexes.

Raw data from any FMP endpoint the analysis does not cover:

```bash
python scripts/fmp_client.py get key-metrics symbol=AAPL period=annual limit=5
```

### Option 3: local web UI

Start it:

```bash
python ui/server.py
```

On a Mac, use `python3 ui/server.py`, started from a Terminal window where `~/.zshrc` is already set up. Then open **http://127.0.0.1:8765** in a browser; press Ctrl+C to stop. If the port is taken, pick another: `python ui/server.py --port 9000`.

- **Handled automatically at start-up:**
  - Reads the `FMP_*` variables saved with `setx`, even if the terminal was opened before `setx`.
  - When connecting to the 54.236.92.205 proxy, sets `FMP_TLS_VERIFY=0` for this server process only.
- **Settings on the page:** ticker, comparison companies, discount rate % (blank = automatic, tied to Treasuries), growth years 1-5 %, terminal growth %, implied volatility % (blank = the past year's realized volatility), starting FCF (latest or 3-year average), macro backdrop, ignore cache.
- **What the page shows:**
  - A yellow banner at the top saying the data comes from a third-party FMP proxy.
  - Company overview: price, market cap, and key figures such as P/E, EV/EBITDA, FCF yield, ROIC, Piotroski and DCF value. Each analysis takes the price from the latest quote (cached for 1 minute) and shows the quote time (New York) under it; the last candle of the chart is updated to that price too.
  - A candlestick price chart (each day's open, high, low and close, with volume underneath) for 3 months, 6 months, year to date or 1 year; hovering a day shows its numbers. When the chart is too narrow for a candle a day it switches to weekly candles; when the data source has no open, high or low prices it draws a line of closing prices.
  - The automated positives and concerns.
  - Each part of the report on its own tab, with the full text report expandable at the bottom.
  - The "Price range" tab has a comparison chart grouped by horizon (past 52 weeks, now, each fiscal year end, in 12 months, in time order): one bar per method in each group, a dot at the mid value, a vertical line at the current price, and a lighter band on the volatility rows for the 95% range; hovering a row shows its numbers. The table below uses the same method + horizon names. The header card shows the forward P/E range for now.
- **Chinese / English toggle:** the "EN / 中文" button at the top right switches the whole page and report; Chinese by default, and the browser remembers your last choice. Translation happens only in the web page: numbers do not change, the full text report at the bottom stays in the original English, and industry names from FMP and a few economic release names without a translation stay in English.
- **Links open directly:** for example `http://127.0.0.1:8765/?symbol=NVDA` analyzes NVDA straight away.
- **Local only:** the page listens on 127.0.0.1, so other devices on your network cannot open it.

The numbers on the page are exactly those `analyze.py` produces, and both share the same cache.

---

## 3. Cache

- **Location:** `~/.cache/fmp-fundamentals` (on Windows `C:\Users\<username>\.cache\fmp-fundamentals`)
- **Lifetime:** latest quote 1 minute, financial statements 7 days, price history and sector data 12 hours, Treasury yields 6 hours, economic calendar 3 hours
- **Skip the cache:** add `--refresh` on the command line, or tick "Ignore cache" on the web page
- **Clear the cache:**

```bash
python scripts/fmp_client.py clear-cache
```

This also deletes the detected proxy connection settings; they are detected again on the next run.

---

## 4. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `FMP_API_KEY is not set` | The key is not set, or the terminal / Claude was not restarted afterwards. See "Set the API key" |
| `API key problem` / `key rejected` | Wrong or expired key. With a proxy, run `fmp_client.py check` first so the connection is detected again |
| `HTTPS certificate verification failed for 54.236.92.205` | The proxy's certificate cannot be verified. Set `FMP_TLS_VERIFY=0` for a single run (mind the risk) |
| `does not cover TICKER` | The plan covers US stocks only. For Hong Kong or mainland China listings, try the US ADR |
| `No profile found for XXX` | Wrong ticker |
| The report shows "Skipped (not in your FMP plan)" | Your plan lacks some endpoints (peers, analyst estimates, quarterly data and so on). The rest of the analysis still works from annual statements |
| Price or market cap looks old | Check where the report's data notes say the price came from: if it says the company profile, the data source gave no latest quote, so add `--refresh` or tick "Ignore cache" on the web page. While the US market is closed the price does not change |
| Windows says `python` is not found | Use `py`, e.g. `py scripts/analyze.py AAPL` |
| A Mac says `command not found: python` | Use `python3` on a Mac |
| On a Mac, Claude says `FMP_API_KEY is not set` although Terminal has it | The Claude desktop app did not read `~/.zshrc`. Also put the key in the `env` block of `~/.claude/settings.json` (step 5 ⑥), then quit the app with ⌘ + Q and reopen it |
| On a Mac, `CERTIFICATE_VERIFY_FAILED` when connecting to FMP's official servers | Python installed from python.org ships without certificates. Open Applications → Python 3.x and double-click `Install Certificates.command` once |
| The web page does not open / the port is taken | Check that `server.py` is still running, or use another port: `--port 9000` |
| Some metrics show n/a or are meaningless for a financial company or REIT | Expected: gross margin, EV multiples and DCF do not apply to banks and insurers. The report's sector note explains |
| The DCF discount rate says `fixed default` | The Treasury or equity risk premium endpoint returned no data, so the fixed 9% was used this time. Run `fmp_client.py check` to see which endpoint failed |
| The industry row in the industry comparison is n/a | FMP has no aggregate for that industry on that exchange; use the sector row and the peer comparison instead |
| Industry P/E shows `negative` | The industry is loss-making as a whole (aggregate P/E below 0), so the P/E comparison is meaningless; look at P/S and peers instead |

Metric definitions and thresholds: [references/metrics.md](references/metrics.md).
