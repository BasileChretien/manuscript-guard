"""Where the paper stands, and what a communication text may say of it.

paper.yaml's `publication:` block records it:

    publication:
      status: accepted          # submitted, accepted, published-online or in-issue
      accepted_on: 2026-11-02
      published_on: 2026-12-01
      doi: 10.1234/example.5678
      url: https://journal.example/article/5678
      embargo_until: 2026-12-01T00:01

A text that links the paper's own DOI or URL before the status says it is online fails
(`comm-status-ahead`): a post that links a DOI the publisher has not yet registered leads
nowhere, and the link is the one exact signal. Words that read as this paper being out only
warn (`comm-status-words`), since no reading of words is exact (Basile, 2026-10-29), and are
read broadly: "our", "this", "these" or "the present" study, paper, trial, findings and the
like, then a verb with any adverb, then "published" or "out" (not "out of"), with no
negation before it; and a headline, "Now published", "Just published", "Out now", "Out
today", "Published:", "Published today, our study ...", but not "Published in 2021, the
...". A DOI is held to its syntax (`comm-doi-malformed`); whether it is registered, and for
this paper, is asked of Crossref by a later step. A link to storage that is neither
persistent nor archived, a shared drive or a bare repository, is a warning
(`comm-link-temporary`).
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
#: This paper's words said to be out, read broadly since they only warn (Basile,
#: 2026-10-29): "our", "this", "these" or "the present", perhaps "new", "latest" and the
#: like, then study, paper, article, work, trial, findings or results, then a verb with any
#: adverb in it, "has now been", "was just", "is", and "published" or "out", not "out of".
_THIS_PAPER_OUT = re.compile(
    r"\b(?:our|this|these|the[ \t]+present)[ \t]+"
    r"(?:(?:new|latest|recent|first|own|full|final)[ \t]+)*"
    r"(?:study|studies|paper|papers|article|articles|work|trial|findings|results)[ \t]+"
    r"(?:(?:has|have|is|are|was|were|been|now|just|finally|officially|today|already)[ \t]+)*"
    r"(?:published\b|out\b(?![ \t]+of\b))",
    re.IGNORECASE,
)
#: A negation before it in its sentence: "It is not true that our study is published."
_NEGATED = re.compile(
    r"\b(?:not|never|no|nor|neither)\b|n['\N{RIGHT SINGLE QUOTATION MARK}]t\b", re.IGNORECASE
)
_LINK = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
#: A headline that says the paper is out, opening a sentence or a post past its marks and
#: emoji: "Now published", "Just published", "Out now", "Out today", and "Published" where
#: a colon, a dash, a stop, a comma or "in", "today", "online" follows, not "Published
#: reports".
_HEADLINE = re.compile(
    r"\A[^\w]*(?:(?P<said>(?:now|just)[ \t]+published\b|out[ \t]+(?:now|today)\b)"
    r"|(?P<published>published)(?=[ \t]*(?:[:!.,\N{EM DASH}\N{EN DASH}-]|\Z)"
    r"|[ \t]+(?:in|today|online|now|this[ \t]+week)\b))",
    re.IGNORECASE,
)
#: After a headline's "Published", what makes it said of other work: "in" and a year, "in
#: 2021", or a clause after a comma that names no work of ours: "Published in JAMA, the
#: ABC trial found", and not "Published today, our study shows".
_IN_A_YEAR = re.compile(r"[ \t]+in[ \t]+(?:\d{4}\b|[^,.]*\b\d{4}\b)")
_OURS = re.compile(r"\b(?:our|this|these|we|my|the[ \t]+present)\b", re.IGNORECASE)


def _other_work(sentence: str, at: int) -> bool:
    if _IN_A_YEAR.match(sentence, at):
        return True
    comma = sentence.find(",", at)
    return comma >= 0 and not _OURS.search(sentence, comma)


def publication(project) -> dict:
    said = project.paper.get("publication")
    return said if isinstance(said, dict) else {}


def is_out(project) -> bool:
    return publication(project).get("status") in OUT


def _dois(text: str) -> list[tuple[str, int]]:
    found = []
    for match in _GIVEN.finditer(text):
        doi = (match["after"] or match["bare"]).rstrip(_TRAILING)
        if match["after"] and "doi.org/" in match.group().lower():
            # A link's query, fragment or closing slash is no part of the DOI it resolves:
            # `https://doi.org/10.1/x?utm_source=bsky` links 10.1/x (fix-only round of #470).
            doi = re.split(r"[?#]", doi, maxsplit=1)[0].rstrip("/").rstrip(_TRAILING)
        found.append((doi, match.start()))
    return found


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def said_published(text: str) -> list[tuple[int, str]]:
    """Where a text's words say this paper is out, with the sentence: links left out, a
    sentence that says so (`_THIS_PAPER_OUT`) with no negation before it, and one that opens
    with a headline (`_HEADLINE`) not said of other work."""
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
        if headline["published"] and _other_work(sentence, headline.end()):
            continue
        found.append((first, " ".join(sentence.split())))
    return found


def _same_url(link: str, url: str) -> bool:
    """Whether a link is the paper's URL: the same, or it and a path, a query or a fragment
    after it, so that `.../a/10` is not `.../a/1`."""
    link, url = _bare_url(link.rstrip(_TRAILING + ">")), _bare_url(url)
    if link.rstrip("/") == url:
        return True
    return link.startswith(url) and link[len(url)] in "/?#"


def _bare_url(url: str) -> str:
    """A URL without its scheme or a `www.`, lower-cased: `http://www.x/a` is `https://x/a`."""
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).rstrip("/")


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
            found.append(Finding(
                GATE, "comm-status-words",
                f"its words read as this paper being out, '{sentence[:120]}', and paper.yaml's "
                f"publication status is {status}",
                severity=WARN, path=path, line=_line(text, at),
                hint="if it says this paper is out, hold it until the paper is online and set "
                "`publication: {status: published-online}`; words are read broadly, and a "
                "sentence about other work is warned too",
            ))  # fmt: skip
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
