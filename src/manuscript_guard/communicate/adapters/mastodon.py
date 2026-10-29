"""Mastodon: each image with its description, then a status for each post.

The requests, as docs.joinmastodon.org names them (read on 2026-10-29):

1. `POST /api/v2/media` for each image, as a form with the file and its `description`, the
   alternative text. It answers the attachment's id, at once (200) or while the server is
   still working on it (202, its `url` null); the attachment is then asked for
   (`GET /api/v1/media/:id`) until it is ready, a few times.
2. `POST /api/v1/statuses` for each post, public, its language, the images on the first,
   and a thread's each `in_reply_to_id` the post before. Each is sent with an
   `Idempotency-Key`: the digest of the approved text, of the files it attaches and of the
   post's number, so that a status sent again, after an answer was lost, is the one status,
   and a corrected image under the same name is another.

Mastodon keeps a key for an hour, and no longer. A post whose answer was lost is recorded with
its key and the moment it was sent (`pending`, `pending_at`); `--resume` sends it again with
the same key only within `KEY_LIFETIME` of that moment. After it, a key sent again may be
unknown to the instance and the post made twice, so `--resume` refuses and asks the author,
who has looked at the account's page: `--was-posted <its link or id>` records the status
they found (asked of the instance, and held to be this account's, no boost, made within
`SENT_BEFORE` before and `KEY_LIFETIME` and `SENT_AFTER` after the moment, and in reply to the
post before), and `--not-posted` sends the post under a new key.

The instance is the author's, `MASTODON_BASE_URL`; the token, `MASTODON_TOKEN`, goes into the
Authorization header and nowhere else. An instance sets its own limit on a post's length,
which `communicate check` holds to 500 by default (`communication.limits` in paper.yaml for
another).
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from manuscript_guard.communicate import Refused
from manuscript_guard.communicate.adapters.net import Api, Image, RemoteError, default_transport

BASE_URL, TOKEN = "MASTODON_BASE_URL", "MASTODON_TOKEN"
MAX_IMAGES = 4
#: How many times an attachment still being worked on is asked for, and how long apart.
READY_TRIES, READY_WAIT = 10, 1.0
#: The transport the client is given; a test puts its own in its place.
TRANSPORT = default_transport
#: How long after a status was sent its `Idempotency-Key` is taken to be kept. Mastodon keeps
#: one for up to an hour (docs.joinmastodon.org, "Post a new status", the `Idempotency-Key`
#: header, read on 2026-10-29); fifty minutes leaves a margin under it for the two clocks.
KEY_LIFETIME = timedelta(minutes=50)
#: How long before a post was sent, by this machine's clock, and how long after
#: `KEY_LIFETIME`, the status `--was-posted` names may have been made, by the instance's: a
#: margin for the two clocks, and for an instance that made the status late.
SENT_BEFORE, SENT_AFTER = timedelta(minutes=5), timedelta(minutes=10)
#: The port a link means where it writes none.
DEFAULT_PORTS = {"http": 80, "https": 443}
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"
_CREATED = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d+))?(Z|z|[+-]\d\d:?\d\d)?")


def idempotency_key(text_sha256: str, attachments_sha256: str, index: int,
                    attempt: int = 0) -> str:  # fmt: skip
    """The key a post is sent with: the same for the same approved text, the same files
    attached and the same post; `attempt`, past naught, where the author said a post sent
    under an earlier key did not go out."""
    said = f"{text_sha256}:{attachments_sha256}:{index}" + (f":{attempt}" if attempt else "")
    return hashlib.sha256(said.encode()).hexdigest()[:40]


def sent_at(pending: dict) -> datetime | None:
    """When the post `pending` records was sent, or None where it does not say."""
    try:
        return datetime.strptime(str(pending.get("pending_at")), _STAMP).replace(
            tzinfo=timezone.utc)  # fmt: skip
    except ValueError:
        return None


def expired(pending: dict, moment: datetime) -> bool:
    """Whether the key of the post `pending` records may no longer be kept by the instance at
    `moment`: `KEY_LIFETIME` has passed since it was sent, or when is not recorded."""
    when = sent_at(pending)
    return when is None or moment - when >= KEY_LIFETIME


def status(text: str, *, language: str, media_ids: list[str] | None = None,
           in_reply_to_id: str | None = None) -> dict:  # fmt: skip
    """The body of one status."""
    out: dict = {"status": text, "visibility": "public", "language": language}
    if media_ids:
        out["media_ids"] = media_ids
    if in_reply_to_id:
        out["in_reply_to_id"] = in_reply_to_id
    return out


def form(image: Image) -> tuple[bytes, str]:
    """The media form of one image, as `multipart/form-data`, and its content type. The
    boundary is the file's digest, so that the same image gives the same bytes."""
    boundary = "mg-" + hashlib.sha256(image.data).hexdigest()[:32]
    name = image.name.replace('"', "").replace("\r", "").replace("\n", "")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"description\"\r\n\r\n".encode()
        + image.alt.encode("utf-8") + b"\r\n",
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\""
         f"\r\nContent-Type: {image.content_type}\r\n\r\n").encode() + image.data + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]  # fmt: skip
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def planned(posts: list[str], images: list[Image], language: str, text_sha256: str,
            attachments_sha256: str) -> list[dict]:  # fmt: skip
    """The requests `--post` would send, written for the outbox: what the instance answers in
    angle brackets; no token."""
    base = f"<{BASE_URL}>"
    requests = [{
        "method": "POST", "url": f"{base}/api/v2/media",
        "body": {"file": image.name, "bytes": len(image.data), "description": image.alt},
    } for image in images]  # fmt: skip
    for index, text in enumerate(posts, 1):
        body = status(text, language=language,
                      media_ids=[f"<the id {image.name} answers>" for image in images]
                      if index == 1 else None,
                      in_reply_to_id=f"<post {index - 1}'s id>" if index > 1 else None)
        requests.append({"method": "POST", "url": f"{base}/api/v1/statuses",
                         "headers": {"Idempotency-Key": idempotency_key(
                             text_sha256, attachments_sha256, index)},
                         "body": body})  # fmt: skip
    return requests


def missing() -> list[str]:
    return [name for name in (BASE_URL, TOKEN) if not os.environ.get(name, "").strip()]


def client(sleep=None) -> tuple[Api, str]:
    token = os.environ[TOKEN].strip()
    base = os.environ[BASE_URL].strip().rstrip("/")
    extra = {"sleep": sleep} if sleep is not None else {}
    return Api("Mastodon", base, f"{BASE_URL} and {TOKEN}", (token,), transport=TRANSPORT,
               **extra), token  # fmt: skip


def upload(api: Api, token: str, image: Image) -> str:
    body, content_type = form(image)
    said = api.call("POST", "/api/v2/media", data=body, content_type=content_type,
                    bearer=token, expect=(200, 202))  # fmt: skip
    media = api.kept("media id", said.get("id"))
    tries = 0
    while said.get("url") is None and tries < READY_TRIES:
        api.sleep(READY_WAIT)
        tries += 1
        said = api.call("GET", f"/api/v1/media/{_path_safe(media)}", bearer=token,
                        expect=(200, 206))  # fmt: skip
    if said.get("url") is None:
        raise RemoteError(f"Mastodon was still working on {image.name} after {READY_TRIES} "
                          "asks; nothing was posted, so run it again later",
                          reached=False)  # fmt: skip
    return media


def _path_safe(said: str) -> str:
    if not said.isascii() or not said.isalnum():
        raise RemoteError("Mastodon answered an id that cannot go into a path")
    return said


def send(posts: list[str], images: list[Image], language: str, digests: tuple[str, str],
         entry: dict, keep, now, sleep=None, *, was_posted: str | None = None,
         not_posted: bool = False) -> None:  # fmt: skip
    """Post each post of `posts` that `entry` does not record as posted, recording each as
    it is posted (`keep(entry)`), and its key and the moment before it is sent. `digests` are
    the text's and its attachments'.

    A post an earlier run sent and heard nothing of (`pending`) is sent again with its own key,
    which the caller has held to be within `KEY_LIFETIME`; or, the author having looked,
    recorded as the status `was_posted` names, or sent under a new key (`not_posted`). It is
    cleared only once the post is recorded: a refusal on the way leaves it as it was."""
    from manuscript_guard.communicate.adapters.bluesky import stamp

    api, token = client(sleep)
    entry.setdefault("account", api.origin)
    if entry["account"] != api.origin:
        raise RemoteError(f"the thread was begun at {entry['account']}, and {BASE_URL} names "
                          f"{api.origin}: resume it where it was begun", reached=False)
    done: list[dict] = entry.setdefault("posts", [])
    inherited = entry.get("pending") if isinstance(entry.get("pending"), dict) else None
    if inherited is not None and was_posted is not None:
        done.append(confirmed(api, token, was_posted, inherited, done))
        entry.pop("pending")
        keep(entry)
        inherited = None
    for index, text in enumerate(posts, 1):
        if index <= len(done):
            continue
        again = inherited is not None and inherited.get("index") == index
        resent = again and not not_posted
        attempt = int(inherited.get("attempt") or 0) + 1 if again and not_posted else 0
        key = (str(inherited["idempotency_key"]) if resent
               else idempotency_key(*digests, index, attempt))  # fmt: skip
        media = [upload(api, token, image) for image in images] if index == 1 else None
        reply = str(done[-1]["id"]) if done else None
        if not resent:
            entry["pending"] = {"index": index, "idempotency_key": key,
                                **({"attempt": attempt} if attempt else {}),
                                "pending_at": stamp(now())}  # fmt: skip
            keep(entry)
        try:
            said = api.call("POST", "/api/v1/statuses", bearer=token,
                            document=status(text, language=language, media_ids=media,
                                            in_reply_to_id=reply),
                            headers={"Idempotency-Key": key})  # fmt: skip
        except RemoteError as exc:
            if not exc.reached and not resent:
                entry.pop("pending")  # refused before it was acted on: nothing was made
                keep(entry)
            raise
        posted = {"index": index, "id": api.kept("status id", said.get("id"))}
        if said.get("url") is not None:
            posted["url"] = api.kept("link", said.get("url"))
        done.append({**posted, "posted_on": stamp(now())})
        entry.pop("pending", None)
        keep(entry)


def status_id(api: Api, said: str) -> str:
    """The id of the status the author named, by its id or by its link on this instance."""
    said = said.strip()
    if "://" in said:
        link = urlsplit(said)
        if _place(link) != _place(urlsplit(api.origin)):
            raise Refused(f"--was-posted names a link that is not on {api.origin}, where the "
                          "thread is: give the link of the post on your own instance, or its id")
        parts = [part for part in link.path.split("/") if part]
        said = parts[-1] if parts else ""
    if not said or not said.isascii() or not said.isalnum():
        raise Refused("--was-posted takes the post's link on your instance, "
                      "`https://example.social/@you/1234`, or its id, `1234`")  # fmt: skip
    return said


def _place(link) -> tuple[str, str, int | None]:
    """A link's scheme, host and port, the port written or the scheme's own."""
    scheme = link.scheme.lower()
    try:
        port = link.port
    except ValueError:
        raise Refused("--was-posted names a link whose port is no number: give the link of "
                      "the post on your own instance, or its id") from None  # fmt: skip
    return scheme, (link.hostname or "").lower(), port or DEFAULT_PORTS.get(scheme)


def created(said: object) -> datetime | None:
    """The moment a status's `created_at` writes, ISO 8601, or None where it writes none."""
    found = _CREATED.fullmatch(said.strip()) if isinstance(said, str) else None
    if found is None:
        return None
    day, fraction, zone = found.groups()
    try:
        moment = datetime.strptime(day, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    moment = moment.replace(microsecond=int((fraction or "0")[:6].ljust(6, "0")))
    if zone in (None, "Z", "z"):
        return moment.replace(tzinfo=timezone.utc)
    sign = -1 if zone[0] == "-" else 1
    hours, minutes = int(zone[1:3]), int(zone[-2:])
    try:
        return moment.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
    except ValueError:  # an offset of a day or more
        return None


def confirmed(api: Api, token: str, was_posted: str, pending: dict, done: list[dict]) -> dict:
    """The post the author found on the account's page, as the instance answers it, recorded
    in the place of the post `pending` sent: refused where it is not this account's, is a
    boost, was made outside the time the post was sent in (`SENT_BEFORE`, `SENT_AFTER`), or
    does not reply to the post before it (or replies to anything, as a thread's first). Its
    words are not compared: Mastodon answers them as HTML."""
    wanted = status_id(api, was_posted)
    said = api.call("GET", f"/api/v1/statuses/{wanted}", bearer=token)
    me = api.call("GET", "/api/v1/accounts/verify_credentials", bearer=token)
    author = said.get("account") if isinstance(said.get("account"), dict) else {}
    if str(said.get("id")) != wanted or str(author.get("id")) != str(me.get("id")):
        raise Refused(f"status {wanted} is not a post of the account {TOKEN} signs in as: "
                      "give the link of the post you found on your own account's page")
    if said.get("reblog") is not None:
        raise Refused(f"status {wanted} is a boost of another post, not post "
                      f"{pending.get('index')} of the thread: give the link of the post itself")
    sent, made = sent_at(pending), created(said.get("created_at"))
    if sent is None or made is None or not (sent - SENT_BEFORE <= made
                                            <= sent + KEY_LIFETIME + SENT_AFTER):  # fmt: skip
        when = pending.get("pending_at") or "a moment not recorded"
        raise Refused(f"status {wanted} was made at {said.get('created_at')}, and post "
                      f"{pending.get('index')} of the thread was sent at {when} (UTC): it is "
                      "another post. Give the link of the one made then, or `--not-posted` "
                      "where there is none")  # fmt: skip
    before = str(done[-1]["id"]) if done else None
    replies = said.get("in_reply_to_id")
    if (str(replies) if replies is not None else None) != before:
        where = f"in reply to post {len(done)}, {before}" if before else "as a new post"
        raise Refused(f"status {wanted} is not post {pending.get('index')} of the thread: that "
                      f"one was sent {where}")  # fmt: skip
    posted = {"index": pending.get("index"), "id": api.kept("status id", said.get("id"))}
    if said.get("url") is not None:
        posted["url"] = api.kept("link", said.get("url"))
    return {**posted, "posted_on": str(pending.get("pending_at")), "recorded": "--was-posted"}


def manual(posts: list[str], images: list[Image]) -> str:
    lines = ["Mastodon, by hand: sign in on your instance, and paste post 1 as a new public post"
             + (", each after it as a reply to the one before:" if len(posts) > 1 else ":")]
    for index, text in enumerate(posts, 1):
        lines += ["", f"--- post {index} ---", text]
    for image in images:
        lines += ["", f"Attach {image.name} to post 1, with the description: {image.alt}"]
    return "\n".join(lines) + "\n"
