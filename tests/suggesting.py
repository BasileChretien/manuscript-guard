"""Helpers for the tests of a review panel's suggested edits (`review --suggestions`):
round 8 of the example given findings with edits and sealed again, the command run, and the
document it writes. `tests/word_edits.py` makes Word's edits to that document."""

from __future__ import annotations

import shutil
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
import yaml

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

ROUND = 8
READING = Path("review") / f"round-{ROUND}" / "pharmacoepidemiologist.yaml"


def reading(project: Path) -> dict:
    return yaml.safe_load((project / READING).read_text(encoding="utf-8"))


def with_edits(project: Path, *findings: dict, seal: bool = True) -> None:
    """Round 8's reading with `findings` added, sealed again as the reader's words."""
    from manuscript_guard.gates.review import reading_digest

    document = reading(project)
    document["findings"] = [*document["findings"], *findings]
    document.pop("reading_sha256", None)
    if seal:
        document["reading_sha256"] = reading_digest(document)
    (project / READING).write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def finding(fid: str, *edits: tuple[str, str], severity: str = "minor") -> dict:
    return {
        "id": fid,
        "severity": severity,
        "finding": f"Finding {fid} is about the wording.",
        "edits": [{"old": old, "new": new} for old, new in edits],
    }


def run(*argv: str) -> tuple[int, str]:
    from manuscript_guard.cli import main

    printed = StringIO()
    with redirect_stdout(printed):
        code = main(list(argv))
    return code, printed.getvalue()


def suggest(project: Path) -> tuple[int, str]:
    return run("review", str(project), "--suggestions", "--round", str(ROUND))


def document(project: Path) -> Path:
    return project / "build" / "suggestions" / f"round-{ROUND}.docx"


def offered_round(project: Path) -> Path:
    with_edits(
        project,
        finding("r8-pe-02", ("has not been examined", "remains unexamined"),
                 ("Reports were included without restriction on age or sex.",
                  "Reports of any age or sex were included.")),
        finding("r8-pe-03", ("specifically", "in particular"), severity="major"),
    )  # fmt: skip
    code, said = suggest(project)
    assert code == 0 and "3 edit(s) written" in said, said
    return document(project)
