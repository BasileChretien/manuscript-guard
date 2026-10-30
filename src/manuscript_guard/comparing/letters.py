"""The authors' response letter and the referee's own comments, held to the two versions.

**The letter.** Each quotation of four words or more in it, in straight or curly double
quotation marks, on one line or across a line break, and each block quotation (`>` lines, a
paragraph of them each), is looked for in both versions as G13 looks for a quoted revision
(`gates.revision.as_quoted`), as words of its own, a curly apostrophe read as a straight one.
Two straight marks with a sentence's end between them are no pair, so an inch's mark does not
take a quotation's:

- in v2 and not in v1: new as quoted (a note);
- in both: quoted as revised, but v1 had it (a warning);
- in v1 only: it quotes the first version (a note);
- in neither: it quotes text neither version holds (a warning), or, where the referee's
  comments are given and hold it, it quotes them (a note).

And each "Table N", "Figure N" and "Supplementary Table N" it names, and each title of a
section of either version, as the paper prints it, is a fact: where the letter names it,
and whether it changed. Nothing says whether the change is the one the letter claims.

**The referee's comments** are cut into items: numbered entries where two or more lines
open with a number ("1.", "2)", "Comment 3:"), paragraphs otherwise. An item is matched to v2
only by a passage it quotes, or by a table, a figure or a section it names. A quoted passage
is unchanged in v2, changed (with the sentence v2 has where it stood, where the sentences
line up), gone, or not in v1 either. An item with neither is not matched, and is to be read.
No item is said to be answered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard import claims
from manuscript_guard.auditing.report import Item
from manuscript_guard.comparing.differences import GATE, prose, shown
from manuscript_guard.comparing.versions import Unreadable, Version, label_of
from manuscript_guard.findings import INFO, WARN
from manuscript_guard.gates.quotations import WORDS
from manuscript_guard.gates.revision import as_quoted, quoted_in

LETTER = "Response letter"
COMMENTS = "Your comments"

NEW_AS_QUOTED = "quote-new-in-v2"
NOT_NEW = "quote-in-v1-already"
FIRST_VERSION = "quote-of-v1"
NEITHER = "quote-in-neither"
YOURS = "quote-of-your-comments"
#: What each outcome says, and how loudly.
SAID = {
    NEW_AS_QUOTED: ("new as quoted: v2 has it and v1 did not", INFO),
    NOT_NEW: ("quoted as revised, but v1 had it: both versions hold it", WARN),
    FIRST_VERSION: ("quotes the first version: v1 has it and v2 does not", INFO),
    NEITHER: ("quotes text neither version holds", WARN),
    YOURS: ("quotes your comments, and neither version holds it", INFO),
}

#: A quotation in curly double marks, which open and close, on one line or across a line
#: break; and a straight double mark, which does both and is an inch's mark as well.
_QUOTED = re.compile(
    r"\N{LEFT DOUBLE QUOTATION MARK}([^\N{RIGHT DOUBLE QUOTATION MARK}]+)"
    r"\N{RIGHT DOUBLE QUOTATION MARK}"
)
_STRAIGHT = re.compile('"')
#: What a quotation between two straight marks never holds: a sentence's end and the next
#: one's start, or a blank line. Between an inch's mark and a quotation's opening there is
#: usually one, and the two marks are then no pair: the second opens the quotation.
_NO_QUOTATION = re.compile(r"[.!?]\s+(?=[A-Z])|\n[ \t]*\n")
#: A line of a block quotation, its marks; and the marks a quoted block may be wrapped in.
_BLOCK = re.compile(r"^[ ]{0,3}>(?:[ \t]?>)*[ \t]?")
_WRAPPING = "\"'\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK} "
#: A table, a figure or a supplementary one named anywhere: "Table 2", "Fig. 3", "Table S1",
#: "Supplementary Table 4".
_NAMED = re.compile(
    r"(?<![\w])(?:(?P<supp>supplementary|supplemental|suppl\.)\s+)?"
    r"(?P<kind>tables?|figures?|figs?\.)\s*(?P<s>S)?(?P<n>\d{1,3})(?![\d])",
    re.IGNORECASE,
)
#: A line that opens a numbered comment: "1.", "(2)", "3)", "Comment 4:", "Point 5 -".
_NUMBERED = re.compile(
    r"^[ \t]*(?:\(?(?P<n>\d{1,3})[.)]"
    r"|(?:comment|point|item|issue|query|question|remark)\s*(?P<m>\d{1,3})\b[.:)]?)[ \t]+",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class Quotation:
    #: The line the quotation opens on, from 1.
    line: int
    #: Its words, as a quote of the paper is compared (`as_quoted`).
    quote: str
    block: bool = False


def folded(text: str) -> str:
    return as_quoted(text).replace("\N{RIGHT SINGLE QUOTATION MARK}", "'").replace(
        "\N{LEFT SINGLE QUOTATION MARK}", "'")  # fmt: skip


def _long_enough(quote: str) -> bool:
    return sum(any(c.isalpha() for c in word) for word in quote.split()) >= WORDS


def quotations(text: str, first: int = 1) -> list[Quotation]:
    """Each quotation of four words or more in `text`, and each paragraph of a block
    quotation, in the order they open; `first` is the line `text` starts on."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    found: list[Quotation] = []
    run: list[str] = []
    opened = 0

    def close() -> None:
        said = " ".join(" ".join(run).split()).strip(_WRAPPING)
        if said and _long_enough(said):
            found.append(Quotation(opened + first - 1, folded(said), True))
        run.clear()

    for at, line in enumerate(lines, 1):
        marks = _BLOCK.match(line)
        if marks is None or not line[marks.end() :].strip():
            close()
            if marks is not None:
                lines[at - 1] = " " * len(line)
            continue
        if not run:
            opened = at
        run.append(line[marks.end() :])
        lines[at - 1] = " " * len(line)
    close()
    rest = "\n".join(lines)
    spans = [(match.start(), match.group(1)) for match in _QUOTED.finditer(rest)
             if "\n\n" not in match.group(1)]  # fmt: skip
    spans += _straight(rest)
    for start, said in spans:
        if _long_enough(said):
            line = rest.count("\n", 0, start) + first
            found.append(Quotation(line, folded(said)))
    return sorted(found, key=lambda q: q.line)


def _straight(text: str) -> list[tuple[int, str]]:
    """Each quotation between two straight marks: each mark with the next, unless what is
    between them holds what no quotation does (`_NO_QUOTATION`), when the first is passed
    over, an inch's mark, and the second opens."""
    marks = [found.start() for found in _STRAIGHT.finditer(text)]
    found = []
    at = 0
    while at + 1 < len(marks):
        said = text[marks[at] + 1 : marks[at + 1]]
        if not said.strip() or _NO_QUOTATION.search(said):
            at += 1
            continue
        found.append((marks[at], said))
        at += 2
    return found


def held_in(quote: str, text: str) -> bool:
    """Whether `text` holds `quote` as words of its own, both as `folded` gives them: not
    the start or the end of a longer word or number ("was 2.1" is not in "was 2.15"). A
    LaTeX paper's cross-reference may stand for a number of the quote, as G13 reads one
    (`revision.quoted_in`)."""
    from manuscript_guard.text.latex.printed import POINTER

    at = text.find(quote)
    while at >= 0:
        end = at + len(quote)
        before = text[at - 1] if at else " "
        after, later = text[end : end + 1] or " ", text[end + 1 : end + 2] or " "
        joined_before = quote[:1].isalnum() and before.isalnum()
        joined_after = quote[-1:].isalnum() and (
            after.isalnum() or (quote[-1].isdigit() and after in ".," and later.isdigit()))
        if not joined_before and not joined_after:
            return True
        at = text.find(quote, at + 1)
    return POINTER in text and quoted_in(quote, text)


def outcome(quote: str, old: str, new: str, mine: str | None = None) -> str:
    """Where a quotation stands: `old`, `new` and `mine` as `folded` gives them."""
    in_old, in_new = held_in(quote, old), held_in(quote, new)
    if in_new:
        return NOT_NEW if in_old else NEW_AS_QUOTED
    if in_old:
        return FIRST_VERSION
    return YOURS if mine is not None and held_in(quote, mine) else NEITHER


def held(letter: str, old: str, new: str, mine: str | None = None) -> list[tuple[Quotation, str]]:
    """Each quotation of the letter, with where it stands in the two versions' texts."""
    texts = folded(old), folded(new), None if mine is None else folded(mine)
    return [(quote, outcome(quote.quote, *texts)) for quote in quotations(letter)]


# ---------------------------------------------------------------------- what is named


def named(text: str, titles: list[str], first: int = 1) -> dict[str, list[int]]:
    """Each table, figure and section title `text` names, with the lines it names it on."""
    found: dict[str, list[int]] = {}
    for match in _NAMED.finditer(text):
        label = label_of(match["kind"], bool(match["supp"] or match["s"]), match["n"])
        found.setdefault(label, []).append(text.count("\n", 0, match.start()) + first)
    for title in titles:
        pattern = r"(?<![\w])" + r"\s+".join(map(re.escape, title.split())) + r"(?![\w])"
        for match in re.finditer(pattern, text):
            found.setdefault(title, []).append(text.count("\n", 0, match.start()) + first)
    return found


def _titles(old: Version, new: Version) -> list[str]:
    titles = {heading.title for version in (old, new) for heading in version.sections}
    return sorted((title for title in titles if re.search(r"[^\W\d_]{2}", title)),
                  key=lambda title: (-len(title), title))  # fmt: skip


def _key(title: str) -> str:
    return " ".join(re.findall(r"\w+", title.casefold()))


def status(name: str, old: Version, new: Version) -> str:
    """Whether the table, figure or section `name` changed between the versions."""
    if re.fullmatch(r"(?:Table|Figure) S?\d+", name):
        kind = "tables" if name.startswith("Table") else "figures"
        was = [d for d in getattr(old, kind) if d.label == name]
        now = [d for d in getattr(new, kind) if d.label == name]
        held_by = lambda d: (_key(d.caption), d.rows)  # noqa: E731
        what = "its cells and caption" if kind == "tables" else "its caption"
    else:
        was = [h for h in old.sections if h.title == name]
        now = [h for h in new.sections if h.title == name]
        held_by = lambda h: as_quoted(h.body)  # noqa: E731
        what = "its text"
    if not was and not now:
        return "found in neither version"
    if not now:
        return "in v1 only: gone from v2"
    if not was:
        return "new in v2"
    if [held_by(d) for d in was] == [held_by(d) for d in now]:
        return f"{what} the same in both versions"
    return f"{what} changed"


def _lines(lines: list[int]) -> str:
    unique = list(dict.fromkeys(lines))
    return ("line " if len(unique) == 1 else "lines ") + ", ".join(map(str, unique))


def letter_items(path: Path, letter: str, old: Version, new: Version,
                 mine: str | None = None) -> list[Item]:  # fmt: skip
    """What the response letter quotes and names, each held to the two versions."""
    found = []
    for quote, said in held(letter, old.text, new.text, mine):
        message, severity = SAID[said]
        kind = "block quotation" if quote.block else "quotation"
        found.append(Item(LETTER, GATE, said, f"the {kind}: {message}", severity, False, path,
                          quote.line, shown(quote.quote)))  # fmt: skip
    for name, lines in named(letter, _titles(old, new)).items():
        found.append(Item(LETTER, GATE, "named", f"{name}, named on {_lines(lines)}: "
                          f"{status(name, old, new)}", INFO, False, path, lines[0]))
    return sorted(found, key=lambda item: item.line or 0)


# --------------------------------------------------------------------- the comments


def comment_items_of(text: str) -> list[tuple[str, int, str]]:
    """The referee's comments, each with its name, its first line and its text: numbered
    entries where two or more lines open with a number, paragraphs otherwise."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    starts = list(_NUMBERED.finditer(text))
    found = []
    if len(starts) >= 2:
        if text[: starts[0].start()].strip():
            found.append(("the text before the first numbered comment", 1,
                          text[: starts[0].start()]))  # fmt: skip
        ends = [match.start() for match in starts[1:]] + [len(text)]
        for match, end in zip(starts, ends, strict=True):
            number = match["n"] or match["m"]
            line = text.count("\n", 0, match.start()) + 1
            found.append((f"comment {number}", line, text[match.start() : end]))
        return found
    at, count = 0, 0
    for paragraph in re.split(r"(\n[ \t]*\n)", text):
        if paragraph.strip() and not re.fullmatch(r"\n[ \t]*\n", paragraph):
            count += 1
            line = text.count("\n", 0, at) + 1 + len(paragraph) - len(paragraph.lstrip("\n"))
            found.append((f"paragraph {count}", line, paragraph))
        at += len(paragraph)
    return found


def _sentences(text: str) -> tuple[list, list[tuple[int, int]], str]:
    """A version's sentences, where each stands in the text all of them make, folded."""
    read = claims.sentences(text)
    joined, spans = "", []
    for _start, first, end in claims.sentence_spans(text):
        said = folded(text[first:end])
        spans.append((len(joined), len(joined) + len(said)))
        joined += said + " "
    return read, spans, joined


def now_reads(quote: str, old: Version, new: Version) -> tuple[str, str | None]:
    """What v2 has where a passage of v1 stood: "changed" with v2's sentences there, or with
    None where they cannot be lined up; or "gone" where v2 has no sentence in its place."""
    before_text, after_text = prose(old, apart=False)[0], prose(new, apart=False)[0]
    was, spans, joined = _sentences(before_text)
    now = claims.sentences(after_text)
    at = joined.find(quote)
    if at < 0:
        return "changed", None
    stood = {k for k, (start, end) in enumerate(spans) if start < at + len(quote) and at < end}
    index = {id(sentence): k for k, sentence in enumerate(was)}
    now_spans = claims.sentence_spans(after_text)
    now_index = {id(sentence): k for k, sentence in enumerate(now)}
    for before, after in claims.changed(was, now):
        if stood & {index[id(sentence)] for sentence in before}:
            texts = [after_text[now_spans[now_index[id(s)]][1] : now_spans[now_index[id(s)]][2]]
                     for s in after]  # fmt: skip
            return "changed", shown(" ".join(texts))
    return "gone", None


def comment_items(path: Path, text: str, old: Version, new: Version) -> list[Item]:
    """Each of the referee's comments, matched to v2 by what it quotes or names, or not."""
    olds, news = folded(old.text), folded(new.text)
    titles = _titles(old, new)
    found = []
    for name, line, said in comment_items_of(text):
        anchors = []
        for quote in quotations(said, line):
            if held_in(quote.quote, olds):
                if held_in(quote.quote, news):
                    anchors.append((quote.line, "comment-quote-unchanged",
                                    "the passage it quotes is unchanged in v2", quote.quote))
                    continue
                how, reads = now_reads(quote.quote, old, new)
                message = ("the passage it quotes is gone from v2" if how == "gone" else
                           "the passage it quotes changed in v2" +
                           (f"; v2 has there: {reads!r}" if reads else ""))  # fmt: skip
                anchors.append((quote.line, f"comment-quote-{how}", message, quote.quote))
            elif held_in(quote.quote, news):
                anchors.append((quote.line, "comment-quote-in-v2", "the passage it quotes is "
                                "not in v1, and v2 has it", quote.quote))  # fmt: skip
            else:
                anchors.append((quote.line, "comment-quote-in-neither", "the passage it "
                                "quotes is not in v1 either, nor in v2", quote.quote))
        for label, lines in named(said, titles, line).items():
            anchors.append((lines[0], "comment-named", f"it names {label}: "
                            f"{status(label, old, new)}", None))  # fmt: skip
        if not anchors:
            found.append(Item(COMMENTS, GATE, "comment-not-matched", f"{name}: not matched: "
                              "it quotes no passage and names no table, figure or section; "
                              "read it", INFO, False, path, line))  # fmt: skip
        found += [Item(COMMENTS, GATE, code, f"{name}: {message}", INFO, False, path, at,
                       None if quote is None else shown(quote))
                  for at, code, message, quote in anchors]  # fmt: skip
    return found


def read_text_of(path: Path, what: str) -> str:
    """A letter's or a comments file's text: Markdown or text as it is, a .docx as `audit`
    reads one. Raises Unreadable."""
    from manuscript_guard.audit import UnreadableText, read_text
    from manuscript_guard.text.docx import NotADocx, read_docx_text

    if not path.is_file():
        raise Unreadable(f"{what} {path} does not exist" if not path.exists()
                         else f"{what} {path} is not a file")  # fmt: skip
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return read_docx_text(path).text
        if suffix in {".md", ".markdown", ".txt"}:
            return read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    except (NotADocx, UnreadableText, OSError) as exc:
        raise Unreadable(f"{what} {path} cannot be read: {exc}") from None
    raise Unreadable(f"{what} {path} is not a .docx, .md or .txt, which is what compare reads")
