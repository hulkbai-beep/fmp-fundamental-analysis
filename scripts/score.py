"""
Fundamental score: valuation, quality, growth and financial health, each scored -2..+2 from a few
indicators with fixed thresholds, then weighted into one score on the same -2..+2 scale and the same
five labels as the technical-analysis scorecard (Bearish .. Bullish).

- Each indicator maps one number to -2..+2 through the cut points below (a value equal to a cut point
  takes the band above it). A pillar is the weighted mean of its indicators.
- An indicator with no data counts as 0 and keeps its weight, so missing data pulls the pillar toward 0.
  An indicator that does not apply (EV/EBITDA for a bank) is left out and the others are reweighted.
- Two caps keep the total at Neutral (+0.4) at most: a balance-sheet red line, and a "value trap"
  (cheap valuation with weak quality and growth).
- Rates enter only through the DCF's Treasury-linked discount rate; macro releases are not scored.

score(r) works on the dict analyze() returns and makes no API calls. render(s) prints the report
section. The rules are documented in references/metrics.md ("Fundamental score"); every change to a
threshold or weight bumps RULES_VERSION. The score is a rule-based label, not a recommendation.
"""
from __future__ import annotations

import bisect
import statistics

RULES_VERSION = "1.0"

PILLARS = ("valuation", "quality", "growth", "health")
PILLAR_WEIGHTS = {"valuation": 0.35, "quality": 0.25, "growth": 0.20, "health": 0.20}

# Indicator weights inside each pillar, by company type. An indicator listed for "general" but not for
# "financial" is shown as not applicable for banks and insurers.
WEIGHTS = {
    "general": {
        "valuation": {"fwd_pe_position": 0.30, "fwd_ev_position": 0.20, "implied_growth_gap": 0.20,
                      "dcf_margin": 0.15, "vs_industry": 0.15},
        "quality": {"roic_level": 0.30, "roic_trend": 0.15, "op_margin_trend": 0.15,
                    "gross_margin_stability": 0.10, "fcf_conversion": 0.20, "sbc_burden": 0.10},
        "growth": {"revenue_cagr": 0.30, "revenue_recent": 0.20, "revenue_forward": 0.30, "eps_forward": 0.20},
        "health": {"net_debt_ebitda": 0.25, "interest_coverage": 0.20, "altman": 0.15, "piotroski": 0.20,
                   "current_ratio": 0.10, "dilution": 0.10},
    },
    "financial": {
        "valuation": {"fwd_pe_position": 0.40, "pb_vs_history": 0.30, "vs_industry": 0.30},
        "quality": {"roe_level": 0.50, "roe_trend": 0.30, "sbc_burden": 0.20},
        "growth": {"revenue_cagr": 0.30, "revenue_recent": 0.20, "revenue_forward": 0.30, "eps_forward": 0.20},
        "health": {"piotroski": 0.40, "equity_to_assets": 0.35, "dilution": 0.25},
    },
}

UP = (-2, -1, 0, 1, 2)    # higher is better
DOWN = (2, 1, 0, -1, -2)  # lower is better
# key: (cut points, scores, unit). Units: pct = fraction shown as %, pt = signed difference in percentage
# points, pp = unsigned percentage points, pctile = percentile of a history, x = multiple, num = plain number.
BANDS = {
    "fwd_pe_position": ((0.25, 0.45, 0.55, 0.75), DOWN, "pctile"),   # the price range's 25th / median / 75th
    "fwd_ev_position": ((0.25, 0.45, 0.55, 0.75), DOWN, "pctile"),
    "trailing_vs_median": ((-0.25, -0.10, 0.10, 0.25), DOWN, "pct"),  # fallback: multiple vs own FY-end median
    "pb_vs_history": ((-0.25, -0.10, 0.10, 0.25), DOWN, "pct"),
    "implied_growth_gap": ((-0.05, -0.02, 0.02, 0.08), DOWN, "pt"),
    "dcf_margin": ((-0.30, -0.10, 0.10, 0.30), UP, "pct"),
    "vs_industry": ((-0.30, -0.10, 0.25, 0.60), DOWN, "pct"),
    "roic_level": ((0.05, 0.08, 0.12, 0.20), UP, "pct"),
    "roe_level": ((0.05, 0.08, 0.11, 0.15), UP, "pct"),
    "roic_trend": ((-0.05, -0.02, 0.02, 0.05), UP, "pt"),
    "roe_trend": ((-0.05, -0.02, 0.02, 0.05), UP, "pt"),
    "op_margin_trend": ((-0.05, -0.02, 0.02, 0.05), UP, "pt"),
    "gross_margin_stability": ((0.015, 0.03, 0.05, 0.08), DOWN, "pp"),
    "fcf_conversion": ((0.5, 0.8, 1.0, 1.2), UP, "x"),
    "sbc_burden": ((0.02, 0.05, 0.10, 0.20), DOWN, "pct"),
    "revenue_cagr": ((0.0, 0.03, 0.08, 0.15), UP, "pct"),
    "revenue_recent": ((0.0, 0.03, 0.08, 0.15), UP, "pct"),
    "revenue_forward": ((0.0, 0.03, 0.08, 0.15), UP, "pct"),
    "eps_forward": ((0.0, 0.05, 0.10, 0.20), UP, "pct"),
    "net_debt_ebitda": ((0.0, 1.0, 2.5, 4.0), DOWN, "x"),
    "net_debt_ebitda_reit": ((0.0, 4.0, 6.0, 8.0), DOWN, "x"),
    "interest_coverage": ((2.0, 4.0, 8.0, 20.0), UP, "x"),
    "piotroski": ((2, 4, 7, 8), UP, "num"),                           # F-score scaled to 9 tests
    "current_ratio": ((1.0, 1.5), (-1, 0, 1), "x"),
    "dilution": ((-0.02, -0.005, 0.01, 0.03), DOWN, "pct"),
    "equity_to_assets": ((0.05, 0.07, 0.10, 0.13), UP, "pct"),
}
ALTMAN_SCORES = {"safe": 1, "grey": 0, "distress": -1}  # -2 when both Z and Z'' are in distress

# The total's five labels: a score exactly on a bound takes the label nearer Neutral.
LABELS = ((1.2, "Bullish"), (0.4, "Moderately bullish"), (-0.4, "Neutral"), (-1.2, "Moderately bearish"))
CAP = 0.4                     # value-trap and red-line caps: the total is at most Neutral
VALUE_TRAP_VALUATION = 1.0    # valuation >= this ...
VALUE_TRAP_BUSINESS = -0.5    # ... while the mean of quality and growth <= this
SLOWDOWN_HIST_MIN = 0.15      # forward-multiple position capped at +1 when historical EPS growth > 15%
SLOWDOWN_RATIO = 0.5          # ... and next year's expected EPS growth is under half of it
COVERAGE_LOW, COVERAGE_HIGH = 0.6, 0.85
AGREEMENT_LOW, AGREEMENT_HIGH = 0.5, 0.7
PILLAR_DEADBAND = 0.25        # a pillar within +-0.25 counts as neutral for agreement


# ---------------------------------------------------------------------------- helpers
def _f(x):
    """Plain float, or None for missing / non-numeric values."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def band_score(value, cuts, scores):
    return scores[bisect.bisect_right(cuts, value)]


def _ind(key, value=None, band=None, score=None, status="ok", note=None, detail=None):
    """One indicator. With a band name and a value, the score comes from that band."""
    cuts, scores, unit = BANDS.get(band or key, (None, None, None))
    if status == "ok" and score is None:
        score = band_score(value, cuts, scores)
    return {"key": key, "status": status, "value": value, "unit": unit, "cuts": list(cuts) if cuts else None,
            "scores": list(scores) if scores else None, "score": score if status == "ok" else 0,
            "note": note, "detail": detail or {}}


def _missing(key, note, band=None):
    return _ind(key, band=band, status="missing", note=note)


def _years_back(years, n=3):
    """The fiscal year n years before the latest (or the oldest one), or None with a single year."""
    return years[max(0, len(years) - 1 - n)] if len(years) >= 2 else None


def _estimates(r):
    """Analyst estimate rows for fiscal years still in progress or ahead, nearest first."""
    return [e for e in ((r.get("analyst") or {}).get("estimates") or []) if not e.get("ended")]


def _fwd_eps_growth(r):
    """Analysts' EPS growth from the fiscal year in progress to the next one (same, usually adjusted, basis)."""
    est = _estimates(r)
    if len(est) >= 2:
        a, b = _f(est[0].get("eps_avg")), _f(est[1].get("eps_avg"))
        if a and a > 0 and b is not None:
            return b / a - 1, est[0]["fy"], est[1]["fy"]
    return None, None, None


def _fwd_revenue_growth(r):
    vals = [_f(e.get("revenue_growth")) for e in _estimates(r)[:2]]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals), [e["fy"] for e in _estimates(r)[:2]]) if vals else (None, None)


# ---------------------------------------------------------------------------- valuation
def _position(band, key):
    return _ind(key, band["now_pct"], detail={"now": band["now"], "p25": band["p25"], "median": band["median"],
                                              "p75": band["p75"], "from": band["from"], "to": band["to"]})


def _multiple_position(r, key, band_key, hist_key):
    """Where today's forward multiple sits in its 3-year history, else the trailing multiple vs its
    fiscal-year-end median."""
    pr = r.get("price_range") or {}
    band = pr.get(band_key)
    if band and band.get("now_pct") is not None:
        return _position(band, key)
    h = (r.get("history_compare") or {}).get(hist_key) or {}
    if h.get("vs_median") is not None and (h.get("n") or 0) >= 3:
        return _ind(key, h["vs_median"], band="trailing_vs_median", note="trailing_history",
                    detail={"now": h["current"], "median": h["median"], "n": h["n"]})
    if pr.get("band_note"):
        return _missing(key, "no_band")
    return _missing(key, "no_estimates" if not _estimates(r) else "loss_making")


def _slowdown_cap(ind, r):
    """A cheap multiple after fast growth often reflects a slowdown the market expects to last: cap +2 at +1."""
    if ind["status"] != "ok" or ind["score"] < 2:
        return
    g, fy0, fy1 = _fwd_eps_growth(r)
    hist = _f((r.get("cagr") or {}).get("eps"))
    if g is not None and hist is not None and hist > SLOWDOWN_HIST_MIN and g < hist * SLOWDOWN_RATIO:
        ind["score"], ind["note"] = 1, "growth_slowdown"
        ind["detail"].update(capped_from=2, eps_growth_next=g, eps_cagr=hist, fy_from=fy0, fy_to=fy1)


def valuation(r, kind):
    d, out = r.get("dcf") or {}, {}
    out["fwd_pe_position"] = _multiple_position(r, "fwd_pe_position", "pe_band", "pe")
    _slowdown_cap(out["fwd_pe_position"], r)
    if kind == "financial":
        h = (r.get("history_compare") or {}).get("pb") or {}
        out["pb_vs_history"] = (_ind("pb_vs_history", h["vs_median"], detail={"now": h["current"], "median": h["median"],
                                                                              "n": h["n"]})
                                if h.get("vs_median") is not None and (h.get("n") or 0) >= 3 else _missing("pb_vs_history", "short_history"))
    else:
        out["fwd_ev_position"] = _multiple_position(r, "fwd_ev_position", "ev_band", "ev_ebitda")
        _slowdown_cap(out["fwd_ev_position"], r)
        out["implied_growth_gap"] = _implied_growth_gap(r, d)
        mos = _f(d.get("margin_of_safety"))
        if "skipped" in d:
            out["dcf_margin"] = _ind("dcf_margin", status="n/a", note="no_dcf")
        elif mos is None:
            out["dcf_margin"] = _missing("dcf_margin", "no_data")
        else:
            vps = _f(d.get("value_per_share"))
            out["dcf_margin"] = _ind("dcf_margin", mos, note="dcf_negative" if vps is not None and vps <= 0 else None,
                                     detail={"value": vps, "low": d.get("range_low"), "high": d.get("range_high")})
    out["vs_industry"] = _vs_industry(r)
    return out


def _implied_growth_gap(r, d):
    """Growth the price implies (reverse DCF) minus the growth analysts expect (or history delivered)."""
    key = "implied_growth_gap"
    if "skipped" in d:
        return _ind(key, status="n/a", note="no_dcf")
    ref, fys = _fwd_revenue_growth(r)
    note, src = None, "analysts"
    if ref is None:
        ref, note, src = _f((r.get("cagr") or {}).get("revenue")), "historical_growth", "history"
    ig = _f(d.get("implied_growth"))
    detail = {"implied": ig, "reference": ref, "reference_source": src, "fys": fys}
    if ig is None:
        why = str(d.get("implied_growth_note") or "")
        if why.startswith("below"):
            return _ind(key, score=2, note="implied_below_range", detail=detail)
        if why.startswith("above"):
            return _ind(key, score=-2, note="implied_above_range", detail=detail)
        return _missing(key, "no_data")
    if ref is None:
        return _missing(key, "no_data")
    return _ind(key, ig - ref, note=note, detail=detail)


def _vs_industry(r):
    sc = (r.get("market") or {}).get("sector")
    if not sc:
        return _missing("vs_industry", "no_market")
    ipe = sc.get("industry_pe") or {}
    if sc.get("vs_industry") is not None:
        return _ind("vs_industry", sc["vs_industry"], detail={
            "company_pe": sc.get("company_pe"), "group_pe": ipe.get("current"), "group": "industry",
            "group_percentile": ipe.get("percentile")})
    if sc.get("vs_sector") is not None:
        spe = sc.get("sector_pe") or {}
        return _ind("vs_industry", sc["vs_sector"], note="sector_pe", detail={
            "company_pe": sc.get("company_pe"), "group_pe": spe.get("current"), "group": "sector",
            "group_percentile": spe.get("percentile")})
    return _missing("vs_industry", "loss_making" if sc.get("company_pe") is None else "no_data")


# ---------------------------------------------------------------------------- quality
def _level(key, years, field):
    vals = [_f(y.get(field)) for y in years]
    vals = [v for v in vals if v is not None]
    if not vals:
        return _missing(key, "no_data")
    return _ind(key, statistics.median(vals), detail={"years": len(vals), "latest": _f(years[-1].get(field))})


def _trend(key, years, field, clip=None):
    """Latest value minus the value three fiscal years earlier (clipped to +-clip, e.g. ROIC of a net-cash
    company, where 150% -> 120% is noise rather than decline)."""
    b = _years_back(years)
    a0, b0 = _f(years[-1].get(field)) if years else None, _f(b.get(field)) if b else None
    if a0 is None or b0 is None:
        return _missing(key, "short_history" if b is None else "no_data")
    lim = (lambda v: max(-clip, min(clip, v))) if clip else (lambda v: v)
    return _ind(key, lim(a0) - lim(b0), detail={"latest": a0, "earlier": b0, "from": b["label"],
                                                "to": years[-1]["label"]})


def quality(r, kind):
    years, out = r.get("years") or [], {}
    L = years[-1] if years else {}
    if kind == "financial":
        out["roe_level"] = _level("roe_level", years, "roe")
        out["roe_trend"] = _trend("roe_trend", years, "roe", clip=0.5)
    else:
        out["roic_level"] = _level("roic_level", years, "roic")
        out["roic_trend"] = _trend("roic_trend", years, "roic", clip=0.5)
        out["op_margin_trend"] = _trend("op_margin_trend", years, "operating_margin")
        gms = [_f(y.get("gross_margin")) for y in years]
        gms = [v for v in gms if v is not None]
        out["gross_margin_stability"] = (_ind("gross_margin_stability", statistics.pstdev(gms),
                                              detail={"years": len(gms), "min": min(gms), "max": max(gms)})
                                         if len(gms) >= 3 else _missing("gross_margin_stability", "short_history"))
        out["fcf_conversion"] = _fcf_conversion(years, L)
    sbc = _f(L.get("sbc_pct"))
    out["sbc_burden"] = _ind("sbc_burden", sbc) if sbc is not None else _missing("sbc_burden", "no_data")
    return out


def _fcf_conversion(years, L):
    key = "fcf_conversion"
    if _f(L.get("fcf")) is not None and L["fcf"] < 0:
        return _ind(key, score=-2, note="negative_fcf", detail={"fcf": L["fcf"], "fy": L.get("label")})
    vals = [_f(y.get("fcf_conversion")) for y in years[-3:]]
    vals = [v for v in vals if v is not None]
    if not vals:
        return _missing(key, "loss_making")
    return _ind(key, statistics.median(vals), detail={"years": len(vals)})


# ---------------------------------------------------------------------------- growth
def growth(r, kind):
    years, cg, out = r.get("years") or [], r.get("cagr") or {}, {}
    L = years[-1] if years else {}
    rc = _f(cg.get("revenue"))
    out["revenue_cagr"] = (_ind("revenue_cagr", rc, detail={"years": len(years) - 1}) if rc is not None
                           else _missing("revenue_cagr", "short_history" if len(years) < 2 else "no_data"))
    ry = _f(L.get("revenue_yoy"))
    out["revenue_recent"] = (_ind("revenue_recent", ry, detail={"fy": L.get("label")}) if ry is not None
                             else _missing("revenue_recent", "short_history" if len(years) < 2 else "no_data"))
    fg, fys = _fwd_revenue_growth(r)
    out["revenue_forward"] = (_ind("revenue_forward", fg, detail={"fys": fys}) if fg is not None
                              else _missing("revenue_forward", "no_estimates"))
    g, fy0, fy1 = _fwd_eps_growth(r)
    if g is not None:
        out["eps_forward"] = _ind("eps_forward", g, detail={"fy_from": fy0, "fy_to": fy1})
    elif _f(cg.get("eps")) is not None:
        out["eps_forward"] = _ind("eps_forward", cg["eps"], note="historical_eps", detail={"years": len(years) - 1})
    else:
        out["eps_forward"] = _missing("eps_forward", "no_estimates" if not _estimates(r) else "loss_making")
    return out


# ---------------------------------------------------------------------------- financial health
def health(r, kind):
    years, out = r.get("years") or [], {}
    L = years[-1] if years else {}
    pio = r.get("piotroski")
    if pio and (pio.get("out_of") or 0) >= 7:
        out["piotroski"] = _ind("piotroski", round(pio["score"] / pio["out_of"] * 9, 1),
                                detail={"score": pio["score"], "out_of": pio["out_of"], "fy": pio.get("year")})
    else:
        out["piotroski"] = _missing("piotroski", "short_history")
    if kind == "financial":
        eta = None if not L.get("total_assets") or L.get("equity") is None else L["equity"] / L["total_assets"]
        out["equity_to_assets"] = _ind("equity_to_assets", eta) if eta is not None else _missing("equity_to_assets", "no_data")
    else:
        out["net_debt_ebitda"] = _net_debt_ebitda(L, kind)
        out["interest_coverage"] = _coverage(L)
        out["altman"] = _altman(r.get("altman"))
        out["current_ratio"] = _current_ratio(L)
    sh = [_f(y.get("shares_yoy")) for y in years]
    sh = [v for v in sh if v is not None]
    out["dilution"] = (_ind("dilution", sum(sh) / len(sh), detail={"years": len(sh)}) if sh
                       else _missing("dilution", "short_history"))
    return out


def _net_debt_ebitda(L, kind):
    key, band = "net_debt_ebitda", "net_debt_ebitda_reit" if kind == "reit" else None
    nd, eb = _f(L.get("net_debt")), _f(L.get("ebitda"))
    note = "reit" if kind == "reit" else None
    if nd is None:
        return _missing(key, "no_data", band)
    if eb is None or eb <= 0:
        return _ind(key, band=band, score=-2 if nd > 0 else 0, note="ebitda_not_positive", detail={"net_debt": nd})
    return _ind(key, nd / eb, band=band, note="net_cash" if nd < 0 else note, detail={"net_debt": nd, "ebitda": eb})


def _coverage(L):
    key = "interest_coverage"
    ie, ebit = _f(L.get("interest_expense")), _f(L.get("ebit"))
    if not ie or ie <= 0:
        if (_f(L.get("debt")) or 0) <= 0 or (_f(L.get("net_debt")) or 0) < 0:
            return _ind(key, score=2, note="no_interest")
        return _missing(key, "no_data")
    if ebit is None:
        return _missing(key, "no_data")
    return _ind(key, ebit / ie)


def _altman(alt):
    key = "altman"
    if not alt:
        return _missing(key, "no_data")
    zones = [z for z in (alt.get("z_zone"), alt.get("z2_zone")) if z]
    if not zones:
        return _missing(key, "no_data")
    score = -2 if len(zones) == 2 and all(z == "distress" for z in zones) else ALTMAN_SCORES[zones[0]]
    value = alt.get("z") if alt.get("z") is not None else alt.get("z_double_prime")
    ind = _ind(key, _f(value), score=score, detail={"z": alt.get("z"), "z_zone": alt.get("z_zone"),
                                                     "z2": alt.get("z_double_prime"), "z2_zone": alt.get("z2_zone")})
    ind["unit"] = "num"
    return ind


def _current_ratio(L):
    key = "current_ratio"
    cr = _f(L.get("current_ratio"))
    if cr is None:
        return _missing(key, "no_data")
    ind = _ind(key, cr)
    # a current ratio under 1 means little for a company with net cash or strong free cash flow
    if ind["score"] < 0 and ((_f(L.get("net_debt")) or 0) < 0 or (_f(L.get("fcf_margin")) or 0) >= 0.10):
        ind["score"], ind["note"] = 0, "cash_rich"
    return ind


# ---------------------------------------------------------------------------- red lines
def red_lines(r, kind):
    years = r.get("years") or []
    L = years[-1] if years else {}
    out = []
    if kind == "financial":
        if _f(L.get("equity")) is not None and L["equity"] <= 0:
            out.append({"type": "negative_equity", "detail": {"equity": L["equity"]}})
        return out
    alt = r.get("altman") or {}
    if alt.get("z_zone") == "distress" and alt.get("z2_zone") == "distress":
        out.append({"type": "altman_distress", "detail": {"z": alt.get("z"), "z2": alt.get("z_double_prime")}})
    ie, ebit, nd = _f(L.get("interest_expense")), _f(L.get("ebit")), _f(L.get("net_debt"))
    if ie and ie > 0 and ebit is not None and nd is not None and nd > 0 and ebit / ie < 1.5:
        out.append({"type": "interest_coverage", "detail": {"coverage": ebit / ie}})
    fcfs = [_f(y.get("fcf")) for y in years[-2:]]
    if len(fcfs) == 2 and all(v is not None and v < 0 for v in fcfs) and nd is not None and nd > 0:
        out.append({"type": "cash_burn", "detail": {"fcf": fcfs, "net_debt": nd}})
    return out


# ---------------------------------------------------------------------------- assembly
PILLAR_FUNCS = {"valuation": valuation, "quality": quality, "growth": growth, "health": health}


def _pillar(name, inds, kind):
    w = WEIGHTS[kind][name]
    # indicators of the general set that do not apply to this company type, for display
    for k in WEIGHTS["general"][name]:
        if k not in w and k not in inds:
            inds[k] = _ind(k, status="n/a", note="financial")
    rows = []
    for k, ind in inds.items():
        ind["pillar"] = name
        ind["weight"] = w.get(k, 0.0) if ind["status"] != "n/a" else 0.0
        rows.append(ind)
    total_w = sum(i["weight"] for i in rows)
    for i in rows:
        i["weight_share"] = i["weight"] / total_w if total_w else 0.0
        i["contribution"] = i["weight_share"] * i["score"]
    order = list(w) + [k for k in WEIGHTS["general"][name] if k not in w]
    rows.sort(key=lambda i: order.index(i["key"]) if i["key"] in order else len(order))
    ok_w = sum(i["weight"] for i in rows if i["status"] == "ok")
    score = sum(i["contribution"] for i in rows)
    return {"score": round(score, 2), "weight": PILLAR_WEIGHTS[name],
            "contribution": round(PILLAR_WEIGHTS[name] * score, 3),
            "coverage": ok_w / total_w if total_w else 0.0, "available": ok_w > 0, "indicators": rows}


def label_of(s):
    for bound, name in LABELS:
        if s > bound or (bound < 0 and s >= bound):
            return name
    return "Bearish"


def _sign(x, dead=PILLAR_DEADBAND):
    return 0 if abs(x) <= dead else (1 if x > 0 else -1)


def _conflicts(p, inds, r, caps):
    out = []
    v, q, g = p["valuation"]["score"], p["quality"]["score"], p["growth"]["score"]
    if v >= VALUE_TRAP_VALUATION and (q + g) / 2 <= VALUE_TRAP_BUSINESS:
        out.append({"type": "value_trap", "values": {"valuation": v, "quality": q, "growth": g}})
    if q >= 1.0 and v <= -1.0:
        out.append({"type": "quality_premium", "values": {"valuation": v, "quality": q}})

    def wmean(keys):
        xs = [(inds[k]["weight"], inds[k]["score"]) for k in keys if k in inds and inds[k]["status"] == "ok"]
        tw = sum(w for w, _ in xs)
        return sum(w * s for w, s in xs) / tw if tw else None
    rel = wmean(("fwd_pe_position", "fwd_ev_position", "vs_industry", "pb_vs_history"))
    absv = wmean(("implied_growth_gap", "dcf_margin"))
    if rel is not None and absv is not None and abs(rel) >= 1 and abs(absv) >= 1 and rel * absv < 0:
        out.append({"type": "methods_disagree", "values": {"relative": round(rel, 2), "absolute": round(absv, 2)}})
    for k in ("fwd_pe_position", "fwd_ev_position"):
        if k in inds and inds[k]["note"] == "growth_slowdown":
            out.append({"type": "growth_slowdown", "values": dict(inds[k]["detail"], indicator=k)})
            break
    vi = inds.get("vs_industry")
    pctl = (vi or {}).get("detail", {}).get("group_percentile")
    if vi and vi["status"] == "ok" and vi["score"] > 0 and pctl is not None and pctl >= 0.8:
        out.append({"type": "group_expensive", "values": {"percentile": pctl, "group": vi["detail"].get("group")}})
    eb = (r.get("analyst") or {}).get("eps_basis")
    if eb and eb.get("gap") is not None and eb["gap"] > 0.10:
        out.append({"type": "adjusted_eps", "values": eb})
    for c in caps:
        if c["type"] != "value_trap":
            out.append({"type": "red_line", "values": c})
    return out


def _confidence(p, inds, total, r, caps):
    reasons = []
    coverage = sum(PILLAR_WEIGHTS[n] * p[n]["coverage"] for n in PILLARS)
    s = _sign(total, 0.4)
    if s:
        agree = sum(PILLAR_WEIGHTS[n] for n in PILLARS if _sign(p[n]["score"]) == s)
    else:
        agree = sum(PILLAR_WEIGHTS[n] for n in PILLARS if abs(p[n]["score"]) <= 0.5)
    vs = _sign(p["valuation"]["score"])
    strong = [i for k, i in inds.items() if i["pillar"] == "valuation" and i["status"] == "ok" and abs(i["score"]) >= 1]
    methods = (sum(1 for i in strong if (i["score"] > 0) == (vs > 0)) / len(strong)) if vs and len(strong) >= 2 else None
    years = r.get("years") or []
    issues = []
    if len(years) < 4:
        issues.append("short_history")
    eb = (r.get("analyst") or {}).get("eps_basis")
    if eb and eb.get("gap") is not None and eb["gap"] > 0.10:
        issues.append("adjusted_eps")
    route = (((r.get("meta") or {}).get("connection") or {}).get("route") or "official")
    if not route.startswith("official"):
        issues.append("proxy_data")
    if caps:
        issues.append("capped")
    if coverage < COVERAGE_LOW or agree < AGREEMENT_LOW or len(years) < 3:
        level = "low"
    elif (coverage >= COVERAGE_HIGH and agree >= AGREEMENT_HIGH and (methods is None or methods >= 0.67)
          and not issues):
        level = "high"
    else:
        level = "medium"
    reasons = [{"code": "coverage", "value": coverage}, {"code": "agreement", "value": agree}]
    if methods is not None:
        reasons.append({"code": "methods", "value": methods})
    reasons += [{"code": i} for i in issues]
    return {"level": level, "coverage": coverage, "agreement": agree, "methods_agreement": methods,
            "issues": issues, "reasons": reasons}


def _value_range(r):
    pr, d = r.get("price_range") or {}, r.get("dcf") or {}
    price = _f((r.get("current") or {}).get("price"))
    now = next((pt for pt in pr.get("forward") or [] if pt.get("at") == "now"), None)
    if now and now.get("pe"):
        lo, mid, hi, basis = now["pe"]["low"], now["pe"]["base"], now["pe"]["high"], "fwd_pe"
    elif d.get("range_low") is not None and (d.get("value_per_share") or 0) > 0:
        lo, mid, hi, basis = d["range_low"], d["value_per_share"], d["range_high"], "dcf"
    else:
        return None
    return {"basis": basis, "low": lo, "mid": mid, "high": hi, "price": price,
            "mid_vs_price": (mid / price - 1) if mid and price else None}


NOT_SCORED = ("analyst_targets", "week52", "volatility", "peers", "macro")


def score(r):
    kind = r.get("sector_kind") or "general"
    wkind = "financial" if kind == "financial" else "general"
    pillars, inds = {}, {}
    for name in PILLARS:
        got = PILLAR_FUNCS[name](r, kind)
        pillars[name] = _pillar(name, got, wkind)
        inds.update({i["key"]: i for i in pillars[name]["indicators"]})
    raw = sum(PILLAR_WEIGHTS[n] * pillars[n]["score"] for n in PILLARS)
    caps = [{"type": c["type"], "detail": c["detail"]} for c in red_lines(r, kind)]
    v, q, g = (pillars[n]["score"] for n in ("valuation", "quality", "growth"))
    if v >= VALUE_TRAP_VALUATION and (q + g) / 2 <= VALUE_TRAP_BUSINESS:
        caps.append({"type": "value_trap", "detail": {"valuation": v, "quality": q, "growth": g}})
    total = round(min(raw, CAP) if caps else raw, 2)
    return {
        "version": RULES_VERSION, "kind": wkind, "score": total, "raw_score": round(raw, 2), "label": label_of(total),
        "capped": bool(caps) and raw > CAP, "caps": caps, "cap_limit": CAP,
        "pillar_order": list(PILLARS), "pillars": pillars,
        "confidence": _confidence(pillars, inds, total, r, caps),
        "conflicts": _conflicts(pillars, inds, r, caps),
        "value_range": _value_range(r),
        "not_scored": list(NOT_SCORED),
        "labels": [{"label": n, "above": b} for b, n in LABELS],
    }


# ---------------------------------------------------------------------------- report section
PILLAR_NAMES = {"valuation": "Valuation", "quality": "Quality", "growth": "Growth", "health": "Financial health"}
IND_NAMES = {
    "fwd_pe_position": "Forward P/E vs its 3-year range", "fwd_ev_position": "Forward EV/EBITDA vs its 3-year range",
    "pb_vs_history": "P/B vs its fiscal-year-end median", "implied_growth_gap": "Reverse DCF: implied minus expected growth",
    "dcf_margin": "DCF value vs price", "vs_industry": "P/E vs industry",
    "roic_level": "ROIC (median)", "roe_level": "ROE (median)", "roic_trend": "ROIC change over 3 years",
    "roe_trend": "ROE change over 3 years", "op_margin_trend": "Operating margin change over 3 years",
    "gross_margin_stability": "Gross margin stability (std. dev.)", "fcf_conversion": "FCF / net income (3-yr median)",
    "sbc_burden": "Stock comp % revenue", "revenue_cagr": "Revenue CAGR", "revenue_recent": "Revenue growth, last FY",
    "revenue_forward": "Expected revenue growth (analysts)", "eps_forward": "Expected EPS growth next FY (analysts)",
    "net_debt_ebitda": "Net debt / EBITDA", "interest_coverage": "Interest coverage (EBIT / interest)",
    "altman": "Altman Z zone", "piotroski": "Piotroski F-score (of 9)", "current_ratio": "Current ratio",
    "dilution": "Share count change per year", "equity_to_assets": "Equity / assets",
}
NOTES = {
    "trailing_history": "fallback: trailing multiple vs its fiscal-year-end median (no forward range)",
    "growth_slowdown": "capped at +1: expected EPS growth is under half the historical rate",
    "historical_growth": "compared with historical revenue CAGR (no analyst estimates)",
    "historical_eps": "fallback: historical EPS CAGR (no analyst estimates)",
    "sector_pe": "compared with the sector (no industry P/E)",
    "implied_below_range": "price implies FCF shrinking more than 50% a year",
    "implied_above_range": "price implies FCF growth above 100% a year",
    "negative_fcf": "free cash flow negative in the last fiscal year",
    "net_cash": "net cash", "reit": "REIT thresholds (leverage is structurally higher)",
    "ebitda_not_positive": "EBITDA not positive", "no_interest": "no interest expense",
    "cash_rich": "below 1 but offset by net cash or FCF margin >= 10%",
    "no_estimates": "no analyst estimates", "loss_making": "earnings not positive", "no_band": "no usable multiple history",
    "no_dcf": "DCF not applicable", "dcf_negative": "DCF value is not positive (cash flows negative)", "no_market": "no industry data (--no-market or unavailable)",
    "short_history": "not enough fiscal years", "no_data": "no data", "financial": "not used for banks / insurers",
}
CAP_TEXT = {
    "value_trap": "value trap: valuation is cheap while quality and growth are weak",
    "altman_distress": "Altman Z and Z'' both in the distress zone",
    "interest_coverage": "EBIT covers interest less than 1.5x with net debt",
    "cash_burn": "free cash flow negative two years running with net debt",
    "negative_equity": "shareholders' equity not positive",
}
CONFLICT_TEXT = {
    "value_trap": "Cheap valuation with weak quality and growth: cheap stocks are often cheap for a reason.",
    "quality_premium": "Strong quality but expensive valuation: a good business already priced as one.",
    "methods_disagree": "Relative methods (multiples vs own history and industry) and absolute methods (DCF, reverse DCF) "
                        "point opposite ways; the gap usually comes from the growth assumption.",
    "growth_slowdown": "Today's multiple is low in its history, but expected EPS growth is under half the historical "
                       "rate, so the multiple may not return to its median.",
    "group_expensive": "Cheap against its group, but the group itself sits in the top fifth of its own P/E history.",
    "adjusted_eps": "Analysts' EPS is about {gap} above reported EPS (adjusted basis), so forward P/E looks lower than GAAP P/E.",
    "red_line": "Balance-sheet red line: {what}.",
}


def _sc(x):
    return "0" if x == 0 else f"{x:+d}"


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fmt_value(v, unit):
    if v is None:
        return "n/a"
    if unit == "pct":
        return f"{v * 100:.1f}%"
    if unit == "pctile":
        return f"{_ordinal(round(v * 100))} percentile"
    if unit == "pt":
        return f"{v * 100:+.1f}pt"
    if unit == "pp":
        return f"{v * 100:.1f}pt"
    if unit == "x":
        return f"{v:.2f}x"
    return f"{v:g}" if float(v).is_integer() else f"{v:.2f}"


def rule_text(ind):
    """The indicator's bands, e.g. "<5%: -2 / 5% to 8%: -1 / ... / >=20%: +2"."""
    if ind["key"] == "altman":
        return "safe +1, grey 0, distress -1 (Z and Z'' both distress: -2)"
    cuts, scores, unit = ind.get("cuts"), ind.get("scores"), ind.get("unit")
    if not cuts:
        return ""

    def f(c):
        if unit in ("pct", "pctile"):
            return f"{c * 100:g}%"
        if unit in ("pt", "pp"):
            return f"{c * 100:g}pt"
        return f"{c:g}x" if unit == "x" else f"{c:g}"
    parts = [f"<{f(cuts[0])}: {_sc(scores[0])}"]
    parts += [f"{f(a)} to {f(b)}: {_sc(s)}" for a, b, s in zip(cuts, cuts[1:], scores[1:])]
    parts.append(f">={f(cuts[-1])}: {_sc(scores[-1])}")
    return " / ".join(parts)


def render(s):
    """The report's "Fundamental score" section (markdown)."""
    out = [f"\n## Fundamental score (rules v{s['version']})"]
    c = s["confidence"]
    head = f"**{s['score']:+.2f} -> {s['label']}**, confidence {c['level']}"
    if s["caps"]:
        head += f" (capped at {s['cap_limit']:+.1f} from {s['raw_score']:+.2f})" if s["capped"] else " (cap rule triggered)"
    out.append(head + ". Score = 0.35 x valuation + 0.25 x quality + 0.20 x growth + 0.20 x financial health; "
               "each pillar is -2..+2. Labels: > +1.2 Bullish, > +0.4 Moderately bullish, -0.4..+0.4 Neutral, "
               "< -0.4 Moderately bearish, < -1.2 Bearish. A rule-based label, not a recommendation.")
    out.append("")
    out.append("| Pillar | Weight | Score | Contribution | Data coverage |")
    out.append("|---|---|---|---|---|")
    for n in s["pillar_order"]:
        p = s["pillars"][n]
        out.append(f"| {PILLAR_NAMES[n]} | {p['weight'] * 100:.0f}% | {p['score']:+.2f} | {p['contribution']:+.2f} | "
                   f"{p['coverage'] * 100:.0f}% |")
    out.append("")
    out.append("| Pillar | Indicator | Value | Score | Weight | Rule |")
    out.append("|---|---|---|---|---|---|")
    for n in s["pillar_order"]:
        for i in s["pillars"][n]["indicators"]:
            if i["status"] == "n/a":
                continue
            val = fmt_value(i["value"], i["unit"]) if i["status"] == "ok" else "n/a"
            if i["note"] == "dcf_negative":
                val = "<= -100%"
            note = f" ({NOTES.get(i['note'], i['note'])})" if i["note"] else ""
            sc = _sc(i["score"]) if i["status"] == "ok" else "0 (missing)"
            out.append(f"| {PILLAR_NAMES[n]} | {IND_NAMES[i['key']]}{note} | {val} | {sc} | "
                       f"{i['weight_share'] * 100:.0f}% | {rule_text(i)} |")
    if s["caps"]:
        out.append("\n**Caps:** " + "; ".join(CAP_TEXT.get(x["type"], x["type"]) for x in s["caps"]) +
                   f". The total is held at {s['cap_limit']:+.1f} (Neutral) at most.")
    if s["conflicts"]:
        out.append("\n**Conflicts:**")
        for x in s["conflicts"]:
            t = CONFLICT_TEXT[x["type"]]
            if x["type"] == "adjusted_eps":
                t = t.format(gap=f"{x['values']['gap'] * 100:.0f}%")
            elif x["type"] == "red_line":
                t = t.format(what=CAP_TEXT.get(x["values"]["type"], x["values"]["type"]))
            out.append(f"- {t}")
    reasons = [f"data coverage {c['coverage'] * 100:.0f}%", f"pillar agreement {c['agreement'] * 100:.0f}%"]
    if c["methods_agreement"] is not None:
        reasons.append(f"valuation methods agreeing {c['methods_agreement'] * 100:.0f}%")
    reasons += [{"short_history": "fewer than 4 fiscal years", "adjusted_eps": "analyst EPS on an adjusted basis",
                 "proxy_data": "data from a third-party proxy", "capped": "a cap rule triggered"}[i] for i in c["issues"]]
    out.append(f"\nConfidence {c['level']}: " + "; ".join(reasons) + ".")
    vr = s.get("value_range")
    if vr:
        src = "forward P/E now (25th / median / 75th percentile multiple)" if vr["basis"] == "fwd_pe" else "DCF range"
        vs = f" ({vr['mid_vs_price'] * 100:+.1f}% vs price)" if vr["mid_vs_price"] is not None else ""
        out.append(f"Value range from the {src}: {vr['low']:,.2f} / {vr['mid']:,.2f} / {vr['high']:,.2f}{vs}.")
    out.append("Not scored: analyst price targets (optimistic, and built from the same forward EPS), the 52-week and "
               "volatility ranges (price moves, not value), peers (auto-peers can include foreign listings) and macro "
               "releases (context; rates already enter through the DCF discount rate). Missing data counts as 0.")
    return "\n".join(out)
