"""Was the manuscript only reworded?

A language pass is trusted with the words: a co-author tidying a paragraph, an editing
service, a model asked to make the English read well. What it is not trusted with is what the
words are about. And that is where `check` is blind, because `check` reads the manuscript as
it is. An edit that puts `{{results.ror.lower}}` where `{{results.ror.upper}}` stood leaves two
bindings that resolve; one that drops `[@lee2019]` leaves a sentence with one citation fewer;
one that retypes a dose leaves a number the conventions allow as readily as the last. Every
gate passes, and the paper says something else.

So this compares the text with what it was, and holds three things to their places: every
binding, every citation key and every typed number. The words between them are free.

- One that is **gone, new or changed** fails. Either the edit was more than a rewording, and
  whoever reads it should know, or it was a slip.
- The same ones **in another order** pass with a warning that shows the place. A clause
  moved to the front of its sentence does that and is harmless; so do two values that changed
  places, which is not. No rule tells the two apart, so a person is shown both.

A number is compared as it is typed. "3" spelt out as "three", "1,200" closed up to "1200"
and "0.50" cut to "0.5" are each reported: the first two may be a matter of style, the third
is not, and nothing here guesses which. What a language edit does to the notation around a
number is free: the space before a unit or a per cent sign, the spaces around a sign of
comparison, a hyphen made a true minus sign.

The text before is the last commit's, or any commit's, or a copy somebody kept. It is a
command and no gate: `check` has one text and this needs two.

What it does not hold is in DESIGN.md's Known gaps: a unit, a sign of comparison, a "not",
"increased" for "decreased". Those are words, and reading them is a reviewer's work.
"""

from __future__ import annotations

import re
import subprocess
from bisect import bisect_left
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import load_project
from manuscript_guard.findings import FAIL, WARN, Finding, Report, merge_all
from manuscript_guard.gates.numbers import SOURCE_GLOB, source_files
from manuscript_guard.text.masking import blank_comments, fenced_blocks, mask
from manuscript_guard.text.placeholders import NAMESPACES, PLACEHOLDER
from manuscript_guard.text.tokens import _ENCLOSED, _FRACTIONS
from manuscript_guard.zotero.citations import find_citations

GATE = "REWORDED"

BINDING = "binding"
CITATION = "citation"
NUMBER = "number"

#: The signs a number is typed with. A hyphen, a true minus sign and an en dash are one
#: sign: making the first into the second is a language edit.
_MINUS = "-\N{MINUS SIGN}\N{EN DASH}"
#: After these a dash joins two things and is no sign: a letter or a figure, a closing
#: bracket, a per cent or a degree sign, and a bound value, which the mask has blanked:
#: "IL-6", "1.2-3.4", "80%-93%", "{{low}}-3". After anything else it is the sign of the
#: number it stands against: a space, an opening bracket, a sign of comparison, a mark
#: of emphasis. Said this way round so that a character nobody listed, an arrow or an
#: "about" sign, leaves the number its sign: read the other way, rewording "about -0.3"
#: with such a character took the sign off and reported a number changed.
_JOINS = r"(?<![^\W_])(?<![)\]}%\N{DEGREE SIGN}\x00])"
#: A number as it is typed: figures, with commas between groups of three and one decimal
#: point. "0,5" is two numbers here and "1,2,3" three, so that a space typed after a comma
#: changes nothing; a fraction or an enclosed figure is one by itself.
_NUMBER = re.compile(
    "(?:" + _JOINS + "(?P<sign>[" + _MINUS + "+]))?"
    r"(?P<figures>\d+(?:,\d{3}(?!\d))*(?:[.\N{MIDDLE DOT}]\d+)?|[" + _FRACTIONS + _ENCLOSED + "])"
)

#: How many lines or facts a message lists before it says how many more there are.
SHOWN = 6
#: How long git may take to answer. It reads one file or lists one folder.
GIT_SECONDS = 30


class NoBefore(Exception):
    """The text before the edit could not be had. The message is written for the author."""


@dataclass(frozen=True)
class Fact:
    """One thing a rewording leaves alone, and where it stands."""

    kind: str
    #: What is compared: a binding's name, a citation's key, a number as typed.
    text: str
    start: int
    line: int

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.text

    @property
    def shown(self) -> str:
        if self.kind == BINDING:
            return "{{" + self.text + "}}"
        if self.kind == CITATION:
            return "@" + self.text
        return f"'{self.text}'"


def _numbers_in(text: str) -> str:
    """`text` with everything blanked that prints no number of the author's: comments, the
    keys of the front matter, bindings, citation keys, addresses. A listing is printed, so
    it is put back: `mask` hides one because G2 reads it by other rules."""
    hidden = mask(text)
    parts: list[str] = []
    position = 0
    for fence in sorted(fenced_blocks(text), key=lambda found: found.start):
        if fence.start < position:
            continue
        parts += [hidden[position : fence.start], text[fence.start : fence.end]]
        position = fence.end
    parts.append(hidden[position:])
    return "".join(parts)


def facts(text: str) -> list[Fact]:
    """Every binding, citation key and typed number of a manuscript file, in the order they
    stand."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    breaks = [found.start() for found in re.finditer("\n", text)]

    def fact(kind: str, held: str, start: int) -> Fact:
        return Fact(kind, held, start, bisect_left(breaks, start) + 1)

    # What pandoc drops holds no binding and no citation. The bindings are the ones
    # `placeholders.parse` calls well formed, found here without its line of each, which it
    # counts from the top of the file every time.
    printed = blank_comments(text) if "<!--" in text else text
    found = [
        fact(BINDING, f"{binding['ns']}.{binding['key']}", binding.start())
        for binding in PLACEHOLDER.finditer(printed)
        if binding["ns"] in NAMESPACES
    ]
    found += [fact(CITATION, use.citekey, use.start) for use in find_citations(printed, Path())]
    for number in _NUMBER.finditer(_numbers_in(text)):
        sign = number["sign"] or ""
        held = ("-" if sign and sign in _MINUS else sign) + number["figures"]
        found.append(fact(NUMBER, held, number.start()))
    return sorted(found, key=lambda one: one.start)


# ------------------------------------------------------------------------ the comparison


def _times(count: int) -> str:
    return {1: "once", 2: "twice"}.get(count, f"{count} times")


def _listed(items: Sequence[str]) -> str:
    """"a", "a and b", "a, b and c", and past `SHOWN` of them how many more."""
    shown = list(items[:SHOWN])
    if len(items) > SHOWN:
        shown.append(f"{len(items) - SHOWN} more")
    if len(shown) < 2:
        return "".join(shown)
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def _lines(found: Sequence[Fact]) -> str:
    # A line that holds it twice is named once: the count is in the sentence already.
    lines = [str(line) for line in dict.fromkeys(fact.line for fact in found)]
    return ("line " if len(lines) == 1 else "lines ") + _listed(lines)


_PUT_BACK = (
    "put it back as it stood; if the change is meant, it is a change to the paper and no "
    "rewording"
)


def _lost(fact: Fact, before: Sequence[Fact], now: int, path: Path | None) -> Finding:
    what = f"the {fact.kind} {fact.shown}"
    if now == 0 and len(before) == 1:
        message = f"{what} is gone: it stood on {_lines(before)} before the edit"
    elif now == 0:
        message = (
            f"{what} is gone: it stood {_times(len(before))} before the edit, on {_lines(before)}"
        )
    else:
        message = (
            f"{what} stood {_times(len(before))} before the edit, on {_lines(before)}, and "
            f"stands {_times(now)} now"
        )
    return Finding(GATE, "fact-lost", message, FAIL, path, hint=_PUT_BACK)


def _new(fact: Fact, after: Sequence[Fact], was: int, path: Path | None, line: int) -> Finding:
    what = f"the {fact.kind} {fact.shown}"
    if was == 0 and len(after) == 1:
        message = f"{what} is new: it did not stand in the text before the edit"
    elif was == 0:
        message = (
            f"{what} is new: it did not stand in the text before the edit, and stands "
            f"{_times(len(after))} now, on {_lines(after)}"
        )
    else:
        message = (
            f"{what} stands {_times(len(after))} now, on {_lines(after)}, and stood "
            f"{_times(was)} before the edit"
        )
    return Finding(GATE, "fact-new", message, FAIL, path, line, hint=_PUT_BACK)


def _untouched(before: Sequence[Fact], after: Sequence[Fact]) -> tuple[int, int]:
    """How many facts the two texts open with in common, and how many they close with."""
    shorter = min(len(before), len(after))
    head = 0
    while head < shorter and before[head].key == after[head].key:
        head += 1
    tail = 0
    while tail < shorter - head and before[-1 - tail].key == after[-1 - tail].key:
        tail += 1
    return head, tail


def _reordered(before: Sequence[Fact], after: Sequence[Fact]) -> list[tuple[int, int]]:
    """Where the same facts stand in another order: each stretch, as far as it has to reach
    for the two texts to hold the same facts again. The stretches do not overlap, and a
    clause moved in one sentence is told apart from one moved in the next.

    Read once, with a count of what one text has had that the other has not: a comparison
    that lined the texts up fact by fact would take the square of a manuscript's length."""
    stretches: list[tuple[int, int]] = []
    owed: Counter[tuple[str, str]] = Counter()
    unsettled = 0
    start = 0
    for index, (was, now) in enumerate(zip(before, after, strict=True)):
        for key, step in ((was.key, 1), (now.key, -1)):
            count = owed[key]
            owed[key] = count + step
            unsettled += (count + step != 0) - (count != 0)
        if unsettled == 0:
            if index > start:
                stretches.append((start, index + 1))
            start = index + 1
    return stretches


def _moved(before: Sequence[Fact], after: Sequence[Fact], path: Path | None) -> Finding:
    return Finding(
        GATE,
        "order-changed",
        "the same bindings, citations and numbers stand here in another order: before the "
        f"edit {_listed_plain(before)}; now {_listed_plain(after)}",
        WARN,
        path,
        after[0].line,
        hint="a clause that moved does this and nothing is wrong; if two values changed "
        "places, put them back",
    )


def _listed_plain(found: Sequence[Fact]) -> str:
    shown = [fact.shown for fact in found[:SHOWN]]
    if len(found) > SHOWN:
        shown.append(f"and {len(found) - SHOWN} more")
    return ", ".join(shown)


def compare(before: str, after: str, path: Path | None = None) -> Report:
    """What an edit did to the bindings, the citations and the typed numbers of one file.

    The counts are of the text as it is now."""
    was, now = facts(before), facts(after)
    stood: dict[tuple[str, str], list[Fact]] = {}
    stands: dict[tuple[str, str], list[Fact]] = {}
    for found, into in ((was, stood), (now, stands)):
        for fact in found:
            into.setdefault(fact.key, []).append(fact)

    findings = [
        _lost(held[0], held, len(stands.get(key, ())), path)
        for key, held in stood.items()
        if len(held) > len(stands.get(key, ()))
    ]
    # Where a fact stands more often than it did, which of them is the new one is not known
    # from the facts alone. The finding is placed at the first that lies past what the two
    # texts open with in common and before what they close with: after one edit that is the
    # one. The message gives every line.
    head, tail = _untouched(was, now)
    first, last = 0, -1
    if head + tail < len(now):
        first, last = now[head].start, now[len(now) - tail - 1].start
    for key, held in stands.items():
        if len(held) > len(stood.get(key, ())):
            between = [fact for fact in held if first <= fact.start <= last]
            line = (between or held)[0].line
            findings.append(_new(held[0], held, len(stood.get(key, ())), path, line))
    if not findings:
        # With one gone there is no saying which of the rest moved: the loss is told, and
        # the order once the loss is settled.
        findings = [
            _moved(was[start:end], now[start:end], path) for start, end in _reordered(was, now)
        ]
    kinds = Counter(fact.kind for fact in now)
    return Report(tuple(findings)).with_counts(
        reworded_files=1,
        reworded_bindings=kinds[BINDING],
        reworded_citations=kinds[CITATION],
        reworded_numbers=kinds[NUMBER],
    )


def _alone(text: str, path: Path, *, gone: bool, since: str) -> Report:
    """A file one of the two texts lacks. Every fact in it is gone or new with it, and a
    file of words alone is only told."""
    found = facts(text)
    kinds = Counter(fact.kind for fact in found)
    counts = {
        "reworded_files": 1,
        "reworded_bindings": kinds[BINDING],
        "reworded_citations": kinds[CITATION],
        "reworded_numbers": kinds[NUMBER],
    }
    if gone:
        code, said, holds = "file-lost", "this file is gone", "held"
        counts = dict.fromkeys(counts, 0)
    else:
        code, said, holds = "file-new", f"this file is new since {since}", "holds"
    if len(found) == 1:
        message, severity = f"{said}, and 1 binding, citation or number with it", FAIL
    elif found:
        message = f"{said}, and {len(found)} bindings, citations and numbers with it"
        severity = FAIL
    else:
        message, severity = f"{said}; it {holds} no binding, citation or number", WARN
    return Report((Finding(GATE, code, message, severity, path),)).with_counts(**counts)


# ---------------------------------------------------------------- where the text before is


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    """Git, asked one thing. The file watcher is off: on a machine that turns it on, git
    can wait on it for ever, and nothing here is worth a watcher."""
    command = ["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=false", *args]
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, timeout=GIT_SECONDS, check=False
        )
    except FileNotFoundError as exc:
        raise NoBefore(
            "git is not installed, and the text before the edit is read from a commit; "
            "or name a copy of it: `manuscript-guard reworded FILE --before COPY`"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise NoBefore(f"git did not answer within {GIT_SECONDS} seconds in {cwd}") from exc
    except OSError as exc:
        raise NoBefore(f"git could not be run in {cwd}: {exc.strerror or exc}") from exc


def _commit(cwd: Path, since: str) -> str:
    """The commit `since` names, as git knows it."""
    if since.startswith("-"):
        raise NoBefore(f"'{since}' is no revision: a revision does not begin with a dash")
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0 or inside.stdout.strip() != b"true":
        raise NoBefore(
            f"{cwd} is not in a git repository, and the text before the edit is read from a "
            "commit; or name a copy of it: `manuscript-guard reworded FILE --before COPY`"
        )
    found = _git(cwd, "rev-parse", "--verify", "--quiet", since + "^{commit}")
    if found.returncode != 0:
        if since == "HEAD":
            raise NoBefore(f"the repository of {cwd} has no commit yet to compare with")
        raise NoBefore(f"git knows no commit named '{since}'")
    return found.stdout.decode("ascii", "replace").strip()


def _decoded(data: bytes, what: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NoBefore(f"{what} is not UTF-8, so it cannot be compared") from exc


def _at(commit: str, cwd: Path, name: str, since: str) -> str | None:
    """The file `name`, a path under `cwd` with forward slashes, as `commit` has it. None
    where the commit has no such file."""
    found = _git(cwd, "cat-file", "blob", f"{commit}:./{name}")
    if found.returncode != 0:
        return None
    return _decoded(found.stdout, f"{name} at {since}")


def _read(path: Path) -> bool:
    """Is this a file the gates read: Markdown, in no folder set aside by its name?"""
    return path.match(SOURCE_GLOB) and not any(part.startswith((".", "_")) for part in path.parts)


def _names_at(commit: str, root: Path, folder: str) -> list[str]:
    """The manuscript files `commit` has under `folder`, as paths under `root`."""
    found = _git(root, "ls-tree", "-r", "-z", "--name-only", commit, "--", f"./{folder}")
    if found.returncode != 0:
        return []
    names = _decoded(found.stdout, "a file name in the commit").split("\0")
    inside = len(Path(folder).parts)
    return sorted(
        name for name in names if name and _read(Path(*Path(name).parts[inside:]))
    )


@dataclass(frozen=True)
class Outcome:
    report: Report
    #: What the paths in the report are shown under.
    root: Path
    #: What the text was compared with, in words.
    against: str


def _one(name: str, cwd: Path, commit: str, since: str) -> Report:
    """One file, a path under `cwd`, against the same file in `commit`."""
    path = cwd / name
    before = _at(commit, cwd, name, since)
    if not path.is_file():
        if before is None:
            raise NoBefore(f"{path} does not exist, now or at {since}")
        return _alone(before, path, gone=True, since=since)
    after = read_text(path)
    if before is None:
        return _alone(after, path, gone=False, since=since)
    return compare(before, after, path)


def against_commit(paths: Sequence[Path], since: str) -> Outcome:
    """Each of `paths` against the commit `since`: a file by itself, a folder as the project
    it lies in, with every manuscript file that project has or had."""
    reports: list[Report] = []
    root: Path | None = None
    described = ""
    for given in paths:
        given = given.resolve()
        if given.is_dir():
            project, _ = load_project(given)
            cwd = project.root
            try:
                folder = project.path("manuscript").relative_to(cwd).as_posix()
            except ValueError as exc:
                raise NoBefore(
                    f"the manuscript folder {project.path('manuscript')} is not under the "
                    f"project {cwd}, so it is not compared as one; name its files"
                ) from exc
        elif given.parent.is_dir():
            cwd, folder = given.parent, None
        else:
            raise NoBefore(f"{given} does not exist")
        commit = _commit(cwd, since)
        described = described or (
            f"the last commit ({commit[:8]})" if since == "HEAD" else f"{since} ({commit[:8]})"
        )
        root = root or cwd
        if folder is None:
            reports.append(_one(given.name, cwd, commit, since))
            continue
        now = [path.relative_to(cwd).as_posix() for path in source_files(cwd / folder)]
        for name in sorted({*now, *_names_at(commit, cwd, folder)}):
            reports.append(_one(name, cwd, commit, since))
    return Outcome(merge_all(reports), root or Path.cwd(), described)


def against_copy(after: Path, before: Path) -> Outcome:
    """One file against a copy of what it was."""
    for path in (after, before):
        if not path.is_file():
            raise NoBefore(f"{path} is not a file" if path.exists() else f"{path} does not exist")
    report = compare(read_text(before), read_text(after), after)
    return Outcome(report, Path.cwd(), str(before))
