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
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.emit import FROZEN_PLAN, source_digest_matches
from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.methods import analysis_digests
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

# A section that exists but says nothing useful.
_EMPTY = re.compile(r"^\s*(?:tbd|todo|n/?a|-+|\.+|see below)?\s*$", re.IGNORECASE)


DESIGNS = Path(__file__).parent.parent / "data" / "study_types.yaml"


def study_types() -> dict:
    """Each study design, the plan sections it needs beyond the seven, and its guidelines."""
    import yaml

    return yaml.safe_load(DESIGNS.read_text(encoding="utf-8"))["types"]


def required_for(study_type: str | None) -> tuple[tuple[str, str, str], ...]:
    """The sections a plan for this design is asked for: the seven, and the design's own,
    each with where it comes from in its hint."""
    if study_type is None or study_type not in study_types():
        return REQUIRED
    own = tuple(
        (section["id"], section["heading"], f"{section['says']} ({section['source']})")
        for section in study_types()[study_type]["sections"]
    )
    return REQUIRED + own


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


def check_design(project: Project) -> Report:
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
    covered = 0

    required = required_for(project.study_type)
    for name, pattern, purpose in required:
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

    if covered == len(required):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="plan-complete",
                severity=INFO,
                message=f"analysis plan covers all {covered} expected sections",
                path=path,
            )
        )

    return report.with_counts(design_sections=covered, design_expected=len(required))
