"""The entries of a reference list typed in APA's author-year form, read where every field of
one is read exactly, and the others said with the reason.

pandoc writes a Word paper's entry as one Markdown paragraph on one line, with its italics as
`*...*` and an en dash as `--`. Two shapes are read, APA 7's for a journal article and for a
book, and each part of an entry must be where the shape puts it:

- an article: `Family, I. I., Other, I., & Last, I. (2020). Title. *Journal*, *12*(3),
  45--67. https://doi.org/10.1000/xyz`, the journal and its volume in italics, together
  (`*Journal, 12*`) or apart; the issue, and the DOI or address, may be absent;
- a book: `Family, I. (2020). *Title*. Publisher.`, with a DOI or address after it or not.

Anything else is not read: an entry with no author in APA's form (a group, a name in full,
"Jr.", twenty-one authors and an ellipsis), a year that is no year ("n.d.", "in press",
"2020, March 3"), a chapter, an edition, a description in brackets, italics inside a title,
and a field holding a character a `.bib` value does not carry as typed (a quotation mark, a
brace, a backslash, a tilde, an ellipsis). A title ending in an abbreviation's stop, "in
the U.S.", is not read either: the stop that ends a title in APA cannot be told from it. One
of a single word, "Dr." or "Inc.", is not seen, and loses its stop (DESIGN.md, Known gaps).
Nothing is guessed, so an entry not read is not written, and its citations stay typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: A year as an entry gives it, with the letter of a second work by the same authors.
YEAR = r"(?:1[89]|20)\d\d[a-z]?"
_HEAD = re.compile(rf"(?P<authors>.+?) \((?P<year>{YEAR})\)\. (?P<rest>.+)")
#: An article's part after the year: its title, the journal and its volume in italics,
#: together or apart, the issue, the pages and what links to it.
_ARTICLE = re.compile(
    r"(?P<title>[^*]+?[.?!]) "
    r"\*(?P<journal>[^*]+?)(?:\*, \*(?P<volume>\d+)|, (?P<together>\d+))\*"
    r"(?:\((?P<number>[^()*]+)\))?, (?P<pages>[A-Za-z]?\d+(?:--[A-Za-z]?\d+)?)\."
    r"(?: (?P<link>\S+))?"
)
#: A book's: its title in italics, the publisher and what links to it. The publisher holds
#: no bracket and no stop before a space: "(2nd ed.). Big Press" and "Big Press. Retrieved
#: from" are no publisher's name (round 1 of #638).
_BOOK = re.compile(
    r"\*(?P<title>[^*]+)\*(?P<stop>\.?) (?P<publisher>(?:[^*()\[\].]|\.(?! ))+?)\."
    r"(?: (?P<link>\S+))?"
)
#: Initials as APA writes them: "J.", "J. A.", "J.-P.", "Ch.".
_INITIALS = re.compile(r"[A-ZÀ-ÖØ-Þ][a-z]?\.(?:[ -][A-ZÀ-ÖØ-Þ][a-z]?\.)*")
#: A family name: letters, and spaces, hyphens or apostrophes between them.
_FAMILY = re.compile(r"[^\W\d_]+(?:[ '’-][^\W\d_]+)*")
_DOI = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|doi:)(?P<doi>10\.\d{4,9}/\S+)")
_ADDRESS = re.compile(r"https?://\S+")
#: A Markdown escape, `\_`, which pandoc prints as the character.
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
#: Markup left in a field, which a `.bib` value would not print as Markdown does.
_MARKUP = re.compile(r"(?<!\\)[*_\[\]<>`^~]")
#: What a `.bib` value does not carry as typed, once the escapes are read.
_UNCARRIED = re.compile(r'["\\{}~^]|\.\.\.|…')
#: A field's last word that is an abbreviation with stops, "U.S.", "e.g." or "Ph.D.": its
#: stop is the one APA ends the field with.
_ABBREVIATED = re.compile(r"(?:^|\s)(?:\w+\.){2,}$")


@dataclass(frozen=True)
class Entry:
    """A reference list's entry, read: where it is, its authors' family names and initials,
    its year as typed (`2020a`), its kind, `article` or `book`, and its other fields as the
    entry gives them, escapes read, in the order a `.bib` writes them."""

    line: int
    families: tuple[str, ...]
    initials: tuple[str, ...]
    year: str
    kind: str
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Unread:
    """An entry of the list not read, with the reason."""

    line: int
    text: str
    why: str


def read_entry(text: str, line: int) -> Entry | Unread:
    """The entry typed as `text`, on `line`, read, or why it is not."""
    head = _HEAD.fullmatch(text.strip())
    if head is None:
        return Unread(line, text, "no year in APA's form, \"(2020).\", follows its authors")
    people = _authors(head.group("authors"))
    if isinstance(people, str):
        return Unread(line, text, people)
    rest = head.group("rest")
    article, book = _ARTICLE.fullmatch(rest), _BOOK.fullmatch(rest)
    if article is not None and not _ABBREVIATED.search(article.group("title")):
        title = article.group("title")
        fields = [("title", title[:-1] if title.endswith(".") else title),
                  ("journal", article.group("journal")),
                  ("volume", article.group("volume") or article.group("together")),
                  ("number", article.group("number")), ("pages", article.group("pages"))]
        kind, link = "article", article.group("link")
    elif (
        book is not None
        # APA puts no stop after a title that ends in "?" or "!", and one after any other.
        and bool(book.group("stop")) != (book.group("title")[-1:] in ("?", "!"))
        and not _ABBREVIATED.search(f"{book.group('publisher')}.")
    ):
        fields = [("title", book.group("title")), ("publisher", book.group("publisher"))]
        kind, link = "book", book.group("link")
    else:
        return Unread(line, text, "its shape is neither an article's, Title. *Journal*, "
                      "*volume*(issue), pages., nor a book's, *Title*. Publisher.")  # fmt: skip
    if link is not None:
        linked = _link(link)
        if linked is None:
            return Unread(line, text, f"what follows its last stop, {link!r}, is no DOI or "
                          "web address alone")  # fmt: skip
        fields.append(linked)
    read: list[tuple[str, str]] = []
    for name, value in fields:
        if value is None:
            continue
        if name not in ("doi", "url") and _MARKUP.search(value):
            return Unread(line, text, f"its {name} holds formatting this does not read")
        value = _ESCAPE.sub(r"\1", value)
        if name not in ("doi", "url") and _UNCARRIED.search(value):
            return Unread(line, text, f"its {name} holds a character a .bib value does not "
                          "carry as typed")  # fmt: skip
        read.append((name, value))
    families, initials = people
    return Entry(line, families, initials, head.group("year"), kind, tuple(read))


def _authors(written: str) -> tuple[tuple[str, ...], tuple[str, ...]] | str:
    """The family names and initials of an APA author list, "Smith, J. A., Lee, K., & Moe,
    P.", or why it is none: each family name followed by its initials, and "&" before the
    last of two or more."""
    parts = written.split(", ")
    why = "its authors are not each a family name and initials, \"Smith, J. A.\", with \"&\" " \
          "before the last"
    if len(parts) % 2:
        return why
    families = parts[0::2]
    initials = parts[1::2]
    if len(families) > 1:
        if not families[-1].startswith("& "):
            return why
        families[-1] = families[-1][2:]
    for family, given in zip(families, initials, strict=True):
        if not _FAMILY.fullmatch(family) or not _INITIALS.fullmatch(given):
            return why
        if not any(letter.isupper() for letter in family):
            return why
    return tuple(families), tuple(initials)


def _link(written: str) -> tuple[str, str] | None:
    """The DOI or web address an entry ends with, as `doi` or `url`: bare, in angle brackets,
    or as a link whose words are its address."""
    address = written
    if address.startswith("<") and address.endswith(">"):
        address = address[1:-1]
    elif found := re.fullmatch(r"\[(?P<words>[^\[\]]+)\]\((?P<target>[^()\s]+)\)", address):
        if found.group("words") != found.group("target"):
            return None
        address = found.group("target")
    address = _ESCAPE.sub(r"\1", address)
    # A stop after it is no part of APA's form, and may be the address's own.
    if address[-1:] in ".,;":
        return None
    doi = _DOI.fullmatch(address)
    if doi is not None:
        return "doi", doi.group("doi")
    return ("url", address) if _ADDRESS.fullmatch(address) else None
