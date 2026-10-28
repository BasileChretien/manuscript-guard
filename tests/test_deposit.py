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
    assert "check --submission" in captured.err
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
    assert "`check --submission`: passed" in markdown
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
def test_gh_pages_is_the_page_and_the_commands_and_pushes_nothing(project: Path, capsys) -> None:
    ready(project)
    assert deposit(project, "gh-pages", "release") == 0
    said = capsys.readouterr().out
    root = folder(project, "gh-pages-release")
    assert contents(root) == {"index.html", ".nojekyll", "SHA256SUMS"}
    assert (root / ".nojekyll").read_bytes() == b""
    assert "<html" in (root / "index.html").read_text(encoding="utf-8")
    assert "git push origin gh-pages" in said
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


def test_the_medrxiv_bundle_and_its_sheet(project: Path, monkeypatch) -> None:
    from manuscript_guard.deposit import preprint

    built = project / "build" / "manuscript.docx"
    built.parent.mkdir(parents=True, exist_ok=True)
    built.write_bytes(b"PK docx")
    monkeypatch.setattr(preprint, "_documents", lambda _project: [(built, "the manuscript")])
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
    assert "## Data availability\n\nAs the manuscript writes it:" in sheet
    assert "Ada Example, whose e-mail address authors.yaml records" in sheet
    assert "@" not in sheet
    assert (project / "build" / "deposit" / "medrxiv-preprint.zip").is_file()


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
