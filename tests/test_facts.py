"""
Offline tests for fa-2.0, the facts output (scripts/facts.py, contracts/fa-2.0.schema.json). No API key needed:

    python -m unittest discover -s tests

fa-2.0 holds facts only; the fundamental score belongs to the decision engine. The tests check that every
synthetic company's document matches the schema and lines its columns up, that no judgement word creeps in,
and that the score can be rebuilt from the document alone: score.py on fa2_score_input.to_score_input(document)
gives the full result's score for 8 companies, 6 variations of 4 of them (24 cases) and a few rarer paths.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import contract as C  # noqa: E402
import facts as F  # noqa: E402
import fake_fmp  # noqa: E402
import score as S  # noqa: E402
from fa2_score_input import to_score_input  # noqa: E402
from test_contract import as_saved, validate  # noqa: E402

SCHEMA = json.loads((ROOT / "contracts" / f"{F.FACTS}.schema.json").read_text(encoding="utf-8"))
SCENARIOS = ("QUAL", "TRAP", "BANK", "EXCH", "UTIL", "QTRS", "ADJE", "REIT")
FULL, DOCS = {}, {}

# No key, and no code, may hold one of these words (models.piotroski.score is the model's own name for its count).
JUDGEMENT = {"score", "rating", "rated", "bull", "bullish", "bear", "bearish", "cheap", "expensive", "undervalued",
             "overvalued", "target", "upside", "downside", "buy", "sell", "signal", "recommend", "recommendation",
             "verdict", "attractive", "label", "confidence", "pillar", "flag", "flags", "safety"}
FREE_TEXT = {"company.name", "company.exchange", "company.sector", "company.industry", "peers[].name",
             "data_quality.restricted[]", "data_quality.errors[]", "data_quality.route"}
CODES = {"status", "kind", "method", "reason", "id", "source", "basis", "as_of_basis", "fcf_start_basis",
         "growth_source", "beta_source", "history_basis", "z_zone", "z2_zone", "not_meaningful"}


def jsonable(x):
    return json.loads(json.dumps(x, default=str))


def leaves(x, path=""):
    """(path, key, value) for every key and list item; list items have key None and [] in the path."""
    items = x.items() if isinstance(x, dict) else ((None, v) for v in x) if isinstance(x, list) else ()
    for k, v in items:
        p = (f"{path}.{k}" if path else k) if k is not None else path + "[]"
        yield p, k, v
        yield from leaves(v, p)


def judgements(doc):
    """Keys and strings that carry a judgement word, and codes that are not snake_case."""
    out = []
    for path, key, v in leaves(doc):
        if key is not None and path != "models.piotroski.score" and JUDGEMENT & set(key.split("_")):
            out.append(path)
        if isinstance(v, str) and path not in FREE_TEXT and JUDGEMENT & set(re.split(r"[^a-z0-9]+", v.lower())):
            out.append(f"{path} = {v!r}")
        name = path.rsplit(".", 1)[-1].replace("[]", "")
        if name in CODES and isinstance(v, str) and not re.fullmatch(r"[a-z0-9_]+", v):
            out.append(f"{path} = {v!r} is not a code")
    return out


def rebuilt(r):
    """The score computed from the fa-2.0 document of r alone, as the decision engine will."""
    return jsonable(S.score(to_score_input(jsonable(F.build(r)))))


def setUpModule():
    import analyze as A
    with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient):
        FULL.update({s: as_saved(A.analyze(A.parse_args([s, "--peers", "none"]))) for s in SCENARIOS})
    DOCS.update({s: F.build(r) for s, r in FULL.items()})


# ---------------------------------------------------------------------------- variations of a full result
TTM_END = f"{fake_fmp.LAST_FY + 1}-06-30"


def with_ttm(r):
    """Quarterly statements: the valuation moves to trailing-twelve-month figures."""
    last = r["years"][-1]
    r["ttm"] = r["basis"] = dict(last, label="TTM", fy="TTM", date=TTM_END, fcf=last["fcf"] * 1.1,
                                 ocf=last["ocf"] * 1.05)
    return r


def adjusted_estimates(r):
    """Analysts' figures for the last reported year well above the reported ones (adjusted EPS and EBITDA)."""
    last, a = r["years"][-1], r["analyst"]
    a["eps_basis"] = {"fy": last["label"], "estimate": last["eps"] * 1.22, "reported": last["eps"], "gap": 0.22}
    a["ebitda_basis"] = {"fy": last["label"], "estimate": last["ebitda"] * 1.15, "reported": last["ebitda"],
                         "gap": 0.15}
    return r


def other_currency(r):
    """Statements in JPY, the price in USD (an ADR)."""
    for y in r["years"]:
        y["currency"] = "JPY"
    return r


def share_basis(r):
    """The share count changed basis inside the price history: no forward range and no trailing fallback."""
    pr = r["price_range"]
    pr.update(trailing_problem="share_basis", band_problem="share_basis", pe_band=None, ev_band=None,
              band_note="share basis changed")
    for pt in pr["forward"]:
        pt["pe"] = pt["ev"] = None
    return r


def no_market(r):
    """--no-market: no Treasury yields and no industry P/E."""
    r["market"] = None
    return r


def no_estimates(r):
    """No analyst coverage."""
    r["analyst"]["estimates"] = []
    r["price_range"].update(pe_band=None, ev_band=None, forward=[])
    return r


VARIATIONS = (with_ttm, adjusted_estimates, other_currency, share_basis, no_market, no_estimates)


def revenue_basis(r):
    last = r["years"][-1]
    r["analyst"]["revenue_basis"] = {"fy": last["label"], "estimate": last["revenue"] * 1.2,
                                     "reported": last["revenue"], "gap": 0.2}
    return r


def implied_below_range(r):
    r["dcf"].update(implied_growth=None,
                    implied_growth_note="below -50%/yr (price is below even a shrinking-FCF value)")
    return r


def implied_above_range(r):
    r["dcf"].update(implied_growth=None, implied_growth_note="above 100%/yr")
    return r


def no_rates(r):
    """Market data without Treasury yields; the industry P/E is still there."""
    r["market"]["rates"] = None
    return r


def no_industry_pe(r):
    """No industry P/E: the comparison falls back to the sector."""
    r["market"]["sector"].update(industry_pe=None, vs_industry=None)
    return r


def short_history(r):
    """Estimates, but too little price history for a forward range, and no fiscal-year-end history either."""
    share_basis(r)["price_range"].update(trailing_problem=None, band_problem=None,
                                         band_note="Not enough positive-earnings price history")
    r["history_compare"] = {}
    return r


def saved_before_trailing_problem(r):
    """A file saved before price_range.trailing_problem existed: band_problem stood for both checks."""
    share_basis(r)["price_range"].pop("trailing_problem")
    r["price_range"]["band_problem"] = "price_jump"
    return r


RARER = (revenue_basis, implied_below_range, implied_above_range, no_rates, no_industry_pe, short_history,
         saved_before_trailing_problem)


# ---------------------------------------------------------------------------- tests
class Schema(unittest.TestCase):
    def test_version_matches_the_module(self):
        self.assertEqual(SCHEMA["properties"]["contract"]["const"], F.FACTS)
        self.assertEqual(SCHEMA["$id"], F.FACTS)

    def test_every_object_always_has_all_its_keys(self):
        def objects(node, path="$"):
            if isinstance(node, dict):
                if "properties" in node:
                    yield path, node
                for k, v in node.items():
                    yield from objects(v, f"{path}.{k}")
            elif isinstance(node, list):
                for v in node:
                    yield from objects(v, path)
        for path, node in objects(SCHEMA):
            self.assertEqual(set(node["required"]), set(node["properties"]), path)
            self.assertIs(node.get("additionalProperties"), False, path)

    def test_the_checker_catches_drift(self):
        f = copy.deepcopy(DOCS["QUAL"])
        f["models"]["dcf"]["status"] = "cheap"
        f["metrics"]["roic"][0] = "high"
        del f["valuation"]["forward"]["pe_ntm"]
        errs = validate(f, SCHEMA, SCHEMA)
        self.assertEqual(len(errs), 3, errs)

    def test_the_word_check_catches_judgements(self):
        self.assertEqual(judgements({"valuation": {"upside": 0.2, "now": {"pe": 20}}}), ["valuation.upside"])
        self.assertTrue(judgements({"models": {"dcf": {"status": "Undervalued"}}}))
        self.assertTrue(judgements({"x": {"method": "CAPM rate"}}))
        self.assertEqual(judgements({"company": {"name": "Target Corp"}, "models": {"piotroski": {"score": 7}}}), [])


class Documents(unittest.TestCase):
    def test_every_company_matches_the_schema(self):
        for sym, f in DOCS.items():
            self.assertEqual(validate(f, SCHEMA, SCHEMA), [], sym)
            json.dumps(f, allow_nan=False)

    def test_no_judgement_words(self):
        for sym, f in DOCS.items():
            self.assertEqual(judgements(f), [], sym)

    def test_columns_line_up_with_their_periods(self):
        for sym, f in DOCS.items():
            st = f["statements"]
            self.assertEqual(st["period"], f["periods"]["fiscal_years"], sym)
            for block in (st, f["metrics"]):
                self.assertEqual({len(v) for v in block.values()}, {len(st["period"])}, sym)
            self.assertEqual(len({len(v) for v in f["valuation"]["history"].values()}), 1, sym)
            sens = f["models"]["dcf"]["sensitivity"]
            if sens:
                self.assertEqual(len(sens["value_per_share"]), len(sens["discount_rates"]), sym)
                self.assertEqual({len(row) for row in sens["value_per_share"]}, {len(sens["growth_1_5"])}, sym)

    def test_numbers_are_the_full_results(self):
        r, f = FULL["QUAL"], DOCS["QUAL"]
        self.assertEqual(f["statements"]["revenue"], [y["revenue"] for y in r["years"]])
        self.assertEqual(f["statements"]["eps_diluted"], [y["eps"] for y in r["years"]])
        self.assertEqual(f["metrics"]["roic"], [y["roic"] for y in r["years"]])
        self.assertEqual(f["price"]["value"], r["current"]["price"])
        self.assertEqual(f["valuation"]["now"]["pe"], r["current"]["pe"])
        self.assertEqual(f["valuation"]["forward_band"]["pe"]["p25"], r["price_range"]["pe_band"]["p25"])
        self.assertEqual(f["valuation"]["forward_band"]["pe"]["pctile"], r["price_range"]["pe_band"]["now_pct"])
        self.assertEqual(f["models"]["dcf"]["value_per_share"], r["dcf"]["value_per_share"])
        self.assertEqual(f["models"]["reverse_dcf"]["implied_growth_1_5"], r["dcf"]["implied_growth"])
        self.assertEqual(f["models"]["piotroski"]["score"], r["piotroski"]["score"])
        self.assertEqual(f["growth"]["cagr"]["revenue"], r["cagr"]["revenue"])
        self.assertEqual(f["models"]["dcf"]["inputs"]["discount_rate"]["method"], "capm")
        for sym, f in DOCS.items():   # forward multiples now: one formula with the band's "now"
            v = f["valuation"]
            for key, band in (("pe_ntm", "pe"), ("ev_ebitda_ntm", "ev_ebitda")):
                if v["forward_band"][band]["status"] == "ok":
                    self.assertEqual(v["forward"][key], v["forward_band"][band]["now"], (sym, key))

    def test_company_types_and_missing_values_say_why(self):
        bank, util, trap, reit, qtrs, adje = (DOCS[s] for s in ("BANK", "UTIL", "TRAP", "REIT", "QTRS", "ADJE"))
        self.assertEqual((bank["company"]["kind"], bank["models"]["dcf"]["status"],
                          bank["models"]["reverse_dcf"]["status"],
                          bank["valuation"]["forward_band"]["ev_ebitda"]["status"]),
                         ("financial", "skipped_financial", "no_dcf", "not_applicable"))
        self.assertIn("dcf", bank["company"]["not_meaningful"])
        self.assertEqual(DOCS["EXCH"]["company"]["kind"], "fee_financial")
        self.assertEqual(util["models"]["dcf"]["status"], "fcf_not_positive")
        self.assertEqual(trap["models"]["dcf"]["status"], "value_not_positive")
        self.assertLessEqual(trap["models"]["dcf"]["value_per_share"], 0)
        self.assertEqual((reit["company"]["kind"], reit["models"]["altman"]["status"]), ("reit", "not_meaningful"))
        self.assertEqual((qtrs["periods"]["valuation_basis"], qtrs["ttm"]["period"], qtrs["ttm"]["currency"]),
                         ("TTM", "TTM", "USD"))
        self.assertEqual(qtrs["statements_through"], qtrs["ttm"]["end"])
        self.assertIsNone(DOCS["QUAL"]["ttm"])
        self.assertGreater(adje["consensus"]["vs_reported"]["eps"]["gap"], 0.5)   # analysts forecast adjusted EPS

    def test_dates_agree_with_the_contract(self):
        for sym, r in FULL.items():
            c, f = C.build(r), DOCS[sym]
            self.assertEqual((f["as_of"], f["as_of_basis"], f["statements_through"]),
                             (c["as_of"], c["as_of_basis"], c["statements_through"]), sym)
        r = copy.deepcopy(FULL["QUAL"])
        r["price_time"] = "2026-10-23 16:00"
        f = F.build(r)
        self.assertEqual((f["as_of"], f["as_of_basis"], f["price"]["source"], f["price"]["time"]),
                         ("2026-10-23", "quote", "quote", "2026-10-23 16:00"))
        r["price_time"] = None
        self.assertEqual(F.build(r)["price"]["source"], "profile")

    def test_files_saved_by_earlier_versions_still_convert(self):
        r = copy.deepcopy(FULL["QUAL"])
        for k in ("generated_at", "market", "peers", "ttm", "price_time"):
            r.pop(k, None)
        r["meta"].pop("connection")
        r["price_range"].pop("trailing_problem")
        f = F.build(r)
        self.assertEqual(validate(f, SCHEMA, SCHEMA), [])
        self.assertEqual((f["rates"], f["valuation"]["vs_group"], f["data_quality"]["route"]), (None, None, None))
        self.assertEqual((f["generated_at"], f["price"]["source"]), (r["as_of"], "profile"))

    def test_insider_trades_are_left_out(self):
        self.assertTrue(FULL["QUAL"]["insider"])               # the full result still has them, for the report
        for f in DOCS.values():
            self.assertNotIn("insider", f)
        self.assertNotIn("insider", SCHEMA["properties"])


class ScoreFromFacts(unittest.TestCase):
    """The decision engine can rebuild the fundamental score from fa-2.0 alone."""

    def test_every_company(self):
        for sym, r in FULL.items():
            self.assertEqual(rebuilt(r), jsonable(r["score"]), sym)

    def test_variations(self):
        for change in VARIATIONS:
            changed = 0
            for sym in ("QUAL", "TRAP", "BANK", "UTIL"):
                r = change(copy.deepcopy(FULL[sym]))
                want = jsonable(S.score(copy.deepcopy(r)))
                self.assertEqual(rebuilt(r), want, (sym, change.__name__))
                changed += want != jsonable(FULL[sym]["score"])
            self.assertTrue(changed, f"{change.__name__} changes no score: it tests nothing")

    def test_rarer_paths(self):
        for change in RARER:
            for sym in ("QUAL", "TRAP"):
                r = change(copy.deepcopy(FULL[sym]))
                self.assertEqual(rebuilt(r), jsonable(S.score(copy.deepcopy(r))), (sym, change.__name__))


class Cli(unittest.TestCase):
    def test_flag_and_file_give_the_same_document(self):
        import analyze as A
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(A, "FMPClient", fake_fmp.FakeClient), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            full, direct, from_file = (str(Path(tmp) / n) for n in ("full.json", "direct.json", "file.json"))
            self.assertEqual(A.main(["QTRS", "--peers", "none", "--json", full, "--facts", direct]), 0)
            self.assertEqual(C.main([full, "--facts", "-o", from_file]), 0)
            a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (direct, from_file))
        self.assertEqual(a, b)
        self.assertEqual((a["contract"], a["ticker"]), (F.FACTS, "QTRS"))
        self.assertEqual(validate(a, SCHEMA, SCHEMA), [])
        self.assertTrue(out.getvalue().startswith("# "))       # stdout is the report alone
        self.assertIn(f"({F.FACTS} facts written to {direct})", err.getvalue())
        self.assertIn(f"({F.FACTS} facts written to {from_file})", err.getvalue())


class Docs(unittest.TestCase):
    def test_skill_and_readmes_mention_the_facts(self):
        for name in ("SKILL.md", "README.md", "README.en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertTrue("--facts" in text and F.FACTS in text, name)


if __name__ == "__main__":
    unittest.main()
