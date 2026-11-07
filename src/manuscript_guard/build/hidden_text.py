"""A document built to be sent holds no text its reader does not see.

The built `manuscript.docx` and `supplementary.docx` go to co-authors, to journals and to
the models some of their readers use. So each is read, as it is written, for what
`hidden.read_hidden` finds: text hidden by its own formatting or by a style, text the
colour of what is behind it, text under 3 pt, zero-width characters inside words, and words
written to a model. Pandoc writes none of these from Markdown; they come from Word markup
written into the source (a raw `openxml` block), a style of the reference document that
hides what it is given (`custom-style`), the reference document's own headers and footers,
characters pasted with the text, or alternative text and properties that hold words to a
model.

Each fails the build at every stage (Basile, 2026-11-06): the document is written and said
not to be sent, and `submit` packs nothing. Words to a model printed where the paper's reader
sees them are a warning, since a paper about such words may quote them. The build checks the
document it made; `submit` checks each one it packs, a copy a co-author edited among them.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.hidden import TO_A_MODEL, Hidden, read_hidden
from manuscript_guard.safexml import UnsafeDocument

GATE = "BUILD"
HIDES = "document-hides-text"
ADDRESSES = "document-addresses-a-model"
UNREAD = "document-unread-for-hidden-text"
#: The codes that keep a document from being sent when they fail.
CODES = frozenset({HIDES, ADDRESSES, UNREAD})
#: How many places of each kind are said, before the rest are counted.
SHOWN = 12

#: How each kind is said, around how the place is kept from sight.
_WHAT = {
    "hidden": "{how}",
    "background": "text too close in colour to what is behind it to be read, {how}",
    "tiny": "text too small to read, {how}",
    "zero-width": "zero-width characters, {how}",
}
_HINT = (
    "a model reading the document reads this and a person does not: take it out of the "
    "source, the raw Word markup, the reference document's style or the reference's record "
    "in Zotero it came from, and build again"
)
_HINT_PRINTED = (
    "words that tell a model reading the paper what to do; unless the paper quotes them as "
    "its subject, take them out"
)


def _said(item: Hidden) -> str:
    if item.kind == TO_A_MODEL:
        return f"{item.where}: {item.how}: {item.text!r}"
    model = "; its words are addressed to a model" if item.model else ""
    what = _WHAT.get(item.kind, "{how}").format(how=item.how)
    return f"{item.where}: {what}: {item.text!r}{model}"


def _finding(item: Hidden, path: Path) -> Finding:
    if item.kind == TO_A_MODEL and item.printed:
        return Finding(gate=GATE, code=ADDRESSES, severity=WARN, message=_said(item),
                       path=path, hint=_HINT_PRINTED)  # fmt: skip
    code = ADDRESSES if item.kind == TO_A_MODEL else HIDES
    return Finding(gate=GATE, code=code, severity=FAIL, message=_said(item), path=path,
                   hint=_HINT)  # fmt: skip


def check_hidden_text(path: Path) -> Report:
    """What `path`, a built Word document, holds that its reader does not see, each place a
    finding (see the module's docstring)."""
    try:
        reading = read_hidden(path)
    except UnsafeDocument as exc:
        unread = Finding(gate=GATE, code=UNREAD, severity=FAIL, path=path,
                         message=f"{path.name} could not be read for hidden text: {exc}",
                         hint="rebuild it; a document that cannot be read is not sent")  # fmt: skip
        return Report((unread,))
    findings: list[Finding] = []
    said: dict[tuple[str, str], int] = {}
    for item in reading.found:
        finding = _finding(item, path)
        key = (finding.code, finding.severity)
        said[key] = said.get(key, 0) + 1
        if said[key] <= SHOWN:
            findings.append(finding)
    for (code, severity), count in said.items():
        if count > SHOWN:
            more = f"and {count - SHOWN} more places like these"
            findings.append(Finding(gate=GATE, code=code, severity=severity, path=path,
                                    message=more))  # fmt: skip
    findings += [
        Finding(gate=GATE, code=UNREAD, severity=FAIL, path=path,
                message=f"{path.name}: a part was not read for hidden text: {why}",
                hint="a document that cannot be read whole is not sent")
        for why in reading.unread
    ]  # fmt: skip
    return Report(tuple(findings), counts={"hidden_text": len(reading.found)})


def hides(report: Report) -> bool:
    """Whether `report` keeps a document from being sent for what it hides."""
    return any(finding.code in CODES for finding in report.failures)
