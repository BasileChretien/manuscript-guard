"""G6 — does this read as though a person wrote it?

The rules come from the English Wikipedia essay "Signs of AI writing", adapted for journal
prose. What the gate can honestly claim is narrow and worth stating: it detects *habits*,
not authorship. A person who writes "it is important to note" is flagged and a model that
avoids every listed construction is not. It is a style check with a specific and
well-catalogued target, not a detector.

Three severities, and the split is what makes it usable:

* **fail** — model output artefacts. `oaicite`, `[cite: 1]`, "as of my last training data".
  These have no innocent reading and should never survive to a submission.
* **warn** — constructions with a defensible use but a strong association. Reported once
  each, with the reason, so an author can disagree and move on.
* **warn on rate** — ordinary scientific words that are a tell only in quantity. "Robust"
  describes a standard error; six "crucial"s in four hundred words does not describe
  anything. Counting occurrences here rather than flagging them is the difference between a
  gate that gets used and one that gets switched off.

Vague attribution gets the one check an encyclopedia cannot use: "studies have shown" is
reported only when no citation appears nearby, because in a manuscript the fix is a
reference rather than a rewrite.

A placeholder reaches the document from more than the manuscript: a "TBD" drawn in a figure,
a "TODO" in a table's caption written by the analysis, or in the note of a cited reference.
So the rules marked `elsewhere` also read the text of each figure G3 reads, the caption of
each table in the results, and the fields of each cited entry of `references.bib` that a
reference list can print.

Words written to the reviewers or to a model, "As requested by Reviewer 2, we added", are
the residue of a revision (`revision-residue`), read in the manuscript only: the response
to the reviewers is where they belong, and G6 never reads it. Each is reported wherever it
stands. Those that answer one reviewer or point at this manuscript warn until submission and
fail there; those a paper about peer review also writes warn at every stage.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.figures import TEXT_FORMATS, _extract_text
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import count_words
from manuscript_guard.zotero.citations import NARRATIVE, bracketed

GATE = "G6"
DATA = Path(__file__).parent.parent / "data" / "ai_writing.yaml"

# How far either side of a claim a supporting citation may sit.
CITATION_WINDOW = 240
BIB_FILE = "references.bib"
#: Fields of a reference that no reference list prints, or that are the type of the entry: its
#: kind, and a field named `type`, which the reader keeps under `type_field` and which was
#: never read here (round 2 of #345).
UNPRINTED = frozenset(
    {"abstract", "annotation", "annote", "comment", "file", "keywords", "langid", "language",
     "mendeley-tags", "type", "type_field", "urldate"}
)  # fmt: skip


@dataclass(frozen=True)
class Rules:
    artefacts: tuple[dict, ...]
    phrases: tuple[dict, ...]
    vague: tuple[dict, ...]
    density: tuple[dict, ...]
    structure: tuple[dict, ...]
    source: str
    residue: tuple[dict, ...] = ()


#: A name in a residue pattern, `{{one}}`, for the words of `residue_words` it stands for.
_NAMED = re.compile(r"\{\{(\w+)\}\}")


@lru_cache(maxsize=1)
def load_rules() -> Rules:
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    words = document.get("residue_words", {})
    # A name may stand in the words of another, one level down: `one` holds `numbered`.
    words = {name: _NAMED.sub(lambda m: f"(?:{words[m.group(1)]})", text)
             for name, text in words.items()}  # fmt: skip
    return Rules(
        artefacts=tuple(document.get("artefacts", ())),
        phrases=tuple(document.get("phrases", ())),
        vague=tuple(document.get("vague_attribution", ())),
        density=tuple(document.get("density", ())),
        structure=tuple(document.get("structure", ())),
        source=document.get("source", ""),
        residue=tuple(
            {**rule, "pattern": _NAMED.sub(lambda m: f"(?:{words[m.group(1)]})", rule["pattern"])}
            for rule in document.get("residue", ())
        ),
    )


def check_writing(
    project: Project, results: Results | None = None, *, submission: bool = False
) -> Report:
    """`submission` makes a failure of each residue that answers one reviewer or points at
    this manuscript, which warns before it."""
    from manuscript_guard.text.reader import LATEX, manuscript_format

    rules = load_rules()
    folder = project.path("manuscript")
    if manuscript_format(folder) == LATEX:
        read, words, cited = _latex_texts(folder)
        report, totals = _judged(read, words, rules, submission=submission, cited=cited)
    else:
        corpus = [(path, read_text(path)) for path in source_files(folder)]
        report, totals = judge_texts(corpus, rules, submission=submission)
    elsewhere = _elsewhere(project, results)
    for where in elsewhere:
        report = report.merge(_artefacts_elsewhere(rules, where, totals))

    return report.with_counts(
        prose_words=totals["words"],
        writing_artefacts=totals["artefacts"],
        writing_phrases=totals["phrases"],
        writing_vague=totals["vague"],
        writing_residue=totals["residue"],
        writing_texts_elsewhere=len(elsewhere),
    )


def _prose(corpus: list[tuple[Path, str]]) -> list[tuple[Path, str, str]]:
    """Each text with its prose: citations, code and bindings are not the author's cadence."""
    return [(path, text, mask(text).replace("\x00", " ")) for path, text in corpus]


def judge_texts(
    corpus: list[tuple[Path, str]], rules: Rules | None = None, *, submission: bool = False
) -> tuple[Report, dict[str, int]]:
    """What G6 says of manuscript texts on their own, and its totals: the artefacts, phrases,
    residue, vague attributions and rates of `check_writing`, without the figures, captions
    and cited fields it also reads. `tools/g6_baseline.py` judges papers written by people
    with it."""
    read = _prose(corpus)
    words = sum(count_words(text) for _path, text, _prose in read)
    return _judged(read, words, rules or load_rules(), submission=submission)


def _judged(
    read: list[tuple[Path, str, str]],
    words: int,
    rules: Rules,
    *,
    submission: bool = False,
    cited: dict[Path, list[int]] | None = None,
) -> tuple[Report, dict[str, int]]:
    """What G6 says of texts read: each as typed and its prose, with the words a journal
    counts in them, and, for a LaTeX file, where its citation commands stand."""
    report = Report()
    totals = {"words": words, "artefacts": 0, "phrases": 0, "vague": 0, "residue": 0}
    for path, text, prose in read:
        report = report.merge(_artefacts(rules, path, text, totals))
        report = report.merge(_phrases(rules, path, text, prose, totals))
        report = report.merge(_residue(rules, path, text, prose, totals, submission))
        report = report.merge(_vague(rules, path, text, prose, totals,
                                     None if cited is None else cited.get(path, [])))  # fmt: skip
    return report.merge(_density(rules, read, totals["words"])), totals


def _latex_texts(folder: Path) -> tuple[list[tuple[Path, str, str]], int, dict[Path, list[int]]]:
    """A LaTeX manuscript as G6 reads it (DESIGN.md, "LaTeX manuscripts", step 7): each file
    of its documents as typed, where the artefacts are looked for as in a Markdown file; its
    prose as the reader masks it, where the phrases and the residue are; where each of its
    citation commands stands, which a vague attribution is judged against; and the words a
    journal would count, as G4 counts them in the document's printed view. The author's
    packages are no text of the paper."""
    from manuscript_guard.text.latex.structure import read_document

    documents = [read_document(folder, supplementary=supplementary).sources
                 for supplementary in (False, True)]  # fmt: skip
    return _read_latex(folder, documents)


def _read_latex(
    folder: Path, documents: list
) -> tuple[list[tuple[Path, str, str]], int, dict[Path, list[int]]]:
    """`_latex_texts` of documents read, each the include tree's sources."""
    from manuscript_guard.text.latex.printed import printed_view

    read: list[tuple[Path, str, str]] = []
    cited: dict[Path, list[int]] = {}
    words = 0
    for document in documents:
        sources = [source for source in document if not source.path.lower().endswith(".sty")]
        for source in sources:
            path = folder / source.path
            read.append((path, _latex_typed(source), _latex_prose(source)))
            cited[path] = _cited_at(source)
        words += count_words(printed_view([source for source in sources if not source.loose]))
        words += sum(count_words(printed_view([source])) for source in sources if source.loose)
    return read, words, cited


def _latex_typed(source) -> str:
    """A LaTeX file as typed, where an artefact or a placeholder is looked for, in a comment
    too, as in a Markdown file's comment. Its preamble is as the reader reads it, the title
    and an abstract: a package's name is no text, `\\usepackage{fixme}` none. A reference list
    typed in `thebibliography` is blanked, its titles held as `references.bib`'s are (round 1
    of step 7b)."""
    from manuscript_guard.text.latex.mask import NUL

    reading = source.reading
    body = reading.body_start if reading.body_start >= 0 else len(source.text)
    typed = reading.masked[:body].replace(NUL, " ") + source.text[body:]
    return _blank(typed, reading.references)


def _latex_prose(source) -> str:
    """A LaTeX file's prose, the phrases', the residue's and the rates': what the reader
    keeps, at the same offsets, a space where it blanks; but a typed table's cells and a
    reference list, as a Markdown table's rows count no words and its references are none of
    the source (round 1 of step 7b)."""
    from manuscript_guard.text.latex.mask import NUL

    reading = source.reading
    return _blank(reading.masked.replace(NUL, " "), (*reading.tables, *reading.references))


def _blank(text: str, spans) -> str:
    """`text` with each span a space, its line breaks kept."""
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if chars[index] != "\n":
                chars[index] = " "
    return "".join(chars)


def _cited_at(source) -> list[int]:
    """Where each citation command of a LaTeX file stands, as `[@...]` stands in Markdown;
    not `\\nocite`, which prints nothing beside a claim (round 1 of step 7b)."""
    return [found.start for found in source.reading.cited
            if not source.text.startswith("\\nocite", found.start)]  # fmt: skip


def rates(corpus: list[tuple[Path, str]], rules: Rules | None = None) -> dict[str, float]:
    """Each rate rule's occurrences per 1000 words over the texts together, whatever its
    threshold: the number `_density` holds to `per_1000`. Empty under 200 words, where G6
    holds no rate."""
    rules = rules or load_rules()
    read = _prose(corpus)
    words = sum(count_words(text) for _path, text, _prose in read)
    if words < 200:
        return {}
    joined = "\n".join(prose for _path, _text, prose in read)
    return {rule["id"]: 1000 * len(_hits(rule, joined)) / words
            for rule in (*rules.density, *rules.structure)}  # fmt: skip


def _line_of(text: str, match: re.Match[str]) -> int:
    """The line of the file the matched words begin on.

    `text` is the file as read, never the prose the rules match in: masking keeps every
    offset and blanks the line ends inside a comment, a listing and the front matter, so a
    count in the prose fell short by each of those lines, and a phrase under a comment was
    reported on the comment. And the words, not the match: a rule that opens with `^\\s*`
    matches from the first blank line above a paragraph, and its finding was put there.
    """
    found = match.group(0)
    offset = match.start() + len(found) - len(found.lstrip())
    return text.count("\n", 0, offset) + 1


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - 40)
    return re.sub(r"\s+", " ", text[left : end + 40]).strip()


def artefacts_in(
    rules: Rules, text: str, *, manuscript: bool
) -> Iterator[tuple[dict, re.Match[str]]]:
    """Each artefact in `text`, with the rule that found it. In the manuscript every rule,
    and a word marked `any_case_in_manuscript` in any case; elsewhere only the rules marked
    `elsewhere`, as they are written. What two rules find in one place is one artefact,
    "[CITATION NEEDED]" a slot and capitals both, and is said once."""
    taken: list[tuple[int, int]] = []
    for rule in rules.artefacts:
        if not manuscript and not rule.get("elsewhere"):
            continue
        any_case = manuscript and rule.get("any_case_in_manuscript")
        flags = re.MULTILINE | (re.IGNORECASE if any_case else 0)
        for match in re.finditer(rule["pattern"], text, flags):
            if any(start < match.end() and match.start() < end for start, end in taken):
                continue
            taken.append(match.span())
            yield rule, match


def _artefacts(rules: Rules, path: Path, text: str, totals: dict) -> Report:
    report = Report()
    for rule, match in artefacts_in(rules, text, manuscript=True):
        totals["artefacts"] += 1
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="model-artefact",
                message=f"{match.group(0)[:60]!r} — {rule['why']}",
                path=path,
                line=_line_of(text, match),
                context=_context(text, match.start(), match.end()),
                hint="remove it; this cannot appear in a submitted manuscript",
            )
        )
    return report


@dataclass(frozen=True)
class Elsewhere:
    """A text outside the manuscript that reaches the document: where it is, and how to
    name it in a finding."""

    path: Path
    text: str
    named: str
    line: int | None = None


def _elsewhere(project: Project, results: Results | None) -> list[Elsewhere]:
    """The text of every figure, the caption of every table, and the printed fields of every
    cited reference, each as one text."""
    found: list[Elsewhere] = []
    figures = project.path("figures")
    if figures.is_dir():
        for path in sorted(figures.rglob("*")):
            if path.is_file() and path.suffix.lower() in TEXT_FORMATS:
                text = _extract_text(path)
                if text:
                    found.append(Elsewhere(path, text, f"the text of {path.name}"))
    for key, table in sorted((results.tables if results else {}).items()):
        if table.caption:
            found.append(Elsewhere(table.source, table.caption, f"the caption of table {key!r}"))
    return found + _cited_fields(project)


def _cited_fields(project: Project) -> list[Elsewhere]:
    path = project.path("literature") / BIB_FILE
    if not path.is_file():
        return []
    from manuscript_guard.text.reader import citation_uses

    # The keys the manuscript cites, in its format: a LaTeX file's `\\nocite{*}` cites each.
    cited = {use.citekey for use in citation_uses(project)}
    written = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for key, fields in read_entries(path).items():
        if key not in cited:
            continue
        opens = re.search(r"^@\w+\s*\{\s*" + re.escape(key) + r"\s*,", written, re.MULTILINE)
        at = opens.start() if opens else 0
        for name, value in fields.items():
            if name in UNPRINTED or not value:
                continue
            # The field where it is written: on a line of its own, or after the key or another
            # field on the entry's line.
            field = re.compile(r"(?:^|[{,])[ \t]*" + re.escape(name) + r"[ \t]*=", re.M | re.I)
            seen = field.search(written, at)
            line = written.count("\n", 0, seen.end() if seen else at) + 1
            found.append(Elsewhere(path, value, f"the {name} of @{key}", line))
    return found


def _artefacts_elsewhere(rules: Rules, where: Elsewhere, totals: dict) -> Report:
    """The rules marked `elsewhere`: a word that counts in any case in the manuscript counts
    here in capitals only."""
    report = Report()
    for rule, match in artefacts_in(rules, where.text, manuscript=False):
        totals["artefacts"] += 1
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="model-artefact",
                message=f"{match.group(0)[:60]!r} in {where.named} — {rule['why']}",
                path=where.path,
                line=where.line,
                context=_context(where.text, match.start(), match.end()),
                hint="remove it; this cannot appear in a submitted manuscript",
            )
        )
    return report


def _phrases(rules: Rules, path: Path, text: str, prose: str, totals: dict) -> Report:
    report = Report()
    for rule in rules.phrases:
        for seen, match in enumerate(re.finditer(rule["pattern"], prose)):
            # Counted before the cap, reported after it. The count is the whole point of
            # this gate — G6 measures rate, not presence — and breaking out of the loop
            # before incrementing made `writing_phrases` stop at four however often a
            # phrase actually appeared, which understates exactly the papers it should
            # flag hardest.
            totals["phrases"] += 1
            if seen >= 3:  # a few examples make the point; a list of forty does not
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="ai-phrasing",
                    severity=WARN,
                    message=f"{rule['id']}: {rule['why']}",
                    path=path,
                    line=_line_of(text, match),
                    context=_context(prose, match.start(), match.end()),
                    hint="rewrite, or keep it deliberately",
                )
            )
    return report


#: The end of a line with nothing on the next: where one paragraph stops for a residue rule.
_BLANK_LINE = re.compile(r"\n[ \t\r]*(?=\n)")


def _paragraphs(text: str) -> list[tuple[int, int]]:
    """Where each paragraph of `text` begins and ends, so that "as suggested by" closing one
    and "Reviewer 2" opening the next are not read as one phrase."""
    spans, start = [], 0
    for blank in _BLANK_LINE.finditer(text):
        spans.append((start, blank.start()))
        start = blank.end()
    return [*spans, (start, len(text))]


def residue_in(
    rules: Rules, text: str, said: list[tuple[int, int]] | None = None
) -> Iterator[tuple[dict, re.Match[str]]]:
    """Each place in `text` that speaks to the reviewers or to a model, with the rule that
    found it: read a paragraph at a time, less what the rule's exemptions cover and the
    places `said` already, an artefact's. The rules that point at this manuscript are tried
    first, so that a place two rules find is said once, and as the stricter."""
    taken: list[tuple[int, int]] = list(said or ())
    paragraphs = _paragraphs(text)
    for rule in sorted(rules.residue, key=lambda rule: not rule.get("self_reference")):
        pattern = re.compile(rule["pattern"])
        exempt = [
            span
            for expression in rule.get("exempt", ())
            for span in _spans(re.compile(expression), text)
        ]
        for start, end in paragraphs:
            for match in pattern.finditer(text, start, end):
                if any(left <= match.start() < right for left, right in exempt):
                    continue
                if any(left < match.end() and match.start() < right for left, right in taken):
                    continue
                taken.append(match.span())
                yield rule, match


def _residue(
    rules: Rules, path: Path, text: str, prose: str, totals: dict, submission: bool
) -> Report:
    """Every residue, each reported: one "as requested by Reviewer 2" is enough. Not where
    an artefact was found, "Here is the revised Methods", which fails already."""
    report = Report()
    said = [match.span() for _rule, match in artefacts_in(rules, text, manuscript=True)]
    for rule, match in residue_in(rules, prose, said):
        totals["residue"] += 1
        binds = bool(rule.get("self_reference"))
        if binds:
            hint = "say it in the response to the reviewers, and here only what the paper reports"
            hint += "" if submission else "; it fails at submission"
        else:
            hint = "say it in the response to the reviewers, unless the paper is about peer review"
        shown = " ".join(match.group(0).split())[:60]
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="revision-residue",
                severity=FAIL if binds and submission else WARN,
                message=f"{shown!r} — {rule['why']}",
                path=path,
                line=_line_of(text, match),
                context=_context(prose, match.start(), match.end()),
                hint=hint,
            )
        )
    return report


def _vague(
    rules: Rules, path: Path, text: str, prose: str, totals: dict, cited: list[int] | None = None
) -> Report:
    """Unsupported appeals to authority, judged against where the citations actually are:
    `cited` where a LaTeX file's citation commands stand, a Markdown file's found here."""
    report = Report()
    if cited is None:
        cited = [m.start() for m in bracketed(text)]
        cited += [m.start() for m in NARRATIVE.finditer(text)]

    for rule in rules.vague:
        for match in re.finditer(rule["pattern"], prose):
            if any(abs(position - match.start()) <= CITATION_WINDOW for position in cited):
                continue
            totals["vague"] += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="vague-attribution",
                    severity=WARN,
                    message=f"{match.group(0)!r} with no citation nearby",
                    path=path,
                    line=_line_of(text, match),
                    context=_context(prose, match.start(), match.end()),
                    hint="cite the studies, or name who argues it and cite them",
                )
            )
    return report


def _density(rules: Rules, corpus: list[tuple[Path, str, str]], words: int) -> Report:
    """Rates over the whole manuscript, because cadence is a property of the whole."""
    report = Report()
    if words < 200:
        return report.with_counts(density_checked=0)

    joined = "\n".join(prose for _path, _text, prose in corpus)
    checked = 0

    for rule in (*rules.density, *rules.structure):
        checked += 1
        hits = _hits(rule, joined)
        rate = 1000 * len(hits) / words
        if rate <= rule["per_1000"]:
            continue
        sample = sorted({h.group(0).strip().lower() for h in hits})[:8]
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="ai-cadence",
                severity=WARN,
                message=(
                    f"{rule['id']}: {len(hits)} in {words} words "
                    f"({rate:.1f} per 1000, threshold {rule['per_1000']})"
                ),
                context=", ".join(sample) if sample else None,
                hint=rule["why"].strip(),
            )
        )

    return report.with_counts(density_checked=checked)


def _hits(rule: dict, joined: str) -> list[re.Match[str]]:
    """A rate rule's occurrences in the prose: its terms, its pattern or its verbs, less
    those inside an exemption. Exemptions apply to every kind of rule: a technical sense of
    a flagged word, and a legitimate structural use of a flagged construction."""
    spans = [
        span
        for expression in rule.get("exempt", [])
        for span in _spans(re.compile(expression), joined)
    ]
    if "terms" in rule or "verbs" in rule:
        words = rule.get("terms") or rule["verbs"]
        pattern = re.compile(r"(?i)\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")
    else:
        pattern = re.compile(rule["pattern"])
    return [
        m
        for m in pattern.finditer(joined)
        if not any(start <= m.start() < end for start, end in spans)
    ]


def _spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in pattern.finditer(text)]
