"""The answers file, `design/setup.yaml`, read and held to what each answer may be.

An agent writes the answers with its file tools, as the authors give them, so that no title
or name passes through a shell. What it wrote is read here every time, held to the schema and
then to what a schema cannot say: that an ORCID iD's check digit is right, that the
statistician named is an author, that the data's folder is inside the project. An answer that
fails is a problem of its question, which stays open with the reason, and nothing is written
from it.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import _plain, load_schema
from manuscript_guard.setup.folder import Folder, SetupRefused

ANSWERS_FILE = "design/setup.yaml"
SCHEMA = "manuscript-guard/setup/1"
#: What puts a decision off: nothing is written for it.
LATER = "later"
#: The answers that are mappings of answers, each of its keys a question of its own.
GROUPS = ("data", "repository")
#: Folders of the project that hold what the toolkit writes or reads as its own.
RESERVED = frozenset({"analysis", "results", "build", "manuscript", "literature", "design",
                      "figures", "review", "profiles", "approvals", "checks", "receipts",
                      ".git", ".github", ".manuscript-guard"})  # fmt: skip
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
_VALIDATOR = Draft202012Validator(load_schema("setup"))
MISSING = object()


def answer(answers: dict, place: str) -> Any:
    """The answer written at `place`, a question's id (`data.where`), or `MISSING`."""
    held: Any = answers
    for part in place.split("."):
        if not isinstance(held, dict) or part not in held:
            return MISSING
        held = held[part]
    return held


def load_answers(root: Path) -> dict:
    """The answers in `root`'s `design/setup.yaml`, none where it is not there;
    `SetupRefused` where it is not a file of answers at all."""
    path = Path(root) / ANSWERS_FILE
    if not path.is_file():
        return {}
    try:
        read = _plain(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise SetupRefused(f"{ANSWERS_FILE} cannot be read as YAML ({exc}); write it again "
                           "with each answer at its question's place") from exc  # fmt: skip
    if read is None:
        return {}
    if not isinstance(read, dict):
        raise SetupRefused(f"{ANSWERS_FILE} holds no answers, one `question: answer` to a line")
    return read


def _question_of(path: list) -> str:
    """The question whose answer a schema error is about."""
    first = str(path[0]) if path else "schema"
    if first in GROUPS and len(path) > 1 and isinstance(path[1], str):
        return f"{first}.{path[1]}"
    return first


def schema_problems(answers: dict) -> dict[str, str]:
    """Each question whose answer the schema refuses, with the first reason."""
    problems: dict[str, str] = {}
    for error in sorted(_VALIDATOR.iter_errors(answers), key=lambda e: list(e.absolute_path)):
        place = _question_of(list(error.absolute_path))
        if error.validator == "additionalProperties" and not error.absolute_path:
            extra = sorted(set(answers) - set(_VALIDATOR.schema["properties"]))
            place = extra[0] if extra else "schema"
            problems.setdefault(place, f"no question is answered at `{place}`")
            continue
        problems.setdefault(place, error.message)
    return problems


def orcid_ok(orcid: str) -> bool:
    """ORCID's check digit, ISO 7064 11,2, as ORCID documents it."""
    digits = orcid.replace("-", "")
    total = 0
    for digit in digits[:-1]:
        total = (total + int(digit)) * 2
    check = (12 - total % 11) % 11
    return digits[-1] == ("X" if check == 10 else str(check))


def journal_slug(name: str) -> str:
    """The name a journal's profile is kept under: its name in lower-case letters and digits,
    the rest a hyphen. "BMJ Open" is `bmj-open`."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def names_an_author(said: str, authors: list) -> bool:
    """`said` names one of `authors`, as `approve --as` and `sign --as` name one: by ORCID iD,
    family name or full name."""
    said = " ".join(said.split()).casefold()
    for author in authors:
        if not isinstance(author, dict):
            continue
        given, family = str(author.get("given", "")), str(author.get("family", ""))
        if said in {family.casefold(), f"{given} {family}".casefold(),
                    str(author.get("orcid", "")).casefold()}:  # fmt: skip
            return True
    return False


def _author_problem(authors: list) -> str | None:
    for number, author in enumerate(authors, 1):
        orcid = author.get("orcid")
        if orcid is not None and not orcid_ok(orcid):
            return f"author {number}'s ORCID iD {orcid} has a wrong check digit"
        email = author.get("email")
        if email is not None and not _EMAIL.match(email):
            return f"author {number}'s e-mail address {email!r} is not an address"
    if not any(author.get("corresponding") for author in authors):
        return "no author is the corresponding author: mark one with `corresponding: true`"
    return None


def _folder_problem(folder_name: str, root: Path) -> str | None:
    relative = Path(folder_name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return (f"{folder_name!r} is not a folder inside the project; data held elsewhere are "
                "`vault` or `site`")  # fmt: skip
    if relative.parts[0] in RESERVED:
        return f"{relative.parts[0]}/ is the toolkit's own folder; the data need one of theirs"
    if (root / relative).is_file():
        return f"{folder_name} is a file, not a folder"
    return None


def _start_problem(start: Any, answers: dict, folder: Folder) -> str | None:
    if start in ("markdown", "latex") or (_word(start) and start in folder.candidates):
        return None
    return f"{start!r} is neither `markdown`, `latex` nor a .docx in this folder"


def _title_problem(title: Any, answers: dict, folder: Folder) -> str | None:
    from manuscript_guard.contracts import ContractError
    from manuscript_guard.scaffold import checked_title

    if title == "" and _word(answer(answers, "start")):
        return None  # the Word paper's own title
    if not title.strip():
        return "the title is empty; give the working title"
    try:
        checked_title(title, latex=answer(answers, "start") == "latex")
    except ContractError as exc:
        return str(exc).replace(", so nothing was made", "")
    return None


def _journal_problem(journal: Any, answers: dict, folder: Folder) -> str | None:
    if isinstance(journal, dict):
        if journal_slug(journal.get("slug") or journal["name"]):
            return None
        return "the journal's name has no letter or digit to name its profile by"
    if journal in (LATER, "help", *folder.profiles):
        return None
    return (f"{journal!r} is no profile of this project; name the journal as "
            "`journal: {name: <its name>}`")  # fmt: skip


def _authors_of(answers: dict) -> list:
    authors = answer(answers, "authors")
    return authors if isinstance(authors, list) else []


def _statistician_problem(said: Any, answers: dict, folder: Folder) -> str | None:
    if not isinstance(said, str) or said == LATER or names_an_author(said, _authors_of(answers)):
        return None
    return (f"{said!r} names no author; for someone who is not one, write "
            "`statistician: {name: <their name>}`")  # fmt: skip


def _lead_problem(lead: Any, answers: dict, folder: Folder) -> str | None:
    if not isinstance(lead, dict) or names_an_author(lead["author"], _authors_of(answers)):
        return None
    return f"{lead['author']!r} names no author"


def _authors_problem(authors: Any, answers: dict, folder: Folder) -> str | None:
    return _author_problem(authors)


def _data_folder_problem(name: Any, answers: dict, folder: Folder) -> str | None:
    return _folder_problem(name, folder.root)


#: What a schema cannot say of an answer, each checked once the schema takes it.
CHECKS = (
    ("start", _start_problem),
    ("title", _title_problem),
    ("journal", _journal_problem),
    ("authors", _authors_problem),
    ("statistician", _statistician_problem),
    ("ethics_lead", _lead_problem),
    ("data.folder", _data_folder_problem),
)


def problems(answers: dict, folder: Folder) -> dict[str, str]:
    """Each question whose answer cannot be written, with the reason in a sentence."""
    if not answers:
        return {}  # no answers yet: nothing to hold to anything
    found = schema_problems(answers)
    for place, check in CHECKS:
        given = answer(answers, place)
        if given is MISSING or place in found:
            continue
        # A role is held to the authors only where the schema takes them.
        if place in ("statistician", "ethics_lead") and "authors" in found:
            continue
        said = check(given, answers, folder)
        if said:
            found[place] = said
    return found


def _word(start: Any) -> bool:
    return isinstance(start, str) and start.lower().endswith(".docx")
