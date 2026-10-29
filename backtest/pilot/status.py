"""
The pilot's usability rule and replacement walk, set before any data was fetched. fetch.py runs it on the PC,
where a replacement is fetched when the walk reaches it; run_pilot.py runs it again in the cloud on the
snapshot and must come to the same decisions.

Over a company's member sessions (SPY's sessions from 2008-01-02 to the snapshot's last day Z that fall in its
S&P 500 spans):
  U1 bars        its split-adjusted daily bars cover at least 90% of them;
  U2 statements  version T's TTM EPS (any sign) is defined on at least 75% of them;
  U3 identity    its quarterly statements carry a single CIK; more than one is kept and listed for review;
  U4 duplicate   it is not one series with, or a twin of, a company already in the sample (V3's tests: the log
                 close ratio's standard deviation under 0.001 over 60 common days while the price moves, or
                 daily log returns correlated 0.97 or more over at least 250 common days).
A drawn company that fails U1 or U2 gives way to the next company of its stratum's seeded order that is neither
drawn nor already used and passes U1, U2 and U4; the spares head each order's remainder. A company whose V3
record has bars_from or cuts (a reused ticker, so its FMP history mixes companies) is skipped. A renamed
company may be read under its new ticker (ALIASES) when the old ticker fails U1 or U2 and the two tickers are one
series. Losses, no band, a short or late window, no signal and a delisting are not reasons to replace: they are
outcomes of the method on the drawn companies.
"""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import panel as P

FIRST_DAY = "2008-01-02"
MIN_BARS = 0.90
MIN_TTM = 0.75
SAME_SERIES_SD = 0.001
SAME_WINDOW = 60
MOVING_SD = 0.002
DUP_CORR = 0.97
DUP_DAYS = 250
ALIASES = {"FBHS": "FBIN"}            # Fortune Brands Home & Security, renamed Fortune Brands Innovations


def sessions(snap: Path, end: str) -> list:
    """SPY's sessions (the days of its split-adjusted bars) up to end: the calendar of the rule."""
    return sorted({str(r["date"])[:10] for r in P.read(Path(snap) / "raw" / "full" / "SPY.json")
                   if r.get("date") and str(r["date"])[:10] <= end})


def member_sessions(sessions: list, spans: list, end: str) -> list:
    return [d for d in sessions if FIRST_DAY <= d <= end and P.in_spans(d, spans)]


def closes(snap: Path, series: str) -> dict:
    out = {}
    for r in P.read(Path(snap) / "raw" / "full" / f"{series}.json"):
        c = P.fnum(r.get("close"))
        if r.get("date") and c and c > 0:
            out[str(r["date"])[:10]] = c
    return out


def assess(snap: Path, series: str, spans: list, sessions: list, end: str) -> dict:
    """U1-U3 of one series: shares of member sessions with a bar and with a TTM EPS, and the CIKs."""
    raw = Path(snap) / "raw"
    mem = member_sessions(sessions, spans, end)
    cl = closes(snap, series)
    q = P.read(raw / "inc_q" / f"{series}.json")
    rows = P.statement_rows(q, P.split_factors(P.read(raw / "splits" / f"{series}.json")), {})
    t_days, t_vals = P.ttm_steps(rows)
    n = len(mem)
    bars = sum(d in cl for d in mem) / n if n else 0.0
    ttm = sum(P.ttm_at(t_days, t_vals, P.day(d))[0] is not None for d in mem) / n if n else 0.0
    lo = (P.day(mem[0]) - dt.timedelta(days=400)).isoformat() if mem else ""
    ciks = sorted({str(r.get("cik")) for r in q if r.get("cik") and mem and lo <= str(r.get("date"))[:10] <= mem[-1]})
    why = ("no member sessions" if not n else f"bars on {bars:.0%} of member sessions" if bars < MIN_BARS
           else f"TTM EPS on {ttm:.0%} of member sessions" if ttm < MIN_TTM else "")
    return {"series": series, "sessions": n, "bars": round(bars, 4), "ttm": round(ttm, 4), "ciks": ciks,
            "ok": not why, "why": why, "review": len(ciks) > 1}


def duplicate_of(a: dict, b: dict) -> str | None:
    """V3's ladder_universe.duplicate_of on two {day: close} series, without pandas: rolling standard deviations
    (ddof 1) over SAME_WINDOW common days from running sums."""
    common = sorted(set(a) & set(b))
    n = len(common)
    if n < SAME_WINDOW:
        return None
    la = [math.log(a[d]) for d in common]
    r = [math.log(b[d] / a[d]) for d in common]
    da = [0.0] + [la[i] - la[i - 1] for i in range(1, n)]          # da[0] is never inside a tested window
    sr, sr2, sd_, sd2 = _cum(r), _cum([x * x for x in r]), _cum(da), _cum([x * x for x in da])
    w = SAME_WINDOW
    for t in range(w, n):
        if _var(sr, sr2, t - w + 1, t + 1) < SAME_SERIES_SD ** 2 and _var(sd_, sd2, t - w + 1, t + 1) > MOVING_SD ** 2:
            return "same series"
    if n >= DUP_DAYS:
        db = [math.log(b[common[i]] / b[common[i - 1]]) for i in range(1, n)]
        if _corr(da[1:], db) >= DUP_CORR:
            return "twin"
    return None


def _cum(x: list) -> list:
    out, s = [0.0], 0.0
    for v in x:
        s += v
        out.append(s)
    return out


def _var(c: list, c2: list, i: int, j: int) -> float:
    m = j - i
    s, s2 = c[j] - c[i], c2[j] - c2[i]
    return max(0.0, (s2 - s * s / m) / (m - 1))


def _corr(x: list, y: list) -> float:
    mx, my = sum(x) / len(x), sum(y) / len(y)
    sxy = sum((u - mx) * (v - my) for u, v in zip(x, y))
    sxx, syy = sum((u - mx) ** 2 for u in x), sum((v - my) ** 2 for v in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0


def walk(sample: dict, snap: Path, sessions: list, end: str, fetch=None) -> dict:
    """The decisions for the drawn sample. fetch(series) gets a company's files into the snapshot before it is
    assessed (on the PC); without it every file must already be there (in the cloud). Returns
    {"companies": [[key, series, sector, spans]], "assessed": {key: ...}, "replacements": [...], "review": [...]}"""
    recs, order = sample["records"], sample["order"]
    drawn = list(sample["sample"])
    assessed, used, accepted, swaps, cache = {}, set(drawn), {}, [], {}

    def cl(series: str) -> dict:
        if series not in cache:
            cache[series] = closes(snap, series)
        return cache[series]

    def get(key: str) -> dict:
        if key not in assessed:
            rec = recs[key]
            series = rec.get("series") or key
            if fetch:
                fetch(series)
            x = assess(snap, series, rec["spans"], sessions, end)
            alias = ALIASES.get(key)
            if not x["ok"] and alias:
                if fetch:
                    fetch(alias)
                y = assess(snap, alias, rec["spans"], sessions, end)
                same = duplicate_of(cl(series), cl(alias)) == "same series"
                x["alias"] = {"series": alias, "ok": y["ok"], "why": y["why"], "same_series": same}
                if y["ok"] and same:
                    x = dict(y, alias_of=series)
            assessed[key] = x
        return assessed[key]

    def dup(key: str) -> str | None:
        c = cl(assessed[key]["series"])
        for other, s in accepted.items():
            hit = duplicate_of(cl(s), c)
            if hit:
                return f"{hit} as {other}"
        return None

    out = []
    for key in drawn:                               # of two drawn duplicates the later one gives way (V3)
        rec = recs[key]
        x = get(key)
        why = x["why"] or dup(key)
        if not why:
            accepted[key] = x["series"]
            out.append([key, x["series"], rec["sector"], rec["spans"]])
            continue
        swap = {"out": key, "why": why, "in": None, "tried": []}
        for alt in order[rec["sector"]]:
            if alt in used:
                continue
            ra = recs[alt]
            if ra.get("bars_from") or ra.get("cuts"):
                used.add(alt)
                swap["tried"].append({"key": alt, "why": "reused ticker (V3 bars_from / cuts)"})
                continue
            used.add(alt)
            y = get(alt)
            why = y["why"] or dup(alt)
            if why:
                swap["tried"].append({"key": alt, "why": why})
                continue
            accepted[alt] = y["series"]
            out.append([alt, y["series"], ra["sector"], ra["spans"]])
            swap["in"] = alt
            break
        swaps.append(swap)
    review = [k for k in accepted if assessed[k]["review"]]
    return {"companies": out, "assessed": assessed, "replacements": swaps, "review": review}
