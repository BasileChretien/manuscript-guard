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
and the commit of main they were counted on, and where they were counted on one format alone
it says which, and holds for findings read from that format alone (the author's decision of
2026-11-23 on a PDF's text). The table is applied where the two reports take
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
    its findings, the false ones from `papers` papers. `gate` names the gate whose findings
    were judged, where another gives a code of the same name; None, it holds for the code's
    findings of any.
    `read_from` names the format of the text the figures were counted on (`PDF`), and the
    entry holds for a finding read from that format alone; None, it holds whatever the
    finding was read from."""

    severity: str
    true: int
    judged: int
    papers: int | None
    gate: str | None = None
    read_from: str | None = None


#: Text the audit read from a PDF (`auditing.gates._Staged.from_pdf`), its paragraphs gone, so
#: that a table's or a legend's words read as prose. What decides is the file the finding was
#: read from: a LaTeX or Word paper's own PDF, audited as a PDF, is one too.
PDF = "PDF"


MEASURED: dict[str, Measured] = {
    # G14's names from the code: 18 true of 50 judged, the false ones from 8 papers. A
    # project's names come from its own analysis, so `check` warns as before. At d056f71.
    "code-name-in-prose": Measured(INFO, true=18, judged=50, papers=8),
    # G6's text a model or a template left behind, every rule of it: 1 true of 30 judged
    # in the reports this table is applied to (an audit, of a paper or of its own PDF, and
    # compare), the false ones from 11 papers. Unfilled placeholder text, 1 of 25 ("xxxx",
    # a "todo"); a chat assistant's register, 0 of 4; a journal template's instruction, 0 of
    # 1 ("Sample table title"). `check`'s own 13 judged were false too. At d056f71 the bare
    # placeholders alone were lowered (1 of 12), a template's instruction and one left for
    # the writer kept failing (Basile, 2026-10-21); every finding of the code is a note now,
    # and `check` fails them from drafting as before. At 27b5cfb (Basile, 2026-11-25, "INFO
    # in audit").
    "model-artefact": Measured(INFO, true=1, judged=30, papers=11),
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
    # G14's short form used before its definition, in text read from a PDF. Lowered at
    # 77abd45db, the PDF's paragraphs gone: 35 true of the 81 reported, the false ones from
    # 17 papers (Basile, 2026-11-23, "INFO on PDFs now"). Measured again with the paragraphs
    # rebuilt for G6 and G14 (#802), at f1bd2fad5: 49 true of the 85 judged findings present
    # on text read from a PDF, 0.576, the false ones from 16 papers, short of the 0.75 a fix
    # must measure for the warning to come back, so it stays a note (Basile, 2026-11-26,
    # "Keep INFO, the 0.75 rule"). From Word, LaTeX or Markdown, where 111 of the 166
    # reported were true, it keeps its warning.
    "abbreviation-used-before-defined": Measured(INFO, true=49, judged=85, papers=16,
                                                 gate="G14", read_from=PDF),
}

Found = TypeVar("Found")


def measured(found: Found, *, read_from: str | None = None) -> Found:
    """`found`, a finding or a report's item, at the severity this table gives its code; as
    it is where the table says nothing of it, of its gate, or of the format it was read from
    (`read_from`, `PDF` for text read from a PDF)."""
    entry = MEASURED.get(getattr(found, "code", ""))
    if entry is None or (
            entry.gate is not None and getattr(found, "gate", None) != entry.gate) or (
            entry.read_from is not None and read_from != entry.read_from):
        return found
    return replace(found, severity=entry.severity)  # type: ignore[type-var]


__all__ = ["MEASURED", "PDF", "Measured", "measured"]
