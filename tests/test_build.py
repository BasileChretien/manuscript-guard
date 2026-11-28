"""Assembly, tables, citations and the document build.

Zotero-dependent tests skip when Zotero is not running, and pandoc-dependent tests skip
when pandoc is absent. Everything else must pass anywhere, because the offline path is the
one CI and a co-author without Zotero rely on.
"""

from __future__ import annotations

import os
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


def _zotero_here() -> bool:
    """Whether a Zotero answers on this machine, asked past the switch the suite sets
    (MANUSCRIPT_GUARD_NO_ZOTERO), for the tests marked `real_zotero`."""
    from manuscript_guard.zotero.client import NO_ZOTERO

    kept = os.environ.pop(NO_ZOTERO, None)
    try:
        return available()
    finally:
        if kept is not None:
            os.environ[NO_ZOTERO] = kept


needs_zotero = pytest.mark.skipif(not _zotero_here(), reason="Zotero is not running")


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
    # With its alternative text as the image's description, in the span that keeps pandoc
    # from printing that as a caption.
    assert "[![Forest plot of" in text and "]{.mg-figure}" in text, "the figure's image"


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
def test_a_heading_straight_under_a_captioned_table_is_printed_as_a_heading(
    project: Path,
) -> None:
    """Known gaps: the caption is a paragraph after the table, and a heading on the next
    line does not interrupt a paragraph, so the document printed "Discussion" at the end of
    the caption while G2 read the heading the source means."""
    import re

    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8").replace(
        "{{table.two_by_two}}\n\n{{figure.forest}}\n\n# Discussion",
        "{{figure.forest}}\n\n{{table.two_by_two}}\n# Discussion", 1,
    )  # fmt: skip
    assert "two_by_two}}\n# Discussion" in text
    path.write_text(text, encoding="utf-8")
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    out = project / "build" / "manuscript.docx"
    build_document(proj, assembled, mode=OFFLINE, output=out)
    xml = zipfile.ZipFile(out).read("word/document.xml").decode("utf-8")
    heading = re.search(r'<w:pStyle w:val="Heading1"\s*/>(?:(?!</w:p>).)*Discussion', xml, re.S)
    assert heading is not None, "Discussion is no heading in the document"


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


@pytest.fixture
def zotero_forgotten():
    """`lookup` keeps its answers for the process: each test here asks its own fake."""
    from manuscript_guard.zotero import reset_cache

    reset_cache()
    yield
    reset_cache()


@pytest.mark.parametrize(
    ("ping", "said"),
    [(False, "Zotero is not running"), (True, "Better BibTeX does not answer")],
)
def test_a_live_build_says_why_zotero_cannot_make_its_fields_before_pandoc_runs(
    project: Path, monkeypatch, zotero_forgotten, ping: bool, said: str
) -> None:
    """The build used to run pandoc, fail, and add "If Zotero is not running" whatever the
    reason was. It now asks first, and says which of the things a live build needs is
    missing, and what to do."""
    import urllib.error

    from manuscript_guard.build import document
    from manuscript_guard.zotero import client

    asked: list[object] = []

    def nothing_there(target, *_args, **_kwargs):
        asked.append(target)
        raise urllib.error.HTTPError(client.ENDPOINT, 404, "Not Found", {}, None)

    monkeypatch.setattr(client, "_ping", lambda timeout: ping)
    monkeypatch.delenv(client.NO_ZOTERO, raising=False)  # the transport is a fake
    monkeypatch.setattr(client.urllib.request, "urlopen", nothing_there)
    monkeypatch.setattr(document, "pandoc", lambda: pytest.fail("pandoc ran"))
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    with pytest.raises(document.ZoteroNotReady, match=said) as caught:
        build_document(proj, assembled, mode=LIVE)
    assert "--offline" in str(caught.value)
    # Better BibTeX is asked where Zotero answered its ping, and only there.
    assert bool(asked) == ping


def test_a_live_build_refuses_keys_the_library_does_not_hold_and_names_them(
    project: Path, monkeypatch, zotero_forgotten
) -> None:
    """A key Zotero does not hold comes out of zotero.lua as text, among fields, and nothing
    said so: the build names each such key before it runs."""
    from test_zotero import FakeBBT, csl

    from manuscript_guard.build import document
    from manuscript_guard.zotero import client

    monkeypatch.setattr(client, "_ping", lambda timeout: True)
    monkeypatch.setattr(client, "rpc", FakeBBT([csl("fictionalClassSignal2019", True)]))
    monkeypatch.setattr(document, "pandoc", lambda: pytest.fail("pandoc ran"))
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    with pytest.raises(document.ZoteroNotReady) as caught:
        build_document(proj, assembled, mode=LIVE)
    assert "fictionalHepaticCohort2021" in str(caught.value)
    assert "fictionalClassSignal2019" not in str(caught.value)


def _docx_with(path: Path, xml: str, **parts: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
        for name, part in parts.items():
            archive.writestr(f"word/{name}.xml", part)
    return path


def test_fewer_zotero_fields_than_citations_are_said(tmp_path: Path) -> None:
    """Only a document with no field at all was warned of: one in which zotero.lua made
    fields of some citations and left the rest as text passed as live."""
    from manuscript_guard.build.document import _verify_live_fields

    field = "<w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION {}</w:instrText>"
    docx = _docx_with(tmp_path / "some.docx", f"<w:document>{field}</w:document>")
    report = _verify_live_fields(docx, 3)
    assert [f.code for f in report.findings] == ["no-live-citations"]
    assert "2 of the 3 citations" in report.findings[0].message
    assert report.counts["zotero_fields"] == 1
    whole = _docx_with(tmp_path / "all.docx", f"<w:document>{field * 3}</w:document>")
    assert not _verify_live_fields(whole, 3).findings


def test_a_citation_in_a_note_is_counted_where_the_note_is(tmp_path: Path) -> None:
    """Round 1 of #811: pandoc writes a footnote's Zotero field into word/footnotes.xml, and
    only word/document.xml was counted, so `Text [@a].[^1]` with `[^1]: As shown by @b.` was
    said to hold a citation as plain text."""
    from manuscript_guard.build.document import _verify_live_fields

    field = "<w:instrText> ADDIN ZOTERO_ITEM CSL_CITATION {}</w:instrText>"
    noted = _docx_with(tmp_path / "notes.docx", f"<w:document>{field}</w:document>",
                       footnotes=f"<w:footnotes>{field}</w:footnotes>",
                       endnotes=f"<w:endnotes>{field}</w:endnotes>")  # fmt: skip
    report = _verify_live_fields(noted, 3)
    assert not report.findings
    assert report.counts["zotero_fields"] == 3


def test_a_better_bibtex_slow_to_answer_lets_the_live_build_try_and_says_so(
    monkeypatch,
) -> None:
    """Round 1 of #811: a Better BibTeX slow to answer just after Zotero starts refused a
    live build that worked before. Not knowing is not a refusal: the build runs, says Zotero
    did not answer in time, and counts the fields it got."""
    from manuscript_guard.build import document
    from manuscript_guard.zotero import BUSY, NOT_RUNNING, Readiness, client

    busy = Readiness(BUSY, detail="did not answer")
    monkeypatch.setattr(client, "readiness", lambda keys, timeout=5: busy)
    said = document._require_zotero(("a",))
    assert [f.code for f in said.findings] == ["zotero-unreadable"]
    assert "did not answer in time" in said.findings[0].message
    monkeypatch.setattr(client, "readiness", lambda keys, timeout=5: Readiness(NOT_RUNNING))
    with pytest.raises(document.ZoteroNotReady):
        document._require_zotero(("a",))


def test_the_instruction_for_a_key_several_items_carry_comes_only_with_one() -> None:
    """Round 1 of #811: "give a key to one item only" was said where no key was ambiguous."""
    from manuscript_guard.build.document import zotero_not_ready
    from manuscript_guard.zotero import KEYS_MISSING, Readiness

    _why, what = zotero_not_ready(Readiness(KEYS_MISSING, missing=("a",)))
    assert "one item only" not in what
    why, what = zotero_not_ready(Readiness(KEYS_MISSING, ambiguous=("b",)))
    assert "one item only" in what
    assert "several items in it carry 1 cited key (@b)" in why


def test_no_fixture_every_test_gets_asks_for_monkeypatch(request) -> None:
    """The fixtures every test gets leave `monkeypatch` to the tests that ask for it: one that
    asked set it up first in every test and undid it last, so a test's patch of `os.open`
    outlived its `tmp_path` and Linux's `shutil.rmtree` failed at teardown (CI of #811)."""
    assert "monkeypatch" not in request.fixturenames


def test_no_test_asks_the_zotero_of_the_machine_it_runs_on(
    monkeypatch, zotero_forgotten
) -> None:
    """Rounds 1 and 2 of #811: every test that builds offline asked 127.0.0.1:23119 what a
    live build would meet, and G7's ping and lookup in every `check` asked the real library
    where Zotero was open. conftest.py sets MANUSCRIPT_GUARD_NO_ZOTERO for the run and every
    process it starts, and the client then opens no connection: the ping G7 asks, the
    probe's, and a call. A test marked `real_zotero` is let through; one that fakes the
    transport lifts it in the test."""
    from manuscript_guard.zotero import NOT_RUNNING, ZoteroUnavailable, client, readiness

    assert os.environ.get(client.NO_ZOTERO)
    monkeypatch.setattr(client.urllib.request, "urlopen",
                        lambda *_a, **_k: pytest.fail("a test reached Zotero"))  # fmt: skip
    assert not client.available()
    assert readiness(("a",)).state == NOT_RUNNING
    with pytest.raises(ZoteroUnavailable):
        client.rpc("api.ready", [])


@needs_pandoc
def test_a_live_build_zotero_was_slow_to_answer_for_says_so_in_its_report(
    project: Path, monkeypatch, tmp_path: Path
) -> None:
    """Round 2 of #811: the warning that Better BibTeX did not answer in time reaches the
    live build's report. A filter that makes no field stands in for Better BibTeX's."""
    from manuscript_guard.build import document
    from manuscript_guard.zotero import BUSY, Readiness, client

    lua = tmp_path / "zotero.lua"
    lua.write_text("return {}", encoding="utf-8")
    monkeypatch.setattr(document, "ensure_zotero_lua", lambda _cache: lua)
    monkeypatch.setattr(document, "_zotero_version", lambda: None)
    monkeypatch.setattr(client, "readiness", lambda keys, timeout=5: Readiness(BUSY))
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    result = build_document(proj, assembled, mode=LIVE)
    codes = [f.code for f in result.report.findings]
    assert "zotero-unreadable" in codes
    assert "no-live-citations" in codes, "and the fields it got are counted"


#: Two entries nothing in the example cites, for a `nocite` to print.
_UNCITED = (
    "\n@article{zeta2001,\n  author = {Zeta, Zoe}, title = {T}, year = {2001},\n}\n"
    "\n@article{alpha2002,\n  author = {Alpha, Al}, title = {U}, year = {2002},\n}\n"
)


def _nocite_in(root: Path, relative: str, value: str) -> None:
    """`references.bib` with `_UNCITED` beside its own, and `nocite: <value>` in the front
    matter of `manuscript/<relative>`, given one where it has none. `value` is YAML as
    typed: a value between single quotation marks unless it is one already, or `~` or
    `null`."""
    bib = root / "literature" / "references.bib"
    bib.write_text(bib.read_text(encoding="utf-8") + _UNCITED, encoding="utf-8")
    path = root / "manuscript" / relative
    text = path.read_text(encoding="utf-8")
    typed = value if value in ("~", "null") or value[:1] in "'\"[" else f"'{value}'"
    line = f"nocite: {typed}\n"
    text = text.replace("---\n", f"---\n{line}", 1) if text.startswith("---\n") else (
        f"---\n{line}---\n\n{text}")  # fmt: skip
    path.write_text(text, encoding="utf-8")


def _printed(path: Path) -> set[str]:
    """Which of `_UNCITED`'s authors the document prints in a reference."""
    return {name for name in ("Zeta", "Alpha") if f"{name}, " in docx_text(path)}


@needs_pandoc
@pytest.mark.parametrize(("value", "printed"), [("@*", {"Zeta", "Alpha"}),
                                                ("@zeta2001", {"Zeta"})])  # fmt: skip
def test_the_supplement_prints_what_its_own_files_nocite_names(
    project: Path, value: str, printed: set[str]
) -> None:
    """Each document takes the `nocite` of its own files: a supplement file's prints in the
    supplement and not in the main text."""
    _nocite_in(project, "supplementary/S1_code_lists.md", value)
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    supplement = build_document(proj, assembled, mode=OFFLINE, supplementary=True)
    assert _printed(supplement.output) == printed
    main = build_document(proj, assembled, mode=OFFLINE)
    assert _printed(main.output) == set()


@needs_pandoc
def test_the_main_text_s_nocite_is_not_the_supplement_s(project: Path) -> None:
    _nocite_in(project, "main.md", "@*")
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    assert _printed(build_document(proj, assembled, mode=OFFLINE).output) == {"Zeta", "Alpha"}
    supplement = build_document(proj, assembled, mode=OFFLINE, supplementary=True)
    assert _printed(supplement.output) == set()


@needs_pandoc
def test_a_live_build_of_files_that_declare_nocite_warns_that_it_leaves_them_out(
    project: Path, monkeypatch, tmp_path: Path
) -> None:
    """Better BibTeX's filter does not read `nocite`, and Zotero's bibliography field lists
    the works cited only: a live build cannot print the works a `nocite` names, and says
    so of each file that declares one, with the offline build that prints them. A filter
    that makes no field stands in for Better BibTeX's."""
    from manuscript_guard.build import document
    from manuscript_guard.findings import WARN
    from manuscript_guard.zotero import READY, Readiness, client

    lua = tmp_path / "zotero.lua"
    lua.write_text("return {}", encoding="utf-8")
    monkeypatch.setattr(document, "ensure_zotero_lua", lambda _cache: lua)
    monkeypatch.setattr(document, "_zotero_version", lambda: None)
    monkeypatch.setattr(client, "readiness", lambda keys, timeout=5: Readiness(READY))

    def warned(supplementary: bool = False) -> list:
        proj, namespace, results, _lit = loaded(project)
        assembled, _ = assemble(proj, namespace, results)
        built = build_document(proj, assembled, mode=LIVE, supplementary=supplementary)
        return [f for f in built.report.findings if f.code == "nocite-not-live"]

    assert warned() == [], "no file declares one yet"
    _nocite_in(project, "main.md", "@*")
    (finding,) = warned()
    assert finding.severity == WARN and finding.gate == "BUILD"
    assert finding.path.resolve() == (project / "manuscript" / "main.md").resolve()
    assert "live build leaves out" in finding.message, finding.message
    assert "every entry" in finding.message, finding.message
    assert "manuscript-guard build --offline" in finding.hint, finding.hint
    assert warned(supplementary=True) == [], "the supplement's files declare none"
    # A supplement file's own, of a key nothing cites: the supplement's build says so.
    _nocite_in(project, "supplementary/S1_code_lists.md", "@zeta2001")
    (finding,) = warned(supplementary=True)
    assert finding.path.name == "S1_code_lists.md" and "@zeta2001" in finding.message


def _live_nocite_warnings(project: Path, monkeypatch, tmp_path: Path) -> list:
    """The `nocite-not-live` findings of a live build of the main text, a filter that makes
    no field standing in for Better BibTeX's."""
    from manuscript_guard.build import document
    from manuscript_guard.zotero import READY, Readiness, client

    lua = tmp_path / "zotero.lua"
    lua.write_text("return {}", encoding="utf-8")
    monkeypatch.setattr(document, "ensure_zotero_lua", lambda _cache: lua)
    monkeypatch.setattr(document, "_zotero_version", lambda: None)
    monkeypatch.setattr(client, "readiness", lambda keys, timeout=5: Readiness(READY))
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    built = build_document(proj, assembled, mode=LIVE)
    return [f for f in built.report.findings if f.code == "nocite-not-live"]


@needs_pandoc
@pytest.mark.parametrize("value", ["~", "null", "email@*", "@fictionalHepaticCohort2021",
                                   "@{a b}"])  # fmt: skip
def test_a_live_build_does_not_warn_of_a_nocite_that_leaves_nothing_out(
    project: Path, monkeypatch, tmp_path: Path, value: str
) -> None:
    """Round 1 of #852: the warning came of every `nocite` not blank. A null names no work,
    nor does an address, and a key the text cites prints in a live build as well: none
    leaves a work out, and none is warned of. The keys are read as the build reads a
    citation (`zotero.find_citations`), `@*` as G7 reads it. Pandoc 3.9 reads no citation
    in a braced key that holds a space, `@{a b}`, in the text or under `nocite`."""
    _nocite_in(project, "main.md", value)
    assert _live_nocite_warnings(project, monkeypatch, tmp_path) == []


@needs_pandoc
@pytest.mark.parametrize("value", ["['@fictionalHepaticCohort2021', '@zeta2001']",
                                   "@2019who", "@_x", "@{zeta.2001}"])  # fmt: skip
def test_a_live_build_names_the_keys_a_nocite_names_that_nothing_cites(
    project: Path, monkeypatch, tmp_path: Path, value: str
) -> None:
    """A key pandoc reads and `find_citations` does not, one that opens with a digit or
    `_`, or a braced one, is taken for a work the text does not cite (round 2 of #852)."""
    _nocite_in(project, "main.md", value)
    (finding,) = _live_nocite_warnings(project, monkeypatch, tmp_path)
    key = {"@2019who": "@2019who", "@_x": "@_x", "@{zeta.2001}": "@zeta.2001"}.get(
        value, "@zeta2001")
    assert key in finding.message, finding.message
    assert "fictionalHepaticCohort2021" not in finding.message, finding.message


#: Entries under keys pandoc reads and `find_citations` does not.
_UNREAD_KEYS = (
    "\n@article{2019who,\n  author = {Who, Wanda}, title = {V}, year = {2019},\n}\n"
    "\n@article{_x,\n  author = {Under, Una}, title = {W}, year = {2018},\n}\n"
    "\n@article{zeta.2001,\n  author = {Braced, Bea}, title = {X}, year = {2017},\n}\n"
)


@needs_pandoc
@pytest.mark.parametrize(("value", "printed"), [
    ("null", None), ("~", None), ("email@*", None), ("@{a b}", None), ("@zeta2001", "Zeta"),
    ("@2019who", "Who"), ("@_x", "Under"), ("@{zeta.2001}", "Braced"),
])  # fmt: skip
def test_a_supplement_citing_nothing_is_given_a_reference_heading_only_for_a_work_its_nocite_names(
    project: Path, value: str, printed: str | None
) -> None:
    """Round 1 of #852: `references_heading.lua` runs before citeproc and puts its heading
    over the `refs` div whether citeproc fills it or not, so a supplement that cites
    nothing, under a `nocite` that names no work, printed a heading over an empty list. The
    filter is run for a `nocite` only where it names a key or asks for every entry; a key
    pandoc reads and `find_citations` does not names one too (round 2)."""
    from manuscript_guard.docxtext import BUILT_HEADING

    _nocite_in(project, "supplementary/S1_code_lists.md", value)
    bib = project / "literature" / "references.bib"
    bib.write_text(bib.read_text(encoding="utf-8") + _UNREAD_KEYS, encoding="utf-8")
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    built = build_document(proj, assembled, mode=OFFLINE, supplementary=True)
    xml = zipfile.ZipFile(built.output).read("word/document.xml").decode("utf-8")
    assert (f'w:name="{BUILT_HEADING}"' in xml) == (printed is not None), xml[-2000:]
    names = ("Zeta", "Alpha", "Who", "Under", "Braced")
    shown = {name for name in names if f"{name}, " in docx_text(built.output)}
    assert shown == ({printed} if printed else set()), shown


@needs_pandoc
def test_an_offline_build_does_not_take_the_supplement_s_nocite_for_a_citation(
    project: Path, monkeypatch, capsys
) -> None:
    """Round 1 of #852: the console's word on an offline build's citations read the whole
    of `build/supplementary.md`, header and all, so a supplement that cites nothing, with
    `nocite: '@zeta2001'` in its header, was said to cite zeta2001, and Zotero was asked for
    it. The text after the header is read."""
    from types import SimpleNamespace

    from manuscript_guard import cli
    from manuscript_guard.zotero import client

    _nocite_in(project, "supplementary/S1_code_lists.md", "@zeta2001")
    proj, namespace, results, _lit = loaded(project)
    assembled, _ = assemble(proj, namespace, results)
    supplement = build_document(proj, assembled, mode=OFFLINE, supplementary=True)
    assert "zeta2001" in (proj.path("build") / "supplementary.md").read_text(encoding="utf-8")
    asked: list[tuple[str, ...]] = []
    monkeypatch.setattr(client, "readiness", lambda keys, timeout=5: asked.append(keys))
    cli._said_offline_citations(proj, SimpleNamespace(citations=()), supplement.output)
    assert asked == [] and capsys.readouterr().out == ""


@needs_pandoc
@needs_zotero
@pytest.mark.real_zotero
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


def styled_captions(markdown: str) -> list[str]:
    """The text of each paragraph `figure_caption.lua` sets in the caption style, as pandoc
    reads `markdown` with it."""
    import json
    import subprocess

    from manuscript_guard.build.document import FIGURE_CAPTION_LUA, pandoc

    done = subprocess.run(
        [pandoc(), "-f", "markdown", "-t", "json", "--lua-filter", str(FIGURE_CAPTION_LUA)],
        input=markdown, capture_output=True, text=True, encoding="utf-8", check=True,
    )  # fmt: skip

    def text(node: object) -> str:
        if isinstance(node, list):
            return "".join(text(item) for item in node)
        if not isinstance(node, dict):
            return ""
        if node.get("t") == "Str":
            return node["c"]
        if node.get("t") in ("Space", "SoftBreak"):
            return " "
        return text(node.get("c"))

    return [
        text(block["c"][1])
        for block in json.loads(done.stdout)["blocks"]
        if block["t"] == "Div" and ["custom-style", "Figure Caption"] in block["c"][0][2]
    ]


@needs_pandoc
@pytest.mark.parametrize(
    "caption",
    ["Figure 1. The estimate.", "**Fig. 1.** The estimate.", "Fig. S2: The estimate.",
     "eFigure 3. The estimate.", "**eFigure S1.** The estimate."],
)  # fmt: skip
def test_a_caption_opening_fig_or_efigure_is_styled_as_one(caption: str) -> None:
    """Known gaps: G2 holds "Fig. 1." and "eFigure 1." as a figure's caption, and the build
    set only "Figure 1." in the caption's style; the others were set in the body font."""
    found = styled_captions(f"![](figure.png)\n\n{caption}\n")
    assert found == [caption.replace("**", "")], found


@needs_pandoc
@pytest.mark.parametrize(
    "prose",
    ["Fig. 1 shows the estimate.", "eFigure 2 shows it.", "Fig. 2.5-fold higher.",
     "Figs. 1. The estimate.", "Fig 1. The estimate.", "efigure 1. The estimate."],
)  # fmt: skip
def test_prose_opening_fig_or_efigure_under_a_figure_is_not_its_caption(prose: str) -> None:
    assert styled_captions(f"![](figure.png)\n\n{prose}\n") == []


@needs_pandoc
@pytest.mark.parametrize(
    ("markdown", "styled"),
    [
        ("![](figure.png)\n\nFigure 4: The estimate.\n", True),
        ("![](figure.png)\n\nFigure S1. The estimate.\n", True),
        ("![](figure.png)\n\nFig. 1. The estimate.\n", True),
        ("![](figure.png)\n\neFigure 1. The estimate.\n", True),
        # left at body size
        ("![](figure.png)\n\nFig 1. The estimate.\n", False),
        ("![](figure.png)\n\nFigure one. The estimate.\n", False),
        ("![](figure.png)\n\nFigure 1.1. The estimate.\n", False),
        ("![](figure.png)\n\nSupplementary Figure 1. The estimate.\n", False),
        ("![](figure.png)\n\nFigure 1 - the estimate.\n", False),
        ("![](figure.png)\n\n**Figure 1** The estimate.\n", False),
        ("![](figure.png)\n\n<!-- a note -->\n\nFigure 1. The estimate.\n", False),
        ("See ![](figure.png) here.\n\nFigure 1. The estimate.\n", False),
    ],
)
def test_the_caption_style_reads_one_convention_and_nothing_else(
    markdown: str, styled: bool
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The figure-caption style reads one convention
    and nothing else"): under a figure, "Figure 4:", "Figure S1.", "Fig. 1." and "eFigure
    1." are styled; "Fig 1.", "Figure one.", "Figure 1.1.", the other forms G2 holds, a
    caption a comment separates from its figure, and one under an image in a paragraph of
    text are left at body size. The 2026-11-09 triage planned a fix (F08), which will
    change this test."""
    found = styled_captions(markdown)
    caption = markdown.rsplit("\n\n", 1)[1].strip().replace("**", "")
    assert found == ([caption] if styled else []), found


def _pixel() -> bytes:
    """A PNG of one white pixel."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        size, crc = struct.pack(">I", len(data)), struct.pack(">I", zlib.crc32(kind + data))
        return size + kind + data + crc

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b"")
    )  # fmt: skip


@needs_pandoc
def test_pandoc_s_own_caption_and_a_quoted_one_are_styled_as_the_known_gap_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The figure-caption style reads one convention
    and nothing else"): a figure with pandoc's own caption keeps `Image Caption`, which the
    build's reference document does not size, nor the `Caption` it is based on; a caption
    in a block quotation takes `Figure Caption` in place of `Block Text`; a table's caption
    is untouched. The build's reference document is made from pandoc's own: pandoc's user
    data folder is pointed at an empty one, as XDG_DATA_HOME points it, so that no
    `reference.docx` of whoever runs the test is read. The 2026-11-09 triage planned a fix
    (F08), which will change this test."""
    import re
    import subprocess

    from manuscript_guard.build.document import FIGURE_CAPTION_LUA, pandoc
    from manuscript_guard.build.styles import reference_with, user_reference

    # Its `pandoc` folder made, or pandoc falls back to its older user data folder.
    (tmp_path / "data-home" / "pandoc").mkdir(parents=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data-home"))
    assert user_reference(pandoc()) is None
    (tmp_path / "figure.png").write_bytes(_pixel())
    reference = reference_with(pandoc(), tmp_path / "reference.docx")
    markdown = (
        "![Own caption words.](figure.png)\n\n"
        "> ![](figure.png)\n>\n> Figure 1. Quoted caption words.\n\n"
        "> Quoted prose words.\n\n"
        "| A | B |\n|---|---|\n| x | y |\n\n: Table caption words.\n"
    )
    output = tmp_path / "out.docx"
    subprocess.run(
        [pandoc(), "-f", "markdown", "-o", str(output), "--lua-filter", str(FIGURE_CAPTION_LUA),
         f"--reference-doc={reference}", f"--resource-path={tmp_path}"],
        input=markdown, text=True, encoding="utf-8", check=True, capture_output=True,
    )  # fmt: skip

    def style_of(words: str) -> str:
        for paragraph in _paragraphs(output):
            if words in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", paragraph)):
                found = re.search(r'<w:pStyle w:val="([^"]+)"', paragraph)
                return found.group(1) if found else ""
        raise AssertionError(f"{words!r} is not in the document")

    assert style_of("Own caption words.") == "ImageCaption"
    assert style_of("Quoted caption words.") == "FigureCaption"
    assert style_of("Quoted prose words.") == "BlockText"
    assert style_of("Table caption words.") == "TableCaption"
    styles = _styles(output)
    for style in ("ImageCaption", "Caption"):
        defined = re.search(
            rf'<w:style [^>]*w:styleId="{style}".*?</w:style>', styles, re.DOTALL
        )
        assert defined is not None and "<w:sz " not in defined.group(0), (style, defined)
    image = re.search(r'<w:style [^>]*w:styleId="ImageCaption".*?</w:style>', styles, re.DOTALL)
    assert image is not None, styles
    assert '<w:basedOn w:val="Caption"/>' in image.group(0).replace(" />", "/>"), image


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


def _pictures(path: Path) -> list[str]:
    """The alternative text of each picture in a built document, as Word reads it."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    wp = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
    return [node.get("descr", "") for node in root.iter(f"{wp}docPr")]


def _with_alt(project: Path, alt: str | None) -> Path:
    import yaml

    sidecar = project / "figures" / "forest.guard.yaml"
    guard = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    guard.pop("alt", None)
    if alt is not None:
        guard["alt"] = alt
    sidecar.write_text(yaml.safe_dump(guard, allow_unicode=True), encoding="utf-8")
    proj, namespace, results, _lit = loaded(project)
    assembled, report = assemble(proj, namespace, results)
    assert report.ok, report.render(project)
    return build_document(proj, assembled, mode=OFFLINE).output


@needs_pandoc
def test_a_figures_alternative_text_is_its_pictures_and_printed_nowhere(project: Path) -> None:
    """Pandoc makes an image alone in its paragraph a figure, and prints its description
    under it as a caption. The build places the image in a span, so that the description is
    the picture's alternative text and nothing more: each binding its display."""
    from manuscript_guard.gates.figure_alt import printed_alt, raw_alt

    proj, namespace, _results, _lit = loaded(project)
    expected = printed_alt(raw_alt(proj, "forest"), namespace)
    assert namespace["results.ror.point"].display in expected and "{{" not in expected
    output = _with_alt(project, raw_alt(proj, "forest"))
    assert _pictures(output) == [expected]
    assert "Forest plot of" not in docx_text(output)


@needs_pandoc
def test_alternative_text_is_written_as_typed_whatever_markup_it_holds(project: Path) -> None:
    """Each ASCII punctuation mark is escaped, so pandoc reads none as markup: not emphasis,
    a link, a citation, maths, a quotation mark to curl, raw HTML or a comment. Its line
    breaks are one space, since a description is one line."""
    typed = (
        'Odds *rose* [twice](x.png) for @citekey and $x^2$ with `code`, <b>bold</b> &amp; '
        '"quoted" -- 50% ... ^up^ ~down~ \\ a <!-- comment --> end.'
    )
    output = _with_alt(project, typed.replace(" for ", "\nfor "))
    assert _pictures(output) == [typed]


@needs_pandoc
def test_a_no_break_space_in_alternative_text_is_kept(project: Path) -> None:
    """Round 1 of #387: the text was folded with `str.split`, which takes a no-break space
    for white space, and "10 mg" went out with the line free to break between them."""
    typed = "A dose of 10\N{NO-BREAK SPACE}mg and 95\N{NARROW NO-BREAK SPACE}%."
    assert _pictures(_with_alt(project, typed)) == [typed]


@needs_pandoc
def test_a_figure_with_no_alternative_text_is_placed_as_before(project: Path) -> None:
    output = _with_alt(project, None)
    assert _pictures(output) == [""]


@needs_pandoc
def test_the_caption_after_a_figure_with_alternative_text_or_none_is_styled(
    project: Path,
) -> None:
    """`figure_caption.lua` knows a figure's paragraph by its one image, and with
    alternative text the image is inside the build's span: the caption under it went on
    being set in the body font until the filter was taught the span."""
    import re

    for alt in ("A dot and its interval on a log scale.", None):
        _with_alt(project, alt)
        output = _captioned(project)
        styled = [p for p in _paragraphs(output) if 'w:val="FigureCaption"' in p]
        assert len(styled) == 1, alt
        assert "What the figure shows" in "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", styled[0]))


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
