"""G16 — the data were held to the data dictionary, and the paper says what they held.

The author's script checks each table it reads against `design/data_dictionary.yaml`
(`Emitter.check_data`, `em$check_data` in R), and the counts are results under `quality.`:
the rows checked, then for each variable the values missing, of the wrong type, out of
range, not among its codes, not matching its pattern, outside the study period or recorded
where the variable does not apply, and for each rule the rows that break it. This gate
reads the dictionary and the results and names what is missing from that chain:

* `not-in-dictionary` (a warning): a variable the analysis declares or a model reads that
  has no entry, so nothing says what it is or what values it may take;
* `quality-not-run`: the dictionary lists variables and no result is under `quality.`;
* `entry-unchecked` and `rule-unchecked`: an entry, or a rule, that no count covers;
* `quality-not-reported`: there are counts, and neither the Methods nor the supplement binds
  one, so a reader cannot see what the data held.

The last four warn while the paper is written and fail at submission, as Basile decided
(2026-10-21). The first three are not asked at the design stage, when the data may not have
been collected, and the last is asked from the drafting stage, when there are Methods. A
value the data break a check with is never a finding: it is a count, which the paper
reports. A dictionary that does not read is G12's `dictionary-invalid`, and this gate says
nothing of it. The gate is silent where there is no dictionary: a project that keeps none
is not asked for one. Whether the counts are current is G1's: the dictionary is an input of
the run that made them, so a dictionary edited since is `input-changed`.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.dictionary import Dictionary, load_dictionary
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.quality import PREFIX, slug
from manuscript_guard.text.placeholders import parse

GATE = "G16"

_RUN = (
    "hand each table the analysis reads to check_data (em.check_data(frame) in Python, "
    "em$check_data(frame) in R), which counts what the dictionary declares under quality.; "
    "the results-binding skill has the outline"
)


def _stage_at_least(stage: str | None, wanted: str) -> bool:
    from manuscript_guard.policy import stage_index

    return stage is None or stage_index(stage) >= stage_index(wanted)


def _shown(project: Project, path: Path) -> str:
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:  # `paths:` can put the results outside the project
        return path.name


def _used(project: Project, results: Results) -> dict[str, str]:
    """Each variable the analysis declares or a model reads, and what says so."""
    used = {
        name: f"is declared in {_shown(project, variable.source)}"
        for name, variable in results.variables.items()
    }
    for model in results.models.values():
        for name in model.variables():
            used.setdefault(
                name, f"is read by model {model.key} in {_shown(project, model.source)}"
            )
    return used


def _undefined(project: Project, dictionary: Dictionary, results: Results) -> list[Finding]:
    known = set(dictionary.names)
    return [
        Finding(
            gate=GATE,
            code="not-in-dictionary",
            severity=WARN,
            message=f"{name} {where} and has no entry in the data dictionary",
            path=dictionary.path,
            hint="give it an entry: its definition, type, and the codes or range its values "
            "may take; a variable the analysis derives names what it is derived from",
        )
        for name, where in sorted(_used(project, results).items())
        if name not in known
    ]


def _unchecked(dictionary: Dictionary, results: Results, severity: str) -> list[Finding]:
    counted = {key for key in results.values if key.startswith(PREFIX)}
    if dictionary.variables and not counted:
        return [
            Finding(
                gate=GATE,
                code="quality-not-run",
                severity=severity,
                message=f"the data dictionary lists {len(dictionary.variables)} variables and "
                f"no result is under {PREFIX}: the data were never held to it",
                path=dictionary.path,
                hint=_RUN,
            )
        ]
    findings = [
        Finding(
            gate=GATE,
            code="entry-unchecked",
            severity=severity,
            message=f"{variable.name} is in the data dictionary and no check counted it "
            f"({PREFIX}{slug(variable.name)}.missing is not in the results)",
            path=dictionary.path,
            line=variable.line,
            hint="hand check_data the table that holds it, after any step that derives it",
        )
        for variable in dictionary.variables
        if f"{PREFIX}{slug(variable.name)}.missing" not in counted
    ]
    findings += [
        Finding(
            gate=GATE,
            code="rule-unchecked",
            severity=severity,
            message=f"rule {rule.id} is in the data dictionary and no check counted the rows "
            f"that break it ({PREFIX}rule.{rule.id} is not in the results)",
            path=dictionary.path,
            hint=f"give check_data the rows that break it, computed={{'{rule.id}': ...}}"
            if rule.computed
            else "hand check_data one table that holds all its variables",
        )
        for rule in dictionary.rules
        if f"{PREFIX}rule.{rule.id}" not in counted
    ]
    return findings


def check_data_quality(
    project: Project, results: Results, stage: str | None = None, *, submission: bool = False
) -> Report:
    """The dictionary against the analysis and against the counts the checks made."""
    from manuscript_guard.policy import ANALYSIS

    dictionary, _report = load_dictionary(project)
    if dictionary is None:
        return Report()
    counted = sum(key.startswith(PREFIX) for key in results.values)
    report = Report(counts={"quality_results": counted})
    if not _stage_at_least(stage, ANALYSIS):
        return report
    findings = _undefined(project, dictionary, results)
    findings += _unchecked(dictionary, results, FAIL if submission else WARN)
    return report.with_findings(*findings)


def _binds_a_count(text: str) -> bool:
    return any(
        placeholder.namespace == "results" and placeholder.key.startswith(PREFIX)
        for placeholder in parse(text)[0]
    )


def _supplement_binds_a_count(manuscript: Path) -> bool:
    """Whether the supplement binds a count: a file of a Markdown one, or a binding of a LaTeX
    one's, in a file its entry inputs or one nothing inputs (step 13)."""
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if manuscript_format(manuscript) != LATEX:
        main = set(source_files(manuscript, main_text_only=True))
        return any(_binds_a_count(read_text(path)) for path in source_files(manuscript)
                   if path not in main)  # fmt: skip
    from manuscript_guard.text.latex.structure import read_document
    from manuscript_guard.text.latex.views import bindings

    return any(
        placeholder.namespace == "results" and placeholder.key.startswith(PREFIX)
        for source in read_document(manuscript, supplementary=True).sources
        if not source.path.lower().endswith(".sty")
        for placeholder in bindings(source)[0]
    )


def check_quality_reported(
    project: Project, results: Results, stage: str | None = None, *, submission: bool = False
) -> Report:
    """Where there are counts, that the Methods or the supplement bind one of them."""
    from manuscript_guard.gates.methods import methods_text
    from manuscript_guard.policy import DRAFTING

    if not _stage_at_least(stage, DRAFTING):
        return Report()
    if not any(key.startswith(PREFIX) for key in results.values):
        return Report()
    dictionary, _report = load_dictionary(project)
    if dictionary is None:
        return Report()
    manuscript = project.path("manuscript")
    methods = methods_text(project)
    if (methods and _binds_a_count(methods)) or _supplement_binds_a_count(manuscript):
        return Report()
    return Report(
        (
            Finding(
                gate=GATE,
                code="quality-not-reported",
                severity=FAIL if submission else WARN,
                message=f"the data were checked against the data dictionary, and neither the "
                f"Methods nor the supplement binds a {PREFIX} count: a reader cannot see what "
                "the data held",
                path=manuscript,
                hint="say in the Methods what was checked and what was found, binding the "
                'counts: "{{results.quality.age.out_of_range}} reports gave an impossible '
                'age and were left out"; the methods-writer skill has the outline',
            ),
        )
    )
