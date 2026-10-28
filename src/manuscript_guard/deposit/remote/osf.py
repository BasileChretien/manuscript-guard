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
    """A project titled `title`, asked for as private: its id, its page, and whether OSF
    answered that it is private. Whether it is is the caller's to judge, once the id is
    recorded: the project exists either way, and a second one must not be made."""
    answer = api.call("POST", f"{HOSTS['api']}/v2/nodes/", document={"data": {
        "type": "nodes", "attributes": {"title": title, "category": "project",
                                        "public": False}}},
        content_type="application/vnd.api+json", expect=(201,))  # fmt: skip
    found = _field(answer, "data", "id")
    if not isinstance(found, str) or not found.isascii() or not found.isalnum() \
            or len(found) > 64:  # fmt: skip
        raise RemoteError(f"{NAME} answered without the project's id")
    try:
        page = api.kept("page", _field(answer, "data", "links", "html"))
    except RemoteError:
        page = None  # the id is what must be recorded; the page is OSF's to show again
    private = _field(answer, "data", "attributes", "public") is False
    return {"id": found, "doi": None, "page": page, "private": private}


def not_private(project: str) -> RemoteError:
    return RemoteError(f"{NAME} made project {project} and did not answer that it is private; "
                       "nothing is uploaded to it, now or later: look at it on OSF's "
                       "page")  # fmt: skip


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
                              f"{api.plain(theirs.lower())}, sent {mine}); stopped, and nothing "
                              "after it was sent")  # fmt: skip
        sent[name] = mine
    return sent


__all__ = ["HOSTS", "NAME", "REFUSED", "TOKEN", "client", "create", "not_private", "upload"]
