"""The corruption harness: does the gate actually catch what it claims to?

A checker that reports "all clear" on a clean project has demonstrated nothing. Its
predecessor in an earlier project passed every day for months and, when finally measured
against fifteen deliberately corrupted headline numbers, caught none of them.

So the headline test here is adversarial and exhaustive rather than illustrative: **every
binding in the manuscript is replaced, one at a time, by the literal value it currently
resolves to**, and each of those manuscripts must fail. This is the hardest version of the
problem, because at the moment of corruption the number on the page is still *correct* —
it is stale only in waiting. A checker that compares numbers against a backing set passes
all of them. This one has to fail all of them, because in source a results-derived number
may not be a literal at all.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import write_digest
from manuscript_guard.findings import merge_all
from manuscript_guard.gates import check_consistency, check_figures, check_freshness, check_numbers


def gate_report(root: Path):
    project, contract_report = load_project(root)
    namespace, results, literature, load_report = load_namespace(project)
    return merge_all(
        [
            contract_report,
            load_report,
            check_freshness(project, results),
            check_numbers(project, namespace, results, literature),
            check_figures(project, results),
            check_consistency(results),
        ]
    )


def codes(report) -> set[str]:
    return {f.code for f in report.failures}


def main_md(root: Path) -> Path:
    return root / "manuscript" / "main.md"


def bindings_in(text: str) -> list[str]:
    return re.findall(r"\{\{(?:results|lit)\.[a-z0-9_.]+\}\}", text)


# --------------------------------------------------------------------------------------
# The baseline. Everything below is meaningless if this fails.
# --------------------------------------------------------------------------------------


def test_clean_example_passes(project: Path) -> None:
    report = gate_report(project)
    assert report.ok, report.render(project)
    assert report.counts["numeric_atoms"] > 0, "a pass over zero numbers is not a pass"
    assert report.counts["bindings"] > 10
    assert report.counts["results_uncovered"] == 0


# --------------------------------------------------------------------------------------
# The headline: every binding, replaced by its own current value, must be caught.
# --------------------------------------------------------------------------------------


def test_every_binding_when_inlined_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    namespace, *_ = load_namespace(load_project(project)[0])[0], None
    resolved = {f"{{{{{ref}}}}}": value.display for ref, value in namespace.items()}

    targets = sorted(set(bindings_in(text)))
    assert len(targets) >= 12, f"the fixture must exercise many bindings, found {len(targets)}"

    escaped: list[str] = []
    for binding in targets:
        literal = resolved[binding]
        corrupted = text.replace(binding, literal)
        main_md(project).write_text(corrupted, encoding="utf-8")
        report = gate_report(project)
        if report.ok:
            escaped.append(f"{binding} -> {literal!r}")
        main_md(project).write_text(text, encoding="utf-8")

    assert not escaped, (
        f"{len(escaped)} of {len(targets)} bindings could be replaced by a hand-typed "
        f"literal without failing the gate:\n  " + "\n  ".join(escaped)
    )


def test_inlining_reports_the_right_reason(project: Path) -> None:
    """Caught is not enough; it has to be caught for the reason the author needs to read."""
    text = main_md(project).read_text(encoding="utf-8")
    namespace = load_namespace(load_project(project)[0])[0]
    binding = "{{results.ror.point}}"
    main_md(project).write_text(
        text.replace(binding, namespace["results.ror.point"].display), encoding="utf-8"
    )
    report = gate_report(project)
    assert "unclassified-number" in codes(report)
    assert "results_uncovered" in report.counts
    # And the coverage side must notice the key is now quoted nowhere.
    assert any(f.code == "unquoted-result" for f in report.failures)


# --------------------------------------------------------------------------------------
# The other ways a number goes wrong.
# --------------------------------------------------------------------------------------


def test_hand_edited_results_file_is_caught(project: Path) -> None:
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["display"] = "9.99"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert "results-edited" in codes(gate_report(project))


def test_a_hand_written_results_fragment_is_caught(project: Path) -> None:
    """The sidecar's absence is the finding, and it has to be a failure.

    While `no-digest` was a warning, an entire fabricated result passed. Write
    `results/national.json` by hand with a headline estimate and a confidence interval no
    analysis ever produced, omit the sidecar because no emitter wrote one, bind the values
    in the manuscript — and `check --submission` came back clean. Nothing else in the
    toolkit looks at a fragment's authorship, so this warning was the only thing between a
    typed number and a cited result.
    """
    fabricated = project / "results" / "national.json"
    fabricated.write_text(
        json.dumps(
            {
                "schema": "manuscript-guard/results/1",
                "provenance": {
                    "generated_by": "analysis/01_disproportionality.py",
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "inputs": [],
                },
                "values": {
                    "national.ror": {"value": 3.84, "display": "3.84", "quoted": True},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    report = gate_report(project)
    assert "no-digest" in codes(report)
    assert any(f.code == "no-digest" for f in report.failures), "a warning let this through"


def test_changed_input_data_is_caught(project: Path) -> None:
    data = project / "data" / "reports.csv"
    extra = "R99999,2024,example-drug,rash,N,F,75+\n"
    data.write_text(data.read_text(encoding="utf-8") + extra, encoding="utf-8")
    assert "input-changed" in codes(gate_report(project))


def test_deleted_input_data_is_caught(project: Path) -> None:
    (project / "data" / "reports.csv").unlink()
    assert "input-missing" in codes(gate_report(project))


def test_modified_analysis_script_is_caught(project: Path) -> None:
    """By content, not by clock.

    This used to bump the mtime and nothing else, and pass — which is also how the check
    was defeated: edit the script for real, then stamp the fragment forward with `touch`,
    and G1 saw an analysis older than its results. It now compares the script's digest
    against the one recorded when the fragment was written. `tests/test_verify.py` holds
    the other half: a touched fragment no longer hides a genuine edit.
    """
    script = project / "analysis" / "01_disproportionality.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    later = time.time() + 10
    os.utime(script, (later, later))
    assert "script-newer" in codes(gate_report(project))


def test_touching_a_script_without_changing_it_is_not_a_change(project: Path) -> None:
    """Re-running a formatter or checking the file out again is not an edit."""
    script = project / "analysis" / "01_disproportionality.py"
    later = time.time() + 10
    os.utime(script, (later, later))
    assert "script-newer" not in codes(gate_report(project))


def test_typo_in_a_binding_is_caught(project: Path) -> None:
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8").replace("{{results.ror.point}}", "{{results.ror.poimt}}"),
        encoding="utf-8",
    )
    report = gate_report(project)
    assert "unresolved-binding" in codes(report)
    assert any("did you mean" in (f.hint or "") for f in report.failures)


def test_malformed_binding_is_caught(project: Path) -> None:
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8").replace("{{results.ror.point}}", "{{ror.point}}"),
        encoding="utf-8",
    )
    assert "malformed-placeholder" in codes(gate_report(project))


def test_unreferenced_result_is_caught(project: Path) -> None:
    """Direction two: a value the analysis declares as quoted that nothing quotes."""
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "{{results.case.n_serious}}", "an unreported number of"
        ),
        encoding="utf-8",
    )
    assert "unquoted-result" in codes(gate_report(project))


def test_hand_authored_table_is_caught(project: Path) -> None:
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n| Group | Reports |\n| --- | --- |\n| example-drug | 987 |\n",
        encoding="utf-8",
    )
    report = gate_report(project)
    assert "hand-authored-table" in codes(report)
    assert any("{{table." in (f.hint or "") for f in report.failures)


def test_edited_figure_number_is_caught(project: Path) -> None:
    svg = project / "figures" / "forest.svg"
    text = svg.read_text(encoding="utf-8")
    svg.write_text(re.sub(r">(\d+\.\d+) \(", ">7.77 (", text, count=1), encoding="utf-8")
    assert "figure-number-unbound" in codes(gate_report(project))


def test_figure_script_that_ignores_results_is_caught(project: Path) -> None:
    script = project / "figures" / "forest.py"
    text = script.read_text(encoding="utf-8")
    script.write_text(
        text.replace('RESULTS = ROOT / "results" / "01_disproportionality.json"', "RESULTS = None")
        .replace('json.loads(RESULTS.read_text(encoding="utf-8"))["values"]', "HARDCODED"),
        encoding="utf-8",
    )
    assert "figure-script-ignores-results" in codes(gate_report(project))


def test_same_quantity_under_two_keys_is_caught(project: Path) -> None:
    """One quantity, two keys, two roundings — 3.84 in one place and 3.8 in another.

    Both displays are honest renderings of the value, which is what makes this the case G8
    exists for: nothing is false, and the paper still contradicts itself.
    """
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.duplicate"] = dict(document["values"]["ror.point"])
    document["values"]["ror.duplicate"]["display"] = "3.8"
    document["values"]["ror.duplicate"]["digits"] = 1
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)  # the edit is legitimate here; we are testing G8, not G1
    assert "divergent-display" in codes(gate_report(project))


def test_a_display_edited_away_from_its_value_is_caught(project: Path) -> None:
    """A bonus from checking displays at emit time: the read path checks them too.

    Re-signing the sidecar hides a hand-edit from G1, but the edited fragment still has to
    be a coherent one. Changing a display to a number the value does not round to now fails
    on load, so the easiest form of the re-signing attack — retype the display, recompute
    the digest — no longer works.
    """
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["ror.point"]["display"] = "9.99"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    assert "no-display" in codes(gate_report(project))


def test_a_projects_own_allowlist_is_reported_not_silent(project: Path) -> None:
    """`conventions:` and `terms:` are self-service on purpose. Invisible is not on purpose.

    A pattern of `\\d+` with a `why` of "house style" is schema-legal and disables G2, and
    the run read exactly like one that had exempted nothing. Every run now says how many
    numbers the project accounted for with its own rules, and which rules did it.
    """
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["conventions"] = [
        {"id": "house-style", "why": "house style", "pattern": r"\d+(?:[.,]\d+)*"}
    ]
    paper.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    main_md(project).write_text(
        main_md(project).read_text(encoding="utf-8") + "\n\nLoose 4321, 9876 and 5.55 here.\n",
        encoding="utf-8",
    )

    report = gate_report(project)
    assert report.counts["atoms_project_exempt"] == 3
    finding = next(f for f in report.findings if f.code == "project-exemption")
    assert "project:house-style" in finding.message


@pytest.mark.parametrize(
    "convention",
    ["p < 0.37", "p < 0.5", "89% CI", "power of 63%"],
)
def test_near_miss_conventions_are_not_waved_through(project: Path, convention: str) -> None:
    """The allowlist is pinned to conventional values, not to the shape of a phrase.

    A rule matching "p < <anything>" would let every reported p-value in the paper through
    as a convention, which is precisely backwards: a p-value you obtained is a result.
    """
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8") + f"\n\nAn added sentence with {convention} in it.\n",
        encoding="utf-8",
    )
    assert "unclassified-number" in codes(gate_report(project))
