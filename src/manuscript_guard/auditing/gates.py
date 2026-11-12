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
is a line of the converted text, which the report says as the document's heading and
paragraph (`auditing.paragraphs`), and in a PDF the line of its text, which the report says
as a page and a line. A place a finding's message names, as G14 names where an abbreviation was
first defined, is put back the same way (`_relocated`): it named the staged copy,
"manuscript/main.md:476", of a paper called anything else.

The project's `paper.yaml` is empty but for what the audit is told: `--english` declares the
paper's English, `--known` lists the words its readers know, names, initials and the field's
terms, which G14 then neither asks defined, reports the spelling of nor reads as code, and
`--submission-residue` makes the residue that answers a reviewer a failure, as `check` does
at the submission stage. Neither gate's finding is counted by `--strict`.

G14's messages and hints say what to set in `paper.yaml`, which a paper audited alone has
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
#: An English as paper.yaml spells it, in words.
_ENGLISH_NAME = {"en-GB": "British", "en-US": "American"}
#: What a word the readers know is given as, on the page and on the command line.
KNOWN = 'a known word (on the page, "Words to leave alone"; on the command line, --known)'

#: What G14 tells a project to set in `paper.yaml`, said as an audit sets it: each pattern
#: with what replaces it. `tests/test_audit.py` holds that each one still matches what the
#: gate writes, so that a gate reworded is noticed rather than left saying paper.yaml. (G4
#: under `--journal` reads no English from paper.yaml in an audit, `FROM_RECORDS`.)
_FOR_AN_AUDIT: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str]], ...] = (
    (re.compile(r"list it in quotes under `language: known_abbreviations:` in paper\.yaml "
                r"if this journal's readers"),
     lambda found: f"give it to the audit as {KNOWN} if the paper's readers"),
    (re.compile(r"list that one word under `language: accepted_spellings:` in paper\.yaml"),
     lambda found: f"give it to the audit as {KNOWN}"),
    (re.compile(r"list it under `language: code_names_kept:` in paper\.yaml"),
     lambda found: f"give it to the audit as {KNOWN}"),
    (re.compile(r"paper\.yaml declares no English"),
     lambda found: "no English was chosen for this audit"),
    (re.compile(r"[Ss]et english_variant: (en-GB|en-US)(?: in paper\.yaml)?"),
     lambda found: f'choose {_ENGLISH_NAME[found[1]]} English (on the page, "English of the '
                   f'paper"; on the command line, --english {_ENGLISH_FLAG[found[1]]})'),
    (re.compile(r"paper\.yaml says english_variant: (en-GB|en-US)"),
     # The English is the reader's (--english) or, under --journal, the profile's.
     lambda found: f"the audit holds the paper to {_ENGLISH_NAME[found[1]]} English"),
)  # fmt: skip


def for_an_audit(text: str) -> str:
    """A gate's message or hint with what it tells a project to set in paper.yaml said as an
    audit sets it (`_FOR_AN_AUDIT`)."""
    for pattern, said in _FOR_AN_AUDIT:
        text = pattern.sub(said, text)
    return text


@dataclass(frozen=True)
class Tracked:
    """One correction G14 would make in a .docx, as the document prints it: `old` becomes
    `new`, found by the words of its paragraph just `before` and `after` it; `codes` are the
    findings it corrects (`corrections.py`), and `line` the line of the converted text it
    stands on, as theirs is. `left_out` says why it cannot be written as a tracked change,
    where it cannot: its words are then the converted text's, and its finding stays a
    comment."""

    codes: tuple[str, ...]
    old: str
    new: str
    before: str = ""
    after: str = ""
    line: int = 0
    left_out: str = ""


@dataclass
class GateRun:
    """G6 and G14 on one paper: their findings, at the paper's paths, or why they did not run."""

    paper: Path
    writing: list[Finding] = field(default_factory=list)
    language: list[Finding] = field(default_factory=list)
    note: str = ""
    #: Whether the lines are lines of a converted text, not of the paper itself.
    converted: bool = False
    #: For a converted .docx, where each line of the converted text stands in the document,
    #: "Methods, paragraph 3" (`auditing.paragraphs`).
    places: object = None
    #: For a .docx whose copy in Track Changes is asked for (`--tracked`), each correction
    #: G14 is sure of; empty otherwise.
    corrections: list[Tracked] = field(default_factory=list)


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
    #: For a PDF, a line of its text in words, "page 3, line 12" (`PdfText.said`); for a
    #: .docx, a line of its converted text, "Methods, paragraph 3" (`places`).
    said: Callable[[int | None], str] | None = None
    #: For a .docx, where each line of the converted text stands (`auditing.paragraphs`).
    places: object = None


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
    from manuscript_guard.text.latex.encodings import CODECS, as_utf8

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
        from manuscript_guard.auditing.paragraphs import of_markdown

        places = of_markdown(converted.text)
        return _Staged({"main.md": converted.text}, {"main.md": paper}, converted=True,
                       said=places.said, places=places)  # fmt: skip
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
    codec = CODECS.get(getattr(tree, "encoding", None) or "")
    for path in sorted([*tree.folder.rglob("*.sty"), *tree.folder.rglob("*.cls")]):
        name = path.relative_to(tree.folder).as_posix()
        try:
            # In the encoding the tree was read in, its declarations UTF-8's, as the files
            # of the tree are (`auditing.latex._gathered`).
            files[name] = as_utf8(read_text(path, codec)) if codec else read_text(path)
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
                             "accepted_spellings": list(known),
                             "code_names_kept": list(known)}  # fmt: skip
    return Project(root=root, paper=paper, authors=None)


def run_gates(
    paper: Path,
    tree=None,
    *,
    english: str | None = None,
    residue: bool = False,
    known: tuple[str, ...] = (),
    corrected: bool = False,
) -> GateRun:
    """G6 and G14 on `paper`, its LaTeX tree given where it is one; and, `corrected`, G14's
    corrections of a .docx for the copy `--tracked` writes, which are worked out only where
    that copy is asked for (Basile, 2026-11-12: "only when asked")."""
    from manuscript_guard.gates.language import check_language
    from manuscript_guard.gates.writing import check_writing

    try:
        staged = _stage(paper, tree)
    except ValueError as exc:
        return GateRun(paper, note=f"G6 and G14 were not run on {paper.name}: {exc}")
    with tempfile.TemporaryDirectory(prefix="mg-audit-") as folder:
        root = Path(folder).resolve()
        project = audit_project(root, staged, english, known)
        put_back = _putting_back(root / "manuscript", staged.back, staged.lines, staged.said,
                                 word=staged.converted)  # fmt: skip
        try:
            writing = check_writing(project, submission=residue)
            language = check_language(project)
        except Exception as exc:  # noqa: BLE001 - a gate that raised is said, not hidden
            from manuscript_guard.diagnostics import crashes

            crashes.record(exc, kind=crashes.GATE, name="G6 and G14")
            return GateRun(paper, note=f"G6 and G14 could not run on {paper.name}: "
                           f"{type(exc).__name__}: {exc}")  # fmt: skip
        from manuscript_guard.auditing.undefined import one_finding
        from manuscript_guard.findings import Report

        # The short forms used and not defined in one finding (`auditing.undefined`), made
        # from G14's warnings in the order it gave them, its reading order, then sorted.
        said = one_finding([put_back(f) for f in language.findings])
        # Only a .docx is copied with its corrections in Track Changes, and only where asked.
        corrections = _corrections(project) if corrected and staged.converted else []
        return GateRun(
            paper,
            writing=[put_back(f) for f in writing.sorted().findings],
            language=list(Report(tuple(said)).sorted().findings),
            converted=staged.converted,
            places=staged.places,
            corrections=corrections,
        )


def _corrections(project: Project) -> list[Tracked]:
    """G14's corrections of the converted .docx, as the document prints them; none where
    reading them raised, which is recorded as a crash and leaves G14's findings as they are,
    each a comment of the copy."""
    from manuscript_guard.diagnostics import crashes
    from manuscript_guard.gates.language import language_edits

    try:
        return as_tracked(language_edits(project))
    except Exception as exc:  # noqa: BLE001 - the findings stand without their corrections
        if crashes.debugging():
            raise
        crashes.record(exc, kind=crashes.GATE, name="G14's corrections")
        return []


#: What Markdown writes that a Word document does not print: emphasis, a raised or lowered
#: piece, a link's or a span's brackets, a code span, an HTML tag, a table's cell marks,
#: maths, and a backslash that escapes nothing, which ends a line. A correction holding one
#: is not written, and its finding stays a comment; the words around one are cut at it.
_UNPRINTED = frozenset("*_^~[]{}`<>|$\\")
#: What pandoc's Markdown writer, its `smart` extension on, prints for a character of the
#: document's own: two hyphens for an en dash, three for an em dash, three dots for an
#: ellipsis. Hyphens and dots of the document's own it writes escaped, "1\--2" (pandoc
#: 3.9, 2026-11-12).
_SMART = (("---", "—"), ("--", "–"), ("...", "…"))
#: A quotation mark or an apostrophe pandoc writes straight, which the document has curly,
#: opening or closing, or straight where it writes it escaped: the words around a
#: correction may hold one, which then stands for any of them, and its own words not.
_STRAIGHT = frozenset("'\"")
#: What opens a line as a heading or an item of a list, which the document prints as
#: neither.
_LINE_MARK = re.compile(r"(?:#{1,6}|[-+]|\d{1,9}[.)])[ \t]+")
#: How many characters of its paragraph each side of a correction find it in the document.
_AROUND = 40


def as_tracked(edits: list) -> list[Tracked]:
    """G14's edits of the converted text of a .docx (`main.md`) as the document prints
    them: each correction's words, and the words of its paragraph either side of it, cut
    at a word and at a mark the document does not print, with pandoc's escapes taken off
    and its dashes and dots put back. One the document cannot be given exactly is kept
    with why (`left_out`), so that its finding stays a comment."""
    from manuscript_guard.corrections import corrections

    texts = {edit.passage.path: edit.passage.text for edit in edits}
    out = []
    for one in corrections(edits):
        if one.path.name != "main.md":
            continue
        text = texts[one.path]
        start, end = one.offset, one.offset + len(one.old)
        old, new = _printed(one.old, exact=True), _printed(one.new, exact=True)
        why = _why_left_out(one.old, one.new, old, new)
        if why:
            out.append(Tracked(one.codes, one.old, one.new, line=one.line, left_out=why))
            continue
        before, after = _around(text, start, end)
        out.append(Tracked(one.codes, old, new, before, after, one.line))
    return out


def _why_left_out(old: str, new: str, printed_old: str | None, printed_new: str | None) -> str:
    """Why a correction cannot be written as the document prints it, or ""."""
    if "\n" in old or "\n" in new:
        return "it runs over a line of the converted text"
    if printed_old is None or printed_new is None:
        if any(kind == "straight" for words in (old, new) for *_, kind in _pieces(words)):
            return "its words hold a quotation mark the converted text writes straight"
        return "its words hold a mark the document does not print"
    if not printed_old or printed_old == printed_new:
        return "it changes nothing the document prints"
    return ""


def _around(text: str, start: int, end: int) -> tuple[str, str]:
    """The words of the line `text[start:end]` stands on, either side of it, as the
    document prints them: at most `_AROUND` characters, cut at a word where the line runs
    on and at the mark nearest it that the document does not print, and without what opens
    the line as a heading or an item of a list."""
    opened = text.rfind("\n", 0, start) + 1
    marked = _LINE_MARK.match(text, opened)
    if marked is not None and marked.end() <= start:
        opened = marked.end()
    closed = text.find("\n", end)
    closed = len(text) if closed < 0 else closed
    before = text[max(opened, start - _AROUND) : start]
    if start - _AROUND > opened:
        space = re.search(r"\s", before)
        before = before[space.end() :] if space else ""
    after = text[end : min(closed, end + _AROUND)]
    if end + _AROUND < closed:
        space = max(after.rfind(" "), after.rfind("\t"))
        after = after[:space] if space >= 0 else ""
    return (_printed(_cut(before, last=True), exact=False) or "",
            _printed(_cut(after, last=False), exact=False) or "")  # fmt: skip


def _pieces(words: str):
    """Each character the document prints for `words` of the converted text, with where it
    starts there and what it is: "text", "unprinted" (`_UNPRINTED`), or "straight"
    (`_STRAIGHT`). An escape is the mark it escapes, and pandoc's dashes and dots
    (`_SMART`) the one character each stands for."""
    at = 0
    while at < len(words):
        if _ESCAPED.match(words, at):
            yield at, words[at + 1], "text"
            at += 2
            continue
        smart = next((pair for pair in _SMART if words.startswith(pair[0], at)), None)
        if smart is not None:
            yield at, smart[1], "text"
            at += len(smart[0])
            continue
        char = words[at]
        yield at, char, ("unprinted" if char in _UNPRINTED
                         else "straight" if char in _STRAIGHT else "text")  # fmt: skip
        at += 1


def _cut(words: str, *, last: bool) -> str:
    """`words` cut at the mark the document does not print nearest the correction: the
    words after the last one where they stand before it (`last`), else before the first."""
    marks = [at for at, _char, kind in _pieces(words) if kind == "unprinted"]
    if not marks:
        return words
    return words[marks[-1] + 1 :] if last else words[: marks[0]]


def _printed(words: str, *, exact: bool) -> str | None:
    """`words` of the converted text as the document prints them, a line's break a space;
    None where they hold a mark the document does not print, or, `exact`, a quotation mark
    written straight, which may stand for either curly one."""
    out = []
    for _at, char, kind in _pieces(words):
        if kind == "unprinted" or (exact and kind == "straight"):
            return None
        out.append(char)
    return re.sub(r"[ \t\r\n]+", " ", "".join(out))


#: A mark of ASCII punctuation pandoc writes with a backslash in front, "p\<0.05", so that
#: Markdown does not read it as its own: the Word document has none.
_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")
#: A word quoted in Markdown's emphasis, "'*p*'", which the Word document prints in italics
#: or in bold.
_QUOTED_BOLD = re.compile(r"'\*\*([^*'\n]+)\*\*'")
_QUOTED_ITALIC = re.compile(r"'\*([^*'\n]+)\*'")
#: The name of the G6 rule a phrasing finding opens with, "importance-tail: ", which means
#: nothing to a reader of the report (the author's audit, 2026-11-10).
_RULE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*: ")


def as_in_word(text: str) -> str:
    """Text a gate quotes from a .docx's converted Markdown, as the document prints it: its
    escapes taken off, a word quoted in emphasis said to be in italics or in bold."""
    text = _QUOTED_BOLD.sub(r"'\1' in bold", text)
    text = _QUOTED_ITALIC.sub(r"'\1' in italics", text)
    return _ESCAPED.sub(r"\1", text)


def _putting_back(manuscript: Path, back: dict[str, Path], lines: tuple[int, ...] = (),
                  said: Callable[[int | None], str] | None = None, *, word: bool = False,
                  ) -> Callable[[Finding], Finding]:  # fmt: skip
    """Each finding at the paper's path; in a PDF at the line of its text, with no column,
    which is the staged Markdown's (`_staged_pdf`). The places its message and its hint
    name, the paper's too (`_relocated`). A phrasing finding's message without the rule's
    name; and in a .docx converted (`word`), what it quotes as the document prints it
    (`as_in_word`)."""
    relocated = _relocated(back, lines, said)
    shown = as_in_word if word else (lambda text: text)

    def put_back(finding: Finding) -> Finding:
        message = finding.message
        if finding.code == "ai-phrasing":
            message = _RULE_NAME.sub("", message, count=1)
        # Said in the audit's own settings (`for_an_audit`), then as Word prints it.
        finding = replace(finding, message=shown(for_an_audit(relocated(message))),
                          hint=finding.hint and shown(for_an_audit(relocated(finding.hint))),
                          context=finding.context and shown(finding.context))  # fmt: skip
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
    name, a file of its LaTeX tree by its path in the tree, a line of a PDF's staged
    Markdown as the page and the line of its text, "page 3, line 12", and a line of a
    .docx's converted text as its section and paragraph, "Methods, paragraph 3" (`said` with
    no `lines`). Those two are places in the very paper whose finding names them, which the
    report names over it, so its name is not said again at each (the author's audit,
    2026-11-11: "defined later at Pharmaquest_manuscript_untracked.docx, Conclusions,
    paragraph 26")."""
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
        if said is not None and name == "main.md":
            at = int(line)
            if not lines:
                return said(at)
            return said(lines[at - 1] if 0 < at <= len(lines) else None)
        return f"{file}:{line}"

    return lambda text: place.sub(shown, text)
