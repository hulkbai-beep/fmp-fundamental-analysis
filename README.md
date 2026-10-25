# FMP 基本面分析（fmp-fundamental-analysis）

**中文** | [English](README.en.md)

用 Financial Modeling Prep（FMP）的数据，对美股做基本面分析。它可以作为 Claude 的技能使用，也可以在命令行或本地网页里直接运行。

分析内容包括：
- 增长：营收、利润、EPS、FCF 的历年数据和 CAGR
- 盈利能力和回报率：毛利率、营业利润率、ROE、ROIC
- 资产负债和流动性：净负债、负债率、流动比率、利息覆盖
- 现金流质量和资本配置：FCF/净利润、股权激励、回购、分红
- 估值：当前倍数与自身 5 年历史对比，以及与同行对比
- 行业和板块对比：公司 P/E 与所在行业、板块的 P/E 及其历史分位对比；公司、行业、板块与标普 500 近 1 月 / 3 月 / 年初至今 / 1 年涨跌对比
- 质量评分：Piotroski F-score、Altman Z
- DCF 和反向 DCF：折现率默认跟 10 年期国债挂钩（CAPM），含折现率 × 增速敏感性表
- 利率和宏观背景（可选）：国债收益率曲线、联邦基金利率、CPI / PPI / PCE / 非农 / 美联储议息的最新公布值和未来三周日程
- 分析师预期和目标价
- 股价区间：「现在」「本财年末」「下一财年末」三个时点的前瞻 P/E 和 EV/EBITDA 区间（未来 12 个月 EPS / EBITDA × 公司自己过去 3 年同口径倍数的 25 / 50 / 75 分位），到这两个财年末的波动区间（68% 和 95%，可以填期权隐含波动率），并和 DCF 区间、分析师目标价、52 周区间放在一起对比
- 内部人交易（只作观察，不计入评分）：近 12 个月高管、董事在公开市场的买入和卖出，剔除股权授予、期权行权、扣股缴税等非市价交易；几位内部人在 90 天内集体买入，或 CEO / CFO 大额买入时，会在自动提示里标出
- 自动提示：列出优点和风险，作为进一步核实的线索，不是结论
- 基本面打分：估值 35%、质量 25%、成长 20%、财务健康 20% 四大项，每个指标按固定区间打 −2 到 +2 分，合成总分和「看多 / 偏多 / 中性 / 偏空 / 看空」标签（和技术面打分同一套刻度），附置信度；价值陷阱和资产负债表红线会把总分封顶在中性。规则固定、有版本号，详见 `references/metrics.md` 第 12 节

所有计算都由脚本完成，Claude 只负责解读。

> 这是分析工具，不构成投资建议。数据可能有误，重要数字请对照公司财报核实。

---

## 目录结构

```
fmp-fundamental-analysis/
├── SKILL.md            # 给 Claude 看的技能说明（工作流程、解读规则、报告模板）
├── README.md           # 本文件：给人看的使用说明（中文）
├── README.en.md        # 英文版使用说明
├── references/
│   ├── validation-set.txt  # 验证打分用的约 20 只股票，各类公司都有
│   └── metrics.md      # 指标定义、阈值、行业注意事项
├── scripts/
│   ├── fmp_client.py   # FMP API 客户端：连接、缓存、限速，以及 check / get 命令
│   ├── analyze.py      # 主分析脚本：生成完整报告
│   ├── score.py        # 基本面打分：四大项、打分区间、封顶规则和置信度
│   ├── score_batch.py  # 批量打分：一串股票的分数写成 CSV，改规则前后可对比
│   └── macro.py        # 利率、宏观和板块数据：独立的宏观仪表盘，也供 analyze.py 调用
└── ui/
    ├── server.py       # 本地网页服务器
    ├── index.html      # 网页界面
    └── i18n.js         # 网页的中英文切换和翻译表
└── tests/
    ├── fake_fmp.py     # 离线的假 FMP 数据（三家虚构公司），测试和试网页用
    └── test_score.py   # 打分的离线测试：python3 -m unittest discover -s tests（不需要 API key）
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

它会显示当前连接（官方还是代理、路径前缀、认证方式、证书验证状态），然后用 AAPL 测试十几个个股接口，再测试板块/行业和宏观接口（板块表现与 P/E、国债收益率、经济指标、经济日历等）。每个接口显示 OK、EMPTY（没有数据）、RESTRICTED（套餐不含）或 ERROR。个股接口全部 OK 就说明设置成功（`historical-price-eod/full` 例外：它只给网页的 K 线图用，没有它网页会改画收盘价折线）；板块和宏观接口的结果用来确认你的套餐/代理支持哪些后续功能。加上 `--peek`（`python scripts/fmp_client.py check --peek`）还会打印板块和宏观接口返回的字段名和首尾两行，方便排查数据格式。

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

Claude 会运行 `analyze.py`，然后按 SKILL.md 里的模板写一份报告。报告包括结论、增长、盈利能力、资产负债、现金流、估值、风险、关注点和数据说明。

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

常用参数：

| 参数 | 说明 | 什么时候用 |
|---|---|---|
| `--peers MSFT,GOOGL` | 指定对比公司，逗号分隔 | 想和特定公司比较，或自动找到的同行不合适 |
| `--peers none` | 不做同行对比 | 节省时间和 API 调用 |
| `--max-peers 5` | 自动同行的最多数量（默认 5） | |
| `--years 5` | 拉取几年历史（默认 5，Starter 套餐上限 5） | |
| `--discount 0.10` | DCF 折现率。默认 = 10 年期国债收益率 + Beta × 美国股权风险溢价，限制在 7%-13%，取到 0.1%；拿不到利率数据时用 9% | Beta 明显不能代表风险时（新上市、高负债、业务转型）手动指定 |
| `--growth 0.06` | DCF 第 1-5 年增速（默认：历史营收 CAGR，限制在 0-15%） | 历史增速不能代表未来（并购、放缓、公司指引） |
| `--terminal 0.025` | DCF 永续增速（默认 0.025） | |
| `--fcf-base avg3` | DCF 起始 FCF 用近 3 年平均（默认 `latest`，用最新一期） | 周期性行业，或最近一年波动大 |
| `--iv 0.45` | 股价区间里的波动区间改用这个年化隐含波动率（0.45 = 45%；默认用过去一年的实际波动率）；网页里是「隐含波动率 %」 | 从券商那里查到了这只股票的期权隐含波动率 |
| `--no-ttm` | 不用最近 12 个月（TTM）数据，可以省 3 次 API 调用 | |
| `--macro` | 在报告里加「利率和宏观背景」一节（多 6 次 API 调用） | 想看利率、通胀、美联储对这家公司的影响 |
| `--no-market` | 不拉国债、板块、行业数据（折现率回到固定 9%，没有行业对比一节），省 9 次 API 调用；不能和 `--macro` 一起用 | 这些接口出错，或想要旧版结果 |
| `--no-insider` | 不拉内部人交易（没有这一节），省 1 到 5 次 API 调用；打分不受影响 | 不需要这一节，或接口出错 |
| `--json out.json` | 把所有计算结果另存为 JSON | 需要原始数字，或交给其他工具使用 |
| `--refresh` | 忽略缓存，重新拉取数据 | 数据看起来过时，或公司刚发布财报 |

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

时间都是 UTC。各板块和行业的 P/E、涨跌幅是 FMP 按交易所（默认纳斯达克）汇总的等权数据，适合看方向和相对位置，不等同于标普 500 的板块指数。

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
- **页面上可以设置：** 股票代码、对比公司、折现率 %（留空 = 跟国债挂钩自动计算）、1-5 年增速 %、永续增速 %、隐含波动率 %（留空 = 用过去一年的实际波动率）、起始 FCF（最新或 3 年平均）、宏观背景、忽略缓存。
- **页面显示的内容：**
  - 走第三方代理时，顶部有黄色提示条标明数据来源；直连官方时不显示。
  - 公司概况：股价、市值，以及 P/E、EV/EBITDA、FCF 收益率、ROIC、Piotroski、DCF 价值等关键指标。股价每次分析都取最新报价（缓存 1 分钟），下面显示报价时间（美东），K 线图最后一根也按这个价格更新。
  - 股价 K 线图（每天的开盘、最高、最低、收盘价，下方是成交量），可以切换 3 个月 / 6 个月 / 年初至今 / 1 年；鼠标移到某一天会显示那天的数字。图太窄放不下每天一根时自动改成周 K 线；数据源没有开高低价时只画收盘价折线。
  - 自动提示的优点和风险。
  - 「基本面打分」卡片：总分、标签和置信度，下面是四大项各自的权重、得分、对总分的贡献和数据覆盖；点开一个大项能看到每个指标的数值、打分区间（命中的那一档高亮）、得分、权重和贡献，以及封顶规则、需要留意的矛盾、合理价值区间和「怎么算的」说明。
  - 报告的各部分按标签页分开显示，底部可以展开完整文字报告。
  - 「股价区间」标签页有一张区间对比图：按时点分组（过去 52 周、现在、各财年末、12 个月后，按时间先后），每组里每种方法一条横条，圆点是中值，竖线是当前股价，波动率行的浅色部分是 95% 区间；鼠标移到某一行会显示具体数字。下面的表格用同样的「方法 + 时点」名称。顶部卡片显示三个前瞻 P/E 区间：现在（未来 12 个月 EPS，由本财年和下一财年按剩余时间加权），以及同一个 P/E 区间分别乘本财年、下一财年的 EPS。
- **中英文切换：** 右上角的「EN / 中文」按钮切换整个页面和报告的语言，默认中文，浏览器会记住上次的选择。翻译只在网页里做：数字不变，底部的完整文字报告始终保留英文原文；FMP 返回的行业名、少数没收录的经济数据名称会保留英文。
- **链接可以直接打开：** 例如 `http://127.0.0.1:8765/?symbol=NVDA` 会自动分析 NVDA。
- **只能在本机访问：** 网页只监听 127.0.0.1，局域网里的其他设备打不开。

网页显示的数字和 `analyze.py` 的结果完全一致，两者也共用同一个缓存。

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
| 金融或 REIT 公司的某些指标显示 n/a 或没有意义 | 这是正常的：银行、保险不适用毛利率、EV 倍数和 DCF。报告的 sector note 会说明 |
| DCF 折现率显示 `fixed default` | 国债或股权风险溢价接口没拿到数据，这次用了固定 9%。运行 `fmp_client.py check` 看是哪个接口有问题 |
| 行业对比里行业那一行是 n/a | FMP 在该交易所没有这个行业的汇总数据，可以参考板块那一行和同行对比 |
| 行业 P/E 显示 `negative` | 这个行业整体是亏损的（汇总 P/E 小于 0），P/E 对比没有意义，改看 P/S 和同行 |

指标的定义和判断阈值见 [references/metrics.md](references/metrics.md)。
