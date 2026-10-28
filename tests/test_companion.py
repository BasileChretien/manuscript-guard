"""The companion page of a package (`package --companion`): ro-crate-preview.html, and its
copy index.html.

Each section is asked of the page as written, from the example's records and from records a
test adds. The page shows nothing a record does not hold, names nobody but the authors, holds
no script but its JSON-LD, and is the same bytes from the same records wherever and whenever
it is made. A value the custodian withholds is in `test_corruption.py`.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from test_package import (
    _custodian,
    _supplement,
    built,
    contents,
    paper,
    ready,
    set_paper,
    with_package,
)

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project

LATEX = Path(__file__).parent / "data" / "latex" / "manuscript"
PAGE = "ro-crate-preview.html"

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


def package(root: Path, *options: str) -> None:
    assert main(["package", str(root), "--companion", *options]) == 0


def page(root: Path) -> str:
    return (built(root) / PAGE).read_text(encoding="utf-8")


def section(text: str, name: str) -> str:
    """One section of the page, by its id."""
    found = re.search(rf'<section id="{name}">(.*?)</section>', text, re.DOTALL)
    assert found, name
    return found[1]


def plain(fragment: str) -> str:
    """What a reader reads: the tags left out, the entities read, the spaces folded."""
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _add_limitations(root: Path) -> None:
    main_md = root / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text(encoding="utf-8").replace(
        "# Data availability", "## Limitations\n\nOnly {{results.case.n_cases}} cases were "
        "reported, and *spontaneous* reports are not a sample.\n\n# Data availability", 1),
        encoding="utf-8")  # fmt: skip
    supplement = root / "manuscript" / "supplementary" / "S1_code_lists.md"
    supplement.write_text(supplement.read_text(encoding="utf-8") + "\n## Limitations of the "
                          "code lists\n\nOne event term stands for a case definition.\n",
                          encoding="utf-8")  # fmt: skip


# --------------------------------------------------------------------------- the sections


def test_the_overview_is_the_abstract_the_citation_the_history_and_the_digests(
    project: Path,
) -> None:
    package(ready(project))
    text = section(page(project), "overview")
    said = plain(text)
    assert "The reporting odds ratio was 3.84 (95% CI 2.89 to 5.12)." in said
    assert "{{" not in text
    assert 'Example A, Sample B. Code and results for "Reporting of hepatic injury' in said
    assert "No DOI is recorded yet" in said and "Version 1:" in said
    frozen = json.loads((project / "design" / "plan.frozen.yaml").read_text(encoding="utf-8"))
    written = json.loads((project / "results" / "01_disproportionality.json")
                         .read_text(encoding="utf-8"))["provenance"]["generated_at"]  # fmt: skip
    assert frozen["frozen_at"] in said and written in said
    from manuscript_guard.assurance import fragments_digest

    assert fragments_digest(load_project(project)[0]) in said
    # The package's digest is the one SHA256SUMS gives, less the files made beside the page.
    import hashlib

    from manuscript_guard.deposit.companion import UNDIGESTED

    lines = [line for line in (built(project) / "SHA256SUMS").read_text(encoding="utf-8")
             .splitlines(keepends=True) if line.split("  ", 1)[1].strip() not in UNDIGESTED]
    assert hashlib.sha256("".join(lines).encode("utf-8")).hexdigest() in said


def test_a_recorded_doi_and_date_are_cited(project: Path) -> None:
    ready(project)
    document = paper(project)
    document["package"].update(doi="10.5281/zenodo.1234567", date="2027-01-15")
    set_paper(project, document)
    package(project)
    said = plain(section(page(project), "overview"))
    assert "2027. https://doi.org/10.5281/zenodo.1234567" in said
    assert "2027-01-15 the date the package gives itself" in said


def test_the_key_findings_are_the_abstracts_sentences_that_print_a_value(project: Path) -> None:
    package(ready(project))
    text = section(page(project), "evidence")
    findings = re.search(r"<ol>(.*?)</ol>", text, re.DOTALL)[1]
    items = [plain(item) for item in re.findall(r"<li>(.*?)</li>", findings, re.DOTALL)]
    assert [item.split(" From ")[0] for item in items] == [
        "Disproportionality analysis of a synthetic spontaneous reporting database covering "
        "2015 to 2024, comparing reports of hepatic injury for example-drug against all other "
        "drugs.",
        "Of 4000 reports, 77 described hepatic injury with example-drug.",
        "The reporting odds ratio was 3.84 (95% CI 2.89 to 5.12).",
    ]
    assert items[2].replace(" ,", ",").endswith(
        "From results.ror.point, results.ror.ci_low, results.ror.ci_high")
    assert 'href="#ev-results-ror.point"' in findings


def test_the_evidence_map_names_each_binding_and_the_file_and_script_it_comes_from(
    project: Path,
) -> None:
    package(ready(project))
    text = section(page(project), "evidence")
    row = re.search(r'<tr id="ev-results-ror.point">(.*?)</tr>', text, re.DOTALL)[1]
    assert plain(row).replace(" ,", ",").startswith(
        "results.ror.point 3.84 manuscript/main.md, line 12: Abstract")
    assert 'href="#file-results-01_disproportionality.json"' in row
    sidecar = (project / "results" / "01_disproportionality.json.sha256").read_text("utf-8")
    files = re.search(r'<tr id="file-results-01_disproportionality.json">(.*?)</tr>', text,
                      re.DOTALL)[1]  # fmt: skip
    assert sidecar.split()[0] in files and "analysis/01_disproportionality.py" in files
    assert "table.baseline" in text and "figure.forest" in text


def test_figures_tables_and_models_are_shown_from_their_records(project: Path) -> None:
    package(ready(project))
    text = section(page(project), "displays")
    figure = re.search(r'<figure id="figure-forest">(.*?)</figure>', text, re.DOTALL)[1]
    assert '<img src="data:image/svg+xml;base64,' in figure
    assert "Forest plot of the reporting odds ratio" in figure and "3.84" in figure
    assert "Review: reviewed" in plain(figure)
    assert "<td>77 (18.1)</td>" in text
    assert "Adjusted model  (model.adjusted" in text and "converged:   yes" in text
    # A figure redrawn by hand is no longer the one its record names, and is not shown.
    svg = project / "figures" / "forest.svg"
    svg.write_bytes(svg.read_bytes() + b"<!-- retouched -->\n")
    shutil.rmtree(project / "build" / "package")
    package(project, "--skip-checks")
    figure = re.search(r'<figure id="figure-forest">(.*?)</figure>',
                       section(page(project), "displays"), re.DOTALL)[1]  # fmt: skip
    assert "data:image/svg+xml" not in figure and "Not shown" in figure


def test_methods_say_how_to_run_it_what_it_read_and_where_each_claim_stands(
    project: Path,
) -> None:
    package(ready(project))
    said = plain(section(page(project), "methods"))
    assert "analysis/01_disproportionality.py python analysis/01_disproportionality.py" in said
    assert "data/reports.csv" in said and "yes: declared synthetic" in said
    assert "The Methods were last read against the code on" in said
    assert "ror analysis/01_disproportionality.py:" in said
    assert "No run of verify is recorded" in said
    assert main(["verify", str(project)]) in (0, 1)
    shutil.rmtree(project / "build" / "package")
    package(project)
    said = plain(section(page(project), "methods"))
    ran_on = json.loads((project / "build" / "verify.json").read_text("utf-8"))["ran_on"]
    assert f"On {ran_on}, it re-ran the analysis and reproduced" in said


def test_limitations_are_the_manuscripts_the_plans_deviations_g12_and_what_no_gate_checks(
    project: Path,
) -> None:
    ready(project)
    _add_limitations(project)
    package(project)
    text = section(page(project), "limitations")
    said = plain(text)
    assert "Only 77 cases were reported, and spontaneous reports are not a sample." in said
    assert "<em>spontaneous</em>" in text
    assert "Limitations of the code lists (supplement) One event term" in said
    assert "Six. The first two came after the first review round" in said
    assert "<ol" in text, "the plan's list is a list"
    assert "<strong>info</strong> <code>plan-complete</code> (<code>design/plan.md</code>)" \
        in text  # fmt: skip
    assert "analysis plan covers all" not in text, "a finding's words are check's"
    assert "<strong>methodological validity</strong>: whether the design supports the " \
           "conclusion" in text  # fmt: skip


def test_co_author_verification_counts_by_author_and_says_whose_approval_stands(
    project: Path,
) -> None:
    ready(project)
    assert main(["approve", str(project), "--as", "Ada Example"]) == 0
    package(project)
    said = plain(section(page(project), "verification"))
    assert re.search(r"Ada Example: approved it on \d{4}-\d{2}-\d{2}, as it stands", said)
    assert "Blaise Sample: has not approved it" in said
    from manuscript_guard.cli import _checking_items

    # Each answer carries the digest of the item as it is: one without counts for nothing.
    first, second = ((str(item["id"]), str(item["digest"])) for item in
                     _checking_items(load_project(project)[0], None).items[:2])  # fmt: skip
    checks = project / "checks"
    checks.mkdir(exist_ok=True)
    (checks / "decisions.csv").write_text(
        "when,by,id,group,title,status,note,digest,bundle\n"
        f"2026-10-01,Blaise Sample,{first[0]},g,t,ok,,{first[1]},b\n"
        f"2026-10-01,Pat Checker,{second[0]},g,t,wrong,,{second[1]},b\n",
        encoding="utf-8")  # fmt: skip
    shutil.rmtree(project / "build" / "package")
    package(project)
    text = page(project)
    assert "Pat Checker" not in text
    said = plain(section(text, "verification"))
    assert "Blaise Sample 1 0 0" in said and "others, not authors 0 1 0" in said


# ------------------------------------------------------------- who is named, what is quoted


def test_no_name_but_the_authors_and_no_passage_word_is_shown(project: Path) -> None:
    ready(project)
    authors = yaml.safe_load((project / "authors.yaml").read_text(encoding="utf-8"))
    authors["roles"]["statistician"] = {"name": "Stella Statistician"}
    (project / "authors.yaml").write_text(yaml.safe_dump(authors, allow_unicode=True),
                                          encoding="utf-8")  # fmt: skip
    passages = project / "literature" / "passages.yaml"
    document = yaml.safe_load(passages.read_text(encoding="utf-8"))
    document["passages"][0].update(support="supports", judged_by="Jane Judge",
                                   judged_on="2026-10-20")  # fmt: skip
    passages.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    package(project)
    text = page(project)
    for name in ("Claude Code", "claude-opus-5", "Stella Statistician", "Jane Judge"):
        assert name not in text, name
    assert "Ada Example" in text and "Blaise Sample" in text
    cited = re.search(r'<tr id="passage-1">(.*?)</tr>', text, re.DOTALL)[1]
    assert "@fictionalClassSignal2019" in cited and "Abstract, Results" in cited
    assert "2026-10-20" in cited
    assert "A signal was detected for the class as a whole" not in text


def test_a_gates_finding_is_shown_by_its_code_and_place_never_its_words(
    project: Path, monkeypatch
) -> None:
    """A G12 message may name whoever a record names: the page gives the code and where it
    stands, and the words are `check`'s to say."""
    import manuscript_guard.gates.design as design
    from manuscript_guard.findings import WARN, Finding, Report

    ready(project)
    plan = project / "design" / "plan.md"
    monkeypatch.setattr(design, "check_design", lambda *a, **k: Report((Finding(
        "G12", "plan-read-by", "read by Rex Reviewer on 2026-01-01", severity=WARN,
        path=plan, line=3),)))  # fmt: skip
    package(project)
    text = section(page(project), "limitations")
    assert "Rex Reviewer" not in text
    assert "<code>plan-read-by</code> (<code>design/plan.md:3</code>)" in text


def test_the_page_changes_no_word_to_keep_a_name_off_it(project: Path) -> None:
    """Nothing is taken out of the text after it is written: a checker called "Ana" or
    "Ada", who is no author, leaves "Analysis" and the author Ada Example as they are."""
    from manuscript_guard.cli import _checking_items

    ready(project)
    first, second = ((str(item["id"]), str(item["digest"])) for item in
                     _checking_items(load_project(project)[0], None).items[:2])  # fmt: skip
    (project / "checks").mkdir(exist_ok=True)
    (project / "checks" / "decisions.csv").write_text(
        "when,by,id,group,title,status,note,digest,bundle\n"
        f"2026-10-01,Ana,{first[0]},g,t,ok,,{first[1]},b\n"
        f"2026-10-01,Ada,{second[0]},g,t,ok,,{second[1]},b\n",
        encoding="utf-8")  # fmt: skip
    package(project)
    text = page(project)
    assert "Disproportionality analysis of a synthetic" in text
    assert "Ada Example" in section(text, "verification")
    assert ">Ana<" not in text and ">Ada<" not in text
    assert "others, not authors 2 0 0" in plain(section(text, "verification"))


def test_a_heading_opening_an_abstract_paragraph_keeps_the_sentence_under_it(
    project: Path,
) -> None:
    ready(project)
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text(encoding="utf-8").replace(
        "**Background.**", "### Results\nThe ROR was {{results.ror.point}}.\n\n**Background.**",
        1), encoding="utf-8")  # fmt: skip
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    findings = re.search(r"<ol>(.*?)</ol>", section(page(project), "evidence"), re.DOTALL)[1]
    assert "The ROR was 3.84." in plain(findings)


def test_the_plans_comments_are_not_printed(project: Path) -> None:
    ready(project)
    plan = project / "design" / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "## Deviations from the plan\n", "## Deviations from the plan\n\n<!-- a note to self "
        "-->\n", 1), encoding="utf-8")  # fmt: skip
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    text = section(page(project), "limitations")
    assert "a note to self" not in text and "Six. The first two came" in plain(text)


def test_a_crate_with_no_date_to_give_is_refused_with_the_page_too(project: Path) -> None:
    from test_package import edit_fragment

    from manuscript_guard.deposit import plan_package

    ready(project)

    def undated(document: dict) -> None:
        document["provenance"]["generated_at"] = "some time last week"

    edit_fragment(project, undated)
    loaded, _ = load_project(project)
    _namespace, results, _literature, _ = load_namespace(loaded)
    codes = {f.code for f in plan_package(loaded, results, companion=True).report.failures}
    assert "package-crate-undated" in codes
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 1
    assert not (project / "build" / "package").exists()


def test_a_record_the_page_cannot_read_leaves_the_other_packages_to_sign(
    project: Path, capsys
) -> None:
    """An approval that does not parse stops the page, with a message, and not the custodian's
    sign-off of the package without it."""
    ready(project)
    _custodian(project)
    document = paper(project)
    document["custodian"] = {"restricts_sending": True}
    set_paper(project, document)
    approvals = project / "approvals"
    approvals.mkdir()
    (approvals / "0000-0002-1825-0097.yaml").write_text(
        "schema: manuscript-guard/approval/1\nauthor: Ada Example\napproved_on: 2026-09-31\n"
        f"document_sha256: {'a' * 64}\n", encoding="utf-8")  # fmt: skip
    capsys.readouterr()
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit"]) == 0  # fmt: skip
    assert "not offered for signing" in capsys.readouterr().err
    assert main(["package", str(project), "--companion"]) == 2
    said = capsys.readouterr().err
    assert "--companion: the page cannot be made:" in said and "Traceback" not in said


def _restricted_sending(root: Path) -> None:
    _custodian(root)
    document = paper(root)
    document["custodian"] = {"restricts_sending": True}
    set_paper(root, document)


def test_anything_that_stops_the_page_leaves_the_rest_to_sign(
    project: Path, monkeypatch, capsys
) -> None:
    """A ValueError from a record nobody foresaw, and a pandoc that cannot say its version:
    `sign` leaves out the page's variant alone, saying why, and `package --companion` stops
    with a message."""
    import manuscript_guard.deposit.companion as companion
    import manuscript_guard.deposit.prose as prose

    ready(project)
    _restricted_sending(project)

    def broken(*_args, **_kwargs):
        raise ValueError("a record nobody foresaw")

    monkeypatch.setattr(companion, "companion_html", broken)
    capsys.readouterr()
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit"]) == 0  # fmt: skip
    assert "not offered for signing: PackageError" in capsys.readouterr().err
    assert main(["package", str(project), "--companion"]) == 2
    assert "ValueError: a record nobody foresaw" in capsys.readouterr().err
    monkeypatch.undo()

    def silent() -> str:
        raise prose.ProseError("pandoc could not be run: denied")

    monkeypatch.setattr(prose, "pandoc_version", silent)
    assert main(["package", str(project), "--companion"]) == 2
    assert "pandoc could not say its version" in capsys.readouterr().err
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit-ro-crate"]) == 0  # fmt: skip


def test_a_hand_edited_render_record_is_no_match_and_no_crash(project: Path) -> None:
    ready(project)
    record = project / "figures" / "forest.render.json"
    document = json.loads(record.read_text(encoding="utf-8"))
    document["rendered_by"] = "../elsewhere/forest.py"
    record.write_text(json.dumps(document), encoding="utf-8")
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    figure = re.search(r'<figure id="figure-forest">(.*?)</figure>',
                       section(page(project), "displays"), re.DOTALL)[1]  # fmt: skip
    assert "data:image/svg+xml" not in figure and "Not shown" in figure


def test_a_figure_a_record_ties_to_a_withheld_file_is_not_shown(project: Path) -> None:
    from manuscript_guard.deposit.companion import companion_html

    ready(project)
    with_package(project, share=[], request="Apply to the custodian.")
    record = project / "figures" / "forest.render.json"
    document = json.loads(record.read_text(encoding="utf-8"))
    document["inputs"] = ["data/event_terms.txt"]
    record.write_text(json.dumps(document), encoding="utf-8")
    package(project)
    figure = re.search(r'<figure id="figure-forest">(.*?)</figure>',
                       section(page(project), "displays"), re.DOTALL)[1]  # fmt: skip
    assert "data:image/svg+xml" not in figure
    assert "drawn from <code>data/event_terms.txt</code>, which the package withholds" in figure
    # And where a run of the figure's script declares it read a withheld file.
    del document["inputs"]
    record.write_text(json.dumps(document), encoding="utf-8")
    loaded, results, plan = _loaded(project)
    drawn = replace(results, fragments=tuple(replace(f, generated_by="figures/forest.py")
                                             for f in results.fragments))  # fmt: skip
    text = companion_html(loaded, drawn, list(plan.entries), list(plan.inputs))
    figure = re.search(r'<figure id="figure-forest">(.*?)</figure>', text, re.DOTALL)[1]
    assert "data:image/svg+xml" not in figure and "which the package withholds" in figure


def test_a_reading_not_filed_is_placed_by_its_round_never_by_its_reader(project: Path) -> None:
    ready(project)
    design = project / "review" / "design"
    design.mkdir(parents=True)
    (design / "panel-1.yaml").write_text(yaml.safe_dump({
        "schema": "manuscript-guard/panel/1", "round": 1, "opened_on": "2026-08-01",
        "manuscript_sha256": "a" * 64, "blinded": False, "rationale": "The design.",
        "reviewers": [{"id": "methods", "role": "Methodologist", "remit": "The design.",
                       "why": "It is the design.", "readers": ["Jane Doe"]}],
    }), encoding="utf-8")  # fmt: skip
    package(project)
    text = section(page(project), "limitations")
    assert "design-review-missing" in text
    assert "<code>review/design/round-1/</code>" in text
    assert "jane-doe" not in page(project) and "Jane Doe" not in page(project)


def test_g12_is_given_at_the_projects_stage(project: Path) -> None:
    ready(project)
    document = paper(project)
    document["study_type"] = "trial"
    set_paper(project, document)
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    text = section(page(project), "limitations")
    assert "<strong>info</strong> <code>registration-missing</code>" in text


def test_the_model_cards_list_only_what_g15_says_under_a_card(project: Path, monkeypatch) -> None:
    import manuscript_guard.gates.models as models
    from manuscript_guard.findings import WARN, Finding, Report

    ready(project)
    monkeypatch.setattr(models, "check_models", lambda *a, **k: Report((
        Finding("G15", "model-carded", "model 'adjusted': a word of the card", severity=WARN),
        Finding("G15", "methods-model-unfitted", "the Methods name a model none fitted",
                severity=WARN))))  # fmt: skip
    package(project)
    text = section(page(project), "displays")
    assert "<code>model-carded</code>" in text and "methods-model-unfitted" not in text
    assert "a word of the card" not in text


def test_the_checkers_items_unread_are_said_without_a_path_and_nothing_is_printed(
    project: Path, monkeypatch, capsys
) -> None:
    import manuscript_guard.cli as cli
    from manuscript_guard.checking.items import ItemsError

    ready(project)

    def unread(found, named):
        print("NOISE to stdout")
        print("NOISE to stderr", file=__import__("sys").stderr)
        raise ItemsError(f"{found.root / 'checks' / 'items.json'} cannot be read: bad")

    monkeypatch.setattr(cli, "_checking_items", unread)
    capsys.readouterr()
    package(project)
    said = capsys.readouterr()
    assert "NOISE" not in said.out and "NOISE" not in said.err
    text = section(page(project), "verification")
    assert "The checker's items could not be read" in text
    assert str(project) not in text and project.as_posix() not in text


def test_no_record_text_can_address_a_piece_of_the_prose(project: Path) -> None:
    ready(project)
    document = paper(project)
    document["title"] = "A" + chr(0) + "0" + chr(0) + "99" + chr(0) + " title"
    set_paper(project, document)
    # G0 refuses the title, and a package made all the same holds a page that is whole.
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    text = page(project)
    assert chr(0) not in text
    assert "<h1>A099 title</h1>" in text
    # The abstract is where it was, and the title is not swapped for a piece of the prose.
    assert "The reporting odds ratio was 3.84" in plain(section(text, "overview"))


def test_a_setext_heading_in_the_abstract_is_no_sentence(project: Path) -> None:
    ready(project)
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text(encoding="utf-8").replace(
        "**Background.**", "Results first\n-------------\nThe ROR was {{results.ror.point}}.\n\n"
        "**Background.**", 1), encoding="utf-8")  # fmt: skip
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    findings = re.search(r"<ol>(.*?)</ol>", section(page(project), "evidence"), re.DOTALL)[1]
    items = [plain(item) for item in re.findall(r"<li>(.*?)</li>", findings, re.DOTALL)]
    assert any(item.startswith("The ROR was 3.84.") for item in items)
    assert not any("Results first" in item or "-----" in item for item in items)


# --------------------------------------------------------------------------- the page itself


def test_the_page_holds_no_script_but_its_json_ld_and_that_parses(project: Path) -> None:
    ready(project)
    document = paper(project)
    document["title"] = "A </script><script>alert(1)</script> & <b>title</b>"
    set_paper(project, document)
    main_md = project / "manuscript" / "main.md"
    main_md.write_text(main_md.read_text(encoding="utf-8").replace(
        "**Background.**", "<script>alert(2)</script> ![x](figures/forest.png) "
        "[a link](javascript:alert(3)) **Background.**", 1), encoding="utf-8")  # fmt: skip
    assert main(["package", str(project), "--companion", "--skip-checks"]) == 0
    text = page(project)
    assert text.count("<script") == 1 and text.count("</script>") == 1
    assert "javascript:" not in text and "<img src=\"figures/" not in text
    found = re.search(r'<script type="application/ld\+json">(.*?)</script>', text, re.DOTALL)
    described = json.loads(found[1])
    assert described["@type"] == "ScholarlyArticle"
    assert described["headline"] == document["title"]
    assert described["author"][0]["@id"] == "https://orcid.org/0000-0002-1825-0097"
    assert described["author"][0]["affiliation"][0]["name"].startswith("Department of")
    assert described["license"] == "https://spdx.org/licenses/MIT"
    assert {"@id": "ro-crate-metadata.json"} in described["isBasedOn"]
    assert described["version"] == "1"
    assert "src=\"http" not in text and "href=\"http://" not in text.split("</head>")[0]


def test_the_page_and_its_copy_are_in_the_package_and_only_when_asked(project: Path) -> None:
    ready(project)
    assert main(["package", str(project), "--ro-crate"]) == 0
    assert PAGE not in contents(built(project))
    shutil.rmtree(project / "build" / "package")
    package(project)
    folder = built(project)
    assert (folder / PAGE).read_bytes() == (folder / "index.html").read_bytes()
    assert {"ro-crate-metadata.json", "RELATIONS.md"} <= contents(folder)
    manifest = yaml.safe_load((folder / "MANIFEST.yaml").read_text(encoding="utf-8"))
    assert manifest["companion_written_with"].startswith("pandoc ")
    assert "`ro-crate-preview.html`" in (folder / "README.md").read_text(encoding="utf-8")
    # The page is the crate's preview, not one of its data: the crate does not list it.
    crate = (folder / "ro-crate-metadata.json").read_text(encoding="utf-8")
    assert PAGE not in crate and '"index.html"' not in crate


def test_without_pandoc_the_companion_is_refused_and_the_rest_is_not(
    project: Path, monkeypatch, capsys
) -> None:
    import manuscript_guard.deposit.prose as prose

    ready(project)
    monkeypatch.setattr(prose.shutil, "which", lambda name: None)
    assert main(["package", str(project), "--companion"]) == 2
    assert "--companion writes the page's prose with pandoc" in capsys.readouterr().err
    assert not (project / "build" / "package").exists()
    assert main(["package", str(project), "--ro-crate"]) == 0


def test_no_clock_and_no_path_of_the_computer(project: Path) -> None:
    from manuscript_guard import __version__

    package(ready(project))
    text = page(project)
    for form in (str(project), project.as_posix(), str(project.parent)):
        assert form not in text
    assert __version__ not in text
    assert "\r" not in text
    # Every date the page holds is a record's.
    recorded = "".join(path.read_text(encoding="utf-8", errors="replace")
                       for path in project.rglob("*") if path.is_file() and "build" not in
                       path.relative_to(project).parts and path.suffix in
                       (".json", ".yaml", ".lock", ".md", ".csv"))  # fmt: skip
    for found in set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)):
        assert found in recorded, found


def test_the_page_is_the_same_bytes_twice_and_from_another_folder(
    project: Path, tmp_path: Path
) -> None:
    package(ready(project))
    first = (built(project) / PAGE).read_bytes()
    package(project)
    assert (built(project) / PAGE).read_bytes() == first
    elsewhere = tmp_path / "elsewhere" / "deeper" / "paper"
    shutil.copytree(project, elsewhere, ignore=shutil.ignore_patterns("build"))
    package(elsewhere)
    assert (built(elsewhere) / PAGE).read_bytes() == first


def _loaded(root: Path):
    from manuscript_guard.deposit import plan_package

    loaded, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(loaded)
    return loaded, results, plan_package(loaded, results, ro_crate=True)


def test_the_bytes_do_not_depend_on_the_order_the_records_are_read_in(project: Path) -> None:
    """A property: the fragments, and the values, tables, models and steps they hold, read in
    any order, give the same page."""
    from manuscript_guard.deposit.companion import companion_html

    ready(project)
    _supplement(project)
    loaded, results, plan = _loaded(project)
    entries, inputs = list(plan.entries), list(plan.inputs)
    once = companion_html(loaded, results, entries, inputs)
    assert len(results.fragments) == 2

    @settings(max_examples=4, deadline=None, derandomize=True,
              suppress_health_check=[HealthCheck.function_scoped_fixture])  # fmt: skip
    @given(st.randoms(use_true_random=False))
    def shuffled(random) -> None:
        def mixed(mapping: dict) -> dict:
            items = list(mapping.items())
            random.shuffle(items)
            return dict(items)

        fragments = list(results.fragments)
        random.shuffle(fragments)
        other = replace(results, fragments=tuple(fragments), values=mixed(results.values),
                        tables=mixed(results.tables), models=mixed(results.models),
                        steps=mixed(results.steps), variables=mixed(results.variables))
        assert companion_html(loaded, other, list(reversed(entries)),
                              list(reversed(inputs))) == once  # fmt: skip

    shuffled()


# ------------------------------------------------------------------- LaTeX, the supplement


def test_a_latex_manuscript_is_shown_as_a_markdown_one_is(project: Path) -> None:
    ready(project)
    shutil.rmtree(project / "manuscript")
    shutil.copytree(LATEX, project / "manuscript")
    package(project)
    text = page(project)
    evidence = section(text, "evidence")
    assert "The reporting odds ratio was 3.84 (95% CI 2.89 to 5.12)." in plain(evidence)
    assert "manuscript/main.tex</code>, line" in evidence
    assert "manuscript/supplementary/main.tex" in evidence.split("<h4>Supplement</h4>")[1]
    figure = re.search(r'<figure id="figure-forest">(.*?)</figure>',
                       section(text, "displays"), re.DOTALL)[1]  # fmt: skip
    assert "The estimate and its interval." in figure
    assert "\\mg" not in text and "{{" not in text


def test_the_supplement_has_a_part_of_its_own(project: Path) -> None:
    ready(project)
    _supplement(project)
    package(project)
    text = page(project)
    supplement = section(text, "evidence").split("<h4>Supplement</h4>")[1]
    assert "results.supplement.n_sites" in supplement and "table.sites" in supplement
    displays = section(text, "displays")
    assert "table.sites" in displays.split("<h4>Supplement</h4>")[1]
    assert "<td>North</td>" in displays
    assert 'id="file-results-02_supplement.json"' in text


# --------------------------------------------------------------------- the custodian


def test_a_custodian_signs_the_companion_package_as_its_own(project: Path, capsys) -> None:
    ready(project)
    _custodian(project)
    document = paper(project)
    document["custodian"] = {"restricts_sending": True}
    set_paper(project, document)
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit-ro-crate"]) == 0  # fmt: skip
    assert main(["package", str(project), "--ro-crate"]) == 0
    shutil.rmtree(project / "build" / "package")
    # The page is a file the custodian has not seen: a package of its own, signed apart.
    assert main(["package", str(project), "--companion"]) == 1
    capsys.readouterr()
    assert main(["sign", str(project), "--as", "Sample", "--finding",
                 "PACKAGE/custodian/deposit-companion"]) == 0  # fmt: skip
    package(project)


# ------------------------------------------------------------------------- the prose


def test_prose_is_written_with_nothing_that_runs_loads_or_leads_elsewhere() -> None:
    from manuscript_guard.deposit.prose import html_fragments, inline

    written = html_fragments([
        "A ![picture](x.png) and [a link](javascript:alert(1)), [the web](https://e.org), "
        "<b onclick=\"x()\">raw</b> and a note[^1].\n\n[^1]: The note's words.",
        "# A heading\n\n`code`{onclick=\"x()\"} and [a span]{.c onclick=\"x()\"}",
        "unclosed\n\n```\nfence",
        "after the fence",
    ])  # fmt: skip
    joined = "\n".join(written)
    assert "<img" not in joined
    assert "javascript:" not in joined
    assert not re.search(r"<[a-z][^>]*onclick", joined), "an attribute was written"
    assert "&lt;b onclick" in written[0], "raw HTML is read as text"
    assert '<a href="https://e.org">the web</a>' in written[0]
    assert "[The note’s words.]" in written[0] or "[The note's words.]" in written[0]
    assert written[1].startswith("<h3>A heading</h3>")
    assert inline(written[3]) == "after the fence"
