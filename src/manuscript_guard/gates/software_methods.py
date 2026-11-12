"""G12 — each package the analysis uses, named in the Methods and cited there.

The plan's Software section says which packages the analysis was to use, and G12 holds it
to the scripts (`gates/software.py`). A reader of the paper sees neither: the Methods are
where the software is named, and a package is credited, and its version found again, through
the reference its authors ask users to cite. So each package used is held to the Methods:

* a package is used when an item of the plan's Software section names it and a script of
  `analysis/` or `figures/` loads it, or the emitter's `software()` recorded it, as G12
  reads the two; base R, Python's standard library, the project's own modules, the
  toolkit's emitters and the language itself (`R`, `Python`) are left out;
* `software-unnamed`: no sentence of the Methods names it. The Methods are the main
  text's Methods section with its subsections and the Methods of the supplement, as G9
  reads them (`gates/methods.py`), in Markdown or in a LaTeX document's printed view;
* `software-uncited`: sentences name it, and none of them carries a citation, read as G6
  reads the citation of an appeal to authority (`gates/writing.py`, `citation_starts`): a
  pandoc citation, a LaTeX citation command, or one typed as text, "[12]" or "(Smith et
  al., 2020)".

Both are warnings at every stage and never fail. One sentence that names the package and
cites is enough, wherever it stands in the Methods. A package named in backticks under the
plan's Deviations is not held to the Methods, as G12 does not hold it to the scripts.

A name is found as a word, in prose and in a code span alike. An R package is matched with
its case, as R loads it: `Matrix` is not `matrix`. A Python package is matched in any case,
"Matplotlib" or "NumPy" as authors write them, and with `-`, `_` and `.` taken for one
another, as PyPI compares distribution names (PEP 503). Its names are those its item gives
and those the scripts import it by, so that `scikit-learn` and `sklearn` both name a
package whose item gives both.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.software import (
    INTERPRETERS,
    PYTHON,
    Load,
    Planned,
    R,
    _given,
    _item_loaded,
    _loads_in,
    _norm,
    code_of,
    deviation_names,
    own_modules,
    planned_packages,
    recorded,
    scripts,
)
from manuscript_guard.text.comments import comment_spans
from manuscript_guard.text.masking import mask

GATE = "G12"
#: The longest stretch of a sentence a finding quotes.
_CONTEXT = 200


@dataclass(frozen=True)
class Used:
    """A package the analysis uses: the item of the plan that names it, and each name it may
    be named by in the Methods, with the language whose rule matches that name."""

    item: Planned
    spellings: tuple[tuple[str, str], ...]


# ----------------------------------------------------------------- what the analysis uses


def used_packages(text: str, read: dict[str, str], emitted: Iterable[str],
                  own: frozenset[str]) -> list[Used]:  # fmt: skip
    """The packages the analysis uses, in the order of the plan's items: an item of its
    Software section the plan means to use, which a script loads or the emitter recorded,
    and which is nobody's choice in neither language, nor named under the Deviations."""
    planned = planned_packages(text)
    if not planned:
        return []
    codes = {relative: code_of(relative, script) for relative, script in sorted(read.items())}
    languages = {language for code in codes.values() for language, lines in code.items()
                 if lines.strip()}  # fmt: skip
    loads = [load for relative, code in codes.items() for load in _loads_in(relative, code)]
    chosen = [load for load in loads if not _given(load, own)]
    loaded = {(load.language, _norm(load.name)) for load in loads}
    picked = {(load.language, _norm(load.name)) for load in chosen}
    made = {_norm(name) for name in emitted}
    deviations = deviation_names(text)
    found = []
    for item in planned:
        if not item.used or any(_norm(name) in deviations for name in item.names):
            continue
        if not _item_loaded(item, loaded, picked, made, languages):
            continue
        spellings = _spellings(item, chosen, made, languages, own)
        if spellings:
            found.append(Used(item, spellings))
    return found


def _spellings(item: Planned, chosen: list[Load], made: set[str], languages: set[str],
               own: frozenset[str]) -> tuple[tuple[str, str], ...]:  # fmt: skip
    """The names an item's package may be named by, each with its language: in R, the names
    the item gives and those R loads it by; in Python, the item's names and those Python
    imports it by. A package only the emitter recorded is of the language of the scripts
    read, Python where both are. None for the language itself, nor for a package nobody
    chooses."""
    whole = {_norm(name) for name in item.names}
    keys = whole | {_norm(name.split(".")[0]) for name in item.names}
    spelled: list[tuple[str, str]] = []
    for load in chosen:
        if load.language == R and _norm(load.name) in whole:
            spelled.append((R, load.name))
        elif load.language == PYTHON and _norm(load.name) in keys:
            spelled.append((PYTHON, load.name))
    found = {language for language, _name in spelled}
    if not found and whole & made:
        first = item.names[0]
        if _norm(first) in INTERPRETERS:
            return ()
        language = R if R in languages and PYTHON not in languages else PYTHON
        if _given(Load(first if language == R else first.split(".")[0], language, None), own):
            return ()
        found = {language}
    spelled = [(language, name) for language in sorted(found) for name in item.names] + spelled
    return tuple(dict.fromkeys(spelled))


# ------------------------------------------------------------------- reading the Methods


@lru_cache(maxsize=512)
def _finder(language: str, spelling: str) -> re.Pattern[str]:
    """A package's name as a word. In R with its case, a point inside it and a hyphen after
    it ("dplyr-based"); in Python in any case, `-`, `_` and `.` for one another, and a
    module after a point (`statsmodels.api`), where a hyphen after it makes another name
    (`pandas-datareader`)."""
    if language == R:
        return re.compile(rf"(?<![\w.]){re.escape(spelling)}(?!\w|\.\w)")
    parts = [re.escape(part) for part in re.split(r"[-_.]", spelling) if part]
    return re.compile(rf"(?<![\w.\-]){'[-_.]'.join(parts)}(?!\w|-\w)", re.IGNORECASE)


def _parts(main: str | None, supplement: Sequence[str]) -> list[str]:
    """The texts of the Methods read: the main text's, then each of the supplement's."""
    return ([main] if main is not None else []) + list(supplement)


def _sentences(text: str) -> list[int]:
    """Where the sentences of a Markdown text are cut, as the claims are read
    (`claims.sentence_spans`), with its start and its end: a sentence runs from one cut to
    the next, and a stretch with no letter of prose, an item that is only a code span, is
    one of its own."""
    from manuscript_guard.claims import sentence_spans

    cuts = {0, len(text)}
    for start, _first, end in sentence_spans(text):
        cuts.update((start, end))
    return sorted(cuts)


@dataclass(frozen=True)
class _Read:
    """One text of the Methods as it is searched: what prints, with code spans kept and
    comments, bindings and citations blanked; where its sentences are cut; and where each of
    its citations starts, outside its comments."""

    text: str
    printed: str
    cuts: list[int]
    cited: list[int]


def _read(text: str) -> _Read:
    from manuscript_guard.gates.writing import citation_starts

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    comments = comment_spans(text)
    cited = [at for at in citation_starts(text)
             if not any(start <= at < end for start, end in comments)]  # fmt: skip
    return _Read(text, mask(text), _sentences(text), sorted(cited))


def _naming(read: _Read, used: Used) -> list[tuple[int, int, bool]]:
    """Each sentence of one text that names the package, as its start, its end and whether
    it carries a citation, in the order of the text."""
    from bisect import bisect_right

    found: dict[tuple[int, int], bool] = {}
    for language, spelling in used.spellings:
        for match in _finder(language, spelling).finditer(read.printed):
            at = bisect_right(read.cuts, match.start()) - 1
            low, high = read.cuts[at], read.cuts[min(at + 1, len(read.cuts) - 1)]
            found[(low, high)] = any(low <= cite < high for cite in read.cited)
    return [(low, high, cited) for (low, high), cited in sorted(found.items())]


# ------------------------------------------------------------------------------ the check


def check_software_cited(project: Project, results: Results | None) -> Report:
    """G12: each package the analysis uses, named in the Methods and cited there. Nothing
    where there is no plan, no package is used, or the paper has no Methods to read."""
    from manuscript_guard.gates.design import _read_plan, plan_path
    from manuscript_guard.gates.methods import main_methods, supplementary_methods

    path = plan_path(project)
    if not path.is_file():
        return Report()
    text, _unreadable = _read_plan(path)
    read = scripts(project)
    used = used_packages(text, read, recorded(results), own_modules(project.root, read))
    if not used:
        return Report()
    supplement = [methods for _path, methods in supplementary_methods(project)]
    return judge_cited(project.root, used, main_methods(project), supplement)


def judge_named(root: Path, text: str, read: dict[str, str], emitted: Iterable[str],
                own: frozenset[str], main: str | None,
                supplement: Sequence[str]) -> Report:  # fmt: skip
    """What G12 says of the Methods, `main` the main text's and `supplement` each of the
    supplement's, against the packages the plan `text` names and the scripts in `read` (by
    their paths from `root`) load or the emitter recorded under `emitted`."""
    return judge_cited(root, used_packages(text, read, emitted, own), main, supplement)


def judge_cited(root: Path, used: list[Used], main: str | None,
                supplement: Sequence[str]) -> Report:  # fmt: skip
    from manuscript_guard.gates.design import PLAN

    parts = [_read(part) for part in _parts(main, supplement)]
    if not parts:
        return Report()
    findings = []
    for package in used:
        naming = [(part, low, high, cited) for part in parts
                  for low, high, cited in _naming(part, package)]  # fmt: skip
        if any(cited for *_where, cited in naming):
            continue
        name = package.item.names[0]
        citing = _how_to_cite(package, name)
        if not naming:
            findings.append(Finding(
                GATE, "software-unnamed",
                f"the analysis uses {name}, and the Methods do not name it",
                severity=WARN, path=root / PLAN, line=package.item.line,
                hint=f"name it in the Methods, in the sentence that says what it did, and "
                f"cite there {citing}; the supplement's Methods count. If it is left out on "
                f"purpose, say why under Deviations from the plan, naming it in backticks, "
                f"`{name}`",
            ))  # fmt: skip
            continue
        part, low, high, _cited = naming[0]
        findings.append(Finding(
            GATE, "software-uncited",
            f"the Methods name {name}, and no sentence that names it cites anything",
            severity=WARN, path=root / PLAN, line=package.item.line,
            context=" ".join(part.text[low:high].split())[:_CONTEXT],
            hint=f"in a sentence that names it, cite {citing}: a citation in the sentence "
            "before or after is read as that sentence's",
        ))  # fmt: skip
    return Report(tuple(findings))


def _how_to_cite(package: Used, name: str) -> str:
    """What to cite for a package, and where its authors say it."""
    if any(language == R for language, _spelling in package.spellings):
        return f'the reference its authors ask for, which `citation("{name}")` prints in R'
    return "the reference its authors ask for, which its documentation gives"


__all__ = ["check_software_cited", "judge_cited", "judge_named", "used_packages"]
