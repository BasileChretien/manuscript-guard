"""The fields of a `.bib` file, as the file writes them: one small reader, everywhere.

The co-author items (`checking/produce.py`) and G7's identifiers read a bibliography through
this. DESIGN.md, Known gaps, "The bibliography is read as fields, not as the format", says
why it is not pandoc's reading and what it leaves as written.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Where a field named `type` is kept: the entry's own type is under `type`, which every
#: reader of this file looks it up by.
TYPE_FIELD = "type_field"


def read_entries(path: Path) -> dict[str, dict[str, str]]:
    """Every entry of a `.bib` file: the fields as they are written.

    A small reader rather than a dependency: a .bib entry is `@type{key, field = {value},}`, and
    what a co-author checks is the fields as they are written. Nested braces are counted, so a
    title holding `{SANRA}` comes out whole.

    The entry is cut at the commas that are **outside** every brace and quote, and only then is
    each piece split at its first `=`. Looking for `name =` anywhere instead found one inside a
    value and made a field of it: on the bibliography this was tried against, four entries in
    fifty-eight gained a field no line of the file declares — `tstat` out of a URL's query
    string, `n` out of "(n = 866)" in an abstract, `given` and `family` out of a biblatex
    extended name — and a URL carrying `&title=` overwrote the entry's real title, which a
    co-author would have been shown as the thing to check.

    What it does not do: decode a TeX accent, expand a `@string` macro, join a `#`
    concatenation, or read a biblatex extended name into its parts. A co-author sees each as the
    file writes it, `M{\\"u}ller` included; DESIGN.md's Known gaps carries that.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    records: dict[str, dict[str, str]] = {}
    # Anchored at a line start, so an `@` inside a value is not the start of an entry, and
    # `@comment` is skipped: both were entries of their own before.
    for start in re.finditer(r"^@(\w+)\s*\{\s*([^,\s]+)\s*,", text, re.MULTILINE):
        kind, key = start.group(1), start.group(2)
        if kind.lower() in {"comment", "preamble", "string"}:
            continue
        depth, index = 1, start.end()
        while index < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            index += 1
        fields: dict[str, str] = {"type": kind}
        for piece in _pieces(text[start.end() : index - 1]):
            name, sign, value = piece.partition("=")
            name = name.strip().lower()
            if not sign or not name.isidentifier():
                continue
            # A field named `type`, the kind of a thesis, a chapter or a dataset written as
            # `@misc`, took the place of the entry's own type (round 2 of #261), and is kept
            # beside it, for the readers that want it (round 1 of #345: it was dropped).
            if name == "type":
                name = TYPE_FIELD
            value = value.strip()
            if (value[:1], value[-1:]) in {("{", "}"), ('"', '"')}:
                value = value[1:-1]
            fields[name] = " ".join(value.replace("{", "").replace("}", "").split())
        records[key] = fields
    return records


def _pieces(body: str) -> list[str]:
    """One .bib entry's body, cut at the commas outside every brace and quote."""
    pieces: list[str] = []
    current: list[str] = []
    depth = 0
    quoted = False
    for char in body:
        if char == '"' and depth == 0:
            quoted = not quoted
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0 and not quoted:
            pieces.append("".join(current))
            current = []
            continue
        current.append(char)
    pieces.append("".join(current))
    return pieces
