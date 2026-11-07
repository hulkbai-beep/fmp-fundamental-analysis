"""
Offline tests of the command line (scripts/analyze.py and the scripts/facts.py converter) and of the local page's
/api/analyze answer (ui/server.py). No API key needed:

    python -m unittest discover -s tests

v2.0 writes one document, fa-2.0: --json, --facts and the deprecated --contract all write it, stdout is the
report alone (facts_report.py, tested in test_facts_report.py) and notes go to stderr. Without peers and
--macro an analysis makes 14 API calls; --macro also fetches the returns and the Treasury curve 3M and 1Y ago
for its section. The page gets the same document and report, and beside them its price chart's daily bars (one
more API call, made only for the page) and its price ranges (ui/price_range.py, tested in test_price_range.py).
"""
from __future__ import annotations

import collections
import contextlib
import datetime as dt
import io
import json
import os
import sys
import tempfile
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
from fmp_client import FMPClient, FMPError, InvalidKey  # noqa: E402
from test_facts import SAVED, text, validate  # noqa: E402

REPORT = "# QUAL - the report as report.render() returns it"
DEFAULT_CALLS = {"profile": 1, "quote": 1, "income-statement": 2, "balance-sheet-statement": 2,
                 "cash-flow-statement": 2, "analyst-estimates": 1, "historical-price-eod/light": 1,
                 "treasury-rates": 1, "market-risk-premium": 1, "historical-sector-pe": 1, "historical-industry-pe": 1}
MACRO_CALLS = dict(DEFAULT_CALLS, **{"treasury-rates": 3, "historical-price-eod/light": 2,
                                     "historical-sector-performance": 1, "historical-industry-performance": 1,
                                     "economic-indicators": 3, "economic-calendar": 3})


def recording_client():
    """A FakeClient class that logs every network call as (endpoint, params), and that log."""
    log = []

    class Client(fake_fmp.FakeClient):
        def _fetch(self, endpoint, params):
            log.append((endpoint, dict(params)))
            return super()._fetch(endpoint, params)
    return Client, log


def failing_client(error):
    class Client(fake_fmp.FakeClient):
        def _fetch(self, endpoint, params):
            raise error
    return Client


def run_main(main, argv, client=fake_fmp.FakeClient):
    """(exit code, stdout, stderr) of main(argv) on an offline client."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(A, "FMPClient", client), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def without_time(doc):
    return {k: v for k, v in doc.items() if k != "generated_at"}


class Outputs(unittest.TestCase):
    def test_json_facts_and_contract_write_the_same_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [str(Path(tmp) / n) for n in ("full.json", "facts.json", "contract.json")]
            code, out, err = run_main(A.main, ["QTRS", "--peers", "none", "--json", paths[0], "--facts", paths[1],
                                               "--contract", paths[2]])
            texts = [Path(p).read_text(encoding="utf-8") for p in paths]
        self.assertEqual(code, 0)
        self.assertEqual(texts[1:], texts[:1] * 2)
        doc = json.loads(texts[0])
        self.assertEqual((doc["contract"], doc["ticker"]), (F.FACTS, "QTRS"))
        self.assertEqual(validate(doc), [])
        self.assertEqual(texts[0], F.dumps(doc))
        self.assertIn("(--contract is deprecated: fa-1.1 was removed in v2.0; it now writes fa-2.0, like --json)", err)
        for p in paths:
            self.assertIn(f"({F.FACTS} written to {p})", err)
        self.assertTrue(out.startswith("# "))
        self.assertNotIn("written to", out)
        self.assertNotIn("deprecated", out)

    def test_stdout_is_the_report_alone(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(A.R, "render", return_value=REPORT):
            code, out, err = run_main(A.main, ["QUAL", "--peers", "none", "--json", str(Path(tmp) / "f.json")])
        self.assertEqual((code, out), (0, REPORT + "\n"))
        self.assertEqual(err.strip().splitlines(), [f"({F.FACTS} written to {Path(tmp) / 'f.json'})"])

    def test_iv_and_no_insider_are_accepted_and_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain, given = str(Path(tmp) / "plain.json"), str(Path(tmp) / "given.json")
            self.assertEqual(run_main(A.main, ["QUAL", "--peers", "none", "--json", plain])[0], 0)
            code, out, err = run_main(A.main, ["QUAL", "--peers", "none", "--iv", "0.45", "--no-insider",
                                               "--json", given])
            docs = [json.loads(Path(p).read_text(encoding="utf-8")) for p in (plain, given)]
        self.assertEqual(code, 0)
        self.assertIn("(--iv is ignored: v2.0 has no volatility range)", err)
        self.assertIn("(--no-insider is ignored: v2.0 fetches no insider trades)", err)
        self.assertEqual(without_time(docs[1]), without_time(docs[0]))
        self.assertTrue(out.startswith("# "))

    def test_a_file_that_cannot_be_written(self):
        """The other files are still written, the run says which one failed, and it exits 1."""
        with tempfile.TemporaryDirectory() as tmp:
            bad, good = Path(tmp) / "missing" / "doc.json", Path(tmp) / "doc.json"
            code, out, err = run_main(A.main, ["QUAL", "--peers", "none", "--json", str(bad), "--facts", str(good)])
            self.assertTrue(good.exists())
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("# QUAL - "))
        self.assertIn(f"Cannot write {bad}: ", err)
        self.assertIn(f"({F.FACTS} written to {good})", err)

    def test_help_hides_the_ignored_options(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            A.parse_args(["--help"])
        self.assertEqual(cm.exception.code, 0)
        for shown in ("--json", "--facts", "--contract", "--macro", "--no-market", "--fcf-base"):
            self.assertIn(shown, out.getvalue())
        for hidden in ("--iv", "--no-insider"):
            self.assertNotIn(hidden, out.getvalue())

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "f.json"
            code, out, err = run_main(A.main, ["QUAL", "--json", str(path)], failing_client(InvalidKey("rejected")))
            self.assertEqual((code, out, path.exists()), (2, "", False))
            self.assertIn("API key problem: rejected", err)
            code, out, err = run_main(A.main, ["QUAL", "--json", str(path)], failing_client(FMPError("HTTP 500")))
            self.assertEqual((code, out, path.exists()), (1, "", False))
            self.assertIn("FMP error: HTTP 500", err)
            # a ticker the plan does not cover: a message, and the interpreter exits with 1
            with self.assertRaises(SystemExit) as cm:
                run_main(A.main, ["NOPE", "--peers", "none", "--json", str(path)])
            self.assertIn("does not cover NOPE", str(cm.exception.code))
            self.assertFalse(path.exists())
            # so does a --peers entry that is not a US ticker
            with self.assertRaises(SystemExit) as cm:
                run_main(A.main, ["QUAL", "--peers", "SHOP.TO", "--json", str(path)])
            self.assertIsInstance(cm.exception.code, str)
            self.assertIn("--peers: 'SHOP.TO' looks like a non-US listing", cm.exception.code)
            self.assertFalse(path.exists())
            # a peer without data only gets a row that says so
            code, out, err = run_main(A.main, ["QUAL", "--peers", "NOPE", "--json", str(path)])
            self.assertEqual(code, 0)
            self.assertIn("\n| NOPE | no data (plan restriction or unknown ticker) |", out)
            self.assertTrue(path.exists())
        # usage errors exit with 2
        for argv in (["QUAL", "--macro", "--no-market"], ["QUAL", "--nope"], ["QUAL", "--years", "five"]):
            with self.subTest(argv=argv), self.assertRaises(SystemExit) as cm:
                run_main(A.main, argv)
            self.assertEqual(cm.exception.code, 2)


class Calls(unittest.TestCase):
    def test_the_default_analysis_makes_14_calls(self):
        client, log = recording_client()
        with mock.patch.object(A, "FMPClient", client):
            r = A.analyze(A.parse_args(["QUAL", "--peers", "none"]))
        self.assertEqual((len(log), r["meta"]["network_calls"]), (14, 14))
        self.assertEqual(dict(collections.Counter(e for e, _ in log)), DEFAULT_CALLS)
        self.assertEqual([p["symbol"] for e, p in log if e == "historical-price-eod/light"], ["QUAL"])  # no SPY
        points = r["market"]["rates"]["points"]
        self.assertEqual([k for k, v in points.items() if v], ["now", "1M ago"])
        self.assertNotIn("returns", r["market"]["sector"])

    def test_macro_still_fetches_the_returns_and_the_full_treasury_curve(self):
        client, log = recording_client()
        with mock.patch.object(A, "FMPClient", client), mock.patch.object(A.R, "render", return_value=REPORT) as rd:
            doc, report = A.run(A.parse_args(["QUAL", "--peers", "none", "--macro"]))
        self.assertEqual(dict(collections.Counter(e for e, _ in log)), MACRO_CALLS)
        self.assertEqual(len(log), 25)
        self.assertEqual(sorted(p["symbol"] for e, p in log if e == "historical-price-eod/light"), ["QUAL", "SPY"])
        self.assertEqual(report, REPORT)
        (f,), kw = rd.call_args
        self.assertEqual((f, kw["calls"]), (doc, (25, 0)))
        md = kw["macro_md"]
        self.assertTrue(md.startswith("### Treasury yields"))
        for part in ("1M ago (", "3M ago (", "1Y ago (", "### Policy rate", "### Price performance",
                     "Price performance to ", "| QUAL |", "| Industry (equal-weight) |", "| S&P 500 (SPY) |"):
            self.assertIn(part, md)
        self.assertNotIn("n/a", md.split("### Price performance")[1])   # every return was computed

    def test_run_reports_on_the_document(self):
        with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient), \
                mock.patch.object(A.R, "render", return_value=REPORT) as rd:
            doc, report = A.run(A.parse_args(["QUAL", "--peers", "none"]))
        self.assertEqual(report, REPORT)
        rd.assert_called_once_with(doc, macro_md=None, calls=(14, 0))
        self.assertEqual(validate(doc), [])


class Client(unittest.TestCase):
    def test_only_the_official_api_with_verified_https(self):
        """The old third-party proxy settings are not read: every request goes to FMP's official API with the key in
        its apikey header, and urlopen gets no SSL context of its own, so the certificate is always verified."""
        seen = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'[{"symbol": "AAPL"}]'

        def urlopen(req, timeout=None, **kw):
            seen.append((req.full_url, req.get_header("Apikey"), kw))
            return Response()

        old = {"FMP_API_KEY": "test-key", "FMP_BASE_URL": "https://1.2.3.4", "FMP_TLS_VERIFY": "0",
               "FMP_PATH_PREFIX": "", "FMP_AUTH_STYLE": "query"}
        with mock.patch.dict(os.environ, old), mock.patch("urllib.request.urlopen", urlopen), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            client = FMPClient(use_cache=False)
            self.assertEqual(client.profile("AAPL"), {"symbol": "AAPL"})
        self.assertEqual(seen, [("https://financialmodelingprep.com/stable/profile?symbol=AAPL", "test-key", {})])
        self.assertEqual((client.describe()["route"], err.getvalue()), ("official FMP API", ""))


class Converter(unittest.TestCase):
    """python scripts/facts.py SAVED.json [-o OUT.json]"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = SAVED["QTRS"]
        (self.dir / "saved.json").write_text(json.dumps(self.saved["full"], indent=2), encoding="utf-8")
        self.want = dict(self.saved["facts"], generated_at=self.saved["full"]["generated_at"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_saved_v1_result_converts(self):
        out = self.dir / "out.json"
        code, stdout, err = run_main(F.main, [str(self.dir / "saved.json"), "-o", str(out)])
        self.assertEqual((code, stdout), (0, ""))
        self.assertEqual(err.strip(), f"({F.FACTS} written to {out})")
        self.assertEqual(text(json.loads(out.read_text(encoding="utf-8"))), text(self.want))
        code, stdout, err = run_main(F.main, [str(self.dir / "saved.json")])
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(text(json.loads(stdout)), text(self.want))
        self.assertEqual(stdout, F.dumps(json.loads(stdout)) + "\n")

    def test_an_fa_2_file_is_written_back_as_it_is(self):
        with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient):
            doc, _ = A.run(A.parse_args(["UTIL", "--peers", "none"]))
        src, out = self.dir / "doc.json", self.dir / "out.json"
        src.write_text(F.dumps(doc), encoding="utf-8")
        self.assertEqual(run_main(F.main, [str(src), "-o", str(out)])[0], 0)
        self.assertEqual(out.read_text(encoding="utf-8"), src.read_text(encoding="utf-8"))

    def test_an_output_that_cannot_be_written(self):
        out = self.dir / "missing" / "out.json"
        code, stdout, err = run_main(F.main, [str(self.dir / "saved.json"), "-o", str(out)])
        self.assertEqual((code, stdout), (1, ""))
        self.assertTrue(err.startswith(f"Cannot write {out}: "), err)
        self.assertNotIn("Traceback", err)

    def test_unreadable_or_not_a_result(self):
        files = {"broken.json": "{not json", "list.json": "[1, 2]", "empty.json": "{}",
                 "contract.json": json.dumps({"contract": "fa-1.1", "ticker": "QUAL", "score": {"total": 1}})}
        for name, content in files.items():
            (self.dir / name).write_text(content, encoding="utf-8")
        for name in list(files) + ["missing.json"]:
            code, out, err = run_main(F.main, [str(self.dir / name), "-o", str(self.dir / "out.json")])
            self.assertEqual((code, out), (1, ""), name)
            self.assertIn(f"Cannot convert {self.dir / name} to {F.FACTS}", err, name)
            self.assertFalse((self.dir / "out.json").exists(), name)


class Page(unittest.TestCase):
    """ui/server.py answers /api/analyze with the document and the report the command line writes, and beside them
    what only the page shows: the price chart's data (analyze.run_page()) and the price ranges (price_range.py)."""

    def test_the_page_gets_what_the_command_line_writes(self):
        import price_range as PR
        import server
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(A.R, "render", return_value=REPORT), \
                mock.patch.dict("os.environ", {"FMP_API_KEY": "offline-test"}):
            path = Path(tmp) / "doc.json"
            self.assertEqual(run_main(A.main, ["QUAL", "--peers", "none", "--json", str(path)])[0], 0)
            with mock.patch.object(server.A, "FMPClient", fake_fmp.FakeClient):
                code, body = server.run_analysis({"symbol": "qual", "peers": "none", "iv": "not a number"})
            cli_doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 200)
        self.assertEqual(set(body), {"result", "report", "log", "prices", "candles", "candles_note", "change_pct",
                                     "price_range"})
        self.assertEqual(body["report"], REPORT)
        self.assertEqual(without_time(body["result"]), without_time(cli_doc))
        self.assertEqual(validate(body["result"]), [])
        json.dumps(body, allow_nan=False)
        # the chart: the last year's daily closes, and the same days as open/high/low/close/volume bars
        doc, prices, candles = body["result"], body["prices"], body["candles"]
        year_ago = (dt.date.fromisoformat(doc["as_of"]) - dt.timedelta(days=366)).isoformat()
        self.assertGreater(len(prices), 240)
        self.assertEqual(prices, sorted(prices))
        self.assertTrue(all(d >= year_ago for d, _ in prices))
        self.assertEqual([b[0] for b in candles], [d for d, _ in prices])
        self.assertEqual([b[4] for b in candles], [p for _, p in prices])
        for d, o, h, lo, c, v in candles:
            self.assertTrue(lo <= min(o, c) <= max(o, c) <= h and v > 0, d)
        self.assertEqual((prices[-1][1], body["candles_note"]), (doc["price"]["value"], None))
        self.assertIsInstance(body["change_pct"], float)
        # the price ranges: price_range.build() on that document and those closes
        self.assertEqual(body["price_range"], json.loads(json.dumps(PR.build(doc, prices))))
        self.assertEqual({r["kind"] for r in body["price_range"]["rows"]},
                         {"week52", "fwd_pe", "fwd_ev", "dcf", "volatility"})

    def test_the_page_still_answers_when_the_bars_or_the_ranges_fail(self):
        import server

        class NoBars(fake_fmp.FakeClient):
            def _fetch(self, endpoint, params):
                if endpoint == "historical-price-eod/full":
                    raise FMPError("historical-price-eod/full: HTTP 500")
                return super()._fetch(endpoint, params)

        with mock.patch.object(server.A, "FMPClient", NoBars), mock.patch.object(A.R, "render", return_value=REPORT):
            code, body = server.run_analysis({"symbol": "qual", "peers": "none"})
        self.assertEqual(code, 200)
        self.assertEqual((body["candles"], body["candles_note"]), ([], "historical-price-eod/full: HTTP 500"))
        self.assertGreater(len(body["prices"]), 240)                   # the chart draws the closes instead
        self.assertEqual(body["result"]["data_quality"]["errors"], [])  # nothing the document reports on

        with mock.patch.object(server.A, "FMPClient", fake_fmp.FakeClient), \
                mock.patch.object(A.R, "render", return_value=REPORT), \
                mock.patch.object(server.PR, "build", side_effect=ZeroDivisionError("a bug")):
            code, body = server.run_analysis({"symbol": "qual", "peers": "none"})
        self.assertEqual(code, 200)
        self.assertNotIn("price_range", body)
        self.assertIn("ZeroDivisionError: a bug", body["log"])

    def test_only_the_page_asks_for_the_daily_bars(self):
        """The command line makes the calls it always made; the page makes one more, for the chart's bars."""
        logs = {}
        for name, run in (("cli", A.run), ("page", A.run_page)):
            client, logs[name] = recording_client()
            with mock.patch.object(A, "FMPClient", client), mock.patch.object(A.R, "render", return_value=REPORT):
                out = run(A.parse_args(["QUAL", "--peers", "none"]))
            self.assertEqual(len(out), 2 if name == "cli" else 3)
            if name == "page":
                self.assertEqual(set(out[2]), {"prices", "candles", "candles_note", "change_pct"})
        self.assertEqual(dict(collections.Counter(e for e, _ in logs["cli"])), DEFAULT_CALLS)
        self.assertEqual(dict(collections.Counter(e for e, _ in logs["page"])),
                         dict(DEFAULT_CALLS, **{"historical-price-eod/full": 1}))
        (params,) = [p for e, p in logs["page"] if e == "historical-price-eod/full"]
        self.assertEqual(params["symbol"], "QUAL")

    def test_the_quote_updates_the_last_bar_but_never_decides_alone(self):
        """apply_quote(): the quote's price is today's close and today's bar's close, widening its high and low;
        a bar for the quote's day is added once that session has opened. Only the closes decide whether the
        quote is used, so the page's bars never change the document."""
        ts = dt.datetime(2026, 11, 6, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5))).timestamp()  # a Friday
        quote = {"price": 105.0, "changePercentage": 1.5, "timestamp": ts, "open": 99.0, "dayHigh": 104.0,
                 "dayLow": 98.0, "volume": 1e6}
        profile = {"price": 100.0, "marketCap": 1e9}
        series = [("2026-11-05", 100.0), ("2026-11-06", 101.0)]
        bars = [("2026-11-05", 99.0, 101.0, 98.5, 100.0, 5e5), ("2026-11-06", 100.0, 102.0, 99.5, 101.0, 2e5)]
        p, s2, b2, when = A.apply_quote(profile, quote, series, bars)
        self.assertEqual((p["price"], p["changePercentage"], when), (105.0, 1.5, "2026-11-06 15:00"))
        self.assertEqual(s2[-1], ("2026-11-06", 105.0))
        self.assertEqual(b2[-1], ("2026-11-06", 100.0, 105.0, 98.0, 105.0, 1e6))  # the quote's day range widens it
        self.assertEqual(b2[0], bars[0])
        # the quote's session has opened and no bar has its day yet: one is added from the quote
        p, s2, b2, _ = A.apply_quote(profile, quote, series[:1], bars[:1])
        self.assertEqual((s2[-1], b2[-1]), (("2026-11-06", 105.0), ("2026-11-06", 99.0, 105.0, 98.0, 105.0, 1e6)))
        # bars newer than the quote are left alone, and the quote is still used for the price
        newer = bars + [("2026-11-09", 101.0, 103.0, 100.0, 102.0, 3e5)]
        p, s2, b2, when = A.apply_quote(profile, quote, series, newer)
        self.assertEqual((p["price"], b2, when), (105.0, newer, "2026-11-06 15:00"))
        # closes newer than the quote: the profile's price stays, and nothing changes
        later = series + [("2026-11-09", 102.0)]
        self.assertEqual(A.apply_quote(profile, quote, later, bars), (profile, later, bars, None))
        # the command line passes no bars
        self.assertEqual(A.apply_quote(profile, quote, series)[2], [])

    def test_values_the_option_parser_would_refuse_get_an_answer(self):
        """Values go to analyze.py attached (--growth=-5e-05), so one starting with "-" is not read as an option;
        anything the parser still refuses is a 400 answer, not a dropped connection (SystemExit is no Exception)."""
        import server
        with mock.patch.object(server.A, "FMPClient", fake_fmp.FakeClient), \
                mock.patch.object(A.R, "render", return_value=REPORT):
            self.assertEqual(server.run_analysis({"symbol": "qual", "peers": "none", "growth": "-0.005"})[0], 200)
            code, body = server.run_analysis({"symbol": "qual", "peers": "-x"})
            self.assertEqual(code, 404)
            self.assertIn("--peers", body["error"])
            for bad in ("inf", "-inf", "nan", "abc"):
                self.assertEqual(server.run_analysis({"symbol": "qual", "growth": bad}),
                                 (400, {"error": "growth must be a number (percent)."}), bad)

            def refuse(argv):
                print("usage: analyze.py ...\nanalyze.py: error: argument --x: invalid", file=sys.stderr)
                raise SystemExit(2)
            with mock.patch.object(server.A, "parse_args", side_effect=refuse):
                self.assertEqual(server.run_analysis({"symbol": "qual"}),
                                 (400, {"error": "analyze.py: error: argument --x: invalid"}))

    def test_overlapping_requests_leave_stderr_alone(self):
        """sys.stderr is process-wide and the server answers each request on its own thread: a request that parses
        its options while another analysis ends must not leave sys.stderr on either request's buffer."""
        import threading
        import server
        saved = sys.stderr
        first_in_run, second_parsing, first_done = threading.Event(), threading.Event(), threading.Event()
        real_parse, real_run = server.A.parse_args, server.A.run_page

        def parse_args(argv):
            if threading.current_thread().name == "second":
                second_parsing.set()
                first_done.wait(0.5)        # the first analysis ends while this request parses
            return real_parse(argv)

        def run(args):
            if threading.current_thread().name == "first":
                first_in_run.set()
                second_parsing.wait(0.5)
            return real_run(args)

        def first():
            server.run_analysis({"symbol": "qual", "peers": "none"})
            first_done.set()

        with mock.patch.object(server.A, "FMPClient", fake_fmp.FakeClient), \
                mock.patch.object(A.R, "render", return_value=REPORT), \
                mock.patch.object(server.A, "parse_args", parse_args), mock.patch.object(server.A, "run_page", run):
            t1 = threading.Thread(target=first, name="first")
            t1.start()
            first_in_run.wait(1)
            t2 = threading.Thread(target=server.run_analysis, args=({"symbol": "qual", "peers": "none"},),
                                  name="second")
            t2.start()
            t1.join()
            t2.join()
        try:
            self.assertIs(sys.stderr, saved)
        finally:
            sys.stderr = saved


if __name__ == "__main__":
    unittest.main()
