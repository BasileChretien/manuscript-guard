"""A file that came from someone else, read for what it hides before an agent reads it
(`screen`): a co-author's Word file, a reviewer's letter, a comment file, a stored
literature page.

Each kind is read by the reader of its kind, and what is found is a warning: the file is
read on, by the command or by the agent, with that in mind (D7.2, Basile, 2026-11-06).

- a Word document (`.docx`, `.docm`, `.dotx`, `.dotm`) by `hidden.word`;
- a page of HTML, and a Markdown file with the HTML it may hold, by `hidden.html`;
- a text file (`.txt`, `.csv`, `.json`, `.yaml`, a `.bib` and its kin, a `.tex`) and a
  PDF's text, read as `literature.sources` reads a stored PDF, for zero-width characters
  inside words and words to a model (`hidden.words`): what a PDF hides by its colour, its
  size or its drawing is not read, only the words it holds;
- an e-mail (`.eml`): its subject, and each part of its text and its HTML; an attachment is
  named, not read, to be saved and screened by itself.

A file is read whole, within the limits the untrusted readers keep (`safexml`): 8 MB of
text or HTML, and an e-mail or a Word file within the limit of an archive.
"""

from __future__ import annotations

from bisect import bisect_right
from email import policy
from email.parser import BytesParser
from pathlib import Path

from manuscript_guard.hidden.html import read_page
from manuscript_guard.hidden.word import (
    BACKGROUND,
    HIDDEN,
    TINY,
    TO_A_MODEL,
    ZERO_WIDTH,
    Hidden,
    Reading,
    quoted,
    read_hidden,
)
from manuscript_guard.hidden.words import printable, to_a_model_in, zero_width_in
from manuscript_guard.safexml import (
    MAX_ARCHIVE_BYTES,
    UnsafeDocument,
    compound_file_said,
    is_compound_file,
)

WORD = frozenset({".docx", ".docm", ".dotx", ".dotm"})
HTML = frozenset({".html", ".htm", ".xhtml"})
MARKDOWN = frozenset({".md", ".markdown", ".qmd", ".rmd"})
PDF = frozenset({".pdf"})
MAIL = frozenset({".eml"})
TEXT = frozenset({"", ".txt", ".text", ".csv", ".tsv", ".json", ".yaml", ".yml", ".xml",
                  ".bib", ".nbib", ".ris", ".rst", ".tex", ".log"})  # fmt: skip
#: The most text or HTML read from one file: reading a text for its words costs some fifty
#: bytes of memory a character.
MAX_TEXT_BYTES = 8 * 1024 * 1024

#: How each kind is said, around how the place is kept from sight.
_WHAT = {
    HIDDEN: "{how}",
    BACKGROUND: "text too close in colour to what is behind it to be read, {how}",
    TINY: "text too small to read, {how}",
    ZERO_WIDTH: "zero-width characters, {how}",
}


def described(item: Hidden) -> str:
    """One place, as `build`, `screen` and the commands that read a file say it: where, what
    keeps it from sight, and its words, escaped where they hold a character that does not
    print."""
    if item.kind == TO_A_MODEL:
        return printable(f"{item.where}: {item.how}: {item.text!r}")
    model = "; its words are addressed to a model" if item.model else ""
    what = _WHAT.get(item.kind, "{how}").format(how=item.how)
    return printable(f"{item.where}: {what}: {item.text!r}{model}")


def said(reading: Reading) -> list[str]:
    """What `reading` found, a line for each place, then each part not read."""
    return [described(item) for item in reading.found] + [
        f"not read: {printable(why)}" for why in reading.unread
    ]


def screen(path: Path) -> Reading:
    """What `path` holds that its reader does not see (see the module's docstring). Raises
    `UnsafeDocument` where it cannot be read, a kind of file no reader reads among them."""
    suffix = path.suffix.casefold()
    if suffix in WORD:
        return read_hidden(path)
    if suffix in PDF:
        return _pdf(path)
    data = _bytes(path, MAX_ARCHIVE_BYTES if suffix in MAIL else MAX_TEXT_BYTES)
    if suffix in MAIL:
        return _mail(path, data)
    text = data.decode("utf-8", errors="replace")
    if suffix in HTML or suffix in MARKDOWN:
        return Reading(path, tuple(read_page(text, path.name,
                                             "the page" if suffix in HTML else "the text")))
    if suffix in TEXT:
        return Reading(path, tuple(text_items(text, path.name, "the text")))
    raise UnsafeDocument(
        f"{path.name}: no reader of hidden text for {suffix}; save it as a Word document, a "
        "PDF, HTML or text and screen that"
    )


def _bytes(path: Path, limit: int) -> bytes:
    try:
        size = path.stat().st_size
        if size > limit:
            raise UnsafeDocument(f"{path.name} is {size // 1024 // 1024} MB, past the "
                                 f"{limit // 1024 // 1024} MB read of one file")  # fmt: skip
        with path.open("rb") as file:
            data = file.read(limit + 1)
    except OSError as exc:
        raise UnsafeDocument(f"{path.name}: cannot be read ({exc})") from exc
    if is_compound_file(data):
        raise UnsafeDocument(compound_file_said(path.name))
    return data


def text_items(text: str, part: str, label: str) -> list[Hidden]:
    """Zero-width characters inside words, and words to a model, in a text read whole,
    each said at its line."""
    breaks = [at for at, character in enumerate(text) if character == "\n"]

    def where(offset: int) -> str:
        return f"{label}, line {bisect_right(breaks, offset - 1) + 1}"

    found = [Hidden(ZERO_WIDTH, where(spot.start), quoted(spot.said), spot.why, part)
             for spot in zero_width_in(text)]  # fmt: skip
    return found + [
        Hidden(TO_A_MODEL, where(spot.start), quoted(spot.said), spot.why, part, printed=True,
               model=spot.rule)
        for spot in to_a_model_in(text)
    ]  # fmt: skip


def _pdf(path: Path) -> Reading:
    from manuscript_guard.literature.sources import UnreadableSource, read_in_reading_order

    _bytes(path, MAX_ARCHIVE_BYTES)  # its size and its kind, before a reader is run on it
    try:
        text = read_in_reading_order(path)
    except UnreadableSource as exc:
        raise UnsafeDocument(str(exc)) from exc
    return Reading(path, tuple(text_items(text, path.name, "the PDF's text")))


def _mail(path: Path, data: bytes) -> Reading:
    """An e-mail's subject, and each part of its text and HTML; an attachment named."""
    message = BytesParser(policy=policy.default).parsebytes(data)
    found = text_items(str(message.get("subject", "")), path.name, "the subject")
    unread: list[str] = []
    for number, part in enumerate(message.walk(), start=1):
        if part.is_multipart():
            continue
        name = part.get_filename()
        if name or part.get_content_disposition() == "attachment":
            unread.append(f"an attachment, {name!r}: save it and screen it by itself")
            continue
        kind = part.get_content_type()
        if not kind.startswith("text/"):
            unread.append(f"part {number} of the message, {kind}: no reader of it")
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, ValueError, AssertionError) as exc:
            unread.append(f"part {number} of the message: its text cannot be read ({exc})")
            continue
        if kind == "text/html":
            found += read_page(content, path.name, f"the message's HTML, part {number}")
        else:
            found += text_items(content, path.name, f"the message, part {number}")
    return Reading(path, tuple(found), tuple(unread))
