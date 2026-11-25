"""A journal's profile and the authors' names from the audit page's form, as the files
`audit --journal` and `audit --authors` read (docs/audit-page.md).

A reader of the page types what the journal's instructions for authors say: its limits, the
sections and the headings of a structured abstract it asks for, the statements it requires,
and how its peer review is blinded. Nothing is guessed: a limit left empty is not in the
profile, and is not checked. Each statement ticked is found as G4 finds any profile's, by a
pattern on the text as Markdown writes it (a .docx and a LaTeX paper are read that way too):
its label in a heading, in the marked words a paragraph opens with ("**Funding:**",
"*Ethics approval.*"), or in plain type ending in a colon within the first few words
("Funding: none"). A sentence that mentions funding is no statement of it.

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
    """A statement a journal may require: its name on the page, the spellings of its label
    (a regular expression's alternatives, matched as words, in any case), and what the report
    says it should hold."""

    shown: str
    labels: str
    why: str


#: The statements the page offers, by their id in the profile.
STATEMENTS: dict[str, Statement] = {
    "funding": Statement(
        "Funding",
        r"funding|financial support|sources? of funding",
        "Funding sources, or a statement that the work received none.",
    ),
    "competing-interests": Statement(
        "Competing interests",
        r"competing interests?|conflicts? of interests?|declarations? of (?:competing )?"
        r"interests?|financial disclosures?",
        "Competing interests for every author, or a statement that there are none.",
    ),
    "ethics": Statement(
        "Ethics approval",
        r"ethics|ethical|institutional review board",
        "The committee that approved the study and its reference, or why no approval was "
        "needed.",
    ),
    "consent": Statement(
        "Consent",
        r"consent",
        "How consent to take part, and to publish, was obtained, or why it was not needed.",
    ),
    "data-availability": Statement(
        "Data availability",
        r"data availability|data sharing|data access|availability of (?:the )?(?:supporting )?"
        r"data",
        "Where the data are, and on what terms.",
    ),
    "author-contributions": Statement(
        "Author contributions",
        r"authors?(?:['\u2019]s?)? contributions?|contributorship|contributors|credit (?:author )?"
        r"statement",
        "What each author did.",
    ),
    "trial-registration": Statement(
        "Trial registration",
        r"(?:clinical )?trial registration|registration (?:number|details)|trial (?:number|"
        r"identifier)",
        "The registry and the trial's number in it.",
    ),
    "use-of-ai": Statement(
        "Use of AI",
        r"(?:use|declaration|disclosure|statement) (?:of|on) (?:the use of )?(?:generative )?"
        r"(?:ai|artificial intelligence)|(?:generative )?(?:ai|artificial intelligence)[- ]"
        r"(?:use|disclosure|statement|declaration)",
        "Whether and how AI tools were used in the work or the writing.",
    ),
}


def pattern(labels: str) -> str:
    """What finds a statement whose label is one of `labels`, in the text as Markdown writes
    it: in a heading's line; in the marked words a paragraph opens with; or in plain type
    among its first six words, before a colon."""
    word = rf"\b(?:{labels})\b"
    return ("(?im)^(?:"
            rf"#{{1,6}}[ \t][^\n]*?{word}"
            rf"|[ \t]*(?:\*\*|__|\*|_)[^\n*_]{{0,80}}?{word}"
            rf"|[ \t]*(?:[^\s:#>|*_][^\s:]*[ \t]+){{0,5}}{word}[^\n:.]{{0,40}}:"
            ")")  # fmt: skip


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
    wanted = _lines(form, "statements")
    unknown = [one for one in wanted if one not in STATEMENTS]
    if unknown:
        raise FormError(f"the page offers no statement {unknown[0]!r}")
    if wanted:
        profile["required_statements"] = [
            {"id": one, "pattern": pattern(STATEMENTS[one].labels), "why": STATEMENTS[one].why}
            for one in STATEMENTS if one in wanted
        ]
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
           "authors_of", "pattern", "profile_of"]  # fmt: skip
