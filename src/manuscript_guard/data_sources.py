"""The datasets that could answer the question, and how each is reached.

`design/data_sources.yaml` is written with the author, by the data-sources skill: the
question and what the data must hold, as the author states them first; the datasets
considered, each with its custodian, what it covers, how it is reached and on what terms,
every access claim with the words of the page it was read from (stored as text in
`design/data_sources/pages/`) or with the person who said it; the ranking, the decision and
who made it, and what came of each request for access. The gates read it offline; nothing
here opens a connection.

What the record says of the chosen sources is held against three things the paper says
elsewhere: `paper.yaml`'s `custodian:`, the plan's Population or Data source section, and the
Data availability statement. The words the statement is read for are here, beside the
record, so that one reading of them serves the gate and the tests.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.journal_quotes import _on_page

RECORD = Path("design") / "data_sources.yaml"
PAGES = Path("design") / "data_sources" / "pages"
MESSAGES = Path("design") / "data_sources" / "messages"

#: Routes by which anyone may have the data, once they have asked for nothing but an account.
OPEN_ROUTES = frozenset({"open-download", "registration"})
#: Routes on which somebody decides, or is paid, before the data are had.
RESTRICTED_ROUTES = frozenset({"application", "data-use-agreement", "authors",
                               "commercial-licence"})  # fmt: skip

#: The fields of a candidate under `access:` and `terms:`: each one set is a claim about how
#: the data are reached, and is to be backed by a claim in `claims:` that names it.
ACCESS_FIELDS = ("route", "steps", "cost", "delay")
TERMS_FIELDS = ("licence", "redistribution", "minimum_cell_count", "restricts_sending",
                "citation")  # fmt: skip

#: A statement that the data are had by asking: "on request", "upon reasonable request",
#: "on a justified request", "from the corresponding author".
ON_REQUEST = re.compile(
    r"\b(?:up)?on\s+(?:an?\s+)?(?:(?:reasonable|justified|justifiable|written|formal|"
    r"motivated|appropriate|scientific)\s+)?requests?\b"
    r"|\bfrom\s+the\s+(?:corresponding|first|last|senior|lead)\s+authors?\b"
    r"|\bby\s+(?:contacting|e-?mailing|writing\s+to)\s+the\s+(?:corresponding|first|last|"
    r"senior|lead)\s+authors?\b",
    re.IGNORECASE,
)

#: A statement that anyone may have the data: "publicly available", "freely accessible",
#: "available for download", "in the public domain".
OPENLY = re.compile(
    r"\b(?:publicly|openly|freely)\s+(?:(?:and\s+)?(?:freely|openly|publicly)\s+)?"
    r"(?:available|accessible|downloadable|obtainable)\b"
    r"|\bavailable\s+(?:publicly|openly|freely|to\s+the\s+public|for\s+(?:free\s+)?download)\b"
    r"|\bin\s+the\s+public\s+domain\b",
    re.IGNORECASE,
)

#: A word that turns what follows it in its clause into its opposite: "are not publicly
#: available", "cannot be made publicly available", "neither ... nor publicly available",
#: "no patient-level data are publicly available".
NEGATION = re.compile(
    r"\b(?:not|cannot|never|neither|nor|no|none|unable|without)\b|n't\b", re.IGNORECASE
)
#: Where a clause starts, for the negation before a phrase: a semicolon or a colon, or a word
#: that turns from one clause to the next ("cannot be shared, but are available on request").
#: Not a comma, a bracket or a dash, which as often set an aside between a denial and what it
#: denies: "are not, however, publicly available" (round 1 of #384).
CLAUSE = re.compile(r"[;:]|\b(?:but|whereas|although|though)\b", re.IGNORECASE)
#: How many words before a phrase a negation can stand and still be its own: enough for an
#: aside of a few words between them.
NEGATION_WORDS = 8

#: What a sentence that names no source is about, for it to be said of the data.
DATA_WORD = re.compile(r"\bdata(?:sets?|bases?)?\b", re.IGNORECASE)
#: Where one sentence of a statement ends and the next begins: a stop and a space before
#: anything but a small letter, which goes on after "e.g." and "et al.", or a blank line.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?![a-z])|\n[ \t]*\n")


def record_path(project: Project) -> Path:
    return project.root / RECORD


def page_path(project: Project, page: str) -> Path:
    return project.root / PAGES / page


def candidates_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Each candidate by its id; of two with one id, the first."""
    found: dict[str, dict[str, Any]] = {}
    for candidate in document.get("candidates") or []:
        found.setdefault(candidate["id"], candidate)
    return found


def chosen(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The candidates the decision chose, in its order, those it names that exist."""
    by_id = candidates_by_id(document)
    ids = (document.get("decision") or {}).get("chosen") or []
    return [by_id[source] for source in ids if source in by_id]


def route(source: dict[str, Any]) -> str | None:
    return (source.get("access") or {}).get("route")


def names(source: dict[str, Any]) -> list[str]:
    """What a source may be called in the text: its name, each other name, each identifier."""
    called = [source["name"], *(source.get("also_known_as") or [])]
    called += [identifier["id"] for identifier in source.get("identifiers") or []]
    return [name for name in called if name.strip()]


def named(text: str, source: dict[str, Any]) -> bool:
    """Whether the text names the source by any of its names, as the words they are: folded
    for case, spacing, line breaks and typography, and neither the end of a longer word nor
    the start of one."""
    return any(_on_page(text, name) for name in names(source))


def sentences(text: str) -> list[str]:
    """The statement's sentences, each on one line."""
    return [" ".join(part.split()) for part in _SENTENCE_END.split(text) if part.strip()]


def says(sentence: str, phrase: re.Pattern[str]) -> bool:
    """Whether the sentence says the phrase, and not its opposite: a negation in the same
    clause, a few words before it, turns "publicly available" into "not publicly available"."""
    for found in phrase.finditer(sentence):
        before = sentence[: found.start()]
        clause = CLAUSE.split(before)[-1]
        if NEGATION.search(" ".join(clause.split()[-NEGATION_WORDS:])) is None:
            return True
    return False


def route_differs(statement: str, sources: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Each chosen source the statement says is reached otherwise than its record says, with
    what it says: `on request` of a source anyone may download, `publicly` of one somebody
    decides on. A sentence is said of the sources it names, or, naming none, of every chosen
    source where they are all reached one way and the sentence speaks of data. A statement
    that also says the open source is openly available is taken to ask for something else,
    the analysis files or the code, when it says "on request"."""
    open_said: set[str] = set()
    request_said: set[str] = set()
    public_said: set[str] = set()
    for sentence in sentences(statement):
        about = _about(sentence, sources)
        if not about:
            continue
        ids = {source["id"] for source in about}
        if says(sentence, OPENLY):
            open_said |= ids
            public_said |= {s["id"] for s in about if route(s) in RESTRICTED_ROUTES}
        if says(sentence, ON_REQUEST):
            request_said |= {s["id"] for s in about if route(s) in OPEN_ROUTES}
    differs = [(source_id, "on request") for source_id in request_said - open_said]
    differs += [(source_id, "publicly") for source_id in public_said]
    order = [source["id"] for source in sources]
    return sorted(differs, key=lambda item: (order.index(item[0]), item[1]))


def _about(sentence: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The sources a sentence is said of: those it names, all on one side of the line between
    open and restricted; or, naming none and speaking of data, every source, if all are on
    one side. A sentence that names an open source and a restricted one is about neither."""
    judged = [source for source in sources if route(source) in OPEN_ROUTES | RESTRICTED_ROUTES]
    about = [source for source in judged if named(sentence, source)]
    if not about:
        named_any = any(named(sentence, source) for source in sources)
        if named_any or not DATA_WORD.search(sentence):
            return []
        about = judged
    sides = {route(source) in OPEN_ROUTES for source in about}
    return about if len(sides) == 1 else []


__all__ = [
    "ACCESS_FIELDS",
    "MESSAGES",
    "NEGATION",
    "ON_REQUEST",
    "OPENLY",
    "OPEN_ROUTES",
    "PAGES",
    "RECORD",
    "RESTRICTED_ROUTES",
    "TERMS_FIELDS",
    "candidates_by_id",
    "chosen",
    "named",
    "names",
    "page_path",
    "record_path",
    "route",
    "route_differs",
    "says",
    "sentences",
]
