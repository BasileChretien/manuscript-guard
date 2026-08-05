"""What the fifth adversarial round found, each with the case that would have caught it.

Three of the six were in code written the day before, and two of those were functions whose
docstrings promised a comparison the body never made — the recurring shape of this project,
appearing again inside the features built to close it.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_revision
from manuscript_guard.roundtrip import paragraph_slug, tag, tagged_paragraphs

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def round_with(root: Path, point: dict, **extra) -> Path:
    from manuscript_guard.gates.review import file_digests

    project, _ = load_project(root)
    document = {
        "schema": "manuscript-guard/revision/1",
        "round": 1,
        "journal": "demo-journal",
        "received_on": "2026-08-05",
        "submitted_files": file_digests(project),
        "reviewers": [{"id": "reviewer-1", "points": [point]}],
        **extra,
    }
    path = root / "revision" / "round-1.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def codes(root: Path) -> set[str]:
    project, _ = load_project(root)
    return {f.code for f in check_revision(project, submission=True).findings}


# ---------------------------------------------------------------- 1: absent from baseline


def test_a_file_absent_from_the_baseline_is_not_verified(project: Path) -> None:
    """`submitted.get(name)` returns None for a missing key, which is never equal to a
    digest — so the comparison fell through to "verified" for any file the baseline did not
    happen to list. A claimed revision of an unlisted file passed unconditionally."""
    round_with(
        project,
        {
            "id": "1.1",
            "comment": "Revise the Methods.",
            "response": "We have revised the Methods.",
            "changed": [{"kind": "manuscript", "name": "main.md"}],
        },
        submitted_files={"decoy.md": "0" * 64},
    )
    assert "claimed-change-did-not-happen" in codes(project)


def test_an_empty_baseline_is_still_the_documented_no_baseline_case(project: Path) -> None:
    """Distinct from the above: with no baseline at all there is genuinely nothing to
    compare against, and saying so is honest. What is refused is a baseline that lists
    other files and not this one."""
    round_with(
        project,
        {
            "id": "1.1",
            "comment": "Revise the Methods.",
            "response": "Revised.",
            "changed": [{"kind": "manuscript", "name": "main.md"}],
        },
        submitted_files={},
    )
    assert "claimed-change-did-not-happen" not in codes(project)


# ---------------------------------------------------------------- 2: path containment


@pytest.mark.parametrize("name", ["../paper.yaml", "C:/Windows/win.ini", "../../etc/hosts"])
def test_a_named_artefact_must_be_inside_the_project(project: Path, name: str) -> None:
    """`Path / "C:/absolute"` discards the left side, and `..` walks out — so "does this
    figure exist" was satisfiable by naming any file on the machine."""
    round_with(
        project,
        {
            "id": "1.2",
            "comment": "Update the figure.",
            "response": "Updated.",
            "changed": [{"kind": "figure", "name": name}],
        },
    )
    assert "claimed-change-did-not-happen" in codes(project)


def test_a_real_figure_is_still_accepted(project: Path) -> None:
    round_with(
        project,
        {
            "id": "1.3",
            "comment": "Update the figure.",
            "response": "Updated.",
            "changed": [{"kind": "figure", "name": "forest.svg"}],
        },
    )
    assert "claimed-change-did-not-happen" not in codes(project)


# ---------------------------------------------------------------- 3: identifier collision


def test_two_files_with_the_same_stem_get_different_identifiers() -> None:
    """The consequence was not a confused report but silent loss: the document carried the
    same bookmark twice, and a co-author's edit to one of them was neither merged nor
    refused. `gates/review.py` had already learned this for file digests."""
    a = tag("Section A.\n", "sectionA/notes.md")
    b = tag("Section B.\n", "sectionB/notes.md")
    assert a.split("}")[0] != b.split("}")[0]


def test_an_identifier_is_a_legal_word_bookmark() -> None:
    """Word bookmark names take letters, digits and underscores, must not start with a
    digit, and are capped at 40 characters."""
    import re

    slug = paragraph_slug("some/deeply/nested/a-very-long-file-name-indeed.md")
    name = f"mg-p-{slug}-12"
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name), name
    assert len(name) <= 40, f"{name} is {len(name)} characters"


def test_identifiers_are_unique_across_the_whole_manuscript(project: Path) -> None:
    nested = project / "manuscript" / "parts"
    nested.mkdir()
    (nested / "main.md").write_text("# Extra\n\nA paragraph.\n", encoding="utf-8")

    projekt, _ = load_project(project)
    known = tagged_paragraphs(projekt)
    assert len(known) == len(set(known)), "an identifier names one paragraph or it names none"
    # main.md, parts/main.md, and the example's supplement — the round trip covers the
    # supplement too, or a co-author's edit to it comes back with nowhere to land.
    assert len({entry[0] for entry in known.values()}) == 3


# ---------------------------------------------------------------- 4: the anchored check


@needs_pandoc
def test_the_anchored_paragraph_must_actually_change(project: Path) -> None:
    """The comparison the docstring always promised. Checking that the identifier still
    resolves detects a deleted paragraph and nothing else, so a response could claim a
    revision, change something else in the same file, and the paragraph the reviewer
    objected to went untouched with the gate silent."""
    projekt, _ = load_project(project)
    known = tagged_paragraphs(projekt)
    anchor = next(iter(known))

    round_with(
        project,
        {
            "id": "1.4",
            "comment": "This paragraph is unclear.",
            "where": anchor,
            "response": "We have revised the Methods.",
            "changed": [{"kind": "manuscript", "name": "main.md"}],
        },
        submitted_paragraphs={
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, (_path, text, _at) in known.items()
        },
    )
    # Change the file, but not the paragraph the reviewer commented on.
    path = project / "manuscript" / "main.md"
    whole = path.read_text(encoding="utf-8")
    path.write_text(whole + "\n\nAn unrelated addition.\n", encoding="utf-8")

    assert "claimed-change-missed-the-point" in codes(project)


@needs_pandoc
def test_revising_the_anchored_paragraph_satisfies_it(project: Path) -> None:
    projekt, _ = load_project(project)
    known = tagged_paragraphs(projekt)
    anchor, (path, text, _start) = next(iter(known.items()))

    round_with(
        project,
        {
            "id": "1.5",
            "comment": "This paragraph is unclear.",
            "where": anchor,
            "response": "We have rewritten it.",
            "changed": [{"kind": "manuscript", "name": path.name}],
        },
        submitted_paragraphs={
            name: hashlib.sha256(body.encode("utf-8")).hexdigest()
            for name, (_p, body, _at) in known.items()
        },
    )
    whole = path.read_text(encoding="utf-8")
    path.write_text(whole.replace(text, text + " Now clarified.", 1), encoding="utf-8")

    assert "claimed-change-missed-the-point" not in codes(project)


# ---------------------------------------------------------------- 6: reviewer slugs


def test_two_spellings_of_one_reviewer_do_not_split_into_two(tmp_path: Path) -> None:
    """"Reviewer 2" and "REVIEWER 2" were two buckets and one id, which put two people's
    points under a single heading in the letter that goes to the journal."""
    from manuscript_guard.cli import _seeded
    from manuscript_guard.roundtrip import Comment

    def fake(_source):
        return [
            Comment(author="Reviewer 2", date="2026-08-05", text="First point."),
            Comment(author="REVIEWER 2", date="2026-08-05", text="Second point."),
        ]

    import manuscript_guard.roundtrip as rt

    saved = rt.comments_in
    rt.comments_in = fake
    try:
        reviewers = _seeded(tmp_path / "unused.docx")
    finally:
        rt.comments_in = saved

    ids = [r["id"] for r in reviewers]
    assert len(ids) == len(set(ids)), f"two reviewers share an id: {ids}"
    assert sum(len(r["points"]) for r in reviewers) == 2
