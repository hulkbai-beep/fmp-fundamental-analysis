# FMP 基本面分析（fmp-fundamental-analysis）

**中文** | [English](README.en.md)

用 Financial Modeling Prep（FMP）的数据，对美股做基本面分析：只给事实和标准模型。它可以作为 Claude 的技能使用，也可以在命令行或本地网页里直接运行。

分析内容包括：
- 增长：营收、利润、EPS、FCF 的历年数据和 CAGR
- 盈利能力和回报率：毛利率、营业利润率、ROE、ROIC
- 资产负债和流动性：净负债、负债率、流动比率、利息覆盖
- 现金流质量和资本配置：FCF/净利润、股权激励、回购、分红
- 估值：当前倍数与自身历年财年末的倍数对比（默认 5 年），以及与同行对比
- 前瞻倍数：按未来两个财年各自的 EPS、按未来 12 个月 EPS 算的前瞻 P/E，前瞻 EV/EBITDA，以及每日前瞻 P/E 和 EV/EBITDA 过去 3 年的分布（10 / 25 / 50 / 75 / 90 分位和今天所处的分位）；只是统计，不换算成股价
- 行业和板块 P/E：公司 P/E 与所在行业、板块的 P/E 对比，以及行业、板块 P/E 在自身历史中的位置
- 质量评分：Piotroski F-score、Altman Z（附公开的分界值）
- DCF 和反向 DCF：折现率默认跟 10 年期国债挂钩（CAPM），含折现率 × 增速敏感性表
- 分析师一致预期：EPS、营收、EBITDA 预期，原样列出
- 利率和宏观背景（可选）：国债收益率曲线、联邦基金利率、CPI / PPI / PCE / 非农 / 美联储议息的最新公布值、未来三周日程，以及公司、所在行业和板块与标普 500 近 1 月 / 3 月 / 年初至今 / 1 年的涨跌对比
- 给其他工具用的唯一输出：fa-2.0 文档（`--json` / `--facts`），每个字段的含义见 `contracts/fa-2.0.schema.json`

所有计算都由脚本完成，Claude 负责把结果讲清楚。本 skill 不判断买还是卖，也不给打分、目标价和价格区间：决定由你做，或者交给决策引擎（[investment-final-plan](https://github.com/hulkbai-beep/investment-final-plan)，它用 fa-2.0 自己计算基本面打分）。

> 这是分析工具，不构成投资建议。数据可能有误，重要数字请对照公司财报核实。

---

## v2.0 的变化

v2.0 只给事实和标准模型。删掉的内容，以及有替代时由什么替代：
- 基本面打分（四大项、标签、置信度、封顶规则）和 fa-1.1 契约，连同 `scripts/score.py`、`scripts/contract.py`、`contracts/fa-1.1.schema.json`、`scripts/score_batch.py`、`references/validation-set.txt`。打分现在由决策引擎计算：investment-final-plan 的 `ifp/fundamental_view.py`，规则 1.3，说明见 [docs/fundamental-score-1.3.md](https://github.com/hulkbai-beep/investment-final-plan/blob/main/docs/fundamental-score-1.3.md)。
- 价格区间和价位（换算成股价的前瞻倍数区间、财年末价位卡片、52 周区间）、波动区间（`--iv`）、分析师目标价和安全边际。前瞻倍数及其 3 年分布作为统计保留（各分位和今天的分位）；DCF 和反向 DCF 保留，每个假设都列出，但不和股价对比。
- 内部人交易（`scripts/insider.py`、`--no-insider`）和自动提示；网页上的 K 线图和已删除部分的卡片。网页显示的事实和报告相同。
- 输出：`--json`、`--facts` 和已弃用的 `--contract` 都写 fa-2.0。`python scripts/facts.py SAVED.json [-o OUT.json]` 转换 v1.x 用 `--json` 保存的结果（取代 `contract.py SAVED.json --facts`）。
- 不做同行对比时，一次分析调用 14 次 API，原来是 21 次；加 `--macro` 是 25 次，原来是 27 次：不再拉内部人交易和目标价，公司、行业、板块与标普 500 的涨跌对比以及 3 个月前、1 年前的国债曲线只在加 `--macro` 时才拉取。

## 目录结构

```
fmp-fundamental-analysis/
├── SKILL.md            # 给 Claude 看的技能说明（工作流程、怎样呈现事实、回答模板）
├── README.md           # 本文件：给人看的使用说明（中文）
├── README.en.md        # 英文版使用说明
├── references/
│   └── metrics.md      # 每个数字怎么算、标准模型、指标在什么情况下会误导
├── scripts/
│   ├── fmp_client.py   # FMP API 客户端：连接、缓存、限速，以及 check / get 命令
│   ├── analyze.py      # 主分析脚本：屏幕上输出报告，加 --json / --facts 写 fa-2.0 文档
│   ├── facts.py        # fa-2.0 文档：报表、比率、估值倍数和标准模型；转换 v1.x 保存的结果
│   ├── facts_report.py # 报告：把一份 fa-2.0 文档写成 markdown（网页和决策引擎也用它）
│   ├── symbols.py      # 股票代码规范化：BRK.B → BRK-B，拒绝外国交易所代码
│   └── macro.py        # 利率、宏观和板块数据：独立的宏观仪表盘，也供 analyze.py 调用
├── contracts/
│   └── fa-2.0.schema.json  # fa-2.0 每个字段的定义（JSON Schema）
├── ui/
│   ├── server.py       # 本地网页服务器
│   ├── index.html      # 网页界面
│   └── i18n.js         # 网页的中英文切换和翻译表
└── tests/              # 离线测试，不需要 API key：python -m unittest discover -s tests
    ├── fake_fmp.py     # 离线的假 FMP 数据（八家虚构公司：QUAL、TRAP、BANK、EXCH、UTIL、QTRS、ADJE、REIT），测试和试网页用
    ├── test_cli.py     # 命令行、转换脚本、API 调用次数和网页接口的测试
    ├── test_facts.py   # fa-2.0 的测试：符合 schema、不含判断用词、旧版本保存的结果转换后和以前一致
    ├── test_facts_report.py  # 报告的测试：各节顺序、表格和以前一致、不含判断用词、每句都有中文翻译
    ├── test_docs.py    # 文档和代码一致的测试：参数、文件路径、报告各节、两份 README
    ├── test_page.py    # 网页的静态测试：决策引擎依赖的部分、每个标签都有中英文、已删除的部分不再出现
    ├── test_symbols.py # 股票代码规范化的测试
    └── data/           # 旧版本保存的结果和报告表格，测试用
```

## 环境要求

- Python 3.8 及以上，只用标准库，**不需要 pip install**。
- Windows 上的命令一般是 `python`（找不到时用 `py`）；macOS / Linux 上用 `python3`。

---

## 一、首次设置

下面 1-4 步以 Windows 为主；**在 MacBook 上请直接看第 5 步**，一步步照做。

### 1. 设置 API key

API key 只从环境变量 `FMP_API_KEY` 读取，不要写进本目录下的任何文件。

Windows（PowerShell 或 CMD）：

```bash
setx FMP_API_KEY "你的key"
```

macOS / Linux：把 `export FMP_API_KEY="你的key"` 加到 `~/.zshrc` 或 `~/.bashrc`（Mac 的详细步骤见第 5 步）。

> `setx` 只对**新打开**的终端生效。设置完要重新打开终端，并重启 Claude，它才能读到新变量。

### 2. 使用第三方 FMP 代理接口（可选）

本机从 2026-10-18 起用的是 **FMP 官方 key**，直连 `https://financialmodelingprep.com`，下面这些变量都不用设置，`FMP_BASE_URL` 也要保持为空。只有改用第三方代理时才需要：

| 环境变量 | 值 / 说明 |
|---|---|
| `FMP_API_KEY` | 代理服务商给你的 token |
| `FMP_BASE_URL` | 代理地址，例如 `https://1.2.3.4` |
| `FMP_TLS_VERIFY` | 设为 `0` 会关闭 HTTPS 证书验证。只在代理的证书验证不通过时设置（用裸 IP 的代理常见） |
| `FMP_PATH_PREFIX`、`FMP_AUTH_STYLE` | 一般不用设置，第一次连接时会自动识别并保存 |

设置代理地址：

```bash
setx FMP_BASE_URL "https://代理地址"
```

**关于 `FMP_TLS_VERIFY=0` 的风险：** 关闭证书验证后，连接可能被中间人截获，你的 API key 也会经过这条连接。所以只在需要时、只对单次运行设置，不要用 `setx` 永久保存。

经代理拿到的数据是转售的 FMP 数据。报告的 Data notes 会写明数据来源（route），看到异常数字时要多留个心。

### 3. 其他可选环境变量

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `FMP_MAX_PER_MIN` | `280` | 每分钟最多发多少个请求 |
| `FMP_MAX_WORKERS` | `6` | 同时并发几个请求。代理不稳定或经常报 429 时调小；设为 `1` 就是逐个请求 |
| `FMP_TIMEOUT` | `30` | 每个请求最多等几秒。代理响应慢、经常超时可以调到 `60` |
| `FMP_CACHE_DIR` | `~/.cache/fmp-fundamentals` | 缓存目录 |

### 4. 检查连接

```bash
python scripts/fmp_client.py check
```

它会显示当前连接（官方还是代理、路径前缀、认证方式、证书验证状态），然后用 AAPL 测试十个左右的个股接口，再测试板块/行业和宏观接口（板块表现与 P/E、国债收益率、经济指标、经济日历等）。每个接口显示 OK、EMPTY（没有数据）、RESTRICTED（套餐不含）或 ERROR。个股接口全部 OK 就说明设置成功；板块和宏观接口的结果用来确认你的套餐/代理支持哪些后续功能。加上 `--peek`（`python scripts/fmp_client.py check --peek`）还会打印板块和宏观接口返回的字段名和首尾两行，方便排查数据格式。

如果用的是证书无法验证的代理，在 PowerShell 里这样检查（只对当前终端窗口生效）：

```powershell
$env:FMP_TLS_VERIFY = '0'; python scripts/fmp_client.py check
```

### 5. 在 MacBook（macOS）上设置

上面 1-4 步以 Windows 为主。在 Mac 上从头装一遍，照下面做就行。命令都在「终端」里运行：按 ⌘ + 空格，搜索「终端」或 Terminal 打开。macOS 默认的 shell 是 zsh，配置文件是 `~/.zshrc`。

**① 确认 Python 和 git**

```bash
python3 --version
git --version
```

Python 显示 3.8 或以上就行。如果弹窗提示安装「命令行开发者工具」，点「安装」，它会同时装好 python3 和 git。也可以用 Homebrew 安装：`brew install python git`。

**② 下载代码**

```bash
mkdir -p ~/Documents/claude
cd ~/Documents/claude
git clone https://github.com/hulkbai-beep/fmp-fundamental-analysis.git
cd fmp-fundamental-analysis
```

如果仓库是私有的，git 会要求登录 GitHub。最省事的是先装 GitHub CLI 登录：`brew install gh`，再 `gh auth login`，然后用 `gh repo clone hulkbai-beep/fmp-fundamental-analysis` 下载。

**③ 设置 API key**

用终端里的 nano 编辑器打开 `~/.zshrc`。这样 key 不会留在命令历史里；也不要用「文本编辑」，它可能把引号自动改成中文弯引号，导致设置失效：

```bash
nano ~/.zshrc
```

用方向键移到文件末尾，粘贴下面这行，把「你的key」换成真实的 key。然后按 Ctrl + O、回车保存，再按 Ctrl + X 退出：

```bash
export FMP_API_KEY="你的key"
```

回到终端，运行 `source ~/.zshrc`（或者关掉终端再开一个）让它生效。检查有没有设置成功（只显示「已设置」，不会打印 key）：

```bash
[ -n "$FMP_API_KEY" ] && echo "已设置" || echo "没设置"
```

用官方 key 不需要 `FMP_TLS_VERIFY`。如果以后改用证书无法验证的代理，也**不要**把 `FMP_TLS_VERIFY=0` 写进 `~/.zshrc`，只在单次运行时加在命令前面。

**④ 检查连接**

```bash
python3 scripts/fmp_client.py check
```

**⑤ 安装成 Claude 技能**

```bash
mkdir -p ~/.claude/skills
rsync -a --exclude .git ~/Documents/claude/fmp-fundamental-analysis/ ~/.claude/skills/fmp-fundamental-analysis/
```

以后代码有更新，先在代码目录里 `git pull`，再跑一次同一条 `rsync`。它相当于 Windows 上的 robocopy。

**⑥ 让 Claude 读到 key**

- **在终端里运行 Claude Code（输入 `claude`）：** 它会读 `~/.zshrc`，第 ③ 步设置好、重开终端就行。
- **用 Claude 桌面 App：** 从程序坞或启动台打开的 App 可能读不到 `~/.zshrc`。如果 Claude 提示 `FMP_API_KEY is not set`，就在 `~/.claude/settings.json` 里也写一份，然后完全退出 App（⌘ + Q）再打开：

```json
{
  "env": {
    "FMP_API_KEY": "你的key"
  }
}
```

用 `nano ~/.claude/settings.json` 打开（文件不存在会自动新建），保存和退出的按键同上。如果文件里已经有内容，只把 `"env"` 这一段合并进去，不要覆盖原有内容。

**Mac 上其他命令的写法：** 本文里的 `python` 都换成 `python3`。

---

## 二、三种用法

### 用法 1：直接问 Claude（推荐）

技能装好后，在 Claude 里直接用中文或英文问就行，不用提到 FMP，例如：
- 「分析一下 AAPL 的基本面」
- 「NVDA 现在贵不贵？」
- 「比较 MSFT、GOOGL、AMZN 的盈利能力和估值」
- 「COST 的护城河怎么样？现金流质量好吗？」
- 「现在利率和通胀是什么情况？对 NVDA 这种成长股有什么影响？」
- 「最近哪些板块强？科技板块现在估值贵吗？」

Claude 会运行 `analyze.py`，然后按 SKILL.md 把事实讲清楚：事实摘要、业务概况、增长、盈利能力、资产负债和现金流、估值事实（倍数与自身历史和行业板块的对比、前瞻倍数、DCF 和反向 DCF）、质量评分、数据的局限和数据说明。它不说该买还是该卖：问「贵不贵」时，它列出这些事实，决定留给你。

**注意：Claude 实际读取的是 `~/.claude/skills/fmp-fundamental-analysis/` 里的那一份技能。**修改本目录后，要把改动同步到那里才会生效。Windows 上可以用：

```powershell
robocopy C:\Users\<用户名>\Documents\claude\fmp-fundamental-analysis C:\Users\<用户名>\.claude\skills\fmp-fundamental-analysis /E /XD .git
```

Mac 上用：

```bash
rsync -a --exclude .git ~/Documents/claude/fmp-fundamental-analysis/ ~/.claude/skills/fmp-fundamental-analysis/
```

### 用法 2：命令行

在本目录下运行：

```bash
python scripts/analyze.py AAPL
```

Mac 上用 `python3 scripts/analyze.py AAPL`。如果用的是证书无法验证的第三方代理，PowerShell 里先运行 `$env:FMP_TLS_VERIFY = '0'`，Mac 上在命令前加 `FMP_TLS_VERIFY=0`。

报告输出到屏幕（stdout，markdown 格式），提示信息输出到 stderr。报告按顺序包括（标题是英文，网页上会翻译）：
- `# TICKER - Name`，一行板块 / 行业、交易所、股价、市值、Beta，一行「Data basis」（哪几个财年、报表币种、有没有 TTM、估值用哪一期、数据日期），金融公司、收费型金融公司、REIT 和公用事业还有一条「Company type」说明，列出对这类公司没有意义的指标
- `## 1. Growth`（增长）、`## 2. Profitability & returns`（盈利能力和回报率）、`## 3. Balance sheet & liquidity`（资产负债和流动性）、`## 4. Cash flow quality & capital allocation`（现金流质量和资本配置）
- `## 5. Valuation`（估值：当前倍数与历年财年末对比、EV 和各种收益率）、`## 6. Forward multiples`（前瞻倍数及其 3 年分布）、`## 7. Industry & sector P/E`（行业和板块 P/E）、`## 8. Quality scores`（质量评分：Piotroski、Altman）、`## 9. DCF`（含敏感性表和反向 DCF）、`## 10. Analyst consensus`（分析师一致预期）
- `## 11. Peer comparison`（同行对比，只在有同行时出现）、`Rates & macro backdrop`（利率和宏观背景，只在加 `--macro` 时出现，编号接在最后一节之后）和 `## Data notes`（数据说明）

常用参数：

| 参数 | 说明 | 什么时候用 |
|---|---|---|
| `--peers MSFT,GOOGL` | 指定对比公司，逗号分隔（每家 5 次 API 调用） | 想和特定公司比较，或自动找到的同行不合适 |
| `--peers none` | 不做同行对比 | 节省时间和 API 调用 |
| `--max-peers 5` | 自动同行的最多数量（默认 5） | |
| `--years 5` | 拉取几年历史（默认 5，Starter 套餐上限 5） | |
| `--discount 0.10` | DCF 折现率。默认 = 10 年期国债收益率 + Beta × 美国股权风险溢价，限制在 7%-13%，取到 0.1%；拿不到利率数据时用 9% | Beta 明显不能代表风险时（新上市、高负债、业务转型）手动指定 |
| `--growth 0.06` | DCF 第 1-5 年增速（默认：历史营收 CAGR，限制在 0-15%） | 历史增速不能代表未来（并购、放缓、公司指引） |
| `--terminal 0.025` | DCF 永续增速（默认 0.025） | |
| `--fcf-base avg3` | DCF 起始 FCF 用近 3 年平均（默认 `latest`，用最新一期） | 周期性行业，或最近一年波动大 |
| `--no-ttm` | 不用最近 12 个月（TTM）数据，可以省 3 次 API 调用 | |
| `--macro` | 在报告里加「利率和宏观背景」一节（多 11 次 API 调用） | 想看利率、通胀、美联储的背景，以及与行业、板块和标普 500 的涨跌对比 |
| `--no-market` | 不拉国债、板块、行业数据（折现率回到固定 9%，没有行业和板块 P/E），省 4 次 API 调用；不能和 `--macro` 一起用 | 这些接口出错，或想用固定折现率 |
| `--json out.json` | 把 fa-2.0 文档另存为文件（见下文） | 需要原始数字，或交给其他工具读取 |
| `--facts out.json` | 和 `--json` 相同（保留它是因为决策引擎会传这个参数） | |
| `--contract out.json` | 已弃用，只保留一个版本：同样写 fa-2.0 文档，并提示 fa-1.1 契约已删除 | 只有旧脚本还在传它 |
| `--refresh` | 忽略缓存，重新拉取数据 | 数据看起来过时，或公司刚发布财报 |

不做同行对比（`--peers none`）时，一次分析调用 14 次 API：加 `--no-ttm` 是 11 次，加 `--no-market` 是 10 次，加 `--macro` 是 25 次。每家同行多 5 次，自动查找同行再多 1 次。`--iv` 和 `--no-insider` 在这一个版本里仍然接受，但不起作用（v2.0 没有波动区间，也不再拉内部人交易），会打印一条提示，`--help` 里也不再列出。

示例：

```bash
python scripts/analyze.py MSFT --peers GOOGL,AMZN,ORCL --discount 0.085 --fcf-base avg3
```

单独看利率和宏观（不针对某只股票）：

```bash
python scripts/macro.py              # 国债曲线、联邦基金利率、失业率、CPI，以及关键数据的最新公布值和未来三周日程
python scripts/macro.py --sectors    # 再加上各板块 P/E（对比自身历史）和涨跌幅（对比标普 500）
python scripts/macro.py --events     # 列出窗口内所有中高影响的美国经济事件
```

时间都是 UTC。各板块和行业的 P/E、涨跌幅是 FMP 按交易所（默认纳斯达克）汇总的数据，涨跌幅是成分公司每日涨跌的等权平均：适合看方向和相对位置，不等同于标普 500 的板块指数。

给其他工具用的 fa-2.0 文档：

```bash
python scripts/analyze.py NVDA --json nvda_facts.json      # 分析时直接导出（--facts 效果相同）
python scripts/facts.py nvda_full.json -o nvda_facts.json  # 把 v1.x 用 --json 保存的完整结果转换成 fa-2.0
```

fa-2.0 只放事实：每个财年（和 TTM）的报表科目与标准比率，当前、历年末和对比自身历史的估值倍数，前瞻倍数和未来 12 个月倍数过去 3 年的分布，行业和板块 P/E，原样的分析师一致预期，以及 Piotroski、Altman、DCF（每个假设都是字段）和反向 DCF。没有打分、标签、提示、价位、目标价和安全边际，这些归做决策的工具。按期间的数据是列数组，和 `period` 对齐；缺失或不适用的值是 null，同一块里的 `status` 代码说明原因。每个字段的含义见 `contracts/fa-2.0.schema.json`；2.x 版本只增加字段。每写一个文件，stderr 上会打印 `(fa-2.0 written to PATH)`。退出码：0 正常；1 FMP 出错、套餐不覆盖这只股票，或输出文件写不进去；2 API key 有问题或命令行参数无效。`facts.py` 遇到已经是 fa-2.x 的文件会原样写回，不加 `-o` 时把文档打印到屏幕，其他文件（例如 fa-1.x 契约）一律拒绝，退出码 1。

股票代码：`BRK.B`、`BRK/B`、`brk b` 这些写法都会自动转成 FMP 用的 `BRK-B`（`scripts/symbols.py`），带外国交易所后缀的（如 `SHOP.TO`、`0700.HK`）会直接提示改用美股代码或 ADR。

调用分析没覆盖到的任意 FMP 接口，拿原始数据：

```bash
python scripts/fmp_client.py get key-metrics symbol=AAPL period=annual limit=5
```

### 用法 3：本地网页 UI

启动：

```bash
python ui/server.py
```

Mac 上用 `python3 ui/server.py`，要在已经设置好 `~/.zshrc` 的终端里启动。然后在浏览器打开 **http://127.0.0.1:8765**，按 Ctrl+C 停止。端口被占用时可以换一个：`python ui/server.py --port 9000`。代码更新后要按 Ctrl+C 停掉再重新启动，网页才会用上新代码。

- **启动时自动处理：**
  - 自动读取 `setx` 保存的 `FMP_*` 变量，即使终端是在 `setx` 之前打开的也能读到。
  - 如果连的是旧代理 54.236.92.205，只对这个服务器进程设置 `FMP_TLS_VERIFY=0`；直连官方时不做任何处理。
- **页面上可以设置：** 股票代码、对比公司、折现率 %（留空 = 跟国债挂钩自动计算）、1-5 年增速 %、永续增速 %、起始 FCF（最新或 3 年平均）、宏观背景、忽略缓存。
- **页面显示的内容：** 和报告相同的事实，来自同一份 fa-2.0 文档：顶部是公司、股价和市值，然后是关键数字的小卡片，再是报告的各节。走第三方代理时会有提示，标明数据来源。
- **中英文切换：** 右上角的「EN / 中文」按钮切换页面的语言，默认中文，浏览器会记住上次的选择。翻译只在网页里做，数字不变；FMP 返回的行业名、少数没收录的经济数据名称会保留英文。
- **链接可以直接打开：** 例如 `http://127.0.0.1:8765/?symbol=NVDA` 会自动分析 NVDA。
- **只能在本机访问：** 网页只监听 127.0.0.1，局域网里的其他设备打不开。

网页运行的是和 `analyze.py` 相同的分析（同一份 fa-2.0 文档和报告），两者也共用同一个缓存。

---

## 三、缓存

- **位置：** `~/.cache/fmp-fundamentals`（Windows 上是 `C:\Users\<用户名>\.cache\fmp-fundamentals`）
- **有效期：** 最新报价 1 分钟，财务数据 7 天，历史股价和板块数据 12 小时，国债收益率 6 小时，经济日历 3 小时
- **跳过缓存：** 命令行加 `--refresh`，或在网页上勾选「忽略缓存」
- **清空缓存：**

```bash
python scripts/fmp_client.py clear-cache
```

这也会删除自动识别出的代理连接方式，下次运行时会重新识别。

---

## 四、常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `FMP_API_KEY is not set` | 没设置 key，或设置后没重开终端/重启 Claude。见「设置 API key」 |
| `API key problem` / `key rejected` | key 错误或已过期。用代理时，先运行 `fmp_client.py check` 重新识别连接方式 |
| `HTTPS certificate verification failed for 54.236.92.205` | 还在连旧代理：`FMP_BASE_URL` 没删干净，删掉后新开终端。确实要用代理时，才在单次运行时设置 `FMP_TLS_VERIFY=0`（注意风险） |
| `does not cover TICKER` | 套餐只覆盖美股。港股、A 股可以试试对应的美股 ADR |
| `No profile found for XXX` | 股票代码不对 |
| 报告里有「Skipped (not in your FMP plan)」 | 套餐不包含某些接口（同行、分析师预期、季度数据等）。其他分析仍然可以基于年报完成 |
| 股价或市值看起来是旧的 | 看报告「数据说明」里股价来自哪里：写的是公司资料，说明数据源没给最新报价，可以加 `--refresh` 或在网页上勾选「忽略缓存」；美股休市时股价本来就不变 |
| Windows 上提示找不到 `python` | 改用 `py`，例如 `py scripts/analyze.py AAPL` |
| Mac 上提示 `command not found: python` | Mac 上用 `python3` |
| Mac 上的 Claude 提示 `FMP_API_KEY is not set`，但终端里设置好了 | Claude 桌面 App 没读到 `~/.zshrc`。在 `~/.claude/settings.json` 的 `env` 里也写一份（见第 5 步 ⑥），然后用 ⌘ + Q 退出 App 再打开 |
| Mac 上连 FMP 官方服务器报 `CERTIFICATE_VERIFY_FAILED` | 从 python.org 下载安装的 Python 默认不带证书。打开「应用程序 → Python 3.x」，双击 `Install Certificates.command` 运行一次 |
| 网页打不开 / 端口被占用 | 确认 `server.py` 还在运行，或换个端口：`--port 9000` |
| 金融或 REIT 公司的某些指标显示 n/a 或没有意义 | 这是正常的：银行、保险不适用毛利率、EV 倍数和 DCF。报告里的「Company type」说明会列出不适用的指标 |
| DCF 折现率显示 `fixed default` | 国债或股权风险溢价接口没拿到数据，这次用了固定 9%。运行 `fmp_client.py check` 看是哪个接口有问题 |
| 行业对比里行业那一行是 n/a | FMP 在该交易所没有这个行业的汇总数据；板块那一行和同行对比仍然可以对照 |
| 行业 P/E 显示 `negative` | 这个行业整体是亏损的（汇总 P/E 小于 0），没有行业 P/E 可以对比 |
| 提示 `--iv is ignored`、`--no-insider is ignored` 或 `--contract is deprecated` | v2.0 在这一个版本里还接受这些参数，但不起作用（`--contract` 和 `--json` 一样写 fa-2.0）；请从自己的脚本里去掉 |
| `Cannot convert ... to fa-2.0` | `facts.py` 只接受 v1.x 用 `analyze.py --json` 保存的完整结果，或 fa-2.x 文件；fa-1.x 契约不是保存的结果，不能转换 |

指标的定义和公式见 [references/metrics.md](references/metrics.md)。
