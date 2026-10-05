"""G14, its second reading — one term for one thing.

A manuscript that says "participants" in the Methods, "subjects" in the Results and
"patients" in the Discussion leaves the reader to work out whether those are three groups
or one. Which word is the right one is the author's call, and often the field's: nothing
here knows that a trial has participants and a registry has patients. What can be checked
is that the manuscript keeps to the word its author chose. So the choice is declared, in
`paper.yaml`:

    language:
      vocabulary:
        - use: participants
          avoid: [subjects, patients]

and the gate reports each word to avoid that the manuscript still uses, once, where it
first appears, with how often. It reports nothing the author did not declare: a check that
guessed at synonyms would be wrong about every pair that are two things.

**Every finding is a warning.** "Subject" is also what a result is subject to, and a list
of words cannot tell the two apart. The entry is the author's to narrow.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import WARN, Finding, Report

GATE = "G14"

# What separates the words of a term: "side effect" is also "side-effect", and a term may
# be broken over two lines of the source.
_BETWEEN = re.compile(r"[\s-]+")
# A quotation set as a block. Its words are somebody else's.
_QUOTED = re.compile(r"(?m)^[ ]{0,3}>[^\n]*")


@dataclass(frozen=True)
class Passage:
    """One manuscript file as this reading takes it: `printed` is the text with everything
    that is not a sentence or a heading blanked, offsets kept."""

    path: Path
    text: str
    printed: str
    line_of: Callable[[int], int]


def context(text: str, offset: int, length: int) -> str:
    """The words around a finding, on one line."""
    left = max(0, offset - 40)
    return re.sub(r"\s+", " ", text[left : offset + length + 40]).strip()


def _words(term: str) -> list[str]:
    return [word for word in _BETWEEN.split(term.strip()) if word]


def _key(term: str) -> str:
    """A term as it is compared: lower case, one space between its words."""
    return " ".join(_words(term)).lower()


def _shape(term: str) -> str:
    """The pattern a term is found by: its words, any white space or a hyphen between
    them, and the plural `s` where the term is written without one."""
    words = _words(term)
    plural = "" if words[-1].lower().endswith("s") else "s?"
    return r"[\s-]+".join(re.escape(word) for word in words) + plural


@dataclass(frozen=True)
class _Vocabulary:
    """What the entries come to: the terms to use, the terms to avoid with the term each
    gives way to, and the terms the entries disagree about."""

    use: dict[str, str]
    avoid: dict[str, tuple[str, str]]  # key -> (the term as the entry writes it, the term to use)
    conflicts: tuple[str, ...]

    def named(self, found: str) -> str | None:
        """The key of the term these words are, the plural folded where the term has none."""
        key = _key(found)
        if key in self.use or key in self.avoid:
            return key
        if key.endswith("s") and (key[:-1] in self.use or key[:-1] in self.avoid):
            return key[:-1]
        return None


def _vocabulary(entries: Iterable[dict]) -> _Vocabulary:
    use: dict[str, str] = {}
    avoid: dict[str, tuple[str, str]] = {}
    disputed: dict[str, str] = {}
    for entry in entries:
        chosen = str(entry["use"])
        if not _key(chosen):
            continue
        use.setdefault(_key(chosen), chosen)
        for term in entry["avoid"]:
            key = _key(str(term))
            if not key:
                continue
            before = avoid.setdefault(key, (str(term), chosen))
            if _key(before[1]) != _key(chosen):
                disputed[key] = (
                    f"{before[0]!r} is to give way to {before[1]!r} and to {chosen!r}"
                )
    for key in sorted(set(use) & set(avoid)):
        disputed[key] = f"{use[key]!r} is a term to use and a term to avoid"
    for key in disputed:
        avoid.pop(key, None)
    return _Vocabulary(use, avoid, tuple(disputed[key] for key in sorted(disputed)))


def _pattern(vocabulary: _Vocabulary) -> re.Pattern[str] | None:
    """Every term, to use or to avoid, the longest first: "adverse drug reaction" is read
    before the "drug reaction" inside it, so a term to avoid that is part of the term to
    use is not found there."""
    terms = [*vocabulary.use.values(), *(written for written, _ in vocabulary.avoid.values())]
    if not vocabulary.avoid:
        return None
    shapes = sorted({_shape(term) for term in terms}, key=lambda shape: (-len(shape), shape))
    return re.compile(r"(?<!\w)(?:" + "|".join(shapes) + r")(?!\w)", re.IGNORECASE)


def judge_vocabulary(
    passages: Iterable[Passage], entries: Iterable[dict], paper: Path
) -> Report:
    """The findings: each term to avoid that the manuscript uses, and each term the
    entries disagree about. `paper` is the file the entries are in, for the second kind."""
    vocabulary = _vocabulary(entries)
    findings = [
        Finding(
            gate=GATE,
            code="vocabulary-conflict",
            severity=WARN,
            message=conflict,
            path=paper,
            hint="under `language: vocabulary:` a term is either used or avoided, and "
            "avoided for one term only; it is not looked for until the entries agree",
        )
        for conflict in vocabulary.conflicts
    ]

    pattern = _pattern(vocabulary)
    first: dict[str, tuple[Passage, int, int]] = {}
    times: dict[str, int] = {}
    for passage in passages if pattern is not None else ():
        printed = _QUOTED.sub(lambda quoted: " " * len(quoted.group(0)), passage.printed)
        for found in pattern.finditer(printed):
            key = vocabulary.named(found.group(0))
            if key is None or key not in vocabulary.avoid:
                continue
            times[key] = times.get(key, 0) + 1
            first.setdefault(key, (passage, found.start(), len(found.group(0))))

    for key, (passage, offset, length) in first.items():
        written, chosen = vocabulary.avoid[key]
        count = "once" if times[key] == 1 else f"{times[key]} times"
        findings.append(
            Finding(
                gate=GATE,
                code="term-avoided",
                severity=WARN,
                message=f"{written!r} is used {count}; this paper's term is {chosen!r}",
                path=passage.path,
                line=passage.line_of(offset),
                context=context(passage.text, offset, length),
                hint="keep to one term for one thing, or change the entry under `language: "
                "vocabulary:` in paper.yaml if these are two things",
            )
        )

    return Report(
        tuple(findings),
        {"vocabulary_terms": len(vocabulary.avoid), "vocabulary_found": len(first)},
    )
