"""End-to-end smoke test of run_pilot.py on a synthetic snapshot: the manifest check, the replacement rule, the
runs, the placebo, the benchmarks and the output files."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import panel as P  # noqa: E402
import run_pilot as R  # noqa: E402
import sim as S  # noqa: E402
import synth  # noqa: E402


def market(snap: Path):
    rnd = random.Random(2)
    days = list(synth.weekdays(dt.date(2003, 1, 2), dt.date(2026, 10, 23)))
    px, rows = 100.0, []
    for d in days:
        o = px * (1 + 0.002 * rnd.gauss(0, 1))
        px *= math.exp(0.0003 + 0.011 * rnd.gauss(0, 1))
        rows.append({"symbol": "SPY", "date": d.isoformat(), "adjOpen": o, "adjClose": px})
    for part, data in (("adj", list(reversed(rows))), ("full", list(reversed(rows)))):
        f = snap / "raw" / part / "SPY.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data))
    tr = [{"date": d.isoformat(), "month3": 2.0 + math.sin(k / 400)} for k, d in enumerate(days[::5])]
    f = snap / "raw" / "market" / "treasury.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(tr))


def manifest(snap: Path):
    files = {}
    for p in sorted((snap / "raw").rglob("*.json")):
        files[str(p.relative_to(snap)).replace("\\", "/")] = {"md5": hashlib.md5(p.read_bytes()).hexdigest()}
    (snap / "manifest.json").write_text(json.dumps({"created": "test", "files": files}))


class RunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.snap, cls.out = root / "snap", root / "out"
        market(cls.snap)
        recs = {}
        for k, (sym, sector) in enumerate((("AAA", "Tech"), ("BBB", "Tech"), ("CCC", "Energy"), ("DDD", "Energy"),
                                           ("EEE", "Tech"))):
            if sym != "BBB":                                   # BBB has no data: replaced by the spare EEE
                synth.company(cls.snap, sym, seed=20 + k, pe_amp=0.4)
            spans = [["2006-01-03", "2030-01-01"]] if sym != "DDD" else [["2010-05-03", "2019-06-03"]]
            recs[sym] = {"series": sym, "sector": sector, "spans": spans}
        manifest(cls.snap)
        cls.sample = root / "sample.json"
        cls.sample.write_text(json.dumps({"sample": ["AAA", "BBB", "CCC", "DDD"],
                                          "order": {"Tech": ["AAA", "BBB", "EEE"], "Energy": ["CCC", "DDD"]},
                                          "spares": {"Tech": ["EEE"], "Energy": []}, "records": recs}))
        spin = root / "spin.json"
        spin.write_text(json.dumps({"events": {"CCC": [{"date": "2015-03-02", "confirmed": True}]}}))
        cls.rc = R.main(["--snap", str(cls.snap), "--out", str(cls.out), "--quick", "--workers", "2",
                         "--sample", str(cls.sample), "--spinoffs", str(spin)])
        cls.res = json.loads((cls.out / "results.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_ran(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual([c["symbol"] for c in self.res["companies"]], ["AAA", "EEE", "CCC", "DDD"])
        self.assertEqual(self.res["replacements"], [{"out": "BBB", "why": "bars on 0% of member sessions",
                                                     "in": "EEE", "tried": []}])
        self.assertTrue((self.out / "plans.csv").exists())

    def test_method_matches_a_direct_run(self):
        rates = __import__("market").load(self.snap)[0]
        p = P.build("CCC", self.snap, [["2006-01-03", "2030-01-01"]], versions=("T",), spinoffs=["2015-03-02"])
        out = S.run(p, S.Rules(), rates, first_day=R.FIRST_DAY)
        rows = [x for x in csv_rows(self.out / "plans.csv") if x["symbol"] == "CCC" and x["run"] == "method_T"]
        self.assertEqual(len(rows), len(out["plans"]) + (1 if out["open"] else 0))
        self.assertFalse(any("2015-03-02" <= x["start"] <= "2016-03-01" for x in rows))   # spin-off blackout

    def test_primary_test(self):
        t = self.res["primary"]["T"]["dh252"]
        self.assertGreater(t["plans"], 20)
        self.assertGreater(t["pool"], 5 * t["plans"])
        self.assertEqual(t["placebo"]["replicas"], 200)
        self.assertTrue(0 < t["placebo"]["p_one_sided"] <= 1)
        self.assertAlmostEqual(t["year_blocks"]["theta"], t["theta"], places=12)
        for sym, x in self.res["primary"]["T"]["every_start"].items():
            self.assertEqual(x["n_missing"], 0, sym)
            self.assertLess(x["max_diff"], 1e-9, sym)
        sig = self.res["signal"]["T"]
        self.assertGreater(sig["days"], 100)
        self.assertIn("gap", sig["h252"])

    def test_report(self):
        import io
        import contextlib
        import report as RP
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(RP.main(["--res", str(self.out)]), 0)
        text = buf.getvalue()
        self.assertTrue(any(x in text for x in (RP.PROMISING, RP.NOT_PROMISING, RP.INCONCLUSIVE)))
        self.assertIn("主检验", text)

    def test_placebo_and_benchmarks(self):
        c = self.res["compare"]["T"]
        self.assertEqual(c["placebo"]["replicas"], 20)
        self.assertGreater(c["placebo"]["plans"]["placebo_mean"], 0)
        ratio = c["placebo"]["plans"]["placebo_mean"] / c["placebo"]["plans"]["method"]
        self.assertTrue(0.6 < ratio < 1.4, ratio)
        for k in ("vs_buy_hold_member", "vs_spy_matched_T", "vs_spy"):
            self.assertIn("mean", c[k])
        s = self.res["summary"]
        self.assertTrue(all(k in s for k in ("method_T", "buy_hold_member", "spy", "spy_matched_T")))
        self.assertLess(s["method_T"]["held_share"], s["buy_hold_member"]["held_share"])

    def test_walk_must_match_the_pc(self):
        sample = json.loads(self.sample.read_text())
        comps, st = R.choose(self.snap, sample)
        self.assertNotIn("same_as_pc", st)                              # no status.json: nothing to compare
        pc = self.snap / "status.json"
        try:
            pc.write_text(json.dumps(dict(st, z=st["z"])))
            self.assertTrue(R.choose(self.snap, sample)[1]["same_as_pc"])
            st["replacements"][0]["in"] = None
            pc.write_text(json.dumps(st))
            self.assertFalse(R.choose(self.snap, sample)[1]["same_as_pc"])
            self.assertEqual(R.main(["--snap", str(self.snap), "--out", str(self.out), "--quick",
                                     "--sample", str(self.sample)]), 2)
        finally:
            pc.unlink()

    def test_manifest_refuses_a_changed_file(self):
        f = self.snap / "raw" / "inc_q" / "AAA.json"
        keep = f.read_text()
        try:
            f.write_text(keep[:-1] + " ]")
            self.assertEqual(R.main(["--snap", str(self.snap), "--out", str(self.out), "--quick",
                                     "--sample", str(self.sample)]), 2)
        finally:
            f.write_text(keep)


def csv_rows(path: Path) -> list:
    import csv
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


if __name__ == "__main__":
    unittest.main()
