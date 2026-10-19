"""The submission pack, and the pre-analysis design gate.

Everything in a submission except the covering letter is already recorded somewhere in the
project, so the tests are mostly about it not being written twice: the title page, the
CRediT statement and the declarations must come from authors.yaml and change when it does.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from manuscript_guard.build import (
    SubmissionError,
    assemble_pack,
    credit_statement,
    declarations,
    title_page,
)
from manuscript_guard.contracts import load_project
from manuscript_guard.gates import check_design
from manuscript_guard.gates.design import plan_path

AUTHORS = Path("authors.yaml")
PLAN = Path("design") / "plan.md"


def edit_yaml(path: Path, mutate) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


# ---------------------------------------------------------------- title page


def test_the_title_page_carries_what_the_manuscript_leaves_out(project: Path) -> None:
    page = title_page(load_project(project)[0])
    assert "Ada Example, PharmD, MSc" in page
    assert "Example University" in page
    assert "0000-0002-1825-0097" in page
    assert "ada.example@invalid.example" in page
    assert "Word count" in page


def test_the_title_page_declares_the_words_the_build_prints(project: Path) -> None:
    """The count the editor reads included the manuscript's front matter, which the build
    strips: the example's title page declared 573 words of main text for 557 printed."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text.sections import measure

    printed, _title = strip_front_matter(
        (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    )
    page = title_page(load_project(project)[0])
    assert f"main text {measure(printed).main_text_words}." in page


def test_affiliation_superscripts_follow_the_declared_order(project: Path) -> None:
    page = title_page(load_project(project)[0])
    assert "Ada Example, PharmD, MSc^1^" in page
    assert "Blaise Sample, MD, PhD^2^" in page


def test_an_equal_contribution_group_is_marked_and_footnoted(project: Path) -> None:
    def mutate(document):
        for author in document["authors"]:
            author["equal_contribution"] = True

    edit_yaml(project / AUTHORS, mutate)
    page = title_page(load_project(project)[0])
    assert page.count("\\*") >= 3, "a mark on each author and the footnote"
    assert "contributed equally" in page


def test_the_title_page_changes_when_the_authors_do(project: Path) -> None:
    """The point of generating it is that it cannot list someone who left the paper."""
    before = title_page(load_project(project)[0])
    edit_yaml(project / AUTHORS, lambda d: d["authors"].pop())
    after = title_page(load_project(project)[0])
    assert "Blaise Sample" in before
    assert "Blaise Sample" not in after


# ---------------------------------------------------------------- CRediT and declarations


def test_credit_is_grouped_by_role_as_journals_print_it(project: Path) -> None:
    statement = credit_statement(load_project(project)[0])
    assert "**Conceptualization:** A.E." in statement
    assert "**Supervision:** B.S." in statement


def test_credit_roles_keep_the_taxonomy_order(project: Path) -> None:
    statement = credit_statement(load_project(project)[0])
    assert statement.index("Conceptualization") < statement.index("Formal analysis")
    assert statement.index("Methodology") < statement.index("Writing – original draft")


def test_missing_credit_roles_are_said_out_loud(project: Path) -> None:
    def mutate(document):
        for author in document["authors"]:
            author.pop("credit", None)

    edit_yaml(project / AUTHORS, mutate)
    assert "No CRediT roles are recorded" in credit_statement(load_project(project)[0])


def test_an_empty_competing_interest_is_not_a_declaration_of_none(project: Path) -> None:
    """The distinction journals care about, and the one an empty field destroys."""

    def mutate(document):
        document["authors"][0]["competing_interests"] = ""

    edit_yaml(project / AUTHORS, mutate)
    text = declarations(load_project(project)[0])
    assert "No declaration is recorded for: Ada Example" in text
    assert "not a declaration of none" in text


def test_funding_is_listed_per_author(project: Path) -> None:
    edit_yaml(project / AUTHORS, lambda d: d["authors"][0].update(funding=["Grant ABC/123"]))
    assert "A.E.: Grant ABC/123" in declarations(load_project(project)[0])


def test_a_project_without_authors_cannot_make_a_title_page(tmp_path: Path) -> None:
    root = tmp_path / "bare"
    (root / "manuscript").mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    with pytest.raises(SubmissionError, match="authors.yaml is required"):
        title_page(load_project(root)[0])


# ---------------------------------------------------------------- the pack


def test_the_pack_gathers_every_part(project: Path) -> None:
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(projekt, document)
    names = {p.name for p in pack.files}
    assert {"manuscript.docx", "title-page.md", "credit-statement.md", "declarations.md"} <= names
    assert any(n.startswith("checklist-") for n in names)
    assert any(p.suffix == ".png" for p in pack.files)


def test_the_manifest_records_what_was_sent(project: Path) -> None:
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(projekt, document)
    manifest = yaml.safe_load(pack.manifest.read_text(encoding="utf-8"))
    assert manifest["journal"] == "demo-journal"
    assert len(manifest["files"]) == len(pack.files)
    assert all(len(entry["sha256"]) == 64 for entry in manifest["files"])
    assert len(manifest["manuscript_sha256"]) == 64


def _pack_manifest(root: Path) -> dict:
    projekt, _ = load_project(root)
    document = root / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")
    return yaml.safe_load(assemble_pack(projekt, document).manifest.read_text(encoding="utf-8"))


def test_the_manifest_says_what_made_it(project: Path) -> None:
    """The version that passed it, the dates of the guidelines it was held to, and the
    review findings a person left as they were, with why and who decided."""
    from manuscript_guard import __version__

    manifest = _pack_manifest(project)
    assert manifest["checked_with"] == f"manuscript-guard {__version__}"
    profile = yaml.safe_load(
        (project / "profiles" / "journals" / "demo-journal.yaml").read_text(encoding="utf-8")
    )
    assert manifest["journal_profile_retrieved_on"] == str(profile["retrieved_on"])
    assert [c["guideline"] for c in manifest["checklists"]] == ["DEMO-OBS"]
    dates = [c["retrieved_on"] for c in manifest["checklists"]]
    assert not {"no profile", "not stated"} & set(dates), dates
    overrides = manifest["overrides"]
    assert {(o["round"], o["finding"]) for o in overrides} == {
        (1, "r1-pe-03"), (1, "r1-bs-02"), (2, "r2-de-01")
    }  # fmt: skip
    assert all(o["reason"] and o["decided_by"] == "not recorded" for o in overrides)


def test_the_manifest_names_who_left_a_finding_as_it_was(project: Path) -> None:
    record = project / "review" / "round-2" / "desk-editor.yaml"
    edit_yaml(record, lambda d: d["findings"][0].update(overridden_by="Anne Fictional"))
    overrides = {o["finding"]: o for o in _pack_manifest(project)["overrides"]}
    assert overrides["r2-de-01"]["decided_by"] == "Anne Fictional"


def test_a_record_that_cannot_be_read_is_listed_and_the_pack_is_assembled(
    project: Path,
) -> None:
    """G11 reports the record; a pack assembled with --skip-checks despite it is assembled,
    as it was before the manifest listed the overrides (round 1 of #250)."""
    record = project / "review" / "round-1" / "biostatistician.yaml"
    record.write_text(
        record.read_text(encoding="utf-8") + "resolution: Fixed: it now says reporting\n",
        encoding="utf-8",
    )
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")
    pack = assemble_pack(projekt, document, checked=False)
    manifest = yaml.safe_load(pack.manifest.read_text(encoding="utf-8"))
    assert {"round": 1, "reviewer": "biostatistician", "unreadable": "a record"} in (
        manifest["overrides"]
    )


def test_git_s_output_is_read_as_utf_8_whatever_the_locale(monkeypatch) -> None:
    import subprocess

    from manuscript_guard.build import submission

    asked = {}

    def run(*args, **kwargs):
        asked.update(kwargs)
        return subprocess.CompletedProcess(args, 0, stdout="0" * 40 + "\n", stderr="")

    monkeypatch.setattr(submission.subprocess, "run", run)
    assert submission._git(Path("."), "rev-parse", "HEAD") == "0" * 40 + "\n"
    assert (asked["encoding"], asked["errors"]) == ("utf-8", "replace")


def test_a_pack_outside_git_says_so(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Round 1 of #250: the assertion stood inside an `if` and said nothing where the test
    folder happened to be in a repository. Git is pointed at no repository here."""
    monkeypatch.setenv("GIT_DIR", str(project / "no-repository"))
    manifest = _pack_manifest(project)
    assert manifest["commit"].startswith("none") and manifest["tree"] == "unknown", manifest


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_manifest_records_the_commit_and_whether_the_tree_differs(project: Path) -> None:
    import subprocess

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "user.name=T", "-c",
             "user.email=t@example.org", "-c", "commit.gpgsign=false", "-C", str(project),
             *args],
            capture_output=True, text=True, check=True, timeout=60,
        ).stdout.strip()  # fmt: skip

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "a paper")
    head = git("rev-parse", "HEAD")
    manifest = _pack_manifest(project)
    assert (manifest["commit"], manifest["tree"]) == (head, "clean")
    main = project / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8") + "\nOne more line.\n", encoding="utf-8")
    manifest = _pack_manifest(project)
    assert (manifest["commit"], manifest["tree"]) == (head, "1 file(s) changed or not committed")
    # Round 1 of #250: a folder git has not been given counted as one file.
    notes = project / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("a\n", encoding="utf-8")
    (notes / "b.md").write_text("b\n", encoding="utf-8")
    manifest = _pack_manifest(project)
    assert (manifest["commit"], manifest["tree"]) == (head, "3 file(s) changed or not committed")


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_the_pack_holds_the_abstract_as_plain_text_with_its_numbers(project: Path) -> None:
    """For the portal's abstract box: every binding filled in with the value the build
    prints, and no Markdown."""
    from manuscript_guard.contracts import load_namespace

    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")
    pack = assemble_pack(projekt, document)
    text = (pack.directory / "abstract.txt").read_text(encoding="utf-8")
    point = load_namespace(projekt)[0]["results.ror.point"].display
    assert text.startswith("Background. Drug-induced hepatic injury")
    assert f"The reporting odds ratio was {point}" in text
    assert "{{" not in text and "**" not in text and "# " not in text
    manifest = yaml.safe_load(pack.manifest.read_text(encoding="utf-8"))
    assert "abstract.txt" in [entry["file"] for entry in manifest["files"]]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_structured_abstract_keeps_its_headings_as_lines(project: Path) -> None:
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("**Background.** Drug-induced", "## Background\n\nDrug-induced", 1),
        encoding="utf-8",
    )
    plain, _why = abstract_text(load_project(project)[0])
    assert plain.startswith("Background\n\nDrug-induced hepatic injury"), plain


def test_a_paper_with_no_abstract_section_gets_no_abstract_file(project: Path) -> None:
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace("# Abstract\n", "# Overview\n", 1),
        encoding="utf-8",
    )
    assert abstract_text(load_project(project)[0]) == (None, None)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "added",
    ["as reported [@fictionalHepaticCohort2021].", "as @fictionalHepaticCohort2021 found.",
     "as noted.[^a]\n\n[^a]: A note.", "as {{table.baseline}} shows.",
     # round 2 of #259: a braced key, an inline note, an image
     "as reported [@{10.1000/xyz}].", "as noted.^[A note.]", "\n\n![Flow](figures/flow.png)",
     # round 3: a link with words of its own, a block that is no paragraph
     "as [the trial](https://example.org) says.", "\n\n::: {.keywords}\nKeywords: x\n:::",
     # round 4: words struck out
     "as ~~not~~ shown.",
     # round 5: a power or a unit, which written flat is another number
     "At 10^0.5^ times.", "As x^*2*^.",
     # round 6: a superscript of letters is a power, not a label
     "A 2^k^ factorial design.", "As e^x^ grows."],
)  # fmt: skip
def test_an_abstract_the_build_formats_and_plain_text_cannot_is_left_out(
    project: Path, added: str
) -> None:
    """Round 1 of #259: a citation came out as the bare key, or in another style than the
    document's, and a footnote as its marker. Left out, and said."""
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "cannot establish risk.", f"cannot establish risk, {added}", 1
        ),
        encoding="utf-8",
    )
    plain, why = abstract_text(load_project(project)[0])
    assert plain is None and "abstract.txt is not written" in why


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_sub_or_superscript_is_written_as_the_plain_writer_can(project: Path) -> None:
    """Round 4 of #259: `C~max~` came out as `C_(max)`. Digits keep their Unicode form;
    letters are written as they are."""
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "cannot establish risk.",
            "cannot establish risk. C~max~ in the 2^nd^ H~2~O at 10^\N{MINUS SIGN}3^ mg.",
            1,
        ),
        encoding="utf-8",
    )
    plain, why = abstract_text(load_project(project)[0])
    assert why is None and (
        "Cmax in the 2nd H\N{SUBSCRIPT TWO}O at "
        "10\N{SUPERSCRIPT MINUS}\N{SUPERSCRIPT THREE} mg." in plain
    ), plain


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_footnote_defined_at_the_end_of_the_text_is_still_a_footnote(project: Path) -> None:
    """Round 3 of #259: read alone, the abstract's `[^a]` had no definition, was no
    footnote to pandoc, and was written as the literal marker."""
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8").replace("cannot establish risk.", "risk.[^a]", 1)
    main.write_text(text + "\n\n[^a]: A note.\n", encoding="utf-8")
    plain, why = abstract_text(load_project(project)[0])
    assert plain is None and "footnote" in why


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("joined", ["\N{REVERSE SOLIDUS}\nKeywords: x", "  \nKeywords: x"])
def test_a_keywords_label_inside_a_paragraph_leaves_the_abstract_out(
    project: Path, joined: str
) -> None:
    """Round 3 of #259: a label after a hard break is in the paragraph above it, so no
    block opens with it; the abstract is left out rather than written with it."""
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace("establish risk.", f"establish risk.{joined}", 1),
        encoding="utf-8",
    )
    plain, why = abstract_text(load_project(project)[0])
    assert plain is None and "keywords label" in why


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "keywords",
    ["## Keywords\n\nhepatotoxicity", "**Keywords:** hepatotoxicity",
     "*Keywords*: hepatotoxicity", "Key words: hepatotoxicity",
     "**Keywords: hepatotoxicity**"],
)  # fmt: skip
def test_the_abstract_s_keywords_are_not_its_text(project: Path, keywords: str) -> None:
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "cannot establish risk.\n", f"cannot establish risk.\n\n{keywords}\n", 1
        ),
        encoding="utf-8",
    )
    plain, _why = abstract_text(load_project(project)[0])
    assert "hepatotoxicity" not in plain and plain.rstrip().endswith("cannot establish risk.")


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "added",
    [
        # round 2 of #259: the word in a sentence, not the label that opens the keywords
        "We searched using\nkeywords for liver injury; 412 reports.",
        "\n\nKey words in titles were screened in 412 reports.",
        # an @ that is no citation
        "Write to jane@example.org about the 412 reports.",
        "<!-- ask @smith --> The 412 reports.",
        # round 3: an emphasised word that opens a sentence, a binding inside a comment
        "\n\n*Key words* in titles were screened in 412 reports.",
        "<!-- move {{table.baseline}} here? --> The 412 reports.",
    ],
)
def test_an_abstract_that_only_mentions_keywords_or_an_at_sign_is_written_whole(
    project: Path, added: str
) -> None:
    from manuscript_guard.build.submission import abstract_text

    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "cannot establish risk.", f"cannot establish risk. {added}", 1
        ),
        encoding="utf-8",
    )
    plain, why = abstract_text(load_project(project)[0])
    assert why is None and "412" in plain, (plain, why)


def test_the_pack_offers_a_checklist_a_journal_can_read(project: Path) -> None:
    """What the pack sent in answer to "attach your completed STROBE checklist" was YAML.

    An editor wants the items and where each is addressed. The YAML stays — it is the record,
    and it diffs — but a table goes beside it, generated so it cannot drift from the file the
    gate checks.
    """
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 placeholder")

    pack = assemble_pack(projekt, document)
    table = next(p for p in pack.files if p.name == "checklist-DEMO-OBS.md")
    text = table.read_text(encoding="utf-8")
    assert "| Item | Recommendation | Addressed in | Not applicable because |" in text
    assert "| Abstract |" in text, text
    assert any(p.name == "checklist-DEMO-OBS.yaml" for p in pack.files), "the record is still sent"


def test_an_unanswered_checklist_item_still_appears_in_the_table(project: Path) -> None:
    """The item text comes from the published guideline, not from the completion — so an item
    nobody answered shows with the answer blank rather than vanishing from what a journal
    receives, which is the difference between an incomplete checklist and a shorter one."""
    from manuscript_guard.build.submission import checklist_table

    completion = project / "reporting" / "DEMO-OBS.yaml"
    document = yaml.safe_load(completion.read_text(encoding="utf-8"))
    dropped = document["items"].pop()["id"]
    completion.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    projekt, _ = load_project(project)
    rows = checklist_table(projekt, completion).splitlines()
    assert any(row.startswith(f"| {dropped} |") for row in rows), rows[-4:]


def test_a_scale_is_not_sent_as_a_completed_reporting_checklist(project: Path) -> None:
    """An appraisal scale and a reporting checklist are different claims, and what a journal
    reads is the file name and the heading. Presented as a checklist, SANRA arrived headed
    "SANRA checklist" with its scoring anchors in a column called "Recommendation"."""
    from manuscript_guard.build.submission import assemble_pack, checklist_table

    profile = project / "profiles" / "reporting" / "DEMO-OBS.yaml"
    published = yaml.safe_load(profile.read_text(encoding="utf-8"))
    published["kind"] = "scale"
    published["long_name"] = "Demonstration Observational Appraisal Scale"
    published["applies_to"] = "Demonstrations; an appraisal scale, not a reporting guideline"
    first = published["items"][0]
    first["clarification"] = "(e.g., a clarifying line, as a scale prints one)"
    first["options"] = [
        {"score": "0", "statement": "Not done."},
        {"score": "2", "statement": "Done."},
    ]
    profile.write_text(yaml.safe_dump(published, sort_keys=False), encoding="utf-8")

    projekt, _ = load_project(project)
    completion = project / "reporting" / "DEMO-OBS.yaml"
    text = checklist_table(projekt, completion)

    assert text.startswith("# DEMO-OBS, completed appraisal scale")
    assert "| Item | Scoring options | Addressed in | Not applicable because |" in text
    assert "Recommendation" not in text
    assert "not a reporting guideline" in text
    assert "the scoring is the reader's to do" in text
    # The options as the form prints them: statement first, score after.
    assert "Not done. (0); Done. (2)" in text
    assert "(e.g., a clarifying line, as a scale prints one)" in text

    # The fixture copies the example without a build, so a pack test writes the document it
    # packs, as the others here do. Guarded on its existence instead, this block ran never and
    # the file names were held by nothing.
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04 a placeholder document, as the other pack tests use")
    pack = assemble_pack(projekt, document)
    names = [p.name for p in pack.files]
    assert "scale-DEMO-OBS.md" in names, names
    assert "scale-DEMO-OBS.yaml" in names, names
    assert not any(name.startswith("checklist-DEMO-OBS") for name in names), names

    # An answer to an item the published instrument does not have is labelled for what the
    # instrument is: inside a scale's table, "not in the published checklist" named the wrong
    # thing, and nothing held either label.
    answers = yaml.safe_load((project / "reporting" / "DEMO-OBS.yaml").read_text(encoding="utf-8"))
    answers["items"].append({"id": "not-an-item", "where": "Methods"})
    (project / "reporting" / "DEMO-OBS.yaml").write_text(
        yaml.safe_dump(answers, sort_keys=False), encoding="utf-8"
    )
    assert "*not in the published scale*" in checklist_table(projekt, completion)


def test_a_pipe_in_an_item_does_not_break_the_table(project: Path) -> None:
    """A pipe inside a cell ends the cell, and reporting checklists contain "and/or" lists."""
    from manuscript_guard.build.submission import checklist_table

    completion = project / "reporting" / "DEMO-OBS.yaml"
    document = yaml.safe_load(completion.read_text(encoding="utf-8"))
    document["items"][0]["where"] = "Methods | Statistical analysis"
    completion.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    projekt, _ = load_project(project)
    row = next(
        line
        for line in checklist_table(projekt, completion).splitlines()
        if "Statistical analysis" in line
    )
    assert "\\|" in row
    assert len(re.findall(r"(?<!\\)\|", row)) == 5, row


def test_reassembling_clears_the_previous_pack(project: Path) -> None:
    """A stale file left in the directory is a file that gets sent by mistake."""
    projekt, _ = load_project(project)
    document = project / "build" / "manuscript.docx"
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_bytes(b"PK\x03\x04")

    pack = assemble_pack(projekt, document)
    stray = pack.directory / "old-version.docx"
    stray.write_bytes(b"PK\x03\x04 stale")
    assemble_pack(projekt, document)
    assert not stray.exists()


# ---------------------------------------------------------------- the design gate


def test_a_complete_plan_is_recognised(project: Path) -> None:
    report = check_design(load_project(project)[0])
    assert report.ok
    assert report.counts["design_sections"] == report.counts["design_expected"]
    assert "plan-complete" in codes(report)


def test_analysis_without_a_plan_warns_but_never_blocks(project: Path) -> None:
    """Warning by decision: blocking exploratory work is a gate that gets bypassed."""
    shutil.rmtree(project / "design")
    report = check_design(load_project(project)[0])
    assert "no-analysis-plan" in codes(report)
    assert report.ok, "the design gate never fails a build"


def test_a_missing_section_is_named(project: Path) -> None:
    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8").replace("## Deviations from the plan", "## Notes")
    path.write_text(text, encoding="utf-8")
    report = check_design(load_project(project)[0])
    assert "plan-section-missing" in codes(report)
    assert any("deviations" in f.message for f in report.findings)


@pytest.mark.parametrize("filler", ["", "TBD", "n/a", "   ", "TODO"])
def test_a_heading_with_nothing_under_it_is_not_a_section(project: Path, filler: str) -> None:
    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8")
    head = text.index("## Deviations from the plan")
    path.write_text(text[:head] + f"## Deviations from the plan\n\n{filler}\n", encoding="utf-8")
    report = check_design(load_project(project)[0])
    assert "plan-section-empty" in codes(report)


def test_a_project_with_no_analysis_and_no_plan_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    (root / "manuscript").mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "T"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    report = check_design(load_project(root)[0])
    assert report.ok
    assert not report.findings


def _replace_section(project: Path, heading: str, replacement: str) -> Path:
    """Swap one `## heading` section of the example plan, body and all, for `replacement`."""
    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8")
    start = text.index(f"## {heading}\n")
    end = text.index("\n## ", start + 1) + 1
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    return path


def test_a_section_whose_content_is_in_subsections_is_not_empty(project: Path) -> None:
    """A section's body stopped at the next heading of any level, so a Population written
    entirely under `### Inclusion` and `### Exclusion` was "a heading with nothing under it"."""
    _replace_section(
        project,
        "Population and data source",
        "## Population and data source\n\n### Inclusion\n\nEvery report in the database.\n\n"
        "### Exclusion\n\nNone.\n\n",
    )
    report = check_design(load_project(project)[0])
    assert "plan-section-empty" not in codes(report)
    assert "plan-complete" in codes(report)


def test_a_subsection_titled_only_by_its_attribute_block_still_counts(project: Path) -> None:
    """Once a title lost its attribute block, `### {#inclusion}` had the empty title the
    plan's preamble has, and was dropped with it: the Population written under it was "a
    heading with nothing under it"."""
    _replace_section(
        project,
        "Population and data source",
        "## Population and data source\n\n### {#inclusion}\n\nAdults aged 18 or over.\n\n",
    )
    report = check_design(load_project(project)[0])
    assert "plan-section-empty" not in codes(report), [f.message for f in report.findings]


def test_a_section_with_only_empty_subsections_is_still_empty(project: Path) -> None:
    _replace_section(
        project,
        "Population and data source",
        "## Population and data source\n\n### Inclusion\n\nTBD\n\n### Exclusion\n\n",
    )
    report = check_design(load_project(project)[0])
    assert any(
        f.code == "plan-section-empty" and "population" in f.message for f in report.findings
    )


def test_the_plans_own_title_does_not_answer_for_its_analysis(project: Path) -> None:
    """`# Analysis plan` matched the "analysis" requirement, so an empty `## Analysis` —
    exactly what `init` scaffolds — was never reported."""
    _replace_section(project, "Analysis", "## Analysis\n\n")
    report = check_design(load_project(project)[0])
    assert any(
        f.code == "plan-section-empty" and "analysis section" in f.message
        for f in report.findings
    ), [f.message for f in report.findings]


def test_the_plans_own_title_does_not_stand_in_for_a_missing_analysis(project: Path) -> None:
    _replace_section(project, "Analysis", "")
    report = check_design(load_project(project)[0])
    assert any(
        f.code == "plan-section-missing" and f.message.endswith("about analysis")
        for f in report.findings
    ), [f.message for f in report.findings]


def test_a_plan_that_is_only_its_title_has_no_analysis(project: Path) -> None:
    """With nothing under it but prose, `# Analysis plan` still answered for "analysis"."""
    path = plan_path(load_project(project)[0])
    path.write_text("# Analysis plan\n\nWe will fit a model, and decide the rest later.\n", "utf-8")
    report = check_design(load_project(project)[0])
    missing = {f.message for f in report.findings if f.code == "plan-section-missing"}
    assert "the plan says nothing about analysis" in missing
    assert len(missing) == 7


def test_a_freshly_scaffolded_plan_reports_its_analysis_as_empty(tmp_path: Path) -> None:
    from manuscript_guard.scaffold import init_project

    root = tmp_path / "fresh"
    init_project(root, title="T")
    report = check_design(load_project(root)[0])
    empty = {f.message for f in report.findings if f.code == "plan-section-empty"}
    assert "the plan's analysis section is a heading with nothing under it" in empty


def test_a_plan_that_is_not_utf8_warns_and_is_still_read(project: Path) -> None:
    """Saved from an editor in Windows-1252, the plan crashed G12 — and a crashed gate is
    `gate-errored`, a failure at every stage, from a gate that is meant never to block."""
    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8").replace("Agreed", "Agrééd")
    path.write_bytes(text.encode("cp1252", errors="replace"))
    report = check_design(load_project(project)[0])
    assert report.ok
    assert "plan-not-utf8" in codes(report)
    assert report.counts["design_sections"] == report.counts["design_expected"]


def test_a_plan_with_a_byte_order_mark_is_read(project: Path) -> None:
    """Notepad's UTF-8 puts U+FEFF before the first `#`, which then starts no heading."""
    path = plan_path(load_project(project)[0])
    path.write_text("﻿" + path.read_text(encoding="utf-8"), encoding="utf-8")
    report = check_design(load_project(project)[0])
    assert "plan-complete" in codes(report)
    assert "plan-not-utf8" not in codes(report)


def test_a_plan_that_is_not_utf8_does_not_fail_check(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    path = plan_path(load_project(project)[0])
    text = path.read_text(encoding="utf-8").replace("Agreed", "Agréed")
    path.write_bytes(text.encode("cp1252"))
    report, _project, _stage, _deferred = _run_gates(project, stage="design")
    assert "gate-errored" not in {f.code for f in report.findings}


def test_a_crlf_plan_with_underlined_headings_is_read(project: Path) -> None:
    """Decoding the bytes by hand kept the carriage returns, and a setext underline followed
    by one is not an underline: every section was reported missing."""
    path = plan_path(load_project(project)[0])
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            title = line[3:]
            lines += [title, "-" * len(title)]
        elif line.startswith("# "):
            lines += [line[2:], "=" * len(line[2:])]
        else:
            lines.append(line)
    path.write_bytes("\r\n".join(lines).encode("utf-8"))
    report = check_design(load_project(project)[0])
    assert "plan-complete" in codes(report), [f.message for f in report.findings]
