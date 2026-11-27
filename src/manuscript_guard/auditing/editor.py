"""The editor's report: what `audit --editor` prints, each finding in one of four parts.

A journal's editor reads a submission for one decision and a letter, and has a few minutes for
it. So the same audit is said in four parts, each finding put in one by its code from one
table, `KINDS` (Basile, 2026-11-25):

- **Look at before you decide**: a number or a record that cannot be right as printed, or a
  sign the submission was tampered with; exact checks, or measured right three times in four.
- **Ask the authors**: what the authors can fix or answer in a line, the journal's rules and
  the reference list among it.
- **For copyediting**: spelling, notation, abbreviations and phrasing, each kind in a line.
- **What the check read**: what was read, what could not be and what was not checked, always
  there, so that the report never reads as a clean bill.

The self-citation counts stand in the summary line at the top, in no part, so that they are
never read as a problem. Each kind of the first three parts says how often its findings were
right on the corpus of published papers (`docs/corpus.md`) where ten or more were judged, and
that it was not yet measured where not (the author's answer of 2026-11-25). A kind is said in
the editor's words, with no gate and no option; the full report is the same audit without
`--editor`. Three codes are parted by what the finding holds rather than by the code alone:
`over-header-n` by its severity, G6's `model-artefact` by its rule, and `document-holds` by
what the Word file holds. A code the table does not name is put to the authors (`FURTHER`),
and `tests/test_audit_editor.py` holds the table to every code the audit makes.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import FAIL

LOOK, ASK, COPYEDIT, READ = "look", "ask", "copyedit", "read"
#: Where a kind is said in the summary line, in no part.
SUMMARY = "summary"
#: The parts, in the order the report gives them.
PARTS = ((LOOK, "Look at before you decide"), (ASK, "Ask the authors"),
         (COPYEDIT, "For copyediting"), (READ, "What the check read"))  # fmt: skip
#: How the summary line counts each part.
COUNTED = {LOOK: "to look at before you decide", ASK: "to ask the authors",
           COPYEDIT: "for copyediting"}  # fmt: skip
#: What the report says under its counts, every time.
SCOPE = ("This check reads the paper's numbers, its words and its reference list, and, given "
         "the journal's profile, the journal's rules. It does not judge the science.")  # fmt: skip

#: The corpus run the records were counted on: main of 2026-11-24 (`tools/corpus.py measure`).
#: A record is the findings judged true of those judged, among those the report gives as a
#: warning or a failure, or, for a kind the audit gives as a note, among its notes.
RUN = "main-cc1af1f14"
#: How many judged findings a record needs before it is shown.
SHOWN_FROM = 10
#: How many notes of one kind of what the check read are listed without `--details`.
READ_LISTED = 5

_HIDES = ("hidden", "unseen", "zero_width", "to_a_model")
_TRACKS = ("insertions", "deletions", "moves", "comments")


@dataclass(frozen=True)
class Kind:
    """One kind of finding as the editor reads it: its part, what it says, the codes, each
    with its gate, whose findings are of it, and its record on the corpus, true of judged.
    `holds`, for a code parted between kinds, says whether a finding of it is of this one."""

    name: str
    part: str
    says: str
    codes: frozenset[tuple[str, str]]
    record: tuple[int, int] | None = None
    holds: Callable[[object, object], bool] | None = None
    #: Whether a finding is said as the number it is about and the words around it, where
    #: its message only repeats what the kind says.
    quoted: bool = False


def _codes(gate: str, *codes: str) -> frozenset[tuple[str, str]]:
    return frozenset((gate, code) for code in codes)


def _failed(item, _report) -> bool:
    return item.severity == FAIL


#: G6's rules that find a bare placeholder: a thing named in brackets, "[url]"
#: (`placeholder-slot`), and a word that marks a gap, "XXXX", "TBD" (`placeholder-word`).
BARE_PLACEHOLDERS = frozenset({"placeholder-slot", "placeholder-word"})
#: The words `placeholder-word` finds that tell the writer what to do rather than mark a gap,
#: "TODO", "INSERT_SOURCE_URL": text left for the writer, asked of the authors.
TO_DO = ("todo", "fixme", "insert_", "paste_")


def _bare(item, _report) -> bool:
    """A bare placeholder ("XXXX", "[url]"), in a blinded submission often a detail taken out
    for review: G6's rule is the part of the finding's subject before its colon
    (`gates.writing`), "placeholder-word: xxxx"."""
    rule, _, words = (getattr(item, "subject", None) or "").partition(":")
    return rule in BARE_PLACEHOLDERS and not words.strip().lower().startswith(TO_DO)


def _facts(item, report):
    return next((facts for facts in getattr(report, "documents", None) or []
                 if Path(facts.path) == Path(item.path or "")), None)  # fmt: skip


def _hides(item, report) -> bool:
    """A Word file that holds text a reader does not see, or text addressed to a model."""
    facts = _facts(item, report)
    return facts is not None and any(getattr(facts, name) for name in _HIDES)


def _tracks(item, report) -> bool:
    """A Word file that holds tracked changes or comments."""
    facts = _facts(item, report)
    return facts is not None and any(getattr(facts, name) for name in _TRACKS)


_PACKAGE_DIFFERS = ("package-file-missing", "package-file-changed", "package-manifest-invalid",
                    "package-sums-differ", "package-result-edited", "package-result-not-by-script",
                    "package-script-missing", "package-receipt-differs",
                    "package-receipt-output-differs", "package-verification-differs")
_PACKAGE_INCOMPLETE = ("package-file-unlisted", "package-checks-skipped",
                       "package-result-no-digest", "package-result-unpinned",
                       "package-sums-missing", "package-receipt-not-packaged",
                       "package-result-unreadable", "package-verification-unreadable")
_PACKAGE_READ = ("package-withheld", "package-verification-quoted", "package-no-results")

KINDS: tuple[Kind, ...] = (
    # ---------------------------------------------------------- look at before you decide
    Kind("numbers-disagree", LOOK,
         "Two numbers that cannot both be right as printed: a P value and its test statistic, "
         "an estimate outside its own interval, a share that does not match its counts, a mean "
         "impossible for whole-number data.", _codes("audit", "does-not-fit"), (13, 13)),
    Kind("total-off", LOOK, "A table's rows do not add up to the total it prints.",
         _codes("audit", "sum-off")),
    Kind("over-n", LOOK, "A count larger than the n its column's header gives.",
         _codes("audit", "over-header-n"), holds=_failed),
    Kind("flow-broken", LOOK,
         "A participant flow whose numbers do not add up from one step to the next.",
         _codes("audit", "flow-broken")),
    Kind("impossible-spread", LOOK,
         "An SD impossible for its mean and n in whole-number data, or a mean and SD impossible "
         "for yes-or-no data.", _codes("audit", "sd-not-possible", "binary-not-possible")),
    Kind("abstract-conflict", LOOK,
         "The Abstract and the Results give different numbers for the same result.",
         _codes("audit", "abstract-conflict")),
    Kind("not-in-outputs", LOOK,
         "A number in the paper that is in none of the results files the authors supplied.",
         _codes("audit", "not-found")),
    Kind("retracted", LOOK,
         "A cited work that was retracted or withdrawn, or is under an expression of concern.",
         _codes("G7", "reference-retracted", "reference-under-concern", "preprint-withdrawn")),
    Kind("hidden-text", LOOK,
         "Text in the Word file that a reader does not see, or text addressed to an AI "
         "reviewer, which may be there to steer the review.", _codes("audit", "document-holds"),
         holds=_hides),
    Kind("package-differs", LOOK,
         "The authors' package does not match its own manifest, or a result was not written by "
         "the script packaged beside it.", _codes("audit", *_PACKAGE_DIFFERS)),
    # ---------------------------------------------------------- ask the authors
    Kind("skewed", ASK,
         "A mean smaller than twice its SD for a measure that cannot be negative: the data are "
         "skewed, and a median with its interquartile range would describe them better.",
         _codes("audit", "mean-sd-skewed")),
    Kind("p-adjusted", ASK,
         "A P value that looks adjusted for multiple comparisons, with no adjustment named.",
         _codes("audit", "question-p-adjusted")),
    Kind("share-weighted", ASK,
         "A percentage that fits its counts only if it was weighted, with no weighting named.",
         _codes("audit", "question-share-weighted")),
    Kind("abstract-not-found", ASK,
         "A number in the Abstract that the check could not find in the Results or the tables.",
         _codes("audit", "abstract-not-found"), (11, 26), quoted=True),
    Kind("abstract-elsewhere", ASK,
         "A number in the Abstract found only in the Introduction or the Discussion.",
         _codes("audit", "question-number-only-in")),
    Kind("abstract-unsourced", ASK,
         "A number in the Abstract's background with no source cited.",
         _codes("audit", "question-background-unsourced")),
    Kind("small-count", ASK,
         "A small count the authors held back that can be worked out from the totals beside "
         "it, which can identify a participant.", _codes("G2", "count-recoverable")),
    Kind("identifier-unknown", ASK,
         "A DOI or PubMed ID that no registry knows: a typo, or a reference that does not "
         "exist.", _codes("G7", "doi-unregistered", "pmid-unknown", "not-found-as-printed")),
    Kind("not-found-by-title", ASK,
         "An article with no DOI that Crossref could not find by its title and first author.",
         _codes("G7", "not-found-by-title")),
    Kind("preprint-published", ASK,
         "A cited preprint that has since been published in a journal.",
         _codes("G7", "preprint-published")),
    Kind("never-cited", ASK, "An entry of the reference list that the text never cites.",
         _codes("G7", "entry-never-cited")),
    Kind("beyond-list", ASK,
         "A citation that names no entry of the reference list.",
         _codes("G7", "citation-beyond-list", "citation-not-listed")),
    Kind("left-in", ASK,
         "Text left from a template or for the writer, or a chatbot's own words, to take out; "
         "and the statement on the use of AI to ask for.", _codes("G6", "model-artefact")),
    Kind("over-limit", ASK,
         "Over the journal's limit on words, figures, tables, references or keywords.",
         _codes("G4", "over-journal-limit")),
    Kind("required-missing", ASK,
         "A section or a statement the journal requires that the check did not find.",
         _codes("G4", "missing-required-statement", "missing-required-section")),
    Kind("abstract-form", ASK,
         "No Abstract under its heading, or a structured abstract without a heading the "
         "journal requires.",
         _codes("G4", "missing-abstract", "abstract-not-found", "abstract-headings-missing")),
    Kind("data-statement", ASK,
         "A data availability statement the journal's policy does not accept, one with no "
         "identifier or with a temporary link, or a dataset's DOI the references do not list.",
         _codes("G4", "data-statement-forbidden", "data-identifier-missing",
                "data-link-temporary", "data-doi-uncited")),
    Kind("boxes", ASK,
         "A box the journal prints beside the abstract, or a graphical abstract, missing, "
         "headed otherwise, or past the journal's limits on its items and words.",
         _codes("G4", "box-missing", "box-heading-invalid", "box-headings-missing", "box-items",
                "box-item-long", "box-over-limit", "graphical-abstract-missing")),
    Kind("tracked", ASK, "Tracked changes or comments left in the Word file.",
         _codes("audit", "document-holds"), holds=_tracks),
    Kind("blind-named", ASK,
         "An author named in a document of a blind submission: a name, an ORCID iD, an e-mail "
         "address or an affiliation.", _codes("audit", "blind-document-names-author")),
    Kind("causal", ASK,
         "A sentence that claims a cause where an observational study can show an "
         "association.", _codes("audit", "causal-word-observational")),
    Kind("baseline-p", ASK,
         "A table of baseline characteristics with a column of P values, which CONSORT "
         "advises against.", _codes("audit", "baseline-p-values")),
    Kind("display-order", ASK,
         "A table or a figure cited nowhere in the text, numbered out of the order of its "
         "first citation, or pointed at though the paper has no legend for it (ICMJE).",
         _codes("G2", "cited-out-of-order", "display-not-cited", "pointer-to-nothing")),
    Kind("package-incomplete", ASK,
         "A file the package's manifest does not list, checks the package says were skipped, "
         "or a result the package cannot tie to its digest.",
         _codes("audit", *_PACKAGE_INCOMPLETE)),
    # ---------------------------------------------------------- for copyediting
    Kind("abbreviation-redefined", COPYEDIT, "An abbreviation defined a second time.",
         _codes("G14", "abbreviation-redefined"), (410, 492)),
    Kind("abbreviation-unused", COPYEDIT, "An abbreviation defined and not used again.",
         _codes("G14", "abbreviation-unused"), (236, 278)),
    Kind("abbreviation-early", COPYEDIT, "An abbreviation used before its definition.",
         _codes("G14", "abbreviation-used-before-defined"), (115, 174)),
    Kind("abbreviation-undefined", COPYEDIT,
         "Abbreviations never defined, which readers may or may not know.",
         _codes("G14", "abbreviation-undefined"), (72, 363)),
    Kind("spelling-variant", COPYEDIT, "A word spelt in the other English.",
         _codes("G14", "spelling-variant"), (133, 147)),
    Kind("spelling-mixed", COPYEDIT, "A word spelt in both Englishes.",
         _codes("G14", "spelling-mixed"), (9, 10)),
    Kind("spelling-declared", COPYEDIT, "A word spelt otherwise than the English chosen.",
         _codes("G14", "spelling-not-as-declared")),
    Kind("p-symbol", COPYEDIT, "P written two ways.", _codes("G14", "notation-p-symbol"),
         (18, 20)),
    Kind("sign-spacing", COPYEDIT, "Signs such as = and < spaced two ways.",
         _codes("G14", "notation-sign-spacing"), (35, 37)),
    Kind("interval-form", COPYEDIT, "Intervals written two ways.",
         _codes("G14", "notation-interval")),
    Kind("percent-form", COPYEDIT, "Percentages written two ways.",
         _codes("G14", "notation-percent")),
    Kind("unit-spacing", COPYEDIT, "A number run into its unit.",
         _codes("G14", "notation-unit"), (12, 18)),
    Kind("space-missing", COPYEDIT, "A number and a word run together.",
         _codes("G14", "notation-space-missing")),
    Kind("code-name", COPYEDIT, "A variable's name from the analysis code written in the text.",
         _codes("G14", "code-name-in-prose"), (39, 43)),
    Kind("vocabulary", COPYEDIT, "A word the paper's own vocabulary avoids or defines otherwise.",
         _codes("G14", "term-avoided", "vocabulary-conflict")),
    Kind("stock-phrase", COPYEDIT, "A stock phrase to tighten.", _codes("G6", "ai-phrasing"),
         (104, 130)),
    Kind("cadence", COPYEDIT, "Sentences of one length and rhythm, to vary.",
         _codes("G6", "ai-cadence"), (25, 28)),
    Kind("vague-attribution", COPYEDIT, "“Studies have shown” with no study named.",
         _codes("G6", "vague-attribution"), (5, 14)),
    Kind("revision-words", COPYEDIT, "Words left from a revision, such as “as the reviewer "
         "asked”.", _codes("G6", "revision-residue")),
    Kind("placeholder", COPYEDIT,
         "A bare placeholder, such as “XXXX” or “[url]”, in a blinded "
         "submission often a detail taken out for review.", _codes("G6", "model-artefact"),
         (1, 12), holds=_bare),
    Kind("abstract-rounded", COPYEDIT,
         "A number in the Abstract found in the Results only rounded another way.",
         _codes("audit", "abstract-rounded")),
    # ---------------------------------------------------------- what the check read
    Kind("unread", READ, "What could not be read.",
         _codes("audit", "unreadable", "output-not-read", "nothing-read")),
    Kind("reading", READ, "What was read, and how.",
         _codes("audit", "not-audited", "headings-read", "passed-over",
                "not-found-on-a-reference-line") | _codes("G14", "abbreviations-passed-over")),
    Kind("abstract-unplaced", READ,
         "Where the check could not tell the Abstract or the Results, and the answers given.",
         _codes("audit", "question-no-abstract", "question-no-results", "abstract-not-compared",
                "abstract-answer-contradicted", "results-heading-unmatched",
                "results-heading-not-read", "results-heading-reports-nothing")),
    Kind("undecided", READ, "Numbers the check could not decide.",
         _codes("audit", "over-header-n", "mean-not-assessable", "whole-numbers-unfound",
                "binary-unfound", "flow-note", "non-negative-unread", "non-negative-unfound")),
    Kind("references-read", READ, "How the references were read and looked up.",
         _codes("G7", "entries-not-told-apart", "identifier-not-sent", "would-ask", "looked-up",
                "lookup-unanswered", "reference-not-sorted", "title-not-searchable",
                "found-twice-by-title", "title-search-unanswered")),
    Kind("not-run", READ, "Checks of the writing that could not run, and why.",
         _codes("G6", "gates-not-run") | _codes("G14", "script-not-read", "tex-words-not-read",
                                                "no-headings")),
    Kind("by-hand", READ, "The journal's rules no check reads, to tick by hand.",
         _codes("G4", "journal-manual-rule")),
    Kind("journal-read", READ,
         "What could not be checked against the journal's rules, and limits nearly reached.",
         _codes("G4", "journal-not-checked", "journal-not-main-document", "journal-not-run",
                "near-journal-limit", "journal-profile-stale")),
    Kind("document-read", READ, "The names Word keeps, and what the Word file was read for.",
         _codes("audit", "document-holds", "document-person", "document-unreadable",
                "authors-not-looked-for")),
    Kind("design-unread", READ, "Where the causal words or the baseline tables were not read.",
         _codes("audit", "causal-words-not-read", "baseline-tables-not-read")),
    Kind("displays-unread", READ,
         "Where the tables or the figures could not be counted from their legends, and were "
         "not held to their order.", _codes("G2", "displays-not-counted")),
    Kind("cited", READ, "The table of cited sentences, and what it could not hold.",
         _codes("audit", "cited-written", "cited-not-listed", "would-ask")),
    Kind("self-citation-read", READ, "What the self-citation counts were read from.",
         _codes("audit", "self-citation-read", "self-citation-not-counted")),
    Kind("package-read", READ, "What the package withheld, and the authors' own check quoted.",
         _codes("audit", *_PACKAGE_READ)),
    # ---------------------------------------------------------- the summary line
    Kind("self-citation", SUMMARY,
         "How many references are the authors' own papers and the journal's own.",
         _codes("audit", "self-citation-author", "self-citation-journal")),
)

#: Where a finding of a code no kind names goes: to the authors, so that it is seen.
FURTHER = Kind("further", ASK, "Further findings.", frozenset())

_BY_CODE: dict[tuple[str, str], list[Kind]] = {}
for _kind in KINDS:
    for _code in _kind.codes:
        _BY_CODE.setdefault(_code, []).append(_kind)


def title(part: str) -> str:
    return dict(PARTS)[part]


def kind_named(name: str) -> Kind | None:
    return next((kind for kind in KINDS if kind.name == name), None)


def kind_of(item, report) -> Kind:
    """The kind `item` is of: among the kinds that name its code, the first whose `holds`
    takes it, a kind with no `holds` last; `FURTHER` where none names it."""
    kinds = sorted(_BY_CODE.get((item.gate, item.code), []), key=lambda k: k.holds is None)
    return next((kind for kind in kinds if kind.holds is None or kind.holds(item, report)),
                FURTHER)  # fmt: skip


def record_said(kind: Kind) -> str:
    if kind.record is None:
        return "Not yet measured on published papers."
    true, judged = kind.record
    return f"Right in {true} of {judged} judged on published papers."


def self_citation_line(said) -> str:
    """The summary line's self-citation counts, facts and never a verdict; "" where none
    were counted."""
    if said is None or said.note:
        return ""
    counts = [f"{author.shown} {len(listed)}" for author, listed in said.authors]
    if said.journal:
        counts.append(f"{said.journal} {len(said.in_journal)}")
    if not counts:
        return ""
    looked = f"{said.looked} reference{'s' if said.looked != 1 else ''}"
    return f"Self-citation, of {looked} looked up: {'; '.join(counts)}."


def parted(report) -> list[tuple[object, Kind]]:
    """Each item of the report with its kind, in the order of the full report."""
    from manuscript_guard.auditing.report import items

    return [(item, kind_of(item, report)) for item in items(report)]


def _said(item, kind: Kind) -> str:
    """What the editor reads of a finding: of a quoted kind, the number and the words around
    it; a question as a referee's draft words it, which names no option; anything else as the
    report says it."""
    if kind.quoted and item.subject and item.context:
        words = " ".join(item.context.split())
        return f"{item.subject}, in “{words}”"
    return item.refereed or item.message


def _where(item, root: Path | None, placers: dict) -> str:
    from manuscript_guard.auditing.report import _shown

    if item.path is None:
        return ""
    show = _shown(root, {item.path: item.placer} if item.placer is not None else placers)
    return show.located(Path(item.path), item.line)


def _listed(found: list, kind: Kind, root: Path | None, placers: dict) -> list[str]:
    lines = []
    for item in found:
        where, said = _where(item, root, placers), _said(item, kind)
        lines.append(f"    {where}: {said}" if where else f"    {said}")
    return lines


def render(report, root: Path | None = None, *, details: bool = False) -> str:
    """The editor's report as text: the summary line, then the four parts. The first two list
    every finding under its kind; copyediting and what was read give each kind in a line,
    and every finding with `details`. The journal's rules to tick by hand are always listed."""
    found = parted(report)
    placers = getattr(report, "placers", None) or {}
    by_part = {key: [(i, k) for i, k in found if k.part == key] for key, _t in PARTS}
    names = ", ".join(Path(p).name for p in getattr(report, "papers", []) or [])
    lines = [f"Editor's report{f' on {names}' if names else ''}",
             "  " + " · ".join(f"{len(by_part[key])} {said}"
                                    for key, said in COUNTED.items())]  # fmt: skip
    cited = self_citation_line(getattr(report, "self_citation", None))
    if cited:
        lines.append(f"  {cited}")
    lines += [f"  Not read: {item.message}" for item, kind in found if kind.name == "unread"]
    lines += ["", SCOPE]
    for number, (key, heading) in enumerate(PARTS, 1):
        here = by_part[key]
        lines += ["", f"{number}. {heading} ({len(here)})"]
        if not here:
            lines.append("  None found by these checks.")
            continue
        for kind in [k for k in KINDS + (FURTHER,) if any(k is h for _i, h in here)]:
            of_kind = [item for item, k in here if k is kind]
            if key == COPYEDIT and not details:
                first = _where(of_kind[0], root, placers)
                at = f", first at {first}" if first else ""
                lines.append(f"  {kind.says[:-1]}: {len(of_kind)}{at}. {record_said(kind)}")
                continue
            lines += ["", f"  {kind.says}"]
            if key != READ:
                lines.append(f"  {record_said(kind)}")
            shown = of_kind if details or key != READ or kind.name == "by-hand" else (
                of_kind[:READ_LISTED])
            lines += _listed(shown, kind, root, placers)
            if len(shown) < len(of_kind):
                lines.append(f"    and {len(of_kind) - len(shown)} more")
    lines += ["", "Every place of every finding, with what it says in full: the same audit "
              "without --editor, or --details."]  # fmt: skip
    return "\n".join(lines)


def as_json(report, discrimination) -> str:
    """The audit's `--json`, each finding with its part and its kind, and the counts of each
    part under `editor`."""
    from manuscript_guard.auditing.report import as_json as audit_json

    said = json.loads(audit_json(report, discrimination))
    found = parted(report)
    findings = [{**finding, "part": kind.part, "kind": kind.name}
                for finding, (_item, kind) in zip(said["findings"], found, strict=True)]
    parts = {key: sum(kind.part == key for _item, kind in found) for key, _t in PARTS}
    cited = self_citation_line(getattr(report, "self_citation", None))
    return json.dumps({**said, "findings": findings,
                       "editor": {"parts": parts, "self_citation": cited or None}},
                      indent=2, ensure_ascii=True)  # fmt: skip


__all__ = ["ASK", "COPYEDIT", "FURTHER", "KINDS", "LOOK", "PARTS", "READ", "RUN", "SCOPE",
           "SHOWN_FROM", "SUMMARY", "Kind", "as_json", "kind_named", "kind_of", "parted",
           "record_said", "render", "self_citation_line", "title"]
