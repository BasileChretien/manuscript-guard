"""A checklist read from the table of the paper that published it, in Europe PMC's JATS XML.

Every fixture here is invented: a two-section checklist for an imaginary guideline. No text
from any published checklist is in the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manuscript_guard.reporting import RecipeError, build_profile, load_recipe
from manuscript_guard.reporting.build import rows_digest_of
from manuscript_guard.reporting.jats import article_text, rows_digest, table_rows

ARTICLE = """<?xml version="1.0" encoding="UTF-8"?><article xml:lang="en"><front><article-meta>
<article-id pub-id-type="pmcid">PMC0000001</article-id></article-meta></front><body>
<p>The checklist is in table 2.</p>
<table-wrap id="tbl1"><label>Table 1</label><caption><p>Who wrote it</p></caption>
<table><tbody><tr><td>A panel</td><td>Ten people</td></tr></tbody></table></table-wrap>
<table-wrap id="tbl2" position="float"><label>Table 2</label>
<caption><p>The imaginary checklist</p></caption>
<table frame="hsides" rules="groups">
<thead><tr><th>Section/topic</th><th>Item</th><th>Checklist item</th></tr></thead>
<tbody>
<tr><td colspan="3">Title</td></tr>
<tr><td>Title</td><td>1</td><td>Name the study as one of its kind in the title</td></tr>
<tr><td colspan="3">Methods</td></tr>
<tr><td rowspan="2">Data</td><td>2a</td>
<td>Describe where the data came from<break/>and when</td></tr>
<tr><td>2b</td>
<td>Give the dates of <italic>every</italic> extraction<xref rid="t2fn1">*</xref></td></tr>
<tr><td>Analysis</td><td>3</td><td>Explain how the model was chosen and fitted</td></tr>
</tbody></table>
<table-wrap-foot><fn id="t2fn1"><p>*Where it applies.</p></fn></table-wrap-foot>
</table-wrap></body></article>
"""

ROWS = [
    ["Title", "", ""],
    ["Title", "1", "Name the study as one of its kind in the title"],
    ["Methods", "", ""],
    ["Data", "2a", "Describe where the data came from and when"],
    ["", "2b", "Give the dates of every extraction*"],
    ["Analysis", "3", "Explain how the model was chosen and fitted"],
]


def _article(folder: Path, text: str = ARTICLE, name: str = "paper.xml") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def _recipe(folder: Path, **change) -> Path:
    meta = {
        "name": "IMAGINARY",
        "source_url": "https://example.invalid/paper",
        "read_from": "Table 2 of the statement paper, from its Europe PMC full text",
        "retrieved_on": "2026-10-16",
        "licence": "CC BY 4.0",
        "download_url": "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC0000001/fullTextXML",
        **change.pop("meta", {}),
    }
    document = {"schema": "manuscript-guard/recipe/1", "meta": meta, "format": "jats-table",
                "table": "tbl2", "document": "paper.xml", "header_rows": 0, "topic_column": 0,
                "id_column": 1, "text_column": 2, **change}  # fmt: skip
    path = folder / "IMAGINARY.recipe.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_a_table_is_read_as_rows_with_its_spans_laid_out(tmp_path: Path) -> None:
    """A heading spans the row; a topic spans the rows below it. Either way the recipe's
    column numbers mean the same column in every row."""
    head, body = table_rows(_article(tmp_path), "tbl2")
    assert head == [["Section/topic", "Item", "Checklist item"]]
    assert body == ROWS


@pytest.mark.parametrize("which", ["tbl2", "Table 2", "table 2", "TABLE 2."])
def test_a_table_is_named_by_its_id_or_its_label(tmp_path: Path, which: str) -> None:
    assert table_rows(_article(tmp_path), which)[1] == ROWS


def test_a_table_not_there_is_refused_with_the_tables_that_are(tmp_path: Path) -> None:
    with pytest.raises(RecipeError, match=r"no table named 'Table 3'.*tbl1 \(Table 1\), tbl2"):
        table_rows(_article(tmp_path), "Table 3")


def test_the_digest_is_of_the_rows_not_the_bytes(tmp_path: Path) -> None:
    """Europe PMC can regenerate its XML. Attributes, whitespace between elements and a new
    metadata element change the bytes and nothing the recipe reads; a word changes both."""
    digest = rows_digest(*table_rows(_article(tmp_path), "tbl2"))
    regenerated = (
        ARTICLE.replace(' position="float"', "")
        .replace("<tbody>\n", "<tbody>\n\n  ")
        .replace("</article-meta>", "<pub-date><year>2026</year></pub-date></article-meta>")
    )
    assert rows_digest(*table_rows(_article(tmp_path, regenerated), "tbl2")) == digest
    revised = ARTICLE.replace("chosen and fitted", "chosen, fitted and checked")
    assert rows_digest(*table_rows(_article(tmp_path, revised), "tbl2")) != digest


def test_a_line_break_in_a_cell_does_not_join_two_words(tmp_path: Path) -> None:
    assert "came from and when" in article_text(_article(tmp_path))


PUBLIC = (
    '\n<!DOCTYPE article\n  PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange'
    ' DTD v1.3 20210610//EN" "JATS-archivearticle1-3.dtd">\n'
)


def test_the_document_type_some_full_texts_open_with_is_set_aside(tmp_path: Path) -> None:
    """Some of Europe PMC's full texts name the JATS DTD at the top. Nothing is fetched from
    it and there is nothing in it to expand, so the article is read as one without it."""
    for doctype in (PUBLIC, '<!DOCTYPE article SYSTEM "x.dtd">', "<!DOCTYPE article>"):
        named = ARTICLE.replace("?>", "?>" + doctype, 1)
        assert table_rows(_article(tmp_path, named), "tbl2")[1] == ROWS


@pytest.mark.parametrize(
    "doctype",
    [
        '<!DOCTYPE article [<!ENTITY a "aaaaaaaaaa">]>',
        '<!DOCTYPE article SYSTEM "x.dtd" [<!ENTITY a "aaaaaaaaaa">]>',
        '<!DOCTYPE article SYSTEM "x.dtd"><!DOCTYPE article SYSTEM "y.dtd">',
        '<!DOCTYPE html SYSTEM "x.dtd">',
    ],
)
def test_a_document_that_declares_more_is_refused(tmp_path: Path, doctype: str) -> None:
    from manuscript_guard.safexml import UnsafeDocument

    with pytest.raises(UnsafeDocument, match="DTD"):
        table_rows(_article(tmp_path, ARTICLE.replace("?>", "?>" + doctype, 1)), "tbl2")


def test_a_declaration_past_the_first_8_kb_is_refused_too(tmp_path: Path) -> None:
    """Round 1 of #294: the parser's own check reads the first 8 KB, and a document type with
    an entity after a long comment was parsed, its entity read into a row."""
    from manuscript_guard.safexml import UnsafeDocument

    hidden = ARTICLE.replace(
        "?>", "?><!--" + "x" * 9000 + '--><!DOCTYPE article [<!ENTITY e "Injected">]>', 1
    ).replace("<td>Analysis</td>", "<td>&e;</td>")
    with pytest.raises(UnsafeDocument, match="DTD or an entity"):
        table_rows(_article(tmp_path, hidden), "tbl2")


def test_a_full_text_not_in_utf_8_is_refused(tmp_path: Path) -> None:
    from manuscript_guard.safexml import UnsafeDocument

    path = tmp_path / "paper.xml"
    path.write_bytes(ARTICLE.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16"))
    with pytest.raises(UnsafeDocument, match="not UTF-8"):
        table_rows(path, "tbl2")


def test_transcribe_says_a_broken_download_is_one_and_goes_on(tmp_path: Path, capsys) -> None:
    """Round 1 of #294: an unsafe or malformed document was a traceback, not a line."""
    from manuscript_guard.cli import main

    root = tmp_path / "paper"
    folder = root / "profiles" / "reporting"
    (folder / "sources").mkdir(parents=True)
    (folder / "recipes").mkdir()
    (root / "paper.yaml").write_text('schema: manuscript-guard/paper/1\ntitle: "T"\n', "utf-8")
    _article(folder / "sources", "<?xml version='1.0'?><article><p>cut short")
    _recipe(folder / "recipes")
    assert main(["transcribe", "IMAGINARY", "--root", str(root)]) == 1
    assert "IMAGINARY.recipe.yaml:" in capsys.readouterr().out


def test_a_document_with_another_root_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecipeError, match="not a JATS article"):
        table_rows(_article(tmp_path, "<?xml version='1.0'?><html><body/></html>"), "tbl2")


def test_a_span_past_any_checklist_is_capped(tmp_path: Path) -> None:
    wide = ARTICLE.replace('<td colspan="3">Title</td>', '<td colspan="999999">Title</td>')
    head, body = table_rows(_article(tmp_path, wide), "tbl2")
    assert len(body[0]) == 64


def test_a_profile_is_built_from_the_paper_s_table(tmp_path: Path) -> None:
    _article(tmp_path)
    recipe = _recipe(tmp_path)
    path, count, unverified = build_profile(recipe, tmp_path, tmp_path / "out")
    assert (count, unverified) == (4, [])
    profile = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert [item["id"] for item in profile["items"]] == ["1", "2a", "2b", "3"]
    assert [item["topic"] for item in profile["items"]] == ["Title", "Data", "Data", "Analysis"]
    assert profile["read_from"].startswith("Table 2 of the statement paper")
    assert profile["verification"] == "every item verified verbatim in the source"
    from manuscript_guard.contracts import validate

    assert validate(profile, "reporting", path).ok


def test_a_changed_table_stops_the_transcription_and_a_reformatted_one_does_not(
    tmp_path: Path,
) -> None:
    digest = rows_digest(*table_rows(_article(tmp_path), "tbl2"))
    recipe = _recipe(tmp_path, meta={"rows_sha256": digest})
    build_profile(recipe, tmp_path, tmp_path / "out")
    _article(tmp_path, ARTICLE.replace(' frame="hsides"', ""))
    build_profile(recipe, tmp_path, tmp_path / "out")
    _article(tmp_path, ARTICLE.replace("<td>3</td>", "<td>4</td>"))
    with pytest.raises(RecipeError, match="its rows have changed"):
        build_profile(recipe, tmp_path, tmp_path / "out")
    build_profile(recipe, tmp_path, tmp_path / "out", allow_changed=True)


def test_the_bytes_digest_of_a_paper_is_not_held(tmp_path: Path) -> None:
    """A sha256 of the bytes would stop the transcription on every regeneration."""
    _article(tmp_path)
    recipe = _recipe(tmp_path, meta={"sha256": "0" * 64})
    build_profile(recipe, tmp_path, tmp_path / "out")


@pytest.mark.parametrize(
    ("change", "refusal"),
    [({"meta": {"read_from": ""}}, "meta.read_from"), ({"table": ""}, "names its `table`")],
)
def test_a_paper_table_recipe_says_what_it_read(tmp_path: Path, change: dict, refusal: str) -> None:
    with pytest.raises(RecipeError, match=refusal):
        load_recipe(_recipe(tmp_path, **change))


def test_transcribe_prints_the_rows_digest_a_new_recipe_lacks(tmp_path: Path, capsys) -> None:
    from manuscript_guard.cli import main

    root = tmp_path / "paper"
    folder = root / "profiles" / "reporting"
    (folder / "sources").mkdir(parents=True)
    (folder / "recipes").mkdir()
    (root / "paper.yaml").write_text('schema: manuscript-guard/paper/1\ntitle: "T"\n', "utf-8")
    _article(folder / "sources")
    _recipe(folder / "recipes")
    digest = rows_digest_of(folder / "recipes" / "IMAGINARY.recipe.yaml", folder / "sources")
    assert main(["transcribe", "IMAGINARY", "--root", str(root)]) == 0
    assert f"rows_sha256: {digest}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [b"<!DOCTYPE html><html><body>Not found</body></html>",
     b"<?xml version='1.0'?><responseWrapper><hitCount>0</hitCount></responseWrapper>"],
)  # fmt: skip
def test_fetch_refuses_what_is_not_a_paper_s_full_text(tmp_path: Path, payload: bytes) -> None:
    from manuscript_guard.reporting.fetch import FetchError, _reject_wrong_type

    with pytest.raises(FetchError, match="not a JATS article|other than a JATS article"):
        _reject_wrong_type("https://example.invalid/x", tmp_path / "paper.xml", payload)
    _reject_wrong_type("https://example.invalid/x", tmp_path / "paper.xml", ARTICLE.encode())


# ------------------------------------------------------------------ the shipped recipes


def _shipped() -> list[Path]:
    from manuscript_guard.paths import SHIPPED_RECIPES

    return sorted(SHIPPED_RECIPES.glob("*.recipe.yaml"))


@pytest.mark.parametrize("path", _shipped(), ids=lambda p: p.name)
def test_every_shipped_recipe_loads_and_names_itself(path: Path) -> None:
    _recipe_, meta = load_recipe(path)
    assert meta["name"] == path.name.split(".recipe")[0]
    replaced = meta.get("superseded_by")
    if replaced:
        assert any(p.name == f"{replaced}.recipe.yaml" for p in _shipped()), replaced
    if meta["_layout"]["format"] == "jats-table":
        assert len(meta.get("rows_sha256", "")) == 64
        assert meta["download_url"].startswith("https://www.ebi.ac.uk/europepmc/")
