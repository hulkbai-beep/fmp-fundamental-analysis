"""The pre-result checks on a synthetic snapshot: every check passes on clean data, and the pipeline check
reproduces the skill's price_range with analysts' estimates."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import checks as C  # noqa: E402
import synth  # noqa: E402
import test_run as TR  # noqa: E402


class ChecksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.snap, cls.out = root / "snap", root / "out"
        TR.market(cls.snap)
        recs = {}
        for k, sym in enumerate(("AAA", "CCC")):
            tr = synth.company(cls.snap, sym, seed=40 + k, pe_amp=0.4)
            q = tr["quarters"]
            eps25 = sum(e for end, per, fy, e in q if fy == 2025)
            est = [{"symbol": sym, "date": f"{y}-12-31", "epsAvg": eps25 * 1.08 ** (y - 2025),
                    "epsLow": eps25 * 0.9, "epsHigh": eps25 * 1.3, "revenueAvg": None, "numAnalystsEps": 12}
                   for y in (2025, 2026, 2027, 2028)]
            (cls.snap / "raw" / "est" / f"{sym}.json").write_text(json.dumps(est))
            (cls.snap / "raw" / "profile" / f"{sym}.json").write_text(json.dumps(
                [{"symbol": sym, "price": 50.0, "marketCap": 50.0 * 100e6}]))
            recs[sym] = {"series": sym, "sector": "Tech", "spans": [["2006-01-03", "2030-01-01"]]}
            if sym == "AAA":                                   # the skill's own /light closes
                full = json.loads((cls.snap / "raw" / "full" / f"{sym}.json").read_text())
                light = [{"symbol": sym, "date": r["date"], "price": r["close"]} for r in full
                         if r["date"] >= "2021-06-01"]
                (cls.snap / "raw" / "light").mkdir(exist_ok=True)
                (cls.snap / "raw" / "light" / f"{sym}.json").write_text(json.dumps(light))
        TR.manifest(cls.snap)
        cls.sample = root / "sample.json"
        cls.sample.write_text(json.dumps({"sample": ["AAA", "CCC"], "order": {"Tech": ["AAA", "CCC"]},
                                          "spares": {"Tech": []}, "records": recs}))
        cls.spin = root / "spin.json"
        cls.spin.write_text(json.dumps({"events": {"AAA": [{"date": "2016-03-05", "confirmed": True}],
                                                   "CCC": [{"date": "2012-10-02", "confirmed": False}]}}))
        cls.rc = C.main(["--snap", str(cls.snap), "--out", str(cls.out), "--pairs", "20", "--sample", str(cls.sample),
                         "--spinoffs", str(cls.spin)])
        cls.res = json.loads((cls.out / "checks.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_pass(self):
        self.assertEqual(self.rc, 0)
        self.assertGreater(self.res["band"]["checked"], 10)
        self.assertGreater(self.res["truncation"]["checked"], 10)
        self.assertGreater(self.res["fills"]["fills"], 20)
        self.assertGreater(self.res["fills"]["plans"], self.res["fills"]["fills"] / 5)
        self.assertEqual(self.res["calendar"]["failed"], 0)
        self.assertEqual(self.res["calendar"]["bars_off_sessions"], {})

    def test_spin_off_evidence(self):
        rows = {(r["symbol"], r["source"]): r for r in self.res["spins"]}
        a = rows[("AAA", "listed")]
        self.assertEqual(a["bar"], "2016-03-07")                        # the next session after a Saturday
        self.assertEqual(len(a["closes"]), 5)
        self.assertIn("largest_drop", a)
        self.assertIsNotNone(a["implied_distribution"])
        self.assertIn(("CCC", "listed"), rows)                          # listed, confirmed or not

    def test_review_table(self):
        text = (self.out / "review.md").read_text(encoding="utf-8")
        for x in ("可用规则", "每家公司", "没有区间的交易日", "分拆核对", "各项检查", "AAA", "CCC"):
            self.assertIn(x, text)

    def test_same_results(self):
        a, b = self.out / "run_a", self.out / "run_b"
        for d, created in ((a, "x"), (b, "y")):
            d.mkdir(exist_ok=True)
            (d / "results.json").write_text(json.dumps({"created": created, "theta": 0.1}))
            (d / "plans.csv").write_text("symbol\nAAA\n")
        self.assertEqual(C.same_results(a, b), [])
        self.assertEqual(C.main(["--same", str(a), str(b)]), 0)
        self.assertEqual(json.loads((a / "repro.json").read_text()), {"same": True, "diff": []})
        (b / "results.json").write_text(json.dumps({"created": "y", "theta": 0.2}))
        self.assertEqual(C.same_results(a, b), ["results.json"])

    def test_pipeline_reproduces_price_range(self):
        pr = self.res["pipeline"]
        self.assertEqual(pr["compared"], 2)
        self.assertEqual(pr["failed"], 0)
        self.assertTrue(all(r["max_rel_diff"] <= 1e-9 for r in pr["rows"]))
        self.assertEqual(pr["not_fwd_pe"], [])                         # the primary range is the forward P/E band
        aaa = next(r for r in pr["rows"] if r["symbol"] == "AAA")
        self.assertTrue(aaa["light"]["ok"])
        self.assertEqual(aaa["light"]["over_1e-6"], 0)
        self.assertNotIn("light", next(r for r in pr["rows"] if r["symbol"] == "CCC"))


if __name__ == "__main__":
    unittest.main()
