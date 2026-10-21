"""G7 and G12: what the methods review records holds, and what is taken from it is cited.

`design/methods_review.yaml` (`methods_review.py`) holds the methods of studies of the same
question, each in the study's own words, an appraisal of each against a methodological
standard, and the author's decision. Two checks read it.

G7 looks for each method's passage in the study's stored files, as it looks for a supporting
passage (`literature/passages.py`). One that is in none of them fails from the analysis stage
on, the stage the plan built on it is frozen at (`similar-passage-not-in-source`; Basile,
2026-10-21): it was retyped, remembered, or taken from another paper. A study with no stored
copy that can be read is a warning (`similar-passage-unchecked`), and a passage of fewer than
four words shows only that its words are somewhere in the study (`similar-passage-too-short`).

G12 holds the appraisals and the decisions. An appraisal names the standard it is judged
against and the standard's domain, so that "immortal time" is a claim a reader can check
against the place it comes from, not the agent's impression (a warning where it names none,
or one the built-in table and the record do not know: `appraisal-without-standard`,
`appraisal-standard-unknown`, `appraisal-domain-unknown`). A decision is a person's: a
model's name may not sign it (`similar-decision-not-human`, failing from the analysis stage
on). A method adopted or adapted is cited in the plan, or in the Methods, by its study's key,
and by the key of the standard it was judged by (`adopted-method-uncited`,
`adopted-standard-uncited`, warnings). The methods not yet appraised, and those appraised and
not yet decided, are counted in a note each.

Whether an appraisal is right is not checked, and cannot be: it is judgement, an agent's
proposal that the design round reads and the author decides on. What is checked is that it
says what it rests on.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.literature.passages import (
    ABSENT,
    NO_SOURCE,
    UNREADABLE,
    VERIFIED,
    looked_for,
    passage_words,
)
from manuscript_guard.literature.sources import UnreadableSource
from manuscript_guard.methods_review import (
    TAKEN,
    Method,
    Review,
    read_review,
    review_path,
)
from manuscript_guard.text.masking import blank_comments
from manuscript_guard.zotero.citations import find_citations

#: Where a citation of the plan is said to be, for `find_citations`, which wants a path.
PLAN_FILE = Path("design") / "plan.md"
#: The fewest words a passage holds for it to say more than that its words are in the study,
#: as G7 asks of a supporting passage.
WORDS = 4


def check_method_passages(project: Project) -> Report:
    """G7: each method's passage is in its study's stored copy."""
    review, report = read_review(project)
    if review is None:
        return report
    path = review_path(project)
    sources = project.path("literature") / "sources"
    read: dict[Path, str | UnreadableSource] = {}
    found = {VERIFIED: 0, ABSENT: 0, NO_SOURCE: 0, UNREADABLE: 0}
    for method in review.methods:
        outcome, looked_in, why = looked_for(sources, method.citekey, method.passage, read)
        found[outcome] += 1
        report = report.with_findings(*_passage_findings(method, outcome, looked_in, why, path))
    return report.with_counts(
        similar_passages=len(review.methods),
        similar_passages_verified=found[VERIFIED],
        similar_passages_failed=found[ABSENT],
        similar_passages_unchecked=found[NO_SOURCE] + found[UNREADABLE],
    )


def _passage_findings(
    method: Method, outcome: str, looked_in: tuple[str, ...], why: str | None, path: Path
) -> list[Finding]:
    context = method.passage[:140]
    found: list[Finding] = []
    if outcome == ABSENT:
        found.append(Finding(
            gate="G7",
            code="similar-passage-not-in-source",
            message=f"{method.named}: the passage is not in the stored copy of "
            f"@{method.citekey}"
            + (f" ({', '.join(looked_in)})" if looked_in else "")
            + (f"; {why}" if why else ""),
            path=path,
            context=context,
            hint="copy the study's words from its stored copy rather than retyping them, "
            "marking words left out with [...]",
        ))  # fmt: skip
    elif outcome in (NO_SOURCE, UNREADABLE):
        found.append(Finding(
            gate="G7",
            code="similar-passage-unchecked",
            severity=WARN,
            message=f"{method.named}: the passage could not be checked: "
            + (f"no stored copy of @{method.citekey}" if outcome == NO_SOURCE
               else f"{outcome} ({why})"),
            path=path,
            context=context,
            hint="store the study under literature/sources/, named by its citation key "
            "(`manuscript-guard sync-sources` copies the studies the review names from Zotero)",
        ))  # fmt: skip
    if passage_words(method.passage) < WORDS:
        found.append(Finding(
            gate="G7",
            code="similar-passage-too-short",
            severity=WARN,
            message=f"{method.named}: the passage holds {passage_words(method.passage)} "
            "word(s), which shows only that they are somewhere in the study",
            path=path,
            context=context,
            hint="copy the sentence of the study that says what it did",
        ))  # fmt: skip
    return found


def check_methods_review(project: Project) -> Report:
    """G12: each appraisal names its standard and domain, each decision a person, and each
    method taken into the plan is cited there, with its standard."""
    review, _report = read_review(project)
    if review is None:
        # What stopped the review being read is said once, by G7's check.
        return Report()
    report = Report()
    path = review_path(project)
    # The plan and the Methods are read only where a method was taken from a study.
    taken = any(m.decision is not None and m.decision.choice in TAKEN for m in review.methods)
    cited, where = _cited(project) if taken else (set(), "")
    for method in review.methods:
        report = report.with_findings(*_appraisal_findings(review, method, path))
        report = report.with_findings(*_decision_findings(review, method, cited, where, path))
    report = report.with_findings(*_redefined(review, path), *_counted(review, path))
    methods = review.methods
    return report.with_counts(
        similar_studies=len(review.studies),
        similar_methods=len(methods),
        # What `check` says it rests on: an appraisal that names a standard and a domain both
        # known, and a decision no model's name signs.
        similar_methods_appraised=sum(_rests_on_a_standard(review, m) for m in methods),
        similar_methods_decided=sum(_decided_by_a_person(m) for m in methods),
        similar_methods_taken=sum(_decided_by_a_person(m) and m.decision.choice in TAKEN
                                  for m in methods),  # fmt: skip
    )


def _rests_on_a_standard(review: Review, method: Method) -> bool:
    """Whether one of the method's appraisals names a standard and a domain of it."""
    for one in method.appraisals:
        standard = review.standard(one.standard)
        if standard is not None and standard.domain(one.domain) is not None:
            return True
    return False


def _decided_by_a_person(method: Method) -> bool:
    from manuscript_guard.gates.literature import _MODEL_NAME

    decision = method.decision
    return decision is not None and not _MODEL_NAME.search(decision.decided_by)


def _appraisal_findings(review: Review, method: Method, path: Path) -> list[Finding]:
    found: list[Finding] = []
    for one in method.appraisals:
        context = " ".join(one.says.split())[:140]
        standard = review.standard(one.standard)
        if not one.standard:
            found.append(Finding(
                gate="G12",
                code="appraisal-without-standard",
                severity=WARN,
                message=f"{method.named}: the appraisal proposed by {one.proposed_by} names no "
                "standard it is judged against",
                path=path,
                context=context,
                hint="name the standard and its domain (data/method_standards.yaml lists the "
                "built-in ones; `standards:` in the review may describe another). A judgement "
                "that rests on no standard is an impression, and a common design can carry a "
                "common bias",
            ))  # fmt: skip
        elif standard is None:
            found.append(Finding(
                gate="G12",
                code="appraisal-standard-unknown",
                severity=WARN,
                message=f"{method.named}: the appraisal names the standard {one.standard!r}, "
                "which the built-in table does not hold and the review does not describe",
                path=path,
                context=context,
                hint="use an id of data/method_standards.yaml, or describe the standard under "
                "`standards:` with its name, its domains and the key it is cited under",
            ))  # fmt: skip
        elif standard.domain(one.domain) is None:
            named = f"the domain {one.domain!r}" if one.domain else "no domain"
            found.append(Finding(
                gate="G12",
                code="appraisal-domain-unknown",
                severity=WARN,
                message=f"{method.named}: the appraisal names {named} of {standard.name}, "
                f"whose domains are: {'; '.join(standard.domains)}",
                path=path,
                context=context,
                hint="name the domain of the standard the judgement is of, as the standard "
                "names it",
            ))  # fmt: skip
    return found


def _decision_findings(
    review: Review, method: Method, cited: set[str], where: str, path: Path
) -> list[Finding]:
    from manuscript_guard.gates.literature import _MODEL_NAME

    decision = method.decision
    if decision is None:
        return []
    found: list[Finding] = []
    if _MODEL_NAME.search(decision.decided_by):
        found.append(Finding(
            gate="G12",
            code="similar-decision-not-human",
            message=f"{method.named}: {decision.decided_by!r} cannot decide whether this study "
            "takes a method",
            path=path,
            hint="an agent may extract the method and propose an appraisal; a named person "
            "decides to adopt, adapt or reject it, and records why",
        ))  # fmt: skip
    if decision.choice not in TAKEN:
        return found
    if method.citekey not in cited:
        found.append(Finding(
            gate="G12",
            code="adopted-method-uncited",
            severity=WARN,
            message=f"{method.named}: decided {decision.choice} by {decision.decided_by}, and "
            f"nothing in {where} cites @{method.citekey}",
            path=path,
            hint=f"cite the study where the plan takes its {method.what}, `[@{method.citekey}]`"
            "; a method taken from another paper is credited to it",
        ))  # fmt: skip
    for standard_id in dict.fromkeys(one.standard for one in method.appraisals if one.standard):
        standard = review.standard(standard_id)
        if standard is None:
            continue
        if standard.citekey is None:
            why = (f"the review gives no citation key for {standard.name} "
                   f"(`standards:`, id {standard.id})")  # fmt: skip
        elif standard.citekey not in cited:
            why = (f"nothing in {where} cites @{standard.citekey}, where it is "
                   "published")  # fmt: skip
        else:
            continue
        found.append(Finding(
            gate="G12",
            code="adopted-standard-uncited",
            severity=WARN,
            message=f"{method.named}: decided {decision.choice}, judged against "
            f"{standard.name}, and {why}",
            path=path,
            hint="cite the methodological source beside the study that applied it"
            + (f" ({standard.found_at})" if standard.found_at else "")
            + "; give its key under `standards:` in the review",
        ))  # fmt: skip
    return found


def _redefined(review: Review, path: Path) -> list[Finding]:
    """A built-in standard the record describes again: its domains stay the table's."""
    from manuscript_guard.methods_review import built_in_standards

    known = built_in_standards()
    return [
        Finding(
            gate="G12",
            code="standard-redescribed",
            severity=WARN,
            message=f"`standards:` describes {ident!r} again, which the built-in table holds; "
            "its name and domains are the table's",
            path=path,
            hint="give a built-in standard only its `citekey`; describe a standard of your own "
            "under an id of its own",
        )
        for ident, entry in review.standards.items()
        if ident in known and (entry.get("name") or entry.get("domains"))
    ]


def _counted(review: Review, path: Path) -> list[Finding]:
    """A note each for the methods not appraised, and those appraised and not decided."""
    methods = review.methods
    found: list[Finding] = []
    bare = sum(not method.appraisals for method in methods)
    if bare:
        found.append(Finding(
            gate="G12",
            code="similar-unappraised",
            severity=INFO,
            message=f"methods of similar studies with no appraisal: {bare} of {len(methods)}",
            path=path,
            hint="judge each against a methodological standard and its domain, not by how "
            "many studies used it (the methods-review skill)",
        ))  # fmt: skip
    waiting = sum(bool(method.appraisals) and method.decision is None for method in methods)
    if waiting:
        found.append(Finding(
            gate="G12",
            code="similar-undecided",
            severity=INFO,
            message=f"methods appraised and not yet decided on: {waiting} of {len(methods)}",
            path=path,
            hint="the author decides each: adopt, adapt or reject, and why",
        ))  # fmt: skip
    return found


def plan_citations(text: str) -> set[str]:
    """The keys a plan's text cites, outside its comments: in a group, `[@a; @b, p. 3]`, or
    narratively, `@a`, as `zotero/citations.py` reads them. A sentence commented out is no
    part of the plan, and its citation credits nothing; nor does a longer key that begins
    with the study's, or an address."""
    return {use.citekey for use in find_citations(blank_comments(text), PLAN_FILE)}


def _cited(project: Project) -> tuple[set[str], str]:
    """The keys the plan cites, and the manuscript's Methods where the manuscript is
    Markdown, with the words a finding names them by. A LaTeX manuscript's Methods are not
    read yet: there the plan's citations are the only ones that count, and the finding says
    so. Nor are they where a manuscript file cannot be read, which is said once of the file:
    this check is G12's, and the plan's gate does not stop for the manuscript."""
    from manuscript_guard.contracts import ContractError
    from manuscript_guard.gates.design import plan_path
    from manuscript_guard.gates.methods import methods_text
    from manuscript_guard.text.reader import LATEX, manuscript_format

    plan = plan_path(project)
    keys: set[str] = set()
    if plan.is_file():
        keys |= plan_citations(plan.read_bytes().decode("utf-8-sig", errors="replace"))
    if manuscript_format(project.path("manuscript")) == LATEX:
        return keys, "design/plan.md (a LaTeX manuscript's Methods are not read yet)"
    try:
        methods = methods_text(project)
    except ContractError:
        return keys, "design/plan.md (a manuscript file could not be read, so its Methods were not)"
    if methods is not None:
        keys |= plan_citations(methods)
    return keys, "design/plan.md or the manuscript's Methods"

