// Chinese / English text for the local UI (ui/index.html).
//
// UI: labels of the page itself, by key, in both languages.
// zh(): translates the English report (scripts/facts_report.py, printed by analyze.py) into Chinese for display.
// It only changes how the page reads; the numbers, the CLI report and the "full text report"
// view stay as facts_report.py wrote them. Text it does not recognise (FMP event names, company
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
    err_contract: c => `这个页面只显示 fa-2 格式的基本面数据（基本面 skill v2.0），收到的数据${c ? `是 ${c}` : "没有 contract 字段"}。`,
    notice_proxy: host => `数据来自 <b>FMP 第三方代理接口</b>（${host}），不是 FMP 官方服务器。重要数字请对照公司财报核实。`,
    notice_no_route: "这份数据没有记录是从 FMP 官方接口还是第三方代理取得的。重要数字请对照公司财报核实。",
    as_of: "截至", mcap: "市值", px_time: s => `报价 ${s} 美东`,
    s_pe: "P/E", s_ev: "EV/EBITDA", s_fcfy: "FCF 收益率", s_roic: "ROIC", s_cagr: "营收 CAGR", s_pio: "Piotroski",
    s_fpe: "前瞻 P/E（未来 12 个月）", s_dcf: "DCF 每股价值",
    // why a tile shows n/a (or a value that is not positive)
    na_kind: "对这类公司没有意义", na_loss: "盈利不为正", na_short: "至少需要 2 个财年",
    na_no_est: "需要本财年和下一财年的分析师预期", na_ntm_eps: "未来 12 个月 EPS 不为正或缺失",
    na_dcf_negative: "不为正：净债务超过现金流折现值", na_dcf_financial: "金融类公司不计算",
    na_dcf_fcf: "起始 FCF 不为正", na_dcf_inputs: "折现率必须高于永续增速",
    no_report: "没有文字报告。", full_report: "完整文字报告（英文原文）",
    // the price chart and the price ranges: only the page shows them (not part of fa-2.0 or the report)
    chart_title: "股价走势", chart_daily: "日 K 线", chart_weekly: "周 K 线", chart_close: "每日收盘价", chart_aria: "股价 K 线图",
    p_3m: "3 个月", p_6m: "6 个月", p_ytd: "年初至今", p_1y: "1 年",
    k_open: "开", k_high: "高", k_low: "低", k_close: "收", k_vol: "量",
    no_ohlc: "数据源没有返回开盘、最高、最低价，这里只画收盘价。", no_prices: "没有价格数据。",
    month: (y, m) => m === 1 ? `${y}` : `${m}月`,
    s_mos: "DCF vs 股价", s_range: "前瞻 P/E 区间",
    s_range_eps: ys => "EPS：" + ys.map(([fy, w]) => `FY${fy}` + (w != null ? ` ${w}%` : "")).join(" + "),
    rc_tab: "股价区间", rc_title: "各方法的股价区间",
    rc_intro: "每一行是一种方法给出的股价区间，都不是预测。只在这个网页上根据 fa-2.0 文档和过去一年的日线计算，不属于 fa-2.0 和报告。",
    rc_note: "圆点 = 中值（基准或现价）；波动率行：深色 = 68% 区间，浅色 = 95% 区间；竖线 = 当前股价。鼠标移到某一行可看具体数字。",
    rc_week52: "交易区间", rc_fwd_pe: "前瞻 P/E", rc_fwd_ev: "前瞻 EV/EBITDA", rc_dcf: "DCF", rc_volatility: "波动率",
    rc_past: "过去 52 周", rc_now: "现在", rc_12m: "12 个月后", rc_fy_end: fy => `FY${fy} 末`,
    rc_price: "现价", rc_low: "低", rc_mid: "中值", rc_high: "高", rc_vs: "中值 vs 现价",
    rc_method: "方法", rc_when: "时间", rc_basis: "依据",
    rb_ntm: "未来 12 个月", rb_fy_est: fy => `FY${fy} 预期`,
    rb_fwd_pe: (eps, src, m) => `EPS ${eps}（${src}）× P/E ${m}`,
    rb_fwd_ev: (e, src, m) => `EBITDA ${e}（${src}）× EV/EBITDA ${m}，减去净债务和少数股东权益`,
    rb_dcf: (r, g) => `折现率 ${r} ±1 个百分点，增速 ${g} ±2 个百分点`,
    rb_volatility: (sd, lo, hi) => `现价 ±1 个标准差，过去一年的年化波动率 ${sd}；95%：${lo} – ${hi}`,
    rb_week52: (a, b) => `${a} 至 ${b} 每日收盘价的最低 / 最高`,
  },
  en: {
    title: "FMP Fundamental Analysis",
    lang_button: "中文", lang_hint: "切换到中文",
    f_symbol: "Ticker", f_peers: "Peers (optional)", ph_peers: "MSFT,GOOGL or none",
    f_discount: "Discount rate %", ph_auto: "Auto", discount_tip: "Blank = 10Y Treasury + beta × equity risk premium (7%-13%)",
    f_growth: "Growth yrs 1-5 %", f_terminal: "Terminal growth %", f_fcf: "Starting FCF", opt_latest: "Latest", opt_avg3: "3-yr average",
    c_macro: "Macro backdrop", c_refresh: "Ignore cache", go: "Analyze",
    loading: sym => `Analyzing ${sym}… (first run takes about 10-30 s; faster once cached)`,
    err_contract: c => `This page shows fa-2 documents only (fundamental skill v2.0); the data it received ${c ? `is ${c}` : "has no contract field"}.`,
    notice_proxy: host => `Data comes from a <b>third-party FMP proxy</b> (${host}), not FMP's official server. Verify key figures against company filings.`,
    notice_no_route: "This data does not say whether it came from FMP's official API or a third-party proxy. Verify key figures against company filings.",
    as_of: "as of", mcap: "Mkt cap", px_time: s => `Quote ${s} ET`,
    s_pe: "P/E", s_ev: "EV/EBITDA", s_fcfy: "FCF yield", s_roic: "ROIC", s_cagr: "Revenue CAGR", s_pio: "Piotroski",
    s_fpe: "Forward P/E (next 12 months)", s_dcf: "DCF value / share",
    na_kind: "not meaningful for this type of company", na_loss: "earnings not positive", na_short: "needs at least 2 fiscal years",
    na_no_est: "needs analyst estimates for the current and next fiscal years", na_ntm_eps: "next-12-month EPS not positive or missing",
    na_dcf_negative: "not positive: net debt exceeds the discounted cash flows", na_dcf_financial: "not computed for a financial company",
    na_dcf_fcf: "starting FCF not positive", na_dcf_inputs: "discount rate must exceed terminal growth",
    no_report: "No report text.", full_report: "Full text report",
    chart_title: "Share price", chart_daily: "Daily candles", chart_weekly: "Weekly candles", chart_close: "Daily closes", chart_aria: "Share price candlestick chart",
    p_3m: "3M", p_6m: "6M", p_ytd: "YTD", p_1y: "1Y",
    k_open: "O", k_high: "H", k_low: "L", k_close: "C", k_vol: "Vol",
    no_ohlc: "The data source returned no open, high or low prices, so this shows closing prices only.", no_prices: "No price data.",
    month: (y, m) => m === 1 ? `${y}` : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1],
    s_mos: "DCF vs price", s_range: "Forward P/E range",
    s_range_eps: ys => "EPS: " + ys.map(([fy, w]) => (w != null ? `${w}% ` : "") + `FY${fy}`).join(" + "),
    rc_tab: "Price range", rc_title: "Price range by method",
    rc_intro: "Each row is the range one method gives for the share price; none of them is a forecast. Worked out on this page only, from the fa-2.0 document and the past year's daily closes: not part of fa-2.0 or the report.",
    rc_note: "Dot = mid value (base case or current price); volatility rows: dark = 68% range, light = 95% range; vertical line = current price. Hover a row for its numbers.",
    rc_week52: "Trading range", rc_fwd_pe: "Forward P/E", rc_fwd_ev: "Forward EV/EBITDA", rc_dcf: "DCF", rc_volatility: "Volatility",
    rc_past: "Past 52 weeks", rc_now: "Now", rc_12m: "In 12 months", rc_fy_end: fy => `FY${fy} end`,
    rc_price: "Price", rc_low: "Low", rc_mid: "Mid", rc_high: "High", rc_vs: "Mid vs price",
    rc_method: "Method", rc_when: "When", rc_basis: "Basis",
    rb_ntm: "next 12 months", rb_fy_est: fy => `FY${fy} est.`,
    rb_fwd_pe: (eps, src, m) => `EPS ${eps} (${src}) x P/E ${m}`,
    rb_fwd_ev: (e, src, m) => `EBITDA ${e} (${src}) x EV/EBITDA ${m}, less net debt and minority interest`,
    rb_dcf: (r, g) => `discount rate ${r} +/-1pt, growth ${g} +/-2pt`,
    rb_volatility: (sd, lo, hi) => `price +/-1 sd at the past year's ${sd} a year; 95%: ${lo} – ${hi}`,
    rb_week52: (a, b) => `lowest / highest daily close, ${a} to ${b}`,
  },
};

// Whole cells, labels and headings (matched after trimming).
const ZH_EXACT = new Map(Object.entries({
  // section headings (the "N. " prefix is handled separately)
  "Growth": "增长",
  "Profitability & returns": "盈利能力与回报",
  "Balance sheet & liquidity": "资产负债与流动性",
  "Cash flow quality & capital allocation": "现金流质量与资本配置",
  "Valuation": "估值",
  "Forward multiples": "前瞻倍数",
  "Industry & sector P/E": "行业与板块 P/E",
  "Quality scores": "质量评分",
  "Analyst consensus": "分析师预期",
  "Peer comparison": "同行对比",
  "Rates & macro backdrop": "利率与宏观背景",
  "Data notes": "数据说明",
  "Treasury yields": "国债收益率",
  "Policy rate, jobs and prices (economic-indicators, latest two readings)": "政策利率、就业与物价（经济指标，最近两期）",
  "Latest key US releases (economic calendar, last 60 days)": "美国关键数据最新公布值（经济日历，近 60 天）",
  "Next key US events (next 3 weeks)": "接下来的美国关键数据（未来 3 周）",
  "Price performance": "股价表现",
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
  "Based on": "依据", "Figure used": "所用数值", "EBITDA est.": "EBITDA 预期", "r \\ g": "折现率 \\ 增速",
  "Item": "项目", "Analysts": "分析师", "Reported": "公布值", "Gap": "差距",
  // growth / profitability / balance sheet / cash flow rows
  "Last column: compound annual growth (CAGR), which needs at least 2 fiscal years.":
    "最后一列是复合增速（CAGR），至少需要 2 个财年的数据。",
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
  "Altman Z: not available (needs working capital, retained earnings, EBIT, revenue, total assets and total liabilities).":
    "Altman Z：无法计算（需要营运资本、留存收益、EBIT、营收、总资产和总负债）。",
  "(Altman Z was built for industrial companies and is not meaningful for this type of company.)":
    "（Altman Z 是为工业企业设计的，对这类公司没有意义。）",
  // DCF
  "FCF-based, 10 years + terminal value.": "基于自由现金流，10 年 + 永续价值。",
  "Starting FCF": "起始 FCF", "Growth yrs 1-5": "第 1-5 年增速", "Growth yrs 6-10": "第 6-10 年增速",
  "Discount rate": "折现率", "Net debt deducted": "扣除的净债务", "Shares": "股数",
  "Value per share (rows = discount rate, columns = growth yrs 1-5):": "每股价值（行 = 折现率，列 = 第 1-5 年增速）：",
  "Financial-sector company: an FCF-based DCF is not meaningful, so none is computed.":
    "金融类公司：基于自由现金流的 DCF 没有意义，所以不计算。",
  "Starting FCF is not positive; DCF not applicable.": "起始 FCF 不是正数，DCF 不适用。",
  "DCF inputs invalid (discount rate must exceed terminal growth).": "DCF 参数无效（折现率必须高于永续增速）。",
  "DCF not available.": "无法计算 DCF。",
  "Reverse DCF: the implied growth is below -50% a year, outside the range searched.":
    "反向 DCF：隐含增速低于每年 -50%，超出了搜索范围。",
  "Reverse DCF: the implied growth is above 100% a year, outside the range searched.":
    "反向 DCF：隐含增速高于每年 100%，超出了搜索范围。",
  "Reverse DCF: not computable.": "反向 DCF：无法计算。",
  // forward multiples
  "Needs analyst estimates for the current and next fiscal years (not on this FMP plan or none published); forward multiples not available.":
    "需要本财年和下一财年的分析师预期（套餐不含或没有发布），算不了前瞻倍数。",
  "Not enough positive-earnings price history for a distribution of the forward multiples (needs about 6 months).":
    "盈利为正的历史股价数据不够（约需 6 个月），算不了前瞻倍数的分布。",
  "Forward P/E each day = close / next-12-month EPS: the fiscal year in progress and the one after it, weighted by the time left in the year (reported EPS once a year is reported, the analysts' average otherwise). This is how published forward P/E histories are built; a single fiscal year's EPS would make the multiple jump at every year end for a fast grower and skew the range.":
    "每天的前瞻 P/E = 当天收盘价 ÷ 未来 12 个月 EPS：当天所在财年和下一财年按该财年剩余时间加权（已公布的财年用实际数，其余用分析师平均预期）。市面上的前瞻 P/E 历史都是这么算的；如果只用单个财年的 EPS，高增长公司的倍数会在每个财年末跳一下，把区间拉偏。",
  "n/a = the EPS or EBITDA used is zero or negative (or missing), so there is no multiple.":
    "n/a = 所用的 EPS 或 EBITDA 为零或负数（或缺失），所以没有倍数。",
  "EV each day = price x shares + net debt + minority interest of the latest reported fiscal year; next-12-month EBITDA as for EPS above.":
    "每天的 EV = 股价 × 股数 + 净债务 + 少数股东权益（都用最近一个已公布财年的数）；未来 12 个月 EBITDA 的算法和上面的 EPS 一样。",
  // analyst / peers
  "No analyst estimates (not on this FMP plan, or none published).": "没有分析师预期（套餐不含，或没有发布）。",
  "The analysts use another revenue basis (often net instead of gross revenue), so the first year's revenue growth above is measured from their figure.":
    "分析师用的营收口径不同（通常是净额而不是总额），所以上表第一年的营收增速是从他们的数字算起的。",
  "A gap in EPS or EBITDA usually means the estimates are on an adjusted (non-GAAP) basis, for example before stock-based compensation.":
    "EPS 或 EBITDA 有差距，通常是因为预期用的是调整后（非 GAAP）口径，比如不扣股权激励。",
  "Each company's last fiscal year, same method for all (* = this company).": "各公司都用最近一个财年，算法相同（* = 本公司）。",
  "Peer median": "同行中位数",
  "no data (plan restriction or unknown ticker)": "无数据（套餐限制或代码有误）",
  // sector & industry
  "No industry or sector data: market data was skipped (--no-market).": "没有行业和板块数据：跳过了市场数据（--no-market）。",
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
  // data notes
  "Data route: official FMP API.": "数据来源：FMP 官方 API。",
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
// Company types other than "general" and the measures that do not apply to them, as facts_report.py names them.
const KIND_ZH = {
  "Financial company": "金融公司",
  "Fee-based financial company (exchange, data provider or insurance broker), analysed like other companies; clearing margin and client money sit on its balance sheet":
    "收费型金融公司（交易所、数据服务商或保险经纪），按普通公司分析；清算保证金和客户资金记在它的资产负债表上",
  "REIT; net income is after property depreciation": "REIT；净利润已扣除物业折旧",
  "Regulated utility, capital-heavy": "受监管的公用事业公司，资本密集",
};
const MEASURE_ZH = { "gross margin": "毛利率", "EV / sales": "EV / 营收", "free cash flow": "自由现金流", "current ratio": "流动比率" };
// Why a multiple history is not comparable (facts_report.py HISTORY_PROBLEMS).
const HISTORY_ZH = {
  "The share counts in the statements do not match today's share basis (for example a stock split the statements do not reflect, an ADR ratio or several share classes)":
    "财报里的股数和现在的股本口径对不上（比如财报没有反映拆股、ADR 换股比例或多类股票）",
  "The price history has a one-day fall of more than 50% or rise of more than 100% (possibly a stock split the prices do not reflect)":
    "股价历史里有单日跌超过 50% 或涨超过 100% 的情况（可能是股价没有按拆股调整）",
};
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
  if (!m) return name;  // "." stops at a line break inside the text (\r, U+2028, U+2029): not an event name
  const base = EVENTS[m[1].toLowerCase().replace(/-/g, " ").replace(/\s+/g, " ").trim()];
  if (!base) return name;
  const period = m[2] ? (MONTHS[m[2]] ? `${MONTHS[m[2]]} 月` : m[2]) : "";
  return period ? `${base}（${period}）` : base;
}

// Sentence templates and fragments, applied in order to text not matched above.
const ZH_RULES = [
  // header, growth, valuation
  [/^(.+?) \/ (.+) \| ([^|]+) \| Price (\S+(?: [A-Z]{3})?) \| Market cap (\S+) \| Beta (\S+)$/,
    (m, sector, industry, ex, px, cap, beta) => `${sectorZh(sector)} / ${industry} | ${ex} | 股价 ${px} | 市值 ${cap} | Beta ${beta}`],
  [/^Data basis: annual (\S+)(?: in (\S+))?(?: \+ TTM to (\S+)| \(TTM unavailable: using last fiscal year\))\. Valuation uses (\S+) figures\. As of (\S+)\.$/,
    (m, years, ccy, ttm, basis, asOf) => `数据口径：${years} 年报` + (ccy ? `，币种 ${ccy}` : "") +
      (ttm ? `，另加截至 ${ttm} 的 TTM` : "（没有 TTM 数据，用最近一个财年）") + `。估值用 ${basis} 的数据。数据截至 ${asOf}。`],
  [/^\*\*Company type:\*\* (.+?)\.(?: Not meaningful for this type of company: (.+)\.)?$/,
    (m, kind, names) => `**公司类型：** ${KIND_ZH[kind] || kind}。` +
      (names ? `对这类公司没有意义的指标：${names.split(", ").map(x => MEASURE_ZH[x] || x).join("、")}。` : "")],
  [/^Last column: compound annual growth \(CAGR\) over (\d+) years?, (\S+) to (\S+)\.$/, "最后一列是 $2 至 $3 的 $1 年复合增速（CAGR）。"],
  [/^Price (\S+(?: [A-Z]{3})?), (\S+) fundamentals\.$/, "股价 $1，基于 $2 的财务数据。"],
  [/^(.+), so the (fiscal-year-end|multiple) history is not comparable( and no distribution is shown)?\.$/,
    (m, why, which, none) => HISTORY_ZH[why] ? `${HISTORY_ZH[why]}，${which === "multiple" ? "" : "财年末的"}历史倍数没法比` +
      (none ? "，所以不显示分布" : "") + "。" : m],
  // quality scores
  [/^\*\*Piotroski F-score (\S+): (\d+) \/ (\d+)\*\* \(tests passed \/ tests with data\)$/,
    "**Piotroski F-score $1：$2 / $3**（通过的检验项 / 有数据的检验项）"],
  [/Altman Z ([-\d.]+) \((\w+); >2\.99 safe, <1\.81 distress\)/g, (m, z, zone) => `Altman Z ${z}（${ZONE[zone] || zone}；>2.99 安全，<1.81 危险）`],
  [/Z'' \(non-manufacturer\) ([-\d.]+) \((\w+); >2\.6 safe, <1\.1 distress\)/g, (m, z, zone) => `Z''（非制造业）${z}（${ZONE[zone] || zone}；>2.6 安全，<1.1 危险）`],
  // DCF
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
  [/^\*\*Base-case value (\S+) per share\.\*\* Range \(discount rate \+\/-1pt, growth \+\/-2pt\): (\S+) - (\S+)\. Terminal value is (\S+) of the total\.$/,
    "**基准情形每股价值 $1。** 区间（折现率 ±1 个百分点、增速 ±2 个百分点）：$2 - $3。永续价值占总价值的 $4。"],
  [/^\*\*Base-case value (\S+) per share is not positive: net debt exceeds the discounted cash flows\.\*\* Range \(discount rate \+\/-1pt, growth \+\/-2pt\): (\S+) - (\S+)\. Terminal value is (\S+) of the total\.$/,
    "**基准情形每股价值 $1，不是正数：净债务超过了现金流折现值。** 区间（折现率 ±1 个百分点、增速 ±2 个百分点）：$2 - $3。永续价值占总价值的 $4。"],
  [/^\*\*Reverse DCF:\*\* today's price implies ~(\S+) FCF growth per year for 5 years \(then fading\), at a (\S+) discount rate\.$/,
    "**反向 DCF：** 按 $2 的折现率，当前股价隐含未来 5 年 FCF 每年增长约 $1（之后逐步回落）。"],
  // analyst consensus, forward multiples
  [/^(\d{4}) \(ended, not yet reported\)$/, "$1（已结束，尚未公布）"],
  [/^Analysts' figures for (\S+), the last reported year, against the reported ones:$/, "分析师对最近一个已公布财年 $1 的预期与公布值对比："],
  [/^FY(\d{4}) EPS \(consensus\)$/, "FY$1 EPS（一致预期）"],
  [/^next-12-month (EPS|EBITDA)(?: \((\d+)% FY(\d{4}) \+ (\d+)% FY(\d{4})\))?$/,
    (m, k, a, fyA, b, fyB) => `未来 12 个月 ${k}` + (a ? `（${a}% FY${fyA} + ${b}% FY${fyB}）` : "")],
  [/^No (\d+)-year distribution: it needs analyst estimates for the current and next fiscal years\.$/,
    "没有过去 $1 年的分布：需要本财年和下一财年的分析师预期。"],
  [/^(\d+)-year forward (P\/E|EV\/EBITDA) on next-12-month (EPS|EBITDA): 25th percentile (\S+), median (\S+), 75th percentile (\S+) \(10th-90th (\S+) - (\S+); (\d+) trading days, (\S+) to (\S+)\)\.$/,
    "过去 $1 年按未来 12 个月 $3 算的前瞻 $2：25 分位 $4，中位数 $5，75 分位 $6（10-90 分位 $7 - $8；$9 个交易日，$10 至 $11）。"],
  [/^Today's forward (P\/E|EV\/EBITDA): (\S+), at the (\d+)(?:st|nd|rd|th) percentile of that history\.$/,
    "当前前瞻 $1：$2，处于这段历史的第 $3 百分位。"],
  [/^Today's forward (P\/E|EV\/EBITDA): (\S+), (below|above) every day of that history\.$/,
    (m, k, v, dir) => `当前前瞻 ${k}：${v}，${dir === "below" ? "低于" : "高于"}这段历史里的每一天。`],
  [/^Today's next-12-month (EPS|EBITDA) is not positive, so there is no forward (P\/E|EV\/EBITDA) for today\.$/,
    "今天的未来 12 个月 $1 不是正数，所以今天没有前瞻 $2。"],
  [/^No forward (P\/E|EV\/EBITDA) distribution: EV multiples do not apply to a financial company\.$/,
    "没有前瞻 $1 分布：EV 类倍数不适用于金融公司。"],
  [/^No forward (P\/E|EV\/EBITDA) distribution: no net debt or share count for the enterprise value\.$/,
    "没有前瞻 $1 分布：缺少计算企业价值所需的净债务或股数。"],
  [/^No forward (P\/E|EV\/EBITDA) distribution: next-12-month EBITDA is not positive\.$/,
    "没有前瞻 $1 分布：未来 12 个月 EBITDA 不是正数。"],
  [/^Not enough positive-(earnings|EBITDA) price history for a forward (P\/E|EV\/EBITDA) distribution \(needs about 6 months\)\.$/,
    (m, base, k) => `${base === "earnings" ? "盈利" : "EBITDA "}为正的历史股价数据不够（约需 6 个月），算不了前瞻 ${k} 分布。`],
  [/^Analysts' (\S+) EPS \((\S+)\) differs from reported diluted EPS \((\S+)\) by (\S+): the estimates may be on an adjusted \(non-GAAP\) basis, while the P\/E history uses reported EPS for reported years\.$/,
    "分析师对 $1 的 EPS（$2）和公司公布的稀释 EPS（$3）相差 $4：预期可能是调整后（非 GAAP）口径，而历史 P/E 在已公布的财年用的是公布的 EPS。"],
  [/^Analysts' (\S+) EBITDA \((\S+)\) differs from reported EBITDA \((\S+)\) by (\S+): the estimates may be on an adjusted basis \(for example before stock-based compensation\), while the EV\/EBITDA history uses reported EBITDA for reported years\.$/,
    "分析师对 $1 的 EBITDA（$2）和公司公布的 EBITDA（$3）相差 $4：预期可能是调整后口径（比如不扣股权激励），而历史 EV/EBITDA 在已公布的财年用的是公布的 EBITDA。"],
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
  // data notes
  [/^Data route: third-party proxy at (\S+)\. Data is not served by FMP directly; spot-check key figures against company filings\.$/,
    "数据来源：第三方代理 $1，不是 FMP 官方服务器；重要数字请对照公司财报核实。"],
  [/^API calls: (\d+) network, (\d+) from cache\.$/, "API 调用：网络 $1 次，缓存 $2 次。"],
  [/^Price from the latest quote at (\S+ \S+) New York time\.$/, "股价来自最新报价，美东时间 $1。"],
  [/^Price from the latest quote\.$/, "股价来自最新报价。"],
  [/^Price from the company profile, which is cached for up to a day \(no current quote\)\.$/, "股价来自公司资料，最多缓存一天（没有拿到当前报价）。"],
  [/^Treasury yields as of (\S+) \(FMP treasury-rates\)\.$/, "国债收益率日期：$1（FMP treasury-rates）。"],
  [/^(Treasury yields and US equity risk premium|Treasury yields|US equity risk premium) unavailable(: DCF used the fixed default discount rate)?\.$/,
    (m, what, dcf) => "缺少" + { "Treasury yields and US equity risk premium": "国债收益率和美国股权风险溢价",
      "Treasury yields": "国债收益率", "US equity risk premium": "美国股权风险溢价" }[what] +
      (dcf ? "：DCF 用了固定默认折现率。" : "。")],
  [/^Statements are in (\S+) and the price in (\S+): the multiples and yields mix the two currencies, and the DCF value per share is in (\S+)\.$/,
    "财报币种是 $1，股价币种是 $2：倍数和收益率混用了两种币种，DCF 的每股价值以 $3 计。"],
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
