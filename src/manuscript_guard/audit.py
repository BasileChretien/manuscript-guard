"""Auditing a paper that was never written with this toolkit.

`manuscript-guard check` works because the manuscript source contains bindings: a
results-derived number cannot be written as a literal, so nothing passes by coincidence.
An existing paper has no bindings. Every number is a literal, and the only question that can
be asked is the weak one: does this number appear anywhere in the outputs?

That question is much less useful than it sounds, and the honest thing is to say so with a
measurement rather than a disclaimer. In the project that preceded this one, set-membership
checking of exactly this kind was measured and found near-vacuous: with the analysis outputs
as the backing set, **100% of integers up to 100 and 97% of integers up to 1000 already
matched something**, and of fifteen deliberately corrupted headline numbers it detected
none.

So this audit reports two things, and the second is not optional:

* the numbers in the paper that match nothing — the actual candidates for a stale value;
* **what a match is worth in this particular project**, computed from the backing set the
  user supplied, so a clean report cannot be mistaken for a clean paper.

It is a triage tool for existing work. For a paper being written, bind the numbers instead.
"""

from __future__ import annotations

import bisect
import codecs
import csv
import io
import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.safexml import COMPOUND_FILE, compound_file_said, is_compound_file
from manuscript_guard.stats.granularity import described as described_mean
from manuscript_guard.stats.granularity import names, possible, table_means
from manuscript_guard.stats.intervals import (
    ASYMMETRY,
    asymmetry,
    described_against,
    described_asymmetry,
    described_outside,
    outside_interval,
    p_against,
    reported_intervals,
)
from manuscript_guard.stats.margins import over_n, sums_off
from manuscript_guard.stats.margins import said as said_recovered
from manuscript_guard.stats.reported import described, judge, reported_tests
from manuscript_guard.stats.shares import described as described_share
from manuscript_guard.stats.shares import off, table_shares
from manuscript_guard.text.blocks import Unprinted, heading_shaped, scannable, section_breaks
from manuscript_guard.text.comments import unclear_comment_lines
from manuscript_guard.text.docx import NotADocx, is_docx, read_docx_text
from manuscript_guard.text.fences import unclear_fence_lines
from manuscript_guard.text.masking import NUL, front_matter_end, mask
from manuscript_guard.text.reference_lists import ends_a_list_alone, is_bibliography_heading
from manuscript_guard.text.tables import Table, markdown_tables
from manuscript_guard.text.tokens import DIGIT, Atom, find_atoms, trim

PAPER_SUFFIXES = {".docx", ".md", ".txt", ".markdown", ".tex", ".pdf"}
#: What a folder given as a paper is searched for: a PDF in a folder is a figure, or a
#: copy of the paper beside its source, as often as it is the paper, and is read only
#: where it is named (`auditing.pdf`).
FOLDER_SUFFIXES = PAPER_SUFFIXES - {".pdf"}
BACKING_SUFFIXES = {".json", ".csv", ".tsv", ".txt", ".yaml", ".yml", ".md"}
FIGURE_SUFFIXES = {".svg", ".pdf"}

# A leading minus is part of the number. U+2212 is always one: it can only be a minus. A
# hyphen or an en dash is one only where it can be a sign: at the start, or after a space,
# an opening bracket, a table pipe, `=`, `:`, `,`, `$`, a comparison, a dash, or another
# hyphen or a slash, as in "-0.72--0.30", which R's `paste0(lo, "-", hi)` writes. Anywhere
# else it joins two things: "0.72-0.82", "0.72–0.82" and "50%-60%" are ranges, "2019-03-04"
# a date, "x-5" a name. Listed rather than excluded, because the first version excluded
# digits, letters and points, and read "50%-60%" as 50 and -60; the second left out the
# hyphen and the slash, so "−0.72-−0.30" in a paper matched an interval running to +0.30;
# and the third read an en dash only as a range, so "–0.51" copied from a typeset PDF, or
# LaTeX's `$-0.51$`, went into the outputs as 0.51.
# With no sign at all, -0.51 in the outputs went in as 0.51, so a paper quoting it correctly
# never matched and a paper printing 0.51 for it did.
_SIGN_MAY_FOLLOW = r"\s(\[{|*=:;,<>~/$\u00b1\u2264\u2265\u2013\u2014\"'\u201c\u2018\-"
_NUMBER = re.compile(
    rf"(?:(?<![^{_SIGN_MAY_FOLLOW}])[-\u2013]|\u2212)?"
    r"\d[\d,\u202f\xa0]*(?:\.\d+)?(?:[eE][+-]?\d+)?"
)

# `--` between digits is a separator and a minus in every format, Markdown included,
# although pandoc renders it as an en dash in Markdown prose. Reading it as pandoc does meant
# knowing where pandoc does and does not: fenced, indented and inline code, HTML comments.
# Each gap in that knowledge flipped a sign in code, where R's output puts "-0.72--0.30"
# meaning -0.30, or swallowed prose. This way every misreading is a false alarm: a Markdown
# range written "2010--2019" reports -2019 as not found.


# Digests, ids and hashes, stripped from backing text before numbers are extracted. Two
# reasons: a hex run like "4e308" parses as an overflowing float, and, worse, the digit
# fragments inside hashes would join the backing set and make every match likelier, quietly
# inflating the very statistic this module exists to report honestly.
_OPAQUE = re.compile(
    r"\b[0-9a-fA-F]{16,}\b|\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"
)
_MAX_DIGITS = 24


@dataclass
class Candidate:
    text: str
    normalised: str
    source: Path
    line: int
    context: str


@dataclass
class Disagreement:
    """A test statistic whose P, as the paper prints it, does not follow from it, or an
    estimate whose interval, or the P beside it, does not fit it."""

    source: Path
    line: int
    message: str
    context: str


@dataclass
class AuditReport:
    papers: tuple[Path, ...] = ()
    backing_files: tuple[Path, ...] = ()
    backing_values: set[str] = field(default_factory=set)
    matched: list[Candidate] = field(default_factory=list)
    unmatched: list[Candidate] = field(default_factory=list)
    classified: int = 0
    unreadable: list[str] = field(default_factory=list)
    #: Outputs named in --against that were not read, or not read as what they claimed to be.
    skipped: list[str] = field(default_factory=list)
    #: Each Word 97-2003 document (.doc) found in a folder given as a paper, which is not
    #: read, with what to do about it. A note: the papers beside it were audited, so
    #: --strict does not count it. A .doc named on its own is in `unreadable`.
    passed_over: list[str] = field(default_factory=list)
    #: Stretches of a paper that were read and deliberately not audited: the reference list.
    not_audited: list[str] = field(default_factory=list)
    #: Numbers found nowhere, on lines taken for reference entries by their shape. Listed
    #: apart from `unmatched`, where volumes and pages would bury the findings, but listed:
    #: four review rounds each found a caption some shape accepted.
    reference_like: list[Candidate] = field(default_factory=list)
    #: Each test whose P does not follow from its statistic. No backing set is needed for
    #: these, and they are listed apart: --strict does not count them.
    disagreements: list[Disagreement] = field(default_factory=list)
    #: The rows --whole-numbers named, and how many means were read in them.
    whole_numbers: tuple[str, ...] = ()
    means_read: int = 0
    #: Each mean of whole numbers whose n is too large for the places it is printed to.
    means_not_assessable: list[Disagreement] = field(default_factory=list)
    #: Each label --whole-numbers gave under which no mean was read: no table row's label
    #: holds it, or no cell of those rows is a mean under a column that names its n.
    whole_numbers_unfound: list[str] = field(default_factory=list)
    #: Whether outputs were given. Without them no number is compared, and `uncompared`
    #: counts the numbers that would have been.
    compared: bool = True
    uncompared: int = 0
    #: Each paper's reference list, counted (`auditing.references.Census`).
    references: list = field(default_factory=list)
    #: What was asked of the registries (`auditing.references.Looked`), with --lookup;
    #: None where nothing was to be.
    lookups: list | None = None
    #: G6 and G14 on each paper (`auditing.gates.GateRun`).
    gates: list = field(default_factory=list)
    #: Each LaTeX entry's tree as it was read (`auditing.latex.Tree`).
    trees: list = field(default_factory=list)
    #: Each total of a table whose printed counts do not add up to it (`stats.margins`),
    #: and each characteristic whose categories add up to more than their column's n. Exact
    #: arithmetic: --strict counts them.
    sums_off: list[Disagreement] = field(default_factory=list)
    over_n: list[Disagreement] = field(default_factory=list)
    #: Each count held back that a total beside it gives away, by a printed total
    #: (`recovered`, which --strict counts) or only by its column's n (`recovered_by_n`,
    #: which it does not: the n is their total only where none of the column lacks them).
    recovered: list[Disagreement] = field(default_factory=list)
    recovered_by_n: list[Disagreement] = field(default_factory=list)
    #: The data custodian's minimum, `--minimum-cell-count`; None where none was given, and
    #: a count held back is then taken to hide every count from one up to its bound.
    minimum: int | None = None
    #: How many lists were read as flows (`stats.flows`); each flow whose arithmetic does
    #: not hold, which --strict counts; and what was allowed for or passed over in one, or
    #: found and not read, which it does not.
    flows_read: int = 0
    #: Of them, those under a heading, or after a caption or a paragraph, that names a flow.
    flows_named: int = 0
    flows_broken: list[Disagreement] = field(default_factory=list)
    flow_notes: list[Disagreement] = field(default_factory=list)
    #: The Abstract against what the paper reports (`auditing.abstract.AbstractRead`).
    abstract: object = None
    #: G4 held to the journal's profile, `--journal` (`auditing.journal.JournalRun`); None
    #: where no profile was given.
    journal: object = None
    #: What each .docx holds besides its text (`auditing.document.DocumentFacts`), where a
    #: reader option was given.
    documents: list = field(default_factory=list)
    #: The causal words of `--design` (`auditing.causal.CausalRead`), the cited sentences of
    #: `--cited` (`auditing.cited.CitedRead`) and the self-citation count
    #: (`auditing.selfcite.SelfCitation`); None where not asked for.
    causal: object = None
    cited: object = None
    self_citation: object = None
    #: Each PDF read, by its path (`auditing.pdf.PdfText`): what its places are said by.
    pdfs: dict = field(default_factory=dict)

    @property
    def examined(self) -> int:
        return (
            len(self.matched) + len(self.unmatched) + len(self.reference_like)
            + self.classified + self.uncompared
        )


def normalise_number(text: str) -> str:
    """A comparable form: no thousands separators, no trailing zeros, no sign noise.

    Sign noise is how a sign is spelled — U+2212, a hyphen or a leading en dash, `+0.51`,
    `-0.00` — and never the sign itself. -0.51 and 0.51 are different numbers, and a paper
    printing one for the other is exactly what an audit is for.
    """
    cleaned = (
        text.replace(",", "").replace(" ", "").replace("\xa0", "").replace("−", "-")
    ).rstrip("%")
    cleaned = re.sub(r"^\u2013(?=\d)", "-", cleaned)
    if len(cleaned) > _MAX_DIGITS:
        return cleaned
    try:
        value = float(cleaned)
    except (ValueError, OverflowError):
        return cleaned
    if not math.isfinite(value):
        return cleaned
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(round(value, 10)).rstrip("0").rstrip(".")


#: An atom made of numbers and the characters that join them: "0.72–0.82", "2000-3999",
#: "77/412", "1.2 ± 0.3". Deliberately not general — an atom carrying any letter is left
#: alone, because splitting one would let an email address or a model name match on whatever
#: digit it happens to contain, and a false match is worse than an unexplained number.
#:
#: A short statistical label closed up against its own number — "n=8,393", "p=0.03", "df=2" —
#: is stripped first. Written with spaces it is already two tokens and reads correctly;
#: written closed up it is one atom that no longer looks like a number at all, and on a real
#: paper's supplements thirty numbers were reported unexplained for that reason alone.
#: Bounded to three letters, so it strips a label and never a word.
#:
#: Either bound may carry a sign, "−0.72–−0.30" or "-0.72–0.30", and `_NUMBER` reads a minus
#: as a sign only where it cannot be the separator.
#:
#: Each segment's first digit has one place it can match: no digits before it. Written as
#: `[\d…]*\d[\d…]*`, the required digit could sit anywhere in a run, and the work multiplied
#: per segment: 100 s for a 72-character hyphenated token.
_LABELLED = re.compile(r"^[A-Za-z]{1,3}\s*=\s*")
_COMPOUND = re.compile(
    r"^[-−–]?[.,%\s\xa0]*\d[\d.,%\s\xa0]*"
    r"(?:[-–—/\xb1:x\xd7][-−]?[.,%\s\xa0]*\d[\d.,%\s\xa0]*)+$"
)


def parts_of(text: str) -> list[str]:
    """The numbers an atom carries, normalised. One for a plain number, two for an interval.

    A confidence interval written as a range is one atom — "0.72–0.82" — and matching it as
    a single string matched nothing, so an interval whose two bounds were both sitting in the
    analysis outputs was reported as not found. On a real paper that was 29 of 232, and they
    are the paper's actual results rather than incidental numbers: the ones an audit exists
    to check are the ones it was worst at.
    """
    stripped = _LABELLED.sub("", text.strip().strip("()[]"), count=1)
    if not _COMPOUND.match(stripped):
        return [normalise_number(stripped)]
    found = [normalise_number(part.group(0)) for part in _NUMBER.finditer(stripped)]
    return found or [normalise_number(stripped)]


def _numbers_in(text: str) -> set[str]:
    return {normalise_number(m.group(0)) for m in _NUMBER.finditer(_OPAQUE.sub(" ", text))}


def _json_values(node: object) -> list[str]:
    """Every key, string and number in a parsed JSON document, as text.

    Not a re-serialisation. `json.dumps` escaped "β" as "\\u03b2", which put 3 and 2 in the
    backing set, and wrote a tab inside a string as the two characters "\\t", so the "t"
    before "-0.51" stopped the minus being read as a sign and 0.51 in a paper matched.
    """
    if isinstance(node, dict):
        return [part for key, value in node.items() for part in [str(key), *_json_values(value)]]
    if isinstance(node, list):
        return [part for item in node for part in _json_values(item)]
    if isinstance(node, bool) or node is None:
        return []
    return [str(node)]


class UnreadableText(ValueError):
    """A file that holds text in no encoding the audit can name."""


# Longest first: the UTF-32 little-endian mark begins with the UTF-16 one.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def read_text(path: Path) -> str:
    """A paper's or an output's text, in the encoding its byte-order mark names, else UTF-8.

    Windows writes these marks: PowerShell 5.1's `Out-File -Encoding utf8` a UTF-8 one, and
    its `>` and default `Out-File` UTF-16. Read as UTF-8, a UTF-8 mark stopped a .json
    parsing, and UTF-16 put a NUL after every character, so "8393,3.84" went into the
    backing set as 8, 3, 9 and 4 — and a paper printing 3 for anything matched. NUL bytes
    with no mark could be UTF-16 or binary, so they are refused rather than guessed at. A
    Word 97-2003 document is one such binary, and is named as one: the advice to save it as
    UTF-8 was wrong for it.
    """
    data = path.read_bytes()
    if is_compound_file(data):
        raise UnreadableText(compound_file_said(path.name))
    encoding = next((name for bom, name in _BOMS if data.startswith(bom)), None)
    if encoding is None and b"\x00" in data:
        raise UnreadableText(
            f"{path.name}: NUL bytes and no byte-order mark, so not read; if it is UTF-16, "
            f"save it as UTF-8"
        )
    # Decoding bytes skips the newline translation `read_text` did, and a setext underline
    # followed by "\r" is not an underline: a CRLF paper lost the heading that ends its
    # reference list.
    text = data.decode(encoding or "utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def load_backing(paths: list[Path]) -> tuple[set[str], list[Path], list[str]]:
    """Every number appearing anywhere in the supplied outputs, and what could not be used.

    Nothing is passed over in silence. A path that does not exist, a spreadsheet or an .rds
    among the outputs, a .json that is not one JSON document: each used to vanish, and every
    number it held was then reported as missing from the *paper*, with nothing to say the
    audit had never looked. A typo in --against produced "0 output file(s)", a paper full of
    findings, and exit 0.
    """
    values: set[str] = set()
    used: list[Path] = []
    skipped: list[str] = []
    readable = ", ".join(sorted(BACKING_SUFFIXES))

    def take(path: Path) -> None:
        suffix = path.suffix.lower()
        try:
            raw = read_text(path)
            if suffix == ".json":
                try:
                    text = "\n".join(_json_values(json.loads(raw)))
                except ValueError:
                    # JSON Lines is the usual reason, and its numbers are all there as text.
                    text = raw
                    skipped.append(f"{path.name}: not valid JSON, so it was read as plain text")
            elif suffix in {".csv", ".tsv"}:
                delimiter = "\t" if suffix == ".tsv" else ","
                rows = csv.reader(io.StringIO(raw, newline=""), delimiter=delimiter)
                text = " ".join(" ".join(row) for row in rows)
            else:
                text = raw
        except UnreadableText as exc:
            skipped.append(str(exc))
            return
        except (OSError, csv.Error) as exc:
            skipped.append(f"{path.name}: could not be read ({exc})")
            return
        values.update(_numbers_in(text))
        used.append(path)

    for given in paths:
        if given.is_dir():
            unread: dict[str, int] = {}
            for path in sorted(given.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() in BACKING_SUFFIXES:
                    take(path)
                else:
                    kind = path.suffix.lower() or "no extension"
                    unread[kind] = unread.get(kind, 0) + 1
            if unread:
                listed = ", ".join(f"{kind} ({n})" for kind, n in sorted(unread.items()))
                skipped.append(
                    f"{given.name}/: {sum(unread.values())} file(s) in formats the audit does "
                    f"not read: {listed}"
                )
        elif given.is_file():
            if given.suffix.lower() in BACKING_SUFFIXES:
                take(given)
            else:
                kind = given.suffix.lower() or "a file with no extension"
                skipped.append(f"{given.name}: {kind} is not a format the audit reads ({readable})")
        else:
            skipped.append(f"{given}: does not exist")

    return values, used, skipped


# A reference-list entry, recognised by its shape rather than by a heading. citeproc appends
# the bibliography with no heading of its own, so there is often nothing to cut at, and every
# volume number and page range in it would otherwise be reported as an unexplained figure.
#
# It was "a capitalised word, a comma, a capitalised word, a year within 200 characters", and
# in a .docx a line is a paragraph: "Overall, Japanese patients accounted for 412 of 8,393
# cases between 2010 and 2019." was a reference, and every number in it was counted among
# the references and compared with nothing. So each part now has to look like a reference
# and not merely like a sentence. The name after the comma is initials or given names that
# the author list goes on from. Between it and the year there is nothing but more names:
# capitalised words, initials, "and", "&", "et al.", a particle such as "van". The year is
# the one an entry carries, "(2019)." or "(2019, March 5)." closing the author list, or
# ". 2021." standing between author and title. "Notably, Japan and Korea contributed 413 …,
# in line with Smith (2019)." has the signature, and a lower-case word before it.
#
# Each token of the author list is unambiguous, one separator character or one whole word,
# so a line that fails costs a single pass rather than a backtracking search.
# Capitals from the Latin script, not only ASCII: "Østergaard", "Éric". Latin Extended-A
# mixes both cases, so a word starting with one of its small letters also counts, which at
# worst accepts a name.
_CAPITAL = "A-Z\u00c0-\u00d6\u00d8-\u00de\u0100-\u017e"
_AUTHOR_LIST = (
    r"(?:[\s,.&]"
    rf"|[{_CAPITAL}][\w'’-]*(?![\w'’-])"
    r"|(?:and|et\s+al|van|von|der|den|de|du|da|das|di|do|dos|del|la|le)(?![\w'’-])"
    rf"|d['’](?=[{_CAPITAL}]))*?"
)
_REFERENCE_ENTRY = re.compile(
    rf"^\s*[{_CAPITAL}][\w'’-]+,\s+"                                 # "Fictional,"
    rf"(?:[{_CAPITAL}]\.(?:\s?-?[{_CAPITAL}]\.)*"
    r"(?=\s*[,&(]|\s+and\s|\s+et\s+al\b|\s+(?:19|20)\d{2})"
    rf"|[{_CAPITAL}][\w'’-]+(?:\s+[{_CAPITAL}][\w'’-]+)*(?=\s*[,.&]|\s+and\s))"
    + _AUTHOR_LIST
    # "(2019)." closing the author list, or "(2019)" before a title in capitals or quoted,
    # as Harvard writes it with no full stop: "(2019) found ..." is a sentence.
    + r"(?:\((?:19|20)\d{2}[a-z]?(?:,[^)]{0,20})?\)"
    + rf"(?:\.|(?=\s+[{_CAPITAL}'‘\"“]))"
    + r"|(?:\.|(?<=\.))\s+(?:19|20)\d{2}[a-z]?\.)",
)

# The numbered styles — Vancouver, AMA, ICMJE — put the surname before the initials with no
# comma, "Smith J, Jones K.", which the author-year shape never matched. What a caption or a
# sentence does not share is the journal signature "2019;393:100", year, volume, page:
# "Figure A. Reports by year, 2015 to 2019" starts the same way and has none. "Stage III,
# diagnosed in 2010-2020; 45 excluded" has a year and a semicolon, which is why the volume
# must run on to its page, and the initials on to another author or the title. "Figure A.
# Case-control design, 2010 to 2019; 1:4 matching" has all of that, which is why the year
# must follow the full stop that ends a journal's name, "Lancet. 2019;393", and why the
# entry must end at its pages. "Figure A. Enrolment to Dec. 2019; 2:1 randomisation. Events
# 413 …" has a full stop before its year too, and then goes on, as a caption does and an
# entry does not. After the pages only a DOI, a PMID, an Epub or availability note may
# follow.
#
# The BMJ's own style puts no full stop before the year, "BMJ 2021;372:n71", and neither does
# a journal's name abbreviated without stops, "N Engl J Med 2019;380:100-10". There the
# year follows a capitalised word that is no month's, "Dec 2019;2:1" being a caption's, and
# the entry still ends at its pages. An article online first has no volume: the year, or
# "Published online" and a date, after the journal's full stop, and then a DOI, a PMID or an
# Epub note, which a caption does not end with. A book ends with "Place: Publisher; 2019.",
# and perhaps its pages, "p. 100-10.".
#
# Each whitespace run has one quantifier that can take it: two side by side made every
# unclassified number on an indented line quadratic.
_NOT_A_MONTH_BEFORE = (
    r"(?<!Jan)(?<!Feb)(?<!Mar)(?<!Apr)(?<!Jun)(?<!Jul)(?<!Aug)(?<!Sep)(?<!Sept)"
    r"(?<!Oct)(?<!Nov)(?<!Dec)(?<!vs)"
)
_YEAR_AND_DATE = r"(?:19|20)\d{2}[a-z]?(?:\s+[A-Z][a-z]{2}(?:\s+\d{1,2})?)?"  # "2019 Mar 5"
_VOLUME_AND_PAGES = (
    r";\s?\d+(?:\([^)]{1,20}\))?:\s?"                     # ";393:", ";42(3):", ";393(Suppl 1):"
    r"[A-Za-z]{0,2}\d+(?:[-–][A-Za-z]{0,2}\d+)?"          # "100-10", "e0213", "n71", "S1-S10"
)
#: What may follow an entry's last part: a DOI, a PMID, an Epub or availability note.
_NOTE_KEYWORD = r"(?i:doi\b|https?://|pubmed\b|pmid\b|pmcid\b|epub\b|available\b|published\b)"
_TRAILING_NOTE = rf"(?:\s+(?:{_NOTE_KEYWORD}|\[)[^\n]*)?\s*$"
_VANCOUVER_ENTRY = re.compile(
    r"^\s*(?:(?:\[\d{1,4}\]|\d{1,4}[.)])\s*)?"            # "12." / "[12]" / "12)"
    rf"(?:[a-z]{{1,3}}\s+){{0,2}}[{_CAPITAL}][\w'’-]+\s+[{_CAPITAL}](?:-?[{_CAPITAL}]){{0,3}}"
    rf"[,.](?=\s+(?:[{_CAPITAL}]|et\s+al\b))"             # ... then an author or the title
    r".{0,400}?(?:"
    # The full stop that ends a journal's name, and not one ending "Dec." or "vs.".
    rf"{_NOT_A_MONTH_BEFORE}\.\s+{_YEAR_AND_DATE}{_VOLUME_AND_PAGES}\.?{_TRAILING_NOTE}"
    # Or a capitalised word that is no month's: "BMJ 2021;372:n71".
    r"|\s(?!(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b)[A-Z][A-Za-z]{0,30}\s+"
    rf"{_YEAR_AND_DATE}{_VOLUME_AND_PAGES}\.?{_TRAILING_NOTE}"
    # Online first: "Drug Saf. 2019. doi:...", "Drug Saf. Published online March 5, 2019."
    rf"|{_NOT_A_MONTH_BEFORE}\.\s+(?:{_YEAR_AND_DATE}|Published\s+online\s+[A-Z][a-z]+\.?"
    r"\s+\d{1,2},?\s+(?:19|20)\d{2})\.\s+(?i:doi\b|https?://|pmid\b|epub\b)[^\n]*$"
    # A book: "London: Example Press; 2019." and perhaps "p. 100-10.".
    rf"|:\s?[{_CAPITAL}][^;:\n]{{0,100}};\s?(?:19|20)\d{{2}}[a-z]?\."
    rf"(?:\s+pp?\.\s?\d+(?:[-–]\d+)?\.)?{_TRAILING_NOTE})"
)

# A web page, in the numbered styles and in Harvard's: an entry whose author may be an
# organisation, "Example Agency.", so it is known by what only a web page's entry has, and
# ends with: "[Internet]" or "[cited 2021 Mar 5]", "Accessed March 5, 2021." and the address,
# or "Available at:" and the address, perhaps with the date it was read. The line has a year.
_WEB_ENTRY = re.compile(
    rf"^\s*(?:(?:\[\d{{1,4}}\]|\d{{1,4}}[.)])\s*)?[{_CAPITAL}]"
    r"(?=[^\n]{0,800}?\b(?:19|20)\d{2}\b)"
    r"[^\n]{0,600}?(?:"
    r"\[Internet\]|\[(?:cited|accessed)\s[^\]\n]{0,40}\]"
    r"|\bAccessed\s[A-Z][a-z]+\.?\s\d{1,2},\s(?:19|20)\d{2}\."
    r"(?:\s+<?(?:https?://|www\.)\S+)?\s*$"
    r"|\bAvailable\s(?:from|at):?\s*<?(?:https?://|www\.)\S+?>?\.?"
    r"(?:\s+\((?:Accessed|cited):?\s[^)\n]{0,40}\)\.?)?\s*$)"
)

# A Markdown footnote definition. It can sit after the bibliography heading, and it is the
# author's text, not a reference.
_FOOTNOTE = re.compile(r"^\s{0,3}\[\^[^\]]+\]:")


def looks_like_reference(line: str) -> bool:
    """Whether a line has the shape of a reference entry. A shape can be wrong, and every
    number on a line it accepts goes uncompared, so the audit names the lines it accepted."""
    return bool(
        _REFERENCE_ENTRY.match(line) or _VANCOUVER_ENTRY.match(line) or _WEB_ENTRY.match(line)
    )


def _markdown_heading_lines(text: str) -> frozenset[int]:
    # The headings pandoc prints: a line it prints as text starts no reference list. The ones
    # G2 calls printed, not every heading the walk places: under a stray `</script>` the walk
    # can place `####### References`, which pandoc prints as text, and the cut after it hid
    # every number below from the comparison.
    return frozenset(
        text.count("\n", 0, found.start)
        for found in section_breaks(text)
        if type(found.title) is not Unprinted
    )


def bibliography_spans(
    text: str,
    headings: frozenset[int] | None = None,
    cells: frozenset[int] = frozenset(),
) -> list[tuple[int, int]]:
    """Where the reference lists are, as 0-based lines `[start, end)`.

    Each runs from a bibliography heading to the next heading of another kind, or to the end
    if there is none. The first version ran to the end regardless, so an appendix after the
    references was never audited, and it used only the first heading, so an appendix's own
    reference list was read as prose.

    `headings` says which lines are headings when the text cannot: a .docx read as plain text
    knows them only from paragraph styles. Omitted, they are read as Markdown, and a line in
    a fenced block, an HTML comment or the front matter does not start a list, whatever it
    says: it is code, a note or metadata. `cells` are lines inside a table, where
    "References" is a column header and not a heading. Given `headings`, the marks are not
    Markdown's, so a heading keeps any `#` it prints.
    """
    lines = text.split("\n")
    markdown = headings is None
    if headings is None:
        headings = _markdown_heading_lines(text)
        # Blanked in place, so the lines still count the same.
        lines = scannable(text).split("\n")
        # A heading continuing a paragraph is printed as text, so it starts no list. It
        # still ends one: `# Appendix`, or `Appendix` underlined, directly under the last
        # entry has no heading in the printed paper, and running the cut on past it would
        # hide the appendix as more references. An early end costs a false alarm; a late
        # one hides numbers.
        ends = headings | heading_shaped(lines)
    else:
        ends = headings
    # A final newline ends the last line; it does not start another.
    last = len(lines) - text.endswith("\n")
    spans: list[tuple[int, int]] = []
    for start, line in enumerate(lines):
        if start in cells or not is_bibliography_heading(
            line, marked=start in headings, markdown=markdown
        ):
            continue
        if spans and start < spans[-1][1]:
            continue
        after = (
            i
            for i in sorted(ends)
            if i > start
            and not is_bibliography_heading(lines[i], marked=True, markdown=markdown)
        )
        end = next(after, last)
        if not markdown and start not in headings:
            end = _end_under_no_heading(lines, start, end)
        spans.append((start, end))
    return spans


def _end_under_no_heading(lines: list[str], start: int, end: int) -> int:
    """Where a .docx's list under a paragraph that is no heading ends, before `end`: at a
    paragraph that ends a list under no heading in Markdown for `check`
    (`ends_a_list_alone`), a caption, a back-matter title or a table, whose rows the reader
    opens with a line of their own, ` | `, which is a pipe table's shape. With no heading
    styles in the document the cut ran to the end of the body, and what came after the list
    was never audited. A list under a styled heading runs on to the next, as one under
    `# References` does in Markdown."""
    return next((i for i in range(start + 1, end) if ends_a_list_alone(lines[i])), end)


def strip_bibliography(
    text: str,
    headings: frozenset[int] | None = None,
    cells: frozenset[int] = frozenset(),
) -> str:
    """`text` with its reference lists blanked, line for line, so line numbers still hold."""
    return _blank(text, bibliography_spans(text, headings, cells))


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    """`text` with the lines in `spans` emptied, except the footnote definitions among them."""
    lines = text.split("\n")
    for start, end in spans:
        in_note = False
        for index in range(start, end):
            line = lines[index]
            if _FOOTNOTE.match(line):
                in_note = True
                continue
            if in_note and (not line.strip() or line.startswith(("    ", "\t"))):
                continue
            in_note = False
            lines[index] = ""
    return "\n".join(lines)


def read_paper(
    path: Path, document=None,
) -> tuple[str, list[tuple[int, int]], list[Table], str, dict[int, tuple[str, bool, int]]]:
    """The paper's text with its reference lists blanked, which lines those were, its
    tables outside them as rows of cells (`text.tables`), the text before the cut, whose
    lists G7's census reads (`auditing.references`), and the lines Word numbers in a .docx
    (`text.docx.DocxText.numbering`).

    A .docx's footnotes and endnotes follow its body, and are read after the cut rather than
    through it: they were being dropped along with the bibliography. `document` is a .docx
    already read (`read_docx_text`), which is not read again.
    """
    if not is_docx(path):
        text = read_text(path)
        spans = bibliography_spans(text)
        blanked = _blank(text, spans)
        return blanked, spans, markdown_tables(blanked), text, {}
    document = document or read_docx_text(path)
    spans = bibliography_spans(document.body, document.headings, document.cells)
    body = _blank(document.body, spans)
    tables = [
        table for table in document.tables
        if not any(start < cell.line <= end for row in table for cell in row
                   for start, end in spans)
    ]  # fmt: skip
    numbering = {line: (count, from_one, place)
                 for line, count, from_one, place in document.numbering}  # fmt: skip
    return ((f"{body}\n{document.notes}" if document.notes else body), spans, tables,
            document.body, numbering)  # fmt: skip


def census_of_markdown(path: Path, text: str):
    """G7's census of a Markdown or text paper, read as `audit` reads it: its lists cut
    where `bibliography_spans` finds them, its citations in what is left, masked, with each
    interval after its value set aside (`auditing.references`)."""
    from manuscript_guard.auditing.references import census_of_text

    spans = bibliography_spans(text)
    blanked = _blank(text, spans)
    hidden = _masked(blanked, printed_as_typed=False)
    return census_of_text(path, text, spans, hidden, _intervals(blanked), docx=False)


@dataclass(frozen=True)
class _Source:
    """One text the audit reads numbers in. `text` is what an atom is reported from;
    `hidden` what is read, masked; `scanned` what the classifier's rules read; `plain` what
    an interval after a value is looked for in. A LaTeX file's are its views at the same
    offsets (`auditing.latex`), and its headings and items are commands (`blocks` False)."""

    path: Path
    text: str
    hidden: str
    scanned: str
    plain: str
    tables: tuple[Table, ...]
    by_shape: bool
    lines_are_blocks: bool
    blocks: bool = True
    layout: tuple[tuple[int, int], ...] = ()
    #: Where each line stands for the Abstract against Results, None in a file with no
    #: headings, and whether the file's document has an Abstract and a Results heading
    #: (`auditing.abstract`); the lines in a table; the lists a flow is read from
    #: (`stats.flows`); and how many counts its text boxes give.
    place: Callable[[int], object] | None = None
    abstract: bool = False
    results: bool = False
    table_lines: frozenset[int] = frozenset()
    lists: tuple = ()
    boxed: int = 0
    #: Where each line stands for the reader options that read sentences, None in a file
    #: with no headings (`auditing.sentences.placing`), and a LaTeX file's `Source`.
    part: Callable[[int], object] | None = None
    latex: object = None
    #: The lines of a Markdown or a Word paper's headings, which are no sentences.
    heading_lines: frozenset[int] = frozenset()
    #: Whether its lines are lines of paragraphs, wrapped as a PDF sets them, though not
    #: Markdown: a sentence goes on from one to the next (`auditing.pdf`).
    wrapped: bool = False

    def scan(self, classifier: Classifier):
        return classifier.scan(self.scanned, lines_are_blocks=self.lines_are_blocks,
                               blocks=self.blocks, layout=self.layout)  # fmt: skip


def _read_sources(
    report: AuditReport, papers: list[Path], found_tex: list[Path]
) -> list[_Source]:
    """Every paper given, read, and G7's census of each taken (`auditing.references`)."""
    from manuscript_guard.auditing.latex import read_latex
    from manuscript_guard.auditing.references import census_of_latex, census_of_text

    sources: list[_Source] = []
    entries = [path for path in papers if path.suffix.lower() == ".tex"]
    for path in papers:
        if path in entries:
            continue
        if path.suffix.lower() == ".pdf":
            _read_pdf(report, sources, path)
            continue
        try:
            document = read_docx_text(path) if is_docx(path) else None
            text, spans, tables, original, numbering = read_paper(path, document)
        except (NotADocx, OSError, UnreadableText) as exc:
            report.unreadable.append(str(exc))
            continue
        docx = is_docx(path)
        hidden = _masked(text, printed_as_typed=docx)
        source = _Source(path, text, hidden, text, text, tuple(tables), not spans, docx)
        sources.append(replace(source, **_structure(text, hidden, tables, document)))
        report.not_audited += [
            f"{path.name}: lines {start + 1}-{end}, read as the reference list"
            for start, end in spans
        ]
        if not docx:
            report.unreadable += unread_shapes(path, text)
        report.references.append(
            census_of_text(path, original, spans, hidden, _intervals(text), docx=docx,
                           numbering=numbering)  # fmt: skip
        )
    if entries or found_tex:
        latex = read_latex(entries, found_tex)
        report.unreadable += latex.unreadable
        report.passed_over += latex.passed_over
        report.not_audited += latex.not_audited
        structures = _latex_structure(latex)
        for file in latex.files:
            plain = file.hidden.replace(NUL, " ")
            sources.append(_Source(file.path, file.source.text, file.hidden, file.hidden,
                                   plain, file.tables, False, False, blocks=False,
                                   layout=file.layout, latex=file.source,
                                   **structures.get(file.path, {})))  # fmt: skip
        report.trees += latex.trees
        report.references += [census_of_latex(tree.entry, list(tree.files))
                              for tree in latex.trees]  # fmt: skip
    return sources


def _read_pdf(report: AuditReport, sources: list[_Source], path: Path) -> None:
    """A PDF read as `auditing.pdf` reads one: its text a line of the PDF to a line, each line
    a block to the classifier, as a .docx's paragraph is, and a line of a paragraph to the
    sentences; its reference list found by its heading, as in a .docx, and ended where a
    list under no heading ends (`_end_under_no_heading`), at a caption or back matter; and
    what it is not read for said."""
    from manuscript_guard.auditing.pdf import UnreadablePdf, read_pdf
    from manuscript_guard.auditing.references import census_of_text

    try:
        pdf = read_pdf(path)
    except UnreadablePdf as exc:
        report.unreadable.append(str(exc))
        return
    report.pdfs[path] = pdf
    text = pdf.text
    spans = pdf_spans(pdf)
    blanked = _blank(text, spans)
    hidden = _masked(blanked, printed_as_typed=True)
    source = _Source(path, blanked, hidden, blanked, blanked, (), not spans, True, wrapped=True)
    sources.append(replace(source, **_pdf_structure(report, pdf)))
    report.not_audited += [pdf.described(), *(
        f"{path.name}: {pdf.stretch(start + 1, end)}, read as the reference list"
        for start, end in spans), *(f"{path.name}: {what}" for what in PDF_NOT_READ)]
    report.references.append(census_of_text(path, text, spans, hidden, _intervals(blanked),
                                            docx=False, printed=True))  # fmt: skip


def pdf_spans(pdf) -> list[tuple[int, int]]:
    """Where a PDF's reference lists are in its text (`auditing.pdf.PdfText`), as 0-based
    lines `[start, end)`: each from its heading, as in a .docx, to the next heading or to
    where a list under no heading ends (`_end_under_no_heading`), at a caption or a title of
    back matter, since a PDF marks no heading but the lines `auditing.pdf` reads as one."""
    lines = pdf.text.split("\n")
    return [(start, _end_under_no_heading(lines, start, end))
            for start, end in bibliography_spans(pdf.text, pdf.heading_lines)]  # fmt: skip


#: What a PDF's text is not read for, said of each PDF audited.
PDF_NOT_READ = (
    "its tables are lines of text, not rows of cells, so no table's totals, shares, means or "
    "counts held back are checked in it; the numbers in them are read as the text's",
    "its lists are lines of text, so no flow is read in it",
    "a line of it is read as a heading only where it holds a section's name and nothing else "
    "(Abstract, Methods, Results, Discussion, References and the like), so a section under "
    "any other title is read as the one before it",
)


def _pdf_structure(report: AuditReport, pdf) -> dict:
    """Where each line of a PDF stands, from the lines that hold a section's name alone
    (`auditing.pdf.heading_title`); placed nowhere where one name stands on two of them,
    which is said."""
    from manuscript_guard.auditing.abstract import placed
    from manuscript_guard.text.sections import Section

    heading_lines = frozenset(line for line, _title in pdf.headings)
    if pdf.repeated:
        report.not_audited.append(
            f"{pdf.path.name}: its lines were placed in no section: "
            + ", ".join(repr(name) for name in pdf.repeated)
            + " stands alone on two lines or more (a structured abstract's own headings, "
            "perhaps), and which is the paper's is not read")  # fmt: skip
        return {"heading_lines": heading_lines}
    sections = [Section(title, 1, "", line) for line, title in pdf.headings]
    place, abstract, results = placed(sections) if sections else (None, False, False)
    return {"place": place, "abstract": abstract, "results": results,
            "part": _parts(sections, None), "heading_lines": heading_lines}  # fmt: skip


def _structure(text: str, hidden: str, tables: list[Table], document) -> dict:
    """What a Markdown or a .docx paper's Abstract against Results and its flows are read
    from: where each line stands under its own headings, a Word document's by their styles;
    the lines in a table; its lists, a Word document's by their levels; and the counts in
    its text boxes. Each file is placed alone: a file with no Abstract is reported whole
    (round 2 of #472, DESIGN.md, "Known gaps")."""
    from manuscript_guard.auditing.abstract import placed
    from manuscript_guard.stats.flows import boxed_counts, docx_lists, markdown_lists
    from manuscript_guard.text.sections import Section, scannable, split_sections

    if document is None:
        sections = [s for s in split_sections(scannable(text)) if s.level]
        lines = frozenset(cell.line for table in tables for row in table for cell in row)
        lists = markdown_lists(text, hidden)
        boxed = 0
    else:
        body = document.body.split("\n")
        sections = [Section(body[at], level, "", at + 1) for at, level in document.heading_levels]
        lines = frozenset(at + 1 for at in document.cells)
        lists = docx_lists(body, dict(document.levels),
                           {at + 1: level for at, level in document.heading_levels})
        boxed = boxed_counts(document.boxed)
    place, abstract, results = placed(sections) if sections else (None, False, False)
    return {"place": place, "abstract": abstract, "results": results, "table_lines": lines,
            "lists": tuple(lists), "boxed": boxed,
            "part": _parts(sections, document), "heading_lines": _heading_lines(
                text, sections)}  # fmt: skip


def _parts(sections: list, document) -> Callable[[int], object] | None:
    """Where each line stands for the reader options that read sentences
    (`auditing.sentences.placing`); a Word document's footnotes and endnotes, read after its
    body, in no part, and not under its last heading (round 2 of #482)."""
    from manuscript_guard.auditing.sentences import Place, placing

    if not sections:
        return None
    place = placing(sections)
    if document is None or not document.notes:
        return place
    last = document.body.count("\n") + 1
    return lambda line: place(line) if line <= last else Place()


def _heading_lines(text: str, sections: list) -> frozenset[int]:
    """The lines a paper's headings stand on, a setext heading's underline among them."""
    lines = text.split("\n")
    found = set()
    for section in sections:
        found.add(section.line)
        below = lines[section.line] if section.line < len(lines) else ""
        if re.fullmatch(r"[ ]{0,3}(?:=+|-+)[ \t]*", below):
            found.add(section.line + 1)
    return frozenset(found)


def _latex_structure(latex) -> dict[Path, dict]:
    """What each LaTeX file's Abstract against Results and flows are read from: where each
    of its lines stands under the headings its document prints over it (`printed`, read
    back to the `.tex` line by `place_line`), the lines of its tables, and its lists."""
    from manuscript_guard.auditing import abstract as placing
    from manuscript_guard.auditing import sentences
    from manuscript_guard.auditing.sentences import place_tex_lines
    from manuscript_guard.stats.flows import latex_lists
    from manuscript_guard.text.latex.printed import printed
    from manuscript_guard.text.sections import scannable, split_sections

    hidden = {file.path: file.hidden for file in latex.files}
    found: dict[Path, dict] = {}
    for tree in latex.trees:
        sources = [source for _path, source in tree.files
                   if not source.path.lower().endswith(".sty")]  # fmt: skip
        view = printed(sources)
        sections = [s for s in split_sections(scannable(view.text)) if s.level]
        place, abstract, results = (placing.placed(sections) if sections
                                    else (None, False, False))  # fmt: skip
        by_line = placing.place_lines(view, place) if place is not None else {}
        parts = (place_tex_lines(view, sentences.placing(sections)) if sections
                 else {})  # fmt: skip
        for path, source in tree.files:
            if path in found or path not in hidden:
                continue
            at = _at_line(by_line.get(source.path, {}), None)
            part = _at_line(parts.get(source.path, {}), sentences.Place())
            text = source.text
            lines = frozenset(line for start, end in source.reading.tables
                              for line in range(text.count("\n", 0, start) + 1,
                                                text.count("\n", 0, end) + 2))  # fmt: skip
            found[path] = {"place": at if place is not None else None, "abstract": abstract,
                           "results": results, "table_lines": lines,
                           "lists": tuple(latex_lists(source, hidden[path])),
                           "part": part if sections else None}  # fmt: skip
    return found


def _at_line(mapped: dict[int, object], before: object) -> Callable[[int], object]:
    """Where a line of a LaTeX file stands: as the last line mapped at or before it stands,
    or `before` above the first."""
    from bisect import bisect_right

    ordered = sorted(mapped)

    def at(line: int) -> object:
        index = bisect_right(ordered, line) - 1
        return mapped[ordered[index]] if index >= 0 else before

    return at


def unread_shapes(path: Path, text: str) -> list[str]:
    """The lines of a Markdown paper that `check` and the build refuse, since the audit reads
    them as they do and pandoc may not: a line of backticks or tildes that is not a plain
    listing's (`fences.unclear_fence_lines`), and a comment opened in a list item or the
    like that pandoc ends with the item (`comments.unclear_comment_lines`). Around either
    the audit read code or a comment where pandoc printed prose, reported no numbers, and
    `--strict` passed."""
    return [
        *(
            f"{path.name}: line {line} is a line of backticks or tildes that is not a plain "
            "fenced listing, so what pandoc prints around it may not be what was audited"
            for line in unclear_fence_lines(text, front_matter_end(text))
        ),
        *(
            f"{path.name}: line {line} opens an HTML comment in a list item, a quotation, a "
            "definition, a footnote or a line block, which pandoc may print as text where it "
            "was not audited"
            for line in unclear_comment_lines(text)
        ),
    ]


def read_figure(path: Path) -> str | None:
    from manuscript_guard.gates.figures import _extract_text

    return _extract_text(path)


#: A numbered citation marker ending an atom, as the atom has it: its closing `]` trimmed.
_MARKER_AT_END = re.compile(r"\[\s*\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*[-–—]\s*\d{1,3})*\s*\]?$")


#: The runs the marker rule took whole before its prefix was narrowed: letters, digits and
#: `.%)`, then the marker, as the atom has it.
_ONCE_TAKEN = re.compile(r"[\w.%)]*\[\s*\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*[-–—]\s*\d{1,3})*\s*\]?")
#: The marker whole, from its `[` in the source: the rule required its `]`, and the atom may
#: stop before it, at the first number of a spaced list, `[1, 2]`.
_WHOLE_MARKER = re.compile(r"\[\s*\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*[-–—]\s*\d{1,3})*\s*\]")


def _apart(atom: Atom) -> list[tuple[Atom, bool]]:
    """An atom with a citation marker glued to a number, as the number and the marker, each
    with whether it is the number read apart.

    An atom runs to the next space, so `(95% CI 1.20, 9.99)[12]` arrives as `9.99)[12`, and
    the marker rule, spanning the word before a marker, filed the bound with the citation: it
    was never compared with the outputs. Read apart, the value is audited like any other and
    the marker is still a citation. A word before a marker has no digit, and stays whole.

    Only a run the rule took whole is read apart. That rule hid every number in it, so
    reading one apart can only add to what is compared. A run it did not take was listed
    whole, and splitting one handed its bracket to the marker rule: in `OR=3[1,20-9,99]` or
    `(Q1–Q3)[55–72]` an interval's bounds were filed as a citation.
    """
    marker = _MARKER_AT_END.search(atom.text)
    value = atom.text[: marker.start()] if marker else ""
    if marker is None or not DIGIT.search(value) or not _ONCE_TAKEN.fullmatch(atom.text):
        return [(atom, False)]
    if not _WHOLE_MARKER.match(atom.source, atom.start + marker.start()):
        return [(atom, False)]
    pieces: list[tuple[Atom, bool]] = []
    for raw, offset in ((value, 0), (marker.group(0), marker.start())):
        text, start = trim(raw, atom.start + offset)
        if text and DIGIT.search(text):
            end, col = start + len(text), atom.col + start - atom.start
            pieces.append((replace(atom, text=text, start=start, end=end, col=col), offset == 0))
    return pieces


#: A year on its own, which a number read apart from a marker may be: `(2019)[4]`.
_YEAR = re.compile(r"(?:19|20)\d{2}[a-z]?")


#: A bracketed range or pair of whole numbers after a value, `64 [55-72]` or `7 [4, 12]`.
#: The value may have a decimal point or a decimal comma, `12,5 [10-15]`, and a percent sign
#: spaced or not, `45 % [40-50]`. A value grouped in thousands, `1,204 [1,100-1,300]`, is
#: read first and as such, and its bounds may be grouped too: read as a decimal comma, `1,204
#: [1-3]` would enclose 1.204. The bounds are otherwise whole numbers of a citation's size,
#: which are what the marker rule takes: a bound with a decimal comma would make a citation
#: of `[4,12-15]` an interval from 4.12. Its brackets may be escaped, `64 \\[55-72\\]`, as
#: pandoc writes them, since the marker rule reads a citation so escaped (round 2 of #463).
_GROUPED = r"[1-9]\d{0,2}(?:,\d{3})+"
_AFTER_A_VALUE = re.compile(
    r"(?<![\w.,\[])"
    rf"(?:(?P<grouped>{_GROUPED})\s*"
    r"\\?\[\s*(?P<grouped_low>\d{1,3}(?:,\d{3})*)\s*(?:[,;]|[-–—])\s*"
    r"(?P<grouped_high>\d{1,3}(?:,\d{3})*)\s*\\?\]"
    r"|(?P<value>\d+(?:[.,]\d+)?)(?:\s?%)?\s*"
    r"\\?\[\s*(?P<low>\d{1,3})\s*(?:[,;]|[-–—])\s*(?P<high>\d{1,3})\s*\\?\])"
)


def _encloses(match: re.Match[str]) -> bool:
    """Whether the bounds `_AFTER_A_VALUE` found enclose the value written before them."""
    if match["grouped"]:
        low, value, high = (
            int(match[name].replace(",", "")) for name in ("grouped_low", "grouped", "grouped_high")
        )
        return low <= value <= high
    return int(match["low"]) <= float(match["value"].replace(",", ".")) <= int(match["high"])


def _within(spans: list[tuple[int, int]], starts: list[int], atom: Atom) -> bool:
    """Whether `atom` lies inside one of `spans`, which are sorted and do not overlap."""
    index = bisect.bisect_right(starts, atom.start) - 1
    return index >= 0 and atom.end <= spans[index][1]


def _intervals(text: str) -> list[tuple[int, int]]:
    """Where a bracketed run of whole numbers is an interval rather than a citation marker.

    Both are written `[55-72]`, and the marker rule took every one for a citation, so the
    bounds of a median [IQR] or a range were never audited. An interval encloses the value
    written before it, `64 [55-72]`; a citation range does not, `12% [4-6]`. A citation that
    happens to enclose a number before it, `found 2 [1,3]`, is read as an interval and listed.
    """
    return [
        (match.end("grouped") if match["grouped"] else match.end("value"), match.end())
        for match in _AFTER_A_VALUE.finditer(text)
        if _encloses(match)
    ]


def _masked(text: str, printed_as_typed: bool) -> str:
    """`text` masked, as `mask` does for Markdown, or, where `printed_as_typed`, with no HTML
    comment: a .docx and a figure print `<!--` as typed, and their text went through the
    same mask as Markdown, so a paragraph that mentions both markers hid everything between
    them. There each `<!--` is masked with its last hyphen made another character, so that
    it opens nothing and every other region is masked as before, and the hyphen is put back
    wherever it was left readable."""
    if not printed_as_typed:
        return mask(text)
    opens_nothing = mask(text.replace("<!--", "<!-\N{HYPHEN}"))
    kept = zip(opens_nothing, text, strict=True)
    return "".join(NUL if hidden == NUL else typed for hidden, typed in kept)


def doc_passed_over(path: Path) -> str:
    """What the report says of a .doc found in a folder given as a paper: the advice a .doc
    named on its own is refused with, under the path it was found at, where it is a compound
    file. A file named .doc that is none, Rich Text or a web page saved under that name, is
    not called a Word 97-2003 document."""
    try:
        with path.open("rb") as handle:
            opening = handle.read(len(COMPOUND_FILE))
    except OSError as exc:
        return f"{path.as_posix()} could not be read ({exc}), and was not audited"
    if is_compound_file(opening):
        return compound_file_said(path.as_posix())
    return (
        f"{path.as_posix()} is named .doc but is no Word 97-2003 document, and is not read: "
        "open it in Word and save it as a Word document (.docx)"
    )


def is_lock_file(path: Path) -> bool:
    """Whether `path` is the file Word keeps beside a document while it is open, "~$" and
    the rest of the document's name, which holds no paper."""
    return path.name.startswith("~$")


def audit(
    papers: list[Path],
    backing: list[Path] | None,
    *,
    figures: list[Path] | None = None,
    classifier: Classifier | None = None,
    whole_numbers: tuple[str, ...] = (),
    passed_over: list[Path] | None = None,
    found_tex: list[Path] | None = None,
    minimum: int | None = None,
    design: str | None = None,
    cited: bool = False,
) -> AuditReport:
    """`whole_numbers` names the rows of the papers' tables whose cells are means of whole
    numbers, which are held to their column's n (`stats/granularity.py`). `passed_over` is
    each .doc a folder given as a paper held, which is named in the report and not read.
    `backing` None is no outputs given: every number is read and classified, and none is
    compared. A `.tex` among `papers` is an entry (`auditing.latex`); `found_tex` are the
    other `.tex` files of a folder given, read where an entry inputs them. `minimum` is the
    data custodian's, below which a count held back that a total gives away is said.
    `design` is the study's design the reader declares, whose causal words are read
    (`auditing.causal`); `cited` asks for each citation beside its sentence
    (`auditing.cited`)."""
    # `rendered=True`: an existing paper has been through citeproc, so its citations are
    # "(Smith 2019)" rather than [@key]. That is the one place the audit-only rules apply.
    classifier = classifier or Classifier.load(rendered=True)
    values, used, skipped = load_backing(backing) if backing is not None else (set(), [], [])
    report = AuditReport(
        backing_values=values, backing_files=tuple(used), skipped=skipped,
        whole_numbers=whole_numbers, whole_numbers_unfound=list(whole_numbers),
        passed_over=[doc_passed_over(path) for path in passed_over or []],
        compared=backing is not None, minimum=minimum,
    )  # fmt: skip

    # Each source, whether a line may be taken for a reference entry by its shape, and
    # whether each of its lines is a block of its own. The shape only counts where no
    # heading said where the reference list is: once one has, the shape can only ever be
    # wrong, and in Markdown a line is a physical line, so a wrapped paragraph can open on
    # anything. A .docx and a figure are read a paragraph or an element per line; Markdown
    # and plain text are read as pandoc reads them.
    sources = _read_sources(report, papers, found_tex or [])
    read = len(sources)
    for path in figures or []:
        text = read_figure(path)
        if text is None:
            report.unreadable.append(
                f"{path.name}: no text layer, so its numbers cannot be audited"
            )
            continue
        if not text.strip():
            # matplotlib's default draws every label as outlines, so a figure full of numbers
            # reads as empty — and was listed as audited, with nothing unmatched in it.
            report.unreadable.append(
                f"{path.name}: no text at all, so nothing in it was audited; labels drawn "
                f"as outlines look like this (matplotlib: rcParams['svg.fonttype'] = 'none')"
            )
            continue
        # A figure prints `<!--`, as a .docx does.
        hidden = _masked(text, printed_as_typed=True)
        sources.append(_Source(path, text, hidden, text, text, (), False, True))

    report.papers = tuple(source.path for source in sources)
    pieces = []
    for source in sources:
        atoms = _read_numbers(report, source, classifier, values)
        _flows(report, source)
        pieces.append(_piece(source, atoms))
    from manuscript_guard.auditing.abstract import against_results

    report.abstract = against_results(pieces)
    if design is not None or cited:
        # The papers' sentences, not the figures': a PDF may be either (`auditing.pdf`).
        _read_sentences(report, sources[:read], papers, design, cited)
    return report


def _in_order(report: AuditReport, sources: list[_Source], papers: list[Path]) -> list:
    """The sources in the order the papers were given, a LaTeX file at its entry's place:
    the Markdown and Word papers are read before the LaTeX ones (round 2 of #482)."""
    entry_of = {path: tree.entry for tree in report.trees for path, _source in tree.files}
    given = {path: at for at, path in enumerate(papers)}

    def at(source: _Source) -> int:
        return given.get(entry_of.get(source.path, source.path), len(given))

    return sorted(sources, key=at)


def _read_sentences(report: AuditReport, sources: list[_Source], papers: list[Path],
                    design: str | None, cited: bool) -> None:  # fmt: skip
    """The causal words of `design`, and the cited sentences, of every paper read."""
    from manuscript_guard.auditing.causal import causal_words
    from manuscript_guard.auditing.cited import cited_sentences

    views = [view for source in _in_order(report, sources, papers)
             for view in _views(source)]
    if design is not None:
        report.causal = causal_words(views, design)
    if cited:
        report.cited = cited_sentences(views, _lists(report))


#: What is said of a front matter's abstract that is no plain text.
UNREAD_FRONT_MATTER = ("its front matter's abstract is a list or a mapping, not a plain "
                       "string, so its sentences were not read")


def _views(source: _Source) -> list:
    """One paper as its sentences are read (`auditing.sentences`): a Markdown file as
    pandoc prints it, a Word document a paragraph a line, a LaTeX file what it prints, each
    with its citations. A Markdown file's front matter is no body text: its abstract, where
    it is a plain string, is read as a text of its own, as the Abstract, at its key's line
    (round 1 of #482), and any other abstract there is said not to be read."""
    from manuscript_guard.auditing import sentences
    from manuscript_guard.claims import readable
    from manuscript_guard.text.masking import front_matter_abstract

    if source.latex is not None:
        read = source.hidden.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'")
        return [sentences.View(source.path, source.text, read, place=source.part,
                               cuts=sentences.latex_cuts(source.latex),
                               cites=tuple(sentences.latex_cites(source.latex, read)),
                               headings=sentences.latex_headings(source.latex))]  # fmt: skip
    # A .docx a paragraph a line, a PDF a line of a paragraph a line: neither is Markdown.
    typed = source.lines_are_blocks
    docx = typed and not source.wrapped
    read = (source.hidden.replace("\N{RIGHT SINGLE QUOTATION MARK}", "'") if typed
            else readable(source.text))  # fmt: skip
    cites = sentences.cites_in_text(source.text, source.hidden, _intervals(source.plain))
    head = 0 if typed else front_matter_end(source.text)
    found = front_matter_abstract(source.text) if head else None
    views, notes = [], ()
    if head:
        read = "".join(char if char == "\n" else NUL for char in read[:head]) + read[head:]
        cites = [cite for cite in cites if cite.start >= head]
    if found is not None and found[1]:
        line, value = found
        views.append(sentences.View(
            source.path, value, readable(value), line_offset=line - 1,
            place=lambda _line: sentences.Place(sentences.ABSTRACT, sentences.ABSTRACT),
            cites=tuple(sentences.cites_in_text(value, _masked(value, printed_as_typed=False),
                                                _intervals(value))),
        ))  # fmt: skip
    elif found is not None:
        notes = (UNREAD_FRONT_MATTER,)
    # A front matter's abstract first: it stands before the body (round 2 of #482).
    return [*views, sentences.View(
        source.path, source.text, read, lines=docx, place=source.part, cites=tuple(cites),
        notes=notes, headings=sentences.line_spans(source.text, source.heading_lines))]


def _lists(report: AuditReport) -> dict[Path, object]:
    """Each file's reference list: a Markdown or Word paper's own, and for each file of a
    LaTeX tree its document's."""
    found: dict[Path, object] = {}
    trees = {tree.entry: tree for tree in report.trees}
    for census in report.references:
        tree = trees.get(census.path)
        for path in ([path for path, _source in tree.files] if tree else [census.path]):
            found.setdefault(path, census)
    return found


def _piece(source: _Source, atoms: list[Atom]):
    """One source as the Abstract against Results reads it (`auditing.abstract`)."""
    from manuscript_guard.auditing.abstract import Piece

    return Piece(source.path, source.hidden, source.place, source.table_lines, source.abstract,
                 source.results, tuple(atoms))  # fmt: skip


def _flows(report: AuditReport, source: _Source) -> None:
    """Each list of one source read as a flow and held to its arithmetic (`stats/flows.py`),
    and a note where its text boxes give the counts a flow drawn in boxes would. A broken
    flow is counted where a heading over it, or the caption or paragraph before it, names a
    flow; under none it is a note, since a list of subgroups has the same shape (Basile,
    2026-10-29)."""
    from manuscript_guard.stats.flows import flows_in

    for flow in flows_in(list(source.lists)):
        report.flows_read += flow.read
        report.flows_named += flow.read and flow.named
        if flow.named:
            report.flows_broken += [Disagreement(source.path, flow.line, problem, flow.context)
                                    for problem in flow.problems]  # fmt: skip
        else:
            report.flow_notes += [
                Disagreement(source.path, flow.line, f"{problem}; no heading over the list, "
                             "nor the caption or paragraph before it, names a flow, so it is "
                             "not counted", flow.context)
                for problem in flow.problems
            ]  # fmt: skip
        report.flow_notes += [Disagreement(source.path, flow.line, note, flow.context)
                              for note in flow.notes]  # fmt: skip
    if source.boxed >= 2:
        report.flow_notes.append(Disagreement(
            source.path, 0, f"its text boxes give {source.boxed} counts (n = N), as a flow "
            "drawn in boxes does: a drawing is not read as a flow, a list is", ""))  # fmt: skip


def _read_numbers(
    report: AuditReport, source: _Source, classifier: Classifier, values: set[str]
) -> list[Atom]:
    """Every number of one source, classified and, where outputs were given, compared; the
    numbers the classifier left unexplained are returned, for the Abstract against Results."""
    rendered_only = {
        rule.id for rule in (*classifier.structural, *classifier.conventions) if rule.audit_only
    }
    # The same rules less those, for a number read apart from its marker: not part of a
    # citation, bar a year, but perhaps a page (`(Smith 2019, p. 12)[5]`) or a version.
    source_rules = replace(
        classifier,
        conventions=tuple(r for r in classifier.conventions if not r.audit_only),
        structural=tuple(r for r in classifier.structural if not r.audit_only),
        _memo={},
    )
    path, text, hidden = source.path, source.text, source.hidden
    found = _disagreements(path, hidden, list(source.tables))
    if report.whole_numbers:
        found = sorted(found + _whole_number_means(report, path, list(source.tables)),
                       key=lambda d: d.line)  # fmt: skip
    report.disagreements += found
    _margins(report, path, list(source.tables))
    scan = source.scan(classifier)
    source_scan = None
    intervals = _intervals(source.plain)
    starts = [start for start, _end in intervals]
    pieces = [piece for atom in find_atoms(text, hidden) for piece in _apart(atom)]
    unexplained: list[Atom] = []
    for atom, read_apart in pieces:
        if not _within(intervals, starts, atom):
            verdict = classifier.classify(atom, None, scan)
            # A number read apart from its marker may be a label, `Table 2[3]`, but not
            # part of a citation, bar a year: the author-year rule took the `9.99` of
            # `(2019; 95% CI 1.20, 9.99)[12]` for one.
            if read_apart and verdict.rule in rendered_only and not _YEAR.fullmatch(atom.text):
                if source_scan is None:
                    source_scan = source.scan(source_rules)
                verdict = source_rules.classify(atom, None, source_scan)
            if verdict.kind != UNCLASSIFIED:
                report.classified += 1
                continue
        unexplained.append(atom)
        if not report.compared:
            report.uncompared += 1
            continue
        candidate = Candidate(
            text=atom.text,
            normalised=normalise_number(atom.text),
            source=path,
            line=atom.line,
            context=atom.line_text.strip()[:140],
        )
        # Every number the atom carries has to be in the outputs, not just one of them:
        # an interval is accounted for when both its bounds are, and "0.72-0.99" with
        # only 0.72 published is exactly the discrepancy this command is for.
        matched = all(part in values for part in parts_of(atom.text))
        # A line shaped like a reference entry is compared like any other. Its numbers
        # are most likely a volume, a page and a year, so a miss is listed apart from
        # the findings rather than among them; a hit counts as a reference. The shape
        # used to decide instead, and a caption it accepted hid every number it held.
        if source.by_shape and looks_like_reference(atom.line_text):
            if matched:
                report.classified += 1
            else:
                report.reference_like.append(candidate)
        elif matched:
            report.matched.append(candidate)
        else:
            report.unmatched.append(candidate)
    return unexplained


def _whole_number_means(report: AuditReport, path: Path, tables: list[Table]) -> list[Disagreement]:
    """Each mean in a row --whole-numbers named, held to its column's n: returned where no
    whole total gives it, and listed apart where its n is too large to tell. A label under
    which a mean is read is taken off the labels that read nothing."""
    found = []
    for table in tables:
        for mean in table_means(table, report.whole_numbers):
            report.means_read += 1
            report.whole_numbers_unfound = [
                label for label in report.whole_numbers_unfound if not names(label, mean.label)
            ]
            verdict = possible(mean.mean, mean.n)
            if verdict is True:
                continue
            uncertain = f" (uncertain: {mean.uncertain})" if mean.uncertain else ""
            if verdict is None:
                report.means_not_assessable.append(Disagreement(
                    path, mean.line, f"{mean.printed} of n = {mean.n}{uncertain}", mean.context,
                ))  # fmt: skip
                continue
            said = f"{described_mean(mean.mean, mean.n)}{uncertain}"
            found.append(Disagreement(path, mean.line, said, mean.context))
    return found


def _margins(report: AuditReport, path: Path, tables: list[Table]) -> None:
    """Each table's totals held to their counts, its characteristics to their column's n,
    and each count it holds back that a total gives away (`stats/margins.py`)."""
    from manuscript_guard.gates.custodian import recoverable

    for table in tables:
        report.sums_off += [Disagreement(path, line.total.count.line, wrong, line.context)
                            for line, wrong in sums_off(table)]  # fmt: skip
        report.over_n += [Disagreement(path, found.line, found.message, found.context)
                          for found in over_n(table)]  # fmt: skip
        for found in recoverable(table, report.minimum):
            listed = report.recovered if found.line.explicit else report.recovered_by_n
            listed.append(Disagreement(path, found.member.count.line, said_recovered(found),
                                       found.member.context or found.line.context))  # fmt: skip


def _disagreements(path: Path, hidden: str, tables: list[Table]) -> list[Disagreement]:
    """The tests in a paper whose P does not follow from the statistic beside it, the
    estimates whose interval or P does not fit them, and the n (%) in its tables whose share
    is not what the count gives of its denominator, read in its text as masked (`_masked`)."""
    found = []
    for test in reported_tests(hidden):
        verdict = judge(test)
        if verdict is None or not verdict.inconsistent:
            continue
        context = " ".join(hidden[test.start : test.end].replace("\x00", " ").split())
        found.append(
            Disagreement(path, hidden.count("\n", 0, test.start) + 1,
                         described(test, verdict), context)  # fmt: skip
        )
    # And each estimate whose interval, or whose P, does not fit it (`stats/intervals.py`).
    for interval in reported_intervals(hidden):
        context = " ".join(hidden[interval.start : interval.end].replace("\x00", " ").split())
        line = hidden.count("\n", 0, interval.start) + 1
        if outside_interval(interval):
            found.append(Disagreement(path, line, described_outside(interval), context))
        share = asymmetry(interval)
        if share is not None and share > ASYMMETRY:
            found.append(Disagreement(path, line, described_asymmetry(interval, share), context))
        verdict = p_against(interval)
        if verdict is not None:
            found.append(Disagreement(path, line, described_against(interval, verdict), context))
    # And each n (%) in a table against its denominator (`stats/shares.py`).
    for table in tables:
        for share in table_shares(table):
            if off(share):
                found.append(Disagreement(path, share.line, described_share(share), share.context))
    return sorted(found, key=lambda d: d.line)


# --------------------------------------------------------------------------- discrimination


@dataclass(frozen=True)
class Discrimination:
    """How much a match is worth, measured against the backing set actually supplied."""

    small_integers: float
    medium_integers: float
    two_decimals: float

    def verdict(self) -> str:
        if self.small_integers > 0.5:
            return (
                "A match on a small integer means almost nothing here. Check those by hand."
            )
        if self.small_integers > 0.2:
            return "Matches on small integers are weak evidence."
        return "Matches carry real information in this project."


def measure_discrimination(values: set[str]) -> Discrimination:
    """What fraction of arbitrary numbers would match this backing set by chance.

    Reported alongside every audit because the alternative is a clean report that means
    nothing. The predecessor project measured 100% of integers up to 100 as already
    "backed"; a check with that property will tell you a paper is fine no matter what is
    in it.
    """
    small = sum(1 for n in range(1, 101) if str(n) in values) / 100
    medium = sum(1 for n in range(1, 1001) if str(n) in values) / 1000
    sample = [f"{n / 100:.2f}" for n in range(100, 1000, 7)]
    decimals = sum(1 for s in sample if normalise_number(s) in values) / len(sample)
    return Discrimination(small_integers=small, medium_integers=medium, two_decimals=decimals)


def render(
    report: AuditReport, discrimination: Discrimination | None, root: Path | None = None
) -> str:
    """The report in its sections (`auditing.report`)."""
    from manuscript_guard.auditing.report import render as sections

    return sections(report, discrimination, root)
