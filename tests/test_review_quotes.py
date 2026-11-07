"""Each review finding quotes the text it is about (item 1 of the plan of 2026-11-06).

A reader sent only the title and abstract raised every defect the example's first panel
found (DESIGN.md, "What the panel finds of the defects we know"), so a finding raised is no
evidence that the paper was read. A finding quotes the manuscript's words, or for something
missing the heading where it belongs, and the quote is looked for once, when the reading is
filed: by `review --run` in what each model was sent, and by `review --seal` in the files a
hand-filed reading carries. G11 reads what was found, counts the anchored and unanchored
findings apart, and notes the readings with unanchored ones; a major finding binds either
way (Basile's D1.1 to D1.4, and his four answers of 2026-11-07).

No test here opens a connection: `review --run` is answered by the transport of
`test_review_run`.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml
from test_review_run import KEY_A, KEY_B, MODEL_A, Providers, answer, configure, reply_text

from manuscript_guard import anchoring
from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.findings import INFO
from manuscript_guard.gates import check_review
from manuscript_guard.gates.review import reading_digest
from manuscript_guard.panel import client, prompt
from manuscript_guard.panel.reply import parse_reply


def loaded(root: Path):
    return load_project(root)[0]


TEXT = (
    "# Methods\n\n"
    "We analysed a *synthetic* spontaneous reporting database, covering\n"
    "the years \u201cbefore\u201d the drug\u2019s withdrawal\u2014all of them.\n\n"
    "**Results.** Reports by group:\n\n"
    "| Group | Reports |\n|---|---|\n| Exposed | 412 |\n\n"
    "## 2.1 Statistical analysis\n\n"
    "The reporting odds ratio was computed in the usual way.\n"
)


def stands(quote: str, *texts: str) -> bool:
    return anchoring.stands(quote, anchoring.read_of(texts or (TEXT,)))


# ------------------------------------------------------------------------ the rule itself


@pytest.mark.parametrize(
    "quote",
    [
        "We analysed a synthetic spontaneous reporting database",
        "We analysed a *synthetic* spontaneous",
        'covering the years "before" the drug\'s withdrawal-all of them',
        "spontaneous reporting   database,\ncovering",
        "WE ANALYSED A SYNTHETIC",
        "We analysed ... reporting database",
        "Results. Reports by group: | Group | Reports",
        "Results. Reports by group: Group Reports",
        "The reporting odds ratio was",
    ],
)
def test_a_quote_copied_from_the_text_stands_in_it(quote: str) -> None:
    """As written, typed with the keyboard's marks, wrapped, in capitals, with words left
    out in order, across emphasis and a table's cell walls."""
    assert stands(quote)


@pytest.mark.parametrize(
    "quote",
    [
        "Methods",
        "# Methods",
        "methods.",
        "Statistical analysis",
        "2.1 Statistical analysis",
        "## 2.1 Statistical analysis",
    ],
)
def test_the_whole_title_of_a_heading_stands_for_something_missing(quote: str) -> None:
    assert stands(quote)


@pytest.mark.parametrize(
    "quote, why",
    [
        ("analysed a synthetic", "three words, and no heading"),
        ("Exposed | 412", "two words of a table"),
        ("Group Reports Exposed 412", "across a table's rule"),
        ("Results.", "a bold label in a paragraph is no heading"),
        ("Statistical", "part of a heading's title"),
        ("nalysed a synthetic spontaneous", "the start of no word"),
        ("We analysed a synthetic spontaneous reporting registry", "a word changed"),
        ("reporting database ... We analysed", "pieces out of order"),
        ("We analysed a \u201csynthetic\u201d spontaneous", "quote marks the text has not"),
        ("The incidence was computed in", "words the text does not have"),
        ("...", "nothing but an elision"),
        ("We ... analysed ... synthetic ... reporting", "a word between each elision"),
    ],
)
def test_a_quote_not_in_the_text_does_not_stand(quote: str, why: str) -> None:
    assert not stands(quote), why


def test_only_pieces_of_two_words_or_more_count_towards_the_four() -> None:
    """Round 1 of #581: one word between elisions is found in almost any paper. Basile,
    2026-11-07, by question box: only pieces of two words or more count."""
    common = "The aim of this study and its design in brief."
    assert anchoring.words("the ... of ... and ... in") == 0
    assert not stands("the ... of ... and ... in", common)
    assert anchoring.words("The aim ... and its ... brief") == 4
    assert stands("The aim ... and its ... brief", common)


@pytest.mark.parametrize(
    "written, quoted",
    [
        ("cases from 2010--2020 in all regions", "cases from 2010\u20132020 in all regions"),
        ("the drug---and only the drug---was", "the drug\u2014and only the drug\u2014was"),
        ("see [the protocol](https://example.org/p) for the codes", "see the protocol for the"),
        ("we measured H~2~O in each sample", "we measured H2O in each"),
        ("about 10^3^ cells per well were seen", "about 103 cells per well"),
    ],
)
def test_what_pandoc_prints_otherwise_stands_as_word_prints_it(written: str, quoted: str) -> None:
    """Round 1 of #581: a person quoting the built document sees pandoc's dashes, a link's
    text, and sub- and superscripts as Word prints them; a model, sent the Markdown, may
    quote it as written. Either stands."""
    assert stands(quoted, written)
    assert stands(written, written)


@pytest.mark.parametrize(
    "written, quoted",
    [
        ("Code is available at [GitHub](https://github.com/a/b) for review.",
         "Code is available at [GitHub]"),
        ("Code is available at [GitHub](https://github.com/a/b) for review.",
         "at [GitHub](https://github.com/a/b) for review"),
        ("We measured the levels of H~2~O in each sample.", "measured the levels of H~2"),
    ],
)  # fmt: skip
def test_part_of_a_link_or_a_script_as_written_stands(written: str, quoted: str) -> None:
    """Round 2 of #581: a model sent the Markdown may copy half of a link or a script as it
    was written, which the text read as printed no longer holds."""
    assert stands(quoted, written)


@pytest.mark.parametrize(
    "heading, quote, there",
    [
        ("## 2020 cohort", "Cohort", False),
        ("## 2020 cohort", "2020 cohort", True),
        ("# 1 Introduction", "Introduction", True),
        ("## 12. Discussion", "Discussion", True),
        ("## S1. Code lists", "Code lists", True),
        ("## B12 deficiency", "Deficiency", False),
        ("## T2 diabetes outcomes", "diabetes outcomes", False),
    ],
)
def test_a_section_s_number_is_one_or_two_digits_or_dotted(
    heading: str, quote: str, there: bool
) -> None:
    """Round 1 of #581: a year that opens a heading is part of its title."""
    assert stands(quote, f"{heading}\n\nSome text under it.\n") is there


def test_a_quote_stands_only_in_the_texts_it_is_looked_for_in() -> None:
    other = "An unrelated paragraph about something else entirely."
    assert stands("An unrelated paragraph about", other)
    assert not stands("An unrelated paragraph about", TEXT)


def test_words_of_a_script_written_without_spaces_are_counted_by_their_letters() -> None:
    """Two letters of Han or kana to a word, as G7 counts the words beside a value."""
    # Nine letters in one run, and a full stop.
    japanese = "".join(map(chr, (0x5168, 0x4F8B, 0x3092, 0x89E3, 0x6790, 0x3057, 0x307E,
                                 0x3057, 0x305F, 0x3002)))  # fmt: skip
    assert anchoring.words(japanese[:7]) == 3
    assert anchoring.words(japanese) == 4
    assert stands(japanese, f"# \u65b9\u6cd5\n\n{japanese}\n")
    assert not stands(japanese[:6], f"# \u65b9\u6cd5\n\n{japanese}\n")


def test_a_model_s_finding_with_no_quote_is_unanchored_and_a_person_s_is_neither() -> None:
    read = anchoring.read_of([TEXT])
    findings = [
        {"id": "a", "quote": "We analysed a synthetic spontaneous"},
        {"id": "b", "quote": "invented words that are not there"},
        {"id": "c"},
        {"id": "d", "quote": "   "},
    ]
    assert anchoring.sort_quotes(findings, read, must_quote=True) == {
        "anchored": ["a"], "unanchored": ["b", "c", "d"]}  # fmt: skip
    assert anchoring.sort_quotes(findings, read, must_quote=False) == {
        "anchored": ["a"], "unanchored": ["b"]}  # fmt: skip


def test_a_latex_heading_stands_for_something_missing() -> None:
    latex = "\\section{Methods}\nWe analysed the reports of a synthetic database.\n"
    read = anchoring.read_of([latex], latex=True)
    assert anchoring.stands("Methods", read)
    assert anchoring.stands("We analysed the reports", read)
    assert not anchoring.stands("Results", read)


# --------------------------------------------------------------------- the reply and prompt


def test_the_reader_of_the_manuscript_is_asked_to_quote_and_a_design_reader_is_not() -> None:
    told = prompt.system_text({"remit": "the estimator"})
    assert '"quote"' in told and "at least four in a row" in told
    assert "heading of the section where it belongs" in told
    assert "quote" not in prompt.system_text({"remit": "the design"}, design=True)


@pytest.mark.parametrize("given", [None, "", "  \n "])
def test_a_reply_whose_quote_is_null_or_blank_is_filed_without_one(given) -> None:
    findings = [{"severity": "minor", "quote": given, "finding": "Say synthetic."}]
    assert parse_reply(reply_text(findings=findings))["findings"] == [
        {"severity": "minor", "finding": "Say synthetic."}
    ]


def test_a_design_reply_may_quote_and_the_quote_is_kept() -> None:
    findings = [{"severity": "minor", "quote": "the plan's words", "finding": "Say why."}]
    assert parse_reply(reply_text(findings=findings), design=True)["findings"][0]["quote"]


# ------------------------------------------------------------- filed by `review --run`


@pytest.fixture
def providers(monkeypatch) -> Providers:
    transport = Providers()
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", KEY_A)
    monkeypatch.setenv("MISTRAL_API_KEY", KEY_B)
    return transport


def printed(root: Path, name: str = "main.md") -> str:
    """A file of the manuscript as the build prints it, which is what a model is sent."""
    return prompt.gather(loaded(root)).texts[name]


def contained(root: Path) -> str:
    """The Results' first sentence as a model is sent it, with its two counts printed."""
    found = re.search(r"The database contained \S+ reports, of which\s+\S+ named", printed(root))
    assert found, "the example's Results open as they did"
    return found.group()


#: A supplement's words, as written and as printed: they hold no binding.
SUPPLEMENT = "The case definition belongs here rather than in the Methods"


def quoting(root: Path) -> list[dict]:
    """A model's findings: one of each kind a quote is."""
    return [
        {"severity": "major", "where": "Results", "quote": contained(root),
         "finding": "The counts do not say how duplicates were handled."},
        {"severity": "minor", "where": "Supplement", "quote": SUPPLEMENT,
         "finding": "Say why the definition is not in the Methods."},
        {"severity": "major", "where": "Methods", "quote": "Duplicate reports were removed",
         "finding": "Duplicates are said to be removed and the method is not given."},
        {"severity": "major", "where": "Methods", "finding": "No case definition is given."},
        {"severity": "comment", "quote": "Discussion", "finding": "The limits are well put."},
        {"severity": "minor", "quote": "The database contained {{results.cohort.n_reports}}",
         "finding": "The binding as the source writes it, which no model is sent."},
    ]  # fmt: skip


@pytest.fixture
def read_by_a_model(project: Path, providers: Providers) -> Path:
    """The example's review replaced by one round read by one model, whose findings quote
    the manuscript each way `quoting` lists."""
    shutil.rmtree(project / "review")
    configure(project, MODEL_A)
    said = quoting(project)
    providers.default = lambda request: answer(reply_text("major-revision", said))
    assert main(["review", str(project), "--run", "--yes"]) == 0
    return project


def model_readings(root: Path) -> list[Path]:
    return sorted((root / "review" / "round-1").glob("*.*.yaml"))


def test_a_model_s_quotes_are_looked_for_in_what_it_was_sent(read_by_a_model: Path) -> None:
    """Its printed counts, the supplement and a heading stand; words the manuscript has not,
    no quote, and a binding as the source writes it do not."""
    for path in model_readings(read_by_a_model):
        document = read_structured(path)
        assert validate(document, "review", path).ok
        assert document["quotes"] == {"anchored": ["r1-01", "r1-02", "r1-05"],
                                      "unanchored": ["r1-03", "r1-04", "r1-06"]}  # fmt: skip
        assert document["findings"][0]["quote"] == contained(read_by_a_model)
        assert document["reading_sha256"] == reading_digest(document)


def test_check_counts_anchored_and_unanchored_findings_apart_and_notes_each_reading(
    read_by_a_model: Path,
) -> None:
    report = check_review(loaded(read_by_a_model))
    readings = len(model_readings(read_by_a_model))
    assert report.counts["review_findings_anchored"] == 3 * readings
    assert report.counts["review_findings_unanchored"] == 3 * readings
    notes = [f for f in report.findings if f.code == "finding-unanchored"]
    assert len(notes) == readings and {f.severity for f in notes} == {INFO}
    assert "3 of 6 findings" in notes[0].message and "r1-03, r1-04, r1-06" in notes[0].message


def test_an_unanchored_major_finding_still_has_to_be_answered(read_by_a_model: Path) -> None:
    """D1.1: filed, marked, counted apart, and still answered under G11."""
    report = check_review(loaded(read_by_a_model), submission=True)
    opened = [f.message for f in report.failures if f.code == "open-major-finding"]
    assert any(" r1-01:" in message for message in opened)
    assert any(" r1-03 [unanchored]:" in message for message in opened)
    assert any(" r1-04 [unanchored]:" in message for message in opened)


def test_the_run_says_how_many_findings_are_anchored(project: Path, providers, capsys) -> None:
    shutil.rmtree(project / "review")
    configure(project, MODEL_A)
    said = quoting(project)
    providers.default = lambda request: answer(reply_text("major-revision", said))
    assert main(["review", str(project), "--run", "--yes"]) == 0
    assert "6 findings (3 major); 3 anchored, 3 unanchored" in capsys.readouterr().out


def test_review_shows_anchored_and_unanchored_findings_apart(read_by_a_model: Path, capsys) -> None:
    capsys.readouterr()
    main(["review", str(read_by_a_model)])
    assert "6 findings, 3 major (3 open); 3 anchored, 3 unanchored" in capsys.readouterr().out


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["quotes"]["anchored"].append("r1-03"),
        lambda d: d.pop("quotes"),
        lambda d: d["findings"][2].update(quote="We analysed a synthetic spontaneous"),
    ],
)
def test_what_was_found_of_the_quotes_is_sealed(read_by_a_model: Path, edit) -> None:
    """A finding made anchored by hand, the check taken out, or a quote changed after filing
    is an edit of the reading, and its lists no longer count."""
    path = model_readings(read_by_a_model)[0]
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = check_review(loaded(read_by_a_model), submission=True)
    assert [f.path for f in report.failures if f.code == "reading-altered"] == [path]
    assert path not in [f.path for f in report.findings if f.code == "finding-unanchored"]


def test_a_reading_with_no_findings_has_no_quotes_to_check(project: Path, providers) -> None:
    shutil.rmtree(project / "review")
    configure(project, MODEL_A)
    providers.default = lambda request: answer(reply_text("pass", []))
    assert main(["review", str(project), "--run", "--yes"]) == 0
    assert all("quotes" not in read_structured(p) for p in model_readings(project))


def test_a_design_reading_keeps_its_quote_and_has_none_checked(
    project: Path, providers: Providers
) -> None:
    """Basile, 2026-11-07: design rounds are not in this change. Their readers are not
    asked to quote, and a quote one gives is kept, sealed, and looked for nowhere."""
    from test_corruption import _feasibility_said

    configure(project, MODEL_A)
    _feasibility_said(project, "design", feasibility__n_reports=4000)
    findings = [{"severity": "major", "quote": "words of no plan at all", "finding": "Why?"}]
    providers.default = lambda request: answer(reply_text("major-revision", findings))
    assert main(["review", str(project), "--design", "--run", "--yes"]) == 0
    filed = sorted((project / "review" / "design" / "round-1").glob("*.*.yaml"))
    assert filed
    for path in filed:
        document = read_structured(path)
        assert document["findings"][0]["quote"] == "words of no plan at all"
        assert "quotes" not in document
        assert document["reading_sha256"] == reading_digest(document)


# ------------------------------------------------------------- sealed by `review --seal`


def file_by_hand(root: Path, findings: str, *flags: str) -> Path:
    assert main(["review", str(root), "--record", "fresh-reader", "--round", "9",
                 "--remit", "the manuscript as it stands",
                 "--verdict", "major-revision", *flags]) == 0  # fmt: skip
    path = next((root / "review" / "round-9").glob("fresh-reader*.yaml"))
    text = path.read_text(encoding="utf-8")
    path.write_bytes(text.replace("findings: []\n", "findings:\n" + findings).encode("utf-8"))
    return path


def seal(root: Path, *flags: str) -> int:
    return main(["review", str(root), "--seal", "fresh-reader", "--round", "9", *flags])


def hand_findings(root: Path) -> str:
    """A person's findings: quoting the source with its binding, the printed text, a
    heading, the supplement, words not there, and one quoting nothing."""
    findings = [
        {"id": "h1", "severity": "major", "finding": "The counts are bare.",
         "quote": "The database contained {{results.cohort.n_reports}} reports"},
        {"id": "h2", "severity": "minor", "finding": "Say what was counted.",
         "quote": contained(root)},
        {"id": "h3", "severity": "major", "finding": "No limits.", "quote": "# Discussion"},
        {"id": "h4", "severity": "minor", "finding": "Move it.", "quote": SUPPLEMENT},
        {"id": "h5", "severity": "major", "finding": "Said and not done.",
         "quote": "Duplicate reports were removed"},
        {"id": "h6", "severity": "comment", "finding": "Well written."},
    ]  # fmt: skip
    dumped = yaml.safe_dump(findings, sort_keys=False, allow_unicode=True, width=10**6)
    return dumped


def test_a_hand_filed_reading_s_quotes_are_looked_for_when_it_is_sealed(
    project: Path, capsys
) -> None:
    """As written, with a binding in it, and as printed, its value in: a person may have read
    either. A person's finding that quotes nothing is in neither list (D1.2)."""
    path = file_by_hand(project, hand_findings(project))
    before = path.read_bytes()
    capsys.readouterr()
    assert seal(project) == 0
    said = capsys.readouterr().out
    assert "quotes: 4 found in what the reading read, 1 not (h5)" in said
    document = read_structured(path)
    assert document["quotes"] == {"anchored": ["h1", "h2", "h3", "h4"], "unanchored": ["h5"]}
    assert path.read_bytes().startswith(before), "nothing the reader wrote is touched"
    assert document["reading_sha256"] == reading_digest(document)
    report = check_review(loaded(project))
    assert report.counts["review_findings_anchored"] == 4
    assert report.counts["review_findings_unanchored"] == 1
    note = next(f for f in report.findings if f.code == "finding-unanchored")
    assert note.path == path and "1 of 6 findings" in note.message


def test_a_reading_that_read_only_the_main_text_does_not_anchor_a_quote_of_the_supplement(
    project: Path,
) -> None:
    path = file_by_hand(project, hand_findings(project))
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["file_sha256"] = {"main.md": document["file_sha256"]["main.md"]}
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), "utf-8")
    assert seal(project) == 0
    assert read_structured(path)["quotes"]["unanchored"] == ["h4", "h5"]


def test_a_reading_whose_files_changed_before_it_was_sealed_is_sealed_unchecked(
    project: Path, capsys
) -> None:
    """D1.3: what it read is not here to read again, so no check is made, and that is
    said."""
    path = file_by_hand(project, hand_findings(project))
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text(encoding="utf-8") + "\nAdded since.\n", "utf-8")
    capsys.readouterr()
    assert seal(project) == 0
    said = capsys.readouterr().out
    assert "quotes not looked for: main.md changed since the reading was filed" in said
    assert "none of its findings is counted anchored or unanchored" in said
    document = read_structured(path)
    assert "quotes" not in document and document["reading_sha256"] == reading_digest(document)
    report = check_review(loaded(project))
    assert report.counts["review_findings_anchored"] == 0
    assert "finding-unanchored" not in {f.code for f in report.findings}


def test_a_model_s_reading_sealed_again_must_still_quote(read_by_a_model: Path) -> None:
    """Round 1 of #581: a reading `review --run` filed, its seal and its `quotes` taken out
    and sealed by hand, is still a model's (it has `provenance`), so its finding that quotes
    nothing is unanchored (D1.2)."""
    path = model_readings(read_by_a_model)[0]
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    del document["reading_sha256"], document["quotes"]
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), "utf-8")
    reviewer = path.name.split(".")[0]
    assert main(["review", str(read_by_a_model), "--seal", reviewer, "--round", "1",
                 "--reading", MODEL_A]) == 0  # fmt: skip
    quotes = read_structured(path)["quotes"]
    assert "r1-04" in quotes["unanchored"] and "r1-03" in quotes["unanchored"]


def test_a_reading_none_of_whose_findings_quotes_is_sealed_with_one_line(
    project: Path, capsys
) -> None:
    path = file_by_hand(project, "- id: h1\n  severity: major\n  finding: No definition.\n")
    before = path.read_bytes()
    assert seal(project) == 0
    assert re.fullmatch(rb"reading_sha256: [0-9a-f]{64}\n", path.read_bytes()[len(before) :])
    assert "quotes" not in capsys.readouterr().out


def test_quotes_written_by_hand_are_refused_at_the_seal(project: Path, capsys) -> None:
    path = file_by_hand(project, hand_findings(project))
    path.write_text(path.read_text(encoding="utf-8")
                    + "quotes:\n  anchored: [h5]\n  unanchored: []\n", "utf-8")  # fmt: skip
    before = path.read_bytes()
    assert seal(project) == 2
    assert "`quotes`" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_a_hand_filed_reading_with_windows_line_endings_keeps_them(project: Path) -> None:
    path = file_by_hand(project, hand_findings(project))
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert seal(project) == 0
    data = path.read_bytes()
    assert b"\nquotes:" in data and data.count(b"\n") == data.count(b"\r\n")
    assert "reading-altered" not in {f.code for f in check_review(loaded(project)).findings}


# ------------------------------------------------------------------ readings of before


def test_the_example_s_sealed_readings_are_read_as_before(project: Path) -> None:
    """D1.4: no reading filed before quotes were checked says anything of them."""
    report = check_review(loaded(project))
    assert report.counts["review_findings_anchored"] == 0
    assert report.counts["review_findings_unanchored"] == 0
    assert "finding-unanchored" not in {f.code for f in report.findings}
    assert "reading-altered" not in {f.code for f in report.findings}


def test_a_quotes_list_on_an_unsealed_reading_is_not_counted(project: Path) -> None:
    findings = (
        "- id: h1\n  severity: major\n  finding: Not there.\n"
        "  quote: Duplicate reports were removed\nquotes:\n  anchored: [h1]\n  unanchored: []\n"
    )
    file_by_hand(project, findings)
    report = check_review(loaded(project))
    assert report.counts["review_findings_anchored"] == 0
