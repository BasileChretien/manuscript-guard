"""What `setup questions` and `setup apply` print: text for a person, JSON for an agent.

The JSON is `manuscript-guard/setup-questions/1` and `manuscript-guard/setup-applied/1`
(`contracts/schemas/`, docs/setup.md). A field added keeps `/1`; a field renamed or removed,
or a value added to a fixed list, makes it `/2`; a question's id is the place its answer is
written at and is not renamed.
"""

from __future__ import annotations

import json
from typing import Any

from manuscript_guard.setup.answers import ANSWERS_FILE
from manuscript_guard.setup.apply import Applied
from manuscript_guard.setup.questions import Asked, Question, Step

QUESTIONS_SCHEMA = "manuscript-guard/setup-questions/1"
APPLIED_SCHEMA = "manuscript-guard/setup-applied/1"


def _question(question: Question) -> dict[str, Any]:
    return {
        "id": question.id,
        "question": question.question,
        "why": question.why,
        "kind": question.kind,
        "options": [{"value": option.value, "label": option.label, "effect": option.effect}
                    for option in question.options],  # fmt: skip
        "recommended": question.recommended,
        "other": question.other,
        "shortlist": question.shortlist,
        "example": question.example,
        "problem": question.problem,
    }


def _step(step: Step) -> dict[str, Any]:
    return {"skill": step.skill, "title": step.title, "why": step.why, "who": step.who}


def asked_dict(asked: Asked) -> dict[str, Any]:
    from manuscript_guard import __version__

    return {
        "schema": QUESTIONS_SCHEMA,
        "tool_version": __version__,
        "folder": str(asked.folder.root),
        "project": "under-way" if asked.folder.is_project else "new",
        "answers_file": ANSWERS_FILE,
        "ready": asked.ready,
        "questions": [_question(question) for question in asked.questions],
        "waiting": [{"id": place, "on": list(on)} for place, on in asked.waiting],
        "known": [{"id": k.id, "value": k.value, "said": k.said} for k in asked.known],
        "after": [_step(step) for step in asked.after],
    }


def asked_json(asked: Asked) -> str:
    return json.dumps(asked_dict(asked), ensure_ascii=False, indent=2)


def _value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def asked_text(asked: Asked) -> str:
    lines = []
    if asked.known:
        lines.append("Decided already:")
        lines += [f"  {k.id}: {_value(k.value)} ({k.said})" for k in asked.known]
    for question in asked.questions:
        lines += ["", f"{question.id}: {question.question}", f"  {question.why}"]
        if question.problem:
            lines.append(f"  The answer written cannot be taken: {question.problem}.")
        for option in question.options:
            mark = " (recommended)" if option.value == question.recommended else ""
            lines.append(f"  - {_value(option.value)}: {option.label}{mark}; {option.effect}")
        if question.other:
            lines.append(f"  - or {question.other}")
    for place, on in asked.waiting:
        lines += ["", f"{place}: asked once {', '.join(on)} is answered"]
    if asked.ready:
        lines += ["", f"Every question is answered in {ANSWERS_FILE}: "
                  "`manuscript-guard setup apply --dry-run` shows what it would write."]
    else:
        lines += ["", f"Each answer goes in {ANSWERS_FILE}, at its question's place."]
    return "\n".join(lines).lstrip("\n")


def applied_dict(applied: Applied, folder: str) -> dict[str, Any]:
    from manuscript_guard import __version__

    def changes(found):
        return [{"file": c.file, "what": c.what, "why": c.why} for c in found]

    return {
        "schema": APPLIED_SCHEMA,
        "tool_version": __version__,
        "folder": folder,
        "dry_run": applied.dry_run,
        "ok": applied.ok,
        "refused": applied.refused,
        "open": list(applied.open),
        "written": changes(applied.written),
        "kept": changes(applied.kept),
        "notes": list(applied.notes),
        "tools": [{"name": t.name, "found": t.found, "said": t.said} for t in applied.tools],
        "after": [_step(step) for step in applied.after],
    }


def applied_json(applied: Applied, folder: str) -> str:
    return json.dumps(applied_dict(applied, folder), ensure_ascii=False, indent=2)


def applied_text(applied: Applied) -> str:
    if not applied.ok:
        said = [f"Nothing more was written: {applied.refused}."]
        if applied.open:
            said.append(f"Still open: {', '.join(applied.open)}; `manuscript-guard setup "
                        "questions` puts each.")
        return "\n".join(said)
    lines = ["Would be written:" if applied.dry_run else "Written:"]
    lines += [f"  {c.file}  {c.what} ({c.why})" for c in applied.written] or ["  nothing"]
    if applied.kept:
        lines += ["", "Kept as it was:"]
        lines += [f"  {c.file}  {c.what}: {c.why}" for c in applied.kept]
    for note in applied.notes:
        lines += ["", note]
    if applied.tools:
        lines += ["", "This machine:"]
        lines += [f"  {t.name}: {t.said}" for t in applied.tools]
    if applied.after:
        lines += ["", "Then:"]
        for step in applied.after:
            by = f"the {step.skill} skill" if step.skill else "the author"
            lines.append(f"  {step.title} ({by}): {step.why}")
    return "\n".join(lines)
