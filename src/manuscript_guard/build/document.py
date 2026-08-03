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

import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.findings import WARN, Finding, Report

GATE = "BUILD"

LUA_URL = (
    "https://raw.githubusercontent.com/retorquere/zotero-better-bibtex/master/"
    "site/content/exporting/zotero.lua"
)

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
    path = cache_dir / "zotero.lua"
    if path.exists() and path.stat().st_size > 1000:
        return path
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(LUA_URL, timeout=60) as response:
            data = response.read()
    except (urllib.error.URLError, OSError) as exc:
        raise BuildError(
            f"could not fetch zotero.lua ({exc}). Build with --offline, or place the file "
            f"at {path}"
        ) from exc
    if b"function" not in data:
        raise BuildError(f"what came back from {LUA_URL} is not a lua filter")
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
    return BuildResult(output=output, mode=mode, report=report)


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
