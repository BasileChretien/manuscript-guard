"""Turning manuscript source into a document pandoc can read.

Three substitutions, all of which resolve to something machine-written:

* `{{results.key}}` and `{{lit.key}}` become the value's display string;
* `{{table.key}}` becomes a pipe table built from the emitted table;
* `{{figure.key}}` becomes an image reference to the rendered figure.

Citations are left exactly as they are. `[@key]` has to survive into pandoc untouched, so
that the Zotero filter can turn it into a live field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results, Table
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.placeholders import parse

GATE = "BUILD"

# For a Word document, a raster or PDF beats SVG: Word's SVG support is uneven and a
# journal's production system is worse.
FIGURE_PREFERENCE = (".png", ".pdf", ".tif", ".tiff", ".jpg", ".jpeg", ".eps", ".svg")


@dataclass(frozen=True)
class Assembled:
    path: Path
    text: str


def render_table(table: Table) -> str:
    """A pandoc pipe table. Column widths are padded only so the source stays readable."""
    columns = list(table.columns)
    widths = [len(c) for c in columns]
    for row in table.rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def line(cells: tuple[str, ...] | list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    rule = []
    for index, alignment in enumerate(table.align):
        dashes = "-" * max(3, widths[index])
        if alignment == "right":
            rule.append(dashes[:-1] + ":")
        elif alignment == "center":
            rule.append(":" + dashes[1:-1] + ":")
        else:
            rule.append(dashes)

    out = [line(columns), "| " + " | ".join(rule) + " |"]
    out.extend(line(row) for row in table.rows)
    if table.caption:
        out.append("")
        out.append(f": {table.caption}")
    return "\n".join(out)


def find_figure(project: Project, key: str) -> Path | None:
    figures = project.path("figures")
    for suffix in FIGURE_PREFERENCE:
        candidate = figures / f"{key}{suffix}"
        if candidate.exists():
            return candidate
    return None


_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


def strip_front_matter(text: str) -> tuple[str, str]:
    """The body without its YAML header, and the title the header declared.

    `init` scaffolds a `title:` into both `paper.yaml` and `manuscript/main.md`, and only
    the first is used — while the second was never removed from the body. Every document
    this tool has ever built therefore opens with a line of raw YAML rendered as prose, and
    when the two titles differ the paper is uploaded under the wrong one: `submit` writes
    the title page and the manifest from `paper.yaml`, so nothing anywhere reports the
    contradiction. It reproduces in the shipped example, where the two happen to match and
    the stray line reads as a harmless duplicate.
    """
    found = _FRONT.match(text)
    if not found:
        return text, ""
    declared = ""
    for line in found.group(1).splitlines():
        if line.strip().startswith("title:"):
            declared = line.split(":", 1)[1].strip().strip("\"'")
            break
    return text[found.end():].lstrip("\n"), declared


def assemble(project: Project, namespace: dict[str, Value], results: Results) -> tuple[
    list[Assembled], Report
]:
    """Substitute every binding in every source file. Nothing is written to disk here."""
    report = Report()
    out: list[Assembled] = []

    for path in source_files(project.path("manuscript")):
        # Tagged before substitution, so each identifier names a *source* paragraph. They
        # become invisible Word bookmarks, and they are how a paragraph a co-author moved is
        # recognised when the document comes back.
        from manuscript_guard.roundtrip import tag

        relative = path.relative_to(project.path("manuscript")).as_posix()
        raw, declared = strip_front_matter(path.read_text(encoding="utf-8"))
        if declared and declared != str(project.paper.get("title", "")):
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="two-titles",
                    severity=WARN,
                    message=f"{path.name} declares a different title from paper.yaml",
                    path=path,
                    context=declared[:120],
                    hint="paper.yaml is the one the document and the submission pack use; "
                    "delete the title from the manuscript or make them agree",
                )
            )
        text = tag(raw, relative)
        placeholders, _ = parse(text)
        rendered = text

        for placeholder in sorted(placeholders, key=lambda p: p.start, reverse=True):
            replacement: str | None = None

            if placeholder.is_value:
                value = namespace.get(placeholder.ref)
                if value is not None:
                    replacement = value.display
            elif placeholder.namespace == "table":
                table = results.tables.get(placeholder.key)
                if table is None:
                    report = report.with_findings(
                        Finding(
                            gate=GATE,
                            code="table-missing",
                            message=f"{placeholder.raw} refers to a table nothing emits",
                            path=path,
                            line=placeholder.line,
                            hint="emit it from the analysis with em.table(...)",
                        )
                    )
                    continue
                replacement = render_table(table)
            elif placeholder.namespace == "figure":
                figure = find_figure(project, placeholder.key)
                if figure is None:
                    report = report.with_findings(
                        Finding(
                            gate=GATE,
                            code="figure-missing",
                            message=f"{placeholder.raw} refers to a figure that is not rendered",
                            path=path,
                            line=placeholder.line,
                            hint=f"run the script that produces figures/{placeholder.key}",
                        )
                    )
                    continue
                # Absolute, because the rendered file lives in build/ and pandoc resolves
                # relative paths against the input's directory.
                replacement = f"![]({figure.resolve().as_posix()})"

            if replacement is not None:
                rendered = (
                    rendered[: placeholder.start] + replacement + rendered[placeholder.end :]
                )

        out.append(Assembled(path=path, text=rendered))

    return out, report.with_counts(assembled_files=len(out))
