"""G6 and G14 on a paper that is in no project.

Both gates read a project's manuscript folder, so the paper is put into one made for it in a
temporary folder (`audit_project`) and the gates run on that as `check` runs them: a Markdown
paper as `manuscript/main.md`; a LaTeX entry as `manuscript/main.tex`, beside the files of
its tree at their own paths, and the packages and classes its folder holds; a .docx through
the conversion `init --from` makes (`from_word.convert`), so that its words are read as they
would be once the paper is brought into a project. Without pandoc a .docx is not converted,
and the two gates are passed over for it with a note. A PDF's text (`auditing.pdf`) is
staged as Markdown, each line that holds a section's name alone made a heading
(`_staged_pdf`). Each finding's path is put back to the paper's; in a converted .docx its line
is a line of the converted text, and in a PDF the line of its text, which the report says as
a page and a line. A place a finding's message names, as G14 names where an abbreviation was
first defined, is put back the same way (`_relocated`): it named the staged copy,
"manuscript/main.md:476", of a paper called anything else.

The project's `paper.yaml` is empty but for what the audit is told: `--english` declares the
paper's English, `--known` lists the words its readers know, names, initials and the field's
terms, which G14 then neither asks defined nor reports the spelling of, and
`--submission-residue` makes the residue that answers a reviewer a failure, as `check` does
at the submission stage. Neither gate's finding is counted by `--strict`.

A gate's message and hint say what to set in `paper.yaml`, which a paper audited alone has
none of, so the audit says it in its own words (`_FOR_AN_AUDIT`): the page's setting and the
command line's flag that do the same (the author's audit, 2026-11-10).
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import Finding

#: What `--english` says, as paper.yaml spells it.
ENGLISH = {"british": "en-GB", "american": "en-US"}
#: The words of `--english` for an English as paper.yaml spells it.
_ENGLISH_FLAG = {spelt: word for word, spelt in ENGLISH.items()}
#: What a word the readers know is given as, on the page and on the command line.
KNOWN = 'a known word (on the page, "Words to leave alone"; on the command line, --known)'

#: What G14 tells a project to set in `paper.yaml`, said as an audit sets it: each pattern
#: with what replaces it. `tests/test_audit.py` holds that each one still matches what the
#: gate writes, so that a gate reworded is noticed rather than left saying paper.yaml.
_FOR_AN_AUDIT: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"list it in quotes under `language: known_abbreviations:` in paper\.yaml "
                r"if this journal's readers"),
     lambda found: f"give it to the audit as {KNOWN} if the paper's readers"),
    (re.compile(r"list that one word under `language: accepted_spellings:` in paper\.yaml"),
     lambda found: f"give it to the audit as {KNOWN}"),
    (re.compile(r"paper\.yaml declares no English"),
     lambda found: "no English was chosen for this audit"),
    (re.compile(r"[Ss]et english_variant: (en-GB|en-US)(?: in paper\.yaml)?"),
     lambda found: f'choose it (on the page, "English of the paper"; on the command line, '
                   f"--english {_ENGLISH_FLAG[found[1]]})"),
    (re.compile(r"paper\.yaml says english_variant: (en-GB|en-US)"),
     lambda found: f"the audit was told the paper is in {_ENGLISH_FLAG[found[1]]} English"),
)  # fmt: skip


def for_an_audit(text: str) -> str:
    """A gate's message or hint with what it tells a project to set in paper.yaml said as an
    audit sets it (`_FOR_AN_AUDIT`)."""
    for pattern, said in _FOR_AN_AUDIT:
        text = pattern.sub(said, text)
    return text


@dataclass
class GateRun:
    """G6 and G14 on one paper: their findings, at the paper's paths, or why they did not run."""

    paper: Path
    writing: list[Finding] = field(default_factory=list)
    language: list[Finding] = field(default_factory=list)
    note: str = ""
    #: Whether the lines are lines of a converted text, not of the paper itself.
    converted: bool = False


@dataclass(frozen=True)
class _Staged:
    files: dict[str, str]
    back: dict[str, Path]
    converted: bool = False
    #: For a PDF, the line of its text (`auditing.pdf.PdfText.text`) that each line of the
    #: staged `main.md` is, from 1.
    lines: tuple[int, ...] = ()
    #: For a PDF whose headings cannot be placed exactly (`auditing.pdf.PdfText.placed`):
    #: where its Abstract ends is not read, so G4's limits on its words are not checked.
    unplaced: bool = False
    #: For a PDF, a line of its text in words, "page 3, line 12" (`PdfText.said`).
    said: Callable[[int | None], str] | None = None


def _staged_pdf(paper: Path) -> _Staged:
    """A PDF's text as the Markdown G4, G6 and G14 read: each line of it a line, and each line
    that holds a section's name alone (`auditing.pdf.heading_title`) a heading, a blank line
    before and after it, a structured abstract's a heading under the Abstract's where it can
    be placed (`PdfText.placed`), with the line of the text each line of the Markdown is."""
    from manuscript_guard.auditing.pdf import UnreadablePdf, read_pdf

    try:
        pdf = read_pdf(paper)
    except UnreadablePdf as exc:
        raise ValueError(str(exc)) from None
    placed = pdf.placed
    levels = ({line: (title, level) for line, title, level in placed} if placed is not None
              else {line: (title, 1) for line, title in pdf.headings})  # fmt: skip
    staged: list[str] = []
    lines: list[int] = []
    for at, text in enumerate(pdf.text.split("\n"), 1):
        said = ["", f"{'#' * levels[at][1]} {levels[at][0]}", ""] if at in levels else [text]
        staged += said
        lines += [at] * len(said)
    return _Staged({"main.md": "\n".join(staged) + "\n"}, {"main.md": paper}, lines=tuple(lines),
                   unplaced=placed is None, said=pdf.said)  # fmt: skip


def _stage(paper: Path, tree=None) -> _Staged:
    """What the manuscript folder holds for `paper`, by path, and where each file came from.
    Raises ValueError with what to say where it cannot be staged."""
    from manuscript_guard.audit import read_text
    from manuscript_guard.contracts._schema import ContractError

    suffix = paper.suffix.lower()
    if suffix == ".pdf":
        return _staged_pdf(paper)
    if suffix == ".docx":
        from manuscript_guard import from_word
        from manuscript_guard.build.document import BuildError, pandoc

        # Asked here, so that the note is audit's: through `convert` it said "init needs it"
        # (round 1 of #463). Not where pandoc is run otherwise than from PATH, as the
        # in-browser page runs pandoc.wasm (`from_word.runner`).
        if from_word.runner is None:
            try:
                pandoc()
            except BuildError as exc:
                raise ValueError(f"{exc}; audit needs it to convert {paper.name} to the text "
                                 "G6 and G14 read") from None  # fmt: skip
        try:
            converted = from_word.convert(paper)
        except ContractError as exc:
            raise ValueError(str(exc)) from None
        return _Staged({"main.md": converted.text}, {"main.md": paper}, converted=True)
    if suffix != ".tex":
        return _Staged({"main.md": read_text(paper)}, {"main.md": paper})
    if tree is None:
        raise ValueError(f"{paper.name}: its tree was not read")
    entry = paper.relative_to(tree.folder).as_posix()
    files, back = {}, {}
    for path, source in tree.files:
        name = path.relative_to(tree.folder).as_posix()
        if name == "main.tex" and name != entry:
            raise ValueError(f"{paper.name} inputs a file named main.tex, the name its own "
                             "copy is given here")  # fmt: skip
        name = "main.tex" if name == entry else name
        files[name], back[name] = source.text, path
    for path in sorted([*tree.folder.rglob("*.sty"), *tree.folder.rglob("*.cls")]):
        name = path.relative_to(tree.folder).as_posix()
        try:
            files[name] = read_text(path)
        except (OSError, ValueError):
            continue
        back[name] = path
    return _Staged(files, back)


def audit_project(
    root: Path, staged: _Staged, english: str | None, known: tuple[str, ...] = ()
) -> Project:
    """A project at `root` whose manuscript is what `staged` holds, its English and the
    words its readers know (`--known`) declared as paper.yaml would declare them."""
    manuscript = root / "manuscript"
    for name, text in staged.files.items():
        target = manuscript / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    paper: dict = {"english_variant": ENGLISH[english]} if english else {}
    if known:
        paper["language"] = {"known_abbreviations": list(known),
                             "accepted_spellings": list(known)}  # fmt: skip
    return Project(root=root, paper=paper, authors=None)


def run_gates(
    paper: Path,
    tree=None,
    *,
    english: str | None = None,
    residue: bool = False,
    known: tuple[str, ...] = (),
) -> GateRun:
    """G6 and G14 on `paper`, its LaTeX tree given where it is one."""
    from manuscript_guard.gates.language import check_language
    from manuscript_guard.gates.writing import check_writing

    try:
        staged = _stage(paper, tree)
    except ValueError as exc:
        return GateRun(paper, note=f"G6 and G14 were not run on {paper.name}: {exc}")
    with tempfile.TemporaryDirectory(prefix="mg-audit-") as folder:
        root = Path(folder).resolve()
        project = audit_project(root, staged, english, known)
        put_back = _putting_back(root / "manuscript", staged.back, staged.lines, staged.said)
        try:
            writing = check_writing(project, submission=residue)
            language = check_language(project)
        except Exception as exc:  # noqa: BLE001 - a gate that raised is said, not hidden
            from manuscript_guard.diagnostics import crashes

            crashes.record(exc, kind=crashes.GATE, name="G6 and G14")
            return GateRun(paper, note=f"G6 and G14 could not run on {paper.name}: "
                           f"{type(exc).__name__}: {exc}")  # fmt: skip
        return GateRun(
            paper,
            writing=[put_back(f) for f in writing.sorted().findings],
            language=[put_back(f) for f in language.sorted().findings],
            converted=staged.converted,
        )


def _putting_back(manuscript: Path, back: dict[str, Path], lines: tuple[int, ...] = (),
                  said: Callable[[int | None], str] | None = None,
                  ) -> Callable[[Finding], Finding]:  # fmt: skip
    """Each finding at the paper's path; in a PDF at the line of its text, with no column,
    which is the staged Markdown's (`_staged_pdf`). The places its message and its hint
    name, the paper's too (`_relocated`)."""
    relocated = _relocated(back, lines, said)

    def put_back(finding: Finding) -> Finding:
        finding = replace(finding, message=for_an_audit(relocated(finding.message)),
                          hint=finding.hint and for_an_audit(relocated(finding.hint)))  # fmt: skip
        if finding.path is None:
            return finding
        try:
            name = Path(finding.path).resolve().relative_to(manuscript).as_posix()
        except ValueError:
            # paper.yaml, which the paper has none of.
            return replace(finding, path=None)
        if lines and name == "main.md":
            line = finding.line
            at = lines[line - 1] if line is not None and 0 < line <= len(lines) else None
            return replace(finding, path=back.get(name), line=at, col=None)
        return replace(finding, path=back.get(name))

    return put_back


def _relocated(
    back: dict[str, Path], lines: tuple[int, ...] = (),
    said: Callable[[int | None], str] | None = None,
) -> Callable[[str], str]:  # fmt: skip
    """What puts a place in the staged project back in the paper. A gate names a manuscript
    file by its path from the project's root, "manuscript/main.md:476", and the staged
    `main.md` or `main.tex` is the paper under another name: it is named by the paper's
    name, a file of its LaTeX tree by its path in the tree, and a line of a PDF's staged
    Markdown as the page and the line of its text, "paper.pdf, page 3, line 12"."""
    if not back:
        return lambda text: text
    names = "|".join(re.escape(name) for name in sorted(back, key=len, reverse=True))
    # Standing alone: after a space, a bracket or a quotation mark, or at the start.
    place = re.compile(rf"(?<![^\s(\[\"'`])manuscript/({names})(?::(\d+))?(?![\w/]|\.\w)")

    def shown(match: re.Match[str]) -> str:
        name, line = match[1], match[2]
        file = back[name].name if name in ("main.md", "main.tex") else name
        if line is None:
            return file
        if lines and said is not None and name == "main.md":
            at = int(line)
            return f"{file}, {said(lines[at - 1] if 0 < at <= len(lines) else None)}"
        return f"{file}:{line}"

    return lambda text: place.sub(shown, text)
