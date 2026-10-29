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
  fills      the trade audit: every buy at the open after a fair close on or after its tranche date and by the
             expiry, under the chase limit, tranche k after k - 1, never at an open that fills a sale of the
             plan; every sale at the open after its signal close, except the delisting and spin-off sales at
             the close of their bar; shares bought = shares sold + shares held for every plan
  basis      the statement basis decisions, EPS x shares / net income outliers and annual-vs-quarters gaps of
             every company, for review by eye
  spins      the evidence to confirm each spin-off (the listed events and panel.spin_candidates): the /full
             closes around the date, the distribution the dividend-adjusted series implies, nearby split rows
  review     the data review table (review.md, check 7), written before any result is opened

    python backtest/pilot/checks.py --snap DIR --out DIR [--pairs 200]
    python backtest/pilot/checks.py --same OUT_1 OUT_2        # check 8: two runs give the same results
                                                              # (writes OUT_1/repro.json for report.py)
"""
from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import market as M  # noqa: E402
import panel as P  # noqa: E402
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
        years = P.statement_rows(P.read(snap / "raw" / "inc_a" / f"{sym}.json"), sp, {}, unclear="none")
        quarters = P.statement_rows(P.read(snap / "raw" / "inc_q" / f"{sym}.json"), sp, {}, unclear="none")
        days = [i for i, d in enumerate(p.dates) if d >= R.FIRST_DAY and p.member[i]]
        for i in rnd.sample(days, min(len(days), per)):
            for v in ("T", "F"):
                d = P.day(p.dates[i])
                start = (d - dt.timedelta(days=P.LOOKBACK_DAYS)).isoformat()
                window = [(p.dates[j], p.c[j]) for j in range(i + 1) if p.dates[j] >= start]
                yrs = [{"date": y["end"].isoformat(), "shares": y["shares"]} for y in P.latest_by_end(years, d)]
                qs = [q for q in quarters if q["known"] < d and q["shares"]]
                cur = max(qs, key=lambda q: (q["known"], q["end"]))["shares"] if qs else None
                code = A.history_problem(yrs, window, start, cur)[0]
                eps = dict(zip(p.dates, p.eps[v]))
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
        if want is None or got is None:
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
                                  unclear="none"):
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
                t.band["T"] == full.band["T"][:k] and t.atr == full.atr[:k]
            done += 1
            if not same:
                first = next((i for i in range(k) if t.band["T"][i] != full.band["T"][i] or
                              t.eps["T"][i] != full.eps["T"][i]), None)
                bad.append({"symbol": sym, "cut": cut, "first_difference": full.dates[first] if first is not None
                            else None})
    return {"checked": done, "filing_day_cuts": filing_cuts, "failed": len(bad), "failures": bad[:20]}


def check_fills(snap: Path, comps: list, z: str, spin: dict) -> dict:
    """The trade audit (SPEC check 6) on the method's runs of both versions, panels as run_pilot builds them."""
    rates, _ = M.load(snap)
    bad, fills, sells, plans = [], 0, 0, 0
    for key, sym, sector, spans in comps:
        p = P.build(sym, snap, spans, versions=R.VERSIONS, snapshot_end=z, spinoffs=spin.get(key, []))
        for v in R.VERSIONS:
            r = S.Rules(version=v)
            out = S.run(p, r, rates, first_day=R.FIRST_DAY)
            held_end = out["open_value"] / p.c[out["last"]] if out["open"] else 0.0
            for pl in out["plans"] + ([out["open"]] if out["open"] else []) + out["voids"]:
                plans += 1
                tag = {"symbol": sym, "version": v, "start": p.dates[pl.start]}
                for k, f in enumerate(pl.filled):
                    sig = f[0] - 1
                    fills += 1
                    ok = f[4] == k and f[1] == p.o[f[0]] and pl.sched[k] <= p.dates[sig] <= pl.expires and \
                        S.temp_of(p.range_at(v, sig), r) == "fair" and f[1] <= p.c[sig] + 0.5 * p.atr[sig] + 1e-9 and \
                        (sig == pl.start if k == 0 else sig >= pl.filled[k - 1][0])
                    if not ok:
                        bad.append(dict(tag, fill=p.dates[f[0]], tranche=k))
                at_open = set()
                for s in pl.sold:
                    sells += 1
                    close = s[4] in R.AT_CLOSE
                    if s[1] != (p.c[s[0]] if close else p.o[s[0]]):
                        bad.append(dict(tag, sale=p.dates[s[0]], why=s[4]))
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
    return {"plans": plans, "fills": fills, "sales": sells, "failed": len(bad), "failures": bad[:20]}


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
               ("boundary", "partial", "share_steps", "eps_shares", "review")) or keep["annual_vs_quarters"] \
                or keep["spin_candidates"]:
            out[sym] = json.loads(json.dumps(keep, default=str))
    return out


def panel_facts(snap: Path, comps: list, z: str, spin: dict) -> dict:
    """Per company, what the data review table lists from the panels run_pilot builds."""
    out = {}
    for key, sym, sector, spans in comps:
        p = P.build(sym, snap, spans, versions=R.VERSIONS, snapshot_end=z, spinoffs=spin.get(key, []))
        rep = R.report_of(p)
        unclear = {k: sum(b["rows_changed"] for b in rep[k].get("boundary", []) if b["action"] == "unclear")
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
    w += [f"- {x['out']} → {x['in']}：{x['why']}" + (f"（试过 {', '.join(x['tried'])}）" if x.get("tried") else "")
          for x in walk["replacements"]] or ["- 没有替换"]
    w += [f"- 待人工看：{x}" for x in walk.get("review", [])]
    w.append(f"\n替换 {len(swaps)} 家。\n")
    w.append("## 每家公司\n")
    w.append("| 公司 | 板块 | 首末行情 | 退市 | 可疑交易日 | 跳空 | 季报占位日 | 年报占位日 | 拆股不明清空的季/年 |")
    w.append("|---|---|---|---|---|---|---|---|---|")
    for k, f in facts.items():
        pq, pa = f["placeholders"]["basis_q"], f["placeholders"]["basis_a"]
        share = lambda x: f"{x[0]}/{x[1]}"                                        # noqa: E731
        w.append(f"| {k} | {f['sector']} | {f['first_bar']} 到 {f['last_bar']} | {'是' if f['delisted'] else ''} | "
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
                parts.append(f"{name} 拆股 {d['split']}×{d['factor']:g} {d['action']}（改 {d['rows_changed']} 行）")
            parts += [f"{name} 部分重述 {len(x['partial'])} 处"] if x.get("partial") else []
            parts += [f"{name} EPS×股数/净利润异常 {len(x['eps_shares'])} 行"] if x.get("eps_shares") else []
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
    """Check 8: the files two runs wrote that differ (results.json apart from its creation time)."""
    diff = []
    for name in sorted(({p.name for p in a.iterdir()} | {p.name for p in b.iterdir()}) - {"repro.json"}):
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
        diff = same_results(Path(a.same[0]), Path(a.same[1]))
        (Path(a.same[0]) / "repro.json").write_text(json.dumps({"same": not diff, "diff": diff}), encoding="utf-8")
        print("same" if not diff else f"differ: {diff}")
        return 1 if diff else 0
    if not (a.snap and a.out):
        ap.error("--snap and --out are required")
    snap, out = Path(a.snap), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
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
    (out / "checks.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    if "review" in a.only:
        text = review_table(walk, panel_facts(snap, comps, z, spin), res["basis"], res["spins"], res)
        (out / "review.md").write_text(text, encoding="utf-8")
    for k, v in res.items():
        if isinstance(v, dict) and "failed" in v:
            print(k, {x: y for x, y in v.items() if x in ("checked", "compared", "plans", "fills", "sales", "failed")})
    print("basis: review", len(res.get("basis", {})), "companies;", "spin-off rows", len(res.get("spins", [])))
    return 1 if any(isinstance(v, dict) and v.get("failed") for v in res.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
