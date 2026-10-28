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
    spans = claims.sentence_spans(blanked)
    worded = claims.sentences(blanked)
    masked = mask(blanked)
    atoms = find_atoms(blanked, masked)
    starts = [atom.start for atom in atoms]
    bound = [p for p in parse(blanked)[0] if p.namespace in VALUE_NAMESPACES]
    breaks = [0, *(at.end() for at in re.finditer("\n", blanked))]
    owned: dict[int, list[str]] = {}
    for anchor in found:
        index = _owner(spans, anchor, blanked)
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
                " ".join(blanked[start:end].split()),
                _why(worded_one.words, atoms[low:high], mine),
                tuple(dict.fromkeys(owned.get(index, ()))),
            )
        )
    return Text(front, error, blanked, head, tuple(sentences), tuple(found))


_BLANK_LINE = re.compile(r"\n[ \t\x00]*\n")


def _owner(spans: list[tuple[int, int, int]], anchor: Anchor, blanked: str) -> int | None:
    """The sentence an anchor belongs to: the one whose piece of the text it stands in,
    which runs on over the space after its stop, so that an anchor written after the stop is
    its sentence's. One that stands in no sentence's piece, on a line of its own, is the
    sentence's before it, unless a blank line parts it from that one and none from the
    sentence after, which it then opens."""
    before = after = None
    for index, (piece, _first, end) in enumerate(spans):
        if piece <= anchor.start < end:
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


def body(text: str) -> str:
    """`text` past its front matter, its line ends made line feeds."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text[front_matter_end(text) :]
