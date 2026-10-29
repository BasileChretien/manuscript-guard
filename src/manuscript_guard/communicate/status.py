"""Where the paper stands, and what a communication text may say of it.

paper.yaml's `publication:` block records it:

    publication:
      status: accepted          # submitted, accepted, published-online or in-issue
      accepted_on: 2026-11-02
      published_on: 2026-12-01
      doi: 10.1234/example.5678
      url: https://journal.example/article/5678
      embargo_until: 2026-12-01T00:01

A text that says this paper is out, or links its DOI or its URL, before the status
says it is online is ahead of the paper (`comm-status-ahead`): a post that links a DOI the
publisher has not yet registered leads nowhere, and an embargo is broken by "our study is
published" as by a link. One form is read and the rest refused (round 2 of #470): "our",
"this" or "the present" study, paper, article or work, then "published" or "out", at once
or after "has been", "is", "was", "is now" or "was just", with no negation before it; a
headline opening a sentence, "Now published", "Just published", "Out now", "Out today" or
"Published:", but not "Published in 2021, ..."; and the paper's own DOI or URL. A DOI is
held to its syntax
(`comm-doi-malformed`); whether it is registered, and for this paper, is asked of Crossref
by a later step. A link to storage that is neither persistent nor archived, a shared drive
or a bare repository, is a warning (`comm-link-temporary`).
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
#: This paper said to be out, in the one form read (round 2 of #470): "our", "this" or "the
#: present" study, paper, article or work, then at once, or after "has been", "is", "was",
#: "is now" or "was just", "published" or "out". Anything between, "our findings agree with
#: published reports", "we published the protocol", is not read, nor one after a negation.
_THIS_PAPER_OUT = re.compile(
    r"\b(?:our|this|the[ \t]+present)[ \t]+(?:study|paper|article|work)[ \t]+"
    r"(?:(?:has[ \t]+been|is[ \t]+now|was[ \t]+just|is|was)[ \t]+)?(?:published|out)\b",
    re.IGNORECASE,
)
#: A negation before it in its sentence: "It is not true that our study is published."
_NEGATED = re.compile(
    r"\b(?:not|never|no|nor|neither)\b|n['\N{RIGHT SINGLE QUOTATION MARK}]t\b", re.IGNORECASE
)
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
#: A headline that says the paper is out, opening a sentence or a post past its marks and
#: emoji: "Now published", "Just published", "Out now", "Out today", and "Published" where
#: a colon, a dash, a stop or "in", "today", "online" follows, not "Published reports".
_HEADLINE = re.compile(
    r"\A[^\w]*(?:(?P<said>(?:now|just)[ \t]+published\b|out[ \t]+(?:now|today)\b)"
    r"|(?P<published>published)(?=[ \t]*(?:[:!.\N{EM DASH}\N{EN DASH}-]|\Z)"
    r"|[ \t]+(?:in|today|online|now|this[ \t]+week)\b))",
    re.IGNORECASE,
)
#: After a headline's "Published", what makes it said of other work: "in" and a year, "in
#: 2021", or a clause after a comma, "Published in JAMA, the ABC trial found".
_OTHER_WORK = re.compile(r"[ \t]+in[ \t]+(?:\d{4}\b|[^,.]*\b\d{4}\b)|[^.!?]*,")


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


def said_published(text: str) -> list[tuple[int, str]]:
    """Where a text says this paper is out, with the sentence: links left out, a sentence
    that says so in the one form read (`_THIS_PAPER_OUT`) with no negation before it, and
    one that opens with a headline (`_HEADLINE`) not said of other work."""
    from manuscript_guard.claims import sentence_spans

    unlinked = _LINK.sub(lambda found: " " * len(found.group()), text)
    found = []
    for _piece, first, end in sentence_spans(unlinked):
        sentence = unlinked[first:end]
        said = _THIS_PAPER_OUT.search(sentence)
        if said is not None and not _NEGATED.search(sentence, 0, said.start()):
            found.append((first + said.start(), " ".join(sentence.split())))
            continue
        headline = _HEADLINE.match(sentence)
        if headline is None:
            continue
        if headline["published"] and _OTHER_WORK.match(sentence, headline.end()):
            continue
        found.append((first, " ".join(sentence.split())))
    return found


def _same_url(link: str, url: str) -> bool:
    """Whether a link is the paper's URL: the same, or it and a path, a query or a fragment
    after it, so that `.../a/10` is not `.../a/1`."""
    link = link.rstrip(_TRAILING).lower()
    if link.rstrip("/") == url:
        return True
    return link.startswith(url) and link[len(url)] in "/?#"


def status_findings(project, path: Path, text: str) -> list[Finding]:
    """What a text's words and links say of the paper's status, against paper.yaml's
    `publication:`; `text` is as printed, its bindings each their display."""
    from manuscript_guard.gates.data_statement import TEMPORARY

    said = publication(project)
    status = said.get("status") or "not given"
    own = str(said.get("doi") or "").lower()
    url = str(said.get("url") or "").rstrip("/").lower()
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
        if url:
            for link in _LINK.finditer(text):
                if _same_url(link.group(), url):
                    what = f"it links the paper's URL, {link.group()}"
                    found.append(_ahead(path, _line(text, link.start()), what, status))
        for at, sentence in said_published(text):
            what = f"it says this paper is published, '{sentence[:120]}'"
            found.append(_ahead(path, _line(text, at), what, status))
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
