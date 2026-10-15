#!/usr/bin/env python3
"""
Fundamental analysis snapshot for one stock, built from FMP financial statements.

All arithmetic happens here so the model only has to interpret the numbers.
Ratios are computed from the raw income / balance-sheet / cash-flow statements,
so the analysis works on FMP plans that only include annual fundamentals.

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
  --iv SIGMA         annual implied volatility for the volatility bands, e.g. 0.45 for 45%
                     (default: the past year's realized volatility)
  --no-ttm           skip trailing-twelve-month data (saves 3 API calls)
  --macro            add the rates & macro backdrop (Fed funds, CPI, jobs, key releases)
  --no-market        skip Treasury / sector / industry data (fixed 9% discount, no sector section;
                     cannot be combined with --macro)
  --json PATH        also write every computed number to a JSON file
  --refresh          ignore the local cache

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
import macro as M  # noqa: E402

FINANCIAL_SECTORS = {"financial services", "financials", "financial"}
REAL_ESTATE_SECTORS = {"real estate"}


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


def median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


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

    for k, src in (("revenue_yoy", "revenue"), ("gross_profit_yoy", "gross_profit"),
                   ("operating_income_yoy", "operating_income"), ("net_income_yoy", "net_income"),
                   ("eps_yoy", "eps"), ("fcf_yoy", "fcf"), ("shares_yoy", "shares")):
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
    t["fy"], t["label"] = "TTM", "TTM"
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
    fixed = None
    if r_source.startswith("CAPM") and abs(r - M.FALLBACK_DISCOUNT) > 0.0005:
        fixed = (dcf_value(fcf0, g1, gt, M.FALLBACK_DISCOUNT, nd, mi, shares) or {}).get("per_share")
    return {
        "fcf_start": fcf0, "fcf_start_basis": base_label,
        "growth_1_5": g1, "growth_source": g_src, "terminal_growth": gt, "discount_rate": r,
        "discount_source": r_source, "value_at_fixed_rate": fixed,
        "net_debt": nd, "shares": shares,
        "value_per_share": base["per_share"], "terminal_value_share": base["tv_share"],
        "margin_of_safety": base["per_share"] / price - 1 if price else None,
        "range_low": min(inner) if inner else None, "range_high": max(inner) if inner else None,
        "grid_rates": rs, "grid_growths": gs, "grid": grid,
        "implied_growth": implied, "implied_growth_note": implied_note,
    }


# ============================================================ peers & analysts
def peer_symbols(client, sym, override, max_peers):
    if override:
        if override.strip().lower() == "none":
            return []
        return [s.strip().upper() for s in override.split(",") if s.strip() and s.strip().upper() != sym]
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
    """The four calls behind one peer row, as (function, args, kwargs) so they can run in parallel."""
    st = client.statements
    return [(client.try_get, ("profile",), {"symbol": s}),
            (st, ("income-statement", s, "annual", 2), {"optional": True}),
            (st, ("balance-sheet-statement", s, "annual", 1), {"optional": True}),
            (st, ("cash-flow-statement", s, "annual", 1), {"optional": True})]


def peer_snapshot(s, prof, inc, bs, cf):
    prof = prof[0] if isinstance(prof, list) and prof else (prof if isinstance(prof, dict) else None)
    if not prof or not inc:
        return {"symbol": s, "error": "no data (plan restriction or unknown ticker)"}
    return lfy_snapshot(prof, build_years(inc, bs, cf))


def fetch_estimates(client, sym):
    est = client.try_get("analyst-estimates", symbol=sym, period="annual", page=0, limit=10)
    if est is None:  # some plans cap `limit`; retry with the smaller page size
        est = client.try_get("analyst-estimates", symbol=sym, period="annual", page=0, limit=5)
        if est is not None:
            client.unrestrict("analyst-estimates")
    return est


def analyst_view(est, pt, last_fy, price, today):
    """est: analyst-estimates rows, pt: price-target-consensus response (either may be None).

    Keeps every fiscal year after the last reported one, up to two years after the one in progress:
    normally the current fiscal year and the two after it (the price range needs those for next-12-month
    figures at each fiscal year end), plus a year that has ended but is not reported yet."""
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
        rows, prev_rev = [], last_fy["revenue"]
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
        same = [e for e in rows_by_date if near_fy_end(e)]
        est_eps = num(same[-1], "epsAvg", "estimatedEpsAvg") if same else None
        if est_eps and est_eps > 0 and last_fy.get("eps") and last_fy["eps"] > 0:
            out["eps_basis"] = {"fy": last_fy["label"], "estimate": est_eps, "reported": last_fy["eps"],
                                "gap": est_eps / last_fy["eps"] - 1}
        est_ebitda = num(same[-1], "ebitdaAvg", "estimatedEbitdaAvg") if same else None
        if est_ebitda and est_ebitda > 0 and last_fy.get("ebitda") and last_fy["ebitda"] > 0:
            out["ebitda_basis"] = {"fy": last_fy["label"], "estimate": est_ebitda, "reported": last_fy["ebitda"],
                                   "gap": est_ebitda / last_fy["ebitda"] - 1}
    pt = pt[0] if isinstance(pt, list) and pt else (pt if isinstance(pt, dict) else None)
    if pt:
        cons = num(pt, "targetConsensus")
        out["price_target"] = {
            "consensus": cons, "median": num(pt, "targetMedian"),
            "high": num(pt, "targetHigh"), "low": num(pt, "targetLow"),
            "upside": div(cons, price) - 1 if cons and price else None,
        }
    return out


# ============================================================ price ranges
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
    """Why the multiple history can't be trusted, or None."""
    # Prices are split-adjusted; statement figures may not be (or may be per ordinary share of an ADR).
    if cur_shares and any(y.get("shares") and y["date"] >= start and not 0.55 <= y["shares"] / cur_shares <= 1.8
                          for y in years):
        return ("The share counts in the statements do not match today's share basis (for example a stock split the "
                "statements do not reflect, an ADR ratio or several share classes), so the multiple history is not "
                "comparable and no forward multiple range is shown.")
    if any(not 0.5 <= b / a <= 2.0 for (_, a), (_, b) in zip(window, window[1:])):
        return ("The price history has a one-day move of more than 50% (possibly a stock split the prices do not "
                "reflect), so no forward multiple range is shown.")
    return None


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


def volatility(series, today):
    """Annualized standard deviation of the past year's daily log moves."""
    start = (today - dt.timedelta(days=365)).isoformat()
    closes = [px for d, px in series if d >= start and px]
    moves = [math.log(b / a) for a, b in zip(closes, closes[1:])]
    return statistics.stdev(moves) * math.sqrt(252) if len(moves) >= 120 else None


def _blend(w, a, b):
    return None if a is None or b is None else w * a + (1 - w) * b


def price_range(years, basis, series, analyst, dcf, price, today, cur_shares=None, iv=None, sector_kind="general",
                lookback_years=3):
    """Price ranges from several methods, for the report's price-range section and the UI chart.

    The forward-multiple ranges are given at three points: now (on next-twelve-month figures), the end of the
    current fiscal year and the end of the next one (where the next twelve months are exactly the following
    fiscal year). The volatility ranges use the same fiscal year ends."""
    estimates = analyst.get("estimates") or []
    cur, nxt, after = ([e for e in estimates if not e["ended"]] + [None, None, None])[:3]
    out = {"price": price, "lookback_years": lookback_years, "pe_band": None, "ev_band": None, "band_note": None,
           "forward": [], "summary": []}
    nd, mi = basis.get("net_debt"), basis.get("minority_interest") or 0.0
    ev_ok = sector_kind != "financial" and nd is not None and bool(cur_shares)
    today_iso = today.isoformat()

    def ntm(rep_key, est_key):
        return _ntm([(y["date"], y[rep_key]) for y in years if y.get(rep_key) is not None] +
                    [(e["date"], e[est_key]) for e in estimates if e.get(est_key) is not None])
    eps_at, ebitda_at = ntm("eps", "eps_avg"), ntm("ebitda", "ebitda_avg")

    if cur and nxt:
        w = min(max((dt.date.fromisoformat(cur["date"]) - today).days, 0) / 365.25, 1.0)
        points = [{"at": "now", "fy": None, "date": today_iso, "uses": [cur["fy"], nxt["fy"]], "weight": w,
                   "eps": eps_at(today_iso), "eps_low": _blend(w, cur["eps_low"], nxt["eps_low"]),
                   "eps_high": _blend(w, cur["eps_high"], nxt["eps_high"]), "ebitda": ebitda_at(today_iso)}]
        for end, e in ((cur, nxt), (nxt, after)):
            if e:
                points.append({"at": "fy_end", "fy": end["fy"], "date": end["date"], "uses": [e["fy"]], "weight": None,
                               "eps": e["eps_avg"], "eps_low": e["eps_low"], "eps_high": e["eps_high"],
                               "ebitda": e.get("ebitda_avg"), "analysts": e["analysts"]})
        now = points[0]
        now_pe = pos_div(price, now["eps"])
        now_ev = pos_div(price * cur_shares + nd + mi, now["ebitda"]) if ev_ok else None

        start = (today - dt.timedelta(days=round(365.25 * lookback_years))).isoformat()
        window = [(d, px) for d, px in series if d >= start and px]
        out["band_note"] = history_problem(years, window, start, cur_shares)
        if not out["band_note"]:
            out["pe_band"], out["ev_band"] = multiple_bands(years, window, eps_at, ebitda_at, now_pe, now_ev)
            if not ev_ok or not (now["ebitda"] and now["ebitda"] > 0):
                out["ev_band"] = None
            if not out["pe_band"] and not out["ev_band"]:
                out["band_note"] = "Not enough positive-earnings price history for a multiple range (needs about 6 months)."

        pb, eb = out["pe_band"], out["ev_band"]
        for pt in points:
            pt["pe"] = pt["ev"] = None
            if pb and pt["eps"] and pt["eps"] > 0:
                pt["pe"] = {k: pt["eps"] * pb[q] for k, q in (("low", "p25"), ("base", "median"), ("high", "p75"))}
                pt["pe"]["at_today"] = pt["eps"] * now_pe if now_pe else None
            if eb and pt["ebitda"] and pt["ebitda"] > 0:
                to_price = lambda m: (m * pt["ebitda"] - nd - mi) / cur_shares  # noqa: E731
                pt["ev"] = {k: to_price(eb[q]) for k, q in (("low", "p25"), ("base", "median"), ("high", "p75"))}
                pt["ev"]["at_today"] = to_price(now_ev) if now_ev else None
            for m in ("pe", "ev"):
                if pt[m]:
                    pt[m]["base_vs_price"] = pt[m]["base"] / price - 1 if price else None
        out["forward"] = points

    def multiple_rows(pt):
        return [{"kind": k, "at": pt["at"], "fy": pt["fy"], "low": pt[m]["low"], "mid": pt[m]["base"],
                 "high": pt[m]["high"]} for k, m in (("fwd_pe", "pe"), ("fwd_ev", "ev")) if pt[m]]

    s = out["summary"]
    for pt in out["forward"][:1]:
        s += multiple_rows(pt)
    if dcf.get("range_low") is not None:
        s.append({"kind": "dcf", "low": dcf["range_low"], "mid": dcf["value_per_share"], "high": dcf["range_high"]})
    t = analyst.get("price_target")
    if t and t.get("low") is not None and t.get("high") is not None:
        s.append({"kind": "targets", "low": t["low"], "mid": t["consensus"], "high": t["high"]})
    year = [(d, px) for d, px in series if d >= (today - dt.timedelta(days=365)).isoformat() and px]
    if len(year) >= 2:
        closes = [px for _, px in year]
        out["week52"] = {"low": min(closes), "high": max(closes), "from": year[0][0], "to": year[-1][0]}
        s.append({"kind": "week52", "low": out["week52"]["low"], "mid": None, "high": out["week52"]["high"]})

    # Volatility ranges to each fiscal year end (1 year when there are no estimates): lognormal around
    # today's price with no drift, +/-1 sd (about 68%) and +/-1.96 sd (about 95%).
    sigma = iv if iv else volatility(series, today)
    vol_rows = {}
    if sigma and price:
        horizons = [(e["fy"], dt.date.fromisoformat(e["date"])) for e in (cur, nxt) if e] or \
                   [(None, today + dt.timedelta(days=365))]
        out["volatility"] = {"sigma": sigma, "implied": bool(iv), "bands": []}
        for fy, end in horizons:
            T = max((end - today).days, 1) / 365.25
            w1, w2 = sigma * math.sqrt(T), 1.96 * sigma * math.sqrt(T)
            b = {"fy": fy, "end": end.isoformat(), "years": T,
                 "low": price * math.exp(-w1), "high": price * math.exp(w1),
                 "low95": price * math.exp(-w2), "high95": price * math.exp(w2)}
            out["volatility"]["bands"].append(b)
            vol_rows[fy] = {"kind": "volatility", "at": "fy_end" if fy else "1y", "fy": fy, "low": b["low"], "mid": price,
                            "high": b["high"], "low95": b["low95"], "high95": b["high95"]}
    # then one group per fiscal year end: forward multiples at that date and the volatility range to it
    for pt in out["forward"][1:]:
        s += multiple_rows(pt)
        if pt["fy"] in vol_rows:
            s.append(vol_rows.pop(pt["fy"]))
    s += vol_rows.values()
    return out


# ============================================================ flags
def make_flags(years, cur, hist_cmp, pio, alt, dcf, rev_cagr, sector_kind):
    red, green = [], []
    L = years[-1]
    n = len(years) - 1

    if L["revenue_yoy"] is not None and L["revenue_yoy"] < 0:
        red.append(f"Revenue fell {pct(L['revenue_yoy'])} in {L['label']}")
    if rev_cagr is not None:
        if rev_cagr >= 0.10:
            green.append(f"Revenue CAGR {pct(rev_cagr)} over {n} years")
        elif rev_cagr < 0:
            red.append(f"Revenue shrinking: CAGR {pct(rev_cagr)} over {n} years")

    base = years[max(0, len(years) - 4)]
    if sector_kind != "financial" and L["operating_margin"] is not None and base["operating_margin"] is not None and base is not L:
        d = L["operating_margin"] - base["operating_margin"]
        if d >= 0.03:
            green.append(f"Operating margin expanded {pct(base['operating_margin'])} -> {pct(L['operating_margin'])} since {base['label']}")
        elif d <= -0.03:
            red.append(f"Operating margin compressed {pct(base['operating_margin'])} -> {pct(L['operating_margin'])} since {base['label']}")

    roic_med = median([y["roic"] for y in years])
    if roic_med is not None and sector_kind != "financial":
        if roic_med >= 0.15:
            green.append(f"Median ROIC {pct(roic_med)}: high returns on capital")
        elif roic_med < 0.06:
            red.append(f"Median ROIC {pct(roic_med)}: below a typical cost of capital")

    if sector_kind != "financial":
        conv = median([y["fcf_conversion"] for y in years[-3:]])
        if conv is not None:
            if conv >= 1.0 and (L["fcf"] or 0) > 0:
                green.append(f"FCF exceeds net income (median conversion {conv:.2f}x, last 3 yrs)")
            elif conv < 0.7:
                red.append(f"Earnings weakly backed by cash (median FCF/NI {conv:.2f}x, last 3 yrs)")
        if L["fcf"] is not None and L["fcf"] < 0:
            red.append(f"Negative free cash flow in {L['label']}")
        if L["net_debt"] is not None and L["net_debt"] < 0:
            green.append("Net cash balance sheet (cash exceeds debt)")
        if L["net_debt_to_ebitda"] is not None and L["net_debt_to_ebitda"] > 3:
            red.append(f"High leverage: net debt / EBITDA {L['net_debt_to_ebitda']:.1f}x")
        if L["interest_coverage"] is not None and L["interest_coverage"] < 3:
            red.append(f"Thin interest coverage: EBIT / interest {L['interest_coverage']:.1f}x")
        if L["current_ratio"] is not None and L["current_ratio"] < 1:
            red.append(f"Current ratio {L['current_ratio']:.2f} (<1): check short-term liquidity")

    share_chg = mean([y["shares_yoy"] for y in years])
    if share_chg is not None:
        if share_chg > 0.02:
            red.append(f"Share dilution ~{pct(share_chg)} per year")
        elif share_chg < -0.01:
            green.append(f"Share count shrinking ~{pct(-share_chg)} per year (buybacks)")
    if L["sbc_pct"] is not None and L["sbc_pct"] > 0.10:
        red.append(f"Stock-based comp is {pct(L['sbc_pct'])} of revenue")
    if L["negative_equity"]:
        red.append("Negative shareholders' equity (check if caused by buybacks rather than losses)")

    if pio and pio["out_of"] >= 7:
        if pio["score"] >= 7:
            green.append(f"Piotroski F-score {pio['score']}/{pio['out_of']} (strong)")
        elif pio["score"] <= 3:
            red.append(f"Piotroski F-score {pio['score']}/{pio['out_of']} (weak)")
    if alt and sector_kind != "financial":
        if alt.get("z_zone") == "distress" and alt.get("z2_zone") in ("distress", None):
            red.append(f"Altman Z {alt['z']:.2f} in distress zone")

    val_keys = (("pe", "P/E"), ("pb", "P/B")) if sector_kind == "financial" else (("pe", "P/E"), ("ev_ebitda", "EV/EBITDA"))
    for k, name in val_keys:
        h = hist_cmp.get(k) or {}
        c = h.get("current")
        if c is None or not h.get("n") or c > 60:  # multiples above ~60x reflect thin earnings, not cheapness
            continue
        if h["n"] >= 3 and c > h["max"]:
            red.append(f"{name} {c:.1f}x is above its {h['n']}-year range ({h['min']:.1f}-{h['max']:.1f}x)")
        elif h["n"] >= 3 and c < h["min"]:
            green.append(f"{name} {c:.1f}x is below its {h['n']}-year range ({h['min']:.1f}-{h['max']:.1f}x)")
        elif h["vs_median"] is not None and h["vs_median"] <= -0.15:
            green.append(f"{name} {c:.1f}x is {pct(-h['vs_median'])} below its {h['n']}-year median {h['median']:.1f}x")

    if dcf and "skipped" not in dcf:
        mos = dcf.get("margin_of_safety")
        if mos is not None and mos >= 0.20:
            green.append(f"Base-case DCF value {pct(mos)} above price")
        elif mos is not None and mos <= -0.30:
            red.append(f"Price is {pct(-mos / (1 + mos))} above base-case DCF value")
        ig = dcf.get("implied_growth")
        if ig is not None and rev_cagr is not None:
            if ig > rev_cagr + 0.05:
                red.append(f"Price implies ~{pct(ig)}/yr FCF growth for 5 yrs vs {pct(rev_cagr)} historical revenue CAGR")
            elif ig < rev_cagr - 0.03:
                green.append(f"Price implies only ~{pct(ig)}/yr FCF growth vs {pct(rev_cagr)} historical revenue CAGR")
    return red, green


# ============================================================ formatting
def money(v):
    if v is None:
        return "n/a"
    a, s = abs(v), "-" if v < 0 else ""
    for div_, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div_:
            return f"{s}{a / div_:.2f}{suf}"
    return f"{s}{a:.0f}"


def pct(v):
    if v is None:
        return "n/a"
    return "0.0%" if abs(v) < 0.0005 else f"{v * 100:.1f}%"


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
    """spec: [(label, key, formatter, cagr_value_or_None)]"""
    rows = []
    for label, key, f, extra in spec:
        row = [label] + [f(p.get(key)) for p in periods]
        if extra is not False:
            row.append(extra if isinstance(extra, str) else "")
        rows.append(row)
    return rows


def fy_label(e):
    return f"{e['fy']} (ended, not yet reported)" if e.get("ended") else e["fy"]


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _band_lines(band, name, base, years):
    """Percentile summary of a forward-multiple history. name: 'P/E' or 'EV/EBITDA'; base: 'EPS' or 'EBITDA'."""
    out = [f"{years}-year forward {name} on next-12-month {base}: 25th percentile {mult(band['p25'])}, median "
           f"{mult(band['median'])}, 75th percentile {mult(band['p75'])} (10th-90th {mult(band['p10'])} - "
           f"{mult(band['p90'])}; {band['n']} trading days, {band['from']} to {band['to']})."]
    if band["now"] is not None:
        n = round(band["now_pct"] * 100)
        where = ("below every day of that history" if band["now_pct"] == 0 else
                 "above every day of that history" if band["now_pct"] == 1 else
                 f"at the {_ordinal(min(max(n, 1), 99))} percentile of that history")
        out.append(f"Today's forward {name}: {mult(band['now'])}, {where}.")
    if band["p75"] > 1.6 * band["p25"]:
        out.append(f"The forward {name} history is wide ({mult(band['p25'])} - {mult(band['p75'])} between the 25th and "
                   f"75th percentiles), often after an earnings trough or a re-rating; lean on the Base column.")
    return out


def _when(pt):
    return "Now" if pt["at"] == "now" else f"FY{pt['fy']} end"


def _uses(pt, fmt):
    """The next-12-month figure a row uses, and where it comes from."""
    if pt["at"] == "now":
        w = round(pt["weight"] * 100)
        return f"{fmt(pt['val'])} ({w}% FY{pt['uses'][0]} + {100 - w}% FY{pt['uses'][1]})"
    return f"{fmt(pt['val'])} (FY{pt['uses'][0]} est.)"


def _fwd_table(points, key, val_key, header, fmt, today_header):
    rows = []
    for pt in points:
        m = pt[key] or {}
        rows.append([_when(pt), pt["date"], _uses(dict(pt, val=pt[val_key]), fmt), per_share(m.get("low")),
                     per_share(m.get("base")), per_share(m.get("high")), per_share(m.get("at_today")),
                     pct(m.get("base_vs_price"))])
    return table(["When", "Date", header, "Low", "Base", "High", today_header, "Base vs price"], rows)


def render_price_range(r):
    pr, a = r["price_range"], r["analyst"]
    pb, eb, pts, yrs = pr["pe_band"], pr["ev_band"], pr["forward"], pr["lookback_years"]
    vol = pr.get("volatility")
    by_at = {(p["at"], p["fy"]): p for p in pts}
    out = [f"Current price {per_share(pr['price'])}. Each row is the range one method gives; none of them is a forecast."]
    names = {"dcf": "DCF", "targets": "Analyst price targets (12-month)", "week52": "52-week closing range"}
    rows = []
    for s in pr["summary"]:
        k = s["kind"]
        pt = by_at.get((s.get("at"), s.get("fy")))
        if k in ("fwd_pe", "fwd_ev"):
            pe = k == "fwd_pe"
            band, base = (pb, "EPS") if pe else (eb, "EBITDA")
            val = pt["eps"] if pe else pt["ebitda"]
            src = "next-12-month" if pt["at"] == "now" else f"FY{pt['uses'][0]}"
            name = f"Forward {'P/E' if pe else 'EV/EBITDA'}, {_when(pt).lower() if pt['at'] == 'now' else _when(pt)}"
            basis = (f"{src} {base} {per_share(val) if pe else money(val)} x {mult(band['p25'])} / "
                     f"{mult(band['median'])} / {mult(band['p75'])}" + ("" if pe else ", less net debt"))
        elif k == "volatility":
            name = f"Volatility to FY{s['fy']} end (68%)" if s.get("fy") else "1-year volatility (68%)"
            basis = (f"+/-1 sd at {pct(vol['sigma'])} a year ({'implied' if vol['implied'] else 'realized'}); "
                     f"95%: {per_share(s['low95'])} - {per_share(s['high95'])}")
        else:
            name = names[k]
            basis = {"dcf": "discount +/-1pt, growth +/-2pt", "targets": "low / consensus / high"}.get(k) or \
                f"daily closes {pr['week52']['from']} to {pr['week52']['to']}"
        rows.append([name, per_share(s["low"]), "-" if k == "week52" else per_share(s["mid"]), per_share(s["high"]), basis])
    if rows:
        out.append(table(["Method", "Low", "Mid", "High", "Basis"], rows))
    else:
        out.append("No method had enough data for a range.")

    out.append("\n### Forward P/E (next-12-month EPS)")
    if not pts:
        out.append("Needs analyst estimates for the current and next fiscal years (not on this FMP plan or none "
                   "published); forward multiple ranges not available.")
    elif pr["band_note"]:
        out.append(pr["band_note"])
    elif not pb:
        out.append("Not enough positive-earnings price history for a P/E range (needs about 6 months).")
    if pts and pb:
        out += _band_lines(pb, "P/E", "EPS", yrs)
        out.append(_fwd_table(pts, "pe", "eps", "EPS used", per_share, "At today's P/E"))
        out.append("\nForward P/E each day = close / next-12-month EPS: the fiscal year in progress and the one after it, "
                   "weighted by the time left in the year (reported EPS once a year is reported, the analysts' average "
                   "otherwise). This is how published forward P/E histories are built; a single fiscal year's EPS would "
                   "make the multiple jump at every year end for a fast grower and skew the range.")
        out.append("Low / Base / High = EPS used x the 25th-percentile / median / 75th-percentile forward P/E. Now = a "
                   "fair-value range for today. At a fiscal year end the next 12 months are exactly the following "
                   "fiscal year, so those rows use that year's average estimate: a fair-value range for that date if "
                   "the company earns it and trades at its usual multiple. Not a forecast.")
        out.append("At today's P/E = EPS used x today's forward P/E: where the price would be if the multiple stays "
                   "where it is (earnings growth only, no re-rating).")
        last = pts[-1]
        if last["at"] == "fy_end" and len(pts) == 3:
            out.append(f"The FY{last['fy']} end row rests on the FY{last['uses'][0]} consensus"
                       + (f" ({int(last['analysts'])} analysts)" if last.get("analysts") else "")
                       + ", which is further out and less reliable.")
        elif len(pts) == 2:
            nfy = pts[-1]["uses"][0]
            out.append(f"No analyst estimate for the year after FY{nfy}, so no range at the end of FY{nfy}.")
        if any(p["pe"] is None for p in pts):
            out.append("n/a = zero or negative EPS in the period used, so a P/E-based price is not meaningful.")
        gap = a.get("eps_basis")
        if gap and abs(gap["gap"]) > 0.05:
            out.append(f"Analysts' {gap['fy']} EPS ({per_share(gap['estimate'])}) differs from reported diluted EPS "
                       f"({per_share(gap['reported'])}) by {pct(gap['gap'])}: the estimates may be on an adjusted (non-GAAP) "
                       f"basis, while the P/E history uses reported EPS, so the forward P/E prices may run "
                       f"{'high' if gap['gap'] > 0 else 'low'}.")
    if r["sector_kind"] == "reit":
        out.append("REIT: net-income P/E understates cash earnings, so the P/E rows are a weak guide here.")
    rep_ccy, px_ccy = r["years"][-1].get("currency"), r["profile"].get("currency")
    if pts and (pb or eb) and rep_ccy and px_ccy and rep_ccy != px_ccy:
        out.append(f"Statements are in {rep_ccy} and the price in {px_ccy}: the P/E rows assume a steady exchange "
                   f"rate and analysts' EPS in {rep_ccy} per share; check both before relying on them.")

    if pts and not pr["band_note"] and r["sector_kind"] != "financial":
        out.append("\n### Forward EV/EBITDA (next-12-month EBITDA)")
        if not eb:
            out.append("Not available: no analyst EBITDA estimates, no net debt figure, or not enough positive-EBITDA "
                       "price history.")
        else:
            out += _band_lines(eb, "EV/EBITDA", "EBITDA", yrs)
            out.append(_fwd_table(pts, "ev", "ebitda", "EBITDA used", money, "At today's EV/EBITDA"))
            out.append("\nEV each day = price x shares + net debt + minority interest of the latest reported fiscal year; "
                       "next-12-month EBITDA as for EPS above. Price = (multiple x EBITDA used - today's net debt and "
                       "minority interest) / today's shares. Columns as in the P/E table. EV/EBITDA looks through "
                       "leverage and tax, so it is a cross-check on the P/E rows.")
            if any(p["ev"] is None for p in pts):
                out.append("n/a = no positive EBITDA estimate for that period.")
            gap = a.get("ebitda_basis")
            if gap and abs(gap["gap"]) > 0.10:
                out.append(f"Analysts' {gap['fy']} EBITDA ({money(gap['estimate'])}) differs from reported EBITDA "
                           f"({money(gap['reported'])}) by {pct(gap['gap'])}: the estimates may be on an adjusted basis "
                           f"(for example before stock-based compensation), so the EV/EBITDA prices may run "
                           f"{'high' if gap['gap'] > 0 else 'low'}.")

    if vol:
        out.append("\n### Volatility range to each fiscal year end")
        src = ("implied volatility you entered" if vol["implied"] else
               "realized: standard deviation of the past year's daily moves, annualized")
        out.append(f"Volatility {pct(vol['sigma'])} a year ({src}).")
        out.append(table(["To", "Date", "Years", "68% range (+/-1 sd)", "95% range (+/-1.96 sd)"],
                         [[f"FY{b['fy']} end" if b["fy"] else "1 year", b["end"], f"{b['years']:.2f}",
                           f"{per_share(b['low'])} - {per_share(b['high'])}",
                           f"{per_share(b['low95'])} - {per_share(b['high95'])}"] for b in vol["bands"]]))
        out.append("\nA statistical range around today's price (lognormal, no drift), not a valuation: about two in "
                   "three outcomes at that date fall inside the 68% range if volatility holds. Real returns have fatter "
                   "tails, so moves beyond the 95% range happen more often than 1 in 20. Options-implied volatility "
                   "is the market's own forward estimate and usually beats the past year's; enter it with --iv "
                   "(e.g. 0.45 for 45%).")
    return "\n".join(out)


def render(r):
    out = []
    pr, years, basis, cur = r["profile"], r["years"], r["basis"], r["current"]
    periods = years + ([r["ttm"]] if r["ttm"] else [])
    heads = [p["label"] for p in periods]
    ccy = years[-1].get("currency") or pr.get("currency") or ""

    out.append(f"# {r['symbol']} - {pr.get('companyName', '')}")
    out.append(f"{pr.get('sector') or 'n/a'} / {pr.get('industry') or 'n/a'} | {pr.get('country') or ''} "
               f"{pr.get('exchange') or pr.get('exchangeShortName') or ''} | Price {per_share(cur['price'])} {pr.get('currency') or ''} "
               f"| Market cap {money(cur['market_cap'])} | Beta {ratio(num(pr, 'beta'))} "
               f"| Employees {pr.get('fullTimeEmployees') or 'n/a'}")
    ttm_txt = f" + TTM to {r['ttm']['date']}" if r["ttm"] else " (TTM unavailable: using last fiscal year)"
    out.append(f"\nData basis: annual {years[0]['label']}-{years[-1]['label']} in {ccy}{ttm_txt}. "
               f"Valuation uses {basis['label']} figures. As of {r['as_of']}.")
    if r["sector_note"]:
        out.append(f"\n**Sector note:** {r['sector_note']}")
    desc = (pr.get("description") or "").strip()
    if desc:
        out.append("\n" + (desc[:600] + ("..." if len(desc) > 600 else "")))

    cg = r["cagr"]
    out.append(f"\n## 1. Growth ({len(years) - 1}-year CAGR in last column)")
    out.append(table(["Metric"] + heads + ["CAGR"], metric_rows(periods, [
        ("Revenue", "revenue", money, pct(cg["revenue"])),
        ("Revenue YoY", "revenue_yoy", pct, ""),
        ("Gross profit", "gross_profit", money, pct(cg["gross_profit"])),
        ("Operating income", "operating_income", money, pct(cg["operating_income"])),
        ("Net income", "net_income", money, pct(cg["net_income"])),
        ("EPS (diluted)", "eps", per_share, pct(cg["eps"])),
        ("EPS YoY", "eps_yoy", pct, ""),
        ("Free cash flow", "fcf", money, pct(cg["fcf"])),
        ("Diluted shares", "shares", money, pct(cg["shares"])),
    ])))

    out.append("\n## 2. Profitability & returns")
    out.append(table(["Metric"] + heads, metric_rows(periods, [
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
    out.append(table(["Metric"] + heads, metric_rows(periods, [
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
    out.append(table(["Metric"] + heads, metric_rows(periods, [
        ("Operating cash flow", "ocf", money, False),
        ("Capex", "capex", money, False),
        ("Capex % revenue", "capex_pct", pct, False),
        ("FCF / net income", "fcf_conversion", ratio, False),
        ("Stock comp % revenue", "sbc_pct", pct, False),
        ("Buybacks", "buybacks", money, False),
        ("Dividends", "dividends", money, False),
        ("Share count YoY", "shares_yoy", pct, False),
    ])))

    out.append(f"\n## 5. Valuation (price {per_share(cur['price'])}, {basis['label']} fundamentals)")
    hc = r["history_compare"]
    rows = []
    for k, name in (("pe", "P/E"), ("ev_ebitda", "EV/EBITDA"), ("ps", "P/S"), ("p_fcf", "P/FCF"), ("pb", "P/B")):
        h = hc.get(k, {})
        rng = f"{mult(h.get('min'))} - {mult(h.get('max'))}" if h.get("n") else "n/a"
        rows.append([name, mult(cur.get(k)), mult(h.get("median")), rng, pct(h.get("vs_median"))])
    out.append(table(["Multiple", "Now", "Hist. median", "Hist. range", "Now vs median"], rows))
    out.append("\n(History = price on each fiscal-year-end date x that year's fundamentals.)")
    out.append(table(["Measure", "Value"], [
        ["Enterprise value", money(cur["enterprise_value"])],
        ["EV / sales", mult(cur["ev_sales"])],
        ["Earnings yield", pct(cur["earnings_yield"])],
        ["FCF yield", pct(cur["fcf_yield"])],
        ["Dividend yield (cash paid)", pct(cur["dividend_yield"])],
        ["Shareholder yield (div + buyback - issuance)", pct(cur["shareholder_yield"])],
        [f"PEG (P/E / {len(years) - 1}y EPS CAGR)", ratio(r["peg"])],
    ]))

    out.append("\n## 6. Quality scores")
    pio = r["piotroski"]
    if pio:
        out.append(f"**Piotroski F-score {pio['year']}: {pio['score']} / {pio['out_of']}** (7-9 strong, 0-3 weak)")
        out.append(table(["Test", "Result"], [[t["test"], {True: "pass", False: "fail", None: "n/a"}[t["pass"]]]
                                              for t in pio["tests"]]))
    else:
        out.append("Piotroski F-score: needs at least 2 fiscal years.")
    alt = r["altman"]
    if alt:
        parts = []
        if "z" in alt:
            parts.append(f"Altman Z {alt['z']:.2f} ({alt['z_zone']}; >2.99 safe, <1.81 distress)")
        if "z_double_prime" in alt:
            parts.append(f"Z'' (non-manufacturer) {alt['z_double_prime']:.2f} ({alt['z2_zone']}; >2.6 safe, <1.1 distress)")
        out.append("\n" + " | ".join(parts))
    if r["sector_kind"] == "financial":
        out.append("(Altman Z is not designed for banks/insurers; ignore it here.)")

    out.append("\n## 7. DCF (FCF-based, 10 years + terminal)")
    d = r["dcf"]
    if "skipped" in d:
        out.append(d["skipped"])
    else:
        out.append(table(["Assumption", "Value"], [
            ["Starting FCF", f"{money(d['fcf_start'])} ({d['fcf_start_basis']})"],
            ["Growth yrs 1-5", f"{pct(d['growth_1_5'])} ({d['growth_source']})"],
            ["Growth yrs 6-10", f"fades linearly to terminal {pct(d['terminal_growth'])}"],
            ["Discount rate", f"{pct(d['discount_rate'])} ({d['discount_source']})"],
            ["Net debt deducted", money(d["net_debt"])],
            ["Shares", money(d["shares"])],
        ]))
        out.append(f"\n**Base-case value {per_share(d['value_per_share'])} per share vs price {per_share(cur['price'])} "
                   f"-> {pct(d['margin_of_safety'])} {'upside' if (d['margin_of_safety'] or 0) >= 0 else 'downside'}.** "
                   f"Reasonable range (discount +/-1pt, growth +/-2pt): {per_share(d['range_low'])} - {per_share(d['range_high'])}. "
                   f"Terminal value is {pct(d['terminal_value_share'])} of the total.")
        if d.get("value_at_fixed_rate") is not None:
            out.append(f"(At the previous fixed {pct(M.FALLBACK_DISCOUNT)} discount rate the base case would be "
                       f"{per_share(d['value_at_fixed_rate'])} per share.)")
        grid_rows = [[pct(rr)] + [per_share(v) for v in row] for rr, row in zip(d["grid_rates"], d["grid"])]
        out.append("\nValue per share (rows = discount rate, columns = growth yrs 1-5):")
        out.append(table(["r \\ g"] + [pct(g) for g in d["grid_growths"]], grid_rows))
        if d["implied_growth"] is not None:
            out.append(f"\n**Reverse DCF:** today's price implies ~{pct(d['implied_growth'])} FCF growth per year for "
                       f"5 years (then fading), at a {pct(d['discount_rate'])} discount rate.")
        else:
            out.append(f"\nReverse DCF: implied growth {d['implied_growth_note']}.")

    out.append("\n## 8. Analyst consensus")
    a = r["analyst"]
    if a.get("estimates"):
        out.append(table(["FY", "EPS est. (low-high)", "Fwd P/E", "Revenue est.", "Rev. growth", "# analysts"],
                         [[fy_label(e), f"{per_share(e['eps_avg'])} ({per_share(e['eps_low'])}-{per_share(e['eps_high'])})",
                           mult(e["forward_pe"]), money(e["revenue_avg"]), pct(e["revenue_growth"]),
                           "n/a" if e["analysts"] is None else int(e["analysts"])] for e in a["estimates"]]))
    if a.get("price_target"):
        pt = a["price_target"]
        out.append(f"\nPrice target consensus {per_share(pt['consensus'])} (median {per_share(pt['median'])}, "
                   f"range {per_share(pt['low'])}-{per_share(pt['high'])}) -> {pct(pt['upside'])} vs price.")
    if not a:
        out.append("Not available on this FMP plan.")

    out.append("\n## 9. Price range (forward P/E and EV/EBITDA, DCF, analyst targets, volatility)")
    out.append(render_price_range(r))

    out.append("\n## 10. Peer comparison (last fiscal year, same method for all)")
    if r["peers"]:
        prow = []
        for p in [r["self_snapshot"]] + r["peers"]:
            if "error" in p:
                prow.append([p["symbol"], p["error"]] + [""] * 9)
                continue
            prow.append([p["symbol"] + (" *" if p is r["self_snapshot"] else ""), money(p["market_cap"]),
                         mult(p["pe"]), mult(p["ev_ebitda"]), mult(p["ps"]), mult(p["p_fcf"]),
                         pct(p["revenue_yoy"]), pct(p["gross_margin"]), pct(p["operating_margin"]),
                         pct(p["roic"]), mult(p["net_debt_to_ebitda"])])
        ok = [p for p in r["peers"] if "error" not in p]
        if ok:
            prow.append(["Peer median", money(median([p["market_cap"] for p in ok]))] +
                        [f(median([p[k] for p in ok])) for k, f in (
                            ("pe", mult), ("ev_ebitda", mult), ("ps", mult), ("p_fcf", mult),
                            ("revenue_yoy", pct), ("gross_margin", pct), ("operating_margin", pct),
                            ("roic", pct), ("net_debt_to_ebitda", mult))])
        out.append(table(["Ticker", "Mkt cap", "P/E", "EV/EBITDA", "P/S", "P/FCF", "Rev YoY",
                          "Gross m.", "Op m.", "ROIC", "ND/EBITDA"], prow))
    else:
        out.append("No peers (FMP stock-peers not available on this plan, or --peers none). "
                   "Re-run with --peers TICKER1,TICKER2 to compare.")

    sec = 11
    mk = r.get("market") or {}
    if mk.get("sector"):
        out.append(f"\n## {sec}. Sector & industry context")
        out.append(M.render_sector_context(mk["sector"], r["symbol"]))
        sec += 1
    if mk.get("macro"):
        out.append(f"\n## {sec}. Rates & macro backdrop")
        out.append(M.render_macro(mk["macro"]))
        sec += 1

    out.append(f"\n## {sec}. Automated flags (prompts for investigation, not conclusions)")
    out.append("**Positives**")
    out += [f"- {g}" for g in r["flags"]["green"]] or ["- none triggered"]
    out.append("\n**Concerns**")
    out += [f"- {x}" for x in r["flags"]["red"]] or ["- none triggered"]

    m = r["meta"]
    out.append("\n## Data notes")
    conn = m["connection"]
    if conn["route"].startswith("official"):
        out.append("- Data route: official FMP API.")
    else:
        out.append(f"- Data route: {conn['route']}. Data is not served by FMP directly; "
                   f"spot-check key figures against company filings.")
    if not conn["tls_verify"]:
        out.append("- HTTPS certificate verification was OFF for this run.")
    out.append(f"- API calls: {m['network_calls']} network, {m['cache_hits']} from cache.")
    fixed = str((r.get("dcf") or {}).get("discount_source", "")).startswith("fixed default")
    if not r.get("market"):
        out.append("- Treasury, sector and industry data skipped (--no-market).")
    elif mk.get("rates"):
        out.append(f"- Treasury yields as of {mk['rates']['date']} (FMP treasury-rates).")
        if mk.get("erp") is None:
            out.append("- US equity risk premium unavailable" +
                       (": DCF used the fixed default discount rate." if fixed else "."))
    else:
        missing = "Treasury yields" + (" and US equity risk premium" if mk.get("erp") is None else "")
        out.append(f"- {missing} unavailable" + (": DCF used the fixed default discount rate." if fixed else "."))
    if m["restricted"]:
        out.append(f"- Skipped (not in your FMP plan): {', '.join(m['restricted'])}")
    for e in dict.fromkeys(m["errors"]):
        out.append(f"- Error: {e}")
    out.append("- Source: Financial Modeling Prep. Computed figures are approximations; verify against filings before acting.")
    return "\n".join(out)


# ============================================================ main
def fetch_prices(client, sym, start, end):
    try:
        return client.prices(sym, start, end)
    except FMPError as e:
        client.add_error(f"price history: {e}")
        return []


def max_workers():
    try:
        return max(1, int(os.environ.get("FMP_MAX_WORKERS") or 6))
    except ValueError:
        return 6


def analyze(args):
    sym = args.symbol.upper()
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
        f_pt = submit(client.try_get, "price-target-consensus", symbol=sym)
        f_peer_syms = submit(peer_symbols, client, sym, args.peers, args.max_peers)
        market_reqs = {}
        if not args.no_market:
            market_reqs.update(M.rates_requests(client, today))
            market_reqs.update(M.sector_requests(client, profile, today))
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
        est, pt = f_est.result(), f_pt.result()
        peers = [peer_snapshot(s, *(f.result() for f in fs)) for s, fs in f_peers]
        market_res = {k: f.result() for k, f in f_market.items()}
    except BaseException:
        for f in futures:
            f.cancel()
        raise
    finally:
        pool.shutdown(wait=True)

    if ttm and ttm["date"] <= years[-1]["date"]:
        ttm = None  # latest quarter is the fiscal year end; annual data is already current
    basis = ttm or years[-1]

    sector = (profile.get("sector") or "").strip().lower()
    industry = (profile.get("industry") or "").lower()
    sector_kind, sector_note = "general", ""
    if sector in FINANCIAL_SECTORS or any(w in industry for w in ("bank", "insurance", "capital markets")):
        sector_kind = "financial"
        sector_note = ("Financial company: gross margin, EV-based multiples, FCF, DCF and Altman Z are not "
                       "meaningful. Focus on ROE, P/B, P/E, book-value growth and leverage.")
    elif sector in REAL_ESTATE_SECTORS or "reit" in industry:
        sector_kind = "reit"
        sector_note = ("REIT: net income understates cash earnings (depreciation). Use P/FCF or operating "
                       "cash flow as an FFO proxy; leverage is structurally higher.")

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
                  "sector": M.sector_context(market_res, profile, current["pe"], series, hist_cmp.get("pe"), today)}
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
    peg = pos_div(current["pe"], cg["eps"] * 100) if cg["eps"] and cg["eps"] > 0 else None

    pio = piotroski(years)
    alt = altman(years[-1], mcap)
    dcf = run_dcf(years, basis, current, args, cg["revenue"], sector_kind, rate, rate_src)
    analyst = analyst_view(est, pt, years[-1], price, today.isoformat())
    ranges = price_range(years, basis, series, analyst, dcf, price, today, div(mcap, price), iv=args.iv,
                         sector_kind=sector_kind)
    red, green = make_flags(years, current, hist_cmp, pio, alt, dcf, cg["revenue"], sector_kind)

    return {
        "symbol": sym, "as_of": today.isoformat(), "profile": profile,
        "sector_kind": sector_kind, "sector_note": sector_note,
        "years": years, "ttm": ttm, "basis": basis, "current": current, "cagr": cg, "peg": peg,
        "valuation_history": hist, "history_compare": hist_cmp,
        "piotroski": pio, "altman": alt, "dcf": dcf, "analyst": analyst, "price_range": ranges,
        "self_snapshot": lfy_snapshot(profile, years), "peers": peers,
        "flags": {"red": red, "green": green},
        "market": market,
        "price_series": series,  # daily closes used for valuation history (the UI charts the last year)
        "meta": {"network_calls": client.stats["network_calls"], "cache_hits": client.stats["cache_hits"],
                 "restricted": client.restricted, "errors": client.errors,
                 "connection": client.describe()},
    }


def parse_args(argv):
    ap = argparse.ArgumentParser(description="FMP fundamental analysis snapshot")
    ap.add_argument("symbol")
    ap.add_argument("--years", type=int, default=5)
    ap.add_argument("--peers", default=None)
    ap.add_argument("--max-peers", type=int, default=5)
    ap.add_argument("--discount", type=float, default=None)
    ap.add_argument("--terminal", type=float, default=0.025)
    ap.add_argument("--growth", type=float, default=None)
    ap.add_argument("--fcf-base", choices=("latest", "avg3"), default="latest")
    ap.add_argument("--iv", type=float, default=None)
    ap.add_argument("--no-ttm", action="store_true")
    ap.add_argument("--macro", action="store_true")
    ap.add_argument("--no-market", action="store_true")
    ap.add_argument("--json", default=None)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    if a.macro and a.no_market:
        ap.error("--macro needs the market data that --no-market skips; use one or the other")
    if a.iv is not None and not 0 < a.iv < 5:
        ap.error("--iv is annual volatility as a decimal, e.g. 0.45 for 45%")
    return a


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = analyze(args)
    except InvalidKey as e:
        print(f"API key problem: {e}", file=sys.stderr)
        return 2
    except FMPError as e:
        print(f"FMP error: {e}", file=sys.stderr)
        return 1
    print(render(result))
    if args.json:
        out = {k: v for k, v in result.items() if k != "price_series"}
        Path(args.json).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"\n(JSON written to {args.json})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
