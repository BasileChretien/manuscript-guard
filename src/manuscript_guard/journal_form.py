"""A journal's profile and the authors' names from the audit page's form, as the files
`audit --journal` and `audit --authors` read (docs/audit-page.md).

A reader of the page types what the journal's instructions for authors say: its limits, the
sections and the headings of a structured abstract it asks for, the statements it requires,
and how its peer review is blinded. Nothing is guessed: a limit left empty is not in the
profile, and is not checked. Each statement ticked is found as G4 finds any profile's, by a
pattern on the text as Markdown writes it (a .docx and a LaTeX paper are read that way too):
a heading that opens with its label, the marked words a paragraph opens with
("**Funding:**", "*Ethics approval.*"), or the label in plain type a paragraph opens with,
before a colon ("Funding: none"). The label must end there: a sentence that mentions
funding, and a heading on the subject ("Funding of mental health services"), state nothing.

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


#: The statements the page offers, by their id in the profile. Each label is matched whole,
#: and must end where the label does (`_END`): "Funding" in "Funding: none" and in a heading
#: "Funding", not in "Funding of mental health services".
STATEMENTS: dict[str, Statement] = {
    "funding": Statement(
        "Funding",
        r"funding|financial support|grant support|sources? of funding|role of the funding "
        r"sources?|statement of funding",
        "Funding sources, or a statement that the work received none.",
    ),
    "competing-interests": Statement(
        "Competing interests",
        r"competing interests?|conflicts? of interests?|conflicting interests?|declarations? of "
        r"(?:competing |conflicting )?interests?|statement of (?:competing|conflicting) "
        r"interests?|financial disclosures?|(?<!ai )(?<!ai-)disclosures?|duality of interests?",
        "Competing interests for every author, or a statement that there are none.",
    ),
    "ethics": Statement(
        "Ethics approval",
        r"ethic(?:s|al) approval and consent(?: to participate)?|ethics|ethical (?:approval|"
        r"statement|considerations?|review|declarations?)|ethics (?:approval|statement|"
        r"committee|declarations?|review)|statement of ethics|institutional review board",
        "The committee that approved the study and its reference, or why no approval was "
        "needed.",
    ),
    "consent": Statement(
        "Consent",
        r"ethic(?:s|al) approval and consent(?: to participate)?|(?:informed |patient |written )?"
        r"consent(?: (?:for publication|to participate|to publish))?",
        "How consent to take part, and to publish, was obtained, or why it was not needed.",
    ),
    "data-availability": Statement(
        "Data availability",
        r"data(?:,? (?:and )?(?:materials?|code|software))*,? (?:availability|accessibility)|"
        r"availability of (?:the )?(?:supporting )?data(?: and materials?)?|data sharing|"
        r"data access",
        "Where the data are, and on what terms.",
    ),
    "author-contributions": Statement(
        "Author contributions",
        r"authors?(?:['\N{RIGHT SINGLE QUOTATION MARK}]s?)? contributions?|authorship "
        r"contributions?|contributorship|contributors|credit (?:authorship contribution |author )?"
        r"statement|author roles",
        "What each author did.",
    ),
    "trial-registration": Statement(
        "Trial registration",
        r"(?:clinical )?trial registration|registration (?:number|details|information)|trial "
        r"(?:number|identifier|registry)|clinical trial number|study registration",
        "The registry and the trial's number in it.",
    ),
    "use-of-ai": Statement(
        "Use of AI",
        r"(?:declaration|disclosure|statement) (?:of|on|regarding) (?:the )?(?:use of )?"
        r"(?:generative )?(?:ai|artificial intelligence)(?: and ai[- ]assisted technologies)?"
        r"(?: in (?:the )?(?:scientific )?writing(?: process)?)?|(?:generative )?(?:ai|"
        r"artificial intelligence)(?: use)? (?:disclosure|statement|declaration)|use of "
        r"(?:generative )?(?:ai|artificial intelligence)(?: tools)?(?: (?:in|for|during) "
        r"(?:the )?(?:writing|preparation)(?: of (?:the|this) (?:manuscript|paper|article))?"
        r"(?: process)?)?",
        "Whether and how AI tools were used in the work or the writing.",
    ),
}

#: A Word bookmark at a paragraph's start, as pandoc writes one: `[]{#_Hlk1 .anchor}`.
_ANCHORS = r"(?:\[\]\{[^}\n]*\}[ \t]*)*"
#: The marks that open or close emphasis: bold and italic, bold, or italic.
_MARK = r"(?:\*\*\*|\*\*|__|\*|_)"
#: A heading's number: "5.", "5", "2.1", "IV.", "A)".
_NUMBER = r"(?:(?:\d+(?:\.\d+)*|[ivxlc]+|[a-z])[.)][ \t]+|\d+(?:\.\d+)*[ \t]+)?"
#: A word before the label, at most two of them: "Statement of", "Human".
_LEAD = r"(?:[^\s*_:.]+[ \t]+){0,2}"
#: A word a label may end in: "Data availability statement", "Ethics declarations".
_TAIL = r"(?:[ \t]+(?:statements?|declarations?|disclosures?|information|details|section))?"
#: Where a label in a heading or in marked words ends: at the marks that close it, a colon,
#: a stop, a heading's attributes or the end of the line.
_END = r"(?=[ \t]*(?:\*\*\*|\*\*|__|\*|_|[:.]|\{|$))"


def pattern(labels: str) -> str:
    """What finds a statement whose label is one of `labels`, in the text as Markdown writes
    it: a heading that opens with it, after its number; the marked words a paragraph opens
    with ("**Funding:**", "*Ethics approval.*"); or a paragraph that opens with it in plain
    type, followed by a colon ("Funding: none"). The label ends where it does, and at most
    two words stand before it."""
    label = rf"{_LEAD}\b(?:{labels}){_TAIL}"
    return ("(?im)^(?:"
            rf"#{{1,6}}[ \t]+{_ANCHORS}{_NUMBER}{_MARK}?[ \t]*{label}{_END}"
            rf"|[ \t]*{_ANCHORS}{_MARK}(?=[^\s*_]){label}{_END}"
            rf"|[ \t]*{_ANCHORS}{label}[ \t]*:"
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
