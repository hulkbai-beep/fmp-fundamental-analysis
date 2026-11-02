#!/usr/bin/env python3
"""
Fundamental analysis of one stock from FMP financial statements: the facts and the standard models.

All arithmetic happens here so the model only has to interpret the numbers. Ratios are computed from the raw
income / balance-sheet / cash-flow statements, so the analysis works on FMP plans that only include annual
fundamentals. The result is one document, fa-2.0 (facts.py, contracts/fa-2.0.schema.json): statements, ratios,
multiples against their own history and the industry, the analysts' consensus and the standard models
(Piotroski, Altman, DCF, reverse DCF). It holds no score, flag, price level or price target: decisions are left
to the user or the decision engine.

Usage:
  python analyze.py AAPL
  python analyze.py AAPL --peers MSFT,GOOGL,AMZN --json aapl.json
  python analyze.py AAPL --discount 0.10 --growth 0.06 --fcf-base avg3
  python analyze.py AAPL --macro

Options:
  --years N          fiscal years of history to request (default 5; Starter plan = 5)
  --peers LIST       comma-separated peer tickers, or "none" (default: FMP stock-peers)
  --max-peers N      max auto peers (default 5)
  --discount R       DCF discount rate (default: CAPM = 10Y Treasury + beta x US equity risk
                     premium, kept within 7-13%; 0.09 if rates data is unavailable)
  --terminal G       DCF terminal growth (default 0.025)
  --growth G         DCF growth for years 1-5 (default: historical revenue CAGR, clamped 0-15%)
  --fcf-base MODE    latest | avg3   starting FCF for the DCF (default latest)
  --no-ttm           skip trailing-twelve-month data (saves 3 API calls)
  --macro            add the rates & macro backdrop (Treasury curve, Fed funds, CPI, jobs, key releases,
                     and the stock's returns against its industry, sector and the S&P 500)
  --no-market        skip Treasury / industry / sector data (fixed 9% discount, no industry and sector P/E;
                     cannot be combined with --macro)
  --json PATH        also write the fa-2.0 document to a file
  --facts PATH       the same (kept for tools that pass it)
  --refresh          ignore the local cache

Kept for one version: --contract PATH writes the fa-2.0 document as well (the fa-1.1 contract was removed in
v2.0); --iv and --no-insider are accepted and ignored. Each prints a note to stderr.

stdout is the markdown report alone (facts_report.py); notes go to stderr. Exit codes: 0 ok, 1 FMP error,
2 API-key problem. `python facts.py saved.json [-o out.json]` converts a full result saved by `--json` of v1.x.
Requests run in parallel (FMP_MAX_WORKERS, default 6; set 1 to fetch one at a time).
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fmp_client import FMPClient, FMPError, InvalidKey, RestrictedEndpoint  # noqa: E402
import facts as F  # noqa: E402
import macro as M  # noqa: E402
import facts_report as R  # noqa: E402
from symbols import normalize_symbol  # noqa: E402

FINANCIAL_SECTORS = {"financial services", "financials", "financial"}
REVENUE_BASIS_GAP = 0.05  # analysts' revenue for the last reported year this far off the reported figure: another basis
# Fee-based financial industries (exchanges, data providers, insurance brokers) run on cash flow like other
# companies, so they get the general analysis rather than the bank / insurer one.
FEE_FINANCIAL_INDUSTRIES = ("data & stock exchanges", "financial data", "stock exchanges", "insurance brokers",
                            "insurance - brokers")


# ============================================================ numeric helpers
def num(d, *keys):
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and math.isfinite(v):
            return float(v)
    return None


def div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def pos_div(a, b):
    """a / b only when b > 0 (multiples on negative denominators are meaningless)."""
    if a is None or b is None or b <= 0:
        return None
    return a / b


def yoy(cur, prev):
    if cur is None or prev is None or prev <= 0:
        return None
    return cur / prev - 1


def cagr(first, last, years):
    if first is None or last is None or years <= 0 or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1


def mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def absval(v):
    return abs(v) if v is not None else None


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ============================================================ statement parsing
def year_key(row):
    return str(row.get("fiscalYear") or row.get("calendarYear") or str(row.get("date", ""))[:4])


def extract(inc, bs, cf):
    """Pull the raw line items we need, tolerating FMP field-name variants."""
    rev = num(inc, "revenue")
    gp = num(inc, "grossProfit")
    if gp is None and rev is not None and num(inc, "costOfRevenue") is not None:
        gp = rev - num(inc, "costOfRevenue")
    op = num(inc, "operatingIncome")
    da = num(inc, "depreciationAndAmortization")
    if da is None:
        da = num(cf, "depreciationAndAmortization")
    ebitda = num(inc, "ebitda")
    if ebitda is None and op is not None and da is not None:
        ebitda = op + da
    ebit = num(inc, "ebit")
    if ebit is None:
        ebit = op

    cash = num(bs, "cashAndShortTermInvestments")
    if cash is None and bs:
        parts = [num(bs, "cashAndCashEquivalents"), num(bs, "shortTermInvestments")]
        cash = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None
    debt = num(bs, "totalDebt")
    if debt is None and bs:
        parts = [num(bs, "shortTermDebt"), num(bs, "longTermDebt")]
        debt = sum(p for p in parts if p is not None) if any(p is not None for p in parts) else None

    ocf = num(cf, "operatingCashFlow", "netCashProvidedByOperatingActivities")
    capex = absval(num(cf, "capitalExpenditure", "investmentsInPropertyPlantAndEquipment"))
    fcf = num(cf, "freeCashFlow")
    if fcf is None and ocf is not None and capex is not None:
        fcf = ocf - capex

    return {
        "revenue": rev,
        "gross_profit": gp,
        "operating_income": op,
        "ebitda": ebitda,
        "ebit": ebit,
        "net_income": num(inc, "netIncome", "bottomLineNetIncome"),
        "eps": num(inc, "epsDiluted", "epsdiluted", "eps"),
        "shares": num(inc, "weightedAverageShsOutDil", "weightedAverageShsOut"),
        "interest_expense": num(inc, "interestExpense"),
        "pretax_income": num(inc, "incomeBeforeTax"),
        "tax": num(inc, "incomeTaxExpense"),
        "rnd": num(inc, "researchAndDevelopmentExpenses"),
        "cash": cash,
        "current_assets": num(bs, "totalCurrentAssets"),
        "current_liabilities": num(bs, "totalCurrentLiabilities"),
        "inventory": num(bs, "inventory"),
        "total_assets": num(bs, "totalAssets"),
        "total_liabilities": num(bs, "totalLiabilities"),
        "equity": num(bs, "totalStockholdersEquity", "totalEquity"),
        "debt": debt,
        "long_term_debt": num(bs, "longTermDebt"),
        "retained_earnings": num(bs, "retainedEarnings"),
        "minority_interest": num(bs, "minorityInterest") or 0.0,
        "goodwill_intangibles": num(bs, "goodwillAndIntangibleAssets"),
        "ocf": ocf,
        "capex": capex,
        "fcf": fcf,
        "sbc": num(cf, "stockBasedCompensation"),
        "buybacks": absval(num(cf, "commonStockRepurchased")),
        "dividends": absval(num(cf, "commonDividendsPaid", "netDividendsPaid", "dividendsPaid")),
        "stock_issued": absval(num(cf, "commonStockIssued", "commonStockIssuance")),
    }


def derive(y, p):
    """Ratios for one period; p is the prior fiscal year (or None)."""
    rev, ni = y["revenue"], y["net_income"]
    y["gross_margin"] = div(y["gross_profit"], rev)
    y["operating_margin"] = div(y["operating_income"], rev)
    y["net_margin"] = div(ni, rev)
    y["ebitda_margin"] = div(y["ebitda"], rev)
    y["fcf_margin"] = div(y["fcf"], rev)
    y["rnd_pct"] = div(y["rnd"], rev)

    eq_avg = mean([y["equity"], p["equity"] if p else None])
    y["negative_equity"] = y["equity"] is not None and y["equity"] <= 0
    y["roe"] = pos_div(ni, eq_avg) if not y["negative_equity"] else None
    y["roa"] = pos_div(ni, mean([y["total_assets"], p["total_assets"] if p else None]))

    rate = div(y["tax"], y["pretax_income"]) if (y["pretax_income"] or 0) > 0 else None
    y["tax_rate"] = rate if rate is not None and 0 <= rate <= 0.5 else 0.21
    nopat = y["operating_income"] * (1 - y["tax_rate"]) if y["operating_income"] is not None else None
    ic = None
    if None not in (y["debt"], y["equity"], y["cash"]):
        ic = y["debt"] + y["equity"] - y["cash"]
    y["invested_capital"] = ic
    y["roic"] = pos_div(nopat, mean([ic, p.get("invested_capital") if p else None]))

    y["current_ratio"] = div(y["current_assets"], y["current_liabilities"])
    if y["current_assets"] is not None:
        y["quick_ratio"] = div(y["current_assets"] - (y["inventory"] or 0), y["current_liabilities"])
    else:
        y["quick_ratio"] = None
    y["debt_to_equity"] = pos_div(y["debt"], y["equity"])
    y["net_debt"] = (y["debt"] - y["cash"]) if None not in (y["debt"], y["cash"]) else None
    y["net_debt_to_ebitda"] = pos_div(y["net_debt"], y["ebitda"])
    y["interest_coverage"] = pos_div(y["ebit"], y["interest_expense"])
    y["fcf_conversion"] = pos_div(y["fcf"], ni)
    y["sbc_pct"] = div(y["sbc"], rev)
    y["capex_pct"] = div(y["capex"], rev)

    for k, src in (("revenue_yoy", "revenue"), ("eps_yoy", "eps"), ("shares_yoy", "shares")):
        y[k] = yoy(y[src], p[src]) if p else None
    return y


def build_years(inc_rows, bs_rows, cf_rows):
    bs_by_date = {r.get("date"): r for r in bs_rows}
    bs_by_fy = {year_key(r): r for r in bs_rows}
    cf_by_date = {r.get("date"): r for r in cf_rows}
    cf_by_fy = {year_key(r): r for r in cf_rows}
    years = []
    for inc in inc_rows:
        d, fy = inc.get("date"), year_key(inc)
        bs = bs_by_date.get(d) or bs_by_fy.get(fy) or {}
        cf = cf_by_date.get(d) or cf_by_fy.get(fy) or {}
        y = extract(inc, bs, cf)
        y["date"], y["fy"], y["label"] = str(d)[:10], fy, f"FY{fy}"
        y["currency"] = inc.get("reportedCurrency")
        years.append(y)
    for i, y in enumerate(years):
        derive(y, years[i - 1] if i else None)
    return years


def build_ttm(qi, qc, qb):
    """TTM figures from the last 4 quarterly income / cash-flow statements and the latest balance sheet."""
    if len(qi) < 4 or len(qc) < 4 or not qb:
        return None

    def summed(rows):
        out = {}
        for r in rows:
            for k, v in r.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    out[k] = out.get(k, 0.0) + v
        return out

    inc_sum = summed(qi)
    inc_sum["weightedAverageShsOutDil"] = num(qi[-1], "weightedAverageShsOutDil", "weightedAverageShsOut")
    inc_sum.pop("weightedAverageShsOut", None)
    t = extract(inc_sum, qb[-1], summed(qc))
    t["date"] = str(qi[-1].get("date", ""))[:10]
    t["fy"], t["label"], t["currency"] = "TTM", "TTM", qi[-1].get("reportedCurrency")
    return derive(t, None)


# ============================================================ prices & valuation
def price_at(series, date):
    """Last close on or before `date` from a sorted [(date, price)] list."""
    if not series:
        return None
    idx = bisect.bisect_right([d for d, _ in series], date) - 1
    return series[idx][1] if idx >= 0 else None


def multiples(price, mcap, y):
    ev = None
    if None not in (mcap, y["debt"], y["cash"]):
        ev = mcap + y["debt"] - y["cash"] + (y["minority_interest"] or 0)
    return {
        "price": price,
        "market_cap": mcap,
        "enterprise_value": ev,
        "pe": pos_div(mcap, y["net_income"]),
        "ps": pos_div(mcap, y["revenue"]),
        "pb": pos_div(mcap, y["equity"]),
        "ev_ebitda": pos_div(ev, y["ebitda"]),
        "ev_sales": pos_div(ev, y["revenue"]),
        "p_fcf": pos_div(mcap, y["fcf"]),
        "earnings_yield": div(y["net_income"], mcap),
        "fcf_yield": div(y["fcf"], mcap),
        "dividend_yield": div(y["dividends"] or 0.0, mcap),
        "shareholder_yield": div((y["dividends"] or 0.0) + (y["buybacks"] or 0.0)
                                 - (y["stock_issued"] or 0.0), mcap),
    }


def valuation_history(years, series):
    hist = []
    for y in years:
        p = price_at(series, y["date"])
        if p is None or not y["shares"]:
            continue
        m = multiples(p, p * y["shares"], y)
        m["label"], m["date"] = y["label"], y["date"]
        hist.append(m)
    return hist


def compare_to_history(current, hist, keys=("pe", "ev_ebitda", "ps", "p_fcf", "pb")):
    out = {}
    for k in keys:
        vals = [h[k] for h in hist if h.get(k) is not None and h[k] > 0]
        cur = current.get(k)
        if not vals:
            out[k] = {"current": cur, "median": None, "min": None, "max": None,
                      "vs_median": None, "n": 0}
            continue
        med = statistics.median(vals)
        out[k] = {
            "current": cur, "median": med, "min": min(vals), "max": max(vals), "n": len(vals),
            "vs_median": (cur / med - 1) if cur is not None else None,
        }
    return out


# ============================================================ quality scores
def piotroski(years):
    if len(years) < 2:
        return None
    c, p = years[-1], years[-2]
    pp = years[-3] if len(years) >= 3 else None
    ta_begin_c = p["total_assets"] or c["total_assets"]
    ta_begin_p = (pp["total_assets"] if pp else None) or p["total_assets"]
    roa_c, roa_p = div(c["net_income"], ta_begin_c), div(p["net_income"], ta_begin_p)
    lev_c, lev_p = div(c["long_term_debt"], c["total_assets"]), div(p["long_term_debt"], p["total_assets"])
    at_c, at_p = div(c["revenue"], ta_begin_c), div(p["revenue"], ta_begin_p)

    def test(name, a, b, op):
        if a is None or b is None:
            return {"test": name, "pass": None}
        return {"test": name, "pass": bool(op(a, b))}

    tests = [
        test("ROA > 0", roa_c, 0, lambda a, b: a > b),
        test("Operating cash flow > 0", c["ocf"], 0, lambda a, b: a > b),
        test("ROA improved", roa_c, roa_p, lambda a, b: a > b),
        test("Cash flow > net income (accruals)", c["ocf"], c["net_income"], lambda a, b: a > b),
        test("Long-term leverage fell", lev_c, lev_p, lambda a, b: a < b or (a == 0 and b == 0)),
        test("Current ratio improved", c["current_ratio"], p["current_ratio"], lambda a, b: a > b),
        test("No net share dilution", c["shares"], p["shares"], lambda a, b: a <= b * 1.005),
        test("Gross margin improved", c["gross_margin"], p["gross_margin"], lambda a, b: a > b),
        test("Asset turnover improved", at_c, at_p, lambda a, b: a > b),
    ]
    scored = [t for t in tests if t["pass"] is not None]
    return {"year": c["label"], "score": sum(1 for t in scored if t["pass"]),
            "out_of": len(scored), "tests": tests}


def altman(y, mcap):
    ta, tl = y["total_assets"], y["total_liabilities"]
    if not ta or not tl or None in (y["current_assets"], y["current_liabilities"],
                                    y["retained_earnings"], y["ebit"], y["revenue"]):
        return None
    x1 = (y["current_assets"] - y["current_liabilities"]) / ta
    x2 = y["retained_earnings"] / ta
    x3 = y["ebit"] / ta
    x5 = y["revenue"] / ta
    out = {"year": y["label"]}
    if mcap:
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * (mcap / tl) + 1.0 * x5
        out["z"] = z
        out["z_zone"] = "safe" if z > 2.99 else ("grey" if z >= 1.81 else "distress")
    if y["equity"] is not None:
        z2 = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * (y["equity"] / tl)
        out["z_double_prime"] = z2
        out["z2_zone"] = "safe" if z2 > 2.6 else ("grey" if z2 >= 1.1 else "distress")
    return out


# ============================================================ DCF
def dcf_value(fcf0, g1, gt, r, net_debt, minority, shares):
    """Years 1-5 grow at g1, years 6-10 fade linearly to gt, then Gordon growth."""
    if r <= gt or fcf0 is None or fcf0 <= 0 or not shares:
        return None
    pv, f = 0.0, fcf0
    for t in range(1, 11):
        g = g1 if t <= 5 else g1 + (gt - g1) * (t - 5) / 5
        f *= 1 + g
        pv += f / (1 + r) ** t
    pv_tv = f * (1 + gt) / (r - gt) / (1 + r) ** 10
    equity = pv + pv_tv - (net_debt or 0) - (minority or 0)
    return {"per_share": equity / shares, "tv_share": pv_tv / (pv + pv_tv)}


def reverse_dcf(fcf0, gt, r, net_debt, minority, shares, price):
    def f(g):
        v = dcf_value(fcf0, g, gt, r, net_debt, minority, shares)
        return None if v is None else v["per_share"] - price
    lo, hi = -0.5, 1.0
    flo, fhi = f(lo), f(hi)
    if flo is None or fhi is None:
        return None, "not computable"
    if flo > 0:
        return None, "below -50%/yr (price is below even a shrinking-FCF value)"
    if fhi < 0:
        return None, "above 100%/yr"
    for _ in range(80):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2, None


def run_dcf(years, basis, cur, args, rev_cagr, sector_kind, r, r_source):
    if sector_kind == "financial":
        return {"skipped": "Financial-sector company: FCF-based DCF is not meaningful (use P/B, ROE, P/E)."}
    if args.fcf_base == "avg3":
        fcf0 = mean([y["fcf"] for y in years[-3:]])
        base_label = "average FCF of last 3 fiscal years"
    else:
        fcf0 = basis["fcf"]
        base_label = f"{basis['label']} FCF"
    if fcf0 is None or fcf0 <= 0:
        return {"skipped": f"Starting FCF ({base_label}) is not positive; DCF not applicable."}
    price, mcap = cur["price"], cur["market_cap"]
    shares = div(mcap, price) or basis["shares"]
    if args.growth is not None:
        g1, g_src = args.growth, "user input"
    elif rev_cagr is not None:
        g1, g_src = clamp(rev_cagr, 0.0, 0.15), "historical revenue CAGR, clamped to 0-15%"
    else:
        g1, g_src = 0.05, "default (no usable revenue history)"
    gt = args.terminal
    nd, mi = basis["net_debt"], basis["minority_interest"]
    base = dcf_value(fcf0, g1, gt, r, nd, mi, shares)
    if base is None:
        return {"skipped": "DCF inputs invalid (discount rate must exceed terminal growth)."}
    rs = [round(r + d, 4) for d in (-0.02, -0.01, 0, 0.01, 0.02) if r + d > gt + 0.005]
    gs = [g1 + d for d in (-0.04, -0.02, 0, 0.02, 0.04)]  # unrounded, so the centre cell equals the base case
    grid = [[(dcf_value(fcf0, g, gt, rr, nd, mi, shares) or {}).get("per_share") for g in gs] for rr in rs]
    inner = [v for i, row in enumerate(grid) for j, v in enumerate(row)
             if v is not None and abs(rs[i] - r) <= 0.0101 and abs(gs[j] - g1) <= 0.0201]
    implied, implied_note = reverse_dcf(fcf0, gt, r, nd, mi, shares, price)
    return {
        "fcf_start": fcf0, "fcf_start_basis": base_label,
        "growth_1_5": g1, "growth_source": g_src, "terminal_growth": gt, "discount_rate": r,
        "discount_source": r_source,
        "net_debt": nd, "shares": shares,
        "value_per_share": base["per_share"], "terminal_value_share": base["tv_share"],
        "range_low": min(inner) if inner else None, "range_high": max(inner) if inner else None,
        "grid_rates": rs, "grid_growths": gs, "grid": grid,
        "implied_growth": implied, "implied_growth_note": implied_note,
    }


# ============================================================ peers & analysts
def peer_symbols(client, sym, override, max_peers):
    if override:
        if override.strip().lower() == "none":
            return []
        try:
            peers = [normalize_symbol(s) for s in override.split(",") if s.strip()]
        except ValueError as e:
            raise SystemExit(f"--peers: {e}") from None
        return [s for s in dict.fromkeys(peers) if s != sym]
    data = client.try_get("stock-peers", symbol=sym) or []
    syms = []
    for r in data if isinstance(data, list) else [data]:
        if not isinstance(r, dict):
            continue
        if "peersList" in r:
            syms.extend(r.get("peersList") or [])
        elif r.get("symbol"):
            syms.append(r["symbol"])
    out = []
    for s in syms:
        s = str(s).upper()
        if s != sym and s not in out:
            out.append(s)
    return out[:max_peers]


def lfy_snapshot(profile, years):
    y = years[-1]
    price, mcap = num(profile, "price"), num(profile, "marketCap", "mktCap")
    m = multiples(price, mcap, y)
    return {
        "symbol": profile.get("symbol"), "name": profile.get("companyName"), "fy": y["label"],
        "market_cap": mcap, "pe": m["pe"], "ev_ebitda": m["ev_ebitda"], "ps": m["ps"],
        "p_fcf": m["p_fcf"], "revenue_yoy": y["revenue_yoy"], "gross_margin": y["gross_margin"],
        "operating_margin": y["operating_margin"], "roe": y["roe"], "roic": y["roic"],
        "net_debt_to_ebitda": y["net_debt_to_ebitda"],
    }


def peer_requests(client, s):
    """The five calls behind one peer row, as (function, args, kwargs) so they can run in parallel."""
    st = client.statements
    return [(client.try_get, ("profile",), {"symbol": s}),
            (st, ("income-statement", s, "annual", 2), {"optional": True}),
            (st, ("balance-sheet-statement", s, "annual", 1), {"optional": True}),
            (st, ("cash-flow-statement", s, "annual", 1), {"optional": True}),
            (fetch_quote, (client, s), {})]


def peer_snapshot(s, prof, inc, bs, cf, quote=None):
    prof = prof[0] if isinstance(prof, list) and prof else (prof if isinstance(prof, dict) else None)
    if not prof or not inc:
        return {"symbol": s, "error": "no data (plan restriction or unknown ticker)"}
    return lfy_snapshot(quote_price(prof, quote), build_years(inc, bs, cf))


def fetch_estimates(client, sym):
    est = client.try_get("analyst-estimates", symbol=sym, period="annual", page=0, limit=10)
    if est is None:  # some plans cap `limit`; retry with the smaller page size
        est = client.try_get("analyst-estimates", symbol=sym, period="annual", page=0, limit=5)
        if est is not None:
            client.unrestrict("analyst-estimates")
    return est


def analyst_view(est, last_fy, price, today):
    """est: analyst-estimates rows (or None).

    Keeps every fiscal year after the last reported one, up to two years after the one in progress:
    normally the current fiscal year and the two after it, plus a year that has ended but is not reported yet."""
    out = {}
    if isinstance(est, list):
        rows_by_date = sorted((e for e in est if isinstance(e, dict) and re.match(r"\d{4}-\d{2}-\d{2}", str(e.get("date")))),
                              key=lambda e: str(e["date"]))

        def near_fy_end(e):
            try:
                return abs((dt.date.fromisoformat(str(e["date"])[:10]) - dt.date.fromisoformat(last_fy["date"])).days) <= 15
            except ValueError:
                return False
        future, ahead = [], 0
        for e in rows_by_date:
            d = str(e["date"])[:10]
            if d <= last_fy["date"] or near_fy_end(e):  # FMP may date the reported year a few days off
                continue
            future.append(e)
            ahead += d > today
            if ahead >= 3:
                break
        same = [e for e in rows_by_date if near_fy_end(e)]
        # Banks, exchanges and some others report gross revenue while analysts forecast net revenue: growth
        # from the reported figure would then show a fall that is only the change of basis. When the analysts'
        # figure for the last reported year is more than 5% off the reported one, growth starts from theirs.
        prev_rev = last_fy["revenue"]
        est_rev = num(same[-1], "revenueAvg", "estimatedRevenueAvg") if same else None
        if est_rev and est_rev > 0 and prev_rev and prev_rev > 0 and abs(est_rev / prev_rev - 1) > REVENUE_BASIS_GAP:
            out["revenue_basis"] = {"fy": last_fy["label"], "estimate": est_rev, "reported": prev_rev,
                                    "gap": est_rev / prev_rev - 1}
            prev_rev = est_rev
        rows = []
        for e in future:
            eps, rev = num(e, "epsAvg", "estimatedEpsAvg"), num(e, "revenueAvg", "estimatedRevenueAvg")
            d = str(e["date"])[:10]
            rows.append({
                "fy": d[:4], "date": d, "ended": d <= today, "eps_avg": eps,
                "eps_low": num(e, "epsLow", "estimatedEpsLow"), "eps_high": num(e, "epsHigh", "estimatedEpsHigh"),
                "revenue_avg": rev, "revenue_growth": yoy(rev, prev_rev),
                "ebitda_avg": num(e, "ebitdaAvg", "estimatedEbitdaAvg"),
                "analysts": num(e, "numAnalystsEps", "numberAnalystsEstimatedEps"),
                "forward_pe": pos_div(price, eps),
            })
            prev_rev = rev
        out["estimates"] = rows
        # FMP's row for the last reported year vs the reported diluted EPS: a large gap suggests the
        # estimates are on an adjusted (non-GAAP) basis, which the P/E history does not share.
        est_eps = num(same[-1], "epsAvg", "estimatedEpsAvg") if same else None
        if est_eps and est_eps > 0 and last_fy.get("eps") and last_fy["eps"] > 0:
            out["eps_basis"] = {"fy": last_fy["label"], "estimate": est_eps, "reported": last_fy["eps"],
                                "gap": est_eps / last_fy["eps"] - 1}
        est_ebitda = num(same[-1], "ebitdaAvg", "estimatedEbitdaAvg") if same else None
        if est_ebitda and est_ebitda > 0 and last_fy.get("ebitda") and last_fy["ebitda"] > 0:
            out["ebitda_basis"] = {"fy": last_fy["label"], "estimate": est_ebitda, "reported": last_fy["ebitda"],
                                   "gap": est_ebitda / last_fy["ebitda"] - 1}
    return out


# ============================================================ forward multiples
def _ntm(fys):
    """fys: [(fiscal_year_end_iso, value)]. Returns day_iso -> next-twelve-month value: the fiscal year in
    progress and the one after it, weighted by the time left in the year in progress (the convention behind
    published forward P/E charts). None when either year is missing or not positive: a blend across a loss
    year gives meaningless multiples."""
    fys = sorted(fys)
    keys = [d for d, _ in fys]
    ends = [dt.date.fromisoformat(d) for d in keys]

    def at(day):
        i = bisect.bisect_left(keys, day)  # first fiscal year ending on or after this day
        if i + 1 >= len(fys) or not 330 <= (ends[i + 1] - ends[i]).days <= 400:  # missing year
            return None
        left = (ends[i] - dt.date.fromisoformat(day)).days
        if left > 400:
            return None
        a, b = fys[i][1], fys[i + 1][1]
        if a <= 0 or b <= 0:
            return None
        w = min(left / 365.25, 1.0)
        return w * a + (1 - w) * b
    return at


def _band(vals, window, now=None):
    q = statistics.quantiles(vals, n=20, method="inclusive")  # 5% steps
    return {"p10": q[1], "p25": q[4], "median": q[9], "p75": q[14], "p90": q[17], "n": len(vals),
            "from": window[0][0], "to": window[-1][0], "now": now,
            "now_pct": sum(v <= now for v in vals) / len(vals) if now else None}


def history_problem(years, window, start, cur_shares):
    """Why the multiple history can't be trusted, as (code, text), or (None, None)."""
    # Prices are split-adjusted; statement figures may not be (or may be per ordinary share of an ADR). An
    # unadjusted split shows as a jump between two fiscal years, an ADR ratio as a gap between the latest year and
    # today. Steady issuance or buybacks (a REIT growing by share sales, an acquisition paid in shares) change
    # the count gradually, and each year's multiple uses its own count, so they do not break the history.
    sh = [y["shares"] for y in years if y.get("shares") and y["date"] >= start]
    steps = list(zip(sh, sh[1:])) + ([(sh[-1], cur_shares)] if sh and cur_shares else [])
    if any(not 0.55 <= a / b <= 1.8 for a, b in steps):
        return "share_basis", ("The share counts in the statements do not match today's share basis (for example a "
                               "stock split the statements do not reflect, an ADR ratio or several share classes), so "
                               "the multiple history is not comparable and no forward multiple range is shown.")
    if any(not 0.5 <= b / a <= 2.0 for (_, a), (_, b) in zip(window, window[1:])):
        return "price_jump", ("The price history has a one-day fall of more than 50% or rise of more than 100% "
                              "(possibly a stock split the prices do not reflect), so no forward multiple range is "
                              "shown.")
    return None, None


def multiple_bands(years, window, eps_at, ebitda_at, now_pe, now_ev_ebitda):
    """Daily forward P/E and forward EV/EBITDA over the window, on next-twelve-month EPS and EBITDA. Reported
    figures are used once a year is reported (so history reflects what the company went on to deliver), the
    analysts' average otherwise. EV uses the share count and net debt of the latest reported fiscal year.
    Non-positive denominators are left out."""
    reported = [y for y in years if y.get("shares") and y.get("net_debt") is not None]
    rep_ends = [y["date"] for y in reported]
    pe, ev = [], []
    for d, px in window:
        eps = eps_at(d)
        if eps and eps > 0:
            pe.append(px / eps)
        ebitda, j = ebitda_at(d), bisect.bisect_right(rep_ends, d) - 1
        if ebitda and ebitda > 0 and j >= 0:
            y = reported[j]
            ev.append((px * y["shares"] + y["net_debt"] + (y["minority_interest"] or 0)) / ebitda)
    # under ~6 months of usable trading days the percentiles mean little
    return (_band(pe, window, now_pe) if len(pe) >= 120 else None,
            _band(ev, window, now_ev_ebitda) if len(ev) >= 120 else None)


def _blend(w, a, b):
    return None if a is None or b is None else w * a + (1 - w) * b


def forward_bands(years, basis, series, analyst, price, today, cur_shares=None, sector_kind="general",
                  lookback_years=3):
    """The distributions of the daily forward P/E and forward EV/EBITDA over the last `lookback_years` (statistics
    only, never turned into prices), with today's value on them, and the checks of the multiple histories.

    forward is today's point: next-twelve-month EPS and EBITDA, the fiscal year in progress and the one after it
    weighted by the time left in the one in progress (None without estimates for both). band_problem says why
    the forward history can't be trusted (no bands then), trailing_problem the same for every fiscal year's
    history behind history_compare."""
    estimates = analyst.get("estimates") or []
    cur, nxt = ([e for e in estimates if not e["ended"]] + [None, None])[:2]
    out = {"lookback_years": lookback_years, "pe_band": None, "ev_band": None, "band_problem": None,
           "trailing_problem": None, "forward": None}
    nd, mi = basis.get("net_debt"), basis.get("minority_interest") or 0.0
    ev_ok = sector_kind != "financial" and nd is not None and bool(cur_shares)
    today_iso = today.isoformat()
    # both checked with or without estimates
    start = (today - dt.timedelta(days=round(365.25 * lookback_years))).isoformat()
    window = [(d, px) for d, px in series if d >= start and px]
    out["band_problem"] = history_problem(years, window, start, cur_shares)[0]
    first = min((y["date"] for y in years), default=start)
    out["trailing_problem"] = history_problem(years, [(d, px) for d, px in series if d >= first and px], first,
                                              cur_shares)[0]
    if not (cur and nxt):
        return out

    def ntm(rep_key, est_key):
        return _ntm([(y["date"], y[rep_key]) for y in years if y.get(rep_key) is not None] +
                    [(e["date"], e[est_key]) for e in estimates if e.get(est_key) is not None])
    eps_at, ebitda_at = ntm("eps", "eps_avg"), ntm("ebitda", "ebitda_avg")
    w = min(max((dt.date.fromisoformat(cur["date"]) - today).days, 0) / 365.25, 1.0)
    now = {"at": "now", "fy": None, "date": today_iso, "uses": [cur["fy"], nxt["fy"]], "weight": w,
           "eps": eps_at(today_iso), "eps_low": _blend(w, cur["eps_low"], nxt["eps_low"]),
           "eps_high": _blend(w, cur["eps_high"], nxt["eps_high"]), "ebitda": ebitda_at(today_iso)}
    out["forward"] = now
    if not out["band_problem"]:
        now_pe = pos_div(price, now["eps"])
        now_ev = pos_div(price * cur_shares + nd + mi, now["ebitda"]) if ev_ok else None
        pe, ev = multiple_bands(years, window, eps_at, ebitda_at, now_pe, now_ev)
        out["pe_band"] = pe
        out["ev_band"] = ev if ev_ok and now["ebitda"] and now["ebitda"] > 0 else None
    return out


# ============================================================ main
def fetch_prices(client, sym, start, end):
    try:
        return client.prices(sym, start, end)
    except FMPError as e:
        client.add_error(f"price history: {e}")
        return []


def fetch_quote(client, sym):
    """The latest quote (price, day change, market cap, day range, timestamp), or None when the plan or data
    source has none; the profile's price, cached for a day, is then used."""
    q = client.try_get("quote", symbol=sym)
    if isinstance(q, list):
        q = q[0] if q else None
    return q if isinstance(q, dict) and (num(q, "price") or 0) > 0 else None


def us_eastern(ts):
    """A Unix timestamp as naive New York time. US daylight saving rules are computed here because
    Python on Windows has no time zone database unless the tzdata package is installed."""
    utc = dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(tzinfo=None)
    mar1, nov1 = dt.datetime(utc.year, 3, 1), dt.datetime(utc.year, 11, 1)
    start = mar1 + dt.timedelta(days=(6 - mar1.weekday()) % 7 + 7, hours=7)  # 2nd Sunday of March, 2:00 EST
    end = nov1 + dt.timedelta(days=(6 - nov1.weekday()) % 7, hours=6)       # 1st Sunday of November, 2:00 EDT
    return utc - dt.timedelta(hours=4 if start <= utc < end else 5)


def quote_price(profile, quote):
    """The profile with the quote's price, day change and market cap (the profile itself is cached for a day).
    Used for the company and for each peer, so the peer table compares prices taken at the same time."""
    if not quote:
        return profile
    px, old = num(quote, "price"), num(profile, "price")
    mcap = num(quote, "marketCap")
    if mcap is None and old and num(profile, "marketCap", "mktCap"):
        mcap = num(profile, "marketCap", "mktCap") * px / old
    profile = {**profile, "price": px}
    for k in ("changePercentage", "change"):
        if num(quote, k) is not None:
            profile[k] = num(quote, k)
    if mcap:
        profile["marketCap"] = mcap
    return profile


def apply_quote(profile, quote, series):
    """Use the latest quote for the price, day change and market cap, and for the latest day of the price
    history, so each run shows the current price while the profile and the daily closes come from the cache.
    Returns (profile, series, quote time in New York as 'YYYY-MM-DD HH:MM'); the time is "" when the quote has
    no timestamp, and None when the quote was not used because it is older than the price history."""
    ts = num(quote, "timestamp")
    when = us_eastern(ts / 1000 if ts > 1e12 else ts) if ts and ts > 0 else None
    day = when.date().isoformat() if when else None
    if day and series and series[-1][0] > day:
        return profile, series, None  # the quote is older than the price history: keep the profile's price
    profile = quote_price(profile, quote)
    if not when:
        return profile, series, ""
    # A close for the quote's day exists once that session has opened (not on weekends or before 9:30).
    opened = when.weekday() < 5 and when.time() >= dt.time(9, 30)
    if series and (series[-1][0] == day or (series[-1][0] < day and opened)):
        series = [p for p in series if p[0] != day] + [(day, profile["price"])]
    return profile, series, when.strftime("%Y-%m-%d %H:%M")


def max_workers():
    try:
        return max(1, int(os.environ.get("FMP_MAX_WORKERS") or 6))
    except ValueError:
        return 6


def analyze(args):
    """One company's analysis: the internal result that facts.build() turns into the fa-2.0 document and run()
    reports on. It is never written to disk (only fa-2.0 is)."""
    try:
        sym = normalize_symbol(args.symbol)  # BRK.B -> BRK-B; refuses foreign listings before any API call
    except ValueError as e:
        raise SystemExit(f"Cannot analyse {args.symbol!r}: {e}") from None
    client = FMPClient(refresh=args.refresh)
    try:
        profile = client.profile(sym)
    except RestrictedEndpoint:
        raise SystemExit(f"Your FMP plan does not cover {sym} (Starter covers US listings only). "
                         f"Try the US ticker/ADR or another data source.")
    if not profile:
        raise SystemExit(f"No profile found for {sym}. Check the ticker.")

    # Everything below only depends on the ticker, so it is fetched in parallel. The client's
    # rate limiter is shared across threads, so FMP_MAX_PER_MIN still holds.
    today = dt.date.today()
    st = client.statements
    pool = ThreadPoolExecutor(max_workers=max_workers())
    futures = []

    def submit(fn, *a, **kw):
        f = pool.submit(fn, *a, **kw)
        futures.append(f)
        return f

    try:
        f_inc = submit(st, "income-statement", sym, "annual", args.years)
        f_bs = submit(st, "balance-sheet-statement", sym, "annual", args.years, optional=True)
        f_cf = submit(st, "cash-flow-statement", sym, "annual", args.years, optional=True)
        f_q = None if args.no_ttm else (
            submit(st, "income-statement", sym, "quarter", 4, optional=True),
            submit(st, "cash-flow-statement", sym, "quarter", 4, optional=True),
            submit(st, "balance-sheet-statement", sym, "quarter", 1, optional=True))
        f_est = submit(fetch_estimates, client, sym)
        f_quote = submit(fetch_quote, client, sym)
        f_peer_syms = submit(peer_symbols, client, sym, args.peers, args.max_peers)
        market_reqs = {}
        if not args.no_market:
            # the Treasury curve 3M / 1Y ago and the returns are only shown in the --macro section
            market_reqs.update(M.rates_requests(client, today, history=args.macro))
            market_reqs.update(M.sector_requests(client, profile, today, returns=args.macro))
            if args.macro:
                market_reqs.update(M.macro_requests(client, today))
        f_market = {k: submit(fn, *a, **kw) for k, (fn, a, kw) in market_reqs.items()}

        inc = f_inc.result()
        if not inc:
            raise SystemExit(f"No income statements returned for {sym}.")
        # price history starts just before the oldest fiscal year, so it waits for the income statements
        start = (dt.date.fromisoformat(str(inc[0].get("date"))[:10]) - dt.timedelta(days=10)).isoformat()
        f_px = submit(fetch_prices, client, sym, start, today.isoformat())
        f_peers = [(s, [submit(fn, *a, **kw) for fn, a, kw in peer_requests(client, s)])
                   for s in f_peer_syms.result()]

        years = build_years(inc, f_bs.result(), f_cf.result())
        ttm = build_ttm(*(f.result() for f in f_q)) if f_q else None
        series = f_px.result()
        est, quote = f_est.result(), f_quote.result()
        peers = [peer_snapshot(s, *(f.result() for f in fs)) for s, fs in f_peers]
        market_res = {k: f.result() for k, f in f_market.items()}
    except BaseException:
        for f in futures:
            f.cancel()
        raise
    finally:
        pool.shutdown(wait=True)

    price_time = None
    if quote:
        profile, series, price_time = apply_quote(profile, quote, series)

    if ttm and ttm["date"] <= years[-1]["date"]:
        ttm = None  # latest quarter is the fiscal year end; annual data is already current
    basis = ttm or years[-1]

    # The company kind decides which standard measures apply (facts.NOT_MEANINGFUL lists the ones that do not).
    sector = (profile.get("sector") or "").strip().lower()
    industry = (profile.get("industry") or "").lower()
    sector_kind = "general"
    if any(w in industry for w in FEE_FINANCIAL_INDUSTRIES):
        sector_kind = "fee_financial"  # Altman Z and the current ratio mean little (clearing margin, client money)
    elif (sector in FINANCIAL_SECTORS or any(w in industry for w in ("bank", "insurance", "capital markets"))
          or ("reit" in industry and "mortgage" in industry)):  # mortgage REITs lend: treated like banks
        sector_kind = "financial"  # gross margin, EV multiples, FCF, DCF and Altman Z mean little
    elif "reit" in industry:  # developers and real-estate services are analysed like other companies
        sector_kind = "reit"  # net income understates cash earnings (depreciation)
    elif sector == "utilities" and "independent power" not in industry:
        sector_kind = "utility"  # capex above operating cash flow, funded with debt and new shares, is normal

    price, mcap = num(profile, "price"), num(profile, "marketCap", "mktCap")
    current = multiples(price, mcap, basis)

    hist = valuation_history(years, series)
    hist_cmp = compare_to_history(current, hist)

    market, capm = None, None
    if not args.no_market:
        rates = M.treasury_view(M.treasury_rows(market_res), today)
        erp = M.us_erp(market_res.get("erp"))
        capm = M.capm_rate(rates, erp, num(profile, "beta"))
        market = {"rates": rates, "erp": erp, "capm": capm,
                  "sector": M.sector_context(market_res, profile, current["pe"], series, today=today)}
        if args.macro:
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            market["macro"] = {
                "rates": rates, "erp": erp,
                "indicators": M.indicators_view(market_res),
                "calendar": M.calendar_view(M.calendar_rows(market_res, client), now),
            }
    if args.discount is not None:
        rate, rate_src = args.discount, "user input"
    elif capm:
        rate, rate_src = capm["rate"], M.capm_note(capm)
    else:
        rate = M.FALLBACK_DISCOUNT
        rate_src = "fixed default; --no-market" if args.no_market else "fixed default; Treasury/risk-premium data unavailable"

    n = len(years) - 1
    cg = {k: cagr(years[0][k], years[-1][k], n) for k in
          ("revenue", "gross_profit", "operating_income", "net_income", "eps", "fcf", "shares")}

    analyst = analyst_view(est, years[-1], price, today.isoformat())
    # the date the price belongs to when there is no quote time: the last close of the past year
    year = [d for d, px in series if d >= (today - dt.timedelta(days=365)).isoformat() and px]
    return {
        "symbol": sym, "as_of": today.isoformat(), "price_time": price_time,
        "last_close": year[-1] if len(year) >= 2 else None, "profile": profile,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "sector_kind": sector_kind,
        "years": years, "ttm": ttm, "basis": basis, "current": current, "cagr": cg,
        "valuation_history": hist, "history_compare": hist_cmp,
        "piotroski": piotroski(years), "altman": altman(years[-1], mcap),
        "dcf": run_dcf(years, basis, current, args, cg["revenue"], sector_kind, rate, rate_src),
        "analyst": analyst,
        "forward_bands": forward_bands(years, basis, series, analyst, price, today, div(mcap, price),
                                       sector_kind=sector_kind),
        "peers": peers, "market": market,
        "meta": {"network_calls": client.stats["network_calls"], "cache_hits": client.stats["cache_hits"],
                 "restricted": sorted(client.restricted), "errors": sorted(client.errors),
                 "connection": client.describe()},
    }


def run(args):
    """One analysis as (fa-2.0 document, markdown report). main() and ui/server.py both call it, so the command
    line and the page always agree."""
    r = analyze(args)
    doc = F.build(json.loads(json.dumps(r, default=str)))  # built from its JSON form, like a result saved by v1.x
    mk = r["market"] or {}
    macro_md = None
    if mk.get("macro"):  # --macro: the dashboard, then the stock's returns against its industry, sector and SPY
        macro_md = M.render_macro(mk["macro"]) + "\n\n" + M.render_returns(mk["sector"], r["symbol"])
    calls = (r["meta"]["network_calls"], r["meta"]["cache_hits"])
    return doc, R.render(doc, macro_md=macro_md, calls=calls)


# accepted for one version, with a note on stderr
DEPRECATED_NOTES = (
    ("contract", "--contract is deprecated: fa-1.1 was removed in v2.0; it now writes fa-2.0, like --json"),
    ("iv", "--iv is ignored: v2.0 has no volatility range"),
    ("no_insider", "--no-insider is ignored: v2.0 fetches no insider trades"),
)


def parse_args(argv):
    ap = argparse.ArgumentParser(description="FMP fundamental analysis: the facts of one stock (fa-2.0)")
    ap.add_argument("symbol")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--peers", default=None)
    ap.add_argument("--max-peers", type=int, default=5)
    ap.add_argument("--discount", type=float, default=None)
    ap.add_argument("--terminal", type=float, default=0.025)
    ap.add_argument("--growth", type=float, default=None)
    ap.add_argument("--fcf-base", choices=("latest", "avg3"), default="latest")
    ap.add_argument("--no-ttm", action="store_true")
    ap.add_argument("--macro", action="store_true")
    ap.add_argument("--no-market", action="store_true")
    ap.add_argument("--json", default=None)
    ap.add_argument("--facts", default=None)
    ap.add_argument("--contract", default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--iv", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--no-insider", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.macro and a.no_market:
        ap.error("--macro needs the market data that --no-market skips; use one or the other")
    return a


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    for key, note in DEPRECATED_NOTES:
        if getattr(args, key):
            print(f"({note})", file=sys.stderr)
    try:
        doc, report = run(args)
    except InvalidKey as e:
        print(f"API key problem: {e}", file=sys.stderr)
        return 2
    except FMPError as e:
        print(f"FMP error: {e}", file=sys.stderr)
        return 1
    print(report)
    text = F.dumps(doc)
    for path in (args.json, args.facts, args.contract):  # one document, under each name a caller gives
        if path:
            Path(path).write_text(text, encoding="utf-8")
            print(f"({F.FACTS} written to {path})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
