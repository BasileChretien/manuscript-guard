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
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.build.styles import reference_with
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import (
    KEEP_THE_LETTER,
    KEEP_THE_TEX,
    PAPER_FILE,
    advice,
    lost_letters,
    named,
    one_line,
    outside_maths,
    unprintable_character,
)
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

# Also ours, run on every docx build: the paragraph after a figure is styled as its caption,
# so a reader can see where the caption ends. See the file's header and `build/styles.py`.
FIGURE_CAPTION_LUA = Path(__file__).with_name("figure_caption.lua")
ZOTERO_STYLES = "http://www.zotero.org/styles/"


class BuildError(Exception):
    """The document could not be produced."""


class MisreadError(BuildError):
    """Pandoc reads the document otherwise than the gates read its sources, so it is not
    made: see `reading.misreading`."""


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


#: A page break for a Word document, as a code span in a paragraph of its own: what the
#: warning about a layout command says to write. A code span and not a block: G2 fails a
#: raw block from `drafting` on, and the paragraph around the span is the one Word needs.
_PAGE_BREAK = '`<w:r><w:br w:type="page"/></w:r>`{=openxml}'
#: How many kinds of layout command are each warned of. Each is looked for in the text, so
#: without a limit the warnings took time with the square of their number.
_KINDS_NAMED = 20


def kinds_of(pieces: list[str] | tuple[str, ...]) -> dict[str, int]:
    """Each piece of TeX that reads the same, in the order pandoc read the first of each,
    with how many there are of it."""
    kinds: dict[str, int] = {}
    for raw in pieces:
        kinds[raw.strip()] = kinds.get(raw.strip(), 0) + 1
    return kinds


def does_nothing(
    inert: list[str] | tuple[str, ...],
    read: list[tuple[str, str]],
    built: list[str],
    output: Path | None = None,
    *,
    files: list[Path | None] | None = None,
) -> Report:
    """A warning for each layout command pandoc reads as TeX in the text, with where the
    first of its kind stands (`reading.misreading` fills `inert`).

    `\\newpage` loses no word, so the document is made, and a manuscript that held one
    before TeX in the text was refused still builds. But Word shows nothing for it, marked
    `{=latex}` or not, and an author who typed it for a page break has none.

    The build puts each warning at the document it made, `output`. `check` makes none, and
    gives `files`, the file of each of `read`: the same warning is then put at the file
    and the line it names."""
    from manuscript_guard.build.reading import located, place

    kinds = kinds_of(inert)
    hint = (
        f"for a page break in Word, write {_PAGE_BREAK} in a paragraph of its own; a command "
        "that is there for a PDF made elsewhere can stand in a code span marked `{=latex}`, "
        "and is then not warned of"
    )
    findings = []
    for raw, times in list(kinds.items())[:_KINDS_NAMED]:
        path, line = output, None
        if files is not None:
            found = located(raw, read, built)
            path, line = (None, None) if found is None else (files[found[0]], found[1])
        findings.append(
            Finding(
                gate=GATE,
                code="tex-does-nothing",
                severity=WARN,
                message=(
                    f"`{' '.join(raw.split())}`{place(raw, read, built)} does nothing in a "
                    "Word document" + (f", nor do {times - 1} more like it" if times > 1 else "")
                ),
                path=path,
                line=line,
                hint=hint,
            )
        )
    if len(kinds) > _KINDS_NAMED:
        findings.append(
            Finding(
                gate=GATE,
                code="tex-does-nothing",
                severity=WARN,
                message=(
                    f"{len(kinds) - _KINDS_NAMED} more kinds of layout command do nothing in "
                    "a Word document either"
                ),
                path=output,
                hint=hint,
            )
        )
    return Report(tuple(findings))


#: What stands between two files of a document. An empty div, which puts nothing in the
#: document, so each file starts afresh. Joined by blank lines alone, a footnote ending one
#: file took in the next file's first paragraph when that opened indented, identifier and
#: all: `tag` judges a note by the end of its own file, where nothing follows. Not a
#: comment: its `-->` closed a `<!--` left open earlier in the file, and the rest of that
#: file vanished.
_BETWEEN_FILES = "\n\n::: {}\n:::\n\n"


def document_files(project, assembled, *, supplementary: bool = False) -> list:
    """The files of one document, the paper or its supplement, in the order they are
    printed. `BuildError` where there is nothing to make that document of.

    The supplement is a separate document, never appended to the paper. Welded in, it
    counted against the journal's word limit, arrived as pages the editor had to find the
    end of, and could not be uploaded to the "supplementary material" slot every
    submission system has."""
    from manuscript_guard.gates.numbers import SUPPLEMENTARY, is_supplementary, printed_order

    manuscript_dir = project.path("manuscript")
    wanted = [a for a in assembled if is_supplementary(manuscript_dir, a.path) == supplementary]
    if supplementary and not wanted:
        raise BuildError(f"nothing under manuscript/{SUPPLEMENTARY}/ to build")
    if not supplementary and not any(a.path.name == "main.md" for a in wanted):
        raise BuildError("no manuscript/main.md to build")
    by_path = {a.path: a for a in wanted}
    return [
        by_path[path]
        for path in printed_order([a.path for a in wanted], supplementary=supplementary)
    ]


def document_text(ordered: list, prologue: str = "", epilogue: str = "") -> str:
    """The text of a document under its header: its files, each starting afresh."""
    return prologue + _BETWEEN_FILES.join(a.text for a in ordered) + epilogue


def as_read(
    ordered: list, prologue: str = "", epilogue: str = ""
) -> tuple[list[tuple[str, str]], list[str]]:
    """What a reading of a document is compared with and looked up in: each part's name
    and its text as it is on disk, and each part's text as built, in the same order."""
    read = [
        ("the build's prologue", prologue),
        *((a.path.name, read_text(a.path)) for a in ordered),
        ("the build's epilogue", epilogue),
    ]
    return read, [prologue, *(a.text for a in ordered), epilogue]


def abbreviations() -> frozenset[str]:
    """The words pandoc's smart typesetting puts a no-break space after, as a build reads them.

    `import` writes that space back into the source as the plain one pandoc makes it of
    again, so it needs the list pandoc really uses: the one in pandoc's user data directory
    when there is one, which pandoc reads instead of its own, and pandoc's default otherwise.
    Taken from the default alone, a no-break space typed after a word the user's pandoc does
    not treat as an abbreviation would come back plain. The build passes no `--data-dir`; if
    it ever does, this must read that directory too.
    """
    directory = user_data_dir()
    own = directory / "abbreviations" if directory is not None else None
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


def user_data_dir(exe: str | None = None) -> Path | None:
    """Pandoc's user data directory, as pandoc itself reports it.

    Asking pandoc is what makes this right on every platform and under XDG_DATA_HOME, and
    `_pandoc_says` reads the answer as UTF-8, which is what pandoc prints: read through the
    console code page instead, a Windows account named Zoë comes back as ZoÃ« and the
    directory is silently not found. The build passes no `--data-dir`; if it ever does, this
    must read that directory too.
    """
    printed = _pandoc_says("--version", exe=exe)
    found = re.search(r"^User data directory:\s*(.+?)\s*$", printed, re.M)
    return Path(found.group(1)) if found else None


def _pandoc_says(*args: str, exe: str | None = None) -> str:
    """What pandoc prints for `args`."""
    finished = subprocess.run(
        [exe or pandoc(), *args], capture_output=True, text=True, encoding="utf-8"
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


def _yaml_text(project, key: str, value: object, *, sent: bool = False) -> str:
    """`value` on one line, as a double-quoted YAML string that pandoc reads back as the
    same text.

    The title, the short title and the keywords were written between double quotation marks
    by hand. A `"` in one ended the string, and pandoc refused the header; a backslash began
    an escape, so `$\\alpha$` became the control character 7 and the document carried it in
    its properties, which Word will not open. A valid `paper.yaml` passed `check` and built
    that document. JSON's escapes are YAML's.

    The lines are folded into one first, as YAML folded them between hand-written quotation
    marks: a title holding a blank line was two paragraphs to pandoc, and the Word writer
    left it out. Only what YAML reads as the end of a line is folded (`one_line`), and the
    tab is kept. Any other control character is refused, as pandoc refused it before: one
    comes from an escape in `paper.yaml` itself, `"\\alpha"` between double quotation marks,
    and written as JSON's escape it reached the document. So are a surrogate and the two
    code points that are no character, which an escape makes too (`named`): a surrogate
    cannot be written as UTF-8, and the build ended in a traceback. `check` reports each
    first.

    TeX the document would be printed without is refused too (`outside_maths`): pandoc
    reads the value as Markdown and the Word writer keeps TeX only as maths, so
    `IFN-\\gamma release assays` was printed `IFN-release assays`. Not where the
    document was `sent` already: see `build_document`.
    """
    text = one_line(str(value))
    character = unprintable_character(text)
    if character is not None:
        raise BuildError(
            f"{project.root / PAPER_FILE}: `{key}` holds {named(character)}, which no "
            f"document can carry: {advice(character)}."
        )
    said = None if sent else outside_maths(text, keyword=key == "keywords")
    if said is not None:
        raise BuildError(f"{project.root / PAPER_FILE}: `{key}`: {said}. Note that {KEEP_THE_TEX}.")
    return json.dumps(text, ensure_ascii=False)


def _front_matter(
    project, *, supplementary: bool = False, live: bool = False, sent: bool = False
) -> str:
    """A YAML header carrying the title and the Zotero settings the filter reads.

    What the author wrote is read by pandoc as Markdown, as the text is: `*E. coli*` is in
    italics, and TeX outside `$` would be left out, which is why it is refused (`_yaml_text`).

    `sent` is for a document that was built already and is built again to be compared with:
    see `build_document`.
    """
    paper = project.paper
    # What `check` reports and a build that skips the check would print: an escape in
    # `paper.yaml` that takes the first letter of a word. What YAML made of it is a line
    # break like any other, so it is looked for in the file.
    lost = [] if sent else lost_letters(project.root / PAPER_FILE)
    if lost:
        first = lost[0]
        raise BuildError(
            f"{project.root / PAPER_FILE}: `{first.where}`, line {first.line}: {first.said}. "
            f"To keep the letter, {KEEP_THE_LETTER}."
        )
    title = str(paper.get("title", ""))
    if supplementary:
        title = f"Supplementary material for: {title}"
    lines = ["---", f"title: {_yaml_text(project, 'title', title, sent=sent)}"]
    # The short title and keywords belong to the paper. A supplement carrying the paper's
    # running head reads, in a journal's system, as a second copy of the paper.
    short = None if supplementary else paper.get("short_title")
    if short:
        lines.append(f"subtitle: {_yaml_text(project, 'short_title', short, sent=sent)}")
    # `keywords: 5` raised here under `--skip-checks`, and one word where a list is expected
    # was printed letter by letter; see `Project.keywords`.
    keywords = None if supplementary else project.keywords
    if keywords:
        printed = ", ".join(_yaml_text(project, "keywords", k, sent=sent) for k in keywords)
        lines.append(f"keywords: [{printed}]")
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


@contextlib.contextmanager
def _reference(build_dir: Path, given: Path | None) -> Iterator[Path]:
    """The reference document this build hands pandoc, and its removal if this build made it.

    A generated one is this build's own file, named by `mkstemp`: one shared name meant two
    builds of a project at once - or a build and an `import`, which builds twice - truncated
    the file the other was reading, or deleted it under it.

    It is removed from the moment it exists, not from the pandoc call onwards, because what
    comes between can fail: `reference_with` on an author's `reference.docx` that is not a
    .docx, and the offline branch on a missing bibliography. A process killed outright cannot
    clean up after itself, and that is in DESIGN.md's Known gaps rather than fixed by deleting
    files this build does not own.
    """
    if given is not None:
        yield given
        return
    cache = build_dir / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    handle, named = tempfile.mkstemp(prefix="reference-", suffix=".docx", dir=cache)
    os.close(handle)
    made = Path(named)
    try:
        yield reference_with(pandoc(), made)
    finally:
        # Suppressed, because a removal that fails must not become the build's error: a file
        # held for an instant by a scanner or a sync client raised PermissionError out of this
        # `finally`, which replaced the sentence the build was already failing with, and after
        # a successful pandoc run it left the document built but unstamped and unrecorded. A
        # file that cannot be removed is left behind instead, as Known gaps says.
        with contextlib.suppress(OSError):
            made.unlink(missing_ok=True)


def build_document(
    project,
    assembled,
    *,
    mode: str = LIVE,
    csl: Path | None = None,
    output: Path | None = None,
    reference_doc: Path | None = None,
    stamp: bool = True,
    prologue: str = "",
    epilogue: str = "",
    supplementary: bool = False,
    verify_reading: bool = True,
    sent: bool = False,
) -> BuildResult:
    """Make the document.

    `sent` is for `import`, which builds again a document that was sent, to compare the one
    that came back with it. A refusal newer than that document is not made: the header is
    written as the sent one's was, an escape that takes a letter and TeX outside dollar
    signs included, since refusing there kept back a document a co-author was holding.
    `check` and the next build still refuse it.

    `stamp` writes the record of which text the document was built from, and there must be
    exactly one document carrying it: the annotated copy passes `stamp=False`.

    `verify_reading` asks pandoc first whether it reads the sources
    as the gates do (`reading.misreading`), and whether it reads TeX in the text that the
    Word writer would leave out, which is refused, or TeX that is only layout, which is
    warned of. Two builds go without: `import`, rebuilding a
    document already sent in order to compare the returned one with it, since refusing
    there stranded a document a co-author was holding; and the annotated copy, which is for
    the author to read, not to send, and whose marks `annotate` has pandoc check as it
    makes them."""
    from manuscript_guard.gates.numbers import SUPPLEMENTARY

    build_dir = project.path("build")
    build_dir.mkdir(parents=True, exist_ok=True)
    output = output or build_dir / (f"{SUPPLEMENTARY}.docx" if supplementary else "manuscript.docx")
    # Named after its output, so the annotated build does not overwrite the intermediate
    # the ordinary one just wrote - two builds, two sources, and either can be read after.
    source = build_dir / f"{output.stem}.md"

    ordered = document_files(project, assembled, supplementary=supplementary)
    body = document_text(ordered, prologue, epilogue)
    header = _front_matter(
        project, supplementary=supplementary, live=mode == LIVE, sent=sent
    )
    source.write_text(header + body, encoding="utf-8", newline="\n")
    from manuscript_guard.zotero import find_citations

    cites = bool(find_citations(body, source))

    # Pandoc runs from the project root and is given paths relative to it wherever it may
    # write them into the document. The document goes to co-authors, and it used to carry
    # the builder's home directory twice: `--bibliography` is metadata, which the Word writer
    # stores as a document property, and a figure linked by absolute path is recorded as the
    # picture's description. Everything else it is handed is made absolute, so the change of
    # directory cannot make a relative argument mean a different file.
    root = project.root.resolve()

    from manuscript_guard.build.reading import TexLeftOut, misreading

    read, built = as_read(ordered, prologue, epilogue)
    inert: list[str] = []
    differs = (
        misreading(header + body, header, read, pandoc(), root, built=built, inert=inert)
        if verify_reading
        else None
    )
    if differs is not None:
        # The document from the last build is not this source's, and left in build/ it is
        # the one a co-author would be sent, or `submit` would pack.
        if output.resolve().is_relative_to(build_dir.resolve()):
            for stale in (output, output.with_name(output.name + SOURCE_STAMP)):
                if stale.is_file():
                    stale.unlink()
        if isinstance(differs, TexLeftOut):
            # The one misreading `check` asks pandoc about too (`tex_check`). The build
            # comes to it where the check was skipped, where the finding is not yet due, and
            # where pandoc took longer over the text than `check` waits: said without that
            # condition, the sentence was false of a text `check` had just passed.
            raise MisreadError(
                f"pandoc reads {differs}. The gates that read the sources counted it as "
                "printed, so the document is not built; `check` reports it too where "
                "pandoc reads the text in the time `check` gives it, and fails for it from "
                "`drafting` on."
            )
        raise MisreadError(
            f"pandoc reads {differs}. The gates judged the sources as they read them, so "
            "the document is not built; `check` cannot see this, and the build asks pandoc."
        )
    command = [pandoc(), "--standalone", str(source.resolve()), "-o", str(output.resolve())]
    with _reference(build_dir, reference_doc) as reference:
        command += [
            f"--reference-doc={reference.resolve()}",
            f"--lua-filter={FIGURE_CAPTION_LUA.resolve()}",
        ]
        report = does_nothing(inert, read, built, output)

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
    if stamp:
        _stamp_source(project, output)
        # And inside the file, where it can survive being emailed. The sidecar answers
        # "is my build current"; this answers "which text were these edits made against",
        # which is the question the moment a co-author sends the document back.
        # With what each paragraph identifier names, so an import can tell an identifier
        # that still names its paragraph from one that has come to name another. Only the
        # paragraphs this document carries, in its order: one of them that is missing when
        # the document comes back was deleted in Word, and a supplement's are elsewhere.
        with contextlib.suppress(Exception):
            from manuscript_guard.gates.review import document_digest
            from manuscript_guard.roundtrip import (
                RecordNotWritten,
                paragraph_order,
                paragraph_record,
                stamp_into,
                write_printed,
            )

            record = paragraph_record(project)
            paragraphs = {
                name: record[name] for name in paragraph_order(output) if name in record
            }
            digest = document_digest(project)
            # And what each block printed, in a file beside the build that the document
            # names: see `roundtrip.PRINTED_PROPERTY`. Only of a document built into build/,
            # which is one that may be sent: `import` builds the source to compare with, into
            # a scratch folder, and recorded, every import left two files behind.
            printed = None
            if output.resolve().is_relative_to(build_dir.resolve()):
                # A build that produced the document must not fail over its record, and must
                # not keep quiet about it either: without it the import refuses more, and
                # nothing said why. The document names the record all the same where its
                # name is known, so that the import of it says the record is missing.
                try:
                    printed = write_printed(
                        build_dir, output, digest, supplementary=supplementary
                    )
                except RecordNotWritten as exc:
                    printed = exc.name
                    report = report.merge(_record_not_written(output, exc))
                except Exception as exc:
                    report = report.merge(_record_not_written(output, exc))
            stamp_into(output, digest, paragraphs, printed)
    return BuildResult(output=output, mode=mode, report=report)


def _record_not_written(output: Path, reason: Exception) -> Report:
    """What the build says when it could not write the record of what a document printed
    (`roundtrip.write_printed`): a warning, since the document itself is as it should be."""
    return Report(
        (
            Finding(
                gate=GATE,
                code="record-not-written",
                severity=WARN,
                message=(
                    f"the record of what {output.name} printed could not be written beside "
                    f"it, under records/: {reason}"
                ),
                path=output,
                hint=(
                    "`import` reads a document less exactly without its record, and refuses "
                    "more; rebuild once the build folder can be written to, and send that "
                    "document"
                ),
            ),
        )
    )


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
