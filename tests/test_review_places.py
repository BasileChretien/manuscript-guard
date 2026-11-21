"""Where a review finding's quote stands, and which readers of a round quote one sentence.

Basile, 2026-11-08, each as recommended: the place is the sentence that holds the quote, a
heading's title at its heading, a quote across two sentences at both and one whose words
stand twice at each; it is found when the reading is filed, in what was read, and sealed;
readers are counted within a round by `reviewed_by`; and `review` shows it, with the
sections each reading quotes, and nothing decides on it (`quote_places.py`).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml
from test_review_quotes import (
    SUPPLEMENT,
    contained,
    file_by_hand,
    hand_findings,
    loaded,
    model_readings,
    printed,
    quoting,
    seal,
)
from test_review_run import KEY_A, KEY_B, MODEL_A, MODEL_B, Providers, answer, configure, reply_text

from manuscript_guard.cli import main
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.gates import check_review
from manuscript_guard.gates.review import reading_digest, round_summaries
from manuscript_guard.panel import client
from manuscript_guard.quote_places import (
    Place,
    groups,
    place_quotes,
    places_of,
    reading_line,
    round_lines,
)

TWIN = Path(__file__).parent / "data" / "latex" / "manuscript"

PAPER = """\
# Abstract

Alpha one two three four. Bravo five six seven eight. Charlie nine ten eleven twelve.

# Methods

## Data source

Delta thirteen fourteen fifteen sixteen. Echo seventeen eighteen nineteen twenty.
Foxtrot twenty one twenty two. Golf twenty three twenty four.

# Results

Bravo five six seven eight. Hotel twenty five twenty six twenty seven.
"""


def placed(quote: str, texts: dict[str, str], written: dict[str, str] | None = None,
           latex: bool = False) -> list[dict]:  # fmt: skip
    return place_quotes([{"id": "q", "quote": quote}], ["q"], texts, written, latex=latex)["q"]


def where(found: list[dict]) -> list[tuple]:
    return [(one["file"], one["section"], one["sentence"], one.get("heading", False))
            for one in found]  # fmt: skip


# --------------------------------------------------------------------------- the sentence


def test_a_quote_is_at_the_sentence_that_holds_it_under_its_section() -> None:
    """A subsection's sentence is under its section: `## Data source` is the Methods'."""
    assert where(placed("fourteen fifteen sixteen. Echo", {"main.md": PAPER})) == [
        ("main.md", "Methods", "Delta thirteen fourteen fifteen sixteen.", False),
        ("main.md", "Methods", "Echo seventeen eighteen nineteen twenty.", False),
    ]
    assert where(placed("Delta thirteen fourteen fifteen", {"main.md": PAPER})) == [
        ("main.md", "Methods", "Delta thirteen fourteen fifteen sixteen.", False)]


def test_a_sentence_written_twice_is_two_places() -> None:
    """An abstract repeating a sentence of the Results: the quote is at each."""
    assert [one["section"] for one in placed("five six seven eight", {"main.md": PAPER})] == [
        "Abstract", "Results"]


def test_two_sentences_that_open_alike_for_400_characters_are_one_place() -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "Two places are one when their file, their section and the first 400 characters"):
    two sentences of one section that agree, whatever the case, for 400 characters and
    differ after are one place; differing before, or in another section or file, two."""
    opening = "Word " + "word " * 85
    alike = f"# Results\n\n{opening}alpha ends here. {opening.upper()}bravo ends there.\n"
    found = placed("word word word word", {"main.md": alike})
    assert [(one["section"], one["sentence"]) for one in found] == [
        ("Results", opening[:400])]
    # The other side of each: differing within the 400, or in another section or file.
    short = "Word " + "word " * 70
    apart = f"# Results\n\n{short}alpha ends here. {short}bravo ends there.\n"
    assert [one["sentence"][-17:] for one in placed("word word word word", {"main.md": apart})] == [
        " alpha ends here.", "bravo ends there."]
    sections = f"# Results\n\n{opening}alpha ends here.\n\n# Methods\n\n{opening}bravo ends.\n"
    assert [one["section"] for one in placed("word word word word", {"main.md": sections})] == [
        "Results", "Methods"]
    files = {"main.md": f"# Results\n\n{opening}alpha ends here.\n",
             "other.md": f"# Results\n\n{opening}bravo ends there.\n"}  # fmt: skip
    assert [one["file"] for one in placed("word word word word", files)] == ["main.md", "other.md"]


def test_a_heading_s_title_is_at_the_heading_under_its_section() -> None:
    assert where(placed("Data source", {"main.md": PAPER})) == [
        ("main.md", "Methods", "Data source", True)]
    assert where(placed("# Results", {"main.md": PAPER})) == [
        ("main.md", "Results", "Results", True)]


def test_a_paper_s_title_typed_as_its_one_top_heading_is_no_section() -> None:
    titled = "# A title of the paper\n\n" + PAPER.replace("# ", "## ").replace("### ", "### ")
    assert [one["section"] for one in placed("Hotel twenty five twenty", {"main.md": titled})] == [
        "Results"]


def test_a_section_is_read_at_the_first_level_its_file_has_two_headings_of() -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "A section is the heading over a sentence of the first level its file has two
    headings of"): a file with one section and subsections under it names the subsections,
    so the example's supplement is read at its tables' level, and an abstract typed under
    a paper's title with no heading of its own is in the title's section."""
    single = "# Methods\n\n## Data\n\nWe counted the reports.\n\n## Analysis\n\nIt was modelled.\n"
    assert [one["section"] for one in placed("We counted the reports", {"main.md": single})] == [
        "Data"]
    # The other side: with two headings at the top level, a subsection's sentence is its
    # section's.
    two = single + "\n# Results\n\nThe rate rose in men.\n"
    assert [one["section"] for one in placed("We counted the reports", {"main.md": two})] == [
        "Methods"]
    supplement = Path(__file__).parents[1] / "example" / "manuscript" / "supplementary"
    text = (supplement / "S1_code_lists.md").read_text(encoding="utf-8")
    assert text.startswith("# Supplementary methods\n")
    assert [one["section"] for one in placed(SUPPLEMENT, {"S1.md": text})] == [
        "Table S1. Code lists used to identify the outcome"]
    titled = ("# A study of the rate\n\nAn abstract under the title alone.\n\n"
              "## Methods\n\nWe counted the reports.\n\n"
              "## Results\n\nThe rate rose.\n")  # fmt: skip
    assert [one["section"] for one in placed("abstract under the title", {"main.md": titled})] == [
        "A study of the rate"]
    assert [one["section"] for one in placed("We counted the reports", {"main.md": titled})] == [
        "Methods"]


def test_a_heading_and_the_line_under_it_are_not_one_sentence() -> None:
    text = "# Methods\nIndia one two three four.\n"
    assert where(placed("India one two three", {"main.md": text})) == [
        ("main.md", "Methods", "India one two three four.", False)]


def test_a_quote_across_three_sentences_is_placed_nowhere() -> None:
    assert placed("twenty. Foxtrot twenty one twenty two. Golf twenty", {"main.md": PAPER}) == []


def test_two_sentences_in_a_row_are_looked_at_only_where_no_one_sentence_holds_the_quote() -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "Two sentences in a row are looked at only where no one sentence holds the
    quote"): words whole in the Results, a stop with a small letter after it cutting
    nothing there, and across a cut in the abstract, are placed in the Results only."""
    text = ("# Abstract\n\nAlpha one two. Three four five six.\n\n"
            "# Results\n\nWe saw one two. three four in all.\n")  # fmt: skip
    assert where(placed("one two. Three four", {"main.md": text})) == [
        ("main.md", "Results", "We saw one two. three four in all.", False)]
    # The other side: with no one sentence holding it, the abstract's two are its places.
    alone = text.replace("We saw one two. three four in all.", "Nothing like it.")
    assert where(placed("one two. Three four", {"main.md": alone})) == [
        ("main.md", "Abstract", "Alpha one two.", False),
        ("main.md", "Abstract", "Three four five six.", False),
    ]


def test_a_sentence_above_every_heading_has_no_section() -> None:
    text = "Juliet one two three four.\n\n# Methods\n\nKilo five six seven.\n"
    assert where(placed("Juliet one two three", {"main.md": text})) == [
        ("main.md", None, "Juliet one two three four.", False)]


def test_a_quote_found_only_as_written_is_placed_in_the_written_file() -> None:
    """A person may copy the source, its binding in; the printed text comes first."""
    written = {"main.md": "# Results\n\nWe counted {{results.n}} reports in all of them.\n"}
    shown = {"main.md": "# Results\n\nWe counted 4000 reports in all of them.\n"}
    assert where(placed("We counted {{results.n}} reports", shown, written)) == [
        ("main.md", "Results", "We counted {{results.n}} reports in all of them.", False)]
    assert where(placed("counted 4000 reports in", shown, written)) == [
        ("main.md", "Results", "We counted 4000 reports in all of them.", False)]


def test_a_binding_alone_on_its_line_stays_in_its_sentence() -> None:
    """A hard wrap can leave a binding alone on a line: the sentence goes on round it."""
    written = {"main.md": "# Results\n\nWe counted\n{{results.n}}\nreports in all of them.\n"}
    shown = {"main.md": "# Results\n\nWe counted 4000 reports in all of them.\n"}
    assert where(placed("counted {{results.n}} reports in", shown, written)) == [
        ("main.md", "Results", "We counted {{results.n}} reports in all of them.", False)]


def test_a_supplement_s_sentence_is_the_supplement_s() -> None:
    texts = {"main.md": PAPER,
             "supplementary/S1.md": "# Supplementary methods\n\nLima one two three four.\n"}
    found = placed("Lima one two three", texts)
    assert where(found) == [("supplementary/S1.md", "Supplementary methods",
                             "Lima one two three four.", False)]  # fmt: skip
    assert reading_line([("q", (Place(**found[0]),))]) == (
        "quotes in: Supplementary methods (supplement) 1")


def test_a_latex_sentence_is_cut_at_its_headings_and_environments() -> None:
    latex = ("\\begin{abstract}\nMike one two three four.\n\\end{abstract}\n"
             "\\section{Methods}\\label{sec:methods}\nNovember five six seven eight.\n")
    assert where(placed("Mike one two three", {"main.tex": latex}, latex=True)) == [
        ("main.tex", "Abstract", "Mike one two three four.", False)]
    assert where(placed("November five six seven", {"main.tex": latex}, latex=True)) == [
        ("main.tex", "Methods", "November five six seven eight.", False)]
    assert where(placed("Methods", {"main.tex": latex}, latex=True)) == [
        ("main.tex", "Methods", "Methods", True)]


@pytest.mark.parametrize("opening", ["\\citet{smith2020}", "\\emph{Hepatic}", "\\mg{results.n}"])
def test_a_latex_sentence_keeps_a_command_that_opens_it_and_prints(opening: str) -> None:
    """Round 1 of #587: every opening command was taken out with its argument, and a
    sentence opening with its citation was kept without its subject."""
    latex = f"\\section{{Results}}\n{opening} reported 426 cases of liver injury.\n"
    assert where(placed("reported 426 cases of liver", {"main.tex": latex}, latex=True)) == [
        ("main.tex", "Results", f"{opening} reported 426 cases of liver injury.", False)]


def test_a_command_that_prints_nothing_does_not_open_what_is_kept() -> None:
    latex = "\\section{Results}\\label{sec:r}\n\\noindent We counted 426 cases in all.\n"
    assert [one["sentence"] for one in placed("counted 426 cases in", {"main.tex": latex},
                                              latex=True)] == ["We counted 426 cases in all."]


def test_a_markdown_sentence_opening_with_a_hash_keeps_it() -> None:
    text = "# Results\n\nThe rate rose.\n#1 ranked drug was example-drug in all reports.\n"
    found = placed("ranked drug was example-drug", {"main.md": text})
    assert [one["sentence"] for one in found] == ["#1 ranked drug was example-drug in all reports."]


def test_a_citation_s_locator_does_not_cut_a_sentence() -> None:
    """Round 1 of #587: cut on the text itself, "[@a, p. 12]" ended a sentence at "p."."""
    text = "# Results\n\nThe rate rose [@smith2020, p. 12] in every year of the study.\n"
    assert where(placed("in every year of", {"main.md": text})) == [
        ("main.md", "Results", "The rate rose [@smith2020, p. 12] in every year of the study.",
         False)]


def test_a_sentence_is_cut_where_g8_cuts_one() -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "A sentence is cut as G8 cuts one"): "Fig. 2" and "Dr. Smith" each cut a sentence,
    a quote across one cut is at both halves and across two is placed nowhere; LaTeX's
    `\\citep[p. 12]{a}` ends a sentence at "p." where Markdown's group does not; `\\item`
    and `\\\\` cut nothing; and an address or a key after "e.g." is cut from it."""
    text = "# Results\n\nThe rate rose as Fig. 2 shows in men. We thank Dr. Smith for the data.\n"
    assert [one["sentence"] for one in placed("as Fig. 2 shows in", {"main.md": text})] == [
        "The rate rose as Fig.", "2 shows in men."]
    assert [one["sentence"] for one in placed("thank Dr. Smith for the", {"main.md": text})] == [
        "We thank Dr.", "Smith for the data."]
    twice = "# Results\n\nWe thank Dr. Smith as Fig. 2 shows here.\n"
    assert placed("thank Dr. Smith as Fig. 2 shows", {"main.md": twice}) == []
    # The other side of the LaTeX locator's cut: a tie, or Markdown's group, ends nothing.
    for spaced, whole in (("[p. 12]", False), ("[p.~12]", True)):
        latex = f"\\section{{Results}}\nThe rate rose \\citep{spaced}{{a}} in every year of it.\n"
        assert [one["sentence"] for one in placed("in every year of", {"main.tex": latex},
                                                  latex=True)] == [  # fmt: skip
            f"The rate rose \\citep{spaced}{{a}} in every year of it." if whole
            else "12]{a} in every year of it."]
    markdown = "# Results\n\nThe rate rose [@a, p. 12] in every year of it.\n"
    assert [one["sentence"] for one in placed("in every year of", {"main.md": markdown})] == [
        "The rate rose [@a, p. 12] in every year of it."]
    items = ("\\section{Methods}\n\\begin{itemize}\n\\item The rate rose in men\n"
             "\\item it fell in women \\\\ and in children.\n\\end{itemize}\n")  # fmt: skip
    assert [one["sentence"] for one in placed("rate rose in men", {"main.tex": items},
                                              latex=True)] == [  # fmt: skip
        "\\item The rate rose in men \\item it fell in women \\\\ and in children."]
    for after in ("https://a.org", "@smith2020"):
        code = f"# Code\n\nSee e.g. {after} for the code of the study.\n"
        assert [one["sentence"] for one in placed("for the code of", {"main.md": code})] == [
            f"{after} for the code of the study."]
    # The other side: a small word after "e.g." does not cut it.
    plainly = "# Code\n\nSee e.g. the archive for the code of the study.\n"
    assert [one["sentence"] for one in placed("for the code of", {"main.md": plainly})] == [
        "See e.g. the archive for the code of the study."]


@pytest.mark.parametrize("ending", [
    "[the repository](https://github.com/a/b).", "<https://github.com/a/b>.",
    "https://github.com/a/b.", "@smith2020.", "(https://github.com/a/b).",
])  # fmt: skip
def test_a_stop_after_a_link_or_a_narrative_citation_ends_its_sentence(ending: str) -> None:
    """Round 2 of #587: G8's reading blanks an address or a citation's key with the stop
    after it, and the two sentences were read as one."""
    text = f"# Data availability\n\nCode is in {ending} Data are deposited in the archive.\n"
    assert where(placed("Data are deposited in", {"main.md": text})) == [
        ("main.md", "Data availability", "Data are deposited in the archive.", False)]


@pytest.mark.parametrize("link", [
    "[the code](https://example.org/a/b)", "[the code](https://example.org/wiki/A_(b))",
    '[the code](https://example.org/a "The code")', "[the code](doi:10.1000/xyz)",
])  # fmt: skip
def test_a_link_with_a_bracket_later_on_its_line_ends_its_sentence(link: str) -> None:
    """Round 3 of #587: the mask took the link's address up to the next space, its `)` and
    stop with it, and the link's target then ran on to the `)` after 1200, so the sentence
    after the link was read into the one before it."""
    text = f"# Results\n\nCode is at {link}. Data (n = 1200) are deposited. Then more.\n"
    assert where(placed("Data (n = 1200) are deposited", {"main.md": text})) == [
        ("main.md", "Results", "Data (n = 1200) are deposited.", False)]


def test_a_stop_inside_inline_code_ends_no_sentence() -> None:
    text = "# Methods\n\nWe ran `fit(x). Then` on every site of the study.\n"
    assert [one["sentence"] for one in placed("on every site of", {"main.md": text})] == [
        "We ran `fit(x). Then` on every site of the study."]


def test_a_bracket_with_an_at_sign_joins_no_paragraphs() -> None:
    """Round 2 of #587: a citation group was filled across a blank line."""
    text = "# Results\n\nAged [18 to 65 as @a found.\n\nThe rate rose in men] overall.\n"
    assert [one["sentence"] for one in placed("The rate rose in", {"main.md": text})] == [
        "The rate rose in men] overall."]


def test_a_stray_bracket_pair_round_an_at_sign_is_one_sentence() -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "A citation group is any bracket pair with an `@` inside it"): "[18, 65) as @a
    found. ... (65, 100]" within one paragraph is read as one sentence from one to the
    other."""
    text = ("# Results\n\nAged [18, 65) as @a found. The rate rose in men. Over (65, 100] it "
            "fell. Then more came.\n")  # fmt: skip
    assert [one["sentence"] for one in placed("The rate rose in men", {"main.md": text})] == [
        "Aged [18, 65) as @a found. The rate rose in men. Over (65, 100] it fell."]
    # The other side: with no bracket pair round the `@`, the sentences are cut at each stop.
    text = text.replace("[18", "(18").replace("100]", "100)")
    assert [one["sentence"] for one in placed("The rate rose in men", {"main.md": text})] == [
        "The rate rose in men."]


def test_an_unanchored_finding_or_one_that_quotes_nothing_is_not_placed() -> None:
    findings = [{"id": "a", "quote": "Alpha one two three"}, {"id": "b", "quote": "Zulu"},
                {"id": "c"}]  # fmt: skip
    assert sorted(place_quotes(findings, ["a", "c"], {"main.md": PAPER})) == ["a"]


# ------------------------------------------------------------------- readers of one place


class Reading:
    def __init__(self, reviewer: str, who: str, places, anchored: int = 1) -> None:
        self.reviewer, self.who, self.places, self.anchored = reviewer, who, places, anchored


ONE = Place("main.md", "Methods", "Delta thirteen fourteen fifteen sixteen.")
TWO = Place("main.md", "Results", "Hotel twenty five twenty six twenty seven.")


def test_readers_are_counted_by_name_and_once_on_a_sentence() -> None:
    """A model that read two remits is one reader; two findings of one reader on one sentence
    count once; a sentence in other case is the same sentence."""
    shouting = Place(ONE.file, ONE.section, ONE.sentence.upper())
    found = groups([
        Reading("methods", "openai/model-a", (("r1-01", (ONE,)), ("r1-02", (ONE, TWO)))),
        Reading("statistics", "openai/model-a", (("r1-01", (shouting,)),)),
        Reading("methods", "Jane Roe", (("h1", (ONE,)),)),
    ])  # fmt: skip
    assert [(group.place, len(group.readers)) for group in found] == [(ONE, 2), (TWO, 1)]
    assert found[0].readers == (
        ("openai/model-a", (("methods", "r1-01"), ("methods", "r1-02"), ("statistics", "r1-01"))),
        ("Jane Roe", (("methods", "h1"),)),
    )


def test_review_lists_the_sentences_two_readers_quote_and_counts_the_rest() -> None:
    lines = round_lines([
        Reading("methods", "openai/model-a", (("r1-01", (ONE,)), ("r1-02", ()))),
        Reading("methods", "mistral/model-b", (("r1-01", (ONE, TWO)),)),
        Reading("statistics", "Jane Roe", None, anchored=2),
        Reading("statistics", "John Doe", None, anchored=0),
    ])  # fmt: skip
    assert lines == [
        "quoted by two readers or more:",
        '  2 readers, Methods: "Delta thirteen fourteen fifteen sixteen."',
        "    openai/model-a: r1-01 (methods)",
        "    mistral/model-b: r1-01 (methods)",
        "1 place quoted by one reader; 1 anchored finding in no one sentence or two; "
        "1 reading filed before the sentences quoted were kept",
    ]
    assert round_lines([Reading("methods", "openai/model-a", (("r1-01", (ONE,)),))]) == [
        "1 place quoted by one reader"]
    assert round_lines([Reading("methods", "x", None, anchored=0)]) == []


def test_a_reading_s_sections_are_counted_a_finding_once_each() -> None:
    again = Place(ONE.file, ONE.section, "Echo seventeen eighteen nineteen twenty.")
    line = reading_line((("a", (ONE, again)), ("b", (TWO,)), ("c", (TWO,)), ("d", ())))
    assert line == "quotes in: Results 2, Methods 1"
    assert reading_line((("d", ()),)) is None and reading_line(None) is None


# ----------------------------------------------------------------------- filed by the run


@pytest.fixture
def providers(monkeypatch) -> Providers:
    transport = Providers()
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", KEY_A)
    monkeypatch.setenv("MISTRAL_API_KEY", KEY_B)
    return transport


@pytest.fixture
def read_by_two_models(project: Path, providers: Providers) -> Path:
    """One round read by two models of two providers, each reading every remit, each
    finding quoting as `quoting` does."""
    shutil.rmtree(project / "review")
    configure(project, MODEL_A, MODEL_B)
    said = quoting(project)
    providers.default = lambda request: answer(reply_text("major-revision", said))
    assert main(["review", str(project), "--run", "--yes"]) == 0
    return project


def test_the_run_keeps_the_sentence_and_the_section_of_each_anchored_quote(
    read_by_two_models: Path,
) -> None:
    root = read_by_two_models
    found = re.search(r"The database contained [^.]+\.", " ".join(printed(root).split()))
    assert found and " ".join(contained(root).split()) in found.group()
    sentence = found.group()
    for path in model_readings(root):
        document = read_structured(path)
        assert validate(document, "review", path).ok
        assert document["reading_sha256"] == reading_digest(document)
        places = document["quotes"]["places"]
        assert sorted(places) == ["r1-01", "r1-02", "r1-05"]
        assert [(p["file"], p["section"]) for p in places["r1-01"]] == [("main.md", "Results")]
        assert places["r1-01"][0]["sentence"] == sentence
        assert [(p["file"], p["section"], p["sentence"][: len(SUPPLEMENT)])
                for p in places["r1-02"]] == [(  # fmt: skip
            "supplementary/S1_code_lists.md", "Table S1. Code lists used to identify the outcome",
            SUPPLEMENT)]
        assert places["r1-05"] == [{"file": "main.md", "section": "Discussion",
                                    "sentence": "Discussion", "heading": True}]  # fmt: skip


def test_review_counts_two_readers_where_two_models_quote_one_sentence(
    read_by_two_models: Path, capsys
) -> None:
    """Each model read four remits, and is one reader of each sentence it quoted."""
    capsys.readouterr()
    main(["review", str(read_by_two_models)])
    said = capsys.readouterr().out
    assert "quoted by two readers or more:" in said
    assert '  2 readers, Results: "The database contained' in said
    assert "  2 readers, Discussion, the heading \"Discussion\"" in said
    assert re.search(r"    openai/model-a: r1-01 \(\S+\), r1-01 \(\S+\), r1-01 \(\S+\), "
                     r"r1-01 \(\S+\)\n", said)  # fmt: skip
    assert "    mistral/model-b: r1-01" in said
    assert said.count("  quotes in: Results 1, Table S1. Code lists used to identify the "
                      "outcome (supplement) 1, Discussion 1") == 8  # fmt: skip


def test_the_places_decide_nothing(read_by_two_models: Path) -> None:
    """G11's counts and findings are the same with the places taken out of every reading,
    sealed again over what is left."""
    before = check_review(loaded(read_by_two_models), submission=True)
    for path in model_readings(read_by_two_models):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        del document["quotes"]["places"]
        document["reading_sha256"] = reading_digest(document)
        path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), "utf-8")
    after = check_review(loaded(read_by_two_models), submission=True)
    assert after.counts == before.counts
    assert [(f.code, f.severity, f.message) for f in after.findings] == [
        (f.code, f.severity, f.message) for f in before.findings]


def test_a_place_changed_after_filing_is_an_edit_of_the_reading(read_by_two_models: Path) -> None:
    path = model_readings(read_by_two_models)[0]
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["quotes"]["places"]["r1-01"][0]["section"] = "Methods"
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), "utf-8")
    report = check_review(loaded(read_by_two_models), submission=True)
    assert [f.path for f in report.failures if f.code == "reading-altered"] == [path]
    assert places_of(read_structured(path)) is None


def test_a_reading_sealed_before_places_were_kept_is_read_as_before(
    read_by_two_models: Path, capsys
) -> None:
    for path in model_readings(read_by_two_models):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        del document["quotes"]["places"]
        document["reading_sha256"] = reading_digest(document)
        path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), "utf-8")
    summary = round_summaries(loaded(read_by_two_models))[0]
    assert {reading.places for reading in summary.readings} == {None}
    assert {reading.anchored for reading in summary.readings} == {3}
    capsys.readouterr()
    main(["review", str(read_by_two_models)])
    said = capsys.readouterr().out
    assert "8 readings filed before the sentences quoted were kept" in said
    assert "quoted by two readers" not in said and "quotes in:" not in said


# ------------------------------------------------------------------- sealed by hand


def test_a_hand_filed_reading_keeps_its_places_when_it_is_sealed(project: Path) -> None:
    """As printed, and as written where a person copied the binding."""
    path = file_by_hand(project, hand_findings(project))
    assert seal(project) == 0
    document = read_structured(path)
    assert validate(document, "review", path).ok
    places = document["quotes"]["places"]
    assert [(p["section"], p["sentence"][:51]) for p in places["h1"]] == [
        ("Results", "The database contained {{results.cohort.n_reports}}")]
    assert places["h2"][0]["section"] == "Results"
    assert "{{" not in places["h2"][0]["sentence"]
    assert places["h3"] == [{"file": "main.md", "section": "Discussion",
                             "sentence": "Discussion", "heading": True}]  # fmt: skip
    assert places["h4"][0]["file"] == "supplementary/S1_code_lists.md"
    assert "h5" not in places and "h6" not in places


def test_two_people_reading_one_remit_are_two_readers(project: Path, capsys) -> None:
    """Two named readings of one remit, by the readers the panel lists, quoting one sentence."""
    finding = yaml.safe_dump([{"id": "h1", "severity": "minor", "finding": "Say so.",
                               "quote": contained(project)}], sort_keys=False, width=10**6)
    for who in ("Jane Roe", "John Doe"):
        assert main(["review", str(project), "--record", "fresh-reader", "--round", "9",
                     "--remit", "the manuscript as it stands", "--verdict", "minor-revision",
                     "--reading", who]) == 0  # fmt: skip
        named = f"fresh-reader.{who.split()[0].lower()}*"
        path = next((project / "review" / "round-9").glob(named))
        text = path.read_text(encoding="utf-8")
        path.write_bytes(text.replace("findings: []\n", "findings:\n" + finding).encode("utf-8"))
        assert seal(project, "--reading", who) == 0
    capsys.readouterr()
    main(["review", str(project)])
    said = capsys.readouterr().out
    assert '  2 readers, Results: "The database contained' in said
    assert "    Jane Roe: h1 (fresh-reader)\n" in said
    assert "    John Doe: h1 (fresh-reader)\n" in said


@pytest.mark.parametrize("names, readers", [
    (("Jane Roe", "J. Roe"), ["Jane Roe", "J. Roe"]),
    ((None, None), ["methods-reader", "statistics-reader"]),
    (("Jane Roe", "Jane Roe"), None),
])  # fmt: skip
def test_readers_are_counted_by_their_names_as_typed(
    project: Path, names: tuple[str | None, str | None], readers: list[str] | None
) -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "Readers are counted by name"): one person filing two plain records, under two
    spellings of a name or with no `--by`, which writes each remit's id, is two readers of
    the sentence both quote; under one name typed alike, one (the other side)."""
    finding = yaml.safe_dump([{"id": "h1", "severity": "minor", "finding": "Say so.",
                               "quote": contained(project)}], sort_keys=False, width=10**6)
    for reviewer, by in zip(("methods-reader", "statistics-reader"), names, strict=True):
        assert main(["review", str(project), "--record", reviewer, "--round", "20",
                     "--remit", f"the {reviewer}'s remit", "--verdict", "minor-revision",
                     *(["--by", by] if by else [])]) == 0  # fmt: skip
        path = project / "review" / "round-20" / f"{reviewer}.yaml"
        text = path.read_text(encoding="utf-8")
        path.write_bytes(text.replace("findings: []\n", "findings:\n" + finding).encode("utf-8"))
        assert main(["review", str(project), "--seal", reviewer, "--round", "20"]) == 0
    summary = next(one for one in round_summaries(loaded(project)) if one.number == 20)
    lines = round_lines(summary.readings)
    if readers is None:
        assert [reading.who for reading in summary.readings] == ["Jane Roe", "Jane Roe"]
        assert lines == ["1 place quoted by one reader"]
        return
    assert [reading.who for reading in summary.readings] == readers
    assert lines[:2] == ["quoted by two readers or more:", lines[1]]
    assert lines[1].startswith('  2 readers, Results: "The database contained')
    assert lines[2:] == [f"    {readers[0]}: h1 (methods-reader)",
                         f"    {readers[1]}: h1 (statistics-reader)"]  # fmt: skip


# --------------------------------------------------------------------------------- LaTeX


@pytest.fixture
def twin(project: Path) -> Path:
    shutil.rmtree(project / "manuscript")
    shutil.copytree(TWIN, project / "manuscript")
    return project


def test_a_latex_reading_by_hand_is_placed_as_printed_or_in_the_file_it_is_typed_in(
    twin: Path,
) -> None:
    """A known gap (DESIGN.md, Known gaps, "Readers at one sentence are readers who quoted
    it", "A LaTeX reading filed by hand that carries every file"): a quote of the printed
    words is placed in the document as printed, under its Results; one standing only as
    written is placed in the `\\input` file it is typed in, which has no `\\section`, so
    before any heading."""
    manuscript = twin / "manuscript"
    (manuscript / "extra.tex").write_text(
        "Extra counts were drawn from \\mg{results.cohort.n_reports} reports in all.\n", "utf-8")
    entry = manuscript / "main.tex"
    text = entry.read_text(encoding="utf-8")
    assert "\\section{Results}\n" in text
    entry.write_text(text.replace("\\section{Results}\n", "\\section{Results}\n\\input{extra}\n",
                                  1), "utf-8")  # fmt: skip
    shown = re.search(r"Extra counts were drawn from \S+ reports", printed(twin, "main.tex"))
    assert shown and "\\mg" not in shown.group()
    findings = yaml.safe_dump([
        {"id": "h1", "severity": "minor", "finding": "Bare.", "quote": shown.group()},
        {"id": "h2", "severity": "minor", "finding": "Bare.",
         "quote": "Extra counts were drawn from \\mg{results.cohort.n_reports} reports"},
    ], sort_keys=False, allow_unicode=True, width=10**6)  # fmt: skip
    path = file_by_hand(twin, findings)
    assert seal(twin) == 0
    places = read_structured(path)["quotes"]["places"]
    assert [(p["file"], p["section"]) for p in places["h1"]] == [("main.tex", "Results")]
    assert places["h2"] == [{"file": "extra.tex", "section": None, "sentence":
                             "Extra counts were drawn from \\mg{results.cohort.n_reports} "
                             "reports in all."}]  # fmt: skip


def test_a_latex_reading_keeps_the_sentence_and_section_of_each_quote(
    twin: Path, providers: Providers, capsys
) -> None:
    shutil.rmtree(twin / "review")
    configure(twin, MODEL_A, MODEL_B)
    sent = printed(twin, "main.tex")
    opening = re.search(r"The database contained \S+ reports, of which\s+\S+ named", sent)
    assert opening, "the twin's Results open as the example's do"
    said = [
        {"severity": "major", "quote": " ".join(opening.group().split()), "finding": "Bare."},
        {"severity": "minor", "quote": SUPPLEMENT, "finding": "Move it."},
        {"severity": "comment", "quote": "Discussion", "finding": "Well put."},
    ]  # fmt: skip
    providers.default = lambda request: answer(reply_text("major-revision", said))
    assert main(["review", str(twin), "--run", "--yes"]) == 0
    for path in model_readings(twin):
        document = read_structured(path)
        assert validate(document, "review", path).ok
        places = document["quotes"]["places"]
        assert [(p["file"], p["section"]) for p in places["r1-01"]] == [("main.tex", "Results")]
        assert places["r1-01"][0]["sentence"].startswith("The database contained")
        # The twin's supplement has two sections of its first level, Supplementary methods
        # and the controls' (PR 3 of wave 3), so a sentence's section is read at that level.
        assert [(p["file"], p["section"]) for p in places["r1-02"]] == [
            ("supplementary/main.tex", "Supplementary methods")]
        assert places["r1-03"] == [{"file": "main.tex", "section": "Discussion",
                                    "sentence": "Discussion", "heading": True}]  # fmt: skip
    capsys.readouterr()
    main(["review", str(twin)])
    shown = capsys.readouterr().out
    assert '  2 readers, Results: "The database contained' in shown
