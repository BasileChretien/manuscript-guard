"""The editor's report as a PDF: what `audit --editor --pdf` writes (Basile, 2026-11-26: the
PDF gives the editor's four parts with `--editor` alone, as the text does; without it the PDF
stays the full report, `auditing.report_pdf`).

It is drawn with the full report's parts, so that the two read alike:

* the cover band, titled "Editor's report on" the papers, with the summary line's counts,
  the self-citation counts and what could not be read under it, then the scope sentence;
* "In this report": each part with its count, and each kind under it with its count, each a
  link to its place;
* each part under a heading of its own, its number, its title and its count, and "None found
  by these checks." where it holds nothing; under it each kind, in the editor's sentence,
  with how often it was right on published papers (the first three parts), and every place
  of every finding, as `--details` lists them, the words it quotes under a rule;
* what an audit leaves to a paper written with manuscript-guard, as the full report ends.

Each part is a bookmark, each kind under its part's, and the frame is the full report's.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from manuscript_guard.auditing import editor
from manuscript_guard.auditing.report_pdf import (
    FAINT,
    HOME,
    LINE,
    MUTED,
    SHOWN_HOME,
    _closing,
    _contents_of,
    _cover,
    _flow,
    _heading,
    _kind,
    gates_run,
)
from manuscript_guard.pdfwriter import Margins, Pdf

#: What a part that holds nothing says, as the text says it.
NONE_FOUND = "None found by these checks."
#: The report's last line, before what an audit leaves to a paper written with the tool.
FULL = ("What each finding says in full, and what to do about it, is in the full report: the "
        "same audit without --editor.")  # fmt: skip


def _part_key(part: str) -> str:
    return f"part:{part}"


def _kind_key(part: str, at: int) -> str:
    return f"part:{part}:{at}"


def _summary(report, by_part: dict[str, list]) -> list[str]:
    """The lines under the title: the summary line's counts, the self-citation counts, and
    each paper or file that could not be read (`editor.render`)."""
    lines = [" · ".join(f"{len(by_part[key])} {said}" for key, said in editor.COUNTED.items())]
    cited = editor.self_citation_line(getattr(report, "self_citation", None))
    if cited:
        lines.append(cited)
    unread = [item for key in by_part for item, kind in by_part[key] if kind.name == "unread"]
    return lines + [f"Not read: {item.message}" for item in unread]


def _place(item, kind, root: Path | None, placers: dict) -> dict:
    """One place of a finding as the full report's PDF draws one (`reader._place`): where,
    what the editor's report says of it, said for a reader, and the words it quotes, as an
    excerpt, where the saying does not already give them."""
    from manuscript_guard.auditing.reader import excerpt, for_a_reader

    quoted = kind.quoted and item.subject and item.context
    return {"where": editor._where(item, root, placers) or "the submission",
            "message": for_a_reader(editor._said(item, kind)),
            "context": None if quoted or not item.context else excerpt(item.context),
            "hint": None}  # fmt: skip


def _kinds(here: list) -> list[tuple[object, list]]:
    """The kinds of a part in the table's order, each with its items."""
    return [(kind, [item for item, of in here if of is kind])
            for kind in (*editor.KINDS, editor.FURTHER)
            if any(of is kind for _item, of in here)]  # fmt: skip


def _drawn(report, title: str, version: str, on: datetime.date, pages: dict[str, int],
           root: Path | None) -> Pdf:  # fmt: skip
    """The editor's report drawn, the contents giving each part's page from `pages`."""
    from manuscript_guard.gates import GATES

    found = editor.parted(report)
    placers = getattr(report, "placers", None) or {}
    by_part = {key: [(item, kind) for item, kind in found if kind.part == key]
               for key, _title in editor.PARTS}  # fmt: skip
    pdf = Pdf(title=title, producer=f"manuscript-guard {version}", author="manuscript-guard",
              subject="What manuscript-guard's audit found in a paper, as an editor reads it",
              frame=Margins(running=title, foot=f"Made with manuscript-guard {version}  ·  "
                            f"{SHOWN_HOME}", uri=HOME, color=FAINT, rule=LINE,
                            home="contents"))  # fmt: skip
    _cover(pdf, {"header": _summary(report, by_part)}, title, version, on)
    _flow(pdf, editor.SCOPE, size=9.3, color=MUTED)
    contents: list[tuple[str, str, int | None, int]] = []
    for number, (key, heading) in enumerate(editor.PARTS, 1):
        contents.append((f"{number}. {heading}", _part_key(key), len(by_part[key]), 0))
        contents += [(kind.says, _kind_key(key, at), len(items), 1)
                     for at, (kind, items) in enumerate(_kinds(by_part[key]))]  # fmt: skip
    _contents_of(pdf, contents, pages)
    for number, (key, heading) in enumerate(editor.PARTS, 1):
        here = by_part[key]
        _heading(pdf, f"{number}. {heading} ({len(here)})", key=_part_key(key), back=False)
        if not here:
            _flow(pdf, NONE_FOUND, size=9.3, color=MUTED)
            continue
        for at, (kind, items) in enumerate(_kinds(here)):
            _kind(pdf, {"title": kind.says, "count": len(items),
                        "note": None if key == editor.READ else editor.record_said(kind),
                        "places": [_place(item, kind, root, placers) for item in items]},
                  _kind_key(key, at))  # fmt: skip
    _closing(pdf, {"closing": FULL}, len(GATES), gates_run(report))
    return pdf


def editor_pdf(report, root: Path | None, paper_names: list[str], *,
               on: datetime.date | None = None) -> bytes:  # fmt: skip
    """The PDF of the editor's report on the audit `report`, its places said from `root`,
    titled by `paper_names`; dated `on`, today by default."""
    from manuscript_guard import __version__

    title = f"Editor's report on {', '.join(paper_names) or 'the paper'}"
    day = on or datetime.date.today()
    # Drawn twice, as the full report is: the contents give each part's page, which only a
    # drawing says (`report_pdf.written`).
    first = _drawn(report, title, __version__, day, {}, root)
    pages = {key: page + 1 for key, (page, _top) in first.places.items()}
    return _drawn(report, title, __version__, day, pages, root).bytes()
