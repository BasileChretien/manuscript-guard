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

import json
import re
from dataclasses import dataclass

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
