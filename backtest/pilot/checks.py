#!/usr/bin/env python3
"""
Checks before any result is read, on the frozen snapshot (all in the cloud; SPEC v1 section 8):

  calendar   SPY's split-adjusted and dividend-adjusted sessions agree up to Z (the rule's calendar and the
             hedge's), and every company bar on or after 2008-01-02 falls on a SPY session
  band       the fast daily band equals the skill's analyze.multiple_bands and the full analyze.history_problem
             on random (company, day, version) triples
  pipeline   at the snapshot's last day, for every company still listed with analysts' estimates: the pilot's
             band code fed the skill's own next-twelve-month EPS (reported years, then today's consensus)
             reproduces analyze.price_range's forward-P/E band and 'now' range exactly
  truncation version T: deleting every bar after a cut and every statement filed on or after it (by this
             file's own reading of the filing dates) changes nothing on or before the cut; half the cuts are
             filing days, where a leak of a single day shows
  fills      the trade audit: the method's rules written out here apart from sim.py (the temperature, the
             levels, the tranche dates, the tiers, the trailing multiples) replay every plan close by close
             from its close, and its levels, buys, sales and end must be theirs (none late, early, unsignalled,
             missing or of another size), as must the closes that start plans, the placebo's pool of start
             days and every plan of its every-start table (one from each pool day, of size 1); every buy at the
             open after a fair close on or after its tranche date and by the expiry, under the chase limit,
             tranche k after k - 1, never at an open that fills a sale of the plan; every sale at the open
             after its signal close, except the delisting and spin-off sales at the close of their bar, for its
             shares at that price less the cost; shares bought = shares sold + shares held for every plan
  basis      the statement basis decisions, EPS x shares / net income outliers and annual-vs-quarters gaps of
             every company, for review by eye
  spins      the evidence to confirm each spin-off (the listed events and panel.spin_candidates): the /full
             closes around the date, the distribution the dividend-adjusted series implies, nearby split rows
  review     the data review table (review.md, check 7), written before any result is opened

checks.json records what the checks were made from (run_pilot.inputs: the snapshot's manifest, the sample, the
confirmed spin-offs, the code; and the md5 of the checks' own code, checks.py and score.py, with the sample
sizes), taken when the checks start: a run whose inputs or code change before it ends is refused and writes
neither checks.json nor review.md. report.py accepts them only for results made from the same inputs, with the
checks' code as it is now, at least 200 band triples and truncation cuts and every every-start plan replayed.
A run first removes the checks.json and review.md in --out.

    python backtest/pilot/checks.py --snap DIR --out DIR [--pairs 200]
    python backtest/pilot/checks.py --same OUT_1 OUT_2        # check 8: two runs give the same results
                                                              # (writes OUT_1/repro.json for report.py)
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import hashlib
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import market as M  # noqa: E402
import panel as P  # noqa: E402
import placebo as PL  # noqa: E402
import report as RP  # noqa: E402
import run_pilot as R  # noqa: E402
import sim as S  # noqa: E402

A = P.A
sys.path.insert(0, str(HERE.parent.parent / "scripts"))
import score as SC  # noqa: E402
SEED = 20261029
LAG = {"Q1": 45, "Q2": 45, "Q3": 45, "Q4": 90, "FY": 90}
VOID = ("lapsed", "expired", "cancelled_below_stop", "spin", "unfilled")    # plans that never bought
SPIN_LOOK = 5                       # sessions either side of a listed spin-off date searched for its drop


def filed(r: dict):
    """This check's own reading of when a statement row became public (written apart from panel.known_day):
    the filing date when it is at least 10 days after the period end, else the period end + 45 / 90 days."""
    end = dt.date.fromisoformat(str(r["date"])[:10])
    f = str(r.get("filingDate") or r.get("acceptedDate") or "")[:10]
    if f and f >= (end + dt.timedelta(days=10)).isoformat():
        return dt.date.fromisoformat(f), False
    return end + dt.timedelta(days=LAG.get(str(r.get("period") or "FY").upper(), 90)), True


def check_calendar(snap: Path, comps: list, z: str) -> dict:
    """The rule's sessions (SPY /full, status.sessions) against the hedge's (SPY dividend-adjusted, market.Spy):
    a day in one and not the other fails; and the company bars from 2008-01-02 on that are not SPY sessions."""
    rule = R.SU.sessions(snap, z)
    hedge = [d for d in M.load(snap)[1].days if d <= z]
    a, b = set(rule), set(hedge)
    off = {}
    for _, sym, sector, spans in comps:
        days = [str(r["date"])[:10] for r in P.read(snap / "raw" / "full" / f"{sym}.json") if r.get("date")]
        n = sorted(d for d in days if R.FIRST_DAY <= d <= z and d not in a)
        if n:
            off[sym] = {"bars": len(n), "first": n[:5]}
    return {"checked": len(rule), "failed": len(a ^ b), "only_full": sorted(a - b)[:10], "only_adj": sorted(b - a)[:10],
            "bars_off_sessions": off}                   # listed for review: sim gives them the previous session


def check_band(snap: Path, comps: list, n: int, rnd: random.Random, z: str) -> dict:
    bad, done = [], 0
    picked = rnd.sample(comps, min(len(comps), 25))
    per = max(1, n // len(picked))
    for _, sym, sector, spans in picked:
        p = P.build(sym, snap, spans, versions=R.VERSIONS, snapshot_end=z)
        sp = P.split_factors(P.read(snap / "raw" / "splits" / f"{sym}.json"))
        years = P.statement_rows(P.read(snap / "raw" / "inc_a" / f"{sym}.json"), sp, {}, unclear="none", units="fix",
                                 eps_shares="later")
        q_raw = P.read(snap / "raw" / "inc_q" / f"{sym}.json")
        reading = {"T": P.statement_rows(q_raw, sp, {}, unclear="mark", units="fix", eps_shares="later"),
                   "F": P.statement_rows(q_raw, sp, {}, unclear="none", units="fix", eps_shares="later")}
        days = [i for i, d in enumerate(p.dates) if d >= R.FIRST_DAY and p.member[i]]
        for i in rnd.sample(days, min(len(days), per)):
            for v in ("T", "F"):
                d = P.day(p.dates[i])
                start = (d - dt.timedelta(days=P.LOOKBACK_DAYS)).isoformat()
                window = [(p.dates[j], p.c[j]) for j in range(i + 1) if p.dates[j] >= start]
                until = next(u for u, _ in p.epochs["T"] if u is None or p.dates[i] <= u)
                ys = P.t_years(years, p.report, until) if v == "T" else years
                yrs = [{"date": y["end"].isoformat(), "shares": y["shares"]} for y in P.latest_by_end(ys, d)]
                # T: the quarters of the day's epoch (an unclear split's old ones leave at its end); F: all, with
                # every boundary decided on the full data
                qs = [q for q in reading[v] if q["known"] < d and q["shares"] and
                      (v == "F" or not q.get("unclear_until") or (until and q["unclear_until"].isoformat() >= until))]
                cur = max(qs, key=lambda q: (q["known"], q["end"]))["shares"] if qs else None
                code = A.history_problem(yrs, window, start, cur)[0]
                eps = dict(zip(p.dates, p.window_eps(v, i)))
                now = A.pos_div(p.c[i], p.eps[v][i])
                want = A.multiple_bands([], window, eps.get, lambda _d: None, now, None)[0]
                got = p.band[v][i]
                if code or not now or want is None:
                    ok = got is None
                else:
                    ok = got is not None and all(abs(got[k] - want[k]) <= 1e-9 * max(1.0, abs(want[k]))
                                                 for k in ("p25", "median", "p75")) and \
                        abs(got["pct"] - want["now_pct"]) <= 1e-12
                done += 1
                if not ok:
                    bad.append({"symbol": sym, "day": p.dates[i], "version": v, "code": code,
                                "got": got, "want": None if want is None else {k: want[k] for k in
                                                                               ("p25", "median", "p75", "now_pct")}})
    return {"checked": done, "failed": len(bad), "failures": bad[:20]}


def _closes(rows: list, field: str) -> list:
    out = sorted((str(r["date"])[:10], P.fnum(r.get(field))) for r in rows if r.get("date"))
    return [(d, c) for d, c in out if c]


def _same_reason(pilot_why: str | None, pr: dict) -> bool:
    """With no band on either side, the pilot's reason and the skill's must be the same."""
    if pilot_why in ("share_basis", "price_jump"):
        return pr.get("band_problem") == pilot_why
    if pilot_why == "short_history":
        return pr.get("band_problem") is None and pr.get("pe_band") is None
    now = next((pt for pt in pr.get("forward") or [] if pt.get("at") == "now"), None)
    return not now or not now.get("pe")                      # EPS not positive: no range shown either


def _window_band(dates: list, closes: list, eps: list, z: str):
    """The band over the window's P/E days at the last day without the condition that its EPS is positive:
    what the skill still builds (with no percentile) when it shows no range."""
    start = (P.day(z) - dt.timedelta(days=P.LOOKBACK_DAYS)).isoformat()
    lo = bisect.bisect_left(dates, start)
    vals = [closes[j] / eps[j] for j in range(lo, len(dates)) if eps[j] and eps[j] > 0]
    if len(vals) < P.MIN_BAND_DAYS:
        return None
    return A._band(vals, [(dates[lo], closes[lo]), (dates[-1], closes[-1])])


def check_pipeline(snap: Path, comps: list) -> dict:
    """At the last day: the skill's price_range against the pilot's band code on the same inputs (exact), what
    the user reads from it (score._value_range, the primary range), the reasons when neither has a band, the
    skill's own /light closes (an audit against /full and the band on them, to 0.5%), and the names whose annual
    statements the pilot's split normalisation changes inside the band's window (the skill reads them raw)."""
    raw = snap / "raw"
    rows, skipped, normalised = [], [], []
    for _, sym, sector, spans in comps:
        bars = _closes(P.read(raw / "full" / f"{sym}.json"), "close")
        est = P.read(raw / "est" / f"{sym}.json")
        prof = (P.read(raw / "profile" / f"{sym}.json") or [{}])[0]
        if not bars or not est:
            skipped.append({"symbol": sym, "why": "no estimates" if bars else "no bars"})
            continue
        z, close = bars[-1]
        zd = dt.date.fromisoformat(z)
        inc_a_all = P.read(raw / "inc_a" / f"{sym}.json")
        inc_a = sorted(inc_a_all, key=lambda r: str(r.get("date")))[-5:]
        years = A.build_years(inc_a, [], [])
        price = close
        mcap = P.fnum(prof.get("marketCap") or prof.get("mktCap"))
        cur_shares = mcap / P.fnum(prof.get("price")) if mcap and P.fnum(prof.get("price")) else None
        analyst = A.analyst_view(est, None, years[-1], price, z)
        if len([e for e in analyst.get("estimates", []) if not e["ended"]]) < 2:
            skipped.append({"symbol": sym, "why": "fewer than two estimate years"})
            continue
        pr = A.price_range(years, {}, bars, analyst, {}, price, zd, cur_shares)
        # the pilot's code on the same inputs: EPS = the skill's NTM blend of reported years and estimates
        ntm = A._ntm([(y["date"], y["eps"]) for y in years if y.get("eps") is not None] +
                     [(e["date"], e["eps_avg"]) for e in analyst["estimates"] if e.get("eps_avg") is not None])
        dates = [d for d, _ in bars]
        closes = [c for _, c in bars]
        eps = [ntm(d) for d in dates]
        yrows = [{"end": dt.date.fromisoformat(y["date"]), "known": dt.date.fromisoformat(y["date"]),
                  "shares": y.get("shares")} for y in years]
        q_shares = [(zd - dt.timedelta(days=1), None, cur_shares)] if cur_shares else []
        band, why = P.bands(dates, closes, eps, [None] * len(dates), yrows, q_shares, z)
        got, want = band[-1], pr["pe_band"]
        e_now = eps[-1]
        vr = SC._value_range({"price_range": pr, "dcf": {}, "current": {"price": price}, "analyst": analyst})
        gap = (analyst.get("eps_basis") or {}).get("gap")
        row = {"symbol": sym, "day": z, "skill_note": pr.get("band_note"), "skill_problem": pr.get("band_problem"),
               "pilot_why": why[-1], "eps_basis_gap": gap, "primary_basis": vr["basis"] if vr else None}
        if not vr:
            row["primary_note"] = ("eps basis gap over 10%: the live primary range would be the DCF"
                                   if gap is not None and abs(gap) > SC.BASIS_GAP else "no forward P/E range now")
        if got is None and why[-1] == "eps_not_positive":
            # no range on either side; the skill's band over the window must still be the pilot's P/E days
            mine = _window_band(dates, closes, eps, z)
            row["ok"] = _same_reason(why[-1], pr) and pr.get("band_problem") is None and \
                (mine is None) == (want is None) and (mine is None or all(
                    abs(mine[k] - want[k]) <= 1e-9 * abs(want[k]) for k in ("p25", "median", "p75")))
        elif want is None or got is None:
            row["ok"] = (want is None) == (got is None) and (got is not None or _same_reason(why[-1], pr))
        else:
            now = pr["forward"][0]["pe"] if pr["forward"] else None
            diffs = [abs(got[k] - want[k]) / abs(want[k]) for k in ("p25", "median", "p75")]
            diffs.append(abs(got["pct"] - want["now_pct"]))
            if now:
                diffs += [abs(e_now * got[q] - now[k]) / abs(now[k]) for k, q in
                          (("low", "p25"), ("base", "median"), ("high", "p75"))]
            if vr:
                diffs += [abs(e_now * got[q] - vr[k]) / abs(vr[k]) for k, q in
                          (("low", "p25"), ("mid", "median"), ("high", "p75"))]
            row["max_rel_diff"] = max(diffs)
            row["ok"] = max(diffs) <= 1e-9
            row["mid"] = e_now * got["median"]
        light = _closes(P.read(raw / "light" / f"{sym}.json"), "price")
        if light:
            full_on = dict(bars)
            common = [(d, c) for d, c in light if d in full_on]
            rel = [abs(c / full_on[d] - 1) for d, c in common]
            row["light"] = {"days": len(light), "common": len(common), "max_rel_diff": max(rel) if rel else None,
                            "over_1e-6": sum(x > 1e-6 for x in rel), "last": light[-1][0]}
            if got is not None and light[-1][0] == z:
                prl = A.price_range(years, {}, light, analyst, {}, light[-1][1], zd, cur_shares)
                bl = prl["pe_band"]
                row["light"]["band_rel_diff"] = None if bl is None else max(
                    abs(got[k] - bl[k]) / abs(bl[k]) for k in ("p25", "median", "p75"))
                row["light"]["ok"] = bl is not None and row["light"]["band_rel_diff"] <= 0.005
        rep = {}
        lo = (zd - dt.timedelta(days=P.LOOKBACK_DAYS + 400)).isoformat()
        for r in P.statement_rows(inc_a_all, P.split_factors(P.read(raw / "splits" / f"{sym}.json")), rep,
                                  unclear="none", units="fix", eps_shares="later"):
            if r["end"].isoformat() >= lo:
                eps0 = P.fnum(r["raw"].get("epsDiluted", r["raw"].get("epsdiluted", r["raw"].get("eps"))))
                sh0 = P.fnum(r["raw"].get("weightedAverageShsOutDil")) or P.fnum(r["raw"].get("weightedAverageShsOut"))
                if (eps0, sh0) != (r["eps"], r["shares"]):
                    normalised.append({"symbol": sym, "end": r["end"].isoformat(), "eps": [eps0, r["eps"]],
                                       "shares": [sh0, r["shares"]]})
        rows.append(row)
    light_bad = [r["symbol"] for r in rows if r.get("light", {}).get("ok") is False]
    return {"compared": len(rows), "failed": sum(not r["ok"] for r in rows), "rows": rows, "skipped": skipped,
            "not_fwd_pe": [r["symbol"] for r in rows if r["primary_basis"] != "fwd_pe"],
            "light_off": light_bad, "normalised_in_window": normalised}


def check_truncation(snap: Path, comps: list, n: int, rnd: random.Random, z: str) -> dict:
    bad, done = [], 0
    per = max(1, n // len(comps))
    filing_cuts = 0
    for _, sym, sector, spans in comps:
        full = P.build(sym, snap, spans, versions=("T",), snapshot_end=z)
        days = [d for i, d in enumerate(full.dates) if d >= R.FIRST_DAY and full.member[i]]
        rows = [r for part in ("inc_q", "inc_a") for r in P.read(snap / "raw" / part / f"{sym}.json") if r.get("date")]
        filings = sorted({filed(r)[0].isoformat() for r in rows} & set(days))
        on_filing = set(rnd.sample(filings, min(len(filings), per)))
        filing_cuts += len(on_filing)
        for cut in sorted(set(rnd.sample(days, min(len(days), per))) | on_filing):
            t = P.build(sym, snap, spans, versions=("T",), truncate=cut, snapshot_end=cut, audit_known=filed)
            k = len(t.dates)
            same = t.dates == full.dates[:k] and t.eps["T"] == full.eps["T"][:k] and \
                t.band["T"] == full.band["T"][:k] and t.atr == full.atr[:k] and \
                t.suspicious == full.suspicious[:k] and \
                all(t.can_start("T", i) == full.can_start("T", i) for i in range(k))
            done += 1
            if not same:
                first = next((i for i in range(k) if t.band["T"][i] != full.band["T"][i] or
                              t.eps["T"][i] != full.eps["T"][i] or t.suspicious[i] != full.suspicious[i]), None)
                bad.append({"symbol": sym, "cut": cut, "first_difference": full.dates[first] if first is not None
                            else None})
    return {"checked": done, "filing_day_cuts": filing_cuts, "failed": len(bad), "failures": bad[:20]}


# The method's rules as SPEC v1 writes them (R1, R3-R5, R8, R9 and section 4), written out apart from sim.Rules
# and sim.temp_of: the trade audit replays every plan with them, so a wrong constant or threshold in sim.py fails it
RICH, HOT = 0.75, 0.95                          # R1: fair <= 0.75 < rich < 0.95 <= hot; no range = unknown
TRAIL_K = {"fair": 3.0, "rich": 2.5, "hot": 2.0, None: 3.0}     # R9's multiples of the ATR, unknown 3.0
TP_W, TAIL, TP1_R = (0.20, 0.30, 0.30), 0.20, 2.0               # R8
WEIGHTS, EVERY, EXPIRY, CHASE = (0.10, 0.20, 0.30, 0.20, 0.20), 10, 120, 0.5    # R5: weekdays, days, ATR
STOP_ATR, T_MIN, T_PROJ, T2_GAP, T2_FALL = 2.0, 1.5, 3.0, 1.0, 5.0             # R3, in ATR
MIN_RR, MIN_RR0, MAX_STOP, COST = 1.5, 1.0, 0.15, 0.0005                       # R4; the cost one way
ENDS_AT_CLOSE = ("delisted", "spin", "expired", "cancelled_below_stop")       # the other ends are at an open


def temperature(rng) -> str | None:
    """R1 on a range (low, mid, high, pct)."""
    if rng is None:
        return None
    return "hot" if rng[3] >= HOT else "rich" if rng[3] > RICH else "fair"


def weekdays_after(d: dt.date, n: int) -> dt.date:
    """R5's tranche dates: n weekdays after d, holidays counted."""
    while n > 0:
        d += dt.timedelta(days=1)
        n -= d.weekday() < 5
    return d


def plan_levels(c: float, a: float, rng) -> dict:
    """R3 and R4 at a close: the stop, the targets, the reward/risk (with the averages formed as the engine forms
    them) and whether the gates pass."""
    stop0 = round(c - STOP_ATR * a, 4)             # 2 ATR below, so the 1-ATR minimum holds by itself
    kept = [round(x, 4) for x in rng[1:3] if x and x >= c + T_MIN * a]
    proj = round(c + T_PROJ * a, 4)
    t1 = kept[0] if kept else proj
    rest = sorted(x for x in kept + [proj] if x >= t1 + T2_GAP * a)
    t2 = rest[0] if rest else round(max(c + T2_FALL * a, t1 + T2_GAP * a), 4)
    p3 = sum(w * c for w in WEIGHTS[:3]) / sum(WEIGHTS[:3])
    p_avg = sum(w * c for w in WEIGHTS) / sum(WEIGHTS)
    rr = None if p3 - stop0 <= 0 else round((t1 - p3) / (p3 - stop0), 2)
    ok = (p_avg - stop0) / p_avg <= MAX_STOP + 1e-12 and (rr is None or rr >= max(MIN_RR, MIN_RR0))
    return {"stop0": stop0, "t1": t1, "t2": t2, "rr": rr, "ok": ok}


def replay_plan(p, pl, v: str) -> dict:
    """SPEC R3-R12 replayed apart from sim.run, close by close from a plan's close to its end, with the rules as
    written above: its levels, its buys [(bar, tranche, shares, cash)], its sales [(bar, reason, shares)], the
    bar and the way it ends, and the tranche fills the chase limit skipped. Only the plan close and the plan's
    size (the sleeve's value then) come from the plan; with the bill's yield never below zero the cash on hand
    never caps a tranche, so each buys its weight of the size."""
    s, n, size = pl.start, len(p.dates), pl.size
    c, a, rng = p.c[s], p.atr[s], p.range_at(v, s)
    d0 = P.day(p.dates[s])
    lv = dict(plan_levels(c, a, rng), price=c, atr=a, expires=(d0 + dt.timedelta(days=EXPIRY)).isoformat(),
              sched=[weekdays_after(d0, k * EVERY).isoformat() for k in range(len(WEIGHTS))])
    out = {"levels": lv, "fills": [], "sales": [], "blocked": 0}
    fills, sales = out["fills"], out["sales"]
    shares, avg, stop, src, hc, trail = 0.0, 0.0, lv["stop0"], "stop", None, None
    fired, tp_sold, cancelled, k_next, order = [False] * 3, [False] * 3, False, 0, None
    if temperature(rng) == "fair":              # tranche 1 is tested at the plan close itself
        order, k_next = ("buy", 0, c + CHASE * a), 1

    def end(i, status):
        return dict(out, end=i, status=status)

    for i in range(s + 1, n):
        if order and order[0] == "sell":        # the open: the sale the last close signalled ...
            q = min(order[1], shares)
            shares -= q
            sales.append((i, order[2], q))
            for t in ([int(x) - 1 for x in order[2][3:].split("+")] if order[2].startswith("tp_") else []):
                tp_sold[t] = True
                if t == 0 and avg > stop:
                    stop, src = avg, "breakeven"
            if shares <= 1e-12 * max(1.0, size):
                return end(i, order[2])
        elif order:                             # ... or the tranche it triggered, unless the open is over its cap
            if order[2] is not None and p.o[i] > order[2]:
                out["blocked"] += 1
                if not fills:
                    return end(i, "lapsed")
                k_next = order[1]
            else:
                amt = WEIGHTS[order[1]] * size
                q = amt / (p.o[i] * (1 + COST))
                avg = (avg * shares + amt) / (shares + q)
                shares += q
                fills.append((i, order[1], q, amt))
        order = None
        c, a, rng = p.c[i], p.atr[i], p.range_at(v, i)          # the close
        temp, last = temperature(rng), i == n - 1
        if shares > 0:
            hc = c if hc is None else max(hc, c)
            if a:
                trail = hc - TRAIL_K[temp] * a if trail is None else max(trail, hc - TRAIL_K[temp] * a)
            eff, why = stop, src
            if tp_sold[1] and trail is not None and trail > eff:  # the trailing stop binds once tp_2 has filled
                eff, why = trail, "trailing"
            if (p.delisted and last) or i in p.spin_exit:
                sales.append((i, "delisted" if p.delisted and last else "spin", shares))
                return end(i, sales[-1][1])
            if c < eff:
                order, cancelled = ("sell", shares, why), True
            else:
                hit = (c >= lv["t1"] or c >= avg + TP1_R * (avg - lv["stop0"]), temp in ("rich", "hot") or
                       c >= lv["t2"], temp == "hot")
                fire = [t for t in range(3) if hit[t] and not fired[t]]
                if fire:
                    left = sum(w for w, d in zip(TP_W, fired) if not d) + TAIL
                    order = ("sell", shares * sum(TP_W[t] for t in fire) / left,
                             "tp_" + "+".join(str(t + 1) for t in fire))
                    for t in fire:
                        fired[t] = True
        elif i in p.spin_exit:                  # nothing bought yet: a spin-off or a close below the stop ends it
            return end(i, "spin")
        elif c < lv["stop0"]:
            return end(i, "cancelled_below_stop")
        if order is None and not cancelled:     # a tranche, on a close with no sale
            if p.dates[i] > lv["expires"]:
                cancelled = True
                if not fills:
                    return end(i, "expired")
            elif k_next < len(WEIGHTS) and p.dates[i] >= lv["sched"][k_next] and temp == "fair" and not last:
                order, k_next = ("buy", k_next, c + CHASE * a if a else None), k_next + 1
    return end(None, "open") if fills else end(n - 1, "unfilled")


def expected_starts(p, out: dict, v: str) -> list:
    """R2 and R12 replayed over a run's closes from 2008-01-02: the bars whose close starts a plan by the rules,
    given when each of the run's plans ended. A plan that ended at an open (a sale there, or a first buy over
    the cap) leaves that bar's close free, one that ended at a close only the next, and an open or unfilled plan
    holds every close to the end."""
    n = len(p.dates)
    busy = [False] * n
    for pl in out["plans"] + out["voids"] + ([out["open"]] if out["open"] else []):
        stop = n if pl.end is None or pl.status == "unfilled" else pl.end + (pl.status in ENDS_AT_CLOSE)
        for i in range(pl.start + 1, stop):
            busy[i] = True
    want = []
    for i in range(bisect.bisect_left(p.dates, R.FIRST_DAY), n - 1):
        rng = p.range_at(v, i)
        if not busy[i] and p.can_start(v, i) and rng is not None and p.atr[i] and p.c[i] < rng[1] and \
                plan_levels(p.c[i], p.atr[i], rng)["ok"]:
            want.append(i)
    return want


def _near(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= 1e-9 * max(1.0, abs(b))
    return a == b


def replay_diff(p, pl, rp: dict) -> dict | None:
    """The first way a plan differs from its replay, with what each side has (a buy as [date, tranche, shares,
    cash], a sale as [date, reason, shares]), or None."""
    lv = rp["levels"]
    keys = [k for k in ("price", "atr", "stop0", "t1", "t2", "rr", "expires", "sched")
            if not _near(getattr(pl, k), lv[k])]
    if keys:
        return {"replay": "levels", "plan": {k: getattr(pl, k) for k in keys}, "rules": {k: lv[k] for k in keys}}
    for kind, got, want in (("buy", [(f[0], f[4], f[2], f[3]) for f in pl.filled], rp["fills"]),
                            ("sale", [(x[0], x[4], x[2]) for x in pl.sold], rp["sales"])):
        k = next((j for j, (x, y) in enumerate(zip(got, want)) if not all(map(_near, x, y))), None)
        if k is None and len(got) != len(want):
            k = min(len(got), len(want))
        if k is not None:
            return {"replay": kind, "plan": [p.dates[got[k][0]], *got[k][1:]] if k < len(got) else None,
                    "rules": [p.dates[want[k][0]], *want[k][1:]] if k < len(want) else None}
    day = lambda i: None if i is None else p.dates[i]                  # noqa: E731
    if (pl.end, pl.status, pl.blocked) != (rp["end"], rp["status"], rp["blocked"]):
        return {"replay": "end", "plan": [day(pl.end), pl.status, pl.blocked],
                "rules": [day(rp["end"]), rp["status"], rp["blocked"]]}
    return None


def plans_digest(p, plans: list, sess: list, zi: int) -> str:
    """The md5 of plans as the rows of their table (run_pilot.TABLE_DIGEST), tabulated here apart from
    placebo.columns, in start order: the start day and its year, whether the 252 and the 126 SPY sessions after
    the start end by session zi (SPEC 5.2), the plan's metrics, its status and buys, the temperature at the start
    and whether that close was below the mid. run_pilot.table_digest gives the same for a table that holds these
    plans, so report.py can see that the plans audited here are the ones the results use."""
    rows = []
    for pl in sorted(plans, key=lambda x: x.start):
        day = p.dates[pl.start]
        row = dict(pl.metrics(), day=day, year=int(day[:4]), full252=sess[pl.start] + 252 <= zi,
                   full126=sess[pl.start] + 126 <= zi, status=pl.status, fills=len(pl.filled), temp0=pl.temp0,
                   below_mid=pl.price < pl.mid0 if pl.mid0 else None)
        rows.append([row[k] for k in R.TABLE_DIGEST])
    return hashlib.md5(json.dumps(rows).encode("utf-8")).hexdigest()


def check_fills(snap: Path, comps: list, z: str, spin: dict) -> dict:
    """The trade audit (SPEC check 6) on the method's runs of both versions, panels and runs as run_pilot makes
    them: every plan close against the signal rule, every plan replayed from its close by the rules as written
    above (levels, buys, sales, end), and the fills themselves: the prices, the trigger closes, the chase limit,
    the cash of each sale, no buy and sale at one open, shares bought = shares sold + shares held. The placebo's
    side too: its pool of start days (placebo.candidates, over the run's days) against the rules (over SPEC's:
    from FIRST_DAY to the bar before the last), and every plan of its every-start table (placebo.every_start,
    what placebo.pool tabulates), which must start on its pool day with size 1, replayed the same way. The
    digests of the method's plans and of the table, tabulated here (plans_digest), go into the result for
    report.py to match with the tables in results.json."""
    rates, spy = M.load(snap)
    zi = bisect.bisect_right(spy.days, z) - 1           # the last SPY session: a window ending later is not full
    bad, fills, sells, plans, pool_days, pool_plans, tables = [], 0, 0, 0, 0, 0, {}
    for key, sym, sector, spans in comps:
        p = P.build(sym, snap, spans, versions=R.VERSIONS, snapshot_end=z, spinoffs=spin.get(key, []))
        hedge = R.hedge_of(p, spy)
        for v in R.VERSIONS:
            r = S.Rules(version=v)
            out = S.run(p, r, rates, first_day=R.FIRST_DAY, hedge=hedge)
            held_end = out["open_value"] / p.c[out["last"]] if out["open"] else 0.0
            every = PL.method_plans(out)
            got, want = sorted(pl.start for pl in every), expected_starts(p, out, v)
            if got != want:
                bad.append({"symbol": sym, "version": v, "replay": "start",
                            "plan": [p.dates[i] for i in sorted(set(got) - set(want))][:5],
                            "rules": [p.dates[i] for i in sorted(set(want) - set(got))][:5]})
            pool = PL.candidates(p, r, out["first"], out["last"])
            mine = [i for i in range(bisect.bisect_left(p.dates, R.FIRST_DAY), len(p.dates) - 1)
                    if p.range_at(v, i) is not None and p.atr[i] and p.can_start(v, i) and
                    plan_levels(p.c[i], p.atr[i], p.range_at(v, i))["ok"]]
            pool_days += len(pool)
            if pool != mine:
                bad.append({"symbol": sym, "version": v, "replay": "pool",
                            "plan": [p.dates[i] for i in sorted(set(pool) - set(mine))][:5],
                            "rules": [p.dates[i] for i in sorted(set(mine) - set(pool))][:5]})
            table = PL.every_start(p, r, rates, hedge, out["first"], out["last"])
            off = next((k for k, (i, pl) in enumerate(zip(pool, table)) if pl.start != i or pl.size != 1.0),
                       None if len(table) == len(pool) else min(len(table), len(pool)))
            if off is not None:
                bad.append({"symbol": sym, "version": v, "replay": "table", "every_start": True,
                            "plan": [p.dates[table[off].start], table[off].size] if off < len(table) else None,
                            "rules": [p.dates[pool[off]], 1.0] if off < len(pool) else None})
            tables.setdefault(v, {})[key] = {"method": plans_digest(p, every, hedge[2], zi),
                                             "pool": plans_digest(p, table, hedge[2], zi)}
            for pl in table:
                pool_plans += 1
                diff = replay_diff(p, pl, replay_plan(p, pl, v))
                if diff:
                    bad.append(dict({"symbol": sym, "version": v, "start": p.dates[pl.start], "every_start": True},
                                    **diff))
            for pl in every:
                plans += 1
                tag = {"symbol": sym, "version": v, "start": p.dates[pl.start]}
                diff = replay_diff(p, pl, replay_plan(p, pl, v))
                if diff:
                    bad.append(dict(tag, **diff))
                for k, f in enumerate(pl.filled):
                    sig = f[0] - 1
                    fills += 1
                    ok = f[4] == k and f[1] == p.o[f[0]] and pl.sched[k] <= p.dates[sig] <= pl.expires and \
                        temperature(p.range_at(v, sig)) == "fair" and \
                        (not p.atr[sig] or f[1] <= p.c[sig] + CHASE * p.atr[sig] + 1e-9) and \
                        (sig == pl.start if k == 0 else sig >= pl.filled[k - 1][0])
                    if not ok:
                        bad.append(dict(tag, fill=p.dates[f[0]], tranche=k))
                at_open = set()
                for s in pl.sold:
                    sells += 1
                    close = s[4] in R.AT_CLOSE
                    if s[1] != (p.c[s[0]] if close else p.o[s[0]]) or \
                            abs(s[3] - s[2] * s[1] * (1 - COST)) > 1e-9 * max(1.0, abs(s[3])):
                        bad.append(dict(tag, sale=[p.dates[s[0]], s[4], s[1], s[2], s[3]]))
                    if not close:
                        at_open.add(s[0])
                both = at_open & {f[0] for f in pl.filled}
                if both:
                    bad.append(dict(tag, buy_and_sale_at_one_open=sorted(p.dates[i] for i in both)))
                bought = sum(f[2] for f in pl.filled)
                left = bought - sum(s[2] for s in pl.sold)
                held = held_end if pl is out["open"] else 0.0
                if abs(left - held) > 1e-9 * max(1.0, bought):
                    bad.append(dict(tag, shares_left=left, held=held))
                if not pl.filled and (pl.sold or pl.status not in VOID):
                    bad.append(dict(tag, void=pl.status))
    return {"plans": plans, "fills": fills, "sales": sells, "pool_days": pool_days, "every_start_plans": pool_plans,
            "failed": len(bad), "failures": bad[:20], "tables": tables}


def check_spins(snap: Path, comps: list, events: dict, z: str) -> list:
    """SPEC 2.6: for every listed spin-off and every panel.spin_candidates move of a company, the /full closes
    from 2 sessions before the date to 2 after, the day's move against SPY's, the distribution the
    dividend-adjusted series implies (d = C_(e-1) x adj_e / adj_(e-1) - C_e, as a share of C_(e-1)), for a
    listed date the largest drop against SPY within SPIN_LOOK sessions (dates are from memory), and the split
    rows within 30 days. Marking an event confirmed in spinoffs.json is done by eye from this."""
    _, spy = M.load(snap)
    out = []
    for key, sym, sector, spans in comps:
        raw = snap / "raw"
        bars, _, _ = P.clean_bars(P.read(raw / "full" / f"{sym}.json"), P.read(raw / "adj" / f"{sym}.json"),
                                  P.read(raw / "splits" / f"{sym}.json"))
        bars = [b for b in bars if b["date"] <= z]
        if len(bars) < 2:
            continue
        dates, close = [b["date"] for b in bars], [b["c"] for b in bars]
        adj = {str(r["date"])[:10]: P.fnum(r.get("adjClose")) for r in P.read(raw / "adj" / f"{sym}.json")
               if r.get("date")}
        split_rows = P.read(raw / "splits" / f"{sym}.json")
        listed = [str(x["date"])[:10] for x in events.get(key, [])]
        cands = [c["date"] for c in P.spin_candidates(bars, split_rows, P.read(raw / "earn" / f"{sym}.json"))]

        def rel(j):
            sm = spy.close_on(dates[j]) / spy.close_on(dates[j - 1]) - 1.0 if spy.close_on(dates[j - 1]) else 0.0
            return close[j] / close[j - 1] - 1.0 - sm, sm

        for d, src in [(d, "listed") for d in listed] + [(d, "candidate") for d in cands if d not in listed]:
            e = bisect.bisect_left(dates, d)
            if not 0 < e < len(dates):
                out.append({"symbol": key, "date": d, "source": src, "note": "outside the bars"})
                continue
            move, spy_move = rel(e)
            a0, a1 = adj.get(dates[e - 1]), adj.get(dates[e])
            dist = close[e - 1] * a1 / a0 - close[e] if a0 and a1 else None
            row = {"symbol": key, "series": sym, "date": d, "source": src, "bar": dates[e],
                   "closes": [[dates[j], close[j]] for j in range(max(0, e - 2), min(len(dates), e + 3))],
                   "move_vs_spy": round(move, 4), "spy_move": round(spy_move, 4),
                   "implied_distribution": None if dist is None else round(dist / close[e - 1], 4),
                   "splits_near": [r for r in split_rows if r.get("date") and
                                   abs((P.day(r["date"]) - P.day(dates[e])).days) <= 30]}
            if src == "listed":
                js = range(max(1, e - SPIN_LOOK), min(len(dates), e + SPIN_LOOK + 1))
                j = min(js, key=lambda k: rel(k)[0])
                row["largest_drop"] = {"bar": dates[j], "move_vs_spy": round(rel(j)[0], 4)}
            out.append(row)
    return out


def check_basis(snap: Path, comps: list, z: str) -> dict:
    out = {}
    for _, sym, sector, spans in comps:
        p = P.build(sym, snap, spans, versions=("T",), snapshot_end=z)
        rep = p.report
        keep = {k: rep[k] for k in ("basis_q", "basis_a", "annual_vs_quarters", "spin_candidates")}
        if any(keep["basis_q"].get(k) or keep["basis_a"].get(k) for k in
               ("boundary", "partial", "share_steps", "eps_units", "eps_shares", "review")) or keep["annual_vs_quarters"] \
                or keep["spin_candidates"]:
            out[sym] = json.loads(json.dumps(keep, default=str))
    return out


def panel_facts(snap: Path, comps: list, z: str, spin: dict) -> dict:
    """Per company, what the data review table lists from the panels run_pilot builds."""
    out = {}
    for key, sym, sector, spans in comps:
        p = P.build(sym, snap, spans, versions=R.VERSIONS, snapshot_end=z, spinoffs=spin.get(key, []))
        rep = R.report_of(p)
        unclear = {k: sum(b.get("rows_changed", 0) for b in rep[k].get("boundary", []) if b["action"] == "unclear")
                   for k in ("basis_q", "basis_a")}
        out[key] = {"series": sym, "sector": sector, "delisted": p.delisted, "first_bar": rep["first_bar"],
                    "last_bar": rep["last_bar"], "suspicious_member_days": rep["suspicious_member_days"],
                    "jumps": len(rep["jumps"]), "unclear_rows": unclear,
                    "placeholders": {k: [rep[k].get("placeholders", 0), rep[k].get("rows", 0)]
                                     for k in ("basis_q", "basis_a")},
                    "no_band": rep["member_days_by_reason"]}
    return out


def review_table(walk: dict, facts: dict, basis: dict, spins: list, res: dict) -> str:
    """The data review table (SPEC check 7) as Markdown, in Chinese: signed off before any result is opened."""
    w = ["# 数据核对表（看结果之前签字）\n", f"快照最后一天 {walk['z']}；公司 {len(walk['companies'])} 家\n",
         "## 可用规则（U1–U4）和替换\n"]
    swaps = [x for x in walk["replacements"] if x.get("in")]
    w += [f"- {x['out']} → {x['in'] or '找不到可用的替补'}：{x['why']}"
          + ("（跳过 " + "，".join(f"{t['key']}：{t['why']}" for t in x["tried"]) + "）" if x.get("tried") else "")
          for x in walk["replacements"]] or ["- 没有替换"]
    w += [f"- 待人工看：{x}" for x in walk.get("review", [])]
    w.append(f"\n替换 {len(swaps)} 家。\n")
    w.append("## 每家公司\n")
    w.append("| 公司 | 板块 | 有行情（U1） | 有 TTM（U2） | 首末行情 | 退市 | 可疑交易日 | 跳空 | 季报占位日 | 年报占位日 | "
             "拆股不明的季/年 |")
    w.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for k, f in facts.items():
        pq, pa = f["placeholders"]["basis_q"], f["placeholders"]["basis_a"]
        share = lambda x: f"{x[0]}/{x[1]}"                                        # noqa: E731
        u = walk.get("assessed", {}).get(k, {})
        w.append(f"| {k} | {f['sector']} | {u.get('bars', 0):.1%} | {u.get('ttm', 0):.1%} | "
                 f"{f['first_bar']} 到 {f['last_bar']} | {'是' if f['delisted'] else ''} | "
                 f"{f['suspicious_member_days'] or ''} | {f['jumps'] or ''} | {share(pq)} | {share(pa)} | "
                 f"{'' if not any(f['unclear_rows'].values()) else '{basis_q}/{basis_a}'.format(**f['unclear_rows'])} |")
    w.append("\n## 在指数内、没有区间的交易日（按原因）\n")
    for v in R.VERSIONS:
        tot = {}
        for f in facts.values():
            for why, n in f["no_band"].get(v, {}).items():
                tot[why] = tot.get(why, 0) + n
        all_ = sum(tot.values()) or 1
        w.append(f"- {v} 版：" + "，".join(f"{why} {n}（{n / all_:.1%}）" for why, n in
                                          sorted(tot.items(), key=lambda kv: -kv[1])))
    w.append("\n## 拆股口径和报表\n")
    for sym, b in basis.items():
        parts = []
        for k, name in (("basis_q", "季报"), ("basis_a", "年报")):
            x = b.get(k, {})
            for d in x.get("boundary", []):
                head = f"{name} 拆股 {d['split']}×{d['factor']:g} "
                if d["action"] == "no row after":
                    parts.append(head + "之后还没有新报表，不用改")
                elif d["action"] == "unclear":
                    why = (f"前后股数比 {d['ratio']:g}" if "verdict_known" not in d else
                           f"能判定口径的报表 {d['verdict_known']} 才公布，晚于拆股后的第一份报表"
                           if d["verdict_known"] else "拆股后的报表里还没有能判定口径的")
                    parts.append(head + f"口径不明（{why}）：之前公布的 {d['rows_changed']} 行"
                                 + (f"在 {d['unused_after']} 之后不再用于 T 版" if d.get("unused_after")
                                    else " EPS 清空（只影响 F 版）"))
                else:
                    parts.append(head + ("旧报表没重述，按倍数改" if d["action"] == "not_restated" else "旧报表已重述")
                                 + f"（改 {d['rows_changed']} 行）")
            parts += [f"{name} 部分重述 {len(x['partial'])} 处"] if x.get("partial") else []
            parts += [f"{name} EPS 和股数口径不同、按之后拆股的倍数改了 {len(x['eps_shares'])} 行（"
                      + "，".join(f"{u['end']} ÷{u['fixed_by']:g}（{'、'.join(u['splits'])} 拆股）"
                                 for u in x["eps_shares"][:8])
                      + ("…" if len(x["eps_shares"]) > 8 else "") + "）"] if x.get("eps_shares") else []
            parts += [f"{name} EPS 单位错、改成净利润÷股数 {len(x['eps_units'])} 行（"
                      + "，".join(f"{u['end']} {u['eps']:g}→{u['now']:g}" for u in x["eps_units"]) + "）"] \
                if x.get("eps_units") else []
            parts += [f"{name} EPS×股数÷净利润不在 0.6–1.6、只列出 {len(x['review'])} 行（"
                      + "，".join(f"{u['end']} {u['eps_x_shares_over_ni']:g}" for u in x["review"][:8])
                      + ("…" if len(x["review"]) > 8 else "") + "）"] if x.get("review") else []
            parts += [f"{name} 相邻两期股数跳变、拆股解释不了，只列出 {len(x['share_steps'])} 处（"
                      + "，".join(f"{u['older_end']}→{u['newer_end']} ×{u['ratio']:g}" for u in x["share_steps"][:8])
                      + ("…" if len(x["share_steps"]) > 8 else "") + "）"] if x.get("share_steps") else []
        parts += [f"年报和四季之和不符 {len(b['annual_vs_quarters'])} 年"] if b.get("annual_vs_quarters") else []
        parts += [f"大幅单日涨跌 {len(b['spin_candidates'])} 次"] if b.get("spin_candidates") else []
        if parts:
            w.append(f"- {sym}：" + "；".join(parts))
    w.append("\n## 分拆核对（据此在 spinoffs.json 里标 confirmed）\n")
    w.append("| 公司 | 日期 | 来源 | 当天相对 SPY | 调整价隐含的分配 | 附近最大跌幅 | 附近拆股行 |")
    w.append("|---|---|---|---|---|---|---|")
    for x in spins:
        if "bar" not in x:
            w.append(f"| {x['symbol']} | {x['date']} | {x['source']} | {x['note']} | | | |")
            continue
        ld = x.get("largest_drop")
        w.append(f"| {x['symbol']} | {x['bar']} | {x['source']} | {x['move_vs_spy']:+.1%} | "
                 f"{'' if x['implied_distribution'] is None else format(x['implied_distribution'], '+.1%')} | "
                 f"{'' if not ld else ld['bar'] + ' ' + format(ld['move_vs_spy'], '+.1%')} | "
                 f"{len(x['splits_near']) or ''} |")
    w.append("\n## 各项检查\n")
    for k, v in res.items():
        if isinstance(v, dict) and "failed" in v:
            n = v.get("checked", v.get("compared", v.get("fills")))
            w.append(f"- {k}：{n} 项，失败 {v['failed']}")
    return "\n".join(w) + "\n"


def same_results(a: Path, b: Path) -> list:
    """Check 8: the outputs of run_pilot (R.OUTPUTS and the pools_*.json of either run) that differ between two
    runs or that either lacks (results.json apart from its creation time). Other files in the folders, such as
    checks.json, review.md, repro.json or a saved report, are not the runs' outputs and are left out."""
    diff = []
    for name in list(R.OUTPUTS) + sorted({q.name for d in (a, b) for q in d.glob("pools_*.json")}):
        pa, pb = a / name, b / name
        if not (pa.is_file() and pb.is_file()):
            diff.append(name)
            continue
        if name == "results.json":
            x, y = (json.loads(q.read_text(encoding="utf-8")) for q in (pa, pb))
            x.pop("created", None)
            y.pop("created", None)
            same = x == y
        else:
            same = pa.read_bytes() == pb.read_bytes()
        if not same:
            diff.append(name)
    return diff


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snap")
    ap.add_argument("--out")
    ap.add_argument("--pairs", type=int, default=200)
    ap.add_argument("--sample", default=str(HERE / "sample.json"))
    ap.add_argument("--spinoffs", default=str(HERE / "spinoffs.json"))
    ap.add_argument("--only", nargs="*", default=["calendar", "band", "pipeline", "truncation", "fills", "basis",
                                                  "spins", "review"])
    ap.add_argument("--same", nargs=2, metavar="OUT", help="compare two run_pilot outputs (check 8) and stop")
    a = ap.parse_args(argv)
    if a.same:
        x, y = (Path(d) for d in a.same)
        if not (x.is_dir() and y.is_dir()) or os.path.samefile(x, y):
            print("refused: check 8 compares the folders of two separate runs")
            return 2
        diff = same_results(x, y)
        digests = [RP.results_digest(json.loads((Path(d) / "results.json").read_text(encoding="utf-8")))
                   if (Path(d) / "results.json").is_file() else None for d in a.same]
        (Path(a.same[0]) / "repro.json").write_text(json.dumps({"same": not diff, "diff": diff, "results": digests}),
                                                    encoding="utf-8")
        print("same" if not diff else f"differ: {diff}")
        return 1 if diff else 0
    if not (a.snap and a.out):
        ap.error("--snap and --out are required")
    snap, out = Path(a.snap), Path(a.out)
    if out.resolve() == snap.resolve() or snap.resolve() in out.resolve().parents:
        print("refused: --out is the snapshot folder or inside it")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for name in ("checks.json", "review.md"):      # a run that fails leaves no earlier checks behind
        (out / name).unlink(missing_ok=True)
    code, before = RP.checks_code(), R.inputs(snap, Path(a.sample), Path(a.spinoffs))     # before anything is read
    if M.check_manifest(snap):
        print("snapshot refused: files differ from the manifest")
        return 2
    sample = json.loads(Path(a.sample).read_text(encoding="utf-8"))
    events = json.loads(Path(a.spinoffs).read_text(encoding="utf-8"))["events"]
    spin = {k: [x["date"] for x in v if x.get("confirmed")] for k, v in events.items()}
    comps, walk = R.choose(snap, sample)
    if walk.get("same_as_pc") is False:
        print("snapshot refused: the replacement walk here differs from the PC's (status.json)")
        return 2
    gaps = M.check_complete(snap, [c[1] for c in comps])
    if gaps:
        print(f"snapshot refused: {len(gaps)} parts failed or are missing, e.g. {gaps[:3]}")
        return 2
    z = walk["z"]
    rnd = random.Random(SEED)
    res = {}
    if "calendar" in a.only:
        res["calendar"] = check_calendar(snap, comps, z)
    if "band" in a.only:
        res["band"] = check_band(snap, comps, a.pairs, rnd, z)
    if "pipeline" in a.only:
        res["pipeline"] = check_pipeline(snap, comps)
    if "truncation" in a.only:
        res["truncation"] = check_truncation(snap, comps, a.pairs, rnd, z)
    if "fills" in a.only:
        res["fills"] = check_fills(snap, comps, z, spin)
    if "basis" in a.only or "review" in a.only:
        res["basis"] = check_basis(snap, comps, z)
    if "spins" in a.only or "review" in a.only:
        res["spins"] = check_spins(snap, comps, events, z)
    if "review" in a.only:                          # written first: checks.json without it does not pass
        text = review_table(walk, panel_facts(snap, comps, z, spin), res["basis"], res["spins"], res)
        (out / "review.md").write_text(text, encoding="utf-8")
        res["review"] = {"written": True}
    if R.inputs(snap, Path(a.sample), Path(a.spinoffs)) != before or RP.checks_code() != code:
        (out / "review.md").unlink(missing_ok=True)
        print("refused: the snapshot's manifest, the sample, the spin-offs or the code changed during the checks")
        return 2
    res["inputs"], res["checks_code"], res["pairs"] = before, code, a.pairs
    (out / "checks.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    for k, v in res.items():
        if isinstance(v, dict) and "failed" in v:
            print(k, {x: y for x, y in v.items() if x in ("checked", "compared", "plans", "fills", "sales",
                                                          "every_start_plans", "failed")})
    print("basis: review", len(res.get("basis", {})), "companies;", "spin-off rows", len(res.get("spins", [])))
    return 1 if any(isinstance(v, dict) and v.get("failed") for v in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
