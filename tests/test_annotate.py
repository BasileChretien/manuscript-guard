"""The annotated copy: what a human checks by eye.

`check` gives a verdict; this is the artefact that lets somebody see why each number is
trusted. The tiers are the whole point, so most of these tests are about a number being
coloured *correctly* rather than coloured at all.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.annotate import (
    DEFECT,
    EXEMPT,
    TIERS,
    TRACED,
    annotate,
    appendix,
    inject_tooltips,
    legend,
)
from manuscript_guard.classify import Classifier
from manuscript_guard.contracts import load_namespace, load_project

PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")


def marked(project: Path):
    projekt, _ = load_project(project)
    namespace, results, _lit, _r = load_namespace(projekt)
    classifier = Classifier.load(projekt.extra_conventions, projekt.extra_terms)
    text = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    return annotate(text, namespace, classifier, counter=[0])


def test_a_bound_number_is_traced_and_names_its_key(project: Path) -> None:
    _text, marks = marked(project)
    ror = next(m for m in marks if m.label == "results.ror.point")
    assert ror.tier == TRACED
    assert "01_disproportionality" in ror.detail
    assert ror.tooltip.startswith("results.ror.point")


def test_a_convention_is_exempt_not_traced(project: Path) -> None:
    """The one place a binary verified/not would lie.

    A convention is a number the gate agreed not to look at. Colouring it like a value
    traced to an artefact would make the annotated copy actively misleading, in the document
    whose entire purpose is to be trusted at a glance.
    """
    _text, marks = marked(project)
    conventions = [m for m in marks if m.label.startswith("convention:")]
    assert conventions, "the example must exercise at least one convention"
    assert all(m.tier == EXEMPT for m in conventions)
    assert all(m.tier != TRACED for m in conventions)


def test_an_attested_value_is_its_own_tier(project: Path) -> None:
    """A person's written word is traceable to a name, not to a document."""
    _text, marks = marked(project)
    attested = [m for m in marks if m.tier == "attested"]
    assert attested, "the example carries an author attestation"
    assert "attested by" in attested[0].detail


def test_an_unbound_number_is_marked_a_defect(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n\nA loose 4321 here.\n", encoding="utf-8")
    _text, marks = marked(project)
    assert any(m.tier == DEFECT and m.shown == "4321" for m in marks)


def test_every_mark_gets_its_own_anchor(project: Path) -> None:
    """Two numbers that read the same must not share a provenance, and in a paper full of
    1s and 2s that happens immediately."""
    _text, marks = marked(project)
    anchors = [m.anchor for m in marks]
    assert len(anchors) == len(set(anchors))


def test_the_appendix_lists_every_mark(project: Path) -> None:
    _text, marks = marked(project)
    table = appendix(marks)
    for mark in marks:
        assert mark.anchor in table


def test_the_legend_says_yellow_is_not_a_verification() -> None:
    assert "not a verification" in legend()
    assert set(TIERS) == {TRACED, "attested", EXEMPT, DEFECT}


@needs_pandoc
def test_the_annotated_build_carries_styles_and_tooltips(project: Path) -> None:
    """Pandoc drops a link title on the way to .docx - verified, not assumed - so the hover
    text is injected afterwards, keyed on the anchor."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline", "--annotated"]) == 0
    output = project / "build" / "manuscript.annotated.docx"
    assert output.exists()

    archive = zipfile.ZipFile(output)
    document = archive.read("word/document.xml").decode("utf-8")
    styles = archive.read("word/styles.xml").decode("utf-8")
    for style, _colour, _meaning in TIERS.values():
        assert f'w:styleId="{style}"' in styles, style
    assert document.count("w:tooltip") > 10
    assert "results." in document or "w:tooltip" in document


@needs_pandoc
def test_the_annotated_copy_is_not_stamped_as_the_manuscript(project: Path) -> None:
    """The stamp is what `check` reads to decide whether the document a co-author opens is
    current. There must be exactly one such document, and this is not it."""
    from manuscript_guard.build.document import SOURCE_STAMP
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline", "--annotated"]) == 0
    annotated = project / "build" / "manuscript.annotated.docx"
    assert not annotated.with_name(annotated.name + SOURCE_STAMP).exists()


def test_injecting_tooltips_into_a_document_without_links_is_harmless(tmp_path: Path) -> None:
    assert inject_tooltips(tmp_path / "nothing.docx", []) == 0
