"""G2: a unit written after a binding is the unit the analysis emitted.

The analysis records a value's unit (`em.value(key, 250, unit="µg")`), and only G8 read it.
"{{results.dose}} mg" printed "250 mg" of a value emitted in micrograms, and nothing said so.
So the symbol written right after each binding is read, the symbols G14 knows a number is
not to run into and `%` and `‰`, with a power or a "/kg" after it, and compared with the
unit emitted: where they differ, G2 warns (`unit-differs-from-emitted`). Spellings of one
unit are one unit: µg, μg and mcg; mL and ml; °C and ℃. Where the value was emitted with no
unit, or with one that is no symbol ("years"), there is nothing to compare.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.notation import UNITS
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.placeholders import parse

GATE = "G2"

#: What may stand between a binding and its unit: spaces of any width, and one line break,
#: which pandoc prints as a space.
_GAP = r"[ \t\u00a0\u2009\u202f]*(?:\r?\n[ \t\u00a0\u2009\u202f]*)?"
_SYMBOLS = (*UNITS, "%", "\u2030")
_SYMBOL = "|".join(sorted(map(re.escape, _SYMBOLS), key=len, reverse=True))
#: A power as it is typed: cm2, with a superscript two, cm^2^, s-1.
_POWER = r"(?:[\u00b2\u00b3]|\^?[-\u2212]?[123]\^?)?"
#: A unit as written after a number: a symbol and its power, and after a slash whatever
#: letters follow, since "mmol/L" divides by a litre the list of symbols leaves out.
_UNIT = re.compile(
    _GAP + r"(?P<unit>(?:" + _SYMBOL + r")" + _POWER + r"(?:/[^\W\d_]+" + _POWER
    + r")*)(?![\w\u00b0])"
)
#: Spellings of one unit, each to the one it is compared as.
_SAME = {
    "\u03bcg": "\u00b5g", "mcg": "\u00b5g", "ml": "mL", "dl": "dL",
    "\u03bcL": "\u00b5L", "\u00b5l": "\u00b5L", "\u03bcl": "\u00b5L",
    "\u03bcm": "\u00b5m", "\u03bcmol": "\u00b5mol", "\u03bcM": "\u00b5M", "\u03bcSv": "\u00b5Sv",
    "\u00baC": "\u00b0C", "\u2103": "\u00b0C", "\u00baF": "\u00b0F",
    "\u2212": "-", "\u00b2": "2", "\u00b3": "3", "^": "",
}  # fmt: skip
_ONE_SYMBOL = re.compile(_SYMBOL)


@dataclass(frozen=True)
class Written:
    """A unit written after a binding: the key, where the binding starts, and the unit."""

    key: str
    start: int
    unit: str


def units_after(text: str) -> list[Written]:
    """The unit symbol written right after each results binding of `text`, where one is."""
    found = []
    for placeholder in parse(text)[0]:
        if placeholder.namespace != "results":
            continue
        after = _UNIT.match(text, placeholder.end)
        if after is not None:
            found.append(Written(placeholder.key, placeholder.start, after["unit"]))
    return found


def same_unit(written: str, emitted: str) -> bool | None:
    """Whether two units are one, None where the emitted one is no unit of symbols."""
    emitted = "".join(emitted.split())
    if not _UNIT.fullmatch(emitted):
        return None
    return _canonical(written) == _canonical(emitted)


def _canonical(unit: str) -> str:
    out = unit
    for spelt, one in sorted(_SAME.items(), key=lambda pair: len(pair[0]), reverse=True):
        out = out.replace(spelt, one)
    return out


def check_bound_units(project: Project, results: Results) -> Report:
    """A warning for each binding followed by a unit other than the one emitted."""
    report = Report()
    for path in source_files(project.path("manuscript")):
        text = read_text(path)
        for written in units_after(text):
            value = results.values.get(written.key)
            if value is None or not value.unit or same_unit(written.unit, value.unit) in (
                True,
                None,
            ):
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="unit-differs-from-emitted",
                    severity=WARN,
                    message=f"results.{written.key} is followed by {written.unit!r}, and the "
                    f"analysis emitted it in {value.unit!r}",
                    path=path,
                    line=text.count("\n", 0, written.start) + 1,
                    hint="write the unit the value was emitted in, or emit it in the unit the "
                    "text gives; the number is the analysis's either way",
                )
            )
    return report
