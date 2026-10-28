"""Zenodo, through its legacy deposition API, as developers.zenodo.org documents it (read
2026-10-28; DESIGN.md, "A deposit is sent only when the author asks").

- `reserve`: `POST /api/deposit/depositions` with `metadata.prereserve_doi` true makes a draft
  and reserves its DOI, which is not registered until the draft is published. The answer
  gives the draft's `id`, the DOI at `metadata.prereserve_doi.doi`, and `links.bucket`, where
  its files go.
- `stage`: `PUT <bucket>/<name>` with each file's bytes, whose answer gives the file's
  `checksum` as `md5:<hex>`, checked against the bytes sent; then the draft's file list,
  which must be those files with those digests and no other; then `PUT
  /api/deposit/depositions/<id>` with the metadata of the bundle's `.zenodo.json`.
- `publish`: `POST /api/deposit/depositions/<id>/actions/publish`, answered `202 Accepted`.
  A published record cannot be deleted.

The sandbox, `sandbox.zenodo.org`, is the same API with a token of its own, and mints test
DOIs (10.5072), which are never a paper's.
"""

from __future__ import annotations

import hashlib
from urllib.parse import quote

from .http import Client, RemoteError, Transport, default_transport, token_from

#: Each target's host, and the variable its token is read from.
HOSTS = {"zenodo": "https://zenodo.org", "zenodo-sandbox": "https://sandbox.zenodo.org"}
TOKENS = {"zenodo": "ZENODO_TOKEN", "zenodo-sandbox": "ZENODO_SANDBOX_TOKEN"}
NAMES = {"zenodo": "Zenodo", "zenodo-sandbox": "Zenodo's sandbox"}


def client(target: str, transport: Transport = default_transport) -> Client:
    return Client(NAMES[target], (HOSTS[target],), token_from(TOKENS[target]), TOKENS[target],
                  transport)  # fmt: skip


def _depositions(target: str) -> str:
    return f"{HOSTS[target]}/api/deposit/depositions"


def _field(document: object, *path: str) -> object:
    for name in path:
        document = document.get(name) if isinstance(document, dict) else None
    return document


def _draft(name: str, document: dict) -> dict:
    """The draft's id, DOI, bucket and page from a deposition as Zenodo gives one."""
    found = document.get("id")
    doi = _field(document, "metadata", "prereserve_doi", "doi")
    bucket = _field(document, "links", "bucket")
    if not isinstance(found, int) or isinstance(found, bool):
        raise RemoteError(f"{name} answered without the draft's id")
    if not isinstance(bucket, str) or not bucket:
        raise RemoteError(f"{name} answered without the draft's bucket")
    page = _field(document, "links", "html")
    return {"id": found, "doi": doi if isinstance(doi, str) else None, "bucket": bucket,
            "page": page if isinstance(page, str) else None}  # fmt: skip


def reserve(api: Client, target: str) -> dict:
    """Make a draft with its DOI reserved; its id, DOI, bucket and page."""
    answer = api.call("POST", _depositions(target),
                      document={"metadata": {"prereserve_doi": True}}, expect=(201,))  # fmt: skip
    draft = _draft(api.name, answer)
    if draft["doi"] is None:
        raise RemoteError(f"{api.name} made draft {draft['id']} and reserved no DOI for it")
    return draft


def md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def _checksum(said: object) -> str | None:
    if not isinstance(said, str):
        return None
    return said.split(":", 1)[1].lower() if said.lower().startswith("md5:") else said.lower()


def held(api: Client, target: str, draft: int) -> dict[str, str]:
    """The draft's files as Zenodo lists them, each by its md5."""
    answer = api.call("GET", f"{_depositions(target)}/{draft}", expect=(200,))
    files = answer.get("files")
    if not isinstance(files, list):
        raise RemoteError(f"{api.name} answered without the draft's list of files")
    listed: dict[str, str] = {}
    for file in files:
        name = file.get("filename") if isinstance(file, dict) else None
        sum_ = _checksum(file.get("checksum")) if isinstance(file, dict) else None
        if not isinstance(name, str) or sum_ is None:
            raise RemoteError(f"{api.name} listed a file of the draft without its name or md5")
        listed[name] = sum_
    return listed


def compare(name: str, listed: dict[str, str], sent: dict[str, str]) -> None:
    """Refuse a draft whose files are not exactly those sent, by name and md5."""
    other = sorted(set(listed) - set(sent))
    if other:
        raise RemoteError(f"the draft at {name} holds files the bundle does not: "
                          f"{', '.join(other)}; delete them on its page first")  # fmt: skip
    missing = sorted(set(sent) - set(listed))
    if missing:
        raise RemoteError(f"the draft at {name} lacks {', '.join(missing)}")
    changed = sorted(file for file in sent if listed[file] != sent[file])
    if changed:
        raise RemoteError(f"the draft at {name} holds other bytes than the bundle for "
                          f"{', '.join(changed)}")  # fmt: skip


def upload(api: Client, draft: dict, files: list[tuple[str, bytes]]) -> dict[str, str]:
    """Each file into the draft's bucket, its md5 checked against Zenodo's: the first that
    differs stops it, and nothing after it is sent."""
    bucket = draft.get("bucket")
    if not isinstance(bucket, str) or not bucket:
        raise RemoteError("the receipt names no bucket to send the files to")
    sent: dict[str, str] = {}
    for name, data in files:
        answer = api.call("PUT", f"{bucket}/{quote(name, safe='')}", data=data,
                          expect=(200, 201))  # fmt: skip
        mine, theirs = md5(data), _checksum(answer.get("checksum"))
        if theirs is None:
            raise RemoteError(f"{api.name} took {name} and gave no md5 to check it by; "
                              "stopped, and the bundle is not recorded as staged")  # fmt: skip
        if theirs != mine:
            raise RemoteError(f"{api.name} holds {name} as other bytes than were sent (md5 "
                              f"{theirs}, sent {mine}); stopped, and nothing after it was "
                              "sent")  # fmt: skip
        sent[name] = mine
    return sent


def describe(api: Client, target: str, draft: dict, metadata: dict) -> None:
    """Put the bundle's `.zenodo.json` as the draft's metadata, its reserved DOI kept."""
    wanted = {**metadata, "prereserve_doi": True}
    answer = api.call("PUT", f"{_depositions(target)}/{draft['id']}",
                      document={"metadata": wanted}, expect=(200,))  # fmt: skip
    kept = _field(answer, "metadata", "prereserve_doi", "doi")
    if draft.get("doi") and kept != draft["doi"]:
        raise RemoteError(f"{api.name} answered the metadata with the DOI {kept}, and the "
                          f"draft's reserved DOI is {draft['doi']}")  # fmt: skip


def publish(api: Client, target: str, draft: dict) -> dict:
    """Publish the draft; its DOI and page as Zenodo gives them."""
    answer = api.call("POST", f"{_depositions(target)}/{draft['id']}/actions/publish",
                      expect=(202,))  # fmt: skip
    doi = answer.get("doi") or _field(answer, "metadata", "prereserve_doi", "doi")
    if doi != draft.get("doi"):
        raise RemoteError(f"{api.name} published draft {draft['id']} with the DOI {doi}, and "
                          f"the DOI it reserved was {draft.get('doi')}")  # fmt: skip
    page = _field(answer, "links", "html") or _field(answer, "links", "record_html")
    return {"doi": doi, "page": page if isinstance(page, str) else draft.get("page")}


__all__ = ["HOSTS", "NAMES", "TOKENS", "client", "compare", "describe", "held", "md5",
           "publish", "reserve", "upload"]  # fmt: skip
