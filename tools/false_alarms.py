"""Draw the false-alarm page from its counts, docs/false-alarms.yaml.

    python tools/false_alarms.py      # writes docs/false-alarms.md and the README's line

The counts come from a run of the corpus of real papers and the verdicts on its findings
(`python tools/corpus.py counts <run>`, docs/corpus.md); this script needs no corpus. It
draws a page that gives, for each code, the share of its warnings judged false, with a 95%
interval, the papers it was measured on and what the share does not measure, and the one
line of the README's Status that quotes the share in all. Both are committed, and
`tests/test_false_alarms.py` fails while they differ from what this draws.

A share is weighted (Basile, 2026-11-25): the first verdicts took at most ten findings of each
code in each report, so each paper's judged warnings of a code stand for all its warnings of
that code. Its interval is the wider of two: the papers resampled 2,000 times, since false
alarms cluster in a few papers, and Wilson's score interval at the share and the number
judged, which a resampling cannot give where no judged warning was false.
"""

from __future__ import annotations

import collections
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "docs" / "false-alarms.yaml"
PAGE = "docs/false-alarms.md"
README = REPO / "README.md"
#: The README's line begins so, and the script writes the line that does.
README_START = "- **False alarms**"

#: A code's share is shown from this many judged warnings, from this many papers: the bar of
#: the rule that lowers a code's severity by its precision (Basile, 2026-11-20 and 11-25).
LEAST_JUDGED = 10
LEAST_PAPERS = 3
DRAWS = 2000
Z = 1.959963984540054

FORMATS = {"docx": "Word", "pdf": "PDF", "latex": "LaTeX", "markdown": "Markdown"}
COMMANDS = {"audit": "audit", "audit-pdf": "audit", "check": "check", "compare": "compare"}
#: A field's name, by the label the corpus gives it (arXiv's category, for a LaTeX paper).
FIELDS = {
    "agri": "agriculture", "astro-ga": "astrophysics of galaxies", "biol": "biology",
    "chem": "chemistry", "cs": "computer science", "cs-lg": "machine learning",
    "ecol": "ecology", "econ-em": "econometrics", "educ": "education", "med": "medicine",
    "meta": "research on research", "multi": "multidisciplinary", "nurs": "nursing",
    "nutr": "nutrition", "pharm": "pharmacology", "pharm-epi": "pharmacoepidemiology",
    "psych": "psychology", "pubh": "public health", "qbio-pe": "populations and evolution",
    "socio": "sociology", "sport": "sport science", "stat-ap": "applied statistics",
}  # fmt: skip

#: Where a paper was found, by the label the corpus gives it.
SOURCES = {
    "arxiv": "arXiv", "pmc": "PubMed Central", "zenodo": "Zenodo", "osf:edarxiv": "EdArXiv",
    "osf:metaarxiv": "MetaArXiv", "osf:osf": "OSF Preprints", "osf:psyarxiv": "PsyArXiv",
    "osf:socarxiv": "SocArXiv", "osf:sportrxiv": "SportRxiv",
}  # fmt: skip

SLUG = re.compile(r"[A-Za-z0-9._-]+")
CODE = re.compile(r"[A-Za-z0-9]+/[a-z0-9][a-z0-9-]*")
WORD = re.compile(r"[a-z0-9][a-z0-9-]*")
LABEL = re.compile(r"[a-z0-9][a-z0-9-]*(:[a-z0-9][a-z0-9-]*)?")
HELD = re.compile(r"h\d{2,}")
REASON = re.compile(r"[a-z][a-z ]*")


# --- the counts, held to counts only ----------------------------------------------------


class CountsError(ValueError):
    pass


def load(path: Path = SOURCE) -> dict:
    document = yaml.safe_load(path.read_text("utf-8"))
    check(document)
    return document


def _keys(said: object, keys: set, where: str) -> dict:
    if not isinstance(said, dict) or set(said) != keys:
        raise CountsError(f"{where} holds {sorted(keys)} and nothing else")
    return said


def _whole(value: object, where: str, least: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < least:
        raise CountsError(f"{where}: {value!r} is no whole number from {least}")
    return value


def _word(value: object, pattern: re.Pattern, where: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise CountsError(f"{where}: {value!r} is not a name the counts may hold")
    return value


def _made(said: dict, where: str) -> None:
    _word(said["run"], SLUG, f"{where} run")
    _word(said["commit"], re.compile(r"[0-9a-f]{40}"), f"{where} commit")
    _word(said["version"], re.compile(r"\d+\.\d+\.\d+"), f"{where} version")


def _papers(said: object, names: re.Pattern, where: str) -> dict:
    if not isinstance(said, dict) or not said:
        raise CountsError(f"{where} papers: a mapping of each paper to its format, field and "
                          "source")  # fmt: skip
    for name, value in said.items():
        _word(name, names, f"{where} papers")
        if not isinstance(value, list) or len(value) != 3 or value[0] not in FORMATS or not all(
                isinstance(v, str) for v in value) or not WORD.fullmatch(value[1]) or not (
                LABEL.fullmatch(value[2])):  # fmt: skip
            raise CountsError(f"{where} papers {name}: a format of {sorted(FORMATS)}, a field "
                              "and a source")  # fmt: skip
    return said


def _row(row: object, size: int, where: str) -> list:
    if not isinstance(row, list) or len(row) != size:
        raise CountsError(f"{where}: a row of {size}, not {row!r}")
    n, true, false = (_whole(v, where) for v in row[-3:])
    if true + false < 1 or true + false > n:
        raise CountsError(f"{where}: {true} true and {false} false of {n} warnings")
    return row


def check(document: object) -> None:
    """Refuse a counts file that holds anything but counts and the names they are counted by:
    whatever it held more would be published with the page."""
    if not isinstance(document, dict) or "tuning" not in document or set(document) - {
            "tuning", "heldout"}:  # fmt: skip
        raise CountsError("the counts hold `tuning`, and `heldout` at most, and nothing else")
    tuning = _keys(document["tuning"], {"run", "commit", "version", "date", "verdicts",
                                        "papers", "given", "strata"}, "tuning")  # fmt: skip
    _made(tuning, "tuning")
    _word(str(tuning["date"]), re.compile(r"\d{4}-\d{2}-\d{2}"), "tuning date")
    said = _keys(tuning["verdicts"], {"first", "batches", "left_out"}, "tuning verdicts")
    _whole(said["first"], "verdicts first"), _whole(said["batches"], "verdicts batches")
    for reason, n in (said["left_out"] or {}).items():
        _word(reason, REASON, "verdicts left out"), _whole(n, f"verdicts left out {reason}")
    papers = _papers(tuning["papers"], SLUG, "tuning")
    given = tuning["given"]
    if not isinstance(given, dict) or not set(given) <= set(COMMANDS):
        raise CountsError(f"tuning given: warnings by report, of {sorted(COMMANDS)}, and code")
    for report, codes in given.items():
        if not isinstance(codes, dict):
            raise CountsError(f"tuning given {report}: warnings by code")
        for code, n in codes.items():
            _word(code, CODE, f"tuning given {report}"), _whole(n, f"given {code}", 1)
    covered: collections.Counter[tuple] = collections.Counter()
    for row in tuning["strata"]:
        paper, report, code = _row(row, 6, "tuning strata")[:3]
        if paper not in papers or code not in given.get(report, {}):
            raise CountsError(f"tuning strata: {row!r} names a paper, report or code not there")
        covered[(report, code)] += row[3]
    over = sorted(" ".join(k) for k, n in covered.items() if n > given[k[0]][k[1]])
    if over:
        raise CountsError(f"tuning strata: more warnings of {over} than the run gave")
    if "heldout" in document:
        held = _keys(document["heldout"], {"run", "commit", "version", "milestone", "papers",
                                           "strata"}, "heldout")  # fmt: skip
        _made(held, "heldout")
        _whole(held["milestone"], "heldout milestone", 1)
        numbered = held["papers"]
        if not isinstance(numbered, dict) or not numbered or not all(
                isinstance(k, str) and HELD.fullmatch(k) and isinstance(v, str) and v in FORMATS
                for k, v in numbered.items()):  # fmt: skip
            raise CountsError("heldout papers: each numbered paper with its format alone")
        for row in held["strata"]:
            paper, report = _row(row, 5, "heldout strata")[:2]
            if paper not in numbered or report not in COMMANDS:
                raise CountsError(f"heldout strata: {row!r} names a paper or report not there")


# --- the shares -------------------------------------------------------------------------


@dataclass(frozen=True)
class Share:
    """Warnings in the papers with a verdict, the judged ones true and false, the papers, and
    the weighted share false with its interval, where there is one."""

    warnings: int
    true: int
    false: int
    papers: int
    share: float
    low: float
    high: float

    @property
    def judged(self) -> int:
        return self.true + self.false

    @property
    def shown(self) -> bool:
        return self.judged >= LEAST_JUDGED and self.papers >= LEAST_PAPERS


def _by_paper(rows: list[tuple[str, int, int, int]]) -> dict[str, tuple[float, int]]:
    """Each paper's weighted false warnings and its warnings: each row's warnings shared out
    as its judged ones were."""
    out: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0])
    for paper, n, true, false in rows:
        out[paper][0] += n * false / (true + false)
        out[paper][1] += n
    return {paper: (said[0], int(said[1])) for paper, said in sorted(out.items())}


def wilson(share: float, n: int) -> tuple[float, float]:
    """Wilson's score interval at a share and a number judged."""
    z2 = Z * Z
    centre = (share + z2 / (2 * n)) / (1 + z2 / n)
    half = Z * math.sqrt(share * (1 - share) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def resampled(papers: dict[str, tuple[float, int]]) -> tuple[float, float]:
    """The 2.5th and 97.5th percentiles of the share over the papers drawn again, as many as
    there are, with replacement, `DRAWS` times. The draws are seeded by the papers' counts, so
    the same counts give the same interval wherever they are measured and whenever."""
    values = list(papers.values())
    draw = random.Random(repr(sorted(papers.items())))
    shares = []
    for _ in range(DRAWS):
        picked = draw.choices(values, k=len(values))
        shares.append(sum(p[0] for p in picked) / sum(p[1] for p in picked))
    shares.sort()
    return shares[int(DRAWS * 0.025)], shares[int(DRAWS * 0.975) - 1]


def share(rows: list[tuple[str, int, int, int]]) -> Share:
    """The weighted share false of `rows`, (paper, warnings, judged true, judged false), with
    its interval: the wider of the papers resampled and Wilson's at the number judged."""
    papers = _by_paper(rows)
    true, false = sum(r[2] for r in rows), sum(r[3] for r in rows)
    warnings = sum(p[1] for p in papers.values())
    point = sum(p[0] for p in papers.values()) / warnings
    low, high = resampled(papers)
    w_low, w_high = wilson(point, true + false)
    return Share(warnings, true, false, len(papers), point, min(low, w_low), max(high, w_high))


# --- the page ---------------------------------------------------------------------------


def percent(value: float) -> str:
    """A share as a reader reads it: to one decimal under 10%, else whole."""
    said = 100 * value
    if said == 0:
        return "0%"
    return f"{said:.1f}%" if said < 9.95 else f"{said:.0f}%"


def interval(said: Share) -> str:
    return f"{percent(said.low)} to {percent(said.high)}"


def number(n: int) -> str:
    return f"{n:,}"


def _gate_order(code: str) -> tuple:
    gate, name = code.split("/", 1)
    digits = re.fullmatch(r"G(\d+)", gate)
    return (0, int(digits.group(1)), "", name) if digits else (1, 0, gate, name)


def _formats(slugs: set[str], papers: dict) -> str:
    counts = collections.Counter(papers[s][0] for s in slugs)
    return ", ".join(f"{FORMATS[f]} {counts[f]}" for f in FORMATS if counts[f])


#: The commands in the order the page gives them: `audit` first, since it is the one an
#: editor or a referee runs on a paper they did not write (Basile, 2026-11-25).
ORDER = ("audit", "check", "compare")


class Counts:
    """The counts read once, with the shares the page gives."""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.tuning = document["tuning"]
        self.heldout = document.get("heldout")
        self.papers = self.tuning["papers"]
        self.strata = [tuple(row) for row in self.tuning["strata"]]
        self.given: collections.Counter[tuple[str, str]] = collections.Counter()
        for report, codes in self.tuning["given"].items():
            for code, n in codes.items():
                self.given[(COMMANDS[report], code)] += n

    def rows(self, test=lambda row: True) -> list[tuple[str, int, int, int]]:
        return [(paper, n, true, false) for paper, report, code, n, true, false in self.strata
                if test((paper, report, code))]  # fmt: skip

    def codes(self) -> list[str]:
        return sorted({row[2] for row in self.strata}, key=_gate_order)

    def code(self, code: str) -> Share:
        return share(self.rows(lambda r: r[2] == code))

    def warnings(self, command: str | None = None, code: str | None = None) -> int:
        return sum(n for (c, k), n in self.given.items()
                   if command in (None, c) and code in (None, k))  # fmt: skip

    def commands_run(self) -> list[str]:
        return [c for c in ORDER if any(COMMANDS[r[1]] == c for r in self.strata)]

    def overall(self, command: str, fmt: str | None = None) -> Share:
        return share(self.rows(lambda r: COMMANDS[r[1]] == command and (
            fmt is None or self.papers[r[0]][0] == fmt)))

    def held_rows(self, command: str, fmt: str | None = None) -> list:
        papers = self.heldout["papers"] if self.heldout else {}
        return [(paper, n, true, false) for paper, report, n, true, false
                in (self.heldout or {}).get("strata", [])
                if COMMANDS[report] == command and fmt in (None, papers[paper])]  # fmt: skip

    def held(self, command: str, fmt: str | None = None) -> Share:
        return share(self.held_rows(command, fmt))

    def commands(self, code: str) -> str:
        said = {COMMANDS[r[1]] for r in self.strata if r[2] == code}
        return ", ".join(c for c in ORDER if c in said)

    def slugs(self, code: str) -> set[str]:
        return {r[0] for r in self.strata if r[2] == code}

    def most(self, command: str) -> tuple[str, int, int] | None:
        """The code that holds more than half of a command's warnings in the papers with a
        verdict, with its warnings there and theirs; None where no code does."""
        held: collections.Counter[str] = collections.Counter()
        for _paper, report, code, n, _true, _false in self.strata:
            if COMMANDS[report] == command:
                held[code] += n
        if not held:
            return None
        code, n = max(held.items(), key=lambda kv: (kv[1], kv[0]))
        return (code, n, sum(held.values())) if 2 * n > sum(held.values()) else None


def _version(section: dict) -> str:
    return f"{section['version']} (commit `{section['commit'][:9]}`)"


#: A reason a verdict is left out, as the corpus tool names it, in a reader's words.
LEFT_OUT = {
    "verdict miss": "problems a judge noticed that no warning raised",
    "verdict unclear": "warnings a judge could not settle from the text",
    "paper removed after judging": "verdicts on papers found after judging not to be "
                                   "manuscripts",
}  # fmt: skip
MISS = "verdict miss"


def _intro(counts: Counts) -> list[str]:
    tuning, verdicts = counts.tuning, counts.tuning["verdicts"]
    left = verdicts["left_out"]
    left_said = "; ".join(f"{number(n)} {LEFT_OUT.get(reason, reason)}"
                          for reason, n in left.items()) or "none"  # fmt: skip
    return [
        "# How often a warning is wrong", "",
        "manuscript-guard was run over real papers that nobody wrote for it, and the warnings it "
        "gave were judged true or false against each paper's text. This page gives, for each "
        "kind of warning, its code, the share judged false: how far an editor, a referee or an "
        "author can take a warning of that kind on trust. It counts warnings and failures only. "
        "A note or a question accuses nothing, and the notices that say how a paper was read "
        "say nothing about the paper.", "",
        f"Measured with manuscript-guard {_version(tuning)}, in the corpus's run "
        f"`{tuning['run']}`, on {len(counts.papers)} papers, and counted on {tuning['date']}. "
        f"The verdicts read are {number(verdicts['first'])} from the first judging and "
        f"{number(verdicts['batches'])} from the later batches; left out: {left_said}. "
        "The page is drawn by `tools/false_alarms.py` from [its counts](false-alarms.yaml), "
        "which hold no paper's text, and is drawn again whenever a new run of main becomes the "
        "base of the corpus gate ([Measuring the gates on real papers](corpus.md)).",
    ]  # fmt: skip


def _dominated(counts: Counts, command: str) -> str:
    said = counts.most(command)
    if said is None:
        return ""
    code, n, of = said
    return (f" Of `{command}`'s {number(of)} warnings in papers with a verdict, {number(n)} are "
            f"`{code}`, so its share is mostly that code's.")


def _in_all(counts: Counts) -> list[str]:
    lines = ["", "## In all", "",
             "By command, `audit` first: it is the one an editor or a referee runs on a paper "
             "they did not write. `check` reads a paper brought into a project, and `compare` "
             "two versions of it.", "",
             "| command | papers | warnings | in papers with a verdict | judged | false "
             "| share false | 95% interval |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
    for command in counts.commands_run():
        rows = [r for r in counts.strata if COMMANDS[r[1]] == command]
        formats = [f for f in FORMATS if any(counts.papers[r[0]][0] == f for r in rows)]
        for fmt in (None, *formats):
            said = counts.overall(command, fmt)
            name = f"`{command}`" if fmt is None else ""
            where = f"all, {said.papers}" if fmt is None else f"{FORMATS[fmt]}, {said.papers}"
            warnings = number(counts.warnings(command)) if fmt is None else ""
            lines.append(f"| {name} | {where} | {warnings} | {number(said.warnings)} | "
                         f"{number(said.judged)} | {number(said.false)} | "
                         f"{percent(said.share)} | {interval(said)} |")  # fmt: skip
    lines += ["", "*Papers* are those with a judged warning from the command; *warnings*, all "
              "the command gave about the papers; *in papers with a verdict*, those of a code "
              "in a paper where a warning of that code was judged, which the share is of. The "
              "share weighs each paper's judged warnings of a code by all its warnings of that "
              "code, so a code that gives many warnings weighs much. `check`'s leave out "
              "the warnings every new project gives before anyone writes in it, an empty "
              "analysis plan say, which are about the project and not the paper."
              + "".join(_dominated(counts, c) for c in counts.commands_run())]  # fmt: skip
    return lines


def _by_code(counts: Counts) -> list[str]:
    lines = ["", "## By code", "",
             f"A code's share is given where {LEAST_JUDGED} or more of its warnings were judged, "
             f"from {LEAST_PAPERS} papers or more. What each code says is in "
             "[What is checked](gates.md) and [Auditing a paper](audit.md).", "",
             "| code | given by | warnings | judged | false | share false | 95% interval "
             "| papers |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |"]  # fmt: skip
    few = []
    for code in counts.codes():
        said = counts.code(code)
        if not said.shown:
            few.append((code, said))
            continue
        lines.append(f"| `{code}` | {counts.commands(code)} | "
                     f"{number(counts.warnings(code=code))} | {number(said.judged)} | "
                     f"{number(said.false)} | {percent(said.share)} | {interval(said)} | "
                     f"{said.papers} ({_formats(counts.slugs(code), counts.papers)}) |")
    lines += ["", "## Codes with too few judged warnings", "",
              f"Fewer than {LEAST_JUDGED} judged, or from fewer than {LEAST_PAPERS} papers: too "
              "few to say what share is false.", "",
              "| code | given by | warnings | judged | true | false | papers |",
              "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]  # fmt: skip
    lines += [f"| `{code}` | {counts.commands(code)} | {number(counts.warnings(code=code))} | "
              f"{said.judged} | {said.true} | {said.false} | {said.papers} |"
              for code, said in few] or ["| none | | | | | | |"]  # fmt: skip
    judged = set(counts.codes())
    unjudged: collections.Counter[str] = collections.Counter()
    for (_command, code), n in counts.given.items():
        if code not in judged:
            unjudged[code] += n
    if not unjudged:
        return lines + ["", "Every code that gave a warning has a judged one."]
    codes = "1 other code" if len(unjudged) == 1 else f"{len(unjudged)} other codes"
    lines += ["", f"{codes} gave {number(sum(unjudged.values()))} warnings, none of them "
              "judged.", "", "<details><summary>The codes, with their warnings</summary>", "",
              ", ".join(f"`{c}` {number(n)}" for c, n in sorted(
                  unjudged.items(), key=lambda kv: _gate_order(kv[0]))), "", "</details>"]
    return lines


def _held_out(counts: Counts) -> list[str]:
    held = counts.heldout
    lines = ["", "## Papers held out from the tuning", ""]
    if not held:
        return lines + ["No held-out set has been measured yet."]
    papers = held["papers"]
    lines += [
        "The rules were changed, pull request by pull request, against the verdicts above, so "
        "on those papers they look better than they are. Another "
        f"{len(papers)} papers are held out: they are measured at the end of a stage of the "
        "work only, never shown to whoever changes a rule, and joined to the tuning papers "
        "after three such measures. Their shares are given by command and format, not by "
        "code, which would show where to look.", "",
        f"Measure {held['milestone']}, with manuscript-guard {_version(held)}, in the run "
        f"`{held['run']}`:", "",
        "| command | papers | warnings judged | false | share false | 95% interval |",
        "| --- | --- | ---: | ---: | ---: | ---: |"]  # fmt: skip
    for command in ORDER:
        rows = counts.held_rows(command)
        if not rows:
            continue
        formats = [f for f in FORMATS if any(papers[r[0]] == f for r in rows)]
        for fmt in (None, *formats):
            said = counts.held(command, fmt)
            name = f"`{command}`" if fmt is None else ""
            where = f"all, {said.papers}" if fmt is None else f"{FORMATS[fmt]}, {said.papers}"
            lines.append(f"| {name} | {where} | {number(said.judged)} | {number(said.false)} | "
                         f"{percent(said.share)} | {interval(said)} |")
    return lines


def _the_papers(counts: Counts) -> list[str]:
    fields = collections.Counter(p[1] for p in counts.papers.values())
    formats = collections.Counter(p[0] for p in counts.papers.values())
    held = collections.Counter((counts.heldout or {}).get("papers", {}).values())
    found = collections.Counter(p[2] for p in counts.papers.values())
    where = [f"{SOURCES.get(s, s)} {found[s]}"
             for s in sorted(found, key=lambda s: (-found[s], s))]
    lines = ["", "## The papers", "",
             "The tuning papers are openly licensed preprints and articles, most of them in "
             f"English, found on {', '.join(where)}. They stay out of this repository, since "
             "few of their licences allow passing them on. The held-out papers are given by "
             "format alone: a field or a source beside it could name the paper.", "",
             "| format | tuning | held out |", "| --- | ---: | ---: |"]  # fmt: skip
    lines += [f"| {FORMATS[f]} | {formats[f]} | {held[f]} |" for f in FORMATS
              if formats[f] or held[f]]  # fmt: skip
    lines += ["", "| field of the tuning papers | papers |", "| --- | ---: |"]
    lines += [f"| {FIELDS.get(field, field)} | {fields[field]} |"
              for field in sorted(fields, key=lambda f: (-fields[f], f))]
    return lines


def _limits(counts: Counts) -> list[str]:
    missed = counts.tuning["verdicts"]["left_out"].get(MISS, 0)
    noticed = (f" The judges noted {number(missed)} such problems in passing, but they were not "
               "asked to look for them, and that number is no measure of what is missed."
               if missed else "")  # fmt: skip
    return ["", "## What these shares do not measure", "",
            "- **Warnings never given.** Only what the tool said was judged. A problem in a "
            "paper that no rule flagged is counted nowhere, so this page says nothing of how "
            f"much the tool misses.{noticed}",
            "- **Papers unlike these.** The papers above are mostly preprints, from the fields "
            "listed, and most are in English. A journal's typeset PDF, a field with notation of "
            "its own or another language may fare worse. The held-out PDFs are articles as "
            "journals typeset them: compare their share with the tuning PDFs'.",
            "- **The same papers tuned on.** A share above is of the papers the rules were "
            "corrected against, and flatters them; the held-out shares show by how much.",
            "- **Who judged.** Model judges, each given the paper's text and one written brief "
            "of what each code claims: in the first judging one judge for each field, and in "
            "the later batches two judges blind to each other, the findings they split on "
            "decided by the toolkit's author, who also read 20 of their agreements once. No "
            "editor judged them.",
            "- **True but minor.** A warning judged true is one whose statement about the text "
            "holds. It may still not be worth an author's time.",
            "- **A sample of each paper.** The first judging took at most ten warnings of each "
            "code in each report, spread through its list, and a paper's judged warnings stand "
            "for its others of the code. A code's warnings in a paper with none judged count "
            "among its warnings and not in its share.",
            "- **The interval.** It is the wider of two: the papers drawn again "
            f"{number(DRAWS)} times with replacement, which allows for false alarms that "
            "cluster in a few papers, and Wilson's score interval at the share and the number "
            "judged, which still has a width where no judged warning was false. Both treat "
            "the papers as drawn at random from papers like them, which they were not."]


def page(counts: Counts) -> str:
    lines = [*_intro(counts), *_in_all(counts), *_by_code(counts), *_held_out(counts),
             *_the_papers(counts), *_limits(counts),
             "", "## Drawing it again", "",
             "```bash",
             "python tools/corpus.py counts <run>      # docs/false-alarms.yaml, from the corpus",
             "python tools/false_alarms.py             # this page and the README's line",
             "```", "",
             "The held-out section is counted again only at a measure of the held-out set, "
             "with `--heldout <folder> <run> --milestone <n>`; otherwise `counts` keeps it as "
             "it stands."]  # fmt: skip
    return "\n".join(lines) + "\n"


def readme_line(counts: Counts) -> str:
    """The README's line: the share of `audit`'s warnings judged false, on the tuning papers
    and the held-out ones, and `check`'s, with the code that makes most of it."""
    said, tuning = counts.overall("audit"), counts.tuning
    line = (f"{README_START} were measured on {len(counts.papers)} real papers with "
            f"{tuning['version']}: of the warnings `audit` gives about a paper, "
            f"{percent(said.share)} were judged false (95% interval {interval(said)})")
    if counts.held_rows("audit"):
        held, other = counts.held("audit"), counts.heldout or {}
        build = ("the same build" if other["commit"] == tuning["commit"]
                 else f"{other['version']} (commit `{other['commit'][:9]}`)")  # fmt: skip
        line += (f", and {percent(held.share)} ({interval(held)}) on "
                 f"{len(other['papers'])} papers held out from the tuning, with {build}")
    line += "."
    if "check" in counts.commands_run():
        check, most = counts.overall("check"), counts.most("check")
        line += " Of those `check` gives"
        line += f", most of them `{most[0]}`," if most else ","
        line += f" {percent(check.share)} were ({interval(check)})."
    return line + (" [How often a warning is wrong](docs/false-alarms.md) gives the share for "
                   "each code, and what it does not measure.")


def drawn(path: Path = SOURCE) -> dict[str, str]:
    """What the script writes: the page, by its path from the repository's root."""
    return {PAGE: page(Counts(load(path)))}


def with_line(readme: str, line: str) -> str:
    """The README with its false-alarm line put in place of the one there."""
    lines = readme.split("\n")
    at = [n for n, said in enumerate(lines) if said.startswith(README_START)]
    if len(at) != 1:
        raise CountsError(f"the README has {len(at)} lines that begin {README_START!r}, not one")
    lines[at[0]] = line
    return "\n".join(lines)


def main() -> int:
    counts = Counts(load())
    (REPO / PAGE).write_text(page(counts), "utf-8", newline="\n")
    readme = README.read_text("utf-8")
    README.write_text(with_line(readme, readme_line(counts)), "utf-8", newline="\n")
    print(f"wrote {PAGE} and the README's line")
    return 0


if __name__ == "__main__":
    sys.exit(main())
