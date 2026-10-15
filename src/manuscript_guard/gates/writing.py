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
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.figures import TEXT_FORMATS, _extract_text
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import count_words
from manuscript_guard.zotero import find_citations
from manuscript_guard.zotero.citations import NARRATIVE, bracketed

GATE = "G6"
DATA = Path(__file__).parent.parent / "data" / "ai_writing.yaml"

# How far either side of a claim a supporting citation may sit.
CITATION_WINDOW = 240
BIB_FILE = "references.bib"
#: Fields of a reference that no reference list prints, or that are the type of the entry.
UNPRINTED = frozenset(
    {"abstract", "annotation", "annote", "comment", "file", "keywords", "langid", "language",
     "mendeley-tags", "type", "urldate"}
)  # fmt: skip


@dataclass(frozen=True)
class Rules:
    artefacts: tuple[dict, ...]
    phrases: tuple[dict, ...]
    vague: tuple[dict, ...]
    density: tuple[dict, ...]
    structure: tuple[dict, ...]
    source: str


@lru_cache(maxsize=1)
def load_rules() -> Rules:
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return Rules(
        artefacts=tuple(document.get("artefacts", ())),
        phrases=tuple(document.get("phrases", ())),
        vague=tuple(document.get("vague_attribution", ())),
        density=tuple(document.get("density", ())),
        structure=tuple(document.get("structure", ())),
        source=document.get("source", ""),
    )


def check_writing(project: Project, results: Results | None = None) -> Report:
    rules = load_rules()
    report = Report()
    totals = {"words": 0, "artefacts": 0, "phrases": 0, "vague": 0}
    corpus: list[tuple[Path, str, str]] = []

    for path in source_files(project.path("manuscript")):
        text = read_text(path)
        # Prose only: citations, code and bindings are not the author's cadence.
        prose = mask(text).replace("\x00", " ")
        corpus.append((path, text, prose))
        totals["words"] += count_words(text)

    for path, text, prose in corpus:
        report = report.merge(_artefacts(rules, path, text, totals))
        report = report.merge(_phrases(rules, path, text, prose, totals))
        report = report.merge(_vague(rules, path, text, prose, totals))

    report = report.merge(_density(rules, corpus, totals["words"]))
    elsewhere = _elsewhere(project, results, [text for _path, text, _prose in corpus])
    for where in elsewhere:
        report = report.merge(_artefacts_elsewhere(rules, where, totals))

    return report.with_counts(
        prose_words=totals["words"],
        writing_artefacts=totals["artefacts"],
        writing_phrases=totals["phrases"],
        writing_vague=totals["vague"],
        writing_texts_elsewhere=len(elsewhere),
    )


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
    `elsewhere`, as they are written."""
    for rule in rules.artefacts:
        if not manuscript and not rule.get("elsewhere"):
            continue
        any_case = manuscript and rule.get("any_case_in_manuscript")
        flags = re.MULTILINE | (re.IGNORECASE if any_case else 0)
        for match in re.finditer(rule["pattern"], text, flags):
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


def _elsewhere(project: Project, results: Results | None, sources: list[str]) -> list[Elsewhere]:
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
    return found + _cited_fields(project, sources)


def _cited_fields(project: Project, sources: list[str]) -> list[Elsewhere]:
    path = project.path("literature") / BIB_FILE
    if not path.is_file():
        return []
    cited = {use.citekey for text in sources for use in find_citations(text, path)}
    written = path.read_text(encoding="utf-8", errors="replace")
    found = []
    for key, fields in read_entries(path).items():
        if key not in cited:
            continue
        opens = re.search(r"^@\w+\s*\{\s*" + re.escape(key) + r"\s*,", written, re.MULTILINE)
        for name, value in fields.items():
            if name in UNPRINTED or not value:
                continue
            at = opens.end() if opens else 0
            field = re.compile(r"^\s*" + re.escape(name) + r"\s*=", re.MULTILINE | re.IGNORECASE)
            seen = field.search(written, at)
            line = written.count("\n", 0, seen.start() if seen else at) + 1
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


def _vague(rules: Rules, path: Path, text: str, prose: str, totals: dict) -> Report:
    """Unsupported appeals to authority, judged against where the citations actually are."""
    report = Report()
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

    for rule in rules.density:
        checked += 1
        # Exemptions apply to both kinds of rule: a technical sense of a flagged word, and
        # a legitimate structural use of a flagged construction.
        spans = [
            span
            for expression in rule.get("exempt", [])
            for span in _spans(re.compile(expression), joined)
        ]
        if "terms" in rule:
            pattern = re.compile(
                r"(?i)\b(?:" + "|".join(re.escape(t) for t in rule["terms"]) + r")\b"
            )
        else:
            pattern = re.compile(rule["pattern"])
        hits = [
            m
            for m in pattern.finditer(joined)
            if not any(start <= m.start() < end for start, end in spans)
        ]

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

    for rule in rules.structure:
        checked += 1
        pattern = re.compile(
            r"(?i)\b(?:" + "|".join(re.escape(v) for v in rule["verbs"]) + r")\b"
        )
        hits = list(pattern.finditer(joined))
        rate = 1000 * len(hits) / words
        if rate > rule["per_1000"]:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="ai-cadence",
                    severity=WARN,
                    message=(
                        f"{rule['id']}: {len(hits)} in {words} words "
                        f"({rate:.1f} per 1000, threshold {rule['per_1000']})"
                    ),
                    context=", ".join(sorted({h.group(0).lower() for h in hits})[:8]),
                    hint=rule["why"].strip(),
                )
            )

    return report.with_counts(density_checked=checked)


def _spans(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in pattern.finditer(text)]
