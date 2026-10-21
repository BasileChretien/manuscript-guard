"""The values file of a LaTeX manuscript, `mgvalues.sty` (DESIGN.md, "LaTeX manuscripts",
"The values file").

`manuscript-guard values` writes it beside each entry file, `manuscript/mgvalues.sty` and the
supplement's. It defines `\\mg` and one entry for each key: a value's display and a table's
cells with TeX's specials escaped, a figure as `\\includegraphics` of its rendered file by a
path from the file's own folder, and a Methods anchor as nothing. Its first line names the
results it was written from by their digest. The entry file loads it with
`\\usepackage{mgvalues}`, so the `.tex` compiles in any editor with the numbers in, and it is
committed, so a co-author's editor has it. A key it does not define prints `??` and the key,
with a LaTeX warning, as an undefined `\\ref` prints `??`; `check` already fails the binding.

`check` writes nothing: it compares the file with what `values` would write.

Escaping is a closed table. It covers TeX's ten specials; `<`, `>` and `|`, which pdfLaTeX's
default OT1 encoding prints as other glyphs, written in maths with `\\ensuremath`, since a
`$...$` would close the maths a binding stands in, `$p = \\mg{results.p}$`; and the characters
beyond ASCII that values carry: the minus, the dashes, ±, ×, ≤, ≥, ·, the no-break and thin
spaces, and the Greek letters. Latin-1 is written as it is, which LaTeX reads as UTF-8. A
value holding any other character is refused (`value-not-printable`), not guessed at.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results, Table
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import Finding, Report

NAME = "mgvalues.sty"

#: TeX's ten specials, as text.
_SPECIALS = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#",
    "%": r"\%", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}  # fmt: skip
#: What prints right only in maths, under pdfLaTeX's default encoding or at all.
_MATHS = {
    "<": "<", ">": ">", "|": r"\vert", "\N{MINUS SIGN}": "-", "\N{PLUS-MINUS SIGN}": r"\pm",
    "\N{MULTIPLICATION SIGN}": r"\times", "\N{LESS-THAN OR EQUAL TO}": r"\leq",
    "\N{GREATER-THAN OR EQUAL TO}": r"\geq", "\N{MIDDLE DOT}": r"\cdot",
    "\N{DOT OPERATOR}": r"\cdot",
}  # fmt: skip
#: The Greek letters, in maths; those whose capital is a Latin letter's are that letter.
_GREEK = dict(
    zip(
        "αβγδεζηθικλμνξπρστυφχψωςϵϑϕϖϱ",
        (r"\alpha", r"\beta", r"\gamma", r"\delta", r"\varepsilon", r"\zeta", r"\eta",
         r"\theta", r"\iota", r"\kappa", r"\lambda", r"\mu", r"\nu", r"\xi", r"\pi", r"\rho",
         r"\sigma", r"\tau", r"\upsilon", r"\varphi", r"\chi", r"\psi", r"\omega",
         r"\varsigma", r"\epsilon", r"\vartheta", r"\phi", r"\varpi", r"\varrho"),
        strict=True,
    )
)  # fmt: skip
_GREEK |= dict(zip("ΓΔΘΛΞΠΣΥΦΨΩ", (r"\Gamma", r"\Delta", r"\Theta", r"\Lambda", r"\Xi",
                                 r"\Pi", r"\Sigma", r"\Upsilon", r"\Phi", r"\Psi", r"\Omega"),
                   strict=True))  # fmt: skip
#: Capitals written as the Latin letter they look like, and the small omicron.
_LATIN_LOOKING = dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΧο", "ABEZHIKMNOPTXo", strict=True))
#: What prints in text with a command. A dash is a command and no ligature: `--` before a
#: value's minus sign, `-0.80--0.12`, made TeX's em dash and dropped the sign (round 1 of
#: step 4b).
_TEXT = {
    "\N{EN DASH}": r"\textendash{}", "\N{EM DASH}": r"\textemdash{}",
    "\N{NO-BREAK SPACE}": "~", "\N{THIN SPACE}": r"\,", "\N{NARROW NO-BREAK SPACE}": r"\,",
}  # fmt: skip
#: A rendered figure's path is written as it is, so a character TeX reads in it is refused;
#: `\includegraphics` takes an underscore, `km_curve.pdf` (round 1 of step 4b).
_UNSAFE_IN_PATH = (set(_SPECIALS) - {"_"}) | {" "}


#: The rendered files pdfLaTeX includes, in the order a figure's is chosen.
PDFLATEX_FIGURES = (".pdf", ".png", ".jpg", ".jpeg")


class NotPrintable(ValueError):
    """What the values file has no way to print under pdfLaTeX: a character, or a figure
    rendered only in a format it does not include."""

    def __init__(self, ref: str, character: str, why: str | None = None) -> None:
        super().__init__(why or (
            f"{ref} holds {character!r} (U+{ord(character):04X}), which the values file has no "
            "way to print under pdfLaTeX"
        ))  # fmt: skip
        self.ref = ref
        self.character = character


def escaped(text: str, ref: str) -> str:
    """`text` as LaTeX prints it under pdfLaTeX, or `NotPrintable`."""
    out = []
    for index, character in enumerate(text):
        if character == "-" and text[index + 1 : index + 2] == "-":
            # Two hyphens are TeX's en dash, and a sign after them lost (round 2 of step 4b).
            out.append("-{}")
        elif character in _SPECIALS:
            out.append(_SPECIALS[character])
        elif character in _MATHS or character in _GREEK:
            out.append(r"\ensuremath{" + (_MATHS | _GREEK)[character] + "}")
        elif character in _LATIN_LOOKING:
            out.append(_LATIN_LOOKING[character])
        elif character in _TEXT:
            out.append(_TEXT[character])
        elif ord(character) < 0x100 and (character.isprintable() or character == " "):
            out.append(character)
        else:
            raise NotPrintable(ref, character)
    return "".join(out)


def tabular(table: Table, ref: str) -> str:
    """A table as a `tabular`: its columns aligned as emitted, its header over a rule. The
    caption is the float's `\\caption`, which the author writes, as a figure's is."""
    columns = "".join({"right": "r", "center": "c"}.get(align, "l") for align in table.align)
    columns = columns or "l" * len(table.columns)

    def row(cells: tuple[str, ...]) -> str:
        written = [escaped(cell, ref) for cell in cells]
        # A row after `\\\\` that opens with `[` or `*` would be read as its argument
        # (round 1 of step 4b).
        if written and written[0].lstrip()[:1] in ("[", "*"):
            written[0] = "{}" + written[0]
        return " & ".join(written) + r" \\"

    lines = [rf"\begin{{tabular}}{{{columns}}}", row(table.columns), r"\hline"]
    lines += [row(cells) for cells in table.rows]
    lines.append(r"\end{tabular}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Written:
    """What `values` writes for one entry file's folder, and what of the results it has no way
    to print, which it leaves out: `\\mg` prints `??` for it, and LaTeX warns."""

    path: Path
    text: str
    refused: tuple[NotPrintable, ...] = ()


def contents(
    folder: Path,
    namespace: dict[str, Value],
    results: Results,
    figures: dict[str, Path | None],
    digest: str,
) -> Written:
    """The values file for the entry file in `folder`: every value, table, figure and anchor
    the results hold that it can print, in the order of their keys, so that the same results
    write the same file. One it cannot print is left out and given as refused, and the rest
    are written: a value no file binds stops nothing (round 1 of step 4b). `figures` are the
    rendered figures by key, None where none is in a format pdfLaTeX includes."""
    entries: list[tuple[str, str]] = []
    refused: list[NotPrintable] = []
    for ref, value in sorted(namespace.items()):
        try:
            entries.append((ref, escaped(value.display, ref)))
        except NotPrintable as found:
            refused.append(found)
    for key, table in sorted(results.tables.items()):
        try:
            entries.append((f"table.{key}", "%\n" + tabular(table, f"table.{key}") + "%\n"))
        except NotPrintable as found:
            refused.append(found)
    for key, rendered in sorted(figures.items()):
        if rendered is None:
            refused.append(NotPrintable(f"figure.{key}", "", why=(
                f"figure.{key} is rendered in no format pdfLaTeX includes "
                f"({', '.join(PDFLATEX_FIGURES)})"
            )))  # fmt: skip
            continue
        relative = posixpath.relpath(rendered.as_posix(), folder.as_posix())
        unsafe = sorted(set(relative) & _UNSAFE_IN_PATH)
        if unsafe:
            refused.append(NotPrintable(f"figure.{key}", unsafe[0]))
            continue
        entries.append((f"figure.{key}", r"\includegraphics[#1]{" + relative + "}"))
    for step in sorted(results.steps):
        entries.append((f"method.{step}", ""))
    return Written(folder / NAME, _HEAD.format(digest=digest) + "".join(
        rf"\expandafter\def\csname mg@{ref}\endcsname#1{{{body}}}" + "\n" for ref, body in entries
    ), tuple(refused))  # fmt: skip


def rendered_figures(project: Project) -> dict[str, Path | None]:
    """Each figure the project renders, by its key, with the file pdfLaTeX includes for it, or
    None where it is rendered only in a format pdfLaTeX does not include (an SVG, a TIFF)."""
    from manuscript_guard.build.assemble import FIGURE_PREFERENCE

    folder = project.path("figures")
    files = folder.iterdir() if folder.is_dir() else ()
    keys = sorted({path.stem for path in files if path.suffix.lower() in FIGURE_PREFERENCE})
    found: dict[str, Path | None] = {}
    for key in keys:
        candidates = (folder / f"{key}{suffix}" for suffix in PDFLATEX_FIGURES)
        found[key] = next((path for path in candidates if path.is_file()), None)
    return found


def entry_folders(project: Project) -> list[Path]:
    """The folder of each LaTeX document's entry file: the main text's, and the supplement's
    where it has one."""
    from manuscript_guard.text.reader import LATEX, latex_entry, manuscript_format

    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        return []
    return [each for each in (folder, folder / "supplementary") if latex_entry(each)]


def check_values(project: Project, namespace: dict[str, Value], results: Results) -> Report:
    """G1: each LaTeX document's values file is what `values` would write from the results as
    they stand. It is missing where its entry file loads it, stale where it differs, since a
    PDF compiled from it shows the numbers it was written with, and a value it cannot print is
    said. A Markdown manuscript has none."""
    report = Report()
    written_files = values_files(project, namespace, results)
    if not written_files:
        return report  # a Markdown manuscript, whose files are not read here
    bound = bound_refs(project)
    for written in written_files:
        shown = _shown(project, written.path)
        # Only a value the document binds is said: one nothing binds is printed nowhere
        # (round 1 of step 4b).
        binds = bound.get(written.path.parent, set())
        report = report.with_findings(*(Finding(
            gate="G1", code="value-not-printable", message=str(found), path=written.path,
            hint="emit the value with characters the values file prints, or write the "
            "symbol in the .tex beside the binding",
        ) for found in written.refused if found.ref in binds))  # fmt: skip
        if not written.path.is_file():
            if _loads_values(written.path.parent):
                report = report.with_findings(Finding(
                    gate="G1", code="values-file-missing",
                    message=f"{shown} is not there, and the entry file beside it loads it",
                    path=written.path, hint="run `manuscript-guard values`, and commit the file",
                ))  # fmt: skip
            continue
        on_disk = written.path.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
        if on_disk != written.text:
            report = report.with_findings(Finding(
                gate="G1", code="values-file-stale",
                message=f"{shown} is not what `values` writes from the results as they stand, "
                "so a PDF compiled from it shows other numbers than the results",
                path=written.path, hint="run `manuscript-guard values`, and commit the file",
            ))  # fmt: skip
    return report


def bound_refs(project: Project) -> dict[Path, set[str]]:
    """The keys each LaTeX document binds, by the folder of its entry file."""
    from manuscript_guard.gates.numbers import is_supplementary
    from manuscript_guard.text.reader import bound_files

    manuscript = project.path("manuscript")
    found: dict[Path, set[str]] = {}
    for bound in bound_files(project):
        folder = manuscript / "supplementary" if is_supplementary(manuscript, bound.path) \
            else manuscript  # fmt: skip
        found.setdefault(folder, set()).update(p.ref for p in bound.placeholders)
    return found


def _loads_values(folder: Path) -> bool:
    """Whether the document whose entry file is in `folder` loads the values file, outside a
    comment, in the entry file or a file its preamble inputs (round 1 of step 4b)."""
    from manuscript_guard.text.latex.structure import read_document

    supplementary = folder.name == "supplementary"
    manuscript = folder.parent if supplementary else folder
    sources = read_document(manuscript, supplementary=supplementary).sources
    return any(name == NAME.removesuffix(".sty") for source in sources if not source.loose
               for _at, name in source.reading.packages)  # fmt: skip


def _shown(project: Project, path: Path) -> str:
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return str(path)


def values_files(project: Project, namespace: dict[str, Value], results: Results) -> list[Written]:
    """What `values` writes beside each LaTeX entry file, from the results as they stand."""
    digest = results_digest(project.root, results)
    figures = rendered_figures(project)
    return [contents(folder, namespace, results, figures, digest)
            for folder in entry_folders(project)]  # fmt: skip


def results_digest(root: Path, results: Results) -> str:
    """The digest of the results a values file was written from: each fragment, by its path
    from the project and the digest of its bytes, in the order of the paths."""
    found = hashlib.sha256()
    for fragment in sorted(results.fragments, key=lambda each: each.path.as_posix()):
        try:
            name = fragment.path.relative_to(root).as_posix()
        except ValueError:
            name = fragment.path.name
        found.update(f"{name}\0{hashlib.sha256(fragment.path.read_bytes()).hexdigest()}\n"
                     .encode())  # fmt: skip
    return found.hexdigest()


_HEAD = r"""% manuscript-guard values, from the results sha256:{digest}
% Written by `manuscript-guard values`; `check` compares it with what that would write.
\NeedsTeXFormat{{LaTeX2e}}
\ProvidesPackage{{mgvalues}}[manuscript-guard values]
\DeclareRobustCommand{{\mg}}[2][]{{%
  \ifcsname mg@#2\endcsname
    \csname mg@#2\endcsname{{#1}}%
  \else
    \textbf{{??}}\,\texttt{{\detokenize{{#2}}}}%
    \PackageWarning{{mgvalues}}{{No value for \detokenize{{#2}}}}%
  \fi}}
"""
