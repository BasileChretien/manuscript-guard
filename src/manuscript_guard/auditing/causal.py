"""`audit --design observational`: a word that claims a cause where the paper sums up what it
found.

The reader declares the design; nothing here guesses it. An observational study shows an
association, and a sentence of its Abstract, Discussion or Conclusion that says one thing
causes another claims more than the design can show. So each sentence there (`auditing.
sentences`) is read for a word of the causation rung of the claim ladder
(`data/claim_strength.yaml`: cause, causes, caused, causing, causal, causally, "demonstrate(d/s)
that", "prove(d/s) that"), the rung only (Basile, 2026-10-29, decision 6 of the editor and
referee layer): "reduced the risk" is the effect rung, and is not read.

A sentence is passed over where it holds a hedge or a negation of the ladder's lists ("may
cause", "we cannot prove that"), which claims no cause, or carries a citation (`sentences`),
where the cause may be another study's, a trial's: "X causes Y [12]". Every other sentence
with such a word is a warning, `causal-word-observational`, which `--strict` does not count.
The Methods, the Results and every other part are never read: "a causal diagram" in the
Methods describes the analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.auditing.sentences import ABSTRACT, CONCLUSION, DISCUSSION, View

CODE = "causal-word-observational"
#: The designs `--design` takes.
DESIGNS = ("observational",)
#: The parts of a paper whose sentences are read.
READ = (ABSTRACT, DISCUSSION, CONCLUSION)
#: The rung of the ladder that is read.
RUNG = "causation"


@dataclass(frozen=True)
class Causal:
    """A sentence that claims a cause: where it is, the words, the part, and the sentence."""

    path: Path
    line: int
    words: tuple[str, ...]
    part: str
    sentence: str


@dataclass
class CausalRead:
    """What `--design` read: how many sentences of the parts it reads, how many with a
    causal word were passed over and why, each one said, and the files with no heading that
    names a part it reads."""

    design: str
    read: int = 0
    hedged: int = 0
    negated: int = 0
    cited: int = 0
    found: list[Causal] = field(default_factory=list)
    unplaced: list[Path] = field(default_factory=list)
    #: What of a file was not read, each with its file: a front matter's abstract that is
    #: no plain string.
    notes: list[tuple[Path, str]] = field(default_factory=list)


def causal_words(views: list[View], design: str) -> CausalRead:
    """Each sentence of the Abstract, the Discussion and the Conclusion of each file that
    holds a causal word and no hedge, negation or citation."""
    from manuscript_guard.claims import claim_words, lists

    rung = lists().rungs.index(RUNG)
    found = CausalRead(design)
    placed: dict[Path, bool] = {}
    for view in views:
        sentences = view.sentences
        # A `\nocite` prints no citation in the sentence (round 2 of #482).
        citing = {view.owner(cite.start) for cite in view.cites if cite.prints}
        found.notes += [(view.path, note) for note in view.notes]
        placed.setdefault(view.path, False)
        for index, sentence in enumerate(sentences):
            if sentence.place.part not in READ:
                continue
            placed[view.path] = True
            found.read += 1
            # From its first word: a citation of the sentence before may open its piece.
            words = claim_words(view.read, sentence.first, sentence.end)
            causal = tuple(dict.fromkeys(word for word, kind in words if kind == rung))
            if not causal:
                continue
            why = passed({kind for _word, kind in words})
            if why == "negated":
                found.negated += 1
            elif why == "hedged":
                found.hedged += 1
            elif index in citing:
                found.cited += 1
            else:
                found.found.append(Causal(view.path, sentence.line, causal,
                                          sentence.place.part, sentence.text))  # fmt: skip
    found.unplaced = [path for path, read in placed.items() if not read]
    return found


def passed(kinds: set) -> str | None:
    """Why a sentence whose words are of `kinds` claims no cause: "negated" where it holds a
    negation, "hedged" where it holds a hedge, None where neither."""
    from manuscript_guard.claims import HEDGE, NEGATED

    if NEGATED in kinds:
        return "negated"
    return "hedged" if HEDGE in kinds else None


def said(one: Causal) -> str:
    """What the report says of a sentence that claims a cause."""
    words = " and ".join(f"'{word}'" for word in one.words)
    return (f"{words} in the {one.part}, in a sentence with no hedge, no negation and no "
            "citation: the study is observational (--design), and the word claims a cause")


#: What the report says to do about one.
HINT = ("an observational design shows an association: ask whether the sentence means one, or "
        "whether a cited trial or a hedge is missing")


__all__ = ["CODE", "DESIGNS", "HINT", "READ", "Causal", "CausalRead", "causal_words", "said"]
