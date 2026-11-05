"""What a GitHub Actions job says of a `check --json` report.

The composite actions at the root of manuscript-guard's repository run this: `folders` says
where the project keeps its manuscript and its documents, `report` writes the job's summary,
GitHub's annotations and the step's outputs from the report, and `badge` writes the badge's
words. It decides nothing: whether the manuscript passed is the report's `ok`, which `check`
set.

At its top it imports nothing but the standard library, and only `folders` imports the
package, so that the badge's action, which installs nothing and runs nothing of the project,
can run this file by its path.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

#: The stages, as `policy.STAGES` names them (a test holds the two equal).
STAGES = ("design", "analysis", "drafting", "internal-review", "submission")

#: How many annotations of each kind a step prints: GitHub shows only some of them on a pull
#: request.
ANNOTATIONS = 50

#: How many findings of each kind the summary lists, how much of a message and of a place,
#: and of the lines on what was recorded: GitHub drops a step's summary larger than 1 MiB
#: whole, so the findings listed also stop where `BUDGET` bytes would be passed, with room to
#: spare. `check.json` in the artefact has every finding.
LISTED = 200
MESSAGE = 500
PLACE = 300
RECORDED_LINE = 300
RECORDED_LINES = 200
BUDGET = 900_000

#: The badge's label, and the colour of each outcome. Blue for a pass at every stage, not
#: green: a pass at `design` holds almost nothing, and green reads as "all is well".
LABEL = "manuscript-guard check"
COLOURS = {"passes": "blue", "fails": "red", "did not run": "lightgrey"}


def read_report(path: Path) -> dict | None:
    """The report `check --json` wrote, or None where there is none to read."""
    try:
        said = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(said, dict) or not isinstance(said.get("ok"), bool):
        return None
    return said


def outcome(report: dict | None, exit_code: int) -> str:
    """What check did: `passes`, `fails` or `did not run`. It exits 0 or 1 with a report,
    and with any other code it did not run to the end, whatever it printed."""
    if report is None or exit_code not in (0, 1):
        return "did not run"
    return "passes" if report["ok"] else "fails"


def relative(path: str | None, workspace: Path) -> str | None:
    """The finding's file from the repository's root, as GitHub places an annotation; None
    where it has none or is outside the repository."""
    if not path:
        return None
    try:
        return Path(path).resolve().relative_to(workspace.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _data(text: str) -> str:
    """A workflow command's message, escaped as GitHub reads it back."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _property(text: str) -> str:
    """A workflow command's property, escaped as GitHub reads it back."""
    return _data(text).replace(":", "%3A").replace(",", "%2C")


def annotation(finding: dict, workspace: Path) -> str | None:
    """GitHub's annotation of a failure or a warning; None for a note."""
    kind = {"fail": "error", "warn": "warning"}.get(finding.get("severity"))
    if kind is None:
        return None
    places = []
    file = relative(finding.get("path"), workspace)
    if file is not None:
        places.append(f"file={_property(file)}")
        for key, name in (("line", "line"), ("col", "col")):
            if isinstance(finding.get(key), int):
                places.append(f"{name}={finding[key]}")
    title = f"{finding.get('gate')} {finding.get('code')}"
    places.append(f"title={_property(title)}")
    message = str(finding.get("message") or "")
    if finding.get("hint"):
        message += f"\nhint: {finding['hint']}"
    return f"::{kind} {','.join(places)}::{_data(message)}"


def annotations(report: dict, workspace: Path) -> list[str]:
    """The annotations, failures first, at most `ANNOTATIONS` of each kind."""
    lines: list[str] = []
    for severity in ("fail", "warn"):
        found = [f for f in report.get("findings", []) if f.get("severity") == severity]
        lines += [annotation(f, workspace) for f in found[:ANNOTATIONS]]
        if len(found) > ANNOTATIONS:
            lines.append(f"::notice::{len(found) - ANNOTATIONS} more of these are in the "
                         "job's summary and in check.json")  # fmt: skip
    return [line for line in lines if line]


def _place(finding: dict, workspace: Path) -> str:
    where = relative(finding.get("path"), workspace) or finding.get("path") or ""
    for key in ("line", "col"):
        if isinstance(finding.get(key), int):
            where += f":{finding[key]}"
    return where


def _longest_run(text: str, mark: str = "`") -> int:
    longest = run = 0
    for character in text:
        run = run + 1 if character == mark else 0
        longest = max(longest, run)
    return longest


def code(text: str) -> str:
    """`text` on one line as a Markdown code span, which shows it as it is: a message quotes
    the manuscript, and a contributor's sentence must not become a link, a picture or
    markup in the summary. The span's backticks outnumber any run of them inside it."""
    text = " ".join(text.split())
    ticks = "`" * (_longest_run(text) + 1)
    padded = f" {text} " if text.startswith("`") or text.endswith("`") else text
    return f"{ticks}{padded}{ticks}"


def fenced(lines: list[str]) -> list[str]:
    """`lines` as a fenced block of text, its fence longer than any run of backticks in
    them, so that no line, a reviewer's name among them, can close it."""
    fence = "`" * max(3, _longest_run("\n".join(lines)) + 1)
    return [f"{fence}text", *lines, fence]


def _item(finding: dict, workspace: Path) -> str:
    """One finding as a line of the summary: its gate and code, its place, its message."""
    place = _clipped(_place(finding, workspace), PLACE)
    message = _clipped(str(finding.get("message") or ""), MESSAGE)
    at = f" {code(place)}" if place else ""
    return f"- **{finding.get('gate')}** {code(str(finding.get('code')))}{at}: {code(message)}"


def summary(report: dict | None, exit_code: int, version: str, workspace: Path) -> str:
    """The job's summary: what was held to what, what is open, and what no gate decides."""
    said = outcome(report, exit_code)
    lines = ["## manuscript-guard check", ""]
    if said == "did not run":
        lines.append(f"`check` did not run to the end (exit code {exit_code}): what it printed "
                     "is in the job's log.")  # fmt: skip
        return "\n".join(lines) + "\n"
    stage = report.get("stage", "the stage paper.yaml declares")
    lines.append(f"manuscript-guard {version} held the manuscript to the stage **{stage}**, "
                 f"and check **{said}** there.")  # fmt: skip
    lines.append("")
    lines.append("A pass means that no finding due at this stage is open, and is not evidence "
                 "that the paper is right; what no gate decides is listed below.")  # fmt: skip
    findings = report.get("findings", [])
    notes = sum(1 for f in findings if f.get("severity") == "info")
    tail = ["", f"And {notes} note{'' if notes == 1 else 's'}, in check.json."] if notes else []
    tail += _recorded(report.get("assurance") or [])
    # What is left of the budget for the findings, each kind's "more" line kept room for.
    room = BUDGET - _size(lines) - _size(tail) - 200
    for severity, heading in (("fail", "Failing"), ("warn", "Warnings")):
        found = [f for f in findings if f.get("severity") == severity]
        if not found:
            continue
        lines += ["", f"### {heading}", ""]
        shown = 0
        for finding in found[:LISTED]:
            item = _item(finding, workspace)
            if _size([item]) > room:
                break
            lines.append(item)
            room -= _size([item])
            shown += 1
        if shown < len(found):
            lines.append(f"- and {len(found) - shown} more, in check.json")
    return "\n".join(lines + tail) + "\n"


def _size(lines: list[str]) -> int:
    """How many bytes `lines` take in the summary, a line break after each."""
    return sum(len(line.encode("utf-8")) + 1 for line in lines)


def _clipped(text: str, most: int) -> str:
    return text if len(text) <= most else text[:most] + " ..."


def _recorded(lines: list) -> list[str]:
    """The lines on what was checked and recorded, as a block of text: each clipped to
    `RECORDED_LINE` characters and a mark that it was, and the first `RECORDED_LINES` of them,
    with a line saying how many more there are. A reviewer's name is the project's text, and a
    long one must not take GitHub's summary away."""
    kept = [_clipped(str(line), RECORDED_LINE) for line in lines[:RECORDED_LINES]]
    if len(lines) > RECORDED_LINES:
        kept.append(f"... and {len(lines) - RECORDED_LINES} more lines, in check.json")
    return ["", "### What was checked, by what", "", *fenced(kept)] if kept else []


def badge(ok: str, stage: str) -> dict:
    """The badge's words, as shields.io's endpoint reads them. `ok` is "true", "false", or
    empty where check did not run; `stage` one of the five, or empty with an empty `ok`.
    Anything else is refused, so that a badge never says what no report said."""
    if ok not in ("true", "false", "") or stage not in (*STAGES, ""):
        raise ValueError(f"no badge for ok={ok!r} and stage={stage!r}")
    if ok and not stage:
        raise ValueError(f"no badge for ok={ok!r} without a stage")
    said = "did not run" if not ok else ("passes" if ok == "true" else "fails")
    message = said if said == "did not run" else f"{said} at stage {stage}"
    return {"schemaVersion": 1, "label": LABEL, "message": message, "color": COLOURS[said]}


def _append(path: str | None, text: str) -> None:
    if path:
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


def _report(args: argparse.Namespace) -> int:
    report = read_report(Path(args.report))
    workspace = Path(args.workspace or os.environ.get("GITHUB_WORKSPACE") or Path.cwd())
    said = outcome(report, args.exit_code)
    if report is not None and said != "did not run":
        for line in annotations(report, workspace):
            print(line)
    _append(os.environ.get("GITHUB_STEP_SUMMARY"),
            summary(report, args.exit_code, args.version, workspace))  # fmt: skip
    ok = "" if said == "did not run" else ("true" if said == "passes" else "false")
    # Held to the five, so that no text of the report's reaches the outputs, a line of its
    # own among them least of all.
    stage = report.get("stage") if said != "did not run" else ""
    stage = stage if stage in STAGES else ""
    _append(os.environ.get("GITHUB_OUTPUT"), f"ok={ok}\nstage={stage}\n")
    return 0


def folders(project: Path) -> dict[str, str]:
    """Where the project keeps its manuscript and its documents, as `paths:` in paper.yaml
    puts them, and whether the manuscript is LaTeX: what the action installs and copies by.
    The package is imported here and nowhere else in this file, so that the badge's action,
    which installs nothing, never needs it. Where paper.yaml cannot be read, the folders it
    would have by default; check then says what is wrong with it."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.contracts._schema import ContractError
    from manuscript_guard.text.reader import LATEX, manuscript_format

    manuscript, build = project / "manuscript", project / "build"
    try:
        loaded, _ = load_project(project)
        manuscript, build = loaded.path("manuscript"), loaded.path("build")
    except (ContractError, OSError, ValueError):
        pass
    said = {"manuscript": str(manuscript), "build": str(build),
            "latex": "true" if manuscript_format(manuscript) == LATEX else "false"}  # fmt: skip
    # A line break would end an output and begin another of the folder's choosing.
    if any("\n" in value or "\r" in value for value in said.values()):
        raise ValueError("paper.yaml names a folder with a line break in it")
    return said


def _folders(args: argparse.Namespace) -> int:
    try:
        said = folders(Path(args.path))
    except ValueError as exc:
        print(f"manuscript-guard: {exc}", file=sys.stderr)
        return 2
    _append(os.environ.get("GITHUB_OUTPUT"), "".join(f"{k}={v}\n" for k, v in said.items()))
    for key, value in said.items():
        print(f"{key}: {value}")
    return 0


def _badge(args: argparse.Namespace) -> int:
    try:
        words = badge(args.ok, args.stage)
    except ValueError as exc:
        print(f"manuscript-guard badge: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(words) + "\n", encoding="utf-8", newline="\n")
    print(f"{words['label']} | {words['message']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci_report", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report", help="the summary, the annotations and the outputs")
    report.add_argument("--report", required=True, help="the file `check --json` wrote")
    report.add_argument("--exit-code", type=int, required=True, help="what `check` exited with")
    report.add_argument("--version", required=True, help="what `manuscript-guard --version` said")
    report.add_argument("--workspace", help="the repository's root; GITHUB_WORKSPACE otherwise")
    report.set_defaults(func=_report)
    where = sub.add_parser("folders", help="where the project keeps its manuscript and documents")
    where.add_argument("--path", required=True, help="the project's folder")
    where.set_defaults(func=_folders)
    words = sub.add_parser("badge", help="the badge's words, as shields.io's endpoint reads them")
    words.add_argument("--ok", required=True)
    words.add_argument("--stage", required=True)
    words.add_argument("--out", required=True)
    words.set_defaults(func=_badge)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
