"""A communication text as `communicate check` reads it: its front matter, its sentences, the
sentences that claim, and the statement of the brief each claiming sentence is anchored to.

A text is Markdown, under `communication/`, with front matter that names its channel:

    ---
    channel: bluesky
    allow:
      - sentence: "cuts the risk"
        reason: the trial's primary outcome, as the paper's abstract puts it
    ---

A sentence **claims** where it holds a word of the claim ladder (`data/claim_strength.yaml`,
"associated", "increased", "caused"), a typed number, or a binding of a value
(`{{results.key}}`, `{{lit.key}}`). A claiming sentence names the statement of the brief it
restates by an **anchor**, which prints nothing:

- a link with no text, `[](#brief:findings.1)`, in the sentence or right after its stop;
- a comment, `<!-- brief: findings.1 -->`, or `<!-- brief: findings.1, limitations.2 -->`.

An anchor in code, in a listing, in another comment or in the front matter is no anchor. A
sentence that claims nothing needs none (decision 2 of 2026-10-28), and one that holds an
anchor is read against its statement whether it claims or not.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

import yaml

from manuscript_guard import claims
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import (
    NUL,
    fenced_blocks,
    front_matter_end,
    html_comments,
    mask,
)
from manuscript_guard.text.placeholders import VALUE_NAMESPACES, parse
from manuscript_guard.text.tokens import find_atoms

#: A statement's id, as the brief writes one: `findings.1`, `limitations.2`.
ID = r"[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*"
#: An anchor written as a link with no text.
LINK = re.compile(r"\[\]\(#brief:(?P<id>" + ID + r")\)")
#: An anchor written as a comment, whole: one id or several, after `brief:`.
COMMENT = re.compile(
    r"\A<!--[ \t\n]*brief:[ \t]*(?P<ids>" + ID + r"(?:[ \t]*,[ \t]*" + ID + r")*)[ \t\n]*-->\Z"
)
_FRONT = re.compile(r"\A---[ \t]*\n(?P<yaml>.*?)\n?(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.DOTALL)
#: A line that parts one post of a thread from the next: a rule of dashes after a blank
#: line. Right under a line of text it is a heading's underline, and parts nothing.
_RULE_LINE = re.compile(r"[ \t]*-{3,}[ \t]*")
#: A mention, `@alice.bsky.social`: no citation of a post's, which writes one in brackets.
_HANDLE = re.compile(r"(?<![\w@.\[/])@[A-Za-z0-9_](?:[\w.-]*\w)?")
#: A hashtag, `#pharmacovigilance`, and not a heading, an entity or a link's fragment.
_HASHTAG = re.compile(r"(?<![\w&#/])#[^\W\d][\w]*")
_BRACKETED = re.compile(r"\[[^\[\]\n]*\]")
_THREAD = chr(0x1F9F5)
#: A thread's counter, "1/5", "(2/5)", "3/5 " followed by the thread's emoji.
_COUNTER = re.compile(
    r"(?:" + _THREAD + r"[ \t]*)?\(?(?P<at>\d{1,3})/(?P<of>\d{1,3})\)?(?:[ \t]*" + _THREAD + r")?"
)


@dataclass(frozen=True)
class Anchor:
    """One statement an anchor names, and where the anchor stands."""

    id: str
    start: int
    end: int


@dataclass(frozen=True)
class Sentence:
    """One sentence of a text: where it stands, its words as typed with its anchors taken
    out, why it claims (empty where it does not), and the statements it is anchored to."""

    start: int
    end: int
    line: int
    text: str
    why: str = ""
    anchors: tuple[str, ...] = field(default=())

    @property
    def claims(self) -> bool:
        return bool(self.why)


@dataclass(frozen=True)
class Text:
    """A communication text: its front matter as read, and its body's sentences."""

    front: dict
    #: Why the front matter could not be read, where it could not.
    front_error: str
    #: The whole text with its line ends made line feeds, every anchor blanked to spaces.
    blanked: str
    #: Where the body starts, past the front matter.
    body_start: int
    sentences: tuple[Sentence, ...]
    anchors: tuple[Anchor, ...]
    #: `blanked` with what a post holds and the paper does not blanked too: each mention, each
    #: hashtag and each thread's counter. What its facts, numbers and claims are read in.
    readable: str = ""
    #: Each post of a thread, as its start and its end in the text.
    posts: tuple[tuple[int, int], ...] = ()


def front_matter(text: str) -> tuple[dict, str]:
    """The front matter of `text` as a mapping, and why it is none where it is not one."""
    found = _FRONT.match(text)
    if found is None:
        return {}, ""
    try:
        document = yaml.safe_load(found["yaml"])
    except yaml.YAMLError as exc:
        return {}, f"its front matter is not YAML: {str(exc).splitlines()[0]}"
    if document is None:
        return {}, ""
    if not isinstance(document, dict):
        return {}, "its front matter is not a mapping of keys to values"
    return document, ""


def _inside(spans: list[tuple[int, int]], at: int) -> bool:
    return any(start <= at < end for start, end in spans)


def anchors(text: str) -> list[Anchor]:
    """Every anchor of `text`, in order: each link with no text whose target is a statement,
    outside code, a listing, a comment and the front matter, and each comment that is an
    anchor whole, every id it names."""
    head = front_matter_end(text)
    fences = fenced_blocks(text)
    comments = html_comments(text, fences)
    hidden = [(0, head), *((f.start, f.end) for f in fences), *comments]
    chars = list(text)
    for start, end in hidden:
        chars[start:end] = NUL * (end - start)
    hidden += code_spans("".join(chars))
    found = [
        Anchor(link["id"], link.start(), link.end())
        for link in LINK.finditer(text)
        if not _inside(hidden, link.start())
    ]
    for start, end in comments:
        if start < head:
            continue
        whole = COMMENT.match(text[start:end])
        if whole is not None:
            found += [Anchor(one.strip(), start, end) for one in whole["ids"].split(",")]
    return sorted(found, key=lambda anchor: (anchor.start, anchor.id))


def _why(words: tuple, atoms: list, bindings: list) -> str:
    """Why a sentence claims: its first word of the ladder, number or binding, whichever
    stands first; nothing where it holds none."""
    reasons = []
    if words:
        ladder = [word for word, kind in words if isinstance(kind, int)]
        if ladder:
            reasons.append((0, f"the word '{ladder[0]}'"))
    if atoms:
        reasons.append((1, f"the number '{atoms[0].text}'"))
    if bindings:
        reasons.append((2, f"the binding {bindings[0].raw}"))
    return min(reasons)[1] if reasons else ""


def read(text: str) -> Text:
    """`text` read: its front matter, its anchors, and each sentence of its body."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    front, error = front_matter(text)
    found = anchors(text)
    chars = list(text)
    for anchor in found:
        chars[anchor.start : anchor.end] = [
            "\n" if char == "\n" else " " for char in text[anchor.start : anchor.end]
        ]
    blanked = "".join(chars)
    head = front_matter_end(blanked)
    threads = posts(blanked, head)
    readable = _readable(blanked, threads)
    spans = claims.sentence_spans(readable)
    worded = claims.sentences(readable)
    masked = mask(readable)
    atoms = find_atoms(readable, masked)
    starts = [atom.start for atom in atoms]
    bound = [p for p in parse(blanked)[0] if p.namespace in VALUE_NAMESPACES]
    breaks = [0, *(at.end() for at in re.finditer("\n", blanked))]
    owned: dict[int, list[str]] = {}
    for anchor in found:
        index = _owner(spans, anchor, readable)
        if index is not None:
            owned.setdefault(index, []).append(anchor.id)
    sentences = []
    for index, ((_piece, start, end), worded_one) in enumerate(zip(spans, worded, strict=True)):
        if end <= head:
            continue
        low, high = bisect_right(starts, start - 1), bisect_right(starts, end - 1)
        mine = [p for p in bound if start <= p.start < end]
        sentences.append(
            Sentence(
                start,
                end,
                bisect_right(breaks, start),
                _SPACE_BEFORE.sub(r"\1", " ".join(blanked[start:end].split())),
                _why(worded_one.words, atoms[low:high], mine),
                tuple(dict.fromkeys(owned.get(index, ()))),
            )
        )
    return Text(front, error, blanked, head, tuple(sentences), tuple(found), readable,
                tuple(threads))  # fmt: skip


_SPACE_BEFORE = re.compile(r" ([.,;:!?)])")


def posts(text: str, head: int = 0) -> list[tuple[int, int]]:
    """Each post of `text` past `head`: the body cut at each line that is a rule of dashes
    after a blank line, the rule in neither post."""
    found = []
    start = at = head
    blank_before = True
    for line in text[head:].splitlines(keepends=True):
        bare = line.rstrip("\n")
        if blank_before and _RULE_LINE.fullmatch(bare):
            found.append((start, at))
            start = at + len(line)
        blank_before = not bare.strip()
        at += len(line)
    found.append((start, len(text)))
    return [(low, high) for low, high in found if text[low:high].strip()]


def _blank(chars: list[str], start: int, end: int) -> None:
    chars[start:end] = [" "] * (end - start)


def _readable(blanked: str, threads: list[tuple[int, int]]) -> str:
    """`blanked` with each mention, hashtag and thread counter blanked, offsets kept."""
    chars = list(blanked)
    bracketed = [(found.start(), found.end()) for found in _BRACKETED.finditer(blanked)]
    for pattern in (_HANDLE, _HASHTAG):
        for found in pattern.finditer(blanked):
            if pattern is _HANDLE and _inside(bracketed, found.start()):
                continue
            _blank(chars, found.start(), found.end())
    for low, high in threads:
        for start, end in _counters(blanked, low, high):
            _blank(chars, start, end)
    return "".join(chars)


def _counters(text: str, low: int, high: int) -> list[tuple[int, int]]:
    """Where a post opens or ends with its thread's counter: "1/5" before a word with a
    capital, or alone; "2/5" after a stop, or alone; either beside the thread's emoji. One
    whose first number is the greater is a fraction."""
    found = []
    first = low + len(text[low:high]) - len(text[low:high].lstrip())
    opening = _COUNTER.match(text, first, high)
    if opening is not None and _counts(opening):
        after = text[opening.end() : high].lstrip()
        if _THREAD in opening.group() or not after or not after[0].islower():
            found.append((opening.start(), opening.end()))
    last = low + len(text[low:high].rstrip())
    for closing in _COUNTER.finditer(text, first, last):
        if closing.end() != last or not _counts(closing) or (found and closing.start() <
                                                             found[0][1]):  # fmt: skip
            continue
        before = text[first : closing.start()].rstrip()
        if _THREAD in closing.group() or not before or not before[-1].isalnum():
            found.append((closing.start(), closing.end()))
    return found


def _counts(found: re.Match[str]) -> bool:
    return 0 < int(found["at"]) <= int(found["of"])


_BLANK_LINE = re.compile(r"\n[ \t\x00]*\n")


def _owner(spans: list[tuple[int, int, int]], anchor: Anchor, blanked: str) -> int | None:
    """The sentence an anchor belongs to: the one whose piece of the text it stands in,
    which runs on over the space after its stop, so that an anchor written after the stop is
    its sentence's. One that stands in no sentence's piece, on a line of its own, is the
    sentence's before it, unless a blank line parts it from that one and none from the
    sentence after, which it then opens."""
    before = after = None
    for index, (piece, first, end) in enumerate(spans):
        if piece <= anchor.start < end:
            if anchor.start >= first + len(blanked[first:end].rstrip(" \t\n\x00")) and \
                    _opens_next(spans, index, anchor, blanked):  # fmt: skip
                return index + 1
            return index
        if end <= anchor.start:
            before = index
        elif after is None:
            after = index
    if before is None or after is None:
        return after if before is None else before
    parted = _BLANK_LINE.search(blanked, spans[before][2] - 1, anchor.start) is not None
    joined = _BLANK_LINE.search(blanked, anchor.end, spans[after][1]) is None
    return after if parted and joined else before


def _opens_next(spans: list[tuple[int, int, int]], index: int, anchor: Anchor,
                blanked: str) -> bool:  # fmt: skip
    """Whether an anchor in the space after a sentence's stop opens the next sentence: it
    opens its line, and the next sentence starts on that line, `<!-- brief: x --> It was.`
    One after the stop on the stop's own line is the sentence's before."""
    if index + 1 >= len(spans):
        return False
    line_start = blanked.rfind("\n", 0, anchor.start) + 1
    if blanked[line_start : anchor.start].strip(" \t\x00"):
        return False
    return "\n" not in blanked[anchor.end : spans[index + 1][1]]


def body(text: str) -> str:
    """`text` past its front matter, its line ends made line feeds."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[front_matter_end(text) :]
