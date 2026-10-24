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
    f_growth: "1-5年增速 %", f_terminal: "永续增速 %", f_fcf: "起始 FCF",
    f_iv: "隐含波动率 %", ph_realized: "历史", iv_tip: "期权隐含波动率（年化），例如 45；留空 = 用过去一年的实际波动率", opt_latest: "最新", opt_avg3: "3年平均",
    c_macro: "宏观背景", c_refresh: "忽略缓存", go: "分析",
    loading: sym => `正在分析 ${sym}…（首次约 10-30 秒，之后有缓存会更快）`,
    notice_proxy: base => `数据来自 <b>FMP 第三方代理接口</b>（${base}），不是 FMP 官方服务器。重要数字请对照公司财报核实。`,
    notice_tls: " 本次 HTTPS 证书验证已关闭。",
    as_of: "截至", mcap: "市值", px_time: s => `报价 ${s} 美东`,
    s_pe: "P/E", s_ev: "EV/EBITDA", s_fcfy: "FCF 收益率", s_roic: "ROIC", s_cagr: "营收 CAGR", s_pio: "Piotroski",
    s_dcf: "DCF 每股价值", s_mos: "DCF vs 股价", s_range: "前瞻 P/E 区间",
    rc_title: "各方法的股价区间",
    rc_fwd_pe: "前瞻 P/E", rc_fwd_ev: "前瞻 EV/EBITDA", rc_dcf: "DCF", rc_targets: "分析师目标价", rc_week52: "交易区间", rc_volatility: "波动率",
    rc_past: "过去 52 周", rc_now: "现在", rc_12m: "12 个月后", rc_fy_end: fy => `FY${fy} 末`,
    rc_price: "现价", rc_low: "低", rc_mid: "中值", rc_high: "高", rc_vs: "中值 vs 现价",
    rc_note: "圆点 = 中值（基准、共识价或现价）；波动率行：深色 = 68% 区间，浅色 = 95% 区间；竖线 = 当前股价。鼠标移到某一行可看具体数字。",
    chart_title: "股价走势", chart_daily: "日 K 线", chart_weekly: "周 K 线", chart_close: "每日收盘价", chart_aria: "股价 K 线图",
    p_3m: "3 个月", p_6m: "6 个月", p_ytd: "年初至今", p_1y: "1 年",
    k_open: "开", k_high: "高", k_low: "低", k_close: "收", k_vol: "量",
    no_ohlc: "数据源没有返回开盘、最高、最低价，这里只画收盘价。", no_prices: "没有价格数据。",
    month: (y, m) => m === 1 ? `${y}` : `${m}月`,
    flags_title: "自动提示（需进一步核实，不是结论）", pos: "优点", neg: "风险", none: "无",
    full_report: "完整文字报告（英文原文）",
  },
  en: {
    title: "FMP Fundamental Analysis",
    lang_button: "中文", lang_hint: "切换到中文",
    f_symbol: "Ticker", f_peers: "Peers (optional)", ph_peers: "MSFT,GOOGL or none",
    f_discount: "Discount rate %", ph_auto: "Auto", discount_tip: "Blank = 10Y Treasury + beta × equity risk premium (7%-13%)",
    f_growth: "Growth yrs 1-5 %", f_terminal: "Terminal growth %", f_fcf: "Starting FCF",
    f_iv: "Implied vol %", ph_realized: "Realized", iv_tip: "Options implied volatility (annual), e.g. 45; blank = the past year's realized volatility", opt_latest: "Latest", opt_avg3: "3-yr average",
    c_macro: "Macro backdrop", c_refresh: "Ignore cache", go: "Analyze",
    loading: sym => `Analyzing ${sym}… (first run takes about 10-30 s; faster once cached)`,
    notice_proxy: base => `Data comes from a <b>third-party FMP proxy</b> (${base}), not FMP's official server. Verify key figures against company filings.`,
    notice_tls: " HTTPS certificate verification was off for this run.",
    as_of: "as of", mcap: "Mkt cap", px_time: s => `Quote ${s} ET`,
    s_pe: "P/E", s_ev: "EV/EBITDA", s_fcfy: "FCF yield", s_roic: "ROIC", s_cagr: "Revenue CAGR", s_pio: "Piotroski",
    s_dcf: "DCF value / share", s_mos: "DCF vs price", s_range: "Forward P/E range",
    rc_title: "Price range by method",
    rc_fwd_pe: "Forward P/E", rc_fwd_ev: "Forward EV/EBITDA", rc_dcf: "DCF", rc_targets: "Analyst targets", rc_week52: "Trading range", rc_volatility: "Volatility",
    rc_past: "Past 52 weeks", rc_now: "Now", rc_12m: "In 12 months", rc_fy_end: fy => `FY${fy} end`,
    rc_price: "Price", rc_low: "Low", rc_mid: "Mid", rc_high: "High", rc_vs: "Mid vs price",
    rc_note: "Dot = mid value (base case, consensus or current price); volatility rows: dark = 68% range, light = 95% range; vertical line = current price. Hover a row for its numbers.",
    chart_title: "Share price", chart_daily: "Daily candles", chart_weekly: "Weekly candles", chart_close: "Daily closes", chart_aria: "Share price candlestick chart",
    p_3m: "3M", p_6m: "6M", p_ytd: "YTD", p_1y: "1Y",
    k_open: "O", k_high: "H", k_low: "L", k_close: "C", k_vol: "Vol",
    no_ohlc: "The data source returned no open, high or low prices, so this shows closing prices only.", no_prices: "No price data.",
    month: (y, m) => m === 1 ? `${y}` : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1],
    flags_title: "Automated flags (prompts for investigation, not conclusions)", pos: "Positives", neg: "Concerns", none: "None",
    full_report: "Full text report",
  },
};

// The fundamental score card (scripts/score.py): pillar, indicator, note and rule texts by key.
const SCORE_UI = {
  zh: {
    sc_title: "基本面打分", sc_rules: v => `规则 v${v}`, sc_conf: "置信度", conf_high: "高", conf_medium: "中", conf_low: "低",
    sc_formula: "总分 = 35% × 估值 + 25% × 质量 + 20% × 成长 + 20% × 财务健康；每一项都在 −2 到 +2 之间。",
    sc_hint: "点开每个大项可以看到下面每个指标的数值、打分区间、得分和权重。",
    sc_pillar: "大项", sc_weight: "权重", sc_score: "得分", sc_contrib: "对总分贡献", sc_cov: "数据覆盖",
    sc_ind: "指标", sc_value: "数值", sc_rule: "打分区间", sc_icontrib: "对大项贡献", sc_icontrib_s: "贡献",
    sc_missing: "缺数据，按 0 分计", sc_na: "不适用", sc_raw: (raw, cap) => `封顶前 ${raw}，封顶后最高 ${cap}`,
    sc_caps: "封顶规则", sc_conflicts: "需要留意的矛盾", sc_how: "怎么算的", sc_range: "合理价值区间",
    sc_range_fwd_pe: "前瞻 P/E，按 3 年倍数的 25 分位 / 中位 / 75 分位", sc_range_dcf: "DCF 区间",
    sc_range_vs: v => `中值相对现价 ${v}`, sc_na_group: n => n,
    p_valuation: "估值", p_quality: "质量", p_growth: "成长", p_health: "财务健康",
    lbl_Bullish: "看多", "lbl_Moderately bullish": "偏多", lbl_Neutral: "中性", "lbl_Moderately bearish": "偏空", lbl_Bearish: "看空",
    ind_fwd_pe_position: "前瞻 P/E 在 3 年区间的位置", ind_fwd_ev_position: "前瞻 EV/EBITDA 在 3 年区间的位置",
    ind_pb_vs_history: "P/B 相对历年中位数", ind_implied_growth_gap: "反向 DCF：股价隐含增速 − 预期增速",
    ind_dcf_margin: "DCF 价值相对股价", ind_vs_industry: "P/E 相对行业",
    ind_roic_level: "ROIC（历年中位数）", ind_roe_level: "ROE（历年中位数）", ind_roic_trend: "ROIC 3 年变化",
    ind_roe_trend: "ROE 3 年变化", ind_op_margin_trend: "营业利润率 3 年变化", ind_gross_margin_stability: "毛利率波动（标准差）",
    ind_fcf_conversion: "FCF / 净利润（近 3 年中位数）", ind_sbc_burden: "股权激励占营收",
    ind_revenue_cagr: "营收复合增速", ind_revenue_recent: "最近一年营收增速", ind_revenue_forward: "分析师预期营收增速",
    ind_eps_forward: "分析师预期下一财年 EPS 增速", ind_net_debt_ebitda: "净债务 / EBITDA",
    ind_interest_coverage: "利息覆盖倍数（EBIT / 利息）", ind_interest_coverage_ebitda: "利息覆盖倍数（EBITDA / 利息）", ind_altman: "Altman Z 区间", ind_piotroski: "Piotroski F-score（满分 9）",
    ind_current_ratio: "流动比率", ind_dilution: "股本年均变化", ind_equity_to_assets: "股东权益 / 总资产",
    note_trailing_history: "没有前瞻区间，改用当前倍数相对历年财年末中位数",
    note_adjusted_basis: "分析师数字和公布数字口径不同（通常是调整后），前瞻区间会混用两种口径，改用当前倍数相对历年财年末中位数",
    note_adjusted_basis_short: "分析师数字和公布数字口径不同（通常是调整后），而且不到 3 个财年，没法改用历史倍数",
    note_clipped: "两端各按 ±50% 截断，回报率很高时的变化只算噪音", note_few_tests: "9 项测试里有数据的不到 7 项",
    note_growth_slowdown: "封顶 +1：预期 EPS 增速不到过去的一半，倍数未必回到中位",
    note_historical_growth: "没有分析师预期，改和历史营收复合增速比", note_historical_eps: "没有可用的分析师 EPS 预期，改用历史 EPS 复合增速",
    note_sector_pe: "没有行业 P/E，改和板块比", note_implied_below_range: "股价隐含 FCF 每年萎缩超过 50%",
    note_implied_above_range: "股价隐含 FCF 每年增长超过 100%", note_negative_fcf: "最近一个财年自由现金流为负",
    note_net_cash: "净现金", note_reit: "REIT 用更宽的杠杆区间", note_utility: "公用事业用更宽的区间：受监管，杠杆天然更高",
    note_ebitda_coverage: "REIT 的 EBIT 扣掉了大量房产折旧", note_ebitda_not_positive: "EBITDA 不为正",
    note_no_interest: "没有利息支出", note_cash_rich: "低于 1，但有净现金或 FCF 利润率 ≥ 10%，不扣分",
    note_no_estimates: "没有分析师预期", note_loss_making: "盈利不为正（已公布或预期）", note_no_band: "没有可用的倍数历史",
    note_share_basis: "财报股数和现在的股数口径不一致（ADR 比例或未调整的拆股），倍数历史不可比",
    note_price_jump: "股价历史里有单日跌超 50% 或涨超 100%（可能是未调整的拆股），倍数历史不可比",
    note_currency: "财报和股价币种不同，这个比率会被汇率扭曲", note_currency_z2: "只看 Z''：财报和股价币种不同，Z 会被汇率扭曲",
    note_no_dcf: "没有 DCF：起始自由现金流不为正", note_dcf_negative: "DCF 估值不为正：净债务超过现金流折现值",
    note_no_market: "没有行业数据", note_short_history: "财年数不够", note_no_data: "没有数据",
    note_na_financial: "银行和保险公司不用这些指标", note_na_reit: "REIT 不用这些指标（折旧和商业模式会扭曲它们）",
    note_na_utility: "公用事业不用这些指标（受监管、重资本）",
    val_negative_fcf: "FCF < 0", val_no_interest: "无利息支出", val_ebitda_not_positive: "EBITDA ≤ 0",
    val_implied_below_range: "隐含每年 < −50%", val_implied_above_range: "隐含每年 > 100%", val_dcf_negative: "≤ −100%",
    pio_scaled: (s, o, v) => `${s} / ${o}（折合 ${v} / 9）`,
    altman_rule: "安全 +1 · 灰色 0 · 危险 −1 · Z 和 Z'' 都危险 −2",
    zone_safe: "安全", zone_grey: "灰色", zone_distress: "危险",
    cap_value_trap: "价值陷阱：估值便宜，但质量和成长平均偏弱（两项均值 ≤ −0.5）", cap_altman_distress: "Altman Z 和 Z'' 都在危险区",
    cap_interest_coverage: "有净债务，且最近两个财年利息覆盖都不到 1.5 倍（EBIT；REIT 用 EBITDA）",
    cap_cash_burn: "连续两年自由现金流为负（REIT 和公用事业看经营现金流），且有净债务",
    cap_negative_equity: "股东权益不为正", cap_note: "触发后总分最高只能是 +0.4（中性）。",
    cf_value_trap: "估值便宜，但质量和成长平均偏弱。便宜往往有原因。",
    cf_quality_premium: "质量好但估值贵：好公司已经按好公司定价。",
    cf_methods_disagree: "相对估值（和自身历史、行业比）与绝对估值（DCF、反向 DCF）方向相反，分歧通常来自增长假设。",
    cf_growth_slowdown: "当前倍数处在历史低位，但预期 EPS 增速不到过去的一半，倍数未必回到中位。",
    cf_group_expensive: g => `相对${g}便宜，但${g}自身的 P/E 处在历史最高的 20%。`,
    cf_adjusted_eps: g => `分析师 EPS 比公布的 EPS 高约 ${g}（调整后口径），前瞻 P/E 看起来会比 GAAP P/E 低。`,
    cf_cyclical_peak: (m, med, n, g) => `营业利润率 ${m} 远高于 ${n} 年中位数 ${med}，而分析师预期 EPS 变化 ${g}：利润率上升、增长和 DCF 可能是在读周期高点。`,
    cf_currency: (st, px) => `财报用 ${st}，股价用 ${px}：DCF、反向 DCF、P/E 相对行业、EV 和历史倍数、Altman Z（保留 Z''）会被汇率扭曲，不计入。`,
    cf_red_line: w => `资产负债表红线：${w}。`,
    grp_industry: "行业", grp_sector: "板块",
    cr_coverage: v => `数据覆盖 ${v}`, cr_agreement: v => `各大项方向一致 ${v}`, cr_methods: v => `估值方法一致 ${v}`,
    cr_short_history: "财年不足 4 年", cr_adjusted_eps: "分析师 EPS 是调整后口径", cr_proxy_data: "数据来自第三方代理",
    cr_capped: "触发了红线或价值陷阱封顶", cr_currency: "财报和股价币种不同", cr_cyclical_peak: "利润率可能处在周期高点",
    pctile: n => `第 ${n} 百分位`, pctile_low: "低于 3 年内每一天", pctile_high: "高于 3 年内每一天",
    sc_how_items: [
      "每个指标按固定区间打 −2 到 +2 分；正好落在分界点上的，算进数值更大的那一档（比如正好第 25 百分位得 +1，不是 +2）。",
      "每个大项是它下面各指标的加权平均；总分再按 35% 估值、25% 质量、20% 成长、20% 财务健康加权。",
      "银行和保险公司、REIT、公用事业各用自己的一套指标和权重（比如银行看 P/B、ROE 和股东权益 / 总资产），通用指标里它们不用的显示为不适用。",
      "算不出来的指标（缺数据、亏损、DCF 跳过、币种不一致）按 0 分计、权重不变，所以数据越少，分数越接近 0，置信度也越低。",
      "封顶规则：碰到资产负债表红线，或者估值便宜但质量和成长平均偏弱（价值陷阱：两项均值 ≤ −0.5），总分最高 +0.4（中性）。另外，过去 EPS 增速超过 15%、但预期增速不到过去一半时，前瞻倍数位置那一项最多 +1。",
      "分档：高于 +1.2 看多，+0.4 到 +1.2 偏多，−0.4 到 +0.4 中性，−1.2 到 −0.4 偏空，低于 −1.2 看空；正好在分界上的取更靠近中性的标签。和技术面打分是同一套刻度。",
      "不计分：分析师目标价（偏乐观，而且和前瞻 P/E 用的是同一份 EPS 预期）、52 周区间和波动率区间（是价格会怎么动，不是值多少）、同行（自动同行可能混有外国上市公司）、宏观数据（只作背景，利率已经通过 DCF 的折现率算进去了）。",
      "这是按固定规则算出的标签，不是买卖建议；改任何阈值或权重都会升规则版本号。",
    ],
  },
  en: {
    sc_title: "Fundamental score", sc_rules: v => `rules v${v}`, sc_conf: "Confidence", conf_high: "high", conf_medium: "medium", conf_low: "low",
    sc_formula: "Score = 35% × valuation + 25% × quality + 20% × growth + 20% × financial health; each is between −2 and +2.",
    sc_hint: "Open a pillar to see each indicator's value, scoring bands, score and weight.",
    sc_pillar: "Pillar", sc_weight: "Weight", sc_score: "Score", sc_contrib: "Contribution", sc_cov: "Data coverage",
    sc_ind: "Indicator", sc_value: "Value", sc_rule: "Scoring bands", sc_icontrib: "To pillar", sc_icontrib_s: "Contrib.",
    sc_missing: "missing, counts as 0", sc_na: "not applicable", sc_raw: (raw, cap) => `${raw} before the cap, at most ${cap}`,
    sc_caps: "Caps", sc_conflicts: "Conflicts to note", sc_how: "How it is computed", sc_range: "Value range",
    sc_range_fwd_pe: "forward P/E at the 25th / median / 75th percentile of its 3-year multiple", sc_range_dcf: "DCF range",
    sc_range_vs: v => `mid vs price ${v}`, sc_na_group: n => n[0].toUpperCase() + n.slice(1),
    p_valuation: "Valuation", p_quality: "Quality", p_growth: "Growth", p_health: "Financial health",
    lbl_Bullish: "Bullish", "lbl_Moderately bullish": "Moderately bullish", lbl_Neutral: "Neutral",
    "lbl_Moderately bearish": "Moderately bearish", lbl_Bearish: "Bearish",
    ind_fwd_pe_position: "Forward P/E vs its 3-year range", ind_fwd_ev_position: "Forward EV/EBITDA vs its 3-year range",
    ind_pb_vs_history: "P/B vs its fiscal-year-end median", ind_implied_growth_gap: "Reverse DCF: implied minus expected growth",
    ind_dcf_margin: "DCF value vs price", ind_vs_industry: "P/E vs industry",
    ind_roic_level: "ROIC (median)", ind_roe_level: "ROE (median)", ind_roic_trend: "ROIC change over 3 years",
    ind_roe_trend: "ROE change over 3 years", ind_op_margin_trend: "Operating margin change over 3 years",
    ind_gross_margin_stability: "Gross margin stability (std. dev.)", ind_fcf_conversion: "FCF / net income (3-yr median)",
    ind_sbc_burden: "Stock comp % revenue", ind_revenue_cagr: "Revenue CAGR", ind_revenue_recent: "Revenue growth, last FY",
    ind_revenue_forward: "Expected revenue growth (analysts)", ind_eps_forward: "Expected EPS growth next FY (analysts)",
    ind_net_debt_ebitda: "Net debt / EBITDA", ind_interest_coverage: "Interest coverage (EBIT / interest)", ind_interest_coverage_ebitda: "Interest coverage (EBITDA / interest)",
    ind_altman: "Altman Z zone", ind_piotroski: "Piotroski F-score (of 9)", ind_current_ratio: "Current ratio",
    ind_dilution: "Share count change per year", ind_equity_to_assets: "Equity / assets",
    note_trailing_history: "no forward range: today's multiple vs its fiscal-year-end median",
    note_adjusted_basis: "analysts' figures are on another basis than reported ones (usually adjusted), which the forward range would mix: today's multiple vs its fiscal-year-end median instead",
    note_adjusted_basis_short: "analysts' figures are on another basis than reported ones (usually adjusted), and fewer than 3 fiscal years for the trailing fallback",
    note_clipped: "each end clipped to ±50%, so a change in a very high return reads as noise", note_few_tests: "fewer than 7 of the 9 tests have data",
    note_growth_slowdown: "capped at +1: expected EPS growth is under half the historical rate",
    note_historical_growth: "no analyst estimates: compared with historical revenue CAGR",
    note_historical_eps: "no usable analyst EPS estimates: historical EPS CAGR", note_sector_pe: "no industry P/E: compared with the sector",
    note_implied_below_range: "price implies FCF shrinking more than 50% a year",
    note_implied_above_range: "price implies FCF growth above 100% a year", note_negative_fcf: "free cash flow negative in the last fiscal year",
    note_net_cash: "net cash", note_reit: "REIT bands, since leverage is structurally higher",
    note_utility: "utility bands, since regulated utilities carry structurally more debt",
    note_ebitda_coverage: "a REIT's EBIT is after heavy property depreciation", note_ebitda_not_positive: "EBITDA not positive",
    note_no_interest: "no interest expense", note_cash_rich: "below 1 but offset by net cash or FCF margin ≥ 10%",
    note_no_estimates: "no analyst estimates", note_loss_making: "earnings not positive (reported or expected)",
    note_no_band: "no usable multiple history",
    note_share_basis: "statement share counts are not on today's basis (ADR ratio or unadjusted split): multiple history not comparable",
    note_price_jump: "a one-day price fall above 50% or rise above 100% (possibly an unadjusted split): multiple history not comparable",
    note_currency: "statements and price in different currencies: this ratio is off by the exchange rate",
    note_currency_z2: "Z'' only: statements and price in different currencies distort Z",
    note_no_dcf: "no DCF: starting free cash flow not positive", note_dcf_negative: "DCF value not positive: net debt exceeds the discounted cash flows",
    note_no_market: "no industry data", note_short_history: "not enough fiscal years", note_no_data: "no data",
    note_na_financial: "not used for banks and insurers", note_na_reit: "not used for REITs (depreciation and the business model distort them)",
    note_na_utility: "not used for utilities (regulated and capital-heavy)",
    val_negative_fcf: "FCF < 0", val_no_interest: "no interest", val_ebitda_not_positive: "EBITDA ≤ 0",
    val_implied_below_range: "implied < −50%/yr", val_implied_above_range: "implied > 100%/yr", val_dcf_negative: "≤ −100%",
    pio_scaled: (s, o, v) => `${s} / ${o} (≈${v} / 9)`,
    altman_rule: "safe +1 · grey 0 · distress −1 · Z and Z'' both distress −2",
    zone_safe: "safe", zone_grey: "grey", zone_distress: "distress",
    cap_value_trap: "value trap: cheap valuation while quality and growth average −0.5 or less", cap_altman_distress: "Altman Z and Z'' both in the distress zone",
    cap_interest_coverage: "net debt, and interest covered less than 1.5x in each of the last two fiscal years (EBIT; EBITDA for REITs)",
    cap_cash_burn: "free cash flow (operating cash flow for REITs and utilities) negative two years running, with net debt",
    cap_negative_equity: "shareholders' equity not positive", cap_note: "When one triggers, the score is at most +0.4 (Neutral).",
    cf_value_trap: "Cheap valuation while quality and growth are weak on average: cheap stocks are often cheap for a reason.",
    cf_quality_premium: "Strong quality but expensive valuation: a good business already priced as one.",
    cf_methods_disagree: "Relative methods (own history, industry) and absolute methods (DCF, reverse DCF) point opposite ways; the gap usually comes from the growth assumption.",
    cf_growth_slowdown: "Today's multiple is low in its history, but expected EPS growth is under half the historical rate, so the multiple may not return to its median.",
    cf_group_expensive: g => `Cheap against its ${g}, but the ${g} itself sits in the top fifth of its own P/E history.`,
    cf_adjusted_eps: g => `Analysts' EPS is about ${g} above reported EPS (adjusted basis), so forward P/E looks lower than GAAP P/E.`,
    cf_cyclical_peak: (m, med, n, g) => `Operating margin (${m}) is far above its ${n}-year median (${med}) while analysts expect EPS to change ${g}: rising margins, growth and the DCF may be reading a cyclical peak.`,
    cf_currency: (st, px) => `Statements are in ${st} and the price in ${px}: the DCF, reverse DCF, P/E vs industry, EV and trailing multiples and Altman Z (Z'' kept) would be off by the exchange rate, so they are left out.`,
    cf_red_line: w => `Balance-sheet red line: ${w}.`,
    grp_industry: "industry", grp_sector: "sector",
    cr_coverage: v => `data coverage ${v}`, cr_agreement: v => `pillars agreeing ${v}`, cr_methods: v => `valuation methods agreeing ${v}`,
    cr_short_history: "fewer than 4 fiscal years", cr_adjusted_eps: "analyst EPS on an adjusted basis", cr_proxy_data: "data from a third-party proxy",
    cr_capped: "a red-line or value-trap cap triggered", cr_currency: "statements and price in different currencies",
    cr_cyclical_peak: "operating margin possibly at a cyclical peak",
    pctile: n => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th")} percentile`,
    pctile_low: "below every day of its 3-year range", pctile_high: "above every day of its 3-year range",
    sc_how_items: [
      "Each indicator scores −2 to +2 from fixed bands; a value exactly on a boundary goes to the band of higher values (exactly the 25th percentile scores +1, not +2).",
      "A pillar is the weighted mean of its indicators; the score weights them 35% valuation, 25% quality, 20% growth, 20% financial health.",
      "Banks and insurers, REITs and utilities use their own indicator sets and weights (a bank, for example, is judged on P/B, ROE and equity / assets); general indicators their set leaves out are shown as not applicable.",
      "An indicator that cannot be computed (no data, a loss, a skipped DCF, mixed currencies) counts as 0 and keeps its weight, so less data pulls the score toward 0 and lowers the confidence.",
      "Caps: a balance-sheet red line, or a cheap valuation while quality and growth average −0.5 or less (value trap), holds the score at +0.4 (Neutral) at most. Separately, after historical EPS growth above 15%, a forward-multiple position scores at most +1 when expected EPS growth is under half of it.",
      "Labels: above +1.2 Bullish, +0.4 to +1.2 Moderately bullish, −0.4 to +0.4 Neutral, −1.2 to −0.4 Moderately bearish, below −1.2 Bearish; a score exactly on a bound takes the label nearer Neutral. The technical scorecard uses the same scale.",
      "Not scored: analyst targets (optimistic, and built from the same EPS estimates as forward P/E), the 52-week and volatility ranges (how the price moves, not what it is worth), peers (auto-peers can include foreign listings) and macro data (context; rates already enter through the DCF discount rate).",
      "A rule-based label, not a recommendation; any change to a threshold or weight bumps the rules version.",
    ],
  },
};
Object.assign(UI.zh, SCORE_UI.zh);
Object.assign(UI.en, SCORE_UI.en);

// Whole cells, labels and headings (matched after trimming).
const ZH_EXACT = new Map(Object.entries({
  // section headings (the "N. " prefix is handled separately)
  "Profitability & returns": "盈利能力与回报",
  "Balance sheet & liquidity": "资产负债与流动性",
  "Cash flow quality & capital allocation": "现金流质量与资本配置",
  "Quality scores": "质量评分",
  "DCF (FCF-based, 10 years + terminal)": "DCF（基于自由现金流，10 年 + 永续）",
  "Analyst consensus": "分析师预期",
  "Price range (forward P/E and EV/EBITDA, DCF, analyst targets, volatility)": "股价区间（前瞻 P/E 与 EV/EBITDA、DCF、分析师目标价、波动）",
  "Forward P/E (next-12-month EPS)": "前瞻 P/E（未来 12 个月 EPS）",
  "Forward EV/EBITDA (next-12-month EBITDA)": "前瞻 EV/EBITDA（未来 12 个月 EBITDA）",
  "Volatility range to each fiscal year end": "到各财年末的波动区间",
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
  "Base": "基准", "Base vs price": "基准 vs 股价", "At today's P/E": "按当前 P/E", "At today's EV/EBITDA": "按当前 EV/EBITDA",
  "When": "时点", "Now": "现在", "EPS used": "所用 EPS", "EBITDA used": "所用 EBITDA",
  "To": "截至", "Date": "日期", "Years": "年数",
  "68% range (+/-1 sd)": "68% 区间（±1 个标准差）", "95% range (+/-1.96 sd)": "95% 区间（±1.96 个标准差）",
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
  "lowest / consensus / highest target": "最低 / 共识 / 最高目标价",
  "No method had enough data for a range.": "数据不够，没有一种方法能算出区间。",
  "The price history has a one-day fall of more than 50% or rise of more than 100% (possibly a stock split the prices do not reflect), so no forward multiple range is shown.":
    "股价历史里有单日跌超过 50% 或涨超过 100% 的情况（可能是股价没有按拆股调整），所以不显示前瞻倍数区间。",
  "Not enough positive-earnings price history for a P/E range (needs about 6 months).":
    "盈利为正的历史股价数据不够（约需 6 个月），算不了 P/E 区间。",
  "Not enough positive-earnings price history for a multiple range (needs about 6 months).":
    "盈利为正的历史股价数据不够（约需 6 个月），算不了倍数区间。",
  "The share counts in the statements do not match today's share basis (for example a stock split the statements do not reflect, an ADR ratio or several share classes), so the multiple history is not comparable and no forward multiple range is shown.":
    "财报里的股数和现在的股本口径对不上（比如财报没有反映拆股、ADR 换股比例或多类股票），历史倍数没法比，所以不显示前瞻倍数区间。",
  "Not available: no analyst EBITDA estimates, no net debt figure, or not enough positive-EBITDA price history.":
    "无法计算：没有分析师 EBITDA 预期、缺少净债务数据，或 EBITDA 为正的历史股价数据不够。",
  "Needs analyst estimates for the current and next fiscal years (not on this FMP plan or none published); forward multiple ranges not available.":
    "需要本财年和下一财年的分析师预期（套餐不含或没有发布），算不了前瞻倍数区间。",
  "Forward P/E each day = close / next-12-month EPS: the fiscal year in progress and the one after it, weighted by the time left in the year (reported EPS once a year is reported, the analysts' average otherwise). This is how published forward P/E histories are built; a single fiscal year's EPS would make the multiple jump at every year end for a fast grower and skew the range.":
    "每天的前瞻 P/E = 当天收盘价 ÷ 未来 12 个月 EPS：当天所在财年和下一财年按该财年剩余时间加权（已公布的财年用实际数，其余用分析师平均预期）。市面上的前瞻 P/E 历史都是这么算的；如果只用单个财年的 EPS，高增长公司的倍数会在每个财年末跳一下，把区间拉偏。",
  "Low / Base / High = EPS used x the 25th-percentile / median / 75th-percentile forward P/E. Now = a fair-value range for today. At a fiscal year end the next 12 months are exactly the following fiscal year, so those rows use that year's average estimate: a fair-value range for that date if the company earns it and trades at its usual multiple. Not a forecast.":
    "低 / 基准 / 高 = 所用 EPS × 前瞻 P/E 的 25 分位 / 中位数 / 75 分位。「现在」= 今天的合理价格区间。到财年末那一天，未来 12 个月正好就是下一个财年，所以财年末那几行用的是下一财年的平均预期：意思是如果公司赚到这个数、市场给它惯常的倍数，那一天的合理价格区间。这不是预测。",
  "At today's P/E = EPS used x today's forward P/E: where the price would be if the multiple stays where it is (earnings growth only, no re-rating).":
    "按当前 P/E = 所用 EPS × 今天的前瞻 P/E：如果倍数保持不变，股价会在哪里（只算盈利增长，不算估值重估）。",
  "n/a = zero or negative EPS in the period used, so a P/E-based price is not meaningful.":
    "n/a = 所用期间里有为零或负的 EPS，用 P/E 算价格没有意义。",
  "EV each day = price x shares + net debt + minority interest of the latest reported fiscal year; next-12-month EBITDA as for EPS above. Price = (multiple x EBITDA used - today's net debt and minority interest) / today's shares. Columns as in the P/E table. EV/EBITDA looks through leverage and tax, so it is a cross-check on the P/E rows.":
    "每天的 EV = 股价 × 股数 + 净债务 + 少数股东权益（都用最近一个已公布财年的数）；未来 12 个月 EBITDA 的算法和上面的 EPS 一样。股价 = （倍数 × 所用 EBITDA - 现在的净债务和少数股东权益）÷ 现在的股数。各列含义同 P/E 表。EV/EBITDA 不受杠杆和税率影响，可以用来交叉验证 P/E 那几行。",
  "n/a = no positive EBITDA estimate for that period.": "n/a = 这段期间没有为正的 EBITDA 预期。",
  "REIT: net-income P/E understates cash earnings, so the P/E rows are a weak guide here.":
    "REIT：按净利润算的 P/E 低估了现金收益，这里 P/E 那几行参考价值有限。",
  "A statistical range around today's price (lognormal, no drift), not a valuation: about two in three outcomes at that date fall inside the 68% range if volatility holds. Real returns have fatter tails, so moves beyond the 95% range happen more often than 1 in 20. Options-implied volatility is the market's own forward estimate and usually beats the past year's; enter it with --iv (e.g. 0.45 for 45%).":
    "这是以现价为中心的统计区间（对数正态、不假设涨跌趋势），不是估值：如果波动率不变，到那天的股价大约三分之二的可能落在 68% 区间里。真实股价的极端涨跌比正态分布多，所以超出 95% 区间的情况不止二十分之一。期权隐含波动率是市场自己对未来波动的估计，通常比过去一年的实际波动更准；可以在「隐含波动率 %」里填（命令行用 --iv 0.45 表示 45%）。",
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

// Price-range methods and horizons: the report's summary table uses the same English names as the
// chart (RANGE_METHODS and _when() in analyze.py), so each English name maps to the chart's Chinese one.
for (const k of ["rc_fwd_pe", "rc_fwd_ev", "rc_dcf", "rc_targets", "rc_week52", "rc_volatility", "rc_past", "rc_now", "rc_12m"]) {
  ZH_EXACT.set(UI.en[k], UI.zh[k]);
}

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
  [/^(EPS|EBITDA) (\S+) \((next 12 months|FY(\d{4}) est\.)\) x (P\/E|EV\/EBITDA) (\S+) \/ (\S+) \/ (\S+)(, less net debt)?$/,
    (m, base, v, src, fy, k, a, b, c, nd) => `${base} ${v}（${fy ? `FY${fy} 预期` : "未来 12 个月"}）× ${k} ${a} / ${b} / ${c}` + (nd ? "，扣除净债务" : "")],
  [/^discount rate (\S+) \+\/-1pt, growth (\S+) \+\/-2pt$/, "折现率 $1 ±1 个百分点，增速 $2 ±2 个百分点"],
  [/^lowest \/ highest daily close, (\S+) to (\S+)$/, "最低 / 最高日收盘价，$1 至 $2"],
  [/^(\S+) \((\d+)% FY(\d{4}) \+ (\d+)% FY(\d{4})\)$/, "$1（$2% FY$3 + $4% FY$5）"],
  [/^(\S+) \(FY(\d{4}) est\.\)$/, "$1（FY$2 预期）"],
  [/^The FY(\d{4}) end row rests on the FY(\d{4}) consensus(?: \((\d+) analysts\))?, which is further out and less reliable\.$/,
    (m, a, b, n) => `FY${a} 末这一行用的是 FY${b} 的一致预期${n ? `（${n} 位分析师）` : ""}，时间更远，可靠性更低。`],
  [/^No analyst estimate for the year after FY(\d{4}), so no range at the end of FY(\d{4})\.$/, "没有 FY$1 之后那一年的分析师预期，所以没有 FY$2 末的区间。"],
  [/^FY(\d{4}) end$/, "FY$1 末"],
  [/^price \+\/-1 sd at (\S+) a year \((realized|implied)\); 95%: (\S+) - (\S+)$/,
    (m, v, src, lo, hi) => `现价 ±1 个标准差，年化波动率 ${v}（${src === "implied" ? "隐含" : "过去一年实际"}）；95%：${lo} - ${hi}`],
  [/^Volatility (\S+) a year \(realized: standard deviation of the past year's daily moves, annualized\)\.$/,
    "波动率：年化 $1（过去一年的实际波动：日涨跌幅的标准差，年化）。"],
  [/^Volatility (\S+) a year \(implied volatility you entered\)\.$/, "波动率：年化 $1（你填入的隐含波动率）。"],
  [/^Current price (\S+)\. Each row is the range one method gives; none of them is a forecast\.$/, "当前股价 $1。每一行是一种方法给出的区间，都不是预测。"],
  [/^(\d+)-year forward (P\/E|EV\/EBITDA) on next-12-month (EPS|EBITDA): 25th percentile (\S+), median (\S+), 75th percentile (\S+) \(10th-90th (\S+) - (\S+); (\d+) trading days, (\S+) to (\S+)\)\.$/,
    "过去 $1 年按未来 12 个月 $3 算的前瞻 $2：25 分位 $4，中位数 $5，75 分位 $6（10-90 分位 $7 - $8；$9 个交易日，$10 至 $11）。"],
  [/^Today's forward (P\/E|EV\/EBITDA): (\S+), at the (\d+)(?:st|nd|rd|th) percentile of that history\.$/,
    "当前前瞻 $1：$2，处于这段历史的第 $3 百分位。"],
  [/^Today's forward (P\/E|EV\/EBITDA): (\S+), (below|above) every day of that history\.$/,
    (m, k, v, dir) => `当前前瞻 ${k}：${v}，${dir === "below" ? "低于" : "高于"}这段历史里的每一天。`],
  [/^The forward (P\/E|EV\/EBITDA) history is wide \((\S+) - (\S+) between the 25th and 75th percentiles\), often after an earnings trough or a re-rating; lean on the Base column\.$/,
    "历史前瞻 $1 分布很宽（25-75 分位 $2 - $3），通常是经历过盈利低谷或估值重估；以「基准」一列为主。"],
  [/^Analysts' (\S+) EBITDA \((\S+)\) differs from reported EBITDA \((\S+)\) by (\S+): the estimates may be on an adjusted basis \(for example before stock-based compensation\), so the EV\/EBITDA prices may run (high|low)\.$/,
    (m, fy, e, rp, gap, dir) => `分析师对 ${fy} 的 EBITDA（${e}）和公司公布的 EBITDA（${rp}）相差 ${gap}：预期可能是调整后口径（比如不扣股权激励），所以 EV/EBITDA 算出的价格可能偏${dir === "high" ? "高" : "低"}。`],
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
  [/^Price from the latest quote at (\S+ \S+) New York time\.$/, "股价来自最新报价，美东时间 $1。"],
  [/^Price from the latest quote\.$/, "股价来自最新报价。"],
  [/^Price from the company profile, which is cached for up to a day \(no current quote\)\.$/, "股价来自公司资料，最多缓存一天（没有拿到当前报价）。"],
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
