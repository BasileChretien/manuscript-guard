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
    finish,
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


def test_finishing_a_document_with_no_marks_is_harmless(tmp_path: Path) -> None:
    assert finish(tmp_path / "nothing.docx", []) == 0


def test_two_variables_that_display_the_same_get_different_hovers(project: Path) -> None:
    """The collision question, and the reason marks are built from offsets.

    Nothing here matches on text. A binding's span comes from the placeholder parser and a
    literal's from the tokenizer, so two keys that happen to render the same string are
    still two marks with two anchors and two tooltips. Matching on the visible value would
    have attached one provenance to both, and in a paper full of 1s and 2s that is not an
    edge case - it is the common case.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\nCases: {{results.case.n_cases}} and serious: {{results.case.n_serious}}, "
        "with {{results.case.n_cases}} again.\n",
        encoding="utf-8",
    )
    _text, marks = marked(project)

    quoted = [m for m in marks if m.label.startswith("results.case.n_")]
    assert len(quoted) >= 3
    assert len({m.anchor for m in quoted}) == len(quoted), "each occurrence needs its own anchor"

    # The same key quoted twice keeps its identity; two different keys never share one.
    by_label = {}
    for mark in quoted:
        by_label.setdefault(mark.label, set()).add(mark.tooltip)
    assert all(len(tips) == 1 for tips in by_label.values()), "one key, one provenance"
    assert len(by_label) >= 2, "the test must exercise two different keys"


def test_a_literal_equal_to_an_emitted_value_is_still_a_defect(project: Path) -> None:
    """The other half of the collision question.

    A typed number that happens to equal a published value is not thereby traced. The
    annotated copy colours it red, because in source a results-derived number may not be a
    literal at all - which is exactly why the gate does not compare values.
    """
    from manuscript_guard.contracts import load_namespace, load_project

    projekt, _ = load_project(project)
    namespace, _results, _lit, _r = load_namespace(projekt)
    display = namespace["results.case.n_cases"].display

    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n\nA typed {display} here.\n", encoding="utf-8"
    )
    _text, marks = marked(project)
    typed = [m for m in marks if m.shown == display and m.tier == DEFECT]
    assert typed, "a literal equal to an emitted value must not borrow its provenance"


@needs_pandoc
def test_the_highlight_reaches_the_page(project: Path) -> None:
    """It did not, and nothing failed.

    The colour was a custom character style wrapping a link. OOXML allows one `w:rStyle`
    per run, pandoc's Link writer puts `Hyperlink` there, and the custom style was silently
    discarded - styles defined, document valid, every number unmarked. Asserted on the
    bytes now, because looking at the XML for the style definition is what missed it.
    """
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline", "--annotated"]) == 0
    document = zipfile.ZipFile(project / "build" / "manuscript.annotated.docx").read(
        "word/document.xml"
    ).decode("utf-8")
    assert document.count("<w:highlight") > 10
    for colour in ("green", "yellow"):
        assert f'<w:highlight w:val="{colour}"/>' in document
    # rStyle must come first inside rPr, or Word drops what follows it.
    assert "<w:highlight" not in document.split("<w:rStyle")[0].split("<w:rPr>")[-1]


@needs_pandoc
def test_the_annotated_copy_contains_the_tables_and_the_figure(project: Path) -> None:
    """The first version annotated the source and substituted only value bindings, so
    `{{table.baseline}}` printed literally: an audit document missing the artefacts a stale
    number is likeliest to survive in."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline", "--annotated"]) == 0
    archive = zipfile.ZipFile(project / "build" / "manuscript.annotated.docx")
    document = archive.read("word/document.xml").decode("utf-8")
    assert "{{table." not in document and "{{figure." not in document
    assert document.count("<w:tbl>") >= 4
    assert any(name.startswith("word/media/") for name in archive.namelist())
