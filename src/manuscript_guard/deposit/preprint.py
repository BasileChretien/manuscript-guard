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
import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

from manuscript_guard.contracts.project import Project

from .archive import entry_bytes, tar_bytes
from .bundles import Bundle, DepositError, _checklists
from .plan import Entry, Withheld, _is_junction, copied, generated

#: The figures medRxiv takes beside the document, as `submit` packs them.
PICTURES = {".png", ".pdf", ".tif", ".tiff", ".eps"}
#: The other pictures the build puts in a document (`assemble.FIGURE_PREFERENCE`), each
#: named as left out beside it.
OTHER_PICTURES = {".jpg", ".jpeg", ".svg"}
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


def _documents(project: Project) -> list[tuple[Path, str, str | None]]:
    """The documents medRxiv is sent, each with why: the .docx of a Markdown manuscript
    built offline, or the PDF of a LaTeX one, and the supplement's; and, for a PDF, the
    digest the custodian signs it by, that of what it is compiled from (`built_from`). A
    .docx is built at a fixed date (`fixed_date`), so that its bytes are signed."""
    if _is_latex(project):
        from manuscript_guard.cli import _latex_engine

        packed = _latex(project)
        _undefined(packed)
        source = built_from(packed, _latex_engine(project))
        return [(pdf, "a document compiled from the LaTeX source", source)
                for pdf in packed.documents]  # fmt: skip
    with fixed_date():
        return [(path, why, None) for path, why in _word(project)]


def _is_latex(project: Project) -> bool:
    from manuscript_guard.text.reader import LATEX, manuscript_format

    return manuscript_format(project.path("manuscript")) == LATEX


#: The date a document built for a deposit carries: 1980-01-01, the first a .zip can hold, as
#: the archives' members carry. Not the clock, so that the same sources give the same bytes,
#: and not the last commit's, which the sign-off's own commit moves.
FIXED_DATE = "315532800"


@contextlib.contextmanager
def fixed_date() -> Iterator[None]:
    """SOURCE_DATE_EPOCH set to `FIXED_DATE` while the documents build: pandoc dates the
    .docx's members and its core properties by it, and the build's stamp dates its own
    part as pandoc dated the rest."""
    before = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = FIXED_DATE
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("SOURCE_DATE_EPOCH", None)
        else:
            os.environ["SOURCE_DATE_EPOCH"] = before


def built_from(packed, engine: str) -> str:
    """What a compiled PDF is signed off by: the tool's version, the LaTeX engine that
    compiled it (round 2 of #460) and every file of the folder it was compiled from, with its
    digest. The PDF's bytes are the author's TeX's, which may write the clock into them, so
    they are not what is signed (see DESIGN, Known gaps)."""
    from manuscript_guard import __version__
    from manuscript_guard.sign_offs import digest_of

    from .plan import _digest

    files = []
    for path in packed.files:
        found = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        files += [(p.relative_to(packed.folder).as_posix(), _digest(p)) for p in found
                  if p.is_file()]  # fmt: skip
    return digest_of("compiled from", f"manuscript-guard {__version__}", f"engine {engine}",
                     sorted(files))


def _word(project: Project) -> list[tuple[Path, str]]:
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

    documents = _documents(project)
    entries = [copied(path, path.name, why) for path, why, _source in documents]
    signed_as = tuple((path.name, source) for path, _why, source in documents if source)
    withheld = []
    figures = project.path("figures")
    for path in sorted(figures.iterdir()) if figures.is_dir() else []:
        suffix = path.suffix.lower()
        if suffix not in PICTURES and suffix not in OTHER_PICTURES:
            continue
        at = f"figures/{path.name}"
        if path.is_symlink() or _is_junction(str(path)):
            # As `package` withholds a link: what it leads to is not the project's to send.
            withheld.append(Withheld(at, "a link, whose target is outside what a bundle holds"))
        elif not path.is_file():
            continue
        elif suffix in OTHER_PICTURES:
            withheld.append(Withheld(at, "a picture in a format `submit` does not pack beside "
                                     "the document, which takes "
                                     + ", ".join(sorted(PICTURES))))  # fmt: skip
        else:
            entries.append(copied(path, at, "a figure"))
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
    return Bundle("medrxiv", "preprint", tuple(sorted(entries, key=lambda e: e.path)),
                  tuple(withheld), signed_as=signed_as)  # fmt: skip


__all__ = ["ARXIV_SHEET", "MEDRXIV_SHEET", "arxiv", "medrxiv"]
