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
from manuscript_guard.text.masking import NUL

GATE = "G14"

# What separates the words of a term as an entry writes it, and as a match is read back:
# white space, a hyphen, and the marks of emphasis, which print as nothing.
_BETWEEN = re.compile(r"[\s*_-]+")
# What may stand between two words of a term in the manuscript: one hyphen, or blanks, or
# one line break with its indentation, each with marks of emphasis beside it, so that
# "_in vitro_ fertilisation" is the term. Not `[\s-]+`: that read a term across a blank
# line, from a heading into its paragraph, from one list item to the next and over a dash.
_JOINT = r"[*_]{0,3}(?:-|[^\S\n]+|[^\S\n]*\n[^\S\n]*)[*_]{0,3}"
# A term starts and ends where a word does. The underscore is no part of a word here,
# though `\w` takes it for one: `_subjects_` is the word in italics.
_BEFORE = r"(?<![^\W_])"
_AFTER = r"(?![^\W_])"
# A line of a quotation set as a block. Its words are somebody else's.
_QUOTE_LINE = re.compile(r"[ ]{0,3}>")


@dataclass(frozen=True)
class Passage:
    """One manuscript file as this reading takes it: `printed` is the text with everything
    that is not a sentence or a heading replaced by NUL, offsets and line breaks kept. NUL
    and not a space, so that two words with a listing or a binding between them are not
    read as standing side by side."""

    path: Path
    text: str
    printed: str
    line_of: Callable[[int], int]


def context(text: str, offset: int, length: int) -> str:
    """The words around a finding, on one line."""
    left = max(0, offset - 40)
    return re.sub(r"\s+", " ", text[left : offset + length + 40]).strip()


def capitals_together(form: str) -> bool:
    """Two capitals side by side: how a word reads as an abbreviation, here and in the
    abbreviation reading."""
    return any(a.isupper() and b.isupper() for a, b in zip(form, form[1:], strict=False))


def _words(term: str) -> list[str]:
    return [word for word in _BETWEEN.split(term.strip()) if word]


def _key(term: str) -> str:
    """A term as it is compared: one space between its words, and lower case unless it is
    written with two capitals together. `OR`, `WHO` and `US` are abbreviations and are
    matched as written; in any case, they were the words "or", "who" and "us"."""
    joined = " ".join(_words(term))
    return joined if capitals_together(joined) else joined.lower()


def _found_as(key: str) -> tuple[str, ...]:
    """The forms a term is found in: itself, and its plural where it is written without
    one."""
    return (key,) if key.endswith("s") else (key, key + "s")


def _shape(term: str) -> str:
    """The pattern a term is found by: its words with `_JOINT` between them, the plural
    `s` where the term is written without one, and any case unless the term is an
    abbreviation."""
    words = _words(term)
    plural = "" if words[-1].endswith("s") else "s?"
    body = _JOINT.join(re.escape(word) for word in words) + plural
    return body if capitals_together(" ".join(words)) else f"(?i:{body})"


def _listed(terms: list[str]) -> str:
    quoted = [repr(term) for term in terms]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + " and " + quoted[-1]


@dataclass(frozen=True)
class _Vocabulary:
    """What the entries come to: the terms to use, the terms to avoid with the term each
    gives way to, and what the entries disagree about."""

    use: dict[str, str]
    avoid: dict[str, tuple[str, str]]  # key -> (the term as the entry writes it, the term to use)
    conflicts: tuple[str, ...]

    def named(self, found: str) -> str | None:
        """The key of the term these words are: as written for an abbreviation, in lower
        case for any other, the plural folded where the term has none."""
        written = " ".join(_words(found))
        for key in (written, written.lower()):
            for form in (key, key[:-1] if key.endswith("s") else key):
                if form in self.use or form in self.avoid:
                    return form
        return None


def _vocabulary(entries: Iterable[dict]) -> _Vocabulary:
    use: dict[str, str] = {}
    written: dict[str, str] = {}
    chosen: dict[str, dict[str, str]] = {}  # avoided key -> {key of the term to use: as written}
    for entry in entries:
        kept = str(entry["use"])
        if not _key(kept):
            continue
        use.setdefault(_key(kept), kept)
        for term in entry["avoid"]:
            key = _key(str(term))
            if key:
                written.setdefault(key, str(term))
                chosen.setdefault(key, {}).setdefault(_key(kept), kept)

    # Two terms are one to the reading where a form of one is a form of the other: the
    # same words, or the plural of a term written without one.
    kept_as = {form: key for key in use for form in _found_as(key)}
    given_as: dict[str, str] = {}
    disputed: dict[str, str] = {}
    for key in sorted(written):
        rivals = list(chosen[key].values())
        if len(rivals) > 1:
            disputed[key] = f"{written[key]!r} is to give way to {_listed(rivals)}"
        for form in _found_as(key):
            if form in kept_as:
                kept = use[kept_as[form]]
                disputed[key] = (
                    f"{kept!r} is a term to use and a term to avoid"
                    if kept == written[key]
                    else f"{kept!r} is a term to use and {written[key]!r} a term to avoid, "
                    "and the two are read as one term"
                )
            other = given_as.setdefault(form, key)
            if other != key and set(chosen[other]) != set(chosen[key]):
                both = _listed([written[other], written[key]])
                disputed[key] = disputed[other] = (
                    f"{both} are read as one term, and are given up for different terms"
                )
    avoid = {
        key: (written[key], next(iter(chosen[key].values())))
        for key in written
        if key not in disputed
    }
    return _Vocabulary(use, avoid, tuple(dict.fromkeys(disputed[key] for key in sorted(disputed))))


def _pattern(vocabulary: _Vocabulary) -> re.Pattern[str] | None:
    """Every term, to use or to avoid, in one pattern. The terms to use are in it so that
    a term to avoid is not found inside one: "drug reaction" in "adverse drug reaction" is
    passed over because the longer term has been read from "adverse" on. Longest first,
    for two terms that start at the same word: "liver injury score" kept, "liver injury"
    given up."""
    if not vocabulary.avoid:
        return None
    terms = [*vocabulary.use.values(), *(written for written, _ in vocabulary.avoid.values())]
    shapes = sorted({_shape(term) for term in terms}, key=lambda shape: (-len(shape), shape))
    return re.compile(_BEFORE + "(?:" + "|".join(shapes) + ")" + _AFTER)


def _quotations(printed: str) -> list[tuple[int, int]]:
    """The lines of each block quotation. A line under `>` opens one only after a blank
    line, as pandoc reads it: "ALT" at the end of one line and "> 3 times the limit" on
    the next are one paragraph."""
    spans: list[tuple[int, int]] = []
    offset = 0
    after_blank, after_quoted = True, False
    for line in printed.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        quoted = _QUOTE_LINE.match(body) is not None and (after_blank or after_quoted)
        if quoted:
            spans.append((offset, offset + len(body)))
        after_blank, after_quoted = not body.strip(" \t" + NUL), quoted
        offset += len(line)
    return spans


def _without(printed: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return printed
    chars = list(printed)
    for start, end in spans:
        chars[start:end] = NUL * (end - start)
    return "".join(chars)


def judge_vocabulary(
    passages: Iterable[Passage], entries: Iterable[dict], paper: Path
) -> Report:
    """The findings: each term to avoid that the manuscript uses, and each thing the
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
            "avoided for one term only; a hyphen, a space, a capital and the plural `s` "
            "make no difference between two terms. It is not looked for until the "
            "entries agree",
        )
        for conflict in vocabulary.conflicts
    ]

    pattern = _pattern(vocabulary)
    first: dict[str, tuple[Passage, int, int]] = {}
    times: dict[str, int] = {}
    for passage in passages if pattern is not None else ():
        printed = _without(passage.printed, _quotations(passage.printed))
        for found in pattern.finditer(printed):
            key = vocabulary.named(found.group(0))
            if key is None or key not in vocabulary.avoid:
                continue
            times[key] = times.get(key, 0) + 1
            first.setdefault(key, (passage, found.start(), len(found.group(0))))

    for key, (passage, offset, length) in first.items():
        written, kept = vocabulary.avoid[key]
        count = "once" if times[key] == 1 else f"{times[key]} times"
        findings.append(
            Finding(
                gate=GATE,
                code="term-avoided",
                severity=WARN,
                message=f"{written!r} is used {count}; this paper's term is {kept!r}",
                path=passage.path,
                line=passage.line_of(offset),
                context=context(passage.text, offset, length),
                hint="keep to one term for one thing, or change the entry under `language: "
                "vocabulary:` in paper.yaml if these are two things. This is the first use; "
                "the count is of the whole manuscript",
            )
        )

    return Report(
        tuple(findings),
        {"vocabulary_terms": len(vocabulary.avoid), "vocabulary_found": len(first)},
    )
