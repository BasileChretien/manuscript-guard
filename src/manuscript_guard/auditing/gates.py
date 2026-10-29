"""G6 and G14 on a paper that is in no project.

Both gates read a project's manuscript folder, so the paper is put into one made for it in a
temporary folder (`audit_project`) and the gates run on that as `check` runs them: a Markdown
paper as `manuscript/main.md`; a LaTeX entry as `manuscript/main.tex`, beside the files of
its tree at their own paths, and the packages and classes its folder holds; a .docx through
the conversion `init --from` makes (`from_word.convert`), so that its words are read as they
would be once the paper is brought into a project. Without pandoc a .docx is not converted,
and the two gates are passed over for it with a note. Each finding's path is put back to the
paper's, and in a converted .docx its line is a line of the converted text.

The project's `paper.yaml` is empty but for what the audit is told: `--english` declares the
paper's English, and `--submission-residue` makes the residue that answers a reviewer a
failure, as `check` does at the submission stage. Neither gate's finding is counted by
`--strict`.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import Finding

#: What `--english` says, as paper.yaml spells it.
ENGLISH = {"british": "en-GB", "american": "en-US"}


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


def _stage(paper: Path, tree=None) -> _Staged:
    """What the manuscript folder holds for `paper`, by path, and where each file came from.
    Raises ValueError with what to say where it cannot be staged."""
    from manuscript_guard.audit import read_text
    from manuscript_guard.contracts._schema import ContractError

    suffix = paper.suffix.lower()
    if suffix == ".docx":
        from manuscript_guard.build.document import BuildError, pandoc
        from manuscript_guard.from_word import convert

        # Asked here, so that the note is audit's: through `convert` it said "init needs it"
        # (round 1 of #463).
        try:
            pandoc()
        except BuildError as exc:
            raise ValueError(f"{exc}; audit needs it to convert {paper.name} to the text G6 "
                             "and G14 read") from None  # fmt: skip
        try:
            converted = convert(paper)
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


def audit_project(root: Path, staged: _Staged, english: str | None) -> Project:
    """A project at `root` whose manuscript is what `staged` holds."""
    manuscript = root / "manuscript"
    for name, text in staged.files.items():
        target = manuscript / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    paper = {"english_variant": ENGLISH[english]} if english else {}
    return Project(root=root, paper=paper, authors=None)


def run_gates(
    paper: Path, tree=None, *, english: str | None = None, residue: bool = False
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
        project = audit_project(root, staged, english)
        put_back = _putting_back(root / "manuscript", staged.back)
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


def _putting_back(manuscript: Path, back: dict[str, Path]) -> Callable[[Finding], Finding]:
    def put_back(finding: Finding) -> Finding:
        if finding.path is None:
            return finding
        try:
            name = Path(finding.path).resolve().relative_to(manuscript).as_posix()
        except ValueError:
            # paper.yaml, which the paper has none of.
            return replace(finding, path=None)
        return replace(finding, path=back.get(name))

    return put_back
