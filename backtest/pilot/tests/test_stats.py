"""Tests of the pilot's statistics: the plan-level placebo test, the weighted block difference, the cluster SE,
the rank correlation and the rules-free signal test, on data whose answers are known."""
from __future__ import annotations

import random
import statistics
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import stats as ST  # noqa: E402


def cols(values: list, years: list, full=None) -> dict:
    return {"dh252": list(values), "year": list(years), "full252": list(full or [True] * len(values))}


class PlanTestTest(unittest.TestCase):
    def test_known_theta_and_a_clear_win(self):
        strat = {"A": cols([3.0] * 4, [2010, 2011, 2011, 2012]), "B": cols([1.0], [2012])}
        pool = {"A": cols([0.0, 1.0, 2.0, 3.0], [2010, 2010, 2011, 2012]), "B": cols([0.0, 2.0], [2012, 2013])}
        out = ST.plan_test(strat, pool, reps=1999, tag="t1")
        expect = (4 * 1.5 + 1 * 1.0) / 5
        self.assertAlmostEqual(out["placebo_expectation"], expect)
        self.assertAlmostEqual(out["theta"], 13.0 / 5 - expect)
        self.assertAlmostEqual(out["placebo"]["p_one_sided"], 5 / 512, delta=0.006)   # P(sum of draws >= 13)
        self.assertAlmostEqual(out["placebo"]["mean"], 0.0, delta=0.05)
        self.assertEqual(out["without_top3"]["companies"], ["A", "B"])
        self.assertIsNone(out["without_top3"]["theta"])                 # nothing left without them

    def test_short_windows_are_left_out(self):
        strat = {"A": cols([5.0, 1.0], [2010, 2011], [False, True])}
        pool = {"A": cols([1.0, 1.0, 9.0], [2010, 2011, 2011], [True, True, False])}
        out = ST.plan_test(strat, pool, reps=99, tag="t2")
        self.assertEqual((out["plans"], out["pool"]), (1, 2))
        self.assertAlmostEqual(out["theta"], 0.0)

    def test_size_under_the_null(self):
        """Strategy plans drawn from the pools themselves: p <= 0.2 about 20% of the time."""
        rnd = random.Random(5)
        hits = 0
        trials = 150
        for t in range(trials):
            strat, pool = {}, {}
            for c in range(6):
                mu = rnd.gauss(0, 1)
                years = [2008 + k % 15 for k in range(60)]
                vals = [mu + rnd.gauss(0, 1) for _ in years]
                pool[c] = cols(vals, years)
                pick = [rnd.randrange(60) for _ in range(rnd.randrange(3, 12))]
                strat[c] = cols([vals[k] for k in pick], [years[k] for k in pick])
            out = ST.plan_test(strat, pool, reps=199, tag=f"null{t}")
            hits += out["placebo"]["p_one_sided"] <= 0.2
        self.assertTrue(0.10 <= hits / trials <= 0.32, hits / trials)

    def test_empty_pool_is_an_error(self):
        with self.assertRaises(ValueError):
            ST.plan_test({"A": cols([1.0], [2010])}, {"A": cols([], [])}, reps=9)

    def test_leave_one_company_out(self):
        strat = {"A": cols([3.0, 3.0], [2010, 2011]), "B": cols([1.0], [2011]), "C": cols([0.0], [2012])}
        pool = {"A": cols([0.0, 0.0], [2010, 2011]), "B": cols([0.0], [2011]), "C": cols([0.0], [2012])}
        out = ST.plan_test(strat, pool, reps=0, tag="loco")
        self.assertAlmostEqual(out["theta"], 7.0 / 4)
        lo = out["leave_one_company_out"]
        self.assertAlmostEqual(lo["min"], 0.5)
        self.assertAlmostEqual(lo["max"], 7.0 / 3)
        self.assertEqual((lo["min_without"], lo["max_without"]), ("A", "C"))
        self.assertIsNone(out["placebo"])                          # reps = 0: theta and its intervals only
        self.assertIn("year_blocks", out)

    def test_metrics_reading_one_pool_draw_the_same_days(self):
        rnd = random.Random(9)
        strat, pool = {}, {}
        for c in "ABCD":
            v = [rnd.gauss(0, 1) for _ in range(40)]
            y = [2008 + k % 10 for k in range(40)]
            pool[c] = dict(cols(v, y), raw252=list(v))
            strat[c] = dict(cols(v[:5], y[:5]), raw252=list(v[:5]))
        a = ST.plan_test(strat, pool, "dh252", reps=300, tag="T")
        b = ST.plan_test(strat, pool, "raw252", reps=300, tag="T")
        self.assertEqual(a["placebo"], b["placebo"])
        c = ST.plan_test(strat, pool, "dh252", reps=300, tag="F")
        self.assertNotEqual(a["placebo"], c["placebo"])            # another version draws its own days


class BlocksTest(unittest.TestCase):
    def test_weighted_equals_unweighted_with_unit_weights(self):
        rnd = random.Random(1)
        xa = [rnd.gauss(0, 1) for _ in range(80)]
        la = [2008 + k % 12 for k in range(80)]
        xb = [rnd.gauss(0, 1) for _ in range(120)]
        lb = [2008 + k % 12 for k in range(120)]
        a = ST.diff_by_blocks(xa, la, xb, lb, "same")
        b = ST.diff_by_blocks_w(xa, la, xb, lb, [1.0] * len(xb), "same")
        for k in ("theta", "se", "lo", "hi"):
            self.assertAlmostEqual(a[k], b[k], places=12)

    def test_cluster_se_is_near_the_spread_of_company_means(self):
        rnd = random.Random(2)
        x = {c: [rnd.gauss(0, 1) for _ in range(20)] for c in range(30)}
        y = {c: [0.0] for c in range(30)}
        got = ST.cluster_se(list(x), x, y, "cl", n_boot=2000)["se"]
        want = statistics.stdev([statistics.mean(v) for v in x.values()]) / 30 ** 0.5
        self.assertAlmostEqual(got, want, delta=0.25 * want)


class SignalTest(unittest.TestCase):
    def test_ranks_and_spearman(self):
        self.assertEqual(ST.ranks([3.0, 1.0, 1.0, 2.0]), [3.0, 0.5, 0.5, 2.0])
        self.assertAlmostEqual(ST.spearman([1, 2, 3, 4], [10, 20, 30, 45]), 1.0)
        self.assertAlmostEqual(ST.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_gap(self):
        rows = [(2008 + k % 10, k % 2 == 0, 0.1 if k % 2 == 0 else -0.1, {252: 0.05 if k % 2 == 0 else 0.0},
                 f"C{k % 7}") for k in range(200)]
        out = ST.signal_test(rows, "s")
        self.assertAlmostEqual(out["h252"]["gap"]["theta"], 0.05)
        self.assertAlmostEqual(out["below_share"], 0.5)
        self.assertGreater(out["h252"]["ic"], 0.8)
        sch = out["h252"]["gap_schemes"]
        self.assertEqual(sorted(sch), ["by_year", "company", "two_years"])
        self.assertEqual((sch["by_year"]["G"], sch["two_years"]["G"], sch["company"]["G"]), (10, 5, 7))

    def test_the_gap_interval_is_the_wider_of_two_year_blocks_and_companies(self):
        """A gap that differs by company: resampling single years mixes every company into every block and
        reads too precise; the company clusters see it, and the gap's interval is theirs."""
        rnd = random.Random(4)
        level = {f"C{c}": rnd.gauss(0, 0.05) for c in range(12)}
        rows = []
        for k in range(1200):
            c, below = f"C{k % 12}", rnd.random() < 0.4
            rows.append((2008 + rnd.randrange(18), below, 0.0, {252: level[c] * below + rnd.gauss(0, 0.02)}, c))
        out = ST.signal_test(rows, "w")["h252"]
        sch, g = out["gap_schemes"], out["gap"]
        self.assertEqual(g["scheme"], "company")
        self.assertEqual(g["hi"] - g["lo"], max(x["hi"] - x["lo"] for k, x in sch.items() if k != "by_year"))
        self.assertGreater(g["hi"] - g["lo"], 1.5 * (sch["by_year"]["hi"] - sch["by_year"]["lo"]))

    def test_the_wider_interval_is_chosen_by_width_not_by_se(self):
        """Company clusters with the larger SE can still give the narrower interval (about 48 clusters' t
        quantile against 9 two-year blocks'): the gap's interval is the wider one."""
        made = {"two_years": (0.0180, 9), "company": (0.0190, 48)}

        def blocks(xa, la, xb, lb, tag, level=ST.LEVEL):
            name = "two_years" if tag.startswith("signal2y") else "company" if tag.startswith("signalco") else None
            se, G = made.get(name, (0.01, 18))
            q = ST.t_ppf(0.5 + level / 2.0, G - 1)
            return {"theta": 0.01, "se": se, "G": G, "lo": 0.01 - q * se, "hi": 0.01 + q * se}
        rows = [(2008 + k % 18, k % 3 == 0, 0.0, {252: 0.01 * (k % 3 == 0)}, f"C{k % 48}") for k in range(900)]
        with mock.patch.object(ST, "diff_by_blocks", blocks):
            g = ST.signal_test(rows, "x")["h252"]["gap"]
        self.assertEqual(g["scheme"], "two_years")
        width = {k: 2 * ST.t_ppf(0.95, G - 1) * se for k, (se, G) in made.items()}
        self.assertGreater(width["two_years"], width["company"])


class YearlyExcessTest(unittest.TestCase):
    def test_the_first_year_counts_from_the_first_session(self):
        """The method holds cash while SPY falls 10% in January 2008 and is flat after: 2008's excess is +10%."""
        import datetime as dt
        cal = [d.isoformat() for d in (dt.date(2008, 1, 2) + dt.timedelta(days=k) for k in range(400))
               if d.weekday() < 5]
        spy = [1.0 if d == cal[0] else 0.9 for d in cal]
        cash = [1.0] * len(cal)
        marks = ST.month_ends(cal)
        self.assertEqual(marks[0], 0)
        mcal = [cal[k] for k in marks]
        got = ST.yearly_excess(mcal, [cash[k] for k in marks], [spy[k] for k in marks])
        self.assertAlmostEqual(got["by_year"]["2008"], 0.10)
        self.assertAlmostEqual(got["by_year"]["2009"], 0.0)


if __name__ == "__main__":
    unittest.main()
