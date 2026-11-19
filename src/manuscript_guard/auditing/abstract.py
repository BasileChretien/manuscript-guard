"""The audit's Abstract against Results: each number the Abstract gives, looked for where the
paper reports, and each interval and test the Abstract gives held to its counterpart there.

An abstract summarises: every number in it should be reported in the paper too. Where the
paper reports is every section but the Abstract, the Introduction, the Discussion, a
conclusion, a summary of the paper and the back matter, and no note (`placed`), the Methods
and the Results as G8 reads them (`gates.reported.Walk`) among them; every table of every
file; the whole of a file with no Abstract, which is a supplement; and, in Markdown, a .docx
or a PDF, the lines between a reference list's end and the next heading, a table typed as
text, a caption or a legend after a list that ends at a display, what follows a thematic
break or a heading-shaped line in Markdown, or a back-matter title in a PDF, an entry there
by its shape or its next number resuming the list (`_past_the_lists`; Basile, 2026-11-15;
rounds 1 and 2 of #692). In LaTeX those lines stand under the section before the list, as it prints
them (DESIGN.md, "Known gaps"). A line
is placed under the headings over it, a Markdown paper's (`split_sections`), a Word
document's heading styles (`DocxText.headings`), a LaTeX document's printed view, its places
read back to the `.tex` lines (`printed`, `place_line`, `place_lines`). Each file is placed
by its own headings, unlike G8, which carries a project's headings from file to file: a
paper split into files has a Discussion in a file of its own reported whole, as a
supplement (round 2 of #472, DESIGN.md, "Known gaps"). Where no file has an Abstract
heading, or none a Results heading, nothing is compared, and the author is asked why, a
question the answers `Answers` holds end (Basile, 2026-11-16, decision 27): a heading
that is the Results by another name, "Experiments", "Numerical results" (`RESULTS_LIKE`), is
one here, and so is one whose title `--results` gives; the comparison never falls back to
the whole body (Basile, 2026-11-13).

* **Not found.** A number of the Abstract the classifier leaves unexplained, not found in
  the tables or any section that reports (`placed`), is said.
  A rounding of one is a match, "53%" for "53.3%" (the author, 2026-10-28), and counted
  apart: the Abstract's number is one the
  reported number rounds to at its places. A part with letters in it and no number read in
  it, "v8", "rs75015950", "chr15", is found only as printed, a whole word where the paper
  reports: an identifier was otherwise never found, even beside its copy in the Methods (a
  preprint of the real-paper corpus, pharm-epi, 2026-11-11). A match here is as weak as the
  audit's against the outputs, and the section ends with what one is worth, the roundings
  counted in. A number in scientific notation, `3\\times 10^{8}`, and a power, `10^{-2}`,
  `10^8`, `10^-2^`, are read whole, in the Abstract and where the paper reports alike
  (`powers`), and found only where the same sign, mantissa and power are printed; a scale,
  a power after a times sign with no mantissa, is no number. Read as atoms, LaTeX's
  `10^{-2}`, its braces blanked, was "10^" and "-2" (tex-astro-ga-B1 of the real-paper
  corpus; round 1 of #696).
* **Asked.** A number not found where the paper reports that the Introduction or its
  material, the Discussion, a "Limitations" or a conclusion gives (`Aside`), matched as
  above, is a question to the author, not a number not found (`ASKED_ONLY_IN`): is that
  where the paper reports it, or is it background? A number of a structured Abstract's
  Background (`BACKGROUND_PARTS`) is looked for in the Introduction and its material too,
  and one found nowhere is a question of its own (`ASKED_BACKGROUND`): is it from the
  literature? (Basile, 2026-11-16, decision 27, part B.)
* **From its counts.** A percentage the Abstract writes beside both its counts, "164 out
  of 250 (66%)", "66% (164/250)" (`stats.shares.written_shares`), is held to them, as a
  table's n (%) is to its denominator, and not looked for: one they give is explained by
  them (`from_counts`), and one they do not, "164 out of 250 (75%)", is an arithmetic
  finding (`arithmetic`, which the audit lists with the other numbers that do not fit the
  ones beside them) and neither found nor not found (the author, 2026-11-11). The counts
  are looked for as any number is. A count with no denominator beside it, "n = 164 (66%)",
  explains nothing, and its percentage is looked for.
* **Conflict.** An exact pairing only. An interval of the Abstract (`reported_intervals`) of
  the same estimate and level as one interval where the paper reports, two of whose three
  numbers agree with it, estimate, lower bound and upper bound, and whose third does not; or
  a test (`reported_tests`) of the same kind, degrees of freedom and statistic as one test
  there, whose P cannot be the same. Two printed numbers agree where one value could be
  printed as both, each to its places: 1.5 and 1.52 agree, 1.90 and 1.89 do not. Where two
  intervals or tests there could be its counterpart, it has none.

`--strict` counts a conflict, and not a number not found (the author, 2026-10-28).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from functools import cache
from math import ceil, floor
from pathlib import Path

from manuscript_guard.keys import ABSTRACT as ABSTRACT_PART
from manuscript_guard.keys import digest, sentence_at
from manuscript_guard.stats.intervals import ReportedInterval, reported_intervals
from manuscript_guard.stats.reported import Reported, p_range, reported_tests
from manuscript_guard.text.markdown_maths import markdown_maths
from manuscript_guard.text.section_names import (
    _METHOD_TITLE,
    ABSTRACT_PARTS,
    _whole,
    names_abstract,
    names_conclusion,
    names_discussion,
    names_introduction,
    names_introduction_material,
    names_keywords,
    names_paper_summary,
    names_results,
    names_statement,
    plain,
)
from manuscript_guard.text.sections import Section
from manuscript_guard.text.tokens import Atom

NUL = "\x00"
#: The headings that are the Results by another name, to the Abstract against Results alone,
#: each a whole title in small letters, numbered, marked or not, and nothing else: "4.
#: Experiments", not "Experiments on synthetic data". The names machine-learning, statistics
#: and astronomy papers give their Results, and those of the real-paper corpus whose Abstract
#: was not compared for want of a Results heading, "Numerical Results" (tex-astro-ga-A2),
#: "Experiments and Results" (tex-cs-lg-A1) and "Empirical analysis" (tex-stat-ap-B1)
#: (Basile, 2026-11-13). "Findings" and "Results and discussion" are the Results already
#: (`names_results`). Not "Analysis", "Data analysis" or "Statistical analysis", as often
#: the Methods as the Results, nor "Simulation studies", which holds a study's design with
#: what it found. No gate reads these: G2's and G9's Results, `init --from` and the order
#: of the sections keep to `names_results`. A closed list.
RESULTS_LIKE = (
    "experiments", "experiments and results", "experimental results", "empirical results",
    "empirical analysis", "main results", "evaluation", "numerical results",
    "simulation results",
)  # fmt: skip
#: What the section is called in the report.
NO_ABSTRACT = "no file has a heading that names the Abstract"
NO_RESULTS = ("no file has a Results heading outside the Abstract, nor a heading whose whole "
              "title is one of the names the Results go by elsewhere: "
              + ", ".join(f'"{name.capitalize()}"' for name in RESULTS_LIKE))  # fmt: skip

#: The questions the section asks the author where no exact rule can decide, each with the
#: answer that ends it (Basile, 2026-11-16, decision 27): a finding of its own kind, which
#: never fails and never counts, says what it saw and asks (`report.question`).
ASKED_NO_ABSTRACT = "question-no-abstract"
ASKED_NO_RESULTS = "question-no-results"
#: Each asks only what is true of the paper read: a PDF cannot be given a heading, so where
#: the paper is one, the change is made in the document it was made from, which is audited
#: instead (round 1 of #697). An answer lasts the run it is given in (DESIGN.md, "Known
#: gaps").
_NAMES = ", ".join(f'"{name.capitalize()}"' for name in RESULTS_LIKE)
_ABSTRACT_SEEN = ("No heading names the Abstract, so it was not compared with the Results. Has "
                  "the paper no Abstract? If its first paragraph, or the text under its title, "
                  'is the Abstract, put the heading "Abstract" over it')  # fmt: skip
_NO_ABSTRACT_ANSWER = ("; if it has none, run `audit` again with `--no-abstract`, and the "
                       "audit then takes the paper as having none.")  # fmt: skip
ASK_NO_ABSTRACT = f"{_ABSTRACT_SEEN} and audit it again{_NO_ABSTRACT_ANSWER}"
ASK_NO_ABSTRACT_PDF = (f"{_ABSTRACT_SEEN} (a PDF cannot be given one) in the document the PDF "
                       f"was made from, and audit that document{_NO_ABSTRACT_ANSWER}")
#: Asked where a PDF is read beside a file of another kind, the one question of the run being
#: true of both (the check of 643700b, #697).
ASK_NO_ABSTRACT_MIXED = (f"{_ABSTRACT_SEEN} (in a PDF's case, in the document the PDF was made "
                         f"from, since a PDF cannot be given one, which is then audited in the "
                         f"PDF's place) and audit it again{_NO_ABSTRACT_ANSWER}")
_RESULTS_SEEN = (
    f'No section is read as the Results (no heading is "Results" or one of the names they go '
    f"by: {_NAMES}), so the Abstract was not compared with them. Which heading holds the "
    "paper's results? Run `audit` again with `--results \"<that heading>\"`, and the audit "
    "then takes that heading as the Results. If they stand under a title that is read as no "
    "heading, "
)  # fmt: skip
_NO_RESULTS_ANSWER = "; if the paper reports no results, run it with `--no-results`."
ASK_NO_RESULTS = (f"{_RESULTS_SEEN}a title typed in bold or numbered by Word, make it a "
                  f"heading, in Word by a heading style, and audit it again{_NO_RESULTS_ANSWER}")
ASK_NO_RESULTS_PDF = (f"{_RESULTS_SEEN}make it a heading in the document the PDF was made from "
                      f"and audit that document{_NO_RESULTS_ANSWER}")
ASK_NO_RESULTS_MIXED = (f"{_RESULTS_SEEN}a title typed in bold or numbered by Word, make it a "
                        f"heading, in Word by a heading style and in a PDF's case in the "
                        f"document the PDF was made from, which is then audited in the PDF's "
                        f"place, and audit it again{_NO_RESULTS_ANSWER}")
#: Why nothing was compared, where the author answered that there is nothing to compare;
#: and the same in a referee's draft, which names no one (`draft`).
SAID_NO_ABSTRACT = "the author says the paper has no Abstract"
SAID_NO_RESULTS = "the author says the paper reports no results"
TOLD = {SAID_NO_ABSTRACT: "the audit was run with the answer that the paper has no Abstract "
                          "(`--no-abstract`)",
        SAID_NO_RESULTS: "the audit was run with the answer that the paper reports no results "
                         "(`--no-results`)"}  # fmt: skip
#: What is said of an answer the paper's own headings contradict, of a title that names no
#: heading, of one whose heading is not read as the Results, and of one whose heading is a
#: section searched for none of the Abstract's numbers otherwise, read as given.
CONTRADICTED = "abstract-answer-contradicted"
UNMATCHED = "results-heading-unmatched"
NOT_TAKEN = "results-heading-not-read"
LIFTED = "results-heading-reports-nothing"
_CONTRADICTS_ABSTRACT = ("--no-abstract: a heading names the Abstract, so the paper's own "
                         "heading is taken over the answer and the Abstract is read as usual")
_CONTRADICTS_RESULTS = ("--no-results: a heading is read as the Results, so the paper's own "
                        "heading is taken over the answer and the Abstract is compared with "
                        "them as usual")  # fmt: skip
_UNMATCHED = '--results "{0}": no heading is "{0}"'
_NOT_TAKEN = ('--results "{0}": the heading stands in the Abstract, on the title page or under '
              "a section that reports nothing, so it is not read as the Results")
_LIFTED = ('--results "{0}": the heading is a section the comparison otherwise searches for '
           "none of the Abstract's numbers, as it does the Introduction, the Discussion, a "
           "conclusion and the back matter; it is read as the Results, as given, so a number of "
           "the Abstract it "
           "repeats is found there")
#: The questions asked of one number of the Abstract, once compared (Basile, 2026-11-16,
#: decision 27, part B): one not found where the paper reports that a section reporting
#: nothing gives, where a paper may report it or give it as background (`Aside`); and one
#: of the Abstract's Background found nowhere, which is the literature's and wants its
#: source in the Introduction.
ASKED_ONLY_IN = "question-number-only-in"
ASKED_BACKGROUND = "question-background-unsourced"
ASK_BACKGROUND = ("{0} in the Abstract's Background is given nowhere in the paper. Is it from "
                  "the literature? The Introduction should give it, with its source.")  # fmt: skip


def _only_in_seen(text: str, places: list[tuple[tuple[str, ...], str]],
                  parts: tuple[str, ...] = ()) -> str:  # fmt: skip
    """What the audit saw of a number of the Abstract found only in sections that report
    nothing: each section by the titles of the headings over it that report nothing and
    where it stands there, as the report says a place; and, where some of the number's parts
    are found where the paper reports, the parts that are not (round 1 of #700)."""
    where = " and ".join(f"under {', '.join(map(_quoted, titles))} ({at})"
                         for titles, at in places)  # fmt: skip
    verb = "are" if len(parts) > 1 else "is"
    subject = (f"Of {text} in the Abstract, {' and '.join(parts)} {verb}" if parts
               else f"{text} in the Abstract is")
    return (f"{subject} found only {where}, where the comparison does not look for the "
            "Abstract's numbers")


def asked_only_in(text: str, places: list[tuple[tuple[str, ...], str]],
                  parts: tuple[str, ...] = ()) -> str:  # fmt: skip
    """The question asked of a number of the Abstract found only in sections that report
    nothing (`ASKED_ONLY_IN`): what the audit saw (`_only_in_seen`), and the answer, the
    `--results` that names every heading over it that reports nothing, or the number given
    in the Methods or the Results."""
    flags = " or ".join(dict.fromkeys(
        "`" + " ".join(f'--results "{title}"' for title in titles) + "`"
        for titles, _at in places))  # fmt: skip
    return (f"{_only_in_seen(text, places, parts)}. Is that where the paper reports it, or is "
            f"it background? If the paper reports it there, run `audit` again with {flags}, "
            "and the audit then takes that heading as the Results; otherwise give it in the "
            "Methods or the Results.")


def referee_only_in(text: str, places: list[tuple[tuple[str, ...], str]],
                    parts: tuple[str, ...] = ()) -> str:  # fmt: skip
    """The same question as a referee's draft says it (`draft`): what the audit saw, and
    that the author is asked, naming no flag (round 1 of #700)."""
    return (f"{_only_in_seen(text, places, parts)}: the author is asked whether the paper "
            "reports it there or gives it as background.")


#: A Background figure given nowhere, as a referee's draft says it.
REFEREE_BACKGROUND = ("{0} in the Abstract's Background is given nowhere in the paper: the "
                      "author is asked whether it is from the literature, which the "
                      "Introduction should give with its source.")  # fmt: skip


def _quoted(title: str) -> str:
    return f'"{title}"'


#: The parts of a structured Abstract that hold its background, by their whole names, a
#: heading's or a run-in label's (Basile, 2026-11-16): a number there may be the
#: literature's, which the Introduction gives with its source, so it is looked for there too.
BACKGROUND_PARTS = ("background", "introduction", "context", "rationale", "objective",
                    "objectives")  # fmt: skip
#: The names a structured Abstract's other parts go by, which end its Background where a
#: line opens on one as a run-in label: the parts `section_names.ABSTRACT_PARTS` names, those
#: `auditing.sentences` reads under a "Summary", and the keywords.
_OTHER_PARTS = (*sorted(ABSTRACT_PARTS), "aim", "aims", "purpose", "design", "setting",
                "participants", "interpretation", "keywords", "key words")  # fmt: skip
#: The sections that report nothing whose numbers a paper may yet report, where an Abstract's
#: number found nowhere else is asked about (`Aside`): the Introduction and its material, the
#: Discussion, a "Limitations" and a conclusion; never the title page, the statements, the
#: notes, the reference list, the keywords nor a summary of the paper.
_LIMITATIONS = ("limitations", "strengths and limitations")


#: Where a run-in label may stand: where a line opens, or a sentence has ended. A Word
#: paper's structured Abstract is often one paragraph, "Background: ... Methods: ...", its
#: labels inside the line (docx-sport-A3 of the real-paper corpus).
_LABEL_OPENS = r"(?:^|(?<=[.!?])(?=[ \t]))[ \t*_]*"


def _label(names: tuple[str, ...]) -> re.Pattern[str]:
    """A run-in label of one of `names`, or of two joined by "and" or "&", the first named
    `first`, a capital first, emphasis around it or not, and a colon or a stop after it:
    "Background:", "**Objectives.**", "Background and aims:", "METHODS:"."""
    every = "|".join(re.escape(name).replace(r"\ ", r"\s+")
                     for name in sorted({*names, *BACKGROUND_PARTS, *_OTHER_PARTS}, key=len,
                                        reverse=True))  # fmt: skip
    first = "|".join(re.escape(name).replace(r"\ ", r"\s+")
                     for name in sorted(names, key=len, reverse=True))  # fmt: skip
    return re.compile(rf"{_LABEL_OPENS}(?=(?-i:[A-Z]))(?P<first>{first})"
                      rf"(?:\s*(?:and|&)\s*(?:{every}))?[*_]*[ \t]*[:.]",
                      re.IGNORECASE | re.MULTILINE)  # fmt: skip


#: A label that opens the Background, and one that opens any part: a part's name the audit
#: knows, with a colon or a stop after it; or a run-in label of any wording, a word with a
#: capital first and up to five more words of letters, commas and "&" allowed between them,
#: and a colon after it, as structured Abstracts write theirs: JAMA's "Design, Setting, and
#: Participants:", "Main Outcomes and Measures:", "Exposures:", "Study design:", Elsevier's
#: "Findings:". Read by the closed list alone, a Background ran on past JAMA's labels into
#: the study's own numbers (round 1 of #700). A sentence that opens on a few words and a
#: colon ends the Background too, early: its numbers after are then read as the rest of the
#: Abstract's are.
_BACKGROUND_LABEL = _label(BACKGROUND_PARTS)
_KNOWN_LABEL = _label((*BACKGROUND_PARTS, *_OTHER_PARTS))
_LABEL_REST = r"[\w'\N{RIGHT SINGLE QUOTATION MARK}-]*"
_LABEL_WORD = rf"[^\W\d_]{_LABEL_REST}"
_ANY_LABEL = re.compile(rf"{_LABEL_OPENS}[A-Z]{_LABEL_REST}"
                        rf"(?:(?:,?[ \t]+|[ \t]*&[ \t]*)(?:{_LABEL_WORD}|&)){{0,5}}"
                        r",?[*_]*[ \t]*:", re.MULTILINE)  # fmt: skip


def label_ends(text: str) -> list[tuple[int, int, bool]]:
    """Each run-in label of a part in `text`, in order, as its start, its end and whether it
    opens the Background (`_BACKGROUND_LABEL`, `_KNOWN_LABEL`, `_ANY_LABEL`)."""
    found: dict[int, tuple[int, bool]] = {}
    for pattern in (_ANY_LABEL, _KNOWN_LABEL):
        for match in pattern.finditer(text):
            found.setdefault(match.start(), (match.end(), False))
    for match in _BACKGROUND_LABEL.finditer(text):
        found[match.start()] = (match.end(), True)
    return [(start, end, opens) for start, (end, opens) in sorted(found.items())]


@dataclass(frozen=True)
class Aside:
    """Where a line stands under a section that reports nothing whose numbers a paper may yet
    report (`_may_report`): the titles of the headings over it that report nothing, outermost
    first, as the paper prints them, each of which `--results` would have to name for the
    line to be searched."""

    titles: tuple[str, ...]

    @property
    def introduction(self) -> bool:
        """Whether it is the Introduction or its material, where a background figure is
        given with its source."""
        return any(names_introduction(title) or names_introduction_material(title)
                   for title in self.titles)  # fmt: skip


class InBackground(str):
    """The Abstract's title, as `placed` gives it for a line in the Abstract's Background,
    under a heading of `BACKGROUND_PARTS` there: a line of the Abstract to every reader."""


@dataclass(frozen=True)
class Answers:
    """The author's answers to the section's questions, as `audit` is given them: that the
    paper has no Abstract (`--no-abstract`), that it reports no results (`--no-results`),
    and the titles of the headings that hold its results (`--results`), each a Results
    heading to this section alone."""

    no_abstract: bool = False
    no_results: bool = False
    results: tuple[str, ...] = ()


def given_title(title: str) -> str:
    """A title `--results` gives, or a heading's, as `section_names` compares a whole name:
    case aside, a number and marks before it aside, a stop or a colon after it aside."""
    return _whole(title)


@dataclass(frozen=True)
class Piece:
    """One file as the section reads it: its text as masked, at the offsets of the text its
    numbers were read in; where each line stands (`place`, None for a file with no
    headings); the lines in a table; whether its document has an Abstract and a Results
    heading; and the numbers the classifier left unexplained in it. `lined` is the masked
    text with every line break of the file where the file has it, which its lines are
    counted in; "" where `hidden` has them all. `hidden` is what is read: a comment's line
    breaks are no line breaks to its sentences, and a blank line in one ended a sentence
    that goes on past it."""

    path: Path
    hidden: str
    place: Callable[[int], object] | None
    tables: frozenset[int]
    abstract: bool
    results: bool
    atoms: tuple[Atom, ...]
    lined: str = ""
    #: The file's text as its atoms are reported from, at the offsets of `hidden`: where a
    #: power's exponent is read (`powers`), whose braces a LaTeX file's `hidden` blanks.
    text: str = ""

    def line(self, at: int) -> int:
        """The line of the file offset `at` stands on."""
        return (self.lined or self.hidden).count("\n", 0, at) + 1


@dataclass
class AbstractRead:
    compared: bool = False
    #: Why nothing was compared, where nothing was.
    why_not: str = ""
    numbers: int = 0
    matched: int = 0
    #: Each number matched only as a rounding, and each not found where the paper reports,
    #: as the audit's `Candidate`; each conflict as its `Disagreement`.
    rounded: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
    #: Each number found as printed, as its `Candidate`: `matched` of them.
    found: list = field(default_factory=list)
    #: Each percentage written beside both its counts that they give, and each that they do
    #: not, as its `Candidate`; and for each of the shares they do not give, wherever its
    #: percentage was read, the arithmetic finding, as the audit's `Disagreement`.
    from_counts: list = field(default_factory=list)
    off_counts: list = field(default_factory=list)
    arithmetic: list = field(default_factory=list)
    #: How many shares were read beside their counts.
    shares: int = 0
    conflicts: list = field(default_factory=list)
    #: What a match is worth against what the paper reports, roundings counted in.
    discrimination: object = None
    #: The question asked of the author, by its code (`ASKED_NO_ABSTRACT`,
    #: `ASKED_NO_RESULTS`), "" where none is; and each note on the answers given, as its code
    #: and what it says.
    question: str = ""
    answered: list = field(default_factory=list)
    #: The questions asked of single numbers, none of which is `not_found`: each number found
    #: only in sections that report nothing (`Aside`), as its `Candidate` with where it
    #: stands there, each `(path, titles, line)`, a section's first line, and the parts of it
    #: that stand only there where others are found ("40%" of "30-40%"), () where none is;
    #: and each of the Abstract's Background found nowhere, as its `Candidate`.
    only_in: list = field(default_factory=list)
    unsourced: list = field(default_factory=list)


def in_abstract(place: object) -> bool:
    return isinstance(place, str) and names_abstract(place)


def names_results_like(title: str) -> bool:
    """Whether a heading's whole title, numbered, marked or not, "&" read as "and", is one
    of `RESULTS_LIKE`: "Experiments", "5. Numerical results", "Experiments & Results"."""
    return " ".join(_whole(title).replace("&", " and ").split()) in RESULTS_LIKE


def _names_the_methods(title: str) -> bool:
    """Whether a heading's whole title, numbered or not ("2.", "(3)", "A.", "IV."), "&" read
    as "and", is a name the Methods go by: one of `classify.METHODS_SECTIONS`' ("Methods",
    "Materials and methods", "Design", "Study design", "Protocol", "Statistical analysis",
    "Analysis plan") or a singular `names_methods` takes whole ("Method", "Materials and
    method", `_METHOD_TITLE`)."""
    from manuscript_guard.classify import METHODS_SECTIONS

    whole = " ".join(_whole(title).replace("&", " and ").split())
    return bool(METHODS_SECTIONS.match(whole) or _METHOD_TITLE.fullmatch(whole))


def _the_methods(sections: list[Section]) -> set[int]:
    """The headings that are the Methods to `_results_by_another_name`: a name the Methods
    go by (`_names_the_methods`) over no Abstract and no heading whose whole title is
    "Introduction", which a paper's title written as a heading over the paper is, "Methods
    and algorithms for robust estimation" (round 3 of #672). A "Limitations", a "Background"
    or a "Discussion of assumptions" under the Methods leaves them the Methods."""
    found = set()
    for index, section in enumerate(sections):
        if not _names_the_methods(section.title):
            continue
        below = []
        for later in sections[index + 1 :]:
            if later.level <= section.level:
                break
            below.append(later.title)
        if not any(names_abstract(t) or re.fullmatch(r"introduction\W*", plain(t), re.I)
                   for t in below):  # fmt: skip
            found.add(id(section))
    return found


def _says_results(title: str) -> bool:
    return "results" in _whole(title)


def _results_by_another_name(sections: list[Section],
                             searched: Callable[[int], object]) -> bool:  # fmt: skip
    """Whether a heading of `RESULTS_LIKE` stands where the section searches, and, where its
    name does not say "results" (`_says_results`), under no Methods (`_the_methods`):
    "### Evaluation" under "## Methods" tells how a model was judged, "### Simulation
    results" there reports, and "Comparison with existing methods" is no Methods (rounds 1
    to 3 of #672)."""
    from manuscript_guard.gates.reported import REPORTED

    methods = _the_methods(sections)
    chain: list[Section] = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        under = any(id(one) in methods for one in chain)
        if (names_results_like(section.title) and searched(section.line) is REPORTED
                and (_says_results(section.title) or not under)):  # fmt: skip
            return True
        chain.append(section)
    return False


def placed(sections: list[Section], notes: frozenset[int] = frozenset(),
           lists: tuple[tuple[int, int], ...] = (), named: tuple[str, ...] = ()
           ) -> tuple[Callable[[int], object], bool, bool,
                      tuple[tuple[str, str], ...]]:  # fmt: skip
    """Where each line of one document stands, given its headings, the lines of its notes
    and its reference lists as the audit cut them, and whether it has an Abstract and a
    Results heading outside it. Each file is placed alone, unlike G8, which carries the
    headings of a paper's files from one into the next: a file with no Abstract is a
    supplement, reported whole, and so is a Discussion written in a file of its own (round 2
    of #472, DESIGN.md, "Known gaps").

    A line is REPORTED, searched for the Abstract's numbers, as G8 reads the Methods and the
    Results (`gates.reported.Walk`), and under any other section too that reports
    (`_searched`): a paper that reports a number under "Participants", "Study design" or an
    appendix had it said not found (Basile, 2026-11-11, after 52 real preprints). So is a
    line between a reference list's end and the next heading (`_past_the_lists`).

    The Results are a heading G8 reads as them where it reports, or one whose whole title is
    the Results by another name (`RESULTS_LIKE`) standing where the section searches, not in
    the Abstract nor under a Discussion (Basile, 2026-11-13), unless it stands under the
    Methods and its name does not say "results" (`_results_by_another_name`).

    `named` are the titles `--results` gives (`Answers.results`): a heading whose whole title
    is one (`given_title`) is a Results heading to this section alone, searched whatever its
    name, where it stands where the section searches, not in the Abstract nor on the title
    page nor under a section that reports nothing (Basile, 2026-11-16, decision 27); one that
    is itself such a section, a Discussion, is read as given, and said (round 1 of #697).
    Last comes each title of `named` that a heading of the document has, as `given_title`
    gives it, with how its headings were read (`NAMED_STATES`): one as the Results, one as
    the Results that is a section reporting nothing otherwise, or none."""
    from manuscript_guard.gates.reported import REPORTED, Walk

    walk = Walk()
    place = walk.placing(sections)
    given = frozenset(given_title(title) for title in named)
    searched = _searched(sections, place, walk, notes, given)
    abstract = any(in_abstract(place(s.line)) for s in sections if names_abstract(s.title))
    states: dict[str, str] = {}
    unanswered = _searched(sections, place, walk, notes)
    for section in sections:
        title = given_title(section.title)
        if title not in given:
            continue
        # Said where the comparison would not have searched it unanswered: a Discussion
        # under the Results is searched already (round 2 of #697).
        state = (NOT_READ if searched(section.line) is not REPORTED else READ
                 if unanswered(section.line) is REPORTED else READ_REPORTING_NOTHING)
        states[title] = max(states.get(title, NOT_READ), state, key=NAMED_STATES.index)
    results = (any(place(s.line) is REPORTED for s in sections if names_results(s.title))
               or _results_by_another_name(sections, searched)
               or any(state != NOT_READ for state in states.values()))  # fmt: skip
    return (_set_aside(_past_the_lists(searched, sections, lists, notes), sections, walk,
                       notes | _listed(lists), given),
            abstract, results, tuple(sorted(states.items())))  # fmt: skip


def _listed(lists: tuple[tuple[int, int], ...]) -> frozenset[int]:
    """The lines, from 1, of the reference lists the audit cut, `[start, end)` from 0: a list
    resumed after a caption among them, which stands under no heading of its own."""
    return frozenset(line for start, end in lists for line in range(start + 1, end + 1))


def _may_report(section: Section) -> bool:
    """Whether a heading that reports nothing names a section whose numbers a paper may yet
    report, its own or as background: the Introduction and its material, the Discussion, a
    "Limitations" and a conclusion (Basile, 2026-11-16, decision 27). Not the statements,
    the reference list, the keywords, a summary of the paper or the Abstract."""
    title = section.title
    if (section.is_references or names_statement(title) or names_keywords(title)
            or names_paper_summary(title) or names_abstract(title)):  # fmt: skip
        return False
    return (names_introduction(title) or names_introduction_material(title)
            or (names_discussion(title) and not names_results(title))
            or names_conclusion(title) or _whole(title) in _LIMITATIONS)  # fmt: skip


def _set_aside(where: Callable[[int], object], sections: list[Section], walk,
               notes: frozenset[int],
               given: frozenset[str]) -> Callable[[int], object]:  # fmt: skip
    """`where`, with an `Aside` for each line placed neither in the Abstract nor where the
    paper reports that stands under headings, the paper's title apart (`_over_the_paper`),
    each of which that reports nothing (`_reports_nothing`) is one whose numbers a paper may
    yet report (`_may_report`): not a note's line, nor a reference list's (`notes` holds
    both), nor a heading's own, nor one of the title page. A line of the Abstract under a
    heading of `BACKGROUND_PARTS` there is `InBackground`, its Abstract's title still."""
    from manuscript_guard.gates.reported import REPORTED

    titles = _over_the_paper(sections)
    opened = _title_page_ends(sections)
    heads = frozenset(section.line for section in sections)
    starts: list[int] = [0]
    asides: list[Aside | None] = [None]
    background: list[bool] = [False]
    chain: list[Section] = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        chain.append(section)
        starts.append(section.line)
        named = [one for one in chain if id(one) not in titles]
        # Every heading over it that reports nothing, one `--results` gave already among them:
        # each is to be named for the line to be searched (round 1 of #700).
        nothing = [one for one in named if _reports_nothing(one, walk)]
        unanswered = any(given_title(one.title) not in given for one in nothing)
        asides.append(Aside(tuple(" ".join(plain_title(one.title).split()) for one in nothing))
                      if unanswered and all(_may_report(one) for one in nothing) else None)
        opens = next((at for at, one in enumerate(chain) if names_abstract(one.title)), None)
        background.append(opens is not None and any(
            _whole(one.title) in BACKGROUND_PARTS for one in chain[opens + 1 :]))  # fmt: skip

    def at(line: int) -> object:
        found = where(line)
        if found is REPORTED:
            return found
        index = bisect_right(starts, line) - 1
        if in_abstract(found):
            return InBackground(found) if background[index] else found
        if line in notes or line in heads or (opened is not None and line < opened):
            return found
        return asides[index] or found

    return at


def plain_title(title: str) -> str:
    """A heading's title as the paper prints it, its number kept: what `--results` is given
    for it, which compares it whole (`given_title`)."""
    from manuscript_guard.classify import _unmarked

    return _unmarked(title).strip()


#: How the headings `--results` names were read, from least to most to say: none as the
#: Results, one as them, and one as them that is a section reporting nothing otherwise.
NOT_READ, READ, READ_REPORTING_NOTHING = "not read", "read", "read, reporting nothing"
NAMED_STATES = (NOT_READ, READ, READ_REPORTING_NOTHING)


def merged(states: list[tuple[str, str]]) -> dict[str, str]:
    """Each title's state over several files' (`placed`): the one with most to say."""
    found: dict[str, str] = {}
    for title, state in states:
        found[title] = max(found.get(title, NOT_READ), state, key=NAMED_STATES.index)
    return found


def _past_the_lists(where: Callable[[int], object], sections: list[Section],
                    lists: tuple[tuple[int, int], ...],
                    notes: frozenset[int]) -> Callable[[int], object]:  # fmt: skip
    """`where`, with REPORTED for each line between the end of a reference list, as 0-based
    lines `[start, end)`, and the next of `sections`' headings or the end of the file. A list
    the audit cuts (`audit.bibliography_spans`) ends before its next heading: once it holds
    an entry, at a display, a table or a caption; in Markdown at a thematic break or a
    heading pandoc prints as text, entry or no entry; in a PDF at a caption or a back-matter
    title, and in a .docx under no heading at a typed caption, a table or a back-matter
    title. The lines after it still stood under "References", which reports nothing, so a
    table typed as text, a caption, a legend or an appendix there was never searched, as a
    Word paper's tables always were (pdf-psych-B3 of the real-paper corpus, its Abstract's
    "33.2%" in the table after its references; Basile, 2026-11-15).
    Never a note's line, nor one of the title page, nor a line of `lists`: the audit's cut,
    blanked before the comparison reads it, and a list resumed after it at an entry by its
    shape or its next number (`audit.resumed_lists`; rounds 1 and 2 of #692)."""
    from manuscript_guard.gates.reported import REPORTED

    heads = sorted(section.line for section in sections)
    stretches = []
    for _start, end in lists:
        first = end + 1
        after = next((line for line in heads if line >= first), None)
        if after is None or after > first:
            stretches.append((first, after))
    if not stretches:
        return where
    opened = _title_page_ends(sections)

    def at(line: int) -> object:
        found = where(line)
        if (found is REPORTED or in_abstract(found) or line in notes
                or (opened is not None and line < opened)):  # fmt: skip
            return found
        listed = any(start < line <= end for start, end in lists)
        past = any(first <= line and (after is None or line < after)
                   for first, after in stretches)  # fmt: skip
        return REPORTED if past and not listed else found

    return at


def _reports_nothing(section: Section, walk) -> bool:
    """Whether a heading names a part of the paper whose numbers are not the paper's own
    report, where an Abstract's number is not looked for: the Introduction, and the
    sections that hold its material under another name, "Related work", "Literature
    review" (`names_introduction_material`); the Discussion, not "Results and discussion",
    which reports; a conclusion; a summary of the paper, "Author summary", "Highlights", an
    Abstract in another language (`names_paper_summary`); and what G8 reads as reporting
    nothing or as summarising (`Walk.elsewhere`, `Walk.summaries`): the abstract, a
    "Limitations" or an "Interpretation" of its own, the statements and the reference list
    (round 1 of #641: a number in a footnote under "References" or in a "Funding" was found,
    and so was one an "Author summary" repeats); and the keywords, under which a Word paper's
    Introduction with no heading of its own stands where a run-in "Keywords:" ends its
    Abstract (`text.docx_abstract`; Basile, 2026-11-15)."""
    title = section.title
    return (id(section) in walk.elsewhere or id(section) in walk.summaries
            or names_introduction(title) or names_introduction_material(title)
            or names_keywords(title)
            or names_conclusion(title) or names_paper_summary(title)
            or (names_discussion(title) and not names_results(title)))  # fmt: skip


#: The Introduction by its whole title, which a heading over it is the paper's title for:
#: not "Background characteristics" under "Participants" (round 2 of #641).
_OPENING = re.compile(r"(?:introduction|background|rationale)\W*", re.IGNORECASE)


def _title_page_ends(sections: list[Section]) -> int | None:
    """The line the title page ends on, the first heading that names the Abstract."""
    return next((s.line for s in sections if names_abstract(s.title)), None)


def _over_the_paper(sections: list[Section]) -> set[int]:
    """The headings that are the paper's title written as a heading over it: those over the
    Abstract or the Introduction. Not one over the Methods alone, as G8 reads it too: the
    text under "Study design" before its "Statistical methods" reports (round 1 of #641)."""
    found = set()
    for index, section in enumerate(sections):
        for later in sections[index + 1 :]:
            if later.level <= section.level:
                break
            if names_abstract(later.title) or _OPENING.fullmatch(plain(later.title)):
                found.add(id(section))
                break
    return found


def _searched(sections: list[Section], place: Callable[[int], object], walk,
              notes: frozenset[int],
              given: frozenset[str] = frozenset()) -> Callable[[int], object]:  # fmt: skip
    """`place`, with REPORTED for each line it places in neither the Abstract nor where the
    paper reports that stands under a heading naming a section, the paper's title apart
    (`_over_the_paper`), none of which reports nothing (`_reports_nothing`): a heading whose
    whole title the author gave as the Results' (`given`, `given_title`) never does. Never a
    note's line, which a .docx's notes after its body and a Markdown footnote's are,
    whatever stands over it: citations are written there. Nor a line of the title page,
    above the first heading that names the Abstract."""
    from manuscript_guard.gates.reported import REPORTED

    titles = _over_the_paper(sections)
    opened = _title_page_ends(sections)
    starts, searched = [0], [False]
    chain: list[Section] = []
    for section in sections:
        while chain and chain[-1].level >= section.level:
            chain.pop()
        chain.append(section)
        named = [one for one in chain if id(one) not in titles]
        starts.append(section.line)
        searched.append(bool(named) and not any(
            _reports_nothing(one, walk) and given_title(one.title) not in given
            for one in named))  # fmt: skip

    def where(line: int) -> object:
        if line in notes:
            return None
        found = place(line)
        if found is REPORTED or in_abstract(found):
            return found
        if opened is not None and line < opened:
            return found
        return REPORTED if searched[bisect_right(starts, line) - 1] else found

    return where


def place_lines(view, place: Callable[[int], object]) -> dict[str, dict[int, object]]:
    """Each line of a LaTeX document's files, by the file's path, placed as the printed view's
    line it was printed from is (`Printed.place_line`). Where several lines of the view that
    print something share one `.tex` line, a place in the Abstract or where the paper reports
    is kept over one that is neither: the untitled heading that closes an abstract stands on
    `\\end{abstract}`'s line, and the Abstract's last sentence before it was placed nowhere,
    as was Results text before a `\\section` on its line (round 1 of #472)."""
    from manuscript_guard.gates.reported import REPORTED

    lines = view.text.split("\n")
    found: dict[str, dict[int, object]] = {}
    for number, printed in enumerate(lines, 1):
        if not printed.replace(NUL, " ").strip():
            continue
        where = view.place_line(number)
        if where is None:
            continue
        mine = found.setdefault(where[0].path, {})
        kept = mine.get(where[1])
        if where[1] in mine and (kept is REPORTED or in_abstract(kept)):
            continue
        mine[where[1]] = place(number)
    return found


# ----------------------------------------------------------------------- printed numbers


def _decimal(printed: str) -> tuple[Decimal, int] | None:
    """A printed number's value and its places, or None where it is no number."""
    cleaned = (printed.replace(",", "").replace(" ", "").replace("\xa0", "")
               .replace("\N{MINUS SIGN}", "-").rstrip("%"))  # fmt: skip
    cleaned = re.sub(r"^\N{EN DASH}(?=\d)", "-", cleaned)
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or not value.is_finite():
        return None
    return value, max(0, -exponent)


def _box(value: Decimal, places: int) -> tuple[Decimal, Decimal]:
    """The values a number printed to `places` stands for, as a half-open range."""
    half = Decimal(5).scaleb(-(places + 1))
    return value - half, value + half


def agree(one: str, other: str) -> bool:
    """Whether one value could be printed as both numbers, each to its own places."""
    first, second = _decimal(one), _decimal(other)
    if first is None or second is None:
        return one == other
    low, high = _box(*first)
    other_low, other_high = _box(*second)
    return low < other_high and other_low < high


def coarser(printed: str) -> set[tuple[str, int]]:
    """Each number, normalised, with its places, that `printed` rounds to at fewer places
    than its own: "53.3" to 53, "0.725" to 0.72, 0.73, 0.7 and 1. A number at the edge of
    its rounding agrees with two."""
    from manuscript_guard.audit import normalise_number

    read = _decimal(printed)
    if read is None:
        return set()
    value, places = read
    low, high = _box(value, places)
    found = set()
    for fewer in range(places):
        unit = Decimal(1).scaleb(-fewer)
        half = unit / 2
        for k in range(floor((low - half) / unit) + 1, ceil((high + half) / unit)):
            found.add((normalise_number(str((Decimal(k) * unit).quantize(unit))), fewer))
    return found


#: The shapes of an atom in which a space was left out around a number, which the section
#: reads the numbers of (G14's `notation-space-missing` reports the space): a number typed
#: against a word, "+0.41points", "10hours"; a word against a signed number, "to+0.77"; and
#: pieces closed up by round brackets, colons or semicolons, each a number, a range, a
#: level named "95%CI", one of these shapes or a label of letters alone, each piece's
#: numbers kept, "CI):+0.05", "45%(95%CI:40-50%"; one piece of any other shape, "CD4:350",
#: and the atom is read whole (round 2 of #613). Only these: an atom with letters in it is
#: otherwise read whole, so that no name or address matches on a digit it holds
#: (`audit._COMPOUND`). Found on the author's Abstract, whose numbers were all "not found"
#: for want of a space (2026-11-10).
_AGAINST_A_WORD = re.compile(r"(?P<number>[-+\N{MINUS SIGN}]?\d[\d.,]*%?)(?P<word>[a-z]{3,})")
_AFTER_A_WORD = re.compile(r"[a-z]{2,}(?P<number>[+\N{MINUS SIGN}]\d[\d.,]*%?)")
_CLOSED_UP = re.compile(r"[():;]+")
#: A number alone, and a level typed against its estimate's name, "95%CI".
_PLAIN = re.compile(r"[-+\N{MINUS SIGN}]?\d[\d.,]*%?")
_LEVEL_NAMED = re.compile(r"(?P<number>\d[\d.,]*%?)[A-Z]{1,3}")
#: The words a rank is typed against, "2ndyear", "21stcentury": an ordinal with its own
#: suffix before one of them is a rank and gives no number. Any other word after the
#: suffix's letters is a word: "312students", "10therapists" (round 1 of #613).
_RANKED = frozenset((
    "year", "line", "grade", "generation", "trimester", "semester", "quartile", "tertile",
    "quintile", "decile", "dose", "wave", "round", "visit", "week", "day", "month", "cycle",
    "edition", "author", "place", "time", "phase", "century", "decade", "order", "degree",
    "percentile", "centile",
))  # fmt: skip


def _ordinal(number: str, word: str) -> bool:
    """Whether a whole number and the word typed against it are a rank and its word: the
    number's own suffix, "st" after a 1, "nd" after a 2, "rd" after a 3, "th" after the rest
    and after 11, 12 and 13, then a word of `_RANKED`."""
    if not number.isdigit():
        return False
    value = int(number)
    suffix = "th" if value % 100 in (11, 12, 13) else {1: "st", 2: "nd", 3: "rd"}.get(
        value % 10, "th")  # fmt: skip
    rest = word[len(suffix) :]
    return word.startswith(suffix) and (rest in _RANKED or rest[:-1] in _RANKED)


def _run_on(stripped: str) -> list[str] | None:
    """The numbers of an atom a space was left out of, as printed; None for an atom of any
    other shape, which is read whole."""
    from manuscript_guard.audit import _COMPOUND, _NUMBER

    against = _AGAINST_A_WORD.fullmatch(stripped)
    if against is not None:
        return [] if _ordinal(against["number"], against["word"]) else [against["number"]]
    after = _AFTER_A_WORD.fullmatch(stripped)
    if after is not None:
        return [after["number"]]
    if _CLOSED_UP.search(stripped) is None:
        return None
    parts: list[str] = []
    for piece in filter(None, _CLOSED_UP.split(stripped)):
        level = _LEVEL_NAMED.fullmatch(piece)
        inner = None if piece.isalpha() or level else _run_on(piece)
        if piece.isalpha():
            continue  # a label: "CI", "students"
        if level is not None:
            parts.append(level["number"])
        elif inner is not None:
            parts += inner
        elif _PLAIN.fullmatch(piece):
            parts.append(piece)
        elif _COMPOUND.match(piece.lstrip("+")):
            parts += [found.group(0) for found in _NUMBER.finditer(piece)]
        else:
            return None  # a piece of any other shape: the atom is read whole
    return parts or None


def printed_parts(text: str) -> list[str]:
    """The numbers an atom carries, as printed: `audit.parts_of` without normalising them,
    and the numbers of an atom a space was left out of (`_run_on`); none for a rank typed
    against its word."""
    from manuscript_guard.audit import _COMPOUND, _LABELLED, _NUMBER

    stripped = _LABELLED.sub("", text.strip().strip("()[]"), count=1)
    run_on = _run_on(stripped)
    if run_on is not None:
        return run_on
    if not _COMPOUND.match(stripped):
        return [stripped]
    return [found.group(0) for found in _NUMBER.finditer(stripped)] or [stripped]


def _numbers(text: str) -> list[str]:
    from manuscript_guard.audit import _NUMBER, _OPAQUE

    return [found.group(0) for found in _NUMBER.finditer(_OPAQUE.sub(" ", text.replace(NUL, " ")))]


#: What a word of the reported text is stripped of at its ends before an Abstract's part is
#: looked for among them: the stops and brackets typed against a word, "chr15." or "(v8)";
#: a Markdown paper's emphasis, which the masked text keeps, "*rs75015950*"; and quotes,
#: straight and curly (round 1 of #624).
_WORD_EDGES = ".,;:()[]*_\"'\N{LEFT DOUBLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}" \
    "\N{LEFT SINGLE QUOTATION MARK}\N{RIGHT SINGLE QUOTATION MARK}"
#: A possessive after a word, "v8's" or "v8\N{RIGHT SINGLE QUOTATION MARK}s".
_POSSESSIVE = re.compile("['\N{RIGHT SINGLE QUOTATION MARK}]s$")


def _words(text: str) -> set[str]:
    """Each word of the reported text, as split at spaces and again at its colons, stripped
    of `_WORD_EDGES` and of a possessive: where an Abstract's part that holds letters, which
    `printed_parts` keeps whole ("v8", "rs75015950", "ieu-a-1185", "chr15:1234"), is looked
    for, since `_numbers` holds the bare numbers alone. A chromosome before its position,
    "chr15:1234", gives "chr15" as well as the whole."""
    found = set()
    for token in text.replace(NUL, " ").split():
        for word in (token, *token.split(":")):
            word = word.strip(_WORD_EDGES)
            found.add(_POSSESSIVE.sub("", word).strip(_WORD_EDGES))
    return found - {""}


# -------------------------------------------------------------------------------- powers

#: A number in scientific notation as TeX sets one, and a power of a number alone: an
#: optional sign, a mantissa and a times sign, `\times`, `\cdot`, "×" or "·" (spaced or not,
#: any run of the gaps of `_GAP` around it), then a number, a caret and a braced exponent,
#: `10^{-2}`, `10^{\,8}`, `2^{10}`, `10^{\alpha}`, or a single digit, `10^8`, `10^8.` at a
#: sentence's
#: end; or pandoc's superscript, `10^-2^`. A bare power is the same number with a mantissa
#: of 1 and keeps its sign, `-10^{8}`. A power after a times sign with no mantissa before
#: it, a column header's "(×10^8 cm^-3)", is a scale (`scale`), no number at all. Not
#: `10^-2` nor `10^82` in maths, which TeX sets as 10 to the minus and 10 to the 8 before a
#: 2: these are read as they were. The first number stands alone, after a sign, a times sign
#: or a TeX command (`_base_alone`); a power after a times sign after anything else,
#: `k_2\times10^{3}`, is a scale. A sign is one where `audit._NUMBER` reads one. A mantissa
#: is its digits grouped as `audit._NUMBER` groups them, by commas, a narrow or a no-break
#: space, and in TeX by `\,` or a decimal comma `{,}` too, with a digit after each separator,
#: and a point and its digits after them (`_MANTISSA`).
_TIMES = r"(?:\\times(?![A-Za-z])|\\cdot(?![A-Za-z])|\N{MULTIPLICATION SIGN}|\N{MIDDLE DOT})"
#: What may stand between a mantissa, its times sign and its power: a space, a tab, a
#: no-break, a thin or a narrow no-break space, TeX's tie `~` and its spaces `\,`, `\;`, `\:`,
#: `\!` and `\ `, in any run and mix (round 2 of #696); the tie only where a `~` is one
#: (`ties`); and a line break with no blank line after it, a space in TeX and in Markdown.
_GAP = (r"(?:[ \t~\N{NO-BREAK SPACE}\N{THIN SPACE}\N{NARROW NO-BREAK SPACE}]|\\[,;:! ]"
        r"|\n(?![ \t]*(?:\n|$)))*")
#: A mantissa: digits grouped as `audit._NUMBER` groups them and as TeX does, a digit after
#: each separator.
_MANTISSA = (r"\d(?:(?:[,\N{NARROW NO-BREAK SPACE}\N{NO-BREAK SPACE}]|\{,\}|\\,)?\d)*"
             r"(?:\.\d+)?|(?<![\w.])\.\d+")
#: The signs of a minus, the hyphen last, where a class of characters reads it as itself.
_DASHES = "\N{MINUS SIGN}\N{EN DASH}-"


@cache
def _power_pattern() -> re.Pattern[str]:
    from manuscript_guard.audit import _SIGN_MAY_FOLLOW

    sign = rf"(?:(?<![^{_SIGN_MAY_FOLLOW}])[-–]|−)"  # an en dash, a minus sign
    return re.compile(
        rf"(?:(?P<sign>{sign})?(?<![\d.])(?P<mantissa>{_MANTISSA}){_GAP}(?P<times>{_TIMES})"
        rf"{_GAP}"
        rf"|(?P<scale>{_TIMES}){_GAP}|(?P<bare>{sign}))?"
        r"(?<![\d.])(?P<base>\d+(?:\.\d+)?)[ \t]*\^(?:"
        rf"(?P<raised>[+{_DASHES}]?\d+(?:\.\d+)?)\^"
        r"|[ \t]*\{(?P<group>(?:[^{}\n]|\{[^{}\n]*\})*)\}"
        r"|[ \t]*(?P<digit>\d)(?!\d|\.\d))"
    )


#: What a braced exponent is read without: TeX's spaces and the commands that print one.
_EXPONENT_SPACE = re.compile(r"\\[,;:! ]|~|\s+")
_EXPONENT_NUMBER = re.compile(rf"[+{_DASHES}]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Power:
    """A number in scientific notation or a power where a file prints one, from `start` to
    `end` of its text: its sign, "-" or "", its mantissa, "1" for a bare power, its base and
    its exponent, each read as a number where it is one (`normalise_number`); or a scale, no
    number. What it is looked for as is all four (`key`): `10^{-2}`, `10^{-2.0}`,
    `1\\times10^{-2}` and `10^-2^` are one number, `5\\times10^{-2}` and `-10^{-2}` others."""

    start: int
    end: int
    sign: str
    mantissa: str
    base: str
    exponent: str
    scale: bool = False

    @property
    def key(self) -> str:
        return f"{self.sign}{self.mantissa}\N{MULTIPLICATION SIGN}{self.base}^{self.exponent}"


def _mantissa(printed: str) -> str:
    """A mantissa as it is looked for: its groupings taken out, `{,}` read as a comma, and
    read as a number (`normalise_number`) unless a comma is left in it, which may be a
    decimal comma or a thousands one: "1{,}5" stays "1,5", never 15 nor 1.5."""
    from manuscript_guard.audit import normalise_number

    plain = printed.replace("{,}", ",").replace("\\,", "")
    plain = plain.replace("\N{NARROW NO-BREAK SPACE}", "").replace("\N{NO-BREAK SPACE}", "")
    return plain if "," in plain else normalise_number(plain)


def _base_alone(text: str, at: int) -> bool:
    """Whether a number at `at` stands alone, after no letter, digit, point or underscore,
    or after a TeX command's name, `\\times10^{8}`."""
    letters = at
    while letters > 0 and text[letters - 1].isascii() and text[letters - 1].isalpha():
        letters -= 1
    if letters < at:
        return letters > 0 and text[letters - 1] == "\\"
    return at == 0 or not (text[at - 1].isalnum() or text[at - 1] in "._")


#: What a `~` is read as where it is no tie: no gap, as no character of `_GAP` is.
_NO_TIE = "\x01"


def ties(path: Path, text: str) -> tuple[tuple[int, int], ...] | None:
    """Where a `~` in a file's text is TeX's tie, a gap around a times sign (`_GAP`): all of
    a LaTeX file's (None); in Markdown, only inside maths as pandoc finds it
    (`text.markdown_maths`), since in its text a `~` marks pandoc's subscript, `CO~2~`, and
    so it does in `\\(...\\)`, which pandoc's Markdown reads as no maths; in a .docx or a
    PDF nowhere, where it is a tilde (Basile, after the checks of b95b6a89f and 191d0e7c2
    in #696)."""
    suffix = path.suffix.lower()
    if suffix == ".tex":
        return None
    return tuple(markdown_maths(text)) if suffix in (".md", ".markdown", ".txt") else ()


def _untied(text: str, tied: tuple[tuple[int, int], ...] | None) -> str:
    """`text` with each `~` outside `tied` made `_NO_TIE`, at the same offsets."""
    if tied is None or "~" not in text:
        return text
    out, at = [], 0
    for start, end in tied:
        out += [text[at:start].replace("~", _NO_TIE), text[start:end]]
        at = end
    out.append(text[at:].replace("~", _NO_TIE))
    return "".join(out)


def powers(text: str, read: str,
           tied: tuple[tuple[int, int], ...] | None = None) -> list[Power]:  # fmt: skip
    """Each number in scientific notation, power and scale `text` prints where `read`, its
    masked text at the same offsets with what is not read blanked, keeps every digit and the
    caret: one in a comment, in code a mask hides or on a line not read is none. A `~` is a
    gap only within `tied`, everywhere where it is None (`ties`)."""
    from manuscript_guard.audit import normalise_number

    if len(text) != len(read):
        return []
    found = []
    for match in _power_pattern().finditer(_untied(text, tied)):
        start, end = match.span()
        scale = match["scale"] is not None
        if match["mantissa"] is not None and match["sign"] is None and not _base_alone(
                text, match.start("mantissa")):  # fmt: skip
            # `k_2\times10^{3}`: no mantissa, so a scale, read from its times sign.
            start, scale = match.start("times"), True
        led = match["sign"] is not None or match["bare"] is not None or scale
        kept = all(read[at] == text[at] for at in range(start, end)
                   if text[at].isdigit() or text[at] == "^")  # fmt: skip
        if not (kept and (led or _base_alone(text, match.start("base")))):
            continue
        # Each part from `text` itself, never from the copy `_untied` made: no `_NO_TIE` in it.
        name = next(one for one in ("raised", "digit", "group") if match[one] is not None)
        exponent = _EXPONENT_SPACE.sub("", text[match.start(name) : match.end(name)])
        if not exponent:
            continue
        if _EXPONENT_NUMBER.fullmatch(exponent):
            exponent = normalise_number(exponent)
        sign = "-" if match["sign"] is not None or match["bare"] is not None else ""
        printed = text[match.start("mantissa") : match.end("mantissa")]
        mantissa = "1" if scale or match["mantissa"] is None else _mantissa(printed)
        base = normalise_number(text[match.start("base") : match.end("base")])
        found.append(Power(start, end, sign, mantissa, base, exponent, scale))
    return found


@dataclass(frozen=True)
class Looked:
    """What the section looks for in an Abstract: an atom, or the atoms of one power or more
    read as one (`_looked_for`), as an atom spanning them; its parts as printed; and which of
    them are powers, looked for among the powers where the paper reports alone."""

    atom: Atom
    parts: tuple[str, ...]
    powered: frozenset[str] = frozenset()


def _looked_for(piece: Piece, abstract: str, lines: set[int]) -> list[Looked]:
    """Each thing one file's Abstract gives to be looked for, in order: an atom of its lines,
    with its parts (`printed_parts`), or the atoms that overlap a power its text prints
    (`powers`), with any other power they overlap, read as one: the powers, and the numbers
    of those atoms outside them as the paper's reported text reads them (`_numbers`). Read
    as atoms, `10^{-2}` in LaTeX, whose braces are blanked, was "10^" and "-2", a number the
    paper does not hold and one it may (tex-astro-ga-B1 of the real-paper corpus); and
    `10^8` was looked for as printed among numbers no power is one of."""
    atoms = [atom for atom in piece.atoms if atom.line in lines]
    groups: list[tuple[list[int], list[Power]]] = []
    tied = ties(piece.path, piece.text)
    for power in powers(piece.text, abstract, tied) if piece.text else ():
        over = [at for at, atom in enumerate(atoms)
                if atom.start < power.end and power.start < atom.end]  # fmt: skip
        if not over:
            continue
        if groups and groups[-1][0][-1] >= over[0]:
            held, read = groups[-1]
            groups[-1] = (sorted({*held, *over}), [*read, power])
        else:
            groups.append((over, [power]))
    opened = {group[0][0]: group for group in groups}
    inside = {at for group in groups for at in group[0]}
    found = []
    for at, atom in enumerate(atoms):
        if at in opened:
            held, read = opened[at]
            found.append(_joined([atoms[one] for one in held], read, piece.text))
        elif at not in inside:
            found.append(Looked(atom, tuple(printed_parts(atom.text))))
    return found


def _joined(atoms: list[Atom], read: list[Power], text: str) -> Looked:
    """Atoms and the powers they overlap, read as one: the powers, then the numbers of the
    atoms outside every power as the paper's reported text reads them, named from the first
    of them to the last as printed. A scale is no number: atoms that hold nothing else give
    nothing to look for, and a number beside one is named alone, "0.2" of a Markdown atom
    "0.2)\\times10^{-2}" (round 2 of #696)."""
    from manuscript_guard.audit import _NUMBER, _OPAQUE

    first = atoms[0]
    named = [(power.start, power.end) for power in read if not power.scale]
    alone = []
    for atom in atoms:
        blank = "".join(" " if any(p.start <= at < p.end for p in read) else text[at]
                        for at in range(atom.start, atom.end))  # fmt: skip
        blank = _OPAQUE.sub(lambda found: " " * len(found.group(0)), blank.replace(NUL, " "))
        for found in _NUMBER.finditer(blank):
            alone.append(found.group(0))
            named.append((atom.start + found.start(), atom.start + found.end()))
    keys = tuple(power.key for power in read if not power.scale)
    start = min((at for at, _end in named), default=first.start)
    end = max((at for _start, at in named), default=first.end)
    atom = replace(first, text=text[start:end], start=start, end=end,
                   col=start - first.line_start + 1)  # fmt: skip
    return Looked(atom, (*keys, *alone), frozenset(keys))


# ------------------------------------------------------------------------------- reading


def _kept(hidden: str, keep: Callable[[int], bool], lined: str = "") -> str:
    """`hidden` with each line `keep` refuses blanked to spaces, so offsets hold, and what is
    masked a space too: a LaTeX file's `95\\%` prints a NUL after its sign, across which no
    interval is read. The lines are those of `lined`, `hidden` at the same offsets with every
    line break of the file, where it is given; a break `hidden` hides, a comment's, is a
    space, as it was, so that no sentence ends at a blank line inside a comment."""
    out = []
    start = 0
    for number, line in enumerate((lined or hidden).split("\n"), 1):
        end = start + len(line)
        out.append(hidden[start:end].replace(NUL, " ") if keep(number) else " " * len(line))
        if end < len(hidden):
            out.append("\n" if hidden[end] == "\n" else " ")
        start = end + 1
    return "".join(out)


def where(piece: Piece, line: int) -> str:
    """What a line of a file is: "reported" in a table, anywhere in a file whose document has
    no Abstract, and under any section that reports (`placed`); "abstract" in the Abstract;
    else ""."""
    from manuscript_guard.gates.reported import REPORTED

    if line in piece.tables or not piece.abstract:
        return "reported"
    place = piece.place(line) if piece.place is not None else None
    if place is REPORTED:
        return "reported"
    return "abstract" if in_abstract(place) else ""


def _parts(piece: Piece) -> tuple[str, str, set[int]]:
    """A file's Abstract and what it reports, each as its text with the other lines blanked,
    and the lines of its Abstract."""
    count = (piece.lined or piece.hidden).count("\n") + 1
    kinds = {line: where(piece, line) for line in range(1, count + 1)}
    abstract = {line for line, kind in kinds.items() if kind == "abstract"}
    return (_kept(piece.hidden, abstract.__contains__, piece.lined),
            _kept(piece.hidden, lambda line: kinds[line] == "reported", piece.lined),
            abstract)  # fmt: skip


def against_results(pieces: list[Piece], answers: Answers | None = None,
                    named: dict[str, str] | None = None) -> AbstractRead:  # fmt: skip
    """The section, over every file the audit read, with the author's `answers`; `named`
    holds each title of `answers.results` a heading has, as `given_title` gives it, and how
    its headings were read (`placed`, `merged`)."""
    from manuscript_guard.audit import (
        Candidate,
        around,
        measure_discrimination,
        normalise_number,
    )

    read = AbstractRead()
    if not _asked(read, pieces, answers or Answers(), named or {}):
        return read
    read.compared = True
    split = [(piece, *_parts(piece)) for piece in pieces]
    printed = [number for _piece, _abstract, reported, _lines in split
               for number in _numbers(reported)]  # fmt: skip
    exact = {normalise_number(number) for number in printed}
    rounded = {found for number in printed for found in coarser(number)}
    words = {word for _piece, _abstract, reported, _lines in split for word in _words(reported)}
    printed_powers = {power.key for piece, _abstract, reported, _lines in split if piece.text
                      for power in powers(piece.text, reported, ties(piece.path, piece.text))
                      if not power.scale}  # fmt: skip
    read.discrimination = measure_discrimination(exact | {value for value, _at in rounded})
    intervals = [(piece, reported, found) for piece, _a, reported, _l in split
                 for found in reported_intervals(reported)]  # fmt: skip
    tests = [(piece, reported, found) for piece, _a, reported, _l in split
             for found in reported_tests(reported)]  # fmt: skip
    aside = _Elsewhere(pieces)
    for piece, abstract, _reported, lines in split:
        spans = _conflicts(read, piece, abstract, intervals, tests)
        written = _shares(read, piece, abstract)
        background = _in_background(piece, abstract, lines)
        for looked in _looked_for(piece, abstract, lines):
            atom, parts = looked.atom, list(looked.parts)
            if any(start <= atom.start < end for start, end in spans):
                continue
            if not parts:
                continue  # "2ndyear": a rank typed against its word, no number to look for
            read.numbers += 1
            candidate = Candidate(atom.text, normalise_number(atom.text), piece.path,
                                  atom.line, around(atom), atom.start,
                                  _keyed(abstract, atom.start, "")["sentence"])  # fmt: skip
            off, parts = _off_its_counts(atom, parts, written)
            states = [("exact" if part in printed_powers else "") if part in looked.powered
                      else _state(part, exact, rounded, words) for part in parts]  # fmt: skip
            if background(atom) and "" in states and not off:
                # A Background number given in the Introduction is found there.
                states = [state or aside.state(part, part in looked.powered, introduction=True)
                          for part, state in zip(parts, states, strict=True)]  # fmt: skip
            if off:
                read.off_counts.append(candidate)
            elif off is not None and "" not in states:
                read.from_counts.append(candidate)
            elif "" in states:
                missing = [part for part, state in zip(parts, states, strict=True) if not state]
                places = aside.places(missing, looked.powered)
                if places:
                    # The parts missing, where some of the atom's are found: "40%" of
                    # "30-40%" (round 1 of #700).
                    read.only_in.append((candidate, places, () if len(missing) == len(parts)
                                         else tuple(missing)))
                elif background(atom):
                    read.unsourced.append(candidate)
                else:
                    read.not_found.append(candidate)
            elif "rounded" in states:
                read.rounded.append(candidate)
            else:
                read.matched += 1
                read.found.append(candidate)
    return read


def _in_background(piece: Piece, abstract: str, lines: set[int]) -> Callable[[Atom], bool]:
    """Whether an atom of one file's Abstract stands in its Background: on a line under a
    heading of `BACKGROUND_PARTS` there (`InBackground`), or from a run-in label of one,
    "Background:", to the next label of a part of any wording, "Methods:", "Design,
    Setting, and Participants:", or the Abstract's end (`label_ends`)."""
    headed = {line for line in lines if piece.place is not None
              and isinstance(piece.place(line), InBackground)}  # fmt: skip
    labels = label_ends(abstract) if lines else []
    spans = [(start, labels[at + 1][0] if at + 1 < len(labels) else len(abstract))
             for at, (start, _end, opens) in enumerate(labels) if opens]  # fmt: skip
    return lambda atom: atom.line in headed or any(start <= atom.start < end
                                                    for start, end in spans)


def _line_starts(piece: Piece) -> list[int]:
    """Where each line of a file starts in its text, line 1 first."""
    starts, at = [], 0
    for row in (piece.lined or piece.hidden).split("\n"):
        starts.append(at)
        at += len(row) + 1
    return starts


class _Elsewhere:
    """The numbers the sections that report nothing give where a paper may yet report
    (`Aside`), each line of them in every file read, as the comparison reads the numbers
    where the paper reports: as printed, each rounding, each word holding letters and each
    power; each with where it stands, `(path, titles, line)`."""

    def __init__(self, pieces: list[Piece]) -> None:
        from manuscript_guard.audit import normalise_number

        self.exact: dict[str, list] = {}
        self.rounded: dict[tuple[str, int], list] = {}
        self.words: dict[str, list] = {}
        self.powers: dict[str, list] = {}
        for piece in pieces:
            if piece.place is None or not piece.abstract:
                continue
            starts = _line_starts(piece)
            placed = {}
            for line in range(1, len(starts) + 1):
                found = piece.place(line)
                if isinstance(found, Aside) and where(piece, line) == "":
                    placed[line] = (piece.path, found.titles, line)
            if not placed:
                continue
            text = _kept(piece.hidden, placed.__contains__, piece.lined)
            for line, place in placed.items():
                end = starts[line] - 1 if line < len(starts) else len(text)
                row = text[starts[line - 1] : end]
                for number in _numbers(row):
                    self.exact.setdefault(normalise_number(number), []).append(place)
                    for one in coarser(number):
                        self.rounded.setdefault(one, []).append(place)
                for word in _words(row):
                    self.words.setdefault(word, []).append(place)
            if piece.text:
                for power in powers(piece.text, text, ties(piece.path, piece.text)):
                    place = placed.get(piece.line(power.start))
                    if place is not None and not power.scale:
                        self.powers.setdefault(power.key, []).append(place)

    def _found(self, part: str, powered: bool) -> tuple[list, list]:
        """Where one part of an Abstract's atom stands among these lines as printed, and
        where only as a rounding, as `_state` reads it where the paper reports: a power and a
        word holding letters as printed alone."""
        from manuscript_guard.audit import normalise_number

        if powered:
            return self.powers.get(part, []), []
        value = normalise_number(part)
        places = _decimal(part)
        if places is None:
            words = self.words.get(part, []) if any(c.isalpha() for c in part) else []
            return [*self.exact.get(value, []), *words], []
        return self.exact.get(value, []), self.rounded.get((value, places[1]), [])

    def state(self, part: str, powered: bool, *, introduction: bool = False) -> str:
        """How one part is found among these lines, "exact", "rounded" or "": as printed
        first, then as a rounding; in the Introduction and its material alone with
        `introduction`, so that a rounding there is seen beside a number printed elsewhere
        (round 1 of #700)."""
        exact, rounded = self._found(part, powered)
        if introduction:
            exact = [one for one in exact if Aside(one[1]).introduction]
            rounded = [one for one in rounded if Aside(one[1]).introduction]
        return "exact" if exact else "rounded" if rounded else ""

    def places(self, parts: list[str], powered: frozenset[str]) -> list[tuple]:
        """Where the parts not found where the paper reports stand among these lines, as
        printed or as a rounding, each section by its first line and in the order of the
        files and their lines; none unless every part stands in one."""
        found: dict[tuple, int] = {}
        for part in parts:
            where_found = [one for listed in self._found(part, part in powered) for one in listed]
            if not where_found:
                return []
            for path, titles, line in where_found:
                key = (path, titles)
                found[key] = min(found.get(key, line), line)
        order = {path: at for at, path in enumerate(dict.fromkeys(p for p, _t in found))}
        return sorted(((path, titles, line) for (path, titles), line in found.items()),
                      key=lambda one: (order[one[0]], one[2]))  # fmt: skip


def _asked(read: AbstractRead, pieces: list[Piece], answers: Answers,
           named: dict[str, str]) -> bool:  # fmt: skip
    """Whether there is an Abstract and a Results to compare, and if not, why not put in
    `read`, with the question to the author where they have not answered it; and each note
    on the answers in `read.answered`: a title `--results` gives that no heading has, whose
    heading is not read as the Results, or whose heading is read as them and is a section
    that reports nothing otherwise (round 1 of #697), and an answer the paper's own headings
    contradict, which they win over (Basile, 2026-11-16, decision 27)."""
    for title in dict.fromkeys(answers.results):
        state = named.get(given_title(title))
        code, said = {None: (UNMATCHED, _UNMATCHED), NOT_READ: (NOT_TAKEN, _NOT_TAKEN),
                      READ_REPORTING_NOTHING: (LIFTED, _LIFTED)}.get(state, ("", ""))
        if code:
            read.answered.append((code, said.format(title)))
    if not any(piece.abstract for piece in pieces):
        read.why_not = SAID_NO_ABSTRACT if answers.no_abstract else NO_ABSTRACT
        read.question = "" if answers.no_abstract else ASKED_NO_ABSTRACT
        return False
    if answers.no_abstract:
        read.answered.append((CONTRADICTED, _CONTRADICTS_ABSTRACT))
    if not any(piece.results for piece in pieces):
        read.why_not = SAID_NO_RESULTS if answers.no_results else NO_RESULTS
        read.question = "" if answers.no_results else ASKED_NO_RESULTS
        return False
    if answers.no_results:
        read.answered.append((CONTRADICTED, _CONTRADICTS_RESULTS))
    return True


def _state(part: str, exact: set[str], rounded: set[tuple[str, int]], words: set[str]) -> str:
    """Whether one part of an Abstract's atom is found where the paper reports: "exact",
    "rounded" or "". A number is compared as a number, with the numbers there and their
    roundings. A part no number is read in, that holds a letter ("v8", "chr15", "PI3K"), is
    found only as printed, a whole word there (`_words`): never by a digit it holds, and
    never as a rounding."""
    from manuscript_guard.audit import normalise_number

    value = normalise_number(part)
    if value in exact:
        return "exact"
    places = _decimal(part)
    if places is None:
        return "exact" if any(c.isalpha() for c in part) and part in words else ""
    return "rounded" if (value, places[1]) in rounded else ""


def _shares(read: AbstractRead, piece: Piece, abstract: str) -> dict[int, tuple[bool, str]]:
    """Each share one file's Abstract writes beside both its counts (`shares.written_shares`),
    by the offset its percentage starts at: whether it is off them, and its percentage as
    printed; each one off them put in `read` as an arithmetic finding, at the line of the
    file it is on, whether or not its percentage was left for the section to read."""
    from manuscript_guard.audit import Disagreement
    from manuscript_guard.stats import shares

    found = {}
    for share, start in shares.written_shares(abstract):
        read.shares += 1
        found[start] = (shares.off(share), share.percent)
        if found[start][0]:
            keyed = _keyed(abstract, start, share.printed)
            said = f"in the Abstract, {shares.described(share)}"
            read.arithmetic.append(Disagreement(piece.path, piece.line(start), said,
                                                _around(abstract, start, share), **keyed))
    return found


def _around(text: str, at: int, share) -> str:
    """The words around a share's percentage on its line, as the report quotes a number's
    (`audit.around`): an Abstract is often a line of its own."""
    from manuscript_guard.audit import around

    ends = text.find("\n", at)
    line_start, line_end = text.rfind("\n", 0, at) + 1, len(text) if ends < 0 else ends
    end = at + len(share.percent)
    return around(Atom(share.percent, at, end, share.line, at - line_start, line_start,
                       line_end, text))  # fmt: skip


def _off_its_counts(atom: Atom, parts: list[str],
                    written: dict[int, tuple[bool, str]]
                    ) -> tuple[bool | None, list[str]]:  # fmt: skip
    """Whether an atom that holds a percentage written beside both its counts is off them,
    and its other parts, to be looked for; None and all its parts for any other atom. An
    atom off its counts is listed so whatever else it holds, as its finding is said: one
    typed closed up, "164/250(75%)", was both not found and off its counts (round 1 of
    #664). One they give is given by them where its other parts are found."""
    from manuscript_guard.audit import normalise_number

    at = next((start for start in written if atom.start <= start < atom.end), None)
    if at is None:
        return None, parts
    off, percent = written[at]
    others = list(parts)
    for part in parts:
        if normalise_number(part) == normalise_number(percent):  # "(66 %)": no sign in it
            others.remove(part)
            break
    return off, others


# ----------------------------------------------------------------------------- conflicts

#: An estimate's name, read as one: its abbreviation, or its words, either way.
_NAMED = {
    "odds ratio": "or", "risk ratio": "rr", "relative risk": "rr", "hazard ratio": "hr",
    "rate ratio": "irr", "incidence rate ratio": "irr", "reporting odds ratio": "ror",
    "proportional reporting ratio": "prr", "prevalence ratio": "pr",
    "subdistribution hazard ratio": "shr", "mean difference": "md", "risk difference": "rd",
    "absolute difference": "ard", "standardised mean difference": "smd",
    "standardized mean difference": "smd",
}  # fmt: skip


def estimate_of(interval: ReportedInterval) -> tuple[str, str, str]:
    """What an interval estimates, as pairing reads it: its kind, its name, an abbreviation
    and its words taken as one, and its level, 95 where none is stated."""
    name = " ".join(interval.name.lower().split())
    name = re.sub(r"(ratio|risk|ence)s$", r"\1", name)
    return interval.kind, _NAMED.get(name, name), interval.level or "95"


def _whole_line(text: str, at: int) -> str:
    """The line `at` stands on, as the report quotes one."""
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    return " ".join(text[start : end if end >= 0 else len(text)].split())[:140]


def _conflicts(read: AbstractRead, piece: Piece, abstract: str, intervals: list,
               tests: list) -> list[tuple[int, int]]:  # fmt: skip
    """Each conflict of one file's Abstract, put in `read`, and where each stands, by the
    lines of the file (`Piece.line`)."""
    from manuscript_guard.audit import Disagreement

    path = piece.path
    spans = []
    for given in reported_intervals(abstract):
        found = _counterpart_interval(given, intervals)
        if found is None:
            continue
        found_in, _text, other = found
        said = (f"the Abstract gives {given.written}, and where the paper reports, "
                f"{_at(found_in, other.start, path)}gives {other.written}")  # fmt: skip
        read.conflicts.append(Disagreement(path, piece.line(given.start), said,
                                           _whole_line(abstract, given.start),
                                           **_keyed(abstract, given.start, given.written)))
        spans.append((given.start, given.end))
    for given in reported_tests(abstract):
        found = _counterpart_test(given, tests)
        if found is None:
            continue
        found_in, _text, other = found
        said = (f"the Abstract gives {_test(given)}, and where the paper reports, "
                f"{_at(found_in, other.start, path)}gives {_test(other)}")  # fmt: skip
        read.conflicts.append(Disagreement(path, piece.line(given.start), said,
                                           _whole_line(abstract, given.start),
                                           **_keyed(abstract, given.start, _test(given))))
        spans.append((given.start, given.end))
    return spans


def _keyed(abstract: str, start: int, typed: str) -> dict:
    """What the key of a finding on the Abstract's number `typed` at `start` is made of
    (`keys`): the number, and its sentence of the Abstract."""
    return {"subject": typed, "at": start,
            "sentence": digest(ABSTRACT_PART, sentence_at(abstract, start))}


def _at(found_in: Piece, start: int, path: Path) -> str:
    line = found_in.line(start)
    return f"line {line} " if found_in.path == path else f"{found_in.path.name} line {line} "


def _test(test: Reported) -> str:
    return f"{test.written}, P {test.sign} {test.p}"


def _counterpart_interval(given: ReportedInterval, intervals: list):
    """The one interval where the paper reports that an Abstract's differs from in exactly
    one of its three numbers, or None: where one agrees in all three, where none or several
    differ in one, or where the Abstract's cannot be read."""
    numbers = (given.estimate, given.low, given.high)
    near = {}
    for found_in, text, other in intervals:
        if estimate_of(other) != estimate_of(given):
            continue
        agreeing = sum(agree(a, b) for a, b in zip(numbers, (other.estimate, other.low,
                                                              other.high), strict=True))
        if agreeing == 3:
            return None
        if agreeing == 2:
            near.setdefault((other.estimate, other.low, other.high), (found_in, text, other))
    return next(iter(near.values())) if len(near) == 1 else None


def p_apart(mine: tuple[float, float], theirs: tuple[float, float]) -> bool:
    """Whether no P can be both: the ranges two printed P stand for do not meet, a range's
    end being no part of it."""
    return not (mine[0] < theirs[1] and theirs[0] < mine[1])


def _counterpart_test(given: Reported, tests: list):
    """The one test where the paper reports of the same kind, degrees of freedom and
    statistic as an Abstract's whose P cannot be the Abstract's, or None: where one of them
    has a P that can, or several could be its counterpart."""
    from manuscript_guard.audit import normalise_number

    mine = p_range(given.sign, given.p)
    if mine is None:
        return None
    df = tuple(normalise_number(one) for one in given.df)
    near = {}
    for found_in, text, other in tests:
        if other.kind != given.kind or tuple(normalise_number(one) for one in other.df) != df:
            continue
        if not agree(given.statistic, other.statistic):
            continue
        theirs = p_range(other.sign, other.p)
        if theirs is None:
            return None
        if not p_apart(mine, theirs):
            return None
        near.setdefault((other.statistic, other.sign, other.p), (found_in, text, other))
    return next(iter(near.values())) if len(near) == 1 else None
