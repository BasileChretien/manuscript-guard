"""The package described as an RO-Crate, and the citation files beside it (`package
--ro-crate`, `--citation`, `--root-citation`).

The crate is asked of as written, as `test_package.py` asks of the package: a relationship
`@graph` states is one the files here show to hold, and every other is in RELATIONS.md. The
corruption cases, a script edited after its run among them, are in `test_corruption.py`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml
from test_package import _supplement, built, contents, paper, ready, set_paper, with_package

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project

LATEX = Path(__file__).parent / "data" / "latex" / "manuscript"
#: What the package holds that the crate does not name: itself, and the two files written
#: after it, which name it by its digest.
UNNAMED = {"ro-crate-metadata.json", "MANIFEST.yaml", "SHA256SUMS"}


def crate(root: Path) -> dict:
    return json.loads((built(root) / "ro-crate-metadata.json").read_text(encoding="utf-8"))


def graph(root: Path) -> dict[str, dict]:
    return {entity["@id"]: entity for entity in crate(root)["@graph"]}


def referenced(node: object) -> set[str]:
    """Every `@id` a node refers to: each object that is a reference and nothing else."""
    if isinstance(node, list):
        return set().union(*(referenced(one) for one in node)) if node else set()
    if isinstance(node, dict):
        if set(node) == {"@id"}:
            return {node["@id"]}
        return set().union(*(referenced(v) for k, v in node.items() if k != "@id"))
    return set()


def ids(links: object) -> list[str]:
    links = links if isinstance(links, list) else [links] if links else []
    return [link["@id"] for link in links]


def relations(root: Path) -> str:
    return (built(root) / "RELATIONS.md").read_text(encoding="utf-8")


def package(root: Path, *options: str) -> None:
    assert main(["package", str(root), *options]) == 0


# ---------------------------------------------------------------------- the crate's shape


def test_the_crate_is_json_ld_with_its_descriptor_and_every_reference_defined(
    project: Path,
) -> None:
    package(ready(project), "--ro-crate")
    document = crate(project)
    assert document["@context"][0] == "https://w3id.org/ro/crate/1.1/context"
    entities = graph(project)
    assert len(entities) == len(document["@graph"]), "two entities share an @id"
    descriptor = entities["ro-crate-metadata.json"]
    assert descriptor["@type"] == "CreativeWork"
    assert descriptor["conformsTo"] == {"@id": "https://w3id.org/ro/crate/1.1"}
    assert descriptor["about"] == {"@id": "./"}
    root = entities["./"]
    assert root["@type"] == "Dataset"
    for field in ("name", "description", "datePublished", "license", "hasPart", "author"):
        assert root[field], field
    assert set(referenced(document["@graph"])) <= set(entities)
    # Every file of the package is a part of it, with its digest and size.
    folder = built(project)
    assert set(ids(root["hasPart"])) == contents(folder) - UNNAMED
    sums = dict(line.split("  ", 1)[::-1] for line in
                (folder / "SHA256SUMS").read_text(encoding="utf-8").splitlines())  # fmt: skip
    for path in contents(folder) - UNNAMED:
        assert entities[path]["sha256"] == sums[path], path
        assert entities[path]["contentSize"] == str((folder / path).stat().st_size), path


def test_the_people_are_named_by_orcid_and_never_by_address(project: Path) -> None:
    package(ready(project), "--ro-crate")
    entities = graph(project)
    ada = entities["https://orcid.org/0000-0002-1825-0097"]
    assert ada["@type"] == "Person" and ada["familyName"] == "Example"
    assert entities[ada["affiliation"][0]["@id"]]["@type"] == "Organization"
    for name in ("ro-crate-metadata.json", ".zenodo.json", "CITATION.cff"):
        text = (built(project) / name).read_text(encoding="utf-8")
        assert "invalid.example" not in text and "email" not in text, name


def test_only_the_relationships_that_hold_are_in_the_graph(project: Path) -> None:
    package(ready(project), "--ro-crate")
    entities = graph(project)
    run = entities["#run-results/01_disproportionality.json"]
    assert run["@type"] == "CreateAction"
    assert run["instrument"] == {"@id": "analysis/01_disproportionality.py"}
    assert ids(run["result"]) == ["results/01_disproportionality.json"]
    assert set(ids(run["object"])) == {"data/reports.csv", "data/event_terms.txt",
                                       "design/data_dictionary.yaml"}  # fmt: skip
    assert run["endTime"] == json.loads(
        (project / "results" / "01_disproportionality.json").read_text(encoding="utf-8")
    )["provenance"]["generated_at"]
    drawing = entities["#render-figures/forest.render.json"]
    assert drawing["instrument"] == {"@id": "figures/forest.py"}
    assert set(ids(drawing["result"])) == {"figures/forest.svg", "figures/forest.png"}
    # Which results the figure was drawn from is recorded nowhere, so it is not stated.
    assert "object" not in drawing
    said = relations(project)
    assert "| #render-figures/forest.render.json | object |" in said
    assert "## Not as recorded\n\nThe record names it, and the files here do not show that " \
           "it holds.\n\nNone." in said  # fmt: skip
    assert "SoftwareSourceCode" in entities["analysis/01_disproportionality.py"]["@type"]


def test_a_withheld_input_is_described_by_its_digest_and_how_to_obtain_it(project: Path) -> None:
    ready(project)
    with_package(project, share=[], request="Apply to the custodian of the event terms.")
    package(project, "--ro-crate")
    entities = graph(project)
    held = entities["#input-data/event_terms.txt"]
    assert held["conditionsOfAccess"] == "Apply to the custodian of the event terms."
    assert len(held["sha256"]) == 64
    assert "data/event_terms.txt" not in contents(built(project))
    # The file is on this computer and is the one the run read, so the link holds.
    run = entities["#run-results/01_disproportionality.json"]
    assert "#input-data/event_terms.txt" in ids(run["object"])
    shutil.rmtree(project / "build" / "package")
    (project / "data" / "event_terms.txt").unlink()
    assert main(["package", str(project), "--ro-crate", "--skip-checks"]) == 0
    run = graph(project)["#run-results/01_disproportionality.json"]
    assert "#input-data/event_terms.txt" not in ids(run["object"])
    assert "| #run-results/01_disproportionality.json | object | data/event_terms.txt | " \
           "withheld, and not on the computer" in relations(project)  # fmt: skip


def test_the_date_is_the_records_and_never_the_clocks(project: Path) -> None:
    package(ready(project), "--ro-crate")
    written = json.loads((project / "results" / "01_disproportionality.json")
                         .read_text(encoding="utf-8"))["provenance"]["generated_at"]  # fmt: skip
    assert graph(project)["./"]["datePublished"] == written[:10]
    assert "publication_date" not in json.loads(
        (built(project) / ".zenodo.json").read_text(encoding="utf-8"))
    shutil.rmtree(project / "build" / "package")
    with_package(project, date="2027-01-15")
    package(project, "--ro-crate")
    assert graph(project)["./"]["datePublished"] == "2027-01-15"
    zenodo = json.loads((built(project) / ".zenodo.json").read_text(encoding="utf-8"))
    assert zenodo["publication_date"] == "2027-01-15"


def test_the_models_are_carried_as_the_models_command_prints_them(project: Path, capsys) -> None:
    package(ready(project), "--ro-crate")
    capsys.readouterr()
    main(["models", str(project)])
    printed = capsys.readouterr().out
    held = (built(project) / "MODELS.md").read_text(encoding="utf-8")
    for line in printed.strip().splitlines():
        assert line.rstrip() in held, line
    assert graph(project)["MODELS.md"]["about"] == [{"@id": "results/01_disproportionality.json"}]


# --------------------------------------------------------------- what is asked, and only that


def test_the_package_is_as_it_was_unless_asked(project: Path) -> None:
    package(ready(project))
    plain = contents(built(project))
    assert not plain & {".zenodo.json", "ro-crate-metadata.json", "RELATIONS.md", "MODELS.md"}
    shutil.rmtree(project / "build" / "package")
    package(project, "--citation")
    assert contents(built(project)) - plain == {".zenodo.json"}
    readme = (built(project) / "README.md").read_text(encoding="utf-8")
    assert "`.zenodo.json`" in readme and "ro-crate" not in readme
    shutil.rmtree(project / "build" / "package")
    package(project, "--ro-crate")
    assert contents(built(project)) - plain == {".zenodo.json", "ro-crate-metadata.json",
                                                "RELATIONS.md", "MODELS.md"}  # fmt: skip


def test_the_zenodo_record_is_made_from_the_records(project: Path) -> None:
    ready(project)
    with_package(project, doi="10.5281/zenodo.1234567")
    (project / "design" / "data_sources.yaml").write_text(yaml.safe_dump({
        "schema": "manuscript-guard/data-sources/1",
        "candidates": [{"id": "reports", "name": "The reports",
                        "identifiers": [{"scheme": "doi", "id": "https://doi.org/10.1234/abc"}]},
                       {"id": "other", "name": "Not chosen",
                        "identifiers": [{"scheme": "doi", "id": "10.1234/other"}]}],
        "decision": {"chosen": ["reports"], "decided_by": "Ada Example",
                     "decided_on": "2026-01-01"},
    }), encoding="utf-8")  # fmt: skip
    package(project, "--citation")
    record = json.loads((built(project) / ".zenodo.json").read_text(encoding="utf-8"))
    assert record["creators"][0] == {
        "name": "Example, Ada", "orcid": "0000-0002-1825-0097",
        "affiliation": "Department of Clinical Pharmacology, Example University Graduate "
        "School of Medicine, Springfield, Japan"}  # fmt: skip
    assert record["license"] == "mit" and record["upload_type"] == "software"
    assert record["doi"] == "10.5281/zenodo.1234567"
    assert record["keywords"] == paper(project)["keywords"]
    assert record["related_identifiers"] == [{"identifier": "10.1234/abc", "relation":
                                              "isDerivedFrom", "resource_type": "dataset",
                                              "scheme": "doi"}]  # fmt: skip
    # A fixed sentence about the package: nothing the paper found.
    assert record["description"].startswith("The analysis code of the paper \"")


def test_several_licences_are_left_to_the_record_form(project: Path, capsys) -> None:
    ready(project)
    with_package(project, licence=["MIT", "CC-BY-4.0"])
    package(project, "--citation")
    assert "license" not in json.loads((built(project) / ".zenodo.json").read_text("utf-8"))
    assert "a Zenodo record takes one" in capsys.readouterr().out


# -------------------------------------------------------------------- bytes, and the root


def test_the_crate_is_the_same_bytes_twice_and_from_another_folder(
    project: Path, tmp_path: Path
) -> None:
    package(ready(project), "--ro-crate")
    first = {path: (built(project) / path).read_bytes() for path in contents(built(project))}
    archive = (built(project).with_suffix(".zip")).read_bytes()
    package(project, "--ro-crate")
    again = {path: (built(project) / path).read_bytes() for path in contents(built(project))}
    assert again == first
    elsewhere = tmp_path / "elsewhere" / "deeper" / "paper"
    shutil.copytree(project, elsewhere, ignore=shutil.ignore_patterns("build"))
    package(elsewhere, "--ro-crate")
    moved = {path: (built(elsewhere) / path).read_bytes() for path in contents(built(elsewhere))}
    assert moved == first
    assert built(elsewhere).with_suffix(".zip").read_bytes() == archive
    for name in ("ro-crate-metadata.json", "RELATIONS.md", ".zenodo.json", "MODELS.md"):
        assert b"\r\n" not in first[name], name
        assert str(project).encode() not in first[name], name


def test_the_files_at_the_root_are_written_only_where_none_is(project: Path, capsys) -> None:
    ready(project)
    mine = "cff-version: 1.2.0\ntitle: My own title\nmessage: Cite me.\n"
    (project / "CITATION.cff").write_text(mine, encoding="utf-8")
    assert main(["package", str(project), "--root-citation", "--dry-run"]) == 0
    assert "root: .zenodo.json would be written at the root" in capsys.readouterr().out
    assert not (project / ".zenodo.json").exists()
    package(project, "--root-citation")
    said = capsys.readouterr().out
    assert (project / "CITATION.cff").read_text(encoding="utf-8") == mine
    assert "root: CITATION.cff at the root is kept; it differs from the package's in " \
           "authors, license, message, title, type" in said  # fmt: skip
    assert "root: .zenodo.json written at the root" in said
    assert (project / ".zenodo.json").read_bytes() == (built(project) / ".zenodo.json").read_bytes()
    # The package holds them all the same.
    assert {"CITATION.cff", ".zenodo.json"} <= contents(built(project))
    (project / ".zenodo.json").write_text('{"title": "Kept"}\n', encoding="utf-8")
    package(project, "--root-citation")
    assert (project / ".zenodo.json").read_text(encoding="utf-8") == '{"title": "Kept"}\n'
    assert "root: .zenodo.json at the root is kept; it differs" in capsys.readouterr().out


def test_a_refused_package_writes_nothing_at_the_root(project: Path) -> None:
    ready(project)
    document = paper(project)
    document["package"].pop("licence")
    set_paper(project, document)
    assert main(["package", str(project), "--root-citation"]) == 1
    assert not (project / "CITATION.cff").exists() and not (project / ".zenodo.json").exists()


# ------------------------------------------------------------- LaTeX, and the supplement


def _latex(root: Path) -> None:
    shutil.rmtree(root / "manuscript")
    shutil.copytree(LATEX, root / "manuscript")


def _codes(root: Path, **options: bool) -> set[str]:
    from manuscript_guard.deposit import plan_package

    loaded, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(loaded)
    return {f.code for f in plan_package(loaded, results, **options).report.findings}


def test_bound_md_reads_a_latex_manuscript_and_the_crate_describes_its_package(
    project: Path,
) -> None:
    ready(project)
    _latex(project)
    assert "package-bound-not-read" not in _codes(project, ro_crate=True)
    package(project, "--ro-crate", "--with-manuscript")
    rows = (built(project) / "BOUND.md").read_text(encoding="utf-8").splitlines()
    points = [row for row in rows if row.startswith("| `ror.point` |")]
    assert points and all("manuscript/main.tex" in row for row in points)
    supplement = [row for row in rows if "manuscript/supplementary/main.tex" in row]
    assert supplement, "the supplement's bindings are listed"
    entities = graph(project)
    assert "manuscript/main.tex" in ids(entities["#paper"]["hasPart"])
    assert "manuscript/main.tex" in ids(entities["./"]["hasPart"])


def test_bound_md_names_each_binding_under_its_latex_heading(project: Path) -> None:
    from manuscript_guard.deposit.bound import bound_rows

    ready(project)
    _latex(project)
    (project / "manuscript" / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\section{Methods}\nOf "
        "\\mg{results.cohort.n_reports} reports.\n\\subsection{Primary  analysis}\nAn odds "
        "ratio of \\mg{results.ror.point}.\n\\end{document}\n", encoding="utf-8")  # fmt: skip
    loaded, _ = load_project(project)
    found = [(row.key, row.section, row.line, row.supplement) for row in bound_rows(loaded)
             if not row.supplement]  # fmt: skip
    assert found == [("cohort.n_reports", "Methods", 4, False),
                     ("ror.point", "Primary analysis", 6, False)]  # fmt: skip


def test_a_latex_part_its_reader_refuses_keeps_the_warning(project: Path) -> None:
    ready(project)
    _latex(project)
    entry = project / "manuscript" / "main.tex"
    text = entry.read_text(encoding="utf-8")
    entry.write_text(text.replace("\\begin{document}", "\\begin{document}\n\\catcode`\\@=11",
                                  1), encoding="utf-8")  # fmt: skip
    from manuscript_guard.deposit import plan_package

    loaded, _ = load_project(project)
    _namespace, results, _literature, _ = load_namespace(loaded)
    (warned,) = [f for f in plan_package(loaded, results).report.findings
                 if f.code == "package-bound-not-read"]  # fmt: skip
    assert "manuscript/main.tex:" in warned.message


def test_the_supplements_runs_and_figures_are_described_as_the_main_texts(project: Path) -> None:
    ready(project)
    _supplement(project)
    package(project, "--ro-crate")
    entities = graph(project)
    run = entities["#run-results/02_supplement.json"]
    assert run["instrument"] == {"@id": "analysis/02_supplement.py"}
    assert ids(run["result"]) == ["results/02_supplement.json"]
    assert "figures/s1_sites.svg" in ids(entities["./"]["hasPart"])
    # The supplement's figure has no record of what drew it, and the crate says none.
    assert "| figures/s1_sites.svg | created by |  | no `*.render.json` records what drew " \
           "it |" in relations(project)  # fmt: skip
    rows = (built(project) / "BOUND.md").read_text(encoding="utf-8")
    assert "manuscript/supplementary/S1_code_lists.md" in rows


# ------------------------------------------------------------------ the custodian's sign-off


def test_a_custodian_signs_the_crate_package_as_its_own(project: Path, capsys) -> None:
    from test_package import _custodian

    ready(project)
    _custodian(project)
    document = paper(project)
    document["custodian"] = {"restricts_sending": True}
    set_paper(project, document)
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit"]) == 0  # fmt: skip
    package(project)
    # The crate is a file the custodian has not seen: a package of its own, signed apart.
    shutil.rmtree(project / "build" / "package")
    assert main(["package", str(project), "--ro-crate"]) == 1
    capsys.readouterr()
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit-ro-crate"]) == 0  # fmt: skip
    package(project, "--ro-crate")
