"""The readings a generated input is put to, each under a name.

A reading is one way the package reads text, taken at the widest door it has: the function
a gate calls on a whole file, not a helper inside it. Each takes something JSON can carry
and gives back something JSON can carry, because the same input is read in two processes
and the two answers are compared: the working tree's beside the base branch's
(`tests/test_differential.py`), and the working tree's beside its own under another hash
seed. `tests/test_properties.py` reads through them too, so a reading added here is held to
the invariants and compared with the base from the day it is written.

**This file is run against two versions of the package**, so it imports nothing from it at
the top. A reading is registered as a function that does the importing and returns the
function that does the reading. Where the first fails, the package it was asked of has no
such reading: a module or a name that is not there yet, in a base older than the reading.
That is said and passed over. Where the second raises, the reading failed on that input,
and what it raised is its answer, to be compared like any other.

A reading that calls a helper by a private name (`_hidden`, `_file`, `_judge`) is tied to
that name. A pull request that renames one changes the reading here, and the base then has
no such reading until the rename is merged.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

Reading = Callable[[Any], Any]

#: Every reading by its name, as the function that finds it in the package on the path.
READINGS: dict[str, Callable[[], Reading]] = {}

MAIN = Path("manuscript") / "main.md"
ROUND = Path("revision") / "round-1.yaml"
PAPER = Path("paper.yaml")

#: The authors a blind review is not to see, as `authors.yaml` holds them: a given name of
#: two words, a family name of three and one with an apostrophe, an ORCID iD, an e-mail
#: address and an institution.
PEOPLE = {
    "authors": [
        {"given": "Ada", "family": "Example", "orcid": "0000-0002-1825-0097",
         "email": "ada.example@invalid.example"},
        {"given": "Mary Ann", "family": "van der Berg"},
        {"given": "Sean", "family": "O'Brien"},
    ],
    "affiliations": [
        {"text": "Department of Clinical Pharmacology, Example University, Springfield, Japan"}
    ],
}  # fmt: skip


def reading(name: str) -> Callable[[Callable[[], Reading]], Callable[[], Reading]]:
    def register(find: Callable[[], Reading]) -> Callable[[], Reading]:
        if name in READINGS:
            raise ValueError(f"two readings are named {name!r}")
        READINGS[name] = find
        return find

    return register


class Unavailable(Exception):
    """This reading needs a program that is not installed here. Raised when the reading is
    looked for, so that it is passed over where it cannot be made, on either side."""


def why_not(raised: BaseException) -> str:
    """Why a reading could not be found in the package on the path, as one of two words.

    `absent`: the package has no such reading, or this machine cannot make it. The module
    or the name it is imported from is not in `manuscript_guard`, which is a reading newer
    than the source, or one whose helper was since renamed; or a program it needs is not
    installed. That is passed over.

    `broken`: anything else. A helper that takes other arguments now, a dependency this
    source needs and the installed ones do not include. The source has the reading and
    could not be asked, which is not the same as having nothing to compare, and was taken
    for it: the readings were passed over and the job was green."""
    if isinstance(raised, Unavailable):
        return "absent"
    inside = (getattr(raised, "name", None) or "").split(".")[0] == "manuscript_guard"
    return "absent" if isinstance(raised, ImportError) and inside else "broken"


def answer(read: Reading, given: Any) -> Any:
    """What `read` makes of `given`, as JSON carries it: its answer, or what it raised.
    Through JSON and back, so that a tuple in one process and a list in the other, which is
    what the pipe makes of it, are the same answer."""
    try:
        found = {"answer": read(given)}
    # `SystemExit` with the rest: it is what the command line raises when it refuses its
    # arguments, and let through it ended the process that was answering.
    except (Exception, SystemExit) as raised:  # noqa: BLE001 - what is raised is the answer
        found = {"raised": f"{type(raised).__name__}: {raised}"}
    return json.loads(json.dumps(found, ensure_ascii=True, sort_keys=True))


def _told(report: Any) -> dict[str, Any]:
    """A report as the two sides compare it: every finding with where it points and what it
    says, in the order the gate gave them, and the counts. Each part under its name, so
    that where two answers part can be said in words: `findings[0].line`. The file is one
    of the parts: a finding moved from the manuscript to `paper.yaml` with its line kept
    was no difference."""
    return {
        "findings": [
            {
                "gate": f.gate,
                "path": None if f.path is None else f.path.as_posix(),
                "code": f.code,
                "severity": f.severity,
                "message": f.message,
                "line": f.line,
                "col": f.col,
                "context": f.context,
                "hint": f.hint,
            }
            for f in report.findings
        ],
        "counts": dict(report.counts),
    }


# ------------------------------------------------------------------------------ hiding


@reading("mask")
def _mask() -> Reading:
    from manuscript_guard.text.masking import mask

    return mask


@reading("latex mask")
def _latex_mask() -> Reading:
    from manuscript_guard.text.latex.mask import mask

    return mask


@reading("latex refusals")
def _latex_refusals() -> Reading:
    from manuscript_guard.text.latex.mask import read

    return lambda text: [[r.code, r.offset] for r in read(text).refusals]


@reading("latex sections")
def _latex_sections() -> Reading:
    # `Heading` came with the headings, so that a base without them has no such reading.
    from manuscript_guard.text.latex.mask import Heading, read  # noqa: F401

    def sections(text: str) -> dict[str, Any]:
        reading = read(text)
        return {
            "headings": [[h.start, h.level, h.title] for h in reading.headings],
            "abstracts": [list(span) for span in reading.abstracts],
            "inputs": [[i.offset, i.path, i.body, list(i.environments)] for i in reading.inputs],
        }

    return sections


@reading("latex bindings")
def _latex_bindings() -> Reading:
    from manuscript_guard.text.latex.mask import read
    from manuscript_guard.text.latex.structure import Source
    from manuscript_guard.text.latex.views import bindings, markdown_view

    def bound(text: str) -> dict[str, Any]:
        source = Source("main.tex", text, read(text))
        good, malformed = bindings(source)
        return {
            "bound": [[p.ref, p.start, p.end, p.line, p.col] for p in good],
            "malformed": [[raw, at, line] for raw, at, line in malformed],
            "view": markdown_view(source, good),
            "tables": [list(span) for span in source.reading.tables],
            "listings": [[found.start, found.end, found.language]
                         for found in source.reading.listings],  # fmt: skip
        }

    return bound


@reading("hidden")
def _hidden() -> Reading:
    from manuscript_guard.gates.language import _hidden as hidden

    return hidden


@reading("own words")
def _own_words() -> Reading:
    from manuscript_guard.gates.language import _hidden as hidden
    from manuscript_guard.gates.vocabulary import own_words

    return lambda text: own_words(hidden(text))


@reading("spans")
def _spans() -> Reading:
    from manuscript_guard.text.comments import comment_spans
    from manuscript_guard.text.fences import fenced_spans
    from manuscript_guard.text.inline import (
        code_spans,
        definition_spans,
        equation_spans,
        link_text_spans,
    )
    from manuscript_guard.text.masking import (
        front_matter_end,
        html_comments,
        mask,
        metadata_blocks,
    )

    def spans(text: str) -> dict[str, Any]:
        masked = mask(text)
        code = code_spans(masked)
        return {
            "front matter": front_matter_end(text),
            "metadata": metadata_blocks(text),
            "fences": [
                {"start": f.start, "body": [f.body_start, f.body_end], "end": f.end, "info": f.info}
                for f in fenced_spans(text)
            ],
            "comments": comment_spans(text),
            "hidden comments": html_comments(text),
            "code": code,
            "equations": equation_spans(masked, code),
            "link text": link_text_spans(text),
            "definitions": definition_spans(text),
        }

    return spans


@reading("sections")
def _sections() -> Reading:
    from manuscript_guard.text.sections import footnote_index, heading_index, split_sections

    def sections(text: str) -> dict[str, Any]:
        return {
            "breaks": [
                {"start": h.start, "level": h.level, "title": h.title, "setext": h.setext}
                for h in heading_index(text)
            ],
            "sections": [
                {"title": s.title, "level": s.level, "line": s.line, "body": s.body,
                 "enclosed": s.enclosed}
                for s in split_sections(text)
            ],  # fmt: skip
            "notes": [
                {"start": n.start, "end": n.end, "references": list(n.references)}
                for n in footnote_index(text)
            ],
        }

    return sections


@reading("supplementary methods")
def _supplementary_methods() -> Reading:
    """What G9 reads as the Methods of a file of the supplement, and each model G15 finds
    named in its Methods. Where G2 holds its Methods-only rules is the `numbers` reading's."""
    from manuscript_guard.gates.methods import supplement_methods_in
    from manuscript_guard.gates.models import named_in_methods

    def supplementary(text: str) -> dict[str, Any]:
        return {
            "read": supplement_methods_in(text),
            "models": [list(found) for found in named_in_methods(text)],
        }

    return supplementary


@reading("summaries")
def _summaries() -> Reading:
    """The results keys a file gives in its Abstract or a conclusion, and those it binds where
    the paper reports them: G8's reading of the parts of a paper."""
    from manuscript_guard.gates.reported import Walk

    def summaries(given: dict[str, Any]) -> dict[str, Any]:
        found, reported = Walk(given["abstract title"]).read(given["text"])
        return {
            "given": [[one.key, one.heading, one.line] for one in found],
            "reported": sorted(reported),
        }

    return summaries


# ----------------------------------------------------------------------------- numbers


@reading("numbers")
def _numbers() -> Reading:
    from manuscript_guard.classify import Classifier
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
    from manuscript_guard.text.tokens import find_atoms

    def numbers(given: dict[str, Any]) -> list[dict[str, Any]]:
        """Every atom G2 finds in the text, as `check_numbers` judges it: where it stands,
        under which headings, and by which rule it is let through or not."""
        text = given["text"]
        classifier = Classifier.load((), tuple(given.get("terms", ())))
        headings, notes = heading_index(text), footnote_index(text)
        scan = classifier.scan(text)
        found = []
        for atom in find_atoms(text, mask(text)):
            chains = chains_at(headings, notes, atom.start)
            verdict = classifier.classify_under(atom, chains, scan)
            found.append(
                {
                    "text": atom.text,
                    "at": [atom.start, atom.end],
                    "line": atom.line,
                    "col": atom.col,
                    "under": list(chains),
                    "verdict": verdict.kind,
                    "rule": verdict.rule,
                    "terms": list(verdict.terms),
                }
            )
        return found

    return numbers


@reading("pointers")
def _pointers() -> Reading:
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.pointers import check_pointers, display_numbers
    from manuscript_guard.text.placeholders import parse

    def pointers(given: dict[str, Any]) -> dict[str, Any]:
        """What G2 says of the pointers of a project with these files under `manuscript/`,
        and what each ref and num binding in them prints, by file and offset."""
        folder = Path(tempfile.mkdtemp(prefix="mg-pointers-"))
        try:
            root = folder / "paper"
            (root / "manuscript").mkdir(parents=True)
            (root / PAPER).write_text("title: A paper\n", encoding="utf-8")
            for relative, text in given["files"].items():
                path = root / "manuscript" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="")
            project = load_project(root)[0]
            numbers = display_numbers(project)
            printed = [
                [relative, found.start, numbers.printed(found)]
                for relative, text in sorted(given["files"].items())
                for found in parse(text)[0]
                if found.is_ref
            ]
            said = _from_root(_told(check_pointers(project)), root)
            return {"report": said, "printed": printed}
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return pointers


#: The coding dictionaries a generated text may type the release of.
DICTIONARIES = {"meddra": "26.1", "whodrug": "Global B3 March 2025", "icd_10": "2019"}


@reading("typed releases")
def _typed_releases() -> Reading:
    """Each place G2 finds a declared dictionary's release typed where it should be bound:
    where it stands and whose release it is."""
    from manuscript_guard.contracts.values import Value
    from manuscript_guard.gates.numbers import typed_releases

    declared = [
        Value(key=f"dictionary.{name}", value=release, display=release, origin="results",
              label=True, role="dictionary")
        for name, release in DICTIONARIES.items()
    ]  # fmt: skip

    def releases(text: str) -> list[list[Any]]:
        return [[start, end, value.key] for start, end, value in typed_releases(text, declared)]

    return releases


#: The intervals whose bounds a generated text quotes: the estimate, the level where the
#: estimate has a second interval, and the keys of the lower and of the upper bound.
INTERVALS = (
    ("ror.point", None, "ror.ci_low", "ror.ci_high"),
    ("ror.point", "90%", "ror.ci90_low", "ror.ci90_high"),
    ("hr.point", None, "hr.ci_low", "hr.ci_high"),
)


@reading("quoted whole")
def _quoted_whole() -> Reading:
    # The gate's function first: where the source has none, the reading is newer than it.
    from manuscript_guard.gates.numbers import in_sentences, quoted_whole
    from manuscript_guard.text.placeholders import parse

    namespace = whole_namespace()

    def read(text: str) -> dict[str, Any]:
        """What G2 says of the statistics a text quotes, and the intervals."""
        placeholders, _malformed = parse(text)
        return _told(quoted_whole([(MAIN, text, in_sentences(placeholders, text))], namespace))

    return read


@reading("data statement")
def _data_statement() -> Reading:
    from manuscript_guard.gates.data_statement import judge_statement

    policy = {"identifier_required": True, "no_data": [r"(?i)\bdoes not report data\b"]}

    def read(text: str) -> dict[str, Any]:
        """What G4 says of a Data availability statement under a policy that requires an
        identifier, with nothing cited."""
        return _told(judge_statement(text, policy, set(), MAIN))

    return read


def whole_namespace() -> dict[str, Any]:
    """Results that say what they belong to: two p values of one estimate, its interval, and
    two shares of one denominator."""
    from manuscript_guard.contracts.values import RESULTS, Value

    def value(key: str, **said: Any) -> tuple[str, Any]:
        return f"results.{key}", Value(key=key, value=1, display="1", origin=RESULTS, **said)

    return dict(
        [
            value("or.point"),
            value("or.ci_low", bounds="or.point", bound="low"),
            value("or.ci_high", bounds="or.point", bound="high"),
            value("or.p", of="or.point", family="secondary"),
            value("hr.p", of="or.point", family="secondary"),
            value("female.pct", of="female.n", over="cohort.n"),
            value("male.pct", of="male.n", over="cohort.n"),
            value("female.n"),
            value("male.n"),
            value("cohort.n"),
        ]
    )


@reading("labels")
def _labels() -> Reading:
    # The gate's function first: where the source has none, the reading is newer than it.
    from manuscript_guard.gates.labels import labelled
    from manuscript_guard.gates.numbers import in_sentences
    from manuscript_guard.text.placeholders import parse

    namespace = labels_namespace()

    def read(text: str) -> dict[str, Any]:
        """What G2 says of the labels a text writes beside intervals and spreads."""
        placeholders, _malformed = parse(text)
        return _told(labelled([(MAIN, text, in_sentences(placeholders, text))], namespace))

    return read


def labels_namespace() -> dict[str, Any]:
    """Results that record their labels: an estimate with its 95% and its 90% interval, one
    with an interval of no level, and a mean with a standard deviation and a standard
    error."""
    from manuscript_guard.contracts.values import RESULTS, Value

    def value(key: str, **said: Any) -> tuple[str, Any]:
        return f"results.{key}", Value(key=key, value=1, display="1", origin=RESULTS, **said)

    return dict(
        [
            value("or.point"),
            value("or.ci_low", bounds="or.point", bound="low", level="95%"),
            value("or.ci_high", bounds="or.point", bound="high", level="95%"),
            value("or.ci90_low", bounds="or.point", bound="low", level="90%"),
            value("or.ci90_high", bounds="or.point", bound="high", level="90%"),
            value("hr.point"),
            value("hr.ci_low", bounds="hr.point", bound="low"),
            value("hr.ci_high", bounds="hr.point", bound="high"),
            value("age.mean"),
            value("age.sd", spread="sd", of="age.mean"),
            value("age.se", spread="se", of="age.mean"),
        ]
    )


@reading("deviations")
def _deviations() -> Reading:
    from manuscript_guard.gates.design import deviations_said

    return deviations_said


@reading("planned results")
def _planned_results() -> Reading:
    from manuscript_guard.gates.design import planned_results

    def read(plan: str) -> Any:
        """Each key the plan's Planned results section lists, whether it is a group, and its
        line; None where the plan has no such section."""
        found = planned_results(plan)
        return None if found is None else [[p.key, p.group, p.line] for p in found]

    return read


@reading("plan variables")
def _plan_variables() -> Reading:
    from manuscript_guard.gates.collection import variables_named

    def read(given: dict[str, Any]) -> Any:
        """The dictionary's variables the plan names and the names it gives that the
        dictionary lacks, each with the line of its first mention."""
        used, undefined = variables_named(given["plan"], given["names"])
        return {"used": [[n.name, n.line] for n in used],
                "undefined": [[n.name, n.line] for n in undefined]}  # fmt: skip

    return read


@reading("interval order")
def _interval_order() -> Reading:
    from manuscript_guard.contracts.values import RESULTS, Value
    from manuscript_guard.gates.numbers import _interval_order as order
    from manuscript_guard.text.placeholders import parse

    namespace = {"results.ror.point": Value("ror.point", 1.0, "1.0", RESULTS)}
    for estimate, level, *keys in INTERVALS:
        for end, key in zip(("low", "high"), keys, strict=True):
            namespace[f"results.{key}"] = Value(
                key, 1.0, "1.0", RESULTS, bounds=estimate, bound=end, level=level
            )

    def interval_order(text: str) -> dict[str, Any]:
        """The intervals G2 finds quoted upper bound first in a text whose bindings are
        the bounds of `INTERVALS`, in the order the gate gives them."""
        return _told(order(parse(text)[0], namespace, MAIN, text))

    return interval_order


# ---------------------------------------------------------------------------- language


def _file(text: str) -> Any:
    from manuscript_guard.gates.language import _file as read

    return read(0, MAIN, text, [], False)


@reading("vocabulary")
def _vocabulary() -> Reading:
    from manuscript_guard.gates.vocabulary import Passage, judge_vocabulary

    def vocabulary(given: dict[str, Any]) -> dict[str, Any]:
        file = _file(given["text"])
        passage = Passage(file.path, file.text, file.printed, file.line_of)
        return _told(judge_vocabulary([passage], given["entries"], PAPER))

    _file("")  # the door this reading goes through is part of what it needs
    return vocabulary


@reading("spelling")
def _spelling() -> Reading:
    from manuscript_guard.gates.spelling import judge_spelling
    from manuscript_guard.gates.vocabulary import Passage

    def spelling(given: dict[str, Any]) -> dict[str, Any]:
        file = _file(given["text"])
        # The text the gate hands this reading: without the sections whose wording is
        # somebody else's, where the source has that text.
        read = getattr(file, "spelt", file.printed)
        passage = Passage(file.path, file.text, read, file.line_of)
        return _told(judge_spelling([passage], given["variant"], given["accepted"], PAPER))

    _file("")
    return spelling


@reading("title held")
def _title_held() -> Reading:
    from manuscript_guard.gates.lookups import title_held

    def held(given: dict[str, str]) -> float | None:
        found = title_held(given["cited"], given["registered"])
        return None if found is None else round(found, 6)

    return held


@reading("title alike")
def _title_alike() -> Reading:
    """How alike a cited title is to a registered one, each way, by which G7 takes a work a
    search found for the one cited (`gates/searched`)."""
    from manuscript_guard.gates.searched import alike

    def held(given: dict[str, str]) -> float:
        return round(alike(given["cited"], [given["registered"]]), 6)

    return held


@reading("search words")
def _search_words() -> Reading:
    """The words of a title `lookup` searches the registries for."""
    from manuscript_guard.gates.searched import search_words

    return search_words


@reading("authors cited")
def _authors_cited() -> Reading:
    """A .bib entry's author field, read into people and groups."""
    from manuscript_guard.literature.names import cited

    def read(field: str) -> list[Any]:
        found = cited(field)
        return [[[n.family, n.given, n.group] for n in found.names], found.truncated]

    return read


@reading("same family name")
def _same_family_name() -> Reading:
    """Whether two family names are one person's, by G7's folding (`gates/authors`)."""
    from manuscript_guard.gates.authors import same

    return lambda given: same(given["cited"], given["registered"])


@reading("units after")
def _units_after() -> Reading:
    """The unit written right after each results binding, which G2 holds to the unit the
    analysis emitted."""
    from manuscript_guard.gates.bound_units import units_after

    def units(text: str) -> list[list[Any]]:
        return [[found.key, found.start, found.unit] for found in units_after(text)]

    return units


@reading("limit stated")
def _limit_stated() -> Reading:
    """Whether the quote of a journal profile's limit states its number, which G4 fails
    where it does not."""
    from manuscript_guard.gates.journal_quotes import _states

    def stated(given: dict[str, Any]) -> bool:
        return _states(given["text"], given["value"])

    return stated


@reading("notation")
def _notation() -> Reading:
    from manuscript_guard.gates.notation import judge_notation
    from manuscript_guard.gates.vocabulary import Passage

    def notation(text: str) -> dict[str, Any]:
        file = _file(text)
        passage = Passage(file.path, file.text, file.printed, file.line_of)
        return _told(judge_notation([passage]))

    _file("")
    return notation


@reading("reported tests")
def _reported_tests() -> Reading:
    """Each test statistic with a P after it in its sentence, as it is printed, and what
    G8 says of the P: the range the statistic gives, and whether the two disagree."""
    from manuscript_guard.stats.reported import judge, reported_tests
    from manuscript_guard.text.masking import mask

    def reported(text: str) -> list[list[Any]]:
        found = []
        for test in reported_tests(mask(text)):
            verdict = judge(test)
            said = None if verdict is None else [
                f"{verdict.low:.12g}", f"{verdict.high:.12g}", verdict.inconsistent,
                verdict.decision,
            ]  # fmt: skip
            found.append(
                [test.start, test.kind, test.statistic, list(test.df), test.sign, test.p,
                 test.quiet, said]  # fmt: skip
            )
        return found

    return reported


@reading("reported intervals")
def _reported_intervals() -> Reading:
    """Each named estimate with a confidence interval after it, as it is printed, and what
    G8 says of it: how far its arms differ, and whether it and its P disagree."""
    from manuscript_guard.stats.intervals import (
        asymmetry,
        outside_interval,
        p_against,
        reported_intervals,
    )
    from manuscript_guard.text.masking import mask

    def reported(text: str) -> list[list[Any]]:
        found = []
        for interval in reported_intervals(mask(text)):
            share = asymmetry(interval)
            against = p_against(interval)
            found.append(
                [interval.start, interval.end, interval.kind, interval.name, interval.estimate,
                 interval.low, interval.high, interval.level,
                 None if interval.p is None else list(interval.p), interval.quiet,
                 interval.p_quiet, None if share is None else f"{share:.12g}",
                 None if against is None else [against.excludes, against.alpha, against.null],
                 outside_interval(interval)]
            )  # fmt: skip
        return found

    return reported


@reading("table shares")
def _table_shares() -> Reading:
    """Each count and its share in a pipe table, as it is printed, with the denominator the
    table names for it and its row's total, whether it is uncertain, and whether `audit`
    lists it as off."""
    from manuscript_guard.stats.shares import off, table_shares
    from manuscript_guard.text.tables import markdown_tables

    def read(text: str) -> list[list[Any]]:
        return [
            [s.line, s.printed, s.count, s.percent, s.over, s.own, s.row_total, s.label,
             s.uncertain, off(s)]
            for table in markdown_tables(text) for s in table_shares(table)
        ]  # fmt: skip

    return read


@reading("whole-number means")
def _whole_number_means() -> Reading:
    """Each mean in a pipe table's rows the auditor names, as it is printed, with its
    column's n, whether it is uncertain, and whether it can be the mean of n whole
    numbers."""
    from manuscript_guard.stats.granularity import possible, table_means
    from manuscript_guard.text.tables import markdown_tables

    def read(given: dict[str, Any]) -> list[list[Any]]:
        labels = tuple(given["labels"])
        return [
            [m.line, m.printed, m.mean, m.n, m.label, m.uncertain, possible(m.mean, m.n)]
            for table in markdown_tables(given["text"]) for m in table_means(table, labels)
        ]  # fmt: skip

    return read


@reading("printed value")
def _printed_value() -> Reading:
    """Whether a value an earlier output printed is this paper's, as G8 compares one read
    from the earlier output's text: each printing given, and the same printing moved."""
    from manuscript_guard.contracts.values import Value
    from manuscript_guard.gates.related import _same_printed

    def compared(given: list[dict[str, Any]]) -> list[list[bool]]:
        found = []
        for case in given:
            now = Value(key="k", value=case["value"], display=case["display"], origin="results")
            found.append([_same_printed(case["printed"], now), _same_printed(case["moved"], now)])
        return found

    return compared


@reading("plan sections")
def _plan_sections_compared() -> Reading:
    """The headings of the sections two plans both have whose words differ, as G8 compares
    an earlier output's plan with this paper's."""
    from manuscript_guard.gates.related_methods import sections_compared

    def compared(given: dict[str, str]) -> list[str]:
        found = sections_compared(given["then"], given["now"])
        return [title for title, _key, _there, _here in found]

    return compared


@reading("abbreviations")
def _abbreviations() -> Reading:
    from manuscript_guard.gates.language import _judge, _Known, _shipped

    def abbreviations(given: dict[str, Any]) -> dict[str, Any]:
        exact, lowered = _shipped()
        known = _Known(exact | set(given.get("known", ())), lowered)
        return _told(_judge([_file(given["text"])], known, Path(".")))

    _file("")
    return abbreviations


@reading("prose quotations")
def _prose_quotations() -> Reading:
    """Each quotation of four words or more in a sentence that cites, with the paragraph's
    line and the works cited: what G7 looks for in the stored sources."""
    from manuscript_guard.gates.quotations import quotations_in

    def quotations(text: str) -> list[list[Any]]:
        return [[q.line, q.quote, list(q.keys)] for q in quotations_in(text)]

    return quotations


@reading("passages")
def _passages() -> Reading:
    """The sentences each entry of a `passages.yaml` belongs to, with the line of each one's
    paragraph, and why an entry belongs to none: what G7 holds a supporting passage to, and
    what the co-author checker shows it beside. No source is stored, so none is read."""
    from manuscript_guard.checking.produce import cited_sentences, citing_document
    from manuscript_guard.literature.passages import Passage, survey

    nowhere = Path(__file__).resolve().parent / "no stored sources"

    def passages(given: dict[str, Any]) -> list[list[Any]]:
        sentences = cited_sentences([citing_document(MAIN, given["text"])])
        entries = tuple(
            Passage(number, entry["sentence"], entry["citekey"], entry["passage"],
                    entry["locator"])
            for number, entry in enumerate(given["entries"], start=1)
        )  # fmt: skip
        found = survey(nowhere, sentences, entries)
        return [
            [[[cited.line, cited.text] for cited in one.sentences], one.stale]
            for one in found.passages
        ]

    return passages


@reading("recycled passages")
def _recycled_passages() -> Reading:
    """The passages of a manuscript file an earlier paper of its authors has too, with their
    lines, how many words are shared and how many of them quoted, the part of the paper they
    stand in and whether they cite it: what G7 reports before a similarity check does."""
    from manuscript_guard.gates.recycling import recycled_in

    def recycled(given: dict[str, str]) -> list[list[Any]]:
        return [
            [p.first_line, p.last_line, p.shared, p.quoted, p.kind, p.cited, p.excerpt]
            for p in recycled_in(given["text"], given["source"], "earlier")
        ]

    return recycled


@reading("checker sentences")
def _checker_sentences() -> Reading:
    """How a co-author's items are cut out of a manuscript: the sentences of each paragraph.

    Registered because it is a reading of text like any other, and because what it gets wrong
    reaches a person rather than a gate: a sentence cut at "et al." was sent to a co-author as an
    item whose whole content was a citation.
    """
    from manuscript_guard.checking.produce import _sentences_of

    def checker_sentences(text: str) -> list[list[Any]]:
        return [[line, sentence] for line, sentence in _sentences_of(text)]

    return checker_sentences


@reading("blind names")
def _blind_names() -> Reading:
    """What names an author of `generated.PEOPLE` in a text, and where: what the build reads
    a document reviewed blind for."""
    from manuscript_guard.build.blinding import names_in, sought

    wanted = sought(PEOPLE)

    def blind_names(text: str) -> list[list[Any]]:
        return [[what, start] for what, start in names_in(text, wanted)]

    return blind_names


# ------------------------------------------------------------------- titles and quotes


@reading("tex outside maths")
def _tex() -> Reading:
    from manuscript_guard.text.tex import tex_outside_maths

    def tex(line: str) -> list[Any] | None:
        found = tex_outside_maths(line)
        return None if found is None else list(found)

    return tex


@reading("reworded")
def _reworded() -> Reading:
    from manuscript_guard.reworded import compare

    def reworded(edit: list[str]) -> dict[str, Any]:
        before, after = edit
        return _told(compare(before, after, MAIN))

    return reworded


@reading("title")
def _title() -> Reading:
    from manuscript_guard.contracts.project import outside_maths

    return lambda line: [outside_maths(line), outside_maths(line, keyword=True)]


@reading("reply numbers")
def _reply_numbers() -> Reading:
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import reply_numbers

    classifier = Classifier.load([], [])
    where = "round 1, reviewer-1 point 1.1, `response`"

    def read(text: str) -> dict[str, Any]:
        """What G2 says of a reply to a reviewer, with no result to bind to."""
        return _told(reply_numbers(text, ROUND, where, classifier, {}))

    return read


@reading("quoted")
def _as_quoted() -> Reading:
    from manuscript_guard.gates.revision import as_quoted

    return as_quoted


@reading("quotation")
def _quotation() -> Reading:
    from manuscript_guard.literature.sources import contains, normalise, states_value

    def quotation(given: dict[str, str]) -> dict[str, Any]:
        source, quote, value = given["source"], given["quote"], given["value"]
        return {
            "read as": normalise(source),
            "found": contains(source, quote),
            "states": states_value(quote, value),
        }

    return quotation


@reading("pdf figure")
def _pdf_figure() -> Reading:
    """The fonts, texts and lines of a PDF figure as G4 reads them: each text's height and
    each line's width in points, through every transform and form, and the page's width."""
    from manuscript_guard.gates.figure_pdf import parse_pdf

    def marks(document: str) -> dict[str, Any] | None:
        figure = parse_pdf(document.encode("latin-1"))
        if figure is None:
            return None
        return {
            "width": figure.width_pt,
            "fonts": [[f.name, f.subtype, f.embedded] for f in figure.fonts],
            "texts": [[text, f"{size:.9g}"] for text, size in figure.texts],
            "lines": [f"{width:.9g}" for width in figure.lines],
        }

    return marks


# --------------------------------------------------------------------------- placeholders


@reading("placeholders")
def _placeholders() -> Reading:
    from manuscript_guard.gates.writing import artefacts_in, load_rules

    def placeholders(text: str) -> dict[str, Any]:
        """What G6's artefact rules find in a text, read as the manuscript and as the text
        of a figure, a caption or a reference: each rule, where, and what it matched."""
        rules = load_rules()
        return {
            side: [
                [rule["id"], match.start(), match.group(0)]
                for rule, match in artefacts_in(rules, text, manuscript=side == "manuscript")
            ]
            for side in ("manuscript", "elsewhere")
        }

    return placeholders


@reading("residue")
def _residue() -> Reading:
    from manuscript_guard.gates.writing import load_rules, residue_in

    def residue(text: str) -> list[list[Any]]:
        """What G6's residue rules find in a text: each rule, whether it fails at
        submission, where, and what it matched."""
        return [
            [rule["id"], bool(rule.get("self_reference")), match.start(), match.group(0)]
            for rule, match in residue_in(load_rules(), text)
        ]

    return residue


@reading("vector figure")
def _vector_figure() -> Reading:
    """The texts and lines of an SVG figure as G4 reads them: each text's height and each
    line's width in units, through every transform, where each text is anchored, and the
    visible area."""
    from manuscript_guard.gates.figure_svg import parse_svg

    def marks(document: str) -> dict[str, Any] | None:
        svg = parse_svg(document)
        if svg is None:
            return None
        return {
            "texts": [[m.text, f"{m.units:.9g}", [f"{v:.9g}" for v in m.at]] for m in svg.texts],
            "lines": [f"{m.units:.9g}" for m in svg.lines],
            "view": None if svg.view is None else [f"{v:.9g}" for v in svg.view],
        }

    return marks


@reading("quote words")
def _quote_words() -> Reading:
    """The words a ledger quote holds beside its value, which G7 counts to say a quote that
    holds little more than the value."""
    from manuscript_guard.literature.sources import words_beside

    def quote_words(given: dict[str, Any]) -> list[str]:
        return words_beside(given["quote"], given["value"])

    return quote_words


@reading("quote placement")
def _quote_placement() -> Reading:
    """What G7 says of a quote its stored source does not hold exactly: how much of it the
    source holds in order, on which lines, and what stands in the way."""
    from manuscript_guard.literature.placement import place, said

    def placed(given: dict[str, str]) -> list[Any] | None:
        placement = place(given["source"], given["quote"])
        if placement is None:
            return None
        return [placement.found, list(placement.lines), said(placement)]

    return placed


@reading("suggested edit")
def _suggested_edit() -> Reading:
    """Where a reviewer's suggested edit is found in a text, as typed or as pandoc printed
    it, and whether its words are words: what `review --suggestions` places an edit by."""
    from manuscript_guard.suggestions import found_in, refused_words

    def placed(given: dict[str, str]) -> dict[str, Any]:
        return {
            "found": [list(span) for span in found_in(given["text"], given["old"])],
            "refused": refused_words(given["old"], given["new"]),
        }

    return placed


@reading("suggestion written")
def _suggestion_written() -> Reading:
    """A suggestion accepted in Word, written into its paragraph's source where its words
    are, as `import` writes it before it merges anything else the author changed there; or
    why it is not."""
    from manuscript_guard.suggestions import Words, write_in

    def written(given: dict[str, Any]) -> dict[str, Any]:
        tokens = [tuple(token) for token in given["tokens"]]
        result = write_in(given["source"], given["printed"], tokens,
                          [Words(given["old"], given["new"])])  # fmt: skip
        if isinstance(result, str):
            return {"refused": result}
        return {
            "source": result.source,
            "shown": result.shown,
            "tokens": [list(token) for token in result.tokens or ()],
        }

    return written


# -------------------------------------------------------------------- a whole project


@reading("check")
def _check() -> Reading:
    from manuscript_guard.cli import main
    from manuscript_guard.scaffold import init_project

    def check(given: dict[str, Any]) -> dict[str, Any]:
        """`check --json` on a new project with this manuscript and these settings typed
        into it. What it prints names files under a folder made for this one run, which
        is written `<project>` here, so that two runs say the same thing."""
        folder = Path(tempfile.mkdtemp(prefix="mg-reading-"))
        try:
            root = folder / "paper"
            init_project(root, "A study of reports")
            (root / MAIN).write_text(given["text"], encoding="utf-8", newline="")
            with (root / PAPER).open("a", encoding="utf-8", newline="") as paper:
                paper.write(given.get("settings", ""))
            before = _snapshot(root)
            printed, complaints = StringIO(), StringIO()
            with redirect_stdout(printed), redirect_stderr(complaints):
                code = main(
                    ["check", str(root), "--json", "--stage", given.get("stage", "design")]
                )
            # A `paper.yaml` that cannot be read ends the command with a sentence and
            # prints no report: nothing to parse, and that is its answer.
            said = json.loads(printed.getvalue()) if printed.getvalue().strip() else None
            found = {
                "exit": code,
                "said": _from_root(said, root),
                "complained": _from_root(complaints.getvalue(), root),
                "written": sorted(_changed(before, _snapshot(root))),
            }
            if folder.name in json.dumps(found):
                raise AssertionError(
                    "`check` printed the folder made for this run in a form this reading "
                    "does not know, so two runs of it could not be compared"
                )
            return found
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return check


def _from_root(said: Any, root: Path, *, written: str = "<project>") -> Any:
    """`said` with the folder `root` written `<project>` in every text it holds, in each
    way a path to it is spelt. Longest first: the resolved path can hold the other."""
    if isinstance(said, dict):
        return {key: _from_root(value, root, written=written) for key, value in said.items()}
    if isinstance(said, list):
        return [_from_root(value, root, written=written) for value in said]
    if not isinstance(said, str):
        return said
    forms = {str(root), str(root.resolve()), root.as_posix(), root.resolve().as_posix()}
    for form in sorted(forms, key=len, reverse=True):
        said = said.replace(form, written)
    return said


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {name for name in {*before, *after} if before.get(name) != after.get(name)}


# -------------------------------------------------------------------------- the round trip

#: The word a block of a generated paper is known by. No two blocks have the same one.
TAGS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")
_TABLE = "| Drug | Reports |\n|------|---------|\n| A | 12 |\n| B | 30 |"
#: What each kind of block says, with its own word in it. They read alike on purpose: the
#: wrong writes the reviews found were on papers whose blocks did.
SAYS = {
    "paragraph": "The {tag} reports of hepatic injury were counted once in each group.",
    "second paragraph": "The {tag} reports of hepatic injury are shown below for each group.",
    "heading": "The {tag} reports of hepatic injury",
    "quotation": "The {tag} reports of hepatic injury were counted once in each group.",
    "item": "The {tag} reports of hepatic injury were counted once in each group.",
    "caption": "The {tag} reports of hepatic injury in each group.",
    "lines": "The {tag} reports of hepatic injury were counted once in each group.",
    "div": "The {tag} reports of hepatic injury were counted once in each group.",
}
#: How each kind is typed. Only the first two are given an identifier by the build.
TYPED = {
    "paragraph": "{says}",
    "second paragraph": "{says}",
    "heading": "## {says}",
    "quotation": "> {says}",
    "item": "- {says}",
    "caption": _TABLE + "\n\n: {says}",
    "lines": "| {says}",
    "div": "::: {{.plain}}\n{says}\n:::",
}
#: The word a co-author changes in a block, and what they type for it. In every sentence.
WAS, NOW = "hepatic", "liver"
#: The word the author changes in the source after the build, where they change one.
AUTHOR_WAS, AUTHOR_NOW = "reports", "records"
#: What the author adds to the source after the build, where they add a paragraph.
ADDED = "A paragraph the author added since the build, about the india reports."

_WORD_PARAGRAPH = re.compile(r"<w:p\b.*?</w:p>", re.DOTALL)
_OPENS = re.compile(
    r"<w:p>(?:<w:pPr>.*?</w:pPr>)?(?P<mark>(?:<w:bookmark(?:Start|End)\b[^>]*/>)*)", re.DOTALL
)


def typed(block: dict[str, str]) -> str:
    """One block of a generated paper as it stands in the source."""
    return TYPED[block["kind"]].format(says=SAYS[block["kind"]].format(tag=block["tag"]))


def _edited_in_word(xml: str, in_word: list[list[str]]) -> str:
    """The document's XML after the co-author's session: each block they touched reworded,
    or deleted. A paragraph deleted in Word with Track Changes off leaves its bookmark
    behind, in front of the next paragraph ("deleted"); edited outside Word it goes with
    its bookmark ("deleted and gone"). The two are one document where there is no bookmark
    to leave or nowhere to leave it: for a block that has no identifier, and for the last
    paragraph of the document, whose bookmark is dropped here. What Word does with that
    last one has not been looked at."""
    for tag, did in in_word:
        paragraph = next(p for p in _WORD_PARAGRAPH.findall(xml) if f" {tag} " in p)
        at = xml.index(paragraph)
        if did == "reworded":
            xml = xml[:at] + paragraph.replace(WAS, NOW, 1) + xml[at + len(paragraph) :]
            continue
        xml = xml[:at] + xml[at + len(paragraph) :]
        opening = _OPENS.match(paragraph)
        following = xml.find("<w:p>", at)
        if did == "deleted" and opening and opening["mark"] and following != -1:
            into = _OPENS.match(xml, following)
            xml = xml[: into.start("mark")] + opening["mark"] + xml[into.start("mark") :]
    return xml


@reading("import")
def _import() -> Reading:
    if shutil.which("pandoc") is None:
        raise Unavailable("pandoc is not installed, and a document is built with it")
    from manuscript_guard.cli import main
    from manuscript_guard.scaffold import init_project

    def round_trip(given: dict[str, Any]) -> dict[str, Any]:
        """A paper typed into a new project, built, edited in Word, and imported: the
        source as the import found it, as it left it, and what was said.

        `blocks` are the paper, `in_word` what the co-author did to which block, and
        `since` what the author did to the source after the build, if anything; with a
        change since, the import is forced, as a stale one has to be."""
        folder = Path(tempfile.mkdtemp(prefix="mg-reading-"))
        try:
            root = folder / "paper"
            init_project(root, "A study of reports")
            path = root / MAIN
            header = path.read_text(encoding="utf-8")
            header = header[: header.index("\n---\n") + len("\n---\n")]

            def write(blocks: list[str]) -> None:
                text = header + "\n" + "\n\n".join(blocks) + "\n"
                path.write_text(text, encoding="utf-8", newline="\n")

            built = [typed(block) for block in given["blocks"]]
            now = list(built)
            if given.get("since"):
                did, tag = given["since"]
                at = next(i for i, block in enumerate(given["blocks"]) if block["tag"] == tag)
                if did == "reworded":
                    now[at] = now[at].replace(AUTHOR_WAS, AUTHOR_NOW, 1)
                elif did == "removed":
                    del now[at]
                else:
                    now.insert(at, ADDED)

            said = StringIO()
            write(built)
            with redirect_stdout(said), redirect_stderr(said):
                code = main(["build", str(root), "--offline", "--skip-checks"])
                if code != 0:
                    return {"built": code, "said": _named(said.getvalue(), root, folder)}
                (document,) = (root / "build").glob("manuscript*.docx")
                returned = folder / "returned.docx"
                with zipfile.ZipFile(document) as sent, zipfile.ZipFile(returned, "w") as back:
                    for item in sent.infolist():
                        data = sent.read(item.filename)
                        if item.filename == "word/document.xml":
                            xml = _edited_in_word(data.decode("utf-8"), given["in_word"])
                            data = xml.encode("utf-8")
                        back.writestr(item, data)
                write(now)
                before = path.read_text(encoding="utf-8")
                forced = ["--force"] if now != built else []
                code = main(["import", str(returned), str(root), "--apply", *forced])
            found = {
                "exit": code,
                "before": before,
                "after": path.read_text(encoding="utf-8"),
                "said": _named(said.getvalue(), root, folder),
            }
            if folder.name in json.dumps(found):
                raise AssertionError(
                    "the import printed the folder made for this run in a form this reading "
                    "does not know, so two runs of it could not be compared"
                )
            return found
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return round_trip


def _named(said: str, root: Path, folder: Path) -> str:
    return _from_root(_from_root(said, root), folder, written="<folder>")


# ---------------------------------------------------------------------- the marked-up copy

_WML = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
#: The pictures a generated figure shows, by name: four pixels of one colour.
PICTURES = {"red": (255, 0, 0), "blue": (0, 0, 255)}
#: How a run of a generated document looks, by the letter a block's run is given.
_LOOKS = {"": "", "i": "<w:i/>", "b": "<w:b/>"}


def _png(colour: tuple[int, int, int]) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + bytes(colour) * 2 for _ in range(2))
    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )  # fmt: skip


def _xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _runs_xml(runs: list[list[str]]) -> str:
    return "".join(
        f'<w:r>{"<w:rPr>" + _LOOKS[look] + "</w:rPr>" if look else ""}'
        f'<w:t xml:space="preserve">{_xml_text(text)}</w:t></w:r>'
        for text, look in runs
    )


def document_of(blocks: list[dict[str, Any]], path: Path) -> Path:
    """A Word document of `blocks`, laid out as pandoc lays one out: a paragraph (`runs`,
    each its text and how it looks, a `style`, in a `list` or not, with a `note` at its
    end or not), a `table` of rows of cells, or a `figure` showing one of `PICTURES`."""
    body: list[str] = []
    notes: list[str] = []
    pictures: dict[str, str] = {}
    for number, block in enumerate(blocks, start=1):
        if block["kind"] == "table":
            columns = len(block["rows"][0])
            grid = '<w:gridCol w:w="2000"/>' * columns
            rows = "".join(
                "<w:tr>" + "".join(
                    '<w:tc><w:tcPr/><w:p><w:pPr><w:pStyle w:val="Compact"/></w:pPr>'
                    + _runs_xml([[cell, ""]]) + "</w:p></w:tc>"
                    for cell in row
                ) + "</w:tr>"
                for row in block["rows"]
            )  # fmt: skip
            body.append(
                f'<w:tbl><w:tblPr><w:tblStyle w:val="Table"/></w:tblPr><w:tblGrid>{grid}'
                f"</w:tblGrid>{rows}</w:tbl>"
            )
            continue
        if block["kind"] == "figure":
            rid = pictures.setdefault(block["picture"], f"rIdPicture{len(pictures) + 1}")
            body.append(
                '<w:p><w:pPr><w:pStyle w:val="CaptionedFigure"/></w:pPr><w:r><w:drawing>'
                '<wp:inline><wp:extent cx="91440" cy="91440"/>'
                f'<wp:docPr id="{number}" name="Picture"/><a:graphic><a:graphicData '
                'uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>'
                f'<pic:nvPicPr><pic:cNvPr id="0" name="{block["picture"]}.png"/>'
                f'<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{rid}"/>'
                '</pic:blipFill><pic:spPr/></pic:pic></a:graphicData></a:graphic>'
                "</wp:inline></w:drawing></w:r></w:p>"
            )  # fmt: skip
            continue
        style = block.get("style") or ("Compact" if block.get("list") else "BodyText")
        listed = (
            '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
            if block.get("list") else ""
        )  # fmt: skip
        reference = ""
        if block.get("note"):
            note = len(notes) + 1
            notes.append(
                f'<w:footnote w:id="{note}"><w:p><w:pPr><w:pStyle w:val="FootnoteText"/>'
                '</w:pPr><w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                f"<w:footnoteRef/></w:r>{_runs_xml([[' ', '']] + block['note'])}</w:p>"
                "</w:footnote>"
            )  # fmt: skip
            reference = (
                '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                f'<w:footnoteReference w:id="{note}"/></w:r>'
            )
        body.append(
            f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{listed}</w:pPr>'
            f'<w:bookmarkStart w:id="{number}" w:name="mg-p-main-{number}"/>'
            f'<w:bookmarkEnd w:id="{number}"/>{_runs_xml(block["runs"])}{reference}</w:p>'
        )
    namespaces = (
        f'xmlns:w="{_WML}" xmlns:r="{_RELS}" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'
    )
    document = f"<w:document {namespaces}><w:body>{''.join(body)}<w:sectPr/></w:body></w:document>"
    footnotes = (
        f'<w:footnotes xmlns:w="{_WML}" xmlns:r="{_RELS}">'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p>'
        '</w:footnote><w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:r>'
        f"<w:continuationSeparator/></w:r></w:p></w:footnote>{''.join(notes)}</w:footnotes>"
    )  # fmt: skip
    styles = (
        f'<w:styles xmlns:w="{_WML}"><w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="BodyText"><w:name w:val="Body Text"/>'
        '</w:style><w:style w:type="paragraph" w:styleId="Compact"><w:name w:val="Compact"/>'
        "</w:style></w:styles>"
    )  # fmt: skip
    numbering = (
        f'<w:numbering xmlns:w="{_WML}"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
        '<w:numFmt w:val="bullet"/><w:lvlText w:val="-"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    )  # fmt: skip
    package = "http://schemas.openxmlformats.org/package/2006"
    office = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    types = (
        f'<Types xmlns="{package}/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        f'<Override PartName="/word/document.xml" ContentType="{office}.document.main+xml"/>'
        f'<Override PartName="/word/footnotes.xml" ContentType="{office}.footnotes+xml"/>'
        f'<Override PartName="/word/styles.xml" ContentType="{office}.styles+xml"/>'
        f'<Override PartName="/word/numbering.xml" ContentType="{office}.numbering+xml"/>'
        "</Types>"
    )  # fmt: skip
    kinds = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    relationships = "".join(
        f'<Relationship Id="{rid}" Type="{kinds}/image" Target="media/{name}.png"/>'
        for name, rid in pictures.items()
    ) + "".join(
        f'<Relationship Id="rId{kind}" Type="{kinds}/{kind}" Target="{kind}.xml"/>'
        for kind in ("footnotes", "styles", "numbering")
    )  # fmt: skip
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", types)
        out.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{package}/relationships"><Relationship Id="rId1" '
            f'Type="{kinds}/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        out.writestr(
            "word/_rels/document.xml.rels",
            f'<Relationships xmlns="{package}/relationships">{relationships}</Relationships>',
        )
        out.writestr("word/document.xml", document)
        out.writestr("word/footnotes.xml", footnotes)
        out.writestr("word/styles.xml", styles)
        out.writestr("word/numbering.xml", numbering)
        for name in pictures:
            out.writestr(f"word/media/{name}.png", _png(PICTURES[name]))
    return path


def _looked(pieces: list[tuple[str, str]]) -> str:
    """Text with how it looks marked, character by character, so that two runs that look
    alike read as one: `*` around italics, `**` around bold."""
    out, now = [], ""
    for text, look in pieces:
        for char in text:
            if look != now:
                out.append({"i": "*", "b": "**"}.get(now, "") + {"i": "*", "b": "**"}.get(look, ""))
                now = look
            out.append(char)
    out.append({"i": "*", "b": "**"}.get(now, ""))
    return "".join(out)


def plain_of(blocks: list[dict[str, Any]]) -> list[str]:
    """What a generated document reads as, as `read_plainly` reads one: a line for each
    paragraph, each row of a table and each figure, then each note."""
    lines: list[str] = []
    notes: list[str] = []
    for block in blocks:
        if block["kind"] == "table":
            lines += [" | ".join(row) for row in block["rows"]]
        elif block["kind"] == "figure":
            lines.append(f"(picture {block['picture']})")
        else:
            lines.append(_looked([(text, look) for text, look in block["runs"]]))
            if block.get("note"):
                notes.append(_looked([(" ", "")] + [(t, k) for t, k in block["note"]]).strip())
    return lines + [f"note: {note}" for note in notes]


def _embedded(drawing: Any) -> str:
    """The relationship id of the picture a drawing shows."""
    key = f"{{{_RELS}}}embed"
    return next(node.get(key) for node in drawing.iter() if node.get(key))


def _look_of(properties: Any) -> str:
    if properties is None:
        return ""
    if properties.find(f"{{{_WML}}}i") is not None:
        return "i"
    return "b" if properties.find(f"{{{_WML}}}b") is not None else ""


def read_plainly(document: Path, *, accept: bool) -> list[str]:
    """A document read as Word shows it with every tracked change accepted, or every one
    rejected: by this file's own reading of the XML, which owes nothing to the package's."""
    from xml.etree import ElementTree as ET

    w = f"{{{_WML}}}"
    gone = w + ("del" if accept else "ins")
    with zipfile.ZipFile(document) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        notes_root = ET.fromstring(archive.read("word/footnotes.xml"))
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        media = {name: archive.read(name) for name in archive.namelist() if "media/" in name}
    colours = {_png(colour): name for name, colour in PICTURES.items()}
    targets = {rel.get("Id"): rel.get("Target") for rel in rels}

    def look(run: Any) -> str:
        properties = run.find(w + "rPr")
        change = None if properties is None else properties.find(w + "rPrChange")
        if not accept and change is not None:
            return _look_of(change.find(w + "rPr"))
        return _look_of(properties)

    def pieces(node: Any) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for child in node:
            if child.tag == gone or child.tag in (w + "pPr", w + "rPr"):
                continue
            if child.tag == w + "r":
                for inner in child:
                    if inner.tag in (w + "t", w + "delText"):
                        out.append((inner.text or "", look(child)))
                    elif inner.tag == w + "drawing":
                        data = media.get("word/" + targets.get(_embedded(inner), ""), b"")
                        out.append((f"(picture {colours.get(data, '?')})", ""))
            else:
                out += pieces(child)
        return out

    def mark_gone(paragraph: Any) -> bool:
        mark = paragraph.find(f"{w}pPr/{w}rPr")
        return mark is not None and mark.find(gone) is not None

    lines: list[str] = []
    for block in root.find(w + "body"):
        if block.tag == w + "p":
            line = _looked(pieces(block))
            if line or not mark_gone(block):
                lines.append(line)
        elif block.tag == w + "tbl":
            for row in block.findall(w + "tr"):
                properties = row.find(w + "trPr")
                if properties is not None and properties.find(gone) is not None:
                    continue
                lines.append(" | ".join(_looked(pieces(cell)) for cell in row.findall(w + "tc")))
    by_id = {n.get(w + "id"): n for n in notes_root.findall(w + "footnote")}
    for reference in root.iter(w + "footnoteReference"):
        holder = next(
            (r for r in root.iter() if reference in list(r)), None
        )  # the run that holds it
        if holder is None:
            continue
        wrapper = next((p for p in root.iter() if holder in list(p)), None)
        if wrapper is not None and wrapper.tag == gone:
            continue
        note = by_id[reference.get(w + "id")]
        lines.append("note: " + " ".join(_looked(pieces(p)) for p in note.findall(w + "p")).strip())
    return [line for line in lines if line]


def shown(document: Path) -> list[str]:
    """A marked-up copy as one line for each paragraph, row and note, its changes marked:
    `[-...-]` deleted, `{+...+}` inserted, `~...~` reformatted, `¶-` and `¶+` a paragraph's
    mark deleted or inserted, `row-` and `row+` a row."""
    from xml.etree import ElementTree as ET

    w = f"{{{_WML}}}"
    with zipfile.ZipFile(document) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        notes_root = ET.fromstring(archive.read("word/footnotes.xml"))
        rels = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
        media = {name: archive.read(name) for name in archive.namelist() if "media/" in name}
    colours = {_png(colour): name for name, colour in PICTURES.items()}
    targets = {rel.get("Id"): rel.get("Target") for rel in rels}

    def text(node: Any) -> str:
        out = []
        for child in node:
            if child.tag == w + "ins":
                out.append("{+" + text(child) + "+}")
            elif child.tag == w + "del":
                out.append("[-" + text(child) + "-]")
            elif child.tag == w + "r":
                properties = child.find(w + "rPr")
                said = ""
                for inner in child:
                    if inner.tag in (w + "t", w + "delText"):
                        said += inner.text or ""
                    elif inner.tag == w + "drawing":
                        data = media.get("word/" + targets.get(_embedded(inner), ""), b"")
                        said += f"(picture {colours.get(data, '?')})"
                    elif inner.tag == w + "footnoteReference":
                        said += "^"
                changed = properties is not None and properties.find(w + "rPrChange") is not None
                out.append(f"~{said}~" if changed else said)
            elif child.tag not in (w + "pPr",):
                out.append(text(child))
        return "".join(out)

    def mark(paragraph: Any) -> str:
        styled = "style " if paragraph.find(f"{w}pPr/{w}pPrChange") is not None else ""
        found = paragraph.find(f"{w}pPr/{w}rPr")
        if found is None:
            return styled
        if found.find(w + "del") is not None:
            return styled + "\N{PILCROW SIGN}- "
        return styled + ("\N{PILCROW SIGN}+ " if found.find(w + "ins") is not None else "")

    lines = []
    for block in root.find(w + "body"):
        if block.tag == w + "p":
            lines.append(mark(block) + text(block))
        elif block.tag == w + "tbl":
            for row in block.findall(w + "tr"):
                properties = row.find(w + "trPr")
                kind = ""
                if properties is not None and properties.find(w + "del") is not None:
                    kind = "row- "
                elif properties is not None and properties.find(w + "ins") is not None:
                    kind = "row+ "
                lines.append(kind + " | ".join(text(c) for c in row.findall(w + "tc")))
    for note in notes_root.findall(w + "footnote"):
        if note.get(w + "type") is None:
            lines.append("note: " + " ".join(text(p) for p in note.findall(w + "p")).strip())
    return lines


@reading("marked up")
def _marked_up() -> Reading:
    """The marked-up copy of a generated revision: as it shows its changes, and as it reads
    accepted and rejected (`read_plainly`). What `build --marked-up` writes."""
    from manuscript_guard.markedup import write

    def marked_up(given: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            before = document_of(given["before"], folder / "before.docx")
            after = document_of(given["after"], folder / "after.docx")
            made = write(before, after, folder / "marked.docx", date="2026-10-21")
            return {
                "shown": shown(made.path),
                "accepted": read_plainly(made.path, accept=True),
                "rejected": read_plainly(made.path, accept=False),
                "counts": made.counts,
            }

    return marked_up


# ------------------------------------------------------------------- as a process of its own


def serve() -> None:
    """Answer for the package on the path until the questions end: a line of JSON in, a
    line of JSON out. The first line out says which package was found, which readings it
    does not have and which it has and cannot make (`why_not`), so that whoever asks can
    refuse an answer from the wrong source and tell nothing to compare from a comparison
    that could not be made.

    Answers go to the standard output as it was when the process began. Everything a
    reading prints after that goes to the standard error, where it cannot be taken for one.
    """
    import os
    import sys

    answers = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="ascii", newline="\n")
    sys.stdout = sys.stderr

    import manuscript_guard

    found: dict[str, Reading] = {}
    lacking: dict[str, dict[str, str]] = {"absent": {}, "broken": {}}
    for name, find in READINGS.items():
        try:
            found[name] = find()
        except Exception as raised:  # noqa: BLE001 - told apart by `why_not`
            lacking[why_not(raised)][name] = f"{type(raised).__name__}: {raised}"

    def say(told: dict[str, Any]) -> None:
        answers.write(json.dumps(told, ensure_ascii=True, sort_keys=True) + "\n")
        answers.flush()

    say({"package": str(Path(manuscript_guard.__file__).resolve().parent), **lacking})
    for line in sys.stdin.buffer:
        asked = json.loads(line)
        name = asked["reading"]
        if name in found:
            say(answer(found[name], asked["given"]))
        elif name in lacking["broken"]:
            say({"broken": lacking["broken"][name]})
        else:
            say({"absent": lacking["absent"].get(name, "no reading has that name")})


if __name__ == "__main__":
    serve()
