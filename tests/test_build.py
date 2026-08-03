"""Assembly, tables, citations and the document build.

Zotero-dependent tests skip when Zotero is not running, and pandoc-dependent tests skip
when pandoc is absent. Everything else must pass anywhere, because the offline path is the
one CI and a co-author without Zotero rely on.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from manuscript_guard.build import LIVE, OFFLINE, BuildError, assemble, build_document, render_table
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.contracts.results import Table
from manuscript_guard.emit import Emitter
from manuscript_guard.findings import merge_all
from manuscript_guard.gates import check_citations, check_numbers
from manuscript_guard.zotero import available, find_citations

HAS_PANDOC = shutil.which("pandoc") is not None
needs_pandoc = pytest.mark.skipif(not HAS_PANDOC, reason="pandoc is not installed")
needs_zotero = pytest.mark.skipif(not available(), reason="Zotero is not running")


def loaded(root: Path):
    project, _ = load_project(root)
    namespace, results, literature, _ = load_namespace(project)
    return project, namespace, results, literature


def codes(report) -> set[str]:
    return {f.code for f in report.failures}


def docx_text(path: Path) -> str:
    """Visible text of a .docx.

    Word splits a sentence across many <w:t> runs whenever formatting or spell-check state
    changes, so searching the raw XML for a phrase finds nothing even when the phrase is
    plainly on the page. Concatenating the runs is the only reliable way to ask what the
    document says — the same trap that let a wrong table value survive every check in the
    predecessor project.
    """
    import re

    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
    runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, re.DOTALL)
    return re.sub(r"\s+", " ", "".join(runs))


# ---------------------------------------------------------------- tables


def test_render_table_is_a_pandoc_pipe_table() -> None:
    table = Table(
        key="t",
        columns=("Characteristic", "Value"),
        rows=(("Reports", "426"), ("Serious", "163 (38.3)")),
        caption="Reports by group.",
        align=("left", "right"),
        quoted=True,
        source=Path("results/x.json"),
    )
    text = render_table(table)
    lines = text.splitlines()
    assert lines[0].startswith("| Characteristic")
    rule_cells = [c.strip() for c in lines[1].strip("|").split("|")]
    assert rule_cells[0].endswith("-"), "left-aligned column"
    assert rule_cells[1].endswith(":"), "right-aligned column"
    assert "| Reports" in text
    assert text.rstrip().endswith(": Reports by group.")


def test_emitter_rejects_a_ragged_table(tmp_path: Path) -> None:
    (tmp_path / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "t"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    script = tmp_path / "a.py"
    script.write_text("# x\n", encoding="utf-8")
    em = Emitter(script, root=tmp_path)
    with pytest.raises(ValueError, match="row 0 has 1 cells"):
        em.table("t", columns=["a", "b"], rows=[["only-one"]])


def test_a_table_nothing_places_is_reported(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("{{table.baseline}}", ""), encoding="utf-8"
    )
    _p, namespace, results, literature = loaded(project)
    report = check_numbers(_p, namespace, results, literature)
    assert "unplaced-table" in codes(report)


# ---------------------------------------------------------------- assembly


def test_assembly_substitutes_values_tables_and_figures(project: Path) -> None:
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    text = next(a.text for a in assembled if a.path.name == "main.md")

    assert "{{" not in text, "every binding must be resolved"
    assert namespace["results.ror.point"].display in text
    assert "| Characteristic" in text, "the table should be rendered inline"
    assert "![](" in text, "the figure should become an image reference"


def test_assembly_leaves_citations_untouched(project: Path) -> None:
    """`[@key]` has to reach pandoc intact or the Zotero filter has nothing to work with."""
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    text = next(a.text for a in assembled if a.path.name == "main.md")
    assert "[@fictionalHepaticCohort2021]" in text


def test_a_missing_figure_is_reported(project: Path) -> None:
    for path in (project / "figures").glob("forest.*"):
        if path.suffix in {".svg", ".png", ".pdf"}:
            path.unlink()
    proj, namespace, results, _lit = loaded(project)
    _assembled, report = assemble(proj, namespace, results)
    assert "figure-missing" in codes(report)


def test_a_missing_table_is_reported(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("{{table.baseline}}", "{{table.nonexistent}}"),
        encoding="utf-8",
    )
    proj, namespace, results, _lit = loaded(project)
    _assembled, report = assemble(proj, namespace, results)
    assert "table-missing" in codes(report)


# ---------------------------------------------------------------- citations


def test_bracketed_and_narrative_citations_are_told_apart() -> None:
    text = "A claim [@smith2020] and [@a2019; @b2020, p. 4]. As @jones2021 showed.\n"
    uses = find_citations(text, Path("m.md"))
    keys = {u.citekey for u in uses}
    assert keys == {"smith2020", "a2019", "b2020", "jones2021"}
    assert {u.citekey for u in uses if u.narrative} == {"jones2021"}


def test_an_email_address_is_not_a_citation() -> None:
    assert find_citations("Write to a.person@example.org for data.\n", Path("m.md")) == []


def test_a_citation_inside_code_is_still_found_but_not_in_backticks() -> None:
    uses = find_citations("Use `@literal` here, but cite @realKey2020.\n", Path("m.md"))
    assert {u.citekey for u in uses} == {"realKey2020"}


def test_the_example_citations_resolve_from_the_committed_bib(project: Path) -> None:
    proj, _ns, _results, literature = loaded(project)
    report = check_citations(proj, literature)
    assert "citation-unresolved" not in codes(report)
    assert report.counts["citations_distinct"] == 2


def test_an_unknown_citekey_is_reported(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "fictionalHepaticCohort2021", "fictionalHepaticCohort2022"
        ),
        encoding="utf-8",
    )
    proj, _ns, _results, literature = loaded(project)
    report = check_citations(proj, literature)
    assert "citation-unresolved" in codes(report)
    assert any("did you mean" in (f.hint or "") for f in report.failures)


def test_a_missing_literature_source_is_reported(project: Path) -> None:
    (project / "literature" / "sources" / "fictionalHepaticCohort2021.txt").unlink()
    proj, _ns, _results, literature = loaded(project)
    assert "literature-source-missing" in codes(check_citations(proj, literature))


def test_an_attested_value_needs_no_stored_source(project: Path) -> None:
    """The whole point of attested.yaml is that no file exists to point at."""
    proj, _ns, _results, literature = loaded(project)
    report = check_citations(proj, literature)
    assert report.counts["literature_sources_missing"] == 0
    assert literature.values["agency.withdrawn_estimate"] is not None


# ---------------------------------------------------------------- the document


@needs_pandoc
def test_offline_build_produces_a_document(project: Path) -> None:
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    result = build_document(proj, assembled, mode=OFFLINE)
    assert result.output.exists()
    assert result.output.stat().st_size > 5000
    text = docx_text(result.output)
    assert "reporting odds ratio of" in text, "the prose should be there"
    assert namespace["results.ror.point"].display in text, "and its bound value with it"
    assert "Characteristic" in text, "the emitted table should reach the document"
    # citeproc should have formatted a reference list from the committed bibliography.
    assert "Imaginary Drug Safety Reports" in text


@needs_pandoc
def test_offline_build_needs_a_bibliography(project: Path) -> None:
    (project / "literature" / "references.bib").unlink()
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    with pytest.raises(BuildError, match="sync-bib"):
        build_document(proj, assembled, mode=OFFLINE)


@needs_pandoc
def test_the_built_document_carries_no_unresolved_bindings(project: Path) -> None:
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    result = build_document(proj, assembled, mode=OFFLINE)
    assert "{{" not in docx_text(result.output)


@needs_pandoc
@needs_zotero
def test_live_build_writes_real_zotero_fields(tmp_path: Path) -> None:
    """The end the whole architecture rests on: Markdown in, live Zotero citations out."""
    from manuscript_guard.zotero import ZoteroUnavailable, library

    try:
        keys = list(library())[:2]
    except ZoteroUnavailable as exc:
        pytest.skip(f"Zotero answered the ping but not the query: {exc}")
    if len(keys) < 2:
        pytest.skip("the Zotero library has fewer than two items with citation keys")

    root = tmp_path / "live"
    (root / "manuscript").mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "Live"\nenglish_variant: en-GB\n',
        encoding="utf-8",
    )
    (root / "manuscript" / "main.md").write_text(
        f"# Body\n\nBracketed [@{keys[0]}] and narrative @{keys[1]}.\n", encoding="utf-8"
    )

    proj, namespace, results, _lit = loaded(root)
    assembled, _ = assemble(proj, namespace, results)
    result = build_document(proj, assembled, mode=LIVE)
    assert result.report.counts["zotero_fields"] >= 2, "both citation forms must become fields"


@needs_pandoc
def test_gates_and_build_agree_on_the_example(project: Path) -> None:
    """A green check must mean the document builds; otherwise the gates guard nothing."""
    proj, namespace, results, literature = loaded(project)
    gates = merge_all([check_numbers(proj, namespace, results, literature)])
    assert gates.ok, gates.render(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok
    assert build_document(proj, assembled, mode=OFFLINE).output.exists()
