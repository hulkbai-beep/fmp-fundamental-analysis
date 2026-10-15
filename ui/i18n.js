// Chinese / English text for the local UI (ui/index.html).
//
// UI: labels of the page itself, by key, in both languages.
// zh(): translates the English report produced by scripts/analyze.py into Chinese for display.
// It only changes how the page reads; the numbers, the CLI report and the "full text report"
// view stay as analyze.py wrote them. Text it does not recognise (FMP event names, company
// names, error details) is shown unchanged.

const UI = {
  zh: {
    title: "FMP 基本面分析",
    lang_button: "EN", lang_hint: "Switch to English",
    f_symbol: "股票代码", f_peers: "对比公司（可选）", ph_peers: "MSFT,GOOGL 或 none",
    f_discount: "折现率 %", ph_auto: "自动", discount_tip: "留空 = 10 年期国债 + Beta × 股权风险溢价（7%-13%）",
    f_growth: "1-5年增速 %", f_terminal: "永续增速 %", f_fcf: "起始 FCF", opt_latest: "最新", opt_avg3: "3年平均",
    c_macro: "宏观背景", c_refresh: "忽略缓存", go: "分析",
    loading: sym => `正在分析 ${sym}…（首次约 10-30 秒，之后有缓存会更快）`,
    notice_proxy: base => `数据来自 <b>FMP 第三方代理接口</b>（${base}），不是 FMP 官方服务器。重要数字请对照公司财报核实。`,
    notice_tls: " 本次 HTTPS 证书验证已关闭。",
    as_of: "截至", mcap: "市值",
    s_pe: "P/E", s_ev: "EV/EBITDA", s_fcfy: "FCF 收益率", s_roic: "ROIC", s_cagr: "营收 CAGR", s_pio: "Piotroski",
    s_dcf: "DCF 每股价值", s_mos: "DCF vs 股价", s_range: "前瞻 P/E 区间",
    rc_title: "各方法的股价区间", rc_fwd_pe: "前瞻 P/E", rc_dcf: "DCF", rc_targets: "分析师目标价",
    rc_week52: "52 周区间", rc_volatility: "1 年波动 ±1σ", rc_price: "现价",
    rc_note: "黑色短线 = 中值（基准、共识价或现价）；红色虚线 = 当前股价。",
    chart_title: "近一年股价", chart_aria: "一年股价走势", no_prices: "没有价格数据。",
    flags_title: "自动提示（需进一步核实，不是结论）", pos: "优点", neg: "风险", none: "无",
    full_report: "完整文字报告（英文原文）",
  },
  en: {
    title: "FMP Fundamental Analysis",
    lang_button: "中文", lang_hint: "切换到中文",
    f_symbol: "Ticker", f_peers: "Peers (optional)", ph_peers: "MSFT,GOOGL or none",
    f_discount: "Discount rate %", ph_auto: "Auto", discount_tip: "Blank = 10Y Treasury + beta × equity risk premium (7%-13%)",
    f_growth: "Growth yrs 1-5 %", f_terminal: "Terminal growth %", f_fcf: "Starting FCF", opt_latest: "Latest", opt_avg3: "3-yr average",
    c_macro: "Macro backdrop", c_refresh: "Ignore cache", go: "Analyze",
    loading: sym => `Analyzing ${sym}… (first run takes about 10-30 s; faster once cached)`,
    notice_proxy: base => `Data comes from a <b>third-party FMP proxy</b> (${base}), not FMP's official server. Verify key figures against company filings.`,
    notice_tls: " HTTPS certificate verification was off for this run.",
    as_of: "as of", mcap: "Mkt cap",
    s_pe: "P/E", s_ev: "EV/EBITDA", s_fcfy: "FCF yield", s_roic: "ROIC", s_cagr: "Revenue CAGR", s_pio: "Piotroski",
    s_dcf: "DCF value / share", s_mos: "DCF vs price", s_range: "Fwd P/E range",
    rc_title: "Price range by method", rc_fwd_pe: "forward P/E", rc_dcf: "DCF", rc_targets: "Analyst targets",
    rc_week52: "52-week range", rc_volatility: "1-yr volatility ±1σ", rc_price: "Price",
    rc_note: "Black tick = mid value (base case, consensus or current price); red dashed line = current price.",
    chart_title: "Share price, last 12 months", chart_aria: "One-year share price chart", no_prices: "No price data.",
    flags_title: "Automated flags (prompts for investigation, not conclusions)", pos: "Positives", neg: "Concerns", none: "None",
    full_report: "Full text report",
  },
};

// Whole cells, labels and headings (matched after trimming).
const ZH_EXACT = new Map(Object.entries({
  // section headings (the "N. " prefix is handled separately)
  "Profitability & returns": "盈利能力与回报",
  "Balance sheet & liquidity": "资产负债与流动性",
  "Cash flow quality & capital allocation": "现金流质量与资本配置",
  "Quality scores": "质量评分",
  "DCF (FCF-based, 10 years + terminal)": "DCF（基于自由现金流，10 年 + 永续）",
  "Analyst consensus": "分析师预期",
  "Price range (forward P/E, DCF, analyst targets, trading range)": "股价区间（前瞻 P/E、DCF、分析师目标价、交易区间）",
  "Forward P/E by fiscal year": "按财年的前瞻 P/E 区间",
  "Peer comparison (last fiscal year, same method for all)": "同行对比（统一用最近财年）",
  "Sector & industry context": "行业与板块对比",
  "Rates & macro backdrop": "利率与宏观背景",
  "Automated flags (prompts for investigation, not conclusions)": "自动提示（需进一步核实，不是结论）",
  "Data notes": "数据说明",
  "Treasury yields": "国债收益率",
  "Policy rate, jobs and prices (economic-indicators, latest two readings)": "政策利率、就业与物价（经济指标，最近两期）",
  "Latest key US releases (economic calendar, last 60 days)": "美国关键数据最新公布值（经济日历，近 60 天）",
  "Next key US events (next 3 weeks)": "接下来的美国关键数据（未来 3 周）",
  "**Positives**": "**优点**", "**Concerns**": "**风险**", "none triggered": "无",
  // table headers
  "Metric": "指标", "CAGR": "复合增速", "Multiple": "倍数", "Now": "当前", "Hist. median": "历史中位数",
  "Hist. range": "历史区间", "Now vs median": "当前 vs 中位数", "Measure": "项目", "Value": "数值",
  "Test": "检验项", "Result": "结果", "Assumption": "假设", "FY": "财年", "EPS est. (low-high)": "EPS 预期（低-高）",
  "Fwd P/E": "前瞻 P/E", "Revenue est.": "营收预期", "Rev. growth": "营收增速", "# analysts": "分析师人数",
  "Ticker": "代码", "Mkt cap": "市值", "Rev YoY": "营收同比", "Gross m.": "毛利率", "Op m.": "营业利润率",
  "ND/EBITDA": "净负债/EBITDA", "Percentile in hist.": "历史分位", "1y ago": "1 年前", "Return": "涨跌幅",
  "YTD": "年初至今", "Yield": "期限", "Indicator": "指标", "Latest": "最新", "Period": "期间", "Previous": "前值",
  "Change": "变化", "Release": "数据", "Event": "事件", "Released (UTC)": "公布时间（UTC）", "Actual": "实际值",
  "Consensus": "预期值", "When (UTC)": "时间（UTC）", "Impact": "影响",
  "Method": "方法", "Low": "低", "Mid": "中值", "High": "高", "Basis": "依据", "Year ends": "财年结束日",
  "Base": "基准", "Base vs price": "基准 vs 股价",
  // growth / profitability / balance sheet / cash flow rows
  "Revenue": "营收", "Revenue YoY": "营收同比", "Gross profit": "毛利", "Operating income": "营业利润",
  "Net income": "净利润", "EPS (diluted)": "EPS（稀释）", "EPS YoY": "EPS 同比", "Free cash flow": "自由现金流",
  "Diluted shares": "稀释股数", "Gross margin": "毛利率", "Operating margin": "营业利润率", "Net margin": "净利率",
  "EBITDA margin": "EBITDA 利润率", "FCF margin": "FCF 利润率", "R&D % revenue": "研发占营收",
  "ROIC (after tax)": "ROIC（税后）", "Cash & ST investments": "现金及短期投资", "Total debt": "总债务",
  "Net debt (neg = net cash)": "净债务（负数 = 净现金）", "Net debt / EBITDA": "净债务 / EBITDA",
  "Debt / equity": "债务 / 股东权益", "Current ratio": "流动比率", "Quick ratio": "速动比率",
  "Interest coverage (EBIT/int.)": "利息覆盖倍数（EBIT / 利息）", "Shareholders' equity": "股东权益",
  "Goodwill & intangibles": "商誉及无形资产", "Operating cash flow": "经营现金流", "Capex": "资本开支",
  "Capex % revenue": "资本开支占营收", "FCF / net income": "FCF / 净利润", "Stock comp % revenue": "股权激励占营收",
  "Buybacks": "回购", "Dividends": "分红", "Share count YoY": "股数同比",
  // valuation measures
  "Enterprise value": "企业价值", "EV / sales": "EV / 营收", "Earnings yield": "盈利收益率", "FCF yield": "FCF 收益率",
  "Dividend yield (cash paid)": "股息率（实付现金）",
  "Shareholder yield (div + buyback - issuance)": "股东回报率（分红 + 回购 - 增发）",
  "(History = price on each fiscal-year-end date x that year's fundamentals.)": "（历史值 = 每个财年末的股价 × 当年的财务数据。）",
  // Piotroski
  "Operating cash flow > 0": "经营现金流 > 0", "ROA improved": "ROA 提升",
  "Cash flow > net income (accruals)": "现金流 > 净利润（应计项）", "Long-term leverage fell": "长期杠杆下降",
  "Current ratio improved": "流动比率提升", "No net share dilution": "股本没有净稀释",
  "Gross margin improved": "毛利率提升", "Asset turnover improved": "资产周转率提升",
  "pass": "通过", "fail": "未通过",
  "Piotroski F-score: needs at least 2 fiscal years.": "Piotroski F-score：至少需要 2 个财年的数据。",
  "(Altman Z is not designed for banks/insurers; ignore it here.)": "（Altman Z 不适用于银行和保险公司，这里可以忽略。）",
  // DCF
  "Starting FCF": "起始 FCF", "Growth yrs 1-5": "第 1-5 年增速", "Growth yrs 6-10": "第 6-10 年增速",
  "Discount rate": "折现率", "Net debt deducted": "扣除的净债务", "Shares": "股数",
  "Value per share (rows = discount rate, columns = growth yrs 1-5):": "每股价值（行 = 折现率，列 = 第 1-5 年增速）：",
  "Financial-sector company: FCF-based DCF is not meaningful (use P/B, ROE, P/E).": "金融类公司：基于自由现金流的 DCF 没有意义（请看 P/B、ROE、P/E）。",
  "DCF inputs invalid (discount rate must exceed terminal growth).": "DCF 参数无效（折现率必须高于永续增速）。",
  // price range
  "Analyst price targets": "分析师目标价", "52-week closing range": "52 周收盘价区间", "1-year volatility band": "1 年波动区间",
  "discount +/-1pt, growth +/-2pt": "折现率 ±1 个百分点、增速 ±2 个百分点", "low / consensus / high": "最低 / 共识 / 最高",
  "No method had enough data for a range.": "数据不够，没有一种方法能算出区间。",
  "No analyst EPS estimates for the current or next fiscal year (not on this FMP plan or none published); forward P/E range not available.":
    "没有本财年和下一财年的分析师 EPS 预期（套餐不含或没有发布），算不了前瞻 P/E 区间。",
  "The price history has a one-day move of more than 50% (possibly a stock split the prices do not reflect), so no forward P/E range is shown.":
    "股价历史里有单日涨跌超过 50% 的情况（可能是股价没有按拆股调整），所以不显示前瞻 P/E 区间。",
  "Not enough positive-earnings price history for a P/E range (needs about 6 months).":
    "盈利为正的历史股价数据不够（约需 6 个月），算不了 P/E 区间。",
  "Forward P/E each day = close / diluted EPS of the fiscal year in progress that day (the reported figure once that year was reported, the analysts' average for the current year).":
    "每天的前瞻 P/E = 当天收盘价 ÷ 当天所在财年的稀释 EPS（已公布的财年用实际数，本财年用分析师平均预期）。",
  "Low / Base / High = analysts' average EPS x the 25th-percentile / median / 75th-percentile forward P/E. The current year's row is a fair-value range for today if the company earns that EPS and trades at its usual forward multiple; the next year's row is the same once that year becomes the current one (about a year out). Not a forecast.":
    "低 / 基准 / 高 = 分析师平均 EPS × 前瞻 P/E 的 25 分位 / 中位数 / 75 分位。本财年这一行的意思是：如果公司赚到这个 EPS、市场给它惯常的前瞻市盈率，现在的合理价格区间；下一财年这一行是一年后（下一财年变成本财年时）的同样估算。这不是预测。",
  "The share counts in the statements do not match today's share basis (for example a stock split the statements do not reflect, an ADR ratio or several share classes), so the P/E history is not comparable and no forward P/E range is shown.":
    "财报里的股数和现在的股本口径对不上（比如财报没有反映拆股、ADR 换股比例或多类股票），历史 P/E 没法比，所以不显示前瞻 P/E 区间。",
  "n/a = the average EPS estimate is zero or negative, so a P/E-based price is not meaningful.":
    "n/a = 平均 EPS 预期为零或负数，用 P/E 算价格没有意义。",
  "REIT: net-income P/E understates cash earnings, so the P/E rows are a weak guide here.":
    "REIT：按净利润算的 P/E 低估了现金收益，这里 P/E 那几行参考价值有限。",
  "The volatility band is statistical, not a valuation: if the past year's volatility holds, about two in three one-year outcomes fall inside it.":
    "波动区间是统计结果，不是估值：如果过去一年的波动幅度不变，一年后的股价大约有三分之二的可能落在这个区间里。",
  // analyst / peers
  "Not available on this FMP plan.": "当前 FMP 套餐不包含这项数据。",
  "Peer median": "同行中位数",
  "no data (plan restriction or unknown ticker)": "无数据（套餐限制或代码有误）",
  "No peers (FMP stock-peers not available on this plan, or --peers none). Re-run with --peers TICKER1,TICKER2 to compare.":
    "没有同行数据（套餐不含 stock-peers，或用了 --peers none）。可以用 --peers 代码1,代码2 重新运行。",
  // sector & industry
  "Industry (equal-weight)": "行业（等权）", "Sector (equal-weight)": "板块（等权）", "S&P 500 (SPY)": "标普 500（SPY）",
  // rates & macro
  "10Y-2Y spread": "10Y-2Y 利差", "10Y-3M spread": "10Y-3M 利差",
  "The curve is inverted (10Y below 2Y).": "收益率曲线倒挂（10 年期低于 2 年期）。",
  "Treasury rates not available.": "没有拿到国债收益率数据。",
  "Fed funds rate (effective, monthly)": "联邦基金有效利率（月度）", "Unemployment rate": "失业率",
  "CPI index (1982-84=100)": "CPI 指数（1982-84=100）",
  "Fed rate decision": "美联储利率决议", "CPI YoY": "CPI 同比", "Core CPI YoY": "核心 CPI 同比", "CPI MoM": "CPI 环比",
  "Core CPI MoM": "核心 CPI 环比", "PPI YoY": "PPI 同比", "Core PPI YoY": "核心 PPI 同比", "PPI MoM": "PPI 环比",
  "Core PPI MoM": "核心 PPI 环比", "PCE price index YoY": "PCE 物价指数同比", "Core PCE price index YoY": "核心 PCE 物价指数同比",
  "Core PCE price index MoM": "核心 PCE 物价指数环比", "Nonfarm payrolls": "非农就业人数",
  "GDP growth (QoQ, annualized)": "GDP 环比折年率", "FOMC minutes": "FOMC 会议纪要",
  "Economic calendar not available (no US events returned).": "没有拿到经济日历（没有返回美国事件）。",
  "No key releases found in the last 60 days of the calendar.": "近 60 天的日历里没有找到关键数据。",
  "None of the tracked events is scheduled in the next 3 weeks.": "未来 3 周没有跟踪的关键数据。",
  // flags
  "Net cash balance sheet (cash exceeds debt)": "净现金状态（现金多于债务）",
  "Negative shareholders' equity (check if caused by buybacks rather than losses)": "股东权益为负（核实是回购还是亏损造成的）",
  // data notes
  "Data route: official FMP API.": "数据来源：FMP 官方 API。",
  "HTTPS certificate verification was OFF for this run.": "本次运行关闭了 HTTPS 证书验证。",
  "Treasury, sector and industry data skipped (--no-market).": "跳过了国债、板块和行业数据（--no-market）。",
  "Source: Financial Modeling Prep. Computed figures are approximations; verify against filings before acting.":
    "数据源：Financial Modeling Prep。计算结果是近似值，做决定前请对照财报核实。",
}));

const ZONE = { safe: "安全", grey: "灰色", distress: "危险" };
const SECTORS = {
  "Basic Materials": "基础材料", "Communication Services": "通信服务", "Consumer Cyclical": "可选消费",
  "Consumer Defensive": "必需消费", "Energy": "能源", "Financial Services": "金融服务", "Healthcare": "医疗保健",
  "Industrials": "工业", "Real Estate": "房地产", "Technology": "科技", "Utilities": "公用事业",
};
const sectorZh = s => SECTORS[s] ? `${SECTORS[s]}（${s}）` : s;
// FMP economic-calendar event names (period suffix removed, lower-cased) for the key US releases.
const EVENTS = {
  "fed interest rate decision": "美联储利率决议", "fomc minutes": "FOMC 会议纪要",
  "inflation rate yoy": "CPI 同比", "core inflation rate yoy": "核心 CPI 同比",
  "inflation rate mom": "CPI 环比", "core inflation rate mom": "核心 CPI 环比",
  "cpi yoy": "CPI 同比", "core cpi yoy": "核心 CPI 同比", "cpi mom": "CPI 环比", "core cpi mom": "核心 CPI 环比",
  "producer price index yoy": "PPI 同比", "producer price index mom": "PPI 环比",
  "ppi yoy": "PPI 同比", "ppi mom": "PPI 环比", "core ppi yoy": "核心 PPI 同比", "core ppi mom": "核心 PPI 环比",
  "pce price index yoy": "PCE 物价指数同比", "pce price index mom": "PCE 物价指数环比",
  "core pce price index yoy": "核心 PCE 物价指数同比", "core pce price index mom": "核心 PCE 物价指数环比",
  "non farm payrolls": "非农就业人数", "nonfarm payrolls": "非农就业人数", "unemployment rate": "失业率",
  "gdp growth rate qoq": "GDP 环比折年率", "gdp growth rate qoq adv": "GDP 环比折年率（初值）",
  "gdp growth rate qoq 2nd est": "GDP 环比折年率（修正值）", "gdp growth rate qoq final": "GDP 环比折年率（终值）",
};
const MONTHS = { Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6, Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12 };
function eventZh(name) {
  const m = name.match(/^(.*?)(?:\s*\((\w{3}|Q[1-4])\))?$/);
  const base = EVENTS[m[1].toLowerCase().replace(/-/g, " ").replace(/\s+/g, " ").trim()];
  if (!base) return name;
  const period = m[2] ? (MONTHS[m[2]] ? `${MONTHS[m[2]]} 月` : m[2]) : "";
  return period ? `${base}（${period}）` : base;
}
const MULT = "(P\\/E|P\\/B|EV\\/EBITDA)";

// Sentence templates and fragments, applied in order to text not matched above.
const ZH_RULES = [
  // headings
  [/^Growth \((\d+)-year CAGR in last column\)$/, "增长（最后一列是 $1 年复合增速）"],
  [/^Valuation \(price (\S+), (\S+) fundamentals\)$/, "估值（股价 $1，基于 $2 财务数据）"],
  // valuation, scores
  [/^PEG \(P\/E \/ (\d+)y EPS CAGR\)$/, "PEG（P/E ÷ $1 年 EPS 复合增速）"],
  [/^\*\*Piotroski F-score (\S+): (\d+) \/ (\d+)\*\* \(7-9 strong, 0-3 weak\)$/, "**Piotroski F-score $1：$2 / $3**（7-9 强，0-3 弱）"],
  [/Altman Z ([-\d.]+) \((\w+); >2\.99 safe, <1\.81 distress\)/g, (m, z, zone) => `Altman Z ${z}（${ZONE[zone] || zone}；>2.99 安全，<1.81 危险）`],
  [/Z'' \(non-manufacturer\) ([-\d.]+) \((\w+); >2\.6 safe, <1\.1 distress\)/g, (m, z, zone) => `Z''（非制造业）${z}（${ZONE[zone] || zone}；>2.6 安全，<1.1 危险）`],
  // DCF
  [/^Starting FCF \((.+)\) is not positive; DCF not applicable\.$/, "起始 FCF（$1）不是正数，DCF 不适用。"],
  [/ ?\(average FCF of last 3 fiscal years\)/g, "（近 3 个财年 FCF 平均）"],
  [/^(\S+) \((\S+) FCF\)$/, "$1（$2 FCF）"],
  [/ ?\(historical revenue CAGR, clamped to 0-15%\)/g, "（历史营收复合增速，限制在 0-15%）"],
  [/ ?\(default \(no usable revenue history\)\)/g, "（默认值：没有可用的营收历史）"],
  [/ ?\(user input\)/g, "（手动输入）"],
  [/^fades linearly to terminal (\S+)$/, "线性降到永续增速 $1"],
  [/ ?\(fixed default; --no-market\)/g, "（固定默认值；--no-market）"],
  [/ ?\(fixed default; Treasury\/risk-premium data unavailable\)/g, "（固定默认值：缺少国债或股权风险溢价数据）"],
  [/ ?\(CAPM: 10Y Treasury (\S+) \((\S+)\) \+ beta (\S+) x US equity risk premium (\S+)( \[beta defaulted to 1\.0\])?( = (\S+?))?(, kept within (\S+))?(, rounded)?\)/g,
    (m, rf, d, b, erp, dflt, eq, raw, kept, range, rnd) =>
      `（CAPM：10 年期国债 ${rf}（${d}）+ Beta ${b} × 美国股权风险溢价 ${erp}` + (dflt ? "［缺少 Beta，按 1.0 计］" : "") +
      (eq ? ` = ${raw}` : "") + (kept ? `，限制在 ${range}` : "") + (rnd ? "，四舍五入" : "") + "）"],
  [/^\*\*Base-case value (\S+) per share vs price (\S+) -> (\S+) (upside|downside)\.\*\* Reasonable range \(discount \+\/-1pt, growth \+\/-2pt\): (\S+) - (\S+)\. Terminal value is (\S+) of the total\.$/,
    (m, v, p, mos, dir, lo, hi, tv) => `**基准情形每股价值 ${v}，股价 ${p}，${dir === "upside" ? "上涨空间" : "下跌空间"} ${mos}。** ` +
      `合理区间（折现率 ±1 个百分点、增速 ±2 个百分点）：${lo} - ${hi}。永续价值占总价值的 ${tv}。`],
  [/^\(At the previous fixed (\S+) discount rate the base case would be (\S+) per share\.\)$/, "（按原来固定的 $1 折现率，基准情形为每股 $2。）"],
  [/^\*\*Reverse DCF:\*\* today's price implies ~(\S+) FCF growth per year for 5 years \(then fading\), at a (\S+) discount rate\.$/,
    "**反向 DCF：** 按 $2 的折现率，当前股价隐含未来 5 年 FCF 每年增长约 $1（之后逐步回落）。"],
  [/^Reverse DCF: implied growth (.+)\.$/, (m, note) => `反向 DCF：隐含增速${{
    "not computable": "无法计算",
    "below -50%/yr (price is below even a shrinking-FCF value)": "低于每年 -50%（股价甚至低于 FCF 萎缩情形下的价值）",
    "above 100%/yr": "高于每年 100%"}[note] || " " + note}。`],
  // analyst, price range
  [/^(\d{4}) \(ended, not yet reported\)$/, "$1（已结束，尚未公布）"],
  [/^(\d{4}) \(current year\)$/, "$1（本财年）"], [/^(\d{4}) \(next year\)$/, "$1（下一财年）"],
  [/^FY(\d{4}) forward P\/E$/, "FY$1 前瞻 P/E"],
  [/^EPS (\S+) x forward P\/E (\S+) \/ (\S+) \/ (\S+)$/, "EPS $1 × 前瞻 P/E $2 / $3 / $4"],
  [/^daily closes (\S+) to (\S+)$/, "每日收盘价，$1 至 $2"],
  [/^\+\/-1 standard deviation of the past year's daily moves \((\S+) a year\)$/, "过去一年日涨跌幅的 ±1 个标准差（年化 $1）"],
  [/^Current price (\S+)\. Each row is the range one method gives; none of them is a forecast\.$/, "当前股价 $1。每一行是一种方法给出的区间，都不是预测。"],
  [/^3-year forward P\/E: 25th percentile (\S+), median (\S+), 75th percentile (\S+) \(10th-90th (\S+) - (\S+); (\d+) trading days, (\S+) to (\S+)\)\.$/,
    "过去 3 年的前瞻 P/E：25 分位 $1，中位数 $2，75 分位 $3（10-90 分位 $4 - $5；$6 个交易日，$7 至 $8）。"],
  [/^Today's forward P\/E: (\S+) on FY(\d{4}) EPS, at the (\d+)(?:st|nd|rd|th) percentile of that history\.$/,
    "当前前瞻 P/E：按 FY$2 EPS 算是 $1，处于这段历史的第 $3 百分位。"],
  [/^The forward P\/E history is wide \((\S+) - (\S+) between the 25th and 75th percentiles\), often after an earnings trough or a re-rating; lean on the Base column\.$/,
    "历史前瞻 P/E 分布很宽（25-75 分位 $1 - $2），通常是经历过盈利低谷或估值重估；以「基准」一列为主。"],
  [/^Analysts' (\S+) EPS \((\S+)\) differs from reported diluted EPS \((\S+)\) by (\S+): the estimates may be on an adjusted \(non-GAAP\) basis, while the P\/E history uses reported EPS, so the forward P\/E prices may run (high|low)\.$/,
    (m, fy, e, rp, gap, dir) => `分析师对 ${fy} 的 EPS（${e}）和公司公布的稀释 EPS（${rp}）相差 ${gap}：预期可能是调整后（非 GAAP）口径，而历史 P/E 用的是公布的 EPS，所以前瞻 P/E 算出的价格可能偏${dir === "high" ? "高" : "低"}。`],
  [/^Statements are in (\S+) and the price in (\S+): the P\/E rows assume a steady exchange rate and analysts' EPS in (\S+) per share; check both before relying on them\.$/,
    "财报币种是 $1，股价币种是 $2：P/E 这几行假设汇率不变、分析师 EPS 也是以 $3 计的每股数，参考前请先核实这两点。"],
  [/^Price target consensus (\S+) \(median (\S+), range (\S+)\) -> (\S+) vs price\.$/, "目标价共识 $1（中位数 $2，区间 $3），相对股价 $4。"],
  // sector & industry
  [/^(\S+) \(company\)$/, "$1（公司）"],
  [/^Industry: (.+)$/, "行业：$1"],
  [/^Sector: (.+)$/, (m, x) => "板块：" + sectorZh(x)],
  [/^negative \((\S+)\)$/, "负值（$1）"],
  [/^n\/a \(last (\S+)\)$/, "n/a（最近一次 $1）"],
  [/Company P\/E vs industry: (\S+); vs sector: (\S+)\. /, "公司 P/E 相对行业 $1，相对板块 $2。"],
  [/Industry\/sector P\/E is FMP's aggregate for the group \((\S+)-listed companies\), not a market-cap-weighted index\. /, "行业和板块 P/E 是 FMP 对这一组 $1 上市公司的汇总，不是市值加权指数。"],
  [/Industry\/sector P\/E is FMP's aggregate for the group, not a market-cap-weighted index\. /, "行业和板块 P/E 是 FMP 对这一组公司的汇总，不是市值加权指数。"],
  [/History: (.+)\.$/, (m, s) => "历史数据：" + s
    .replace(/company at its last (\d+) fiscal year-ends/, "公司取最近 $1 个财年末")
    .replace(/industry daily since (\S+) \(latest (\S+)\)/, "行业为 $1 起的每日数据（最新 $2）")
    .replace(/sector daily since (\S+) \(latest (\S+)\)/, "板块为 $1 起的每日数据（最新 $2）")
    .replace(/; /g, "；") + "。"],
  [/^Price performance to (\S+):$/, "截至 $1 的涨跌幅："],
  // rates & macro
  [/^now \((\S+)\)$/, "当前（$1）"], [/^now$/, "当前"],
  [/^1M ago(?: \((\S+)\))?$/, (m, d) => "1 个月前" + (d ? `（${d}）` : "")],
  [/^3M ago(?: \((\S+)\))?$/, (m, d) => "3 个月前" + (d ? `（${d}）` : "")],
  [/^1Y ago(?: \((\S+)\))?$/, (m, d) => "1 年前" + (d ? `（${d}）` : "")],
  [/^US equity risk premium \(FMP market-risk-premium\): (\S+)\.$/, "美国股权风险溢价（FMP market-risk-premium）：$1。"],
  [/^([+-][\d.]+)pt$/, "$1 个百分点"],
  [/^([+-][\d.]+)% MoM$/, "环比 $1%"],
  [/^(\S+) \((\d{4}-\d{2}-\d{2})\)$/, "$1（$2）"],
  // flags
  [/^Revenue fell (\S+) in (\S+)$/, "$2 营收下降 $1"],
  [/^Revenue CAGR (\S+) over (\d+) years$/, "近 $2 年营收复合增速 $1"],
  [/^Revenue shrinking: CAGR (\S+) over (\d+) years$/, "营收在萎缩：近 $2 年复合增速 $1"],
  [/^Operating margin expanded (\S+) -> (\S+) since (\S+)$/, "营业利润率自 $3 起从 $1 升到 $2"],
  [/^Operating margin compressed (\S+) -> (\S+) since (\S+)$/, "营业利润率自 $3 起从 $1 降到 $2"],
  [/^Median ROIC (\S+): high returns on capital$/, "ROIC 中位数 $1：资本回报高"],
  [/^Median ROIC (\S+): below a typical cost of capital$/, "ROIC 中位数 $1：低于一般的资本成本"],
  [/^FCF exceeds net income \(median conversion (\S+), last 3 yrs\)$/, "自由现金流高于净利润（近 3 年转化率中位数 $1）"],
  [/^Earnings weakly backed by cash \(median FCF\/NI (\S+), last 3 yrs\)$/, "利润的现金支撑偏弱（近 3 年 FCF / 净利润中位数 $1）"],
  [/^Negative free cash flow in (\S+)$/, "$1 自由现金流为负"],
  [/^High leverage: net debt \/ EBITDA (\S+)$/, "杠杆偏高：净债务 / EBITDA $1"],
  [/^Thin interest coverage: EBIT \/ interest (\S+)$/, "利息覆盖偏低：EBIT / 利息 $1"],
  [/^Current ratio (\S+) \(<1\): check short-term liquidity$/, "流动比率 $1（<1）：注意短期流动性"],
  [/^Share dilution ~(\S+) per year$/, "股本每年稀释约 $1"],
  [/^Share count shrinking ~(\S+) per year \(buybacks\)$/, "股数每年减少约 $1（回购）"],
  [/^Stock-based comp is (\S+) of revenue$/, "股权激励占营收 $1"],
  [/^Piotroski F-score (\d+)\/(\d+) \(strong\)$/, "Piotroski F-score $1/$2（强）"],
  [/^Piotroski F-score (\d+)\/(\d+) \(weak\)$/, "Piotroski F-score $1/$2（弱）"],
  [/^Altman Z (\S+) in distress zone$/, "Altman Z $1，处于危险区"],
  [new RegExp(`^${MULT} (\\S+) is above its (\\d+)-year range \\((\\S+)\\)$`), "$1 $2 高于过去 $3 年的区间（$4）"],
  [new RegExp(`^${MULT} (\\S+) is below its (\\d+)-year range \\((\\S+)\\)$`), "$1 $2 低于过去 $3 年的区间（$4）"],
  [new RegExp(`^${MULT} (\\S+) is (\\S+) below its (\\d+)-year median (\\S+)$`), "$1 $2 比过去 $4 年中位数 $5 低 $3"],
  [/^Base-case DCF value (\S+) above price$/, "DCF 基准价值比股价高 $1"],
  [/^Price is (\S+) above base-case DCF value$/, "股价比 DCF 基准价值高 $1"],
  [/^Price implies ~(\S+)\/yr FCF growth for 5 yrs vs (\S+) historical revenue CAGR$/, "股价隐含未来 5 年 FCF 每年增长约 $1，历史营收复合增速只有 $2"],
  [/^Price implies only ~(\S+)\/yr FCF growth vs (\S+) historical revenue CAGR$/, "股价只隐含 FCF 每年增长约 $1，历史营收复合增速为 $2"],
  // data notes
  [/^Data route: third-party proxy at (\S+)\. Data is not served by FMP directly; spot-check key figures against company filings\.$/,
    "数据来源：第三方代理 $1，不是 FMP 官方服务器；重要数字请对照公司财报核实。"],
  [/^API calls: (\d+) network, (\d+) from cache\.$/, "API 调用：网络 $1 次，缓存 $2 次。"],
  [/^Treasury yields as of (\S+) \(FMP treasury-rates\)\.$/, "国债收益率日期：$1（FMP treasury-rates）。"],
  [/^(Treasury yields and US equity risk premium|Treasury yields|US equity risk premium) unavailable(: DCF used the fixed default discount rate)?\.$/,
    (m, what, dcf) => "缺少" + { "Treasury yields and US equity risk premium": "国债收益率和美国股权风险溢价",
      "Treasury yields": "国债收益率", "US equity risk premium": "美国股权风险溢价" }[what] +
      (dcf ? "：DCF 用了固定默认折现率。" : "。")],
  [/^Skipped \(not in your FMP plan\): (.+)$/, "已跳过（套餐不含）：$1"],
  [/^Error: (.+)$/, "错误：$1"],
];

function zh(text) {
  const s = String(text ?? "");
  const key = s.trim();
  if (ZH_EXACT.has(key)) return ZH_EXACT.get(key);
  const head = key.match(/^(\d+)\.\s+(.+)$/);  // numbered section heading
  if (head) return `${head[1]}. ${zh(head[2])}`;
  const ev = eventZh(key);
  if (ev !== key) return ev;
  let out = key;
  for (const [re, rep] of ZH_RULES) out = out.replace(re, rep);
  return out;
}
