"""The publisher's proof, compared with what the author sent.

manuscript-guard's guarantees stop at the document the author sends: every number in it is
the one the analysis emitted, every reference checked. The proof the journal sends back is
typeset from that document by people and programs that can change a digit, drop a minus,
swap two cells, renumber a reference or lose an affiliation, and the author has a day or
two to find it by eye. `manuscript-guard proof <proof>` reads the proof's text and holds it
to the document in the submission pack, part by part (`compare`), and the title page to
`authors.yaml` (`front`), and lists what the author has to ask the production office to
correct, with the page and the line. It sends nothing: the reply is the author's.

What it compares, how, and what it cannot see are in DESIGN.md, "The publisher's proof is
held to what was sent".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.proof.compare import CORRECTION, Change, Comparison, best
from manuscript_guard.proof.reading import Reading, UnreadableProof, readings
from manuscript_guard.proof.sent import NotSent, document_for, provenance, read_sent

__all__ = ["NotSent", "ProofReport", "UnreadableProof", "check_proof"]

#: Below this share of what was sent found in the proof, the proof is not of this document.
LEAST_FOUND = 0.3
#: The most words a line of the title page holds for what else it adds to go unreported.
QUIET = 25


@dataclass(frozen=True)
class ProofReport:
    proof: Path
    document: Path
    reading: Reading
    #: What is said of the document compared with: the pack, the approvals, the source.
    provenance: tuple[str, ...]
    changes: tuple[Change, ...]
    not_compared: tuple[str, ...]
    found: int
    total: int

    @property
    def corrections(self) -> tuple[Change, ...]:
        return tuple(change for change in self.changes if change.kind == CORRECTION)


class NotThisProof(Exception):
    """The proof reads as too little of the document for the comparison to mean anything."""


def check_proof(
    project: Project, proof: Path, *, against: Path | None = None, supplementary: bool = False
) -> ProofReport:
    """Compare a proof with what was sent. Raises `NotSent`, `UnreadableProof` or
    `NotThisProof` where there is nothing to compare, or no comparison that means
    anything."""
    from manuscript_guard.proof.front import check_front
    from manuscript_guard.proof.origin import origins

    document = document_for(project, against, supplementary)
    sent = read_sent(document)
    if not sent.parts:
        raise NotSent(f"{document.name} holds no text to compare the proof with")
    found = readings(proof)
    chosen = best(sent, found)
    reading = chosen.reading
    front: list[Change] = []
    quiet: frozenset[int] = frozenset()
    if not supplementary:
        front, used = check_front(project, reading)
        # A line that holds the title page's words and much else is a reader's whole
        # column: what else it holds is still reported.
        quiet = frozenset(at for at in used if len(reading.lines[at].text.split()) <= QUIET)
    # By the module, which `from manuscript_guard.proof import compare` names: the function
    # of the same name, imported here, would stand in its place.
    from manuscript_guard.proof import compare as comparing

    result: Comparison = comparing.compare(
        sent, reading, origins(project, supplementary=supplementary), quiet
    )
    if result.total and result.found < LEAST_FOUND * result.total:
        share = round(100 * result.found / result.total)
        raise NotThisProof(
            f"{proof.name} prints {share}% of {document.name}, read with {reading.reader}: it "
            "is not this document's proof, or its text could not be read in order"
        )
    changes = tuple(sorted((*front, *result.changes), key=lambda c: (c.page or 0, c.at)))
    return ProofReport(
        proof=proof,
        document=document,
        reading=reading,
        provenance=tuple(provenance(project, document, sent.stamp)),
        changes=changes,
        not_compared=sent.not_compared,
        found=result.found,
        total=result.total,
    )
