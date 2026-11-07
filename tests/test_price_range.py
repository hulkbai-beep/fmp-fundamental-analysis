"""
Offline tests of the local page's price ranges (ui/price_range.py): the ranges v1.x showed in its report and page,
now worked out for the page only, from a fa-2.0 document and the past year's daily closes. No API key needed:

    python -m unittest discover -s tests
"""
from __future__ import annotations

import copy
import json
import math
import statistics
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ui"))

import analyze as A  # noqa: E402
import facts as F  # noqa: E402
import fake_fmp  # noqa: E402
import price_range as PR  # noqa: E402
from test_facts import SAVED  # noqa: E402

PAGES = {}  # symbol -> (the fa-2.0 document, the daily closes) as ui/server.py gets them


def setUpModule():
    with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient), mock.patch.object(A.R, "render", return_value=""):
        for sym in ("QUAL", "TRAP", "BANK", "UTIL", "QTRS", "REIT"):
            doc, _, chart = A.run_page(A.parse_args([sym, "--peers", "none"]))
            PAGES[sym] = (doc, chart["prices"])


def rows(pr, kind=None):
    return [r for r in pr["rows"] if kind is None or r["kind"] == kind]


def close(a, b):
    return math.isclose(a, b, rel_tol=1e-9)


class SameAsBefore(unittest.TestCase):
    def test_the_multiple_and_dcf_ranges_v1_showed(self):
        """Results v1.x saved (tests/data/saved_8c5ceed.json) hold the ranges v1.x showed; the page gets the same
        ones from the fa-2.0 document built from each result: forward P/E and EV/EBITDA now and at both fiscal
        year ends (net debt from the TTM for QTRS), the DCF range and the DCF value against the price."""
        for sym, case in SAVED.items():
            full = case["full"]
            pr = PR.build(F.build(full), [])
            saved = [s for s in full["price_range"]["summary"] if s["kind"] in ("fwd_pe", "fwd_ev", "dcf")]
            self.assertEqual([(r["kind"], r["at"], r["fy"]) for r in pr["rows"]],
                             [(s["kind"], s["at"], s["fy"]) for s in saved], sym)
            for r, s in zip(pr["rows"], saved):
                for k in ("low", "mid", "high"):
                    self.assertTrue(close(r[k], s[k]), (sym, r["kind"], r["fy"], k, r[k], s[k]))
            mos = full["dcf"].get("margin_of_safety")
            self.assertTrue(pr["dcf_vs_price"] is mos is None or close(pr["dcf_vs_price"], mos), sym)
        self.assertEqual(SAVED["QTRS"]["facts"]["periods"]["valuation_basis"], "TTM")

    def test_the_header_ranges_v1_showed(self):
        """Forward P/E 25th-75th percentile now (next-twelve-month EPS, weighted by the time left in the fiscal year
        in progress), then on the EPS of the fiscal year in progress and of the next on their own."""
        full = SAVED["QUAL"]["full"]
        pr = PR.build(F.build(full), [])
        now = next(p for p in full["price_range"]["forward"] if p["at"] == "now")
        band = full["price_range"]["pe_band"]
        w = round(now["weight"] * 100)
        open_fys = [e for e in full["analyst"]["estimates"] if not e["ended"]][:2]
        want = [("now", None, now["pe"]["low"], now["pe"]["high"], [[now["uses"][0], w], [now["uses"][1], 100 - w]])]
        want += [("fy", e["fy"], e["eps_avg"] * band["p25"], e["eps_avg"] * band["p75"], [[e["fy"], None]])
                 for e in open_fys]
        got = [(t["at"], t["fy"], t["low"], t["high"], t["uses"]) for t in pr["pe_ranges"]]
        self.assertEqual([g[:2] + g[4:] for g in got], [x[:2] + x[4:] for x in want])
        for g, x in zip(got, want):
            self.assertTrue(close(g[2], x[2]) and close(g[3], x[3]), (g, x))


class FromTheCloses(unittest.TestCase):
    def test_the_trading_range_and_the_volatility(self):
        doc, prices = PAGES["QUAL"]
        pr = PR.build(doc, prices)
        start = (A.dt.date.fromisoformat(doc["as_of"]) - A.dt.timedelta(days=365)).isoformat()
        year = [(d, c) for d, c in prices if start <= d <= doc["as_of"]]
        (w52,) = rows(pr, "week52")
        self.assertEqual((w52["low"], w52["high"], w52["from"], w52["to"], w52["mid"]),
                         (min(c for _, c in year), max(c for _, c in year), year[0][0], year[-1][0], None))
        moves = [math.log(b / a) for (_, a), (_, b) in zip(year, year[1:])]
        sigma = statistics.stdev(moves) * math.sqrt(252)
        price = doc["price"]["value"]
        vol = rows(pr, "volatility")
        ends = [(e["fy"], e["date"]) for e in doc["consensus"]["estimates"] if not e["ended"]][:2]
        self.assertEqual([(r["fy"], r["date"], r["at"]) for r in vol], [(fy, d, "fy_end") for fy, d in ends])
        for r in vol:
            years = (A.dt.date.fromisoformat(r["date"]) - A.dt.date.fromisoformat(doc["as_of"])).days / 365.25
            self.assertTrue(close(r["sigma"], sigma) and close(r["years"], years))
            for k, z in (("low", -1), ("high", 1), ("low95", -1.96), ("high95", 1.96)):
                self.assertTrue(close(r[k], price * math.exp(z * sigma * math.sqrt(years))), k)
            self.assertEqual(r["mid"], price)

    def test_only_the_52_weeks_to_the_document_date_count(self):
        doc, _ = PAGES["QUAL"]
        as_of = A.dt.date.fromisoformat(doc["as_of"])
        day = lambda n: (as_of + A.dt.timedelta(days=n)).isoformat()  # noqa: E731
        closes = [[day(-400), 1.0], [day(-365), 50.0], [day(-10), None], [day(-5), 0], [day(-3), "x"],
                  [day(0), 60.0], [day(1), 999.0]]
        (w52,) = rows(PR.build(doc, closes), "week52")
        self.assertEqual((w52["low"], w52["high"], w52["from"], w52["to"]), (50.0, 60.0, day(-365), day(0)))
        self.assertEqual(rows(PR.build(doc, closes[:2] + closes[-1:]), "week52"), [])  # one close is no range

    def test_a_volatility_needs_six_months_of_moves(self):
        doc, _ = PAGES["QUAL"]
        as_of = A.dt.date.fromisoformat(doc["as_of"])
        closes = [[(as_of - A.dt.timedelta(days=n)).isoformat(), 100.0 * (1.01 if n % 2 else 0.99)]
                  for n in range(PR.MIN_MOVES, -1, -1)]   # MIN_MOVES + 1 closes, MIN_MOVES moves
        self.assertEqual(len(rows(PR.build(doc, closes), "volatility")), 2)
        self.assertEqual(rows(PR.build(doc, closes[1:]), "volatility"), [])

    def test_without_closes_only_the_document_ranges(self):
        doc, _ = PAGES["QUAL"]
        self.assertEqual({r["kind"] for r in PR.build(doc, [])["rows"]}, {"fwd_pe", "fwd_ev", "dcf"})


class Shape(unittest.TestCase):
    def test_rows_go_by_horizon_in_time_order(self):
        doc, prices = PAGES["QUAL"]
        pr = PR.build(doc, prices)
        self.assertEqual([(r["kind"], r["at"], r["fy"]) for r in pr["rows"]],
                         [("week52", "past", None), ("fwd_pe", "now", None), ("fwd_ev", "now", None),
                          ("dcf", "now", None), ("fwd_pe", "fy_end", "2026"), ("fwd_ev", "fy_end", "2026"),
                          ("volatility", "fy_end", "2026"), ("fwd_pe", "fy_end", "2027"),
                          ("fwd_ev", "fy_end", "2027"), ("volatility", "fy_end", "2027")])
        self.assertEqual([r["date"] for r in pr["rows"]], sorted(r["date"] for r in pr["rows"]))
        self.assertEqual((pr["price"], pr["as_of"]), (doc["price"]["value"], doc["as_of"]))

    def test_what_each_row_rests_on(self):
        doc, prices = PAGES["QUAL"]
        pr = PR.build(doc, prices)
        band, ntm = doc["valuation"]["forward_band"], doc["valuation"]["forward"]["ntm"]
        pe_now, ev_now, dcf = rows(pr)[1:4]
        q = [band["pe"][k] for k in ("p25", "median", "p75")]
        self.assertEqual((pe_now["eps"], pe_now["uses"], pe_now["weight"], pe_now["multiples"]),
                         (ntm["eps"], ntm["fys"], ntm["weight"], q))
        self.assertEqual([pe_now[k] for k in ("low", "mid", "high")], [ntm["eps"] * m for m in q])
        nd, shares = doc["statements"]["net_debt"][-1], doc["company"]["market_cap"] / doc["price"]["value"]
        qe = [band["ev_ebitda"][k] for k in ("p25", "median", "p75")]
        self.assertEqual(ev_now["net_debt"], nd)
        self.assertEqual([ev_now[k] for k in ("low", "mid", "high")], [(m * ntm["ebitda"] - nd) / shares for m in qe])
        m = doc["models"]["dcf"]
        self.assertEqual((dcf["low"], dcf["mid"], dcf["high"], dcf["discount_rate"], dcf["growth"]),
                         (m["low"], m["value_per_share"], m["high"], m["inputs"]["discount_rate"]["value"],
                          m["inputs"]["growth_1_5"]))
        # at a fiscal year end the next twelve months are the following fiscal year
        est = doc["consensus"]["estimates"]
        pe_fy = [r for r in rows(pr, "fwd_pe") if r["at"] == "fy_end"]
        self.assertEqual([(r["fy"], r["uses"], r["eps"]) for r in pe_fy],
                         [(est[0]["fy"], [est[1]["fy"]], est[1]["eps_avg"]), (est[1]["fy"], [est[2]["fy"]], est[2]["eps_avg"])])

    def test_every_company_gives_plain_json(self):
        for sym, (doc, prices) in PAGES.items():
            pr = PR.build(doc, prices)
            self.assertEqual(json.loads(json.dumps(pr, allow_nan=False)), pr, sym)
            for r in pr["rows"]:
                self.assertTrue(0 < r["low"] <= r["high"] and (r["mid"] is None or r["low"] <= r["mid"] <= r["high"]),
                                (sym, r))


class LeftOut(unittest.TestCase):
    def test_a_measure_not_meaningful_for_the_company_gives_no_row(self):
        doc, prices = PAGES["REIT"]
        self.assertIn("pe", doc["company"]["not_meaningful"])
        pr = PR.build(doc, prices)
        self.assertEqual((rows(pr, "fwd_pe"), pr["pe_ranges"]), ([], []))
        self.assertTrue(rows(pr, "fwd_ev"))
        doc, prices = PAGES["BANK"]
        self.assertTrue({"ev_ebitda", "dcf"} <= set(doc["company"]["not_meaningful"]))
        pr = PR.build(doc, prices)
        self.assertEqual((rows(pr, "fwd_ev"), rows(pr, "dcf"), pr["dcf_vs_price"]), ([], [], None))
        self.assertTrue(rows(pr, "fwd_pe"))

    def test_a_price_that_is_not_positive_gives_no_row(self):
        """TRAP's net debt is above the EV its multiples give, and its DCF value is not positive: v1.x showed those
        ranges as negative prices; the page leaves them out."""
        doc, prices = PAGES["TRAP"]
        self.assertEqual(doc["models"]["dcf"]["status"], "value_not_positive")
        pr = PR.build(doc, prices)
        self.assertEqual({r["kind"] for r in pr["rows"]}, {"week52", "volatility"})
        self.assertIsNone(pr["dcf_vs_price"])
        # without the net debt, the same multiples give positive prices
        ok = copy.deepcopy(doc)
        ok["statements"]["net_debt"] = [0.0] * len(ok["statements"]["net_debt"])
        self.assertTrue(rows(PR.build(ok, prices), "fwd_ev"))

    def test_without_estimates_the_volatility_runs_twelve_months(self):
        doc, prices = PAGES["QUAL"]
        bare = copy.deepcopy(doc)
        bare["consensus"]["estimates"] = []
        pr = PR.build(bare, prices)
        self.assertEqual([(r["kind"], r["at"]) for r in pr["rows"]], [("week52", "past"), ("dcf", "now"),
                                                                      ("volatility", "12m")])
        as_of = A.dt.date.fromisoformat(doc["as_of"])
        self.assertEqual(pr["rows"][-1]["date"], (as_of + A.dt.timedelta(days=365)).isoformat())
        self.assertEqual(pr["pe_ranges"], [])

    def test_a_document_without_its_date_or_figures(self):
        self.assertEqual(PR.build({}, []), {"price": None, "as_of": None, "rows": [], "pe_ranges": [],
                                            "dcf_vs_price": None})
        doc, prices = PAGES["QUAL"]
        self.assertEqual(PR.build(dict(doc, as_of=None), prices)["rows"], [])
        no_price = copy.deepcopy(doc)
        no_price["price"]["value"] = None
        pr = PR.build(no_price, prices)
        self.assertEqual({r["kind"] for r in pr["rows"]}, {"week52", "fwd_pe", "dcf"})  # no shares for EV, no volatility
        self.assertIsNone(pr["dcf_vs_price"])

    def test_the_valuation_basis_period_gives_the_net_debt(self):
        doc, _ = PAGES["QTRS"]
        self.assertEqual(doc["periods"]["valuation_basis"], "TTM")
        self.assertEqual(PR.basis_debt(doc), (doc["ttm"]["net_debt"], doc["ttm"]["minority_interest"] or 0.0))
        doc, _ = PAGES["QUAL"]
        i = doc["statements"]["period"].index(doc["periods"]["valuation_basis"])
        self.assertEqual(PR.basis_debt(doc), (doc["statements"]["net_debt"][i], 0.0))
        self.assertEqual(PR.basis_debt(dict(doc, periods={"valuation_basis": "FY1999"})), (None, 0.0))


if __name__ == "__main__":
    unittest.main()
