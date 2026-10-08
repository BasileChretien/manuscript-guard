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
import re
import shutil
import tempfile
import zipfile
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


class Unavailable(Exception):
    """This reading needs a program that is not installed here. Raised when the reading is
    looked for, so that it is passed over where it cannot be made, on either side."""


def why_not(raised: BaseException) -> str:
    """Why a reading could not be found in the package on the path, as one of two words.

    `absent`: the package has no such reading, or this machine cannot make it. The module
    or the name it is imported from is not in `manuscript_guard`, which is a reading newer
    than the source, or one whose helper was since renamed; or a program it needs is not
    installed. That is passed over.

    `broken`: anything else. A helper that takes other arguments now, a dependency this
    source needs and the installed ones do not include. The source has the reading and
    could not be asked, which is not the same as having nothing to compare, and was taken
    for it: the readings were passed over and the job was green."""
    if isinstance(raised, Unavailable):
        return "absent"
    inside = (getattr(raised, "name", None) or "").split(".")[0] == "manuscript_guard"
    return "absent" if isinstance(raised, ImportError) and inside else "broken"


def answer(read: Reading, given: Any) -> Any:
    """What `read` makes of `given`, as JSON carries it: its answer, or what it raised.
    Through JSON and back, so that a tuple in one process and a list in the other, which is
    what the pipe makes of it, are the same answer."""
    try:
        found = {"answer": read(given)}
    # `SystemExit` with the rest: it is what the command line raises when it refuses its
    # arguments, and let through it ended the process that was answering.
    except (Exception, SystemExit) as raised:  # noqa: BLE001 - what is raised is the answer
        found = {"raised": f"{type(raised).__name__}: {raised}"}
    return json.loads(json.dumps(found, ensure_ascii=True, sort_keys=True))


def _told(report: Any) -> dict[str, Any]:
    """A report as the two sides compare it: every finding with where it points and what it
    says, in the order the gate gave them, and the counts. Each part under its name, so
    that where two answers part can be said in words: `findings[0].line`. The file is one
    of the parts: a finding moved from the manuscript to `paper.yaml` with its line kept
    was no difference."""
    return {
        "findings": [
            {
                "gate": f.gate,
                "path": None if f.path is None else f.path.as_posix(),
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
        # The text the gate hands this reading: without the sections whose wording is
        # somebody else's, where the source has that text.
        read = getattr(file, "spelt", file.printed)
        passage = Passage(file.path, file.text, read, file.line_of)
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


def _from_root(said: Any, root: Path, *, written: str = "<project>") -> Any:
    """`said` with the folder `root` written `<project>` in every text it holds, in each
    way a path to it is spelt. Longest first: the resolved path can hold the other."""
    if isinstance(said, dict):
        return {key: _from_root(value, root, written=written) for key, value in said.items()}
    if isinstance(said, list):
        return [_from_root(value, root, written=written) for value in said]
    if not isinstance(said, str):
        return said
    forms = {str(root), str(root.resolve()), root.as_posix(), root.resolve().as_posix()}
    for form in sorted(forms, key=len, reverse=True):
        said = said.replace(form, written)
    return said


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _changed(before: dict[str, bytes], after: dict[str, bytes]) -> set[str]:
    return {name for name in {*before, *after} if before.get(name) != after.get(name)}


# -------------------------------------------------------------------------- the round trip

#: The word a block of a generated paper is known by. No two blocks have the same one.
TAGS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")
_TABLE = "| Drug | Reports |\n|------|---------|\n| A | 12 |\n| B | 30 |"
#: What each kind of block says, with its own word in it. They read alike on purpose: the
#: wrong writes the reviews found were on papers whose blocks did.
SAYS = {
    "paragraph": "The {tag} reports of hepatic injury were counted once in each group.",
    "second paragraph": "The {tag} reports of hepatic injury are shown below for each group.",
    "heading": "The {tag} reports of hepatic injury",
    "quotation": "The {tag} reports of hepatic injury were counted once in each group.",
    "item": "The {tag} reports of hepatic injury were counted once in each group.",
    "caption": "The {tag} reports of hepatic injury in each group.",
    "lines": "The {tag} reports of hepatic injury were counted once in each group.",
    "div": "The {tag} reports of hepatic injury were counted once in each group.",
}
#: How each kind is typed. Only the first two are given an identifier by the build.
TYPED = {
    "paragraph": "{says}",
    "second paragraph": "{says}",
    "heading": "## {says}",
    "quotation": "> {says}",
    "item": "- {says}",
    "caption": _TABLE + "\n\n: {says}",
    "lines": "| {says}",
    "div": "::: {{.plain}}\n{says}\n:::",
}
#: The word a co-author changes in a block, and what they type for it. In every sentence.
WAS, NOW = "hepatic", "liver"
#: The word the author changes in the source after the build, where they change one.
AUTHOR_WAS, AUTHOR_NOW = "reports", "records"
#: What the author adds to the source after the build, where they add a paragraph.
ADDED = "A paragraph the author added since the build, about the india reports."

_WORD_PARAGRAPH = re.compile(r"<w:p\b.*?</w:p>", re.DOTALL)
_OPENS = re.compile(
    r"<w:p>(?:<w:pPr>.*?</w:pPr>)?(?P<mark>(?:<w:bookmark(?:Start|End)\b[^>]*/>)*)", re.DOTALL
)


def typed(block: dict[str, str]) -> str:
    """One block of a generated paper as it stands in the source."""
    return TYPED[block["kind"]].format(says=SAYS[block["kind"]].format(tag=block["tag"]))


def _edited_in_word(xml: str, in_word: list[list[str]]) -> str:
    """The document's XML after the co-author's session: each block they touched reworded,
    or deleted. A paragraph deleted in Word with Track Changes off leaves its bookmark
    behind, in front of the next paragraph ("deleted"); edited outside Word it goes with
    its bookmark ("deleted and gone"). The two are one document where there is no bookmark
    to leave or nowhere to leave it: for a block that has no identifier, and for the last
    paragraph of the document, whose bookmark is dropped here. What Word does with that
    last one has not been looked at."""
    for tag, did in in_word:
        paragraph = next(p for p in _WORD_PARAGRAPH.findall(xml) if f" {tag} " in p)
        at = xml.index(paragraph)
        if did == "reworded":
            xml = xml[:at] + paragraph.replace(WAS, NOW, 1) + xml[at + len(paragraph) :]
            continue
        xml = xml[:at] + xml[at + len(paragraph) :]
        opening = _OPENS.match(paragraph)
        following = xml.find("<w:p>", at)
        if did == "deleted" and opening and opening["mark"] and following != -1:
            into = _OPENS.match(xml, following)
            xml = xml[: into.start("mark")] + opening["mark"] + xml[into.start("mark") :]
    return xml


@reading("import")
def _import() -> Reading:
    if shutil.which("pandoc") is None:
        raise Unavailable("pandoc is not installed, and a document is built with it")
    from manuscript_guard.cli import main
    from manuscript_guard.scaffold import init_project

    def round_trip(given: dict[str, Any]) -> dict[str, Any]:
        """A paper typed into a new project, built, edited in Word, and imported: the
        source as the import found it, as it left it, and what was said.

        `blocks` are the paper, `in_word` what the co-author did to which block, and
        `since` what the author did to the source after the build, if anything; with a
        change since, the import is forced, as a stale one has to be."""
        folder = Path(tempfile.mkdtemp(prefix="mg-reading-"))
        try:
            root = folder / "paper"
            init_project(root, "A study of reports")
            path = root / MAIN
            header = path.read_text(encoding="utf-8")
            header = header[: header.index("\n---\n") + len("\n---\n")]

            def write(blocks: list[str]) -> None:
                text = header + "\n" + "\n\n".join(blocks) + "\n"
                path.write_text(text, encoding="utf-8", newline="\n")

            built = [typed(block) for block in given["blocks"]]
            now = list(built)
            if given.get("since"):
                did, tag = given["since"]
                at = next(i for i, block in enumerate(given["blocks"]) if block["tag"] == tag)
                if did == "reworded":
                    now[at] = now[at].replace(AUTHOR_WAS, AUTHOR_NOW, 1)
                elif did == "removed":
                    del now[at]
                else:
                    now.insert(at, ADDED)

            said = StringIO()
            write(built)
            with redirect_stdout(said), redirect_stderr(said):
                code = main(["build", str(root), "--offline", "--skip-checks"])
                if code != 0:
                    return {"built": code, "said": _named(said.getvalue(), root, folder)}
                (document,) = (root / "build").glob("manuscript*.docx")
                returned = folder / "returned.docx"
                with zipfile.ZipFile(document) as sent, zipfile.ZipFile(returned, "w") as back:
                    for item in sent.infolist():
                        data = sent.read(item.filename)
                        if item.filename == "word/document.xml":
                            xml = _edited_in_word(data.decode("utf-8"), given["in_word"])
                            data = xml.encode("utf-8")
                        back.writestr(item, data)
                write(now)
                before = path.read_text(encoding="utf-8")
                forced = ["--force"] if now != built else []
                code = main(["import", str(returned), str(root), "--apply", *forced])
            found = {
                "exit": code,
                "before": before,
                "after": path.read_text(encoding="utf-8"),
                "said": _named(said.getvalue(), root, folder),
            }
            if folder.name in json.dumps(found):
                raise AssertionError(
                    "the import printed the folder made for this run in a form this reading "
                    "does not know, so two runs of it could not be compared"
                )
            return found
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return round_trip


def _named(said: str, root: Path, folder: Path) -> str:
    return _from_root(_from_root(said, root), folder, written="<folder>")


# ------------------------------------------------------------------- as a process of its own


def serve() -> None:
    """Answer for the package on the path until the questions end: a line of JSON in, a
    line of JSON out. The first line out says which package was found, which readings it
    does not have and which it has and cannot make (`why_not`), so that whoever asks can
    refuse an answer from the wrong source and tell nothing to compare from a comparison
    that could not be made.

    Answers go to the standard output as it was when the process began. Everything a
    reading prints after that goes to the standard error, where it cannot be taken for one.
    """
    import os
    import sys

    answers = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="ascii", newline="\n")
    sys.stdout = sys.stderr

    import manuscript_guard

    found: dict[str, Reading] = {}
    lacking: dict[str, dict[str, str]] = {"absent": {}, "broken": {}}
    for name, find in READINGS.items():
        try:
            found[name] = find()
        except Exception as raised:  # noqa: BLE001 - told apart by `why_not`
            lacking[why_not(raised)][name] = f"{type(raised).__name__}: {raised}"

    def say(told: dict[str, Any]) -> None:
        answers.write(json.dumps(told, ensure_ascii=True, sort_keys=True) + "\n")
        answers.flush()

    say({"package": str(Path(manuscript_guard.__file__).resolve().parent), **lacking})
    for line in sys.stdin.buffer:
        asked = json.loads(line)
        name = asked["reading"]
        if name in found:
            say(answer(found[name], asked["given"]))
        elif name in lacking["broken"]:
            say({"broken": lacking["broken"][name]})
        else:
            say({"absent": lacking["absent"].get(name, "no reading has that name")})


if __name__ == "__main__":
    serve()
