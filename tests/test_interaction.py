"""What the feature-interaction sweep found.

Each feature was built and tested alone. These are the failures that only appear when two
are used together, which is how a paper is actually written.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

import pytest

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def edited_docx(source: Path, target: Path, was: str, now: str, *, occurrence: int) -> Path:
    """A co-author editing ONE occurrence of a repeated sentence, counting from 1."""
    with zipfile.ZipFile(source) as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                at = -1
                for _ in range(occurrence):
                    at = xml.find(was, at + 1)
                    assert at >= 0, f"occurrence {occurrence} of {was!r} not in the document"
                xml = xml[:at] + now + xml[at + len(was) :]
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    return target


@needs_pandoc
def test_an_edit_lands_in_the_paragraph_it_came_from(project: Path, tmp_path: Path) -> None:
    """The merge matched by text, so it rewrote the *first* paragraph reading that way.

    A limitation restated in the Abstract and again in the Discussion is ordinary in a
    paper. An edit to the second copy silently rewrote the first and left the second alone:
    two corruptions, nothing reported, after the paragraph identifier had been established
    precisely so nothing had to be guessed.
    """
    from manuscript_guard.cli import main

    path = project / "manuscript" / "main.md"
    twice = "This limitation is stated in two places."
    text = path.read_text(encoding="utf-8")
    text = text.replace("# Introduction\n", f"# Introduction\n\n{twice}\n", 1)
    text = text.replace("# Discussion\n", f"# Discussion\n\n{twice}\n", 1)
    path.write_text(text, encoding="utf-8")

    assert main(["build", str(project), "--offline"]) == 0
    returned = edited_docx(
        project / "build" / "manuscript.docx",
        tmp_path / "back.docx",
        twice,
        "This limitation is stated in two places, as the reviewer noted.",
        occurrence=2,
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0

    after = path.read_text(encoding="utf-8")
    intro, _, discussion = after.partition("# Discussion")
    assert twice in intro, "the Introduction copy must be untouched"
    assert "as the reviewer noted" in discussion, "the Discussion copy is the one that changed"
    assert "as the reviewer noted" not in intro, "the wrong paragraph was rewritten"


@needs_pandoc
def test_import_says_how_much_it_could_not_look_at(project: Path, tmp_path: Path) -> None:
    """Only paragraphs carrying an identifier are compared. Table cells, headings, captions
    and anything newly written are invisible — and saying nothing let a co-author believe
    they had corrected a table when the correction went nowhere."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = shutil.copy(project / "build" / "manuscript.docx", tmp_path / "back.docx")

    import io
    import sys

    captured = io.StringIO()
    saved, sys.stdout = sys.stdout, captured
    try:
        main(["import", str(returned), str(project)])
    finally:
        sys.stdout = saved

    out = captured.getvalue()
    assert "carry no identifier" in out, out
    assert re.search(r"\d+ of \d+ paragraphs", out), out


@needs_pandoc
def test_respond_refuses_an_out_of_date_document_like_import_does(
    project: Path, tmp_path: Path
) -> None:
    """One command called the document dangerous while the other baked its anchors into the
    revision record without a word — recording a baseline describing two manuscripts."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = shutil.copy(project / "build" / "manuscript.docx", tmp_path / "old.docx")

    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA later paragraph.\n", encoding="utf-8")

    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 1
    assert not (project / "revision" / "round-1.yaml").exists()

    # --force is the deliberate escape, same as import's.
    assert main(["respond", str(project), "--open", "--from", str(returned), "--force"]) == 0


def test_no_hint_names_a_command_that_does_not_exist() -> None:
    """Two hints told the author to run `manuscript-guard review --open`, including the one
    on a finding that fails at submission. There is no such flag."""
    from manuscript_guard.cli import build_parser

    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    real = {
        name: {flag for action in sub._actions for flag in action.option_strings}
        for name, sub in choices.items()
    }

    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path(__file__).resolve().parent.parent / "src").rglob("*.py")
    )
    for command, flags in real.items():
        for suggested in re.findall(rf"manuscript-guard {command} (--[a-z-]+)", source):
            assert suggested in flags, (
                f"a hint suggests `{command} {suggested}`, which is not a flag"
            )
