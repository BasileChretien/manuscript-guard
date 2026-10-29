"""What a Word file holds besides its text, for the editor or the referee it was sent to.

A submission sent with its tracked changes still in it, a comment left in, text formatted as
hidden, or the names of the people who edited it in its properties, says things its authors
did not mean to send. Each is read from the document's XML as Word writes it, exactly, and
counted (`document_facts`):

- tracked insertions and deletions: each `w:ins` and `w:del` that holds text, in the body,
  the notes, the headers and the footers. A change Word marks on a paragraph mark alone, or
  on formatting, holds no text and is not counted;
- tracked moves: each move once, by the name Word gives the range it was moved to
  (`w:moveToRangeStart`), however many paragraphs it wraps in a `w:moveTo` of their own
  (Word 365, 2026-10-29); a `w:moveTo` that holds text in no named range counts once;
- comments: each `w:comment` of `word/comments.xml`;
- hidden text: each run with text whose own properties hide it (`w:vanish`). Text a style
  hides is not read (Known gaps);
- the names Word keeps, each with the field it is in: the document's author (`dc:creator`)
  and last editor (`cp:lastModifiedBy`), the author of each tracked change and comment
  (`w:author`), and the people `word/people.xml` lists.

None of it is counted by `--strict`: some journals ask for a revision with its changes
tracked. Whether a name there is one of the authors' is the blinding check's
(`auditing.journal`), with `--authors`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.safexml import UnsafeDocument, open_archive, read_part

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_W15 = "{http://schemas.microsoft.com/office/word/2012/wordml}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_CORE = {
    "{http://purl.org/dc/elements/1.1/}creator": "the document's author (dc:creator)",
    "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy": (
        "the document's last editor (cp:lastModifiedBy)"
    ),
}
#: Where an author of a tracked change or a comment is written: the body, the notes, the
#: comments, the headers and the footers.
_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml", "word/comments.xml")
_HEADER_FOOTER = ("word/header", "word/footer")
#: What a tracked change that holds text holds it in.
_TEXT = (f"{_W}t", f"{_W}delText", f"{_W}instrText", f"{_W}delInstrText")
#: The values of an on-off property that turn it off.
_OFF = ("0", "false", "off")


@dataclass
class DocumentFacts:
    """What one .docx holds besides its text."""

    path: Path
    insertions: int = 0
    deletions: int = 0
    moves: int = 0
    comments: int = 0
    hidden: int = 0
    #: Each name Word keeps, with the field it is in, in the order read, once per field.
    people: list[tuple[str, str]] = field(default_factory=list)
    #: Why the document could not be read, where it could not.
    note: str = ""


def _parts(names: list[str]) -> list[str]:
    return [name for name in names if name in _PARTS or (
        name.startswith(_HEADER_FOOTER) and name.endswith(".xml"))]  # fmt: skip


def _holds_text(element) -> bool:
    return any(node.tag in _TEXT and (node.text or "").strip() for node in element.iter())


def _hidden(run) -> bool:
    """Whether a run's own properties hide it: `w:vanish` on, and text in it."""
    properties = run.find(f"{_W}rPr")
    vanish = None if properties is None else properties.find(f"{_W}vanish")
    if vanish is None or vanish.get(f"{_W}val", "1").casefold() in _OFF:
        return False
    return any((node.text or "").strip() for node in run.iter(f"{_W}t"))


def _elements(root):
    """Each element of a part, in document order, but those of an AlternateContent's
    fallback: Word writes a text box twice, the fallback for readers that predate it, and
    `text.docx` reads only the choice (round 2 of #478: a change in a box counted twice)."""
    stack = [root]
    while stack:
        element = stack.pop()
        if element.tag == _FALLBACK:
            continue
        yield element
        stack.extend(reversed(list(element)))


def _moves(root) -> int:
    """The moves of one part, each once: the named ranges a move went to, and each `w:moveTo`
    holding text outside any of them. Word wraps each paragraph of a move in a `w:moveTo` of
    its own, between one `w:moveToRangeStart` and its `w:moveToRangeEnd`."""
    named: set[str] = set()
    open_ranges: set[str] = set()
    alone = 0
    for element in _elements(root):
        if element.tag == f"{_W}moveToRangeStart":
            open_ranges.add(element.get(f"{_W}id", ""))
            named.add(element.get(f"{_W}name") or f"#{element.get(f'{_W}id', '')}")
        elif element.tag == f"{_W}moveToRangeEnd":
            open_ranges.discard(element.get(f"{_W}id", ""))
        elif element.tag == f"{_W}moveTo" and not open_ranges and _holds_text(element):
            alone += 1
    return len(named) + alone


def document_facts(path: Path) -> DocumentFacts:
    """What `path`, a .docx, holds besides its text (see the module's docstring)."""
    facts = DocumentFacts(path)
    try:
        with open_archive(path) as archive:
            names = archive.namelist()
            authors: list[str] = []
            for name in _parts(names):
                root = read_part(archive, name)
                facts.moves += _moves(root)
                for element in _elements(root):
                    if element.tag in (f"{_W}ins", f"{_W}del") and _holds_text(element):
                        if element.tag == f"{_W}ins":
                            facts.insertions += 1
                        else:
                            facts.deletions += 1
                    elif element.tag == f"{_W}comment" and name == "word/comments.xml":
                        facts.comments += 1
                    elif element.tag == f"{_W}r" and _hidden(element):
                        facts.hidden += 1
                    author = element.get(f"{_W}author")
                    if author and author.strip() and author.strip() not in authors:
                        authors.append(author.strip())
            if "docProps/core.xml" in names:
                for node in read_part(archive, "docProps/core.xml"):
                    if node.tag in _CORE and node.text and node.text.strip():
                        facts.people.append((_CORE[node.tag], node.text.strip()))
            facts.people += [("the author of a tracked change or a comment (w:author)", a)
                             for a in authors]  # fmt: skip
            if "word/people.xml" in names:
                listed = []
                for node in read_part(archive, "word/people.xml").iter(f"{_W15}person"):
                    person = (node.get(f"{_W15}author") or "").strip()
                    if person and person not in listed:
                        listed.append(person)
                facts.people += [("the people who edited it (word/people.xml)", p)
                                 for p in listed]  # fmt: skip
    except UnsafeDocument as exc:
        facts.note = f"{path.name} could not be read for what it holds besides its text: {exc}"
    return facts


def described(facts: DocumentFacts) -> str:
    """One line of what the document holds: its tracked changes, comments and hidden text."""
    if facts.note:
        return facts.note
    held = [
        _counted(facts.insertions, "tracked insertion"),
        _counted(facts.deletions, "tracked deletion"),
        _counted(facts.moves, "tracked move"),
        _counted(facts.comments, "comment"),
        _counted(facts.hidden, "run of hidden text", "runs of hidden text"),
    ]
    return f"{facts.path.name}: " + ", ".join(held)


def _counted(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"
