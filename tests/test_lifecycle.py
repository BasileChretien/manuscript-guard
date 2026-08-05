"""What walking the whole lifecycle found.

These are not component bugs. They are places where one step's output was not what the next
step expected, and the tests that missed them all shared a shape: they built their input the
way the code under test reads it, rather than the way the real caller writes it.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def body_text(document: Path) -> list[str]:
    xml = zipfile.ZipFile(document).read("word/document.xml").decode("utf-8")
    return [
        " ".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block))
        for block in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
    ]


# ---------------------------------------------------------------- front matter


@needs_pandoc
def test_the_document_does_not_open_with_raw_yaml(project: Path) -> None:
    """`init` scaffolds a title into both paper.yaml and main.md; only the first is used,
    and the second was never removed from the body. Every document this tool had ever built
    opened with a line of YAML rendered as prose — including the shipped example, where the
    two titles match and the stray line read as a harmless duplicate."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    paragraphs = body_text(project / "build" / "manuscript.docx")
    assert paragraphs, "the document has no text at all"
    assert not any("title:" in p for p in paragraphs[:4]), paragraphs[:4]
    assert "---" not in paragraphs[0]


def test_two_different_titles_are_reported(project: Path) -> None:
    """`submit` writes the title page and the manifest from paper.yaml, so when the two
    disagree the paper goes out under a title nothing in the manuscript mentions."""
    from manuscript_guard.build.assemble import assemble
    from manuscript_guard.contracts import load_namespace, load_project

    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace('title: "', 'title: "A different ', 1), encoding="utf-8")

    projekt, _ = load_project(project)
    namespace, results, _lit, _r = load_namespace(projekt)
    _assembled, report = assemble(projekt, namespace, results)
    assert "two-titles" in {f.code for f in report.findings}


def test_matching_titles_are_not_reported(project: Path) -> None:
    from manuscript_guard.build.assemble import assemble
    from manuscript_guard.contracts import load_namespace, load_project

    projekt, _ = load_project(project)
    namespace, results, _lit, _r = load_namespace(projekt)
    _assembled, report = assemble(projekt, namespace, results)
    assert "two-titles" not in {f.code for f in report.findings}


def test_a_body_with_no_front_matter_is_untouched() -> None:
    from manuscript_guard.build.assemble import strip_front_matter

    body, declared = strip_front_matter("# Methods\n\nProse.\n")
    assert body == "# Methods\n\nProse.\n"
    assert declared == ""


def test_front_matter_is_stripped_and_its_title_reported() -> None:
    from manuscript_guard.build.assemble import strip_front_matter

    body, declared = strip_front_matter('---\ntitle: "A paper"\n---\n\n# Methods\n')
    assert body == "# Methods\n"
    assert declared == "A paper"


# ---------------------------------------------------------------- the baseline


@needs_pandoc
def test_the_recorded_baseline_is_in_the_representation_the_gate_reads(
    project: Path, tmp_path: Path
) -> None:
    """The digest comparison was dead code, and its test passed anyway.

    `respond --open --from` hashed the text extracted from the .docx; the gate re-hashes the
    markdown source. Rendered prose and source carrying `{{bindings}}` are never the same
    string, so `now == paragraphs[where]` could not fire. The test written alongside the fix
    built the baseline the way the *gate* reads it rather than the way the *command* writes
    it, so it passed over a check that could never run.
    """
    from manuscript_guard.cli import main
    from manuscript_guard.contracts import load_project
    from manuscript_guard.roundtrip import tagged_paragraphs

    assert main(["build", str(project), "--offline"]) == 0
    returned = shutil.copy(project / "build" / "manuscript.docx", tmp_path / "back.docx")
    assert main(["respond", str(project), "--open", "--from", str(returned)]) == 0

    document = yaml.safe_load((project / "revision" / "round-1.yaml").read_text(encoding="utf-8"))
    baseline = document["submitted_paragraphs"]
    assert baseline, "no paragraph baseline recorded"

    projekt, _ = load_project(project)
    known = tagged_paragraphs(projekt)
    shared = [name for name in baseline if name in known]
    assert shared, "the baseline names no paragraph the source has"

    agreeing = [
        name
        for name in shared
        if hashlib.sha256(known[name][1].encode("utf-8")).hexdigest() == baseline[name]
    ]
    assert agreeing == shared, (
        "the recorded baseline and the gate's recomputation must be the same "
        "representation, or the comparison can never fire"
    )


# ---------------------------------------------------------------- a usable first run


def test_a_fresh_project_has_a_bibliography_to_build_from(tmp_path: Path) -> None:
    """A scaffolded manuscript has no citations, and `build --offline` refused it — telling
    the author to run `sync-bib` with Zotero open, which is the one thing `--offline` exists
    so they do not have to do."""
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    root.mkdir()
    init_project(root, title="T")
    assert (root / "literature" / "references.bib").exists()


@needs_pandoc
def test_a_fresh_project_can_be_built_offline(tmp_path: Path) -> None:
    from manuscript_guard.cli import main
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    root.mkdir()
    init_project(root, title="T")
    assert main(["build", str(root), "--offline", "--skip-checks"]) == 0


# ---------------------------------------------------------------- exit codes


@needs_pandoc
def test_comments_alone_are_not_a_failure(project: Path, tmp_path: Path) -> None:
    """`return 0 if args.apply else 1` treated "a co-author left notes" as a problem, so a
    hook or a CI step keyed on the exit code reported one."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = shutil.copy(project / "build" / "manuscript.docx", tmp_path / "back.docx")
    assert main(["import", str(returned), str(project)]) == 0
