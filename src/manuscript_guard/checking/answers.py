"""Reading an answers file, and saying whose word it is.

A page built since the register exists writes `checking-answers/2`: the page's identifier, the
name and ORCID iD it was built for, its token and the digest of what it asked. Pages built before
wrote `checking-answers/1`, which has the identifier and the name only, and both are read.

What the file says about who made it is then held to `checks/bundles.csv` (`register.py`):

* it names a page in the register: its token must hash to the one recorded, and its name and
  ORCID iD must be the page's, or the file is refused (`Refused`, exit 2 at the command), with
  the reason, and nothing from it is recorded;
* it names no page in the register, or is a `/1` file: it is recorded, and read as **claimed**;
* a `/1` file that names a registered page is refused: no registered page writes one.

The name is then looked up in `authors.yaml` as `approve --as` looks one up, by ORCID iD, e-mail
address, full name or family name, and recorded as the author's name. A name that is not an
author's is recorded as the file gives it, and the import says so.
"""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.checking.register import REGISTER, Row, read_register, token_sha256

SCHEMA_1 = "manuscript-guard/checking-answers/1"
SCHEMA_2 = "manuscript-guard/checking-answers/2"
#: What the page writes now.
ANSWERS_SCHEMA = SCHEMA_2
READ = (SCHEMA_1, SCHEMA_2)


class AnswersError(Exception):
    """An answers file that cannot be read, or does not belong to this project."""


class Refused(AnswersError):
    """An answers file that names a page in the register and does not match it."""


@dataclass(frozen=True)
class Answers:
    """One answers file, read, and what it is worth as attribution."""

    path: Path
    document: dict
    #: The name its decisions are recorded under: the author's, where `authors.yaml` has them.
    by: str
    #: Whether `authors.yaml` lists them; None where no project was given to look in.
    author: bool | None
    #: It names no page this project registered, so the name is the file's word.
    claimed: bool
    bundle: str


def read_answers(answers_file: Path, *, project_root: Path, project=None,
                 register: dict[str, Row] | None = None) -> Answers:  # fmt: skip
    """Read one answers file and hold it to the register. Refuses (`AnswersError`) a file
    that is not one, and (`Refused`) one that does not match the page it names."""
    try:
        document = json.loads(answers_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AnswersError(
            f"{answers_file} is not an answers file this can read ({exc}). The page writes it "
            f"with its own button; a file edited by hand afterwards may no longer be JSON."
        ) from exc
    if not isinstance(document, dict) or document.get("schema") not in READ:
        said = document.get("schema") if isinstance(document, dict) else type(document).__name__
        raise AnswersError(
            f"{answers_file}: schema is {said!r}, and this reads {' or '.join(map(repr, READ))}"
        )
    said = str(document.get("by") or "").strip()
    if not said:
        raise AnswersError(f"{answers_file} does not say who made it")
    bundle = str(document.get("bundle") or "")
    if register is None:
        register = read_register(project_root)
    row = register.get(bundle) if bundle else None
    if row is not None:
        _held_to(answers_file, document, said, row)
    by, author = _resolved(project, said, str(document.get("orcid") or ""), answers_file)
    return Answers(path=answers_file, document=document, by=by, author=author,
                   claimed=row is None, bundle=bundle)  # fmt: skip


def _held_to(answers_file: Path, document: dict, said: str, row: Row) -> None:
    page = f"page {row.bundle}, built for {row.person} on {row.built_on} ({REGISTER})"
    if document.get("schema") != SCHEMA_2:
        raise Refused(
            f"{answers_file} names {page}, and is written as {document.get('schema')!r}: that "
            f"page writes {SCHEMA_2!r} with its token. Nothing from the file is recorded."
        )
    token = str(document.get("token") or "")
    # Compared in constant time, though nothing here is a server: it costs nothing.
    if not token or not hmac.compare_digest(token_sha256(token), row.token_sha256):
        raise Refused(
            f"{answers_file} names {page}, and its token is not that page's. The file was "
            f"edited, or made from another page. Nothing from it is recorded; ask "
            f"{row.person} to save their answers from the page again."
        )
    if said != row.person:
        raise Refused(
            f"{answers_file} says it is by {said}, and it names {page}. Nothing from it is "
            f"recorded: a page's answers carry the name it was built for."
        )
    orcid = str(document.get("orcid") or "")
    if row.orcid and orcid != row.orcid:
        raise Refused(
            f"{answers_file} gives the ORCID iD {orcid or 'none'}, and it names {page}, built "
            f"for {row.orcid}. Nothing from it is recorded."
        )


def _resolved(project, said: str, orcid: str, answers_file: Path) -> tuple[str, bool | None]:
    """The name to record, and whether `authors.yaml` lists them."""
    if project is None:
        return said, None
    from manuscript_guard.approvals import AmbiguousAuthor, NoSuchAuthor, find_author, name_of

    try:
        author = find_author(project, orcid or said)
    except AmbiguousAuthor as exc:
        raise AnswersError(f"{answers_file}: {exc}") from exc
    except NoSuchAuthor:
        if not orcid:
            return said, False
        # An ORCID iD no author has: the name may still be one of theirs.
        return _resolved(project, said, "", answers_file)
    if orcid and name_of(author) != said:
        # The iD and the name are two authors', or an iD and a stranger's name.
        try:
            named = find_author(project, said)
        except NoSuchAuthor:
            named = None
        if named is not None and named is not author:
            raise AnswersError(
                f"{answers_file} says it is by {said} and gives the ORCID iD of "
                f"{name_of(author)}; which of them made it is not for this to guess"
            )
    return name_of(author), True
