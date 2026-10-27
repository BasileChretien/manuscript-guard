"""Deciding what an atom is.

Four verdicts, and only one of them is acceptable in a finished manuscript source:

  TERM          a name that happens to contain digits (CYP3A4, COVID-19)
  STRUCTURAL    a pointer or a categorical label (Table 2, grade 3, day 30)
  CONVENTION    a convention of scientific writing (p < 0.05, 95% CI)
  UNCLASSIFIED  everything else — reported as a defect

There is no verdict for "matches a number in the results", because in manuscript source a
results-derived number cannot be written as a literal at all. It is a `{{results.key}}`
placeholder or it is a defect. That is what makes this check strong where set-membership
checking is not: nothing can pass by coincidence, because passing is not about the value.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import accumulate
from pathlib import Path

import yaml

from manuscript_guard.text.blocks import Unprinted, read_blocks
from manuscript_guard.text.masking import comparison_escapes
from manuscript_guard.text.tokens import Atom

DATA_DIR = Path(__file__).parent / "data"

TERM = "term"
STRUCTURAL = "structural"
CONVENTION = "convention"
UNCLASSIFIED = "unclassified"

#: A length as TeX reads one, its unit typed against its number, in a unit TeX measures the
#: page in and no paper measures anything in: points, scaled points, Didot points, a font's
#: em and ex, maths units. A LaTeX file's definitions set such lengths,
#: `\\def\\bibhang{24pt}`, `\\lower.5ex` (2026-10-23, from 2601.04966 and 2412.11273). TeX's
#: big points, Cicero and picas are left out, since a paper writes base pairs `bp`, cubic
#: centimetres `cc` and parsecs `pc` with the same letters (round 1 of #443), and so are
#: millimetres, centimetres and inches, which may be the paper's own measure. Layout only in
#: a definition's body (`Classifier.scan`'s `layout`): in the text "24pt" may be a scale's
#: points.
TEX_LENGTH = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:pt|sp|dd|em|ex|mu)")
TEX_LENGTH_WHY = "A TeX length a definition's body sets the page with, which measures nothing."


@dataclass(frozen=True)
class Rule:
    id: str
    why: str
    pattern: re.Pattern[str]
    kind: str
    # A rule that exists only to read a *rendered* document. `audit` meets citations that
    # citeproc has already turned into "(Smith and Jones 2019)"; manuscript source writes
    # them `[@key]` and masks them, so the same rule there buys nothing and costs a great
    # deal — it spans a whole parenthetical, and `_rule_covers` accepts any atom inside a
    # span, so `(Smith 2019, n = 412)` would file 412 as structural. Kept out of the gate
    # that carries the invariant, and out of `explain`, which describes that gate.
    audit_only: bool = False
    # A rule that only holds where the manuscript is describing its own method. `p < 0.05`
    # in a Methods section is a threshold the author chose in advance — a convention. The
    # same characters in Results are a *finding*, and were being waved through: a
    # significance claim the analysis never produced passed the gate that carries the
    # invariant. The rule cannot tell them apart by their text, because they have the same
    # text; it can tell them apart by where they are.
    methods_only: bool = False
    # A rule about headings, which holds only where a match starts a line pandoc prints as
    # one. A `#` line is a heading at the start of a block and text inside a paragraph, and
    # no pattern can see the line above it.
    heading_only: bool = False
    # The same for list numbering: a list cannot interrupt a paragraph either, so "412." that
    # a hard wrap put at the start of a line is prose, and a hand-typed count there passed.
    list_only: bool = False


@dataclass(frozen=True)
class Verdict:
    kind: str
    rule: str | None = None
    detail: str | None = None
    #: The terms that accounted for the atom, where `rule` is `terms`.
    terms: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.kind != UNCLASSIFIED


def _load_rules(filename: str, section: str, kind: str) -> tuple[Rule, ...]:
    document = yaml.safe_load((DATA_DIR / filename).read_text(encoding="utf-8"))
    return tuple(
        Rule(
            id=item["id"],
            why=item["why"],
            pattern=re.compile(item["pattern"], re.MULTILINE),
            kind=kind,
            audit_only=bool(item.get("audit_only", False)),
            methods_only=bool(item.get("methods_only", False)),
            heading_only=bool(item.get("heading_only", False)),
            list_only=bool(item.get("list_only", False)),
        )
        for item in document[section]
    )


@lru_cache(maxsize=1)
def _shipped() -> tuple[tuple[Rule, ...], tuple[Rule, ...], tuple[str, ...]]:
    conventions = _load_rules("conventions.yaml", "conventions", CONVENTION)
    structural = _load_rules("structural.yaml", "structural", STRUCTURAL)
    terms = yaml.safe_load((DATA_DIR / "terms.yaml").read_text(encoding="utf-8"))["terms"]
    ordered = tuple(sorted((str(t).lower() for t in terms), key=len, reverse=True))
    return conventions, structural, ordered


@dataclass(frozen=True)
class Classifier:
    conventions: tuple[Rule, ...]
    structural: tuple[Rule, ...]
    terms: tuple[str, ...]
    # Terms this project added, kept apart from the shipped list so a run can say how much
    # of its own clean bill of health it owes to its own allowlist.
    project_terms: frozenset[str] = frozenset()
    # One-entry scan memo for callers that pass no scan of their own. A dict rather than a
    # field on a frozen dataclass because its *contents* are what change.
    _memo: dict = field(default_factory=dict, repr=False, compare=False)

    def is_project_exemption(self, verdict: Verdict) -> bool:
        """Whether this atom was accepted by something the project itself declared.

        `conventions:` and `terms:` in paper.yaml are self-service, deliberately — the gate
        is a tool for an author who wants it, not a control over one who does not. What is
        not deliberate is their being invisible: a project could exempt half its numbers
        and the run would read exactly like one that exempted none.
        """
        if verdict.rule and verdict.rule.startswith("project:"):
            return True
        if verdict.rule == "terms":
            # The terms themselves, and not `detail` cut at its commas: a declared name
            # that holds one, `1,3-BDG`, was a term and was counted for nobody.
            return bool(set(verdict.terms) & self.project_terms)
        return False

    @classmethod
    def load(
        cls,
        extra_conventions: tuple[dict, ...] = (),
        extra_terms: tuple[str, ...] = (),
        *,
        rendered: bool = False,
    ) -> Classifier:
        """Build a classifier. `rendered=True` for text citeproc has already been through.

        The default is deliberately the strict one: a rule needed only to read a built
        document must not quietly widen the gate that reads the source.
        """
        conventions, structural, terms = _shipped()
        if not rendered:
            conventions = tuple(r for r in conventions if not r.audit_only)
            structural = tuple(r for r in structural if not r.audit_only)
        project_rules = tuple(
            Rule(
                id=f"project:{item.get('id', item['pattern'][:24])}",
                why=item["why"],
                pattern=re.compile(item["pattern"], re.MULTILINE),
                kind=CONVENTION,
            )
            for item in extra_conventions
        )
        project_terms = frozenset(str(t).lower() for t in extra_terms)
        # Longest first, and by their letters within one length: left to the order of a set,
        # terms of one length were tried in an order that changed from one run to the next.
        merged_terms = tuple(
            sorted({*terms, *project_terms}, key=lambda term: (-len(term), term))
        )
        return cls(conventions + project_rules, structural, merged_terms, project_terms)

    def scan(
        self,
        text: str,
        *,
        lines_are_blocks: bool = False,
        blocks: bool = True,
        layout: Iterable[tuple[int, int]] = (),
    ) -> Scan:
        """Find every rule's matches in one document, so `classify` is a lookup.

        `text` is read as Markdown, where a heading or a list item starts only where pandoc
        would start one. `lines_are_blocks` is for text that is not Markdown and has no
        paragraphs spanning lines: a .docx read one Word paragraph per line, or a figure's
        text one element per line. Read as Markdown, every line after the first would be a
        wrapped line of one long paragraph, and typed numbering there would stop counting.
        Every line then starts a list item where one is typed, and none is a heading.

        `blocks` False is for a LaTeX file's view (`text/latex/views.py`), whose headings and
        list items are commands: LaTeX numbers them, so no number typed there is their
        numbering, and the rules that read a heading's or an item's numbering hold nowhere in
        it. The NUL the reader writes for what does not print is taken out before the rules
        read it (`_printed`).

        `layout` is where a LaTeX file sets its pages: its definitions' bodies, where a TeX
        length is layout (`TEX_LENGTH`).
        """
        rules = (*self.structural, *self.conventions)
        if not blocks:
            rules = tuple(rule for rule in rules if not (rule.heading_only or rule.list_only))
        found = _scan(rules, text, lines_are_blocks=lines_are_blocks, blanked=not blocks)
        spans = sorted(layout)
        if not spans:
            return found
        return Scan(found.starts, found.reach, tuple(start for start, _end in spans),
                    tuple(accumulate((end for _start, end in spans), max)))  # fmt: skip

    def classify(
        self, atom: Atom, section: Sequence[str] | None = None, scan: Scan | None = None
    ) -> Verdict:
        """Judge one atom. `section` is the chain of headings enclosing it, when known.

        Only G2 passes a section, because only G2 is reading a manuscript with headings. A
        caller that passes nothing gets every rule, which is the behaviour figure text and
        the audit had before `methods_only` existed and still need: a figure legend has no
        Methods section to sit in, and a `p < 0.05` in one is a legend convention.

        `scan` is the document's rule matches, found once by the caller. Without one this
        scans `atom.source` and remembers the result for the next atom from the same string,
        so a caller judging many atoms from one document pays for one scan either way and
        both paths answer identically — two code paths with different semantics is the bug
        this file has already had several times.
        """
        matched = _terms_covering(atom.text, self.terms)
        if matched is None and (marked := _unsigned_marked(atom)) is not None:
            # `HbA~1c~` is `HbA1c` with a subscript, and `CO~2~` a declared `CO2`.
            bare, raised, sunk = marked
            matched = _names_covering(bare, raised, self.terms, sunk=sunk)
        if matched is not None:
            return Verdict(TERM, rule="terms", detail=", ".join(matched), terms=tuple(matched))
        if scan is None:
            scan = self._scan_of(atom.source)
        for rule in self.structural:
            if _applies(rule, section) and scan.covers(rule.id, atom.start, atom.end):
                return Verdict(STRUCTURAL, rule=rule.id, detail=rule.why)
        for rule in self.conventions:
            if _applies(rule, section) and scan.covers(rule.id, atom.start, atom.end):
                return Verdict(CONVENTION, rule=rule.id, detail=rule.why)
        if scan.in_layout(atom.start, atom.end) and TEX_LENGTH.fullmatch(atom.text):
            return Verdict(CONVENTION, rule="tex-length", detail=TEX_LENGTH_WHY)
        return Verdict(UNCLASSIFIED)

    def classify_under(
        self, atom: Atom, sections: Sequence[Sequence[str]], scan: Scan | None = None
    ) -> Verdict:
        """Judge an atom under each of `sections`, as a footnote's number is judged where it
        stands and at each of its references (`sections.chains_at`): unclassified if it is
        under any, and otherwise judged under the first, where it stands."""
        verdicts = [self.classify(atom, section, scan) for section in sections]
        return next((v for v in verdicts if v.kind == UNCLASSIFIED), verdicts[0])

    def _scan_of(self, text: str) -> Scan:
        """One-entry memo, keyed by the text itself, for callers that pass no scan."""
        cached = self._memo.get("text")
        if cached is not None and cached is text:
            return self._memo["scan"]
        found = self.scan(text)
        self._memo.clear()
        self._memo["text"] = text
        self._memo["scan"] = found
        return found


# Where a method may be described. The analysis plan counts: it is the same statement made
# before the fact, and G12 reads it as one.
# Whole heading, not a prefix. `\b` at the end made this a prefix match, so an ordinary
# Results subsection called "Protocol deviations" or "Design of the sub-study" counted as
# Methods and re-admitted every threshold rule underneath it. Anchored at both ends now: a
# heading either is one of these or it is not, and an unusual one means binding the value,
# which is the direction to fail in.
METHODS_SECTIONS = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*|[IVXLC]+[.)]\s*)?"  # numbered headings: "2. Methods", "II."
    # Never a section that reports what was found as well: "Methods and results", a research
    # letter's combined section, let every threshold convention through under its results.
    r"(?!.*\b(?:results?|findings|discussion|conclusions?)\b)"
    # "Materials and methods", "Patients and methods", "Methods and analysis": the Methods by
    # another name, which G4 has always counted as a required Methods section present.
    # "Methods: data sources", "Methods. Study design", "Methods of the study": the Methods
    # with what they hold after a stop, a colon or a dash, or after "of".
    r"(?:[^\n]*?\band\s+methods|methods\s+and\s+[^\n]+|"
    r"methods\s*[:.\N{EN DASH}\N{EM DASH}][^\n]*|methods\s+of\s+[^\n]+|methods|methodology|"
    r"statistical\s+(?:analysis|analyses|methods)|analysis\s+plan|statistical\s+plan|"
    r"study\s+design|design|protocol|sensitivity\s+analys[ei]s)"
    r"\s*$",
    re.IGNORECASE,
)

#: What labels a part of a supplement: "Appendix 1:", "eAppendix 2.", "Appendix S1.",
#: "Supplement 1.", "S1 Appendix.", "S1 Text".
_SUPPLEMENT_LABEL = (
    r"(?:e?appendix|supplement|S\d+\s+(?:appendix|text|file))"
    r"(?:\s+(?:S?\d+[A-Z]?|[A-Z]))?(?:\s*[.:]\s*|\s+)"
)

# What a supplement calls its Methods, which none of the names above is: "Supplementary
# methods", "Supplemental methods 2", "Online methods", "eMethods", "eMethods 1. Data
# source", "S1 Methods", "Appendix 1: Methods", "Appendix S1. Supplementary methods",
# "Supplement 1. eMethods". Under these, G2's Methods-only conventions passed nowhere and a
# model's kind typed in them was never read by G15, although every gate reads the supplement:
# `is_methods` takes them, for their own text and for a section under them that names a
# method too (`_opened_by_the_supplement`). The name marks the section as the supplement's
# Methods, so words may follow it after a stop, a colon or a space, as a numbered part's
# title does; a word glued to it ("eMethodsX") is another name, and "Methods" alone is the
# list above's.
SUPPLEMENT_METHODS = re.compile(
    # The look ahead first, where it is tried once: after the number, as in the list above,
    # it was tried again at each place the number could end, and "1." typed a thousand times
    # took a second. A number holds no word, so it is read the same.
    r"^(?!.*\b(?:results?|findings|discussion|conclusions?)\b)"
    r"\s*(?:\d+(?:\.\d+)*[.)]?\s*|[IVXLC]+[.)]\s*)?"
    rf"(?:{_SUPPLEMENT_LABEL}(?:(?:supplementary|supplemental)\s+)?methods"
    rf"|(?:{_SUPPLEMENT_LABEL})?(?:(?:supplementary|supplemental|online)\s+methods"
    r"|e-?methods|S\d+\s+methods))"
    r"(?:\s*\d+[A-Z]?|\s+S\d+[A-Z]?|\s+[IVXLC]+\b)?"
    r"(?:[^\w\n][^\n]*)?$",
    re.IGNORECASE,
)


def names_supplement_methods(title: str) -> bool:
    """Whether a heading's title, as typed, is a supplement's name of the Methods
    (`SUPPLEMENT_METHODS`). Such a name holds the word, and the pattern is tried only on a
    title that does: `is_methods` reads every title for every number."""
    return "methods" in title.lower() and SUPPLEMENT_METHODS.match(title) is not None


def names_methods_place(title: str) -> bool:
    """Whether a heading's title, as typed, names a place the method is described: a name of
    `METHODS_SECTIONS` or of `SUPPLEMENT_METHODS`. Where it stands is `is_methods`'s to say."""
    return bool(METHODS_SECTIONS.match(title)) or names_supplement_methods(title)


def _opened_by_the_supplement(section: Sequence[str]) -> bool:
    """Whether a supplement's name of the Methods opens the run of headings, innermost
    outwards, that each name a method: "eMethods 1", or "Supplementary methods" over
    "Statistical analysis" or "eMethods 2". Not a heading of another name under one.

    A supplement often has "Supplementary methods" over all of it, its tables and a paragraph
    of results among them, as the example's has. Read as the Methods there, a P the paragraph
    reported passed as the threshold chosen in advance, which main failed as unbound (round 1
    of #395). The main text's names hold everything under them, as they always have."""
    for title in reversed(section):
        if isinstance(title, Unprinted):
            continue  # a line pandoc prints as text, inside the section above, as for main's
        if not names_methods_place(title):
            return False
        if names_supplement_methods(title):
            return True
    return False


# Headings that make everything under them a report of what happened, whatever the
# subheadings are called. Several names in METHODS_SECTIONS are ambiguous — "Sensitivity
# analyses", "Design", "Protocol" are all written as Results subsections — and matching
# `any` heading in the chain meant a Results subsection called "Sensitivity analyses"
# re-admitted every methods_only rule beneath it. A reported `p < 0.001` there classified
# as the pre-specified threshold: exactly the failure `methods_only` was built to close,
# in a subsection that appears in most pharmacoepidemiology papers.
NOT_METHODS_SECTIONS = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*|[IVXLC]+[.)]\s*)?"  # "3. Results", "III. Results"
    r"(?:results?|findings|discussion|conclusions?|interpretation|introduction|background|"
    r"abstract|summary|limitations)"
    r"\s*$",
    re.IGNORECASE,
)


def is_methods(section: Sequence[str] | None) -> bool:
    """True when the enclosing headings describe the method rather than the findings.

    A Methods-like heading counts only while no ancestor is a section that reports what
    happened. "Methods > Sensitivity analyses" is Methods; "Results > Sensitivity analyses"
    is not, and the difference is the whole point of the rule.

    A title pandoc prints as text (`Unprinted`) can say Results, and never Methods: the line
    ends the section above it either way, but a reader of the document sees no heading there.
    A chain that knows its printed headings (`sections.Chain`) must say Methods both ways, so
    such a line can take Methods away and never grant them.

    Results is recognised through the marks a printed title can keep: `# Results` over a rule
    is a heading pandoc prints as "# Results", `- Results` over one is a list item holding a
    heading, and `{#sec-results}` is an identifier. Methods is not, so a mark never opens it.
    """
    if not section:
        return False
    printed = getattr(section, "printed", None)
    if printed is not None and not is_methods(printed):
        return False
    if any(rules_out_methods(title) for title in section):
        return False
    if any(
        METHODS_SECTIONS.match(title) for title in section if not isinstance(title, Unprinted)
    ):
        return True
    return _opened_by_the_supplement(section)


def rules_out_methods(title: str) -> bool:
    """True when a heading's title names a section that is not Methods, Results say, read
    through the marks and raw markup it may keep."""
    return bool(NOT_METHODS_SECTIONS.match(_unmarked(title)))


_MARKS = re.compile(r"^[\s#>*+_-]+")
#: What a title can hold that the page does not show: an HTML tag or comment, and raw TeX
#: such as `\label{sec:results}`. No alternative can start again inside what another failed
#: on, so a long title is read in one pass.
_RAW = re.compile(r"<!--.*?(?:-->|$)|</?[A-Za-z][^<>\n]*>|\\[A-Za-z]+\*?(?:\{[^{}]*\})*")


def _unmarked(title: str) -> str:
    """A heading's title without the marks it may keep: leading hashes, quote and list
    marks, emphasis around it (`**Results**`), trailing attributes, and raw HTML or TeX,
    which a reader of the built document does not see (`# <del>Results</del>`).

    The attribute block goes first. Stripped after raw markup, an unclosed `<!--` in
    `{title="<!--"}` took the `}` with it, and "Results" was no longer read."""
    return _without_emphasis_end(_MARKS.sub("", _RAW.sub("", _without_attributes(title))))


def _without_attributes(title: str) -> str:
    """`title` without a closing `{...}` holding no brace, and the spaces around it. Worked
    out from the last `{`: as `\\s*\\{[^{}]*\\}\\s*$` it was tried from every character of a
    run of spaces, and `is_methods` reads every title for every number."""
    body = title.rstrip()
    if not body.endswith("}"):
        return title
    opening = body.rfind("{")
    if opening == -1 or "}" in body[opening + 1 : -1]:
        return title
    return body[:opening].rstrip()


def _without_emphasis_end(title: str) -> str:
    """`title` without the spaces, `*` and `_` it ends with. `[\\s*_]+$` was tried from
    every character of such a run: 1,000 ` *_` over five numbers took G2 36 s."""
    end = len(title)
    while end and (title[end - 1].isspace() or title[end - 1] in "*_"):
        end -= 1
    return title[:end]


def _applies(rule: Rule, section: Sequence[str] | None) -> bool:
    # A verdict reads a section only here, and only whether it is Methods: a footnote's
    # numbers are judged under one chain of each kind (`sections.chains_at`), which holds
    # while that is so.
    return not rule.methods_only or section is None or is_methods(section)


@dataclass(frozen=True)
class Scan:
    """Where every rule matches in one document, found once.

    The classifier used to match each rule against a bounded window around each atom, which
    is one regex scan per atom per rule. On a paragraph written as a single line with 8,000
    numbers in it that is 168,000 scans of 320 characters each, and `check` took 30 seconds
    inside `_rule_covers` alone. The windows overlap almost entirely, so nearly all of that
    work was being done again and again on the same characters.

    Scanning the whole document once per rule is the same question asked once. It also
    removes the reason `^` and `$` were broken: in a window they meant "start of this
    160-character slice", which is a position 160 characters before the atom and almost
    never the start of anything. `ordered-list-marker` therefore only ever fired within the
    first 160 characters of a file, and every numbered list further down a real manuscript
    was reported as unbound numbers. Scanning the document under `re.MULTILINE` makes the
    anchors mean what all three anchored rules were written to mean.
    """

    #: rule id -> the start offset of each match, in document order.
    starts: dict[str, list[int]]
    #: rule id -> the furthest end reached by any match starting at or before the same index.
    #: A running maximum, so coverage is one binary search rather than a walk: matches are
    #: sorted by start but not by end, and a long early match can cover an atom that several
    #: later, shorter matches do not.
    reach: dict[str, list[int]]
    #: Where a LaTeX file sets its pages (`Classifier.scan`'s `layout`), by start, and the
    #: furthest end reached by any of them starting at or before the same index.
    layout_starts: tuple[int, ...] = ()
    layout_reach: tuple[int, ...] = ()

    def covers(self, rule_id: str, start: int, end: int) -> bool:
        starts = self.starts.get(rule_id)
        if not starts:
            return False
        index = bisect_right(starts, start) - 1
        return index >= 0 and self.reach[rule_id][index] >= end

    def in_layout(self, start: int, end: int) -> bool:
        index = bisect_right(self.layout_starts, start) - 1
        return index >= 0 and self.layout_reach[index] >= end


def _printed(text: str, *, blanked: bool = False) -> tuple[str, list[int] | None]:
    """`text` without the backslashes that escape a comparison, and where each character of
    that came from; see `comparison_escapes`. `ROR \\> 2` prints as `ROR > 2`, and a rule
    reads what prints.

    Removed, not blanked. A space kept every offset and satisfied any rule that wants one
    there: `412)\\>ULOQ` at the start of a line read as a list marker, and 412 passed.

    `blanked` is for a LaTeX file's view, where the reader writes NUL for what does not
    print: those go too, so that `per 100\\,000 person-years`, a space and a NUL there, reads
    as it prints.
    """
    gone = set(comparison_escapes(text))
    if blanked:
        gone.update(found.start() for found in _BLANK.finditer(text))
    if not gone:
        return text, None
    origin = [index for index in range(len(text) + 1) if index not in gone]
    return "".join(text[index] for index in origin[:-1]), origin


_BLANK = re.compile("\x00")


def _scan(
    rules: Iterable[Rule], text: str, *, lines_are_blocks: bool = False, blanked: bool = False
) -> Scan:
    printed, origin = _printed(text, blanked=blanked)
    starts: dict[str, list[int]] = {}
    reach: dict[str, list[int]] = {}
    ends: dict[str, list[int]] = {}
    blocks: tuple[frozenset[int], frozenset[int]] | None = None
    for rule in rules:
        at: list[int] = []
        upto: list[int] = []
        until: list[int] = []
        furthest = -1
        # Text whose lines are blocks (a .docx, a figure) has no Markdown headings: Word's
        # carry a style, not a `#`, so a heading rule holds nowhere in it.
        if rule.heading_only and lines_are_blocks:
            continue
        for match in rule.pattern.finditer(printed):
            start, end = match.span()
            if origin is not None:
                start, end = origin[start], origin[end - 1] + 1 if end > start else origin[start]
            if (rule.heading_only or rule.list_only) and not lines_are_blocks:
                if blocks is None:
                    found = read_blocks(text)
                    blocks = (
                        frozenset(heading.start for heading in found.headings),
                        frozenset(found.items),
                    )
                if start not in blocks[0 if rule.heading_only else 1]:
                    continue
            at.append(start)
            until.append(end)
            furthest = max(furthest, end)
            upto.append(furthest)
        if not at:
            continue
        if rule.id in starts:
            # A second rule under one name: two conventions a project gave one `id`, or two
            # whose patterns begin with the same 24 characters. Its matches join the first
            # rule's. They replaced them, and the number the first was written for failed
            # as unbound. Sorted only here, so that a name held by one rule costs nothing.
            spans = sorted(
                [*zip(starts[rule.id], ends[rule.id], strict=True), *zip(at, until, strict=True)]
            )
            at = [start for start, _end in spans]
            until = [end for _start, end in spans]
            upto = list(accumulate(until, max))
        starts[rule.id] = at
        ends[rule.id] = until
        reach[rule.id] = upto
    return Scan(starts, reach)


#: A subscript and a superscript as pandoc reads them: between two of the sign, with no
#: space and no sign inside. `HbA~1c~`, `Ca^2+^`.
_SUBSCRIPT = re.compile(r"~([^\s~]+)~")
_SUPERSCRIPT = re.compile(r"\^([^\s^]+)\^")
#: A word and, in a superscript, digits alone, with a sign before them or none: a
#: citation's number typed by hand (`shown^12^`, `shown^3-5^`) or an exponent (`year^-1^`).
#: Neither is a name. An ion's charge has its sign after the digit, `Ca^2+^`, and is one.
_MARKED_WORD = re.compile(r"[^\W\d_]+\^[-+−]?\d[\d,–-]*\^")


def _with_its_closing_sign(atom: Atom) -> str:
    """The atom's text with the `~` that closed its last subscript, where the tokenizer
    took it off: an atom is cut at the punctuation round it, so `CO~2~` is `CO~2` there."""
    closed = atom.text.count("~") % 2 and atom.source[atom.end : atom.end + 1] == "~"
    return atom.text + "~" if closed else atom.text


def unsigned(atom: Atom) -> str | None:
    """The atom's text with the signs of its subscripts and superscripts taken out, which
    is how a name is matched against the terms: `HbA~1c~` as `HbA1c`, `CO~2~` as a declared
    `CO2`. None where it holds neither.

    No term matched `CO~2`, built in or declared, and an author had to declare it sign and
    all, or type the subscript character.

    A sign is one where pandoc reads one: closed by another, with no space between. A
    tilde nothing closes is printed as a tilde and stands for "about" or for a range. The
    first version took every sign out, and the number after such a tilde joined the
    letters before it: `pH~2` was `ph2`, which holds the built-in term `h2`, so a pH, an
    effect of `HR~2` and a rise of `increased~2-fold` were accepted as terms."""
    marked = _unsigned_marked(atom)
    return None if marked is None else marked[0]


def _unsigned_marked(atom: Atom) -> tuple[str, frozenset[int], frozenset[int]] | None:
    """`unsigned`, with the places in it that a superscript held and those that a
    subscript held."""
    text = _with_its_closing_sign(atom)
    lowered, sunk, _kept = _signs_out(_SUBSCRIPT, text)
    bare, raised, kept = _signs_out(_SUPERSCRIPT, lowered)
    sunk = frozenset(kept[at] for at in sunk if kept[at] >= 0)
    return None if bare == text else (bare, raised, sunk)


def _signs_out(sign: re.Pattern[str], text: str) -> tuple[str, frozenset[int], list[int]]:
    """`text` with each pair of `sign` taken out round what it holds; the places in the
    result that what the signs held stands at; and, for each place of `text`, its place in
    the result, or -1 for a sign taken out."""
    pieces: list[str] = []
    held: set[int] = set()
    kept: list[int] = []
    cut = size = 0
    for match in sign.finditer(text):
        before, inside = text[cut : match.start()], match.group(1)
        kept += range(size, size + len(before))
        size += len(before)
        held.update(range(size, size + len(inside)))
        kept += (-1, *range(size, size + len(inside)), -1)
        size += len(inside)
        pieces += (before, inside)
        cut = match.end()
    kept += range(size, size + len(text) - cut)
    return "".join((*pieces, text[cut:])), frozenset(held), kept


def declarable(atom: Atom) -> str | None:
    """The name to declare for an unbound atom, where it reads as a name written with a
    subscript or a superscript: `CO2` for `CO~2~`. None where it reads as anything else.

    A name opens with a letter and keeps its digits in its subscripts and superscripts.
    A number beside it is a number (`HbA~1c~7.2`, `R^2^=0.85`), and so is one before it
    (`412~patients~`). A word with digits alone in a superscript is a citation's number
    or an exponent (`shown^12^`, `year^-1^`). Told how to declare any of these, an author
    would have exempted the number."""
    bare = unsigned(atom)
    if bare is None or not bare[:1].isalpha():
        return None
    text = _with_its_closing_sign(atom)
    if any(ch.isdigit() for ch in _SUPERSCRIPT.sub("", _SUBSCRIPT.sub("", text))):
        return None
    return None if _MARKED_WORD.fullmatch(text) else bare


def _names_covering(
    text: str,
    raised: frozenset[int],
    terms: tuple[str, ...],
    *,
    sunk: frozenset[int] = frozenset(),
) -> list[str] | None:
    """`_terms_covering` for a name read without its signs, `raised` being the places in
    `text` that a superscript held and `sunk` those a subscript held. A term holding a
    raised place counts only where it opens a word: taking the signs out puts a
    superscript's digits hard against the word before it, and a citation's number typed
    after a word with a capital inside, "PharmD^2^" or "ApoB^12^", made `d2` and `b12` at
    that capital. `I^131^` opens its word and is a name.

    A subscript is part of the name it is typed in, `pCO~2~` being `co2` and `ppFEV~1~`
    `fev1`, so a term holding a sunk place counts where a word opens, where a capital
    follows a lower-case letter, or directly after another term; but not after a capital,
    where it counted as any term does: an index set below the line after an abbreviation,
    "HR~2~" or "OR~2~", was `r2`, and its number went unchecked."""
    return _terms_covering(text, terms, raised, sunk)


def _term_may_start(text: str, at: int) -> bool:
    """Whether a term may begin at `at` of `text`, as written: where a word opens, after
    no letter and no digit; after a capital, as in "CD3", "CCR2", "HLA-DRB1" and "Th1"; or
    where a capital follows a lower-case letter, as in "sIL-2R", "ppFEV1" and "pCO2". Not
    after a lower-case letter, "April-12", nor after a digit. A term may also begin where
    another ends (`_terms_covering`)."""
    if at == 0 or not text[at - 1].isalnum():
        return True
    before = text[at - 1]
    return before.isupper() or (before.islower() and text[at].isupper())


@lru_cache(maxsize=16)
def _by_first_letter(terms: tuple[str, ...]) -> dict[str, tuple[tuple[int, str], ...]]:
    """The terms by their first character, each with its place in `terms`."""
    found: dict[str, list[tuple[int, str]]] = {}
    for rank, term in enumerate(terms):
        if term:
            found.setdefault(term[0], []).append((rank, term))
    return {first: tuple(ranked) for first, ranked in found.items()}


#: Whether a term counts directly after another, as in "PaO2FiO2" and "CD8CD4". A name of
#: its own so that the property tests can take the opening away and see them fail.
_AFTER_A_TERM = True


def _terms_covering(
    text: str,
    terms: tuple[str, ...],
    raised: frozenset[int] = frozenset(),
    sunk: frozenset[int] = frozenset(),
) -> list[str] | None:
    """Terms that between them account for every digit in `text`, or None. A term counts
    where `_term_may_start`, or directly after another term; the terms used are given in
    the order of `terms`. A term holding a place in `raised` counts only where
    `_term_may_start` and a word opens, and one holding a place in `sunk` not after a
    capital that ends no term (`_names_covering`).

    A term was found anywhere in an atom as it is written, and only a name read without its
    signs was held to a word's start: taking the signs out puts the digits of a superscript
    hard against the word before it, and `risk^1^`, a citation's number, was `risk1`, which
    holds the term `k1`. As written, a word was taken for a name in the same way: with the
    interleukins among the terms, "April-12" held `il-12` and "Brazil-3" `il-3`, and their
    numbers went unchecked. Held to a word's start alone, a name after a lower-case prefix,
    "sIL-2R", was a number; a capital after a lower-case letter opens a name as well.

    The terms were gone through once, longest first, each taken out where it stood, and a
    term directly after another counted only where that one came first among the terms:
    "PaO2FiO2" was a number for terms in one order. Going through them again for as long
    as one was taken out took time by the square of the atom for names alternating with
    nothing between, and did not end for a declared term of one space. So the text is read
    once from its end: at each place, whether what follows can be covered, opening there
    or after a term. Where a term or a step past a character could each cover the rest, a
    term with a digit is taken first, then the step, so a term with no digit is named only
    where it is needed; among terms, the one first in `terms`, so cyp2c19 before cyp2c9."""
    low = "".join(ch.lower() if len(ch.lower()) == 1 else ch for ch in text)
    size = len(low)
    by_first = _by_first_letter(terms)
    found = [
        tuple((rank, term) for rank, term in by_first.get(low[at], ()) if low.startswith(term, at))
        for at in range(size)
    ]
    opens = [_term_may_start(text, at) for at in range(size)]
    # How many raised places stand before each place, so that whether a term holds one is
    # a subtraction; and where a word opens, which is where a term holding one may.
    below = list(accumulate((at in raised for at in range(size)), initial=0)) if raised else []
    under = list(accumulate((at in sunk for at in range(size)), initial=0)) if sunk else []
    words = [opens[at] and (at == 0 or not text[at - 1].isalnum()) for at in range(size)]

    def may_open(at: int, term: str, ended: bool) -> bool:
        if below and below[at + len(term)] > below[at]:
            return words[at]
        if under and under[at + len(term)] > under[at] and not words[at]:
            stepped = text[at - 1].islower() and text[at].isupper()
            return stepped or (ended and _AFTER_A_TERM)
        return opens[at] or (ended and _AFTER_A_TERM)

    # `plain[at]`: what follows `at` can be covered, `at` being no term's end; `after[at]`:
    # the same where a term ends at `at`, so that another may open there.
    plain = [False] * size + [True]
    after = [False] * size + [True]
    for at in range(size - 1, -1, -1):
        step = not low[at].isdigit() and plain[at + 1]
        plain[at] = step or any(
            after[at + len(term)] for _rank, term in found[at] if may_open(at, term, False)
        )
        after[at] = step or any(
            after[at + len(term)] for _rank, term in found[at] if may_open(at, term, True)
        )
    if not plain[0]:
        return None
    used: set[int] = set()
    at, ended = 0, False
    while at < size:
        fits = [
            (rank, term)
            for rank, term in found[at]
            if may_open(at, term, ended) and after[at + len(term)]
        ]
        digits = [(rank, term) for rank, term in fits if any(ch.isdigit() for ch in term)]
        step = not low[at].isdigit() and plain[at + 1]
        chosen = digits or ([] if step else fits)
        if chosen:
            rank, term = chosen[0]
            used.add(rank)
            at, ended = at + len(term), True
            continue
        at, ended = at + 1, False
    return [terms[rank] for rank in sorted(used)] or None
