"""Tests of the day-by-day simulation on synthetic panels: every trade at the open after the signal close, the
gates, the DCA schedule and pause, the chase limit, the stop, the take-profit ladder, the trailing stop and the
accounting; and the plan levels against the decision engine's own functions when its repo is at hand."""
from __future__ import annotations

import datetime as dt
import os
import random
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import panel as P  # noqa: E402
import sim as S  # noqa: E402
import synth  # noqa: E402

SPANS = [["2005-01-03", "2030-01-01"]]
IFP = Path(os.environ.get("IFP_REPO", HERE.parents[3] / "investment-final-plan"))


def flat_rate(_day):
    return 0.02


class SimTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        snap = Path(cls.tmp.name)
        synth.company(snap, "SYN", seed=11, pe_amp=0.45)
        cls.p = P.build("SYN", snap, SPANS, versions=("T",))
        cls.r = S.Rules()
        cls.out = S.run(cls.p, cls.r, flat_rate)
        cls.all = cls.out["plans"] + ([cls.out["open"]] if cls.out["open"] else [])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_has_plans_and_exits_of_each_kind(self):
        self.assertGreater(len(self.out["plans"]), 10)
        kinds = {s[4] for pl in self.out["plans"] for s in pl.sold}
        for k in ("stop", "tp_1"):
            self.assertIn(k, kinds)

    def test_entries_follow_a_close_below_the_mid(self):
        p = self.p
        for pl in self.all:
            lo, mid, hi, pct = p.range_at("T", pl.start)
            self.assertLess(p.c[pl.start], mid)
            self.assertTrue(p.member[pl.start])
            self.assertEqual(pl.filled[0][0], pl.start + 1)            # bought at the next open
            self.assertEqual(pl.filled[0][1], p.o[pl.start + 1])
            self.assertEqual(pl.stop0, round(pl.price - 2 * pl.atr, 4))

    def test_tranches_in_order_on_schedule_fair_and_under_the_chase_limit(self):
        p = self.p
        for pl in self.all:
            self.assertEqual([f[4] for f in pl.filled], list(range(len(pl.filled))))
            t0 = dt.date.fromisoformat(p.dates[pl.start])
            for f in pl.filled:
                sig, k = f[0] - 1, f[4]
                self.assertEqual(pl.sched[k], S.add_weekdays(t0, 10 * k).isoformat())
                self.assertGreaterEqual(p.dates[sig], pl.sched[k])
                self.assertLessEqual(p.dates[sig], pl.expires)
                self.assertEqual(S.temp_of(p.range_at("T", sig), self.r), "fair")
                self.assertLessEqual(f[1], p.c[sig] + 0.5 * p.atr[sig] + 1e-12)
                if k:                                                  # tranche k only after k - 1 filled
                    self.assertGreater(sig, pl.filled[k - 1][0] - 1)

    def test_one_action_type_per_close(self):
        for pl in self.all:
            buys = {f[0] for f in pl.filled}
            sells = {s[0] for s in pl.sold}
            self.assertFalse(buys & sells)

    def test_stop_exits_at_next_open(self):
        p = self.p
        seen = 0
        for pl in self.out["plans"]:
            for (i, px, q, got, why) in pl.sold:
                self.assertEqual(px, p.o[i])
                if why == "stop":
                    self.assertLess(p.c[i - 1], pl.stop0)
                    seen += 1
        self.assertGreater(seen, 0)

    def test_take_profit_shares_partition_the_position(self):
        """With no buy between the tiers, tp_1 / tp_2 / tp_3 sell 20 / 30 / 30% of the position."""
        checked = 0
        for pl in self.all:
            tiers = [s for s in pl.sold if s[4].startswith("tp_")]
            if not tiers or any(f[0] > tiers[0][0] for f in pl.filled):
                continue
            held = sum(f[2] for f in pl.filled)
            for s in tiers:
                want = sum(self.r.tp_weights[int(t) - 1] for t in s[4][3:].split("+"))
                self.assertAlmostEqual(s[2] / held, want, places=9)
                checked += 1
        self.assertGreater(checked, 3)

    def test_trailing_binds_only_after_tp_2_filled(self):
        for pl in self.out["plans"]:
            tp2 = [s[0] for s in pl.sold if "2" in s[4][3:].split("+") and s[4].startswith("tp_")]
            for s in pl.sold:
                if s[4] == "trailing":
                    self.assertTrue(tp2 and tp2[0] < s[0])

    def test_breakeven_after_tp_1(self):
        p = self.p
        for pl in self.out["plans"]:
            if any(s[4] == "breakeven" for s in pl.sold):
                self.assertTrue(any(s[4].startswith("tp_1") for s in pl.sold))

    def test_accounting(self):
        p, out = self.p, self.out
        last = out["last"]
        self.assertAlmostEqual(out["value"][last], out["end_value"], places=12)
        for pl in out["plans"]:
            q_in = sum(f[2] for f in pl.filled)
            q_out = sum(s[2] for s in pl.sold)
            self.assertAlmostEqual(q_in, q_out, places=9)

    def test_gates_wait(self):
        tight = S.run(self.p, replace(S.Rules(), min_rr=50.0), flat_rate)
        self.assertEqual(len(tight["plans"]), 0)
        self.assertGreater(tight["waits"]["reward_risk"], 0)

    def test_no_new_plan_outside_membership(self):
        p2 = replace(self.p, member=[d < "2012-01-01" for d in self.p.dates])
        out = S.run(p2, S.Rules(), flat_rate)
        self.assertTrue(all(p2.dates[pl.start] < "2012-01-01" for pl in out["plans"]))

    def test_variants_run(self):
        for kw in ({"cooldown": 20}, {"cancel_on_tp1": True}, {"trail_from": "first_fill"}, {"trail_from": "tp_3"},
                   {"tp_temp": False}, {"skip_paused": True}, {"max_price": "plan"}, {"max_price": None},
                   {"min_rr": None, "min_rr0": None}, {"tranche_below_mid": True}, {"stop_pct": 0.15},
                   {"no_stop": True}, {"exit_all_at": "high"}, {"tp_split": "raw"}):
            out = S.run(self.p, replace(S.Rules(), **kw), flat_rate)
            for pl in out["plans"]:
                self.assertAlmostEqual(sum(f[2] for f in pl.filled), sum(s[2] for s in pl.sold), places=9)
        cool = S.run(self.p, replace(S.Rules(), cooldown=20), flat_rate)
        for a, b in zip(cool["plans"], cool["plans"][1:]):
            self.assertGreaterEqual(b.start, a.end + 20)

    def test_deterministic(self):
        again = S.run(self.p, S.Rules(), flat_rate)
        self.assertEqual(again["end_value"], self.out["end_value"])


@unittest.skipUnless((IFP / "ifp" / "entries.py").exists(), "the decision engine's repo is not at hand")
class EngineFidelityTest(unittest.TestCase):
    """The pilot's stop, targets and reward/risk gate against the engine's own functions on random inputs."""

    def test_levels_match_the_engine(self):
        sys.path.insert(0, str(IFP))
        from ifp import config, entries as E, sizing  # noqa: E402
        rules = config.load_rules()
        r = S.Rules()
        rnd = random.Random(5)
        for _ in range(3000):
            P_ = round(rnd.uniform(5, 500), 2)
            A_ = P_ * rnd.uniform(0.005, 0.1)
            mid = P_ * rnd.uniform(0.98, 1.4)
            high = mid * rnd.uniform(1.0, 1.4)
            ents = [{"est_price": P_, "weight": w} for w in r.weights]
            lv = {"ATR": A_, "S1": None, "S_star": None, "resistances": []}
            stop = E.initial_stop(ents, lv, rules)["price"]
            self.assertEqual(S.initial_stop(P_, A_, r), stop)
            fa = {"valuation": {"primary_range": {"range": [P_ * 0.8, mid, high]}}}
            tg = E.targets(fa, lv, P_, rules)
            t1, t2, src = S.targets(P_, A_, mid, high, r)
            self.assertEqual((t1, t2, src), (tg[0]["price"], tg[1]["price"], tg[0]["source"]))
            rr = sizing.core_reward_risk(ents, stop, [], t1, 1.5, 1.0)
            p_avg = sum(x["weight"] * x["est_price"] for x in ents) / sum(x["weight"] for x in ents)
            fails = rr["rr"] is not None and rr["rr"] < 1.5 or rr["rr_initial_stop"] is not None and \
                rr["rr_initial_stop"] < 1.0 or (p_avg - stop) / p_avg > 0.15
            got_rr, why = S.gates(P_, stop, t1, r)
            self.assertEqual(got_rr, rr["rr"])
            self.assertEqual(why is not None, fails)


if __name__ == "__main__":
    unittest.main()
