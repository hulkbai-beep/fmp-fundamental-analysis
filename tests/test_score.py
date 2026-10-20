"""
Offline tests for the fundamental score (scripts/score.py). No API key or network needed:

    python3 -m unittest discover -s tests

The rule tests feed hand-built inputs to the scoring functions; the end-to-end tests run the whole analysis
on the synthetic companies in fake_fmp.py (QUAL, TRAP, BANK) and check the report and the UI endpoint.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ui"))

import score as S  # noqa: E402


def ok(key, score, value=None):
    return S._ind(key, value, score=score)


def pillar_stub(scores):
    """A pillar function that gives every indicator of the pillar the same score."""
    def fn(name):
        def f(r, kind):
            keys = S.WEIGHTS["financial" if kind == "financial" else "general"][name]
            return {k: ok(k, scores[name]) for k in keys}
        return f
    return {n: fn(n) for n in S.PILLARS}


def stubbed_score(scores, r=None):
    with mock.patch.dict(S.PILLAR_FUNCS, pillar_stub(scores)):
        return S.score(r or {})


class Rules(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(S.PILLAR_WEIGHTS.values()), 1.0)
        for kind, pillars in S.WEIGHTS.items():
            for name, w in pillars.items():
                self.assertAlmostEqual(sum(w.values()), 1.0, msg=f"{kind}/{name}")

    def test_every_indicator_has_a_band_and_a_name(self):
        for pillars in S.WEIGHTS.values():
            for w in pillars.values():
                for k in w:
                    self.assertIn(k, S.IND_NAMES)
                    if k != "altman":
                        self.assertIn(k, S.BANDS)

    def test_bands_are_ordered(self):
        for key, (cuts, scores, _unit) in S.BANDS.items():
            self.assertEqual(list(cuts), sorted(cuts), key)
            self.assertEqual(len(scores), len(cuts) + 1, key)

    def test_value_on_a_cut_takes_the_band_above(self):
        cuts, scores, _ = S.BANDS["fwd_pe_position"]
        self.assertEqual(S.band_score(0.2499, cuts, scores), 2)
        self.assertEqual(S.band_score(0.25, cuts, scores), 1)
        self.assertEqual(S.band_score(0.75, cuts, scores), -2)
        cuts, scores, _ = S.BANDS["roic_level"]
        self.assertEqual(S.band_score(0.12, cuts, scores), 1)
        self.assertEqual(S.band_score(0.1199, cuts, scores), 0)

    def test_labels_on_bounds_take_the_one_nearer_neutral(self):
        cases = {1.21: "Bullish", 1.2: "Moderately bullish", 0.41: "Moderately bullish", 0.4: "Neutral", 0.0: "Neutral",
                 -0.4: "Neutral", -0.41: "Moderately bearish", -1.2: "Moderately bearish", -1.21: "Bearish"}
        for v, want in cases.items():
            self.assertEqual(S.label_of(v), want, v)


class Pillars(unittest.TestCase):
    def test_missing_counts_as_zero_and_keeps_its_weight(self):
        inds = {"fwd_pe_position": ok("fwd_pe_position", 2)}
        for k in S.WEIGHTS["general"]["valuation"]:
            inds.setdefault(k, S._missing(k, "no_data"))
        p = S._pillar("valuation", inds, "general")
        self.assertAlmostEqual(p["score"], 0.6)          # 30% x +2, the rest count as 0
        self.assertAlmostEqual(p["coverage"], 0.30)

    def test_not_applicable_is_dropped_and_the_rest_reweighted(self):
        inds = {"fwd_pe_position": ok("fwd_pe_position", 2), "pb_vs_history": ok("pb_vs_history", 0),
                "vs_industry": ok("vs_industry", -1)}
        p = S._pillar("valuation", inds, "financial")
        na = [i["key"] for i in p["indicators"] if i["status"] == "n/a"]
        self.assertEqual(sorted(na), ["dcf_margin", "fwd_ev_position", "implied_growth_gap"])
        self.assertAlmostEqual(p["score"], 0.4 * 2 + 0.3 * 0 + 0.3 * -1)
        self.assertAlmostEqual(sum(i["weight_share"] for i in p["indicators"]), 1.0)
        self.assertEqual(p["coverage"], 1.0)

    def test_total_is_the_weighted_pillars(self):
        s = stubbed_score({"valuation": 1, "quality": 2, "growth": -1, "health": 0})
        self.assertAlmostEqual(s["score"], 0.35 * 1 + 0.25 * 2 + 0.20 * -1)
        self.assertFalse(s["caps"])
        self.assertEqual(s["label"], "Moderately bullish")


class Caps(unittest.TestCase):
    def test_value_trap_caps_at_neutral(self):
        s = stubbed_score({"valuation": 2, "quality": -1, "growth": -1, "health": 2})
        self.assertAlmostEqual(s["raw_score"], 0.65)
        self.assertEqual(s["score"], 0.4)
        self.assertTrue(s["capped"])
        self.assertEqual(s["label"], "Neutral")
        self.assertEqual([c["type"] for c in s["caps"]], ["value_trap"])

    def test_value_trap_thresholds_are_inclusive(self):
        s = stubbed_score({"valuation": 1.0, "quality": -0.5, "growth": -0.5, "health": 2})
        self.assertIn("value_trap", [c["type"] for c in s["caps"]])
        s = stubbed_score({"valuation": 1.0, "quality": -0.4, "growth": -0.5, "health": 2})
        self.assertNotIn("value_trap", [c["type"] for c in s["caps"]])

    def test_value_trap_survives_float_rounding(self):
        # (0.4 - 1.4) / 2 is -0.49999999999999994 in floats
        s = stubbed_score({"valuation": 1.5, "quality": 0.4, "growth": -1.4, "health": 1.0})
        self.assertIn("value_trap", [c["type"] for c in s["caps"]])
        self.assertEqual(s["score"], 0.4)

    def test_cap_never_raises_a_low_score(self):
        r = {"years": [{"interest_expense": 100, "ebit": 120, "net_debt": 1000}] * 2}
        s = stubbed_score({"valuation": -1, "quality": -1, "growth": -1, "health": -1}, r)
        self.assertEqual(s["score"], -1.0)
        self.assertFalse(s["capped"])
        self.assertEqual([c["type"] for c in s["caps"]], ["interest_coverage"])

    def test_red_line_caps_a_high_score(self):
        r = {"years": [{"interest_expense": 100, "ebit": 120, "net_debt": 1000}] * 2}
        s = stubbed_score({"valuation": 2, "quality": 2, "growth": 2, "health": 2}, r)
        self.assertEqual(s["score"], 0.4)
        self.assertTrue(s["capped"])

    def test_red_lines(self):
        def types(r, kind="general"):
            return [c["type"] for c in S.red_lines(r, kind)]
        self.assertEqual(types({"altman": {"z_zone": "distress", "z2_zone": "distress"}}), ["altman_distress"])
        self.assertEqual(types({"altman": {"z_zone": "distress", "z2_zone": "grey"}}), [])
        weak = {"interest_expense": 100, "ebit": 149, "net_debt": 1}
        self.assertEqual(types({"years": [weak, weak]}), ["interest_coverage"])
        # one bad year (a one-off charge) is not enough
        self.assertEqual(types({"years": [dict(weak, ebit=900), weak]}), [])
        self.assertEqual(types({"years": [weak, dict(weak, ebit=150)]}), [])
        self.assertEqual(types({"years": [dict(weak, net_debt=-1)] * 2}), [])
        burn = {"years": [{"fcf": -1, "net_debt": 5}, {"fcf": -2, "net_debt": 5}]}
        self.assertEqual(types(burn), ["cash_burn"])
        self.assertEqual(types({"years": [{"fcf": 1, "net_debt": 5}, {"fcf": -2, "net_debt": 5}]}), [])
        self.assertEqual(types({"years": [{"equity": -1, "interest_expense": 100, "ebit": 0, "net_debt": 9}]},
                               "financial"), ["negative_equity"])
        # REITs: EBITDA cover, operating (not free) cash flow, no Altman; utilities: no Altman, operating cash flow
        distress = {"altman": {"z_zone": "distress", "z2_zone": "distress"}}
        self.assertEqual(types(distress, "reit"), [])
        self.assertEqual(types(distress, "utility"), [])
        reit = {"interest_expense": 100, "ebit": 100, "ebitda": 300, "net_debt": 5, "fcf": -1, "ocf": 2}
        self.assertEqual(types({"years": [reit, reit]}, "reit"), [])
        self.assertEqual(types({"years": [reit, reit]}, "general"), ["interest_coverage", "cash_burn"])
        self.assertEqual(types({"years": [dict(reit, ocf=-1)] * 2}, "utility"), ["interest_coverage", "cash_burn"])


class Indicators(unittest.TestCase):
    def est(self, *eps):
        return {"analyst": {"estimates": [{"fy": 2026 + i, "eps_avg": e, "ended": False} for i, e in enumerate(eps)]}}

    def test_growth_slowdown_caps_cheap_multiple_at_plus_one(self):
        r = dict(self.est(1.0, 1.05), cagr={"eps": 0.20})
        ind = ok("fwd_pe_position", 2, 0.1)
        S._slowdown_cap(ind, r)
        self.assertEqual((ind["score"], ind["note"]), (1, "growth_slowdown"))
        r = dict(self.est(1.0, 1.12), cagr={"eps": 0.20})
        ind = ok("fwd_pe_position", 2, 0.1)
        S._slowdown_cap(ind, r)
        self.assertEqual(ind["score"], 2)
        r = dict(self.est(1.0, 1.01), cagr={"eps": 0.15})     # history must be above 15%
        ind = ok("fwd_pe_position", 2, 0.1)
        S._slowdown_cap(ind, r)
        self.assertEqual(ind["score"], 2)

    def test_multiple_position_falls_back_to_trailing_history(self):
        r = {"history_compare": {"pe": {"vs_median": -0.30, "n": 4, "current": 14, "median": 20}}}
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["score"], ind["note"], ind["unit"]), (2, "trailing_history", "pct"))
        r["history_compare"]["pe"]["n"] = 2
        self.assertEqual(S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")["status"], "missing")

    def test_multiple_position_uses_forward_band(self):
        r = {"price_range": {"pe_band": {"now_pct": 0.40, "now": 18, "p25": 16, "median": 20, "p75": 24,
                                         "from": "2023-10-20", "to": "2026-10-20"}}}
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["score"], ind["unit"]), (1, "pctile"))

    def test_current_ratio_below_one_is_not_penalised_with_net_cash(self):
        self.assertEqual(S._current_ratio({"current_ratio": 0.8, "net_debt": -1})["note"], "cash_rich")
        self.assertEqual(S._current_ratio({"current_ratio": 0.8, "net_debt": -1})["score"], 0)
        self.assertEqual(S._current_ratio({"current_ratio": 0.8, "net_debt": 1, "fcf_margin": 0.05})["score"], -1)

    def test_interest_coverage_without_interest(self):
        self.assertEqual(S._coverage({"interest_expense": 0, "debt": 0}, "general")["score"], 2)
        self.assertEqual(S._coverage({"interest_expense": 0, "debt": 10, "net_debt": 5}, "general")["status"], "missing")
        # unknown debt is not zero debt
        self.assertEqual(S._coverage({"interest_expense": 0}, "general")["status"], "missing")
        self.assertEqual(S._coverage({"interest_expense": 10, "ebit": 100}, "general")["score"], 1)  # 10x
        self.assertEqual(S.score({})["score"], 0)

    def test_coverage_by_company_type(self):
        L = {"interest_expense": 100, "ebit": 150, "ebitda": 450}
        self.assertEqual(S._coverage(L, "general")["score"], -2)       # 1.5x EBIT
        reit = S._coverage(L, "reit")                                    # 4.5x EBITDA on REIT bands
        self.assertEqual((reit["score"], reit["note"], round(reit["value"], 2)), (1, "ebitda_coverage", 4.5))
        self.assertEqual(S._coverage(dict(L, ebit=250), "utility")["score"], 0)  # 2.5x on utility bands

    def test_reit_and_utility_leverage_bands(self):
        L = {"net_debt": 5, "ebitda": 1}
        self.assertEqual(S._net_debt_ebitda(L, "general")["score"], -2)
        self.assertEqual(S._net_debt_ebitda(L, "reit")["score"], 0)
        self.assertEqual(S._net_debt_ebitda(dict(L, net_debt=6), "utility")["score"], 0)
        self.assertEqual(S._net_debt_ebitda({"net_debt": -5, "ebitda": 1}, "general")["note"], "net_cash")
        nc = S._net_debt_ebitda({"net_debt": -5, "ebitda": 1}, "reit")
        self.assertEqual((nc["note"], nc["detail"]["base_note"]), ("net_cash", "reit"))

    def test_altman(self):
        self.assertEqual(S._altman({"z": 1.0, "z_zone": "distress", "z2_zone": "distress"})["score"], -2)
        self.assertEqual(S._altman({"z": 1.5, "z_zone": "distress", "z2_zone": "safe"})["score"], -1)
        self.assertEqual(S._altman({"z": 4, "z_zone": "safe"})["score"], 1)
        self.assertEqual(S._altman(None)["status"], "missing")

    def test_negative_fcf_scores_minus_two(self):
        self.assertEqual(S._fcf_conversion([{"fcf": -5}], {"fcf": -5})["score"], -2)

    def test_implied_growth_outside_the_solver_range(self):
        r = dict(self.est(1.0, 1.1), cagr={"revenue": 0.05})
        self.assertEqual(S._implied_growth_gap(r, {"implied_growth_note": "below -50%"})["score"], 2)
        self.assertEqual(S._implied_growth_gap(r, {"implied_growth_note": "above 100%"})["score"], -2)
        g = S._implied_growth_gap(r, {"implied_growth": 0.10})
        self.assertEqual((g["note"], round(g["value"], 4)), ("historical_growth", 0.05))

    def test_negative_dcf_value_is_flagged(self):
        r = {"dcf": {"margin_of_safety": -1.5, "value_per_share": -5}}
        ind = S.valuation(r, "general")["dcf_margin"]
        self.assertEqual((ind["score"], ind["note"]), (-2, "dcf_negative"))

    def test_skipped_dcf_counts_as_missing(self):
        # negative FCF must not drop the DCF indicators and lift the valuation by reweighting
        out = S.valuation({"dcf": {"skipped": "Starting FCF is not positive"}}, "general")
        for k in ("dcf_margin", "implied_growth_gap"):
            self.assertEqual((out[k]["status"], out[k]["note"]), ("missing", "no_dcf"))
        p = S._pillar("valuation", out, "general")
        self.assertLess(p["coverage"], 0.7)

    def test_expected_loss(self):
        r = dict(self.est(-1.0, 2.0), cagr={"eps": 0.25})
        g = S.growth(r, "general")["eps_forward"]
        self.assertEqual((g["status"], g["note"]), ("missing", "loss_making"))
        g = S.growth(dict(self.est(1.0, -0.5)), "general")["eps_forward"]
        self.assertEqual(g["score"], -2)                       # swinging to a loss next year
        g = S.growth({"cagr": {"eps": 0.25}}, "general")["eps_forward"]
        self.assertEqual((g["score"], g["note"]), (2, "historical_eps"))
        # a forward range exists but today's next-12-month EPS is not positive: no trailing fallback
        band = {"now_pct": None, "now": None, "p25": 1, "median": 2, "p75": 3, "from": "a", "to": "b"}
        hist = {"pe": {"vs_median": -0.3, "n": 5, "current": 10, "median": 14}}
        r = dict(self.est(-1.0, 2.0), price_range={"pe_band": band}, history_compare=hist)
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["status"], ind["note"]), ("missing", "loss_making"))
        r["price_range"] = {}
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["status"], ind["note"]), ("missing", "loss_making"))

    def test_broken_share_basis_blocks_the_trailing_fallback(self):
        hist = {"pe": {"vs_median": -0.77, "n": 5, "current": 5, "median": 22},
                "pb": {"vs_median": -0.8, "n": 5, "current": 1, "median": 5}}
        r = dict(self.est(1.0, 1.1), price_range={"band_problem": "share_basis"}, history_compare=hist)
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["status"], ind["note"]), ("missing", "share_basis"))
        self.assertEqual(S._pb_vs_history(r)["note"], "share_basis")
        r["price_range"] = {"band_problem": None}
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["score"], ind["note"]), (2, "trailing_history"))

    def test_adjusted_eps_uses_the_trailing_multiple(self):
        band = {"now_pct": 0.05, "now": 15, "p25": 18, "median": 20, "p75": 22, "from": "a", "to": "b"}
        hist = {"pe": {"vs_median": 0.30, "n": 5, "current": 26, "median": 20}}
        r = dict(self.est(1.0, 1.1), price_range={"pe_band": band}, history_compare=hist,
                 analyst=dict(self.est(1.0, 1.1)["analyst"], eps_basis={"gap": 0.40}))
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["score"], ind["note"]), (-2, "adjusted_basis"))
        r["analyst"]["eps_basis"] = {"gap": 0.05}               # small gaps keep the forward range
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["score"], ind["unit"]), (2, "pctile"))

    def test_slowdown_cap_keeps_the_fallback_note(self):
        r = dict(self.est(1.0, 1.04), cagr={"eps": 0.30},
                 history_compare={"pe": {"vs_median": -0.30, "n": 5, "current": 14, "median": 20}})
        out = S.valuation(r, "general")["fwd_pe_position"]
        self.assertEqual((out["score"], out["note"], out["detail"]["base_note"]), (1, "growth_slowdown", "trailing_history"))

    def test_currency_mismatch(self):
        r = {"years": [{"currency": "JPY", "label": "FY2025"}], "profile": {"currency": "USD"},
             "dcf": {"margin_of_safety": 9.0, "value_per_share": 1000, "implied_growth": -0.4},
             "market": {"sector": {"vs_industry": -0.99, "company_pe": 0.2}},
             "altman": {"z": 1.7, "z_zone": "distress", "z_double_prime": 3.0, "z2_zone": "grey"},
             "history_compare": {"pe": {"vs_median": -0.9, "n": 5, "current": 1, "median": 10}}}
        v = S.valuation(r, "general")
        for k in ("dcf_margin", "implied_growth_gap", "vs_industry", "fwd_ev_position", "fwd_pe_position"):
            self.assertEqual((v[k]["status"], v[k]["note"]), ("missing", "currency"), k)
        alt = S.health(r, "general")["altman"]
        self.assertEqual((alt["score"], alt["note"]), (0, "currency_z2"))  # Z'' grey only
        r["altman"]["z2_zone"] = "distress"
        self.assertEqual(S.red_lines(r, "general"), [])
        s = S.score(r)
        self.assertIn("currency", s["confidence"]["issues"])
        self.assertIn("currency", [c["type"] for c in s["conflicts"]])

    def test_cyclical_peak_is_flagged(self):
        years = [{"operating_margin": m} for m in (0.05, 0.06, 0.04, 0.07, 0.20)]
        r = dict(self.est(10.0, 6.5), years=years)
        self.assertIsNotNone(S._cyclical_peak(r))
        self.assertIsNone(S._cyclical_peak(dict(self.est(10.0, 11.0), years=years)))  # EPS still rising
        s = stubbed_score({"valuation": 1, "quality": 1, "growth": 1, "health": 1}, r)
        self.assertIn("cyclical_peak", s["confidence"]["issues"])
        self.assertNotEqual(s["confidence"]["level"], "high")

    def test_two_of_three_valuation_methods_is_agreement(self):
        def val(r, kind):
            sc = {"fwd_pe_position": 2, "fwd_ev_position": 1, "implied_growth_gap": -1, "dcf_margin": 0, "vs_industry": 0}
            return {k: ok(k, v) for k, v in sc.items()}
        stubs = pillar_stub({"valuation": 0, "quality": 1, "growth": 1, "health": 1})
        stubs["valuation"] = val
        with mock.patch.dict(S.PILLAR_FUNCS, stubs):
            s = S.score({"years": [{}] * 4})
        self.assertAlmostEqual(s["confidence"]["methods_agreement"], 2 / 3)
        self.assertEqual(s["confidence"]["level"], "high")

    def test_type_sets(self):
        reit = S._pillar("quality", S.quality({"years": []}, "reit"), "reit")
        na = {i["key"] for i in reit["indicators"] if i["status"] == "n/a"}
        self.assertEqual(na, {"roic_level", "fcf_conversion"})
        self.assertTrue(all(i["note"] == "na_reit" for i in reit["indicators"] if i["status"] == "n/a"))
        util = S._pillar("health", S.health({"years": []}, "utility"), "utility")
        na = {i["key"] for i in util["indicators"] if i["status"] == "n/a"}
        self.assertEqual(na, {"altman", "current_ratio"})
        q = S._pillar("quality", S.quality({"years": []}, "utility"), "utility")
        self.assertIn("roe_level", [i["key"] for i in q["indicators"] if i["status"] != "n/a"])


class TextsAndUI(unittest.TestCase):
    """Every code score.py emits has a report text and both UI translations."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "scripts" / "score.py").read_text()
        cls.i18n = (ROOT / "ui" / "i18n.js").read_text()

    def both(self, key):
        n = len(re.findall(r'(?<![\w"])"?' + re.escape(key) + r'"?\s*:', self.i18n))
        self.assertEqual(n, 2, f"{key} should be defined once in zh and once in en")

    def test_notes(self):
        used = set(re.findall(r'note="(\w+)"', self.src)) | set(re.findall(r'_missing\([^,]+, "(\w+)"', self.src))
        used |= set(re.findall(r'"(\w+)" if not _estimates', self.src))
        for n in used:
            self.assertIn(n, S.NOTES)
        for n in S.NOTES:
            self.both("note_" + n)

    def test_indicators_caps_conflicts_labels(self):
        for k in S.IND_NAMES:
            self.both("ind_" + k)
        for k in S.CAP_TEXT:
            self.both("cap_" + k)
        for k in S.CONFLICT_TEXT:
            self.both("cf_" + k)
        for k in S.VALUE_TEXT:
            self.both("val_" + k)
        for k in S.ISSUE_TEXT:
            self.both("cr_" + k)
        for k in S.NA_NOTE.values():
            self.assertIn(k, S.NOTES)
        for _b, name in S.LABELS + ((None, "Bearish"),):
            self.both(f'lbl_{name}')
        for n in S.PILLARS:
            self.both("p_" + n)


class Docs(unittest.TestCase):
    """references/metrics.md section 12 states the same bands and weights as the code."""

    @classmethod
    def setUpClass(cls):
        text = (ROOT / "references" / "metrics.md").read_text()
        cls.doc = text[text.index("## 12. Fundamental score"):]

    def test_bands(self):
        for band, (cuts, scores, unit) in S.BANDS.items():
            rule = S.rule_text({"key": band, "cuts": cuts, "scores": scores, "unit": unit})
            self.assertIn(f"| {rule} |", self.doc, band)

    def test_weights(self):
        kinds = ("general", "financial", "reit", "utility")
        for p in S.PILLARS:
            keys = dict.fromkeys(k for kind in kinds for k in S.WEIGHTS[kind][p])
            for k in keys:
                cells = [f"{S.WEIGHTS[kind][p][k] * 100:.0f}%" if k in S.WEIGHTS[kind][p] else "n/a" for kind in kinds]
                self.assertIn(f"| {S.PILLAR_NAMES[p]} | {S.IND_NAMES[k]} | " + " | ".join(cells) + " |", self.doc, k)

    def test_formula_and_version(self):
        formula = " + ".join(f"{S.PILLAR_WEIGHTS[n]:.2f} x {S.PILLAR_NAMES[n].lower()}" for n in S.PILLARS)
        self.assertIn(formula, self.doc.replace("\n", " "))
        self.assertIn(f"Rules version {S.RULES_VERSION}", self.doc.replace("\n", " "))


class EndToEnd(unittest.TestCase):
    """The whole analysis on synthetic companies, through the report and the UI endpoint."""

    @classmethod
    def setUpClass(cls):
        import analyze as A
        import fake_fmp
        cls.A = A
        cls.patch = mock.patch.object(A, "FMPClient", fake_fmp.FakeClient)
        cls.patch.start()
        cls.results = {}
        for sym in ("QUAL", "TRAP", "BANK", "EXCH", "UTIL"):
            cls.results[sym] = A.analyze(A.parse_args([sym, "--peers", "none"]))

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def check_consistent(self, s):
        raw = sum(p["weight"] * p["score"] for p in s["pillars"].values())
        self.assertAlmostEqual(s["raw_score"], round(raw, 2), places=2)
        for name, p in s["pillars"].items():
            shares = [i["weight_share"] for i in p["indicators"] if i["status"] != "n/a"]
            self.assertAlmostEqual(sum(shares), 1.0, msg=name)
            self.assertAlmostEqual(p["score"], round(sum(i["contribution"] for i in p["indicators"]), 2), places=2)
        self.assertEqual(s["label"], S.label_of(s["score"]))
        json.dumps(s)

    def test_quality_compounder_on_a_low_multiple(self):
        s = self.results["QUAL"]["score"]
        self.check_consistent(s)
        self.assertEqual(s["kind"], "general")
        self.assertGreater(s["score"], 0.4)
        self.assertFalse(s["caps"])
        self.assertGreater(s["pillars"]["valuation"]["score"], 1)
        fpe = next(i for i in s["pillars"]["valuation"]["indicators"] if i["key"] == "fwd_pe_position")
        self.assertEqual(fpe["status"], "ok")
        self.assertIsNotNone(s["value_range"])

    def test_indebted_shrinking_company_hits_a_red_line(self):
        s = self.results["TRAP"]["score"]
        self.check_consistent(s)
        self.assertLess(s["score"], -0.4)
        self.assertIn("interest_coverage", [c["type"] for c in s["caps"]])
        self.assertIn(s["confidence"]["level"], ("medium", "low"))

    def test_bank_uses_the_financial_set(self):
        s = self.results["BANK"]["score"]
        self.check_consistent(s)
        self.assertEqual(s["kind"], "financial")
        keys = {i["key"]: i["status"] for p in s["pillars"].values() for i in p["indicators"]}
        self.assertEqual(keys["fwd_ev_position"], "n/a")
        self.assertEqual(keys["net_debt_ebitda"], "n/a")
        self.assertEqual(keys["roe_level"], "ok")
        self.assertEqual(keys["equity_to_assets"], "ok")

    def test_fee_based_financial_is_analysed_like_other_companies(self):
        r = self.results["EXCH"]
        self.assertEqual(r["sector_kind"], "general")
        self.check_consistent(r["score"])
        self.assertNotIn("skipped", r["dcf"])
        self.assertFalse(r["score"]["caps"])

    def test_utility_is_not_capped_for_normal_utility_finances(self):
        r = self.results["UTIL"]
        s = r["score"]
        self.check_consistent(s)
        self.assertEqual((r["sector_kind"], s["kind"]), ("utility", "utility"))
        self.assertLess(r["years"][-1]["fcf"], 0)        # capex above operating cash flow, as usual
        self.assertFalse(s["caps"])
        keys = {i["key"]: i for p in s["pillars"].values() for i in p["indicators"]}
        self.assertEqual(keys["altman"]["status"], "n/a")
        self.assertEqual(keys["dcf_margin"]["note"], "no_dcf")
        self.assertEqual(keys["net_debt_ebitda"]["note"], "utility")

    def test_currency_mismatch_end_to_end(self):
        import copy
        r = copy.deepcopy(self.results["QUAL"])
        r["years"][-1]["currency"] = "JPY"
        s = S.score(r)
        self.check_consistent(s)
        self.assertNotEqual(s["confidence"]["level"], "high")
        self.assertEqual(s["value_range"]["basis"], "fwd_pe")   # the forward P/E band is in one currency

    def test_every_emitted_note_has_texts(self):
        notes = {n for r in self.results.values() for p in r["score"]["pillars"].values() for i in p["indicators"]
                 for n in (i["note"], i["detail"].get("base_note")) if n}
        self.assertLessEqual(notes, set(S.NOTES))

    def test_report_section(self):
        for sym, r in self.results.items():
            text = self.A.render(r)
            i, j = text.find("## Fundamental score (rules v"), text.find("## 1. Growth")
            self.assertTrue(0 <= i < j, sym)
            self.assertIn("| Pillar | Weight |", text[i:j])

    def test_ui_endpoint(self):
        import fake_fmp
        import server
        with mock.patch.object(server.A, "FMPClient", fake_fmp.FakeClient), \
                mock.patch.dict(os.environ, {"FMP_API_KEY": "offline-test"}):
            code, body = server.run_analysis({"symbol": "QUAL", "peers": "none"})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["result"]["score"]["version"], S.RULES_VERSION)
        self.assertIn("## Fundamental score", body["report"])
        json.dumps(body, default=str)


if __name__ == "__main__":
    unittest.main()
