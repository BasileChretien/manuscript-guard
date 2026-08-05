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


# ------------------------------------- the table rule, applied to the file rather than the API


def test_a_number_typed_into_a_fragment_table_is_caught(project: Path) -> None:
    """"Tables are emitted, not written" was enforced only inside the Python emitter.

    So it held for exactly as long as Python was the only language that could emit a table,
    and it never held at all for a fragment someone edited afterwards: re-sign the file and
    the cell was never looked at again. G2 now applies the same rule to what is on disk.
    """
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    key = next(iter(document["tables"]))
    document["tables"][key]["rows"][0][2] = "9999"
    document["tables"][key]["composed"] = [
        entry
        for entry in document["tables"][key].get("composed", [])
        if not (entry.get("row") == 0 and entry.get("column") == 2)
    ]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    codes = {f.code for f in gate_report(project).findings}
    assert "unemitted-table-number" in codes


def test_a_transposed_interval_typed_into_a_fragment_is_caught(project: Path) -> None:
    """The multi-claim rule too: every number emitted, in the wrong order."""
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    key = next(iter(document["tables"]))
    document["tables"][key]["rows"][0][2] = "3.84 (5.12 to 2.89)"
    document["tables"][key]["composed"] = [
        entry
        for entry in document["tables"][key].get("composed", [])
        if not (entry.get("row") == 0 and entry.get("column") == 2)
    ]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    codes = {f.code for f in gate_report(project).findings}
    assert "typed-composite-cell" in codes


def test_claiming_a_cell_was_composed_does_not_launder_it(project: Path) -> None:
    """The exemption records what the emitter formatted; the literal is still checked.

    Otherwise the `composed` block would be a way to write anything into a table by adding
    one entry to the fragment beside it.
    """
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    key = next(iter(document["tables"]))
    document["tables"][key]["rows"][0][2] = "9999"
    document["tables"][key]["composed"] = [
        {"row": 0, "column": 2, "template": "9999", "parts": []}
    ]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    codes = {f.code for f in gate_report(project).findings}
    assert "unemitted-table-number" in codes


def test_a_composed_claim_must_rebuild_the_cell_it_is_attached_to(project: Path) -> None:
    """The exemption has to prove itself, or it is just an assertion in a file.

    Checking the declared template instead of the cell meant an entry claiming an empty
    template exempted whatever the cell actually said — zero atoms scanned, so a cell
    reading "True mortality 4281003.55%" passed with nothing reported. The gate now rebuilds
    the cell from the template and parts and requires the result to match.
    """
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    key = next(iter(document["tables"]))
    document["tables"][key]["rows"][0][2] = "True mortality 4281003.55% (fabricated)"
    document["tables"][key]["composed"] = [{"row": 0, "column": 2, "template": "", "parts": []}]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    codes = {f.code for f in gate_report(project).findings}
    assert "composition-does-not-match" in codes


def test_a_composed_part_does_not_whitelist_another_table(project: Path) -> None:
    """Parts excuse their own cell and nowhere else.

    Folded into one project-wide set, a single entry anywhere — even in a table with no rows
    — whitelisted its strings everywhere, so a phantom `parts: ["777777"]` made an unrelated,
    unmarked cell reading "777777" pass.
    """
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["tables"]["poison"] = {
        "columns": ["x"],
        "rows": [],
        "composed": [{"column": 0, "template": "{}", "parts": ["777777"]}],
    }
    key = next(k for k in document["tables"] if k != "poison")
    document["tables"][key]["rows"][0][2] = "777777"
    document["tables"][key]["composed"] = [
        entry
        for entry in document["tables"][key].get("composed", [])
        if not (entry.get("row") == 0 and entry.get("column") == 2)
    ]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    codes = {f.code for f in gate_report(project).findings}
    assert "unemitted-table-number" in codes


# ------------------------------------------------- an interval is a declared thing


def test_an_interval_quoted_backwards_in_prose_is_caught(project: Path) -> None:
    """Both bindings resolve, no literal appears, and the paper prints 7.02 to 2.10.

    Three keys named point, ci_low and ci_high are three unrelated numbers as far as any
    check is concerned. The table path has refused a typed composite cell since round two
    because "a point estimate and its bounds can be transposed and still pass"; prose is
    where that sentence actually gets written.
    """
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    swapped = text.replace(
        "(95% CI {{results.ror.ci_low}} to\n{{results.ror.ci_high}})",
        "(95% CI {{results.ror.ci_high}} to\n{{results.ror.ci_low}})",
    )
    assert swapped != text, "the example must still quote the interval in one sentence"
    path.write_text(swapped, encoding="utf-8")

    codes = {f.code for f in gate_report(project).findings}
    assert "interval-reversed" in codes


def test_the_example_quotes_its_interval_the_right_way_round(project: Path) -> None:
    assert "interval-reversed" not in {f.code for f in gate_report(project).findings}


def test_bounds_in_separate_sentences_are_not_compared(project: Path) -> None:
    """Two intervals in successive sentences say nothing about each other, and a paper may
    legitimately give one bound alone."""
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\nThe upper bound was {{results.ror.ci_high}}. The lower was "
        "{{results.ror.ci_low}}.\n",
        encoding="utf-8",
    )
    assert "interval-reversed" not in {f.code for f in gate_report(project).findings}


def test_restating_a_bound_does_not_invent_a_reversal(project: Path) -> None:
    """"2.10 to 7.02, and the lower bound of 2.10 excludes unity" is ordinary writing.

    The guard meant to keep the *first* mention of each end read `value.bound in seen` while
    the keys were `"{bounds}:{bound}"`, so it never matched and each later mention overwrote
    the position. Restating the lower bound after the upper therefore made a correctly
    ordered interval look reversed — and an author whose only recourse is to delete a true
    sentence learns to distrust the gate.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\nThe interval ran {{results.ror.ci_low}} to {{results.ror.ci_high}}, and a "
        "lower bound of {{results.ror.ci_low}} excludes the null.\n",
        encoding="utf-8",
    )
    assert "interval-reversed" not in {f.code for f in gate_report(project).findings}


def test_restating_a_bound_does_not_hide_a_reversal(project: Path) -> None:
    """The same dead guard, the other way round: the reversal that goes unreported.

    Last-mention-wins moved `high` past `low`, so a sentence that really does print the
    interval backwards passed as long as it went on to name the upper bound again.
    """
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\nThe interval ran {{results.ror.ci_high}} to {{results.ror.ci_low}}, an upper "
        "bound of {{results.ror.ci_high}} in the primary analysis.\n",
        encoding="utf-8",
    )
    assert "interval-reversed" in {f.code for f in gate_report(project).findings}


# ------------------------------------------------- a bound must bracket its estimate


def _rewrite_value(project: Path, key: str, **fields) -> None:
    """Edit one value in the fragment and re-stamp it, so the *freshness* gate stays quiet.

    Without the re-stamp every one of these cases fails on `results-edited` instead, and
    would pass while proving nothing about the check under test.
    """
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"][key].update(fields)
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def test_an_estimate_outside_its_own_interval_is_caught(project: Path) -> None:
    """`interval()` refuses this, and `interval()` was the only thing that did.

    The results fragment is a contract with three other writers — `value(bounds=…)` called
    directly, the R emitter, a hand-edited file — so a point estimate outside its own
    confidence interval reached the page with `check` silent. It is the one arithmetic error
    a reader catches by eye in the first sentence of the Results.
    """
    _rewrite_value(project, "ror.point", value=12.0, display="12.00")
    report = gate_report(project)
    assert "estimate-outside-interval" in codes(report)
    assert any("12.00" in (f.message or "") for f in report.failures)


def test_an_inverted_interval_in_the_fragment_is_caught(project: Path) -> None:
    """Naming them low and high in the analysis does not make them so."""
    _rewrite_value(project, "ror.ci_low", value=7.02, display="7.02")
    _rewrite_value(project, "ror.ci_high", value=2.10, display="2.10")
    assert "interval-inverted" in codes(gate_report(project))


def test_a_bound_of_nothing_is_caught(project: Path) -> None:
    """A bound whose estimate no source publishes claims a check that cannot happen."""
    _rewrite_value(project, "ror.ci_low", bounds="ror.absent")
    assert "bound-dangling" in codes(gate_report(project))


def test_two_lower_bounds_are_caught(project: Path) -> None:
    """Both ends declared `low` left the interval unbracketed and nothing said so."""
    _rewrite_value(project, "ror.ci_high", bound="low")
    assert "bound-duplicated" in codes(gate_report(project))


def test_a_bound_that_cannot_be_compared_says_so(project: Path) -> None:
    """Skipping it silently would make "not checked" read exactly like "checked"."""
    _rewrite_value(project, "ror.ci_low", value="about two", display="about two")
    assert "bound-uncheckable" in codes(gate_report(project))


def test_the_examples_own_interval_brackets_its_estimate(project: Path) -> None:
    clean = codes(gate_report(project))
    assert not clean & {
        "estimate-outside-interval",
        "interval-inverted",
        "bound-dangling",
        "bound-duplicated",
    }
