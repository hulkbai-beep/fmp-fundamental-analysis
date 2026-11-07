"""
Offline, static tests of the local page (ui/index.html and its labels in ui/i18n.js). No browser and no JavaScript
engine are needed:

    python -m unittest discover -s tests

The decision engine (investment-final-plan, ifp/web.py fa_page) embeds this page to show a saved run: it puts a
fetch override for /api/analyze in front of the line <script src="i18n.js"></script>, hides the form #f and opens
the page with ?symbol=, which submits the form. So those stay exactly as they are. The tests also check that every
label key the page uses has both languages in i18n.js and that i18n.js keeps no label the page does not use, that
the form sends only what ui/server.py reads, that the price chart and the price ranges come from beside the
document (only the page shows them), and that the parts v2.0 removed (the score, the flags, the insider trades,
the implied volatility) are gone from the page.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "ui"))

PAGE = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
I18N = (ROOT / "ui" / "i18n.js").read_text(encoding="utf-8")
SCRIPT = PAGE.split('<script src="i18n.js"></script>', 1)[-1]     # the page's own script

# ifp/web.py fa_page: the line it injects in front of, and what it injects
MARKER = '<script src="i18n.js"></script>'
ENGINE_INJECT = ("<style>#f{display:none}</style><script>(()=>{const run=\"runs/QUAL/2026-11-02\";const f=window.fetch"
                 ".bind(window);window.fetch=(u,o)=>String(u).startsWith('/api/analyze')?f('/api/fa-view?run='+"
                 "encodeURIComponent(run),o):f(u,o);})();</script>")
# The labels the page set with t(): applyLang() reads the attribute keys; every other call names its key.
DYNAMIC_CALLS = {"t(el.dataset.i18n)", "t(el.dataset.i18nPh)", "t(el.dataset.i18nTitle)"}
# Label keys of the parts v2.0 removed, by prefix or name (the score card, the flags card, the implied-volatility
# input).
REMOVED_KEYS = re.compile(r"^(sc_|lbl_|ind_|note_|val_|cap_|cf_|cr_|q_|zone_|conf_|grp_|pctile|pio_scaled|"
                          r"altman_rule|flags_title$|pos$|neg$|none$|f_iv$|iv_tip$|ph_realized$)")
# What the page may no longer mention (case-sensitive: the Piotroski tile reads models.piotroski.score).
REMOVED_TEXT = ("scoreCard", "r.score", "viewsHtml", "flag", "Flag", "margin_of_safety", "SCORE_UI", "insider",
                "Insider", "price target", "Price target")
# What the page shows beside the document (ui/server.py; the decision engine sends the same from its run)
PAGE_ONLY = ("prices", "candles", "candles_note", "change_pct", "price_range")


# ---------------------------------------------------------------------------- reading JavaScript as text
def skip_string(src, i):
    """The index after the '...' or "..." literal that starts at src[i]."""
    quote, i = src[i], i + 1
    while src[i] != quote:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def skip_template(src, i):
    """The index after the `...` template that starts at src[i], ${...} parts (and templates in them) included."""
    i += 1
    while src[i] != "`":
        if src[i] == "\\":
            i += 2
        elif src.startswith("${", i):
            i = skip_braces(src, i + 1)
        else:
            i += 1
    return i + 1


def skip_braces(src, i):
    """The index after the {...} block that starts at src[i] (strings, templates and comments skipped)."""
    depth = 0
    while True:
        c = src[i]
        if c in "'\"":
            i = skip_string(src, i)
            continue
        if c == "`":
            i = skip_template(src, i)
            continue
        if src.startswith("//", i):
            i = src.index("\n", i)
            continue
        if src.startswith("/*", i):
            i = src.index("*/", i) + 2
            continue
        depth += {"{": 1, "}": -1}.get(c, 0)
        i += 1
        if depth == 0:
            return i


TOKEN = re.compile(r"\s+|//[^\n]*|/\*.*?\*/|[A-Za-z_$][\w$]*|\d[\d.]*|=>|\.\.\.|\S", re.S)


def tokens(src):
    """The tokens of a piece of JavaScript without regular expression literals: strings and templates whole."""
    out, i = [], 0
    while i < len(src):
        if src[i] in "'\"`":
            j = (skip_template if src[i] == "`" else skip_string)(src, i)
        else:
            j = TOKEN.match(src, i).end()
            if not src[i].isspace() and not src.startswith(("//", "/*"), i):
                out.append(src[i:j])
            i = j
            continue
        out.append(src[i:j])
        i = j
    return out


def ui_labels(src):
    """{language: set of keys} of the object `const UI = {zh: {...}, en: {...}}` in i18n.js."""
    start = src.index("{", src.index("const UI = {"))
    toks = tokens(src[start:skip_braces(src, start)])
    out, depth, lang = {}, 0, None
    for k, tok in enumerate(toks):
        if tok in "{([":
            depth += 1
            if depth == 2 and toks[k - 1] == ":":
                lang = toks[k - 2]
                out[lang] = set()
        elif tok in "})]":
            depth -= 1
        elif depth == 2 and toks[k - 1] in "{," and k + 1 < len(toks) and toks[k + 1] == ":":
            out[lang].add(tok.strip("\"'"))
    return out


LABELS = ui_labels(I18N)


def page_keys():
    """The label keys the page uses: data-i18n* attributes and t("key", ...) calls."""
    keys = set(re.findall(r'data-i18n(?:-ph|-title)?="([^"]+)"', PAGE))
    return keys | set(re.findall(r'\bt\("([^"]+)"', SCRIPT))


def form_fields():
    form = re.search(r'<form id="f">(.*?)</form>', PAGE, re.S).group(1)
    return set(re.findall(r'\bname="([^"]+)"', form))


class Tokenizer(unittest.TestCase):
    def test_the_label_reader(self):
        src = ('const UI = {\n  zh: { a: "x: y", "b c": `t ${x ? `in ${y}` : "}"}`, // d: "no"\n'
               '    f: (u, v) => ({ w: u }), g: 1 },\n  en: { a: "", "b c": "", f: 0, g: 2 },\n};\nconst Z = { h: 1 };')
        self.assertEqual(ui_labels(src), {"zh": {"a", "b c", "f", "g"}, "en": {"a", "b c", "f", "g"}})


class Engine(unittest.TestCase):
    """What ifp/web.py fa_page relies on."""

    def test_the_engine_can_embed_the_page(self):
        self.assertEqual(PAGE.count(MARKER), 1)
        self.assertEqual(PAGE.count('<form id="f">'), 1)
        self.assertEqual(PAGE.count('fetch("/api/analyze?" + q)'), 1)
        self.assertEqual(len(re.findall(r"\bfetch\(", PAGE)), 1)      # the one request the engine answers
        self.assertIn('<button type="button" class="lang" id="lang"></button>', PAGE)
        self.assertIn('$("#lang").onclick', SCRIPT)
        # the engine opens the page with ?symbol=TICKER, which submits the form
        self.assertIn('new URLSearchParams(location.search).get("symbol")', SCRIPT)
        self.assertIn('$("#f").requestSubmit()', SCRIPT)
        # its injected script and style go in front of i18n.js, before the page's own script runs
        embedded = PAGE.replace(MARKER, ENGINE_INJECT + MARKER, 1)
        self.assertLess(embedded.index(ENGINE_INJECT), embedded.index("const t = "))
        self.assertNotRegex(PAGE, r'<form id="f"[^>]*\bstyle=')       # nothing overrides the engine's #f{display:none}

    def test_the_page_reads_the_v2_answer(self):
        self.assertIn('startsWith("fa-2")', SCRIPT)                    # an error card for anything but fa-2.x
        self.assertIn("data.result", SCRIPT)
        self.assertIn("data.report", SCRIPT)
        for absent in (".profile", ".current", "r.years"):
            self.assertNotIn(absent, SCRIPT)

    def test_there_is_no_tls_notice(self):
        """The client always verifies FMP's HTTPS certificate, so neither the report nor the page has a note that
        verification was off."""
        for text in ((ROOT / "scripts" / "facts_report.py").read_text(encoding="utf-8"), SCRIPT, I18N):
            self.assertNotIn("verification was OFF", text)
            self.assertNotIn("notice_tls", text)

    def test_the_translator_returns_what_it_cannot_read(self):
        """eventZh() runs on every text zh() gets. Its "." stops at a line break inside the text (\\r, U+2028,
        U+2029), so the match can be null: it must then return the text, not throw and blank the page."""
        body = I18N[I18N.index("function eventZh("):]
        body = body[:body.index("\n}\n")]
        self.assertRegex(body, r"const m = name\.match\(.+\);\n\s*if \(!m\) return name;")


class Labels(unittest.TestCase):
    def test_both_languages_have_the_same_labels(self):
        self.assertEqual(sorted(LABELS), ["en", "zh"])
        self.assertEqual(sorted(LABELS["zh"] ^ LABELS["en"]), [])

    def test_every_label_the_page_uses_exists_and_none_is_unused(self):
        used = page_keys()
        self.assertGreater(len(used), 30)
        self.assertEqual(sorted(used - LABELS["zh"]), [])
        self.assertEqual(sorted(used - LABELS["en"]), [])
        self.assertEqual(sorted(LABELS["zh"] - used), [])

    def test_every_label_call_names_its_key(self):
        """So the check above sees every key: no t(variable) apart from applyLang()'s attribute keys."""
        starts = [m.start() for m in re.finditer(r"\bt\(", SCRIPT)]
        named = [i for i in starts if re.match(r't\("[\w-]+"\s*[,)]', SCRIPT[i:])]
        self.assertGreater(len(named), 20)
        others = {SCRIPT[i:SCRIPT.index(")", i) + 1] for i in starts if i not in named}
        self.assertEqual(sorted(others - DYNAMIC_CALLS), [])

    def test_no_label_of_a_removed_part(self):
        self.assertEqual(sorted(k for k in LABELS["zh"] | LABELS["en"] if REMOVED_KEYS.match(k)), [])
        self.assertNotIn("SCORE_UI", I18N)

    def test_the_report_translator_and_sector_names_stay(self):
        """The page translates the report with zh() and the sector with sectorZh() (tested in
        test_facts_report.py)."""
        for name in ("function zh(", "const sectorZh = ", "const ZH_EXACT = ", "const ZH_RULES = "):
            self.assertEqual(I18N.count(name), 1, name)
        self.assertIn("sectorZh(", SCRIPT)
        self.assertRegex(SCRIPT, r"\btr\(")


class Form(unittest.TestCase):
    def test_the_form_sends_what_the_server_reads(self):
        import server

        class Query(dict):
            """A query that records which parameters run_analysis() reads."""
            read = set()

            def get(self, key, default=None):
                self.read.add(key)
                return super().get(key, default)

            def __getitem__(self, key):
                self.read.add(key)
                return super().__getitem__(key)

        q = Query(symbol="QUAL", peers="TRAP", discount="9", growth="5", terminal="2.5", fcf_base="avg3", macro="1",
                  refresh="1", iv="45", years="3")
        with mock.patch.object(server.A, "run_page", return_value=({}, "", {"prices": []})) as run:
            self.assertEqual(server.run_analysis(q)[0], 200)
        args = run.call_args[0][0]
        self.assertEqual((args.peers, args.discount, args.fcf_base, args.macro, args.refresh, args.iv),
                         ("TRAP", 0.09, "avg3", True, True, None))
        self.assertEqual(sorted(form_fields()), sorted(Query.read))     # iv and years are not read
        # the page itself adds nothing else to the query
        self.assertEqual(set(re.findall(r'\bq\.(?:set|append)\("([^"]+)"', SCRIPT)), {"symbol"})

    def test_no_implied_volatility_input(self):
        self.assertNotIn("iv", form_fields())
        self.assertNotRegex(PAGE, r"""["'&?]iv\b""")


class PageOnly(unittest.TestCase):
    """The price chart and the price ranges: only the page shows them, from the parts of the answer beside the
    document (never from the document, which has no such fields)."""

    def test_the_page_reads_them_beside_the_document(self):
        for name in PAGE_ONLY:
            self.assertRegex(SCRIPT, rf"\bdata\.{name}\b", name)
            self.assertNotRegex(SCRIPT, rf"\b(?:d|result|r)\.{name}\b", name)

    def test_each_part_is_left_out_when_it_is_missing(self):
        """The decision engine may send none of them (a run without a technical chart, an older skill)."""
        self.assertIn("if (barsOf(data).length) h += priceCard(data);", SCRIPT)
        self.assertIn("lastRange = data.price_range?.rows?.length ? data.price_range : null;", SCRIPT)
        self.assertIn('typeof data.change_pct === "number"', SCRIPT)
        self.assertIn("(pr ? rangeTiles(", SCRIPT)

    def test_the_price_range_tab_comes_before_the_data_notes(self):
        self.assertIn('sections.findIndex(s => s.startsWith("## Data notes"))', SCRIPT)
        self.assertIn('name: t("rc_tab"), html: rangeSection(lastRange)', SCRIPT)

    def test_every_method_has_a_colour_and_a_name(self):
        import price_range as PR  # noqa: F401  (the module that makes the rows)
        kinds = set(re.findall(r'"kind": "(\w+)"', (ROOT / "ui" / "price_range.py").read_text(encoding="utf-8")))
        self.assertEqual(kinds, {"week52", "fwd_pe", "fwd_ev", "dcf", "volatility"})
        colours = re.search(r"const RC_COLOR = \{(.*?)\};", SCRIPT).group(1)
        names = re.search(r"const rcKind = k => \(\{(.*?)\}\)", SCRIPT, re.S).group(1)
        for k in kinds:
            self.assertRegex(colours, rf"\b{k}: \"--c-", k)
            self.assertIn(f'{k}: t("rc_{k}")', names)


class Removed(unittest.TestCase):
    def test_the_page_no_longer_shows_the_removed_parts(self):
        self.assertEqual([w for w in REMOVED_TEXT if w in PAGE], [])

    def test_no_special_cases_for_removed_sections(self):
        """The report v2.0 writes has no "## Fundamental score" or "## N. Price range": every section is a tab."""
        for heading in ("Fundamental score", "Price range"):
            self.assertNotIn(heading, PAGE)


if __name__ == "__main__":
    unittest.main()
