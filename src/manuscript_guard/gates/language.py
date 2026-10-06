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

The gate has two more readings: of the terms the paper keeps to, in
`gates/vocabulary.py`, and of its spelling, in `gates/spelling.py`. They take the files
read here, so the manuscript is masked once, and `check_language` gives all three.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import PAPER_FILE, Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
from manuscript_guard.gates.spelling import judge_spelling
from manuscript_guard.gates.vocabulary import (
    Passage,
    capitals_together,
    context,
    judge_vocabulary,
)
from manuscript_guard.paths import SHIPPED_RECIPES
from manuscript_guard.text.blocks import Heading, find_headings
from manuscript_guard.text.inline import code_spans, equation_spans
from manuscript_guard.text.masking import NUL, front_matter_end, mask
from manuscript_guard.text.sections import Section

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
# The short form opening a bracket: alone, or before a separator ("ROR; 95% CI ...").
_OPENS_WITH = re.compile(
    rf"[\s{re.escape(_QUOTES)}]*(?P<short>[^\W_]+(?:-[^\W_]+)*)[\s{re.escape(_QUOTES)}]*(?:$|[;,:])"
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
# "CRediT authorship contribution statement", "Role of the funding source".
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


def _known(project: Project) -> _Known:
    exact, lowered = _shipped()
    return _Known(
        exact
        | set(project.known_abbreviations)
        | _listed(project.paper.get("reporting_guideline")),
        lowered | {term.lower() for term in _listed(project.paper.get("terms"))},
    )


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
    """
    at = len(before) - 1
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
        at -= 1
    found = before[at + 1 :].strip().strip(_EDGES).strip()
    if len(found) <= len(short):
        return None
    # A short form does not define itself, nor through its plural: in "expressed as ORs
    # (OR, 95% CI)" the letters of OR are all in "ORs".
    words = {_singular(word.strip(_EDGES)).lower() for word in found.split()}
    if _singular(short).lower() in words:
        return None
    return found


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
    headings: list[Heading], chain: list[Section], *, supplementary: bool
) -> list[_Region]:
    """Which text each stretch of a file belongs to. `chain` is the headings a reader is
    under, carried from one file of a document into the next: a file that opens without a
    heading continues the section the last one ended in."""

    def here(start: int) -> _Region:
        if any(section.is_references for section in chain):
            return _Region(start, None, True)
        quiet = any(_QUIET.search(section.title) for section in chain)
        if supplementary:
            return _Region(start, SUPPLEMENT, quiet)
        abstract = any(section.is_abstract for section in chain)
        return _Region(start, ABSTRACT if abstract else BODY, quiet)

    regions = [here(0)]
    for heading in headings:
        while chain and chain[-1].level >= heading.level:
            chain.pop()
        chain.append(Section(title=heading.title, level=heading.level, body="", line=0))
        regions.append(here(heading.start))
    return regions


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
    starts: list[int] = field(default_factory=list)
    breaks: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.starts = [region.start for region in self.regions]
        self.breaks = [index for index, char in enumerate(self.text) if char == "\n"]

    def region_at(self, offset: int) -> _Region:
        return self.regions[bisect_right(self.starts, offset) - 1]

    def line_of(self, offset: int) -> int:
        return bisect_left(self.breaks, offset) + 1


def _file(order: int, path: Path, text: str, chain: list[Section], supplementary: bool) -> _File:
    headings = find_headings(text)
    hidden = _hidden(text)
    # A heading in capitals is not an abbreviation, and one that uses an abbreviation is
    # not where a reader expects it defined: the abbreviations are read without them.
    prose = _hide(hidden, (_heading_span(text, heading) for heading in headings)).replace(
        NUL, " "
    )
    regions = _regions(headings, chain, supplementary=supplementary)
    ends = [*(region.start for region in regions[1:]), len(text)]
    references = [
        (region.start, end)
        for region, end in zip(regions, ends, strict=True)
        if region.scope is None
    ]
    return _File(
        order=order,
        path=path,
        text=text,
        regions=regions,
        definitions=_definitions(prose),
        prose=prose,
        printed=_hide(hidden, references),
    )


def _read(project: Project) -> list[_File]:
    """The manuscript as a reader meets it: the paper's files in printed order, then the
    supplement's."""
    root = project.path("manuscript")
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
            files.append(_file(len(files), path, text, chain, supplementary))
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
                _Definition(file.order, offset, region.quiet, long)
            )

    for file in files:
        for word in _WORD.finditer(file.prose):
            token = word.group(0)
            if token.islower() or token.isdigit():
                continue
            region = file.region_at(word.start())
            if region.scope is None:
                continue
            for within, short, is_defined in _forms(token, defined, known):
                offset = word.start() + within
                if (file.order, offset) in defining:
                    continue
                if not is_defined and region.quiet:
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


def _judge(files: list[_File], known: _Known, root: Path) -> Report:
    """The findings, from files already read. Apart from `check_language` so that what it
    costs can be measured on a manuscript of any size without writing one to disk."""
    scopes = _collect(files, known)

    def where(mark: _Mark) -> str:
        file = files[mark.order]
        try:
            shown = file.path.relative_to(root).as_posix()
        except ValueError:
            shown = str(file.path)
        return f"{shown}:{file.line_of(mark.offset)}"

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
                        f"{short} is used here, and defined later at {where(first)}",
                        "define an abbreviation where it first appears: the long form, then "
                        "the short form in brackets",
                    )
                )

            for again in definitions[1:]:
                if _same_meaning(first.long, again.long):
                    message = f"{short} is defined again; it was defined at {where(first)}"
                    hint = "define an abbreviation once and use the short form after that"
                else:
                    message = (
                        f"{short} is defined as {again.long!r} here and as {first.long!r} "
                        f"at {where(first)}"
                    )
                    hint = "one short form, one meaning: a reader keeps the first"
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


def check_language(project: Project) -> Report:
    """The three readings of the manuscript: its abbreviations, the terms it keeps to,
    and its spelling."""
    files = _read(project)
    passages = [Passage(file.path, file.text, file.printed, file.line_of) for file in files]
    paper = project.root / PAPER_FILE
    return (
        _judge(files, _known(project), project.root)
        .merge(judge_vocabulary(passages, project.vocabulary, paper))
        .merge(
            judge_spelling(
                passages, project.english_variant, project.accepted_spellings, paper
            )
        )
    )
