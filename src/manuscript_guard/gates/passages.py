"""G7: a cited statement's supporting passage is in the work it cites.

`literature/passages.yaml` holds, for a sentence that cites a work, the passage of that work
that supports it (`literature/passages.py`). Each passage is looked for in the work's stored
files, word for word, with words left out read as a quotation in the prose reads them. One
that is in none of them fails (`passage-not-in-source`): it was retyped, or remembered, or
taken from another paper. One whose work has no stored copy that can be read is a warning
(`passage-unchecked`), and one of fewer than four words shows only that the words are
somewhere in the work (`passage-too-short`). A passage whose sentence is no longer in the
manuscript, or no longer cites the work, is stale, and a note says so and which sentence it
may now be (`passage-stale`).

A person's judgement of it: a model's name may not sign it (`judgement-not-human`), a passage
judged not to support its sentence fails from internal-review (`passage-does-not-support`),
and one judged to support it in part is a warning (`passage-partly-supports`).

The sentences that cite and carry no passage of any work they cite are counted: one note
while drafting, one warning from internal-review, never a failure, since a citation of the
software used or of where a method comes from needs no passage (Basile, 2026-10-20).
`manuscript-guard passages --missing` lists them.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.checking.produce import cited_sentences, citing_document
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.literature.passages import (
    ABSENT,
    CHANGED,
    DOES_NOT,
    NO_SOURCE,
    PARTLY,
    PASSAGES_FILE,
    UNCITED,
    UNREADABLE,
    VERIFIED,
    Checked,
    Survey,
    passage_words,
    read_passages,
    survey,
)
from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, stage_index

GATE = "G7"
#: The fewest words a passage holds for it to say more than that its words are in the work.
WORDS = 4


def survey_of(project: Project) -> tuple[Survey, Report]:
    """The manuscript's cited sentences and the project's passages, matched and looked for,
    with what stopped the passages file being read."""
    passages, report = read_passages(project.path("literature"))
    documents = [
        citing_document(path, read_text(path))
        for path in source_files(project.path("manuscript"))
    ]
    sources = project.path("literature") / "sources"
    return survey(sources, cited_sentences(documents), passages), report


def check_passages(project: Project, stage: str = DRAFTING) -> Report:
    """Each passage held to its source and its sentence, and the statements with none counted."""
    found, report = survey_of(project)
    path = project.path("literature") / PASSAGES_FILE
    for checked in found.passages:
        report = report.with_findings(*_findings(checked, path))
    statements = found.statements
    carrying = sum(found.carries(index) for index, _cited in statements)
    missing = len(statements) - carrying
    if missing:
        due = stage_index(stage) >= stage_index(INTERNAL_REVIEW)
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="statements-without-passage",
                severity=WARN if due else INFO,
                message="cited statements with no passage of a work they cite: "
                f"{missing} of {len(statements)}",
                path=path,
                hint="`manuscript-guard passages --missing` lists them; record in "
                f"literature/{PASSAGES_FILE} the words of the cited work that support each, "
                "copied from its stored source. A citation of software, or of where a method "
                "comes from, needs none",
            )
        )
    checked = found.passages
    return report.with_counts(
        cited_statements=len(statements),
        cited_statements_with_passage=carrying,
        passages_verified=sum(c.found == VERIFIED for c in checked),
        passages_failed=sum(c.found == ABSENT for c in checked),
        passages_unchecked=sum(c.found in (NO_SOURCE, UNREADABLE) for c in checked),
        passages_stale=sum(c.stale is not None for c in checked),
        passages_judged=sum(c.passage.support is not None for c in checked),
    )


def _findings(checked: Checked, path: Path) -> list[Finding]:
    """What G7 says of one passage."""
    passage = checked.passage
    found: list[Finding] = []
    context = passage.passage[:140]
    if checked.found == ABSENT:
        found.append(Finding(
            gate=GATE,
            code="passage-not-in-source",
            message=f"{passage.named}: the passage is not in the stored source of "
            f"@{passage.citekey} ({', '.join(checked.looked_in)})"
            + (f"; {checked.why}" if checked.why else ""),
            path=path,
            context=context,
            hint="copy the words from the stored source rather than retyping them, marking "
            "words left out with [...]; or cite the work that says them",
        ))  # fmt: skip
    elif checked.found in (NO_SOURCE, UNREADABLE):
        found.append(Finding(
            gate=GATE,
            code="passage-unchecked",
            severity=WARN,
            message=f"{passage.named}: the passage could not be checked: "
            + (f"no stored source of @{passage.citekey}" if checked.found == NO_SOURCE
               else f"{checked.found} ({checked.why})"),
            path=path,
            context=context,
            hint="store the work under literature/sources/, named by its citation key "
            "(`manuscript-guard sync-sources` copies it from Zotero)",
        ))  # fmt: skip
    if passage_words(passage.passage) < WORDS:
        found.append(Finding(
            gate=GATE,
            code="passage-too-short",
            severity=WARN,
            message=f"{passage.named}: the passage holds {passage_words(passage.passage)} "
            "word(s), which shows only that they are somewhere in the work",
            path=path,
            context=context,
            hint="copy the sentence of the work that says what the citing sentence says",
        ))  # fmt: skip
    found += _judged(checked, path)
    if checked.stale is not None:
        found.append(_stale(checked, path))
    return found


def _judged(checked: Checked, path: Path) -> list[Finding]:
    """What G7 says of a person's judgement of a passage."""
    from manuscript_guard.gates.literature import _MODEL_NAME

    passage = checked.passage
    if passage.support is None:
        return []
    found: list[Finding] = []
    if _MODEL_NAME.search(passage.judged_by or ""):
        found.append(Finding(
            gate=GATE,
            code="judgement-not-human",
            message=f"{passage.named}: {passage.judged_by!r} cannot judge whether a passage "
            "supports a sentence",
            path=path,
            hint="an agent may draft the passage; a named person reads it against the "
            "sentence and records the judgement",
        ))  # fmt: skip
    if checked.stale is not None:
        # A judgement of words the manuscript no longer has: the stale note says so.
        return found
    if passage.support == DOES_NOT:
        found.append(Finding(
            gate=GATE,
            code="passage-does-not-support",
            message=f"{passage.named}: {passage.judged_by} judged on {passage.judged_on} that "
            "the passage does not support the sentence",
            path=path,
            context=" ".join(passage.sentence.split())[:140],
            hint="reword the sentence to say what the work says, find the passage that "
            "supports it, or cite another work",
        ))  # fmt: skip
    elif passage.support == PARTLY:
        found.append(Finding(
            gate=GATE,
            code="passage-partly-supports",
            severity=WARN,
            message=f"{passage.named}: {passage.judged_by} judged on {passage.judged_on} that "
            "the passage supports the sentence in part",
            path=path,
            context=" ".join(passage.sentence.split())[:140],
            hint="say in the sentence only what the work says, or cite the work that says the "
            "rest",
        ))  # fmt: skip
    return found


def _stale(checked: Checked, path: Path) -> Finding:
    """The note on a passage whose sentence the manuscript no longer has, or no longer cites
    its work."""
    passage = checked.passage
    if checked.stale == UNCITED:
        why = f"its sentence no longer cites @{passage.citekey}"
    elif checked.stale == CHANGED and checked.near is not None:
        shown = " ".join(checked.near.text.split())
        shown = shown if len(shown) <= 120 else shown[:117] + "..."
        where = f"{checked.near.path.name}, paragraph at line {checked.near.line}"
        why = f"its sentence was reworded; it may now read {shown!r} ({where})"
    else:
        why = f"no sentence of the manuscript citing @{passage.citekey} reads so"
    judged = (
        f"; {passage.judged_by}'s judgement ({passage.support}) was of the old words"
        if passage.support is not None else ""
    )  # fmt: skip
    return Finding(
        gate=GATE,
        code="passage-stale",
        severity=INFO,
        message=f"{passage.named} belongs to no sentence: {why}{judged}",
        path=path,
        hint="write the sentence as the manuscript now has it, and read the passage against "
        "it again; or remove the entry",
    )
