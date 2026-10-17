"""`manuscript-guard style`: the journal's citation style fetched once from the CSL style
repository, and kept in the project for the offline build.

The repository keeps an independent style at its root (`the-lancet.csl`) and a dependent one,
which names the style it formats like and holds no formatting of its own, under `dependent/`
(`dependent/the-lancet-oncology.csl`). A name is asked for at the root first, then under
`dependent/`; a dependent style's parent is then fetched from the root, and both are kept.
What this writes is read offline by `journal_style`, and decides nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from manuscript_guard.contracts.project import Project
from manuscript_guard.journal_style import (
    FORMATS,
    SCHEMA,
    NotAStyle,
    Parsed,
    digest,
    folder,
    parse,
    write_record,
)
from manuscript_guard.lookup.http import (
    TIMEOUT_SECONDS,
    NoAnswer,
    Request,
    Response,
    Transport,
    default_transport,
    user_agent,
)

#: The official CSL style repository's files, as served on its default branch.
REPOSITORY = "https://raw.githubusercontent.com/citation-style-language/styles/master/"
DEPENDENT = "dependent/"


class NotFetched(Exception):
    """The style could not be fetched or is not one. The message is ours, and says why."""


@dataclass(frozen=True)
class Fetched:
    name: str
    url: str
    data: bytes
    parsed: Parsed


def _get(transport: Transport, url: str) -> Response:
    try:
        return transport(Request(url, headers={"User-Agent": user_agent(None)}), TIMEOUT_SECONDS)
    except NoAnswer as exc:
        raise NotFetched(f"no answer from the CSL style repository: {exc}") from None


def _fetch(transport: Transport, base: str, name: str, places: tuple[str, ...]) -> Fetched:
    """The first of `places` under `base` that has the style, read and parsed."""
    for place in places:
        url = f"{base}{place}{name}.csl"
        answer = _get(transport, url)
        if answer.status == 404:
            continue
        if answer.status != 200:
            raise NotFetched(f"the CSL style repository answered {answer.status} for {name}")
        try:
            return Fetched(name, url, answer.body, parse(answer.body, f"the style {name}"))
        except NotAStyle as exc:
            raise NotFetched(str(exc)) from None
    raise NotFetched(f"the CSL style repository has no style named {name}")


def fetch(
    name: str, *, transport: Transport | None = None, base: str | None = None
) -> tuple[Fetched, Fetched | None]:
    """The style, and its independent parent where it is a dependent style. The transport and
    the repository are looked up when called, so a test can stand in for both."""
    transport = transport or default_transport
    base = base or REPOSITORY
    style = _fetch(transport, base, name, ("", DEPENDENT))
    if style.parsed.parent is None:
        return style, None
    parent = _fetch(transport, base, style.parsed.parent, ("",))
    if parent.parsed.parent is not None:
        raise NotFetched(
            f"the style {name} depends on {parent.name}, which is itself a dependent style"
        )
    return style, parent


def _entry(fetched: Fetched) -> dict:
    entry = {
        "style": fetched.name,
        "title": fetched.parsed.title,
        "file": f"{fetched.name}.csl",
        "source_url": fetched.url,
        "sha256": digest(fetched.data),
        "licence": fetched.parsed.licence,
    }
    return {key: value for key, value in entry.items() if value}


def store(
    project: Project,
    name: str,
    *,
    transport: Transport | None = None,
    base: str | None = None,
    today: Callable[[], date] = date.today,
) -> dict:
    """Fetch the style and keep it: the files, then the record that names them. Nothing is
    written unless every file came back and is a style."""
    style, parent = fetch(name, transport=transport, base=base)
    record = {"schema": SCHEMA, **_entry(style), "retrieved_on": today().isoformat()}
    found = style.parsed.citation_format or (parent.parsed.citation_format if parent else None)
    if found in FORMATS:
        record["citation_format"] = found
    if parent is not None:
        record["parent"] = _entry(parent)
    where = folder(project)
    where.mkdir(parents=True, exist_ok=True)
    for fetched in (style, parent):
        if fetched is not None:
            (where / f"{fetched.name}.csl").write_bytes(fetched.data)
    write_record(project, record)
    return record


__all__ = ["DEPENDENT", "REPOSITORY", "Fetched", "NotFetched", "fetch", "store"]
