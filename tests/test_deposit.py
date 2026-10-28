"""`manuscript-guard deposit`: a bundle staged for a target in build/deposit/, and nothing
sent anywhere.

Each test asks of the folder and the archive as written, or of what the command refused, as
`test_package.py` does. The custodian's checks come first: a small count, a restricted input
and a bundle the custodian restricting sending has not signed off each stop it, with nothing
written. The preprint bundles are made with the LaTeX build and the Word build stood in for
where a test is about what the bundle holds, so that they need neither TeX nor pandoc; no
test compiles LaTeX, and none opens a connection.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml
from test_package import (
    _custodian,
    _git,
    _small_cell,
    contents,
    declare_input,
    edit_fragment,
    paper,
    ready,
    set_paper,
)

from manuscript_guard.cli import main

PANDOC = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
GIT = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def deposit(root: Path, target: str, bundle: str, *options: str) -> int:
    return main(["deposit", str(root), "--target", target, "--bundle", bundle, *options])


def folder(root: Path, name: str) -> Path:
    return root / "build" / "deposit" / name


def nothing_written(root: Path) -> bool:
    home = root / "build" / "deposit"
    return not home.exists() or not any(home.iterdir())


def unfrozen(root: Path) -> Path:
    """The example before its first results were kept: no plan.frozen.yaml."""
    (root / "design" / "plan.frozen.yaml").unlink()
    return root


def frozen_on(root: Path) -> str:
    return json.loads((root / "design" / "plan.frozen.yaml").read_text(encoding="utf-8"))[
        "frozen_at"
    ]


def minimum(root: Path, **custodian: object) -> None:
    document = paper(root)
    document["custodian"] = {**document.get("custodian", {}), **custodian}
    set_paper(root, document)


# ------------------------------------------------------------------ targets and bundles


@pytest.mark.parametrize(
    ("target", "bundle"),
    [
        ("arxiv", "preregistration"),
        ("arxiv", "release"),
        ("medrxiv", "release"),
        ("medrxiv", "preregistration"),
        ("gh-pages", "preprint"),
        ("gh-pages", "preregistration"),
        ("zenodo", "preprint"),
        ("osf", "preprint"),
    ],
)
def test_a_target_and_a_bundle_that_do_not_go_together_are_refused(
    project: Path, capsys, target: str, bundle: str
) -> None:
    assert deposit(project, target, bundle) == 2
    said = capsys.readouterr().err
    assert f"--target {target} does not take --bundle {bundle}" in said
    assert nothing_written(project)


def test_an_unknown_target_is_refused_by_the_parser(project: Path) -> None:
    with pytest.raises(SystemExit) as stopped:
        deposit(project, "figshare", "release")
    assert stopped.value.code == 2


# ------------------------------------------------------------------ the pre-registration


def test_the_preregistration_holds_the_plan_its_records_and_how_to_cite_it(project: Path) -> None:
    assert deposit(unfrozen(project), "zenodo", "preregistration") == 0
    held = contents(folder(project, "zenodo-preregistration"))
    assert held == {"design/plan.md", "design/data_dictionary.yaml", "design/data_dictionary.csv",
                    "README.md", "CITATION.cff", ".zenodo.json", "SHA256SUMS"}  # fmt: skip
    root = folder(project, "zenodo-preregistration")
    assert (root / "design" / "plan.md").read_bytes() == \
        (project / "design" / "plan.md").read_bytes()  # fmt: skip
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "deposited before any results were written" in readme
    assert "not an entry in a registry" in readme
    citation = yaml.safe_load((root / "CITATION.cff").read_text(encoding="utf-8"))
    assert citation["title"].startswith("Analysis plan for")
    assert "doi" not in citation
    record = json.loads((root / ".zenodo.json").read_text(encoding="utf-8"))
    assert record["upload_type"] == "publication"
    assert "@" not in (root / "CITATION.cff").read_text(encoding="utf-8")
    # SHA256SUMS names every other file by its digest.
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert (project / "build" / "deposit" / "zenodo-preregistration.zip").is_file()


def test_a_plan_results_were_written_from_is_no_preregistration(project: Path, capsys) -> None:
    assert deposit(project, "osf", "preregistration") == 1
    said = capsys.readouterr().err
    assert "is no pre-registration now" in said and "--retrospective" in said
    assert nothing_written(project)


def test_a_retrospective_plan_is_labelled_as_one(project: Path) -> None:
    why = "The protocol was written before the analysis and not deposited then."
    assert deposit(project, "osf", "preregistration", "--retrospective", why) == 0
    root = folder(project, "osf-preregistration")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert (f"Analysis plan, deposited after results were first written on {frozen_on(project)}"
            in readme)  # fmt: skip
    assert "It is not a pre-registration." in readme and why in readme
    assert "design/plan.frozen.yaml" in contents(root)
    record = json.loads((root / ".zenodo.json").read_text(encoding="utf-8"))
    assert "is not a pre-registration" in record["description"]


def test_retrospective_with_no_results_written_is_refused(project: Path, capsys) -> None:
    assert deposit(unfrozen(project), "zenodo", "preregistration", "--retrospective", "x") == 2
    assert "no results have been" in capsys.readouterr().err
    assert nothing_written(project)


def test_the_archives_are_the_same_bytes_twice_and_from_another_folder(
    project: Path, tmp_path: Path
) -> None:
    unfrozen(project)
    archive = project / "build" / "deposit" / "zenodo-preregistration.zip"
    assert deposit(project, "zenodo", "preregistration") == 0
    first = archive.read_bytes()
    assert deposit(project, "zenodo", "preregistration") == 0
    assert archive.read_bytes() == first
    elsewhere = tmp_path / "elsewhere" / "moved"
    shutil.copytree(project, elsewhere, ignore=shutil.ignore_patterns("build"))
    assert deposit(elsewhere, "zenodo", "preregistration") == 0
    assert (elsewhere / "build" / "deposit" / "zenodo-preregistration.zip").read_bytes() == first
    with zipfile.ZipFile(archive) as opened:
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in opened.infolist())


def test_the_tar_is_the_same_bytes_and_says_nothing_of_who_or_when() -> None:
    from manuscript_guard.deposit.archive import tar_bytes

    members = [("b.tex", b"\\documentclass{article}\n"), ("a.bbl", b"\\begin{thebibliography}")]
    made = tar_bytes(members)
    assert made == tar_bytes(list(reversed(members)))
    assert made[4:8] == b"\0\0\0\0"  # the gzip stream's date
    with tarfile.open(fileobj=io.BytesIO(made), mode="r:gz") as opened:
        infos = opened.getmembers()
    assert [info.name for info in infos] == ["a.bbl", "b.tex"]
    assert all((i.mtime, i.uid, i.gid, i.uname, i.gname, i.mode) == (0, 0, 0, "", "", 0o644)
               for i in infos)  # fmt: skip


# ------------------------------------------------------------------ the custodian first


def test_a_small_count_in_the_results_stops_a_release_before_anything_is_built(
    project: Path, capsys
) -> None:
    ready(project)
    minimum(project, minimum_cell_count=5)
    edit_fragment(project, _small_cell)
    assert deposit(project, "zenodo", "release") == 1
    said = capsys.readouterr().out
    assert "below the data custodian's minimum of 5" in said
    assert "Nothing is built" in said
    assert nothing_written(project)
    assert not (project / "build" / "package").exists()


def test_a_plan_carries_no_results_and_their_counts_do_not_stop_it(project: Path) -> None:
    unfrozen(project)
    minimum(project, minimum_cell_count=5)
    edit_fragment(project, _small_cell)
    assert deposit(project, "zenodo", "preregistration") == 0


def test_a_small_count_the_manuscript_binds_stops_a_preprint(project: Path, capsys) -> None:
    minimum(project, minimum_cell_count=100000)
    assert deposit(project, "medrxiv", "preprint") == 1
    said = capsys.readouterr().out
    assert "the data custodian's minimum of 100000" in said
    assert nothing_written(project)


@GIT
def test_a_restricted_input_git_tracks_stops_every_deposit(project: Path, capsys) -> None:
    unfrozen(project)
    declare_input(project, "data/event_terms.txt", restricted=True)
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "x")
    assert deposit(project, "zenodo", "preregistration") == 1
    assert "is declared restricted, and git tracks it" in capsys.readouterr().out
    assert nothing_written(project)


def _restricted_dictionary(root: Path) -> None:
    """The data dictionary declared a restricted input of the analysis: it never goes."""
    digest = hashlib.sha256((root / "design" / "data_dictionary.yaml").read_bytes()).hexdigest()

    def change(document: dict) -> None:
        document["provenance"]["inputs"].append(
            {"path": "design/data_dictionary.yaml", "sha256": digest, "restricted": True}
        )

    edit_fragment(root, change)


def test_a_restricted_input_the_bundle_would_carry_stops_it(project: Path, capsys) -> None:
    _restricted_dictionary(unfrozen(project))
    assert deposit(project, "zenodo", "preregistration") == 1
    said = capsys.readouterr().out
    assert "the analysis declares restricted, and the bundle would deposit it" in said
    assert "design/data_dictionary.yaml" in said
    assert nothing_written(project)


def test_a_custodian_who_restricts_sending_signs_the_bundle_as_it_stands(
    project: Path, capsys
) -> None:
    unfrozen(project)
    _custodian(project)
    minimum(project, restricts_sending=True)
    assert deposit(project, "zenodo", "preregistration") == 1
    said = capsys.readouterr().out
    assert "restricts where the paper's files may be sent" in said
    assert "--finding DEPOSIT/custodian/zenodo/preregistration" in said
    assert nothing_written(project)
    # A dry run lists what the custodian would sign, and is refused as the deposit is.
    assert deposit(project, "zenodo", "preregistration", "--dry-run") == 1
    assert "in   design/plan.md" in capsys.readouterr().out
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/zenodo/preregistration"]) == 0  # fmt: skip
    assert deposit(project, "zenodo", "preregistration") == 0, capsys.readouterr().out
    # Another target is another place the files go, signed off apart.
    assert deposit(project, "zenodo-sandbox", "preregistration") == 1
    # What was signed is the list of files and their digests.
    plan = project / "design" / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "\nA change.\n", encoding="utf-8")
    shutil.rmtree(project / "build" / "deposit")
    assert deposit(project, "zenodo", "preregistration") == 1
    assert nothing_written(project)


def test_a_retrospective_plan_is_signed_off_with_its_reason(project: Path, capsys) -> None:
    _custodian(project)
    minimum(project, restricts_sending=True)
    why = "Deposited at the journal's request."
    assert deposit(project, "osf", "preregistration", "--retrospective", why) == 1
    assert "--retrospective" in capsys.readouterr().out
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/osf/preregistration"]) == 1  # fmt: skip
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/osf/preregistration", "--retrospective", why]) == 0
    assert deposit(project, "osf", "preregistration", "--retrospective", why) == 0


# ------------------------------------------------------------------ the release


def test_a_release_is_refused_while_the_submission_check_fails(project: Path, capsys) -> None:
    ready(project)
    path = project / "results" / "01_disproportionality.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"0.05"', '"0.050"'),
                    encoding="utf-8")  # fmt: skip
    assert deposit(project, "zenodo", "release") == 1
    captured = capsys.readouterr()
    assert "has been modified since the analysis" in captured.out
    assert "check --stage submission" in captured.err
    assert nothing_written(project)
    assert deposit(project, "gh-pages", "release") == 1


@PANDOC
def test_the_release_is_the_package_with_its_page_and_how_it_was_checked(project: Path) -> None:
    assert deposit(ready(project), "zenodo", "release") == 0
    root = folder(project, "zenodo-release")
    held = contents(root)
    for wanted in ("results/01_disproportionality.json", "analysis/01_disproportionality.py",
                   "ro-crate-metadata.json", "ro-crate-preview.html", "index.html",
                   "RELATIONS.md", "CITATION.cff", ".zenodo.json", "README.md", "BOUND.md",
                   "MANIFEST.yaml", "SHA256SUMS", "VERIFICATION.md", "VERIFICATION.json",
                   "design/data_dictionary.csv", "checklist-DEMO-OBS.md"):  # fmt: skip
        assert wanted in held, wanted
    assert not held & {"authors.yaml", "approvals", "figures/forest.review.yaml"}
    record = json.loads((root / "VERIFICATION.json").read_text(encoding="utf-8"))
    assert record["check"]["passed"] is True
    assert record["check"]["gates"]["G1"]["failing"] == 0
    assert set(record["digests"]) == {"document_sha256", "front_sha256", "results_sha256"}
    assert [a["author"] for a in record["approvals"]] == ["Ada Example", "Blaise Sample"]
    assert {d["dimension"] for d in record["assurance"]} >= {"computational reproducibility"}
    markdown = (root / "VERIFICATION.md").read_text(encoding="utf-8")
    assert "`check --stage submission`: passed" in markdown
    # No reviewer is named who is not an author, as on the companion page.
    for text in (markdown, json.dumps(record)):
        assert "claude-opus-5" not in text and "Claude Code" not in text
    for line in (root / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest


@PANDOC
def test_the_release_is_the_same_bytes_twice(project: Path) -> None:
    ready(project)
    archive = project / "build" / "deposit" / "zenodo-release.zip"
    assert deposit(project, "zenodo", "release") == 0
    first = archive.read_bytes()
    assert deposit(project, "zenodo", "release") == 0
    assert archive.read_bytes() == first


@PANDOC
@GIT
def test_a_signed_release_stays_signed_in_a_committed_project(project: Path, capsys) -> None:
    """MANIFEST.yaml names the commit and whether the tree is clean, and the sign-off is a
    file written into the tree: what the custodian signs leaves it out, as `package` does,
    so that signing does not stale the sign-off it writes (round 1 of #460)."""
    ready(project)
    _custodian(project)
    minimum(project, restricts_sending=True)
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "x")
    assert deposit(project, "zenodo", "release") == 1
    assert "--finding DEPOSIT/custodian/zenodo/release" in capsys.readouterr().out
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/zenodo/release"]) == 0  # fmt: skip
    assert deposit(project, "zenodo", "release") == 0, capsys.readouterr().out
    assert "MANIFEST.yaml" in contents(folder(project, "zenodo-release"))


@PANDOC
def test_gh_pages_is_the_page_and_the_commands_and_pushes_nothing(project: Path, capsys) -> None:
    ready(project)
    assert deposit(project, "gh-pages", "release") == 0
    said = capsys.readouterr().out
    root = folder(project, "gh-pages-release")
    assert contents(root) == {"index.html", ".nojekyll", "SHA256SUMS"}
    assert (root / ".nojekyll").read_bytes() == b""
    assert "<html" in (root / "index.html").read_text(encoding="utf-8")
    assert "git push origin gh-pages" in said
    # Whether or not the branch is there yet: `--orphan` alone fails once it is.
    assert "git switch gh-pages || git switch --orphan gh-pages" in said
    assert "Nothing has been uploaded or pushed" in said


def test_a_dry_run_lists_and_writes_nothing(project: Path, capsys) -> None:
    assert deposit(unfrozen(project), "zenodo", "preregistration", "--dry-run") == 0
    said = capsys.readouterr().out
    assert "would write build/deposit/zenodo-preregistration/" in said
    assert "design/plan.md" in said and "out  design/data_sources.yaml" in said
    assert nothing_written(project)


# ------------------------------------------------------------------ the preprints


def _fake_latex(root: Path, monkeypatch) -> Path:
    """The submission folder as `pack_latex` writes one, without TeX."""
    from manuscript_guard.build.latex_pack import LatexPack
    from manuscript_guard.deposit import preprint

    staged = root / "build" / "latex" / "submission"
    staged.mkdir(parents=True)
    for name, text in (("manuscript.tex", "\\documentclass{article}\n"),
                       ("manuscript.bbl", "\\begin{thebibliography}{1}\n"),
                       ("forest.pdf", "%PDF-1.5\n"), ("supplementary.tex", "\\documentclass{x}\n"),
                       ("manuscript.pdf", "%PDF\n")):  # fmt: skip
        (staged / name).write_text(text, encoding="utf-8")
    files = tuple(p for p in sorted(staged.iterdir()) if p.name != "manuscript.pdf")
    packed = LatexPack(staged, files, (staged / "manuscript.pdf",), ())
    monkeypatch.setattr(preprint, "_latex", lambda _project: packed)
    return staged


def _below_submission(root: Path) -> None:
    """A project that passes `check` at its stage and fails `check --stage submission`: a
    reporting item left unanswered, which G5 fails from internal review
    (`checklist-item-unanswered`)."""
    from manuscript_guard.cli import _run_gates

    path = root / "reporting" / "DEMO-OBS.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["items"][0] = {"id": document["items"][0]["id"]}
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")  # fmt: skip
    assert _run_gates(root, stage="drafting")[0].ok
    assert not _run_gates(root, submission=True)[0].ok


@pytest.mark.parametrize("target", ["arxiv", "medrxiv"])
def test_a_preprint_is_refused_while_the_submission_check_fails(
    project: Path, monkeypatch, capsys, target: str
) -> None:
    """A preprint is public, so it is held to the submission's bar, as a release is, and not
    to the project's stage."""
    from manuscript_guard.deposit import preprint

    _fake_latex(project, monkeypatch)
    monkeypatch.setattr(preprint, "_documents", lambda _project: [])
    _below_submission(project)
    assert deposit(project, target, "preprint") == 1
    assert "failing in `check --stage submission`" in capsys.readouterr().err
    assert nothing_written(project)


def test_the_arxiv_bundle_is_the_source_as_a_tar_and_its_sheet(project: Path, monkeypatch) -> None:
    _fake_latex(project, monkeypatch)
    assert deposit(project, "arxiv", "preprint") == 0
    root = folder(project, "arxiv-preprint")
    assert contents(root) == {"manuscript.tex", "manuscript.bbl", "forest.pdf",
                              "arxiv_submission_sheet.md", "SHA256SUMS"}  # fmt: skip
    archive = project / "build" / "deposit" / "arxiv-preprint.tar.gz"
    with tarfile.open(archive, mode="r:gz") as opened:
        assert opened.getnames() == ["forest.pdf", "manuscript.bbl", "manuscript.tex"]
    first = archive.read_bytes()
    sheet = (root / "arxiv_submission_sheet.md").read_text(encoding="utf-8")
    assert "Nothing has been uploaded" in sheet
    assert "at most 1,920 characters" in sheet and "as this sheet names it" in sheet
    assert "`manuscript.bbl`: included" in sheet
    assert f"{len(first):,} bytes compressed" in sheet
    assert "Ada Example, ORCID 0000-0002-1825-0097" in sheet
    assert "The supplement is not in the archive" in sheet
    assert "medRxiv" in sheet and "endorsement" in sheet
    assert deposit(project, "arxiv", "preprint") == 0
    assert archive.read_bytes() == first


def test_an_abstract_longer_than_arxiv_takes_is_said(project: Path, monkeypatch) -> None:
    from manuscript_guard.build import submission

    monkeypatch.setattr(submission, "abstract_text", lambda _project: ("w" * 1921, None))
    _fake_latex(project, monkeypatch)
    assert deposit(project, "arxiv", "preprint") == 0
    sheet = (folder(project, "arxiv-preprint") / "arxiv_submission_sheet.md").read_text("utf-8")
    assert "Length: 1921 characters" in sheet and "This abstract is longer" in sheet


def test_a_markdown_manuscript_without_tex_is_refused_for_arxiv(project: Path, monkeypatch,
                                                                capsys) -> None:  # fmt: skip
    from manuscript_guard.build import latex_out
    from manuscript_guard.build.latex import LatexMissing

    def missing(*_args, **_kwargs):
        raise LatexMissing("latexmk is not on PATH")

    monkeypatch.setattr(latex_out, "build_from_markdown", missing)
    assert deposit(project, "arxiv", "preprint") == 2
    assert "latexmk is not on PATH" in capsys.readouterr().err
    assert nothing_written(project)


def _fake_docx(root: Path, monkeypatch) -> Path:
    from manuscript_guard.deposit import preprint

    built = root / "build" / "manuscript.docx"
    built.parent.mkdir(parents=True, exist_ok=True)
    built.write_bytes(b"PK docx")
    monkeypatch.setattr(preprint, "_documents", lambda _project: [(built, "the manuscript", None)])
    return built


def _sheet(root: Path) -> str:
    """The medRxiv sheet of the project as it stands, asked of the sheet itself, so that an
    edit no gate is asked about at submission can be made first."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.deposit.sheets import medrxiv_sheet

    return medrxiv_sheet(load_project(root)[0], files=[])


def _authors(root: Path, change) -> None:
    path = root / "authors.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")  # fmt: skip


def _statement(root: Path, added: str) -> None:
    path = root / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    at = text.index("this repository. No real patient data")
    path.write_text(text[:at] + f"this repository. {added} " + text[at + len("this repository. "):],
                    encoding="utf-8")  # fmt: skip


@PANDOC
def test_the_data_statement_is_printed_with_its_bindings_filled(project: Path) -> None:
    """As the abstract is: a binding in the statement is its display, never `{{…}}`
    (round 1 of #460)."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.revision import displays
    from manuscript_guard.text.placeholders import substitute

    _statement(project, "The cohort held {{results.cohort.n_reports}} reports.")
    shown = substitute("{{results.cohort.n_reports}}", displays(load_project(project)[0]))
    assert "{{" not in shown
    sheet = _sheet(project)
    said = sheet.split("## Data availability", 1)[1].split("## Licence", 1)[0]
    assert f"The cohort held {shown} reports." in said
    assert "{{" not in said


@PANDOC
def test_a_data_statement_that_cites_is_to_be_copied_from_the_document(project: Path) -> None:
    _statement(project, "The method is described elsewhere [@fictionalClassSignal2019].")
    said = _sheet(project).split("## Data availability", 1)[1].split("## Licence", 1)[0]
    assert "Copy it from the document" in said
    assert "@fictional" not in said and "[" not in said


def test_the_sheet_says_each_author_as_authors_yaml_records_them(project: Path) -> None:
    """An accented name as it is spelt, several affiliations, no ORCID, an affiliation id
    `affiliations` does not list, and two corresponding authors (round 1 of #460)."""

    def change(document: dict) -> None:
        ada, blaise = document["authors"]
        ada["given"] = "Hélène"
        ada["affiliations"] = ["uni", "chu", "nowhere"]
        blaise.pop("orcid")
        blaise["corresponding"] = True

    _authors(project, change)
    sheet = _sheet(project)
    assert ("- Hélène Example, ORCID 0000-0002-1825-0097; Department of Clinical "
            "Pharmacology") in sheet  # fmt: skip
    line = next(row for row in sheet.splitlines() if row.startswith("- Hélène Example"))
    assert "Regional Pharmacovigilance Centre" in line
    assert "affiliation `nowhere`: not recorded" in line
    assert "- Blaise Sample, ORCID not recorded; Regional Pharmacovigilance" in sheet
    assert ("authors.yaml marks 2 authors `corresponding: true`, Hélène Example, Blaise "
            "Sample") in sheet  # fmt: skip
    assert "no single author" not in sheet


def _medrxiv(root: Path, monkeypatch):
    from manuscript_guard.contracts import load_project
    from manuscript_guard.deposit import preprint

    _fake_docx(root, monkeypatch)
    return preprint.medrxiv(load_project(root)[0])


def test_a_figure_medrxiv_is_not_sent_is_named(project: Path, monkeypatch) -> None:
    """A .jpg beside the document is named as left out, not dropped (round 1 of #460)."""
    shutil.copyfile(project / "figures" / "forest.png", project / "figures" / "photo.jpg")
    made = _medrxiv(project, monkeypatch)
    assert "figures/photo.jpg" not in {entry.path for entry in made.entries}
    assert "figures/photo.jpg" in {held.path for held in made.withheld}


def test_a_linked_figure_is_withheld_as_the_package_withholds_one(
    project: Path, monkeypatch, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere.png"
    shutil.copyfile(project / "figures" / "forest.png", outside)
    try:
        (project / "figures" / "linked.png").symlink_to(outside)
    except OSError:
        pytest.skip("this system makes no symbolic link without a privilege")
    made = _medrxiv(project, monkeypatch)
    assert "figures/linked.png" not in {entry.path for entry in made.entries}
    assert [held.why for held in made.withheld if held.path == "figures/linked.png"] == \
        ["a link, whose target is outside what a bundle holds"]  # fmt: skip


def test_the_medrxiv_bundle_and_its_sheet(project: Path, monkeypatch) -> None:
    _fake_docx(project, monkeypatch)
    assert deposit(project, "medrxiv", "preprint") == 0
    root = folder(project, "medrxiv-preprint")
    held = contents(root)
    assert {"manuscript.docx", "figures/forest.png", "checklist-DEMO-OBS.md", "declarations.md",
            "credit-statement.md", "medrxiv_submission_sheet.md", "SHA256SUMS"} <= held
    assert "figures/forest.py" not in held
    sheet = (root / "medrxiv_submission_sheet.md").read_text(encoding="utf-8")
    assert "## Competing interests\n\n- Ada Example: None declared." in sheet
    assert "## Funding\n\n- Ada Example: not recorded" in sheet
    assert "not recorded: the project keeps no record of ethics approval" in sheet
    assert "not recorded: paper.yaml lists no registration" in sheet
    assert "DEMO-OBS; the completed checklist(s): checklist-DEMO-OBS.md" in sheet
    if shutil.which("pandoc") is not None:
        assert "## Data availability\n\nAs the document prints it:" in sheet
    assert "Ada Example, whose e-mail address authors.yaml records" in sheet
    # That an address is recorded is said, and the address is never printed.
    assert "ada.example@invalid.example" not in sheet
    assert (project / "build" / "deposit" / "medrxiv-preprint.zip").is_file()


@PANDOC
def test_a_medrxiv_bundle_signed_off_is_the_same_bytes_when_deposited(project: Path,
                                                                     capsys) -> None:  # fmt: skip
    """The custodian signs the bytes that go out: the .docx is built at a fixed date, so the
    build `sign` makes and the one `deposit` makes are one file (round 1 of #460)."""
    _custodian(project)
    minimum(project, restricts_sending=True)
    assert deposit(project, "medrxiv", "preprint") == 1
    assert "--finding DEPOSIT/custodian/medrxiv/preprint" in capsys.readouterr().out
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/medrxiv/preprint"]) == 0  # fmt: skip
    assert deposit(project, "medrxiv", "preprint") == 0, capsys.readouterr().out
    first = (folder(project, "medrxiv-preprint") / "manuscript.docx").read_bytes()
    assert deposit(project, "medrxiv", "preprint") == 0
    assert (folder(project, "medrxiv-preprint") / "manuscript.docx").read_bytes() == first
    with zipfile.ZipFile(folder(project, "medrxiv-preprint") / "manuscript.docx") as opened:
        assert {info.date_time for info in opened.infolist()} == {(1980, 1, 1, 0, 0, 0)}


def test_a_compiled_pdf_is_signed_off_by_what_it_is_compiled_from(project: Path, monkeypatch,
                                                                  capsys) -> None:  # fmt: skip
    """The author's TeX may write the clock into a PDF, so a LaTeX manuscript's PDF is signed
    by the folder it is compiled from and the tool's version, not by its bytes."""
    from manuscript_guard.deposit import preprint

    staged = _fake_latex(project, monkeypatch)
    packed = preprint._latex(project)
    calls = []

    def compiled(_project):
        calls.append(1)
        (staged / "manuscript.pdf").write_bytes(f"%PDF compiled at call {len(calls)}\n".encode())
        return packed

    monkeypatch.setattr(preprint, "_latex", compiled)
    monkeypatch.setattr(preprint, "_is_latex", lambda _project: True)
    _custodian(project)
    minimum(project, restricts_sending=True)
    assert deposit(project, "medrxiv", "preprint") == 1
    capsys.readouterr()
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/medrxiv/preprint"]) == 0  # fmt: skip
    assert deposit(project, "medrxiv", "preprint") == 0, capsys.readouterr().out
    assert len(calls) == 3
    # What it is compiled from is what was signed.
    (staged / "manuscript.tex").write_text("\\documentclass{article}\n% changed\n",
                                          encoding="utf-8")  # fmt: skip
    assert deposit(project, "medrxiv", "preprint") == 1


def test_the_build_stamp_is_dated_as_the_rest_of_the_document(tmp_path: Path) -> None:
    from manuscript_guard.roundtrip import stamp_into

    document = tmp_path / "made.docx"
    with zipfile.ZipFile(document, "w") as out:
        out.writestr(zipfile.ZipInfo("[Content_Types].xml", date_time=(1980, 1, 1, 0, 0, 0)),
                     "<Types></Types>")  # fmt: skip
        out.writestr(zipfile.ZipInfo("_rels/.rels", date_time=(1980, 1, 1, 0, 0, 0)),
                     "<Relationships></Relationships>")  # fmt: skip
    stamp_into(document, "0" * 64)
    with zipfile.ZipFile(document) as opened:
        assert {info.date_time for info in opened.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        assert "docProps/custom.xml" in opened.namelist()


def test_a_restricted_input_copied_under_another_name_is_caught_by_its_bytes(
    project: Path, monkeypatch
) -> None:
    """`pack_latex` copies each file the build read into one folder, under a name of its own:
    a restricted input among them is the same bytes (round 1 of #460)."""
    from manuscript_guard.contracts import load_namespace, load_project
    from manuscript_guard.deposit.plan import copied
    from manuscript_guard.deposit.preflight import restricted_entries

    _restricted_dictionary(project)
    staged = _fake_latex(project, monkeypatch)
    shutil.copyfile(project / "design" / "data_dictionary.yaml", staged / "table-input.yaml")
    loaded = load_project(project)[0]
    results = load_namespace(loaded)[1]
    entries = (copied(staged / "table-input.yaml", "table-input.yaml", "the source"),
               copied(staged / "manuscript.tex", "manuscript.tex", "the source"))  # fmt: skip
    assert [f.message.split(" ")[0] for f in restricted_entries(loaded, results, entries)] == \
        ["table-input.yaml"]  # fmt: skip


def test_retrospective_is_refused_with_a_bundle_that_holds_no_plan(project: Path,
                                                                    capsys) -> None:  # fmt: skip
    for target, bundle in (("zenodo", "release"), ("arxiv", "preprint")):
        assert deposit(project, target, bundle, "--retrospective", "why") == 2
        said = capsys.readouterr()
        assert f"--bundle {bundle} deposits no plan" in said.err
        assert "sign --as" not in said.out
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "DEPOSIT/custodian/zenodo/release", "--retrospective", "why"]) == 2
    assert "deposits no plan" in capsys.readouterr().err
    assert nothing_written(project)


@PANDOC
def test_a_markdown_manuscript_goes_to_medrxiv_as_its_documents_built_offline(
    project: Path,
) -> None:
    assert deposit(project, "medrxiv", "preprint") == 0
    held = contents(folder(project, "medrxiv-preprint"))
    assert {"manuscript.docx", "supplementary.docx"} <= held
    with zipfile.ZipFile(folder(project, "medrxiv-preprint") / "manuscript.docx") as opened:
        assert "word/document.xml" in opened.namelist()


# ------------------------------------------------------------------ nothing is sent


def test_nothing_is_sent_the_command_opens_no_connection(project: Path, monkeypatch) -> None:
    import socket

    def refused(*_args, **_kwargs):
        raise AssertionError("deposit opened a connection")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    assert deposit(unfrozen(project), "zenodo", "preregistration") == 0
