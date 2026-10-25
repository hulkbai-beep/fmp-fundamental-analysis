"""
Ticker normalisation (scripts/symbols.py): what people type -> the symbol FMP's stable API expects.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ui"))

from symbols import normalize_symbol  # noqa: E402

ACCEPTED = [("AAPL", "AAPL"), ("aapl", "AAPL"), ("  msft ", "MSFT"), ("$nvda", "NVDA"), ("$ TSLA", "TSLA"),
            ("BRK.B", "BRK-B"), ("brk.b", "BRK-B"), ("BRK-B", "BRK-B"), ("BRK/B", "BRK-B"), ("brk b", "BRK-B"),
            ("BRK  B", "BRK-B"), ("$BRK.B", "BRK-B"), ("BF.B", "BF-B"), ("hei.a", "HEI-A"), ("LEN.B", "LEN-B")]
REFUSED = [("", "no ticker given"), ("   ", "no ticker given"), (None, "no ticker given"), ("$", "no ticker given"),
           ("SHOP.TO", "non-US listing"), ("0700.HK", "non-US listing"), ("SAP.DE", "non-US listing"),
           ("VOD.L", "London listing"), ("7203.T", "non-US"), ("AAPL;rm", "not a US ticker"),
           ("TOOLONGSYMBOL", "not a US ticker"), ("A B C", "not a US ticker"), ("<script>", "not a US ticker"),
           ("12345", "not a US ticker"), ("BRK.B.C", "not a US ticker")]


class Normalise(unittest.TestCase):
    def test_accepted_forms(self):
        for typed, symbol in ACCEPTED:
            self.assertEqual(normalize_symbol(typed), symbol, typed)
            self.assertEqual(normalize_symbol(symbol), symbol, symbol)   # idempotent

    def test_refused_forms(self):
        for typed, message in REFUSED:
            with self.assertRaisesRegex(ValueError, message, msg=repr(typed)):
                normalize_symbol(typed)


class EntryPoints(unittest.TestCase):
    """Every way in normalises the same way: analyze(), --peers, score_batch, the UI."""

    @classmethod
    def setUpClass(cls):
        import analyze as A
        import fake_fmp
        cls.A, cls.fake = A, fake_fmp
        cls.patch = mock.patch.object(A, "FMPClient", fake_fmp.FakeClient)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def test_analyze_takes_typed_forms_and_refuses_foreign_listings(self):
        r = self.A.analyze(self.A.parse_args(["$qual", "--peers", "none", "--no-market"]))
        self.assertEqual(r["symbol"], "QUAL")
        with self.assertRaisesRegex(SystemExit, "non-US listing"):
            self.A.analyze(self.A.parse_args(["SHOP.TO", "--peers", "none"]))

    def test_peer_override_is_normalised(self):
        self.assertEqual(self.A.peer_symbols(None, "QUAL", "brk.b, $trap ,QUAL,BRK-B", 5), ["BRK-B", "TRAP"])
        with self.assertRaisesRegex(SystemExit, "--peers"):
            self.A.peer_symbols(None, "QUAL", "SHOP.TO", 5)

    def test_batch_reads_typed_forms(self):
        import types
        import score_batch as B
        args = types.SimpleNamespace(symbols=["brk.b", "$qual", "QUAL", "shop.to"], file=None)
        self.assertEqual(B.read_symbols(args), ["BRK-B", "QUAL", "SHOP.TO"])   # the foreign one fails in analyze()

    def test_ui_normalises_and_refuses(self):
        import server
        with mock.patch.object(server.A, "FMPClient", self.fake.FakeClient), \
                mock.patch.dict("os.environ", {"FMP_API_KEY": "offline-test"}):
            code, body = server.run_analysis({"symbol": "$qual", "peers": "none"})
            self.assertEqual((code, body["result"]["symbol"]), (200, "QUAL"))
            code, body = server.run_analysis({"symbol": "SHOP.TO"})
            self.assertEqual(code, 400)
            self.assertIn("non-US listing", body["error"])


if __name__ == "__main__":
    unittest.main()
