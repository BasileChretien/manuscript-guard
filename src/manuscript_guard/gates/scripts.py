"""The gates read English, and say where a manuscript's prose is in a script they do not.

A sentence in Chinese with every result bound still fails G2: Chinese puts no space between
words, so "表1" (Table 1) and "95%置信区间" (95% CI) are read together with the characters
round them, and match no rule. A sentence that writes its numbers in Chinese numerals, "四千",
is not read as holding a number at all. G4 counts words between spaces, where a journal
writing in Chinese counts characters; G6's phrasing and G14's abbreviations, terms and
spelling are lists of English. So a manuscript file whose prose holds Han, Hiragana,
Katakana or Hangul is said to, with how much of it there is and what was not read in it.

It is a warning and never more. An English paper may quote a title, a name or a term in
another script, and those words are right where they stand.
"""

from __future__ import annotations

import re
from collections import Counter

from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.vocabulary import Passage

GATE = "G14"


def _span(low: int, high: int) -> str:
    """A range of a character class, from code point to code point."""
    return f"{chr(low)}-{chr(high)}"


#: The scripts the gates do not read, by the blocks of Unicode that hold them.
SCRIPTS = {
    "Han": _span(0x3400, 0x4DBF) + _span(0x4E00, 0x9FFF) + _span(0xF900, 0xFAFF)
    + _span(0x20000, 0x2EBEF),
    "Hiragana": _span(0x3040, 0x309F),
    "Katakana": _span(0x30A0, 0x30FF) + _span(0x31F0, 0x31FF) + _span(0xFF66, 0xFF9F),
    "Hangul": _span(0x1100, 0x11FF) + _span(0x3130, 0x318F) + _span(0xAC00, 0xD7AF),
}
_ANY = re.compile("[" + "".join(SCRIPTS.values()) + "]")
_EACH = {name: re.compile("[" + span + "]") for name, span in SCRIPTS.items()}

_NOT_READ = (
    "numbers written in its numerals, which are not seen as numbers; figures run into its "
    "characters, which G2 reads together with them and fails even where every result is "
    "bound; the word count, which counts words between spaces; and AI phrasing, "
    "abbreviations, terms and spelling, which are read in English"
)


def scripts_in(text: str) -> Counter[str]:
    """How many characters of each script the gates do not read `text` holds."""
    found: Counter[str] = Counter()
    for match in _ANY.finditer(text):
        character = match.group()
        for name, pattern in _EACH.items():
            if pattern.match(character):
                found[name] += 1
                break
    return found


def judge_scripts(passages: list[Passage]) -> Report:
    """One warning for each file whose prose holds a script the gates do not read."""
    report = Report()
    total = 0
    for passage in passages:
        found = scripts_in(passage.printed)
        if not found:
            continue
        count = sum(found.values())
        total += count
        first = _ANY.search(passage.printed)
        named = ", ".join(f"{name} ({n})" for name, n in sorted(found.items()))
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="script-not-read",
                severity=WARN,
                message=f"{count} character{'' if count == 1 else 's'} of prose in a script "
                f"the gates do not read: {named}. Not checked in them: {_NOT_READ}",
                path=passage.path,
                line=passage.line_of(first.start()) if first else None,
                hint="a quoted title or name in another script is fine where it is; a "
                "manuscript written in it is read by these gates as English",
            )
        )
    return report.with_counts(prose_not_read=total)


__all__ = ["SCRIPTS", "judge_scripts", "scripts_in"]
