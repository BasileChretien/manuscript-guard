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
    # The supporting passages hold the manuscript's sentences and the names of who judged
    # them (the last round of #388): no packaged file carries a cited sentence.
    assert "literature/passages.yaml" not in held
    cited = yaml.safe_load((project / "literature" / "passages.yaml").read_text(
        encoding="utf-8"))["passages"][0]["sentence"].split("{{")[0].strip()  # fmt: skip
    for path in held:
        data = (built(project) / path).read_bytes()
        assert cited.encode("utf-8") not in data, path


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


def test_a_design_record_the_analysis_reads_goes_as_the_record(project: Path) -> None:
    """The data checks declare the data dictionary as an input. It is a record of the design,
    which the package takes, and not data withheld for want of a declaration; declared
    restricted, it is held back like any input."""
    assert "design/data_dictionary.yaml" in {
        record["path"] for record in json.loads(fragment(project).read_text("utf-8"))[
            "provenance"]["inputs"]}  # fmt: skip
    ready(project)
    assert refused(project) == set()
    assert main(["package", str(project)]) == 0
    folder = built(project)
    assert "design/data_dictionary.yaml" in contents(folder)
    manifest = yaml.safe_load((folder / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert all(w["path"] != "design/data_dictionary.yaml" for w in manifest["withheld"])
    declare_input(project, "design/data_dictionary.yaml", restricted=True)
    assert "package-request-missing" in refused(project)
    assert "design/data_dictionary.yaml" not in _entries(project)


def _entries(root: Path) -> set[str]:
    from manuscript_guard.deposit import plan_package

    loaded, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(loaded)
    return {entry.path for entry in plan_package(loaded, results).entries}


def test_a_design_record_git_does_not_track_goes_by_the_inputs_rule(project: Path) -> None:
    """Taken as the record only where the records are taken: one never committed is withheld
    as git does not track it, and as an input it is not said to be deposited."""
    ready(project)
    _git(project, "init", "-q")
    _git(project, "add", "-A")
    _git(project, "rm", "-q", "--cached", "design/data_dictionary.yaml")
    _git(project, "commit", "-q", "-m", "x")
    assert "package-request-missing" in refused(project)
    assert "design/data_dictionary.yaml" not in _entries(project)


def test_a_design_record_that_is_a_link_goes_by_the_inputs_rule(
    project: Path, tmp_path: Path
) -> None:
    """A link is not taken as the record, whose loop does not ask: the inputs' rule holds it."""
    ready(project)
    dictionary = project / "design" / "data_dictionary.yaml"
    target = tmp_path / "elsewhere.yaml"
    target.write_bytes(dictionary.read_bytes())
    dictionary.unlink()
    try:
        dictionary.symlink_to(target)
    except OSError:
        pytest.skip("this system makes no symbolic link without a privilege")
    assert "package-request-missing" in refused(project)
    assert "design/data_dictionary.yaml" not in _entries(project)


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


def _supplement(root: Path) -> None:
    """A second script whose results only the supplement prints, a table and a value, and a
    figure of the supplement's own."""
    script = root / "analysis" / "02_supplement.py"
    script.write_text(
        "from manuscript_guard.emit import Emitter\n"
        "em = Emitter(__file__)\n"
        'em.add_input("data/reports.csv", synthetic=True)\n'
        'em.value("supplement.n_sites", 3)\n'
        'em.table("sites", ["Site", "Reports"], [["North", 2], ["South", 40]],\n'
        '         caption="Reports by site.")\n'
        "em.write()\n",
        encoding="utf-8",
    )
    ran = subprocess.run([sys.executable, "analysis/02_supplement.py"], cwd=root,
                         capture_output=True, text=True)  # fmt: skip
    assert ran.returncode == 0, ran.stderr
    page = root / "manuscript" / "supplementary" / "S1_code_lists.md"
    page.write_text(page.read_text(encoding="utf-8") + "\n## Table S3. Reports by site\n\n"
                    "The reports came from {{results.supplement.n_sites}} sites.\n\n"
                    "{{table.sites}}\n", encoding="utf-8")  # fmt: skip
    (root / "figures" / "s1_sites.py").write_text("# draws figures/s1_sites.svg\n",
                                                  encoding="utf-8")  # fmt: skip
    (root / "figures" / "s1_sites.svg").write_text("<svg/>\n", encoding="utf-8")


def test_the_supplement_is_packaged_as_the_main_text_is(project: Path) -> None:
    """Basile's rule of 2026-10-21: the supplement is held to the main text's rules. Its
    tables and figures, their scripts and results go in as the main text's do, BOUND.md lists
    what it prints, `--with-manuscript` takes its source, and its counts are held to the
    custodian's minimum; no built document goes, the supplement's no more than the paper's."""
    ready(project)
    _supplement(project)
    (project / "build").mkdir(exist_ok=True)
    for built_document in ("manuscript.docx", "supplementary.docx"):
        (project / "build" / built_document).write_bytes(b"PK")
    assert main(["package", str(project)]) == 0
    folder = built(project)
    held = contents(folder)
    for wanted in ("analysis/02_supplement.py", "results/02_supplement.json",
                   "results/02_supplement.json.sha256", "figures/s1_sites.py",
                   "figures/s1_sites.svg"):  # fmt: skip
        assert wanted in held, wanted
    assert not [path for path in held if path.endswith(".docx")]
    assert not [path for path in held if path.startswith("manuscript/")]
    supplement = "manuscript/supplementary/S1_code_lists.md"
    rows = (folder / "BOUND.md").read_text(encoding="utf-8").splitlines()
    for key in ("`supplement.n_sites`", "`table.sites`", "`table.outcome_codes`"):
        (row,) = [row for row in rows if row.startswith(f"| {key} |")]
        assert supplement in row, row
    assert "supplement" in (folder / "README.md").read_text(encoding="utf-8")

    shutil.rmtree(project / "build" / "package")
    assert main(["package", str(project), "--with-manuscript"]) == 0
    assert supplement in contents(built(project))

    document = paper(project)
    document["custodian"] = {"minimum_cell_count": 5}
    set_paper(project, document)
    assert refused(project) == {"package-small-count"}
    from manuscript_guard.deposit import small_counts

    loaded, _ = load_project(project)
    _namespace, results, _literature, _ = load_namespace(loaded)
    named = {(small.fragment, small.where) for small in small_counts(loaded, results)}
    assert ("results/02_supplement.json", "supplement.n_sites") in named
    assert ("results/02_supplement.json", "table sites, row 1, column 2") in named


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
        # Round 1: emphasis by underscores, a code span and quotation marks.
        "_10.5281/zenodo.1234567_",
        "`10.5281/zenodo.1234567`",
        "'10.5281/zenodo.1234567'",
    ],
)
def test_a_statement_that_names_the_deposit_passes(project: Path, written: str) -> None:
    with_package(project, doi="10.5281/zenodo.1234567")
    _statement(project, f"The code and results are deposited at Zenodo ({written})")
    assert _doi_codes(project, submission=True) == {}


def test_a_statement_in_another_file_than_a_heading_like_it_is_read(project: Path) -> None:
    """Round 1: the statement in one file and a "Data sharing" subsection in another; the
    main text is read as one, as G4 reads it."""
    with_package(project, doi="10.5281/zenodo.1234567")
    main_md = project / "manuscript" / "main.md"
    source = main_md.read_text(encoding="utf-8")
    start = source.index("# Data availability")
    end = source.index("\n# ", start + 1)
    methods = source.index("# Methods")
    moved = source[:methods] + "# Methods\n\n### Data sharing between sites\n\nNone.\n" + \
        source[methods + len("# Methods"):start] + source[end + 1:]  # fmt: skip
    main_md.write_text(moved, encoding="utf-8")
    (project / "manuscript" / "zz-declarations.md").write_text(
        "# Data availability\n\nDeposited as 10.5281/zenodo.1234567.\n", encoding="utf-8"
    )
    assert _doi_codes(project, submission=True) == {}


def test_a_code_availability_statement_that_names_the_deposit_passes(project: Path) -> None:
    """Round 1: the deposit is code, and many journals ask for its own statement."""
    with_package(project, doi="10.5281/zenodo.1234567")
    _statement(project, "The data are held by the custodian.\n\n## Code availability\n\n"
               "The code is deposited as 10.5281/zenodo.1234567.")  # fmt: skip
    assert _doi_codes(project, submission=True) == {}


def test_another_doi_that_begins_with_the_deposits_is_not_it(project: Path) -> None:
    with_package(project, doi="10.5281/zenodo.1234567")
    _statement(project, "The code is at https://doi.org/10.5281/zenodo.12345678.")
    assert "package-doi-not-named" in _doi_codes(project, submission=False)


def test_a_latex_statement_is_held_to_the_deposits_doi(project: Path) -> None:
    """Since #414 G4 reads a LaTeX manuscript as it prints, and this check with it: the
    example's LaTeX twin is held to the DOI as the Markdown manuscript is."""
    twin = Path(__file__).parent / "data" / "latex" / "manuscript"
    shutil.rmtree(project / "manuscript")
    shutil.copytree(twin, project / "manuscript")
    with_package(project, doi="10.5281/zenodo.1234567")
    assert _doi_codes(project, submission=True) == {"package-doi-not-named": "fail"}
    entry = project / "manuscript" / "main.tex"
    text = entry.read_text(encoding="utf-8")
    named = text.replace("are all in\nthis repository.",
                         "are all in this repository, deposited as 10.5281/zenodo.1234567.")
    assert named != text
    entry.write_text(named, encoding="utf-8")
    assert _doi_codes(project, submission=True) == {}


def test_no_doi_declared_asks_nothing(project: Path) -> None:
    _statement(project, "The code is available from the corresponding author.")
    assert _doi_codes(project, submission=True) == {}


# ------------------------------------------------------------ round 1 of the review


@pytest.mark.parametrize(
    "cell", ["3/412 (0.7%)", "3 / 412 (0.7 %)", "3 (<1%)", "3 (0\N{MIDDLE DOT}7)", "3 (0,7)",
             "3 (\N{LESS-THAN OR EQUAL TO}0.7%)"],
)  # fmt: skip
def test_a_count_with_its_denominator_and_share_is_a_count(cell: str) -> None:
    """Round 1: n/N (%), a share held behind a bound, a middle dot or a decimal comma."""
    from manuscript_guard.deposit.counts import count_in_cell

    assert count_in_cell(cell) == 3


def _mini(tmp_path: Path, scripts: dict[str, str], package: str) -> Path:
    """A project whose analysis is `scripts`, each run once in order, and a synthetic input."""
    root = tmp_path / "mini"
    for sub in ("analysis", "data", "manuscript", "results"):
        (root / sub).mkdir(parents=True)
    (root / "paper.yaml").write_text(
        f'schema: manuscript-guard/paper/1\ntitle: "Mini"\nenglish_variant: en-GB\n{package}',
        encoding="utf-8",
    )
    (root / "LICENSE").write_text(MIT, encoding="utf-8")
    (root / "data" / "x.csv").write_text("a\n1\n", encoding="utf-8")
    for name, body in scripts.items():
        (root / "analysis" / name).write_text(
            "from manuscript_guard.emit import Emitter\n"
            "em = Emitter(__file__)\n" + body + "em.write()\n", encoding="utf-8"
        )
        ran = subprocess.run([sys.executable, f"analysis/{name}"], cwd=root,
                             capture_output=True, text=True)  # fmt: skip
        assert ran.returncode == 0, ran.stderr
    return root


def test_a_results_file_another_script_read_is_deposited_as_results(tmp_path: Path) -> None:
    """Session's own: `02` declares `01`'s results as its input, and the fragment was
    withheld as an input nobody declared shareable."""
    root = _mini(tmp_path, {
        "01_first.py": 'em.add_input("data/x.csv", synthetic=True)\nem.value("n.a", 40)\n',
        "02_next.py": 'em.add_input("results/01_first.json")\nem.value("n.b", 41)\n',
    }, "package:\n  licence: MIT\n")  # fmt: skip
    assert main(["package", str(root)]) == 0
    held = contents(built(root))
    assert {"results/01_first.json", "results/02_next.json"} <= held
    listed = (built(root) / "INPUTS.md").read_text(encoding="utf-8")
    assert "| `results/01_first.json` |" in listed and "yes: a results file" in listed


@pytest.mark.parametrize("name", ["paper.yaml", "README.md", "MANIFEST.yaml"])
def test_an_input_at_a_name_the_package_writes_is_refused(tmp_path: Path, name: str) -> None:
    """Session's own: two files would be written at one path, and SHA256SUMS name both."""
    root = _mini(tmp_path, {}, "")
    if name != "paper.yaml":
        (root / name).write_text("shared: true\n", encoding="utf-8")
    (root / "analysis" / "01_first.py").write_text(
        "from manuscript_guard.emit import Emitter\nem = Emitter(__file__)\n"
        f'em.add_input("{name}")\nem.value("n.a", 40)\nem.write()\n', encoding="utf-8"
    )
    ran = subprocess.run([sys.executable, "analysis/01_first.py"], cwd=root,
                         capture_output=True, text=True)  # fmt: skip
    assert ran.returncode == 0, ran.stderr
    document = paper(root)
    document["package"] = {"licence": "MIT", "share": [name]}
    set_paper(root, document)
    # paper.yaml has changed since the run read it: only the package's own refusal is asked.
    assert "package-name-taken" in refused(root)


def test_a_folder_that_is_the_project_itself_is_refused(project: Path) -> None:
    """Round 1: `paths.analysis: "."` walked the whole project, review records and stored
    copies of cited works with it."""
    ready(project)
    document = paper(project)
    document["paths"] = {"analysis": "."}
    set_paper(project, document)
    assert "package-folder-is-root" in refused(project)


def test_a_restricted_input_under_another_name_for_the_same_file_stays_out(
    project: Path,
) -> None:
    """Round 1: a declared input was held out of the walk by its name, so another name for the
    same file, a hard link here, or the path in another case where the file system ignores
    case, went in."""
    ready(project)
    with_package(project, request="Apply to the custodian.")
    raw = project / "analysis" / "data" / "raw.csv"
    raw.parent.mkdir()
    raw.write_text("id,age\n1,40\n", encoding="utf-8")
    os.link(raw, project / "analysis" / "data" / "copy.csv")

    def declare(document: dict) -> None:
        document["provenance"]["inputs"].append(
            {"path": "analysis/data/raw.csv", "sha256": "0" * 64, "bytes": 13,
             "restricted": True}
        )  # fmt: skip

    edit_fragment(project, declare)
    assert main(["package", str(project), "--skip-checks"]) == 0
    held = contents(built(project))
    assert "analysis/data/raw.csv" not in held and "analysis/data/copy.csv" not in held
    with zipfile.ZipFile(built(project).with_suffix(".zip")) as opened:
        assert not [n for n in opened.namelist() if n.lower().endswith(("raw.csv", "copy.csv"))]


def test_a_restricted_input_named_in_another_case_stays_out(project: Path) -> None:
    ready(project)
    with_package(project, request="Apply to the custodian.")
    raw = project / "analysis" / "data" / "raw.csv"
    raw.parent.mkdir()
    raw.write_text("id,age\n1,40\n", encoding="utf-8")
    if not (project / "Analysis" / "Data" / "raw.csv").exists():
        pytest.skip("this file system tells the two names apart")

    def declare(document: dict) -> None:
        document["provenance"]["inputs"].append(
            {"path": "Analysis/Data/raw.csv", "sha256": "0" * 64, "bytes": 13,
             "restricted": True}
        )  # fmt: skip

    edit_fragment(project, declare)
    assert main(["package", str(project), "--skip-checks"]) == 0
    with zipfile.ZipFile(built(project).with_suffix(".zip")) as opened:
        assert not [n for n in opened.namelist() if n.lower().endswith("raw.csv")]


def test_the_readme_says_what_was_taken_outside_a_repository(project: Path) -> None:
    """Round 1: the README said files git did not track were listed, of a project git does
    not hold, where every file of the folders was taken."""
    assert main(["package", str(ready(project))]) == 0
    readme = (built(project) / "README.md").read_text(encoding="utf-8")
    assert "git did not track" not in readme
    assert "not a git repository" in readme


def test_the_readme_names_the_licence_file_copied(project: Path) -> None:
    (project / "COPYING").write_text(MIT, encoding="utf-8")
    assert main(["package", str(project)]) == 0
    folder = built(project)
    assert "COPYING" in contents(folder)
    assert "(see COPYING)" in (folder / "README.md").read_text(encoding="utf-8")


# ------------------------------------------------------------ round 2 of the review


def test_a_repository_git_cannot_answer_for_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2: in a repository git could not be asked about, every file was taken as though
    there were none, the files git ignores with them, and the README said there was none."""
    from manuscript_guard.deposit import plan

    ready(project)
    (project / ".git").mkdir()
    monkeypatch.setattr(plan, "GIT", "git-that-is-not-installed")
    assert "package-git-unanswered" in refused(project)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_worktree_whose_repository_is_gone_is_refused(project: Path) -> None:
    """The last fix round: git says "not a git repository: <gitdir>" of a `.git` file whose
    gitdir is gone, a moved checkout or a pruned worktree, and that was read as none."""
    ready(project)
    (project / ".git").write_text(f"gitdir: {project.parent / 'gone'}\n", encoding="utf-8")
    assert "package-git-unanswered" in refused(project)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_git_folder_git_says_is_no_repository_refuses_nothing(project: Path) -> None:
    """The fix round: a `.git` above the project that git does not take for a repository, as
    beyond a mount or a ceiling, refused an ordinary project."""
    ready(project)
    (project / ".git").mkdir()  # git says: not a git repository
    assert "package-git-unanswered" not in refused(project)


def test_two_spellings_of_one_input_are_one_input(project: Path) -> None:
    """Round 2: `./data/event_terms.txt` declared restricted beside the same file declared
    shared as `data/event_terms.txt` were two inputs, and the shared one went in."""
    ready(project)

    def declare(document: dict) -> None:
        document["provenance"]["inputs"].append(
            {"path": "./data/event_terms.txt", "sha256": "0" * 64, "bytes": 50,
             "restricted": True}
        )  # fmt: skip

    edit_fragment(project, declare)
    with_package(project, request="Apply to the custodian.")
    assert "package-share-restricted" in refused(project)
    with_package(project, share=[])
    assert main(["package", str(project), "--skip-checks"]) == 0
    assert "data/event_terms.txt" not in contents(built(project))


def test_a_results_file_declared_restricted_stays_out(tmp_path: Path) -> None:
    """Round 2: a results file another script declared restricted went in as results."""
    root = _mini(tmp_path, {
        "01_first.py": 'em.add_input("data/x.csv", synthetic=True)\nem.value("n.a", 40)\n',
        "02_next.py": 'em.add_input("results/01_first.json", restricted=True)\n'
                      'em.value("n.b", 41)\n',
    }, "package:\n  licence: MIT\n  request: Write to the authors.\n")  # fmt: skip
    assert main(["package", str(root)]) == 0
    held = contents(built(root))
    assert "results/01_first.json" not in held
    # The fix round: its digest went in without it.
    assert "results/01_first.json.sha256" not in held
    assert "results/02_next.json" in held


@pytest.mark.parametrize(
    ("cell", "count"),
    [
        ("3 (0.7%)*", 3), ("3\N{MODIFIER LETTER SMALL A}", 3), ("3 (.7%)", 3),
        ("3 [0.7%]", 3), ("3 (0.7%)\N{DAGGER}", 3), ("3^a^", 3), ("3/412 [0.7%]", 3),
        # The fix round: a share behind a bound with no percent sign is a share, "2 (<0.1)"
        # in an "n (%)" column, so "1 (<0.001)" is read as a count too, and signed off.
        ("2 (<0.1)", 2), ("1 (<0.001)", 1), ("3 (<1)", 3),
        ("3\N{MODIFIER LETTER SMALL A}\N{MODIFIER LETTER SMALL B}", 3), ("3^a,b^", 3),
        ("3\N{SUPERSCRIPT ONE}", 3), ("3\N{MODIFIER LETTER SMALL A} (0.7%)", 3),
        ("3* (0.7%)", 3), ("3^a^ (0.7%)\N{DAGGER}", 3),
    ],
)  # fmt: skip
def test_a_cell_is_read_with_its_footnote_marks_and_its_share_behind_a_bound(
    cell: str, count: int | None
) -> None:
    """Round 2: a footnote mark after a count, a share with no digit before its point, and a
    share in square brackets hid the count. The fix round: two marks, a superscript digit, a
    mark before the share."""
    from manuscript_guard.deposit.counts import count_in_cell

    assert count_in_cell(cell) == count


def test_a_folder_that_leads_to_the_project_itself_is_refused(project: Path) -> None:
    """Round 2: `paths.analysis` set to a link to the project walked the whole of it."""
    ready(project)
    link = project / "code"
    try:
        os.symlink(project, link, target_is_directory=True)
    except OSError:
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(project)],
                              capture_output=True) if sys.platform == "win32" else None  # fmt: skip
        if made is None or made.returncode != 0:
            pytest.skip("cannot make a link to a folder here")
    document = paper(project)
    document["paths"] = {"analysis": "code"}
    set_paper(project, document)
    try:
        assert "package-folder-is-root" in refused(project)
    finally:
        # A junction is removed as an empty folder, which leaves what it leads to alone.
        link.unlink() if link.is_symlink() else os.rmdir(link)


@pytest.mark.parametrize(
    ("text", "doi"),
    [
        ("\N{LEFT SINGLE QUOTATION MARK}10.5281/zenodo.1234567\N{RIGHT SINGLE QUOTATION MARK}",
         "10.5281/zenodo.1234567"),
        ("deposited as 10.1000/study" + chr(92) + "_code.", "10.1000/study_code"),
    ],
)  # fmt: skip
def test_a_doi_in_curly_quotes_or_with_an_escaped_underscore_is_named(text: str, doi: str) -> None:
    from manuscript_guard.gates.data_statement import names_doi

    assert names_doi(text, doi)


# ------------------------------------------------------- the fix round of the review


def test_an_input_is_held_to_the_file_a_withheld_input_is(project: Path) -> None:
    """The fix round: a shared input that is the same file as a restricted one, a hard link
    here and the name in another case on macOS, deposited the restricted bytes."""
    ready(project)
    terms = project / "data" / "event_terms.txt"
    os.link(terms, project / "data" / "terms_kept.txt")

    def declare(document: dict) -> None:
        document["provenance"]["inputs"].append(
            {"path": "data/terms_kept.txt", "sha256": "0" * 64, "bytes": 50,
             "restricted": True}
        )  # fmt: skip

    edit_fragment(project, declare)
    with_package(project, request="Apply to the custodian.")
    assert main(["package", str(project), "--skip-checks"]) == 0
    held = contents(built(project))
    assert "data/event_terms.txt" not in held and "data/terms_kept.txt" not in held


def test_a_declared_path_through_a_step_up_is_outside(project: Path) -> None:
    """The fix round: "data/../x.csv" was read as "x.csv", and is the wrong file where
    `data` is a link."""
    ready(project)

    def declare(document: dict) -> None:
        document["provenance"]["inputs"].append(
            {"path": "data/../secret.csv", "sha256": "0" * 64, "bytes": 5, "synthetic": True}
        )

    edit_fragment(project, declare)
    with_package(project, request="Apply to the custodian.")
    assert "package-outside" in refused(project)


def test_a_folder_that_leads_above_the_project_is_refused(project: Path) -> None:
    """The fix round: `paths.analysis` set to a link to the folder above walked the project
    as one of its folders, and its neighbours with it."""
    ready(project)
    link = project / "code"
    try:
        os.symlink(project.parent, link, target_is_directory=True)
    except OSError:
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(project.parent)],
                              capture_output=True) if sys.platform == "win32" else None  # fmt: skip
        if made is None or made.returncode != 0:
            pytest.skip("cannot make a link to a folder here")
    document = paper(project)
    document["paths"] = {"analysis": "code"}
    set_paper(project, document)
    try:
        assert "package-outside" in refused(project)
    finally:
        link.unlink() if link.is_symlink() else os.rmdir(link)


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
