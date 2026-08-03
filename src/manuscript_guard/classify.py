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
        merged_terms = tuple(
            sorted({*terms, *(str(t).lower() for t in extra_terms)}, key=len, reverse=True)
        )
        return cls(conventions + project_rules, structural, merged_terms)

    def classify(self, atom: Atom) -> Verdict:
        matched = _terms_covering(atom.text, self.terms)
        if matched is not None:
            return Verdict(TERM, rule="terms", detail=", ".join(matched))
        for rule in self.structural:
            if _rule_covers(rule, atom):
                return Verdict(STRUCTURAL, rule=rule.id, detail=rule.why)
        for rule in self.conventions:
            if _rule_covers(rule, atom):
                return Verdict(CONVENTION, rule=rule.id, detail=rule.why)
        return Verdict(UNCLASSIFIED)


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
