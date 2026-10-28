"""Where the paper stands, and what a communication text may say of it.

paper.yaml's `publication:` block records it:

    publication:
      status: accepted          # submitted, accepted, published-online or in-issue
      accepted_on: 2026-11-02
      published_on: 2026-12-01
      doi: 10.1234/example.5678
      url: https://journal.example/article/5678
      embargo_until: 2026-12-01T00:01

A text that says the paper is published, or links its DOI, before the status says it is
online is ahead of the paper (`comm-status-ahead`): a post that links a DOI the publisher has
not yet registered leads nowhere, and an embargo is broken by "published" as by a link. A
DOI is held to its syntax (`comm-doi-malformed`); whether it is registered, and for this
paper, is asked of Crossref by a later step. A link to storage that is neither persistent
nor archived, a shared drive or a bare repository, is a warning (`comm-link-temporary`).
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.communicate import GATE
from manuscript_guard.findings import WARN, Finding

#: The statuses after which the paper is out, and a text may link it.
OUT = frozenset({"published-online", "in-issue"})
STATUSES = ("submitted", "accepted", "published-online", "in-issue")
#: A DOI as the syntax has it (the DOI Handbook, 2.2): the prefix 10., a registrant code of
#: four to nine digits, a slash and a suffix.
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
#: Where a text gives a DOI: whatever follows a resolver or `doi:`, or bare, `10.`, digits
#: and a slash, so that a number, "10.5", is none.
_GIVEN = re.compile(
    r"(?:(?:https?://)?(?<![\w.])(?:dx\.)?doi\.org/|\bdoi:[ \t]*)(?P<after>[^\s<>\"]+)"
    r"|(?<![\w./])(?P<bare>10\.\d+/[^\s<>\"]+)",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?)]}'*_"
#: "published" said of the paper: not "to be published" nor "will be published".
_PUBLISHED = re.compile(r"(?<![Bb]e )\b[Pp]ublished\b")


def publication(project) -> dict:
    said = project.paper.get("publication")
    return said if isinstance(said, dict) else {}


def is_out(project) -> bool:
    return publication(project).get("status") in OUT


def _dois(text: str) -> list[tuple[str, int]]:
    found = []
    for match in _GIVEN.finditer(text):
        doi = (match["after"] or match["bare"]).rstrip(_TRAILING)
        found.append((doi, match.start()))
    return found


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def status_findings(project, path: Path, text: str) -> list[Finding]:
    """What a text's words and links say of the paper's status, against paper.yaml's
    `publication:`; `text` is as printed, its bindings each their display."""
    from manuscript_guard.gates.data_statement import TEMPORARY

    said = publication(project)
    status = said.get("status") or "not given"
    own = str(said.get("doi") or "").lower()
    found = []
    for doi, at in _dois(text):
        if not DOI.match(doi):
            found.append(Finding(
                GATE, "comm-doi-malformed",
                f"{doi!r} is no DOI: a DOI is 10., four to nine digits, a slash and a suffix",
                path=path, line=_line(text, at), context=doi,
                hint="copy the DOI as the publisher or the repository gives it",
            ))  # fmt: skip
        elif own and doi.lower() == own and status not in OUT:
            found.append(_ahead(path, _line(text, at), f"it links the paper's DOI, {doi}", status))
    if status not in OUT:
        for match in _PUBLISHED.finditer(text):
            found.append(_ahead(path, _line(text, match.start()),
                                f"it says '{match.group()}'", status))  # fmt: skip
    for link in TEMPORARY.finditer(text):
        found.append(Finding(
            GATE, "comm-link-temporary",
            f"{link.group()} is storage its owner can change or delete, and a reader who "
            "follows it later may find nothing",
            severity=WARN, path=path, line=_line(text, link.start()), context=link.group(),
            hint="link a persistent copy: the paper's DOI, a repository's DOI or a release",
        ))  # fmt: skip
    return found


def _ahead(path: Path, line: int, what: str, status: str) -> Finding:
    return Finding(
        GATE, "comm-status-ahead",
        f"{what}, and paper.yaml's publication status is {status}: the text is ahead of the "
        "paper",
        path=path, line=line,
        hint="hold the text until the paper is online, and then set `publication: {status: "
        "published-online}` in paper.yaml; or say what is true now, 'accepted in'",
    )  # fmt: skip


def paper_doi_findings(project, paper_path: Path) -> list[Finding]:
    """`comm-doi-malformed` for paper.yaml's own `publication.doi`, which the schema also
    refuses: what `communicate check` would link is the one it reads."""
    doi = publication(project).get("doi")
    if doi is None or (isinstance(doi, str) and DOI.match(doi)):
        return []
    return [Finding(GATE, "comm-doi-malformed",
                    f"paper.yaml's publication.doi, {doi!r}, is no DOI", path=paper_path,
                    hint="write the DOI without its resolver: 10.1234/abcd")]  # fmt: skip
