"""Tests of the daily panel: EPS known only after filing, the split basis judged by filing date, the band equal
to the skill's own computation, and nothing on or before a day changing when later data is deleted (version T),
including planted leaks that the deletion test must catch."""
from __future__ import annotations

import bisect
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
import panel as P  # noqa: E402
import synth  # noqa: E402

A = P.A
SPANS = [["2005-01-03", "2030-01-01"]]


def true_known(end: dt.date, per: str, k: int, placeholder_every: int) -> dt.date:
    """The synthetic filing dates, independently of panel.known_day."""
    if placeholder_every and k % placeholder_every == 0:
        return end + dt.timedelta(days=90 if per == "Q4" else 45)
    return synth.filed_on(end, per)


def ttm_truth(quarters, d, placeholder_every=0):
    known = sorted((end, e) for k, (end, per, fy, e) in enumerate(quarters)
                   if true_known(end, per, k, placeholder_every) < d)
    return sum(e for _, e in known[-4:]) if len(known) >= 4 else None


class PanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.snap = Path(cls.tmp.name)
        cls.truth = synth.company(cls.snap, "SYN", seed=3, placeholder_every=7)
        synth.company(cls.snap, "RST", seed=4, split_restated=True)
        cls.p = P.build("SYN", cls.snap, SPANS)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def acts(self, p, kind="basis_q"):
        return [r["action"] for r in p.report[kind]["boundary"]]

    def test_split_restated(self):
        self.assertEqual(self.acts(self.p), ["not_restated"])
        self.assertEqual(self.acts(self.p, "basis_a"), ["not_restated"])
        q = P.build("RST", self.snap, SPANS)
        self.assertEqual(self.acts(q), ["restated"])                    # FMP restated: nothing to do
        self.assertTrue(all(r.get("basis_factor", 1.0) == 1.0 for r in P.statement_rows(
            P.read(self.snap / "raw" / "inc_q" / "RST.json"), [(dt.date(2014, 6, 9), 2.0)], {})))

    def test_ttm_known_after_filing(self):
        quarters = self.truth["quarters"]
        checked = 0
        for d in (dt.date(2010, 2, 4), dt.date(2014, 6, 10), dt.date(2019, 11, 6), dt.date(2024, 3, 1)):
            iso = d.isoformat()
            if iso not in self.p.dates:
                continue
            i = self.p.dates.index(iso)
            self.assertAlmostEqual(self.p.eps["T"][i], ttm_truth(quarters, d, 7), places=4)
            checked += 1
        self.assertGreater(checked, 2)

    def test_split_between_period_end_and_filing(self):
        # a 3-for-1 split on 2014-04-20: Q1 2014 ended before it but was filed after it, so GAAP shows it on the
        # new basis; a boundary drawn at the period end would divide it by 3 a second time
        tr = synth.company(self.snap, "STR", seed=8, split=(dt.date(2014, 4, 20), 3.0))
        p = P.build("STR", self.snap, SPANS)
        self.assertEqual(self.acts(p), ["not_restated"])
        for iso in ("2014-05-08", "2014-06-02", "2015-01-05", "2013-09-03"):
            i = p.dates.index(iso)
            self.assertAlmostEqual(p.eps["T"][i], ttm_truth(tr["quarters"], P.day(iso)), places=4)

    def test_partial_restatement(self):
        # FMP restated only the rows filed from 2012 on for the 2014 split: the boundary looks restated, the
        # step between 2011 Q3 and 2011 Q4 (filed 2012-02-29) carries the factor
        tr = synth.company(self.snap, "PRT", seed=9, restated_from=dt.date(2012, 1, 1))
        p = P.build("PRT", self.snap, SPANS)
        self.assertEqual(self.acts(p), ["restated"])
        self.assertEqual([r["factor"] for r in p.report["basis_q"]["partial"]], [2.0])
        for iso in ("2010-06-01", "2011-12-01", "2012-05-01", "2016-05-02"):
            i = p.dates.index(iso)
            self.assertAlmostEqual(p.eps["T"][i], ttm_truth(tr["quarters"], P.day(iso)), places=4)

    def test_eps_on_another_basis_than_shares(self):
        bad = (dt.date(2012, 3, 31), dt.date(2012, 6, 30))
        tr = synth.company(self.snap, "MIX", seed=10, split_restated=True, eps_not_restated=bad)
        p = P.build("MIX", self.snap, SPANS)
        self.assertEqual(sorted(r["end"] for r in p.report["basis_q"]["eps_shares"]),
                         [d.isoformat() for d in bad])
        i = p.dates.index("2012-12-03")
        self.assertAlmostEqual(p.eps["T"][i], ttm_truth(tr["quarters"], P.day("2012-12-03")), places=4)

    def test_only_a_later_split_puts_eps_on_the_shares_basis(self):
        """A split before a row cannot leave its EPS and share fields on different bases, so EPS x shares / net
        income near 2 in rows filed years after a 2-for-1 split (here the net income field: minority interests,
        preferred dividends) is listed, not fixed; a row whose EPS FMP did not restate for a later split is
        fixed, and the fix names that split. status.py's frozen reading still takes every run of splits."""
        when = dt.date(2009, 6, 1)
        tr = synth.company(self.snap, "OLD", seed=11, split=(when, 2.0), split_restated=True,
                           eps_not_restated=(dt.date(2008, 3, 31),))
        path = self.snap / "raw" / "inc_q" / "OLD.json"
        rows = json.loads(path.read_text())
        for r in rows:
            if r["date"] in ("2015-03-31", "2015-06-30"):
                r["netIncome"] /= 2
        path.write_text(json.dumps(rows))
        p = P.build("OLD", self.snap, SPANS)
        self.assertEqual([(u["end"], u["fixed_by"], u["splits"]) for u in p.report["basis_q"]["eps_shares"]],
                         [("2008-03-31", 2.0, ["2009-06-01"])])
        self.assertEqual([(u["end"], u["eps_x_shares_over_ni"]) for u in p.report["basis_q"]["review"]],
                         [("2015-03-31", 2.0), ("2015-06-30", 2.0)])
        for iso in ("2008-09-02", "2015-09-01", "2016-02-01"):
            i = p.dates.index(iso)
            self.assertAlmostEqual(p.eps["T"][i], ttm_truth(tr["quarters"], P.day(iso)), places=4)
        rep = {}
        P.statement_rows(rows, P.split_factors(P.read(self.snap / "raw" / "splits" / "OLD.json")), rep)
        self.assertEqual([u["end"] for u in rep["eps_shares"]], ["2008-03-31", "2015-03-31", "2015-06-30"])

    def test_stale_and_missing_quarters(self):
        gone = (dt.date(2016, 3, 31), dt.date(2016, 6, 30), dt.date(2016, 9, 30))
        synth.company(self.snap, "GAP", seed=12, drop_quarters=gone)
        p = P.build("GAP", self.snap, SPANS)
        i = p.dates.index("2016-11-01")          # newest known quarter 2015 Q4, 306 days earlier
        self.assertIsNone(p.eps["T"][i])
        self.assertEqual(p.why["T"][i], "eps_stale")
        i = p.dates.index("2017-03-01")          # 2016 Q4 known on 2017-03-01 + 1 only: 2015 Q4 still newest
        self.assertIsNone(p.eps["T"][i])

    def test_f_horizon(self):
        ends = [r["end"] for r in P.latest_by_end(P.statement_rows(
            P.read(self.snap / "raw" / "inc_a" / "SYN.json"), P.split_factors(
                P.read(self.snap / "raw" / "splits" / "SYN.json")), {}))]
        self.assertEqual(self.p.report["f_horizon"], ends[-2].isoformat())
        late = [i for i, d in enumerate(self.p.dates) if d > ends[-2].isoformat() and d >= "2008-01-02"]
        self.assertTrue(late)
        self.assertTrue(all(self.p.band["F"][i] is None and self.p.why["F"][i] == "beyond_horizon" for i in late))

    def test_band_is_the_skills(self):
        """The fast band equals analyze.multiple_bands and the full analyze.history_problem on the same inputs."""
        p, rnd = self.p, random.Random(7)
        sp = P.split_factors(P.read(self.snap / "raw" / "splits" / "SYN.json"))
        years = P.statement_rows(P.read(self.snap / "raw" / "inc_a" / "SYN.json"), sp, {})
        quarters = P.statement_rows(P.read(self.snap / "raw" / "inc_q" / "SYN.json"), sp, {})
        checked = 0
        for v in ("T", "F"):
            eps_by_day = dict(zip(p.dates, p.eps[v]))
            for i in rnd.sample(range(len(p.dates)), 60):
                d = P.day(p.dates[i])
                if p.dates[i] < "2007-12-01":
                    continue
                start = (d - dt.timedelta(days=P.LOOKBACK_DAYS)).isoformat()
                window = [(p.dates[j], p.c[j]) for j in range(i + 1) if p.dates[j] >= start]
                yrs = [{"date": y["end"].isoformat(), "shares": y["shares"]} for y in P.latest_by_end(years, d)]
                qs = [q for q in quarters if q["known"] < d and q["shares"]]
                cur = max(qs, key=lambda q: (q["known"], q["end"]))["shares"] if qs else None
                code, _ = A.history_problem(yrs, window, start, cur)
                now = A.pos_div(p.c[i], p.eps[v][i]) if p.eps[v][i] else None
                want = A.multiple_bands([], window, eps_by_day.get, lambda _d: None, now, None)[0]
                if code or not now or want is None:
                    self.assertIsNone(p.band[v][i])
                    continue
                got = p.band[v][i]
                for k in ("p25", "median", "p75"):
                    self.assertAlmostEqual(got[k], want[k], places=9)
                self.assertAlmostEqual(got["pct"], want["now_pct"], places=12)
                checked += 1
        self.assertGreater(checked, 60)

    def test_truncation_changes_nothing_before(self):
        for cut in ("2011-05-16", "2014-06-06", "2014-06-10", "2020-03-20"):
            t = P.build("SYN", self.snap, SPANS, truncate=cut, snapshot_end=cut)
            n = len(t.dates)
            self.assertEqual(t.dates, self.p.dates[:n])
            for v in ("T",):
                self.assertEqual(t.eps[v], self.p.eps[v][:n])
                self.assertEqual(t.band[v], self.p.band[v][:n])
            self.assertEqual(t.atr, self.p.atr[:n])

    def test_planted_leaks_are_caught(self):
        """Each leak changes some T band before a cut once the later filings are deleted by their true dates."""
        orig = P.known_day

        def period_end(r):
            return P.day(r["date"]), False

        def q4_at_45(r):
            k, ph = orig(r)
            if ph and str(r.get("period")).upper() in ("Q4", "FY"):
                return P.day(r["date"]) + dt.timedelta(days=45), ph
            return k, ph

        def placeholder_at_end(r):
            k, ph = orig(r)
            return (P.day(r["date"]), ph) if ph else (k, ph)

        synth.company(self.snap, "LKQ", seed=13, placeholder_every=3)
        cuts = ("2009-02-17", "2012-02-16", "2018-02-15", "2021-02-16")
        for leak in (period_end, q4_at_45, placeholder_at_end):
            with mock.patch.object(P, "known_day", leak):
                full = P.build("LKQ", self.snap, SPANS)
                changed = False
                for cut in cuts:
                    t = P.build("LKQ", self.snap, SPANS, truncate=cut, snapshot_end=cut, audit_known=orig)
                    changed |= t.band["T"] != full.band["T"][:len(t.dates)]
            self.assertTrue(changed, leak.__name__)
        full = P.build("LKQ", self.snap, SPANS)            # no leak: nothing changes
        for cut in cuts:
            t = P.build("LKQ", self.snap, SPANS, truncate=cut, snapshot_end=cut, audit_known=orig)
            self.assertEqual(t.band["T"], full.band["T"][:len(t.dates)])

    def test_an_eps_in_the_wrong_unit_is_fixed(self):
        """One quarter's EPS 1000 times too large (APOL's 2008 Q2 in FMP) becomes net income / shares, and T is
        as without the slip; a net income 1000 times too small (TPR's 2003 Q2) leaves the EPS alone."""
        synth.company(self.snap, "UNT", seed=21, split=None)
        base = P.build("UNT", self.snap, SPANS)
        path = self.snap / "raw" / "inc_q" / "UNT.json"
        rows = json.loads(path.read_text())
        rows.sort(key=lambda r: r["date"])
        eps_bad, ni_bad = rows[40], rows[60]
        eps_bad["epsDiluted"] *= 1000
        ni_bad["netIncome"] /= 1000
        path.write_text(json.dumps(rows))
        p = P.build("UNT", self.snap, SPANS)
        fixed = p.report["basis_q"]["eps_units"]
        self.assertEqual([u["end"] for u in fixed], [eps_bad["date"]])
        want = eps_bad["netIncome"] / eps_bad["weightedAverageShsOutDil"]
        self.assertAlmostEqual(fixed[0]["now"], want, places=6)
        for a, b in zip(p.eps["T"], base.eps["T"]):
            self.assertTrue(a is None and b is None or abs(a - b) <= 1e-6 * max(1.0, abs(b)))
        for a, b in zip(p.band["T"], base.band["T"]):            # equal up to the EPS's rounding in the file
            self.assertEqual(a is None, b is None)
            if a is not None:
                for k in ("p25", "median", "p75"):
                    self.assertAlmostEqual(a[k], b[k], delta=1e-5 * abs(b[k]))
                self.assertAlmostEqual(a["pct"], b["pct"], delta=0.01)
        rep = {}                                    # the frozen walk's reading keeps the rows as filed
        P.statement_rows(rows, [], rep)
        self.assertEqual(rep["eps_units"], [])

    def test_split_after_the_day_changes_no_multiple(self):
        """A 2-for-1 split after the cut, with the statements restated or not: the P/E band at the cut is the
        same as without the split, and the range is in the new units."""
        cut, when = "2019-06-03", "2021-03-01"
        for sym, restated in (("SPN", False), ("SPL", True)):
            synth.company(self.snap, sym, seed=14, split=None)
            base = P.build(sym, self.snap, SPANS)
            raw = self.snap / "raw"
            rows = json.loads((raw / "full" / f"{sym}.json").read_text())
            for r in rows:
                if r["date"] < when:                       # prices adjusted back for the split
                    for k in ("open", "high", "low", "close"):
                        r[k] = r[k] / 2
            (raw / "full" / f"{sym}.json").write_text(json.dumps(rows))
            for part in ("inc_q", "inc_a"):
                rows = json.loads((raw / part / f"{sym}.json").read_text())
                for r in rows:
                    if restated or r["filingDate"] >= when:    # new basis: restated, or filed after the split
                        r["epsDiluted"] /= 2
                        r["weightedAverageShsOutDil"] *= 2
                (raw / part / f"{sym}.json").write_text(json.dumps(rows))
            (raw / "splits" / f"{sym}.json").write_text(json.dumps([{"date": when, "numerator": 2, "denominator": 1}]))
            after = P.build(sym, self.snap, SPANS, truncate=cut, snapshot_end=cut)
            self.assertEqual([r["action"] for r in after.report["basis_q"]["boundary"]],
                             ["restated" if restated else "not_restated"])
            i = base.dates.index(cut)
            for k in ("p25", "median", "p75", "pct"):
                self.assertAlmostEqual(after.band["T"][i][k], base.band["T"][i][k], places=9)
            self.assertAlmostEqual(after.range_at("T", i)[1], base.range_at("T", i)[1] / 2, places=9)

    def test_suspicious_flags_are_point_in_time(self):
        """One-day moves over 50% flag no bar before them, and each bar while the verdict is pending only on what
        its close knows: a bad print in /full alone from its own bar; a fall both series show that reverses 2
        bars later from the reversal on; a real fall that holds never, unless a split row is within 5 bars of it,
        and then only from that row's bar on. A build cut anywhere flags what the full build flags up to the
        cut."""
        synth.company(self.snap, "JMP", seed=31, split=None)
        raw = self.snap / "raw"
        full, adj = (json.loads((raw / part / "JMP.json").read_text()) for part in ("full", "adj"))
        days = sorted(r["date"] for r in full)
        rev, bad, real, near = days[2000], days[3000], days[4000], days[4500]
        for rows, keys in ((full, ("open", "high", "low", "close")), (adj, ("adjOpen", "adjHigh", "adjLow",
                                                                            "adjClose"))):
            for r in rows:
                f = (0.45 if rev <= r["date"] < days[2002] else 1.0) * (0.45 if r["date"] >= real else 1.0) * \
                    (0.45 if r["date"] >= near else 1.0)
                if rows is full and r["date"] == bad:
                    f *= 0.4                                # one bad print, /full only
                for k in keys:
                    r[k] *= f
        for part, rows in (("full", full), ("adj", adj)):
            (raw / part / "JMP.json").write_text(json.dumps(rows))
        (raw / "splits" / "JMP.json").write_text(json.dumps([{"date": days[4503], "numerator": 3, "denominator": 2}]))
        p = P.build("JMP", self.snap, SPANS)
        jumps = {j["date"]: j["verified"] for j in p.report["clean"]["jumps"]}
        self.assertEqual((jumps[rev], jumps[days[2002]], jumps[bad], jumps[real], jumps[near]),
                         (False, True, False, True, False))
        r, i, k, m = p.dates.index(rev), p.dates.index(bad), p.dates.index(real), p.dates.index(near)
        self.assertFalse(any(p.suspicious[r - 40:r + 2]))
        self.assertTrue(all(p.suspicious[r + 2:r + 41]))
        self.assertFalse(any(p.suspicious[i - 40:i]))
        self.assertTrue(all(p.suspicious[i:i + 41]))
        self.assertFalse(any(p.suspicious[k - 40:k + 60]))
        self.assertFalse(any(p.suspicious[m - 40:m + 3]))     # a move that holds, then a split row 3 bars later:
        self.assertTrue(all(p.suspicious[m + 3:m + 41]))      # flagged from the split row's bar, not before it
        for cut in (p.dates[r + 1], p.dates[r + 3], p.dates[i - 1], p.dates[i + 2], p.dates[i + 30],
                    p.dates[k + 2], p.dates[m + 1], p.dates[m + 2], p.dates[m + 4]):
            t = P.build("JMP", self.snap, SPANS, truncate=cut, snapshot_end=cut)
            self.assertEqual(t.suspicious, p.suspicious[:len(t.dates)], cut)

    def test_an_unclear_split_takes_old_statements_out_of_use_once_a_new_one_is(self):
        """A 10% stock dividend FMP did not restate, with a 3% buyback after it: the share counts cannot tell the
        basis. Version T keeps the older statements as filed until the first statement filed after the split is
        in use (as keeping them: every statement in use then is on the one old basis) and from then on uses none
        of them anywhere in its window (as clearing them); deleting later data changes nothing before a cut."""
        when = dt.date(2016, 6, 6)
        synth.company(self.snap, "UNC", seed=33, split=(when, 1.1))
        path = self.snap / "raw" / "inc_q" / "UNC.json"
        rows = json.loads(path.read_text())
        for r in rows:
            if r["filingDate"] >= when.isoformat():
                r["weightedAverageShsOutDil"] *= 0.97
        path.write_text(json.dumps(rows))
        p = P.build("UNC", self.snap, SPANS, versions=("T",))
        (b,) = p.report["basis_q"]["boundary"]
        first = min(r["filingDate"] for r in rows if r["filingDate"] >= when.isoformat())
        self.assertEqual((b["action"], b["unused_after"]), ("unclear", first))
        orig = P.statement_rows

        def reading(mode):
            return lambda raw, sp, rep, unclear="keep", **kw: orig(raw, sp, rep, mode if unclear == "mark" else unclear,
                                                                   **kw)
        with mock.patch.object(P, "statement_rows", reading("keep")):
            keep = P.build("UNC", self.snap, SPANS, versions=("T",))
        with mock.patch.object(P, "statement_rows", reading("none")):
            none = P.build("UNC", self.snap, SPANS, versions=("T",))
        k = bisect.bisect_right(p.dates, first)
        self.assertEqual((p.eps["T"][:k], p.band["T"][:k]), (keep.eps["T"][:k], keep.band["T"][:k]))
        self.assertEqual((p.eps["T"][k:], p.band["T"][k:]), (none.eps["T"][k:], none.band["T"][k:]))
        self.assertGreater(sum(x is not None for x in p.band["T"][:k]), 1000)    # clearing them loses these
        self.assertEqual(sum(x is not None for x in none.band["T"][:k]), 0)
        self.assertNotEqual(p.window_eps("T", k - 1), p.window_eps("T", k))
        for cut in (first, p.dates[k + 5], "2017-08-01", "2018-03-01"):
            t = P.build("UNC", self.snap, SPANS, versions=("T",), truncate=cut, snapshot_end=cut)
            n = len(t.dates)
            self.assertEqual((t.eps["T"], t.band["T"]), (p.eps["T"][:n], p.band["T"][:n]), cut)
            self.assertEqual(len(t.epochs["T"]), 1 if cut == first else 2, cut)  # the cut removed the epoch's end

    def test_a_verdict_filed_after_the_epochs_end_is_unclear(self):
        """The share-count test of a split reads the first statement after it with a share count and a later
        period end. When that one is filed after the first statement after the split (here the first has no
        share count), T leaves its old statements on that first one's day whatever the test says: two snapshots
        that differ only from the later filing on (a 3% buyback after the split, or none) agree on every day up
        to it."""
        when, got = dt.date(2016, 6, 6), {}
        for sym, mult in (("LTU", 0.97), ("LTN", 1.0)):
            synth.company(self.snap, sym, seed=57, split=(when, 1.1))
            path = self.snap / "raw" / "inc_q" / f"{sym}.json"
            rows = json.loads(path.read_text())
            post = sorted((r for r in rows if r["filingDate"] >= when.isoformat()), key=lambda r: r["filingDate"])
            post[0]["weightedAverageShsOutDil"] = None
            for r in post[1:]:
                r["weightedAverageShsOutDil"] *= mult
            path.write_text(json.dumps(rows))
            got[sym] = P.build(sym, self.snap, SPANS, versions=("T",))
        first, verdict = post[0]["filingDate"], post[1]["filingDate"]
        u, n = got["LTU"], got["LTN"]
        for p in (u, n):
            (b,) = p.report["basis_q"]["boundary"]
            self.assertEqual((b["action"], b["unused_after"], b["verdict_known"]), ("unclear", first, verdict))
        k = bisect.bisect_right(u.dates, verdict)
        self.assertEqual((u.eps["T"][:k], u.band["T"][:k]), (n.eps["T"][:k], n.band["T"][:k]))
        self.assertGreater(sum(x is not None for x in u.band["T"][:k]), 1000)
        rows = [{"end": dt.date(2020, 3, 31), "known": dt.date(2020, 5, 5), "eps": 1.0, "shares": 100.0, "ni": 100.0},
                {"end": dt.date(2020, 6, 30), "known": dt.date(2020, 8, 5), "eps": 0.5, "shares": None, "ni": 100.0}]
        rep = {}                                    # a statement after the split, none to judge it by: unclear too
        out = P.normalize_basis(rows, [(dt.date(2020, 7, 1), 2.0)], rep, unclear="mark")
        self.assertEqual([(b["action"], b["unused_after"], b["verdict_known"], b["ratio"]) for b in rep["boundary"]],
                         [("unclear", "2020-08-05", None, None)])
        self.assertEqual(out[0]["unclear_until"], dt.date(2020, 8, 5))
        rep = {}
        P.normalize_basis(rows, [(dt.date(2020, 7, 1), 2.0)], rep)          # the frozen walk's reading
        self.assertEqual([b["action"] for b in rep["boundary"]], ["no row after"])

    def test_before_an_unclear_split_t_reads_the_years_as_filed(self):
        """A 2-for-1 split FMP did not restate, with the quarterly share counts after it 1.5 times higher, so the
        quarterly test is unclear and T uses the quarters filed before it as filed up to the first statement
        after it. Its share check then reads the fiscal years as filed too: whether the annual statements after
        the split say not restated (as generated) or unclear (with the same 1.5) changes nothing before that
        day, and the share check passes."""
        when, got = dt.date(2016, 6, 6), {}
        for sym, amult in (("QUA", 1.0), ("QUU", 1.5)):
            synth.company(self.snap, sym, seed=61, split=(when, 2.0))
            for part, m in (("inc_q", 1.5), ("inc_a", amult)):
                path = self.snap / "raw" / part / f"{sym}.json"
                rows = json.loads(path.read_text())
                for r in rows:
                    if r["filingDate"] >= when.isoformat():
                        r["weightedAverageShsOutDil"] *= m
                path.write_text(json.dumps(rows))
            got[sym] = P.build(sym, self.snap, SPANS, versions=("T",))
        a, u = got["QUA"], got["QUU"]
        self.assertEqual([b["action"] for b in a.report["basis_a"]["boundary"]], ["not_restated"])
        self.assertEqual([b["action"] for b in u.report["basis_a"]["boundary"]], ["unclear"])
        (b,) = a.report["basis_q"]["boundary"]
        self.assertEqual(b["action"], "unclear")
        k = bisect.bisect_right(a.dates, b["unused_after"])
        self.assertEqual((a.eps["T"][:k], a.band["T"][:k]), (u.eps["T"][:k], u.band["T"][:k]))
        self.assertGreater(sum(x is not None for x in a.band["T"][:k]), 1000)

    def test_loss_years_have_no_band(self):
        synth.company(self.snap, "LOS", seed=5, loss_years=(2012, 2013))
        q = P.build("LOS", self.snap, SPANS)
        i = q.dates.index("2013-07-01")
        self.assertIsNone(q.band["T"][i])
        self.assertIn(q.why["T"][i], ("eps_not_positive", "price_jump"))


if __name__ == "__main__":
    unittest.main()
