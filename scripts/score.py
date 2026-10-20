"""
Fundamental score: valuation, quality, growth and financial health, each scored -2..+2 from a few
indicators with fixed thresholds, then weighted into one score on the same -2..+2 scale and the same
five labels as the technical-analysis scorecard (Bearish .. Bullish).

- Each indicator maps one number to -2..+2 through the cut points below (a value equal to a cut point
  takes the band of higher values, e.g. exactly the 25th percentile scores +1, not +2). A pillar is the
  weighted mean of its indicators.
- Banks and insurers, REITs and utilities have their own indicator sets and weights (WEIGHTS); the general
  indicators they leave out are shown as not applicable.
- An indicator that cannot be computed (no data, a loss, a skipped DCF) counts as 0 and keeps its weight,
  so missing data pulls the pillar toward 0 and lowers the confidence.
- Two caps keep the total at Neutral (+0.4) at most: a balance-sheet red line, and a "value trap"
  (cheap valuation with weak quality and growth). Separately, a forward-multiple position scores at most
  +1 after historical EPS growth above 15% when expected EPS growth is under half of it.
- Rates enter only through the DCF's Treasury-linked discount rate; macro releases are not scored.

score(r) works on the dict analyze() returns and makes no API calls. render(s) prints the report
section. The rules are documented in references/metrics.md section 12; every change to a threshold or
weight bumps RULES_VERSION. The score is a rule-based label, not a recommendation.
"""
from __future__ import annotations

import bisect
import statistics

RULES_VERSION = "1.0"

PILLARS = ("valuation", "quality", "growth", "health")
PILLAR_WEIGHTS = {"valuation": 0.35, "quality": 0.25, "growth": 0.20, "health": 0.20}

# Indicator weights inside each pillar, by company type (analyze.py's sector_kind). An indicator listed for
# "general" but not for the company's type is shown as not applicable.
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
    # REITs: depreciation makes GAAP ROIC, FCF / net income and EBIT coverage misleading; current ratio and
    # Altman Z mean little for a landlord. Coverage is EBITDA / interest.
    "reit": {
        "valuation": {"fwd_pe_position": 0.30, "fwd_ev_position": 0.20, "implied_growth_gap": 0.20,
                      "dcf_margin": 0.15, "vs_industry": 0.15},
        "quality": {"roic_trend": 0.25, "op_margin_trend": 0.30, "gross_margin_stability": 0.25, "sbc_burden": 0.20},
        "growth": {"revenue_cagr": 0.30, "revenue_recent": 0.20, "revenue_forward": 0.30, "eps_forward": 0.20},
        "health": {"net_debt_ebitda": 0.30, "interest_coverage": 0.25, "piotroski": 0.25, "dilution": 0.20},
    },
    # Utilities: regulated returns are judged on ROE; capex above operating cash flow (negative FCF), a current
    # ratio under 1 and a low Altman Z are normal.
    "utility": {
        "valuation": {"fwd_pe_position": 0.30, "fwd_ev_position": 0.20, "implied_growth_gap": 0.20,
                      "dcf_margin": 0.15, "vs_industry": 0.15},
        "quality": {"roe_level": 0.35, "roe_trend": 0.20, "op_margin_trend": 0.20, "gross_margin_stability": 0.10,
                    "sbc_burden": 0.15},
        "growth": {"revenue_cagr": 0.30, "revenue_recent": 0.20, "revenue_forward": 0.30, "eps_forward": 0.20},
        "health": {"net_debt_ebitda": 0.30, "interest_coverage": 0.25, "piotroski": 0.25, "dilution": 0.20},
    },
}
NA_NOTE = {"financial": "na_financial", "reit": "na_reit", "utility": "na_utility"}

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
    "net_debt_ebitda_utility": ((3.0, 4.5, 6.5, 8.0), DOWN, "x"),
    "interest_coverage": ((2.0, 4.0, 8.0, 20.0), UP, "x"),
    "interest_coverage_reit": ((2.0, 3.0, 4.0, 6.0), UP, "x"),       # EBITDA / interest
    "interest_coverage_utility": ((1.5, 2.0, 3.0, 4.5), UP, "x"),
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
BASIS_GAP = 0.10              # analysts' EPS / EBITDA this far from reported: the forward range mixes bases
COVERAGE_RED_LINE = 1.5       # interest covered less than this in each of the last two fiscal years
CYCLICAL_MARGIN_RATIO = 1.5   # latest operating margin >= 1.5x its median (and 5pt above it) while
CYCLICAL_MARGIN_GAP = 0.05    # ... analysts expect EPS to fall: possibly a cyclical peak
COVERAGE_LOW, COVERAGE_HIGH = 0.6, 0.85
AGREEMENT_LOW, AGREEMENT_HIGH = 0.5, 0.7
METHODS_HIGH = 2 / 3          # at least two of three strong valuation indicators agree with the pillar
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
    """The fiscal year n years before the latest, or None when the history is shorter."""
    return years[-1 - n] if len(years) > n else None


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


def _fwd_not_positive(r, field):
    """True when analysts expect a loss (eps_avg) or negative EBITDA (ebitda_avg) in the fiscal year in
    progress or the next one."""
    return any(v is not None and v <= 0 for v in (_f(e.get(field)) for e in _estimates(r)[:2]))


def _currency_mismatch(r):
    """(statement currency, price currency) when they differ, e.g. an ADR of a company reporting in JPY:
    every ratio that mixes the price with statement figures is then off by the exchange rate."""
    years = r.get("years") or []
    rep = years[-1].get("currency") if years else None
    px = (r.get("profile") or {}).get("currency")
    return (rep, px) if rep and px and rep != px else None


def _basis_gap(r, basis_key):
    """How far analysts' figures for the last reported year sit from the reported ones (eps_basis /
    ebitda_basis), when the gap is large enough to mean another basis (usually adjusted, non-GAAP)."""
    gap = _f(((r.get("analyst") or {}).get(basis_key) or {}).get("gap"))
    return gap if gap is not None and abs(gap) > BASIS_GAP else None


# ---------------------------------------------------------------------------- valuation
def _position(band, key):
    return _ind(key, band["now_pct"], detail={"now": band["now"], "p25": band["p25"], "median": band["median"],
                                              "p75": band["p75"], "from": band["from"], "to": band["to"]})


def _multiple_position(r, key, band_key, hist_key, basis_key, est_field):
    """Where today's forward multiple sits in its 3-year history. Falls back to the trailing multiple vs its
    fiscal-year-end median when there is no forward range, or when analysts' figures are on another basis
    than the reported ones the range's history is built from (adjusted EPS). Never falls back when the share
    basis or the price history is broken, or when price and statements are in different currencies."""
    pr = r.get("price_range") or {}
    band, gap, ccy = pr.get(band_key), _basis_gap(r, basis_key), _currency_mismatch(r)
    if key == "fwd_ev_position" and ccy:  # EV adds price-currency market cap to statement-currency net debt
        return _missing(key, "currency")
    if band and gap is None:
        if band.get("now_pct") is not None:
            return _position(band, key)
        return _missing(key, "loss_making")  # a range exists, but today's next-12-month figure is not positive
    if _fwd_not_positive(r, est_field):
        return _missing(key, "loss_making")
    if pr.get("band_problem") in ("share_basis", "price_jump"):
        return _missing(key, pr["band_problem"])
    if ccy:
        return _missing(key, "currency")
    h = (r.get("history_compare") or {}).get(hist_key) or {}
    if h.get("vs_median") is not None and (h.get("n") or 0) >= 3:
        return _ind(key, h["vs_median"], band="trailing_vs_median",
                    note="adjusted_basis" if gap is not None else "trailing_history",
                    detail={"now": h["current"], "median": h["median"], "n": h["n"], "basis_gap": gap})
    if gap is not None:
        return _missing(key, "adjusted_basis")
    if not _estimates(r):
        return _missing(key, "no_estimates")
    return _missing(key, "no_band" if pr.get("band_note") else "no_data")


def _slowdown_cap(ind, r):
    """A cheap multiple after fast growth often reflects a slowdown the market expects to last: cap +2 at +1."""
    if ind["status"] != "ok" or ind["score"] < 2:
        return
    g, fy0, fy1 = _fwd_eps_growth(r)
    hist = _f((r.get("cagr") or {}).get("eps"))
    if g is not None and hist is not None and hist > SLOWDOWN_HIST_MIN and g < hist * SLOWDOWN_RATIO:
        if ind["note"]:
            ind["detail"]["base_note"] = ind["note"]  # e.g. trailing_history: keep saying what the value is
        ind["score"], ind["note"] = 1, "growth_slowdown"
        ind["detail"].update(capped_from=2, eps_growth_next=g, eps_cagr=hist, fy_from=fy0, fy_to=fy1)


def valuation(r, kind):
    d, out = r.get("dcf") or {}, {}
    out["fwd_pe_position"] = _multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
    _slowdown_cap(out["fwd_pe_position"], r)
    if kind == "financial":
        out["pb_vs_history"] = _pb_vs_history(r)
    else:
        out["fwd_ev_position"] = _multiple_position(r, "fwd_ev_position", "ev_band", "ev_ebitda", "ebitda_basis",
                                                    "ebitda_avg")
        _slowdown_cap(out["fwd_ev_position"], r)
        out["implied_growth_gap"] = _implied_growth_gap(r, d)
        out["dcf_margin"] = _dcf_margin(r, d)
    out["vs_industry"] = _vs_industry(r)
    return out


def _pb_vs_history(r):
    key, problem = "pb_vs_history", (r.get("price_range") or {}).get("band_problem")
    if problem in ("share_basis", "price_jump"):
        return _missing(key, problem)
    if _currency_mismatch(r):
        return _missing(key, "currency")
    h = (r.get("history_compare") or {}).get("pb") or {}
    if h.get("vs_median") is None or (h.get("n") or 0) < 3:
        return _missing(key, "short_history")
    return _ind(key, h["vs_median"], detail={"now": h["current"], "median": h["median"], "n": h["n"]})


def _dcf_margin(r, d):
    key = "dcf_margin"
    if _currency_mismatch(r):
        return _missing(key, "currency")
    if "skipped" in d:  # starting FCF not positive: no DCF support for the price, so it counts as missing
        return _missing(key, "no_dcf")
    mos = _f(d.get("margin_of_safety"))
    if mos is None:
        return _missing(key, "no_data")
    vps = _f(d.get("value_per_share"))
    return _ind(key, mos, note="dcf_negative" if vps is not None and vps <= 0 else None,
                detail={"value": vps, "low": d.get("range_low"), "high": d.get("range_high")})


def _implied_growth_gap(r, d):
    """Growth the price implies (reverse DCF) minus the growth analysts expect (or history delivered)."""
    key = "implied_growth_gap"
    if _currency_mismatch(r):
        return _missing(key, "currency")
    if "skipped" in d:
        return _missing(key, "no_dcf")
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
    if _currency_mismatch(r):  # the company's P/E divides a price-currency market cap by statement earnings
        return _missing("vs_industry", "currency")
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
    if kind in ("financial", "utility"):
        out["roe_level"] = _level("roe_level", years, "roe")
        out["roe_trend"] = _trend("roe_trend", years, "roe", clip=0.5)
    if kind != "financial":
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
    est = _estimates(r)
    first = _f(est[0].get("eps_avg")) if est else None
    if g is not None:  # includes a swing to an expected loss next year (growth <= -100%, scores -2)
        out["eps_forward"] = _ind("eps_forward", g, detail={"fy_from": fy0, "fy_to": fy1})
    elif first is not None and first <= 0:  # a loss expected this year: growth is not meaningful
        out["eps_forward"] = _missing("eps_forward", "loss_making")
    elif _f(cg.get("eps")) is not None:
        out["eps_forward"] = _ind("eps_forward", cg["eps"], note="historical_eps", detail={"years": len(years) - 1})
    else:
        out["eps_forward"] = _missing("eps_forward", "no_estimates" if len(est) < 2 else "no_data")
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
        out["interest_coverage"] = _coverage(L, kind)
        if kind == "general":
            out["altman"] = _altman(r.get("altman"), _currency_mismatch(r))
            out["current_ratio"] = _current_ratio(L)
    sh = [_f(y.get("shares_yoy")) for y in years]
    sh = [v for v in sh if v is not None]
    out["dilution"] = (_ind("dilution", sum(sh) / len(sh), detail={"years": len(sh)}) if sh
                       else _missing("dilution", "short_history"))
    return out


def _net_debt_ebitda(L, kind):
    key = "net_debt_ebitda"
    band = {"reit": "net_debt_ebitda_reit", "utility": "net_debt_ebitda_utility"}.get(kind)
    kind_note = kind if band else None  # REITs and utilities: looser bands, say so
    nd, eb = _f(L.get("net_debt")), _f(L.get("ebitda"))
    if nd is None:
        return _missing(key, "no_data", band)
    if eb is None or eb <= 0:
        return _ind(key, band=band, score=-2 if nd > 0 else 0, note="ebitda_not_positive",
                    detail={"net_debt": nd, "base_note": kind_note})
    if nd < 0:
        return _ind(key, nd / eb, band=band, note="net_cash", detail={"net_debt": nd, "ebitda": eb, "base_note": kind_note})
    return _ind(key, nd / eb, band=band, note=kind_note, detail={"net_debt": nd, "ebitda": eb})


def _coverage_ratio(y, kind):
    """One fiscal year's interest cover: EBIT / interest, or EBITDA / interest for a REIT (its EBIT is after
    heavy property depreciation). None without a positive interest expense."""
    ie, num = _f(y.get("interest_expense")), _f(y.get("ebitda" if kind == "reit" else "ebit"))
    return num / ie if ie and ie > 0 and num is not None else None


def _coverage(L, kind):
    key = "interest_coverage"
    band = {"reit": "interest_coverage_reit", "utility": "interest_coverage_utility"}.get(kind)
    ie = _f(L.get("interest_expense"))
    if not ie or ie <= 0:
        debt, nd = _f(L.get("debt")), _f(L.get("net_debt"))
        if (debt is not None and debt <= 0) or (nd is not None and nd < 0):  # unknown debt is not zero debt
            return _ind(key, band=band, score=2, note="no_interest")
        return _missing(key, "no_data", band)
    cov = _coverage_ratio(L, kind)
    if cov is None:
        return _missing(key, "no_data", band)
    return _ind(key, cov, band=band, note={"reit": "ebitda_coverage", "utility": "utility"}.get(kind))


def _altman(alt, ccy=None):
    """Altman zone score. With statements in another currency than the price, Z (which divides market cap by
    liabilities) is off by the exchange rate, so only Z'' (book equity) is used."""
    key = "altman"
    if not alt:
        return _missing(key, "no_data")
    z, z_zone = (None, None) if ccy else (alt.get("z"), alt.get("z_zone"))
    zones = [zz for zz in (z_zone, alt.get("z2_zone")) if zz]
    if not zones:
        return _missing(key, "no_data")
    score = -2 if len(zones) == 2 and all(zz == "distress" for zz in zones) else ALTMAN_SCORES[zones[0]]
    value = z if z is not None else alt.get("z_double_prime")
    ind = _ind(key, _f(value), score=score, note="currency_z2" if ccy else None,
               detail={"z": z, "z_zone": z_zone, "z2": alt.get("z_double_prime"), "z2_zone": alt.get("z2_zone")})
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
    # Altman Z means little for REITs and utilities, and Z is off by the exchange rate when currencies differ
    if (kind == "general" and not _currency_mismatch(r)
            and alt.get("z_zone") == "distress" and alt.get("z2_zone") == "distress"):
        out.append({"type": "altman_distress", "detail": {"z": alt.get("z"), "z2": alt.get("z_double_prime")}})
    nd = _f(L.get("net_debt"))
    # two years running, so that a single year's one-off charge does not trip it
    covs = [_coverage_ratio(y, kind) for y in years[-2:]]
    if (nd is not None and nd > 0 and len(covs) == 2
            and all(c is not None and c < COVERAGE_RED_LINE for c in covs)):
        out.append({"type": "interest_coverage", "detail": {"coverage": covs, "basis": "ebitda" if kind == "reit" else "ebit"}})
    # REITs and utilities fund growth capex with debt and new shares, so for them only operating cash flow counts
    field = "fcf" if kind == "general" else "ocf"
    flows = [_f(y.get(field)) for y in years[-2:]]
    if len(flows) == 2 and all(v is not None and v < 0 for v in flows) and nd is not None and nd > 0:
        out.append({"type": "cash_burn", "detail": {field: flows, "net_debt": nd}})
    return out


# ---------------------------------------------------------------------------- assembly
PILLAR_FUNCS = {"valuation": valuation, "quality": quality, "growth": growth, "health": health}


def _pillar(name, inds, kind):
    """Weights the indicators of the company type's set; general-set indicators the type does not use are
    listed as not applicable (weight 0) for display."""
    w = WEIGHTS[kind][name]
    rows = []
    for k in list(w) + [k for k in WEIGHTS["general"][name] if k not in w]:
        if k in w:
            ind = inds.get(k) or _missing(k, "no_data")
            ind["weight"] = w[k] if ind["status"] != "n/a" else 0.0
        else:
            ind = _ind(k, status="n/a", note=NA_NOTE.get(kind))
            ind["weight"] = 0.0
        ind["pillar"] = name
        rows.append(ind)
    total_w = sum(i["weight"] for i in rows)
    for i in rows:
        i["weight_share"] = i["weight"] / total_w if total_w else 0.0
        i["contribution"] = i["weight_share"] * i["score"]
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


def _is_value_trap(v, q, g):
    # rounded: pillar scores carry two decimals, and e.g. (0.4 - 1.4) / 2 is -0.49999999999999994 in floats
    return v >= VALUE_TRAP_VALUATION and round((q + g) / 2, 6) <= VALUE_TRAP_BUSINESS


def _cyclical_peak(r):
    """The latest operating margin far above its own median while analysts expect EPS to fall: the trend,
    growth and DCF indicators may be reading a cyclical peak."""
    years = r.get("years") or []
    ms = [m for m in (_f(y.get("operating_margin")) for y in years) if m is not None]
    latest = _f(years[-1].get("operating_margin")) if years else None
    g = _fwd_eps_growth(r)[0]
    if latest is None or len(ms) < 4 or g is None or g >= 0:
        return None
    med = statistics.median(ms)
    if latest - med >= CYCLICAL_MARGIN_GAP and (med <= 0 or latest >= med * CYCLICAL_MARGIN_RATIO):
        return {"margin": latest, "median": med, "years": len(ms), "eps_growth_next": g}
    return None


def _conflicts(p, inds, r, caps):
    out = []
    v, q, g = p["valuation"]["score"], p["quality"]["score"], p["growth"]["score"]
    if _is_value_trap(v, q, g):
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
    if eb and eb.get("gap") is not None and eb["gap"] > BASIS_GAP:
        out.append({"type": "adjusted_eps", "values": eb})
    peak = _cyclical_peak(r)
    if peak:
        out.append({"type": "cyclical_peak", "values": peak})
    ccy = _currency_mismatch(r)
    if ccy:
        out.append({"type": "currency", "values": {"statements": ccy[0], "price": ccy[1]}})
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
    if eb and eb.get("gap") is not None and eb["gap"] > BASIS_GAP:
        issues.append("adjusted_eps")
    if _currency_mismatch(r):
        issues.append("currency")
    if _cyclical_peak(r):
        issues.append("cyclical_peak")
    route = (((r.get("meta") or {}).get("connection") or {}).get("route") or "official")
    if not route.startswith("official"):
        issues.append("proxy_data")
    if caps:
        issues.append("capped")
    if coverage < COVERAGE_LOW or agree < AGREEMENT_LOW or len(years) < 3:
        level = "low"
    elif (coverage >= COVERAGE_HIGH and agree >= AGREEMENT_HIGH and (methods is None or methods >= METHODS_HIGH - 1e-9)
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
    elif d.get("range_low") is not None and (d.get("value_per_share") or 0) > 0 and not _currency_mismatch(r):
        lo, mid, hi, basis = d["range_low"], d["value_per_share"], d["range_high"], "dcf"
    else:
        return None
    return {"basis": basis, "low": lo, "mid": mid, "high": hi, "price": price,
            "mid_vs_price": (mid / price - 1) if mid and price else None}


NOT_SCORED = ("analyst_targets", "week52", "volatility", "peers", "macro")


def score(r):
    kind = r.get("sector_kind") or "general"
    kind = kind if kind in WEIGHTS else "general"
    pillars, inds = {}, {}
    for name in PILLARS:
        got = PILLAR_FUNCS[name](r, kind)
        pillars[name] = _pillar(name, got, kind)
        inds.update({i["key"]: i for i in pillars[name]["indicators"]})
    raw = sum(PILLAR_WEIGHTS[n] * pillars[n]["score"] for n in PILLARS)
    caps = [{"type": c["type"], "detail": c["detail"]} for c in red_lines(r, kind)]
    v, q, g = (pillars[n]["score"] for n in ("valuation", "quality", "growth"))
    if _is_value_trap(v, q, g):
        caps.append({"type": "value_trap", "detail": {"valuation": v, "quality": q, "growth": g}})
    total = round(min(raw, CAP) if caps else raw, 2)
    return {
        "version": RULES_VERSION, "kind": kind, "score": total, "raw_score": round(raw, 2), "label": label_of(total),
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
    "adjusted_basis": "analysts' figures are on another basis than reported ones (usually adjusted), which the forward "
                      "range's history would mix: trailing multiple vs its fiscal-year-end median used instead",
    "growth_slowdown": "capped at +1: expected EPS growth is under half the historical rate",
    "historical_growth": "compared with historical revenue CAGR (no analyst estimates)",
    "historical_eps": "fallback: historical EPS CAGR (no usable analyst EPS estimates)",
    "sector_pe": "compared with the sector (no industry P/E)",
    "implied_below_range": "price implies FCF shrinking more than 50% a year",
    "implied_above_range": "price implies FCF growth above 100% a year",
    "negative_fcf": "free cash flow negative in the last fiscal year",
    "net_cash": "net cash", "reit": "REIT thresholds, since leverage is structurally higher",
    "utility": "utility thresholds, since regulated utilities carry structurally more debt",
    "ebitda_coverage": "EBITDA / interest, since a REIT's EBIT is after property depreciation",
    "ebitda_not_positive": "EBITDA not positive", "no_interest": "no interest expense",
    "cash_rich": "below 1 but offset by net cash or FCF margin >= 10%",
    "no_estimates": "no analyst estimates", "loss_making": "earnings not positive (reported or expected)",
    "no_band": "no usable multiple history",
    "share_basis": "statement share counts are not on today's basis (ADR ratio or unadjusted split), so the "
                   "multiple history is not comparable",
    "price_jump": "a one-day price fall of more than 50% or rise of more than 100% (possibly an unadjusted split), "
                  "so the multiple history is not comparable",
    "currency": "statements and price are in different currencies, so this ratio is off by the exchange rate",
    "currency_z2": "Z'' only: statements and price are in different currencies, which distorts Z",
    "no_dcf": "no DCF: starting FCF not positive", "dcf_negative": "DCF value is not positive (cash flows negative)",
    "no_market": "no industry data (--no-market or unavailable)",
    "short_history": "not enough fiscal years", "no_data": "no data",
    "na_financial": "not used for banks and insurers",
    "na_reit": "not used for REITs (depreciation and the business model distort it)",
    "na_utility": "not used for utilities (regulated and capital-heavy)",
}
# What the value column shows for an indicator scored from a condition rather than a number.
VALUE_TEXT = {"negative_fcf": "FCF < 0", "no_interest": "no interest", "ebitda_not_positive": "EBITDA <= 0",
              "implied_below_range": "< -50%/yr", "implied_above_range": "> 100%/yr", "dcf_negative": "<= -100%"}
CAP_TEXT = {
    "value_trap": "value trap: valuation is cheap while quality and growth are weak",
    "altman_distress": "Altman Z and Z'' both in the distress zone",
    "interest_coverage": "interest covered less than 1.5x (EBIT; EBITDA for REITs) in each of the last two fiscal "
                         "years, with net debt",
    "cash_burn": "free cash flow (operating cash flow for REITs and utilities) negative two years running, with net debt",
    "negative_equity": "shareholders' equity not positive",
}
CONFLICT_TEXT = {
    "value_trap": "Cheap valuation with weak quality and growth: cheap stocks are often cheap for a reason.",
    "quality_premium": "Strong quality but expensive valuation: a good business already priced as one.",
    "methods_disagree": "Relative methods (multiples vs own history and industry) and absolute methods (DCF, reverse DCF) "
                        "point opposite ways; the gap usually comes from the growth assumption.",
    "growth_slowdown": "Today's multiple is low in its history, but expected EPS growth is under half the historical "
                       "rate, so the multiple may not return to its median.",
    "group_expensive": "Cheap against its {group}, but the {group} itself sits in the top fifth of its own P/E history.",
    "adjusted_eps": "Analysts' EPS is about {gap} above reported EPS (adjusted basis), so forward P/E looks lower than GAAP P/E.",
    "cyclical_peak": "Operating margin ({margin}) is far above its {years}-year median ({median}) while analysts expect "
                     "EPS to fall ({growth}): rising margins, growth and the DCF may be reading a cyclical peak.",
    "currency": "Statements are in {statements} and the price in {price}: the DCF, reverse DCF, P/E vs industry, EV and "
                "trailing multiples and Altman Z (Z'' kept) are left out, since they would be off by the exchange rate.",
    "red_line": "Balance-sheet red line: {what}.",
}
ISSUE_TEXT = {"short_history": "fewer than 4 fiscal years", "adjusted_eps": "analyst EPS on an adjusted basis",
              "proxy_data": "data from a third-party proxy", "capped": "a red-line or value-trap cap triggered",
              "currency": "statements and price in different currencies",
              "cyclical_peak": "operating margin possibly at a cyclical peak"}


def conflict_text(x):
    v, t = x["values"], CONFLICT_TEXT[x["type"]]
    if x["type"] == "adjusted_eps":
        return t.format(gap=f"{v['gap'] * 100:.0f}%")
    if x["type"] == "red_line":
        return t.format(what=CAP_TEXT.get(v["type"], v["type"]))
    if x["type"] == "group_expensive":
        return t.format(group=v.get("group") or "group")
    if x["type"] == "cyclical_peak":
        return t.format(margin=f"{v['margin'] * 100:.1f}%", median=f"{v['median'] * 100:.1f}%", years=v["years"],
                        growth=f"{v['eps_growth_next'] * 100:+.0f}%")
    if x["type"] == "currency":
        return t.format(**v)
    return t


def _sc(x):
    return "0" if x == 0 else f"{x:+d}"


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def fmt_value(v, unit):
    if v is None:
        return "n/a"
    if unit == "pct":
        return f"{v * 100:.1f}%"
    if unit == "pctile":  # as the price-range section words it
        if v <= 0:
            return "below every day of its 3-year range"
        if v >= 1:
            return "above every day of its 3-year range"
        return f"{_ordinal(min(99, max(1, round(v * 100))))} percentile"
    if unit == "pt":
        t = f"{abs(v) * 100:.1f}"
        return f"{'' if float(t) == 0 else '+' if v > 0 else '-'}{t}pt"  # no sign on a change that rounds to zero
    if unit == "pp":
        return f"{v * 100:.1f}pt"
    if unit == "x":
        return f"{v:.2f}x"
    return f"{v:.2f}".rstrip("0").rstrip(".")


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
               "each pillar is -2..+2. Labels: above +1.2 Bullish, above +0.4 Moderately bullish, -0.4 to +0.4 Neutral, "
               "below -0.4 Moderately bearish, below -1.2 Bearish; a score exactly on a bound takes the label nearer "
               "Neutral. A rule-based label, not a recommendation.")
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
            val = VALUE_TEXT.get(i["note"], val) if i["status"] == "ok" else val
            if i["key"] == "piotroski" and i["status"] == "ok" and i["detail"]["out_of"] != 9:
                val = f"{i['detail']['score']} of {i['detail']['out_of']} tests ({val} of 9)"
            notes = [n for n in (i["note"], i["detail"].get("base_note")) if n]
            note = f" ({'; '.join(NOTES.get(n, n) for n in notes)})" if notes else ""
            sc = _sc(i["score"]) if i["status"] == "ok" else "0 (missing)"
            out.append(f"| {PILLAR_NAMES[n]} | {IND_NAMES[i['key']]}{note} | {val} | {sc} | "
                       f"{i['weight_share'] * 100:.0f}% | {rule_text(i)} |")
    if s["caps"]:
        out.append("\n**Caps:** " + "; ".join(CAP_TEXT.get(x["type"], x["type"]) for x in s["caps"]) +
                   f". The total is held at {s['cap_limit']:+.1f} (Neutral) at most.")
    if s["conflicts"]:
        out.append("\n**Conflicts:**")
        out += [f"- {conflict_text(x)}" for x in s["conflicts"]]
    reasons = [f"data coverage {c['coverage'] * 100:.0f}%", f"pillar agreement {c['agreement'] * 100:.0f}%"]
    if c["methods_agreement"] is not None:
        reasons.append(f"valuation methods agreeing {c['methods_agreement'] * 100:.0f}%")
    reasons += [ISSUE_TEXT[i] for i in c["issues"]]
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
