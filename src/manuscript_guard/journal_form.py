"""A journal's profile and the authors' names from the audit page's form, as the files
`audit --journal` and `audit --authors` read (docs/audit-page.md).

A reader of the page types what the journal's instructions for authors say: its limits, the
sections and the headings of a structured abstract it asks for, the statements it requires,
and how its peer review is blinded. Nothing is guessed: a limit left empty is not in the
profile, and is not checked. Each statement ticked comes with the heading the journal asks
for it under, the usual one unless the reader types the journal's ("Funding", "Competing
interests"), alternatives joined by " or ". It is found as G4 finds any profile's, by a
pattern on the text as Markdown writes it (a .docx and a LaTeX paper are read that way too):
a heading, the marked words a paragraph opens with ("**Funding:**"), or the words a
paragraph opens with in plain type before a colon ("Funding: none"), whose whole title is
that heading, whatever its case, its number or its marks. Nothing else is read as one: a
paper that states its funding under "Financial support" is told the journal asks for
"Funding" (Basile, 2026-11-25: the journal's own heading, after three rounds of review found
a vocabulary of statement names took too much or too little).

The profile is the one the command line reads, validated against its schema, so that the page
and `audit --journal` given the same file say the same; web/test/check.py builds the command
line's file with this module.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

SCHEMA = "manuscript-guard/journal/1"
#: The name the profile is given where the reader gives none.
UNNAMED = "The journal"
#: Who read the instructions, as the profile records it.
READ_BY = "the reader, in the audit page's form"
#: The ways a journal's review is blinded, as the schema names them.
BLINDINGS = ("single", "double", "triple", "open")
#: The limits the form takes, as the schema names them, with how each is said in an error,
#: and the least each may be.
LIMITS = {
    "abstract_words": ("the words in the abstract", 1),
    "main_text_words": ("the words in the main text", 1),
    "figures": ("the figures", 0),
    "tables": ("the tables", 0),
    "references": ("the references", 1),
    "keywords": ("the keywords", 1),
}


class FormError(ValueError):
    """What the form says cannot make a profile or an authors file: the message says why."""


@dataclass(frozen=True)
class Statement:
    """A statement a journal may require: its name on the page, the heading it usually
    stands under, which the page offers until the reader types the journal's, and what the
    report says it should hold."""

    shown: str
    heading: str
    why: str


#: The statements the page offers, by their id in the profile.
STATEMENTS: dict[str, Statement] = {
    "funding": Statement(
        "Funding", "Funding",
        "Funding sources, or a statement that the work received none.",
    ),
    "competing-interests": Statement(
        "Competing interests", "Competing interests",
        "Competing interests for every author, or a statement that there are none.",
    ),
    "ethics": Statement(
        "Ethics approval", "Ethics approval",
        "The committee that approved the study and its reference, or why no approval was "
        "needed.",
    ),
    "consent": Statement(
        "Consent", "Informed consent",
        "How consent to take part, and to publish, was obtained, or why it was not needed.",
    ),
    "data-availability": Statement(
        "Data availability", "Data availability",
        "Where the data are, and on what terms.",
    ),
    "author-contributions": Statement(
        "Author contributions", "Author contributions",
        "What each author did.",
    ),
    "trial-registration": Statement(
        "Trial registration", "Trial registration",
        "The registry and the trial's number in it.",
    ),
    "use-of-ai": Statement(
        # Elsevier's heading in full, as a heading is matched whole, and the shorter ones
        # other journals print.
        "Use of AI", "Declaration of generative AI and AI-assisted technologies in the "
        "writing process or Declaration of generative AI or Use of AI",
        "Whether and how AI tools were used in the work or the writing.",
    ),
}

#: What joins two headings the journal takes for one statement: "Competing interests or
#: Conflicts of interest".
_OR = re.compile(r"[ \t]+or[ \t]+", re.IGNORECASE)
#: A Word bookmark, as pandoc writes one: `[]{#_Hlk1 .anchor}`.
_ANCHORS = r"(?:\[\]\{[^}\n]*\}[ \t]*)*"
#: The marks that open or close emphasis: bold and italic, bold, or italic.
_MARK = r"(?:\*\*\*|\*\*|__|\*|_)"
#: A heading's number, as `section_names` reads one: "2", "2.1.", "II.", "A)", "(2)".
_NUMBER = r"(?:(?:\(\d+\)|\d+(?:\.\d+)*[.)]?|[ivxlc]+[.)]|[a-z][.)])[ \t]+)?"
#: What may end a heading after its title, in any order: white space, the marks that close
#: emphasis, a colon or a stop, a closing sequence of hashes, a Word bookmark, attributes.
#: Runs of the characters between the braced pieces, which start with a character no run
#: holds, so that a line that does not end so is refused in time linear in its length: a
#: run of one class is read without the backtracking a repeated group of alternatives costs.
_HEADING_END = r"(?:[ \t:.*_#]*(?:\[\]\{[^}\n]*\}|\{[^}\n]*\}))*[ \t:.*_#]*$"


def headings_of(typed: str) -> list[str]:
    """The headings a journal takes for a statement, as typed: each alternative of `typed`,
    joined by " or ", with its white space made one space; none where nothing is typed."""
    return [" ".join(one.split()) for one in _OR.split(typed) if one.strip()]


def _spelled(heading: str) -> str:
    """`heading` as a pattern: its words as typed, any white space between them, and an
    apostrophe either straight or curly."""
    apostrophe = "['\N{RIGHT SINGLE QUOTATION MARK}]"
    return r"[ \t]+".join(re.sub(apostrophe, apostrophe, re.escape(word))
                          for word in heading.split())  # fmt: skip


def pattern(headings: list[str]) -> str:
    """What finds a statement under one of `headings`, in the text as Markdown writes it: a
    heading whose whole title is one of them, numbered, marked or not; the marked words a
    paragraph opens with, all of them one of them ("**Funding:**", "*Funding.*"); or one of
    them in plain type a paragraph opens with, before a colon ("Funding: none"). In any
    case, and past a Word bookmark."""
    title = "(?:" + "|".join(_spelled(one) for one in headings) + ")"
    return ("(?im)^(?:"
            rf"#{{1,6}}[ \t]+{_ANCHORS}{_NUMBER}{_MARK}?{_ANCHORS}{title}{_HEADING_END}"
            rf"|[ \t]*{_ANCHORS}{_MARK}{_ANCHORS}{title}[ \t:.]*{_MARK}"
            rf"|[ \t]*{_ANCHORS}{title}[ \t]*:"
            ")")  # fmt: skip


def _statements(form: Mapping) -> list[dict]:
    """The statements the form ticks, in the order the page lists them, each with the
    pattern of the headings the reader gave it, or of its usual one, and a `why` that names
    them. `FormError` for a statement the page does not offer."""
    wanted = _lines(form, "statements")
    unknown = [one for one in wanted if one not in STATEMENTS]
    if unknown:
        raise FormError(f"the page offers no statement {unknown[0]!r}")
    typed = form.get("headings") or {}
    if not isinstance(typed, Mapping):
        raise FormError("headings is a mapping of a statement to its heading")
    made = []
    for one in (one for one in STATEMENTS if one in wanted):
        given = typed.get(one)
        headings = headings_of(given if isinstance(given, str) else "") or [STATEMENTS[one].heading]
        said = " or ".join(f'"{heading}"' for heading in headings)
        made.append({"id": one, "pattern": pattern(headings),
                     "why": f"{STATEMENTS[one].why} The journal asks for it under the heading "
                            f"{said}."})  # fmt: skip
    return made


def _text(form: Mapping, key: str) -> str:
    value = form.get(key)
    return value.strip() if isinstance(value, str) else ""


def _lines(form: Mapping, key: str) -> list[str]:
    value = form.get(key) or []
    if not isinstance(value, list):
        raise FormError(f"{key} is a list of lines")
    return [line.strip() for line in value if isinstance(line, str) and line.strip()]


def _limit(form: Mapping, key: str) -> int | None:
    said, least = LIMITS[key]
    typed = str((form.get("limits") or {}).get(key) or "").strip()
    if not typed:
        return None
    if not re.fullmatch(r"\d{1,7}", typed) or int(typed) < least:
        raise FormError(f"the limit on {said} is a whole number from {least}: {typed!r} is not")
    return int(typed)


def profile_of(form: Mapping) -> dict:
    """The profile the form describes. `FormError` where a value is not one the profile can
    hold: a limit that is no whole number, a statement or a blinding the page does not offer,
    a date that is no date."""
    from datetime import date

    date_given = _text(form, "date")
    try:
        date.fromisoformat(date_given)
    except ValueError:
        raise FormError("the date the instructions were read on is no date: "
                        f"{date_given!r}") from None
    profile: dict = {"schema": SCHEMA, "name": _text(form, "name") or UNNAMED,
                     "source_url": _text(form, "url"), "retrieved_on": date_given,
                     "retrieved_by": READ_BY}  # fmt: skip
    limits = {key: value for key in LIMITS if (value := _limit(form, key)) is not None}
    if limits:
        profile["limits"] = limits
    structure: dict = {}
    sections = _lines(form, "sections")
    if sections:
        structure["required_sections"] = sections
    headings = _lines(form, "abstract_headings")
    if headings:
        structure["abstract_structured"] = True
        structure["abstract_headings"] = headings
    if structure:
        profile["structure"] = structure
    statements = _statements(form)
    if statements:
        profile["required_statements"] = statements
    blinding = _text(form, "blinding")
    if blinding:
        if blinding not in BLINDINGS:
            raise FormError(f"the journal's review is single, double, triple or open: "
                            f"{blinding!r} is none of them")  # fmt: skip
        profile["blinding"] = blinding
    _valid(profile, "journal")
    return profile


def authors_of(form: Mapping) -> dict:
    """The authors the form names, in authors.yaml's shape, as `--authors` reads it: each row
    with a name, its given and its family name both; an ORCID iD and an e-mail address where
    typed; and each affiliation, a line. `FormError` where a row has one name and not the
    other, or none is named."""
    rows = form.get("authors") or []
    if not isinstance(rows, list):
        raise FormError("authors is a list of rows")
    people = []
    for number, row in enumerate(rows, 1):
        row = row if isinstance(row, Mapping) else {}
        given, family, orcid, email = (_text(row, key)
                                       for key in ("given", "family", "orcid", "email"))
        if not (given or family or orcid or email):
            continue
        if not (given and family):
            raise FormError(f"author {number} needs a given name and a family name, which is "
                            "how a name is looked for")  # fmt: skip
        person = {"given": given, "family": family}
        if orcid:
            person["orcid"] = orcid
        if email:
            person["email"] = email
        people.append(person)
    if not people:
        raise FormError("no author is named: give each one's given and family name")
    document: dict = {"authors": people}
    affiliations = _lines(form, "affiliations")
    if affiliations:
        document["affiliations"] = [{"text": line} for line in affiliations]
    return document


def as_text(document: dict) -> str:
    """`document` as the YAML file the command line reads, its keys in the order given."""
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=1000)


def _valid(profile: dict, schema: str) -> None:
    from manuscript_guard.contracts._schema import validate

    report = validate(profile, schema, Path("journal.yaml"), gate="G4")
    if not report.ok:
        raise FormError("; ".join(finding.message for finding in report.findings))


__all__ = ["BLINDINGS", "LIMITS", "STATEMENTS", "FormError", "Statement", "as_text",
           "authors_of", "headings_of", "pattern", "profile_of"]  # fmt: skip
