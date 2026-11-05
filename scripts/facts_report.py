#!/usr/bin/env python3
"""
The facts report: one fa-2.0 document (scripts/facts.py) as markdown, in English; the web page translates it.

analyze.py prints it, the web page shows it, and the decision engine loads this file by path to show runs it
converted from older versions, so it uses the standard library only and imports none of the skill's modules.
It shows the statements, ratios, multiples and standard models the document holds, and nothing else: no score,
label, flag, price level, price target or margin of safety, and the distributions of the forward multiples are
statistics only, never turned into prices.

  render(f, macro_md=None, calls=None) -> str
    f           a fa-2.x document
    macro_md    the body of the rates & macro section (analyze.py --macro); None: no such section
    calls       (network calls, cache hits) for the data notes; None: no such line
"""
from __future__ import annotations

import statistics

# Company types other than "general" (company.kind), and the measures named in company.not_meaningful.
KINDS = {
    "financial": "Financial company",
    "fee_financial": ("Fee-based financial company (exchange, data provider or insurance broker), analysed like "
                      "other companies; clearing margin and client money sit on its balance sheet"),
    "reit": "REIT; net income is after property depreciation",
    "utility": "Regulated utility, capital-heavy",
}
MEASURES = {"gross_margin": "gross margin", "ev_ebitda": "EV/EBITDA", "ev_sales": "EV / sales",
            "fcf": "free cash flow", "dcf": "DCF", "altman": "Altman Z", "current_ratio": "current ratio",
            "pe": "P/E"}
PIOTROSKI_TESTS = {
    "roa_positive": "ROA > 0", "ocf_positive": "Operating cash flow > 0", "roa_improved": "ROA improved",
    "ocf_above_net_income": "Cash flow > net income (accruals)", "leverage_fell": "Long-term leverage fell",
    "current_ratio_improved": "Current ratio improved", "no_dilution": "No net share dilution",
    "gross_margin_improved": "Gross margin improved", "asset_turnover_improved": "Asset turnover improved",
}
# Why the multiple history is not comparable (valuation.vs_own_history.status, forward_band.status).
HISTORY_PROBLEMS = {
    "share_basis": ("The share counts in the statements do not match today's share basis (for example a stock "
                    "split the statements do not reflect, an ADR ratio or several share classes)"),
    "price_jump": ("The price history has a one-day fall of more than 50% or rise of more than 100% (possibly a "
                   "stock split the prices do not reflect)"),
}
GROWTH_SOURCES = {"user": "user input", "revenue_cagr_clamped_0_15": "historical revenue CAGR, clamped to 0-15%",
                  "default_5pct": "default (no usable revenue history)"}
DCF_SKIPS = {
    "skipped_financial": "Financial-sector company: an FCF-based DCF is not meaningful, so none is computed.",
    "fcf_not_positive": "Starting FCF is not positive; DCF not applicable.",
    "invalid_inputs": "DCF inputs invalid (discount rate must exceed terminal growth).",
}
REVERSE_DCF = {
    "below_range": "Reverse DCF: the implied growth is below -50% a year, outside the range searched.",
    "above_range": "Reverse DCF: the implied growth is above 100% a year, outside the range searched.",
    "not_computable": "Reverse DCF: not computable.",
}


# ---------------------------------------------------------------------------- formatting (as analyze.py)
def money(v):
    if v is None:
        return "n/a"
    a, s = abs(v), "-" if v < 0 else ""
    for div_, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div_:
            return f"{s}{a / div_:.2f}{suf}"
    return f"{s}{a:.0f}"


def txt(v):
    return "n/a" if v is None else str(v)


def one_line(v):
    """A text from FMP (a name, an endpoint, an error) on one line: a line break inside it (\\r, \\n, U+2028,
    U+2029) would split a list item or a table row."""
    return "n/a" if v is None else " ".join(str(v).split())


def pct(v):
    if v is None:
        return "n/a"
    return "0.0%" if abs(v) < 0.0005 else f"{v * 100:.1f}%"


def pct_digits(v, digits):
    """A percentage with fixed decimals, as macro.py prints yields (2) and percentiles (0)."""
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def mult(v):
    if v is None:
        return "n/a"
    return "0.0x" if abs(v) < 0.05 else f"{v:.1f}x"


def ratio(v):
    return "n/a" if v is None else f"{v:.2f}"


def per_share(v):
    return "n/a" if v is None else f"{v:,.2f}"


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def metric_rows(periods, spec):
    """spec: [(label, key, formatter, CAGR text, or False for no CAGR column)]"""
    rows = []
    for label, key, f, extra in spec:
        row = [label] + [f(p.get(key)) for p in periods]
        if extra is not False:
            row.append(extra if isinstance(extra, str) else "")
        rows.append(row)
    return rows


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ---------------------------------------------------------------------------- reading the document
def get(d, *path):
    """d[k1][k2]..., or None where a level is missing or null."""
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def latest(f, block, key):
    """The latest fiscal year's value in a statements / metrics column."""
    col = get(f, block, key) or []
    return col[-1] if col else None


def pos_div(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def periods(f):
    """The columns of the statement tables, oldest first: each fiscal year, then the TTM when there is one, as
    dicts of the statement and metric values under their fa-2.0 names."""
    blocks = [f.get("statements") or {}, f.get("metrics") or {}]
    out = []
    for i, label in enumerate(blocks[0].get("period") or []):
        p = {}
        for b in blocks:
            p.update({k: col[i] if i < len(col) else None for k, col in b.items() if isinstance(col, list)})
        out.append(dict(p, label=label or p.get("end") or "n/a"))
    if f.get("ttm"):
        out.append(dict(f["ttm"], label=f["ttm"].get("period") or "TTM"))
    return out


def price_text(f):
    px = f.get("price") or {}
    return per_share(px.get("value")) + (f" {px['currency']}" if px.get("currency") else "")


# ---------------------------------------------------------------------------- sections
def header(f):
    c, px, per = f.get("company") or {}, f.get("price") or {}, f.get("periods") or {}
    out = [f"# {f.get('ticker')} - {one_line(c['name'])}" if c.get("name") else f"# {f.get('ticker')}"]
    sector, industry, exchange = (one_line(c.get(k) or None) for k in ("sector", "industry", "exchange"))
    out.append(f"{sector} / {industry} | {exchange} | Price {price_text(f)} | Market cap {money(c.get('market_cap'))} "
               f"| Beta {ratio(c.get('beta'))}")
    fys, ccy = per.get("fiscal_years") or [], c.get("statement_currency") or px.get("currency")
    span = "n/a" if not fys else txt(fys[0]) if len(fys) == 1 else f"{txt(fys[0])}-{txt(fys[-1])}"
    ttm = f.get("ttm")
    out.append(f"\nData basis: annual {span}" + (f" in {ccy}" if ccy else "") +
               (f" + TTM to {txt(ttm.get('end'))}" if ttm else " (TTM unavailable: using last fiscal year)") +
               f". Valuation uses {per.get('valuation_basis') or 'n/a'} figures. As of {f.get('as_of') or 'n/a'}.")
    kind = c.get("kind") or "general"
    if kind != "general":
        line = f"**Company type:** {KINDS.get(kind, kind)}."
        names = [MEASURES.get(k, k) for k in c.get("not_meaningful") or []]
        if names:
            line += f" Not meaningful for this type of company: {', '.join(names)}."
        out.append("\n" + line)
    return out


def statement_sections(f):
    """Sections 1-4: the same tables, rows and formatting as the reports before v2.0."""
    ps = periods(f)
    heads = [p["label"] for p in ps]
    g = f.get("growth") or {}
    cg = g.get("cagr") or {}
    out = ["\n## 1. Growth"]
    n = g.get("years") or 0
    out.append(f"Last column: compound annual growth (CAGR) over {n} year{'' if n == 1 else 's'}, "
               f"{txt(g.get('from'))} to {txt(g.get('to'))}." if n else
               "Last column: compound annual growth (CAGR), which needs at least 2 fiscal years.")
    out.append(table(["Metric"] + heads + ["CAGR"], metric_rows(ps, [
        ("Revenue", "revenue", money, pct(cg.get("revenue"))),
        ("Revenue YoY", "revenue_yoy", pct, ""),
        ("Gross profit", "gross_profit", money, pct(cg.get("gross_profit"))),
        ("Operating income", "operating_income", money, pct(cg.get("operating_income"))),
        ("Net income", "net_income", money, pct(cg.get("net_income"))),
        ("EPS (diluted)", "eps_diluted", per_share, pct(cg.get("eps"))),
        ("EPS YoY", "eps_yoy", pct, ""),
        ("Free cash flow", "fcf", money, pct(cg.get("fcf"))),
        ("Diluted shares", "shares_diluted", money, pct(cg.get("shares"))),
    ])))

    out.append("\n## 2. Profitability & returns")
    out.append(table(["Metric"] + heads, metric_rows(ps, [
        ("Gross margin", "gross_margin", pct, False),
        ("Operating margin", "operating_margin", pct, False),
        ("Net margin", "net_margin", pct, False),
        ("EBITDA margin", "ebitda_margin", pct, False),
        ("FCF margin", "fcf_margin", pct, False),
        ("R&D % revenue", "rnd_pct", pct, False),
        ("ROE", "roe", pct, False),
        ("ROA", "roa", pct, False),
        ("ROIC (after tax)", "roic", pct, False),
    ])))

    out.append("\n## 3. Balance sheet & liquidity")
    out.append(table(["Metric"] + heads, metric_rows(ps, [
        ("Cash & ST investments", "cash", money, False),
        ("Total debt", "debt", money, False),
        ("Net debt (neg = net cash)", "net_debt", money, False),
        ("Net debt / EBITDA", "net_debt_to_ebitda", mult, False),
        ("Debt / equity", "debt_to_equity", ratio, False),
        ("Current ratio", "current_ratio", ratio, False),
        ("Quick ratio", "quick_ratio", ratio, False),
        ("Interest coverage (EBIT/int.)", "interest_coverage", mult, False),
        ("Shareholders' equity", "equity", money, False),
        ("Goodwill & intangibles", "goodwill_intangibles", money, False),
    ])))

    out.append("\n## 4. Cash flow quality & capital allocation")
    out.append(table(["Metric"] + heads, metric_rows(ps, [
        ("Operating cash flow", "ocf", money, False),
        ("Capex", "capex", money, False),
        ("Capex % revenue", "capex_pct", pct, False),
        ("FCF / net income", "fcf_conversion", ratio, False),
        ("Stock comp % revenue", "sbc_pct", pct, False),
        ("Buybacks", "buybacks", money, False),
        ("Dividends", "dividends", money, False),
        ("Share count YoY", "shares_yoy", pct, False),
    ])))
    return out


def valuation_section(f):
    now = get(f, "valuation", "now") or {}
    vh = get(f, "valuation", "vs_own_history") or {}
    out = ["\n## 5. Valuation", f"Price {price_text(f)}, {get(f, 'periods', 'valuation_basis') or 'n/a'} fundamentals."]
    rows = []
    for k, name in (("pe", "P/E"), ("ev_ebitda", "EV/EBITDA"), ("ps", "P/S"), ("p_fcf", "P/FCF"), ("pb", "P/B")):
        h = vh.get(k) or {}
        rng = f"{mult(h.get('min'))} - {mult(h.get('max'))}" if h.get("n") else "n/a"
        rows.append([name, mult(now.get(k)), mult(h.get("median")), rng, pct(h.get("vs_median"))])
    out.append(table(["Multiple", "Now", "Hist. median", "Hist. range", "Now vs median"], rows))
    out.append("\n(History = price on each fiscal-year-end date x that year's fundamentals.)")
    if vh.get("status") in HISTORY_PROBLEMS:
        out.append(f"{HISTORY_PROBLEMS[vh['status']]}, so the fiscal-year-end history is not comparable.")
    out.append("\n" + table(["Measure", "Value"], [
        ["Enterprise value", money(get(f, "company", "enterprise_value"))],
        ["EV / sales", mult(now.get("ev_sales"))],
        ["Earnings yield", pct(now.get("earnings_yield"))],
        ["FCF yield", pct(now.get("fcf_yield"))],
        ["Dividend yield (cash paid)", pct(now.get("dividend_yield"))],
        ["Shareholder yield (div + buyback - issuance)", pct(now.get("shareholder_yield"))],
    ]))
    return out


def _band_lines(b, name, base, years, start, end):
    """A forward multiple's daily distribution and where today sits in it. name: 'P/E' or 'EV/EBITDA'."""
    out = [f"{years}-year forward {name} on next-12-month {base}: 25th percentile {mult(b.get('p25'))}, median "
           f"{mult(b.get('median'))}, 75th percentile {mult(b.get('p75'))} (10th-90th {mult(b.get('p10'))} - "
           f"{mult(b.get('p90'))}; {txt(b.get('n'))} trading days, {txt(start)} to {txt(end)})."]
    p = b.get("pctile")
    if p is None or b.get("now") is None:
        out.append(f"Today's next-12-month {base} is not positive, so there is no forward {name} for today.")
        return out
    where = ("below every day of that history" if p == 0 else "above every day of that history" if p == 1 else
             f"at the {_ordinal(min(max(round(p * 100), 1), 99))} percentile of that history")
    out.append(f"Today's forward {name}: {mult(b['now'])}, {where}.")
    return out


def _band_missing(b, name, financial):
    status = b.get("status")
    if status == "not_applicable":
        return (f"No forward {name} distribution: EV multiples do not apply to a financial company." if financial
                else f"No forward {name} distribution: no net debt or share count for the enterprise value.")
    if status == "ebitda_not_positive":
        return f"No forward {name} distribution: next-12-month EBITDA is not positive."
    word = "earnings" if name == "P/E" else "EBITDA"
    return f"Not enough positive-{word} price history for a forward {name} distribution (needs about 6 months)."


def forward_section(f):
    fw = get(f, "valuation", "forward") or {}
    fb = get(f, "valuation", "forward_band") or {}
    financial = get(f, "company", "kind") == "financial"
    out = ["\n## 6. Forward multiples"]
    open_est = [e for e in get(f, "consensus", "estimates") or [] if not e.get("ended")][:2]
    eps_of = {e.get("fy"): e.get("eps_avg") for e in open_est}
    rows = []
    for i in (1, 2):
        fy = fw.get(f"fy{i}")
        if fy:
            rows.append(["P/E", f"FY{fy} EPS (consensus)", per_share(eps_of.get(fy)), mult(fw.get(f"pe_fy{i}"))])
    ntm = fw.get("ntm")
    if ntm:
        fys, w = ntm.get("fys") or [], ntm.get("weight")
        blend = ""
        if len(fys) == 2 and None not in fys and w is not None:
            w = round(w * 100)
            blend = f" ({w}% FY{fys[0]} + {100 - w}% FY{fys[1]})"
        rows.append(["P/E", f"next-12-month EPS{blend}", per_share(ntm.get("eps")), mult(fw.get("pe_ntm"))])
        if not financial:
            rows.append(["EV/EBITDA", f"next-12-month EBITDA{blend}", money(ntm.get("ebitda")),
                         mult(fw.get("ev_ebitda_ntm"))])
    status = fb.get("status")
    if not rows:
        out.append("Needs analyst estimates for the current and next fiscal years (not on this FMP plan or none "
                   "published); forward multiples not available.")
        return out
    out.append(table(["Multiple", "Based on", "Figure used", "Now"], rows))
    if any(r[3] == "n/a" for r in rows):
        out.append("\nn/a = the EPS or EBITDA used is zero or negative (or missing), so there is no multiple.")

    out.append("")
    years, start, end = fb.get("lookback_years") or 3, fb.get("from"), fb.get("to")
    if status == "no_estimates":
        out.append(f"No {years}-year distribution: it needs analyst estimates for the current and next fiscal years.")
        return out
    if status in HISTORY_PROBLEMS:
        out.append(f"{HISTORY_PROBLEMS[status]}, so the multiple history is not comparable and no distribution is "
                   f"shown.")
        return out
    if status != "ok":
        out.append("Not enough positive-earnings price history for a distribution of the forward multiples (needs "
                   "about 6 months).")
        return out
    shown = []
    for key, name, base in (("pe", "P/E", "EPS"), ("ev_ebitda", "EV/EBITDA", "EBITDA")):
        b = fb.get(key) or {}
        if b.get("status") in ("ok", "now_not_positive"):
            out += _band_lines(b, name, base, years, start, end)
            shown.append(key)
        else:
            out.append(_band_missing(b, name, financial))
    out.append("\nForward P/E each day = close / next-12-month EPS: the fiscal year in progress and the one after it, "
               "weighted by the time left in the year (reported EPS once a year is reported, the analysts' average "
               "otherwise). This is how published forward P/E histories are built; a single fiscal year's EPS would "
               "make the multiple jump at every year end for a fast grower and skew the range.")
    if "ev_ebitda" in shown:
        out.append("EV each day = price x shares + net debt + minority interest of the latest reported fiscal year; "
                   "next-12-month EBITDA as for EPS above.")
    vr = get(f, "consensus", "vs_reported") or {}
    gap = vr.get("eps") or {}
    if "pe" in shown and gap.get("gap") is not None and abs(gap["gap"]) > 0.05:
        out.append(f"Analysts' {txt(vr.get('fy'))} EPS ({per_share(gap.get('estimate'))}) differs from reported "
                   f"diluted EPS ({per_share(gap.get('reported'))}) by {pct(gap['gap'])}: the estimates may be on an "
                   f"adjusted (non-GAAP) basis, while the P/E history uses reported EPS for reported years.")
    gap = vr.get("ebitda") or {}
    if "ev_ebitda" in shown and gap.get("gap") is not None and abs(gap["gap"]) > 0.10:
        out.append(f"Analysts' {txt(vr.get('fy'))} EBITDA ({money(gap.get('estimate'))}) differs from reported EBITDA "
                   f"({money(gap.get('reported'))}) by {pct(gap['gap'])}: the estimates may be on an adjusted basis "
                   f"(for example before stock-based compensation), while the EV/EBITDA history uses reported EBITDA "
                   f"for reported years.")
    return out


def _group_now(g):
    if g.get("status") == "negative":
        return f"negative ({txt(g.get('date'))})"
    if g.get("status") == "stale":
        return f"n/a (last {txt(g.get('date'))})"
    return mult(g.get("pe"))


def group_section(f):
    out = ["\n## 7. Industry & sector P/E"]
    vg = get(f, "valuation", "vs_group")
    if not vg:
        out.append("No industry or sector data: market data was skipped (--no-market).")
        return out
    hist = get(f, "valuation", "vs_own_history", "pe") or {}
    rows = [[f"{f.get('ticker')} (company)", mult(vg.get("company_pe")), mult(hist.get("median")),
             f"{mult(hist.get('min'))} - {mult(hist.get('max'))}" if hist.get("n") else "n/a", "", ""]]
    groups = [(key, vg.get(key) or {}) for key in ("industry", "sector")]
    for key, g in groups:
        name = f"{key.capitalize()}: {one_line(g.get('name') or None)}"
        if (g.get("status") or "unavailable") == "unavailable":
            rows.append([name] + ["n/a"] * 5)
            continue
        rows.append([name, _group_now(g), mult(g.get("median")), f"{mult(g.get('min'))} - {mult(g.get('max'))}",
                     pct_digits(g.get("pe_pctile"), 0), mult(g.get("year_ago"))])
    out.append(table(["P/E", "Now", "Hist. median", "Hist. range", "Percentile in hist.", "1y ago"], rows))
    spans = [f"{key} daily since {txt(g.get('since'))} (latest {txt(g.get('date'))})" for key, g in groups
             if (g.get("status") or "unavailable") != "unavailable"]
    if hist.get("n"):
        spans.insert(0, f"company at its last {hist['n']} fiscal year-ends")
    ex = f" ({one_line(vg['exchange'])}-listed companies)" if vg.get("exchange") else ""
    out.append(f"\nCompany P/E vs industry: {pct(get(vg, 'industry', 'premium'))}; vs sector: "
               f"{pct(get(vg, 'sector', 'premium'))}. Industry/sector P/E is FMP's aggregate for the group{ex}, not a "
               f"market-cap-weighted index. History: {'; '.join(spans) or 'n/a'}.")
    return out


def quality_section(f):
    out = ["\n## 8. Quality scores"]
    pio = get(f, "models", "piotroski")
    if pio:
        out.append(f"**Piotroski F-score {txt(pio.get('fy'))}: {txt(pio.get('score'))} / {txt(pio.get('out_of'))}** "
                   f"(tests passed / tests with data)")
        out.append(table(["Test", "Result"], [[PIOTROSKI_TESTS.get(t.get("id"), t.get("id")),
                                               {True: "pass", False: "fail"}.get(t.get("pass"), "n/a")]
                                              for t in pio.get("tests") or []]))
    else:
        out.append("Piotroski F-score: needs at least 2 fiscal years.")
    alt = get(f, "models", "altman") or {}
    parts = []
    if alt.get("z") is not None:
        parts.append(f"Altman Z {alt['z']:.2f} ({txt(alt.get('z_zone'))}; >2.99 safe, <1.81 distress)")
    if alt.get("z2") is not None:
        parts.append(f"Z'' (non-manufacturer) {alt['z2']:.2f} ({txt(alt.get('z2_zone'))}; >2.6 safe, <1.1 distress)")
    out.append("\n" + (" | ".join(parts) or "Altman Z: not available (needs working capital, retained earnings, EBIT, "
                                            "revenue, total assets and total liabilities)."))
    if alt.get("status") == "not_meaningful":
        out.append("(Altman Z was built for industrial companies and is not meaningful for this type of company.)")
    return out


def _capm_note(d):
    """How the CAPM rate was set, as analyze.py wrote it (macro.capm_note)."""
    note = (f"CAPM: 10Y Treasury {pct_digits(d.get('rf'), 2)} ({txt(d.get('rf_date'))}) + beta {ratio(d.get('beta'))} "
            f"x US equity risk premium {pct_digits(d.get('erp'), 2)}")
    if d.get("beta_source") == "default_1":
        note += " [beta defaulted to 1.0]"
    note += f" = {pct_digits(d.get('raw'), 2)}"
    if d.get("clamped"):
        note += ", kept within 7%-13%"
    elif None not in (d.get("value"), d.get("raw")) and abs(d["value"] - d["raw"]) > 5e-5:
        note += ", rounded"
    return note


def _discount_source(d):
    method = d.get("method")
    if method == "user":
        return "user input"
    if method == "capm":
        return _capm_note(d)
    return ("fixed default; --no-market" if d.get("reason") == "no_market" else
            "fixed default; Treasury/risk-premium data unavailable")


def dcf_section(f):
    out = ["\n## 9. DCF"]
    d = get(f, "models", "dcf") or {}
    inp = d.get("inputs")
    if not inp or d.get("value_per_share") is None:
        out.append(DCF_SKIPS.get(d.get("status"), "DCF not available."))
        return out
    out.append("FCF-based, 10 years + terminal value.")
    basis = (f"{txt(get(f, 'periods', 'valuation_basis'))} FCF" if inp.get("fcf_start_basis") == "valuation_basis"
             else "average FCF of last 3 fiscal years")
    disc = inp.get("discount_rate") or {}
    out.append(table(["Assumption", "Value"], [
        ["Starting FCF", f"{money(inp.get('fcf_start'))} ({basis})"],
        ["Growth yrs 1-5", f"{pct(inp.get('growth_1_5'))} "
                           f"({GROWTH_SOURCES.get(inp.get('growth_source'), inp.get('growth_source'))})"],
        ["Growth yrs 6-10", f"fades linearly to terminal {pct(inp.get('terminal_growth'))}"],
        ["Discount rate", f"{pct(disc.get('value'))} ({_discount_source(disc)})"],
        ["Net debt deducted", money(inp.get("net_debt"))],
        ["Shares", money(inp.get("shares"))],
    ]))
    v = d["value_per_share"]
    head = (f"Base-case value {per_share(v)} per share." if v > 0 else
            f"Base-case value {per_share(v)} per share is not positive: net debt exceeds the discounted cash flows.")
    out.append(f"\n**{head}** Range (discount rate +/-1pt, growth +/-2pt): {per_share(d.get('low'))} - "
               f"{per_share(d.get('high'))}. Terminal value is {pct(d.get('terminal_value_share'))} of the total.")
    sens = d.get("sensitivity") or {}
    if sens.get("value_per_share"):
        out.append("\nValue per share (rows = discount rate, columns = growth yrs 1-5):")
        out.append(table(["r \\ g"] + [pct(g) for g in sens.get("growth_1_5") or []],
                         [[pct(r)] + [per_share(x) for x in row]
                          for r, row in zip(sens.get("discount_rates") or [], sens["value_per_share"])]))
    rev = get(f, "models", "reverse_dcf") or {}
    if rev.get("implied_growth_1_5") is not None:
        out.append(f"\n**Reverse DCF:** today's price implies ~{pct(rev['implied_growth_1_5'])} FCF growth per year "
                   f"for 5 years (then fading), at a {pct(rev.get('discount_rate'))} discount rate.")
    elif rev.get("status") in REVERSE_DCF:
        out.append("\n" + REVERSE_DCF[rev["status"]])
    return out


def consensus_section(f):
    out = ["\n## 10. Analyst consensus"]
    est = get(f, "consensus", "estimates") or []
    if not est:
        out.append("No analyst estimates (not on this FMP plan, or none published).")
    else:
        # the old report's columns, plus the EBITDA consensus it showed in its forward EV/EBITDA tables
        out.append(table(["FY", "EPS est. (low-high)", "Fwd P/E", "Revenue est.", "Rev. growth", "EBITDA est.",
                          "# analysts"],
                         [[f"{txt(e.get('fy'))} (ended, not yet reported)" if e.get("ended") else txt(e.get("fy")),
                           f"{per_share(e.get('eps_avg'))} ({per_share(e.get('eps_low'))}-{per_share(e.get('eps_high'))})",
                           mult(e.get("pe_on_fy_eps")), money(e.get("revenue_avg")), pct(e.get("revenue_growth")),
                           money(e.get("ebitda_avg")), "n/a" if e.get("analysts") is None else e["analysts"]]
                          for e in est]))
    vr = get(f, "consensus", "vs_reported") or {}
    rows = [[name, fmt((vr.get(key) or {}).get("estimate")), fmt((vr.get(key) or {}).get("reported")),
             pct((vr.get(key) or {}).get("gap"))]
            for key, name, fmt in (("eps", "EPS (diluted)", per_share), ("ebitda", "EBITDA", money),
                                   ("revenue", "Revenue", money)) if vr.get(key)]
    if rows:
        out.append(f"\nAnalysts' figures for {txt(vr.get('fy'))}, the last reported year, against the reported ones:")
        out.append(table(["Item", "Analysts", "Reported", "Gap"], rows))
        notes = []
        if vr.get("revenue"):
            notes.append("The analysts use another revenue basis (often net instead of gross revenue), so the first "
                         "year's revenue growth above is measured from their figure.")
        if vr.get("eps") or vr.get("ebitda"):
            notes.append("A gap in EPS or EBITDA usually means the estimates are on an adjusted (non-GAAP) basis, for "
                         "example before stock-based compensation.")
        out.append("\n" + "\n".join(notes))
    return out


def own_row(f):
    """The company's latest fiscal year with the formulas used for each peer (market cap now, statements of
    that year), so the rows compare like with like."""
    mcap = get(f, "company", "market_cap")
    debt, cash = latest(f, "statements", "debt"), latest(f, "statements", "cash")
    ev = mcap + debt - cash + (latest(f, "statements", "minority_interest") or 0) if None not in (mcap, debt, cash) \
        else None
    return {"symbol": f.get("ticker"), "market_cap": mcap,
            "pe": pos_div(mcap, latest(f, "statements", "net_income")),
            "ev_ebitda": pos_div(ev, latest(f, "statements", "ebitda")),
            "ps": pos_div(mcap, latest(f, "statements", "revenue")),
            "p_fcf": pos_div(mcap, latest(f, "statements", "fcf")),
            **{k: latest(f, "metrics", k) for k in ("revenue_yoy", "gross_margin", "operating_margin", "roic",
                                                     "net_debt_to_ebitda")}}


PEER_COLUMNS = (("pe", mult), ("ev_ebitda", mult), ("ps", mult), ("p_fcf", mult), ("revenue_yoy", pct),
                ("gross_margin", pct), ("operating_margin", pct), ("roic", pct), ("net_debt_to_ebitda", mult))


def peers_section(f, number):
    peers = f.get("peers") or []
    out = [f"\n## {number}. Peer comparison", "Each company's last fiscal year, same method for all (* = this company)."]
    rows = []
    for p in [dict(own_row(f), status="self")] + peers:
        if p.get("status") == "no_data":
            rows.append([txt(p.get("symbol")), "no data (plan restriction or unknown ticker)"] + [""] * 9)
            continue
        symbol = txt(p.get("symbol"))
        rows.append([f"{symbol} *" if p.get("status") == "self" else symbol, money(p.get("market_cap"))]
                    + [fmt(p.get(k)) for k, fmt in PEER_COLUMNS])
    ok = [p for p in peers if p.get("status") == "ok"]
    if ok:
        rows.append(["Peer median", money(median([p.get("market_cap") for p in ok]))] +
                    [fmt(median([p.get(k) for p in ok])) for k, fmt in PEER_COLUMNS])
    out.append(table(["Ticker", "Mkt cap", "P/E", "EV/EBITDA", "P/S", "P/FCF", "Rev YoY", "Gross m.", "Op m.", "ROIC",
                      "ND/EBITDA"], rows))
    return out


def data_notes(f, calls):
    dq, px = f.get("data_quality") or {}, f.get("price") or {}
    out = ["\n## Data notes"]
    route = dq.get("route")
    if route and route.startswith("official"):
        out.append("- Data route: official FMP API.")
    elif route:
        out.append(f"- Data route: {one_line(route)}. Data is not served by FMP directly; spot-check key figures "
                   f"against company filings.")
    if px.get("source") == "quote":
        out.append(f"- Price from the latest quote at {px['time']} New York time." if px.get("time") else
                   "- Price from the latest quote.")
    else:
        out.append("- Price from the company profile, which is cached for up to a day (no current quote).")
    rates = f.get("rates")
    fixed = get(f, "models", "dcf", "inputs", "discount_rate", "method") == "fixed_default"
    if rates is None and get(f, "valuation", "vs_group") is None:
        out.append("- Treasury, sector and industry data skipped (--no-market).")
    elif rates and rates.get("treasury_10y") is not None:
        out.append(f"- Treasury yields as of {txt(rates.get('date'))} (FMP treasury-rates).")
        if rates.get("equity_risk_premium") is None:
            out.append("- US equity risk premium unavailable" +
                       (": DCF used the fixed default discount rate." if fixed else "."))
    else:
        missing = "Treasury yields" + (" and US equity risk premium" if get(rates, "equity_risk_premium") is None
                                       else "")
        out.append(f"- {missing} unavailable" + (": DCF used the fixed default discount rate." if fixed else "."))
    cm = dq.get("currency_mismatch")
    if cm:
        out.append(f"- Statements are in {cm.get('statements')} and the price in {cm.get('price')}: the multiples and "
                   f"yields mix the two currencies, and the DCF value per share is in {cm.get('statements')}.")
    if dq.get("restricted"):
        out.append(f"- Skipped (not in your FMP plan): {', '.join(one_line(r) for r in dq['restricted'])}")
    for e in dict.fromkeys(one_line(e) for e in dq.get("errors") or []):
        out.append(f"- Error: {e}")
    if calls is not None:
        out.append(f"- API calls: {calls[0]} network, {calls[1]} from cache.")
    out.append("- Source: Financial Modeling Prep. Computed figures are approximations; verify against filings before "
               "acting.")
    return out


def render(f, macro_md=None, calls=None):
    """The report of a fa-2.x document. macro_md: the rates & macro section's body; calls: (network, cache)."""
    if not str(f.get("contract") or "").startswith("fa-2"):
        raise ValueError(f"not a fa-2.x document (contract {f.get('contract')!r})")
    out = header(f) + statement_sections(f) + valuation_section(f) + forward_section(f) + group_section(f) + \
        quality_section(f) + dcf_section(f) + consensus_section(f)
    number = 11
    if f.get("peers"):
        out += peers_section(f, number)
        number += 1
    if macro_md:
        out += [f"\n## {number}. Rates & macro backdrop", macro_md.strip("\n")]
    out += data_notes(f, calls)
    return "\n".join(out)
