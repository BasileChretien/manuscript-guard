"""Writing the one file a co-author is sent.

Everything is inside it: the items, the sentences, and the evidence, images included, as data
URIs. That is not elegance, it is the requirement — a co-author who receives a folder opens the
page from inside the zip viewer, the images do not load, and they conclude the thing is broken.
One file has nothing to go wrong.

The page is served from nowhere. It makes no request, loads no font, no script and no stylesheet
from a network, and works on a laptop in a hospital with no connection. The two things it writes
are the viewer's own browser storage (which keeps their answers across a closed tab, though not
a note they have typed and not yet attached to one, and nothing at all where a browser refuses
storage) and the answers file they
send back.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from manuscript_guard.checking import register
from manuscript_guard.checking.items import Items, as_payload
from manuscript_guard.checking.register import state_of

TEMPLATE = Path(__file__).with_name("checker.html")
#: Big enough for a page image of a scanned table, small enough that nobody's mail server
#: refuses it. A project that needs more should render its pages smaller, not raise this.
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_BUNDLE_BYTES = 24 * 1024 * 1024
#: What a browser will show from a data URI without a plugin.
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}


class BundleError(Exception):
    """The bundle cannot be written, and the message says what to change."""


def slug(name: str) -> str:
    """A file name from a person's name, keeping it recognisable and portable.

    Accents are folded rather than dropped, because "answers-cabe.json" should be readable by
    the person who sent it; a name in another script that folds to nothing falls back to a hash
    so that two co-authors never share a file name.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", folded).strip("-").lower()
    return cleaned or hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]


def _data_uri(path: Path) -> str:
    if not path.is_file():
        raise BundleError(
            f"{path} is named as evidence and is not there. The items file points at its "
            f"evidence by path, relative to itself."
        )
    kind = IMAGE_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if kind not in IMAGE_TYPES.values():
        raise BundleError(
            f"{path} is {kind or 'of an unknown type'}; evidence images must be PNG, JPEG, GIF, "
            f"WebP or SVG, which a browser shows without anything installed."
        )
    raw = path.read_bytes()
    if len(raw) > MAX_IMAGE_BYTES:
        raise BundleError(
            f"{path} is {len(raw) // 1024} kB, over the {MAX_IMAGE_BYTES // 1024} kB a single "
            f"piece of evidence may be. Render the page smaller: a checker reads a value, not "
            f"the typesetting."
        )
    return f"data:{kind};base64," + base64.b64encode(raw).decode("ascii")


@dataclass(frozen=True)
class Built:
    """One page written: where, how large, and what the register keeps of it."""

    path: Path
    size: int
    person: str
    orcid: str
    bundle: str
    token: str
    state: str
    items: int
    built_on: str


def build_bundle(
    items: Items,
    *,
    person: str,
    title: str,
    out: Path,
    to: str = "",
) -> tuple[Path, int]:
    """Write the page for one person. Returns the file and its size in bytes."""
    built = build_page(items, person=person, title=title, out=out, to=to)
    return built.path, built.size


def build_page(
    items: Items,
    *,
    person: str,
    title: str,
    out: Path,
    to: str = "",
    orcid: str = "",
    token: str | None = None,
    shown: str = "",
) -> Built:
    """Write the page for one person, carrying their name, their ORCID iD where they have one
    and a random token of its own (`register.new_token`, unless one is given).

    `person` is the name their answers are recorded under, which the answers file carries;
    `shown`, where given, the name the page greets them by, which `checker build` makes the
    same."""
    person = person.strip()
    if not person:
        raise BundleError("say who the file is for: a decision is recorded under their name")

    payload = as_payload(items)
    # One image, carried once. A page of a source document is evidence for every value printed
    # on it, so in a real queue one page can be named by twenty-five items; inlined per item it
    # would be carried twenty-five times and the file would not fit in an email.
    images: dict[str, str] = {}
    for item in payload["items"]:
        evidence = []
        for one in item.get("evidence") or ():
            copy = dict(one)
            if copy.get("kind") == "image":
                named = copy.pop("file", None)
                if named:
                    path = (items.path.parent / str(named)).resolve()
                    key = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
                    if key not in images:
                        images[key] = _data_uri(path)
                    copy["img"] = key
            evidence.append(copy)
        if evidence:
            item["evidence"] = evidence
    carried = len(images)

    built_on = datetime.now().astimezone().isoformat(timespec="seconds")
    token = token or register.new_token()
    digests = [i["digest"] for i in payload["items"]]
    # Where the browser keeps a co-author's unsent answers: the items and who they went to, so a
    # page rebuilt with nothing changed for them keeps their progress.
    storage = hashlib.sha256((json.dumps(digests, sort_keys=True) + person).encode()).hexdigest()
    # The page's own name, which the register keys on: that, and the token, so that no two
    # builds share one and an answers file names the one page it came from.
    identity = hashlib.sha256((storage + token).encode()).hexdigest()[:12]
    orcid = orcid.strip()
    state = state_of(digests)
    payload.update(
        {
            "images": images,
            "bundle": identity,
            "storage": storage[:12],
            "by": person,
            "person": {"name": shown.strip() or person, "orcid": orcid},
            "token": token,
            "state": state,
            "to": to,
            "built_on": built_on,
            "filename": f"answers-{slug(shown.strip() or person)}.json",
        }
    )

    html = TEMPLATE.read_text(encoding="utf-8")
    # Every `<` in the data is written `\u003c`, which JSON and JavaScript both read back as `<`.
    # Escaping only `</` kept `</script>` from ending the page's own script, but an item holding
    # `<!--` and then `<script` put the browser's parser in a state where the page's real
    # `</script>` closed nothing, and the page showed nothing. The line and paragraph separators
    # are escaped because a JavaScript older than 2019 reads either as the end of a line, inside
    # a string. Written as escapes here too: the characters themselves are invisible in source.
    encoded = (
        json.dumps(payload, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    page = html.replace("__BUNDLE__", encoded).replace("__TITLE__", _escape(title))
    if "__BUNDLE__" in page or "__TITLE__" in page:
        raise BundleError("the page template no longer carries both of its placeholders")

    # Measured before it is written: a page refused for its size used to be left on disk, where
    # it could be sent all the same.
    data = page.encode("utf-8")
    size = len(data)
    if size > MAX_BUNDLE_BYTES:
        raise BundleError(
            f"{out.name} would come to {size // 1024 // 1024} MB, over the "
            f"{MAX_BUNDLE_BYTES // 1024 // 1024} MB a mail server will usually carry. It holds "
            f"{carried} distinct image(s): render them smaller, or split the items between "
            f"files."
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return Built(path=out, size=size, person=person, orcid=orcid, bundle=identity, token=token,
                 state=state, items=len(digests), built_on=built_on)  # fmt: skip


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
