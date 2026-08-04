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
from pathlib import Path

import yaml

from manuscript_guard.text.tokens import Atom

DATA_DIR = Path(__file__).parent / "data"

TERM = "term"
STRUCTURAL = "structural"
CONVENTION = "convention"
UNCLASSIFIED = "unclassified"


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


@dataclass(frozen=True)
class Verdict:
    kind: str
    rule: str | None = None
    detail: str | None = None

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
        if verdict.rule == "terms" and verdict.detail:
            used = {part.strip() for part in verdict.detail.split(",")}
            return bool(used & self.project_terms)
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
        merged_terms = tuple(sorted({*terms, *project_terms}, key=len, reverse=True))
        return cls(conventions + project_rules, structural, merged_terms, project_terms)

    def scan(self, text: str) -> Scan:
        """Find every rule's matches in one document, so `classify` is a lookup."""
        return _scan((*self.structural, *self.conventions), text)

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
        if matched is not None:
            return Verdict(TERM, rule="terms", detail=", ".join(matched))
        if scan is None:
            scan = self._scan_of(atom.source)
        for rule in self.structural:
            if _applies(rule, section) and scan.covers(rule.id, atom.start, atom.end):
                return Verdict(STRUCTURAL, rule=rule.id, detail=rule.why)
        for rule in self.conventions:
            if _applies(rule, section) and scan.covers(rule.id, atom.start, atom.end):
                return Verdict(CONVENTION, rule=rule.id, detail=rule.why)
        return Verdict(UNCLASSIFIED)

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
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?"  # numbered headings: "2. Methods"
    r"(?:materials\s+and\s+methods|methods\s+and\s+materials|methods|methodology|"
    r"statistical\s+(?:analysis|analyses|methods)|analysis\s+plan|statistical\s+plan|"
    r"study\s+design|design|protocol|sensitivity\s+analys[ei]s)"
    r"\s*$",
    re.IGNORECASE,
)


# Headings that make everything under them a report of what happened, whatever the
# subheadings are called. Several names in METHODS_SECTIONS are ambiguous — "Sensitivity
# analyses", "Design", "Protocol" are all written as Results subsections — and matching
# `any` heading in the chain meant a Results subsection called "Sensitivity analyses"
# re-admitted every methods_only rule beneath it. A reported `p < 0.001` there classified
# as the pre-specified threshold: exactly the failure `methods_only` was built to close,
# in a subsection that appears in most pharmacoepidemiology papers.
NOT_METHODS_SECTIONS = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*[.)]?\s*)?"
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
    """
    if not section:
        return False
    if any(NOT_METHODS_SECTIONS.match(title) for title in section):
        return False
    return any(METHODS_SECTIONS.match(title) for title in section)


def _applies(rule: Rule, section: Sequence[str] | None) -> bool:
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

    def covers(self, rule_id: str, start: int, end: int) -> bool:
        starts = self.starts.get(rule_id)
        if not starts:
            return False
        index = bisect_right(starts, start) - 1
        return index >= 0 and self.reach[rule_id][index] >= end


def _scan(rules: Iterable[Rule], text: str) -> Scan:
    starts: dict[str, list[int]] = {}
    reach: dict[str, list[int]] = {}
    for rule in rules:
        at: list[int] = []
        upto: list[int] = []
        furthest = -1
        for match in rule.pattern.finditer(text):
            at.append(match.start())
            furthest = max(furthest, match.end())
            upto.append(furthest)
        if at:
            starts[rule.id] = at
            reach[rule.id] = upto
    return Scan(starts, reach)


def _terms_covering(text: str, terms: tuple[str, ...]) -> list[str] | None:
    """Terms that between them account for every digit in `text`, or None.

    Longest first, so cyp2c19 is consumed before cyp2c9 could nibble at it.
    """
    rest = text.lower()
    used: list[str] = []
    for term in terms:
        if term and term in rest:
            rest = rest.replace(term, " ")
            used.append(term)
            if not any(ch.isdigit() for ch in rest):
                return used
    return None
