"""TeX in the text, as `check` reports it: what the build would refuse, and warn of.

Pandoc reads a backslash before a letter as TeX wherever it stands outside maths, and the
Word writer leaves it out with whatever the command takes after it. The gates read the
sources, and every one of them counted that text as printed. The build asks pandoc how it
reads the document and refuses (`reading.misreading`), so an author learned of it at the
build, after `check` had passed.

A rule that reads the sources as the gates do was the first plan, and it could only
over-report: what pandoc takes for TeX turns on citations, brackets, `<`, line breaks and
the values put in. So `check` asks pandoc too, where pandoc is installed, with the text the
build would hand it. What it reports is then what the build refuses, in the build's words,
and nothing else. Where pandoc is not installed it says so in a note and passes: the build,
which cannot run without pandoc either, judges it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from manuscript_guard.build import reading
from manuscript_guard.build.assemble import assemble
from manuscript_guard.build.document import (
    _KINDS_NAMED,
    GATE,
    BuildError,
    _front_matter,
    as_read,
    document_files,
    document_text,
    does_nothing,
    kinds_of,
)
from manuscript_guard.contracts import ContractError
from manuscript_guard.findings import INFO, Finding, Report

#: TeX in the text that the Word writer leaves out. It fails from `drafting` on
#: (`policy.BINDS_AT`).
CODE = "tex-in-the-text"
#: The note that TeX in the text was not judged. Never a failure, and no finding of TeX:
#: its severity is `info`, as that of a finding put off to a later stage is, and its code
#: is its own.
NOT_JUDGED = "tex-not-judged"
#: How many documents pandoc read: the paper, and its supplement where there is one. A
#: pass over none reads otherwise like a pass.
READ = "documents_read_for_tex"
#: How many seconds `check` waits for pandoc to read one document. Pandoc reads the example
#: in a tenth of a second and its text two hundred times over, 164,000 words, in two. But it
#: takes about three times as long for each level of brackets nested in brackets, thirteen
#: seconds at ten deep, and the first version waited without limit: `check`, which had never
#: waited on another program, did not come back on a line of brackets, at a session's start
#: as before a build. Past the limit pandoc is stopped and the document is not judged here.
READ_SECONDS = 10.0


def _note(message: str, hint: str | None = None) -> Finding:
    return Finding(gate=GATE, code=NOT_JUDGED, severity=INFO, message=message, hint=hint)


def findings_of(
    lost: list[str] | tuple[str, ...],
    layout: list[str] | tuple[str, ...],
    read: list[tuple[str, str]],
    built: list[str],
    files: list[Path | None],
) -> list[Finding]:
    """What `check` says of the TeX pandoc read in one document: a failure for each kind
    that loses something, in the build's sentence and at the line it names, and the
    build's warning for each layout command.

    Two pieces that read the same are looked up at one place, the first, so they are one
    finding that counts the other. The kinds named are as many as the warning names: each
    is looked for through every source."""
    kinds = kinds_of(lost)
    findings = []
    for piece, times in list(kinds.items())[:_KINDS_NAMED]:
        more = f", and {times - 1} more like it" if times > 1 else ""
        said, remedy = reading.tex_said(piece, read, built, more)
        found = reading.located(piece, read, built)
        path, line = (None, None) if found is None else (files[found[0]], found[1])
        findings.append(
            Finding(
                gate=GATE,
                code=CODE,
                message=f"pandoc reads {said}",
                path=path,
                line=line,
                hint=remedy,
            )
        )
    if len(kinds) > _KINDS_NAMED:
        findings.append(
            Finding(
                gate=GATE,
                code=CODE,
                # It has no file, so a report puts it before the twenty: it points at
                # nothing above it.
                message=(
                    f"pandoc reads {len(kinds) - _KINDS_NAMED} more kinds of TeX in the "
                    "text than the twenty named, and the Word writer leaves each out of the "
                    "document"
                ),
                hint="each is named once the twenty that are named are put right",
            )
        )
    return [*findings, *does_nothing(layout, read, built, files=files).findings]


def _document(project, ordered: list, pandoc: str, *, supplementary: bool) -> Report:
    """One document's TeX, from one run of pandoc on the text the build would hand it."""
    which = "the supplement" if supplementary else "the manuscript"
    try:
        # As the build of a document that was sent writes it: TeX in the title and a
        # letter an escape takes are findings of their own and stop nothing here.
        header = _front_matter(project, supplementary=supplementary, sent=True)
    except (BuildError, ContractError):
        # A title no document can carry, which `check` reports. The text is read under
        # no header.
        header = ""
    read, built = as_read(ordered)
    try:
        found = reading.tex_read(header + document_text(ordered), pandoc, READ_SECONDS)
    except subprocess.TimeoutExpired:
        return Report(
            (
                _note(
                    f"pandoc had not read {which} after {READ_SECONDS:g} s, so TeX in it is "
                    "not judged here: the build judges it, and waits for pandoc as long as "
                    "it takes"
                ),
            )
        )
    except (OSError, ValueError) as error:
        # A file named pandoc that the system cannot run, or an answer that is no JSON. It
        # was `gate-errored`, which fails at every stage and calls itself a bug, where no
        # pandoc at all is a note.
        return Report(
            (
                _note(
                    f"pandoc could not be run on {which}, or its answer could not be read "
                    f"({type(error).__name__}: {error}), so TeX in it is not judged here: "
                    "the build needs pandoc too"
                ),
            )
        )
    except RecursionError:
        # Python's JSON reader recurses, and two thousand nested divs overflow it. The
        # build refuses such a document, whatever it holds.
        return Report(
            (
                _note(
                    f"{which} is nested too deep for pandoc's reading of it to be walked, so "
                    "TeX in it is not judged here: the build refuses a document nested so deep"
                ),
            )
        )
    if found is None:
        return Report(
            (
                _note(
                    f"pandoc could not read {which}, so TeX in it is not judged here: the "
                    "build says what pandoc says of it"
                ),
            )
        )
    lost, layout = found
    files = [None, *(a.path for a in ordered), None]
    return Report(tuple(findings_of(lost, layout, read, built, files)), {READ: 1})


def check_tex(project, namespace, results) -> Report:
    """TeX in the text that the build would refuse, and the layout commands it would warn
    of, for the paper and for its supplement: `findings_of` each.

    Pandoc is run once for each of the two documents, not once for each file: a file is
    read as the build reads it, in its document, where a macro defined in one file is
    applied in the next."""
    pandoc = shutil.which("pandoc")
    if pandoc is None:
        return Report(
            (
                _note(
                    "pandoc is not on PATH, so TeX in the text is not judged here: the "
                    "build judges it",
                    hint=(
                        "pandoc reads a backslash before a letter outside maths as TeX, and "
                        "the Word writer leaves it out; `check` asks pandoc where it is "
                        "installed (https://pandoc.org/installing.html)"
                    ),
                ),
            ),
            {READ: 0},
        )
    assembled, _report = assemble(project, namespace, results)
    report = Report(counts={READ: 0})
    for supplementary in (False, True):
        try:
            ordered = document_files(project, assembled, supplementary=supplementary)
        except BuildError:
            # No `main.md`, or no supplement: no document, and nothing to read.
            continue
        report = report.merge(_document(project, ordered, pandoc, supplementary=supplementary))
    return report
