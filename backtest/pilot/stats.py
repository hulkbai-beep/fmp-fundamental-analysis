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
    """Indices of the first session (where every series starts at 1.0, so the first year counts from it), the
    last session of each month, and the last session."""
    if not cal:
        return []
    return sorted({0, len(cal) - 1} | {k for k in range(len(cal) - 1) if cal[k][:7] != cal[k + 1][:7]})


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


# ---------------------------------------------------------------- the primary test (plan level)
PLAN_REPS = 1000
PLACEBO_SEED = 20261029


def _stream(tag: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{PLACEBO_SEED}|{tag}".encode()).hexdigest()[:16], 16))


def plan_stream(company, version: str, k: int) -> random.Random:
    """The placebo's draws for one (company, version, replica): the same days for every metric that reads the
    same pool, and any replica can be redrawn alone."""
    return _stream(f"plan|{version}|{company}|{k}")


def diff_by_blocks_w(xa: list, la: list, xb: list, lb: list, wb: list, tag: str, level: float = LEVEL) -> dict:
    """mean(A) - weighted mean(B), both formed in every resample from the same resampled blocks (V3's
    unpaired difference; the weights of B are fixed)."""
    uniq, table = block_table(list(la) + list(lb), tag)
    idx = {u: j for j, u in enumerate(uniq)}
    G = len(uniq)
    sa, na, sb, wsum = [0.0] * G, [0] * G, [0.0] * G, [0.0] * G
    for v, lab in zip(xa, la):
        sa[idx[lab]] += v
        na[idx[lab]] += 1
    for v, lab, w in zip(xb, lb, wb):
        sb[idx[lab]] += w * v
        wsum[idx[lab]] += w
    rs = []
    for row in table:
        ca, cw = sum(na[j] for j in row), sum(wsum[j] for j in row)
        rs.append(sum(sa[j] for j in row) / ca - sum(sb[j] for j in row) / cw if ca and cw else None)
    theta = sum(xa) / len(xa) - sum(w * v for v, w in zip(xb, wb)) / sum(wb)
    out = summary(theta, rs, G, level)
    out["n_a"], out["n_b"] = len(xa), len(xb)
    return out


def _theta(cos: list, x: dict, y: dict) -> float | None:
    """mean of the strategy's plans pooled minus sum n_i mean(pool_i) / sum n_i (a company whose pool is empty
    once a year is left out is left out too: each strategy start is a pool day, so it then has no plans)."""
    cos = [c for c in cos if y[c]]
    n = sum(len(x[c]) for c in cos)
    if not n:
        return None
    return sum(sum(x[c]) for c in cos) / n - sum(len(x[c]) * sum(y[c]) / len(y[c]) for c in cos if x[c]) / n


def plan_test(strat: dict, pool: dict, metric: str = "dh252", full: str = "full252", reps: int = PLAN_REPS,
              tag: str = "T", level: float = LEVEL) -> dict:
    """The primary test. strat, pool: {company: placebo.columns}. theta = the strategy's plans with a full
    window pooled (a plan that never bought counts 0) minus the placebo's expectation (each company's pool
    mean weighted by its number of strategy plans). Placebo replicas draw n_i starts per company with
    replacement from its pool (plan_stream(company, tag, replica)): one-sided p = (1 + #{theta_b >= theta}) /
    (1 + reps). Interval: calendar-year blocks of the start (strategy plans and the pool resampled together,
    the pool weighted n_i / |pool_i|). Also the company-cluster bootstrap SE, leave-one-year-out, without the 3
    largest contributors and the range of leave-one-company-out."""
    def pick(cols):
        keep = [k for k, f in enumerate(cols[full]) if f]
        return [cols[metric][k] for k in keep], [cols["year"][k] for k in keep]
    x, xy, y, yy = {}, {}, {}, {}
    for c in sorted(strat):
        x[c], xy[c] = pick(strat[c])
        y[c], yy[c] = pick(pool[c]) if c in pool else ([], [])
    cos = [c for c in x if x[c]]
    if any(not y[c] for c in cos):
        raise ValueError(f"a company has strategy plans but an empty pool: {[c for c in cos if not y[c]]}")
    theta = _theta(cos, x, y)
    out = {"metric": metric, "companies": len(cos), "plans": sum(len(x[c]) for c in cos),
           "pool": sum(len(y[c]) for c in cos), "theta": theta,
           "void_plans": sum(1 for c in strat for f, k in zip(strat[c][full], strat[c].get("fills") or [])
                             if f and not k)}
    if theta is None:
        return out
    n_tot = sum(len(x[c]) for c in cos)
    expect = sum(len(x[c]) * sum(y[c]) / len(y[c]) for c in cos) / n_tot
    out["strategy_mean"], out["placebo_expectation"] = theta + expect, expect
    out["placebo"] = None                                   # reps = 0: theta only (the variants)
    if reps > 0:
        draws = []
        for b in range(reps):
            tot = 0.0
            for c in cos:
                rnd, yc = plan_stream(c, tag, b), y[c]
                m = len(yc)
                tot += sum(yc[int(rnd.random() * m)] for _ in range(len(x[c])))
            draws.append(tot / n_tot - expect)
        ge = sum(d >= theta for d in draws)
        srt = sorted(draws)
        out["placebo"] = {"replicas": reps, "p_one_sided": (1 + ge) / (1 + reps),
                          "percentile": 1 - (1 + ge) / (1 + reps), "mean": statistics.mean(draws),
                          "sd": statistics.stdev(draws) if reps > 1 else None,
                          "q05": srt[int(0.05 * (reps - 1))], "q50": srt[int(0.5 * (reps - 1))],
                          "q95": srt[int(0.95 * (reps - 1))]}
    xa = [v for c in cos for v in x[c]]
    la = [v for c in cos for v in xy[c]]
    xb = [v for c in cos for v in y[c]]
    lb = [v for c in cos for v in yy[c]]
    wb = [len(x[c]) / len(y[c]) for c in cos for _ in y[c]]
    out["year_blocks"] = diff_by_blocks_w(xa, la, xb, lb, wb, f"plan|{tag}|{metric}", level)
    out["cluster"] = cluster_se(cos, x, y, f"cluster|{tag}|{metric}")
    years = sorted(set(la))
    loyo = {}
    for yr in years:
        xs = {c: [v for v, t in zip(x[c], xy[c]) if t != yr] for c in cos}
        ys = {c: [v for v, t in zip(y[c], yy[c]) if t != yr] for c in cos}
        loyo[yr] = _theta([c for c in cos if xs[c]], xs, ys)
    vals = [v for v in loyo.values() if v is not None]
    out["leave_one_year_out"] = {"by_year": loyo, "min": min(vals) if vals else None,
                                 "max": max(vals) if vals else None}
    contrib = {c: sum(v - sum(y[c]) / len(y[c]) for v in x[c]) / n_tot for c in cos}
    top = sorted(cos, key=lambda c: contrib[c], reverse=True)[:3]
    rest = [c for c in cos if c not in top]
    out["without_top3"] = {"companies": top, "theta": _theta(rest, x, y)}
    loco = {c: _theta([k for k in cos if k != c], x, y) for c in cos}
    have = {c: v for c, v in loco.items() if v is not None}
    out["leave_one_company_out"] = {"min": min(have.values()) if have else None,
                                    "max": max(have.values()) if have else None,
                                    "min_without": min(have, key=have.get) if have else None,
                                    "max_without": max(have, key=have.get) if have else None}
    out["by_company"] = {c: {"plans": len(x[c]), "pool": len(y[c]), "mean": sum(x[c]) / len(x[c]),
                             "pool_mean": sum(y[c]) / len(y[c]), "contribution": contrib[c]} for c in cos}
    return out


def cluster_se(cos: list, x: dict, y: dict, tag: str, n_boot: int = B) -> dict:
    """theta's standard error from resampling whole companies with replacement (sqrt(K / (K - 1)) applied)."""
    K = len(cos)
    if K < 2:
        return {"se": None, "K": K}
    rnd = _stream(tag)
    sx = [sum(x[c]) for c in cos]
    nx = [len(x[c]) for c in cos]
    ex = [len(x[c]) * sum(y[c]) / len(y[c]) for c in cos]
    rs = []
    for _ in range(n_boot):
        ks = [rnd.randrange(K) for _ in range(K)]
        n = sum(nx[k] for k in ks)
        rs.append((sum(sx[k] for k in ks) - sum(ex[k] for k in ks)) / n)
    return {"se": math.sqrt(K / (K - 1)) * statistics.stdev(rs), "K": K}


# ---------------------------------------------------------------- the rules-free signal test
def ranks(v: list) -> list:
    order = sorted(range(len(v)), key=lambda k: v[k])
    out = [0.0] * len(v)
    j = 0
    while j < len(order):
        k = j
        while k + 1 < len(order) and v[order[k + 1]] == v[order[j]]:
            k += 1
        for m in range(j, k + 1):
            out[order[m]] = (j + k) / 2.0
        j = k + 1
    return out


def spearman(a: list, b: list) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    sab = sum((u - ma) * (w - mb) for u, w in zip(ra, rb))
    saa, sbb = sum((u - ma) ** 2 for u in ra), sum((w - mb) ** 2 for w in rb)
    return sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None


def signal_test(rows: list, tag: str = "T") -> dict:
    """rows: (year, below_mid, signal, {h: forward hedged return}, company) on the sampled gate-passing member
    days. Per horizon: mean after below-mid days minus after the other days, the share of days below mid, and
    the pooled Spearman IC of the signal with the forward return. The gap's interval (an amendment of SPEC 5.3
    after review): a day's return runs up to a year ahead and a company stays below its mid for months, so
    neighbouring calendar years and one company's days are not independent, and the interval of SPEC 5.3's
    1-year blocks (kept as 'by_year') covered about 86% for a stated 90% in no-edge simulations; 'gap' is
    the wider of 2-calendar-year blocks and company clusters, each with its own t quantile."""
    out = {"days": len(rows), "below_share": sum(1 for r in rows if r[1]) / len(rows) if rows else None}
    schemes = (("by_year", lambda r: r[0], f"signal|{tag}"), ("two_years", lambda r: 2008 + 2 * ((r[0] - 2008) // 2),
                                                                f"signal2y|{tag}"),
               ("company", lambda r: r[4], f"signalco|{tag}"))
    for h in sorted({h for r in rows for h in r[3]}):
        have = [r for r in rows if r[3].get(h) is not None]
        a = [r for r in have if r[1]]
        b = [r for r in have if not r[1]]
        res = {"days": len(have), "below": len(a), "other": len(b)}
        if a and b:
            got = {name: diff_by_blocks([r[3][h] for r in a], [lab(r) for r in a], [r[3][h] for r in b],
                                        [lab(r) for r in b], f"{t}|{h}") for name, lab, t in schemes}
            wide = max(("two_years", "company"), key=lambda k: got[k]["se"] if math.isfinite(got[k]["se"]) else -1.0)
            res["gap"] = dict(got[wide], scheme=wide)
            res["gap_schemes"] = {k: {"se": x["se"], "G": x["G"], "lo": x["lo"], "hi": x["hi"]} for k, x in got.items()}
        res["ic"] = spearman([r[2] for r in have], [r[3][h] for r in have])
        out[f"h{h}"] = res
    return out
