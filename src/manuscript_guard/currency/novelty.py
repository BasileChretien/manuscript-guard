"""Claims of novelty or absence in the manuscript, read by the list in data (DESIGN.md, "A
claim to be first, or that nothing is known, rests on a recorded search").

`data/novelty_claims.yaml` holds three lists, `priority`, `absence` and `softer`. Each
paragraph of the main text and of `manuscript/supplementary/`, Markdown or LaTeX (a LaTeX
document as it prints, `text.latex.printed`), is read in the prose G6 masks: code, maths,
bindings and comments are blank there, and in Markdown the front matter too. A paragraph is
cut into sentences only where a pattern matches in it, since the cut reads a long paragraph
slowly. Each sentence is matched with its whitespace folded to single spaces and its case
folded; a sentence is one claim, of the first list that reads it. A claim keeps its words as
written (for LaTeX as the printed view gives them), and is matched to an entry of kind
`novelty` in `literature/currency.yaml` by those words folded (`statement_words`), exactly:
any rewording takes an entry off its claim.

Nothing here reads a record or the network: the gate (`gates/novelty.py`) holds each claim to
its entry's searches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project

DATA = Path(__file__).parent.parent / "data" / "novelty_claims.yaml"
#: The lists, in the order a sentence is read by them.
LISTS = ("priority", "absence", "softer")
#: The lists that warn from drafting and fail at submission; `softer` is a note.
BINDING = ("priority", "absence")
_FRAGMENT = re.compile(r"\$\{(\w+)\}")
_NUL = "\x00"


@dataclass(frozen=True)
class Rule:
    """One pattern of the list: the list it is in, its id, the pattern and why."""

    list: str
    id: str
    pattern: re.Pattern[str]
    why: str


@dataclass(frozen=True)
class Claim:
    """A sentence the list reads: its file, the line its paragraph starts on, its words as
    written, the list and the pattern that read it, and the words matched."""

    path: Path
    line: int
    text: str
    list: str
    rule: str
    words: str

    @property
    def folded(self) -> str:
        """The words an entry is matched by."""
        from manuscript_guard.literature.passages import statement_words

        return statement_words(self.text)


def _expanded(pattern: str, fragments: dict[str, str], depth: int = 0) -> str:
    if depth > 5:
        raise ValueError(f"{DATA.name}: the fragments refer to each other in a circle")
    return _FRAGMENT.sub(lambda found: _expanded(fragments[found[1]], fragments, depth + 1),
                         pattern)  # fmt: skip


@lru_cache(maxsize=1)
def rules() -> tuple[Rule, ...]:
    """The three lists, in the order a sentence is read by them."""
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    fragments = {name: " ".join(str(text).split()) for name, text in
                 (document.get("fragments") or {}).items()}  # fmt: skip
    out = []
    for name in LISTS:
        for item in document.get(name) or ():
            pattern = _expanded(str(item["pattern"]), fragments)
            out.append(Rule(name, str(item["id"]), re.compile(pattern, re.IGNORECASE),
                            str(item["why"])))  # fmt: skip
    return tuple(out)


@lru_cache(maxsize=1)
def nothing_left_out() -> frozenset[str]:
    """The words a `not_searched` may not be, folded as `_folded_note` folds it."""
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return frozenset(_folded_note(str(word)) for word in document.get("nothing_left_out") or ())


def _folded_note(text: str) -> str:
    return " ".join(text.replace(".", " ").split()).casefold()


def not_searched_problem(text: object) -> str:
    """Why `text` cannot say what a search did not reach, or "" where it can (D4.4): it is
    given, as words, holds a letter, and is not a word that says nothing was left out."""
    if text is not None and not isinstance(text, str):
        return ("what the search did not reach is said in words, one text, not a list or a "
                "number")  # fmt: skip
    if text is None or not text.strip():
        return ("say what the search did not reach: the databases and the kinds of work it "
                "left out (Embase, grey literature, conference abstracts, other languages)")
    if not any(char.isalpha() for char in text):
        return "what the search did not reach is said in words, with a letter in them"
    if _folded_note(text) in nothing_left_out():
        return (f"{text.strip()!r} says the search left nothing out, which no search does: "
                "name the databases and the kinds of work it did not reach")
    return ""


def read_sentence(sentence: str) -> tuple[Rule, str] | None:
    """The first rule that reads a sentence, with the words it matched; None where none does.
    The sentence is matched with its whitespace folded."""
    folded = " ".join(sentence.replace(_NUL, " ").split())
    for rule in rules():
        found = rule.pattern.search(folded)
        if found:
            return rule, found.group(0)
    return None


def _any_rule(text: str) -> bool:
    folded = " ".join(text.replace(_NUL, " ").split())
    return any(rule.pattern.search(folded) for rule in rules())


def claims_in(text: str) -> list[tuple[int, str, Rule, str]]:
    """Each claim of one text, as `(line, sentence, rule, words)`: the line the sentence's
    paragraph starts on, its words as written, comments blanked, the rule that read it and
    the words matched. Read in the prose G14 reads (`gates.language._hidden`): what
    `text.masking.mask` takes, the front matter, inline code, equations and image captions
    are blank there."""
    from manuscript_guard.checking.produce import _split
    from manuscript_guard.gates.language import _hidden
    from manuscript_guard.text.masking import blank_comments

    body = blank_comments(text)
    masked = _hidden(text)
    out: list[tuple[int, str, Rule, str]] = []
    line, at = 1, 0
    for paragraph in body.split("\n\n"):
        start, end = at, at + len(paragraph)
        at = end + 2
        # A third line break in a row opens the next piece: its words start below it (round
        # 1 of #583).
        here = line + paragraph[:len(paragraph) - len(paragraph.lstrip("\r\n"))].count("\n")
        line += paragraph.count("\n") + 2
        prose = masked[start:end]
        if not _any_rule(prose):
            continue
        tokens = [found.span() for found in re.finditer(r"\S+", paragraph)]
        pieces = _split(" ".join(paragraph.split()))
        spans = _spans(pieces, tokens)
        for piece, (first, last) in zip(pieces, spans, strict=True):
            read = read_sentence(prose[first:last])
            if read is not None:
                out.append((here, piece, *read))
    return out


def _spans(pieces: list[str], tokens: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Where each piece `_split` cut stands in its paragraph: pieces are runs of whole words,
    so the n-th piece is its words' run of the paragraph's. Where they do not add up, every
    piece is read over the whole paragraph."""
    counts = [len(piece.split()) for piece in pieces]
    if sum(counts) != len(tokens) or not tokens:
        whole = (tokens[0][0], tokens[-1][1]) if tokens else (0, 0)
        return [whole] * len(pieces)
    spans, index = [], 0
    for count in counts:
        spans.append((tokens[index][0], tokens[index + count - 1][1]) if count else (0, 0))
        index += count
    return spans


def claims(project: Project) -> list[Claim]:
    """Every claim of the main text and the supplement, in the order of the files and their
    sentences: a Markdown file as typed, a LaTeX document as it prints, each sentence placed
    back at its `.tex` file and line, once."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    out: list[Claim] = []
    if manuscript_format(folder) != LATEX:
        for path in source_files(folder):
            out += [Claim(path, line, sentence, rule.list, rule.id, words)
                    for line, sentence, rule, words in claims_in(read_text(path))]  # fmt: skip
        return out
    from manuscript_guard.text.latex.printed import printed_of

    for part in (False, True):
        view = printed_of(folder, supplementary=part)
        for line, sentence, rule, words in claims_in(view.text):
            where = view.place_line(line)
            if where is not None:
                source, placed = where
                out.append(Claim(folder / source.path, placed, sentence, rule.list, rule.id,
                                 words))  # fmt: skip
    return out


__all__ = ["BINDING", "LISTS", "Claim", "Rule", "claims", "claims_in", "not_searched_problem",
           "nothing_left_out", "read_sentence", "rules"]
