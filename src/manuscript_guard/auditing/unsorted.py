"""The entries of a paper's reference list the audit could not sort, said in one note.

An entry with no DOI and no PMID is sorted by its shape (`auditing.by_title`), and one that is
neither an article, a book, a web page nor a legal text is not looked up: a note said so for
each, `reference-not-sorted`. Run on 52 real preprints, the audit gave 1,405 of them on 22
papers, 598 on one and 579 on another, most from a list that runs on into tables. So the
audit says them in one note for the paper (the author's decision 16, 2026-11-14), as it says
the short forms left undefined (#640, `auditing.undefined`) and the names from the code
(#673, `auditing.code_names`): the entries in the list's order, at the place of the first,
each reason said once with its entries. Each entry keeps the note it had and its place,
which `--json` gives under the note. The References line still counts the entries
(`summary`), and the section still lists each one with what it is (`report._unlooked`).

`check` sorts no entry: nothing here is a project's.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from manuscript_guard.auditing.by_title import CODES, UNSORTED
from manuscript_guard.auditing.undefined import gathered

#: The code of the note on an entry not sorted.
CODE = CODES[UNSORTED]
#: The note on one entry, "entry 23: not sorted: ..., so not looked up: check it by hand"
#: (`by_title.said`): the entry's label, then why. `tests/test_audit_unsorted.py` holds that
#: it matches what the report writes.
_SAID = re.compile(r"^(?P<entry>.+?): (?P<why>not sorted: .+): check it by hand$", re.DOTALL)
#: A label of a numbered list, "entry 23", or of one unnumbered, "entry 4 of the list".
_NUMBERED = re.compile(r"^entry (?P<number>\d+)(?P<rest> of the list)?$")


def one_finding(found: list, at: Callable[[Path | None, int | None], str] | None = None
                ) -> list:  # fmt: skip
    """`found`, the report's items on one paper's reference list in the list's order, with
    its notes on the entries not sorted made one where the first stood. Any other item, and
    a note whose message is not the report's for one entry, is left as it is. `at` says
    where an entry stands, "line 12" or a .docx's "References, paragraph 7"
    (`report._title_items`): the note says it of two entries with one label."""
    return gathered(found, _entry, lambda mine: _made(mine, at or _line))


def _line(_path: Path | None, line: int | None) -> str:
    return f"line {line}"


def _entry(item) -> str | None:
    """The entry the note on one entry not sorted names; None for any other item."""
    said = _SAID.match(item.message) if item.code == CODE else None
    return said["entry"] if said else None


def _phrase(parts: list[str]) -> str:
    return ", ".join(parts[:-1]) + f" and {parts[-1]}" if len(parts) > 1 else "".join(parts)


def _named(labels: list[tuple[str, str | None]]) -> str:
    """"entries 3, 7 and 12", "entries 1 and 4 of the list", "entry 2": the labels in their
    order, each run of numbers of one kind said once with them, a run of any other label,
    a LaTeX list's "\\bibitem{key}", label by label, and the runs one after another, "entries
    1, 2 and 5 of the list, then entries 34 and 38" (docx-psych-B2's list, read in part as
    numbered and in part as not). Each label is given with its place where another entry has
    the same label, "entries 2 (line 8) and 2 (line 13)", a list whose numbering starts
    again (round 1 of #679), and with None where it is its own."""
    runs: list[tuple[str | None, list[str]]] = []
    for label, place in labels:
        numbered = _NUMBERED.match(label)
        kind = (numbered["rest"] or "") if numbered else None
        said = (numbered["number"] if numbered else label) + (f" ({place})" if place else "")
        if runs and runs[-1][0] == kind:
            runs[-1][1].append(said)
        else:
            runs.append((kind, [said]))
    return ", then ".join(
        _phrase(said) if kind is None
        else f"entr{'y' if len(said) == 1 else 'ies'} {_phrase(said)}{kind}"
        for kind, said in runs)  # fmt: skip


def _message(mine: list[tuple[str, object]], at: Callable[[Path | None, int | None], str]
             ) -> str:  # fmt: skip
    """"3 entries not sorted: ..., so not looked up: entries 1, 3 and 4 of the list; check
    them by hand": each reason once, with its entries, in the order each is first met, an
    entry whose label another has too with where it stands (`at`)."""
    labelled = Counter(label for label, _item in mine)
    reasons: dict[str, list[tuple[str, str | None]]] = {}
    for label, item in mine:
        place = at(item.path, item.line) if labelled[label] > 1 else None
        reasons.setdefault(_SAID.match(item.message)["why"], []).append((label, place))
    count = len(mine)
    said = "; ".join(f"{why}: {_named(labels)}" for why, labels in reasons.items())
    return (f"{count} entr{'y' if count == 1 else 'ies'} {said}; check "
            f"{'it' if count == 1 else 'them'} by hand")  # fmt: skip


def _made(mine: list[tuple[str, object]],
          at: Callable[[Path | None, int | None], str] = _line):  # fmt: skip
    first = mine[0][1]
    entries = [{"entry": label, "message": item.message,
                "path": None if item.path is None else str(item.path), "line": item.line}
               for label, item in mine]  # fmt: skip
    return replace(first, message=_message(mine, at), listed={"entries": entries})


__all__ = ["CODE", "one_finding"]
