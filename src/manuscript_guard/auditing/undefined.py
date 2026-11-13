"""The short forms a paper audited uses and does not define, said in one finding.

G14 gives `check` a warning for each abbreviation used and not defined, which a project's
author answers one at a time. Run on 52 real preprints, the audit's were the noisiest it had:
354 of the 427 that judges read were false, the field's own terms, institutions, genes and
instruments, often dozens in one paper, and the true ones were lost among them. So the
audit says them in one finding for the paper (the author's decision, 2026-11-11): the
short forms in the order the paper first uses them, at the first use of the first, with
`--known` as the remedy. Each form keeps the warning G14 gave it, its place, its count and
its quote, which `--json` gives under the finding and `--details` lists.

The order is G14's own: it gives its warnings part by part, the Abstract, the main text,
then the supplement, and within each in the order of each form's first use as it reads the
files, the paper's order and then the place in each (`_Mark.key`). So the warnings are taken
in the order G14 gave them, not sorted by path: a LaTeX paper's Discussion, input after its
Methods, sorts first by its file's name (round 1 of #640).

A form that journals' own style guides say needs no definition
(`data/journal_abbreviations.yaml`) is not listed, and the finding says how many it passed
over and by which list; where every form is on it, a note says so (`PASSED`). `check` reads
neither: its warnings are G14's, one for each form.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.findings import INFO, WARN, Finding

#: The code of G14's warning for one short form used and not defined.
CODE = "abbreviation-undefined"
#: The code of the note said where every such form is on the list: nothing to define, and
#: the reader told what was passed over (round 1 of #640).
PASSED = "abbreviations-passed-over"
LIST = Path(__file__).resolve().parent.parent / "data" / "journal_abbreviations.yaml"
#: The scopes G14 reads apart, as its messages name them (`gates.language`).
_SCOPES = ("abstract", "main text", "supplement")
#: G14's message for one form, "HIV is used 2 times in the main text as G14 reads it, and
#: not defined there": the form and the part it is used in. `tests/test_audit_undefined.py`
#: holds that it matches what the gate writes.
_SAID = re.compile(r"^(?P<form>\S+) is used (?:once|\d+ times) in the "
                   rf"(?P<scope>{'|'.join(_SCOPES)}) as G14 reads it, and not defined there")
#: What the finding asks for, in the audit's own words (`auditing.gates.KNOWN`).
HINT = ("define each at its first use, the long form then the short form in brackets; give "
        "the ones the paper's readers take for words or names to the audit as known words "
        '(on the page, "Words to leave alone"; on the command line, --known)')  # fmt: skip


@dataclass(frozen=True)
class Listed(Finding):
    """G14's warnings of one kind on a paper audited, one for each word, said as one finding:
    `forms` holds each warning with its word, in the order G14 gave them. The short forms
    used and not defined are one (`Undefined`), the names from the code another
    (`auditing.code_names`, decision 13 of 2026-11-13). `each` titles the list of them that
    `--details` gives."""

    forms: tuple[tuple[str, Finding], ...] = ()
    each: str = ""

    @property
    def counted(self) -> int:
        """How many words it lists: each once, though G14 reads the abstract apart; none for
        the note on forms passed over (`PASSED`), which asks nothing."""
        return len({form for form, _warning in self.forms})

    def as_dict(self) -> dict:
        out = {key: value for key, value in super().as_dict().items()
               if key not in ("forms", "passed_over", "each")}  # fmt: skip
        return {**out, **listed(self)}


#: What `--details` titles the short forms' list with.
EACH = "Each short form used and not defined, where it is first used:"


@dataclass(frozen=True)
class Undefined(Listed):
    """G14's warnings on the short forms a paper uses and does not define, as one finding.
    `forms` holds each warning with its form, in the order the paper first uses the forms;
    `passed_over` the forms on the list of journals' style guides, which are not listed."""

    each: str = EACH
    passed_over: tuple[str, ...] = ()


def listed(finding: Finding) -> dict:
    """What `--json` gives beside the finding: each word with the warning G14 gave it and
    where it is first used, and for the short forms the forms passed over by the list.
    Nothing for any other finding."""
    if not isinstance(finding, Listed):
        return {}
    out: dict = {
        "forms": [{"form": form, "message": warning.message,
                   "path": None if warning.path is None else str(warning.path),
                   "line": warning.line, "context": warning.context}
                  for form, warning in finding.forms],
    }  # fmt: skip
    if isinstance(finding, Undefined):
        out |= {"passed_over": list(finding.passed_over), "passed_over_by": LIST.name}
    return out


def gathered(
    found: list[Finding],
    word: Callable[[Finding], str | None],
    made: Callable[[list[tuple[str, Finding]]], Finding],
) -> list[Finding]:
    """`found` with the findings `word` names a word for made one by `made`, where the first
    of them stood, the rest dropped; `made` is given each with its word, in `found`'s order.
    Every other finding is left as it is, and with none named `found` is as it was."""
    mine = [(said, finding) for finding in found if (said := word(finding)) is not None]
    if not mine:
        return list(found)
    taken = {id(finding) for _word, finding in mine}
    first = id(mine[0][1])
    one = made(mine)
    out: list[Finding] = []
    for finding in found:
        if id(finding) not in taken:
            out.append(finding)
        elif id(finding) == first:
            out.append(one)
    return out


@lru_cache(maxsize=1)
def _list() -> tuple[frozenset[str], tuple[str, ...]]:
    """The forms on the list, and the names of its sources."""
    read = yaml.safe_load(LIST.read_text(encoding="utf-8"))
    names = tuple(str(source["name"]) for source in read.get("sources", {}).values())
    return frozenset(str(form) for form in read.get("exempt", {})), names


def exempt() -> frozenset[str]:
    """The short forms journals' style guides say need no definition."""
    return _list()[0]


def _sources() -> str:
    names = _list()[1]
    return ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else "".join(names)


def _phrase(forms: list[str]) -> str:
    return ", ".join(forms[:-1]) + f" and {forms[-1]}" if len(forms) > 1 else "".join(forms)


def _said(form: str, scopes: list[str]) -> str:
    """A form as the list names it: where only the abstract or the supplement leaves it
    undefined, said so, as G14 reads those apart from the main text."""
    if "main text" in scopes:
        return form
    return f"{form} (in the {' and the '.join(scopes)})"


def _message(forms: list[tuple[str, Finding]], passed: list[str]) -> str:
    """"3 short forms are used and not defined as G14 reads the paper: 'XYZ' here, then
    HR (in the abstract), QQQ; 2 more passed over (HIV and MRI), ...": the first quoted, so
    that a comment on the .docx is anchored on it (`auditing.commented.words_of`)."""
    scopes: dict[str, list[str]] = {}
    for form, warning in forms:
        said = _SAID.match(warning.message)
        scopes.setdefault(form, []).append(said["scope"] if said else "main text")
    named = [_said(form, where) for form, where in scopes.items()]
    first = next(iter(scopes))
    count = len(scopes)
    message = (f"{count} short form{'s are' if count != 1 else ' is'} used and not defined "
               f"as G14 reads the paper: '{first}'{named[0][len(first):]} here")  # fmt: skip
    if named[1:]:
        message += ", then " + ", ".join(named[1:])
    if passed:
        message += (f"; {len(passed)} more passed over ({_phrase(passed)}), being on the list "
                    f"of short forms that {_sources()} say need no definition")  # fmt: skip
    return message


def one_finding(found: list[Finding]) -> list[Finding]:
    """`found`, G14's findings on one paper audited in the order G14 gave them, with its
    warnings on the short forms used and not defined made one (`Undefined`) where the first
    of them stood, the forms on the list (`exempt`) passed over. A warning whose message is
    not G14's for one form is left as it is. Where every form is on the list, a note says
    which were passed over (`PASSED`) in their place."""
    return gathered(found, _form, _one)


def _form(finding: Finding) -> str | None:
    """The form G14's warning on one short form used and not defined names; None for any
    other finding."""
    said = _SAID.match(finding.message) if finding.code == CODE else None
    return said["form"] if said and finding.gate == "G14" else None


def _one(mine: list[tuple[str, Finding]]) -> Undefined:
    mine = _ordered(mine)
    on_list = exempt()
    kept = [(form, finding) for form, finding in mine if form not in on_list]
    passed = list(dict.fromkeys(form for form, _finding in mine if form in on_list))
    return _made(kept, passed) if kept else _noted(mine, passed)


def _ordered(mine: list[tuple[str, Finding]]) -> list[tuple[str, Finding]]:
    """G14's warnings in its own reading order, which is the order it gave them: part by
    part, and within each by each form's first use as it reads the files (`_Mark.key`)."""
    return list(mine)


def _made(kept: list[tuple[str, Finding]], passed: list[str]) -> Undefined:
    first = kept[0][1]
    return Undefined(gate="G14", code=CODE, message=_message(kept, passed), severity=WARN,
                     path=first.path, line=first.line, col=first.col, context=first.context,
                     hint=HINT, forms=tuple(kept), passed_over=tuple(passed))  # fmt: skip


def _noted(mine: list[tuple[str, Finding]], passed: list[str]) -> Undefined:
    """The note where every form left undefined is on the list: how many were passed over,
    which, and by which list, at the first use of the first, the first quoted for the copy
    with comments to stand on."""
    first = mine[0][1]
    rest = f", then {_phrase(passed[1:])}" if passed[1:] else ""
    count = len(passed)
    message = (f"{count} short form{'s' if count != 1 else ''} used and not defined "
               f"{'were' if count != 1 else 'was'} passed over: '{passed[0]}' here{rest}, "
               f"being on the list of short forms that {_sources()} say need no definition")
    return Undefined(gate="G14", code=PASSED, message=message, severity=INFO,
                     path=first.path, line=first.line, col=first.col, context=first.context,
                     hint=None, forms=(), passed_over=tuple(passed))  # fmt: skip


__all__ = ["CODE", "EACH", "LIST", "PASSED", "Listed", "Undefined", "exempt", "gathered",
           "listed", "one_finding"]
