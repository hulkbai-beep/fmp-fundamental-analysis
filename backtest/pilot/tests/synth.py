"""Synthetic FMP snapshots for the pilot's tests: the same files and fields fetch.py writes."""
from __future__ import annotations

import datetime as dt
import json
import math
import random
from pathlib import Path


def weekdays(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def filed_on(pe_end: dt.date, per: str) -> dt.date:
    return pe_end + dt.timedelta(days=60 if per in ("Q4", "FY") else 35)


def company(snap: Path, sym: str, seed: int = 1, start=dt.date(2003, 1, 2), end=dt.date(2026, 10, 23),
            split: tuple | None = (dt.date(2014, 6, 9), 2.0), split_restated: bool = False, eps0: float = 1.0,
            growth: float = 0.07, pe_mid: float = 18.0, pe_amp: float = 0.25, vol: float = 0.25,
            loss_years: tuple = (), placeholder_every: int = 0, restated_from: dt.date | None = None,
            eps_not_restated: tuple = (), drop_quarters: tuple = ()):
    """One company: daily bars whose log P/E swings around pe_mid, quarterly and annual income statements
    filed 35 / 60 days after the period end, quarterly dividends and (optionally) a split. Statements are as
    GAAP issues them: a row filed before the split is on the old share basis unless FMP restated it
    (split_restated: every row; restated_from: only rows filed on or after that day, a partial restatement).
    eps_not_restated: period ends whose share count FMP restated but whose EPS it did not. drop_quarters:
    period ends missing from the quarterly statements."""
    rnd = random.Random(seed)
    days = list(weekdays(start, end))
    # quarterly EPS on today's split basis
    quarters = []
    y, q = start.year - 1, 1
    while True:
        m = 3 * q
        pe_end = dt.date(y, m, 31 if m in (3, 12) else 30)
        if pe_end > end:
            break
        t = (pe_end - start).days / 365.25
        e = eps0 / 4 * math.exp(growth * t) * (1 + 0.05 * rnd.gauss(0, 1))
        if y in loss_years:
            e = -abs(e)
        quarters.append((pe_end, f"Q{q}", y, e))
        q += 1
        if q == 5:
            y, q = y + 1, 1

    def ttm_true(d):
        known = [x for x in quarters if x[0] + dt.timedelta(days=40) < d]
        return sum(x[3] for x in known[-4:]) if len(known) >= 4 else None

    bars, adj, logpe = [], [], 0.0
    acc = 1.0
    for i, d in enumerate(days):
        logpe = 0.995 * logpe + vol / math.sqrt(252) * rnd.gauss(0, 1)
        e = ttm_true(d) or eps0
        c = max(0.5, abs(e)) * pe_mid * math.exp(pe_amp * logpe)
        o = c * (1 + 0.003 * rnd.gauss(0, 1))
        h, lo = max(o, c) * (1 + 0.005 * abs(rnd.gauss(0, 1))), min(o, c) * (1 - 0.005 * abs(rnd.gauss(0, 1)))
        bars.append({"symbol": sym, "date": d.isoformat(), "open": round(o, 4), "high": round(h, 4),
                     "low": round(lo, 4), "close": round(c, 4), "volume": 1_000_000 + i})
        adj.append({"symbol": sym, "date": d.isoformat(), "adjOpen": o * acc, "adjHigh": h * acc,
                    "adjLow": lo * acc, "adjClose": c * acc, "volume": 1_000_000 + i})
    bars.reverse()
    adj.reverse()                                   # FMP answers newest first
    shares_now = 100e6

    def basis(filed: dt.date) -> float:
        if not split or split_restated or filed >= split[0]:
            return 1.0
        if restated_from and filed >= restated_from:
            return 1.0
        return split[1]                             # filed before the split and not restated: the old basis

    inc_q, inc_a = [], []
    for k, (pe_end, per, fy, e) in enumerate(quarters):
        if pe_end in drop_quarters:
            continue
        filed = filed_on(pe_end, per)
        f = basis(filed)
        fe = split[1] if pe_end in eps_not_restated else f    # the share count restated, the EPS not
        row = {"date": pe_end.isoformat(), "symbol": sym, "period": per, "fiscalYear": str(fy),
               "filingDate": filed.isoformat(), "acceptedDate": filed.isoformat() + " 16:05:00",
               "epsDiluted": round(e * fe, 6), "weightedAverageShsOutDil": shares_now / f,
               "netIncome": e * shares_now}
        if placeholder_every and k % placeholder_every == 0:
            row["filingDate"] = pe_end.isoformat()  # FMP placeholder: not after the period end
            row["acceptedDate"] = pe_end.isoformat() + " 00:00:00"
        inc_q.append(row)
    for fy in sorted({x[2] for x in quarters}):
        qs = [x for x in quarters if x[2] == fy]
        if len(qs) < 4:
            continue
        pe_end = dt.date(fy, 12, 31)
        filed = filed_on(pe_end, "FY")
        f = basis(filed)
        e = sum(x[3] for x in qs)
        inc_a.append({"date": pe_end.isoformat(), "symbol": sym, "period": "FY", "fiscalYear": str(fy),
                      "filingDate": filed.isoformat(), "epsDiluted": round(e * f, 6),
                      "weightedAverageShsOutDil": shares_now / f, "netIncome": e * shares_now})
    divs = []
    for d in days[::63]:
        divs.append({"date": d.isoformat(), "adjDividend": 0.2, "dividend": 0.2})
    splits = [{"date": split[0].isoformat(), "numerator": split[1], "denominator": 1}] if split else []
    files = {"full": bars, "adj": adj, "inc_q": list(reversed(inc_q)), "inc_a": list(reversed(inc_a)),
             "div": divs, "splits": splits, "profile": [{"symbol": sym, "sector": "Industrials"}],
             "earn": [], "est": []}
    for part, rows in files.items():
        p = snap / "raw" / part / f"{sym}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows), encoding="utf-8")
    return {"days": days, "quarters": quarters}
