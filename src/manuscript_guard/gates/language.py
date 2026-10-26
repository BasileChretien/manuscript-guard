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
definitions and is otherwise held to its own.

The gate has three more readings: of the terms the paper keeps to, in
`gates/vocabulary.py`, of its spelling, in `gates/spelling.py`, and of its notation, in
`gates/notation.py`. They take the files read here, so the manuscript is masked once,
and `check_language` gives all four, and says where the prose is in a script none of
them reads (`gates/scripts.py`).
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import PAPER_FILE, Project
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates import glossary
from manuscript_guard.gates.notation import judge_notation
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.gates.scripts import judge_scripts
from manuscript_guard.gates.spelling import judge_spelling
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
from manuscript_guard.text.masking import NUL, front_matter_end, mask
from manuscript_guard.text.reference_lists import unmarked_reference_lists
from manuscript_guard.text.sections import Section

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

# A word, with the hyphens that join its parts. Unicode letters and digits, no underscore.
_WORD = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
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
    rf"[\s{re.escape(_QUOTES)}]*(?P<short>[^\W_]+(?:-[^\W_]+)*)[\s{re.escape(_QUOTES)}]*"
    r"(?:$|[;,:])"
)
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
_BEFORE_PAREN = re.compile(r"(?P<short>[^\W_]+(?:-[^\W_]+)*)[ \t]?$")
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
    masked = mask(text)
    code = code_spans(masked)
    spans = [
        (0, front_matter_end(text)),
        *code,
        *equation_spans(masked, code),
        *(found.span() for found in _IMAGE.finditer(text)),
    ]
    kept = "".join(
        "\n" if char == NUL and text[index] == "\n" else char
        for index, char in enumerate(masked)
    )
    return _hide(kept, spans)


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
) -> list[_Region]:
    """Which text each stretch of a file belongs to. `chain` is the headings a reader is
    under, carried from one file of a document into the next: a file that opens without a
    heading continues the section the last one ended in. `lists` are the reference lists
    under a line that is no heading (`unmarked_reference_lists`): each is read as the list
    under `# References` is, and the text after it as the text before it."""

    def here(start: int) -> _Region:
        return _region(start, chain, supplementary=supplementary, abstract_title=abstract_title)

    regions = [here(0)]
    for heading in headings:
        while chain and chain[-1].level >= heading.level:
            chain.pop()
        chain.append(Section(title=heading.title, level=heading.level, body="", line=0))
        regions.append(here(heading.start))
    for start, end in lists:
        before = [region for region in regions if region.start < start]
        after = [region for region in regions if region.start >= end]
        resumed = [region for region in regions if region.start <= end][-1]
        regions = [*before, _Region(start, None, True)]
        if not after or after[0].start > end:
            regions.append(_Region(end, resumed.scope, resumed.quiet))
        regions += after
    return regions


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


def _inside(spans: tuple[tuple[int, int], ...], offset: int) -> bool:
    """`_within` for spans in order and none inside another, by halving."""
    at = bisect_right(spans, (offset, float("inf"))) - 1
    return at >= 0 and spans[at][0] <= offset < spans[at][1]


def _in_capitals(prose: str) -> list[tuple[int, int]]:
    """Where `prose` holds a heading typed in capitals: a paragraph set entirely in bold
    whose letters are all capitals, "**ABSTRACT**", which is how a manuscript converted from
    Word writes a heading, pandoc making one only of a heading style; and a cell of a
    table's header row whose letters are, "MODEL 1". Not a table's body, whose cells name
    what the rows count, `COPD` among them, nor a plain paragraph or a list item. In order,
    and none inside another."""
    spans: list[tuple[int, int]] = []
    start = 0
    for gap in (*_BLANK_LINE.finditer(prose), None):
        end = len(prose) if gap is None else gap.start()
        paragraph = prose[start:end]
        if _BOLD.fullmatch(paragraph) and paragraph.isupper():
            spans.append((start, end))
        else:
            spans += _header_cells(prose, start, end)
        if gap is not None:
            start = gap.end()
    return sorted(spans)


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
    before = prose[max(0, bracket.start() - 400) : bracket.start()]
    before = _BLANK_LINE.split(before)[-1]
    words = " ".join(before.split()[-_window(short) :])
    long = _long_form(short, words)
    if long is None and short != _singular(short):
        long = _long_form(_singular(short), words)
    if long is None:
        return None
    return bracket.start(1) + opening.start("short"), _stem(short, long), long


def _long_inside(prose: str, bracket: re.Match[str]) -> tuple[int, str, str] | None:
    """A definition with its long form in the bracket: "ROR (reporting odds ratio)"."""
    standing = _BEFORE_PAREN.search(prose, max(0, bracket.start() - LONGEST - 1), bracket.start())
    if standing is None or not _may_be_defined(standing.group("short")):
        return None
    # The search starts a short form's length back, so it can start inside a word.
    head = standing.start("short")
    if head > 0 and (prose[head - 1].isalnum() or prose[head - 1] == "-"):
        return None
    short = standing.group("short")
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


def _definitions(prose: str) -> list[tuple[int, str, str]]:
    """Every definition in `prose`: where its short form stands, the form it defines, and
    the long form. Both orders in round brackets, "reporting odds ratio (ROR)" and "ROR
    (reporting odds ratio)", and the short form in square ones, "hazard ratio [HR]"."""
    found: list[tuple[int, str, str]] = []
    for bracket in _PAREN.finditer(prose):
        if _BLANK_LINE.search(bracket.group(1)):
            continue
        definition = _short_inside(prose, bracket) or _long_inside(prose, bracket)
        if definition is not None:
            found.append(definition)
    for bracket in _SQUARE.finditer(prose):
        if _BLANK_LINE.search(bracket.group(1)):
            continue
        definition = _short_inside(prose, bracket)
        if definition is not None:
            found.append(definition)
    return found


def _listed_as(form: str, known: _Known) -> bool:
    """Is this word, or the singular it is the plural of, one the lists exempt? Any final
    `s` counts, as for a defined abbreviation: `PARPis` for a listed `PARPi`."""
    return form in known or (form.endswith("s") and form[:-1] in known)


def _named(
    parts: list[str], starts: list[int], index: int, defined: set[str], known: _Known
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
        rest = "-".join(parts[index + 1 : stop])
        for form in dict.fromkeys((f"{opening}-{rest}", f"{lowered}-{rest}")):
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
    parts: list[str], starts: list[int], begin: int, end: int, defined: set[str], known: _Known
) -> list[tuple[int, str, bool]]:
    """The abbreviations in one stretch of a hyphenated word that holds no ordinary word.

    Read whole where the whole is defined or known, `SARS-CoV-2`. Where nothing in it is,
    it is reported whole, so `LC-MS` is one abbreviation and not `LC` and `MS`, and a
    trial is named `KEYNOTE-189`, as its definition would name it."""
    found: list[tuple[int, str, bool]] = []
    loose: list[int] = []
    index = begin
    while index < end:
        for stop in range(end, index, -1):
            form = "-".join(parts[index:stop])
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
    whole = _singular("-".join(parts[begin:end]))
    if not found and shaped and len(whole) <= LONGEST:
        return [(starts[begin], whole, False)]
    found = [entry for entry in found if entry[1]]
    return found + [(starts[index], _singular(parts[index]), False) for index in shaped]


def _forms(token: str, defined: set[str], known: _Known) -> list[tuple[int, str, bool]]:
    """The abbreviations in one word: where each starts in it, its short form, and whether
    it is one the manuscript defines."""
    parts = token.split("-")
    starts = [0]
    for part in parts[:-1]:
        starts.append(starts[-1] + len(part) + 1)
    found: list[tuple[int, str, bool]] = []
    joined = len(parts) <= _JOINED_PARTS
    index = 0
    while index < len(parts):
        named = _named(parts, starts, index, defined, known) if joined else None
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
        found += _run(parts, starts, index, stop, defined, known)
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
) -> _File:
    headings = find_headings(text)
    hidden = _hidden(text)
    # A heading in capitals is not an abbreviation, and one that uses an abbreviation is
    # not where a reader expects it defined: the abbreviations are read without them.
    prose = _hide(hidden, (_heading_span(text, heading) for heading in headings)).replace(
        NUL, " "
    )
    regions = _regions(headings, chain, supplementary=supplementary, abstract_title=abstract_title,
                       lists=unmarked_reference_lists(text))  # fmt: skip
    titled = [(heading.start, _heading_span(text, heading)[1], heading.level, heading.title)
              for heading in headings]  # fmt: skip
    return _assembled(
        order, path, text, hidden, prose, regions,
        captions=tuple(glossary.markdown_captions(prose)),
        glossaries=tuple(glossary.sections(titled, len(text))),
        headed=bool(headings), supplementary=supplementary,
    )  # fmt: skip


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
    definitions = [*_definitions(prose), *listed]
    restating = frozenset(at for at, _short, _long in definitions
                          if _restates(captions, glossaries, at))  # fmt: skip
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
                supplementary=supplementary,
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


def _latex_file(source: Source, supplementary: bool, abstract_title: str | None) -> _LatexFile:
    from manuscript_guard.text.latex.views import bindings, markdown_view
    from manuscript_guard.text.latex.words import words

    seen = words(source)
    titles = [(heading.start, max(heading.end, heading.start))
              for heading in source.reading.headings]  # fmt: skip
    regions = _latex_regions(source, supplementary=supplementary, abstract_title=abstract_title)
    # A word in a reference list is none G14 skips: it reads no word there, and a typed
    # list's accented names were said unread (round 1 of step 7).
    starts = [region.start for region in regions]
    unread = tuple(span for span in seen.unread
                   if regions[bisect_right(starts, span[0]) - 1].scope is not None)  # fmt: skip
    return _LatexFile(
        view=markdown_view(source, bindings(source)[0]),
        words=seen.text,
        untitled=_hide(seen.text, titles),
        regions=regions,
        breaks=[index for index, char in enumerate(source.text) if char == "\n"],
        unread=unread,
        captions=tuple(glossary.latex_captions(source)),
        glossaries=tuple(glossary.sections(
            [(heading.start, max(heading.end, heading.start), heading.level, heading.title)
             for heading in source.reading.headings], len(source.text))),
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
        for path in document:
            text = read_text(path)
            files.append(_file(len(files), path, text, chain, supplementary, named))
    return files


def _collect(files: list[_File], known: _Known) -> dict[str, _Scope]:
    scopes = {name: _Scope(name) for name in (ABSTRACT, BODY, SUPPLEMENT)}
    defined: set[str] = set()
    defining: set[tuple[int, int]] = set()

    for file in files:
        for offset, short, long in file.definitions:
            region = file.region_at(offset)
            if region.scope is None:
                continue
            defined.add(short)
            defining.add((file.order, offset))
            scopes[region.scope].defined.setdefault(short, []).append(
                _Definition(file.order, offset, region.quiet, long, offset in file.restating)
            )

    for file in files:
        capitals = _in_capitals(file.prose)
        starts = [start for start, _end in capitals]
        for word in _WORD.finditer(_CLOCK.sub(lambda time: " " * len(time[0]), file.prose)):
            token = word.group(0)
            if token.islower() or token.isdigit():
                continue
            region = file.region_at(word.start())
            # A glossary's lines are its entries, and none of them is a use.
            if region.scope is None or _in_a_glossary(file, word.start()):
                continue
            at = bisect_right(starts, word.start()) - 1
            shouted = at >= 0 and word.start() < capitals[at][1]
            for within, short, is_defined in _forms(token, defined, known):
                offset = word.start() + within
                if (file.order, offset) in defining:
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
                f"{short} is defined as {again.long!r} here and as {first.long!r} "
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

            if uses and uses[0].key < first.key:
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
            if not uses and not first.quiet:
                findings.append(
                    finding(
                        "abbreviation-unused",
                        first,
                        short,
                        f"{short} is defined and not used again in the {scope.name}",
                        f"write {first.long!r} out and drop the short form, unless a table "
                        "or a figure uses it: those are not read here",
                    )
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
            message = f"{short} is used {times} in the {scope.name} and not defined there"
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


def check_language(project: Project, stage: str | None = None) -> Report:
    """The four readings of the manuscript: its abbreviations, the terms it keeps to,
    its spelling and its notation; and where its prose is in a script none of them reads.
    `stage` is the one `check` runs at, which decides only whether `no-headings` is said."""
    files = _read(project)
    passages = [Passage(file.path, file.text, file.printed, file.line_of) for file in files]
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
        # And where the prose is in a script none of the readings is written for, said once
        # for each file, which a LaTeX file read in stretches is again here.
        .merge(judge_scripts(_whole(files)))
        .merge(_not_read(files))
    )


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
    """Once for each LaTeX file, how many of its words hold an accent command or `\\-`, which
    the reader cannot write with their letters side by side, and so G14 does not read."""
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
            f"command or \\-, and G14 does not read {'them' if many else 'it'}: the first is "
            f"{typed[start:end]!r}",
            line=file.line_of(start), context=context(typed, start, end - start),
            hint="the file is read as UTF-8, so type an accented letter as itself rather than "
            "as an accent command, and leave the hyphenation to LaTeX",
        ))  # fmt: skip
    return Report(tuple(findings))
