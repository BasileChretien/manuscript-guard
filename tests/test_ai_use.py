"""G4's AI-use check (`gates/ai_use.py`, `text/model_names.py`): DESIGN.md, "The AI-use
statement names the models the records hold"."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts.project import Project, load_project
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates.ai_use import (
    APPRAISED,
    NOT_STATED,
    UNDECLARED,
    UNNAMED,
    check_ai_use,
    made_by,
    model_work,
    places,
)
from manuscript_guard.text.model_names import named, names, names_of

# ------------------------------------------------------------------------- the name rule

#: The section's worked examples, each as it says: (text, name, named).
WORKED = [
    ("Claude Opus 4.5", "claude-opus-4-5", True),
    ("claude opus 4-5", "claude-opus-4-5", True),
    ("Claude 5 Opus", "claude-opus-4-5", False),
    ("Claude Opus 4.5.1", "claude-opus-4-5", False),
    ("Claude Opus 4.5", "claude-opus-4", False),
    ("GPT-4o", "gpt-4", False),
    ("GPT-5.1", "gpt-5", False),
    ("GPT-4o 3 times", "o3", False),
    ("GPT-5, 1", "gpt-5.1", False),
    ("Qwen 2.5 72B", "qwen2.5-72b", True),
    ("We used GPT-5.1 (OpenAI).", "gpt-5.1", True),
    ("GPT-4o", "gpt4o", True),
    ("Claude Opus 50", "claude-opus-5", False),
    # The limits, as written down.
    ("o3-mini", "o3", True),
    ("GPT-4o mini", "gpt-4o", True),
    ("Claude Opus 4, 5 times", "claude-opus-4-5", True),
    ("Claude Opus v4.5", "claude-opus-4-5", False),
    ("we did not use GPT-5.1", "gpt-5.1", True),
]


@pytest.mark.parametrize(("text", "name", "expected"), WORKED)
def test_a_statement_names_a_model_as_the_section_says(text: str, name: str,
                                                       expected: bool) -> None:  # fmt: skip
    assert names(text, name) is expected


@pytest.mark.parametrize(
    ("spellings", "text", "expected"),
    [
        (("openrouter/openai/gpt-5.1",), "GPT-5.1", True),
        (("openrouter/anthropic/claude-opus-4-5-20251101",), "Claude Opus 4.5", True),
        (("claude-opus-4-5@20251101",), "Claude Opus 4.5", True),
        (("gpt-4o-2024-08-06",), "GPT-4o", True),
        (("mistral-large-latest",), "Mistral Large", True),
        (("llama3.1:8b-instruct-q4_K_M",), "Llama 3.1", True),
        (("llama3.1:70b",), "Llama 3.1 8B", True),
        (("gpt-5.1",), "ChatGPT", False),
        (("gpt-5.1",), "OpenAI's model", False),
        (("gpt-5.1-chat", "gpt-5.1-2026-08-01"), "gpt 5.1", True),
        (("claude-opus-4-5-0605",), "Claude Opus 4.5", False),
    ],
)
def test_a_model_is_named_by_any_of_its_names(spellings: tuple, text: str,
                                              expected: bool) -> None:  # fmt: skip
    assert named(text, spellings) is expected


def test_the_ways_of_shortening_a_name_combine() -> None:
    spelt = "openrouter/anthropic/claude-opus-4-5-20251101"
    found = names_of(spelt)
    assert "claude-opus-4-5" in found and found[0] == spelt
    assert names_of(None, "", "  ") == ()


def test_a_name_typed_in_full_width_is_the_name_typed_plainly() -> None:
    """A Japanese input method types full-width letters, digits and marks (round 1)."""
    assert names("ＧＰＴ－５．１", "gpt-5.1") and names("ＧＰＴ-５.１ (OpenAI)", "gpt-5.1")
    # Letters of a script written without spaces run on into the name's last word: a limit.
    assert not names("GPT-5.1を用いた", "gpt-5.1")


def test_a_name_with_no_letter_or_digit_names_nothing() -> None:
    assert not names("Claude Opus 4.5", "--") and not names("", "gpt-5.1")


# --------------------------------------------------------------------- who made a record


@pytest.mark.parametrize(
    ("name", "provenance", "expected"),
    [
        ("openai/gpt-5.1", None, ("openai", "gpt-5.1", None)),
        ("openrouter/openai/gpt-5.1", None, ("openrouter", "openai/gpt-5.1", None)),
        ("Claude Code", None, None),
        ("claude-opus-5", None, None),
        ("Ada Example", None, None),
        ("anthropic/", None, None),
        (" openai / gpt-5.1", None, None),
        ("biostatistician", {"provider": "openai", "model": "gpt-5.1",
                             "model_reported": "gpt-5.1-2026-08-01"},
         ("openai", "gpt-5.1", "gpt-5.1-2026-08-01")),
        # A provenance with no model says nothing; the name is read alone.
        ("Ada Example", {"provider": "openai"}, None),
        ("mistral/mistral-large", {"note": "x"}, ("mistral", "mistral-large", None)),
    ],
)  # fmt: skip
def test_a_record_says_a_model_made_it_by_provenance_or_by_a_provider_model_name(
    name: str, provenance: object, expected: object
) -> None:
    assert made_by(name, provenance) == expected


def _write(path: Path, document: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")  # fmt: skip
    return path


def _reading(root: Path, name: str, reader: str, *, number: int = 1, findings=None,
             provenance=None, design: bool = False) -> Path:  # fmt: skip
    folder = root / "review" / ("design" if design else "") / f"round-{number}"
    document = {"schema": "manuscript-guard/design-review/1" if design
                else "manuscript-guard/review/1",
                "round": number, "reviewer": name, "reviewed_by": reader,
                "reviewed_on": "2026-11-01", "verdict": "minor-revision"}  # fmt: skip
    if provenance:
        document["provenance"] = provenance
    if findings:
        document["findings"] = findings
    return _write(folder / f"{name}.yaml", document)


def test_every_kind_of_record_a_model_s_work_is_filed_in_is_read(project: Path) -> None:
    _reading(project, "stats", "openai/gpt-5.1", number=11, findings=[
        {"id": "f1", "severity": "minor", "finding": "x",
         "resolution": "Edited in Word as stats (openai/gpt-5.1) suggested: …"},
        {"id": "f2", "severity": "minor", "finding": "y", "resolution": "Done by hand."},
    ])  # fmt: skip
    _reading(project, "plan", "mistral/mistral-large-latest", number=1, design=True)
    currency = project / "literature" / "currency"
    _write(currency / "readings" / "c1.kimi.1.yaml", {
        "schema": "manuscript-guard/currency-reading/1", "reader": "moonshot/kimi-k2",
        "number": 1, "read_on": "2026-10-02"})  # fmt: skip
    _write(currency / "replies" / "c1.1.gemini.yaml", {
        "schema": "manuscript-guard/currency-assessment/1", "reader": "x",
        "provenance": {"provider": "google", "model": "gemini-2.5-pro"}, "number": 1})
    _write(currency / "searches" / "c1-1.yaml", {
        "schema": "manuscript-guard/currency-search/1", "terms_by": "deepseek/deepseek-chat",
        "number": 1, "searched_on": "2026-10-03"})  # fmt: skip
    _write(project / "figures" / "extra.review.yaml", {
        "schema": "manuscript-guard/figure-review/1", "reviewed_by": "anthropic/claude-opus-5",
        "reviewed_on": "2026-10-04"})  # fmt: skip
    _write(project / "design" / "methods_review.yaml", {
        "schema": "manuscript-guard/methods-review/1",
        "studies": [{"citekey": "s", "methods": [
            {"field": "design", "appraisal": {"proposed_by": "openai/o3",
                                              "proposed_on": "2026-09-01"}},
            {"field": "outcome", "appraisal": {"proposed_by": "Ada Example"}},
            # The schema takes a list of appraisals for one method too (round 1 of the code).
            {"field": "exposure", "appraisal": [{"proposed_by": "openai/o4-mini"},
                                                {"proposed_by": "Ada Example"}]}]}]})
    # A refused reply is not read, nor a record a person made.
    (project / "review" / "round-11" / "refused").mkdir(parents=True)
    (project / "review" / "round-11" / "refused" / "stats.txt").write_text(
        "This is not a review record. It is the reply openai/gpt-4o gave", encoding="utf-8")
    _reading(project, "person", "Ada Example", number=11)

    works = model_work(load_project(project)[0])
    assert sorted((w.model, w.did, w.number, w.on, w.taken) for w in works) == sorted([
        ("gpt-5.1", "read the manuscript", 11, "2026-11-01", 1),
        ("mistral-large-latest", "read the analysis plan", 1, "2026-11-01", 0),
        ("kimi-k2", "read a cited work for its currency", 1, "2026-10-02", 0),
        ("gemini-2.5-pro", "read a reply in Word", 1, None, 0),
        ("deepseek-chat", "wrote a literature search's terms", 1, "2026-10-03", 0),
        ("claude-opus-5", "read a figure", None, "2026-10-04", 0),
        ("o3", APPRAISED, None, "2026-09-01", 0),
        ("o4-mini", APPRAISED, None, None, 0),
    ])  # fmt: skip


def test_the_example_shows_no_model_s_work(project: Path) -> None:
    """Its readers are named "Claude Code" and "claude-opus-5", which read as a person's
    (a limit, written down), so it has nothing to report."""
    loaded = load_project(project)[0]
    assert model_work(loaded) == []
    assert check_ai_use(loaded, "submission").findings == ()


# --------------------------------------------------------------------- the statement's text


def test_a_heading_match_takes_its_line_and_section_and_a_phrase_its_paragraph() -> None:
    text = ("# Methods\n\nWords.\n\n## Use of GPT-5.1\n\nWe used it.\n\n### More\n\nAlso.\n\n"
            "## Results\n\nOther.\n\nWriting was helped by Claude Opus 5.\nIts lines.\n\n"
            "Next paragraph.\n")  # fmt: skip
    assert places(text, r"(?im)^#+\s*use of") == [
        "## Use of GPT-5.1\n\nWe used it.\n\n### More\n\nAlso.\n\n"
    ]
    assert places(text, r"helped by") == ["Writing was helped by Claude Opus 5.\nIts lines."]


def test_a_comment_inside_a_paragraph_does_not_split_it_and_is_not_read() -> None:
    text = "Before.\n\nWe used\n<!-- GPT-4o -->\nGPT-5.1 to edit.\n\nAfter.\n"
    [place] = places(text, "to edit")
    assert "GPT-5.1" in place and "GPT-4o" not in place and "We used" in place
    # A blank line inside the comment ends no paragraph either (round 1).
    [place] = places("We used GPT-5.1\n<!-- a\n\nb -->\nand Claude Opus 5 to edit.\n", "to edit")
    assert "GPT-5.1" in place and "Claude Opus 5" in place and "a" not in place.split()


def test_a_record_that_does_not_fit_its_schema_stops_nothing(project: Path) -> None:
    """G0 reports the file; the check reads what it can (round 1)."""
    from manuscript_guard.gates.journal import check_journal

    _write(project / "design" / "methods_review.yaml",
           {"schema": "manuscript-guard/methods-review/1", "studies": 3})
    _write(project / "review" / "round-11" / "odd.yaml",
           {"schema": "manuscript-guard/review/1", "reviewed_by": 7, "findings": "none"})
    loaded = load_project(project)[0]
    assert model_work(loaded) == []
    assert check_ai_use(loaded, "submission").findings == ()
    assert not [f for f in check_journal(loaded).findings if f.code == "gate-errored"]


def test_a_statement_in_latex_is_read_in_the_printed_view(tmp_path: Path) -> None:
    from manuscript_guard.gates.journal import main_text

    (tmp_path / "manuscript").mkdir()
    (tmp_path / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Methods}\nWords.\n"
        "\\section{Use of AI}\nWe used GPT-5.1 to edit the English.\n"
        "\\section{Results}\nOther.\n\\end{document}\n", encoding="utf-8")
    loaded = Project(tmp_path, {"schema": "manuscript-guard/paper/1"}, None)
    [place] = places(main_text(loaded), r"(?im)^#+\s*use of ai")
    assert "GPT-5.1" in place and "Results" not in place and "Other" not in place


def test_a_latex_supplement_s_statement_is_read_from_the_file_its_build_prints(
    tmp_path: Path,
) -> None:
    from manuscript_guard.gates.ai_use import default_places, supplement_text

    folder = tmp_path / "manuscript" / "supplementary"
    folder.mkdir(parents=True)
    (tmp_path / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Methods}\nW.\n\\end{document}\n",
        encoding="utf-8")  # fmt: skip
    # A file the supplement's entry does not input is not printed, and not read.
    (folder / "loose.tex").write_text("\\section{Use of AI}\nClaude Opus 5.\n", "utf-8")
    loaded = Project(tmp_path, {"schema": "manuscript-guard/paper/1"}, None)
    assert default_places(supplement_text(loaded)) == []
    (folder / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Use of AI}\n"
        "We used GPT-5.1 to edit.\n\\section{Tables}\nT.\n\\end{document}\n", encoding="utf-8")
    [place] = default_places(supplement_text(loaded))
    assert "GPT-5.1" in place and "Tables" not in place


# ------------------------------------------------------------------------------- the check


def _require(project: Path, pattern: str = r"(?im)^#+\s*use of (generative )?ai") -> None:
    path = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["required_statements"].append({"id": "ai-use", "kind": "ai_use",
                                             "pattern": pattern, "why": "Name each tool."})
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")  # fmt: skip


def _say(project: Path, text: str, *, supplement: bool = False) -> None:
    path = (next((project / "manuscript" / "supplementary").glob("*.md")) if supplement
            else project / "manuscript" / "main.md")  # fmt: skip
    path.write_text(path.read_text(encoding="utf-8") + "\n" + text + "\n", encoding="utf-8")


def _declare(project: Path, uses: list) -> None:
    path = project / "authors.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["ai_use"] = {"declared_by": "Ada Example", "declared_on": "2026-11-07",
                          "uses": uses}  # fmt: skip
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")  # fmt: skip


def _found(project: Path, stage: str | None = None) -> list[tuple[str, str, str]]:
    report = check_ai_use(load_project(project)[0], stage)
    return [(f.code, f.severity, f.message) for f in report.findings]


def test_a_required_statement_that_names_no_model_on_record_warns_then_fails(
    project: Path,
) -> None:
    _require(project)
    _declare(project, [])
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "## Use of AI\n\nNo AI tools were used.")
    assert _found(project, "drafting") == [
        (UNNAMED, WARN, "the AI-use statement does not name gpt-5.1 (openai)")]
    assert [s for _c, s, _m in _found(project, "submission")] == [FAIL]


def test_a_statement_that_names_every_model_and_tool_passes(project: Path) -> None:
    _require(project)
    _declare(project, [{"tool": "DeepL", "purpose": "translation", "what": "x"}])
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "## Use of AI\n\nGPT-5.1 read the draft; DeepL translated a quotation.")
    assert _found(project, "submission") == []


def test_every_model_and_every_declared_tool_left_out_is_listed(project: Path) -> None:
    """D6.5: one model named of two, and a declared tool not named, is a finding."""
    _require(project)
    _declare(project, [{"tool": "Claude Opus 5", "provider": "Anthropic",
                        "purpose": "drafting", "what": "x"}])  # fmt: skip
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _reading(project, "clinic", "mistral/mistral-large-2411", number=11)
    _say(project, "## Use of AI\n\nGPT-5.1 read the draft.")
    [(code, _s, message)] = _found(project)
    assert code == UNNAMED
    assert message == ("the AI-use statement does not name mistral-large-2411 (mistral), "
                       "Claude Opus 5 (Anthropic)")


def test_a_declared_tool_whose_name_begins_with_a_model_s_on_record_is_still_wanted(
    project: Path,
) -> None:
    """GPT-4o mini, declared for drafting, is another model than the GPT-4o that read: a
    statement naming GPT-4o names the reader and not the drafting tool (round 1)."""
    _require(project)
    _declare(project, [{"tool": "GPT-4o mini", "purpose": "drafting", "what": "x"}])
    _reading(project, "stats", "openai/gpt-4o", number=11)
    _say(project, "## Use of AI\n\nGPT-4o read the draft.")
    assert _found(project, "submission") == [
        (UNNAMED, FAIL, "the AI-use statement does not name GPT-4o mini")]


def test_a_declared_tool_that_is_a_model_on_record_is_asked_for_once(project: Path) -> None:
    _require(project)
    _declare(project, [{"tool": "GPT-4o", "purpose": "editing", "what": "x"}])
    _reading(project, "stats", "openai/gpt-4o", number=11)
    _say(project, "## Use of AI\n\nA model read the draft.")
    assert _found(project) == [
        (UNNAMED, WARN, "the AI-use statement does not name gpt-4o (openai)")]


def test_a_heading_s_own_words_name_the_model(project: Path) -> None:
    _require(project, r"(?im)^#+\s*use of")
    _declare(project, [])
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "## Use of GPT-5.1\n\nWe used it to edit the English.")
    assert _found(project, "submission") == []


def test_a_statement_split_between_two_places_is_read_as_one(project: Path) -> None:
    _require(project, r"(?im)^#+\s*acknowledg|analysis code was written")
    _declare(project, [])
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _reading(project, "code", "anthropic/claude-opus-4-5", number=11)
    _say(project, "Some of the analysis code was written with Claude Opus 4.5.\n\n"
                  "## Acknowledgements\n\nGPT-5.1 read a draft as a reviewer.")  # fmt: skip
    assert _found(project, "submission") == []


def test_a_required_statement_only_in_the_supplement_is_none(project: Path) -> None:
    """The journal reads its statements in the paper: `missing-required-statement`, from
    the journal's own check, whose hint names the models."""
    from manuscript_guard.gates.journal import check_journal

    _require(project)
    _declare(project, [])
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "## Use of AI\n\nGPT-5.1 read the draft.", supplement=True)
    assert _found(project) == []
    loaded = load_project(project)[0]
    [missing] = [f for f in check_journal(loaded).findings
                 if f.code == "missing-required-statement" and "ai-use" in f.message]
    assert "gpt-5.1 (openai)" in missing.hint and "review --ai-use" in missing.hint


def test_a_name_missing_from_the_statement_but_in_the_supplement_is_said(project: Path) -> None:
    _require(project)
    _declare(project, [])
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "## Use of AI\n\nA model read the draft.")
    _say(project, "GPT-5.1 read the draft.", supplement=True)
    report = check_ai_use(load_project(project)[0], None)
    [finding] = report.findings
    assert "gpt-5.1 named in the supplement" in finding.hint


def test_a_journal_that_asks_for_nothing_gets_a_note_where_nothing_is_said(
    project: Path,
) -> None:
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    [(code, severity, _message)] = _found(project, "submission")
    assert (code, severity) == (NOT_STATED, INFO)


def test_with_no_journal_asking_a_model_named_anywhere_is_disclosed(project: Path) -> None:
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "The analysis code was checked with GPT-5.1.", supplement=True)
    assert _found(project, "submission") == []


def test_a_default_heading_naming_none_warns_and_never_fails(project: Path) -> None:
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, "## Declaration of generative AI use\n\nNone was used.", supplement=True)
    assert [(c, s) for c, s, _m in _found(project, "submission")] == [(UNNAMED, WARN)]


@pytest.mark.parametrize("heading", ["Generative models", "Language model performance",
                                     "Use of the registry"])  # fmt: skip
def test_a_heading_with_no_statement_word_or_no_tool_word_is_no_statement(
    project: Path, heading: str
) -> None:
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, f"## {heading}\n\nWords.")
    assert [c for c, _s, _m in _found(project)] == [NOT_STATED]


@pytest.mark.parametrize("heading", ["Use of LLMs", "AI disclosure",
                                     "Statement on the use of artificial intelligence"])
def test_a_default_heading_s_words_may_be_singular_or_plural(project: Path,
                                                             heading: str) -> None:  # fmt: skip
    _reading(project, "stats", "openai/gpt-5.1", number=11)
    _say(project, f"## {heading}\n\nWords.")
    assert [c for c, _s, _m in _found(project)] == [UNNAMED]


def test_the_authors_list_is_asked_for_where_the_journal_asks(project: Path) -> None:
    _require(project)
    assert [(c, s) for c, s, _m in _found(project)] == [(UNDECLARED, INFO)]
    _declare(project, [])
    assert _found(project) == []


def test_review_ai_use_lists_what_the_records_show_and_writes_nothing(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuscript_guard.cli import main

    _reading(project, "stats", "openai/gpt-5.1", number=11, findings=[
        {"id": "f1", "severity": "minor", "finding": "x",
         "resolution": "Edited in Word as stats (openai/gpt-5.1) suggested: …"}])  # fmt: skip
    _declare(project, [{"tool": "DeepL", "purpose": "translation", "what": "A quotation."}])
    before = sorted(p.as_posix() for p in project.rglob("*"))
    assert main(["review", str(project), "--ai-use"]) == 0
    said = capsys.readouterr().out
    assert "gpt-5.1, from openai" in said and "read the manuscript: 1 record(s)" in said
    assert "suggested wording taken in 1 finding(s)" in said
    assert "DeepL, translation: A quotation." in said
    assert sorted(p.as_posix() for p in project.rglob("*")) == before
    assert main(["review", str(project), "--ai-use", "--providers"]) == 2
