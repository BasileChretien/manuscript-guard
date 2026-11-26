"""G4: the statements every paper makes, and no heading with nothing under it.

A paper written for BMJ Open (2026-11-26) built with four headings and nothing under them:
"Data availability statement", "Ethics statements", "Disclaimer" and "Contributors, funding and
competing interests" each held only an HTML comment saying what was still to be written, which
the build does not print. `check` passed at the drafting stage. G4 asked only for the
statements a journal's profile lists, and an empty heading is a match for its pattern. So two
findings, each a note before the drafting stage, a warning while the paper is drafted and a
failure from internal review on (the author's rule, 2026-11-26):

- `section-empty`: a heading of the main text or the supplement under which nothing is
  printed before the next heading of its level or above: no text, or only HTML comments, a
  link's reference definition (`[//]: # (to confirm)`, Markdown's comment) and white space, or
  a placeholder G6 does not fail ("TO CONFIRM", "To be completed", "Pending"). A placeholder
  G6 fails as `model-artefact` ("TBD", "TODO", "XXX", "[Placeholder]", "[TO BE COMPLETED]")
  is something printed, and its gap is G6's finding alone. A heading whose subsections print
  something is not empty. One gap is one finding: a heading empty only through its empty
  subsections is not said, its subsections are. The reference list's heading is printed
  under, since the build puts the bibliography there, and so is the last heading of the main
  text or the supplement when its title ends in "references" or "bibliography"
  ("Supplementary references"), where pandoc puts it; a heading with no title is passed over.
- `declaration-missing`: the manuscript has no statement of one of the kinds every paper
  makes, where no journal's profile says which statements the journal asks for: data
  availability, ethics, funding, competing interests, author contributions, and AI use where
  a record shows a model at work or `authors.yaml` declares a tool under `ai_use`
  (`gates/ai_use.wanted`). The main text and the supplement are read, as G4 reads the
  declarations. A statement is a heading or a paragraph's label of its kind with words printed
  after it, a placeholder not among them: the headings of `data/disclosures.yaml` for
  funding, interests, ethics and contributions, as G4 reads the declarations, the
  Acknowledgements among the funding statement's; the Data availability statement's, in the
  forms journals ask for ("Data availability", "Code and data availability", "Data,
  Materials, and Software Availability", "Data accessibility"), or the profile's own; the
  AI-use statement's (`ai_use.default_places`). An ethics statement may also be a sentence of
  the Methods that holds the words of its heading, or a sentence anywhere that says no
  approval was needed (`no_approval`, as G4 reads a denial); and any of them a sentence of a
  Declarations section that holds the words of its kind's heading. A label's own words are no
  sentence of either, and a CRediT role ("Funding acquisition") or an item of the ICMJE form
  states no funding. A label is the words a paragraph opens with before a colon ("**Funding:**",
  "Funding:"), or a short paragraph wholly in emphasis with no stop ("**Funding**"), or one
  whose words are only a statement's title, whatever stop ends it ("**Funding.**",
  "*Competing interests.*"); one wholly in emphasis that ends in a stop and says more ("*The
  authors declare no competing interests.*") is a sentence, a statement of what its words
  name.

A kind whose only heading is empty is said once, by `section-empty`. Where the target
journal's profile lists required statements, they are the journal's, read from its page, and
`missing-required-statement` asks for them: this check then asks for none of its own, so that
a kind is never asked for twice, nor asked for against the journal's own list. Its empty
headings are still said. And one gap is one finding with the notes of the other checks too:
where this asks for the funding, competing interests or AI-use statement, G4's notes
`funding-not-stated`, `interests-not-stated` and `ai-use-not-stated` are not raised
(`asked_for`), and what they said of the records is in this finding's hint.

English only, as the declarations are read. A LaTeX manuscript's statements are read in its
printed view; its headings are not checked for emptiness (DESIGN.md, Known gaps).
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.text.blocks import find_headings, scannable
from manuscript_guard.text.masking import blank, front_matter_end, html_comments, metadata_blocks
from manuscript_guard.text.sections import Section, split_sections

GATE = "G4"
EMPTY = "section-empty"
MISSING = "declaration-missing"

DATA, ETHICS, FUNDING, INTERESTS, CONTRIBUTIONS, AI_USE = (
    "data", "ethics", "funding", "interests", "contributions", "ai_use")  # fmt: skip
#: The kinds of statement every paper makes, in the order they are said.
KINDS = (DATA, ETHICS, FUNDING, INTERESTS, CONTRIBUTIONS, AI_USE)
#: What each is called in a finding.
NAMES = {
    DATA: "data availability statement",
    ETHICS: "ethics statement",
    FUNDING: "funding statement",
    INTERESTS: "competing interests statement",
    CONTRIBUTIONS: "author contributions statement",
    AI_USE: "AI-use statement",
}
#: The usual heading of each kind, as a finding suggests it.
USUAL = {
    DATA: "Data availability",
    ETHICS: "Ethics",
    FUNDING: "Funding",
    INTERESTS: "Competing interests",
    CONTRIBUTIONS: "Author contributions",
    AI_USE: "Use of AI",
}
#: What to write, for each kind.
WRITE = {
    DATA: "say where the data and the code can be had, or why they cannot be shared",
    ETHICS: "name the committee that approved the study and its reference, or say why no "
    "approval was needed",
    FUNDING: "name each funder and grant, or say that the work received no funding",
    INTERESTS: "declare each author's competing interests, or say that there are none",
    CONTRIBUTIONS: "say what each author did, in CRediT's roles where the journal uses them",
    AI_USE: "name each AI tool and what it did; `manuscript-guard review --ai-use` lists what "
    "the records show",
}

#: The words of a Data availability statement's title, in the forms journals ask for: "Data
#: availability", "Data and code availability", "Code and data availability" (Copernicus),
#: "Data, Materials, and Software Availability" (PNAS), "Data accessibility", "Data sharing",
#: "Availability of data and materials" (BMC). Each names data: "Availability of code" is no
#: data statement (round 2 of #819).
_DATA_TITLE = (
    r"(?:(?:code|software) and )?data(?:,? (?:and )?(?:code|materials?|software))*,? "
    r"(?:availability|accessibility|sharing)"
    r"|availability of (?:the )?(?:(?:code|software) and (?:the )?)?data"
)
#: The same as a heading or a label opens with it, its number aside, and in a sentence.
_DATA_HEADING = re.compile(rf"^[\W\d]*(?:{_DATA_TITLE})\b", re.IGNORECASE)
_DATA_WORDS = re.compile(rf"\b(?:{_DATA_TITLE})\b", re.IGNORECASE)
#: What a section or a label holds that says only that its text is still to come: read whole,
#: its marks and stops aside. One G6 already fails as `model-artefact` ("TBD", "XXX",
#: "[Placeholder]", "[TO BE COMPLETED]") is no placeholder here: it is something printed, and
#: its gap is G6's finding alone (`_placeholder`).
_PLACEHOLDER = re.compile(
    r"(?:to (?:be )?(?:confirm(?:ed)?|check(?:ed)?|complet(?:e|ed)|writ(?:e|ten)"
    r"|fill(?:ed)?(?: in)?|add(?:ed)?|decided?|determined|provided|supplied)"
    r"(?: (?:with|by|from) the authors?)?|placeholder|pending)",
    re.IGNORECASE,
)
#: A link's reference definition, which prints nothing: `[//]: # (to confirm)`, the idiom for
#: a comment in Markdown, and `[label]: <url> "title"`. Not a footnote's, `[^1]: ...`, which
#: prints.
_DEFINITION = re.compile(
    r"(?m)^ {0,3}\[(?!\^)[^\]\n]+\]:[ \t]*\S+"
    r"(?:[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'|\([^)\n]*\)))?[ \t]*$"
)
#: A title the bibliography is printed under besides the reference list's own, as the last
#: heading of its document, where pandoc puts the bibliography: one that ends in its word,
#: "Supplementary references", "Additional references" (round 2 of #819).
_REFERENCES_LAST = re.compile(
    r"\b(?:references|bibliography|works cited|literature cited|reference list)\W*$",
    re.IGNORECASE,
)
#: A supplement's number before a title: "S4.", "S2.1".
_SUPPLEMENT_NUMBER = re.compile(r"^\s*S\d+(?:\.\d+)*\.?\s+")
#: The kinds G4's reading of the declarations knows by their headings and labels.
_DISCLOSED = (FUNDING, INTERESTS, ETHICS, CONTRIBUTIONS)
STATED, HEADED_EMPTY = "stated", "empty"


def _placeholder(text: str) -> bool:
    """Whether `text` says only that its text is still to come, in words G6 does not fail."""
    words = re.sub(r"[\W_]+", " ", text).strip()
    return (bool(words) and _PLACEHOLDER.fullmatch(words) is not None
            and not _g6_fails(text))  # fmt: skip


@cache
def _g6_rules() -> object:
    from manuscript_guard.gates.writing import load_rules

    return load_rules()


def _g6_fails(text: str) -> bool:
    """Whether G6 fails something in `text` as `model-artefact`, as it reads the manuscript."""
    from manuscript_guard.gates.writing import artefacts_in

    return next(artefacts_in(_g6_rules(), text, manuscript=True), None) is not None


def _says(text: str) -> bool:
    """Whether `text`, as printed, says something: words that are no placeholder."""
    return bool(text.strip()) and not _placeholder(text)


def _unprinted(text: str) -> str:
    """`text` with the links' reference definitions blanked, offsets kept."""
    return blank(text, [found.span() for found in _DEFINITION.finditer(text)])


# ----------------------------------------------------------------------- empty headings


@dataclass(frozen=True)
class EmptyHeading:
    """A heading with nothing printed under it, at its line of the text it was read in."""

    title: str
    level: int
    line: int
    offset: int


def _shown(text: str) -> str:
    """`text` with what the build does not print blanked, offsets kept: the front matter, the
    YAML blocks of the body, the HTML comments and the links' reference definitions. Fenced
    listings are printed, and kept."""
    spans = [(0, front_matter_end(text)), *metadata_blocks(text), *html_comments(text)]
    return _unprinted(blank(text, spans))


def _opens(text: str, start: int, setext: bool) -> int:
    """Where a heading's own text starts: past its line, and past its underline."""
    body = text.find("\n", start)
    if body != -1 and setext:
        body = text.find("\n", body + 1)
    return len(text) if body == -1 else body


def _bibliography(title: str, last: bool) -> bool:
    """Whether the build prints the bibliography under a heading of this title: the reference
    list's own, or, as the document's `last` heading, one whose title ends in its word."""
    from manuscript_guard.text.section_names import plain

    # A supplement's number too, "S4. References cited", which `plain` leaves on.
    bare = _SUPPLEMENT_NUMBER.sub("", plain(title))
    return (Section(title=bare, level=1, body="", line=0).is_references
            or (last and bool(_REFERENCES_LAST.search(bare))))  # fmt: skip


def _ends(headings: list) -> list[int]:
    """For each heading, the index of the next of its level or above: where what is below it
    ends. One pass, a stack of the headings still open."""
    ends = [len(headings)] * len(headings)
    open_: list[int] = []
    for index, heading in enumerate(headings):
        while open_ and headings[open_[-1]].level >= heading.level:
            ends[open_.pop()] = index
        open_.append(index)
    return ends


def _below(flags: list[bool], ends: list[int]) -> list[bool]:
    """For each heading, whether a heading below it, to `ends`, has its flag: counted from
    the end, so that each is asked once."""
    after = [0] * (len(flags) + 1)
    for index in reversed(range(len(flags))):
        after[index] = after[index + 1] + flags[index]
    return [after[index + 1] - after[ends[index]] > 0 for index in range(len(flags))]


def _printed(headings: list, bodies: list[str]) -> list[bool]:
    """For each heading, whether anything is printed under it: in its own text, the
    bibliography under the reference list's heading, or under a heading below it."""
    own = [_says(body) or _bibliography(heading.title.strip(), index == len(headings) - 1)
           for index, (heading, body) in enumerate(zip(headings, bodies, strict=True))]
    below = _below(own, _ends(headings))
    return [mine or under for mine, under in zip(own, below, strict=True)]


def _passed_over(title: str, level: int) -> bool:
    """A heading never said to be empty: one with no title."""
    return not title


def _gaps(headings: list, printed: list[bool]) -> list[int]:
    """The headings said to be empty: each with nothing printed under it and no heading said
    below it. A heading empty only through its empty subsections is no gap of its own; each
    of them is."""
    ends = _ends(headings)
    said = [False] * len(headings)
    after = [0] * (len(headings) + 1)
    for index in reversed(range(len(headings))):
        heading = headings[index]
        said[index] = (not printed[index] and after[index + 1] == after[ends[index]]
                       and not _passed_over(heading.title.strip(), heading.level))  # fmt: skip
        after[index] = after[index + 1] + said[index]
    return [index for index, gap in enumerate(said) if gap]


def empty_headings(text: str) -> list[EmptyHeading]:
    """Each heading of `text` under which nothing is printed, and no heading below it is said
    to be, in order. Headings are found as the gates find them (`scannable`), so a `#` line
    in a listing is none."""
    headings = find_headings(scannable(text))
    shown = _shown(text)
    bodies = [
        shown[_opens(text, heading.start, heading.setext):(
            headings[index + 1].start if index + 1 < len(headings) else len(text))]
        for index, heading in enumerate(headings)
    ]  # fmt: skip
    breaks = [at for at, char in enumerate(text) if char == "\n"]
    found = []
    for index in _gaps(headings, _printed(headings, bodies)):
        heading = headings[index]
        found.append(EmptyHeading(heading.title.strip(), heading.level,
                                  bisect_left(breaks, heading.start) + 1, heading.start))
    return found


# ----------------------------------------------------------------------- the statements


def _data_kind(title: str, heading: str | None) -> bool:
    """Whether a heading or a label opens a Data availability statement: by the forms
    journals ask for, or by the heading the journal's profile gives it."""
    if _DATA_HEADING.search(title):
        return True
    try:
        return bool(heading and re.search(heading, title, re.IGNORECASE))
    except re.error:
        return False  # G4 says the profile's pattern is no regular expression


def _ai_kind(title: str) -> bool:
    from manuscript_guard.gates.ai_use import _STATEMENT, _TOOL

    return bool(_TOOL.search(title) and _STATEMENT.search(title))


def kinds_of(title: str, data_heading: str | None = None) -> list[str]:
    """The standard kinds a heading or a label names: "Contributors, funding and competing
    interests" names three. A Declarations section is `declarations`, read for its words."""
    from manuscript_guard.gates.disclosures import DECLARATIONS, _heading_kinds

    found = [kind for kind in _heading_kinds(title) if kind in (*_DISCLOSED, DECLARATIONS)]
    if _data_kind(title, data_heading):
        found.append(DATA)
    if _ai_kind(title):
        found.append(AI_USE)
    return found


#: The marks of emphasis, the doubled before the single.
_EMPHASIS = ("**", "__", "*", "_")


def _emphasised_sentence(paragraph: str) -> bool:
    """Whether a paragraph is a sentence wholly in emphasis, ending in a stop inside its marks
    or after them: "*The authors declare no competing interests.*", "**No funding was
    received.**". G4's reading of the declarations takes one of six words or fewer for a label
    alone; it is a statement (round 2 of #819). "**Funding**", with no stop, is a label, and
    so is a title alone with its stop, "**Funding.**", "*Competing interests.*" (round 3)."""
    text = paragraph.strip()
    for mark in _EMPHASIS:
        if not text.startswith(mark):
            continue
        inner = text[len(mark):]
        stop = inner[-1:] if inner[-1:] in (".", "!", "?") and inner[:-1].endswith(mark) else ""
        inner = inner[: len(inner) - len(stop)]
        if len(inner) <= len(mark) or not inner.endswith(mark):
            return False
        inner = inner[: -len(mark)]
        return (mark not in inner and bool(stop or inner.rstrip().endswith((".", "!", "?")))
                and not _title_only(inner))  # fmt: skip
    return False


#: The words a statement's title is made of ("Ethics approval and consent to participate",
#: "Data, Materials, and Software Availability", "Use of generative AI"): a paragraph wholly
#: in emphasis of these words alone is a label, whatever stop ends it.
_TITLE_WORDS = frozenset((
    "a", "accessibility", "acknowledgement", "acknowledgements", "acknowledgment",
    "acknowledgments", "ai", "and", "approval", "artificial", "author", "author's", "authors",
    "authors'", "authorship", "availability", "board", "code", "committee", "competing",
    "conflict", "conflicting", "conflicts", "consent", "contribution", "contributions",
    "contributor", "contributors", "contributorship", "credit", "data", "declaration",
    "declarations", "disclosure", "disclosures", "duality", "ethical", "ethics", "financial",
    "for", "funder", "funding", "generative", "grant", "grants", "information",
    "institutional", "intelligence", "interest", "interests", "irb", "language", "llm", "llms",
    "materials", "model", "models", "of", "on", "or", "participate", "publication", "review",
    "role", "roles", "sharing", "software", "source", "sources", "statement", "statements",
    "support", "the", "to", "tools", "use",
))  # fmt: skip


def _title_only(words: str) -> bool:
    """Whether `words`, their marks and stops taken off, are only a statement's title, of a
    kind this check reads: "Funding", "Competing interests", "Data availability" (round 3 of
    #819). "The authors declare no competing interests" is a sentence."""
    said = re.findall(r"[a-z']+", words.casefold().replace("\N{RIGHT SINGLE QUOTATION MARK}", "'"))
    return (bool(said) and all(word in _TITLE_WORDS for word in said)
            and bool(_label_of(" ".join(said), None)))  # fmt: skip


def _said_words(text: str) -> str:
    """The words `text` prints as sentences: each paragraph without the label it opens with,
    "**Funding:**" or "Data availability:", whose words name a kind and state nothing. A
    sentence wholly in emphasis is kept whole: it is no label."""
    from manuscript_guard.gates.disclosures import _label, paragraphs

    kept = []
    for paragraph in paragraphs(text):
        labelled = None if _emphasised_sentence(paragraph) else _label(paragraph)
        kept.append(labelled[1] if labelled is not None else paragraph)
    return "\n\n".join(piece for piece in kept if _says(piece))


def _without_roles(folded: str) -> str:
    """Folded words without the CRediT roles and the items of the ICMJE form, whose words name
    a statement they are no part of: "Funding acquisition", "Grants or contracts from any
    entity" (`not_statements` of `data/disclosures.yaml`)."""
    from manuscript_guard.gates.disclosures import _data, _pattern

    for pattern in _data()["not_statements"]:
        folded = _pattern(f"(?:{pattern})").sub(" ", folded)
    return folded


def _words_of(kind: str, text: str) -> bool:
    """Whether `text` holds the words of `kind`'s heading: "no competing interests", "this
    work received no funding", "ethical approval", "no generative AI was used"."""
    from manuscript_guard.gates.disclosures import _data, _pattern, fold

    # Marks of emphasis are no part of a word: "_no competing interests_".
    text = re.sub(r"[*_`]+", " ", text)
    if kind == DATA:
        return bool(_DATA_WORDS.search(text))
    if kind == AI_USE:
        return any(_ai_kind(sentence) for sentence in re.split(r"(?<=[.!?])\s+|\n", text))
    folded = fold(text)
    if kind == FUNDING:
        folded = _without_roles(folded)
    # The headings' patterns that hold to a whole title (`^...$`) say nothing of a sentence.
    return bool(_pattern(_data()["headings"][kind]).search(folded))


def stated(text: str, *, abstract: str | None = None,
           data_heading: str | None = None) -> dict[str, str]:  # fmt: skip
    """Each standard kind `text` holds: `stated` where words are printed after a heading or a
    label of it, `empty` where its only heading has nothing printed under it; a kind the text
    does not hold is left out. Headings' and labels' own words are no statement: the Methods
    and a Declarations section are read for their sentences without them."""
    from manuscript_guard.gates.disclosures import (
        DECLARATIONS,
        _data,
        _first,
        _label,
        _labelled,
        _own,
        paragraphs,
    )
    from manuscript_guard.text.section_names import methods_sections
    from manuscript_guard.text.sections import subsections

    printed = _unprinted(scannable(text))
    sections = split_sections(printed)
    empty = {heading.line for heading in empty_headings(text)}
    said: dict[str, str] = {}

    def found(kind: str, how: str) -> None:
        if said.get(kind) != STATED:
            said[kind] = how

    for section in sections:
        if not section.title:
            continue
        for kind in kinds_of(section.title, data_heading):
            if kind == DECLARATIONS:
                # Its own sentences, before a heading of its parts, which are read as headings,
                # and each without its label, which is read as a label.
                words = _said_words(section.body)
                for named in KINDS:
                    if _words_of(named, words):
                        found(named, STATED)
            elif _says(_own(section.enclosed, kind)):
                found(kind, STATED)
            elif section.line in empty:
                found(kind, HEADED_EMPTY)
    for section in methods_sections(sections, abstract):
        parts = subsections(sections, sections.index(section))
        if _words_of(ETHICS, _said_words("\n\n".join(part.body for part in parts))):
            found(ETHICS, STATED)
    # A sentence that says no approval was needed is an ethics statement where it stands: in
    # the Data availability statement, say, as G4 reads a denial (`ethics-approval-denied`).
    if _first(_data()["no_approval"], printed):
        found(ETHICS, STATED)
    # `_labelled` gives one label for each paragraph that opens with one, in order.
    labelled = [piece for piece in paragraphs(printed) if _label(piece) is not None]
    for paragraph, (label, rest) in zip(labelled, _labelled(printed), strict=False):
        if _emphasised_sentence(paragraph):
            # A sentence, not a label: it states what its words name (round 2 of #819).
            for kind in KINDS:
                if _words_of(kind, paragraph):
                    found(kind, STATED)
            continue
        held = _held(_label(paragraph)[1], rest, data_heading)
        for kind in _label_of(label, data_heading):
            if _says(held):
                found(kind, STATED)
    return said


def _held(own: str, rest: str, data_heading: str | None) -> str:
    """What a label holds: the rest of its own paragraph, whatever that is ("**Ethics
    approval:** Ethics committee: CPP Sud-Est", round 2 of #819); for a label alone, or over a
    comment, what follows it up to the next label of a standard kind (`_cut`)."""
    return own if own.strip() else _cut(rest, data_heading)


def _label_of(label: str, data_heading: str | None) -> list[str]:
    """The standard kinds a paragraph's label opens: none for a CRediT role or an item of the
    ICMJE form (`disclosures._label_kinds`)."""
    from manuscript_guard.gates.disclosures import _label_kinds

    kinds = [kind for kind in _label_kinds(label) if kind in _DISCLOSED]
    kinds += [DATA] if _data_kind(label, data_heading) else []
    kinds += [AI_USE] if _ai_kind(label) else []
    return kinds


def _cut(rest: str, data_heading: str | None) -> str:
    """What a label alone heads, to the next label of a standard kind. G4's reading of the
    declarations ends one, or one over a comment, at a label of its own four kinds; a Data
    availability or an AI-use label after it is no part of it either (round 1 of #819). A label
    of the same kind after it ("Ethical approval:", then "Ethics committee: CPP Sud-Est") is a
    statement of its own."""
    from manuscript_guard.gates.disclosures import _label, paragraphs

    kept = []
    for paragraph in paragraphs(rest):
        labelled = _label(paragraph)
        if labelled is not None and _label_of(labelled[0], data_heading):
            break
        kept.append(paragraph)
    return "\n\n".join(kept)


def merged(*readings: dict[str, str]) -> dict[str, str]:
    """What several texts hold together: a kind stated in one is stated."""
    out: dict[str, str] = {}
    for said in readings:
        for kind, how in said.items():
            if out.get(kind) != STATED:
                out[kind] = how
    return out


def missing(said: dict[str, str], wanted: Iterable[str] = KINDS, *,
            empty_said: bool = True) -> list[str]:  # fmt: skip
    """The kinds of `wanted` that `said`, as `stated` gives it, does not hold. One whose only
    heading is empty is left out where `empty_said`, since `section-empty` says it."""
    return [kind for kind in wanted
            if said.get(kind) != STATED and not (empty_said and said.get(kind) == HEADED_EMPTY)]


# ------------------------------------------------------------------------------ the check


@dataclass(frozen=True)
class _Source:
    """One file of a document as the gates join them: where its text starts in the whole,
    and how many lines of front matter come before it in the file."""

    path: Path
    start: int
    skipped: int


def _document(folder: Path, *, supplementary: bool) -> tuple[str, list[_Source]]:
    """A Markdown document as `journal.main_text` joins it, each file's front matter left
    out, with where each file starts."""
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files

    paths = [path for path in source_files(folder)
             if is_supplementary(folder, path) == supplementary]  # fmt: skip
    pieces, sources, at = [], [], 0
    for path in printed_order(paths, supplementary=supplementary):
        text = read_text(path)
        head = front_matter_end(text)
        if pieces:
            at += 2
        sources.append(_Source(path, at, text.count("\n", 0, head)))
        pieces.append(text[head:])
        at += len(text) - head
    return "\n\n".join(pieces), sources


def _located(joined: str, sources: list[_Source], offset: int) -> tuple[Path | None, int]:
    source = next((s for s in reversed(sources) if s.start <= offset), None)
    if source is None:
        return None, joined.count("\n", 0, offset) + 1
    return source.path, source.skipped + joined.count("\n", source.start, offset) + 1


def severity_at(stage: str | None) -> str:
    """A note before the drafting stage, a warning while drafting, a failure from internal
    review on. No stage is drafting, the default."""
    from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, stage_index

    here = stage_index(stage or DRAFTING)
    if here >= stage_index(INTERNAL_REVIEW):
        return FAIL
    return WARN if here >= stage_index(DRAFTING) else INFO


def _empty_finding(heading: EmptyHeading, path: Path | None, line: int, severity: str,
                   heads: list[str]) -> Finding:  # fmt: skip
    """`heads`: the statements the manuscript has nowhere but under this heading."""
    named = [NAMES[kind] for kind in heads]
    lacking = (f", so the manuscript has no {', '.join(named[:-1])} or {named[-1]}"
               if len(named) > 1 else f", so the manuscript has no {named[0]}" if named else "")
    return Finding(
        gate=GATE, code=EMPTY, severity=severity, path=path, line=line,
        message=f"the heading {heading.title!r} has nothing under it{lacking}",
        hint="write what goes under it, or take the heading out until it is written: an HTML "
        "comment or a placeholder is not a statement, and the built document shows the "
        "heading alone" + "".join(f"; {WRITE[kind]}" for kind in heads),
        subject=heading.title,
    )  # fmt: skip


def _missing_finding(kind: str, path: Path | None, severity: str, recorded: str) -> Finding:
    return Finding(
        gate=GATE, code=MISSING, severity=severity, path=path,
        message=f"the manuscript has no {NAMES[kind]}",
        hint=f"{WRITE[kind]}, under a heading such as \"{USUAL[kind]}\" or in a paragraph "
        f"labelled \"{USUAL[kind]}:\"{recorded}; the submission-pack skill drafts the "
        "declarations from authors.yaml",
        subject=kind,
    )  # fmt: skip


def _recorded(project: Project, kind: str) -> str:
    """What the records hold that the statement of `kind` is to give, as the notes this
    finding stands in for said it (`funding-not-stated`, `interests-not-stated`,
    `ai-use-not-stated`)."""
    from manuscript_guard.gates.ai_use import statement_hint
    from manuscript_guard.gates.disclosures import (
        _field,
        _name,
        _people,
        _texts,
        is_none_statement,
    )

    if kind == AI_USE:
        return statement_hint(project)
    people = _people(project.authors)
    if kind == FUNDING:
        held = [f"{_name(author)}: {entry}" for author in people
                for entry in _texts(author.get("funding"))]  # fmt: skip
    elif kind == INTERESTS:
        held = [f"{_name(author)}: {_field(author, 'competing_interests')}" for author in people
                if _field(author, "competing_interests")
                and not is_none_statement(_field(author, "competing_interests"))]  # fmt: skip
    else:
        return ""
    return f"; authors.yaml records {'; '.join(held)}" if held else ""


@dataclass(frozen=True)
class _Reading:
    said: dict[str, str]
    wanted: list[str]
    markdown: bool
    data_heading: str | None

    @property
    def lacking(self) -> list[str]:
        return missing(self.said, self.wanted, empty_said=self.markdown)


def _read(project: Project) -> _Reading:
    """The statements the manuscript holds, and those this check asks for."""
    from manuscript_guard.gates.ai_use import supplement_text, wanted
    from manuscript_guard.gates.data_statement import _profile_heading
    from manuscript_guard.gates.journal import _profile, abstract_title, main_text
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    data_heading = _profile_heading(project)
    abstract = abstract_title(project)
    said = merged(stated(main_text(project), abstract=abstract, data_heading=data_heading),
                  stated(supplement_text(project), data_heading=data_heading))  # fmt: skip
    profile = _profile(project) or {}
    # The journal's list, where its profile has one, is `missing-required-statement`'s.
    asked = [] if profile.get("required_statements") else [
        kind for kind in KINDS if kind != AI_USE or wanted(project)]  # fmt: skip
    return _Reading(said, asked, manuscript_format(folder) != LATEX, data_heading)


def asked_for(project: Project) -> set[str]:
    """The kinds `declaration-missing` is said of: for the checks whose notes it stands in
    for, so that one gap is one finding."""
    if not project.path("manuscript").is_dir():
        return set()
    return set(_read(project).lacking)


def check_statements(project: Project, stage: str | None = None) -> Report:
    """G4's check of the standard statements and of empty headings, at `stage` (the module's
    docstring)."""
    folder = project.path("manuscript")
    if not folder.is_dir():
        return Report()
    severity = severity_at(stage)
    reading = _read(project)
    findings: list[Finding] = []
    if reading.markdown:
        for supplementary in (False, True):
            joined, sources = _document(folder, supplementary=supplementary)
            for heading in empty_headings(joined):
                path, line = _located(joined, sources, heading.offset)
                named = kinds_of(heading.title, reading.data_heading)
                heads = [kind for kind in KINDS
                         if kind in named and reading.said.get(kind) == HEADED_EMPTY]
                findings.append(_empty_finding(heading, path, line, severity, heads))
    where = _main_file(folder)
    findings += [_missing_finding(kind, where, severity, _recorded(project, kind))
                 for kind in reading.lacking]  # fmt: skip
    return Report(tuple(findings))


def _main_file(folder: Path) -> Path | None:
    """The file a statement missing from the main text is said of: `main.md`, or the main
    text's first file."""
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    glob = "*.tex" if manuscript_format(folder) == LATEX else None
    paths = [path for path in (source_files(folder, glob=glob) if glob else source_files(folder))
             if not is_supplementary(folder, path)]  # fmt: skip
    ordered = printed_order(paths, supplementary=False)
    return ordered[0] if ordered else None


__all__ = ["EMPTY", "KINDS", "MISSING", "asked_for", "check_statements", "empty_headings",
           "kinds_of", "merged", "missing", "severity_at", "stated"]  # fmt: skip
