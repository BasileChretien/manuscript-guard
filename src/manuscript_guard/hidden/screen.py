"""A file that came from someone else, read for what it hides before an agent reads it
(`screen`): a co-author's Word file, a reviewer's letter, a comment file, a stored
literature page.

Each kind is read by the reader of its kind, and what is found is a warning: the file is
read on, by the command or by the agent, with that in mind (D7.2, Basile, 2026-11-06).

- a Word document (`.docx`, `.docm`, `.dotx`, `.dotm`) by `hidden.word`;
- a page of HTML, and a Markdown file with the HTML it may hold, by `hidden.html`;
- a text file (`.txt`, `.csv`, `.json`, `.yaml`, `.xml`, a `.bib` and its kin, a `.tex`) and
  a PDF's text, read as `literature.sources` reads a stored PDF, for zero-width characters
  inside words and words to a model (`hidden.words`): what a PDF hides by its colour, its
  size or its drawing is not read, only the words it holds;
- an e-mail (`.eml`): its subject, and each part of its text and its HTML; an attachment is
  named, not read, to be saved and screened by itself.

A text is read in the encoding its byte-order mark names, UTF-8 where it has none, and a
JSON file's `\\u` escapes and an XML file's character references are read as what they
stand for (the security review of #576). Each file is read within limits, said where it
passes one: 4 MB of text or HTML, of a PDF's text and of each part of an e-mail; an e-mail
of 16 MB and 500 parts; and 500 places said of one file.
"""

from __future__ import annotations

import base64
import codecs
import email
import html
import quopri
import re
import shutil
import subprocess
import threading
from bisect import bisect_right
from dataclasses import replace
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
#: The most text or HTML read from one file, or from one part of an e-mail or a PDF:
#: reading a text for its words costs some fifty bytes of memory a character.
MAX_TEXT_BYTES = 4 * 1024 * 1024
#: The most of an e-mail read, its attachments among it, and the most of its parts.
MAX_MAIL_BYTES = 16 * 1024 * 1024
MAX_PARTS = 500
#: The most of an e-mail's subject read: its encoded words cost the parser more than their
#: length (the security review of #576).
SUBJECT_AT_MOST = 64 * 1024
#: The most places said of one file; the rest are counted.
MAX_FOUND = 500
#: How long `pdftotext` is given for a PDF's text, in seconds.
PDF_SECONDS = 60
_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
#: An encoded word of a header (RFC 2047): its charset, its encoding and its text.
_ENCODED_WORD = re.compile(r"=\?([^?\s]{1,40})\?([bBqQ])\?([^?\s]*)\?=")
#: Encoded words one after another: the spaces between them are no part of the text
#: (RFC 2047, 6.2).
_ENCODED_RUN = re.compile(rf"(?:{_ENCODED_WORD.pattern})(?:[ \t\r\n]+(?:{_ENCODED_WORD.pattern}))*")
_BOMS = ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
         (codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
         (codecs.BOM_UTF16_BE, "utf-16"))  # fmt: skip

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
    """Each part `reading` did not read, a line for each, then a line for each place it
    found: the parts not read first, so that a command that cuts the lines keeps them
    (the review of 1d5327d)."""
    more = [f"and {reading.more} more places, not said"] if reading.more else []
    unread = [f"not read: {printable(why)}" for why in reading.unread]
    return unread + [described(item) for item in reading.found] + more


def screen(path: Path) -> Reading:
    """What `path` holds that its reader does not see (see the module's docstring), as far
    as `MAX_FOUND` places. Raises `UnsafeDocument` where it cannot be read, a kind of file no
    reader reads among them."""
    reading = _read(path)
    if len(reading.found) <= MAX_FOUND:
        return reading
    # Words to a model are kept first, then what is hidden, then zero-width characters,
    # each in the file's order: a cut by the file's order alone let decoys push words to
    # a model out (the review of 1d5327d).
    kept = sorted(range(len(reading.found)), key=lambda at: _first(reading.found[at]))
    return replace(reading, found=tuple(reading.found[at] for at in sorted(kept[:MAX_FOUND])),
                   more=len(reading.found) - MAX_FOUND)  # fmt: skip


def _first(item: Hidden) -> int:
    if item.kind == TO_A_MODEL or item.model:
        return 0
    return 2 if item.kind == ZERO_WIDTH else 1


def _read(path: Path) -> Reading:
    suffix = path.suffix.casefold()
    if suffix in WORD:
        return read_hidden(path)
    if suffix in PDF:
        return _pdf(path)
    data = _bytes(path, MAX_MAIL_BYTES if suffix in MAIL else MAX_TEXT_BYTES)
    if suffix in MAIL:
        return _mail(path, data)
    text = _decoded(data)
    if suffix in HTML or suffix in MARKDOWN:
        return Reading(path, tuple(read_page(text, path.name,
                                             "the page" if suffix in HTML else "the text")))
    if suffix in TEXT:
        if suffix == ".json":
            text = _JSON_ESCAPE.sub(lambda found: chr(int(found.group(1), 16)), text)
        elif suffix == ".xml":
            text = html.unescape(text)
        return Reading(path, tuple(text_items(text, path.name, "the text")))
    raise UnsafeDocument(
        f"{path.name}: no reader of hidden text for {suffix}; save it as a Word document, a "
        "PDF, HTML or text and screen that"
    )


def _decoded(data: bytes) -> str:
    """Text in the encoding its byte-order mark names, UTF-8 where it has none."""
    for mark, encoding in _BOMS:
        if data.startswith(mark):
            return data.decode(encoding, errors="replace")
    return data.decode("utf-8", errors="replace")


def _bytes(path: Path, limit: int) -> bytes:
    try:
        size = path.stat().st_size
        if size > limit:
            raise UnsafeDocument(f"{path.name} is {_size(size)}, past the {_size(limit)} read "
                                 "of one file")  # fmt: skip
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
    """A PDF's text, in reading order, as far as `MAX_TEXT_BYTES` of it (round 1 of
    #576: a small PDF can give text of any length)."""
    _bytes(path, MAX_ARCHIVE_BYTES)  # its size and its kind, before a reader is run on it
    text, cut = _pdf_text(path)
    if not text.strip():
        # A page scanned as a picture gives no text, and a damaged one none either: neither
        # is a PDF that hides nothing (round 2 of #576).
        raise UnsafeDocument(f"{path.name} gives no text to read (a scanned page, or a "
                             "damaged or encrypted file)")  # fmt: skip
    unread = (f"the PDF's text past the {_size(MAX_TEXT_BYTES)} read",) if cut else ()
    return Reading(path, tuple(text_items(text, path.name, "the PDF's text")), unread)


def _size(count: int) -> str:
    return f"{count // 1024 // 1024} MB" if count >= 1024 * 1024 else f"{count} bytes"


def _pdf_text(path: Path) -> tuple[str, bool]:
    """The PDF's text and whether it was cut: from `pdftotext` read as far as the
    limit and stopped there, in `PDF_SECONDS`; else as `literature.sources` reads one.
    The path is given whole, so that a file named like an option is read as a file."""
    exe = shutil.which("pdftotext")
    if exe is None:
        return _pdf_text_without(path)
    stopped = threading.Event()
    try:
        with subprocess.Popen([exe, "-enc", "UTF-8", str(path.resolve()), "-"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as running:
            timer = threading.Timer(PDF_SECONDS, lambda: (stopped.set(), running.kill()))
            timer.start()
            try:
                data = running.stdout.read(MAX_TEXT_BYTES + 1) if running.stdout else b""
                cut = len(data) > MAX_TEXT_BYTES
                if cut:
                    running.kill()
                running.wait()
            finally:
                timer.cancel()
    except OSError as exc:
        raise UnsafeDocument(f"{path.name}: pdftotext could not be run ({exc})") from exc
    if stopped.is_set():
        raise UnsafeDocument(f"{path.name}: pdftotext took more than {PDF_SECONDS} "
                             "seconds")  # fmt: skip
    if not cut and running.returncode != 0:
        # Refused by pdftotext: read as a stored source is, pypdf's way (round 2 of #576).
        return _pdf_text_without(path)
    return data[:MAX_TEXT_BYTES].decode("utf-8", errors="replace"), cut


def _pdf_text_without(path: Path) -> tuple[str, bool]:
    from manuscript_guard.literature.sources import UnreadableSource, read_in_reading_order

    try:
        text = read_in_reading_order(path)
    except UnreadableSource as exc:
        raise UnsafeDocument(str(exc)) from exc
    return text[:MAX_TEXT_BYTES], len(text) > MAX_TEXT_BYTES


def _mail(path: Path, data: bytes) -> Reading:
    """An e-mail's subject, and each part of its text and HTML, each as far as
    `MAX_TEXT_BYTES`; an attachment named. Read by the parser's first policy, which keeps a
    header as text: the default one makes an object of each, at a cost growing as the
    square of a subject's encoded words (the security review of #576)."""
    try:
        return _parts_of_mail(path, email.message_from_bytes(data))
    except RecursionError as exc:
        # Parts nested past what the parser follows (round 1 of #576).
        raise UnsafeDocument(f"{path.name}: its parts are nested too deep to read") from exc
    except MemoryError as exc:
        raise UnsafeDocument(f"{path.name}: too large to read") from exc


def _subject(message, unread: list[str]) -> str:
    # The header as written, its bytes past ASCII read as UTF-8: the first policy's `get`
    # gives them as characters it could not read (the review of 1d5327d).
    raw = next((str(value) for name, value in message.raw_items()
                if name.casefold() == "subject"), "")  # fmt: skip
    if len(raw) > SUBJECT_AT_MOST:
        unread.append(f"the subject: past the {_size(SUBJECT_AT_MOST)} of it read")
        raw = raw[:SUBJECT_AT_MOST]
    raw = raw.encode("utf-8", "surrogateescape").decode("utf-8", errors="replace")
    return _ENCODED_RUN.sub(_run, raw)


def _run(found: re.Match[str]) -> str:
    """Encoded words one after another, read as one text."""
    return "".join(_word(word) for word in _ENCODED_WORD.finditer(found.group(0)))


def _word(found: re.Match[str]) -> str:
    """An encoded word read as its text, or left as written where it cannot be: by a
    pattern that reads the subject in time linear in its length, where the library's own
    reader took time growing as the square of its words (the security review of #576)."""
    charset, encoding, data = found.groups()
    try:
        if encoding in "bB":
            written = base64.b64decode(data + "=" * (-len(data) % 4))
        else:
            written = quopri.decodestring(data.encode("ascii", "replace"), header=True)
        # RFC 2231 may name a language after the charset, `UTF-8*en`.
        return written.decode(codecs.lookup(charset.split("*")[0]).name, errors="replace")
    except (LookupError, ValueError):
        return found.group(0)


def _content(part, number: int, unread: list[str]) -> str | None:
    """The text of one part of an e-mail, decoded, or None where it is not read."""
    payload = part.get_payload(decode=True) or b""
    if len(payload) > MAX_TEXT_BYTES:
        unread.append(f"part {number} of the message: past the {_size(MAX_TEXT_BYTES)} of "
                      "text read")  # fmt: skip
        return None
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(codecs.lookup(charset).name, errors="replace")
    except (LookupError, UnicodeError, ValueError) as exc:
        unread.append(f"part {number} of the message: its text cannot be read ({exc})")
        return None


def _parts_of_mail(path: Path, message) -> Reading:
    unread: list[str] = []
    found = text_items(_subject(message, unread), path.name, "the subject")
    for number, part in enumerate(message.walk(), start=1):
        if number > MAX_PARTS:
            unread.append(f"the message holds more than {MAX_PARTS} parts; the rest are not "
                          "read")  # fmt: skip
            break
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
        content = _content(part, number, unread)
        if content is None:
            continue
        if kind == "text/html":
            found += read_page(content, path.name, f"the message's HTML, part {number}")
        else:
            found += text_items(content, path.name, f"the message, part {number}")
    return Reading(path, tuple(found), tuple(unread))
