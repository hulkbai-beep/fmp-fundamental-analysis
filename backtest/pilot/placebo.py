"""
The random-timing placebo: the same companies, the same plan levels, gates, build, stop and take-profit rules,
but plans start on random days instead of on a close below the band mid. The candidate days of a company are
the days a plan could start whatever the price (a member day with a band and an ATR on which the stop and
reward/risk gates pass); on every candidate day the sleeve is flat, the placebo starts a plan with probability
h. h is calibrated per company and version so that the placebo starts as many plans on average as the method
did. Replica k of a company draws from its own seeded stream, so any replica can be rerun alone.
"""
from __future__ import annotations

import hashlib
import random

import sim as S

MASTER = 20261029
CALIBRATION_REPS = 20
CALIBRATION_ROUNDS = 3


def stream(symbol: str, version: str, k: int, master: int = MASTER) -> random.Random:
    h = hashlib.sha256(f"{master}|placebo|{symbol}|{version}|{k}".encode()).hexdigest()
    return random.Random(int(h[:16], 16))


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


def draw(cands: list, symbol: str, version: str, k: int, h: float) -> set:
    """The start days of replica k: the same uniform draw per candidate day for every h, so the count rises
    with h and calibration converges."""
    rnd = stream(symbol, version, k)
    u = [rnd.random() for _ in cands]
    return {i for i, x in zip(cands, u) if x < h}


def n_plans(out: dict) -> int:
    return len(out["plans"]) + (1 if out["open"] else 0)


def calibrate(p, r: S.Rules, rates, target: int, cands: list, first_day: str) -> float:
    """h such that the mean number of plans over the calibration replicas is about the method's."""
    if not target or not cands:
        return 0.0
    h = min(1.0, target / len(cands) * 3.0)
    for _ in range(CALIBRATION_ROUNDS):
        got = [n_plans(S.run(p, r, rates, first_day=first_day, record_days=False,
                             starts=draw(cands, p.symbol, r.version, -1 - k, h)))
               for k in range(CALIBRATION_REPS)]
        mean = sum(got) / len(got)
        if mean <= 0:
            h = min(1.0, h * 4.0)
            continue
        h = min(1.0, h * target / mean)
    return h


def replica(p, r: S.Rules, rates, h: float, k: int, cands: list, **kw) -> dict:
    """One placebo run: plans may start on the drawn candidate days."""
    return S.run(p, r, rates, starts=draw(cands, p.symbol, r.version, k, h), **kw)


def eligible_days(p, out: dict, r: S.Rules) -> int:
    """Days in the method's own run on which it was flat and could have started a plan whatever the price
    (a member day with a band and an ATR): the base of the method's entry rate."""
    busy = set()
    for pl in out["plans"] + ([out["open"]] if out["open"] else []):
        end = pl.end if pl.end is not None else out["last"]
        busy.update(range(pl.start, end + r.cooldown + 1))
    return sum(1 for i in range(out["first"], out["last"])
               if i not in busy and p.atr[i] and p.range_at(r.version, i) is not None and p.can_start(r.version, i))
