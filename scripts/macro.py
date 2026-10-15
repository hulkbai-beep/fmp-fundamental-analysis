#!/usr/bin/env python3
"""
Rates, macro and sector/industry context from FMP.

analyze.py uses this module for the rate-linked (CAPM) discount rate and the sector & industry
section of each report. On its own it prints a rates & macro dashboard:

  python macro.py                  Treasury curve, Fed funds, CPI, jobs, risk premium,
                                   latest key US releases and the next ones on the calendar
  python macro.py --sectors        add every sector's P/E (vs its 5-year history) and returns
  python macro.py --events         add every US high/medium-impact calendar event in the window
  python macro.py --json out.json  also write the numbers to a JSON file
  python macro.py --refresh        ignore the local cache

Notes on the data (what the FMP stable endpoints return, checked against the proxy):
- treasury-rates returns at most ~3 months per request, so the 1-year-ago curve is a second call.
- economic-indicators returns only the two most recent values for monthly series, so CPI/PPI/PCE
  year-over-year readings come from the economic calendar (actual / estimate / previous).
- Sector and industry P/E and performance are FMP aggregates of companies listed on one exchange
  (NASDAQ by default); performance is the equal-weighted average daily change of those companies.
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
from fmp_client import FMPClient, FMPError, InvalidKey  # noqa: E402

EXCHANGES = {"NASDAQ", "NYSE", "AMEX"}
DEFAULT_SECTORS = ("Basic Materials", "Communication Services", "Consumer Cyclical",
                   "Consumer Defensive", "Energy", "Financial Services", "Healthcare",
                   "Industrials", "Real Estate", "Technology", "Utilities")
TENORS = (("month3", "3M"), ("year2", "2Y"), ("year5", "5Y"), ("year10", "10Y"), ("year30", "30Y"))
CAPM_FLOOR, CAPM_CAP = 0.07, 0.13
FALLBACK_DISCOUNT = 0.09

# Key US releases on the economic calendar: (label, pattern matched against the event name with
# its trailing "(Sep)" / "(Q3)" period removed, lower-cased). Names follow FMP's calendar
# (e.g. "Core PPI MoM (Sep)", "Fed Interest Rate Decision"); alternatives cover naming variants.
KEY_EVENTS = (
    ("Fed rate decision", r"(fed|fomc)( funds)? interest rate decision$"),
    ("CPI YoY", r"(cpi|inflation rate) yoy$"),
    ("Core CPI YoY", r"core (cpi|inflation rate) yoy$"),
    ("CPI MoM", r"(cpi|inflation rate) mom$"),
    ("Core CPI MoM", r"core (cpi|inflation rate) mom$"),
    ("PPI YoY", r"ppi yoy$"),
    ("Core PPI YoY", r"core ppi yoy$"),
    ("PPI MoM", r"ppi mom$"),
    ("Core PPI MoM", r"core ppi mom$"),
    ("PCE price index YoY", r"pce price index yoy$"),
    ("Core PCE price index YoY", r"core pce price index yoy$"),
    ("Core PCE price index MoM", r"core pce price index mom$"),
    ("Nonfarm payrolls", r"non ?farm payrolls$"),
    ("Unemployment rate", r"unemployment rate$"),
    ("GDP growth (QoQ, annualized)", r"gdp growth rate qoq"),
    ("FOMC minutes", r"fomc minutes$"),
)
_KEY_RES = [(label, re.compile(r"^" + pat)) for label, pat in KEY_EVENTS]


# ============================================================ small helpers
def iso(d):
    return d.isoformat()


def fnum(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def rows_of(data):
    if isinstance(data, dict):
        data = [data]
    return [r for r in (data or []) if isinstance(r, dict)]


def day(r):
    return str(r.get("date", ""))[:10]


def on_or_before(series, date, max_gap_days=10):
    """Value from a sorted [(date, value)] list at the last date <= `date`, if that date is
    within `max_gap_days` of the target (otherwise the series does not reach back that far)."""
    if not series:
        return None, None
    i = bisect.bisect_right([d for d, _ in series], date) - 1
    if i < 0:
        return None, None
    d, v = series[i]
    if (dt.date.fromisoformat(date) - dt.date.fromisoformat(d)).days > max_gap_days:
        return None, None
    return d, v


def window_starts(end):
    """Start dates for the 1M / 3M / YTD / 1Y return windows ending on `end` (a date)."""
    return (("1M", iso(end - dt.timedelta(days=30))), ("3M", iso(end - dt.timedelta(days=91))),
            ("YTD", iso(dt.date(end.year - 1, 12, 31))), ("1Y", iso(end - dt.timedelta(days=365))))


def exchange_of(profile):
    ex = str((profile or {}).get("exchange") or (profile or {}).get("exchangeShortName") or "").upper()
    return ex if ex in EXCHANGES else None


def pct(v, digits=1):
    return "n/a" if v is None else f"{v * 100:.{digits}f}%"


def bp(v):
    return "n/a" if v is None else f"{v * 10000:+.0f}bp"


def mult(v):
    return "n/a" if v is None else f"{v:.1f}x"


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


# ============================================================ fetching
def fetch_hist(client, endpoint, params):
    """try_get with an exchange-filter fallback: if the exchange-filtered request returns
    nothing, ask again without it (the endpoint's default universe)."""
    data = client.try_get(endpoint, **params)
    if not rows_of(data) and params.get("exchange"):
        data = client.try_get(endpoint, **{k: v for k, v in params.items() if k != "exchange"})
    return rows_of(data)


def fetch_prices(client, symbol, start, end):
    try:
        return client.prices(symbol, start, end)
    except FMPError as e:
        client.add_error(f"{symbol} prices: {e}")
        return []


# treasury-rates returns at most ~90 days counted back from `to`, so the curve now / 1M ago,
# 3M ago and 1Y ago come from three short windows.
TREASURY_WINDOWS = (("tsy_recent", 45, 0), ("tsy_3m_ago", 106, 84), ("tsy_year_ago", 380, 355))


def rates_requests(client, today):
    """Requests behind the Treasury curve and the US equity risk premium (4 calls)."""
    reqs = {name: (client.try_get, ("treasury-rates",),
                   {"from": iso(today - dt.timedelta(days=a)), "to": iso(today - dt.timedelta(days=b))})
            for name, a, b in TREASURY_WINDOWS}
    reqs["erp"] = (client.try_get, ("market-risk-premium",), {})
    return reqs


def treasury_rows(res):
    """All treasury-rates rows fetched by rates_requests(), merged."""
    return [r for name, _, _ in TREASURY_WINDOWS for r in rows_of(res.get(name))]


# The economic calendar lists every country (~70 events a day) and a response appears to stop at a
# few thousand rows, so the window is fetched in pieces: two months back (Fed decisions are up to
# ~8 weeks apart) and three weeks ahead.
CALENDAR_CHUNKS = ((-60, -31), (-30, 0), (1, 21))
CALENDAR_ROW_CAP = 4000


def macro_requests(client, today):
    """Requests behind the macro dashboard beyond the rates (6 calls)."""
    span = {"from": iso(today - dt.timedelta(days=400)), "to": iso(today)}
    reqs = {f"ind_{name}": (client.try_get, ("economic-indicators",), dict(span, name=name))
            for name in ("federalFunds", "CPI", "unemploymentRate")}
    for i, (a, b) in enumerate(CALENDAR_CHUNKS):
        reqs[f"calendar_{i}"] = (client.try_get, ("economic-calendar",),
                                 {"from": iso(today + dt.timedelta(days=a)), "to": iso(today + dt.timedelta(days=b))})
    return reqs


def calendar_rows(res, client=None):
    """Merge the economic-calendar pieces from macro_requests(), dropping duplicates."""
    seen, out = set(), []
    for i in range(len(CALENDAR_CHUNKS)):
        rows = rows_of(res.get(f"calendar_{i}"))
        if client is not None and len(rows) >= CALENDAR_ROW_CAP:
            client.add_error(f"economic-calendar returned {len(rows)} rows for one window; "
                             "some events may be missing")
        for r in rows:
            k = (str(r.get("date", "")), str(r.get("country", "")), str(r.get("event", "")))
            if k not in seen:
                seen.add(k)
                out.append(r)
    return out


def sector_requests(client, profile, today):
    """Requests behind the sector & industry section of a company report (5 calls)."""
    sector, industry = (profile.get("sector") or "").strip(), (profile.get("industry") or "").strip()
    ex = exchange_of(profile)
    five_y = {"from": iso(today - dt.timedelta(days=5 * 365 + 2)), "to": iso(today)}
    one_y = {"from": iso(today - dt.timedelta(days=372)), "to": iso(today)}
    exch = {"exchange": ex} if ex else {}
    reqs = {"spy": (fetch_prices, (client, "SPY", one_y["from"], one_y["to"]), {})}
    if sector:
        reqs["sector_pe"] = (fetch_hist, (client, "historical-sector-pe", dict(five_y, sector=sector, **exch)), {})
        reqs["sector_perf"] = (fetch_hist, (client, "historical-sector-performance", dict(one_y, sector=sector, **exch)), {})
    if industry:
        reqs["industry_pe"] = (fetch_hist, (client, "historical-industry-pe", dict(five_y, industry=industry, **exch)), {})
        reqs["industry_perf"] = (fetch_hist, (client, "historical-industry-performance", dict(one_y, industry=industry, **exch)), {})
    return reqs


def board_requests(client, today, sectors):
    """Requests behind the all-sectors board (2 per sector)."""
    five_y = {"from": iso(today - dt.timedelta(days=5 * 365 + 2)), "to": iso(today)}
    one_y = {"from": iso(today - dt.timedelta(days=372)), "to": iso(today)}
    reqs = {"spy": (fetch_prices, (client, "SPY", one_y["from"], one_y["to"]), {})}
    for s in sectors:
        reqs[f"pe::{s}"] = (fetch_hist, (client, "historical-sector-pe", dict(five_y, sector=s)), {})
        reqs[f"perf::{s}"] = (fetch_hist, (client, "historical-sector-performance", dict(one_y, sector=s)), {})
    return reqs


def run_requests(reqs, workers):
    """Run {name: (fn, args, kwargs)} concurrently and return {name: result}."""
    if not reqs:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {k: pool.submit(fn, *a, **kw) for k, (fn, a, kw) in reqs.items()}
        return {k: f.result() for k, f in futures.items()}


def max_workers():
    try:
        return max(1, int(os.environ.get("FMP_MAX_WORKERS") or 6))
    except ValueError:
        return 6


# ============================================================ rates
def treasury_view(rows):
    """Current Treasury curve, the curve ~1M / 3M / 1Y earlier, and the 10Y-2Y / 10Y-3M spreads,
    from treasury-rates rows. All yields are fractions (0.0519 = 5.19%)."""
    rows = sorted({day(r): r for r in rows_of(rows) if day(r) and fnum(r.get("year10")) is not None}.items())
    if not rows:
        return None
    latest_day, latest = rows[-1]
    end = dt.date.fromisoformat(latest_day)

    def curve(r):
        c = {label: (fnum(r.get(key)) / 100 if fnum(r.get(key)) is not None else None) for key, label in TENORS}
        c["10Y-2Y"] = c["10Y"] - c["2Y"] if None not in (c["10Y"], c["2Y"]) else None
        c["10Y-3M"] = c["10Y"] - c["3M"] if None not in (c["10Y"], c["3M"]) else None
        return c

    series = [(d, r) for d, r in rows]
    points = {"now": dict(curve(latest), date=latest_day)}
    for label, days in (("1M ago", 30), ("3M ago", 91), ("1Y ago", 365)):
        d, r = on_or_before(series, iso(end - dt.timedelta(days=days)), max_gap_days=10)
        points[label] = dict(curve(r), date=d) if r else None
    return {"date": latest_day, "points": points}


def us_erp(data):
    for r in rows_of(data):
        if str(r.get("country", "")).strip().lower() in ("united states", "usa", "us"):
            total = fnum(r.get("totalEquityRiskPremium"))
            return total / 100 if total is not None else None
    return None


def capm_rate(rates, erp, beta):
    """Discount rate = 10Y Treasury + beta x US equity risk premium, kept within 7-13%."""
    rf = ((rates or {}).get("points", {}).get("now") or {}).get("10Y")
    if rf is None or erp is None:
        return None
    b, b_src = (beta, "profile") if beta is not None and beta > 0 else (1.0, "default (no beta)")
    raw = rf + b * erp
    rate = min(CAPM_CAP, max(CAPM_FLOOR, raw))
    return {"rate": rate, "raw": raw, "clamped": abs(rate - raw) > 1e-12, "rf": rf,
            "rf_date": rates["date"], "beta": b, "beta_source": b_src, "erp": erp}


def capm_note(c):
    note = (f"CAPM: 10Y Treasury {pct(c['rf'], 2)} ({c['rf_date']}) + beta {c['beta']:.2f} "
            f"x US equity risk premium {pct(c['erp'], 2)}")
    if c["beta_source"] != "profile":
        note += " [beta defaulted to 1.0]"
    if c["clamped"]:
        note += f" = {pct(c['raw'], 2)}, kept within {pct(CAPM_FLOOR, 0)}-{pct(CAPM_CAP, 0)}"
    return note


# ============================================================ macro indicators & calendar
def indicator_view(data):
    rows = sorted((day(r), fnum(r.get("value"))) for r in rows_of(data) if day(r) and fnum(r.get("value")) is not None)
    if not rows:
        return None
    out = {"date": rows[-1][0], "value": rows[-1][1]}
    if len(rows) > 1:
        out["prev_date"], out["prev_value"] = rows[-2]
    return out


def _event_key(name):
    base = re.sub(r"\s*\([^)]*\)\s*$", "", str(name or "")).lower().replace("-", " ")
    return re.sub(r"\s+", " ", base).strip()


def classify_event(name):
    key = _event_key(name)
    # "core ..." patterns are listed after the headline ones; prefer the most specific match
    hits = [label for label, rx in _KEY_RES if rx.match(key)]
    core = [h for h in hits if h.lower().startswith("core")]
    if key.startswith("core"):
        return core[0] if core else None
    hits = [h for h in hits if not h.lower().startswith("core")]
    return hits[0] if hits else None


def calendar_view(data, now):
    """Latest release and next scheduled date of each key US event, plus all US events."""
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    us = [r for r in rows_of(data) if str(r.get("country", "")).upper() in ("US", "USA", "UNITED STATES")]
    us.sort(key=lambda r: str(r.get("date", "")))
    latest, upcoming = {}, {}
    for r in us:
        label = classify_event(r.get("event"))
        if not label:
            continue
        when = str(r.get("date", ""))
        if when <= now_s or fnum(r.get("actual")) is not None:
            latest[label] = r          # sorted ascending, so the last one wins
        elif label not in upcoming:
            upcoming[label] = r
    order = [label for label, _ in KEY_EVENTS]
    pick = lambda r: {"event": r.get("event"), "date": str(r.get("date", ""))[:16],
                      "actual": fnum(r.get("actual")), "estimate": fnum(r.get("estimate")),
                      "previous": fnum(r.get("previous")), "unit": r.get("unit"), "impact": r.get("impact")}
    return {
        "rows": len(us),
        "latest": [dict(pick(latest[k]), label=k) for k in order if k in latest],
        "upcoming": sorted((dict(pick(upcoming[k]), label=k) for k in order if k in upcoming),
                           key=lambda e: e["date"]),
        "all_us": [pick(r) for r in us if str(r.get("impact", "")).lower() in ("high", "medium")],
    }


# ============================================================ sector & industry
def pe_stats(rows):
    series = sorted((day(r), fnum(r.get("pe"))) for r in rows if day(r) and (fnum(r.get("pe")) or 0) > 0)
    if not series:
        return None
    vals = [v for _, v in series]
    cur_d, cur = series[-1]
    d1, v1 = on_or_before(series, iso(dt.date.fromisoformat(cur_d) - dt.timedelta(days=365)))
    return {
        "date": cur_d, "current": cur, "median": statistics.median(vals), "min": min(vals), "max": max(vals),
        "percentile": sum(1 for v in vals if v <= cur) / len(vals), "since": series[0][0], "n": len(vals),
        "year_ago": v1, "exchange": (rows[0].get("exchange") if rows else None),
    }


def perf_index(rows):
    """Cumulative index from FMP's average daily % change: [(date, index level)]."""
    level, out = 1.0, []
    for d, c in sorted((day(r), fnum(r.get("averageChange"))) for r in rows if day(r)):
        if c is None:
            continue
        level *= 1 + c / 100
        out.append((d, level))
    return out


def window_returns(series, end_day=None):
    """1M / 3M / YTD / 1Y returns from a sorted [(date, level)] series (prices or an index)."""
    if not series:
        return {}
    end_d, end_v = series[-1] if end_day is None else on_or_before(series, end_day, 7)
    if end_v is None:
        return {}
    out = {}
    for label, start in window_starts(dt.date.fromisoformat(end_d)):
        _, v0 = on_or_before(series, start, max_gap_days=7)
        out[label] = (end_v / v0 - 1) if v0 else None
    return out


def sector_context(res, profile, company_pe, company_prices, company_hist_pe=None):
    """Assemble the sector & industry section from the results of sector_requests()."""
    sector, industry = profile.get("sector"), profile.get("industry")
    s_pe = pe_stats(res.get("sector_pe") or [])
    i_pe = pe_stats(res.get("industry_pe") or [])
    spy = res.get("spy") or []
    end_day = spy[-1][0] if spy else None
    returns = {
        "company": window_returns(company_prices or [], end_day),
        "industry": window_returns(perf_index(res.get("industry_perf") or []), end_day),
        "sector": window_returns(perf_index(res.get("sector_perf") or []), end_day),
        "spy": window_returns(spy, end_day),
    }
    rel = lambda a, b: (a / b - 1) if a is not None and b else None
    exchanges = {x.get("exchange") for k in ("sector_pe", "industry_pe") for x in (res.get(k) or [])[:1]}
    exchanges.discard(None)
    return {
        "sector": sector, "industry": industry, "exchange": ", ".join(sorted(exchanges)) or None,
        "sector_pe": s_pe, "industry_pe": i_pe, "company_pe": company_pe,
        "company_hist_pe": company_hist_pe,
        "vs_industry": rel(company_pe, (i_pe or {}).get("current")),
        "vs_sector": rel(company_pe, (s_pe or {}).get("current")),
        "returns": returns, "returns_end": end_day,
    }


def sector_board(res, sectors):
    rows = []
    spy = res.get("spy") or []
    end_day = spy[-1][0] if spy else None
    for s in sectors:
        st = pe_stats(res.get(f"pe::{s}") or [])
        rows.append({"sector": s, "pe": st, "returns": window_returns(perf_index(res.get(f"perf::{s}") or []), end_day)})
    return {"rows": rows, "spy": window_returns(spy, end_day), "end": end_day}


# ============================================================ rendering
def render_rates(rates, erp, capm=None):
    out = []
    if rates:
        cols = ["now", "1M ago", "3M ago", "1Y ago"]
        heads = ["Yield"] + [f"{c} ({rates['points'][c]['date']})" if rates["points"].get(c) else c for c in cols]
        rows = []
        for _, label in TENORS + ((None, "10Y-2Y"), (None, "10Y-3M")):
            spread = "-" in label
            row = [label + (" spread" if spread else "")]
            for c in cols:
                p = rates["points"].get(c)
                v = p.get(label) if p else None
                row.append("n/a" if v is None else (bp(v) if spread else pct(v, 2)))
            rows.append(row)
        out.append(table(heads, rows))
        now = rates["points"]["now"]
        if now.get("10Y-2Y") is not None and now["10Y-2Y"] < 0:
            out.append("\nThe curve is inverted (10Y below 2Y).")
    else:
        out.append("Treasury rates not available.")
    if erp is not None:
        out.append(f"\nUS equity risk premium (FMP market-risk-premium): {pct(erp, 2)}.")
    if capm:
        out.append(f"Discount rate used for the DCF: {pct(capm['rate'], 2)} - {capm_note(capm)}.")
    return "\n".join(out)


def _num(v, unit):
    if v is None:
        return "n/a"
    u = unit or ""
    return f"{v:g}{u}" if u in ("%",) else (f"{v:g} {u}".strip())


def render_macro(m):
    out = ["### Treasury yields", render_rates(m.get("rates"), m.get("erp"))]
    out.append("\n### Policy rate, jobs and prices (economic-indicators, latest two readings)")
    rows = []
    for key, label, kind in (("federalFunds", "Fed funds rate (effective, monthly)", "rate"),
                             ("unemploymentRate", "Unemployment rate", "rate"),
                             ("CPI", "CPI index (1982-84=100)", "index")):
        ind = m.get("indicators", {}).get(key)
        if not ind:
            rows.append([label, "n/a", "", "", ""])
            continue
        cur, prev = ind["value"], ind.get("prev_value")
        if kind == "index":
            chg = f"{(cur / prev - 1) * 100:+.2f}% MoM" if prev else ""
            rows.append([label, f"{cur:,.2f}", ind["date"], f"{prev:,.2f} ({ind.get('prev_date')})" if prev else "", chg])
        else:
            chg = f"{cur - prev:+.2f}pt" if prev is not None else ""
            rows.append([label, f"{cur:.2f}%", ind["date"], f"{prev:.2f}% ({ind.get('prev_date')})" if prev is not None else "", chg])
    out.append(table(["Indicator", "Latest", "Period", "Previous", "Change"], rows))

    cal = m.get("calendar") or {}
    out.append("\n### Latest key US releases (economic calendar, last 60 days)")
    if not cal.get("rows"):
        out.append("Economic calendar not available (no US events returned).")
        return "\n".join(out)
    if cal.get("latest"):
        out.append(table(["Release", "Event", "Released (UTC)", "Actual", "Consensus", "Previous"],
                         [[e["label"], e["event"], e["date"], _num(e["actual"], e["unit"]),
                           _num(e["estimate"], e["unit"]), _num(e["previous"], e["unit"])] for e in cal["latest"]]))
    else:
        out.append("No key releases found in the last 60 days of the calendar.")
    out.append("\n### Next key US events (next 3 weeks)")
    if cal.get("upcoming"):
        out.append(table(["Event", "When (UTC)", "Consensus", "Previous"],
                         [[e["event"], e["date"], _num(e["estimate"], e["unit"]), _num(e["previous"], e["unit"])]
                          for e in cal["upcoming"]]))
    else:
        out.append("None of the tracked events is scheduled in the next 3 weeks.")
    return "\n".join(out)


def render_sector_context(sc, company_label):
    out = []
    ex = f" ({sc['exchange']}-listed companies)" if sc.get("exchange") else ""
    rows = []
    hist = sc.get("company_hist_pe") or {}
    rows.append([f"{company_label} (company)", mult(sc.get("company_pe")),
                 mult(hist.get("median")), f"{mult(hist.get('min'))} - {mult(hist.get('max'))}" if hist.get("n") else "n/a",
                 "", ""])
    for key, name in (("industry_pe", f"Industry: {sc.get('industry') or 'n/a'}"),
                      ("sector_pe", f"Sector: {sc.get('sector') or 'n/a'}")):
        st = sc.get(key)
        if not st:
            rows.append([name, "n/a", "n/a", "n/a", "n/a", "n/a"])
            continue
        rows.append([name, mult(st["current"]), mult(st["median"]), f"{mult(st['min'])} - {mult(st['max'])}",
                     pct(st["percentile"], 0), mult(st["year_ago"])])
    out.append(table(["P/E", "Now", "Hist. median", "Hist. range", "Percentile in hist.", "1y ago"], rows))
    spans = [f"{name} daily since {st['since']}" for key, name in (("industry_pe", "industry"), ("sector_pe", "sector"))
             for st in [sc.get(key)] if st]
    if hist.get("n"):
        spans.insert(0, f"company at its last {hist['n']} fiscal year-ends")
    out.append(f"\nCompany P/E vs industry: {pct(sc.get('vs_industry'))}; vs sector: {pct(sc.get('vs_sector'))}. "
               f"Industry/sector P/E is FMP's aggregate for the group{ex}, not a market-cap-weighted index. "
               f"History: {'; '.join(spans) or 'n/a'}.")
    r = sc.get("returns") or {}
    labels = ("1M", "3M", "YTD", "1Y")
    rrows = [[name] + [pct((r.get(key) or {}).get(w)) for w in labels]
             for key, name in (("company", company_label), ("industry", f"Industry (equal-weight)"),
                               ("sector", "Sector (equal-weight)"), ("spy", "S&P 500 (SPY)"))]
    out.append(f"\nPrice performance to {sc.get('returns_end') or 'n/a'}:")
    out.append(table(["Return"] + list(labels), rrows))
    return "\n".join(out)


def render_board(b):
    labels = ("1M", "3M", "YTD", "1Y")
    rows = []
    for row in sorted(b["rows"], key=lambda x: -((x["returns"] or {}).get("3M") or -9)):
        st = row["pe"] or {}
        rows.append([row["sector"], mult(st.get("current")), mult(st.get("median")),
                     pct(st.get("percentile"), 0) if st else "n/a"] +
                    [pct((row["returns"] or {}).get(w)) for w in labels])
    rows.append(["S&P 500 (SPY)", "", "", ""] + [pct(b["spy"].get(w)) for w in labels])
    since = sorted(row["pe"]["since"] for row in b["rows"] if row["pe"])
    note = f"\n\nP/E median and percentile use daily readings since {since[0]} (up to 5 years)." if since else ""
    return table(["Sector", "P/E now", "Median P/E", "P/E percentile"] + [f"{w} return" for w in labels], rows) + note


# ============================================================ CLI
def build_dashboard(client, today, now, sectors=False):
    reqs = dict(rates_requests(client, today), **macro_requests(client, today))
    names = list(DEFAULT_SECTORS)
    if sectors:
        snap = rows_of(client.try_get("sector-performance-snapshot",
                                      date=iso(today - dt.timedelta(days=1))))
        names = sorted({str(r.get("sector")) for r in snap if r.get("sector")}) or names
        reqs.update(board_requests(client, today, names))
    res = run_requests(reqs, max_workers())
    rates = treasury_view(treasury_rows(res))
    m = {
        "as_of": iso(today), "rates": rates, "erp": us_erp(res.get("erp")),
        "indicators": {k: indicator_view(res.get(f"ind_{k}")) for k in ("federalFunds", "CPI", "unemploymentRate")},
        "calendar": calendar_view(calendar_rows(res, client), now),
    }
    if sectors:
        m["sector_board"] = sector_board(res, names)
    return m


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Rates & macro dashboard from FMP")
    ap.add_argument("--sectors", action="store_true", help="add the all-sectors P/E and returns board")
    ap.add_argument("--events", action="store_true", help="list every US high/medium-impact event in the window")
    ap.add_argument("--json", default=None)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        client = FMPClient(refresh=args.refresh)
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        m = build_dashboard(client, now.date(), now, sectors=args.sectors)
    except InvalidKey as e:
        print(f"API key problem: {e}", file=sys.stderr)
        return 2
    except FMPError as e:
        print(f"FMP error: {e}", file=sys.stderr)
        return 1
    print(f"# Rates & macro backdrop (as of {m['as_of']} UTC)\n")
    print(render_macro(m))
    if args.sectors:
        b = m["sector_board"]
        print(f"\n### Sectors (FMP aggregates, returns to {b['end'] or 'n/a'}; sorted by 3M return)")
        print(render_board(b))
        print("\nSector P/E and returns are FMP aggregates of one exchange's listed companies; "
              "returns are equal-weighted averages of daily changes.")
    if args.events:
        print("\n### All US high/medium-impact events in the window")
        evs = m["calendar"]["all_us"]
        print(table(["When (UTC)", "Event", "Impact", "Actual", "Consensus", "Previous"],
                    [[e["date"], e["event"], e["impact"], _num(e["actual"], e["unit"]),
                      _num(e["estimate"], e["unit"]), _num(e["previous"], e["unit"])] for e in evs])
              if evs else "None.")
    conn = client.describe()
    print("\n### Data notes")
    print(f"- Data route: {conn['route']}." + ("" if conn["route"].startswith("official") else
          " Not served by FMP directly; spot-check important figures."))
    print(f"- API calls: {client.stats['network_calls']} network, {client.stats['cache_hits']} from cache.")
    if client.restricted:
        print(f"- Skipped (not in your FMP plan): {', '.join(client.restricted)}")
    for e in dict.fromkeys(client.errors):
        print(f"- Error: {e}")
    if args.json:
        out = dict(m)
        if not args.events:
            out["calendar"] = {k: v for k, v in m["calendar"].items() if k != "all_us"}
        Path(args.json).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        print(f"\n(JSON written to {args.json})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
