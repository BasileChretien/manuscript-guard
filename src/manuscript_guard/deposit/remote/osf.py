"""OSF: a bundle staged as a private project, and nothing more.

`POST https://api.osf.io/v2/nodes/` makes the project, private (`public: false`), and each
file goes to its OSF Storage through WaterButler, `PUT
https://files.osf.io/v1/resources/<id>/providers/osfstorage/?kind=file&name=<name>`, answered
`201 Created` with the file's digests, of which the md5 is checked against the bytes sent.

A DOI is refused: OSF mints one only for a project or a registration that is public, and the
tool makes a private one. Publishing is refused too: making a project public is the author's
to do on OSF's own page, where they see what it holds.
"""

from __future__ import annotations

from urllib.parse import quote

from .http import Client, RemoteError, Transport, default_transport, token_from
from .zenodo import md5

HOSTS = {"api": "https://api.osf.io", "files": "https://files.osf.io"}
TOKEN = "OSF_TOKEN"
NAME = "OSF"
#: Why each action the tool does not take at OSF is refused.
REFUSED = {
    "reserve": "OSF mints a DOI only for a project or a registration that is public, and the "
               "tool stages a private one: make it public, or register it, on OSF's page, "
               "and the DOI is minted there",
    "publish": "making an OSF project public is done on OSF's own page, by the author, who "
               "sees there what it holds; the tool stages it private and goes no further",
}


def client(transport: Transport = default_transport) -> Client:
    return Client(NAME, (HOSTS["api"], HOSTS["files"]), token_from(TOKEN), TOKEN, transport)


def _field(document: object, *path: str) -> object:
    for name in path:
        document = document.get(name) if isinstance(document, dict) else None
    return document


def create(api: Client, title: str) -> dict:
    """A private project titled `title`: its id and page."""
    answer = api.call("POST", f"{HOSTS['api']}/v2/nodes/", document={"data": {
        "type": "nodes", "attributes": {"title": title, "category": "project",
                                        "public": False}}},
        content_type="application/vnd.api+json", expect=(201,))  # fmt: skip
    found = _field(answer, "data", "id")
    if not isinstance(found, str) or not found.isascii() or not found.isalnum():
        raise RemoteError(f"{NAME} answered without the project's id")
    if _field(answer, "data", "attributes", "public") is not False:
        raise RemoteError(f"{NAME} made project {found} and did not answer that it is private; "
                          "nothing was uploaded to it: look at it on OSF's page")  # fmt: skip
    page = _field(answer, "data", "links", "html")
    return {"id": found, "doi": None, "page": page if isinstance(page, str) else None}


def upload(api: Client, node: str, files: list[tuple[str, bytes]]) -> dict[str, str]:
    """Each file into the project's OSF Storage, its md5 checked against OSF's: the first that
    differs, or that OSF gives no md5 for, stops it."""
    sent: dict[str, str] = {}
    for name, data in files:
        url = (f"{HOSTS['files']}/v1/resources/{node}/providers/osfstorage/?kind=file&name="
               f"{quote(name, safe='')}")  # fmt: skip
        answer = api.call("PUT", url, data=data, expect=(201,))
        theirs = _field(answer, "data", "attributes", "extra", "hashes", "md5")
        mine = md5(data)
        if not isinstance(theirs, str):
            raise RemoteError(f"{NAME} took {name} and gave no md5 to check it by; stopped, "
                              "and the bundle is not recorded as staged")  # fmt: skip
        if theirs.lower() != mine:
            raise RemoteError(f"{NAME} holds {name} as other bytes than were sent (md5 "
                              f"{theirs.lower()}, sent {mine}); stopped, and nothing after it "
                              "was sent")  # fmt: skip
        sent[name] = mine
    return sent


__all__ = ["HOSTS", "NAME", "REFUSED", "TOKEN", "client", "create", "upload"]
