"""The pre-result checks on a synthetic snapshot: every check passes on clean data, and the pipeline check
reproduces the skill's price_range with analysts' estimates."""
from __future__ import annotations

import bisect
import contextlib
import datetime as dt
import json
import random
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
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
        cls.rc = C.main(["--snap", str(cls.snap), "--out", str(cls.out), "--pairs", "20",
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
        self.assertEqual(self.res["pairs"], 20)
        self.assertEqual(self.res["fills"]["every_start_plans"], self.res["fills"]["pool_days"])   # every one
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
            pl = next((x for x in out["plans"] if any(s[4].startswith("tp_") for s in x.sold)), None)
            if pl:
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

    def test_the_every_start_table_is_replayed_in_full(self):
        """Check 6 replays every plan of the placebo's every-start table, as run_pilot makes it: a table whose
        plans start on the next pool day, or whose plans are not of size 1, fails it, and so does a sim that
        sells a session late only in plans simulated alone (the method's plans then all pass), or one whose
        metrics are off only in those plans, their trades unchanged (SPEC amendment 25: only the table's plans
        are simulated alone, so only their recomputed metrics see such a fault)."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        comps = comps[:1]
        table, run0 = C.PL.every_start, C.S.run

        def next_day(*a, **k):
            plans = table(*a, **k)
            return plans[1:] + plans[:1]

        def sized(*a, **k):
            plans = table(*a, **k)
            for pl in plans[:3]:
                pl.size = 0.99
            return plans

        def late(p, r, *a, **k):
            out = run0(p, r, *a, **k)
            for pl in out["plans"] if k.get("single") else []:
                for j, s in enumerate(pl.sold):
                    b = s[0] + 1
                    if s[4] == "stop" and b < len(p.dates) and b not in {f[0] for f in pl.filled}:
                        pl.sold[j] = (b, p.o[b], s[2], s[2] * p.o[b] * (1 - r.cost), s[4])
                        break
            return out

        def off(p, r, *a, **k):
            out = run0(p, r, *a, **k)
            for pl in C.PL.method_plans(out) if k.get("single") else []:
                pl.m["dh252"] *= 1.01
            return out
        for obj, name, fault, kinds in ((C.PL, "every_start", next_day, {"table"}),
                                        (C.PL, "every_start", sized, {"table", "buy"}), (C.S, "run", late, {"sale"}),
                                        (C.S, "run", off, {"metrics"})):
            with mock.patch.object(obj, name, fault):
                got = C.check_fills(self.snap, comps, walk["z"], {})
            self.assertGreater(got["failed"], 0, name)
            self.assertEqual({f.get("replay") for f in got["failures"]}, kinds, (name, got["failures"][:2]))
            self.assertTrue(all(f.get("every_start") for f in got["failures"]), name)
        self.assertEqual(got["every_start_plans"], got["pool_days"])

    def test_the_audited_plans_are_the_tabulated_ones(self):
        """Check 6 records a digest of the plans it replayed, the method's and the every-start table's, and
        run_pilot.py one of the tables it tabulates, the rows theta comes from: on the code as it is they are
        equal; a placebo.pool that drops the plans started on hot days, which the replay (running
        placebo.every_start itself) never sees, or a placebo.columns that calls a window full five sessions
        early, makes them differ, and report.py then gives no label."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        key, sym, sector, spans = comps[0]
        rates, spy = C.M.load(self.snap)
        cal = [d for d in spy.days if R.FIRST_DAY <= d <= walk["z"]]
        spin = {"AAA": ["2016-03-05"]}.get(key, [])
        args = (self.snap, key, sym, sector, spans, spin, R.VERSIONS, {}, cal, R.accrual(cal, rates))

        def digests(res):
            return {v: {"method": R.table_digest(res["strategy"][v]), "pool": R.table_digest(res["pool"][v])}
                    for v in R.VERSIONS}
        self.assertEqual(digests(R.company_runs(args)), {v: self.res["fills"]["tables"][v][key] for v in R.VERSIONS})
        pool0 = C.PL.pool

        def cold(*a, **k):
            cols = pool0(*a, **k)
            keep = [j for j, t in enumerate(cols["temp0"]) if t != "hot"]
            self.assertLess(len(keep), len(cols["temp0"]))
            return {c: [x[j] for j in keep] for c, x in cols.items()}
        with mock.patch.object(C.PL, "pool", cold):
            got = digests(R.company_runs(args))
        for v in R.VERSIONS:
            self.assertEqual(got[v]["method"], self.res["fills"]["tables"][v][key]["method"])
            self.assertNotEqual(got[v]["pool"], self.res["fills"]["tables"][v][key]["pool"])
        cols0 = C.PL.columns

        def early(p, plans, sess, zi):
            return cols0(p, plans, sess, zi + 5)
        with mock.patch.object(C.PL, "columns", early):
            got = digests(R.company_runs(args))
        self.assertNotEqual(got["T"]["pool"], self.res["fills"]["tables"]["T"][key]["pool"])    # F's pool ends
        self.assertEqual(got["F"]["pool"], self.res["fills"]["tables"]["F"][key]["pool"])       # at its horizon

        def longer(*a, **k):                    # a column with a value more than the table has rows
            cols = pool0(*a, **k)
            return dict(cols, dh252=cols["dh252"] + [0.0])

        def shifted(*a, **k):                   # the start's bar one late, its day right
            cols = pool0(*a, **k)
            return dict(cols, start=[i + 1 for i in cols["start"]])
        for fault in (longer, shifted):
            with mock.patch.object(C.PL, "pool", fault):
                got = digests(R.company_runs(args))
            for v in R.VERSIONS:
                self.assertNotEqual(got[v]["pool"], self.res["fills"]["tables"][v][key]["pool"], fault.__name__)

    def test_the_hedge_and_the_metrics_are_audited_apart(self):
        """Check 6 reads SPY's sessions, opens and closes itself (Hedge) and recomputes the metrics of every
        plan it replays from the plan's trades (plan_metrics): on the code as it is nothing differs by more than
        1e-9. The hedge's opens taken from its closes, its session numbers one late, sim's window a session
        short, the metrics scaled after the run, or a run from a day after 2008-01-02, each with the trades
        unchanged, fail it."""
        self.assertLess(self.res["fills"]["metrics_worst"], 1e-9)
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        hedge0, sess0, metrics0 = R.hedge_of, C.PL.sessions, C.S.Plan.metrics

        def closes(p, spy):
            o, c, s = hedge0(p, spy)
            return c, c, s

        def late(dates, days):
            return [s + 1 for s in sess0(dates, days)]

        def scaled(pl):
            m = metrics0(pl)
            return dict(m, dh252=m["dh252"] * 1.01)
        for patch, kinds in ((mock.patch.object(C.R, "hedge_of", closes), {"hedge", "metrics"}),
                             (mock.patch.object(C.PL, "sessions", late), {"hedge"}),
                             (mock.patch.object(C.S, "H_LONG", 251), {"metrics"}),
                             (mock.patch.object(C.S.Plan, "metrics", scaled), {"metrics"}),
                             (mock.patch.object(C.R, "FIRST_DAY", "2008-01-03"), {"range"})):
            with patch:
                got = C.check_fills(self.snap, comps[:1], walk["z"], {})
            self.assertTrue(kinds <= {f.get("replay") for f in got["failures"]}, (kinds, got["failures"][:2]))
        p = P.build(comps[0][1], self.snap, comps[0][3], snapshot_end=walk["z"])
        self.assertIn("2008-01-02", p.dates)                        # the late run lost a bar

    def test_the_dividends_are_audited_apart(self):
        """Check 6 reads the dividends file itself (SPEC 4, checks.dividends): panel.build's dividends dropped, or
        each one bar late, and a dividends file whose fields SPEC 4 does not name, each with the trades as the run
        makes them, fail it."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        build0 = P.build

        def faulty(late):
            def build(*a, **k):
                p = build0(*a, **k)
                return replace(p, div=[0.0] + p.div[:-1] if late else [0.0] * len(p.div))
            return build
        for late in (False, True):
            with mock.patch.object(C.P, "build", faulty(late)):
                got = C.check_fills(self.snap, comps[:1], walk["z"], {})
            self.assertIn("dividends", {f.get("replay") for f in got["failures"]}, late)
        f = self.snap / "raw" / "div" / f"{comps[0][1]}.json"
        keep = f.read_text()
        try:
            f.write_text(json.dumps([{"date": r["date"], "adj_dividend": r["adjDividend"]} for r in json.loads(keep)]))
            got = C.check_fills(self.snap, comps[:1], walk["z"], {})
        finally:
            f.write_text(keep)
        self.assertEqual([(x["replay"], x["bars"], x["read"]) for x in got["failures"] if x.get("replay") == "dividends"],
                         [("dividends", 0, 0)])

    def test_the_start_fields_are_audited(self):
        """Check 6 compares each replayed plan's start temperature, percentile and mid (what the tables' temp0
        and below_mid and plans.csv's pct0 and vs_mid read) with the start's range: a sim that stores one of them
        wrong, its decisions unchanged, fails it."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        for name in ("temp0", "pct0", "mid0"):
            @dataclass
            class Wrong(C.S.Plan):
                def __post_init__(self, name=name):
                    setattr(self, name, "hot" if name == "temp0" and self.temp0 != "hot" else
                            "cold" if name == "temp0" else getattr(self, name) * 1.01)
            with mock.patch.object(C.S, "Plan", Wrong):
                got = C.check_fills(self.snap, comps[:1], walk["z"], {})
            self.assertEqual({f.get("replay") for f in got["failures"]}, {"levels"}, name)
            self.assertEqual(list(got["failures"][0]["plan"]), [name])

    def test_the_data_reviews_entries_must_name_one_row(self):
        """Check 'fixes' (SPEC amendment 29): a correction that names exactly one statement row passes; one whose
        filing date names no row, one that names a row twice over and an exclusion that ends before it starts
        fail it; entries of a company the run does not hold are listed, and review.md lists every entry."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        self.assertEqual((self.res["fixes"]["failed"], self.res["fixes"]["entries"]), (0, {}))
        self.assertIn("## 数据审查的修正", (self.out / "review.md").read_text())
        sym = comps[0][1]
        q = json.loads((self.snap / "raw" / "inc_q" / f"{sym}.json").read_text())[5]
        right = {"kind": "inc_q", "date": q["date"][:10], "filed": q["filingDate"][:10], "set": {"epsDiluted": 1.0},
                 "why": "w"}
        path = Path(self.tmp.name) / "fixes_check.json"
        entries = {"rows": [right, dict(right, filed="1999-01-01")],
                   "exclude": [{"version": "T", "from": "2019-01-02", "to": "2018-06-28", "why": "w"}]}
        path.write_text(json.dumps({"companies": {sym: entries, "ZZZ": {"rows": [right]}}}))
        got = C.check_fixes(self.snap, comps, walk["z"], path)
        self.assertEqual((got["checked"], got["failed"], got["not_in_run"]), (3, 2, ["ZZZ"]))
        self.assertEqual([x.get("filed", "exclude") for x in got["failures"]], ["1999-01-01", "exclude"])
        f = self.snap / "raw" / "inc_q" / f"{sym}.json"
        keep = f.read_text()
        try:
            f.write_text(json.dumps(json.loads(keep) + [q]))                # the same row twice
            path.write_text(json.dumps({"companies": {sym: {"rows": [right]}}}))
            got = C.check_fixes(self.snap, comps, walk["z"], path)
        finally:
            f.write_text(keep)
        self.assertEqual([(x["date"], x["rows"]) for x in got["failures"]], [(right["date"], 2)])
        text = C.review_table(walk, {}, {}, [], {"fixes": C.check_fixes(self.snap, comps, walk["z"], path)})
        self.assertIn(f"- {sym} 季报 {right['date']}（{right['filed']} 公布）：epsDiluted 改为 1.0。w", text)

    def test_the_limits_check_finds_the_shapes_it_guards(self):
        """Check 'limits' (SPEC amendment 24): the clean synthetic companies pass; an unclear split whose epoch
        reaches member days (synth.late_verdict A), a quarter filed again after a split (B) and a quarter first
        filed after a split though a later one was filed before it (C) fail it."""
        self.assertEqual({k: self.res["limits"][k] for k in ("checked", "held_epochs", "failed")},
                         {"checked": 2, "held_epochs": 0, "failed": 0})
        tmp = tempfile.TemporaryDirectory()
        snap = Path(tmp.name)
        got = {}
        for shape in ("A", "B"):
            synth.late_verdict(snap, f"LV{shape}0", shape, False)
            got[shape] = C.check_limits(snap, [(f"LV{shape}0", f"LV{shape}0", "Tech", [["2005-01-03", "2030-01-01"]])],
                                        "2026-10-23")
        self.assertEqual([x["symbol"] for x in got["A"]["reaching"]], ["LVA0"])
        self.assertEqual([(x["end"], x["splits"]) for x in got["B"]["refiled_across_split"]],
                         [("2016-03-31", ["2016-06-06"])])
        synth.company(snap, "LVC0", seed=7, split=(dt.date(2016, 6, 6), 2.0))
        path = snap / "raw" / "inc_q" / "LVC0.json"
        rows = json.loads(path.read_text())
        for r in rows:
            if r["date"] == "2015-12-31":
                r["filingDate"], r["acceptedDate"] = "2016-07-15", "2016-07-15 16:05:00"
        path.write_text(json.dumps(rows))
        got["C"] = C.check_limits(snap, [("LVC0", "LVC0", "Tech", [["2005-01-03", "2030-01-01"]])], "2026-10-23")
        self.assertEqual([(x["statements"], x["end"], x["split"], x["latest_end_before"])
                          for x in got["C"]["filed_late_across_split"]], [("inc_q", "2015-12-31", "2016-06-06", "2016-03-31")])
        self.assertEqual(got["A"]["filed_late_across_split"] + got["B"]["filed_late_across_split"], [])
        self.assertTrue(all(x["failed"] for x in got.values()))
        tmp.cleanup()

    def test_a_run_that_starts_late_fails_the_pool_check(self):
        """Check 6 tests the pool of start days against the rule over SPEC's range (2008-01-02 to the bar before
        the last), not over the run's own first and last bars: a method run that starts after the first pool
        day takes that day out of the pool and of the every-start table, and the check says so."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        run0, cand = C.S.run, C.PL.candidates

        def late(p, r, rates, first_day=None, **k):
            out = run0(p, r, rates, first_day=first_day, **k)
            if k.get("single"):
                return out
            return run0(p, r, rates, first_day=p.dates[cand(p, r, out["first"], out["last"])[0] + 1], **k)
        with mock.patch.object(C.S, "run", late):
            got = C.check_fills(self.snap, comps[:1], walk["z"], {})
        self.assertIn("pool", {f.get("replay") for f in got["failures"]}, got["failures"][:2])

    def test_the_band_check_reads_the_quarters_each_version_reads(self):
        """Check 3 takes the share check's latest quarter from the quarters each version reads: T's of the day's
        epoch (an unclear split's old statements as filed), F's with every split decided on the full data. On
        splits whose share-count verdict comes after the first statement after them (synth.late_verdict) both
        versions pass, on days up to that statement and after it."""
        tmp = tempfile.TemporaryDirectory()
        snap, comps = Path(tmp.name), []
        for shape, other in (("A", False), ("B", False), ("B", True)):
            sym = f"LV{shape}{int(other)}"
            synth.late_verdict(snap, sym, shape, other)
            comps.append((sym, sym, "Tech", [["2005-01-03", "2030-01-01"]]))
        p = P.build(comps[0][1], snap, comps[0][3], versions=("T",))
        k = bisect.bisect_right(p.dates, "2016-11-04")
        want = set(range(k - 100, k)) | set(range(bisect.bisect_left(p.dates, R.FIRST_DAY), k, 50))

        class Days(random.Random):
            def sample(self, pop, n):
                pop = list(pop)
                return pop if not pop or not isinstance(pop[0], int) else [i for i in pop if i in want]
        got = C.check_band(snap, comps, 10 ** 6, Days(), "2026-10-23")
        self.assertEqual((got["checked"], got["failed"]), (2 * len(comps) * len(want), 0), got["failures"][:2])
        tmp.cleanup()

    def test_the_band_check_follows_spin_offs_and_the_data_review(self):
        """Check 3 builds the panels as the run does, with the confirmed spin-offs and the data review's entries:
        on the days a spin-off's restart (checks.restarts, read apart from panel.build) or an exclusion leaves
        without a band there must be none, and after a restart (an exclusion's: the day after its last) the band
        is the skill's over the window from the restart on; every company with a restart is checked on the days
        around it too. A build that ignores the spin-off or the exclusion, or whose window after a restart still
        holds the days before it, fails it."""
        tmp = tempfile.TemporaryDirectory()
        snap = Path(tmp.name)
        synth.company(snap, "SPN", seed=16)
        comps = [("SPN", "SPN", "Tech", [["2005-01-03", "2030-01-01"]])]
        x, ex = "2016-03-07", {"version": "F", "from": "2019-01-02", "to": "2019-06-28"}
        restart = {"T": "2017-03-08", "F": "2017-01-01"}
        dates = P.build("SPN", snap, comps[0][3], versions=("T",)).dates
        want = set(range(bisect.bisect_left(dates, R.FIRST_DAY), len(dates), 40))
        for e in (x, "2016-12-30", "2017-01-02", "2017-03-08", "2019-01-02", "2019-06-28", "2020-01-02", "2020-03-09"):
            k = bisect.bisect_left(dates, e)
            want |= set(range(k - 3, k + 3))

        class Days(random.Random):
            def sample(self, pop, n):
                pop = list(pop)
                return pop if not pop or not isinstance(pop[0], int) else [i for i in pop if i in want]
        bands0, build0 = P.bands, P.build

        def no_restart(dates, close, eps, why_eps, years, q_shares, first_day, resets=()):
            out, why = bands0(dates, close, eps, why_eps, years, q_shares, first_day)
            for a, b in resets:                      # no band in the span, but the window keeps the days before it
                for i in range(bisect.bisect_left(dates, a), bisect.bisect_left(dates, b)):
                    out[i], why[i] = None, "spin_reset"
            return out, why

        def ignoring(**over):
            return lambda *a, **k: build0(*a, **dict(k, **over))
        got = {}
        with mock.patch.object(P, "fixes_of", lambda sym, path=P.FIXES: {"exclude": [ex]}):
            for name, patch in (("right", contextlib.nullcontext()), ("no restart", mock.patch.object(P, "bands", no_restart)),
                                ("no spin-off", mock.patch.object(P, "build", ignoring(spinoffs=[]))),
                                ("no exclusion", mock.patch.object(P, "build", ignoring(fixes={})))):
                with patch:
                    got[name] = C.check_band(snap, comps, 10 ** 6, Days(), "2026-10-23", {"SPN": [x]})
        right = got["right"]
        self.assertEqual((right["checked"], right["failed"], right["restart_companies"]),
                         (2 * len(want) + right["near_restarts"], 0, 1), right["failures"][:2])
        self.assertGreaterEqual(right["near_restarts"], 2 * 20)
        late = got["no restart"]["failures"]
        self.assertTrue(late and all(f["code"] is None and (restart[f["version"]] <= f["day"] < "2020-03-09" or
                                                            f["version"] == "F" and ex["to"] < f["day"] < "2022-06-30")
                                     for f in late))
        self.assertEqual({(f["version"], f["code"]) for f in got["no spin-off"]["failures"] if f["day"] < restart["F"]},
                         {("T", "no band expected"), ("F", "no band expected")})
        off = got["no exclusion"]["failures"]
        self.assertEqual({(f["version"], f["code"], f["day"] <= ex["to"]) for f in off},
                         {("F", "no band expected", True), ("F", None, False)})
        self.assertTrue(all(ex["from"] <= f["day"] < "2022-06-30" for f in off))
        tmp.cleanup()

    def test_a_trigger_close_without_an_atr_has_no_chase_limit(self):
        """SPEC R5's chase limit needs the trigger close's ATR. Without one (or with 0; neither happens on a
        panel.build panel after its 14th bar, so they are planted here) sim buys the tranche uncapped, the
        replay does too, and so does the per-fill audit."""
        comps, walk = R.choose(self.snap, json.loads(self.sample.read_text()))
        key, sym, sector, spans = comps[0]
        p = P.build(sym, self.snap, spans, versions=R.VERSIONS, snapshot_end=walk["z"])
        out = C.S.run(p, C.S.Rules(version="T"), C.M.load(self.snap)[0], first_day=R.FIRST_DAY)
        pl = next(x for x in out["plans"] if len(x.filled) >= 3)
        holes, orig = {pl.filled[1][0] - 1: None, pl.filled[2][0] - 1: 0.0}, P.build

        def build(*a, **k):
            q = orig(*a, **k)
            for j, v in holes.items():
                q.atr[j] = v
            return q
        with mock.patch.object(P, "build", build):
            got = C.check_fills(self.snap, comps[:1], walk["z"], {})
        self.assertEqual(got["failed"], 0, got["failures"][:2])

    def test_an_epoch_that_ends_a_day_early_fails_the_truncation_check(self):
        """Version T's choice of epoch is made in panel.build, apart from normalize_basis. A build whose T drops
        the old statements on the very day the first statement after an unclear split is filed (d < end in
        place of d <= end) acts on that statement before the day it may: a cut on that filing day shows it,
        since the cut removes that statement and with it the end of the epoch."""
        tmp = tempfile.TemporaryDirectory()
        snap, when = Path(tmp.name), dt.date(2016, 6, 6)
        synth.company(snap, "UNC", seed=33, split=(when, 1.1))
        path = snap / "raw" / "inc_q" / "UNC.json"
        rows = json.loads(path.read_text())
        for r in rows:
            if r["filingDate"] >= when.isoformat():
                r["weightedAverageShsOutDil"] *= 0.97
        path.write_text(json.dumps(rows))
        first = min(r["filingDate"] for r in rows if r["filingDate"] >= when.isoformat())
        comps = [("UNC", "UNC", "Tech", [["2005-01-03", "2030-01-01"]])]

        class OnlyFirst:                            # the cuts: that filing day alone
            def sample(self, pop, k):
                return [x for x in pop if x == first]
        orig = P.build

        def early(*a, **k):
            p = orig(*a, **k)
            ep = p.epochs["T"]
            p.eps["T"] = [ep[next(j for j, (u, _) in enumerate(ep) if u is None or d < u)][1][i]
                          for i, d in enumerate(p.dates)]
            return p
        self.assertEqual(C.check_truncation(snap, comps, 2, OnlyFirst(), "2026-10-23")["failed"], 0)
        with mock.patch.object(P, "build", early):
            got = C.check_truncation(snap, comps, 2, OnlyFirst(), "2026-10-23")
        self.assertEqual((got["checked"], got["filing_day_cuts"], got["failed"]), (1, 1, 1))
        tmp.cleanup()

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
            {"split": "2014-03-03", "factor": 1.05, "action": "unclear", "ratio": None, "rows_changed": 31,
             "unused_after": "2014-05-05", "verdict_known": None},
            {"split": "2013-03-04", "factor": 1.05, "action": "unclear", "ratio": 1.01, "rows_changed": 29,
             "unused_after": "2013-04-10", "verdict_known": "2013-05-06"},
            {"split": "2012-05-01", "factor": 2.0, "action": "not_restated", "ratio": 2.01, "rows_changed": 24}],
            "eps_shares": [{"end": "2010-03-31", "ratio": 1.98, "fixed_by": 2.0, "splits": ["2012-05-01"]}],
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
                  "拆股后的报表里还没有能判定口径的", "能判定口径的报表 2013-05-06 才公布",
                  "2010-03-31 ÷2（2012-05-01 拆股）",
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

    def test_inputs_changed_during_the_checks_refuse_them(self):
        """A spin-off confirmed, or the checks' code edited, while the checks run: what they checked is neither
        state, so the run writes neither checks.json nor review.md."""
        out, spin = Path(self.tmp.name) / "out_race", Path(self.tmp.name) / "spin_race.json"
        spin.write_text(self.spin.read_text())
        orig = C.check_calendar

        def confirm(*a, **k):
            data = json.loads(spin.read_text())
            data["events"]["CCC"][0]["confirmed"] = True
            spin.write_text(json.dumps(data))
            return orig(*a, **k)
        args = ["--snap", str(self.snap), "--out", str(out), "--sample", str(self.sample), "--spinoffs", str(spin)]
        with mock.patch.object(C, "check_calendar", confirm):
            self.assertEqual(C.main(args + ["--only", "calendar", "review"]), 2)
        self.assertFalse((out / "checks.json").exists())
        self.assertFalse((out / "review.md").exists())
        codes = iter([{"checks.py": "a" * 32}, {"checks.py": "b" * 32}])
        with mock.patch.object(C.RP, "checks_code", lambda: next(codes)):
            self.assertEqual(C.main(args + ["--only", "calendar"]), 2)
        self.assertFalse((out / "checks.json").exists())
        self.assertEqual(C.main(args + ["--only", "calendar"]), 0)          # unchanged: written
        self.assertTrue((out / "checks.json").exists())

    def test_the_snapshot_folder_is_not_an_output_folder(self):
        """checks.py refuses an --out that is the snapshot folder or inside it, before writing anything there."""
        link = Path(self.tmp.name) / "snap_link"
        link.symlink_to(self.snap)
        for out in (self.snap, link, self.snap / "raw"):
            self.assertEqual(C.main(["--snap", str(self.snap), "--out", str(out), "--only", "calendar",
                                     "--sample", str(self.sample), "--spinoffs", str(self.spin)]), 2, out)
            self.assertFalse((out / "checks.json").exists(), out)
        link.unlink()

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
        """Check 8 compares what run_pilot writes and nothing else (checks or a report kept beside the results do
        not count), names an output either run lacks, and refuses to compare a run with itself."""
        a, b = self.out / "run_a", self.out / "run_b"
        for d, created in ((a, "x"), (b, "y")):
            d.mkdir(exist_ok=True)
            (d / "results.json").write_text(json.dumps({"created": created, "theta": 0.1}))
            for name in ("plans.csv", "portfolio.json", "status.json", "pools_T.json", "pools_F.json"):
                (d / name).write_text("the same\n")
        (a / "checks.json").write_text("{}")
        (a / "review.md").write_text("a table")
        (b / "report.md").write_text("a report")
        self.assertEqual(C.same_results(a, b), [])
        self.assertEqual(C.main(["--same", str(a), str(b)]), 0)
        digest = C.RP.results_digest({"theta": 0.1})
        self.assertEqual(json.loads((a / "repro.json").read_text()),
                         {"same": True, "diff": [], "results": [digest, digest]})
        for other in (a, a / ".." / "run_a", self.out / "no_run"):
            self.assertEqual(C.main(["--same", str(a), str(other)]), 2)
        (b / "pools_F.json").unlink()
        self.assertEqual(C.same_results(a, b), ["pools_F.json"])
        (b / "status.json").unlink()
        self.assertEqual(C.same_results(a, b), ["status.json", "pools_F.json"])
        (b / "results.json").write_text(json.dumps({"created": "y", "theta": 0.2}))
        self.assertEqual(C.same_results(a, b)[0], "results.json")

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
