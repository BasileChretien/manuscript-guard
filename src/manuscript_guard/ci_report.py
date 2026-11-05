"""What a GitHub Actions job says of a `check --json` report.

The composite actions at the root of manuscript-guard's repository run this: `report` writes
the job's summary, GitHub's annotations and the step's outputs from the report, and `badge`
writes the badge's words. It reads only what it is given and decides nothing: whether the
manuscript passed is the report's `ok`, which `check` set.

It imports nothing but the standard library, so that the badge's action, which installs
nothing and runs nothing of the project, can run this file by its path.
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
#: request, and the summary has them all.
ANNOTATIONS = 50

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


def _plain(text: str) -> str:
    """`text` as Markdown shows it, on one line: a message quotes the manuscript, and a
    contributor's sentence must not become a link or a picture in the summary."""
    text = " ".join(text.split())
    # Each escaped as CommonMark lets any ASCII punctuation be: the backslash first.
    for mark in "\\`*_[]<>|#!&":
        text = text.replace(mark, "\\" + mark)
    return text


def _item(finding: dict, workspace: Path) -> str:
    """One finding as a line of the summary: its gate and code, its place, its message."""
    place = _place(finding, workspace).replace("`", "'")
    message = _plain(str(finding.get("message") or ""))
    at = f" `{place}`" if place else ""
    return f"- **{finding.get('gate')}** `{finding.get('code')}`{at}: {message}"


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
    for severity, heading in (("fail", "Failing"), ("warn", "Warnings")):
        found = [f for f in findings if f.get("severity") == severity]
        if found:
            lines += ["", f"### {heading}", ""]
            lines += [_item(f, workspace) for f in found]
    notes = sum(1 for f in findings if f.get("severity") == "info")
    if notes:
        lines += ["", f"And {notes} note{'' if notes == 1 else 's'}, in check.json."]
    if report.get("assurance"):
        lines += ["", "### What was checked, by what", "", "```text", *report["assurance"], "```"]
    return "\n".join(lines) + "\n"


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
    words = sub.add_parser("badge", help="the badge's words, as shields.io's endpoint reads them")
    words.add_argument("--ok", required=True)
    words.add_argument("--stage", required=True)
    words.add_argument("--out", required=True)
    words.set_defaults(func=_badge)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
