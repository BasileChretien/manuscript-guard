"""A LaTeX source and its PDF built from a Markdown manuscript, `build --latex` (DESIGN.md,
"LaTeX out of Markdown", step 11).

The document is assembled as the Word build assembles it, and pandoc writes it as LaTeX:
with the class and options the journal's profile names, natbib or biblatex as its
`bibliography:` says, or citeproc with the citation style where it says neither, and the
title, keywords and authors as the template's variables. The source goes in one folder, as
the LaTeX submission folder does (`latex_pack.py`), with each picture under its name and the
`.bib` cut to the cited entries, and is compiled alone there.

What pandoc writes is checked twice past the gates, which read the Markdown:
1. the LaTeX reader reads the body pandoc writes, without the template, and refuses what it
   refuses, raw TeX the Word writer drops among it (`MisreadError`);
2. the digits the reader keeps in that body must be the ones the Markdown reader keeps in
   the assembled Markdown, in order (`MisreadError`). The template, the title page and the
   front matter are on neither side. Each difference pandoc makes on purpose is put right on
   one side, measured against pandoc 3.9: a figure's alternative text, which LaTeX holds in
   `\\includegraphics`'s options, is taken out of the Markdown; so is the number of an
   ordered list's item, which LaTeX prints from its counter; a footnote's digits are read at
   each of its marks, where pandoc writes it; a `longtable`'s header repeated for the pages it
   runs on to is passed over, and its caption, which pandoc writes first, may stand before or
   after its rows; and under citeproc, the citations and the reference list pandoc writes
   as text are passed over.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.build.document import BuildError, MisreadError

#: The longest pandoc is given to write one document.
PANDOC_SECONDS = 300
#: The shape the build writes a figure in, its alternative text first (`assemble.py`).
_FIGURE = re.compile(r"\[!\[(?P<alt>(?:\\.|[^\]\\])*)\]\((?:[^)\\]|\\.)*\)\]\{\.mg-figure\}")
#: A list item's marker, from the item's start: past a block quote's `>` and the indent.
_MARKER = re.compile(r"[ \t>]*\(?(?P<marker>[0-9]{1,9})[.)]")
#: What pandoc writes round a citation and the reference list under citeproc.
_CITEPROC = re.compile(r"\\citeproc\{")
_REFERENCES = re.compile(r"\\begin\{CSLReferences\}.*?\\end\{CSLReferences\}", re.DOTALL)
#: A character pandoc writes in text as a command, with what ends the command's name: what an
#: address holds as one character (round 3 of step 11).
_PRINTED_SIGN = re.compile(r"\\(?:textasciitilde|textasciicircum|textbackslash|textbar|textless|"
                           r"textgreater|textquotedbl|textquotesingle|ldots)(?:\{\}| (?=\S))?"
                           r"|\\\^\{\}|\\[_%&#$~{}]")
#: A key in a citation's item, as pandoc reads one: a letter, a digit, `_` or a brace after the
#: `@` (round 4 of step 11).
_KEYED = re.compile(r"(?<![\w`])-?@[\w{]")
#: A footnote's mark, and its definition at the start of a line, as `sections.py` reads them.
_NOTE_MARK = re.compile(r"\[\^(?P<label>[^\]\s]+)\]")
_NOTE_DEFINITION = re.compile(r"[ ]{0,3}\[\^(?P<label>[^\]\s]+)\]:")
#: The brackets after a narrative citation, which pandoc reads as its locator.
_LOCATOR = re.compile(r"[ \t]*\[[^\]\n]*\]")
#: A `longtable`'s caption, and its header repeated on each page it runs on to.
_CAPTION = re.compile(r"\\caption\s*\{")
_REPEATED = re.compile(r"\\endfirsthead(?P<head>.*?)\\endhead", re.DOTALL)


@dataclass(frozen=True)
class Citations:
    """How the source cites: `natbib` or `biblatex`, with the profile's style, or
    `citeproc` with the citation style's file."""

    kind: str
    style: str | None = None
    csl: Path | None = None


def citations(project, csl: Path | None) -> Citations:
    """As the journal's profile says under `latex: {bibliography: ...}`: BibTeX through natbib,
    biblatex, or neither, which citeproc formats."""
    from manuscript_guard.gates.journal import _profile

    stated = (((_profile(project) or {}).get("latex") or {}).get("bibliography")) or {}
    if stated.get("kind") == "bibtex":
        return Citations("natbib", stated.get("bst"))
    if stated.get("kind") == "biblatex":
        return Citations("biblatex", stated.get("style"))
    return Citations("citeproc", csl=csl)


def build_from_markdown(project, assembled, *, engine: str = "pdflatex",
                        csl: Path | None = None):  # fmt: skip
    """Write the LaTeX folder of each document, check what pandoc wrote, and compile it alone:
    the folder, its files and the PDFs, as `latex_pack.LatexPack`."""
    from manuscript_guard.build.latex import fresh_root
    from manuscript_guard.build.latex_pack import (
        MAIN,
        STAGED,
        SUPPLEMENT,
        LatexPack,
        _alone,
        _Names,
    )

    cited = citations(project, csl)
    root = fresh_root(project)
    folder = root / STAGED
    folder.mkdir()
    names = _Names([f"{name}.{suffix}" for name in (MAIN, SUPPLEMENT)
                    for suffix in ("tex", "pdf", "bbl", "aux", "log")]
                   + ["references.bib"])  # fmt: skip
    written, keys = [], set()
    for supplementary in (False, True):
        body_markdown = _markdown(project, assembled, supplementary=supplementary)
        if body_markdown is None:
            continue
        name = SUPPLEMENT if supplementary else MAIN
        # The header too, which prints nothing without the template: citeproc writes the
        # reference list in the document's language, as the standalone document has it.
        header = _header(project, supplementary)
        body = _pandoc(project, header + body_markdown, _citing(project, cited))
        reading = _checked(body, body_markdown, cited, name)
        keys |= {found.key for found in reading.cited}
        whole = _pandoc(project, header + body_markdown,
                        ["--standalone", *_template(project), *_citing(project, cited)])
        written_out = _pictures(project, whole, body, reading, folder, names)
        (folder / f"{name}.tex").write_text(written_out, encoding="utf-8", newline="")
        written.append(name)
    if cited.kind != "citeproc" and keys:
        from manuscript_guard.build.latex_pack import _cut

        bib = project.path("literature") / "references.bib"
        if not bib.is_file():
            raise BuildError(f"{bib} does not exist; run `manuscript-guard sync-bib` with Zotero "
                             "open")  # fmt: skip
        (folder / "references.bib").write_text(
            _cut(bib.read_text(encoding="utf-8", errors="replace"), None if "*" in keys else keys),
            encoding="utf-8", newline="\n")  # fmt: skip
    alone = _alone(project, folder, written, engine, headings=False)
    # Every file but the documents' PDFs: a figure may be a PDF (round 2 of step 11).
    made = {f"{name}.pdf" for name in written}
    files = tuple(sorted(path for path in folder.iterdir() if path.name not in made))
    undefined = tuple(dict.fromkeys(left for compiled in alone for left in compiled.undefined))
    return LatexPack(folder, files, tuple(compiled.pdf for compiled in alone), undefined,
                     tuple(alone))  # fmt: skip


def _markdown(project, assembled, *, supplementary: bool) -> str | None:
    """The document's Markdown, assembled as the Word build's is; None for a supplement the
    manuscript does not have."""
    from manuscript_guard.build.document import document_files, document_text
    from manuscript_guard.gates.numbers import is_supplementary, source_files

    folder = project.path("manuscript")
    # `document_files` refuses a supplement the manuscript does not have (round 1 of step 11).
    if supplementary and not any(is_supplementary(folder, path)
                                 for path in source_files(folder)):  # fmt: skip
        return None
    ordered = document_files(project, assembled, supplementary=supplementary)
    if not ordered:
        return None
    return document_text(ordered)


def _pandoc(project, markdown: str, arguments: list[str]) -> str:
    """What pandoc writes as LaTeX for `markdown`, run from the project's folder."""
    from manuscript_guard.build.document import pandoc

    # Code as `verbatim`: highlighted, it is commands whose arguments the reader reads.
    command = [pandoc(), "-f", "markdown", "-t", "latex", "--wrap=preserve", "--no-highlight",
               *arguments]  # fmt: skip
    try:
        done = subprocess.run(command, input=markdown, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=project.root,
                              timeout=PANDOC_SECONDS, check=False)  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"pandoc took longer than {PANDOC_SECONDS} s to write the LaTeX") from exc
    if done.returncode != 0:
        raise BuildError(f"pandoc failed:\n{done.stderr.strip()}")
    return done.stdout


def _citing(project, cited: Citations) -> list[str]:
    if cited.kind == "natbib":
        return ["--natbib", "--metadata=bibliography:references.bib",
                *([f"--variable=biblio-style:{cited.style}"] if cited.style else [])]  # fmt: skip
    if cited.kind == "biblatex":
        options = [f"--variable=biblatexoptions:style={cited.style}"] if cited.style else []
        return ["--biblatex", "--metadata=bibliography:references.bib", *options]
    from manuscript_guard.build.document import relative_to_root

    bib = project.path("literature") / "references.bib"
    arguments = ["--citeproc", "--metadata=link-citations:true"]
    if bib.is_file():
        arguments.append(f"--bibliography={relative_to_root(project, bib)}")
    if cited.csl is not None:
        arguments.append(f"--csl={relative_to_root(project, cited.csl.resolve())}")
    return arguments


def _template(project) -> list[str]:
    """The class and options the journal's profile names, and its pandoc template where the
    project keeps one beside the profile, `profiles/journals/latex/<slug>/template.latex`."""
    from manuscript_guard.gates.journal import _profile

    stated = (((_profile(project) or {}).get("latex")) or {})
    # Pandoc 3.9's template quotes each keyword for the PDF's properties with `\\xmpquote`,
    # which hyperref defines only in its recent versions: measured, MiKTeX's of 2024-06 does
    # not, and the compile stopped on it. Given where it is not defined, it prints the word.
    arguments = ["--variable=header-includes:\\providecommand{\\xmpquote}[1]{#1}",
                 f"--variable=documentclass:{stated.get('class') or 'article'}"]  # fmt: skip
    arguments += [f"--variable=classoption:{option}" for option in stated.get("class_options", [])]
    slug = project.target_journal
    template = project.root / "profiles" / "journals" / "latex" / str(slug) / "template.latex"
    if slug and template.is_file():
        arguments.append(f"--template={template.resolve()}")
    return arguments


def _header(project, supplementary: bool) -> str:
    """The title, the keywords and, where the journal's review is not blind, the authors, for
    the template to print."""
    from manuscript_guard.build.blinding import BLIND
    from manuscript_guard.build.document import _yaml_text, document_language
    from manuscript_guard.gates.journal import blinding

    paper = project.paper
    title = str(paper.get("title", ""))
    if supplementary:
        title = f"Supplementary material for: {title}"
    lines = ["---", f"title: {_yaml_text(project, 'title', title)}"]
    authors = (project.authors or {}).get("authors") if isinstance(project.authors, dict) else []
    names = [" ".join(str(person.get(part) or "").strip() for part in ("given", "family")).strip()
             for person in authors or [] if isinstance(person, dict)]  # fmt: skip
    if blinding(project) not in BLIND and any(names):
        lines.append("author:")
        lines += [f"  - {_yaml_text(project, 'authors', name)}" for name in names if name]
    keywords = None if supplementary else project.keywords
    if keywords:
        written = ", ".join(_yaml_text(project, "keywords", keyword) for keyword in keywords)
        lines.append(f"keywords: [{written}]")
    lines += [f"lang: {document_language(project)}", "---", ""]
    return "\n".join(lines)


def _pictures(project, text: str, body: str, reading, folder: Path, names) -> str:
    """`text`, the standalone document, with each picture of the project's its body includes
    copied into the folder and named there by its name. The pictures are the reader's of the
    body, which the standalone document holds as pandoc writes it alone: its template is no
    text the reader is asked to read."""
    written = body.strip("\n")
    if not written:
        # A document whose body is empty includes no picture (round 2 of step 11).
        return text
    offset = text.find(written) - (len(body) - len(body.lstrip("\n")))
    if text.find(written) < 0:
        raise BuildError("pandoc's standalone document does not hold its body as pandoc "
                         "writes it alone, so its pictures cannot be placed; please report "
                         "this")  # fmt: skip
    out, at = [], 0
    root = project.root.resolve()
    for _start, end, opened in reading.graphics:
        path = body[opened + 1 : end - 1].strip()
        found = (root / path).resolve()
        if not found.is_file() or not found.is_relative_to(root):
            continue
        name = names.claim(found, path.replace("\\", "/"))
        shutil.copyfile(found, folder / name)
        out += [text[at : offset + opened], "{" + name + "}"]
        at = offset + end
    return "".join(out) + text[at:]


def _checked(body: str, markdown: str, cited: Citations, name: str):
    """The reader's reading of the body pandoc wrote for `markdown`, or `MisreadError` where it
    refuses it or keeps other digits."""
    from manuscript_guard.text.latex.mask import read

    citeproc = cited.kind == "citeproc"
    reading = read(_without_citeproc_keys(body) if citeproc else body, body=True)
    for refusal in reading.refusals:
        line = body.count("\n", 0, refusal.offset) + 1
        raise MisreadError(f"pandoc writes LaTeX for {name} that the LaTeX reader refuses, at "
                           f"line {line} of its body: {refusal.message}. The text that makes "
                           "it is likely TeX written in the Markdown")  # fmt: skip
    differs = compare_digits(markdown, body, reading, citeproc=citeproc)
    if differs is not None:
        raise MisreadError(f"pandoc's LaTeX for {name} prints other digits than the gates read "
                           f"in the Markdown: {differs}")  # fmt: skip
    return reading


def _without_citeproc_keys(body: str) -> str:
    """`body` with the command and the key of each citation citeproc wrote, `\\citeproc{ref-x}`,
    and the reference list as spaces, its line breaks kept, so that the reader reads the text
    a citation prints as a group, which the comparison passes over with the list. The
    commands are pandoc's, and the author-facing reader refuses them as citation commands
    it does not know."""
    spans = [(found.start(), _group_end(body, found.end() - 1))
             for found in _CITEPROC.finditer(body)]  # fmt: skip
    spans += [found.span() for found in _REFERENCES.finditer(body)]
    shown = list(body)
    for start, end in spans:
        for index in range(start, end):
            if shown[index] not in "\r\n":
                shown[index] = " "
    return "".join(shown)


def compare_digits(markdown: str, body: str, reading, *, citeproc: bool) -> str | None:
    """None where the digits the LaTeX reader keeps in `body` are those the Markdown reader
    keeps in `markdown`, in order, less what pandoc moves or LaTeX prints on its own; else
    where they part, said."""
    wanted = _markdown_digits(markdown, citeproc=citeproc)
    at = 0
    for kind, first, second in _latex_units(body, reading, citeproc=citeproc):
        size = len(first) + len(second)
        here = "".join(digit for digit, _ in wanted[at : at + size])
        printed = "".join(digit for digit, _ in first + second)
        rotated = "".join(digit for digit, _ in second + first)
        if here == printed or (kind == "table" and here == rotated):
            at += size
            continue
        both = first + second
        part = next((index for index in range(min(len(here), len(both)))
                     if here[index] != printed[index]), min(len(here), len(both)))  # fmt: skip
        markdown_at = wanted[at + part][1] if at + part < len(wanted) else len(markdown)
        latex_at = both[part][1] if part < len(both) else len(body)
        return (f"LaTeX prints {printed[part : part + 12] or 'nothing'!r} at line "
                f"{body.count(chr(10), 0, latex_at) + 1} of the body, where the Markdown has "
                f"{here[part : part + 12] or 'nothing'!r} at line "
                f"{markdown.count(chr(10), 0, markdown_at) + 1}")
    if at < len(wanted):
        line = markdown.count("\n", 0, wanted[at][1]) + 1
        return f"the Markdown has digits from line {line} that the LaTeX does not print"
    return None


def _markdown_digits(markdown: str, *, citeproc: bool) -> list[tuple[str, int]]:
    """Each digit the Markdown reader keeps, with where it stands: a figure's alternative text
    and an ordered list's numbers taken out, a footnote's digits at each of its marks, and under
    citeproc, whose citations the comparison passes over, each citation with its locator."""
    from manuscript_guard.text.blocks import list_items
    from manuscript_guard.text.masking import mask, masked_spans, metadata_blocks
    from manuscript_guard.text.sections import footnote_index

    shown = list(mask(markdown))
    noted = footnote_index(markdown, unreferenced=True)
    # A note's mark is no number, but one with no definition pandoc prints as it is typed,
    # `[^1]`, in LaTeX as in Word, and the mask blanks it all the same. Only where the mask
    # blanked it as a mark: one in a listing or a comment is not printed (round 2 of step 11).
    # Only a note something marks: a mark inside another note pandoc prints as typed
    # (round 4 of step 11), whatever its label (round 5).
    defined = {found["label"] for note in noted if note.references
               and (found := _NOTE_DEFINITION.match(markdown, note.start)) is not None}  # fmt: skip
    hidden = [span for name, spans in masked_spans(markdown).items() if name != "footnote"
              for span in spans]  # fmt: skip
    for found in _NOTE_MARK.finditer(markdown):
        within = any(note.start < found.start() < note.end for note in noted)
        if (found["label"] in defined and not within
                or any(a <= found.start() < b for a, b in hidden)):  # fmt: skip
            continue
        for index in range(found.start("label"), found.end("label")):
            if markdown[index].isdigit():
                shown[index] = markdown[index]
    # A YAML block pandoc reads as metadata wherever it stands, which the body does not print.
    for start, end in metadata_blocks(markdown):
        for index in range(start, end):
            shown[index] = " "
    if citeproc:
        from manuscript_guard.zotero.citations import NARRATIVE, bracketed

        # Pandoc's citation group: each of its items, apart at `;`, names a key. A bracket
        # with an item that names none is text, and a key in it a narrative citation
        # (measured, round 2 of step 11).
        spans = [found.span() for found in bracketed(markdown)
                 if all(_KEYED.search(item) for item in found["body"].split(";"))]  # fmt: skip
        for found in NARRATIVE.finditer(markdown):
            # `@key [p. 33]`: pandoc takes the brackets after a narrative key as its locator.
            after = _LOCATOR.match(markdown, found.end())
            spans.append((found.start(), after.end() if after else found.end()))
        for start, end in spans:
            for index in range(start, end):
                shown[index] = " "
    for found in _FIGURE.finditer(markdown):
        for index in range(found.start("alt"), found.end("alt")):
            shown[index] = " "
    for start in list_items(markdown):
        marker = _MARKER.match(markdown, start)
        if marker is not None:
            for index in range(marker.start("marker"), marker.end("marker")):
                shown[index] = " "
    placed: dict[int, list[tuple[str, int]]] = {}
    # A note nothing marks pandoc does not print, and its digits go with it (round 2).
    for note in noted:
        digits = [(shown[index], index) for index in range(note.start, note.end)
                  if shown[index].isdigit()]  # fmt: skip
        # Pandoc writes the note at each of its marks (round 1 of step 11).
        for reference in note.references:
            placed.setdefault(reference, []).extend(digits)
        for index in range(note.start, note.end):
            shown[index] = " "
    out: list[tuple[str, int]] = []
    for index, character in enumerate(shown):
        out.extend(placed.get(index, ()))
        if character.isdigit():
            out.append((character, index))
    return out


_Digits = list[tuple[str, int]]


def addresses(body: str, reading) -> list[tuple[int, int]]:
    """Where each address or DOI pandoc writes as text stands in `body`, which the Markdown
    mask blanks (round 1 of step 11). A character pandoc writes as a command is part of it,
    `\\textasciitilde smith` and `a\\_b`, with the space or the `{}` that ends the command's
    name; any other command ends it, `\\footnote{` after one (rounds 2 and 3)."""
    from manuscript_guard.text.latex.mask import NUL
    from manuscript_guard.text.masking import _URL

    view = list(re.sub(f"{NUL}{{2,}}", lambda run: " " * len(run.group()), reading.masked))
    for found in _PRINTED_SIGN.finditer(body):
        for index in range(found.start(), found.end()):
            view[index] = "x"
    return [found.span() for found in _URL.finditer("".join(view))]


def _latex_units(body: str, reading, *, citeproc: bool) -> list[tuple[str, _Digits, _Digits]]:
    """The digits the LaTeX reader keeps, each with where it stands, in order, as runs of text
    and tables: a table's caption apart from its rows, its repeated header and, under
    citeproc, the citations and the reference list passed over."""
    from manuscript_guard.text.latex.mask import NUL

    shown = list(reading.masked.replace(NUL, " "))
    for start, end in addresses(body, reading):
        for index in range(start, end):
            shown[index] = " "
    skipped = [found.span() for found in _REFERENCES.finditer(body)] if citeproc else []
    if citeproc:
        for found in _CITEPROC.finditer(body):
            end = _group_end(body, found.end() - 1)
            skipped.append((found.start(), _group_end(body, end) if end < len(body) else end))
    for start, end in skipped:
        for index in range(start, min(end, len(shown))):
            shown[index] = " "

    def digits(start: int, end: int) -> _Digits:
        return [(shown[index], index) for index in range(start, min(end, len(shown)))
                if shown[index].isdigit()]  # fmt: skip

    units: list[tuple[str, _Digits, _Digits]] = []
    at = 0
    for start, end in sorted(reading.tables):
        if start < at:
            continue
        units.append(("text", digits(at, start), []))
        for found in _REPEATED.finditer(body, start, end):
            for index in range(found.start("head"), found.end("head")):
                shown[index] = " "
        caption = _CAPTION.search(body, start, end)
        if caption is None:
            units.append(("text", digits(start, end), []))
        else:
            close = _group_end(body, caption.end() - 1)
            units.append(("table", digits(caption.start(), close),
                          digits(start, caption.start()) + digits(close, end)))  # fmt: skip
        at = end
    units.append(("text", digits(at, len(shown)), []))
    return units


def _group_end(text: str, opened: int) -> int:
    """Past the brace group that opens at `opened`."""
    depth = 0
    for at in range(opened, len(text)):
        if text[at] == "\\":
            continue
        if text[at] == "{" and text[at - 1 : at] != "\\":
            depth += 1
        elif text[at] == "}" and text[at - 1 : at] != "\\":
            depth -= 1
            if depth == 0:
                return at + 1
    return len(text)
