"""
Offline tests for the insider-trades section (scripts/insider.py). No API key or network needed:

    python3 -m unittest discover -s tests

The rows follow FMP's insider-trading/search shape, checked against the live API: 16 fields per row,
newest filing first, typeOfOwner with HTML entities, Form 3 rows with an empty transactionType.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import insider as I  # noqa: E402
from fmp_client import RestrictedEndpoint  # noqa: E402

TODAY = dt.date(2026, 10, 25)


def row(days_ago, name, code, shares, price, owner="director", form="4", filed_after=2):
    d = TODAY - dt.timedelta(days=days_ago)
    return {"filingDate": (d + dt.timedelta(days=filed_after)).isoformat(), "transactionDate": d.isoformat(),
            "reportingCik": name, "transactionType": code, "reportingName": name, "typeOfOwner": owner,
            "directOrIndirect": "D", "formType": form, "securitiesTransacted": shares, "price": price,
            "url": "https://www.sec.gov/Archives/edgar/data/1/1-index.htm"}


class Roles(unittest.TestCase):
    def test_titles_from_real_filings(self):
        cases = {
            "director, officer: President &amp; Chief Exec Officer": "Director, CEO",
            "officer: CEO Worldwide Amazon Stores": "Officer",  # a business unit's CEO
            "officer: Chair and CEO": "CEO",
            "officer: CFO, Treasurer and EVP": "CFO",
            "officer: Senior Vice President,  CFO": "CFO",
            "officer: COO": "Officer",
            "10 percent owner": "10% owner",
            "director": "Director",
            "": "Other",
        }
        for owner, want in cases.items():
            self.assertEqual(I.role(owner), want, owner)


class Summary(unittest.TestCase):
    def test_counts_only_open_market_trades_once(self):
        rows = [row(10, "A", "S-Sale", 1000, 50), row(12, "A", "F-InKind", 300, 50), row(20, "B", "P-Purchase", 100, 40),
                row(20, "B", "P-Purchase", 100, 40, form="4/A"),        # amended repeat
                row(30, "C", "", 0, 0, form="3"),                       # initial holdings, not a trade
                row(40, "D", "A-Award", 5000, 0), row(50, "A", "M-Exempt", 800, 10),
                row(400, "B", "P-Purchase", 900, 30)]                  # before the 12-month window
        s = I.summarize(rows, TODAY, market_cap=1e9)
        self.assertEqual((s["buys"]["trades"], s["buys"]["value"]), (1, 4000))
        self.assertEqual((s["sells"]["trades"], s["sells"]["value"]), (1, 50000))
        self.assertEqual(s["other"], 3)  # tax withholding, award, option exercise; not the Form 3
        self.assertAlmostEqual(s["sells_vs_mcap"], 5e-5)
        self.assertIsNone(s["cluster"])
        self.assertEqual(I.flags(s), [])

    def test_cluster_needs_three_insiders_within_90_days(self):
        two = [row(10, "A", "P-Purchase", 100, 10), row(40, "B", "P-Purchase", 100, 10), row(200, "C", "P-Purchase", 100, 10)]
        self.assertIsNone(I.summarize(two, TODAY)["cluster"])
        three = two + [row(80, "D", "P-Purchase", 1000, 10)]
        c = I.summarize(three, TODAY)["cluster"]
        self.assertEqual((c["insiders"], c["value"]), (3, 12000))
        self.assertEqual((c["from"], c["to"]), ((TODAY - dt.timedelta(days=80)).isoformat(),
                                                (TODAY - dt.timedelta(days=10)).isoformat()))
        self.assertTrue(I.flags(I.summarize(three, TODAY))[0].startswith("Insider cluster buying: 3 insiders bought 12.00K"))

    def test_large_ceo_purchase_is_flagged_on_its_own(self):
        rows = [row(15, "TAN LIP BU", "P-Purchase", 105263, 95, owner="director, officer: CEO"),
                row(20, "Small", "P-Purchase", 100, 95, owner="officer: EVP, CFO")]   # under BIG_BUY
        f = I.flags(I.summarize(rows, TODAY))
        self.assertEqual(f, [f"Insider buying: TAN LIP BU (Director, CEO) bought 10.00M on the open market on "
                             f"{(TODAY - dt.timedelta(days=15)).isoformat()}"])

    def test_not_in_plan(self):
        s = I.summarize(None, TODAY)
        self.assertEqual(s, {"restricted": True})
        self.assertEqual(I.flags(s), [])
        self.assertIn("not in your FMP plan", I.render(s))


class Paging(unittest.TestCase):
    class Client:
        def __init__(self, rows, refuse_from=None):
            self.rows, self.refuse_from, self.pages, self.restricted = rows, refuse_from, [], []

        def try_get(self, endpoint, symbol, page, limit):
            self.pages.append(page)
            if self.refuse_from is not None and page >= self.refuse_from:
                self.restricted.append(endpoint)
                return None
            return self.rows[page * limit:(page + 1) * limit]

        def unrestrict(self, endpoint):
            self.restricted.remove(endpoint)

    def rows(self, n, step_days):
        return [row(i * step_days, f"P{i}", "S-Sale", 10, 10) for i in range(n)]

    def test_stops_once_a_page_reaches_past_the_window(self):
        c = self.Client(self.rows(400, 2))   # 100 rows = 200 days
        rows, complete = I.fetch(c, "X", TODAY)
        self.assertEqual((c.pages, len(rows), complete), ([0, 1], 200, True))

    def test_partial_when_the_pages_run_out(self):
        c = self.Client(self.rows(600, 0.5))   # 500 rows = 250 days
        rows, complete = I.fetch(c, "X", TODAY)
        self.assertEqual((len(rows), complete), (500, False))
        s = I.summarize(rows, TODAY, complete=complete)
        self.assertEqual(s["from"], min(r["transactionDate"] for r in rows))
        self.assertIn("FMP returned only the latest 500 filings", I.render(s))

    def test_a_refused_later_page_keeps_the_first(self):
        c = self.Client(self.rows(300, 1), refuse_from=1)
        rows, complete = I.fetch(c, "X", TODAY)
        self.assertEqual((len(rows), complete, c.restricted), (100, False, []))
        c = self.Client(self.rows(300, 1), refuse_from=0)
        self.assertEqual(I.fetch(c, "X", TODAY), (None, False))


class EndToEnd(unittest.TestCase):
    """The section in the full analysis of the synthetic companies, and its translations."""

    @classmethod
    def setUpClass(cls):
        import analyze as A
        import fake_fmp
        cls.A = A
        with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient):
            cls.qual = A.analyze(A.parse_args(["QUAL", "--peers", "none"]))
            cls.qual_off = A.analyze(A.parse_args(["QUAL", "--peers", "none", "--no-insider"]))
            cls.bank = A.analyze(A.parse_args(["BANK", "--peers", "none"]))
        cls.i18n = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")

    def test_section_flag_and_score(self):
        rep = self.A.render(self.qual)
        self.assertIn("Insider trades (last 12 months, observation only)", rep)
        self.assertIn("| Purchases | 3 | 3 |", rep)
        self.assertIn("[Form 4](https://www.sec.gov/", rep)
        self.assertTrue(any(g.startswith("Insider cluster buying: 3 insiders") for g in self.qual["flags"]["green"]))
        self.assertEqual(self.qual["score"], self.qual_off["score"])  # observation only
        self.assertNotIn("Insider trades", self.A.render(self.qual_off))
        self.assertIn("No open-market purchases or sales in this period.", self.A.render(self.bank))

    def test_every_line_has_a_chinese_translation(self):
        rep = self.A.render(self.qual) + "\n" + self.A.render(self.bank)
        sec = rep[rep.index("Insider trades ("):]
        sec = sec[:sec.index("\n## ")]
        rules = [re.compile(m) for m in re.findall(r"\[/(\^.+?\$)/,", self.i18n)]
        exact = set(re.findall(r'"((?:[^"\\]|\\.)+)":\s*"', self.i18n))
        lines = [l.strip() for l in sec.split("\n")[1:] if l.strip() and not set(l) <= set("|-")]
        cells = [c.strip() for l in lines if l.startswith("|") for c in l.strip("|").split("|")]
        texts = [l for l in lines if not l.startswith("|")] + [c for c in cells if re.search(r"[a-z]{3}", c)
                                                              and not c.startswith("[Form 4]")]
        texts += [g for g in self.qual["flags"]["green"] if g.startswith("Insider")]
        names = {"Stone Maria", "Diaz Carlos", "Lee Ann", "Park Min"}
        for t in texts:
            if t in names:
                continue
            js = t.replace("\\", "\\\\")
            self.assertTrue(t in exact or js in exact or any(r.search(t.replace("/", "\\/")) or r.search(t) for r in rules),
                            f"no translation for: {t}")
