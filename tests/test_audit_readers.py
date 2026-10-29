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
BS = chr(92)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def profile(tmp_path: Path, *, blinding: str = "single", more: str = "") -> Path:
    """A journal profile an editor keeps: a 40-word main text, the four sections, a Funding
    statement under its own heading, British English, one rule no gate checks."""
    path = tmp_path / "journal.yaml"
    path.write_text(
        "schema: manuscript-guard/journal/1\n"
        "name: The Journal of Examples\n"
        "source_url: https://example.org/authors\n"
        f"retrieved_on: {date.today().isoformat()}\n"
        "english_variant: en-GB\n"
        f"blinding: {blinding}\n"
        "limits:\n  main_text_words: 40\n"
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
    assert "Not checked here (they read a project's records):" in text


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
    journal = profile(tmp_path, more=more)
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, PAPER + statement)),
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
