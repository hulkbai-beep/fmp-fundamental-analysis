"""The pre-result checks on a synthetic snapshot: every check passes on clean data, and the pipeline check
reproduces the skill's price_range with analysts' estimates."""
from __future__ import annotations

import datetime as dt
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import checks as C  # noqa: E402
import panel as P  # noqa: E402
import run_pilot as R  # noqa: E402
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
        cls.rc = C.main(["--snap", str(cls.snap), "--out", str(cls.out), "--pairs", "20", "--every-start", "60",
                         "--sample", str(cls.sample), "--spinoffs", str(cls.spin)])
        cls.res = json.loads((cls.out / "checks.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_pass(self):
        self.assertEqual(self.rc, 0)
        self.assertEqual(self.res["review"], {"written": True})
        self.assertEqual(self.res["inputs"]["spinoffs"], {"AAA": ["2016-03-05"], "CCC": []})
        self.assertEqual(self.res["checks_code"], C.RP.checks_code())
        self.assertEqual((self.res["pairs"], self.res["every_start"]), (20, 60))
        self.assertEqual(self.res["fills"]["every_start_plans"], 60)
        self.assertGreater(self.res["fills"]["pool_days"], 1000)
        self.assertGreater(self.res["band"]["checked"], 10)
        self.assertGreater(self.res["truncation"]["checked"], 10)
        self.assertGreater(self.res["fills"]["fills"], 20)
        self.assertGreater(self.res["fills"]["plans"], self.res["fills"]["fills"] / 5)
        self.assertEqual(self.res["calendar"]["failed"], 0)
        self.assertEqual(self.res["calendar"]["bars_off_sessions"], {})

    def test_one_day_leaks_are_caught(self):
        """A statement usable at the close of its own filing day (a non-strict step, or a known day one day
        early) changes T only on filing days: the truncation check must fail on it, and pass without it."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        orig_step, orig_known = P.step_at, P.known_day

        def same_day(days, vals, d, strict=True):
            return orig_step(days, vals, d, strict=False)

        def day_early(r):
            k, ph = orig_known(r)
            return (k - dt.timedelta(days=1), ph) if k and not ph else (k, ph)

        clean = C.check_truncation(self.snap, comps, 10, random.Random(5), walk["z"])
        self.assertEqual(clean["failed"], 0)
        self.assertGreater(clean["filing_day_cuts"], 0)
        for name, leak in (("step_at", same_day), ("known_day", day_early)):
            with mock.patch.object(P, name, leak):
                got = C.check_truncation(self.snap, comps, 10, random.Random(5), walk["z"])
            self.assertGreater(got["failed"], 0, name)

    def test_review_table_lists_skipped_candidates(self):
        walk = {"z": "2026-10-23", "companies": [], "review": [],
                "replacements": [{"out": "BBB", "why": "TTM EPS on 0% of member sessions", "in": "CCC",
                                  "tried": [{"key": "EEE", "why": "reused ticker (V3 bars_from / cuts)"}]},
                                 {"out": "DDD", "why": "bars on 10% of member sessions", "in": None, "tried": []}]}
        text = C.review_table(walk, {}, {}, [], {})
        self.assertIn("BBB → CCC", text)
        self.assertIn("EEE：reused ticker", text)
        self.assertIn("DDD → 找不到可用的替补", text)

    def test_late_or_early_sales_fail_the_trade_audit(self):
        """Check 6 replays every plan close by close: a stop sale filled one session late, or one session early
        (before its close signalled it), fails it; the sales as simulated pass."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        orig, moved = C.S.run, []

        def shift(by):
            def run(p, r, *a, **k):
                out = orig(p, r, *a, **k)
                for pl in out["plans"]:
                    bars = {f[0] for f in pl.filled}
                    for j, s in enumerate(pl.sold):
                        b = s[0] + by
                        if s[4] == "stop" and 0 < b < len(p.dates) and b not in bars and not moved:
                            pl.sold[j] = (b, p.o[b], s[2], s[2] * p.o[b] * (1 - r.cost), s[4])
                            moved.append(p.dates[b])
                return out
            return run
        for by in (1, -1):
            moved.clear()
            with mock.patch.object(C.S, "run", shift(by)):
                got = C.check_fills(self.snap, comps, walk["z"], {})
            self.assertEqual(len(moved), 1)
            self.assertEqual(got["failed"], 1, by)
            self.assertEqual(got["failures"][0]["replay"], "sale")
            self.assertEqual(got["failures"][0]["plan"][1:], got["failures"][0]["rules"][1:])     # stop, all shares
        self.assertEqual(C.check_fills(self.snap, comps, walk["z"], {})["failed"], 0)

    def test_the_trade_audit_reads_the_rules_apart_from_sim(self):
        """Check 6 takes the temperature, the gates and the tranche dates from SPEC, not from sim.py: a sim whose
        rich threshold is 0.70, whose gates turn plans away at a reward/risk under 1.7, or whose tranche dates
        come a weekday late, fails it; so does a sale of another size."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        temp0, gates0, days0, run0 = C.S.temp_of, C.S.gates, C.S.add_weekdays, C.S.run

        def temp(rng, r):
            return None if rng is None else "hot" if rng[3] >= 0.95 else "rich" if rng[3] > 0.70 else "fair"

        def gates(P_, stop, t1, r):
            rr, why = gates0(P_, stop, t1, r)
            return rr, why or ("reward_risk" if rr is not None and rr < 1.7 else None)

        def days(d, n):
            return days0(d, n + 1 if n else 0)

        def bigger(p, r, *a, **k):
            out = run0(p, r, *a, **k)
            pl = next(x for x in out["plans"] if any(s[4].startswith("tp_") for s in x.sold))
            j = next(j for j, s in enumerate(pl.sold) if s[4].startswith("tp_"))
            pl.sold[j] = pl.sold[j][:2] + (pl.sold[j][2] * 1.01,) + pl.sold[j][3:]
            return out
        for name, fault, kinds in (("temp_of", temp, {"buy", "sale", "end"}), ("gates", gates, {"start"}),
                                   ("add_weekdays", days, {"levels"}), ("run", bigger, {"sale"})):
            with mock.patch.object(C.S, name, fault):
                got = C.check_fills(self.snap, comps, walk["z"], {})
            self.assertGreater(got["failed"], 0, name)
            self.assertTrue({f.get("replay") for f in got["failures"]} & kinds, (name, got["failures"][:2]))
        sized = next(f for f in got["failures"] if f.get("replay") == "sale")
        self.assertAlmostEqual(sized["plan"][2], 1.01 * sized["rules"][2])       # the record shows the sizes

    def test_flags_that_read_ahead_fail_the_truncation_check(self):
        """A suspicious flag that depends on later bars (V3 flagged the 40 bars before a jump; here any bar before
        a 5% rise over the next 10 sessions) differs between the full build and one cut at the day."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        orig = P.clean_bars

        def ahead(rows, adj_rows, split_rows):
            bars, sus, rep = orig(rows, adj_rows, split_rows)
            c = [b["c"] for b in bars]
            return bars, [s or (i + 10 < len(c) and c[i + 10] > 1.05 * c[i]) for i, s in enumerate(sus)], rep
        with mock.patch.object(P, "clean_bars", ahead):
            got = C.check_truncation(self.snap, comps, 40, random.Random(5), walk["z"])
        self.assertGreater(got["failed"], 0)

    def test_review_table_shows_every_basis_finding(self):
        """Check 7's table: a split with no statement after it, an unclear one, share-count steps and EPS x
        shares / net income outliers no split explains, and each company's U1 / U2 shares."""
        basis = {"XYZ": {"basis_q": {"boundary": [
            {"split": "2026-06-15", "factor": 2.0, "action": "no row after"},
            {"split": "2016-06-06", "factor": 1.1, "action": "unclear", "ratio": 1.067, "rows_changed": 40,
             "unused_after": "2016-08-04"},
            {"split": "2012-05-01", "factor": 2.0, "action": "not_restated", "ratio": 2.01, "rows_changed": 24}],
            "share_steps": [{"older_end": "2019-03-31", "newer_end": "2019-06-30", "ratio": 1.4}],
            "review": [{"end": "2018-03-31", "eps_x_shares_over_ni": 3.0}]},
            "basis_a": {"boundary": [{"split": "2016-06-06", "factor": 1.1, "action": "unclear", "ratio": 1.2,
                                      "rows_changed": 9}]}, "annual_vs_quarters": [], "spin_candidates": []}}
        walk = {"z": "2026-10-23", "companies": [["XYZ", "XYZ", "Tech", []]], "replacements": [], "review": [],
                "assessed": {"XYZ": {"bars": 0.991, "ttm": 0.874}}}
        facts = {"XYZ": {"series": "XYZ", "sector": "Tech", "delisted": False, "first_bar": "2004-11-02",
                         "last_bar": "2026-10-23", "suspicious_member_days": 0, "jumps": 0,
                         "unclear_rows": {"basis_q": 40, "basis_a": 9}, "placeholders": {"basis_q": [0, 90],
                                                                                          "basis_a": [0, 22]},
                         "no_band": {}}}
        text = C.review_table(walk, facts, basis, [], {})
        for x in ("2026-06-15×2 之后还没有新报表", "在 2016-08-04 之后不再用于 T 版", "EPS 清空（只影响 F 版）",
                  "旧报表没重述，按倍数改（改 24 行）", "股数跳变", "2019-03-31→2019-06-30 ×1.4", "不在 0.6–1.6",
                  "| 99.1% | 87.4% |"):
            self.assertIn(x, text)

    def test_no_checks_file_without_the_review_table(self):
        """A run that fails before the review table is written leaves no checks.json, not even an earlier one."""
        out = Path(self.tmp.name) / "out_review"
        out.mkdir()
        (out / "checks.json").write_text(json.dumps({"review": {"written": True}}))
        (out / "review.md").write_text("an earlier table")
        with mock.patch.object(C, "review_table", side_effect=KeyError("rows_changed")):
            with self.assertRaises(KeyError):
                C.main(["--snap", str(self.snap), "--out", str(out), "--only", "review", "--sample", str(self.sample),
                        "--spinoffs", str(self.spin)])
        self.assertFalse((out / "checks.json").exists())
        self.assertFalse((out / "review.md").exists())

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
        digest = C.RP.results_digest({"theta": 0.1})
        self.assertEqual(json.loads((a / "repro.json").read_text()),
                         {"same": True, "diff": [], "results": [digest, digest]})
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



class PipelineLossYearTest(unittest.TestCase):
    def test_a_loss_year_ahead_shows_no_range_on_either_side(self):
        """Consensus EPS below zero for next year: the skill shows no range today and neither does the pilot,
        the skill's band over the window is still the pilot's P/E days, and the row passes."""
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d)
            q = synth.company(snap, "NEG", seed=44, pe_amp=0.4)["quarters"]
            eps25 = sum(e for end, per, fy, e in q if fy == 2025)
            est = [{"symbol": "NEG", "date": f"{y}-12-31", "epsAvg": eps25 * (1.08 if y < 2027 else -0.5),
                    "epsLow": -eps25, "epsHigh": eps25 * 1.3, "revenueAvg": None, "numAnalystsEps": 12}
                   for y in (2025, 2026, 2027, 2028)]
            (snap / "raw" / "est" / "NEG.json").write_text(json.dumps(est))
            (snap / "raw" / "profile" / "NEG.json").write_text(json.dumps(
                [{"symbol": "NEG", "price": 50.0, "marketCap": 50.0 * 100e6}]))
            got = C.check_pipeline(snap, [("NEG", "NEG", "Tech", [["2006-01-03", "2030-01-01"]])])
        self.assertEqual(got["compared"], 1)
        row = got["rows"][0]
        self.assertEqual(row["pilot_why"], "eps_not_positive")
        self.assertTrue(row["ok"])
        self.assertEqual(got["failed"], 0)


if __name__ == "__main__":
    unittest.main()
