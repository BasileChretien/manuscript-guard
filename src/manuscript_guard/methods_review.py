"""The methods of studies of the same question, read before the plan is settled.

A plan is better for knowing how others answered its question: which comparator they chose,
where they started follow-up, what they adjusted for. It is not better for copying what most
of them did. A design used often can carry a bias often: immortal time spread through the
pharmacoepidemiology of the 2000s in exactly that way. So a method is judged against a
published methodological standard, never by how many studies used it, and the author decides
what to take.

`design/methods_review.yaml` holds, for each study chosen, why it is similar and, field by
field (`FIELDS`), the words of its stored copy that say what it did, with where they are.
G7 looks for each passage in the study's stored files as it looks for a supporting passage
(`literature/passages.py`). An appraisal names the standard and its domain it is judged
against, from the built-in table (`data/method_standards.yaml`) or a standard the record
describes, and who proposed it: an agent may. A decision to adopt, adapt or reject a method
is a person's (`decided_by`), and a method adopted is cited in the plan, with the standard
it was judged by.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import Finding, Report

REVIEW = Path("design") / "methods_review.yaml"
SCHEMA = "manuscript-guard/methods-review/1"
STANDARDS = Path(__file__).parent / "data" / "method_standards.yaml"

#: What a study did, field by field: the parts of a plan a method is taken into.
FIELDS = (
    "design", "data source", "population", "case definition", "exposure", "outcome",
    "comparator", "time zero and follow-up", "confounding", "model", "missing data",
    "sensitivity analyses", "other",
)  # fmt: skip

ADOPT = "adopt"
ADAPT = "adapt"
REJECT = "reject"
#: The decisions that take a method into the plan, which then cites where it came from.
TAKEN = (ADOPT, ADAPT)


@dataclass(frozen=True)
class Standard:
    """A methodological standard: the built-in table's, or one the record describes."""

    id: str
    name: str
    domains: tuple[str, ...]
    built_in: bool
    #: The key the project cites it under, where the record gives one.
    citekey: str | None = None
    #: How to find it, for the built-in table's: a DOI or a page.
    found_at: str = ""

    def domain(self, named: str | None) -> str | None:
        """The standard's domain `named` is, read loosely, or None."""
        if not named or not named.strip():
            return None
        wanted = _folded(named)
        return next((domain for domain in self.domains if _folded(domain) == wanted), None)


@dataclass(frozen=True)
class Appraisal:
    standard: str | None
    domain: str | None
    concern: str
    says: str
    proposed_by: str
    proposed_on: str | None = None


@dataclass(frozen=True)
class Decision:
    choice: str
    why: str
    decided_by: str
    decided_on: str


@dataclass(frozen=True)
class Method:
    """One field of one study: what it did, in its words, judged and decided."""

    study: int
    number: int
    citekey: str
    field: str
    passage: str
    locator: str
    label: str | None = None
    summary: str = ""
    appraisals: tuple[Appraisal, ...] = ()
    decision: Decision | None = None

    @property
    def what(self) -> str:
        return self.label if self.field == "other" and self.label else self.field

    @property
    def named(self) -> str:
        """How a finding names it: its study, its field, and where it is in the file."""
        return f"@{self.citekey}, {self.what} (study {self.study}, method {self.number})"


@dataclass(frozen=True)
class Study:
    number: int
    citekey: str
    similar: tuple[str, ...]
    why: str
    methods: tuple[Method, ...]


@dataclass(frozen=True)
class Review:
    question: str
    studies: tuple[Study, ...]
    #: The standards the record names, by id: a built-in one's citation key, or one of the
    #: project's own with its domains.
    standards: dict[str, dict]

    @property
    def methods(self) -> list[Method]:
        return [method for study in self.studies for method in study.methods]

    def standard(self, ident: str | None) -> Standard | None:
        """The standard an appraisal names: the built-in table's, with the citation key the
        record gives it, or the record's own; None where neither holds it."""
        if not ident or not ident.strip():
            return None
        ident = ident.strip()
        own = self.standards.get(ident, {})
        citekey = str(own["citekey"]).strip() if own.get("citekey") else None
        known = built_in_standards().get(ident)
        if known is not None:
            return Standard(known.id, known.name, known.domains, True, citekey, known.found_at)
        if own.get("domains"):
            return Standard(
                ident, str(own.get("name") or ident),
                tuple(str(d) for d in own["domains"]), False, citekey,
            )  # fmt: skip
        return None


def _folded(text: str) -> str:
    """A name as it is compared: its case, hyphens, underscores and runs of space folded."""
    return " ".join(re.sub(r"[-_/]+", " ", text).casefold().split())


@lru_cache(maxsize=1)
def standards_table() -> dict[str, dict]:
    """The built-in table of standards (`data/method_standards.yaml`), by id."""
    import yaml

    return yaml.safe_load(STANDARDS.read_text(encoding="utf-8"))["standards"]


def built_in_standards() -> dict[str, Standard]:
    """The built-in standards, by id."""
    return {
        ident: Standard(
            ident, str(entry["name"]), tuple(str(d) for d in entry["domains"]), True,
            found_at=f"https://doi.org/{entry['doi']}" if entry.get("doi")
            else str(entry.get("url") or ""),
        )
        for ident, entry in standards_table().items()
    }  # fmt: skip


def standards_for(study_type: str | None) -> list[str]:
    """The built-in standards that apply to a study design, by id, in the table's order."""
    return [ident for ident, entry in standards_table().items()
            if study_type is None or study_type in entry.get("applies_to", ())]  # fmt: skip


def review_path(project: Project) -> Path:
    return project.root / REVIEW


def read_review(project: Project) -> tuple[Review | None, Report]:
    """The project's methods review, and what stopped it being read.

    No file is no review and no finding: a project need keep none. A file that cannot be
    parsed, or does not fit its schema, gives no review and says why."""
    path = review_path(project)
    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, Report((
            Finding(gate="G0", code="schema-violation", message=str(exc), path=path,
                    hint="see the methods-review schema"),
        ))  # fmt: skip
    if document is None:
        return None, Report()
    report = validate(document, "methods-review", path)
    if not report.ok or not isinstance(document, dict):
        return None, report
    studies = tuple(
        _study(number, entry)
        for number, entry in enumerate(document.get("studies") or [], start=1)
    )
    standards = {
        str(entry["id"]): entry for entry in document.get("standards") or []
    }
    return Review(str(document.get("question") or ""), studies, standards), report


def _study(number: int, entry: dict) -> Study:
    citekey = str(entry["citekey"]).strip()
    methods = tuple(
        Method(
            study=number,
            number=index,
            citekey=citekey,
            field=str(method["field"]),
            passage=str(method["passage"]),
            locator=str(method["locator"]).strip(),
            label=method.get("label"),
            summary=str(method.get("summary") or ""),
            appraisals=tuple(_appraisal(one) for one in _listed(method.get("appraisal"))),
            decision=_decision(method.get("decision")),
        )
        for index, method in enumerate(entry.get("methods") or [], start=1)
    )
    return Study(
        number, citekey, tuple(entry["similar"]), str(entry.get("why") or ""), methods
    )


def _listed(value: object) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _appraisal(entry: dict) -> Appraisal:
    def text(name: str) -> str | None:
        value = entry.get(name)
        return None if value is None else str(value).strip()

    return Appraisal(
        standard=text("standard"),
        domain=text("domain"),
        concern=str(entry["concern"]),
        says=str(entry["says"]),
        proposed_by=str(entry["proposed_by"]).strip(),
        proposed_on=text("proposed_on"),
    )


def _decision(entry: dict | None) -> Decision | None:
    if entry is None:
        return None
    return Decision(
        choice=str(entry["choice"]),
        why=str(entry["why"]),
        decided_by=str(entry["decided_by"]).strip(),
        decided_on=str(entry["decided_on"]),
    )


def review_keys(project: Project) -> list[str]:
    """The citation keys the methods review names, studies first, in the file's order: the
    works whose stored copy its passages are looked for in, and the standards it cites. A
    review that cannot be read names none."""
    review, _report = read_review(project)
    if review is None:
        return []
    keys = [study.citekey for study in review.studies]
    keys += [str(entry["citekey"]).strip() for entry in review.standards.values()
             if entry.get("citekey")]  # fmt: skip
    return list(dict.fromkeys(keys))


def for_panel(review: Review) -> str:
    """The review as a design round reads it: each study, why it was chosen, and each method
    with its words, the appraisals proposed and the author's decision."""
    lines = []
    if review.question.strip():
        lines += [f"Question the studies were chosen for: {' '.join(review.question.split())}", ""]
    for study in review.studies:
        lines.append(f"Study {study.number}: @{study.citekey} (similar in "
                     f"{', '.join(study.similar)})" + (f": {study.why}" if study.why else ""))
        for method in study.methods:
            lines.append(f"  {method.what}"
                         + (f": {method.summary}" if method.summary else ""))  # fmt: skip
            words = " ".join(method.passage.split())
            lines.append(f'    its words ({method.locator}): "{words}"')
            for one in method.appraisals:
                standard = review.standard(one.standard)
                against = standard.name if standard is not None else (one.standard or "no standard")
                domain = f", {one.domain}" if one.domain else ""
                lines.append(f"    appraisal, proposed by {one.proposed_by}, against {against}"
                             f"{domain}: concern {one.concern}: {' '.join(one.says.split())}")
            if method.decision is not None:
                decision = method.decision
                lines.append(f"    decision of {decision.decided_by} ({decision.decided_on}): "
                             f"{decision.choice}: {' '.join(decision.why.split())}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
