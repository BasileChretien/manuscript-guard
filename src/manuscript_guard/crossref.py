"""A table or a figure named by its key, and the number the document gives it.

"As Table 2 shows" is typed, and G2 holds it to what the document places
(`gates/pointers.py`). It goes stale whenever a table moves: the example called its tables
"Table 2" and "Table 3" after its first had moved to the supplement, and only a gate said so.
`{{ref.table.baseline}}` names the table instead, by the key it is placed with, and the
build prints the number the document gives it, counted as G2 counts: the main text's tables
in the order its files print, Table 1 being the first `{{table.<key>}}` the main text places
and Table S1 the supplement's first. A table moved renumbers every mention of it, and a
mention cannot point at a table that is not there. LaTeX's `\\ref`, MyST's (Jupyter Book's)
and pandoc-crossref's references do this from a label; here the label is the key the display
is placed by already.

Two forms, Basile's choice on 2026-10-20. `{{ref.table.key}}` prints the pointer whole,
"Table 2". `{{num.table.key}}` prints its number alone, "2", or "S1" in the supplement, for a
list or a range the author writes ("Tables {{num.table.a}} and {{num.table.b}}"), and G2
holds the words typed before it to the display it names.

How the pointer is written is the target journal's: its profile's `pointers:` block gives a
form for each kind of each document, "eTable {n}" or "Fig. {n}", and where it gives none the
form is "Table {n}", "Figure {n}", "Table S{n}" or "Figure S{n}".

A number is printed only where the count is exact, Basile's choice on 2026-10-20. Where a
document also places a kind by hand, or sends some to the journal as files of their own,
where a bound one falls among them is not known: a ref to that kind of that document is
refused (`ref-number-unknown`), and so is one to a key placed twice.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from manuscript_guard.text.placeholders import Placeholder

TABLE = "table"
FIGURE = "figure"
KINDS = (TABLE, FIGURE)
REF = "ref"
NUM = "num"
#: Where a form puts the number.
NUMBER = "{n}"
#: For each kind of each document, `(supplementary, kind)`: the key a profile's `pointers:`
#: gives its form under, and the form where it gives none.
FORMS: dict[tuple[bool, str], tuple[str, str]] = {
    (False, TABLE): ("table", "Table {n}"),
    (False, FIGURE): ("figure", "Figure {n}"),
    (True, TABLE): ("supplementary_table", "Table S{n}"),
    (True, FIGURE): ("supplementary_figure", "Figure S{n}"),
}
UNRESOLVED = "unresolved-binding"
UNKNOWN = "ref-number-unknown"


def where(supplementary: bool) -> str:
    return "the supplement" if supplementary else "the main text"


@dataclass(frozen=True)
class Display:
    """A table or a figure placed by its binding, and its number in its document."""

    kind: str
    key: str
    supplementary: bool
    number: int

    @property
    def binding(self) -> str:
        return f"{{{{{self.kind}.{self.key}}}}}"


@dataclass(frozen=True)
class Refused:
    """Why a ref prints no number: the finding's code, and what to tell the author."""

    code: str
    why: str
    hint: str


@dataclass(frozen=True)
class Numbers:
    """What each table and figure placed by its binding is numbered, in its document.

    `bound` counts them by `(supplementary, kind)`; `by_hand` holds the kinds a document
    also places by hand, and `as_files` how many of each paper.yaml sends as files of their
    own (`displays:`). `forms` is how the document writes a pointer to each.
    """

    placed: Mapping[tuple[str, str], tuple[Display, ...]]
    bound: Mapping[tuple[bool, str], int]
    by_hand: frozenset[tuple[bool, str]]
    as_files: Mapping[tuple[bool, str], int]
    forms: Mapping[tuple[bool, str], str]
    #: The keys of the tables a caption is typed beside, whose emitted caption the build
    #: prints without a number (`gates.pointers.caption_label`).
    captioned: frozenset[str] = frozenset()

    def uncounted(self, supplementary: bool, kind: str) -> str | None:
        """Why a bound display of this kind of this document has no known number, or None."""
        if (supplementary, kind) in self.by_hand:
            return f"{where(supplementary)} also places a {kind} by hand"
        files = self.as_files.get((supplementary, kind), 0)
        if files:
            return f"paper.yaml sends {files} of {where(supplementary)}'s {kind}s as files"
        return None

    def display(self, placeholder: Placeholder) -> Display | Refused:
        """The display a ref names, or why it has no number to print."""
        kind, _, key = placeholder.key.partition(".")
        if kind not in KINDS or not key:
            return Refused(
                UNRESOLVED,
                f"{placeholder.raw} names no table and no figure",
                f"the form is {{{{{placeholder.namespace}.table.<key>}}}} or "
                f"{{{{{placeholder.namespace}.figure.<key>}}}}, with the key the display is "
                "placed by",
            )
        found = self.placed.get((kind, key), ())
        if not found:
            return Refused(
                UNRESOLVED,
                f"{placeholder.raw} names a {kind} nothing places",
                f"place it with {{{{{kind}.{key}}}}}, or name one that is placed",
            )
        if len(found) > 1:
            return Refused(
                UNKNOWN,
                f"{placeholder.raw} names a {kind} placed {len(found)} times, so it has more "
                "than one number",
                f"place {{{{{kind}.{key}}}}} once, and type the pointer to the other",
            )
        display = found[0]
        why = self.uncounted(display.supplementary, kind)
        if why is not None:
            return Refused(
                UNKNOWN,
                f"{placeholder.raw} cannot be numbered: {why}, and where {display.binding} "
                "falls among those is not known",
                f"type the pointer there, or place every {kind} of {where(display.supplementary)} "
                f"by {{{{{kind}.<key>}}}}",
            )
        return display

    def bindings(self) -> dict[str, str]:
        """What each ref and num binding the document could hold prints, by its ref:
        `{"ref.table.baseline": "Table 1", "num.table.baseline": "1"}`, for a printer that
        substitutes by ref. One the count cannot number is left out."""
        out: dict[str, str] = {}
        for (kind, key), found in self.placed.items():
            if len(found) != 1 or self.uncounted(found[0].supplementary, kind):
                continue
            form = self.forms[found[0].supplementary, kind]
            out[f"{REF}.{kind}.{key}"] = form.replace(NUMBER, str(found[0].number))
            out[f"{NUM}.{kind}.{key}"] = number_of(form, found[0].number)
        return out

    def printed(self, placeholder: Placeholder) -> str | None:
        """What a ref prints, or None where it has no number."""
        display = self.display(placeholder)
        if isinstance(display, Refused):
            return None
        form = self.forms[display.supplementary, display.kind]
        if placeholder.namespace == NUM:
            return number_of(form, display.number)
        return form.replace(NUMBER, str(display.number))


def number_of(form: str, number: int) -> str:
    """What `num` prints under a form: the word of it holding the number. "S2" under
    "Table S{n}", "2" under "eTable {n}" or "Supplementary Table {n}"."""
    word = next((word for word in form.split() if NUMBER in word), NUMBER)
    return word.replace(NUMBER, str(number))


def forms_of(document: Mapping | None) -> dict[tuple[bool, str], str]:
    """The form for each kind of each document: the journal profile's, or the default."""
    declared = (document or {}).get("pointers") or {}
    return {
        place: str(declared.get(name) or default) for place, (name, default) in FORMS.items()
    }


def project_forms(project) -> dict[tuple[bool, str], str]:
    """The forms of the target journal's profile, where it has a valid one."""
    from manuscript_guard.gates.journal import _profile

    return forms_of(_profile(project))


__all__ = [
    "FIGURE",
    "FORMS",
    "KINDS",
    "NUM",
    "NUMBER",
    "REF",
    "TABLE",
    "UNKNOWN",
    "UNRESOLVED",
    "Display",
    "Numbers",
    "Refused",
    "forms_of",
    "number_of",
    "project_forms",
    "where",
]
