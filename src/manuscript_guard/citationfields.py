"""A citation field of Word's Zotero plugin, known by its code rather than by its words.

A live build writes each citation as a field: `ADDIN ZOTERO_ITEM CSL_CITATION {...}` in its
code, and the words it shows after it. The words are whatever Zotero last formatted, so a
co-author's Refresh, or a switch of style, changes them with nothing cited changed. The code
says what is cited: each item's URI, and the locator, prefix and suffix of each.

So a field is known by its identity, those parts of its code, and its words are left aside.
An item is named by the key at the end of its URI (`.../items/ABCD1234`): Zotero writes a
library's URI anew when it is synced (`users/local/...` becomes `users/123/...`), and the key
stays. The citation's own ID and each item's local ID are not part of it, and neither is the
item's data, which a Refresh brings up to date.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from xml.sax.saxutils import unescape

#: A citation field's code. Word may split it over several `instrText` runs; it is read
#: whole, joined, before it is matched.
_CITATION = re.compile(r"\A\s*ADDIN\s+ZOTERO_ITEM\s+CSL_CITATION\s+(\{.*\})\s*\Z", re.DOTALL)
_ITEM_KEY = re.compile(r"/items/([A-Za-z0-9]+)/?\Z")
#: What of an item, beside the item itself, the citation says: where in the work, the words
#: around it, and whether the author's name is printed.
_KEPT = ("locator", "label", "prefix", "suffix", "suppress-author", "author-only")


@dataclass(frozen=True)
class Citation:
    """What a citation field cites, and the words its code says it shows."""

    #: Each item in order, by its key, with its locator, prefix and suffix: canonical JSON.
    identity: str
    #: `properties.formattedCitation`: on a field a build just wrote, the citation as the
    #: source writes it; once Zotero has refreshed it, Zotero's words.
    formatted: str


def citation_of(code: str) -> Citation | None:
    """The citation a field's code holds, or None where the code is not a Zotero citation's,
    or not one this can read: a field's code is anyone's to edit."""
    match = _CITATION.match(code)
    if match is None:
        return None
    try:
        data = json.loads(match.group(1))
    except (ValueError, RecursionError):
        return None
    entries = data.get("citationItems") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        return None
    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        # `uri` in documents written by Zotero before 5.
        uris = entry.get("uris", entry.get("uri"))
        uris = [uris] if isinstance(uris, str) else uris
        if not isinstance(uris, list) or not uris or not all(isinstance(u, str) for u in uris):
            return None
        keys = sorted({(found.group(1) if (found := _ITEM_KEY.search(u)) else u) for u in uris})
        item: dict[str, object] = {"items": keys}
        for name in _KEPT:
            value = entry.get(name)
            if value not in (None, "", False):
                item[name] = value
        items.append(item)
    properties = data.get("properties")
    formatted = properties.get("formattedCitation") if isinstance(properties, dict) else None
    return Citation(
        json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        formatted if isinstance(formatted, str) else "",
    )


# ---------------------------------------------------------------- a citation inserted in Word

#: A citation field a reference manager writes in Word, by its code: CSL JSON after the
#: name, as Zotero's and others' fields hold it, or the XML of an `EN.CITE` field.
_CSL_FIELD = re.compile(r"\A\s*ADDIN\s+(?:ZOTERO_ITEM\s+)?CSL_CITATION\s+(\{.*\})\s*\Z", re.DOTALL)
_EN_CITE = re.compile(r"\A\s*ADDIN\s+EN\.CITE(?:\.DATA)?\b(.*)\Z", re.DOTALL)
#: The tag of a content control a reference manager wraps a citation in, its CSL JSON
#: encoded in base64 after the last underscore.
_TAGGED = re.compile(r"\AMENDELEY_CITATION(?:_v\d+)?_?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Work:
    """What a citation field says of one work it cites: as much as it says."""

    author: str = ""
    year: str = ""
    title: str = ""
    doi: str = ""

    def __str__(self) -> str:
        said = " ".join(part for part in (self.author, self.year) if part)
        title = self.title if len(self.title) <= 80 else self.title[:77] + "..."
        if title:
            said = f'{said}, "{title}"' if said else f'"{title}"'
        return said or "a work it does not name"


def inserted(code: str) -> tuple[Work, ...] | None:
    """The works a citation field or a reference manager's content control cites, where its
    code is one (`fields_of` gives a content control's tag as its code); None where it is
    not a citation's. A citation whose code cannot be read is one work it does not name."""
    for pattern, read in ((_CSL_FIELD, _csl_works), (_TAGGED, _tagged_works)):
        found = pattern.match(code)
        if found is not None:
            return read(found.group(1)) or (Work(),)
    found = _EN_CITE.match(code)
    if found is not None:
        return _endnote_works(found.group(1)) or (Work(),)
    return None


def _csl_works(text: str) -> tuple[Work, ...]:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return ()
    entries = data.get("citationItems") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return ()
    works = []
    for entry in entries:
        item = entry.get("itemData") if isinstance(entry, dict) else None
        works.append(_csl_work(item) if isinstance(item, dict) else Work())
    return tuple(works)


def _csl_work(item: dict) -> Work:
    authors = item.get("author")
    first = authors[0] if isinstance(authors, list) and authors else {}
    author = ""
    if isinstance(first, dict):
        author = str(first.get("family") or first.get("literal") or "")
    issued = item.get("issued")
    year = ""
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            year = str(parts[0][0])
        elif isinstance(issued.get("raw"), str):
            year = issued["raw"][:4]
    title = item.get("title")
    doi = item.get("DOI")
    return Work(
        author,
        year,
        str(title) if isinstance(title, str) else "",
        str(doi) if isinstance(doi, str) else "",
    )


def _tagged_works(text: str) -> tuple[Work, ...]:
    encoded = text.rsplit("_", 1)[-1]
    try:
        decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4), validate=True)
        return _csl_works(decoded.decode("utf-8"))
    except (binascii.Error, ValueError):
        return ()


def _endnote_works(text: str) -> tuple[Work, ...]:
    """Each `<Cite>` of an `EN.CITE` field: its first author, year and title. The XML is read
    by its elements' names, not parsed: it is whatever the field's code says."""
    text = unescape(text)
    works = []
    for cite in re.findall(r"<Cite\b.*?</Cite>", text, re.DOTALL):
        def first(name: str, cite: str = cite) -> str:
            found = re.search(rf"<{name}\b[^>]*>(.*?)</{name}>", cite, re.DOTALL)
            return re.sub(r"<[^>]+>", "", found.group(1)).strip() if found else ""

        author = first("Author").split(",")[0].strip()
        works.append(Work(author, first("Year"), first("title"),
                          first("electronic-resource-num")))  # fmt: skip
    return tuple(works)
