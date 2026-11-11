"""The short forms a paper audited uses and does not define, said in one finding.

G14 gives `check` a warning for each abbreviation used and not defined, which a project's
author answers one at a time. Run on 52 real preprints, the audit's were the noisiest it had:
354 of the 427 that judges read were false, the field's own terms, institutions, genes and
instruments, often dozens in one paper, and the true ones were lost among them. So the
audit says them in one finding for the paper (the author's decision, 2026-11-11): the
short forms in the order the paper first uses them, at the first use of the first, with
`--known` as the remedy. Each form keeps the warning G14 gave it, its place, its count and
its quote, which `--json` gives under the finding and `--details` lists.

A form that journals' own style guides say needs no definition
(`data/journal_abbreviations.yaml`) is not listed, and the finding says how many it passed
over and by which list. `check` reads neither: its warnings are G14's, one for each form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.findings import WARN, Finding

#: The code of G14's warning for one short form used and not defined.
CODE = "abbreviation-undefined"
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
class Undefined(Finding):
    """G14's warnings on the short forms a paper uses and does not define, as one finding.
    `forms` holds each warning with its form, in the order the paper first uses the forms;
    `passed_over` the forms on the list of journals' style guides, which are not listed."""

    forms: tuple[tuple[str, Finding], ...] = ()
    passed_over: tuple[str, ...] = ()

    @property
    def counted(self) -> int:
        """How many short forms it lists: each once, though G14 reads the abstract apart."""
        return len({form for form, _warning in self.forms})

    def as_dict(self) -> dict:
        out = {key: value for key, value in super().as_dict().items()
               if key not in ("forms", "passed_over")}  # fmt: skip
        return {**out, **listed(self)}


def listed(finding: Finding) -> dict:
    """What `--json` gives beside the finding: each form with the warning G14 gave it, where
    it is first used, and the forms passed over by the list. Nothing for any other finding."""
    if not isinstance(finding, Undefined):
        return {}
    return {
        "forms": [{"form": form, "message": warning.message,
                   "path": None if warning.path is None else str(warning.path),
                   "line": warning.line, "context": warning.context}
                  for form, warning in finding.forms],
        "passed_over": list(finding.passed_over),
        "passed_over_by": LIST.name,
    }  # fmt: skip


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
    """`found`, G14's findings on one paper audited, with its warnings on the short forms
    used and not defined made one (`Undefined`) where the first of them stood, the forms
    on the list (`exempt`) passed over. A warning whose message is not G14's for one form is
    left as it is. No finding is made where every form is on the list."""
    mine = []
    for finding in found:
        said = _SAID.match(finding.message) if finding.code == CODE else None
        if said and finding.gate == "G14":
            mine.append((said["form"], finding))
    if not mine:
        return list(found)
    mine.sort(key=lambda pair: _at(pair[1]))
    on_list = exempt()
    kept = [(form, finding) for form, finding in mine if form not in on_list]
    passed = list(dict.fromkeys(form for form, _finding in mine if form in on_list))
    taken = {id(finding) for _form, finding in mine}
    first = id(mine[0][1])
    out: list[Finding] = []
    for finding in found:
        if id(finding) not in taken:
            out.append(finding)
        elif id(finding) == first and kept:
            out.append(_made(kept, passed))
    return out


def _at(finding: Finding) -> tuple[str, int, int]:
    """Where a warning stands, to order them: its file, its line, its column."""
    return (str(finding.path or ""), finding.line or 0, finding.col or 0)


def _made(kept: list[tuple[str, Finding]], passed: list[str]) -> Undefined:
    first = kept[0][1]
    return Undefined(gate="G14", code=CODE, message=_message(kept, passed), severity=WARN,
                     path=first.path, line=first.line, col=first.col, context=first.context,
                     hint=HINT, forms=tuple(kept), passed_over=tuple(passed))  # fmt: skip


__all__ = ["CODE", "LIST", "Undefined", "exempt", "listed", "one_finding"]
