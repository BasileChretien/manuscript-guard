"""Turning manuscript source into a document pandoc can read.

Three substitutions, all of which resolve to something machine-written:

* `{{results.key}}` and `{{lit.key}}` become the value's display string;
* `{{table.key}}` becomes a pipe table built from the emitted table;
* `{{figure.key}}` becomes an image reference to the rendered figure.

Citations are left exactly as they are. `[@key]` has to survive into pandoc untouched, so
that the Zotero filter can turn it into a live field.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results, Table
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files, unreadable_header
from manuscript_guard.text.fences import unclear_fence_lines
from manuscript_guard.text.masking import FRONTMATTER, front_matter_end, front_matter_problem
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import rules_opening_blocks

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


def strip_front_matter(text: str) -> tuple[str, str]:
    """The body without its YAML header, and the title the header declared.

    `init` scaffolds a `title:` into both `paper.yaml` and `manuscript/main.md`, and only
    the first is used — while the second was never removed from the body. Every document
    this tool has ever built therefore opens with a line of raw YAML rendered as prose, and
    when the two titles differ the paper is uploaded under the wrong one: `submit` writes
    the title page and the manifest from `paper.yaml`, so nothing anywhere reports the
    contradiction. It reproduces in the shipped example, where the two happen to match and
    the stray line reads as a harmless duplicate.

    The block is found by the pattern the gates mask it with, so the build and the gates
    agree on where the front matter ends.
    """
    found = FRONTMATTER.match(text)
    if not found:
        return text, ""
    declared = ""
    for line in found.group("yaml").splitlines():
        if line.strip().startswith("title:"):
            declared = line.split(":", 1)[1].strip().strip("\"'")
            break
    return text[found.end():].lstrip("\n"), declared


def rule_findings(path: Path, text: str) -> tuple[Finding, ...]:
    """A refusal for each line of dashes below the front matter with a line directly above
    or under it (`sections.rules_opening_blocks`).

    With a line under it, pandoc may read YAML metadata there, merged over the build's
    header with the later value winning: a `title:` in it replaced paper.yaml's on the
    title page. Pandoc prints no heading from that, nor from a table, and under a line it
    reads a heading the gates may not. Refused in the build as well as in `check`, so no
    document is made from a source the gates misread.
    """
    lines = text.split("\n")

    def beside(line: int) -> str:
        # `line` counts from 1: `lines[line - 2]` is the line above the rule, quoted unless
        # it is blank, and `lines[line]` the one under it.
        above = lines[line - 2].strip() if line >= 2 else ""
        under = lines[line].strip() if line < len(lines) else ""
        return (above or under)[:120]

    return tuple(
        Finding(
            gate=GATE,
            code="rule-opens-a-block",
            message=f"{path.name}: a line of dashes with a line directly above or under it, "
            "which pandoc may read as a heading's underline, YAML metadata or a table",
            path=path,
            line=line,
            context=beside(line),
            hint="write a heading with `#`, as `## Methods`; put a blank line above and "
            "under a thematic break; move metadata into paper.yaml; a table is emitted and "
            "placed with `{{table.key}}`",
        )
        for line in rules_opening_blocks(text)
    )


def fence_findings(path: Path, text: str) -> tuple[Finding, ...]:
    """A refusal for each line of backticks or tildes below the front matter that is not a
    plain fenced listing's (`fences.unclear_fence_lines`).

    Pandoc may read such a line as text, as inline code running on to a later fence, or
    as a listing the gates do not see, and the gates then read prose as code or code as
    prose. An R Markdown chunk header is the common one: pandoc opens no listing on it.
    """
    lines = text.split("\n")
    return tuple(
        Finding(
            gate=GATE,
            code="unclear-fence",
            message=f"{path.name}: a line of backticks or tildes that is not a plain fenced "
            "listing, which pandoc may read as text, inline code or a listing the gates "
            "do not see",
            path=path,
            line=line,
            context=lines[line - 1].strip()[:120],
            hint="open a listing at the margin, under a blank line, outside any comment or "
            "raw block, with at most a language word or `{.class}` attributes after the "
            "fence on the same line, and close it; move a listing out of a list item, "
            "whose indentation pandoc takes off before it looks for the closer; to comment "
            "a listing out, put the comment's `-->` on a line of its own after the closer; "
            "knit R Markdown first, since pandoc prints a `{r ...}` chunk as text",
        )
        for line in unclear_fence_lines(text, front_matter_end(text))
    )


def refused_shapes(path: Path, text: str) -> tuple[Finding, ...]:
    """Every shape the build refuses in a source file: `rule_findings` and
    `fence_findings`."""
    return (*rule_findings(path, text), *fence_findings(path, text))


def check_shapes(project: Project) -> Report:
    """`refused_shapes` for every source file, so `check` refuses what the build would."""
    report = Report()
    for path in source_files(project.path("manuscript")):
        report = report.with_findings(*refused_shapes(path, path.read_text(encoding="utf-8")))
    return report


def assemble(
    project: Project, namespace: dict[str, Value], results: Results, *, mark: bool = False
) -> tuple[list[Assembled], Report]:
    """Substitute every binding in every source file. Nothing is written to disk here.

    `mark` wraps each binding and citation in a bookmark of its own, for the build `import`
    compares with and for nothing else; see `roundtrip.tag`.
    """
    report = Report()
    out: list[Assembled] = []

    for path in source_files(project.path("manuscript")):
        # Tagged before substitution, so each identifier names a *source* paragraph. They
        # become invisible Word bookmarks, and they are how a paragraph a co-author moved is
        # recognised when the document comes back.
        from manuscript_guard.roundtrip import tag

        relative = path.relative_to(project.path("manuscript")).as_posix()
        source = path.read_text(encoding="utf-8")
        report = report.with_findings(*refused_shapes(path, source))
        # Built anyway, the header printed as text: the identifier in front of it hid it
        # from pandoc, which would have refused the file. `--skip-checks` does not reach this.
        problem = front_matter_problem(source)
        if problem is not None:
            report = report.with_findings(unreadable_header(path, *problem, GATE))
        raw, declared = strip_front_matter(source)
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
        text = tag(raw, relative, mark=mark)
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
                # Relative to the project root, which pandoc runs from. It was absolute, and
                # pandoc records an image's path as the picture's description - so every
                # document sent to a co-author carried the builder's home directory.
                from manuscript_guard.build.document import relative_to_root

                replacement = f"![]({relative_to_root(project, figure)})"

            if replacement is not None:
                rendered = (
                    rendered[: placeholder.start] + replacement + rendered[placeholder.end :]
                )

        out.append(Assembled(path=path, text=rendered))

    return out, report.with_counts(assembled_files=len(out))
