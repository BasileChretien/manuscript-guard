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
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.text.docx import NotADocx, is_docx, read_docx_text
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import heading_index, scannable, strip_attributes
from manuscript_guard.text.tokens import DIGIT, Atom, find_atoms, trim

PAPER_SUFFIXES = {".docx", ".md", ".txt", ".markdown"}
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
    #: Stretches of a paper that were read and deliberately not audited: the reference list.
    not_audited: list[str] = field(default_factory=list)
    #: Numbers found nowhere, on lines taken for reference entries by their shape. Listed
    #: apart from `unmatched`, where volumes and pages would bury the findings, but listed:
    #: four review rounds each found a caption some shape accepted.
    reference_like: list[Candidate] = field(default_factory=list)

    @property
    def examined(self) -> int:
        return (
            len(self.matched) + len(self.unmatched) + len(self.reference_like)
            + self.classified
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
    with no mark could be UTF-16 or binary, so they are refused rather than guessed at.
    """
    data = path.read_bytes()
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


# A line that is nothing but a bibliography heading, perhaps numbered, perhaps in bold. From
# there to the next heading is page ranges, volume numbers and years belonging to other
# people's papers: not the author's claims, and reporting them buries the findings that
# matter.
#
# Everything after the heading word is one character class under one quantifier. The first
# version had five optional whitespace runs in a row there, and a line that began with the
# word and failed later backtracked through every way of dividing its spaces between them:
# 26 s for one line of the kind `pdftotext -layout` writes.
#
# And every run of whitespace before the word has exactly one quantifier that can take it:
# the line is stripped first, and a number takes the spaces after it. With `^\s*` beside
# `[\s*_]*` a failing line was still quadratic in its indentation, and `pdftotext -layout`
# indents a right-hand column by a hundred spaces: 20 s for 3,000 such lines.
#
# A pandoc attribute block after the word, `{-}` or `{#refs .unnumbered}`, is not matched
# here. It is taken off a marked heading before the match, by `strip_attributes`, which reads
# it item by item, so this pattern keeps one quantifier after the word.
_BIBLIOGRAPHY = re.compile(
    r"^(?P<hashes>#+)?[\s*_]*"
    r"(?:(?P<numbered>\d+[.)])[\s*_]*|(?P<bare>\d+)\s[\s*_]*)?"
    r"(?P<word>references(?:\s+cited)?|reference\s+list|list\s+of\s+references"
    r"|cited\s+references|bibliography|works\s+cited|literature\s+cited|cited\s+literature)"
    r"(?P<tail>[\s*_:.|]*)$",
    re.IGNORECASE,
)


def is_bibliography_heading(
    line: str, *, marked: bool = False, markdown: bool = True
) -> bool:
    """A bibliography heading: a line that is marked as a heading, or has a heading's shape.

    `marked` is for a line the document itself calls a heading, a Markdown `#` or setext
    heading or a styled paragraph in a .docx. Any other line has to look like one:
    capitalised, and not ending in a full stop. "12 references." and "references." are where
    a hard wrap left the end of a sentence, and taking either for a heading hid the rest of
    the section.

    A marked line is read without the attribute block at its end, as pandoc reads it.
    Pandoc users write an unnumbered reference heading as `# References {-}`, and the audit
    found no heading there: it cut nothing, and every number in a book or a web page in the
    list was reported among the findings. On an unmarked line the braces are printed, so
    "References {-}" there is text. Only spaces and tabs may follow the block: `strip()`
    takes every Unicode space, and a no-break space after `{-}`, which pandoc prints braces
    and all, cut a list.

    `markdown` says whether the marks are Markdown's. There a marked line opening with `#`
    is an ATX heading and loses its closing `#`s. A setext heading reading "References #"
    prints the `#`, and so does a .docx, where a style marks the heading and Word prints
    every `#` in "# References #".

    An unmarked line starting with `#` is not one at all. `#` opens a comment in R, Python
    and YAML, and `# References` in a code listing cut everything after it; where `#` does
    make a heading, the document has marked it.
    """
    text = line.strip()
    if marked:
        text = strip_attributes(line.lstrip().rstrip(" \t"))
        if markdown and text.startswith("#"):
            text = text.rstrip("#").rstrip(" \t")
        text = text.strip()
    found = _BIBLIOGRAPHY.match(text)
    if not found:
        return False
    if marked:
        return True
    if found.group("hashes"):
        return False
    return found.group("word")[0].isupper() and "." not in found.group("tail")


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
    + r"(?:\((?:19|20)\d{2}[a-z]?(?:,[^)]{0,20})?\)\.|(?:\.|(?<=\.))\s+(?:19|20)\d{2}[a-z]?\.)",
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
# follow. A style with no full stop before the year, as the BMJ's own, is not recognised,
# which is the safe direction.
#
# Each whitespace run has one quantifier that can take it: two side by side made every
# unclassified number on an indented line quadratic.
_VANCOUVER_ENTRY = re.compile(
    r"^\s*(?:(?:\[\d{1,4}\]|\d{1,4}[.)])\s*)?"            # "12." / "[12]" / "12)"
    rf"(?:[a-z]{{1,3}}\s+){{0,2}}[{_CAPITAL}][\w'’-]+\s+[{_CAPITAL}](?:-?[{_CAPITAL}]){{0,3}}"
    rf"[,.](?=\s+(?:[{_CAPITAL}]|et\s+al\b))"             # ... then an author or the title
    # The full stop that ends a journal's name, and not one ending "Dec." or "vs.".
    r".{0,400}?(?<!Jan)(?<!Feb)(?<!Mar)(?<!Apr)(?<!Jun)(?<!Jul)(?<!Aug)(?<!Sep)(?<!Sept)"
    r"(?<!Oct)(?<!Nov)(?<!Dec)(?<!vs)\.\s+(?:19|20)\d{2}[a-z]?"  # "Lancet. 2019"
    r"(?:\s+[A-Z][a-z]{2}(?:\s+\d{1,2})?)?"               # "2019 Mar", "2019 Mar 5"
    r";\s?\d+(?:\([^)]{1,20}\))?:\s?"                     # ";393:", ";42(3):", ";393(Suppl 1):"
    r"[A-Za-z]{0,2}\d+(?:[-–][A-Za-z]{0,2}\d+)?"          # "100-10", "e0213", "n71", "S1-S10"
    r"\.?(?:\s+(?:(?i:doi\b|https?://|pubmed\b|pmid\b|pmcid\b|epub\b|available\b"
    r"|published\b)|\[)[^\n]*)?\s*$"
)

# A Markdown footnote definition. It can sit after the bibliography heading, and it is the
# author's text, not a reference.
_FOOTNOTE = re.compile(r"^\s{0,3}\[\^[^\]]+\]:")


def looks_like_reference(line: str) -> bool:
    """Whether a line has the shape of a reference entry. A shape can be wrong, and every
    number on a line it accepts goes uncompared, so the audit names the lines it accepted."""
    return bool(_REFERENCE_ENTRY.match(line) or _VANCOUVER_ENTRY.match(line))


def _markdown_heading_lines(text: str) -> frozenset[int]:
    return frozenset(text.count("\n", 0, found.start) for found in heading_index(text))


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
            for i in sorted(headings)
            if i > start
            and not is_bibliography_heading(lines[i], marked=True, markdown=markdown)
        )
        spans.append((start, next(after, last)))
    return spans


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


def read_paper(path: Path) -> tuple[str, list[tuple[int, int]]]:
    """The paper's text with its reference lists blanked, and which lines those were.

    A .docx's footnotes and endnotes follow its body, and are read after the cut rather than
    through it: they were being dropped along with the bibliography.
    """
    if not is_docx(path):
        text = read_text(path)
        spans = bibliography_spans(text)
        return _blank(text, spans), spans
    document = read_docx_text(path)
    spans = bibliography_spans(document.body, document.headings, document.cells)
    body = _blank(document.body, spans)
    return (f"{body}\n{document.notes}" if document.notes else body), spans


def read_figure(path: Path) -> str | None:
    from manuscript_guard.gates.figures import _extract_text

    return _extract_text(path)


#: A numbered citation marker ending an atom, as the atom has it: its closing `]` trimmed.
_MARKER_AT_END = re.compile(r"\[\s*\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*[-–—]\s*\d{1,3})*\s*\]?$")


#: The runs the marker rule took whole before its prefix was narrowed: letters, digits and
#: `.%)`, then the marker, as the atom has it.
_ONCE_TAKEN = re.compile(r"[\w.%)]*\[\s*\d{1,3}(?:\s*[,;]\s*\d{1,3}|\s*[-–—]\s*\d{1,3})*\s*\]?")
#: The marker's closing bracket, which the atom's trimming took off and the rule required.
_CLOSED = re.compile(r"\s*\]")


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
    taken = _ONCE_TAKEN.fullmatch(atom.text) and _CLOSED.match(atom.source, atom.end)
    if marker is None or not DIGIT.search(value) or not taken:
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
_AFTER_A_VALUE = re.compile(
    r"(?<![\w.,\[])(?P<value>\d+(?:\.\d+)?)%?\s*"
    r"\[\s*(?P<low>\d{1,3})\s*(?:[,;]|[-–—])\s*(?P<high>\d{1,3})\s*\]"
)


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
        (match.end("value"), match.end())
        for match in _AFTER_A_VALUE.finditer(text)
        if int(match["low"]) <= float(match["value"]) <= int(match["high"])
    ]


def audit(
    papers: list[Path],
    backing: list[Path],
    *,
    figures: list[Path] | None = None,
    classifier: Classifier | None = None,
) -> AuditReport:
    # `rendered=True`: an existing paper has been through citeproc, so its citations are
    # "(Smith 2019)" rather than [@key]. That is the one place the audit-only rules apply.
    classifier = classifier or Classifier.load(rendered=True)
    values, used, skipped = load_backing(backing)
    report = AuditReport(backing_values=values, backing_files=tuple(used), skipped=skipped)

    # Each source, and whether a line may be taken for a reference entry by its shape. Only
    # where no heading said where the reference list is: once one has, the shape can only
    # ever be wrong, and in Markdown a line is a physical line, so a wrapped paragraph can
    # open on anything.
    sources: list[tuple[Path, str, bool]] = []
    for path in papers:
        try:
            text, spans = read_paper(path)
        except (NotADocx, OSError, UnreadableText) as exc:
            report.unreadable.append(str(exc))
            continue
        sources.append((path, text, not spans))
        report.not_audited += [
            f"{path.name}: lines {start + 1}-{end}, read as the reference list"
            for start, end in spans
        ]
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
        sources.append((path, text, False))

    report.papers = tuple(path for path, _text, _shape in sources)
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

    for path, text, by_shape in sources:
        intervals = _intervals(text)
        starts = [start for start, _end in intervals]
        pieces = [piece for atom in find_atoms(text, mask(text)) for piece in _apart(atom)]
        for atom, read_apart in pieces:
            if not _within(intervals, starts, atom):
                verdict = classifier.classify(atom)
                # A number read apart from its marker may be a label, `Table 2[3]`, but not
                # part of a citation, bar a year: the author-year rule took the `9.99` of
                # `(2019; 95% CI 1.20, 9.99)[12]` for one.
                if read_apart and verdict.rule in rendered_only and not _YEAR.fullmatch(atom.text):
                    verdict = source_rules.classify(atom)
                if verdict.kind != UNCLASSIFIED:
                    report.classified += 1
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
            found = all(part in values for part in parts_of(atom.text))
            # A line shaped like a reference entry is compared like any other. Its numbers
            # are most likely a volume, a page and a year, so a miss is listed apart from
            # the findings rather than among them; a hit counts as a reference. The shape
            # used to decide instead, and a caption it accepted hid every number it held.
            if by_shape and looks_like_reference(atom.line_text):
                if found:
                    report.classified += 1
                else:
                    report.reference_like.append(candidate)
            elif found:
                report.matched.append(candidate)
            else:
                report.unmatched.append(candidate)

    return report


def _ranges(numbers: list[int]) -> str:
    """"3-25, 29": sorted line numbers, with any no more than two apart shown as a range,
    since reference entries are usually separated by blank lines."""
    runs: list[list[int]] = []
    for number in numbers:
        if runs and number - runs[-1][-1] <= 2:
            runs[-1].append(number)
        else:
            runs.append([number])
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


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


def render(report: AuditReport, discrimination: Discrimination, root: Path | None = None) -> str:
    def show(path: Path) -> str:
        if root is None:
            return path.name
        try:
            return str(path.relative_to(root))
        except ValueError:
            return path.name

    lines: list[str] = []
    lines.append(
        f"Audited {len(report.papers)} file(s) against {len(report.backing_values)} distinct "
        f"numbers from {len(report.backing_files)} output file(s)."
    )
    apart = (
        f", and {len(report.reference_like)} not found on lines read as reference entries"
        if report.reference_like
        else ""
    )
    lines.append(
        f"{report.examined} numeric tokens: {report.classified} conventions or references, "
        f"{len(report.matched)} found in the outputs, {len(report.unmatched)} not found{apart}."
    )

    for heading, items in (
        ("Could not read:", report.unreadable),
        ("Outputs not read as given:", report.skipped),
        ("Not audited:", report.not_audited),
    ):
        if items:
            lines.append("")
            lines.append(heading)
            lines += [f"  {item}" for item in items]

    if report.unmatched:
        lines.append("")
        lines.append("NOT FOUND IN ANY OUTPUT — check each of these:")
        by_source: dict[Path, list[Candidate]] = {}
        for candidate in report.unmatched:
            by_source.setdefault(candidate.source, []).append(candidate)
        for source, items in by_source.items():
            lines.append(f"  {show(source)}")
            for candidate in items[:40]:
                lines.append(f"    line {candidate.line}: {candidate.text}")
                lines.append(f"      {candidate.context}")
            if len(items) > 40:
                lines.append(f"    (+{len(items) - 40} more)")

    if report.reference_like:
        lines.append("")
        lines.append(
            "NOT FOUND, ON LINES READ AS REFERENCE ENTRIES — mostly volumes, pages and years; "
            "a caption or sentence misread as an entry shows up here (not counted by --strict):"
        )
        by_line: dict[Path, dict[int, list[str]]] = {}
        for candidate in report.reference_like:
            numbers = by_line.setdefault(candidate.source, {})
            numbers.setdefault(candidate.line, []).append(candidate.text)
        for source, numbers in by_line.items():
            lines.append(f"  {show(source)}")
            ordered = sorted(numbers)
            for number in ordered[:40]:
                lines.append(f"    line {number}: {', '.join(numbers[number])}")
            if len(ordered) > 40:
                lines.append(f"    (+{len(ordered) - 40} more lines: {_ranges(ordered[40:])})")

    lines.append("")
    lines.append("What a match is worth here:")
    lines.append(
        f"  integers 1-100    {discrimination.small_integers:6.0%} of all possible values "
        f"already match"
    )
    lines.append(f"  integers 1-1000   {discrimination.medium_integers:6.0%}")
    lines.append(f"  two-decimal       {discrimination.two_decimals:6.0%}")
    lines.append(f"  {discrimination.verdict()}")
    if discrimination.small_integers > 0.5:
        lines.append(
            "  Point --against at the analysis outputs rather than the raw data if you can. "
            "A row-level dataset contains most small integers, so it matches almost anything."
        )
    lines.append("")
    lines.append(
        "This audit asks only whether a number appears somewhere in the outputs. It cannot "
        "tell whether it appears in the right place, or whether the sentence around it is "
        "true. For a paper still being written, bind the numbers instead: "
        "`manuscript-guard init`."
    )
    return "\n".join(lines)
