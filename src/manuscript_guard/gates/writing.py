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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import count_words
from manuscript_guard.zotero.citations import BRACKETED, NARRATIVE

GATE = "G6"
DATA = Path(__file__).parent.parent / "data" / "ai_writing.yaml"

# How far either side of a claim a supporting citation may sit.
CITATION_WINDOW = 240


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


def check_writing(project: Project) -> Report:
    rules = load_rules()
    report = Report()
    totals = {"words": 0, "artefacts": 0, "phrases": 0, "vague": 0}
    corpus: list[tuple[Path, str, str]] = []

    for path in source_files(project.path("manuscript")):
        text = path.read_text(encoding="utf-8")
        # Prose only: citations, code and bindings are not the author's cadence.
        prose = mask(text).replace("\x00", " ")
        corpus.append((path, text, prose))
        totals["words"] += count_words(text)

    for path, text, prose in corpus:
        report = report.merge(_artefacts(rules, path, text, totals))
        report = report.merge(_phrases(rules, path, prose, totals))
        report = report.merge(_vague(rules, path, text, prose, totals))

    report = report.merge(_density(rules, corpus, totals["words"]))

    return report.with_counts(
        prose_words=totals["words"],
        writing_artefacts=totals["artefacts"],
        writing_phrases=totals["phrases"],
        writing_vague=totals["vague"],
    )


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - 40)
    return re.sub(r"\s+", " ", text[left : end + 40]).strip()


def _artefacts(rules: Rules, path: Path, text: str, totals: dict) -> Report:
    report = Report()
    for rule in rules.artefacts:
        for match in re.finditer(rule["pattern"], text, re.MULTILINE):
            totals["artefacts"] += 1
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="model-artefact",
                    message=f"{match.group(0)[:60]!r} — {rule['why']}",
                    path=path,
                    line=_line_of(text, match.start()),
                    context=_context(text, match.start(), match.end()),
                    hint="remove it; this cannot appear in a submitted manuscript",
                )
            )
    return report


def _phrases(rules: Rules, path: Path, prose: str, totals: dict) -> Report:
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
                    line=_line_of(prose, match.start()),
                    context=_context(prose, match.start(), match.end()),
                    hint="rewrite, or keep it deliberately",
                )
            )
    return report


def _vague(rules: Rules, path: Path, text: str, prose: str, totals: dict) -> Report:
    """Unsupported appeals to authority, judged against where the citations actually are."""
    report = Report()
    cited = [m.start() for m in BRACKETED.finditer(text)]
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
                    line=_line_of(prose, match.start()),
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
