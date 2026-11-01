"""
The decision engine's side of fa-2.0, kept here to prove the document is enough: rebuild, from fa-2.0 alone,
the part of analyze.py's result that score.py reads. tests/test_facts.py checks that
score.score(to_score_input(fa-2.0)) equals the score of the original result. The engine takes this over
together with a frozen copy of score.py (step 3 of the slimming plan).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import facts as F  # noqa: E402

BAND_PROBLEMS = ("share_basis", "price_jump", "short_history")   # analyze.py sets band_note for these
DCF_SKIPPED = ("skipped_financial", "fcf_not_positive", "invalid_inputs")
REVERSE_NOTES = {"below_range": "below -50%/yr", "above_range": "above 100%/yr", "not_computable": "not computable"}


def _row(values, label, date, currency):
    y = {"label": label, "date": date, "currency": currency}
    for k, src in F.STATEMENT_FIELDS:
        y[src] = values.get(k)
    for k in F.METRIC_FIELDS:
        y[k] = values.get(k)
    return y


def _years(f):
    st, mt = f["statements"], f["metrics"]
    out = []
    for i, label in enumerate(st["period"]):
        values = {k: st[k][i] for k, _ in F.STATEMENT_FIELDS}
        values.update({k: mt[k][i] for k in F.METRIC_FIELDS})
        out.append(_row(values, label, st["end"][i], st["currency"][i]))
    return out


def _band(b, window):
    if b["p25"] is None:
        return None
    return {"now": b["now"], "now_pct": b["pctile"], **{k: b[k] for k in F.BAND_STATS},
            "from": window["from"], "to": window["to"]}


def _price_range(f):
    v = f["valuation"]
    fb, hist, fwd = v["forward_band"], v["vs_own_history"], v["forward"]
    pe, ev = _band(fb["pe"], fb), _band(fb["ev_ebitda"], fb)
    now = None
    if fwd["ntm"] is not None:
        eps = fwd["ntm"]["eps"]
        now = {"at": "now", "eps": eps, "ebitda": fwd["ntm"]["ebitda"], "pe": None}
        if pe and eps and eps > 0:   # analyze.py: the NTM EPS times the band's quartiles
            now["pe"] = {"low": eps * pe["p25"], "base": eps * pe["median"], "high": eps * pe["p75"]}
    return {"pe_band": pe, "ev_band": ev, "band_note": fb["status"] if fb["status"] in BAND_PROBLEMS else None,
            "band_problem": fb["status"] if fb["status"] in F.HISTORY_PROBLEMS else None,
            "trailing_problem": hist["status"] if hist["status"] in F.HISTORY_PROBLEMS else None,
            "forward": [now] if now else []}


def _analyst(f):
    c = f["consensus"]
    out = {"estimates": [{src: e[k] for k, src in F.ESTIMATE_FIELDS} for e in c["estimates"]]}
    vr = c["vs_reported"]
    for k, key in (("eps", "eps_basis"), ("ebitda", "ebitda_basis"), ("revenue", "revenue_basis")):
        if vr[k] is not None:
            out[key] = {"fy": vr["fy"], **vr[k]}
    return out


def _dcf(f):
    d, rev = f["models"]["dcf"], f["models"]["reverse_dcf"]
    if d["status"] in DCF_SKIPPED:
        return {"skipped": d["status"]}
    if d["value_per_share"] is None:
        return {}
    price = f["price"]["value"]
    return {"value_per_share": d["value_per_share"],
            "margin_of_safety": d["value_per_share"] / price - 1 if price else None,   # as analyze.py
            "range_low": d["low"], "range_high": d["high"], "implied_growth": rev["implied_growth_1_5"],
            "implied_growth_note": REVERSE_NOTES.get(rev["status"])}


def _market(f):
    g, rt = f["valuation"]["vs_group"], f["rates"]
    if g is None and rt is None:
        return None
    rates = None
    if rt is not None and rt["treasury_10y"] is not None:
        rates = {"date": rt["date"], "points": {"now": {"10Y": rt["treasury_10y"]}}}
    sector = None
    if g is not None:
        def grp(x):
            return None if x["status"] == "unavailable" else {"current": x["pe"], "percentile": x["pe_pctile"]}
        sector = {"company_pe": g["company_pe"], "industry_pe": grp(g["industry"]), "sector_pe": grp(g["sector"]),
                  "vs_industry": g["industry"]["premium"], "vs_sector": g["sector"]["premium"]}
    return {"rates": rates, "sector": sector}


def to_score_input(f):
    years = _years(f)
    t = f["ttm"]
    ttm = None if t is None else _row(t, "TTM", t["end"], t["currency"])
    hist = {m: {"current": h["now"], **{k: h[k] for k in ("median", "min", "max", "n", "vs_median")}}
            for m, h in f["valuation"]["vs_own_history"].items() if isinstance(h, dict)}
    pio, alt = f["models"]["piotroski"], f["models"]["altman"]
    return {
        "sector_kind": f["company"]["kind"],
        "profile": {"currency": f["price"]["currency"]},
        "years": years, "ttm": ttm, "basis": ttm or years[-1],
        "current": {"price": f["price"]["value"], "market_cap": f["company"]["market_cap"]},
        "cagr": f["growth"]["cagr"],
        "history_compare": hist,
        "price_range": _price_range(f),
        "analyst": _analyst(f),
        "dcf": _dcf(f),
        "market": _market(f),
        "piotroski": None if pio is None else {"year": pio["fy"], "score": pio["score"], "out_of": pio["out_of"]},
        "altman": None if alt["status"] == "unavailable" else {
            "year": alt["fy"], "z": alt["z"], "z_zone": alt["z_zone"], "z_double_prime": alt["z2"],
            "z2_zone": alt["z2_zone"]},
        "meta": {"connection": {"route": f["data_quality"]["route"]}},
    }
