"""G4 against a journal profile's boxes, graphical abstract and sharing policy
(`gates/journal_boxes.py`, `text/boxes.py`): the boxes the journal prints beside the abstract
are in the main text and within its limits, a warning until submission and a failure there
where the box is required; G8 reads a box's numbers as a summary's; and each new rule of the
profile is quoted like every other."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.contracts._schema import validate
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates import check_boxes, check_journal, check_reported
from manuscript_guard.gates.journal_quotes import rules_of
from manuscript_guard.gates.reported import Walk
from manuscript_guard.policy import BINDS_AT, DRAFTING, SUBMISSION
from manuscript_guard.text.boxes import box_rules, markdown_boxes, markdown_items

PROFILE = Path("profiles") / "journals" / "demo-journal.yaml"
MAIN = Path("manuscript") / "main.md"
CODES = ("box-missing", "box-items", "box-item-long", "box-over-limit", "box-headings-missing")

HIGHLIGHTS = {"id": "highlights", "heading": "^highlights$", "required": True, "items_min": 3,
              "items_max": 5, "item_max_chars": 85}  # fmt: skip
KEY_POINTS = {"id": "key-points", "heading": "^key points$", "max_words": 40,
              "headings": ["Question", "Findings", "Meaning"]}  # fmt: skip
WRITTEN = (
    "# Highlights\n\n- Reports of hepatic injury were disproportionate.\n"
    "- The odds ratio was {{results.ror.point}}.\n- Disproportionality is not incidence.\n\n"
    "# Key points\n\n**Question** Is hepatic injury reported more often?\n\n"
    "**Findings** Reports were disproportionate.\n\n**Meaning** A signal, not a risk.\n\n"
)


def _asks(root: Path, **blocks) -> None:
    path = root / PROFILE
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document.update(blocks)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _write(root: Path, boxes: str, *, into: Path = MAIN) -> None:
    path = root / into
    text = path.read_text(encoding="utf-8")
    if into == MAIN:
        text = text.replace("# Abstract\n", boxes + "# Abstract\n", 1)
    else:
        text = text + "\n\n" + boxes
    path.write_text(text, encoding="utf-8")


def _found(root: Path, stage: str = DRAFTING) -> list[tuple[str, str, str]]:
    project, _ = load_project(root)
    namespace = load_namespace(project)[0]
    report = check_boxes(project, namespace, stage)
    return [(f.code, f.severity, f.message) for f in report.findings]


def _codes(root: Path, stage: str = DRAFTING) -> dict[str, str]:
    return {code: severity for code, severity, _message in _found(root, stage)}


# ------------------------------------------------------------------------------ the profile


def test_the_new_blocks_are_a_valid_profile_and_each_rule_is_keyed_for_its_quote() -> None:
    document = {
        "schema": "manuscript-guard/journal/1", "name": "J", "source_url": "u",
        "retrieved_on": "2026-10-28",
        "graphical_abstract": {"required": True, "width_px": 1328, "height_px": 531,
                               "formats": ["tiff", "png"], "aspect_ratio": "2.5:1"},
        "boxes": [HIGHLIGHTS, KEY_POINTS],
        "sharing": {"source_url": "https://example.invalid/sharing", "retrieved_on": "2026-10-28",
                    "accepted": {"where": ["institutional-repository"], "embargo_months": 12}},
    }  # fmt: skip
    assert validate(document, "journal", Path("j.yaml")).ok
    rules = rules_of(document)
    assert {"graphical_abstract.required", "graphical_abstract.width_px", "boxes.highlights",
            "boxes.key-points", "sharing.accepted"} <= set(rules)  # fmt: skip
    # Where the policy was read, and when, are no rules of the page.
    assert "sharing.source_url" not in rules and "sharing.retrieved_on" not in rules


@pytest.mark.parametrize(
    "bad",
    [
        {"boxes": [{"id": "Highlights", "heading": "x"}]},
        {"boxes": [{"id": "highlights"}]},
        {"boxes": [{"id": "highlights", "heading": "x", "colour": "blue"}]},
        {"graphical_abstract": {"aspect_ratio": "wide"}},
        {"sharing": {"published": {"where": ["anywhere"]}}},
    ],
)
def test_a_box_or_a_policy_in_the_wrong_shape_is_refused(bad: dict) -> None:
    document = {"schema": "manuscript-guard/journal/1", "name": "J", "source_url": "u",
                "retrieved_on": "2026-10-28", **bad}  # fmt: skip
    assert not validate(document, "journal", Path("j.yaml")).ok


def test_a_box_with_no_quote_is_named_among_the_unquoted_rules(project: Path) -> None:
    _asks(project, boxes=[HIGHLIGHTS], sharing={"published": {"where": ["personal-site"]}})
    report = check_journal(load_project(project)[0])
    said = next(f.message for f in report.findings if f.code == "journal-rule-unquoted")
    assert "boxes.highlights" in said and "sharing.published" in said


def test_a_box_s_quote_is_held_to_the_stored_page(project: Path) -> None:
    profile = yaml.safe_load((project / PROFILE).read_text(encoding="utf-8"))
    quotes = {**profile["quotes"], "boxes.highlights": "Give three to five highlights."}
    _asks(project, boxes=[HIGHLIGHTS], quotes=quotes)
    report = check_journal(load_project(project)[0])
    assert [f.message for f in report.failures if f.code == "journal-quote-not-on-page"] == [
        'the quote for boxes.highlights is not on the stored page: "Give three to five '
        'highlights."'
    ]


# ------------------------------------------------------------------------------- the boxes


def test_boxes_written_as_the_journal_asks_pass_at_submission(project: Path) -> None:
    _asks(project, boxes=[HIGHLIGHTS, KEY_POINTS])
    _write(project, WRITTEN)
    assert _found(project, SUBMISSION) == []


@pytest.mark.parametrize(
    ("required", "stage", "severity"),
    [(True, DRAFTING, WARN), (True, SUBMISSION, FAIL), (False, SUBMISSION, WARN)],
)
def test_a_missing_box_warns_until_submission_and_fails_there_where_required(
    project: Path, required: bool, stage: str, severity: str
) -> None:
    _asks(project, boxes=[{**HIGHLIGHTS, "required": required}])
    assert _codes(project, stage) == {"box-missing": severity}


def test_a_box_in_the_supplement_is_not_the_box(project: Path) -> None:
    _asks(project, boxes=[HIGHLIGHTS])
    _write(project, WRITTEN, into=Path("manuscript") / "supplementary" / "S1_code_lists.md")
    project_, _ = load_project(project)
    report = check_boxes(project_, load_namespace(project_)[0], SUBMISSION)
    [finding] = report.findings
    assert (finding.code, finding.severity) == ("box-missing", FAIL)
    assert "manuscript/supplementary/S1_code_lists.md" in finding.hint


@pytest.mark.parametrize(
    ("written", "codes"),
    [
        # Two items, of three to five.
        ("# Highlights\n\n- One.\n- Two.\n\n", {"box-items"}),
        # Six.
        ("# Highlights\n\n" + "".join(f"- Item {n}.\n" for n in range(6)) + "\n", {"box-items"}),
        # An item hidden in a comment is no item: two, as printed.
        ("# Highlights\n\n- One.\n- Two.\n<!--\n- Three.\n-->\n\n", {"box-items"}),
        # An item of 86 characters.
        ("# Highlights\n\n- One.\n- Two.\n- " + "x" * 85 + ".\n\n", {"box-item-long"}),
        # Paragraphs where there is no list: three, each an item.
        ("# Highlights\n\nOne.\n\nTwo.\n\nThree.\n\n", set()),
    ],
)
def test_a_box_s_items_are_counted_and_measured_as_printed(
    project: Path, written: str, codes: set[str]
) -> None:
    _asks(project, boxes=[HIGHLIGHTS])
    _write(project, written)
    assert set(_codes(project, SUBMISSION)) == codes
    assert set(_codes(project, DRAFTING).values()) <= {WARN}


def test_a_binding_in_an_item_is_measured_as_its_display(project: Path) -> None:
    """`{{results.ror.point}}` is 21 characters as written and its display far fewer: an
    item measured as written failed a highlight the journal takes."""
    _asks(project, boxes=[{**HIGHLIGHTS, "item_max_chars": 30}])
    _write(project, "# Highlights\n\n- One.\n- Two.\n- The ROR was {{results.ror.point}}.\n\n")
    assert _codes(project, SUBMISSION) == {}
    _write(project, "# Highlights\n\n- One.\n- Two.\n- The reporting odds ratio was "
                    "{{results.ror.point}}.\n\n")  # fmt: skip
    [(code, _severity, message)] = _found(project, SUBMISSION)
    assert code == "box-item-long" and "The reporting odds ratio was 3." in message


def test_a_box_over_its_words_and_without_its_headings_is_reported(project: Path) -> None:
    _asks(project, boxes=[{**KEY_POINTS, "max_words": 10}])
    _write(project, "# Key points\n\n**Question** Is hepatic injury reported more often than "
                    "expected with this drug?\n\n**Findings** Yes.\n\n")  # fmt: skip
    assert _codes(project) == {"box-over-limit": WARN, "box-headings-missing": WARN}
    said = dict((code, message) for code, _s, message in _found(project))
    assert said["box-headings-missing"] == "the box key-points is missing: Meaning"


def test_a_box_heading_that_is_no_pattern_fails_and_the_rest_are_read(project: Path) -> None:
    _asks(project, boxes=[{"id": "highlights", "heading": "(unclosed"}, KEY_POINTS])
    _write(project, WRITTEN)
    assert _codes(project) == {"box-heading-invalid": FAIL}


def test_without_boxes_or_a_profile_nothing_is_said(project: Path) -> None:
    _write(project, WRITTEN)
    assert _found(project, SUBMISSION) == []


def test_no_sharing_block_refuses_nothing(project: Path) -> None:
    """Decided 2026-10-28: with no `sharing:` block a link to the DOI may be shared and
    nothing uploaded, which is the communicate commands' to hold. G4 says nothing of it."""
    report = check_journal(load_project(project)[0])
    assert not [f for f in report.findings if "sharing" in f.message]


# ------------------------------------------------------------------- graphical abstract


def test_a_required_graphical_abstract_is_noted_until_its_folder_exists(project: Path) -> None:
    _asks(project, graphical_abstract={"required": True})
    assert _codes(project, SUBMISSION) == {"graphical-abstract-missing": INFO}
    (project / "communication" / "graphical-abstract").mkdir(parents=True)
    assert _codes(project, SUBMISSION) == {}
    _asks(project, graphical_abstract={"required": False})
    (project / "communication" / "graphical-abstract").rmdir()
    assert _codes(project, SUBMISSION) == {}


# ------------------------------------------------------------------------------- LaTeX


def _latex(root: Path, body: str) -> None:
    folder = root / "manuscript"
    for path in folder.rglob("*.md"):
        path.unlink()
    (folder / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\\section{Introduction}\nx\n"
        "\\section{Results}\nThe ROR was \\mg{results.ror.point}.\n\\end{document}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("body", "codes"),
    [
        ("\\begin{highlights}\n\\item One.\n\\item Two.\n\\item Three.\n\\end{highlights}\n", {}),
        ("\\begin{highlights}\n\\item One.\n\\item Two.\n% \\item Three.\n\\end{highlights}\n",
         {"box-items": FAIL}),
        ("\\section*{Highlights}\n\\begin{itemize}\n\\item One.\n\\item Two.\n\\item Three.\n"
         "\\end{itemize}\n", {}),
        ("\\section*{Highlights}\n\\begin{itemize}\n\\item One.\n\\item " + "x" * 90 + "\n"
         "\\item Three.\n\\end{itemize}\n", {"box-item-long": FAIL}),
        ("% \\begin{highlights}\n% \\item One.\n% \\end{highlights}\n", {"box-missing": FAIL}),
    ],
)  # fmt: skip
def test_a_latex_box_is_read_in_its_environment_or_under_its_heading(
    project: Path, body: str, codes: dict
) -> None:
    _asks(project, boxes=[HIGHLIGHTS])
    _latex(project, body)
    assert _codes(project, SUBMISSION) == codes


# --------------------------------------------------------------------------------- G8


def test_a_number_a_box_gives_is_a_summary_s() -> None:
    rules, _ = box_rules({"boxes": [HIGHLIGHTS]})
    text = ("# Highlights\n\n- {{results.a}} and {{results.b}}.\n\n# Results\n\n{{results.b}}."
            "\n\n# Discussion\n\n{{results.c}}.\n")  # fmt: skip
    given, reported = Walk(None, rules).read(text)
    assert [(one.key, one.heading) for one in given] == [("a", "Highlights"), ("b", "Highlights")]
    assert reported == {"b"}
    # Without the box, the heading names no part of the paper, as before.
    assert Walk(None).read(text)[0] == []


def test_g8_warns_of_a_number_only_a_box_gives(project: Path) -> None:
    _write(project, "# Highlights\n\n- The signal was met: {{results.signal.met}}.\n\n")
    project_, _ = load_project(project)

    def unreported() -> list[str]:
        results = load_namespace(project_)[1]
        return [f.message for f in check_reported(project_, results).findings]

    assert not any("results.signal.met" in said for said in unreported())
    _asks(project, boxes=[HIGHLIGHTS])
    assert any("results.signal.met is given under 'Highlights'" in s for s in unreported())


def test_g8_reads_a_latex_box_environment_as_a_summary(project: Path) -> None:
    _asks(project, boxes=[HIGHLIGHTS])
    _latex(project, "\\begin{highlights}\n\\item Met: \\mg{results.signal.met}.\n"
                    "\\item The ROR was \\mg{results.ror.point}.\n\\end{highlights}\n")
    project_, _ = load_project(project)
    results = load_namespace(project_)[1]
    said = [f.message for f in check_reported(project_, results).findings]
    assert said == ["results.signal.met is given under 'highlights' and reported nowhere in the "
                    "Methods, the Results, a table or a figure"]  # fmt: skip


# ------------------------------------------------------------------------ the reader


def test_a_list_item_runs_on_over_its_lines_and_a_paragraph_after_the_list_is_none() -> None:
    body = "\n- One\n  more.\n- Two\nlazily.\n\nAfter the list.\n\n## Sub\n\n"
    assert markdown_items(body) == ["One\n  more.", "Two\nlazily."]
    assert markdown_items("\nFirst.\n\nSecond\nline.\n\n### Head\n\nThird.\n") == [
        "First.", "Second\nline.", "Third."]


def test_a_box_s_heading_is_read_as_printed_and_front_matter_is_none() -> None:
    rules, _ = box_rules({"boxes": [HIGHLIGHTS]})
    text = "---\ntitle: x\n# Highlights\n---\n\n## 1. **Highlights**\n\n- One.\n"
    [found] = markdown_boxes(text, rules, {})
    assert (found.title, found.line, found.items) == ("1. **Highlights**", 6, ("One.",))


def test_the_box_codes_bind_at_submission() -> None:
    assert {code: BINDS_AT[code] for code in CODES} == dict.fromkeys(CODES, SUBMISSION)


@pytest.mark.parametrize("block", ["boxes", "graphical_abstract", "sharing"])
def test_the_template_s_example_of_each_new_block_is_a_valid_profile(block: str) -> None:
    """The template shows each block commented out; uncommented, it has to be what the schema
    takes, or the author's first edit fails."""
    from manuscript_guard.paths import SHIPPED_JOURNALS

    lines = (SHIPPED_JOURNALS / "TEMPLATE.yaml").read_text(encoding="utf-8").split("\n")
    start = lines.index(f"# {block}:")
    shown = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        shown.append(line[2:])
    # A date as its text, as the profile's reader gives it.
    block_read = json.loads(json.dumps(yaml.safe_load("\n".join(shown)), default=str))
    document = {"schema": "manuscript-guard/journal/1", "name": "J", "source_url": "u",
                "retrieved_on": "2026-10-28", **block_read}  # fmt: skip
    report = validate(document, "journal", Path("TEMPLATE.yaml"))
    assert report.ok, report.render()


# ------------------------------------------------- a box's numbers, held to its quote


def _quoted(root: Path, **blocks) -> dict[str, str]:
    """The `journal-limit-not-in-quote` and `journal-quote-not-on-page` messages G4 gives with
    `blocks` set in the profile, the quotes among them added to its own."""
    profile = yaml.safe_load((root / PROFILE).read_text(encoding="utf-8"))
    quotes = {**profile["quotes"], **blocks.pop("quotes", {})}
    _asks(root, quotes=quotes, **blocks)
    report = check_journal(load_project(root)[0])
    codes = ("journal-limit-not-in-quote", "journal-quote-not-on-page", "journal-page-not-stored",
             "journal-page-changed")  # fmt: skip
    return sorted((f.code, f.message) for f in report.findings if f.code in codes)


def test_each_number_of_a_box_is_held_to_its_quote(project: Path) -> None:
    """A box's `item_max_chars` typed 58 for the page's 85 passed G4: only a limit's number was
    held to its quote."""
    quote = "Include 3 to 5 highlights, each of no more than 85 characters."
    page = project / "profiles" / "journals" / "sources" / "demo-journal.txt"
    page.write_text(page.read_text(encoding="utf-8") + "\n" + quote + "\n", encoding="utf-8")
    box = {**HIGHLIGHTS, "item_max_chars": 58}
    said = _quoted(project, boxes=[box], quotes={"boxes.highlights": quote})
    assert ("journal-limit-not-in-quote", "boxes.highlights item_max_chars is 58, and its "
            f"quote does not say 58: \"{quote}\"") in said  # fmt: skip
    assert not any("items_min" in m or "items_max" in m for _c, m in said)
    said = _quoted(project, boxes=[HIGHLIGHTS])
    assert not [m for c, m in said if c == "journal-limit-not-in-quote"]


def test_a_graphical_abstract_s_size_is_held_to_its_quote(project: Path) -> None:
    quote = "Images should be a minimum of 1328 x 531 pixels."
    blocks = {"graphical_abstract": {"required": True, "width_px": 1328, "height_px": 513},
              "quotes": {"graphical_abstract.width_px": quote,
                         "graphical_abstract.height_px": quote,
                         "graphical_abstract.required": "A graphical abstract is mandatory."}}
    said = [m for c, m in _quoted(project, **blocks) if c == "journal-limit-not-in-quote"]
    assert said == [f"graphical_abstract.height_px is 513, and its quote does not say 513: "
                    f"\"{quote}\""]  # fmt: skip


# ------------------------------------------------- a block's quotes, held to its own page

SHARING_QUOTE = "The accepted manuscript may be deposited after 12 months."
SHARING = {"page_file": "profiles/journals/sources/demo-journal-sharing.txt",
           "accepted": {"where": ["institutional-repository"], "embargo_months": 12}}


def _sharing_page(root: Path, text: str) -> Path:
    page = root / SHARING["page_file"]
    page.write_text(text, encoding="utf-8")
    return page


def test_a_block_s_quotes_are_held_to_the_page_it_names(project: Path) -> None:
    from manuscript_guard.gates.journal_quotes import page_digest

    text = f"Sharing policy.\n\n{SHARING_QUOTE}\n"
    _sharing_page(project, text)
    blocks = {"sharing": {**SHARING, "page_sha256": page_digest(text)},
              "quotes": {"sharing.accepted": SHARING_QUOTE}}
    assert _quoted(project, **blocks) == []


def test_a_block_s_quote_on_the_wrong_page_fails(project: Path) -> None:
    """The quote is on the instructions page, and the block names a page of its own: it is
    held to that one, where it is not."""
    page = project / "profiles" / "journals" / "sources" / "demo-journal.txt"
    page.write_text(page.read_text(encoding="utf-8") + SHARING_QUOTE + "\n", encoding="utf-8")
    _sharing_page(project, "Sharing policy.\n")
    said = _quoted(project, sharing=SHARING, quotes={"sharing.accepted": SHARING_QUOTE})
    assert ("journal-quote-not-on-page", f"the quote for sharing.accepted is not on the page of "
            f"sharing: \"{SHARING_QUOTE}\"") in said  # fmt: skip
    assert any(c == "journal-page-changed" and "demo-journal-sharing.txt" in m for c, m in said)


def test_a_block_s_own_page_not_stored_is_said(project: Path) -> None:
    said = _quoted(project, sharing=SHARING, quotes={"sharing.accepted": SHARING_QUOTE})
    assert ("journal-page-not-stored", "the journal's page is not stored at "
            "profiles/journals/sources/demo-journal-sharing.txt, so no quote of sharing can be "
            "held to it") in said  # fmt: skip
    # And no quote of the instructions page is taken for one gone from it.
    assert not [m for c, m in said if c == "journal-quote-not-on-page"]


def test_a_reread_reads_each_page_on_its_own(project: Path, capsys) -> None:
    """Read again, the instructions page is not held to the sharing policy's quote, and the
    policy's page, read again with `--page`, is held to it alone."""
    from manuscript_guard.cli import main

    _sharing_page(project, f"Sharing policy.\n\n{SHARING_QUOTE}\n")
    _asks(project, sharing=SHARING, quotes={
        **yaml.safe_load((project / PROFILE).read_text(encoding="utf-8"))["quotes"],
        "sharing.accepted": SHARING_QUOTE})  # fmt: skip
    instructions = project / "profiles" / "journals" / "sources" / "demo-journal.txt"
    again = project / "again.txt"
    again.write_text(instructions.read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["journal", str(project), "--reread", str(again)]) == 0
    assert "sharing.accepted" not in capsys.readouterr().out
    again.write_text("Sharing policy, revised.\n", encoding="utf-8")
    assert main(["journal", str(project), "--reread", str(again),
                 "--page", SHARING["page_file"]]) == 1  # fmt: skip
    out = capsys.readouterr().out
    assert "NOT on the page    sharing.accepted" in out
    assert "limits.abstract_words" not in out and "manual: cover letter" not in out
    assert "in the profile's sharing." in out
    assert main(["journal", str(project), "--reread", str(again), "--page", "nowhere.txt"]) == 2
