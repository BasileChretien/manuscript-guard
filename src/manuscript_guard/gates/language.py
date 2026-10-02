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
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
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
_BLANK_LINE = re.compile(r"\n[ \t]*\n")
_QUOTES = (
    "*_\"'"
    "\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}"
    "\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
)
# The short form opening a bracket: alone, or before a separator ("ROR; 95% CI ...").
_OPENS_WITH = re.compile(
    rf"[\s{re.escape(_QUOTES)}]*(?P<short>[^\W_]+(?:-[^\W_]+)*)[\s{re.escape(_QUOTES)}]*(?:$|[;,:])"
)
# The word standing against an opening bracket: "ROR (reporting odds ratio)".
_BEFORE_PAREN = re.compile(r"(?P<short>[^\W_]+(?:-[^\W_]+)*)[ \t]?$")
# Bounded, so a line of `![` with no closing bracket is read once and not once per `![`.
_IMAGE = re.compile(r"!\[[^\]]{0,1000}\]\([^)\n]{0,1000}\)")
# I to XXXIX. Longer numerals, and the letters C, D, L and M, are left to be read as
# abbreviations: CI, MI, CD and LV are valid numerals and are far more often not numerals.
_ROMAN = re.compile(r"X{0,3}(?:IX|IV|V?I{0,3})")
_ARTICLES = ("the ", "a ", "an ")

# Sections where capitals are people and institutions, not abbreviations a reader needs
# defined: initials in a contributions statement, a funder's name, a society's.
_QUIET = re.compile(
    r"^\s*(?:"
    r"(?:authors?['\N{RIGHT SINGLE QUOTATION MARK}]?s?\s+)?contributions?"
    r"|contributors?(?:hip)?"
    r"|acknowledge?ments?"
    r"|funding|financial\s+support"
    r"|competing\s+interests?|conflicts?\s+of\s+interest|declarations?\s+of\s+interests?"
    r"|disclosures?"
    r")\b",
    re.IGNORECASE,
)

#: How a hyphenated word is read: `SARS-CoV-2` whole when it is a name, `ROR-based` as its
#: parts when it is not. Past this many parts only the parts are read, so a line of
#: `a-a-a-...` costs what its length is.
_JOINED_PARTS = 6


@dataclass(frozen=True)
class _Mark:
    """One place an abbreviation stands. `order` is the file's place in the reading, so
    marks from several files sort as a reader meets them."""

    order: int
    offset: int
    path: Path
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
        single = form[:-1] if form.endswith("s") else form
        return (
            form in self.exact
            or single in self.exact
            or form.lower() in self.lowered
            or single.lower() in self.lowered
        )


def _known(project: Project) -> _Known:
    exact, lowered = _shipped()
    return _Known(
        exact | set(project.known_abbreviations) | set(project.reporting_guidelines),
        lowered | {str(term).lower() for term in project.extra_terms},
    )


def _capitals_together(form: str) -> bool:
    return any(a.isupper() and b.isupper() for a, b in zip(form, form[1:], strict=False))


def _numeral(form: str) -> bool:
    return bool(form) and _ROMAN.fullmatch(form) is not None


def _reads_as_abbreviation(form: str) -> bool:
    """Would a reader take this word, met with no definition, for an abbreviation?

    Two capitals side by side. Stricter than what a definition may introduce, on purpose:
    `McNemar`, `DeLong`, `NaCl` and `PhD` have two capitals and are not abbreviations
    anybody defines, and a rule that reported them would be switched off for the surnames
    alone. `HbA1c` and `mL` are missed by it and caught when the manuscript defines them.
    """
    return (
        2 <= len(form) <= LONGEST
        and _capitals_together(form)
        and not _numeral(form)
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
    found = before[at + 1 :].strip()
    if len(found) <= len(short) or short.lower() in found.lower().split():
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


def _prose(text: str, headings: list[Heading]) -> str:
    """`text` with everything that is not a sentence blanked, offsets and line breaks kept.

    Blanked: what `mask` takes (listings, comments, bindings, citation keys, link targets),
    the front matter, inline code and equations, image captions, and headings. A heading in
    capitals is not an abbreviation, and one that uses an abbreviation is not where a
    reader expects it defined.
    """
    masked = mask(text)
    code = code_spans(masked)
    spans = [
        (0, front_matter_end(text)),
        *code,
        *equation_spans(masked, code),
        *(found.span() for found in _IMAGE.finditer(text)),
        *(_heading_span(text, heading) for heading in headings),
    ]
    chars = [
        ("\n" if text[index] == "\n" else " ") if char == NUL else char
        for index, char in enumerate(masked)
    ]
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


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
        quiet = any(_QUIET.match(section.title) for section in chain)
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


def _definitions(prose: str) -> list[tuple[int, str, str]]:
    """Every definition in `prose`: where its short form stands, the short form as written,
    and the long form. Both orders: "reporting odds ratio (ROR)" and "ROR (reporting odds
    ratio)"."""
    found: list[tuple[int, str, str]] = []
    for bracket in _PAREN.finditer(prose):
        inner = bracket.group(1)
        if _BLANK_LINE.search(inner):
            continue
        opening = _OPENS_WITH.match(inner)
        if opening and _may_be_defined(opening.group("short")):
            short = opening.group("short")
            before = prose[max(0, bracket.start() - 400) : bracket.start()]
            before = _BLANK_LINE.split(before)[-1]
            words = before.split()[-_window(short) :]
            long = _long_form(short, " ".join(words))
            if long is None and short != _singular(short):
                long = _long_form(_singular(short), " ".join(words))
            if long is not None:
                found.append((bracket.start(1) + opening.start("short"), short, long))
                continue
        standing = _BEFORE_PAREN.search(
            prose, max(0, bracket.start() - LONGEST - 1), bracket.start()
        )
        if standing is None or not _may_be_defined(standing.group("short")):
            continue
        # The search starts a short form's length back, so it can start inside a word.
        head = standing.start("short")
        if head > 0 and (prose[head - 1].isalnum() or prose[head - 1] == "-"):
            continue
        short = standing.group("short")
        words = inner.split()
        if not 2 <= len(words) <= _window(short):
            continue
        joined = " ".join(words)
        long = _long_form(_singular(short), joined)
        if long is None:
            continue
        # The long form has to be the bracket, give or take an article: "ROR (see the
        # ratio results)" matches its letters from "ratio" on and defines nothing.
        rest = joined[: len(joined) - len(long)].lower()
        if rest and rest not in _ARTICLES:
            continue
        found.append((standing.start("short"), short, long))
    return found


def _forms(token: str, defined: set[str], known: _Known) -> list[tuple[int, str, bool]]:
    """The abbreviations in one word: where each starts in it, its short form, and whether
    it is one the manuscript defines. A hyphenated word is read whole where the whole is a
    defined or known name, and by its parts where it is not."""
    parts = token.split("-")
    starts = [0]
    for part in parts[:-1]:
        starts.append(starts[-1] + len(part) + 1)
    found: list[tuple[int, str, bool]] = []
    index = 0
    while index < len(parts):
        furthest = len(parts) if len(parts) <= _JOINED_PARTS else index + 1
        for stop in range(furthest, index, -1):
            form = "-".join(parts[index:stop])
            base = form if form in defined else _singular(form)
            if base in defined:
                found.append((starts[index], base, True))
                index = stop
                break
            if form in known:
                index = stop
                break
        else:
            part = parts[index]
            if _reads_as_abbreviation(_singular(part)):
                found.append((starts[index], _singular(part), False))
            index += 1
    return found


@dataclass
class _File:
    order: int
    path: Path
    text: str
    prose: str
    regions: list[_Region]
    definitions: list[tuple[int, str, str]]
    starts: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.starts = [region.start for region in self.regions]

    def region_at(self, offset: int) -> _Region:
        return self.regions[bisect_right(self.starts, offset) - 1]


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
            text = path.read_text(encoding="utf-8")
            headings = find_headings(text)
            prose = _prose(text, headings)
            files.append(
                _File(
                    order=len(files),
                    path=path,
                    text=text,
                    prose=prose,
                    regions=_regions(headings, chain, supplementary=supplementary),
                    definitions=_definitions(prose),
                )
            )
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
            base = _singular(short)
            defined.add(base)
            defining.add((file.order, offset))
            scopes[region.scope].defined.setdefault(base, []).append(
                _Definition(file.order, offset, file.path, region.quiet, long)
            )

    for file in files:
        for word in _WORD.finditer(file.prose):
            token = word.group(0)
            if token.islower() or token.isdigit():
                continue
            region = file.region_at(word.start())
            if region.scope is None:
                continue
            for within, base, is_defined in _forms(token, defined, known):
                offset = word.start() + within
                if (file.order, offset) in defining:
                    continue
                if not is_defined and region.quiet:
                    continue
                scopes[region.scope].used.setdefault(base, []).append(
                    _Mark(file.order, offset, file.path, region.quiet)
                )
    return scopes


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _context(text: str, offset: int, length: int) -> str:
    left = max(0, offset - 40)
    return re.sub(r"\s+", " ", text[left : offset + length + 40]).strip()


def _same_meaning(one: str, other: str) -> bool:
    def plain(long: str) -> str:
        words = re.sub(r"[-\s]+", " ", long.lower()).strip()
        for article in _ARTICLES:
            if words.startswith(article):
                words = words[len(article) :]
        return words.rstrip("s")

    return plain(one) == plain(other)


def check_language(project: Project) -> Report:
    files = _read(project)
    known = _known(project)
    scopes = _collect(files, known)
    texts = {file.order: file.text for file in files}
    root = project.root

    def where(mark: _Mark) -> str:
        try:
            shown = mark.path.relative_to(root).as_posix()
        except ValueError:
            shown = str(mark.path)
        return f"{shown}:{_line_of(texts[mark.order], mark.offset)}"

    def finding(code: str, mark: _Mark, short: str, message: str, hint: str) -> Finding:
        text = texts[mark.order]
        return Finding(
            gate=GATE,
            code=code,
            severity=WARN,
            message=message,
            path=mark.path,
            line=_line_of(text, mark.offset),
            context=_context(text, mark.offset, len(short)),
            hint=hint,
        )

    report = Report()
    everything: set[str] = set()
    defined_anywhere: set[str] = set()

    for scope in scopes.values():
        everything.update(scope.defined, scope.used)
        defined_anywhere.update(scope.defined)

        for short, definitions in scope.defined.items():
            definitions.sort(key=lambda mark: mark.key)
            first = definitions[0]
            uses = sorted(scope.used.get(short, ()), key=lambda mark: mark.key)

            early = [use for use in uses if use.key < first.key]
            if early:
                report = report.with_findings(
                    finding(
                        "abbreviation-used-before-defined",
                        early[0],
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
                report = report.with_findings(
                    finding("abbreviation-redefined", again, short, message, hint)
                )

            # A funder or a society named in full with its acronym, once, is how those
            # statements are written; nothing later is expected to use it.
            if not uses and not first.quiet:
                report = report.with_findings(
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
            report = report.with_findings(
                finding(
                    "abbreviation-undefined",
                    uses[0],
                    short,
                    message,
                    "define it at first use, or list it under `language: "
                    "known_abbreviations:` in paper.yaml if this journal's readers take it "
                    "for a word or a name",
                )
            )

    return report.with_counts(
        abbreviations_read=len(everything),
        abbreviations_defined=len(defined_anywhere),
    )
