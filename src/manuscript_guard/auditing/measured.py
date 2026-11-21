"""The severity `audit` and `compare` give a code whose findings were judged on real papers.

`check` holds a project to the stage it declares (`policy`), and a gate gives each finding
the severity its author chose. A paper that is audited was written without the tool, and a
code can be wrong there more often than it is right: a name from the code that is a
committee's reference, a run of Xs that is a masked value. So where a code's findings were
judged on the corpus of real papers (`docs/corpus.md`), its severity in the two reports
that read such papers is set by how often it was right, by one rule (DESIGN.md, "In an audit,
a code's severity follows how often it was right"; the author's decisions of 2026-11-20):

- lowered to INFO where at least 10 of its warnings and failures were judged, under half of
  them were true, and the false ones came from at least 3 papers;
- raised to WARN, from INFO, where at least 10 were judged and 0.9 or more were true, but
  never a code that says what the project lacks rather than what the paper says.

A code lowered goes back up once a fix measures 0.75 or more. Each entry gives its figures
and the commit of main they were counted on. The table is applied where the two reports take
their findings (`auditing.gates.run_gates` for G6 and G14, `auditing.report` for what it says
of a reference list and of the Abstract's numbers, `comparing.differences` for a sentence
whose claim changed); `check` never reads it, and gives each of these codes what it gave
before.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TypeVar

from manuscript_guard.findings import INFO, WARN


@dataclass(frozen=True)
class Measured:
    """What an audit gives a code, and the figures that decided it: `true` of `judged` of
    its findings, the false ones from `papers` papers. `rules`, for G6's `model-artefact`,
    names the rules of `data/ai_writing.yaml` whose findings it holds for; empty, it holds
    for every finding of the code. `gate` names the gate whose findings were judged, where
    another gives a code of the same name; None, it holds for the code's findings of any."""

    severity: str
    true: int
    judged: int
    papers: int | None
    rules: frozenset[str] = frozenset()
    gate: str | None = None


#: G6's rules that find a bare placeholder, and whose findings were judged: a thing named in
#: brackets, "[url]", "[citation needed]" (`placeholder-slot`), and a word that marks a gap,
#: "xxxx", "XXX", "TBD" (`placeholder-word`). Not the rules of a slot that tells the writer
#: what to put, "[insert the date]", "[describe the cohort]", "[your name]", "[TO BE
#: COMPLETED]", none of whose findings was judged loud; the first of them also finds an
#: instruction in brackets before `placeholder-filler` can, "[fill in later]". Nor
#: `placeholder-filler`, an instruction left for the writer, nor `placeholder-template`, a
#: journal template's instruction to its authors, which has no innocent reading and fails
#: wherever it is read (Basile, 2026-10-21); nor a model's markup or its voice.
BARE_PLACEHOLDERS = frozenset({"placeholder-slot", "placeholder-word"})

MEASURED: dict[str, Measured] = {
    # G14's names from the code: 18 true of 50 judged, the false ones from 8 papers. A
    # project's names come from its own analysis, so `check` warns as before. At d056f71.
    "code-name-in-prose": Measured(INFO, true=18, judged=50, papers=8),
    # G6's bare placeholders: 1 true of 12 judged, the false ones from 4 papers (of the
    # code's 13, the thirteenth a template's instruction). `check` fails them from drafting.
    # At d056f71.
    "model-artefact": Measured(INFO, true=1, judged=12, papers=4, rules=BARE_PLACEHOLDERS),
    # A PDF's reference list whose entries could not be told apart: 13 true of 13 judged.
    # At d056f71.
    "entries-not-told-apart": Measured(WARN, true=13, judged=13, papers=None),
    # A number of the Abstract the audit finds nowhere the paper reports: 8 true of 21
    # judged, the false ones from 5 papers (a number written out as a word, a share the
    # tables give as a proportion, a source's designation, an arXiv identifier). Not G4's
    # code of that name, a journal's Abstract missing, which `check` and an audit with
    # `--journal` give, and which keeps its warning. At 0949b4b.
    "abstract-not-found": Measured(INFO, true=8, judged=21, papers=5, gate="audit"),
    # A changed sentence that may now say the opposite of what it said: 1 true of 17 judged,
    # the false ones from 4 papers, most of them a section rewritten rather than a claim
    # reversed. Not `reworded`'s, which reads one edit of a project's own text. At 0949b4b.
    "claim-negation": Measured(INFO, true=1, judged=17, papers=4, gate="compare"),
}

Found = TypeVar("Found")


#: The words `placeholder-word` finds that tell the writer what to do rather than mark a gap,
#: "TODO", "FIXME", "INSERT_SOURCE_URL", "PASTE_TABLE_2": they fail, as an instruction does.
TO_DO = ("todo", "fixme", "insert_", "paste_")


def _rule(found: object) -> str | None:
    """The G6 rule a finding is of, which its subject opens with (`gates.writing._keyed`):
    "placeholder-word: xxxx"; none where its words tell the writer what to do (`TO_DO`)."""
    subject = getattr(found, "subject", None)
    if not subject:
        return None
    rule, _, words = subject.partition(":")
    return None if words.strip().startswith(TO_DO) else rule


def measured(found: Found) -> Found:
    """`found`, a finding or a report's item, at the severity this table gives its code; as
    it is where the table says nothing of it, or of its gate."""
    entry = MEASURED.get(getattr(found, "code", ""))
    if entry is None or (entry.rules and _rule(found) not in entry.rules) or (
            entry.gate is not None and getattr(found, "gate", None) != entry.gate):
        return found
    return replace(found, severity=entry.severity)  # type: ignore[type-var]


__all__ = ["BARE_PLACEHOLDERS", "MEASURED", "Measured", "measured"]
