#!/usr/bin/env python3
"""
The fa-1.1 contract: a small, versioned summary of analyze.py's result for other tools to read.

analyze.py's full result (and its --json file) is internal and may change between versions. The contract is
the public interface: fields are only ever added, and renaming or removing one means a new major version
(fa-2.0). It selects and normalises facts and makes no judgement of its own (nothing here says "cheap" or
"buy"). contracts/fa-1.1.schema.json describes every field; tests/test_contract.py checks both.

Usage:
  python contract.py aapl.json             print the contract of a saved `analyze.py --json` file
  python contract.py aapl.json -o c.json   write it to a file instead
  python analyze.py AAPL --contract c.json write it straight from a run

Conventions:
  as_of               the trading day the price belongs to (the quote's date, else the last daily close)
  generated_at        when the analysis ran
  ranges              [low, mid, high] in the price currency; mid is null where a method has no midpoint
  fractions           growth, margins, percentiles and gaps are fractions (0.25 = 25%), as in the full result
  null                missing data; never estimated
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score as S  # noqa: E402

CONTRACT = "fa-1.1"   # 1.1 adds valuation.availability; 1.x versions only add fields
# valuation.availability: whether each valuation input exists, and why not (fwd_pe, dcf, ...)
AVAILABILITY_KEYS = ("fwd_pe", "fwd_ev", "primary_range", "reverse_dcf", "dcf", "fcf_yield_spread", "vs_industry")
FALLBACK_NOTES = ("trailing_history", "adjusted_basis", "sector_pe")   # a stand-in measure was used
DCF_SKIPS = (("Financial-sector", "financial"), ("not positive", "negative_fcf"), ("inputs invalid", "invalid_inputs"))
RANGE_KINDS = ("fwd_pe", "fwd_ev", "dcf")
HISTORY_METRICS = ("pe", "ev_ebitda", "ps", "p_fcf", "pb")
ESTIMATE_FIELDS = ("fy", "date", "eps_avg", "eps_low", "eps_high", "revenue_growth", "analysts", "forward_pe")


def _num(x):
    """Plain float, or None for missing / non-numeric values (bools are not numbers here)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _day(x):
    return str(x)[:10] if x else None


def _trio(low, mid, high):
    return [_num(low), _num(mid), _num(high)]


# ---------------------------------------------------------------------------- dates
def as_of(r):
    """(date, basis): the quote's date, else the last close in the price history, else the run date."""
    if r.get("price_time"):
        return _day(r["price_time"]), "quote"
    last = ((r.get("price_range") or {}).get("week52") or {}).get("to")
    if last:
        return _day(last), "last_close"
    return _day(r.get("as_of")), "run_date"


def statements_through(r):
    """End date of the latest period in the statements: the TTM quarter, else the latest fiscal year."""
    ttm = r.get("ttm")
    if ttm and ttm.get("date"):
        return _day(ttm["date"])
    years = r.get("years") or []
    return _day(years[-1].get("date")) if years else None


# ---------------------------------------------------------------------------- blocks
def _company(r):
    p, c = r.get("profile") or {}, r.get("current") or {}
    return {"name": p.get("companyName"), "exchange": p.get("exchange"), "sector": p.get("sector"),
            "industry": p.get("industry"), "kind": r.get("sector_kind"), "currency": p.get("currency"),
            "market_cap": _num(c.get("market_cap")), "is_etf": bool(p.get("isEtf")), "is_adr": bool(p.get("isAdr"))}


def _score(s):
    conf = s.get("confidence") or {}
    return {
        "total": s["score"], "label": s["label"], "raw": s["raw_score"], "capped": s["capped"],
        "cap_limit": s["cap_limit"], "caps": s["caps"],
        "confidence": {"level": conf.get("level"), "coverage": _num(conf.get("coverage")),
                       "agreement": _num(conf.get("agreement")),
                       "methods_agreement": _num(conf.get("methods_agreement")), "issues": conf.get("issues") or []},
        "pillars": {n: {"score": p["score"], "weight": p["weight"], "coverage": _num(p.get("coverage")),
                        "available": bool(p.get("available"))}
                    for n, p in ((n, s["pillars"][n]) for n in s.get("pillar_order") or s["pillars"])},
        "views": {k: (s.get("views") or {}).get(k) for k in ("business", "price", "quadrant")},
        "conflicts": s["conflicts"],
        "not_scored": s.get("not_scored") or [],
    }


def _indicators(s):
    """Every indicator of the score, flat by key, with its pillar. n/a ones are those the company type ignores."""
    out = {}
    for name in s.get("pillar_order") or s["pillars"]:
        for i in s["pillars"][name]["indicators"]:
            out[i["key"]] = {"pillar": name, "status": i["status"], "value": _num(i.get("value")),
                             "unit": i.get("unit"), "score": _num(i.get("score")), "weight": _num(i.get("weight")),
                             "note": i.get("note")}
    return out


def _band(ind):
    """Where today's multiple sits: in its own 3-year forward range (pctile 0..1), or, as the score's fallback,
    vs its fiscal-year-end median."""
    if not ind or ind["status"] != "ok":
        return None
    d = ind.get("detail") or {}
    if ind.get("unit") == "pctile":
        return {"basis": "forward_3y", "now": _num(d.get("now")), "pctile": _num(ind.get("value")),
                "p25": _num(d.get("p25")), "median": _num(d.get("median")), "p75": _num(d.get("p75")),
                "from": _day(d.get("from")), "to": _day(d.get("to")), "vs_median": None}
    return {"basis": "trailing_vs_median", "now": _num(d.get("now")), "pctile": None, "p25": None,
            "median": _num(d.get("median")), "p75": None, "from": None, "to": None,
            "vs_median": _num(ind.get("value"))}


def _ranges(pr, analyst):
    """Valuation and price ranges now ([low, mid, high]) and at the coming fiscal year ends."""
    now = {k: None for k in RANGE_KINDS + ("week52", "analyst_targets")}
    fy_end = []
    for row in pr.get("summary") or []:
        trio = _trio(row.get("low"), row.get("mid"), row.get("high"))
        kind, at = row.get("kind"), row.get("at")
        if at == "now" and kind in RANGE_KINDS:
            now[kind] = trio
        elif kind == "week52":
            now["week52"] = trio
        elif kind == "targets":
            now["analyst_targets"] = trio
        elif at == "fy_end":
            fy_end.append({"kind": kind, "fy": row.get("fy"), "date": _day(row.get("date")), "range": trio})
    pt = analyst.get("price_target") or {}
    if now["analyst_targets"] is None and pt.get("consensus") is not None:
        now["analyst_targets"] = _trio(pt.get("low"), pt.get("consensus"), pt.get("high"))
    return now, fy_end


def _dcf(d):
    if not d or d.get("skipped") or _num(d.get("value_per_share")) is None:
        return None
    return {"value": _num(d["value_per_share"]), "low": _num(d.get("range_low")), "high": _num(d.get("range_high")),
            "margin": _num(d.get("margin_of_safety")), "discount_rate": _num(d.get("discount_rate")),
            "growth": _num(d.get("growth_1_5")), "terminal_growth": _num(d.get("terminal_growth")),
            "fcf_start_basis": d.get("fcf_start_basis")}


def _state(status, reason=None, text=None):
    return {"status": status, "reason": reason, "text": text}


def _indicator_state(ind):
    """ok / fallback / unavailable for one score indicator, with its note as the reason."""
    if not ind:
        return _state("unavailable", "no_data", S.NOTES["no_data"])
    note = ind.get("note")
    base = (ind.get("detail") or {}).get("base_note")   # the score keeps the original note when it caps a value
    if ind["status"] == "ok":
        if (base or note) in FALLBACK_NOTES or (ind["key"].endswith("_position") and ind.get("unit") != "pctile"):
            why = base or (note if note in FALLBACK_NOTES else "trailing_history")
            text = S.NOTES.get(why)
            if note and note != why:                      # e.g. also capped for a growth slowdown
                text = f"{text}; {S.NOTES.get(note, note)}"
            return _state("fallback", why, text)
        return _state("ok", note, S.NOTES.get(note) if note else None)
    if ind["status"] == "n/a":
        return _state("unavailable", note or "not_applicable", S.NOTES.get(note, "not used for this company type"))
    return _state("unavailable", note or "no_data", S.NOTES.get(note, S.NOTES["no_data"]))


def _dcf_state(r):
    d = r.get("dcf") or {}
    if d.get("skipped"):
        code = next((c for k, c in DCF_SKIPS if k in d["skipped"]), "skipped")
        return _state("unavailable", code, d["skipped"])
    if _num(d.get("value_per_share")) is None:
        return _state("unavailable", "no_data", "DCF not computed")
    if _num(d["value_per_share"]) <= 0:
        return _state("unavailable", "dcf_negative", S.NOTES["dcf_negative"])
    return _state("ok")


def _availability(r, s, raw, valuation):
    """Which valuation inputs exist, which are stand-ins, and why the others are missing."""
    out = {"fwd_pe": _indicator_state(raw.get("fwd_pe_position")),
           "fwd_ev": _indicator_state(raw.get("fwd_ev_position")),
           "reverse_dcf": _indicator_state(raw.get("implied_growth_gap")),
           "dcf": _dcf_state(r),
           "fcf_yield_spread": _indicator_state(raw.get("fcf_yield_spread")),
           "vs_industry": _indicator_state(raw.get("vs_industry"))}
    if valuation["primary_range"]:
        basis = valuation["primary_range"]["basis"]
        out["primary_range"] = _state("ok" if basis == "fwd_pe" else "fallback", basis,
                                      None if basis == "fwd_pe" else "no usable forward P/E range, so the DCF range is used")
    else:
        why = [f"forward P/E: {out['fwd_pe']['reason']}" if out["fwd_pe"]["status"] != "ok" else
               "forward P/E on another EPS basis than the statements",
               f"DCF: {out['dcf']['reason']}" if out["dcf"]["status"] != "ok" else "DCF in another currency"]
        out["primary_range"] = _state("unavailable", "no_forward_pe_or_dcf",
                                      "neither a forward P/E range nor a DCF range is usable (" + "; ".join(why) + ")")
    return {k: out[k] for k in AVAILABILITY_KEYS}


def _yield_spread(ind):
    """FCF yield minus the 10Y Treasury yield; REITs use operating cash flow (detail.basis "ocf")."""
    if not ind or ind["status"] != "ok":
        return None
    return {"value": _num(ind.get("value")), "basis": (ind.get("detail") or {}).get("basis") or "fcf"}


def _valuation(r, s):
    raw = {i["key"]: i for p in s["pillars"].values() for i in p["indicators"]}
    pr, analyst = r.get("price_range") or {}, r.get("analyst") or {}
    now, fy_end = _ranges(pr, analyst)
    vr = s.get("value_range")
    gap = raw.get("implied_growth_gap") or {}
    gd = gap.get("detail") or {}
    dcf = r.get("dcf") or {}
    vi = raw.get("vs_industry") or {}
    vd = vi.get("detail") or {}
    hc = r.get("history_compare") or {}
    out = {
        "fwd_pe": _band(raw.get("fwd_pe_position")),
        "fwd_ev": _band(raw.get("fwd_ev_position")),
        "ranges": now,
        "ranges_fy_end": fy_end,
        "primary_range": None if not vr else {"basis": vr.get("basis"), "range": _trio(vr.get("low"), vr.get("mid"),
                                                                                        vr.get("high")),
                                              "mid_vs_price": _num(vr.get("mid_vs_price"))},
        "reverse_dcf": {"implied": _num(gd.get("implied", dcf.get("implied_growth"))),
                        "reference": _num(gd.get("reference")), "reference_source": gd.get("reference_source"),
                        "analysts": _num(gd.get("analysts")),
                        "gap": _num(gap.get("value")) if gap.get("status") == "ok" else None},
        "dcf": _dcf(dcf),
        "fcf_yield_spread": _yield_spread(raw.get("fcf_yield_spread")),
        "vs_industry": None if vi.get("status") != "ok" else {
            "company_pe": _num(vd.get("company_pe")), "group_pe": _num(vd.get("group_pe")),
            "group": vd.get("group"), "group_pctile": _num(vd.get("group_percentile")),
            "premium": _num(vi.get("value"))},
        "vs_own_history": {m: {k: _num((hc.get(m) or {}).get(k)) for k in ("current", "median", "min", "max", "vs_median")}
                           for m in HISTORY_METRICS if hc.get(m)},
    }
    out["availability"] = _availability(r, s, raw, out)
    return out


def _estimates(analyst):
    """The next two fiscal years analysts cover that have not ended yet."""
    rows = [e for e in analyst.get("estimates") or [] if not e.get("ended")][:2]
    return [{k: (e.get(k) if k in ("fy", "date") else _num(e.get(k))) for k in ESTIMATE_FIELDS} for e in rows]


def _insider(ins):
    if ins is None:
        return {"available": False, "reason": "skipped (--no-insider)"}
    if ins.get("restricted"):
        return {"available": False, "reason": "not in the FMP plan"}
    b, s, ob = ins.get("buys") or {}, ins.get("sells") or {}, ins.get("officer_buy")
    return {"available": True, "from": ins.get("from"), "to": ins.get("to"), "complete": bool(ins.get("complete")),
            "open_market_buys": b.get("trades"), "buyers": b.get("insiders"), "buy_value": _num(b.get("value")),
            "cluster_buy": ins.get("cluster") is not None, "cluster": ins.get("cluster"),
            "officer_buy": None if not ob else {k: ob.get(k) for k in ("date", "role", "value")},
            "open_market_sells": s.get("trades"), "sellers": s.get("insiders"), "sell_value": _num(s.get("value")),
            "sells_vs_mcap": _num(ins.get("sells_vs_mcap"))}


def _warnings(r):
    w = []
    if r.get("sector_note"):
        w.append(r["sector_note"])
    if not r.get("price_time"):
        w.append("price from the company profile, not a timestamped quote")
    pr = r.get("price_range") or {}
    for k in ("band_note", "band_problem", "trailing_problem"):
        if pr.get(k):
            w.append(f"price range {k.replace('_', ' ')}: {pr[k]}")
    if (r.get("dcf") or {}).get("skipped"):
        w.append(f"DCF skipped: {r['dcf']['skipped']}")
    return w


# ---------------------------------------------------------------------------- contract
def build(r):
    """The fa-1.1 contract of one analyze.py result (the in-memory dict or a loaded --json file)."""
    s = r["score"]
    day, basis = as_of(r)
    meta = r.get("meta") or {}
    return {
        "contract": CONTRACT,
        "rules_version": s["version"],
        "ticker": r["symbol"],
        "generated_at": r.get("generated_at") or _day(r.get("as_of")),
        "as_of": day,
        "as_of_basis": basis,
        "price": _num((r.get("current") or {}).get("price")),
        "price_time": r.get("price_time") or None,
        "statements_through": statements_through(r),
        "period_basis": (r.get("basis") or {}).get("label"),
        "data_source": (meta.get("connection") or {}).get("route"),
        "company": _company(r),
        "score": _score(s),
        "indicators": _indicators(s),
        "valuation": _valuation(r, s),
        "estimates": _estimates(r.get("analyst") or {}),
        "insider": _insider(r.get("insider")),
        "flags_text": {"red": list((r.get("flags") or {}).get("red") or []),
                       "green": list((r.get("flags") or {}).get("green") or [])},
        "warnings": _warnings(r),
        "restricted": list(meta.get("restricted") or []),
        "errors": list(meta.get("errors") or []),
    }


def dumps(c):
    return json.dumps(c, indent=2, ensure_ascii=False)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=f"Build the {CONTRACT} contract from a saved analyze.py --json file")
    ap.add_argument("full_json")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args(argv)
    try:
        r = json.loads(Path(a.full_json).read_text(encoding="utf-8"))
        text = dumps(build(r))
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"Cannot build the contract from {a.full_json}: {e!r}", file=sys.stderr)
        return 1
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"({CONTRACT} contract written to {a.out})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
