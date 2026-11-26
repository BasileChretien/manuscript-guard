"""G9: an analysis the Results name that the Methods never name.

A reader meets a test in the Results, "the proportions differed (Fisher's exact test)", turns
to the Methods to learn what it is, what it was used for and why it suits the data, and finds
nothing. Neither the checks of the Methods against the code (G9's ledger, G15's models) nor
the review of numbers sees it: the code may have run the test, and the number is bound. On a
real manuscript, read by a panel that checked numbers, consistency and claims for 29 rounds,
a reader without statistical training was the first to see it.

So each method of `data/statistical_methods.yaml` that the Results name, the main text's or
the supplement's, is looked for in the Methods, the main text's or the supplement's, under
any of its names. Where none of them stands there, a warning at the first place the Results
name it (`analysis-not-in-methods`), at every stage. The text is read as a reader reads it
(`claims.readable`): not in a binding, a citation, a comment or code.

The sections are found as G8 finds them (`reported.Walk.parts`): the Methods and the Results
where the paper reports, a Results heading under the Methods being the Methods', and in a
file of the supplement the innermost heading that names its Methods or its Results
(`reported.supplement_parts`). A paper with no Methods section, or none of its Results, is
not read: G4 says the section a journal requires and the paper lacks. The Abstract, the
Introduction and the Discussion are not read either, since they name the methods of other
studies as well as their own.

It reads names from a list, so it says nothing of a method the list does not hold, and a
Methods that names a method only to say it was not used counts as naming it. DESIGN.md's
Known gaps carries both.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard import claims
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.gates.reported import Walk, _methods_or_results, supplement_parts
from manuscript_guard.text.sections import scannable, split_sections

GATE = "G9"
CODE = "analysis-not-in-methods"
DATA = Path(__file__).parent.parent / "data" / "statistical_methods.yaml"

#: What may stand between two words of a name: a space, a hyphen, an en dash or a line
#: break, one or more, as "chi squared", "chi-squared", "Mann--Whitney" and "Mann–Whitney".
_JOIN = r"[\s\-\N{EN DASH}\N{HYPHEN}\N{NON-BREAKING HYPHEN}]+"
#: How a name of the list is cut into its words.
_WORDS = re.compile(r"[ \-\N{EN DASH}]+")
#: A name in capitals alone, matched as written: "ANOVA", "GEE".
_CAPITALS = re.compile(r"[A-Z]{2,}")
#: The parts of the paper a method is looked for in.
METHODS, RESULTS = "methods", "results"


@dataclass(frozen=True)
class Method:
    """A method of the list: its id, the name a warning gives it, and what finds its names."""

    id: str
    name: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Named:
    """A method named in the Methods or the Results: the method's id, the file and the line
    it is named on, its offset in the text read, the words as typed, and the part."""

    method: str
    path: Path
    line: int
    at: int
    words: str
    part: str


@lru_cache(maxsize=1)
def methods() -> tuple[Method, ...]:
    """The methods of `data/statistical_methods.yaml`, in its order."""
    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return tuple(Method(entry["id"], entry["name"], pattern(entry["names"]))
                 for entry in data["methods"])  # fmt: skip


def pattern(names: Iterable[str]) -> re.Pattern[str]:
    """What finds any of `names` as the list says a name is read: whole words, in any case
    but a name in capitals alone, its words joined by `_JOIN`, an "'s" that ends a word there
    or not, and an "s" or "es" after its last word."""
    folded: list[str] = []
    exact: list[str] = []
    for name in names:
        body = _JOIN.join(_word(word) for word in _WORDS.split(name)) + "(?:e?s)?"
        (exact if _CAPITALS.fullmatch(name) else folded).append(body)
    choices = ([f"(?i:{'|'.join(folded)})"] if folded else []) + exact
    return re.compile(rf"(?<!\w)(?:{'|'.join(choices)})(?!\w)")


def _word(word: str) -> str:
    """One word of a name, an "'s" at its end there or not ("Fisher's", "Fisher")."""
    if word.endswith("'s"):
        return re.escape(word[:-2]) + "(?:'s|s')?"
    return re.escape(word)


def named_in(text: str, starts: list[int], kinds: list[str | None]
             ) -> list[tuple[str, int, int, str, str]]:  # fmt: skip
    """Each name of a method that `text` holds in its Methods or its Results, in order: the
    method's id, the line, the offset, the words as typed, and the part. `starts` and `kinds`
    are the line each heading starts on and what the text under it is, as `Walk.parts` and
    `supplement_parts` give them. `text` is a Markdown file or a LaTeX document's printed
    view."""
    read = claims.readable(text)
    breaks = [found.start() for found in re.finditer("\n", text)]
    found = []
    for method in methods():
        for match in method.pattern.finditer(read):
            line = bisect_right(breaks, match.start() - 1) + 1
            part = kinds[bisect_right(starts, line) - 1]
            if part in (METHODS, RESULTS):
                found.append((method.id, line, match.start(), text[match.start():match.end()],
                              part))  # fmt: skip
    return sorted(found, key=lambda one: one[2])


def paper_parts(text: str, walk: Walk) -> tuple[list[int], list[str | None]]:
    """`Walk.parts` of one file of the paper, under the headings `walk` carries into it."""
    return walk.parts([section for section in split_sections(scannable(text)) if section.level])


def supplement_kinds(text: str) -> tuple[list[int], list[str | None]]:
    """What each part of one file of the supplement is, its Methods or its Results."""
    return supplement_parts(text, _methods_or_results)


def named(project: Project) -> tuple[list[Named], bool, bool]:
    """Each method named in the Methods or the Results of the manuscript, in the order the
    files print, the supplement's last; and whether the paper has a Methods section and a
    Results section at all, the main text's or the supplement's."""
    from manuscript_guard.gates.journal import abstract_title, box_rules_of
    from manuscript_guard.text.reader import LATEX, manuscript_format

    root = project.path("manuscript")
    walk = Walk(abstract_title(project), box_rules_of(project))
    if manuscript_format(root) == LATEX:
        return _latex_named(root, walk)
    sources = source_files(root)
    supplement = [path for path in sources if is_supplementary(root, path)]
    paper = printed_order([path for path in sources if path not in supplement],
                          supplementary=False)  # fmt: skip
    found: list[Named] = []
    seen: set[str | None] = set()
    for path in [*paper, *supplement]:
        text = read_text(path)
        starts, kinds = supplement_kinds(text) if path in supplement else paper_parts(text, walk)
        seen.update(kinds)
        found += [Named(method, path, line, at, words, part)
                  for method, line, at, words, part in named_in(text, starts, kinds)]  # fmt: skip
    return found, METHODS in seen, RESULTS in seen


def _latex_named(root: Path, walk: Walk) -> tuple[list[Named], bool, bool]:
    """`named` of a LaTeX manuscript, read in each document's printed view, each name placed
    at the `.tex` file and line it stands on, as G8 places a summary's binding."""
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.latex.structure import ENTRY, read_document

    found: list[Named] = []
    seen: set[str | None] = set()
    for supplementary in (False, True):
        sources = [source for source in read_document(root, supplementary=supplementary).sources
                   if not source.loose and not source.path.lower().endswith(".sty")]  # fmt: skip
        view = printed(sources)
        parts = supplement_kinds if supplementary else (lambda text: paper_parts(text, walk))
        starts, kinds = parts(view.text)
        seen.update(kinds)
        for method, line, at, words, part in named_in(view.text, starts, kinds):
            where = view.place(at)
            path, placed = (where[0].path, where[1]) if where else (ENTRY, line)
            found.append(Named(method, root / path, placed, at, words, part))
    return found, METHODS in seen, RESULTS in seen


def unnamed_in_methods(found: list[Named]) -> list[tuple[Named, int]]:
    """For each method the Results name and the Methods never do, where the Results first
    name it and how many times they do, in the order of the list."""
    in_methods = {one.method for one in found if one.part == METHODS}
    first: dict[str, Named] = {}
    times: dict[str, int] = {}
    for one in found:
        if one.part == RESULTS and one.method not in in_methods:
            first.setdefault(one.method, one)
            times[one.method] = times.get(one.method, 0) + 1
    order = {method.id: at for at, method in enumerate(methods())}
    return [(first[method], times[method]) for method in sorted(first, key=order.__getitem__)]


def check_analyses_named(project: Project) -> Report:
    """A warning for each method the Results name that the Methods never name, where the
    paper has both."""
    found, has_methods, has_results = named(project)
    report = Report()
    if not (has_methods and has_results):
        return report
    names = {method.id: method.name for method in methods()}
    for one, times in unnamed_in_methods(found):
        more = f", and {times - 1} more time{'s' if times > 2 else ''} after" if times > 1 else ""
        report = report.with_findings(Finding(
            gate=GATE, code=CODE, severity=WARN, path=one.path, line=one.line,
            message=f"the Results name {names[one.method]} ({one.words!r} here{more}), and "
            "the Methods never do",
            context=" ".join(one.words.split()),
            hint="say in the Methods what it is, what it was used for and why it suits these "
            "data, in a sentence a reader without statistical training can follow (the "
            "methods-writer skill); where the Methods name it in other words, give it one "
            "name in both",
            subject=one.method, at=one.at,
        ))  # fmt: skip
    return report

