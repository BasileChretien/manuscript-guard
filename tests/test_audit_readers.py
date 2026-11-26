"""`audit` for a reader who did not write the paper: an editor's `--journal`, the Document
section of a .docx, and `--authors` where the journal reviews blind (docs/refereeing.md).

The rules G4 holds a paper to are `check`'s own, and are tested there; these hold what the
audit adds: a profile read and refused as it should be, G4 run on a paper in no project and
saying what it did not check, the names Word keeps, and an author named in a document the
journal reviews blind counted by `--strict`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import zipfile
from datetime import date
from pathlib import Path

import pytest

from manuscript_guard.auditing import NOTICE
from manuscript_guard.cli import main
from manuscript_guard.gates.journal import FROM_RECORDS

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                     reason="pdftotext is not installed")  # fmt: skip
BS = chr(92)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def profile(tmp_path: Path, *, blinding: str | None = "single", more: str = "",
            limits: str = "main_text_words: 40") -> Path:  # fmt: skip
    """A journal profile an editor keeps: a 40-word main text, the four sections, a Funding
    statement under its own heading, British English, one rule no gate checks."""
    path = tmp_path / "journal.yaml"
    path.write_text(
        "schema: manuscript-guard/journal/1\n"
        "name: The Journal of Examples\n"
        "source_url: https://example.org/authors\n"
        f"retrieved_on: {date.today().isoformat()}\n"
        "english_variant: en-GB\n"
        + (f"blinding: {blinding}\n" if blinding else "")
        + f"limits:\n  {limits}\n"
        "structure:\n  required_sections: [Introduction, Methods, Results, Discussion]\n"
        "required_statements:\n"
        "  - id: funding\n"
        f"    pattern: '(?im)^#+{BS}s*funding'\n"
        "    why: a funding statement under its own heading\n"
        "manual:\n"
        "  - rule: The cover letter suggests a handling editor.\n"
        "    quote: Your cover letter should suggest a handling editor.\n" + more,
        encoding="utf-8",
    )
    return path


PAPER = (
    "# Introduction\n\nThe colour of the urine was recorded in every patient who came to the "
    "clinic during the study.\n\n"
    "# Methods\n\nWe counted the patients seen in each month of the year and the share of "
    "them whose urine was dark.\n\n"
    "# Results\n\nOf 40 patients, 12 (30%) had dark urine at the first visit.\n\n"
    "# Discussion\n\nDark urine was common among the patients seen at this clinic.\n"
)


def paper_md(tmp_path: Path, text: str = PAPER) -> Path:
    path = tmp_path / "paper.md"
    path.write_text(text, encoding="utf-8")
    return path


def audited(capsys, *argv: str) -> tuple[int, dict, str]:
    code = main(["audit", *argv, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def section(report: dict, name: str) -> list[dict]:
    return [f for f in report["findings"] if f["section"] == name]


# ------------------------------------------------------------------------- --journal


def test_a_paper_over_the_limit_and_without_a_statement_is_said_and_not_counted(
    tmp_path: Path, capsys
) -> None:
    code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                 str(profile(tmp_path)), "--strict")  # fmt: skip
    journal = section(report, "Journal (G4)")
    codes = {f["code"] for f in journal}
    assert {"over-journal-limit", "missing-required-statement"} <= codes, journal
    assert not any(f["counted"] for f in journal)
    assert code == 0 and report["ok"], "G4's limits and statements are not counted (decision 8)"
    over = next(f for f in journal if f["code"] == "over-journal-limit")
    assert over["message"].startswith("main text: ") and over["message"].endswith("limit 40")
    assert Path(over["path"]).name == "journal.yaml"


def test_a_paper_within_the_profile_has_no_g4_finding(tmp_path: Path, capsys) -> None:
    text = PAPER + "\n# Funding\n\nNone.\n"
    roomy = profile(tmp_path).read_text(encoding="utf-8").replace("main_text_words: 40",
                                                                  "main_text_words: 4000")
    (tmp_path / "roomy.yaml").write_text(roomy, encoding="utf-8")
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, text)), "--journal",
                                  str(tmp_path / "roomy.yaml"))  # fmt: skip
    journal = section(report, "Journal (G4)")
    assert {f["code"] for f in journal} <= {"journal-not-checked", "journal-manual-rule"}, journal


def test_a_declaration_set_in_bold_reads_as_missing_with_the_template_s_pattern(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): G4
    finds a statement by the profile's pattern, and the template's, anchored on a heading,
    reads a declaration set as a bold paragraph as missing; a pattern for the phrase finds
    it."""
    import yaml

    import manuscript_guard

    template = Path(manuscript_guard.__file__).parent / "profiles" / "journals" / "TEMPLATE.yaml"
    statements = yaml.safe_load(template.read_text(encoding="utf-8"))["required_statements"]
    [anchored] = [s["pattern"] for s in statements if s["id"] == "funding"]
    written = profile(tmp_path).read_text(encoding="utf-8")
    ours = f"'(?im)^#+{BS}s*funding'"
    for name, pattern, held in (("template.yaml", anchored, True),
                                ("phrase.yaml", "(?i)funding", False)):  # fmt: skip
        (tmp_path / name).write_text(written.replace(ours, f"'{pattern}'"), encoding="utf-8")
        for tail, missing in (("\n# Funding\n\nNone.\n", False),
                              ("\n**Funding.** None.\n", held),
                              ("\n**Funding**\n\nNone.\n", held)):  # fmt: skip
            _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + tail)),
                                          "--journal", str(tmp_path / name))  # fmt: skip
            said = [f["message"] for f in report["findings"]
                    if f["code"] == "missing-required-statement"]  # fmt: skip
            assert said == (["the journal requires a funding statement"] if missing else []), (
                name, tail)


def test_what_g4_does_not_check_here_is_said_and_the_manual_rules_are_listed(
    tmp_path: Path, capsys
) -> None:
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                  str(profile(tmp_path)))  # fmt: skip
    journal = section(report, "Journal (G4)")
    skipped = [f for f in journal if f["code"] == "journal-not-checked"]
    assert len(skipped) == len(FROM_RECORDS) + 1, skipped
    assert all(f["severity"] == "info" and not f["counted"] for f in skipped)
    assert any("stored page" in f["message"] for f in skipped)
    assert any("graphical abstract" in f["message"] for f in skipped)
    rule = [f for f in journal if f["code"] == "journal-manual-rule"]
    assert [(f["message"], f["context"]) for f in rule] == [
        ("to check by hand: The cover letter suggests a handling editor.",
         "Your cover letter should suggest a handling editor.")]  # fmt: skip
    main(["audit", str(paper_md(tmp_path)), "--journal", str(profile(tmp_path))])
    text = capsys.readouterr().out
    assert "=== Journal (G4) (not counted by --strict) ===" in text
    assert "[ ] The cover letter suggests a handling editor." in text
    assert "  Not checked here:\n" in text


def test_a_journal_audit_runs_no_ai_use_check_and_says_so(tmp_path: Path, capsys) -> None:
    """A known gap (DESIGN.md, Known gaps, "The AI-use statement is held to names, and to
    the records that say a model made them"): a paper in no project has no records, so
    `audit --journal` does not run the AI-use check, even on a statement naming no model
    where the profile asks for one, and says so among what G4 did not check."""
    more = ("  - id: ai-use\n    kind: ai_use\n    pattern: '(?im)^#+" + BS + "s*use of ai'\n"
            "    why: Name each tool.\n")  # fmt: skip
    path = profile(tmp_path)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("manual:\n", more + "manual:\n", 1), encoding="utf-8")
    paper = PAPER + "\n# Use of AI\n\nA model read the draft.\n"
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, paper)), "--journal",
                                  str(path))  # fmt: skip
    journal = section(report, "Journal (G4)")
    assert not [f for f in journal if f["code"].startswith("ai-use")], journal
    skipped = [f["message"] for f in journal if f["code"] == "journal-not-checked"]
    said = "the AI-use statement held to the records of a model's work"
    assert len([m for m in skipped if said in m]) == 1, skipped


def test_the_profiles_english_is_the_one_g14_holds_the_paper_to(tmp_path: Path, capsys) -> None:
    american = PAPER.replace("colour", "color")
    spelt = {"spelling-variant", "spelling-not-as-declared"}
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, american)))
    assert not [f for f in report["findings"] if f["code"] in spelt]
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, american)), "--journal",
                                  str(profile(tmp_path)))  # fmt: skip
    assert [f for f in report["findings"] if f["code"] in spelt], report["findings"]
    # --english is the reader's word, and wins over the profile's.
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, american)), "--journal",
                                  str(profile(tmp_path)), "--english", "american")  # fmt: skip
    assert not [f for f in report["findings"] if f["code"] in spelt]


@pytest.mark.parametrize("english", [(), ("--english", "american")], ids=["none", "other"])
def test_a_journal_audit_names_no_paper_yaml(
    tmp_path: Path, capsys, english: tuple[str, ...]
) -> None:
    """The profile asks for British English, and the reader chose none or the other. No
    finding of the audit, G4's under `--journal` among them, tells the reader to set
    something in paper.yaml, which a paper audited alone has none of (review of #615). G4's
    English check reads paper.yaml and is not run in an audit (`FROM_RECORDS`)."""
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                  str(profile(tmp_path)), *english)  # fmt: skip
    assert [f for f in report["findings"] if f["gate"] == "G4"], report["findings"]
    said = [f"{f['message']} {f.get('hint') or ''}" for f in report["findings"]]
    assert not [text for text in said if "paper.yaml" in text], said


def test_a_dataset_the_reference_list_cites_is_not_said_to_be_uncited(
    tmp_path: Path, capsys
) -> None:
    """The data statement's DOI is held to the paper's own reference list, which the audit
    reads, and not to a references.bib a paper in no project does not have."""
    more = ("data_availability:\n  source: https://example.org/data\n"
            f"  retrieved_on: {date.today().isoformat()}\n  identifier_required: true\n")
    statement = ("\n# Data availability\n\nThe data are at https://doi.org/10.5281/zenodo.1234567"
                 ".\n")  # fmt: skip
    listed = ("\n# References\n\n1. Doe J. The data. Zenodo. 2024. "
              "doi:10.5281/zenodo.1234567\n")  # fmt: skip
    other = "\n# References\n\n1. Roe K. A trial. BMJ 2020;370:m1. doi:10.5555/fictional.1\n"
    journal = profile(tmp_path, more=more)
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + statement + other)),
                                  "--journal", str(journal))  # fmt: skip
    assert "data-doi-uncited" in {f["code"] for f in report["findings"]}
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + statement + listed)),
                                  "--journal", str(journal))  # fmt: skip
    codes = {f["code"] for f in report["findings"]}
    assert "data-doi-uncited" not in codes and "data-identifier-missing" not in codes


def test_a_profile_that_fails_its_schema_is_refused(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("schema: manuscript-guard/journal/1\nname: No address\n", encoding="utf-8")
    code, report, err = audited(capsys, str(paper_md(tmp_path)), "--journal", str(broken))
    assert code == 2 and report["ok"] is False
    assert "is not a journal profile the audit can read" in report["error"]
    assert "source_url" in err and "retrieved_on" in err


def test_authors_without_a_journal_are_refused(tmp_path: Path, capsys) -> None:
    code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--authors",
                                 str(authors_file(tmp_path)))  # fmt: skip
    assert code == 2 and "--authors goes with --journal" in report["error"]


def test_the_main_document_is_named_first_as_a_file(tmp_path: Path, capsys) -> None:
    folder = tmp_path / "submission"
    folder.mkdir()
    paper_md(folder)
    code, report, _err = audited(capsys, str(folder), "--journal", str(profile(tmp_path)))
    assert code == 2 and "name it first, as a file" in report["error"]


def test_the_rest_of_the_submission_is_not_held_to_the_limits(tmp_path: Path, capsys) -> None:
    supplement = tmp_path / "supplement.md"
    supplement.write_text("# Supplementary methods\n\n" + "More words. " * 80, encoding="utf-8")
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), str(supplement),
                                  "--journal", str(profile(tmp_path)))  # fmt: skip
    others = [f for f in report["findings"] if f["code"] == "journal-not-main-document"]
    assert [Path(f["path"]).name for f in others] == ["supplement.md"]


def test_the_first_paper_named_is_the_main_document_whichever_it_is(tmp_path: Path,
                                                                    capsys) -> None:  # fmt: skip
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): the
    main document is the first paper named, so a supplement named first is held to the
    limits and the main document after it is read as the rest of the submission."""
    supplement = tmp_path / "supplement.md"
    supplement.write_text("# Supplementary methods\n\n" + "More words. " * 80, encoding="utf-8")
    paper = paper_md(tmp_path)
    for named, held, rest in (((supplement, paper), "main text: 162 words, limit 40", "paper.md"),
                              ((paper, supplement), "main text: 65 words, limit 40",
                               "supplement.md")):  # fmt: skip
        _code, report, _err = audited(capsys, *map(str, named), "--journal",
                                      str(profile(tmp_path)))  # fmt: skip
        over = [f["message"] for f in report["findings"] if f["code"] == "over-journal-limit"]
        others = [Path(f["path"]).name for f in report["findings"]
                  if f["code"] == "journal-not-main-document"]  # fmt: skip
        assert (over, others) == ([held], [rest])


def test_the_notice_is_said_with_a_reader_option_and_not_without(tmp_path: Path, capsys) -> None:
    _code, _report, err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                  str(profile(tmp_path)))  # fmt: skip
    assert NOTICE in err
    _code, _report, err = audited(capsys, str(paper_md(tmp_path)))
    assert NOTICE not in err


@needs_pandoc
def test_a_docx_is_held_to_the_journal_as_pandoc_converts_it(tmp_path: Path, capsys) -> None:
    paper_md(tmp_path)
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    _code, report, _err = audited(capsys, str(tmp_path / "paper.docx"), "--journal",
                                  str(profile(tmp_path)))  # fmt: skip
    codes = {f["code"] for f in section(report, "Journal (G4)")}
    assert {"over-journal-limit", "missing-required-statement"} <= codes


def test_without_pandoc_g4_on_a_docx_is_said_not_run(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import document

    def absent() -> str:
        raise document.BuildError("pandoc is not on PATH")

    monkeypatch.setattr(document, "pandoc", absent)
    paper = make_docx(tmp_path / "paper.docx")
    _code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)))
    not_run = [f for f in report["findings"] if f["code"] == "journal-not-run"]
    assert len(not_run) == 1 and "pandoc is not on PATH" in not_run[0]["message"]


# --------------------------------------------------------------------- the Document section


def make_docx(path: Path, *, creator: str = "Ada Example", commenter: str = "Ada Example",
              text: str = "Of 40 patients, 12 had dark urine.") -> Path:  # fmt: skip
    """A .docx with a tracked insertion and deletion, a hidden run, one comment, and a
    person in each field Word keeps names in."""
    body = (
        f"<w:p><w:r><w:t>{text}</w:t></w:r>"
        "<w:ins w:id='1' w:author='Ben Reviser'><w:r><w:t> Added 3.</w:t></w:r></w:ins>"
        "<w:del w:id='2' w:author='Ben Reviser'><w:r><w:delText> Gone 4.</w:delText></w:r>"
        "</w:del>"
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t> Hidden 5.</w:t></w:r>"
        "<w:r><w:rPr><w:vanish w:val='0'/></w:rPr><w:t> Shown 6.</w:t></w:r></w:p>"
        "<w:p><w:pPr><w:rPr><w:ins w:id='3' w:author='Ben Reviser'/></w:rPr></w:pPr></w:p>"
    )
    document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body>{body}</w:body>"
                "</w:document>")  # fmt: skip
    comments = (f"<?xml version='1.0'?><w:comments xmlns:w='{W}'><w:comment w:id='0' "
                f"w:author='{commenter}'><w:p><w:r><w:t>Check this.</w:t></w:r></w:p>"
                "</w:comment></w:comments>")  # fmt: skip
    core = ("<?xml version='1.0'?><cp:coreProperties xmlns:cp='http://schemas.openxmlformats.org"
            "/package/2006/metadata/core-properties' xmlns:dc='http://purl.org/dc/elements/1.1/'>"
            f"<dc:creator>{creator}</dc:creator><cp:lastModifiedBy>Ben Reviser"
            "</cp:lastModifiedBy></cp:coreProperties>")  # fmt: skip
    people = ("<?xml version='1.0'?><w15:people xmlns:w15='http://schemas.microsoft.com/office/"
              "word/2012/wordml'><w15:person w15:author='Cy Third'/></w15:people>")  # fmt: skip
    with zipfile.ZipFile(path, "w") as archive:
        for name, part in (("word/document.xml", document), ("word/comments.xml", comments),
                           ("docProps/core.xml", core), ("word/people.xml", people)):
            archive.writestr(zipfile.ZipInfo(name, FIXED_TIME), part)
    return path


def test_a_docx_says_its_changes_comments_hidden_text_and_people(tmp_path: Path, capsys) -> None:
    paper = make_docx(tmp_path / "paper.docx")
    code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)),
                                 "--strict")  # fmt: skip
    counts = report["counts"]
    assert (counts["tracked_insertions"], counts["tracked_deletions"], counts["tracked_moves"],
            counts["comments"], counts["hidden_runs"]) == (1, 1, 0, 1, 1)  # fmt: skip
    document = section(report, "Document")
    held = [f for f in document if f["code"] == "document-holds"]
    assert len(held) == 1 and held[0]["severity"] == "warn" and not held[0]["counted"]
    people = [f["message"] for f in document if f["code"] == "document-person"]
    assert people == [
        "the document's author (dc:creator): Ada Example",
        "the document's last editor (cp:lastModifiedBy): Ben Reviser",
        "the author of a tracked change or a comment (w:author): Ben Reviser",
        "the author of a tracked change or a comment (w:author): Ada Example",
        "the people who edited it (word/people.xml): Cy Third",
    ], people
    # A tracked change is not counted: some journals ask for a revision with its changes
    # shown (decision 8).
    assert code == 0


def test_without_a_reader_option_there_is_no_document_section(tmp_path: Path, capsys) -> None:
    _code, report, _err = audited(capsys, str(make_docx(tmp_path / "paper.docx")))
    assert not section(report, "Document") and "comments" not in report["counts"]


def test_a_markdown_paper_has_no_document_to_read(tmp_path: Path, capsys) -> None:
    main(["audit", str(paper_md(tmp_path)), "--journal", str(profile(tmp_path))])
    out = capsys.readouterr().out
    assert "=== Document ===" in out and "Not applicable: no .docx was given" in out


# ---------------------------------------------------------------------------- --authors


def authors_file(tmp_path: Path) -> Path:
    path = tmp_path / "authors.yaml"
    path.write_text(
        "authors:\n"
        "  - given: Ada\n    family: Example\n    email: ada@example.org\n"
        "affiliations:\n"
        "  - text: Department of Examples, University of Nowhere Hospital, Somewhere\n",
        encoding="utf-8",
    )
    return path


def test_an_author_in_a_comment_of_a_blind_document_is_counted(tmp_path: Path, capsys) -> None:
    paper = make_docx(tmp_path / "paper.docx")
    code, report, _err = audited(capsys, str(paper), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    places = {f["message"].split(" is in ")[1].split(" of paper.docx")[0] for f in named}
    assert places == {"the author of a tracked change or a comment",
                      "the document's author (dc:creator)"}, named  # fmt: skip
    assert all(f["counted"] and f["section"] == "Document" for f in named)
    assert code == 1 and report["counts"]["authors_named"] == 2
    assert all("ask the authors for a file without it" in f["hint"] for f in named)


def test_a_blind_document_that_names_nobody_passes(tmp_path: Path, capsys) -> None:
    paper = make_docx(tmp_path / "paper.docx", creator="Editorial Office", commenter="Ed")
    code, report, _err = audited(capsys, str(paper), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    assert code == 0 and not [f for f in report["findings"] if f["counted"]]


def test_an_institution_named_in_a_blind_markdown_paper_is_counted(
    tmp_path: Path, capsys
) -> None:
    text = PAPER + "\nWe thank the University of Nowhere Hospital for its help.\n"
    code, report, _err = audited(capsys, str(paper_md(tmp_path, text)), "--journal",
                                 str(profile(tmp_path, blinding="triple")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert [f["message"].split(" is in ")[0] for f in named] == [
        "'University of Nowhere Hospital'"]
    assert code == 1


def test_an_author_named_in_the_rest_of_the_submission_is_counted(tmp_path: Path,
                                                                  capsys) -> None:  # fmt: skip
    """The reviewers read the supplement too: every document given is looked in, and only the
    main one is held to the journal's limits."""
    supplement = tmp_path / "supplement.md"
    supplement.write_text("# Supplementary methods\n\nAs A. Example showed before, 12 of 40.\n",
                          encoding="utf-8")  # fmt: skip
    code, report, _err = audited(capsys, str(paper_md(tmp_path)), str(supplement), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert [Path(f["path"]).name for f in named] == ["supplement.md"], named
    assert code == 1


def test_an_author_in_a_latex_preamble_is_counted(tmp_path: Path, capsys) -> None:
    (tmp_path / "main.tex").write_text(
        f"{BS}documentclass{{article}}{BS}author{{Ada~Example}}{BS}begin{{document}}"
        f"{BS}section{{Results}}Of 40 patients, 12 had dark urine.{BS}end{{document}}\n",
        encoding="utf-8",
    )
    code, report, _err = audited(capsys, str(tmp_path / "main.tex"), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert [f["message"].split(" is in ")[0] for f in named] == ["'Ada Example'"], named
    assert code == 1


def test_a_review_that_is_not_blind_looks_for_nobody_and_says_so(tmp_path: Path, capsys) -> None:
    paper = make_docx(tmp_path / "paper.docx")
    code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)),
                                 "--authors", str(authors_file(tmp_path)), "--strict")  # fmt: skip
    said = [f for f in report["findings"] if f["code"] == "authors-not-looked-for"]
    assert len(said) == 1 and "single" in said[0]["message"]
    assert code == 0


def test_a_blind_review_without_authors_says_nobody_was_looked_for(tmp_path: Path, capsys) -> None:
    _code, report, _err = audited(capsys, str(make_docx(tmp_path / "paper.docx")), "--journal",
                                  str(profile(tmp_path, blinding="double")))  # fmt: skip
    said = [f for f in report["findings"] if f["code"] == "authors-not-looked-for"]
    assert len(said) == 1 and "--authors names them" in said[0]["message"]


def test_an_authors_file_without_names_is_refused(tmp_path: Path, capsys) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("authors:\n  - email: ada@example.org\n", encoding="utf-8")
    code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                 str(profile(tmp_path)), "--authors", str(bad))  # fmt: skip
    assert code == 2 and "has no `given` and `family` name" in report["error"]


# ------------------------------------------------- review round 1 of #478, each its finding


@pytest.mark.parametrize("blinding", ["single", None])
def test_a_review_that_is_not_blind_is_never_said_to_be_blind(
    tmp_path: Path, capsys, blinding: str | None
) -> None:
    """Round 1, finding 1: with `blinding: single`, or no key, and no --authors, the Document
    section said "The journal's review is blind"."""
    main(["audit", str(make_docx(tmp_path / "paper.docx")), "--journal",
          str(profile(tmp_path, blinding=blinding))])  # fmt: skip
    out = capsys.readouterr().out
    assert "review is blind" not in out and "-blind" not in out, out
    _code, report, _err = audited(capsys, str(make_docx(tmp_path / "paper.docx")), "--journal",
                                  str(profile(tmp_path, blinding=blinding)))  # fmt: skip
    assert not [f for f in report["findings"] if f["code"] == "authors-not-looked-for"]


def tables(count: int) -> str:
    return "".join(f"\n| Group | n |\n|---|---|\n| A | {i} |\n| B | {i + 1} |\n"
                   for i in range(count))  # fmt: skip


def test_six_tables_against_a_limit_of_three_are_over_it(tmp_path: Path, capsys) -> None:
    """Round 1, finding 2: `measure` counts a table only as a binding, so a paper's own six
    tables passed a limit of three, and the report said "Within every limit"."""
    journal = profile(tmp_path, limits="tables: 3\n  display_items: 4")
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + tables(6))),
                                  "--journal", str(journal))  # fmt: skip
    over = {f["message"] for f in report["findings"] if f["code"] == "over-journal-limit"}
    assert over == {"tables: 6, limit 3", "figures and tables: 6, limit 4"}, over
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + tables(3))),
                                  "--journal", str(journal))  # fmt: skip
    assert not [f for f in report["findings"] if f["code"] == "over-journal-limit"]


def test_a_table_in_a_comment_or_a_listing_is_not_counted(tmp_path: Path, capsys) -> None:
    hidden = f"\n<!--\n{tables(1)}\n-->\n\n```\n{tables(1)}\n```\n"
    journal = profile(tmp_path, limits="tables: 1")
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + tables(1) + hidden)),
                                  "--journal", str(journal))  # fmt: skip
    assert not [f for f in report["findings"] if f["code"] == "over-journal-limit"]


def test_a_table_written_in_html_puts_the_table_limit_under_not_checked(
    tmp_path: Path, capsys
) -> None:
    html = "\n<table><tr><td>A</td><td>1</td></tr></table>\n"
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + html)), "--journal",
                                  str(profile(tmp_path, limits="tables: 3")))  # fmt: skip
    skipped = [f["message"] for f in report["findings"] if f["code"] == "journal-not-checked"]
    assert any("written in HTML" in said for said in skipped), skipped


@needs_pandoc
def test_a_docx_with_six_tables_is_over_a_limit_of_three(tmp_path: Path, capsys) -> None:
    paper_md(tmp_path, PAPER + tables(6))
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    over, unchecked = _over_and_unchecked(capsys, tmp_path / "paper.docx",
                                          profile(tmp_path, limits="tables: 3"))  # fmt: skip
    assert (over, unchecked) == (["tables: 6, limit 3"], [])


def _converted_as(monkeypatch, tmp_path: Path, markdown: str) -> Path:
    """A .docx that pandoc converts to `markdown` with its lines ended "\\r\\n", as the
    pandoc on Windows writes them, whatever the system the test runs on."""
    from manuscript_guard import from_word

    tree = {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": [
        {"t": "Header", "c": [1, ["introduction", [], []], [{"t": "Str", "c": "Introduction"}]]},
        {"t": "Para", "c": [{"t": "Str", "c": "Text."}]}]}  # fmt: skip
    windows = markdown.replace("\n", "\r\n")

    def runner(arguments, given, path):
        return json.dumps(tree) if arguments[arguments.index("-t") + 1] == "json" else windows

    monkeypatch.setattr(from_word, "runner", runner)
    paper = tmp_path / "paper.docx"
    with zipfile.ZipFile(paper, "w") as archive:
        archive.writestr("word/document.xml", f"<?xml version='1.0'?><w:document xmlns:w='{W}'>"
                         "<w:body><w:p><w:r><w:t>Text.</w:t></w:r></w:p></w:body></w:document>")
    return paper


def test_a_docx_converted_with_windows_line_ends_has_its_tables_counted(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pandoc on Windows ends its Markdown's lines "\\r\\n", and the audit kept them: no table
    was read in that text, so `--journal` said a table's rule was not read and not all were
    counted, where Linux and the page said nothing (2026-11-25, while building #791). A table
    indented in a list item is still said to be one that was not counted."""
    journal = profile(tmp_path, limits="tables: 1")
    paper = _converted_as(monkeypatch, tmp_path, PAPER + tables(2))
    assert _over_and_unchecked(capsys, paper, journal) == (["tables: 2, limit 1"], [])
    listed = "\n1.  The groups:\n\n    | Group | n |\n    |---|---|\n    | A | 1 |\n"
    paper = _converted_as(monkeypatch, tmp_path, PAPER + tables(1) + listed)
    _over, unchecked = _over_and_unchecked(capsys, paper, journal)
    assert len(unchecked) == 1 and "indented" in unchecked[0], unchecked


def _paths_in(node: object) -> list[str]:
    """Every value of a "path" key in a report's `--json`, at any depth."""
    if isinstance(node, list):
        return [path for item in node for path in _paths_in(item)]
    if not isinstance(node, dict):
        return []
    here = [node["path"]] if isinstance(node.get("path"), str) else []
    return here + [path for value in node.values() for path in _paths_in(value)]


def test_audit_names_a_file_with_forward_slashes(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows the report said `G4 journals\\examples.yaml` and `--json` gave
    `"path": "project\\\\main.tex"`, where Linux and the page say `journals/examples.yaml` and
    `project/main.tex`, so the page's report could not be the command line's there (found
    building #791). An audit writes a path with forward slashes on every system (Basile,
    2026-11-25)."""
    (tmp_path / "project" / "sections").mkdir(parents=True)
    (tmp_path / "project" / "main.tex").write_text(
        f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Introduction}}\n"
        f"The ROR was 2.5 in the study.\n{BS}input{{sections/results}}\n{BS}end{{document}}\n",
        encoding="utf-8")  # fmt: skip
    (tmp_path / "project" / "sections" / "results.tex").write_text(
        f"{BS}section{{Results}}\nOf 40 patients, 12 had dark urine. The HR was 1.2.\n",
        encoding="utf-8")  # fmt: skip
    (tmp_path / "journals").mkdir()
    profile(tmp_path).replace(tmp_path / "journals" / "examples.yaml")
    monkeypatch.chdir(tmp_path)
    given = ["project/main.tex", "--journal", "journals/examples.yaml"]
    main(["audit", *given])
    assert " G4 journals/examples.yaml\n" in capsys.readouterr().out
    _code, report, _err = audited(capsys, *given)
    paths = _paths_in(report["findings"])
    assert {"project/main.tex", "project/sections/results.tex",
            "journals/examples.yaml"} <= set(paths), paths  # fmt: skip
    assert not [path for path in paths if BS in path], paths


def test_a_path_the_platform_writes_with_backslashes_is_written_with_forward_ones() -> None:
    """What `test_audit_names_a_file_with_forward_slashes` holds on Windows, held on every
    system: each place the report and `--json` name a file, given Windows' paths."""
    from dataclasses import replace
    from pathlib import PureWindowsPath

    from manuscript_guard.auditing import unsorted
    from manuscript_guard.auditing.report import REFERENCES, Item, _rendered, _Show
    from manuscript_guard.auditing.undefined import Undefined, listed
    from manuscript_guard.findings import INFO, Finding

    class Placed:
        def said(self, line: int | None) -> str:
            return f"Methods, paragraph {line}"

    root = PureWindowsPath("C:\\work")
    inner = PureWindowsPath("project\\sections\\results.tex")
    item = Item(REFERENCES, "G7", unsorted.CODE, "entry 3: not sorted: why: check it by hand",
                INFO, False, inner, 2)  # fmt: skip
    assert item.as_dict()["path"] == "project/sections/results.tex"
    assert _Show(root)(root / inner) == "project/sections/results.tex"
    journal = Finding("G4", "over-journal-limit", "m", path=PureWindowsPath("journals\\x.yaml"))
    under = Finding("G4", "over-journal-limit", "m", path=root / inner, line=2)
    word = Finding("G4", "over-journal-limit", "m", path=root / "paper.docx", line=3)
    # With no paper's places, and with a .docx's beside them (`_rendered`'s two ways).
    for found, show in (([journal, under], _Show(root)),
                        ([journal, under, word], _Show(root, {root / "paper.docx": Placed()}))):
        said = _rendered(found, root, show)
        assert " G4 journals/x.yaml\n" in said and " G4 project/sections/results.tex:2\n" in said
    forms = listed(Undefined("G14", "abbreviation-undefined", "m", forms=(("HR", under),)))
    assert forms["forms"][0]["path"] == "C:/work/project/sections/results.tex"
    entries = unsorted.one_finding([item, replace(item, line=4)])[0].listed["entries"]
    assert [entry["path"] for entry in entries] == ["project/sections/results.tex"] * 2


def test_a_latex_paper_s_table_floats_are_held_to_the_limit(tmp_path: Path, capsys) -> None:
    floats = "".join(f"{BS}begin{{table}}{BS}caption{{T{i}}}{BS}begin{{tabular}}{{ll}}A & {i}"
                     f"{BS}end{{tabular}}{BS}end{{table}}\n" for i in range(4))  # fmt: skip
    (tmp_path / "main.tex").write_text(
        f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}\n{floats}"
        f"{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    _code, report, _err = audited(capsys, str(tmp_path / "main.tex"), "--journal",
                                  str(profile(tmp_path, limits="tables: 3")))  # fmt: skip
    over = {f["message"] for f in report["findings"] if f["code"] == "over-journal-limit"}
    assert over == {"tables: 4, limit 3"}, over


SELF_CITED = "Example, A. (2020). An earlier study of dark urine. J Ex 1:1-2."


def test_a_self_citation_in_a_markdown_reference_list_is_not_a_leak(
    tmp_path: Path, capsys
) -> None:
    """Round 1, finding 3: the authors' own work cited in the third person, in the reference
    list, is what a blind journal asks for, and was counted as the author named."""
    text = PAPER + f"\n# References\n\n1. {SELF_CITED}\n"
    code, report, _err = audited(capsys, str(paper_md(tmp_path, text)), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    assert not [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert code == 0
    # Outside the list it is a leak still.
    text = PAPER + f"\nAs {SELF_CITED}\n\n# References\n\n1. Other, B. (2019). X. J Ex 2:3.\n"
    code, report, _err = audited(capsys, str(paper_md(tmp_path, text)), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    assert len([f for f in report["findings"] if f["code"] == "blind-document-names-author"]) == 1
    assert code == 1


def docx_of(path: Path, paragraphs: list[tuple[str, str]]) -> Path:
    """A .docx of `(style, text)` paragraphs, with no styles part: the style is only an id,
    as EndNote's "EndNoteBibliography" or Word's "Normal" is in a document not built here."""
    body = "".join(
        (f"<w:p><w:pPr><w:pStyle w:val='{style}'/></w:pPr>" if style else "<w:p>")
        + f"<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"
        for style, text in paragraphs
    )
    document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body>{body}</w:body>"
                "</w:document>")  # fmt: skip
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), document)
    return path


@pytest.mark.parametrize("style", ["EndNoteBibliography", "Normal", ""])
def test_a_self_citation_in_a_docx_reference_list_is_not_a_leak(
    tmp_path: Path, capsys, style: str
) -> None:
    paper = docx_of(tmp_path / "paper.docx", [
        ("", "Of 40 patients, 12 had dark urine."), ("", "References"),
        (style, f"1. {SELF_CITED}"), (style, "2. Other, B. (2019). X. J Ex 2:3."),
    ])  # fmt: skip
    code, report, _err = audited(capsys, str(paper), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    assert not [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert code == 0


def test_a_name_a_tracked_change_deleted_in_the_text_is_still_a_leak(
    tmp_path: Path, capsys
) -> None:
    """The text is read as the audit reads it, its reference list cut; what a tracked change
    deleted outside the list is read too, since a reviewer who shows the changes sees it."""
    paper = make_docx(tmp_path / "paper.docx", creator="Office", commenter="Ed",
                      text="Of 40 patients, 12 had dark urine.")  # fmt: skip
    with zipfile.ZipFile(paper) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    parts["word/document.xml"] = parts["word/document.xml"].replace(
        b"Gone 4.", b"As A. Example found.")
    with zipfile.ZipFile(paper, "w") as archive:
        for name, data in parts.items():
            archive.writestr(zipfile.ZipInfo(name, FIXED_TIME), data)
    code, report, _err = audited(capsys, str(paper), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert len(named) == 1 and "tracked change deleted" in named[0]["message"], named
    assert code == 1


def latex_with_bibtex(tmp_path: Path) -> Path:
    path = tmp_path / "main.tex"
    path.write_text(
        f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}Of 40, 12."
        f"{BS}section{{Data availability}}The data are at https://doi.org/10.5281/zenodo.1234567."
        f"{BS}bibliographystyle{{plain}}{BS}bibliography{{refs}}{BS}end{{document}}\n",
        encoding="utf-8",
    )
    return path


def test_a_dataset_is_not_said_uncited_where_no_reference_list_was_read(
    tmp_path: Path, capsys
) -> None:
    """Round 1, finding 4: a LaTeX paper's list is in its .bib, which is not read, so every
    DOI of its data statement was "not cited"."""
    more = ("data_availability:\n  source: https://example.org/data\n"
            f"  retrieved_on: {date.today().isoformat()}\n  identifier_required: true\n")
    _code, report, _err = audited(capsys, str(latex_with_bibtex(tmp_path)), "--journal",
                                  str(profile(tmp_path, more=more)))  # fmt: skip
    codes = {f["code"] for f in report["findings"]}
    assert "data-doi-uncited" not in codes, report["findings"]
    skipped = [f["message"] for f in report["findings"] if f["code"] == "journal-not-checked"]
    assert any("main document's reference list was not read" in s for s in skipped), skipped


def svg(text: str) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'><text x='1' y='5'>"
            f"{text}</text></svg>")  # fmt: skip


def test_only_the_pictures_a_latex_paper_places_are_searched(tmp_path: Path, capsys) -> None:
    """Round 1, non-blocking 1: every PDF and SVG under the folder was read as a figure, so a
    compiled paper or an earlier one beside main.tex was searched and counted."""
    (tmp_path / "old-draft.svg").write_text(svg("Ada Example"), encoding="utf-8")
    (tmp_path / "flow.svg").write_text(svg("Patients screened"), encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}Of 40, 12."
        f"{BS}includegraphics{{flow.svg}}\n% {BS}includegraphics{{old-draft.svg}}\n"
        f"{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    argv = (str(tmp_path / "main.tex"), "--journal", str(profile(tmp_path, blinding="double")),
            "--authors", str(authors_file(tmp_path)), "--strict")  # fmt: skip
    code, report, _err = audited(capsys, *argv)
    assert not [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert code == 0
    (tmp_path / "flow.svg").write_text(svg("Drawn by Ada Example"), encoding="utf-8")
    code, report, _err = audited(capsys, *argv)
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert [f["message"].split(" is in ")[1].split(" of ")[0] for f in named] == [
        "a figure (flow.svg)"], named
    assert code == 1


def test_a_move_word_writes_over_two_paragraphs_counts_once(tmp_path: Path, capsys) -> None:
    """Word marks a moved passage with a named range where it went from and where it went
    to, and wraps each paragraph's runs of it in its own w:moveFrom or w:moveTo: two
    paragraphs moved together are one move."""
    moved = "".join(
        f"<w:p><w:moveTo w:id='{n}' w:author='Ben'><w:r><w:t>Moved {n}.</w:t></w:r></w:moveTo>"
        "</w:p>" for n in (11, 12))  # fmt: skip
    gone = "".join(
        f"<w:p><w:moveFrom w:id='{n}' w:author='Ben'><w:r><w:t>Moved {n}.</w:t></w:r>"
        "</w:moveFrom></w:p>" for n in (21, 22))  # fmt: skip
    body = (
        "<w:p><w:r><w:t>Of 40 patients, 12 had dark urine.</w:t></w:r></w:p>"
        "<w:moveFromRangeStart w:id='1' w:name='move1' w:author='Ben'/>" + gone +
        "<w:moveFromRangeEnd w:id='1'/>"
        "<w:p><w:r><w:t>Between.</w:t></w:r></w:p>"
        "<w:moveToRangeStart w:id='2' w:name='move1' w:author='Ben'/>" + moved +
        "<w:moveToRangeEnd w:id='2'/>"
    )
    document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body>{body}</w:body>"
                "</w:document>")  # fmt: skip
    paper = tmp_path / "paper.docx"
    with zipfile.ZipFile(paper, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), document)
    _code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)))
    assert report["counts"]["tracked_moves"] == 1
    assert report["counts"]["tracked_insertions"] == report["counts"]["tracked_deletions"] == 0


# ------------------------------------------------- review round 2 of #478, each its note

HEADING_STYLES = (f"<w:styles xmlns:w='{W}'><w:style w:type='paragraph' w:styleId='Heading1'>"
                  "<w:name w:val='heading 1'/></w:style></w:styles>")  # fmt: skip


def test_back_matter_after_a_docx_list_under_a_styled_heading_is_read(
    tmp_path: Path, capsys
) -> None:
    """Round 2, note 1: the list's cut ran from a styled "References" to the next styled
    heading, so the acknowledgements under a Normal title after it were never read."""
    paper = docx_of(tmp_path / "paper.docx", [
        ("", "Of 40 patients, 12 had dark urine."), ("Heading1", "References"),
        ("", f"1. {SELF_CITED}"), ("", "2. Other, B. (2019). X. J Ex 2:3."),
        ("", "Acknowledgements"), ("", "We thank the University of Nowhere Hospital."),
    ])  # fmt: skip
    with zipfile.ZipFile(paper, "a") as archive:
        archive.writestr(zipfile.ZipInfo("word/styles.xml", FIXED_TIME), HEADING_STYLES)
    code, report, _err = audited(capsys, str(paper), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f["message"].split(" is in ")[0] for f in report["findings"]
             if f["code"] == "blind-document-names-author"]  # fmt: skip
    assert named == ["'University of Nowhere Hospital'"], named
    assert code == 1


def _named(capsys, tmp_path: Path, paper: Path) -> list[str]:
    _code, report, _err = audited(capsys, str(paper), "--journal",
                                  str(profile(tmp_path, blinding="double")), "--authors",
                                  str(authors_file(tmp_path)))  # fmt: skip
    return [f["message"].split(" is in ")[0] for f in report["findings"]
            if f["code"] == "blind-document-names-author"]  # fmt: skip


def test_the_blinding_check_finds_a_name_as_the_build_does(tmp_path: Path, capsys) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): the
    given and family name, or an initial with its stop, is found; a family name alone, an
    initial with no stop, and a part of the affiliation under three words ("Somewhere") are
    not looked for, where its parts of three words or more are."""
    for said, found in (("Ada Example", "'Ada Example'"), ("A. Example", "'Ada Example'"),
                        ("Example, A.", "'Ada Example'"), ("A Example", None),
                        ("Example", None), ("Ada", None), ("Somewhere", None),
                        ("Department of Examples", "'Department of Examples'"),
                        ("University of Nowhere Hospital", "'University of Nowhere Hospital'")):
        paper = paper_md(tmp_path, PAPER + f"\nAs {said} wrote, it was so.\n")
        assert _named(capsys, tmp_path, paper) == ([] if found is None else [found]), said


def test_a_self_citation_is_read_as_text_where_the_list_is_not_cut_out(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): a list
    the audit does not find ("Sources") is read as text, its self-citation reported; in a
    .docx a deleted entry is read but in a list styled "Bibliography"; an entry shaped as a
    title of back matter or a caption, or a Word table between two entries, ends the cut
    early, and the self-citation after it is reported, a false alarm; and a list laid out as
    a Word table is cut at its first row."""
    listed = f"\n\n1. {SELF_CITED}\n2. Other, B. (2019). X. J Ex 2:3.\n"
    assert _named(capsys, tmp_path, paper_md(tmp_path, PAPER + "\n# Sources" + listed)) == [
        "'Ada Example'"]
    # The other side: the list under "References" is cut out, as `read_paper` finds it.
    assert _named(capsys, tmp_path, paper_md(tmp_path, PAPER + "\n# References" + listed)) == []
    for style, leaks in (("Bibliography", False), ("", True), ("Normal", True)):
        pstyle = f"<w:pPr><w:pStyle w:val='{style}'/></w:pPr>" if style else ""
        body = ("<w:p><w:r><w:t>Of 40 patients, 12 had dark urine.</w:t></w:r></w:p>"
                "<w:p><w:r><w:t>References</w:t></w:r></w:p>"
                f"<w:p>{pstyle}<w:r><w:t>1. Other, B. (2019). X. J Ex 2:3.</w:t></w:r></w:p>"
                f"<w:p>{pstyle}<w:del w:id='1' w:author='Ed'><w:r><w:delText>2. {SELF_CITED}"
                "</w:delText></w:r></w:del></w:p>")  # fmt: skip
        paper = tmp_path / "deleted.docx"
        with zipfile.ZipFile(paper, "w") as archive:
            archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME),
                             f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body>{body}"
                             "</w:body></w:document>")  # fmt: skip
        assert _named(capsys, tmp_path, paper) == (["'Ada Example'"] if leaks else []), style
    for shaped, leaks in (("Funding", True), ("Acknowledgements", True),
                          ("Figure 1. A chart. Office (2018).", True),
                          ("Table 1 of the census. Office (2018).", True),
                          ("Other, C. (2018). Z. J Ex 4:5.", False)):  # fmt: skip
        paper = docx_of(tmp_path / "cut.docx", [
            ("", "Of 40 patients, 12 had dark urine."), ("Heading1", "References"),
            ("", "Other, B. (2019). X. J Ex 2:3."), ("", shaped), ("", SELF_CITED)])  # fmt: skip
        with zipfile.ZipFile(paper, "a") as archive:
            archive.writestr(zipfile.ZipInfo("word/styles.xml", FIXED_TIME), HEADING_STYLES)
        assert _named(capsys, tmp_path, paper) == (["'Ada Example'"] if leaks else []), shaped
    # A table between two entries ends the cut there too, and the entry after it is read.
    for between, leaks in (("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cohort 2019</w:t></w:r></w:p>"
                            "</w:tc></w:tr></w:tbl>", True), ("", False)):  # fmt: skip
        paper = tmp_path / "tabled.docx"
        with zipfile.ZipFile(paper, "w") as archive:
            archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), (
                f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body><w:p><w:r><w:t>Of 40 "
                "patients, 12 had dark urine.</w:t></w:r></w:p><w:p><w:pPr><w:pStyle "
                "w:val='Heading1'/></w:pPr><w:r><w:t>References</w:t></w:r></w:p><w:p><w:r>"
                "<w:t>Other, B. (2019). X. J Ex 2:3.</w:t></w:r></w:p>" + between
                + f"<w:p><w:r><w:t>{SELF_CITED}</w:t></w:r></w:p></w:body></w:document>"))
            archive.writestr(zipfile.ZipInfo("word/styles.xml", FIXED_TIME), HEADING_STYLES)
        assert _named(capsys, tmp_path, paper) == (["'Ada Example'"] if leaks else []), between
    cell = "<w:tc><w:p><w:r><w:t xml:space='preserve'>{}</w:t></w:r></w:p></w:tc>"
    rows = "".join(f"<w:tr>{cell.format(n)}{cell.format(text)}</w:tr>"
                   for n, text in (("1.", "Other, B. (2019). X. J Ex 2:3."), ("2.", SELF_CITED)))
    paper = tmp_path / "table.docx"
    with zipfile.ZipFile(paper, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), (
            f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body><w:p><w:r><w:t>Of 40 "
            "patients, 12 had dark urine.</w:t></w:r></w:p><w:p><w:pPr><w:pStyle "
            "w:val='Heading1'/></w:pPr><w:r><w:t>References</w:t></w:r></w:p>"
            f"<w:tbl>{rows}</w:tbl></w:body></w:document>"))  # fmt: skip
        archive.writestr(zipfile.ZipInfo("word/styles.xml", FIXED_TIME), HEADING_STYLES)
    assert _named(capsys, tmp_path, paper) == ["'Ada Example'"]


def test_a_limit_not_checked_is_never_said_to_be_kept(tmp_path: Path, capsys) -> None:
    """Round 2, note 2: with the table limits under "not checked", the section still said
    "Within every limit", under a heading that called every entry a project's record."""
    text = PAPER + "\n# Funding\n\nNone.\n\n<table><tr><td>A</td></tr></table>\n"
    roomy = profile(tmp_path, limits="main_text_words: 4000\n  tables: 3")
    main(["audit", str(paper_md(tmp_path, text)), "--journal", str(roomy)])
    out = capsys.readouterr().out
    assert "Within every limit" not in out and "they read a project's records" not in out, out
    assert "written in HTML" in out


def test_the_main_document_s_own_list_holds_the_data_statement(tmp_path: Path, capsys) -> None:
    """Round 2, note 3: a supplement's list made a dataset the main document cites (by its own
    list, or one not read) cited or not."""
    more = ("data_availability:\n  source: https://example.org/data\n"
            f"  retrieved_on: {date.today().isoformat()}\n  identifier_required: true\n")
    statement = ("\n# Data availability\n\nThe data are at https://doi.org/10.5281/zenodo.1234567"
                 ".\n")  # fmt: skip
    journal = profile(tmp_path, more=more)
    for listed in ("1. Doe J. The data. Zenodo. 2024. doi:10.5281/zenodo.1234567",
                   "1. Roe K. A trial. BMJ 2020;370:m1. doi:10.5555/fictional.1"):
        supplement = tmp_path / "supplement.md"
        supplement.write_text(f"# Supplementary methods\n\nMore.\n\n# References\n\n{listed}\n",
                              encoding="utf-8")  # fmt: skip
        _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + statement)),
                                      str(supplement), "--journal", str(journal))  # fmt: skip
        assert "data-doi-uncited" not in {f["code"] for f in report["findings"]}, listed
        skipped = [f["message"] for f in report["findings"] if f["code"] == "journal-not-checked"]
        assert any("main document's reference list was not read" in s for s in skipped), skipped


MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def test_a_tracked_change_in_a_text_box_counts_once(tmp_path: Path, capsys) -> None:
    """Round 2, note 4: Word writes a text box twice, its choice and a fallback for readers
    that predate it; the fallback is not read, as `text.docx` does not read it."""
    inserted = ("<w:p><w:ins w:id='{n}' w:author='Ben'><w:r><w:t>Boxed 7.</w:t></w:r></w:ins>"
                "<w:r><w:rPr><w:vanish/></w:rPr><w:t>Hidden.</w:t></w:r></w:p>")
    body = (
        "<w:p><w:r><w:t>Of 40 patients, 12 had dark urine.</w:t></w:r>"
        f"<w:r><mc:AlternateContent xmlns:mc='{MC}'><mc:Choice Requires='wps'>"
        + inserted.format(n=1) + "</mc:Choice><mc:Fallback>" + inserted.format(n=2)
        + "</mc:Fallback></mc:AlternateContent></w:r></w:p>"
    )
    document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}' xmlns:mc='{MC}'><w:body>"
                f"{body}</w:body></w:document>")  # fmt: skip
    paper = tmp_path / "paper.docx"
    with zipfile.ZipFile(paper, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), document)
    _code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)))
    assert (report["counts"]["tracked_insertions"], report["counts"]["hidden_runs"]) == (1, 1)


def test_a_change_of_formatting_and_a_box_written_only_as_a_fallback_are_not_counted(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): a
    change of formatting alone is no tracked change, and a text box Word wrote only as a
    fallback is not read, its change and its author uncounted; an insertion, in the text or
    in a box's choice, is counted with its author."""
    boxed = "<w:p><w:ins w:id='1' w:author='Ben'><w:r><w:t>Boxed 7.</w:t></w:r></w:ins></w:p>"
    ben = ["the author of a tracked change or a comment (w:author): Ben"]
    for inner, counted, named in (
        ("<w:r><w:rPr><w:b/><w:rPrChange w:id='5' w:author='Ben'><w:rPr/></w:rPrChange>"
         "</w:rPr><w:t> Bold 3.</w:t></w:r>", 0, ben),
        (f"<w:r><mc:AlternateContent><mc:Fallback>{boxed}</mc:Fallback></mc:AlternateContent>"
         "</w:r>", 0, []),
        ("<w:ins w:id='5' w:author='Ben'><w:r><w:t> Added 3.</w:t></w:r></w:ins>", 1, ben),
        (f"<w:r><mc:AlternateContent><mc:Choice Requires='wps'>{boxed}</mc:Choice>"
         "</mc:AlternateContent></w:r>", 1, ben),
    ):  # fmt: skip
        document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}' xmlns:mc='{MC}'><w:body>"
                    f"<w:p><w:r><w:t>Of 40 patients, 12 had dark urine.</w:t></w:r>{inner}</w:p>"
                    "</w:body></w:document>")  # fmt: skip
        paper = tmp_path / "paper.docx"
        with zipfile.ZipFile(paper, "w") as archive:
            archive.writestr(zipfile.ZipInfo("word/document.xml", FIXED_TIME), document)
        _code, report, _err = audited(capsys, str(paper), "--journal", str(profile(tmp_path)))
        counts = report["counts"]
        assert (counts["tracked_insertions"], counts["tracked_deletions"]) == (counted, 0), inner
        people = [f["message"] for f in section(report, "Document")
                  if f["code"] == "document-person"]  # fmt: skip
        assert people == named, inner


def test_a_latex_file_s_metadata_names_no_person_in_the_document_section(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): the
    Document section reads no LaTeX file's metadata: `pdfauthor` names no person there, and
    the blinding check finds the name in the preamble as the text it is."""
    (tmp_path / "main.tex").write_text(
        f"{BS}documentclass{{article}}\n{BS}usepackage{{hyperref}}\n"
        f"{BS}hypersetup{{pdfauthor={{Ada Example}}}}\n{BS}begin{{document}}\n"
        f"{BS}section{{Results}}\nOf 40, 12.\n{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    _code, report, _err = audited(capsys, str(tmp_path / "main.tex"), "--journal",
                                  str(profile(tmp_path, blinding="double")), "--authors",
                                  str(authors_file(tmp_path)))  # fmt: skip
    assert [(f["code"], f["message"]) for f in section(report, "Document")] == [
        ("blind-document-names-author", "'Ada Example' is in the text of main.tex, and the "
         "journal's review is double-blind")]  # fmt: skip


def test_a_table_in_a_block_quotation_is_counted(tmp_path: Path, capsys) -> None:
    """Round 2, note 5: a pipe table in a block quotation was not counted."""
    quoted = "".join(f"\n> | Group | n |\n> |---|---|\n> | A | {i} |\n" for i in range(4))
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + quoted)), "--journal",
                                  str(profile(tmp_path, limits="tables: 3")))  # fmt: skip
    over = {f["message"] for f in report["findings"] if f["code"] == "over-journal-limit"}
    assert over == {"tables: 4, limit 3"}, over


def test_a_table_indented_in_a_list_item_puts_the_table_limits_under_not_checked(
    tmp_path: Path, capsys
) -> None:
    """Round 2, note 5: a table in a list item, indented as pandoc writes one, was counted
    as none; where it cannot be read exactly, the limit is said not to be checked."""
    listed = ("\n1.  The groups:\n\n    | Group | n |\n    |---|---|\n    | A | 1 |\n\n"
              "    +-------+---+\n    | Group | n |\n    +=======+===+\n    | B     | 2 |\n"
              "    +-------+---+\n")  # fmt: skip
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + listed)), "--journal",
                                  str(profile(tmp_path, limits="tables: 3")))  # fmt: skip
    skipped = [f["message"] for f in report["findings"] if f["code"] == "journal-not-checked"]
    assert any("indented" in said for said in skipped), skipped
    # A table at the margin beside it is counted all the same.
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + tables(1))),
                                  "--journal", str(profile(tmp_path, limits="tables: 3")))
    skipped = [f["message"] for f in report["findings"] if f["code"] == "journal-not-checked"]
    assert not any("indented" in said for said in skipped), skipped


#: One table of each of the four kinds pandoc's manual shapes: pipe, simple, multiline, grid.
FOUR_KINDS = ("\n| Group | n |\n|---|---|\n| A | 1 |\n"
              "\n  Group   n\n  -----   ---\n  A       1\n\n"
              "\n-------------------\n  Group   n\n  -----   ---\n  A       1\n"
              "-------------------\n\n"
              "\n+-------+---+\n| Group | n |\n+=======+===+\n| A     | 1 |\n+-------+---+\n")


def _over_and_unchecked(capsys, paper: Path, journal: Path, *more: str) -> tuple[list, list]:
    _code, report, _err = audited(capsys, str(paper), *more, "--journal", str(journal))
    over = [f["message"] for f in report["findings"] if f["code"] == "over-journal-limit"]
    unchecked = [f["message"] for f in report["findings"]
                 if f["code"] == "journal-not-checked" and "table" in f["message"]]  # fmt: skip
    return over, unchecked


def test_the_tables_and_figures_counted_are_pandoc_s_four_kinds_floats_and_placed_figures(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): each
    of pandoc's four kinds of table is counted; a simple table in a list item whose columns'
    dashes run under three is not seen, neither counted nor said unchecked, where one of
    three is said; a LaTeX `tabular` in no captioned float is not counted; and a figure sent
    as a file of its own is not counted, where one the paper places is."""
    tables_3 = profile(tmp_path, limits="tables: 3")
    paper = paper_md(tmp_path, PAPER + FOUR_KINDS)
    assert _over_and_unchecked(capsys, paper, tables_3) == (["tables: 4, limit 3"], [])
    for dashes, unchecked in (("--", False), ("---", True)):
        listed = f"\n1.  The groups:\n\n    Group  n\n    {dashes}    {dashes}\n    A      1\n\n"
        over, said = _over_and_unchecked(capsys, paper_md(tmp_path, PAPER + tables(3) + listed),
                                         tables_3)  # fmt: skip
        assert over == [] and bool(said) is unchecked, dashes
    floats = "".join(f"{BS}begin{{table}}{BS}caption{{T{i}}}{BS}begin{{tabular}}{{ll}}A & {i}"
                     f"{BS}end{{tabular}}{BS}end{{table}}\n" for i in range(3))  # fmt: skip
    tabular = f"{BS}begin{{tabular}}{{ll}}A & 1{BS}end{{tabular}}"
    for fourth, counted in ((tabular, False),
                            (f"{BS}begin{{table}}{tabular}{BS}end{{table}}", False),
                            (f"{BS}begin{{table}}{BS}caption{{X}}{tabular}{BS}end{{table}}", True)):
        (tmp_path / "main.tex").write_text(
            f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}\n{floats}"
            f"{fourth}\n{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
        over, _said = _over_and_unchecked(capsys, tmp_path / "main.tex", tables_3)
        assert over == (["tables: 4, limit 3"] if counted else []), fourth
    figures_1 = profile(tmp_path, limits="figures: 1")
    for name in ("f1.png", "f2.png"):
        (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    placed = paper_md(tmp_path, PAPER + "\n![Figure 1. Flow](f1.png)\n")
    sent = tmp_path / "figure2.svg"
    sent.write_text(svg("Figure 2. Patients screened"), encoding="utf-8")
    assert _over_and_unchecked(capsys, placed, figures_1, "--figures", str(sent)) == ([], [])
    both = paper_md(tmp_path, PAPER + "\n![Figure 1. Flow](f1.png)\n\n![Figure 2. Flow](f2.png)\n")
    assert _over_and_unchecked(capsys, both, figures_1)[0] == ["figures: 2, limit 1"]


def _png(path: Path) -> Path:
    """A one-pixel picture pandoc can embed."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))  # fmt: skip

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0,
                                                                        0, 0))
                     + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))
    return path


@needs_pandoc
def test_a_word_layout_table_is_counted_and_a_picture_with_no_caption_is_not(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): a .docx's
    tables are counted as pandoc writes them, a Word table used for layout among them; and
    its figures as `measure` counts them, so a picture with no caption pandoc reads is not."""
    paper_md(tmp_path)
    subprocess.run(["pandoc", "paper.md", "-o", "plain.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    cell = "<w:tc><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc>"
    layout = f"<w:tbl><w:tr>{cell.format('Left')}{cell.format('Right')}</w:tr></w:tbl><w:p/>"
    with zipfile.ZipFile(tmp_path / "plain.docx") as source, zipfile.ZipFile(
            tmp_path / "layout.docx", "w") as out:  # fmt: skip
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "word/document.xml":
                text = data.decode("utf-8")
                at = text.rindex("<w:sectPr")
                data = (text[:at] + layout * 4 + text[at:]).encode("utf-8")
            out.writestr(item, data)
    over, _said = _over_and_unchecked(capsys, tmp_path / "layout.docx",
                                      profile(tmp_path, limits="tables: 3"))  # fmt: skip
    assert over == ["tables: 4, limit 3"]
    _png(tmp_path / "f.png")
    for caption, counted in (("", False), ("Figure 1. Flow", True)):
        paper_md(tmp_path, PAPER + f"\n![{caption}](f.png)\n\n![{caption}](f.png)\n")
        subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                       timeout=120)  # fmt: skip
        over, _said = _over_and_unchecked(capsys, tmp_path / "paper.docx",
                                          profile(tmp_path, limits="figures: 1"))  # fmt: skip
        assert over == (["figures: 2, limit 1"] if counted else []), caption


def test_a_latex_picture_is_found_from_the_entry_s_folder_or_its_file_s_and_no_other(
    tmp_path: Path, capsys
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): a
    LaTeX paper's pictures are found from the entry's folder or the placing file's own, by
    the name as written and with `.svg` after it; `\\graphicspath` is not followed, and a
    raster picture holds no text to read, an author's name in its bytes among them."""
    (tmp_path / "figs").mkdir()
    (tmp_path / "sections").mkdir()
    (tmp_path / "figs" / "flow.svg").write_text(svg("Drawn by Ada Example"), encoding="utf-8")
    (tmp_path / "sections" / "chart.svg").write_text(svg("Drawn by Ada Example"),
                                                     encoding="utf-8")  # fmt: skip
    (tmp_path / "sections" / "results.tex").write_text(f"{BS}includegraphics{{chart}}\n",
                                                       encoding="utf-8")  # fmt: skip
    (tmp_path / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n Drawn by Ada Example")
    for placed, figure in ((f"{BS}graphicspath{{{{figs/}}}}{BS}includegraphics{{flow}}", None),
                           (f"{BS}includegraphics{{figs/flow}}", "flow.svg"),
                           (f"{BS}input{{sections/results}}", "chart.svg"),
                           (f"{BS}includegraphics{{chart}}", None),
                           (f"{BS}includegraphics{{photo.png}}", None)):  # fmt: skip
        (tmp_path / "main.tex").write_text(
            f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}Of 40, 12."
            f"{placed}\n{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
        _code, report, _err = audited(capsys, str(tmp_path / "main.tex"), "--journal",
                                      str(profile(tmp_path, blinding="double")), "--authors",
                                      str(authors_file(tmp_path)))  # fmt: skip
        named = [f["message"] for f in report["findings"]
                 if f["code"] == "blind-document-names-author"]  # fmt: skip
        assert named == ([] if figure is None else [
            f"'Ada Example' is in a figure ({figure}) of main.tex, and the journal's review is "
            "double-blind"]), placed


@needs_pdftotext
def test_a_latex_picture_is_found_with_pdf_after_its_name(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A paper read by its editor or a referee"): a
    LaTeX paper's picture placed by its name alone is found with `.pdf` after it, and the
    text the PDF draws is read; placed by a name no file has with either ending, nothing
    is."""
    monkeypatch.syspath_prepend(str(Path(__file__).parent))
    from proof_pdf import typeset

    (tmp_path / "plot.pdf").write_bytes(typeset(["Drawn by Ada Example"], columns=1))
    for name, named in (("plot", ["'Ada Example' is in a figure (plot.pdf) of main.tex, and the "
                                  "journal's review is double-blind"]), ("chart", [])):  # fmt: skip
        (tmp_path / "main.tex").write_text(
            f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}Of 40, 12."
            f"{BS}includegraphics{{{name}}}\n{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
        _code, report, _err = audited(capsys, str(tmp_path / "main.tex"), "--journal",
                                      str(profile(tmp_path, blinding="double")), "--authors",
                                      str(authors_file(tmp_path)))  # fmt: skip
        assert [f["message"] for f in report["findings"]
                if f["code"] == "blind-document-names-author"] == named, name


@pytest.mark.parametrize("placed", [f"{BS}includesvg{{flow}}", f"{BS}includegraphics{{flow.v2}}",
                                    f"{BS}includegraphics*[width=3cm]{{flow.v2}}",
                                    f"{BS}includegraphics{{flow}}"])
def test_a_picture_placed_by_includesvg_or_with_a_dot_in_its_name_is_searched(
    tmp_path: Path, capsys, placed: str
) -> None:
    """Round 2, note 6: `\\includesvg` was not read, and a name with a dot in it was tried
    only as written."""
    name = "flow.svg" if "{flow}" in placed else "flow.v2.svg"
    (tmp_path / name).write_text(svg("Drawn by Ada Example"), encoding="utf-8")
    (tmp_path / "flow").write_text("no picture", encoding="utf-8")
    (tmp_path / "main.tex").write_text(
        f"{BS}documentclass{{article}}{BS}begin{{document}}{BS}section{{Results}}Of 40, 12."
        f"{placed}\n{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    code, report, _err = audited(capsys, str(tmp_path / "main.tex"), "--journal",
                                 str(profile(tmp_path, blinding="double")), "--authors",
                                 str(authors_file(tmp_path)), "--strict")  # fmt: skip
    named = [f for f in report["findings"] if f["code"] == "blind-document-names-author"]
    assert [f["message"].split(" is in ")[1].split(" of ")[0] for f in named] == [
        f"a figure ({name})"], named
    assert code == 1
