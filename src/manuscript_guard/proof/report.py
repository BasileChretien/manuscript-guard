"""The report of a proof's comparison: on the screen, as a list for the reply to the
production office (`--out`), and as JSON (`--json`). Nothing here sends anything."""

from __future__ import annotations

import json
from pathlib import Path

from manuscript_guard.proof import ProofReport
from manuscript_guard.proof.compare import ADDED, COPY_EDIT, CORRECTION, MOVED, Change
from manuscript_guard.proof.tokens import TYPOGRAPHY

#: The longest text a line of the screen report quotes.
QUOTE = 160
_HEADINGS = (
    (CORRECTION, "Corrections to ask for"),
    (COPY_EDIT, "Copy-edits to accept or query"),
    (TYPOGRAPHY, "Typography, the same value set otherwise (shown, not counted)"),
    (MOVED, "Set elsewhere than where it stood (shown, not counted)"),
    (ADDED, "Text the proof adds (shown, not counted)"),
)


def place(change: Change) -> str:
    """Where the change is in the proof: its page, and the line number it prints."""
    if change.page is None and change.line is None:
        return "in the proof"
    said = f"p. {change.page}" if change.page is not None else ""
    if change.line is not None:
        said = f"{said}, l. {change.line}" if said else f"l. {change.line}"
    return said


def _cut(text: str, size: int = QUOTE) -> str:
    return text if len(text) <= size else text[: size - 1].rstrip() + "\N{HORIZONTAL ELLIPSIS}"


def _describe(change: Change) -> str:
    if change.kind == ADDED:
        return f'"{_cut(change.printed)}"'
    if change.kind == MOVED:
        return f"{change.part}: {change.note}"
    what = change.what if change.part in ("", "the title page") else f"{change.what}, {change.part}"
    if change.kind == CORRECTION and not change.printed:
        said = f'{what}: "{_cut(change.sent)}" ({change.note or "not in the proof"})'
    elif change.kind == CORRECTION and not change.sent:
        said = f'{what}: the proof prints "{_cut(change.printed)}" ({change.note})'
    else:
        said = f'{what}: "{_cut(change.sent)}" is printed "{_cut(change.printed)}"'
        if change.note:
            said += f" ({change.note})"
    if change.source:
        said += f" [from {change.source}]"
    return said


def render(report: ProofReport, root: Path | None = None) -> str:
    def shown(path: Path) -> str:
        if root is not None:
            try:
                return path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                pass
        return str(path)

    share = round(100 * report.found / report.total) if report.total else 0
    lines = [
        f"Proof: {shown(report.proof)}, {report.reading.pages or 'no'} page"
        f"{'' if report.reading.pages == 1 else 's'}, read with {report.reading.reader}"
        + (", with the line numbers it prints" if report.reading.numbered else ""),
        f"Compared with: {shown(report.document)}; {share}% of its words and numbers are "
        "printed in place.",
        *(f"  {said}" for said in report.provenance),
    ]
    if report.reading.furniture:
        taken = "; ".join(_cut(text, 60) for text in report.reading.furniture[:4])
        more = len(report.reading.furniture) - 4
        lines.append(f"Taken out as what every page repeats: {taken}"
                     + (f"; and {more} more" if more > 0 else ""))  # fmt: skip
    for kind, heading in _HEADINGS:
        found = [change for change in report.changes if change.kind == kind]
        if kind != CORRECTION and not found:
            continue
        lines += ["", f"{heading} ({len(found)})"]
        if not found:
            lines.append("  none: every number, unit, citation, reference and name of what "
                         "was sent is printed as it was sent")  # fmt: skip
        for number, change in enumerate(found, start=1):
            lines.append(f"  {number}. {place(change)}: {_describe(change)}")
    lines += ["", "Not compared:"]
    lines += [f"  - {item}" for item in report.not_compared]
    lines += [
        "  - figures by their captions only: a picture's numbers and labels are not read",
        "  - which superscript ties an author to an affiliation, and text in a figure or an "
        "equation",
        "",
        "Nothing has been sent: the corrections are yours to send to the production office.",
    ]
    return "\n".join(lines)


def markdown(report: ProofReport) -> str:
    """The corrections as a numbered list, to paste into the reply to the production office."""
    found = report.corrections
    lines = [f"Corrections to the proof ({report.proof.name})", ""]
    if not found:
        lines.append("No correction: the proof prints every number, unit, citation, reference "
                     "and name as it was sent.")  # fmt: skip
    for number, change in enumerate(found, start=1):
        if change.was and change.now and ", " not in change.was:
            ask = (f'in "{change.printed}", replace "{change.now}" with "{change.was}" '
                   f"({change.what}, {change.part})")  # fmt: skip
        elif not change.printed:
            ask = f'restore "{change.sent}" ({change.what}, {change.part}), which the proof omits'
        elif not change.sent:
            ask = f'delete "{change.printed}" ({change.what}), which the manuscript does not have'
        else:
            ask = f'replace "{change.printed}" with "{change.sent}" ({change.what}, {change.part})'
        lines.append(f"{number}. {place(change).capitalize()}: {ask}.")
    return "\n".join(lines) + "\n"


def as_json(report: ProofReport) -> str:
    def entry(change: Change) -> dict:
        return {
            "kind": change.kind, "what": change.what, "part": change.part,
            "sent": change.sent, "printed": change.printed, "page": change.page,
            "line": change.line, "source": change.source, "note": change.note,
        }  # fmt: skip

    return json.dumps(
        {
            "proof": str(report.proof),
            "document": str(report.document),
            "reader": report.reading.reader,
            "pages": report.reading.pages,
            "found": report.found,
            "total": report.total,
            "provenance": list(report.provenance),
            "corrections": len(report.corrections),
            "changes": [entry(change) for change in report.changes],
            "not_compared": list(report.not_compared),
        },
        indent=2,
        ensure_ascii=False,
    )
