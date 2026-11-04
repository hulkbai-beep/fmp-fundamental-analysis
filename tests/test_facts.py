"""
Offline tests for fa-2.0, the facts document (scripts/facts.py, contracts/fa-2.0.schema.json). No API key needed:

    python -m unittest discover -s tests

fa-2.0 holds facts only; the fundamental score belongs to the decision engine, whose tests check that the score
rebuilds from this document. Here: every synthetic company's document matches the schema and lines its columns
up, no judgement word creeps in, missing values say why, and full results saved by v1.x still convert to the
documents 8c5ceed's facts.py made from them (tests/data/saved_8c5ceed.json). A small JSON Schema checker lives
here so the skill keeps to the standard library.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import facts as F  # noqa: E402
import fake_fmp  # noqa: E402

SCHEMA = json.loads((ROOT / "contracts" / f"{F.FACTS}.schema.json").read_text(encoding="utf-8"))
SAVED = json.loads((ROOT / "tests" / "data" / "saved_8c5ceed.json").read_text(encoding="utf-8"))["cases"]
SCENARIOS = ("QUAL", "TRAP", "BANK", "EXCH", "UTIL", "QTRS", "ADJE", "REIT")
FULL, DOCS = {}, {}   # analyze()'s internal results in their JSON form, and their fa-2.0 documents

# No key, and no code, may hold one of these words (models.piotroski.score is the model's own name for its count).
JUDGEMENT = {"score", "rating", "rated", "bull", "bullish", "bear", "bearish", "cheap", "expensive", "undervalued",
             "overvalued", "target", "upside", "downside", "buy", "sell", "signal", "recommend", "recommendation",
             "verdict", "attractive", "label", "confidence", "pillar", "flag", "flags", "safety"}
FREE_TEXT = {"company.name", "company.exchange", "company.sector", "company.industry", "peers[].name",
             "data_quality.restricted[]", "data_quality.errors[]", "data_quality.route"}
CODES = {"status", "kind", "method", "reason", "id", "source", "basis", "as_of_basis", "fcf_start_basis",
         "growth_source", "beta_source", "history_basis", "z_zone", "z2_zone", "not_meaningful"}
TYPES = {"null": lambda x: x is None, "boolean": lambda x: isinstance(x, bool),
         "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
         "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
         "string": lambda x: isinstance(x, str), "array": lambda x: isinstance(x, list),
         "object": lambda x: isinstance(x, dict)}


def validate(inst, schema=SCHEMA, root=SCHEMA, path="$"):
    """Errors of inst against the JSON Schema subset the fa-2.0 schema uses."""
    errs = []
    if "$ref" in schema:
        errs += validate(inst, root["$defs"][schema["$ref"].rsplit("/", 1)[-1]], root, path)
    if "const" in schema and inst != schema["const"]:
        errs.append(f"{path}: {inst!r} is not {schema['const']!r}")
    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} not in {schema['enum']}")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(TYPES[t](inst) for t in types):
            return errs + [f"{path}: {type(inst).__name__} is not {types}"]
    if isinstance(inst, dict):
        props = schema.get("properties", {})
        errs += [f"{path}: missing {k}" for k in schema.get("required", []) if k not in inst]
        for k, v in inst.items():
            extra = schema.get("additionalProperties", True)
            if k in props:
                errs += validate(v, props[k], root, f"{path}.{k}")
            elif extra is False:
                errs.append(f"{path}: unexpected {k}")
            elif isinstance(extra, dict):
                errs += validate(v, extra, root, f"{path}.{k}")
    if isinstance(inst, list):
        if len(inst) < schema.get("minItems", 0) or len(inst) > schema.get("maxItems", len(inst)):
            errs.append(f"{path}: {len(inst)} items")
        if "items" in schema:
            for i, v in enumerate(inst):
                errs += validate(v, schema["items"], root, f"{path}[{i}]")
    return errs


def jsonable(x):
    return json.loads(json.dumps(x, default=str))


def text(doc):
    """The document as comparable text: -0.0 vs 0.0 or True vs 1 differ here, not with ==."""
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


def at(doc, path):
    for k in path.split("."):
        doc = doc[k]
    return doc


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


def setUpModule():
    import analyze as A
    with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient):
        FULL.update({s: jsonable(A.analyze(A.parse_args([s, "--peers", "none"]))) for s in SCENARIOS})
    DOCS.update({s: F.build(r) for s, r in FULL.items()})


# ---------------------------------------------------------------------------- variations of an internal result
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
    """The share count changed basis inside the price history: no forward bands, no comparable history."""
    r["forward_bands"].update(trailing_problem="share_basis", band_problem="share_basis", pe_band=None, ev_band=None)
    return r


def no_market(r):
    """--no-market: no Treasury yields and no industry P/E."""
    r["market"] = None
    return r


def no_estimates(r):
    """No analyst coverage."""
    r["analyst"]["estimates"] = []
    r["forward_bands"].update(pe_band=None, ev_band=None, forward=None)
    return r


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
    """Market data without Treasury yields; the risk premium and the industry P/E are still there."""
    r["market"]["rates"] = None
    return r


def no_industry_pe(r):
    """No industry P/E: the comparison falls back to the sector."""
    r["market"]["sector"].update(industry_pe=None, vs_industry=None)
    return r


def short_history(r):
    """Estimates, but too little price history for a forward band, and no fiscal-year-end history either."""
    r["forward_bands"].update(pe_band=None, ev_band=None)
    r["history_compare"] = {}
    return r


# each variation and what its document must then say
VARIATIONS = (
    (with_ttm, {"periods.valuation_basis": "TTM", "ttm.period": "TTM", "statements_through": TTM_END}),
    (adjusted_estimates, {"consensus.vs_reported.eps.gap": 0.22, "consensus.vs_reported.ebitda.gap": 0.15}),
    (other_currency, {"company.statement_currency": "JPY",
                      "data_quality.currency_mismatch": {"statements": "JPY", "price": "USD"}}),
    (share_basis, {"valuation.forward_band.status": "share_basis", "valuation.forward_band.pe.status": "share_basis",
                   "valuation.forward_band.ev_ebitda.status": "share_basis",
                   "valuation.vs_own_history.status": "share_basis"}),
    (no_market, {"rates": None, "valuation.vs_group": None}),
    (no_estimates, {"valuation.forward_band.status": "no_estimates", "valuation.forward.ntm": None,
                    "valuation.forward.pe_ntm": None, "valuation.forward.fy1": None, "consensus.estimates": []}),
    (revenue_basis, {"consensus.vs_reported.revenue.gap": 0.2}),
    (implied_below_range, {"models.reverse_dcf.status": "below_range", "models.reverse_dcf.implied_growth_1_5": None}),
    (implied_above_range, {"models.reverse_dcf.status": "above_range"}),
    (no_rates, {"rates.date": None, "rates.treasury_10y": None}),
    (no_industry_pe, {"valuation.vs_group.industry.status": "unavailable", "valuation.vs_group.industry.premium": None,
                      "valuation.vs_group.sector.status": "ok"}),
    (short_history, {"valuation.forward_band.status": "short_history",
                     "valuation.forward_band.pe.status": "short_history", "valuation.vs_own_history.pe": None}),
)


# ---------------------------------------------------------------------------- tests
class Schema(unittest.TestCase):
    def test_version_matches_the_module(self):
        self.assertEqual(SCHEMA["properties"]["contract"]["const"], F.FACTS)
        self.assertEqual(SCHEMA["$id"], F.FACTS)
        self.assertEqual((F.FACTS, F.METHOD_VERSION), ("fa-2.0", "2.0.0"))

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
        errs = validate(f)
        self.assertEqual(len(errs), 3, errs)

    def test_the_word_check_catches_judgements(self):
        self.assertEqual(judgements({"valuation": {"upside": 0.2, "now": {"pe": 20}}}), ["valuation.upside"])
        self.assertTrue(judgements({"models": {"dcf": {"status": "Undervalued"}}}))
        self.assertTrue(judgements({"x": {"method": "CAPM rate"}}))
        self.assertEqual(judgements({"company": {"name": "Target Corp"}, "models": {"piotroski": {"score": 7}}}), [])


class Documents(unittest.TestCase):
    def test_every_company_matches_the_schema(self):
        for sym, f in DOCS.items():
            self.assertEqual(validate(f), [], sym)
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

    def test_numbers_are_the_internal_results(self):
        r, f = FULL["QUAL"], DOCS["QUAL"]
        self.assertEqual(f["statements"]["revenue"], [y["revenue"] for y in r["years"]])
        self.assertEqual(f["statements"]["eps_diluted"], [y["eps"] for y in r["years"]])
        self.assertEqual(f["metrics"]["roic"], [y["roic"] for y in r["years"]])
        self.assertEqual(f["price"]["value"], r["current"]["price"])
        self.assertEqual(f["valuation"]["now"]["pe"], r["current"]["pe"])
        self.assertEqual(f["valuation"]["forward_band"]["pe"]["p25"], r["forward_bands"]["pe_band"]["p25"])
        self.assertEqual(f["valuation"]["forward_band"]["pe"]["pctile"], r["forward_bands"]["pe_band"]["now_pct"])
        self.assertEqual(f["valuation"]["forward"]["ntm"]["eps"], r["forward_bands"]["forward"]["eps"])
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

    def test_variations_say_why_values_are_missing(self):
        for change, want in VARIATIONS:
            for sym in ("QUAL", "TRAP"):
                f = F.build(change(copy.deepcopy(FULL[sym])))
                case = (sym, change.__name__)
                self.assertEqual(validate(f), [], case)
                self.assertEqual(judgements(f), [], case)
                self.assertEqual({p: at(f, p) for p in want}, want, case)
                self.assertNotEqual(text(f), text(DOCS[sym]), f"{case}: the variation changes nothing")

    def test_dates(self):
        for sym, r in FULL.items():
            f = DOCS[sym]
            self.assertEqual(r["last_close"], fake_fmp.SCENARIOS[sym]["prices"][-1][0], sym)
            self.assertEqual((f["as_of"], f["as_of_basis"], f["statements_through"]),
                             (r["last_close"], "last_close", (r["ttm"] or r["years"][-1])["date"]), sym)
        r = copy.deepcopy(FULL["QUAL"])
        r["price_time"] = "2026-10-23 16:00"
        f = F.build(r)
        self.assertEqual((f["as_of"], f["as_of_basis"], f["price"]["source"], f["price"]["time"]),
                         ("2026-10-23", "quote", "quote", "2026-10-23 16:00"))
        r["price_time"] = None
        self.assertEqual(F.build(r)["price"]["source"], "profile")
        r["last_close"] = None   # fewer than two closes in the past year
        self.assertEqual((F.build(r)["as_of"], F.build(r)["as_of_basis"]), (r["as_of"], "run_date"))

    def test_what_v2_leaves_out(self):
        for sym, r in FULL.items():
            self.assertEqual(set(r) & {"score", "flags", "insider", "price_range", "price_series", "candles",
                                       "candles_note", "self_snapshot", "sector_note"}, set(), sym)
            self.assertNotIn("margin_of_safety", r["dcf"], sym)
            self.assertNotIn("price_target", r["analyst"], sym)
            self.assertEqual(set(r["forward_bands"]), {"lookback_years", "pe_band", "ev_band", "band_problem",
                                                       "trailing_problem", "forward"}, sym)
            self.assertEqual(set(r["forward_bands"]["forward"]), {"at", "fy", "date", "uses", "weight", "eps",
                                                                  "eps_low", "eps_high", "ebitda"}, sym)
            self.assertEqual(set(r["market"]), {"rates", "erp", "capm", "sector"}, sym)   # no --macro
            self.assertNotIn("returns", r["market"]["sector"], sym)
            self.assertNotIn("insider", DOCS[sym], sym)
        self.assertNotIn("insider", SCHEMA["properties"])


class SavedResults(unittest.TestCase):
    """Full results saved by v1.x still convert: the decision engine converts old runs with this facts.py."""

    def test_results_saved_at_8c5ceed_give_the_documents_it_made(self):
        for case, c in SAVED.items():
            want = dict(c["facts"], generated_at=c["full"]["generated_at"])
            self.assertEqual(text(F.build(copy.deepcopy(c["full"]))), text(want), case)

    def test_the_internal_result_and_a_saved_one_say_the_same(self):
        """forward_bands and last_close of the internal result give the document that price_range gave."""
        for case, c in SAVED.items():
            r = copy.deepcopy(c["full"])
            pr = r.pop("price_range")
            now = next(p for p in pr["forward"] if p["at"] == "now")
            r["last_close"] = pr["week52"]["to"]
            r["forward_bands"] = dict({k: pr[k] for k in ("lookback_years", "pe_band", "ev_band", "band_problem",
                                                          "trailing_problem")},
                                      forward={k: now[k] for k in ("at", "fy", "date", "uses", "weight", "eps",
                                                                   "eps_low", "eps_high", "ebitda")})
            self.assertEqual(text(F.build(r)), text(F.build(c["full"])), case)

    def test_files_saved_by_earlier_versions_still_convert(self):
        """A saved result without the keys added while v1.0 was being built (generated_at, market data, peers, TTM,
        quote time, connection, trailing_problem) still converts."""
        r = copy.deepcopy(SAVED["QUAL"]["full"])
        for k in ("generated_at", "market", "peers", "ttm", "price_time"):
            r.pop(k, None)
        r["meta"].pop("connection")
        r["price_range"].pop("trailing_problem")
        f = F.build(r)
        self.assertEqual(validate(f), [])
        self.assertEqual((f["rates"], f["valuation"]["vs_group"], f["data_quality"]["route"]), (None, None, None))
        self.assertEqual((f["generated_at"], f["price"]["source"]), (r["as_of"], "profile"))
        self.assertEqual((f["as_of"], f["as_of_basis"]), (r["price_range"]["week52"]["to"], "last_close"))
        self.assertEqual(f["valuation"]["vs_own_history"]["status"], "ok")
        r["price_range"]["band_problem"] = "price_jump"   # before trailing_problem, band_problem stood for both checks
        self.assertEqual(F.build(r)["valuation"]["vs_own_history"]["status"], "price_jump")

    def test_a_document_that_is_already_fa_2_is_returned_as_it_is(self):
        f = DOCS["QUAL"]
        self.assertIs(F.build(f), f)
        later = dict(f, contract="fa-2.3")
        self.assertIs(F.build(later), later)


class Docs(unittest.TestCase):
    def test_skill_and_readmes_mention_the_facts(self):
        for name in ("SKILL.md", "README.md", "README.en.md"):
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertTrue("--facts" in content and F.FACTS in content, name)


if __name__ == "__main__":
    unittest.main()
