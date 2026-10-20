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

    def test_cap_never_raises_a_low_score(self):
        r = {"years": [{"interest_expense": 100, "ebit": 120, "net_debt": 1000}]}
        s = stubbed_score({"valuation": -1, "quality": -1, "growth": -1, "health": -1}, r)
        self.assertEqual(s["score"], -1.0)
        self.assertFalse(s["capped"])
        self.assertEqual([c["type"] for c in s["caps"]], ["interest_coverage"])

    def test_red_line_caps_a_high_score(self):
        r = {"years": [{"interest_expense": 100, "ebit": 120, "net_debt": 1000}]}
        s = stubbed_score({"valuation": 2, "quality": 2, "growth": 2, "health": 2}, r)
        self.assertEqual(s["score"], 0.4)
        self.assertTrue(s["capped"])

    def test_red_lines(self):
        def types(r, kind="general"):
            return [c["type"] for c in S.red_lines(r, kind)]
        self.assertEqual(types({"altman": {"z_zone": "distress", "z2_zone": "distress"}}), ["altman_distress"])
        self.assertEqual(types({"altman": {"z_zone": "distress", "z2_zone": "grey"}}), [])
        self.assertEqual(types({"years": [{"interest_expense": 100, "ebit": 149, "net_debt": 1}]}), ["interest_coverage"])
        self.assertEqual(types({"years": [{"interest_expense": 100, "ebit": 150, "net_debt": 1}]}), [])
        self.assertEqual(types({"years": [{"interest_expense": 100, "ebit": 50, "net_debt": -1}]}), [])
        burn = {"years": [{"fcf": -1, "net_debt": 5}, {"fcf": -2, "net_debt": 5}]}
        self.assertEqual(types(burn), ["cash_burn"])
        self.assertEqual(types({"years": [{"fcf": 1, "net_debt": 5}, {"fcf": -2, "net_debt": 5}]}), [])
        self.assertEqual(types({"years": [{"equity": -1, "interest_expense": 100, "ebit": 0, "net_debt": 9}]},
                               "financial"), ["negative_equity"])


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
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe")
        self.assertEqual((ind["score"], ind["note"], ind["unit"]), (2, "trailing_history", "pct"))
        r["history_compare"]["pe"]["n"] = 2
        self.assertEqual(S._multiple_position(r, "fwd_pe_position", "pe_band", "pe")["status"], "missing")

    def test_multiple_position_uses_forward_band(self):
        r = {"price_range": {"pe_band": {"now_pct": 0.40, "now": 18, "p25": 16, "median": 20, "p75": 24,
                                         "from": "2023-10-20", "to": "2026-10-20"}}}
        ind = S._multiple_position(r, "fwd_pe_position", "pe_band", "pe")
        self.assertEqual((ind["score"], ind["unit"]), (1, "pctile"))

    def test_current_ratio_below_one_is_not_penalised_with_net_cash(self):
        self.assertEqual(S._current_ratio({"current_ratio": 0.8, "net_debt": -1})["note"], "cash_rich")
        self.assertEqual(S._current_ratio({"current_ratio": 0.8, "net_debt": -1})["score"], 0)
        self.assertEqual(S._current_ratio({"current_ratio": 0.8, "net_debt": 1, "fcf_margin": 0.05})["score"], -1)

    def test_interest_coverage_without_interest(self):
        self.assertEqual(S._coverage({"interest_expense": 0, "debt": 0})["score"], 2)
        self.assertEqual(S._coverage({"interest_expense": 0, "debt": 10, "net_debt": 5})["status"], "missing")
        self.assertEqual(S._coverage({"interest_expense": 10, "ebit": 100})["score"], 1)  # 10x

    def test_reit_leverage_bands(self):
        L = {"net_debt": 5, "ebitda": 1}
        self.assertEqual(S._net_debt_ebitda(L, "general")["score"], -2)
        self.assertEqual(S._net_debt_ebitda(L, "reit")["score"], 0)
        self.assertEqual(S._net_debt_ebitda({"net_debt": -5, "ebitda": 1}, "general")["note"], "net_cash")

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
        for _b, name in S.LABELS + ((None, "Bearish"),):
            self.both(f'lbl_{name}')
        for n in S.PILLARS:
            self.both("p_" + n)


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
        for sym in ("QUAL", "TRAP", "BANK"):
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
