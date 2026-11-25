"""A journal's profile and the authors' names from the audit page's form, as the files
`audit --journal` and `audit --authors` read (docs/audit-page.md).

A reader of the page types what the journal's instructions for authors say: its limits, the
sections and the headings of a structured abstract it asks for, the statements it requires,
and how its peer review is blinded. Nothing is guessed: a limit left empty is not in the
profile, and is not checked. Each statement ticked is found as G4 finds any profile's, by a
pattern on the text as Markdown writes it (a .docx and a LaTeX paper are read that way too):
a heading whose whole title names statements, as G7 and G8 read a statement's heading
(`section_names.STATEMENT_TITLE`), one of them this one ("Funding", "Funding/Support",
"Acknowledgements and funding"); the marked words a paragraph opens with, all of them such
names ("**Funding:**"); or such names in plain type a paragraph opens with, before a colon
("Funding: none"). A sentence that mentions funding, and a heading on the subject ("Funding of
mental health services"), state nothing.

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
    """A statement a journal may require: its name on the page, the words that say a
    statement's title is this one (a regular expression's alternatives, matched as words, in
    any case), and what the report says it should hold."""

    shown: str
    words: str
    why: str


#: The statements the page offers, by their id in the profile: each with the words that
#: say it is this one among the names of a statement's title (`pattern`).
STATEMENTS: dict[str, Statement] = {
    "funding": Statement(
        "Funding",
        r"fund(?:ing|ers?)|support|sponsor(?:s|ship)?|grants?",
        "Funding sources, or a statement that the work received none.",
    ),
    "competing-interests": Statement(
        "Competing interests",
        r"interests?|(?<!ai )(?<!ai-)disclosures?",
        "Competing interests for every author, or a statement that there are none.",
    ),
    "ethics": Statement(
        "Ethics approval",
        r"ethic(?:s|al)|institutional review board",
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
        r"data",
        "Where the data are, and on what terms.",
    ),
    "author-contributions": Statement(
        "Author contributions",
        r"contribut\w*|credit|author roles",
        "What each author did.",
    ),
    "trial-registration": Statement(
        "Trial registration",
        r"registration|registry|trial (?:number|identifier)",
        "The registry and the trial's number in it.",
    ),
    "use-of-ai": Statement(
        "Use of AI",
        r"ai|artificial intelligence",
        "Whether and how AI tools were used in the work or the writing.",
    ),
}

#: Names of a statement journals print that `section_names.STATEMENT_NAMES`, which G7 and G8
#: read, does not hold; the form's patterns read both.
EXTRA_NAMES = (
    r"(?:"
    r"disclosures?\s+of\s+(?:potential\s+)?conflicts?\s+of\s+interests?"
    r"|statements?\s+of\s+(?:(?:competing|conflicting)\s+interests?|ethics|funding)"
    r"|duality\s+of\s+interests?|grant\s+support"
    r"|compliance\s+with\s+ethical\s+standards|ethics\s+and\s+dissemination"
    r"|institutional\s+review\s+board(?:\s+approval)?"
    r"|data(?:,?\s+(?:and\s+)?(?:materials?|code|software))+,?\s+availability"
    r"|data\s+accessibility"
    r"|(?:(?:clinical\s+)?trial\s+|study\s+)?registration(?:\s+(?:number|details|information))?"
    r"|clinical\s+trial\s+(?:number|identifier|registry)"
    r"|credit\s+authorship\s+contribution"
    r"|authors?['\N{RIGHT SINGLE QUOTATION MARK}]s\s+contributions?"
    r"|(?:declarations?|disclosures?|statements?)\s+(?:of|on|regarding)\s+(?:the\s+)?"
    r"(?:use\s+of\s+)?(?:generative\s+)?(?:ai|artificial\s+intelligence)\b[\w\s-]*"
    r"|(?:generative\s+)?(?:ai|artificial\s+intelligence)(?:\s+use)?\s+(?:disclosure|"
    r"statement|declaration)"
    r"|use\s+of\s+(?:generative\s+)?(?:ai|artificial\s+intelligence)(?:\s+tools?)?(?:\s+"
    r"(?:in|for|during)\s+(?:the\s+)?(?:writing|preparation)\b[\w\s-]*)?"
    r")(?:\s+(?:statements?|declarations?|disclosures?|section))?"
)


def _on_a_line(names: str) -> str:
    """`names` read within a line: a space or a tab where they take any white space."""
    return names.replace(r"[\w\s-]*", r"[\w \t-]*").replace(r"\s", r"[ \t]")


def _names() -> str:
    from manuscript_guard.text.section_names import STATEMENT_NAMES

    return rf"(?:{_on_a_line(STATEMENT_NAMES)}|{_on_a_line(EXTRA_NAMES)})"


#: A Word bookmark, as pandoc writes one: `[]{#_Hlk1 .anchor}`.
_ANCHORS = r"(?:\[\]\{[^}\n]*\}[ \t]*)*"
#: The marks that open or close emphasis: bold and italic, bold, or italic.
_MARK = r"(?:\*\*\*|\*\*|__|\*|_)"
#: A heading's number, as `section_names` reads one: "2", "2.1.", "II.", "A)", "(2)".
_NUMBER = r"(?:(?:\(\d+\)|\d+(?:\.\d+)*[.)]?|[ivxlc]+[.)]|[a-z][.)])[ \t]+)?"


def pattern(words: str) -> str:
    """What finds a statement whose words are `words`, in the text as Markdown writes it: a
    heading whose whole title names statements (`section_names.STATEMENT_TITLE`'s names, and
    `EXTRA_NAMES`), "Funding", "Funding/Support", "Ethics approval and consent to
    participate", one of them this one; the marked words a paragraph opens with, all of them
    such names ("**Funding:**", "*Ethics approval.*"); or a paragraph that opens with such
    names in plain type, before a colon ("Funding: none"). A heading that only opens with
    one, "Funding of mental health services", names the paper's own matter."""
    names = _names()
    title = rf"(?:the[ \t]+)?{names}(?:[ \t]*(?:,[ \t]*(?:and\b)?|;|&|/|\band\b)[ \t]*{names})*"
    word = rf"\b(?:{words})\b"
    return ("(?im)^(?:"
            rf"#{{1,6}}[ \t]+{_ANCHORS}{_NUMBER}{_MARK}?[ \t]*"
            rf"(?={title}[^\w\n]*(?:\{{[^}}\n]*\}}[ \t]*)?$)[^\n]*?{word}"
            rf"|[ \t]*{_ANCHORS}{_MARK}(?=[^\s*_]){_ANCHORS}"
            rf"(?={title}[ \t]*[:.]?[ \t]*{_MARK})[^\n:*_]*?{word}"
            rf"|[ \t]*{_ANCHORS}(?={title}[ \t]*:)[^\n:]*?{word}"
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
            {"id": one, "pattern": pattern(STATEMENTS[one].words), "why": STATEMENTS[one].why}
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
