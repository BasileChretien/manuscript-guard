"""The prose of the companion page, written as HTML by pandoc: each piece of the manuscript,
the plan or a record the page shows, turned into a fragment of HTML with nothing in it that
runs, loads or points anywhere.

Every piece goes to pandoc in one document, each after a paragraph that marks where it
starts, and comes back as one HTML document cut at those marks: one pandoc for the reading
and one for the writing, however many pieces. A piece that swallows the marks after it, an
unclosed code fence, is written again on its own.

What the page shows is what pandoc's Markdown reader reads in it, less what would make the
page do anything: raw HTML, TeX and attributes are read as text (the reader's extensions for
them are off), a picture is its description, a link that is not to the web or an address is
its words, and a footnote is its text in brackets where it stands. Pandoc's user data
directory is not read: the bytes depend on pandoc's version, which MANIFEST.yaml names, and on
nothing else of the computer.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile

#: The reader's extensions that are off: anything that would pass HTML or TeX through, give
#: an element an attribute, read a block of metadata, or number a heading.
READER = (
    "markdown"
    "-raw_html-raw_attribute-raw_tex-yaml_metadata_block-pandoc_title_block"
    "-auto_identifiers-link_attributes-header_attributes-fenced_code_attributes"
    "-inline_code_attributes-bracketed_spans-fenced_divs-native_divs-native_spans"
)
PANDOC_SECONDS = 120
#: What starts a piece in the document pandoc reads: a word no manuscript writes.
MARK = "MGCOMPANIONPIECE{:05d}"
_MARK = re.compile(r"<p>MGCOMPANIONPIECE(\d{5})</p>\n?")
#: The links a page may follow: to the web, and to an address.
_SAFE_LINK = re.compile(r"(?i)^(?:https?:|mailto:)")
#: How much deeper a heading of a piece is than the page's own headings: `#` is an h3.
SHIFT = 2


class ProseError(Exception):
    """Pandoc could not write the prose."""


def pandoc_version() -> str | None:
    """`pandoc 3.9.0.2`, the first line pandoc prints of itself, or None where it is not on
    PATH."""
    found = shutil.which("pandoc")
    if found is None:
        return None
    done = _run([found, "--version"], "")
    first = done.splitlines()[0].strip() if done.strip() else "pandoc"
    name, _, version = first.partition(" ")
    return f"pandoc {version.strip()}" if name.lower().startswith("pandoc") else first


def _run(command: list[str], given: str) -> str:
    try:
        done = subprocess.run(command, input=given, capture_output=True, encoding="utf-8",
                              timeout=PANDOC_SECONDS, check=False)  # fmt: skip
    except subprocess.TimeoutExpired:
        raise ProseError(f"pandoc gave no answer within {PANDOC_SECONDS} s") from None
    except OSError as exc:
        raise ProseError(f"pandoc could not be run: {exc}") from None
    if done.returncode != 0:
        raise ProseError(f"pandoc could not write the companion's prose:\n{done.stderr.strip()}")
    return done.stdout


def _pandoc(*args: str, given: str) -> str:
    found = shutil.which("pandoc")
    if found is None:
        raise ProseError("pandoc is not on PATH")
    with tempfile.TemporaryDirectory(prefix="mg-companion-") as empty:
        # An empty data directory: what the user's own holds is not read.
        return _run([found, f"--data-dir={empty}", *args], given)


def _inlines_of(blocks: list) -> list:
    """The inlines of a footnote's blocks, one space between blocks."""
    out: list = []
    for block in blocks:
        if isinstance(block, dict) and block.get("t") in ("Para", "Plain"):
            if out:
                out.append({"t": "Space"})
            out += block["c"]
    return out


def _safe(node: object) -> object:
    """A node of pandoc's tree, with nothing in it that loads, runs or leads anywhere but the
    web or an address."""
    if isinstance(node, list):
        return [_safe(item) for item in node]
    if not isinstance(node, dict):
        return node
    kind, content = node.get("t"), node.get("c")
    if kind == "Image":
        return {"t": "Span", "c": [["", [], []], _safe(content[1])]}
    if kind == "Link":
        if _SAFE_LINK.match(str(content[2][0])):
            return {"t": "Link", "c": [["", [], []], _safe(content[1]), content[2]]}
        return {"t": "Span", "c": [["", [], []], _safe(content[1])]}
    if kind == "Note":
        inner = _safe(_inlines_of(content))
        return {"t": "Span", "c": [["", [], []],
                                   [{"t": "Str", "c": "["}, *inner, {"t": "Str", "c": "]"}]]}
    if kind in ("RawInline", "RawBlock"):
        return {"t": "Str", "c": ""} if kind == "RawInline" else {"t": "Plain", "c": []}
    if kind == "Header":
        return {"t": "Header", "c": [min(content[0] + SHIFT, 6), *_safe(content[1:])]}
    return {key: _safe(value) for key, value in node.items()}


def _split(blocks: list, count: int) -> list[list] | None:
    """The blocks of each piece, cut at the marks; None where a piece swallowed a mark."""
    pieces: list[list] = []
    for block in blocks:
        text = block.get("c") if block.get("t") == "Para" else None
        if (isinstance(text, list) and len(text) == 1 and text[0].get("t") == "Str"
                and text[0]["c"] == MARK.format(len(pieces))):  # fmt: skip
            pieces.append([])
        elif pieces:
            pieces[-1].append(block)
        else:
            return None
    return pieces if len(pieces) == count else None


def _document(api: list, pieces: list[list]) -> dict:
    blocks: list = []
    for number, piece in enumerate(pieces):
        blocks.append({"t": "Para", "c": [{"t": "Str", "c": MARK.format(number)}]})
        blocks += piece
    return {"pandoc-api-version": api, "meta": {}, "blocks": blocks}


def _read(texts: list[str]) -> tuple[list, list[list]]:
    """Each text as pandoc's blocks, read in one document where none swallows a mark."""
    given = "".join(f"{MARK.format(n)}\n\n{text}\n\n" for n, text in enumerate(texts))
    document = json.loads(_pandoc("-f", READER, "-t", "json", given=given))
    pieces = _split(document["blocks"], len(texts))
    if pieces is not None:
        return document["pandoc-api-version"], pieces
    api, pieces = document["pandoc-api-version"], []
    for text in texts:
        one = json.loads(_pandoc("-f", READER, "-t", "json", given=text))
        pieces.append(one["blocks"])
    return api, pieces


def html_fragments(texts: list[str]) -> list[str]:
    """Each Markdown text as a fragment of HTML, in order: one pandoc to read them and one to
    write them."""
    if not texts:
        return []
    api, pieces = _read(texts)
    written = _pandoc("-f", "json", "-t", "html5", "--wrap=none",
                      given=json.dumps(_document(api, _safe(pieces)), ensure_ascii=False))
    found = list(_MARK.finditer(written))
    if [int(match[1]) for match in found] != list(range(len(texts))):
        raise ProseError("pandoc wrote the companion's prose in another order than it read it")
    ends = [match.start() for match in found[1:]] + [len(written)]
    return [written[match.end():end].strip("\n") for match, end in zip(found, ends, strict=True)]


def inline(fragment: str) -> str:
    """A fragment of one paragraph without the paragraph: a sentence in a list or a cell."""
    found = re.fullmatch(r"<p>(.*)</p>", fragment, re.DOTALL)
    return found[1] if found and "<p>" not in found[1] else fragment


__all__ = ["READER", "ProseError", "html_fragments", "inline", "pandoc_version"]
