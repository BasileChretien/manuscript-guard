"""The preprint bundles: the paper as arXiv compiles it, and as medRxiv reads it.

- arXiv takes the LaTeX source. A LaTeX manuscript's is the submission folder `submit`
  writes (`build/latex_pack.pack_latex`): each document one file, its inputs and bindings
  written in, its comments out, with the figures and the `.bbl`, compiled alone in an empty
  folder. A Markdown manuscript is written as LaTeX first, as `build --latex` writes it
  (`build/latex_out.build_from_markdown`). Either needs TeX, and is refused without it. The
  archive is a .tar.gz of the main document's source; the supplement, a second document,
  stays out.
- medRxiv takes the documents: the .docx `build --offline` makes of a Markdown manuscript,
  or the PDF a LaTeX one compiles to, the supplement beside it, the figures, each reporting
  checklist as a table (G5), the declarations and the CRediT statement (G4).

Each comes with its sheet (`sheets.py`). Nothing is uploaded: neither server has an
interface the tool sends through.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from manuscript_guard.contracts.project import Project

from .archive import entry_bytes, tar_bytes
from .bundles import Bundle, DepositError, _checklists
from .plan import Entry, copied, generated

#: The figures medRxiv takes beside the document, as `submit` packs them.
PICTURES = {".png", ".pdf", ".tif", ".tiff", ".eps"}
ARXIV_SHEET = "arxiv_submission_sheet.md"
MEDRXIV_SHEET = "medrxiv_submission_sheet.md"


def _latex(project: Project):
    """The submission folder of the manuscript, a `LatexPack`, built and compiled alone."""
    from manuscript_guard.build import BuildError
    from manuscript_guard.build.latex import LatexMissing
    from manuscript_guard.build.latex_pack import pack_latex
    from manuscript_guard.cli import _latex_engine, _latex_from_markdown
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if manuscript_format(project.path("manuscript")) != LATEX:
        packed = _latex_from_markdown(project, argparse.Namespace(csl=None))
        if isinstance(packed, int):
            raise DepositError("", packed)
        return packed
    namespace, results, _literature, _ = load_namespace(project)
    try:
        return pack_latex(project, namespace, results, engine=_latex_engine(project))
    except LatexMissing as exc:
        raise DepositError(str(exc), 2) from None
    except (BuildError, OSError) as exc:
        raise DepositError(f"the LaTeX source is not built: {exc}") from None


def _undefined(packed) -> None:
    if packed.undefined:
        raise DepositError("LaTeX left " + ", ".join(packed.undefined) + " undefined; the "
                           "PDF prints `?` where each stands, and the preprint is not "
                           "staged")  # fmt: skip


def arxiv(project: Project) -> Bundle:
    """The main document's LaTeX source as a .tar.gz, and the sheet."""
    from manuscript_guard.build.latex_pack import SUPPLEMENT
    from manuscript_guard.cli import _latex_engine

    packed = _latex(project)
    _undefined(packed)
    notes = []
    sources: list[Entry] = []
    for path in sorted(packed.files):
        if not path.is_file():
            notes.append(f"{path.name}/ is a folder of the source, and is not in the archive")
        elif path.stem == SUPPLEMENT:
            continue
        else:
            sources.append(copied(path, path.name, "the LaTeX source arXiv compiles"))
    names = [entry.path for entry in sources]
    size = len(tar_bytes([(entry.path, entry_bytes(entry)) for entry in sources]))
    pdf = packed.documents[0]
    shown = pdf.relative_to(project.root).as_posix() if pdf.is_relative_to(project.root) \
        else pdf.name  # fmt: skip
    from .sheets import arxiv_sheet

    sheet = generated(ARXIV_SHEET, arxiv_sheet(project, files=names, size=size, pdf=shown,
                                               engine=_latex_engine(project)),
                      "what arXiv's form asks, and what the project records")  # fmt: skip
    if any(path.stem == SUPPLEMENT for path in packed.files):
        notes.append("the supplement is not in the archive: arXiv compiles one document a "
                     "submission")  # fmt: skip
    return Bundle("arxiv", "preprint", tuple(sorted([*sources, sheet], key=lambda e: e.path)),
                  tarred=tuple(names), notes=tuple(notes))  # fmt: skip


def _documents(project: Project) -> list[tuple[Path, str]]:
    """The documents medRxiv is sent, each with why: the .docx of a Markdown manuscript
    built offline, or the PDF of a LaTeX one, and the supplement's."""
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if manuscript_format(project.path("manuscript")) == LATEX:
        packed = _latex(project)
        _undefined(packed)
        return [(pdf, "a document compiled from the LaTeX source") for pdf in packed.documents]
    from manuscript_guard.build import OFFLINE, BuildError, MisreadError, assemble, build_document
    from manuscript_guard.cli import _build_supplement, _journal_style, _print_assembly_warnings
    from manuscript_guard.contracts import load_namespace

    namespace, results, _literature, _ = load_namespace(project)
    assembled, report = assemble(project, namespace, results)
    if not report.ok:
        print(report.render(project.root))
        raise DepositError("", 1)
    _print_assembly_warnings(report, project)
    style = _journal_style(project, argparse.Namespace(csl=None, offline=True))
    try:
        built = build_document(project, assembled, mode=OFFLINE, csl=style)
        if not built.report.ok:
            print(built.report.render(project.root))
            raise DepositError("the document did not build cleanly")
        supplement = _build_supplement(project, assembled, mode=OFFLINE, csl=style)
    except MisreadError as exc:
        raise DepositError(str(exc)) from None
    except BuildError as exc:
        raise DepositError(str(exc), 2) from None
    found = [(built.output, "the manuscript, built offline")]
    if supplement is not None:
        found.append((supplement, "the supplement, its own document"))
    return found


def medrxiv(project: Project) -> Bundle:
    """The documents, the figures, the checklists, the declarations, and the sheet."""
    from manuscript_guard.build.submission import SubmissionError, credit_statement, declarations

    entries = [copied(path, path.name, why) for path, why in _documents(project)]
    figures = project.path("figures")
    for path in sorted(figures.iterdir()) if figures.is_dir() else []:
        if path.is_file() and path.suffix.lower() in PICTURES:
            entries.append(copied(path, f"figures/{path.name}", "a figure"))
    entries += _checklists(project)
    try:
        entries.append(generated("declarations.md", declarations(project),
                                 "funding and competing interests, as authors.yaml records"))
        entries.append(generated("credit-statement.md", credit_statement(project),
                                 "each author's CRediT roles"))  # fmt: skip
    except SubmissionError as exc:
        raise DepositError(str(exc), 2) from None
    from .sheets import medrxiv_sheet

    names = sorted(entry.path for entry in entries)
    entries.append(generated(MEDRXIV_SHEET, medrxiv_sheet(project, files=names),
                             "what medRxiv's form asks, and what the project records"))
    return Bundle("medrxiv", "preprint", tuple(sorted(entries, key=lambda e: e.path)))


__all__ = ["ARXIV_SHEET", "MEDRXIV_SHEET", "arxiv", "medrxiv"]
