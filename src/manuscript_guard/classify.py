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
from collections.abc import Sequence
from dataclasses import dataclass
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
            pattern=re.compile(item["pattern"]),
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
                pattern=re.compile(item["pattern"]),
                kind=CONVENTION,
            )
            for item in extra_conventions
        )
        project_terms = frozenset(str(t).lower() for t in extra_terms)
        merged_terms = tuple(sorted({*terms, *project_terms}, key=len, reverse=True))
        return cls(conventions + project_rules, structural, merged_terms, project_terms)

    def classify(self, atom: Atom, section: Sequence[str] | None = None) -> Verdict:
        """Judge one atom. `section` is the chain of headings enclosing it, when known.

        Only G2 passes a section, because only G2 is reading a manuscript with headings. A
        caller that passes nothing gets every rule, which is the behaviour figure text and
        the audit had before `methods_only` existed and still need: a figure legend has no
        Methods section to sit in, and a `p < 0.05` in one is a legend convention.
        """
        matched = _terms_covering(atom.text, self.terms)
        if matched is not None:
            return Verdict(TERM, rule="terms", detail=", ".join(matched))
        for rule in self.structural:
            if _applies(rule, section) and _rule_covers(rule, atom):
                return Verdict(STRUCTURAL, rule=rule.id, detail=rule.why)
        for rule in self.conventions:
            if _applies(rule, section) and _rule_covers(rule, atom):
                return Verdict(CONVENTION, rule=rule.id, detail=rule.why)
        return Verdict(UNCLASSIFIED)


# Where a method may be described. The analysis plan counts: it is the same statement made
# before the fact, and G12 reads it as one.
METHODS_SECTIONS = re.compile(
    r"^\s*(?:materials\s+and\s+)?(?:methods|methodology|statistical\s+analysis|"
    r"analysis\s+plan|study\s+design|design|protocol)\b",
    re.IGNORECASE,
)


def is_methods(section: Sequence[str] | None) -> bool:
    """True when any enclosing heading is a Methods-like one."""
    return bool(section) and any(METHODS_SECTIONS.match(title) for title in section)


def _applies(rule: Rule, section: Sequence[str] | None) -> bool:
    return not rule.methods_only or section is None or is_methods(section)


def _rule_covers(rule: Rule, atom: Atom) -> bool:
    """True when the rule matches a span of the line that contains the whole atom."""
    start, end = atom.in_line
    for match in rule.pattern.finditer(atom.line_text):
        if match.start() <= start and match.end() >= end:
            return True
    return False


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
