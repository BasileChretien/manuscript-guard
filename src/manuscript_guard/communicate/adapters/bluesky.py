"""Bluesky: a session, each image's blob, and a record for each post.

The requests, as atproto names them (docs.bsky.app, "Posting via the Bluesky API", as
recorded on 2026-10-29 and not read on that day: the page did not load):

1. `com.atproto.server.createSession` with the handle and an app password, which answers
   the account's DID and an access token. The app password is the author's, from
   `BLUESKY_APP_PASSWORD`; it goes into that one request's body and nowhere else.
2. `com.atproto.repo.uploadBlob` for each image, its bytes as they are, which answers the
   blob the record names; its alternative text goes into the record beside it.
3. `com.atproto.repo.createRecord` for each post, an `app.bsky.feed.post` whose links are
   marked as facets at their UTF-8 byte offsets (`facets`): Bluesky counts a facet's place
   in bytes, and a text with an accent or a Japanese word before a link marks the wrong
   letters when it is counted in characters. A thread's posts after the first each reply to
   the first (`root`) and to the one before (`parent`).

Each record is given its key (`rkey`), a TID of the moment it is sent, each above the last key
made, and the key is written down before it is sent: a post whose answer was lost is then
asked for by that key when the thread is resumed, and sent again only where Bluesky says it
holds no record under it (`RecordNotFound`), so that no post is made twice.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from manuscript_guard.communicate.adapters.net import (
    Answered,
    Api,
    Image,
    RemoteError,
    default_transport,
)

#: The service the account is on; `BLUESKY_SERVICE` names another (a self-hosted PDS).
SERVICE = "https://bsky.social"
#: Where a post is read, for the link recorded beside its URI.
APP = "https://bsky.app"
HANDLE, PASSWORD, SERVICE_ENV = "BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD", "BLUESKY_SERVICE"
COLLECTION = "app.bsky.feed.post"
#: As many images as a post embeds, and the largest a blob of one may be (as recorded from
#: the lexicon `app.bsky.embed.images` on 2026-10-29, not read on its page that day).
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 1_000_000
#: The transport the client is given; a test puts its own in its place.
TRANSPORT = default_transport

_LINK = re.compile(r"https?://[^\s<>\"'\x00]+")
#: What a link does not end on, as written in a sentence: its stop, and a mark after it.
_AFTER_LINK = ".,;:!?'\""
_TID_ALPHABET = "234567abcdefghijklmnopqrstuvwxyz"


def links(text: str) -> list[tuple[int, int, str]]:
    """Each link of `text` as its start and end in characters, and the link: `https://`
    and what follows to a space, less a stop or a mark after it, and a closing bracket it
    does not open."""
    found = []
    for match in _LINK.finditer(text):
        link = match.group()
        while link:
            unopened = link[-1] == ")" and link.count(")") > link.count("(")
            if link[-1] not in _AFTER_LINK and not unopened:
                break
            link = link[:-1]
        if re.fullmatch(r"https?://", link) is None and link:
            found.append((match.start(), match.start() + len(link), link))
    return found


def in_bytes(text: str, at: int) -> int:
    """Where the character at `at` of `text` starts, in UTF-8 bytes."""
    return len(text[:at].encode("utf-8"))


def facets(text: str) -> list[dict]:
    """Each link of `text` as a facet of a post: where it is, in UTF-8 bytes from the start,
    and the link it is."""
    out = []
    for start, end, link in links(text):
        byte_start, byte_end = in_bytes(text, start), in_bytes(text, end)
        out.append({
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
        })  # fmt: skip
    return out


def tid(moment: datetime, clock: int = 0) -> str:
    """A record key of `moment`, as atproto writes one: its microseconds since 1970 and a
    clock id in 64 bits, the first naught, in base 32 sortable, thirteen letters."""
    return _tid_of(int(moment.timestamp() * 1_000_000), clock)


def _tid_of(micros: int, clock: int = 0) -> str:
    value = ((micros & ((1 << 53) - 1)) << 10) | (clock & 0x3FF)
    letters = []
    for _ in range(13):
        letters.append(_TID_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(letters))


def micros_of(rkey: object) -> int | None:
    """The microseconds a TID `tid` wrote, or None where `rkey` is no TID."""
    if not isinstance(rkey, str) or len(rkey) != 13 or any(
            letter not in _TID_ALPHABET for letter in rkey):  # fmt: skip
        return None
    value = 0
    for letter in rkey:
        value = value * 32 + _TID_ALPHABET.index(letter)
    return value >> 10


def next_tid(moment: datetime, last: int) -> tuple[str, int]:
    """The record key of a post sent at `moment`, above `last`, the microseconds of the last
    key made: a clock that answers the same moment twice, as Windows' can, would otherwise
    give two posts one key. The key, and its microseconds."""
    micros = max(int(moment.timestamp() * 1_000_000), last + 1)
    return _tid_of(micros), micros


def stamp(moment: datetime) -> str:
    """A moment as a record's `createdAt` is written: UTC, to the millisecond, with `Z`."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def record(text: str, created_at: str, *, langs: list[str], images: list[dict] | None = None,
           reply: dict | None = None) -> dict:  # fmt: skip
    """The `app.bsky.feed.post` a post is: its text, its links as facets, its language, the
    images it embeds (each `{"alt", "image": <blob>}`) and what it replies to."""
    out: dict = {"$type": COLLECTION, "text": text, "createdAt": created_at, "langs": langs}
    marked = facets(text)
    if marked:
        out["facets"] = marked
    if images:
        out["embed"] = {"$type": "app.bsky.embed.images", "images": images}
    if reply:
        out["reply"] = reply
    return out


def create_body(repo: str, rkey: str, post: dict) -> dict:
    return {"repo": repo, "collection": COLLECTION, "rkey": rkey, "record": post}


def _reference(post: dict) -> dict:
    return {"uri": post["uri"], "cid": post["cid"]}


def reply_to(done: list[dict]) -> dict | None:
    """What the next post of a thread replies to: the thread's first post, and its last."""
    if not done:
        return None
    return {"root": _reference(done[0]), "parent": _reference(done[-1])}


# ---------------------------------------------------------------------- what is planned


def planned(posts: list[str], images: list[Image], langs: list[str]) -> list[dict]:
    """The requests `--post` would send, written for the outbox: what the service answers,
    and the moment each post is sent, in angle brackets; no credential."""
    service = origin()
    requests: list[dict] = [{
        "method": "POST", "url": f"{service}/xrpc/com.atproto.server.createSession",
        "body": {"identifier": f"<{HANDLE}>", "password": f"<{PASSWORD}>"},
    }]  # fmt: skip
    for image in images:
        requests.append({
            "method": "POST", "url": f"{service}/xrpc/com.atproto.repo.uploadBlob",
            "headers": {"Content-Type": image.content_type},
            "body": {"file": image.name, "bytes": len(image.data)},
        })  # fmt: skip
    done: list[dict] = []
    for index, text in enumerate(posts, 1):
        embedded = [{"alt": image.alt, "image": f"<the blob {image.name} answers>"}
                    for image in images] if index == 1 else None  # fmt: skip
        post = record(text, f"<the moment post {index} is sent>", langs=langs,
                      images=embedded, reply=reply_to(done))  # fmt: skip
        requests.append({
            "method": "POST", "url": f"{service}/xrpc/com.atproto.repo.createRecord",
            "body": create_body("<the DID the session answers>",
                                f"<a TID of the moment post {index} is sent>", post),
        })  # fmt: skip
        done.append({"uri": f"<post {index}'s uri>", "cid": f"<post {index}'s cid>"})
    return requests


# ------------------------------------------------------------------------- what is sent


def origin() -> str:
    return os.environ.get(SERVICE_ENV, "").strip() or SERVICE


def missing() -> list[str]:
    """The variables the credentials are read from that are not set."""
    return [name for name in (HANDLE, PASSWORD) if not os.environ.get(name, "").strip()]


def client() -> Api:
    """The service, with the app password kept out of every message and record. A handle is
    public, and the DID of a `did:web` account holds it, so it is no secret; an e-mail address
    given in its place (an `@` in it) is kept out as one."""
    handle, password = os.environ[HANDLE].strip(), os.environ[PASSWORD].strip()
    secrets = (password, handle) if "@" in handle else (password,)
    return Api("Bluesky", origin(), f"{HANDLE} and {PASSWORD}", secrets,
               transport=TRANSPORT)  # fmt: skip


@dataclass(frozen=True)
class Session:
    api: Api
    did: str
    token: str


def session(api: Api) -> Session:
    handle, password = os.environ[HANDLE].strip(), os.environ[PASSWORD].strip()
    said = api.call("POST", "/xrpc/com.atproto.server.createSession",
                    document={"identifier": handle, "password": password})  # fmt: skip
    token = said.get("accessJwt")
    if not isinstance(token, str) or not token:
        raise RemoteError("Bluesky answered the session with no access token")
    held = api.holding(token)
    if isinstance(said.get("refreshJwt"), str):
        held = held.holding(said["refreshJwt"])
    did = held.kept("DID", said.get("did"))
    if not did.startswith("did:"):
        raise RemoteError("Bluesky answered the session with no DID")
    return Session(held, did, token)


def upload(at: Session, image: Image) -> dict:
    said = at.api.call("POST", "/xrpc/com.atproto.repo.uploadBlob", data=image.data,
                       content_type=image.content_type, bearer=at.token)  # fmt: skip
    blob = said.get("blob")
    if not isinstance(blob, dict):
        raise RemoteError(f"Bluesky answered the upload of {image.name} with no blob")
    return blob


def _post_answer(at: Session, said: dict, rkey: str) -> dict:
    uri, cid = at.api.kept("URI", said.get("uri")), at.api.kept("CID", said.get("cid"))
    if not uri.startswith(f"at://{at.did}/{COLLECTION}/"):
        raise RemoteError("Bluesky answered a post's URI that is not of this account's posts")
    return {"uri": uri, "cid": cid, "url": f"{APP}/profile/{at.did}/post/{uri.rsplit('/', 1)[1]}",
            "rkey": rkey}  # fmt: skip


def held(at: Session, rkey: str) -> dict | None:
    """The post this account holds under `rkey`, or None where Bluesky says it holds none
    (`RecordNotFound`). Any other refusal is no answer, and is raised: read as "not found", a
    post made would be made again."""
    try:
        said = at.api.call("GET", "/xrpc/com.atproto.repo.getRecord", bearer=at.token,
                           query={"repo": at.did, "collection": COLLECTION, "rkey": rkey})
    except Answered as exc:
        if exc.status == 400 and exc.error == "RecordNotFound":
            return None
        raise
    return _post_answer(at, said, rkey)


def create(at: Session, rkey: str, post: dict) -> dict:
    said = at.api.call("POST", "/xrpc/com.atproto.repo.createRecord", bearer=at.token,
                       document=create_body(at.did, rkey, post))  # fmt: skip
    return _post_answer(at, said, rkey)


def _last_made(entry: dict) -> int:
    """The microseconds of the latest key `entry` records, a post's or the one pending; -1
    where it records none."""
    keyed = [*entry.get("posts", []), entry.get("pending")]
    found = [micros_of(one.get("rkey")) for one in keyed if isinstance(one, dict)]
    return max((micros for micros in found if micros is not None), default=-1)


def send(posts: list[str], images: list[Image], langs: list[str], entry: dict, keep, now
         ) -> None:  # fmt: skip
    """Post each post of `posts` that `entry` does not record as posted, recording each as it
    is posted (`keep(entry)`), and the key of each before it is sent.

    A key written down by an earlier run (`pending`) is asked for first, and sent again only
    where Bluesky says it holds no record under it; it is cleared only once the post is
    recorded, so that a refusal on the way leaves it for the next run to ask for again."""
    at = session(client())
    account = entry.setdefault("account", at.did)
    if account != at.did:
        raise RemoteError(f"the thread was begun from {account}, and these credentials are of "
                          f"{at.did}: resume it from the account it was begun from",
                          reached=False)  # fmt: skip
    done: list[dict] = entry.setdefault("posts", [])
    last = _last_made(entry)
    for index, text in enumerate(posts, 1):
        if index <= len(done):
            continue
        pending = entry.get("pending")
        inherited = isinstance(pending, dict) and pending.get("index") == index
        if inherited:
            found = held(at, str(pending["rkey"]))
            if found is not None:
                done.append({"index": index, **found, "posted_on": pending["created_at"]})
                entry.pop("pending")
                keep(entry)
                continue
            rkey, created = str(pending["rkey"]), str(pending["created_at"])
        else:
            moment = now()
            rkey, last = next_tid(moment, last)
            created = stamp(moment)
        embedded = None
        if index == 1 and images:
            embedded = [{"alt": image.alt, "image": upload(at, image)} for image in images]
        post = record(text, created, langs=langs, images=embedded, reply=reply_to(done))
        if not inherited:
            entry["pending"] = {"index": index, "rkey": rkey, "created_at": created}
            keep(entry)
        try:
            made = create(at, rkey, post)
        except RemoteError as exc:
            if not exc.reached and not inherited:
                entry.pop("pending")  # refused before it was acted on: nothing was made
                keep(entry)
            raise
        done.append({"index": index, **made, "posted_on": created})
        entry.pop("pending")
        keep(entry)


def manual(posts: list[str], images: list[Image]) -> str:
    """What to paste where, by hand."""
    lines = [f"Bluesky, by hand: sign in at {APP}, and paste post 1 as a new post"
             + (", each after it as a reply to the one before:" if len(posts) > 1 else ":")]
    for index, text in enumerate(posts, 1):
        lines += ["", f"--- post {index} ---", text]
    for image in images:
        lines += ["", f"Attach {image.name} to post 1, with the alternative text: {image.alt}"]
    return "\n".join(lines) + "\n"
