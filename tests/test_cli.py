"""
Offline tests of the command line (scripts/analyze.py and the scripts/facts.py converter) and of the local page's
/api/analyze answer (ui/server.py). No API key needed:

    python -m unittest discover -s tests

v2.0 writes one document, fa-2.0: --json, --facts and the deprecated --contract all write it, stdout is the
report alone (facts_report.py, tested in test_facts_report.py) and notes go to stderr. Without peers and
--macro an analysis makes 14 API calls; --macro also fetches the returns and the Treasury curve 3M and 1Y ago
for its section.
"""
from __future__ import annotations

import collections
import contextlib
import io
import json
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
from fmp_client import FMPError, InvalidKey  # noqa: E402
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
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            A.parse_args(["QUAL", "--macro", "--no-market"])
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
        rd.assert_called_once_with(doc, macro_md=None, calls=(14, 0), tls_verify=True)
        self.assertEqual(validate(doc), [])


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
    """ui/server.py answers /api/analyze with the document and the report of analyze.run()."""

    def test_the_page_gets_what_the_command_line_writes(self):
        import server
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(A.R, "render", return_value=REPORT), \
                mock.patch.dict("os.environ", {"FMP_API_KEY": "offline-test"}):
            path = Path(tmp) / "doc.json"
            self.assertEqual(run_main(A.main, ["QUAL", "--peers", "none", "--json", str(path)])[0], 0)
            with mock.patch.object(server.A, "FMPClient", fake_fmp.FakeClient):
                code, body = server.run_analysis({"symbol": "qual", "peers": "none", "iv": "not a number"})
            cli_doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(code, 200)
        self.assertEqual(set(body), {"result", "report", "log"})       # no candles or prices
        self.assertEqual(body["report"], REPORT)
        self.assertEqual(without_time(body["result"]), without_time(cli_doc))
        self.assertEqual(validate(body["result"]), [])
        json.dumps(body, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
