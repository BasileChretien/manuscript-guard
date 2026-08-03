"""Hook handlers, reached through `manuscript-guard hook <event>`.

Routed through the CLI rather than shell scripts for two reasons. The console script is on
PATH on every platform once the package is installed, which shell scripts and `python3` are
not; and a handler that is ordinary Python is a handler that can be tested.

Three rules govern everything here.

**A hook must never break the session.** Any unexpected error exits 0 in silence. A guard
that crashes when a project is half-configured is worse than no guard, because the author
removes it and loses the guard that worked.

**A hook must be fast.** `guard-write` and `after-edit` fire on every edit, so neither loads
the full gate set: the first is a path check, the second classifies numbers in one file.
Only `session-start` and the submission guard run the gates, and those fire rarely.

**A hook blocks only what is unambiguous.** Writing to a machine-written results file is
always wrong. Prose that trips the AI-writing lint is not, so that is reported as context,
never denied.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Paths that no editor should write, relative to the project root. Each is generated, and
# editing one desynchronises it from whatever generates it.
FORBIDDEN = (
    ("results/", ".json", "results are machine-written; change the analysis and re-run it"),
    ("results/", ".sha256", "the digest is written with the fragment it covers"),
    ("build/", "", "everything in build/ is regenerated; edit the source instead"),
    (
        "profiles/reporting/",
        ".yaml",
        "checklist profiles are transcribed from the official document; "
        "edit the recipe and re-run `manuscript-guard transcribe`",
    ),
)

# Commands that mean a manuscript is about to leave the building. Matched against the whole
# command string rather than by a prefix rule: a leading env-var assignment or `cd x &&`
# defeats prefix matching, which is exactly how a submission slipped past the guard in the
# project that preceded this one.
SUBMISSION_MARKERS = re.compile(
    # The two unambiguous ones: asking for a submission pack, or asking for submission
    # standards.
    r"manuscript-guard\s+submit\b|--submission\b|"
    # Moving a submission somewhere: an action verb near the pack or a built document.
    r"\b(?:zip|tar|scp|rsync|cp|copy|mv|move|curl|wget|mail|sendmail|git\s+push)\b"
    r"[^\n]{0,120}?(?:\bsubmission\b|\.docx\b)",
    re.IGNORECASE,
)


def _read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}


def _emit(payload: dict) -> int:
    print(json.dumps(payload))
    return 0


def _deny(event: str, reason: str) -> int:
    return _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def _context(event: str, text: str) -> int:
    return _emit({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def _edited_path(payload: dict) -> Path | None:
    target = payload.get("tool_input", {}).get("file_path")
    return Path(target) if target else None


def _relative_to_project(path: Path) -> tuple[Path, str] | None:
    """Find the project root above `path`, and the path relative to it."""
    from manuscript_guard.contracts import ContractError, find_root

    try:
        root = find_root(path.parent if path.suffix else path)
    except (ContractError, OSError):
        return None
    try:
        return root, str(path.resolve().relative_to(root)).replace("\\", "/")
    except (ValueError, OSError):
        return None


# --------------------------------------------------------------------------- handlers


def guard_write(payload: dict) -> int:
    """Refuse edits to files that something else generates."""
    path = _edited_path(payload)
    if path is None:
        return 0
    found = _relative_to_project(path)
    if found is None:
        return 0
    _root, relative = found

    for prefix, suffix, why in FORBIDDEN:
        if relative.startswith(prefix) and relative.endswith(suffix):
            return _deny(
                "PreToolUse",
                f"{relative} is generated, not written. {why}.",
            )
    return 0


def after_edit(payload: dict) -> int:
    """Classify the numbers in a manuscript file the moment it is saved."""
    path = _edited_path(payload)
    if path is None or path.suffix.lower() != ".md":
        return _after_analysis_edit(path)
    found = _relative_to_project(path)
    if found is None:
        return 0
    root, relative = found

    from manuscript_guard.classify import UNCLASSIFIED, Classifier
    from manuscript_guard.contracts import load_project
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.tokens import find_atoms

    project, _ = load_project(root)
    manuscript = project.path("manuscript")
    try:
        path.resolve().relative_to(manuscript.resolve())
    except (ValueError, OSError):
        return 0

    classifier = Classifier.load(project.extra_conventions, project.extra_terms)
    text = path.read_text(encoding="utf-8", errors="replace")
    loose = [
        (atom.line, atom.text)
        for atom in find_atoms(text, mask(text))
        if classifier.classify(atom).kind == UNCLASSIFIED
    ]
    if not loose:
        return 0

    listed = "; ".join(f"line {line}: {text!r}" for line, text in loose[:6])
    more = f" (+{len(loose) - 6} more)" if len(loose) > 6 else ""
    return _context(
        "PostToolUse",
        f"{relative} has {len(loose)} number(s) bound to nothing — {listed}{more}. "
        f"Bind each with {{{{results.<key>}}}} or {{{{lit.<key>}}}}, or add it to "
        f"`conventions:` in paper.yaml with a reason.",
    )


def _after_analysis_edit(path: Path | None) -> int:
    if path is None:
        return 0
    found = _relative_to_project(path)
    if found is None:
        return 0
    _root, relative = found
    if not relative.startswith("analysis/"):
        return 0
    return _context(
        "PostToolUse",
        f"{relative} changed. The results it wrote are now stale until it is re-run, and "
        f"the Methods may no longer describe it (`manuscript-guard methods`).",
    )


def guard_submission(payload: dict) -> int:
    """Before anything that looks like a submission, hold the project to that standard."""
    command = str(payload.get("tool_input", {}).get("command", ""))
    if not SUBMISSION_MARKERS.search(command):
        return 0

    from manuscript_guard.cli import _run_gates

    cwd = Path(payload.get("cwd") or Path.cwd())
    report, project, _stage, _deferred = _run_gates(cwd, submission=True)
    if report.ok:
        return 0

    lines = [f"  {f.code}: {f.message}" for f in report.failures[:8]]
    more = f"\n  (+{len(report.failures) - 8} more)" if len(report.failures) > 8 else ""
    return _deny(
        "PreToolUse",
        f"{len(report.failures)} submission check(s) failing in {project.root.name}:\n"
        + "\n".join(lines)
        + more
        + "\n\nRun `manuscript-guard check --submission` for the full list.",
    )


def session_start(payload: dict) -> int:
    """One line on where the manuscript stands, so nobody has to remember."""
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.policy import DESCRIPTIONS

    cwd = Path(payload.get("cwd") or Path.cwd())
    report, project, stage, deferred = _run_gates(cwd)
    failing = len(report.failures)
    warnings = len(report.warnings)

    parts = [
        f"manuscript-guard: {project.root.name} at stage '{stage}' "
        f"({DESCRIPTIONS[stage]}). {failing} failing, {warnings} warning(s)."
    ]
    if deferred:
        upcoming = min(deferred, key=lambda s: list(DESCRIPTIONS).index(s))
        parts.append(f"{sum(deferred.values())} more become due at '{upcoming}'.")
    if failing:
        parts.append("Run `manuscript-guard check`.")
    return _context("SessionStart", " ".join(parts))


HANDLERS = {
    "guard-write": guard_write,
    "after-edit": after_edit,
    "guard-submission": guard_submission,
    "session-start": session_start,
}


def dispatch(event: str, payload: dict | None = None) -> int:
    """Run a handler, swallowing anything unexpected.

    A hook that raises in a project that is half-configured teaches the author to remove
    the hook, and they lose the ones that were working.
    """
    handler = HANDLERS.get(event)
    if handler is None:
        return 0
    try:
        return handler(payload if payload is not None else _read_event())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for `manuscript-guard-hook`.

    A separate console script from the main CLI, and this module imports nothing heavy at
    module level, because the Bash guard fires on *every* shell command. Routing it through
    the full CLI would load the gates, the build pipeline and the Zotero client before
    deciding the command has nothing to do with a submission.
    """
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] not in HANDLERS:
        return 0
    return dispatch(args[0])


if __name__ == "__main__":
    sys.exit(main())
