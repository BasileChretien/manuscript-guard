"""G12 — was there a plan before there was an analysis?

The strongest thing anyone can do for the credibility of a result is to write down what
they intended to do before they did it. Not because deviating is wrong — most real analyses
deviate — but because a deviation that was declared is a decision, and a deviation nobody
recorded is indistinguishable from having tried several things and reported the best one.

This gate **warns and never blocks**, by explicit decision. Blocking would be the stronger
discipline and it would be unworkable: exploratory work is real work, and a gate that
prevents you writing code until a plan is agreed is a gate that gets bypassed on the first
afternoon it costs you something.

So it does the useful part instead. It notices that analysis code exists with no plan behind
it, and it insists that the plan's sections say something rather than existing. A plan whose
"Deviations from the plan" heading is empty is a plan nobody has revisited, which is the
common case and the one worth naming.

And it notices a plan changed after the results were known. The emitter keeps the plan as it
stood the first time any results were written (`design/plan.frozen.yaml`, never
overwritten). A plan that differs from that copy while its Deviations section reads as it
did is a plan rewritten after the results with nothing said, which is the pattern of a
hypothesis fitted to its results; a warning, as everything here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.emit import FROZEN_PLAN, source_digest_matches
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.methods import analysis_digests
from manuscript_guard.text.blocks import list_items
from manuscript_guard.text.inline import code_spans
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import Section, split_sections, subsections

GATE = "G12"
PLAN = Path("design") / "plan.md"

# Each entry: heading pattern, and what it is for. Wording is matched loosely because an
# author's headings are their own.
REQUIRED = (
    ("question", r"(?i)\b(research )?question|objective", "what is being asked"),
    ("design", r"(?i)\bdesign\b", "the study design and why it suits the question"),
    ("population", r"(?i)\bpopulation|participants|data source\b", "who or what is included"),
    ("exposure", r"(?i)\bexposure|intervention|predictor\b", "what is being compared"),
    ("outcome", r"(?i)\boutcome|endpoint\b", "what is being measured"),
    ("analysis", r"(?i)\banalysis|statistical\b", "the estimator and the model"),
    (
        "deviations",
        r"(?i)\bdeviation|changes? (from|to) the plan|amendments?\b",
        "what changed after the plan was agreed, or that nothing did",
    ),
)

#: What every key a feasibility script emits opens with: `feasibility.n_reports`.
FEASIBILITY = "feasibility."

#: The heading of the plan's list of the results the paper will report. Not one of the seven:
#: a plan without it says nothing to hold the results to.
PLANNED = r"(?i)\bplanned results?\b"

#: What a planned result's code span holds: a key as the analysis emits it, `ror.point`, or
#: as the manuscript binds it, `results.ror.point`; or a group of keys, `ror.*`. A span with
#: no dot is code, not a key: `glm`, `R`.
_PLANNED_KEY = re.compile(r"(?:results\.)?([A-Za-z_][\w-]*(?:\.[\w-]+)+)")
_PLANNED_GROUP = re.compile(r"(?:results\.)?([A-Za-z_][\w-]*(?:\.[\w-]+)*)\.\*")
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


@dataclass(frozen=True)
class Planned:
    """A result the plan says the paper will report: its key, or the stem of a group of
    keys, and the line it is listed on."""

    key: str
    group: bool
    line: int

# A section that exists but says nothing useful.
_EMPTY = re.compile(r"^\s*(?:tbd|todo|n/?a|-+|\.+|see below)?\s*$", re.IGNORECASE)


def plan_path(project: Project) -> Path:
    return project.root / PLAN


def _read_plan(path: Path) -> tuple[str, Finding | None]:
    """The plan's text, and a warning if it had to be guessed at.

    A plan saved in Windows-1252 raised, and a gate that raises is `gate-errored`, which
    fails at every stage — from the one gate that is meant never to block. The headings
    are what this gate reads, and they survive a replaced accent; the warning is for
    everything else that will read the file. A byte-order mark is stripped, since in front
    of the first `#` it stops the title being a heading, and line endings are made `\\n`,
    since decoding bytes does not translate them and a setext underline followed by `\\r`
    is not an underline.
    """
    raw = path.read_bytes()

    def lines(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")

    try:
        return lines(raw.decode("utf-8-sig")), None
    except UnicodeDecodeError as exc:
        return lines(raw.decode("utf-8", errors="replace")), Finding(
            gate=GATE,
            code="plan-not-utf8",
            severity=WARN,
            message=f"{PLAN.as_posix()} is not UTF-8 (byte {exc.start}), so it was read with "
            f"the undecodable characters replaced",
            path=path,
            hint="re-save it as UTF-8; pandoc, git diffs and every other reader of the plan "
            "expect it",
        )


def _plan_sections(text: str) -> list[Section]:
    """The plan's sections, without the plan's own title.

    `# Analysis plan` is what `init` writes at the top, and it matched the "analysis"
    requirement — so the empty `## Analysis` scaffolded under it was never reported, and a
    plan with no Analysis section at all counted as having one. The first heading is the
    title when every heading after it is deeper, or when there is none: it encloses the plan
    rather than being a part of it. A plan that is one heading and some prose therefore has
    no sections, which is the truth about it.

    The text before the first heading is left out by its level, not its title. A heading
    that is only an attribute block, `### {#inclusion}`, has an empty title too, and was left
    out with what it heads.
    """
    sections = [s for s in split_sections(text) if s.level > 0]
    if sections and all(s.level > sections[0].level for s in sections[1:]):
        return sections[1:]
    return sections


def _says_nothing(sections: list[Section], index: int) -> bool:
    """A heading with nothing under it, counting what its subsections say.

    Judged on the section's own text alone, a Population written entirely under
    `### Inclusion` was a heading with nothing under it; judged on everything it encloses,
    `### Inclusion` followed by `### Exclusion` would say something. So: every part of it
    is empty, headings aside.
    """
    return all(_EMPTY.match(part.body.strip()) for part in subsections(sections, index))


def deviations_said(text: str) -> str:
    """What a plan's Deviations section says, as words: its line breaks and spacing left
    out, so that a section re-wrapped says what it said."""
    pattern = dict((name, rule) for name, rule, _purpose in REQUIRED)["deviations"]
    sections = _plan_sections(text)
    said = [
        part.body
        for index, section in enumerate(sections)
        if re.search(pattern, section.title)
        for part in subsections(sections, index)
    ]
    return " ".join(" ".join(said).split())


def planned_results(text: str) -> list[Planned] | None:
    """The results a plan's Planned results section lists: for each list item under it, the
    first code span the item holds, where that is a key or a group of keys. None where the
    plan has no such section; an empty list where it has one and names no key in it.

    An item is read up to the next item or its first blank line, so a nested item's key is
    its own and not its parent's, and a key in prose after the list is no item's. An item
    whose first code span is not a key is not read: it is code."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    sections = _plan_sections(text)
    masked = mask(text)
    spans = code_spans(masked)
    items = list_items(text)
    lines = text.count("\n") + 2
    planned: list[Planned] | None = None
    for index, section in enumerate(sections):
        if not re.search(PLANNED, section.title):
            continue
        planned = planned or []
        after = index + len(subsections(sections, index))
        end = sections[after].line if after < len(sections) else lines
        inside = [start for start in items if section.line < _line(text, start) < end]
        for number, start in enumerate(inside):
            stop = inside[number + 1] if number + 1 < len(inside) else _offset(text, end)
            blank = _BLANK_LINE.search(text, start, stop)
            stop = blank.start() if blank else stop
            first = next((span for span in spans if start <= span[0] < stop), None)
            if first is None:
                continue
            said = text[first[0] : first[1]].strip("`").strip()
            if group := _PLANNED_GROUP.fullmatch(said):
                planned.append(Planned(group.group(1), True, _line(text, start)))
            elif key := _PLANNED_KEY.fullmatch(said):
                planned.append(Planned(key.group(1), False, _line(text, start)))
    return planned


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _offset(text: str, line: int) -> int:
    """Where line `line` (from 1) starts, or the end of the text past its last line."""
    offset = 0
    for _ in range(line - 1):
        found = text.find("\n", offset)
        if found < 0:
            return len(text)
        offset = found + 1
    return offset


def _emitted(results: Results, planned: Planned) -> list[bool]:
    """Whether each result the planned key names is quoted: one entry for each value, table
    or model it names, none where the analysis emitted nothing under it."""
    key = planned.key
    if planned.group:
        return [v.quoted for k, v in results.values.items() if k.startswith(f"{key}.")]
    if key in results.values:
        return [results.values[key].quoted]
    kind, _, name = key.partition(".")
    if kind == "table" and name in results.tables:
        return [results.tables[name].quoted]
    if kind == "model" and name in results.models:
        return [True]
    return []


def _named(deviations: str, planned: Planned) -> bool:
    """Whether the Deviations section names the key, as the plan lists it or bound."""
    key = re.escape(planned.key) + (r"\.\*" if planned.group else "")
    return bool(re.search(rf"(?<![\w.-])(?:results\.)?{key}(?![\w-]|\.\w)", deviations))


def _planned(text: str, path: Path, results: Results | None, stage: str | None) -> Report:
    """The results the plan promised against those the analysis emitted and quoted.

    Asked once the analysis is under way: at the design stage nothing has been emitted, and
    called without results nothing can be compared."""
    from manuscript_guard.policy import DESIGN

    planned = planned_results(text)
    if planned is None or results is None or stage in (None, DESIGN):
        return Report()
    if not planned:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="planned-results-unkeyed",
                    severity=WARN,
                    message="the plan's Planned results section names no result by its key",
                    path=path,
                    hint="list each result the paper will report as an item that opens with "
                    "its key in backticks, `ror.point`, or a group of keys, `ror.*`",
                ),
            ),
            {"planned_results": 0},
        )
    deviations = deviations_said(text)
    findings = []
    for item in planned:
        quoted = _emitted(results, item)
        if quoted and any(quoted):
            continue
        if _named(deviations, item):
            continue
        written = f"{item.key}.*" if item.group else item.key
        findings.append(
            Finding(
                gate=GATE,
                code="planned-result-unquoted" if quoted else "planned-result-missing",
                severity=WARN,
                message=f"the plan lists {written} among the results the paper will report, "
                + ("and the analysis emits it with quoted=False" if quoted
                   else "and the analysis emits nothing under it"),  # fmt: skip
                path=path,
                line=item.line,
                hint="report it, or say under Deviations from the plan why it is not "
                f"reported, naming {written}",
            )
        )
    return Report(tuple(findings), {"planned_results": len(planned)})


def _frozen(project: Project, path: Path, text: str) -> Report:
    """The plan against the copy kept when the first results were written."""
    frozen = project.root / FROZEN_PLAN
    if not frozen.is_file():
        results = project.path("results")
        if results.is_dir() and any(results.glob("*.json")):
            return Report(
                (
                    Finding(
                        gate=GATE,
                        code="plan-not-frozen",
                        severity=INFO,
                        message=f"results exist and no {FROZEN_PLAN.as_posix()} records the "
                        f"plan as it stood when they were first written",
                        path=path,
                        hint="the emitter keeps it on the next write; a plan changed before "
                        "then cannot be told from one written first",
                    ),
                )
            )
        return Report()
    try:
        record = read_structured(frozen)
    except ContractError:
        record = None
    if not isinstance(record, dict) or not isinstance(record.get("plan"), str) or not \
            isinstance(record.get("sha256"), str):  # fmt: skip
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="plan-frozen-unreadable",
                    severity=WARN,
                    message=f"{FROZEN_PLAN.as_posix()} does not hold the plan and its digest",
                    path=frozen,
                    hint="it is written by the emitter, never by hand; restore it from version "
                    "control",
                ),
            )
        )
    # Unchanged by its bytes, or by its words: a plan re-wrapped says what it said.
    if source_digest_matches(path, record["sha256"]) or text.split() == record["plan"].split():
        return Report()
    if deviations_said(text) != deviations_said(record["plan"]):
        return Report()
    return Report(
        (
            Finding(
                gate=GATE,
                code="plan-changed-after-results",
                severity=WARN,
                message=f"the plan has changed since the first results were written "
                f"({record.get('frozen_at', 'date not recorded')}), and its Deviations "
                f"section says what it said then",
                path=path,
                hint="say under Deviations what changed, when, who decided, and whether the "
                "results it affects were known by then",
            ),
        )
    )


def check_design(
    project: Project, results: Results | None = None, stage: str | None = None
) -> Report:
    """The plan's sections, and, while it is being written, whether the data were looked at.

    `results` and `stage` are what `check` has; called without them, the feasibility
    results are not asked for."""
    path = plan_path(project)
    analysis = analysis_digests(project)

    if not path.exists():
        if not analysis:
            return Report(counts={"design_sections": 0})
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="no-analysis-plan",
                    severity=WARN,
                    message=f"{len(analysis)} analysis file(s) exist and there is no {PLAN}",
                    path=path,
                    hint="write down what you intended before you did it; the analysis-plan "
                    "skill has the outline. A deviation that was declared is a decision",
                )
            ,),
            {"design_sections": 0},
        )

    text, unreadable = _read_plan(path)
    sections = _plan_sections(text)
    report = Report((unreadable,)) if unreadable else Report()
    report = report.merge(_frozen(project, path, text))
    report = report.merge(_planned(text, path, results, stage))
    covered = 0
    said: set[str] = set()

    for name, pattern, purpose in REQUIRED:
        matching = [i for i, s in enumerate(sections) if re.search(pattern, s.title)]
        if not matching:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="plan-section-missing",
                    severity=WARN,
                    message=f"the plan says nothing about {name}",
                    path=path,
                    hint=purpose,
                )
            )
            continue
        if all(_says_nothing(sections, i) for i in matching):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="plan-section-empty",
                    severity=WARN,
                    message=f"the plan's {name} section is a heading with nothing under it",
                    path=path,
                    line=sections[matching[0]].line,
                    hint=purpose,
                )
            )
            continue
        covered += 1
        said.add(name)

    if covered == len(REQUIRED):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="plan-complete",
                severity=INFO,
                message=f"analysis plan covers all {covered} expected sections",
                path=path,
            )
        )

    if "analysis" in said and _feasibility_unknown(results, stage):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="feasibility-not-run",
                severity=WARN,
                message="the plan sets out an analysis, and no result says what the data can "
                f"answer: nothing is emitted under {FEASIBILITY}",
                path=path,
                hint="write a feasibility script, analysis/00_feasibility.py or .R, that emits "
                "the cohort at each selection step, the outcome's events, each planned "
                "variable's missing values, the date range and the duplicates found, as "
                f"{FEASIBILITY}<name>; the analysis-plan skill has the outline",
            )
        )

    return report.with_counts(design_sections=covered, design_expected=len(REQUIRED))


def _feasibility_unknown(results: Results | None, stage: str | None) -> bool:
    """While the plan is being written, whether no result says what the data can answer.

    Asked at the design stage only: once the analysis has run, its own results say it.
    """
    from manuscript_guard.policy import DESIGN

    if results is None or stage != DESIGN:
        return False
    return not any(key.startswith(FEASIBILITY) for key in results.values)
