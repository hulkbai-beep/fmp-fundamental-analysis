#!/usr/bin/env python3
"""
Run the forward-P/E band pilot on a frozen snapshot: the user's buy method on the 50 drawn companies with EPS
version T (the main result) and F / FY (look-ahead EPS: descriptive, not evidence), the descriptive variants,
buy-and-hold of the same companies and SPY. The primary test: the method's plans against plans started on
random eligible days of the same companies, each plan's P&L hedged daily with SPY over the 252 sessions after
its signal (stats.plan_test, from the every-start table of placebo.pool); the rules-free signal test beside it.
Writes results.json, plans.csv and portfolio.json to --out (report.py turns them into the report).

    python backtest/pilot/run_pilot.py --snap DIR --out DIR [--plan-replicas 1000] [--replicas 200]
                                       [--workers 4] [--quick]

All computing happens here; the snapshot is refused when a file differs from its manifest.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import json
import math
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
import status as SU  # noqa: E402

FIRST_DAY = "2008-01-02"
VERSIONS = ("T", "F", "FY")
MAIN = "T"
PLACEBO_VERSIONS = ("T", "F")
SIGNAL_EVERY = 21                               # the rules-free signal test samples every 21st session
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
# ---------------------------------------------------------------- the companies
def choose(snap: Path, sample: dict) -> tuple[list, dict]:
    """The companies after the pre-registered replacement walk (status.py), [(key, series, sector, spans)], and
    the walk's record. The walk is rerun here on the snapshot and must reach the decisions fetch.py recorded on
    the PC (status.json); a snapshot without status.json (the tests) is walked up to SPY's last session."""
    pc_path = snap / "status.json"
    pc = json.loads(pc_path.read_text(encoding="utf-8")) if pc_path.exists() else None
    z = pc["z"] if pc else SU.sessions(snap, "9999-12-31")[-1]
    st = SU.walk(sample, snap, SU.sessions(snap, z), z)
    st["z"] = z
    if pc:
        keys = ("companies", "replacements", "review")
        mine, theirs = ({k: x[k] for k in keys} for x in (st, pc))
        st["same_as_pc"] = json.dumps(mine, sort_keys=True) == json.dumps(theirs, sort_keys=True)
    return [tuple(c) for c in st["companies"]], st


# ---------------------------------------------------------------- runs of one company
def adj_series(snap: Path, sym: str, dates: list) -> tuple[list, list]:
    """Dividend-adjusted open and close on the panel's dates (None where missing)."""
    rows = {str(r["date"])[:10]: r for r in P.read(snap / "raw" / "adj" / f"{sym}.json")}
    o = [P.fnum(rows[d].get("adjOpen")) if d in rows else None for d in dates]
    c = [P.fnum(rows[d].get("adjClose")) if d in rows else None for d in dates]
    return o, c


def tiers(exits: list) -> set:
    return {int(t) for e in exits if e.startswith("tp_") for t in e[3:].split("+")}


def plan_rows(p, out: dict, run: str, version: str, sector: str, key: str | None = None) -> list:
    rows = []
    items = [(pl, False) for pl in out["plans"]] + ([(out["open"], True)] if out["open"] else [])
    for pl, is_open in items:
        inv = pl.invested()
        mtm = out["open_value"] if is_open else 0.0
        end = out["last"] if is_open else pl.end
        first = pl.filled[0][0]
        tp = tiers([s[4] for s in pl.sold])
        rows.append({
            "symbol": key or p.symbol, "sector": sector, "run": run, "version": version,
            "start": p.dates[pl.start], "year": int(p.dates[pl.start][:4]), "first_fill": p.dates[first],
            "end": p.dates[end], "open_at_end": is_open, "status": "open" if is_open else pl.status,
            "P": pl.price, "atr_pct": pl.atr / pl.price, "stop0": pl.stop0, "t1": pl.t1, "t2": pl.t2,
            "t1_src": pl.t1_src, "rr": pl.rr, "pct0": pl.pct0,
            "below_mid": pl.price / pl.mid0 - 1 if pl.mid0 else None,
            "tranches": len(pl.filled), "filled_frac": inv / pl.size, "blocked": pl.blocked,
            "tp1": 1 in tp, "tp2": 2 in tp, "tp3": 3 in tp,
            "invested": inv, "proceeds": pl.proceeds(), "mtm": mtm, "ret": (pl.proceeds() + mtm - inv) / inv,
            "sessions": end - first + 1, "full252": p.delisted or pl.start + S.H_LONG <= out["last"],
            **{k: x for k, x in pl.metrics().items()},
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


def hedge_of(p, spy: M.Spy) -> tuple[list, list]:
    """SPY's adjusted open and close on the company's bar dates (the hedge leg of the primary metric)."""
    return [spy.open_on(d) for d in p.dates], [spy.close_on(d) for d in p.dates]


def every_start_check(strat: dict, pool: dict) -> dict:
    """Each of the method's plans must be in the every-start table with the same outcome (a plan's course does
    not depend on the sleeve around it)."""
    at = {s: k for k, s in enumerate(pool["start"])}
    missing, worst = [], 0.0
    for k, s in enumerate(strat["start"]):
        j = at.get(s)
        if j is None:
            missing.append(strat["day"][k])
            continue
        if strat["status"][k] != pool["status"][j]:
            missing.append(strat["day"][k] + " status")
        for m in ("dh252", "dh126", "raw252"):
            worst = max(worst, abs(strat[m][k] - pool[m][j]))
    return {"plans": len(strat["start"]), "missing": missing[:10], "n_missing": len(missing), "max_diff": worst}


def signal_rows(p, v: str, cands: list, adj_c: list, spy: M.Spy, sample: set, last: int) -> list:
    """The rules-free signal test's days: sampled gate-passing member days with the forward return of the
    stock (dividends included) minus SPY's over 63 / 126 / 252 sessions (to the last close when delisted)."""
    out = []
    for i in cands:
        d = p.dates[i]
        if d not in sample or not adj_c[i]:
            continue
        low, mid, high, pct = p.range_at(v, i)
        fwd = {}
        for h in (63, 126, 252):
            j = i + h if i + h <= last else (last if p.delisted else None)
            if j is None or not adj_c[j]:
                fwd[h] = None
                continue
            fwd[h] = adj_c[j] / adj_c[i] - spy.close_on(p.dates[j]) / spy.close_on(d)
        out.append((int(d[:4]), p.c[i] < mid, -math.log(p.c[i] / mid), fwd))
    return out


def company_runs(args) -> dict:
    """Every run of one company: the method on each version (its plans with the hedged metric, the every-start
    table of the placebo, the sleeve-level placebo replicas and the SPY mirror), the variants on T,
    buy-and-hold, the rules-free signal days and the panel's report. Executed in a worker process."""
    snap, key, series, sector, spans, spin_days, versions, variants, replicas, cal, accr = args
    marks = ST.month_ends(cal)
    rates, spy = M.load(snap)
    p = P.build(series, snap, spans, versions=versions, spinoffs=spin_days)
    hedge = hedge_of(p, spy)
    adj_o, adj_c = adj_series(snap, series, p.dates)
    sample = set(cal[::SIGNAL_EVERY])
    res = {"symbol": key, "series": series, "sector": sector, "runs": {}, "plans": [], "placebo": {},
           "eligible": {}, "strategy": {}, "pool": {}, "every_start": {}, "signal": {}, "report": report_of(p)}
    for v in versions:
        r = S.Rules(version=v)
        out = S.run(p, r, rates, first_day=FIRST_DAY, hedge=hedge)
        res["runs"][f"method_{v}"] = compact(out, p.dates, cal, accr, marks)
        res["plans"] += plan_rows(p, out, f"method_{v}", v, sector, key)
        res["runs"][f"spy_matched_{v}"] = compact(mirror_spy(p, out, spy, rates), p.dates, cal, accr, marks)
        res["eligible"][v] = PL.eligible_days(p, out, r)
        res["strategy"][v] = PL.columns(p, PL.method_plans(out), out["last"])
        if v in PLACEBO_VERSIONS:
            res["pool"][v] = PL.pool(p, r, rates, hedge, out["first"], out["last"])
            res["every_start"][v] = every_start_check(res["strategy"][v], res["pool"][v])
            if v == MAIN:
                res["signal"][v] = signal_rows(p, v, res["pool"][v]["start"], adj_c, spy, sample, out["last"])
        if v in PLACEBO_VERSIONS and replicas:
            cands = PL.candidates(p, r, out["first"], out["last"])
            target = PL.n_plans(out)
            h = PL.calibrate(p, r, rates, target, cands, FIRST_DAY)
            reps = []
            for k in range(replicas):
                o = PL.replica(p, r, rates, h, k, cands, first_day=FIRST_DAY)
                c = compact(o, p.dates, cal, accr, marks)
                reps.append({"monthly": c["monthly"], "held_share": c["held_share"], "plans": c["plans"]})
            res["placebo"][v] = {"h": h, "candidates": len(cands), "target": target, "reps": reps}
    for name, kw in variants.items():
        out = S.run(p, replace(S.Rules(version=MAIN), **kw), rates, first_day=FIRST_DAY, hedge=hedge)
        res["runs"][name] = compact(out, p.dates, cal, accr, marks)
        res["plans"] += plan_rows(p, out, name, MAIN, sector, key)
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
    """Per replica of the sleeve-level placebo: the equal-weight portfolio's monthly statistics."""
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
        out.append({"cagr": s["cagr"], "max_dd": s["max_dd"], "sharpe": s["sharpe"],
                    "plans": sum(x["plans"] for x in reps),
                    "held_share": sum(x["held_share"] for x in reps) / len(reps)})
    return out


def compare(results: list, plans: list, cal: list, accr: list, versions, spy_monthly: list) -> dict:
    """Descriptive: the method's per-plan return with a calendar-year block interval, its portfolio's rank
    among the sleeve-level placebo replicas, and its yearly excess over buy-and-hold, the SPY mirror and SPY."""
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
                "sharpe": ST.rank_against(ms["sharpe"], [x["sharpe"] for x in reps]),
                "max_dd": ST.rank_against(ms["max_dd"], [x["max_dd"] for x in reps]),
                "plans": {"method": len(mine), "placebo_mean": sum(x["plans"] for x in reps) / len(reps)},
                "held_share": {"method": sum(r["runs"][run]["held_share"] for r in results) / len(results),
                               "placebo_mean": sum(x["held_share"] for x in reps) / len(reps)},
            }
        for bench in ("buy_hold_member", f"spy_matched_{v}", "spy"):
            b = spy_monthly if bench == "spy" else average([r["runs"][bench]["monthly"] for r in results])
            o[f"vs_{bench}"] = ST.yearly_excess(mcal, m_month, b)
        out[v] = o
    return out


def primary(results: list, reps: int) -> dict:
    """The plan-level test per version (T is the main result, F is look-ahead), on the hedged metric over 252
    sessions, with the 126-session and the unhedged versions beside it (descriptive)."""
    out = {}
    for v in PLACEBO_VERSIONS:
        have = [r for r in results if v in r["pool"]]
        if not have:
            continue
        strat = {r["symbol"]: r["strategy"][v] for r in have}
        pool = {r["symbol"]: r["pool"][v] for r in have}
        out[v] = {"dh252": ST.plan_test(strat, pool, "dh252", "full252", reps, v),
                  "dh126": ST.plan_test(strat, pool, "dh126", "full126", reps, v),
                  "raw252": ST.plan_test(strat, pool, "raw252", "full252", reps, v),
                  "every_start": {r["symbol"]: r["every_start"][v] for r in have}}
    return out


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snap", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan-replicas", type=int, default=ST.PLAN_REPS, help="the primary test's placebo")
    ap.add_argument("--replicas", type=int, default=200, help="the sleeve-level placebo (descriptive)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--quick", action="store_true", help="T only, no variants, 20 sleeve and 200 plan replicas "
                                                         "(a smoke test)")
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
    comps, walk = choose(snap, sample)
    if walk.get("same_as_pc") is False:
        print("snapshot refused: the replacement walk here differs from the PC's (status.json)")
        return 2
    swaps = walk["replacements"]
    rates, spy = M.load(snap)
    cal = [d for d in spy.days if FIRST_DAY <= d <= walk["z"]]
    accr = accrual(cal, rates)
    versions = (MAIN,) if a.quick else VERSIONS
    variants = {} if a.quick else VARIANTS
    reps = 20 if a.quick else a.replicas
    plan_reps = 200 if a.quick else a.plan_replicas
    jobs = [(snap, key, series, sec, spans, spinoffs.get(key, []), versions, variants, reps, cal, accr)
            for key, series, sec, spans in comps]
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
           "companies": [{"symbol": c[0], "series": c[1], "sector": c[2]} for c in comps], "replacements": swaps,
           "walk": {k: walk.get(k) for k in ("z", "same_as_pc", "review", "assessed")},
           "first_day": FIRST_DAY, "rules": asdict(S.Rules()), "variants": variants,
           "primary": primary(results, plan_reps),
           "signal": {MAIN: ST.signal_test([x for r in results for x in r["signal"].get(MAIN, [])], MAIN)},
           "summary": summary,
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
    print(f"{len(comps)} companies ({sum(1 for x in swaps if x['in'])} replaced), {len(plans)} plan rows; "
          f"results in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
