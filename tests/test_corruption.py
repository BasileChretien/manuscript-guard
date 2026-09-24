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


def test_a_binding_cut_in_half_is_caught(project: Path) -> None:
    """The shape a bad merge leaves: an opening `{{` and a key with no closing brace at all.

    `import --apply` once spliced a reworded paragraph at an offset a reorder had already
    moved, and left `{{lit.agency.withdrawnWhether the signal extends...` in the source.
    The loose pattern needed at least one closing brace to call anything a placeholder, so
    `check` reported nothing wrong and `build` printed the fragment into the document.
    """
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "{{lit.agency.withdrawn_estimate}}", "{{lit.agency.withdrawn"
        ),
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
        "(95% CI {{results.ror.ci_low}} to {{results.ror.ci_high}})",
        "(95% CI {{results.ror.ci_high}} to {{results.ror.ci_low}})",
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


def _add_second_interval(project: Path, low: float, high: float, level: str = "90%") -> None:
    """Give `ror.point` a second interval, the way `interval(level=…)` writes one."""
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    slug = "".join(c for c in level if c.isalnum()).lower()
    for end, number in (("low", low), ("high", high)):
        document["values"][f"ror.ci{slug}_{end}"] = {
            "value": number,
            "display": f"{number:.2f}",
            "digits": 2,
            "bounds": "ror.point",
            "bound": end,
            "level": level,
        }
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def test_a_second_interval_is_not_a_duplicated_bound(project: Path) -> None:
    """Two intervals on one estimate is ordinary; four ends on one interval is not.

    The bracketing check groups by (estimate, level), so declaring a 90% CI beside the 95%
    gives two intervals rather than one with two lower bounds. Without the level it is a
    duplicate, and rightly.
    """
    _add_second_interval(project, 2.51, 5.87)
    assert not codes(gate_report(project)) & {"bound-duplicated", "estimate-outside-interval"}


def test_a_second_interval_is_checked_like_the_first(project: Path) -> None:
    """Naming a level must not be a way to stop the estimate being checked against it."""
    _add_second_interval(project, 4.10, 5.87)
    report = gate_report(project)
    assert "estimate-outside-interval" in codes(report)
    assert any("90%" in (f.message or "") for f in report.failures), report.render(project)


def test_two_levels_quoted_in_one_sentence_are_not_compared(project: Path) -> None:
    """"3.84 (95% CI 2.10 to 7.02; 90% CI 2.51 to 5.87)" is one sentence and two intervals.

    Comparing the positions across levels made the 90% lower bound follow the 95% upper one
    and read as a reversal — a false positive on the exact sentence the feature exists for.
    """
    _add_second_interval(project, 2.51, 5.87)
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\nThe estimate was {{results.ror.point}} (95% CI {{results.ror.ci_low}} to "
        "{{results.ror.ci_high}}; 90% CI {{results.ror.ci90_low}} to "
        "{{results.ror.ci90_high}}).\n",
        encoding="utf-8",
    )
    assert "interval-reversed" not in codes(gate_report(project))


def test_the_second_interval_is_still_read_for_order(project: Path) -> None:
    """Levels must partition the check, not switch it off."""
    _add_second_interval(project, 2.51, 5.87)
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\nThe 90% interval ran {{results.ror.ci90_high}} to {{results.ror.ci90_low}}.\n",
        encoding="utf-8",
    )
    report = gate_report(project)
    assert "interval-reversed" in codes(report)
    assert any("90%" in (f.message or "") for f in report.failures)


def _publish_text(project: Path, key: str, text: str, *, quoted: bool = True, **extra) -> None:
    """Add a string value to the fragment, and quote it in the manuscript if it is quoted."""
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"][key] = {"value": text, "display": text, "quoted": quoted, **extra}
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    if not quoted:
        return
    main = project / "manuscript" / "main.md"
    main.write_text(
        main.read_text(encoding="utf-8") + f"\n\nIn conclusion, {{{{results.{key}}}}}.\n",
        encoding="utf-8",
    )


def test_a_claim_published_as_a_value_is_reported(project: Path) -> None:
    """The one route by which text escapes everything that reads text.

    A results key holding a sentence substitutes into the manuscript, resolves, and passes —
    while leaving the manuscript sources, which is where the writing gate reads prose. So a
    causal claim nobody wrote in the paper, and nothing checked, reached the page.
    """
    _publish_text(project, "spin.conclusion", "The drug causes liver failure")
    assert "prose-as-value" in {f.code for f in gate_report(project).findings}


def test_a_name_declared_as_a_name_is_not_reported(project: Path) -> None:
    """`label=True` already means "a name, not a measurement", and keeping a drug name in
    one place is a perfectly good reason to publish a string."""
    _publish_text(project, "study.drug", "example-drug", label=True)
    assert "prose-as-value" not in {f.code for f in gate_report(project).findings}


def test_an_unquoted_string_is_nobody_s_business(project: Path) -> None:
    """The rule is about what reaches the page, not about what the analysis holds."""
    _publish_text(project, "notes.internal", "a working note", quoted=False)
    assert "prose-as-value" not in {f.code for f in gate_report(project).findings}


def test_the_example_publishes_no_prose(project: Path) -> None:
    assert "prose-as-value" not in {f.code for f in gate_report(project).findings}


def test_the_examples_own_interval_brackets_its_estimate(project: Path) -> None:
    clean = codes(gate_report(project))
    assert not clean & {
        "estimate-outside-interval",
        "interval-inverted",
        "bound-dangling",
        "bound-duplicated",
    }


# ------------------------------------------------- line endings are not a change


def test_rewriting_the_analysis_to_crlf_is_not_a_change(project: Path) -> None:
    """A checkout must not be able to fake `script-newer`.

    This repository's own .gitattributes pins `eol=lf` and its comment records why: "CI
    failed exactly that way on Ubuntu and macOS while passing on the machine the digests
    were computed on." A project scaffolded by `init` got no such file, so the fix
    protected the toolkit and not the people using it. An author on Windows with
    core.autocrlf=true records a CRLF digest, a co-author on Linux checks out LF, and G1
    reports that a script nobody touched has changed.

    The bytes differ here; the code does not. That distinction is the whole finding.
    """
    script = project / "analysis" / "01_disproportionality.py"
    as_lf = script.read_bytes().replace(b"\r\n", b"\n")
    script.write_bytes(as_lf.replace(b"\n", b"\r\n"))

    assert "script-newer" not in codes(gate_report(project))


def test_a_real_edit_still_fails_after_a_crlf_rewrite(project: Path) -> None:
    """The obvious wrong fix — normalise, then compare loosely — must not blind the gate.

    Line endings are excused; a changed statement is not, whatever the file's line endings.
    """
    script = project / "analysis" / "01_disproportionality.py"
    as_lf = script.read_bytes().replace(b"\r\n", b"\n") + b"\n# changed\n"
    script.write_bytes(as_lf.replace(b"\n", b"\r\n"))

    assert "script-newer" in codes(gate_report(project))


@pytest.mark.parametrize(
    ("recorded_as", "on_disk_as"),
    [(b"\r\n", b"\n"), (b"\n", b"\r\n"), (b"\r", b"\n"), (b"\n", b"\r")],
)
def test_a_legacy_digest_survives_a_change_of_checkout(
    project: Path, recorded_as: bytes, on_disk_as: bytes
) -> None:
    """A digest recorded before `source_digest` existed was taken over raw bytes.

    Which bytes those were depends on the checkout that produced it, so the record and the
    working tree can disagree about line endings while agreeing about the code. The
    CRLF-recorded / LF-current direction is the likeliest of all — recorded on Windows, then
    normalised by git — and it was the one combination still broken when this only accepted
    the normalised digest and today's raw digest. Both hashed the LF bytes; neither matched
    the CRLF record; G1 reported `script-newer` for a script nobody had touched.
    """
    import hashlib

    script = project / "analysis" / "01_disproportionality.py"
    as_lf = script.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["provenance"]["generated_by_sha256"] = hashlib.sha256(
        as_lf.replace(b"\n", recorded_as)
    ).hexdigest()
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    script.write_bytes(as_lf.replace(b"\n", on_disk_as))
    assert "script-newer" not in codes(gate_report(project))


def test_a_legacy_digest_does_not_excuse_an_edited_script(project: Path) -> None:
    """Accepting three spellings of one file must not become accepting a different file."""
    import hashlib

    script = project / "analysis" / "01_disproportionality.py"
    as_lf = script.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["provenance"]["generated_by_sha256"] = hashlib.sha256(
        as_lf.replace(b"\n", b"\r\n")
    ).hexdigest()
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    script.write_bytes(as_lf + b"\n# changed\n")
    assert "script-newer" in codes(gate_report(project))


# -------------------------------------------------------------------------------------- G7
# Citation integrity against a running Zotero, simulated: the fake answers as Better BibTeX
# 9.0.64 does (see tests/test_zotero.py), so these run anywhere.


def _g7(root: Path):
    from manuscript_guard.gates import check_citations

    project, _ = load_project(root)
    _namespace, _results, literature, _ = load_namespace(project)
    return check_citations(project, literature)


def _zotero(monkeypatch, items: list[dict]) -> None:
    from test_zotero import FakeBBT

    from manuscript_guard.zotero import client, reset_cache

    reset_cache()
    monkeypatch.setattr(client, "rpc", FakeBBT(items))
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: True)


def test_an_unpinned_cited_key_is_caught(project: Path, monkeypatch) -> None:
    from test_zotero import CLASS, HEPATIC, csl

    _zotero(monkeypatch, [csl(HEPATIC, True), csl(CLASS, False)])
    report = _g7(project)
    unpinned = [f for f in report.failures if f.code == "citation-key-unpinned"]
    assert [f.message for f in unpinned] == [f"@{CLASS} is not pinned in Zotero"]
    assert f"Citation Key: {CLASS}" in unpinned[0].hint


def test_a_cited_key_carried_by_two_items_is_caught(project: Path, monkeypatch) -> None:
    """The duplicate that made Better BibTeX refuse the whole export in a real project."""
    from test_zotero import CLASS, HEPATIC, csl

    _zotero(monkeypatch, [csl(HEPATIC, True), csl(CLASS, True), csl(CLASS, False)])
    report = _g7(project)
    assert "citation-key-ambiguous" in codes(report)
    assert "citation-unresolved" not in codes(report)


def test_a_wrapped_citation_to_a_missing_item_is_caught(project: Path, monkeypatch) -> None:
    """The first key of a group that wraps onto a new line was invisible to G7 and to
    sync-bib (neither the bracketed nor the narrative pattern found it)."""
    from test_zotero import CLASS, HEPATIC, csl

    main = main_md(project)
    wrapped = f"\nA wrapped claim [@ghostKey2020;\n@{HEPATIC}].\n"
    main.write_text(main.read_text(encoding="utf-8") + wrapped, encoding="utf-8")
    _zotero(monkeypatch, [csl(HEPATIC, True), csl(CLASS, True)])
    report = _g7(project)
    assert any(
        f.code == "citation-unresolved" and "ghostKey2020" in f.message for f in report.failures
    )


# ------------------------------------------------------------------------------ audit
# `audit` is the weak check, set membership against the outputs, and says so. These are the
# ways it was weaker than it said: a wrong number that matched, and wrong numbers it never
# looked at while reporting the file as audited.

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _p(text: str, style: str | None = None) -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def _docx(path: Path, body: str, parts: dict[str, str] | None = None) -> Path:
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        document = f"<w:document {W}><w:body>{body}</w:body></w:document>"
        archive.writestr("word/document.xml", document)
        for name, xml in (parts or {}).items():
            archive.writestr(name, xml)
    return path


def _outputs(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "out.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_audit_catches_a_sign_flipped_estimate(tmp_path: Path) -> None:
    """The outputs' minus was dropped when they were read, so a paper printing 0.51 for an
    estimate of -0.51 matched, and was reported as found in the outputs."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"log_ror": -0.51}')
    paper = tmp_path / "paper.md"
    paper.write_text("The log reporting odds ratio was 0.51.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["0.51"]


def test_audit_reads_an_appendix_after_the_references(tmp_path: Path) -> None:
    """Everything after the reference heading was dropped, appendices included."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77, "sens": 4.56}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "We saw 77 cases.\n\n# References\n\nSmith J. T. Lancet. 2019;393:1-2.\n\n"
        "# Appendix 1\n\nThe sensitivity estimate was 4.65.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["4.65"]
    assert report.unmatched[0].line == 9, "line numbers must still point into the file"


def test_audit_reads_the_footnotes_of_a_document_with_references(tmp_path: Path) -> None:
    """A .docx is read body first and notes after, so the reference heading in the body cut
    every footnote and endnote along with the bibliography."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77, "excluded": 12}')
    footnote = _p("Twenty-one, or 21, were excluded.")
    notes = f"<w:footnotes {W}><w:footnote>{footnote}</w:footnote></w:footnotes>"
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We saw 77 cases.") + _p("References") + _p("Smith J. T. Lancet. 2019;393:1-2."),
        {"word/footnotes.xml": notes},
    )
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["21"]


def test_audit_reads_a_styled_appendix_after_the_references(tmp_path: Path) -> None:
    """In Word the end of the reference list is the next heading, which only its style says."""
    from manuscript_guard.audit import audit

    styles = (
        f"<w:styles {W}>"
        '<w:style w:type="paragraph" w:styleId="Titre1"><w:name w:val="heading 1"/></w:style>'
        "</w:styles>"
    )
    outputs = _outputs(tmp_path, '{"n": 77, "sens": 4.56}')
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We saw 77 cases.")
        + _p("References", "Titre1")
        + _p("Smith J. T. Lancet. 2019;393:1-2.")
        + _p("Supplementary appendix", "Titre1")
        + _p("The sensitivity estimate was 4.65."),
        {"word/styles.xml": styles},
    )
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["4.65"]


def test_audit_does_not_count_an_outlined_figure_as_audited(tmp_path: Path) -> None:
    """matplotlib's default draws labels as paths: every number in the figure is there to
    see, none is text, and the figure was listed as audited with nothing unmatched."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    figure = tmp_path / "forest.svg"
    figure.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 L10 10"/></svg>', encoding="utf-8"
    )
    report = audit([], [outputs], figures=[figure])
    assert figure not in report.papers
    assert any("forest.svg" in item and "no text" in item for item in report.unreadable)


@pytest.mark.parametrize(
    "sentence",
    [
        "Overall, Japanese patients accounted for 99 of 8,393 cases reported in 2010-2019.",
        "Finally, FAERS data from 2004 to 2023 showed 99 cases.",
        "However, VigiBase showed 99/412 in 2021.",
        "However, Smith (2019) reported 99 cases.",
        "Previously, J. Smith et al. (2019) reported 99 cases.",
        "However, Smith, Jones and Brown (2019) reported 99 cases.",
        # The numbered-style shape: a word, one to four capitals, a comma, then "year;digit".
        "Stage III, diagnosed between 2010 and 2020; 99 patients were excluded.",
        "Group B, enrolled from January 2015 to December 2019; 99 completed follow-up.",
        # A narrative citation ends a sentence with the signature "(2019).", so the words
        # between the name and the year have to be names, not prose.
        "Notably, Japan and Korea contributed 99 of 8,393 cases, in line with Smith (2019).",
        "Similarly, Smith and colleagues found 99 cases in Japan (2019).",
        # A caption ending a clause with "Dec. 2019; 2:1" has a full stop before the year and a
        # volume-and-page shape after it. An entry ends at its pages; a caption goes on.
        "Figure A. Enrolment from Jan. 2017 to Dec. 2019; 2:1 randomisation. Events 99 of 8,393.",
        "Table B. Cases diagnosed in 2020 vs. 2019; 1:4 matched controls; 99 of 8,393.",
        "Panel B. Follow-up ended Dec. 2019; 3:1 allocation; 99 events.",
    ],
)
def test_audit_does_not_take_a_body_paragraph_for_a_reference(
    tmp_path: Path, sentence: str
) -> None:
    """The author-year shape was a capitalised word, a comma, another capitalised word and a
    year within 200 characters. In a .docx a line is a whole paragraph, so a paragraph opening
    "Overall, Japanese patients ..." was a reference entry, and every number in it was counted
    among "conventions or references" and never compared with anything."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 8393, "total": 412}')
    paper = tmp_path / "paper.md"
    paper.write_text(sentence + "\n", encoding="utf-8")
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert any(text.split("/")[0] == "99" for text in unmatched), unmatched


def test_audit_does_not_guess_at_references_once_a_heading_found_them(tmp_path: Path) -> None:
    """In Markdown a line is a physical line, so a wrapped paragraph can open on anything.
    Once a heading has said where the reference list is, nothing else is a reference."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 412}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "Reports came from three countries: Japan, Korea and China. Of those from\n"
        "Japan, Korea. 1985. There were 99 cases among 412 reports.\n\n"
        "# References\n\nSmith J, Jones K. Title. Lancet. 2019;393:1-2.\n",
        encoding="utf-8",
    )
    assert "99" in [c.text for c in audit([paper], [outputs]).unmatched]


def test_audit_reads_utf16_outputs_as_text_not_digits(tmp_path: Path) -> None:
    """Windows PowerShell 5 writes UTF-16 for `>` and Out-File. Read as UTF-8, every digit
    is followed by a NUL, so "8393,3.84" went into the backing set as 8, 3, 9 and 4: a paper
    printing 3 for anything matched."""
    from manuscript_guard.audit import audit

    outputs = tmp_path / "out.csv"
    outputs.write_text("n,ror\n8393,3.84\n", encoding="utf-16")
    paper = tmp_path / "paper.md"
    paper.write_text("We saw 8393 reports and 3 cases.\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["3"]
    assert {"8393", "3.84"} <= report.backing_values


def test_audit_does_not_take_a_wrapped_line_for_a_references_heading(tmp_path: Path) -> None:
    """A heading may carry a bare number, "5 References", and a hard-wrapped line that
    happened to read "12 references." then hid the rest of the section."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 12, "ror": 3.84}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "We drew on the literature, citing\n12 references.\n"
        "The pooled reporting odds ratio was 9.99.\n\n## Discussion\n\nText.\n",
        encoding="utf-8",
    )
    assert "9.99" in [c.text for c in audit([paper], [outputs]).unmatched]


def test_audit_does_not_take_a_table_header_for_a_references_heading(tmp_path: Path) -> None:
    """A .docx table cell is its own line, so a column headed "References" read as the
    start of the bibliography and hid everything up to the next styled heading."""
    from manuscript_guard.audit import audit

    def cell(text: str) -> str:
        return f"<w:tc>{_p(text)}</w:tc>"

    table = (
        "<w:tbl>"
        f"<w:tr>{cell('Study')}{cell('References')}</w:tr>"
        f"<w:tr>{cell('Cohort A')}{cell('12')}</w:tr>"
        "</w:tbl>"
    )
    outputs = _outputs(tmp_path, '{"n": 12, "ror": 3.84}')
    paper = _docx(tmp_path / "paper.docx", table + _p("The pooled ratio was 9.99."))
    assert "9.99" in [c.text for c in audit([paper], [outputs]).unmatched]


@pytest.mark.parametrize(
    "opening",
    [
        "## Methods\n\n```r\n# References\nlibrary(stats)\n```\n",
        "## Methods\n\n~~~\nReferences\n~~~\n",
        "## Methods\n\n<!--\n# References\n-->\n",
        "## Methods\n\n<!--\nReferences\n-->\n",
        "---\ntitle: A study\n# References\nbibliography: refs.bib\n---\n",
    ],
)
def test_audit_does_not_start_a_reference_list_in_code_or_a_comment(
    tmp_path: Path, opening: str
) -> None:
    """`#` is a comment character in R, Python and YAML, and a line starting with it was a
    heading wherever it stood: `# References` in a code listing, an HTML comment or the
    front matter cut everything after it as a reference list, so no number there was
    compared and `--strict` passed."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = tmp_path / "paper.md"
    paper.write_text(f"{opening}\nThe pooled ROR was 9.99, from 413 cases.\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert {c.text.rstrip(".,") for c in report.unmatched} == {"9.99", "413"}
    assert report.not_audited == []


@pytest.mark.parametrize(
    "references", ["", "References\n\nSmith J, Jones K. A study. Lancet. 2019;393:100-10.\n\n"]
)
def test_audit_reads_prose_after_a_rule_at_the_top(tmp_path: Path, references: str) -> None:
    """`---` followed by a blank line is a horizontal rule, and pandoc prints what follows.
    It was read as front matter running to the next `---`, so the prose between was never
    audited; a reference heading inside it used to cut the closing `---` by accident."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        f"---\n\nThe pooled ROR was 9.99.\n\n{references}---\n\nEnd.\n", encoding="utf-8"
    )
    assert [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched] == ["9.99"]


@pytest.mark.parametrize("blank", ["", "  "])
def test_the_build_prints_the_headings_the_gates_read(blank: str) -> None:
    """The build found the end of the front matter with a pattern of its own. Once the gates
    stopped taking `---` and a blank line for front matter, the build still stripped it: G2
    read the `## Methods` heading inside, so `p < 0.001` after it passed as the alpha chosen
    in advance, and the document printed it with no Methods heading above it."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text.sections import headings

    text = (
        f"---\n{blank}\n## Methods\n\nCases were compared with non-cases.\n\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    )
    body, _title = strip_front_matter(text)
    assert headings(body) == headings(text) == ["Methods"]


def test_audit_does_not_take_a_hash_paragraph_in_word_for_a_heading(tmp_path: Path) -> None:
    """In a .docx only a paragraph's style makes it a heading. A code listing pasted in as
    plain paragraphs, with `# References` among its comments, cut everything after it."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = _docx(
        tmp_path / "paper.docx",
        _p("# References") + _p("library(stats)") + _p("The pooled ROR was 9.99."),
    )
    report = audit([paper], [outputs])
    assert [c.text.rstrip(".") for c in report.unmatched] == ["9.99"]
    assert report.not_audited == []


def test_audit_reads_every_reference_list_and_what_lies_between(tmp_path: Path) -> None:
    """Only the first heading was used, so a second reference list (an appendix's own) was
    read as prose, and the first list's shape detection was off for the whole file."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "We saw 77 cases.\n\n# References\n\nSmith J. T. Lancet. 2019;393:1-2.\n\n"
        "# Appendix\n\nThe estimate was 9.99.\n\n## References\n\n"
        "Jones K. T. BMJ. 2020;368:m1.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["9.99"]
    assert len(report.not_audited) == 2


def test_audit_does_not_turn_json_escapes_into_numbers(tmp_path: Path) -> None:
    """Outputs were re-serialised with every non-ASCII character escaped, so "β" became
    "\u03b2" and put 3 and 2 in the backing set, and "0.72–0.82" gave 20130.82."""
    import json as json_module

    from manuscript_guard.audit import audit

    outputs = tmp_path / "out.json"
    document = {"ci": "0.72–0.82", "term": "β (age)", "n": 77}
    outputs.write_text(json_module.dumps(document, ensure_ascii=False), encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("We saw 77 reports and 3 cases, 0.72-0.82.\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["3"]
    assert "20130.82" not in report.backing_values


def test_audit_reads_an_appendix_after_the_references_in_a_crlf_file(tmp_path: Path) -> None:
    """Bytes decoded by hand keep their carriage returns, and a setext underline followed
    by one is not an underline: the appendix under it was cut with the references."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77, "sens": 4.56}')
    paper = tmp_path / "paper.md"
    paper.write_bytes(
        b"We saw 77.\r\n\r\nReferences\r\n----------\r\n\r\nSmith J. T. Lancet. 2019;393:1-2."
        b"\r\n\r\nAppendix\r\n--------\r\n\r\nThe estimate was 4.65.\r\n"
    )
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["4.65"]


def test_audit_does_not_take_a_wrapped_sentence_end_for_a_references_heading(
    tmp_path: Path,
) -> None:
    """"references." alone on a line is where a hard wrap left the end of a sentence."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"screened": 1204, "kept": 412}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "## Results\n\nWe screened 1,204 records and kept 412 after removing duplicate\n"
        "references.\nThe pooled reporting odds ratio was 9.99.\n\n## Discussion\n\nText.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["9.99"]
    assert report.not_audited == []


def test_audit_keeps_the_sign_of_a_number_inside_a_json_string(tmp_path: Path) -> None:
    """Re-serialised, a tab in a string became the text "\t", and the "t" before "-0.51"
    stopped the minus being read as a sign: 0.51 in the paper matched."""
    import json as json_module

    from manuscript_guard.audit import audit

    outputs = tmp_path / "out.json"
    outputs.write_text(json_module.dumps({"table": "term\tlog_ror\nage\t-0.51"}), "utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The log reporting odds ratio for age was 0.51.\n", encoding="utf-8")
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["0.51"]


def test_audit_does_not_take_a_caption_for_a_numbered_reference(tmp_path: Path) -> None:
    """"Figure A." reads as "Smith J." and "2019; 1:4" as "2019;393:100": in a file with no
    references heading, the caption's numbers were never compared."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 8393, "cases": 412}')
    paper = tmp_path / "supplement.md"
    paper.write_text(
        "Figure A. Case-control design, 2010 to 2019; 1:4 matching on age and sex. "
        "Cases 413 of 8,393; ROR 9.99.\n",
        encoding="utf-8",
    )
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert "413" in unmatched and "9.99" in unmatched, unmatched


@pytest.mark.parametrize(
    "caption",
    [
        "Figure A. Events 413 of 8,393 from Jan. 2017 to Dec. 2019; 2:1.",
        "Figure A. Enrolment Jan. 2017 to Dec. 2019; 2:1 [@smith2019]. Events 413 of 8,393.",
    ],
)
def test_audit_never_drops_a_number_on_a_line_read_as_a_reference(
    tmp_path: Path, caption: str
) -> None:
    """Four review rounds each found a caption the reference shapes accepted, and every
    number on an accepted line went uncompared. However the shapes are tuned, a caption can
    be written to fit one, so an accepted line is now compared like any other and its
    unmatched numbers are listed apart."""
    from manuscript_guard.audit import audit, measure_discrimination, render

    outputs = _outputs(tmp_path, '{"n": 8393, "cases": 412}')
    paper = tmp_path / "supplement.md"
    paper.write_text(caption + "\n", encoding="utf-8")
    report = audit([paper], [outputs])
    shown = [c.text for c in [*report.unmatched, *report.reference_like]]
    assert "413" in shown, shown
    assert "413" in render(report, measure_discrimination(report.backing_values))


def test_audit_keeps_a_negative_bound_after_a_hyphen(tmp_path: Path) -> None:
    """A minus after the separator was never read as a sign: an output written by R's
    `paste0(lo, "-", hi)` as "-0.72--0.30" went in as -0.72 and 0.3, so a paper printing a
    confidence interval of -0.72 to 0.30, one crossing zero, matched."""
    from manuscript_guard.audit import audit

    outputs = tmp_path / "table.csv"
    outputs.write_text("term,estimate,ci\nexposure,-0.51,-0.72--0.30\n", encoding="utf-8")
    paper = tmp_path / "paper.md"
    paper.write_text("The estimate was -0.51 (95% CI -0.72 to 0.30).\n", encoding="utf-8")
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert len(unmatched) == 1 and unmatched[0].startswith("0.30"), unmatched


@pytest.mark.parametrize("interval", ["−0.72-−0.30", "(−0.72/−0.30)"])
def test_audit_catches_a_flipped_upper_bound_written_with_a_minus_sign(
    tmp_path: Path, interval: str
) -> None:
    """U+2212 can only be a minus, and after a hyphen or slash it was read as nothing, so a
    paper printing -0.30 for an output of +0.30 matched."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"lo": -0.72, "hi": 0.30}')
    paper = tmp_path / "paper.md"
    paper.write_text(f"The interval was {interval} in this analysis.\n", encoding="utf-8")
    assert len(audit([paper], [outputs]).unmatched) == 1


def test_audit_reads_code_in_a_markdown_output_as_written(tmp_path: Path) -> None:
    """Pandoc leaves `--` alone inside code, and knitr puts R's console output in code
    blocks, so "-0.72--0.30" there runs to -0.30: rewriting it as an en dash made a paper
    printing an upper bound of 0.30 match."""
    from manuscript_guard.audit import audit

    outputs = tmp_path / "model.md"
    outputs.write_text(
        '```\n## [1] "-0.72--0.30"\n```\n\nInline `-0.51--0.10` too.\n', encoding="utf-8"
    )
    paper = tmp_path / "paper.txt"
    paper.write_text("The interval was -0.72 to 0.30, and -0.51 to 0.10.\n", encoding="utf-8")
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert any(t.startswith("0.30") for t in unmatched), unmatched
    assert any(t.startswith("0.10") for t in unmatched), unmatched


def test_audit_reads_an_indented_code_block_as_written(tmp_path: Path) -> None:
    """knitr's md_document writes R's console output as four-space indented code, where
    pandoc renders "--" as written: the bound is -0.30, not 0.30."""
    from manuscript_guard.audit import audit

    outputs = tmp_path / "model.md"
    outputs.write_text('Output:\n\n    ## [1] "-0.72--0.30"\n', encoding="utf-8")
    paper = tmp_path / "paper.txt"
    paper.write_text("The interval was -0.72 to 0.30.\n", encoding="utf-8")
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert any(t.startswith("0.30") for t in unmatched), unmatched


def test_audit_reads_prose_between_html_comments(tmp_path: Path) -> None:
    """Rewriting "2-->" as an en dash broke the comment's close, and the masking then ran to
    the next comment's end and swallowed the sentence between them."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "<!--Table 2-->\n\nThe ROR was 9.99 in 413 cases.\n\n<!-- end of results -->\n",
        encoding="utf-8",
    )
    assert {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched} == {"9.99", "413"}


@pytest.mark.parametrize(
    "bound",
    [
        "<w:r><w:noBreakHyphen/><w:t>0.30</w:t></w:r>",
        '<w:r><w:sym w:font="Symbol" w:char="F02D"/><w:t>0.30</w:t></w:r>',
    ],
)
def test_audit_reads_a_minus_word_writes_as_an_element(tmp_path: Path, bound: str) -> None:
    """A non-breaking hyphen (Ctrl+Shift+-) and a Symbol-font minus are elements, not
    text, and the reader dropped them: "-0.72 to -0.30" read as "-0.72 to 0.30" and matched
    an output interval running to +0.30."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"lo": -0.72, "hi": 0.30}')
    body = f"<w:p><w:r><w:t xml:space=\"preserve\">CI -0.72 to </w:t></w:r>{bound}</w:p>"
    paper = _docx(tmp_path / "paper.docx", body)
    unmatched = [c.text for c in audit([paper], [outputs]).unmatched]
    assert any(t.endswith("0.30") for t in unmatched), unmatched


def test_audit_keeps_numbers_either_side_of_a_line_break_apart(tmp_path: Path) -> None:
    """A manual line break was dropped, so a stacked cell "-0.51 / -0.72 to -0.30" read as
    the range "-0.51-0.72", and -0.72 matched an output of +0.72."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.51, "lo": 0.72, "hi": -0.30}')
    body = (
        "<w:p><w:r><w:t>-0.51</w:t><w:br/><w:t xml:space=\"preserve\">-0.72 to -0.30</w:t>"
        "</w:r></w:p>"
    )
    paper = _docx(tmp_path / "paper.docx", body)
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["-0.72"]


@pytest.mark.parametrize("change", ["del", "moveFrom"])
@pytest.mark.parametrize(
    "layout", ["<w:br/>", "<w:cr/>", "<w:tab/>", '<w:ptab w:alignment="left"/>']
)
def test_audit_reads_nothing_for_a_deleted_line_break(
    tmp_path: Path, change: str, layout: str
) -> None:
    """A line break or a tab deleted, or moved away, as a tracked change read as a space
    where Word shows nothing. A minus before one lost its number, so "−0.30" matched an
    output of +0.30, and "-0.51" read as -0.5 and 1, which matched two outputs the paper
    never printed."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.5, "n": 1, "hi": 0.30}')

    def around(before: str, after: str) -> str:
        gone = f'<w:{change} w:id="1" w:author="a"><w:r>{layout}</w:r></w:{change}>'
        return (
            f'<w:p><w:r><w:t xml:space="preserve">{before}</w:t></w:r>{gone}'
            f"<w:r><w:t>{after}</w:t></w:r></w:p>"
        )

    paper = _docx(
        tmp_path / "paper.docx",
        around("The estimate was -0.5", "1.") + around("Its upper bound was −", "0.30."),
    )
    shown = {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched}
    assert shown == {"-0.51", "−0.30"}, shown


def test_audit_does_not_read_text_moved_away(tmp_path: Path) -> None:
    """A tracked move leaves the text at its old place as well as its new one, and the old
    one ran into its neighbours: "-0.5" beside a "1" moved elsewhere read as -0.51."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.51}')
    moved = '<w:moveFrom w:id="1" w:author="a"><w:r><w:t>1</w:t></w:r></w:moveFrom>'
    body = f"<w:p><w:r><w:t>The estimate was -0.5</w:t></w:r>{moved}<w:r><w:t>.</w:t></w:r></w:p>"
    paper = _docx(tmp_path / "paper.docx", body)
    assert [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched] == ["-0.5"]


def _gone(change: str, style: str | None = None) -> str:
    """The properties of a paragraph whose mark was deleted or moved away."""
    styled = f'<w:pStyle w:val="{style}"/>' if style else ""
    return f'<w:pPr>{styled}<w:rPr><w:{change} w:id="1" w:author="a"/></w:rPr></w:pPr>'


@pytest.mark.parametrize("change", ["del", "moveFrom"])
@pytest.mark.parametrize(
    "between",
    ["", '<w:bookmarkStart w:id="9" w:name="_Ref1"/><w:bookmarkEnd w:id="9"/>'],
    ids=["adjacent", "bookmark-between"],
)
def test_audit_joins_paragraphs_whose_mark_was_removed(
    tmp_path: Path, change: str, between: str
) -> None:
    """A paragraph whose mark was deleted, or moved away, as a tracked change runs on into
    the next once the change is accepted, and the audit read the two as separate lines: "−"
    ending one and "0.30" starting the next matched an output of +0.30, and "-0.5" then "1"
    matched -0.5 and 1 where the paper prints -0.51. A bookmark between them does not part
    them."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.5, "n": 1, "hi": 0.30}')

    def joined(before: str, after: str) -> str:
        run = f'<w:r><w:t xml:space="preserve">{before}</w:t></w:r>'
        return f"<w:p>{_gone(change)}{run}</w:p>{between}{_p(after)}"

    paper = _docx(
        tmp_path / "paper.docx",
        joined("The estimate was -0.5", "1.") + joined("Its upper bound was −", "0.30."),
    )
    shown = {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched}
    assert shown == {"-0.51", "−0.30"}, shown


@pytest.mark.parametrize(
    "props",
    [
        '<w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs>',
        '<w:pPrChange w:id="2" w:author="a"><w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/>'
        "</w:tabs></w:pPr></w:pPrChange>",
    ],
    ids=["tab-stops", "tab-stops-before-the-change"],
)
def test_audit_joins_a_paragraph_that_sets_tab_stops(tmp_path: Path, props: str) -> None:
    """A tab stop is `w:tab` too, under `w:pPr/w:tabs`, and was read as a typed tab: a
    space at the start of the paragraph's line, where it did no harm until a join put it
    between "-0.5" and "1". Word writes the old tab stops into `w:pPrChange` when it copies
    the first paragraph's formatting onto the second."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.5, "n": 1}')
    before = "<w:r><w:t>The estimate was -0.5</w:t></w:r>"
    after = f"<w:p><w:pPr>{props}</w:pPr><w:r><w:t>1.</w:t></w:r></w:p>"
    paper = _docx(tmp_path / "paper.docx", f"<w:p>{_gone('del')}{before}</w:p>{after}")
    shown = {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched}
    assert shown == {"-0.51"}, shown


@pytest.mark.parametrize("joined", [False, True])
def test_audit_reads_a_paragraph_whole_around_a_text_box(tmp_path: Path, joined: bool) -> None:
    """A text box's paragraphs were read where its anchor sits, in the middle of the paragraph
    holding it, so the rest of that paragraph, or the one it runs on into, landed on the text
    box's line: "-0.5", a text box, then "1" read as -0.5, which matched."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.5, "n": 1}')
    box = (
        '<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml"><v:textbox>'
        f"<w:txbxContent>{_p('Panel A')}</w:txbxContent></v:textbox></v:shape></w:pict></w:r>"
    )
    before = "<w:r><w:t>The estimate was -0.5</w:t></w:r>"
    if joined:
        body = f"<w:p>{_gone('del')}{before}{box}</w:p>{_p('1.')}"
    else:
        body = f"<w:p>{before}{box}<w:r><w:t>1.</w:t></w:r></w:p>"
    paper = _docx(tmp_path / "paper.docx", body)
    shown = {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched}
    assert shown == {"-0.51"}, shown


def test_audit_reports_a_number_in_a_text_box_once(tmp_path: Path) -> None:
    """Word writes every text box twice: as DrawingML, and again in VML inside an
    AlternateContent fallback for readers that predate it. Both copies were read, so a wrong
    number in a text box was reported twice, on two lines, and took two of the forty findings
    listed for its file; a right one was counted twice as found."""
    from manuscript_guard.audit import audit, measure_discrimination, render

    outputs = _outputs(tmp_path, '{"n": 412}')
    content = f"<w:txbxContent>{_p('Cases: 412 of 8393.')}</w:txbxContent>"
    mc = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
    vml = 'xmlns:v="urn:schemas-microsoft-com:vml"'
    box = (
        f"<w:r><mc:AlternateContent {mc}>"
        f'<mc:Choice Requires="wps"><w:drawing>{content}</w:drawing></mc:Choice>'
        f"<mc:Fallback><w:pict><v:shape {vml}><v:textbox>{content}</v:textbox></v:shape>"
        "</w:pict></mc:Fallback></mc:AlternateContent></w:r>"
    )
    paper = _docx(tmp_path / "paper.docx", f"<w:p><w:r><w:t>See the box.</w:t></w:r>{box}</w:p>")
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["8393"], report.unmatched
    assert [c.text for c in report.matched] == ["412"], report.matched
    shown = render(report, measure_discrimination(report.backing_values))
    assert "1 found in the outputs, 1 not found." in shown, shown


def test_audit_reads_an_emoji_word_writes_only_as_a_choice(tmp_path: Path) -> None:
    """Word writes an emoji it inserts as `w16se:symEx` in an AlternateContent choice, and the
    character itself only in the fallback. With the fallback unread and the choice not
    understood, the numbers either side ran together: "12", an emoji and "34" read as 1234,
    which matched an output the paper never printed."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1234}')
    mc = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
    se = 'xmlns:w16se="http://schemas.microsoft.com/office/word/2015/wordml/symex"'
    emoji = (
        f'<w:r><mc:AlternateContent {mc} {se}><mc:Choice Requires="w16se">'
        '<w16se:symEx w16se:font="Segoe UI Emoji" w16se:char="1F642"/></mc:Choice>'
        f"<mc:Fallback><w:t>{chr(0x1F642)}</w:t></mc:Fallback></mc:AlternateContent></w:r>"
    )
    body = f"<w:p><w:r><w:t>Scored 12</w:t></w:r>{emoji}<w:r><w:t>34.</w:t></w:r></w:p>"
    report = audit([_docx(tmp_path / "paper.docx", body)], [outputs])
    assert report.matched == [], report.matched
    assert [c.text.rstrip(".") for c in report.unmatched] == [f"12{chr(0x1F642)}34"]


def test_audit_reads_past_a_deleted_text_box_in_the_reference_list(tmp_path: Path) -> None:
    """A deleted text box's text was dropped, but its paragraphs still started lines. One
    styled as a heading was an empty heading, which ended the reference list there, and the
    entries after it were reported as numbers missing from the outputs."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    box = (
        '<w:del w:id="2" w:author="a"><w:r><w:drawing><w:txbxContent>'
        f"{_p('Old panel', 'Heading1')}</w:txbxContent></w:drawing></w:r></w:del>"
    )
    entry = f"<w:p><w:r><w:t>Smith J. Lancet. 2019;393:1-2.</w:t></w:r>{box}</w:p>"
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We found 77 cases.")
        + _p("References", "Heading1")
        + entry
        + _p("Jones K. BMJ. 2020;368:45-52."),
    )
    report = audit([paper], [outputs])
    assert report.unmatched == [], report.unmatched
    assert report.not_audited == ["paper.docx: lines 3-5, read as the reference list"]


def test_audit_reads_an_appendix_whose_heading_a_reference_ran_into(tmp_path: Path) -> None:
    """A paragraph run on into a heading takes the heading's style, which is what Word shows
    once the change is accepted. Taking the first paragraph's instead read the appendix as
    part of the reference list, and a wrong number in it went unaudited."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77, "sens": 4.56}')
    entry = "<w:r><w:t>Smith J. T. Lancet. 2019;393:1-2.</w:t></w:r>"
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We saw 77 cases.")
        + _p("References", "Heading1")
        + f"<w:p>{_gone('del')}{entry}</w:p>"
        + _p("Supplementary appendix", "Heading1")
        + _p("The sensitivity estimate was 4.65."),
    )
    assert "4.65" in [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched]


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("out.txt", "estimate –0.51 (95% CI –0.72 to –0.30)\n"),
        ("out.md", "The estimate was $-0.51$, CI $-0.72$ to $-0.30$.\n"),
    ],
)
def test_audit_reads_a_typeset_minus_in_the_outputs(
    tmp_path: Path, name: str, content: str
) -> None:
    """Values copied from a typeset PDF carry an en dash for a minus, and LaTeX writes
    `$-0.51$`; both went into the backing set as positive, so a paper that lost every sign
    matched."""
    from manuscript_guard.audit import audit

    outputs = tmp_path / name
    outputs.write_text(content, encoding="utf-8")
    paper = tmp_path / "paper.txt"
    paper.write_text("The estimate was 0.51 (95% CI 0.72 to 0.30).\n", encoding="utf-8")
    shown = {c.text.strip("().") for c in audit([paper], [outputs]).unmatched}
    assert {"0.51", "0.72", "0.30"} <= shown, shown
