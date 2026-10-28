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

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.notation import UNITS
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.reader import bound_files

GATE = "G2"

#: What may stand between a binding and its unit: spaces of any width, pandoc's escaped
#: space and the entity of a no-break one, an HTML comment, which is not printed, and one
#: line break, which pandoc prints as a space (round 1 of #279).
_SPACE = (
    r"(?:[ \t\u00a0\u2009\u202f\N{HAIR SPACE}\N{FIGURE SPACE}]"
    r"|\\ |&nbsp;|&NonBreakingSpace;|&#0*160;|&#[xX]0*[aA]0;"
    # A comment ends at its own "-->" and at a blank line, so that no unit is read across
    # the text between two comments, and adjacent ones cannot be split two ways (round 1
    # of #341).
    r"|<!--(?:(?!-->)(?!\n[ \t]*\n)[\s\S])*-->)"
)
_GAP = rf"{_SPACE}*(?:\r?\n{_SPACE}*)?"
_SYMBOLS = (*UNITS, "%", "\u2030")
_SYMBOL = "|".join(sorted(map(re.escape, _SYMBOLS), key=len, reverse=True))
#: A power as it is typed: cm2, with a superscript two, cm^2^, s-1, kg with a superscript
#: minus one.
_SUPERSCRIPTS = r"[\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}]"
_POWER = rf"(?:\N{{SUPERSCRIPT MINUS}}?{_SUPERSCRIPTS}|\^?[-\N{{MINUS SIGN}}]?[123]\^?)?"
_NEGATIVE = rf"(?:\N{{SUPERSCRIPT MINUS}}{_SUPERSCRIPTS}|\^?[-\N{{MINUS SIGN}}][123]\^?)"
#: What divides after a space, with a power below nought: the symbols, and the one-letter
#: ones G14 leaves out, which a power below nought tells from a word: "mg L-1", "µg m-3",
#: "mg kg-1 d-1".
_DIVISOR = "|".join(sorted((*map(re.escape, UNITS), "L", "l", "m", "s", "d", "day"),
                           key=len, reverse=True))  # fmt: skip
_SPACED = (
    r"(?:[ \N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE}](?:" + _DIVISOR + r")"
    + _NEGATIVE + r"(?![\w\N{DEGREE SIGN}]))*"
)
#: A unit as written after a number: a symbol and its power; after a space, a divisor with
#: its power below nought, "mg kg-1", read as "mg/kg"; and after a slash whatever letters
#: follow, since "mmol/L" divides by a litre the list of symbols leaves out.
_UNIT = re.compile(
    _GAP + r"(?P<unit>(?:" + _SYMBOL + r")" + _POWER + _SPACED
    + r"(?:/[^\W\d_]+" + _POWER
    + r")*)(?![\w\u00b0])"
)
#: Spellings of one unit, each to the one it is compared as.
_SAME = {
    "\u03bcg": "\u00b5g", "mcg": "\u00b5g", "ml": "mL", "dl": "dL",
    "\u03bcL": "\u00b5L", "\u00b5l": "\u00b5L", "\u03bcl": "\u00b5L",
    "\u03bcm": "\u00b5m", "\u03bcmol": "\u00b5mol", "\u03bcM": "\u00b5M", "\u03bcSv": "\u00b5Sv",
    "\u00baC": "\u00b0C", "\u2103": "\u00b0C", "\u00baF": "\u00b0F",
    "\u2212": "-", "\u00b2": "2", "\u00b3": "3", "^": "",
    "\N{SUPERSCRIPT MINUS}": "-", "\N{SUPERSCRIPT ONE}": "1",
}  # fmt: skip
#: A divisor after a space, as `_canonical` reads it once its signs are spelt alike: the
#: symbol and the power below nought, "kg-1" in "mg kg-1".
_SPACED_DIVISOR = re.compile(r"\s+([^\W\d_]+)-([123])")
#: A litre after a slash is one litre however it is cased: mmol/l is mmol/L.
_PER_LITRE = re.compile(r"/l(?![^\W\d_])")
_ONE_SYMBOL = re.compile(_SYMBOL)


@dataclass(frozen=True)
class Written:
    """A unit written after a binding: the key, where the binding starts, and the unit."""

    key: str
    start: int
    unit: str


def units_after(text: str, typed: str | None = None) -> list[Written]:
    """The unit symbol written right after each results binding of `text`, where one is.

    `typed` is a LaTeX file as typed, where `text` is its Markdown view. A unit is read there
    only where nothing but spaces stands between it and the binding and inside it no command
    or maths: `\\mg{results.dose}~$\\mu$g` prints µg, and its view reads "g", since the reader
    blanks `\\mu`. Such a unit is not compared."""
    found = []
    for placeholder in parse(text)[0]:
        if placeholder.namespace != "results":
            continue
        after = _UNIT.match(text, placeholder.end)
        if after is None:
            continue
        if typed is not None and _BLANKED.search(typed, placeholder.end, after.end()):
            continue
        found.append(Written(placeholder.key, placeholder.start, after["unit"]))
    return found


#: What the LaTeX reader blanks between a binding and a unit, or inside one, so that what
#: the view reads there is not what LaTeX prints: a command other than a space's, maths, or
#: a brace.
_BLANKED = re.compile(r"\\(?!(?:thinspace|nobreakspace|enspace)(?![A-Za-z]))[A-Za-z@]+|[${}]")


def same_unit(written: str, emitted: str) -> bool | None:
    """Whether two units are one, None where the emitted one is no unit of symbols.

    An emitted unit is read with its spaces one space each, so that "mg kg-1" divides by
    the kilogram, and where so it is none, with no space at all, as "mg / kg" is "mg/kg"."""
    spaced = " ".join(emitted.split())
    emitted = spaced if _UNIT.fullmatch(spaced) else "".join(emitted.split())
    if not _UNIT.fullmatch(emitted):
        return None
    return _canonical(written) == _canonical(emitted)


def _canonical(unit: str) -> str:
    """A unit spelt as the one it is compared as: one spelling of each symbol and power,
    and a divisor after a space, "mg kg-1", after a slash, "mg/kg"."""
    out = unit
    for spelt, one in sorted(_SAME.items(), key=lambda pair: len(pair[0]), reverse=True):
        out = out.replace(spelt, one)
    out = _SPACED_DIVISOR.sub(
        lambda divisor: "/" + divisor[1] + ("" if divisor[2] == "1" else divisor[2]), out
    )
    return _PER_LITRE.sub("/L", out)


def check_bound_units(project: Project, results: Results) -> Report:
    """A warning for each binding followed by a unit other than the one emitted."""
    report = Report()
    for bound in bound_files(project):
        path, text = bound.path, bound.view
        for written in units_after(text, bound.text if bound.latex else None):
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
