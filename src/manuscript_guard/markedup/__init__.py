"""The marked-up copy a journal asks for at resubmission: the revision, with every change since
the document it was sent shown.

`write` compares the document that was sent (`before`) with the revision as just built
(`after`), printed text against printed text, so that a number the analysis printed anew is
a change like any word typed: see `writer`, `atoms` (what is compared), `align`
(what is paired with what) and `verify` (the check that every copy passes before it is
kept). The copy is the revision's own document with the changes written in as Word's tracked
changes, all by one author, "Revision", which names nobody; or, where the journal asks for
highlights, with what was added highlighted and what was removed struck through.

The copy is never the manuscript. It carries a property saying what it is
(`MARKED_UP_PROPERTY`) and none of the build's stamps, so `import`, `respond --from` and
`submit --document` refuse it, and `check` does not take it for a build.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from manuscript_guard.markedup.package import CUSTOM, DOCUMENT, FOOTNOTES, MarkedUpError, Package, W

__all__ = [
    "AUTHOR",
    "FORMS",
    "MARKED_UP_PROPERTY",
    "MarkedUpError",
    "Made",
    "marked_up_of",
    "write",
]

#: The author of every change: no person, so that a blind review stays blind.
AUTHOR = "Revision"
#: Tracked changes, or highlights where the journal asks for them.
FORMS = ("tracked", "highlighted")
#: What the copy says it is: its form, and the SHA-256 of the document it was compared with.
MARKED_UP_PROPERTY = "manuscript-guard-marked-up"
#: The changes a document sent may not hold: it is compared as it was read.
_PENDING = frozenset(
    W + t
    for t in ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "trPrChange",
              "tblPrChange", "tcPrChange", "sectPrChange", "cellIns", "cellDel", "cellMerge")
)  # fmt: skip
_PROPERTY = re.compile(
    rf'<property\b[^>]*\bname="{MARKED_UP_PROPERTY}"[^>]*>\s*<vt:lpwstr>(.*?)</vt:lpwstr>',
    re.DOTALL,
)


@dataclass(frozen=True)
class Made:
    """What one marked-up copy shows: how many of each kind of change."""

    path: Path
    form: str
    counts: dict[str, int]

    @property
    def changed(self) -> bool:
        return any(self.counts.values())


def _pending(package: Package) -> int:
    count = 0
    for part in (DOCUMENT, FOOTNOTES):
        tree = package.tree(part)
        if tree is not None:
            count += sum(1 for node in tree.iter() if node.tag in _PENDING)
    return count


def marked_up_of(document: Path) -> dict | None:
    """What a marked-up copy says it is, or None for any other document."""
    import zipfile

    from manuscript_guard.safexml import UnsafeDocument, read_member

    try:
        with zipfile.ZipFile(document) as archive:
            if CUSTOM not in archive.namelist():
                return None
            xml = read_member(archive, CUSTOM).decode("utf-8", "replace")
    except (OSError, zipfile.BadZipFile, UnsafeDocument):
        return None
    found = _PROPERTY.search(xml)
    if found is None:
        return None
    from xml.sax.saxutils import unescape

    try:
        said = json.loads(unescape(found.group(1)))
    except ValueError:
        return {}
    return said if isinstance(said, dict) else {}


def _stamped(package: Package, said: dict) -> None:
    """The copy's properties: the build's stamps taken out, since the copy is not the build
    and nothing may read it as one, and what it is put in."""
    from manuscript_guard.roundtrip import (
        _CUSTOM_PROPERTY,
        _CUSTOM_REL,
        _CUSTOM_RELS,
        _CUSTOM_XML,
        _PROPERTY_ELEMENT,
        _ours,
    )

    existing = package.parts.get(CUSTOM, b"").decode("utf-8", "replace")
    kept = [
        element
        for element in _PROPERTY_ELEMENT.findall(existing)
        if not _ours(element) and f'name="{MARKED_UP_PROPERTY}"' not in element
    ]
    value = escape(json.dumps(said, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    ours = [_CUSTOM_PROPERTY.format(name=MARKED_UP_PROPERTY, value=value)]
    numbered = [
        re.sub(r'\bpid="\d+"', f'pid="{i}"', element, count=1)
        for i, element in enumerate(kept + ours, start=2)
    ]
    if CUSTOM not in package.parts:
        package.parts["[Content_Types].xml"] = package.parts["[Content_Types].xml"].replace(
            b"</Types>", _CUSTOM_RELS.encode() + b"</Types>"
        )
        package.parts["_rels/.rels"] = package.parts["_rels/.rels"].replace(
            b"</Relationships>", _CUSTOM_REL.encode() + b"</Relationships>"
        )
    package.add_part(CUSTOM, _CUSTOM_XML.format(properties="".join(numbered)).encode("utf-8"))


def write(
    before: Path,
    after: Path,
    target: Path,
    *,
    date: str,
    form: str = "tracked",
    round_number: int | None = None,
) -> Made:
    """Write to `target` the revision `after` with every change since `before` shown, in
    `form`, every change dated `date` (an ISO 8601 day). The copy is checked before it is
    kept (`verify.check`); a copy that would not pass raises `MarkedUpError` and nothing is
    written."""
    import hashlib

    from manuscript_guard.markedup.verify import check, highlighted
    from manuscript_guard.markedup.writer import Writer

    if form not in FORMS:
        raise MarkedUpError(f"no marked-up copy of the form {form!r}: {' or '.join(FORMS)}")
    for document in (before, after):
        if marked_up_of(document) is not None:
            raise MarkedUpError(
                f"{document.name} is itself a marked-up copy; compare the documents it was "
                f"made from"
            )
    old, new = Package.read(before), Package.read(after)
    for package, which in ((old, "the document sent"), (new, "the revision")):
        pending = _pending(package)
        if pending:
            raise MarkedUpError(
                f"{package.name}, {which}, holds {pending} tracked change(s) nobody accepted or "
                f"rejected, so it does not say one text to compare; accept or reject them in "
                f"Word and save it first"
            )
    writer = Writer(old, new, author=AUTHOR, date=f"{date}T00:00:00Z")
    body = new.body()
    merged = writer.merge_story(list(old.body()), list(body), DOCUMENT)
    for child in list(body):
        body.remove(child)
    for child in merged:
        body.append(child)
    _stamped(
        new,
        {
            "form": form,
            "since": hashlib.sha256(before.read_bytes()).hexdigest(),
            "round": round_number,
        },
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
        tracked = Path(scratch) / "tracked.docx"
        new.write(tracked)
        check(tracked, before, after)
        made = (
            highlighted(tracked, Path(scratch) / "highlighted.docx")
            if form == "highlighted"
            else tracked
        )
        os.replace(made, target)
    counts = Counter({k: v for k, v in writer.counts.items() if v})
    return Made(target, form, dict(counts))
