#!/usr/bin/env python3
"""
fa-2.0: the facts of one analysis, for other tools to read (the decision engine first).

Built from analyze.py's full result: the in-memory dict, or a saved `analyze.py --json` file, including files
saved by earlier versions, so old runs convert (`contract.py --facts saved.json` does the same):

  python facts.py saved.json               print the fa-2.0 document of a saved result
  python facts.py saved.json -o out.json   write it to a file instead

A file that is already fa-2.x is written back as it is. The document holds the statements, standard ratios,
multiples against their own history and the industry, the analysts' consensus as published, and the standard
models (Piotroski, Altman, DCF and reverse DCF). It holds no score, label, flag, price level, price target or
margin of safety: judgements belong to the decision engine. This module does not import score.py.

Conventions:
  per-period data   column arrays aligned with "period", oldest first; `ttm` holds the same keys for one period
  numbers           full precision; fractions are decimals (0.25 = 25%); money in the statement currency,
                    per-share DCF values and prices in the price currency
  null              missing; the block's "status" is "ok" or a code saying why not (codes only, never sentences)
  versions          "contract" stays the version key; 2.x only adds fields, renaming or removing one is fa-3.0;
                    method_version moves when a formula or a data check changes

contracts/fa-2.0.schema.json describes every field; tests/test_facts.py checks the shape, the absence of
judgement words, and that the score can be rebuilt from this document alone.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FACTS = "fa-2.0"
METHOD_VERSION = "2.0.0"

# statement line items per period: (fa-2.0 name, analyze.py name)
STATEMENT_FIELDS = (
    ("revenue", "revenue"), ("gross_profit", "gross_profit"), ("operating_income", "operating_income"),
    ("ebitda", "ebitda"), ("ebit", "ebit"), ("net_income", "net_income"), ("eps_diluted", "eps"),
    ("shares_diluted", "shares"), ("interest_expense", "interest_expense"), ("rnd", "rnd"),
    ("cash", "cash"), ("debt", "debt"), ("net_debt", "net_debt"), ("equity", "equity"),
    ("total_assets", "total_assets"), ("total_liabilities", "total_liabilities"),
    ("current_assets", "current_assets"), ("current_liabilities", "current_liabilities"),
    ("goodwill_intangibles", "goodwill_intangibles"), ("minority_interest", "minority_interest"),
    ("ocf", "ocf"), ("capex", "capex"), ("fcf", "fcf"), ("sbc", "sbc"), ("buybacks", "buybacks"),
    ("dividends", "dividends"), ("stock_issued", "stock_issued"),
)
# standard ratios per period (same names as analyze.py); formulas in references/metrics.md
METRIC_FIELDS = (
    "gross_margin", "operating_margin", "net_margin", "ebitda_margin", "fcf_margin", "rnd_pct",
    "roe", "roa", "roic", "current_ratio", "quick_ratio", "debt_to_equity", "net_debt_to_ebitda",
    "interest_coverage", "fcf_conversion", "sbc_pct", "capex_pct", "revenue_yoy", "eps_yoy", "shares_yoy",
)
MULTIPLES = ("pe", "ps", "pb", "ev_ebitda", "ev_sales", "p_fcf", "earnings_yield", "fcf_yield", "dividend_yield",
             "shareholder_yield")
HISTORY_MULTIPLES = ("pe", "ps", "pb", "ev_ebitda", "ev_sales", "p_fcf", "fcf_yield")
VS_HISTORY = ("pe", "ev_ebitda", "ps", "p_fcf", "pb")
CAGR_FIELDS = ("revenue", "gross_profit", "operating_income", "net_income", "eps", "fcf", "shares")
ESTIMATE_FIELDS = (("fy", "fy"), ("date", "date"), ("ended", "ended"), ("analysts", "analysts"),
                   ("eps_avg", "eps_avg"), ("eps_low", "eps_low"), ("eps_high", "eps_high"),
                   ("revenue_avg", "revenue_avg"), ("revenue_growth", "revenue_growth"),
                   ("ebitda_avg", "ebitda_avg"), ("pe_on_fy_eps", "forward_pe"))
BAND_STATS = ("p10", "p25", "median", "p75", "p90", "n")
HISTORY_PROBLEMS = ("share_basis", "price_jump")
PEER_FIELDS = ("market_cap", "pe", "ev_ebitda", "ps", "p_fcf", "revenue_yoy", "gross_margin", "operating_margin",
               "roe", "roic", "net_debt_to_ebitda")

# Metrics that mean little for a company type, as in analyze.py's sector notes; their values are still given.
NOT_MEANINGFUL = {
    "financial": ["gross_margin", "ev_ebitda", "ev_sales", "fcf", "dcf", "altman"],
    "fee_financial": ["altman", "current_ratio"],
    "reit": ["pe", "altman"],
    "utility": ["altman"],
}
# analyze.py's English texts -> codes (needed for files saved before these codes existed)
DCF_SKIPS = (("Financial-sector", "skipped_financial"), ("not positive", "fcf_not_positive"),
             ("inputs invalid", "invalid_inputs"))
PIOTROSKI_TESTS = {
    "ROA > 0": "roa_positive", "Operating cash flow > 0": "ocf_positive", "ROA improved": "roa_improved",
    "Cash flow > net income (accruals)": "ocf_above_net_income", "Long-term leverage fell": "leverage_fell",
    "Current ratio improved": "current_ratio_improved", "No net share dilution": "no_dilution",
    "Gross margin improved": "gross_margin_improved", "Asset turnover improved": "asset_turnover_improved",
}


def _num(x):
    """Plain float, or None for missing / non-numeric values (bools are not numbers here)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _int(x):
    """Counts: a whole number, or None."""
    v = _num(x)
    return int(v) if v is not None and v == int(v) else None


def _day(x):
    return str(x)[:10] if x else None


def _code(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or None


def _div(a, b):
    return a / b if a is not None and b else None


def _pos_div(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def _bands(r):
    """The forward-multiple block: forward_bands, or price_range in a result saved by v1.x."""
    return (r["forward_bands"] if "forward_bands" in r else r.get("price_range")) or {}


def _now_point(r):
    """Today's next-twelve-month figures: forward_bands.forward, or the "now" point among price_range.forward's
    points (v1.x)."""
    fwd = _bands(r).get("forward")
    if isinstance(fwd, list):
        return next((p for p in fwd if p.get("at") == "now"), None)
    return fwd


# ---------------------------------------------------------------------------- dates
def as_of(r):
    """(date, basis): the quote's date, else the last close in the price history, else the run date."""
    if r.get("price_time"):
        return _day(r["price_time"]), "quote"
    # the last close of the past year; a result saved by v1.x has it as the end of its 52-week range
    last = r["last_close"] if "last_close" in r else ((r.get("price_range") or {}).get("week52") or {}).get("to")
    if last:
        return _day(last), "last_close"
    return _day(r.get("as_of")), "run_date"


def statements_through(r):
    """End date of the latest period in the statements: the TTM quarter, else the latest fiscal year."""
    ttm = r.get("ttm")
    if ttm and ttm.get("date"):
        return _day(ttm["date"])
    years = r.get("years") or []
    return _day(years[-1].get("date")) if years else None


# ---------------------------------------------------------------------------- blocks
def _company(r):
    p, c, years = r.get("profile") or {}, r.get("current") or {}, r.get("years") or []
    kind = r.get("sector_kind") or "general"
    return {"name": p.get("companyName"), "exchange": p.get("exchange"), "sector": p.get("sector"),
            "industry": p.get("industry"), "kind": kind, "not_meaningful": list(NOT_MEANINGFUL.get(kind, [])),
            "statement_currency": years[-1].get("currency") if years else None, "beta": _num(p.get("beta")),
            "market_cap": _num(c.get("market_cap")), "enterprise_value": _num(c.get("enterprise_value")),
            "is_etf": bool(p.get("isEtf")), "is_adr": bool(p.get("isAdr"))}


def _period_values(y):
    out = {k: _num(y.get(src)) for k, src in STATEMENT_FIELDS}
    out.update({k: _num(y.get(k)) for k in METRIC_FIELDS})
    return out


def _statements(years):
    cols = {"period": [y.get("label") for y in years], "end": [_day(y.get("date")) for y in years],
            "currency": [y.get("currency") for y in years]}
    cols.update({k: [_num(y.get(src)) for y in years] for k, src in STATEMENT_FIELDS})
    return cols


def _metrics(years):
    return {k: [_num(y.get(k)) for y in years] for k in METRIC_FIELDS}


def _ttm(t):
    if not t:
        return None
    return {"period": "TTM", "end": _day(t.get("date")), "currency": t.get("currency"), **_period_values(t)}


def _growth(r):
    years = r.get("years") or []
    cg = r.get("cagr") or {}
    return {"from": years[0].get("label") if years else None, "to": years[-1].get("label") if years else None,
            "years": max(len(years) - 1, 0), "cagr": {k: _num(cg.get(k)) for k in CAGR_FIELDS}}


def _open_estimates(r):
    return [e for e in (r.get("analyst") or {}).get("estimates") or [] if not e.get("ended")]


def _forward(r):
    """Forward multiples now: on each of the next two fiscal years' consensus EPS, and on next-twelve-month EPS
    and EBITDA (the two fiscal years blended by the time left in the one in progress)."""
    cur, price = r.get("current") or {}, _num((r.get("current") or {}).get("price"))
    est = _open_estimates(r)
    now = _now_point(r)
    out = {"fy1": None, "pe_fy1": None, "fy2": None, "pe_fy2": None, "pe_ntm": None, "ev_ebitda_ntm": None,
           "ntm": None}
    for i, e in enumerate(est[:2], 1):
        out[f"fy{i}"], out[f"pe_fy{i}"] = e.get("fy"), _num(e.get("forward_pe"))
    if now:
        eps, ebitda = _num(now.get("eps")), _num(now.get("ebitda"))
        out["ntm"] = {"eps": eps, "eps_low": _num(now.get("eps_low")), "eps_high": _num(now.get("eps_high")),
                      "ebitda": ebitda, "fys": list(now.get("uses") or []), "weight": _num(now.get("weight"))}
        out["pe_ntm"] = _pos_div(price, eps)
        # as analyze.py computes the band's "now": today's market cap on its share count, plus the net debt and
        # minority interest of the valuation basis period
        basis, mcap = r.get("basis") or {}, _num(cur.get("market_cap"))
        shares, nd = _div(mcap, price), _num(basis.get("net_debt"))
        if (r.get("sector_kind") or "general") != "financial" and nd is not None and shares:
            out["ev_ebitda_ntm"] = _pos_div(price * shares + nd + (_num(basis.get("minority_interest")) or 0.0), ebitda)
    return out


def _band(b, why_missing):
    """One forward multiple's 3-year daily distribution: statistics only, never turned into prices.
    status now_not_positive: the distribution exists, but today's next-twelve-month figure is not positive."""
    out = {"status": why_missing, "now": None, "pctile": None, **{k: None for k in BAND_STATS}}
    if not b:
        return out
    out.update({k: (_int if k == "n" else _num)(b.get(k)) for k in BAND_STATS})
    out["now"], out["pctile"] = _num(b.get("now")), _num(b.get("now_pct"))
    out["status"] = "ok" if out["pctile"] is not None else "now_not_positive"
    return out


def _forward_band(r):
    pr = _bands(r)
    pe, ev = pr.get("pe_band"), pr.get("ev_band")
    if len(_open_estimates(r)) < 2:
        status = "no_estimates"
    elif pr.get("band_problem") in HISTORY_PROBLEMS:
        status = pr["band_problem"]
    elif pe or ev:
        status = "ok"
    else:
        status = "short_history"
    first = pe or ev or {}
    pe_why = ev_why = status
    if status == "ok":  # one of the two exists: say why the other is missing
        cur, basis = r.get("current") or {}, r.get("basis") or {}
        shares = _div(_num(cur.get("market_cap")), _num(cur.get("price")))
        ebitda = _num((_forward(r).get("ntm") or {}).get("ebitda"))
        pe_why = "short_history"
        ev_why = ("not_applicable" if (r.get("sector_kind") or "general") == "financial"
                  or _num(basis.get("net_debt")) is None or not shares else
                  "ebitda_not_positive" if not ebitda or ebitda <= 0 else "short_history")
    return {"status": status, "lookback_years": _int(pr.get("lookback_years")), "from": _day(first.get("from")),
            "to": _day(first.get("to")), "history_basis": "reported_then_consensus",
            "pe": _band(pe, pe_why), "ev_ebitda": _band(ev, ev_why)}


def _vs_own_history(r):
    pr = _bands(r)
    # files saved before trailing_problem existed: the forward band's check was the only one
    problem = pr["trailing_problem"] if "trailing_problem" in pr else pr.get("band_problem")
    hc = r.get("history_compare") or {}
    out = {"status": problem if problem in HISTORY_PROBLEMS else "ok", "basis": "fiscal_year_end_close"}
    for m in VS_HISTORY:
        h = hc.get(m)
        out[m] = None if not h else {"now": _num(h.get("current")), "median": _num(h.get("median")),
                                     "min": _num(h.get("min")), "max": _num(h.get("max")), "n": _int(h.get("n")),
                                     "vs_median": _num(h.get("vs_median"))}
    return out


def _history(r):
    hist = r.get("valuation_history") or []
    out = {"period": [h.get("label") for h in hist], "date": [_day(h.get("date")) for h in hist],
           "price": [_num(h.get("price")) for h in hist]}
    out.update({k: [_num(h.get(k)) for h in hist] for k in HISTORY_MULTIPLES})
    return out


def _group(st, name, premium):
    st = st or {}
    return {"name": name, "status": st.get("status") or "unavailable", "date": _day(st.get("date")),
            "pe": _num(st.get("current")), "latest_value": _num(st.get("latest_value")),
            "pe_pctile": _num(st.get("percentile")), "median": _num(st.get("median")), "min": _num(st.get("min")),
            "max": _num(st.get("max")), "since": _day(st.get("since")), "n": _int(st.get("n")),
            "year_ago": _num(st.get("year_ago")), "premium": _num(premium)}


def _vs_group(r):
    """FMP's aggregate P/E of the industry and sector (one exchange's listed companies) and the company's P/E
    against them; null when the market data was skipped (--no-market)."""
    sc = (r.get("market") or {}).get("sector")
    if not sc:
        return None
    return {"exchange": sc.get("exchange"), "company_pe": _num(sc.get("company_pe")),
            "industry": _group(sc.get("industry_pe"), sc.get("industry"), sc.get("vs_industry")),
            "sector": _group(sc.get("sector_pe"), sc.get("sector"), sc.get("vs_sector"))}


def _valuation(r):
    cur = r.get("current") or {}
    return {"now": {k: _num(cur.get(k)) for k in MULTIPLES}, "history": _history(r),
            "vs_own_history": _vs_own_history(r), "forward": _forward(r), "forward_band": _forward_band(r),
            "vs_group": _vs_group(r)}


def _rates(r):
    m = r.get("market") or {}
    rates, erp = m.get("rates"), _num(m.get("erp"))
    rf = _num((((rates or {}).get("points") or {}).get("now") or {}).get("10Y"))
    if rf is None and erp is None:
        return None
    return {"date": _day((rates or {}).get("date")) if rf is not None else None, "treasury_10y": rf,
            "equity_risk_premium": erp}


def _discount(d, capm):
    """The DCF discount rate and where it came from. The CAPM fields are null for the other methods."""
    src = str(d.get("discount_source") or "")
    out = {"value": _num(d.get("discount_rate")), "method": None, "reason": None, "rf": None, "rf_date": None,
           "beta": None, "beta_source": None, "erp": None, "raw": None, "clamped": None}
    if src == "user input":
        out["method"] = "user"
    elif src.startswith("CAPM"):  # 10Y Treasury + beta x US equity risk premium, kept within 7-13%
        capm = capm or {}
        out.update(method="capm", rf=_num(capm.get("rf")), rf_date=_day(capm.get("rf_date")),
                   beta=_num(capm.get("beta")),
                   beta_source="profile" if capm.get("beta_source") == "profile" else "default_1",
                   erp=_num(capm.get("erp")), raw=_num(capm.get("raw")), clamped=bool(capm.get("clamped")))
    else:
        out.update(method="fixed_default", reason="no_market" if "--no-market" in src else "rates_unavailable")
    return out


def _dcf(r):
    d = r.get("dcf") or {}
    if d.get("skipped") or _num(d.get("value_per_share")) is None:
        code = (next((c for k, c in DCF_SKIPS if k in d["skipped"]), _code(d["skipped"])) if d.get("skipped")
                else "unavailable")
        return ({"status": code, "inputs": None, "value_per_share": None, "low": None, "high": None,
                 "terminal_value_share": None, "sensitivity": None},
                {"status": "no_dcf", "implied_growth_1_5": None, "discount_rate": None})
    growth_src = str(d.get("growth_source") or "")
    inputs = {
        "fcf_start": _num(d.get("fcf_start")),
        # the FCF of the period in periods.valuation_basis (latest fiscal year or TTM), or a 3-year average
        "fcf_start_basis": ("average_3y" if str(d.get("fcf_start_basis") or "").startswith("average")
                            else "valuation_basis"),
        "growth_1_5": _num(d.get("growth_1_5")),
        "growth_source": ("user" if growth_src == "user input" else
                          "revenue_cagr_clamped_0_15" if growth_src.startswith("historical revenue CAGR") else
                          "default_5pct" if growth_src.startswith("default") else _code(growth_src)),
        "terminal_growth": _num(d.get("terminal_growth")),
        "discount_rate": _discount(d, (r.get("market") or {}).get("capm")),
        "net_debt": _num(d.get("net_debt")), "shares": _num(d.get("shares")),
    }
    vps = _num(d["value_per_share"])
    dcf = {"status": "ok" if vps > 0 else "value_not_positive", "inputs": inputs, "value_per_share": vps,
           "low": _num(d.get("range_low")), "high": _num(d.get("range_high")),
           "terminal_value_share": _num(d.get("terminal_value_share")),
           "sensitivity": {"discount_rates": [_num(x) for x in d.get("grid_rates") or []],
                           "growth_1_5": [_num(x) for x in d.get("grid_growths") or []],
                           "value_per_share": [[_num(v) for v in row] for row in d.get("grid") or []]}}
    ig, note = _num(d.get("implied_growth")), str(d.get("implied_growth_note") or "")
    status = ("ok" if ig is not None else "below_range" if note.startswith("below") else
              "above_range" if note.startswith("above") else "not_computable")
    # the solver searches implied growth between -50% and +100% a year (below_range / above_range)
    return dcf, {"status": status, "implied_growth_1_5": ig, "discount_rate": inputs["discount_rate"]["value"]}


def _models(r):
    kind = r.get("sector_kind") or "general"
    pio = r.get("piotroski")
    piotroski = None if not pio else {
        "fy": pio.get("year"), "score": _int(pio.get("score")), "out_of": _int(pio.get("out_of")),
        "tests": [{"id": PIOTROSKI_TESTS.get(t.get("test")) or _code(t.get("test")), "pass": t.get("pass")}
                  for t in pio.get("tests") or []]}
    alt = r.get("altman")
    altman = {"status": "unavailable" if not alt else ("ok" if kind == "general" else "not_meaningful"),
              "fy": (alt or {}).get("year"), "z": _num((alt or {}).get("z")), "z_zone": (alt or {}).get("z_zone"),
              "z2": _num((alt or {}).get("z_double_prime")), "z2_zone": (alt or {}).get("z2_zone")}
    dcf, reverse = _dcf(r)
    return {"piotroski": piotroski, "altman": altman, "dcf": dcf, "reverse_dcf": reverse}


def _consensus(r):
    a = r.get("analyst") or {}
    kinds = {"fy": lambda v: v, "date": _day, "ended": bool, "analysts": _int}
    rows = [{k: kinds.get(k, _num)(e.get(src)) for k, src in ESTIMATE_FIELDS} for e in a.get("estimates") or []]

    def gap(key):
        g = a.get(key)
        return None if not g else {"estimate": _num(g.get("estimate")), "reported": _num(g.get("reported")),
                                   "gap": _num(g.get("gap"))}
    fy = next((a[k].get("fy") for k in ("eps_basis", "ebitda_basis", "revenue_basis") if a.get(k)), None)
    return {"estimates": rows,
            "vs_reported": {"fy": fy, "eps": gap("eps_basis"), "ebitda": gap("ebitda_basis"),
                            "revenue": gap("revenue_basis")}}


def _peers(r):
    """Each peer's latest fiscal year (--peers); null when there are none."""
    out = []
    for p in r.get("peers") or []:
        ok = "error" not in p
        out.append({"symbol": p.get("symbol"), "status": "ok" if ok else "no_data",
                    "name": p.get("name") if ok else None, "fy": p.get("fy") if ok else None,
                    **{k: _num(p.get(k)) if ok else None for k in PEER_FIELDS}})
    return out or None


def _data_quality(r):
    years, meta = r.get("years") or [], r.get("meta") or {}
    stmt = years[-1].get("currency") if years else None
    px = (r.get("profile") or {}).get("currency")
    return {"fiscal_years": len(years), "ttm": bool(r.get("ttm")),
            "currency_mismatch": {"statements": stmt, "price": px} if stmt and px and stmt != px else None,
            "restricted": sorted(meta.get("restricted") or []), "errors": sorted(meta.get("errors") or []),
            "route": (meta.get("connection") or {}).get("route")}


# ---------------------------------------------------------------------------- document
def _is_facts(r):
    return str(r.get("contract") or "").startswith("fa-2")


def _is_result(r):
    """A full result as analyze.py --json of v1.x saved it (or an internal result)."""
    return isinstance(r.get("symbol"), str) and isinstance(r.get("years"), list) and bool(r["years"])


def build(r):
    """The fa-2.0 document of one analyze.py result (the internal result or a loaded v1.x --json file). A document
    that is already fa-2.x is returned as it is."""
    if _is_facts(r):
        return r
    years = r.get("years") or []
    day, basis = as_of(r)
    cur, p = r.get("current") or {}, r.get("profile") or {}
    return {
        "contract": FACTS,
        "method_version": METHOD_VERSION,
        "ticker": r.get("symbol"),
        "generated_at": r.get("generated_at") or _day(r.get("as_of")),
        "as_of": day,
        "as_of_basis": basis,
        "statements_through": statements_through(r),
        "price": {"value": _num(cur.get("price")), "currency": p.get("currency"),
                  "source": "quote" if r.get("price_time") is not None else "profile",
                  "time": r.get("price_time") or None},
        "company": _company(r),
        "periods": {"fiscal_years": [y.get("label") for y in years],
                    "ttm_through": _day((r.get("ttm") or {}).get("date")),
                    "valuation_basis": (r.get("basis") or {}).get("label")},
        "statements": _statements(years),
        "metrics": _metrics(years),
        "ttm": _ttm(r.get("ttm")),
        "growth": _growth(r),
        "valuation": _valuation(r),
        "rates": _rates(r),
        "models": _models(r),
        "consensus": _consensus(r),
        "peers": _peers(r),
        "data_quality": _data_quality(r),
    }


def dumps(f):
    return json.dumps(f, indent=2, ensure_ascii=False)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=f"Convert a full result saved by analyze.py --json (v1.x) to {FACTS}")
    ap.add_argument("saved_json")
    ap.add_argument("-o", "--out", default=None, help="write the document to this file instead of stdout")
    a = ap.parse_args(argv)
    try:
        r = json.loads(Path(a.saved_json).read_text(encoding="utf-8"))
        if not isinstance(r, dict) or not (_is_facts(r) or _is_result(r)):
            raise ValueError(f"not a full result saved by analyze.py --json, nor an {FACTS} document")
        text = dumps(build(r))
    except (OSError, ValueError, LookupError, TypeError, AttributeError, ArithmeticError) as e:
        print(f"Cannot convert {a.saved_json} to {FACTS}: {e}", file=sys.stderr)
        return 1
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"({FACTS} written to {a.out})", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
