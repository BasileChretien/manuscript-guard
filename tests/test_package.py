"""The package an author deposits: the code, the results and what they ran with, and never
the data a custodian keeps.

What the package holds is a list the tool decides, and what it leaves out is a list it
prints, so each test asks of the package as written, the folder and the .zip, rather than
of the plan that should have made it: a file the plan said it withheld and the writer copied
anyway would pass a test of the plan.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import write_digest

MIT = "MIT License\n\nCopyright (c) 2026 The authors\n\nPermission is hereby granted.\n"


def ready(root: Path) -> Path:
    """The example as a project that may be packaged: its paper.yaml declares the licence
    and what may be shared, and a licence file is beside it, as the repository's is."""
    (root / "LICENSE").write_text(MIT, encoding="utf-8")
    return root


def paper(root: Path) -> dict:
    return yaml.safe_load((root / "paper.yaml").read_text(encoding="utf-8"))


def set_paper(root: Path, document: dict) -> None:
    (root / "paper.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def with_package(root: Path, **settings: object) -> None:
    document = paper(root)
    document["package"] = {**document.get("package", {}), **settings}
    set_paper(root, document)


def built(root: Path) -> Path:
    """The folder of the one package `package` wrote."""
    (found,) = [path for path in (root / "build" / "package").iterdir() if path.is_dir()]
    return found


def contents(folder: Path) -> set[str]:
    return {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}


def fragment(root: Path) -> Path:
    return root / "results" / "01_disproportionality.json"


def edit_fragment(root: Path, change) -> None:
    """Change the fragment and sign it again, so that G1 is satisfied and only the package
    has anything to say."""
    path = fragment(root)
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(path)


def declare_input(root: Path, relative: str, **flags: bool) -> None:
    def change(document: dict) -> None:
        for record in document["provenance"]["inputs"]:
            if record["path"] == relative:
                record.update(flags)

    edit_fragment(root, change)


def refused(root: Path, **options: bool) -> set[str]:
    """The codes of what stops the package, as the plan has them; the command prints their
    messages, and exits 1."""
    from manuscript_guard.deposit import plan_package

    loaded, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(loaded)
    return {f.code for f in plan_package(loaded, results, **options).report.failures}


# ------------------------------------------------------------------ the example, deposited


def test_the_example_is_packaged_and_reproduces_from_the_unpacked_zip(
    project: Path, tmp_path: Path, capsys
) -> None:
    """The whole point: someone with the .zip and nothing else runs `verify` in it, and the
    analysis gives the numbers the paper prints."""
    from manuscript_guard.verify import to_report, verify

    assert main(["package", str(ready(project))]) == 0, capsys.readouterr().out
    folder = built(project)
    archive = folder.with_suffix(".zip")
    assert archive.is_file()

    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(archive) as opened:
        opened.extractall(unpacked)
    (root,) = list(unpacked.iterdir())
    assert root.name == folder.name
    assert contents(root) == contents(folder)

    loaded, report = load_project(root)
    assert report.ok, report.render(root)
    result = verify(loaded)
    assert result.ok and not result.skipped, to_report(result).render(root)
    assert sum(len(c.agreed) for c in result.comparisons) > 10


def test_the_package_holds_what_reproduces_the_results_and_nothing_of_the_rest(
    project: Path,
) -> None:
    assert main(["package", str(ready(project))]) == 0
    held = contents(built(project))
    for wanted in (
        "analysis/00_simulate.py",
        "analysis/01_disproportionality.py",
        "results/01_disproportionality.json",
        "results/01_disproportionality.json.sha256",
        "figures/forest.py",
        "figures/forest.svg",
        "figures/forest.render.json",
        "design/plan.md",
        "design/plan.frozen.yaml",
        "data/reports.csv",  # synthetic
        "data/event_terms.txt",  # listed in package.share
        "literature/ledger.yaml",
        "literature/references.bib",
        "LICENSE",
        "README.md",
        "CITATION.cff",
        "BOUND.md",
        "INPUTS.md",
        "MANIFEST.yaml",
        "SHA256SUMS",
        "paper.yaml",
    ):
        assert wanted in held, wanted
    for path in held:
        assert not path.startswith(("literature/sources/", "review/", "build/", "approvals/"))
        assert not path.startswith(("manuscript/", "profiles/", "reporting/"))
        assert not path.endswith(".review.yaml"), path
    assert "authors.yaml" not in held
    assert "methods.lock" not in held


def test_a_cited_works_stored_copy_is_never_packaged(project: Path) -> None:
    """literature/sources/ holds copies of published papers, most of them someone else's to
    distribute: the ledger quotes them and goes in, the copies do not."""
    sources = project / "literature" / "sources"
    assert any(sources.iterdir())
    assert main(["package", str(ready(project)), "--with-manuscript"]) == 0
    held = contents(built(project))
    assert not [path for path in held if path.startswith("literature/sources")]
    assert "literature/ledger.yaml" in held


def test_every_file_is_named_by_its_digest_in_the_manifest(project: Path) -> None:
    assert main(["package", str(ready(project))]) == 0
    folder = built(project)
    sums = {}
    for line in (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    assert set(sums) == contents(folder) - {"SHA256SUMS"}
    for name, digest in sums.items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name

    manifest = yaml.safe_load((folder / "MANIFEST.yaml").read_text(encoding="utf-8"))
    listed = {entry["file"]: entry for entry in manifest["files"]}
    assert set(listed) == contents(folder) - {"SHA256SUMS", "MANIFEST.yaml"}
    for name, entry in listed.items():
        data = (folder / name).read_bytes()
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["bytes"] == len(data)
    assert manifest["checks"] == "passed"


def test_the_zip_is_made_the_same_twice(project: Path) -> None:
    """A deposit can be checked against the folder it came from, and two packages of an
    unchanged project are one file: no clock goes into the archive."""
    assert main(["package", str(ready(project))]) == 0
    first = built(project).with_suffix(".zip").read_bytes()
    assert main(["package", str(project)]) == 0
    assert built(project).with_suffix(".zip").read_bytes() == first


def test_a_dry_run_lists_and_writes_nothing(project: Path, capsys) -> None:
    assert main(["package", str(ready(project)), "--dry-run"]) == 0
    said = capsys.readouterr().out
    assert "  in   analysis/01_disproportionality.py" in said
    assert "  out  literature/sources/" in said
    assert not (project / "build" / "package").exists()


# ------------------------------------------------------------------------- the inputs


def test_a_restricted_input_is_left_out_and_listed_with_how_to_request_it(project: Path) -> None:
    ready(project)
    with_package(project, share=[], request="Apply to the Example Data Office.")
    declare_input(project, "data/event_terms.txt", restricted=True)
    assert main(["package", str(project)]) == 0
    folder = built(project)
    assert "data/event_terms.txt" not in contents(folder)
    listed = (folder / "INPUTS.md").read_text(encoding="utf-8")
    recorded = (project / "data" / "event_terms.txt").read_bytes()
    assert "data/event_terms.txt" in listed
    assert hashlib.sha256(recorded).hexdigest() in listed
    assert "restricted" in listed
    assert "Apply to the Example Data Office" in listed
    manifest = yaml.safe_load((folder / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert {"path": "data/event_terms.txt", "why": "declared restricted"} in manifest["withheld"]


def test_an_input_neither_synthetic_nor_shared_is_withheld(project: Path) -> None:
    """Fail closed: the author says what may be deposited, and nothing else is."""
    ready(project)
    with_package(project, share=[], request="Write to the corresponding author.")
    assert main(["package", str(project)]) == 0
    held = contents(built(project))
    assert "data/event_terms.txt" not in held
    assert "data/reports.csv" in held  # declared synthetic


def test_a_withheld_input_with_no_way_to_request_it_is_refused(project: Path, capsys) -> None:
    ready(project)
    with_package(project, share=[])
    assert main(["package", str(project)]) == 1
    assert "says nothing of how to obtain them" in capsys.readouterr().out
    assert refused(project) == {"package-request-missing"}
    assert not (project / "build" / "package").exists()


def test_sharing_a_restricted_input_is_refused(project: Path, capsys) -> None:
    ready(project)
    declare_input(project, "data/event_terms.txt", restricted=True)
    assert main(["package", str(project)]) == 1
    assert "which the analysis declares restricted" in capsys.readouterr().out
    # It is withheld as well, and nothing says how to obtain it.
    assert refused(project) == {"package-share-restricted", "package-request-missing"}


def test_sharing_what_no_analysis_read_is_refused(project: Path, capsys) -> None:
    ready(project)
    with_package(project, share=["data/event_terms.txt", "data/event_term.txt"])
    assert main(["package", str(project)]) == 1
    assert "data/event_term.txt, which no analysis declares" in capsys.readouterr().out
    assert refused(project) == {"package-share-unknown"}


def test_a_shared_input_that_is_a_pointer_is_withheld(project: Path) -> None:
    """A Git LFS pointer in a clone where the data were not fetched is not the data."""
    ready(project)
    terms = project / "data" / "event_terms.txt"
    data = terms.read_bytes()
    terms.write_bytes(
        b"version https://git-lfs.github.com/spec/v1\n"
        + f"oid sha256:{hashlib.sha256(data).hexdigest()}\nsize {len(data)}\n".encode()
    )
    with_package(project, request="Fetch it with git lfs pull.")
    assert main(["package", str(project)]) == 0
    folder = built(project)
    assert "data/event_terms.txt" not in contents(folder)
    assert "not fetched" in (folder / "INPUTS.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------- what git tracks


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
         "-c", "core.fsmonitor=false", *args],
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_file_git_does_not_track_is_withheld(project: Path) -> None:
    """In a repository, what the author committed is what goes: a file beside the scripts
    that git was never given may be data kept out of it on purpose."""
    ready(project)
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "x")
    (project / "analysis" / "extract.csv").write_text("id,age\n1,40\n", encoding="utf-8")
    assert main(["package", str(project), "--skip-checks"]) == 0
    folder = built(project)
    assert "analysis/extract.csv" not in contents(folder)
    assert "analysis/01_disproportionality.py" in contents(folder)
    manifest = yaml.safe_load((folder / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert {"path": "analysis/extract.csv", "why": "git does not track it"} in manifest["withheld"]


# --------------------------------------------------------------------- the custodian


def test_the_example_holds_no_count_the_minimum_forbids(project: Path) -> None:
    """The reading of counts finds none in a fragment that has none: a parameter of 3, a
    level of nought dropped, a share and a ratio are no small counts."""
    ready(project)
    document = paper(project)
    document["custodian"] = {"minimum_cell_count": 5}
    set_paper(project, document)
    assert main(["package", str(project)]) == 0


def _small_value(document: dict) -> None:
    document["values"]["cohort.n_tiny"] = {"value": 3, "display": "<5"}


def _small_cell(document: dict) -> None:
    document["tables"]["baseline"]["rows"][2][1] = "3 (0.7)"


def _small_level(document: dict) -> None:
    document["models"]["adjusted"]["events_by_level"]["sex"]["F"] = 2


def _small_missing(document: dict) -> None:
    document["variables"]["sex"]["observed"]["missing"] = 1


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (_small_value, "cohort.n_tiny"),
        (_small_cell, "baseline"),
        (_small_level, "events_by_level"),
        (_small_missing, "missing"),
    ],
)
def test_a_count_below_the_minimum_anywhere_in_a_fragment_refuses_the_package(
    project: Path, capsys, change, where: str
) -> None:
    """A fragment is deposited whole, value and display both: "<5" in the paper does not
    hold back the 3 beside it in the file."""
    ready(project)
    document = paper(project)
    document["custodian"] = {"minimum_cell_count": 5}
    set_paper(project, document)
    edit_fragment(project, change)
    assert main(["package", str(project)]) == 1
    said = capsys.readouterr().out
    assert "below the data custodian's minimum of 5" in said and where in said
    assert refused(project) == {"package-small-count"}
    assert not (project / "build" / "package").exists()


def _custodian(root: Path) -> None:
    authors = yaml.safe_load((root / "authors.yaml").read_text(encoding="utf-8"))
    authors["roles"] = {**authors.get("roles", {}), "data_custodian": "Sample"}
    (root / "authors.yaml").write_text(yaml.safe_dump(authors, allow_unicode=True),
                                       encoding="utf-8")


def test_the_custodian_may_sign_off_the_small_counts(project: Path, capsys) -> None:
    ready(project)
    _custodian(project)
    document = paper(project)
    document["custodian"] = {"minimum_cell_count": 5}
    set_paper(project, document)
    edit_fragment(project, _small_cell)
    assert main(["package", str(project)]) == 1
    capsys.readouterr()
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/small-counts"]) == 0  # fmt: skip
    assert main(["package", str(project)]) == 0, capsys.readouterr().out
    # Another small count is another statement, and the one signed does not cover it.
    edit_fragment(project, _small_level)
    assert main(["package", str(project)]) == 1


def test_a_custodian_who_restricts_sending_signs_the_package_as_it_stands(
    project: Path, capsys
) -> None:
    ready(project)
    _custodian(project)
    document = paper(project)
    document["custodian"] = {"restricts_sending": True}
    set_paper(project, document)
    assert main(["package", str(project)]) == 1
    assert "the data custodian restricts where" in capsys.readouterr().out
    assert refused(project) == {"package-not-authorised"}
    assert refused(project, with_manuscript=True) == {"package-not-authorised"}
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit"]) == 0  # fmt: skip
    assert main(["package", str(project)]) == 0, capsys.readouterr().out
    # What was signed is the list of files and their digests: a changed figure script is a
    # package the custodian has not seen.
    script = project / "figures" / "forest.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    shutil.rmtree(project / "build" / "package")
    assert main(["package", str(project)]) == 1
    assert not (project / "build" / "package").exists()


# ------------------------------------------------------------- what it refuses besides


def test_stale_results_are_not_packaged_unless_the_check_is_skipped(project: Path, capsys) -> None:
    ready(project)
    path = fragment(project)
    path.write_text(path.read_text(encoding="utf-8").replace('"0.05"', '"0.050"'), encoding="utf-8")
    assert main(["package", str(project)]) == 1
    assert "has been modified since the analysis" in capsys.readouterr().out
    assert main(["package", str(project), "--skip-checks"]) == 0
    manifest = yaml.safe_load((built(project) / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert manifest["checks"].startswith("SKIPPED")


def test_no_licence_file_is_refused(project: Path, capsys) -> None:
    assert not (project / "LICENSE").exists()
    assert main(["package", str(project)]) == 1
    assert "the project has no licence file" in capsys.readouterr().out
    assert refused(project) == {"package-licence-missing"}


def test_no_declared_licence_is_refused(project: Path, capsys) -> None:
    ready(project)
    document = paper(project)
    del document["package"]["licence"]
    set_paper(project, document)
    assert main(["package", str(project)]) == 1
    assert "paper.yaml declares no package.licence" in capsys.readouterr().out
    assert refused(project) == {"package-licence-undeclared"}


def test_nothing_to_package_says_so(tmp_path: Path, capsys) -> None:
    assert main(["init", str(tmp_path / "p"), "--title", "A paper"]) == 0
    capsys.readouterr()
    assert main(["package", str(tmp_path / "p")]) == 2
    assert "no results" in capsys.readouterr().err


# ------------------------------------------------------------------ what it writes


def test_the_citation_file_names_the_authors_and_no_address(project: Path) -> None:
    ready(project)
    with_package(project, doi="10.5281/zenodo.1234567")
    assert main(["package", str(project)]) == 0
    cff = yaml.safe_load((built(project) / "CITATION.cff").read_text(encoding="utf-8"))
    assert cff["cff-version"] == "1.2.0"
    assert cff["license"] == "MIT"
    assert cff["doi"] == "10.5281/zenodo.1234567"
    first = cff["authors"][0]
    assert first["family-names"] == "Example" and first["given-names"] == "Ada"
    assert first["orcid"] == "https://orcid.org/0000-0002-1825-0097"
    assert "Example University" in first["affiliation"]
    assert "invalid.example" not in (built(project) / "CITATION.cff").read_text(encoding="utf-8")


def test_the_readme_says_how_to_re_run_and_what_verify_checks(project: Path) -> None:
    ready(project)
    with_package(project, share=[], request="Write to the corresponding author.")
    assert main(["package", str(project)]) == 0
    folder = built(project)
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "manuscript-guard verify" in readme
    assert "analysis/01_disproportionality.py" in readme
    session = json.loads(fragment(project).read_text(encoding="utf-8"))["provenance"]["session"]
    assert f"{session['language']} {session['version']}" in readme
    assert "data/event_terms.txt" in readme
    assert "Write to the corresponding author." in readme
    assert "sha256sum -c SHA256SUMS" in readme


def test_the_bound_results_are_listed_and_the_prose_is_not(project: Path) -> None:
    ready(project)
    assert main(["package", str(project)]) == 0
    folder = built(project)
    bound = (folder / "BOUND.md").read_text(encoding="utf-8")
    namespace, results = None, None
    loaded, _ = load_project(project)
    namespace, results, _lit, _ = load_namespace(loaded)
    assert "`ror.point`" in bound and results.values["ror.point"].display in bound
    assert "table.two_by_two" in bound or "`two_by_two`" in bound
    assert "manuscript/main.md" not in contents(folder)

    shutil.rmtree(project / "build" / "package")
    assert main(["package", str(project), "--with-manuscript"]) == 0
    assert "manuscript/main.md" in contents(built(project))


def test_the_package_tells_the_author_the_steps_and_uploads_nothing(project: Path, capsys) -> None:
    assert main(["package", str(ready(project))]) == 0
    said = capsys.readouterr().out
    assert "package.doi" in said and "Data availability" in said


# ----------------------------------------------------------- the statement names the DOI


def _statement(root: Path, text: str) -> None:
    main_md = root / "manuscript" / "main.md"
    source = main_md.read_text(encoding="utf-8")
    start = source.index("# Data availability")
    end = source.index("\n# ", start + 1)
    main_md.write_text(source[:start] + f"# Data availability\n\n{text}\n" + source[end:],
                       encoding="utf-8")  # fmt: skip


def _doi_codes(root: Path, submission: bool) -> dict[str, str]:
    from manuscript_guard.gates.data_statement import check_package_doi

    loaded, _ = load_project(root)
    return {f.code: f.severity for f in check_package_doi(loaded, submission=submission).findings}


def test_a_statement_that_does_not_name_the_deposit_is_said(project: Path) -> None:
    with_package(project, doi="10.5281/zenodo.1234567")
    _statement(project, "The code is available from the corresponding author.")
    assert _doi_codes(project, submission=False) == {"package-doi-not-named": "warn"}
    assert _doi_codes(project, submission=True) == {"package-doi-not-named": "fail"}


@pytest.mark.parametrize(
    "written",
    [
        "10.5281/zenodo.1234567",
        "https://doi.org/10.5281/zenodo.1234567.",
        "doi:10.5281/ZENODO.1234567",
        "<https://doi.org/10.5281/zenodo.1234567>",
    ],
)
def test_a_statement_that_names_the_deposit_passes(project: Path, written: str) -> None:
    with_package(project, doi="10.5281/zenodo.1234567")
    _statement(project, f"The code and results are deposited at Zenodo ({written})")
    assert _doi_codes(project, submission=True) == {}


def test_another_doi_that_begins_with_the_deposits_is_not_it(project: Path) -> None:
    with_package(project, doi="10.5281/zenodo.1234567")
    _statement(project, "The code is at https://doi.org/10.5281/zenodo.12345678.")
    assert "package-doi-not-named" in _doi_codes(project, submission=False)


def test_no_doi_declared_asks_nothing(project: Path) -> None:
    _statement(project, "The code is available from the corresponding author.")
    assert _doi_codes(project, submission=True) == {}


# ---------------------------------------------------------------------------- R


def _rscript() -> str | None:
    found = shutil.which("Rscript")
    if found:
        return found
    candidates = sorted(Path("C:/Program Files/R").glob("R-*/bin/x64/Rscript.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


RSCRIPT = _rscript()
EMIT_R = Path(__file__).resolve().parent.parent / "r" / "manuscriptguard" / "R" / "emit.R"


@pytest.mark.skipif(RSCRIPT is None, reason="R is not installed")
def test_an_r_analysis_is_packaged_with_its_r_version_and_reproduces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.verify import to_report, verify

    root = tmp_path / "rpaper"
    for sub in ("analysis", "data", "manuscript", "results"):
        (root / sub).mkdir(parents=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "R"\nenglish_variant: en-GB\n'
        "package:\n  licence: MIT\n  share: [data/tiny.csv]\n",
        encoding="utf-8",
    )
    (root / "LICENSE").write_text(MIT, encoding="utf-8")
    (root / "data" / "tiny.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    (root / "analysis" / "01_r.R").write_text(
        'if (!requireNamespace("jsonlite", quietly = TRUE)) quit(status = 3)\n'
        f'source("{EMIT_R.as_posix()}")\n'
        'em <- mg_emitter("analysis/01_r.R", inputs = "data/tiny.csv")\n'
        'd <- read.csv("data/tiny.csv")\n'
        'em$value("cohort.n_rows", nrow(d))\n'
        "em$write()\n",
        encoding="utf-8",
    )
    ran = subprocess.run([RSCRIPT, "--vanilla", "analysis/01_r.R"], cwd=root,
                         capture_output=True, text=True)  # fmt: skip
    if ran.returncode == 3:
        pytest.skip("jsonlite is not installed for this R")
    assert ran.returncode == 0, ran.stderr

    assert main(["package", str(root)]) == 0
    folder = built(root)
    readme = (folder / "README.md").read_text(encoding="utf-8")
    session = json.loads(next((root / "results").glob("*.json")).read_text(encoding="utf-8"))
    assert f"R {session['provenance']['session']['version']}" in readme
    assert "Rscript" in readme

    monkeypatch.setenv("PATH", os.pathsep.join([str(Path(RSCRIPT).parent),
                                                str(Path(sys.executable).parent),
                                                os.environ.get("PATH", "")]))  # fmt: skip
    loaded, _ = load_project(folder)
    result = verify(loaded)
    assert result.ok and not result.skipped, to_report(result).render(folder)
