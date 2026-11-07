"""
Price ranges for the local page: the range each method gives for the share price, worked out from a fa-2.0
document and the past year's daily closes. Only the page shows them (ui/server.py, and the decision engine's copy
of the page): they are not part of fa-2.0 or the report, and none of them is a forecast.

One row per method and horizon (the past 52 weeks, now, the end of the fiscal year in progress and of the next):
- week52: the lowest and highest daily close of the 52 weeks to the document's date (as_of).
- fwd_pe, fwd_ev: next-twelve-month EPS or EBITDA times the 25th percentile, median and 75th percentile of the
  document's 3-year distribution of the forward multiple (valuation.forward_band). Now uses today's
  next-twelve-month figures (valuation.forward.ntm); at a fiscal year end the next twelve months are the following
  fiscal year, so that year's consensus (consensus.estimates). An EV/EBITDA becomes a price less the net debt and
  minority interest of the valuation basis period, over today's shares (market cap / price).
- dcf: models.dcf low, value per share and high (discount rate within 1 point, growth within 2 points).
- volatility: today's price moved by one standard deviation (about 68% of outcomes) and by 1.96 (about 95%) of the
  past year's daily log moves, annualized and scaled to the time left to each of those fiscal year ends (12 months
  out without estimates), with no drift.
A measure the document marks as not meaningful for the company (company.not_meaningful) gives no row, and neither
does a method whose prices are not all positive.

Standard library only: the decision engine loads this file from the installed skill.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics

MIN_MOVES = 120   # daily moves a volatility needs (about 6 months of trading days)
Z95 = 1.96        # standard deviations around the mean that hold about 95% of a normal distribution


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _shift(day, days):
    return (dt.date.fromisoformat(day) + dt.timedelta(days=days)).isoformat()


def _days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def quartiles(band):
    """[25th percentile, median, 75th percentile] of a forward multiple's distribution, or None without one."""
    q = [_num((band or {}).get(k)) for k in ("p25", "median", "p75")]
    return None if None in q else q


def basis_debt(doc):
    """(net debt, minority interest) of the valuation basis period: the TTM, else that fiscal year's column of the
    statements. Net debt is None when the document has none; a missing minority interest counts as 0."""
    basis = (doc.get("periods") or {}).get("valuation_basis")
    if basis == "TTM":
        col = doc.get("ttm") or {}
        return _num(col.get("net_debt")), _num(col.get("minority_interest")) or 0.0
    st = doc.get("statements") or {}
    periods = st.get("period") or []
    if basis not in periods:
        return None, 0.0
    i = periods.index(basis)

    def at(key):
        values = st.get(key) or []
        return _num(values[i]) if i < len(values) else None
    return at("net_debt"), at("minority_interest") or 0.0


def closes_to(closes, as_of):
    """The positive daily closes of the 52 weeks to as_of, [(date, close)] oldest first."""
    start = _shift(as_of, -365)
    out = []
    for row in closes or []:
        d, c = str(row[0])[:10], _num(row[1])
        if start <= d <= as_of and c and c > 0:
            out.append((d, c))
    return sorted(out)


def volatility(year):
    """Annualized standard deviation of the daily log moves of `year` (closes_to()), or None under MIN_MOVES."""
    moves = [math.log(b / a) for (_, a), (_, b) in zip(year, year[1:])]
    return statistics.stdev(moves) * math.sqrt(252) if len(moves) >= MIN_MOVES else None


def build(doc, closes):
    """The page's price ranges from a fa-2.0 document and daily closes [(date, close), ...]:
    {"price", "as_of",
     "rows": one per method and horizon, sorted by the horizon's date (methods in the order above within one):
        {"kind", "at": "past" | "now" | "fy_end" | "12m", "fy", "date", "low", "mid", "high", ...what it rests on},
     "pe_ranges": the header's forward P/E ranges: now, then the fiscal year in progress and the next on their own
        EPS, {"at": "now" | "fy", "fy", "low", "high", "uses": [[fy, weight in % or None], ...]},
     "dcf_vs_price": the DCF value per share / price - 1, or None}."""
    price, as_of = _num((doc.get("price") or {}).get("value")), str(doc.get("as_of") or "")[:10]
    out = {"price": price, "as_of": as_of or None, "rows": [], "pe_ranges": [], "dcf_vs_price": None}
    if not as_of:
        return out
    company = doc.get("company") or {}
    nm = set(company.get("not_meaningful") or [])
    val = doc.get("valuation") or {}
    band = val.get("forward_band") or {}
    pe_q = None if "pe" in nm else quartiles(band.get("pe"))
    ev_q = None if "ev_ebitda" in nm else quartiles(band.get("ev_ebitda"))
    ntm = (val.get("forward") or {}).get("ntm") or {}
    open_fys = sorted((e for e in (doc.get("consensus") or {}).get("estimates") or [] if not e.get("ended")),
                      key=lambda e: e.get("date") or "")
    cur, nxt, after = (open_fys + [None, None, None])[:3]
    nd, mi = basis_debt(doc)
    mcap = _num(company.get("market_cap"))
    shares = mcap / price if mcap and price else None

    # next-twelve-month points: now, and the end of the fiscal year in progress and of the next, where the next
    # twelve months are the following fiscal year
    points = []
    if cur and nxt:
        w = _num(ntm.get("weight"))
        points.append({"at": "now", "fy": None, "date": as_of, "uses": [str(f) for f in ntm.get("fys") or []],
                       "weight": w, "eps": _num(ntm.get("eps")), "ebitda": _num(ntm.get("ebitda"))})
        for end, e in ((cur, nxt), (nxt, after)):
            if e:
                points.append({"at": "fy_end", "fy": end["fy"], "date": end["date"], "uses": [e["fy"]],
                               "weight": None, "eps": _num(e.get("eps_avg")), "ebitda": _num(e.get("ebitda_avg"))})

    def multiples(pt):
        rows = []
        if pe_q and pt["eps"] and pt["eps"] > 0:
            rows.append({"kind": "fwd_pe", **_horizon(pt), **dict(zip(("low", "mid", "high"),
                         (pt["eps"] * m for m in pe_q))), "eps": pt["eps"], "uses": pt["uses"],
                         "weight": pt["weight"], "multiples": pe_q})
        if ev_q and pt["ebitda"] and pt["ebitda"] > 0 and nd is not None and shares:
            rows.append({"kind": "fwd_ev", **_horizon(pt), **dict(zip(("low", "mid", "high"),
                         ((m * pt["ebitda"] - nd - mi) / shares for m in ev_q))), "ebitda": pt["ebitda"],
                         "uses": pt["uses"], "weight": pt["weight"], "multiples": ev_q, "net_debt": nd + mi})
        return rows

    rows = []
    year = closes_to(closes, as_of)
    if len(year) >= 2:
        rows.append({"kind": "week52", "at": "past", "fy": None, "date": year[0][0], "low": min(c for _, c in year),
                     "mid": None, "high": max(c for _, c in year), "from": year[0][0], "to": year[-1][0]})
    for pt in points[:1]:
        rows += multiples(pt)
    dcf = (doc.get("models") or {}).get("dcf") or {}
    if "dcf" not in nm and dcf.get("status") == "ok":
        inputs = dcf.get("inputs") or {}
        rows.append({"kind": "dcf", "at": "now", "fy": None, "date": as_of, "low": _num(dcf.get("low")),
                     "mid": _num(dcf.get("value_per_share")), "high": _num(dcf.get("high")),
                     "discount_rate": _num((inputs.get("discount_rate") or {}).get("value")),
                     "growth": _num(inputs.get("growth_1_5"))})
        vps = _num(dcf.get("value_per_share"))
        if vps and price:
            out["dcf_vs_price"] = vps / price - 1

    sigma = volatility(year)
    vol_rows = {}
    if sigma and price:
        horizons = [(e["fy"], e["date"]) for e in (cur, nxt) if e] or [(None, _shift(as_of, 365))]
        for fy, end in horizons:
            years = max(_days(as_of, end), 1) / 365.25
            w1, w2 = sigma * math.sqrt(years), Z95 * sigma * math.sqrt(years)
            vol_rows[fy] = {"kind": "volatility", "at": "fy_end" if fy else "12m", "fy": fy, "date": end,
                            "low": price * math.exp(-w1), "mid": price, "high": price * math.exp(w1),
                            "low95": price * math.exp(-w2), "high95": price * math.exp(w2), "sigma": sigma,
                            "years": years}
    for pt in points[1:]:  # each fiscal year end: the forward multiples there, then the volatility to it
        rows += multiples(pt)
        if pt["fy"] in vol_rows:
            rows.append(vol_rows.pop(pt["fy"]))
    rows += vol_rows.values()
    # a price that is not positive (net debt above the EV a multiple gives, say) means nothing as a price
    rows = [r for r in rows if all(r[k] is not None and r[k] > 0 for k in ("low", "high"))
            and (r["mid"] is None or r["mid"] > 0)]
    out["rows"] = sorted(rows, key=lambda r: r["date"])  # stable: the method order stays within a horizon

    if pe_q:
        now = next((r for r in out["rows"] if r["kind"] == "fwd_pe" and r["at"] == "now"), None)
        if now:
            w = None if now["weight"] is None else round(now["weight"] * 100)
            out["pe_ranges"].append({"at": "now", "fy": None, "low": now["low"], "high": now["high"],
                                     "uses": [[fy, None if w is None else (w if i == 0 else 100 - w)]
                                              for i, fy in enumerate(now["uses"])]})
        for e in (cur, nxt):
            eps = _num((e or {}).get("eps_avg"))
            if eps and eps > 0:
                out["pe_ranges"].append({"at": "fy", "fy": e["fy"], "low": eps * pe_q[0], "high": eps * pe_q[2],
                                         "uses": [[e["fy"], None]]})
    return out


def _horizon(pt):
    return {"at": pt["at"], "fy": pt["fy"], "date": pt["date"]}
