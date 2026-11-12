"""The rows reader: a checklist table in a PDF, read from where each word sits.

The pages here are written as `pdftotext -bbox` writes them, word by word with each word's
box, and the checklists on them are invented: this repository ships recipes and not checklist
text, and a page of one's own can hold the shapes a published one happens to hold once.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from manuscript_guard.reporting import RecipeError, build_profile
from manuscript_guard.reporting.rows import RowsRecipe, joined, transcribe_rows

#: The height of every invented line, in points, and the step from one line to the next.
HEIGHT = 12.0
STEP = 18.0

CENTRED_COLUMNS = {"section": 0, "id": 85, "text": 135, "blank": 480}
TOPIC_COLUMNS = {"section": 0, "text": 70, "form": 280}


def bbox(*lines: tuple[float, float, str]) -> str:
    """A page as `pdftotext -bbox` writes it: each (x, top, words) a line of words."""
    words = []
    for x, top, text in lines:
        at = x
        for word in text.split():
            escaped = word.replace("&", "&amp;").replace('"', "&quot;")
            words.append(
                f'    <word xMin="{at:.6f}" yMin="{top:.6f}" xMax="{at + 5 * len(word):.6f}" '
                f'yMax="{top + HEIGHT:.6f}">{escaped}</word>'
            )
            at += 5 * len(word) + 3
    return (
        '<!DOCTYPE html><html><head><title>t</title></head><body><doc>\n'
        '  <page width="595.000000" height="842.000000">\n'
        + "\n".join(words)
        + "\n  </page>\n</doc></body></html>\n"
    )


def centred(number: str, top: float, *text: str, x: float = 140) -> list[tuple]:
    """An item as Word sets a centred number against lines of text starting at `top`."""
    lines = [(x, top + i * STEP, line) for i, line in enumerate(text)]
    middle_line = top + (len(text) - 1) * STEP / 2
    return [*lines, (104, middle_line, number)]


def pages_are(monkeypatch: pytest.MonkeyPatch, pages: dict[int, str]) -> None:
    from manuscript_guard.reporting import columns

    monkeypatch.setattr(columns, "run_pdftotext", lambda _path, page, *_options: pages[page])


def recipe(**layout) -> RowsRecipe:
    defaults = {"rows": "centred-id", "columns": CENTRED_COLUMNS, "pages": [1]}
    return RowsRecipe.from_layout("x.pdf", {**defaults, **layout})


#: An invented table of four items under two headings, set as Word sets SAGER's: a one-line
#: item, a two-line item whose number stands between its lines, a three-line item whose number
#: shares the middle line, and a two-line item straight after it with nothing between.
TABLE_LINES = (
    (34, 50, "Item number Text Reported on"),
    (34, 70, "topic number page number"),
    (34, 100, "Opening"),
    *centred("1", 130, "The thing is named plainly"),
    (34, 160, "Middle"),
    *centred("2a", 190, "The thing is measured where it", "can be measured"),
    *centred(
        "2b", 226, "The thing is compared with the", "other thing, and the difference", "is stated"
    ),
    *centred("2c", 280, "Each measure is given with", "its unit"),
    (34, 330, "An invented footnote under the table"),
    (94, 800, "Imaginary Checklist"),
)
TABLE = bbox(*TABLE_LINES)


def read_table(monkeypatch: pytest.MonkeyPatch, page: str = TABLE, items: int = 4, **layout):
    pages_are(monkeypatch, {1: page})
    return transcribe_rows(
        Path("x.pdf"),
        recipe(
            items=items,
            start_after="topic number page number",
            stop_at="An invented footnote under the table",
            ignore=["Imaginary Checklist"],
            **layout,
        ),
    )


# ---------------------------------------------------------------- numbers centred on their text


def test_each_number_takes_the_run_of_lines_centred_on_it(monkeypatch: pytest.MonkeyPatch) -> None:
    items = read_table(monkeypatch)
    assert [(i.id, i.section, i.text) for i in items] == [
        ("1", "Opening", "The thing is named plainly"),
        ("2a", "Middle", "The thing is measured where it can be measured"),
        ("2b", "Middle",
         "The thing is compared with the other thing, and the difference is stated"),
        ("2c", "Middle", "Each measure is given with its unit"),
    ]


def test_a_row_broken_across_pages_carries_on_above_the_next_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Word breaks a row at the page and sets its number against the part above the break, so
    the lines at the top of the next page, above its first heading, have no number of their
    own."""
    first = bbox(
        (34, 70, "topic number page number"),
        (34, 100, "Opening"),
        *centred("1", 130, "The thing is named plainly,", "where it has a", "name of its own"),
    )
    second = bbox(
        (140, 60, "and its other names are"),
        (140, 78, "given too"),
        (34, 110, "Closing"),
        *centred("2", 140, "The thing is put away"),
    )
    pages_are(monkeypatch, {1: first, 2: second})
    items = transcribe_rows(
        Path("x.pdf"), recipe(pages=[1, 2], items=2, start_after="topic number page number")
    )
    assert items[0].text == (
        "The thing is named plainly, where it has a name of its own and its other names are "
        "given too"
    )
    assert [i.id for i in items] == ["1", "2"]


def test_an_item_whole_at_the_top_of_a_page_is_read_by_its_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Where a number stands above the page's first heading, the lines there are its run and
    carry nothing on."""
    first = bbox(
        (34, 70, "topic number page number"),
        (34, 100, "Opening"),
        *centred("1", 130, "The thing is named plainly"),
    )
    second = bbox(*centred("2", 60, "The thing is weighed", "and the weight is given"))
    pages_are(monkeypatch, {1: first, 2: second})
    items = transcribe_rows(
        Path("x.pdf"), recipe(pages=[1, 2], items=2, start_after="topic number page number")
    )
    assert [(i.id, i.text) for i in items] == [
        ("1", "The thing is named plainly"),
        ("2", "The thing is weighed and the weight is given"),
    ]


def test_a_line_no_number_takes_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    page = bbox(*TABLE_LINES, (140, 316, "a stray line"))
    with pytest.raises(RecipeError, match="'a stray line' is in no item's run"):
        read_table(monkeypatch, page)


def test_a_number_no_run_is_centred_on_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    page = bbox(
        (34, 70, "topic number page number"),
        (34, 100, "Opening"),
        (140, 130, "The thing is named plainly"),
        (140, 148, "and briefly"),
        (104, 160, "1"),
    )
    with pytest.raises(RecipeError, match="no run of lines is centred on item 1"):
        pages_are(monkeypatch, {1: page})
        transcribe_rows(Path("x.pdf"), recipe(items=1, start_after="topic number page number"))


def test_a_number_that_is_not_one_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RecipeError, match="'2b.' is not an item's number"):
        read_table(monkeypatch, TABLE.replace(">2b<", ">2b.<"))


def test_a_heading_sharing_its_line_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    page = bbox(
        (34, 70, "topic number page number"),
        (34, 100, "Opening"),
        (140, 100, "The thing is named plainly"),
        (104, 100, "1"),
    )
    pages_are(monkeypatch, {1: page})
    with pytest.raises(RecipeError, match="the heading 'Opening' shares its line"):
        transcribe_rows(Path("x.pdf"), recipe(items=1, start_after="topic number page number"))


def test_a_word_in_a_blank_column_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    page = bbox(*TABLE_LINES, (500, 130, "p.4"))
    with pytest.raises(RecipeError, match="'p.4' stands in a column the recipe says is blank"):
        read_table(monkeypatch, page)


@pytest.mark.parametrize(
    ("layout", "said"),
    [
        ({"start_after": "no such line"}, "no line reads 'no such line', where the recipe starts"),
        ({"stop_at": "no such line"}, "no line reads 'no such line', where the recipe stops"),
    ],
    ids=["start", "stop"],
)
def test_a_boundary_the_page_does_not_print_is_refused(
    layout: dict, said: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages_are(monkeypatch, {1: TABLE})
    settings = {
        "items": 4,
        "start_after": "topic number page number",
        "stop_at": "An invented footnote under the table",
        "ignore": ["Imaginary Checklist"],
        **layout,
    }
    with pytest.raises(RecipeError, match=said):
        transcribe_rows(Path("x.pdf"), recipe(**settings))


def test_the_running_foot_is_read_unless_it_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """The foot starts in the number column, so read it is a number that is not one."""
    without_footnote = [line for line in TABLE_LINES if not line[2].startswith("An invented")]
    pages_are(monkeypatch, {1: bbox(*without_footnote)})
    with pytest.raises(RecipeError, match="'Imaginary' is not an item's number"):
        transcribe_rows(
            Path("x.pdf"), recipe(items=4, start_after="topic number page number")
        )


def test_a_count_other_than_the_recipes_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RecipeError, match="4 items read, and the recipe says the checklist has 5"):
        read_table(monkeypatch, items=5)


def test_a_number_read_twice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RecipeError, match="item 2a is read twice"):
        read_table(monkeypatch, TABLE.replace(">2b<", ">2a<"))


# ---------------------------------------------------------------- rows found by their titles


TOPICS = [
    {"id": "F1", "topic": "Things made"},
    {"id": "F2", "topic": "Things bought"},
    {"id": "G1", "topic": "Things counted"},
]

BOX = "where reported: page or section"

FORM = bbox(
    (52, 40, "For each row, say where it is reported."),
    (52, 70, "Finding:"),
    (77, 100, "Things made"),
    (285, 100, BOX),
    (505, 100, "n/a"),
    (77, 112, "Say what was made, and by"),
    (77, 124, "whom."),
    (77, 136, "Say where it can be had."),
    (77, 160, "Things bought"),
    (285, 155, BOX),
    (285, 166, "or say none were"),
    (77, 172, "Name the seller and the step-"),
    (77, 184, "by-step order."),
    (52, 220, "Gathering"),
    (77, 240, "A paragraph the section opens with, and"),
    (77, 252, "no row's text."),
    (77, 276, "Things counted"),
    (285, 276, BOX),
    (77, 288, "Give the count and how it was made."),
    (290, 780, "2"),
)


def read_form(monkeypatch: pytest.MonkeyPatch, page: str = FORM, topics=None, **layout):
    pages_are(monkeypatch, {1: page})
    settings = {
        "rows": "topics",
        "columns": TOPIC_COLUMNS,
        "items": len(topics or TOPICS),
        "topics": topics or TOPICS,
        "start_after": "For each row, say where it is reported.",
        "marker": "where reported",
        **layout,
    }
    return transcribe_rows(Path("x.pdf"), RowsRecipe.from_layout("x.pdf", settings))


def test_each_row_runs_from_its_title_to_the_next(monkeypatch: pytest.MonkeyPatch) -> None:
    items = read_form(monkeypatch)
    assert [(i.id, i.section, i.topic, i.text) for i in items] == [
        ("F1", "Finding", "Things made",
         "Say what was made, and by whom. Say where it can be had."),
        ("F2", "Finding", "Things bought", "Name the seller and the step-by-step order."),
        ("G1", "Gathering", "Things counted", "Give the count and how it was made."),
    ]


def test_a_title_the_recipe_leaves_out_gives_the_row_above_two_boxes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the box count, F2's lines would be written under F1, and nothing would say so."""
    with pytest.raises(RecipeError, match="F1 has 2"):
        read_form(monkeypatch, topics=[TOPICS[0], TOPICS[2]])


def test_a_first_title_left_out_leaves_a_box_under_a_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first row of a section left out of the recipe would be its preamble, passed over:
    its box is what says otherwise."""
    with pytest.raises(RecipeError, match="a form box stands under no item's title"):
        read_form(monkeypatch, topics=TOPICS[1:])


def test_a_title_not_printed_as_the_recipe_has_it_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topics = [TOPICS[0], {"id": "F2", "topic": "Things purchased"}, TOPICS[2]]
    with pytest.raises(RecipeError, match="'Things purchased' \\(F2\\) is not found"):
        read_form(monkeypatch, topics=topics)


def test_titles_in_another_order_than_the_pages_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RecipeError, match="'Things made' \\(F1\\) is not found"):
        read_form(monkeypatch, topics=[TOPICS[1], TOPICS[0], TOPICS[2]])


# ---------------------------------------------------------------- what the reading rests on


def test_a_suspended_hyphen_at_a_line_end_loses_its_space() -> None:
    """A pinned limit (DESIGN.md, Known gaps). A line that ends in a hyphen is joined to the
    next with no space, which is right for "step-" and "by-step" and wrong for a suspended
    hyphen, "Sex- and gender-based", broken after "Sex-". Neither shipped checklist breaks a
    line there; if this fails because the join changed, Known gaps is what to correct."""
    assert joined(["Name the step-", "by-step order"]) == "Name the step-by-step order"
    assert joined(["Sex-", "and gender-based analyses"]) == "Sex-and gender-based analyses"


def test_a_pdftotext_without_bbox_is_refused_in_a_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Xpdf's pdftotext answers -bbox with its usage and an exit status of 99."""
    from test_transcribe import pdftotext_runs

    from manuscript_guard.reporting import columns
    from manuscript_guard.reporting.rows import page_words

    pdftotext_runs(
        monkeypatch,
        "import sys; sys.stderr.write('Usage: pdftotext [options] <PDF-file>'); sys.exit(99)",
    )
    assert columns.shutil.which("pdftotext") == "pdftotext"
    path = tmp_path / "x.pdf"
    path.write_bytes(b"%PDF-1.4")
    with pytest.raises(RecipeError, match="Poppler's pdftotext gives it; Xpdf's"):
        page_words(path, 3)


def test_a_word_is_read_as_pdftotext_escapes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from manuscript_guard.reporting.rows import page_words

    pages_are(monkeypatch, {1: bbox((77, 100, 'a "quoted" R&D word'))})
    assert [w.text for w in page_words(Path("x.pdf"), 1)] == ["a", '"quoted"', "R&D", "word"]


@pytest.mark.parametrize(
    ("layout", "said"),
    [
        ({"columns": {"text": 0, "margin": 40}}, "unknown column roles: margin"),
        ({"rows": "boxes"}, "`rows` is one of centred-id, topics"),
        ({"columns": {"text": 0}}, "needs the columns id, text"),
        ({"columns": {"section": 10, "id": 85, "text": 135}}, "the first starting at 0"),
        ({"topics": TOPICS}, "`topics` goes with `rows: topics`"),
        ({"items": None}, "states how many `items`"),
    ],
    ids=["role", "rule", "missing-column", "first-column", "topics", "count"],
)
def test_a_recipe_that_does_not_say_enough_is_refused(layout: dict, said: str) -> None:
    settings = {"rows": "centred-id", "columns": CENTRED_COLUMNS, "items": 4, **layout}
    with pytest.raises(RecipeError, match=said):
        RowsRecipe.from_layout("x.pdf", settings)


def test_a_rows_profile_says_what_its_reading_rests_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "x.pdf").write_bytes(b"%PDF-1.4 not read, the page is replaced")
    pages_are(monkeypatch, {1: TABLE})
    path = tmp_path / "IMAGINARY.recipe.yaml"
    path.write_text(
        "schema: manuscript-guard/recipe/1\n"
        "meta:\n  name: IMAGINARY\n  source_url: https://example.org/\n"
        "  retrieved_on: 2026-11-12\n  licence: invented for this test\n"
        "document: x.pdf\nformat: pdf-rows\nrows: centred-id\npages: [1]\n"
        "columns: {section: 0, id: 85, text: 135, blank: 480}\n"
        "start_after: topic number page number\n"
        "stop_at: An invented footnote under the table\n"
        "ignore: [Imaginary Checklist]\nitems: 4\ntext_column: 0\n",
        encoding="utf-8",
    )
    written, count, unverified = build_profile(path, sources, tmp_path / "out")
    profile = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert (count, unverified) == (4, [])
    assert profile["verification"].startswith("read from where each word sits on the page")
    assert "compared with no other reading" in profile["verification"]
    assert [item["id"] for item in profile["items"]] == ["1", "2a", "2b", "2c"]


def test_the_shipped_rows_recipes_state_their_counts_and_checksums() -> None:
    from manuscript_guard.paths import SHIPPED_RECIPES
    from manuscript_guard.reporting.build import load_recipe

    found = {}
    for path in sorted(SHIPPED_RECIPES.glob("*.recipe.yaml")):
        recipe_, meta = load_recipe(path)
        if meta["_layout"]["format"] == "pdf-rows":
            RowsRecipe.from_layout(recipe_.document, meta["_layout"])
            assert len(meta["sha256"]) == 64, path.name
            found[meta["name"]] = meta["_layout"]["items"]
    assert found == {"MDAR": 18, "SAGER-2022-human": 18, "SAGER-2022-other": 13}


# ---------------------------------------------------------------- the published documents


SOURCES = os.environ.get("MANUSCRIPT_GUARD_CHECKLIST_SOURCES")


@pytest.mark.skipif(
    not SOURCES, reason="MANUSCRIPT_GUARD_CHECKLIST_SOURCES names no folder of checklists"
)
def test_every_shipped_recipe_whose_document_is_at_hand_transcribes(tmp_path: Path) -> None:
    """With MANUSCRIPT_GUARD_CHECKLIST_SOURCES naming a folder of the published documents, as
    `fetch` saves them, every shipped recipe whose document is there transcribes, to the count
    it states where it states one, with no item unverified. The documents are not in the
    repository, so in CI this is skipped."""
    from manuscript_guard.paths import SHIPPED_RECIPES
    from manuscript_guard.reporting.build import load_recipe

    folder = Path(SOURCES or "")
    read = []
    for path in sorted(SHIPPED_RECIPES.glob("*.recipe.yaml")):
        recipe_, meta = load_recipe(path)
        if not (folder / recipe_.document).exists():
            continue
        _written, count, unverified = build_profile(path, folder, tmp_path)
        assert unverified == [], path.name
        stated = meta["_layout"].get("items")
        assert count == stated if stated else count > 0, path.name
        read.append(path.name)
    assert read, f"no shipped recipe's document is in {folder}"
