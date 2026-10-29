#!/usr/bin/env python3
"""
Run the forward-P/E band pilot on a frozen snapshot: the user's buy method on the 50 drawn companies with EPS
version T (the main result) and F / FY (optimistic ceilings), the descriptive variants, the random-timing
placebo, buy-and-hold of the same companies and SPY. Writes results.json, plans.csv and portfolio.json to
--out (report.py turns them into the report).

    python backtest/pilot/run_pilot.py --snap DIR --out DIR [--replicas 1000] [--workers 4] [--quick]

All computing happens here; the snapshot is refused when a file differs from its manifest.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import json
import sys
from dataclasses import asdict, replace
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import market as M  # noqa: E402
import panel as P  # noqa: E402
import placebo as PL  # noqa: E402
import sim as S  # noqa: E402
import stats as ST  # noqa: E402

FIRST_DAY = "2008-01-02"
VERSIONS = ("T", "F", "FY")
MAIN = "T"
PLACEBO_VERSIONS = ("T", "F")
VARIANTS = {                                    # descriptive only, on version T
    "V1_cap_at_plan_price": {"max_price": "plan"},
    "V3_cancel_tranches_at_tp1": {"cancel_on_tp1": True},
    "V4_trailing_from_first_fill": {"trail_from": "first_fill"},
    "V5_trailing_after_tp3": {"trail_from": "tp_3"},
    "V6_no_valuation_tiers": {"tp_temp": False},
    "V8_cooldown_20": {"cooldown": 20},
    "V11_no_reward_risk_gate": {"min_rr": None, "min_rr0": None},
    "V12_tranches_below_mid": {"tranche_below_mid": True},
    "stop_15pct": {"stop_pct": 0.15},
    "no_stop": {"no_stop": True},
    "exit_all_above_high": {"exit_all_at": "high"},
}
MIN_BAR_COVER = 0.90                            # a usable company's bars cover this share of its member weekdays
MIN_QUARTERS = 8


# ---------------------------------------------------------------- the companies
def weekdays(a: str, b: str) -> int:
    d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    n = (d1 - d0).days
    return n // 7 * 5 + sum((d0 + dt.timedelta(days=k)).weekday() < 5 for k in range(n % 7))


def usable(snap: Path, sym: str, spans: list, end: str) -> tuple[bool, str]:
    """The pre-registered replacement rule: bars covering 90% of the member weekdays in the window and at
    least 8 quarterly income statements."""
    raw = snap / "raw"
    bars = P.read(raw / "full" / f"{sym}.json")
    q = P.read(raw / "inc_q" / f"{sym}.json")
    if not bars:
        return False, "no bars"
    if len(q) < MIN_QUARTERS:
        return False, f"{len(q)} quarterly statements"
    days = sorted({str(r["date"])[:10] for r in bars})
    need = have = 0
    for a, b in spans:
        a, b = max(a, FIRST_DAY), min(b, end)
        if a >= b:
            continue
        need += weekdays(a, b)
        have += bisect.bisect_left(days, b) - bisect.bisect_left(days, a)
    if need and have / need < MIN_BAR_COVER:
        return False, f"bars cover {have / need:.0%} of member weekdays"
    return True, ""


def choose(snap: Path, sample: dict, end: str) -> tuple[list, list]:
    """The 50 companies after replacements, [(symbol, sector, spans)], and the replacements made: a drawn
    company without usable data gives way to the next usable spare of its sector, in the drawn order."""
    recs, out, swaps, used = sample["records"], [], [], set()
    for sym in sample["sample"]:
        r = recs[sym]
        ok, why = usable(snap, r["series"], r["spans"], end)
        if ok:
            out.append((r["series"], r["sector"], r["spans"]))
            continue
        for alt in sample["spares"][r["sector"]]:
            ra = recs[alt]
            if alt not in used and usable(snap, ra["series"], ra["spans"], end)[0]:
                used.add(alt)
                out.append((ra["series"], ra["sector"], ra["spans"]))
                swaps.append({"out": sym, "why": why, "in": alt})
                break
        else:
            swaps.append({"out": sym, "why": why, "in": None})
    return out, swaps


# ---------------------------------------------------------------- runs of one company
def adj_series(snap: Path, sym: str, dates: list) -> tuple[list, list]:
    """Dividend-adjusted open and close on the panel's dates (None where missing)."""
    rows = {str(r["date"])[:10]: r for r in P.read(snap / "raw" / "adj" / f"{sym}.json")}
    o = [P.fnum(rows[d].get("adjOpen")) if d in rows else None for d in dates]
    c = [P.fnum(rows[d].get("adjClose")) if d in rows else None for d in dates]
    return o, c


def tiers(exits: list) -> set:
    return {int(t) for e in exits if e.startswith("tp_") for t in e[3:].split("+")}


def plan_rows(p, out: dict, run: str, version: str, sector: str) -> list:
    rows = []
    items = [(pl, False) for pl in out["plans"]] + ([(out["open"], True)] if out["open"] else [])
    for pl, is_open in items:
        inv = pl.invested()
        mtm = out["open_value"] if is_open else 0.0
        end = out["last"] if is_open else pl.end
        first = pl.filled[0][0]
        tp = tiers([s[4] for s in pl.sold])
        rows.append({
            "symbol": p.symbol, "sector": sector, "run": run, "version": version,
            "start": p.dates[pl.start], "year": int(p.dates[pl.start][:4]), "first_fill": p.dates[first],
            "end": p.dates[end], "open_at_end": is_open, "status": "open" if is_open else pl.status,
            "P": pl.price, "atr_pct": pl.atr / pl.price, "stop0": pl.stop0, "t1": pl.t1, "t2": pl.t2,
            "t1_src": pl.t1_src, "rr": pl.rr, "pct0": pl.pct0,
            "below_mid": pl.price / pl.mid0 - 1 if pl.mid0 else None,
            "tranches": len(pl.filled), "filled_frac": inv / pl.size, "blocked": pl.blocked,
            "tp1": 1 in tp, "tp2": 2 in tp, "tp3": 3 in tp,
            "invested": inv, "proceeds": pl.proceeds(), "mtm": mtm, "ret": (pl.proceeds() + mtm - inv) / inv,
            "sessions": end - first + 1,
        })
    return rows


def master_series(dates: list, x: dict, cal: list, accr: list) -> list:
    """A sleeve's value on the master calendar, 1.0 on the first day: T-bill growth before the company's first
    bar and after its last one, the sleeve's own value in between (carried over a day without a bar)."""
    i0, i1, val = x["first"], x["last"], x["value"]
    if i0 > i1:
        return list(accr)
    d0, d1 = dates[i0], dates[i1]
    k0 = min(bisect.bisect_left(cal, d0), len(cal) - 1)
    scale = accr[k0]
    by_day = {dates[i]: val[i] for i in range(i0, i1 + 1) if val[i] is not None}
    out, last_k, last_v = [], None, None
    for k, d in enumerate(cal):
        v = by_day.get(d) if d0 <= d <= d1 else None
        if v is not None:
            last_k, last_v = k, scale * v
            out.append(last_v)
        elif last_v is None:
            out.append(accr[k])
        elif d > d1:
            out.append(last_v * accr[k] / accr[last_k])
        else:
            out.append(last_v)
    return out


def held_share(x: dict) -> float:
    """Share of the sleeve's value held in stock, averaged over its sessions."""
    if x.get("held") is None:
        return None
    vals = [h / v for h, v in zip(x["held"][x["first"]:x["last"] + 1], x["value"][x["first"]:x["last"] + 1]) if v]
    return sum(vals) / len(vals) if vals else 0.0


def buy_hold(p, adj_o: list, adj_c: list, rates) -> dict:
    """Fully invested (dividends reinvested) on member days: bought at the open of the first member day,
    sold at the open of the first day after; cash at the T-bill otherwise; a delisting sells at the last close."""
    n = len(p.dates)
    i0 = bisect.bisect_left(p.dates, FIRST_DAY)
    cash, units, cost, px = 1.0, 0.0, S.Rules().cost, None
    value, held = [None] * n, [None] * n
    for i in range(i0, n):
        if i > i0:
            days = (P.day(p.dates[i]) - P.day(p.dates[i - 1])).days
            cash *= 1.0 + rates(p.dates[i - 1]) * days / 365.0
        if adj_o[i]:
            if p.member[i] and units == 0 and i < n - 1:
                units, cash = cash / (adj_o[i] * (1 + cost)), 0.0
            elif not p.member[i] and units > 0:
                cash, units = cash + units * adj_o[i] * (1 - cost), 0.0
        px = adj_c[i] or px
        if units and i == n - 1 and p.delisted:
            cash, units = cash + units * px * (1 - cost), 0.0
        held[i] = units * px if units else 0.0
        value[i] = cash + held[i]
    return {"value": value, "held": held, "first": i0, "last": n - 1}


def mirror_spy(p, out: dict, spy: M.Spy, rates) -> dict:
    """The same cash flows in SPY: each tranche's cash buys SPY at that day's open, each sale sells the same
    fraction of the SPY holding (at the close for a delisting sale); the cash part is the method's own. It
    isolates what the stock added beyond being in the market at those times."""
    n = len(p.dates)
    events = {}
    for pl in out["plans"] + ([out["open"]] if out["open"] else []):
        for f in pl.filled:
            events.setdefault(f[0], []).append(("buy", f[3], f[2]))
        for s in pl.sold:
            events.setdefault(s[0], []).append(("sell", s[2], s[4]))
    cost = S.Rules().cost
    i0 = out["first"]
    cash, units, shares = 1.0, 0.0, 0.0
    value = [None] * n
    for i in range(i0, out["last"] + 1):
        d = p.dates[i]
        if i > i0:
            days = (P.day(d) - P.day(p.dates[i - 1])).days
            cash *= 1.0 + rates(p.dates[i - 1]) * days / 365.0
        for e in sorted(events.get(i, []), key=lambda e: e[0] != "sell"):
            if e[0] == "buy":
                amt = min(e[1], cash)
                units += amt / (spy.open_on(d) * (1 + cost))
                cash -= amt
                shares += e[2]
            elif shares > 0:
                frac = min(1.0, e[1] / shares)
                px = spy.close_on(d) if e[2] == "delisted" else spy.open_on(d)
                cash += units * frac * px * (1 - cost)
                units *= 1.0 - frac
                shares -= e[1]
                if shares <= 1e-12:
                    shares, units = 0.0, 0.0
        value[i] = cash + units * spy.close_on(d)
    return {"value": value, "held": None, "first": i0, "last": out["last"]}


def compact(out: dict, dates: list, cal: list, accr: list, marks: list) -> dict:
    """A run reduced to what the portfolio needs: the master series (daily), the held share, the counts."""
    series = master_series(dates, out, cal, accr)
    return {"series": series, "monthly": [series[k] for k in marks], "held_share": held_share(out),
            "plans": len(out.get("plans", [])) + (1 if out.get("open") else 0), "waits": out.get("waits"),
            "expired": out.get("expired"), "lapsed": out.get("lapsed")}


def company_runs(args) -> dict:
    """Every run of one company: the method on each version (with its placebo replicas and its SPY mirror),
    the variants on T, buy-and-hold, and the panel's report. Executed in a worker process."""
    snap, sym, sector, spans, spinoffs, versions, variants, replicas, cal, accr = args
    marks = ST.month_ends(cal)
    rates, spy = M.load(snap)
    p = P.build(sym, snap, spans, versions=versions, spinoffs=spinoffs.get(sym, []))
    res = {"symbol": sym, "sector": sector, "runs": {}, "plans": [], "placebo": {}, "eligible": {},
           "report": report_of(p)}
    for v in versions:
        r = S.Rules(version=v)
        out = S.run(p, r, rates, first_day=FIRST_DAY)
        res["runs"][f"method_{v}"] = compact(out, p.dates, cal, accr, marks)
        res["plans"] += plan_rows(p, out, f"method_{v}", v, sector)
        res["runs"][f"spy_matched_{v}"] = compact(mirror_spy(p, out, spy, rates), p.dates, cal, accr, marks)
        res["eligible"][v] = PL.eligible_days(p, out, r)
        if v in PLACEBO_VERSIONS and replicas:
            cands = PL.candidates(p, r, out["first"], out["last"])
            target = PL.n_plans(out)
            h = PL.calibrate(p, r, rates, target, cands, FIRST_DAY)
            reps = []
            for k in range(replicas):
                o = PL.replica(p, r, rates, h, k, cands, first_day=FIRST_DAY)
                c = compact(o, p.dates, cal, accr, marks)
                rows = plan_rows(p, o, "placebo", v, sector)
                reps.append({"monthly": c["monthly"], "held_share": c["held_share"], "plans": c["plans"],
                             "rets": [x["ret"] for x in rows], "years": [x["year"] for x in rows]})
            res["placebo"][v] = {"h": h, "candidates": len(cands), "target": target, "reps": reps}
    for name, kw in variants.items():
        out = S.run(p, replace(S.Rules(version=MAIN), **kw), rates, first_day=FIRST_DAY)
        res["runs"][name] = compact(out, p.dates, cal, accr, marks)
        res["plans"] += plan_rows(p, out, name, MAIN, sector)
    adj_o, adj_c = adj_series(snap, sym, p.dates)
    res["runs"]["buy_hold_member"] = compact(buy_hold(p, adj_o, adj_c, rates), p.dates, cal, accr, marks)
    return res


def report_of(p) -> dict:
    """The panel's data report: statement basis decisions, spin-off candidates, why member days lack a range."""
    rep = {k: v for k, v in p.report.items() if k != "clean"}
    rep["jumps"] = p.report["clean"]["jumps"]
    rep["bars_removed"] = p.report["clean"]["placeholders_removed"]
    why = {}
    for v, w in p.why.items():
        c = {}
        for i, x in enumerate(w):
            if p.dates[i] >= FIRST_DAY and p.member[i]:
                c[x or "ok"] = c.get(x or "ok", 0) + 1
        why[v] = c
    rep["member_days_by_reason"] = why
    rep["delisted"] = p.delisted
    rep["first_bar"], rep["last_bar"] = (p.dates[0], p.dates[-1]) if p.dates else (None, None)
    return json.loads(json.dumps(rep, default=str))


# ---------------------------------------------------------------- the portfolio
def accrual(cal: list, rates) -> list:
    a = [1.0]
    for k in range(1, len(cal)):
        days = (P.day(cal[k]) - P.day(cal[k - 1])).days
        a.append(a[-1] * (1.0 + rates(cal[k - 1]) * days / 365.0))
    return a


def average(rows: list) -> list:
    return [sum(x[k] for x in rows) / len(rows) for k in range(len(rows[0]))]


def placebo_portfolios(results: list, v: str, cal: list, accr: list) -> list:
    """Per replica: the equal-weight portfolio's monthly statistics and the pooled per-plan mean return."""
    marks = ST.month_ends(cal)
    mcal, macc = [cal[k] for k in marks], [accr[k] for k in marks]
    have = [r for r in results if v in r["placebo"]]
    if not have:
        return []
    n = len(have[0]["placebo"][v]["reps"])
    out = []
    for k in range(n):
        reps = [r["placebo"][v]["reps"][k] for r in have]
        s = ST.series_stats(mcal, average([x["monthly"] for x in reps]), macc)
        rets = [x for rep in reps for x in rep["rets"]]
        out.append({"cagr": s["cagr"], "max_dd": s["max_dd"], "plans": sum(x["plans"] for x in reps),
                    "plan_mean": sum(rets) / len(rets) if rets else None,
                    "held_share": sum(x["held_share"] for x in reps) / len(reps),
                    "rets": rets, "years": [y for rep in reps for y in rep["years"]]})
    return out


def compare(results: list, plans: list, cal: list, accr: list, versions, spy_monthly: list) -> dict:
    """The method against its placebo (rank among the replicas; per-plan difference with a calendar-year block
    interval), and against buy-and-hold and SPY (yearly excess with a block interval)."""
    marks = ST.month_ends(cal)
    mcal, macc = [cal[k] for k in marks], [accr[k] for k in marks]
    out = {}
    for v in versions:
        run = f"method_{v}"
        mine = [x for x in plans if x["run"] == run]
        m_month = average([r["runs"][run]["monthly"] for r in results])
        ms = ST.series_stats(mcal, m_month, macc)
        o = {"plans": len(mine), "plan_mean": ST.mean_by_blocks([x["ret"] for x in mine], [x["year"] for x in mine],
                                                                f"{run}|plans")}
        reps = placebo_portfolios(results, v, cal, accr)
        if reps:
            o["placebo"] = {
                "replicas": len(reps),
                "cagr": ST.rank_against(ms["cagr"], [x["cagr"] for x in reps]),
                "max_dd": ST.rank_against(ms["max_dd"], [x["max_dd"] for x in reps]),
                "plan_mean": ST.rank_against(o["plan_mean"]["theta"], [x["plan_mean"] for x in reps]),
                "plans": {"method": len(mine), "placebo_mean": sum(x["plans"] for x in reps) / len(reps)},
                "held_share": {"method": sum(r["runs"][run]["held_share"] for r in results) / len(results),
                               "placebo_mean": sum(x["held_share"] for x in reps) / len(reps)},
            }
            pool_r = [x for rep in reps for x in rep["rets"]]
            pool_y = [y for rep in reps for y in rep["years"]]
            o["plan_vs_placebo"] = ST.diff_by_blocks([x["ret"] for x in mine], [x["year"] for x in mine],
                                                     pool_r, pool_y, f"{run}|vs_placebo")
        for bench in ("buy_hold_member", f"spy_matched_{v}", "spy"):
            b = spy_monthly if bench == "spy" else average([r["runs"][bench]["monthly"] for r in results])
            o[f"vs_{bench}"] = ST.yearly_excess(mcal, m_month, b)
        out[v] = o
    return out


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snap", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--replicas", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--quick", action="store_true", help="T only, no variants, 20 replicas (a smoke test)")
    ap.add_argument("--sample", default=str(HERE / "sample.json"), help="the drawn sample (tests use their own)")
    ap.add_argument("--spinoffs", default=str(HERE / "spinoffs.json"))
    a = ap.parse_args(argv)
    snap, out = Path(a.snap), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    bad = M.check_manifest(snap)
    if bad:
        print(f"snapshot refused: {len(bad)} files differ from the manifest, e.g. {bad[:3]}")
        return 2
    man = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    sample = json.loads(Path(a.sample).read_text(encoding="utf-8"))
    spin = json.loads(Path(a.spinoffs).read_text(encoding="utf-8"))
    spinoffs = {k: [x["date"] for x in v if x.get("confirmed")] for k, v in spin["events"].items()}
    rates, spy = M.load(snap)
    cal = [d for d in spy.days if d >= FIRST_DAY]
    accr = accrual(cal, rates)
    comps, swaps = choose(snap, sample, cal[-1])
    versions = (MAIN,) if a.quick else VERSIONS
    variants = {} if a.quick else VARIANTS
    reps = 20 if a.quick else a.replicas
    jobs = [(snap, s, sec, spans, spinoffs, versions, variants, reps, cal, accr) for s, sec, spans in comps]
    with Pool(a.workers) as pool:
        results = pool.map(company_runs, jobs)
    marks = ST.month_ends(cal)
    spy_plain = [spy.close_on(d) / spy.close_on(cal[0]) for d in cal]
    runs = list(results[0]["runs"])
    port = {run: average([r["runs"][run]["series"] for r in results]) for run in runs}
    port["spy"] = spy_plain
    summary = {run: ST.series_stats(cal, s, accr) for run, s in port.items()}
    for run in runs:
        hs = [r["runs"][run]["held_share"] for r in results if r["runs"][run]["held_share"] is not None]
        summary[run]["held_share"] = sum(hs) / len(hs) if hs else None
        summary[run]["plans"] = sum(r["runs"][run]["plans"] for r in results)
    plans = [row for r in results for row in r["plans"]]
    res = {"created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "snapshot": {"created": man.get("created"), "last_day": cal[-1], "files": len(man["files"])},
           "companies": [{"symbol": c[0], "sector": c[1]} for c in comps], "replacements": swaps,
           "first_day": FIRST_DAY, "rules": asdict(S.Rules()), "variants": variants, "summary": summary,
           "compare": compare(results, plans, cal, accr, versions, [spy_plain[k] for k in marks]),
           "placebo_calibration": {r["symbol"]: {v: {k: x for k, x in pl.items() if k != "reps"}
                                                 for v, pl in r["placebo"].items()} for r in results},
           "reports": {r["symbol"]: r["report"] for r in results},
           "eligible_days": {r["symbol"]: r["eligible"] for r in results}}
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    with (out / "plans.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(plans[0]) if plans else ["symbol"])
        w.writeheader()
        w.writerows(plans)
    (out / "portfolio.json").write_text(json.dumps({"dates": cal, "series": port}), encoding="utf-8")
    print(f"{len(comps)} companies ({len(swaps)} replaced), {len(plans)} plan rows; results in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
