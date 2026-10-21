"""Where a number the proof changed came from in the source: the binding that printed it,
or the line of the manuscript it was typed on.

A paragraph of the document carries the identifier of its source paragraph (`roundtrip.tag`),
so the bindings in that paragraph are known, and each binding's value as the results give it
now. A binding whose value prints the number is named; a number that no binding prints and
the paragraph holds as it is was typed. A cell of a table is named by the table's binding:
the tables of a document are printed in the order the build reads its sources, one for each
`{{table.…}}`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.proof.sent import CELL, Part
from manuscript_guard.proof.tokens import NUMBER, prepared, tokens

Origin = Callable[[Part, str], str]


def origins(project: Project, *, supplementary: bool = False) -> Origin:
    """A function that says where a number of a part came from, "" where it cannot."""
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.contracts._schema import ContractError, read_text
    from manuscript_guard.contracts.values import Value
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
    from manuscript_guard.roundtrip import tagged_paragraphs
    from manuscript_guard.text.placeholders import parse

    manuscript = project.path("manuscript")
    try:
        namespace: dict[str, Value] = load_namespace(project)[0]
        tagged = tagged_paragraphs(project)
        files = printed_order(
            [p for p in source_files(manuscript)
             if is_supplementary(manuscript, p) == supplementary],
            supplementary=supplementary,
        )  # fmt: skip
        texts = {path: read_text(path) for path in files}
    except (OSError, ValueError, ContractError):
        # Where the source cannot be read, `check` says why; the proof is still compared,
        # and a correction names no source.
        return lambda _part, _raw: ""
    tables = [placeholder.raw for path in files for placeholder in parse(texts[path])[0]
              if placeholder.namespace == "table"]  # fmt: skip

    def where(path: Path, start: int) -> str:
        text = texts.get(path)
        if text is None:
            text = read_text(path)
        line = text[:start].count("\n") + 1
        return f"{path.relative_to(project.root).as_posix()}, line {line}"

    def origin(part: Part, raw: str) -> str:
        if part.kind == CELL:
            return f"{tables[part.table - 1]}" if 0 < part.table <= len(tables) else ""
        found = tagged.get(part.identifier)
        if found is None:
            return ""
        path, text, start = found
        placed = where(path, start)
        keys = []
        for placeholder in parse(text)[0]:
            value = namespace.get(placeholder.ref) if placeholder.is_value else None
            if value is not None and _prints(value.display, raw):
                keys.append(placeholder.raw)
        if keys:
            return f"{', '.join(dict.fromkeys(keys))} in {placed}"
        if _prints(text, raw):
            return f"typed in {placed}"
        return placed

    return origin


def _prints(text: str, raw: str) -> bool:
    """Whether `text` prints the number `raw` as a number of its own."""
    wanted = prepared(raw)
    return any(t.kind == NUMBER and t.raw == wanted for t in tokens(prepared(text), 0))
