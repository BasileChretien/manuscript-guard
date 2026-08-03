"""Fetching a guideline's own checklist document, on request.

The design question this answers is a licensing one. Reporting guidelines are published
under a patchwork of terms — RECORD says CC BY, READUS-PV is CC BY-NC, and several state no
reuse licence at all — so a repository that ships their text has to satisfy the strictest of
them, and cannot.

Fetching sidesteps it. When this downloads from the publisher's own URL because the user
asked it to, the user obtains the document exactly as they would by clicking the link, and
the project distributes nothing. What the project ships is the recipe: instructions for
reading a document the user already holds.

Three deliberate choices follow:

* **Never on install.** `pip install` runs offline in CI and sandboxes, network side-effects
  break reproducible builds, and a silent download means nobody reads the terms. Fetching is
  an explicit command.
* **The licence is printed before the download**, so the terms are seen rather than
  buried in a file nobody opens.
* **The document is checksummed** against the recipe. That proves the file is the one the
  recipe was written for, and turns a silently revised checklist — new items, moved columns
  — into a clear failure instead of a plausible wrong transcription.
"""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard import __version__

USER_AGENT = f"manuscript-guard/{__version__} (+https://github.com/BasileChretien/manuscript-guard)"
TIMEOUT = 120
MAX_BYTES = 40 * 1024 * 1024


class FetchError(Exception):
    """The document could not be obtained."""


@dataclass(frozen=True)
class FetchResult:
    path: Path
    bytes_written: int
    digest: str
    expected: str | None

    @property
    def matches(self) -> bool:
        return self.expected is None or self.digest == self.expected


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_document(
    url: str,
    destination: Path,
    *,
    expected_sha256: str | None = None,
    overwrite: bool = False,
) -> FetchResult:
    """Download one document. Refuses to overwrite silently."""
    if destination.exists() and not overwrite:
        data = destination.read_bytes()
        return FetchResult(destination, 0, sha256_bytes(data), expected_sha256)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(
            f"could not download {url}: {exc}. Checklist download links move often — open "
            f"the guideline's page and save the file into {destination.parent} yourself."
        ) from exc

    if len(data) > MAX_BYTES:
        raise FetchError(f"{url} returned more than {MAX_BYTES // 1024 // 1024} MB; refusing")
    if not data:
        raise FetchError(f"{url} returned nothing")
    _reject_wrong_type(url, destination, data)

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return FetchResult(destination, len(data), sha256_bytes(data), expected_sha256)


# A .docx is a zip ("PK"), a PDF starts "%PDF". Anything beginning with markup is a web
# page wearing a document's file extension.
MAGIC = {".docx": b"PK", ".pdf": b"%PDF"}


def _reject_wrong_type(url: str, destination: Path, data: bytes) -> None:
    """Refuse to save a landing page as though it were the document.

    Several checklist "download" links are HTML: a redirect page, a viewer wrapper, or a
    site's 404. Saved under a .docx name they fail much later and confusingly — the first
    version of this fetched two such pages and only the checksum caught them. Failing here
    says what actually happened.
    """
    expected = MAGIC.get(destination.suffix.lower())
    if expected is None or data.startswith(expected):
        return
    looks_like_html = data.lstrip()[:15].lower().startswith((b"<!doctype", b"<html", b"<?xml"))
    what = "a web page" if looks_like_html else "something else"
    raise FetchError(
        f"{url} returned {what}, not {destination.suffix}. The link is probably a landing "
        f"page or a viewer wrapper rather than the file itself. Open the guideline's page, "
        f"copy the direct link to the document, and pass it with --url."
    )


def licence_notice(meta: dict) -> str:
    """What the user should see before a document is downloaded on their behalf."""
    lines = [
        f"  {meta['name']} — {meta.get('long_name', '')}".rstrip(),
        f"    source:  {meta['source_url']}",
        f"    licence: {meta['licence']}",
    ]
    if meta.get("licence_url"):
        lines.append(f"    terms:   {meta['licence_url']}")
    lines.append(
        "    This downloads the guideline's own document to your machine. "
        "manuscript-guard redistributes none of it."
    )
    return "\n".join(lines)
