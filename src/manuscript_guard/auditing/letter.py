"""`audit --letter FILE.md`: the draft of the letter that returns a paper to its authors
before review, made from the editor's report (`auditing.editor`; Basile, 2026-11-25).

The kinds the editor's report puts under "Ask the authors" are asked under "Please correct
or answer before review", and those under "Look at before you decide" under "Please check",
in words that put nothing as the authors' fault, since a finding to check may be right as it
stands. Each kind is asked once, in the sentence `data/letter.yaml` gives it for the authors,
and each place it was found is listed under it, with what the editor's report says there and
the words it quotes. What is for copyediting and what the check read are not in it, nor the
self-citation counts: the report has them.

Its first line says it is a draft, for the editor to read, change and send. The same report
gives the same bytes: nothing reads a clock, and the file is written once, never over one
there (`draft.write`, `draft.refused`).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from manuscript_guard import __version__
from manuscript_guard.auditing import editor

DATA = Path(__file__).parent.parent / "data" / "letter.yaml"
FLAG = "--letter"
#: The parts of the editor's report the letter asks, each under its heading, in this order.
ASKED = ((editor.ASK, "Please correct or answer before review"), (editor.LOOK, "Please check"))
FIRST = (f"[Draft from manuscript-guard {__version__}: read it, change what you need, and "
         "delete this line before sending.]")  # fmt: skip
GREETING = "Dear Author,"
OPENING = ("Thank you for your submission. Before it is sent for review, please attend to the "
           "points below. Each says where in your files it was found.")  # fmt: skip
NOTHING = "Our checks of your files raised no point to put to you before review."
CHECK_SAID = ("Each of these may be right as it stands. Where it is, a line in your reply "
              "saying so is enough.")  # fmt: skip
CLOSING = ("Please send the revised files with a reply that says, point by point, what you "
           "changed.")  # fmt: skip
SIGNED = ("Yours sincerely,", "", "[Name]", "[Journal], Editorial Office")
#: How much of the words a finding quotes the letter gives, cut at a space.
QUOTED = 200


@dataclass(frozen=True)
class Sentences:
    """`data/letter.yaml`, read: the sentence of each kind, and of a finding no kind names."""

    kinds: dict[str, str]
    further: str


def read(text: str) -> Sentences:
    """The sentences `text` holds, refused with a `ValueError` that says where it is wrong."""
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict) or not isinstance(raw.get("kinds"), dict):
        raise ValueError(f"{DATA.name}: needs `kinds`, a mapping, and `further`")
    said = {**raw["kinds"], "further": raw.get("further")}
    for name, sentence in said.items():
        if not isinstance(name, str) or not isinstance(sentence, str) or not sentence.strip():
            raise ValueError(f"{DATA.name}: {name!r} is not a name with a sentence")
    kinds = {name: " ".join(sentence.split()) for name, sentence in raw["kinds"].items()}
    return Sentences(kinds, " ".join(raw["further"].split()))


@cache
def sentences() -> Sentences:
    """The sentences the package ships."""
    return read(DATA.read_text(encoding="utf-8"))


def asked(kind) -> str:
    """What the letter asks of a kind (`editor.Kind`): its sentence, or the one for a
    finding no kind names."""
    known = sentences()
    return known.kinds.get(kind.name, known.further)


def _quoted(context: str) -> str:
    """The words a finding quotes, on one line, cut at a space after `QUOTED` characters."""
    text = " ".join(context.split())
    if len(text) <= QUOTED:
        return text
    cut = text.rfind(" ", 0, QUOTED)
    return text[:cut if cut > 0 else QUOTED] + " ..."


def _asked(found: list, root: Path | None, placers: dict, editors: frozenset) -> list[str]:
    """Each kind of a part, numbered, in its sentence, with each of its places under it; no
    place for a finding placed in one of the editor's own files, `editors` (the journal's
    profile), which the authors do not have."""
    lines: list[str] = []
    kinds = [kind for kind in (*editor.KINDS, editor.FURTHER)
             if any(of is kind for _item, of in found)]  # fmt: skip
    for number, kind in enumerate(kinds, start=1):
        lines.append(f"{number}. {asked(kind)}")
        for item in (item for item, of in found if of is kind):
            where = "" if item.path in editors else editor._where(item, root, placers)
            said = editor._said(item, kind)
            lines.append(f"   - {where + ': ' if where else ''}{said}")
            if item.context and not kind.quoted:
                lines.append(f"     > {_quoted(item.context)}")
        lines.append("")
    return lines


def for_audit(report, root: Path | None = None) -> str:
    """The letter for the audit `report`, its places said from `root` as the editor's report
    says them."""
    found = editor.parted(report)
    placers = getattr(report, "placers", None) or {}
    journal = getattr(report, "journal", None)
    editors = frozenset() if journal is None else frozenset({journal.profile})
    parts = [(heading, [(item, kind) for item, kind in found if kind.part == part])
             for part, heading in ASKED]  # fmt: skip
    lines = [FIRST, "", GREETING, ""]
    if not any(held for _heading, held in parts):
        return "\n".join([*lines, NOTHING, "", *SIGNED]) + "\n"
    lines += [OPENING, ""]
    for heading, held in parts:
        if not held:
            continue
        lines += [f"## {heading}", ""]
        if heading == dict(ASKED)[editor.LOOK]:
            lines += [CHECK_SAID, ""]
        lines += _asked(held, root, placers, editors)
    lines += [CLOSING, "", *SIGNED]
    return "\n".join(lines) + "\n"
