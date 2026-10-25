"""
Offline tests for the fa-1.1 contract (scripts/contract.py, contracts/fa-1.1.schema.json). No API key needed:

    python -m unittest discover -s tests

The synthetic companies in fake_fmp.py run through analyze() and the JSON round trip that `--json` files go
through; every contract must match the schema, and its numbers must be the full result's numbers. A small
JSON Schema checker lives here so the skill keeps to the standard library.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import contract as C  # noqa: E402
import score as S  # noqa: E402

SCHEMA = json.loads((ROOT / "contracts" / f"{C.CONTRACT}.schema.json").read_text(encoding="utf-8"))
SCENARIOS = ("QUAL", "TRAP", "BANK", "EXCH", "UTIL")
TYPES = {"null": lambda x: x is None, "boolean": lambda x: isinstance(x, bool),
         "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
         "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
         "string": lambda x: isinstance(x, str), "array": lambda x: isinstance(x, list),
         "object": lambda x: isinstance(x, dict)}


def validate(inst, schema, root=SCHEMA, path="$"):
    """Errors of inst against the JSON Schema subset the contract schemas use."""
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


def as_saved(result):
    """The result as an `analyze.py --json` file holds it."""
    out = {k: v for k, v in result.items() if k not in ("price_series", "candles", "candles_note")}
    return json.loads(json.dumps(out, default=str))


class Schema(unittest.TestCase):
    def test_version_matches_the_module(self):
        self.assertEqual(SCHEMA["properties"]["contract"]["const"], C.CONTRACT)
        self.assertEqual(SCHEMA["$id"], C.CONTRACT)

    def test_every_top_level_field_is_required(self):
        self.assertEqual(set(SCHEMA["required"]), set(SCHEMA["properties"]))

    def test_the_checker_catches_drift(self):
        c = {"contract": "fa-1.1"}
        self.assertTrue(validate(c, SCHEMA))                                   # missing fields
        self.assertTrue(validate({"available": "yes"}, SCHEMA["properties"]["insider"]))
        self.assertTrue(validate([1, 2], SCHEMA["$defs"]["trio"]))
        self.assertTrue(validate({"score": 1, "weight": 0.2, "coverage": 1, "available": True, "x": 1},
                                 SCHEMA["$defs"]["pillar"]))
        self.assertTrue(validate("Buy", SCHEMA["$defs"]["label"]))
        self.assertFalse(validate([1.0, None, 2.0], SCHEMA["$defs"]["trio"]))
        self.assertTrue(validate(True, SCHEMA["$defs"]["num"]))              # a bool is not a number


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import analyze as A
        import fake_fmp
        cls.A, cls.fake = A, fake_fmp
        cls.patch = mock.patch.object(A, "FMPClient", fake_fmp.FakeClient)
        cls.patch.start()
        cls.full = {s: as_saved(A.analyze(A.parse_args([s, "--peers", "none"]))) for s in SCENARIOS}
        cls.contracts = {s: C.build(r) for s, r in cls.full.items()}

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def test_every_company_type_matches_the_schema(self):
        for sym, c in self.contracts.items():
            self.assertEqual(validate(c, SCHEMA), [], sym)
            json.dumps(c, allow_nan=False)

    def test_numbers_are_the_full_results(self):
        r, c = self.full["QUAL"], self.contracts["QUAL"]
        s = r["score"]
        self.assertEqual((c["contract"], c["rules_version"], c["ticker"]), (C.CONTRACT, S.RULES_VERSION, "QUAL"))
        self.assertEqual((c["score"]["total"], c["score"]["label"]), (s["score"], s["label"]))
        self.assertEqual(c["price"], r["current"]["price"])
        self.assertEqual({n: p["score"] for n, p in c["score"]["pillars"].items()},
                         {n: p["score"] for n, p in s["pillars"].items()})
        keys = [i["key"] for p in s["pillars"].values() for i in p["indicators"]]
        self.assertEqual(list(c["indicators"]), keys)
        fpe = next(i for i in s["pillars"]["valuation"]["indicators"] if i["key"] == "fwd_pe_position")
        self.assertEqual(c["valuation"]["fwd_pe"]["basis"], "forward_3y")
        self.assertEqual(c["valuation"]["fwd_pe"]["pctile"], fpe["value"])
        self.assertEqual(c["valuation"]["fwd_pe"]["p75"], fpe["detail"]["p75"])
        dcf = next(x for x in r["price_range"]["summary"] if x["kind"] == "dcf" and x["at"] == "now")
        self.assertEqual(c["valuation"]["ranges"]["dcf"], [dcf["low"], dcf["mid"], dcf["high"]])
        vr = s["value_range"]
        self.assertEqual(c["valuation"]["primary_range"]["basis"], vr["basis"])
        self.assertEqual(c["valuation"]["primary_range"]["range"], [vr["low"], vr["mid"], vr["high"]])
        self.assertEqual(c["valuation"]["dcf"]["value"], r["dcf"]["value_per_share"])

    def test_a_red_line_reaches_the_contract(self):
        c = self.contracts["TRAP"]
        self.assertIn("interest_coverage", [x["type"] for x in c["score"]["caps"]])
        self.assertNotIn(c["score"]["label"], ("Bullish", "Moderately bullish"))

    def test_bank_has_no_ev_band_dcf_or_fcf_yield(self):
        c = self.contracts["BANK"]
        self.assertEqual(c["company"]["kind"], "financial")
        self.assertIsNone(c["valuation"]["fwd_ev"])
        self.assertIsNone(c["valuation"]["dcf"])
        self.assertIsNone(c["valuation"]["fcf_yield_spread"])
        self.assertEqual(c["indicators"]["net_debt_ebitda"]["status"], "n/a")
        self.assertEqual(c["indicators"]["roe_level"]["status"], "ok")
        self.assertTrue(c["warnings"])                               # the sector note

    def test_reit_yield_uses_operating_cash_flow(self):
        prof = self.fake.SCENARIOS["QUAL"]["profile"]
        with mock.patch.dict(prof, sector="Real Estate", industry="REIT - Office"):
            c = C.build(as_saved(self.A.analyze(self.A.parse_args(["QUAL", "--peers", "none"]))))
        self.assertEqual(c["company"]["kind"], "reit")
        self.assertEqual(c["valuation"]["fcf_yield_spread"]["basis"], "ocf")
        self.assertEqual(self.contracts["QUAL"]["valuation"]["fcf_yield_spread"]["basis"], "fcf")
        self.assertEqual(validate(c, SCHEMA), [])

    def test_dates(self):
        r = self.full["QUAL"]
        c = self.contracts["QUAL"]
        self.assertEqual((c["as_of"], c["as_of_basis"]), (r["price_range"]["week52"]["to"], "last_close"))
        self.assertEqual(c["statements_through"], r["years"][-1]["date"][:10])
        quoted = copy.deepcopy(r)
        quoted["price_time"], quoted["ttm"] = "2026-10-23 16:00", {"date": "2026-09-30", "label": "TTM"}
        c2 = C.build(quoted)
        self.assertEqual((c2["as_of"], c2["as_of_basis"], c2["price_time"]), ("2026-10-23", "quote", "2026-10-23 16:00"))
        self.assertEqual(c2["statements_through"], "2026-09-30")
        bare = copy.deepcopy(r)
        bare["price_range"]["week52"] = None
        self.assertEqual(C.build(bare)["as_of_basis"], "run_date")

    def test_availability_says_what_is_missing_and_why(self):
        q, bank, util, trap = (self.contracts[s]["valuation"] for s in ("QUAL", "BANK", "UTIL", "TRAP"))
        self.assertEqual({v["status"] for v in q["availability"].values()}, {"ok"})
        self.assertEqual(bank["availability"]["dcf"]["reason"], "financial")
        self.assertIn("Financial-sector", bank["availability"]["dcf"]["text"])
        self.assertEqual(bank["availability"]["fwd_ev"]["reason"], "na_financial")
        self.assertEqual((util["availability"]["dcf"]["status"], util["availability"]["dcf"]["reason"]),
                         ("unavailable", "negative_fcf"))
        self.assertEqual(trap["availability"]["fwd_pe"]["reason"], "loss_making")
        self.assertEqual(trap["availability"]["primary_range"]["reason"], "no_forward_pe_or_dcf")
        self.assertIn("loss_making", trap["availability"]["primary_range"]["text"])

    def test_availability_matches_the_values(self):
        for sym, c in self.contracts.items():
            v, a = c["valuation"], c["valuation"]["availability"]
            for key in ("fwd_pe", "fwd_ev"):
                want = {None: "unavailable", "forward_3y": "ok", "trailing_vs_median": "fallback"}[(v[key] or {}).get("basis")]
                self.assertEqual(a[key]["status"], want, (sym, key))
            self.assertEqual(a["primary_range"]["status"] == "unavailable", v["primary_range"] is None, sym)
            self.assertEqual(a["fcf_yield_spread"]["status"] == "unavailable", v["fcf_yield_spread"] is None, sym)
            self.assertEqual(a["vs_industry"]["status"] == "unavailable", v["vs_industry"] is None, sym)
            self.assertEqual(a["reverse_dcf"]["status"] == "unavailable", v["reverse_dcf"]["gap"] is None, sym)
            if a["dcf"]["status"] == "ok":
                self.assertGreater(v["dcf"]["value"], 0, sym)
            for key, state in a.items():
                if state["status"] != "ok":
                    self.assertTrue(state["reason"] and state["text"], (sym, key))

    def test_insider_states(self):
        c = self.contracts["QUAL"]["insider"]
        self.assertTrue(c["available"])
        self.assertIsInstance(c["open_market_buys"], int)
        r = copy.deepcopy(self.full["QUAL"])
        r["insider"] = None
        self.assertEqual(C.build(r)["insider"], {"available": False, "reason": "skipped (--no-insider)"})
        r["insider"] = {"restricted": True}
        self.assertEqual(C.build(r)["insider"]["reason"], "not in the FMP plan")
        for x in (C.build(r), self.contracts["QUAL"]):
            self.assertEqual(validate(x, SCHEMA), [])

    def test_flag_and_file_give_the_same_contract(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("sys.stdout"):
            full, direct, from_file = (str(Path(tmp) / n) for n in ("full.json", "direct.json", "file.json"))
            self.assertEqual(self.A.main(["QUAL", "--peers", "none", "--json", full, "--contract", direct]), 0)
            self.assertEqual(C.main([full, "-o", from_file]), 0)
            a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (direct, from_file))
        self.assertEqual(a, b)
        self.assertRegex(a["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertEqual(validate(a, SCHEMA), [])

    def test_unreadable_file(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(C.main([str(ROOT / "no-such-file.json")]), 1)


class Docs(unittest.TestCase):
    def test_skill_and_readmes_mention_the_contract(self):
        for name in ("SKILL.md", "README.md", "README.en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertTrue("--contract" in text and C.CONTRACT in text, name)


if __name__ == "__main__":
    unittest.main()
