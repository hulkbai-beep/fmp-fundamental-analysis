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
        self.assertAlmostEqual(p["score"], 0.5)          # 25% x +2, the rest count as 0
        self.assertAlmostEqual(p["coverage"], 0.25)

    def test_not_applicable_is_dropped_and_the_rest_reweighted(self):
        inds = {"fwd_pe_position": ok("fwd_pe_position", 2), "pb_vs_history": ok("pb_vs_history", 0),
                "vs_industry": ok("vs_industry", -1)}
        p = S._pillar("valuation", inds, "financial")
        na = [i["key"] for i in p["indicators"] if i["status"] == "n/a"]
        self.assertEqual(sorted(na), ["dcf_margin", "fcf_yield_spread", "fwd_ev_position", "implied_growth_gap"])
        self.assertAlmostEqual(p["score"], 0.4 * 2 + 0.3 * 0 + 0.3 * -1)
        self.assertAlmostEqual(sum(i["weight_share"] for i in p["indicators"]), 1.0)
        self.assertEqual(p["coverage"], 1.0)

    def test_total_is_the_weighted_pillars(self):
        s = stubbed_score({"valuation": 1, "quality": 2, "growth": -1, "health": 0})
        self.assertAlmostEqual(s["score"], 0.35 * 1 + 0.25 * 2 + 0.20 * -1)
        self.assertFalse(s["caps"])
        self.assertEqual(s["label"], "Moderately bullish")

    def test_two_views_leave_the_total_alone(self):
        s = stubbed_score({"valuation": -1, "quality": 2, "growth": 1, "health": 0})
        self.assertAlmostEqual(s["score"], 0.35 * -1 + 0.25 * 2 + 0.20 * 1)
        self.assertEqual(s["views"]["business"], round((0.25 * 2 + 0.20 * 1) / 0.65, 2))
        self.assertEqual((s["views"]["price"], s["views"]["quadrant"]), (-1, "good_business_pricey"))
        for scores, quadrant in (((1, 1), "good_business_good_price"), ((1, -1), "cheap_weak_business"),
                                 ((-1, -1), "weak_and_pricey"), ((0, 0), "good_business_good_price")):
            v, b = scores
            s = stubbed_score({"valuation": v, "quality": b, "growth": b, "health": b})
            self.assertEqual(s["views"]["quadrant"], quadrant, scores)

    def test_no_negative_zero(self):
        s = stubbed_score({"valuation": -0.004, "quality": 0, "growth": 0, "health": 0})
        self.assertEqual([str(x) for x in (s["score"], s["raw_score"], s["pillars"]["valuation"]["score"])],
                         ["0.0"] * 3)


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
        self.assertEqual(types(distress, "fee_financial"), [])
        self.assertEqual(types(burn, "fee_financial"), ["cash_burn"])
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

    def test_old_share_basis_break_blocks_the_trailing_fallback(self):
        # the forward range's 3 years are fine, but an older fiscal year in the trailing history is not
        hist = {"pe": {"vs_median": -0.77, "n": 5, "current": 5, "median": 22},
                "pb": {"vs_median": -0.8, "n": 5, "current": 1, "median": 5}}
        r = dict(self.est(1.0, 1.1), price_range={"band_problem": None, "trailing_problem": "share_basis"},
                 history_compare=hist)
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["status"], ind["note"]), ("missing", "share_basis"))
        self.assertEqual(S._pb_vs_history(r)["note"], "share_basis")

    def test_forward_range_without_a_point_for_today_falls_back(self):
        band = {"now_pct": None, "now": None, "p25": 18, "median": 20, "p75": 22, "from": "a", "to": "b"}
        r = dict(self.est(1.0, None), price_range={"pe_band": band},
                 history_compare={"pe": {"vs_median": 0.0, "n": 5, "current": 20, "median": 20}})
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe", "eps_basis", "eps_avg")
        self.assertEqual((ind["status"], ind["note"]), ("ok", "trailing_history"))

    def test_unknown_ebitda_is_missing(self):
        self.assertEqual(S._net_debt_ebitda({"net_debt": 50, "ebitda": None}, "general")["status"], "missing")
        self.assertEqual(S._net_debt_ebitda({"net_debt": 50, "ebitda": -1}, "general")["score"], -2)

    def test_piotroski_with_too_few_tests(self):
        self.assertEqual(S.health({"piotroski": {"score": 4, "out_of": 6}}, "financial")["piotroski"]["note"], "few_tests")
        self.assertEqual(S.health({}, "financial")["piotroski"]["note"], "short_history")

    def test_clipped_trend_is_flagged(self):
        years = [{"label": f"FY{y}", "roic": v} for y, v in ((2022, 0.8), (2023, 1.0), (2024, 1.2), (2025, 1.5))]
        ind = S._trend("roic_trend", years, "roic", clip=0.5)
        self.assertEqual((ind["value"], ind["note"]), (0.0, "clipped"))
        self.assertIsNone(S._trend("roic_trend", years, "roic")["note"])

    def test_value_range_skips_forward_pe_on_adjusted_eps(self):
        r = {"price_range": {"forward": [{"at": "now", "pe": {"low": 90, "base": 100, "high": 110}}]},
             "dcf": {"range_low": 70, "value_per_share": 80, "range_high": 95}, "current": {"price": 100},
             "analyst": {"eps_basis": {"gap": 0.25}}}
        self.assertEqual(S._value_range(r)["basis"], "dcf")
        r["analyst"]["eps_basis"]["gap"] = 0.05
        self.assertEqual(S._value_range(r)["basis"], "fwd_pe")

    def test_reit_coverage_is_named_for_ebitda(self):
        L = {"interest_expense": 10, "ebit": 15, "ebitda": 40, "net_debt": 100}
        self.assertEqual(S._coverage(L, "reit")["detail"]["basis"], "ebitda")
        self.assertEqual(S._coverage(L, "general")["detail"]["basis"], "ebit")
        self.assertIn("interest_coverage_ebitda", S.IND_NAMES)

    def test_three_year_change_needs_four_years(self):
        years = [{"label": f"FY{y}", "roic": r} for y, r in ((2022, 0.10), (2023, 0.12), (2024, 0.15), (2025, 0.16))]
        ind = S._trend("roic_trend", years, "roic")
        self.assertAlmostEqual(ind["value"], 0.06)
        self.assertEqual((ind["detail"]["from"], ind["score"]), ("FY2022", 2))
        self.assertEqual(S._trend("roic_trend", years[1:], "roic")["note"], "short_history")

    def test_negative_fcf_scores_minus_two(self):
        self.assertEqual(S._fcf_conversion([{"fcf": -5}], {"fcf": -5})["score"], -2)

    def test_implied_growth_outside_the_solver_range(self):
        r = dict(self.est(1.0, 1.1), cagr={"revenue": 0.05})
        self.assertEqual(S._implied_growth_gap(r, {"implied_growth_note": "below -50%"})["score"], 2)
        self.assertEqual(S._implied_growth_gap(r, {"implied_growth_note": "above 100%"})["score"], -2)
        g = S._implied_growth_gap(r, {"implied_growth": 0.10})
        self.assertEqual((g["note"], round(g["value"], 4)), ("historical_growth", 0.05))

    def test_implied_growth_compares_with_the_lower_of_analysts_and_history(self):
        def r(cagr, *growth):
            return {"analyst": {"estimates": [{"fy": 2026 + i, "revenue_growth": g, "ended": False}
                                              for i, g in enumerate(growth)]}, "cagr": {"revenue": cagr}}
        g = S._implied_growth_gap(r(0.05, 0.12, 0.10), {"implied_growth": 0.10})
        self.assertEqual((g["note"], g["detail"]["reference_source"], round(g["value"], 4)), ("history_lower", "history", 0.05))
        g = S._implied_growth_gap(r(0.15, 0.12, 0.10), {"implied_growth": 0.10})
        self.assertEqual((g["note"], g["detail"]["reference_source"], round(g["value"], 4)), (None, "analysts", -0.01))
        g = S._implied_growth_gap(r(None, 0.12, 0.10), {"implied_growth": 0.10})
        self.assertEqual((g["note"], round(g["value"], 4)), (None, -0.01))

    def test_optimistic_estimates_are_a_conflict(self):
        r = dict(self.est(1.0, 1.20), cagr={"eps": 0.10})      # exactly 10 points above history
        self.assertIsNotNone(S._optimistic_estimates(r))
        s = stubbed_score({"valuation": 0, "quality": 0, "growth": 0, "health": 0}, r)
        c = [x for x in s["conflicts"] if x["type"] == "optimistic_estimates"]
        self.assertEqual(len(c), 1)
        self.assertIn("+20.0%", S.conflict_text(c[0]))
        self.assertEqual(s["score"], 0)                          # listed only, the score does not move
        self.assertIsNone(S._optimistic_estimates(dict(self.est(1.0, 1.15), cagr={"eps": 0.10})))
        self.assertIsNone(S._optimistic_estimates(self.est(1.0, 1.5)))   # no history to compare with

    def test_fcf_yield_spread(self):
        rates = {"rates": {"date": "2026-10-23", "points": {"now": {"10Y": 0.042}}}}
        r = {"basis": {"fcf": 50.0, "ocf": 80.0, "label": "TTM"}, "current": {"market_cap": 1000.0}, "market": rates}
        g = S._fcf_yield_spread(r, "general")
        self.assertEqual((round(g["value"], 4), g["score"], g["detail"]["basis"]), (0.008, 0, "fcf"))   # 5.0% - 4.2%
        g = S._fcf_yield_spread(r, "reit")                     # REITs: operating cash flow
        self.assertEqual((round(g["value"], 4), g["score"], g["detail"]["basis"]), (0.038, 1, "ocf"))
        self.assertEqual(S._fcf_yield_spread(dict(r, basis={"fcf": -10.0}), "general")["score"], -2)
        self.assertEqual(S._fcf_yield_spread(dict(r, market=None), "general")["note"], "no_treasury")
        self.assertEqual(S._fcf_yield_spread(dict(r, current={}), "general")["note"], "no_data")
        r["years"], r["profile"] = [{"currency": "JPY"}], {"currency": "USD"}
        self.assertEqual(S._fcf_yield_spread(r, "general")["note"], "currency")
        self.assertNotIn("fcf_yield_spread", S.valuation(dict(r, years=[]), "utility"))
        self.assertIn("fcf_yield_spread", S.valuation(dict(r, years=[]), "reit"))

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

    def test_dilution_is_the_median_year(self):
        # one all-share acquisition year among steady buybacks
        years = [{"shares_yoy": v} for v in (None, -0.01, 0.35, -0.02, -0.01)]
        ind = S.health({"years": years}, "general")["dilution"]
        self.assertEqual((ind["value"], ind["score"]), (-0.01, 1))

    def test_forward_revenue_growth_on_the_analysts_basis_is_noted(self):
        r = {"analyst": {"estimates": [{"fy": "2026", "revenue_growth": 0.05}, {"fy": "2027", "revenue_growth": 0.07}],
                         "revenue_basis": {"fy": "FY2025", "estimate": 70, "reported": 100, "gap": -0.3}}}
        ind = S.growth(r, "financial")["revenue_forward"]
        self.assertEqual((round(ind["value"], 4), ind["note"]), (0.06, "revenue_basis"))
        del r["analyst"]["revenue_basis"]
        self.assertIsNone(S.growth(r, "financial")["revenue_forward"]["note"])

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
        fee = S._pillar("health", S.health({"years": []}, "fee_financial"), "fee_financial")
        self.assertEqual({i["key"]: i["note"] for i in fee["indicators"] if i["status"] == "n/a"},
                         {"altman": "na_fee_financial", "current_ratio": "na_fee_financial"})


class AnalystsAndHistory(unittest.TestCase):
    """analyze.py inputs the score relies on."""

    @classmethod
    def setUpClass(cls):
        import analyze as A
        cls.A = A

    def view(self, fy0_revenue):
        last = {"date": "2025-12-31", "label": "FY2025", "revenue": 100.0, "eps": 2.0, "ebitda": None}
        est = [{"date": "2025-12-31", "revenueAvg": fy0_revenue, "epsAvg": 2.0},
               {"date": "2026-12-31", "revenueAvg": fy0_revenue * 1.05, "epsAvg": 2.2},
               {"date": "2027-12-31", "revenueAvg": fy0_revenue * 1.05 * 1.05, "epsAvg": 2.4}]
        return self.A.analyst_view(est, None, last, 50.0, "2026-06-30")

    def test_revenue_growth_starts_from_the_analysts_figure_on_another_basis(self):
        a = self.view(70.0)  # analysts forecast net revenue, the statements show gross revenue
        self.assertAlmostEqual(a["revenue_basis"]["gap"], -0.3)
        self.assertEqual([round(e["revenue_growth"], 4) for e in a["estimates"]], [0.05, 0.05])
        a = self.view(98.0)  # the same basis: growth starts from the reported figure
        self.assertNotIn("revenue_basis", a)
        self.assertAlmostEqual(a["estimates"][0]["revenue_growth"], 98 * 1.05 / 100 - 1)

    def test_share_basis(self):
        def problem(shares, cur):
            years = [{"date": f"{2021 + i}-12-31", "shares": v} for i, v in enumerate(shares)]
            return self.A.history_problem(years, [], "2000-01-01", cur)[0]
        self.assertIsNone(problem([400, 600, 700, 870, 900], 915))       # a REIT growing by share sales
        self.assertEqual(problem([200, 210, 420, 425, 430], 430), "share_basis")  # an unadjusted 2:1 split
        self.assertEqual(problem([100, 101, 102, 103, 104], 520), "share_basis")  # an ADR ratio
        self.assertIsNone(problem([1000, 900, 800, 700, 600], 590))      # steady buybacks


class TextsAndUI(unittest.TestCase):
    """Every code score.py emits has a report text and both UI translations."""

    @classmethod
    def setUpClass(cls):
        cls.src = (ROOT / "scripts" / "score.py").read_text(encoding="utf-8")
        cls.i18n = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")

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
        for q in S.QUADRANTS.values():
            self.both("q_" + q)
            self.assertIn(q, S.QUADRANT_TEXT)


class Docs(unittest.TestCase):
    """references/metrics.md section 12 states the same bands and weights as the code."""

    @classmethod
    def setUpClass(cls):
        text = (ROOT / "references" / "metrics.md").read_text(encoding="utf-8")
        cls.doc = text[text.index("## 12. Fundamental score"):]

    def test_bands(self):
        for band, (cuts, scores, unit) in S.BANDS.items():
            rule = S.rule_text({"key": band, "cuts": cuts, "scores": scores, "unit": unit})
            self.assertIn(f"| {rule} |", self.doc, band)

    def test_weights(self):
        kinds = ("general", "financial", "reit", "utility", "fee_financial")
        for p in S.PILLARS:
            keys = dict.fromkeys(k for kind in kinds for k in S.WEIGHTS[kind][p])
            for k in keys:
                cells = [f"{S.WEIGHTS[kind][p][k] * 100:.0f}%" if k in S.WEIGHTS[kind][p]
                         else "n/a" if k in S.WEIGHTS["general"][p] else "-" for kind in kinds]
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
        self.assertEqual((r["sector_kind"], r["score"]["kind"]), ("fee_financial", "fee_financial"))
        self.check_consistent(r["score"])
        keys = {i["key"]: i["status"] for p in r["score"]["pillars"].values() for i in p["indicators"]}
        self.assertEqual((keys["fwd_ev_position"], keys["altman"], keys["current_ratio"]), ("ok", "n/a", "n/a"))
        self.assertNotIn("skipped", r["dcf"])
        self.assertFalse(r["score"]["caps"])

    def test_company_type_from_the_industry(self):
        import fake_fmp
        prof = fake_fmp.SCENARIOS["QUAL"]["profile"]
        for sector, industry, kind in (("Real Estate", "Real Estate - Services", "general"),
                                       ("Real Estate", "REIT - Office", "reit"),
                                       ("Real Estate", "REIT - Mortgage", "financial")):
            with mock.patch.dict(prof, sector=sector, industry=industry):
                r = self.A.analyze(self.A.parse_args(["QUAL", "--peers", "none", "--no-market"]))
            self.assertEqual((r["sector_kind"], r["score"]["kind"]), (kind, kind), industry)

    def test_share_basis_is_checked_over_every_fiscal_year(self):
        import fake_fmp
        oldest = fake_fmp.SCENARIOS["QUAL"]["inc"][0]             # outside the forward range's 3 years
        with mock.patch.dict(oldest, weightedAverageShsOutDil=oldest["weightedAverageShsOutDil"] / 4):
            r = self.A.analyze(self.A.parse_args(["QUAL", "--peers", "none", "--no-market"]))
        pr = r["price_range"]
        self.assertEqual((pr["band_problem"], pr["trailing_problem"]), (None, "share_basis"))
        self.assertIsNone(self.results["QUAL"]["price_range"]["trailing_problem"])

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


class Batch(unittest.TestCase):
    """scripts/score_batch.py on the synthetic companies."""

    def test_batch_writes_scores_indicators_and_diff(self):
        import csv
        import tempfile
        import analyze as A
        import fake_fmp
        import score_batch as B
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(A, "FMPClient", fake_fmp.FakeClient), \
                mock.patch("sys.stdout"):
            tickers = Path(tmp) / "t.txt"
            tickers.write_text("QUAL, BANK  # two types\nnope\n", encoding="utf-8")
            self.assertEqual(B.main(["--file", str(tickers), "--out", f"{tmp}/a"]), 0)
            with open(f"{tmp}/a/scores.csv", encoding="utf-8") as f:
                rows = {r["symbol"]: r for r in csv.DictReader(f)}
            self.assertEqual(list(rows), ["QUAL", "BANK", "NOPE"])
            self.assertEqual((rows["BANK"]["kind"], rows["BANK"]["error"]), ("financial", ""))
            self.assertTrue(rows["NOPE"]["error"])
            with open(f"{tmp}/a/indicators.csv", encoding="utf-8") as f:
                inds = list(csv.DictReader(f))
            self.assertIn("fwd_pe_position", {r["indicator"] for r in inds if r["symbol"] == "QUAL"})
            self.assertEqual(B.main(["QUAL", "BANK", "--out", f"{tmp}/b", "--compare", f"{tmp}/a"]), 0)
            with open(f"{tmp}/b/diff.csv", encoding="utf-8") as f:
                self.assertEqual(list(csv.DictReader(f)), [])
