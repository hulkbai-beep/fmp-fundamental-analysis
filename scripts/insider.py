#!/usr/bin/env python3
"""
Insider trades from FMP: open-market purchases and sales by a company's officers, directors and 10%
owners (SEC Form 4) over the last 12 months.

analyze.py adds them to each report for observation only; the fundamental score does not use them.
Only open-market purchases (transaction code P) and sales (code S) count. Awards, option exercises,
shares withheld for tax, gifts and the other codes are not trades at the market price and are left out.
Purchases with an insider's own money, especially by several insiders within a few months, have
historically come before better returns; sales are mostly diversification, taxes or pre-planned
(10b5-1) sales and say little on their own.
"""
from __future__ import annotations

import datetime as dt
import html
import math
import re

ENDPOINT = "insider-trading/search"
PAGE = 100
MAX_PAGES = 5         # up to 500 filings: large companies file many awards and planned sales a year
LOOKBACK_DAYS = 365
CLUSTER_DAYS = 90     # "several insiders buying together": CLUSTER_MIN or more people within 90 days
CLUSTER_MIN = 3
BIG_BUY = 100_000     # a CEO or CFO purchase of at least this much is flagged on its own
TOP = 10              # rows in the insider and purchase tables


def fnum(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def money(v):
    if v is None:
        return "n/a"
    a, s = abs(v), "-" if v < 0 else ""
    for d, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= d:
            return f"{s}{a / d:.2f}{suf}"
    return f"{s}{a:.0f}"


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def _day(r, key):
    return str(r.get(key) or "")[:10]


def _sec_url(u):
    return isinstance(u, str) and u.startswith("https://www.sec.gov/") and not any(c in u for c in " ()[]|")


# ============================================================ fetching
def fetch(client, symbol, today):
    """Form 4 rows filed in the lookback window and a little before (newest first, as FMP returns them),
    or None when the endpoint is not in the plan. Pages until a page reaches back past the window.
    Returns (rows, complete): complete is False when the pages ran out before the window start."""
    start = (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    rows = []
    for page in range(MAX_PAGES):
        data = client.try_get(ENDPOINT, symbol=symbol, page=page, limit=PAGE)
        if data is None:
            if page == 0:
                return None, False
            client.unrestrict(ENDPOINT)  # a later page refused (page cap): keep what came back
            return rows, False
        data = [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
        rows += data
        if len(data) < PAGE or min(_day(r, "filingDate") for r in data) < start:
            return rows, True
    return rows, False


# ============================================================ summary
def role(owner):
    """FMP's typeOfOwner ("director, officer: President &amp; Chief Exec Officer", "10 percent owner") as a
    short label: Director, CEO, CFO, Officer, 10% owner, joined with commas. A business unit's CEO
    ("CEO Amazon Web Services") is an Officer, not the company's CEO."""
    s = html.unescape(str(owner or "")).lower()
    parts = []
    if "director" in s:
        parts.append("Director")
    if re.search(r"chief exec|\bceo\b", s) and not re.search(r"\bceo\s+(?!and\b|&)\w", s):
        parts.append("CEO")
    elif re.search(r"chief financial|\bcfo\b", s):
        parts.append("CFO")
    elif "officer" in s:
        parts.append("Officer")
    if "10 percent" in s or "10%" in s:
        parts.append("10% owner")
    return ", ".join(parts) or "Other"


def summarize(rows, today, market_cap=None, complete=True):
    """rows: insider-trading/search rows (None when not in the plan). Open-market purchases and sales
    over the last LOOKBACK_DAYS by transaction date, per side, per insider, and the largest cluster of
    purchases."""
    if rows is None:
        return {"restricted": True}
    end, start = today.isoformat(), (today - dt.timedelta(days=LOOKBACK_DAYS)).isoformat()
    if not complete and rows:  # the pages stopped before the window start: totals cover what came back
        start = max(start, min(_day(r, "transactionDate") or end for r in rows))
    seen, trades, other = set(), [], 0
    for r in rows:
        d = _day(r, "transactionDate")
        if not start <= d <= end:
            continue
        # an amended Form 4 (4/A) repeats the original rows
        key = (r.get("reportingCik") or r.get("reportingName"), d, r.get("transactionType"),
               r.get("securitiesTransacted"), r.get("price"), r.get("directOrIndirect"))
        if key in seen or str(r.get("formType") or "").startswith("3"):  # Form 3: holdings on joining
            continue
        seen.add(key)
        code = str(r.get("transactionType") or "").strip().upper()[:1]
        shares, price = fnum(r.get("securitiesTransacted")), fnum(r.get("price"))
        if code not in ("P", "S") or not shares or shares <= 0 or not price or price <= 0:
            other += 1
            continue
        trades.append({"date": d, "name": html.unescape(str(r.get("reportingName") or "n/a")).strip(),
                       "role": role(r.get("typeOfOwner")), "kind": "buy" if code == "P" else "sell",
                       "shares": shares, "price": price, "value": shares * price, "url": r.get("url")})

    def side(kind):
        ts = [t for t in trades if t["kind"] == kind]
        return {"trades": len(ts), "insiders": len({t["name"] for t in ts}),
                "shares": sum(t["shares"] for t in ts), "value": sum(t["value"] for t in ts)}

    people = {}
    for t in sorted(trades, key=lambda t: t["date"]):
        p = people.setdefault(t["name"], {"name": t["name"], "role": t["role"], "bought": 0.0, "sold": 0.0})
        p["bought" if t["kind"] == "buy" else "sold"] += t["value"]
        p["role"], p["last"] = t["role"], t["date"]

    buys = sorted((t for t in trades if t["kind"] == "buy"), key=lambda t: t["date"])
    cluster = None
    for i, t in enumerate(buys):
        stop = (dt.date.fromisoformat(t["date"]) + dt.timedelta(days=CLUSTER_DAYS)).isoformat()
        w = [b for b in buys[i:] if b["date"] <= stop]
        names = {b["name"] for b in w}
        c = {"from": t["date"], "to": w[-1]["date"], "insiders": len(names), "value": sum(b["value"] for b in w)}
        if len(names) >= CLUSTER_MIN and (cluster is None or (c["insiders"], c["value"]) > (cluster["insiders"], cluster["value"])):
            cluster = c
    officer = [t for t in buys if re.search(r"\b(CEO|CFO)\b", t["role"]) and t["value"] >= BIG_BUY]
    sells = side("sell")
    return {
        "from": start, "to": end, "complete": complete, "other": other,
        "buys": side("buy"), "sells": sells,
        "sells_vs_mcap": sells["value"] / market_cap if market_cap and sells["value"] else None,
        "insiders": sorted(people.values(), key=lambda p: -(p["bought"] + p["sold"]))[:TOP],
        "purchases": list(reversed(buys))[:TOP], "cluster": cluster,
        "officer_buy": max(officer, key=lambda t: t["value"]) if officer else None,
    }


def flags(s):
    """Positives for the automated flags: a cluster of purchases, else a large CEO or CFO purchase.
    Sales raise no flag: most are diversification, taxes or pre-planned."""
    if not s or s.get("restricted"):
        return []
    if s["cluster"]:
        c = s["cluster"]
        return [f"Insider cluster buying: {c['insiders']} insiders bought {money(c['value'])} on the open market "
                f"between {c['from']} and {c['to']}"]
    if s["officer_buy"]:
        t = s["officer_buy"]
        return [f"Insider buying: {t['name']} ({t['role']}) bought {money(t['value'])} on the open market on {t['date']}"]
    return []


# ============================================================ report
def render(s):
    if s.get("restricted"):
        return "Insider trades are not in your FMP plan (insider-trading/search)."
    out = [f"Form 4 filings, trades from {s['from']} to {s['to']}. Only open-market purchases (code P) and "
           f"sales (code S) count; {s['other']} other transactions (awards, option exercises, shares withheld "
           f"for tax, gifts) are left out."]
    if not s["complete"]:
        out.append(f"FMP returned only the latest {MAX_PAGES * PAGE} filings, so the totals start at {s['from']}.")
    b, x = s["buys"], s["sells"]
    if not b["trades"] and not x["trades"]:
        out.append("No open-market purchases or sales in this period.")
    else:
        out.append(table(["Side", "Trades", "Insiders", "Shares", "Amount"],
                         [[name, v["trades"], v["insiders"], f"{v['shares']:,.0f}", money(v["value"])]
                          for name, v in (("Purchases", b), ("Sales", x))]))
        if s["sells_vs_mcap"] is not None:
            v = s["sells_vs_mcap"] * 100
            out.append(f"Sales were {'<0.01' if v < 0.01 else f'{v:.2f}'}% of the market cap.")
        out.append("\n**By insider**")
        out.append(table(["Insider", "Role", "Bought", "Sold", "Last trade"],
                         [[p["name"], p["role"], money(p["bought"]) if p["bought"] else "-",
                           money(p["sold"]) if p["sold"] else "-", p["last"]] for p in s["insiders"]]))
    if s["purchases"]:
        out.append("\n**Open-market purchases (latest first)**")
        out.append(table(["Date", "Insider", "Role", "Shares", "Price", "Amount", "Filing"],
                         [[t["date"], t["name"], t["role"], f"{t['shares']:,.0f}", f"{t['price']:,.2f}",
                           money(t["value"]), f"[Form 4]({t['url']})" if _sec_url(t["url"]) else "-"]
                          for t in s["purchases"]]))
    out.append(f"\nObservation only, not used in the score. Purchases with the insider's own money, especially "
               f"by {CLUSTER_MIN} or more insiders within {CLUSTER_DAYS} days, have historically come before better "
               f"returns, mostly at small and mid-size companies. Sales are mostly diversification, taxes or "
               f"pre-planned (10b5-1) sales and say little on their own.")
    return "\n".join(out)
