"""
Statistics of the pilot: performance of a value series, the method against its random-timing placebo, and
calendar-year block bootstrap intervals (the ladder V3 method: whole calendar years resampled with
replacement, the small-block correction sqrt(G / (G - 1)) on the standard error). Standard library only.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import random
import statistics

B = 10_000
LEVEL = 0.90
BOOT_SEED = 20261029


def years_between(a: str, b: str) -> float:
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days / 365.25


def series_stats(cal: list, v: list, accr: list) -> dict:
    """CAGR, annual volatility, Sharpe ratio on daily excess returns over the T-bill, maximum drawdown."""
    yrs = years_between(cal[0], cal[-1])
    rets, ex = [], []
    for k in range(1, len(v)):
        if v[k - 1] and v[k]:
            r = v[k] / v[k - 1] - 1.0
            rets.append(r)
            ex.append(r - (accr[k] / accr[k - 1] - 1.0))
    peak, mdd = v[0], 0.0
    for x in v:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1.0)
    vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) > 2 else None
    sd = statistics.stdev(ex) if len(ex) > 2 else 0.0
    return {"total": v[-1] / v[0] - 1.0, "cagr": (v[-1] / v[0]) ** (1 / yrs) - 1.0 if yrs > 0 else None,
            "vol": vol, "sharpe": statistics.mean(ex) / sd * math.sqrt(252) if sd else None, "max_dd": mdd,
            "tbill_cagr": accr[-1] ** (1 / yrs) - 1.0 if yrs > 0 else None}


def month_ends(cal: list) -> list:
    """Indices of the last session of each month (and the last session)."""
    out = [k for k in range(len(cal) - 1) if cal[k][:7] != cal[k + 1][:7]]
    return out + [len(cal) - 1]


def t_ppf(p: float, df: int) -> float:
    """Student's t quantile by bisection on the CDF (df >= 1)."""
    lo, hi = -50.0, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def t_cdf(x: float, df: int) -> float:
    """Student's t CDF from the regularised incomplete beta function."""
    if x == 0:
        return 0.5
    z = df / (df + x * x)
    tail = 0.5 * _betai(df / 2.0, 0.5, z)
    return 1.0 - tail if x > 0 else tail


def _betai(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lb) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lb) * _betacf(b, a, 1 - x) / b


def _betacf(a: float, b: float, x: float) -> float:
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > 1e-300 else 1e-300
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-300 else 1e-300)
        c = 1.0 + aa / c if abs(1.0 + aa / c) > 1e-300 else 1e-300
        de = d * c
        h *= de
        if abs(de - 1.0) < 1e-12:
            break
    return h


def block_table(labels: list, tag: str, n_boot: int = B) -> tuple[list, list]:
    """(the distinct blocks, n_boot resamples of block indices), seeded from the blocks themselves."""
    uniq = sorted(set(labels))
    seed = int(hashlib.sha256(f"{BOOT_SEED}|{tag}|{','.join(map(str, uniq))}".encode()).hexdigest()[:16], 16)
    rnd = random.Random(seed)
    G = len(uniq)
    return uniq, [[rnd.randrange(G) for _ in range(G)] for _ in range(n_boot)]


def summary(theta: float, rs: list, G: int, level: float = LEVEL) -> dict:
    rs = [x for x in rs if x is not None and math.isfinite(x)]
    sd = statistics.stdev(rs) if len(rs) > 1 else float("nan")
    se = math.sqrt(G / (G - 1)) * sd if G > 1 else float("nan")
    q = t_ppf(0.5 + level / 2.0, G - 1) if G > 1 else float("nan")
    srt = sorted(rs)
    pct = (lambda f: srt[min(len(srt) - 1, max(0, int(round(f * (len(srt) - 1)))))]) if srt else (lambda f: None)
    p = 2.0 * (1.0 - t_cdf(abs(theta) / se, G - 1)) if se and se > 0 and math.isfinite(se) else None
    return {"theta": theta, "se": se, "G": G, "lo": theta - q * se, "hi": theta + q * se,
            "lo_pct": pct((1 - level) / 2), "hi_pct": pct((1 + level) / 2), "p": p, "level": level}


def mean_by_blocks(x: list, labels: list, tag: str, level: float = LEVEL) -> dict:
    """Mean of x with a calendar-block bootstrap interval (blocks = labels, e.g. the start year)."""
    if not x:
        return {"theta": None, "n": 0}
    uniq, table = block_table(labels, tag)
    idx = {u: j for j, u in enumerate(uniq)}
    s, n = [0.0] * len(uniq), [0] * len(uniq)
    for v, lab in zip(x, labels):
        s[idx[lab]] += v
        n[idx[lab]] += 1
    rs = []
    for row in table:
        tot, cnt = sum(s[j] for j in row), sum(n[j] for j in row)
        rs.append(tot / cnt if cnt else None)
    out = summary(sum(x) / len(x), rs, len(uniq), level)
    out["n"] = len(x)
    return out


def diff_by_blocks(xa: list, la: list, xb: list, lb: list, tag: str, level: float = LEVEL) -> dict:
    """mean(A) - mean(B), both means formed in every resample from the same resampled blocks."""
    if not xa or not xb:
        return {"theta": None, "n_a": len(xa), "n_b": len(xb)}
    uniq, table = block_table(list(la) + list(lb), tag)
    idx = {u: j for j, u in enumerate(uniq)}
    G = len(uniq)
    sa, na, sb, nb = [0.0] * G, [0] * G, [0.0] * G, [0] * G
    for v, lab in zip(xa, la):
        sa[idx[lab]] += v
        na[idx[lab]] += 1
    for v, lab in zip(xb, lb):
        sb[idx[lab]] += v
        nb[idx[lab]] += 1
    rs = []
    for row in table:
        ca, cb = sum(na[j] for j in row), sum(nb[j] for j in row)
        rs.append(sum(sa[j] for j in row) / ca - sum(sb[j] for j in row) / cb if ca and cb else None)
    out = summary(sum(xa) / len(xa) - sum(xb) / len(xb), rs, G, level)
    out["n_a"], out["n_b"] = len(xa), len(xb)
    return out


def yearly_excess(cal: list, a: list, b: list) -> dict:
    """Calendar-year returns of a minus b (both value series on cal): per year and the block-bootstrap mean."""
    years = sorted({d[:4] for d in cal})
    out = {}
    for y in years:
        ks = [k for k, d in enumerate(cal) if d[:4] == y]
        k0 = ks[0] - 1 if ks[0] > 0 else ks[0]
        k1 = ks[-1]
        out[y] = (a[k1] / a[k0] - 1.0) - (b[k1] / b[k0] - 1.0)
    vals = list(out.values())
    return {"by_year": out, "mean": mean_by_blocks(vals, list(out), "yearly_excess")}


def rank_against(value: float, draws: list) -> dict:
    """Where the method's value falls among the placebo replicas: the share of replicas at or above it (a
    one-sided p-value with the +1 correction) and the replicas' mean and spread."""
    d = [x for x in draws if x is not None and math.isfinite(x)]
    if not d or value is None:
        return {"value": value, "n": len(d)}
    ge = sum(x >= value for x in d)
    return {"value": value, "n": len(d), "placebo_mean": statistics.mean(d),
            "placebo_sd": statistics.stdev(d) if len(d) > 1 else None,
            "p_one_sided": (ge + 1) / (len(d) + 1), "percentile": sum(x < value for x in d) / len(d)}
