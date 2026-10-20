"""
Offline stand-in for the FMP API, for tests and for trying the UI without a key.

FakeClient is an FMPClient whose HTTP layer answers from synthetic data built here, so analyze() runs
end to end (statements, estimates, prices, Treasury yields, industry P/E) with no network. Endpoints a
scenario does not provide answer as "not in your plan", like a restricted FMP plan.

Scenarios:
  QUAL  a growing, profitable, net-cash company whose forward P/E sits near the bottom of its range
  TRAP  a shrinking, indebted company burning cash, on a low multiple
  BANK  a regional bank (financial-sector rules)
  EXCH  an exchange / data company: in the financial sector, but analysed like other companies
  UTIL  a regulated utility: capex above operating cash flow (negative FCF), high leverage
"""
from __future__ import annotations

import datetime as dt
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fmp_client import FMPClient, RestrictedEndpoint  # noqa: E402

TODAY = dt.date.today()
LAST_FY = TODAY.year - 1  # fiscal years end on Dec 31; the year in progress is TODAY.year


def _days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def _company(sym, revenue, gm, om, shares, cash, debt, sbc_pct, fcf_ratio, interest, eps_growth_est,
             rev_growth_est, multiple_now, multiple_mid, sector, industry, beta=1.1, equity_ratio=0.45, asset_turn=1.6):
    """Five fiscal years of statements and the matching market data. revenue / gm / om / shares / cash /
    debt / fcf_ratio are per-year lists, oldest first."""
    inc, bs, cf = [], [], []
    for i, fy in enumerate(range(LAST_FY - 4, LAST_FY + 1)):
        date = f"{fy}-12-31"
        rev = revenue[i]
        op = rev * om[i]
        pretax = op - interest[i]
        tax = max(pretax, 0) * 0.18
        ni = pretax - tax
        assets = rev * asset_turn
        equity = assets * equity_ratio
        inc.append({"date": date, "fiscalYear": str(fy), "reportedCurrency": "USD", "revenue": rev,
                    "grossProfit": rev * gm[i], "operatingIncome": op, "ebitda": op + rev * 0.04, "ebit": op,
                    "depreciationAndAmortization": rev * 0.04, "netIncome": ni, "epsDiluted": ni / shares[i],
                    "weightedAverageShsOutDil": shares[i], "interestExpense": interest[i],
                    "incomeBeforeTax": pretax, "incomeTaxExpense": tax, "researchAndDevelopmentExpenses": rev * 0.1})
        bs.append({"date": date, "fiscalYear": str(fy), "cashAndShortTermInvestments": cash[i], "totalDebt": debt[i],
                   "longTermDebt": debt[i] * 0.9, "totalCurrentAssets": rev * 0.6, "totalCurrentLiabilities": rev * 0.35,
                   "inventory": rev * 0.05, "totalAssets": assets, "totalLiabilities": assets - equity,
                   "totalStockholdersEquity": equity, "retainedEarnings": equity * 0.7, "minorityInterest": 0,
                   "goodwillAndIntangibleAssets": rev * 0.1})
        ocf = ni * fcf_ratio[i] + rev * 0.05
        cf.append({"date": date, "fiscalYear": str(fy), "operatingCashFlow": ocf, "capitalExpenditure": -rev * 0.05,
                   "freeCashFlow": ocf - rev * 0.05, "stockBasedCompensation": rev * sbc_pct,
                   "commonStockRepurchased": -rev * 0.03, "commonDividendsPaid": -rev * 0.01,
                   "depreciationAndAmortization": rev * 0.04})
    eps = [r["epsDiluted"] for r in inc]
    est, e, rv = [], eps[-1], revenue[-1]
    for k, fy in enumerate(range(LAST_FY + 1, LAST_FY + 4)):
        e *= 1 + eps_growth_est[k]
        rv *= 1 + rev_growth_est[k]
        est.append({"symbol": sym, "date": f"{fy}-12-31", "epsAvg": e, "epsLow": e * 0.9, "epsHigh": e * 1.1,
                    "revenueAvg": rv, "ebitdaAvg": rv * (om[-1] + 0.04), "numAnalystsEps": 20 - 4 * k})

    # Daily closes: forward P/E x next-twelve-month EPS, the multiple swinging around multiple_mid over the
    # last three years and ending at multiple_now.
    fy_eps = [(dt.date(LAST_FY - 4 + i, 12, 31), v) for i, v in enumerate(eps)] + \
             [(dt.date(LAST_FY + 1 + k, 12, 31), x["epsAvg"]) for k, x in enumerate(est)]

    def ntm(d):
        for (d0, a), (_, b) in zip(fy_eps, fy_eps[1:]):
            if d <= d0:
                w = min((d0 - d).days / 365.25, 1.0)
                return w * a + (1 - w) * b
        return fy_eps[-1][1]
    rnd = random.Random(sym)
    start, prices = dt.date(LAST_FY - 4, 12, 20), []
    days = list(_days(start, TODAY))
    for j, d in enumerate(days):
        left = (len(days) - 1 - j) / 252  # years before today
        m = multiple_mid + (multiple_mid * 0.22) * math.sin(left * 2 * math.pi / 1.4 + 1.3)
        m += (multiple_now - m) * math.exp(-left * 6)  # glide to today's multiple
        m *= 1 + rnd.gauss(0, 0.01)
        prices.append((d.isoformat(), round(max(ntm(d), 0.05) * m, 2)))
    price = prices[-1][1]
    profile = {"symbol": sym, "companyName": f"{sym} Test Corp", "price": price, "marketCap": price * shares[-1],
               "beta": beta, "sector": sector, "industry": industry, "exchange": "NASDAQ",
               "exchangeShortName": "NASDAQ", "currency": "USD", "country": "US", "fullTimeEmployees": "1000",
               "description": f"Synthetic company used by the offline tests ({sym}).", "changePercentage": 0.5}
    return {"profile": profile, "inc": inc, "bs": bs, "cf": cf, "est": est, "prices": prices,
            "target": {"targetConsensus": price * 1.2, "targetMedian": price * 1.18, "targetHigh": price * 1.5,
                       "targetLow": price * 0.9}}


def _scenarios():
    g = [1.0, 1.12, 1.25, 1.40, 1.57]
    qual = _company("QUAL", revenue=[100e9 * x for x in g], gm=[0.60, 0.61, 0.60, 0.61, 0.61],
                    om=[0.30, 0.31, 0.32, 0.33, 0.33], shares=[1.00e9, 0.99e9, 0.98e9, 0.97e9, 0.96e9],
                    cash=[40e9] * 5, debt=[20e9] * 5, sbc_pct=0.025, fcf_ratio=[1.1] * 5, interest=[0.8e9] * 5,
                    eps_growth_est=[0.12, 0.12, 0.11], rev_growth_est=[0.11, 0.10, 0.10],
                    multiple_now=19.0, multiple_mid=26.0, sector="Technology", industry="Software - Application")
    s = [1.0, 0.97, 0.93, 0.88, 0.84]
    trap = _company("TRAP", revenue=[20e9 * x for x in s], gm=[0.30, 0.28, 0.27, 0.25, 0.24],
                    om=[0.08, 0.07, 0.05, 0.035, 0.03], shares=[0.50e9, 0.52e9, 0.54e9, 0.57e9, 0.60e9],
                    cash=[1e9] * 5, debt=[9e9, 9.5e9, 10e9, 10.5e9, 11e9], sbc_pct=0.01,
                    fcf_ratio=[0.9, 0.6, 0.3, -2.5, -3.0], interest=[0.45e9, 0.5e9, 0.55e9, 0.6e9, 0.62e9],
                    eps_growth_est=[0.02, 0.03, 0.03], rev_growth_est=[-0.03, -0.01, 0.0],
                    multiple_now=7.0, multiple_mid=10.0, sector="Consumer Cyclical", industry="Department Stores",
                    equity_ratio=0.2)
    b = [1.0, 1.05, 1.10, 1.16, 1.21]
    bank = _company("BANK", revenue=[10e9 * x for x in b], gm=[1.0] * 5, om=[0.32] * 5,
                    shares=[0.30e9] * 5, cash=[30e9] * 5, debt=[40e9] * 5, sbc_pct=0.01, fcf_ratio=[1.0] * 5,
                    interest=[0.0] * 5, eps_growth_est=[0.05, 0.06, 0.06], rev_growth_est=[0.04, 0.04, 0.04],
                    multiple_now=11.0, multiple_mid=12.0, sector="Financial Services", industry="Banks - Regional",
                    equity_ratio=0.10, asset_turn=15.0)
    exch = _company("EXCH", revenue=[5e9 * x for x in g], gm=[0.80] * 5, om=[0.50] * 5, shares=[0.10e9] * 5,
                    cash=[1e9] * 5, debt=[4e9] * 5, sbc_pct=0.02, fcf_ratio=[1.1] * 5, interest=[0.15e9] * 5,
                    eps_growth_est=[0.10, 0.10, 0.10], rev_growth_est=[0.10, 0.09, 0.09],
                    multiple_now=28.0, multiple_mid=30.0, sector="Financial Services",
                    industry="Financial - Data & Stock Exchanges")
    u = [1.0, 1.04, 1.08, 1.12, 1.17]
    util = _company("UTIL", revenue=[30e9 * x for x in u], gm=[0.45] * 5, om=[0.25] * 5, shares=[0.75e9 + 0.01e9 * i for i in range(5)],
                    cash=[1e9] * 5, debt=[44e9, 46e9, 48e9, 50e9, 52e9], sbc_pct=0.003, fcf_ratio=[-0.2] * 5,
                    interest=[2.2e9, 2.3e9, 2.4e9, 2.5e9, 2.6e9], eps_growth_est=[0.06, 0.06, 0.06],
                    rev_growth_est=[0.04, 0.04, 0.04], multiple_now=16.0, multiple_mid=18.0, sector="Utilities",
                    industry="Regulated Electric", beta=0.5, equity_ratio=0.28, asset_turn=4.5)
    return {"QUAL": qual, "TRAP": trap, "BANK": bank, "EXCH": exch, "UTIL": util}


SCENARIOS = _scenarios()


def _between(rows, params):
    lo, hi = params.get("from", "0000"), params.get("to", "9999")
    return [r for r in rows if lo <= r["date"] <= hi]


def _market():
    tsy = [{"date": d.isoformat(), "month3": 4.0, "year2": 3.8, "year5": 3.9, "year10": 4.2, "year30": 4.6}
           for d in _days(TODAY - dt.timedelta(days=400), TODAY)]
    group_pe = {}
    for name, mid in (("Technology", 32.0), ("Software - Application", 34.0), ("Consumer Cyclical", 22.0),
                      ("Department Stores", 12.0), ("Financial Services", 15.0), ("Banks - Regional", 12.5),
                      ("Financial - Data & Stock Exchanges", 30.0), ("Utilities", 18.0), ("Regulated Electric", 17.0)):
        rows = []
        for j, d in enumerate(_days(TODAY - dt.timedelta(days=5 * 365 + 2), TODAY)):
            rows.append({"date": d.isoformat(), "pe": round(mid * (1 + 0.15 * math.sin(j / 90)), 2), "exchange": "NASDAQ"})
        group_pe[name] = rows
    spy = [(d.isoformat(), round(500 * (1 + 0.0004) ** j, 2)) for j, d in enumerate(_days(TODAY - dt.timedelta(days=372), TODAY))]
    return tsy, group_pe, spy


TREASURY, GROUP_PE, SPY = _market()


def answer(endpoint, params):
    """The synthetic response for one request, or raise RestrictedEndpoint."""
    sym = params.get("symbol")
    c = SCENARIOS.get(sym) if sym else None
    period = params.get("period", "annual")
    if endpoint == "profile" and c:
        return [c["profile"]]
    if endpoint in ("income-statement", "balance-sheet-statement", "cash-flow-statement") and c:
        if period != "annual":
            raise RestrictedEndpoint(f"{endpoint}: not included in your plan (quarterly)")
        rows = {"income-statement": c["inc"], "balance-sheet-statement": c["bs"], "cash-flow-statement": c["cf"]}[endpoint]
        return list(reversed(rows[-int(params.get("limit", 5)):]))
    if endpoint == "analyst-estimates" and c:
        return list(reversed(c["est"]))
    if endpoint == "price-target-consensus" and c:
        return [c["target"]]
    if endpoint == "quote" and c:
        p = c["profile"]
        return [{"symbol": sym, "price": p["price"], "marketCap": p["marketCap"], "changePercentage": 0.5}]
    if endpoint == "historical-price-eod/light":
        rows = c["prices"] if c else (SPY if sym == "SPY" else None)
        if rows is None:
            raise RestrictedEndpoint(f"{endpoint}: unknown symbol {sym}")
        return _between([{"date": d, "price": p} for d, p in rows], params)
    if endpoint == "treasury-rates":
        return list(reversed(_between(TREASURY, params)))
    if endpoint == "market-risk-premium":
        return [{"country": "United States", "totalEquityRiskPremium": 4.6}]
    if endpoint in ("historical-sector-pe", "historical-industry-pe"):
        name = params.get("sector") or params.get("industry")
        rows = GROUP_PE.get(name)
        if rows is None:
            return []
        key = "sector" if "sector" in params else "industry"
        return [dict(r, **{key: name}) for r in _between(rows, params)]
    if endpoint in ("historical-sector-performance", "historical-industry-performance"):
        return [{"date": r["date"], "averageChange": 0.03} for r in _between(TREASURY, params)]
    raise RestrictedEndpoint(f"{endpoint}: not included in your plan (offline test data)")


class FakeClient(FMPClient):
    """FMPClient answering from the synthetic scenarios above; no network, no cache."""

    def __init__(self, *a, **kw):
        kw.update(api_key="offline-test", use_cache=False)
        super().__init__(*a, **kw)

    def _fetch(self, endpoint, params):
        self._count("network_calls")
        return answer(endpoint, params)
