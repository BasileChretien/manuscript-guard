"""G1 and G12 — data held out from a model's development, read only by its validation (item 11).

A prediction model validated on data held out from its development is validated
independently only where nothing that built or tuned the model read those data first. The
plan declares each held-out input in its `held_out:` block (`gates/declarations.py`): the
input, the script that validates on it, the model's files, and any script that may read it
to describe it. Once the plan holds such a block, both emitters keep the record of each
script's first read of each input, `design/first_reads.yaml`, with the digests of that run's
inputs and the plan as it stood (`emit.record_first_reads`). DESIGN.md, "Controls the plan
declares, and data held out until the model is fixed".

G1, from the analysis stage, fails a leak (D11.2):

* `held-out-read-elsewhere`: a script read the held-out input, by its path or by its bytes
  under another, and the plan its first read was written under did not name it as the
  input's validator or reader.

G12, each a warning that fails at submission unless said otherwise:

* `held-out-read-before-model`: the validation script first read the input with one version
  of the model and reads another now: the model was written again after the held-out data
  were seen. It fails from the analysis stage (D11.2);
* `held-out-order-unknown`: what the record holds cannot tell: no first read recorded, or the
  model not among its inputs or the run's now, or a plan version that says nothing of the
  input; a note where the plan names no model;
* `held-out-unread`, `held-out-declared-late` and `held-out-changed`: stood down by the
  Deviations naming the input;
* `first-reads-unreadable`: the record does not read as the emitters write it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.emit import FIRST_READS, _first_reads_shaped, input_digest
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.declarations import HeldOut, read_declarations

#: A finding of G1's and G12's for held-out data.
G1, G12 = "G1", "G12"


@dataclass(frozen=True)
class Read:
    """A script's read of a held-out input: the path it declared, its first read in the
    record (or None), and whether a fragment declares it now."""

    script: str
    path: str
    first: dict | None
    now: bool


@dataclass
class _Held:
    """What the plan, its frozen copy and the record of first reads say of held-out data."""

    plan: Path
    text: str
    now: list[HeldOut]
    then: dict[str, HeldOut] | None
    record: dict | None
    unreadable: bool
    reads: dict[str, list[Read]] = field(default_factory=dict)
    #: Each script's inputs now, by path, with their digests, as its fragment declares them.
    inputs_now: dict[str, dict[str, str]] = field(default_factory=dict)


def _record(root: Path) -> tuple[dict | None, bool]:
    path = root / FIRST_READS
    if not path.is_file():
        return None, False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, True
    return (record, False) if _first_reads_shaped(record) else (None, True)


def _held(project: Project, results: Results) -> _Held | None:
    """The held-out data of the plan, and every read of each: None where the plan declares
    none, now or in its frozen copy."""
    from manuscript_guard.gates.declarations import frozen_plan
    from manuscript_guard.gates.design import _read_plan, plan_path

    plan = plan_path(project)
    text = _read_plan(plan)[0] if plan.is_file() else ""
    now = list(read_declarations(text).held_out)
    kept, _synthetic = frozen_plan(project)
    then = None if kept is None else {h.input: h for h in read_declarations(kept).held_out}
    if not now and not then:
        return None
    record, unreadable = _record(project.root)
    held = _Held(plan, text, now, then, record, unreadable)
    for fragment in results.fragments:
        held.inputs_now.setdefault(fragment.generated_by, {}).update(
            {str(i["path"]): str(i.get("sha256")) for i in fragment.inputs
             if isinstance(i, dict) and "path" in i}  # fmt: skip
        )
    for entry in now:
        held.reads[entry.input] = _reads_of(project, results, entry, record)
    return held


def _reads_of(
    project: Project, results: Results, entry: HeldOut, record: dict | None
) -> list[Read]:
    """Each script that read the input, by its path or by its bytes under another: in a
    fragment now, an input not declared synthetic, or in the record of first reads."""
    digests = {i.get("sha256") for f in results.fragments for i in f.inputs
               if isinstance(i, dict) and i.get("path") == entry.input}  # fmt: skip
    for read in (record or {}).get("reads", []):
        digests |= {i.get("sha256") for i in read.get("inputs", []) if isinstance(i, dict)
                    and i.get("path") == entry.input}  # fmt: skip
    on_disk = project.root / entry.input
    if on_disk.is_file():
        digests.add(input_digest(on_disk))
    digests.discard(None)

    def held(path: object, digest: object) -> bool:
        return path == entry.input or digest in digests

    seen: dict[tuple[str, str], bool] = {}
    for fragment in results.fragments:
        for given in fragment.inputs:
            if isinstance(given, dict) and not given.get("synthetic") and \
                    held(given.get("path"), given.get("sha256")):  # fmt: skip
                seen[(fragment.generated_by, str(given["path"]))] = True
    firsts: dict[tuple[str, str], dict] = {}
    for read in (record or {}).get("reads", []):
        digest = next((i.get("sha256") for i in read.get("inputs", []) if isinstance(i, dict)
                       and i.get("path") == read["input"]), None)  # fmt: skip
        if held(read["input"], digest):
            firsts.setdefault((read["script"], read["input"]), read)
            seen.setdefault((read["script"], read["input"]), False)
    return [Read(script, path, firsts.get((script, path)), now)
            for (script, path), now in seen.items()]  # fmt: skip


def _allowed(record: dict, read: Read, entry: HeldOut) -> bool | None:
    """Whether the plan the read was first written under named its script as the input's
    validator or reader: None where that version says nothing of the input."""
    assert read.first is not None
    version = record["plans"].get(read.first["plan"])
    if not isinstance(version, str):
        return None
    declared = next((h for h in read_declarations(version).held_out if h.input == entry.input),
                    None)  # fmt: skip
    if declared is None:
        return None
    return read.script in declared.readers()


def check_held_out_reads(project: Project, results: Results | None, stage: str | None) -> Report:
    """G1: a script that read held-out data the plan did not let it read when it first did
    (D11.2). Asked from the analysis stage; the policy defers it before."""
    if results is None or stage is None:
        return Report()
    held = _held(project, results)
    if held is None or held.record is None:
        return Report()
    findings = []
    for entry in held.now:
        for read in held.reads[entry.input]:
            if read.first is None or _allowed(held.record, read, entry) is not False:
                continue
            under = "" if read.path == entry.input else f" (its bytes, as {read.path})"
            findings.append(Finding(
                gate=G1, code="held-out-read-elsewhere", severity=FAIL,
                message=f"{read.script} read the held-out input {entry.input}{under}, first on "
                f"{read.first.get('read_at', 'a day not recorded')}, and the plan did not then "
                f"name it as the input's validator or reader: the validation by "
                f"{entry.validated_by} is not independent",
                path=held.plan, line=entry.line,
                hint="validate on data no script that built or tuned the model has read, or "
                "take the declaration out of the plan and say why under Deviations from the "
                "plan; the paper then cannot call the validation independent",
            ))  # fmt: skip
    return Report(tuple(findings))


_PATH_EDGE = re.compile(r"(?<![\w./-])\./")


def input_named(deviations: str, path: str) -> bool:
    """Whether the Deviations name the input by its path: `_named`'s rule with the slash
    added, a leading `./` left off on both sides (DESIGN.md, item 11)."""
    said = _PATH_EDGE.sub("", deviations)
    path = path.removeprefix("./")
    return bool(re.search(rf"(?<![\w./-]){re.escape(path)}(?![\w/-]|\.\w)", said))


def check_held_out(project: Project, results: Results | None, stage: str | None) -> Report:
    """G12: the validation's first read of each held-out input against the model it
    validates, and the declarations against the frozen copy and the record."""
    from manuscript_guard.gates.design import deviations_said
    from manuscript_guard.policy import DESIGN, SUBMISSION

    if results is None or stage is None or stage == DESIGN:
        return Report()
    held = _held(project, results)
    if held is None:
        return Report()
    deviations = deviations_said(held.text)
    severity = FAIL if stage == SUBMISSION else WARN
    findings: list[Finding] = []

    def said(code: str, message: str, hint: str, *, line: int | None = None,
             level: str | None = None) -> None:  # fmt: skip
        findings.append(Finding(gate=G12, code=code, severity=level or severity,
                                message=message, path=held.plan, line=line, hint=hint))  # fmt: skip

    if held.unreadable:
        findings.append(Finding(
            gate=G12, code="first-reads-unreadable", severity=severity,
            message=f"{FIRST_READS.as_posix()} does not read as the emitters write it, so no "
            "first read of the held-out data can be told",
            path=project.root / FIRST_READS,
            hint="it is written by the emitters and never by hand; restore it from version "
            "control",
        ))  # fmt: skip
    for entry in held.now:
        named = input_named(deviations, entry.input)
        before = held.then.get(entry.input) if held.then is not None else None
        if held.then is not None and before is None and not named:
            said("held-out-declared-late",
                 f"the held-out input {entry.input} is not in the plan as it stood when the "
                 "first results were written: reads of it before then were not recorded",
                 f"say under Deviations from the plan when {entry.input} was held out, "
                 "naming it", line=entry.line)  # fmt: skip
        elif before is not None and before.said() != entry.said() and not named:
            said("held-out-changed",
                 f"the held-out input {entry.input} is declared with another script, model or "
                 "reader than in the plan as it stood when the first results were written",
                 f"say under Deviations from the plan what changed and why, naming "
                 f"{entry.input}", line=entry.line)  # fmt: skip
        _order(held, entry, named, said)
    for path in held.then or {}:
        if path not in {h.input for h in held.now} and not input_named(deviations, path):
            said("held-out-changed",
                 f"the held-out input {path} was in the plan when the first results were "
                 "written, and is gone from it",
                 f"say under Deviations from the plan why {path} is no longer held out, "
                 "naming it; the paper then cannot call its validation independent")
    return Report(tuple(findings), {"held_out_reads": sum(map(len, held.reads.values()))})


def _order(held: _Held, entry: HeldOut, named: bool, said) -> None:
    """The validation's first read against the model it validates, and every other read
    whose leave the record cannot tell."""
    reads = held.reads[entry.input]
    validator = [r for r in reads if r.script == entry.validated_by and r.path == entry.input]
    for read in reads:
        if read.script == entry.validated_by and read.path == entry.input:
            continue
        if read.first is None or (held.record and _allowed(held.record, read, entry) is None):
            said("held-out-order-unknown",
                 f"{read.script} read the held-out input {entry.input}"
                 + ("" if read.path == entry.input else f" (as {read.path})")
                 + ", and the record of first reads cannot tell whether the plan let it",
                 "keep design/first_reads.yaml committed, as the emitters write it; a script "
                 "that only describes the data is named in the entry's read_by",
                 line=entry.line)  # fmt: skip
    if not validator:
        if not named:
            said("held-out-unread",
                 f"the plan holds out {entry.input} for {entry.validated_by}, which has not "
                 "read it",
                 f"run the validation, declaring {entry.input} as its input, or say under "
                 "Deviations from the plan why not, naming it", line=entry.line)  # fmt: skip
        return
    (read,) = validator[:1]
    if not entry.model:
        said("held-out-order-unknown",
             f"{entry.validated_by} builds the model it validates on {entry.input}, as the "
             "plan names no model, so whether the model was settled first cannot be told",
             "where the model is a file another script writes, name it under model",
             line=entry.line, level=INFO)  # fmt: skip
        return
    if read.first is None:
        said("held-out-order-unknown",
             f"no first read of {entry.input} by {entry.validated_by} is recorded, so whether "
             "the model was settled before cannot be told",
             "keep design/first_reads.yaml committed, as the emitters write it",
             line=entry.line)  # fmt: skip
        return
    at_first = {i.get("path"): i.get("sha256") for i in read.first.get("inputs", [])
                if isinstance(i, dict)}  # fmt: skip
    current = _current(held, entry)
    for model in entry.model:
        if model not in at_first or model not in current:
            said("held-out-order-unknown",
                 f"{entry.validated_by} did not declare the model {model} as an input "
                 + ("when it first read " + entry.input if model not in at_first else "now"),
                 "declare the model's files as inputs of the validation script",
                 line=entry.line)  # fmt: skip
        elif at_first[model] != current[model]:
            said("held-out-read-before-model",
                 f"{entry.validated_by} first read the held-out input {entry.input} on "
                 f"{read.first.get('read_at', 'a day not recorded')} with another version of "
                 f"the model {model} than it reads now: the model was written again after "
                 "the held-out data were seen, and the validation is not independent",
                 "validate on data nobody has read, or take the declaration out of the plan "
                 "and say why under Deviations from the plan",
                 line=entry.line, level=FAIL)  # fmt: skip


def _current(held: _Held, entry: HeldOut) -> dict[str, str]:
    """The digests of the inputs the validation script's fragment declares now."""
    return held.inputs_now.get(entry.validated_by, {})
