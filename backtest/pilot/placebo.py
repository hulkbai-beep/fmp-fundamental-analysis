"""
The random-timing placebo of the primary test: the same companies, the same plan levels, gates, build, stop and
take-profit rules, but plans start on random days instead of on a close below the band mid.

The pool of a company is every bar on which a plan could start whatever the price: a member day that is not
suspicious, not the close before a confirmed spin-off and not in a blackout after one, with a band and an ATR,
on which the stop and reward/risk gates pass, and not the last bar (any temperature: a plan started while rich
waits for fair). The every-start table (pool()) simulates one plan alone from every pool day; a plan's course
does not depend on the sleeve around it, so each of the method's plans must be in the table with the same
outcome. stats.plan_test draws the replicas from the table: for every company as many start days as the
method had plans with a full window, with replacement from its pool days with a full window.

A window is full when the 252nd SPY session after the start is on or before Z, the snapshot's last session
(whether or not the company still trades then: a delisted company's plan ends at its last close).
"""
from __future__ import annotations

import bisect

import sim as S


def sessions(dates: list, spy_days: list) -> list:
    """The SPY session number of each bar: the last SPY session on or before its date."""
    return [bisect.bisect_right(spy_days, d) - 1 for d in dates]


def candidates(p, r: S.Rules, first: int, last: int) -> list:
    """Bars on which a plan could start whatever the price: the gates are those of the method's own plan."""
    out = []
    for i in range(first, last):
        rng = p.range_at(r.version, i)
        if not (rng and p.atr[i] and p.can_start(r.version, i)):
            continue
        c, A = p.c[i], p.atr[i]
        stop0 = S.initial_stop(c, A, r, gate=True)
        t1, _, _ = S.targets(c, A, rng[1], rng[2], r)
        if S.gates(c, stop0, t1, r)[1] is None:
            out.append(i)
    return out


COLUMNS = ("start", "day", "year", "full252", "full126", "dh252", "dh126", "raw252", "tb252", "cost252", "dep252",
           "mae252", "status", "fills", "temp0", "below_mid")


def row(p, pl, sess: list, zi: int) -> dict:
    """A plan's row of its table (COLUMNS): its hedged metric per unit of the planned position and whether its
    window is full (the 252nd / 126th SPY session after the start is session zi or earlier)."""
    out = {"start": pl.start, "day": p.dates[pl.start], "year": int(p.dates[pl.start][:4]),
           "full252": sess[pl.start] + S.H_LONG <= zi, "full126": sess[pl.start] + S.H_SHORT <= zi,
           "status": pl.status, "fills": len(pl.filled), "temp0": pl.temp0,
           "below_mid": pl.price < pl.mid0 if pl.mid0 else None}
    out.update(pl.metrics())
    return {k: out[k] for k in COLUMNS}


def columns(p, plans: list, sess: list, zi: int) -> dict:
    """Plans (closed, open or void) as columns, by start (their rows, row())."""
    out = {k: [] for k in COLUMNS}
    for pl in sorted(plans, key=lambda x: x.start):
        for k, x in row(p, pl, sess, zi).items():
            out[k].append(x)
    return out


def method_plans(out: dict) -> list:
    """Every plan the method started: closed, still open at the end, and void (never bought)."""
    return out["plans"] + ([out["open"]] if out["open"] else []) + out["voids"]


def every_start(p, r: S.Rules, rates, hedge, first: int, last: int) -> list:
    """One plan from every pool day, simulated alone (the plans of the every-start table; checks.py replays
    each). hedge: sim.run's (SPY opens, SPY closes, SPY session numbers) on p.dates."""
    plans = []
    for i in candidates(p, r, first, last):
        o = S.run(p, r, rates, first_day=p.dates[i], starts={i}, record_days=False, hedge=hedge, single=True)
        got = method_plans(o)
        if got:
            plans.append(got[0])
    return plans


def pool(p, r: S.Rules, rates, hedge, first: int, last: int, zi: int) -> dict:
    """The every-start table: every_start's plans as columns."""
    return columns(p, every_start(p, r, rates, hedge, first, last), hedge[2], zi)
