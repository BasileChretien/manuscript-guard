"""G4: the manuscript's own declarations are held to authors.yaml.

`authors.yaml` records, per author, the grants (`funding`), the competing interests
(`competing_interests`) and the CRediT roles (`credit`), and the ethics lead's approval
reference (`roles.ethics_lead.approval`). `submit` writes declarations from them, and no
gate read the manuscript's own statements against them: a paper could say "This work
received no funding" while the record listed a grant, and every gate passed. The rules
are Basile's (DESIGN.md, "The declarations are held to authors.yaml"):

- `funding-grant-missing`: an entry of an author's `funding` is not in the funding
  statement. An entry is found by each of its words that holds a digit, its grant
  identifier; one with no such word is found by its words.
- `funding-denied`: the funding statement says there was none, and some author's `funding`
  is not empty.
- `interests-author-missing`: an author whose `competing_interests` declares an interest is
  not named, by family name, in the competing interests statement.
- `interests-none-contradicted`: the statement says no author has an interest, and one's
  record declares one.
- `interests-unfilled`: an author's `competing_interests` is empty while another's is
  filled. An empty field is not a declaration of none.
- `ethics-approval-missing`: the ethics lead's approval reference is not in an Ethics
  section, the Methods or the Declarations, of the main text or the supplement.
- `ethics-approval-denied`: the manuscript says no approval was needed, and the record
  gives one.
- `credit-author-missing`, `credit-role-missing`: where the manuscript has an author
  contributions statement, an author with recorded roles is not named in it, by family
  name or initials, or a role recorded is not in it in CRediT's words.

Each is a warning until submission and a failure there. Two notes, `funding-not-stated` and
`interests-not-stated`, say that the record has something to declare and the manuscript has
no statement of that kind: a journal that asks for one has G4's required statements, and
one that collects it on its form has the file `submit` writes. With no authors.yaml, or
none of these fields filled, nothing is said.

Where a statement is, and the phrases that say none, are in `data/disclosures.yaml`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import AUTHORS_FILE, Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report

GATE = "G4"
DATA = Path(__file__).parent.parent / "data" / "disclosures.yaml"

FUNDING, INTERESTS, ETHICS, CONTRIBUTIONS, DECLARATIONS = (
    "funding", "interests", "ethics", "contributions", "declarations")  # fmt: skip

GRANT_MISSING = "funding-grant-missing"
FUNDING_DENIED = "funding-denied"
FUNDING_NOT_STATED = "funding-not-stated"
INTERESTS_AUTHOR_MISSING = "interests-author-missing"
INTERESTS_NONE_CONTRADICTED = "interests-none-contradicted"
INTERESTS_UNFILLED = "interests-unfilled"
INTERESTS_NOT_STATED = "interests-not-stated"
APPROVAL_MISSING = "ethics-approval-missing"
APPROVAL_DENIED = "ethics-approval-denied"
CREDIT_AUTHOR_MISSING = "credit-author-missing"
CREDIT_ROLE_MISSING = "credit-role-missing"

#: Every dash a hyphen, every curly quotation mark a straight one.
_DASHES = dict.fromkeys(
    (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE58, 0xFE63, 0xFF0D), "-")
_QUOTES = {**dict.fromkeys((0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x02BC), "'"),
           **dict.fromkeys((0x201C, 0x201D, 0x201E, 0x2033), '"')}  # fmt: skip
#: What separates the parts of a grant identifier: white space, a dash, a slash, a point or
#: an underscore.
_SEPARATOR = r"[\s\-/._]"
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
#: A paragraph that opens with a label: "**Funding:** ...", "*Competing interests.* ...",
#: "Funding: ...". Emphasised, the label may end in a colon or a full stop, inside or
#: outside the marks; plain, only in a colon, so that a sentence is no label.
_LABEL = re.compile(
    r"^[ \t]*(?:(?P<mark>\*\*|__|\*|_)(?P<marked>[^\n*_:.]{1,60}?)[ \t]*[:.]?(?P=mark)"
    r"[ \t]*[:.]?|(?P<plain>[^\n*_:.#>|]{1,60}?)[ \t]*:)"
)
#: A label holds at most this many words: more is a sentence. Alone in its paragraph, fewer:
#: "Ethics approval and consent to participate" (BMC) is the longest.
_LABEL_WORDS = 8
_ALONE_WORDS = 6


# ----------------------------------------------------------------------------- folding


def fold(text: str) -> str:
    """Text as the phrases of `data/disclosures.yaml` read it: accents taken off, case one,
    dashes and quotation marks straight, white space one space."""
    from manuscript_guard.gates.authors import LETTERS

    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.translate(_DASHES).translate(_QUOTES).casefold().translate(LETTERS)
    return " ".join(text.split())


def words(text: str) -> str:
    """`text` as a row of words, as an entry, a name or a role is found: folded, `&` read as
    "and", apostrophes taken out ("O'Brien" is "obrien") and every other mark a space."""
    folded = fold(text).replace("&", " and ").replace("'", "")
    return " ".join(re.sub(r"[\W_]+", " ", folded).split())


def _in_words(phrase: str, text: str) -> bool:
    wanted = words(phrase)
    return bool(wanted) and f" {wanted} " in f" {words(text)} "


def identifiers(entry: str) -> list[str]:
    """The words of a funding entry or an approval reference that hold a digit, with the
    marks around each taken off: its grant identifier ("ANR-20-CE17-0001", "12345")."""
    found = []
    for word in str(entry).split():
        bare = re.sub(r"^[\W_]+|[\W_]+$", "", word)
        if any(c.isdigit() for c in bare):
            found.append(bare)
    return found


def _identifier_pattern(token: str) -> re.Pattern[str]:
    """What finds `token` in folded text: its runs of letters and of digits in order, a
    separator optional between a letter and a digit and needed between two runs of one
    kind, which `token` writes apart; and no digit before or after its digits, no letter
    before or after its letters, so that "12345" is not found in "123456"."""
    atoms = re.findall(r"\d+|[^\W\d_]+", fold(token))
    parts = []
    for index, atom in enumerate(atoms):
        if index:
            same = atom[0].isdigit() == atoms[index - 1][0].isdigit()
            parts.append(f"{_SEPARATOR}+" if same else f"{_SEPARATOR}*")
        parts.append(re.escape(atom))
    if not atoms:
        return re.compile(r"(?!x)x")
    before = r"(?<!\d)" if atoms[0][0].isdigit() else r"(?<![^\W\d_])"
    after = r"(?!\d)" if atoms[-1][-1].isdigit() else r"(?![^\W\d_])"
    return re.compile(before + "".join(parts) + after)


def names_identifier(text: str, token: str) -> bool:
    """Whether `text` gives the grant identifier `token`, however its parts are joined."""
    return bool(_identifier_pattern(token).search(fold(text)))


def entry_named(text: str, entry: str) -> bool:
    """Whether `text` gives a funding entry or an approval reference: each of its words that
    holds a digit, or, where none does, its words in a row."""
    tokens = identifiers(entry)
    if tokens:
        return all(names_identifier(text, token) for token in tokens)
    return _in_words(entry, text)


def missing_identifiers(text: str, entry: str) -> list[str]:
    return [token for token in identifiers(entry) if not names_identifier(text, token)]


# ------------------------------------------------------------------------------ phrases


_FRAGMENT = re.compile(r"\$\{(\w+)\}")


@lru_cache(maxsize=1)
def _data() -> dict:
    """`data/disclosures.yaml`, each `${name}` in its patterns the fragment of that name."""
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    fragments = {name: str(text).strip() for name, text in
                 (document.pop("fragments", None) or {}).items()}  # fmt: skip

    def filled(pattern: str) -> str:
        return _FRAGMENT.sub(lambda found: fragments[found[1]], str(pattern).strip())

    return {key: ({kind: filled(p) for kind, p in value.items()} if isinstance(value, dict)
                  else [filled(p) for p in value] if isinstance(value, list) else value)
            for key, value in document.items()}  # fmt: skip


@cache
def _pattern(source: str) -> re.Pattern[str]:
    return re.compile(source)


#: A heading's number, taken off before its words are read: "6.", "6.1", "6.1.", "VI.", "7".
_NUMBER = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?|[IVX]+\.?)\s+")


def _heading_kinds(title: str) -> list[str]:
    folded = fold(_NUMBER.sub("", re.sub(r"[*_`]", "", title)))
    return [kind for kind, pattern in _data()["headings"].items()
            if _pattern(pattern).search(folded)]  # fmt: skip


def _acknowledgements(title: str) -> bool:
    return bool(re.search(r"\backnowledge?ments?\b", fold(title)))


def _whole(text: str, patterns: Iterable[str]) -> bool:
    said = fold(text).rstrip(" .;:!")
    return bool(said) and any(_pattern(f"(?:{p})").fullmatch(said) for p in patterns)


def is_none_statement(text: str) -> bool:
    """Whether a record's `competing_interests`, or a whole statement, says there is none:
    "None declared.", "The authors declare no competing interests"."""
    return _whole(text, _data()["none"])


def _first(patterns: Iterable[str], text: str) -> bool:
    folded = fold(text)
    return any(_pattern(p).search(folded) for p in patterns)


# ------------------------------------------------------------------------------- places


@dataclass(frozen=True)
class Place:
    """A part of the manuscript that is a statement of one kind: a heading's section, or a
    paragraph opened by a label."""

    kind: str
    title: str
    text: str


def paragraphs(text: str) -> list[str]:
    return [piece for piece in _BLANK_LINE.split(text) if piece.strip()]


def _label(paragraph: str) -> tuple[str, str] | None:
    """The label a paragraph opens with and what follows it, where it has one. A label alone
    in its paragraph, as a conversion from Word writes "**Funding**", has fewer words: a
    sentence in italics is no label."""
    found = _LABEL.match(paragraph)
    if found is None:
        return None
    label = (found["marked"] or found["plain"] or "").strip()
    rest = paragraph[found.end():]
    most = _LABEL_WORDS if rest.strip() else _ALONE_WORDS
    if not label or len(label.split()) > most or (not rest.strip() and re.search(r"\d", label)):
        return None
    return label, rest


def _own(enclosed: str, kind: str) -> str:
    """A section's text up to a heading or a label inside it that opens a statement of
    another kind: "# Competing interests" over "## Author contributions", or over a
    paragraph "**Funding:** ...", holds only its own statement."""
    kept = []
    for paragraph in paragraphs(enclosed):
        head = re.match(r"[ \t]*#+[ \t]+(.*)", paragraph)
        labelled = None if head else _label(paragraph)
        title = head[1] if head else labelled[0] if labelled else None
        kinds = _heading_kinds(title) if title else []
        if kinds and kind not in kinds:
            break
        kept.append(paragraph)
    return "\n\n".join(kept)


def _labelled(printed: str) -> Iterator[tuple[str, str]]:
    """Each label of `printed` with what it heads: the rest of its paragraph, or, where that
    is blank, the paragraphs after it up to the next heading or label of a statement. "AE:
    Conceptualization." is a label of no statement, and is read as part of the one above."""

    def heads(paragraph: str) -> bool:
        labelled = _label(paragraph)
        return labelled is not None and bool(_heading_kinds(labelled[0]))

    pieces = paragraphs(printed)
    for index, paragraph in enumerate(pieces):
        labelled = _label(paragraph)
        if labelled is None:
            continue
        label, rest = labelled
        if not rest.strip():
            following = []
            for later in pieces[index + 1:]:
                if later.lstrip().startswith("#") or heads(later):
                    break
                following.append(later)
            rest = "\n\n".join(following)
        yield label, rest


def places(text: str, abstract: str | None = None) -> list[Place]:
    """Each statement of the kinds `data/disclosures.yaml` names in `text`: the section of a
    heading that names it, and each paragraph whose label does; and the Methods, as
    `methods`, by the test G9 reads them by. Comments and fenced listings are blanked
    first, as G4 reads every required statement."""
    from manuscript_guard.text.blocks import scannable
    from manuscript_guard.text.section_names import methods_sections
    from manuscript_guard.text.sections import split_sections

    printed = scannable(text)
    sections = split_sections(printed)
    found: list[Place] = []
    for section in sections:
        if not section.title:
            continue
        for kind in _heading_kinds(section.title):
            text = section.enclosed if kind == DECLARATIONS else _own(section.enclosed, kind)
            found.append(Place(kind, section.title, text))
    for section in methods_sections(sections, abstract):
        found.append(Place("methods", section.title, section.enclosed))
    for label, rest in _labelled(printed):
        for kind in _heading_kinds(label):
            found.append(Place(kind, label, rest))
    return found


def _of(found: Iterable[Place], *kinds: str) -> list[Place]:
    return [place for place in found if place.kind in kinds]


def _shown(text: str, limit: int = 200) -> str:
    said = " ".join(text.split())
    return said if len(said) <= limit else said[: limit - 1].rstrip() + "\N{HORIZONTAL ELLIPSIS}"


def _saying(found: Iterable[Place], patterns: Iterable[str]) -> str | None:
    """The first paragraph of `found` that says what one of `patterns` reads, as written."""
    patterns = list(patterns)
    for place in found:
        for paragraph in paragraphs(place.text):
            if _first(patterns, paragraph):
                return _shown(paragraph)
    return None


def _says_none(found: Iterable[Place], whole: Iterable[str]) -> str | None:
    """The first place whose whole text says none, by `whole`."""
    whole = list(whole)
    for place in found:
        if _whole(place.text, whole):
            return _shown(place.text) or place.title
    return None


# ------------------------------------------------------------------------------ authors


def _people(authors: object) -> list[dict]:
    """The authors of authors.yaml that are mappings. A file of another shape is the
    schema's to report (`authors-incomplete`); this check reads what it can of it."""
    listed = authors.get("authors") if isinstance(authors, dict) else None
    return [a for a in listed if isinstance(a, dict)] if isinstance(listed, list) else []


def _field(author: dict, key: str) -> str:
    """A text field of an author, or "" where it holds no text."""
    value = author.get(key)
    return value.strip() if isinstance(value, str) else ""


def _name(author: dict) -> str:
    return " ".join(_field(author, part) for part in ("given", "family")).strip()


def _initials(author: dict) -> str:
    """The initials `submit` prints for an author (`build.submission._initials`)."""
    from manuscript_guard.build.submission import _initials as printed

    if not _field(author, "given") or not _field(author, "family"):
        return ""
    try:
        return printed(author)
    except (IndexError, KeyError, TypeError, AttributeError):
        return ""


def _texts(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def author_named(author: dict, text: str) -> bool:
    """Whether `text` names `author`: by family name, or by the initials `submit` prints,
    "A.E." or "AE"."""
    family = _field(author, "family")
    if family and _in_words(family, text):
        return True
    letters = re.findall(r"[^\W\d_]", fold(_initials(author)))
    if not letters:
        return False
    said = f" {words(text)} "
    return f" {' '.join(letters)} " in said or f" {''.join(letters)} " in said


def _role_words(text: str) -> str:
    """A role as it is found: in words, "-isation" read as CRediT's "-ization"."""
    return re.sub(r"isation\b", "ization", words(text))


def role_named(role: str, text: str) -> bool:
    wanted = _role_words(role)
    return bool(wanted) and f" {wanted} " in f" {_role_words(text)} "


def _approval(authors: object) -> str | None:
    roles = authors.get("roles") if isinstance(authors, dict) else None
    lead = roles.get("ethics_lead") if isinstance(roles, dict) else None
    approval = lead.get("approval") if isinstance(lead, dict) else None
    return approval.strip() if isinstance(approval, str) and approval.strip() else None


def something_to_check(authors: object) -> bool:
    """Whether authors.yaml fills any field this check reads."""
    if not isinstance(authors, dict):
        return False
    people = _people(authors)
    return bool(_approval(authors)) or any(
        _texts(a.get("funding")) or _texts(a.get("credit"))
        or _field(a, "competing_interests") for a in people)  # fmt: skip


# -------------------------------------------------------------------------------- judge


def judge(authors: dict, main: str, supplement: str = "", *, submission: bool = False,
          path: Path | None = None, abstract: str | None = None) -> Report:  # fmt: skip
    """What G4 says of the manuscript's declarations, `main` its main text and `supplement`
    its supplement, against `authors`, the contents of authors.yaml."""
    if not something_to_check(authors):
        return Report()
    found = places(main, abstract) + places(supplement, abstract)
    severity = FAIL if submission else WARN
    findings: list[Finding] = []
    for check in (_funding, _interests, _ethics, _contributions):
        findings += check(authors, found, main + "\n\n" + supplement, severity, path)
    return Report(tuple(findings))


def _finding(code: str, severity: str, path: Path | None, message: str, hint: str,
             context: str | None = None) -> Finding:  # fmt: skip
    return Finding(gate=GATE, code=code, severity=severity, path=path, message=message,
                   hint=hint, context=context)  # fmt: skip


def _funding(authors: dict, found: list[Place], _whole_text: str, severity: str,
             path: Path | None) -> Iterator[Finding]:  # fmt: skip
    entries = [(author, entry) for author in _people(authors)
               for entry in _texts(author.get("funding"))]  # fmt: skip
    if not entries:
        return
    stated = _of(found, FUNDING)
    recorded = "; ".join(f"{_name(author)}: {entry}" for author, entry in entries)
    if not stated:
        yield _finding(
            FUNDING_NOT_STATED, INFO, path,
            "authors.yaml records funding, and the manuscript has no funding statement",
            f"write a Funding section that gives each grant authors.yaml records ({recorded}); "
            "a journal that collects funding on its form has it from the declarations "
            "`submit` writes")  # fmt: skip
        return
    statement = "\n\n".join(place.text for place in stated)
    # "None" says none only where a funding heading or label opens it: under the
    # Acknowledgements it says there is no one to thank. And a statement that gives a grant
    # authors.yaml records denies nothing, whatever else a sentence of it says.
    headed = [place for place in stated if not _acknowledgements(place.title)]
    granted = any(identifiers(entry) and not missing_identifiers(statement, entry)
                  for _author, entry in entries)  # fmt: skip
    denial = None if granted else (_saying(stated, _data()["no_funding"])
                                   or _says_none(headed, _data()["none_funding"]))  # fmt: skip
    if denial is not None:
        yield _finding(
            FUNDING_DENIED, severity, path,
            "the funding statement says the work received no funding, and authors.yaml "
            f"records funding: {recorded}",
            "name each grant in the funding statement as authors.yaml records it; if the "
            "work had no funding, the record is what is wrong: take the entries out of "
            "`funding` in authors.yaml", denial)  # fmt: skip
        return
    for author, entry in entries:
        if entry_named(statement, entry):
            continue
        missing = missing_identifiers(statement, entry)
        given = ", ".join(missing) if missing else entry
        yield _finding(
            GRANT_MISSING, severity, path,
            f"the funding statement does not give {given}, which authors.yaml records for "
            f"{_name(author)} ({entry})",
            f"write the grant in the funding statement as authors.yaml records it, \"{entry}\"; "
            "if the record is wrong, correct it under `funding` in authors.yaml")  # fmt: skip


def _interests(authors: dict, found: list[Place], _whole_text: str, severity: str,
               path: Path | None) -> Iterator[Finding]:  # fmt: skip
    people = _people(authors)
    recorded = {id(a): _field(a, "competing_interests") for a in people}
    if not any(recorded.values()):
        return
    for author in people:
        if not recorded[id(author)]:
            yield _finding(
                INTERESTS_UNFILLED, severity, path,
                f"authors.yaml records no competing interests for {_name(author)}: an empty "
                "field is not a declaration of none",
                f"write what {_name(author)} declares under `competing_interests` in "
                "authors.yaml, or \"None declared.\" where there is nothing")  # fmt: skip
    declared = [a for a in people
                if recorded[id(a)] and not is_none_statement(recorded[id(a)])]  # fmt: skip
    if not declared:
        return
    stated = _of(found, INTERESTS)
    listed = "; ".join(f"{_name(a)}: {recorded[id(a)]}" for a in declared)
    if not stated:
        yield _finding(
            INTERESTS_NOT_STATED, INFO, path,
            "authors.yaml records competing interests, and the manuscript has no competing "
            "interests statement",
            f"write a Competing interests section that names each author with what they "
            f"declare ({listed})")  # fmt: skip
        return
    collective = (_says_none(stated, _data()["none"])
                  or _saying(stated, _data()["collective_none"]))  # fmt: skip
    if collective is not None:
        yield _finding(
            INTERESTS_NONE_CONTRADICTED, severity, path,
            "the competing interests statement says no author has an interest, and "
            f"authors.yaml records interests: {listed}",
            "name each of these authors in the statement with what they declare; if they "
            "have none, the record is what is wrong: write \"None declared.\" under "
            "`competing_interests` in authors.yaml", collective)  # fmt: skip
        return
    statement = "\n\n".join(place.text for place in stated)
    for author in declared:
        if author_named(author, statement):
            continue
        initials = _initials(author)
        yield _finding(
            INTERESTS_AUTHOR_MISSING, severity, path,
            f"the competing interests statement does not name {_name(author)}, whose "
            "interests authors.yaml records",
            f"name {_field(author, 'family')}"
            + (f" or {initials}" if initials else "")
            + " in the statement with what authors.yaml records: "
            f"\"{recorded[id(author)]}\"; if the record is wrong, correct "
            "`competing_interests` in authors.yaml")  # fmt: skip


def _ethics(authors: dict, found: list[Place], whole_text: str, severity: str,
            path: Path | None) -> Iterator[Finding]:  # fmt: skip
    approval = _approval(authors)
    if approval is None:
        return
    from manuscript_guard.text.blocks import scannable

    denial = _saying([Place(ETHICS, "", scannable(whole_text))], _data()["no_approval"])
    if denial is not None:
        yield _finding(
            APPROVAL_DENIED, severity, path,
            "the manuscript says no ethical approval was needed, and authors.yaml records "
            f"the approval {approval}",
            "give the committee and the approval's reference in the Ethics statement or the "
            "Methods; if no approval was needed, the record is what is wrong: correct "
            "`roles.ethics_lead.approval` in authors.yaml", denial)  # fmt: skip
        return
    where = _of(found, ETHICS, DECLARATIONS, "methods")
    if any(entry_named(place.text, approval) for place in where):
        return
    yield _finding(
        APPROVAL_MISSING, severity, path,
        f"the manuscript does not give the ethics approval {approval}, which authors.yaml "
        "records",
        f"give the committee and the reference, \"{approval}\", in an Ethics section, the "
        "Methods or the Declarations, as `roles.ethics_lead.approval` in authors.yaml "
        "records it; if the record is wrong, correct it there")  # fmt: skip


def _contributions(authors: dict, found: list[Place], _whole_text: str, severity: str,
                   path: Path | None) -> Iterator[Finding]:  # fmt: skip
    credited = [(a, _texts(a.get("credit"))) for a in _people(authors)]
    credited = [(a, roles) for a, roles in credited if roles]
    stated = _of(found, CONTRIBUTIONS)
    if not credited or not stated:
        # Many journals collect CRediT in the submission form: no statement, nothing said.
        return
    statement = "\n\n".join(place.text for place in stated)
    for author, roles in credited:
        if author_named(author, statement):
            continue
        initials = _initials(author)
        yield _finding(
            CREDIT_AUTHOR_MISSING, severity, path,
            f"the author contributions statement does not name {_name(author)}, whose CRediT "
            "roles authors.yaml records",
            f"name them by family name or as {initials or 'their initials'}, with the roles "
            f"authors.yaml records: {', '.join(roles)}; if the record is wrong, correct "
            "`credit` in authors.yaml")  # fmt: skip
    held: dict[str, list[str]] = {}
    for author, roles in credited:
        for role in roles:
            held.setdefault(role, []).append(_initials(author) or _name(author))
    for role, holders in held.items():
        if role_named(role, statement):
            continue
        yield _finding(
            CREDIT_ROLE_MISSING, severity, path,
            f"the author contributions statement does not give the CRediT role \"{role}\", "
            f"which authors.yaml records for {', '.join(holders)}",
            f"write the role in CRediT's words, \"{role}\", with who held it; if the record "
            "is wrong, correct `credit` in authors.yaml")  # fmt: skip


# -------------------------------------------------------------------------------- check


def check_disclosures(project: Project, stage: str | None = None) -> Report:
    """G4's check of the declarations on the project, at `stage` (the module's docstring)."""
    from manuscript_guard.policy import SUBMISSION

    authors = project.authors
    if not something_to_check(authors) or not project.path("manuscript").is_dir():
        return Report()
    from manuscript_guard.gates.ai_use import supplement_text
    from manuscript_guard.gates.journal import abstract_title, main_text

    return judge(authors, main_text(project), supplement_text(project),
                 submission=stage == SUBMISSION, path=project.root / AUTHORS_FILE,
                 abstract=abstract_title(project))  # fmt: skip


__all__ = [
    "check_disclosures", "entry_named", "identifiers", "is_none_statement", "judge",
    "names_identifier", "places", "role_named", "words",
]  # fmt: skip
