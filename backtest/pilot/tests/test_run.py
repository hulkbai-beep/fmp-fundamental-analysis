"""End-to-end test of run_pilot.py on a synthetic snapshot: the manifest check, the replacement rule, the runs
of both versions and the four variants, the primary test, the signal test, the benchmarks, the output files and
the report."""
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
import market as M  # noqa: E402
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
    if not (snap / "fetch_log.json").exists():                     # as the PC writes it: nothing failed
        (snap / "fetch_log.json").write_text(json.dumps({"failures": [], "optional_missing": []}))
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
        cls.rc = R.main(["--snap", str(cls.snap), "--out", str(cls.out), "--plan-replicas", "200", "--workers", "4",
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
        for name in ("plans.csv", "portfolio.json", "pools_T.json", "pools_F.json", "status.json"):
            self.assertTrue((self.out / name).exists(), name)
        pools = json.loads((self.out / "pools_T.json").read_text())
        self.assertEqual(sorted(pools), ["AAA", "CCC", "DDD", "EEE"])
        status = json.loads((self.out / "status.json").read_text())
        self.assertEqual(status["z"], self.res["walk"]["z"])

    def test_void_plans_are_rows(self):
        rows = csv_rows(self.out / "plans.csv")
        void = [x for x in rows if x["first_fill"] == ""]
        self.assertGreater(len(void), 0)
        self.assertTrue(all(x["ret"] == "" and x["tranches"] == "0" and float(x["dh252"]) == 0.0 for x in void))
        self.assertTrue({x["status"] for x in void} <= {"lapsed", "expired", "cancelled_below_stop", "spin",
                                                         "unfilled"})

    def test_method_matches_a_direct_run(self):
        import placebo as PL
        rates = __import__("market").load(self.snap)[0]
        p = P.build("CCC", self.snap, [["2006-01-03", "2030-01-01"]], versions=("T",), spinoffs=["2015-03-02"],
                    snapshot_end=self.res["walk"]["z"])
        out = S.run(p, S.Rules(), rates, first_day=R.FIRST_DAY)
        rows = [x for x in csv_rows(self.out / "plans.csv") if x["symbol"] == "CCC" and x["run"] == "method_T"]
        self.assertEqual(sorted(x["start"] for x in rows), sorted(p.dates[pl.start] for pl in PL.method_plans(out)))
        self.assertFalse(any("2015-02-27" <= x["start"] <= "2016-03-01" for x in rows))   # spin-off blackout

    def test_primary_test(self):
        for v in ("T", "F"):
            t = self.res["primary"][v]["dh252"]
            self.assertGreater(t["plans"], 20)
            self.assertGreater(t["pool"], 5 * t["plans"])
            self.assertEqual(t["placebo"]["replicas"], 200)
            self.assertTrue(0 < t["placebo"]["p_one_sided"] <= 1)
            self.assertAlmostEqual(t["year_blocks"]["theta"], t["theta"], places=12)
            lo = t["leave_one_company_out"]
            self.assertLessEqual(lo["min"], lo["max"])
            for sym, x in self.res["primary"][v]["every_start"].items():
                self.assertEqual(x["n_missing"], 0, sym)
                self.assertLess(x["max_diff"], 1e-9, sym)
        sig = self.res["signal"]["T"]
        self.assertGreater(sig["days"], 100)
        self.assertIn("gap", sig["h252"])

    def test_signal_days_are_full_window_pool_days(self):
        pools = json.loads((self.out / "pools_T.json").read_text())
        sample = set(json.loads((self.out / "portfolio.json").read_text())["dates"][::R.SIGNAL_EVERY])
        full = sum(1 for x in pools.values() for d, f in zip(x["day"], x["full252"]) if f and d in sample)
        self.assertEqual(self.res["signal"]["T"]["days"], full)

    def test_variants(self):
        vt = self.res["variant_tests"]
        self.assertEqual(sorted(vt), sorted(R.VARIANTS))
        for name, x in vt.items():
            self.assertIsNotNone(x["dh252"]["theta"], name)
            self.assertIsNone(x["dh252"]["placebo"], name)            # descriptive: no p-value
            self.assertEqual(x["own_table"], name != "V8_cooldown_20", name)
            for sym, e in x["every_start"].items():
                self.assertEqual(e["n_missing"], 0, (name, sym))
                self.assertLess(e["max_diff"], 1e-9, (name, sym))
        d = self.res["describe"]["T"]
        self.assertEqual(d["plans"], self.res["primary"]["T"]["dh252"]["plans"])
        self.assertAlmostEqual(d["mean"]["dh252"], self.res["primary"]["T"]["dh252"]["strategy_mean"], places=12)
        self.assertAlmostEqual(d["pool_mean"]["dh252"], self.res["primary"]["T"]["dh252"]["placebo_expectation"],
                               places=12)
        g = self.res["gates"]["T"]
        self.assertEqual(g["below_mid"], g["pass"] + g["stop_too_far"] + g["reward_risk"])
        self.assertGreater(self.res["t_vs_f"]["days"], 1000)

    def test_report(self):
        import io
        import contextlib
        import report as RP
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(RP.main(["--res", str(self.out)]), 0)
        text = buf.getvalue()
        self.assertIn(RP.NO_RESULT, text)                               # no checks.json, no rerun: no result
        for x in ("主检验", "四个对照版本", "V-a", "F 版"):
            self.assertIn(x, text)

    def test_decision_rule(self):
        import report as RP
        t = {"theta": 0.004, "placebo": {"percentile": 0.9}, "leave_one_year_out": {"min": 0.001},
             "without_top3": {"theta": 0.002}}
        sig = {"h252": {"gap": {"theta": 0.01}}}
        self.assertEqual(RP.decide(t, sig, True)[0], RP.PROMISING)
        self.assertEqual(RP.decide(t, sig, False)[0], RP.NO_RESULT)
        self.assertEqual(RP.decide(dict(t, placebo={"percentile": 0.7}), sig, True)[0], RP.INCONCLUSIVE)
        self.assertEqual(RP.decide(t, {"h252": {"gap": {"theta": -0.01}}}, True)[0], RP.INCONCLUSIVE)
        self.assertEqual(RP.decide(dict(t, theta=-0.001), sig, True)[0], RP.NOT_PROMISING)
        self.assertEqual(RP.decide(dict(t, leave_one_year_out={"min": -0.001}), sig, True)[0], RP.NOT_PROMISING)
        self.assertEqual(RP.decide(dict(t, without_top3={"theta": 0.0}), sig, True)[0], RP.NOT_PROMISING)
        self.assertEqual(RP.decide(dict(t, placebo={"percentile": 0.3}), sig, True)[0], RP.INCONCLUSIVE)
        self.assertIn("很强的反面证据", RP.f_reading(RP.NOT_PROMISING, -0.001, -0.002)[0])
        self.assertIn("说明不了什么", RP.f_reading(RP.NOT_PROMISING, -0.001, 0.003)[0])
        self.assertEqual(RP.f_reading(RP.NO_RESULT, 0.1, 0.1), [])

    def test_checks_gate_the_result(self):
        import report as RP
        ch = {k: {"failed": 0} for k, _ in RP.CHECKS}
        self.assertEqual(RP.checks_pass(self.res, ch, {"same": True, "diff": []}), (True, []))
        ok, notes = RP.checks_pass(self.res, dict(ch, fills={"failed": 2}), {"same": True, "diff": []})
        self.assertFalse(ok)
        self.assertFalse(RP.checks_pass(self.res, ch, None)[0])
        self.assertFalse(RP.checks_pass(self.res, {k: v for k, v in ch.items() if k != "band"},
                                        {"same": True, "diff": []})[0])

    def test_benchmarks(self):
        c = self.res["compare"]["T"]
        for k in ("vs_buy_hold_member", "vs_spy_matched_T", "vs_spy"):
            self.assertIn("mean", c[k])
        s = self.res["summary"]
        self.assertTrue(all(k in s for k in ("method_T", "buy_hold_member", "spy", "spy_matched_T", "method_F")))
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

    def test_failed_or_missing_parts_refuse(self):
        """A part that failed on the PC, or a chosen company's part that is not in the snapshot at all (read as
        empty data otherwise), stops the run even when every file present matches the manifest."""
        log = self.snap / "fetch_log.json"
        keep = log.read_text()
        try:
            log.write_text(json.dumps({"failures": [{"part": "splits", "symbol": "AAA", "error": "HTTP 500"}],
                                       "optional_missing": []}))
            self.assertEqual(M.check_complete(self.snap, ["AAA"]), ["failed on the PC: splits/AAA"])
            self.assertEqual(R.main(["--snap", str(self.snap), "--out", str(self.out), "--quick",
                                     "--sample", str(self.sample)]), 2)
        finally:
            log.write_text(keep)
        f = self.snap / "raw" / "div" / "CCC.json"
        data = f.read_bytes()
        try:
            f.unlink()
            manifest(self.snap)
            self.assertEqual(M.check_complete(self.snap, ["CCC"]), ["missing: raw/div/CCC.json"])
            self.assertEqual(R.main(["--snap", str(self.snap), "--out", str(self.out), "--quick",
                                     "--sample", str(self.sample)]), 2)
        finally:
            f.write_bytes(data)
            manifest(self.snap)
        self.assertEqual(M.check_complete(self.snap, ["AAA", "CCC", "DDD", "EEE"]), [])

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
