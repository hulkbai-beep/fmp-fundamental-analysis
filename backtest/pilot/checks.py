#!/usr/bin/env python3
"""
Checks before any result is read, on the frozen snapshot (all in the cloud):

  band       the fast daily band equals the skill's analyze.multiple_bands and the full analyze.history_problem
             on random (company, day, version) triples
  pipeline   at the snapshot's last day, for every company still listed with analysts' estimates: the pilot's
             band code fed the skill's own next-twelve-month EPS (reported years, then today's consensus)
             reproduces analyze.price_range's forward-P/E band and 'now' range exactly
  truncation version T: deleting every bar after a cut and every statement filed on or after it (by this
             file's own reading of the filing dates) changes nothing on or before the cut
  fills      every buy at the open after a fair close on or after its tranche date and under the chase limit,
             every sale at the open after its signal close, tranche k after k - 1
  basis      the statement basis decisions, EPS x shares / net income outliers and annual-vs-quarters gaps of
             every company, for review by eye

    python backtest/pilot/checks.py --snap DIR --out DIR [--pairs 200]
"""
from __future__ import annotations

import argparse
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
SEED = 20261029
LAG = {"Q1": 45, "Q2": 45, "Q3": 45, "Q4": 90, "FY": 90}


def filed(r: dict):
    """This check's own reading of when a statement row became public (written apart from panel.known_day):
    the filing date when it is at least 10 days after the period end, else the period end + 45 / 90 days."""
    end = dt.date.fromisoformat(str(r["date"])[:10])
    f = str(r.get("filingDate") or r.get("acceptedDate") or "")[:10]
    if f and f >= (end + dt.timedelta(days=10)).isoformat():
        return dt.date.fromisoformat(f), False
    return end + dt.timedelta(days=LAG.get(str(r.get("period") or "FY").upper(), 90)), True


def check_band(snap: Path, comps: list, n: int, rnd: random.Random) -> dict:
    bad, done = [], 0
    picked = rnd.sample(comps, min(len(comps), 25))
    per = max(1, n // len(picked))
    for _, sym, sector, spans in picked:
        p = P.build(sym, snap, spans)
        sp = P.split_factors(P.read(snap / "raw" / "splits" / f"{sym}.json"))
        years = P.statement_rows(P.read(snap / "raw" / "inc_a" / f"{sym}.json"), sp, {})
        quarters = P.statement_rows(P.read(snap / "raw" / "inc_q" / f"{sym}.json"), sp, {})
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


def check_pipeline(snap: Path, comps: list) -> dict:
    """The skill's price_range at the last day against the pilot's band code on the same inputs."""
    raw = snap / "raw"
    rows, skipped = [], []
    for _, sym, sector, spans in comps:
        bars = sorted((str(r["date"])[:10], P.fnum(r.get("close"))) for r in P.read(raw / "full" / f"{sym}.json"))
        bars = [(d, c) for d, c in bars if c]
        est = P.read(raw / "est" / f"{sym}.json")
        prof = (P.read(raw / "profile" / f"{sym}.json") or [{}])[0]
        if not bars or not est:
            skipped.append({"symbol": sym, "why": "no estimates" if bars else "no bars"})
            continue
        z, close = bars[-1]
        inc_a = sorted(P.read(raw / "inc_a" / f"{sym}.json"), key=lambda r: str(r.get("date")))[-5:]
        years = A.build_years(inc_a, [], [])
        price = close
        mcap = P.fnum(prof.get("marketCap") or prof.get("mktCap"))
        cur_shares = mcap / P.fnum(prof.get("price")) if mcap and P.fnum(prof.get("price")) else None
        analyst = A.analyst_view(est, None, years[-1], price, z)
        if len([e for e in analyst.get("estimates", []) if not e["ended"]]) < 2:
            skipped.append({"symbol": sym, "why": "fewer than two estimate years"})
            continue
        pr = A.price_range(years, {}, bars, analyst, {}, price, dt.date.fromisoformat(z), cur_shares)
        # the pilot's code on the same inputs: EPS = the skill's NTM blend of reported years and estimates
        ntm = A._ntm([(y["date"], y["eps"]) for y in years if y.get("eps") is not None] +
                     [(e["date"], e["eps_avg"]) for e in analyst["estimates"] if e.get("eps_avg") is not None])
        dates = [d for d, _ in bars]
        closes = [c for _, c in bars]
        eps = [ntm(d) for d in dates]
        yrows = [{"end": dt.date.fromisoformat(y["date"]), "known": dt.date.fromisoformat(y["date"]),
                  "shares": y.get("shares")} for y in years]
        q_shares = [(dt.date.fromisoformat(z) - dt.timedelta(days=1), None, cur_shares)] if cur_shares else []
        band, why = P.bands(dates, closes, eps, [None] * len(dates), yrows, q_shares, z)
        got, want = band[-1], pr["pe_band"]
        row = {"symbol": sym, "day": z, "skill_note": pr.get("band_note"), "pilot_why": why[-1],
               "eps_basis_gap": (analyst.get("eps_basis") or {}).get("gap")}
        if want is None or got is None:
            row["ok"] = (want is None) == (got is None)
        else:
            now = pr["forward"][0]["pe"] if pr["forward"] else None
            e_now = eps[-1]
            diffs = [abs(got[k] - want[k]) / abs(want[k]) for k in ("p25", "median", "p75")]
            diffs.append(abs(got["pct"] - want["now_pct"]))
            if now:
                diffs += [abs(e_now * got[q] - now[k]) / abs(now[k]) for k, q in
                          (("low", "p25"), ("base", "median"), ("high", "p75"))]
            row["max_rel_diff"] = max(diffs)
            row["ok"] = max(diffs) <= 1e-9
            row["mid"] = e_now * got["median"]
        rows.append(row)
    return {"compared": len(rows), "failed": sum(not r["ok"] for r in rows), "rows": rows, "skipped": skipped}


def check_truncation(snap: Path, comps: list, n: int, rnd: random.Random) -> dict:
    bad, done = [], 0
    per = max(1, n // len(comps))
    for _, sym, sector, spans in comps:
        full = P.build(sym, snap, spans, versions=("T",))
        days = [d for i, d in enumerate(full.dates) if d >= R.FIRST_DAY and full.member[i]]
        for cut in sorted(rnd.sample(days, min(len(days), per))):
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
    return {"checked": done, "failed": len(bad), "failures": bad[:20]}


def check_fills(snap: Path, comps: list) -> dict:
    rates, _ = M.load(snap)
    bad, fills, sells = [], 0, 0
    for _, sym, sector, spans in comps:
        p = P.build(sym, snap, spans)
        for v in R.VERSIONS:
            r = S.Rules(version=v)
            out = S.run(p, r, rates, first_day=R.FIRST_DAY)
            for pl in out["plans"] + ([out["open"]] if out["open"] else []):
                for k, f in enumerate(pl.filled):
                    sig = f[0] - 1
                    fills += 1
                    ok = f[4] == k and f[1] == p.o[f[0]] and p.dates[sig] >= pl.sched[k] and \
                        S.temp_of(p.range_at(v, sig), r) == "fair" and f[1] <= p.c[sig] + 0.5 * p.atr[sig] + 1e-9 and \
                        (k == 0 and sig == pl.start or k > 0 and sig >= pl.filled[k - 1][0])
                    if not ok:
                        bad.append({"symbol": sym, "version": v, "fill": p.dates[f[0]], "tranche": k})
                for s in pl.sold:
                    sells += 1
                    if s[4] != "delisted" and s[1] != p.o[s[0]]:
                        bad.append({"symbol": sym, "version": v, "sale": p.dates[s[0]]})
    return {"fills": fills, "sales": sells, "failed": len(bad), "failures": bad[:20]}


def check_basis(snap: Path, comps: list) -> dict:
    out = {}
    for _, sym, sector, spans in comps:
        p = P.build(sym, snap, spans, versions=("T",))
        rep = p.report
        keep = {k: rep[k] for k in ("basis_q", "basis_a", "annual_vs_quarters", "spin_candidates")}
        if any(keep["basis_q"].get(k) or keep["basis_a"].get(k) for k in
               ("boundary", "partial", "share_steps", "eps_shares", "review")) or keep["annual_vs_quarters"] \
                or keep["spin_candidates"]:
            out[sym] = json.loads(json.dumps(keep, default=str))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snap", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs", type=int, default=200)
    ap.add_argument("--sample", default=str(HERE / "sample.json"))
    ap.add_argument("--only", nargs="*", default=["band", "pipeline", "truncation", "fills", "basis"])
    a = ap.parse_args(argv)
    snap, out = Path(a.snap), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if M.check_manifest(snap):
        print("snapshot refused: files differ from the manifest")
        return 2
    sample = json.loads(Path(a.sample).read_text(encoding="utf-8"))
    comps, walk = R.choose(snap, sample)
    if walk.get("same_as_pc") is False:
        print("snapshot refused: the replacement walk here differs from the PC's (status.json)")
        return 2
    rnd = random.Random(SEED)
    res = {}
    if "band" in a.only:
        res["band"] = check_band(snap, comps, a.pairs, rnd)
    if "pipeline" in a.only:
        res["pipeline"] = check_pipeline(snap, comps)
    if "truncation" in a.only:
        res["truncation"] = check_truncation(snap, comps, a.pairs, rnd)
    if "fills" in a.only:
        res["fills"] = check_fills(snap, comps)
    if "basis" in a.only:
        res["basis"] = check_basis(snap, comps)
    (out / "checks.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    for k, v in res.items():
        if k != "basis":
            print(k, {x: y for x, y in v.items() if x in ("checked", "compared", "fills", "sales", "failed")})
    print("basis: review", len(res.get("basis", {})), "companies")
    return 1 if any(v.get("failed") for k, v in res.items() if k != "basis") else 0


if __name__ == "__main__":
    sys.exit(main())
