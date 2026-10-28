"""What `next` prints: the decision as JSON (`manuscript-guard/next/1`) or as text."""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.findings import FAIL, INFO, WARN, Finding
from manuscript_guard.guide.model import (
    ASK,
    AUTHOR,
    COUNTED_GATES,
    PROJECT,
    SCHEMA,
    SHOWN_FINDINGS,
    UNREADABLE,
    Action,
    Option,
    State,
    _where,
    shown,
)
from manuscript_guard.policy import DESCRIPTIONS, STAGES, SUBMISSION


def _next_stage(state: State) -> str | None:
    if state.stage not in STAGES or state.stage == SUBMISSION:
        return None
    return STAGES[STAGES.index(state.stage) + 1]


def _counts(state: State) -> dict:
    by_gate = {gate: {FAIL: 0, WARN: 0, INFO: 0} for gate in COUNTED_GATES}
    for finding in state.findings:
        by_gate.setdefault(finding.gate, {FAIL: 0, WARN: 0, INFO: 0})
        by_gate[finding.gate][finding.severity] = by_gate[finding.gate].get(
            finding.severity, 0) + 1
    total = {level: sum(1 for f in state.findings if f.severity == level)
             for level in (FAIL, WARN, INFO)}  # fmt: skip
    deferred = {stage: state.deferred[stage] for stage in STAGES if stage in state.deferred}
    return {**total, "by_gate": by_gate, "deferred": deferred}


def _finding(finding: Finding, root: Path) -> dict:
    return {"code": finding.code, "path": _where(finding, root) or None, "line": finding.line,
            "message": finding.message}  # fmt: skip


def _option(option: Option) -> dict:
    return {"id": option.id, "label": option.label, "effect": option.effect,
            "command": shown(option.argv), "argv": list(option.argv),
            "placeholders": dict(option.placeholders), "who": option.who}  # fmt: skip


def _action(action: Action, root: Path) -> dict:
    choice = action.choice
    return {
        "id": action.id, "rule": action.rule, "tier": action.tier, "title": action.title,
        "why": action.why, "codes": list(action.codes), "count": action.count,
        "skill": action.skill, "who": action.who, "command": shown(action.argv),
        "argv": None if action.argv is None else list(action.argv),
        "findings": [_finding(f, root) for f in action.findings[:SHOWN_FINDINGS]],
        "choice": None if choice is None else {
            "question": choice.question, "recommended": choice.recommended,
            "options": [_option(option) for option in choice.options],
        },
    }  # fmt: skip


def to_dict(state: State, actions: list[Action]) -> dict:
    project = state.kind == PROJECT
    checked = state.checker
    return {
        "schema": SCHEMA, "tool_version": __version__, "root": state.root.as_posix(),
        "project": {"kind": state.kind, "format": state.format if project else None,
                    "error": state.error},
        "stage": {"current": state.stage, "next": _next_stage(state),
                  "description": DESCRIPTIONS.get(state.stage or "")},
        "counts": _counts(state),
        "checker": None if checked is None else {
            "items": checked.items, "outstanding": checked.outstanding,
            "stale": checked.stale, "disagreements": checked.disagreements},
        "notes": list(state.notes),
        "actions": [_action(action, state.root) for action in actions],
    }  # fmt: skip


def to_json(state: State, actions: list[Action]) -> str:
    return json.dumps(to_dict(state, actions), indent=2, ensure_ascii=True)


def render(state: State, actions: list[Action], *, every: bool = False, shown_at_most: int = 3
           ) -> str:  # fmt: skip
    """The decision as text: the first actions in full, the rest by title unless `every`."""
    counts = _counts(state)
    lines = [f"manuscript-guard {__version__} — {state.root.as_posix()}"]
    if state.kind == PROJECT:
        following = _next_stage(state)
        lines.append(f"stage: {state.stage} ({DESCRIPTIONS[state.stage]})"
                     + (f"; next: {following}" if following else ""))  # fmt: skip
        waiting = sum(counts["deferred"].values())
        lines.append(f"{counts[FAIL]} failing, {counts[WARN]} warnings, {counts[INFO]} notes"
                     + (f"; {waiting} not due yet" if waiting else ""))  # fmt: skip
    elif state.kind == UNREADABLE:
        lines.append(f"paper.yaml cannot be read: {state.error}")
    else:
        lines.append("no manuscript-guard project here")
    lines += [f"note: {note}" for note in state.notes]
    if not actions:
        lines.append("\nNothing to do: every gate passes and no step is due.")
    full = actions if every else actions[:shown_at_most]
    for number, action in enumerate(full, 1):
        lines += [""] + _rendered(number, action, state.root)
    left = actions[len(full):]
    if left:
        lines.append(f"\n{len(left)} more: " + "; ".join(a.title for a in left))
        lines.append("`manuscript-guard next --all` shows each in full.")
    return "\n".join(lines)


def _rendered(number: int, action: Action, root: Path) -> list[str]:
    lines = [f"{number}. {action.title}", f"   {action.why}"]
    if action.skill:
        lines.append(f"   skill: {action.skill}")
    if action.argv is not None:
        lines.append(f"   run: {shown(action.argv)}" + ("  (ask the author first)"
                                                       if action.who == ASK else ""))
    for finding in action.findings[:SHOWN_FINDINGS]:
        where = _where(finding, root)
        where = f" {where}" + (f":{finding.line}" if finding.line else "") if where else ""
        lines.append(f"   - {finding.code}{where}: {finding.message}")
    if action.count > SHOWN_FINDINGS:
        lines.append(f"   and {action.count - SHOWN_FINDINGS} more")
    if action.choice is not None:
        lines.append(f"   {action.choice.question}")
        for index, option in enumerate(action.choice.options, 1):
            mark = " (recommended)" if option.id == action.choice.recommended else ""
            who = {AUTHOR: "; the author runs it", ASK: "; ask the author first"}.get(
                option.who, "")
            lines.append(f"   {index}) {option.label}{mark}: {option.effect}{who}")
            lines.append(f"      {shown(option.argv)}")
    return lines
