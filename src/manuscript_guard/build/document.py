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


def _front_matter(project) -> str:
    """A YAML header carrying the title and the Zotero settings the filter reads."""
    paper = project.paper
    lines = ["---", f'title: "{paper.get("title", "").replace(chr(34), chr(39))}"']
    short = paper.get("short_title")
    if short:
        lines.append(f'subtitle: "{short}"')
    keywords = paper.get("keywords")
    if keywords:
        lines.append("keywords: [" + ", ".join(f'"{k}"' for k in keywords) + "]")
    lines += [
        "lang: " + ("en-GB" if project.english_variant == "en-GB" else "en-US"),
        "zotero:",
        "  client: zotero",
        "  scannable-cite: false",
        "  author-in-text: true",
        "---",
        "",
    ]
    return "\n".join(lines)


def build_document(
    project,
    assembled,
    *,
    mode: str = LIVE,
    csl: Path | None = None,
    output: Path | None = None,
) -> BuildResult:
    build_dir = project.path("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    source = build_dir / "manuscript.md"

    main = [a for a in assembled if a.path.name == "main.md"]
    rest = sorted((a for a in assembled if a.path.name != "main.md"), key=lambda a: a.path.name)
    if not main:
        raise BuildError("no manuscript/main.md to build")
    body = "\n\n".join(a.text for a in main + rest)
    source.write_text(
        _front_matter(project) + body, encoding="utf-8", newline="\n"
    )

    output = output or build_dir / "manuscript.docx"
    command = [pandoc(), "--standalone", str(source), "-o", str(output)]
    report = Report()

    if mode == LIVE:
        command += [f"--lua-filter={ensure_zotero_lua(build_dir / '.cache')}"]
    else:
        bib = project.path("literature") / "references.bib"
        if not bib.exists():
            raise BuildError(
                f"{bib} does not exist; run `manuscript-guard sync-bib` with Zotero open"
            )
        command += ["--citeproc", f"--bibliography={bib}"]
        if csl is not None:
            command += [f"--csl={csl}"]

    finished = subprocess.run(command, capture_output=True, text=True)
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
    if mode == LIVE:
        report = report.merge(_verify_live_fields(output))
    _stamp_source(project, output)
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

    # A build that produced the document must not fail over its receipt.
    with contextlib.suppress(OSError):
        output.with_name(output.name + SOURCE_STAMP).write_text(
            f"{document_digest(project)}  {output.name}\n", encoding="utf-8", newline="\n"
        )


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
