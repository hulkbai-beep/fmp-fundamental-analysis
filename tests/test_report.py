"""
Offline tests for scripts/report.py, the facts report of v2.0. No API key needed:

    python -m unittest discover -s tests

The report is rendered from the fa-2.0 documents of the synthetic companies in 19 cases (the 8 companies and the
options that change the document). The tests check the sections and their order; that sections 1-4 and the peer
table are the report of 8c5ceed byte for byte (tests/data holds those tables for 4 cases as that report printed
them); that no judgement word appears; that ui/i18n.js has a Chinese translation for every text; that the macro
section and the API-call line appear only when given; that documents converted from results saved by v1.x render;
and that the rarer status codes of fa-2.0 render in words.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "data"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import facts as F  # noqa: E402
import fake_fmp  # noqa: E402


def load_report():
    """scripts/report.py loaded from its file, as the decision engine loads it to render the runs it converted."""
    spec = importlib.util.spec_from_file_location("fa_report_under_test", ROOT / "scripts" / "report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load_report()

CASES = {
    "QUAL": ["QUAL", "--peers", "none"],
    "TRAP": ["TRAP", "--peers", "none"],
    "BANK": ["BANK", "--peers", "none"],
    "EXCH": ["EXCH", "--peers", "none"],
    "UTIL": ["UTIL", "--peers", "none"],
    "QTRS": ["QTRS", "--peers", "none"],
    "ADJE": ["ADJE", "--peers", "none"],
    "REIT": ["REIT", "--peers", "none"],
    "QTRS_no-ttm": ["QTRS", "--peers", "none", "--no-ttm"],
    "QUAL_no-market": ["QUAL", "--peers", "none", "--no-market"],
    "BANK_no-market": ["BANK", "--peers", "none", "--no-market"],
    "QUAL_macro": ["QUAL", "--peers", "none", "--macro"],
    "QUAL_user-dcf": ["QUAL", "--peers", "none", "--discount", "0.1", "--growth", "0.06", "--terminal", "0.03"],
    "QTRS_avg3": ["QTRS", "--peers", "none", "--fcf-base", "avg3"],
    "UTIL_avg3": ["UTIL", "--peers", "none", "--fcf-base", "avg3"],
    "TRAP_avg3": ["TRAP", "--peers", "none", "--fcf-base", "avg3"],
    "QUAL_peers": ["QUAL", "--peers", "TRAP,UTIL,NOPE"],
    "QUAL_years3": ["QUAL", "--peers", "none", "--years", "3"],
    "REIT_years3": ["REIT", "--peers", "none", "--years", "3"],
}
DOCS, REPORTS = {}, {}

SECTIONS = ["1. Growth", "2. Profitability & returns", "3. Balance sheet & liquidity",
            "4. Cash flow quality & capital allocation", "5. Valuation", "6. Forward multiples",
            "7. Industry & sector P/E", "8. Quality scores", "9. DCF", "10. Analyst consensus"]
# Words and phrases that judge or advise; none may appear outside the texts FMP provides.
JUDGEMENT_WORDS = ("upside", "downside", "strong", "stronger", "weak", "weaker", "cheap", "cheaper", "expensive",
                   "attractive", "unattractive", "undervalued", "overvalued", "bargain", "buy", "sell", "target",
                   "targets", "bullish", "bearish", "recommend", "recommended", "recommendation", "verdict", "rating",
                   "signal", "good", "bad", "healthy")
JUDGEMENT_PHRASES = ("lean on", "focus on", "fair value", "intrinsic value", "margin of safety")
# Parts of the report before v2.0 that v2.0 removed.
REMOVED = ("Price range", "Base vs price", "At today's", "Volatility", "volatility", "Insider", "Automated flags",
           "Fundamental score", "Price target", "price target", "52-week", "Margin of safety", "PEG")


def setUpModule():
    import analyze as A
    with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient):
        for name, argv in CASES.items():
            DOCS[name] = F.build(json.loads(json.dumps(A.analyze(A.parse_args(argv)), default=str)))
    REPORTS.update({name: R.render(doc) for name, doc in DOCS.items()})


def headings(text):
    return re.findall(r"^## (.+)$", text, re.M)


def section(text, title):
    """The lines of one '## ' section, without its heading and the blank lines that end it."""
    out = None
    for line in text.splitlines():
        if line.startswith("## "):
            if out is not None:
                break
            if line == f"## {title}":
                out = []
        elif out is not None:
            out.append(line)
    if out is None:
        raise AssertionError(f"no section {title!r}")
    while out and not out[-1]:
        out.pop()
    return out


def tables_by_section(text):
    """The table lines of each numbered '## N.' section, by N."""
    out, number = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            m = re.match(r"## (\d+)\.", line)
            number = int(m.group(1)) if m else None
        elif number is not None and line.startswith("|"):
            out.setdefault(number, []).append(line)
    return out


def old_tables(name):
    """The tables of sections 1-4 the report of 8c5ceed printed for a case, with its fiscal years moved to the
    synthetic data of today (fake_fmp's last fiscal year is the year before the current one; the files were
    written in 2026, the figures do not depend on the date)."""
    text = (DATA / f"old_report_{name}_sections_1-4.md").read_text(encoding="utf-8")
    text = re.sub(r"FY(\d{4})", lambda m: f"FY{int(m.group(1)) + fake_fmp.LAST_FY - 2025}", text)
    return tables_by_section(text)


def fmp_texts(doc):
    """Texts the report repeats from FMP (names, endpoint and error messages, the data route)."""
    c, dq = doc.get("company") or {}, doc.get("data_quality") or {}
    vg = (doc.get("valuation") or {}).get("vs_group") or {}
    texts = [c.get(k) for k in ("name", "sector", "industry", "exchange")]
    texts += [(vg.get(k) or {}).get("name") for k in ("industry", "sector")] + [vg.get("exchange")]
    texts += [p.get("name") for p in doc.get("peers") or []]
    texts += list(dq.get("restricted") or []) + list(dq.get("errors") or []) + [dq.get("route")]
    return sorted({t for t in texts if t}, key=len, reverse=True)


def judgements(text, doc):
    """The judgement words and phrases in a report of doc, FMP's own texts excepted."""
    for t in fmp_texts(doc):
        text = text.replace(t, " ")
    low = text.lower()
    return [w for w in JUDGEMENT_WORDS + JUDGEMENT_PHRASES if re.search(rf"\b{re.escape(w)}\b", low)]


def fy(offset=0):
    """A fiscal-year label of the synthetic data: offset 0 is the last reported year."""
    return f"FY{fake_fmp.LAST_FY + offset}"


def js_string(s):
    """The text of a JavaScript string literal's body (the keys in i18n.js use JSON's escapes)."""
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


# The exact entries and the regex rules of zh() (ui/i18n.js), read as text: the tests need no JavaScript engine.
I18N = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
ZH_KEYS = {js_string(k) for k in re.findall(r'"((?:[^"\\]|\\.)+)":\s*"', I18N)}
ZH_RULES = [re.compile(r) for r in re.findall(r"\[/((?:[^/\\\n]|\\.)+)/[gimsuy]*,", I18N)]


def pieces(text):
    """The texts the page passes to zh() one by one (ui/index.html md()): headings without their number, list
    items, other lines and table cells. The '# TICKER - Name' line is not one of them."""
    for line in text.splitlines():
        if line.startswith("|"):
            if not re.fullmatch(r"\|[\s|:-]+\|", line):
                yield from (c.strip() for c in line.strip("|").split("|"))
        elif line.startswith("## "):
            yield re.sub(r"^\d+\.\s+", "", line[3:])
        elif line.startswith("### "):
            yield line[4:]
        elif line.startswith("- "):
            yield line[2:]
        elif line.strip() and not line.startswith("# "):
            yield line.strip()


def untranslated(text, doc):
    """The pieces of a report that ui/i18n.js has neither an exact entry nor a rule for (statically: a whole-text
    rule that matches, or fragment rules that leave no English word), FMP's own texts excepted."""
    out = []
    for p in pieces(text):
        if p in ZH_KEYS or any(r.pattern.startswith("^") and r.search(p) for r in ZH_RULES):
            continue
        rest = p
        for r in ZH_RULES:
            rest = r.sub(" ", rest)
        for t in fmp_texts(doc):
            rest = rest.replace(t, " ")
        if re.search(r"[a-z]{3}", rest):
            out.append(p)
    return out


class Report(unittest.TestCase):
    def test_standard_library_only(self):
        """The engine loads report.py by path, without the skill's folders on sys.path."""
        tree = ast.parse((ROOT / "scripts" / "report.py").read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        self.assertTrue(names)
        self.assertEqual(sorted(names - set(sys.stdlib_module_names)), [])
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level])

    def test_every_case_renders_its_sections_in_order(self):
        self.assertEqual(len(REPORTS), 19)
        for name, text in REPORTS.items():
            with self.subTest(name):
                doc, lines = DOCS[name], text.splitlines()
                self.assertEqual(lines[0], f"# {doc['ticker']} - {doc['company']['name']}")
                self.assertRegex(lines[1], r"^.+ / .+ \| .+ \| Price [\d,.]+ USD \| Market cap \S+ \| Beta \S+$")
                self.assertRegex(text, r"\nData basis: annual FY\d{4}-FY\d{4} in USD( \+ TTM to \d{4}-\d\d-\d\d| \(TTM "
                                       r"unavailable: using last fiscal year\))\. Valuation uses (FY\d{4}|TTM) figures\. "
                                       r"As of \d{4}-\d\d-\d\d\.\n")
                peers = ["11. Peer comparison"] if name == "QUAL_peers" else []
                self.assertEqual(headings(text), SECTIONS + peers + ["Data notes"])
                for title in headings(text):
                    self.assertTrue([x for x in section(text, title) if x.strip()], title)
                self.assertEqual(lines[-1], "- Source: Financial Modeling Prep. Computed figures are approximations; "
                                            "verify against filings before acting.")
                self.assertNotIn("None", text)
                self.assertNotIn("\n\n\n", text)

    def test_company_kind_note(self):
        notes = {}
        for name, text in REPORTS.items():
            c = DOCS[name]["company"]
            line = [x for x in text.splitlines() if x.startswith("**Company type:**")]
            with self.subTest(name):
                if c["kind"] == "general":
                    self.assertEqual(line, [])
                    continue
                self.assertEqual(len(line), 1)
                for k in c["not_meaningful"]:
                    self.assertIn(R.MEASURES[k], line[0].split("Not meaningful for this type of company:")[1])
                notes[c["kind"]] = line[0]
        self.assertEqual(sorted(notes), ["fee_financial", "financial", "reit", "utility"])
        self.assertEqual(notes["financial"], "**Company type:** Financial company (bank or insurer). Not meaningful for "
                                             "this type of company: gross margin, EV/EBITDA, EV / sales, free cash "
                                             "flow, DCF, Altman Z.")

    def test_sections_1_to_4_as_before(self):
        for name in ("QTRS", "BANK", "TRAP"):
            with self.subTest(name):
                new = {k: v for k, v in tables_by_section(REPORTS[name]).items() if k <= 4}
                self.assertEqual(new, old_tables(name))
        self.assertIn("| TTM |", old_tables("QTRS")[1][0])
        self.assertIn(f"{fy()} | TTM | CAGR |", tables_by_section(REPORTS["QTRS"])[1][0])
        self.assertEqual(section(REPORTS["QTRS"], "1. Growth")[0],
                         f"Last column: compound annual growth (CAGR) over 4 years, {fy(-4)} to {fy()}.")

    def test_peer_table_as_before(self):
        expected = (DATA / "old_report_QUAL_peers_peer_table.md").read_text(encoding="utf-8").splitlines()
        self.assertEqual(tables_by_section(REPORTS["QUAL_peers"])[11], expected)
        self.assertEqual(section(REPORTS["QUAL_peers"], "11. Peer comparison")[0],
                         "Each company's last fiscal year, same method for all (* = this company).")

    def test_no_judgement_words(self):
        for name, text in REPORTS.items():
            with self.subTest(name):
                self.assertEqual(judgements(text, DOCS[name]), [])
                self.assertEqual([t for t in REMOVED if t in text], [])

    def test_every_text_has_a_chinese_translation(self):
        for name, text in REPORTS.items():
            with self.subTest(name):
                self.assertEqual(untranslated(text, DOCS[name]), [])
        doc = DOCS["QUAL"]
        self.assertEqual(untranslated(REPORTS["QUAL"] + "\nA sentence nobody translated.", doc),
                         ["A sentence nobody translated."])

    def test_the_word_check_finds_planted_words(self):
        doc = copy.deepcopy(DOCS["QUAL"])
        doc["company"]["name"] = "Strong Buy Target Corp"
        text = R.render(doc)
        self.assertIn("# QUAL - Strong Buy Target Corp", text)
        self.assertEqual(judgements(text, doc), [])
        self.assertEqual(judgements(text + "\nThe shares look cheap; lean on the base case.", doc),
                         ["cheap", "lean on"])

    def test_no_prices_from_multiples(self):
        """The forward distributions stay multiples, and the DCF is never set against the price."""
        for name, text in REPORTS.items():
            with self.subTest(name):
                fwd = "\n".join(section(text, "6. Forward multiples"))
                self.assertNotIn("USD", fwd)
                self.assertNotIn("per share", fwd)
                self.assertNotRegex(fwd, r"(?i)\bprice (of|at|level)")
                for line in section(text, "9. DCF"):
                    if "price" in line.lower():
                        self.assertTrue(line.startswith("**Reverse DCF:** today's price implies"), line)

    def test_macro_and_calls_only_when_given(self):
        macro = "### Treasury yields\n| Tenor | Now |\n|---|---|\n| 10Y | 4.20% |\n"
        for name, number in (("QUAL", 11), ("QUAL_peers", 12)):
            with self.subTest(name):
                plain = REPORTS[name]
                self.assertNotIn("Rates & macro backdrop", plain)
                self.assertNotIn("API calls", plain)
                self.assertEqual(R.render(DOCS[name], macro_md="", calls=None), plain)
                text = R.render(DOCS[name], macro_md=macro, calls=(21, 3))
                self.assertEqual(headings(text)[-2:], [f"{number}. Rates & macro backdrop", "Data notes"])
                block = f"\n## {number}. Rates & macro backdrop\n{macro.strip()}\n"
                self.assertIn(block + "\n## Data notes\n", text)
                calls = "- API calls: 21 network, 3 from cache.\n"
                self.assertIn(calls, text)
                self.assertEqual(text.replace(block, "", 1).replace(calls, "", 1), plain)
                self.assertEqual(R.render(DOCS[name], calls=(0, 9)).count("- API calls: 0 network, 9 from cache."), 1)

    def test_documents_converted_from_old_results(self):
        full = json.loads((DATA / "old_full_v1.1_QUAL.json").read_text(encoding="utf-8"))
        older = copy.deepcopy(full)   # as v1.0 saved it: no generation time, market data, peers, TTM or quote time
        for k in ("generated_at", "market", "peers", "ttm", "price_time"):
            older.pop(k)
        older["meta"].pop("connection")
        older["price_range"].pop("trailing_problem")
        for label, r in (("v1.1", full), ("v1.0", older)):
            with self.subTest(label):
                doc = F.build(r)
                text = R.render(doc)
                self.assertTrue(text.startswith("# QUAL - QUAL Test Corp\n"))
                self.assertEqual(headings(text), SECTIONS + ["Data notes"])
                self.assertEqual(judgements(text, doc), [])
                self.assertEqual([t for t in REMOVED if t in text], [])
        self.assertIn("- Data route: official FMP API.", R.render(F.build(full)))
        no_market = R.render(F.build(older))
        self.assertIn("No industry or sector data: market data was skipped (--no-market).", no_market)
        self.assertNotIn("Data route", no_market)

    def test_contract_versions(self):
        doc = copy.deepcopy(DOCS["QUAL"])
        doc["contract"], doc["block_of_a_later_version"] = "fa-2.1", {"x": 1}
        self.assertEqual(R.render(doc), REPORTS["QUAL"])
        for contract in ("fa-1.1", None):
            with self.assertRaises(ValueError):
                R.render(dict(doc, contract=contract))

    def test_options_in_the_text(self):
        """--no-market, the user's DCF inputs, --fcf-base avg3 and a financial company's DCF."""
        for name in ("QUAL_no-market", "BANK_no-market"):
            with self.subTest(name):
                text = REPORTS[name]
                self.assertEqual(section(text, "7. Industry & sector P/E"),
                                 ["No industry or sector data: market data was skipped (--no-market)."])
                self.assertIn("- Treasury, sector and industry data skipped (--no-market).", text)
        self.assertIn("| Discount rate | 9.0% (fixed default; --no-market) |", REPORTS["QUAL_no-market"])
        self.assertIn("| Discount rate | 10.0% (user input) |", REPORTS["QUAL_user-dcf"])
        self.assertIn("| Starting FCF |", REPORTS["QTRS_avg3"])
        self.assertIn("(average FCF of last 3 fiscal years) |", REPORTS["QTRS_avg3"])
        self.assertIn("Financial-sector company: an FCF-based DCF is not meaningful, so none is computed.",
                      REPORTS["BANK"])


def band(status):
    return {"status": status, "now": None, "pctile": None, "p10": None, "p25": None, "median": None, "p75": None,
            "p90": None, "n": None}


def set_bands(f, status):
    f["valuation"]["forward_band"].update(status=status, pe=band(status), ev_ebitda=band(status))


def no_estimates(f):
    f["consensus"]["estimates"] = []
    f["valuation"]["forward"] = {"fy1": None, "pe_fy1": None, "fy2": None, "pe_fy2": None, "pe_ntm": None,
                                 "ev_ebitda_ntm": None, "ntm": None}
    set_bands(f, "no_estimates")


def one_open_year(f):
    f["consensus"]["estimates"] = f["consensus"]["estimates"][:1]
    f["valuation"]["forward"].update(fy2=None, pe_fy2=None, pe_ntm=None, ev_ebitda_ntm=None, ntm=None)
    set_bands(f, "no_estimates")


def history_problem(status):
    def mutate(f):
        set_bands(f, status)
        f["valuation"]["vs_own_history"]["status"] = status
    return mutate


def now_not_positive(f):
    fb = f["valuation"]["forward_band"]
    fb["pe"].update(status="now_not_positive", now=None, pctile=None)
    fb["ev_ebitda"] = band("ebitda_not_positive")
    f["valuation"]["forward"].update(pe_ntm=None, ev_ebitda_ntm=None)
    f["valuation"]["forward"]["ntm"].update(eps=-1.0, ebitda=-5e9)


def ev_not_applicable(f):
    f["valuation"]["forward_band"]["ev_ebitda"] = band("not_applicable")
    f["valuation"]["forward"]["ev_ebitda_ntm"] = None


def extremes(f):
    fb = f["valuation"]["forward_band"]
    fb["pe"]["pctile"], fb["ev_ebitda"]["pctile"] = 0.0, 1.0


def groups(f):
    g = f["valuation"]["vs_group"]
    g["industry"].update({k: None for k in g["industry"] if k != "name"}, status="unavailable")
    g["sector"].update(status="stale", pe=None, pe_pctile=None, premium=None)
    g["exchange"] = None


def negative_group(f):
    f["valuation"]["vs_group"]["industry"].update(status="negative", pe=None, latest_value=-3.2, pe_pctile=None,
                                                  premium=None)


def rates_unavailable(f):
    f["rates"] = None
    f["models"]["dcf"]["inputs"]["discount_rate"].update(value=0.09, method="fixed_default", reason="rates_unavailable",
                                                         rf=None, rf_date=None, beta=None, beta_source=None, erp=None,
                                                         raw=None, clamped=None)


def no_erp(f):
    f["rates"]["equity_risk_premium"] = None
    f["models"]["dcf"]["inputs"]["discount_rate"].update(value=0.09, method="fixed_default", reason="rates_unavailable")


def capm_clamped(f):
    f["models"]["dcf"]["inputs"]["discount_rate"].update(beta_source="default_1", beta=1.0, raw=0.2, value=0.13,
                                                         clamped=True)


def models_missing(f):
    f["models"]["piotroski"] = None
    f["models"]["altman"] = {"status": "unavailable", "fy": None, "z": None, "z_zone": None, "z2": None,
                             "z2_zone": None}


def dcf_status(status):
    def mutate(f):
        f["models"]["dcf"] = {"status": status, "inputs": None, "value_per_share": None, "low": None, "high": None,
                              "terminal_value_share": None, "sensitivity": None}
        f["models"]["reverse_dcf"] = {"status": "no_dcf", "implied_growth_1_5": None, "discount_rate": None}
    return mutate


def reverse_status(status):
    def mutate(f):
        f["models"]["reverse_dcf"].update(status=status, implied_growth_1_5=None)
    return mutate


def negative_dcf(f):
    f["models"]["dcf"].update(value_per_share=-12.5, low=-20.0, high=-5.0)


def default_growth(f):
    f["models"]["dcf"]["inputs"].update(growth_source="default_5pct", growth_1_5=0.05, fcf_start_basis="average_3y")


def consensus_rows(f):
    f["consensus"]["vs_reported"] = {"fy": fy(), "eps": None, "ebitda": None,
                                     "revenue": {"estimate": 1.2e11, "reported": 1.0e11, "gap": 0.2}}
    e = f["consensus"]["estimates"]
    e.insert(0, dict(e[0], fy=str(fake_fmp.LAST_FY), ended=True, analysts=None, pe_on_fy_eps=None))


def notes(f):
    f["data_quality"].update(currency_mismatch={"statements": "JPY", "price": "USD"}, route="third-party proxy at x.org",
                             errors=["price history: timeout", "price history: timeout"])
    f["price"].update(source="quote", time="2026-10-30 16:00")


def profile_price(f):
    f["price"].update(source="profile", time=None)
    f["data_quality"]["route"] = None


def peers_no_data(f):
    f["peers"] = [{"symbol": "NOPE", "status": "no_data", "name": None, "fy": None,
                   **{k: None for k in ("market_cap", "pe", "ev_ebitda", "ps", "p_fcf", "revenue_yoy", "gross_margin",
                                        "operating_margin", "roe", "roic", "net_debt_to_ebitda")}}]


def one_fiscal_year(f):
    for b in ("statements", "metrics"):
        f[b] = {k: v[-1:] for k, v in f[b].items()}
    f["periods"]["fiscal_years"] = f["periods"]["fiscal_years"][-1:]
    f["growth"].update({"years": 0, "from": fy(), "cagr": {k: None for k in f["growth"]["cagr"]}})
    f["valuation"]["vs_own_history"] = {"status": "ok", "basis": "fiscal_year_end_close",
                                        **{k: None for k in ("pe", "ev_ebitda", "ps", "p_fcf", "pb")}}


def no_years(f):
    for b in ("statements", "metrics"):
        f[b] = {k: [] for k in f[b]}
    f["periods"]["fiscal_years"] = []
    f["company"].update(name=None, kind="something_new", not_meaningful=[], statement_currency=None)
    f["price"]["currency"] = None


# (mutation of QUAL's document, lines or line parts its report must hold)
VARIATIONS = {
    "no estimates": (no_estimates, ["Needs analyst estimates for the current and next fiscal years (not on this FMP "
                                    "plan or none published); forward multiples not available.",
                                    "No analyst estimates (not on this FMP plan, or none published)."]),
    "one open year": (one_open_year, ["No 3-year distribution: it needs analyst estimates for the current and next "
                                      "fiscal years."]),
    "share basis": (history_problem("share_basis"), [
        R.HISTORY_PROBLEMS["share_basis"] + ", so the fiscal-year-end history is not comparable.",
        R.HISTORY_PROBLEMS["share_basis"] + ", so the multiple history is not comparable and no distribution is shown."]),
    "price jump": (history_problem("price_jump"), [
        R.HISTORY_PROBLEMS["price_jump"] + ", so the fiscal-year-end history is not comparable.",
        R.HISTORY_PROBLEMS["price_jump"] + ", so the multiple history is not comparable and no distribution is shown."]),
    "short history": (history_problem("short_history"), [
        "Not enough positive-earnings price history for a distribution of the forward multiples (needs about 6 "
        "months)."]),
    "not positive today": (now_not_positive, [
        "n/a = the EPS or EBITDA used is zero or negative (or missing), so there is no multiple.",
        "Today's next-12-month EPS is not positive, so there is no forward P/E for today.",
        "No forward EV/EBITDA distribution: next-12-month EBITDA is not positive."]),
    "EV not applicable": (ev_not_applicable, [
        "No forward EV/EBITDA distribution: no net debt or share count for the enterprise value."]),
    "percentile extremes": (extremes, ["below every day of that history.", "above every day of that history."]),
    "groups unavailable or stale": (groups, ["| Industry: Software - Application | n/a | n/a | n/a | n/a | n/a |",
                                             "| Sector: Technology | n/a (last "]),
    "negative group": (negative_group, ["| Industry: Software - Application | negative ("]),
    "rates unavailable": (rates_unavailable, [
        "(fixed default; Treasury/risk-premium data unavailable) |",
        "- Treasury yields and US equity risk premium unavailable: DCF used the fixed default discount rate."]),
    "no risk premium": (no_erp, ["- US equity risk premium unavailable: DCF used the fixed default discount rate."]),
    "CAPM kept in range": (capm_clamped, ["[beta defaulted to 1.0] = 20.00%, kept within 7%-13%) |"]),
    "models missing": (models_missing, [
        "Piotroski F-score: needs at least 2 fiscal years.",
        "Altman Z: not available (needs working capital, retained earnings, EBIT, revenue, total assets and total "
        "liabilities)."]),
    "DCF inputs invalid": (dcf_status("invalid_inputs"), [R.DCF_SKIPS["invalid_inputs"]]),
    "DCF FCF not positive": (dcf_status("fcf_not_positive"), [R.DCF_SKIPS["fcf_not_positive"]]),
    "DCF unavailable": (dcf_status("unavailable"), ["DCF not available."]),
    "reverse below range": (reverse_status("below_range"), [R.REVERSE_DCF["below_range"]]),
    "reverse above range": (reverse_status("above_range"), [R.REVERSE_DCF["above_range"]]),
    "reverse not computable": (reverse_status("not_computable"), [R.REVERSE_DCF["not_computable"]]),
    "DCF value not positive": (negative_dcf, [
        "**Base-case value -12.50 per share is not positive: net debt exceeds the discounted cash flows.** Range "
        "(discount rate +/-1pt, growth +/-2pt): -20.00 - -5.00."]),
    "default growth, 3-year FCF": (default_growth, ["(average FCF of last 3 fiscal years) |",
                                                    "| Growth yrs 1-5 | 5.0% (default (no usable revenue history)) |"]),
    "consensus rows": (consensus_rows, [
        f"| {fake_fmp.LAST_FY} (ended, not yet reported) |",
        f"Analysts' figures for {fy()}, the last reported year, against the reported ones:",
        "| Revenue | 120.00B | 100.00B | 20.0% |",
        "The analysts use another revenue basis (often net instead of gross revenue), so the first year's revenue "
        "growth above is measured from their figure."]),
    "data notes": (notes, [
        "- Data route: third-party proxy at x.org. Data is not served by FMP directly; spot-check key figures against "
        "company filings.",
        "- Price from the latest quote at 2026-10-30 16:00 New York time.",
        "- Statements are in JPY and the price in USD: the multiples and yields mix the two currencies, and the DCF "
        "value per share is in JPY.",
        "- Error: price history: timeout"]),
    "profile price": (profile_price, ["- Price from the company profile, which is cached for up to a day (no current "
                                      "quote)."]),
    "peers without data": (peers_no_data, ["## 11. Peer comparison",
                                           "| NOPE | no data (plan restriction or unknown ticker) |"]),
    "one fiscal year": (one_fiscal_year, [f"Data basis: annual {fy()} in USD",
                                          "Last column: compound annual growth (CAGR), which needs at least 2 fiscal "
                                          "years."]),
    "no fiscal years, unknown kind": (no_years, ["# QUAL\n", "Data basis: annual n/a (TTM unavailable",
                                                 "**Company type:** something_new."]),
}


class StatusCodes(unittest.TestCase):
    def test_variations_render_in_words(self):
        for name, (mutate, expected) in VARIATIONS.items():
            with self.subTest(name):
                doc = copy.deepcopy(DOCS["QUAL"])
                mutate(doc)
                text = R.render(doc, macro_md="### Treasury yields\nTreasury rates not available.", calls=(3, 4))
                for part in expected:
                    self.assertIn(part, text)
                self.assertEqual(judgements(text, doc), [])
                self.assertEqual(untranslated(text, doc), [])
                self.assertNotIn("None", text)
                self.assertEqual(headings(text)[-1], "Data notes")

    def test_variations_drop_what_does_not_apply(self):
        def report(mutate):
            doc = copy.deepcopy(DOCS["QUAL"])
            mutate(doc)
            return R.render(doc)
        self.assertNotIn("Reverse DCF", report(dcf_status("invalid_inputs")))
        self.assertNotIn("Value per share (rows", report(dcf_status("unavailable")))
        self.assertEqual(report(notes).count("- Error: price history: timeout"), 1)
        self.assertNotIn("Data route", report(profile_price))
        self.assertNotIn("Peer median", report(peers_no_data))
        self.assertNotIn("EV each day", report(ev_not_applicable))
        self.assertIn("Forward P/E each day", report(ev_not_applicable))


if __name__ == "__main__":
    unittest.main()
