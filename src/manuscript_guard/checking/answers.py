"""Reading an answers file, and saying whose word it is.

A page built since the register exists writes `checking-answers/2`: the page's identifier, the
name and ORCID iD it was built for, its token and the digest of what it asked. Pages built before
wrote `checking-answers/1`, which has the identifier and the name only, and both are read.

What the file says about who made it is then held to `checks/bundles.csv` (`register.py`):

* it names a page in the register: its token must hash to the one recorded, and its name and
  ORCID iD must be the page's, or the file is refused (`Refused`, exit 2 at the command), with
  the reason, and nothing from it is recorded;
* it names no page in the register, or is a `/1` file: it is recorded, and read as **claimed**:
  the name in it is whatever the file says, and nothing holds it to anything;
* a `/1` file that names a registered page is refused: no registered page writes one.

The name is then looked up in `authors.yaml` (`people.resolve`): by ORCID iD, full name or
family name, compared in Unicode's composed form and without case, and recorded under the
author's name as `authors.yaml` writes it. A file by a name two authors share is refused
(`people.Namesakes`). A name that is no author's is recorded as the file gives it, and the
import says so. A name that is an author's with an ORCID
iD that is not theirs is refused in a file from a registered page, and in any other file is
recorded as "Name <iD>", apart from the author, and marked.

The whole shape of the file is checked before anything from it is recorded.
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
    #: The name is an author's and the ORCID iD is not theirs, or the other way round.
    orcid_differs: bool = False


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
    _shaped(answers_file, document)
    said = str(document.get("by") or "").strip()
    if not said:
        raise AnswersError(f"{answers_file} does not say who made it")
    bundle = str(document.get("bundle") or "")
    if register is None:
        register = read_register(project_root)
    row = register.get(bundle) if bundle else None
    if row is not None:
        _held_to(answers_file, document, said, row)
    orcid = str(document.get("orcid") or "")
    found = _resolved(project, said, orcid, answers_file)
    if found is None:
        return Answers(path=answers_file, document=document, by=said, author=None,
                       claimed=row is None, bundle=bundle)  # fmt: skip
    if found.orcid_differs and row is not None:
        raise Refused(
            f"{answers_file} names page {row.bundle} ({REGISTER}), built for {row.person} with "
            f"the ORCID iD {row.orcid or 'none'}, and authors.yaml does not give that name that "
            f"iD now. Nothing from it is recorded: rebuild the page for them with "
            f"`checker build`, and ask them to answer on the new one."
        )
    return Answers(path=answers_file, document=document, by=found.by,
                   author=found.author is not None, claimed=row is None, bundle=bundle,
                   orcid_differs=found.orcid_differs)  # fmt: skip


#: Each field of the file, and of an answer in it, with the type it must have where it is given.
_FILE_FIELDS = {"schema": str, "bundle": str, "by": str, "built_on": str, "saved_on": str,
                "orcid": str, "token": str, "state": str, "answers": list}  # fmt: skip
_ANSWER_FIELDS = {"id": str, "digest": str, "status": str, "note": str, "at": str,
                  "title": str, "group": str}  # fmt: skip


def _shaped(answers_file: Path, document: dict) -> None:
    """Refuse a file whose fields are not of the shape the page writes, before any of it is
    recorded: an `answers` that is a number failed in the middle of an import of several files,
    after the files before it had been written."""
    def wrong(where: str, field: str, value, kind: type) -> AnswersError:
        return AnswersError(
            f"{answers_file}: {where}{field} is {type(value).__name__}, and the page writes "
            f"{kind.__name__}. Nothing from any file of this import is recorded."
        )

    for field, kind in _FILE_FIELDS.items():
        if document.get(field) is not None and not isinstance(document[field], kind):
            raise wrong("", field, document[field], kind)
    for n, answer in enumerate(document.get("answers") or (), 1):
        if not isinstance(answer, dict):
            raise wrong(f"answer {n} ", "itself", answer, dict)
        for field, kind in _ANSWER_FIELDS.items():
            if answer.get(field) is not None and not isinstance(answer[field], kind):
                raise wrong(f"answer {n}'s ", field, answer[field], kind)
        if not str(answer.get("id") or "").strip():
            raise AnswersError(f"{answers_file}: answer {n} names no item")


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


def _resolved(project, said: str, orcid: str, answers_file: Path):
    """Who the file is by, as `people.resolve` finds them; None where no project was given."""
    if project is None:
        return None
    from manuscript_guard.approvals import AmbiguousAuthor
    from manuscript_guard.checking.people import Namesakes, SharedOrcid, resolve

    try:
        return resolve(project, said, orcid)
    except (AmbiguousAuthor, Namesakes, SharedOrcid) as exc:
        raise AnswersError(f"{answers_file}: {exc}") from exc
