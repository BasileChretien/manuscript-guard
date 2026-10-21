"""The title page of a proof held to `authors.yaml`: each author's name, in the order listed,
each affiliation's text, each ORCID iD the proof prints, and the corresponding author's
e-mail address.

The document sent carries none of these: the title page is its own file of the pack, written
from `authors.yaml` (`build.submission.title_page`). So they are looked for in the whole of
the proof's text, read as the comparison reads it (`tokens.prepared`, `tokens.key`): case
and the shape of quotation marks and dashes aside, letter for letter, accents kept. A name
the proof prints with the given name's initials only is shown and not counted, as a
journal's style may set it. Which superscript links an author to which affiliation is not
read: the PDF's text keeps the digit and loses what it is set against.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from manuscript_guard.contracts.project import Project
from manuscript_guard.proof.compare import CORRECTION, Change
from manuscript_guard.proof.reading import Reading
from manuscript_guard.proof.tokens import TYPOGRAPHY, key, prepared

#: Read in words already folded to lower case: an iD that ends in X is "...x" by then.
_ORCID = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b", re.IGNORECASE)
#: The marks set against a name: affiliations by number, "1,2" or "1-3", and the signs of a
#: corresponding author or of equal contribution.
_MARKS = re.compile(r"[\d,;*#†‡§¶‖\-–]*")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_WORDS = re.compile(r"\S+")
#: How alike a stretch of the proof must be to a name or an affiliation to be it, changed.
ALIKE = 0.8
#: How many of an affiliation's words must stand together in the proof for it to be there,
#: changed, rather than missing.
SHARE = 0.6


@dataclass(frozen=True)
class _Flat:
    """The proof's text in one line of folded words, each word with the line it is on."""

    words: list[str]
    lines: list[int]
    #: Each word as the proof prints it, for the report.
    shown: list[str]

    @property
    def text(self) -> str:
        return " ".join(self.words)

    def printed(self, start: int, end: int) -> str:
        return " ".join(self.shown[start:end])


#: What stands at a word's edges and is not the word: punctuation, and the superscript
#: number in front of an affiliation ("1Department").
_EDGES = re.compile(r"^(?:[^\w@]+|\d+(?=[^\W\d]))|[^\w@]+$")


def _bare(word: str) -> str:
    return key(_EDGES.sub("", word))


def _said(text: str) -> list[str]:
    return [bare for word in _WORDS.findall(prepared(text)) if (bare := _bare(word))]


def _flat(reading: Reading) -> _Flat:
    """The proof's words, a word broken at a line's end put together again."""
    words: list[str] = []
    lines: list[int] = []
    shown: list[str] = []
    broken = False
    for index, line in enumerate(reading.lines):
        for word in _WORDS.findall(prepared(line.text)):
            bare = _EDGES.sub("", word)
            if broken and bare[:1].islower() and words:
                # In an address the hyphen is the domain's: "nagoya-" and "u.ac.jp".
                joint = "-" if "@" in shown[-1] else ""
                words[-1] += joint + key(bare)
                shown[-1] += joint + bare
                broken = False
                continue
            broken = False
            if bare:
                words.append(key(bare))
                shown.append(bare)
                lines.append(index)
        broken = prepared(line.text).rstrip().endswith("-")
    return _Flat(words, lines, shown)


def check_front(project: Project, reading: Reading) -> tuple[list[Change], set[int]]:
    """The corrections the title page needs, and the lines of the proof that were found to
    be the title page's, which are then not reported as added."""
    from manuscript_guard.approvals import authors_of, name_of

    authors = authors_of(project)
    if not authors:
        return [], set()
    flat = _flat(reading)
    changes: list[Change] = []
    used: set[int] = set()
    first: list[int | None] = []
    for author in authors:
        name = name_of(author)
        at = _find(flat, name)
        first.append(at)
        if at is not None:
            used.update(flat.lines[at : at + len(name.split())])
            continue
        changes.append(_name_change(flat, reading, author, name))
    found = [at for at in first if at is not None]
    if len(found) == len(first) and found != sorted(found):
        printed = ", ".join(name_of(a) for _at, a in sorted(zip(found, authors, strict=True),
                                                             key=lambda pair: pair[0]))
        changes.append(_change(reading, flat, min(found), "authors' order",
                               ", ".join(map(name_of, authors)), printed))  # fmt: skip
    for affiliation in (project.authors or {}).get("affiliations") or []:
        text = str(affiliation.get("text") or "") if isinstance(affiliation, dict) else ""
        if text.strip():
            change = _affiliation(flat, reading, text, used)
            if change is not None:
                changes.append(change)
    changes += _identifiers(flat, reading, authors, used)
    return changes, used


def _find(flat: _Flat, said: str) -> int | None:
    """Where the words of `said` stand in a row in the proof, first."""
    wanted = _said(said)
    if not wanted:
        return None
    for at in range(len(flat.words) - len(wanted) + 1):
        if flat.words[at] != wanted[0] or flat.words[at : at + len(wanted) - 1] != wanted[:-1]:
            continue
        last = flat.words[at + len(wanted) - 1]
        # A name with its marks set against it: "example1", "example1,2", "example1-3,*".
        if last.startswith(wanted[-1]) and _MARKS.fullmatch(last[len(wanted[-1]) :]):
            return at
    return None


def _change(reading: Reading, flat: _Flat, at: int | None, what: str, sent: str, printed: str,
            kind: str = CORRECTION, note: str = "") -> Change:  # fmt: skip
    line = reading.lines[flat.lines[at]] if at is not None and flat.lines else None
    return Change(kind, what, "the title page", sent, printed,
                  line.page if line else None, line.number if line else None, note=note,
                  at=-1)  # fmt: skip


def _name_change(flat: _Flat, reading: Reading, author: dict, name: str) -> Change:
    family = str(author.get("family") or "").strip()
    given = str(author.get("given") or "").strip()
    initials = " ".join(part[0] + "." for part in given.replace("-", " ").split() if part)
    for shown in (f"{initials} {family}", initials.replace(" ", "") + f" {family}"):
        at = _find(flat, shown)
        if at is not None and initials:
            return _change(reading, flat, at, "author's name", name, shown, TYPOGRAPHY,
                           "printed with the given name's initials")  # fmt: skip
    at, printed = _alike(flat, name)
    if at is not None:
        return _change(reading, flat, at, "author's name", name, printed,
                       note="the name is printed otherwise")  # fmt: skip
    return _change(reading, flat, None, "author's name", name, "", note="not in the proof")


def _alike(flat: _Flat, said: str) -> tuple[int | None, str]:
    """The stretch of the proof as long as `said` that is most like it, if it is alike."""
    wanted = " ".join(_said(said))
    size = len(wanted.split())
    best, where = 0.0, None
    for at in range(len(flat.words) - size + 1):
        window = " ".join(flat.words[at : at + size])
        if window[:1] != wanted[:1] and window[-2:] != wanted[-2:]:
            continue
        ratio = difflib.SequenceMatcher(None, wanted, window).ratio()
        if ratio > best:
            best, where = ratio, at
    if where is None or best < ALIKE:
        return None, ""
    return where, flat.printed(where, where + size)


def _affiliation(flat: _Flat, reading: Reading, text: str, used: set[int]) -> Change | None:
    at = _find(flat, text)
    words = _said(text)
    if at is not None:
        used.update(flat.lines[at : at + len(words)])
        return None
    # The stretch of the proof that holds most of its words of four letters or more, as many
    # words as it has and a half: "of" and "and" stand everywhere.
    wanted = {word for word in words if len(word) >= 4} or set(words)
    span = max(len(words) + len(words) // 2, 1)
    best, where = 0, None
    for start in range(max(len(flat.words) - span + 1, 1)):
        held = len(wanted & set(flat.words[start : start + span]))
        if held > best:
            best, where = held, start
    if where is None or best < SHARE * len(wanted):
        return _change(reading, flat, None, "affiliation", text, "", note="not in the proof")
    hits = [k for k in range(where, min(where + span, len(flat.words)))
            if flat.words[k] in wanted]  # fmt: skip
    used.update(flat.lines[hits[0] : hits[-1] + 1])
    return _change(reading, flat, hits[0], "affiliation", text,
                   flat.printed(hits[0], hits[-1] + 1),
                   note="the affiliation is printed otherwise")  # fmt: skip


def _identifiers(flat: _Flat, reading: Reading, authors: list[dict], used: set[int]
                 ) -> list[Change]:  # fmt: skip
    from manuscript_guard.approvals import name_of

    changes = []
    text = flat.text
    # The lines that print an identifier are the title page's, whatever else they say.
    for at, word in enumerate(flat.words):
        if _ORCID.search(word) or _EMAIL.fullmatch(word):
            used.add(flat.lines[at])
    printed = {found.group(0).upper() for found in _ORCID.finditer(text)}
    if printed:
        listed = {str(a.get("orcid") or "").strip().upper(): a for a in authors if a.get("orcid")}
        for orcid, author in listed.items():
            if orcid not in printed:
                changes.append(_change(reading, flat, None, "ORCID iD",
                                       f"{name_of(author)}: {orcid}", "",
                                       note="not in the proof"))  # fmt: skip
        for orcid in sorted(printed - set(listed)):
            changes.append(_change(reading, flat, None, "ORCID iD", "", orcid,
                                   note="the proof prints an ORCID iD no author has"))  # fmt: skip
    emails = {found.group(0).casefold().rstrip(".") for found in _EMAIL.finditer(text)}
    for author in authors:
        email = str(author.get("email") or "").strip().casefold()
        if not author.get("corresponding") or not email:
            continue
        if email in emails:
            continue
        near = difflib.get_close_matches(email, sorted(emails), n=1, cutoff=ALIKE)
        changes.append(_change(reading, flat, None, "e-mail address",
                               f"{name_of(author)}: {email}", near[0] if near else "",
                               note="printed otherwise" if near else "not in the proof",
                               ))  # fmt: skip
    return changes
