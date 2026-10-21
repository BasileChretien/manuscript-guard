"""What each registry says of one identifier, read into the record's terms.

Each answer ends in one of three statuses:

* `found`: the registry answered in the shape its documentation gives, and knew the work.
* `absent`: it answered, in that shape, that it does not know it. Crossref not knowing a DOI
  is no proof the DOI does not exist: DataCite registers datasets Crossref never sees, and
  other agencies (JaLC, mEDRA, KISTI) register others. Only doi.org answers for all of them.
* `unresolvable`: anything else. A 429, a 500, a timeout, an answer of another shape, a 200
  that holds an error. Never "not retracted": a lookup that did not work said nothing.

The shapes were read from the services' documentation and from live answers on 2026-10-15
(DESIGN.md, "A reference is looked up once, and the answer is kept").
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from manuscript_guard.literature import names
from manuscript_guard.lookup.http import NoAnswer, Request, Response, user_agent

FOUND = "found"
ABSENT = "absent"
UNRESOLVABLE = "unresolvable"

Ask = Callable[[Request], Response]
SHAPE = "an answer not of the shape the service documents"


def unresolvable(why: str) -> dict[str, Any]:
    return {"status": UNRESOLVABLE, "why": why}


def _json(response: Response) -> Any:
    try:
        return json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def _status_only(response: Response) -> dict[str, Any] | None:
    """What a status says on its own: None for a 200, to be read further."""
    if response.status == 200:
        return None
    if response.status == 429:
        return unresolvable("throttled (HTTP 429): asked too often, or past the allowance")
    if 300 <= response.status < 400:
        return unresolvable(f"redirected (HTTP {response.status}), and not followed")
    return unresolvable(f"HTTP {response.status}")


def _ask(ask: Ask, request: Request) -> Response | dict[str, Any]:
    try:
        return ask(request)
    except NoAnswer as exc:
        return unresolvable(str(exc))


def _text(value: Any) -> str | None:
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v.strip()), None)
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None


def _year(value: Any) -> int | None:
    """The year of a Crossref date (`{"date-parts": [[1998, 2]]}`), or of a year written
    as a number or as the start of a string ("1998 Feb 28", "1998/02/28 00:00")."""
    if isinstance(value, dict):
        parts = value.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            value = parts[0][0]
        else:
            return None
    if isinstance(value, str):
        found = re.match(r"\s*(\d{4})\b", value)
        value = int(found.group(1)) if found else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1000 <= value <= 9999 else None


def _date(value: Any) -> str | None:
    """A Crossref date as ISO, as far as it goes: "2010-02-06", "1998-02", "1998"."""
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not (isinstance(parts, list) and parts and isinstance(parts[0], list)):
        return None
    numbers = [p for p in parts[0] if isinstance(p, int) and not isinstance(p, bool)]
    if not numbers or not 1000 <= numbers[0] <= 9999:
        return None
    return "-".join([f"{numbers[0]:04d}", *(f"{n:02d}" for n in numbers[1:3])])


def _kept(record: dict[str, Any]) -> dict[str, Any]:
    """The record without the fields the answer did not have."""
    return {k: v for k, v in record.items() if v not in (None, [], "")}


# ------------------------------------------------------------------------------ Crossref


def _update(item: Any) -> dict[str, Any] | None:
    """One `update-to` or `updated-by` notice: its kind, its DOI, its date, who says so.
    Crossmark writes `expression_of_concern`, the Retraction Watch data `expression-of-
    concern`: one kind, read as one."""
    if not isinstance(item, dict) or not isinstance(item.get("type"), str):
        return None
    if not item["type"].strip():
        return None
    return _kept(
        {
            "type": item["type"].strip().lower().replace("-", "_"),
            "doi": item["DOI"].lower() if isinstance(item.get("DOI"), str) else None,
            "date": _date(item.get("updated")),
            "source": item.get("source") if isinstance(item.get("source"), str) else None,
        }
    )


def crossref(doi: str, ask: Ask, base: str, contact: str | None) -> dict[str, Any]:
    """`GET /works/{doi}`. A 404 is Crossref not knowing the DOI, which is not the DOI not
    existing. A 200 is a work only with `"status": "ok"`, `"message-type": "work"` and a
    message that carries its DOI."""
    # Crossref asks for the contact address in the User-Agent as well as in `mailto`; no
    # other registry is sent it there.
    request = Request(
        base + quote(doi, safe="/"),
        secret={"mailto": contact or ""},
        headers={"User-Agent": user_agent(contact)},
    )
    answer = _ask(ask, request)
    if isinstance(answer, dict):
        return answer
    if answer.status == 404:
        return {"status": ABSENT}
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    message = data.get("message") if isinstance(data, dict) else None
    if not (
        isinstance(data, dict)
        and data.get("status") == "ok"
        and data.get("message-type") == "work"
        and isinstance(message, dict)
        and isinstance(message.get("DOI"), str)
    ):
        return unresolvable(SHAPE)
    return {"status": FOUND, **work(message)}


def _authors(people: list[names.Name]) -> list[dict[str, str]]:
    return [p.record() for p in people if p.family or p.group]


def work(message: dict[str, Any]) -> dict[str, Any]:
    """One Crossref work, from `/works/{doi}` or from a search's `items`, which hold the
    same shape. The caller has held it to having a DOI."""
    relation = message.get("relation") if isinstance(message.get("relation"), dict) else {}
    preprint_of = [
        r["id"].lower()
        for r in relation.get("is-preprint-of", [])
        if isinstance(r, dict) and r.get("id-type") == "doi" and isinstance(r.get("id"), str)
    ]
    people = message.get("author") if isinstance(message.get("author"), list) else []
    return _kept(
        {
            "doi": message["DOI"].lower(),
            "type": _text(message.get("type")),
            "subtype": _text(message.get("subtype")),
            "title": _text(message.get("title")),
            "subtitle": _text(message.get("subtitle")),
            "original_title": _text(message.get("original-title")),
            "container": _text(message.get("container-title")),
            "years": _kept(
                {
                    "print": _year(message.get("published-print")),
                    "online": _year(message.get("published-online")),
                    "issued": _year(message.get("issued")),
                    "posted": _year(message.get("posted")),
                }
            ),
            "volume": _text(message.get("volume")),
            "page": _text(message.get("page")),
            "article_number": _text(message.get("article-number")),
            "updated_by": [u for u in map(_update, message.get("updated-by") or []) if u],
            "update_to": [u for u in map(_update, message.get("update-to") or []) if u],
            "preprint_of": preprint_of,
            "authors": _authors([names.crossref(p) for p in people if isinstance(p, dict)]),
        }
    )


# ------------------------------------------------------------------------------ OpenAlex


def openalex(doi: str, ask: Ask, base: str, key: str | None) -> dict[str, Any]:
    """`GET /works/doi:{doi}`, for `is_retracted`. A work has an `id` and that flag."""
    answer = _ask(ask, Request(base + quote(doi, safe="/"), secret={"api_key": key or ""}))
    if isinstance(answer, dict):
        return answer
    if answer.status == 404:
        return {"status": ABSENT}
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    if not (
        isinstance(data, dict)
        and isinstance(data.get("id"), str)
        and isinstance(data.get("is_retracted"), bool)
    ):
        return unresolvable(SHAPE)
    return {
        "status": FOUND,
        "is_retracted": data["is_retracted"],
        **_kept(
            {
                "title": _text(data.get("title")) or _text(data.get("display_name")),
                "type": _text(data.get("type")),
                "year": _year(data.get("publication_year")),
            }
        ),
    }


# ------------------------------------------------------------------------------ DataCite


def datacite(doi: str, ask: Ask, base: str) -> dict[str, Any]:
    """`GET /dois/{doi}`, for a DOI Crossref does not know: a dataset's, most often."""
    answer = _ask(ask, Request(base + quote(doi, safe="/")))
    if isinstance(answer, dict):
        return answer
    if answer.status == 404:
        return {"status": ABSENT}
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    attributes = (
        data["data"].get("attributes")
        if isinstance(data, dict) and isinstance(data.get("data"), dict)
        else None
    )
    if not isinstance(attributes, dict) or not isinstance(attributes.get("titles"), list):
        return unresolvable(SHAPE)
    titles = [t for t in attributes["titles"] if isinstance(t, dict)]
    main = [t.get("title") for t in titles if not t.get("titleType")]
    types = attributes.get("types") if isinstance(attributes.get("types"), dict) else {}
    return {
        "status": FOUND,
        **_kept(
            {
                "title": _text(main) or _text([t.get("title") for t in titles]),
                "type": _text(types.get("resourceTypeGeneral")),
                "year": _year(attributes.get("publicationYear")),
            }
        ),
    }


# ------------------------------------------------------------------------------ doi.org


def doi_org(doi: str, ask: Ask, base: str) -> dict[str, Any]:
    """The handle API, which every registration agency's DOIs pass through: whether the DOI
    is registered at all, and nothing about the work. Response code 1 is a handle with
    values, 200 a handle with none, 100 no handle (HTTP 404)."""
    answer = _ask(ask, Request(base + quote(doi, safe="/")))
    if isinstance(answer, dict):
        return answer
    data = _json(answer)
    code = data.get("responseCode") if isinstance(data, dict) else None
    if answer.status == 404 and code == 100:
        return {"status": ABSENT}
    said = _status_only(answer)
    if said:
        return said
    if code in (1, 200):
        return {"status": FOUND}
    return unresolvable(SHAPE)


# ------------------------------------------------------------------------------ PubMed


def pubmed(
    pmid: str, ask: Ask, base: str, contact: str | None, key: str | None
) -> dict[str, Any]:
    """E-utilities ESummary, as JSON. It answers an error with a 200: `{"error": ...}` for
    the request, and `{"result": {pmid: {"error": ...}}}` for a PMID it does not know."""
    answers = summaries([pmid], ask, base, contact, key)
    return answers if "status" in answers else answers[pmid]


def summaries(
    pmids: list[str], ask: Ask, base: str, contact: str | None, key: str | None
) -> dict[str, Any]:
    """ESummary for several PMIDs in one request: each PMID's answer, or one unresolvable
    answer for all of them where the request got none (it has a `status`; a PMID never
    does)."""
    request = Request(
        base,
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json",
                "tool": "manuscript-guard"},
        secret={"email": contact or "", "api_key": key or ""},
    )  # fmt: skip
    answer = _ask(ask, request)
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    data = _json(answer)
    if not isinstance(data, dict) or "error" in data:
        return unresolvable(SHAPE if not isinstance(data, dict) else "the service said: error")
    result = data.get("result")
    if not isinstance(result, dict):
        return unresolvable(SHAPE)
    read = {pmid: _summary(pmid, result.get(pmid)) for pmid in pmids}
    shapeless = [a for a in read.values() if a["status"] == UNRESOLVABLE]
    return shapeless[0] if shapeless else read


def _summary(pmid: str, item: Any) -> dict[str, Any]:
    """One PMID's summary. `{"error": ...}` in its place is a PMID PubMed does not know."""
    if not isinstance(item, dict):
        return unresolvable(SHAPE)
    if "error" in item:
        return {"status": ABSENT}
    if item.get("uid") != pmid or not isinstance(item.get("title"), str):
        return unresolvable(SHAPE)
    ids = item.get("articleids") if isinstance(item.get("articleids"), list) else []
    dois = [
        i["value"].lower()
        for i in ids
        if isinstance(i, dict) and i.get("idtype") == "doi" and isinstance(i.get("value"), str)
    ]
    pubtypes = item.get("pubtype") if isinstance(item.get("pubtype"), list) else []
    people = [a for a in item.get("authors") or [] if isinstance(a, dict)]
    return {
        "status": FOUND,
        **_kept(
            {
                "title": _text(item.get("title")),
                "year": _year(item.get("sortpubdate")) or _year(item.get("pubdate")),
                "doi": dois[0] if dois else None,
                "pubtypes": [p.strip() for p in pubtypes if isinstance(p, str) and p.strip()],
                "volume": _text(item.get("volume")),
                "pages": _text(item.get("pages")),
                "elocation": _text(item.get("elocationid")),
                "journal": _text(item.get("fulljournalname")),
                "journal_abbreviation": _text(item.get("source")),
                "authors": _authors([
                    names.pubmed(a["name"], a.get("authtype") == "CollectiveName")
                    for a in people if isinstance(a.get("name"), str)
                ]),  # fmt: skip
            }
        ),
    }


__all__ = [
    "ABSENT",
    "FOUND",
    "UNRESOLVABLE",
    "crossref",
    "datacite",
    "doi_org",
    "openalex",
    "pubmed",
    "summaries",
    "unresolvable",
    "work",
]
