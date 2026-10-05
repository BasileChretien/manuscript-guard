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
    from manuscript_guard.zotero import ZoteroUnavailable, rpc
    from manuscript_guard.zotero.client import PINNED_CONDITION

    # Two pinned items, found by a condition search. Reading the whole library here, as this
    # test used to, takes about a minute on a library of a few thousand items, so on any real
    # library the test ran out of time and skipped itself: the end-to-end test was the one
    # never run where it mattered.
    try:
        keys = [i["citation-key"] for i in rpc("item.search", [PINNED_CONDITION])][:2]
    except ZoteroUnavailable as exc:
        pytest.skip(f"Zotero answered the ping but not the query: {exc}")
    if len(keys) < 2:
        pytest.skip("the Zotero library has fewer than two items with pinned citation keys")

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


# ---------------------------------------------------------------- figure captions


def _styles(path: Path) -> str:
    return zipfile.ZipFile(path).read("word/styles.xml").decode("utf-8", "replace")


def _paragraphs(path: Path) -> list[str]:
    import re

    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8", "replace")
    return re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)


def _captioned(project: Path) -> Path:
    """The example, cut down to a figure with a caption and two ordinary paragraphs."""
    (project / "manuscript" / "main.md").write_text(
        "# Results\n\nOrdinary prose before the figure.\n\n{{figure.forest}}\n\n"
        "**Figure 1.** What the figure shows, at length.\n\n"
        "Figure 1 is discussed in this paragraph, which is not a caption.\n",
        encoding="utf-8",
    )
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    return build_document(proj, assembled, mode=OFFLINE).output


@needs_pandoc
def test_the_caption_after_a_figure_is_styled_smaller(project: Path) -> None:
    """A caption set in the body font leaves a reader nothing to tell caption from text."""
    import re

    output = _captioned(project)
    styles = _styles(output)
    assert 'w:styleId="FigureCaption"' in styles, "the style must be defined in the document"
    caption = re.search(r'<w:style [^>]*w:styleId="FigureCaption".*?</w:style>', styles, re.DOTALL)
    assert caption is not None
    size = re.search(r'<w:sz w:val="(\d+)"', caption.group(0))
    assert size is not None, "a caption style that sets no size is not smaller than anything"
    default = re.search(r"<w:docDefaults>.*?<w:sz w:val=\"(\d+)\"", styles, re.DOTALL)
    assert default is not None
    assert int(size.group(1)) < int(default.group(1)), "the caption must be the smaller size"

    styled = [p for p in _paragraphs(output) if 'w:val="FigureCaption"' in p]
    assert len(styled) == 1, "exactly the one caption"
    assert "What the figure shows" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", styled[0]))


@needs_pandoc
def test_a_paragraph_that_follows_no_figure_is_not_a_caption(project: Path) -> None:
    """The rule is position, not the word "Figure": prose that mentions a figure is prose."""
    import re

    output = _captioned(project)
    for paragraph in _paragraphs(output):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph))
        if "is discussed in this paragraph" in text or "prose before the figure" in text:
            assert 'w:val="FigureCaption"' not in paragraph


@needs_pandoc
def test_the_ordinary_build_still_records_its_source(project: Path) -> None:
    """The build now always hands pandoc a reference document, and the stamp that tells a
    co-author's document from a current one must not be what distinguishes the two builds."""
    from manuscript_guard.build.document import SOURCE_STAMP

    output = _captioned(project)
    assert output.with_name(output.name + SOURCE_STAMP).is_file()


@needs_pandoc
def test_prose_directly_after_a_figure_is_not_set_as_its_caption(project: Path) -> None:
    """The argument resumes under a figure as often as a caption opens there."""
    import re

    (project / "manuscript" / "main.md").write_text(
        "# Results\n\nOrdinary prose before the figure.\n\n{{figure.forest}}\n\n"
        "Figure 1 shows the estimate with its interval, and this sentence is the argument "
        "resuming, not a caption.\n",
        encoding="utf-8",
    )
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    output = build_document(proj, assembled, mode=OFFLINE).output
    found = [
        p
        for p in _paragraphs(output)
        if "the argument resuming" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p))
    ]
    assert len(found) == 1
    assert 'w:val="FigureCaption"' not in found[0], "prose was set in the caption style"


@needs_pandoc
def test_a_fold_change_under_a_figure_is_not_a_caption(project: Path) -> None:
    """"Figure 2.5-fold higher ..." opens with a figure number only if the stop is not read."""
    import re

    (project / "manuscript" / "main.md").write_text(
        "# Results\n\n{{figure.forest}}\n\nFigure 2.5-fold higher than the comparator, which "
        "is a sentence about a ratio.\n",
        encoding="utf-8",
    )
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    output = build_document(proj, assembled, mode=OFFLINE).output
    found = [
        p
        for p in _paragraphs(output)
        if "a sentence about a ratio" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p))
    ]
    assert len(found) == 1
    assert 'w:val="FigureCaption"' not in found[0]


@needs_pandoc
def test_the_authors_own_reference_document_still_styles_the_build(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Passing --reference-doc tells pandoc to ignore the author's own one, so the build has
    to start from it. It is the only way this toolkit lets anyone set the typography."""
    import subprocess

    home = tmp_path / "data-home"
    (home / "pandoc").mkdir(parents=True)
    default = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"], capture_output=True, check=True
    ).stdout
    scratch = tmp_path / "default.docx"
    scratch.write_bytes(default)
    house = (
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="HouseStyle">'
        '<w:name w:val="House Style"/><w:basedOn w:val="Normal"/></w:style>'
    )
    with (
        zipfile.ZipFile(scratch) as zin,
        zipfile.ZipFile(home / "pandoc" / "reference.docx", "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = data.decode("utf-8").replace("</w:styles>", house + "</w:styles>").encode()
            zout.writestr(item, data)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))

    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok
    output = build_document(proj, assembled, mode=OFFLINE).output
    assert "HouseStyle" in _styles(output), "the author's reference document was not used"
    assert 'w:styleId="FigureCaption"' in _styles(output), "and the caption style with it"


@needs_pandoc
def test_an_authors_own_caption_style_is_not_overridden(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two definitions of one style id is not a document, and theirs is the one to keep."""
    import re
    import subprocess

    home = tmp_path / "data-home"
    (home / "pandoc").mkdir(parents=True)
    default = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"], capture_output=True, check=True
    ).stdout
    scratch = tmp_path / "default.docx"
    scratch.write_bytes(default)
    theirs = (
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="FigureCaption">'
        '<w:name w:val="Figure Caption"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:sz w:val="18"/></w:rPr></w:style>'
    )
    with (
        zipfile.ZipFile(scratch) as zin,
        zipfile.ZipFile(home / "pandoc" / "reference.docx", "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = data.decode("utf-8").replace("</w:styles>", theirs + "</w:styles>").encode()
            zout.writestr(item, data)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))

    output = _captioned(project)
    styles = _styles(output)
    assert styles.count('w:styleId="FigureCaption"') == 1, "one definition, not two"
    defined = re.search(r'<w:style [^>]*w:styleId="FigureCaption".*?</w:style>', styles, re.DOTALL)
    assert defined is not None
    assert '<w:sz w:val="18"/>' in defined.group(0).replace(" />", "/>"), "theirs, at 9 pt"


@needs_pandoc
def test_a_build_that_brings_a_reference_document_is_still_stamped(project: Path) -> None:
    """`stamp` and "has a reference document" are now two different questions, and the stamp
    is what tells a co-author's document from a current one."""
    from manuscript_guard.build.document import SOURCE_STAMP, pandoc
    from manuscript_guard.build.styles import reference_with

    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    reference = reference_with(pandoc(), project / "build" / ".cache" / "brought-in.docx")

    kept = build_document(proj, assembled, mode=OFFLINE, reference_doc=reference)
    assert kept.output.with_name(kept.output.name + SOURCE_STAMP).is_file()
    assert reference.is_file(), (
        "a reference document the caller brought is not the build's to remove"
    )

    unstamped = project / "build" / "unstamped.docx"
    built = build_document(proj, assembled, mode=OFFLINE, output=unstamped, stamp=False)
    assert not built.output.with_name(built.output.name + SOURCE_STAMP).exists()


@needs_pandoc
@pytest.mark.parametrize("name", ["data home", "Zoë"])
def test_the_authors_reference_document_is_found_wherever_their_home_is(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Pandoc prints the path in UTF-8. Read through the console code page, a home directory
    spelt with any other letter came back mojibake, the file was not found, and the build
    went quietly back to pandoc's default."""
    import io
    import subprocess

    home = tmp_path / name
    (home / "pandoc").mkdir(parents=True)
    default = subprocess.run(
        ["pandoc", "--print-default-data-file", "reference.docx"], capture_output=True, check=True
    ).stdout
    house = (
        b'<w:style w:type="paragraph" w:styleId="HouseStyle">'
        b'<w:name w:val="House Style"/></w:style>'
    )
    with (
        zipfile.ZipFile(io.BytesIO(default)) as zin,
        zipfile.ZipFile(home / "pandoc" / "reference.docx", "w") as zout,
    ):
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = data.replace(b"</w:styles>", house + b"</w:styles>")
            zout.writestr(item, data)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))

    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok
    output = build_document(proj, assembled, mode=OFFLINE).output
    assert b"HouseStyle" in zipfile.ZipFile(output).read("word/styles.xml")


@needs_pandoc
def test_two_builds_of_one_project_at_once_do_not_collide(project: Path) -> None:
    """The generated reference document used to have one name per project, so a second build
    truncated the file the first was reading, or deleted it: pandoc read half a .docx, or the
    unlink raised. `import` builds twice, and an agent runs tool calls in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)

    def build(n: int) -> Path:
        return build_document(
            proj, assembled, mode=OFFLINE, output=project / "build" / f"at-once-{n}.docx"
        ).output

    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = [done.result() for done in [pool.submit(build, n) for n in range(4)]]

    for output in outputs:
        assert output.is_file() and output.stat().st_size > 5000
        assert 'w:styleId="FigureCaption"' in _styles(output)
    left = list((project / "build" / ".cache").glob("reference-*"))
    assert left == [], f"the cache kept {[p.name for p in left]}"


def _unreadable_user_reference(home: Path) -> Path:
    """A `reference.docx` in a pandoc user data directory under `home` that is not a .docx."""
    (home / "pandoc").mkdir(parents=True, exist_ok=True)
    target = home / "pandoc" / "reference.docx"
    target.write_bytes(b"This is not a .docx at all.")
    return target


@needs_pandoc
def test_a_caption_whose_space_is_a_no_break_space_is_still_a_caption(project: Path) -> None:
    """Word writes one where a space was typed, and a Lua pattern's %s does not match it."""
    import re

    (project / "manuscript" / "main.md").write_text(
        "# Results\n\n{{figure.forest}}\n\n"
        "**Figure\u00a01.** A caption whose space came from Word.\n",
        encoding="utf-8",
    )
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    output = build_document(proj, assembled, mode=OFFLINE).output
    styled = [p for p in _paragraphs(output) if 'w:val="FigureCaption"' in p]
    assert len(styled) == 1, "the caption was left at body size"
    assert "came from Word" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", styled[0]))


@needs_pandoc
def test_a_user_reference_that_is_not_a_docx_is_said_in_a_sentence(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Their file, not a bug here, and `BadZipFile` names neither the file nor what to do."""
    home = tmp_path / "data-home"
    _unreadable_user_reference(home)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))

    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    with pytest.raises(BuildError, match="cannot be read as a .docx") as raised:
        build_document(proj, assembled, mode=OFFLINE)
    assert str(home / "pandoc" / "reference.docx") in str(raised.value), (
        "the message has to name the file, which is the whole point of it"
    )


@needs_pandoc
def test_a_build_that_fails_before_pandoc_leaves_nothing_in_the_cache(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two failures between the file's creation and the pandoc call: the author's reference
    cannot be read, and the bibliography an offline build needs is gone."""
    cache = project / "build" / ".cache"

    home = tmp_path / "data-home"
    _unreadable_user_reference(home)
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    with pytest.raises(BuildError):
        build_document(proj, assembled, mode=OFFLINE)
    assert list(cache.glob("reference-*")) == [], "the unreadable reference left a file"

    monkeypatch.delenv("XDG_DATA_HOME")
    (project / "literature" / "references.bib").unlink()
    with pytest.raises(BuildError, match="sync-bib"):
        build_document(proj, assembled, mode=OFFLINE)
    assert list(cache.glob("reference-*")) == [], "the missing bibliography left a file"


@needs_pandoc
@pytest.mark.parametrize("succeeds", [True, False])
def test_a_reference_the_build_cannot_remove_is_not_the_builds_error(
    project: Path, monkeypatch: pytest.MonkeyPatch, succeeds: bool
) -> None:
    """A scanner or a sync client holding the file for an instant made the removal raise out
    of the `finally`: it replaced the sentence a failing build was already raising, and it
    left a successful build's document unstamped, with no record of what it was built from."""
    from manuscript_guard.build import document as module
    from manuscript_guard.build.document import SOURCE_STAMP
    from manuscript_guard.roundtrip import RECORDS

    real = module.reference_with
    held = []

    def hold(pandoc: str, target: Path, extra: str = "") -> Path:
        made = real(pandoc, target, extra)
        held.append(made.open("rb"))  # kept open across the build, as a scanner would
        return made

    monkeypatch.setattr(module, "reference_with", hold)
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    try:
        if succeeds:
            built = build_document(proj, assembled, mode=OFFLINE)
            stamp = built.output.with_name(built.output.name + SOURCE_STAMP)
            assert stamp.is_file(), "the document was built and not stamped"
            records = project / "build" / RECORDS
            assert records.is_dir() and any(records.iterdir()), "and left with no record"
        else:
            (project / "literature" / "references.bib").unlink()
            # The build's own sentence, not PermissionError from the tidying up.
            with pytest.raises(BuildError, match="sync-bib"):
                build_document(proj, assembled, mode=OFFLINE)
    finally:
        for handle in held:
            handle.close()
        for left in (project / "build" / ".cache").glob("reference-*"):
            left.unlink(missing_ok=True)
