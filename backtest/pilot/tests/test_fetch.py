"""fetch.py against a fake FMP client (the row cap, the replacement walk, redaction, the pack and the cloud's
unpacking), and status.py's tests on synthetic series. No network."""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import fetch as F  # noqa: E402
import market as M  # noqa: E402
import snapshot as SN  # noqa: E402
import status as ST  # noqa: E402
import synth  # noqa: E402
import test_run as TR  # noqa: E402
from fmp_client import FMPError  # noqa: E402

KEY = "test-key-0123456789"
Z = dt.date(2026, 10, 23)


def bdays(a: dt.date, b: dt.date):
    return [d for d in synth.weekdays(a, b)]


class FakeEOD:
    """An FMP-like daily endpoint: rows in [from, to], newest first, at most 5,000."""

    def __init__(self, first, last):
        self.days = bdays(first, last)
        self.calls = 0

    def get(self, endpoint, symbol=None, **p):
        self.calls += 1
        a, b = F.day(p["from"]), F.day(p["to"])
        return [{"date": d.isoformat(), "close": 1.0} for d in reversed(self.days) if a <= d <= b][:F.EOD_ROW_CAP]


class FakeClient:
    """Serves a synthetic source snapshot the way FMP answers."""

    def __init__(self, src: Path, fail=None):
        self.src, self.fail = src, fail or {}
        self.stats = {"network_calls": 0}

    def _rows(self, part, sym):
        p = self.src / "raw" / part / f"{sym}.json"
        return json.loads(p.read_text()) if p.exists() else []

    def get(self, endpoint, **p):
        self.stats["network_calls"] += 1
        sym = p.get("symbol")
        if (endpoint, sym) in self.fail:
            raise FMPError(self.fail[(endpoint, sym)])
        daily = {"historical-price-eod/full": "full", "historical-price-eod/dividend-adjusted": "adj"}
        if endpoint in daily or endpoint == "historical-price-eod/light":
            rows = self._rows(daily.get(endpoint, "full"), sym)
            a, b = p["from"], p["to"]
            rows = [r for r in rows if a <= r["date"] <= b]
            if endpoint == "historical-price-eod/light":
                rows = [{"symbol": sym, "date": r["date"], "price": r["close"]} for r in rows]
            return rows[:F.EOD_ROW_CAP]
        if endpoint == "treasury-rates":
            b = F.day(p["to"])
            a = max(F.day(p["from"]), b - dt.timedelta(days=89))
            return [r for r in self._rows("market", "treasury") if a.isoformat() <= r["date"] <= b.isoformat()][::-1]
        if endpoint == "income-statement":
            return self._rows("inc_q" if p.get("period") == "quarter" else "inc_a", sym)
        part = {"splits": "splits", "dividends": "div", "earnings": "earn", "profile": "profile",
                "analyst-estimates": "est"}.get(endpoint)
        if part:
            return self._rows(part, sym)
        if endpoint == "historical-market-capitalization":
            return [{"symbol": sym, "date": p["from"], "marketCap": 1e9}]
        raise FMPError(f"HTTP 404 on {endpoint}")


class DailyHistoryTest(unittest.TestCase):
    def check(self, first, last, start, end):
        f = FakeEOD(first, last)
        rows, problem, n = F.daily_history(f.get, "historical-price-eod/full", "X", start, end)
        self.assertEqual([r["date"] for r in rows], [d.isoformat() for d in f.days if start <= d <= end])
        return n

    def test_shapes(self):
        self.assertEqual(self.check(dt.date(1990, 1, 2), Z, F.GLOBAL_START, Z), 2)       # needs two requests
        self.assertEqual(self.check(dt.date(2020, 12, 9), Z, F.GLOBAL_START, Z), 1)       # began inside the chunk
        self.check(dt.date(1990, 1, 2), dt.date(2016, 2, 1), F.GLOBAL_START, Z)          # delisted 2016
        self.check(dt.date(1990, 1, 2), dt.date(2008, 6, 30), F.GLOBAL_START, Z)         # ended before the first chunk
        self.assertEqual(self.check(dt.date(1990, 1, 2), Z, dt.date(2011, 3, 1), Z), 1)  # fits the cap: one request
        self.assertEqual(self.check(dt.date(1993, 1, 29), Z, F.MARKET_START, Z), 1)

    def test_last_session_and_start(self):
        self.assertEqual(F.last_session(dt.datetime(2026, 10, 29, 20, 30)), dt.date(2026, 10, 29))   # 16:30 EDT
        self.assertEqual(F.last_session(dt.datetime(2026, 10, 29, 15, 0)), dt.date(2026, 10, 28))    # 11:00 EDT
        self.assertEqual(F.last_session(dt.datetime(2026, 11, 2, 1, 0)), dt.date(2026, 10, 30))      # Sunday evening
        self.assertEqual(F.price_start([["1996-01-02", "2026-10-29"]], Z), dt.date(2004, 11, 2))
        self.assertEqual(F.price_start([["2025-03-24", "2026-10-29"]], Z), dt.date(2022, 1, 23))


class StatusTest(unittest.TestCase):
    def test_duplicates(self):
        rnd = random.Random(3)
        days = [d.isoformat() for d in bdays(dt.date(2015, 1, 2), dt.date(2017, 12, 29))]
        a, b, px = {}, {}, 50.0
        for d in days:
            px *= math.exp(0.02 * rnd.gauss(0, 1))
            a[d] = px
            b[d] = px * (1 + 0.03 * rnd.gauss(0, 1))
        self.assertEqual(ST.duplicate_of(a, {d: 2 * v for d, v in a.items()}), "same series")
        self.assertIsNone(ST.duplicate_of(a, b))
        twin = {d: v * math.exp(0.001 * rnd.gauss(0, 1)) for d, v in a.items()}
        self.assertIn(ST.duplicate_of(a, twin), ("same series", "twin"))


class FetchRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        src = root / "src"
        TR.market(src)
        for k, sym in enumerate(("AAA", "BBB", "CCC", "EEE")):
            synth.company(src, sym, seed=60 + k, pe_amp=0.4)
        (src / "raw" / "inc_q" / "BBB.json").write_text("[]")       # BBB: no quarterly statements -> U2 fails
        recs = {s: {"series": s, "sector": "Tech", "spans": [["2006-01-03", "2030-01-01"]]} for s in
                ("AAA", "BBB", "CCC", "EEE")}
        recs["EEE"]["bars_from"] = "2019-01-02"                          # a reused ticker: skipped by the walk
        cls.sample = root / "sample.json"
        cls.sample.write_text(json.dumps({"sample": ["AAA", "BBB"], "order": {"Tech": ["AAA", "BBB", "EEE", "CCC"]},
                                          "spares": {"Tech": ["EEE", "CCC"]}, "records": recs}))
        cls.out = root / "snap"
        fail = {("earnings", "AAA"): f"HTTP 404 on earnings: bad request apikey={KEY}"}
        with mock.patch.object(F, "FMPClient", lambda use_cache=False: FakeClient(src, fail)), \
                mock.patch.dict(os.environ, {"FMP_API_KEY": KEY}, clear=False):
            for v in F.ENV_REFUSED:
                os.environ.pop(v, None)
            cls.rc = F.main(["--out", str(cls.out), "--sample", str(cls.sample), "--end", Z.isoformat()])
            cls.zip = root / "snap.zip"
            cls.rc_pack = F.main(["--out", str(cls.out), "--pack", str(cls.zip)])
        cls.status = json.loads((cls.out / "status.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_run_and_walk(self):
        self.assertEqual(self.rc, 1)                                     # the failed earnings part
        self.assertEqual([c[0] for c in self.status["companies"]], ["AAA", "CCC"])
        sw = self.status["replacements"][0]
        self.assertEqual((sw["out"], sw["in"]), ("BBB", "CCC"))
        self.assertTrue(sw["why"].startswith("TTM EPS on 0%"))
        self.assertEqual(sw["tried"][0]["key"], "EEE")
        self.assertFalse((self.out / "raw" / "full" / "EEE.json").exists())   # never fetched

    def test_no_key_anywhere_and_redacted(self):
        log = json.loads((self.out / "fetch_log.json").read_text())
        self.assertEqual(len(log["failures"]), 1)
        self.assertIn("***", log["failures"][0]["error"])
        for f in self.out.rglob("*"):
            if f.is_file():
                self.assertNotIn(KEY.encode(), f.read_bytes(), f)

    def test_manifest_pack_unpack(self):
        self.assertEqual(M.check_manifest(self.out), [])
        self.assertEqual(self.rc_pack, 0)
        import hashlib
        zmd5 = hashlib.md5(self.zip.read_bytes()).hexdigest()
        mmd5 = hashlib.md5((self.out / "manifest.json").read_bytes()).hexdigest()
        dest = Path(self.tmp.name) / "unpacked"
        self.assertEqual(SN.main(["--zip", str(self.zip), "--zip-md5", zmd5, "--manifest-md5", mmd5,
                                  "--out", str(dest)]), 0)
        self.assertEqual(M.check_manifest(dest), [])
        self.assertEqual(SN.main(["--zip", str(self.zip), "--zip-md5", "0" * 32, "--manifest-md5", mmd5,
                                  "--out", str(Path(self.tmp.name) / "u2")]), 2)
        stray = self.out / "raw" / "full" / "ZZZ.json"
        stray.write_text("[]")
        try:
            self.assertEqual(M.check_manifest(self.out), ["raw/full/ZZZ.json"])
        finally:
            stray.unlink()

    def test_key_with_whitespace_is_still_redacted(self):
        """A key read with a trailing CR (a CRLF key file in Git Bash) is the stripped key the client sends: the
        failure text is redacted all the same."""
        out = Path(self.tmp.name) / "snap_cr"
        fail = {("earnings", "AAA"): f"HTTP 404 on earnings: bad request apikey={KEY}"}
        with mock.patch.object(F, "FMPClient", lambda use_cache=False: FakeClient(Path(self.tmp.name) / "src", fail)), \
                mock.patch.dict(os.environ, {"FMP_API_KEY": KEY + "\r\n"}, clear=False):
            F.main(["--out", str(out), "--sample", str(self.sample), "--end", Z.isoformat()])
        log = json.loads((out / "fetch_log.json").read_text())
        self.assertIn("***", log["failures"][0]["error"])
        for f in out.rglob("*"):
            if f.is_file():
                self.assertNotIn(KEY.encode(), f.read_bytes(), f)

    def test_pack_refuses_a_scan_file_that_is_not_there(self):
        z = Path(self.tmp.name) / "no.zip"
        with mock.patch.dict(os.environ, {"FMP_API_KEY": KEY}, clear=False):
            rc = F.main(["--out", str(self.out), "--pack", str(z), "--scan", str(Path(self.tmp.name) / "consle.log")])
        self.assertNotEqual(rc, 0)
        self.assertFalse(z.exists())

    def test_rerun_fetches_nothing_new(self):
        with mock.patch.object(F, "FMPClient", lambda use_cache=False: FakeClient(Path(self.tmp.name) / "src")), \
                mock.patch.dict(os.environ, {"FMP_API_KEY": KEY}, clear=False):
            rc = F.main(["--out", str(self.out), "--sample", str(self.sample)])
        self.assertEqual(rc, 0)                                          # the earnings part now succeeds
        self.assertTrue((self.out / "raw" / "earn" / "AAA.json").exists())
        self.assertEqual(M.check_manifest(self.out), [])


if __name__ == "__main__":
    unittest.main()
