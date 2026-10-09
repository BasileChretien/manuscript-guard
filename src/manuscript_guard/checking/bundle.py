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
from datetime import datetime
from pathlib import Path

from manuscript_guard.checking.items import Items, as_payload

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


def build_bundle(
    items: Items,
    *,
    person: str,
    title: str,
    out: Path,
    to: str = "",
) -> tuple[Path, int]:
    """Write the page for one person. Returns the file and its size in bytes."""
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
    # The bundle's own name: the project's items and who it went to, so an answers file can be
    # told from one made against a later state of the manuscript.
    identity = hashlib.sha256(
        (json.dumps([i["digest"] for i in payload["items"]], sort_keys=True) + person).encode()
    ).hexdigest()[:12]
    payload.update(
        {
            "images": images,
            "bundle": identity,
            "by": person,
            "to": to,
            "built_on": built_on,
            "filename": f"answers-{slug(person)}.json",
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
    return out, size


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
