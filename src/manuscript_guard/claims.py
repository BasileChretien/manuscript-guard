"""Did an edit change how strongly a sentence claims what it claims?

`reworded` holds an edit to the words: no binding, citation key or typed number may change.
A polish can keep all of those and still say something else. "Use was associated with a
higher risk" made "use increased the risk" claims an effect where the analysis showed an
association; a "may" dropped makes a possibility a finding; a "did not" dropped turns the
result round. Every fact stands where it stood.

So each sentence the edit changed is compared with what it was, for the words that set how
strongly it claims (`data/claim_strength.yaml`, adapted from the Claim-Strength Contract of
Yila-AI/awesome-research-skills):

- a **hedge**, "may", "appears": one gone makes the claim stronger, one new weaker;
- a **limit**, "only", "in this sample": the same;
- a word of the **ladder**, which runs from consistency through association, prediction,
  contribution and effect to causation: a word moved up makes the claim stronger, down
  weaker. Within a rung it is free, "associated" made "linked to";
- a **negation**, "not", "no": one gone or new turns the claim round, whatever else moved.

Hedges, limits and negations are counted, so "may" made "might" is free. A sentence whose
moves go both ways, or whose ladder words changed with no direction to tell, is reported
as moved.

Every finding is a warning. A list of words cannot know whether the author meant the move,
and a reviewer who asked for "associated" where the text said "caused" meant it.

Only sentences the edit changed are read, each against what it was. The two texts are cut
into sentences, and those that stand in both, once in each and in the same order, are
lined up first, as patience diff does: the longest run of them in order, found in n log n.
Between two of them lies what the edit changed. Where as many sentences stand there before
as after, they are compared one by one, and otherwise together. Where there are none on
one side, a sentence was added or deleted whole, and nothing is compared: that is no
rewording of a sentence, and its numbers and citations are held by `reworded` itself.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.findings import WARN, Finding
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import NUL, front_matter_end, mask

GATE = "REWORDED"
DATA = Path(__file__).parent / "data" / "claim_strength.yaml"

STRONGER = "claim-stronger"
WEAKER = "claim-weaker"
MOVED = "claim-moved"
NEGATION = "claim-negation"
#: Every code a finding of this module carries. A caller that holds a text to its facts
#: and only shows its claims, as a review panel's suggested edit is, tells them apart by it.
CODES = frozenset({STRONGER, WEAKER, MOVED, NEGATION})

HEDGE = "hedge"
LIMIT = "limit"
NEGATED = "negation"
#: The classes of words that are counted in a sentence, and compared by their count.
COUNTED = (HEDGE, LIMIT, NEGATED)
#: A word that ends so is read as the class it is listed under: "*n't".
_ANY_WORD = "*"

#: Where a sentence ends: a stop, what may close after it, and a space, where the next word
#: does not go on in lower case. "e.g. the" goes on; so does "0.5", which has no space.
_STOP = re.compile(
    r"[.!?][)\]\"'*_\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]*"
    r"\s+(?![\sa-z])"
)
#: A line that opens a block opens a sentence too: a blank line, a heading, a quotation, an
#: item of a list, a table's row. A line of blanked text alone is a blank line.
_BLOCK = re.compile(r"\n[ \t\x00]*(?:\n|#|>|[-*+][ \t]|\d+[.)][ \t]|\|)")
_LETTER = re.compile(r"[^\W_]")
_SPACES = re.compile(r"[\s\x00]+")
#: "a", "an" or "the" directly before what follows.
_ARTICLE = re.compile(r"(?<![\w-])(?:a|an|the)\s+\Z", re.IGNORECASE)

#: A word as it was read, and what it is: a class, or a rung of the ladder.
Word = tuple[str, "str | int"]


@dataclass(frozen=True)
class Lists:
    """The words, read from the data file."""

    pattern: re.Pattern[str]
    #: Each word as it is read, in lower case with one space between its words, and what it
    #: is: a class, or the rung of the ladder counted from the weakest.
    kinds: dict[str, str | int]
    #: What ends a word that is read as one class whatever it starts with.
    endings: tuple[tuple[str, str], ...]
    rungs: tuple[str, ...]
    lower_case_only: frozenset[str]

    def kind(self, word: str) -> str | int | None:
        """What `word` is, or None where it is none of the words: the pattern ignores case
        as Python does, which matches "i" to a dotless i and "s" to a long s, and "might"
        typed with a dotless i is no word of the list."""
        if word in self.kinds:
            return self.kinds[word]
        return next((kind for ending, kind in self.endings if word.endswith(ending)), None)


def _phrase(word: str) -> str:
    if word.startswith(_ANY_WORD):
        return r"[^\W\d_]+" + re.escape(word[len(_ANY_WORD) :])
    return r"\s+".join(map(re.escape, word.split()))


#: What may not stand on either side of a word that is read: a letter, a figure or a hyphen,
#: which join it to another word.
EDGES = (r"(?<![\w-])", r"(?![\w-])")


@lru_cache(maxsize=1)
def lists() -> Lists:
    return read_lists()


def read_lists(edges: tuple[str, str] = EDGES) -> Lists:
    """The words of the data file, each read between `edges`."""
    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    kinds: dict[str, str | int] = {}
    for rung, step in enumerate(data["ladder"]):
        kinds.update(dict.fromkeys(step["words"], rung))
    for name, kind in (("hedges", HEDGE), ("limits", LIMIT), ("negations", NEGATED)):
        kinds.update(dict.fromkeys(data[name], kind))
    endings = tuple(
        (word[len(_ANY_WORD) :], kind) for word, kind in kinds.items() if word.startswith("*")
    )
    words = sorted(kinds, key=len, reverse=True)
    pattern = re.compile(
        edges[0] + "(?:" + "|".join(map(_phrase, words)) + ")" + edges[1], re.IGNORECASE
    )
    return Lists(
        pattern,
        {word: kind for word, kind in kinds.items() if not word.startswith(_ANY_WORD)},
        endings,
        tuple(step["rung"] for step in data["ladder"]),
        frozenset(data.get("lower_case_only", ())),
    )


@dataclass(frozen=True)
class Sentence:
    """One sentence of a text, as it is lined up and as its claim is read."""

    #: Its words, every run of spaces and of blanked text made one space: two sentences
    #: with the same key are one sentence, wrapped or not.
    key: str
    line: int
    #: Each word that sets how strongly it claims, as it was read, with what it is.
    words: tuple[Word, ...]


def _readable(text: str) -> str:
    """`text` with what prints no prose of the author's blanked: `mask` blanks comments,
    listings, the keys of the front matter, bindings, citations and addresses, and inline
    code is blanked here. A curly apostrophe is read as a straight one."""
    read = mask(text)
    spans = code_spans(read)
    if spans:
        chars = list(read)
        for start, end in spans:
            chars[start:end] = NUL * (end - start)
        read = "".join(chars)
    return read.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")


def _capital(word: str, typed: str, opens: bool) -> bool:
    """Whether `word`, typed with a capital, is read: where it opens its sentence, with no
    other capital, and is not to be read in lower case only. A capital elsewhere marks a
    name, "in May 2020"."""
    return opens and typed[1:] == typed[1:].lower() and word not in lists().lower_case_only


def _words(read: str, start: int, end: int) -> tuple[Word, ...]:
    """The words of the sentence `read[start:end]` that set how strongly it claims."""
    known = lists()
    found = []
    for match in known.pattern.finditer(read, start, end):
        typed = match.group()
        word = " ".join(typed.lower().split())
        if typed != typed.lower():
            opens = _LETTER.search(read, start, match.start()) is None
            if not _capital(word, typed, opens):
                continue
        adjective = " " not in word and word.endswith("ed")
        if adjective and _ARTICLE.search(read, max(start, match.start() - 8), match.start()):
            continue
        kind = known.kind(word)
        if kind is not None:
            found.append((word, kind))
    return tuple(found)


def _pieces(
    text: str, read: str, lines: bool = False, cuts: Iterable[int] = ()
) -> list[tuple[int, int, int]]:
    """Where each sentence of `text` stands, as `read` cuts it: its start, the offset of its
    first character that is no space, and its end; a piece with no letter in `read` is none.
    `text` has its line ends made line feeds. With `lines`, each line is a block of its own,
    as each paragraph of a Word document read as text is; `cuts` are more places a sentence
    ends, where a LaTeX heading's command starts and its title ends."""
    cuts = {0, len(read), *(at for at in cuts if 0 < at < len(read))}
    cuts.update(found.end() for found in _STOP.finditer(read))
    cuts.update(found.start() + 1 for found in _BLOCK.finditer(read))
    if lines:
        cuts.update(found.end() for found in re.finditer("\n", read))
    # Each value of the front matter is read apart, and is on its own line. The mask blanks
    # the line ends there with the keys.
    head = front_matter_end(text)
    cuts.update(at + 1 for at in range(head) if text[at] == "\n")
    found = []
    ordered = sorted(cuts)
    for start, end in zip(ordered, ordered[1:], strict=False):
        piece = read[start:end]
        if _LETTER.search(piece) is None:
            continue
        found.append((start, start + len(piece) - len(piece.lstrip(" \t\n\x00")), end))
    return found


def sentence_spans(text: str) -> list[tuple[int, int, int]]:
    """Where each sentence of `text` stands, as `sentences` cuts them: where its piece of the
    text starts, where its first character that is no space stands, and where it ends, the
    space after its stop included. `text` has its line ends made line feeds already, so that
    an offset is one of the caller's."""
    return _pieces(text, _readable(text))


def readable(text: str) -> str:
    """`text` as a Markdown manuscript's sentences are read: what prints no prose blanked
    (`mask`, and inline code), at the same offsets, a curly apostrophe read as a straight
    one."""
    return _readable(text)


def sentence_pieces(
    text: str, read: str, lines: bool = False, cuts: Iterable[int] = ()
) -> list[tuple[int, int, int]]:
    """`sentence_spans` of a text already read: `read` is `text` with what prints no prose
    blanked at the same offsets, as `readable` blanks a Markdown file's, or as the audit's
    reading of a Word document or a LaTeX file does. With `lines`, each line is a block;
    `cuts` are more places a sentence ends."""
    return _pieces(text, read, lines, cuts)


def claim_words(read: str, start: int, end: int) -> tuple[Word, ...]:
    """The words of the sentence `read[start:end]` that set how strongly it claims, each
    with what it is: a class (`HEDGE`, `LIMIT`, `NEGATED`) or the rung of the ladder."""
    return _words(read, start, end)


def sentences(text: str) -> list[Sentence]:
    """The sentences of a manuscript file that hold a word, in order."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    read = _readable(text)
    breaks = [found.start() for found in re.finditer("\n", text)]
    return [
        Sentence(
            _SPACES.sub(" ", read[start:end]).strip(),
            bisect_left(breaks, first) + 1,
            _words(read, start, end),
        )
        for start, first, end in _pieces(text, read)
    ]


# ------------------------------------------------------------------- lining the texts up


def _chain(anchors: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest run of `anchors`, given in the order of the text before, that is in order
    in the text after too: patience sorting, n log n."""
    tails: list[int] = []
    tail_of: list[int] = []
    back: list[int] = []
    for index, (_was, now) in enumerate(anchors):
        at = bisect_left(tails, now)
        if at == len(tails):
            tails.append(now)
            tail_of.append(index)
        else:
            tails[at] = now
            tail_of[at] = index
        back.append(tail_of[at - 1] if at else -1)
    chain = []
    index = tail_of[-1] if tail_of else -1
    while index >= 0:
        chain.append(anchors[index])
        index = back[index]
    return chain[::-1]


Unit = tuple[tuple[Sentence, ...], tuple[Sentence, ...]]


def changed(was: Sequence[Sentence], now: Sequence[Sentence]) -> list[Unit]:
    """What the edit changed, each piece as the sentences before and the sentences after:
    one and one where a stretch has as many on each side, all of the stretch otherwise.
    A stretch with nothing on one side is a sentence added or deleted whole, and left out."""
    stood = Counter(sentence.key for sentence in was)
    stands = Counter(sentence.key for sentence in now)
    once = {key for key, count in stood.items() if count == 1 and stands[key] == 1}
    where = {sentence.key: at for at, sentence in enumerate(now) if sentence.key in once}
    chain = _chain([(at, where[one.key]) for at, one in enumerate(was) if one.key in once])
    units: list[Unit] = []
    ends = [*chain, (len(was), len(now))]
    for (low, first), (high, last) in zip([(-1, -1), *chain], ends, strict=True):
        low, first = low + 1, first + 1
        while low < high and first < last and was[low].key == now[first].key:
            low, first = low + 1, first + 1
        while low < high and first < last and was[high - 1].key == now[last - 1].key:
            high, last = high - 1, last - 1
        units += _stretch(was[low:high], now[first:last])
    return units


def _stretch(was: Sequence[Sentence], now: Sequence[Sentence]) -> list[Unit]:
    """What changed in one stretch, its ends that stand in both texts taken off: one and one
    where it has as many sentences before as after, all of it otherwise. A stretch with
    nothing on one side is a sentence added or deleted whole, no rewording of a sentence,
    and nothing is compared."""
    if not was or not now:
        return []
    if len(was) == len(now):
        return [
            ((one,), (other,)) for one, other in zip(was, now, strict=True) if one.key != other.key
        ]
    return [(tuple(was), tuple(now))]


# --------------------------------------------------------------------- what moved, and how


def _beyond(words: Sequence[Word], other: Sequence[Word], by_rung: bool = False) -> list[Word]:
    """The words of `words` that `other` does not hold as often, in their order: counted by
    the word, or for the ladder by its rung, so that a word made another of its rung is no
    change."""

    def key(word: Word) -> str | int:
        return word[1] if by_rung else word[0]

    left = Counter(map(key, words)) - Counter(map(key, other))
    taken = []
    for word in words:
        if left[key(word)] > 0:
            left[key(word)] -= 1
            taken.append(word)
    return taken


def _listed(shown: Sequence[str]) -> str:
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _change(gone: Sequence[str], new: Sequence[str]) -> str:
    """"'may' is gone", "'only' is new", "'may' is now 'might' and 'possibly'"."""
    if gone and new:
        return f"{_listed(gone)} {'is' if len(gone) == 1 else 'are'} now {_listed(new)}"
    words = gone or new
    return f"{_listed(words)} {'is' if len(words) == 1 else 'are'} {'gone' if gone else 'new'}"


def _ladder(was: Sequence[int], now: Sequence[int]) -> str:
    """Which way the ladder moved, from the rungs of its words before and after: STRONGER,
    WEAKER, or MOVED where that cannot be told.

    Where words left rungs and words came to others, the move is up when every rung that
    came is above every rung that left, and down the other way. Where words only left or
    only came, the sentence is read by its lowest rung, which is its claim where one word
    of the ladder holds another: "associated with increased mortality" claims an
    association. With no word of the ladder a sentence states, and a word of consistency
    makes it claim less than that."""
    left = list((Counter(was) - Counter(now)).elements())
    came = list((Counter(now) - Counter(was)).elements())
    if left and came:
        if min(came) > max(left):
            return STRONGER
        return WEAKER if max(came) < min(left) else MOVED
    low_was, low_now = min(was, default=None), min(now, default=None)
    if low_was == low_now:
        return MOVED
    if low_was is None:
        return WEAKER if low_now == 0 else STRONGER
    if low_now is None:
        return STRONGER if low_was == 0 else WEAKER
    return STRONGER if low_now > low_was else WEAKER


def _lead(code: str, one: bool) -> str:
    it, claims = ("this sentence", "claims") if one else ("these sentences", "claim")
    did, said = ("it did", "it said") if one else ("they did", "they said")
    return {
        STRONGER: f"{it} {claims} more than {did} before the edit",
        WEAKER: f"{it} {claims} less than {did} before the edit",
        MOVED: f"how strongly {it} {claims} changed, and which way cannot be told",
        NEGATION: f"{it} may now say the opposite of what {said} before the edit",
    }[code]


_HINT = (
    "a language edit keeps what a sentence claims: if the move is meant, because the evidence "
    "or a reviewer asks for it, nothing needs doing; if not, put the words back"
)


def _finding(unit: Unit, path: Path | None) -> Finding | None:
    """What moved between the sentences of `unit` before and after, as one finding."""
    was = [word for sentence in unit[0] for word in sentence.words]
    now = [word for sentence in unit[1] for word in sentence.words]
    parts: list[str] = []
    ways: list[str] = []
    came: set[Word] = set()
    turned = False
    # Counted, so that a word made another of its class is no change.
    for kind in COUNTED:
        mine_was = [word for word in was if word[1] == kind]
        mine_now = [word for word in now if word[1] == kind]
        if len(mine_was) == len(mine_now):
            continue
        gone, new = _beyond(mine_was, mine_now), _beyond(mine_now, mine_was)
        parts.append(_change([f"'{word}'" for word, _ in gone], [f"'{word}'" for word, _ in new]))
        came.update(new)
        if kind == NEGATED:
            turned = True
        else:
            ways.append(STRONGER if len(mine_now) < len(mine_was) else WEAKER)
    ladder_was = [word for word in was if isinstance(word[1], int)]
    ladder_now = [word for word in now if isinstance(word[1], int)]
    gone = _beyond(ladder_was, ladder_now, by_rung=True)
    new = _beyond(ladder_now, ladder_was, by_rung=True)
    if gone or new:
        rungs = lists().rungs
        parts.append(_change([f"'{word}' ({rungs[rung]})" for word, rung in gone],
                             [f"'{word}' ({rungs[rung]})" for word, rung in new]))  # fmt: skip
        came.update(new)
        ways.append(_ladder([rung for _, rung in ladder_was], [rung for _, rung in ladder_now]))
    if not parts:
        return None
    if turned:
        code = NEGATION
    elif MOVED in ways or len(set(ways)) > 1:
        code = MOVED
    else:
        code = ways[0]
    one = len(unit[0]) == len(unit[1]) == 1
    message = f"{_lead(code, one)}: {'; '.join(parts)}"
    # On the first sentence that holds a word that came, where one came: in a stretch read
    # whole, a sentence added beside the one that changed may stand first.
    line = next(
        (sentence.line for sentence in unit[1] if came.intersection(sentence.words)),
        unit[1][0].line,
    )
    return Finding(GATE, code, message, WARN, path, line, hint=_HINT)


def compare_pair(source: str, said: str) -> Finding | None:
    """How strongly `said` claims against `source`, each read whole as one stretch: the
    finding `moved` would give had an edit made the one the other, or None where its claim
    is the same. For two texts that are not one edited into the other, a sentence of a
    communication and the sentence of the paper it restates (`communicate check`): nothing
    is lined up, since a paraphrase shares no sentence with its source. A source with no
    word is read as a sentence that states."""
    was = tuple(sentences(source)) or (Sentence("", 1, ()),)
    now = tuple(sentences(said))
    if not now:
        return None
    return _finding((was, now), None)


def moved(before: str, after: str, path: Path | None = None) -> list[Finding]:
    """A warning for each sentence, or stretch of sentences, whose claim an edit made
    stronger, weaker or turned round, placed on the line where it stands now."""
    found = (_finding(unit, path) for unit in changed(sentences(before), sentences(after)))
    return [finding for finding in found if finding is not None]

