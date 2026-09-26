"""Producing the .docx.

Two modes, and the choice is not a preference but a fact about the machine:

**live** — pandoc with Better BibTeX's `zotero.lua`, which queries the running Zotero and
writes real `ADDIN ZOTERO_ITEM CSL_CITATION` fields. Word's Zotero plugin adopts them, so
the author can add citations by hand afterwards and refresh the bibliography. Requires
Zotero to be open.

**offline** — pandoc with `--citeproc` against the committed `references.bib` and a CSL
style. Citations are formatted text rather than live fields. This is what CI and a
co-author without Zotero get.

The document is regenerated from Markdown every time, which is the whole reason numbers
cannot go stale: nothing is ever carried across by hand, so there is nothing to forget.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import WARN, Finding, Report

GATE = "BUILD"

# Pinned to an immutable commit and verified by content hash.
#
# pandoc executes a lua filter with os and io available, so this file is code running on the
# author's machine. Fetching it from a mutable branch means whatever that branch holds on the
# day of the build. The rest of this toolkit already refuses to use a downloaded document
# that does not match a recorded hash — see reporting/fetch.py — and there is no reason the
# one download that is *executed* should be the exception.
#
# To move to a newer filter: change both constants together, having read the diff.
LUA_COMMIT = "736265327bf5673d495730a3884dafe84f450788"
LUA_URL = (
    f"https://raw.githubusercontent.com/retorquere/zotero-better-bibtex/{LUA_COMMIT}/"
    "site/content/exporting/zotero.lua"
)
LUA_SHA256 = "a9ccec3de37954ad3b66c67c2d05e41a4c7ad3a99a4cfd99e184cebb822faf02"
LUA_MAX_BYTES = 2 * 1024 * 1024

LIVE = "live"
OFFLINE = "offline"

# Ours, shipped with the package, run after zotero.lua on a live build: the bibliography
# field and document preferences Word's Zotero plugin needs, which zotero.lua writes for
# LibreOffice only. See the file's header.
ZOTERO_WORD_LUA = Path(__file__).with_name("zotero_word.lua")
ZOTERO_STYLES = "http://www.zotero.org/styles/"


class BuildError(Exception):
    """The document could not be produced."""


@dataclass(frozen=True)
class BuildResult:
    output: Path
    mode: str
    report: Report


def pandoc() -> str:
    found = shutil.which("pandoc")
    if not found:
        raise BuildError("pandoc is not on PATH; see https://pandoc.org/installing.html")
    return found


def abbreviations() -> frozenset[str]:
    """The words pandoc's smart typesetting puts a no-break space after, as a build reads them.

    `import` writes that space back into the source as the plain one pandoc makes it of
    again, so it needs the list pandoc really uses: the one in pandoc's user data directory
    when there is one, which pandoc reads instead of its own, and pandoc's default otherwise.
    Taken from the default alone, a no-break space typed after a word the user's pandoc does
    not treat as an abbreviation would come back plain. The build passes no `--data-dir`; if
    it ever does, this must read that directory too.
    """
    found = re.search(r"^User data directory:\s*(.+?)\s*$", _pandoc_says("--version"), re.M)
    own = Path(found.group(1)) / "abbreviations" if found else None
    if own is not None and own.is_file():
        # Bytes, not text: read as text, a lone carriage return already ended a line.
        text = own.read_bytes().decode("utf-8")
    else:
        text = _pandoc_says("--print-default-data-file", "abbreviations")
    # As pandoc reads it: the byte-order mark and carriage returns dropped, and each line an
    # abbreviation exactly as written. Stripped, `e.g. ` with a stray space was on the list
    # here and not to pandoc, and a no-break space typed after "e.g." was written back plain.
    lines = text.removeprefix("\ufeff").replace("\r", "").split("\n")
    return frozenset(line for line in lines if line)


def _pandoc_says(*args: str) -> str:
    """What pandoc prints for `args`."""
    finished = subprocess.run(
        [pandoc(), *args], capture_output=True, text=True, encoding="utf-8"
    )
    if finished.returncode != 0:
        raise BuildError(f"pandoc {' '.join(args)} failed:\n{finished.stderr.strip()}")
    return finished.stdout


def relative_to_root(project, path: Path) -> str:
    """`path` as pandoc should see it when run from the project root: relative, if it can be.

    Relative because pandoc writes some of what it is given into the document, and a path
    that names the builder's home directory is not something to send to co-authors. Falls
    back to the absolute path for a file on another drive, which has no relative form.
    """
    try:
        return Path(os.path.relpath(path.resolve(), project.root.resolve())).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def ensure_zotero_lua(cache_dir: Path) -> Path:
    """Fetch and cache Better BibTeX's pandoc filter.

    Not vendored: it belongs to Better BibTeX and tracks its behaviour, so pinning a copy
    here would mean shipping a stale one. Cached under build/, which is gitignored.
    """
    import hashlib

    path = cache_dir / "zotero.lua"
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == LUA_SHA256:
        return path

    cache_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"manuscript-guard: downloading Better BibTeX's pandoc filter from\n"
        f"  {LUA_URL}\n"
        f"  pandoc executes this file. It is pinned to a commit and verified against a "
        f"recorded hash.",
    )
    try:
        request = urllib.request.Request(LUA_URL, headers={"User-Agent": "manuscript-guard"})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(LUA_MAX_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise BuildError(
            f"could not fetch zotero.lua ({exc}). Build with --offline, or place the file "
            f"at {path}"
        ) from exc

    if len(data) > LUA_MAX_BYTES:
        raise BuildError(f"{LUA_URL} returned more than {LUA_MAX_BYTES // 1024} KB; refusing")

    digest = hashlib.sha256(data).hexdigest()
    if digest != LUA_SHA256:
        raise BuildError(
            f"zotero.lua does not match its recorded hash.\n"
            f"  expected {LUA_SHA256}\n  got      {digest}\n"
            f"pandoc executes this file, so it is not run unverified. If Better BibTeX has "
            f"published a new filter, read the diff and update LUA_COMMIT and LUA_SHA256 "
            f"together."
        )
    path.write_bytes(data)
    return path


def _zotero_style(project) -> str | None:
    """The Zotero style id for the target journal's citation style, if its profile names one.

    A journal profile records `references: {csl: apa}`; Zotero identifies the same style as
    http://www.zotero.org/styles/apa. A full URL in the profile is used as it is.
    """
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.journal import profile_path

    slug = project.target_journal
    path = profile_path(project, slug) if slug else None
    if path is None:
        return None
    with contextlib.suppress(Exception):
        document = read_structured(path)
        csl = str(((document or {}).get("references") or {}).get("csl") or "").strip()
        if csl:
            return csl if csl.startswith("http") else ZOTERO_STYLES + csl
    return None


def _zotero_version() -> str | None:
    """The running Zotero's version, as Better BibTeX reports it; None if it does not answer."""
    from manuscript_guard.zotero import ZoteroUnavailable, rpc

    with contextlib.suppress(ZoteroUnavailable, AttributeError, TypeError):
        ready = rpc("api.ready", [], timeout=5)
        return str(ready.get("zotero")) if isinstance(ready, dict) and ready.get("zotero") else None
    return None


def _word_lines(project) -> list[str]:
    """The `zotero-word` block zotero_word.lua reads: the style and locale Word should use."""
    style = _zotero_style(project)
    if style is None:
        return []
    locale = "en-GB" if project.english_variant == "en-GB" else "en-US"
    lines = ["zotero-word:", f'  style: "{style}"', f"  locale: {locale}"]
    version = _zotero_version()
    if version:
        lines.append(f'  zotero-version: "{version}"')
    return lines


def _front_matter(project, *, supplementary: bool = False, live: bool = False) -> str:
    """A YAML header carrying the title and the Zotero settings the filter reads."""
    paper = project.paper
    title = str(paper.get("title", "")).replace(chr(34), chr(39))
    if supplementary:
        title = f"Supplementary material for: {title}"
    lines = ["---", f'title: "{title}"']
    # The short title and keywords belong to the paper. A supplement carrying the paper's
    # running head reads, in a journal's system, as a second copy of the paper.
    short = None if supplementary else paper.get("short_title")
    if short:
        lines.append(f'subtitle: "{short}"')
    keywords = None if supplementary else paper.get("keywords")
    if keywords:
        lines.append("keywords: [" + ", ".join(f'"{k}"' for k in keywords) + "]")
    lines += [
        "lang: " + ("en-GB" if project.english_variant == "en-GB" else "en-US"),
        "zotero:",
        "  client: zotero",
        "  scannable-cite: false",
        "  author-in-text: true",
    ]
    if live:
        lines += _word_lines(project)
    lines += ["---", ""]
    return "\n".join(lines)


def build_document(
    project,
    assembled,
    *,
    mode: str = LIVE,
    csl: Path | None = None,
    output: Path | None = None,
    reference_doc: Path | None = None,
    prologue: str = "",
    epilogue: str = "",
    supplementary: bool = False,
) -> BuildResult:
    from manuscript_guard.gates.numbers import SUPPLEMENTARY, is_supplementary

    build_dir = project.path("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    output = output or build_dir / (f"{SUPPLEMENTARY}.docx" if supplementary else "manuscript.docx")
    # Named after its output, so the annotated build does not overwrite the intermediate
    # the ordinary one just wrote - two builds, two sources, and either can be read after.
    source = build_dir / f"{output.stem}.md"

    # The supplement is a separate document, never appended to the paper. Welded in, it
    # counted against the journal's word limit, arrived as pages the editor had to find the
    # end of, and could not be uploaded to the "supplementary material" slot every
    # submission system has.
    manuscript_dir = project.path("manuscript")
    wanted = [a for a in assembled if is_supplementary(manuscript_dir, a.path) == supplementary]

    if supplementary:
        if not wanted:
            raise BuildError(f"nothing under manuscript/{SUPPLEMENTARY}/ to build")
        ordered = sorted(wanted, key=lambda a: a.path.name)
    else:
        main = [a for a in wanted if a.path.name == "main.md"]
        if not main:
            raise BuildError("no manuscript/main.md to build")
        ordered = main + sorted(
            (a for a in wanted if a.path.name != "main.md"), key=lambda a: a.path.name
        )

    # An empty div between two files, which puts nothing in the document, so each file
    # starts afresh. Joined by blank lines alone, a footnote ending one file took in the next
    # file's first paragraph when that opened indented, identifier and all: `tag` judges a
    # note by the end of its own file, where nothing follows. Not a comment: its `-->` closed
    # a `<!--` left open earlier in the file, and the rest of that file vanished.
    body = prologue + "\n\n::: {}\n:::\n\n".join(a.text for a in ordered) + epilogue
    source.write_text(
        _front_matter(project, supplementary=supplementary, live=mode == LIVE) + body,
        encoding="utf-8",
        newline="\n",
    )
    from manuscript_guard.zotero import find_citations

    cites = bool(find_citations(body, source))

    # Pandoc runs from the project root and is given paths relative to it wherever it may
    # write them into the document. The document goes to co-authors, and it used to carry
    # the builder's home directory twice: `--bibliography` is metadata, which the Word writer
    # stores as a document property, and a figure linked by absolute path is recorded as the
    # picture's description. Everything else it is handed is made absolute, so the change of
    # directory cannot make a relative argument mean a different file.
    root = project.root.resolve()
    command = [pandoc(), "--standalone", str(source.resolve()), "-o", str(output.resolve())]
    if reference_doc is not None:
        command += [f"--reference-doc={reference_doc.resolve()}"]
    report = Report()

    if mode == LIVE:
        command += [f"--lua-filter={ensure_zotero_lua(build_dir / '.cache').resolve()}"]
        # A document with no citations gets no bibliography field (a supplement of tables).
        if cites:
            command += [f"--lua-filter={ZOTERO_WORD_LUA.resolve()}"]
    else:
        bib = project.path("literature") / "references.bib"
        if not bib.exists():
            raise BuildError(
                f"{bib} does not exist; run `manuscript-guard sync-bib` with Zotero open"
            )
        command += ["--citeproc", f"--bibliography={relative_to_root(project, bib)}"]
        if csl is not None:
            command += [f"--csl={relative_to_root(project, csl.resolve())}"]

    finished = subprocess.run(command, capture_output=True, text=True, cwd=root)
    if finished.returncode != 0:
        raise BuildError(f"pandoc failed:\n{finished.stderr.strip()}")
    if finished.stderr.strip():
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="pandoc-warning",
                severity=WARN,
                message=finished.stderr.strip()[:400],
                path=output,
            )
        )
    # A document that cites nothing has no fields to find, and warning that its citations
    # will be plain text only taught the author to ignore the warning.
    if mode == LIVE and cites:
        report = report.merge(_verify_live_fields(output))
    # Not the annotated copy: the stamp is what `check` reads to decide whether the
    # document a co-author opens is current, and there must be exactly one such document.
    if reference_doc is None:
        _stamp_source(project, output)
        # And inside the file, where it can survive being emailed. The sidecar answers
        # "is my build current"; this answers "which text were these edits made against",
        # which is the question the moment a co-author sends the document back.
        with contextlib.suppress(Exception):
            from manuscript_guard.gates.review import document_digest
            from manuscript_guard.roundtrip import stamp_into

            stamp_into(output, document_digest(project))
    return BuildResult(output=output, mode=mode, report=report)


SOURCE_STAMP = ".source.sha256"


def _stamp_source(project, output: Path) -> None:
    """Record which manuscript this document was built from.

    Nothing linked the two, so a `build/manuscript.docx` sitting beside changed sources was
    not reported by anything: edit the manuscript, do not rebuild, and `check` passes over a
    document that still holds the old number. It is the .docx a co-author opens and a
    journal receives, which makes it the worst file in the project to leave unexamined.

    `document_digest`, not `manuscript_digest`: the numbers in the document come from
    `results/`, so a re-run analysis with untouched prose is the commoner way for a build to
    go stale, and the first version of this check could not see it at all.
    """
    from manuscript_guard.gates.review import document_digest

    # Written to a neighbour and renamed into place. `write_text` truncates first, so a
    # build interrupted between the truncate and the write left an empty stamp beside a
    # perfectly good document — and an empty stamp reads as a digest of "", which does not
    # match, so the next `check` reports the document stale and the author rebuilds a
    # document that was never wrong. `os.replace` is atomic on both platforms.
    #
    # A build that produced the document must not fail over its receipt.
    stamp = output.with_name(output.name + SOURCE_STAMP)
    with contextlib.suppress(OSError):
        pending = stamp.with_name(stamp.name + ".tmp")
        pending.write_text(
            f"{document_digest(project)}  {output.name}\n", encoding="utf-8", newline="\n"
        )
        os.replace(pending, stamp)


def _verify_live_fields(docx: Path) -> Report:
    """Confirm the citations really are Zotero fields, not text that looks like them.

    Worth checking rather than assuming: the filter fails quietly when Zotero is closed,
    and the resulting document looks fine until someone clicks Refresh in Word and every
    citation disappears.
    """
    import zipfile

    try:
        xml = zipfile.ZipFile(docx).read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return Report(
            (
                Finding(
                    gate=GATE,
                    code="docx-unreadable",
                    message=f"could not inspect the built document: {exc}",
                    path=docx,
                ),
            )
        )

    fields = xml.count("ZOTERO_ITEM")
    if fields:
        return Report(counts={"zotero_fields": fields})
    return Report(
        (
            Finding(
                gate=GATE,
                code="no-live-citations",
                severity=WARN,
                message="the document has no Zotero fields; citations will be plain text",
                path=docx,
                hint="open Zotero and rebuild, or build with --offline deliberately",
            ),
        ),
        counts={"zotero_fields": 0},
    )
