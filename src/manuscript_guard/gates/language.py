"""G14 — the manuscript's abbreviations agree with themselves.

Whether "ROR" needs defining is a question about a journal. Whether it *was* defined, where,
how often, and whether anything used it afterwards are questions about the manuscript, and
those have answers that need no style guide. This gate asks only the second kind, which is
why it works the same in any field:

* an abbreviation used before the sentence that defines it;
* one defined twice, or defined as two different things;
* one defined and never used again, so the reader learnt it for nothing;
* one used and never defined.

The last is the one that depends on the reader. "DNA" is a word in a genetics journal and
an abbreviation in a law review, so the list of what may stand undefined is data
(`data/abbreviations.yaml`, kept short) and the project's to extend, under
`language: known_abbreviations:` in `paper.yaml`.

**Every finding is a warning.** A definition is recognised by its shape, a long form with
the short form in brackets after it or the other way round, and the long form is matched to
the short one letter by letter (Schwartz and Hearst, 2003). That reading is good and not
exact: a name in capitals is not an abbreviation, and a definition written as a sentence
("hereafter ROR") is not seen. A check that can be wrong may advise; it may not stop a
build.

Three texts are read apart, because each is read apart. The abstract is indexed and read
without the paper, so what it uses it must define. The main text does not inherit from the
abstract. The supplement is read after the paper, so it inherits the main text's
definitions and is otherwise held to its own. The title page that opens either is not read
for abbreviations at all (`text/title_page.py`): its units and institutions need no
defining.

The gate has three more readings: of the terms the paper keeps to, in
`gates/vocabulary.py`, of its spelling, in `gates/spelling.py`, and of its notation, in
`gates/notation.py`. They take the files read here, so the manuscript is masked once,
and `check_language` gives all four, and says where the prose is in a script none of
them reads (`gates/scripts.py`).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.dictionary import load_dictionary
from manuscript_guard.contracts.project import PAPER_FILE, Project
from manuscript_guard.contracts.results import Results, load_results
from manuscript_guard.corrections import Edit
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates import glossary
from manuscript_guard.gates.code_names import Names, Prose, judge_code_names
from manuscript_guard.gates.notation import judge_notation, notation_edits
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.gates.scripts import judge_scripts
from manuscript_guard.gates.spelling import judge_spelling, opens_a_sentence, spelling_edits
from manuscript_guard.gates.vocabulary import (
    Passage,
    capitals_together,
    context,
    judge_vocabulary,
)
from manuscript_guard.paths import SHIPPED_RECIPES
from manuscript_guard.policy import DRAFTING
from manuscript_guard.text.blocks import Heading, find_headings
from manuscript_guard.text.inline import code_spans, equation_spans
from manuscript_guard.text.masking import NUL, front_matter_end, kept_breaks, mask
from manuscript_guard.text.placeholders import VALUE_NAMESPACES
from manuscript_guard.text.reference_lists import unmarked_reference_lists
from manuscript_guard.text.section_names import section_name_alone
from manuscript_guard.text.sections import Section
from manuscript_guard.text.tables import table_lines
from manuscript_guard.text.title_page import title_page_end

if TYPE_CHECKING:
    from manuscript_guard.text.latex.structure import Source

GATE = "G14"
DATA = Path(__file__).parent.parent / "data"

ABSTRACT = "abstract"
BODY = "main text"
SUPPLEMENT = "supplement"

#: A short form is at most this long. Schwartz and Hearst use ten; study and guideline
#: names (`READUS-PV`, `SARS-CoV-2`) run a little longer.
LONGEST = 15

# A word, with the hyphens that join its parts, and the stops a letter follows: `L.AS`, a
# short form with a stop inside it, and `ROR.The`, two sentences typed on with no space,
# which `_forms` splits again. A stop before a digit joins nothing, a superscript or a
# subscript one among them, so "GDPR.12" and "GDPR.¹²", a reference number typed on, are
# GDPR, and "BA.1" and "1.5" read as before (round 1 of #612); and so does one before "A"
# or "I" alone, the word a sentence typed on opens with, "the ICU.A total" (round 2).
# Unicode letters and digits, no underscore. A stop at its end is not in it.
_RAISED_OR_LOWERED = (
    r"[\N{SUPERSCRIPT ONE}\N{SUPERSCRIPT TWO}\N{SUPERSCRIPT THREE}"
    r"\N{SUPERSCRIPT ZERO}-\N{LATIN SUBSCRIPT SMALL LETTER T}]"
)
_PARTS = (rf"[^\W_]+(?:-[^\W_]+|\.(?=[^\W\d_])(?!{_RAISED_OR_LOWERED}|[AI](?![^\W_]))"
          r"[^\W_]+)*")  # fmt: skip
_WORD = re.compile(_PARTS)
#: What joins two parts of a word.
_JOINS = re.compile(r"[-.]")
# One level of brackets, not running on for ever: an unclosed "(" must not pair with a ")"
# three paragraphs later.
_PAREN = re.compile(r"\(([^()]{1,300})\)")
# The form a journal uses inside a parenthesis: "(hazard ratio [HR], 0.75)". A citation is
# not read as one, since `mask` has taken its key and left no word in the bracket, nor a
# link to a file, whose `](target)` is masked with its bracket. A link to a URL is: `mask`
# takes the URL first and leaves the `]`, so "reporting odds ratio [ROR](https://...)"
# defines ROR, which is what it says.
_SQUARE = re.compile(r"\[([^\[\]]{1,300})\]")
# A count written as pandoc writes a subscript: the 2 of `CO~2~`.
_SUBSCRIPT = re.compile(r"~(\d{1,2})~")
_BLANK_LINE = re.compile(r"\n[ \t\r]*\n")
_QUOTES = (
    "*_\"'"
    "\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
    "\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
)
#: What may cling to either end of a long form and is no part of it.
_EDGES = _QUOTES + ".,;:()[]"
# The short form opening a bracket: alone, or before a separator ("ROR; 95% CI ...", "ROR:
# 3.84", read by its letters like any other). One followed by an equals sign or a number
# gives a statistic and defines nothing: "a higher risk (HR 1.32, 95% CI ...)" is no
# definition of HR, though "higher risk" begins with its letters.
_OPENS_WITH = re.compile(
    rf"[\s{re.escape(_QUOTES)}]*(?P<short>{_PARTS})[\s{re.escape(_QUOTES)}]*"
    r"(?:$|[;,:])"
)
# The short form closing a bracket after a semicolon or a comma, its long form before the
# separator: "(i.e. time to task failure; TTF)" (an exercise physiology preprint of the
# real-paper corpus), "[that is, the hazard ratio, HR]". The last separator is the one.
_CLOSES_WITH = re.compile(
    rf"(?P<before>.*)[;,][\s{re.escape(_QUOTES)}]*(?P<short>{_PARTS})[\s{re.escape(_QUOTES)}]*$",
    re.DOTALL,
)
# A short form after a dash with a space on either side, its long form before the dash:
# "Basic Income Support for Sustainability - BISS", "Basic Payment Scheme \N{EN DASH} BPS"
# (an agricultural-policy preprint of the real-paper corpus), a hyphen, an en dash or an em
# dash, or "--" and "---", which pandoc prints as those; a no-break space is a space. The
# whole word, not a part of `BPS-based`. Only a short form that ends its clause defines
# (`_ends_its_clause`; the author, 2026-11-12, in place of the exceptions of #623).
_DASH_SPACE = r"[ \t\N{NO-BREAK SPACE}]"
_DASH = r"(?:---?|[-\N{EN DASH}\N{EM DASH}])"
_DASHED = re.compile(
    rf"(?<=\S){_DASH_SPACE}+{_DASH}{_DASH_SPACE}+(?P<short>{_PARTS})(?![^\W_]|-[^\W_])"
)
#: Spaces of any kind on one line, and the same across at most one line break.
_LINE_GAP = r"[ \t\r\N{NO-BREAK SPACE}]*"
_ONE_BREAK = rf"{_LINE_GAP}(?:\n{_LINE_GAP})?"
#: A closing quote or emphasis mark, part of the short form's typing.
_MARKS = rf"[{re.escape(_QUOTES)}]*"
#: A citation, which is no more words of the sentence: a bracket the mask has blanked,
#: `[@key]` and `[@a; @b]`, one of numbers, "[12]", "[1, 3-5]", and a superscript number,
#: "^12^". LaTeX's `~\cite{key}` is blanked whole, so spaces pass over it.
_CITED = (rf"(?:{_ONE_BREAK}(?:\[[\s\d,;\-\N{{EN DASH}}\N{{EM DASH}}]*\]"
          rf"|\^[\d,\-\N{{EN DASH}}]+\^))*")  # fmt: skip
# What follows a short form that ends its clause, a closing mark and a citation between
# them allowed: a stop, a semicolon, a closing bracket of either kind or a table cell's bar,
# a comma or a colon and a word, a closing spaced dash and a word, a hard line break (a
# backslash or two spaces before the line's end, as pandoc reads them, and as LaTeX's `\\`
# is left), or the end of the paragraph or of the text. A single line break inside a
# paragraph is read as a space. "Basic Payment Scheme - BPS, which pays farmers", "... - BPS
# [@ec2013]." and "the Scheme - BPS - replaced it" define; a statistic goes on past its
# short form, "older people - OR [95% CI ...] 1.52", "- OR of 1.52", "- OR, 1.52", "- OR -
# 1.52", and defines nothing. A stop before a digit is a decimal point. What this misses is
# in DESIGN.md's Known gaps.
_CLAUSE_ENDS = re.compile(
    rf"{_MARKS}{_CITED}"
    rf"(?:{_ONE_BREAK}(?:\.(?!\d)|[;)\]|]|[,:]{_ONE_BREAK}{_MARKS}[^\W\d_])"
    rf"|{_DASH_SPACE}+{_DASH}{_DASH_SPACE}{_ONE_BREAK}{_MARKS}[^\W\d_]"
    rf"|(?:{_DASH_SPACE}*\\| {{2,}})\r?\n"
    rf"|{_LINE_GAP}(?:\Z|\n{_LINE_GAP}(?:\n|\Z)))"
)
#: A binding that prints a value, as typed: a namespace of `VALUE_NAMESPACES`, `{{results.or}}`
#: or `{{lit.key}}`, and LaTeX's `\mg{results.or}`, its optional argument allowed. An anchor,
#: `{{method.step}}`, prints nothing, and a pointer, `{{ref.table.key}}`, prints "Table 2":
#: neither is a value.
_VALUE_BINDING = "(?:" + "|".join(VALUE_NAMESPACES) + r")\."
#: Spaces as typed, a LaTeX tie among them, which the mask reads as a space, on one line and
#: across at most one line break.
_TYPED_GAP = r"[ \t\r~\N{NO-BREAK SPACE}]*"
_TYPED_BREAK = rf"{_TYPED_GAP}(?:\n{_TYPED_GAP})?"
#: A value bound to the results after the short form, after spaces, a colon, a comma or a
#: closing dash. The mask blanks it, and a binding is where a number would be, so the short
#: form gives a statistic: "- OR {{results.or}}." defines nothing, as "- OR 1.52." does not
#: (round 2 of #643).
_BOUND = re.compile(
    rf"{_MARKS}(?:{_TYPED_GAP}(?:[:,]|{_DASH}))?{_TYPED_BREAK}"
    rf"(?:\{{\{{\s*|\\mg(?![A-Za-z])\s*(?:\[[^\]\n]*\]\s*)?\{{\s*){_VALUE_BINDING}"
)
#: The end of a line, after a closing mark and a citation: where a list item's ends.
_LINE_ENDS = re.compile(rf"{_MARKS}{_CITED}{_LINE_GAP}(?:\n|\Z)")
#: A list item's line as typed, in a block quote or not: "- ", "* ", "1. ", "2) ", `\item`.
_LIST_ITEM = re.compile(r"[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]|\\item(?![A-Za-z]))")
#: A Markdown list item's marker, by its kind: a bullet, or a number's delimiter.
_MARKER = re.compile(r"[ \t]*(?:>[ \t]*)*(?:(?P<bullet>[-*+])|\d{1,9}(?P<delimiter>[.)]))[ \t]")
#: A block quote's `>` at a line's start, each with all the spaces after it; or nothing.
_QUOTE = re.compile(r"(?:[ \t]*>[ \t]*)*")
#: How a lead-in line a list stands under ends: "The schemes were:".
_LEAD_IN = ":"
#: What opens a line that ends the item above it: a heading, LaTeX's next `\item` or the
#: list's `\end{...}`. (A list item's line and a blank line do too.)
_ENDS_AN_ITEM = re.compile(r"[ \t]{0,3}#|[ \t]*\\(?:item|end)(?![A-Za-z])")
#: How far back a list is looked for above a line with a marker, in lines.
_LIST_LOOKBACK = 200
#: The brackets a long form opens and closes, round and square: a letter of its short form
#: is not found inside one it opens (`_inside_a_bracket`).
_OPENING = "(["
_CLOSING = ")]"
# A time of day: `11:00AM`, `10:00 PM`, `7:15` at the end of a line and `AM` on the next.
# Read as words it is `11` and `00AM`, or a `PM`, which are abbreviations to the gate.
_CLOCK = re.compile(r"(?<![\d:])\d{1,2}:[0-5]\d(?::[0-5]\d)?\s?(?:AM|PM)(?![^\W_])")
# A paragraph set entirely in bold, `**TITLE PAGE**` or `__RESULTS__`: a heading typed in Word.
_BOLD = re.compile(r"\s*(\*\*|__)(?:(?!\1).)+\1\s*", re.DOTALL)
# The rule under a table's header row: a pipe table's dashes, a grid table's `=` line.
_HEADER_RULE = re.compile(
    r"\+[:+]*=[=:+]*|(?=.*\|)\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?"
)
# The word standing against an opening bracket: "ROR (reporting odds ratio)".
_BEFORE_PAREN = re.compile(rf"(?P<short>{_PARTS})[ \t]?$")
# An image with its caption: `![caption](target)` or `![caption][label]`, a bracket inside
# the caption allowed one deep, for a citation. Bounded throughout, so a line of `![` with
# no closing bracket is read once and not once per `![`.
_IMAGE = re.compile(
    r"!\[(?:[^\[\]]|\[[^\[\]]{0,300}\]){0,1000}\]"
    r"(?:\([^)\n]{0,1000}\)|\[[^\]\n]{0,300}\])"
)
# I to XXXIX. Longer numerals, and the letters C, D, L and M, are left to be read as
# abbreviations: CI, MI, CD and LV are valid numerals and are far more often not numerals.
_ROMAN = re.compile(r"X{0,3}(?:IX|IV|V?I{0,3})")
# A registration or accession number: letters, then five digits or more. NCT01234567,
# CRD42020123456, ISRCTN12345678, GSE12345.
_IDENTIFIER = re.compile(r"[A-Za-z]{2,}\d{5,}")
# An RRID's accession, after "RRID:", as `data/structural.yaml`'s `rrid` reads it, an
# underscore escaped as Markdown writes it or as the LaTeX reader leaves it, `_` and a NUL,
# allowed: "CVCL_0030" names a cell line, and its letters are no abbreviation and its
# underscore no name from the code. "RRID" itself needs no definition, as "DOI" does
# (`data/abbreviations.yaml`). The reading is `rrids.py`'s, copied here and in
# `data/structural.yaml`, which a masked view and a YAML rule cannot import; a test holds the
# three to one another (`tests/test_rrid_lookup.py::test_g2_g14_and_rrids_py_read_an_rrid_alike`).
# A `.` joins before a digit only; a `-` ends it before a word of four
# small letters or more with no `:`, `_` or `-` after it.
_RRID = re.compile(
    r"(?<![A-Za-z0-9_\-])RRID:(?:[^\S\n]|\n)?\x00*(?P<accession>[A-Za-z][A-Za-z0-9]*"
    r"(?:(?:\\?[_:]\x00?|\.(?=[0-9])|-(?![a-z]{4,}(?![A-Za-z0-9_:\-])))[A-Za-z0-9]+)+"
    r"|[A-Za-z]+\d[A-Za-z0-9]*)"
)
_ARTICLES = ("the ", "a ", "an ")

# Sections where capitals are people and institutions, not abbreviations a reader needs
# defined: initials in a contributions statement, a funder's name, a society's. Found by a
# word anywhere in the title, because publishers word these headings their own way:
# "CRediT authorship contribution statement", "Role of the funding source". The spelling
# is not read in them either: their wording is the taxonomy's and the funder's.
_QUIET = re.compile(
    r"\b(?:"
    r"contributions?|contributors?(?:hip)?"
    r"|acknowledge?ments?"
    r"|funding|financial\s+(?:support|disclosures?)"
    r"|competing\s+interests?|conflicts?\s+of\s+interests?"
    r"|declarations?\s+of\s+(?:competing\s+)?interests?"
    r"|disclosures?"
    r"|author\s+statement"
    r")\b",
    re.IGNORECASE,
)
# A paragraph that opens with a statement's name in bold, as Word papers run a statement on
# from its label: "**Authors\' contributions** JMD, BC and CD designed ...", "**Funding:**
# The THERS programme ...". Its capitals are people and institutions as under a heading
# that names the statement. At the margin, as pandoc writes a Word paragraph: an indented
# line is a table's or a list's. The label is at most 80 characters with no `*` or `_` in
# it, so the match is short however the line goes on.
_RUN_IN = re.compile(r"(\*\*|__)(?=[^\s*_])(?P<label>[^*_\n]{1,80}?)\1")
# A backslash escape, as pandoc writes an apostrophe in Markdown: `Authors\' contributions`.
_ESCAPE = re.compile(r"\\(.)")
# The end of a paragraph: a blank line, a CRLF one too. And the blank lines before one,
# which open none.
_PARAGRAPH_END = re.compile(r"\n[ \t\r]*\n")
_BLANK_LINES = re.compile(r"(?:[ \t\r]*\n)*")
# A line break pandoc prints as a space, a SoftBreak: one with no more than one space or tab
# before it (pandoc 3.9). Two or more, or a backslash, make a LineBreak, which leaves the
# words before it on a line of their own.
_SOFT_BREAK = re.compile(r"[ \t]?\r?\n[ \t]*")

#: How a hyphenated word is read: `SARS-CoV-2` whole when it is a name, `ROR-based` as its
#: parts when it is not. Past this many parts only the parts are read, so a line of
#: `a-a-a-...` costs what its length is.
_JOINED_PARTS = 6

#: The symbols of the elements, and D for deuterium, which solvents are named with.
_PERIODIC_TABLE = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga "
    "Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd "
    "Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra "
    "Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv "
    "Ts Og D"
)
_ELEMENTS = frozenset(_PERIODIC_TABLE.split())
#: The counts read as a formula's. Nobody writes a count of one, so `HSV1` and `PD1` are
#: not formulas; `C6H12O6` is one and `IC50` is not.
_SMALLEST_COUNT = 2
_LARGEST_COUNT = 12
#: The digits a count is written in. Not `str.isdigit`, which a superscript two also
#: answers and `int` then refuses.
_DIGITS = "0123456789"
#: The subscript digits, U+2080 to U+2089, as the digits they stand for: `CO₂` is `CO2`.
_SUBSCRIPTS = {0x2080 + digit: str(digit) for digit in range(10)}


@dataclass(frozen=True)
class _Mark:
    """One place an abbreviation stands. `order` is the file's place in the reading, so
    marks from several files sort as a reader meets them."""

    order: int
    offset: int
    quiet: bool = False

    @property
    def key(self) -> tuple[int, int]:
        return (self.order, self.offset)


@dataclass(frozen=True)
class _Definition(_Mark):
    long: str = ""
    #: In a caption or a glossary: where a definition may be given again, and is not given
    #: twice by being so.
    restates: bool = False


@dataclass
class _Scope:
    """What one separately-read text defines and uses, by short form."""

    name: str
    defined: dict[str, list[_Definition]] = field(default_factory=dict)
    used: dict[str, list[_Mark]] = field(default_factory=dict)


@lru_cache(maxsize=1)
def _shipped() -> tuple[frozenset[str], frozenset[str]]:
    """What needs no definition anywhere: the shipped list and the names of the reporting
    guidelines the toolkit knows; and the names G2 already reads as names, in lower case."""
    listed = yaml.safe_load((DATA / "abbreviations.yaml").read_text(encoding="utf-8"))
    known = {str(entry) for entry in listed.get("known", ())}
    if SHIPPED_RECIPES.exists():
        for recipe in SHIPPED_RECIPES.glob("*.recipe.yaml"):
            name = recipe.name[: -len(".recipe.yaml")]
            # `TRIPOD-development` is a recipe; the guideline a manuscript names is TRIPOD.
            known.update((name, name.split("-")[0]))
    terms = yaml.safe_load((DATA / "terms.yaml").read_text(encoding="utf-8"))
    return frozenset(known), frozenset(str(term).lower() for term in terms.get("terms", ()))


@dataclass(frozen=True)
class _Known:
    exact: frozenset[str]
    lowered: frozenset[str]

    def __contains__(self, form: object) -> bool:
        if not isinstance(form, str):
            return False
        return form in self.exact or form.lower() in self.lowered


def _listed(value: object) -> set[str]:
    """A setting's entries as words, read past one in the wrong shape: the schema reports
    that, and a gate that raised on it would fail a build over a warning's worth of work."""
    if not isinstance(value, (list, tuple)):
        return set()
    return {str(entry) for entry in value if isinstance(entry, (str, int, float))}


@lru_cache(maxsize=1)
def _statistical() -> frozenset[str]:
    """The statistical abbreviations a style manual lets stand undefined
    (`data/statistical_abbreviations.yaml`)."""
    listed = yaml.safe_load((DATA / "statistical_abbreviations.yaml").read_text(encoding="utf-8"))
    return frozenset(str(entry) for entry in listed.get("exempt", ()))


def _asked(known: _Known, statistics: bool, named: frozenset[str]) -> _Known:
    """`known` with the statistical abbreviations added, unless the journal asks for them to
    be defined (`statistics`), and less those it names: what a journal asks to be defined
    is reported where it is not, whoever exempted it."""
    exact = known.exact if statistics else known.exact | _statistical()
    return _Known(exact - named, known.lowered - {name.lower() for name in named})


def _known(project: Project) -> _Known:
    from manuscript_guard.gates.journal import abbreviations_asked

    exact, lowered = _shipped()
    listed = _Known(
        exact
        | set(project.known_abbreviations)
        | _listed(project.paper.get("reporting_guideline")),
        lowered | {term.lower() for term in _listed(project.paper.get("terms"))},
    )
    return _asked(listed, *abbreviations_asked(project))


def _numeral(form: str) -> bool:
    return bool(form) and _ROMAN.fullmatch(form) is not None


def _formula(form: str) -> bool:
    """Is this a chemical formula: a word that reads from end to end as element symbols and
    their counts, two elements or more, with a count somewhere.

    The count is what tells a formula from an abbreviation. `CO2`, `H2SO4` and `NaHCO3` are
    formulas. `CO`, `CI` and `HCV` spell elements too, and so do `PCa`, `SCr` and `HCl`:
    with no count there is nothing to tell prostate cancer from a phosphorus-calcium
    compound, so all of those are still reported."""
    form = form.translate(_SUBSCRIPTS)
    if not any(char in _DIGITS for char in form):
        return False
    # reached[i]: the most elements that can be read up to character i, or -1.
    reached = [-1] * (len(form) + 1)
    reached[0] = 0
    for start in range(len(form)):
        if reached[start] < 0:
            continue
        for width in (2, 1):
            stop = start + width
            if stop > len(form) or form[start:stop] not in _ELEMENTS:
                continue
            while stop < len(form) and form[stop] in _DIGITS:
                stop += 1
            count = form[start + width : stop]
            if count and (
                count[0] == "0" or not _SMALLEST_COUNT <= int(count) <= _LARGEST_COUNT
            ):
                continue
            reached[stop] = max(reached[stop], reached[start] + 1)
    return reached[len(form)] >= 2


def _reads_as_abbreviation(form: str) -> bool:
    """Would a reader take this word, met with no definition, for an abbreviation?

    Two capitals side by side. Stricter than what a definition may introduce, on purpose:
    `McNemar`, `DeLong`, `NaCl` and `PhD` have two capitals and are not abbreviations
    anybody defines, and a rule that reported them would be switched off for the surnames
    alone. `HbA1c` and `mL` are missed by it and caught when the manuscript defines them.
    A numeral, a registration number and a chemical formula are not abbreviations either.
    """
    return (
        2 <= len(form) <= LONGEST
        and capitals_together(form)
        and not _numeral(form)
        and _IDENTIFIER.fullmatch(form) is None
        and not _formula(form)
    )


def _may_be_defined(form: str) -> bool:
    """Can this be the short form in a definition? Wider than `_reads_as_abbreviation`,
    because the long form beside it is the evidence: two capitals anywhere, or one that is
    not simply the capital of a word (`mL`, `pH`), or a capital with a digit (`T2`)."""
    if not 2 <= len(form) <= LONGEST or _numeral(form) or not any(c.isalpha() for c in form):
        return False
    capitals = sum(c.isupper() for c in form)
    if capitals >= 2:
        return True
    if capitals == 0:
        return False
    return not form[0].isupper() or any(c.isdigit() for c in form)


def _singular(form: str) -> str:
    """`RORs` is `ROR`; `CNS` and `mAbs` are themselves."""
    if len(form) > 2 and form.endswith("s") and (form[-2].isupper() or form[-2].isdigit()):
        return form[:-1]
    return form


def _defined_as(form: str, defined: set[str]) -> str | None:
    """The defined short form this word is a use of, its plural included: `RORs` for `ROR`,
    `mAbs` for `mAb`."""
    if form in defined:
        return form
    if form.endswith("s") and form[:-1] in defined:
        return form[:-1]
    return None


def _long_form(short: str, before: str) -> str | None:
    """The long form `short` abbreviates, read from the end of `before`; None when its
    letters are not there in order.

    Schwartz and Hearst's rule (Pac Symp Biocomput 2003;8:451-62): going backwards, each
    letter or digit of the short form is found in turn, and the first must begin a word.
    A letter is not taken from inside a bracket the long form would open: where the nearest
    is, the bracket is passed over and its letters looked for before it, so the `S` of
    "Depression Scale (French version) (HADS)" is the one of "Scale".
    """
    searched = before
    while True:
        matched = _letters(short, searched)
        if matched is None:
            return None
        opened = _inside_a_bracket(searched, matched)
        if opened is None:
            break
        searched = _passed_over(searched, opened)
    found = before[matched[-1] :].strip().strip(_EDGES).strip()
    if len(found) <= len(short):
        return None
    # A short form does not define itself, nor through its plural: in "expressed as ORs
    # (OR, 95% CI)" the letters of OR are all in "ORs".
    words = {_singular(word.strip(_EDGES)).lower() for word in found.split()}
    if _singular(short).lower() in words:
        return None
    return found


def _letters(short: str, before: str) -> list[int] | None:
    """Where each letter or digit of `short` is found going back from the end of `before`,
    the nearest each time, the last letter first; None where one is not there."""
    at = len(before) - 1
    matched: list[int] = []
    for position in range(len(short) - 1, -1, -1):
        wanted = short[position].lower()
        if not wanted.isalnum():
            continue
        first = position == 0
        while at >= 0 and (
            before[at].lower() != wanted or (first and at > 0 and before[at - 1].isalnum())
        ):
            at -= 1
        if at < 0:
            return None
        matched.append(at)
        at -= 1
    return matched or None


def _inside_a_bracket(before: str, matched: list[int]) -> int | None:
    """Where a bracket opens that the long form would open and a letter of the short form is
    found inside, the outermost; None where there is none. `matched` are where its letters
    were found, the last letter first.

    "(WSE1) and 40 (12.5%) had a second WSE (WSE2)" has the `2` of WSE2 inside "(12.5%)",
    which is no part of a long form. A bracket closing one opened before the long form is,
    "warning score (WSE) at 1 hour (WSE1)", where WSE1 is the WSE at one hour, and so is a
    whole bracket none of the letters is in, "adjusted (for age) relative risk (aRR)"."""
    letters = set(matched)
    opened: list[int] = []
    for at in range(matched[-1], matched[0] + 1):
        char = before[at]
        if char in _OPENING:
            opened.append(at)
        elif char in _CLOSING and opened:
            opened.pop()
        elif opened and at in letters:
            return opened[0]
    return None


def _passed_over(before: str, opened: int) -> str:
    """`before` with the bracket that opens at `opened` blanked to its close, or to the end
    where it does not close, so that no letter is found in it."""
    depth, at = 0, opened
    while at < len(before):
        depth += (before[at] in _OPENING) - (before[at] in _CLOSING)
        if depth == 0:
            break
        at += 1
    return before[:opened] + " " * (min(at, len(before) - 1) + 1 - opened) + before[at + 1 :]


def _window(short: str) -> int:
    """How many words back a long form may start: Schwartz and Hearst's bound."""
    return min(len(short) + 5, len(short) * 2)


def _heading_span(text: str, heading: Heading) -> tuple[int, int]:
    end = text.find("\n", heading.start)
    if end != -1 and heading.setext:
        end = text.find("\n", end + 1)
    return heading.start, len(text) if end == -1 else end


def _hide(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """`text` with `spans` replaced by NUL, offsets and line breaks kept."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = NUL
    return "".join(chars)


def _hidden(text: str) -> str:
    """`text` with everything that is not a sentence or a heading replaced by NUL, offsets
    and line breaks kept: what `mask` takes (listings, comments, bindings, citation keys,
    link targets), the front matter, inline code and equations, and image captions.

    The one reading of a file both halves of the gate start from. The abbreviations are
    read in it with the headings hidden as well and every NUL made a space, which is the
    text they have always been read in. The vocabulary is read in it as it stands, so that
    a word before a listing and a word after it are not taken for neighbours."""
    return _views(text)[0]


def _views(text: str) -> tuple[str, str]:
    """`_hidden(text)`, and the text of its code spans with everything else NUL, as `mask`
    leaves them: a binding or a URL in a code span is no word of it. The code names are
    read in the second (`gates/code_names.py`). Masked once for both."""
    masked = mask(text)
    code = code_spans(masked)
    unread = [(0, front_matter_end(text)), *(found.span() for found in _IMAGE.finditer(text))]
    spans = [*code, *equation_spans(masked, code), *unread, *_rrids(masked)]
    kept = "".join(
        "\n" if char == NUL and text[index] == "\n" else char
        for index, char in enumerate(masked)
    )
    return _hide(kept, spans), _set_aside(_only(masked, code), unread)


def _rrids(text: str) -> list[tuple[int, int]]:
    """Where each RRID's accession runs, which G14 does not read."""
    return [found.span("accession") for found in _RRID.finditer(text)]


def _only(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """`text` with all but `spans` replaced by NUL, offsets kept."""
    chars = [NUL] * len(text)
    for start, end in spans:
        chars[start:end] = text[start:end]
    return "".join(chars)


def _set_aside(code: str, spans: Iterable[tuple[int, int]]) -> str:
    """A view of the code spans with `spans` hidden too: where G14 reads no sentence, the
    front matter, an image's caption, a LaTeX figure, the preamble and the reference list, it
    reads no code either (round 1 of #575)."""
    return _hide(code, spans) if code else code


@dataclass(frozen=True)
class _Region:
    start: int
    scope: str | None  # None: not read at all (the reference list)
    quiet: bool


def _regions(
    headings: list[Heading],
    chain: list[Section],
    *,
    supplementary: bool,
    abstract_title: str | None = None,
    lists: Iterable[tuple[int, int]] = (),
    statements: Iterable[tuple[int, int]] = (),
    keywords: Mapping[int, int] | None = None,
) -> list[_Region]:
    """Which text each stretch of a file belongs to. `chain` is the headings a reader is
    under, carried from one file of a document into the next: a file that opens without a
    heading continues the section the last one ended in. `lists` are the reference lists
    under a line that is no heading (`unmarked_reference_lists`): each is read as the list
    under `# References` is, and the text after it as the text before it. `statements` are
    the paragraphs a statement's bold label opens (`_run_in_statements`): each is quiet, as
    under a heading that names the statement, in the part of the paper it stands in.
    `keywords` gives, by where it starts, each heading that names the keywords and where its
    first paragraph ends (`_keywords_lists`): where it follows the Abstract, up to there it
    is read as the Abstract's, a list of its terms and no use in the main text (round 1 of
    #689); anywhere else it is read as any heading's section is (round 2)."""

    def here(start: int) -> _Region:
        return _region(start, chain, supplementary=supplementary, abstract_title=abstract_title)

    kept = keywords or {}
    regions = [here(0)]
    for heading in headings:
        while chain and chain[-1].level >= heading.level:
            chain.pop()
        chain.append(Section(title=heading.title, level=heading.level, body="", line=0))
        # Only after the Abstract: after a reference list or a statement the list took its
        # scope, and was not read (round 2 of #689).
        if heading.start in kept and regions[-1].scope == ABSTRACT:
            before = regions[-1]
            regions.append(_Region(heading.start, before.scope, before.quiet))
            regions.append(here(kept[heading.start]))
            continue
        regions.append(here(heading.start))
    regions = _set_apart(regions, statements, lambda start, at: _Region(start, at.scope, True))
    return _set_apart(regions, lists, lambda start, _at: _Region(start, None, True))


def _set_apart(
    regions: list[_Region],
    spans: Iterable[tuple[int, int]],
    apart: Callable[[int, _Region], _Region],
) -> list[_Region]:
    """`regions` with each of `spans`, in order and apart, read as `apart` says from the
    region it opens in, and what was read before it read again after it: one pass over
    both, so that a file of many statements costs what its length is (round 1 of #596)."""
    out: list[_Region] = []
    at, current = 0, regions[0]
    for start, end in spans:
        while at < len(regions) and regions[at].start <= start:
            current = regions[at]
            if current.start < start:
                out.append(current)
            at += 1
        out.append(apart(start, current))
        while at < len(regions) and regions[at].start < end:
            current = regions[at]
            at += 1
        if at == len(regions) or regions[at].start > end:
            out.append(_Region(end, current.scope, current.quiet))
    return out + regions[at:]


def _run_in_statements(hidden: str, headings: list[Heading]) -> list[tuple[int, int]]:
    """Where each paragraph runs that opens with a statement's name in bold (`_RUN_IN`), as
    offsets `[start, end)`: a name `STATEMENT_TITLE` reads whole, as a heading's, and that
    `_QUIET` finds, "Authors' contributions", "Funding:", "Acknowledgements". A label that
    is the whole paragraph, "**Funding**" on its own over the statement, takes the paragraph
    after it too, up to a heading. A paragraph that only opens with such a word in bold,
    "**Contributions of this study** We ...", is the paper's own, and so is one whose bold
    word goes on into its sentence, "**Funding** of the NHS fell" (`_a_label`), and a label
    inside a paragraph. `hidden` is the file masked, a listing and a comment blanked."""
    starts = sorted(heading.start for heading in headings)
    found: list[tuple[int, int]] = []
    position = 0
    while position < len(hidden):
        # A paragraph opens past the blank lines before it, however many there are.
        position = _BLANK_LINES.match(hidden, position).end()
        if position == len(hidden):
            break
        start, (end, position) = position, _paragraph(hidden, position)
        opening = _RUN_IN.match(hidden, start)
        if opening is None:
            continue
        label, rest = opening.group("label"), hidden[opening.end() : end]
        if not (_names_a_statement(label) and _a_label(label, rest)):
            continue
        if _alone(rest):
            under = _under_a_label(hidden, position, starts)
            if under is not None:
                end, position = under
        found.append((start, end))
    return found


def _keywords_lists(text: str, hidden: str, headings: list[Heading]) -> dict[int, int]:
    """Each heading whose title names the keywords (`section_names.names_keywords`), by where
    it starts, with where the first paragraph under it ends, or the heading itself where a
    heading follows it first: the list of the paper's keywords, which `init --from` writes
    under such a heading where a run-in "Keywords:" ends the Abstract, and the text after it
    is the main text's (round 1 of #689)."""
    from manuscript_guard.text.section_names import names_keywords

    starts = sorted(heading.start for heading in headings)
    found: dict[int, int] = {}
    for heading in headings:
        if not names_keywords(heading.title):
            continue
        after = _heading_span(text, heading)[1]
        opened = _BLANK_LINES.match(hidden, after).end()
        end = _paragraph(hidden, opened)[0] if opened < len(hidden) else after
        following = bisect_right(starts, heading.start)
        if following < len(starts) and starts[following] < end:
            end = max(after, starts[following])
        found[heading.start] = end
    return found


def _paragraph(text: str, start: int) -> tuple[int, int]:
    """Where the paragraph opening at `start` ends, and where the text after it opens."""
    stop = _PARAGRAPH_END.search(text, start)
    return (stop.start(), stop.end()) if stop else (len(text), len(text))


def _alone(rest: str) -> bool:
    """Whether a label's paragraph holds nothing after it but a colon or a stop."""
    return not rest.strip(" \t\r\n:.")


def _a_label(label: str, rest: str) -> bool:
    """Whether bold words with `rest` after them in their paragraph are a label, not the
    first words of a sentence: they end in a colon or a stop, or what follows them opens
    with one, or with no small letter. "**Funding** of the NHS fell" goes on into its
    sentence (round 1 of #596), on its line or across a line break pandoc prints as a space
    (`_SOFT_BREAK`); "**Funding** none" is read as that sentence too. A hard line break
    leaves the words on a line of their own, as a label stands."""
    soft = _SOFT_BREAK.match(rest)
    after = rest[soft.end() :] if soft else rest.lstrip(" \t")
    return label.rstrip().endswith((":", ".")) or after[:1] in (":", ".") or not (
        after[:1].islower())  # fmt: skip


def _under_a_label(text: str, start: int, headings: list[int]) -> tuple[int, int] | None:
    """The paragraph under a label that stands alone, opening at `start`: where it ends and
    where the text after it opens; None where nothing follows, or a heading does. `headings`
    are where the headings start, in order."""
    if start >= len(text):
        return None
    end, after = _paragraph(text, start)
    at = bisect_left(headings, start)
    if at < len(headings) and headings[at] < end:
        return None
    return end, after


def _names_a_statement(label: str) -> bool:
    """Whether a bold label is a statement's name whose capitals are people and institutions:
    its whole text a statement's name (`STATEMENT_TITLE`) that `_QUIET` finds. "Authors'
    contributions" and "Funding:" are; "Abbreviations" is a glossary's, and "Contributions
    of this study" the paper's own."""
    from manuscript_guard.text.section_names import STATEMENT_TITLE

    label = _ESCAPE.sub(r"\1", label).strip()
    return bool(STATEMENT_TITLE.match(label) and _QUIET.search(label))


def _region(
    start: int,
    chain: list[Section],
    *,
    supplementary: bool,
    abstract_title: str | None,
    abstract: bool = False,
    references: bool = False,
) -> _Region:
    """The text a stretch under `chain` belongs to; `abstract` and `references` where a LaTeX
    environment says so, which no heading in the chain does."""
    if references or any(section.is_references for section in chain):
        return _Region(start, None, True)
    quiet = any(_QUIET.search(section.title) for section in chain)
    if supplementary:
        return _Region(start, SUPPLEMENT, quiet)
    abstract = abstract or any(section.names_abstract(abstract_title) for section in chain)
    return _Region(start, ABSTRACT if abstract else BODY, quiet)


def _latex_regions(
    source: Source, *, supplementary: bool, abstract_title: str | None = None
) -> list[_Region]:
    """Which text each stretch of a LaTeX file belongs to: the headings in force at each
    place, as the include tree gives them, a file input after a heading under it; the
    abstract where an abstract runs, or where the file is input inside one; and no text in a
    reference list typed in `thebibliography`.

    The heading the reader gives an abstract is in force past its end until the next
    heading, so it is left out of every chain, and the abstract's own span says where it
    runs (`Reading.abstracts`)."""
    reading = source.reading
    spans = (*reading.abstracts, *reading.references)
    edges = {0, *(heading.start for heading in reading.headings),
             *(end for end, _after in source.resumes),
             *(edge for span in spans for edge in span)}  # fmt: skip
    regions = []
    for start in sorted(edges):
        chain = [Section(title=heading.title, level=heading.level, body="", line=0)
                 for heading in source.chain_at(start + 1) if heading.end != -1]  # fmt: skip
        inside = "abstract" in source.environments or _within(reading.abstracts, start)
        regions.append(_region(start, chain, supplementary=supplementary,
                               abstract_title=abstract_title, abstract=inside,
                               references=_within(reading.references, start)))  # fmt: skip
    return regions


def _within(spans: Iterable[tuple[int, int]], offset: int) -> bool:
    return any(start <= offset < end for start, end in spans)


def _restates(captions: tuple, glossaries: tuple, offset: int) -> bool:
    """Whether a definition at `offset` is in a caption or a glossary, where it may restate
    one the text gives."""
    return _inside(captions, offset) or _inside(glossaries, offset)


def _in_a_glossary(file: _File, offset: int) -> bool:
    """Whether a word at `offset` is in a glossary, whose lines are not uses."""
    return _inside(file.glossaries, offset)


def _on_the_title_page(file: _File, offset: int) -> bool:
    """Whether a word at `offset` is on the title page that opens the file, which G14 does
    not read for abbreviations: nothing there needs defining, and nothing there is a use or
    a definition (`text/title_page.py`)."""
    return offset < file.title_page


def _on_title_pages(files: list[_File]) -> dict[str, set[str]]:
    """The words the files' title pages hold, whole and by their parts, by the text each
    stands in: the paper's, or the supplement's. A title typed as a heading among them,
    "# Drug safety in the PACES year" (round 2 of #654). Where one is an entry of that
    text's list of abbreviations, the title page uses it, the one use it makes (Basile,
    2026-11-12); where one is a short form that text defines and never uses, its hint says
    that the title page's use was not counted."""
    found: dict[str, set[str]] = {}
    for file in files:
        for word in _WORD.finditer(file.printed, 0, file.title_page):
            scope = file.region_at(word.start()).scope
            if scope is not None:
                found.setdefault(scope, set()).update((word.group(0),
                                                       *_JOINS.split(word.group(0))))  # fmt: skip
    return found


def _inside(spans: tuple[tuple[int, int], ...], offset: int) -> bool:
    """`_within` for spans in order and none inside another, by halving."""
    at = bisect_right(spans, (offset, float("inf"))) - 1
    return at >= 0 and spans[at][0] <= offset < spans[at][1]


def _in_capitals(prose: str) -> list[tuple[int, int]]:
    """Where `prose` holds a heading typed in capitals: a paragraph set entirely in bold
    whose letters are all capitals, "**ABSTRACT**", which is how a manuscript converted from
    Word writes a heading, pandoc making one only of a heading style; a paragraph that is
    only a section's name in capitals, numbered or not, "2. DISCUSSION", "ABSTRACT", as a
    paper typed in Word has its headings in plain capitals (`_names_a_section`); and a cell
    of a table's header row whose letters are, "MODEL 1". Not a table's body, whose cells
    name what the rows count, `COPD` among them, nor any other plain paragraph or a list
    item. In order, and none inside another."""
    spans: list[tuple[int, int]] = []
    start = 0
    for gap in (*_BLANK_LINE.finditer(prose), None):
        end = len(prose) if gap is None else gap.start()
        paragraph = prose[start:end]
        if paragraph.isupper() and (_BOLD.fullmatch(paragraph) or _names_a_section(paragraph)):
            spans.append((start, end))
        else:
            spans += _header_cells(prose, start, end)
        if gap is not None:
            start = gap.end()
    return sorted(spans)


def _names_a_section(paragraph: str) -> bool:
    """Whether a paragraph is only a section's name, of the closed list a title standing
    alone is read as a heading by (`section_name_alone`), a number before it or none, its
    stop escaped as pandoc writes a numbered Word paragraph or not: "2. DISCUSSION",
    "1\\. INTRODUCTION", "ABSTRACT" (corpus papers converted from Word)."""
    return section_name_alone(_ESCAPE.sub(r"\1", paragraph)) is not None


def _header_cells(prose: str, start: int, end: int) -> list[tuple[int, int]]:
    """The cells of the header rows of the tables between `start` and `end` whose letters
    are all capitals: the rows above a pipe table's dashes or a grid table's `=` rule."""
    lines = []
    at = start
    for line in prose[start:end].split("\n"):
        lines.append((at, line))
        at += len(line) + 1
    cells = []
    for index, (_at, line) in enumerate(lines):
        if not _HEADER_RULE.fullmatch(line.strip()):
            continue
        header = []
        for above in reversed(lines[:index]):
            if not above[1].lstrip().startswith("|"):
                break
            header.insert(0, above)
        for row in _rows(header):
            cells += _capitals_in_row(prose, row)
    return cells


def _rows(header: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """The lines of a header as its rows: one row, a grid table's cell running over
    several lines, where each line has its bars where the first has them; else a row for
    each line."""
    if not header:
        return []
    bars = [index for index, char in enumerate(header[0][1]) if char == "|"]
    if all(len(line) > bars[-1] and all(line[bar] == "|" for bar in bars)
           for _at, line in header):  # fmt: skip
        return [header]
    return [[line] for line in header]


def _capitals_in_row(prose: str, row: list[tuple[int, str]]) -> list[tuple[int, int]]:
    """The cells of one row whose letters are all capitals, a cell read whole over all the
    lines of the row: "Patients with" over "COPD" is one cell, and has small letters."""
    bars = [index for index, char in enumerate(row[0][1]) if char == "|"]
    cells = []
    for left, right in zip(bars, [*bars[1:], None], strict=True):
        pieces = [(at + left + 1, at + (len(line) if right is None else right))
                  for at, line in row]  # fmt: skip
        if " ".join(prose[low:high] for low, high in pieces).isupper():
            cells += pieces
    return cells


def _stem(short: str, long: str) -> str:
    """The form a definition defines: `RORs` defines `ROR`, and `mAbs` after "monoclonal
    antibodies" defines `mAb`, since a plural long form says the `s` is the plural's."""
    single = _singular(short)
    if single != short:
        return single
    last = long.split()[-1].strip(_EDGES) if long.split() else ""
    if (
        len(short) > 2
        and short.endswith("s")
        and last.lower().endswith("s")
        and _may_be_defined(short[:-1])
    ):
        return short[:-1]
    return short


def _short_inside(prose: str, bracket: re.Match[str]) -> tuple[int, str, str] | None:
    """A definition with its short form in the bracket: "reporting odds ratio (ROR)"."""
    opening = _OPENS_WITH.match(bracket.group(1))
    if opening is None or not _may_be_defined(opening.group("short")):
        return None
    short = opening.group("short")
    long = _read_back(short, _paragraph_before(prose, bracket.start()))
    if long is None:
        return None
    return bracket.start(1) + opening.start("short"), _stem(short, long), long


def _short_closing(bracket: re.Match[str]) -> tuple[int, str, str] | None:
    """A definition with its short form closing the bracket after a semicolon or a comma,
    and its long form before the separator: "(i.e. time to task failure; TTF)"."""
    closing = _CLOSES_WITH.match(bracket.group(1))
    if closing is None or not _may_be_defined(closing.group("short")):
        return None
    short = closing.group("short")
    long = _read_back(short, closing.group("before"))
    if long is None:
        return None
    return bracket.start(1) + closing.start("short"), _stem(short, long), long


def _dashed(prose: str, typed: str | None = None) -> list[tuple[int, str, str]]:
    """The definitions with a dash: "Basic Payment Scheme - BPS", the long form before the
    dash in its paragraph, the short form ending its clause. `typed` is the text as typed,
    where a list item's marker stands, of the length of `prose`."""
    lines = typed if typed is not None and len(typed) == len(prose) else prose
    found = []
    for dash in _DASHED.finditer(prose):
        short = dash.group("short")
        if not _may_be_defined(short) or not _ends_its_clause(prose, lines, dash):
            continue
        long = _read_back(short, _paragraph_before(prose, dash.start()))
        if long is not None:
            found.append((dash.start("short"), _stem(short, long), long))
    return found


def _ends_its_clause(prose: str, typed: str, dash: re.Match[str]) -> bool:
    """Does the short form `dash` found end its clause (`_CLAUSE_ENDS`), or a list item,
    which ends where its line does when the next line is no continuation of it? A value
    bound to the results after it ends nothing (`_BOUND`)."""
    if _BOUND.match(typed, dash.end()):
        return False
    if _CLAUSE_ENDS.match(prose, dash.end()):
        return True
    line = typed.rfind("\n", 0, dash.start()) + 1
    ending = _LINE_ENDS.match(prose, dash.end())
    return bool(ending and _in_a_list_item(typed, line) and _item_ends(typed, ending.end()))


def _in_a_list_item(typed: str, line: int) -> bool:
    """Is the line starting at `line` a list item's: opened by a marker, with the next line
    an item of the same kind, or in a list that opens its block, with a marker or indented,
    or opens under a lead-in line ending in a colon? The lines between are the items above
    it, their indented lines and their lazy continuations, unindented, as `_item_ends` reads
    them. Each line is read through a block quote's `>`. A line in the middle of a paragraph
    that opens "2020) " or "3. " is no list item. `\\item` is one wherever it stands."""
    listed = _LIST_ITEM.match(typed, line)
    if listed is None:
        return False
    if "\\item" in listed.group(0):
        return True
    marked = _MARKER.match(typed, line)
    below = _MARKER.match(_line_at(typed, len(_line_at(typed, line)) + line + 1))
    if marked is not None and below is not None and _kind(below) == _kind(marked):
        return True
    at = line
    for _step in range(_LIST_LOOKBACK):
        here = _line_at(typed, at)
        if at == 0:
            return _opens_a_list(here)
        above = typed.rfind("\n", 0, at - 1) + 1
        written = typed[_QUOTE.match(typed, above).end() : at - 1]
        if not written.strip(" \t\r") or _ENDS_AN_ITEM.match(written):
            return _opens_a_list(here)
        if written.rstrip(" \t\r").endswith(_LEAD_IN) and _MARKER.match(here):
            return True
        at = above
    return True


def _line_at(typed: str, start: int) -> str:
    """The line of `typed` that starts at `start`, without its line break."""
    stop = typed.find("\n", start)
    return typed[start:] if stop < 0 else typed[start:stop]


def _kind(marker: re.Match[str]) -> str:
    """The kind of a list item's marker: its bullet, or a number's delimiter."""
    return marker["bullet"] or marker["delimiter"]


def _opens_a_list(written: str) -> bool:
    """Does the line `written`, the first of its block, open a list: a marker's or indented,
    read through a block quote's `>`?"""
    unquoted = written[_QUOTE.match(written).end() :]
    return bool(_MARKER.match(written)) or unquoted[:1] in (" ", "\t")


def _item_ends(typed: str, after: int) -> bool:
    """Does the list item end at the line break before `after`: is the next line blank,
    another item's, a heading or the list's end, and not its own continuation?"""
    if after >= len(typed):
        return True
    stop = typed.find("\n", after)
    written = typed[after:] if stop < 0 else typed[after:stop]
    return (not written.strip(" \t\r>") or bool(_LIST_ITEM.match(written))
            or bool(_ENDS_AN_ITEM.match(written)))  # fmt: skip


def _paragraph_before(prose: str, end: int) -> str:
    """The text of the paragraph before `end`, at most 400 characters of it."""
    return _BLANK_LINE.split(prose[max(0, end - 400) : end])[-1]


def _read_back(short: str, before: str) -> str | None:
    """The long form `short` abbreviates at the end of `before`, within Schwartz and
    Hearst's bound, of its singular where the plural's letters are not there."""
    words = " ".join(before.split()[-_window(short) :])
    long = _long_form(short, words)
    if long is None and short != _singular(short):
        long = _long_form(_singular(short), words)
    return long


def _long_inside(prose: str, bracket: re.Match[str]) -> tuple[int, str, str] | None:
    """A definition with its long form in the bracket: "ROR (reporting odds ratio)"."""
    standing = _BEFORE_PAREN.search(prose, max(0, bracket.start() - LONGEST - 1), bracket.start())
    if standing is None:
        return None
    head, short = standing.start("short"), standing.group("short")
    found = _long_after(prose, bracket, head, short)
    # A sentence typed on with no space puts the word before its stop in the short form,
    # "rose.ROR (reporting odds ratio)": tried again from the last stop (round 1 of #612).
    if found is None and "." in short:
        cut = short.rindex(".") + 1
        found = _long_after(prose, bracket, head + cut, short[cut:])
    return found


def _long_after(
    prose: str, bracket: re.Match[str], head: int, short: str
) -> tuple[int, str, str] | None:
    """`_long_inside` for the short form `short` standing at `head` before the bracket."""
    if not _may_be_defined(short):
        return None
    # The search starts a short form's length back, so it can start inside a word.
    if head > 0 and (prose[head - 1].isalnum() or prose[head - 1] == "-"):
        return None
    words = bracket.group(1).split()
    if not 2 <= len(words) <= _window(short):
        return None
    joined = " ".join(words)
    long = _long_form(_singular(short), joined)
    if long is None:
        return None
    # The long form has to be the bracket, give or take an article: "ROR (see the ratio
    # results)" matches its letters from "ratio" on and defines nothing.
    rest = joined[: joined.rfind(long)].strip(_EDGES + " ").lower()
    if rest and rest + " " not in _ARTICLES:
        return None
    return head, _stem(short, long), long


def _definitions(prose: str, typed: str | None = None) -> list[tuple[int, str, str]]:
    """Every definition in `prose`: where its short form stands, the form it defines, and
    the long form. Both orders in round brackets, "reporting odds ratio (ROR)" and "ROR
    (reporting odds ratio)", and the short form in square ones, "hazard ratio [HR]"; in
    either, the short form closing the bracket after a separator with its long form before
    that, "(i.e. time to task failure; TTF)"; and the short form after a dash, "Basic
    Payment Scheme - BPS", read by the text as `typed` too where that is given."""
    found: list[tuple[int, str, str]] = []
    for bracket in _PAREN.finditer(prose):
        if _BLANK_LINE.search(bracket.group(1)):
            continue
        definition = (_short_inside(prose, bracket) or _long_inside(prose, bracket)
                      or _short_closing(bracket))  # fmt: skip
        if definition is not None:
            found.append(definition)
    for bracket in _SQUARE.finditer(prose):
        if _BLANK_LINE.search(bracket.group(1)):
            continue
        definition = _short_inside(prose, bracket) or _short_closing(bracket)
        if definition is not None:
            found.append(definition)
    # A short form a bracket already defines where it stands is not defined there again.
    bracketed = {at for at, _short, _long in found}
    return found + [each for each in _dashed(prose, typed) if each[0] not in bracketed]


def _listed_as(form: str, known: _Known) -> bool:
    """Is this word, or the singular it is the plural of, one the lists exempt? Any final
    `s` counts, as for a defined abbreviation: `PARPis` for a listed `PARPi`."""
    return form in known or (form.endswith("s") and form[:-1] in known)


def _joined(token: str, parts: list[str], starts: list[int], begin: int, end: int) -> str:
    """The parts of `token` from `begin` to `end` as the word writes them, with the hyphen
    or the stop between each two: `L.AS`, `SARS-CoV-2`."""
    return token[starts[begin] : starts[end - 1] + len(parts[end - 1])]


def _named(
    token: str,
    parts: list[str],
    starts: list[int],
    index: int,
    defined: set[str],
    known: _Known,
) -> tuple[int, list[tuple[int, str, bool]]] | None:
    """A defined or listed name of two parts or more that starts here, and where it stops.

    Looked for before the word is split at its ordinary words, because a name may hold
    one: `RNA-seq`, `non-HDL-C`, `EMPEROR-Preserved`. Split first, `RNA-seq` was never
    matched whole, so its definition was reported as unused.

    A name that opens with an ordinary word takes a capital at the start of a sentence, so
    `Non-HDL-C` is looked for as `non-HDL-C` too. Only there: the capitals of the name
    itself are the name, and `Rna-seq` is not `RNA-seq`."""
    opening = parts[index]
    lowered = opening[0].lower() + opening[1:] if _is_word(opening) else opening
    for stop in range(len(parts), index + 1, -1):
        whole = _joined(token, parts, starts, index, stop)
        for form in dict.fromkeys((whole, lowered + whole[len(opening) :])):
            base = _defined_as(form, defined)
            if base is not None:
                return stop, [(starts[index], base, True)]
            if _listed_as(form, known):
                return stop, []
    return None


def _is_word(part: str) -> bool:
    """An ordinary word in a hyphenated one: `based` in `ROR-based`, `Non` in `Non-ICI`."""
    return len(part) >= 2 and part.isalpha() and part[1:].islower()


def _run(
    token: str,
    parts: list[str],
    starts: list[int],
    begin: int,
    end: int,
    defined: set[str],
    known: _Known,
) -> list[tuple[int, str, bool]]:
    """The abbreviations in one stretch of a hyphenated word that holds no ordinary word.

    Read whole where the whole is defined or known, `SARS-CoV-2`. Where nothing in it is,
    it is reported whole, so `LC-MS` is one abbreviation and not `LC` and `MS`, and a
    trial is named `KEYNOTE-189`, as its definition would name it; and `L.AS` is one,
    whose parts a stop joins."""
    found: list[tuple[int, str, bool]] = []
    loose: list[int] = []
    index = begin
    while index < end:
        for stop in range(end, index, -1):
            form = _joined(token, parts, starts, index, stop)
            base = _defined_as(form, defined)
            if base is not None:
                found.append((starts[index], base, True))
                index = stop
                break
            if _listed_as(form, known):
                found.append((starts[index], "", True))
                index = stop
                break
        else:
            loose.append(index)
            index += 1
    shaped = [index for index in loose if _reads_as_abbreviation(_singular(parts[index]))]
    whole = _singular(_joined(token, parts, starts, begin, end))
    if not found and shaped and len(whole) <= LONGEST:
        return [(starts[begin], whole, False)]
    found = [entry for entry in found if entry[1]]
    return found + [(starts[index], _singular(parts[index]), False) for index in shaped]


def _forms(token: str, defined: set[str], known: _Known) -> list[tuple[int, str, bool]]:
    """The abbreviations in one word: where each starts in it, its short form, and whether
    it is one the manuscript defines. Its parts are what a hyphen or a stop joins (`_WORD`):
    `ROR-based` is ROR and a word, `L.AS` one abbreviation, and `ROR.The`, a sentence typed
    on with no space, ROR and a word."""
    parts = _JOINS.split(token)
    starts = [0]
    for part in parts[:-1]:
        starts.append(starts[-1] + len(part) + 1)
    found: list[tuple[int, str, bool]] = []
    joined = len(parts) <= _JOINED_PARTS
    index = 0
    while index < len(parts):
        named = _named(token, parts, starts, index, defined, known) if joined else None
        if named is not None:
            index, uses = named
            found += uses
            continue
        if _is_word(parts[index]):
            index += 1
            continue
        stop = index + 1
        if joined:
            while stop < len(parts) and not _is_word(parts[stop]):
                stop += 1
        found += _run(token, parts, starts, index, stop, defined, known)
        index = stop
    return found


@dataclass
class _File:
    order: int
    path: Path
    text: str
    regions: list[_Region]
    definitions: list[tuple[int, str, str]]
    #: The text the abbreviations are read in: sentences, everything else a space.
    prose: str = ""
    #: The text the vocabulary is read in: sentences and headings, less the reference
    #: list, everything else NUL.
    printed: str = ""
    #: The text the spelling is read in: `printed` less the sections whose wording is
    #: somebody else's, the ones `_QUIET` finds.
    spelt: str = ""
    #: The text of the code spans, everything else NUL, which the code names are read in
    #: beside `printed`.
    code: str = ""
    #: Where its tables' cells run, which the code names are not read in: a Markdown table of
    #: the four kinds pandoc reads (`text.tables.table_lines`), a LaTeX `tabular` and its kin
    #: less its captions and footnotes (`_latex_cells`).
    tables: tuple[tuple[int, int], ...] = ()
    starts: list[int] = field(default_factory=list)
    breaks: list[int] = field(default_factory=list)
    #: The stretch of the file this reads, where a LaTeX file is read in stretches, the text
    #: up to a file it inputs and the text after it; the whole file otherwise.
    stretch: tuple[int, int] | None = None
    #: Where each word stands that the LaTeX reader could not read, an accent command in it.
    unread: tuple[tuple[int, int], ...] = ()
    #: A LaTeX file as typed, where `text` is the file as Markdown writes it.
    typed: str = ""
    #: Where a caption or a legend runs, and where a glossary's body does, in order.
    captions: tuple[tuple[int, int], ...] = ()
    glossaries: tuple[tuple[int, int], ...] = ()
    #: Where the definitions stand that are in a caption or a glossary.
    restating: frozenset[int] = frozenset()
    #: Whether the file has a heading; None for a LaTeX file, whose sections G14 reads from
    #: its commands.
    headed: bool | None = None
    supplementary: bool = False
    #: The authors' initials its contributions statement names (`_initials`).
    initials: frozenset[str] = frozenset()
    #: Where the title page that opens the file ends, 0 where it opens with none
    #: (`text/title_page.py`): no abbreviation is read before it.
    title_page: int = 0

    def __post_init__(self) -> None:
        self.starts = [region.start for region in self.regions]
        if not self.breaks:
            self.breaks = [index for index, char in enumerate(self.text) if char == "\n"]
        if self.stretch is None:
            self.stretch = (0, len(self.text))

    def region_at(self, offset: int) -> _Region:
        return self.regions[bisect_right(self.starts, offset) - 1]

    def line_of(self, offset: int) -> int:
        return bisect_left(self.breaks, offset) + 1


def _file(
    order: int,
    path: Path,
    text: str,
    chain: list[Section],
    supplementary: bool,
    abstract_title: str | None = None,
    opens: bool | None = None,
) -> _File:
    """A Markdown file read. `opens` where it is the first file of the paper or of the
    supplement, which a title page may open; by default, where `order` is 0."""
    headings = find_headings(text)
    hidden, code = _views(text)
    if opens is None:
        opens = order == 0
    title_page = (title_page_end(hidden, headings, abstract_title) or 0) if opens else 0
    # A heading in capitals is not an abbreviation, and one that uses an abbreviation is
    # not where a reader expects it defined: the abbreviations are read without them.
    prose = _hide(hidden, (_heading_span(text, heading) for heading in headings)).replace(
        NUL, " "
    )
    statements = _run_in_statements(hidden, headings)
    regions = _regions(headings, chain, supplementary=supplementary, abstract_title=abstract_title,
                       lists=unmarked_reference_lists(text), statements=statements,
                       keywords=_keywords_lists(text, hidden, headings))  # fmt: skip
    titled = [(heading.start, _heading_span(text, heading)[1], heading.level, heading.title)
              for heading in headings]  # fmt: skip
    # A glossary under a heading that names it, and one a paragraph of its own opens, as a
    # paper typed in Word has it with no title: "List of abbreviations and acronyms used".
    glossaries = glossary.united([*glossary.sections(titled, len(text)),
                                  *glossary.opened(prose, text, titled, _may_be_defined)])
    return _assembled(
        order, path, text, hidden, prose, regions,
        captions=tuple(glossary.markdown_captions(prose)),
        glossaries=glossaries,
        headed=bool(headings), supplementary=supplementary, code=code,
        tables=_markdown_tables(text),
        initials=_initials(prose, _contributions(hidden, titled, statements)),
        title_page=title_page,
    )  # fmt: skip


def _markdown_tables(text: str) -> tuple[tuple[int, int], ...]:
    """Where the lines of a Markdown file's tables run, each line from its start to its
    break: a pipe, a grid, a simple and a multiline table (`text.tables.table_lines`), read
    from the masked text, so that one in a fenced block or a comment is none."""
    lines = table_lines(kept_breaks(text, mask(text)))
    spans, at = [], 0
    for number, line in enumerate(text.split("\n")):
        if number in lines:
            spans.append((at, at + len(line)))
        at += len(line) + 1
    return tuple(spans)


#: The statements whose capitals are the authors' initials, by a word of the heading or the
#: label: "Authors' contributions", "CRediT authorship contribution statement", "Author
#: statement". Not the acknowledgements, the funding or the interests, whose capitals are
#: institutions as often as people, JAMA's "Additional contributions" among them, which are
#: its acknowledgements (round 2 of #611).
_CONTRIBUTED = re.compile(
    r"\b(?<!additional )(?:contributions?|contributors?(?:hip)?|author\s+statement)\b",
    re.IGNORECASE,
)
#: A bracket, round or square, on one line; and what may stand between the initials in one
#: that holds only initials: "(CD)", "(JB, CD)", "[JB and CD]", "(JB; CD)", "(JB & CD)".
_BRACKETED = re.compile(r"[(\[](?P<inside>[^()\[\]\n]{1,80})[)\]]")
_BETWEEN_INITIALS = " \t,;&"
#: An author's initials as a contributions statement writes them: two to four capitals,
#: "CD", "JMD", and "J-MD", which is taken whole and as "JMD", never as its parts: an `MD`
#: elsewhere is as often a mean difference.
_INITIALS_SPAN = range(2, 5)


def _people(prose: str, initials: frozenset[str]) -> frozenset[int]:
    """Where each word stands that is a person: an author's initials (`_initials`) in a
    bracket that holds nothing but such initials, "by a single author (CD)", "(JB and CD)".
    Anywhere else the letters are read as an abbreviation, since an author whose initials
    are AE would otherwise hide every undefined AE (DESIGN.md, Known gaps)."""
    if not initials:
        return frozenset()
    found: set[int] = set()
    for bracket in _BRACKETED.finditer(prose):
        inside = bracket.group("inside")
        named = [word for word in _WORD.finditer(inside) if word.group(0) != "and"]
        if not named or any(word.group(0) not in initials for word in named):
            continue
        # Nothing but the initials, "and" and the marks between them.
        if _WORD.sub("", inside).strip(_BETWEEN_INITIALS):
            continue
        found.update(bracket.start("inside") + word.start() for word in named)
    return frozenset(found)


def _contributions(
    hidden: str, titled: list[tuple[int, int, int, str]], statements: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Where a contributions statement runs: the body of a heading that names one, to the
    next heading of its level or above, and a paragraph a bold label that names one opens
    (`_run_in_statements`)."""
    ordered = sorted(titled)
    spans = []
    for index, (_start, end, level, title) in enumerate(ordered):
        if _QUIET.search(title) and _CONTRIBUTED.search(title):
            stop = next((later[0] for later in ordered[index + 1 :] if later[2] <= level),
                        len(hidden))  # fmt: skip
            spans.append((end, stop))
    for start, end in statements:
        opening = _RUN_IN.match(hidden, start)
        if opening is not None and _CONTRIBUTED.search(_ESCAPE.sub(r"\1", opening["label"])):
            spans.append((start, end))
    return spans


def _initials(prose: str, spans: Iterable[tuple[int, int]]) -> frozenset[str]:
    """The authors' initials a contributions statement names, "JMD, BC and CD designed the
    study": each word of two to four capitals in it. In a bracket of initials anywhere in
    the paper, "by a single author (CD)", such a word is a person (`_people`)."""
    found = set()
    for start, end in spans:
        for word in _WORD.finditer(prose, start, end):
            letters = word.group(0).replace("-", "")
            if len(letters) in _INITIALS_SPAN and letters.isalpha() and letters.isupper():
                found.update((word.group(0), letters))
    return frozenset(found)


def _assembled(
    order: int, path: Path, text: str, hidden: str, prose: str, regions: list[_Region], **more
) -> _File:
    """A file read: its regions, its definitions, and the texts each reading reads in. A
    glossary's entries are definitions, after those of its sentences."""
    ends = [*(region.start for region in regions[1:]), len(text)]
    spans = list(zip(regions, ends, strict=True))
    references = [(region.start, end) for region, end in spans if region.scope is None]
    # A reference list is quiet too, so this hides it with the rest.
    quiet = [(region.start, end) for region, end in spans if region.quiet]
    captions, glossaries = more.get("captions", ()), more.get("glossaries", ())
    raw = more.get("typed") or text
    listed = [(entry.at, _stem(entry.short, entry.long), entry.long)
              for span in glossaries for entry in glossary.entries(prose, raw, span)
              if _may_be_defined(entry.short)]  # fmt: skip
    definitions = [*_definitions(prose, raw), *listed]
    restating = frozenset(at for at, _short, _long in definitions
                          if _restates(captions, glossaries, at))  # fmt: skip
    more["code"] = _set_aside(more.get("code", ""), references)
    return _File(
        order=order,
        path=path,
        text=text,
        regions=regions,
        definitions=definitions,
        restating=restating,
        prose=prose,
        printed=_hide(hidden, references),
        spelt=_hide(hidden, quiet),
        **more,
    )


def _latex_read(root: Path, abstract_title: str | None) -> list[_File]:
    """A LaTeX manuscript as a reader meets it: the main text's document, then the
    supplement's, each in stretches in the order the build prints them, a file input where
    its `\\input` ends. So a word in the entry file after an `\\input` is read after the
    words of the file input there, as LaTeX prints it."""
    from manuscript_guard.text.latex.structure import read_document

    files: list[_File] = []
    for supplementary in (False, True):
        read: dict[str, _LatexFile] = {}
        document = read_document(root, supplementary=supplementary)
        for source, start, end in _stretches(document.sources):
            if source.path not in read:
                read[source.path] = _latex_file(source, supplementary, abstract_title)
            whole = read[source.path]
            outside = ((0, start), (end, len(source.text)))
            files.append(_assembled(
                len(files), root / source.path, whole.view, _hide(whole.words, outside),
                _hide(whole.untitled, outside).replace(NUL, " "), whole.regions,
                breaks=whole.breaks, stretch=(start, end), typed=source.text,
                unread=tuple(span for span in whole.unread if start <= span[0] < end),
                captions=whole.captions, glossaries=whole.glossaries,
                supplementary=supplementary, code=_hide(whole.code, outside),
                tables=whole.cells, initials=whole.initials,
            ))  # fmt: skip
    return files


@dataclass(frozen=True)
class _LatexFile:
    """What G14 reads of a LaTeX file, worked out once for each of its stretches: the file as
    Markdown writes it, `\\mg{results.key}` as `{{results.key}}`, which the notation reads a
    bound value in and a finding quotes; its words (`text/latex/words.py`), and less its
    headings' titles; its regions; where its lines break; and the words it cannot read."""

    view: str
    words: str
    untitled: str
    regions: list[_Region]
    breaks: list[int]
    unread: tuple[tuple[int, int], ...]
    #: Where its captions' text runs, and its glossaries' bodies.
    captions: tuple[tuple[int, int], ...] = ()
    glossaries: tuple[tuple[int, int], ...] = ()
    #: The text of its code, `\\verb` and `\\texttt`, as the reader masks it, NUL elsewhere.
    code: str = ""
    #: The authors' initials its contributions statement names (`_initials`).
    initials: frozenset[str] = frozenset()
    #: Where its tables' cells run (`_latex_cells`).
    cells: tuple[tuple[int, int], ...] = ()


#: A note's text, `\\footnote` or `\\tablefootnote`, which a table's cell prints at the foot.
_NOTE_ARGUMENT = re.compile(
    r"\\(?:table)?footnote(?:text)?(?![A-Za-z])\s*(?:\[[^\[\]]*\]\s*)?\{")


def _latex_cells(
    source: Source, captions: Iterable[tuple[int, int]]
) -> tuple[tuple[int, int], ...]:
    """Where a LaTeX file's tables run (the reader's `tables`: a `tabular` and its kin), less
    the text of each caption and each footnote in them, which is prose: only the cells are no
    sentence (round 1 of #673, finding 2)."""
    from manuscript_guard.text.latex.printed import _arguments, _passed_over

    read, comments = _passed_over(source.reading)
    notes = [(opened + 1, closed) for begun, opened, closed
             in _arguments(source.text, _NOTE_ARGUMENT, 0, len(source.text), comments)
             if read(begun)]  # fmt: skip
    holes = sorted([*captions, *notes])
    cells: list[tuple[int, int]] = []
    for start, end in source.reading.tables:
        at = start
        for low, high in holes:
            if high <= at or low >= end:
                continue
            if low > at:
                cells.append((at, low))
            at = max(at, high)
        if at < end:
            cells.append((at, end))
    return tuple(cells)


def _latex_file(source: Source, supplementary: bool, abstract_title: str | None) -> _LatexFile:
    from manuscript_guard.text.latex.views import bindings, markdown_view
    from manuscript_guard.text.latex.words import _preamble, words

    seen = words(source)
    titles = [(heading.start, max(heading.end, heading.start))
              for heading in source.reading.headings]  # fmt: skip
    titled = [(heading.start, max(heading.end, heading.start), heading.level, heading.title)
              for heading in source.reading.headings]  # fmt: skip
    regions = _latex_regions(source, supplementary=supplementary, abstract_title=abstract_title)
    # A word in a reference list is none G14 skips: it reads no word there, and a typed
    # list's accented names were said unread (round 1 of step 7).
    starts = [region.start for region in regions]
    unread = tuple(span for span in seen.unread
                   if regions[bisect_right(starts, span[0]) - 1].scope is not None)  # fmt: skip
    # An RRID's accession is read neither as words nor as a name from the code.
    accessions = _rrids(source.reading.masked)
    captions = tuple(glossary.latex_captions(source))
    return _LatexFile(
        view=_hide(markdown_view(source, bindings(source)[0]), accessions),
        words=_hide(seen.text, accessions),
        untitled=_hide(seen.text, [*titles, *accessions]),
        regions=regions,
        breaks=[index for index, char in enumerate(source.text) if char == "\n"],
        unread=unread,
        captions=captions,
        cells=_latex_cells(source, captions),
        glossaries=tuple(glossary.sections(titled, len(source.text))),
        initials=_initials(seen.text, _contributions(seen.text, titled, [])),
        code=_set_aside(_only(source.reading.masked, source.reading.code),
                        [*_preamble(source.reading), *source.reading.figures]),
    )  # fmt: skip


def _stretches(sources) -> Iterator[tuple[Source, int, int]]:
    """Each stretch of each file, `(source, start, end)`, in the order the build prints them:
    a file up to an `\\input` it holds, the file input there, then the rest of it. `sources`
    are in the include tree's order, each file before the files it inputs; the author's
    packages, which no `\\input` reads, come last."""
    # A file input is text whatever the case of its suffix: `Methods.TEX`, which the file
    # list holds where the file system's names are not case-sensitive, is read as
    # `methods.tex` is (round 1 of step 7).
    texts = [source for source in sources if not _package(source)]
    queue = iter(texts)

    def of(source: Source) -> Iterator[tuple[Source, int, int]]:
        at = 0
        for cut in _input_ends(source):
            yield source, at, cut
            following = next(queue, None)
            if following is not None:
                yield from of(following)
            at = cut
        yield source, at, len(source.text)

    for source in queue:
        yield from of(source)
    for source in sources:
        if _package(source):
            yield source, 0, len(source.text)


def _package(source: Source) -> bool:
    """Whether a source is the author's package, `macros.sty`, which no `\\input` reads."""
    return source.path.lower().endswith(".sty")


def _input_ends(source: Source) -> list[int]:
    """Where each file the source inputs ends its `\\input`, in order: the include tree reads
    each file there, and lists it next."""
    return [end for end, _after in source.resumes]


def _read(project: Project) -> list[_File]:
    """The manuscript as a reader meets it: the paper's files in printed order, then the
    supplement's. The abstract is the section the journal's profile names as one, where it
    names one ("Summary"), as G4 reads it."""
    from manuscript_guard.gates.journal import abstract_title
    from manuscript_guard.text.reader import LATEX, manuscript_format

    named = abstract_title(project)
    root = project.path("manuscript")
    if manuscript_format(root) == LATEX:
        return _latex_read(root, named)
    sources = source_files(root)
    paper = printed_order(
        [p for p in sources if not is_supplementary(root, p)], supplementary=False
    )
    supplement = printed_order(
        [p for p in sources if is_supplementary(root, p)], supplementary=True
    )
    files: list[_File] = []
    for document, supplementary in ((paper, False), (supplement, True)):
        chain: list[Section] = []
        for at, path in enumerate(document):
            text = read_text(path)
            files.append(_file(len(files), path, text, chain, supplementary, named, at == 0))
    return files


def _collect(files: list[_File], known: _Known) -> dict[str, _Scope]:
    scopes = {name: _Scope(name) for name in (ABSTRACT, BODY, SUPPLEMENT)}
    defined: set[str] = set()
    defining: set[tuple[int, int]] = set()

    for file in files:
        for offset, short, long in file.definitions:
            region = file.region_at(offset)
            # Nothing on the title page is a definition: its institutions' names are not
            # the paper's terms (Basile, 2026-11-12).
            if region.scope is None or _on_the_title_page(file, offset):
                continue
            defined.add(short)
            defining.add((file.order, offset))
            scopes[region.scope].defined.setdefault(short, []).append(
                _Definition(file.order, offset, region.quiet, long, offset in file.restating)
            )

    # The authors' initials a contributions statement names, which are people in a bracket
    # of initials anywhere in the paper: "by a single author (CD)".
    initials = frozenset().union(*(file.initials for file in files))
    for file in files:
        capitals = _in_capitals(file.prose)
        starts = [start for start, _end in capitals]
        people = _people(file.prose, initials)
        for word in _WORD.finditer(_CLOCK.sub(lambda time: " " * len(time[0]), file.prose)):
            token = word.group(0)
            if token.islower() or token.isdigit():
                continue
            region = file.region_at(word.start())
            # A glossary's lines are its entries, and none of them is a use; nor is a word
            # of the title page, its departments, units and institutions.
            if (region.scope is None or _in_a_glossary(file, word.start())
                    or _on_the_title_page(file, word.start())):  # fmt: skip
                continue
            at = bisect_right(starts, word.start()) - 1
            shouted = at >= 0 and word.start() < capitals[at][1]
            for within, short, is_defined in _forms(token, defined, known):
                offset = word.start() + within
                if (file.order, offset) in defining:
                    continue
                if not is_defined and offset in people:
                    continue
                # A word of a heading typed in capitals, or of a table's label, is a use of
                # what the manuscript defines and is not reported as undefined.
                if not is_defined and (region.quiet or shouted):
                    continue
                if not is_defined:
                    # `CO~2~`: the word is `CO`, and with its subscript it is a formula.
                    count = _SUBSCRIPT.match(file.prose, offset + len(short))
                    if count is not None and _formula(short + count.group(1)):
                        continue
                scopes[region.scope].used.setdefault(short, []).append(
                    _Mark(file.order, offset, region.quiet)
                )
    return scopes


def _same_meaning(one: str, other: str) -> bool:
    def plain(long: str) -> str:
        words = re.sub(r"[-\s]+", " ", long.lower()).strip()
        for article in _ARTICLES:
            if words.startswith(article):
                words = words[len(article) :]
        return words.rstrip("s")

    return plain(one) == plain(other)


def _given_again(
    short: str, definitions: list[_Definition], said
) -> list[tuple[_Definition, str, str]]:
    """Each definition of `short` after the first that is a finding, with its message and
    hint: one that gives another meaning than the first, wherever it stands; and one that
    gives the same meaning again, unless a caption or a glossary gives it, which may restate
    what the text defines, or none of the text's own came before it. `definitions` are in
    the order they stand; `said(mark, here)` names where `mark` stands, seen from `here`."""
    first = definitions[0]
    given: _Definition | None = None
    found = []
    for again in definitions:
        if again is not first and not _same_meaning(first.long, again.long):
            found.append((
                again,
                # The long forms quoted as typed: `repr` doubled a backslash an escape had,
                # "d\'Intérêt" (the author's audit, 2026-11-11).
                f"{short} is defined as '{again.long}' here and as '{first.long}' "
                f"{said(first, again)}",
                "one short form, one meaning: a reader keeps the first",
            ))  # fmt: skip
        elif again is not first and not again.restates and given is not None:
            found.append((
                again,
                f"{short} is defined again; it was defined {said(given, again)}",
                "define an abbreviation once and use the short form after that",
            ))  # fmt: skip
        if given is None and not again.restates:
            given = again
    return found


def _headless(files: list[_File]) -> Finding | None:
    """The note that the main text of a Markdown manuscript has no heading at all, so that
    its abstract and its sections are read as one text; None where it has one."""
    paper = [file for file in files if file.headed is not None and not file.supplementary]
    if not paper or any(file.headed for file in paper):
        return None
    return Finding(
        gate=GATE,
        code="no-headings",
        severity=INFO,
        message="the manuscript has no headings, so its abstract and main text are read as "
        "one; abbreviation-redefined is not reported",
        path=paper[0].path,
        hint="give each section a Markdown heading, `# Abstract`, `# Methods`: a line in bold "
        "is not one",
    )


def _says_headless(stage: str | None) -> bool:
    """Whether the `no-headings` note is said at this stage: once, at drafting (Basile,
    2026-10-23), when the sections are being written. At any other stage, or where `check`
    gave none, the paper is still read as one text, and the note is not said."""
    return stage == DRAFTING


def _judge(files: list[_File], known: _Known, root: Path, stage: str | None = None) -> Report:
    """The findings, from files already read, at `stage` where one is given. Apart from
    `check_language` so that what it costs can be measured on a manuscript of any size
    without writing one to disk."""
    scopes = _collect(files, known)

    def where(mark: _Mark) -> str:
        file = files[mark.order]
        try:
            shown = file.path.relative_to(root).as_posix()
        except ValueError:
            shown = str(file.path)
        return f"{shown}:{file.line_of(mark.offset)}"

    def placed(mark: _Mark, here: _Mark, at: str, beside: str) -> str:
        """Where `mark` stands, said from `here`: `beside` where it is on the same line of
        the same file, which `at` and the place would name as though it were another
        (corpus round, 2026-10-23: "defined later at main.tex:158" of a use on line 158)."""
        one, other = files[mark.order], files[here.order]
        same = one.path == other.path and one.line_of(mark.offset) == other.line_of(here.offset)
        return beside if same else f"{at} {where(mark)}"

    def listed(mark: _Mark) -> bool:
        """Whether `mark` stands in a list of abbreviations, whose entries are said as such
        (the author's audit, 2026-11-11: "defined later at ... Conclusions, paragraph 26" of
        the list at the end, and "write '...' out and drop the short form" of its entries)."""
        return _in_a_glossary(files[mark.order], mark.offset)

    def finding(code: str, mark: _Mark, short: str, message: str, hint: str) -> Finding:
        file = files[mark.order]
        return Finding(
            gate=GATE,
            code=code,
            severity=WARN,
            message=message,
            path=file.path,
            line=file.line_of(mark.offset),
            context=context(file.text, mark.offset, len(short)),
            hint=hint,
        )

    findings: list[Finding] = []
    everything: set[str] = set()
    defined_anywhere: set[str] = set()
    title_paged = _on_title_pages(files)
    headless = _headless(files)
    if headless is not None and _says_headless(stage):
        findings.append(headless)

    for scope in scopes.values():
        everything.update(scope.defined, scope.used)
        defined_anywhere.update(scope.defined)

        for short, definitions in scope.defined.items():
            definitions.sort(key=lambda mark: mark.key)
            first = definitions[0]
            uses = sorted(scope.used.get(short, ()), key=lambda mark: mark.key)

            if uses and uses[0].key < first.key and all(listed(mark) for mark in definitions):
                # Defined only in the list of abbreviations, after this use: the text owes
                # the long form at first use as well, as most journals ask. Where the text
                # spells it out too, after the list, it is defined later there, as before
                # (review of #634).
                findings.append(
                    finding(
                        "abbreviation-used-before-defined",
                        uses[0],
                        short,
                        f"{short} is used here and not spelt out; only the list of "
                        "abbreviations defines it, "
                        + placed(first, uses[0], "at", "on the same line"),
                        "spell it out where it first appears, the long form then the short "
                        "form in brackets: most journals ask for that besides the list",
                    )
                )
            elif uses and uses[0].key < first.key:
                findings.append(
                    finding(
                        "abbreviation-used-before-defined",
                        uses[0],
                        short,
                        f"{short} is used here, and defined "
                        + placed(first, uses[0], "later at", "later on the same line"),
                        "define an abbreviation where it first appears: the long form, then "
                        "the short form in brackets",
                    )
                )

            # Without headings nothing tells the abstract from the main text, so a
            # definition the abstract repeats would be reported as one given twice.
            for again, message, hint in [] if headless and scope.name == BODY else (
                _given_again(
                    short,
                    definitions,
                    lambda mark, here: placed(mark, here, "at", "earlier on the same line"),
                )
            ):
                findings.append(finding("abbreviation-redefined", again, short, message, hint))

            # A funder or a society named in full with its acronym, once, is how those
            # statements are written; nothing later is expected to use it.
            if not uses and not first.quiet and all(listed(mark) for mark in definitions):
                # An entry of the list of abbreviations nothing else uses: the list's to drop,
                # not the text's to write out. Its use on the title page is one: the list
                # covers the title page's units and institutions too (Basile, 2026-11-12,
                # "Yes, count it"). It is the only use the title page makes.
                if short not in title_paged.get(scope.name, ()):
                    findings.append(
                        finding(
                            "abbreviation-unused",
                            first,
                            short,
                            # Not "nowhere else": another entry of the list may use it, and
                            # the list's lines are no uses (review of #634).
                            f"{short} is in the list of abbreviations and not used in the "
                            f"{scope.name} as G14 reads it",
                            "take it out of the list, unless a table, a figure, another entry "
                            "of the list or the supplementary material uses it: tables and "
                            "figures are not read here",
                        )
                    )
            elif not uses and not first.quiet and not _leaned_on(scopes, scope.name, short):
                findings.append(
                    finding(
                        "abbreviation-unused",
                        first,
                        short,
                        f"{short} is defined and not used again in the {scope.name} as G14 "
                        "reads it",
                        f"write '{first.long}' out and drop the short form, unless a table "
                        "or a figure uses it: those are not read here"
                        + ("; the title page uses it, and is not read for abbreviations"
                           if short in title_paged.get(scope.name, ()) else ""),
                    )  # fmt: skip
                )

        for short, uses in scope.used.items():
            if short in scope.defined or short in known:
                continue
            if scope.name == SUPPLEMENT and short in scopes[BODY].defined:
                continue
            # A use among the acknowledgements counts as a use, and is not where a reader
            # is owed the definition.
            uses = sorted((use for use in uses if not use.quiet), key=lambda mark: mark.key)
            if not uses:
                continue
            times = "once" if len(uses) == 1 else f"{len(uses)} times"
            # As G14 reads it: not a figure's caption or a LaTeX `comment` (DESIGN.md, Known
            # gaps), so a use or a definition there is not counted (corpus round, 2026-11-10).
            message = (f"{short} is used {times} in the {scope.name} as G14 reads it, and not "
                       "defined there")  # fmt: skip
            if scope.name == BODY and short in scopes[ABSTRACT].defined:
                message += "; the abstract defines it, and is read apart from the paper"
            findings.append(
                finding(
                    "abbreviation-undefined",
                    uses[0],
                    short,
                    message,
                    "define it at first use, or list it in quotes under `language: "
                    "known_abbreviations:` in paper.yaml if this journal's readers take it "
                    "for a word or a name",
                )
            )

    return Report(
        tuple(findings),
        {"abbreviations_read": len(everything), "abbreviations_defined": len(defined_anywhere)},
    )


def check_language(
    project: Project, stage: str | None = None, results: Results | None = None
) -> Report:
    """The five readings of the manuscript: its abbreviations, the terms it keeps to, its
    spelling, its notation and the names from its code; and where its prose is in a script
    none of them reads. `stage` is the one `check` runs at, which decides whether
    `no-headings` is said and whether a name from the code fails. `results` are the
    analysis's, read from the project where they are not given."""
    files = _read(project)
    passages = [Passage(file.path, file.text, file.printed, file.line_of) for file in files]
    prose = [Prose(file.path, file.text, file.printed, file.code, file.line_of, file.tables)
             for file in files]  # fmt: skip
    # A contributions statement names its roles as CRediT spells them and a funding
    # statement is worded by the funder, so the spelling is read without those sections.
    # The vocabulary is read in them: a term the author gave up is the author's there too.
    spelt = [Passage(file.path, file.text, file.spelt, file.line_of) for file in files]
    paper = project.root / PAPER_FILE
    return (
        _judge(files, _known(project), project.root, stage)
        .merge(judge_vocabulary(passages, project.vocabulary, paper))
        .merge(
            judge_spelling(spelt, project.english_variant, project.accepted_spellings, paper)
        )
        # A P value in an acknowledgement is the author's, so this one reads them all.
        .merge(judge_notation(passages))
        .merge(judge_code_names(prose, _code_names(project, results), stage))
        # And where the prose is in a script none of the readings is written for, said once
        # for each file, which a LaTeX file read in stretches is again here.
        .merge(judge_scripts(_whole(files)))
        .merge(_not_read(files))
    )


def language_edits(project: Project) -> list[Edit]:
    """The exact edits G14's readings would make (`corrections.py`), the manuscript read as
    `check_language` reads it: each abbreviation defined and not used again written out,
    each word of the other English respelt, and the notation set as the manuscript's own."""
    files = _read(project)
    passages = [Passage(file.path, file.text, file.printed, file.line_of) for file in files]
    spelt = [Passage(file.path, file.text, file.spelt, file.line_of) for file in files]
    return (abbreviation_edits(files, _known(project))
            + spelling_edits(spelt, project.english_variant, project.accepted_spellings)
            + notation_edits(passages))  # fmt: skip


def abbreviation_edits(files: list[_File], known: _Known) -> list[Edit]:
    """Each abbreviation `abbreviation-unused` says is defined and not used again, written
    out where it is defined, at every place: "the reporting odds ratio (ROR)" becomes "the
    reporting odds ratio", and "ROR (reporting odds ratio)" becomes "reporting odds ratio",
    with a capital where it opens a sentence (the author, 2026-11-11). Only where the
    bracket holds the one form and nothing more; not an entry of a list of abbreviations,
    which the list is to drop; not a definition among the acknowledgements, where a funder
    is named in full with its acronym; and not the main text's where the supplementary
    material uses the form, which the main text's definition serves (round 1 of #645)."""
    edits = []
    scopes = _collect(files, known)
    for name, scope in scopes.items():
        for short, definitions in scope.defined.items():
            definitions = sorted(definitions, key=lambda mark: mark.key)
            if scope.used.get(short) or definitions[0].quiet:
                continue
            if _leaned_on(scopes, name, short):
                continue
            for mark in definitions:
                file = files[mark.order]
                if _kept(file, mark):
                    continue
                edit = _written_out(file, mark, short)
                edits += [edit] if edit is not None else []
    return edits


#: "a" or "an" before a short form, which was chosen for how the short form is said: "an
#: SAE (serious adverse event)" written out would read "an serious adverse event". Across
#: a line break, a no-break space, a LaTeX tie or a mark of emphasis or quotation as well
#: (round 2 of #645).
_AN_ARTICLE = re.compile(rf"(?<![\w-])an?[\s~{re.escape(_QUOTES)}]+\Z", re.IGNORECASE)


def _after_an_article(text: str, at: int) -> bool:
    """Is the short form at `at` after "a" or "an", which no edit puts right (rounds 1 and
    2 of #645)?"""
    return _AN_ARTICLE.search(text, max(0, at - 16), at) is not None


def _runs_on(text: str, end: int) -> bool:
    """Does a square bracket closing just before `end` run on into a link's address, a
    reference or a span's attributes, "[ROR](https://...)", "[HR]{.smallcaps}" (round 1 of
    #645)? A round bracket is no link's: "(ROR)[@smith2020]" is a definition and a citation
    (round 2 of #645)."""
    return text[end - 1 : end] == "]" and text[end : end + 1] in ("(", "[", "{")


def _takes_a_capital(long: str) -> bool:
    """Does the long form take the capital of a sentence it opens: not where its first word
    keeps a case of its own, "mRNA vaccine" (round 2 of #645)."""
    return long.split()[0].islower()


def _kept(file: _File, mark: _Definition) -> bool:
    """Is the definition at `mark` one no edit writes out: a funder's among the
    acknowledgements, named in full with its acronym, or an entry of a list of
    abbreviations, which the list is to drop?"""
    return mark.quiet or _in_a_glossary(file, mark.offset)


def _leaned_on(scopes: dict, name: str, short: str) -> bool:
    """Is the main text's definition of `short` what the supplementary material's use of it
    leans on, so that it is used after all (rounds 1 and 2 of #645)? Not where the
    supplementary material defines it itself (round 3 of #645)."""
    supplement = scopes[SUPPLEMENT]
    return name == BODY and bool(supplement.used.get(short)) and short not in supplement.defined


def _written_out(file: _File, mark: _Definition, short: str) -> Edit | None:
    """The edit that drops the short form of one definition, or None where it is not one
    of the two shapes an edit is sure of."""
    text, at, long = file.text, mark.offset, mark.long
    end = at + len(short)
    if text[at:end] != short or not long:
        return None
    passage = Passage(file.path, file.text, file.printed, file.line_of)
    bracket = text[at - 1 : at] + text[end : end + 1]
    if (bracket in ("()", "[]") and text[at - 2 - len(long) : at - 1] == long + " "
            and not _runs_on(text, end + 1)):  # fmt: skip
        return Edit("abbreviation-unused", passage, at - 2, end + 1, "",
                    (at - 2 - len(long), end + 1))  # fmt: skip
    after = f" ({long})"
    if text[end : end + len(after)] == after and not _after_an_article(text, at):
        opens = opens_a_sentence(text, at) and _takes_a_capital(long)
        spelt = long[:1].upper() + long[1:] if opens else long
        return Edit("abbreviation-unused", passage, at, end + len(after), spelt,
                    (at, end + len(after)))  # fmt: skip
    return None


def _code_names(project: Project, results: Results | None) -> Names:
    """The names the code-name reading looks for: the keys of the results, the labels of
    the dictionary's variables by their names, and the words the paper keeps. A dictionary
    that cannot be read gives no names here; G12 reports what is wrong with it."""
    if results is None:
        results, _report = load_results(project.path("results"))
    dictionary, _report = load_dictionary(project)
    labels = {} if dictionary is None else {v.name: v.label for v in dictionary.variables}
    return Names(frozenset(results.values), labels, frozenset(project.code_names_kept))


def _whole(files: list[_File]) -> list[Passage]:
    """Each file once, in the order it is first read, its stretches put back together."""
    stretches: dict[Path, list[_File]] = {}
    for file in files:
        stretches.setdefault(file.path, []).append(file)
    passages = []
    for path, parts in stretches.items():
        printed = "".join(part.printed[part.stretch[0] : part.stretch[1]]
                          for part in sorted(parts, key=lambda part: part.stretch))  # fmt: skip
        passages.append(Passage(path, parts[0].text, printed, parts[0].line_of))
    return passages


def _not_read(files: list[_File]) -> Report:
    """Once for each LaTeX file, how many of its words hold an accent command over no letter,
    which the reader cannot write as a letter, and so G14 does not read."""
    unread: dict[Path, list[tuple[_File, tuple[int, int]]]] = {}
    for file in files:
        unread.setdefault(file.path, []).extend((file, span) for span in file.unread)
    findings = []
    for path, found in unread.items():
        if not found:
            continue
        file, (start, end) = min(found, key=lambda each: each[1])
        typed = file.typed or file.text
        count = len(found)
        many = count != 1
        findings.append(Finding(
            gate=GATE, code="tex-words-not-read", severity=WARN, path=path,
            message=f"{count} word{'s' if many else ''} here hold{'' if many else 's'} an accent "
            f"command over no letter, and G14 does not read {'them' if many else 'it'}: the "
            f"first is {typed[start:end]!r}",
            line=file.line_of(start), context=context(typed, start, end - start),
            hint="put the accent over its letter, `\\'{e}` rather than `\\'{}e`, or type the "
            "accented letter as itself: the file is read as UTF-8",
        ))  # fmt: skip
    return Report(tuple(findings))
