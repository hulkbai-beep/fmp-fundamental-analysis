"""
Offline checks that the docs (SKILL.md, README.md, README.en.md, references/metrics.md) describe the code as it is.
No API key needed:

    python -m unittest discover -s tests

- Every option of `analyze.py --help` is documented in SKILL.md and both READMEs (and has a row in their options
  table, which lists no other option), and every option the docs mention exists in one of the scripts' command
  lines, or is one of the options v2.0 accepts and ignores (said so); a command line in the docs uses only options
  of the script it runs.
- Every file of the skill the docs name exists; only the "What changed in v2.0" section may name the removed files.
  The folder layout of the READMEs lists every file under scripts/, contracts/, references/ and ui/.
- The report sections the guides list are the ones scripts/facts_report.py writes, in its order (an offline
  company with peers and --macro), and metrics.md's contents list matches its sections.
- Outside "What changed in v2.0" the docs mention a removed output or option only to say it is gone or to point to
  the decision engine.
- README.md and README.en.md are parallel: the same heading levels, tables, commands, options, paths and links.
"""
from __future__ import annotations

import contextlib
import io
import re
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
import fmp_client  # noqa: E402
import macro as M  # noqa: E402

DOCS = ("SKILL.md", "README.md", "README.en.md", "references/metrics.md")
GUIDES = ("SKILL.md", "README.md", "README.en.md")  # the ones that document the command line
TEXT = {name: (ROOT / name).read_text(encoding="utf-8") for name in DOCS}
CHANGES = re.compile(r"^## (What changed in v2\.0|v2\.0 的变化)\s*$")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
HELP_OPTION = re.compile(r"^ +(?:-\w(?: [A-Z_]+)?, )?(--[a-z][a-z0-9-]*)", re.M)  # the option lines of a --help
COMMAND = re.compile(r"\b(?:python3?|py) (?:scripts|ui)/(\w+\.py)\b([^`\n]*)")   # a command line and what follows
SKILL_PATH = re.compile(r"(?<![\w./-])(?:scripts|tests|ui|contracts|references)/[\w./-]*\w|"
                        r"(?<![\w./-])(?:SKILL|README(?:\.en)?)\.md(?![\w.])")
IGNORED_SAID = ("ignored", "不起作用")      # how the docs say that --iv and --no-insider do nothing
EXTERNAL_OPTIONS = {"--exclude", "--version"}  # rsync, python3 and git in the setup steps
REMOVED_FILES = ("scripts/score.py", "scripts/contract.py", "contracts/fa-1.1.schema.json", "scripts/score_batch.py",
                 "references/validation-set.txt", "scripts/insider.py")
SCORE_RULES = "https://github.com/hulkbai-beep/investment-final-plan/blob/main/docs/fundamental-score-1.3.md"


def help_text(call):
    """What an argparse --help prints."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        call()
    return out.getvalue()


def script_options():
    """{script: its long options}: from the option lines of --help where the script uses argparse, from the
    docstring otherwise."""
    import server
    with mock.patch.object(sys, "argv", ["server.py", "--help"]):
        server_help = help_text(server.main)
    return {
        "analyze.py": set(HELP_OPTION.findall(help_text(lambda: A.parse_args(["--help"])))),
        "facts.py": set(HELP_OPTION.findall(help_text(lambda: F.main(["--help"])))),
        "macro.py": set(HELP_OPTION.findall(help_text(lambda: M.main(["--help"])))),
        "server.py": set(HELP_OPTION.findall(server_help)),
        "fmp_client.py": set(OPTION.findall(fmp_client.__doc__)),
    }


OPTIONS = script_options()
DEPRECATED = {"--" + key.replace("_", "-") for key, _ in A.DEPRECATED_NOTES}   # each prints a note when used
IGNORED = DEPRECATED - OPTIONS["analyze.py"]                                  # accepted, ignored, not in --help


def without_code(text):
    return re.sub(r"^```.*?^```[^\n]*$", "", text, flags=re.M | re.S)


def section(text, heading, inside=True):
    """The lines of the '## ' section whose heading matches, without the heading ('' when there is none); with
    inside=False, every other line."""
    out, cur = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            cur = bool(heading.match(line))
            if not (inside or cur):
                out.append(line)
        elif cur == inside:
            out.append(line)
    return "\n".join(out)


def paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def tables(text):
    """Each markdown table as its list of rows (cells), separator rows left out."""
    out, cur = [], None
    for line in without_code(text).splitlines():
        line = line.strip()   # a table inside a list item is indented
        if line.startswith("|"):
            if cur is None:
                cur = []
                out.append(cur)
            if not re.fullmatch(r"\|[\s|:-]+\|", line):
                cur.append([c.strip() for c in line.strip("|").split("|")])
        else:
            cur = None
    return out


def code_blocks(text):
    """The fenced code blocks, normalised so the two READMEs compare: comments, quoted strings and <placeholders>
    are left out."""
    out = []
    for block in re.findall(r"^```[^\n]*\n(.*?)^```", text, flags=re.M | re.S):
        lines = []
        for line in block.splitlines():
            line = re.sub(r"\s+#.*$", "", line)
            line = re.sub(r"\"[^\"]*\"|'[^']*'", "Q", line)
            lines.append(re.sub(r"<[^>]*>", "<X>", line).rstrip())
        out.append(lines)
    return out


def tree_paths(text):
    """The files and folders of the folder layout block (the one starting with fmp-fundamental-analysis/)."""
    block = next(b for b in re.findall(r"^```\n(.*?)^```", text, flags=re.M | re.S)
                 if b.startswith("fmp-fundamental-analysis/"))
    stack, out = [], []
    for line in block.splitlines()[1:]:
        m = re.match(r"^((?:│   |    )*)[├└]── (\S+)", line)
        depth = len(m.group(1)) // 4
        stack[depth:] = [m.group(2).rstrip("/")]
        out.append("/".join(stack) + ("/" if m.group(2).endswith("/") else ""))
    return out


def report_of(argv):
    with mock.patch.object(A, "FMPClient", fake_fmp.FakeClient), contextlib.redirect_stderr(io.StringIO()):
        return A.run(A.parse_args(argv))[1]


MACRO = "Rates & macro backdrop"   # listed without its number, which depends on the peers


def listed_sections(name):
    """The report's sections a guide lists, in its order. SKILL.md: the bold names of the bullets under "## The
    report, section by section" (the title line and the company-type note are not sections). A README: the
    `## N. ...` code spans and the macro entry of the list that holds `## 1. Growth`."""
    text = TEXT[name]
    if name == "SKILL.md":
        names = re.findall(r"^- \*\*(.+?)\*\*", section(text, re.compile(r"^## The report, section by section")), re.M)
        return [n for n in names if re.match(r"\d+\. ", n) or n in (MACRO, "Data notes")]
    lines = text.splitlines()
    i = j = next(k for k, line in enumerate(lines) if "`## 1. Growth`" in line)
    while i > 0 and lines[i - 1].startswith("- "):
        i -= 1
    while j + 1 < len(lines) and lines[j + 1].startswith("- "):
        j += 1
    spans = re.findall(rf"`(## [^`]+|{re.escape(MACRO)})`", "\n".join(lines[i:j + 1]))
    return [s[3:] if s.startswith("## ") else s for s in spans]


# Words for what v2.0 removed. Outside "What changed in v2.0" a sentence may hold one only to say it is gone (a
# negation), to tell what was there before v2.0, or to point to the decision engine that now has the score.
REMOVED_WORDS = re.compile(r"fundamental score|基本面(?:打分|评分)|price ranges?\b|价格区间|price targets?\b|"
                           r"target prices?\b|目标价|\binsider|内部人|margin of safety|安全边际|--iv\b|--no-insider\b|"
                           r"volatility range|implied volatility|隐含波动率|波动区间|K-line|candlestick|K ?线|"
                           r"\bfa-1\.1\b|automated flags|\bverdicts?\b", re.I)
# A negation, looked for in the sentence without its code spans and option names: the "no" of `--no-insider` or the
# "none" of `--peers none` says nothing is gone, nor do 不 in 不同 / 不仅, 别 in 分别 or "not only ... but also".
SAYS_GONE = re.compile(r"\b(?:no|not(?! only)|never|none|nor|neither|without|removed|deleted|dropped|ignored|ignores|"
                       r"gone)\b|n't|不再|不给|不会|不起作用|不用|不要|不能|不是|没有|无需|删除|删掉|去掉|移除|忽略|别用", re.I)
ELSEWHERE = re.compile(r"investment-final-plan|decision engine|决策引擎|fundamental_view|before v2\.0|v2\.0 之前", re.I)


def presented_as_present(text):
    """The sentences of a doc (outside "What changed in v2.0", code blocks and SKILL.md's frontmatter) that name a
    removed output or option without saying it is gone."""
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    text = without_code(section(text, CHANGES, inside=False))
    out = []
    for block in re.split(r"\n\s*\n|\n(?=\s*[-*] |\s*\d+\. |\|)", text):
        for s in re.split(r"(?<=[.!?;])\s+|(?<=[。；])", " ".join(block.split())):
            prose = OPTION.sub(" ", re.sub(r"`[^`]*`", " ", s))
            if REMOVED_WORDS.search(s) and not SAYS_GONE.search(prose) and not ELSEWHERE.search(s):
                out.append(s)
    return out


class Options(unittest.TestCase):
    def test_every_option_of_the_help_is_documented(self):
        shown = OPTIONS["analyze.py"] - {"--help"}
        self.assertIn("--facts", shown)
        for name in GUIDES:
            for opt in sorted(shown):
                self.assertRegex(TEXT[name], rf"`{re.escape(opt)}(?![\w-])", f"{name} does not document {opt}")

    def test_every_option_the_docs_mention_exists(self):
        known = set().union(*OPTIONS.values()) | IGNORED | EXTERNAL_OPTIONS | {"--help"}
        for name in DOCS:
            self.assertEqual(sorted(set(OPTION.findall(TEXT[name])) - known), [], name)

    def test_each_command_line_uses_options_of_its_script(self):
        for name in DOCS:
            for script, rest in COMMAND.findall(TEXT[name]):
                used = set(OPTION.findall(rest.split(" #")[0]))
                self.assertEqual(sorted(used - OPTIONS[script]), [], f"{name}: {script}{rest}")

    def test_the_options_table_lists_the_options_of_analyze(self):
        """The table of analyze.py's options has a row for each option of --help (a deprecated one may be left to
        the text) and no other option."""
        self.assertEqual(DEPRECATED & OPTIONS["analyze.py"], {"--contract"})
        for name in GUIDES:
            listed = {opt for table in tables(TEXT[name]) if table[0][0] in ("Option", "参数")
                      for row in table[1:] for opt in OPTION.findall(row[0])}
            self.assertEqual(sorted(listed - OPTIONS["analyze.py"]), [], name)
            self.assertEqual(sorted(OPTIONS["analyze.py"] - listed - DEPRECATED - {"--help"}), [], name)

    def test_the_ignored_options_are_said_to_be_ignored(self):
        self.assertEqual(IGNORED, {"--iv", "--no-insider"})
        for name in GUIDES:
            paras = paragraphs(without_code(TEXT[name]))
            for opt in sorted(IGNORED):
                self.assertTrue(any(re.search(rf"`{re.escape(opt)}`", p) and any(w in p for w in IGNORED_SAID)
                                    for p in paras), f"{name}: {opt} is not said to be ignored")


class Paths(unittest.TestCase):
    def test_every_path_the_docs_name_exists_or_is_named_as_removed(self):
        """Outside "What changed in v2.0" every path exists; inside it, a path exists or names a removed file."""
        for name in DOCS:
            outside = set(SKILL_PATH.findall(section(TEXT[name], CHANGES, inside=False)))
            inside = set(SKILL_PATH.findall(section(TEXT[name], CHANGES)))
            self.assertEqual(sorted(p for p in outside if not (ROOT / p).exists()), [],
                             f"{name} names files that do not exist")
            self.assertEqual(sorted(p for p in inside if not (ROOT / p).exists() and p not in REMOVED_FILES), [],
                             f"{name}: What changed names files that neither exist nor were removed")

    def test_what_changed_names_the_removed_files(self):
        for name in GUIDES:
            changes = section(TEXT[name], CHANGES)
            for path in REMOVED_FILES:
                self.assertFalse((ROOT / path).exists(), path)
                self.assertIn(f"`{path}`", changes, name)

    def test_the_folder_layout_lists_existing_files(self):
        for name in ("README.md", "README.en.md"):
            listed = tree_paths(TEXT[name])
            self.assertEqual([p for p in listed if not (ROOT / p).exists()], [], name)
            files = sorted(p.relative_to(ROOT).as_posix() for d in ("scripts", "contracts", "references", "ui")
                           for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            self.assertEqual([f for f in files if f not in listed], [], f"{name} leaves out files")


class Sections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = report_of(["QUAL", "--peers", "TRAP,UTIL", "--macro"])
        cls.headings = re.findall(r"^## (.+)$", cls.report, re.M)

    def test_the_report_sections_the_docs_list_are_the_ones_it_writes(self):
        """Each guide's list of the sections names every one the report writes, in the report's order."""
        self.assertEqual(self.headings[-3:], ["11. Peer comparison", f"12. {MACRO}", "Data notes"])
        want = [MACRO if h.endswith(MACRO) else h for h in self.headings]
        for name in GUIDES:
            self.assertEqual(listed_sections(name), want, name)

    def test_the_header_parts_the_docs_name(self):
        bank = report_of(["BANK", "--peers", "none"])
        for part in ("\nData basis: ", "\n**Company type:** "):
            self.assertIn(part, bank)
        self.assertNotIn("**Company type:**", self.report)   # a general company has no such note
        for name in GUIDES:
            for part in ("# TICKER - Name", "Data basis", "Company type"):
                self.assertIn(part, TEXT[name], name)

    def test_metrics_contents_match_its_sections(self):
        text = TEXT["references/metrics.md"]
        contents = re.findall(r"^(\d+)\. (.+)$", section(text, re.compile(r"^## Contents")), re.M)
        found = re.findall(r"^## (\d+)\. (.+)$", text, re.M)
        self.assertEqual([n for n, _ in found], [str(i) for i in range(1, len(found) + 1)])
        self.assertEqual([n for n, _ in contents], [n for n, _ in found])
        for (_, entry), (_, title) in zip(contents, found):
            self.assertTrue(title.startswith(entry.split(" (")[0]), (entry, title))


class Removed(unittest.TestCase):
    def test_removed_outputs_and_options_are_not_described_as_present(self):
        for name in DOCS:
            self.assertEqual(presented_as_present(TEXT[name]), [], name)

    def test_the_check_finds_planted_sentences(self):
        planted = ["Use `--iv 0.45` to add the volatility range of the price.",
                   "- **Fundamental score.** The report opens with the fundamental score; quote it first.",
                   "报告最后有「价格区间」一节，给出目标价和 52 周区间。",
                   "Use `--no-insider` to skip the insider trades (saves 1 to 5 API calls).",
                   "With `--no-market` the report still prints the price targets.",
                   "Run it with `--peers none` and the report still prints the price targets.",
                   "The report shows not only the fundamental score but also the price range.",
                   "Quote the price target instead of the DCF value.",
                   "报告分别给出目标价和价格区间。", "报告不仅给出目标价，还给出价格区间。"]
        kept = ["v2.0 has no price targets.", "不给目标价。", "The score lives in the decision engine.",
                "`--iv` and `--no-insider` are accepted and ignored.", "`--no-insider` 不起作用。"]
        for s in planted:
            self.assertTrue(presented_as_present(f"# Doc\n\nSome text.\n\n{s}\n"), s)
        for s in kept:
            self.assertEqual(presented_as_present(f"# Doc\n\n{s}\n"), [], s)


class Content(unittest.TestCase):
    def test_skill_frontmatter_keeps_the_name_and_the_trigger_phrases(self):
        head = TEXT["SKILL.md"].split("\n---\n", 1)[0]
        self.assertIn("\nname: fmp-fundamental-analysis\n", head)
        for phrase in ("cheap/expensive/undervalued", "值不值得买", "贵不贵", "估值", "利率"):
            self.assertIn(phrase, head)

    def test_the_score_rules_moved_to_the_decision_engine(self):
        for name in DOCS:
            self.assertIn(SCORE_RULES, TEXT[name], name)
            self.assertIn("ifp/fundamental_view.py", TEXT[name], name)
        for name in GUIDES:
            self.assertTrue(section(TEXT[name], CHANGES).strip(), f"{name} has no 'What changed in v2.0' section")

    def test_the_call_counts_the_docs_state(self):
        log = []

        class Client(fake_fmp.FakeClient):
            def _fetch(self, endpoint, params):
                log.append(endpoint)
                return super()._fetch(endpoint, params)

        n = {}
        for name, argv in (("none", ["--peers", "none"]), ("no-ttm", ["--peers", "none", "--no-ttm"]),
                           ("no-market", ["--peers", "none", "--no-market"]), ("macro", ["--peers", "none", "--macro"]),
                           ("two peers", ["--peers", "TRAP,UTIL"]), ("auto peers", [])):
            log.clear()
            with mock.patch.object(A, "FMPClient", Client):
                A.analyze(A.parse_args(["QUAL", *argv]))
            n[name] = len(log)
        self.assertEqual((n["none"], n["no-ttm"], n["no-market"], n["macro"]), (14, 11, 10, 25))
        self.assertEqual((n["two peers"] - n["none"], n["auto peers"] - n["none"]), (10, 1))  # the fake has no peers
        en, zh, skill = TEXT["README.en.md"], TEXT["README.md"], TEXT["SKILL.md"]
        self.assertIn(f"makes {n['none']} API calls: {n['no-ttm']} with `--no-ttm`, {n['no-market']} with "
                      f"`--no-market`, {n['macro']} with `--macro`. Peers add 5 calls each, and finding the automatic "
                      f"peers 1 more.", en)
        self.assertIn(f"调用 {n['none']} 次 API：加 `--no-ttm` 是 {n['no-ttm']} 次，加 `--no-market` 是 {n['no-market']} "
                      f"次，加 `--macro` 是 {n['macro']} 次。每家同行多 5 次，自动查找同行再多 1 次。", zh)
        ttm, market, macro = n["none"] - n["no-ttm"], n["none"] - n["no-market"], n["macro"] - n["none"]
        for part in (f"saves {ttm} API calls", f"({macro} more API calls)", f"saves {market} API calls",
                     "(5 API calls each)"):
            self.assertIn(part, en)
        for part in (f"省 {ttm} 次 API 调用", f"多 {macro} 次 API 调用", f"省 {market} 次 API 调用", "每家 5 次 API 调用"):
            self.assertIn(part, zh)
        for part in (f"({ttm} fewer API calls)", "(5 API calls per peer)"):
            self.assertIn(part, skill)
        # What changed in v2.0: 21 and 27 calls before (measured on 8c5ceed), the measured counts now
        for text in (en, skill):
            self.assertIn(f"Without peers an analysis makes {n['none']} API calls instead of 21, and {n['macro']} "
                          f"instead of 27 with `--macro`", " ".join(text.split()))
        self.assertIn(f"不做同行对比时，一次分析调用 {n['none']} 次 API，原来是 21 次；加 `--macro` 是 {n['macro']} 次，"
                      f"原来是 27 次", zh)


class Parallel(unittest.TestCase):
    """README.md (Chinese) and README.en.md (English) have the same structure."""

    def setUp(self):
        self.zh, self.en = TEXT["README.md"], TEXT["README.en.md"]

    def test_same_headings(self):
        levels = [[len(h) for h in re.findall(r"^(#+) ", without_code(t), re.M)] for t in (self.zh, self.en)]
        self.assertEqual(levels[0], levels[1])

    def test_same_tables(self):
        zh, en = tables(self.zh), tables(self.en)
        self.assertEqual([len(t) for t in zh], [len(t) for t in en])
        for tz, te in zip(zh, en):
            for rz, re_ in zip(tz, te):
                self.assertEqual(re.findall(r"`[^`]+`", rz[0]), re.findall(r"`[^`]+`", re_[0]), (rz[0], re_[0]))

    def test_same_commands(self):
        self.assertEqual(code_blocks(self.zh), code_blocks(self.en))

    def test_same_options_paths_and_links(self):
        for pattern in (OPTION, SKILL_PATH, re.compile(r"\]\((?!README)([^)]+)\)")):
            self.assertEqual(sorted(set(pattern.findall(self.zh))), sorted(set(pattern.findall(self.en))),
                             pattern.pattern)


if __name__ == "__main__":
    unittest.main()
