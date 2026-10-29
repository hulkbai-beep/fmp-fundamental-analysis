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


def bars(p) -> list:
    """sim.run's hedge argument with the company's own bars as the session calendar."""
    return list(range(len(p.dates)))


def hedge_pnl(p, pl, so, sc, sess, h=S.H_LONG) -> float:
    """The SPY leg of a plan's hedged metric, replayed from its trades alone (SPEC 5.1): overnight on the shares
    held at the previous close, intraday on the shares held after the open's trades; a sale at the close keeps
    the shares through the day."""
    buys, opens, closes = {}, {}, {}
    for f in pl.filled:
        buys[f[0]] = buys.get(f[0], 0.0) + f[2]
    for x in pl.sold:
        book = closes if x[4] in ("delisted", "spin") else opens
        book[x[0]] = book.get(x[0], 0.0) + x[2]
    sh, out = 0.0, 0.0
    end = pl.end if pl.end is not None else len(p.dates) - 1
    for i in range(pl.start + 1, end + 1):
        if sess[i] - sess[pl.start] > h:
            break
        out += sh * p.c[i - 1] * (so[i] / sc[i - 1] - 1.0)
        sh += buys.get(i, 0.0) - opens.get(i, 0.0)
        out += sh * p.o[i] * (sc[i] / so[i] - 1.0)
        sh -= closes.get(i, 0.0)
    return out


class HedgedMetricTest(unittest.TestCase):
    """The primary metric's accounting, the every-start table and the forced exits."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.snap = Path(cls.tmp.name)
        synth.company(cls.snap, "SYN", seed=11, pe_amp=0.45)
        cls.p = P.build("SYN", cls.snap, SPANS, versions=("T",))
        cls.r = S.Rules()
        n = len(cls.p.dates)
        rnd = random.Random(3)
        so, sc, px = [], [], 100.0
        for _ in range(n):                                          # any SPY-like series
            so.append(px * (1 + 0.002 * rnd.gauss(0, 1)))
            px *= 1 + 0.01 * rnd.gauss(0, 1)
            sc.append(px)
        cls.spy = (so, sc, bars(cls.p))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def window_ends(self, pl):
        return pl.end is not None and pl.end - pl.start <= S.H_LONG

    def test_unhedged_equals_the_cash_flows(self):
        out = S.run(self.p, self.r, flat_rate)                      # no hedge: the hedge leg is 0
        n = 0
        for pl in out["plans"]:
            m = pl.metrics()
            self.assertAlmostEqual(m["dh252"], m["raw252"], places=12)
            if self.window_ends(pl):
                n += 1
                self.assertAlmostEqual(m["raw252"], (pl.proceeds() - pl.invested()) / pl.size, places=10)
                self.assertLessEqual(m["mae252"], 0.0)
                self.assertGreater(m["cost252"], 0.0)
        self.assertGreater(n, 10)

    def test_hedged_against_itself_leaves_dividends_less_costs(self):
        p = self.p
        out = S.run(p, self.r, flat_rate, hedge=(p.o, p.c, bars(p)))
        n = 0
        for pl in out["plans"]:
            if self.window_ends(pl):
                n += 1
                m = pl.metrics()
                self.assertAlmostEqual(m["dh252"], pl.divs / pl.size - m["cost252"], places=10)
        self.assertGreater(n, 10)

    def test_a_stock_equal_to_spy_gives_minus_costs(self):
        """SPEC check 1: with no dividends and SPY = the stock, DH_252 is minus the costs of every plan."""
        p = replace(self.p, div=[0.0] * len(self.p.dates))
        out = S.run(p, self.r, flat_rate, hedge=(p.o, p.c, bars(p)))
        for pl in out["plans"] + ([out["open"]] if out["open"] else []):
            m = pl.metrics()
            self.assertAlmostEqual(m["dh252"], -m["cost252"], places=12)
        self.assertGreater(len(out["plans"]), 10)

    def test_raw_less_hedged_is_the_hedge_leg(self):
        """SPEC check 1: raw_252 - DH_252 equals the SPY leg replayed from the plan's trades alone."""
        p, (so, sc, sess) = self.p, self.spy
        out = S.run(p, self.r, flat_rate, hedge=self.spy)
        plans = out["plans"] + ([out["open"]] if out["open"] else [])
        for pl in plans:
            m = pl.metrics()
            self.assertAlmostEqual(m["raw252"] - m["dh252"], hedge_pnl(p, pl, so, sc, sess) / pl.size, places=10)
        self.assertGreater(len(plans), 10)

    def test_the_window_counts_spy_sessions(self):
        """Bars two SPY sessions apart: the 252-session window holds the 126 bars the 126-session one holds when
        bars and sessions are one."""
        p, n = self.p, len(self.p.dates)
        flat = ([1.0] * n, [1.0] * n)
        one = S.run(p, self.r, flat_rate, hedge=flat + (bars(p),))
        two = S.run(p, self.r, flat_rate, hedge=flat + ([2 * i for i in range(n)],))
        longer = 0
        for a, b in zip(one["plans"], two["plans"]):
            self.assertEqual(a.start, b.start)
            self.assertAlmostEqual(b.metrics()["dh252"], a.metrics()["dh126"], places=12)
            longer += a.end - a.start > 126
        self.assertGreater(longer, 0)

    def test_every_start_reproduces_the_method(self):
        import placebo as PL
        p = self.p
        out = S.run(p, self.r, flat_rate, hedge=self.spy)
        zi = self.spy[2][-1]
        mine = PL.columns(p, PL.method_plans(out), self.spy[2], zi)
        pool = PL.pool(p, self.r, flat_rate, self.spy, out["first"], out["last"], zi)
        at = {s: k for k, s in enumerate(pool["start"])}
        self.assertGreater(len(pool["start"]), 3 * len(mine["start"]))
        for k, s in enumerate(mine["start"]):
            j = at[s]
            self.assertEqual(mine["status"][k], pool["status"][j])
            for m in ("dh252", "dh126", "raw252", "dep252", "mae252"):
                self.assertAlmostEqual(mine[m][k], pool[m][j], places=12)
        self.assertTrue(all(b for b, f in zip(mine["below_mid"], mine["fills"])))
        self.assertGreater(sum(1 for b in pool["below_mid"] if not b), 0)   # the pool holds any temperature

    def test_void_plans_are_kept_with_zero_metrics(self):
        p = self.p
        out = S.run(p, replace(self.r, max_price_atr=-100.0), flat_rate)  # every buy_1 above its cap: lapses
        self.assertEqual(out["plans"], [])
        self.assertGreater(len(out["voids"]), 5)
        self.assertTrue(all(v.status == "lapsed" and not v.filled for v in out["voids"]))
        self.assertTrue(all(x == 0.0 for v in out["voids"] for x in v.metrics().values()))

    def test_spin_off_sells_at_the_last_close_before(self):
        out = S.run(self.p, self.r, flat_rate)
        pl = max(out["plans"], key=lambda x: x.end - x.filled[0][0])
        mid = (pl.filled[0][0] + pl.end) // 2
        ex = self.p.dates[mid + 1]
        p2 = P.build("SYN", self.snap, SPANS, versions=("T",), spinoffs=[ex])
        self.assertEqual(p2.spin_exit, {mid})
        self.assertFalse(p2.can_start("T", mid))                     # no plan starts on that close either
        out2 = S.run(p2, self.r, flat_rate, hedge=self.spy)
        hit = [x for x in out2["plans"] if x.status == "spin"]
        self.assertEqual(len(hit), 1)
        self.assertEqual(hit[0].end, mid)
        self.assertEqual(hit[0].sold[-1][:2], (mid, p2.c[mid]))       # at that close
        self.assertFalse(any(x.start <= mid < x.end for x in out2["plans"] if x is not hit[0]))
        so, sc, sess = self.spy                                      # held through that day, sold at its close
        m = hit[0].metrics()
        self.assertAlmostEqual(m["raw252"] - m["dh252"], hedge_pnl(p2, hit[0], so, sc, sess) / hit[0].size, places=10)

    def test_a_waiting_plan_is_cancelled_before_a_spin_off(self):
        import placebo as PL
        p = self.p
        pool = PL.pool(p, self.r, flat_rate, self.spy, 0, len(p.dates) - 1, self.spy[2][-1])
        k = next(k for k, (t, f) in enumerate(zip(pool["temp0"], pool["fills"]))
                 if t == "rich" and f and pool["status"][k] != "lapsed" and
                 S.run(p, self.r, flat_rate, first_day=pool["day"][k], starts={pool["start"][k]}, single=True,
                       record_days=False)["plans"][0].filled[0][0] > pool["start"][k] + 3)
        i = pool["start"][k]
        p2 = P.build("SYN", self.snap, SPANS, versions=("T",), spinoffs=[p.dates[i + 3]])
        o = S.run(p2, self.r, flat_rate, first_day=p.dates[i], starts={i}, single=True, record_days=False)
        self.assertEqual([(v.status, v.end, v.filled) for v in o["voids"]], [("spin", i + 2, [])])

    def test_a_plan_cancelled_below_its_stop_never_bought(self):
        import placebo as PL
        p = self.p
        pool = PL.pool(p, self.r, flat_rate, self.spy, 0, len(p.dates) - 1, self.spy[2][-1])
        cut = [k for k, st in enumerate(pool["status"]) if st == "cancelled_below_stop"]
        self.assertGreater(len(cut), 10)
        for k in cut[:40]:
            i = pool["start"][k]
            o = S.run(p, self.r, flat_rate, first_day=p.dates[i], starts={i}, single=True, record_days=False,
                      hedge=self.spy)
            v = o["voids"][0]
            self.assertNotEqual(v.temp0, "fair")                     # a fair start buys at the next open
            self.assertEqual(v.filled, [])
            self.assertLess(p.c[v.end], v.stop0)
            self.assertTrue(all(p.c[j] >= v.stop0 for j in range(i, v.end)))
            self.assertTrue(all(x == 0.0 for x in v.metrics().values()))
        self.assertIn("expired", pool["status"])

    def test_suspicious_bars_start_nothing(self):
        """SPEC R2(d) / K21: a suspicious bar below the mid starts no plan and is not a pool day."""
        import placebo as PL
        p = self.p
        starts = {pl.start for pl in PL.method_plans(S.run(p, self.r, flat_rate))}
        sus = list(p.suspicious)
        for i in starts:
            sus[i] = True
        p2 = replace(p, suspicious=sus)
        again = {pl.start for pl in PL.method_plans(S.run(p2, self.r, flat_rate))}
        self.assertFalse(again & starts)
        self.assertGreater(len(again), 0)
        cands = set(PL.candidates(p2, self.r, 0, len(p.dates) - 1))
        self.assertFalse(cands & starts)

    def test_a_delisted_company_is_sold_at_its_last_close(self):
        out = S.run(self.p, self.r, flat_rate)
        pl = max(out["plans"], key=lambda x: x.end - x.filled[0][0])
        cut = self.p.dates[(pl.filled[0][0] + pl.end) // 2]
        end = (dt.date.fromisoformat(cut) + dt.timedelta(days=60)).isoformat()
        p2 = P.build("SYN", self.snap, SPANS, versions=("T",), truncate=cut, snapshot_end=end)
        self.assertTrue(p2.delisted)
        o = S.run(p2, self.r, flat_rate, hedge=(p2.o, p2.c, bars(p2)))
        last = len(p2.dates) - 1
        self.assertIsNone(o["open"])
        x = o["plans"][-1]
        self.assertEqual((x.status, x.end, x.sold[-1][:2]), ("delisted", last, (last, p2.c[last])))
        self.assertAlmostEqual(o["end_value"], o["value"][last], places=12)
        p3 = P.build("SYN", self.snap, SPANS, versions=("T",), truncate=cut, snapshot_end=cut)
        self.assertFalse(p3.delisted)
        self.assertIsNotNone(S.run(p3, self.r, flat_rate)["open"])  # the same plan, still open at the end


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
