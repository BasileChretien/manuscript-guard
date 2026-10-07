"""The readings a generated input is put to, each under a name.

A reading is one way the package reads text, taken at the widest door it has: the function
a gate calls on a whole file, not a helper inside it. Each takes something JSON can carry
and gives back something JSON can carry, because the same input is read in two processes
and the two answers are compared: the working tree's beside the base branch's
(`tests/test_differential.py`), and the working tree's beside its own under another hash
seed. `tests/test_properties.py` reads through them too, so a reading added here is held to
the invariants and compared with the base from the day it is written.

**This file is run against two versions of the package**, so it imports nothing from it at
the top. A reading is registered as a function that does the importing and returns the
function that does the reading. Where the first fails, the package it was asked of has no
such reading: a module or a name that is not there yet, in a base older than the reading.
That is said and passed over. Where the second raises, the reading failed on that input,
and what it raised is its answer, to be compared like any other.

A reading that calls a helper by a private name (`_hidden`, `_file`, `_judge`) is tied to
that name. A pull request that renames one changes the reading here, and the base then has
no such reading until the rename is merged.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

Reading = Callable[[Any], Any]

#: Every reading by its name, as the function that finds it in the package on the path.
READINGS: dict[str, Callable[[], Reading]] = {}

MAIN = Path("manuscript") / "main.md"
PAPER = Path("paper.yaml")


def reading(name: str) -> Callable[[Callable[[], Reading]], Callable[[], Reading]]:
    def register(find: Callable[[], Reading]) -> Callable[[], Reading]:
        if name in READINGS:
            raise ValueError(f"two readings are named {name!r}")
        READINGS[name] = find
        return find

    return register


def answer(read: Reading, given: Any) -> Any:
    """What `read` makes of `given`, as JSON carries it: its answer, or what it raised.
    Through JSON and back, so that a tuple in one process and a list in the other, which is
    what the pipe makes of it, are the same answer."""
    try:
        found = {"answer": read(given)}
    except Exception as raised:  # noqa: BLE001 - what a reading raises is its answer
        found = {"raised": f"{type(raised).__name__}: {raised}"}
    return json.loads(json.dumps(found, ensure_ascii=True, sort_keys=True))


def _told(report: Any) -> dict[str, Any]:
    """A report as the two sides compare it: every finding with where it points and what it
    says, in the order the gate gave them, and the counts. Each part under its name, so
    that where two answers part can be said in words: `findings[0].line`."""
    return {
        "findings": [
            {
                "gate": f.gate,
                "code": f.code,
                "severity": f.severity,
                "message": f.message,
                "line": f.line,
                "col": f.col,
                "context": f.context,
                "hint": f.hint,
            }
            for f in report.findings
        ],
        "counts": dict(report.counts),
    }


# ------------------------------------------------------------------------------ hiding


@reading("mask")
def _mask() -> Reading:
    from manuscript_guard.text.masking import mask

    return mask


@reading("hidden")
def _hidden() -> Reading:
    from manuscript_guard.gates.language import _hidden as hidden

    return hidden


@reading("own words")
def _own_words() -> Reading:
    from manuscript_guard.gates.language import _hidden as hidden
    from manuscript_guard.gates.vocabulary import own_words

    return lambda text: own_words(hidden(text))


@reading("spans")
def _spans() -> Reading:
    from manuscript_guard.text.comments import comment_spans
    from manuscript_guard.text.fences import fenced_spans
    from manuscript_guard.text.inline import (
        code_spans,
        definition_spans,
        equation_spans,
        link_text_spans,
    )
    from manuscript_guard.text.masking import (
        front_matter_end,
        html_comments,
        mask,
        metadata_blocks,
    )

    def spans(text: str) -> dict[str, Any]:
        masked = mask(text)
        code = code_spans(masked)
        return {
            "front matter": front_matter_end(text),
            "metadata": metadata_blocks(text),
            "fences": [
                {"start": f.start, "body": [f.body_start, f.body_end], "end": f.end, "info": f.info}
                for f in fenced_spans(text)
            ],
            "comments": comment_spans(text),
            "hidden comments": html_comments(text),
            "code": code,
            "equations": equation_spans(masked, code),
            "link text": link_text_spans(text),
            "definitions": definition_spans(text),
        }

    return spans


@reading("sections")
def _sections() -> Reading:
    from manuscript_guard.text.sections import footnote_index, heading_index, split_sections

    def sections(text: str) -> dict[str, Any]:
        return {
            "breaks": [
                {"start": h.start, "level": h.level, "title": h.title, "setext": h.setext}
                for h in heading_index(text)
            ],
            "sections": [
                {"title": s.title, "level": s.level, "line": s.line, "body": s.body,
                 "enclosed": s.enclosed}
                for s in split_sections(text)
            ],  # fmt: skip
            "notes": [
                {"start": n.start, "end": n.end, "references": list(n.references)}
                for n in footnote_index(text)
            ],
        }

    return sections


# ----------------------------------------------------------------------------- numbers


@reading("numbers")
def _numbers() -> Reading:
    from manuscript_guard.classify import Classifier
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
    from manuscript_guard.text.tokens import find_atoms

    def numbers(given: dict[str, Any]) -> list[dict[str, Any]]:
        """Every atom G2 finds in the text, as `check_numbers` judges it: where it stands,
        under which headings, and by which rule it is let through or not."""
        text = given["text"]
        classifier = Classifier.load((), tuple(given.get("terms", ())))
        headings, notes = heading_index(text), footnote_index(text)
        scan = classifier.scan(text)
        found = []
        for atom in find_atoms(text, mask(text)):
            chains = chains_at(headings, notes, atom.start)
            verdict = classifier.classify_under(atom, chains, scan)
            found.append(
                {
                    "text": atom.text,
                    "at": [atom.start, atom.end],
                    "line": atom.line,
                    "col": atom.col,
                    "under": list(chains),
                    "verdict": verdict.kind,
                    "rule": verdict.rule,
                    "terms": list(verdict.terms),
                }
            )
        return found

    return numbers


# ---------------------------------------------------------------------------- language


def _file(text: str) -> Any:
    from manuscript_guard.gates.language import _file as read

    return read(0, MAIN, text, [], False)


@reading("vocabulary")
def _vocabulary() -> Reading:
    from manuscript_guard.gates.vocabulary import Passage, judge_vocabulary

    def vocabulary(given: dict[str, Any]) -> dict[str, Any]:
        file = _file(given["text"])
        passage = Passage(file.path, file.text, file.printed, file.line_of)
        return _told(judge_vocabulary([passage], given["entries"], PAPER))

    _file("")  # the door this reading goes through is part of what it needs
    return vocabulary


@reading("spelling")
def _spelling() -> Reading:
    from manuscript_guard.gates.spelling import judge_spelling
    from manuscript_guard.gates.vocabulary import Passage

    def spelling(given: dict[str, Any]) -> dict[str, Any]:
        file = _file(given["text"])
        passage = Passage(file.path, file.text, file.printed, file.line_of)
        return _told(judge_spelling([passage], given["variant"], given["accepted"], PAPER))

    _file("")
    return spelling


@reading("abbreviations")
def _abbreviations() -> Reading:
    from manuscript_guard.gates.language import _judge, _Known, _shipped

    def abbreviations(given: dict[str, Any]) -> dict[str, Any]:
        exact, lowered = _shipped()
        known = _Known(exact | set(given.get("known", ())), lowered)
        return _told(_judge([_file(given["text"])], known, Path(".")))

    _file("")
    return abbreviations


# ------------------------------------------------------------------- titles and quotes


@reading("tex outside maths")
def _tex() -> Reading:
    from manuscript_guard.text.tex import tex_outside_maths

    def tex(line: str) -> list[Any] | None:
        found = tex_outside_maths(line)
        return None if found is None else list(found)

    return tex


@reading("title")
def _title() -> Reading:
    from manuscript_guard.contracts.project import outside_maths

    return lambda line: [outside_maths(line), outside_maths(line, keyword=True)]


@reading("quotation")
def _quotation() -> Reading:
    from manuscript_guard.literature.sources import contains, normalise, states_value

    def quotation(given: dict[str, str]) -> dict[str, Any]:
        source, quote, value = given["source"], given["quote"], given["value"]
        return {
            "read as": normalise(source),
            "found": contains(source, quote),
            "states": states_value(quote, value),
        }

    return quotation


# -------------------------------------------------------------------- a whole project


@reading("check")
def _check() -> Reading:
    from manuscript_guard.cli import main
    from manuscript_guard.scaffold import init_project

    def check(given: dict[str, Any]) -> dict[str, Any]:
        """`check --json` on a new project with this manuscript and these settings typed
        into it. What it prints names files under a folder made for this one run, which
        is written `<project>` here, so that two runs say the same thing."""
        folder = Path(tempfile.mkdtemp(prefix="mg-reading-"))
        try:
            root = folder / "paper"
            init_project(root, "A study of reports")
            (root / MAIN).write_text(given["text"], encoding="utf-8", newline="")
            with (root / PAPER).open("a", encoding="utf-8", newline="") as paper:
                paper.write(given.get("settings", ""))
            before = _snapshot(root)
            printed, complaints = StringIO(), StringIO()
            with redirect_stdout(printed), redirect_stderr(complaints):
                code = main(
                    ["check", str(root), "--json", "--stage", given.get("stage", "design")]
                )
            # A `paper.yaml` that cannot be read ends the command with a sentence and
            # prints no report: nothing to parse, and that is its answer.
            said = json.loads(printed.getvalue()) if printed.getvalue().strip() else None
            found = {
                "exit": code,
                "said": _from_root(said, root),
                "complained": _from_root(complaints.getvalue(), root),
                "written": sorted(_changed(before, _snapshot(root))),
            }
            if folder.name in json.dumps(found):
                raise AssertionError(
                    "`check` printed the folder made for this run in a form this reading "
                    "does not know, so two runs of it could not be compared"
                )
            return found
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return check


def _from_root(said: Any, root: Path) -> Any:
    """`said` with the project's folder written `<project>` in every text it holds, in
    each way a path to it is spelt. Longest first: the resolved path can hold the other."""
    if isinstance(said, dict):
        return {key: _from_root(value, root) for key, value in said.items()}
    if isinstance(said, list):
        return [_from_root(value, root) for value in said]
    if not isinstance(said, str):
        return said
    forms = {str(root), str(root.resolve()), root.as_posix(), root.resolve().as_posix()}
    for form in sorted(forms, key=len, reverse=True):
        said = said.replace(form, "<project>")
    return said


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {name for name in {*before, *after} if before.get(name) != after.get(name)}


# ------------------------------------------------------------------- as a process of its own


def serve() -> None:
    """Answer for the package on the path until the questions end: a line of JSON in, a
    line of JSON out. The first line out says which package was found and which readings
    it has no door for, so that whoever asks can refuse an answer from the wrong source.

    Answers go to the standard output as it was when the process began. Everything a
    reading prints after that goes to the standard error, where it cannot be taken for one.
    """
    import os
    import sys

    answers = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="ascii", newline="\n")
    sys.stdout = sys.stderr

    import manuscript_guard

    found: dict[str, Reading] = {}
    absent: dict[str, str] = {}
    for name, find in READINGS.items():
        try:
            found[name] = find()
        except Exception as raised:  # noqa: BLE001 - an older package lacks a newer door
            absent[name] = f"{type(raised).__name__}: {raised}"

    def say(told: dict[str, Any]) -> None:
        answers.write(json.dumps(told, ensure_ascii=True, sort_keys=True) + "\n")
        answers.flush()

    say({"package": str(Path(manuscript_guard.__file__).resolve().parent), "absent": absent})
    for line in sys.stdin.buffer:
        asked = json.loads(line)
        name = asked["reading"]
        if name in found:
            say(answer(found[name], asked["given"]))
        else:
            say({"absent": absent.get(name, "no reading has that name")})


if __name__ == "__main__":
    serve()
