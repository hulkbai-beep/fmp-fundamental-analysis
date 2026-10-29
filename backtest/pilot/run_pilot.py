#!/usr/bin/env python3
"""
Run the forward-P/E band pilot on a frozen snapshot: the user's buy method on the 50 drawn companies with EPS
version T (the main result) and F (look-ahead EPS: read one way only), the four variants of SPEC v1 section 7,
buy-and-hold of the same companies and SPY. The primary test: the method's plans against plans started on
random eligible days of the same companies, each plan's P&L hedged daily with SPY over the 252 SPY sessions
after its signal (stats.plan_test, from the every-start table of placebo.pool); the rules-free signal test
beside it; each variant's theta against its own table (descriptive). Writes results.json, plans.csv,
portfolio.json, pools_T.json, pools_F.json and status.json to --out (report.py turns them into the report),
after removing the ones an earlier run left there and its repro.json.

    python backtest/pilot/run_pilot.py --snap DIR --out DIR [--plan-replicas 1000] [--workers 4] [--quick]

All computing happens here; the snapshot is refused when a file differs from its manifest, and the run when its
inputs (the snapshot's manifest, the sample, the confirmed spin-offs, the code) change before it ends.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import hashlib
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
VERSIONS = ("T", "F")
MAIN = "T"
SIGNAL_EVERY = 21                               # the rules-free signal test samples every 21st SPY session
VARIANTS = {                                    # SPEC v1 section 7: version T, descriptive only
    "stop_15pct": {"stop_pct": 0.15},                       # V-a
    "exit_all_above_high": {"exit_all_at": "high"},         # V-b
    "V8_cooldown_20": {"cooldown": 20},                     # V-c
    "V12_tranches_below_mid": {"tranche_below_mid": True},  # V-d
}
SLEEVE_ONLY = ("cooldown", "cooldown_after")    # rules a plan simulated alone never meets: the main table serves
AT_CLOSE = ("delisted", "spin")                 # sales at the close of their bar (SPEC R10)
OUTPUTS = ("results.json", "plans.csv", "portfolio.json", "status.json")     # with pools_<version>.json
CODE = [HERE / f for f in ("market.py", "panel.py", "placebo.py", "run_pilot.py", "sim.py", "stats.py",
                           "status.py")] + [HERE.parent.parent / "scripts" / "analyze.py"]   # what results come from


def md5_of(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def inputs(snap: Path, sample: Path, spinoffs: Path) -> dict:
    """What a run or a set of checks was made from: the snapshot (its manifest), the drawn sample, the confirmed
    spin-offs and the code results come from, taken when it starts and again before it writes (a change in
    between refuses it). report.py takes checks only for results with the same inputs."""
    events = json.loads(spinoffs.read_text(encoding="utf-8"))["events"]
    return {"manifest": md5_of(snap / "manifest.json"), "sample": md5_of(sample),
            "spinoffs": {k: sorted(x["date"] for x in v if x.get("confirmed")) for k, v in sorted(events.items())},
            "code": {f.name: md5_of(f) for f in CODE}}
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


def plan_rows(p, out: dict, run: str, version: str, sector: str, key: str, sess: list, zi: int) -> list:
    """One row per plan the run started: closed, open at the end, or void (it never bought: lapsed at the
    chase limit, expired, cancelled below its stop or before a spin-off, or still waiting at the end)."""
    rows = []
    items = [(pl, False) for pl in out["plans"]] + ([(out["open"], True)] if out["open"] else []) + \
        [(pl, False) for pl in out["voids"]]
    for pl, is_open in items:
        inv = pl.invested()
        mtm = out["open_value"] if is_open else 0.0
        end = out["last"] if is_open else pl.end
        first = pl.filled[0][0] if pl.filled else None
        bought = sum(f[2] for f in pl.filled)
        tp = tiers([s[4] for s in pl.sold])
        rows.append({
            "symbol": key, "sector": sector, "run": run, "version": version,
            "start": p.dates[pl.start], "year": int(p.dates[pl.start][:4]),
            "first_fill": p.dates[first] if first is not None else None,
            "end": p.dates[end], "open_at_end": is_open, "status": "open" if is_open else pl.status,
            "P": pl.price, "atr_pct": pl.atr / pl.price, "stop0": pl.stop0, "t1": pl.t1, "t2": pl.t2,
            "t1_src": pl.t1_src, "rr": pl.rr, "pct0": pl.pct0, "temp0": pl.temp0,
            "below_mid": pl.price / pl.mid0 - 1 if pl.mid0 else None,
            "tranches": len(pl.filled), "filled_frac": inv / pl.size, "blocked": pl.blocked,
            "avg_vs_P": inv / bought / pl.price - 1 if bought else None,
            "days_to_fill": first - pl.start if first is not None else None,
            "tp1": 1 in tp, "tp2": 2 in tp, "tp3": 3 in tp,
            "invested": inv, "proceeds": pl.proceeds(), "mtm": mtm,
            "ret": (pl.proceeds() + mtm - inv) / inv if inv else None,
            "sessions": end - first + 1 if first is not None else 0,
            "full252": sess[pl.start] + S.H_LONG <= zi,
            **pl.metrics(),
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
    fraction of the SPY holding (at the close for a delisting or spin-off sale, after that day's open trades);
    the cash part is the method's own. It isolates what the stock added beyond being in the market then."""
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
        for e in sorted(events.get(i, []), key=lambda e: 1 if e[0] == "buy" else 2 if e[2] in AT_CLOSE else 0):
            if e[0] == "buy":
                amt = min(e[1], cash)
                units += amt / (spy.open_on(d) * (1 + cost))
                cash -= amt
                shares += e[2]
            elif shares > 0:
                frac = min(1.0, e[1] / shares)
                px = spy.close_on(d) if e[2] in AT_CLOSE else spy.open_on(d)
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


def hedge_of(p, spy: M.Spy) -> tuple[list, list, list]:
    """SPY's adjusted open and close on the company's bar dates (the hedge leg of the primary metric) and the
    SPY session number of each bar (the calendar its window counts)."""
    return [spy.open_on(d) for d in p.dates], [spy.close_on(d) for d in p.dates], PL.sessions(p.dates, spy.days)


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


def signal_rows(p, v: str, pool: dict, adj_c: list, spy: M.Spy, sess: list, zi: int, sample: set,
                key: str = "") -> list:
    """The rules-free signal test's days (SPEC 5.3): every SIGNAL_EVERY-th SPY session from FIRST_DAY that is
    one of the company's pool days with a full window, with the stock's return (dividends included) minus
    SPY's to the 63rd / 126th / 252nd SPY session after it; when the company's bars stop earlier, to its last
    bar and SPY on that bar's date. Rows (year, below the mid, signal, {h: return}, company)."""
    out = []
    for i, full in zip(pool["start"], pool["full252"]):
        d = p.dates[i]
        if not full or d not in sample or not adj_c[i]:
            continue
        low, mid, high, pct = p.range_at(v, i)
        fwd = {}
        for h in (63, 126, 252):
            k = sess[i] + h
            j = bisect.bisect_right(p.dates, spy.days[k]) - 1 if k <= zi else None
            ok = j is not None and j > i and adj_c[j]
            fwd[h] = adj_c[j] / adj_c[i] - spy.close_on(p.dates[j]) / spy.close_on(d) if ok else None
        out.append((int(d[:4]), p.c[i] < mid, -math.log(p.c[i] / mid), fwd, key))
    return out


def gate_days(p, r: S.Rules, first: int, last: int) -> dict:
    """Days a plan could start on (as placebo.candidates, before the gates) with the close below the mid, by
    what the gates said: how many the 15% stop distance and the reward/risk gate block (SPEC 5.4)."""
    out = {"below_mid": 0, "pass": 0, "stop_too_far": 0, "reward_risk": 0}
    for i in range(first, last):
        rng = p.range_at(r.version, i)
        if not (rng and p.atr[i] and p.can_start(r.version, i)) or not p.c[i] < rng[1]:
            continue
        c, A = p.c[i], p.atr[i]
        t1, _, _ = S.targets(c, A, rng[1], rng[2], r)
        out["below_mid"] += 1
        out[S.gates(c, S.initial_stop(c, A, r, gate=True), t1, r)[1] or "pass"] += 1
    return out


def t_vs_f(p, first: int, last: int, sample: set) -> dict:
    """Versions T and F on the member days where both have a range: how often they agree on 'below the mid',
    and both percentiles on the sampled days (for their rank correlation)."""
    days, agree, pairs = 0, 0, []
    for i in range(first, last + 1):
        a, b = p.range_at("T", i), p.range_at("F", i)
        if not p.member[i] or a is None or b is None:
            continue
        days += 1
        agree += (p.c[i] < a[1]) == (p.c[i] < b[1])
        if p.dates[i] in sample:
            pairs.append((a[3], b[3]))
    return {"days": days, "agree": agree, "pairs": pairs}


def own_pool(kw: dict) -> bool:
    """Whether a variant needs its own every-start table: it changes how a plan runs, not only when one may
    start."""
    return any(k not in SLEEVE_ONLY for k in kw)


def company_runs(args) -> dict:
    """Every run of one company: the method on each version (its plans with the hedged metric, the every-start
    table of the placebo and the SPY mirror), the variants on T (each with its own table where its rules
    change how a plan runs), buy-and-hold, the rules-free signal days, the gate counts, T against F and the
    panel's report. Executed in a worker process."""
    snap, key, series, sector, spans, spin_days, versions, variants, cal, accr = args
    marks = ST.month_ends(cal)
    rates, spy = M.load(snap)
    z = cal[-1]
    zi = bisect.bisect_right(spy.days, z) - 1
    p = P.build(series, snap, spans, versions=versions, snapshot_end=z, spinoffs=spin_days)
    hedge = hedge_of(p, spy)
    sess = hedge[2]
    adj_o, adj_c = adj_series(snap, series, p.dates)
    sample = set(cal[::SIGNAL_EVERY])
    res = {"symbol": key, "series": series, "sector": sector, "runs": {}, "plans": [], "strategy": {}, "pool": {},
           "every_start": {}, "signal": {}, "gates": {}, "t_vs_f": None, "report": report_of(p)}
    for v in versions:
        r = S.Rules(version=v)
        out = S.run(p, r, rates, first_day=FIRST_DAY, hedge=hedge)
        res["runs"][f"method_{v}"] = compact(out, p.dates, cal, accr, marks)
        res["plans"] += plan_rows(p, out, f"method_{v}", v, sector, key, sess, zi)
        res["runs"][f"spy_matched_{v}"] = compact(mirror_spy(p, out, spy, rates), p.dates, cal, accr, marks)
        res["strategy"][v] = PL.columns(p, PL.method_plans(out), sess, zi)
        res["pool"][v] = PL.pool(p, r, rates, hedge, out["first"], out["last"], zi)
        res["every_start"][v] = every_start_check(res["strategy"][v], res["pool"][v])
        res["gates"][v] = gate_days(p, r, out["first"], out["last"])
        if v == MAIN:
            res["signal"][v] = signal_rows(p, v, res["pool"][v], adj_c, spy, sess, zi, sample, key)
    if "T" in versions and "F" in versions:
        res["t_vs_f"] = t_vs_f(p, out["first"], out["last"], sample)
    for name, kw in variants.items():
        r = replace(S.Rules(version=MAIN), **kw)
        out = S.run(p, r, rates, first_day=FIRST_DAY, hedge=hedge)
        res["runs"][name] = compact(out, p.dates, cal, accr, marks)
        res["plans"] += plan_rows(p, out, name, MAIN, sector, key, sess, zi)
        res["strategy"][name] = PL.columns(p, PL.method_plans(out), sess, zi)
        if own_pool(kw):
            res["pool"][name] = PL.pool(p, r, rates, hedge, out["first"], out["last"], zi)
        res["every_start"][name] = every_start_check(res["strategy"][name], res["pool"].get(name, res["pool"][MAIN]))
    res["runs"]["buy_hold_member"] = compact(buy_hold(p, adj_o, adj_c, rates), p.dates, cal, accr, marks)
    return res


def report_of(p) -> dict:
    """The panel's data report: statement basis decisions, spin-off candidates, suspicious bars, why member days
    lack a range."""
    rep = {k: v for k, v in p.report.items() if k != "clean"}
    rep["jumps"] = p.report["clean"]["jumps"]
    rep["bars_removed"] = p.report["clean"]["placeholders_removed"]
    rep["suspicious_bars"] = sum(p.suspicious)
    rep["suspicious_member_days"] = sum(1 for i, d in enumerate(p.dates)
                                        if d >= FIRST_DAY and p.member[i] and p.suspicious[i])
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


def compare(results: list, plans: list, cal: list, versions, spy_monthly: list) -> dict:
    """Descriptive: the method's per-plan return on the money it invested (plans that bought) with a
    calendar-year block interval, and its portfolio's yearly excess over buy-and-hold, the SPY mirror and SPY."""
    marks = ST.month_ends(cal)
    mcal = [cal[k] for k in marks]
    out = {}
    for v in versions:
        run = f"method_{v}"
        mine = [x for x in plans if x["run"] == run and x["ret"] is not None]
        m_month = average([r["runs"][run]["monthly"] for r in results])
        o = {"plans": len(mine), "plan_mean": ST.mean_by_blocks([x["ret"] for x in mine], [x["year"] for x in mine],
                                                                f"{run}|plans")}
        for bench in ("buy_hold_member", f"spy_matched_{v}", "spy"):
            b = spy_monthly if bench == "spy" else average([r["runs"][bench]["monthly"] for r in results])
            o[f"vs_{bench}"] = ST.yearly_excess(mcal, m_month, b)
        out[v] = o
    return out


def tables(results: list, key: str) -> tuple[dict, dict]:
    """(strategy columns, pool columns) by company for a version or a variant (a variant without a table of
    its own uses the main one)."""
    return ({r["symbol"]: r["strategy"][key] for r in results},
            {r["symbol"]: r["pool"].get(key, r["pool"][MAIN]) for r in results})


def primary(results: list, reps: int, versions) -> dict:
    """The plan-level test per version (T is the main result, F is look-ahead), on the hedged metric over 252
    sessions, with the 126-session and the unhedged versions beside it (descriptive)."""
    out = {}
    for v in versions:
        strat, pool = tables(results, v)
        out[v] = {"dh252": ST.plan_test(strat, pool, "dh252", "full252", reps, v),
                  "dh126": ST.plan_test(strat, pool, "dh126", "full126", reps, v),
                  "raw252": ST.plan_test(strat, pool, "raw252", "full252", reps, v),
                  "every_start": {r["symbol"]: r["every_start"][v] for r in results}}
    return out


def variant_tests(results: list, variants) -> dict:
    """Each variant's theta on DH_252 against its own every-start table (SPEC 7: descriptive, no p-value)."""
    out = {}
    for name in variants:
        strat, pool = tables(results, name)
        out[name] = {"dh252": ST.plan_test(strat, pool, "dh252", "full252", 0, f"{MAIN}|{name}"),
                     "own_table": all(name in r["pool"] for r in results),
                     "every_start": {r["symbol"]: r["every_start"][name] for r in results}}
    return out


def describe(results: list, key: str) -> dict:
    """SPEC 5.4, per plan with a full window: the method's mean of each metric against the pool's, weighted as
    theta weights it (each company's pool mean times its number of plans); the method's quantiles of DH_252
    and raw_252; the market part (raw_252 - DH_252); the exits of both."""
    strat, pool = tables(results, key)
    n, sums, wsum, exits, pexits, dh, raw = 0, {}, {}, {}, {}, [], []
    for c in strat:
        x, y = strat[c], pool[c]
        mine = [k for k, f in enumerate(x["full252"]) if f]
        pk = [k for k, f in enumerate(y["full252"]) if f]
        if not mine or not pk:
            continue
        n += len(mine)
        for m in S.METRICS:
            sums[m] = sums.get(m, 0.0) + sum(x[m][k] for k in mine)
            wsum[m] = wsum.get(m, 0.0) + len(mine) * sum(y[m][k] for k in pk) / len(pk)
        for k in mine:
            exits[x["status"][k]] = exits.get(x["status"][k], 0) + 1
            dh.append(x["dh252"][k])
            raw.append(x["raw252"][k])
        for k in pk:
            pexits[y["status"][k]] = pexits.get(y["status"][k], 0.0) + len(mine) / len(pk)
    if not n:
        return {"plans": 0}
    q = lambda v, f: sorted(v)[min(len(v) - 1, int(f * len(v)))]        # noqa: E731
    return {"plans": n, "mean": {m: sums[m] / n for m in S.METRICS}, "pool_mean": {m: wsum[m] / n for m in S.METRICS},
            "market_part": {"method": (sums["raw252"] - sums["dh252"]) / n,
                            "pool": (wsum["raw252"] - wsum["dh252"]) / n},
            "dh252": {"median": q(dh, 0.5), "q25": q(dh, 0.25), "q75": q(dh, 0.75), "q05": q(dh, 0.05)},
            "raw252": {"median": q(raw, 0.5), "q25": q(raw, 0.25), "q75": q(raw, 0.75), "q05": q(raw, 0.05)},
            "exits": {k: v / n for k, v in sorted(exits.items())},
            "pool_exits": {k: v / n for k, v in sorted(pexits.items())}}


def pool_dump(results: list, v: str) -> dict:
    """The every-start table of a version by company (pools_T.json, pools_F.json): enough to redo theta."""
    keep = ("day", "year", "full252", "full126", "dh252", "dh126", "raw252", "status", "fills", "temp0", "below_mid")
    return {r["symbol"]: {k: r["pool"][v][k] for k in keep} for r in results if v in r["pool"]}


TABLE_DIGEST = tuple(k for k in PL.COLUMNS if k != "start")     # a table's rows as their digest reads them


def table_digest(cols: dict) -> str:
    """The md5 of a table's rows (every column but the start's bar number) in start order: checks.plans_digest,
    which tabulates the plans check 6 audits by itself, gives the same when the table holds those plans and
    tabulates them right (report.py matches the two)."""
    rows = [list(r) for r in zip(*(cols[k] for k in TABLE_DIGEST))]
    return hashlib.md5(json.dumps(rows).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--snap", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--plan-replicas", type=int, default=ST.PLAN_REPS, help="the primary test's placebo")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--quick", action="store_true", help="T only, no variants, 200 replicas (a smoke test)")
    ap.add_argument("--sample", default=str(HERE / "sample.json"), help="the drawn sample (tests use their own)")
    ap.add_argument("--spinoffs", default=str(HERE / "spinoffs.json"))
    a = ap.parse_args(argv)
    snap, out = Path(a.snap), Path(a.out)
    if out.resolve() == snap.resolve() or snap.resolve() in out.resolve().parents:
        print("refused: --out is the snapshot folder or inside it")    # before anything there is deleted
        return 2
    out.mkdir(parents=True, exist_ok=True)
    for f in [out / name for name in OUTPUTS + ("repro.json",)] + list(out.glob("pools_*.json")):
        f.unlink(missing_ok=True)                   # an earlier run's outputs, and a comparison of them
    before = inputs(snap, Path(a.sample), Path(a.spinoffs))       # before anything is read
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
    gaps = M.check_complete(snap, [c[1] for c in comps])
    if gaps:
        print(f"snapshot refused: {len(gaps)} parts failed or are missing, e.g. {gaps[:3]}")
        return 2
    swaps = walk["replacements"]
    rates, spy = M.load(snap)
    cal = [d for d in spy.days if FIRST_DAY <= d <= walk["z"]]
    accr = accrual(cal, rates)
    versions = (MAIN,) if a.quick else VERSIONS
    variants = {} if a.quick else VARIANTS
    plan_reps = 200 if a.quick else a.plan_replicas
    jobs = [(snap, key, series, sec, spans, spinoffs.get(key, []), versions, variants, cal, accr)
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
    tf = [r["t_vs_f"] for r in results if r["t_vs_f"]]
    pairs = [x for t in tf for x in t["pairs"]]
    gates = {v: {k: sum(r["gates"][v][k] for r in results) for k in results[0]["gates"][v]} for v in versions}
    res = {"created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "snapshot": {"created": man.get("created"), "last_day": cal[-1], "files": len(man["files"])},
           "inputs": before,
           "companies": [{"symbol": c[0], "series": c[1], "sector": c[2]} for c in comps], "replacements": swaps,
           "walk": {k: walk.get(k) for k in ("z", "same_as_pc", "review", "assessed")},
           "first_day": FIRST_DAY, "rules": asdict(S.Rules()), "variants": variants,
           "primary": primary(results, plan_reps, versions),
           "signal": {MAIN: ST.signal_test([x for r in results for x in r["signal"].get(MAIN, [])], MAIN)},
           "variant_tests": variant_tests(results, variants),
           "describe": {k: describe(results, k) for k in list(versions) + list(variants)},
           "gates": gates,
           "t_vs_f": {"days": sum(t["days"] for t in tf), "agree": sum(t["agree"] for t in tf),
                      "sampled": len(pairs), "spearman": ST.spearman([a for a, _ in pairs], [b for _, b in pairs])}
           if tf else None,
           "summary": summary,
           "tables": {v: {r["symbol"]: {"method": table_digest(r["strategy"][v]), "pool": table_digest(r["pool"][v])}
                          for r in results} for v in versions},
           "compare": compare(results, plans, cal, versions, [spy_plain[k] for k in marks]),
           "reports": {r["symbol"]: r["report"] for r in results}}
    if inputs(snap, Path(a.sample), Path(a.spinoffs)) != before:
        print("refused: the snapshot's manifest, the sample, the spin-offs or the code changed during the run")
        return 2
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    with (out / "plans.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(plans[0]) if plans else ["symbol"])
        w.writeheader()
        w.writerows(plans)
    (out / "portfolio.json").write_text(json.dumps({"dates": cal, "series": port}), encoding="utf-8")
    for v in versions:
        (out / f"pools_{v}.json").write_text(json.dumps(pool_dump(results, v)), encoding="utf-8")
    (out / "status.json").write_text(json.dumps(walk, indent=1, default=str), encoding="utf-8")
    print(f"{len(comps)} companies ({sum(1 for x in swaps if x['in'])} replaced), {len(plans)} plan rows; "
          f"results in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
