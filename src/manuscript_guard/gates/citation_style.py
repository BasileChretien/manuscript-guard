"""G4: the journal's citation style is the one every build formats with.

The profile names the journal's style (`references: {csl: ...}`). A live build hands it to
Zotero; an offline build uses the copy `manuscript-guard style` keeps in the project. Where
there is no copy, or the copy is not what was fetched, the offline build formats in pandoc's
default style, and the document a co-author or CI builds looks like no journal's. And a style
that numbers its citations, for a journal the profile says does not (or the other way
round), is a profile with one of the two wrong. Each is a warning, read offline.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.journal_style import (
    NUMERIC,
    changed,
    is_file_name,
    profile_style,
    read_record,
    record_path,
    style_name,
)

GATE = "G4"


def _finding(code: str, message: str, hint: str, path: Path) -> Report:
    return Report((Finding(GATE, code, message, severity=WARN, path=path, hint=hint),))


def check_style(project: Project, document: dict, path: Path) -> Report:
    named = profile_style(document)
    if not named:
        return Report()
    name = style_name(named)
    if name is None:
        file_named = "; a name with `.csl` is a file's, and the repository's has none" if (
            is_file_name(named)) else ""  # fmt: skip
        return _finding(
            "journal-style-not-stored",
            f"the profile names the citation style {named!r}, which is not a name of the CSL "
            f"style repository{file_named}, so an offline build formats citations in pandoc's "
            "default style",
            "name the style as the repository does (`the-lancet`, or its zotero.org/styles "
            "URL) and run `manuscript-guard style`, or build with `--csl FILE`",
            path,
        )
    record = read_record(project, name)
    if record is None:
        return _finding(
            "journal-style-not-stored",
            f"the profile names the citation style {name}, and the project holds no copy of "
            "it, so an offline build formats citations in pandoc's default style",
            "run `manuscript-guard style` to fetch it from the CSL style repository once",
            path,
        )
    report = Report()
    wrong = changed(project, record)
    if wrong:
        report = report.merge(
            _finding(
                "journal-style-changed",
                f"the stored citation style {name} is not as it was fetched on "
                f"{record['retrieved_on']}: {', '.join(wrong)}; an offline build does not use "
                "it, and formats citations in pandoc's default style",
                "run `manuscript-guard style --again` to fetch it again; a style you changed "
                "on purpose is passed by hand, with `--csl FILE`",
                record_path(project, name),
            )
        )
    numbered = (document.get("references") or {}).get("numbered")
    found = record.get("citation_format")
    if isinstance(numbered, bool) and found and numbered != (found == NUMERIC):
        said = "numbered" if numbered else "not numbered"
        report = report.merge(
            _finding(
                "journal-style-format",
                f"the profile says citations are {said}, and the style {name} formats them "
                f"{found}",
                "one of the two is wrong: read the journal's instructions again, and correct "
                "`numbered:` or `csl:` in the profile",
                path,
            )
        )
    return report


__all__ = ["check_style"]
