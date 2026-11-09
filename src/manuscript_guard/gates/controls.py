"""G12 — the controls the plan declares, held to what the analysis emitted (item 5).

An analysis that has only been run on the study's data has never shown that it can find an
answer. A control shows it: data simulated with a known effect, a positive control (an
association known to exist) or a negative control (an exposure or an outcome where no effect
is expected), put through the analysis that gives the result it stands beside. The plan
declares each in its `controls:` block (`gates/declarations.py`), with the value expected
and one of three rules that pass it, and the script of that result emits it with
`em.control()` (DESIGN.md, "Controls the plan declares, and data held out until the model is
fixed").

What is checked, from the analysis stage on, each a warning that fails at submission:

* `control-failed`: the rule does not hold on the values emitted; at submission it stays a
  warning where the main text or the supplement binds one of the control's values and the
  Deviations name its key (D5.3);
* `control-missing`: declared, and not emitted, unless the Deviations name its key;
* `control-declared-late`: not in the plan's frozen copy, so chosen after the first results,
  unless the Deviations name it; a note where the copy marks an all-synthetic first run;
* `control-changed`: in the frozen copy, and gone from the plan or declared otherwise there,
  unless the Deviations name it;
* `control-undeclared`: emitted, and no control of the plan has its key;
* `control-other-script`: emitted by a script that emitted none of the result it stands
  beside (D5.4: the same script path, which is the check's limit);
* `control-unreported`: from the drafting stage, no binding of one of its values in the main
  text or the supplement, a Markdown or a LaTeX one (Basile, 2026-11-09).
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.declarations import (
    PARTS,
    WITHIN,
    Control,
    frozen_plan,
    read_declarations,
)

GATE = "G12"


def passes(control: Control, point: float, low: float, high: float) -> bool:
    """Whether the control's rule holds on its values, as stored: the interval holds the
    expected value (or the null, which the expected value then is), or the estimate is within
    the distance of it. A value at a bound passes (D5.2)."""
    if control.rule == WITHIN:
        assert control.distance is not None
        return abs(point - control.expected) <= control.distance
    return low <= control.expected <= high


def _under(name: str, stem: str) -> bool:
    return not stem or name.startswith(f"{stem}.")


def _beside(results: Results, control: Control, fragment: Path) -> bool | None:
    """Whether the script that emitted the control emitted the result it stands beside, by
    the script each fragment names (D5.4: the same script path), so that a script writing
    its control to a fragment of its own is the same script (round 1 of PR 2a): None where
    no fragment emitted that result."""
    script = {f.path: f.generated_by for f in results.fragments}
    of = control.of
    kind, _, name = of.partition(".")
    if control.group:
        sources = [v.source for key, v in results.values.items() if key.startswith(f"{of}.")]
        if kind == "table":
            sources += [t.source for key, t in results.tables.items() if _under(key, name)]
        if kind == "model":
            sources += [m.source for key, m in results.models.items() if _under(key, name)]
    else:
        sources = [results.values[of].source] if of in results.values else []
        if kind == "table" and name in results.tables:
            sources.append(results.tables[name].source)
        if kind == "model" and name in results.models:
            sources.append(results.models[name].source)
    if not sources:
        return None
    return script.get(fragment) in {script.get(source) for source in sources}


def _values(results: Results, key: str) -> tuple[float, float, float] | None:
    found = [results.values.get(f"{key}.{part}") for part in PARTS]
    numbers = [getattr(value, "value", None) for value in found]
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in numbers):
        return None
    point, low, high = numbers
    return float(point), float(low), float(high)


def check_controls(project: Project, results: Results | None, stage: str | None) -> Report:
    """Each control the plan declares, or the analysis emits, against the other and against
    the plan's frozen copy. Asked from the analysis stage: before it, nothing is emitted."""
    from manuscript_guard.gates.design import (
        Planned,
        _named,
        _read_plan,
        _written,
        deviations_said,
        plan_path,
    )
    from manuscript_guard.policy import DESIGN, DRAFTING, SUBMISSION, stage_index

    if results is None or stage is None or stage == DESIGN:
        return Report()
    path = plan_path(project)
    text = _read_plan(path)[0] if path.is_file() else ""
    declared = read_declarations(text)
    now = {c.key: c for c in declared.controls}
    # Declared and not read: `plan-declarations-unreadable` says so, and nothing here says
    # the plan declares no such control (round 1 of PR 2a).
    refused = set(declared.refused_keys)
    kept, synthetic = frozen_plan(project)
    frozen = None if kept is None else read_declarations(kept)
    then = None if frozen is None else {c.key: c for c in frozen.controls}
    # Declared then and not read, as mistyped: not chosen late (round 2 of PR 2a).
    refused_then = set() if frozen is None else set(frozen.refused_keys)
    emitted = {key: fragment.path for fragment in results.fragments for key in fragment.controls}
    if not now and not then and not emitted:
        return Report()
    deviations = deviations_said(text)
    severity = FAIL if stage == SUBMISSION else WARN
    drafted = stage_index(stage) >= stage_index(DRAFTING)
    refs: set[str] | None = None

    def named(key: str) -> bool:
        return _named(deviations, Planned(key, False, 0))

    def as_named(key: str) -> str:
        """The key as the Deviations name it: one with no dot, bound (round 1 of PR 2a)."""
        return _written(Planned(key, False, 0))

    def reported(key: str) -> bool:
        nonlocal refs
        if refs is None:
            from manuscript_guard.contracts._schema import read_text
            from manuscript_guard.gates.synthetic import quoted_refs
            from manuscript_guard.text.reader import manuscript_files

            # A file whose text cannot be had raises here, so that the check stops at it and
            # `check` names it once: read past, its bindings were missed, and every control
            # it reported read as unreported.
            for path in manuscript_files(project):
                read_text(path)
            refs = quoted_refs(project)
        return any(ref.startswith(f"results.{key}.") for ref in refs)

    def said(code: str, message: str, hint: str, *, line: int | None = None,
             at: Path | None = None, level: str | None = None) -> Finding:  # fmt: skip
        return Finding(gate=GATE, code=code, severity=level or severity, message=message,
                       path=at or path, line=line, hint=hint)  # fmt: skip

    findings: list[Finding] = []
    passed = 0
    for key, control in now.items():
        if then is not None and key not in then and key not in refused_then and not named(key):
            findings.append(said(
                "control-declared-late",
                f"the control {key} is not in the plan as it stood when the first results "
                "were written: it was chosen after them"
                + ("; that run read synthetic data only, so no real result dates it"
                   if synthetic else ""),
                f"say under Deviations from the plan when and why {key} was added, naming "
                f"{as_named(key)}; "
                "a control chosen once the results are known shows much less",
                line=control.line, level=INFO if synthetic else None))  # fmt: skip
        elif then is not None and key in then and then[key].said() != control.said() \
                and not named(key):  # fmt: skip
            findings.append(said(
                "control-changed",
                f"the control {key} is declared otherwise than in the plan as it stood when "
                "the first results were written",
                f"say under Deviations from the plan what changed in {key} and why, naming "
                f"{as_named(key)}",
                line=control.line))  # fmt: skip
        fragment = emitted.get(key)
        values = _values(results, key)
        if fragment is None or values is None:
            if not named(key):
                findings.append(said(
                    "control-missing",
                    f"the plan declares the control {key}, and the analysis "
                    + ("emits no interval for it" if fragment else "does not emit it"),
                    f"emit it with em.control(\"{key}\", estimate, lower, upper) in the script "
                    "of the result it stands beside, or say under Deviations why not, naming "
                    f"{as_named(key)}", line=control.line))  # fmt: skip
            continue
        beside = _beside(results, control, fragment)
        if not beside:
            where = next(f.generated_by for f in results.fragments if f.path == fragment)
            findings.append(said(
                "control-other-script",
                f"the control {key} is emitted by {where}, "
                + ("and no script emits the result it stands beside, " + control.of
                   + (".*" if control.group else "") if beside is None
                   else "which emits none of the result it stands beside, " + control.of
                   + (".*" if control.group else "")),
                "emit the control in the script of that result, so that it goes through the "
                "same code", line=control.line))  # fmt: skip
        point, low, high = values
        if passes(control, point, low, high):
            passed += 1
        else:
            excused = reported(key) and named(key)
            shown = (f"{point:g}, within {control.distance:g} of {control.expected:g}"
                     if control.rule == WITHIN
                     else f"{low:g} to {high:g} around {control.expected:g}")  # fmt: skip
            findings.append(said(
                "control-failed",
                f"the control {key} fails its rule, {control.rule}: {shown} does not hold"
                + ("; the paper reports it and the Deviations name it" if excused else ""),
                f"report {key} in the paper and say under Deviations from the plan why it "
                f"failed, naming {as_named(key)}: a control that failed tells the reader "
                "something about the analysis", line=control.line,
                level=WARN if excused else None))  # fmt: skip
        if drafted and not reported(key):
            findings.append(said(
                "control-unreported",
                f"the control {key} is not reported: no value of it is bound in the main "
                "text or the supplement",
                f"bind it where the controls are reported, {{{{results.{key}.point}}}} and "
                "its interval, in the Methods, the Results or the supplement",
                line=control.line))  # fmt: skip
    for key in (then or {}):
        if key not in now and key not in refused and not named(key):
            findings.append(said(
                "control-changed",
                f"the control {key} was in the plan when the first results were written, and "
                "is gone from it",
                f"say under Deviations from the plan why {key} was dropped, naming "
                f"{as_named(key)}"))
    for key, fragment in emitted.items():
        if key not in now and key not in refused:
            findings.append(said(
                "control-undeclared",
                f"the analysis emits the control {key}, and the plan declares no control by "
                "that key, so nothing says what passes it",
                "declare it in the plan's controls: block, with its kind, of, expected and "
                "rule, and say under Deviations when it was added", at=fragment))  # fmt: skip
    return Report(tuple(findings), {"controls_passed": passed})
