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

import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import write_digest
from manuscript_guard.findings import merge_all
from manuscript_guard.gates import (
    check_consistency,
    check_figures,
    check_freshness,
    check_models,
    check_numbers,
    check_relations,
)


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
            check_relations(results),
            check_models(project, results),
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


@pytest.mark.parametrize("tail", ["/", "//", ":/", " "])
def test_a_citation_locator_hard_against_punctuation_passes_g2(project: Path, tail: str) -> None:
    """`import` writes `@key [p. 3]/{{results.x}}` when a co-author deletes the words between
    a citation and a value. The locator ran on through its `]` as `3]/`, G2 failed it as an
    unbound number, and the build refused a paragraph pandoc prints correctly."""
    text = main_md(project).read_text(encoding="utf-8")
    probe = f"As @fictionalClassSignal2019 [p. 3]{tail}{{{{results.ror.point}}}} overall."
    main_md(project).write_text(f"{text}\n\n# Probe\n\n{probe}\n", encoding="utf-8")
    report = gate_report(project)
    assert report.ok, report.render(project)


def test_a_value_written_hard_after_a_citation_locator_is_still_caught(project: Path) -> None:
    """Cutting the atom at the locator's `]` must not hide what follows it: 9.99 is a claim."""
    text = main_md(project).read_text(encoding="utf-8")
    probe = "As @fictionalClassSignal2019 [p. 3]/9.99 overall."
    main_md(project).write_text(f"{text}\n\n# Probe\n\n{probe}\n", encoding="utf-8")
    report = gate_report(project)
    messages = [f.message for f in report.failures]
    assert any("9.99" in m for m in messages), messages
    assert not any("'3" in m for m in messages), "the locator is not the unbound number"


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


# An input kept out of the repository by Git LFS or git-annex, as a clone has it where the
# data are not fetched: the pointer at its path, and not the data (item 35).

_LFS_V1 = "version https://git-lfs.github.com/spec/v1\n"


def _reports_record(root: Path) -> dict:
    fragment = next((root / "results").glob("*.json"))
    inputs = json.loads(fragment.read_text(encoding="utf-8"))["provenance"]["inputs"]
    return next(i for i in inputs if i["path"] == "data/reports.csv")


def _not_fetched(root: Path, pointer: str) -> list[tuple[str, str]]:
    """G1's findings about inputs with the example's reports replaced by this pointer."""
    (root / "data" / "reports.csv").write_bytes(pointer.encode("utf-8"))
    return [(f.code, f.severity) for f in gate_report(root).findings
            if f.code.startswith("input")]  # fmt: skip


def _lfs(sha: str, size: int, *extra: str) -> str:
    return _LFS_V1 + "".join(extra) + f"oid sha256:{sha}\nsize {size}\n"


def test_an_input_git_lfs_keeps_is_judged_by_its_pointer(project: Path) -> None:
    """A clone without the data held a pointer where the reports were, and G1 hashed the
    pointer: `input-changed` for an input nobody touched, failing CI from the analysis
    stage. The pointer names the content by its SHA-256 and its size."""
    record = _reports_record(project)
    sha, size = record["raw_sha256"], record["bytes"]
    assert _not_fetched(project, _lfs(sha, size)) == [("input-by-pointer", "info")]
    other = "0" * 64
    assert _not_fetched(project, _lfs(other, size)) == [("input-changed", "fail")]
    assert _not_fetched(project, _lfs(sha, size + 1)) == [("input-changed", "fail")]
    # With an extension the oid is of the content after it: nothing can be compared.
    extended = _lfs(sha, size, f"ext-0-crypt sha256:{sha}\n")
    assert _not_fetched(project, extended) == [("input-not-fetched", "warn")]


@pytest.mark.parametrize(
    ("pointer", "said"),
    [
        ("/annex/objects/SHA256E-s{size}--{sha}.csv\n", "input-by-pointer"),
        ("/annex/objects/SHA256-s{size}--{sha}", "input-by-pointer"),
        # A locked file checked out where links are not made holds the link's target.
        ("../.git/annex/objects/Gq/Xv/SHA256E-s{size}--{sha}.csv/SHA256E-s{size}--{sha}.csv",
         "input-by-pointer"),
        ("/annex/objects/SHA256E-s{size}--{other}.csv\n", "input-changed"),
        # DataLad's default backend names the content by MD5: the size alone is compared.
        ("/annex/objects/MD5E-s{size}--0123456789abcdef0123456789abcdef.csv\n",
         "input-not-fetched"),
        ("/annex/objects/MD5E-s1--0123456789abcdef0123456789abcdef.csv\n", "input-changed"),
    ],
)
def test_an_input_git_annex_keeps_is_judged_by_its_key(project: Path, pointer, said) -> None:
    record = _reports_record(project)
    text = pointer.format(size=record["bytes"], sha=record["raw_sha256"], other="1" * 64)
    [(code, _severity)] = _not_fetched(project, text)
    assert code == said


def test_an_annexed_input_locked_is_a_link_to_nothing(project: Path) -> None:
    """Before, a link whose target is not fetched did not exist, and G1 said
    `input-missing`."""
    record = _reports_record(project)
    data = project / "data" / "reports.csv"
    data.unlink()
    key = f"SHA256E-s{record['bytes']}--{record['raw_sha256']}.csv"
    try:
        os.symlink(f"../.git/annex/objects/Gq/Xv/{key}/{key}", data)
    except OSError as exc:  # pragma: no cover - Windows without the right to make links
        pytest.skip(f"cannot make a symbolic link here: {exc}")
    found = [(f.code, f.severity) for f in gate_report(project).findings
             if f.code.startswith("input")]  # fmt: skip
    assert found == [("input-by-pointer", "info")]


def test_results_that_record_no_raw_digest_say_a_pointer_cannot_be_compared(
    project: Path,
) -> None:
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    record = next(i for i in document["provenance"]["inputs"] if i["path"] == "data/reports.csv")
    sha, size = record.pop("raw_sha256"), record["bytes"]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    assert _not_fetched(project, _lfs(sha, size)) == [("input-not-fetched", "warn")]


def test_a_small_input_that_is_the_data_is_hashed_as_before(project: Path) -> None:
    """The example's event terms are 50 bytes, as small as a pointer, and are the data."""
    terms = project / "data" / "event_terms.txt"
    assert terms.stat().st_size < 1024
    assert [f.code for f in gate_report(project).findings if f.code.startswith("input")] == []
    terms.write_bytes(terms.read_bytes() + b"x")
    assert "input-changed" in codes(gate_report(project))


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


def _estimates_said(project: Path) -> list[str]:
    return [
        f.message.split("(")[0]
        for f in gate_report(project).findings
        if f.code == "figure-estimates"
    ]


@pytest.mark.parametrize(
    ("added", "said"),
    [
        ('sns.barplot(data=frame, x="arm", y="reports")', ["sns.barplot"]),
        ('sns.barplot(data=frame, x="arm", y="reports", errorbar=None)', []),
        ('sns.barplot(data=frame, x="arm", y="reports", seed=2024)', []),
        ('sns.regplot(data=frame, x="dose", y="reports", ci=None)', []),
        ("spread = frame.groupby('arm').reports.std()", [".reports.std"]),
        ("spread = frame.reports.std(ddof=1)", []),
        ("subset = frame.sample(200)", ["frame.sample"]),
        ("np.random.seed(7)\nsubset = frame.sample(200)", []),
        ("kept = frame.dropna()", ["frame.dropna"]),
        ("# sns.barplot(data=frame) in a comment", []),
    ],
)
def test_a_figure_that_estimates_while_it_draws_is_warned(
    project: Path, added: str, said: list[str]
) -> None:
    """A bootstrap interval, a spread whose divisor is unstated, rows sampled or dropped in
    the figure script: none passes through the results, and the random ones change at every
    render. Each is a warning, until the call is told not to or a seed settles it."""
    script = project / "figures" / "forest.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n" + added + "\n", encoding="utf-8")
    assert _estimates_said(project) == said


def test_a_draw_from_a_generator_the_script_made_is_not_read_as_pinned(project: Path) -> None:
    """A known gap (round 1 of #288): `rng.normal` is a method of the generator, not under
    `np.random.`, so an unseeded generator's draws are not warned. DESIGN.md says so."""
    script = project / "figures" / "forest.py"
    added = "rng = np.random.default_rng()\nnoise = rng.normal(size=3)\n"
    script.write_text(script.read_text(encoding="utf-8") + "\n" + added, encoding="utf-8")
    assert _estimates_said(project) == []


def test_an_estimate_with_its_reason_beside_the_figure_is_not_warned(project: Path) -> None:
    script = project / "figures" / "forest.py"
    script.write_text(
        script.read_text(encoding="utf-8")
        + '\nsns.barplot(data=frame, x="arm", y="y")\nsubset = frame.sample(20)\n',
        encoding="utf-8",
    )
    sidecar = project / "figures" / "forest.guard.yaml"
    sidecar.write_text(
        sidecar.read_text(encoding="utf-8")
        + "\nallow_estimates:\n  - value: barplot\n    why: the bars show the raw means\n"
        + "  - value: sample\n",  # no reason, so no exemption
        encoding="utf-8",
    )
    assert _estimates_said(project) == ["frame.sample"]


def test_an_allowlist_section_that_is_no_list_allows_nothing(project: Path) -> None:
    """Round 1 of #288: `allow_estimates: 5` was iterated, raised, and the gate errored."""
    script = project / "figures" / "forest.py"
    script.write_text(script.read_text(encoding="utf-8") + '\nsns.barplot(data=frame)\n',
                      encoding="utf-8")  # fmt: skip
    sidecar = project / "figures" / "forest.guard.yaml"
    sidecar.write_text(sidecar.read_text(encoding="utf-8") + "\nallow_estimates: 5\n",
                       encoding="utf-8")  # fmt: skip
    assert _estimates_said(project) == ["sns.barplot"]


@pytest.mark.parametrize(
    ("script", "said"),
    [
        ("ggplot(d, aes(arm, y)) + stat_summary()", ["stat_summary"]),
        ('ggplot(d, aes(x, y)) + geom_smooth(method = "lm", se = FALSE)', ["geom_smooth"]),
        ("ggplot(d, aes(arm, y)) + geom_jitter(width = 0.2)", ["geom_jitter"]),
        ("ggplot(d, aes(arm, y)) + geom_jitter(seed = NA)", ["geom_jitter"]),
        # Round 1 of #288: geom_jitter takes no seed, and ggplot2 ignores one given to it.
        ("ggplot(d, aes(arm, y)) + geom_jitter(seed = 1)", ["geom_jitter"]),
        ("ggplot(d, aes(arm, y)) + geom_jitter(position = position_jitter(seed = 1))", []),
        ("ggplot(d, aes(arm, y)) + geom_point(position = position_jitter(width = 0.2))",
         ["position_jitter"]),
        ("set.seed(3)\nggplot(d, aes(arm, y)) + geom_jitter()", []),
        ("d <- na.omit(d)", ["na.omit"]),
        ("x <- rnorm(10)", ["rnorm"]),
        ("set.seed(3)\nx <- rnorm(10)", []),
    ],
)
def test_an_r_figure_that_estimates_while_it_draws_is_warned(
    tmp_path: Path, script: str, said: list[str]
) -> None:
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.figure_source import check_figure_source

    path = tmp_path / "funnel.R"
    path.write_text("library(ggplot2)\n" + script + "\n", encoding="utf-8")
    report = check_figure_source(path, Classifier.load())
    found = [f.message.split("(")[0] for f in report.findings if f.code == "figure-estimates"]
    assert found == said


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


def test_a_count_and_a_percentage_that_coincide_are_not_one_quantity(project: Path) -> None:
    """56 sources and 56.0 per cent are two quantities that happen to share a number.

    G8 used to key collisions on the bare value, so this pair reported one quantity written
    two ways and failed the build. There was no fix available to the author except to change
    the paper until the coincidence went away, which is the tool corrupting the manuscript
    rather than protecting it. Units are what distinguish the two, and they are recorded.
    """
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    point = document["values"]["ror.point"]
    document["values"]["ror.point"] = {
        **point, "value": 56.0, "display": "56.0%", "digits": 1, "unit": "%",
    }
    document["values"]["sources.n"] = {
        **point, "value": 56, "display": "56", "digits": 0,
    }
    document["values"]["sources.n"].pop("unit", None)
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    # Verified to fail without the unit key: with G8 grouping on the bare value, this
    # fragment reports divergent-display and the build stops.
    assert "divergent-display" not in codes(gate_report(project))


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


MARGINS = [
    {"kind": "sum", "key": "cohort.n_reports",
     "of": ["table2x2.a", "table2x2.b", "table2x2.c", "table2x2.d"]},
    {"kind": "sum", "key": "cohort.n_drug_reports", "of": ["table2x2.a", "table2x2.b"]},
    {"kind": "in_order", "key": "cohort.period_start", "of": ["cohort.period_end"]},
]  # fmt: skip


def _declare_relations(project: Path, relations: list[dict], flows: dict | None = None,
                       values: dict | None = None) -> dict:  # fmt: skip
    """What `em.relation` and `em.flow` would have written, put in the example's fragment."""
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["relations"] = relations
    if flows:
        document["flows"] = flows
    for key, value in (values or {}).items():
        document["values"][key] = {"value": value, "display": str(value), "quoted": False}
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    return document


def _edit_value(project: Path, key: str, value: int) -> None:
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"][key].update(value=value, display=str(value))
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def test_a_cell_that_no_longer_sums_to_its_margin_is_caught(project: Path) -> None:
    """The four cells of the 2x2 table and its margins: each bound, each passing on its own,
    and nothing held them to each other until the analysis declared it."""
    _declare_relations(project, MARGINS)
    clean = gate_report(project)
    assert not {f.code for f in clean.findings} & {"relation-broken", "relation-unresolved"}
    # The three relations declared here, and the flow the example itself records.
    assert clean.counts["relations_checked"] == 3 + 1
    _edit_value(project, "table2x2.d", 3381)
    assert "relation-broken" in codes(gate_report(project))


def test_a_period_that_ends_before_it_starts_is_caught(project: Path) -> None:
    _declare_relations(project, MARGINS)
    _edit_value(project, "cohort.period_start", 2025)
    assert "relation-broken" in codes(gate_report(project))


def test_a_relation_naming_a_key_nothing_emits_is_caught(project: Path) -> None:
    _declare_relations(project, [{"kind": "sum", "key": "cohort.n_reports",
                                  "of": ["table2x2.a", "table2x2.e"]}])  # fmt: skip
    assert "relation-unresolved" in codes(gate_report(project))


def test_a_flow_stage_that_its_exclusions_do_not_reach_is_caught(project: Path) -> None:
    """A flow diagram's counts, typed by hand, were the one place no check looked."""
    counts = {"flow.screening.stage.1": 4000, "flow.screening.stage.2": 426,
              "flow.screening.excluded.1.1": 3574}  # fmt: skip
    record = {"stages": [{"label": "Reports", "key": "flow.screening.stage.1"},
                         {"label": "Reports of the drug", "key": "flow.screening.stage.2"}],
              "exclusions": [[{"reason": "Another drug", "key": "flow.screening.excluded.1.1"}]],
              "overlapping": False}  # fmt: skip
    _declare_relations(project, [], flows={"screening": record}, values=counts)
    assert not {f.code for f in gate_report(project).findings} & {"flow-broken"}
    _edit_value(project, "flow.screening.excluded.1.1", 3575)
    assert "flow-broken" in codes(gate_report(project))


@pytest.mark.parametrize(
    ("named", "cited"),
    [("house-style", "project:house-style"), (None, r"project:\d+(?:[.,]\d+)*")],
    ids=["named", "unnamed"],
)
def test_a_projects_own_allowlist_is_reported_not_silent(
    project: Path, named: str | None, cited: str
) -> None:
    """`conventions:` and `terms:` are self-service on purpose. Invisible is not on purpose.

    A pattern of `\\d+` with a `why` of "house style" is schema-legal and disables G2, and
    the run read exactly like one that had exempted nothing. Every run now says how many
    numbers the project accounted for with its own rules, and which rules did it: by the
    name the author gave the rule (`id`), or by the start of its pattern.
    """
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    convention = {"why": "house style", "pattern": r"\d+(?:[.,]\d+)*"}
    if named:
        convention["id"] = named
    document["conventions"] = [convention]
    paper.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    main_md(project).write_text(
        main_md(project).read_text(encoding="utf-8") + "\n\nLoose 4321, 9876 and 5.55 here.\n",
        encoding="utf-8",
    )

    report = gate_report(project)
    assert "schema-violation" not in codes(report)
    assert report.counts["atoms_project_exempt"] == 3
    finding = next(f for f in report.findings if f.code == "project-exemption")
    assert cited in finding.message


@pytest.mark.parametrize(
    "conventions",
    [
        pytest.param(r"\d+", id="a pattern where a list is expected"),
        pytest.param([r"\d+"], id="a list of patterns with no reason"),
        pytest.param([{"pattern": r"\d+"}], id="an entry with no reason"),
        pytest.param([{"pattern": r"\d+", "why": ""}], id="an entry with an empty reason"),
        pytest.param(
            [{"pattern": r"(?a)(?u)\d+", "why": "pasted"}], id="a pattern that does not compile"
        ),
    ],
)
def test_a_convention_the_schema_refuses_exempts_nothing(project: Path, conventions) -> None:
    """A `conventions:` in the wrong shape is not read, so the gate runs where it raised. What
    it must not do is read part of it: a pattern with no reason is not an exemption."""
    from manuscript_guard.cli import _run_gates

    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["conventions"] = conventions
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    main_md(project).write_text(
        main_md(project).read_text(encoding="utf-8") + "\n\nLoose 4321 here.\n", encoding="utf-8"
    )

    report, _project, _chosen, _deferred = _run_gates(project)
    assert {"schema-violation", "unclassified-number"} <= codes(report)
    assert "gate-errored" not in codes(report)
    assert report.counts["atoms_project_exempt"] == 0


@pytest.mark.parametrize(
    "conventions",
    [
        pytest.param(
            [
                {"id": "house", "pattern": "7 spare kits", "why": "kept by every site"},
                {"id": "house", "pattern": "13 spare forms", "why": "kept by every site"},
            ],
            id="named alike",
        ),
        pytest.param(
            [
                {"pattern": "(?i)(?:each site kept )?7 spare kits", "why": "kept by every site"},
                {"pattern": "(?i)(?:each site kept )?13 spare forms", "why": "kept by every site"},
            ],
            id="patterns that begin alike",
        ),
    ],
)
def test_conventions_under_one_name_each_exempt_their_own_number(
    project: Path, conventions
) -> None:
    """A rule's matches were kept under its name, so a second convention under the same
    name, an `id` given twice or two patterns whose first 24 characters agree, replaced the
    first one's: the number the first was written for failed as unbound."""
    from manuscript_guard.cli import _run_gates

    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["conventions"] = conventions
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    main_md(project).write_text(
        main_md(project).read_text(encoding="utf-8")
        + "\n\nEach site kept 7 spare kits and 13 spare forms.\n",
        encoding="utf-8",
    )

    report, _project, _chosen, _deferred = _run_gates(project)
    assert "unclassified-number" not in codes(report), report.render(project)
    assert report.counts["atoms_project_exempt"] == 2


def test_a_number_typed_into_a_file_that_is_not_utf8_is_not_a_pass(project: Path) -> None:
    """G2 cannot read the file, so it cannot report the number in it. The run fails all the
    same at every stage, on a finding that names the file, and nothing is built from it."""
    from manuscript_guard.cli import _run_gates, main
    from manuscript_guard.policy import STAGES

    path = main_md(project)
    path.write_bytes(path.read_bytes() + b"\nThe caf\xe9 saw 4321 patients.\n")

    for stage in STAGES:
        report, _project, _chosen, _deferred = _run_gates(project, stage=stage)
        assert "manuscript-unreadable" in codes(report), stage
        assert "gate-errored" not in codes(report), stage
    assert main(["build", str(project), "--offline"]) == 1
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 2
    assert not list((project / "build").rglob("*.docx"))


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


def _in_methods(project: Path, sentence: str) -> None:
    path = main_md(project)
    anchor = "Reporting follows the checklist"
    text = path.read_text(encoding="utf-8")
    assert anchor in text
    path.write_text(text.replace(anchor, f"{sentence}\n\n{anchor}", 1), encoding="utf-8")


def test_an_escaped_threshold_is_still_a_convention(project: Path) -> None:
    """Pandoc's Markdown writer escapes every comparison, so a Methods section converted from
    Word reads `p \\< 0.05` and `ROR \\> 2`; `import` escapes a `>` that a `<` earlier in the
    paragraph could close as a tag. Each prints the bare character. G2 read neither: the
    threshold rules never matched, and `\\>3` was an atom no rule began at."""
    _in_methods(
        project,
        r"Significance was set at p \< 0.05; a signal needed ROR \> 2, IC025 \> 0 and \>3 cases.",
    )
    report = gate_report(project)
    # The example declares its alpha and its case threshold, so the two that equal them fail
    # as typed parameters: a verdict only a number read as a convention can get.
    typed = sorted(f.message.split()[0] for f in report.failures if f.code == "typed-parameter")
    assert typed == ["'0.05'", "'3'"], report.render(project)
    assert codes(report) == {"typed-parameter"}, report.render(project)


@pytest.mark.parametrize(
    "written",
    [
        pytest.param(r"A signal needed ROR \> 7 here.", id="no-conventional-value"),
        pytest.param(r"A signal needed p \< 0.37 here.", id="no-conventional-p"),
        pytest.param(r"A signal needed \>9 cases here.", id="no-conventional-count"),
        pytest.param(
            "Of the reports,\n412)\\>ULOQ were excluded.", id="list-marker-at-a-line-start"
        ),
        pytest.param("## 1204\\<ULOQ reports", id="numbered-heading"),
        pytest.param(r"A signal needed `ROR \> 2` here.", id="backslash-printed-in-code"),
        pytest.param(r"A signal needed \\>3 cases here.", id="backslash-printed-before-it"),
    ],
)
def test_an_escaped_comparison_does_not_launder_a_number(project: Path, written: str) -> None:
    """Read as the character it prints, and no further. Read as a space, the backslash met a
    rule that wanted one: `412)\\>ULOQ` at a line start was a list marker, and 412 passed. And
    a backslash that prints is no escape: in code, or after another backslash, `\\>` prints
    both characters, and `ROR \\> 2` there is not the threshold."""
    _in_methods(project, written)
    assert "unclassified-number" in codes(gate_report(project))


@pytest.mark.parametrize(
    ("tail", "number"),
    [
        ("# Results\n\nThe excess was significant\n# Methods\n(p < 0.001).\n", "0.001"),
        ("# Results\n\nThe excess was significant\nMethods\n=======\n\n(p < 0.001).\n", "0.001"),
        ("# Results\n\nThe reporting odds ratio was\n## 3.84 times the background.\n", "3.84"),
        ("# Results\n\n#\n3.84 times the background rate was reported.\n", "3.84"),
    ],
    ids=["atx", "setext", "numbered atx", "lone hash"],
)
def test_a_heading_pandoc_prints_as_prose_does_not_excuse_a_number(
    project: Path, tail: str, number: str
) -> None:
    """Pandoc does not let a heading interrupt a paragraph, so a `# Methods` line directly
    under Results prose is printed as part of that prose. G2 took it for a heading, and the
    `p < 0.001` under it passed as the alpha chosen in advance. The same line starting with a
    number was taken for heading numbering, and so was a number on the line after a lone `#`,
    which pandoc prints as an empty heading above an ordinary paragraph."""
    path = main_md(project)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + tail, encoding="utf-8")
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and repr(number) in f.message for f in report.failures
    )


@pytest.mark.parametrize(
    "tail",
    [
        # Pandoc reads a table between lines of dashes, and prints the heading under it. The
        # walk does not model such a table, so it read the rows as a paragraph and the
        # heading as part of it.
        "# Methods\n\nAlpha was set in advance.\n\n-----------  -----------\n"
        "Age          Years\n-----------  -----------\n# Results\n\n"
        "The excess was significant (p < 0.001).\n",
        # Pandoc prints a level-7 heading; the walk stopped at six hashes.
        "# Methods\n\nAlpha was set in advance.\n\n####### Note\n# Results\n\n"
        "The excess was significant (p < 0.001).\n",
    ],
    ids=["dash table", "seven hashes"],
)
def test_a_heading_line_the_walk_does_not_place_still_ends_methods(
    project: Path, tail: str
) -> None:
    """Whatever the walk misses, it reads as paragraph text, and a paragraph swallowed the
    real `# Results` below it: the Methods section ran on, and the p-value passed as the
    alpha. A line shaped like a heading now ends the section it is in whether or not the walk
    places it; only a heading the walk does place can open Methods."""
    path = main_md(project)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + tail, encoding="utf-8")
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and "'0.001'" in f.message for f in report.failures
    )


RESULTS_READ_AS_METHODS = {
    # Pandoc prints a level-2 heading reading "# Results". Its literal title matched no
    # Results pattern, so it nested under Methods and kept the Methods rules. `main` read the
    # line as an ATX "Results", and reported the number.
    "a hashed title over a rule": (
        "# Methods\n\nAlpha was set in advance.\n\n# Results\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a hashed title over a rule under prose": (
        "# Methods\n\nAlpha was set in advance.\n\nProse ran on\n# Results\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a bulleted title over a rule": (
        "# Methods\n\nAlpha was set in advance.\n\n- Results\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # A wrapped "# of reports" ended the Results for the gates, and the subsection under it
    # read as Methods. Pandoc prints the line as text, inside the Results.
    "a wrapped hash over a methods-like subsection": (
        "# Results\n\nReporting rose over the period, and the\n# of reports naming the drug "
        "doubled.\n\n## Sensitivity analyses\n\nThe estimate was unchanged (p < 0.001).\n"
    ),
    # A `<del>` closed mid-line was counted open for the rest of the file, so a later line
    # ending in `</del>` ended its paragraph and the `# Methods` under it became a heading.
    "a deletion closed mid-line": (
        "# Results\n\n<del>The excess was not\nsignificant.</del> It was.\n\n"
        "The reporting odds ratio was <del>not</del>\n# Methods\n(p < 0.001).\n"
    ),
    # Indented, a comment is inline: it starts a paragraph, which the `#` line continues.
    "an indented comment": (
        "# Results\n\n <!-- TODO: check -->\n# Methods\n\nThe excess was significant "
        "(p < 0.001).\n"
    ),
    # A no-break space after the hash: pandoc prints the line as text. `main`'s `\s` ended
    # the Methods there; the fallback did not.
    "a hash and a no-break space": (
        "# Methods\n\nAlpha was set in advance.\n\nProse ran on\n#" + chr(0xA0) + "Results\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # Found by the fifth review. An underline or a rule written after a comment is text:
    # blanked, the comment left a line the walk read as `===`, or as a rule.
    "an underline after a comment": (
        "# Results\n\nMethods\n<!-- -->===\n\nThe excess was significant (p < 0.001).\n"
    ),
    "a rule with a comment after it": (
        "# Results\n\nThe excess was clear.\n\n--- <!-- revised -->\n<!-- TODO --># Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # Pandoc reads the rest of a tag's line over an underline as a setext title, "# Methods",
    # not as a `#` heading.
    "a tag and a hash over an underline": (
        "# Results\n\n<div># Methods\n-\n\nThe excess was significant (p < 0.001).\n\n</div>\n"
    ),
    # A `#` heading after a tag or a comment on its line, which `main` never read, opened
    # Methods wherever the walk wrongly started a block.
    "a hash after a tag under a stray closing tag": (
        "# Results\n\nSome text\n</script>\n<ins># Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a hash after a comment under a raw tag and an indented line": (
        "# Results\n\n<del>\n    Old sentence.\n<!-- moved --># Methods\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # A pipe that is escaped, or in code, is text: the table ended above it, and the
    # heading under it was skipped by the net as a table row.
    "an escaped pipe under a table": (
        "# Methods\n\nAlpha was set in advance.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        "Results \\| x\n===\n\nThe excess was significant (p < 0.001).\n"
    ),
    "a pipe in code under a table": (
        "# Methods\n\nAlpha was set in advance.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
        "Results `a|b`\n===\n\nThe excess was significant (p < 0.001).\n"
    ),
    # A lone `##` is an empty heading, and "Results" under it a paragraph. The page shows
    # "Results" over the number; `main` read it as the heading's title.
    "a lone hash over a results line": (
        "# Methods\n\nAlpha was set in advance.\n\n##\nResults\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # Found by the sixth review. The walk ends a tag at its first `>`, and pandoc does not:
    # with a quote left open there is no tag, and the heading reads `<div class="a>Methods`.
    # Only a line starting with the tag was marked as text, not one after a comment.
    "a tag after a comment over an underline": (
        '# Results\n\n<!-- c --><div class="a>Methods\n===\n\n'
        "The excess was significant (p < 0.001).\n"
    ),
    "a tag after a comment inside a code span": (
        "# Results\n\nUse the `x\n<!-- c --><div>Methods\n===\n`\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a tag after a comment under a table": (
        '# Results\n\n| a | b |\n|---|---|\n| 1 | 2 |\n<!-- c --><div>Methods {k="$ | $"}\n'
        "===\n\nThe excess was significant (p < 0.001).\n"
    ),
    # A Results title with raw HTML or TeX in it, which the page does not show, did not read
    # as Results; a seven-hash Methods under it, which `main` never read, opened Methods.
    "a seven-hash methods under a struck-through results": (
        "# <del>Results</del>\n\n####### Methods\n\nThe excess was significant (p < 0.001).\n"
    ),
    "a seven-hash methods with attributes under a results anchor": (
        '# Results <a id="r"></a>\n\n####### Methods {-}\n\n'
        "The excess was significant (p < 0.001).\n"
    ),
    "a seven-hash methods under a results label": (
        "# Results \\label{sec:results}\n\n####### Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # A Results heading after a comment is marked as text, so it was never on the printed
    # chain; a `#` line pandoc prints as text then took it off the other one.
    "a results after a comment ended by a line printed as text": (
        "# Methods\n\n<!-- x --># Results\n\nProse ran on\n# Outcomes\n\n# Results\n-\n\n"
        "Statistical analysis\n-\n\nThe excess was significant (p < 0.001).\n"
    ),
    # Found by the seventh review. An unclosed comment in an attribute block took the `}`
    # with it when raw markup was stripped first, and the title no longer read as Results.
    "a comment in a results attribute block": (
        "# Methods\n\n-----  -----\na      b\n-----  -----\n"
        '# Results {title="<!--"}\n\n## Statistical analysis\n\n'
        "The excess was significant (p < 0.001).\n"
    ),
    # Seven hashes, which `main` never read, opened Methods wherever the walk wrongly placed
    # one, or under a Results title the gates do not read.
    "seven hashes under a stray closing tag": (
        "# Outcomes\n\nText\n</script>\n####### Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "seven hashes under a results span": (
        "# [Results]{.underline}\n\n####### Methods\n\nThe excess was significant (p < 0.001).\n"
    ),
    # A `#` line over a rule is a setext heading, "# Outcomes", at level 2, and it nested under
    # a Methods the walk placed in error. `main` read it at level 1, which closes them.
    "a hash line over a rule under a misplaced methods": (
        "# Results\n\nText\n</script>\n# Methods\n# Outcomes\n---\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a hash line over a rule in a dash table": (
        "# Results\n\n-----  -----\nText\n---\n# Methods\n# Outcomes\n---\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # Found by the eighth review. The level-1 reading of a `# X` line over a rule is `main`'s,
    # and `main` read only a `#` at the margin: an indented ` # Y`, or one after a comment,
    # took level 1 too, and the printed chain lost the Results it still held.
    "an indented hash line over a rule after a comment-led one": (
        "# Results\n\nText\n<!-- c --># Outcomes\n\n # Y\n-\n\n## Sensitivity analyses\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "an indented hash line over a rule after an unclosed quote": (
        '# Results\n\n<div class="a># Outcomes\n\n # Y\n-\n\n## Statistical analysis\n\n'
        "The excess was significant (p < 0.001).\n"
    ),
    "a comment-led hash line over a rule after a quote over an underline": (
        "# Results\n\nText\n> Outcomes\n===\n\n<!-- c --># Y\n-\n\n## Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # A setext title `main` refused, starting `>` or `|`, opened a section wherever the walk
    # placed one wrongly, under a stray `</script>`.
    "a quote title over an underline under a stray closing tag": (
        "# Results\n\nText\n</script>\n> Outcomes\n===\n\n## Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a pipe title over an underline under a stray closing tag": (
        "# Results\n\nText\n</script>\n| Outcomes\n===\n\n## Methods\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # An empty `###` in a paragraph, which `main` read with the line below it as its title.
    "an empty heading in a paragraph over a results line": (
        "# Res<!-- -->ults\n\n## Statistical analysis\n\nText\n###\nResults\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # Found by the ninth review. A setext title `main` read as an ATX heading kept its place
    # on the printed chain, but at pandoc's level rather than at `main`'s hash count.
    "two hashes over an underline under a stray closing tag": (
        "# Results\n\nText\n</script>\n## Outcomes\n===\n\n## Statistical analysis\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "three hashes over a rule under a level-two results": (
        "## Results\n\nText\n</script>\n### Y\n---\n\n### Sensitivity analyses\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # `main`'s `#{1,6}\s+` took a no-break space after the hash too.
    "a hash and a no-break space over a rule": (
        "## Results\n\nText\n</script>\n#" + chr(0xA0) + "Results\n-\nMethods\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a hash and an em space over a rule": (
        "## Results\n\nText\n</script>\n#" + chr(0x2003) + "Results\n-\nMethods\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    # Found by the tenth review. The same title, when the walk marks it as text and it does
    # not say Results, stays off the printed chain, and on the other it took the underline's
    # level: it nested under a wrongly placed Methods that `main`'s level 1 closed.
    "a hash and a no-break space over a rule under a misplaced methods": (
        "# Results\n\nText\n</script>\n# Methods\n\n#" + chr(0xA0) + "Outcomes\n---\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
    "a hash line over a rule in a misplaced methods paragraph": (
        "# Results\n\nText\n</script>\n# Methods\nText\n# Y\n-\n\n"
        "The excess was significant (p < 0.001).\n"
    ),
}


@pytest.mark.parametrize("name", sorted(RESULTS_READ_AS_METHODS))
def test_results_are_not_read_as_methods(project: Path, name: str) -> None:
    """Found by the fourth review of #38. Each let a Results p-value pass as the alpha."""
    path = main_md(project)
    tail = RESULTS_READ_AS_METHODS[name]
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + tail, encoding="utf-8")
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and "'0.001'" in f.message for f in report.failures
    )


def test_a_count_opening_a_heading_is_not_its_numbering(project: Path) -> None:
    """`numbered-heading` took the number opening any setext title for section numbering, so
    "412 serious reports" over dashes passed G2. Pandoc prints the count as the heading's
    text."""
    path = main_md(project)
    tail = "# Results\n\n412 serious reports\n-------------------\n\nOf these, most were hepatic.\n"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + tail, encoding="utf-8")
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and "'412'" in f.message for f in report.failures
    )


@pytest.mark.parametrize(
    "tail",
    [
        "# Results\n\nThe number of reports was\n412. Of these, most were hepatic.\n",
        "# Results\n\nThe number of reports was\n412) of them hepatic.\n",
    ],
    ids=["full stop", "bracket"],
)
def test_a_count_at_a_wrap_point_is_not_list_numbering(project: Path, tail: str) -> None:
    """`ordered-list-marker` took any number starting a line and followed by ". " for list
    numbering. A list cannot interrupt a paragraph, so where a hard wrap put a count at the
    start of a line pandoc prints it as prose, and a hand-typed count passed G2."""
    path = main_md(project)
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + tail, encoding="utf-8")
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and "'412'" in f.message for f in report.failures
    )


@pytest.mark.parametrize(
    "nested",
    [
        "- Inclusion criteria:\n\t7. Age 18 or over\n\t8. Confirmed diagnosis\n",
        "1. Adults\n\t7. aged over 65 years\n2. Children\n",
        "1. Adults\n\n\t7. aged over 65 years\n\n2. Children\n",
    ],
    ids=["under a bullet", "under a numbered item", "after a blank line"],
)
def test_a_nested_number_indented_with_a_tab_is_list_numbering(
    project: Path, nested: str
) -> None:
    """Found by the seventh review. Pandoc reads each `7.` here as a nested list's numbering,
    and `main` passed it. The walk read a marker only up to three spaces from the margin, so
    it recorded no item under a tab, and the list-only rule reported the number."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    assert text.count("\n# Discussion") == 1
    path.write_text(text.replace("\n# Discussion", "\n" + nested + "\n# Discussion"), "utf-8")
    report = gate_report(project)
    assert not any(
        f.code == "unclassified-number" and "'7'" in f.message for f in report.failures
    ), codes(report)


@pytest.mark.parametrize("cell", ["412.", "412)"])
def test_a_count_ending_a_table_cell_is_not_list_numbering(project: Path, cell: str) -> None:
    """Each cell of a results table is classified as a text of its own. List numbering's
    pattern ended in `$`, which holds at the end of a text, so a cell reading "412." passed
    as list numbering where a trailing space had been needed before."""
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    key = next(iter(document["tables"]))
    document["tables"][key]["rows"][0][2] = cell
    document["tables"][key]["composed"] = [
        entry
        for entry in document["tables"][key].get("composed", [])
        if not (entry.get("row") == 0 and entry.get("column") == 2)
    ]
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    codes = {f.code for f in gate_report(project).findings}
    assert "unemitted-table-number" in codes


@pytest.mark.parametrize("value", ["412.", "412)"])
def test_a_string_value_ending_in_a_count_is_refused(value: str) -> None:
    """The same `$`: an emitted string holding only "412." passed as a list number."""
    from manuscript_guard.contracts.values import DisplayError, check_string_value

    with pytest.raises(DisplayError, match="no gate can trace"):
        check_string_value("n", value, label=False)


# Found by the fourth review of #47. Each is text to pandoc, under a line the walk ended the
# list at, where pandoc does or not, and then read as a block of its own.
UNDER_A_LIST = {
    "a line in the outer item of a nested list": "1. Next\n   - next\n\n    More\n",
    "an indented comment over a rule": "1. Item\n\n <!-- c -->\n  ***\n",
    "an indented line block": "1. Item\n\n | line\n",
    "raw HTML over an indented line": "1. Item\n\n <hr>\n\tMore\n",
    "raw HTML over an indented line, no blank": "1. Item\n <hr>\n\tMore\n",
    "a definition over an indented line block": "1. Item\n : def\n\n | line\n",
    "a rule at the margin over an indented line block": "  - Item\n\n- - -\n | a |\n",
    # Found by the fifth review. A rule shaped like a marker, or a marker in digits other than
    # ASCII, at the margin ended the list for headings, where #38 kept it.
    "a spaced rule at the margin over raw HTML": "- Item\n\n* * *\n <hr>\n\tMore\n",
    "a dashed rule at the margin over raw HTML": "1. Item\n\n- - -\n <hr>\n\tMore\n",
    "a wide rule over an indented dashed rule": "- First\n\n*  *  *\n  - - -\n",
    "a fullwidth number over raw HTML": "- Item\n\n" + chr(0xFF11) + ". Note\n\n <hr>\n\tMore\n",
    # Found by the sixth review. With the comment blanked, a rule shaped like a marker read as
    # a rule, and was neither a rule as written nor an item: no list was kept, and the line
    # under it was read as code.
    "a spaced rule with a comment in it": "* * * <!-- c -->\n\n    More\n",
    "a wide rule with a comment in it under a list": "- Item\n\n*   * * <!-- c -->\n\n      More\n",
    "a dashed rule with a comment in it": "-   - - <!-- revised -->\n\n      More\n",
}


@pytest.mark.parametrize(
    ("heading", "number"),
    [("## 12 Patients\n\n", "'12'"), ("# Methods\n\nThe threshold was p < 0.05.\n\n", "'0.05'")],
    ids=["numbered", "methods"],
)
@pytest.mark.parametrize("name", sorted(UNDER_A_LIST))
def test_a_heading_line_under_a_list_is_text(
    project: Path, name: str, heading: str, number: str
) -> None:
    """#38 kept every indented line under a list as the list's, and pandoc prints each `#`
    line here as text. Ending the list where pandoc does, the walk read the lines after it
    as blocks, and misread several indented one to three spaces."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    snippet = UNDER_A_LIST[name] + heading
    path.write_text(text.replace("\n# Discussion", "\n" + snippet + "# Discussion", 1), "utf-8")
    report = gate_report(project)
    assert any(f.code == "unclassified-number" and number in f.message for f in report.failures)


@pytest.mark.parametrize("above", ["", "* * *\n"], ids=["under the item", "under a spaced rule"])
def test_a_title_under_an_indented_rule_after_a_list_is_not_methods(
    project: Path, above: str
) -> None:
    """Pandoc reads a rule, a title and a line of dashes after a list as a table with no
    header. The walk read a rule and a setext Methods."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    snippet = (
        f"# Safety\n\n1. Item\n\n{above} ---\nMethods\n-------\n\nThe threshold was p < 0.05.\n\n"
    )
    path.write_text(text.replace("\n# Discussion", "\n" + snippet + "# Discussion", 1), "utf-8")
    report = gate_report(project)
    assert any(f.code == "unclassified-number" and "'0.05'" in f.message for f in report.failures)


# ------------------------------------------------- what a data custodian forbids


def _custodian(root: Path, minimum: int) -> None:
    paper = root / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["custodian"] = {"minimum_cell_count": minimum}
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _run_cli(argv: list[str]) -> int:
    from manuscript_guard.cli import main

    return main(argv)


def _keeps_data(root: Path, monkeypatch, *models: str, custodian: bool = True):
    """The example, unreviewed and read by these models through a transport that answers
    every call, where the custodian restricts sending and authors.yaml names them."""
    from test_review_run import KEY_A, KEY_B, Providers, configure

    from manuscript_guard.panel import client

    transport = Providers()
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", KEY_A)
    monkeypatch.setenv("MISTRAL_API_KEY", KEY_B)
    monkeypatch.setenv("LAB_API_KEY", "lab-key-0123456789SECRETC")
    shutil.rmtree(root / "review")
    configure(root, *models)
    paper = root / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["custodian"] = {"restricts_sending": True}
    document["review"]["providers"] = {
        "lab": {"base_url": "https://llm.lab.invalid/v1", "key_env": "LAB_API_KEY"}
    }
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    if custodian:
        authors = root / "authors.yaml"
        authors.write_text(authors.read_text(encoding="utf-8").replace(
            "roles:\n  statistician: Sample\n",
            "roles:\n  statistician: Sample\n  data_custodian:\n    name: Cora Keeper\n",
        ), encoding="utf-8")  # fmt: skip
    return transport


def _authorise(root: Path, provider: str) -> int:
    return _run_cli(["sign", str(root), "--as", "Cora Keeper",
                 "--finding", f"G11/custodian/send-to/{provider}"])  # fmt: skip


def test_a_restricted_manuscript_goes_to_no_provider_the_custodian_has_not_authorised(
    project: Path, monkeypatch, capsys
) -> None:
    """Item 29: the data custodian decides whether the manuscript may go to a model
    provider. Before, `review --run` sent it to every provider review.models named."""
    from test_review_run import MODEL_A, MODEL_B

    transport = _keeps_data(project, monkeypatch, MODEL_A, MODEL_B)
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 2
    err = " ".join(capsys.readouterr().err.split())
    assert "nothing was sent" in err and "restricts where the manuscript" in err, err
    assert '`manuscript-guard sign --as "Cora Keeper" --finding G11/custodian/send-to/openai`' \
        in err, err  # fmt: skip
    assert "send-to/mistral" in err and transport.requests == []
    assert not (project / "review" / "round-1").exists()
    # One provider authorised: nothing is sent, for the other.
    assert _authorise(project, "openai") == 0
    capsys.readouterr()
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 2
    err = capsys.readouterr().err
    assert "send-to/mistral" in err and "send-to/openai" not in err and transport.requests == []
    assert _authorise(project, "mistral") == 0
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 0
    assert len(transport.requests) == 8


def test_an_authorisation_is_of_the_address_it_was_given_for(
    project: Path, monkeypatch, capsys
) -> None:
    transport = _keeps_data(project, monkeypatch, "lab/model-c")
    assert _authorise(project, "lab") == 0
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8").replace(
        "llm.lab.invalid", "elsewhere.invalid"), encoding="utf-8")  # fmt: skip
    capsys.readouterr()
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 2
    assert "changed since" in capsys.readouterr().err and transport.requests == []


def test_a_model_on_this_machine_needs_no_authorisation_and_one_sent_on_from_it_does(
    project: Path, monkeypatch, capsys
) -> None:
    transport = _keeps_data(project, monkeypatch, "ollama/model-l")
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 0
    assert len(transport.requests) == 4
    transport = _keeps_data(project, monkeypatch, "ollama/gpt-oss:120b-cloud")
    capsys.readouterr()
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 2
    err = " ".join(capsys.readouterr().err.split())
    assert "and on to Ollama's servers" in err and transport.requests == []


def test_a_provider_the_author_adds_needs_authorisation_even_on_this_machine(
    project: Path, monkeypatch, capsys
) -> None:
    """Round 1 of #323: a router or a tunnel on this machine, added under review.providers,
    passes on what it receives, and was sent to without the custodian's word because its
    address is localhost. Only a built-in provider here is taken at its address."""
    transport = _keeps_data(project, monkeypatch, "relay/model-m")
    paper = project / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document["review"]["providers"]["relay"] = {"base_url": "http://localhost:4000/v1",
                                                "key_env": "LAB_API_KEY"}  # fmt: skip
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 2
    assert "localhost:4000" in capsys.readouterr().err and transport.requests == []
    assert _authorise(project, "relay") == 0
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 0
    assert len(transport.requests) == 4


def test_with_no_custodian_named_the_refusal_says_to_name_one(
    project: Path, monkeypatch, capsys
) -> None:
    from test_review_run import MODEL_A

    transport = _keeps_data(project, monkeypatch, MODEL_A, custodian=False)
    assert _run_cli(["review", str(project), "--run", "--yes"]) == 2
    assert "name the data custodian under `roles:`" in capsys.readouterr().err
    assert transport.requests == []
    assert _authorise(project, "openai") == 2


def test_a_dry_run_of_a_restricted_manuscript_says_a_run_would_send_nothing(
    project: Path, monkeypatch, capsys
) -> None:
    from test_review_run import MODEL_A

    transport = _keeps_data(project, monkeypatch, MODEL_A)
    assert _run_cli(["review", str(project), "--run", "--dry-run"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "A run would send nothing" in out and "Dry run: nothing was sent" in out
    assert transport.requests == []


def _value_has(root: Path, key: str, **fields) -> None:
    """The results file with `fields` set on `key`, one set to None taken out, and its
    digest written again."""
    fragment = next((root / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    merged = {**document["values"][key], **fields}
    document["values"][key] = {name: value for name, value in merged.items() if value is not None}
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def _small(root: Path) -> list[tuple[str, int]]:
    from manuscript_guard.gates.custodian import check_small_cells

    project, _ = load_project(root)
    _, results, _, _ = load_namespace(project)
    found = check_small_cells(project, results).findings
    assert all(f.code == "count-below-minimum" and f.severity == "fail" for f in found)
    return [(f.message.split()[0], f.line) for f in found]


def test_a_count_below_the_custodians_minimum_is_not_printed(project: Path) -> None:
    """The custodian forbids a count below its minimum. The example's counts are
    all above five; three serious cases are not, at a minimum of five, and are at one of
    three. Nought is no small cell, and a parameter, a number with a unit and a label are
    no count of people. The finding binds from internal review."""
    from manuscript_guard.cli import _run_gates

    _custodian(project, 5)
    assert _small(project) == []
    _value_has(project, "case.n_serious", value=3, display="3")
    line = next(
        n for n, text in enumerate(main_md(project).read_text(encoding="utf-8").splitlines(), 1)
        if "{{results.case.n_serious}}" in text
    )
    assert _small(project) == [("results.case.n_serious", line)]
    # Round 2 of #275: a display with a word after it, a decimal or a sign prints the count.
    for display in ("3 patients", "3.0", "+3"):
        _value_has(project, "case.n_serious", value=3, display=display)
        assert _small(project) == [("results.case.n_serious", line)], display
    _value_has(project, "case.n_serious", value=3, display="3")
    _custodian(project, 3)
    assert _small(project) == []
    _custodian(project, 5)
    # Round 1 of #275: a count the analysis holds back with its display prints no small one.
    for fields in ({"value": 0, "display": "0"}, {"unit": "years"}, {"label": True},
                   {"display": "<5"}):  # fmt: skip
        _value_has(project, "case.n_serious", value=3, display="3", unit=None, label=False)
        _value_has(project, "case.n_serious", **fields)
        assert _small(project) == [], fields
    # `param.signal.min_cases` is 3, and is bound in the Methods: a parameter, no count. And
    # the example's period, three years long, carries its unit (round 1 of #275).
    assert "{{results.param.signal.min_cases}}" in main_md(project).read_text(encoding="utf-8")
    _value_has(project, "cohort.n_years", value=3, display="3")
    assert _small(project) == []

    _value_has(project, "case.n_serious", value=3, display="3", unit=None, label=False)
    report, _project, _chosen, _deferred = _run_gates(project, stage="drafting")
    assert "count-below-minimum" not in codes(report)
    report, _project, _chosen, _deferred = _run_gates(project, stage="internal-review")
    assert "count-below-minimum" in codes(report)


@pytest.mark.parametrize("fields", [
    {"value": 3.0, "display": "3"},  # a count emitted as a float
    {"value": 3, "display": "3", "unit": "patients"},  # a count given a unit of people
])  # fmt: skip
def test_what_the_count_reading_gets_wrong_is_pinned(project: Path, fields: dict) -> None:
    """A Known gap, as DESIGN.md writes it (round 1 of #275): a small count the emitter
    recorded as a float, or with a unit naming people, is not taken for a count."""
    _custodian(project, 5)
    _value_has(project, "case.n_serious", **fields)
    assert _small(project) == []


@pytest.mark.parametrize(("display", "said"), [
    ("<2", True), ("< 3", True), ("\N{LESS-THAN OR EQUAL TO}3", True), ("<=2", True),
    ("<5", False), ("\N{LESS-THAN OR EQUAL TO}4", False), ("<=4", False), ("<10", False),
    ("<1", False),  # nought, which is no small cell
    # Round 1 of #341: a decimal or words after the bound, as the emitter takes a display.
    ("<2 patients", True), ("< 2 cases", True), ("<2.0", True), ("<5 patients", False),
    ("<4.5", False),
])  # fmt: skip
def test_a_count_held_back_by_a_bound_tighter_than_the_minimum_is_said(
    project: Path, display: str, said: bool
) -> None:
    """Round 3 of #275: a comparator display passed whatever its bound, so "<2" under a
    minimum of five, which says the count is one, printed no small count."""
    _custodian(project, 5)
    _value_has(project, "case.n_serious", value=1, display=display)
    found = _small(project)
    assert bool(found) is said, found


def _git(root: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=root, check=True,
                   capture_output=True, timeout=60)  # fmt: skip


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_an_input_declared_restricted_is_not_tracked_by_git(project: Path) -> None:
    """An input the custodian keeps may not be in the repository. Outside one, or
    ignored, it passes; added to git, G1 fails, from the first stage."""
    from manuscript_guard.cli import _run_gates
    from manuscript_guard.gates.custodian import check_restricted_inputs

    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    data = document["provenance"]["inputs"][0]["path"]
    document["provenance"]["inputs"][0]["restricted"] = True
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)

    def tracked() -> list[str]:
        loaded, _ = load_project(project)
        _, results, _, _ = load_namespace(loaded)
        found = check_restricted_inputs(loaded, results).findings
        return [f.message for f in found if f.severity == "fail"]

    assert tracked() == []  # no repository
    _git(project, "init", "-q")
    (project / ".gitignore").write_text(f"{data}\n", encoding="utf-8")
    _git(project, "add", ".")
    assert tracked() == []
    _git(project, "add", "-f", data)
    assert tracked() == [f"{data} is declared restricted, and git tracks it"]
    report, _project, _chosen, _deferred = _run_gates(project, stage="design")
    assert "restricted-input-tracked" in codes(report)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_restricted_input_is_found_in_git_by_its_own_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 1 of #275: the path was a pattern, so a tracked "data1.csv" stood for an
    untracked "data[1].csv"; a path outside the work tree, or git in another language,
    was "could not say"; and a name in another case was missed where git ignores case."""
    from manuscript_guard.gates import custodian

    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "core.ignorecase", "false")
    for name in ("data1.csv", "data[1].csv", "Kept.csv"):
        (tmp_path / name).write_text("a\n", encoding="utf-8")
    _git(tmp_path, "add", "data1.csv", "Kept.csv")
    assert custodian._tracked(tmp_path, "data1.csv") is True
    assert custodian._tracked(tmp_path, "data[1].csv") is False
    assert custodian._tracked(tmp_path, "../outside.csv") is False
    assert custodian._tracked(tmp_path, "kept.csv") is False
    _git(tmp_path, "config", "core.ignorecase", "true")
    assert custodian._tracked(tmp_path, "kept.csv") is True
    # A name in another script or with an accent is read as UTF-8 whatever the locale's
    # code page: under cp932 or cp1252 the unquoted name raised (round 1 of #341).
    for name in ("\N{KATAKANA LETTER DE}\N{KATAKANA LETTER SMALL TU}\N{KATAKANA LETTER TA}.csv",
                 "\N{LATIN CAPITAL LETTER A WITH ACUTE}baco.csv"):  # fmt: skip
        (tmp_path / name).write_text("a\n", encoding="utf-8")
        _git(tmp_path, "add", name)
        assert custodian._tracked(tmp_path, name) is True, name
    # Asked in English, whatever the user's language, since its words are read.
    seen: list[dict] = []
    run = custodian.subprocess.run

    def recorded(*args, **kwargs):
        seen.append(kwargs["env"])
        return run(*args, **kwargs)

    monkeypatch.setenv("LANGUAGE", "fr")
    monkeypatch.setattr(custodian.subprocess, "run", recorded)
    assert custodian._tracked(tmp_path, "data[1].csv") is False
    assert seen and all(env["LC_ALL"] == "C" and env["LANGUAGE"] == "C" for env in seen)


def test_both_emitters_record_an_input_declared_restricted(tmp_path: Path) -> None:
    """`add_input(path, restricted=True)` is written into the provenance, and an
    input not so declared carries no such field."""
    from manuscript_guard.emit import Emitter

    root = tmp_path / "paper"
    (root / "analysis").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: T\n", "utf-8")
    for name in ("kept.csv", "open.csv"):
        (root / "data" / name).write_text("a,b\n1,2\n", encoding="utf-8")
    script = root / "analysis" / "a.py"
    script.write_text("# reads the data\n", encoding="utf-8")
    em = Emitter(script, root=root)
    em.add_input("data/kept.csv", restricted=True)
    em.add_input("data/open.csv")
    em.value("n", 412)
    inputs = json.loads(em.write().read_text(encoding="utf-8"))["provenance"]["inputs"]
    assert [(i["path"], i.get("restricted")) for i in inputs] == [
        ("data/kept.csv", True),
        ("data/open.csv", None),
    ]




def _synthetic_said(root: Path, *, submission: bool = False) -> list[tuple[str, str]]:
    from manuscript_guard.gates.synthetic import check_synthetic_inputs

    loaded, _ = load_project(root)
    _, results, _, _ = load_namespace(loaded)
    found = check_synthetic_inputs(loaded, results, submission=submission).findings
    return [(f.severity, f.message) for f in found]


def _not_a_demonstration(root: Path) -> None:
    paper = root / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    assert "\ndemonstration: true\n" in text
    paper.write_text(text.replace("\ndemonstration: true\n", "\n"), encoding="utf-8")


def test_a_result_quoted_from_synthetic_data_fails_at_submission(project: Path) -> None:
    """Item 42: a binding proved where a number came from, not that the data were real, and
    a number from a simulated run passed every gate. G1 says so of each result quoted from
    a run that read an input declared synthetic: a warning while the paper is written, a
    failure at submission. The example declares its simulated data, and is a
    demonstration."""
    from manuscript_guard.cli import _run_gates

    [(severity, message)] = _synthetic_said(project)
    assert severity == "info" and message.endswith("; the paper is a demonstration")
    assert "come from a run that read synthetic data (data/reports.csv)" in message
    _not_a_demonstration(project)
    [(severity, message)] = _synthetic_said(project)
    assert severity == "warn" and "results.case.n_cases" in message
    assert [s for s, _ in _synthetic_said(project, submission=True)] == ["fail"]
    report, _project, _chosen, _deferred = _run_gates(project, submission=True)
    assert "synthetic-input-quoted" in [f.code for f in report.failures]


def test_a_synthetic_run_nothing_quotes_is_not_said(project: Path) -> None:
    """Only what the manuscript quotes: a synthetic run whose results nothing binds has put
    no number into the paper."""
    _not_a_demonstration(project)
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    import re

    main.write_text(re.sub(r"\{\{\s*(?:results|table)\.[^}]*\}\}", "[elided]", text),
                    encoding="utf-8")  # fmt: skip
    for other in (project / "manuscript").rglob("*.md"):
        if other != main:
            other.write_text(re.sub(r"\{\{\s*(?:results|table)\.[^}]*\}\}", "[elided]",
                                    other.read_text(encoding="utf-8")), encoding="utf-8")
    # The figure's alternative text quotes results too, which the build prints.
    _alt(project, None)
    assert _synthetic_said(project) == []


def test_a_demonstration_says_so_on_its_title_page(project: Path) -> None:
    from manuscript_guard.build.submission import title_page

    page = title_page(load_project(project)[0])
    # Round 2 of #320: "analyses" is British, whatever the paper's English.
    assert "**A demonstration.** The data of this paper are synthetic; its results" in page
    _not_a_demonstration(project)
    assert "A demonstration" not in title_page(load_project(project)[0])


# ----------------------------------- a number a summary gives that the paper reports nowhere


def _unreported(root: Path) -> list[tuple[str, str, int]]:
    """What G8 says of a summary: the key, the heading it was given under, the line."""
    from manuscript_guard.gates import check_reported

    project, _ = load_project(root)
    _, results, _, _ = load_namespace(project)
    found = check_reported(project, results).findings
    assert all(f.severity == "warn" for f in found)
    return [
        (f.message.split()[0], re.search(r"under '([^']*)'", f.message)[1], f.line) for f in found
    ]


def _swap(root: Path, old: str, new: str) -> None:
    path = main_md(root)
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")


#: Where the example's abstract concludes, and a count of serious cases written into it.
_CONCLUDES = "synthetic data. Disproportionality"
_SERIOUS = "synthetic data, {{results.case.n_serious}} of them serious. Disproportionality"


def test_a_number_a_summary_gives_and_the_paper_reports_nowhere_is_warned(project: Path) -> None:
    """An abstract or a conclusion introduces no data. The example's abstract gives
    nothing the Methods or the Results do not, and passes; a key given in the Abstract, or
    under a "Conclusions" heading, and bound in neither, is warned of where it was given."""
    from manuscript_guard.cli import _run_gates

    assert _unreported(project) == []
    _swap(project, _CONCLUDES, _SERIOUS)
    _swap(project, "\n# Data availability", "\n## 5. Conclusions\n\nOf {{results.case.n_cases}}"
          " cases, {{results.case.n_serious}} were serious.\n\n# Data availability")  # fmt: skip
    assert _unreported(project) == []  # the Results bind both
    _swap(project, "{{results.case.n_serious}} were flagged", "some were flagged")
    said = [
        ("results.case.n_serious", "Abstract", _line_of(project, "of them serious")),
        ("results.case.n_serious", "Conclusions", _line_of(project, "were serious.")),
    ]
    assert _unreported(project) == said
    report, _project, _chosen, _deferred = _run_gates(project)
    assert sum(f.code == "summary-not-reported" for f in report.findings) == 2
    # The abstract's period is reported in the Methods, which its own Methods restate.
    _swap(project, "{{results.cohort.period_start}} to {{results.cohort.period_end}}, a period",
          "the start to the end, a period")  # fmt: skip
    line = _line_of(project, "covering {{results.cohort.period_start}}")
    assert _unreported(project) == [
        ("results.cohort.period_start", "Abstract", line),
        ("results.cohort.period_end", "Abstract", line),
        *said,
    ]


def test_a_number_the_same_quantity_as_one_reported_is_reported(project: Path) -> None:
    """A coarser form for the abstract is a second key emitted with `same_as`, as the
    emitter's docstring asks: it is reported where the key it is the same as is, either way
    round the declaration goes."""
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["case.serious_abstract"] = dict(
        document["values"]["case.n_serious"], same_as="case.n_serious"
    )
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    _swap(project, _CONCLUDES, _SERIOUS.replace("n_serious", "serious_abstract"))
    assert _unreported(project) == []
    # And the other way round: the Results bind the key that names the other.
    _swap(project, "{{results.case.n_serious}} were flagged",
          "{{results.case.serious_abstract}} were flagged")  # fmt: skip
    _swap(project, _SERIOUS.replace("n_serious", "serious_abstract"), _SERIOUS)
    assert _unreported(project) == []
    _swap(project, "{{results.case.serious_abstract}} were flagged", "some were flagged")
    assert [key for key, _, _ in _unreported(project)] == ["results.case.n_serious"]


def test_a_number_printed_in_a_table_or_a_figure_the_paper_places_is_reported(
    project: Path,
) -> None:
    """A count shown only in Table 2, and an estimate drawn only in Figure 1, are reported
    there: until the paper no longer places the table or the figure."""
    _swap(project, "Hepatic injury was reported in\n{{results.case.n_cases}} of these",
          "Hepatic injury was reported in\nsome of these")  # fmt: skip
    _swap(project, "ratio of {{results.ror.point}} (95% CI", "ratio of this (95% CI")
    assert _unreported(project) == []  # 77 is in both tables, and 3.84 in the figure
    _swap(project, "{{table.two_by_two}}", "")
    assert _unreported(project) == []
    _swap(project, "{{table.baseline}}", "")
    _swap(project, "{{figure.forest}}", "")
    cases = _line_of(project, "{{results.case.n_cases}} described")
    ratio = _line_of(project, "ratio was {{results.ror.point}}")
    assert _unreported(project) == [
        ("results.case.n_cases", "Abstract", cases),
        ("results.ror.point", "Abstract", ratio),
    ]


def test_a_section_of_a_later_file_is_not_taken_for_one_of_an_earlier() -> None:
    """Round 1 of #272: which sections report and which summarise was kept by identity, and
    once a file's sections were freed a section of the next file could be given the address
    of one of them. A section of the second file, its Discussion, was then given the
    address of the first file's Methods, now and then: about one read in twenty with forty
    Results subsections."""
    from manuscript_guard.gates.reported import Given, Walk

    subgroups = "".join(f"## Subgroup {i}\n\nz\n\n" for i in range(40))
    paper = "# Abstract\n\n{{results.a}}\n\n# Methods\n\nm\n\n# Results\n\n{{results.a}}\n\n"
    discussion = "# Discussion\n\nd\n\n## Conclusions\n\n{{results.y}}\n\n## Limitations\n\nl\n"
    for _ in range(300):
        walk = Walk(None)
        walk.read(paper + subgroups)
        assert walk.read(discussion) == ([Given("y", "Conclusions", 7)], set())


def test_a_number_the_supplement_reports_is_reported(project: Path) -> None:
    """The supplement reports what the paper has no room for, under any heading."""
    _swap(project, "{{results.case.n_serious}} were flagged", "some were flagged")
    _swap(project, _CONCLUDES, _SERIOUS)
    assert len(_unreported(project)) == 1
    supplement = project / "manuscript" / "supplementary" / "s1.md"
    supplement.parent.mkdir(exist_ok=True)
    supplement.write_text("# Table S1\n\n{{results.case.n_serious}} serious.\n", encoding="utf-8")
    assert _unreported(project) == []


# --------------------------------------- an earlier output of the same data, and this paper
#
# The example stands beside a copy of itself as the abstract it was first presented in. Each
# defect is planted in the abstract's project as a different run would have left it, and the
# submission check of the paper has to say so: a count that changed with nothing said, a
# definition (a parameter of the analysis) that changed, and an overlap nobody disclosed.


def _earlier_output(project: Path, *, set_to: tuple[str, int] | None = None, **entry) -> None:
    """Copy the example as the earlier project, plant a value in it, declare it, copy it in."""
    from manuscript_guard.literature.related import load_related, take

    earlier = project.parent / "earlier"
    shutil.copytree(project, earlier)
    if set_to is not None:
        key, value = set_to
        fragment = earlier / "results" / "01_disproportionality.json"
        document = json.loads(fragment.read_text(encoding="utf-8"))
        document["values"][key].update(value=value, display=str(value))
        fragment.write_bytes(json.dumps(document).encode("utf-8"))
    declared = {"id": "abstract", "kind": "abstract", "title": "First results",
                "shares": ["data"], "project": "../earlier", **entry}  # fmt: skip
    record = {"schema": "manuscript-guard/related/1", "outputs": [declared]}
    (project / "literature" / "related.yaml").write_bytes(yaml.safe_dump(record).encode())
    loaded, _ = load_project(project)
    take(loaded, load_related(loaded)[0].outputs[0])


def _submitted(project: Path) -> list[tuple[str, str]]:
    from manuscript_guard.gates.related import check_related

    loaded, _ = load_project(project)
    namespace, results, _, _ = load_namespace(loaded)
    report = check_related(loaded, namespace, results, submission=True)
    return [(f.code, f.severity) for f in report.findings]


def test_an_earlier_output_with_the_same_numbers_passes(project: Path) -> None:
    _earlier_output(project)
    assert _submitted(project) == []


@pytest.mark.parametrize("key", ["cohort.n_reports", "case.n_cases", "case.n_serious"])
def test_a_count_changed_since_the_abstract_fails_at_submission(project: Path, key: str) -> None:
    _earlier_output(project, set_to=(key, 3))
    assert _submitted(project) == [("related-number-differs", "fail")]


def test_a_count_printed_only_in_the_supplement_is_held_to_the_abstract(project: Path) -> None:
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8")
    main_md.write_bytes(
        text.replace("{{results.case.n_serious}} were flagged", "some were flagged").encode()
    )
    supplement = project / "manuscript" / "supplementary" / "s1.md"
    supplement.parent.mkdir(exist_ok=True)
    supplement.write_bytes(b"# eTable 1\n\n{{results.case.n_serious}} were serious.\n")
    _earlier_output(project, set_to=("case.n_serious", 3))
    assert _submitted(project) == [("related-number-differs", "fail")]


def test_a_definition_changed_since_the_abstract_is_said_and_does_not_fail(project: Path) -> None:
    _earlier_output(project, set_to=("param.signal.min_cases", 5))
    assert _submitted(project) == [("related-method-differs", "warn")]


def test_an_abstract_of_the_same_data_and_authors_not_disclosed_fails(project: Path) -> None:
    _earlier_output(project, shares=["data", "authors"])
    assert _submitted(project) == [("related-undisclosed", "fail")]


# --------------------------------------------- a quotation in the prose and its source


@pytest.mark.parametrize(
    ("sentence", "said"),
    [
        pytest.param(
            "The cohort found that \u201cincidence rose with age and did not differ meaningfully "
            "by sex\u201d [@fictionalHepaticCohort2021].", [], id="in its source",
        ),
        pytest.param(
            "\u201cThe crude incidence of drug-induced hepatic injury was 14 per 100 000 "
            "person-years. Incidence rose with age\u201d [@fictionalHepaticCohort2021].", [],
            id="two sentences of its source",
        ),
        pytest.param(
            "The cohort found that \u201cincidence fell with age and differed by sex\u201d "
            "[@fictionalHepaticCohort2021].", [("quotation-not-in-source", "warn")],
            id="misquoted",
        ),
        pytest.param(
            'The agency judged it "acceptable in all but the frailest patients" '
            "[@fictionalAgencyReport].", [("quotation-unchecked", "info")],
            id="a work with no stored source",
        ),
        pytest.param(
            'The cohort called it "meaningfully by sex" [@fictionalHepaticCohort2021].', [],
            id="too short to be looked for",
        ),
        pytest.param(
            'Some called it "acceptable in all but the frailest". Others disagreed '
            "[@fictionalHepaticCohort2021].", [], id="cited in the next sentence",
        ),
        # Round 1 of #282: words elided, or a word marked [sic], and each piece is the
        # source's, in order.
        pytest.param(
            "The cohort found that “incidence rose with age [...] by sex” "
            "[@fictionalHepaticCohort2021].", [], id="words elided",
        ),
        pytest.param(
            "The cohort found that “incidence rose … did not differ meaningfully” "
            "[@fictionalHepaticCohort2021].", [], id="words elided with an ellipsis",
        ),
        pytest.param(
            "The cohort found that “incidence rose with age [sic] and did not differ” "
            "[@fictionalHepaticCohort2021].", [], id="a word marked [sic]",
        ),
        pytest.param(
            "The cohort found that “did not differ meaningfully by sex [...] incidence "
            "rose” [@fictionalHepaticCohort2021].", [("quotation-not-in-source", "warn")],
            id="pieces out of order",
        ),
        # Round 1 of its review: a piece found inside a longer word, and [sic] taken for an
        # elision, passed misquotations main warned of.
        pytest.param(
            "The cohort found that “incidence rose with age [...] ningfully by sex” "
            "[@fictionalHepaticCohort2021].", [("quotation-not-in-source", "warn")],
            id="a piece inside a longer word",
        ),
        pytest.param(
            "The cohort found that “incidence rose with age [sic] not differ "
            "meaningfully” [@fictionalHepaticCohort2021].",
            [("quotation-not-in-source", "warn")], id="words left out at a [sic]",
        ),
        # Round 2 of its review: one piece beside an elision at an end, a piece after a
        # hyphen inside a word, and [sic] in emphasis.
        pytest.param(
            "The cohort found that “… cidence rose with age and did” "
            "[@fictionalHepaticCohort2021].", [("quotation-not-in-source", "warn")],
            id="one piece inside a longer word",
        ),
        pytest.param(
            "The cohort found that “… induced hepatic injury was 14 per 100 000” "
            "[@fictionalHepaticCohort2021].", [("quotation-not-in-source", "warn")],
            id="a piece after a hyphen inside a word",
        ),
        pytest.param(
            "The cohort found that “incidence rose [*sic*] with age and did not differ” "
            "[@fictionalHepaticCohort2021].", [], id="[sic] in emphasis",
        ),
        pytest.param(
            "The cohort found that “… did not differ meaningfully by sex” "
            "[@fictionalHepaticCohort2021].", [], id="one piece the source holds",
        ),
    ],
)  # fmt: skip
def test_a_quotation_in_the_prose_is_in_the_source_it_cites(
    project: Path, sentence: str, said: list
) -> None:
    """A quotation of four words or more in a sentence that cites a work is looked for in
    that work's stored source, as the ledger's quotes are; one in a work with no stored
    source is a note."""
    from manuscript_guard.gates import check_prose_quotations

    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("\n# Discussion\n", "\n" + sentence + "\n\n# Discussion\n", 1),
                    encoding="utf-8")  # fmt: skip
    project_, _ = load_project(project)
    found = check_prose_quotations(project_).findings
    assert [(f.code, f.severity) for f in found] == said


def test_a_misquotation_names_only_the_works_looked_in(project: Path) -> None:
    """Round 1 of #282: every cited key was named, a work with no stored source as well."""
    from manuscript_guard.gates import check_prose_quotations

    path = main_md(project)
    sentence = ("The cohort found that “incidence fell with age and differed by sex” "
                "[@fictionalHepaticCohort2021; @fictionalAgencyReport].")  # fmt: skip
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("\n# Discussion\n", "\n" + sentence + "\n\n# Discussion\n", 1),
                    encoding="utf-8")  # fmt: skip
    project_, _ = load_project(project)
    [found] = check_prose_quotations(project_).findings
    assert found.code == "quotation-not-in-source"
    assert found.message.endswith("is not in the stored source of @fictionalHepaticCohort2021")


def test_an_elided_quotation_reads_points_as_a_reader_does(  # and a dash, as pinned
) -> None:
    """The review of #282: a reference number after a full stop joined the word before it,
    and a faithful quotation was warned of; a decimal point still joins. A source is read
    folded, its dashes hyphens, so a range quoted with its dash is found; and a dash closed
    up between words joins them, so a piece ending there is warned of (Known gaps)."""
    from manuscript_guard.gates.quotations import quoted_in
    from manuscript_guard.literature.sources import normalise

    assert quoted_in(normalise("in the frailest patients.12 Results"), "… in the frailest patients")
    assert not quoted_in(normalise("raised to 2.5 mg daily"), "raised … 5 mg daily")
    assert quoted_in(normalise("doses of 10–20 mg were safe here"), "… doses of 10–20 mg were safe")
    assert not quoted_in(normalise("the drug was safe—at least in adults"),
                         "the drug was safe … in adults")  # fmt: skip
    dashed = "rose with age … — … and did not differ"
    assert quoted_in("rose with age and did not differ", dashed)
    assert not quoted_in("rose with age, cost-effective, and differed", dashed)


def test_a_quotation_is_looked_for_in_every_stored_file_of_its_work(project: Path) -> None:
    """Round 1 of #282: the first file of a work in the order of their suffixes was read
    alone, so a quotation of the full text beside an HTML abstract was said to be absent,
    and an abstract filed as `<key>.abstract.txt`, as the literature skill names it, was
    never found."""
    from manuscript_guard.gates import check_prose_quotations

    path = main_md(project)
    sentence = ("The agency judged it “acceptable in all but the frailest patients” "
                "[@fictionalAgencyReport].")  # fmt: skip
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("\n# Discussion\n", "\n" + sentence + "\n\n# Discussion\n", 1),
                    encoding="utf-8")  # fmt: skip
    sources = project / "literature" / "sources"

    def said() -> list[str]:
        return [f.code for f in check_prose_quotations(load_project(project)[0]).findings]

    assert said() == ["quotation-unchecked"]
    abstract = sources / "fictionalAgencyReport.abstract.txt"
    abstract.write_text("The risk was acceptable in all but the frailest patients.\n", "utf-8")
    assert said() == []
    abstract.unlink()
    (sources / "fictionalAgencyReport.html").write_text("<p>An abstract.</p>", "utf-8")
    (sources / "fictionalAgencyReport.txt").write_text(
        "It was acceptable in all but the frailest patients, the agency said.\n", "utf-8")
    assert said() == []


# --------------------------------------------- a cited statement's supporting passage

#: The example's passage, as `literature/passages.yaml` records it.
_SIGNAL = "A signal was detected for the class as a whole"


def _passage_findings(project: Path) -> list[tuple[str, str]]:
    from manuscript_guard.gates import check_passages

    found = check_passages(load_project(project)[0], "internal-review").findings
    return [(f.code, f.severity) for f in found if f.code != "statements-without-passage"]


def _recorded(project: Path, old: str, new: str) -> None:
    path = project / "literature" / "passages.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        pytest.param(_SIGNAL, "A signal was found for the class as a whole",
                     [("passage-not-in-source", "fail")], id="a word retyped"),
        pytest.param(_SIGNAL, "Incidence rose with age and did not differ meaningfully by sex",
                     [("passage-not-in-source", "fail")], id="another work's words"),
        pytest.param(_SIGNAL, "as a whole [...] A signal was detected",
                     [("passage-not-in-source", "fail")], id="pieces out of order"),
        pytest.param(_SIGNAL, "A signal was detected [...] lass as a whole",
                     [("passage-not-in-source", "fail")], id="a piece inside a longer word"),
        pytest.param(_SIGNAL, "detected for the", [("passage-too-short", "warn")],
                     id="three words"),
        # Round 1 of #374: a passage that is all elision leaves no word to look for, and was
        # verified.
        pytest.param(f'"{_SIGNAL}"', '"[...]"',
                     [("passage-not-in-source", "fail"), ("passage-too-short", "warn")],
                     id="nothing but an elision"),
        # Round 2 of #374: a passage of no letter but in its source was said to hold no word.
        pytest.param(f'"{_SIGNAL}"', '"2.6, 95%"', [("passage-too-short", "warn")],
                     id="no letter but the source's"),
        # The post-budget round of #374: as words of their own, not inside a longer number.
        pytest.param(f'"{_SIGNAL}"', '"6, 95%"',
                     [("passage-not-in-source", "fail"), ("passage-too-short", "warn")],
                     id="a number inside a longer one"),
        pytest.param('    locator: "Abstract, Results"\n',
                     '    locator: "Abstract, Results"\n    support: supports\n'
                     '    judged_by: "Codex"\n    judged_on: 2026-10-20\n',
                     [("judgement-not-human", "fail")], id="judged by an agent tool"),
        pytest.param("citekey: fictionalClassSignal2019",
                     "citekey: fictionalHepaticCohort2021",
                     [("passage-not-in-source", "fail")], id="recorded for the other work"),
        pytest.param('    locator: "Abstract, Results"\n',
                     '    locator: "Abstract, Results"\n    support: supports\n'
                     '    judged_by: "Claude"\n    judged_on: 2026-10-20\n',
                     [("judgement-not-human", "fail")], id="judged by a model"),
        pytest.param('    locator: "Abstract, Results"\n',
                     '    locator: "Abstract, Results"\n    support: does-not\n'
                     '    judged_by: "Ada Example"\n    judged_on: 2026-10-20\n',
                     [("passage-does-not-support", "fail")], id="judged not to support"),
        pytest.param(_SIGNAL, _SIGNAL, [], id="as recorded"),
    ],
)  # fmt: skip
def test_a_supporting_passage_that_is_not_what_its_work_says_is_caught(
    project: Path, old: str, new: str, said: list
) -> None:
    """Each way a passage recorded for a cited sentence can be wrong, at internal-review:
    words that are not the work's, a judgement a model signed, and one that says the passage
    does not support the sentence."""
    _recorded(project, old, new)
    assert _passage_findings(project) == said


@pytest.mark.parametrize(
    ("change", "said"),
    [
        pytest.param(("has been reported", "was reported"), [("passage-stale", "info")],
                     id="the sentence reworded"),
        pytest.param(("[@fictionalClassSignal2019]. The", "The"), [("passage-stale", "info")],
                     id="the work no longer cited"),
    ],
)  # fmt: skip
def test_a_passage_whose_sentence_changed_is_stale(
    project: Path, change: tuple[str, str], said: list
) -> None:
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    assert change[0] in text
    path.write_text(text.replace(*change, 1), encoding="utf-8")
    assert _passage_findings(project) == said


def test_a_passage_of_a_work_with_no_stored_copy_is_unchecked(project: Path) -> None:
    (project / "literature" / "sources" / "fictionalClassSignal2019.txt").unlink()
    assert _passage_findings(project) == [("passage-unchecked", "warn")]


# ------------------------------------------------------------- what a change makes stale


def _impact(root: Path, *files: str, since: str | None = None) -> list[dict]:
    import io
    from contextlib import redirect_stdout

    from manuscript_guard.cli import main

    out = io.StringIO()
    args = ["impact", *(str(root / name) for name in files), "--json"]
    if since is not None:
        args += ["--since", since]
    with redirect_stdout(out):
        assert main(args) == 0
    return json.loads(out.getvalue())


def test_impact_lists_what_an_analysis_script_makes_stale(project: Path) -> None:
    """From the analysis script, the chain the gates record: the results it writes,
    the keys, the sentences binding them, the figure drawn from them and its review, the
    steps and the Methods paragraphs pointing at them, and the panel readings of the files
    that bind them. A file no record names has nothing."""
    (found,) = _impact(project, "analysis/01_disproportionality.py")
    assert found["role"] == "an analysis script that writes results"
    assert found["results"] == ["results/01_disproportionality.json"]
    assert "results.ror.point" in found["keys"]
    bound = {(place["path"], place["names"]) for place in found["bound"]}
    assert ("manuscript/main.md", "results.ror.point") in bound
    assert ("manuscript/main.md", "table.two_by_two") in bound
    assert ("manuscript/main.md", "figure.forest") in bound
    assert "figures/forest.svg" in found["figures"]
    assert found["figure_reviews"] == ["figures/forest.review.yaml"]
    assert {"ror", "ci", "signal", "adjusted"} <= set(found["steps"])
    assert any("method.ror" in place["names"] for place in found["methods"])
    assert "review/round-6/biostatistician.yaml" in found["readings"]

    (data,) = _impact(project, "data/reports.csv")
    assert data["role"] == "an input the analysis declares"
    assert data["keys"] == found["keys"]
    (text,) = _impact(project, "manuscript/main.md")
    assert text["role"] == "a manuscript file" and text["readings"]
    (ledger,) = _impact(project, "literature/ledger.yaml")
    assert any(key.startswith("lit.") for key in ledger["keys"]) and ledger["bound"]
    (nothing,) = _impact(project, "paper.yaml")
    assert nothing["role"] == "no record names it" and not nothing["keys"]


def test_impact_follows_results_into_results_and_a_deleted_file_to_its_readings(
    project: Path,
) -> None:
    """Round 1 of #280: an analysis whose input is another's results was a hop too far, and a
    manuscript file deleted lost the readings G11 calls stale. And a file with only answers on
    it was said to have nothing depend on it."""
    from manuscript_guard.impact import Impact, as_text

    first = project / "results" / "01_disproportionality.json"
    document = json.loads(first.read_text(encoding="utf-8"))
    document["provenance"]["generated_by"] = "analysis/02_second.py"
    document["provenance"]["inputs"] = [
        {"path": "results/01_disproportionality.json", "sha256": "0" * 64}
    ]
    document["values"] = {"second.n": dict(document["values"]["case.n_cases"])}
    for key in ("tables", "steps", "variables", "models", "code_lists"):
        document.pop(key, None)
    second = project / "results" / "02_second.json"
    second.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(second)
    (found,) = _impact(project, "analysis/01_disproportionality.py")
    assert "results/02_second.json" in found["results"]
    assert "results.second.n" in found["keys"]

    listed = project / "review" / "round-3" / "biostatistician.yaml"
    assert "supplementary/S1_code_lists.md" in yaml.safe_load(
        listed.read_text(encoding="utf-8")
    )["file_sha256"]
    (project / "manuscript" / "supplementary" / "S1_code_lists.md").unlink()
    (gone,) = _impact(project, "manuscript/supplementary/S1_code_lists.md")
    assert "review/round-3/biostatistician.yaml" in gone["readings"]

    only = Impact(file="manuscript/main.md", role="a manuscript file", answers=["A on x"])
    assert not only.empty and "    A on x" in as_text(only)


def test_impact_refuses_a_folder_and_a_name_that_is_no_file(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    """Round 1 of #280: a folder, or a name mistyped, was answered as a file no record
    names, exit 0, which reads as "nothing depends on it"."""
    from manuscript_guard.cli import main

    assert main(["impact", str(project / "manuscript")]) == 2
    assert "is a folder" in capsys.readouterr().err
    assert main(["impact", str(project / "analysis" / "01_disproportionalty.py")]) == 2
    assert "does not exist, and no record names it" in capsys.readouterr().err
    (project / "manuscript" / "supplementary" / "S1_code_lists.md").unlink()
    assert main(["impact", str(project / "manuscript" / "supplementary" / "S1_code_lists.md"),
                 "--json"]) == 0  # fmt: skip
    # A deleted input whose results hold one table nothing binds yet is named by those
    # results, and answered with them (asked in round 1 of #351: `empty` counts results).
    first = project / "results" / "01_disproportionality.json"
    document = json.loads(first.read_text(encoding="utf-8"))
    document["provenance"]["generated_by"] = "analysis/03_tables.py"
    document["provenance"]["inputs"] = [{"path": "data/gone.csv", "sha256": "0" * 64}]
    document["tables"] = {"unbound": document["tables"]["two_by_two"]}
    document["values"] = {}
    for key in ("steps", "variables", "models", "code_lists"):
        document.pop(key, None)
    third = project / "results" / "03_tables.json"
    third.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(third)
    capsys.readouterr()
    assert main(["impact", str(project / "data" / "gone.csv"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["results"] == ["results/03_tables.json"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_impact_with_no_file_lists_what_changed_since_the_last_commit(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no file, `impact` takes the files changed since the last commit, as `reworded`
    reads the working tree against it, and what depends on each."""
    import subprocess

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=project, check=True,
                       capture_output=True, timeout=60)  # fmt: skip

    monkeypatch.chdir(project)
    git("init", "-q")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "-m", "x")
    assert _impact(project) == []
    script = project / "analysis" / "01_disproportionality.py"
    script.write_text(script.read_text(encoding="utf-8") + "\n# a comment\n", encoding="utf-8")
    (found,) = _impact(project)
    assert found["file"] == "analysis/01_disproportionality.py"
    assert found["results"] == ["results/01_disproportionality.json"]
    # Round 1 of #280: git's names are read as UTF-8, not in the locale's code page.
    named = project / "manuscript" / ("r" + chr(0xE9) + "sum" + chr(0x8003) + ".md")
    named.write_text("New.\n", encoding="utf-8")
    assert named.name in {Path(one["file"]).name for one in _impact(project)}
    # Round 2 of #280: on a UTF-8 locale the name above passes without the encoding, so the
    # encoding git's names are read in is asked of the call itself.
    import manuscript_guard.impact as impact

    asked = []
    real = impact.subprocess.run

    def run(*args, **kwargs):
        asked.append(kwargs.get("encoding"))
        return real(*args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(impact.subprocess, "run", run)
        _impact(project)
    assert asked and set(asked) == {"utf-8"}
    # A file moved with `git mv` is two files to what depends on them: the old name's
    # readings are stale as much as the new name's, and rename detection lists only the new.
    named.unlink()
    git("mv", "manuscript/supplementary/S1_code_lists.md", "manuscript/supplementary/S1.md")
    files = {one["file"]: one for one in _impact(project)}
    assert {"manuscript/supplementary/S1_code_lists.md", "manuscript/supplementary/S1.md"} <= set(
        files
    ), files
    assert files["manuscript/supplementary/S1_code_lists.md"]["readings"]


# ------------------------------------------------------------- the authors' approvals


def _approvals_said(root: Path) -> list[tuple[str, str]]:
    from manuscript_guard.approvals import check_approvals

    project, _ = load_project(root)
    found = check_approvals(project).findings
    assert all(f.severity == "warn" for f in found)
    return sorted((f.code, f.message.split(" approved")[0].split(" has not")[0]) for f in found)


def test_an_approval_is_bound_to_the_manuscript_the_author_read(project: Path) -> None:
    """`approve --as` records an author's approval with the digest of the prose and
    the results; `submit` says which authors have none, and which approved a manuscript that
    has changed since. An author is found by ORCID iD, e-mail, full name or family name."""
    from manuscript_guard.cli import main

    assert _approvals_said(project) == [
        ("approval-missing", "Ada Example"), ("approval-missing", "Blaise Sample")
    ]
    assert main(["approve", str(project), "--as", "0000-0002-1825-0097"]) == 0
    assert main(["approve", str(project), "--as", "blaise sample", "--note", "as read"]) == 0
    assert _approvals_said(project) == []
    record = yaml.safe_load((project / "approvals" / "0000-0001-5109-3700.yaml").read_text("utf-8"))
    assert record["author"] == "Blaise Sample" and record["note"] == "as read"
    assert main(["approve", str(project), "--as", "Nobody"]) == 2

    path = main_md(project)
    path.write_text(path.read_text(encoding="utf-8") + "\nOne sentence more.\n", "utf-8")
    assert _approvals_said(project) == [
        ("approval-stale", "Ada Example"), ("approval-stale", "Blaise Sample")
    ]
    assert main(["approve", str(project), "--as", "Example"]) == 0
    assert _approvals_said(project) == [("approval-stale", "Blaise Sample")]


def test_two_authors_named_alike_are_approved_apart(project: Path) -> None:
    """Round 1 of #284: an approval was filed by the author's name folded to plain letters,
    so two authors with one name shared a file, and the one who never approved was not
    said. A file kept by the ORCID iD is each author's own, and a record names its author."""
    from manuscript_guard.cli import main

    authors = project / "authors.yaml"
    text = authors.read_text(encoding="utf-8")
    alike = "given: Wei\n    family: Zhang"
    for given, family in (("Ada", "Example"), ("Blaise", "Sample")):
        text = text.replace(f"given: {given}\n    family: {family}", alike)
    authors.write_text(text, encoding="utf-8")
    assert main(["approve", str(project), "--as", "0000-0002-1825-0097"]) == 0
    assert _approvals_said(project) == [("approval-missing", "Wei Zhang")]
    assert main(["approve", str(project), "--as", "0000-0001-5109-3700"]) == 0
    assert _approvals_said(project) == []


def test_an_approval_covers_the_title_page_the_authors_put_their_names_to(
    project: Path,
) -> None:
    """Round 1 of #284, Basile's choice of 2026-10-20: a new title, or an author added, left
    every approval of the old one standing, since the digest held the prose and the results
    alone. What the title page prints now counts; what it does not, a comment, a role, the
    keywords written another way, does not (round 1 of #355), nor an approval written
    before."""
    from manuscript_guard.cli import main

    both = ("0000-0002-1825-0097", "0000-0001-5109-3700")
    for author in both:
        assert main(["approve", str(project), "--as", author]) == 0
    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    commented = text.replace("target_journal:", "# a comment\ntarget_journal:")
    flowed = commented.replace("keywords:\n  - pharmacovigilance\n  - disproportionality\n  - "
                               "hepatotoxicity", "keywords: [pharmacovigilance, "
                               "disproportionality, hepatotoxicity]")  # fmt: skip
    assert flowed != commented
    paper.write_text(flowed, "utf-8")
    authors = project / "authors.yaml"
    listed = authors.read_text(encoding="utf-8")
    named = listed.replace("  statistician: Sample\n",
                           "  statistician: Sample\n  data_custodian: Example\n")  # fmt: skip
    assert named != listed
    authors.write_text(named, encoding="utf-8")
    assert _approvals_said(project) == []
    authors.write_text(listed, encoding="utf-8")
    paper.write_text(text.replace('short_title: "Hepatic injury with example-drug"',
                                  'short_title: "Hepatic injury"'), "utf-8")  # fmt: skip
    assert _approvals_said(project) == [
        ("approval-stale", "Ada Example"), ("approval-stale", "Blaise Sample")
    ]
    from manuscript_guard.approvals import check_approvals

    def front_said() -> list[str]:
        return [f.message for f in check_approvals(load_project(project)[0]).findings]

    said = front_said()
    assert len(said) == 2 and all(m.endswith(
        "and its title page, CRediT statement or declarations have changed since")
        for m in said), said  # fmt: skip
    for author in both:
        assert main(["approve", str(project), "--as", author]) == 0
    # Rounds 2 and 3 of #355: a competing interest, a grant and a CRediT role are printed in
    # the authors' names too.
    declared = authors.read_text(encoding="utf-8")
    for old, new in (('"None declared."', '"Fees from a comparator\'s maker."'),
                     ('    competing_interests:', '    funding:\n      - "Grant 1"\n'
                      '    competing_interests:'),
                     ("      - Conceptualization\n", "      - Conceptualization\n"
                      "      - Software\n")):  # fmt: skip
        assert old in declared, old
        authors.write_text(declared.replace(old, new, 1), "utf-8")
        said = front_said()
        front = "CRediT statement or declarations have changed since"
        assert len(said) == 2 and all(m.endswith(front) for m in said), (new, said)
    authors.write_text(declared, encoding="utf-8")
    authors.write_text(authors.read_text(encoding="utf-8").replace(
        "family: Sample", "family: Sample-Smith"), encoding="utf-8")  # fmt: skip
    said = _approvals_said(project)
    assert ("approval-stale", "Ada Example") in said, said
    # An approval written before the title page was held to is judged as it was given.
    for author in both:
        assert main(["approve", str(project), "--as", author]) == 0
    for path in (project / "approvals").glob("*.yaml"):
        kept = path.read_text(encoding="utf-8").splitlines()
        earlier = [line for line in kept if not line.startswith("front_sha256")]
        path.write_text("\n".join(earlier) + "\n", encoding="utf-8")
    paper.write_text(text.replace('short_title: "Hepatic injury with example-drug"',
                                  'short_title: "Another"'), "utf-8")  # fmt: skip
    assert _approvals_said(project) == []


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_submit_says_which_authors_have_not_approved(project: Path, capsys) -> None:
    """Round 1 of #284: `submit` prints the authors with no approval, and nothing asserted
    it; the pack is assembled all the same, since sending is the corresponding author's
    call."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    document = str(project / "build" / "manuscript.docx")
    capsys.readouterr()
    assert main(["submit", str(project), "--document", document, "--skip-checks"]) == 0
    said = capsys.readouterr().out
    assert said.count("has not approved the manuscript") == 2, said
    assert "Ada Example has not" in said and "Blaise Sample has not" in said
    assert 'manuscript-guard approve --as "Ada Example"' in said
    for author in ("0000-0002-1825-0097", "0000-0001-5109-3700"):
        assert main(["approve", str(project), "--as", author]) == 0
    capsys.readouterr()
    assert main(["submit", str(project), "--document", document, "--skip-checks"]) == 0
    assert "approved" not in capsys.readouterr().out


# ------------------------------------------------ the unit written after a binding


def _unit_emitted(root: Path, key: str, unit: str | None) -> None:
    fragment = next((root / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    entry = document["values"][key]
    if unit is None:
        entry.pop("unit", None)
    else:
        entry["unit"] = unit
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


def _units_said(root: Path) -> list[tuple[str, int]]:
    from manuscript_guard.gates import check_bound_units

    project, _ = load_project(root)
    _, results, _, _ = load_namespace(project)
    found = check_bound_units(project, results).findings
    assert all(f.code == "unit-differs-from-emitted" and f.severity == "warn" for f in found)
    return [(f.message.split()[0], f.line) for f in found]


@pytest.mark.parametrize(
    ("emitted", "written", "said"),
    [
        ("\N{PER MILLE SIGN}", None, True),  # the example's "%" after a share emitted per mille
        ("%", None, False),  # as the example has it
        ("\N{MICRO SIGN}g", " mg", True),
        ("\N{MICRO SIGN}g", " mcg", False),
        ("\N{MICRO SIGN}g", " \N{GREEK SMALL LETTER MU}g", False),
        ("mg/kg", " mg/kg", False),
        ("years", " mg", False),  # no symbol emitted: nothing to compare
        (None, " mg", False),  # no unit emitted
        # Round 1 of #279: a litre after a slash in either case, and what may stand between
        # the binding and its unit, pandoc's escaped space, an entity, a comment and the
        # narrow spaces, none of which hid the unit from the reading.
        ("mmol/L", " mmol/l", False),
        ("\N{MICRO SIGN}g", "\\ mg", True),
        ("\N{MICRO SIGN}g", "&nbsp;mg", True),
        ("\N{MICRO SIGN}g", "<!-- the dose --> mg", True),
        ("\N{MICRO SIGN}g", "\N{HAIR SPACE}mg", True),
        ("\N{MICRO SIGN}g", "\N{FIGURE SPACE}mg", True),
        # Round 1 of #341: the other spellings of the entity are read, and no unit is read
        # across the words between two comments.
        ("\N{MICRO SIGN}g", "&#0160;mg", True),
        ("\N{MICRO SIGN}g", "&NonBreakingSpace;mg", True),
        ("\N{MICRO SIGN}g", "<!-- a --> patients were given <!-- b --> mg", False),
    ],
)
def test_a_unit_written_after_a_binding_is_the_one_emitted(
    project: Path, emitted: str | None, written: str | None, said: bool
) -> None:
    """"{{results.dose}} mg" printed "250 mg" of a value emitted in micrograms. A
    unit written after a binding that is not the emitted one is said; spellings of one unit
    are one unit, and a value emitted with no unit, or none of symbols, is not compared."""
    _unit_emitted(project, "case.pct_serious", emitted)
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    if written is not None:
        binding = "{{results.case.pct_serious}}"
        text = text.replace(binding + "%", binding + written, 1)
        path.write_text(text, encoding="utf-8")
    line = next(n for n, row in enumerate(text.splitlines(), 1) if "case.pct_serious" in row)
    assert _units_said(project) == ([("results.case.pct_serious", line)] if said else [])


@pytest.mark.parametrize(("emitted", "written", "said"), [
    # A divisor after a space is not read: the written unit is its first symbol, and an
    # emitted one is compared with nothing.
    ("mg/kg", " mg kg-1", True),
    ("mg kg-1", " mg/kg", False),
    # A divisor written as a word is not read either.
    ("mg/kg/day", " mg/kg per day", True),
])  # fmt: skip
def test_what_the_unit_reading_gets_wrong_is_pinned(
    project: Path, emitted: str, written: str, said: bool
) -> None:
    """Known gaps, as DESIGN.md writes them (round 1 of #279, where it said "mg/kg" and
    "mg kg-1" were taken for two units both ways)."""
    _unit_emitted(project, "case.pct_serious", emitted)
    path = main_md(project)
    binding = "{{results.case.pct_serious}}"
    path.write_text(path.read_text(encoding="utf-8").replace(binding + "%", binding + written, 1),
                    encoding="utf-8")  # fmt: skip
    assert bool(_units_said(project)) is said


@pytest.mark.parametrize(("written", "emitted"), [
    ("\N{GREEK SMALL LETTER MU}g", "\N{MICRO SIGN}g"), ("mcg", "\N{MICRO SIGN}g"),
    ("ml", "mL"), ("dl", "dL"), ("mmol/l", "mmol/L"), ("mg/dl", "mg/dL"),
    ("\N{GREEK SMALL LETTER MU}L", "\N{MICRO SIGN}L"), ("\N{MICRO SIGN}l", "\N{MICRO SIGN}L"),
    ("\N{GREEK SMALL LETTER MU}l", "\N{MICRO SIGN}L"),
    ("\N{GREEK SMALL LETTER MU}m", "\N{MICRO SIGN}m"),
    ("\N{GREEK SMALL LETTER MU}mol", "\N{MICRO SIGN}mol"),
    ("\N{GREEK SMALL LETTER MU}M", "\N{MICRO SIGN}M"),
    ("\N{GREEK SMALL LETTER MU}Sv", "\N{MICRO SIGN}Sv"),
    ("\N{MASCULINE ORDINAL INDICATOR}C", "\N{DEGREE SIGN}C"),
    ("\N{DEGREE CELSIUS}", "\N{DEGREE SIGN}C"),
    ("\N{MASCULINE ORDINAL INDICATOR}F", "\N{DEGREE SIGN}F"),
    ("cm\N{SUPERSCRIPT TWO}", "cm2"), ("cm^2^", "cm2"), ("cm\N{SUPERSCRIPT THREE}", "cm3"),
    ("h\N{MINUS SIGN}1", "h-1"),
])  # fmt: skip
def test_every_spelling_of_one_unit_is_one_unit(written: str, emitted: str) -> None:
    """Round 1 of #279: only mcg and mu were held, so an empty list of spellings passed."""
    from manuscript_guard.gates.bound_units import same_unit

    assert same_unit(written, emitted) is True
    assert same_unit(written, "kg") is False


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


# ------------------------------------------------- the response to the reviewers


def _round_with(root: Path, points: list[dict]) -> Path:
    """Round 1, opened as `respond --open` opens it, with these points."""
    from manuscript_guard.cli import main

    assert main(["respond", str(root), "--open"]) == 0
    path = root / "revision" / "round-1.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["reviewers"] = [{"id": "reviewer-1", "points": points}]
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), "utf-8")
    return path


def _point(**fields) -> dict:
    return {"id": "1.1", "comment": "Report the adjusted ratio.", **fields}


def _g13(root: Path, *, submission: bool = True):
    from manuscript_guard.gates import check_revision

    project, _ = load_project(root)
    return check_revision(project, submission=submission)


def _said(report, *codes: str) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in report.findings if f.code in codes]


def _in_the_discussion(root: Path, sentence: str) -> None:
    path = main_md(root)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("# Data availability", f"{sentence}\n\n# Data availability", 1),
                    encoding="utf-8")  # fmt: skip


def _reply_numbers(root: Path) -> list[str]:
    return [
        f.message
        for f in gate_report(root).findings
        if f.code in ("unclassified-number", "reply-unbound-number")
        and f.path and f.path.name == "round-1.yaml"
    ]


def test_a_result_typed_into_a_reply_fails(project: Path) -> None:
    """Item 11: the letter prints a reply word for word, and G2 read only the manuscript."""
    _round_with(project, [_point(
        response="The adjusted ROR is now 2.31 (95% CI 1.40 to 3.80).",
        rebutted="We kept 412 reports.",
    )])  # fmt: skip
    said = _reply_numbers(project)
    assert any("2.31" in m and "`response`" in m for m in said), said
    assert any("412" in m and "`rebutted`" in m for m in said), said
    assert not any("95" in m for m in said), "a convention is not a result"


def test_a_reply_names_places_by_number_and_types_no_threshold(project: Path) -> None:
    """Round 1 of #266: a line, a reviewer, a comment and a page are places, and a threshold
    typed in a reply is a result: the Methods' conventions are not the reply's."""
    _round_with(project, [_point(
        response="The changes are on lines 120-125 of the revised manuscript, as Reviewer 2 "
        "asked (see our response to comment 1.3, page 4).",
        rebutted="The interaction is now significant (p < 0.001).",
    )])  # fmt: skip
    said = _reply_numbers(project)
    assert [m for m in said if "`response`" in m] == [], said
    assert any("0.001" in m for m in said), said


@pytest.mark.parametrize(
    ("reply", "typed"),
    [
        # Round 2 of #266: a comma after a place does not run on to the count after it.
        ("As suggested by Reviewer 1, 312 controls were added.", "312"),
        ("In response to comment 1.3, 41 reports were reclassified.", "41"),
        # A place word at the end of a paragraph names nothing in the next.
        ("We thank the reviewers\n\n41 cases were excluded.", "41"),
    ],
)
def test_a_count_after_a_place_is_still_a_count(project: Path, reply: str, typed: str) -> None:
    _round_with(project, [_point(response=reply, rebutted="x")])
    assert any(f"{typed!r}" in m for m in _reply_numbers(project)), _reply_numbers(project)


def test_a_number_typed_in_a_reply_fails_at_submission_only(project: Path) -> None:
    from manuscript_guard.policy import DRAFTING, SUBMISSION, apply_stage

    _round_with(project, [_point(response="The ROR is now 2.31.", rebutted="x")])
    report = gate_report(project)
    drafting, _ = apply_stage(report, DRAFTING)
    assert "reply-unbound-number" not in {f.code for f in drafting.failures}
    submission, _ = apply_stage(report, SUBMISSION)
    assert "reply-unbound-number" in {f.code for f in submission.failures}


def test_a_result_bound_in_a_reply_passes_and_is_printed(project: Path) -> None:
    from manuscript_guard.build.submission import response_letter
    from manuscript_guard.contracts import load_namespace

    _round_with(project, [_point(
        response="The ROR is now {{results.ror.point}} (95% CI {{results.ror.ci_low}} to "
        "{{results.ror.ci_high}}).",
        changed=[{"kind": "results", "name": "ror.point"}],
    )])  # fmt: skip
    assert _reply_numbers(project) == []
    projekt, _ = load_project(project)
    point = load_namespace(projekt)[0]["results.ror.point"].display
    letter = response_letter(projekt)
    assert f"The ROR is now {point}" in letter and "{{" not in letter


def test_a_binding_in_a_reply_that_names_nothing_fails(project: Path) -> None:
    _round_with(project, [_point(response="Now {{results.no_such_key}}.", rebutted="x")])
    said = [f for f in gate_report(project).findings if f.code == "unresolved-binding"]
    assert any("round 1" in f.message for f in said), said


def test_a_quoted_revision_that_is_in_the_paper_and_new_passes(project: Path) -> None:
    _round_with(project, [_point(
        response="We now say so.",
        changed=[{"kind": "text", "quote": "The adjusted ratio was {{results.ror.point}}.",
                  "section": "Discussion"}],
    )])  # fmt: skip
    _in_the_discussion(project, "The *adjusted* ratio was\n{{results.ror.point}}.")
    assert _said(_g13(project), "quoted-text-absent", "quoted-text-not-new",
                 "quoted-text-elsewhere", "quoted-text-unchecked") == []  # fmt: skip


def test_a_quoted_revision_the_paper_does_not_hold_fails(project: Path) -> None:
    _round_with(project, [_point(
        response="We now say so.",
        changed=[{"kind": "text", "quote": "The adjusted ratio was reported."}],
    )])  # fmt: skip
    assert _said(_g13(project), "quoted-text-absent") == [("quoted-text-absent", "fail")]
    assert _said(_g13(project, submission=False), "quoted-text-absent") == [
        ("quoted-text-absent", "warn")
    ]


def test_a_quoted_revision_the_journal_already_read_fails(project: Path) -> None:
    _in_the_discussion(project, "A sentence the journal has read.")
    _round_with(project, [_point(
        response="We now say so.",
        changed=[{"kind": "text", "quote": "A sentence the journal has read."}],
    )])  # fmt: skip
    assert _said(_g13(project), "quoted-text-not-new") == [("quoted-text-not-new", "fail")]


def test_a_quote_of_the_printed_sentence_against_its_markup_is_pinned() -> None:
    """Known gaps (round 1 of #266): a quote is compared with the Markdown less its `*`,
    backticks and comments, so emphasis written with underscores, or a citation, keeps a
    quote of the sentence as it prints from matching it."""
    from manuscript_guard.gates.revision import as_quoted

    assert "The ratio rose" in as_quoted("The *ratio* rose.")
    assert "The ratio rose" not in as_quoted("The _ratio_ rose.")
    assert "as reported (1)" not in as_quoted("as reported [@key].")


def test_a_quoted_revision_in_another_section_fails(project: Path) -> None:
    _round_with(project, [_point(
        response="We now say so in the Abstract.",
        changed=[{"kind": "text", "quote": "A new sentence.", "section": "Abstract"}],
    )])  # fmt: skip
    _in_the_discussion(project, "A new sentence.")
    assert _said(_g13(project), "quoted-text-elsewhere") == [("quoted-text-elsewhere", "fail")]


def test_a_quoted_revision_in_a_round_without_a_copy_is_a_note(project: Path) -> None:
    import shutil

    _round_with(project, [_point(
        response="We now say so.", changed=[{"kind": "text", "quote": "A new sentence."}]
    )])  # fmt: skip
    shutil.rmtree(project / "revision" / "round-1")
    _in_the_discussion(project, "A new sentence.")
    assert _said(_g13(project), "quoted-text-unchecked") == [("quoted-text-unchecked", "info")]


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        ("As manuscript-guard reported, the count changed.", "response-leak"),
        ("G13: point-unanswered was resolved.", "response-leak"),
        ("See main.md:120 for the new text.", "response-leak"),
        ("We add the count [AUTHOR: give the new count].", "response-placeholder"),
        ("TODO: answer this.", "response-artefact"),
        ("We revised it oaicite here.", "response-artefact"),
    ],
)
def test_what_must_not_reach_a_journal_in_a_reply_fails(
    project: Path, reply: str, code: str
) -> None:
    _round_with(project, [_point(response=reply, rebutted="No change was needed.")])
    assert _said(_g13(project), code) == [(code, "fail")]


def test_a_note_on_a_change_is_read_as_the_reply_is(project: Path) -> None:
    """Round 1 of #266: a changed entry's `note` is printed in the letter after the change,
    and neither G13's reply checks nor G2 read it."""
    changed = [{"kind": "text", "quote": "A new sentence.", "note": "TODO: say where."}]
    _round_with(project, [_point(response="We now say so.", changed=changed)])
    assert _said(_g13(project), "response-artefact") == [("response-artefact", "fail")]
    changed[0]["note"] = "as the reviewer asked, from line 120"
    _round_with(project, [_point(response="We now say so.", changed=changed)])
    from manuscript_guard.gates.numbers import replies

    document = {"reviewers": [{"id": "r", "points": [{"id": "1", "changed": changed}]}]}
    assert replies(document, 1) == [("round 1, r point 1, `changed[0].note`",
                                     "as the reviewer asked, from line 120")]  # fmt: skip
    # Through G2 itself, and round 1 of #349: a binding in the note is filled in the letter,
    # as the reply's are, where it was printed as typed.
    changed[0]["note"] = "the ROR is now 2.31"
    _round_with(project, [_point(response="We now say so.", changed=changed)])
    assert any("2.31" in m and "changed[0].note" in m for m in _reply_numbers(project))
    changed[0]["note"] = "the ROR is now {{results.ror.point}}"
    _round_with(project, [_point(response="We now say so.", changed=changed)])
    assert _reply_numbers(project) == []
    from manuscript_guard.build.submission import response_letter
    from manuscript_guard.contracts import load_namespace

    projekt, _ = load_project(project)
    point = load_namespace(projekt)[0]["results.ror.point"].display
    letter = response_letter(projekt)
    assert f"the ROR is now {point}" in letter and "{{" not in letter


@pytest.mark.parametrize(
    "reply",
    [
        "Certainly, we have revised the Methods.",
        "Cells arrested in G2/M were excluded, as the reviewer asked.",
        # Round 1 of #266: a tumour's grade, with what it means in brackets.
        "Most tumours were G1 (well-differentiated).",
        "The changes are on line 120 of the revised manuscript.",
    ],
)
def test_what_a_reply_may_say_passes(project: Path, reply: str) -> None:
    _round_with(project, [_point(response=reply, rebutted="No change was needed.")])
    report = _g13(project)
    assert _said(report, "response-leak", "response-placeholder", "response-artefact") == []


def test_the_templates_words_left_for_the_reviewers_fail(project: Path) -> None:
    from manuscript_guard.gates.revision import TEMPLATE_COMMENT

    _round_with(project, [{"id": "1.1", "comment": TEMPLATE_COMMENT,
                           "response": "Done.", "rebutted": "Nothing to change."}])  # fmt: skip
    assert _said(_g13(project), "response-placeholder") == [("response-placeholder", "fail")]


def test_opening_a_round_keeps_the_manuscript_as_it_renders(project: Path) -> None:
    from manuscript_guard.contracts import load_namespace

    _round_with(project, [_point(response="x", rebutted="y")])
    kept = (project / "revision" / "round-1" / "submitted" / "main.md").read_text("utf-8")
    projekt, _ = load_project(project)
    point = load_namespace(projekt)[0]["results.ror.point"].display
    assert point in kept and "{{results.ror.point}}" not in kept


# ------------------------------------------------- a statistic reported whole


#: A fragment declaring a p value of an estimate, a second p value of its family, a share
#: of two counts, and the estimate's interval.
_WHOLE = {
    "or.point": {"value": 2.5, "display": "2.50"},
    "or.ci_low": {"value": 1.4, "display": "1.40", "bounds": "or.point", "bound": "low"},
    "or.ci_high": {"value": 3.8, "display": "3.80", "bounds": "or.point", "bound": "high"},
    "or.p": {"value": 0.012, "display": "0.012", "of": "or.point", "family": "secondary"},
    "hr.p": {"value": 0.043, "display": "0.043", "of": "or.point", "family": "secondary"},
    "female.pct": {"value": 52.1, "display": "52.1", "of": "female.n", "over": "cohort.n"},
    "female.n": {"value": 521, "display": "521"},
    "cohort.n": {"value": 1000, "display": "1000"},
}


def _with_whole(root: Path, paragraph: str, corrections: dict | None = None) -> None:
    document = {
        "schema": "manuscript-guard/results/1",
        "provenance": {
            "generated_by": "analysis/01_disproportionality.py",
            "generated_at": "2026-10-15T00:00:00+00:00",
        },
        "values": {f"whole.{key}": dict(spec) for key, spec in _WHOLE.items()},
    }
    for spec in document["values"].values():
        for field in ("bounds", "of", "over"):
            if field in spec:
                spec[field] = f"whole.{spec[field]}"
    if corrections is not None:
        document["corrections"] = corrections
    fragment = root / "results" / "02_whole.json"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    path = main_md(root)
    path.write_text(path.read_text(encoding="utf-8") + f"\n\n{paragraph}\n", encoding="utf-8")


# ------------------------------------------------- what the data statement says


_DATA_POLICY = {
    "source": "https://example.org/data-policy",
    "retrieved_on": "2026-10-15",
    "forbidden": [
        {
            "pattern": r"(?i)\bon (?:reasonable )?request\b",
            "unless": r"(?i)\b(?:because|privacy|committee)\b",
            "why": "say why the data cannot be shared, and how to ask",
        },
        {"pattern": r"(?i)\bupon acceptance\b", "why": "deposit before publication"},
    ],
    "identifier_required": True,
    "no_data": [r"(?i)\bdoes not report data\b"],
}


def _data_statement(root: Path, statement: str, policy: dict | None = None) -> list:
    profile = root / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["data_availability"] = policy or _DATA_POLICY
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    path = main_md(root)
    text = path.read_text(encoding="utf-8")
    start, end = text.index("# Data availability"), text.index("# Funding")
    path.write_text(text[:start] + f"# Data availability\n\n{statement}\n\n" + text[end:],
                    encoding="utf-8")  # fmt: skip
    return _data_findings(root)


def _data_findings(root: Path) -> list:
    from manuscript_guard.gates import check_journal

    project, _ = load_project(root)
    codes_ = {"data-statement-forbidden", "data-identifier-missing", "data-link-temporary",
              "data-doi-uncited"}  # fmt: skip
    return sorted((f.code, f.severity) for f in check_journal(project).findings if f.code in codes_)


@pytest.mark.parametrize(
    ("statement", "said"),
    [
        # Item 16: on request with no reason or route, and a promise for later.
        ("Data are available on reasonable request.",
         [("data-identifier-missing", "fail"), ("data-statement-forbidden", "fail")]),
        ("Data will be deposited upon acceptance.",
         [("data-identifier-missing", "fail"), ("data-statement-forbidden", "fail")]),
        # No identifier where the journal requires one.
        ("The data are held by the study team.", [("data-identifier-missing", "fail")]),
        # A shared drive and a bare repository are neither persistent nor archived.
        ("Data: https://drive.google.com/x and doi:10.5281/zenodo.1234567.",
         [("data-doi-uncited", "warn"), ("data-link-temporary", "warn")]),
        ("Code and data: https://github.com/someone/study, GSE123456.",
         [("data-link-temporary", "warn")]),
    ],
)  # fmt: skip
def test_a_data_statement_the_journal_does_not_accept_is_reported(
    project: Path, statement: str, said: list
) -> None:
    assert _data_statement(project, statement) == said


@pytest.mark.parametrize(
    "statement",
    [
        "Data are available on reasonable request from the data access committee, because "
        "of patient privacy. GEO accession GSE123456.",
        "The dataset is in GEO under GSE123456, and the code at "
        "https://github.com/someone/study/releases/tag/v1.0.",
        "This article does not report data.",
    ],
)
def test_a_data_statement_the_journal_accepts_passes(project: Path, statement: str) -> None:
    assert _data_statement(project, statement) == []


def test_a_dataset_cited_by_its_key_is_named_by_its_doi(project: Path) -> None:
    """Round 1 of #269: a data citation made as the journal asks, by its key, counted as no
    identifier, though the reference list prints its DOI. Round 2: an article cited in the
    statement, a cohort profile, named data it does not hold."""
    bib = project / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    article = "@article{fictionalClassSignal2019,\n"
    text = text.replace(article, article + "  doi = {10.1016/x.2019.1},\n", 1)
    dataset = "@dataset{fictionalHepaticCohort2021,\n  doi = {10.5281/zenodo.1234567},\n"
    bib.write_text(
        text.replace("@article{fictionalHepaticCohort2021,\n", dataset, 1), encoding="utf-8"
    )
    assert _data_statement(project, "Data are in Zenodo [@fictionalHepaticCohort2021].") == []
    assert _data_statement(
        project, "The data are held by the study team [@fictionalClassSignal2019]."
    ) == [("data-identifier-missing", "fail")]


def test_a_dataset_written_as_misc_with_its_type_field_is_named_by_its_doi(
    project: Path,
) -> None:
    """Round 1 of #345: BibTeX has no `@dataset`, and a hand-kept file writes one as `@misc`
    with `type = {dataset}`; the reader that kept the entry's own type dropped the field."""
    bib = project / "literature" / "references.bib"
    dataset = ("@misc{fictionalHepaticCohort2021,\n  type = {dataset},\n"
               "  doi = {10.5281/zenodo.1234567},\n")  # fmt: skip
    bib.write_text(
        bib.read_text(encoding="utf-8").replace(
            "@article{fictionalHepaticCohort2021,\n", dataset, 1
        ),
        encoding="utf-8",
    )
    assert _data_statement(project, "Data are in Zenodo [@fictionalHepaticCohort2021].") == []


@pytest.mark.parametrize(
    ("before", "heading"),
    [
        # A Methods subsection that matches the default words is not the statement.
        ("## Data sharing between sites\n\nThe sites shared records weekly.\n\n",
         "# Data availability"),
        ("", "# 7. Data availability"),
        ("", "# Data and code availability"),
    ],
)  # fmt: skip
def test_the_statement_is_found_under_its_heading_however_written(
    project: Path, before: str, heading: str
) -> None:
    def said(statement: str) -> list:
        _data_statement(project, statement)
        path = main_md(project)
        text = path.read_text(encoding="utf-8").replace("# Results", before + "# Results", 1)
        path.write_text(text.replace("# Data availability", heading, 1), encoding="utf-8")
        return _data_findings(project)

    assert said("The dataset is in GEO, GSE123456.") == []
    path = main_md(project)
    text = path.read_text(encoding="utf-8").replace(before, "", 1)
    path.write_text(text.replace(heading, "# Data availability", 1), encoding="utf-8")
    assert said("Data are held by the team.") == [("data-identifier-missing", "fail")]


def test_a_statement_heading_level_with_a_methods_subsection_is_pinned(project: Path) -> None:
    """Known gaps (round 2 of #269): of two matching headings at one level, the first is
    read, so a numbered Methods subsection on data sharing is taken for the statement where
    the statement stands under a Declarations heading at the same level."""
    _data_statement(project, "Data are held by the team.")
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    text = text.replace("# Results", "## 2.4 Data sharing between sites\n\nThe sites shared "
                        "records weekly.\n\n# Results", 1)  # fmt: skip
    text = text.replace("# Data availability\n\nData are held by the team.",
                        "# Declarations\n\n## Availability of data and materials\n\nThe "
                        "dataset is in GEO, GSE123456.", 1)  # fmt: skip
    path.write_text(text, encoding="utf-8")
    assert _data_findings(project) == [("data-identifier-missing", "fail")]


def test_a_dataset_doi_the_reference_list_cites_passes(project: Path) -> None:
    bib = project / "literature" / "references.bib"
    opening = "@article{fictionalHepaticCohort2021,\n"
    bib.write_text(bib.read_text(encoding="utf-8").replace(
        opening, opening + "  doi = {10.5281/zenodo.1234567},\n", 1), encoding="utf-8")  # fmt: skip
    assert _data_statement(project, "Data: https://doi.org/10.5281/ZENODO.1234567.") == []
    # A DOI with a parenthesis of its own, and one set in bold, are read whole.
    other = "@article{fictionalClassSignal2019,\n"
    lancet = "  doi = {10.1016/S0140-6736(20)30183-5},\n"
    bib.write_text(bib.read_text(encoding="utf-8").replace(other, other + lancet, 1), "utf-8")
    assert _data_statement(
        project, "Data: 10.1016/S0140-6736(20)30183-5 and **10.5281/zenodo.1234567**."
    ) == []


def test_a_profile_with_no_data_policy_reads_nothing_under_the_heading(project: Path) -> None:
    from manuscript_guard.gates import check_journal

    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    said = text.replace("The synthetic dataset", "On request only. The synthetic dataset", 1)
    path.write_text(said, encoding="utf-8")
    project_, _ = load_project(project)
    assert not [f for f in check_journal(project_).findings if f.code.startswith("data-")]


def test_a_forbidden_data_statement_fails_from_internal_review(project: Path) -> None:
    from manuscript_guard.gates import check_journal
    from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, apply_stage

    _data_statement(project, "Data are available on request.")
    project_, _ = load_project(project)
    report = check_journal(project_)
    drafting, _ = apply_stage(report, DRAFTING)
    assert "data-statement-forbidden" not in {f.code for f in drafting.failures}
    reviewed, _ = apply_stage(report, INTERNAL_REVIEW)
    assert "data-statement-forbidden" in {f.code for f in reviewed.failures}


# ------------------------------------------------- a placeholder, wherever it is written


def _g6(root: Path, results=None):
    from manuscript_guard.gates import check_writing

    project, _ = load_project(root)
    if results is None:
        _namespace, results, _literature, _report = load_namespace(project)
    return check_writing(project, results)


def _placeholders(report) -> list[tuple[str, str]]:
    return [(f.severity, f.message) for f in report.findings if f.code == "model-artefact"]


def _with_paragraph(root: Path, paragraph: str) -> None:
    path = main_md(root)
    path.write_text(path.read_text(encoding="utf-8") + f"\n\n{paragraph}\n", encoding="utf-8")


_LABEL_CODES = ("interval-level-differs", "interval-level-undeclared", "spread-label-differs")


def _labels_said(root: Path) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in gate_report(root).findings if f.code in _LABEL_CODES]


def test_a_spread_quoted_without_its_mean_is_no_p_value_alone(project: Path) -> None:
    """Round 1 of #327: a spread records what it is of, and G2 took it for a p value quoted
    without its estimate, which it "tests"."""
    document = {
        "schema": "manuscript-guard/results/1",
        "provenance": {"generated_by": "analysis/01_disproportionality.py",
                       "generated_at": "2026-10-18T00:00:00+00:00"},
        "values": {
            "age.mean": {"value": 45.2, "display": "45.2"},
            "age.sd": {"value": 12.3, "display": "12.3", "spread": "sd", "of": "age.mean"},
        },
    }  # fmt: skip
    fragment = project / "results" / "02_labels.json"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    path = main_md(project)
    path.write_text(path.read_text(encoding="utf-8") + "\n\nMean age was "
                    "{{results.age.mean}} years. Its SD was {{results.age.sd}}.\n",
                    encoding="utf-8")  # fmt: skip
    assert "quoted-alone" not in {f.code for f in gate_report(project).findings}


def test_a_level_written_otherwise_than_emitted_is_said(project: Path) -> None:
    """Item 33, as the brief found it: the abstract's "(95% CI ...)" changed to "(90% CI ...)"
    over the example's 95% interval, and `check` said nothing."""
    assert _labels_said(project) == []
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    assert text.count("(95% CI {{results.ror.ci_low}}") >= 1
    path.write_text(text.replace("(95% CI {{results.ror.ci_low}}", "(90% CI {{results.ror.ci_low}}",
                                 1), encoding="utf-8")  # fmt: skip
    assert _labels_said(project) == [("interval-level-differs", "warn")]


def test_an_interval_quoted_with_no_level_emitted_asks_for_it(project: Path) -> None:
    for end in ("ci_low", "ci_high"):
        _value_has(project, f"ror.{end}", level=None)
    assert _labels_said(project) == [("interval-level-undeclared", "warn")]


def test_a_spread_labelled_the_other_kind_is_said(project: Path) -> None:
    document = {
        "schema": "manuscript-guard/results/1",
        "provenance": {"generated_by": "analysis/01_disproportionality.py",
                       "generated_at": "2026-10-18T00:00:00+00:00"},
        "values": {
            "age.mean": {"value": 45.2, "display": "45.2"},
            "age.sd": {"value": 12.3, "display": "12.3", "spread": "sd", "of": "age.mean"},
        },
    }  # fmt: skip
    fragment = project / "results" / "02_labels.json"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    path = main_md(project)
    plain = path.read_text(encoding="utf-8")
    path.write_text(plain + "\n\nAge was {{results.age.mean}} (SD {{results.age.sd}}) years.\n",
                    encoding="utf-8")  # fmt: skip
    assert _labels_said(project) == []
    path.write_text(plain + "\n\nAge was {{results.age.mean}} (SE {{results.age.sd}}) years.\n",
                    encoding="utf-8")  # fmt: skip
    assert _labels_said(project) == [("spread-label-differs", "warn")]


def _whole_said(root: Path) -> list[tuple[str, str]]:
    codes_ = ("quoted-alone", "interval-not-quoted-whole", "family-uncorrected")
    return [(f.code, f.severity) for f in gate_report(root).findings if f.code in codes_]


_ESTIMATE = "{{results.whole.or.point}} (95% CI {{results.whole.or.ci_low}} to " \
    "{{results.whole.or.ci_high}})"


@pytest.mark.parametrize(
    ("paragraph", "said"),
    [
        # A p value in the sentence after its estimate.
        (f"The ratio was {_ESTIMATE}. P was {{{{results.whole.or.p}}}}.", ["quoted-alone"]),
        # A share with neither count.
        (f"The ratio was {_ESTIMATE}. Women were {{{{results.whole.female.pct}}}}%.",
         ["quoted-alone"]),
        # An estimate quoted, and its interval never whole.
        ("The ratio was {{results.whole.or.point}}, below {{results.whole.or.ci_high}}.",
         ["interval-not-quoted-whole"]),
    ],
)  # fmt: skip
def test_a_statistic_quoted_without_what_it_belongs_to_is_a_warning(
    project: Path, paragraph: str, said: list[str]
) -> None:
    """Item 13: nothing tied a p value to its estimate, a share to its counts, or asked that
    an interval's two bounds be quoted together anywhere."""
    _with_whole(project, paragraph, {"secondary": {"method": "holm"}})
    assert _whole_said(project) == [(code, "warn") for code in said]


@pytest.mark.parametrize(
    "paragraph",
    [
        f"The ratio was {_ESTIMATE} (P = {{{{results.whole.or.p}}}}).",
        f"The ratio was {_ESTIMATE}. Of {{{{results.whole.cohort.n}}}} patients, "
        "{{results.whole.female.n}} ({{results.whole.female.pct}}%) were women.",
        f"The ratio was {_ESTIMATE}. It was {{{{results.whole.or.point}}}} again.",
        # #267: the stop of "s.e." before a number ends no sentence, as `labels` reads it.
        f"The ratio was {_ESTIMATE} (s.e. 0.21), P = {{{{results.whole.or.p}}}}.",
    ],
)
def test_a_statistic_quoted_with_what_it_belongs_to_passes(project: Path, paragraph: str) -> None:
    _with_whole(project, paragraph, {"secondary": {"method": "holm"}})
    assert _whole_said(project) == []


def test_a_statistic_naming_what_nothing_emits_says_so(project: Path) -> None:
    """#267: a p value whose `of` names a key no fragment emits was said to be quoted
    alone, whatever its sentence held; it is the name that is wrong."""
    _with_whole(project, f"The ratio was {_ESTIMATE}.", {"secondary": {"method": "holm"}})
    fragment = project / "results" / "02_whole.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["whole.hr.p"]["of"] = "whole.hr.point"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nThe hazard ratio had P = "
        "{{results.whole.hr.p}} beside {{results.whole.or.point}}.\n",
        encoding="utf-8",
    )
    said = [f for f in gate_report(project).findings if f.code == "quoted-alone"]
    assert [f.message for f in said] == [
        "results.whole.hr.p names results.whole.hr.point as what it belongs to, which "
        "nothing emits"
    ]


def test_a_share_naming_what_nothing_emits_beside_its_other_count_says_so(
    project: Path,
) -> None:
    """Round 1 of #343: a share whose `of` is misspelt, quoted beside its `over`, passed,
    since the sentence held one of its names; no other gate reads `over`."""
    paragraph = ("Of {{results.whole.cohort.n}} patients, {{results.whole.female.pct}}% were "
                 "women.")  # fmt: skip
    _with_whole(project, f"The ratio was {_ESTIMATE}. {paragraph}",
                {"secondary": {"method": "holm"}})  # fmt: skip
    fragment = project / "results" / "02_whole.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["whole.female.pct"]["of"] = "whole.femal.n"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    said = [f for f in gate_report(project).findings if f.code == "quoted-alone"]
    assert [f.message for f in said] == [
        "results.whole.female.pct names results.whole.femal.n as what it belongs to, which "
        "nothing emits"
    ]
    # Round 2 of #343: the name nothing emits, bound in the sentence, is said once, as the
    # binding that resolves to nothing.
    del document["values"]["whole.cohort.n"]
    document["values"]["whole.female.pct"]["of"] = "whole.female.n"
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    codes = [f.code for f in gate_report(project).findings
             if f.code in ("quoted-alone", "unresolved-binding")]  # fmt: skip
    assert codes == ["unresolved-binding"]


@pytest.mark.parametrize(
    ("added", "paragraph", "said"),
    [
        # A second level of the same estimate is asked for whole as well, though the paper
        # quotes the one it means.
        ({"values": {"whole.or.ci90_low": {"value": 1.6, "display": "1.60",
                                           "bounds": "whole.or.point", "bound": "low",
                                           "level": "90%"},
                     "whole.or.ci90_high": {"value": 3.4, "display": "3.40",
                                            "bounds": "whole.or.point", "bound": "high",
                                            "level": "90%"}}},
         f"The ratio was {_ESTIMATE}.", ["interval-not-quoted-whole"]),
        # An interval quoted whole only in a table the analysis emits: its cells are text,
        # and no sentence binds the bounds.
        ({"tables": {"ratios": {"columns": ["Ratio", "95% CI"],
                                "rows": [["2.50", "1.40 to 3.80"]]}}},
         "The ratio was {{results.whole.or.point}} (Table 3).\n\n{{table.ratios}}",
         ["interval-not-quoted-whole"]),
        # A caption that gives a P again is a sentence of its own.
        ({}, f"The ratio was {_ESTIMATE} (P = {{{{results.whole.or.p}}}}).\n\n"
             "Table: Ratios; P = {{results.whole.or.p}} for the first.", ["quoted-alone"]),
        # A key declared the same quantity as the estimate stands for nothing of it.
        ({"values": {"whole.headline": {"value": 2.5, "display": "2.50",
                                        "same_as": "whole.or.point"}}},
         f"The ratio was {_ESTIMATE}. Overall it was {{{{results.whole.headline}}}}, P = "
         "{{results.whole.or.p}}.", ["quoted-alone"]),
    ],
)  # fmt: skip
def test_what_quoted_alone_does_not_read_is_pinned(
    project: Path, added: dict, paragraph: str, said: list[str]
) -> None:
    """Known gaps (#267): G2 reads which bindings share a sentence, so a second level of an
    interval, an emitted table, a caption and a key declared `same_as` the estimate are each
    read as they stand. A change here is a change to what DESIGN.md says of them."""
    _with_whole(project, paragraph, {"secondary": {"method": "holm"}})
    fragment = project / "results" / "02_whole.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    for field, entries in added.items():
        document.setdefault(field, {}).update(entries)
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    assert _whole_said(project) == [(code, "warn") for code in said]


@pytest.mark.parametrize(
    "fields",
    [
        {"over": "whole.cohort.n"},
        {"family": "secondary"},
        {"of": "whole.female.n", "over": "whole.cohort.n", "family": "secondary"},
    ],
)
def test_a_fragment_written_by_hand_is_held_to_what_the_emitters_refuse(
    project: Path, fields: dict
) -> None:
    """#267: the emitters refuse a denominator with no numerator, a family with no estimate,
    and a share in a family of p values; the schema did not, so a fragment written by hand
    skipped G2's and G8's checks of them."""
    from manuscript_guard.contracts import load_namespace

    _with_whole(project, "", {"secondary": {"method": "holm"}})
    fragment = project / "results" / "02_whole.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["whole.extra"] = {"value": 0.5, "display": "0.50", **fields}
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    projekt, _ = load_project(project)
    _namespace, _results, _literature, report = load_namespace(projekt)
    assert any(f.path and f.path.name == "02_whole.json" for f in report.failures)


def test_a_family_of_p_values_with_no_correction_is_a_warning(project: Path) -> None:
    _with_whole(project, f"The ratio was {_ESTIMATE}.")
    assert _whole_said(project) == [("family-uncorrected", "warn")]


def test_none_is_a_correction_with_its_reason(project: Path) -> None:
    from manuscript_guard.contracts import load_namespace

    _with_whole(project, f"The ratio was {_ESTIMATE}.", {"secondary": {"method": "none"}})
    projekt, _ = load_project(project)
    _namespace, _results, _literature, report = load_namespace(projekt)
    assert any(f.path and f.path.name == "02_whole.json" for f in report.failures)
    _with_whole(
        project, "", {"secondary": {"method": "none", "reason": "exploratory, as stated"}}
    )
    assert _whole_said(project) == []


@pytest.mark.parametrize(
    "slot",
    [
        "n = XXXX patients",
        "[TO BE COMPLETED]",
        "[CLAIM NEEDS EVIDENCE]",
        "[PLACEHOLDER - VERIFY]",
        "[Repository]",
        "[DOI/accession]",
        "[citation needed]",
        "[describe the cohort]",
        "Lorem ipsum dolor sit amet",
        "FIXME",
        "TKTK",
        "fill in later.",
        "This section is a template.",
        "Discussion prompt: what else?",
        "dated 2025-XX-XX",
        "INSERT_SOURCE_URL_30",
        # Round 1 of #262: an instruction cut by a hard wrap, and one before a colon.
        "approved by [insert the name of the\nethics committee]",
        "[insert number]: 2024",
        "[CITATION NEEDED]",
        # Round 2 of #262: a count of thousands, an instruction marked for Word, and filler
        # before a list item, which main or round 1 caught.
        "1,XXX reports",
        "[insert the date]{.mark}",
        "- Dose: fill in later\n- Route: oral",
    ],
)
def test_a_placeholder_in_the_manuscript_fails(project: Path, slot: str) -> None:
    """Item 10.6: `XXX` was read only whole, so `XXXX` passed, and a slot in capitals, a
    thing to supply in brackets, filler text and an instruction to the writer passed too."""
    _with_paragraph(project, f"The cohort was {slot} as planned.")
    said = _placeholders(_g6(project))
    assert [severity for severity, _ in said] == ["fail"], said


@pytest.mark.parametrize(
    "prose",
    [
        "The karyotype was 47,XXX in one patient.",
        "Women with XXX syndrome were not excluded.",
        "The code is in a [repository](https://example.org/code).",
        "As the review put it [Add-on therapy in epilepsy] (in Spanish).",
        "Drugs that replace later lines of therapy were counted.",
        "TK inhibitors were the reference group.",
        # Round 1 of #262: an abbreviation nested in parentheses is in brackets and capitals,
        # a hard wrap is no end of a phrase, and a paper on teaching has discussion prompts.
        "Cases of SJS or TEN [SJS/TEN] were counted.",
        "Terms were coded (system organ class/preferred term [SOC/PT]).",
        "Drugs that replace later\nlines of therapy were counted.",
        "Each case ended with discussion prompts.",
    ],
)
def test_what_looks_like_a_placeholder_and_is_prose_passes(project: Path, prose: str) -> None:
    _with_paragraph(project, prose)
    assert _placeholders(_g6(project)) == []


def test_a_placeholder_drawn_in_a_figure_fails(project: Path) -> None:
    """A "TBD" in a figure reached the document: G6 read only the manuscript."""
    figure = project / "figures" / "forest.svg"
    text = figure.read_text(encoding="utf-8")
    figure.write_text(text.replace("</svg>", "<text>Panel TBD</text></svg>", 1), encoding="utf-8")
    report = _g6(project)
    said = [f for f in report.findings if f.code == "model-artefact"]
    assert [(f.severity, f.path.name) for f in said] == [("fail", "forest.svg")]
    assert "the text of forest.svg" in said[0].message


def test_a_placeholder_in_a_table_caption_fails(project: Path) -> None:
    """The caption an analysis writes for its table was read by no gate for a placeholder."""
    from dataclasses import replace

    project_, _ = load_project(project)
    _namespace, results, _literature, _report = load_namespace(project_)
    baseline = replace(results.tables["baseline"], caption="Reports by drug group. TODO units.")
    results = replace(results, tables={**results.tables, "baseline": baseline})
    said = _placeholders(_g6(project, results))
    assert len(said) == 1 and "the caption of table 'baseline'" in said[0][1], said


def _cited_entry_has(root: Path, field: str) -> None:
    bib = root / "literature" / "references.bib"
    opening = "@article{fictionalHepaticCohort2021,\n"
    text = bib.read_text(encoding="utf-8")
    bib.write_text(text.replace(opening, opening + f"  {field},\n", 1), encoding="utf-8")


def test_a_placeholder_in_a_cited_reference_fails_on_its_line(project: Path) -> None:
    """A "TBD" in a field of a cited entry is printed in the reference list."""
    _cited_entry_has(project, "number = {TBD}")
    _cited_entry_has(project, "doi = {[DOI]}")
    report = _g6(project)
    said = [f for f in report.findings if f.code == "model-artefact"]
    assert [(f.severity, f.path.name) for f in said] == [("fail", "references.bib")] * 2
    # Round 2 of #262: a slot that is the whole of a field, in brackets, is a slot.
    assert any("the doi of @fictionalHepaticCohort2021" in f.message for f in said)
    number = [f for f in said if "the number of @fictionalHepaticCohort2021" in f.message]
    lines = (project / "literature" / "references.bib").read_text(encoding="utf-8").splitlines()
    assert len(number) == 1 and "TBD" in lines[number[0].line - 1]


@pytest.mark.parametrize(
    "field",
    [
        # Capitals only outside the manuscript: "Todo" opens many a Spanish title.
        "title = {Todo sobre la farmacovigilancia}",
        "title = {Drug response in women with a 47,XXX karyotype}",
        # Round 1 of #262: titles PubMed translated into English, in brackets.
        "title = {[Your diagnosis?]}",
        "title = {[TREATMENT OF EPILEPSY WITH PHENYTOIN]}",
        # Fields no reference list prints.
        "abstract = {TODO}",
        "file = {TBD.pdf}",
    ],
)
def test_what_a_cited_reference_holds_and_is_no_placeholder_passes(
    project: Path, field: str
) -> None:
    _cited_entry_has(project, field)
    assert _placeholders(_g6(project)) == []


# ------------------------------------------- words to the reviewers, left in the manuscript


def _residue_said(root: Path, *, submission: bool) -> list[str]:
    from manuscript_guard.gates import check_writing

    project, _ = load_project(root)
    report = check_writing(project, submission=submission)
    return [f.severity for f in report.findings if f.code == "revision-residue"]


@pytest.mark.parametrize(
    "residue",
    [
        "As requested by Reviewer 2, we added a sensitivity analysis.",
        "In response to the reviewer's comment, we clarified the exposure.",
        "In the previous version of this manuscript, the cohort was larger.",
        "We have now clarified the definition of exposure.",
        "The definition is given on page 4, lines 120-125.",
        "I have shortened the Discussion to two paragraphs.",
    ],
)
def test_words_to_the_reviewers_in_the_manuscript_fail_at_submission(
    project: Path, residue: str
) -> None:
    """A revision's words to the reviewers, or a model's to its user, reached the manuscript
    and no gate read them: the artefacts G6 knew were a chat tool's markup and placeholders.
    They warn while the paper is revised and fail at submission (Basile, 2026-10-20)."""
    _with_paragraph(project, residue)
    assert _residue_said(project, submission=False) == ["warn"]
    assert _residue_said(project, submission=True) == ["fail"]


def test_words_to_the_reviewers_in_the_supplement_fail_too(project: Path) -> None:
    supplement = project / "manuscript" / "supplementary" / "appendix.md"
    supplement.parent.mkdir(exist_ok=True)
    supplement.write_text("# Appendix\n\nAs suggested by the reviewer, we added Table S9.\n",
                          encoding="utf-8")  # fmt: skip
    assert _residue_said(project, submission=True) == ["fail"]


def test_the_letter_to_the_reviewers_is_not_read_for_residue(project: Path) -> None:
    """The response is where these words belong: G6 never reads the round's file nor the
    letter `respond` writes from it, and G13 lets the letter say them."""
    reply = ("As requested by Reviewer 2, we have now clarified this in the revised "
             "manuscript (page 4, lines 120-125).")  # fmt: skip
    _round_with(project, [_point(response=reply, rebutted="No change was needed.")])
    from manuscript_guard.cli import main

    assert main(["respond", str(project)]) in (0, 1)
    assert (project / "build" / "response-to-reviewers.md").is_file()
    assert _residue_said(project, submission=True) == []
    codes_said = ("response-leak", "response-placeholder", "response-artefact")
    assert _said(_g13(project), *codes_said) == []


def test_a_placeholder_on_an_entrys_first_line_is_found_on_it(project: Path) -> None:
    """Round 1 of #262: a field written on the entry's line was put on the next entry's."""
    bib = project / "literature" / "references.bib"
    opening = "@article{fictionalHepaticCohort2021,\n"
    text = bib.read_text(encoding="utf-8")
    bib.write_text(text.replace(opening, opening[:-1] + " number = {TBD},\n", 1), encoding="utf-8")
    said = [f for f in _g6(project).findings if f.code == "model-artefact"]
    lines = bib.read_text(encoding="utf-8").splitlines()
    assert len(said) == 1 and lines[said[0].line - 1].startswith("@article{fictionalHepatic")


def test_a_placeholder_in_an_uncited_reference_says_nothing(project: Path) -> None:
    bib = project / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8") + "\n@article{uncitedDraft2024,\n  title = {TODO},\n}\n",
        encoding="utf-8",
    )
    assert _placeholders(_g6(project)) == []


@pytest.mark.parametrize(
    ("rule", "prose"),
    [
        ("chat-closer", "I hope this helps the reader."),
        ("source-disclaimer", "While specific details about the cohort are limited, it grew."),
        ("stacked-hedge", "The signal could potentially reflect stimulated reporting."),
        ("upbeat-close", "The future of pharmacovigilance lies in its ability to adapt."),
        ("text-about-text", "In this section, we will discuss the background."),
        ("user-should", "The user should add the dose here."),
    ],
)
def test_the_phrasing_the_essay_lists_is_a_warning(project: Path, rule: str, prose: str) -> None:
    """Item 10.6: phrasing the source essay lists and G6 did not read, each a warning and
    never a failure."""
    _with_paragraph(project, prose)
    report = _g6(project)
    said = [f for f in report.findings if f.message.startswith(f"{rule}:")]
    assert [(f.code, f.severity) for f in said] == [("ai-phrasing", "warn")], said
    assert _placeholders(report) == []


def test_an_em_dash_typed_as_three_hyphens_is_counted(project: Path) -> None:
    """Known gaps of #339: G6 counted the em dash itself, so a manuscript that typed it as
    `---`, which pandoc prints as one, showed it none. Two hyphens are an en dash, and a line
    of dashes is a rule or a table's."""
    import shutil

    from manuscript_guard.gates.writing import check_writing

    shutil.rmtree(project / "manuscript" / "supplementary", ignore_errors=True)
    main = project / "manuscript" / "main.md"
    sentence = "The signal---weak at first---grew over the years of reporting. "
    filler = "Reports were counted by drug and by event in each year of the study. " * 20
    rules = "\n\n---\n\n| a | b |\n|---|:---:|\n| 1 | 2 |\n\n"

    def rates(text: str) -> list[str]:
        main.write_text(f"# Discussion\n\n{text}\n", encoding="utf-8")
        report = check_writing(load_project(project)[0])
        return [f.message.split(":")[0] for f in report.findings if f.code == "ai-cadence"]

    assert "em-dash" in rates(sentence * 4 + filler)
    assert "em-dash" not in rates(sentence.replace("---", "--") * 4 + filler)
    assert "em-dash" not in rates(filler + rules * 6)
    # Round 1 of #352: nor inline code, printed as typed, nor a table's "not applicable".
    assert "em-dash" not in rates(filler + "Records were split on the `---` line. " * 5)
    assert "em-dash" not in rates(filler + "\n\n" + "| Drug A | --- |\n" * 20)


# ------------------------------------------------- the environment the results were made in


def _rerun_with(root: Path, files: dict[str, str]) -> None:
    from conftest import run_analysis

    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    run_analysis(root)


def _environment_said(root: Path) -> list[tuple[str, str]]:
    return [
        (f.severity, f.message)
        for f in gate_report(root).findings
        if f.code == "environment-changed"
    ]


def test_a_lockfile_changed_since_the_results_is_said(project: Path) -> None:
    """Item 18: the emitter recorded no package environment, so a requirements file pinning
    another version after the results were written went unsaid."""
    _rerun_with(project, {"requirements.txt": "pandas==2.2.2\n"})
    assert _environment_said(project) == []
    (project / "requirements.txt").write_text("pandas==2.1.0\n", encoding="utf-8")
    said = _environment_said(project)
    assert said and all(severity == "warn" for severity, _ in said)
    assert all("requirements.txt changed since these results" in m for _, m in said)


@pytest.mark.parametrize("name", ["requirements.txt", "renv.lock", "uv.lock"])
def test_a_lockfile_checked_out_with_other_line_endings_is_unchanged(
    project: Path, name: str
) -> None:
    """Round 1 of #265: git checks a lockfile out with CRLF on Windows and LF elsewhere, and
    a byte digest read that as a change."""
    (project / name).write_bytes(b"pandas==2.2.2\r\nnumpy==2.0.0\r\n")
    _rerun_with(project, {})
    (project / name).write_bytes(b"pandas==2.2.2\nnumpy==2.0.0\n")
    assert _environment_said(project) == []


def test_a_lockfile_gone_or_new_since_the_results_is_said(project: Path) -> None:
    _rerun_with(project, {"requirements.txt": "pandas==2.2.2\n"})
    (project / "requirements.txt").unlink()
    (project / "renv.lock").write_text("{}\n", encoding="utf-8")
    said = " ".join(m for _, m in _environment_said(project))
    assert "requirements.txt pinned the packages" in said and "is gone" in said
    assert "renv.lock was not there when these results were written" in said


def test_a_fragment_written_before_the_environment_was_recorded_says_nothing(
    project: Path,
) -> None:
    from manuscript_guard.emit import write_digest

    (project / "renv.lock").write_text("{}\n", encoding="utf-8")
    for fragment in (project / "results").glob("*.json"):
        document = json.loads(fragment.read_text(encoding="utf-8"))
        document["provenance"].pop("environment", None)
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)
    assert _environment_said(project) == []


# ------------------------------------------------- a pointer names what the document carries
# "In step 1204 reports were excluded, as Table 4000 and Figure 9 show." passed G2 whole: each
# number followed a pointer word. The example itself called its two tables "Table 2" and
# "Table 3", after its first had moved to the supplement.


def _pointer_findings(root: Path) -> list[tuple[str, str]]:
    return [
        (f.code, f.message)
        for f in gate_report(root).findings
        if f.code in ("pointer-to-nothing", "cited-out-of-order", "display-not-cited")
    ]


def _add_to_results(root: Path, sentence: str) -> None:
    main = main_md(root)
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("Baseline characteristics are shown in Table 1.",
                     f"Baseline characteristics are shown in Table 1. {sentence}", 1),
        encoding="utf-8",
    )  # fmt: skip


def test_the_example_points_at_what_it_carries(project: Path) -> None:
    assert _pointer_findings(project) == []


@pytest.mark.parametrize(
    ("sentence", "names"),
    [
        ("As Table 4000 shows.", "table 4000"),
        ("As Figure 9 shows.", "figure 9"),
        ("As Table S5 shows.", "table S5"),
        ("As Supplemental Table 3 shows.", "table S3"),
        ("As eTable 4 shows.", "table S4"),
        ("As Tables 1 and 3 show.", "table 3"),
        ("As Figures 1\N{EN DASH}2 show.", "figure 2"),
    ],
)
def test_a_pointer_to_what_the_document_does_not_carry_is_said(
    project: Path, sentence: str, names: str
) -> None:
    _add_to_results(project, sentence)
    said = _pointer_findings(project)
    assert [code for code, _ in said] == ["pointer-to-nothing"], said
    assert f"points at {names}," in said[0][1], said


def _all_pointer_findings(root: Path) -> list[tuple[str, str, str]]:
    from manuscript_guard.contracts import load_project
    from manuscript_guard.gates.pointers import check_pointers

    report = check_pointers(load_project(root)[0])
    return [(f.code, f.severity, f.message) for f in report.findings]


@pytest.mark.parametrize(
    ("change", "sentence", "unchecked"),
    [
        # round 1 of #256: figures sent to the journal as files of their own
        (("{{figure.forest}}", ""), "As Figure 1 shows.", "the main text's figures"),
        # a table written by hand, in a form the first version did not count
        (("{{table.baseline}}", "| A | B |\n|:--|--:|\n| x | y |"), "As Table 3 shows.",
         "the main text's tables"),
        # an image placed by hand
        (("{{figure.forest}}", "![The forest plot](forest.png)"), "As Figure 2 shows.",
         "the main text's figures"),
        # the supplement places no figure by its binding
        (None, "As Supplementary Figure 1 shows.", "the supplement's figures"),
    ],
)  # fmt: skip
def test_a_kind_placed_some_other_way_is_not_checked_and_says_so(
    project: Path, change: tuple[str, str] | None, sentence: str, unchecked: str
) -> None:
    """Exact counts only, Basile's choice on 2026-10-15: what is not placed by its binding
    cannot be counted, so its pointers are not held to a count, and a note says so."""
    if change:
        main = main_md(project)
        main.write_text(main.read_text(encoding="utf-8").replace(*change, 1), encoding="utf-8")
    _add_to_results(project, sentence)
    said = _all_pointer_findings(project)
    assert not [s for s in said if s[0] != "pointers-unchecked"], said
    assert any(code == "pointers-unchecked" and severity == "info" and unchecked in message
               for code, severity, message in said), said  # fmt: skip


@pytest.mark.parametrize(
    "sentence",
    [
        "As Supplemental Table 1 shows.",
        "As Extended Data Fig. 1 shows.",
        "As Table 1 in the Supplement shows.",
        "As Tables S1\N{EN DASH}2 show.",
        "As eFigure 1 shows.",
    ],
)
def test_a_pointer_to_the_supplement_is_no_citation_of_the_main_text(
    project: Path, sentence: str
) -> None:
    """Round 1 of #256: read as the main text's, "Supplemental Table 1" before Table 1's
    first citation made the main text's tables cited out of order."""
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace("# Results\n", f"# Results\n\n{sentence}\n", 1), "utf-8")
    assert not [s for s in _all_pointer_findings(project) if s[0] == "cited-out-of-order"]


def test_a_pointer_that_ends_a_wrapped_line_is_a_citation(project: Path) -> None:
    """Round 2 of #256: "shown in\nTable 1." was taken for a caption, and Table 1 for a
    table cited nowhere."""
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("are shown in Table 1.", "are shown in\nTable 1.", 1),
        encoding="utf-8",
    )
    assert _pointer_findings(project) == []


def _declare(root: Path, line: str) -> None:
    paper = root / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8") + f"\n{line}\n", encoding="utf-8")


def test_a_figure_sent_as_a_file_is_declared_and_counted(project: Path) -> None:
    """Round 2 of #256, Basile's choice of 2026-10-15: one figure bound, a flow chart sent to
    the journal as a file of its own. Undeclared, "Figure 2" points at nothing; declared in
    paper.yaml, it is counted, and must be cited like any other."""
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("can reconstruct it.", "can reconstruct it. The flow is in Figure 2.", 1),
        encoding="utf-8",
    )
    assert [code for code, _ in _pointer_findings(project)] == ["pointer-to-nothing"]
    _declare(project, "displays: {figures_as_files: 1}")
    assert _pointer_findings(project) == []
    main.write_text(text, encoding="utf-8")
    said = _pointer_findings(project)
    assert [code for code, _ in said] == ["display-not-cited"], said
    assert said[0][1].startswith("Figure 2 ")


def test_figures_all_sent_as_files_are_checked_once_declared(project: Path) -> None:
    main = main_md(project)
    main.write_text(
        main.read_text(encoding="utf-8").replace("{{figure.forest}}", "", 1), encoding="utf-8"
    )
    _declare(project, "displays: {figures_as_files: 1}")
    assert _pointer_findings(project) == []
    _add_to_results(project, "As Figure 3 shows.")
    said = _pointer_findings(project)
    assert [code for code, _ in said] == ["pointer-to-nothing"], said
    assert "and 1 sent as files" in said[0][1]


def test_a_count_of_displays_sent_as_files_is_a_whole_number(project: Path) -> None:
    _declare(project, "displays: {figures_as_files: -1}")
    assert "schema-violation" in codes(gate_report(project))


def test_a_caption_typed_above_a_table_is_no_citation_of_it(project: Path) -> None:
    main = main_md(project)
    text = main.read_text(encoding="utf-8").replace("in Table 2, so", "below, so", 1)
    main.write_text(
        text.replace("{{table.two_by_two}}", "**Table 2.** Counts\n\n{{table.two_by_two}}", 1),
        encoding="utf-8",
    )
    said = _pointer_findings(project)
    assert [code for code, _ in said] == ["display-not-cited"], said


def test_a_pointer_to_nothing_fails_from_the_internal_review(project: Path) -> None:
    """Basile's choice on 2026-10-14: while the draft is written its tables move."""
    from manuscript_guard.cli import _run_gates

    _add_to_results(project, "As Table 9 shows.")
    drafting, *_ = _run_gates(project, stage="drafting")
    assert [f.severity for f in drafting.findings if f.code == "pointer-to-nothing"] == ["info"]
    reviewing, *_ = _run_gates(project, stage="internal-review")
    assert "pointer-to-nothing" in codes(reviewing)


def test_tables_first_cited_out_of_order_are_said(project: Path) -> None:
    _add_to_results(project, "Table 2 has the counts.")
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("Baseline characteristics are shown in Table 1. Table 2 has the counts.",
                     "Table 2 has the counts. Baseline characteristics are shown in Table 1.", 1),
        encoding="utf-8",
    )  # fmt: skip
    assert [code for code, _ in _pointer_findings(project)] == ["cited-out-of-order"]


def test_a_table_cited_nowhere_is_said(project: Path) -> None:
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace("in Table 2, so", "below, so", 1), encoding="utf-8")
    said = _pointer_findings(project)
    assert [code for code, _ in said] == ["display-not-cited"], said
    assert said[0][1].startswith("Table 2 ")


@pytest.mark.parametrize(
    "sentence",
    ["In step 1204 reports were excluded.", "Box 47 lists the reports.",
     "Panel 312 shows the reports.", "Item 125 lists them."],
)  # fmt: skip
def test_a_count_after_a_word_with_nothing_to_check_it_against_is_a_count(
    project: Path, sentence: str
) -> None:
    _add_to_results(project, sentence)
    assert "unclassified-number" in codes(gate_report(project))


def test_a_count_after_a_list_of_tables_is_a_count(project: Path) -> None:
    """Round 2 of #256: after "and" a comma ends the list, so "In Tables 1 and 2, 30
    patients" is two pointers and a count, not a pointer to Table 30 and a 30 let through."""
    _add_to_results(project, "In Tables 1 and 2, 30 patients were excluded.")
    assert "unclassified-number" in codes(gate_report(project))
    assert _pointer_findings(project) == []


def test_a_count_after_a_range_of_tables_read_as_a_table_is_pinned() -> None:
    """Known gaps (round 3 of #256): after a range a comma goes on with the list, as it must
    for "Tables S1-S3, S5", so "In Tables 1-3, 30 patients" reads Table 30."""
    from manuscript_guard.gates.pointers import pointers_in

    said = pointers_in("In Tables 1-3, 30 patients were excluded.", Path("x"))
    assert [p.number for p in said] == [1, 2, 3, 30]
    said = pointers_in("Tables S1-S3, S5 list the codes.", Path("x"))
    assert [p.number for p in said] == [1, 2, 3, 5]


def test_a_serial_comma_ends_no_list_of_tables(project: Path) -> None:
    """Round 3 of #256: "Tables 1, 2, and 3" stopped the pointer at 2, and the 3 was taken
    for a cross-reference no gate held to a table, in a paper that places two."""
    from manuscript_guard.gates.pointers import pointers_in

    said = pointers_in("In Tables 1, 2, and 3, 30 patients were excluded.", Path("x"))
    assert [p.number for p in said] == [1, 2, 3]
    _add_to_results(project, "Tables 1, 2, and 3 show the reports.")
    assert [code for code, _ in _pointer_findings(project)] == ["pointer-to-nothing"]


def test_a_list_of_tables_is_one_pointer(project: Path) -> None:
    """"Tables 1 and 2 show" left its 2 bound to nothing."""
    _add_to_results(project, "Tables 1 and 2 show the reports.")
    report = gate_report(project)
    assert "unclassified-number" not in codes(report)
    assert _pointer_findings(project) == []


# ------------------------------------------------- the plan when the results were first known


def _plan_said(root: Path) -> list[tuple[str, str]]:
    from manuscript_guard.gates import check_design

    project, _ = load_project(root)
    return [
        (f.code, f.severity)
        for f in check_design(project).findings
        if f.code.startswith("plan-") and f.code not in ("plan-complete",)
    ]


def _plan_edited(root: Path, old: str, new: str) -> None:
    plan = root / "design" / "plan.md"
    text = plan.read_text(encoding="utf-8")
    assert old in text, old
    plan.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_the_plan_is_kept_as_it_stood_when_the_first_results_were_written(
    project: Path,
) -> None:
    """Item 26: nothing recorded whether the plan was rewritten after the results."""
    frozen = project / "design" / "plan.frozen.yaml"
    record = yaml.safe_load(frozen.read_text(encoding="utf-8"))
    assert record["plan"] == (project / "design" / "plan.md").read_text(encoding="utf-8")
    assert _plan_said(project) == []


def test_a_plan_changed_after_the_results_with_nothing_said_is_a_warning(project: Path) -> None:
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome, chosen later.\n")
    assert _plan_said(project) == [("plan-changed-after-results", "warn")]


def test_a_plan_changed_with_its_deviation_said_passes(project: Path) -> None:
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome, chosen later.\n")
    _plan_edited(project, "## Deviations from the plan",
                 "## Deviations from the plan\n\n2026-10-15: a second outcome was added, "
                 "decided by the authors, before its results were known.\n")  # fmt: skip
    assert _plan_said(project) == []


def test_a_plan_rewrapped_says_what_it_said(project: Path) -> None:
    plan = project / "design" / "plan.md"
    text = plan.read_text(encoding="utf-8")
    plan.write_text(text.replace("\n\n", "\n\n\n").replace(". ", ".\n"), encoding="utf-8")
    assert _plan_said(project) == []


def test_a_plan_kept_with_its_byte_order_mark_and_rewrapped_says_what_it_said(
    project: Path,
) -> None:
    """Round 1 of #271: the emitters kept a plan's byte-order mark, which G12 strips when it
    reads the plan, and a plan re-wrapped then no longer read as the copy."""
    frozen = project / "design" / "plan.frozen.yaml"
    record = json.loads(frozen.read_text(encoding="utf-8"))
    record["plan"] = "﻿" + record["plan"]
    frozen.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    plan = project / "design" / "plan.md"
    text = plan.read_text(encoding="utf-8")
    plan.write_bytes(("﻿" + text.replace(". ", ".\n")).encode("utf-8"))
    assert _plan_said(project) == []


def test_the_kept_plan_is_never_written_again(project: Path) -> None:
    from conftest import run_analysis

    frozen = project / "design" / "plan.frozen.yaml"
    kept = frozen.read_bytes()
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome, chosen later.\n")
    run_analysis(project)
    assert frozen.read_bytes() == kept
    assert _plan_said(project) == [("plan-changed-after-results", "warn")]


def test_results_with_no_kept_plan_are_a_note(project: Path) -> None:
    (project / "design" / "plan.frozen.yaml").unlink()
    assert _plan_said(project) == [("plan-not-frozen", "info")]


def test_the_example_keeps_its_plan_as_a_project_does() -> None:
    """The example commits its results, so it commits the plan kept when they were first
    written. Without it, `check` there gave the note for results older than the emitters'
    copy, and each run of the analysis left a file git neither tracked nor ignored."""
    from conftest import EXAMPLE

    assert _plan_said(EXAMPLE) == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_the_example_s_loop_leaves_nothing_git_does_not_know(tmp_path: Path) -> None:
    """Its analysis and `check`, run in a checkout of the example, write only files the
    repository tracks or ignores. A file that is neither goes in with the next `git add -A`;
    the plan the emitter keeps was one until the example committed its own."""
    import subprocess

    from conftest import EXAMPLE, REPO, run_analysis

    from manuscript_guard.cli import main

    def git(*args: str, given: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=REPO,
                              input=given, capture_output=True, text=True, encoding="utf-8",
                              timeout=60)  # fmt: skip

    listed = git("ls-files", "-z", "example")
    if listed.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = {name.removeprefix("example/") for name in listed.stdout.split("\0") if name}
    root = tmp_path / "example"
    for name in tracked:
        if (EXAMPLE / name).is_file():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(EXAMPLE / name, root / name)
    run_analysis(root)
    assert main(["check", str(root)]) in (0, 1)  # whether it passes is held elsewhere
    written = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in tracked
    )
    ignored = git("check-ignore", "--stdin", given="".join(f"example/{n}\n" for n in written))
    # 0: some are ignored, 1: none are. Anything else is git failing, not an answer.
    assert ignored.returncode in (0, 1), ignored.stderr
    unknown = set(written) - {name.removeprefix("example/") for name in ignored.stdout.splitlines()}
    assert not unknown, f"written, and neither tracked nor ignored: {sorted(unknown)}"


# ------------------------------------------------- the results the plan promised


def _planned_said(root: Path, stage: str = "drafting", **unquoted: bool) -> list[tuple[str, str]]:
    """G12's word on the plan's Planned results at a stage, with the values named emitted
    with quoted=False: each finding's code and the line it points at."""
    from manuscript_guard.gates import check_design

    if unquoted:
        fragment = next((root / "results").glob("*.json"))
        document = json.loads(fragment.read_text(encoding="utf-8"))
        for key in unquoted:
            document["values"][key.replace("__", ".")]["quoted"] = False
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)
    project, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(project)
    text = (root / "design" / "plan.md").read_text(encoding="utf-8").splitlines()
    return [(f.code, text[f.line - 1].strip() if f.line else "")
            for f in check_design(project, results, stage).findings
            if f.code.startswith("planned-")]  # fmt: skip


def test_a_result_the_plan_promised_and_the_analysis_never_emitted_is_a_warning(
    project: Path,
) -> None:
    """Item 37: G2 said when the analysis emitted a value nothing quoted, and nothing said
    when the plan promised a result the analysis never emitted."""
    from manuscript_guard.gates import check_design

    promised = "- `death.n_cases`: deaths among the cases"
    _plan_edited(project, "- `case.pct_serious`", f"{promised}\n- `case.pct_serious`")
    assert _planned_said(project) == [("planned-result-missing", promised)]
    assert _planned_said(project, "design") == []
    assert not [f for f in check_design(load_project(project)[0]).findings
                if f.code.startswith("planned-")]  # fmt: skip


def test_a_planned_result_emitted_unquoted_is_a_warning(project: Path) -> None:
    assert _planned_said(project) == []
    said = _planned_said(project, case__pct_serious=True)
    assert said == [("planned-result-unquoted", "- `case.pct_serious`: the proportion of the "
                     "cases that were serious")]  # fmt: skip


def test_a_planned_group_counts_while_one_of_its_keys_is_quoted(project: Path) -> None:
    assert _planned_said(project, ror__ci90_low=True, ror__ci90_high=True) == []
    said = _planned_said(project, ror__point=True, ror__ci_low=True, ror__ci_high=True)
    assert said == [("planned-result-unquoted", "- `ror.*`: the reporting odds ratio and its "
                     "95% interval")]  # fmt: skip


def test_a_planned_result_the_deviations_name_passes(project: Path) -> None:
    _plan_edited(project, "- `case.pct_serious`",
                 "- `death.n_cases`: deaths among the cases\n- `case.pct_serious`")  # fmt: skip
    _plan_edited(project, "No analysis was added",
                 "3. Deaths, `death.n_cases`, were not reported: the generator writes none.\n\n"
                 "No analysis was added")  # fmt: skip
    assert _planned_said(project) == []
    _plan_edited(project, "Deaths, `death.n_cases`, were", "Deaths, `death.n_cases_all`, were")
    assert [code for code, _line in _planned_said(project)] == ["planned-result-missing"]


def test_a_planned_key_with_no_dot_is_read_in_its_bound_form(project: Path) -> None:
    """Round 1 of #305: `results.dose` was read as the key `results.dose`, since `dose` has
    no dot, and a promise kept was said to be broken."""
    from manuscript_guard.gates import check_design

    promised = "- `results.dose`: the dose"
    _plan_edited(project, "- `case.pct_serious`", f"{promised}\n- `case.pct_serious`")
    assert _planned_said(project) == [("planned-result-missing", promised)]
    # Round 2 of #305: the word "dose" in the Deviations stood the key down.
    _plan_edited(project, "No analysis was added", "The dose groups were analysed as planned.\n\n"
                 "No analysis was added")  # fmt: skip
    assert _planned_said(project) == [("planned-result-missing", promised)]
    project_, _ = load_project(project)
    _namespace, results, _literature, _ = load_namespace(project_)
    [said] = [f for f in check_design(project_, results, "drafting").findings
              if f.code == "planned-result-missing"]  # fmt: skip
    assert "lists results.dose among" in said.message and "naming results.dose" in said.hint
    fragment = next((project / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["dose"] = {"value": 5, "display": "5"}
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    assert _planned_said(project) == []


def test_a_planned_results_section_that_names_no_key_is_a_warning(project: Path) -> None:
    plan = project / "design" / "plan.md"
    text = plan.read_text(encoding="utf-8")
    start, end = text.index("## Planned results\n"), text.index("## Sample size")
    words = "## Planned results\n\nThe cases, the ratio and the share that were serious.\n\n"
    plan.write_text(text[:start] + words + text[end:], encoding="utf-8")
    assert _planned_said(project) == [("planned-results-unkeyed", "")]


def test_a_deviations_heading_that_names_the_planned_results_is_not_the_list(
    project: Path,
) -> None:
    """Round 1 of #305: "Changes to the planned results" was read as the plan's list, named
    no key, and the plan was said to list its results by none."""
    _plan_edited(project, "## Deviations from the plan", "## Changes to the planned results")
    assert _planned_said(project) == []
    plan = project / "design" / "plan.md"
    text = plan.read_text(encoding="utf-8")
    start, end = text.index("## Planned results\n"), text.index("## Sample size")
    plan.write_text(text[:start] + text[end:], encoding="utf-8")
    assert _planned_said(project) == []
    # Round 1 of #351: where the planned results come first, the heading is the list's.
    words = "## Planned results and amendments\n\nThe cases and the ratio.\n\n"
    plan.write_text(text[:start] + words + text[end:], encoding="utf-8")
    assert _planned_said(project) == [("planned-results-unkeyed", "")]


def test_a_planned_group_of_tables_or_models_is_looked_for_among_them(project: Path) -> None:
    """Round 1 of #305: `table.*` was looked for among the values, found nothing, and the
    tables the analysis emitted were said to be missing."""
    groups = "- `table.*`: the tables\n- `model.*`: the models\n- `case.pct_serious`"
    _plan_edited(project, "- `case.pct_serious`", groups)
    assert _planned_said(project) == []
    _plan_edited(project, "- `model.*`: the models", "- `model.crude.*`: the crude models")
    assert _planned_said(project) == [("planned-result-missing",
                                       "- `model.crude.*`: the crude models")]  # fmt: skip


# ------------------------------------------------- the data dictionary

#: The example's report file, described as a dictionary describes it.
_EXAMPLE_DICTIONARY = """\
schema: manuscript-guard/data-dictionary/1
code_lists:
  yes_no:
    - {code: 1, label: "Yes"}
    - {code: 0, label: "No"}
variables:
  - name: report_id
    label: Report
    definition: The report's identifier in the database.
    type: identifier
    reason: the record's own identifier
  - name: serious
    label: Serious
    definition: The report was classed as serious.
    type: binary
    code_list: yes_no
    reason: the proportion of the cases that were serious
"""


def _dictionary_failures(root: Path, text: str, stage: str) -> list[str]:
    """What the whole check fails on at a stage, with this dictionary in the example."""
    from manuscript_guard.cli import _run_gates

    path = root / "design" / "data_dictionary.yaml"
    path.write_bytes(text.encode("utf-8"))
    report, _project, _chosen, _deferred = _run_gates(root, stage=stage)
    return [f"{f.gate} {f.code}" for f in report.failures]


@pytest.mark.parametrize("stage", ["design", "submission"])
def test_a_dictionary_that_reads_leaves_the_example_as_it_was(project: Path, stage: str) -> None:
    assert _dictionary_failures(project, _EXAMPLE_DICTIONARY, stage) == []


@pytest.mark.parametrize(
    "old, new",
    [
        ("    code_list: yes_no", "    code_list: yes_or_no"),
        ("{code: 0, label: \"No\"}", "{code: 0, label: No}"),
        ("{code: 1, label: \"Yes\"}", "{code: 01, label: \"Yes\"}"),
        ("  - name: serious", "  - name: report_id"),
        ("    type: binary", "    type: yes-no"),
    ],
)
@pytest.mark.parametrize("stage", ["design", "submission"])
def test_a_dictionary_that_does_not_read_fails_the_check_at_every_stage(
    project: Path, stage: str, old: str, new: str
) -> None:
    """A dictionary read as written would hand the data checks another variable's codes, or
    codes the data never hold: it fails, as a malformed contract does, where everything
    else G12 says warns."""
    assert old in _EXAMPLE_DICTIONARY
    failed = _dictionary_failures(project, _EXAMPLE_DICTIONARY.replace(old, new), stage)
    assert failed and set(failed) == {"G12 dictionary-invalid"}, failed


def _collection_said(root: Path, text: str, stage: str) -> tuple[list[str], list[str]]:
    """What the whole check fails on and what G12 warns of the collection plan, at a stage."""
    from manuscript_guard.cli import _run_gates

    (root / "design" / "data_dictionary.yaml").write_bytes(text.encode("utf-8"))
    report, _project, _chosen, _deferred = _run_gates(root, stage=stage)
    warned = [f.code for f in report.warnings
              if f.code.startswith(("plan-variable", "dictionary-"))]  # fmt: skip
    return [f.code for f in report.failures], warned


@pytest.mark.parametrize("stage", ["design", "submission"])
def test_a_variable_the_plan_uses_and_nobody_collects_is_warned_of(
    project: Path, stage: str
) -> None:
    """A covariate the analysis adjusts for and the dictionary does not define is found
    when the data come in: G12 says so while the plan is written, and warns at every stage."""
    _plan_edited(project, "No stratification by", "Adjusted for `age_years`. No stratification by")
    failed, warned = _collection_said(project, _EXAMPLE_DICTIONARY, stage)
    assert failed == [] and warned == ["plan-variable-undefined"]


@pytest.mark.parametrize("stage", ["design", "submission"])
def test_an_entry_nothing_needs_is_warned_of(project: Path, stage: str) -> None:
    unneeded = _EXAMPLE_DICTIONARY.replace(
        "    reason: the proportion of the cases that were serious\n", ""
    )
    failed, warned = _collection_said(project, unneeded, stage)
    assert failed == [] and warned == ["dictionary-entry-unused"]
    _plan_edited(project, "Seriousness is reported", "Seriousness, `serious`, is reported")
    assert _collection_said(project, unneeded, stage) == ([], [])


# ------------------------------------------------- the unit of analysis


def _model_card_has(root: Path, **fields) -> None:
    """Give the example's model card these fields, and sign the fragment again."""
    for fragment in (root / "results").glob("*.json"):
        document = json.loads(fragment.read_text(encoding="utf-8"))
        for card in (document.get("models") or {}).values():
            card.update(fields)
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)


def _unit_said(root: Path) -> list[tuple[str, str]]:
    project, _ = load_project(root)
    _namespace, results, _literature, _report = load_namespace(project)
    assert results.models, "the example fits a model"
    said = check_models(project, results).findings
    return [(f.code, f.severity) for f in said if f.code == "unit-rows-independent"]


def _models_said(root: Path, code: str) -> list[str]:
    project, _ = load_project(root)
    _namespace, results, _literature, report = load_namespace(project)
    assert "adjusted" in results.models, report.render()
    return [f.message for f in check_models(project, results).findings if f.code == code]


def _given(card: dict, fields: dict) -> dict:
    """The card with these fields, a field given None taken out."""
    return {key: value for key, value in {**card, **fields}.items() if value is not None}


def _crude_beside_adjusted(root: Path, crude: dict, adjusted: dict) -> None:
    """The example's adjusted model, and a crude one of the same outcome with only the
    exposure, each card given the fields passed."""
    for fragment in (root / "results").glob("*.json"):
        document = json.loads(fragment.read_text(encoding="utf-8"))
        card = document["models"]["adjusted"]
        document["models"]["crude"] = _given(card, {
            "name": "Crude model", "formula": "hepatic ~ exposed",
            "terms": [t for t in card["terms"] if t["term"] == "exposed"], "parameters": 1,
            **crude,
        })  # fmt: skip
        document["models"]["adjusted"] = _given(card, adjusted)
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)


def _adjusted_has(root: Path, **fields) -> None:
    _crude_beside_adjusted(root, {}, fields)
    for fragment in (root / "results").glob("*.json"):
        document = json.loads(fragment.read_text(encoding="utf-8"))
        del document["models"]["crude"]
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)


_ROWS = {name: hashlib.sha256(name.encode("utf-8")).hexdigest() for name in ("all", "some")}


@pytest.mark.parametrize(
    ("crude", "adjusted", "said"),
    [
        # A stratum fitted without its stratifier is these two cards as well, and is warned
        # of as a crude model on other rows: Known gaps.
        ({"rows_sha256": _ROWS["all"]}, {"rows_sha256": _ROWS["some"], "n_used": 3800}, 1),
        # Equal counts and different rows: the digest tells them apart.
        ({"rows_sha256": _ROWS["all"]}, {"rows_sha256": _ROWS["some"]}, 1),
        ({"rows_sha256": _ROWS["all"]}, {"rows_sha256": _ROWS["all"]}, 0),
        # A card that does not say which rows it used is not compared.
        ({"rows_sha256": None}, {"rows_sha256": _ROWS["some"]}, 0),
        # The same terms on other rows are a subgroup, by design.
        ({"rows_sha256": _ROWS["all"], "terms": "adjusted's"}, {"rows_sha256": _ROWS["some"]}, 0),
        # Round 1 of #289: another outcome of the same variable, `I(score > 10)` beside
        # `I(score > 5)`, is not the crude model of this one; the same one spaced otherwise is.
        ({"rows_sha256": _ROWS["all"], "outcome": "I(hepatic > 1)"},
         {"rows_sha256": _ROWS["some"]}, 0),
        ({"rows_sha256": _ROWS["all"], "outcome": " spaced "}, {"rows_sha256": _ROWS["some"]}, 1),
    ],
    ids=["fewer rows", "as many rows", "the same rows", "rows unknown", "a subgroup",
         "another outcome", "the outcome spaced"],
)  # fmt: skip
def test_a_crude_and_an_adjusted_model_on_different_rows_are_a_warning(
    project: Path, crude: dict, adjusted: dict, said: int
) -> None:
    """Item 36: a covariate's missing values drop rows from the adjusted model only, and
    the crude and adjusted estimates were compared as if one adjustment parted them."""
    card = json.loads(next((project / "results").glob("*.json"))
                      .read_text(encoding="utf-8"))["models"]["adjusted"]  # fmt: skip
    if crude.get("terms") == "adjusted's":
        crude = {**crude, "terms": card["terms"]}
    if crude.get("outcome") == " spaced ":
        spaced = " " + card["outcome"]["expression"].replace("", " ").strip() + " "
        crude = {**crude, "outcome": {**card["outcome"], "expression": spaced}}
    elif isinstance(crude.get("outcome"), str):
        crude = {**crude, "outcome": {**card["outcome"], "expression": crude["outcome"]}}
    _crude_beside_adjusted(project, crude, adjusted)
    found = _models_said(project, "models-on-different-rows")
    assert len(found) == said, found
    assert all(message.startswith("model 'adjusted': its terms include all of 'crude'")
               for message in found)  # fmt: skip


_POISSON = {"language": "Python", "package": "statsmodels", "class": "GLM",
            "family": "Poisson", "link": "Log"}  # fmt: skip


@pytest.mark.parametrize(
    ("fields", "said"),
    [
        ({"engine": _POISSON, "covariance": "nonrobust"}, 1),
        ({"engine": _POISSON, "covariance": "model-based"}, 1),
        ({"engine": _POISSON, "covariance": "HC0"}, 0),
        ({"engine": _POISSON, "covariance": None}, 0),
        # Round 1 of #289: with a person-time offset the model estimates a rate ratio, and
        # its own variance is the right one.
        ({"engine": _POISSON, "covariance": "nonrobust", "offset": True}, 0),
        ({"covariance": "nonrobust"}, 0),
    ],
    ids=["nonrobust", "model-based", "robust", "not said", "rate", "logistic"],
)
def test_a_poisson_model_of_a_binary_outcome_wants_a_robust_variance(
    project: Path, fields: dict, said: int
) -> None:
    """Item 36: a risk ratio from Poisson regression of a binary outcome, with the model's
    own standard errors, passed; they overstate its error."""
    _adjusted_has(project, **fields)
    assert len(_models_said(project, "poisson-binary-variance")) == said


def test_the_poisson_hint_says_what_r_can_do(project: Path) -> None:
    """Round 1 of #289: R's card always says model-based, and the hint named only the
    statsmodels remedy."""
    _adjusted_has(project, engine=_POISSON, covariance="model-based")
    loaded, _ = load_project(project)
    _namespace, results, _literature, _report = load_namespace(loaded)
    hints = [f.hint for f in check_models(loaded, results).findings
             if f.code == "poisson-binary-variance"]  # fmt: skip
    assert len(hints) == 1 and "glm(family = binomial(link = 'log'))" in hints[0]
    assert "sandwich::vcovHC" in hints[0]


def test_rows_of_one_unit_taken_as_independent_are_a_warning(project: Path) -> None:
    """Item 14: a model fitted on several rows a patient, with ordinary standard errors,
    passed."""
    _model_card_has(project, unit={"column": "patient", "units": 3}, covariance="nonrobust")
    assert _unit_said(project) == [("unit-rows-independent", "warn")]


@pytest.mark.parametrize(
    "fields",
    [
        {"unit": {"column": "patient", "units": 3}, "covariance": "cluster"},
        {"unit": {"column": "patient", "units": 3}, "covariance": "Cluster"},
        {"unit": {"column": "patient", "units": 3},
         "engine": {"language": "Python", "package": "statsmodels", "class": "MixedLM"}},
        {"unit": {"column": "patient", "units": 100000}, "covariance": "nonrobust"},
        {"covariance": "nonrobust"},
    ],
)  # fmt: skip
def test_rows_of_one_unit_accounted_for_say_nothing(project: Path, fields: dict) -> None:
    _model_card_has(project, **fields)
    assert _unit_said(project) == []


# ------------------------------------------------- a named person signs off a warning

_UNIT_WARNING = "G15/unit-rows-independent/adjusted"


def _signed_said(root: Path) -> list[tuple[str, str, str]]:
    """G15's word on the rows of one unit: its severity, its message and its hint."""
    project, _ = load_project(root)
    _namespace, results, _literature, _report = load_namespace(project)
    said = check_models(project, results).findings
    return [
        (f.severity, f.message, f.hint or "")
        for f in said
        if f.code in ("unit-rows-independent", "schema-violation")
    ]


def _roles(root: Path, roles: str) -> None:
    authors = root / "authors.yaml"
    text = re.sub(r"(?m)^roles:\n(?:  .*\n)*", "", authors.read_text(encoding="utf-8"))
    authors.write_text(text + roles, encoding="utf-8")


def test_a_warning_the_statistician_signed_is_said_with_their_name(project: Path) -> None:
    """Item 48: a G15 warning left standing was the author's to dismiss. The statistician
    authors.yaml names signs it off, bound to the model's card: it is then information that
    names them, and a refitted model wants a new sign-off."""
    from manuscript_guard.cli import main

    _model_card_has(project, unit={"column": "patient", "units": 3}, covariance="nonrobust")
    [(severity, _message, hint)] = _signed_said(project)
    assert severity == "warn"
    assert f'Blaise Sample, the statistician, signs it off with `manuscript-guard sign --as "Blaise Sample" --finding {_UNIT_WARNING}`' in hint  # noqa: E501
    assert main(["sign", str(project), "--as", "Ada Example", "--finding", _UNIT_WARNING]) == 2
    assert main(["sign", str(project), "--as", "Sample", "--finding", "G15/nothing/here"]) == 2
    assert _signed_said(project)[0][0] == "warn"

    note = "three visits a patient; the cluster fit agrees"
    signed = ["sign", str(project), "--as", "0000-0001-5109-3700", "--finding", _UNIT_WARNING]
    assert main([*signed, "--note", note]) == 0
    [(severity, message, hint)] = _signed_said(project)
    assert severity == "info"
    assert message.endswith(f"signed off by Blaise Sample, the statistician, on {time.strftime('%Y-%m-%d')}")  # noqa: E501
    assert hint == f"they said: {note}"

    _model_card_has(project, unit={"column": "patient", "units": 4})
    [(severity, _message, hint)] = _signed_said(project)
    assert severity == "warn" and "and it has changed since" in hint


def test_a_sign_off_counts_only_from_the_person_who_holds_the_role(project: Path) -> None:
    """A sign-off by someone the roles no longer name, one copied to another finding, or
    roles that name nobody or no author: the warning stands, and says what is wanted."""
    from manuscript_guard.cli import main
    from manuscript_guard.sign_offs import DIRECTORY

    _model_card_has(project, unit={"column": "patient", "units": 3}, covariance="nonrobust")
    assert main(["sign", str(project), "--as", "Sample", "--finding", _UNIT_WARNING]) == 0
    _roles(project, "roles:\n  statistician: Example\n")
    [(severity, _message, hint)] = _signed_said(project)
    assert severity == "warn" and "was signed by Blaise Sample, who is not the statistician" in hint

    _roles(project, "roles:\n  statistician: Nobody\n")
    [(severity, _message, hint)] = _signed_said(project)
    assert severity == "warn" and "'Nobody' is not an author" in hint
    assert main(["sign", str(project), "--as", "Sample", "--finding", _UNIT_WARNING]) == 2

    _roles(project, "")
    [(severity, _message, hint)] = _signed_said(project)
    assert severity == "warn" and "name the statistician under `roles:`" in hint
    assert main(["sign", str(project), "--as", "Sample", "--finding", _UNIT_WARNING]) == 2

    _roles(project, "roles:\n  statistician: Sample\n")
    [record] = (project / DIRECTORY).glob("*.yaml")
    signed = yaml.safe_load(record.read_text(encoding="utf-8"))
    elsewhere = {**signed, "finding": "G15/model-few-events/adjusted"}
    record.write_text(yaml.safe_dump(elsewhere), encoding="utf-8")
    [(severity, _message, hint)] = _signed_said(project)
    assert severity == "warn" and "signs another finding" in hint
    record.write_text(yaml.safe_dump({**signed, "signed_sha256": "not a digest"}), "utf-8")
    said = _signed_said(project)
    assert [s for s, _m, _h in said] == ["fail", "warn"], said
    assert "is not a sign-off it can read" in said[1][2]
    # Round 1 of #304: a record that is not YAML stopped G15, and its findings went with it.
    record.write_text("said: [unclosed\n", encoding="utf-8")
    said = _signed_said(project)
    assert [s for s, _m, _h in said] == ["fail", "warn"], said
    assert "cannot parse" in said[0][1] and "is not a sign-off it can read" in said[1][2]


def test_a_sign_off_is_bound_to_every_model_the_warning_names(project: Path) -> None:
    """Round 1 of #304: a warning that the adjusted model used other rows than the crude one
    was bound to the adjusted model's card alone, and kept its sign-off when the crude model
    was refitted on other rows of the same count. It keeps G15's place in the report, too."""
    from manuscript_guard.cli import main

    _crude_beside_adjusted(project, {"rows_sha256": _ROWS["all"]}, {"rows_sha256": _ROWS["some"]})
    project_, _ = load_project(project)
    _namespace, results, _literature, _report = load_namespace(project_)
    raised = [f.code for f in check_models(project_, results).findings]
    finding = "G15/models-on-different-rows/adjusted"
    assert main(["sign", str(project), "--as", "Sample", "--finding", finding]) == 0
    said = check_models(project_, results).findings
    assert [f.code for f in said] == raised
    assert [f.severity for f in said if f.code == "models-on-different-rows"] == ["info"]

    other = hashlib.sha256(b"other").hexdigest()
    _crude_beside_adjusted(project, {"rows_sha256": other}, {"rows_sha256": _ROWS["some"]})
    _namespace, results, _literature, _report = load_namespace(project_)
    said = [f for f in check_models(project_, results).findings
            if f.code == "models-on-different-rows"]  # fmt: skip
    assert [f.severity for f in said] == ["warn"] and "changed since" in said[0].hint


def test_a_signed_warning_keeps_its_place_among_the_others(project: Path) -> None:
    """Round 2 of #304: the order was held only where the signed warning came last, which
    appending it would also pass. Here a later warning follows it."""
    from manuscript_guard.cli import main

    _crude_beside_adjusted(project, {"rows_sha256": _ROWS["all"]},
                           {"rows_sha256": _ROWS["some"], "engine": _POISSON,
                            "covariance": "nonrobust"})  # fmt: skip
    project_, _ = load_project(project)
    _namespace, results, _literature, _report = load_namespace(project_)
    raised = [f.code for f in check_models(project_, results).findings]
    signed, later = "poisson-binary-variance", "models-on-different-rows"
    assert raised.index(signed) < raised.index(later), raised
    finding = f"G15/{signed}/adjusted"
    assert main(["sign", str(project), "--as", "Sample", "--finding", finding]) == 0
    said = check_models(project_, results).findings
    assert [f.code for f in said] == raised
    assert [f.severity for f in said if f.code == signed] == ["info"]


def test_a_statistician_who_is_not_an_author_signs_by_name(project: Path) -> None:
    from manuscript_guard.cli import main

    _model_card_has(project, unit={"column": "patient", "units": 3}, covariance="nonrobust")
    _roles(project, "roles:\n  statistician:\n    name: Chris Keeper\n"
                    "    email: chris.keeper@invalid.example\n")  # fmt: skip
    assert main(["sign", str(project), "--as", "Keeper", "--finding", _UNIT_WARNING]) == 2
    assert main(["sign", str(project), "--as", "chris.keeper@invalid.example", "--finding",
                 _UNIT_WARNING]) == 0  # fmt: skip
    [(severity, message, _hint)] = _signed_said(project)
    assert severity == "info" and "signed off by Chris Keeper, the statistician" in message


@pytest.mark.parametrize(
    "roles, valid",
    [
        ("roles:\n  ethics_lead:\n    author: Sample\n    approval: IRB-2026-014\n", True),
        ("roles:\n  ethics_lead: Sample\n", False),
        ("roles:\n  statistician:\n    author: Sample\n    name: Blaise Sample\n", False),
        ("roles:\n  reviewer: Sample\n", False),
    ],
)
def test_the_ethics_lead_is_named_with_the_approval(project: Path, roles: str, valid: bool) -> None:
    """The person responsible for ethics approval comes with the approval's reference; a
    holder is an author or a name, not both; and the roles are the ones the toolkit knows."""
    _roles(project, roles)
    _loaded, report = load_project(project)
    said = [f for f in report.findings if f.code == "authors-incomplete"]
    assert (not said) == valid, [f.message for f in said]


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


def _reversed_in(text: str) -> list[tuple[int, str]]:
    """The intervals G2 finds quoted upper bound first in `text`, each by its line and its
    level. `{low}` and `{high}` are the bounds of a 95% interval, `{low90}` and `{high90}`
    those of a 90% one around the same estimate. In the order the gate reports them."""
    from manuscript_guard.contracts.values import RESULTS, Value
    from manuscript_guard.gates.numbers import _interval_order
    from manuscript_guard.text.placeholders import parse

    namespace, written = {}, {}
    for slug, level in (("", None), ("90", "90%")):
        for end in ("low", "high"):
            key = f"ror.ci{slug}_{end}"
            namespace[f"results.{key}"] = Value(
                key, 1.0, "1.0", RESULTS, bounds="ror.point", bound=end, level=level
            )
            written[f"{end}{slug}"] = f"{{{{results.{key}}}}}"
    text = text.format(**written)
    report = _interval_order(parse(text)[0], namespace, Path("main.md"), text)
    assert {f.code for f in report.findings} <= {"interval-reversed"}
    return [(f.line, "90%" if "the 90% interval" in f.message else "") for f in report.findings]


@pytest.mark.parametrize(
    ("text", "backwards"),
    [
        ("The bounds were {high} and {low}.\n", [(1, "")]),
        ("The upper bound was {high}. The lower was {low}.\n", []),
        ("The upper bound was {high}.\n{low} was the lower.\n", []),
        ("Was the upper bound {high}? The lower was {low}! No more.\n", []),
        ("It ran {low} to {high}.\nAt 90% it ran {high90} to {low90}.\n", [(2, "90%")]),
        ("It ran {high} to {low}. At 90%\nit ran {high90}\nto {low90}.\n", [(1, ""), (2, "90%")]),
        ("It was (95% CI {low} to {high}; 90% CI {low90} to {high90}).\n", []),
        ("It was (95% CI {low} to {high}; 90% CI {high90} to {low90}).\n", [(1, "90%")]),
        ("It was (95% CI {high} to {low}; 90% CI {high90} to {low90}).\n", [(1, ""), (1, "90%")]),
        ("It was (90% CI {high90} to {low90}; 95% CI {high} to {low}).\n", [(1, "90%"), (1, "")]),
        ("It was {high90} (95%: {high} to {low}) to {low90}.\n", [(1, "90%"), (1, "")]),
        ("It was {low} and {high90} to {high} and {low90}.\n", [(1, "90%")]),
        ("It was {high} in 3.5 of them and {low} in the rest.\n", [(1, "")]),
        ("{high} to {low}", [(1, "")]),
    ],
    ids=[
        "one sentence",
        "successive sentences",
        "a sentence that ends its line",
        "a question and an exclamation",
        "two intervals in successive sentences",
        "a second sentence over three lines",
        "two levels in one sentence",
        "two levels, the second backwards",
        "two levels, both backwards",
        "two levels, both backwards, the 90% first",
        "two levels, both backwards, one inside the other",
        "two levels, one backwards and quoted second",
        "a stop inside a number",
        "nothing before or after",
    ],
)
def test_bounds_are_compared_within_their_sentence(
    text: str, backwards: list[tuple[int, str]]
) -> None:
    """Which sentence a bound is in was counted from the top of the file for every bound,
    and is now looked up among the sentence ends of the file. What is compared with what is
    as it was: these are the sentences `main` grouped the bounds into."""
    assert _reversed_in(text) == backwards


@pytest.mark.parametrize(
    ("text", "backwards"),
    [
        ("It ran {high}.{low} was the lower bound.\n", []),
        ("It ran.{high} to {low} in all.\n", []),
        ("Up.{high} came first. The lower bound was {low}.\n", [(1, "")]),
    ],
    ids=["between two bounds", "a reversal that passes", "a reversal that is none"],
)
def test_a_stop_against_a_binding_ends_a_sentence_for_that_binding_alone(
    text: str, backwards: list[tuple[int, str]]
) -> None:
    """A known limit, held so that it is known. A stop ends a sentence where white space
    follows it. One typed against a binding, `ran.{{results.ror.ci_high}}`, has none after
    it, and ends a sentence for that one binding and for nothing after it: the search for
    sentence ends stopped at each binding, and took the binding for the end of the text. So
    the binding is counted one sentence on from the rest of its own, among the bindings of
    the next. DESIGN.md has it under Known gaps."""
    assert _reversed_in(text) == backwards


@pytest.mark.parametrize(
    ("text", "backwards"),
    [
        ("It ran {high} <!-- was 7.02. --> to {low}.\n", [(1, "")]),
        ("It ran {high} <!-- was 7.02 --> to {low}.\n", [(1, "")]),
        ("It ran {high}\n<!--\nA note. Another!\n\nAnd a third?\n-->\nto {low}.\n", [(1, "")]),
        ("<!-- A draft. Of two sentences. -->\nIt ran {high} to {low}.\n", [(2, "")]),
        ("It ran {high}.<!-- checked --> The lower bound was {low}.\n", []),
        ("It ran {high}. <!-- checked -->The lower bound was {low}.\n", []),
        ("It ran {high}.<!-- checked -->{low} was the lower bound.\n", []),
        ("It ran.<!-- checked -->{high} to {low} in all.\n", [(1, "")]),
        ("It ran {high} `<!-- was 7.02. -->` to {low}.\n", []),
        ("It ran {high} <!-- was 7.02. to {low}.\n", []),
    ],
    ids=[
        "a stop in a comment",
        "a comment with no stop",
        "a comment of several lines",
        "a comment above the sentence",
        "a comment between a stop and its space",
        "a comment after a stop and its space",
        "a comment between a stop and a binding",
        "a comment between a stop and the upper bound",
        "a comment that is code",
        "a comment nobody closed",
    ],
)
def test_a_comment_is_white_space_to_the_sentences(
    text: str, backwards: list[tuple[int, str]]
) -> None:
    """Pandoc drops an HTML comment, and the bindings are read in the text with each
    comment blanked. The sentences were read in the text as typed. So a stop inside a
    comment ended a sentence between the two bounds of an interval, and the reversal
    passed with the paper printing it; and a stop with a comment typed against it ended
    none, so the bounds of two sentences were compared. The sentences are read where the
    bindings are now: a comment is white space to both. What is no comment, code or a
    `<!--` nobody closed, is read as it is typed."""
    assert _reversed_in(text) == backwards


def test_a_stop_in_a_comment_hides_no_reversed_interval(project: Path) -> None:
    """The example's interval quoted backwards, with a note between its bounds that holds
    a stop. Both bindings resolve, the note reaches no document, and the paper prints the
    interval backwards: `check` said nothing."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    swapped = text.replace(
        "{{results.ror.ci_low}} to {{results.ror.ci_high}}",
        "{{results.ror.ci_high}} <!-- was 7.02. Check. --> to {{results.ror.ci_low}}",
        1,
    )
    assert swapped != text, "the example must still quote the interval in one sentence"
    path.write_text(swapped, encoding="utf-8")
    assert "interval-reversed" in codes(gate_report(project))


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


@pytest.mark.parametrize(
    "display",
    [
        "$$y = 2.1 x$$",
        "2.1\n\n3.4",
        "2.1\n::: {.note}",
        "\\begin{equation}y = 2.1 x\\end{equation}",
        "2.1 <div>3.4</div>",
    ],
    ids=["display-maths", "blank-line", "line-break", "latex-environment", "html-block-tag"],
)
def test_a_value_that_would_split_its_paragraph_is_caught(project: Path, display: str) -> None:
    """Identifiers are given to the source before bindings are substituted, and a paragraph
    with `$$` in its source gets none. A value that prints display maths puts `$$` into a
    paragraph that has one: pandoc gives the equation a Word paragraph of its own, only the
    part before it carries the identifier, and import took a move of that part for a move
    of the whole sentence. `label=True` changes nothing, and a digit kept it quiet: the only
    word said was the prose warning, for a display with no digit in it."""
    _publish_text(project, "model.formula", display, label=True)
    report = gate_report(project)
    assert "value-splits-paragraph" in codes(report), report.findings
    finding = next(f for f in report.failures if f.code == "value-splits-paragraph")
    assert finding.path == main_md(project) and "results.model.formula" in finding.message


@pytest.mark.parametrize("display", ["$y = 2.1 x$", "2.1 (95% CI 1.8-2.4)", "*E. coli*"])
def test_a_value_that_stays_inside_its_sentence_is_not_caught(
    project: Path, display: str
) -> None:
    """Inline maths, a number with its interval, emphasis: pandoc keeps each inside the
    paragraph, and the paragraph reaches Word whole."""
    _publish_text(project, "model.formula", display, label=True)
    assert "value-splits-paragraph" not in {f.code for f in gate_report(project).findings}


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


# A manuscript folder with nothing in it the gates read. The run failed only through what that
# left behind, 21 results quoted nowhere, and at the design and analysis stages it passed.


def _as_quarto(root: Path) -> str:
    for path in (root / "manuscript").rglob("*.md"):
        path.rename(path.with_suffix(".qmd"))
    return ".qmd"


def _set_aside(root: Path) -> str:
    folder = root / "manuscript"
    drafts = folder / "_drafts"
    drafts.mkdir()
    for path in sorted(folder.glob("*.md")):
        path.rename(drafts / path.name)
    shutil.rmtree(folder / "supplementary")
    return "set aside by"


def _mistyped(root: Path) -> str:
    paper = root / "paper.yaml"
    paper.write_text(
        paper.read_text(encoding="utf-8") + "\npaths:\n  manuscript: manuscritp\n",
        encoding="utf-8",
    )
    return "manuscritp/ does not exist"


@pytest.mark.parametrize("empty", [_as_quarto, _set_aside, _mistyped], ids=lambda f: f.__name__)
def test_a_manuscript_folder_the_gates_cannot_read_is_named(project: Path, empty) -> None:
    from manuscript_guard.cli import _run_gates

    said = empty(project)
    report, _project, _stage, _deferred = _run_gates(project, stage="drafting")
    found = [f for f in report.failures if f.code == "manuscript-empty"]
    assert len(found) == 1 and said in found[0].message, report.render(project)
    assert "unquoted-result" not in codes(report), "the one finding, not one per result"


def _as_latex(root: Path) -> Path:
    """The example's manuscript as LaTeX: its entry file is `main.tex`, and no Markdown is
    left where the gates read."""
    folder = root / "manuscript"
    for path in folder.rglob("*.md"):
        path.unlink()
    entry = folder / "main.tex"
    entry.write_text(
        "\\documentclass{article}\n\\begin{document}\nOf 4100 reports, 12 were fatal.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    return entry


def test_a_manuscript_in_two_formats_is_refused_at_every_stage(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    (project / "manuscript" / "main.tex").write_text("\\documentclass{article}\n", "utf-8")
    for stage in ("design", "submission"):
        report, _project, _stage, _deferred = _run_gates(project, stage=stage)
        found = [f for f in report.failures if f.code == "two-formats"]
        assert len(found) == 1, (stage, report.render(project))


def test_markdown_in_a_latex_manuscript_is_refused(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    _as_latex(project)
    notes = project / "manuscript" / "notes.md"
    notes.write_text("Of 4100 reports, 12 were fatal.\n", encoding="utf-8")
    (project / "manuscript" / "_drafts").mkdir()
    (project / "manuscript" / "_drafts" / "old.md").write_text("Old.\n", encoding="utf-8")
    report, _project, _stage, _deferred = _run_gates(project, stage="design")
    found = [f for f in report.failures if f.code == "other-format-file"]
    assert [f.path for f in found] == [notes], report.render(project)


def test_a_gate_not_taught_latex_reads_nothing_and_fails_at_submission(project: Path) -> None:
    """Each gate that reads only Markdown would read nothing of a LaTeX manuscript and pass.
    It does not run, and says so: a note while the paper is written, a failure at
    submission. What it would have said of a folder with no Markdown is not said."""
    from manuscript_guard.cli import _run_gates

    _as_latex(project)
    drafting, _project, _stage, _deferred = _run_gates(project, stage="drafting")
    unread = sorted(f.gate for f in drafting.findings if f.code == "not-read-in-latex")
    expected = ["BUILD", "G1", "G13", "G14", "G15", "G2", "G4", "G6", "G7", "G8", "G8r", "G9"]
    assert unread == expected, drafting.render(project)
    assert "not-read-in-latex" not in codes(drafting)
    said = {f.code for f in drafting.findings}
    assert not {"manuscript-empty", "unquoted-result"} & said, drafting.render(project)
    submission, _project, _stage, _deferred = _run_gates(project, stage="submission")
    failing = sorted(f.gate for f in submission.failures if f.code == "not-read-in-latex")
    assert failing == expected, submission.render(project)


#: The checks that read the manuscript only as Markdown, and those that do not read it.
_MARKDOWN_ONLY = (
    "check_related",
    "check_numbers", "check_bound_units", "check_small_cells", "check_citations",
    "check_prose_quotations", "check_journal", "check_reporting", "check_writing",
    "check_methods", "check_synthetic_inputs", "check_reported", "check_recomputed",
    "check_revision", "check_language", "check_models", "check_shapes", "check_tex",
    "check_passages",
)  # fmt: skip
_NOT_THE_MANUSCRIPT = (
    "check_review", "check_freshness", "check_figures", "check_figure_reviews",
    "check_literature_chain", "check_shortlist", "check_design", "check_design_rounds",
    "check_consistency", "check_restricted_inputs", "check_relations",
    # It finds the figures placed in the Markdown sources, so it reads nothing of a LaTeX
    # manuscript and says nothing of one; it runs, as G3's other check does (round 1 of #387).
    "check_figure_alt",
    # The same, for the colours each figure paints.
    "check_figure_colours",
)  # fmt: skip
#: The checks that read LaTeX: they run on a LaTeX manuscript as on any.
_READS_LATEX = ("check_latex",)


def test_each_check_not_taught_latex_is_not_run_and_the_others_are(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinned check by check, not gate by gate (round 1 of #370): a check left out of the set
    shares its gate with one still in it, so the gates' names did not change."""
    from manuscript_guard import cli
    from manuscript_guard.findings import Report

    called: list[str] = []

    def recorder(name: str):
        return lambda *_args, **_kwargs: called.append(name) or Report()

    for name in _MARKDOWN_ONLY + _NOT_THE_MANUSCRIPT + _READS_LATEX:
        monkeypatch.setattr(cli, name, recorder(name))
    _as_latex(project)
    cli._run_gates(project, stage="drafting")
    assert sorted(called) == sorted(_NOT_THE_MANUSCRIPT + _READS_LATEX)
    # One entry calls two checks, so the set is pinned name by name as well (round 2). A
    # check an entry of the runner's table gains must be put in one of the tuples, and
    # the one the runner calls in its own body is `check_format` (round 3).
    assert set(_MARKDOWN_ONLY) == cli._NOT_READ_IN_LATEX
    body = {name for name in cli._run_gates.__code__.co_names if name.startswith("check_")}
    assert body == {"check_format"}
    runner = {
        name
        for code in cli._run_gates.__code__.co_consts
        if isinstance(code, type(cli._run_gates.__code__))
        for name in code.co_names
        if name.startswith("check_")
    }
    assert runner == set(_MARKDOWN_ONLY + _NOT_THE_MANUSCRIPT + _READS_LATEX)


def test_a_main_tex_without_a_class_leaves_a_markdown_manuscript_markdown(project: Path) -> None:
    """A header pandoc includes may be called `main.tex`: it declares no class, so it is no
    entry file, and the Markdown beside it is read as before (round 1 of #370)."""
    from manuscript_guard.cli import _run_gates

    header = project / "manuscript" / "main.tex"
    header.write_text("\\usepackage{booktabs}\n", "utf-8")
    report, _project, _stage, _deferred = _run_gates(project, stage="submission")
    said = {f.code for f in report.findings}
    assert not {"two-formats", "other-format-file", "not-read-in-latex"} & said


def test_what_the_latex_reader_refuses_fails_build_at_its_file_and_line(project: Path) -> None:
    """A brace left open in an input file, and an `\\input` of a file that is not there, each
    fail BUILD at every stage where they stand; a file nothing inputs is a warning."""
    from manuscript_guard.cli import _run_gates

    entry = _as_latex(project)
    folder = entry.parent
    entry.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{methods}\n\\input{gone}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (folder / "methods.tex").write_text("Of 4100.\nAn {open brace\n", encoding="utf-8")
    (folder / "notes.tex").write_text("Nobody inputs this.\n", encoding="utf-8")
    report, _project, _stage, _deferred = _run_gates(project, stage="design")
    found = {(f.code, f.path.name, f.line) for f in report.failures if f.gate == "BUILD"}
    assert ("tex-unbalanced", "methods.tex", 2) in found, report.render(project)
    assert ("tex-refused", "main.tex", 4) in found, report.render(project)
    warned = [f for f in report.findings if f.code == "tex-not-input"]
    assert [f.path.name for f in warned] == ["notes.tex"]
    assert "tex-not-input" not in codes(report)


@pytest.mark.parametrize("encoding", ["cp1252", "utf-16", "utf-32"])
def test_a_latex_file_that_is_not_utf8_is_named_as_a_markdown_one_is(
    project: Path, encoding: str
) -> None:
    """In a code page, or as UTF-16, which round 2 of #370 found taken for an empty Markdown
    folder: its `\\documentclass` was not seen in the bytes."""
    from manuscript_guard.cli import _run_gates

    entry = _as_latex(project)
    text = "\\documentclass{article}\nCaf\N{LATIN SMALL LETTER E WITH ACUTE}\n"
    entry.write_bytes(text.encode(encoding))
    report, _project, _stage, _deferred = _run_gates(project, stage="design")
    found = [f for f in report.failures if f.code == "manuscript-unreadable"]
    assert [f.path for f in found] == [entry], report.render(project)


# -------------------------------------------------------------------------------------- G7
# Citation integrity against a running Zotero, simulated: the fake answers as Better BibTeX
# 9.0.64 does (see tests/test_zotero.py), so these run anywhere.


def _g7(root: Path, *, closed: bool = True):
    """G7 as it reads with Zotero closed, so that what it says does not depend on the
    machine: CI has no Zotero, and a test opens no connection. A test that stands in for
    Zotero itself (`_zotero`) passes `closed=False`, and G7 reads that."""
    from unittest import mock

    from manuscript_guard.gates import check_citations

    project, _ = load_project(root)
    _namespace, _results, literature, _ = load_namespace(project)
    if not closed:
        return check_citations(project, literature)
    with mock.patch("manuscript_guard.gates.citations.available", return_value=False):
        return check_citations(project, literature)


# The identifiers of `references.bib` and the fields each entry needs, read offline: nothing
# read them, so a mistyped DOI or an article with no journal reached the reference list.


def _bib_field(root: Path, field: str, value: str | None) -> None:
    """Set, or with None take out, one field of the example's first reference."""
    bib = root / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    head, rest = text.split("@article{fictionalHepaticCohort2021,\n", 1)
    entry, tail = rest.split("\n}\n", 1)
    lines = [line for line in entry.split("\n") if not line.strip().startswith(f"{field} ")]
    if value is not None:
        lines.insert(0, f"  {field} = {{{value}}},")
    bib.write_text(
        head + "@article{fictionalHepaticCohort2021,\n" + "\n".join(lines) + "\n}\n" + tail,
        encoding="utf-8",
    )


def _bib_findings(root: Path) -> list[tuple[str, str]]:
    return [
        (f.code, f.message)
        for f in _g7(root).findings
        if f.code in ("identifier-malformed", "reference-field-missing")
    ]


def test_the_example_s_references_are_well_formed(project: Path) -> None:
    assert _bib_findings(project) == []


@pytest.mark.parametrize(
    ("field", "value", "said"),
    [
        ("doi", "10.1000", "the DOI '10.1000'"),
        ("doi", "1016/j.example.2021.01.001", "the DOI '1016/j.example.2021.01.001'"),
        ("doi", "10.1016/j example", "the DOI '10.1016/j example'"),
        ("pmid", "PMID: 12345678", "the PMID 'PMID: 12345678'"),
        ("pmcid", "1234567", "the PMCID '1234567'"),
        ("isbn", "978-0-306-40615-8", "the ISBN '978-0-306-40615-8'"),
        ("isbn", "0-306-40615-3", "the ISBN '0-306-40615-3'"),
        ("journal", None, "an @article entry needs its journal or journaltitle"),
        ("year", None, "an @article entry needs its year or date"),
    ],
)
def test_a_malformed_identifier_or_a_missing_field_is_said(
    project: Path, field: str, value: str | None, said: str
) -> None:
    _bib_field(project, field, value)
    found = _bib_findings(project)
    assert len(found) == 1 and said in found[0][1], found


def test_a_malformed_identifier_fails_from_internal_review(project: Path) -> None:
    """Deferred while drafting, when an entry may be a placeholder, and a failure once the
    reference list is printed for others to read."""
    from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, apply_stage

    _bib_field(project, "doi", "1016/j.example.2021.01.001")
    _bib_field(project, "journal", None)
    report = _g7(project)
    codes = {"identifier-malformed", "reference-field-missing"}
    drafting, deferred = apply_stage(report, DRAFTING)
    assert not [f for f in drafting.failures if f.code in codes]
    assert deferred.get(INTERNAL_REVIEW, 0) >= 2
    reviewed, _ = apply_stage(report, INTERNAL_REVIEW)
    assert {f.code for f in reviewed.failures} >= codes


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("doi", "10.1016/j.example.2021.01.001"),
        ("doi", "https://doi.org/10.1016/j.example.2021.01.001"),
        ("doi", "doi:10.1002/(SICI)1097-0258(19980430)17:8<857::AID-SIM777>3.0.CO;2-E"),
        ("pmid", "12345678"),
        ("pmcid", "PMC1234567"),
        ("isbn", "978-0-306-40615-7"),
        ("isbn", "0-8044-2957-X"),
        # round 1 of #249: groups parted by spaces, a label, two in one field
        ("isbn", "978 0 306 40615 7"),
        ("isbn", "ISBN 978-0-306-40615-7"),
        ("isbn", "0306406152 9780306406157"),
        ("year", None),  # a `date` in its place, as BibLaTeX writes it
    ],
)
def test_a_well_formed_identifier_or_a_field_s_other_name_passes(
    project: Path, field: str, value: str | None
) -> None:
    _bib_field(project, field, value)
    if field == "year":
        _bib_field(project, "date", "2021-03-01")
    assert _bib_findings(project) == []


# What the registries said of a cited reference, read from its lookup record by G7, offline.
# Each record here is written as `lookup` writes one, with its digests, by `_looked_up`.

_LOOKED_DOI = "10.5555/fictional.2021.001"
_LOOKED_KEY = "fictionalHepaticCohort2021"
#: The example's first reference, as Crossref would have it.
_CROSSREF = {
    "status": "found",
    "doi": _LOOKED_DOI,
    "type": "journal-article",
    "title": "Hepatic injury in a fictional national cohort, 2010-2019",
    "container": "Journal of Imaginary Pharmacoepidemiology",
    "years": {"print": 2021, "online": 2021, "issued": 2021},
    "volume": "12",
    "page": "101-109",
}


def _looked_up(root: Path, *, on: str = "2026-10-01", pmid: str | None = None, **sources):
    """Give the example's first reference a DOI (and a PMID), and write its lookup record
    with what each registry said: Crossref and OpenAlex found it unless told otherwise."""
    from manuscript_guard.literature.bibfile import read_entries
    from manuscript_guard.literature.lookups import (
        SCHEMA,
        answers_digest,
        entry_digest,
        write_record,
    )

    _bib_field(root, "doi", _LOOKED_DOI)
    if pmid:
        _bib_field(root, "pmid", pmid)
    fields = read_entries(root / "literature" / "references.bib")[_LOOKED_KEY]
    answers = {
        "crossref": _CROSSREF,
        "openalex": {"status": "found", "is_retracted": False},
        **sources,
    }
    record = {
        "schema": SCHEMA,
        "citekey": _LOOKED_KEY,
        "looked_up_on": on,
        "entry_sha256": entry_digest(fields),
        "identifiers": {"doi": _LOOKED_DOI, **({"pmid": pmid} if pmid else {})},
        "sources": {k: v for k, v in answers.items() if v is not None},
    }
    record["answers_sha256"] = answers_digest(record)
    write_record(load_project(root)[0], record)


def _g7_codes(root: Path) -> dict[str, str]:
    """What G7 says of the registries' records; with Zotero closed it also warns that no
    citation key was checked for pinning, which is not what these tests are about."""
    return {f.code: f.severity for f in _g7(root).findings if f.code != "pinning-unchecked"}


def _retraction(kind: str = "retraction") -> dict:
    notice = {"type": kind, "doi": "10.5555/notice.1", "date": "2023-02-06",
              "source": "retraction-watch"}  # fmt: skip
    return {**_CROSSREF, "updated_by": [notice]}


def test_a_reference_looked_up_and_found_as_cited_passes(project: Path) -> None:
    _looked_up(project)
    found = _g7_codes(project)
    assert not {c for c, s in found.items() if s != "info"}, found
    assert _g7(project).counts["references_looked_up"] == 1


@pytest.mark.parametrize(
    "sources",
    [
        {"crossref": _retraction()},
        {"crossref": _retraction("removal")},
        {"openalex": {"status": "found", "is_retracted": True}},
        {"pubmed": {"status": "found", "doi": _LOOKED_DOI,
                    "pubtypes": ["Journal Article", "Retracted Publication"]}},
    ],
)  # fmt: skip
def test_a_retracted_reference_fails_from_drafting(project: Path, sources: dict) -> None:
    from manuscript_guard.policy import DRAFTING, apply_stage

    _looked_up(project, pmid="31000001" if "pubmed" in sources else None, **sources)
    report = _g7(project)
    assert "reference-retracted" in {f.code for f in report.failures}
    drafting, _ = apply_stage(report, DRAFTING)
    assert "reference-retracted" in {f.code for f in drafting.failures}


def test_a_retracted_reference_cited_with_a_reason_is_noted(project: Path) -> None:
    paper = project / "paper.yaml"
    paper.write_text(
        paper.read_text(encoding="utf-8") + f"\nlookup:\n  cited_as_retracted:\n"
        f"    {_LOOKED_KEY}: the Discussion is about why it was retracted\n",
        encoding="utf-8",
    )
    _looked_up(project, crossref=_retraction())
    found = _g7_codes(project)
    assert "reference-retracted" not in found
    assert found["reference-retracted-cited"] == "info"


def test_an_expression_of_concern_or_a_correction_is_not_a_retraction(project: Path) -> None:
    concern = {**_CROSSREF, "updated_by": [{"type": "expression_of_concern"},
                                            {"type": "correction"}]}  # fmt: skip
    _looked_up(project, crossref=concern)
    found = _g7_codes(project)
    assert "reference-retracted" not in found
    assert found["reference-under-concern"] == "warn"


@pytest.mark.parametrize(
    ("sources", "fails"),
    [
        ({"crossref": {"status": "absent"}, "datacite": {"status": "absent"},
          "doi_org": {"status": "absent"}}, True),
        # Not proof: one of the three did not answer.
        ({"crossref": {"status": "absent"}, "datacite": {"status": "absent"},
          "doi_org": {"status": "unresolvable", "why": "HTTP 500"}}, False),
        # Registered by another agency: doi.org knows it, and nothing more is known.
        ({"crossref": {"status": "absent"}, "datacite": {"status": "absent"},
          "doi_org": {"status": "found"}}, False),
    ],
)  # fmt: skip
def test_a_doi_registered_nowhere_fails_and_only_when_every_registry_said_so(
    project: Path, sources: dict, fails: bool
) -> None:
    _looked_up(project, **sources)
    found = _g7_codes(project)
    assert ("doi-unregistered" in found) is fails, found


def test_a_dataset_s_doi_crossref_does_not_know_passes(project: Path) -> None:
    dataset = {"status": "found", "title": _CROSSREF["title"], "type": "Dataset", "year": 2021}
    _looked_up(project, crossref={"status": "absent"}, datacite=dataset)
    found = _g7_codes(project)
    assert not {c for c, s in found.items() if s != "info"}, found


@pytest.mark.parametrize(
    ("registered", "fails"),
    [
        ("Renal injury in a fictional national cohort, 2010-2019", False),  # 7 of 8 held
        ("Renal failure in a fictional national registry, 2010-2019", True),
        ("A disproportionality signal for a fictional drug class", True),
        # a subtitle the entry left out, and a flag the registry put in front
        ("RETRACTED: Hepatic injury in a fictional national cohort, 2010-2019: a study",
         False),
        ("Hepatic injury in a fictional national cohort, 2010\N{EN DASH}2019", False),
    ],
)  # fmt: skip
def test_an_identifier_that_names_another_title_fails(
    project: Path, registered: str, fails: bool
) -> None:
    _looked_up(project, crossref={**_CROSSREF, "title": registered})
    found = _g7_codes(project)
    assert ("reference-title-mismatch" in found) is fails, found


def test_a_title_in_british_spelling_matches_its_american_registration(project: Path) -> None:
    _bib_field(project, "title", "Haemorrhage and tumour behaviour in a randomised cohort")
    _looked_up(
        project,
        crossref={**_CROSSREF, "title": "Hemorrhage and tumor behavior in a randomized cohort"},
    )
    assert "reference-title-mismatch" not in _g7_codes(project)


@pytest.mark.parametrize(("pubmed_doi", "fails"), [(_LOOKED_DOI, False), (None, True)])
def test_pubmed_s_title_of_the_same_work_is_a_candidate(
    project: Path, pubmed_doi: str | None, fails: bool
) -> None:
    """Round 1 of #253: a paper Crossref registered under its title in another language,
    and PubMed under the English one the entry cites, was said to name another title.
    PubMed's title counts where PubMed gives the work the entry's own DOI."""
    crossref = {**_CROSSREF, "title": "Lésions hépatiques dans une cohorte nationale fictive"}
    pubmed = {"status": "found", "title": "Hepatic injury in a fictional national cohort, "
              "2010-2019", **({"doi": pubmed_doi} if pubmed_doi else {})}  # fmt: skip
    _looked_up(project, pmid="31000001", crossref=crossref, pubmed=pubmed)
    assert ("reference-title-mismatch" in _g7_codes(project)) is fails


def test_a_title_in_another_script_is_not_compared(project: Path) -> None:
    _looked_up(project, crossref={**_CROSSREF, "title": "架空のコホートにおける肝障害"})
    assert "reference-title-mismatch" not in _g7_codes(project)


@pytest.mark.parametrize(
    ("crossref", "pubtypes"),
    [
        ({**_CROSSREF, "update_to": [{"type": "retraction", "doi": "10.5555/other"}]}, None),
        ({**_CROSSREF, "update_to": [{"type": "erratum", "doi": "10.5555/other"}]}, None),
        ({**_CROSSREF, "type": "journal"}, None),
        ({**_CROSSREF, "type": "journal-issue"}, None),
        ({**_CROSSREF, "type": "component"}, None),
        (_CROSSREF, ["Published Erratum"]),
    ],
)  # fmt: skip
def test_an_identifier_that_names_a_notice_or_a_container_fails(
    project: Path, crossref: dict, pubtypes: list | None
) -> None:
    pubmed = {"status": "found", "doi": _LOOKED_DOI, "pubtypes": pubtypes} if pubtypes else None
    _looked_up(project, pmid="31000001" if pubmed else None, crossref=crossref, pubmed=pubmed)
    found = _g7_codes(project)
    assert "reference-not-the-work" in found, found


def test_a_volume_cited_as_proceedings_may_resolve_to_one(project: Path) -> None:
    _looked_up(project, crossref={**_CROSSREF, "type": "proceedings"})
    bib = project / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8").replace(
            f"@article{{{_LOOKED_KEY},", f"@proceedings{{{_LOOKED_KEY},", 1
        ),
        encoding="utf-8",
    )
    assert "reference-not-the-work" not in _g7_codes(project)


@pytest.mark.parametrize(("years", "fails"), [
    ({"print": 2022, "online": 2021, "issued": 2021}, False),
    ({"print": 2022}, False),
    ({"print": 2019, "issued": 2019}, True),
    ({"issued": 2024, "online": 2023}, True),
])  # fmt: skip
def test_a_year_more_than_one_off_every_registered_year_fails(
    project: Path, years: dict, fails: bool
) -> None:
    _looked_up(project, crossref={**_CROSSREF, "years": years})
    found = _g7_codes(project)
    assert ("reference-year-mismatch" in found) is fails, found


def test_a_pmid_that_names_another_work_than_the_doi_fails(project: Path) -> None:
    pubmed = {"status": "found", "doi": "10.5555/another.work", "pubtypes": ["Journal Article"]}
    _looked_up(project, pmid="31000001", pubmed=pubmed)
    assert "pmid-names-another-work" in _g7_codes(project)


def test_the_identity_failures_wait_for_internal_review(project: Path) -> None:
    from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, apply_stage

    _looked_up(project, crossref={**_CROSSREF, "title": "Another paper", "type": "journal"})
    report = _g7(project)
    identity = {"reference-title-mismatch", "reference-not-the-work"}
    assert identity <= {f.code for f in report.failures}
    drafting, _ = apply_stage(report, DRAFTING)
    assert not identity & {f.code for f in drafting.failures}
    reviewed, _ = apply_stage(report, INTERNAL_REVIEW)
    assert identity <= {f.code for f in reviewed.failures}


def test_a_preprint_published_since_is_said(project: Path) -> None:
    preprint = {**_CROSSREF, "type": "posted-content", "subtype": "preprint",
                "preprint_of": ["10.5555/published.version"]}  # fmt: skip
    _looked_up(project, crossref=preprint)
    found = _g7_codes(project)
    assert found["preprint-published"] == "warn"


def test_a_withdrawn_preprint_is_said_and_not_failed_as_retracted(project: Path) -> None:
    preprint = {**_retraction("withdrawal"), "type": "posted-content", "subtype": "preprint"}
    _looked_up(project, crossref=preprint)
    found = _g7_codes(project)
    assert found["preprint-withdrawn"] == "warn" and "reference-retracted" not in found


def test_an_edited_record_fails(project: Path) -> None:
    """A retraction taken out of a record by hand, the digest left as `lookup` wrote it."""
    from manuscript_guard.literature.lookups import record_path

    _looked_up(project, crossref=_retraction())
    path = record_path(load_project(project)[0], _LOOKED_KEY)
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    del record["sources"]["crossref"]["updated_by"]
    path.write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    found = _g7_codes(project)
    assert "lookup-record-edited" in found and "reference-retracted" not in found


def test_a_record_dated_in_the_future_fails(project: Path) -> None:
    _looked_up(project, on="2999-01-01")
    assert "lookup-date-future" in _g7_codes(project)


def test_an_old_or_missing_record_or_a_changed_entry_is_said(project: Path) -> None:
    _looked_up(project, on="2020-01-01")
    _bib_field(project, "volume", "13")
    _bib_field(project, "doi", "10.5555/second")  # the other reference: no record
    found = _g7_codes(project)
    assert found["lookup-stale"] == "warn"
    assert found["lookup-entry-changed"] == "warn"


def test_a_reference_with_an_identifier_and_no_record_is_said_once(project: Path) -> None:
    _bib_field(project, "doi", _LOOKED_DOI)
    findings = [f for f in _g7(project).findings if f.code == "lookup-missing"]
    assert len(findings) == 1 and findings[0].severity == "warn"
    assert f"@{_LOOKED_KEY}" in findings[0].message


def test_an_answer_that_did_not_come_fails_nothing(project: Path) -> None:
    _looked_up(project, crossref={"status": "unresolvable", "why": "HTTP 429"})
    found = _g7_codes(project)
    assert found.pop("lookup-unresolvable") == "info"
    assert not {c for c, s in found.items() if s != "info"}, found


def test_a_lookup_that_got_no_answer_at_all_is_a_warning(project: Path) -> None:
    """Round 1 of #253: nothing is known of the reference, retracted or not."""
    _looked_up(project, crossref={"status": "unresolvable", "why": "HTTP 429"},
               openalex={"status": "unresolvable", "why": "HTTP 429"})  # fmt: skip
    found = _g7_codes(project)
    assert found.pop("lookup-unresolvable") == "warn"
    assert not {c for c, s in found.items() if s == "fail"}, found


@pytest.mark.parametrize(
    ("cited", "registered"),
    [
        # round 1 of #253: markup on either side is part of a word, not a space in it
        ("Ambient PM\N{REVERSE SOLIDUS}textsubscript2.5 and hepatic injury in a cohort",
         "Ambient PM<sub>2.5</sub> and hepatic injury in a cohort"),
        ("Ambient PM2.5 and hepatic injury in a cohort",
         "Ambient PM<sub>2.5</sub> and hepatic injury in a cohort"),
        ("$^18$F-FDG uptake in hepatic injury",
         "<sup>18</sup>F-FDG uptake in hepatic injury"),
        ("Une fran\N{REVERSE SOLIDUS}c caise cohort of hepatic injury",
         "Une fran\N{LATIN SMALL LETTER C WITH CEDILLA}aise cohort of hepatic injury"),
        ("Une fran\N{REVERSE SOLIDUS}ccaise cohort of hepatic injury",
         "Une fran\N{LATIN SMALL LETTER C WITH CEDILLA}aise cohort of hepatic injury"),
        # round 2 of #253: a Greek letter is no accent and the letters after it
        ("$\N{REVERSE SOLIDUS}beta$-Lactam allergy in children",
         "\N{GREEK SMALL LETTER BETA}-Lactam allergy in children"),
        ("$\N{REVERSE SOLIDUS}kappa$ and $\N{REVERSE SOLIDUS}tau$ in hepatic injury",
         "\N{GREEK SMALL LETTER KAPPA} and \N{GREEK SMALL LETTER TAU} in hepatic injury"),
    ],
)  # fmt: skip
def test_a_title_marked_up_on_either_side_is_the_same_title(
    project: Path, cited: str, registered: str
) -> None:
    _bib_field(project, "title", cited)
    _looked_up(project, crossref={**_CROSSREF, "title": registered})
    assert "reference-title-mismatch" not in _g7_codes(project)


@pytest.mark.parametrize("kind", ["new_version", "new_edition"])
def test_a_new_version_of_a_work_is_the_work(project: Path, kind: str) -> None:
    """Round 1 of #253: a Cochrane review's current version updates the one before it,
    and is no notice."""
    _looked_up(project, crossref={**_CROSSREF, "update_to": [{"type": kind, "doi": "10.5/x"}]})
    assert "reference-not-the-work" not in _g7_codes(project)


def test_a_pmid_pubmed_does_not_know_fails(project: Path) -> None:
    _looked_up(project, pmid="31000001", pubmed={"status": "absent"})
    found = _g7_codes(project)
    assert found["pmid-unknown"] == "fail"


@pytest.mark.parametrize("pages", ["e000", "in press", "xxx-xxx", "??", "0--0"])
def test_placeholder_pages_are_said(project: Path, pages: str) -> None:
    _bib_field(project, "pages", pages)
    assert _g7_codes(project).get("pages-placeholder") == "warn"


@pytest.mark.parametrize(
    ("crossref", "said"),
    [
        ({**_CROSSREF, "volume": "21"}, "volume 12, registered 21"),
        ({**_CROSSREF, "page": "110-118"}, "first page or number 101"),
        ({**_CROSSREF, "page": None, "article_number": "101880T"}, "registered 101880t"),
    ],
)
def test_a_volume_or_first_page_that_differs_is_a_warning(
    project: Path, crossref: dict, said: str
) -> None:
    _looked_up(project, crossref={k: v for k, v in crossref.items() if v is not None})
    findings = [f for f in _g7(project).findings if f.code == "reference-details-differ"]
    assert len(findings) == 1 and findings[0].severity == "warn" and said in findings[0].message


@pytest.mark.parametrize(
    "fields",
    [
        # round 1 of #249: complete in BibLaTeX, which `sync-bib` writes, and short of a
        # field only BibTeX's styles ask for
        {"type": "unpublished", "author": "A", "title": "T", "date": "2024"},
        {"type": "book", "author": "A", "title": "T", "year": "2020"},
        {"type": "incollection", "author": "A", "title": "T", "booktitle": "B", "date": "2020"},
        {"type": "inbook", "author": "A", "title": "T", "booktitle": "B", "year": "2020"},
    ],
)
def test_an_entry_complete_in_either_format_needs_no_other_field(fields: dict) -> None:
    from manuscript_guard.gates.identifiers import problems

    assert problems("k", fields) == []


@pytest.mark.parametrize(
    "doi",
    [
        "https://www.doi.org/10.1016/j.example.2021.01.001",
        "doi.org/10.1016/j.example.2021.01.001",
        "dx.doi.org/10.1016/j.example.2021.01.001",
        "DOI 10.1016/j.example.2021.01.001",
        "DOI: 10.1016/j.example.2021.01.001",
    ],
)
def test_a_doi_written_with_a_resolver_or_its_scheme_is_read(project: Path, doi: str) -> None:
    """Round 1 of #249: these were reported malformed. Zotero stores a bare DOI, and a
    reference typed by hand or pasted from a page is often written so."""
    _bib_field(project, "doi", doi)
    assert _bib_findings(project) == []


@pytest.mark.parametrize(
    "isbn",
    [
        "ISBN 13: 978-0-306-40615-7",
        "e-ISBN 978-0-306-40615-7",
        "eISBN: 978 0 306 40615 7",
        "978-0-306-40615-7 pbk.",
        "0-306-40615-2 Hardcover; 978-0-306-40615-7 paperback",
    ],
)
def test_an_isbn_labelled_or_qualified_without_brackets_is_read(isbn: str) -> None:
    """Round 2 of #249: each label and qualifier stuck to the ISBN beside it, and a valid
    ISBN was reported."""
    from manuscript_guard.gates.identifiers import problems

    assert problems("k", {"type": "misc", "isbn": isbn}) == []


def test_an_isbn_10_opening_978_before_another_word_is_pinned() -> None:
    """Known gaps (round 2 of #249): a valid ISBN-10 that opens with 978, followed by a
    word that is no label or qualifier, is read as the start of an ISBN-13 and reported."""
    from manuscript_guard.gates.identifiers import problems

    assert problems("k", {"type": "misc", "isbn": "9781234563"}) == []
    assert problems("k", {"type": "misc", "isbn": "9781234563 pbk."}) == []
    found = problems("k", {"type": "misc", "isbn": "9781234563 reprint"})
    assert [code for code, _said in found] == ["identifier-malformed"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        # Round 1 of #345: a field of qualifiers alone holds no ISBN, and was emptied.
        ("isbn", "online"),
        ("isbn", "(print)"),
        # A scheme that lost its colon is no dressing to take off.
        ("doi", "doi10.1000/x"),
    ],
)
def test_what_is_set_aside_beside_an_identifier_is_no_identifier(field: str, value: str) -> None:
    from manuscript_guard.gates.identifiers import problems

    found = problems("k", {"type": "misc", field: value})
    assert [code for code, _said in found] == ["identifier-malformed"], found


def test_an_isbn_written_in_brackets_alone_is_left_as_it_was() -> None:
    """Round 2 of #345: a bracketed group is set aside as a qualifier, so an ISBN written in
    brackets alone left the field empty, and "holds no ISBN" refused a valid one."""
    from manuscript_guard.gates.identifiers import problems

    assert problems("k", {"type": "misc", "isbn": "(978-0-306-40615-7)"}) == []
    # Round 3: read there, with its check digit; and a digit in a label or in words in
    # brackets is no ISBN.
    for field in ("(978-0-306-40615-8)", "ISBN-13:", "(2nd ed., 1999)"):
        found = problems("k", {"type": "misc", "isbn": field})
        assert [code for code, _said in found] == ["identifier-malformed"], field


def test_a_volume_of_its_word_alone_stays_a_volume() -> None:
    """Round 1 of #345: "V." (five) became no volume, and the book merged with the one
    cited with none. Round 2: "Volume" lost its "Vol", and "Vol." became "."."""
    from manuscript_guard.gates.duplicates import _volume, identifiers_of

    def named(volume: str | None) -> set:
        fields = {"type": "book", "isbn": "0-306-40615-2"}
        return identifiers_of({**fields, "volume": volume} if volume else fields)

    assert named("V.") != named(None) and named("Volume") != named(None)
    assert named("Vol. 1") == named("1") == named("v. 1") == named("Volume 1")
    assert [_volume(v) for v in ("Volume", "Vol.", "V.", "Vol.2")] == ["volume", "vol.", "v.", "2"]
    # Round 3: a word with a digit straight after it.
    assert named("Vol1") == named("1")


def test_a_part_takes_from_its_crossref_all_but_the_title() -> None:
    """Round 1 of #345: every field of the parent was taken under its own name, so a paper
    with no title of its own met "needs its title" with the proceedings' name. Round 2: a
    chapter takes its book's author, as biber gives it."""
    from manuscript_guard.gates.identifiers import problems

    parent = {"type": "proceedings", "title": "The meeting", "year": "2020",
              "editor": "Somebody"}  # fmt: skip
    found = problems("k", {"type": "inproceedings", "author": "A", "crossref": "p"}, parent)
    assert [said for _code, said in found] == [
        "@k: an @inproceedings entry needs its title, and has none",
    ]
    book = {"type": "book", "author": "Kant, I.", "title": "Werke", "year": "1900"}
    assert problems("c", {"type": "inbook", "title": "Kritik", "crossref": "b"}, book) == []
    # Round 3: a periodical's title is the article's journal, and a multi-volume work's is
    # no booktitle.
    article = {"type": "article", "author": "A", "title": "T", "year": "2000", "crossref": "j"}
    assert problems("a", article, {"type": "periodical", "title": "J"}) == []
    chapter = {"type": "incollection", "author": "A", "title": "T", "year": "2000"}
    found = problems("a", chapter, {"type": "mvcollection", "title": "J"})
    assert [said for _code, said in found] == [
        "@a: an @incollection entry needs its booktitle, and has none"
    ]


def test_a_part_takes_its_book_s_fields_from_its_crossref(project: Path) -> None:
    """Round 1 of #249: a hand-written `@inproceedings` that takes its booktitle from the
    `@proceedings` its `crossref` names was told it had none. The key is matched exactly, as
    biber matches it (round 1 of #345)."""
    bib = project / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8")
        + "\n@inproceedings{part2020,\n  author = {A},\n  title = {A paper},\n"
        "  crossref = {proc2020},\n}\n\n@proceedings{proc2020,\n  title = {The meeting},\n"
        "  year = {2020},\n}\n\n@inproceedings{orphan2020,\n  author = {B},\n"
        "  title = {Another paper},\n  crossref = {Proc2020},\n  year = {2020},\n}\n",
        encoding="utf-8",
    )
    assert [message for _code, message in _bib_findings(project)] == [
        "@orphan2020: an @inproceedings entry needs its booktitle, and has none"
    ]


def test_a_field_named_type_leaves_the_entry_s_type(tmp_path: Path) -> None:
    """Round 2 of #261: `type = {chapter}` took the place of `@inbook`, and the entry was
    read as a type nothing requires anything of."""
    from manuscript_guard.literature.bibfile import read_entries

    bib = tmp_path / "references.bib"
    bib.write_text("@inbook{k,\n  type = {Chapter},\n  author = {A},\n}\n", encoding="utf-8")
    assert read_entries(bib)["k"]["type"] == "inbook"
    # Round 1 of #345: the field is kept beside it, for the readers that want it.
    assert read_entries(bib)["k"]["type_field"] == "Chapter"


# One work cited under two keys: the reference list prints it twice.


def _both_have(
    root: Path, first: dict[str, str], second: dict[str, str], types: tuple[str, str] = ("", "")
) -> None:
    """Give each of the example's two references the fields named, and the entry type. Their
    volumes go, so that a volume is only the one a test gives."""
    bib = root / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    text = text.replace("  volume  = {12},\n", "").replace("  volume  = {7},\n", "")
    keys = ("fictionalHepaticCohort2021", "fictionalClassSignal2019")
    for key, fields, kind in zip(keys, (first, second), types, strict=True):
        opening = f"@article{{{key},\n"
        added = "".join(f"  {name} = {{{value}}},\n" for name, value in fields.items())
        text = text.replace(opening, "@" + (kind or "article") + opening[8:] + added, 1)
    bib.write_text(text, encoding="utf-8")


def _duplicate_findings(root: Path) -> list[tuple[str, str, str]]:
    return [
        (f.code, f.severity, f.message)
        for f in _g7(root).findings
        if f.code in ("reference-duplicate", "reference-title-duplicate")
    ]


@pytest.mark.parametrize(
    ("first", "second", "named"),
    [
        ({"doi": "10.5555/x.1"}, {"doi": "https://doi.org/10.5555/X.1."}, "DOI"),
        ({"pmid": "31000001"}, {"pmid": "031000001"}, "PMID"),
        ({"pmcid": "PMC1234"}, {"pmcid": "pmc1234"}, "PMCID"),
        ({"isbn": "0-306-40615-2"}, {"isbn": "978-0-306-40615-7"}, "ISBN"),
        # Round 2 of #261: one volume written with its word and without.
        ({"isbn": "0-306-40615-2", "volume": "1"},
         {"isbn": "978-0-306-40615-7", "volume": "Vol. 1"}, "ISBN"),
        # Round 1 of #249: a resolver with `www.`, and a scheme with no colon.
        ({"doi": "10.5555/x.1"}, {"doi": "https://www.doi.org/10.5555/x.1"}, "DOI"),
        ({"doi": "10.5555/x.1"}, {"doi": "DOI 10.5555/X.1"}, "DOI"),
    ],
)  # fmt: skip
def test_one_work_cited_under_two_keys_fails(
    project: Path, first: dict, second: dict, named: str
) -> None:
    _both_have(project, first, second, ("book", "collection") if named == "ISBN" else ("", ""))
    said = _duplicate_findings(project)
    assert [(code, severity) for code, severity, _ in said] == [("reference-duplicate", "fail")]
    assert f"by the same {named}" in said[0][2]


def test_one_work_under_two_keys_fails_from_internal_review(project: Path) -> None:
    from manuscript_guard.policy import DRAFTING, INTERNAL_REVIEW, apply_stage

    _both_have(project, {"doi": "10.5555/x.1"}, {"doi": "10.5555/x.1"})
    report = _g7(project)
    drafting, _ = apply_stage(report, DRAFTING)
    assert "reference-duplicate" not in {f.code for f in drafting.failures}
    reviewed, _ = apply_stage(report, INTERNAL_REVIEW)
    assert "reference-duplicate" in {f.code for f in reviewed.failures}


def test_two_entries_with_one_title_are_a_warning(project: Path) -> None:
    bib = project / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8").replace(
            "A disproportionality signal for a fictional drug class",
            "HEPATIC INJURY IN A FICTIONAL NATIONAL COHORT, 2010--2019",
            1,
        ),
        encoding="utf-8",
    )
    said = _duplicate_findings(project)
    assert [(code, severity) for code, severity, _ in said] == [
        ("reference-title-duplicate", "warn")
    ]  # fmt: skip


_ISBN = "978-0-306-40615-7"


@pytest.mark.parametrize(
    ("types", "first", "second"),
    [
        # Two chapters of one book carry its ISBN, or its DOI.
        (("incollection", "incollection"), {"isbn": _ISBN}, {"isbn": "0-306-40615-2"}),
        (("inbook", "inbook"), {"doi": "10.5555/book.1"}, {"doi": "10.5555/book.1"}),
        # Two papers of one proceedings volume.
        (("inproceedings", "inproceedings"), {"isbn": _ISBN}, {"isbn": _ISBN}),
        # A book cited beside one of its chapters.
        (
            ("book", "incollection"),
            {"isbn": _ISBN, "doi": "10.5555/book.1"},
            {"isbn": _ISBN, "doi": "10.5555/book.1"},
        ),
        # Two volumes of one set, under the set's ISBN.
        (("book", "book"), {"isbn": _ISBN, "volume": "1"}, {"isbn": _ISBN, "volume": "2"}),
        # An ISBN on an article or a misc entry names no book that is cited.
        (("article", "misc"), {"isbn": _ISBN}, {"isbn": _ISBN}),
    ],
)
def test_parts_of_one_book_are_two_works(
    project: Path, types: tuple[str, str], first: dict, second: dict
) -> None:
    _both_have(project, first, second, types)
    assert _duplicate_findings(project) == []


def test_different_works_and_an_uncited_duplicate_say_nothing(project: Path) -> None:
    _both_have(project, {"doi": "10.5555/x.1"}, {"doi": "10.5555/x.2"})
    assert _duplicate_findings(project) == []
    bib = project / "literature" / "references.bib"
    bib.write_text(
        bib.read_text(encoding="utf-8")
        + "\n@article{uncitedCopy2021,\n  doi = {10.5555/x.1},\n  title = {T},\n}\n",
        encoding="utf-8",
    )
    assert _duplicate_findings(project) == []


def _zotero(monkeypatch, items: list[dict]) -> None:
    from test_zotero import FakeBBT

    from manuscript_guard.zotero import client, reset_cache

    reset_cache()
    monkeypatch.setattr(client, "rpc", FakeBBT(items))
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: True)


def test_an_unpinned_cited_key_is_caught(project: Path, monkeypatch) -> None:
    from test_zotero import CLASS, HEPATIC, csl

    _zotero(monkeypatch, [csl(HEPATIC, True), csl(CLASS, False)])
    report = _g7(project, closed=False)
    unpinned = [f for f in report.failures if f.code == "citation-key-unpinned"]
    assert [f.message for f in unpinned] == [f"@{CLASS} is not pinned in Zotero"]
    assert f"Citation Key: {CLASS}" in unpinned[0].hint


def test_a_cited_key_carried_by_two_items_is_caught(project: Path, monkeypatch) -> None:
    """The duplicate that made Better BibTeX refuse the whole export in a real project."""
    from test_zotero import CLASS, HEPATIC, csl

    _zotero(monkeypatch, [csl(HEPATIC, True), csl(CLASS, True), csl(CLASS, False)])
    report = _g7(project, closed=False)
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
    report = _g7(project, closed=False)
    assert any(
        f.code == "citation-unresolved" and "ghostKey2020" in f.message for f in report.failures
    )


# A literature value with a blank field. `source_file: ""` was passed over by both gates:
# `check --stage drafting` added no finding, and the value was simply not counted as
# verified, so the run claimed every value it had checked was verified.

_BLANK_FIELDS = [
    ("ledger", "source_file", ""),
    ("ledger", "source_file", "   "),
    ("ledger", "locator", ""),
    ("ledger", "locator", " "),
    ("ledger", "quote", " "),
    ("attested", "attested_by", " "),
    ("attested", "statement", "\t"),
    ("attested", "source", " "),
    ("attested", "locator", " "),
]


@pytest.mark.parametrize(
    ("file", "field", "blank"),
    _BLANK_FIELDS,
    ids=[f"{file}-{field}-{len(blank)}" for file, field, blank in _BLANK_FIELDS],
)
def test_a_literature_value_with_a_blank_field_fails(
    project: Path, file: str, field: str, blank: str
) -> None:
    from manuscript_guard.cli import _run_gates

    path = project / "literature" / f"{file}.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"][0][field] = blank
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    report, _project, _stage, _deferred = _run_gates(project, stage="drafting")
    assert any(
        f.code == "schema-violation" and f"entries/0/{field}" in f.message
        for f in report.failures
    ), report.render(project)


def _literature_report(root: Path, change=None):
    """G7's two literature checks, run as `check` runs them; `change` edits the loaded
    values first, to reach the gates with what the schema would have refused."""
    from manuscript_guard.gates import check_citations, check_literature_chain

    project, _ = load_project(root)
    _namespace, _results, literature, load_report = load_namespace(project)
    if change is not None:
        literature = change(literature)
    return merge_all(
        [
            load_report,
            check_citations(project, literature),
            check_literature_chain(project, literature),
        ]
    )


def _without_source(literature):
    from dataclasses import replace

    from manuscript_guard.contracts.literature import Literature

    key = "background.reported_incidence"
    value = literature.values[key]
    changed = replace(value, detail={**value.detail, "source_file": " "})
    return Literature({**literature.values, key: changed}, literature.root)


def _source_removed(root: Path) -> None:
    (root / "literature" / "sources" / "fictionalHepaticCohort2021.txt").unlink()


def _misquoted(root: Path) -> None:
    source = root / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text("A different paper entirely.\n", encoding="utf-8")


def _value_not_quoted(root: Path) -> None:
    path = root / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"][0].update(value=17.0, display="17")
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _unreadable(root: Path) -> None:
    path = root / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"][0]["source_file"] = "sources/fictionalHepaticCohort2021.docx"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (root / "literature" / "sources" / "fictionalHepaticCohort2021.docx").write_bytes(b"PK")


@pytest.mark.parametrize(
    ("edit", "change", "verdict", "code"),
    [
        (None, None, "literature_verified", None),
        (None, _without_source, "literature_failed", "literature-source-missing"),
        (_source_removed, None, "literature_failed", "literature-source-missing"),
        (_misquoted, None, "literature_failed", "quote-not-in-source"),
        (_value_not_quoted, None, "literature_failed", "value-not-in-quote"),
        (_unreadable, None, "literature_unverifiable", None),
    ],
    ids=["clean", "no source named", "source gone", "quote", "value", "unreadable"],
)
def test_every_literature_value_ends_in_one_verdict(
    project: Path, edit, change, verdict: str, code: str | None
) -> None:
    """Verified, unverifiable, failed or attested: one of the four for every value, so a
    value the gates passed over shows as a count that does not add up."""
    if edit is not None:
        edit(project)
    report = _literature_report(project, change)
    counts = report.counts
    verdicts = ("verified", "unverifiable", "failed", "attested")
    assert sum(counts[f"literature_{name}"] for name in verdicts) == counts[
        "literature_values"
    ], counts
    # The edited value, the first of the two ledger entries, is the one that moved.
    expected = {"literature_verified": 2, "literature_unverifiable": 0, "literature_failed": 0}
    if verdict != "literature_verified":
        expected["literature_verified"] = 1
        expected[verdict] = 1
    assert {name: counts[name] for name in expected} == expected, counts
    if code is not None:
        assert code in codes(report), report.render(project)


# ------------------------------------------------------- a P worked out from its statistic
# A statistic and a P that the analysis did not make agree: typed, quoted from a source, or
# bound from two keys. G2 sees two numbers, each of which passed.


def _recomputed(root: Path):
    from manuscript_guard.gates import check_recomputed

    project, _ = load_project(root)
    namespace, results, _literature, _ = load_namespace(project)
    return check_recomputed(project, namespace, results)


def _recomputed_codes(root: Path, sentence: str) -> list[str]:
    main = main_md(root)
    main.write_text(main.read_text(encoding="utf-8") + "\n" + sentence + "\n", encoding="utf-8")
    return [f.code for f in _recomputed(root).findings]


def _emitted(root: Path, **displays: str) -> None:
    """Values in the example's results, each with the display given, as an analysis would
    emit them."""
    fragment = next((root / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    for key, display in displays.items():
        digits = len(display.partition(".")[2])
        value = {"value": float(display), "display": display, "digits": digits}
        document["values"][key.replace("__", ".")] = value
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


@pytest.mark.parametrize(
    ("sentence", "found"),
    [
        ("Earlier work found t(23) = 2.45, p = .022 [@fictionalHepaticCohort2021].", []),
        ("Earlier work found t(23) = 2.45, p = .041 [@fictionalHepaticCohort2021].",
         ["p-inconsistent"]),
        ("Earlier work found t(23) = 2.45, p = .40 [@fictionalHepaticCohort2021].",
         ["p-decision-error"]),
        ("The arms differed, *F*(2, 45) = 3.21, *P* = 0.30.", ["p-decision-error"]),
        ("The arms differed, \N{GREEK SMALL LETTER CHI}^2^(1) = 0.5, *P* \\< 0.05.",
         ["p-decision-error"]),
        ("The arms differed, z = 3.30, P = 0.01.", ["p-inconsistent"]),
        ("A one-sided t(23) = 2.45, p = .011, as planned.", []),
        ("<!-- t(23) = 2.45, p = .40 -->", []),
    ],
)
def test_a_p_that_does_not_follow_from_its_statistic_is_found(
    project: Path, sentence: str, found: list[str]
) -> None:
    assert _recomputed_codes(project, sentence) == found


def test_a_statistic_and_a_p_bound_from_two_analyses_are_found(project: Path) -> None:
    """The crude t beside the adjusted P: each bound, each passed by G2, and no gate saw
    that they disagree."""
    _emitted(project, crude__t="2.45", adjusted__p="0.30")
    sentence = "The groups differed, t(23) = {{results.crude.t}}, p = {{results.adjusted.p}}."
    assert _recomputed_codes(project, sentence) == ["p-decision-error"]


def test_a_p_is_judged_at_the_alpha_the_analysis_emits(project: Path) -> None:
    """t(23) = 1.90 gives 0.070: below an alpha of 0.10, as the P of .03 printed beside it
    is, so the two disagree and no decision does."""
    sentence = "The groups differed, t(23) = 1.90, p = .03."
    assert _recomputed_codes(project, sentence) == ["p-decision-error"]
    _emitted(project, param__alpha="0.10")
    assert [f.code for f in _recomputed(project).findings] == ["p-inconsistent"]


def test_a_quote_whose_statistic_and_p_disagree_is_found(project: Path) -> None:
    """The source's own numbers disagree, so the value taken from them may be the wrong
    one of the two."""
    said = (
        "The crude incidence of drug-induced hepatic injury was 14 per 100 000 "
        "person-years, t(23) = 2.45, p = .40."
    )
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text(source.read_text(encoding="utf-8") + "\n" + said + "\n", encoding="utf-8")
    path = project / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"][0]["quote"] = said
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = _literature_report(project)
    assert [f.code for f in report.findings if f.code == "quote-p-inconsistent"] == [
        "quote-p-inconsistent"
    ]
    assert report.counts["literature_verified"] == 2


def test_a_quote_two_values_rest_on_is_judged_once(project: Path) -> None:
    """Round 1 of #285: one quote backing two values reported its statistic and P twice,
    once under each key. The source is the same sentence either way."""
    said = (
        "The crude incidence of drug-induced hepatic injury was 14 per 100 000 "
        "person-years in 2019, t(23) = 2.45, p = .40."
    )
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text(source.read_text(encoding="utf-8") + "\n" + said + "\n", encoding="utf-8")
    path = project / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"][0]["quote"] = said
    second = dict(document["entries"][0], key="background.reported_year", value=2019,
                  display="2019")  # fmt: skip
    second.pop("unit", None)
    document["entries"].append(second)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = _literature_report(project)
    assert report.counts["literature_verified"] == 3
    found = [f for f in report.findings if f.code == "quote-p-inconsistent"]
    assert len(found) == 1, [f.message for f in found]


def test_an_audited_paper_s_p_that_does_not_follow_is_listed_apart(tmp_path: Path) -> None:
    """`audit` reads a paper that was never bound, and needs no outputs for this."""
    from manuscript_guard.audit import audit, measure_discrimination, render
    from manuscript_guard.cli import main

    paper = tmp_path / "paper.md"
    paper.write_text("The groups differed, t = 2.45, df = 23, p = .40.\n", encoding="utf-8")
    outputs = tmp_path / "outputs.csv"
    outputs.write_text("value\n23\n2.45\n0.40\n", encoding="utf-8")
    report = audit([paper], [outputs])
    assert [(d.line, d.context) for d in report.disagreements] == [
        (1, "t = 2.45, df = 23, p = .40")
    ]
    shown = render(report, measure_discrimination(report.backing_values))
    assert "DO NOT FIT THE ONES BESIDE THEM" in shown
    assert "on the other side of 0.05" in shown
    # Every number is in the outputs, and --strict counts only those.
    assert main(["audit", str(paper), "--against", str(outputs), "--strict"]) == 0


# ------------------------------------------------- an estimate, its interval and its P
# A ratio's interval is symmetric on the log scale, and excludes its null exactly when the P
# beside it is below one less its level. Numbers typed, quoted, or bound from two keys can
# break either, and G2 sees each number pass.


@pytest.mark.parametrize(
    ("sentence", "found"),
    [
        ("The odds ratio was 2.6 (95% CI 2.1 to 3.2), P = 0.001.", []),
        ("The odds ratio was 2.6 (95% CI 1.2 to 3.2).", ["ratio-interval-asymmetric"]),
        ("The odds ratio was 1.9 (95% CI 1.2 to 3.0), P = 0.40.", ["p-against-interval"]),
        ("The mean difference was 0.4 (95% CI -0.2 to 1.0), P = 0.001.",
         ["p-against-interval"]),
        ("The adjusted odds ratio was 1.9 (95% CI 1.2 to 3.0), P = 0.40.",
         ["p-against-interval"]),
        ("The odds ratio was 2.6 (95% profile-likelihood CI 1.2 to 3.2).", []),
        ("The odds ratio was 1.9 (95% CI 1.2 to 3.0), Bonferroni-adjusted P = 0.40.", []),
        ("The odds ratio was 1.9 (95% CI 1.2 to 3.0) in men and 1.1 (95% CI 0.8 to 1.5) in "
         "women, P = 0.40 for interaction.", []),
        ("The risk ratio was 1.50 (90% CI 1.05 to 2.14), P = 0.07.", []),
        ("<!-- The odds ratio was 2.6 (95% CI 1.2 to 3.2). -->", []),
        # Round 1 of #300: a bound transposed past its estimate, and a ratio named after
        # the word "difference".
        ("The odds ratio was 2.6 (95% CI 2.1 to 2.3).", ["interval-excludes-estimate"]),
        ("The mean difference was 1.4 (95% CI 0.2 to 0.9).", ["interval-excludes-estimate"]),
        ("No difference in mortality, HR 0.83 (95% CI 0.65 to 1.05), P = 0.13.", []),
    ],
)  # fmt: skip
def test_an_interval_that_does_not_fit_its_estimate_or_its_p_is_found(
    project: Path, sentence: str, found: list[str]
) -> None:
    assert _recomputed_codes(project, sentence) == found


def test_an_estimate_bound_from_one_analysis_and_its_interval_from_another_is_found(
    project: Path,
) -> None:
    """The crude estimate beside the adjusted interval, and the crude P beside the adjusted
    estimate: each number bound, each passed by G2, and no gate saw that they disagree."""
    _emitted(
        project, crude__or="2.80", crude__p="0.080", adjusted__or="2.23",
        adjusted__low="1.60", adjusted__high="3.10",
    )  # fmt: skip
    interval = "(95% CI {{results.adjusted.low}} to {{results.adjusted.high}})"
    crude = "The odds ratio was {{results.crude.or}} " + interval + "."
    assert _recomputed_codes(project, crude) == ["ratio-interval-asymmetric"]
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(text.replace("{{results.crude.or}}", "{{results.adjusted.or}}"), "utf-8")
    adjusted = "The adjusted odds ratio was {{results.adjusted.or}} " + interval
    sentence = adjusted + ", P = {{results.crude.p}}."
    assert _recomputed_codes(project, sentence) == ["p-against-interval"]
    assert _recomputed(project).counts["printed_intervals_read"] == 5


@pytest.mark.parametrize(
    ("interval", "code"),
    [
        ("rate ratio 1.9, 95% CI 1.2-3.0, P = 0.40", "quote-p-against-interval"),
        ("rate ratio 2.6, 95% CI 1.2-3.2", "quote-interval-asymmetric"),
        # Round 2 of #300: each code G7 says of a quote has a case.
        ("rate ratio 2.6, 95% CI 2.1-2.3", "quote-interval-excludes-estimate"),
    ],
)
def test_a_quote_whose_interval_does_not_fit_its_p_is_found(
    project: Path, interval: str, code: str
) -> None:
    """The source's own numbers disagree, so the value taken from them may be the wrong
    one."""
    said = (
        "The crude incidence of drug-induced hepatic injury was 14 per 100 000 "
        f"person-years ({interval})."
    )
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text(source.read_text(encoding="utf-8") + "\n" + said + "\n", encoding="utf-8")
    path = project / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"][0]["quote"] = said
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = _literature_report(project)
    assert [f.code for f in report.findings if f.code.startswith("quote-")] == [code]
    assert report.counts["literature_verified"] == 2


def test_an_audited_paper_s_interval_that_does_not_fit_is_listed_apart(tmp_path: Path) -> None:
    """`audit` reads a paper that was never bound, and needs no outputs for this."""
    from manuscript_guard.audit import audit

    paper = tmp_path / "paper.md"
    paper.write_text(
        "The odds ratio was 2.6 (95% CI 1.2 to 3.2).\n\n"
        "The hazard ratio was 1.9 (95% CI 1.2 to 3.0), P = 0.40.\n\n"
        "The risk ratio was 2.6 (95% CI 2.1 to 2.3).\n",
        encoding="utf-8",
    )
    report = audit([paper], [])
    assert [(d.line, d.context) for d in report.disagreements] == [
        (1, "odds ratio was 2.6 (95% CI 1.2 to 3.2"),
        (3, "hazard ratio was 1.9 (95% CI 1.2 to 3.0), P = 0.40"),
        (5, "risk ratio was 2.6 (95% CI 2.1 to 2.3"),
    ]
    assert "outside its own interval" in report.disagreements[2].message
    assert "arms differ" in report.disagreements[0].message
    assert "excludes 1, and P = 0.40 is above 0.05" in report.disagreements[1].message


#: A table 1 with four shares off their denominators: a count copied from another row, one
#: under a label with a footnote marker, one of its own denominator, and one among the
#: categories of a characteristic whose shares add up to 100. And a mean (SD) that says %.
_SHARES_OFF = (
    "Table 1. Characteristics.\n\n"
    "| Characteristic | Exposed (n = 1200) | Unexposed (N=3,400) |\n"
    "|---|---|---|\n"
    "| HbA1c, %, mean (SD) | 54 (12) | 55 (11) |\n"
    "| Female sex, n (%) | 640 (53.3) | 1,800 (52.9) |\n"
    "| Diabetes, n (%) | 300 (26.0) | 700 (20.6) |\n"
    "| Smoking^a^, n (%) | 200 (17.5) | 500 (14.7) |\n"
    "| Stroke, n/N (%) | 12/40 (35.0) | 9/45 (20.0) |\n"
    "| Region | | |\n"
    "| North | 600 (50.0) | 1,700 (50.0) |\n"
    "| South | 600 (50.0) | 1,800 (50.0) |\n"
)


def test_an_audited_table_s_n_percent_off_its_denominator_is_listed_apart(
    tmp_path: Path,
) -> None:
    """Item 19.4: an n (%) in a table is held to the denominator the table names, its own or
    its column header's n, within half a unit of the share's last place. It needs no
    outputs, and is listed with the P and the intervals that do not fit. The share says
    which denominators it would fit, and a row whose label carries a footnote marker says
    it is uncertain: a note may give it another."""
    from manuscript_guard.audit import audit, measure_discrimination, render

    paper = tmp_path / "paper.md"
    paper.write_text(_SHARES_OFF, encoding="utf-8")
    report = audit([paper], [])
    assert [(d.line, d.message) for d in report.disagreements] == [
        (7, "n (%) 300 (26.0): 300 of 1200 is 25.00%, not 26.0; 26.0% is 300 of 1152 to 1156"),
        (8, "n (%) 200 (17.5): 200 of 1200 is 16.67%, not 17.5; 17.5% is 200 of 1140 to 1146 "
            "(uncertain: the row's label carries a footnote marker, and a note may give it "
            "another denominator)"),
        (9, "n (%) 12/40 (35.0): 12 of 40 is 30.00%, not 35.0"),
        (12, "n (%) 1,800 (50.0): 1800 of 3400 is 52.94%, not 50.0; 50.0% is 1800 of 3597 "
             "to 3603"),
    ]  # fmt: skip
    assert report.disagreements[0].context == "Diabetes, n (%) | 300 (26.0) | 700 (20.6)"
    shown = render(report, measure_discrimination(set()))
    assert "an n (%) and its denominator" in shown
    assert "line 12: n (%) 1,800 (50.0)" in shown


def test_a_header_that_names_its_n_before_a_comma_gives_its_denominator(
    tmp_path: Path,
) -> None:
    """Round 1 of #314: "Exposed, n = 1200, n (%)" named no denominator, since a count was
    not read where a comma followed it, and every share under it was held to nothing."""
    from manuscript_guard.audit import audit

    paper = tmp_path / "paper.md"
    paper.write_text("| | Exposed, n = 1,200, n (%) |\n|---|---|\n"
                     "| Diabetes | 300 (26.0) |\n", encoding="utf-8")  # fmt: skip
    [said] = audit([paper], []).disagreements
    assert said.message.startswith("n (%) 300 (26.0): 300 of 1200 is 25.00%")


@pytest.mark.parametrize(
    ("written", "listed"),
    [
        # A characteristic's categories with its P value on its label row (round 2 of #314).
        ("| | A (n = 1200) | B (n = 3400) | P |\n|---|---|---|---|\n| Sex | | | 0.12 |\n"
         "| Male | 604 (53.3) | 1800 (52.9) | |\n| Female | 560 (46.7) | 1600 (47.1) | |\n",
         "n (%) 604 (53.3): 604 of 1200 is 50.33%"),
        # A yes/no characteristic whose label ends "(%)" (round 2 of #314).
        ("| | A (n = 1200), n (%) |\n|---|---|\n| Male sex (%) | 640 (58.0%) |\n",
         "n (%) 640 (58.0%): 640 of 1200 is 53.33%"),
    ],
)  # fmt: skip
def test_an_n_percent_off_its_denominator_is_listed_in_a_shape_review_found(
    tmp_path: Path, written: str, listed: str
) -> None:
    from manuscript_guard.audit import audit

    paper = tmp_path / "paper.md"
    paper.write_text(written, encoding="utf-8")
    [said] = audit([paper], []).disagreements
    assert said.message.startswith(listed)


def test_categories_run_on_into_the_next_characteristic_are_not_read(tmp_path: Path) -> None:
    """A known gap, pinned (round 3 of #314): with nothing but their sum to say they are
    shares, categories followed in the same run by the next characteristic are not read,
    and 650 (50.0), which is 54.17% of 1200, is not listed. Without the Diabetes row it is."""
    from manuscript_guard.audit import audit

    paper = tmp_path / "paper.md"
    table = ("| | Overall (n = 1200) |\n|---|---|\n| Smoking status | |\n"
             "| Never | 650 (50.0) |\n| Former | 400 (33.3) |\n"
             "| Current | 200 (16.7) |\n")  # fmt: skip
    paper.write_text(table + "| Diabetes | 300 (25.0) |\n", encoding="utf-8")
    assert audit([paper], []).disagreements == []
    paper.write_text(table, encoding="utf-8")
    assert [d.line for d in audit([paper], []).disagreements] == [4]


def _ledger_mean(project: Path, printed: str, declared: dict | None) -> None:
    """A third ledger entry, a mean of answers as the source prints it, with what the
    ledger says it is a mean of."""
    said = f"The 28 patients interviewed rated their pain {printed} on average."
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text(source.read_text(encoding="utf-8") + "\n" + said + "\n", encoding="utf-8")
    path = project / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = {
        "key": "background.pain_mean", "value": float(printed), "display": printed,
        "citekey": "fictionalHepaticCohort2021", "depth": "full-text",
        "source_file": "sources/fictionalHepaticCohort2021.txt", "locator": "Results",
        "quote": said,
    }  # fmt: skip
    if declared is not None:
        entry["mean_of_whole_numbers"] = declared
    document["entries"].append(entry)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


@pytest.mark.parametrize(
    ("printed", "declared", "said"),
    [
        # 3.47 is no whole total over 28: 97 and 98 give 3.46 and 3.50.
        ("3.47", {"n": 28}, ["quote-mean-not-possible"]),
        ("3.46", {"n": 28}, []),
        # 2.17 is no total over 3, and 13 over 6 when each of 3 answered 2 items.
        ("2.17", {"n": 3}, ["quote-mean-not-possible"]),
        ("2.17", {"n": 3, "items": 2}, []),
        # Any mean printed to two places is possible for 100 or more, and for 96, whose
        # totals and the ties between them print every one (round 1 of #331).
        ("3.47", {"n": 150}, ["quote-mean-not-assessable"]),
        ("3.47", {"n": 96}, ["quote-mean-not-assessable"]),
        ("3.47", {"n": 95}, []),
        ("3.47", None, []),
        # A count YAML writes "28.0" is 28 (round 1 of #331: the float raised).
        ("3.47", {"n": 28.0}, ["quote-mean-not-possible"]),
    ],
)  # fmt: skip
def test_a_ledger_mean_of_whole_numbers_is_held_to_its_n(
    project: Path, printed: str, declared: dict | None, said: list[str]
) -> None:
    """Item 19.5: a value the ledger says is a mean of whole numbers, of n people answering
    a number of items each, can be printed only as a whole total over their product. One
    that cannot is a warning, and a mean whose n is too large to tell is a note."""
    _ledger_mean(project, printed, declared)
    report = _literature_report(project)
    codes = [f.code for f in report.findings if f.code.startswith("quote-mean")]
    assert codes == said
    assert report.counts["literature_verified"] == 3
    if said == ["quote-mean-not-possible"] and declared == {"n": 28}:
        [finding] = [f for f in report.findings if f.code == "quote-mean-not-possible"]
        assert finding.severity == "warn"
        assert finding.message == (
            "background.pain_mean: in the source, 3.47 cannot be the mean of 28 whole "
            "numbers: the totals either side, 97 and 98 over 28, give 3.46 and 3.50; it can "
            "be the mean of 19 or 30 whole numbers"
        )


def test_the_n_a_mean_fits_counts_one_at_which_every_mean_does() -> None:
    """Round 2 of #331: 3.50 is no mean of 97 whole numbers but is 336 over 96, at which
    every mean printed to two places is possible; the message skipped 96 and named 94."""
    from manuscript_guard.stats.granularity import described

    assert described("3.50", 97).endswith("it can be the mean of 96 or 98 whole numbers")


def test_a_ledger_mean_of_whole_numbers_needs_a_count(project: Path) -> None:
    """An n of none is refused by the schema, not read as a mean of nothing."""
    _ledger_mean(project, "3.47", {"n": 0})
    assert "schema-violation" in [f.code for f in _literature_report(project).findings]


def test_a_ledger_mean_printed_with_more_than_itself_says_how_to_test_it(
    project: Path,
) -> None:
    """Round 1 of #331: a display that is not a plain decimal, "3.47 (1.20)", is not
    assessable, and the note said there was nothing to do; the mean can be tested if it is
    recorded alone."""
    said = "The 28 patients interviewed rated their pain 3.47 (1.20) on average."
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text(source.read_text(encoding="utf-8") + "\n" + said + "\n", encoding="utf-8")
    path = project / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["entries"].append({
        "key": "background.pain_mean", "value": "3.47 (1.20)", "display": "3.47 (1.20)",
        "citekey": "fictionalHepaticCohort2021", "depth": "full-text",
        "source_file": "sources/fictionalHepaticCohort2021.txt", "locator": "Results",
        "quote": said, "mean_of_whole_numbers": {"n": 28},
    })  # fmt: skip
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    [note] = [f for f in _literature_report(project).findings
              if f.code == "quote-mean-not-assessable"]  # fmt: skip
    assert "record the mean alone" in note.hint


def test_not_assessable_is_worked_out_as_the_search_finds_it() -> None:
    """Round 2 of #331: a mean is not assessable where every mean printed to its places is
    possible for N. That is worked out, from the ties between totals, since the search took
    seconds at four places; here the two agree for every N at one, two and three places."""
    import math
    from fractions import Fraction

    from manuscript_guard.stats import granularity

    def searched(count: int, places: int) -> bool:
        scale = 10**places
        half = Fraction(1, 2 * scale)
        return count < scale and any(
            math.ceil((Fraction(k, scale) - half) * count)
            > math.floor((Fraction(k, scale) + half) * count)
            for k in range(scale)
        )

    for places in (1, 2, 3):
        counts = range(1, 10**places + 3) if places < 3 else range(480, 1003)
        for count in counts:
            assert granularity._some_mean_is_none(count, places) is searched(count, places), (
                count, places)  # fmt: skip


def test_a_mean_without_a_nought_and_a_mean_under_a_body_row_s_n_are_read() -> None:
    """Round 1 of #331: ".47 (.12)" was not read. Round 2: a row of means whose other cell
    names an n set it for the rows below, and their means were not uncertain."""
    from manuscript_guard.stats.granularity import table_means
    from manuscript_guard.text.tables import markdown_tables

    text = ("| | Treated (n = 30) | Note |\n|---|---|---|\n"
            "| Pain at 12 weeks | .47 (.12) | n = 25 |\n"
            "| Pain at 24 weeks | 3.0 (1.0) | 3.1 (0.9) |\n")  # fmt: skip
    [table] = markdown_tables(text)
    found = [(m.mean, m.n, m.uncertain) for m in table_means(table, ("pain",))]
    assert found[0] == (".47", 30, None)
    assert found[1][:2] == ("3.0", 30) and found[1][2] is None
    assert found[2][:2] == ("3.1", 25) and "row of means" in found[2][2]


@pytest.mark.parametrize("row", [
    "| Pain at 12 weeks | 3.1 (1.0), n = 25 |",
    "| Age, years | 45.1 (9.0), n = 25 |",
    "| Pain at 12 weeks | 3.1 (1.0) (n = 25) |",
])  # fmt: skip
def test_a_mean_that_names_its_n_makes_the_means_below_it_uncertain(row: str) -> None:
    """Round 1 of #336: a cell that is a mean and its n set the n for the column below,
    and those means were held to it as certain, where its row had no other mean or was not
    a row read for means at all."""
    from manuscript_guard.stats.granularity import table_means
    from manuscript_guard.text.tables import markdown_tables

    [table] = markdown_tables(f"| | Treated (n = 30) |\n|---|---|\n{row}\n| Pain | 3.0 (1.0) |\n")
    below = table_means(table, ("pain",))[-1]
    assert (below.mean, below.n) == ("3.0", 25)
    assert below.uncertain and "row of means" in below.uncertain


@pytest.mark.parametrize("header", ["| | 2019 (n = 120) |", "| | 12 (n = 120) |",
                                    "| | 0.5 (n = 120) |"])  # fmt: skip
def test_a_year_or_a_count_beside_an_n_is_a_header_not_a_mean(header: str) -> None:
    """Round 2 of #336: a header's year, or a count, with an n beside it was taken for a
    mean naming its n, and the means below it were called uncertain."""
    from manuscript_guard.stats.granularity import table_means
    from manuscript_guard.text.tables import markdown_tables

    [table] = markdown_tables(f"{header}\n|---|---|\n| Pain | 3.0 (1.0) |\n")
    [below] = table_means(table, ("pain",))
    assert (below.mean, below.n, below.uncertain) == ("3.0", 120, None)


def test_a_header_of_two_rows_marks_the_means_below_uncertain() -> None:
    """A Known gap (the post-budget round of #336): only the first row is a header, so a
    second header row, "0.5 (n = 40)", is taken for a mean naming its n. The n is right;
    the means below are called uncertain."""
    from manuscript_guard.stats.granularity import table_means
    from manuscript_guard.text.tables import markdown_tables

    [table] = markdown_tables("| | Dose (mg) |\n|---|---|\n| | 0.5 (n = 40) |\n"
                              "| Pain | 3.0 (1.0) |\n")  # fmt: skip
    [below] = table_means(table, ("pain",))
    assert (below.mean, below.n) == ("3.0", 40) and "row of means" in below.uncertain


_WHOLE_NUMBERS = (
    "# Results\n\n"
    "| Characteristic | Treated (n = 28) | Control (n = 140) |\n"
    "|---|---|---|\n"
    "| Pain score, mean (SD) | 3.47 (1.20) | 3.46 (1.10) |\n"
    "| Days in hospital^a^ | 2.50 \N{PLUS-MINUS SIGN} 1.1 | 4.1 |\n"
    "| Visits, mean | 1.75 | 2.13 |\n"
    "| Age, years | 45.37 (12.1) | 44.2 (11.0) |\n"
)


def test_an_audited_mean_of_whole_numbers_is_held_to_its_column_s_n(tmp_path: Path) -> None:
    """Item 19.5: `audit --whole-numbers` names the rows whose cells are means of whole
    numbers, and each is held to its column header's n. A mean no whole total over n gives
    is listed with the numbers that do not fit; a mean whose n is too large for its places
    is listed apart, as not assessable; a row not named is not read, though its mean of 28
    would not fit; and a label that names no row is said."""
    from manuscript_guard.audit import audit, measure_discrimination, render

    paper = tmp_path / "paper.md"
    paper.write_text(_WHOLE_NUMBERS, encoding="utf-8")
    named = ("pain score", "Days in hospital", "visits", "PHQ-9")
    report = audit([paper], [], whole_numbers=named)
    assert [(d.line, d.message) for d in report.disagreements] == [
        (5, "3.47 cannot be the mean of 28 whole numbers: the totals either side, 97 and 98 "
            "over 28, give 3.46 and 3.50; it can be the mean of 19 or 30 whole numbers"),
    ]  # fmt: skip
    assert report.means_read == 6
    assert [(d.line, d.message) for d in report.means_not_assessable] == [
        (5, "3.46 (1.10) of n = 140"),
        (6, "4.1 of n = 140 (uncertain: the row's label carries a footnote marker, and a "
            "note may give it another n)"),
        (7, "2.13 of n = 140"),
    ]  # fmt: skip
    assert report.whole_numbers_unfound == ["PHQ-9"]
    shown = render(report, measure_discrimination(set()))
    assert "a mean of whole numbers and its n" in shown
    assert "Means of whole numbers (--whole-numbers): 6 read in the rows named, 3 not " in shown
    assert "--whole-numbers 'PHQ-9': no mean was read in a row whose label holds it" in shown


def test_a_header_whose_first_cell_holds_a_named_label_still_gives_its_n(
    tmp_path: Path,
) -> None:
    """Round 1 of #331: a table about one scale headed by its name read the header as a row
    of means, never read its n, and read no mean under it, saying nothing."""
    from manuscript_guard.audit import audit

    paper = tmp_path / "paper.md"
    paper.write_text("| Pain score | Treated (n = 28) | Control (n = 30) |\n|---|---|---|\n"
                     "| Pain score at baseline | 3.47 (1.2) | 3.50 (1.1) |\n",
                     encoding="utf-8")  # fmt: skip
    report = audit([paper], [], whole_numbers=("pain score",))
    assert report.means_read == 2
    assert [d.line for d in report.disagreements] == [3]
    assert report.whole_numbers_unfound == []


def test_a_named_label_under_which_no_mean_is_read_is_said(tmp_path: Path) -> None:
    """Round 1 of #331: a label that names rows, none of whose means is read (their header
    names no n), is said, as one that names no row is."""
    from manuscript_guard.audit import audit, measure_discrimination, render

    paper = tmp_path / "paper.md"
    paper.write_text("| Outcome | Cases | Controls |\n|---|---|---|\n"
                     "| Visits, mean | 3.47 | 3.50 |\n", encoding="utf-8")  # fmt: skip
    report = audit([paper], [], whole_numbers=("visits",))
    assert report.means_read == 0
    assert report.whole_numbers_unfound == ["visits"]
    assert "--whole-numbers 'visits': no mean was read in a row whose label holds it" in render(
        report, measure_discrimination(set())
    )


def test_an_audit_without_whole_numbers_reads_no_mean(tmp_path: Path) -> None:
    """No row is taken for means of whole numbers unless the auditor names it: 3.47 of 28 is
    not listed, and the report says nothing of means."""
    from manuscript_guard.audit import audit, measure_discrimination, render

    paper = tmp_path / "paper.md"
    paper.write_text(_WHOLE_NUMBERS, encoding="utf-8")
    report = audit([paper], [])
    assert report.disagreements == [] and report.means_read == 0
    assert "Means of whole numbers" not in render(report, measure_discrimination(set()))


def test_audit_whole_numbers_on_the_command_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from manuscript_guard.cli import main

    paper = tmp_path / "paper.md"
    paper.write_text(_WHOLE_NUMBERS, encoding="utf-8")
    outputs = tmp_path / "outputs.json"
    outputs.write_text('{"n": 28}', encoding="utf-8")
    main(["audit", str(paper), "--against", str(outputs), "--whole-numbers", "pain score"])
    shown = capsys.readouterr().out
    assert "line 5: 3.47 cannot be the mean of 28 whole numbers" in shown
    assert "2 read in the rows named" in shown


def _cell(text: str, *, span: int = 1) -> str:
    props = f'<w:tcPr><w:gridSpan w:val="{span}"/></w:tcPr>' if span > 1 else ""
    return f"<w:tc>{props}<w:p>{text}</w:p></w:tc>"


@pytest.mark.parametrize(("value", "span"), [("3", 3), ("63", 63), ("999999999", 63),
                                              ("0", 1), ("x", 1)])  # fmt: skip
def test_a_cell_spans_no_more_columns_than_word_allows(value: str, span: int) -> None:
    """Round 1 of #314: a span had no upper bound, and a crafted gridSpan of 999999999 built
    a string of marks of about a gigabyte. Word allows a table 63 columns."""
    import xml.etree.ElementTree as ET

    from manuscript_guard.text import docx

    namespace = docx.W.strip("{}")
    cell = ET.fromstring(f'<w:tc xmlns:w="{namespace}"><w:tcPr><w:gridSpan w:val="{value}"/>'
                         f"</w:tcPr></w:tc>")  # fmt: skip
    assert docx._span(cell) == span


def _run(text: str, *, raised: bool = False) -> str:
    props = '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>' if raised else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r>'


def test_an_n_percent_in_a_word_table_is_read_by_its_row_and_column(tmp_path: Path) -> None:
    """Item 19.4: in a .docx each cell is a line of its own, so a table is read as Word lays
    it out, rows of cells, a header cell spanning two columns counted as each. A footnote
    marker typed as superscript, or a footnote's own reference, makes the row uncertain.
    The text the rest of the audit reads is what it was: the marks go."""
    from manuscript_guard.audit import audit
    from manuscript_guard.text.docx import read_docx_text

    def row(*cells: str) -> str:
        return "<w:tr>" + "".join(cells) + "</w:tr>"

    def plain(*texts: str) -> list[str]:
        return [_cell(_run(text)) for text in texts]

    table = "<w:tbl>" + "".join([
        row(_cell(""), _cell(_run("Arms (n = 900)"), span=2)),
        row(*plain("Characteristic", "Exposed", "Unexposed")),
        row(*plain("Diabetes, n (%)", "300 (33.3)", "100 (11.0)")),
        row(_cell(_run("Smoking") + _run("a", raised=True) + _run(", n (%)")),
            *plain("90 (10.0)", "95 (11.0)")),
        row(_cell(_run("Stroke, n (%)") + '<w:r><w:footnoteReference w:id="2"/></w:r>'),
            *plain("9 (1.0)", "18 (3.0)")),
    ]) + "</w:tbl>"  # fmt: skip
    paper = _docx(tmp_path / "paper.docx", _p("Results") + table + _p("After the table."))
    said = audit([paper], []).disagreements
    assert [d.message.split(";")[0] for d in said] == [
        "n (%) 100 (11.0): 100 of 900 is 11.11%, not 11.0",
        "n (%) 95 (11.0): 95 of 900 is 10.56%, not 11.0",
        "n (%) 18 (3.0): 18 of 900 is 2.00%, not 3.0",
    ]
    assert ["uncertain" in d.message for d in said] == [False, True, True]
    assert said[1].context == "Smoking^a^, n (%) | 90 (10.0) | 95 (11.0)"
    body = read_docx_text(paper).body
    assert "\nSmokinga, n (%) | \n90 (10.0) | \n" in body
    assert not any(chr(mark) in body for mark in range(0x19, 0x20))


@pytest.mark.parametrize(
    "written",
    [
        # No denominator anywhere in the table.
        "| Characteristic | Exposed | Unexposed |\n|---|---|---|\n"
        "| Diabetes, n (%) | 300 (26.0) | 7 (2.0) |\n",
        # A label that names a median, although it says %.
        "| | A (n = 100) |\n|---|---|\n| Ejection fraction, %, median (IQR) | 55 (15) |\n",
        # A column whose header names a mean, although it says n (%).
        "| | Mean (SD) or n (%), n = 100 |\n|---|---|\n| Visits | 4 (2) |\n",
        # Nothing says the numbers in brackets are shares, and they do not add up to 100.
        "| | A (n = 50) |\n|---|---|\n| Visits | 3 (2) |\n| Calls | 5 (1) |\n",
        # Shares of the row's own total.
        "| | A (n = 100) | B (n = 200) |\n|---|---|---|\n"
        "| Exposed, n (%) | 30 (60.0) | 20 (40.0) |\n",
        # A "%" that is a unit, its mean (SD) printed as whole numbers (round 1 of #314).
        "| | A (n = 1200) | B (n = 3400) |\n|---|---|---|\n"
        "| Oxygen saturation, % | 96 (3) | 95 (4) |\n| LVEF, % | 55 (10) | 54 (11) |\n",
        # A unit in percent under a header that says n (%): a measure all the same.
        "| | A (n = 1200), n (%) |\n|---|---|\n| HbA1c (%) | 7 (1) |\n"
        "| Diabetes, n (%) | 300 (25.0) |\n",
        # A whole-number mean whose running sum with the shares passes through 100, under
        # a section label and a header that does not say n (%) (round 3 of #314).
        "| | Overall (n = 1200) |\n|---|---|\n| Baseline | |\n| Age, years | 62 (11) |\n"
        "| Female sex | 540 (45.0) |\n| Hypertension | 528 (44.0) |\n"
        "| Diabetes | 216 (18.0) |\n",
        # The subtypes again, the next characteristic straight after them (round 2).
        "| | A (n = 1200), n (%) | B (n = 3400), n (%) |\n|---|---|---|\n"
        "| Diabetes, n (%) | 300 (25.0) | 700 (20.6) |\n| Diabetes type | | |\n"
        "| Type 1 | 30 (10.0) | 70 (10.0) |\n| Type 2 | 270 (90.0) | 630 (90.0) |\n"
        "| Hypertension, n (%) | 500 (41.7) | 1400 (41.2) |\n",
        # And with a P value beside their label (round 2).
        "| | A (n = 1200) | B (n = 3400) | P |\n|---|---|---|---|\n"
        "| Diabetes, n (%) | 300 (25.0) | 700 (20.6) | 0.01 |\n"
        "| Diabetes type | | | 0.40 |\n| Type 1 | 30 (10.0) | 70 (10.0) | |\n"
        "| Type 2 | 270 (90.0) | 630 (90.0) | |\n",
        # The subtypes of another row, shares of it and not of the column (round 1 of #314).
        "| | A (n = 1200) | B (n = 3400) |\n|---|---|---|\n"
        "| Diabetes, n (%) | 300 (25.0) | 700 (20.6) |\n| Diabetes type | | |\n"
        "| Type 1 | 30 (10.0) | 70 (10.0) |\n| Type 2 | 270 (90.0) | 630 (90.0) |\n",
        # In a fenced listing.
        "```\n| | A (n = 1200) |\n|---|---|\n| Diabetes, n (%) | 300 (26.0) |\n```\n",
        # In the reference list.
        "Text.\n\n# References\n\n| | A (n = 1200) |\n|---|---|\n"
        "| Diabetes, n (%) | 300 (26.0) |\n",
        # In a sentence.
        "Diabetes was present in 300 (26.0%) of the 1200 exposed patients (n = 1200).\n",
    ],
)  # fmt: skip
def test_an_n_percent_held_to_nothing_is_not_listed(tmp_path: Path, written: str) -> None:
    """Item 19.4: only a column of shares with a denominator is held to it. Mean (SD) and
    median (IQR) never fire, a share of the row is not wrong, and a table that is not one,
    or not the paper's, is not read."""
    from manuscript_guard.audit import audit

    paper = tmp_path / "paper.md"
    paper.write_text(written, encoding="utf-8")
    assert audit([paper], []).disagreements == []


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ("drug-induced hepatic\n12\ninjury",
         "the source has '12' between 'hepatic' and 'injury' (line 13): numbers"),
        ("drug-induced hepa-\ntic injury", "'hepa' and 'tic' are one word, split by a hyphen"),
        ("hepatic injury", "the source has 'drug-induced' between 'of' and 'hepatic' (line 12)"),
        ("drug-induced liver injury",
         "after 'induced' the quote has 'hepatic', where the source has 'liver injury was'"),
        ("per 100\N{MIDDLE DOT}000",
         "between '100' and '000' (line 12) the source has '\N{MIDDLE DOT}' where the quote "
         "has ' '"),
    ],
)  # fmt: skip
def test_a_quote_not_in_its_source_says_what_stands_in_the_way(
    project: Path, written: str, said: str
) -> None:
    """Item 19: G7 fails a quote that is not in the source exactly, and used to say only
    that. The quote's words in order, with line numbers, a hyphen or a symbol between, are
    put right in a minute once that is named. The verdict is the same."""
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    text = source.read_text(encoding="utf-8")
    plain = "drug-induced hepatic injury" if "induced" in written else "per 100 000"
    if written == "hepatic injury":
        # The quote leaves a word out, rather than the source putting one in.
        path = project / "literature" / "ledger.yaml"
        ledger = path.read_text(encoding="utf-8")
        path.write_text(ledger.replace("of drug-induced hepatic", "of hepatic", 1), "utf-8")
    else:
        source.write_text(text.replace(plain, written, 1), encoding="utf-8")
    report = _literature_report(project)
    found = [f for f in report.findings if f.code == "quote-not-in-source"]
    assert len(found) == 1 and found[0].severity == "fail", report.render(project)
    assert said in found[0].message, found[0].message
    assert report.counts["literature_failed"] == 1


@pytest.mark.parametrize(
    ("quote", "short"),
    [
        ("A signal was detected for the class as a whole (ROR 2.6, 95% CI 2.1-3.2).", False),
        ("the class as a whole (ROR 2.6", False),
        # Round 1 of #278: the threshold itself, four words beside the value and three.
        ("as a whole (ROR 2.6", False),
        ("a whole (ROR 2.6", True),
        ("whole (ROR 2.6", True),
        ("ROR 2.6", True),
        ("2.6", True),
    ],
)
def test_a_quote_that_holds_little_more_than_its_value_is_said(
    project: Path, quote: str, short: bool
) -> None:
    """G7 holds the quote to the source and the value to the quote, so "2.6" quoted alone
    passed both: it proves only that those digits are somewhere in the source. A quote with
    fewer than four words beside its value is said; the value is still verified."""
    path = project / "literature" / "ledger.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = next(e for e in document["entries"] if e.get("display") == "2.6")
    entry["quote"] = quote
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    report = _literature_report(project)
    said = [f for f in report.findings if f.code == "quote-too-short"]
    assert [f.severity for f in said] == (["warn"] if short else []), report.render(project)
    assert report.counts["literature_verified"] == 2


# --------------------------------------------------------------------- the journal gate
# A journal's limits, sections and statements are about the document the editor receives,
# and the build strips every file's front matter before printing it.


def _journal(root: Path):
    from manuscript_guard.gates import check_journal

    project, _ = load_project(root)
    return check_journal(project)


# ---------------------------------------------------- the journal shortlist (item 49)


def _shortlist_said(root: Path) -> list[tuple[str, str]]:
    from manuscript_guard.gates.shortlist import check_shortlist

    project, _ = load_project(root)
    return [(f.code, f.severity) for f in check_shortlist(project).findings]


def _target_said(root: Path, table=None, **candidate) -> list[tuple[str, str]]:
    """G4 of the example's journal, shortlisted with these fields and looked up."""
    from test_journal_lookup import look_up_journals, write_shortlist

    write_shortlist(root, **candidate)
    look_up_journals(root, table)
    return _shortlist_said(root)


def test_a_shortlist_is_held_to_its_schema_as_a_warning(project: Path) -> None:
    from test_journal_lookup import write_shortlist

    assert _shortlist_said(project) == []
    write_shortlist(project, issn=["1111-111"])
    assert _shortlist_said(project) == [("shortlist-schema", "warn")]


def test_a_journal_chosen_from_outside_the_shortlist_is_said(project: Path) -> None:
    from test_journal_lookup import write_shortlist

    write_shortlist(project)
    path = project / "journals" / "shortlist.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["decision"]["journal"] = "A Journal Nobody Considered"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert ("shortlist-unknown-journal", "warn") in _shortlist_said(project)


def test_a_target_journal_not_indexed_for_medline_is_said(project: Path) -> None:
    """Item 49: a predatory journal is in neither MEDLINE nor DOAJ. The shortlist chose the
    example's journal, and the NLM Catalog said it is not currently indexed."""
    from test_journal_lookup import Table, esearch, esummary

    assert _target_said(project) == []
    assert _target_said(project, Table(esummary=esummary("N"))) == [
        ("journal-not-in-medline", "warn")
    ]
    assert _target_said(project, Table(esearch=esearch())) == [("journal-not-in-medline", "warn")]
    # The author's reason makes it a note that quotes them.
    said = _target_said(project, Table(esummary=esummary("N")),
                        outside_medline="A society journal of the field, indexed in Embase.")
    assert said == [("journal-not-in-medline", "info")]


def test_an_open_access_target_journal_not_in_doaj_is_said(project: Path) -> None:
    from test_journal_lookup import Table, listed

    assert _target_said(project, Table(doaj=listed(total=0))) == []
    assert _target_said(project, Table(doaj=listed(total=0)), open_access=True) == [
        ("journal-not-in-doaj", "warn")
    ]
    assert _target_said(project, open_access=True) == []


def test_what_is_not_known_of_the_target_journal_is_a_note(project: Path) -> None:
    """An answer that did not come, or a record missing or edited, is no evidence that the
    journal is outside MEDLINE: a note, and no warning."""
    from test_journal_lookup import ONLINE, Table, _json, esummary, write_shortlist

    said = _target_said(project, Table(esearch=_json(500, {})), open_access=True)
    assert said == [("journal-not-looked-up", "info")]
    write_shortlist(project)
    for record in (project / "journals" / "lookups").glob("*.yaml"):
        record.unlink()
    assert _shortlist_said(project) == [("journal-not-looked-up", "info")]
    _target_said(project, Table(esummary=esummary("N")))
    edited = project / "journals" / "lookups" / f"{ONLINE}.yaml"
    edited.write_text(edited.read_text(encoding="utf-8").replace("2026-10-17", "2026-10-18"),
                      encoding="utf-8")  # fmt: skip
    assert _shortlist_said(project) == [("journal-not-looked-up", "info")]


def test_the_target_journal_is_found_by_its_profile_its_name_or_the_decision(
    project: Path,
) -> None:
    from test_journal_lookup import Table, esummary

    no = Table(esummary=esummary("N"))
    assert _target_said(project, no, profile="another-profile") == [
        ("journal-not-in-medline", "warn")
    ]  # by the profile's name, "Journal of Demonstrative Pharmacoepidemiology"
    paper = project / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8").replace("target_journal: demo-journal\n",
                                                               ""), encoding="utf-8")  # fmt: skip
    assert _target_said(project, no) == [("journal-not-in-medline", "warn")]


def test_a_target_journal_none_of_the_candidates_is_said(project: Path) -> None:
    """Round 1 of #321: a candidate named otherwise than the target's profile, with no
    `profile:`, was not found, and G4 said nothing at all of whether the journal is indexed.
    The decision is not taken for the target: it may name another journal."""
    from test_journal_lookup import Table, esummary

    said = _target_said(project, Table(esummary=esummary("N")), journal="J Demonstr Pharm",
                        profile="another-profile")  # fmt: skip
    assert said == [("shortlist-unknown-journal", "warn"),
                    ("journal-target-not-shortlisted", "info")]  # fmt: skip


def test_the_warning_says_what_a_listing_is_evidence_of(project: Path) -> None:
    """Round 1 of #321: the hint said a predatory journal is never listed, which is not so,
    and called the target "the journal chosen" where the decision chose another."""
    from test_journal_lookup import Table, esummary

    from manuscript_guard.gates.shortlist import check_shortlist

    _target_said(project, Table(esummary=esummary("N")))
    [found] = [f for f in check_shortlist(load_project(project)[0]).findings
               if f.code == "journal-not-in-medline"]  # fmt: skip
    assert "the target journal" in found.message and "chosen" not in found.message
    assert "never" not in found.hint and "evidence" in found.hint


#: What G4 says of the figure files.
_ARTWORK_CODES = ("figure-format", "figure-resolution", "figure-height", "figure-file-size",
                  "figure-shrinks", "legend-words")  # fmt: skip


def _artwork_said(root: Path, side: dict | None = None, **rules) -> list[tuple[str, str]]:
    """G4 with the example's journal given these artwork rules, and the example's figure
    this sidecar: forest.png is 1950 by 660 pixels, drawn at 300 dpi, 165 mm wide."""
    profile = root / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["figures"] = {"source_url": "https://journal.example/artwork",
                           "read_on": "2026-10-15", "confirmed": True, **rules}  # fmt: skip
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    if side:
        sidecar = root / "figures" / "forest.guard.yaml"
        guard = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        sidecar.write_text(yaml.safe_dump({**guard, **side}, sort_keys=False), encoding="utf-8")
    report = _journal(root)
    assert report.ok or not [f for f in report.failures if f.code == "schema"], report.render()
    return [(f.code, f.severity) for f in report.findings if f.code in _ARTWORK_CODES]


@pytest.mark.parametrize(
    ("rules", "side", "said"),
    [
        # 1950 pixels over 89 mm is 556 dpi.
        ({"min_dpi": {"halftone": 600}, "widths_mm": [89, 183]}, None,
         [("figure-resolution", "warn")]),
        ({"min_dpi": {"halftone": 500}, "widths_mm": [89, 183]}, None, []),
        # Printed 60 mm wide, it is 825 dpi.
        ({"min_dpi": {"halftone": 600}, "widths_mm": [89]}, {"print_width_mm": 60}, []),
        ({"min_dpi": {"halftone": 300, "line_art": 1000}, "widths_mm": [89]},
         {"kind": "line_art"}, [("figure-resolution", "warn")]),
        ({"formats": ["tiff", "eps"]}, None, [("figure-format", "warn")]),
        ({"formats": ["tiff", "png"]}, None, []),
        # Round 1 of #291: a journal writes "jpg" or "tif" as often as "jpeg" or "tiff".
        ({"formats": ["tif", "jpg"]}, None, [("figure-format", "warn")]),
        ({"max_file_mb": 0.005}, None, [("figure-file-size", "warn")] * 2),
        # 89 mm wide, 660 / 1950 of that high: 30 mm.
        ({"max_height_mm": 20, "widths_mm": [89]}, None, [("figure-height", "warn")]),
        # Drawn 165 mm wide and printed 89: 10 pt prints at 5.4.
        ({"min_text_pt": 6, "widths_mm": [89]}, None, [("figure-shrinks", "warn")]),
        ({"min_text_pt": 5, "widths_mm": [89]}, None, []),
        ({"min_dpi": {"halftone": 600}, "widths_mm": [89], "applies_from": "acceptance"},
         None, [("figure-resolution", "info")]),
    ],
)
def test_a_figure_file_the_journal_would_refuse_is_a_warning(
    project: Path, rules: dict, side: dict | None, said: list
) -> None:
    """Item 17: resolution, format, size and height were free text in a profile's notes,
    and the first anyone heard of them was the portal refusing the upload."""
    assert _artwork_said(project, side, **rules) == said


#: What G4 says of the text and lines inside a vector figure.
_VECTOR_CODES = ("figure-text-small", "figure-line-thin", "figure-text-clipped")


def _vector_said(root: Path, side: dict | None = None, **rules) -> list[tuple[str, str]]:
    _artwork_said(root, side, **rules)
    return [(f.code, f.severity) for f in _journal(root).findings if f.code in _VECTOR_CODES]


@pytest.mark.parametrize(
    ("rules", "side", "said"),
    [
        # forest.svg is 468 units wide, and its smallest text 8 units: at 89 mm, 4.31 pt.
        ({"min_text_pt": 5, "widths_mm": [89, 183]}, None, [("figure-text-small", "warn")]),
        ({"min_text_pt": 4, "widths_mm": [89, 183]}, None, []),
        # Printed 120 mm wide it is 5.8 pt; at 183, 8.9.
        ({"min_text_pt": 5, "widths_mm": [89]}, {"print_width_mm": 120}, []),
        ({"min_text_pt": 5, "widths_mm": [183]}, None, []),
        # Its thinnest line is 0.6 units: at 89 mm, 0.32 pt.
        ({"min_line_pt": 0.5, "widths_mm": [89]}, None, [("figure-line-thin", "warn")]),
        ({"min_line_pt": 0.25, "widths_mm": [89]}, None, []),
        # Without a print width, at its own: 468 pt, where 8 units are 8 pt.
        ({"min_text_pt": 9}, None, [("figure-text-small", "warn")]),
        ({"min_text_pt": 5, "widths_mm": [89], "applies_from": "acceptance"}, None,
         [("figure-text-small", "info")]),
    ],
)  # fmt: skip
def test_text_or_lines_too_small_where_a_vector_figure_prints_are_a_warning(
    project: Path, rules: dict, side: dict | None, said: list
) -> None:
    """Item 17: a vector figure is scaled to the width it prints at, and its text and lines
    with it; a journal's least text and line are at the printed size."""
    assert _vector_said(project, side, **rules) == said


def test_a_text_anchored_outside_a_vector_figure_is_a_warning(project: Path) -> None:
    """Item 17: a label placed past the edge of what an SVG shows is cut off in print."""
    figure = project / "figures" / "forest.svg"
    text = figure.read_text(encoding="utf-8")
    assert _vector_said(project, None, formats=["png", "svg"]) == []
    # The figure is drawn again on each machine, and matplotlib places its labels a little
    # differently on each (CI on Linux): the first label is moved by its own x, not found
    # by the one this machine wrote.
    first = re.search(r'<text\b[^>]*?\bx="([-\d.]+)" y="([-\d.]+)"', text)
    assert first is not None, "the example's figure writes its labels as text"
    x, y = float(first.group(1)) + 400, float(first.group(2))
    figure.write_text(text[: first.start(1)] + f"{x:g}" + text[first.end(1) :], encoding="utf-8")
    said = [f for f in _journal(project).findings if f.code == "figure-text-clipped"]
    assert [(f.severity, f.path.name) for f in said] == [("warn", "forest.svg")]
    assert f"anchored at ({x:.0f}, {y:.0f})" in said[0].message


def test_the_message_says_how_small_a_vector_figure_s_text_prints(project: Path) -> None:
    _artwork_said(project, None, min_text_pt=5, widths_mm=[89])
    said = [f for f in _journal(project).findings if f.code == "figure-text-small"]
    assert len(said) == 1
    assert "prints at 4.31 pt at 89 mm wide, the narrowest the journal prints at," in (
        said[0].message
    ), said[0].message


#: What G4 says of a PDF figure.
_PDF_CODES = (*_VECTOR_CODES, "figure-font-type3", "figure-font-not-embedded")


@pytest.mark.parametrize(
    ("font", "content", "rules", "said"),
    [
        (b"/Type3 /BaseFont /ABCDEF+DejaVuSans", b"", {},
         [("figure-font-type3", "warn")]),
        (b"/Type1 /BaseFont /Helvetica", b"", {}, [("figure-font-not-embedded", "warn")]),
        # A page 216 pt wide printed at 89 mm: 5 pt text prints at 5.84, a 0.2 pt line at 0.23.
        (b"/Type3 /BaseFont /S", b"BT /F1 5 Tf (a) Tj ET", {"min_text_pt": 6},
         [("figure-font-type3", "warn"), ("figure-text-small", "warn")]),
        (b"/Type3 /BaseFont /S", b"BT /F1 5 Tf (a) Tj ET", {"min_text_pt": 5},
         [("figure-font-type3", "warn")]),
        (b"/Type3 /BaseFont /S", b"0.2 w 0 0 m 1 1 l S", {"min_line_pt": 0.25},
         [("figure-font-type3", "warn"), ("figure-line-thin", "warn")]),
        (b"/Type1 /BaseFont /Helvetica", b"", {"applies_from": "acceptance"},
         [("figure-font-not-embedded", "info")]),
    ],
)  # fmt: skip
def test_a_pdf_figure_s_fonts_text_and_lines_the_journal_would_refuse_are_a_warning(
    project: Path, font: bytes, content: bytes, rules: dict, said: list
) -> None:
    """Item 17: a PDF figure's fonts are Type 3 unless matplotlib is told otherwise, or not in
    the file at all where R's pdf() wrote it; and its text and lines print at the size of
    the width it prints at."""
    from generated import pdf_document

    fonts = {"F1": b"<< /Type /Font /Subtype " + font + b" >>"}
    (project / "figures" / "forest.pdf").write_bytes(pdf_document(content, fonts))
    _artwork_said(project, None, widths_mm=[89], **rules)
    found = [(f.code, f.severity) for f in _journal(project).findings
             if f.code in _PDF_CODES and f.path.name == "forest.pdf"]  # fmt: skip
    assert found == said


@pytest.mark.parametrize("written", ["tif", "TIF", "tiff"])
def test_a_tiff_is_taken_however_the_journal_writes_it(project: Path, written: str) -> None:
    """Round 1 of #291: "tif" in a profile matched no file, and the message said the TIFF
    was a format the journal does not take."""
    shutil.copy(project / "figures" / "forest.png", project / "figures" / "forest.tif")
    assert _artwork_said(project, formats=[written.lower(), "eps"]) == []


@pytest.mark.parametrize(
    ("width_mm", "rules", "shown"),
    [
        # Round 1 of #291: 299.7 dpi was printed "300 dpi", beside a minimum of 300.
        (165.27, {"min_dpi": {"halftone": 300}}, "at 299.6 dpi"),
        # Round 2: 299.97 was printed "300.0", and 300.03 beside a maximum of 300 too.
        (165.11, {"min_dpi": {"halftone": 300}}, "at 299.9 dpi"),
        (165.09, {"max_dpi": 300}, "at 300.1 dpi"),
    ],
)
def test_a_resolution_at_its_limit_is_printed_on_the_side_it_fails(
    project: Path, width_mm: float, rules: dict, shown: str
) -> None:
    _artwork_said(project, {"print_width_mm": width_mm}, **rules)
    found = [f for f in _journal(project).findings if f.code == "figure-resolution"]
    assert len(found) == 1 and shown in found[0].message, found


def test_a_supplementary_figure_is_held_to_the_supplement_s_rules(project: Path) -> None:
    main = main_md(project)
    main.write_text(main.read_text(encoding="utf-8").replace("{{figure.forest}}\n", ""),
                    encoding="utf-8")  # fmt: skip
    supplement = project / "manuscript" / "supplementary" / "S1.md"
    supplement.parent.mkdir(exist_ok=True)
    supplement.write_text("# Supplementary figure\n\n{{figure.forest}}\n", encoding="utf-8")
    said = _artwork_said(project, widths_mm=[89], min_dpi={"halftone": 300},
                         supplementary={"max_dpi": 300})  # fmt: skip
    assert said == [("figure-resolution", "warn")]


def test_a_legend_longer_than_the_journal_takes_is_a_warning(project: Path) -> None:
    main = main_md(project)
    legend = "**Figure 1.** " + " ".join(["The reporting odds ratio and its interval."] * 4)
    main.write_text(main.read_text(encoding="utf-8").replace(
        "{{figure.forest}}\n", "{{figure.forest}}\n\n" + legend + "\n"), encoding="utf-8")
    assert _artwork_said(project, legend_words=20) == [("legend-words", "warn")]
    assert _artwork_said(project, legend_words=40) == []


def test_a_second_files_front_matter_is_not_a_required_section(project: Path) -> None:
    """The gate reads the main text as one string joined from every file, and only the first
    file's front matter is at the top of it. A later file's block was read as prose: its
    closing `---`, directly under a YAML line, underlined that line into a heading, so
    `title: Methods of the online appendix` satisfied the required Methods section of a
    paper that had none, and its words counted as main text."""
    main = main_md(project)
    main.write_text(
        main.read_text(encoding="utf-8").replace("# Methods\n", "# Approach\n"), encoding="utf-8"
    )
    before = _journal(project)
    assert "missing-required-section" in codes(before)

    (project / "manuscript" / "online_appendix.md").write_text(
        "---\ntitle: Methods of the online appendix\n---\n\nThree more words.\n",
        encoding="utf-8",
    )
    after = _journal(project)
    assert "missing-required-section" in codes(after)
    assert after.counts["main_text_words"] == before.counts["main_text_words"] + 3


# A section found by its heading. G4 counted "2. Methods" and "Patients and methods" as the
# required Methods, and G9 read neither: with a wrong parameter in `methods.lock`, it warned
# under "# Methods" and said nothing under the other two. The abstract was found only as
# "Abstract", so The Lancet's "Summary" was main text and the abstract's limit read nothing.


def _methods_retitled(root: Path, heading: str) -> None:
    main = main_md(root)
    main.write_text(
        main.read_text(encoding="utf-8").replace("# Methods\n", f"# {heading}\n", 1),
        encoding="utf-8",
    )


def _wrong_alpha_in_the_lock(root: Path) -> None:
    from manuscript_guard.gates import reconcile

    reconcile(load_project(root)[0], parameters={"alpha": "0.07"})


@pytest.mark.parametrize(
    "heading",
    [
        "Methods",
        "2. Methods",
        "2.1 Methods",
        "II. Methods",
        "Patients and methods",
        # each a heading main's G4 took for the Methods, which round 2 of #246 found refused
        "Materials & methods",
        "**2. Methods**",
        "[Methods]{.smallcaps}",
        "2.Methods",
        "Section 2: Methods",
        "Laboratory methods",
        "Study design, setting, participants and methods",
    ],
)
def test_a_wrong_parameter_is_found_under_any_heading_g4_counts_as_the_methods(
    project: Path, heading: str
) -> None:
    from manuscript_guard.gates import check_methods

    _methods_retitled(project, heading)
    _wrong_alpha_in_the_lock(project)
    report = check_methods(load_project(project)[0])
    assert any(
        f.code == "methods-parameter-absent" and "alpha = 0.07" in f.message
        for f in report.warnings
    ), report.render(project)
    assert "methods-not-found" not in {f.code for f in report.findings}
    assert "missing-required-section" not in codes(_journal(project))


def test_a_methods_and_results_section_is_no_methods_for_g2(project: Path) -> None:
    """A research letter's combined section. Taken for the Methods, it let every threshold
    convention through under its results: a reported p value passed as the alpha."""
    from manuscript_guard.classify import is_methods

    assert not is_methods(("Methods and results",))
    assert not is_methods(("2. Results and methods",))
    _methods_retitled(project, "Methods and results")
    main = main_md(project)
    main.write_text(
        main.read_text(encoding="utf-8").replace(
            "# Methods and results\n", "# Methods and results\n\nThe difference was "
            "significant (p < 0.001).\n", 1
        ),
        encoding="utf-8",
    )
    assert any(
        f.code == "unclassified-number" and "0.001" in f.message
        for f in gate_report(project).failures
    )


@pytest.mark.parametrize(
    "title",
    [
        "A method for signal detection",
        # round 2 of #246: a title the word heads is over the Results, and is no Methods
        "Statistical methods for signal detection",
        "Methods for detecting adverse drug reactions",
    ],
)
def test_a_paper_s_title_written_as_a_heading_is_not_its_methods(
    project: Path, title: str
) -> None:
    """With the title an H1 over `##` sections, a heading holding the word was the first
    that named the Methods, and G9 read the whole paper as them: a wrong parameter stated in
    the Results passed."""
    from manuscript_guard.gates import check_methods
    from manuscript_guard.gates.methods import methods_in

    text = (
        f"# {title}\n\n## Background\n\nWords.\n\n"
        "## Limitations of existing methods\n\nWords.\n\n## Methods\n\nNo alpha here."
        "\n\n## Results\n\nAn alpha of 0.07 was used.\n"
    )
    assert methods_in(text) == "\n\nNo alpha here.\n\n"
    # Round 3 of #246: numbered in brackets, in bold or with an ampersand, the Methods were
    # not read as named, and the heading before them that only holds the word was taken.
    for methods in ("(2) Methods", "**2. Methods**", "Materials & methods"):
        assert methods_in(text.replace("## Methods", f"## {methods}")) == "\n\nNo alpha here.\n\n"
    main = main_md(project)
    body = main.read_text(encoding="utf-8").split("---\n", 2)
    demoted = body[2].replace("\n# ", "\n## ")
    main.write_text(f"---{body[1]}---\n\n# {title}\n{demoted}", encoding="utf-8")
    _wrong_alpha_in_the_lock(project)
    main.write_text(
        main.read_text(encoding="utf-8") + "\nAn alpha of 0.07 was used.\n", encoding="utf-8"
    )
    report = check_methods(load_project(project)[0])
    assert any(
        f.code == "methods-parameter-absent" and "alpha = 0.07" in f.message
        for f in report.warnings
    ), report.render(project)


def test_no_heading_that_names_the_methods_is_said(project: Path) -> None:
    from manuscript_guard.gates import check_methods

    _methods_retitled(project, "Approach")
    _wrong_alpha_in_the_lock(project)
    report = check_methods(load_project(project)[0])
    assert [f.code for f in report.warnings if f.code.startswith("methods-")] == [
        "methods-not-found"
    ], report.render(project)
    assert "missing-required-section" in codes(_journal(project))


def test_a_structured_abstract_s_results_are_not_the_paper_s(project: Path) -> None:
    """Every required section, not only the Methods: the abstract's "Results" answered the
    journal's required Results in a paper whose body called them something else."""
    main = main_md(project)
    text = main.read_text(encoding="utf-8").replace("\n# Results\n", "\n# Findings\n", 1)
    main.write_text(
        text.replace("# Abstract\n\n", "# Abstract\n\n## Results\n\nA ratio.\n\n", 1),
        encoding="utf-8",
    )
    assert any(
        f.code == "missing-required-section" and "Results" in f.message
        for f in _journal(project).failures
    )


def test_a_structured_abstract_s_methods_are_not_the_paper_s(project: Path) -> None:
    """The required sections were looked for among every heading, the abstract's own
    among them, so a paper with no Methods section passed on its abstract's subheading."""
    _methods_retitled(project, "Approach")
    main = main_md(project)
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("# Abstract\n\n", "# Abstract\n\n## Methods\n\nA cohort.\n\n", 1),
        encoding="utf-8",
    )
    assert any(
        f.code == "missing-required-section" and "Methods" in f.message
        for f in _journal(project).failures
    )


def _abstract_retitled(root: Path, heading: str, words: int = 0) -> None:
    main = main_md(root)
    text = main.read_text(encoding="utf-8")
    padding = " ".join(["more"] * words)
    main.write_text(
        text.replace("# Abstract\n\n", f"# {heading}\n\n{padding}\n\n", 1), encoding="utf-8"
    )


def _profile_says(root: Path, **structure: str) -> None:
    path = root / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["structure"].update(structure)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_an_abstract_the_profile_calls_summary_is_held_to_the_abstract_s_limit(
    project: Path,
) -> None:
    _abstract_retitled(project, "Summary", words=400)
    _profile_says(project, abstract_title="Summary")
    report = _journal(project)
    assert any(
        f.code == "over-journal-limit" and f.message.startswith("abstract:")
        for f in report.findings
    ), report.render(project)
    assert "abstract-not-found" not in {f.code for f in report.findings}


def test_an_abstract_no_heading_names_is_said(project: Path) -> None:
    """"Summary" with no `abstract_title`: the abstract's limit read nothing, and its words
    counted as main text."""
    _abstract_retitled(project, "Summary", words=400)
    report = _journal(project)
    found = [f for f in report.warnings if f.code == "abstract-not-found"]
    assert len(found) == 1 and "300 words" in found[0].message, report.render(project)
    assert report.counts["abstract_words"] == 0


def test_a_comment_in_the_front_matter_is_not_a_required_statement(project: Path) -> None:
    """`# Funding` is a heading in Markdown and a comment in YAML. Inside the front matter it
    satisfied the journal's funding statement, and the build, which strips the block,
    printed a paper with no funding statement in it."""
    main = main_md(project)
    text = main.read_text(encoding="utf-8").replace("# Funding\n", "# Acknowledgements\n")
    text = text.replace("---\n", "---\n# Funding: none was received.\n", 1)
    main.write_text(text, encoding="utf-8")
    report = _journal(project)
    assert any(
        f.code == "missing-required-statement" and "funding" in f.message
        for f in report.failures
    )


@pytest.mark.parametrize(
    "hidden",
    [
        "<!--\n# Funding\nTBD\n-->\n",
        "```r\n# Funding source, from the registry\nfunder <- NA\n```\n",
        "~~~python\n# Funding\nfunder = None\n~~~\n",
    ],
)
def test_a_statement_that_does_not_print_as_one_is_missing(project: Path, hidden: str) -> None:
    """The statement patterns were searched in the main text with its HTML comments and
    fenced code still in it. `# Funding` is a heading in Markdown and a comment in R and
    Python: inside `<!-- -->` it satisfied the journal's funding statement and printed
    nothing, and inside a listing it printed as a line of code. Either way the paper went
    out with no funding statement."""
    main = main_md(project)
    text = main.read_text(encoding="utf-8").replace("# Funding\n", "# Acknowledgements\n")
    main.write_text(f"{text}\n{hidden}", encoding="utf-8")
    report = _journal(project)
    assert any(
        f.code == "missing-required-statement" and "funding" in f.message
        for f in report.failures
    )


def test_a_structured_abstract_heading_in_a_comment_is_missing(project: Path) -> None:
    """The abstract's required headings were looked for in its text with its comments still
    in it, so `<!-- Conclusions: to write -->` met a Conclusions heading the abstract did
    not print."""
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["structure"]["abstract_headings"] = ["Background", "Methods", "Conclusions"]
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    main = main_md(project)
    text = main.read_text(encoding="utf-8").replace(
        "**Conclusions.** Reporting", "<!-- Conclusions: to write -->\nReporting"
    )
    main.write_text(text, encoding="utf-8")
    assert "abstract-headings-missing" in codes(_journal(project))


# ------------------------------------------------------ a figure's alternative text


def _alt(root: Path, alt: object = None, **rules) -> None:
    """The example's figure given this alternative text (None takes it away), and its
    journal these artwork rules."""
    if rules:
        profile = root / "profiles" / "journals" / "demo-journal.yaml"
        document = yaml.safe_load(profile.read_text(encoding="utf-8"))
        document["figures"] = {"source_url": "https://journal.example/artwork",
                               "read_on": "2026-10-21", "confirmed": True, **rules}  # fmt: skip
        profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    sidecar = root / "figures" / "forest.guard.yaml"
    guard = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    guard.pop("alt", None)
    if alt is not None:
        guard["alt"] = alt
    sidecar.write_text(yaml.safe_dump(guard, sort_keys=False, allow_unicode=True),
                       encoding="utf-8")  # fmt: skip


def _alt_said(root: Path, stage: str = "drafting") -> list[tuple[str, str]]:
    """What `check` says of the figure's alternative text at `stage`, the stage's policy
    applied."""
    from manuscript_guard.cli import _run_gates

    report, _project, _chosen, _deferred = _run_gates(root, stage=stage)
    return [(f.code, f.severity) for f in report.findings if f.code.startswith("figure-alt-")]


def test_the_examples_alternative_text_passes_at_every_stage(project: Path) -> None:
    for stage in ("drafting", "internal-review", "submission"):
        assert _alt_said(project, stage) == [], stage


@pytest.mark.parametrize(
    ("stage", "rules", "said"),
    [
        ("drafting", {}, "info"),
        ("internal-review", {}, "warn"),
        ("submission", {}, "warn"),
        ("submission", {"alt_text": "requested"}, "warn"),
        ("drafting", {"alt_text": "required"}, "info"),
        ("internal-review", {"alt_text": "required"}, "warn"),
        ("submission", {"alt_text": "required"}, "fail"),
        # Round 1 of #387: where the journal applies its artwork rules from acceptance, G4
        # notes what does not meet them, and so does this.
        ("submission", {"alt_text": "required", "applies_from": "acceptance"}, "info"),
    ],
)
def test_a_figure_with_no_alternative_text_fails_only_where_the_journal_requires_one(
    project: Path, stage: str, rules: dict, said: str
) -> None:
    """Basile, 2026-10-21: a note while drafting, a warning from internal review, and a
    failure at submission where the journal's profile requires alternative text. The build
    placed every figure as `![](path)`, so every document went out with none."""
    _alt(project, None, **rules)
    assert _alt_said(project, stage) == [("figure-alt-missing", said)]


@pytest.mark.parametrize("alt", ["", "   \n", ["a list"], 3.84, {"text": "a mapping"}])
def test_alternative_text_that_is_no_text_is_none(project: Path, alt: object) -> None:
    _alt(project, alt, alt_text="required")
    assert _alt_said(project, "submission") == [("figure-alt-missing", "fail")]


def test_a_supplementary_figure_is_held_to_the_supplements_rule(project: Path) -> None:
    """A rule under `supplementary:` replaces the main one for a figure only the supplement
    places, as every other artwork rule does."""
    main = main_md(project)
    main.write_text(main.read_text(encoding="utf-8").replace("{{figure.forest}}\n", ""),
                    encoding="utf-8")  # fmt: skip
    (project / "manuscript" / "supplementary" / "figures.md").write_text(
        "# Supplementary figure\n\n{{figure.forest}}\n", encoding="utf-8"
    )
    _alt(project, None, alt_text="requested", supplementary={"alt_text": "required"})
    assert ("figure-alt-missing", "fail") in _alt_said(project, "submission")


def test_each_binding_in_the_alternative_text_typed_as_its_value_fails(project: Path) -> None:
    """The headline corruption, in the alternative text: each binding replaced by the value
    it prints is correct today and stale in waiting, and fails as it would in the prose."""
    sidecar = project / "figures" / "forest.guard.yaml"
    raw = yaml.safe_load(sidecar.read_text(encoding="utf-8"))["alt"]
    namespace = load_namespace(load_project(project)[0])[0]
    found = bindings_in(raw)
    assert len(found) == 3, raw
    for binding in found:
        display = namespace[binding.strip("{}")].display
        _alt(project, raw.replace(binding, display))
        assert _alt_said(project) == [("figure-alt-number", "fail")], binding


def test_a_number_in_the_alternative_text_that_prose_would_pass_passes(project: Path) -> None:
    """Held as prose is, and no harder: a convention ("95% CI") is no result."""
    _alt(project, "The estimate is drawn with its 95% CI, {{results.ror.ci_low}} to "
                  "{{results.ror.ci_high}}.")  # fmt: skip
    assert _alt_said(project) == []


@pytest.mark.parametrize(
    "binding",
    ["{{results.no_such_key}}", "{{table.two_by_two}}", "{{figure.forest}}",
     "{{method.no_such_step}}", "{{results.ror.point}"],
)  # fmt: skip
def test_a_binding_in_the_alternative_text_that_prints_no_value_fails(
    project: Path, binding: str
) -> None:
    _alt(project, f"The reporting odds ratio, {binding}, drawn on a log scale.")
    assert _alt_said(project) == [("figure-alt-binding", "fail")]


def test_alternative_text_longer_than_the_journal_takes_is_a_warning(project: Path) -> None:
    """Counted as printed: each binding its display, so "{{results.ror.point}}" is four
    characters ("3.84") and not twenty-two."""
    from manuscript_guard.gates.figure_alt import printed_alt, raw_alt

    loaded = load_project(project)[0]
    printed = printed_alt(raw_alt(loaded, "forest"), load_namespace(loaded)[0])
    _alt(project, yaml.safe_load(
        (project / "figures" / "forest.guard.yaml").read_text(encoding="utf-8"))["alt"],
        alt_text_max_chars=len(printed))  # fmt: skip
    assert _alt_said(project, "internal-review") == []
    _alt(project, yaml.safe_load(
        (project / "figures" / "forest.guard.yaml").read_text(encoding="utf-8"))["alt"],
        alt_text_max_chars=len(printed) - 1)  # fmt: skip
    assert _alt_said(project, "drafting") == [("figure-alt-long", "info")]
    assert _alt_said(project, "submission") == [("figure-alt-long", "warn")]


def test_a_comment_in_the_alternative_text_is_read_as_it_is_printed(project: Path) -> None:
    """Round 1 of #387: the build prints the text as written, an HTML comment and all, and
    the checks read it as Markdown, which hides a comment: a number typed into one went out
    with nothing said, and a binding in one was printed as written."""
    from manuscript_guard.gates.figure_alt import printed_alt, raw_alt

    _alt(project, "Odds ratio <!-- was {{results.ror.point}}, 3.84 -->.")
    assert _alt_said(project) == [("figure-alt-number", "fail")]
    loaded = load_project(project)[0]
    assert printed_alt(raw_alt(loaded, "forest"), load_namespace(loaded)[0]) == (
        "Odds ratio <!-- was 3.84, 3.84 -->."
    )
    _alt(project, "Odds ratio <!-- {{results.no_such_key}} -->.")
    assert _alt_said(project) == [("figure-alt-binding", "fail")]


def test_a_declared_parameter_typed_into_the_alternative_text_fails(project: Path) -> None:
    """Round 1 of #387: G2 fails a threshold typed in the prose once the analysis declares
    it, and the alternative text passed it as the convention it reads as."""
    from manuscript_guard.cli import _run_gates

    _alt(project, "The estimate, {{results.ror.point}}, is significant at p < 0.05.")
    report, _project, _chosen, _deferred = _run_gates(project)
    [found] = [f for f in report.findings if f.code.startswith("figure-alt-")]
    assert (found.code, found.severity) == ("figure-alt-number", "fail")
    assert "'0.05'" in found.message and "which the analysis declares" in found.message


def test_a_count_bound_in_the_alternative_text_is_held_to_the_custodians_minimum(
    project: Path,
) -> None:
    """Round 1 of #387: the build prints a count bound in the alternative text into the
    picture and the pack, and G2 read the manuscript's bindings alone."""
    _custodian(project, 5)
    _value_has(project, "case.n_serious", value=3, display="3")
    main = main_md(project)
    main.write_text(main.read_text(encoding="utf-8").replace(
        "{{results.case.n_serious}}", "a few"), encoding="utf-8")  # fmt: skip
    assert _small(project) == []
    _alt(project, "Of the cases, {{results.case.n_serious}} were serious.")
    assert _small(project) == [("results.case.n_serious", None)]


def test_a_result_quoted_in_the_alternative_text_alone_is_quoted_from_synthetic_data(
    project: Path,
) -> None:
    """Round 1 of #387: the build prints it, so a result from a synthetic run quoted there
    is a number from synthetic data in the paper."""
    import re

    _not_a_demonstration(project)
    for path in (project / "manuscript").rglob("*.md"):
        path.write_text(re.sub(r"\{\{\s*(?:results|table)\.[^}]*\}\}", "[elided]",
                               path.read_text(encoding="utf-8")), encoding="utf-8")  # fmt: skip
    _alt(project, None)
    assert _synthetic_said(project) == []
    _alt(project, "Forest plot of the reporting odds ratio, {{results.ror.point}}.")
    [(severity, _message)] = _synthetic_said(project)
    assert severity == "warn"


def test_a_journal_profile_with_an_alt_text_rule_out_of_shape_is_refused(project: Path) -> None:
    _alt(project, "Text.", alt_text="mandatory")
    assert "schema-violation" in codes(_journal(project))


# ------------------------------------------------------------ a figure's colours, as seen

#: matplotlib's red and green, which deuteranopia makes one colour; Okabe and Ito's orange
#: and sky blue, which stay apart for every deficiency and are one grey.
_RED, _GREEN, _ORANGE, _SKY = "#d62728", "#2ca02c", "#e69f00", "#56b4e9"


def _painted(root: Path, *marks: str, svg: bool = True) -> None:
    """The example's figure redrawn as lines in `marks`, each a colour or `text:<colour>`
    for a text in that colour; as an SVG, or as a PDF in its place."""
    figures = root / "figures"
    for stale in ("forest.svg", "forest.pdf"):
        (figures / stale).unlink(missing_ok=True)
    if svg:
        body = "".join(
            f'<text x="5" y="{10 + 12 * n}" fill="{m[5:]}">label</text>' if m.startswith("text:")
            else f'<path d="M0 {10 * n}L90 {10 * n}" style="fill: none; stroke: {m}"/>'
            for n, m in enumerate(marks)
        )
        (figures / "forest.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100pt" height="80pt" '
            f'viewBox="0 0 100 80"><rect width="100" height="80" fill="#ffffff"/>{body}</svg>',
            encoding="utf-8",
        )
        return
    from generated import pdf_document

    def rgb(code: str) -> bytes:
        return b" ".join(b"%.4f" % (int(code[i : i + 2], 16) / 255) for i in (1, 3, 5))

    ops = []
    for n, m in enumerate(marks):
        if m.startswith("text:"):
            ops.append(b"%s rg BT /F1 9 Tf 5 %d Td (label) Tj ET" % (rgb(m[5:]), 10 + 12 * n))
        else:
            ops.append(b"%s RG 0 %d m 90 %d l S" % (rgb(m), 10 * n, 10 * n))
    (figures / "forest.pdf").write_bytes(pdf_document(b"\n".join(ops)))


def _colours_said(root: Path) -> list[tuple[str, str]]:
    from manuscript_guard.gates.figure_colours import check_figure_colours

    report = check_figure_colours(load_project(root)[0])
    return [(f.code, f.severity) for f in report.findings]


def _guarded(root: Path, **fields) -> None:
    sidecar = root / "figures" / "forest.guard.yaml"
    guard = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    sidecar.write_text(yaml.safe_dump({**guard, **fields}, sort_keys=False, allow_unicode=True),
                       encoding="utf-8")  # fmt: skip


def test_the_examples_figure_keeps_its_colours_apart(project: Path) -> None:
    """Black, grey and white: no deficiency moves a grey, and grey keeps them apart."""
    from manuscript_guard.gates.figure_colours import check_figure_colours

    report = check_figure_colours(load_project(project)[0])
    assert report.findings == () and report.counts["figures_colour_checked"] == 1


@pytest.mark.parametrize("svg", [True, False], ids=["svg", "pdf"])
def test_two_colours_a_deficiency_makes_one_are_a_warning(project: Path, svg: bool) -> None:
    """Basile, 2026-10-21: read from the figure itself, simulated with Machado et al. (2009)
    and compared by CIEDE2000; a warning, never a failure. matplotlib's default red and
    green are 72 apart to normal vision and under 5 apart with deuteranopia."""
    _painted(project, _RED, _GREEN, svg=svg)
    assert _colours_said(project) == [("figure-colours-confused", "warn")]
    from manuscript_guard.gates.figure_colours import check_figure_colours

    [found] = check_figure_colours(load_project(project)[0]).findings
    assert "deuteranopia" in found.message and _GREEN in found.message and _RED in found.message


def test_a_palette_drawn_for_deficiencies_is_said_only_of_grey(project: Path) -> None:
    """Okabe and Ito's orange and sky blue are one grey: a note, and a warning where the
    journal prints its figures in grey or the figure's guard file asks."""
    _painted(project, _ORANGE, _SKY)
    assert _colours_said(project) == [("figure-greyscale-confused", "info")]
    _guarded(project, greyscale=True)
    assert _colours_said(project) == [("figure-greyscale-confused", "warn")]
    _guarded(project, greyscale=False)
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["figures"] = {"source_url": "https://journal.example/artwork",
                           "read_on": "2026-10-21", "confirmed": True, "print": "greyscale"}
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert _colours_said(project) == [("figure-greyscale-confused", "warn")]


@pytest.mark.parametrize(
    ("value", "why", "said"),
    [
        (f"{_RED} {_GREEN}", "the two series also differ by line style", "info"),
        (_GREEN, "the treated group is also drawn dashed", "info"),
        (f"{_RED} {_GREEN}", "", "warn"),
        (f"{_RED} #000000", "another pair", "warn"),
    ],
)
def test_a_pair_the_guard_gives_a_reason_for_is_a_note(
    project: Path, value: str, why: str, said: str
) -> None:
    """With a reason for the pair, or for one colour of it, the warning is a note that
    quotes it; with none, or for another pair, it stays a warning."""
    _painted(project, _RED, _GREEN)
    _guarded(project, allow_colours=[{"value": value, "why": why}])
    assert _colours_said(project) == [("figure-colours-confused", said)]
    if said == "info":
        from manuscript_guard.gates.figure_colours import check_figure_colours

        [found] = check_figure_colours(load_project(project)[0]).findings
        assert why in found.hint


@pytest.mark.parametrize("svg", [True, False], ids=["svg", "pdf"])
def test_a_texts_colour_is_not_a_series(project: Path, svg: bool) -> None:
    """A label in red beside a green line confuses no data."""
    _painted(project, f"text:{_RED}", _GREEN, svg=svg)
    assert _colours_said(project) == []


def _ramp_codes(steps: int) -> list[str]:
    """`steps` shades from ggplot2's dark blue to its light one, as a continuous colour scale
    draws its points."""
    start, end = (0x13, 0x2B, 0x43), (0x56, 0xB1, 0xF7)
    return ["#" + "".join(f"{round(a + (b - a) * i / (steps - 1)):02x}" for a, b in
                          zip(start, end, strict=True)) for i in range(steps)]  # fmt: skip


def test_a_figure_that_draws_a_scale_is_said_not_to_be_compared(project: Path) -> None:
    """Rounds 1 to 3 of #398: a scale's shades sit just over the threshold apart and grey
    brought every pair under it, and each rule for telling its shades from series failed one
    way or the other. Basile, 2026-10-21: such a figure is not compared, and is said not to
    be, the series beside the scale with it."""
    _painted(project, *_ramp_codes(64))
    assert _colours_said(project) == [("figure-colours-scale", "info")]
    _painted(project, *_ramp_codes(64), _RED, _GREEN)
    assert _colours_said(project) == [("figure-colours-scale", "info")]


def test_a_line_plot_with_light_bands_is_compared(project: Path) -> None:
    """The review of #398: three series' bands at an opacity of 0.1 chain by hue at one
    lightness; taken for a scale, they switched the check off, and red and green, one colour
    with deuteranopia, went unsaid."""
    _painted(project, _RED, "#ff7f0e", "#bcbd22", _GREEN, "#fbe9e9", "#fff2e7", "#f8f8e9")
    assert ("figure-colours-confused", "warn") in _colours_said(project)


def test_a_default_figures_greys_make_no_scale(project: Path) -> None:
    """matplotlib's black, its grid's grey, a legend's frame and white chain within the
    threshold; they make no scale, and the figure's red and green are compared."""
    _painted(project, "#000000", "#b0b0b0", "#cccccc", "#d6d6d6", "#ffffff", _RED, _GREEN)
    assert ("figure-colours-confused", "warn") in _colours_said(project)
    assert ("figure-colours-scale", "info") not in _colours_said(project)


def test_a_figure_of_more_colours_than_are_compared_is_said_so(project: Path) -> None:
    from manuscript_guard.gates.figure_colours import MANY

    # A grid of reds and greens, as a heat map drawn as vectors paints one.
    side = int(MANY**0.5) + 2
    _painted(project, *(f"#{i * 11:02x}{j * 11:02x}80" for i in range(side) for j in range(side)))
    assert _colours_said(project) == [("figure-colours-many", "info")]


@pytest.mark.parametrize(
    "value",
    ["rgb(214, 39, 40) and rgb(44, 160, 44)", f"{_RED}, {_GREEN}, #000000",
     "tab red: #d62728; tab green: #2ca02c"],
)  # fmt: skip
def test_a_pair_is_found_however_the_guard_writes_its_colours(project: Path, value: str) -> None:
    """Round 1 of #398: `rgb(214, 39, 40)` was cut at its commas and matched nothing, and a
    value of three colours matched no pair."""
    _painted(project, _RED, _GREEN)
    _guarded(project, allow_colours=[{"value": value, "why": "they differ by line style"}])
    assert _colours_said(project) == [("figure-colours-confused", "info")]


def _heat_codes() -> list[str]:
    """A heat map's shades, black to red to yellow to white, three hundred and more of them
    distinct, as a map drawn as vectors paints them."""
    stops = ((0, 0, 0), (255, 0, 0), (255, 255, 0), (255, 255, 255))
    out = []
    for (a, b) in zip(stops, stops[1:], strict=False):
        for i in range(150):
            out.append("#" + "".join(f"{round(x + (y - x) * i / 150):02x}"
                                     for x, y in zip(a, b, strict=True)))  # fmt: skip
    return list(dict.fromkeys(out))


def test_a_heat_map_of_many_colours_is_said_not_to_be_compared(project: Path) -> None:
    """Past three hundred colours nothing is compared, the series beside the heat map with
    it, and the note says so (a known gap, in DESIGN.md)."""
    from manuscript_guard.gates.figure_colours import MANY

    assert len(_heat_codes()) > MANY
    _painted(project, *_heat_codes(), _RED, _GREEN)
    assert _colours_said(project) == [("figure-colours-many", "info")]


def test_an_svg_that_cannot_be_read_gives_way_to_the_pdf_beside_it(project: Path) -> None:
    _painted(project, _RED, _GREEN, svg=False)
    (project / "figures" / "forest.svg").write_text("<svg><unclosed", encoding="utf-8")
    assert _colours_said(project) == [("figure-colours-confused", "warn")]


def test_a_figure_with_only_a_raster_is_said_to_be_unread(project: Path) -> None:
    _painted(project)
    (project / "figures" / "forest.svg").unlink()
    assert _colours_said(project) == [("figure-colours-unread", "info")]


def test_confused_colours_warn_and_never_fail(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    _painted(project, _RED, _GREEN)
    report, _project, _chosen, _deferred = _run_gates(project, submission=True)
    said = [(f.code, f.severity) for f in report.findings if f.code.startswith("figure-colours")]
    assert said == [("figure-colours-confused", "warn")]


def test_a_journal_profile_with_a_print_rule_out_of_shape_is_refused(project: Path) -> None:
    profile = project / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["figures"] = {"source_url": "https://journal.example/artwork",
                           "read_on": "2026-10-21", "confirmed": True, "print": "sepia"}
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    assert "schema-violation" in codes(_journal(project))


# ------------------------------------------------- the journal's citation style (item 51)


def _style_said(root: Path) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in _journal(root).findings
            if f.code.startswith("journal-style")]  # fmt: skip


def test_a_journal_style_the_project_does_not_keep_is_said(project: Path) -> None:
    """The offline build formatted in pandoc's default style, whatever the profile named, and
    nothing said so."""
    from test_style import DEPENDENT, keep_style, name_style

    assert _style_said(project) == []
    name_style(project, DEPENDENT)
    assert _style_said(project) == [("journal-style-not-stored", "warn")]
    name_style(project, "https://example.org/styles/elsewhere")
    assert _style_said(project) == [("journal-style-not-stored", "warn")]
    keep_style(project, DEPENDENT)
    assert _style_said(project) == []
    # Round 1 of #322: a file's name is said to be one (round 1 of #349: untested).
    name_style(project, f"{DEPENDENT}.csl")
    [said] = [f for f in _journal(project).findings if f.code == "journal-style-not-stored"]
    assert "a name with `.csl` is a file's" in said.message


def test_a_kept_style_edited_since_is_said_and_not_used(project: Path) -> None:
    from test_style import DEPENDENT, PARENT, keep_style

    from manuscript_guard.journal_style import stored

    keep_style(project, DEPENDENT)
    parent = project / "profiles" / "journals" / "styles" / DEPENDENT / f"{PARENT}.csl"
    parent.write_bytes(parent.read_bytes() + b"<!-- edited -->")
    assert _style_said(project) == [("journal-style-changed", "warn")]
    assert stored(load_project(project)[0], DEPENDENT) is None
    parent.unlink()
    [said] = [f for f in _journal(project).findings if f.code == "journal-style-changed"]
    assert f"{PARENT}.csl (missing)" in said.message


@pytest.mark.parametrize(
    ("found", "numbered", "said"),
    [
        ("numeric", True, []),
        ("numeric", False, [("journal-style-format", "warn")]),
        ("author-date", True, [("journal-style-format", "warn")]),
        ("author-date", False, []),
        ("note", True, [("journal-style-format", "warn")]),
    ],
)
def test_a_style_that_numbers_otherwise_than_the_profile_is_said(
    project: Path, found: str, numbered: bool, said: list
) -> None:
    """The style's own citation format against the profile's `numbered:`: one of the two
    was read wrong from the journal's page."""
    from test_style import DEPENDENT, keep_style, name_style

    keep_style(project, DEPENDENT)
    record = project / "profiles" / "journals" / "styles" / f"{DEPENDENT}.yaml"
    document = yaml.safe_load(record.read_text(encoding="utf-8"))
    record.write_text(yaml.safe_dump({**document, "citation_format": found}, sort_keys=False),
                      encoding="utf-8")  # fmt: skip
    name_style(project, DEPENDENT, numbered=numbered)
    assert _style_said(project) == said


# ------------------------------------------------------------- what the build prints
# The build strips every file's front matter and writes the header from paper.yaml. Text
# the gates read there and the build drops is checked, then left out of the document.

SENTINEL = "Zebrafish marmalade sentinel phrase."


@pytest.mark.parametrize(
    "abstract",
    [
        f"abstract: |\n  {SENTINEL}\n",
        "abstract: >-\n  Zebrafish marmalade\n  sentinel phrase.\n",
        f"abstract: {SENTINEL}\n",
        f'"abstract": {SENTINEL}\n',
        # Merged in through a list that is met twice: under the first of two merge keys,
        # by a mapping that merges it, and as the second. See `_MET_TWICE` further down.
        f"l: &l [{{abstract: {SENTINEL}}}]\ny: &y {{abstract: ~}}\nm2: &m2 {{<<: *l}}\n"
        "a: &a {<<: [*m2, *y]}\n<<: *a\n<<: *l\n",
    ],
)
def test_an_abstract_in_the_front_matter_is_refused(project: Path, abstract: str, capsys) -> None:
    """G2 read an `abstract:` in the front matter, because pandoc prints one, and the build
    stripped the block and wrote a header from paper.yaml, which has no abstract. The
    abstract was checked and then left out of the document without a word, and the word
    count, which follows the build, gave a journal's abstract limit 0 words to pass on.
    `check` refuses it now, and the build refuses it even when told to skip the checks."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("---\n", "---\n" + abstract, 1), encoding="utf-8")

    assert main(["check", str(project), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    failing = [(f["code"], f["line"]) for f in findings if f["severity"] == "fail"]
    assert failing == [("front-matter-abstract", 2)]

    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "under a `# Abstract` heading" in capsys.readouterr().out
    # Any name: a build that skipped failing checks writes `manuscript.UNCHECKED.*`.
    assert list((project / "build").glob("manuscript*")) == []


def test_a_supplements_front_matter_abstract_is_refused(project: Path) -> None:
    """The build strips a supplement's front matter as it strips the paper's."""
    from manuscript_guard.build.assemble import assemble

    supplement = project / "manuscript" / "supplementary" / "appendix.md"
    supplement.parent.mkdir(parents=True, exist_ok=True)
    supplement.write_text(f"---\nabstract: {SENTINEL}\n---\n\n# Appendix\n\nText.\n", "utf-8")

    def refused(report) -> list[tuple[str, str, int | None]]:
        found = [f for f in report.failures if f.code == "front-matter-abstract"]
        return [(f.gate, f.path.name, f.line) for f in found]

    assert refused(gate_report(project)) == [("G2", "appendix.md", 2)]
    projekt, _ = load_project(project)
    namespace, results, _literature, _report = load_namespace(projekt)
    assert refused(assemble(projekt, namespace, results)[1]) == [("BUILD", "appendix.md", 2)]


#: A header whose root has two merge keys. Under the first, `a` merges `m2` and then `y`,
#: and `m2` merges the list `l`, which the second key names as well. Pandoc takes the
#: abstract of the list's member, since `m2` stands before `y`. A search that goes through
#: a merged list once, and marks it when the mapping that merges it is read, has marked `l`
#: at the root before `m2` is reached, passes over it there, and takes `y`'s: tried for
#: speed in #168, it left an abstract pandoc prints unrefused, and was taken back.
_MET_TWICE = (
    "l: &l [{{abstract: {first}}}]\ny: &y {{abstract: {second}}}\nm2: &m2 {{<<: *l}}\n"
    "a: &a {{<<: [*m2, *y]}}\n<<: *a\n<<: *l\n"
)


def _abstract_line(front: str) -> int | None:
    from manuscript_guard.text.masking import front_matter_abstract

    found = front_matter_abstract(f"---\n{front}---\n\nBody.\n")
    return None if found is None else found[0]


@pytest.mark.parametrize(
    ("front", "line"),
    [
        (f"abstract: {SENTINEL}\n", 2),
        (f"'abstract': {SENTINEL}\n", 2),
        (f'abstract: "\n  {SENTINEL}"\n', 2),
        (f"abstract: '\n  {SENTINEL}'\n", 2),
        (f"{{title: T, abstract: {SENTINEL}}}\n", 2),
        (f"title: T\nabstract:\n\n  {SENTINEL}\n", 3),
        ("abstract: 0\n", 2),
        # Blocks pandoc reads and PyYAML could not turn into Python values, or not scan.
        (f'date: 2024-02-30\n"abstract": {SENTINEL}\n', 3),
        (f"created: !r Sys.Date()\n'abstract': {SENTINEL}\n", 3),
        (f'subtitle:\tS\n"abstract": {SENTINEL}\n', 3),
        # Pandoc expands a tab to the next multiple of four columns, so this is one block.
        ('"abstract": |\n  Zebrafish marmalade\n\tsentinel phrase.\n', 2),
        (f'title:\tT\n"abstract":\t{SENTINEL}\n', 3),
        # Pandoc takes a merge key's mapping into the one holding it, and knows a merge key
        # by its text, `<<`, however it is quoted or tagged.
        (f"base: &b {{abstract: {SENTINEL}}}\n<<: *b\n", 2),
        (f'base: &b {{abstract: {SENTINEL}}}\n"<<": *b\n', 2),
        (f"base: &b {{abstract: {SENTINEL}}}\n'<<': *b\n", 2),
        (f"!!merge abstract: {SENTINEL}\n", 2),
        (_MET_TWICE.format(first=SENTINEL, second="~"), 2),
        # PyYAML counts U+2028 as a line break, and the file does not.
        (f'title: "Hepatic{chr(0x2028)}injury"\nabstract: {SENTINEL}\n', 3),
        # Pandoc prints the text whatever the tag says, and a quoted "null" is the word.
        (f"abstract: !!null {SENTINEL}\n", 2),
        ('abstract: "null"\n', 2),
    ],
)
def test_every_spelling_of_a_front_matter_abstract_is_found(front: str, line: int) -> None:
    """G2 finds a front-matter value by its key line, and YAML has spellings that line
    misses: a quoted key, a quoted value opened on the key's line and continued below it, a
    flow mapping, a merge key. Pandoc prints each as the abstract, so the refusal reads the
    block as YAML, the way pandoc reads it, and names the line of the key."""
    assert _abstract_line(front) == line


@pytest.mark.parametrize(
    "front",
    [
        'abstract: ""\n',
        "abstract:\n",
        "abstract: |\n",
        "abstract: >-\n",
        "abstract: |2\n",
        "abstract: null\n",
        "abstract: # written last\n",
        'abstract: "" # none\n',
        f"meta:\n  abstract: {SENTINEL}\n",
        # The first of two merge keys wins, quoted or not, and its abstract is empty.
        f'e: &e {{abstract: ""}}\nf: &f {{abstract: {SENTINEL}}}\n"<<": *e\n<<: *f\n',
        # The list's member is null and stands before the text, which is not the abstract.
        _MET_TWICE.format(first="~", second=SENTINEL),
    ],
)
def test_a_front_matter_abstract_pandoc_prints_nothing_for_is_not_refused(front: str) -> None:
    """Nothing is lost by stripping an abstract pandoc reads as empty, or a key named
    `abstract` inside another mapping, which pandoc does not take for the abstract."""
    assert _abstract_line(front) is None


def test_a_merge_key_bomb_in_the_front_matter_does_not_hold_up_check() -> None:
    """A mapping merging the one before it twice doubles, with each line, the work of
    anything that expands merge keys: 22 lines, 614 bytes, held `check` for 38 seconds when
    the block was built into Python values. The search for a merged abstract has the same
    shape, so it visits each mapping once; this one is found only after all of `a21`."""
    merges = [f"a{i}: &a{i} {{<<: [*a{i - 1}, *a{i - 1}]}}" for i in range(1, 22)]
    lines = ["a0: &a0 {k: v}", *merges, f"z: &z {{abstract: {SENTINEL}}}", "<<: [*a21, *z]"]
    started = time.perf_counter()
    line = _abstract_line("\n".join(lines) + "\n")
    assert time.perf_counter() - started < 5
    assert line == 24


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


_BOOK = "Smith J. Pharmacovigilance: a practical guide. 3rd ed. Oxford: Wiley; 2019. 412 p."


@pytest.mark.parametrize(
    "heading",
    [
        "# References {-}",
        "# References {.unnumbered}",
        "# References {#refs .unnumbered}",
        "References {-}\n==============",
        "# References # {-}",
    ],
)
def test_audit_cuts_at_a_references_heading_with_pandoc_attributes(
    tmp_path: Path, heading: str
) -> None:
    """Pandoc users write an unnumbered reference heading as `# References {-}`, and only
    `[\\s*_:.|]` could follow the heading word. No heading was found, nothing was cut, and
    an entry no shape recognises, a book here, had every number reported as a finding, so
    `--strict` failed on the bibliography."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77, "sens": 4.56}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        f"We saw 77 cases.\n\n{heading}\n\n{_BOOK}\n\n# Appendix {{#sec-appendix}}\n\n"
        "The sensitivity estimate was 4.65.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["4.65"]
    assert report.reference_like == []
    assert len(report.not_audited) == 1


def test_audit_cuts_at_a_styled_references_heading_with_pandoc_attributes(
    tmp_path: Path,
) -> None:
    """A heading style marks the paragraph as a heading, as `#` does in Markdown."""
    from manuscript_guard.audit import audit

    styles = (
        f"<w:styles {W}>"
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
        "</w:styles>"
    )
    outputs = _outputs(tmp_path, '{"n": 77, "sens": 4.56}')
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We saw 77 cases.")
        + _p("References {-}", "Heading1")
        + _p(_BOOK)
        + _p("Appendix", "Heading1")
        + _p("The sensitivity estimate was 4.65."),
        {"word/styles.xml": styles},
    )
    report = audit([paper], [outputs])
    assert [c.text for c in report.unmatched] == ["4.65"]
    assert len(report.not_audited) == 1


def test_audit_does_not_take_an_unmarked_line_with_braces_for_a_references_heading(
    tmp_path: Path,
) -> None:
    """An attribute block is markup only on a heading. On a line of prose, or a paragraph
    in Word with no heading style, pandoc and Word print "References {-}" as it stands, and
    taking it for a heading would hide everything after it."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    markdown = tmp_path / "paper.md"
    markdown.write_text(
        "We saw 77 cases, as the section headed\nReferences {-}\n"
        "explains. The pooled reporting odds ratio was 9.99.\n",
        encoding="utf-8",
    )
    word = _docx(
        tmp_path / "paper.docx",
        _p("We saw 77 cases.") + _p("References {-}") + _p("The pooled ratio was 9.99."),
    )
    for paper in (markdown, word):
        report = audit([paper], [outputs])
        assert [c.text.rstrip(".") for c in report.unmatched] == ["9.99"], paper.name
        assert report.not_audited == [], paper.name


def test_audit_does_not_cut_at_a_heading_that_prints_its_braces_or_its_hash(
    tmp_path: Path,
) -> None:
    """Pandoc reads no quoted value that opens with a space, so it prints
    `# References {title=" Works cited"}` braces and all. And closing `#`s belong to an ATX
    heading: a setext heading or a Word heading reading "References #" prints the `#`.
    Taken for reference headings, each cut the paragraph after it, and its number went
    unread."""
    from manuscript_guard.audit import audit

    styles = (
        f"<w:styles {W}>"
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
        "</w:styles>"
    )
    outputs = _outputs(tmp_path, '{"n": 77}')
    papers = []
    for index, heading in enumerate(
        ['# References {title=" Works cited"}', "References #\n------------"]
    ):
        path = tmp_path / f"paper{index}.md"
        path.write_text(
            f"We saw 77 cases.\n\n{heading}\n\nThe pooled reporting odds ratio was 9.99.\n",
            encoding="utf-8",
        )
        papers.append(path)
    papers.append(
        _docx(
            tmp_path / "paper.docx",
            _p("We saw 77 cases.")
            + _p("References #", "Heading1")
            + _p("The pooled ratio was 9.99."),
            {"word/styles.xml": styles},
        )
    )
    for paper in papers:
        report = audit([paper], [outputs])
        assert [c.text.rstrip(".") for c in report.unmatched] == ["9.99"], paper.name
        assert report.not_audited == [], paper.name


@pytest.mark.parametrize(
    "heading",
    [
        "# References {-}\N{NO-BREAK SPACE}",
        "# References {-}\N{IDEOGRAPHIC SPACE}",
        "# References {-}\N{THIN SPACE}",
        "# References {-}\f",
        "# References #\N{NO-BREAK SPACE}",
        "# References {.\N{SUPERSCRIPT TWO}}",
        "# References {\N{SUPERSCRIPT TWO}=1}",
        "# References {.\N{ROMAN NUMERAL EIGHT}}",
    ],
)
def test_audit_does_not_cut_at_braces_or_a_hash_pandoc_prints(
    tmp_path: Path, heading: str
) -> None:
    """`strip()` takes every Unicode space, and pandoc allows only spaces and tabs after a
    block or a closing `#`: a no-break space after `{-}` leaves the braces printed. And a
    class or a key opens with a letter, where `[^\\W\\d_]` also took `\u00b2` and `\u2167`. Each was
    read as a reference heading, and the paragraph after it was cut unread."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        f"We saw 77 cases.\n\n{heading}\n\nThe pooled ratio was 9.99.\n", encoding="utf-8"
    )
    report = audit([paper], [outputs])
    assert "9.99" in [c.text.rstrip(".") for c in report.unmatched]
    assert report.not_audited == []


def test_audit_does_not_cut_at_a_word_heading_that_prints_its_hashes(tmp_path: Path) -> None:
    """Closing `#`s are Markdown syntax. A Word Heading 1 reading "# References #" prints
    both, and was read as a Markdown heading with its closing `#` taken off."""
    from manuscript_guard.audit import audit

    styles = (
        f"<w:styles {W}>"
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
        "</w:styles>"
    )
    outputs = _outputs(tmp_path, '{"n": 77}')
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We saw 77 cases.")
        + _p("# References #", "Heading1")
        + _p("The pooled ratio was 9.99."),
        {"word/styles.xml": styles},
    )
    report = audit([paper], [outputs])
    assert [c.text.rstrip(".") for c in report.unmatched] == ["9.99"]
    assert report.not_audited == []


@pytest.mark.parametrize(
    "results",
    [
        "# Results {#sec-results}",
        '# Results {#sec-results title="the \\"main\\" results"}',
        "# Results {#sec-results note=a\\}b}",
        "# Results {#sec-results}\n\n###",
        "# Results {#sec-results lang=fr\u00a0FR}",
        '# Results {#sec-results title="\N{NEXT LINE}x y"}',
        '# Results {#sec-results title="\N{LINE SEPARATOR}x y"}',
    ],
)
def test_g2_reads_a_results_heading_with_pandoc_attributes_as_results(
    project: Path, results: str
) -> None:
    """A heading's title kept its attribute block, and `is_methods` matches a title whole.
    So `# Results {#sec-results}` was not a Results heading, and a subsection under it named
    like a Methods one, "Sensitivity analyses", made a reported `p < 0.001` the alpha chosen
    in advance. The first fix read no backslash escapes in a value, which pandoc reads, and
    read the heading's line to the end of the match, which ran on past a blank line to a
    line of `#`s. The second ended an unquoted value at a no-break space, where pandoc ends
    one only at a space, a tab, a line break or `}`. The third refused a quoted value that
    opens with any `\\s`, where pandoc refuses only its own spaces, and U+0085 or U+2028 is
    not one of them."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    text = text.replace("\n# Results\n", f"\n{results}\n", 1)
    text = text.replace(
        "\n# Discussion\n",
        "\n## Sensitivity analyses\n\nThe excess was significant (p < 0.001).\n\n# Discussion\n",
        1,
    )
    path.write_text(text, encoding="utf-8")
    assert "unclassified-number" in codes(gate_report(project))


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
        # A comment inside the YAML. On a line of its own the comment makes the header not
        # YAML, which pandoc refuses to build, so it sits in a value here.
        "---\ntitle: A study <!-- keep in step with paper.yaml -->\n# References\n"
        "bibliography: refs.bib\n---\n",
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


_CLAIM_LINE = "The excess was significant (p < 0.001).\n"
_RULED = "\n## Methods\n\nCases were compared with non-cases.\n\n---\n\n" + _CLAIM_LINE

_OPENING_RULES = [
    # YAML metadata below the front matter: pandoc prints none of it, and a `title:` in it
    # replaces paper.yaml's.
    "---\nnote: |\n  Methods\n---\n",
    "---\n# Methods\nnote: v\n...\n",
    # Not YAML: pandoc reads a table, whose lines are cells, not headings.
    "---\nMethods\n---\n",
    "----\nMethods\n\n## Results\n----\n",
    # Directly under a setext heading, the rule is not its underline.
    "Results\n-------\n---\nMethods\n---\n",
    # A setext heading itself: `#` is the one way to write a heading with nothing to judge.
    "Methods\n-------\n",
]


@pytest.mark.parametrize("block", _OPENING_RULES)
def test_a_rule_with_a_line_under_it_is_refused(project: Path, block: str, capsys) -> None:
    """Below the front matter, pandoc reads a line of dashes with a line directly under it
    as YAML metadata or as a table, and neither prints a heading. The gates read prose and
    took the closing rule for a setext underline: under `## Results`, `Methods` in a YAML
    comment or a one-cell table headed the paragraph after, and `p < 0.001` in it passed as
    the alpha chosen in advance. Modelling pandoc's readers here was tried and did not hold,
    so the shape is refused, by `check` and by the build."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{block}\n{_CLAIM_LINE}", "utf-8")
    assert main(["check", str(project), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert "rule-opens-a-block" in {f["code"] for f in findings if f["severity"] == "fail"}
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "pandoc may read as a heading's underline, YAML metadata or a table" in (
        capsys.readouterr().out
    )


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_import_takes_back_a_document_built_before_its_source_was_refused(
    project: Path, tmp_path: Path
) -> None:
    """A document built from a setext heading before the refusal existed came back and was
    refused, and rewriting the heading as the hint said changed the digest, so it was then
    refused as built from another version. The refusal belongs to `check` and the build,
    which still make the author rewrite the heading before the next document."""
    from manuscript_guard.build import OFFLINE, assemble, build_document
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\nSensitivity analyses\n--------------------\n\nText.\n", "utf-8")
    loaded = load_project(project)[0]
    namespace, results, _literature, _report = load_namespace(loaded)
    assembled, report = assemble(loaded, namespace, results)
    assert not report.ok, "the source is refused now"
    built = build_document(loaded, assembled, mode=OFFLINE)
    returned = tmp_path / "back.docx"
    returned.write_bytes(built.output.read_bytes())
    assert main(["import", str(returned), str(project)]) == 0


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    ("block", "said"),
    [
        # A `<!--` pandoc prints as code opens a comment for the heading scan, which then
        # read no rule, while pandoc merged the YAML block's title over paper.yaml's. Written
        # `\<!--` here first, which #39 taught the gates to read as pandoc does; indented
        # code is one place the gates' comment reading still does not know.
        (
            "Run it as:\n\n    make all <!-- aside\n\n::: note\n---\ntitle: Evil\n...\n:::\n\n"
            "later -->\n",
            "title",
        ),
        # A title continuing a paragraph over `===`: the gates read a Methods heading pandoc
        # prints as text, and put the claim under it. Named with its file and line.
        (f"We also saw\nMethods\n=======\n\n{_CLAIM_LINE}", "'Methods' at main.md:"),
    ],
)
def test_the_build_refuses_what_pandoc_reads_otherwise(
    project: Path, block: str, said: str, capsys
) -> None:
    """Every shape the refusals list was found by a review, and each round found more: the
    fifth found five that put another title on the title page. So the build asks pandoc
    how it reads the document it is about to make, and stops when the metadata holds
    anything the build's header did not set, or the headings differ from the gates'."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{block}", encoding="utf-8")
    capsys.readouterr()
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    err = capsys.readouterr().err
    assert "pandoc reads" in err and said in err, err
    # Said of these and not of TeX in the text, which `check` asks pandoc about too.
    assert "`check` cannot see this, and the build asks pandoc." in err, err
    assert not (project / "build" / "manuscript.UNCHECKED.docx").exists()


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_misread_supplement_fails_the_build_and_leaves_no_old_copy(
    project: Path, capsys
) -> None:
    """The supplement was reported as not built and the build still exited 0, and `submit`
    packed the supplement from the build before, a version behind the manuscript."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    old = project / "build" / "supplementary.docx"
    assert old.exists()
    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    text = supplement.read_text(encoding="utf-8")
    supplement.write_text(f"{text}\nWe also saw\nMethods\n=======\n\nText.\n", "utf-8")
    capsys.readouterr()
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "pandoc reads" in capsys.readouterr().err
    assert not old.exists()
    assert main(["submit", str(project), "--offline", "--skip-checks"]) == 1


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_import_takes_back_a_document_built_before_the_build_asked_pandoc(
    project: Path, tmp_path: Path
) -> None:
    """`import` rebuilds the document it sent, to compare the returned one with, and that
    rebuild refused a source the build now refuses, a document already out with a
    co-author included."""
    from manuscript_guard.build import OFFLINE, assemble, build_document
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\nWe also saw\nMethods\n=======\n\nText.\n", "utf-8")
    loaded = load_project(project)[0]
    namespace, results, _literature, _report = load_namespace(loaded)
    assembled, _assembly = assemble(loaded, namespace, results)
    built = build_document(loaded, assembled, mode=OFFLINE, verify_reading=False)
    returned = tmp_path / "back.docx"
    returned.write_bytes(built.output.read_bytes())
    assert main(["import", str(returned), str(project)]) == 0


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    "heading",
    [
        "## Limitations <!-- shorten this later -->",
        "## Estimating $\\beta_{1}$",
        "## Change in HbA~1c~ from baseline",
        "## Effect of CO~2~ on growth",
        "## Area in m^2^",
        "## Strengths &amp; limitations",
        "## The set {1, 2, 3}",
        "## The `f{x}` call",
        "## Methods^[A note.]",
        "## Methods[^m]\n\n[^m]: A note.",
        "## See [the site][ref]\n\n[ref]: https://example.org",
        "## Aware**ness**",
        '## <span class="x">Results</span>',
        # Found by the seventh: definitions whose text starts on the next line, and an
        # example reference.
        "## Methods[^m]\n\n[^m]:\n    A note.",
        "## See [the site][ref]\n\n[ref]:\n  https://example.org",
        "## See (@good)\n\n(@good) An example.",
    ],
)
def test_a_heading_pandoc_prints_as_the_gates_read_it_is_not_refused(heading: str) -> None:
    """The sixth review found each refused by the build: the gates' raw title and pandoc's
    printed one split into words differently. The gates' titles are now read by pandoc
    too, so both sides are pandoc's words."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    body = f"# Introduction\n\nText.\n\n{heading}\n\nMore text.\n"
    found = misreading(header + body, header, [("main.md", body)], shutil.which("pandoc"), Path())
    assert found is None, found


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    ("written", "built"),
    [
        ("## Patients on {{results.dose}}mg", "## Patients on 50mg"),
        ("## The {{results.rank}}th percentile", "## The 90th percentile"),
        ("## x{{results.i}} and y", "## x3 and y"),
        ("## Doses of {{results.range}}", "## Doses of 3 to 5 mg"),
    ],
)
def test_a_placeholder_against_letters_is_read_as_its_value(written: str, built: str) -> None:
    """The stand-in for a placeholder was set apart by spaces, so `{{results.dose}}mg`
    read as two words where pandoc printed one, `50mg`, and was refused."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    source = f"# Introduction\n\nText.\n\n{written}\n\nMore text.\n"
    document = f"# Introduction\n\nText.\n\n{built}\n\nMore text.\n"
    found = misreading(
        header + document,
        header,
        [("main.md", source)],
        shutil.which("pandoc"),
        Path(),
        built=[document],
    )
    assert found is None, found


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    ("written", "built"),
    [
        # Found by the eighth: YAML in a footnote's definition, which the build copied into
        # the text it read the header's metadata from, so the title it set went unseen.
        (
            "# Results\n\nA closing remark.[^n]\n\n[^n]:\n    ---\n    title: Evil\n    ...\n",
            None,
        ),
        # A heading in a list item is a heading in the document, and the gates read text.
        ("# Methods\n\n1. # Results\n\n   The excess (p < 0.001).\n", None),
        ("# Methods\n\n- ## Listed\n\nText.\n", None),
        ("# Methods\n\nTerm\n:   ## Inside\n\nText.\n", None),
        # A heading that is only a placeholder matched any heading at its level, so two
        # misreads that cancelled passed: the value is read now, not a wildcard.
        (
            "# Results\n\nWe also saw\n## {{results.x}}\n\nThe `<!--` marker.\n\n## Methods\n\n"
            "The excess (p < 0.001). -->\n\n## Last\n",
            "# Results\n\nWe also saw\n## Subgroups\n\nThe `<!--` marker.\n\n## Methods\n\n"
            "The excess (p < 0.001). -->\n\n## Last\n",
        ),
        # A value that puts a heading in: the gates judged the file as written.
        (
            "# Results\n\nThe rate was {{results.rate}}.\n\nThe excess (p < 0.001).\n",
            "# Results\n\nThe rate was 4.\n\n# Discussion\n\nThe excess (p < 0.001).\n",
        ),
        # Found by the ninth: a heading in a list stood in for one the gates misread, a
        # `# Methods` straight under a line of text that pandoc prints as text. The gates
        # read no heading in a list, so one there is never theirs.
        (
            "# Results\n\nShown in Table 2.\n# Methods\n\nThe excess (p < 0.001).\n\n"
            "- # Methods\n",
            None,
        ),
        (
            "# Results\n\nShown in Table 2.\n# Methods\n\nThe excess (p < 0.001).\n\n"
            "1. # Methods\n",
            None,
        ),
        (
            "# Results\n\nShown in Table 2.\n# Methods\n\nThe excess (p < 0.001).\n\n"
            "Aside\n:   # Methods\n",
            None,
        ),
        # A commented-out footnote holding YAML pandoc cannot read: copied into the titles'
        # own document, it made that run fail, and the check gave up on every heading.
        (
            "# Results\n\nShown in Table 2.\n# Methods\n\nThe excess (p < 0.001).\n\n"
            "<!--\n[^n1]:\n    ---\n    sites: [Caen\n    ...\n-->\n",
            None,
        ),
    ],
)
def test_the_build_refuses_what_its_reading_used_to_let_through(
    written: str, built: str | None
) -> None:
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    document = built or written
    found = misreading(
        header + document,
        header,
        [("main.md", written)],
        shutil.which("pandoc"),
        Path(),
        built=[document],
    )
    assert found is not None


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_deeply_nested_divs_are_compared_or_refused_not_a_crash() -> None:
    """Found reviewing #71: six hundred nested divs overflowed the recursive walk of
    pandoc's reading, and the build stopped on a traceback. Where Python's own JSON reader
    gives up depends on its version and system, before 600 on 3.10, at 2000 on 3.13 on
    Windows and past it on Linux and macOS, so either depth may be compared or refused;
    neither may crash. The walks themselves are tested apart, below the JSON reader."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    for depth in (600, 2000):
        body = (
            "# Results\n\n"
            + "".join(":" * (depth + 3 - i) + " {.d}\n\n" for i in range(depth))
            + "Deep.\n\n"
            + "".join(":" * (4 + i) + "\n\n" for i in range(depth))
        )
        found = misreading(
            header + body, header, [("main.md", body)], shutil.which("pandoc"), Path()
        )
        assert found is None or found.startswith("a document nested too deep"), (
            depth,
            found,
        )


def test_the_walks_of_pandoc_s_reading_take_any_depth() -> None:
    """The review of #65's CI fix: the test above accepts a refusal at any depth, so a walk
    made recursive again would pass it wherever the JSON reader overflows first. A tree
    built in Python, twenty thousand divs deep, is walked on every system alike."""
    from manuscript_guard.build.reading import _headers, _nodes

    depth = 20_000
    tree: list = [{"t": "Header", "c": [2, ["deep", [], []], [{"t": "Str", "c": "Deep"}]]}]
    for _ in range(depth):
        tree = [{"t": "Div", "c": [["", [], []], tree]}]
    tree = [{"t": "BulletList", "c": [tree]}]
    assert [(found.level, found.listed) for found in _headers(tree)] == [(2, True)]
    assert sum(1 for _ in _nodes(tree, lambda node: True)) == depth + 3


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_definition_in_a_comment_is_not_copied_to_the_titles() -> None:
    """Round nine of #65: a commented-out footnote holding YAML pandoc cannot read, copied
    to the titles' run, made it fail. The definitions come from the text the gates do not
    take for code or a comment, so this one is not copied, and the reading agrees."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    body = (
        "# Results\n\nThe excess was significant.\n\n"
        "<!--\n[^n1]:\n    ---\n    sites: [Caen\n    ...\n-->\n"
    )
    found = misreading(
        header + body, header, [("main.md", body)], shutil.which("pandoc"), Path()
    )
    assert found is None, found


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_titles_that_cannot_be_read_while_the_document_can_are_refused() -> None:
    """Round nine of #65's other half: when the titles' run fails and the document reads,
    passing switched the check off for every heading. A footnote-shaped line in a `<pre>`,
    which pandoc prints as raw HTML and the gates copy, holds broken YAML; the heading the
    gates misread under a line of text must not pass with it."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    body = (
        "# Methods\n\nWe also saw it.\n# Results\n\nThe excess was significant.\n\n"
        "<pre>\n[^n1]:\n    ---\n    sites: [Caen\n    ...\n</pre>\n"
    )
    found = misreading(
        header + body, header, [("main.md", body)], shutil.which("pandoc"), Path()
    )
    assert found is not None and found.startswith("the document, but not"), found


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_setext_title_in_a_list_item_is_refused_for_what_pandoc_reads() -> None:
    """Reviewing #65's fixes: the gates read `- Results` over `===` as a heading, marker
    and all, and pandoc a heading inside the list. The build refused it, saying pandoc read
    the line as text."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    body = "# Methods\n\nText.\n\n- Results\n=========\n\nThe excess was 9.87.\n"
    found = misreading(
        header + body, header, [("main.md", body)], shutil.which("pandoc"), Path()
    )
    assert found is not None and "in a list" in found, found


def test_opener_lines_are_read_in_linear_time() -> None:
    """Roman numerals that were single letters too, a comment's pattern that ran across
    later comments, a TeX argument that was also a footnote marker, and a command's name
    that could stop at any letter let one line of a few hundred characters take minutes:
    each could be read more ways than one."""
    import time

    from manuscript_guard.text.sections import rules_opening_blocks

    backslash = chr(92)
    for item, tail in [
        ("i. ", "y ---"),
        ("* <!-- --> ", "y ---"),
        (f"{backslash}a[^x]: ", "y ---"),
        (f"{backslash}ivx. ", "y ---"),
        ("- ", "y - - -"),
    ]:
        text = "# Results\n\nx) " + item * 4000 + tail + "\ntitle: Evil\n"
        started = time.perf_counter()
        rules_opening_blocks(text)
        assert time.perf_counter() - started < 2, item


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    "body",
    [
        # A heading holding block-level HTML: pandoc makes no heading of it, and the gates'
        # title of it made no paragraph on its own, which switched the whole check off.
        "# Discussion <hr>\n\nText.\n",
        (
            "# Results\n\nWe also saw\nMethods\n=======\n\nThe excess (p < 0.001).\n\n"
            "## Notes <div></div>\n\nNone.\n"
        ),
        # A paragraph of the titles' own taken for a title, its first word for the lead.
        (
            "# Intro\n\nText.\n\n## Methods <div>x</div> dropped Results\n\n"
            "The ROR was 4.2 (p < 0.001).\n\n- ## Results\n\nText.\n"
        ),
    ],
)
def test_a_title_pandoc_cannot_read_alone_does_not_switch_the_check_off(body: str) -> None:
    """When a title did not come back as a paragraph of its own, the check gave up on the
    headings of the whole document, and a misread elsewhere in it built."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    found = misreading(header + body, header, [("main.md", body)], shutil.which("pandoc"), Path())
    assert found is not None


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_the_annotated_copy_builds_with_a_subscript_in_a_heading(project: Path) -> None:
    """The annotated copy is marked up for the author to read, not the document sent, and
    its marks changed how a subscript in a heading read: it was refused as a misread."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("# Discussion", "# Change in HbA~1c~ from baseline"), "utf-8")
    args = ["build", str(project), "--offline", "--annotated", "--skip-checks"]
    assert main(args) == 0


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_refused_build_into_the_build_directory_itself_does_not_crash(
    project: Path, capsys
) -> None:
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\nWe also saw\nMethods\n=======\n\nText.\n", "utf-8")
    (project / "build").mkdir(exist_ok=True)
    out = project / "build"
    assert main(["build", str(project), "--offline", "--skip-checks", "-o", str(out)]) == 1


# ------------------------------------------------- a document reviewed blind names no author

_W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_R_NS = (
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _blind(root: Path, kind: str = "double") -> None:
    profile = root / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    document["blinding"] = kind
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _word(path: Path, body: str = "", **parts: str) -> Path:
    """A document holding `body` as its paragraphs, and any other part as it is given."""
    document = f"<w:document {_W_NS}><w:body>{body}</w:body></w:document>"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
        for name, xml in parts.items():
            archive.writestr(name.replace("__", "/").replace("_xml", ".xml"), xml)
    return path


def _named(root: Path, document: Path) -> list[tuple[str, str]]:
    from manuscript_guard.build.blinding import check_blinded

    project, _ = load_project(root)
    found = check_blinded(project, document).findings
    assert all(f.code == "blind-document-names-author" and f.severity == "fail" for f in found)
    return sorted(
        (re.match(r"(['\"])(.*?)\1 is in ", f.message)[2],
         re.search(r" is in (.*) of ", f.message)[1])
        for f in found
    )


_CORE_NS = (
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)


@pytest.mark.parametrize(
    ("body", "parts", "said"),
    [
        pytest.param(
            "<w:p><w:r><w:t>As Ada</w:t></w:r><w:r><w:br/><w:t>Example showed</w:t></w:r></w:p>",
            {}, [("Ada Example", "the text")], id="a name split across a run and a break",
        ),
        pytest.param(
            "<w:p><w:del w:author='Someone'><w:r><w:delText>Example, A.</w:delText></w:r>"
            "</w:del></w:p>",
            {}, [("Ada Example", "the text")], id="a name a tracked change deleted",
        ),
        pytest.param(
            "", {"word__footnotes_xml": f"<w:footnotes {_W_NS}><w:footnote><w:p><w:r><w:t>"
                 "B. Sample, unpublished.</w:t></w:r></w:p></w:footnote></w:footnotes>"},
            [("Blaise Sample", "the text")], id="a name in a footnote",
        ),
        pytest.param(
            "<w:p><w:r><w:t>See https://orcid.org/0000-0002-1825-0097 or write to "
            "ADA.EXAMPLE@INVALID.EXAMPLE.</w:t></w:r></w:p>",
            {}, [("the ORCID iD 0000-0002-1825-0097", "the text"),
                 ("the e-mail address ada.example@invalid.example", "the text")],
            id="an ORCID iD and an e-mail address",
        ),
        pytest.param(
            "<w:p><w:r><w:t>Done at the department of clinical\u00a0 pharmacology.</w:t></w:r>"
            "</w:p>",
            {}, [("Department of Clinical Pharmacology", "the text")],
            id="an institution in another case and spacing",
        ),
        pytest.param(
            "", {"docProps__core_xml": f"<cp:coreProperties {_CORE_NS}><dc:creator>Ada Example"
                 "</dc:creator><cp:lastModifiedBy>Blaise Sample</cp:lastModifiedBy>"
                 "</cp:coreProperties>"},
            [("Ada Example", "the document's author (dc:creator)"),
             ("Blaise Sample", "the document's last editor (cp:lastModifiedBy)")],
            id="Word's author fields",
        ),
        pytest.param(
            "<w:p><w:ins w:author='Ada Example'><w:r><w:t>new</w:t></w:r></w:ins></w:p>",
            {}, [("Ada Example", "the author of a tracked change or a comment")],
            id="the author of a tracked change",
        ),
        pytest.param(
            "", {"word__people_xml": "<w15:people xmlns:w15='urn:w15'><w15:person "
                 "w15:author='Blaise Sample'/></w15:people>"},
            [("Blaise Sample", "the people who edited it")], id="the people who edited it",
        ),
        pytest.param(
            "", {"word__media__image1.svg": "<svg xmlns='http://www.w3.org/2000/svg'><text>"
                 "Example University Graduate School of Medicine</text></svg>"},
            [("Example University Graduate School of Medicine", "a figure (image1.svg)")],
            id="the text of a figure the document holds",
        ),
        # Round 1 of #273: matplotlib writes a DOCTYPE into every SVG, and the parser's
        # refusal of it stopped the whole check. One with entities is read for nothing, and
        # the rest of the document still is.
        pytest.param(
            "<w:p><w:r><w:t>Ada Example.</w:t></w:r></w:p>",
            {"word__media__a.svg": '<?xml version="1.0"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG '
             '1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg xmlns='
             '"http://www.w3.org/2000/svg"><text>B. Sample</text></svg>',
             "word__media__b.svg": '<!DOCTYPE svg [<!ENTITY e "x">]><svg><text>&e;</text></svg>'},
            [("Ada Example", "the text"), ("Blaise Sample", "a figure (a.svg)")],
            id="a figure with a DOCTYPE",
        ),
        pytest.param(
            "<w:p><w:r><w:t>As B. O\N{RIGHT SINGLE QUOTATION MARK}Sample said.</w:t></w:r></w:p>",
            {}, [("Blaise O'Sample", "the text")], id="an apostrophe printed curly",
        ),
        # Round 1 of #273: a link's address, a field's code and Word's company field.
        pytest.param(
            "", {"word___rels__document.xml.rels": "<Relationships xmlns='http://schemas."
                 "openxmlformats.org/package/2006/relationships'><Relationship Id='rId9' "
                 "Type='hyperlink' Target='mailto:ada.example@invalid.example' "
                 "TargetMode='External'/></Relationships>"},
            [("the e-mail address ada.example@invalid.example", "the address of a link")],
            id="a link's address",
        ),
        pytest.param(
            "<w:p><w:r><w:fldChar w:fldCharType='begin'/></w:r><w:r><w:instrText "
            "xml:space='preserve'> HYPERLINK \"https://orcid.org/</w:instrText></w:r><w:r>"
            "<w:instrText>0000-0002-1825-0097\" </w:instrText></w:r><w:r><w:fldChar "
            "w:fldCharType='separate'/></w:r><w:r><w:t>my record</w:t></w:r><w:r><w:fldChar "
            "w:fldCharType='end'/></w:r></w:p>", {},
            [("the ORCID iD 0000-0002-1825-0097", "a field's code")], id="a field's code",
        ),
        pytest.param(
            "<w:p><w:fldSimple w:instr=' HYPERLINK \"mailto:ada.example@invalid.example\" '>"
            "<w:r><w:t>write</w:t></w:r></w:fldSimple></w:p>", {},
            [("the e-mail address ada.example@invalid.example", "a field's code")],
            id="a simple field's code",
        ),
        # Round 2 of #349: a table pasted as a link to its file, a field nested in a link's
        # code, and a link's field left open at the paragraph's end.
        pytest.param(
            "<w:p><w:r><w:fldChar w:fldCharType='begin'/></w:r><w:r><w:instrText> LINK "
            "Excel.Sheet.12 \"C:/Users/Ada Example/Documents/t.xlsx\" \"Sheet1\" "
            "</w:instrText></w:r><w:r><w:fldChar w:fldCharType='separate'/></w:r><w:r><w:t>"
            "a table</w:t></w:r><w:r><w:fldChar w:fldCharType='end'/></w:r></w:p>", {},
            [("Ada Example", "a field's code")], id="a table linked to its file",
        ),
        pytest.param(
            "<w:p><w:r><w:fldChar w:fldCharType='begin'/></w:r><w:r><w:instrText> HYPERLINK "
            "\"mailto:</w:instrText></w:r><w:r><w:fldChar w:fldCharType='begin'/></w:r><w:r>"
            "<w:instrText> MERGEFIELD x </w:instrText></w:r><w:r><w:fldChar "
            "w:fldCharType='end'/></w:r><w:r><w:instrText>ada.example@invalid.example\" "
            "</w:instrText></w:r><w:r><w:fldChar w:fldCharType='separate'/></w:r><w:r><w:t>"
            "write</w:t></w:r><w:r><w:fldChar w:fldCharType='end'/></w:r></w:p>", {},
            [("the e-mail address ada.example@invalid.example", "a field's code")],
            id="a field nested in a link's code",
        ),
        pytest.param(
            "<w:p><w:r><w:fldChar w:fldCharType='begin'/></w:r><w:r><w:instrText> HYPERLINK "
            "\"https://orcid.org/0000-0002-1825-0097\" </w:instrText></w:r></w:p>", {},
            [("the ORCID iD 0000-0002-1825-0097", "a field's code")],
            id="a link's field left open",
        ),
        pytest.param(
            "", {"docProps__app_xml": "<Properties xmlns='http://schemas.openxmlformats.org/"
                 "officeDocument/2006/extended-properties'><Company>Example University "
                 "Graduate School of Medicine</Company></Properties>"},
            [("Example University Graduate School of Medicine",
              "the document's company (Company)")], id="Word's company field",
        ),
        # The alternative text the build writes from a figure's guard file, or Word lets a
        # co-author type: read aloud, printed nowhere.
        pytest.param(
            "<w:p><w:r><w:drawing><wp:inline xmlns:wp='http://schemas.openxmlformats.org/"
            "drawingml/2006/wordprocessingDrawing'><wp:docPr id='1' name='Picture' "
            "descr='The estimate, as Example and Sample drew it' title='By Ada Example'/>"
            "</wp:inline></w:drawing></w:r></w:p>", {},
            [("Ada Example", "the alternative text of a picture")],
            id="a picture's alternative text",
        ),
    ],
)  # fmt: skip
def test_a_document_reviewed_blind_names_no_author_anywhere_word_keeps_one(
    project: Path, tmp_path: Path, body: str, parts: dict, said: list
) -> None:
    """Where the journal's review is double-blind, an author's name, ORCID iD,
    e-mail address or institution is found in the text, a figure, and every field Word
    keeps an author in, which a co-author's copy comes back with."""
    _blind(project)
    authors = project / "authors.yaml"
    if "O'Sample" in str(said):
        authors.write_text(authors.read_text(encoding="utf-8").replace(
            "family: Sample", "family: \"O'Sample\""), encoding="utf-8")  # fmt: skip
    document = _word(tmp_path / "manuscript.docx", body, **parts)
    assert _named(project, document) == sorted(said)


def test_a_place_building_again_does_not_clear_says_how_to_clear_it(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #349: a link's address, a field's code and the Company had the text's
    hint, "build again", which clears none of them."""
    from manuscript_guard.build.blinding import check_blinded

    _blind(project)
    company = ("<Properties xmlns='http://schemas.openxmlformats.org/officeDocument/2006/"
               "extended-properties'><Company>Example University Graduate School of Medicine"
               "</Company></Properties>")  # fmt: skip
    document = _word(tmp_path / "a.docx", **{"docProps__app_xml": company})
    [found] = check_blinded(load_project(project)[0], document).findings
    assert "Inspect Document" in found.hint and "build again" not in found.hint


def test_what_the_blind_check_reads_wrongly_is_pinned(project: Path, tmp_path: Path) -> None:
    """Known gaps (#273): an institution named in two words is not looked for, and an
    initial with its stop before a word that is an author's family name reads as that
    author, "Panel A. Example" as Ada Example."""
    _blind(project)
    authors = project / "authors.yaml"
    authors.write_text(authors.read_text(encoding="utf-8").replace(
        "Department of Clinical Pharmacology, Example University Graduate School of Medicine",
        "Example Institute"), encoding="utf-8")  # fmt: skip
    body = "<w:p><w:r><w:t>Data from the Example Institute were used.</w:t></w:r></w:p>"
    assert _named(project, _word(tmp_path / "a.docx", body)) == []
    body = "<w:p><w:r><w:t>Panel A. Example of the design.</w:t></w:r></w:p>"
    assert _named(project, _word(tmp_path / "b.docx", body)) == [("Ada Example", "the text")]


def test_a_document_reviewed_blind_may_cite_its_authors_in_its_reference_list(
    project: Path, tmp_path: Path
) -> None:
    """A self-citation prints the authors' names in the reference list, which the journals
    ask for in the third person rather than taken out, and a localised Word may give the
    list's style another identifier. A family name alone, a name with a letter more, a city
    and a country name nobody, nor does an article before the family name or a letter after
    it (round 1 of #273: "A Cross-sectional study" named Anna Cross); and a review that is
    not blind is not read."""
    _blind(project)
    body = (
        "<w:p><w:pPr><w:pStyle w:val='Bibliography'/></w:pPr><w:r><w:t>Example A, Sample B. "
        "A study. 2019.</w:t></w:r></w:p>"
        "<w:p><w:pPr><w:pStyle w:val='ab'/></w:pPr><w:r><w:t>Example, A. A study.</w:t></w:r>"
        "</w:p>"
        "<w:p><w:r><w:t>Example data from Springfield, Japan, as Ada Examples said. A Example "
        "study, on Example A and Example B.</w:t></w:r></w:p>"
    )
    styles = (
        f"<w:styles {_W_NS}><w:style w:type='paragraph' w:styleId='ab'>"
        "<w:name w:val='Bibliography'/></w:style></w:styles>"
    )
    assert _named(project, _word(tmp_path / "a.docx", body, word__styles_xml=styles)) == []
    # Round 1 of #349: a live citation's field code holds the cited work's data, a
    # self-citation's publisher among it, and a link in the reference list is the list's.
    cited = (
        "<w:p><w:r><w:fldChar w:fldCharType='begin'/></w:r><w:r><w:instrText> ADDIN "
        "ZOTERO_ITEM CSL_CITATION {\"citationItems\":[{\"itemData\":{\"publisher\":\"Example "
        "University Graduate School of Medicine\"}}]}</w:instrText></w:r><w:r><w:fldChar "
        "w:fldCharType='separate'/></w:r><w:r><w:t>(1)</w:t></w:r><w:r><w:fldChar "
        "w:fldCharType='end'/></w:r></w:p>"
        f"<w:p {_R_NS}><w:pPr><w:pStyle w:val='Bibliography'/></w:pPr><w:hyperlink "
        "r:id='rId5'><w:r><w:t>Example A. A thesis.</w:t></w:r></w:hyperlink></w:p>"
    )
    links = (
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId5' Type='hyperlink' Target='mailto:ada.example@invalid.example' "
        "TargetMode='External'/></Relationships>"
    )
    # Round 2 of #349: pandoc copies every link into the notes' part, under the same
    # identifier or another, and the address is the reference list's there too.
    rels = {"word___rels__document.xml.rels": links,
            "word___rels__footnotes.xml.rels": links.replace("rId5", "rId9")}
    # Round 3 of #349: and a field elsewhere that links to the same address.
    cited += ("<w:p><w:fldSimple w:instr=' HYPERLINK \"mailto:ada.example@invalid.example\" '>"
              "<w:r><w:t>write</w:t></w:r></w:fldSimple></w:p>")  # fmt: skip
    document = _word(tmp_path / "cited.docx", cited, **rels)
    assert _named(project, document) == []
    named = "<w:p><w:r><w:t>As Ada Example showed.</w:t></w:r></w:p>"
    assert _named(project, _word(tmp_path / "b.docx", named)) == [("Ada Example", "the text")]
    _blind(project, "single")
    assert _named(project, _word(tmp_path / "c.docx", named)) == []


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_document_reviewed_blind_is_built_and_packed_only_without_its_authors(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The example names no author and builds. An author named in the Discussion is said
    and the build exits 1; a copy edited in Word, whose author field names one, is not
    packed. A self-citation the build prints is not a name to take out: the reference list
    is not read, and an author-date citation prints the family name alone."""
    from manuscript_guard.cli import main

    _blind(project)
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0
    authors = project / "authors.yaml"
    text = authors.read_text(encoding="utf-8")
    authors.write_text(text.replace("given: Ada\n    family: Example", "given: Anne\n    "
                                    "family: Fictional"), encoding="utf-8")  # fmt: skip
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0
    built = project / "build" / "manuscript.docx"
    edited = project / "final" / "manuscript.docx"
    edited.parent.mkdir()
    with zipfile.ZipFile(built) as source, zipfile.ZipFile(edited, "w") as copy:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "docProps/core.xml":
                data = data.replace(b"<dc:creator></dc:creator>",
                                    b"<dc:creator>Anne Fictional</dc:creator>")  # fmt: skip
            copy.writestr(item, data)
    capsys.readouterr()
    assert main(["submit", str(project), "--document", str(edited), "--skip-checks"]) == 1
    assert "'Anne Fictional' is in the document's author (dc:creator)" in capsys.readouterr().out
    assert not (project / "build" / "submission" / "manuscript.docx").exists()
    source = main_md(project)
    source.write_text(source.read_text(encoding="utf-8").replace(
        "# Discussion\n\n", "# Discussion\n\nAs Anne Fictional showed before, ", 1),
        encoding="utf-8")  # fmt: skip
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "'Anne Fictional' is in the text of manuscript.docx" in capsys.readouterr().out


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_submit_refuses_a_pack_missing_its_document_or_its_supplement(
    project: Path, capsys
) -> None:
    """A refused build removes its document, and `submit --document` then packed nothing
    in its place, and no supplement, and exited 0."""
    from manuscript_guard.cli import main

    missing = project / "build" / "manuscript.docx"
    assert main(["submit", str(project), "--document", str(missing), "--skip-checks"]) == 2
    assert main(["build", str(project), "--offline"]) == 0
    # A document edited elsewhere is packed with the supplement the build made.
    elsewhere = project / "final" / "manuscript-edited.docx"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(missing.read_bytes())
    assert main(["submit", str(project), "--document", str(elsewhere), "--skip-checks"]) == 0
    assert (project / "build" / "submission" / "supplementary.docx").exists()
    (project / "build" / "supplementary.docx").unlink()
    assert main(["submit", str(project), "--document", str(missing), "--skip-checks"]) == 2


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_submit_does_not_delete_a_document_inside_the_pack(project: Path) -> None:
    """Found by the ninth review: the pack's directory is emptied before the document is
    copied into it, so `--document build/submission/manuscript.docx` deleted the document,
    perhaps a co-author's edited copy, and exited 0 with a pack that lacked it."""
    from manuscript_guard.cli import main

    assert main(["submit", str(project), "--offline"]) == 0
    inside = project / "build" / "submission" / "manuscript.docx"
    written = inside.read_bytes()
    assert main(["submit", str(project), "--document", str(inside), "--skip-checks"]) == 2
    assert inside.read_bytes() == written


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_the_build_reads_a_binding_in_a_heading_as_its_value(project: Path) -> None:
    """The gates read `{{results.cohort.n}}` where pandoc reads the number: not a
    difference, and neither are emphasis or an identifier."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    heading = "\n## A cohort of {{results.cohort.n}} *reports* {#sec-cohort}\n\nText.\n"
    source.write_text(f"{text}{heading}", encoding="utf-8")
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0


_EVIL = "---\ntitle: Evil\nnote: |\n  Methods\n---\n"


@pytest.mark.parametrize(
    "block",
    [
        # Found by review: a line the heading scan takes for a setext title but pandoc does
        # not, so the rule under it was let through as an underline while pandoc read YAML
        # and took its title for the document's.
        f"::: note\nA note.\n:::\n{_EVIL}",
        f"::: note\n{_EVIL}:::\n",
        f"<div>\nA note.\n</div>\n{_EVIL}",
        f"\\begin{{center}}\nx\n\\end{{center}}\n{_EVIL}",
        f"+---+---+\n| a | b |\n+---+---+\n{_EVIL}",
        f"a | b\n--|--\nc | d\n{_EVIL}",
        f"    x <- 1\n    y <- 2\n{_EVIL}",
        f"{{{{table.two_by_two}}}}\n{_EVIL}",
        # A lazy line of a quotation or a list item under the rule: pandoc reads a table in
        # the quotation or the item, the heading scan a heading from the closing rule.
        "> ---\nMethods\n---\n",
        "* ---\n  Methods\n---\n",
        "-\nMethods\n-\n",
        # Under the second line of a paragraph a rule is text to pandoc, not an underline.
        "We also saw\nMethods\n---\n",
        # Rules of two dashes, spaced dashes, or indented a little open tables too.
        "--\nMethods\n--\n",
        "- - -\nMethods\n- - -\n",
        "  ---\nMethods\n  ---\n",
        # ...where only the opening rule can be caught: the closing one is under a heading.
        "--\ncell\n\n## Results\n--\n",
        "- -\ncell\n\n## Results\n- -\n",
        # A comment closing on the rule's line: pandoc reads on from the `-->`.
        f"<!-- x\nabc -->{_EVIL}",
        # Found by the second review: a comment on the line above the title is no break.
        # In a paragraph the title continues it; at a block start the build's bookmark goes
        # in front of the comment, and the title then continues that paragraph.
        "We also saw it.\n<!-- check with reviewer 2 -->\nMethods\n-------\n",
        "<!-- reviewer 2 asked for this -->\nMethods\n-------\n",
        # Found by the third: a table placeholder spelled with spaces, or after other text,
        # is still where the build puts a table, which takes the lines under it for caption.
        "{{ table.two_by_two }}\n---\nMethods\n---\n",
        "See {{table.two_by_two}}\n---\nMethods\n---\n",
        # Found by the fourth, each a title the exemption for setext headings let through:
        # a comment after the underline, which pandoc prints with it as text;
        "Methods\n------- <!-- check -->\n\n",
        "Methods\n-------<!-- x -->\n\n",
        # a comment whose last line looks like a heading, taken for a break above the title;
        "<!-- Removed at a reviewer's request:\n## Sensitivity analysis -->\nMethods\n-------\n\n",
        # a rule with a blank line under it, under a line pandoc makes its heading;
        "# Methods\n---\n\n## Statistical analysis\n\n",
        "> Cases were compared with non-cases.\n---\n\n",
        # a comment closing on the rule's line, its last line indented;
        "<!-- reviewer note\n  on two lines --> ---\ntitle: Evil\n...\n\n",
        # a comment inside a placeholder's braces, which the build removes first;
        "{{table.baseline<!-- x -->}}\n---\ntitle: Evil\n...\n",
        # a listing pandoc does not make, and an underline pandoc does not read.
        "We also saw it.\n~~~\nx <- 1\n~~~\nMethods\n-------\n\n",
        "We also saw\nPart\n====\nMethods\n-------\n\n",
        # So no line of dashes passes under a title: every one of those was a title the
        # exemption had to judge, and a plain one is refused with them, `#` doing the same.
        "Results\n-------\n\nText.\n",
        "Results\n---\nText directly under a heading.\n",
        "Results\n-\n\nText.\n",
        "```\nx\n```\nResults\n-------\n",
        "## Section\nResults\n-------\n",
        "Part\n====\nResults\n-------\n",
        "2. Methods\n----------\n",
        "2) Methods\n----------\n",
        "{{results.cohort.n}} reports\n---\n",
        # Nor over a line: pandoc reads an item, YAML or a table from it.
        "-\n  an empty item's text\n",
        # Found by the fifth: pandoc starts a block after markup, or a list, definition or
        # footnote marker, and reads the dashes after it as YAML.
        "<div>---\ntitle: Evil\n...\n</div>\n",
        "<hr>---\ntitle: Evil\n...\n",
        "<div>\nA note.\n\n</div>---\ntitle: Evil\n...\n",
        "## Note\n<!-- aside -->    ---\ntitle: Evil\n...\n",
        "## Note\n<!-- aside -->\t---\ntitle: Evil\n...\n",
        "## Note\n\\newpage ---\ntitle: Evil\n...\n",
        "## Note\n\\end{center}---\ntitle: Evil\n...\n",
        "Term\n:   ---\n    title: Evil\n    ...\n",
        "## Note\n* ---\n  title: Evil\n  ...\n",
        "## Note\n1. ---\n   title: Evil\n   ...\n",
        "## Note\n[^1]: ---\n    title: Evil\n    ...\n",
        # Found by the sixth: markers nested on one line, and a TeX group closed with `}}`.
        "## Note\n* * ---\n    title: Evil\n    ...\n",
        "## Note\n- 1) ---\n     title: Evil\n     ...\n",
        "## Note\n\\newcommand{\\x}{\\textbf{y}}---\ntitle: Evil\n...\n",
        # Found by the seventh: tags that are blocks or inline as pandoc finds them, a
        # processing instruction, a starred command, a marker before markup or a TeX
        # command, a comment closing on the line before either, and a deeper TeX group.
        "## Note\n<del> ---\ntitle: Evil\n...\n",
        "## Note\n<svg> ---\ntitle: Evil\n...\n",
        "## Note\n<?xml version='1.0'?> ---\ntitle: Evil\n...\n",
        "## Note\n\\section*{A} ---\ntitle: Evil\n...\n",
        "## Note\n* \\newpage ---\n  title: Evil\n  ...\n",
        "## Note\n<div> * ---\n  title: Evil\n  ...\n",
        "## Note\n<!-- a\nb --> \\newpage ---\ntitle: Evil\n...\n",
        "## Note\n<!-- a\nb --> * ---\n  title: Evil\n  ...\n",
        "## Note\n\\newcommand{\\x}{\\textbf{\\emph{y}}}---\ntitle: Evil\n...\n",
        # Found by the eighth: four more tags pandoc starts a block behind.
        "## Note\n<applet> ---\ntitle: Evil\n...\n",
        "## Note\n<area> ---\ntitle: Evil\n...\n",
        "## Note\n<frameset> ---\ntitle: Evil\n...\n",
        "## Note\n<isindex> ---\ntitle: Evil\n...\n",
        # Found by the ninth: after a command, `[^1]` is its optional argument to pandoc.
        "## Note\n\\newpage[^1]---\ntitle: Evil\n...\n",
        "## Note\n\\newpage[^1] ---\ntitle: Evil\n...\n",
        "## Note\n\\foo[x][y]{1em} ---\ntitle: Evil\n...\n",
        # Found reviewing #106: pandoc reads a definition's brackets after its groups too.
        "## Note\n\\newcommand{\\foo}[1]{bar} ---\ntitle: Evil\n...\n",
        "## Note\n\\newenvironment{x}[1]{a}{b} ---\ntitle: Evil\n...\n",
        "## Note\n\\newtheorem{thm}{Theorem}[section] ---\ntitle: Evil\n...\n",
        "## Note\n\\titleformat{a}[b]{c}{d}{e}{f} ---\ntitle: Evil\n...\n",
        # Found reviewing #109: three more definitions pandoc reads by their own shape.
        "## Note\n\\DeclareRobustCommand{\\foo}[1]{bar} ---\ntitle: Evil\n...\n",
        "## Note\n\\provideenvironment{x}[1]{a}{b} ---\ntitle: Evil\n...\n",
        "## Note\n\\DeclareMathOperator{\\foo}[x]{bar} ---\ntitle: Evil\n...\n",
    ],
)
def test_every_way_a_rule_can_open_a_block_is_refused(block: str) -> None:
    from manuscript_guard.text.sections import rules_opening_blocks

    text = f"---\ntitle: A study\n---\n\n# Introduction\n\nProse.\n\n{block}\nThe end.\n"
    assert rules_opening_blocks(text) != []


@pytest.mark.parametrize(
    "block",
    [
        "Text.\n\n---\n\nMore text.\n",
        "Text.\n\n- - -\n\nMore text.\n",
        "Text.\n \t\n---\n  \nMore text.\n",
        "Text.\n\n-\n\nMore text.\n",
        "```\n---\nnote: v\n---\n```\n",
        "<!--\n---\nnote: v\n---\n-->\n",
        "The end.\n\n---\n",
        "Results\n=======\n\nText.\n",
        # Dashes in prose are dashes, a range split over lines included.
        "The interval ran from {{results.ror.ci_low}}--\n{{results.ror.ci_high}}.\n",
        "As we said ---\nand as the data show.\n",
        # Found by the sixth: inline markup is no block, and a rule inside a quotation is the
        # quotation's.
        "An area of 3 m<sup>2</sup> ---\nlarge.\n",
        "The [drug]{.smallcaps} --\nwas used.\n",
        "Values x > --\nnext.\n",
        "> Para one.\n>\n> ---\n>\n> Para two.\n",
        # An item that is an en dash: no YAML opens on two dashes.
        "1. a\n2. --\n3. b\n",
        # Found reviewing #65's fixes: pandoc takes brackets as a command's argument only
        # before its groups, and the text after them starts no block.
        "\\vspace{1em}[^x] ---\nnote: v\n...\n",
        "\\textsuperscript{a}[^9] ---\nnext.\n",
        "\\foo[x]{1em}[y] ---\nnext.\n",
    ],
)
def test_a_rule_that_opens_nothing_is_not_refused(block: str) -> None:
    """A line of dashes between blank lines is a thematic break to pandoc, whatever is
    around it; one in code or a comment is not read at all. A setext heading underlined
    with `=` has no dashes to misread."""
    from manuscript_guard.text.sections import rules_opening_blocks

    text = f"---\ntitle: A study\n---\n\n# Introduction\n\n{block}"
    assert rules_opening_blocks(text) == []


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        # A rule, not front matter: the heading prints.
        (f"---\n{_RULED}", ["Methods"]),
        (f"---\n  {_RULED}", ["Methods"]),
        # Front matter, with a YAML comment in it: nothing prints.
        (f"---\n# keep in step\ntitle: A study\n# Methods\n---\n\n{_CLAIM_LINE}", []),
        (f'---\n# Methods\ntitle: "A study <!--"\n---\n-->\n\n{_CLAIM_LINE}', []),
    ],
)
def test_the_build_prints_the_headings_the_gates_read(text: str, printed: list[str]) -> None:
    """The build found the end of the front matter with a pattern of its own. Once the gates
    stopped taking `---` and a blank line for front matter, the build still stripped it: G2
    read the `## Methods` heading inside, so `p < 0.001` after it passed as the alpha chosen
    in advance, and the document printed it with no Methods heading above it. The heading
    scan then blanked comments before it looked for front matter, so a comment on the first
    line of the YAML read as that blank line, and a `# Methods` in the YAML headed the body."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text.sections import headings

    body, _title = strip_front_matter(text)
    assert headings(body) == headings(text) == printed


_INTRODUCTION = (
    "# Introduction\n\nThe first reports came in 2019.\n\n---\n\n# Methods\n\n"
    "Cases were compared with non-cases.\n"
)


@pytest.mark.parametrize(
    "text",
    [
        # Closed by `...`, which YAML and pandoc accept. The build took only `---` and ran on
        # to the horizontal rule, and the Introduction went with the header.
        f"---\ntitle: A study\n...\n\n{_INTRODUCTION}",
        "---\r\ntitle: A study\r\n...\r\n\r\n" + _INTRODUCTION.replace("\n", "\r\n"),
        # Never closed. Pandoc reads to the rule, finds no YAML there and refuses to build.
        f"---\ntitle: A study\n\n{_INTRODUCTION}",
        # Closed, but not a mapping, so not metadata: pandoc prints it.
        f"---\n- first\n- second\n---\n\n{_INTRODUCTION}",
        f"---\nA sentence, not a key.\n...\n\n{_INTRODUCTION}",
    ],
    ids=["closed by dots", "closed by dots, crlf", "never closed", "a list", "a sentence"],
)
def test_the_front_matter_never_takes_the_body_with_it(text: str) -> None:
    """`strip_front_matter` ran to the first `---` line in the file, wherever it was, and
    called everything above it front matter. A header closed by `...` and a rule further
    down took the Introduction out of the built document, out of `import` and out of G13,
    with no warning. The front matter now ends at the first `---` or `...` line, and counts
    only when pandoc keeps it as metadata; anything else is left where pandoc prints it or
    refuses it."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text.sections import headings

    body, _title = strip_front_matter(text)
    assert "The first reports came in 2019." in body
    assert "Introduction" in headings(body)
    assert headings(body) == headings(text)


@pytest.mark.parametrize(
    "header",
    [
        "---\n<!-- keep in step -->\ntitle: A study\n# Methods\n---\n",
        "---\ntitle: A study\n\n# Methods\n\nCases were compared with non-cases.\n\n---\n",
        "---\ntitle: Reporting of hepatic injury: a study\n---\n",
    ],
    ids=["a comment on its first line", "never closed before a rule", "an unquoted colon"],
)
def test_a_header_pandoc_cannot_read_stops_check_and_the_build(
    project: Path, header: str
) -> None:
    """A header pandoc cannot read as YAML was left in the body, for pandoc to refuse. It
    never did: the identifier in front of the header's first paragraph made it prose, the
    build printed the YAML as text and exited 0, and the gates read the `# Methods` in it as
    a heading, so `p < 0.001` under it passed as the alpha chosen in advance. Both now stop
    and name the YAML's error."""
    from manuscript_guard.build.assemble import assemble

    source = main_md(project)
    body = source.read_text(encoding="utf-8").split("\n---\n", 1)[1]
    source.write_text(
        header + "\nThe excess was significant (p < 0.001).\n" + body, encoding="utf-8"
    )
    assert "front-matter-unreadable" in codes(gate_report(project))
    projekt, _ = load_project(project)
    namespace, results, _literature, _report = load_namespace(projekt)
    _assembled, built = assemble(projekt, namespace, results)
    assert "front-matter-unreadable" in codes(built)


@pytest.mark.parametrize(
    ("paper", "shown"),
    [
        ('---\ntitle: "Risk <!-- draft"\n---\n\n## Methods\n\nThe ROR was 9.99. -->\n', {"9.99"}),
        (
            '---\ntitle: "Risk <!-- draft"\n---\n\n# Results\n\nThe ROR was 3.84.\n\n'
            "references\n==========\n\nSmith J. A paper. Lancet. 2019;393:100-10. -->\n\n"
            "# Appendix\n\nThe appendix ROR was 9.99.\n\n<!-- a later note -->\n",
            {"3.84", "9.99"},
        ),
        (
            "---\nabstract: |\n  ```\n---\n\n## Methods\n\nThe ROR was 9.99.\n\n"
            "```r\nx <- 1\n```\n",
            {"9.99"},
        ),
        # A code block in the abstract is still code: its `<!--` opens no comment.
        (
            "---\nabstract: |\n  Drafts were searched for\n\n  ```\n  <!--\n  ```\n\n"
            "  and 9.99% held one. <!-- recheck -->\n---\n\n# Results\n\nIt was 3.84%.\n",
            {"9.99%", "3.84%"},
        ),
    ],
)
def test_nothing_opened_in_the_front_matter_hides_the_body(
    tmp_path: Path, paper: str, shown: set[str]
) -> None:
    """Pandoc reads the YAML apart from the body, and each value apart from the rest. The
    masking read them as one text: a `<!--` in a title ran on to the next `-->` in the body,
    and a fence opener in an abstract paired with a fence in the body, so everything between
    was hidden from G2 and the audit while pandoc printed it. Once the heading scan stopped
    at the front matter and the masking did not, a reference heading between the two cut the
    body's `-->` away, and the title's comment ran on over an appendix. The first fix looked
    for fences in the body alone, so a `<!--` in a code block in the abstract opened a
    comment again."""
    from manuscript_guard.audit import audit
    from manuscript_guard.text.masking import NUL, mask, masked_spans

    outputs = _outputs(tmp_path, '{"n": 1}')
    path = tmp_path / "paper.md"
    path.write_text(paper, encoding="utf-8")
    assert {c.text.rstrip(".") for c in audit([path], [outputs]).unmatched} == shown
    assert all(number in mask(paper) for number in shown), "G2 reads what the audit reads"
    hidden = {i for spans in masked_spans(paper).values() for a, b in spans for i in range(a, b)}
    explained = "".join(NUL if i in hidden else ch for i, ch in enumerate(paper))
    assert explained == mask(paper), "`explain` reports what G2 masks"


def test_a_comment_opened_in_the_front_matter_hides_no_binding(project: Path) -> None:
    """The binding parser blanked HTML comments across the whole file, so a `<!--` in a YAML
    comment ran on to the next comment in the body, and no binding between was parsed: a
    reversed interval passed and printed as "(95% CI 5.12 to 2.89)"."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    text = text.replace("\n---\n", "\n# note <!-- keep the title in step\n---\n", 1)
    text = text.replace(
        "{{results.ror.ci_low}} to {{results.ror.ci_high}}",
        "{{results.ror.ci_high}} to {{results.ror.ci_low}}",
        1,
    )
    text = text.replace("# Introduction", "<!-- checked -->\n\n# Introduction", 1)
    path.write_text(text, encoding="utf-8")
    assert "interval-reversed" in codes(gate_report(project))


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("header", "rule"),
    [
        # 0.2.12 closed front matter only with `---`.
        ("---\n{title}\n...\n", r"\A---\r?\n(.*?)\r?\n---[ \t]*\r?\n"),
        # From 0.2.13 until 0.2.47 a header that is a sentence, which pandoc prints, was
        # stripped all the same.
        (
            "---\nKept for the authors.\n...\n",
            r"\A---[ \t]*\r?\n(?![ \t]*\r?\n)(.*?)\r?\n(?:---|\.\.\.)[ \t]*\r?\n",
        ),
    ],
    ids=["0.2.12", "0.2.13"],
)
def test_a_document_numbered_under_older_rules_is_not_merged(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header: str, rule: str
) -> None:
    """Paragraph identifiers are positional, and 0.2.13 moved where front matter closed by
    `...` ends. A document built before that and imported after it had every identifier a
    block out of step: `import --apply` wrote three paragraphs' text over three others and
    printed "merged 3 reworded paragraph(s), bindings intact". The rule changed again in
    0.2.47, for a header pandoc does not keep as metadata."""
    import importlib

    from manuscript_guard.cli import main

    # The module, not the `assemble` function the package exports under the same name.
    assembly = importlib.import_module("manuscript_guard.build.assemble")
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    title = text.split("\n")[1]
    path.write_text(
        header.format(title=title) + text[text.index("\n---\n") + len("\n---\n") :], "utf-8"
    )
    source = path.read_text(encoding="utf-8")

    # Built as that release built it.
    before = re.compile(rule, re.DOTALL)

    def as_before(raw: str) -> tuple[str, str]:
        found = before.match(raw)
        return (raw[found.end() :].lstrip("\n"), "") if found else (raw, "")

    with monkeypatch.context() as patched:
        patched.setattr(assembly, "strip_front_matter", as_before)
        # Nor did that release refuse a line of dashes over a line of text (#65).
        patched.setattr(assembly, "rule_findings", lambda path, text: ())
        assert main(["build", str(project), "--offline"]) == 0
    returned = tmp_path / "back.docx"
    shutil.copy(project / "build" / "manuscript.docx", returned)
    # A co-author's edit, in a document that records no paragraphs, as 0.2.12's did not.
    scratch = tmp_path / "t.docx"
    with zipfile.ZipFile(returned) as zin, zipfile.ZipFile(scratch, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b"received no funding", b"received no external funding")
            elif item.filename == "docProps/custom.xml":
                data = re.sub(
                    rb'<property\b[^>]*name="manuscript-guard-paragraphs-\d+".*?</property>',
                    b"",
                    data,
                    flags=re.DOTALL,
                )
            zout.writestr(item, data)

    main(["import", str(scratch), str(project), "--apply"])
    assert path.read_text(encoding="utf-8") == source, "an edit landed in another paragraph"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("was", "now"),
    [
        ("# Introduction\n\n", "# Introduction\n\nA paragraph added after the build.\n\n"),
        ("examined.\n\n# Methods", "examined.\n\nA paragraph added after the build.\n\n# Methods"),
        ("Whether the signal extends to example-drug specifically has not been examined.\n\n", ""),
    ],
    ids=["added above", "added directly above a heading", "removed above"],
)
def test_a_forced_import_does_not_write_over_a_neighbouring_paragraph(
    project: Path, tmp_path: Path, was: str, now: str
) -> None:
    """Identifiers are positional. With a paragraph added to the source since the build,
    above the one a co-author edited, every identifier after it named the paragraph before,
    and `import --apply --force` wrote three edits over their neighbours and printed "merged
    3 reworded paragraph(s), bindings intact". The plan showed what each edit became, never
    which paragraph it replaced, so reading every hunk could not have caught it. Refused,
    every edit below the change had to be carried over by hand; followed to where it stands
    now, among the same blocks as at the build, the edit lands in its own paragraph."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = tmp_path / "back.docx"
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as zin, zipfile.ZipFile(
        returned, "w"
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.replace(b"received no funding", b"received no external funding")
            zout.writestr(item, data)
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    assert was in text
    path.write_text(text.replace(was, now, 1), encoding="utf-8")
    edited = path.read_text(encoding="utf-8").replace(
        "received no funding", "received no external funding"
    )

    main(["import", str(returned), str(project), "--apply", "--force"])
    assert path.read_text(encoding="utf-8") == edited, "the edit is not where it was made"


def _sent_back(
    project: Path,
    tmp_path: Path,
    change,
    *,
    recorded: bool = True,
    document: str = "manuscript.docx",
) -> Path:
    """The built document as a co-author returns it, `change` applied to its body's XML;
    without its record of paragraphs unless `recorded`, as releases before 0.2.60 built it."""
    returned = tmp_path / "back.docx"
    with zipfile.ZipFile(project / "build" / document) as zin, zipfile.ZipFile(
        returned, "w"
    ) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = change(data.decode("utf-8")).encode("utf-8")
            elif item.filename == "docProps/custom.xml" and not recorded:
                data = re.sub(
                    rb'<property\b[^>]*name="manuscript-guard-paragraphs-\d+".*?</property>',
                    b"",
                    data,
                    flags=re.DOTALL,
                )
            zout.writestr(item, data)
    return returned


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_an_import_does_not_cut_a_paragraph_down_to_a_link_definition(
    project: Path, tmp_path: Path
) -> None:
    """A paragraph opening `[Note]:` with a narrative citation after it is prose. Cut down
    in Word to the label and the citation, it is a link's definition, which pandoc prints
    nothing of: merged, the paragraph vanished from the next build (#72's round-4 review)."""
    from manuscript_guard.cli import main

    path = main_md(project)
    paragraph = "[Note]: @fictionalClassSignal2019 says the ratio was high.\n\n"
    anchor = "# Data availability"
    path.write_text(
        path.read_text(encoding="utf-8").replace(anchor, paragraph + anchor, 1), "utf-8"
    )
    source = path.read_text(encoding="utf-8")
    assert main(["build", str(project), "--offline"]) == 0
    returned = _sent_back(
        project, tmp_path, lambda xml: xml.replace("says the ratio was high.", "", 1)
    )

    main(["import", str(returned), str(project), "--apply"])
    assert path.read_text(encoding="utf-8") == source, "cut down to a link definition"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_value_paragraph_retyped_into_the_one_before_is_not_merged(
    project: Path, tmp_path: Path
) -> None:
    """A document that records nothing may never have carried a paragraph that is only a
    value, releases before 0.2.49 gave it no identifier, so one missing from it was left out
    of the comparison, and of the join check with it. Joined into the paragraph before by
    retyping across the break, which takes its bookmark, it merged as a rewording and the
    number was in the source twice. Main reports the join."""
    from manuscript_guard.cli import main

    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    anchor = "has not been examined.\n\n# Methods"
    assert anchor in text
    path.write_text(
        text.replace(anchor, "has not been examined.\n\n{{results.ror.point}}\n\n# Methods"),
        encoding="utf-8",
    )
    assert main(["build", str(project), "--offline"]) == 0

    def retyped(xml: str) -> str:
        value = _word_paragraph(xml, ">3.84<")
        return xml.replace(value, "", 1).replace(
            "has not been examined.", "has not been examined. 3.84", 1
        )

    returned = _sent_back(project, tmp_path, retyped, recorded=False)
    source = path.read_text(encoding="utf-8")

    assert main(["import", str(returned), str(project), "--apply"]) == 1
    assert path.read_text(encoding="utf-8") == source, "the number was written in twice"


def _word_paragraph(xml: str, words: str) -> str:
    """The Word paragraph carrying an identifier whose text holds `words`."""
    return next(
        p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if "mg-p-" in p and words in p
    )


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_forced_import_does_not_write_into_another_paragraph_reading_the_same(
    project: Path, tmp_path: Path
) -> None:
    """Declarations repeat: "Not applicable." under two headings. The record held a hash of
    each paragraph's text, which cannot tell the two apart, so with a third declaration added
    above them since the build, the first one's identifier named the new one, read the same,
    was trusted, and `import --apply --force` wrote a co-author's ethics approval under
    "Consent to participate"."""
    from manuscript_guard.cli import main
    from manuscript_guard.roundtrip import tagged_paragraphs

    path = main_md(project)
    tail = (
        "# Funding\n\nThis work received no funding.\n\n# Competing interests\n\nNone declared.\n"
    )
    declared = (
        "# Ethics approval\n\nNot applicable.\n\n# Consent for publication\n\nNot applicable.\n\n"
        "# Competing interests\n\nNone declared.\n"
    )
    text = path.read_text(encoding="utf-8")
    assert tail in text
    path.write_text(text.replace(tail, declared), encoding="utf-8")
    assert main(["build", str(project), "--offline"]) == 0
    ethics = next(
        name
        for name, (_path, words, _start) in tagged_paragraphs(load_project(project)[0]).items()
        if words == "Not applicable."
    )

    def approved(xml: str) -> str:
        at = xml.index(f'w:name="{ethics}"')
        stop = xml.index("</w:p>", at)
        edited = xml[at:stop].replace("Not applicable.", "Approved by the review board.")
        return xml[:at] + edited + xml[stop:]

    returned = _sent_back(project, tmp_path, approved)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "# Ethics approval\n",
            "# Consent to participate\n\nNot applicable.\n\n# Ethics approval\n",
        ),
        encoding="utf-8",
    )
    source = path.read_text(encoding="utf-8")

    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    assert path.read_text(encoding="utf-8") == source, "an edit landed in another paragraph"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("lost", [False, True], ids=["bookmark kept", "bookmark lost"])
def test_a_paragraph_joined_to_one_the_source_changed_is_not_merged(
    project: Path, tmp_path: Path, lost: bool
) -> None:
    """With the second of two paragraphs edited in the source since the build, only the first
    kept a trusted identifier, and the two joined in Word read as the first one reworded:
    `import --apply --force` merged it, and the second paragraph's text was in the source
    twice. With the join retyped across the boundary, which takes the second bookmark with
    it, the import also exited 0. Main reports the join."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0

    def joined(xml: str) -> str:
        first = _word_paragraph(xml, "Drug-induced hepatic injury remains")
        second = _word_paragraph(xml, "Whether the signal")
        inner = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", second, flags=re.DOTALL)
        if lost:
            inner = re.sub(r"<w:bookmark(?:Start|End)[^>]*/>", "", inner)
        return xml.replace(second, "", 1).replace(first, first[: -len("</w:p>")] + inner, 1)

    returned = _sent_back(project, tmp_path, joined)
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "has not been examined.", "has not been examined before.", 1
        ),
        encoding="utf-8",
    )
    source = path.read_text(encoding="utf-8")

    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    assert path.read_text(encoding="utf-8") == source, "a join was merged as a rewording"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_block_tagged_since_the_build_joined_into_the_one_above_is_not_merged(
    project: Path, tmp_path: Path
) -> None:
    """A list item carries no identifier, so a document records none for it; turned into a
    paragraph since the build, it has one now, which the record does not hold and the join
    check did not weigh. Joined in Word into the paragraph above it, the join merged as a
    rewording, the import exited 0, and the sentence was in the source twice. A release that
    tags more kinds of block does the same with no source change at all. Main reports the
    join."""
    from manuscript_guard.cli import main

    path = main_md(project)
    signal = "Whether the signal extends to example-drug specifically has not been examined.\n"
    item = "- No other signal was examined in this analysis.\n"
    text = path.read_text(encoding="utf-8")
    assert signal in text
    path.write_text(text.replace(signal, f"{signal}\n{item}", 1), encoding="utf-8")
    assert main(["build", str(project), "--offline"]) == 0

    def joined(xml: str) -> str:
        above = _word_paragraph(xml, "Whether the signal")
        below = next(
            p
            for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
            if "No other signal was examined" in p
        )
        inner = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", below, flags=re.DOTALL)
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(below, "", 1).replace(above, above[: -len("</w:p>")] + space + inner, 1)

    returned = _sent_back(project, tmp_path, joined)
    path.write_text(path.read_text(encoding="utf-8").replace(item, item[2:], 1), encoding="utf-8")
    source = path.read_text(encoding="utf-8")

    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    assert path.read_text(encoding="utf-8") == source, "a join was merged as a rewording"


def test_g2_reads_no_body_prose_as_code_from_a_fence_in_the_front_matter() -> None:
    """A fence opener in an abstract, with no closer there, paired with a fence in the body,
    and the prose between was judged as R."""
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import _fenced_code

    text = (
        '---\nabstract: |\n  ```r\n---\n\n## Results\n\nThe label read "ROR 9.99".\n\n'
        "```r\nx <- 1\n```\n"
    )
    report = _fenced_code(Path("main.md"), text, Classifier.load())
    assert "code-block-text-number" not in {f.code for f in report.findings}


def test_g2_judges_a_listing_in_the_front_matter_as_code() -> None:
    """A code block in a front-matter value is a listing too, and a number in its string is
    a claim. Looked for in the body alone, `_fenced_code` missed it while `mask` hid it, and
    the number was read by nothing; no test held the two to the same fences."""
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import _fenced_code
    from manuscript_guard.text.masking import NUL, fenced_blocks, mask

    text = (
        '---\ntitle: T\nsubtitle: |\n  ```python\n  print("ROR 9.99")\n  ```\n---\n\n'
        "# Results\n\nText.\n"
    )
    report = _fenced_code(Path("main.md"), text, Classifier.load())
    assert "code-block-text-number" in {f.code for f in report.findings}
    masked = mask(text)
    assert all(masked[i] == NUL for f in fenced_blocks(text) for i in range(f.start, f.end))


def test_a_url_ending_a_yaml_value_hides_nothing_of_the_next(tmp_path: Path) -> None:
    """A URL is masked to the next space, and the key of the next YAML line is masked too,
    so one ending a title ran through that key into the next value: 9.99, which pandoc
    prints in the abstract, was read by nothing."""
    from manuscript_guard.audit import audit
    from manuscript_guard.text.masking import mask

    paper = (
        "---\ntitle: Data at https://example.org/data\nabstract: 9.99 was the ROR.\n---\n\n"
        "# Results\n\nThe cohort held n = 1 report.\n"
    )
    outputs = _outputs(tmp_path, '{"n": 1}')
    path = tmp_path / "paper.md"
    path.write_text(paper, encoding="utf-8")
    assert {c.text.rstrip(".") for c in audit([path], [outputs]).unmatched} == {"9.99"}
    assert "9.99" in mask(paper)


def test_a_yaml_block_in_the_body_heads_nothing(project: Path) -> None:
    """Pandoc reads a YAML block anywhere in the body as metadata, so a `# Methods` line in
    one is a YAML comment. Read as a heading, it gave the paragraph under
    the block the Methods chain, and a `p < 0.001` in the Introduction passed as the alpha
    chosen in advance."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    anchor = "Whether the signal extends to example-drug specifically has not been examined.\n"
    assert anchor in text
    block = "\n---\nnote: x\n# Methods\n---\n\nThe difference was p < 0.001.\n"
    path.write_text(text.replace(anchor, anchor + block, 1), encoding="utf-8")
    assert "unclassified-number" in codes(gate_report(project))


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        # The build passes a body block to pandoc, which prints its author, date and
        # abstract, a wrapped value included.
        (
            "Para.\n\n---\nauthor: The 12 investigators\ndate: Revised after 9.94\n"
            "abstract: The ROR was\n  9.91 in the cohort.\n---\n\nAfter.\n",
            ("12", "9.94", "9.91"),
        ),
        # Under a caption, pandoc reads the block as a table and prints it.
        ("Table: Cohort sizes.\n\n---\nCases: 120\nControls: 480\n---\n", ("120", "480")),
        # In the body a URL still runs to the next space: stopped at a comment, the link
        # target after it started inside the old URL and ran on.
        ("See https://x.org/a<!--c-->](b ROR 8.88) here.\n", ("8.88",)),
    ],
    ids=["printed values", "table", "url in the body"],
)
def test_masking_hides_nothing_a_body_yaml_block_prints(text: str, shown: tuple[str, ...]) -> None:
    """Masked as a whole, a YAML block in the body hid values the build prints: pandoc
    prints a body block's author, date and abstract, and a block under a caption is a
    table. A body block is only kept from heading anything."""
    from manuscript_guard.text.masking import mask

    masked = mask(text)
    assert all(number in masked for number in shown)


def test_a_yaml_block_inside_a_comment_brings_back_no_heading(project: Path) -> None:
    """Pandoc reads a YAML block inside an HTML comment as part of the comment. Masked, the
    block stopped the comment scanner, so a `# Methods` further down the comment headed the
    paragraph after it, and its `p < 0.001` passed as the alpha."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    anchor = "Whether the signal extends to example-drug specifically has not been examined.\n"
    comment = "\n<!--\n\n---\nnote: x\n---\n\n# Methods\n\n-->\n\nThe difference was p < 0.001.\n"
    path.write_text(text.replace(anchor, anchor + comment, 1), encoding="utf-8")
    assert "unclassified-number" in codes(gate_report(project))


def test_a_raw_block_in_the_front_matter_is_not_reported(project: Path) -> None:
    """The build strips the manuscript's front matter, so a raw LaTeX block under
    `header-includes` never reaches the document; G2 failed it as a `raw-block` written
    straight into the build."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    title = text.split("\n")[1]
    header = (
        f"---\n{title}\nheader-includes: |\n  ```{{=latex}}\n  \\usepackage{{setspace}}\n"
        "  ```\n---\n"
    )
    path.write_text(header + text[text.index("\n---\n") + len("\n---\n") :], encoding="utf-8")
    assert "raw-block" not in codes(gate_report(project))


_TICKS = "`" * 3
_PRINTED = "The excess was 9.99."
# Each makes a fenced listing of prose to the gates that pandoc prints: a fence pandoc does
# not open, or one it does not close, so that the gates' closer paired with the next fence.
_NOT_A_FENCE = {
    # Python splits a line at these; pandoc splits at a newline alone, and deletes a lone
    # carriage return.
    **{
        f"a fence after {name} on one line": (
            f"We found it.{chr(code)}{_TICKS}\n\n{_PRINTED}\n\nThe end.{chr(code)}{_TICKS}\n"
        )
        for name, code in {
            "a form feed": 0x0C,
            "a vertical tab": 0x0B,
            "a file separator": 0x1C,
            "a next-line control": 0x85,
            "a line separator": 0x2028,
            "a paragraph separator": 0x2029,
            "a lone carriage return": 0x0D,
        }.items()
    },
    # After the fence pandoc takes one word, then `{attributes}`, and nothing else.
    "an opener with two words": f"{_TICKS}r foo\n{_PRINTED}\n{_TICKS}\n",
    "an R Markdown chunk header": f"{_TICKS}{{r, echo=FALSE}}\n{_PRINTED}\n{_TICKS}\n",
    "an opener with a word after its attributes": f"{_TICKS}{{.r}} x\n{_PRINTED}\n{_TICKS}\n",
    "an opener ending in a no-break space": f"{_TICKS}r{chr(0xA0)}\n{_PRINTED}\n{_TICKS}\n",
    "an opener ending in a form feed": f"{_TICKS}r{chr(0x0C)}\n{_PRINTED}\n{_TICKS}\n",
    "a tilde opener with a backtick": f"~~~r`x\n{_PRINTED}\n~~~\n",
    # Attributes may run on to the next line, but not past a blank one.
    "attributes broken by a blank line": f"{_TICKS}{{.r\n\n.x}}\n{_PRINTED}\n{_TICKS}\n",
    # Pandoc closes on spaces and tabs after the fence, and no indentation past three.
    **{
        f"a closer {where}": (
            f"{_TICKS}r\nx\n{closer}\n\nMore code.\n\n{_TICKS}\n{_PRINTED}\n\n"
            f"{_TICKS}r\ny\n{_TICKS}\n"
        )
        for where, closer in {
            "ending in a no-break space": _TICKS + chr(0xA0),
            "ending in a form feed": _TICKS + chr(0x0C),
            "ending in an ideographic space": _TICKS + chr(0x3000),
            "after a no-break space": chr(0xA0) + _TICKS,
            "after a tab": "\t" + _TICKS,
            "after a space and a tab": " \t" + _TICKS,
            "after a lone carriage return": "x\r" + _TICKS,
        }.items()
    },
}


@pytest.mark.parametrize("name", sorted(_NOT_A_FENCE))
def test_the_gates_read_prose_that_no_fence_of_pandocs_holds(name: str) -> None:
    """The fence reader split lines where Python does, at a form feed and six other
    characters as well as a newline, and stripped every Unicode space off a closer. Pandoc
    does neither, so prose it printed was a listing to every gate, and G2 read no number in
    it. Now the gates read it, or the shape is refused."""
    from manuscript_guard.text.fences import unclear_fence_lines
    from manuscript_guard.text.masking import mask

    text = f"# Results\n\nWe found it.\n\n{_NOT_A_FENCE[name]}\nThe end.\n"
    assert "9.99" in mask(text) or unclear_fence_lines(text)


_CHUNK = (
    f"{_TICKS}{{r setup}}\nx <- 1\n{_TICKS}\n\n{_PRINTED}\n\n"
    f"{_TICKS}{{r plot}}\ny <- 2\n{_TICKS}\n"
)
# Fences pandoc may not open, or may pair otherwise than the gates.
_UNCLEAR_FENCES = [
    # Found by review: pandoc opens no fence on an R Markdown chunk header, and its closer
    # then opened one to the gates that ran to the next chunk, over the prose between.
    _CHUNK,
    _CHUNK.replace(_TICKS, "~~~"),
    _CHUNK.replace("{r setup}", "{r, echo=FALSE}"),
    _CHUNK.replace("{r setup}", "r see below"),
    _CHUNK.replace("{r setup}", "{.r} x"),
    _CHUNK.replace("{r setup}", 'python title="x"'),
    # Attributes over two lines pandoc may or may not close.
    f"{_TICKS}{{.r\n{_TICKS}\n}}\nBody.\n{_TICKS}\n\n{_PRINTED}\n",
    f"{_TICKS}{{.r\n.x}}\nx <- 1\n{_TICKS}\n\n{_PRINTED}\n",
    # A tilde fence, or an indented one, cannot interrupt a paragraph; a backtick one can.
    f"We used a line:\n~~~\n\n{_PRINTED}\n\n~~~r\ny\n~~~\n",
    f"We used a line:\n  {_TICKS}r\nx\n{_TICKS}\n\n{_PRINTED}\n\n{_TICKS}r\ny\n{_TICKS}\n",
    f"We used a line:\n{_TICKS}r\nx\n{_TICKS}\n",
    # Something other than a space in front of the fence: pandoc reads text.
    f"{chr(0xFEFF)}{_TICKS}r\nx\n{_TICKS}\n\n{_PRINTED}\n\n{_TICKS}r\ny\n{_TICKS}\n",
    f"{chr(0xA0)}{_TICKS}r\nx\n{_TICKS}\n\n{_PRINTED}\n\n{_TICKS}r\ny\n{_TICKS}\n",
    # An opener with no closer, and a closer with no opener.
    f"{_TICKS}r\nx <- 1\n\n{_PRINTED}\n",
    f"{_PRINTED}\n\n{_TICKS}\n",
    # Found by the second review. In a list item pandoc takes the item's indentation off
    # before it looks for the closer, and closed where the gates read on to the next one.
    f"- {_TICKS}r\n  x <- a\n\n  {_TICKS}\n\n{_PRINTED}\n\n{_TICKS}r\ny <- b\n{_TICKS}\n",
    (
        f"1. Step one:\n\n   {_TICKS}r\n   x <- 1\n    {_TICKS}\n\n{_PRINTED}\n\n"
        f"{_TICKS}r\ny\n{_TICKS}\n"
    ),
    f"- [ ] {_TICKS}r\nx\n{_TICKS}\n",
    f": {_TICKS}r\nx\n{_TICKS}\n",
    f"[^1]: {_TICKS}r\n    x\n    {_TICKS}\n",
    # Inside a comment or a raw block the fence is raw text to pandoc, and the gates paired
    # it with a later one.
    f"<!-- old version:\n\n{_TICKS}r\nx <- 1\n-->\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"<pre>\n\n{_TICKS}r\nx\n</pre>\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"<script>\n\n{_TICKS}r\nx\n</script>\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"\\begin{{comment}}\n\n{_TICKS}r\nx\n\\end{{comment}}\n\n{_PRINTED}\n\n{_TICKS}\n",
    # A quoted value not closed on the line: pandoc reads it on over the lines.
    f"{_TICKS}{{.r label='fit1}}\nThe cohort's data.\n{_TICKS}\n\n{_PRINTED}\n",
    # A backslash before a tab: pandoc expands the tab first, and escapes a space.
    f"{_TICKS}{{k=a\\\tb .r}}\nx\n{_TICKS}\n",
    # Found by the third review: a raw block or a comment closes only on its own mark, and
    # another mark inside it closed it to the gates.
    f"<pre>\na --> b\n\n{_TICKS}r\nx\n</pre>\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"\\begin{{center}}\na --> b\n\n{_TICKS}r\nx\n\\end{{center}}\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"<!-- see </pre>\n\n{_TICKS}r\nx\n-->\n\n{_PRINTED}\n\n{_TICKS}\n",
    # Found by the fourth: pandoc counts a raw block of the same name opened inside one,
    # reads a backslash before a backtick as a backtick, and closes a code span on a later
    # line; a space may stand before an environment's brace, and `<?php` opens raw text.
    f"<pre>\n<pre>\n</pre>\n\n{_TICKS}r\nx\n</pre>\n\n{_PRINTED}\n\n{_TICKS}\n",
    (
        f"\\begin{{center}}\n\\begin{{center}}\n\\end{{center}}\n\n{_TICKS}r\nx\n"
        f"\\end{{center}}\n\n{_PRINTED}\n\n{_TICKS}\n"
    ),
    f"Text \\`<!-- and `x`.\n\n{_TICKS}r\nx\n-->\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"See `x\ny` and <!-- z `w`.\n\n{_TICKS}r\nx\n-->\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"\\begin {{center}}\n\n{_TICKS}r\nx\n\\end{{center}}\n\n{_PRINTED}\n\n{_TICKS}\n",
    f"<?php\n\n{_TICKS}r\nx\n?>\n\n{_PRINTED}\n\n{_TICKS}\n",
]


@pytest.mark.parametrize("block", _UNCLEAR_FENCES)
def test_a_fence_pandoc_may_not_open_is_refused(block: str) -> None:
    from manuscript_guard.text.fences import unclear_fence_lines

    assert unclear_fence_lines(f"# Results\n\nWe found it.\n\n{block}\nThe end.\n") != []


def test_an_r_markdown_chunk_is_refused_by_check_and_the_build(project: Path, capsys) -> None:
    """Two chunks and prose between: the gates hid the prose, and pandoc printed it."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{_CHUNK}", encoding="utf-8")
    assert main(["check", str(project), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert "unclear-fence" in {f["code"] for f in findings if f["severity"] == "fail"}
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "not a plain fenced listing" in capsys.readouterr().out


#: Comments the gates mask that pandoc prints, or partly prints: it reads a list item, a
#: quotation, a definition and its term, a footnote and a line block on their own, and a
#: comment opened in one ends there. Checked against pandoc in test_pandoc_agreement.py.
_UNREAD_COMMENTS = {
    "under a list item": "Intro.\n\n- item above\n<!--\nThe hidden odds ratio was 9.99.\n\n"
    "more -->\n\nAfter 3.33.\n",
    "code across list items": "- a stray ` tick\n- b `<!--` note 9.99 -->\n",
    "under a quotation": "> quote\n<!--\nhidden 9.99.\n\nmore -->\n",
    "under a definition": "Term\n:   def\n<!--\nhidden 9.99.\n\nmore -->\n",
    "under an example": "(@) ex\n<!--\nhidden 9.99.\n\nmore -->\n",
    "under an empty item": "-\n<!-- x\n\n9.99 -->\n",
    "across list items": "- a\n- b <!-- x\n- c 9.99 -->\n",
    "across quoted items": "> - a <!-- x\n> - b 9.99 -->\n",
    "in a term": "Term <!-- x\n\n:   def 9.99 -->\n",
    "in a footnote": "Text.[^1]\n\n[^1]: note <!-- x\n\nmore 9.99 -->\n",
    "in a line block": "| line <!-- x\n| b 9.99 -->\n",
    "in an item's second paragraph": "- item\n\n  para <!-- x\n\ny 9.99 -->\n",
    "past a stray div fence": "- item\n:::\nlazy <!-- x\n\n9.99 -->\n",
    # Round 1 of #115: a line block ends at a line at the margin, and pandoc's item ends at
    # a marker short of the item's text, a comment open or not.
    "a line block spilling onto the margin": "| Department of Pharmacology\n"
    "| University Hospital <!-- old address\nRoom 9.99 -->\n",
    "an item commented out between items": "- A\n<!--\n- B 9.99\n-->\n- C\n",
    "a comment run on to the next item": "- A <!--\n- B 9.99 -->\n- C\n",
    "a sub-item commented out among sub-items": "- A\n  - A.1\n  <!--\n  - A.2 9.99\n"
    "  -->\n- B\n",
    "a marker short of the item's text": "- A\n  - A.1 <!-- x\n   - y 9.99 -->\n",
    "a marker short of a wide number's text": "10. Step <!-- x\n   - y 9.99 -->\n",
    "code paired across a sub-item": "- a `x\n  - b `<!--` 9.99 -->\n",
    "a table in an item, then the margin": "- a\n\n  | x |\n<!-- y\n\nz 9.99 -->\n",
    # Found fuzzing round 1's fix: a `>` alone opens a quotation, or is text in an item,
    # and was read as a blank line.
    "under an empty quotation": ">\n<!-- x 9.99\n\n-->\n",
    "under a `>` in an item": "(@) ex\n>\n<!-- 9.99\n   - sub3\n\n  -->\n",
    # An item on a line continuing a quotation is an item of the quotation's list, whose
    # other items start where the sub-item does.
    "an item continuing a quoted list": ">   - qsub\nx -->\n- a <!-- x 9.99\n  - sub\n  -->\n",
    "items continuing a quoted list": "> - qitem\n10. ten\n- a <!-- x 9.99\n  - b\n  -->\n",
    "a line block's indented line, then the margin": "| a | b |\n  - a <!-- x\ntext 9.99\n"
    "x -->\n",
    "under a `>` that is an item's text": "- item\n>   - q\n</div>\n>\n<!-- 9.99\n"
    "  - a <!-- x\nx -->\n",
    "a line block's indented marker, then the margin": "| a | b |\n    - sub\n  - a <!-- x\n"
    "`tick 9.99\n  -->\n",
    "a line block after a closing tag": "(@) ex\n</div>\n| a | b |\n  <!--\n9.99\n  -->\n",
    "an item's text past a `|` line": "- a\n| b\nc <!-- x\n\n9.99 -->\n",
}


@pytest.mark.parametrize("paper", _UNREAD_COMMENTS.values(), ids=_UNREAD_COMMENTS.keys())
def test_a_comment_pandoc_ends_with_its_block_is_refused(paper: str) -> None:
    """The gates read the comment to its `-->`, past the end of the block pandoc reads it
    in, or pair a backtick across the blocks and see a comment pandoc prints as code. The
    refusal names the line of the `<!--`."""
    from manuscript_guard.text.comments import unclear_comment_lines

    assert unclear_comment_lines(paper) == [paper[: paper.index("<!--")].count("\n") + 1]


@pytest.mark.parametrize(
    "paper",
    [
        "Intro.\n\n<!--\nhidden 9.99.\n\nmore -->\n\nAfter.\n",
        "Intro.\n<!--\nhidden 9.99.\n\nmore -->\n\nAfter.\n",
        "Intro <!--\nhidden 9.99.\n\nmore -->\n",
        "- item\n\n<!--\nhidden 9.99.\n\nmore -->\n\nAfter.\n",
        "<!--\n- item 9.99\n- item\n-->\n",
        "- item <!-- hidden 9.99 -->\n",
        "- item\n<!-- hidden 9.99\nstill -->\n",
        "- a\n  - b <!-- x\n  9.99 -->\n",
        "> - a\n> - b <!-- x\n> 9.99 -->\n",
        "# Results <!-- draft\n\nThe ROR was 9.99 -->\n",
        "---\ntitle: A study\n---\n\n- item\n\n<!-- 9.99 -->\n",
        # Round 1 of #115: sub-items inside a comment the item opened, at or past the
        # item's text, are the item's to pandoc, and a table ends at a line at the margin.
        "- Reporting bias\n  <!--\n  - notoriety bias 9.99\n  - duplicates\n  -->\n"
        "- Missing data\n",
        "- Reporting bias. <!-- note to self:\n  - check notoriety bias 9.99\n"
        "  - ask the second reviewer -->\n- Missing data.\n",
        "1. Step one\n   <!--\n   a. detail 9.99\n   -->\n2. Step two\n",
        "1. Step one\n    <!--\n    a. detail 9.99\n    -->\n2. Step two\n",
        "10. Step <!-- x\n    - y 9.99 -->\n",
        "- A\n<!--\n  - A.1 9.99\n-->\n- B\n",
        "- a\n  - b <!-- x\n    - c 9.99 -->\n",
        "- A <!-- x\n  > q 9.99\n  -->\n",
        "> - a <!-- x\n>   - b 9.99 -->\n",
        "| Analysis | Included |\n|---|---|\n| Primary | yes |\n<!--\n"
        "| Excluding duplicates | 9.99 |\n-->\n\nText after.\n",
        "## Results\n| a | b |\n|---|---|\n| 1 | 2 |\n<!--\nx 9.99\n\n-->\n",
        "Text\n| a |\n<!--\nx 9.99\n\n-->\n",
    ],
)
def test_a_comment_pandoc_drops_as_the_gates_do_is_not_refused(paper: str) -> None:
    """On its own line under a blank line, in a paragraph at the margin, whose comment pandoc
    reads on over blank lines, opened and closed on an item's own lines, sub-items and all,
    or under a table."""
    from manuscript_guard.text.comments import unclear_comment_lines

    assert unclear_comment_lines(paper) == []


def test_a_comment_under_a_list_item_is_refused_by_check_and_the_build(
    project: Path, capsys
) -> None:
    """Pandoc reads the `<!--` as text continuing the item, ends the item at the blank line
    and prints the comment's 9.99, which the gates had masked: check and the build passed."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(
        f"{text}\n## Results\n\n- item above\n<!--\nThe hidden odds ratio was 9.99.\n\nmore -->\n",
        encoding="utf-8",
    )
    line = source.read_text(encoding="utf-8").split("\n").index("- item above") + 2
    assert main(["check", str(project), "--json"]) == 1
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert {(f["code"], f["line"]) for f in findings if f["severity"] == "fail"} == {
        ("unclear-comment", line)
    }
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "HTML comment" in capsys.readouterr().out


def test_a_sub_list_or_table_rows_commented_out_pass_check_and_the_build(
    project: Path, capsys
) -> None:
    """Round 1 of #115: pandoc drops each comment, and main passed them, where the refusal
    failed check and the build on ordinary list and table editing."""
    from manuscript_guard.cli import main

    source = main_md(project)
    source.write_text(
        source.read_text(encoding="utf-8")
        + "\n## Limitations\n\n- Reporting bias\n  <!--\n  - notoriety bias\n  - duplicates\n"
        "  -->\n- Missing data. <!-- note to self:\n  - check the imputation\n"
        "  - ask the second reviewer -->\n- Channelling.\n\n| Analysis | Included |\n"
        "|---|---|\n| Primary | yes |\n<!--\n| Excluding duplicates | pending |\n-->\n\n"
        "Text after.\n",
        encoding="utf-8",
    )
    assert main(["check", str(project), "--json"]) == 0
    findings = json.loads(capsys.readouterr().out)["findings"]
    assert "unclear-comment" not in {f["code"] for f in findings}
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0


@pytest.mark.parametrize(
    "block",
    [
        f"{_TICKS}r\nx <- 1\n{_TICKS}\n",
        f"{_TICKS}\nx <- 1\n{_TICKS}\n",
        "~~~ {.r .numberLines}\nx <- 1\n~~~~\n",
        f"{_TICKS}{{=openxml}}\n<w:p/>\n{_TICKS}\n",
        f"{_TICKS}{{#1 .r}}\nx <- 1\n{_TICKS}\n",
        # Back to back, the second under the first's closer.
        f"{_TICKS}r\nx\n{_TICKS}\n{_TICKS}python\ny\n{_TICKS}\n",
        # A listing of Markdown, fences and all.
        f"````md\n{_TICKS}r\nx\n{_TICKS}\n````\n",
        # Inline code, and a listing in a list item, indented four columns.
        f"Use {_TICKS}x{_TICKS} here.\n",
        f"1. Run this:\n\n    {_TICKS}r\n    x <- 1\n    {_TICKS}\n",
        # Markup in a listing is code: a comment's marks in it open or close nothing.
        f"{_TICKS}html\n<p>A <b>bold</b> claim.</p>\n<!-- left open\n{_TICKS}\n",
        f"{_TICKS}mermaid\ngraph LR\n  A --> B\n{_TICKS}\n",
        # A custom element whose name starts with a raw one's.
        f"<pre-x>\n\n{_TICKS}r\nx\n{_TICKS}\n",
        # Two identical listings.
        f"{_TICKS}r\nx <- 1\n{_TICKS}\n\n{_TICKS}r\nx <- 1\n{_TICKS}\n",
        # Found by the third review: a mark in inline code, a `<pre>` in a line of text and a
        # comment closed at once open nothing.
        f"Use `<!--` to open a comment.\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"The HTML `<pre>` element.\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"Wrap it in `\\begin{{table}}`.\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"Text with <pre> in it.\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"<!-- the <pre> tag -->\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"<!-->\n\n{_TICKS}r\nx\n{_TICKS}\n",
        # Found by the fifth: pandoc counts no `<script>` opened inside one, and `<?` opens
        # nothing before anything but a letter.
        f"<script>\na <script> b\n</script>\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"<script>\n<script>\n</script>\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"<? marks a query in our notation.\n\n{_TICKS}r\nx\n{_TICKS}\n",
        f"<?= x\n\n{_TICKS}r\nx\n{_TICKS}\n",
        # Found reviewing round six: a listing commented out whole, the comment's `-->` after
        # its closer, is the comment's, and pandoc prints none of it.
        f"<!-- An earlier model:\n\n{_TICKS}r\nfit0 <- glm(y ~ x)\n{_TICKS}\n-->\n",
        f"<!--\n{_TICKS}r\nx\n{_TICKS}\n\n{_TICKS}python\ny\n{_TICKS}\n-->\n",
    ],
)
def test_a_plain_fence_is_not_refused(block: str) -> None:
    from manuscript_guard.text.fences import unclear_fence_lines

    assert unclear_fence_lines(f"# Results\n\nWe found it.\n\n{block}\nThe end.\n") == []


@pytest.mark.parametrize(
    "block",
    [
        "<!--\n~~~r\nx\n~~~\n-->\n",
        f"<!--\n- Fit the model:\n\n  {_TICKS}r\n  x\n  {_TICKS}\n-->\n",
        f"Text <!-- aside\n{_TICKS}r\nx\n{_TICKS}\nend of the aside -->\n",
        # Found by round 4 of #71: each follows from round 3's rule.
        f"<!-- An earlier\nmodel:\n{_TICKS}r\nx\n{_TICKS}\n-->\n",
        f"Text.\n<!--\n{_TICKS}r\nx\n{_TICKS}\n-->\n",
        f"## Note\n<!--\n{_TICKS}r\nx\n{_TICKS}\n-->\n",
        f"<!--\n{_TICKS}r\nx\n{_TICKS}\nand then\n{_TICKS}r\ny\n{_TICKS}\n-->\n",
        f" <!--\n{_TICKS}r\nx\n{_TICKS}\n-->\n",
    ],
    ids=[
        "tilde-under-comment",
        "in-a-list-item",
        "under-text-opening-it",
        "under-wrapped-comment-text",
        "comment-under-a-paragraph",
        "comment-under-a-heading",
        "text-between-two-listings",
        "comment-indented-a-space",
    ],
)
def test_a_listing_commented_out_in_these_shapes_is_refused(block: str) -> None:
    """Known gaps: pandoc prints nothing of these, and they are refused. A listing a comment
    holds is let be only where pandoc would read it as the gates do without the comment,
    and a backtick fence not apart only straight under a `<!--` that starts its line: under
    any line of text, a footnote's or a list item's took the fence in, and pandoc printed
    the claim after it (round 3's review of #71)."""
    from manuscript_guard.text.fences import unclear_fence_lines

    assert unclear_fence_lines(f"# Results\n\nWe found it.\n\n{block}\nThe end.\n") != []


def test_a_listing_a_comment_closes_inside_is_still_refused() -> None:
    """A comment whose `-->` falls inside the listing ends there, and the lines after it are
    printed: the listing is not the comment's, and stays refused."""
    from manuscript_guard.text.fences import unclear_fence_lines

    text = f"# Results\n\n<!--\n{_TICKS}r\nx -->\nThe excess (p < 0.001).\n{_TICKS}\n"
    assert unclear_fence_lines(text) != []


@pytest.mark.parametrize(
    "comment",
    [
        # Comments the gates see and pandoc does not: `<!--` in code beside a stray
        # backtick, and one never closed.
        "Write `<!--` to hide a line; the `x column is unused.\n\n",
        "<!-- an aside never closed\n\n",
    ],
)
def test_a_listing_behind_a_false_comment_keeps_the_plain_form(comment: str) -> None:
    """Found by round 2's review: a listing a comment holds was let be whatever its shape, on
    the gates' reading of where comments are. Behind a comment pandoc does not see, a listing
    in a list item, its closer indented past the item's, is code to the gates up to the last
    closer; pandoc ends it early and prints the claim after it. It passed `check` and the
    build, where round 1's head refused it. A listing a comment holds keeps the plain form."""
    from manuscript_guard.text.fences import unclear_fence_lines

    text = (
        f"# Results\n\n{comment}- Fit the model:\n  {_TICKS}r\n  fit <- glm(y ~ x)\n"
        f"    {_TICKS}\n\nThe excess was 9.87 (p < 0.001).\n\n{_TICKS}r\nsessionInfo()\n{_TICKS}\n"
    )
    assert unclear_fence_lines(text) != []


# Lines a backtick fence straight under them joins for pandoc: a footnote's, or a list
# item's that already has more than one line. Pandoc takes the fence into the container,
# strips its indentation and ends the code at an indented closer; the gates read on to the
# next closer at the margin, over the claim after it.
_CONTAINERS = {
    "footnote": "Ref.[^1]\n\n[^1]: A note.\n",
    "footnote continued": "Ref.[^1]\n\n[^1]: A note.\n\n    More of the note.\n",
    "footnote in a list": "- Ref.[^1]\n\n  [^1]: A note.\n",
    "nested item": "- An item.\n  - A sub-item.\n",
    "item continued": "- An item.\n\n  More of it.\n",
    "nested ordered item": "1. One.\n   a. Sub.\n",
    "comment under a footnote": "Ref.[^1]\n\n[^1]: A note.\n<!-- never closed\n",
}


@pytest.mark.parametrize("apart", [False, True], ids=["tight", "apart"])
@pytest.mark.parametrize("above", sorted(_CONTAINERS))
def test_a_listing_under_a_container_s_line_is_not_held_by_a_false_comment(
    above: str, apart: bool
) -> None:
    """Found by round 3's review: behind a comment the gates see and pandoc does not, a
    backtick listing straight under any line was held, since pandoc opens one under a line
    of text. Not under a footnote's or a longer list item's line, which takes the fence in;
    the claim after it printed, and `check` and the build passed. A listing that is not
    apart is held only straight under the `<!--` line, itself apart."""
    from manuscript_guard.text.fences import unclear_fence_lines

    gap = "\n" if apart else ""
    text = (
        f"# Results\n\n<!-- never closed\n\n{_CONTAINERS[above]}{_TICKS}r\n"
        f"fit <- glm(y ~ x)\n    {_TICKS}\n{gap}The excess was 9.87 (p < 0.001).\n{gap}"
        f"{_TICKS}r\nsessionInfo()\n{_TICKS}\n"
    )
    assert unclear_fence_lines(text) != []


@pytest.mark.parametrize(
    "text",
    [
        f"# Results\n\n<!-- An earlier model:\n{_TICKS}r\nfit0 <- glm(y ~ x)\n{_TICKS}\n-->\n",
        f"<!-- An earlier model:\n{_TICKS}r\nfit0 <- glm(y ~ x)\n{_TICKS}\n-->\n",
        f"# Results\n\n<!--\n{_TICKS}r\nfit0\n{_TICKS}\n\n{_TICKS}r\nfit1\n{_TICKS}\n-->\n",
    ],
    ids=["under-a-heading", "file-start", "two-listings"],
)
def test_a_listing_straight_under_its_comment_is_still_held(text: str) -> None:
    """Round 1's shape stays accepted with `<!--` straight above the opener: the comment
    line is apart, and pandoc opens a backtick fence under it."""
    from manuscript_guard.text.fences import unclear_fence_lines

    assert unclear_fence_lines(text) == []


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    "lead",
    [
        "As noted.[^n1]\n\n[^n1]: A note `<!--` `x\n",
        "- Fit the model.\n  - A step `<!--` `x\n",
        "- Fit the model.\n\n  A step `<!--` `x\n",
    ],
    ids=["footnote", "nested-item", "item-continued"],
)
def test_a_false_comment_in_a_container_hides_no_claim(project: Path, lead: str) -> None:
    """Round 3's reproduction on the example: `<!--` in code beside a stray backtick, on a
    footnote's or a list item's line, then a listing whose closer pandoc reads early. The
    claim after it printed in the document, untraced, while `check` and the build passed."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    block = (
        f"{lead}{_TICKS}r\nfit <- glm(y ~ x)\n    {_TICKS}\n\n"
        f"The excess was 9.87 (p < 0.001).\n\n{_TICKS}r\nsessionInfo()\n{_TICKS}\n"
    )
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{block}", encoding="utf-8")
    assert main(["check", str(project)]) == 1
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_listing_commented_out_whole_builds(project: Path) -> None:
    """Found reviewing round six: every fence line inside a comment was refused, so a
    listing commented out while an author decided, an ordinary habit, failed `check` and
    the build, `--skip-checks` too, where #65's tip built it. Pandoc prints nothing of it,
    and the gates mask both the comment and the listing."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    anchor = "Reporting follows the checklist declared in `paper.yaml`.\n"
    assert text.count(anchor) == 1
    snippet = (
        f"\n<!-- An earlier model, kept while we decide:\n\n{_TICKS}r\n"
        f"fit0 <- glm(case ~ drug, family = binomial)\n{_TICKS}\n-->\n"
    )
    source.write_text(text.replace(anchor, anchor + snippet), encoding="utf-8")
    assert main(["check", str(project)]) == 0
    assert main(["build", str(project), "--offline"]) == 0


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_listing_in_a_comment_pandoc_does_not_see_is_compared() -> None:
    """`check` lets a listing a comment holds whole be, and the comment is the tracker's
    reading, which a stray backtick can fool: here `<!--` is code to pandoc, and the gates'
    listing runs from one chunk's closer to the next, over a claim pandoc prints. The build
    finds the listing neither in a comment nor opening a code block, and refuses."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    body = (
        "# Results\n\nUse `<!--` for the `x variable.\n\n"
        f"{_TICKS}{{r}}\nx\n{_TICKS}\n\nThe excess (p < 0.001).\n\n{_TICKS}{{r}}\ny\n{_TICKS}\n"
    )
    found = misreading(header + body, header, [("main.md", body)], shutil.which("pandoc"), Path())
    assert found is not None

def test_the_unclear_fence_hint_names_the_margin_and_list_items() -> None:
    """A listing in a list item, indented as Markdown has it, was refused under a hint that
    said to open it under a blank line, which it was."""
    from manuscript_guard.build.assemble import fence_findings

    text = f"# Methods\n\n1. Install:\n\n   {_TICKS}r\n   install.packages('x')\n   {_TICKS}\n"
    hint = fence_findings(Path("main.md"), text)[0].hint
    assert "margin" in hint and "list item" in hint and "comment" in hint, hint


@pytest.mark.parametrize(
    ("info", "language"),
    [
        ("r", "r"),
        (" python ", "python"),
        ("{.python}", "python"),
        ("r{.x}", "r"),
        ("", ""),
        ("{k='a .b' .r}", "r"),
    ],
)
def test_a_listing_s_language_is_its_word_or_its_first_class(info: str, language: str) -> None:
    """`{.python}` and `r {.x}` came out as the languages `{.python}` and `r{.x}`, which no
    lexer knows, so the listing was reported unread instead of judged."""
    from manuscript_guard.text.fences import Fence

    assert Fence(start=0, body_start=0, body_end=0, end=0, info=info).language == language


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_the_build_refuses_a_listing_pandoc_does_not_make(project: Path, capsys) -> None:
    """A plain listing inside a TeX group: raw to pandoc, which prints the prose after it,
    and code to the gates, which read on to the next fence. `check` cannot see the group;
    the build compares every listing the gates mask with the code pandoc makes."""
    from manuscript_guard.cli import main

    block = f"\\newcommand{{\\x}}{{\n\n{_TICKS}r\nx\n}}\n\n{_PRINTED}\n\n{_TICKS}\n"
    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{block}", encoding="utf-8")
    capsys.readouterr()
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    err = capsys.readouterr().err
    assert "listing" in err and "main.md" in err, err


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_the_build_finds_each_listing_where_the_gates_read_it(project: Path, capsys) -> None:
    """Listings were matched to pandoc's code by their lines, so a copy did as well as the
    listing: the gates read a listing inside a TeX group, masking the claim after it, and an
    indented block holding the same lines passed for it. Each listing is now found by a line
    of its own, put in the copy pandoc reads."""
    from manuscript_guard.cli import main

    block = (
        f"\\newcommand{{\\x}}{{\n\n{_TICKS}r\n}}\n\n{_PRINTED}\n\n{_TICKS}\n\n"
        f"    }}\n    {_PRINTED}\n"
    )
    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{block}", encoding="utf-8")
    capsys.readouterr()
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    err = capsys.readouterr().err
    assert "listing" in err and "main.md" in err, err


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    ("written", "built"),
    [
        # Found by the sixth review: a caption over a listing whose first line is dashes is
        # a table to pandoc, its header the fence, ending at the first blank line, and the
        # YAML and heading after it read. The line put first in the listing to find it made
        # it a code block, and only that reading was compared.
        (
            f"# Methods\n\n: Settings used.\n\n{_TICKS}yaml\n---\nseed: 1\n\n---\n"
            f"title: Another title\n...\n\n# Results\n\nThe excess (p < 0.001).\n\n{_TICKS}\n",
            None,
        ),
        (
            f"# Methods\n\n: The model call.\n\n{_TICKS}r\n------\n"
            f"The reporting odds ratio was 9.99.\n{_TICKS}\n",
            None,
        ),
        # A value holding a fence ends the listing early, and the claim after it prints as
        # prose: the listings were paired by count, and each compared built to built.
        (
            f'# Results\n\n{_TICKS}r\nx <- "{{{{results.label}}}}"\nThe excess was 9.99.\n'
            f"{_TICKS}\n",
            f'# Results\n\n{_TICKS}r\nx <- "a"\n{_TICKS}\n"\nThe excess was 9.99.\n{_TICKS}\n',
        ),
        # A value holding a whole listing: the file has more listings as built.
        (
            "# Results\n\nThe code is {{results.label}}.\n",
            f"# Results\n\nThe code is a\n\n{_TICKS}r\nx\n{_TICKS}\n\n.\n",
        ),
    ],
)
def test_the_build_refuses_a_listing_the_line_or_a_value_changes(
    written: str, built: str | None
) -> None:
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    document = built or written
    found = misreading(
        header + document,
        header,
        [("main.md", written)],
        shutil.which("pandoc"),
        Path(),
        built=[document],
    )
    assert found is not None


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_placeholders_in_a_listing_are_matched_in_linear_time() -> None:
    """A listing of placeholders was matched with a pattern joined by `.*?`, tried against
    every block pandoc made: six placeholder lines after an 80-line comment ran past two
    minutes."""
    import shutil
    import time

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    comment = "<!--\n" + "".join(f"draft line {i}\n" for i in range(80)) + "-->\n\n"
    listing = f"{_TICKS}r\n" + "".join(f"{{{{results.v{i}}}}}\n" for i in range(8)) + "Total\n"
    body = f"# Results\n\n{comment}{listing}{_TICKS}\n"
    started = time.perf_counter()
    misreading(header + body, header, [("main.md", body)], shutil.which("pandoc"), Path())
    assert time.perf_counter() - started < 20


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_copy_of_a_listing_s_mark_does_not_pass_for_it(project: Path, capsys) -> None:
    """The line put first in each listing was `mglisting0`, which anyone can type: a
    listing opening with it, after a listing pandoc does not make, passed for that one. The
    line is made new each build, and must come back once."""
    from manuscript_guard.cli import main

    # One listing to the gates, from the first fence to the last; to pandoc, a TeX group,
    # the claim printed, and a listing opening with a typed copy of the mark.
    block = (
        f"\\newcommand{{\\x}}{{\n\n{_TICKS}\n}}\n\n{_PRINTED}\n\n"
        f"{_TICKS}r\nmglisting0\n{_TICKS}\n"
    )
    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    source.write_text(f"{text}\n## Results\n\nWe found it.\n\n{block}", encoding="utf-8")
    capsys.readouterr()
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    assert "listing" in capsys.readouterr().err


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_listings_deep_in_quotations_do_not_overflow() -> None:
    """Pandoc's reading was walked by recursion, and quotations six hundred deep raised
    RecursionError in the build."""
    import shutil

    from manuscript_guard.build.reading import misreading

    header = "---\ntitle: A study\n---\n"
    body = "# Results\n\n" + "> " * 600 + "Deep.\n"
    misreading(header + body, header, [("main.md", body)], shutil.which("pandoc"), Path())


def test_a_raw_block_with_a_space_before_its_format_is_one() -> None:
    """Pandoc reads `{ =openxml}` as a raw block, whose text reaches the reader as formatted
    prose; the gate took it for a listing in no known language and only warned."""
    from manuscript_guard.classify import Classifier
    from manuscript_guard.gates.numbers import _fenced_code

    text = f"# Results\n\n{_TICKS}{{ =openxml}}\n<w:p/>\n{_TICKS}\n"
    report = _fenced_code(Path("main.md"), text, Classifier.load())
    assert "raw-block" in {f.code for f in report.findings}


def test_a_yaml_block_after_a_form_feed_fence_is_refused() -> None:
    """A YAML block between two fences only the gates saw escaped the refusal, and its
    `title:` replaced paper.yaml's. No listing hides it now; the heading reads blank it as
    metadata (#85), and the rule scan, which keeps it (#65), refuses it."""
    from manuscript_guard.text.sections import rules_opening_blocks, scannable

    feed = chr(0x0C)
    text = (
        f"---\ntitle: A study\n---\n\n# Results\n\nWe found it.{feed}{_TICKS}\n\n"
        f"---\ntitle: Evil\n---\n\nThe end.{feed}{_TICKS}\n"
    )
    assert "Evil" in scannable(text, metadata=False)
    assert rules_opening_blocks(text) != []


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


def test_audit_compares_a_count_at_a_wrap_point(tmp_path: Path) -> None:
    """A Markdown paper is read as pandoc reads it: a count a hard wrap put at the start of
    a line is prose, not list numbering, and was never compared with the outputs."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "The number of reports was\n412. Of these, most were hepatic.\n", encoding="utf-8"
    )
    assert [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched] == ["412"]


def test_audit_still_reads_typed_numbering_in_word_as_numbering(tmp_path: Path) -> None:
    """A .docx is one Word paragraph per line, with no blank line between, so read as
    Markdown every line after the first would be a wrapped line of one long paragraph.
    Each paragraph starts a block, and "2. The second criterion." typed in Word is list
    numbering, as it was before the Markdown rule changed."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = _docx(
        tmp_path / "paper.docx",
        _p("Criteria were applied in turn.")
        + _p("2. The second criterion.")
        + _p("3. The third, on 9.99 of them."),
    )
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["9.99"]


def test_audit_reads_a_hash_typed_in_word_as_text_not_heading_numbering(
    tmp_path: Path,
) -> None:
    """Taking each Word paragraph for a block switched off the heading check as well, so a
    paragraph typed "# 3 sites were excluded" counted its 3 as heading numbering. Word's
    headings carry a style, not a `#`, and the paragraph is text."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = _docx(
        tmp_path / "paper.docx",
        _p("Sites were screened in turn.")
        + _p("# 3 sites were excluded after the audit.")
        + _p("The pooled ROR was 9.99."),
    )
    assert [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched] == ["3", "9.99"]


def test_audit_does_not_start_a_reference_list_inside_a_paragraph(tmp_path: Path) -> None:
    """`# References` directly under a line of prose is printed as part of that paragraph,
    not as a heading. It cut everything after it, so the number below was never compared."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        "The sources are listed below\n# References\n\nThe pooled ROR was 9.99.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert [c.text.rstrip(".") for c in report.unmatched] == ["9.99"]
    assert report.not_audited == []


@pytest.mark.parametrize(
    "heading",
    ["####### References", "<!-- c --># References", " # References\n---"],
    ids=["seven hashes", "after a comment", "indented over a rule"],
)
def test_audit_does_not_start_a_reference_list_at_a_heading_the_walk_misplaces(
    tmp_path: Path, heading: str
) -> None:
    """Found by the eighth review of #38. Under a stray `</script>` the walk can place a
    heading pandoc prints as text; G2 marks such a heading so that it opens no Methods, but
    the audit took it as the reference list's heading, and cut the prose after it."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"ror": 1.23}')
    paper = tmp_path / "paper.md"
    paper.write_text(
        f"# Introduction\n\nThe ROR was 1.23.\n\nText\n</script>\n{heading}\n"
        "The final ROR was 9.87.\n",
        encoding="utf-8",
    )
    report = audit([paper], [outputs])
    assert "9.87" in [c.text.rstrip(".") for c in report.unmatched]


def test_audit_still_ends_a_reference_list_at_a_heading_printed_as_prose(
    tmp_path: Path,
) -> None:
    """The other side of the test above. `# Appendix` directly under a reference entry is
    printed as part of it, and pandoc gives the appendix no heading. Ending the cut only at
    headings pandoc prints would hide the appendix as more references. An early end costs a
    false alarm; a late one hides numbers."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    for appendix in ("# Appendix\n", "Appendix\n--------\n"):
        paper = tmp_path / "paper.md"
        paper.write_text(
            "We saw 77 cases.\n\n# References\n\nSmith J. T. Lancet. 2019;393:1-2.\n"
            f"{appendix}\nThe estimate was 9.99.\n",
            encoding="utf-8",
        )
        assert [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched] == ["9.99"]


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


COMMENT_MARKERS_IN_CODE = "We stripped `<!--` markers. The ROR was {}.\n\nNote: `-->` closes.\n"


def test_audit_reads_prose_between_comment_markers_in_code(tmp_path: Path) -> None:
    """Pandoc prints `` `<!--` `` as code. The masking took it for a comment and hid
    everything up to the next `-->`, a later `` `-->` `` included: the audit reported 0
    numeric tokens and `--strict` passed."""
    from manuscript_guard.audit import audit
    from manuscript_guard.cli import main

    outputs = _outputs(tmp_path, '{"n": 1}')
    paper = tmp_path / "paper.md"
    paper.write_text("# Methods\n\n" + COMMENT_MARKERS_IN_CODE.format("9.99"), encoding="utf-8")
    assert [c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched] == ["9.99"]
    assert main(["audit", str(paper), "--against", str(outputs), "--strict"]) == 1


@pytest.mark.parametrize(
    "paper",
    [
        "<!-- draft\n```r\nx <- 1 # -->\n```\n\nThe ROR was 9.99. <!-- a -->\n",
        "---\ntitle: Stripping <!-- markers\n---\n\nThe ROR was 9.99. <!-- note -->\n",
        "<!-- Cut after review --\n> The pilot ROR was 9.99.\n-->\n",
        "Set `<!-- ROR 9.99\n```\n-->\n```\n` in the template.\n",
    ],
    ids=[
        "closed in a listing",
        "opened in the title",
        "cut short by --, newline, >",
        "code across a fence line",
    ],
)
def test_audit_reads_prose_pandoc_prints_near_comment_markers(tmp_path: Path, paper: str) -> None:
    """Pandoc prints 9.99 in each. The first three comments end before the next `-->`: at
    one inside a listing, at the end of the title they were opened in, or nowhere, because
    pandoc's HTML reader stops at `--` and `>` and then prints the whole thing. In the last
    the `<!--` is code, and a code span already open runs across the fence lines."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 1}')
    path = tmp_path / "paper.md"
    path.write_text(paper, encoding="utf-8")
    assert "9.99" in [c.text.rstrip(".") for c in audit([path], [outputs]).unmatched]


@pytest.mark.parametrize(
    "paper",
    [
        "# Methods\n\nThe template begins:\n\n    <!-- header\n\n# Results\n\n"
        "The ROR was 9.99.\n\n```html\n<!-- footer -->\n```\n",
        "# Methods\n\n- Wrap the template in ```:\n```html\n<!-- template\n```\n\n"
        "# Results\n\nThe ROR was 9.99.\n\n<!-- TODO -->\n",
        "Set `x\n````\ny`\n```\n<!--\n````\n\nThe ROR was 9.99. -->\n",
        "---\nabstract: |\n  Let $x <!-- y$. The ROR was 9.99.\n\n  ```\n  -->\n  ```\n"
        "author: A. Author <!-- add B -->\n---\n\nBody.\n",
    ],
    ids=[
        "an opener pandoc prints as code, closed in a listing",
        "a code span pandoc ends at a list item",
        "a code span over a fence line",
        "a front-matter key the old rule never read",
    ],
)
def test_the_comment_scanner_hides_nothing_the_old_rule_did_not(tmp_path: Path, paper: str) -> None:
    """The scanner knows code spans and fences, but not every place pandoc ends one: an
    indented code block, a list item, maths. Where it guessed a code span or a comment that
    pandoc does not make, a `<!--` it should have ignored closed on a `-->` inside a listing,
    or one it should have found in a listing opened a comment, and Results and 9.99 were
    hidden: `audit --strict` exited 0. The old rule read all three."""
    from manuscript_guard.audit import audit
    from manuscript_guard.cli import main

    outputs = _outputs(tmp_path, '{"n": 1}')
    path = tmp_path / "paper.md"
    path.write_text(paper, encoding="utf-8")
    assert "9.99" in [c.text.rstrip(".") for c in audit([path], [outputs]).unmatched]
    assert main(["audit", str(path), "--against", str(outputs), "--strict"]) == 1


@pytest.mark.parametrize(
    "paper",
    [
        "The ROR\n~~~\nwas 9.99.\n~~~\n",
        "Set `x\n```\ny`.\n\nThe ROR was 9.99.\n\n```\n",
        "<!--\n```r\nold\n-->\n\nThe ROR was 9.99.\n\n```r\nnew\n```\n",
    ],
    ids=["tilde fence under text", "fence in a code span", "fence opened in a comment"],
)
def test_audit_strict_refuses_a_fence_pandoc_may_not_open(
    tmp_path: Path, paper: str, capsys
) -> None:
    """Pandoc prints 9.99 in each. The audit read a listing over it, reported 0 numeric
    tokens, and `--strict` exited 0, where check and the build refuse the fence line."""
    from manuscript_guard.cli import main

    outputs = _outputs(tmp_path, '{"n": 1}')
    path = tmp_path / "paper.md"
    path.write_bytes(paper.encode("utf-8"))
    assert main(["audit", str(path), "--against", str(outputs), "--strict"]) == 1
    assert "not a plain fenced listing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "paper",
    [
        "- item above\n<!--\nThe hidden odds ratio was 9.99.\n\nmore -->\n",
        "- a stray ` tick\n- b `<!--` note 9.99 -->\n",
    ],
    ids=["under a list item", "code across list items"],
)
def test_audit_strict_refuses_a_comment_pandoc_ends_with_its_item(
    tmp_path: Path, paper: str, capsys
) -> None:
    """Pandoc prints 9.99 in each, and the audit, masking the comment as check does, read
    no number at all: `--strict` exited 0."""
    from manuscript_guard.cli import main

    outputs = _outputs(tmp_path, '{"n": 1}')
    path = tmp_path / "paper.md"
    path.write_bytes(paper.encode("utf-8"))
    assert main(["audit", str(path), "--against", str(outputs), "--strict"]) == 1
    assert "HTML comment" in capsys.readouterr().out


def test_a_bad_binding_after_a_comment_closed_in_a_listing_is_caught(project: Path) -> None:
    """The old binding parser got this right and the first version of the shared scanner
    did not: it read with the fences blanked, so the comment ran on over the binding."""
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\n<!-- draft\n```r\nx <- 1 # -->\n```\n\n"
        + "The ROR was {{results.no_such_key}}. <!-- a -->\n",
        encoding="utf-8",
    )
    assert "unresolved-binding" in codes(gate_report(project))


def test_g2_reads_a_number_in_an_escaped_comment(project: Path) -> None:
    """`\\<!--` opens no comment: pandoc prints "A note <!– 42 –> here.", and G2 masked it as
    one, so the 42 passed unbound. `import --apply` writes exactly this shape, since it
    escapes a `<` before `!` that a co-author typed in Word."""
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nA note \\<!-- 42 --> here.\n",
        encoding="utf-8",
    )
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and "42" in f.message for f in report.failures
    ), report.render(project)


def test_g2_reads_prose_between_comment_markers_in_code(project: Path) -> None:
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\n" + COMMENT_MARKERS_IN_CODE.format("9.99"),
        encoding="utf-8",
    )
    report = gate_report(project)
    assert any(
        f.code == "unclassified-number" and "9.99" in f.message for f in report.failures
    ), report.render(project)


def test_a_bad_binding_between_comment_markers_in_code_is_caught(project: Path) -> None:
    """Skipped as commented out, it was neither resolved nor substituted, and the document
    printed `{{results.no_such_key}}`."""
    path = main_md(project)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n\n"
        + COMMENT_MARKERS_IN_CODE.format("{{results.no_such_key}}"),
        encoding="utf-8",
    )
    assert "unresolved-binding" in codes(gate_report(project))


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


@pytest.mark.parametrize(("part", "note"), [("footnotes", "footnote"), ("endnotes", "endnote")])
def test_audit_joins_paragraphs_within_a_note(tmp_path: Path, part: str, note: str) -> None:
    """Footnotes and endnotes go through the same reader as the body. A deleted mark joins
    two paragraphs of one note, so "-0.5" and "1" there are -0.51, and the last paragraph
    of a note does not run on into the next note: "2" and "3" stay two numbers."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.5, "n": 1, "a": 2, "b": 3}')
    joined = f"<w:p>{_gone('del')}<w:r><w:t>The estimate was -0.5</w:t></w:r></w:p>{_p('1.')}"
    last = f"<w:p>{_gone('del')}<w:r><w:t>Group 2</w:t></w:r></w:p>"
    notes = "".join(f"<w:{note}>{body}</w:{note}>" for body in (joined, last, _p("3 more.")))
    paper = _docx(
        tmp_path / "paper.docx",
        _p("See the notes."),
        {f"word/{part}.xml": f"<w:{part} {W}>{notes}</w:{part}>"},
    )
    shown = {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched}
    assert shown == {"-0.51"}, shown


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


def test_audit_reads_a_number_typed_in_the_symbol_font(tmp_path: Path) -> None:
    """Word can keep text typed in the Symbol font as that font's private-use characters:
    "40" as U+F034 U+F030 (found in a real document). They are not digits, so the number was
    never seen, and a wrong one went unaudited while the file was reported as audited."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"days": 41}')
    fonts = '<w:rPr><w:rFonts w:ascii="Symbol" w:hAnsi="Symbol"/></w:rPr>'
    digits = f"<w:r>{fonts}<w:t>{chr(0xF034)}{chr(0xF030)}</w:t></w:r>"
    body = f'<w:p><w:r><w:t xml:space="preserve">Follow-up was </w:t></w:r>{digits}'
    body += '<w:r><w:t xml:space="preserve"> days.</w:t></w:r></w:p>'
    paper = _docx(tmp_path / "paper.docx", body)
    assert [c.text for c in audit([paper], [outputs]).unmatched] == ["40"]


@pytest.mark.parametrize("change", ["del", "moveFrom"])
def test_audit_reads_past_a_text_box_deleted_or_moved_out_of_the_reference_list(
    tmp_path: Path, change: str
) -> None:
    """A deleted text box's text was dropped, but its paragraphs still started lines. One
    styled as a heading was an empty heading, which ended the reference list there, and the
    entries after it were reported as numbers missing from the outputs. A box moved away
    with Track Changes on is the same where it was, and is read once, where it went."""
    from manuscript_guard.audit import audit
    from manuscript_guard.text.docx import read_docx_text

    outputs = _outputs(tmp_path, '{"n": 77, "panel": 12}')
    content = f"<w:txbxContent>{_p('Panel 12', 'Heading1')}</w:txbxContent>"
    box = (
        f'<w:{change} w:id="2" w:author="a"><w:r><w:drawing>{content}</w:drawing></w:r>'
        f"</w:{change}>"
    )
    entry = f"<w:p><w:r><w:t>Smith J. Lancet. 2019;393:1-2.</w:t></w:r>{box}</w:p>"
    moved_to = (
        '<w:p><w:r><w:t>See the panel.</w:t></w:r><w:moveTo w:id="3" w:author="a"><w:r>'
        f"<w:drawing>{content}</w:drawing></w:r></w:moveTo></w:p>"
        if change == "moveFrom"
        else ""
    )
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We found 77 cases.")
        + moved_to
        + _p("References", "Heading1")
        + entry
        + _p("Jones K. BMJ. 2020;368:45-52."),
    )
    report = audit([paper], [outputs])
    assert report.unmatched == [], report.unmatched
    lines = "3-5" if change == "del" else "5-7"
    assert report.not_audited == [f"paper.docx: lines {lines}, read as the reference list"]
    document = read_docx_text(paper)
    body = document.body.split("\n")
    # Only "References", and the moved copy before it, are headings: none inside the list.
    assert sorted(body[i] for i in document.headings) == sorted(
        ["References"] + (["Panel 12"] if change == "moveFrom" else [])
    )
    assert document.body.count("Panel 12") == (1 if change == "moveFrom" else 0)


#: A text box as Word writes one, twice over. In a row moved away Word 16 marks none of its
#: paragraphs, in either copy: the box goes with the text it is anchored in.
_BOX = (
    '<w:r><mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/'
    '2006"><mc:Choice Requires="wps"><w:drawing><w:txbxContent>'
    f"{_p('Panel 9')}</w:txbxContent></w:drawing></mc:Choice><mc:Fallback><w:pict>"
    f"<w:txbxContent>{_p('Panel 9')}</w:txbxContent></w:pict></mc:Fallback>"
    "</mc:AlternateContent></w:r>"
)


@pytest.mark.parametrize(
    ("row_mark", "mark", "text", "inside"),
    [
        ('<w:trPr><w:del w:id="3" w:author="a"/></w:trPr>', "", "del", ""),
        ('<w:trPr><w:del w:id="3" w:author="a"/></w:trPr>', "del", "del", ""),
        ("", "moveFrom", "moveFrom", ""),
        ("", "moveFrom", "moveFrom", _BOX),
    ],
    ids=["deleted-row", "deleted-row-and-mark", "moved-row", "moved-row-with-text-box"],
)
def test_audit_reads_past_a_table_row_gone_from_the_reference_list(
    tmp_path: Path, row_mark: str, mark: str, text: str, inside: str
) -> None:
    """Word marks a deleted table row in the row's own properties, not by wrapping it, and a
    row moved away not at all: it moves the mark of every paragraph in the row instead. The
    row's text was dropped, but its row and cell still started lines, and a cell styled as a
    heading was an empty heading, which ended the reference list there: the entries after
    it were reported as numbers missing from the outputs. A text box in a moved row has no
    mark moved, and read as one left in place it kept the row."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"n": 77}')
    gone = f'<w:rPr><w:{mark} w:id="5" w:author="a"/></w:rPr>' if mark else ""
    kind = "delText" if text == "del" else "t"
    cell = (
        f'<w:p><w:pPr><w:pStyle w:val="Heading1"/>{gone}</w:pPr><w:{text} w:id="4" '
        f'w:author="a"><w:r><w:{kind}>Old</w:{kind}></w:r>{inside}</w:{text}></w:p>'
    )
    row = f"<w:tr>{row_mark}<w:tc>{cell}</w:tc></w:tr>"
    paper = _docx(
        tmp_path / "paper.docx",
        _p("We found 77 cases.")
        + _p("References", "Heading1")
        + _p("Smith J. Lancet. 2019;393:1-2.")
        + f"<w:tbl>{row}</w:tbl>"
        + _p("Jones K. BMJ. 2020;368:45-52."),
    )
    report = audit([paper], [outputs])
    assert report.unmatched == [], report.unmatched
    assert report.not_audited == ["paper.docx: lines 3-5, read as the reference list"]


@pytest.mark.parametrize("change", ["del", "moveFrom"])
def test_audit_joins_a_paragraph_across_a_table_word_drops(tmp_path: Path, change: str) -> None:
    """A paragraph whose mark was deleted runs on past a table whose every row was deleted or
    moved away: Word 16 shows "-0.5", such a table, and "1" as -0.51. The table ended the
    line, so the two pieces were read apart and matched two outputs the paper never printed."""
    from manuscript_guard.audit import audit

    outputs = _outputs(tmp_path, '{"est": -0.5, "n": 1}')
    row_mark = '<w:trPr><w:del w:id="3" w:author="a"/></w:trPr>' if change == "del" else ""
    kind = "delText" if change == "del" else "t"
    cell = (
        f'<w:p>{_gone(change)}<w:{change} w:id="4" w:author="a"><w:r><w:{kind}>7</w:{kind}>'
        f"</w:r></w:{change}></w:p>"
    )
    table = f"<w:tbl><w:tr>{row_mark}<w:tc>{cell}</w:tc></w:tr></w:tbl>"
    before = "<w:r><w:t>The estimate was -0.5</w:t></w:r>"
    paper = _docx(tmp_path / "paper.docx", f"<w:p>{_gone('del')}{before}</w:p>{table}{_p('1.')}")
    shown = {c.text.rstrip(".") for c in audit([paper], [outputs]).unmatched}
    assert shown == {"-0.51"}, shown


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


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_comment_mark_in_a_listing_hides_no_binding_from_the_build(project: Path) -> None:
    """A `<!--` in a listing is code to pandoc. The placeholder parser on main read it as a
    comment that ran on to a later note's `-->`, so the binding between was never
    substituted, and the document printed `{{results.ror.point}}` while `check` passed.
    `test_comments.py` holds the parser to it; this holds the build, end to end. A listing
    of HTML is an ordinary thing to write, so the build must print the value, not refuse."""
    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    ticks = "`" * 3
    source.write_text(
        f"{text}\n# Appendix\n\n{ticks}html\n<!-- a comment left open in a listing\n{ticks}\n\n"
        "The reporting odds ratio was {{results.ror.point}}.\n\n<!-- a later note -->\n",
        encoding="utf-8",
    )
    assert main(["build", str(project), "--offline"]) == 0
    built = (project / "build" / "manuscript.md").read_text(encoding="utf-8")
    assert "{{results.ror.point}}" not in built
    value = load_namespace(load_project(project)[0])[0]["results.ror.point"].display
    assert f"The reporting odds ratio was {value}." in built


# A sentence in the example's Results, one in its Methods, and its last line.
_IN_RESULTS = "are shown in Table 1."
_IN_METHODS = "Reporting follows the checklist declared in `paper.yaml`."
_AT_END = "None declared.\n"


def _with_footnote(project: Path, referenced: tuple[str, ...], defined: str, note: str) -> None:
    """The example with `[^n]` after each sentence in `referenced`, and `note`, its
    definition, in a paragraph of its own after the sentence `defined`."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    for sentence in referenced:
        assert text.count(sentence) == 1, sentence
        text = text.replace(sentence, sentence + "[^n]")
    anchor = defined + "[^n]" if defined in referenced else defined
    assert text.count(anchor) == 1, anchor
    text = text.replace(anchor, anchor.rstrip("\n") + "\n\n" + note, 1)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("referenced", "defined", "note"),
    [
        # The review's reproduction: referenced from Results, defined under Methods.
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "[^n]: The excess was significant (p < 0.001).\n",
        ),
        # Its first paragraph runs on over lines, and later ones are indented.
        ((_IN_RESULTS,), _IN_METHODS, "[^n]: The excess\nwas significant (p < 0.001).\n"),
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "[^n]: A note.\n\n    The excess was significant (p < 0.001).\n",
        ),
        # Referenced from Methods and from Results, it prints in both, and must pass in both.
        (
            (_IN_METHODS, _IN_RESULTS),
            _AT_END,
            "[^n]: The excess was significant (p < 0.001).\n",
        ),
        # Found by the ninth review: a heading the walk found but pandoc prints as text
        # neither refuses a definition nor ends a note. An empty heading takes the line under
        # it as its title, and a lazy line of the note is shaped like a title `main` refused.
        ((_IN_RESULTS,), _IN_METHODS, "##\n[^n]: The excess was significant (p < 0.001).\n"),
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "######\n\n[^n]: The excess was significant (p < 0.001).\n",
        ),
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "[^n]: A note\n    > The excess was significant (p < 0.001).\n---\n",
        ),
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "#######\n[^n]: The excess was significant (p < 0.001).\n",
        ),
    ],
)
def test_a_footnote_is_read_where_it_is_referenced(
    project: Path, referenced: tuple[str, ...], defined: str, note: str
) -> None:
    """Pandoc prints a footnote where it is referenced. G2 filed its text under the section
    its definition sits in, so a finding referenced from Results and defined under Methods,
    `p < 0.001`, passed as the alpha chosen in advance, and the document printed it as a
    footnote to a Results sentence."""
    _with_footnote(project, referenced, defined, note)
    assert "unclassified-number" in codes(gate_report(project))


def test_a_note_s_lazy_pipe_line_is_read_where_it_is_referenced(project: Path) -> None:
    """Found by the ninth review. A lazy line of a note, shaped like a setext title starting
    `|` that the walk found and pandoc prints as the note's text, ended the note above it;
    its `p < 0.001` passed as the alpha, where `main` reports it as a table row."""
    note = "[^n]: A note\n    | The excess was significant (p < 0.001).\n-\n"
    _with_footnote(project, (_IN_RESULTS,), _IN_METHODS, note)
    assert "hand-authored-table" in codes(gate_report(project))


@pytest.mark.parametrize(
    "results",
    [
        "Text\n[^a]: As reported.[^n]\n---\n",
        "Text\n[^a]: A note\nAs reported.[^n]\n---\n",
    ],
    ids=["on the definition line", "on a lazy line"],
)
def test_a_reference_under_a_misread_definition_still_counts(project: Path, results: str) -> None:
    """Found by the tenth review. A `[^a]:` line over an underline is paragraph text to
    pandoc and a setext title to `main`, which refused it as a definition, so the `[^n]` on
    it counted as a reference in the Results. Taken for a definition, it swallowed that
    reference, and note n, defined under Methods, was judged there alone."""
    path = main_md(project)
    tail = f"# Methods\n\nText.\n\n[^n]: {_CLAIM}\n\n# Results\n\n{results}"
    path.write_text(path.read_text(encoding="utf-8") + "\n\n" + tail, encoding="utf-8")
    assert "unclassified-number" in codes(gate_report(project))


_CLAIM = "The excess was significant (p < 0.001)."


@pytest.mark.parametrize(
    "after_results",
    [
        # Found by review: text the gates took for a note's, which pandoc prints where it
        # stands, under Results. Judged at the Methods reference alone, each passed.
        # A `[^n]:` line under a paragraph's last line is that paragraph's to pandoc.
        f"\n[^n]: {_CLAIM}\n",
        # A list item holds the definition, and the four-space paragraph after it.
        f"\n\n- Serious cases were reviewed.\n\n  [^n]: By two assessors.\n\n    {_CLAIM}\n",
        # A line of no-break spaces is not blank to pandoc, and a comment ends the note.
        f"\n\n[^n]: By two assessors.\n\n{chr(0xA0)}\n    {_CLAIM}\n",
        f"\n\n[^n]: By two assessors.\n\n<!-- check wording -->\n\n    {_CLAIM}\n",
    ],
)
def test_a_claim_taken_for_a_note_s_text_is_judged_where_it_stands(
    project: Path, after_results: str
) -> None:
    """A number in a note is judged where it stands as well as at its references, so a claim
    the gates misread as a Methods note's text still fails in Results, as it did on main."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    text = text.replace(_IN_METHODS, _IN_METHODS + "[^n]", 1)
    text = text.replace(_IN_RESULTS, _IN_RESULTS + after_results, 1)
    path.write_text(text, encoding="utf-8")
    assert "unclassified-number" in codes(gate_report(project))


def test_a_note_nested_in_another_is_judged_where_it_stands(project: Path) -> None:
    """A definition in another note's indented block is a note of its own to pandoc,
    printed at its own reference in Results; the gates read it as the Methods note's."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    text = text.replace(_IN_METHODS, _IN_METHODS + "[^n]", 1)
    nested = f"[^m]\n\n[^n]: By two assessors.\n\n    [^m]: {_CLAIM}\n"
    text = text.replace(_IN_RESULTS, _IN_RESULTS + nested, 1)
    path.write_text(text, encoding="utf-8")
    assert "unclassified-number" in codes(gate_report(project))


def test_a_note_in_another_file_is_judged_where_it_stands(project: Path) -> None:
    """The build joins the main text's files, so a note is printed at references in other
    files too; each file is indexed apart, and a note referenced from a Methods-like section
    of its own file was judged there alone."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace(_IN_RESULTS, _IN_RESULTS + "[^n]", 1), encoding="utf-8")
    (project / "manuscript" / "appendix.md").write_text(
        "# Statistical analysis\n\nThe threshold was fixed in advance.[^n]\n\n"
        f"# Notes\n\n[^n]: {_CLAIM}\n",
        encoding="utf-8",
    )
    assert "unclassified-number" in codes(gate_report(project))


@pytest.mark.parametrize(
    ("referenced", "defined", "note"),
    [
        # Past its end the text is its own section's: a paragraph at the margin after a
        # blank line, or indented three spaces, is not the note's.
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "[^n]: A note.\n\nSignificance was set at p < 0.01.\n",
        ),
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "[^n]: A note.\n\n   Significance was set at p < 0.01.\n",
        ),
    ],
)
def test_a_footnote_s_alpha_is_read_where_it_is_referenced(
    project: Path, referenced: tuple[str, ...], defined: str, note: str
) -> None:
    _with_footnote(project, referenced, defined, note)
    assert not gate_report(project).failures, codes(gate_report(project))


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_an_import_does_not_bring_a_lone_colon_up_into_a_definition(
    project: Path, tmp_path: Path
) -> None:
    """A hard-wrapped paragraph whose last line is a lone `:`, reworded in its first stretch:
    the merge joined the first two lines, the `:` came up to line 2, and the next build
    printed a definition list with no identifier (#72's round-3 review)."""
    from manuscript_guard.cli import main

    path = main_md(project)
    paragraph = "We enrolled patients over\ntwo years, reaching {{results.ror.point}} of\n:\n\n"
    anchor = "# Data availability"
    path.write_text(
        path.read_text(encoding="utf-8").replace(anchor, paragraph + anchor, 1), "utf-8"
    )
    source = path.read_text(encoding="utf-8")
    assert main(["build", str(project), "--offline"]) == 0
    returned = _sent_back(
        project, tmp_path, lambda xml: xml.replace("We enrolled", "We recruited", 1)
    )

    main(["import", str(returned), str(project), "--apply"])
    assert path.read_text(encoding="utf-8") == source, "a lone colon became a definition"


# ------------------------------------------- a heading run into a paragraph, beside a change

_ALPHA = "Alpha paragraph talks about the cohort of patients."
_PAPA = "Papa paragraph reports that twelve reports were excluded for missing dates."
_ROMEO = "Romeo paragraph explains how duplicates were removed before the analysis."
_BRAVO = "Bravo paragraph describes the exposure window."
#: Blocks Word does not show, or shows elsewhere: a heading past one of them stands directly
#: beside the paragraph in Word, and pandoc prints a table's caption above the table.
_NOTE = "<!-- a note to self: check the counts -->"
_LINK = "[registry]: https://example.org/registry"
_TABLE = "| Drug | Reports |\n|------|---------|\n| A | 12 |\n| B | 30 |"
#: A paper cut down to a few paragraphs fails the gates; built past them, the document is
#: named for it.
_UNCHECKED = "manuscript.UNCHECKED.docx"


def _paper(project: Path, *blocks: str) -> Path:
    """The example with its main text replaced by `blocks`, its title kept."""
    path = main_md(project)
    text = path.read_text(encoding="utf-8")
    front = text[: text.index("\n---\n") + len("\n---\n")]
    path.write_text(front + "\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


def _shown(paragraph: str) -> str:
    """A Word paragraph's visible text."""
    return "".join(re.findall(r"<w:t(?:\s[^>]*)?>(.*?)</w:t>", paragraph, re.DOTALL))


def _run_into_papa(heading: str, *, below: bool):
    """The change Word makes when the heading reading `heading` is run into the Papa
    paragraph: Delete at the end of the paragraph above, or Backspace at the start of the one
    below. One paragraph, carrying Papa's identifier, reading "MethodsPapa..." or
    "...dates.Results"."""

    def change(xml: str) -> str:
        paragraphs = re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL)
        found = next(p for p in paragraphs if "mg-p-" not in p and _shown(p) == heading)
        papa = _word_paragraph(xml, "Papa paragraph")
        runs = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", found, flags=re.DOTALL)
        runs = re.sub(r"<w:bookmark(?:Start|End)[^>]*/>", "", runs[: -len("</w:p>")])
        if below:
            joined = papa[: -len("</w:p>")] + runs + "</w:p>"
        else:
            opening = re.match(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", papa, re.DOTALL)
            joined = opening.group(0) + runs + papa[opening.end() :]
        return xml.replace(found, "", 1).replace(papa, joined, 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("built", "now", "heading", "below"),
    [
        (
            ("# Intro", _ALPHA, _PAPA, "## Results\n" + _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, _PAPA, "## Findings\n" + _ROMEO, _BRAVO),
            "Results",
            True,
        ),
        (
            ("# Intro", _ALPHA, "## Methods\n" + _PAPA, "## Data", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, _PAPA, "## Data", _ROMEO, _BRAVO),
            "Methods",
            False,
        ),
        (
            ("# Intro", _ALPHA, "## Methods\n" + _PAPA, "## Data", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, "## Study design\n" + _PAPA, "## Data", _ROMEO, _BRAVO),
            "Methods",
            False,
        ),
        (
            ("# Intro", _ALPHA, "## Methods", _PAPA, "## Data", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, "## Methods", "## Sub\n" + _PAPA, "## Data", _ROMEO, _BRAVO),
            "Methods",
            False,
        ),
        (
            # One block added above, one removed: Papa keeps its identifier.
            ("# Intro", _ALPHA, "## Methods", _PAPA, _ROMEO, _BRAVO),
            ("# Intro", "A paragraph added since the build.", _ALPHA, _PAPA, _ROMEO, _BRAVO),
            "Methods",
            False,
        ),
        (
            ("# Intro", _ALPHA, _PAPA, "## Results", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO),
            "Results",
            True,
        ),
        (
            ("# Intro", _ALPHA, _PAPA, _NOTE, "## Results", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, _PAPA, _NOTE, _ROMEO, _BRAVO),
            "Results",
            True,
        ),
        (
            ("# Intro", _ALPHA, _PAPA, _LINK, "## Results", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, _PAPA, _LINK, _ROMEO, _BRAVO),
            "Results",
            True,
        ),
        (
            ("# Intro", "## Methods", _NOTE, _PAPA, _ROMEO, _BRAVO),
            ("# Intro", "A paragraph added since the build.", _NOTE, _PAPA, _ROMEO, _BRAVO),
            "Methods",
            False,
        ),
        (
            ("# Intro", _ALPHA, _PAPA, _TABLE, ": Counts by drug", _ROMEO, _BRAVO),
            ("# Intro", _ALPHA, _PAPA, _TABLE, _ROMEO, _BRAVO),
            "Counts by drug",
            True,
        ),
    ],
    ids=[
        "glued below, renamed",
        "glued above, removed",
        "glued above, renamed",
        "glued above, added",
        "above, removed",
        "below, removed",
        "below past a comment, removed",
        "below past a link definition, removed",
        "above past a comment, removed",
        "caption after its table, removed",
    ],
)
def test_a_heading_run_into_a_paragraph_beside_a_changed_one_is_not_merged(
    project: Path,
    tmp_path: Path,
    built: tuple[str, ...],
    now: tuple[str, ...],
    heading: str,
    below: bool,
) -> None:
    """A heading run into the paragraph beside it in Word is refused: its text would be in
    the source twice. It is recognised by the heading beside the paragraph having vanished
    while its text turned up in the paragraph, and the heading looked at is the one in the
    source now. One changed in the `.md` since the build, renamed, removed, or written straight
    above a paragraph with no blank line, is not the one the co-author ran in, and the run-in
    merged: "MethodsPapa paragraph..." under a heading the file no longer has. The record held
    nothing of a heading written straight above a paragraph."""
    from manuscript_guard.cli import main

    path = _paper(project, *built)
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0
    returned = _sent_back(
        project, tmp_path, _run_into_papa(heading, below=below), document=_UNCHECKED
    )
    _paper(project, *now)
    source = path.read_text(encoding="utf-8")

    main(["import", str(returned), str(project), "--apply", "--force"])
    assert path.read_text(encoding="utf-8") == source, "a run-in heading was merged"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("name", "below"),
    [("results.md", True), ("1_methods.md", True), ("1_methods.md", False)],
    ids=["after main.md, below", "before main.md by path, below", "before main.md, above"],
)
def test_a_heading_across_a_file_boundary_run_into_a_paragraph_is_not_merged(
    project: Path, tmp_path: Path, name: str, below: bool
) -> None:
    """The files of the main text are one document, so the heading opening the next file
    stands directly under the last paragraph of this one in Word, and one closing this file
    directly above the first paragraph of the next. Removed from the `.md` since the build,
    it was in nothing either paragraph's record held, and its run-in merged. The build
    prints `main.md` first and the rest by file name, whatever their paths sort as: read in
    path order, `1_methods.md` came before `main.md`, and its heading was beside nothing."""
    from manuscript_guard.cli import main

    other = main_md(project).parent / name
    if below:
        path = _paper(project, "# Intro", _ALPHA, _PAPA)
        other.write_text(f"# Methods\n\n{_ROMEO}\n\n{_BRAVO}\n", encoding="utf-8")
    else:
        path = _paper(project, "# Intro", _ALPHA, "## Methods")
        other.write_text(f"{_PAPA}\n\n{_ROMEO}\n\n{_BRAVO}\n", encoding="utf-8")
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0
    returned = _sent_back(
        project, tmp_path, _run_into_papa("Methods", below=below), document=_UNCHECKED
    )
    if below:
        other.write_text(f"{_ROMEO}\n\n{_BRAVO}\n", encoding="utf-8")
    else:
        _paper(project, "# Intro", _ALPHA)
    sources = path.read_text(encoding="utf-8"), other.read_text(encoding="utf-8")

    main(["import", str(returned), str(project), "--apply", "--force"])
    now = path.read_text(encoding="utf-8"), other.read_text(encoding="utf-8")
    assert now == sources, "a run-in heading was merged"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "changed",
    [
        (_ALPHA, "Alpha paragraph talks about the cohort of adult patients."),
        (_ROMEO, "Romeo paragraph explains how duplicates were removed first."),
        (_BRAVO, "Bravo paragraph, reworded by the author since."),
    ],
    ids=["the paragraph above", "the paragraph below", "one further off"],
)
def test_a_rewording_beside_headings_that_did_not_change_still_merges(
    project: Path, tmp_path: Path, changed: tuple[str, str]
) -> None:
    """Only a paragraph beside a changed heading or other block without an identifier is
    refused. With another paragraph reworded in the `.md` since the build, next to it or
    not, no heading could have stood where that paragraph stands, and the co-author's
    rewording merges as on main."""
    from manuscript_guard.cli import main

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, "## Data", _BRAVO)
    path = _paper(project, *blocks)
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0

    def reworded(xml: str) -> str:
        return xml.replace("were excluded for missing dates", "were dropped for missing dates", 1)

    returned = _sent_back(project, tmp_path, reworded, document=_UNCHECKED)
    _paper(project, *(changed[1] if block == changed[0] else block for block in blocks))
    source = path.read_text(encoding="utf-8")

    main(["import", str(returned), str(project), "--apply", "--force"])
    assert path.read_text(encoding="utf-8") == source.replace(
        "were excluded for missing dates", "were dropped for missing dates", 1
    )


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_heading_run_into_a_paragraph_is_not_merged_where_it_prints_otherwise_now(
    project: Path, tmp_path: Path
) -> None:
    """Its source is unchanged, but a value in it is not: the heading looked at printed
    "Results in 4100 reports", the co-author ran in "Results in 4000 reports", and the
    run-in merged, 4000 typed into the paragraph as a number no binding prints."""
    from manuscript_guard.cli import main

    heading = "## Results in {{results.cohort.n_reports}} reports"
    path = _paper(project, "# Intro", _ALPHA, _PAPA, heading, _ROMEO, _BRAVO)
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0
    returned = _sent_back(
        project,
        tmp_path,
        _run_into_papa("Results in 4000 reports", below=True),
        document=_UNCHECKED,
    )
    fragment = project / "results" / "01_disproportionality.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["values"]["cohort.n_reports"].update(value=4100, display="4100")
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    source = path.read_text(encoding="utf-8")

    main(["import", str(returned), str(project), "--apply", "--force"])
    assert path.read_text(encoding="utf-8") == source, "a run-in heading was merged"


# --------------------------------- a paste or a move beside what the source changed since

#: A paragraph that is only a value: 4000 reports at the build, re-run to 4100 in some tests.
_REPORTS = "{{results.cohort.n_reports}}"


def _forced_import(
    project: Path,
    tmp_path: Path,
    built: tuple[str, ...],
    now: tuple[str, ...],
    change,
    *,
    reports: int | None = None,
) -> tuple[str, str, str]:
    """The main text built as `built`, returned with `change` made to it in Word, rewritten as
    `now` in the `.md` - and with the analysis re-run to count `reports` reports, if given -
    then imported with --force: the source after, the source before, and what was printed."""
    from contextlib import redirect_stdout
    from io import StringIO

    from manuscript_guard.cli import main

    path = _paper(project, *built)
    assert main(["build", str(project), "--offline", "--skip-checks"]) == 0
    returned = _sent_back(project, tmp_path, change, document=_UNCHECKED)
    _paper(project, *now)
    if reports is not None:
        fragment = project / "results" / "01_disproportionality.json"
        document = json.loads(fragment.read_text(encoding="utf-8"))
        document["values"]["cohort.n_reports"].update(value=reports, display=str(reports))
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)
    before = path.read_text(encoding="utf-8")
    printed = StringIO()
    with redirect_stdout(printed):
        main(["import", str(returned), str(project), "--apply", "--force"])
    return path.read_text(encoding="utf-8"), before, printed.getvalue()


def _paragraph_runs(paragraph: str) -> str:
    """A Word paragraph's runs, without its properties or its bookmarks."""
    runs = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", paragraph, flags=re.DOTALL)
    return re.sub(r"<w:bookmark(?:Start|End)[^>]*/>", "", runs[: -len("</w:p>")])


def _pasted(words: str, into: str, *, cut: bool = True, left: str | None = None):
    """The paragraph holding `words` pasted onto the end of the one holding `into`, after a
    space, as a paste without Track Changes leaves it: the runs, and no bookmark. Cut, the
    paragraph is gone from where it stood; copied, it is still there.

    Word 16 does not delete a cut paragraph's identifier with its text: `left` puts it where
    Word leaves it, in front of the next paragraph's own ("next", as `_word_delete` in
    tests/test_roundtrip.py does) or on the emptied line ("emptied")."""

    def change(xml: str) -> str:
        pasted = _word_paragraph(xml, words)
        runs = _paragraph_runs(pasted)
        if cut and left == "next":
            from test_roundtrip import _word_delete

            xml = _word_delete(xml, pasted)
        elif cut and left == "emptied":
            opening = re.match(
                r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?(?:<w:bookmark(?:Start|End)\b[^>]*/>)*",
                pasted,
                re.DOTALL,
            )
            xml = xml.replace(pasted, opening.group(0) + "</w:p>", 1)
        elif cut:
            xml = xml.replace(pasted, "", 1)
        target = _word_paragraph(xml, into)
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(target, target[: -len("</w:p>")] + space + runs + "</w:p>", 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_value_paragraph_pasted_into_another_is_not_merged_once_the_value_is_rerun(
    project: Path, tmp_path: Path
) -> None:
    """A paragraph that is only a value, printing 4000, cut and pasted onto the end of
    another in Word; the analysis re-run to 4100 before the import. The paste check weighed
    the words the paragraph gained against the value's paragraph as the fresh build prints
    it, "4100", found nothing, and "...dates. 4000" was merged: a number typed into prose
    beside the binding that prints it. Only the words it printed outside its bindings and
    citations are known of what a paragraph printed at the build, and a value alone has
    none."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _REPORTS, _BRAVO)
    after, before, _out = _forced_import(
        project, tmp_path, blocks, blocks, _pasted(">4000<", "Papa paragraph"), reports=4100
    )
    assert after == before, "a number was typed into the source"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_value_paragraph_joined_into_the_one_above_is_not_merged_once_the_value_is_rerun(
    project: Path, tmp_path: Path
) -> None:
    """The same, joined: "None." and the value after it, retyped across the break so the
    value's identifier goes. Weighed against "4100", "None. 4000" read no more like the two
    together than like "None." alone, and merged as a rewording."""

    def joined(xml: str) -> str:
        return _pasted(">4000<", ">None.<")(xml)

    blocks = ("# Notes", _ALPHA, "None.", _REPORTS, _BRAVO)
    after, before, _out = _forced_import(project, tmp_path, blocks, blocks, joined, reports=4100)
    assert after == before, "a number was typed into the source"


def _elsewhere(blocks: tuple[str, ...]) -> tuple[str, ...]:
    """The `.md` edited since the build where Word left it alone: stale, nothing re-run."""
    return tuple(block.replace("exposure window", "exposure period") for block in blocks)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (f"{_REPORTS}.", ">4000.<"),
        ("{{results.ror.ci_low}}\N{EN DASH}{{results.ror.ci_high}}", "5.12<"),
    ],
    ids=["full stop", "range"],
)
def test_a_value_with_punctuation_pasted_in_a_stale_document_is_not_merged(
    project: Path, tmp_path: Path, value: str, shown: str
) -> None:
    """Round 1 of #116's review. Only the words outside a paragraph's bindings were taken as
    what it printed at the build, and a full stop or a dash beside a value was kept as a word
    of its own: "." and "–", never found among "4000." or "2.89–5.12". The value paragraph
    counted as known, and pasted into Papa it merged, where main, weighing the fresh
    rendering, which is what was sent when nothing was re-run, refused it."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, value, _BRAVO)
    after, before, _out = _forced_import(
        project, tmp_path, blocks, _elsewhere(blocks), _pasted(shown, "Papa paragraph")
    )
    assert after == before, "numbers were typed into Papa"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_an_interval_joined_in_a_stale_document_is_not_merged(
    project: Path, tmp_path: Path
) -> None:
    """The same, joined: "(" and ")" beside the interval's values were words of their own,
    and "...was as follows. 3.84 (2.89 to 5.12)" merged as a rewording."""
    lead = "The reporting odds ratio for the main model, with its interval, was as follows."
    trio = "{{results.ror.point}} ({{results.ror.ci_low}} to {{results.ror.ci_high}})"
    blocks = ("# Results", _ALPHA, _PAPA, _ROMEO, lead, trio, _BRAVO)
    after, before, _out = _forced_import(
        project, tmp_path, blocks, _elsewhere(blocks), _pasted("(2.89", "was as follows.")
    )
    assert after == before, "numbers were typed into the paragraph above"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("blocks", "into"),
    [
        (("# Intro", _ALPHA, _PAPA, _ROMEO, f"{_REPORTS}.", _BRAVO), "Papa paragraph"),
        (("# Notes", _ALPHA, "None.", f"{_REPORTS}.", _BRAVO), ">None.<"),
    ],
    ids=["pasted", "joined"],
)
def test_a_value_with_a_full_stop_is_not_merged_once_rerun(
    project: Path, tmp_path: Path, blocks: tuple[str, ...], into: str
) -> None:
    """The first two tests above, with a full stop after the value: re-run to 4100, "4000."
    was weighed as the word "." and merged."""
    after, before, _out = _forced_import(
        project, tmp_path, blocks, blocks, _pasted(">4000.<", into), reports=4100
    )
    assert after == before, "a stale number was typed into the source"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("twelve reports were excluded", "twelve of the reports were excluded"),
        ("were excluded for missing dates.", "were excluded."),
    ],
    ids=["a word added", "a sentence's end cut"],
)
@pytest.mark.parametrize("author", ["reworded", "dropped"])
def test_an_edit_merges_when_word_deletes_a_paragraph_the_author_also_changed(
    project: Path, tmp_path: Path, old: str, new: str, author: str
) -> None:
    """Round 1 of #116's review: with a paragraph the author also changed, or dropped,
    deleted in Word, every rewording in the document that gained a word was refused, since
    what the deleted one said could not be known. Only a rewording that gained five words in
    a row, or a word with a digit in it, could hold such a paragraph pasted in; a word added
    and a clause cut merge, as on main."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = _elsewhere(blocks) if author == "reworded" else blocks[:-1]

    def change(xml: str) -> str:
        return xml.replace(_word_paragraph(xml, "Bravo paragraph"), "", 1).replace(old, new, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert after == before.replace(old, new, 1), out


def test_what_a_paragraph_printed_is_read_past_a_no_break_space_the_marked_build_lacks() -> None:
    """Pandoc puts a no-break space after "et al." before a citation, and not before the
    bookmark the marked build puts around it. Compared character for character, the two
    builds differed, and in a document built from other inputs every such paragraph read as
    saying nothing known. The words that touch no binding or citation are what was sent."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import _as_sent

    fresh = f"As Smith et al.{chr(0xA0)}(2020) found, 4100 reports were screened."
    plain = fresh.replace(chr(0xA0), " ")
    spans = tuple((plain.index(t), plain.index(t) + len(t)) for t in ("(2020)", "4100"))
    words = _as_sent(fresh, Block(("p",), plain, tokens=spans), stale=True)
    assert words == ["As", "Smith", "et", "al.", "found,", "reports", "were", "screened."]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_paragraph_whose_words_are_not_known_is_named_by_where_it_stood(
    project: Path, tmp_path: Path
) -> None:
    """The refusal quoted the paragraph's identifier, 'mg-p-...', which the author cannot
    find anywhere. It names the paragraph before it in the document as sent instead. That
    is for a document without its record of what it printed (`_without_record`, below):
    with it, the paragraph is named by what it said, which the record holds."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = (*blocks[:2], "A paragraph the author wrote in place of Papa.", *blocks[3:])
    pasted = _pasted("Papa paragraph", "Bravo paragraph")
    _after, _before, out = _forced_import(project, tmp_path, blocks, now, pasted)
    assert "it came back holding another paragraph ('Papa paragraph reports" in out
    assert "did not come back (" not in out

    def unrecorded(xml: str) -> str:
        _without_record(project)
        return pasted(xml)

    _after, _before, out = _forced_import(project, tmp_path, blocks, now, unrecorded)
    refusal = next(line for line in out.splitlines() if "did not come back (" in line)
    assert "the one after 'Alpha paragraph talks about" in refusal
    assert "mg-p-" not in refusal


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("reworded", "left"),
    [(_ALPHA, "next"), (_ALPHA, "emptied"), (_PAPA, "next")],
    ids=[
        "the pasted one reworded, identifier left on the next",
        "the pasted one reworded, identifier left on the emptied line",
        "a guard: the next one reworded, identifier left on it",
    ],
)
def test_a_paragraph_cut_in_word_whose_identifier_stayed_is_looked_for(
    project: Path, tmp_path: Path, reworded: str, left: str
) -> None:
    """Word 16 does not delete a cut paragraph's identifier: it goes in front of the next
    paragraph's own, or stays on the emptied line. Alpha, reworded in the `.md` since the
    build and so not compared, was cut and pasted onto the end of Romeo; its identifier left
    behind was taken for the paragraph having come back, so it was never looked for in
    Romeo's new words, and Romeo merged holding Alpha's old sentence, twice in the source. A
    paragraph whose identifier came back only on other text - beside another's, on an empty
    line, in a join that does not hold its text - did not come back. The last case, with
    Papa reworded instead and Alpha compared, main already refuses: Alpha's text is looked
    for whole in Romeo."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(
        block.replace(" paragraph ", " paragraph, reworded, ", 1) if block == reworded else block
        for block in blocks
    )
    after, before, _out = _forced_import(
        project, tmp_path, blocks, now, _pasted("Alpha paragraph", "Romeo paragraph", left=left)
    )
    assert after == before, "a paragraph's words went into the source twice"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("was", "now"),
    [
        (_REPORTS, f"{_REPORTS} reports"),
        (_ROMEO, _ROMEO.replace(" paragraph ", " paragraph, reworded, ", 1)),
    ],
    ids=["the value reworded", "the next one reworded"],
)
def test_a_value_cut_in_word_whose_identifier_stayed_is_not_merged_as_a_number(
    project: Path, tmp_path: Path, was: str, now: str
) -> None:
    """The same with a paragraph that is only a value, printing 4000, cut and pasted onto the
    end of Papa, and the analysis re-run to 4100: "...dates. 4000" merged, a number typed
    beside the binding that prints it. The value reworded in the `.md`, its identifier on
    Romeo's was taken for the paragraph; Romeo reworded, the two read as a join."""
    blocks = ("# Intro", _ALPHA, _PAPA, _REPORTS, _ROMEO, _BRAVO)
    after, before, _out = _forced_import(
        project,
        tmp_path,
        blocks,
        tuple(now if block == was else block for block in blocks),
        _pasted(">4000<", "Papa paragraph", left="next"),
        reports=4100,
    )
    assert after == before, "a stale number was typed into the source"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_rerun_paragraph_deleted_in_word_leaves_a_rewording_elsewhere_to_merge(
    project: Path, tmp_path: Path
) -> None:
    """What a paragraph printed at the build is known outside its bindings: its words there
    are weighed, and a rewording that holds none of them merges, as on main."""
    counted = f"Of {_REPORTS} reports screened, twelve were duplicates of earlier ones."
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, counted, _BRAVO)

    def edited(xml: str) -> str:
        xml = xml.replace(_word_paragraph(xml, "reports screened"), "", 1)
        return xml.replace("were excluded for missing dates", "were dropped for missing dates", 1)

    after, before, _out = _forced_import(project, tmp_path, blocks, blocks, edited, reports=4100)
    assert after == before.replace("were excluded for missing", "were dropped for missing", 1)


def _reworded(block: str) -> str:
    """`block` as the author reworded it in the `.md` since the build."""
    return block.replace(" paragraph ", " paragraph, reworded, ", 1)


def _word_joined(first: str, second: str):
    """The paragraph holding `first` joined with the one after it, holding `second`, as
    Delete at the end of the first leaves it with Track Changes off, a space typed between
    them: one paragraph in the first's style, the second's identifier where its text begins."""

    def change(xml: str) -> str:
        one, two = _word_paragraph(xml, first), _word_paragraph(xml, second)
        rest = re.sub(r"^<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", "", two, flags=re.DOTALL)
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(two, "", 1).replace(one, one[: -len("</w:p>")] + space + rest, 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "added", [", which ran from the first to the last dose.", " in 2019."], ids=["clause", "year"]
)
@pytest.mark.parametrize("shape", ["deleted", "joined", "moved"])
def test_an_edit_merges_beside_a_change_in_word_before_a_paragraph_the_author_changed(
    project: Path, tmp_path: Path, shape: str, added: str
) -> None:
    """Round 1 of #119's review. Word 16 puts the identifier of a paragraph deleted or cut
    with Track Changes off in front of the next paragraph's own, and keeps the second
    identifier of a join where the second paragraph's text begins. Romeo, the next one here,
    was reworded in the `.md` since the build and so not compared: what it said was not
    known, a block with two identifiers could not say whose text it held, and Romeo counted
    as not come back although it stood there untouched. Every rewording in the document that
    gained five words or a digit was then refused, which main merges. Each identifier owns
    the text from its bookmark to the next one's, and Romeo's is Romeo's paragraph."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(_reworded(block) if block == _ROMEO else block for block in blocks)
    # Moved to the start of Bravo, Papa takes Bravo's identifier: Alpha is edited instead.
    target = _ALPHA if shape == "moved" else _BRAVO
    edited = target[:-1] + added

    def change(xml: str) -> str:
        from test_roundtrip import _word_delete, _word_paste

        papa = _word_paragraph(xml, "Papa paragraph")
        if shape == "deleted":
            xml = _word_delete(xml, papa)
        elif shape == "joined":
            xml = _word_joined("Papa paragraph", "Romeo paragraph")(xml)
        else:
            xml = _word_paste(xml, [papa], _word_paragraph(xml, "Bravo paragraph"), "untracked")
        return xml.replace(target, edited, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert after == before.replace(target, edited, 1), out
    assert "did not come back (" not in out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "added", [", which began only in the last year of the study.", " in 2019."]
)
def test_an_edit_merges_in_the_example_beside_a_deletion_before_a_paragraph_the_author_changed(
    project: Path, tmp_path: Path, added: str
) -> None:
    """The same in the example, as the review made it in Word 16: the author rewords the
    paragraph on the event term, the co-author deletes the one before it and adds to the
    Discussion. The refusal said the event-term paragraph "did not come back", and it was
    there, unchanged."""
    from contextlib import redirect_stdout
    from io import StringIO

    from test_roundtrip import _word_delete

    from manuscript_guard.cli import main

    path = main_md(project)
    assert main(["build", str(project), "--offline"]) == 0
    ending = "predates the marketing of example-drug."

    def change(xml: str) -> str:
        xml = _word_delete(xml, _word_paragraph(xml, "We analysed a synthetic"))
        return xml.replace(ending, ending[:-1] + added, 1)

    returned = _sent_back(project, tmp_path, change)
    hepatic = "Hepatic injury is the single event term used by the data generator."
    reworded = "Hepatic injury is the only event term the data generator uses."
    path.write_text(path.read_text(encoding="utf-8").replace(hepatic, reworded, 1), "utf-8")
    before = path.read_text(encoding="utf-8")
    printed = StringIO()
    with redirect_stdout(printed):
        main(["import", str(returned), str(project), "--apply", "--force"])
    out = printed.getvalue()
    # The merge rewraps the paragraph's lines.
    after = " ".join(path.read_text(encoding="utf-8").split())
    assert after == " ".join(before.replace(ending, ending[:-1] + added, 1).split()), out
    assert "did not come back (" not in out


def test_a_paragraph_whose_identifier_holds_text_it_cannot_be_told_by_is_not_said_gone(
    tmp_path: Path,
) -> None:
    """The refusal said a paragraph whose words are not known "did not come back" whenever
    its identifier was not read as on its own text: untrue of one whose identifier stands on
    text that cannot be told for its own, here text reading exactly as Bravo's. It says the
    paragraph may not have come back. One whose identifier is nowhere, or holds nothing,
    did not come back."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    reworded = _reworded(_ROMEO)
    path = tmp_path / "main.md"
    text = f"{_ALPHA}\n\n{reworded}\n\n{_BRAVO}\n"
    path.write_text(text, encoding="utf-8")
    known = {name: (path, line, text.index(line)) for name, line in (("a", _ALPHA), ("b", _BRAVO))}
    sent = [Block(("a",), _ALPHA), Block(("r",), reworded), Block(("b",), _BRAVO)]
    grown = Block(("b",), _BRAVO[:-1] + ", which ran from the first to the last dose.")
    reasons = {}
    for case, held in (("unsure", _BRAVO), ("gone", "")):
        returned = [Block(("a",), _ALPHA), Block(("r",), held), grown]
        plan = plan_import(known, sent, returned, built=("a", "r", "b"))
        reasons[case] = " ".join(why for refusal in plan.refused for why in refusal.why)
    assert "may not have come back (the one after 'Alpha paragraph" in reasons["unsure"]
    assert "did not come back" not in reasons["unsure"]
    assert "did not come back (the one after 'Alpha paragraph" in reasons["gone"]


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("left", ["in front of the next", "joined onto the one before"])
def test_a_paragraph_cut_in_word_is_looked_for_though_the_one_holding_its_identifier_changed(
    project: Path, tmp_path: Path, left: str
) -> None:
    """Guards for the reading above. Papa, reworded in the `.md` and so not compared, is cut
    and pasted onto the end of Bravo, and the paragraph its identifier was left on is edited
    too: Romeo, with Papa's identifier in front of its own, or Alpha, with the line Papa's
    text left empty joined onto its end. Neither holds Papa's text, but read as a block with
    one identifier whose text is not known, Papa's counted as come back there, and Bravo
    merged holding Papa's old sentence, twice in the source. Papa's identifier owns the text
    after it and before the next one: none."""
    from test_roundtrip import _parts, _word_delete

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(_reworded(block) if block == _PAPA else block for block in blocks)

    def change(xml: str) -> str:
        papa = _word_paragraph(xml, "Papa paragraph")
        runs = _paragraph_runs(papa)
        if left == "in front of the next":
            xml = _word_delete(xml, papa)
            xml = xml.replace("duplicates were removed", "duplicates were taken out", 1)
        else:
            _props, mark, _runs = _parts(papa)
            xml = xml.replace(papa, "", 1)
            alpha = _word_paragraph(xml, "Alpha paragraph")
            xml = xml.replace(alpha, alpha[: -len("</w:p>")] + mark + "</w:p>", 1)
            xml = xml.replace("talks about the cohort", "is about the cohort", 1)
        bravo = _word_paragraph(xml, "Bravo paragraph")
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(bravo, bravo[: -len("</w:p>")] + space + runs + "</w:p>", 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert after == before, out


#: A lead-in sentence and the list it introduces, and a block quotation: blocks the build
#: gives no identifier, and Word 16 puts a cut paragraph's identifier at their start.
_LEAD = "Papa paragraph reports what was excluded from the analysis:"
_LIST = "- reports without a date of onset\n- reports without a drug name"
_ITEM = ("reports without a date of onset", "reports with no date of onset")
_QUOTE = "> A quoted line from the guideline for the review."
_QUOTED = ("A quoted line from the guideline", "A quoted line taken from the guideline")


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("blocks", "cut", "into", "edit", "reports"),
    [
        (("# Intro", _ALPHA, _LEAD, _LIST, _ROMEO, _BRAVO), "Papa", "Romeo", _ITEM, None),
        (("# Intro", _ALPHA, _PAPA, _QUOTE, _ROMEO, _BRAVO), "Papa", "Romeo", _QUOTED, None),
        (
            ("# Intro", _ALPHA, _PAPA, _REPORTS, _LIST, _ROMEO, _BRAVO),
            ">4000<",
            "Papa",
            _ITEM,
            4100,
        ),
    ],
    ids=["before a list", "before a quotation", "a value before a list"],
)
def test_a_paragraph_cut_before_an_edited_list_or_quote_is_not_that_block(
    project: Path,
    tmp_path: Path,
    blocks: tuple[str, ...],
    cut: str,
    into: str,
    edit: tuple[str, str],
    reports: int | None,
) -> None:
    """Round 1 of #119's review, on main too. Cut in Word and pasted onto the end of another
    paragraph, a paragraph's identifier went to the start of the list item or quotation after
    it, and that block was edited. An identifier on a heading is taken off by its style; on a
    list item or a quotation it stayed, and read as the paragraph reworded: the lead-in's
    source was replaced by the list item's text, or Papa merged "...dates. 4000". Neither
    block is ever given an identifier, and one on them is taken off as from a heading."""

    def change(xml: str) -> str:
        return _pasted(cut, into, left="next")(xml).replace(*edit, 1)

    after, before, out = _forced_import(
        project, tmp_path, blocks, blocks, change, reports=reports
    )
    assert after == before, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("quotation", ["edited in Word", "edited in the .md"])
def test_a_paragraph_the_author_changed_cut_before_a_quotation_is_looked_for(
    project: Path, tmp_path: Path, quotation: str
) -> None:
    """The same with Papa reworded in the `.md`, and so not compared, pasted onto the end of
    Bravo: its identifier on the quotation, which no longer read as the quotation the fresh
    build prints, counted as Papa come back, and Bravo merged holding Papa's old sentence."""
    blocks = ("# Intro", _ALPHA, _PAPA, _QUOTE, _ROMEO, _BRAVO)
    now = tuple(_reworded(block) if block == _PAPA else block for block in blocks)
    if quotation == "edited in the .md":
        now = tuple(block.replace(*_QUOTED) for block in now)

    def change(xml: str) -> str:
        xml = _pasted("Papa paragraph", "Bravo paragraph", left="next")(xml)
        return xml.replace(*_QUOTED, 1) if quotation == "edited in Word" else xml

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert after == before, out


#: A loose list: its first item has a second paragraph, which the build gives an identifier
#: and pandoc numbers with no marker, in front of an item, which has none.
_LOOSE = (
    "- zulu item one\n\n"
    "  Papa continuation paragraph reports that twelve reports were excluded.\n\n"
    "- zulu item two"
)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("how", ["deleted", "cut"])
def test_a_list_items_second_paragraph_is_not_the_next_item(
    project: Path, tmp_path: Path, how: str
) -> None:
    """Round 2 of #119's review, on main too. The second paragraph of a loose list item has
    an identifier, and being numbered it read as a list item, like the item after it.
    Deleted or cut in Word, it left its identifier on that item, which, "sent with the role
    it has", kept it: edited, the item was written over the paragraph's source line and the
    item left as it was. The paragraph was built with no marker and the item with one, so
    the item is not a block the build gave that identifier."""
    from test_roundtrip import _word_delete

    blocks = ("# Intro", _ALPHA, _LOOSE, _ROMEO, _BRAVO)

    def change(xml: str) -> str:
        if how == "cut":
            xml = _pasted("Papa continuation", "Romeo paragraph", left="next")(xml)
        else:
            xml = _word_delete(xml, _word_paragraph(xml, "Papa continuation"))
        return xml.replace("zulu item two", "zulu item number two", 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("block", "edit"),
    [
        (
            "Zulu ratio of the reports\n:   the zulu definition of the ratio",
            ("Zulu ratio of the reports", "Zulu ratio of all the reports"),
        ),
        (
            '::: {custom-style="Zulu Note"}\nzulu styled note text here.\n:::',
            ("zulu styled note text", "zulu styled note words"),
        ),
        ("```\nzulu code line one\n```", ("zulu code line one", "zulu code line two")),
    ],
    ids=["definition list", "custom-style div", "code block"],
)
def test_a_paragraph_cut_before_another_block_without_an_identifier_is_not_that_block(
    project: Path, tmp_path: Path, block: str, edit: tuple[str, str]
) -> None:
    """Round 2 of #119's review, on main too. An identifier was taken off the blocks known
    by a role: a heading, a caption, a reference entry, a list item, a quotation. A paragraph
    cut before the term of a tight definition list, a div with a style of its own or a code
    block left its identifier there, and edited, that block was written over the paragraph.
    The build gives none of them an identifier, and an identifier left on a block of a kind
    the build gives none, which is not the kind its own paragraph was built as, is taken
    off, whatever the kind."""
    blocks = ("# Intro", _ALPHA, _LEAD, block, _ROMEO, _BRAVO)

    def change(xml: str) -> str:
        return _pasted("Papa paragraph", "Romeo paragraph", left="next")(xml).replace(*edit, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out


_CONTINUED = "Papa continuation paragraph reports that twelve reports were excluded."


def _restyled(was: str, now: str):
    """The paragraph reading `was` given a style the build uses nowhere, and rewritten as
    `now`."""

    def change(xml: str) -> str:
        paragraph = _word_paragraph(xml, was)
        styled = re.sub(r'<w:pStyle w:val="[^"]*"\s*/>', '<w:pStyle w:val="ZuluOwn"/>', paragraph)
        assert styled != paragraph, "the paragraph has no style to change"
        return xml.replace(paragraph, styled.replace(was, now, 1), 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("block", "was", "now", "restyle"),
    [
        (_LOOSE, _CONTINUED, "Twelve reports had no date and were left out.", False),
        (_BRAVO, _BRAVO, "Exposure was counted for thirty days from the first dose.", True),
    ],
    ids=["a list item's second paragraph", "given a style the build uses nowhere"],
)
def test_a_paragraph_still_takes_a_rewording_where_no_block_without_an_identifier_is_like_it(
    project: Path, tmp_path: Path, block: str, was: str, now: str, restyle: bool
) -> None:
    """Guards for the rule above, each reworded past most of its words, as main merges
    them. A list item's second paragraph is still the kind of block it was built as. And a
    paragraph the co-author gave a style the build uses nowhere is not on a block the build
    gave no identifier."""
    blocks = ("# Intro", _ALPHA, _ROMEO, block)

    def change(xml: str) -> str:
        assert was in xml
        return _restyled(was, now)(xml) if restyle else xml.replace(was, now, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before.replace(was, now, 1) != before, out


# ------------------------------------ what the record of printed text lets the import read


def _without_record(project: Path) -> None:
    """The document's record of what it printed, gone: imported on another machine, or with
    build/ cleaned."""
    shutil.rmtree(project / "build" / "records")


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("lead", "block", "edit"),
    [
        (
            "Baseline characteristics of the reports are shown below.",
            _TABLE + "\n\n: Baseline characteristics of the reports.",
            (
                "Baseline characteristics of the reports.",
                "Baseline characteristics of the reports by group.",
            ),
        ),
        (
            "Statistical analysis was done in R.",
            "## Statistical analysis",
            (">Statistical analysis<", ">Statistical analysis in R<"),
        ),
        (
            "Zulu ratio of the reports is defined below:",
            "Zulu ratio of the reports\n:   the zulu definition of the ratio",
            ("Zulu ratio of the reports<", "Zulu ratio of all the reports<"),
        ),
        (
            "Statistical analysis was done in R.",
            "## Statistical analysis",
            (">Statistical analysis<", ">Statistical analysis was done in R<"),
        ),
    ],
    ids=["caption", "heading", "definition term", "heading retitled as the sentence"],
)
def test_a_paragraph_deleted_before_a_block_reading_mostly_like_it_is_not_that_block(
    project: Path, tmp_path: Path, lead: str, block: str, edit: tuple[str, str]
) -> None:
    """Round 1 of #120's review, on main too. An identifier stays on a block that keeps most
    of its paragraph's words, which is how a paragraph restyled as a heading stays itself.
    A sentence announcing a table reads like the caption under it, one above a heading like
    the heading, a lead-in like the term it introduces: deleted in Word, the sentence left
    its identifier on that block, and edited, the block's new text was written over the
    sentence's source line. The record says that block stood under the sentence and did not
    come back as it was; what carries the identifier is that block edited or the sentence
    reworded, and nothing says which. Refused, and not reported deleted."""
    from test_roundtrip import _word_delete

    blocks = ("# Intro", _ALPHA, lead, block, _ROMEO, _BRAVO)

    def change(xml: str) -> str:
        xml = _word_delete(xml, _word_paragraph(xml, lead))
        assert edit[0] in xml
        return xml.replace(*edit, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "deleted in Word" not in out, "either was done: the import cannot say which"
    assert "is either this paragraph, reworded, or the text that stood under it" in out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_sentence_deleted_above_the_example_s_table_is_not_its_caption(
    project: Path, tmp_path: Path
) -> None:
    """The same on the example, through a build that passes its checks and an import without
    --force: a sentence announcing the contingency table, deleted in Word, and the caption
    under it changed. The caption was written over the sentence."""
    from contextlib import redirect_stdout
    from io import StringIO

    from test_roundtrip import _word_delete

    from manuscript_guard.cli import main

    path = main_md(project)
    lead = "The contingency table underlying the reporting odds ratio is given below."
    table, text = "{{table.two_by_two}}", path.read_text(encoding="utf-8")
    assert table in text
    path.write_text(text.replace(table, f"{lead}\n\n{table}", 1), encoding="utf-8")
    assert main(["build", str(project), "--offline"]) == 0
    caption = "Contingency table underlying the reporting odds ratio."
    edited = "The contingency table underlying the reporting odds ratio estimate."

    def change(xml: str) -> str:
        xml = _word_delete(xml, _word_paragraph(xml, lead))
        assert caption in xml
        return xml.replace(caption, edited, 1)

    returned = _sent_back(project, tmp_path, change)
    before = path.read_text(encoding="utf-8")
    printed = StringIO()
    with redirect_stdout(printed):
        main(["import", str(returned), str(project), "--apply"])
    assert path.read_text(encoding="utf-8") == before, printed.getvalue()


_FURTHER = "Papa continuation paragraph reports that twelve reports were excluded."
_OWN_KIND = {
    "display maths": (
        _LEAD,
        "The ratio was computed as $$x = y$$ where both are counts of reports.",
        ("The ratio was computed as", "The ratio was calculated as"),
        ("The ratio was computed as", "Each count is then divided by the other, which gives"),
    ),
    "line block": (
        _LEAD,
        "| zulu line block one\n| zulu line block two",
        ("zulu line block one", "zulu line block uno"),
        ("zulu line block one", "an address the co-author typed over the old"),
    ),
    "div without a style": (
        _LEAD,
        "::: {.plain}\nzulu plain div paragraph here.\n:::",
        ("zulu plain div paragraph", "zulu plain div words"),
        ("zulu plain div paragraph here.", "A note the co-author wrote here in its place."),
    ),
    "line block in a list item": (
        "Papa continuation",
        f"- zulu item one\n\n  {_FURTHER}\n\n  | zulu line block one\n  | zulu line block two",
        ("zulu line block one", "zulu line block uno"),
        ("zulu line block one", "an address the co-author typed over the old"),
    ),
}


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("edited", ["lightly", "past most of its words"])
@pytest.mark.parametrize("shape", list(_OWN_KIND))
def test_a_paragraph_deleted_before_a_block_of_its_own_kind_is_not_that_block(
    project: Path, tmp_path: Path, shape: str, edited: str
) -> None:
    """Round 1 of #120's review, on main too. Some blocks the build gives no identifier are
    of the kind a paragraph is: the body text either side of a displayed equation, a line
    block, a div with no style of its own; and, under a list item's further paragraph, a line
    block in the same item. The paragraph before one deleted in Word, its identifier went
    onto a block its kind cannot tell from it, and edited, that block was written over the
    paragraph. The record says the block stood under the paragraph and is gone as it was.
    Edited lightly, it reads like that block and not like the paragraph, which was deleted.
    Reworded past most of its words, it reads like neither, and is refused."""
    from test_roundtrip import _word_delete

    lead, block, light, heavy = _OWN_KIND[shape]
    blocks = ("# Intro", _ALPHA, block, _ROMEO, _BRAVO)
    if lead == _LEAD:
        blocks = ("# Intro", _ALPHA, _LEAD, block, _ROMEO, _BRAVO)
    edit = light if edited == "lightly" else heavy

    def change(xml: str) -> str:
        xml = _word_delete(xml, _word_paragraph(xml, lead))
        assert edit[0] in xml
        return xml.replace(*edit, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert ("deleted in Word" in out) == (edited == "lightly"), out


_CALLOUT = "Table 1 shows the baseline characteristics of the reports included in the analysis."
_CAPTION = "Baseline characteristics of the reports included in the analysis."


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "caption", ["edited in Word", "deleted in Word", "changed in the .md since the build"]
)
def test_a_sentence_reworded_far_from_the_caption_it_reads_like_still_merges(
    project: Path, tmp_path: Path, caption: str
) -> None:
    """Round 2 of #120's review: a guard, as main merges it. A sentence pointing at a table
    in the words of its caption, the table at the end of the paper. Asked whether it read
    like any text without an identifier that was gone, the sentence, reworded, lost its
    identifier whenever the caption was touched, or changed in the `.md`. Only what stood
    under a paragraph can carry its identifier, and the caption did not."""
    now = _CALLOUT.replace("shows", "gives")
    blocks = ("# Results", _ALPHA, _CALLOUT, _ROMEO, "# Tables", f"{_TABLE}\n\n: {_CAPTION}")
    later = blocks
    if caption == "changed in the .md since the build":
        later = (*blocks[:-1], f"{_TABLE}\n\n: {_CAPTION.replace('of the', 'of all the')}")

    def change(xml: str) -> str:
        assert _CALLOUT in xml
        xml = xml.replace(_CALLOUT, now, 1)
        if caption == "edited in Word":
            xml = xml.replace(_CAPTION, _CAPTION.replace("the analysis", "the main analysis"), 1)
        elif caption == "deleted in Word":
            found = next(
                p for p in re.findall(r"<w:p\b.*?</w:p>", xml, re.DOTALL) if _CAPTION in p
            )
            xml = xml.replace(found, "", 1)
        return xml

    after, before, out = _forced_import(project, tmp_path, blocks, later, change)
    assert after == before.replace(_CALLOUT, now, 1) != before, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_callout_reworded_on_the_example_merges_with_its_caption_edited_too(
    project: Path, tmp_path: Path
) -> None:
    """The same on the example, through a checked build and an import without --force."""
    from contextlib import redirect_stdout
    from io import StringIO

    from manuscript_guard.cli import main

    path = main_md(project)
    lead = "Table 3 shows the contingency table underlying the reporting odds ratio."
    anchor, text = "{{table.baseline}}\n\n", path.read_text(encoding="utf-8")
    assert anchor in text
    path.write_text(text.replace(anchor, f"{anchor}{lead}\n\n", 1), encoding="utf-8")
    assert main(["build", str(project), "--offline"]) == 0
    caption = "Contingency table underlying the reporting odds ratio."
    now = lead.replace("shows", "gives")

    def change(xml: str) -> str:
        assert lead in xml
        assert caption in xml
        return xml.replace(lead, now, 1).replace(caption, caption[:-1] + " for example-drug.", 1)

    returned = _sent_back(project, tmp_path, change)
    before = path.read_text(encoding="utf-8")
    printed = StringIO()
    with redirect_stdout(printed):
        main(["import", str(returned), str(project), "--apply"])
    assert path.read_text(encoding="utf-8") == before.replace(lead, now, 1), printed.getvalue()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_conclusion_and_the_key_point_repeating_it_reworded_alike_still_merges(
    project: Path, tmp_path: Path
) -> None:
    """Round 2 of #120's review: a guard. A list of key points repeats the conclusion, and a
    word is changed in both."""
    point = "Reporting of hepatic injury was disproportionate for example-drug."
    conclusion = "Reporting of hepatic injury was disproportionate for example-drug in these data."
    blocks = (
        "# Key points",
        f"- {point}\n- Disproportionality is not incidence.",
        "# Abstract",
        _ALPHA,
        conclusion,
        "# Methods",
        _ROMEO,
        _BRAVO,
    )

    def change(xml: str) -> str:
        assert xml.count("hepatic injury was") == 2
        return xml.replace("hepatic injury was", "liver injury was")

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before.replace(conclusion, conclusion.replace("hepatic", "liver"), 1), out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("lead", "block", "under"),
    [
        (
            "Papa paragraph reports what was excluded:",
            "- reports whose onset date was missing or fell outside the study period\n"
            "- duplicate reports",
            "reports whose onset date was missing or fell outside the study period",
        ),
        ("Papa paragraph gives Table 1.", f"{_TABLE}\n\n: {_CAPTION}", _CAPTION),
    ],
    ids=["list item", "caption"],
)
def test_a_paragraph_joined_with_the_block_under_it_is_not_reported_deleted(
    project: Path, tmp_path: Path, lead: str, block: str, under: str
) -> None:
    """Round 2 of #120's review: a guard. Delete pressed at the end of a lead-in runs the
    block under it into the paragraph, which then holds that block whole and reads mostly
    like it. It holds the paragraph whole too, and is the join main reports."""
    blocks = ("# Intro", _ALPHA, lead, block, _ROMEO, _BRAVO)

    after, before, out = _forced_import(
        project, tmp_path, blocks, blocks, _run_into_papa(under, below=True)
    )
    assert after == before, out
    assert "deleted in Word" not in out, out
    assert "came back joined" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_rewording_merges_beside_a_deletion_above_a_block_the_md_changed_since(
    project: Path, tmp_path: Path
) -> None:
    """A guard, as main merges it, found by running random sessions under both trees. Papa
    is reworded in Word and Romeo, under it, deleted, which leaves Romeo's identifier on the
    div after it; the author changed that div in the `.md` since the build. The record
    takes the identifier off the div, which reads as it was sent. The div then has no
    identifier and does not read as the fresh build prints it, and counted as new text
    beside Papa, it had Papa's rewording refused as a split. It is not new: the document
    was sent with it."""
    from test_roundtrip import _word_delete

    div = "::: {.plain}\nzulu plain div paragraph here.\n:::"
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, div, _BRAVO)
    now = tuple(block.replace("zulu plain div", "zulu ordinary div") for block in blocks)
    old, new = "twelve reports were excluded", "twelve of the reports were excluded"

    def change(xml: str) -> str:
        return _word_delete(xml, _word_paragraph(xml, "Romeo paragraph")).replace(old, new, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert after == before.replace(old, new, 1), out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("record", ["beside the build", "gone"])
def test_a_sentence_typed_after_the_emptied_line_is_joined_up_is_not_the_cut_paragraph(
    project: Path, tmp_path: Path, record: str
) -> None:
    """Round 2 of #119's review. Papa is reworded in the `.md`. In Word its text is cut
    without its paragraph mark, Backspace joins the emptied line onto the end of Alpha, a
    sentence is typed there and the text pasted onto the end of Bravo. Word puts the
    sentence after Papa's bookmark, so the identifier holds it, and what Papa had said was
    not known: Papa counted as come back, reworded, and Bravo merged its old sentence. The
    record says what Papa printed, and the sentence is not that. Without the record this is
    the gap it was."""
    from test_roundtrip import _parts

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(_reworded(b) if b == _PAPA else b for b in blocks)
    space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
    typed = "A sentence the co-author added here later."
    typed = f'<w:r><w:t xml:space="preserve"> {typed}</w:t></w:r>'

    def change(xml: str) -> str:
        if record == "gone":
            _without_record(project)
        papa = _word_paragraph(xml, "Papa paragraph")
        runs, (_props, mark, _runs) = _paragraph_runs(papa), _parts(papa)
        xml = xml.replace(papa, "", 1)
        alpha = _word_paragraph(xml, "Alpha paragraph")
        xml = xml.replace(alpha, alpha[: -len("</w:p>")] + mark + typed + "</w:p>", 1)
        bravo = _word_paragraph(xml, "Bravo paragraph")
        return xml.replace(bravo, bravo[: -len("</w:p>")] + space + runs + "</w:p>", 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert (after == before) == (record == "beside the build"), out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("record", ["beside the build", "gone"])
def test_a_sentence_typed_where_a_paragraph_the_author_changed_was_cut_is_not_that_paragraph(
    project: Path, tmp_path: Path, record: str
) -> None:
    """The gap #119 left open and named. Papa is reworded in the `.md`, so what it said was
    not known. Its text is cut in Word, a sentence typed on its line, and the text pasted
    onto the end of Romeo: the identifier alone on text that read as nothing sent counted as
    Papa, reworded, and Romeo merged Papa's old sentence. The record says what Papa
    printed."""
    from test_roundtrip import _parts

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(_reworded(b) if b == _PAPA else b for b in blocks)

    def change(xml: str) -> str:
        if record == "gone":
            _without_record(project)
        cut = _word_paragraph(xml, "Papa paragraph")
        runs, (props, mark, _runs) = _paragraph_runs(cut), _parts(cut)
        typed = "A sentence the co-author wrote in its place."
        typed = f'<w:r><w:t xml:space="preserve">{typed}</w:t></w:r>'
        xml = xml.replace(cut, f"<w:p>{props}{mark}{typed}</w:p>", 1)
        romeo = _word_paragraph(xml, "Romeo paragraph")
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(romeo, romeo[: -len("</w:p>")] + space + runs + "</w:p>", 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert (after == before) == (record == "beside the build"), out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("author", ["reworded", "dropped"])
@pytest.mark.parametrize("record", ["beside the build", "gone"])
def test_a_rewording_that_gained_five_words_merges_beside_a_paragraph_both_changed(
    project: Path, tmp_path: Path, author: str, record: str
) -> None:
    """Round 2 of #116's review: five of twenty ordinary sessions. The co-author deletes a
    paragraph the author had changed or dropped, and rewords another so that it gains six
    words in a row. What the deleted one had said was not known, so the interim rule held
    the rewording back as a possible paste of it. The record says what it printed, the
    rewording holds none of it, and it merges, as on main before that rule. Without the
    record the rule stands."""
    old = "Papa paragraph reports that twelve reports were excluded for missing dates."
    new = "Papa paragraph reports that missing dates meant twelve reports had to be left out."
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = _elsewhere(blocks) if author == "reworded" else blocks[:-1]

    def change(xml: str) -> str:
        if record == "gone":
            _without_record(project)
        return xml.replace(_word_paragraph(xml, "Bravo paragraph"), "", 1).replace(old, new, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    merged = before.replace(old, new, 1)
    assert after == (merged if record == "beside the build" else before), out
    assert ("records/" in out) == (record == "gone"), out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_rerun_value_is_refused_for_its_own_reason(project: Path, tmp_path: Path) -> None:
    """Round 2 of #116's review. With the analysis re-run, a paragraph printing the value
    came back printing 4000 where the fresh build prints 4100. Counted from the fresh build,
    it had gained "4000", a word with a digit, and with a paragraph whose words were not
    known deleted in the same round it was refused as a possible paste of that paragraph,
    which sent the author looking for one. Counted from what it printed, it gained nothing,
    and is refused for its value, as main refused it."""
    papa = "Papa paragraph reports that {{results.cohort.n_reports}} reports were screened."
    blocks = ("# Intro", _ALPHA, papa, _ROMEO, _BRAVO)

    def change(xml: str) -> str:
        bravo = _word_paragraph(xml, "Bravo paragraph")
        return xml.replace(bravo, "", 1).replace("talks about", "speaks about", 1)

    after, before, out = _forced_import(
        project, tmp_path, blocks, blocks[:-1], change, reports=4100
    )
    assert after == before.replace("talks about", "speaks about", 1), out
    assert "comes from results.cohort.n_reports" in out, out


_WORD_BLOCK = re.compile(r"<w:p\b.*?</w:p>", re.DOTALL)


def _joined_up(paragraph: str, above: str, retyped: str, *, typed: str = "", whole: bool = False):
    """Word 16, Track Changes off: the paragraph's text deleted, Backspace on the emptied
    line, and the block above it edited. Its identifier is then at the end of that block.

    As Word leaves each, made there over COM. Text typed at the join goes after the
    bookmark, as does text typed over a selection that ends at it: `typed`, so that
    "Funding", three Backspaces and "ers" is "Fund", the bookmark, "ers". The block selected
    whole and typed over, the bookmark is at its start, in front of all of it: `whole`."""
    from test_roundtrip import _parts

    def change(xml: str) -> str:
        cut = _word_paragraph(xml, paragraph)
        _props, mark, _runs = _parts(cut)
        xml = xml.replace(cut, "", 1)
        block = next(p for p in _WORD_BLOCK.findall(xml) if "mg-p-" not in p and above in p)
        after = f'<w:r><w:t xml:space="preserve">{typed}</w:t></w:r>' if typed else ""
        if whole:
            opening = re.match(r"<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", block, re.DOTALL)
            joined = opening.group(0) + mark + f"<w:r><w:t>{retyped}</w:t></w:r></w:p>"
        else:
            joined = block.replace(above, retyped)[: -len("</w:p>")] + mark + after + "</w:p>"
        return xml.replace(block, joined, 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("paragraph", "above", "retyped"),
    [
        ("This work received no funding.", ">Funding<", ">Funders<"),
        ("None declared.", ">Competing interests<", ">Conflicts of interest<"),
    ],
)
def test_a_paragraph_cut_and_joined_up_to_the_heading_above_is_not_that_heading(
    project: Path, tmp_path: Path, paragraph: str, above: str, retyped: str
) -> None:
    """Round 1 of #121's review, a regression against main, made in Word on the example as
    shipped and imported without --force. A paragraph's text deleted and Backspace pressed
    on the emptied line, its identifier is at the end of the heading above. The record said
    what stood under the paragraph, nothing there was gone, and so the block was taken for
    the paragraph: the heading retitled, "Funders" was written over "This work received no
    funding." Word puts what is typed at a bookmark after it, so the text in front of an
    identifier is never its paragraph's: behind the block's text and holding none, the
    paragraph is gone."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    returned = _sent_back(project, tmp_path, _joined_up(paragraph, above, retyped))
    before = main_md(project).read_text(encoding="utf-8")
    main(["import", str(returned), str(project), "--apply"])
    assert main_md(project).read_text(encoding="utf-8") == before


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_paragraph_cut_and_joined_up_to_the_list_item_above_is_not_that_item(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #121's review, a regression against main. The same above a list: one word
    of the last item retyped, the item was written over the paragraph cut from under it."""
    blocks = ("# Intro", _ALPHA, "- zulu item one\n- zulu item two", _ROMEO, _BRAVO)
    change = _joined_up("Romeo paragraph", "zulu item two", "zulu item number 2")
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "deleted in Word" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_paragraph_cut_and_joined_up_to_the_definition_above_is_not_that_definition(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #121's review, a regression against main. The same under a definition
    list: the definition edited, it was written over the paragraph cut from under it."""
    definition = "Zulu ratio of the reports\n:   the zulu definition of the ratio"
    blocks = ("# Intro", _ALPHA, definition, _ROMEO, _BRAVO)
    change = _joined_up("Romeo paragraph", "the zulu definition of", "the zulu meaning of")
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "deleted in Word" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("above", "edit"),
    [
        ("## Zulu funding", (">Zulu funding<", ">Zulu fund<", "ers")),
        ("- zulu item one\n- zulu item two", ("zulu item two", "zulu item ", "2")),
        ("| zulu line block one\n| zulu line block two", ("block two", "block ", "2")),
    ],
    ids=["heading", "list item", "line block"],
)
def test_text_typed_where_a_cut_paragraph_was_joined_up_is_not_that_paragraph(
    project: Path, tmp_path: Path, above: str, edit: tuple[str, str, str]
) -> None:
    """The same edits as Word 16 leaves them when the end of the block is typed over: three
    Backspaces and "ers", or the last word selected and typed over. What is typed goes after
    the bookmark, so the paragraph's identifier holds "ers". That is not the paragraph
    reworded, since the text in front of it is another block's. Nor can it be told from the
    block above run into the paragraph and both edited, so the paragraph is refused and not
    reported deleted. Taken for the paragraph, "Zulu funders" was written over it."""
    blocks = ("# Intro", _ALPHA, above, _ROMEO, _BRAVO)
    was, head, typed = edit
    change = _joined_up("Romeo paragraph", was, head, typed=typed)
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "came back inside another block" in out, out
    assert "deleted in Word" not in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("above", "was", "now", "told"),
    [
        ("## Zulu funding", "Zulu funding", "Sponsors", "deleted in Word"),
        ("- zulu item one\n- zulu item two", "zulu item two", "a new item", "deleted in Word"),
        (
            "| zulu line block one\n| zulu line block two",
            "zulu line block one",
            "a line the co-author typed over the old one",
            "that stood above it",
        ),
        (
            "| zulu line block one\n| zulu line block two",
            "zulu line block one",
            "zulu line block uno and zulu line block two",
            "deleted in Word",
        ),
    ],
    ids=["heading", "list item", "line block", "line block, lightly"],
)
def test_a_block_typed_over_whole_after_a_join_up_is_not_the_cut_paragraph(
    project: Path, tmp_path: Path, above: str, was: str, now: str, told: str
) -> None:
    """Made in Word 16: the paragraph's text deleted, Backspace, then the block above
    selected whole and typed over. The bookmark is then at the start of that block, where a
    paragraph's own is. So a block that stood directly above the paragraph, gone as it was,
    is weighed as one under it is: a heading or list item typed over is that block, and the
    paragraph was deleted; a line block typed over reads like the paragraph rewritten with
    the line block deleted, and is refused. Taken for the paragraph, each was written over
    it."""
    blocks = ("# Intro", _ALPHA, above, _ROMEO, _BRAVO)
    change = _joined_up("Romeo paragraph", was, now, whole=True)
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert told in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("block", "was", "now"),
    [
        ("## Zulu funding", "Zulu funding", "Zulu sponsors and their role"),
        ("- zulu item one\n- zulu item two", "zulu item two", "a second thing altogether"),
    ],
    ids=["heading", "list item"],
)
def test_a_block_moved_onto_a_cut_paragraph_s_line_and_edited_is_not_that_paragraph(
    project: Path, tmp_path: Path, block: str, was: str, now: str
) -> None:
    """A guard, as main reads it. A paragraph's text deleted, and a heading from elsewhere
    cut with its paragraph mark and pasted onto the emptied line, where what is pasted goes
    after the identifier; then retitled. Nothing beside the paragraph is gone, and by "there
    is nothing else for it to be" the heading was the paragraph, restyled and rewritten, and
    was written over it. A block of another kind than the paragraph's, not reading like it,
    is weighed against text of that kind gone from anywhere."""
    from test_roundtrip import _parts

    blocks = ("# Intro", _ALPHA, _ROMEO, _BRAVO, block, _PAPA)

    def change(xml: str) -> str:
        moved = next(p for p in _WORD_BLOCK.findall(xml) if "mg-p-" not in p and was in p)
        cut = _word_paragraph(xml, "Romeo paragraph")
        _props, mark, _runs = _parts(cut)
        opening = re.match(r"<w:p\b[^>]*>\s*(?:<w:pPr>.*?</w:pPr>)?", moved, re.DOTALL)
        pasted = opening.group(0) + mark + f"<w:r><w:t>{now}</w:t></w:r></w:p>"
        return xml.replace(moved, "", 1).replace(cut, pasted, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "deleted in Word" in out, out


def _typed_in_front(paragraph: str, under: str, typed: str):
    """Word 16, Track Changes off: the paragraph deleted whole, which leaves its identifier
    at the start of the block under it, and a new block typed there, then Enter. What is
    typed goes after the bookmark, in that block's style; the block follows as it was."""
    from test_roundtrip import _word_delete

    def change(xml: str) -> str:
        xml = _word_delete(xml, _word_paragraph(xml, paragraph))
        carrying = next(p for p in _WORD_BLOCK.findall(xml) if under in p)
        as_sent = re.sub(
            r'<w:bookmarkStart [^>]*w:name="mg-p-[^>]*/><w:bookmarkEnd [^>]*/>', "", carrying
        )
        assert as_sent != carrying and under in as_sent
        return xml.replace(carrying, carrying.replace(under, typed, 1) + as_sent, 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_heading_typed_in_front_of_the_next_one_is_not_the_paragraph_deleted_above_it(
    project: Path, tmp_path: Path
) -> None:
    """Round 2 of #121's review, a regression against main, made in Word on the example as
    shipped and imported without --force. "Reporting follows the checklist..." deleted
    whole, then "Reporting" and Enter typed in front of "Results": the new heading carries
    the paragraph's identifier at its start, and nothing the document was sent with is gone.
    By "there is nothing else for it to be" it was the paragraph, and the source line became
    `Reporting`, "merged 1 reworded paragraph(s)". It is the same bytes as the paragraph
    given a heading's style and rewritten, so one reading has to give: a block of a kind the
    build gives no identifier, not reading like the paragraph, is not the paragraph, as
    main reads it."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    change = _typed_in_front("Reporting follows the checklist", ">Results<", ">Reporting<")
    returned = _sent_back(project, tmp_path, change)
    before = main_md(project).read_text(encoding="utf-8")
    main(["import", str(returned), str(project), "--apply"])
    assert main_md(project).read_text(encoding="utf-8") == before


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("under", "was", "typed"),
    [
        ("# Zulu results", ">Zulu results<", ">Zulu screening<"),
        ("- zulu item one\n- zulu item two", "zulu item one", "a new first item"),
        (
            "> zulu quotation from the protocol.",
            "zulu quotation from the protocol.",
            "a new quotation.",
        ),
    ],
    ids=["heading", "list item", "quotation"],
)
def test_a_block_typed_where_a_deleted_paragraph_s_identifier_slid_is_not_that_paragraph(
    project: Path, tmp_path: Path, under: str, was: str, typed: str
) -> None:
    """Round 2 of #121's review, a regression against main. The same in front of a list
    and a quotation: a new first item typed where the lead-in was deleted was written over
    the lead-in, a body paragraph above a list that kept its items."""
    blocks = ("# Intro", _ALPHA, _ROMEO, under, _BRAVO)
    change = _typed_in_front("Romeo paragraph", was, typed)
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "deleted in Word" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_retitled_heading_is_not_the_paragraph_deleted_above_it_where_its_title_is_typed_again(
    project: Path, tmp_path: Path
) -> None:
    """Round 2 of #121's review, a regression against main. The heading under a deleted
    paragraph retitled, and its old title typed as a new heading elsewhere. What is gone is
    counted over the whole document, the old title is there to count, and so nothing was
    gone: the retitled heading was written over the paragraph."""
    from test_roundtrip import _word_delete

    blocks = ("# Intro", _ALPHA, _ROMEO, "# Zulu results", _BRAVO)

    def change(xml: str) -> str:
        heading = next(p for p in _WORD_BLOCK.findall(xml) if ">Zulu results<" in p)
        xml = _word_delete(xml, _word_paragraph(xml, "Romeo paragraph"))
        xml = xml.replace(">Zulu results<", ">Zulu findings<", 1)
        bravo = _word_paragraph(xml, "Bravo paragraph")
        return xml.replace(bravo, bravo + heading, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out


def test_an_identifier_a_build_put_behind_text_is_not_read_as_joined_up() -> None:
    """Where a bookmark sits says how it came there only because a build puts it at the
    start of its block. The record says where it was, and one a build put behind text of
    its own block, should a build ever do so, is not read as a line joined up."""
    from collections import Counter
    from dataclasses import replace

    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import _off_as_sent

    place = (("mg-p-main-1", 7),)
    sent = Block(names=("mg-p-main-1",), text="Label: the paragraph as it was sent.", at=place)
    back = [replace(sent, text="Label: the paragraph as it came back.")]

    out, untold = _off_as_sent([sent], back, Counter())
    assert out == back and not untold
    out, untold = _off_as_sent([replace(sent, at=(("mg-p-main-1", 0),))], back, Counter())
    assert not out[0].names and "behind 'Label:'" in untold["mg-p-main-1"].why


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("heading", "edit"),
    [
        ("Zulu approval", (">Zulu approval<", ">Zulu consent<")),
        ("Papa paragraph", ("Papa paragraph reports that", ": it reports that")),
    ],
    ids=["retitled", "opening with the heading's words"],
)
def test_a_heading_run_into_its_paragraph_and_edited_is_not_merged_into_it(
    project: Path, tmp_path: Path, heading: str, edit: tuple[str, str]
) -> None:
    """Two Known gaps, as main merges them. A heading run into the paragraph under it is
    known as a join by its title turning up in the paragraph. Retitled in the same round,
    the title is gone; and where the paragraph opened with the heading's own words, cut
    from it after the join, the title appears as often as it did. Either way the block
    merged, heading text and all, and the heading stayed in the source. The paragraph's
    identifier is behind the heading's text, which is never the paragraph's own."""
    blocks = ("# Intro", _ALPHA, f"## {heading}", _PAPA, _BRAVO)

    def change(xml: str) -> str:
        xml = _run_into_papa(heading, below=False)(xml)
        assert edit[0] in xml
        return xml.replace(*edit, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "came back inside another block" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    ("above", "gone"),
    [
        ("## Zulu funding", "Zulu funding"),
        ("- zulu item one\n- zulu item two", "zulu item two"),
        ("| zulu line block one\n| zulu line block two", "zulu line block one"),
    ],
    ids=["heading", "list item", "line block"],
)
@pytest.mark.parametrize("reworded", ["lightly", "past most of its words"])
def test_a_rewording_merges_under_a_block_deleted_in_the_same_round(
    project: Path, tmp_path: Path, above: str, gone: str, reworded: str
) -> None:
    """Guards for the block above a paragraph, as main merges them. With that block now
    weighed where it is gone, a paragraph reworded under one deleted in the same round must
    still merge: by its kind under a heading or a list item, however far it was reworded,
    and by its words under a block of its own kind. Under one of those, rewritten past most
    of its words, it is the same bytes as that block typed over whole with the paragraph
    deleted, and is refused: the one case here that main merges and this does not. (A block
    edited rather than deleted is new text beside the paragraph, and main refuses the
    rewording as a split.)"""
    blocks = ("# Intro", _ALPHA, above, _ROMEO, _BRAVO)
    old = "explains how duplicates were removed before the analysis."
    new = (
        "explains how duplicate reports were removed before the analysis."
        if reworded == "lightly"
        else "says which records were dropped as copies, and when."
    )

    def change(xml: str) -> str:
        block = next(p for p in _WORD_BLOCK.findall(xml) if "mg-p-" not in p and gone in p)
        return xml.replace(block, "", 1).replace(old, new, 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    untold = "line block" in above and reworded != "lightly"
    assert after == (before if untold else before.replace(old, new, 1)), out
    assert ("either this paragraph, reworded" in out) == untold, out


def _without_its_equation(paragraph: str, edit: tuple[str, str]):
    """Word 16, Track Changes off: the paragraph and the displayed equation under it deleted
    in one selection, and the text after the equation edited. The paragraph's identifier is
    then in front of that text."""
    from test_roundtrip import _word_delete

    def change(xml: str) -> str:
        equation = next(p for p in _WORD_BLOCK.findall(xml) if "<m:oMathPara>" in p)
        xml = _word_delete(xml.replace(equation, "", 1), _word_paragraph(xml, paragraph))
        assert edit[0] in xml
        return xml.replace(*edit, 1)

    return change


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_paragraph_deleted_with_the_equation_under_it_is_not_the_heading_after(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #121's review, a regression against main. The text under a paragraph was
    read up to the next table, figure or equation, since an identifier left behind goes onto
    the next paragraph. It slides past an equation deleted with its paragraph, onto the
    heading after, and retitled, the heading was written over the paragraph."""
    blocks = ("# Intro", _ALPHA, _ROMEO, "$$x = y$$", "# Zulu results", _BRAVO)
    change = _without_its_equation("Romeo paragraph", (">Zulu results<", ">Zulu findings<"))
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert "deleted in Word" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("edited", ["lightly", "past most of its words"])
def test_a_paragraph_deleted_with_the_equation_under_it_is_not_the_text_after_the_equation(
    project: Path, tmp_path: Path, edited: str
) -> None:
    """Round 1 of #121's review, on main too, made in Word. A sentence and the equation
    under it deleted in one selection, the identifier is on the "where" line after the
    equation, which is body text as the sentence was. A comma typed into that line, it was
    written over the sentence, and the clause was in the source twice. That line stood under
    the paragraph past the equation and is gone as it was: edited lightly it is that line
    and the paragraph was deleted; retyped whole it cannot be told, and is refused."""
    tail = "where zulu and yankee count the reports in each group."
    blocks = ("# Intro", _ALPHA, _ROMEO, f"$$x = y$$\n{tail}", _BRAVO)
    now = (
        "where zulu and yankee count the reports, in each group."
        if edited == "lightly"
        else "Both counts are taken from the table of reports by group."
    )
    change = _without_its_equation("Romeo paragraph", (tail, now))
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out
    assert ("deleted in Word" in out) == (edited == "lightly"), out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "block",
    [
        "| zulu line block one\n| zulu line block two",
        "::: {.plain}\nzulu plain div paragraph here.\n:::",
    ],
    ids=["line block", "div without a style"],
)
def test_a_paragraph_cut_and_joined_up_to_a_block_of_its_own_kind_is_not_that_block(
    project: Path, tmp_path: Path, block: str
) -> None:
    """Round 1 of #121's review, on main too. A paragraph's text cut, its emptied line
    joined up to a line block or a plain div above it, and that block retyped: its new text
    was written over the paragraph. The block is body text as the paragraph was, so its kind
    says nothing; the identifier is at its end, where a paragraph's own never is."""
    blocks = ("# Intro", _ALPHA, block, _ROMEO, _BRAVO)
    words = "zulu line block two" if "line block" in block else "zulu plain div paragraph here."
    change = _joined_up("Romeo paragraph", words, "a line the co-author typed over the old one")
    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    assert after == before, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_rewordings_beside_a_paragraph_that_cannot_be_told_are_not_refused_as_split(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #121's review, as main merges them. A line block deleted and its lead-in
    rewritten cannot be told from the lead-in deleted and the block retyped, and is refused.
    Its identifier taken off, the block counted as new text, and a one-word rewording in the
    paragraph on either side was refused as "split in two in Word". The refusal is of the
    paragraph it concerns."""
    lead = "Papa paragraph lists the search terms one per line, as follows."
    lines = "| zulu line block one\n| zulu line block two"
    blocks = ("# Intro", _ALPHA, lead, lines, _ROMEO, _BRAVO)

    def change(xml: str) -> str:
        gone = next(p for p in _WORD_BLOCK.findall(xml) if "zulu line block one" in p)
        xml = xml.replace(gone, "", 1).replace(lead, "The search terms are in Table S1.", 1)
        xml = xml.replace("cohort of patients", "cohort of the patients", 1)
        return xml.replace("duplicates were removed", "duplicates were dropped", 1)

    after, before, out = _forced_import(project, tmp_path, blocks, blocks, change)
    expected = before.replace("cohort of patients", "cohort of the patients", 1)
    assert after == expected.replace("duplicates were removed", "duplicates were dropped", 1), out
    assert "either this paragraph, reworded" in out, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_paragraph_whose_text_is_known_is_looked_for_past_new_text_on_its_line(
    project: Path, tmp_path: Path
) -> None:
    """Round 1 of #119's review, on main too. With a paragraph added above since the build,
    Papa is not compared, but what it said is known: its source reads as it did. In Word 16
    its text is cut without its paragraph mark, a sentence typed on the emptied line, and the
    text pasted onto the end of Alpha. Papa's identifier alone on text that read as nothing
    sent counted as Papa come back, and Alpha merged Papa's sentence, twice in the source. A
    paragraph whose text is known came back only where that text is."""
    from test_roundtrip import _parts

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = ("# Intro", _ALPHA, "An added paragraph written by the author since.", *blocks[2:])

    def change(xml: str) -> str:
        cut = _word_paragraph(xml, "Papa paragraph")
        runs, (props, mark, _runs) = _paragraph_runs(cut), _parts(cut)
        typed = "A sentence the co-author wrote in its place."
        typed = f'<w:r><w:t xml:space="preserve">{typed}</w:t></w:r>'
        xml = xml.replace(cut, f"<w:p>{props}{mark}{typed}</w:p>", 1)
        alpha = _word_paragraph(xml, "Alpha paragraph")
        space = '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        return xml.replace(alpha, alpha[: -len("</w:p>")] + space + runs + "</w:p>", 1)

    after, before, out = _forced_import(project, tmp_path, blocks, now, change)
    assert after == before, out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize(
    "reworded",
    [("the cohort of", "the group of"), (_ALPHA, "Another sentence altogether, rewritten.")],
    ids=["a word", "all of it"],
)
@pytest.mark.parametrize("cut", [True, False], ids=["cut", "copied"])
def test_a_paragraph_the_source_changed_pasted_into_another_is_not_merged(
    project: Path, tmp_path: Path, reworded: tuple[str, str], cut: bool
) -> None:
    """A paragraph the author reworded since the build is not compared, so the paste check,
    which weighed only the paragraphs compared, did not see it pasted onto the end of
    another: that one merged holding the paragraph's old words, and the source had them
    twice. Cut, what the paragraph said at the build is not known when the author changed
    it; copied, it is what came back."""
    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(block.replace(*reworded) for block in blocks)
    after, before, _out = _forced_import(
        project, tmp_path, blocks, now, _pasted("Alpha paragraph", "Romeo paragraph", cut=cut)
    )
    assert after == before, "a paragraph's words went into the source twice"


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_move_past_a_paragraph_not_compared_is_not_applied(
    project: Path, tmp_path: Path
) -> None:
    """The author reworded Papa since the build, so it is not compared, and the co-author
    moved Bravo above it in Word. Moves are worked out among the paragraphs compared, where
    Bravo only passed Romeo, and it was written between Papa and Romeo, where nobody put
    it. DESIGN.md said such a move is not applied; it is now withheld and named."""

    def moved(xml: str) -> str:
        bravo = _word_paragraph(xml, "Bravo paragraph")
        papa = _word_paragraph(xml, "Papa paragraph")
        return xml.replace(bravo, "", 1).replace(papa, bravo + papa, 1)

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO)
    now = tuple(block.replace("twelve reports", "twelve records") for block in blocks)
    after, before, out = _forced_import(project, tmp_path, blocks, now, moved)
    assert after == before, "a move was written where nobody put it"
    assert "not applied" in out and "Bravo paragraph" in out


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_move_beside_a_paragraph_not_compared_that_does_not_pass_it_is_applied(
    project: Path, tmp_path: Path
) -> None:
    """Only a move past such a paragraph is withheld: two paragraphs swapped below it are
    moved, as on main."""
    delta = "Delta paragraph closes the section after Bravo."

    def swapped(xml: str) -> str:
        bravo = _word_paragraph(xml, "Bravo paragraph")
        delta_ = _word_paragraph(xml, "Delta paragraph")
        return xml.replace(bravo, "", 1).replace(delta_, delta_ + bravo, 1)

    blocks = ("# Intro", _ALPHA, _PAPA, _ROMEO, _BRAVO, delta)
    now = tuple(block.replace("twelve reports", "twelve records") for block in blocks)
    after, before, _out = _forced_import(project, tmp_path, blocks, now, swapped)
    assert after == before.replace(f"{_BRAVO}\n\n{delta}", f"{delta}\n\n{_BRAVO}", 1)


@pytest.mark.parametrize("left", [(), ("Wingdings character F04A",)], ids=["nothing", "symbol"])
def test_a_split_beside_a_moved_paragraph_left_empty_is_not_merged(
    tmp_path: Path, left: tuple[str, ...]
) -> None:
    """A paragraph split in Word leaves its second half without an identifier, and only the
    paragraphs beside the first half can vouch that nothing there is new. One moved in with
    Track Changes on, its moved text then deleted - left with nothing, or with a smiley that
    has no text - vouched for it, and import wrote the paragraph as its first half."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    y, x, z = "Yankee one is here. Yankee two is there.", "Xray text is here.", "Zulu closes it."
    path = tmp_path / "main.md"
    text = f"# Methods\n\n{y}\n\n{x}\n\n{z}\n"
    path.write_text(text, encoding="utf-8")
    pairs = zip("yxz", (y, x, z), strict=True)
    known = {name: (path, words, text.index(words)) for name, words in pairs}
    sent = [Block((), "Methods"), Block(("y",), y), Block(("x",), x), Block(("z",), z)]
    returned = [
        sent[0],
        Block(("y",), "Yankee one is here."),
        Block(("x",), "", arrived=True, unread=left),
        Block((), "Yankee two is there."),
        Block((), ""),
        sent[3],
    ]
    apply_plan(known, plan_import(known, sent, returned))
    assert path.read_text(encoding="utf-8") == text, "a split was merged as its first half"


@pytest.mark.parametrize("shape", ["spacer joined in", "cut in between", "maths cut in between"])
def test_a_split_that_nothing_in_the_markup_shows_is_not_merged(
    tmp_path: Path, shape: str
) -> None:
    """A paragraph split in Word whose second half no identifier sits beside: taken into the
    spacer line under it, whose identifier it then carries, or pushed past a paragraph cut
    and pasted between the halves without Track Changes, which keeps its identifier. Import
    merged the paragraph as its first half and only listed the second."""
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import apply_plan, plan_import

    y, z, o = "Yankee one is here. Yankee two is there.", "Zulu is moved.", "Oscar closes it."
    between = "$$x = y$$" if shape.startswith("maths") else "&nbsp;"
    path = tmp_path / "main.md"
    text = f"# Methods\n\n{y}\n\n{between}\n\n{z}\n\n{o}\n"
    path.write_text(text, encoding="utf-8")
    lines = [("y", y), ("z", z), ("o", o)] + ([("s", between)] if between == "&nbsp;" else [])
    known = {name: (path, words, text.index(words)) for name, words in lines}
    line = Block(kind="equation", key="x=y") if between != "&nbsp;" else Block(("s",), "")
    sent = [Block((), "Methods"), Block(("y",), y), line, Block(("z",), z), Block(("o",), o)]
    first, second = Block(("y",), "Yankee one is here."), "Yankee two is there."
    if shape == "spacer joined in":
        returned = [sent[0], first, Block(("s",), second), sent[3], sent[4]]
    else:
        landed = line if between != "&nbsp;" else Block((), "")
        oscar = Block(("o",), o) if between != "&nbsp;" else Block(("s", "o"), o)
        returned = [sent[0], first, landed, sent[3], Block((), second), oscar]
    apply_plan(known, plan_import(known, sent, returned))
    assert path.read_text(encoding="utf-8") == text, "a split was merged as its first half"


def _unmarked(node):
    """Pandoc's reading with every annotation mark, a styled span around a link to an
    `#mg-n` anchor, replaced by what it holds, and neighbouring words joined."""
    if isinstance(node, list):
        out: list = []
        for item in node:
            if (
                isinstance(item, dict)
                and item.get("t") == "Span"
                and any(key == "custom-style" for key, _ in item["c"][0][2])
                and len(item["c"][1]) == 1
                and item["c"][1][0].get("t") == "Link"
                and item["c"][1][0]["c"][2][0].startswith("#mg-n")
            ):
                out.extend(_unmarked(item["c"][1][0]["c"][1]))
            else:
                out.append(_unmarked(item))
        joined: list = []
        for item in out:
            if joined and isinstance(item, dict) and item.get("t") == "Str":
                last = joined[-1]
                if isinstance(last, dict) and last.get("t") == "Str":
                    joined[-1] = {"t": "Str", "c": last["c"] + item["c"]}
                    continue
            joined.append(item)
        return joined
    if isinstance(node, dict):
        return {key: _unmarked(value) for key, value in node.items()}
    return node


def _marked_texts(node) -> list[str]:
    """The text of every annotation mark in pandoc's reading."""
    found: list[str] = []
    if isinstance(node, list):
        for item in node:
            found += _marked_texts(item)
    elif isinstance(node, dict):
        if node.get("t") == "Link" and node["c"][2][0].startswith("#mg-n"):
            found.append(json.dumps(node["c"][1]))
        found += _marked_texts(node.get("c"))
    return found


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_the_annotated_copy_keeps_inline_markup_around_numbers(project: Path) -> None:
    """The annotator wrapped `HbA~1c` in a mark and left the closing `~` outside, so pandoc
    read no subscript, and wrote a link inside a code span, where it printed literally. The
    annotated copy must read as the manuscript does, marks aside, with each number marked
    where a mark can go, and a number in code listed in the appendix instead."""
    import shutil
    import subprocess

    from manuscript_guard.cli import main

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    added = (
        "\n# Change in HbA~1c~ from baseline\n\n"
        "The CO~2~ level was read over a 3 m^2^ area in 10^6^ cells, with the `x2` variable.\n"
    )
    source.write_text(text + added, encoding="utf-8")
    assert main(["build", str(project), "--offline", "--annotated", "--skip-checks"]) == 0
    annotated = (project / "build" / "manuscript.annotated.md").read_text(encoding="utf-8")

    def read(markdown: str):
        out = subprocess.run(
            [shutil.which("pandoc"), "-f", "markdown", "-t", "json"],
            input=markdown.encode("utf-8"),
            capture_output=True,
            check=True,
        )
        return json.loads(out.stdout)["blocks"]

    blocks = read(annotated)
    heading = next(
        b for b in blocks if b["t"] == "Header" and "Change" in json.dumps(b["c"][2])
    )
    paragraph = next(b for b in blocks if b["t"] == "Para" and '"CO"' in json.dumps(b["c"]))
    # The markup survives, marks aside: each reads as the same text without marks does.
    assert _unmarked(heading) == _unmarked(read(added)[0])
    assert _unmarked(paragraph) == _unmarked(read(added)[1])
    # The numbers are marked where they can be, and the one in code is not.
    marked = _marked_texts(heading) + _marked_texts(paragraph)
    assert any('"1c"' in m for m in marked), marked
    assert any('"3"' in m for m in marked), marked
    # The 2 of `CO~2~` is marked. The 2 of `m^2^` is an exponent on a unit, which is no
    # number, as the 2 of `m²` is none: it carries no mark and is a superscript still, the
    # paragraph reading as it did. A number in a superscript, the 6 of `10^6^`, is marked.
    assert sum('"2"' in m for m in marked) == 1, marked
    assert any('"6"' in m and "Superscript" in m for m in marked), marked
    assert {"t": "Code", "c": [["", [], []], "x2"]} in paragraph["c"]
    appendix = annotated[annotated.index("# Appendix") :]
    assert "x2" in appendix and "code" in appendix


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_a_mark_pandoc_reads_otherwise_is_taken_out() -> None:
    """The number finder reads `width="300` in an HTML tag as a number, and nothing in the
    annotator's own rule knows tags, so the mark went inside the tag. Pandoc reads the file
    with its marks and without, and each mark in a paragraph that reads differently is
    taken out and listed in the appendix with the reason. The next paragraph keeps its own."""
    import shutil

    from manuscript_guard.annotate import READ_OTHERWISE, annotate, appendix
    from manuscript_guard.classify import Classifier

    text = (
        '# Extra\n\nA figure <img src="f.png" width="300"> of 12 patients.\n\n'
        "Another 42 plain.\n"
    )
    annotated, marks = annotate(
        text, {}, Classifier.load([], []), counter=[0], pandoc=shutil.which("pandoc")
    )
    assert '<img src="f.png" width="300">' in annotated
    shown = {mark.shown: mark for mark in marks}
    assert shown["12"].unmarked == READ_OTHERWISE
    assert not shown["42"].unmarked
    assert "[[42](#" in annotated
    assert f"Not marked in the text: {READ_OTHERWISE}" in appendix(marks)


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    ("text", "marked", "unmarked"),
    [
        # Found by review of round 1: numbers main marked, and the first version did not.
        # A citation's locator: pandoc keeps the citation's source text, which citeproc
        # never prints, and it differed with the mark in.
        ("Of 120 reports, 14 were serious [@smith2021, p. 33].", {"120", "14"}, {}),
        # A currency sign is not an equation's: a mark on the digits alone left one dollar
        # sign facing another across the paragraph.
        ("The fee was US$5 and the refund US$3, and 7 more.", {"US$5", "US$3", "7"}, {}),
        ("Costs ranged from $10-$50 per dose.", {"$10-$50"}, {}),
        # Found by the fix-only round: an escaped dollar, the mark after its backslash,
        # which escaped the mark's bracket; and a dollar after the digits, which faced the
        # next one across the marks.
        ("The fee was \\$5 for 3 visits.", {"\\$5", "3"}, {}),
        ("It cost 5$ and then 10$, over 3 days.", {"5", "10", "3"}, {}),
        # A footnote marker after a bracket is not a link's target, and a citation is not a
        # link's text.
        (
            "The odds ratio was 2.1 [95% CI 1.2-3.4][^2] in 40 patients.\n\n[^2]: Adjusted.",
            {"2.1", "95%", "1.2-3.4", "40"},
            {},
        ),
        (
            "Of 120 reports, 14 were serious [@smith2021, p. 33][^1].\n\n[^1]: A note.",
            {"120", "14", "33"},
            {},
        ),
        ("As shown [@a2020, p. 3][@b2021, p. 5].", {"3", "5"}, {}),
        # Found by the extra round: an escaped range, split by its inner backslash; and a
        # bracket before a citation, or before a label nothing defines, which pandoc reads
        # as text. In prose, and in a table or a list, where the first version unmarked
        # the whole block.
        ("Costs ranged from \\$10-\\$50 per dose.", {"\\$10-\\$50"}, {}),
        ("Costs ranged from \\$1,000-\\$2,000 per dose.", {"\\$1,000-\\$2,000"}, {}),
        # An escaped dollar after the digits stays outside the mark, with its backslash.
        ("It cost 5\\$ and then 10\\$, over 3 days.", {"5", "10", "3"}, {}),
        # Found by the fix-only round of the extra one: any escaped punctuation in a range
        # is text, `\%` from LaTeX habit, and `\~`, without which pandoc reads a subscript.
        ("Between 5\\%-10\\% of 40 sites.", {"5\\%-10\\%", "40"}, {}),
        (
            "It was 12\\% (95\\% CI 10\\%-14\\%) in 40 sites.",
            {"12", "95", "10\\%-14\\%", "40"},
            {},
        ),
        ("About \\~5-\\~7 in 40 sites.", {"\\~5-\\~7", "40"}, {}),
        (
            "| Site | Share |\n|------|-------|\n| A | 5\\%-10\\% |\n| B | \\~5-\\~7 |",
            {"5\\%-10\\%", "\\~5-\\~7"},
            {},
        ),
        (
            "- Between 5\\%-10\\%.\n- About \\~5-\\~7 in 40 sites.",
            {"5\\%-10\\%", "\\~5-\\~7", "40"},
            {},
        ),
        # Found by the round after the budget: pandoc escapes any character that is not a
        # letter, a digit or a space, not ASCII punctuation alone.
        ("Between 5\\°-10\\° of 40 sites.", {"5\\°-10\\°", "40"}, {}),
        ("Doses of \\±5-\\±10 in 40 sites.", {"\\±5-\\±10", "40"}, {}),
        ("Values of \\≥5-\\≥10 in 40 sites.", {"\\≥5-\\≥10", "40"}, {}),
        ("From 5\\‰-10\\‰ and 5\\–10 in 40 sites.", {"5\\‰-10\\‰", "5\\–10", "40"}, {}),
        (
            "| Site | Range |\n|------|-------|\n| A | 5\\°-10\\° |\n| B | 2\\*3\\*4 |",
            {"5\\°-10\\°", "2\\*3\\*4"},
            {},
        ),
        ("It was 12\\° and 12\\% at 40 sites.", {"12", "40"}, {}),
        (
            "| Drug | Cost |\n|------|------|\n| A | \\$10-\\$50 |\n| B | \\$5 |",
            {"\\$10-\\$50", "\\$5"},
            {},
        ),
        ("- Drug A cost \\$10-\\$50.\n- Drug B cost \\$5 for 3 visits.", {"\\$10-\\$50", "3"}, {}),
        (
            "The odds ratio was 2.1 [95% CI 1.2-3.4][@smith2021] in 40 patients.",
            {"2.1", "95%", "1.2-3.4", "40"},
            {},
        ),
        ("The rate was [4.5 per 100][see @smith2021] in 12 sites.", {"4.5", "100", "12"}, {}),
        ("The rate was [4.5 per 100][-@smith2021] in 12 sites.", {"4.5", "100", "12"}, {}),
        # The finder reads `12][13` as one number, as on main, whose mark escapes the
        # brackets.
        ("Counts were [12][13] in all 40 sites.", {"12][13", "40"}, {}),
        # A mark straight after a `]` reads as a reference: that number goes unmarked, and
        # its paragraph keeps the rest.
        ("Fees [B]7 in 3 sites.", {"3"}, {"B]7": "IN_MARKUP"}),
        (
            "It was [95% CI 1.2-3.4]1.2-3.4[12] in 40 sites.",
            {"95%", "40"},
            {"1.2-3.4[12": "IN_MARKUP"},
        ),
        (
            "| Odds ratio | CI |\n|----|----|\n| 2.1 | [1.2-3.4][@smith2021] |",
            {"2.1", "1.2-3.4"},
            {},
        ),
        ("- 2.1 [95% CI 1.2-3.4][@smith2021]\n- 40 patients", {"95%", "1.2-3.4", "40"}, {}),
        # A reference link the file defines is a link: its number stays unmarked. (The
        # definition holds no digit: a number in a definition is marked, which is recorded
        # in Known gaps.)
        (
            "Of 120 reports, as shown in [Table 2][tbl].\n\n[tbl]: #results-table",
            {"120"},
            {"2": "IN_LINK"},
        ),
        # A dollar sign in inline code opens no equation.
        ("Age (`df$age`) was split into 3 groups and sex (`df$sex`) into 2.", {"3", "2"}, {}),
        # A link to an anchor: only the number in its text goes unmarked.
        (
            "Of 120 reports, 14 were serious, as shown in [Table 2](#tbl-2).",
            {"120", "14"},
            {"2": "IN_LINK"},
        ),
        # The follow-ups of #76. A backslash pandoc keeps, before a letter or a digit, is
        # text inside the mark as outside it.
        ("It was 1.2\\pm0.3 at 40 sites.", {"1.2\\pm0.3", "40"}, {}),
        ("Between 5\\²-10\\² of 40 sites.", {"5\\²-10\\²", "40"}, {}),
        ("It was 12\\² at 40 sites.", {"12\\²", "40"}, {}),
        ("Files in data\\2021\\05 for 40 sites.", {"data\\2021\\05", "40"}, {}),
        # Around a number read across several runs, a `@` is a citation's.
        ("It was 5$\\5@a in 40 sites.", {"40"}, {"5$\\5@a": "IN_MARKUP"}),
        # A mark straight after a TeX command is taken for its argument.
        ("Of 12 patients, \\a 5 were seen.", {"12"}, {"5": "IN_MARKUP"}),
        # An ordered list's numbers are the list's: marked, they broke it.
        ("1. First 12 patients\n2. Then 14 more", {"12", "14"}, {"1": "IN_LIST"}),
        # A heading's title is a label (a link pandoc reads without a second bracket is
        # tested apart, below).
        ("As in [the 3 steps][Results] for 40 sites.", {"40"}, {"3": "IN_LINK"}),
        # Definitions pandoc does not read: under a paragraph's line, or in a listing.
        ("As in [Table 2][t] for 40 sites.\n\nText\n[t]: #x", {"2", "40"}, {}),
        ("As in [Table 2][t] for 40 sites.\n\n```\n[t]: #x\n```", {"2", "40"}, {}),
    ],
)
def test_the_annotated_copy_marks_what_main_marked(
    text: str, marked: set[str], unmarked: dict[str, str]
) -> None:
    import shutil

    from manuscript_guard import annotate as module
    from manuscript_guard.classify import Classifier

    _annotated, marks = module.annotate(
        f"# Results\n\n{text}\n",
        {},
        Classifier.load([], []),
        counter=[0],
        pandoc=shutil.which("pandoc"),
    )
    shown = {mark.shown: mark.unmarked for mark in marks}
    assert marked <= {s for s, reason in shown.items() if not reason}, shown
    for number, reason in unmarked.items():
        assert shown.get(number) == getattr(module, reason), shown


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize(
    "text",
    [
        "As in [Table 2] for 40 sites.\n\n[table 2]: #t",
        "As in [Table 2][@smith2021] for 40 sites.\n\n[table 2]: #t",
    ],
)
def test_a_shortcut_link_and_its_definition_take_no_mark(text: str) -> None:
    """The follow-ups of #76: a bracket pandoc reads as a link with no second bracket, or
    falling back to its own text over a citation, is a link's text; and a number in a
    link's definition, marked, broke the definition, and every paragraph using it lost its
    marks."""
    import shutil

    from manuscript_guard import annotate as module
    from manuscript_guard.classify import Classifier

    _annotated, marks = module.annotate(
        f"# Results\n\n{text}\n",
        {},
        Classifier.load([], []),
        counter=[0],
        pandoc=shutil.which("pandoc"),
    )
    assert [(mark.shown, mark.unmarked) for mark in marks] == [
        ("2", module.IN_LINK),
        ("40", ""),
        ("2", module.IN_DEFINITION),
    ]


@pytest.mark.parametrize(
    ("text", "links"),
    [
        # Pandoc matches a label ignoring case and runs of white space, and an empty
        # bracket takes the text as the label.
        ("See [Table 2][].\n\n[table  2]: #t\n", ["[Table 2]"]),
        ("See [Table 2][T].\n\n[t]: #t\n", ["[Table 2]"]),
        ("See [Table 2](#t).\n", ["[Table 2]"]),
        # Nothing defines these, so pandoc reads text: a footnote's marker, a citation,
        # a label with no definition, and a footnote's definition, which is no link's.
        ("See [Table 2][^1].\n\n[^1]: A note.\n", []),
        ("See [Table 2][@smith2021].\n", []),
        ("See [Table 2][t].\n", []),
        ("See [Table 2][].\n\n[^table 2]: A note.\n", []),
        # The follow-ups of #76, each as pandoc 3.9 reads it. A bracket on its own is a link
        # when its text is defined, and falls back to that over a citation or a note's
        # marker, but not over a label nothing defines; not before a span's attributes.
        ("See [Table 2] here.\n\n[table 2]: #t\n", ["[Table 2]"]),
        ("See [Table 2][@smith2021].\n\n[table 2]: #t\n", ["[Table 2]"]),
        ("See [Table 2][^1].\n\n[table 2]: #t\n\n[^1]: A note.\n", ["[Table 2]"]),
        ("See [Table 2][t].\n\n[table 2]: #t\n", []),
        ("See [Table 2]{.smallcaps} here.\n\n[table 2]: #t\n", []),
        # A heading's title is a label, case aside; a line pandoc prints as text is none.
        ("# Methods\n\nSee [the 3 steps][Methods].\n", ["[the 3 steps]"]),
        ("# Methods\n\nSee [methods] here.\n", ["[methods]"]),
        ("Text.\n# Methods\n\nSee [the 3 steps][Methods].\n", []),
        # A definition under a paragraph's line, in a listing or in a comment is none; in a
        # quotation it is.
        ("Text\n[t]: #x\n\nSee [Table 2][t].\n", []),
        ("```\n[t]: #x\n```\n\nSee [Table 2][t].\n", []),
        ("<!--\n[t]: #x\n-->\n\nSee [Table 2][t].\n", []),
        ("> [t]: #x\n\nSee [Table 2][t].\n", ["[Table 2]"]),
        # Pandoc lower-cases a label; it does not fold `ß` into `ss`.
        ("See [x][Straße].\n\n[STRASSE]: #x\n", []),
    ],
)
def test_a_link_s_text_is_found_only_where_pandoc_reads_a_link(
    text: str, links: list[str]
) -> None:
    from manuscript_guard.text.inline import link_text_spans

    assert [text[start:end] for start, end in link_text_spans(text)] == links


# --------------------------------------------------------------------------------------
# A round read by several readers. The panel names who reads each remit, and G11 holds the
# round to it. Each way of losing a reading, or of passing one off as another, must fail a
# submission: a round where two of three models answered is not a round the panel read.
# --------------------------------------------------------------------------------------

_READERS = ("openai/model-a", "mistral/model-b")


def _round_two(root: Path) -> Path:
    return root / "review" / "round-2"


def _reading(root: Path, reviewer: str, reader: str) -> Path:
    from manuscript_guard.gates.review import reading_slug

    return _round_two(root) / f"{reviewer}.{reading_slug(reader)}.yaml"


def _edit(path: Path, mutate) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _review_failures(root: Path) -> set[str]:
    from manuscript_guard.gates import check_review

    return codes(check_review(load_project(root)[0], submission=True))


def _read_by_two_models(root: Path) -> None:
    """Round two of the example, with both reviewers read by two models as well."""
    from manuscript_guard.record import write_review

    def name_readers(document):
        for reviewer in document["reviewers"]:
            reviewer["readers"] = list(_READERS)

    _edit(root / "review" / "panel-2.yaml", name_readers)
    for reviewer in ("desk-editor", "clinical-reader"):
        for reader in _READERS:
            write_review(
                load_project(root)[0],
                reviewer,
                verdict="minor-revision",
                round_number=2,
                reading=reader,
            )


def _lose(root: Path) -> None:
    _reading(root, "desk-editor", _READERS[1]).unlink()


def _empty(root: Path) -> None:
    _reading(root, "desk-editor", _READERS[1]).write_text("", encoding="utf-8")


def _pass_one_reader_off_as_the_other(root: Path) -> None:
    shutil.copy(
        _reading(root, "desk-editor", _READERS[0]), _reading(root, "desk-editor", _READERS[1])
    )


def _rename_the_reader_inside(root: Path) -> None:
    _reading(root, "desk-editor", _READERS[1]).unlink()
    _edit(_reading(root, "desk-editor", _READERS[0]), lambda d: d.update(reader=_READERS[1]))


def _pass_one_remit_off_as_the_other(root: Path) -> None:
    shutil.copy(
        _reading(root, "clinical-reader", _READERS[1]),
        _reading(root, "desk-editor", _READERS[1]),
    )


def _bring_a_reading_from_another_round(root: Path) -> None:
    _edit(_reading(root, "desk-editor", _READERS[1]), lambda d: d.update(round=1))


def _strip_the_reader(root: Path) -> None:
    _edit(_reading(root, "desk-editor", _READERS[1]), lambda d: d.pop("reader"))


def _file_it_by_hand_instead(root: Path) -> None:
    """The remit is read, by a record nobody named: not the reader the panel asked for."""
    _reading(root, "desk-editor", _READERS[1]).unlink()
    assert (_round_two(root) / "desk-editor.yaml").exists()


def _leave_a_major_finding_open(root: Path) -> None:
    _edit(
        _reading(root, "desk-editor", _READERS[1]),
        lambda d: d["findings"].append(
            {"id": "f1", "severity": "major", "finding": "The conclusion does not follow."}
        ),
    )


def _edit_the_manuscript_afterwards(root: Path) -> None:
    path = main_md(root)
    path.write_text(path.read_text(encoding="utf-8") + "\n\nAdded after.\n", encoding="utf-8")


def _answer_a_finding_in_words_yaml_cannot_read(root: Path) -> None:
    """The step the gate asks for, done with a slip: a resolution with a colon in it. The
    reading's other major finding was never answered, and must not stop binding because the
    file stopped parsing. Found by the review of #128."""
    path = _reading(root, "desk-editor", _READERS[1])
    text = path.read_text(encoding="utf-8").replace(
        "findings: []\n",
        "findings:\n"
        "- id: f1\n  severity: major\n  finding: The abstract claims a risk.\n"
        "  resolution: Fixed: it says reporting now.\n"
        "- id: f2\n  severity: major\n  finding: No denominator is given.\n",
    )
    assert "resolution: Fixed: it" in text
    path.write_text(text, encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(text)


def _leave_merge_markers_in_a_reading(root: Path) -> None:
    path = _reading(root, "desk-editor", _READERS[1])
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("verdict:", "<<<<<<< HEAD\nverdict: pass\n=======\nverdict:", 1)
        + ">>>>>>> theirs\n",
        encoding="utf-8",
    )


def _save_a_reading_as_utf16(root: Path) -> None:
    """What Windows PowerShell 5 writes for `>`, and what some editors offer. Found by the
    second review round of #128: taken for a note, with its findings."""
    path = _reading(root, "desk-editor", _READERS[1])
    path.write_bytes(path.read_text(encoding="utf-8").encode("utf-16"))


def _pass_another_remit_off_under_the_plain_name(root: Path) -> None:
    """The model read the other remit only. Its record, copied over the reviewer's own
    plain record, says the other reviewer inside. Found by the review of #128."""
    _reading(root, "desk-editor", _READERS[1]).unlink()
    shutil.copy(
        _reading(root, "clinical-reader", _READERS[1]), _round_two(root) / "desk-editor.yaml"
    )


def _pass_another_round_off_under_the_plain_name(root: Path) -> None:
    moved = _reading(root, "desk-editor", _READERS[1])
    _edit(moved, lambda d: d.update(round=1))
    moved.replace(_round_two(root) / "desk-editor.yaml")


_LOST_READINGS = {
    "a reading is deleted": (_lose, "reading-missing"),
    "a resolution is typed in words YAML cannot read": (
        _answer_a_finding_in_words_yaml_cannot_read,
        "reading-unreadable",
    ),
    "merge markers are left in a reading": (
        _leave_merge_markers_in_a_reading,
        "reading-unreadable",
    ),
    "another remit's reading is copied under the plain name": (
        _pass_another_remit_off_under_the_plain_name,
        "reading-missing",
    ),
    "another round's reading is moved to the plain name": (
        _pass_another_round_off_under_the_plain_name,
        "reading-missing",
    ),
    "a reading is saved again as UTF-16": (_save_a_reading_as_utf16, "reading-unreadable"),
    "a reading is emptied": (_empty, "schema-violation"),
    "one reader's record is copied as the other's": (
        _pass_one_reader_off_as_the_other,
        "reading-misfiled",
    ),
    "the reader named inside is changed": (_rename_the_reader_inside, "reading-misfiled"),
    "another remit's reading is copied in": (
        _pass_one_remit_off_as_the_other,
        "reading-misfiled",
    ),
    "a reading says it is of another round": (
        _bring_a_reading_from_another_round,
        "reading-misfiled",
    ),
    "the reader is taken out of a reading": (_strip_the_reader, "reading-misfiled"),
    "the remit is answered by hand instead": (_file_it_by_hand_instead, "reading-missing"),
    "a model's major finding is left open": (_leave_a_major_finding_open, "open-major-finding"),
    "the manuscript is edited after the readings": (
        _edit_the_manuscript_afterwards,
        "review-stale",
    ),
}


def test_a_round_read_by_two_models_passes_a_submission(project: Path) -> None:
    """The baseline. Everything in the next test is meaningless if this fails."""
    _read_by_two_models(project)
    assert not _review_failures(project)
    assert len(list(_round_two(project).glob("*.yaml"))) == 6


@pytest.mark.parametrize("name", sorted(_LOST_READINGS))
def test_every_way_of_losing_a_reading_fails_a_submission(project: Path, name: str) -> None:
    corrupt, expected = _LOST_READINGS[name]
    _read_by_two_models(project)
    corrupt(project)
    assert expected in _review_failures(project)


def test_the_example_s_own_rounds_are_read_as_they_were(project: Path) -> None:
    """One record a reviewer, no readers named: nothing about them changed. Rounds three to
    eight read revisions with the earlier rounds in front of them, so the eighth supersedes
    the seven before it and each says it was not blinded."""
    from manuscript_guard.gates import check_review

    report = check_review(load_project(project)[0], submission=True)
    assert report.ok, report.render(project)
    said = sorted((f.code, f.path.parent.name) for f in report.findings)
    superseded = [("review-superseded", f"round-{n}")
                  for n, many in ((1, 3), (2, 2), (3, 2), (4, 2), (5, 2), (6, 2), (7, 1))
                  for _ in range(many)]  # fmt: skip
    assert said == superseded + [("round-not-blinded", "review")] * 6, report.render(project)
    assert report.counts["review_rounds_complete"] == 8


def test_a_reading_that_stops_parsing_fails_with_no_readers_named_either(project: Path) -> None:
    """The panel names nobody, so nothing is `reading-missing`. The reading carried an
    unanswered major finding; a warning that it "names no reader" let the submission pass."""
    from manuscript_guard.record import write_review

    path = write_review(
        load_project(project)[0],
        "desk-editor",
        verdict="major-revision",
        round_number=2,
        reading=_READERS[0],
    ).path
    text = path.read_text(encoding="utf-8").replace(
        "findings: []\n",
        "findings:\n"
        "- id: f1\n  severity: major\n  finding: The abstract claims a risk.\n"
        "- id: f2\n  severity: major\n  finding: No denominator is given.\n",
    )
    path.write_text(text, encoding="utf-8")
    assert "open-major-finding" in _review_failures(project)

    path.write_text(
        text.replace(
            "  finding: The abstract claims a risk.\n",
            "  finding: The abstract claims a risk.\n"
            "  resolution: Fixed: it says reporting now.\n",
        ),
        encoding="utf-8",
    )
    assert "reading-unreadable" in _review_failures(project)


# --------------------------------------------------------------------------------------
# A filed reading cannot be softened. A major finding binds until it is answered, and before
# the seal it stopped binding when it was made minor, reworded or deleted, with nothing in
# `check` to say so. Readings are filed here as `review --run` files them, through a
# transport that answers for the providers.
# --------------------------------------------------------------------------------------

_A_MODEL_SAID = [
    {"severity": "major", "where": "Methods", "finding": "No case definition is given."},
    {"severity": "minor", "where": "Abstract", "finding": "Say the data are synthetic."},
]


def _filed_by_a_model(root: Path, monkeypatch) -> Path:
    """One reviewer's reading, filed by `review --run` from a reply with a major finding."""
    from test_review_run import Providers, answer, configure, reply_text

    from manuscript_guard.cli import main
    from manuscript_guard.panel import client

    transport = Providers()
    transport.default = lambda request: answer(reply_text("major-revision", _A_MODEL_SAID))
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-0123456789SECRETA")
    shutil.rmtree(root / "review")
    configure(root, "openai/model-a")
    assert main(["review", str(root), "--run", "--yes"]) == 0
    return sorted((root / "review" / "round-1").glob("*.*.yaml"))[0]


_SOFTENINGS = {
    "a major made minor": lambda d: d["findings"][0].update(severity="minor"),
    "a major made a comment": lambda d: d["findings"][0].update(severity="comment"),
    "a finding deleted": lambda d: d["findings"].pop(0),
    "a finding reworded": lambda d: d["findings"][0].update(finding="Case definition: fine."),
    "a finding moved": lambda d: d["findings"][0].update(where="Discussion"),
    "the verdict softened": lambda d: d.update(verdict="pass"),
    "the summary rewritten": lambda d: d.update(summary="A careful paper."),
    "a rejection test turned": lambda d: d["rejection_tests"][0].update(holds=True),
}


@pytest.mark.parametrize("name", sorted(_SOFTENINGS))
def test_a_model_s_reading_changed_after_it_was_filed_fails(
    project: Path, monkeypatch, name: str
) -> None:
    from manuscript_guard.gates import check_review

    path = _filed_by_a_model(project, monkeypatch)
    _edit(path, _SOFTENINGS[name])
    report = check_review(load_project(project)[0], submission=True)
    altered = [f for f in report.failures if f.code == "reading-altered"]
    assert [f.path for f in altered] == [path], report.render(project)
    # Before submission it is said, as G11 says everything until then.
    report = check_review(load_project(project)[0])
    assert any(f.code == "reading-altered" for f in report.warnings)


_ANSWERS_TO_A_MODEL = {
    "a resolution": lambda d: d["findings"][0].update(
        resolution="A case definition is now given.", resolved_on="2026-10-14"
    ),
    "an override": lambda d: d["findings"][0].update(overridden="Out of scope here."),
}


@pytest.mark.parametrize("name", sorted(_ANSWERS_TO_A_MODEL))
def test_answering_a_model_s_finding_is_not_an_edit_of_the_reading(
    project: Path, monkeypatch, name: str
) -> None:
    path = _filed_by_a_model(project, monkeypatch)
    assert "open-major-finding" in _review_failures(project)
    # The model read every remit, and each reading has the major finding to answer.
    for reading in sorted(path.parent.glob("*.*.yaml")):
        _edit(reading, _ANSWERS_TO_A_MODEL[name])
    failures = _review_failures(project)
    assert "reading-altered" not in failures
    assert "open-major-finding" not in failures


def test_a_model_s_reading_with_its_seal_taken_out_is_said(project: Path, monkeypatch) -> None:
    """The seal deleted and the major made minor: no major is left to say the reading is
    unsealed, so a reading `review --run` filed is said whatever it holds."""
    from manuscript_guard.gates import check_review

    path = _filed_by_a_model(project, monkeypatch)

    def unseal_and_soften(document):
        document.pop("reading_sha256")
        document["findings"][0]["severity"] = "minor"

    _edit(path, unseal_and_soften)
    report = check_review(load_project(project)[0], submission=True)
    assert [f.path for f in report.warnings if f.code == "reading-unsealed"] == [path]


def _read_by_models(
    root: Path, monkeypatch, *models: str, verdict: str = "major-revision", findings=None,
    remit: str | None = None,
) -> list[Path]:  # fmt: skip
    """A round read by `models` through `review --run`, each answering `verdict` with
    `findings`, of a panel whose one reviewer has `remit` where it is given."""
    from test_review_run import Providers, answer, configure, reply_text

    from manuscript_guard.cli import main
    from manuscript_guard.panel import client

    transport = Providers()
    said = _A_MODEL_SAID if findings is None else findings
    transport.default = lambda request: answer(reply_text(verdict, said))
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-0123456789SECRETA")
    monkeypatch.setenv("MISTRAL_API_KEY", "sk-test-mistral-0123456789SECRETB")
    shutil.rmtree(root / "review")
    if remit is not None:
        (root / "review").mkdir()
        panel = {"schema": "manuscript-guard/panel/1", "round": 1, "opened_on": "2026-10-15",
                 "rationale": "One reader, for the test.",
                 "reviewers": [{"id": "reader", "role": "Reader", "remit": remit,
                                "why": "The test needs one."}]}  # fmt: skip
        (root / "review" / "panel-1.yaml").write_text(yaml.safe_dump(panel), encoding="utf-8")
    configure(root, *models)
    assert main(["review", str(root), "--run", "--yes"]) == 0
    return sorted((root / "review" / "round-1").glob("*.*.yaml"))


def _review_warnings(root: Path) -> list[str]:
    from manuscript_guard.gates import check_review

    return [f.code for f in check_review(load_project(root)[0]).warnings]


def test_a_round_every_reading_of_which_came_from_one_provider_is_said(
    project: Path, monkeypatch
) -> None:
    """The models of one provider share their blind spots. A round read by one provider's
    model is said, at every stage; one read by two providers, or by people, is not."""
    from manuscript_guard.gates import check_review

    assert "round-one-provider" not in _review_warnings(project)  # the example's people
    _read_by_models(project, monkeypatch, "openai/model-a")
    assert _review_warnings(project).count("round-one-provider") == 1
    report = check_review(load_project(project)[0], submission=True)
    assert "round-one-provider" in [f.code for f in report.warnings]
    _read_by_models(project, monkeypatch, "openai/model-a", "mistral/model-b")
    assert "round-one-provider" not in _review_warnings(project)


def test_a_model_that_passed_a_remit_covering_the_figures_is_said(
    project: Path, monkeypatch
) -> None:
    """Figures are not sent to a model, so a model's pass of a remit that covers them passed
    what it never saw. Another verdict, and another remit, are not said."""
    figures = "Whether the figures show what the text says, and are labelled."
    _read_by_models(project, monkeypatch, "openai/model-a", verdict="pass", findings=[],
                    remit=figures)  # fmt: skip
    assert "figures-not-seen" in _review_warnings(project)
    _read_by_models(project, monkeypatch, "openai/model-a", verdict="minor-revision",
                    remit=figures)  # fmt: skip
    assert "figures-not-seen" not in _review_warnings(project)
    _read_by_models(project, monkeypatch, "openai/model-a", verdict="pass", findings=[],
                    remit="Whether the estimator is stated fully.")  # fmt: skip
    assert "figures-not-seen" not in _review_warnings(project)


def test_what_a_finding_asks_is_filed_said_and_sealed(project: Path, monkeypatch) -> None:
    """A finding may say it asks for a computation, which is a new result to emit and a new
    reconciliation of the Methods with the code. It is filed with the finding, named in the
    open finding, and sealed: made a disclosure after filing, the reading is altered. An ask
    the schema does not know is refused with the reply."""
    from manuscript_guard.gates import check_review

    asked = [{"severity": "major", "ask": "computation", "where": "Results",
              "finding": "Give the estimate adjusted for age."}]  # fmt: skip
    path = _read_by_models(project, monkeypatch, "openai/model-a", findings=asked)[0]
    filed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert filed["findings"][0]["ask"] == "computation"
    report = check_review(load_project(project)[0], submission=True)
    opened = [f.message for f in report.failures if f.code == "open-major-finding"]
    assert opened and all("(asks for a computation)" in message for message in opened)
    assert "reading-altered" not in [f.code for f in report.failures]
    _edit(path, lambda d: d["findings"][0].update(ask="disclosure"))
    assert "reading-altered" in _review_failures(project)

    from manuscript_guard.panel.reply import parse_reply

    # Round 1 of #276: the prompt shows `ask`, and a model that leaves it out writes null.
    left_out = json.loads(_reply_with([{"severity": "comment", "ask": None, "finding": "x"}]))
    found = parse_reply(json.dumps(left_out))["findings"]
    assert found == [{"severity": "comment", "finding": "x"}]
    with pytest.raises(Exception, match="ask"):
        parse_reply(json.dumps({**json.loads(_reply_with(asked)), "findings": [
            {**asked[0], "ask": "everything"}]}))  # fmt: skip


def _reply_with(findings: list) -> str:
    from test_review_run import reply_text

    return reply_text("major-revision", findings)


def test_the_example_s_hand_filed_readings_are_sealed_too(project: Path) -> None:
    """`review --seal` sealed them, and the same edits fail."""
    path = project / "review" / "round-1" / "biostatistician.yaml"
    assert "reading_sha256" in yaml.safe_load(path.read_text(encoding="utf-8"))
    _edit(path, lambda d: d["findings"][0].update(severity="minor"))
    assert "reading-altered" in _review_failures(project)


# --------------------------------------------------------------------------------------
# Two titles. Assembling compares the title in a manuscript file's own header with
# paper.yaml's and makes a warning where they differ. No command showed it: `build` and
# `submit` printed what assembling found only when that held a failure, and `check` did not
# ask. The document carries paper.yaml's title, so nothing wrong was printed. The author was
# never told that the header said otherwise.
#
# Shown, the warning was wrong wherever the header's title was not one plain line: it was
# read by line, not as YAML. The table further down is of headers and what each declares.
# --------------------------------------------------------------------------------------

OTHER_TITLE = "Another title"
TWO_TITLES = "main.md declares a different title from paper.yaml"


def retitled(root: Path) -> str:
    """The example with its title changed in paper.yaml and not in the manuscript's header,
    which is how the two come apart. Returns the title the header still declares."""
    paper = root / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    was = yaml.safe_load(text)["title"]
    line = 'title: "' + was + '"'
    assert line in text, "the fixture changed under this test"
    paper.write_text(text.replace(line, "title: '" + OTHER_TITLE + "'", 1), encoding="utf-8")
    assert line in main_md(root).read_text(encoding="utf-8")
    return was


def two_titles(report) -> list:
    return [f for f in report.findings if f.code == "two-titles"]


@pytest.mark.parametrize(
    "stage", ["design", "analysis", "drafting", "internal-review", "submission"]
)
def test_a_title_changed_in_paper_yaml_alone_is_a_warning_of_check(
    stage: str, project: Path
) -> None:
    """At every stage: the stage decides which failures are due, and a warning is not one."""
    from manuscript_guard.build.assemble import assemble
    from manuscript_guard.cli import _run_gates

    before = {f.code for f in _run_gates(project, stage=stage)[0].failures}
    was = retitled(project)

    report = _run_gates(project, stage=stage)[0]
    (found,) = two_titles(report)
    assert found.severity == "warn"
    assert (found.path, found.line) == (main_md(project), 2), "at the header's own title"
    assert found.context == was[:120]
    assert "paper.yaml is the one the document and the submission pack use" in found.hint
    assert {f.code for f in report.failures} == before, "a warning, and it fails nothing"
    # What `check` says is what the build's own assembling says.
    loaded = load_project(project)[0]
    namespace, results, _literature, _load = load_namespace(loaded)
    assert two_titles(assemble(loaded, namespace, results)[1]) == [found]


def test_one_title_is_not_a_finding_of_check(project: Path) -> None:
    """The baseline: the example as shipped, whose two titles agree; a header that holds
    another key and no title; and a file with no header. Neither of these declares one."""
    from manuscript_guard.cli import _run_gates

    assert two_titles(_run_gates(project)[0]) == []
    was = retitled(project)
    text = main_md(project).read_text(encoding="utf-8")
    line = 'title: "' + was + '"'
    main_md(project).write_text(text.replace(line, "lang: en-GB", 1), encoding="utf-8")
    assert main_md(project).read_text(encoding="utf-8").startswith("---\nlang: en-GB\n---\n")
    assert two_titles(_run_gates(project)[0]) == []
    main_md(project).write_text(text.split("---\n", 2)[2].lstrip("\n"), encoding="utf-8")
    assert two_titles(_run_gates(project)[0]) == []


def test_check_prints_the_two_titles_and_still_passes(project: Path, capsys) -> None:
    from manuscript_guard.cli import main

    assert main(["check", str(project)]) == 0
    assert TWO_TITLES not in capsys.readouterr().out
    was = retitled(project)

    assert main(["check", str(project)]) == 0
    said = capsys.readouterr().out
    assert said.count(TWO_TITLES) == 1
    assert "> " + was[:120] in said
    assert "0 failing" in said

    assert main(["check", str(project), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    (found,) = [f for f in payload["findings"] if f["code"] == "two-titles"]
    assert (found["severity"], found["gate"]) == ("warn", "BUILD")


def _printed_title(document: Path) -> str:
    with zipfile.ZipFile(document) as docx:
        properties = docx.read("docProps/core.xml").decode("utf-8")
    return re.search("<dc:title>(.*?)</dc:title>", properties, re.S).group(1)


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
@pytest.mark.parametrize("flags", [(), ("--skip-checks",)], ids=["checked", "unchecked"])
def test_build_says_the_two_titles_differ_and_builds(
    flags: tuple[str, ...], project: Path, capsys
) -> None:
    """Said once, before the document is made, and the document is paper.yaml's."""
    from manuscript_guard.cli import main

    retitled(project)
    assert main(["build", str(project), "--offline", *flags]) == 0
    said = capsys.readouterr().out
    assert said.count(TWO_TITLES) == 1
    assert "[WARN] BUILD" in said
    assert "assembled_files" not in said, "the counts say nothing beside a warning"
    assert said.index(TWO_TITLES) < said.index("built ")
    assert _printed_title(project / "build" / "manuscript.docx") == OTHER_TITLE


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_build_says_nothing_of_titles_that_agree(project: Path, capsys) -> None:
    """The baseline: a build with nothing to say prints the documents it made, and no more."""
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    said = capsys.readouterr().out
    assert TWO_TITLES not in said
    assert [line[:6] for line in said.splitlines()] == ["built ", "built "]


def test_a_build_the_check_refuses_says_the_two_titles_differ_once(
    project: Path, capsys
) -> None:
    """The check's own report carries the warning, and nothing is assembled after it."""
    from manuscript_guard.cli import main

    retitled(project)
    with main_md(project).open("a", encoding="utf-8") as handle:
        handle.write("\nA further 4321 reports were excluded.\n")
    assert main(["build", str(project), "--offline"]) == 1
    said = capsys.readouterr().out
    assert "not building" in said
    assert said.count(TWO_TITLES) == 1


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_submit_says_the_two_titles_differ_and_assembles_the_pack(
    project: Path, capsys
) -> None:
    """`submit` writes the title page from paper.yaml: the command where a header nobody
    kept up matters most was as silent as `build`."""
    from manuscript_guard.cli import main

    retitled(project)
    assert main(["submit", str(project), "--offline", "--skip-checks"]) == 0
    said = capsys.readouterr().out
    assert said.count(TWO_TITLES) == 1
    assert said.index(TWO_TITLES) < said.index("submission pack:")
    page = (project / "build" / "submission" / "title-page.md").read_text(encoding="utf-8")
    assert OTHER_TITLE in page


_AS_INIT_TYPES_IT = 'title: "A cohort study"'
_APOSTROPHE = chr(39)
_BACKSLASH = chr(92)
_ESCAPED_MARK = _BACKSLASH + '"'
_GAMMA = 'title: "IFN-$' + _BACKSLASH * 2 + 'gamma$ release assays"'
_OBESITY = 'title: "Rethinking the ' + _APOSTROPHE + "obesity paradox" + _APOSTROPHE + '"'

#: The header's title is read as YAML reads it, and compared with paper.yaml's with the
#: white space of each folded. Each case is a header, the title as paper.yaml types it, and
#: whether the header declares another title, which is when a warning is made. The first
#: seventeen are the ones a reading by line got wrong, each the other way round, while the
#: warning was shown and before the header was read as YAML (#165).
AS_YAML_READS_IT = {
    "a comment after the title": (
        "title: A cohort study  # working title", _AS_INIT_TYPES_IT, False
    ),
    "an apostrophe doubled between single quotation marks": (
        "title: " + _APOSTROPHE + "Crohn" + _APOSTROPHE * 2 + "s disease" + _APOSTROPHE,
        'title: "Crohn' + _APOSTROPHE + 's disease"',
        False,
    ),
    "a quotation mark escaped between double ones": (
        'title: "A ' + _ESCAPED_MARK + "quoted" + _ESCAPED_MARK + ' title"',
        "title: " + _APOSTROPHE + 'A "quoted" title' + _APOSTROPHE,
        False,
    ),
    "a backslash doubled between double quotation marks, as init types paper.yaml's": (
        _GAMMA, _GAMMA, False
    ),
    "a quoted title that ends with a phrase between the other marks": (
        _OBESITY, _OBESITY, False
    ),
    "a plain title that ends with a quotation mark": (
        'title: A study of "frailty"',
        "title: " + _APOSTROPHE + 'A study of "frailty"' + _APOSTROPHE,
        False,
    ),
    "a folded block": (
        "title: >\n  A cohort study\n  of two lines",
        'title: "A cohort study of two lines"',
        False,
    ),
    "a long title wrapped on to a second line": (
        'title: "A cohort study of adults\n  in primary care"',
        'title: "A cohort study of adults in primary care"',
        False,
    ),
    "an author's title above it": (
        "author:\n  - name: A\n    title: Dr\ntitle: A cohort study", _AS_INIT_TYPES_IT, False
    ),
    "an author's title and none of the header's own": (
        "author:\n  - name: A\n    title: Dr", _AS_INIT_TYPES_IT, False
    ),
    "a folded block in paper.yaml": (
        "title: A cohort study", "title: >\n  A cohort study", False
    ),
    "a title whose first line is paper.yaml's and that runs on to a second": (
        "title: A cohort study\n  of two lines", _AS_INIT_TYPES_IT, True
    ),
    "a title that begins on the line under the key": (
        "title:\n  Another", _AS_INIT_TYPES_IT, True
    ),
    "a plain title that ends with an apostrophe paper.yaml's does not have": (
        "title: What matters to the patients" + _APOSTROPHE,
        "title: What matters to the patients",
        True,
    ),
    "a space before the colon": ("title : Another", _AS_INIT_TYPES_IT, True),
    "a key between quotation marks": ('"title": Another', _AS_INIT_TYPES_IT, True),
    "a title written twice": (
        "title: A cohort study\ntitle: Another", _AS_INIT_TYPES_IT, True
    ),
    # What a reading by line gave rightly, and the YAML one must still.
    "another title": ("title: Another", _AS_INIT_TYPES_IT, True),
    "another title under an author's": (
        "author:\n  - name: A\n    title: Dr\ntitle: Another", _AS_INIT_TYPES_IT, True
    ),
    "no title": ("lang: en-GB", _AS_INIT_TYPES_IT, False),
    "a title with nothing after it": ("title:", _AS_INIT_TYPES_IT, False),
    "an empty title": ('title: ""', _AS_INIT_TYPES_IT, False),
    # What YAML has besides.
    "a null title": ("title: ~", _AS_INIT_TYPES_IT, False),
    "a literal block": ("title: |\n  A cohort study", _AS_INIT_TYPES_IT, False),
    "a tab after the key, which pandoc expands": (
        "title:" + chr(9) + "A cohort study", _AS_INIT_TYPES_IT, False
    ),
    "two spaces where paper.yaml has one": (
        "title: A  cohort study", _AS_INIT_TYPES_IT, False
    ),
    "an anchor on the title": ("title: &t A cohort study", _AS_INIT_TYPES_IT, False),
    "the same title through a merge key": (
        "base: &b {title: A cohort study}\n<<: *b", _AS_INIT_TYPES_IT, False
    ),
    "another title through a merge key": (
        "base: &b {title: Another}\n<<: *b", _AS_INIT_TYPES_IT, True
    ),
    "a title of its own over a merged one": (
        "base: &b {title: Another}\n<<: *b\ntitle: A cohort study", _AS_INIT_TYPES_IT, False
    ),
    "a list for a title": ("title: [A cohort study, Another]", _AS_INIT_TYPES_IT, True),
    # A no-break space is a character to pandoc, and prints as one.
    "a no-break space where paper.yaml has a space": (
        "title: A" + chr(0xA0) + "cohort study", _AS_INIT_TYPES_IT, True
    ),
    "a no-break space after the title": (
        "title: A cohort study" + chr(0xA0), _AS_INIT_TYPES_IT, True
    ),
    # A line break YAML keeps inside the title, which only the folding takes away.
    "a literal block over two lines": (
        "title: |" + chr(10) + "  A cohort" + chr(10) + "  study", _AS_INIT_TYPES_IT, False
    ),
    # Pandoc knows the key by its case.
    "a key with a capital": ("Title: Another", _AS_INIT_TYPES_IT, False),
    # Compared as typed, not as Markdown: pandoc prints these two alike.
    "the same words marked up another way": (
        "title: A *cohort* study", 'title: "A _cohort_ study"', True
    ),
}

#: Where the comparison says "another title" and pandoc would print the two alike: the
#: limit DESIGN.md's Known gaps records.
ALIKE_TO_PANDOC = {"the same words marked up another way"}


def test_init_types_a_title_with_tex_as_the_row_says(tmp_path: Path) -> None:
    """The row named for `init` says how `init` types such a title into paper.yaml. Held
    here, so that the row does not go on saying it if that changes."""
    from manuscript_guard.scaffold import init_project

    init_project(tmp_path / "paper", title="IFN-$" + _BACKSLASH + "gamma$ release assays")
    lines = (tmp_path / "paper" / "paper.yaml").read_text(encoding="utf-8").splitlines()
    assert lines[1] == _GAMMA


def _with_header(root: Path, header: str, typed: str = _AS_INIT_TYPES_IT):
    """A new project titled `typed` in paper.yaml, its manuscript opening with `header`."""
    from manuscript_guard.scaffold import init_project

    init_project(root, title="A cohort study")
    paper = root / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    assert _AS_INIT_TYPES_IT in text, "what `init` types changed under this test"
    paper.write_text(text.replace(_AS_INIT_TYPES_IT, typed, 1), encoding="utf-8")
    body = main_md(root).read_text(encoding="utf-8").split("---\n", 2)[2]
    main_md(root).write_text("---\n" + header + "\n---\n" + body, encoding="utf-8")
    project, report = load_project(root)
    assert not [f for f in report.failures if f.path == paper], "paper.yaml is still read"
    return project


def _folded(value) -> str:
    """On one line, as the comparison folds a title: spaces, tabs and line breaks, and not a
    no-break space."""
    return re.sub("[ " + chr(9) + chr(10) + chr(13) + "]+", " ", str(value)).strip(" ")


@pytest.mark.parametrize("case", list(AS_YAML_READS_IT))
def test_the_header_s_title_is_read_as_yaml_reads_it(case: str, tmp_path: Path) -> None:
    from manuscript_guard.build.assemble import check_shapes

    header, typed, warned = AS_YAML_READS_IT[case]
    project = _with_header(tmp_path / "paper", header, typed)
    # The table against YAML itself: the header declares another title, or it does not.
    declared = yaml.safe_load(header.expandtabs(4)).get("title")
    another = declared not in (None, "") and _folded(declared) != _folded(project.paper["title"])
    assert warned is another, "the table says what YAML says"

    found = two_titles(check_shapes(project))
    assert bool(found) is warned
    if warned:
        # A title that is no text is shown as its line stands in the file.
        shown = header if isinstance(declared, list) else _folded(declared)
        assert [f.context for f in found] == [shown]


def _title_to_pandoc(block: str):
    """The title pandoc keeps from a header, as it would print it; None where it keeps none."""
    import subprocess

    done = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=("---\n" + block + "\n---\n\nText.\n").encode("utf-8"),
        capture_output=True,
        check=True,
    )
    title = json.loads(done.stdout)["meta"].get("title")
    if title in (None, {"t": "MetaInlines", "c": []}, {"t": "MetaString", "c": ""}):
        return None
    # A block is a paragraph to pandoc and a quoted title a line: the same words printed.
    if title["t"] == "MetaBlocks" and [block["t"] for block in title["c"]] in (["Para"], ["Plain"]):
        title = {"t": "MetaInlines", "c": title["c"][0]["c"]}
    if title["t"] == "MetaInlines":
        # A line break inside a paragraph is printed as a space.
        spaced = [{"t": "Space"} if item == {"t": "SoftBreak"} else item for item in title["c"]]
        title = {"t": "MetaInlines", "c": spaced}
    return title


@pytest.mark.skipif(
    __import__("shutil").which("pandoc") is None, reason="pandoc is not installed"
)
def test_pandoc_takes_from_each_header_the_title_the_table_says() -> None:
    """The table is checked against PyYAML where it is used; this asks pandoc, which reads
    the manuscript. For each row it keeps a title from the header that is not the one it
    keeps from paper.yaml's line exactly where the table says a warning is made, but for
    the rows named as alike to it."""
    differently = set()
    for case, (header, typed, warned) in AS_YAML_READS_IT.items():
        declared = _title_to_pandoc(header)
        another = declared is not None and declared != _title_to_pandoc(typed)
        if another is not warned:
            differently.add(case)
    assert differently == ALIKE_TO_PANDOC


def _forget_headers() -> None:
    """Empty the caches of what was read from headers, so that a test of the reading is
    not answered from an earlier one, its own in a rerun included."""
    from manuscript_guard.text import masking

    for cached in vars(masking).values():
        if callable(getattr(cached, "cache_clear", None)):
            cached.cache_clear()


def test_a_header_is_composed_once_for_its_place_its_abstract_and_its_title(monkeypatch) -> None:
    """Composing is the slow part, and each further one is a further place to fail: a
    second one can raise where the first did not, being further down the stack. The
    abstract was read from a second composing, and the title at first with it."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text import masking

    _forget_headers()
    calls = []
    composing = yaml.compose_all

    def once(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise RecursionError("maximum recursion depth exceeded")
        return composing(*args, **kwargs)

    monkeypatch.setattr(yaml, "compose_all", once)
    text = "---\ntitle: Composed once for the title\nabstract: An abstract.\n---\n\nText.\n"
    assert masking.FRONTMATTER.match(text) is not None
    assert masking.front_matter_problem(text) is None
    assert masking.front_matter_abstract(text) == (3, "An abstract.")
    assert masking.front_matter_title(text) == (2, "Composed once for the title")
    assert strip_front_matter(text) == ("Text.\n", "Composed once for the title")
    assert len(calls) == 1


def test_a_header_too_deep_to_compose_declares_nothing_and_stays_in_the_body(monkeypatch) -> None:
    """What the first composing cannot take is no front matter: left in the body, where
    pandoc refuses it, with no abstract and no title read from it."""
    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.text import masking

    def too_deep(*args, **kwargs):
        raise RecursionError("maximum recursion depth exceeded")

    _forget_headers()
    monkeypatch.setattr(yaml, "compose_all", too_deep)
    text = "---\ntitle: Too deep to compose\nabstract: An abstract.\n---\n\nText.\n"
    assert masking.FRONTMATTER.match(text) is None
    assert masking.front_matter_abstract(text) is None
    assert masking.front_matter_title(text) is None
    assert strip_front_matter(text) == (text, "")


def _nested_header(depth: int) -> str:
    """A header whose `nest` key holds mappings `depth` deep, each one space further in."""
    lines = [" " * (level + 1) + "k:" for level in range(depth)]
    return "\n".join(["---", "title: A cohort study", "nest:", *lines]) + " v\n---\n\nText.\n"


def _stripped_from(frames: int, text: str) -> tuple[str, str]:
    """`strip_front_matter(text)` from `frames` calls further down the stack: where Python's
    limit falls depends on how deep the caller stands, and callers differ."""
    from manuscript_guard.build.assemble import strip_front_matter

    if frames:
        return _stripped_from(frames - 1, text)
    return strip_front_matter(text)


@pytest.mark.parametrize("frames", [0, 1])
def test_a_header_nested_as_deep_as_it_can_be_composed_ends_nothing_in_a_traceback(
    frames: int,
) -> None:
    """A header too deep to compose is left in the body, for pandoc to refuse. Read a
    second time for its title, one call further down, a header the first composing had
    just managed raised `RecursionError` out of `strip_front_matter`, and `import` ended
    in a traceback where main answered (the review of #168)."""
    raised, stripped, left = [], [], []
    for depth in range(440, 500):
        _forget_headers()
        try:
            body, _title = _stripped_from(frames, _nested_header(depth))
        except RecursionError:
            raised.append(depth)
            continue
        (stripped if body == "Text.\n" else left).append(depth)
    assert raised == [], f"RecursionError at nesting {raised}"
    # Where the limit falls is the interpreter's and the caller's. The two tests above hold
    # the same with no limit to find; this one says so when it has found none.
    if not (stripped and left):
        pytest.skip("Python's recursion limit falls outside the nestings tried here")


def test_the_warning_of_two_titles_names_the_line_of_the_header_s_title(tmp_path: Path) -> None:
    from manuscript_guard.build.assemble import check_shapes

    header = "author:\n  - name: A\n    title: Dr\ntitle: Another"
    project = _with_header(tmp_path / "paper", header)
    (found,) = two_titles(check_shapes(project))
    assert (found.line, found.context) == (5, "Another")


def test_a_supplementary_file_s_own_title_is_compared_with_the_paper_s(tmp_path: Path) -> None:
    """Nothing prints it: the supplement's title is made from the paper's. The hint says
    that, and does not say to make the two agree, which nobody should do there."""
    from manuscript_guard.build.assemble import check_shapes

    project = _with_header(tmp_path / "paper", "title: Another")
    supplement = tmp_path / "paper" / "manuscript" / "supplementary" / "S1.md"
    supplement.parent.mkdir()
    supplement.write_text(
        "---\ntitle: Supplementary methods\n---\n\n# Supplementary methods\n\nText.\n",
        encoding="utf-8",
    )
    paper, found = sorted(two_titles(check_shapes(project)), key=lambda f: f.path.name == "S1.md")
    assert (found.path, found.context) == (supplement, "Supplementary methods")
    assert found.message == "S1.md declares a different title from paper.yaml"
    assert "nothing prints" in found.hint and "delete the title from its header" in found.hint
    assert "agree" not in found.hint
    assert paper.path == main_md(tmp_path / "paper")
    assert "make them agree" in paper.hint, "the paper's own file keeps the hint it had"


# --------------------------------------------------------------------------------------
# A suggested edit is placed exactly, and decided before it is imported. A finding may carry
# the wording it asks for (`edits`); `review --suggestions` writes each as a tracked change
# under its reader's name, and `import` brings back what the author accepted. An edit that
# changed after it was filed would be shown in Word as the reader's; one placed anywhere but
# exactly would change other words; and one nobody decided would be imported as accepted.
# --------------------------------------------------------------------------------------

_A_MODEL_SUGGESTED = [
    {
        "severity": "minor",
        "where": "Introduction",
        "finding": "Say plainly that nobody has looked.",
        "edits": [{"old": "has not been examined", "new": "remains unexamined"}],
    },
]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["findings"][0]["edits"][0].update(new="was never examined by anyone"),
        lambda d: d["findings"][0]["edits"].append({"old": "specifically", "new": "alone"}),
        lambda d: d["findings"][0].pop("edits"),
    ],
    ids=["new-words-changed", "an-edit-added", "the-edits-deleted"],
)
def test_a_model_s_suggested_edit_changed_after_it_was_filed_fails(
    project: Path, monkeypatch, mutate
) -> None:
    """The edit is the reader's, and Word shows it under the reader's name: changed after
    the reading was filed, the reading is altered."""
    from test_review_run import Providers, answer, configure, reply_text

    from manuscript_guard.cli import main
    from manuscript_guard.panel import client

    transport = Providers()
    transport.default = lambda request: answer(reply_text("minor-revision", _A_MODEL_SUGGESTED))
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai-0123456789SECRETA")
    shutil.rmtree(project / "review")
    configure(project, "openai/model-a")
    assert main(["review", str(project), "--run", "--yes"]) == 0
    path = sorted((project / "review" / "round-1").glob("*.*.yaml"))[0]
    filed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert filed["findings"][0]["edits"] == _A_MODEL_SUGGESTED[0]["edits"]
    assert "reading-altered" not in _review_failures(project)
    _edit(path, mutate)
    assert "reading-altered" in _review_failures(project)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_an_edit_that_changes_a_number_a_binding_or_a_citation_is_not_written(
    project: Path,
) -> None:
    """By the rule `reworded` applies: a typed number changed, words that are only in the
    text with a value printed into them, words inside a citation, and new words that would
    open a binding or a citation. Each stays a finding to answer, and no document is made
    for edits none of which could be placed."""
    from suggesting import document, finding, suggest, with_edits

    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Whether the signal extends to example-drug specifically has not been examined.",
            "Whether the signal extends to example-drug specifically has not been examined, "
            "as the agency said [see @fictionalClassSignal2019, p. 4].",
        ),
        encoding="utf-8",
    )
    with_edits(
        project,
        finding(
            "r8-pe-02",
            ("computed from a 2 x 2 table", "computed from a 3 x 2 table"),
            ("a period of 10 years", "ten years"),
            ("as the agency said", "as {{results.ror.point}} said"),
            ("has not been examined", "has not been examined @fictionalClassSignal2019"),
        ),
        finding("r8-pe-03", ("p. 4", "p. 5")),
    )
    code, said = suggest(project)
    assert code == 0, said
    reasons = {
        "computed from a 2 x 2 table": "more than a change of words",
        "a period of 10 years": "only with a value",
        "as the agency said": "Markdown reads as markup",
        "has not been examined": "Markdown reads as markup",
        "p. 4": "inside a citation",
    }
    for old, why in reasons.items():
        line = next((ln for ln in said.splitlines() if f"'{old}" in ln), "")
        assert why in line, (old, said)
    assert "written as tracked changes" not in said
    assert not document(project).exists()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_an_edit_whose_words_are_not_found_exactly_once_is_not_written(project: Path) -> None:
    """Words in the manuscript more than once, nowhere, across two paragraphs, across a hard
    line break that writing them would delete, and two edits of the same words: none is
    placed by guessing which was meant."""
    from suggesting import finding, suggest, with_edits

    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Whether the signal extends to example-drug specifically has not",
            "Whether the signal extends to *example-drug* specifically  \nhas not",
        ),
        encoding="utf-8",
    )
    with_edits(
        project,
        finding(
            "r8-pe-02",
            ("the", "THE"),
            ("words that are nowhere", "other words"),
            ("has not been examined.\n\nWhether", "x"),
            ("specifically has not", "has not"),
            ("Reports were included without", "Reports were taken without"),
            ("were included without restriction", "were included with no restriction"),
            ("example-drug specifically", "the drug specifically"),
        ),
    )
    code, said = suggest(project)
    assert code == 0, said
    reasons = {
        "the": "in the manuscript",
        "words that are nowhere": "not in the manuscript as it stands",
        # Quoted as the reader was sent it, across the emphasis the source holds.
        "example-drug specifically": "only as the build prints them, across markup",
        "has not been examined. Whether": "two paragraphs",
        "specifically has not": "across a line break",
        "Reports were included without": "same words",
        "were included without restriction": "same words",
    }
    for old, why in reasons.items():
        line = next((ln for ln in said.splitlines() if f"'{old}" in ln), "")
        assert why in line, (old, said)


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_a_suggestion_nobody_decided_is_not_imported(project: Path, tmp_path: Path) -> None:
    """Read as accepted, as `import` reads every tracked change, a suggestion the author
    never looked at would merge. Nothing is imported while one is left, whichever."""
    from suggesting import offered_round, run
    from word_edits import decide

    document = offered_round(project)
    before = (project / "manuscript" / "main.md").read_bytes()
    record = (project / "review" / "round-8" / "pharmacoepidemiologist.yaml").read_bytes()
    for choices in ({}, {1: "accept"}, {1: "accept", 2: "reject"}, {2: "reject", 3: "accept"}):
        returned = decide(document, tmp_path / "back.docx", choices)
        code, said = run("import", str(returned), str(project), "--apply")
        assert code == 1, said
        assert "Accept or reject each one in Word first" in said
        assert (project / "manuscript" / "main.md").read_bytes() == before
        assert (project / "review" / "round-8" / "pharmacoepidemiologist.yaml").read_bytes() == (
            record
        )


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_an_edit_that_written_in_would_be_more_than_its_words_is_not_written(
    project: Path,
) -> None:
    """An accepted suggestion is written into the source where its words are, not merged
    from Word's text, so what the source then says is asked before it is offered. New words
    that open the paragraph as a list item would take it out of the paragraphs the build
    marks, and new words against a closing underscore would end the emphasis there: written
    so, neither reads as Word shows it accepted."""
    from suggesting import document, finding, suggest, with_edits

    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "Whether the signal extends to example-drug specifically",
            "Whether the signal extends to _example-drug_, specifically",
        ),
        encoding="utf-8",
    )
    with_edits(
        project,
        finding("r8-pe-02", ("Whether the signal", "+ Whether the signal"),
                (", specifically", "s specifically")),
    )  # fmt: skip
    code, said = suggest(project)
    assert code == 0, said
    reasons = {
        "Whether the signal": "no longer be a paragraph of its own",
        ", specifically": "would not read as Word shows it",
    }
    for old, why in reasons.items():
        line = next((ln for ln in said.splitlines() if f"'{old}'" in ln), "")
        assert why in line, (old, said)
    assert not document(project).exists()


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("how", ["old-words-changed", "record-gone"])
def test_an_accepted_suggestion_whose_words_are_not_the_document_s_is_not_merged(
    project: Path, tmp_path: Path, how: str
) -> None:
    """`import` writes an accepted suggestion's words from its sealed record, where the old
    words are found once and are the ones the document showed. A record sealed again with
    other old words, which are in the paragraph too, would put the new words in the wrong
    place; a record that is gone gives no words. Either way the paragraph is refused whole:
    merged from Word's text instead, it could lose the markup the edit was offered beside."""
    from suggesting import READING, offered_round, reading, run
    from word_edits import decide

    from manuscript_guard.gates.review import reading_digest

    main = project / "manuscript" / "main.md"
    document = offered_round(project)
    returned = decide(document, tmp_path / "back.docx", {1: "accept", 2: "accept", 3: "accept"})
    if how == "record-gone":
        (project / READING).unlink()
    else:
        record = reading(project)
        edit = next(f for f in record["findings"] if f["id"] == "r8-pe-03")["edits"][0]
        edit["old"] = "example-drug"
        record["reading_sha256"] = reading_digest(record)
        (project / READING).write_text(yaml.safe_dump(record, sort_keys=False), encoding="utf-8")
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 1, said
    assert "cannot be written into the source where its words were" in said, said
    text = main.read_text(encoding="utf-8")
    assert "Whether the signal extends to example-drug specifically has not been examined." in (
        text
    )
    assert "in particular" not in text


# --------------------------------------------------------------------------------------
# G14: an abbreviation is defined once, before it is used. Each test below makes one of the
# edits a hurried revision makes, and the gate has to report that edit and no other.
# --------------------------------------------------------------------------------------

UNDEFINED_USE = " (ROR {{lit.background.class_ror}})"
DEFINED_USE = ", with a reporting odds ratio (ROR) of {{lit.background.class_ror}}"
SPELT_OUT = "The reporting odds ratio was computed from"
ABBREVIATED = "The ROR was computed from"


def language_findings(root: Path) -> list[tuple[str, int]]:
    from manuscript_guard.gates import check_language

    report = check_language(load_project(root)[0])
    assert report.ok, "G14 warns; it does not fail"
    return sorted((f.code, f.line) for f in report.findings)


def with_ror_defined(root: Path) -> str:
    """The example with its one slip mended: ROR defined where the Introduction first uses
    it, and used once in the Methods."""
    text = main_md(root).read_text(encoding="utf-8")
    assert UNDEFINED_USE in text and SPELT_OUT in text, "the fixture changed under this test"
    mended = text.replace(UNDEFINED_USE, DEFINED_USE).replace(SPELT_OUT, ABBREVIATED)
    main_md(root).write_text(mended, encoding="utf-8")
    return mended


def line_of(text: str, needle: str) -> int:
    return text.count("\n", 0, text.index(needle)) + 1


def test_the_example_s_undefined_abbreviation_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    assert language_findings(project) == [("abbreviation-undefined", line_of(text, "(ROR "))]


def test_the_mended_example_has_nothing_to_report(project: Path) -> None:
    """The baseline for what follows: a gate that reports the clean text proves nothing by
    reporting the corrupted one."""
    with_ror_defined(project)
    assert language_findings(project) == []


def test_abbreviating_throughout_without_a_definition_is_caught(project: Path) -> None:
    """Find-and-replace of the long form, the definition never written: the abstract and
    the main text each use ROR, and neither defines it."""
    text = main_md(project).read_text(encoding="utf-8")
    shortened = re.sub(r"\breporting(\s+)odds(\s+)ratio\b", "ROR", text)
    assert shortened.count("ROR") > 4
    main_md(project).write_text(shortened, encoding="utf-8")
    found = language_findings(project)
    assert [code for code, _line in found] == ["abbreviation-undefined"] * 2
    assert found[0][1] == line_of(shortened, "The ROR was"), "the abstract's, where it is used"


def test_a_definition_moved_below_its_first_use_is_caught(project: Path) -> None:
    """The Introduction is cut down and its definition goes with the cut; the author
    defines the term again where the Methods compute it. The Introduction still uses it."""
    mended = with_ror_defined(project)
    moved = mended.replace(DEFINED_USE, UNDEFINED_USE).replace(
        ABBREVIATED, "The reporting odds ratio (ROR) was computed from"
    )
    moved = moved.replace("A signal was defined", "A raised ROR was read as a signal, defined")
    main_md(project).write_text(moved, encoding="utf-8")
    assert language_findings(project) == [
        ("abbreviation-used-before-defined", line_of(moved, "(ROR {{"))
    ]


def test_a_definition_pasted_a_second_time_is_caught(project: Path) -> None:
    mended = with_ror_defined(project)
    again = mended.replace(
        "The reporting odds ratio observed here", "The reporting odds ratio (ROR) observed here"
    )
    assert again != mended
    main_md(project).write_text(again, encoding="utf-8")
    assert language_findings(project) == [
        ("abbreviation-redefined", line_of(again, "ratio (ROR) observed"))
    ]


def test_a_definition_whose_only_use_was_cut_is_caught(project: Path) -> None:
    mended = with_ror_defined(project)
    cut = mended.replace(ABBREVIATED, SPELT_OUT)
    main_md(project).write_text(cut, encoding="utf-8")
    assert language_findings(project) == [("abbreviation-unused", line_of(cut, "(ROR)"))]


def test_a_definition_whose_brackets_were_deleted_is_caught(project: Path) -> None:
    """A copy-editor's tidy: "a reporting odds ratio (ROR) of" becomes "a reporting odds
    ratio of", and the Methods still say ROR."""
    mended = with_ror_defined(project)
    tidied = mended.replace("ratio (ROR) of", "ratio of")
    assert tidied != mended
    main_md(project).write_text(tidied, encoding="utf-8")
    assert language_findings(project) == [
        ("abbreviation-undefined", line_of(tidied, ABBREVIATED))
    ]


# --------------------------------------------------------------------------------------
# A round read by models through `review --run`. What a run files is a set of records like
# any other. What it must not do is leave a round that passes a submission with less than
# was asked for: a provider that was down, a reply that was not a review, a finding nobody
# answered. No test here opens a connection; the transport answers from the test.
# --------------------------------------------------------------------------------------

_RAN = json.dumps(
    {
        "verdict": "minor-revision",
        "summary": "The estimator is stated and the estimate can be reconstructed.",
        "rejection_tests": [
            {
                "test": "The estimate cannot be reconstructed from what is reported.",
                "holds": False,
                "evidence": "The two-by-two table is in the Results.",
            }
        ],
        "findings": [{"severity": "minor", "where": "Abstract", "finding": "Say synthetic."}],
    }
)


def _served(text: str, finish: str = "stop"):
    from manuscript_guard.panel.client import HttpResponse

    body = {
        "id": "chatcmpl-1",
        "model": "model-as-served",
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    return HttpResponse(200, {}, json.dumps(body).encode())


def _with(**changed) -> str:
    said = json.loads(_RAN)
    said.update(changed)
    return json.dumps(said)


def _down():
    from manuscript_guard.panel.client import HttpResponse

    return HttpResponse(500, {}, b'{"message": "internal error"}')


def _no_answer():
    from manuscript_guard.panel.client import TransportError

    raise TransportError("timeout", "no answer within 600 s")


_MAJOR = [{"severity": "major", "finding": "The conclusion does not follow from the estimate."}]
_ANSWERED = [{**_MAJOR[0], "resolution": "Already addressed in the Discussion."}]

#: What the second provider does, and the failure a submission must then show.
_RUNS_THAT_FALL_SHORT = {
    "a provider is down": (_down, "reading-missing"),
    "a provider does not answer in time": (_no_answer, "reading-missing"),
    "a model answers in prose": (lambda: _served("The paper is fine."), "reading-missing"),
    "a reply is cut short": (lambda: _served(_RAN, "length"), "reading-missing"),
    "a reply is cut short and still parses": (
        lambda: _served(_with(findings=[]), "length"),
        "reading-missing",
    ),
    "a model declines": (lambda: _served(_RAN, "content_filter"), "reading-missing"),
    "a model gives a verdict of its own": (
        lambda: _served(_with(verdict="accept")),
        "reading-missing",
    ),
    "a model leaves the verdict out": (
        lambda: _served(json.dumps({k: v for k, v in json.loads(_RAN).items() if k != "verdict"})),
        "reading-missing",
    ),
    "a model answers its own major finding": (
        lambda: _served(_with(findings=_ANSWERED)),
        "reading-missing",
    ),
    "a model says who read and when": (
        lambda: _served(_with(reviewed_by="A. Statistician", reviewed_on="2026-01-01")),
        "reading-missing",
    ),
    "a model wraps the review in words": (
        lambda: _served("Here is my review." + chr(10) + _RAN),
        "reading-missing",
    ),
    "a reply holds a character a record would not keep as written": (
        lambda: _served(_with(summary="The estimator is stated." + chr(0x85) + "It is the ROR.")),
        "reading-missing",
    ),
    "a model raises a major finding": (
        lambda: _served(_with(verdict="major-revision", findings=_MAJOR)),
        "open-major-finding",
    ),
}


def _run_round_two(root: Path, monkeypatch, second=None) -> int:
    """Round two of the example, read by two models as well as by hand. `second` is what
    the second provider does with each request; the first always files a clean reading."""
    from manuscript_guard.cli import main
    from manuscript_guard.panel import client

    def transport(request, timeout):
        if second is not None and "api.mistral.ai" in request.url:
            return second()
        return _served(_RAN)

    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-0123456789ABCDEF")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-0123456789ABCDEF")
    paper = root / "paper.yaml"
    paper.write_bytes(
        paper.read_bytes()
        + (chr(10) + "review:" + chr(10) + "  models: [openai/model-a, mistral/model-b]").encode()
        + chr(10).encode()
    )
    return main(["review", str(root), "--run", "--round", "2", "--yes"])


def test_a_round_two_models_read_through_a_run_passes_a_submission(
    project: Path, monkeypatch
) -> None:
    """The baseline. Everything in the next test is meaningless if this fails."""
    assert _run_round_two(project, monkeypatch) == 0
    assert not _review_failures(project)
    assert len(list(_round_two(project).glob("*.*.yaml"))) == 4


@pytest.mark.parametrize("name", sorted(_RUNS_THAT_FALL_SHORT))
def test_a_run_that_falls_short_fails_a_submission(project: Path, monkeypatch, name: str) -> None:
    second, expected = _RUNS_THAT_FALL_SHORT[name]
    code = _run_round_two(project, monkeypatch, second)
    assert expected in _review_failures(project)
    if expected == "reading-missing":
        assert code == 1, "and the command itself says the round is not complete"
        assert not list(_round_two(project).glob("*.mistral-model-b.yaml"))
        assert len(list(_round_two(project).glob("*.openai-model-a.yaml"))) == 2


def test_a_run_nobody_agreed_to_changes_nothing(project: Path, monkeypatch) -> None:
    """Under a test nobody is there to be asked. Without `--yes`, nothing is sent, and the
    project is left byte for byte as it was: no panel gains a reader it then waits for."""
    from manuscript_guard.cli import main
    from manuscript_guard.panel import client

    sent: list = []
    monkeypatch.setattr(client, "default_transport", lambda request, timeout: sent.append(1))
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-0123456789ABCDEF")
    paper = project / "paper.yaml"
    paper.write_bytes(
        paper.read_bytes()
        + (chr(10) + "review:" + chr(10) + "  models: [openai/model-a]" + chr(10)).encode()
    )
    before = {
        path: path.read_bytes() for path in sorted(project.rglob("*")) if path.is_file()
    }
    assert main(["review", str(project), "--run", "--round", "2"]) == 2
    assert sent == []
    after = {path: path.read_bytes() for path in sorted(project.rglob("*")) if path.is_file()}
    assert after == before
    assert not _review_failures(project)


# --------------------------------------------------------------------------------------
# What the data can answer, while the plan is written
# --------------------------------------------------------------------------------------


def _feasibility_said(root: Path, stage: str, **values: int) -> list[str]:
    """G12 at a stage, with these values emitted besides the example's."""
    from manuscript_guard.gates import check_design

    if values:
        fragment = next((root / "results").glob("*.json"))
        document = json.loads(fragment.read_text(encoding="utf-8"))
        for key, value in values.items():
            document["values"][key.replace("__", ".")] = {"value": value, "display": str(value)}
        fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
        write_digest(fragment)
    project, _ = load_project(root)
    _namespace, results, _literature, _ = load_namespace(project)
    return [f.code for f in check_design(project, results, stage).findings
            if f.code == "feasibility-not-run"]  # fmt: skip


def test_a_plan_written_before_the_data_were_looked_at_is_a_warning(project: Path) -> None:
    """Item 47: a plan could set out an analysis of data nobody had counted, and nothing
    said so while it was written."""
    assert _feasibility_said(project, "design") == ["feasibility-not-run"]
    assert _feasibility_said(project, "drafting") == []


def test_a_plan_with_feasibility_results_says_nothing(project: Path) -> None:
    assert _feasibility_said(project, "design", feasibility__n_reports=4000) == []


def test_a_plan_with_no_analysis_yet_is_not_asked_for_feasibility(project: Path) -> None:
    """An empty Analysis is its own finding; the feasibility results wait for an analysis."""
    plan = project / "design" / "plan.md"
    text = plan.read_text(encoding="utf-8")
    start, end = text.index("## Analysis\n"), text.index("## Sample size")
    plan.write_text(text[:start] + "## Analysis\n\nTBD\n\n" + text[end:], encoding="utf-8")
    assert _feasibility_said(project, "design") == []


# ------------------------------------------------- a panel reads the plan before the results

_DESIGN_REMIT = "Whether the design supports the inference the plan intends: confounding, " \
    "selection, immortal time, missing data, multiplicity"  # fmt: skip


def _design_said(root: Path, submission: bool = False) -> list[tuple[str, str]]:
    from manuscript_guard.gates.design_review import check_design_rounds

    project, _ = load_project(root)
    return [(f.code, f.severity) for f in check_design_rounds(project, submission=submission)
            .findings]  # fmt: skip


def _design_recorded(root: Path, findings: str = "") -> Path:
    from manuscript_guard.cli import main

    assert main(["review", str(root), "--design", "--record", "methodologist", "--verdict",
                 "major-revision", "--remit", _DESIGN_REMIT]) == 0  # fmt: skip
    record = root / "review" / "design" / "round-1" / "methodologist.yaml"
    if findings:
        text = record.read_text(encoding="utf-8").replace("findings: []\n", findings)
        record.write_text(text, encoding="utf-8")
    return record


_DESIGN_MAJOR = (
    "findings:\n- id: d1\n  severity: major\n  finding: The comparator drugs share the "
    "indication only in part, so the ratio mixes the drug with its indication.\n"
)


def test_a_design_round_reads_the_plan_and_its_majors_are_answered(project: Path) -> None:
    """Item 46: no panel read the plan before there were results, and a design that could
    not answer its question was said too late."""
    from manuscript_guard.cli import main

    assert _design_said(project) == []
    record = _design_recorded(project, _DESIGN_MAJOR)
    assert _design_said(project) == [("design-reading-unsealed", "warn"),
                                     ("design-major-open", "warn")]  # fmt: skip
    assert ("design-major-open", "fail") in _design_said(project, submission=True)
    assert main(["review", str(project), "--design", "--seal", "methodologist"]) == 0
    assert _design_said(project) == [("design-major-open", "warn")]
    text = record.read_text(encoding="utf-8")
    record.write_text(text.replace("  finding: The comparator", "  resolution: The plan now "
                                   "restricts the comparators to the same indication.\n"
                                   "  finding: The comparator"), encoding="utf-8")  # fmt: skip
    assert _design_said(project) == []


def test_a_design_round_of_a_plan_changed_since_is_stale(project: Path) -> None:
    from manuscript_guard.cli import main

    _design_recorded(project)
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome.\n")
    assert _design_said(project) == [("design-review-stale", "warn")]
    # Round 1 of #308: a later round that read the plan as it stands left the first stale
    # for good. It supersedes it, as a manuscript round does.
    assert main(["review", str(project), "--design", "--record", "methodologist",
                 "--round", "2", "--verdict", "pass"]) == 0  # fmt: skip
    assert _design_said(project) == [("design-review-superseded", "info")]


def test_a_later_design_round_supersedes_only_the_readers_who_read_again(project: Path) -> None:
    """Round 2 of #308: a later round of one reviewer superseded every stale reading of the
    round before it, a reviewer who never read the plan as it stands included."""
    from manuscript_guard.cli import main

    _design_recorded(project)
    remit = "Whether the analysis can estimate what is asked"
    assert main(["review", str(project), "--design", "--record", "statistician", "--verdict",
                 "pass", "--remit", remit]) == 0  # fmt: skip
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome.\n")
    assert main(["review", str(project), "--design", "--record", "methodologist",
                 "--round", "2", "--verdict", "pass"]) == 0  # fmt: skip
    said = _design_said(project)
    assert sorted(said) == [("design-review-stale", "warn"), ("design-review-superseded", "info")]


def test_a_superseded_design_round_s_open_major_still_binds(project: Path) -> None:
    from manuscript_guard.cli import main

    _design_recorded(project, _DESIGN_MAJOR)
    assert main(["review", str(project), "--design", "--seal", "methodologist"]) == 0
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome.\n")
    assert main(["review", str(project), "--design", "--record", "methodologist",
                 "--round", "2", "--verdict", "pass"]) == 0  # fmt: skip
    assert _design_said(project) == [("design-review-superseded", "info"),
                                     ("design-major-open", "warn")]  # fmt: skip


def test_a_design_round_is_stale_when_the_data_are_counted_again(project: Path) -> None:
    _feasibility_said(project, "design", feasibility__n_reports=4000)
    _design_recorded(project)
    assert _design_said(project) == []
    _feasibility_said(project, "design", feasibility__n_reports=3999)
    assert _design_said(project) == [("design-review-stale", "warn")]


def test_a_design_reading_changed_after_its_seal_is_said(project: Path) -> None:
    from manuscript_guard.cli import main

    record = _design_recorded(project, _DESIGN_MAJOR)
    assert main(["review", str(project), "--design", "--seal", "methodologist"]) == 0
    text = record.read_text(encoding="utf-8")
    record.write_text(text.replace("severity: major", "severity: minor"), encoding="utf-8")
    assert _design_said(project) == [("design-reading-altered", "warn")]
    assert _design_said(project, submission=True) == [("design-reading-altered", "fail")]


def test_a_design_panel_reviewer_who_has_not_read_is_said(project: Path) -> None:
    _design_recorded(project)
    panel = project / "review" / "design" / "panel-1.yaml"
    document = yaml.safe_load(panel.read_text(encoding="utf-8"))
    document["reviewers"].append({"id": "clinician", "remit": "Whether the question matters"})
    panel.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert _design_said(project) == [("design-review-missing", "warn")]


def test_a_design_panel_naming_one_reviewer_twice_is_said_once(project: Path) -> None:
    """Rounds 1 of #308 and #313: G11 says a reviewer listed twice, and G12 did not; one
    record answered both remits, and its overrides were listed twice."""
    from manuscript_guard.gates.design_review import override_signables

    record = _design_recorded(project, _DESIGN_MAJOR)
    record.write_text(record.read_text(encoding="utf-8").replace(
        "  finding: The comparator", "  overridden: The indication is the exposure here.\n"
        "  finding: The comparator"), encoding="utf-8")  # fmt: skip
    panel = project / "review" / "design" / "panel-1.yaml"
    document = yaml.safe_load(panel.read_text(encoding="utf-8"))
    document["reviewers"].append(dict(document["reviewers"][0]))
    panel.write_text(yaml.safe_dump(document), encoding="utf-8")
    said = _design_said(project)
    assert said.count(("design-duplicate-reviewer", "warn")) == 1
    assert ("design-duplicate-reviewer", "fail") in _design_said(project, submission=True)
    assert len(override_signables(load_project(project)[0])) == 1


def test_a_reader_named_by_a_reviewer_s_second_slot_is_read(project: Path) -> None:
    """Round 1 of #348: a reviewer listed twice was read from its first slot alone, so a
    reader only the second named went unread, and its open major unsaid."""
    _design_read_by(project, "openai/gpt-x")
    _design_read_by(project, "Dr Tanaka", _DESIGN_MAJOR)
    panel = project / "review" / "design" / "panel-1.yaml"
    document = yaml.safe_load(panel.read_text(encoding="utf-8"))
    first = document["reviewers"][0]
    document["reviewers"] = [{**first, "readers": ["openai/gpt-x"]},
                             {**first, "readers": ["Dr Tanaka"]}]  # fmt: skip
    panel.write_text(yaml.safe_dump(document), encoding="utf-8")
    said = _design_said(project)
    assert ("design-major-open", "warn") in said, said
    assert ("design-reading-unnamed", "warn") not in said
    # Round 2 of #348: a slot that names no reader asks for the plain record still.
    del document["reviewers"][0]["readers"]
    panel.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert ("design-review-missing", "warn") in _design_said(project)


def test_a_design_reading_giving_one_id_to_two_findings_is_said(project: Path) -> None:
    """Round 1 of #313: an override is signed by its finding's id, so two overridden majors
    of one id shared one sign-off."""
    _design_recorded(project, _DESIGN_MAJOR + _DESIGN_MAJOR.replace("findings:\n", ""))
    said = _design_said(project)
    assert ("design-finding-id-repeated", "warn") in said
    assert ("design-finding-id-repeated", "fail") in _design_said(project, submission=True)


def test_a_design_reader_the_panel_cannot_name_fails_at_submission(project: Path) -> None:
    """Round 1 of #315: G11 fails a reader it cannot file at submission, and G12 warned."""
    _design_recorded(project)
    panel = project / "review" / "design" / "panel-1.yaml"
    document = yaml.safe_load(panel.read_text(encoding="utf-8"))
    document["reviewers"][0]["readers"] = ["model-a", "Model A"]
    panel.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert ("design-reader-unnamed", "warn") in _design_said(project)
    assert ("design-reader-unnamed", "fail") in _design_said(project, submission=True)


def test_a_design_round_is_not_a_round_of_the_manuscript(project: Path) -> None:
    """Kept apart: a design round never counts toward the manuscript's rounds, and needs a
    remit of its own before a folder is made for it."""
    from manuscript_guard.cli import main
    from manuscript_guard.gates import check_review

    before = check_review(load_project(project)[0]).counts
    assert main(["review", str(project), "--design", "--record", "methodologist",
                 "--verdict", "pass"]) == 2  # fmt: skip
    assert not (project / "review" / "design").exists()
    _design_recorded(project)
    assert check_review(load_project(project)[0]).counts == before


_OVERRIDDEN = "  overridden: The indication is recorded for too few reports to restrict on.\n"


def test_an_overridden_design_objection_is_signed_by_the_statistician(project: Path) -> None:
    """Item 46: an override of a design-round major was the author's word alone; the
    statistician the project names signs it, bound to the objection and the reason."""
    from manuscript_guard.cli import main

    record = _design_recorded(project, _DESIGN_MAJOR + _OVERRIDDEN)
    assert main(["review", str(project), "--design", "--seal", "methodologist"]) == 0
    key = "G12/design-override/1/methodologist/d1"
    said = _override_said(project)
    assert [(code, severity) for code, severity, _hint in said] == [
        ("design-override-unsigned", "warn")
    ]
    assert f'manuscript-guard sign --as "Blaise Sample" --finding {key}' in said[0][2]
    assert main(["sign", str(project), "--as", "Ada Example", "--finding", key]) == 2
    assert main(["sign", str(project), "--as", "Sample", "--finding", key]) == 0
    signed = [(code, severity) for code, severity, _hint in _override_said(project)]
    assert signed == [("design-override-unsigned", "info")]
    # Round 1 of #313: the message said nobody had signed, and kept saying it once signed.
    from manuscript_guard.gates.design_review import check_design_rounds

    [message] = [f.message for f in check_design_rounds(load_project(project)[0]).findings
                 if f.code == "design-override-unsigned"]  # fmt: skip
    assert "nobody" not in message and "signed off by Blaise Sample" in message

    # A reason rewritten after the signature wants it again.
    text = record.read_text(encoding="utf-8")
    record.write_text(text.replace("too few reports", "too few of the reports"), "utf-8")
    [(code, severity, hint)] = _override_said(project)
    assert (code, severity) == ("design-override-unsigned", "warn") and "changed since" in hint


def test_a_resolved_design_objection_wants_no_signature(project: Path) -> None:
    from manuscript_guard.cli import main

    resolved = _OVERRIDDEN + "  resolution: The comparators are restricted to the indication.\n"
    _design_recorded(project, _DESIGN_MAJOR + resolved)
    assert main(["review", str(project), "--design", "--seal", "methodologist"]) == 0
    assert _override_said(project) == []


def _override_said(root: Path) -> list[tuple[str, str, str]]:
    from manuscript_guard.gates.design_review import check_design_rounds

    project, _ = load_project(root)
    return [(f.code, f.severity, f.hint or "") for f in check_design_rounds(project).findings
            if f.code == "design-override-unsigned"]  # fmt: skip


def _design_read_by(root: Path, reader: str, findings: str = "", round_: int = 1) -> Path:
    """A named reading of the methodologist's design remit, filed as `--reading` files it."""
    from manuscript_guard.cli import main
    from manuscript_guard.gates.review import reading_slug

    assert main(["review", str(root), "--design", "--record", "methodologist", "--reading",
                 reader, "--round", str(round_), "--verdict", "major-revision", "--remit",
                 _DESIGN_REMIT]) == 0  # fmt: skip
    record = (root / "review" / "design" / f"round-{round_}"
              / f"methodologist.{reading_slug(reader)}.yaml")  # fmt: skip
    if findings:
        text = record.read_text(encoding="utf-8").replace("findings: []\n", findings)
        record.write_text(text, encoding="utf-8")
    return record


def test_a_design_remit_read_by_two_readers_is_read_twice(project: Path) -> None:
    """Item 46: a design panel's named readers were not read, so a remit read by two models
    counted one reading, and the other's objections went unread. Each reader the panel
    names is read from its own file now, as in a manuscript round."""
    from manuscript_guard.cli import main

    first = _design_read_by(project, "openai/gpt-x", _DESIGN_MAJOR)
    _design_read_by(project, "Dr Tanaka")
    panel = yaml.safe_load((project / "review" / "design" / "panel-1.yaml").read_text("utf-8"))
    assert panel["reviewers"][0]["readers"] == ["openai/gpt-x", "Dr Tanaka"]
    assert first.name == "methodologist.openai-gpt-x.yaml"
    assert yaml.safe_load(first.read_text("utf-8"))["reader"] == "openai/gpt-x"
    assert _design_said(project) == [("design-reading-unsealed", "warn"),
                                     ("design-major-open", "warn")]  # fmt: skip
    assert main(["review", str(project), "--design", "--seal", "methodologist", "--reading",
                 "openai/gpt-x"]) == 0  # fmt: skip
    from manuscript_guard.gates.design_review import check_design_rounds

    [open_] = check_design_rounds(load_project(project)[0]).findings
    assert open_.message.startswith("design round 1: methodologist (openai/gpt-x) d1:")


def test_a_named_design_reader_who_has_not_read_is_said(project: Path) -> None:
    _design_read_by(project, "openai/gpt-x")
    panel = project / "review" / "design" / "panel-1.yaml"
    document = yaml.safe_load(panel.read_text(encoding="utf-8"))
    document["reviewers"][0]["readers"].append("Dr Tanaka")
    panel.write_text(yaml.safe_dump(document), encoding="utf-8")
    from manuscript_guard.gates.design_review import check_design_rounds

    [missing] = check_design_rounds(load_project(project)[0]).findings
    assert (missing.code, missing.severity) == ("design-review-missing", "warn")
    assert missing.message == "design round 1: methodologist (Dr Tanaka) has not read the plan"
    assert '--reading "Dr Tanaka" --verdict' in missing.hint


def test_a_design_reading_the_panel_names_no_reader_for_is_not_read(project: Path) -> None:
    """As in a manuscript round: a file beside the record is read only when the panel names
    its reader, and one it does not is said."""
    record = _design_recorded(project)
    beside = record.with_name("methodologist.old.yaml")
    beside.write_text(record.read_text(encoding="utf-8").replace(
        "findings: []\n", _DESIGN_MAJOR), encoding="utf-8")  # fmt: skip
    assert _design_said(project) == [("design-reading-unnamed", "warn")]


def test_a_named_design_reading_that_names_another_reader_is_not_counted(project: Path) -> None:
    record = _design_read_by(project, "openai/gpt-x", _DESIGN_MAJOR)
    record.write_text(record.read_text(encoding="utf-8").replace(
        "reader: openai/gpt-x", "reader: mistral/m"), encoding="utf-8")  # fmt: skip
    assert _design_said(project) == [("design-reading-misfiled", "warn")]
    assert _design_said(project, submission=True) == [("design-reading-misfiled", "fail")]


def test_a_stale_named_design_reading_is_superseded_by_its_own_reader_only(
    project: Path,
) -> None:
    """Supersession is by reader: one model reading the changed plan again does not answer
    for the person who read it before."""
    _design_read_by(project, "openai/gpt-x")
    _design_read_by(project, "Dr Tanaka")
    _plan_edited(project, "## Outcome", "## Outcome\n\nA second outcome.\n")
    _design_read_by(project, "openai/gpt-x", round_=2)
    from manuscript_guard.gates.design_review import check_design_rounds

    said = check_design_rounds(load_project(project)[0]).findings
    assert sorted((f.code, f.message.split(" read ")[0]) for f in said) == [
        ("design-review-stale", "design round 1: methodologist (Dr Tanaka)"),
        ("design-review-superseded", "design round 1: methodologist (openai/gpt-x)"),
    ]


def test_a_named_reader_s_overridden_design_objection_is_signed_apart(project: Path) -> None:
    """Each reading numbers its own findings, so two readers' d1 are two objections."""
    from manuscript_guard.cli import main

    _design_read_by(project, "openai/gpt-x", _DESIGN_MAJOR + _OVERRIDDEN)
    assert main(["review", str(project), "--design", "--seal", "methodologist", "--reading",
                 "openai/gpt-x"]) == 0  # fmt: skip
    [(code, _severity, hint)] = _override_said(project)
    assert "--finding G12/design-override/1/methodologist.openai-gpt-x/d1" in hint


# --------------------------------------------------------------------------------------
# TeX outside dollar signs in what the build prints of paper.yaml
# --------------------------------------------------------------------------------------

#: What an author types in place of a line of the example's `paper.yaml`, and the words
#: the document was printed with: pandoc reads the value as Markdown, takes a backslash
#: before a letter for TeX, and the Word writer leaves TeX out wherever it is not maths. A
#: command takes its braces with it, so the second loses two words. `check` passed each.
TEX_IN_PAPER_YAML = {
    "a Greek letter in the title": (
        "title: ",
        "title: 'IFN-" + chr(92) + "gamma release assays'",
        "IFN-release assays",
    ),
    "words in a command's braces in the short title": (
        "short_title: ",
        "short_title: 'Injury " + chr(92) + "textit{in vivo} and after'",
        "Injury  and after",
    ),
    "a keyword": (
        "  - hepatotoxicity",
        "  - TNF" + chr(92) + "alpha signalling",
        "TNFsignalling",
    ),
}


@pytest.mark.parametrize("case", list(TEX_IN_PAPER_YAML))
def test_tex_outside_dollar_signs_in_a_title_or_a_keyword_is_caught(
    case: str, project: Path, monkeypatch
) -> None:
    from manuscript_guard.contracts import project as contract

    starts, written, _printed = TEX_IN_PAPER_YAML[case]
    paper = project / "paper.yaml"
    lines = paper.read_text(encoding="utf-8").split(chr(10))
    (at,) = [index for index, line in enumerate(lines) if line.startswith(starts)]
    lines[at] = written
    paper.write_text(chr(10).join(lines), encoding="utf-8")

    with monkeypatch.context() as before:  # as the tool was before the rule: a pass
        before.setattr(contract, "outside_maths", lambda text, **how: None)
        assert gate_report(project).ok

    report = gate_report(project)
    assert codes(report) == {"schema-violation"}
    (finding,) = report.failures
    assert "stands outside dollar signs, and the document is printed without it" in finding.message


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("case", list(TEX_IN_PAPER_YAML))
def test_what_the_document_was_printed_as_is_what_the_table_says(case: str) -> None:
    """The corruption is pandoc's reading, so the table is held to pandoc: each value, as
    the build writes it into its header, and the words pandoc keeps of it."""
    import subprocess

    _starts, written, printed = TEX_IN_PAPER_YAML[case]
    value = yaml.safe_load(written.strip().removeprefix("- "))
    value = value if isinstance(value, str) else next(iter(value.values()))
    header = "---" + chr(10) + "title: " + json.dumps(value) + chr(10) + "---" + chr(10)
    shown = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "json"],
        input=header.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    inlines = json.loads(shown.stdout)["meta"]["title"]["c"]
    words = "".join(
        inline["c"] if inline["t"] == "Str" else " " if inline["t"] == "Space" else ""
        for inline in inlines
    )
    assert words == printed


# --------------------------------------------------------------------------------------
# TeX in the text that the Word writer leaves out, and a bound number with it
# --------------------------------------------------------------------------------------

_HELD = "The database contained {{results.cohort.n_reports}} reports, of which"
#: The page break the warning gives: a code span of Word's own, in a paragraph of its own.
_PAGE_BREAK = '`<w:r><w:br w:type="page"/></w:r>`{=openxml}'
_NEEDS_PANDOC = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


def _results_with(project: Path, sentence: str) -> str:
    """The example's Results with the sentence that holds its first bound number replaced,
    and that number as the document prints it."""
    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    assert text.count(_HELD) == 1
    source.write_text(text.replace(_HELD, sentence), encoding="utf-8")
    return load_namespace(load_project(project)[0])[0]["results.cohort.n_reports"].display


def _printed(document: Path) -> str:
    """The words of a built document, paragraph by paragraph."""
    with zipfile.ZipFile(document) as docx:
        body = docx.read("word/document.xml").decode("utf-8")
    return chr(10).join(_shown(p) for p in re.findall(r"<w:p[ >].*?</w:p>", body, re.DOTALL))


def _refused(project: Path, capsys, sentence: str) -> tuple[str, str]:
    """`check` fails with `sentence`, a build stops at the check, and a build that skips the
    check is refused with the same sentence and leaves no document: what `check` printed,
    and what the build that skipped it said."""
    from manuscript_guard.cli import main

    capsys.readouterr()
    assert main(["check", str(project)]) == 1
    checked = capsys.readouterr().out
    assert sentence in checked, checked

    assert main(["build", str(project), "--offline"]) == 1
    assert "not building" in capsys.readouterr().out

    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    said = capsys.readouterr().err
    assert sentence in said, said
    assert not list((project / "build").glob("manuscript*.docx"))
    return checked, said


@_NEEDS_PANDOC
def test_a_bound_number_under_a_page_break_is_not_lost_through_check_and_the_build(
    project: Path, capsys
) -> None:
    """Pandoc folds digits that open a line into a command above it that takes no braces:
    `\\newpage` over `{{results.cohort.n_reports}} reports were in the database` is the
    TeX `\\newpage` and the number, and the paragraph is printed from ` reports` on.
    Every gate that reads the sources had counted the number as printed. A page break
    alone loses no word and only does nothing in Word; this one takes a number with it, and
    `check` and the build refuse it."""
    count = _results_with(
        project,
        chr(92) + "newpage" + chr(10)
        + "{{results.cohort.n_reports}} reports were in the database, of which",
    )
    assert gate_report(project).ok, "the gates read the sources, where the number is bound"

    checked, said = _refused(
        project, capsys, f"pandoc reads as TeX `{chr(92)}newpage` to `{count}` (main.md:"
    )
    assert "does nothing in a Word document" not in checked + said


@_NEEDS_PANDOC
def test_a_bound_number_after_a_tex_command_is_not_lost_through_check_and_the_build(
    project: Path, capsys
) -> None:
    """`The database contained \\approx {{results.cohort.n_reports}} reports` passed
    `check` and the build, and the document read "The database contained  reports": pandoc
    takes the number for the command's argument, and the Word writer leaves the TeX out.
    The gates that read the sources still pass it. The build asks pandoc, and refuses;
    and so does `check`, which asks pandoc too."""
    from manuscript_guard.cli import main

    count = _results_with(
        project, _HELD.replace("contained ", "contained " + chr(92) + "approx ")
    )
    assert gate_report(project).ok, "the gates read the sources, where the number is bound"

    source = main_md(project).read_text(encoding="utf-8")
    line = source[: source.index(chr(92) + "approx")].count(chr(10)) + 1

    # The line of the file, where the build's own text has no front matter and holds the
    # tables: it was named four lines up.
    checked, said = _refused(
        project, capsys, f"pandoc reads as TeX `{chr(92)}approx {count}` (main.md:{line})"
    )
    for told in (checked, said):
        assert "the Word writer leaves" in told
        assert "code span marked `{=latex}`" in told
        assert "a block" not in told, "check fails a raw block from drafting on"
    assert main(["submit", str(project), "--offline"]) == 1
    assert main(["submit", str(project), "--offline", "--skip-checks"]) == 1


@_NEEDS_PANDOC
def test_the_same_sentence_with_its_sign_as_maths_is_built_with_the_number(project: Path) -> None:
    from manuscript_guard.cli import main

    count = _results_with(
        project, _HELD.replace("contained ", "contained $" + chr(92) + "approx$ ")
    )
    assert main(["build", str(project), "--offline"]) == 0
    assert f"{count} reports, of which" in _printed(project / "build" / "manuscript.docx")


@_NEEDS_PANDOC
def test_a_page_break_alone_builds_and_the_build_says_it_does_nothing_in_word(
    project: Path, capsys
) -> None:
    """A bare page break built before the refusal and loses no word, so it still builds:
    the build warns that Word shows nothing for it, and says how a page break is written."""
    from manuscript_guard.cli import main

    count = _results_with(project, chr(92) + "newpage" + chr(10) + chr(10) + _HELD)
    capsys.readouterr()

    assert main(["build", str(project), "--offline"]) == 0
    said = capsys.readouterr().out
    assert f"`{chr(92)}newpage`" in said and "does nothing in a Word document" in said, said
    assert _PAGE_BREAK in said, "how a page break is written for Word"
    assert f"The database contained {count} reports" in _printed(
        project / "build" / "manuscript.docx"
    )


@_NEEDS_PANDOC
def test_the_page_break_the_warning_gives_passes_check_and_breaks_the_page(
    project: Path, capsys
) -> None:
    """The warning named a block marked `{=openxml}`, and so did the refusal for
    `{=latex}`. G2 fails a raw block from `drafting` on, so an author who followed either
    was stopped by `check`. As a code span it passes, and Word gets its page break."""
    from manuscript_guard.cli import main

    _results_with(project, _PAGE_BREAK + chr(10) + chr(10) + _HELD)
    assert main(["check", str(project)]) == 0, capsys.readouterr().out
    assert main(["build", str(project), "--offline"]) == 0
    assert "does nothing" not in capsys.readouterr().out
    with zipfile.ZipFile(project / "build" / "manuscript.docx") as docx:
        body = docx.read("word/document.xml").decode("utf-8")
    assert body.count('<w:br w:type="page"') == 1


@_NEEDS_PANDOC
def test_a_bound_number_in_the_braces_of_a_space_is_not_lost_through_check_and_the_build(
    project: Path, capsys
) -> None:
    """A length was a number with a unit, or with any command after it. So
    `\\hspace{ {{results.cohort.n_reports}}\\reports}` passed for a layout command: `check`
    passed, the build warned that it does nothing in a Word document and made one, and
    the document read "The database contained  reports", two spaces where the number
    was. The command in a length has to be one that is a length, and this is refused with
    the rest."""

    opened = "contained " + chr(92) + "hspace{ "
    count = _results_with(
        project,
        _HELD.replace("contained ", opened).replace(" reports,", chr(92) + "reports} reports,"),
    )
    assert opened + "{{results.cohort.n_reports}}" in main_md(project).read_text(encoding="utf-8")
    assert gate_report(project).ok, "the gates read the sources, where the number is bound"

    checked, said = _refused(
        project, capsys, f"pandoc reads as TeX `{chr(92)}hspace{{ {count}{chr(92)}reports}}`"
    )
    assert "does nothing in a Word document" not in checked + said


@_NEEDS_PANDOC
def test_a_bound_number_in_a_citations_brackets_is_not_lost_through_check_and_the_build(
    project: Path, capsys
) -> None:
    """The same sentence inside a citation's brackets: `[of \\approx
    {{results.cohort.n_reports}} reports, see @key]` passed `check` and the build, and the
    document read "(of  reports, see Fictional and Fictional 2021)". Pandoc keeps what
    stands before and after the key apart from the rest of its reading, and the build did
    not look there."""

    source = main_md(project)
    text = source.read_text(encoding="utf-8")
    cited = "[@fictionalHepaticCohort2021], and a disproportionality"
    assert text.count(cited) == 1
    source.write_text(
        text.replace(
            cited,
            "[of " + chr(92) + "approx {{results.cohort.n_reports}} reports, see "
            "@fictionalHepaticCohort2021], and a disproportionality",
        ),
        encoding="utf-8",
    )
    count = load_namespace(load_project(project)[0])[0]["results.cohort.n_reports"].display
    assert gate_report(project).ok, "the gates read the sources, where the number is bound"

    _refused(project, capsys, f"pandoc reads as TeX `{chr(92)}approx {count}`")


@_NEEDS_PANDOC
def test_tex_in_the_supplement_stops_the_build_and_leaves_no_old_copy(
    project: Path, capsys
) -> None:
    from manuscript_guard.cli import main

    assert main(["build", str(project), "--offline"]) == 0
    old = project / "build" / "supplementary.docx"
    assert old.exists()
    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    text = supplement.read_text(encoding="utf-8")
    supplement.write_text(
        f"{text}{chr(10)}Codes were matched {chr(92)}textit{{a priori}} only.{chr(10)}", "utf-8"
    )
    capsys.readouterr()

    assert main(["build", str(project), "--offline", "--skip-checks"]) == 1
    said = capsys.readouterr().err
    assert "the supplement is not built" in said
    assert f"`{chr(92)}textit{{a priori}}`" in said
    assert "S1_code_lists.md:" in said
    assert not old.exists()


@_NEEDS_PANDOC
def test_import_takes_back_a_document_built_before_tex_in_the_text_was_refused(
    project: Path, monkeypatch, capsys
) -> None:
    """`import` builds the source again to compare the returned document with, and makes
    that build without asking pandoc how it reads the text. A document sent with its TeX
    left out, before the build refused it, still comes back."""
    from manuscript_guard.build import reading
    from manuscript_guard.cli import main

    _results_with(project, _HELD.replace("contained ", "contained " + chr(92) + "approx "))
    with monkeypatch.context() as before:  # as `check` and the build were before the refusal
        before.setattr(reading, "_tex_left_out", lambda *args: None)
        before.setattr(reading, "tex_read", lambda source, pandoc, limit=None: ([], []))
        assert main(["build", str(project), "--offline"]) == 0
    sent = project / "build" / "manuscript.docx"
    assert "The database contained  reports" in _printed(sent)
    capsys.readouterr()

    assert main(["import", str(sent), str(project)]) == 0
    assert "nothing came back" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# What a plan for each study design says, and the guideline its paper follows
# --------------------------------------------------------------------------------------


def _paper_has(root: Path, **settings) -> None:
    paper = root / "paper.yaml"
    document = yaml.safe_load(paper.read_text(encoding="utf-8"))
    document.update(settings)
    paper.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _plan_asked(root: Path) -> list[str]:
    """The sections G12 says the plan does not have."""
    from manuscript_guard.gates import check_design

    project, report = load_project(root)
    assert report.ok, report.render()
    return sorted(f.message.removeprefix("the plan says nothing about ")
                  for f in check_design(project).findings
                  if f.code == "plan-section-missing")  # fmt: skip


def test_a_plan_is_asked_for_what_its_design_needs(project: Path) -> None:
    """Item 45: G12 asked every plan for the same seven sections, so a disproportionality
    analysis with no case definition or comparator, or a trial with no estimand, passed."""
    assert _plan_asked(project) == []
    _paper_has(project, study_type="disproportionality")
    # The example's plan has "Sensitivity analyses", and none of the others.
    assert _plan_asked(project) == ["case definition", "comparator", "deduplication", "measure"]
    _paper_has(project, study_type="trial")
    assert _plan_asked(project) == ["estimand", "interim analyses", "missing data",
                                    "randomisation"]  # fmt: skip


def test_a_section_the_design_needs_says_where_it_comes_from(project: Path) -> None:
    from manuscript_guard.gates import check_design

    _paper_has(project, study_type="trial")
    project_, _ = load_project(project)
    hints = {f.message: f.hint for f in check_design(project_).findings}
    assert "ICH E9(R1)" in hints["the plan says nothing about estimand"]


@pytest.mark.parametrize(
    ("design", "renamed", "still_asked"),
    [
        # Round 1 of #292: "Case-control" holds "case" and "control" as words of their own.
        ("case-control", "## Case-control design", ["cases", "controls"]),
        # Round 2: and so does any other joiner, the en dash of a typeset protocol first.
        ("case-control", "## Case\N{EN DASH}control design", ["cases", "controls"]),
        ("case-control", "## Case control design", ["cases", "controls"]),
        ("case-control", "## Case/control design", ["cases", "controls"]),
        ("disproportionality", "## Background\n\nWhy this.\n\n## Disproportionality analysis",
         ["comparator", "measure"]),
        ("disproportionality", "## Outcome measures", ["comparator", "measure"]),
        # A further round: any "measures" heading the plan has for something else.
        ("disproportionality", "## Data quality measures\n\nDuplicates removed.",
         ["comparator", "measure"]),
        ("disproportionality", "## 4. Bias mitigation measures", ["comparator", "measure"]),
    ],
)
def test_a_heading_every_plan_has_is_not_a_design_s_section(
    project: Path, design: str, renamed: str, still_asked: list[str]
) -> None:
    _paper_has(project, study_type=design)
    plan = project / "design" / "plan.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace("## Design", renamed, 1),
                    encoding="utf-8")  # fmt: skip
    asked = _plan_asked(project)
    assert all(name in asked for name in still_asked), asked


def test_a_design_s_section_written_is_found(project: Path) -> None:
    _paper_has(project, study_type="disproportionality")
    plan = project / "design" / "plan.md"
    plan.write_text(
        plan.read_text(encoding="utf-8")
        + "\n## Deduplication\n\nReports sharing a case identifier are kept once.\n"
        + "\n## Case definition\n\nHepatic injury by its MedDRA terms, as coded.\n"
        + "\n## Comparator\n\nEvery other report in the database.\n"
        + "\n## Measure\n\nThe reporting odds ratio, a signal where its lower bound is above 1.\n",
        encoding="utf-8",
    )
    assert _plan_asked(project) == []


@pytest.mark.parametrize(
    "heading",
    ["## 3. Disproportionality measures", "## 2.4 Measure", "## Choice of measure",
     "## Primary disproportionality measure", "## Measures of disproportionality"],
)  # fmt: skip
def test_a_measure_s_section_numbered_or_qualified_is_found(project: Path, heading: str) -> None:
    """Round 2 of #292: a section number, or a word before "measure", hid the section."""
    _paper_has(project, study_type="disproportionality")
    plan = project / "design" / "plan.md"
    plan.write_text(
        plan.read_text(encoding="utf-8")
        + "\n## Deduplication\n\nReports sharing a case identifier are kept once.\n"
        + "\n## Case definition\n\nHepatic injury by its MedDRA terms, as coded.\n"
        + "\n## Comparator\n\nEvery other report in the database.\n"
        + f"\n{heading}\n\nThe reporting odds ratio, a signal where its lower bound is above 1.\n",
        encoding="utf-8",
    )
    assert _plan_asked(project) == []


def _guideline_said(root: Path) -> list[str]:
    from manuscript_guard.gates import check_reporting

    project, _ = load_project(root)
    return [f.message for f in check_reporting(project).findings
            if f.code == "reporting-guideline-for-design"]  # fmt: skip


@pytest.mark.parametrize(
    ("design", "guidelines", "said"),
    [
        ("cohort", ["STROBE"], False),
        ("cohort", ["RECORD-PE"], False),
        ("cohort", [], True),
        ("cohort", ["CONSORT"], True),
        ("prediction-model", ["TRIPOD+AI"], False),
        ("disproportionality", ["READUS-PV"], False),
        (None, [], False),
    ],
)
def test_a_paper_whose_design_has_none_of_its_guidelines_is_told(
    project: Path, design: str | None, guidelines: list[str], said: bool
) -> None:
    """The same table names the guidelines a design is reported with."""
    if design:
        _paper_has(project, study_type=design)
    _paper_has(project, reporting_guideline=guidelines)
    assert bool(_guideline_said(project)) is said


def test_the_guidelines_a_paper_declares_are_named_as_it_writes_them(project: Path) -> None:
    """Round 1 of #292: the message named them in the capitals they are compared in."""
    _paper_has(project, study_type="cohort")
    _paper_has(project, reporting_guideline=["Consort"])
    [said] = _guideline_said(project)
    assert said.endswith("and paper.yaml declares Consort")


# --------------------------------------------------------------------------------------
# A number written with pandoc's subscript and superscript signs
# --------------------------------------------------------------------------------------

#: A number typed by hand in each shape the signs allow, and the atom G2 reports for it:
#: the example's first bound count, and small numbers, which are the ones that can pass
#: for an exponent or complete a term. A name is matched against the terms with the signs
#: of its subscripts and superscripts taken out, and an exponent on a unit is read as `m²`
#: is, as typography: neither may take a number with it.
_TYPED_WITH_SIGNS = {
    "between the signs of a superscript": ("^{n}^ reports", "^{n}^"),
    "with a subscript after it": ("{n}~total~ reports", "{n}~total"),
    "as an exponent on a letter": ("n^{n}^ reports", "n^{n}^"),
    "as an exponent on a unit": ("m^{n}^ reports", "m^{n}^"),
    "hard against a built-in name": ("HbA~1c~{n} reports", "HbA~1c~{n}"),
    "as a power of ten": ("4 × 10^3^ reports", "10^3^"),
    # The bounds of the exponent: one digit, on a word that is longer than a unit.
    "one digit on a word of four letters": ("reports in year^3^", "year^3^"),
    "one digit on a longer word": ("reports in period^3^", "period^3^"),
    "two digits on a unit": ("reports per m^25^", "m^25^"),
    # A number after a tilde nothing closes, hard against a word that ends as a built-in
    # term does: `ph2` holds `h2`, `hr2` holds `r2`, `increased2` holds `d2`.
    "an effect after a tilde": ("reports at about HR~2", "HR~2"),
    "a pH after a tilde": ("reports at pH~2", "pH~2"),
    "a fold change after a tilde": ("reports, increased~2-fold", "increased~2-fold"),
    "the upper end of a range": ("reports in 1 week~2 weeks", "week~2"),
    # The same where the letter before the tilde is the whole of the term's: `h2`.
    "the upper end of a range in hours": ("reports with a lag of 1 h~2 h", "h~2"),
    # A citation's number after a word that ends as a built-in term does.
    "a citation's number in a superscript": ("reports of cancer^2^", "cancer^2^"),
}


@pytest.mark.parametrize("case", list(_TYPED_WITH_SIGNS))
def test_a_number_written_with_script_signs_is_still_reported(project: Path, case: str) -> None:
    """`HbA~1c~` is matched as `HbA1c` and `kg/m^2^` is read as `kg/m²`. A number typed by
    hand in the same signs is an unbound number like any other."""
    count = load_namespace(load_project(project)[0])[0]["results.cohort.n_reports"].display
    typed, atom = (part.format(n=count) for part in _TYPED_WITH_SIGNS[case])
    _results_with(project, _HELD.replace("{{results.cohort.n_reports}} reports", typed))

    report = gate_report(project)

    assert not report.ok
    assert any(
        failure.code == "unclassified-number" and failure.message.startswith(f"{atom!r} ")
        for failure in report.failures
    ), [failure.message for failure in report.failures]


# --------------------------------------------------------------------------------------
# G14, the vocabulary: the example keeps to "hepatic injury". Each test below lets another
# word for it into the text, the way a co-author's paragraph or a pasted sentence does, and
# the gate has to report that word where it stands.
# --------------------------------------------------------------------------------------


def vocabulary_findings(root: Path) -> list[tuple[str, int, str]]:
    from manuscript_guard.gates import check_language

    report = check_language(load_project(root)[0])
    assert report.ok, "G14 warns; it does not fail"
    return sorted(
        (f.code, f.line, f.message)
        for f in report.findings
        if not f.code.startswith("abbreviation-")
    )


def test_the_example_keeps_to_its_term(project: Path) -> None:
    """The baseline for what follows."""
    assert vocabulary_findings(project) == []


def test_a_co_author_s_other_word_for_the_outcome_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    assert old in text, "the fixture changed under this test"
    edited = text.replace(old, old + " Liver injury is also under-reported in general.")
    main_md(project).write_text(edited, encoding="utf-8")
    assert vocabulary_findings(project) == [
        (
            "term-avoided",
            line_of(edited, "Liver injury is also"),
            "'liver injury' is used once; this paper's term is 'hepatic injury'",
        )
    ]


def test_a_heading_renamed_with_the_other_word_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    edited = text.replace("# Discussion\n", "# Liver damage in context\n")
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    assert vocabulary_findings(project) == [
        (
            "term-avoided",
            line_of(edited, "# Liver damage in context"),
            "'liver damage' is used once; this paper's term is 'hepatic injury'",
        )
    ]


def test_find_and_replace_of_the_term_is_caught_everywhere_it_went(project: Path) -> None:
    """Every "hepatic injury" turned into "liver injury": one finding, at the first in the
    text, with the count of them all, the supplement's included. The one in the front
    matter's title is not counted: the build prints its title from `paper.yaml`."""
    from manuscript_guard.text.masking import front_matter_end

    changed = 0
    for path in sorted((project / "manuscript").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        edited = re.sub(r"(?i)hepatic(\s+)injury", r"liver\1injury", text)
        changed += len(re.findall(r"(?i)hepatic\s+injury", text[front_matter_end(text) :]))
        path.write_text(edited, encoding="utf-8")
    assert changed > 5
    ((code, line, message),) = vocabulary_findings(project)
    assert code == "term-avoided"
    assert f"is used {changed} times" in message
    edited = main_md(project).read_text(encoding="utf-8")
    body = front_matter_end(edited)
    assert line == edited.count("\n", 0, edited.index("liver injury", body)) + 1


def test_the_word_in_a_citation_key_or_a_comment_is_not_the_manuscript_s(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(
        old,
        old + " <!-- say liver injury here? --> See also [@liver-injury-cohort2020].",
    )
    main_md(project).write_text(edited, encoding="utf-8")
    assert vocabulary_findings(project) == []


# --------------------------------------------------------------------------------------
# G14, the spelling: the example declares British English and is written in it. Each test
# below lets the other spelling into the text the way it gets there: a co-author's
# sentence, a spell-checker set to the other English, a paragraph pasted from another
# paper, a line of paper.yaml changed with nobody respelling the text. The gate has to say
# which word, and where.
# --------------------------------------------------------------------------------------


def spelling_findings(root: Path) -> list[tuple[str, int | None, str]]:
    from manuscript_guard.gates import check_language

    report = check_language(load_project(root)[0])
    assert report.ok, "G14 warns; it does not fail"
    return [
        (f.code, f.line, f.message) for f in report.findings if f.code.startswith("spelling-")
    ]


def test_the_example_is_spelt_as_it_declares(project: Path) -> None:
    """The baseline for what follows."""
    assert spelling_findings(project) == []


# Prose in a script the gates do not read. A Chinese sentence with every result bound still
# failed G2, and one that wrote its numbers in Chinese numerals had nothing found in it: the
# gates read English, and nothing said so.

_CHINESE = (
    "结果见表1，比值比为{{results.ror.point}}（95%置信区间{{results.ror.ci_low}}～"
    "{{results.ror.ci_high}}）。\n\n共纳入四千份报告，其中一百二十三份为肝损伤，比值比约为三点四。\n"
)


def _script_findings(root: Path) -> list:
    from manuscript_guard.gates import check_language

    report = check_language(load_project(root)[0])
    return [f for f in report.findings if f.code == "script-not-read"]


def test_prose_in_a_script_the_gates_do_not_read_is_said(project: Path) -> None:
    main = main_md(project)
    main.write_text(main.read_text(encoding="utf-8") + "\n" + _CHINESE, encoding="utf-8")
    (found,) = _script_findings(project)
    assert found.severity == "warn"
    assert "characters of prose" in found.message and "Han (" in found.message
    assert "numbers written in it" in found.message


def test_a_title_quoted_in_another_script_warns_and_fails_nothing(project: Path) -> None:
    from manuscript_guard.cli import _run_gates

    main = main_md(project)
    text = main.read_text(encoding="utf-8").replace(
        "Several limitations follow from the design.",
        "Several limitations follow from the design, as the agency's own report, "
        "「医薬品安全性情報」, says.",
        1,
    )
    main.write_text(text, encoding="utf-8")
    (found,) = _script_findings(project)
    assert "Han" in found.message and "Hiragana" not in found.message
    report, *_ = _run_gates(project, stage="submission")
    assert "script-not-read" not in codes(report)


def test_a_co_author_s_sentence_in_the_other_spelling_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    assert old in text, "the fixture changed under this test"
    edited = text.replace(old, old + " The color of a tablet is rarely recorded.")
    main_md(project).write_text(edited, encoding="utf-8")
    assert spelling_findings(project) == [
        (
            "spelling-variant",
            line_of(edited, "The color of a tablet"),
            "'color' is the American spelling of 'colour', used once; this paper is in "
            "British English",
        )
    ]


def test_a_word_respelt_by_a_spell_checker_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    assert text.count("We analysed") == 1, "the fixture changed under this test"
    edited = text.replace("We analysed", "We analyzed")
    main_md(project).write_text(edited, encoding="utf-8")
    assert spelling_findings(project) == [
        (
            "spelling-variant",
            line_of(edited, "We analyzed"),
            "'analyzed' is the American spelling of 'analysed', used once; this paper is in "
            "British English",
        )
    ]


def test_the_declared_english_changed_and_the_text_left_as_it_was_is_caught(
    project: Path,
) -> None:
    """A journal that wants American spelling: the line in paper.yaml is changed, and the
    manuscript still says "analysed"."""
    path = project / "paper.yaml"
    paper = path.read_text(encoding="utf-8")
    assert paper.count("english_variant: en-GB") == 1, "the fixture changed under this test"
    path.write_text(paper.replace("english_variant: en-GB", "english_variant: en-US"), "utf-8")
    text = main_md(project).read_text(encoding="utf-8")
    assert spelling_findings(project) == [
        (
            "spelling-variant",
            line_of(text, "We analysed"),
            "'analysed' is the British spelling of 'analyzed', used once; this paper is in "
            "American English",
        )
    ]


def test_a_second_ending_brought_in_by_a_co_author_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(
        old,
        old + " Reports were categorised and prioritised by region.\n\nThey were then "
        "summarized by quarter.",
    )
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    assert spelling_findings(project) == [
        (
            "spelling-mixed",
            line_of(edited, "They were then summarized"),
            "both endings are used: -ise 2 times ('categorised', 'prioritised') and -ize "
            "once ('summarized')",
        )
    ]


def test_a_paragraph_pasted_from_a_paper_in_the_other_english_is_caught(project: Path) -> None:
    """Five spellings of the other usage against the example's one of its own: the gate
    says the manuscript is not in the English it declares, names every word and what to
    write, and points at paper.yaml, since it cannot know which of the two is the slip."""
    supplement = project / "manuscript" / "supplementary" / "S1_code_lists.md"
    text = supplement.read_text(encoding="utf-8")
    supplement.write_text(
        text + "\nThe color of the tumor, the anemia, the edema and the hemoglobin level "
        "were not coded.\n",
        encoding="utf-8",
    )
    from manuscript_guard.gates import check_language

    report = check_language(load_project(project)[0])
    (finding,) = [f for f in report.findings if f.code.startswith("spelling-")]
    assert finding.code == "spelling-not-as-declared"
    assert finding.path == project / "paper.yaml"
    assert finding.message.startswith("5 words are in American spelling (5 different ones)")
    for word, instead in (
        ("color", "colour"),
        ("tumor", "tumour"),
        ("anemia", "anaemia"),
        ("edema", "oedema"),
        ("hemoglobin", "haemoglobin"),
    ):
        assert f"{word} ({instead}, once)" in finding.hint


def test_a_name_a_quotation_and_a_citation_key_in_the_other_spelling_are_left_alone(
    project: Path,
) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(
        old,
        old + " The World Health Organization keeps the database [@color-atlas2020], and "
        "its guidance says:\n\n> Report the color and the labeling of the product.\n\n"
        "<!-- check the color of the tablet -->",
    )
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    assert spelling_findings(project) == []


# --------------------------------------------------------------------------------------
# G14, the notation: the example joins the bounds of its intervals with "to", sets "%"
# against its number and states no P value with a sign. Each test below lets another way
# of writing one of these into the text, as a co-author's sentence or a retyped line does,
# and the gate has to say which, and where.
# --------------------------------------------------------------------------------------


def notation_findings(root: Path) -> list[tuple[str, int | None, str]]:
    from manuscript_guard.gates import check_language

    report = check_language(load_project(root)[0])
    assert report.ok, "G14 warns; it does not fail"
    return [
        (f.code, f.line, f.message) for f in report.findings if f.code.startswith("notation-")
    ]


def test_the_example_writes_its_statistics_one_way(project: Path) -> None:
    """The baseline for what follows."""
    assert notation_findings(project) == []


def test_an_interval_retyped_with_a_hyphen_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "{{results.ror.ci_low}} to {{results.ror.ci_high}})."
    assert text.count(old) == 1, "the fixture changed under this test"
    edited = text.replace(old, "{{results.ror.ci_low}}-{{results.ror.ci_high}}).")
    main_md(project).write_text(edited, encoding="utf-8")
    ((code, line, message),) = notation_findings(project)
    assert code == "notation-interval"
    assert line == line_of(edited, "{{results.ror.ci_low}}-{{results.ror.ci_high}}")
    assert message.startswith(
        "the two bounds of an interval are joined by a hyphen once, as in "
        "'CI {{\N{HORIZONTAL ELLIPSIS}}}-{{\N{HORIZONTAL ELLIPSIS}}}'; the manuscript "
        "joins them by 'to' "
    )


def test_a_co_author_s_p_value_in_another_notation_is_caught(project: Path) -> None:
    """The example writes "p-value" once, in lower case. A sentence with a capital P makes
    two forms, used as often, and the later one is shown."""
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    assert old in text, "the fixture changed under this test"
    edited = text.replace(old, old + " The association held (P={{results.ror.point}}).")
    main_md(project).write_text(edited, encoding="utf-8")
    assert notation_findings(project) == [
        (
            "notation-p-symbol",
            line_of(edited, "The association held"),
            "the P value is written 'P' once; the manuscript writes 'p' once",
        )
    ]


def test_a_percent_sign_set_off_by_a_space_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(old, old + " In {{results.case.pct_serious}} % the report was serious.")
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    ((code, line, message),) = notation_findings(project)
    assert code == "notation-percent"
    assert line == line_of(edited, "Several limitations")
    assert message.startswith(
        "'%' stands after a space once, as in '{{\N{HORIZONTAL ELLIPSIS}}} %'; the "
        "manuscript sets it against its number "
    )


def test_a_dose_typed_without_its_space_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(old, old + " A dose of 5mg daily is usual, and 10mg is not rare.")
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    assert notation_findings(project) == [
        (
            "notation-unit",
            line_of(edited, "Several limitations"),
            "a number runs into its unit 2 times: '5mg', '10mg'",
        )
    ]


def test_another_notation_in_a_comment_a_listing_or_a_quotation_is_not_the_manuscript_s(
    project: Path,
) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(
        old,
        old + " <!-- P=0.03, 95% CI 1-2, 5 %, 5mg --> The script sets `p=0.05`.\n\n"
        "> The label gives 5mg (95% CI 1-2; P=0.04) in 5 % of users.\n",
    )
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    assert notation_findings(project) == []

def test_a_sign_closed_up_by_a_co_author_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    assert old in text, "the fixture changed under this test"
    edited = text.replace(
        old,
        old + " Most reports were serious (n = 12) or fatal (n = 4)."
        "\n\nFew were neither (n=3).",
    )
    main_md(project).write_text(edited, encoding="utf-8")
    assert notation_findings(project) == [
        (
            "notation-sign-spacing",
            line_of(edited, "Few were neither"),
            "the sign after P or n has no space around it once, as in 'n=3'; the manuscript "
            "writes it with a space on each side of it 2 times, as in 'n = 12'",
        )
    ]


def test_a_space_typed_on_one_side_of_a_sign_is_caught(project: Path) -> None:
    text = main_md(project).read_text(encoding="utf-8")
    old = "Several limitations follow from the design."
    edited = text.replace(old, old + " Most reports were serious (n= 12).")
    assert edited != text
    main_md(project).write_text(edited, encoding="utf-8")
    assert notation_findings(project) == [
        (
            "notation-sign-spacing",
            line_of(edited, "Several limitations"),
            "the sign after P or n has a space on one side only once, as in 'n= 12'",
        )
    ]


# --------------------------------------------------------------------------------------
# A language pass that changed more than the words. `check` passes each of these: both
# bounds are bindings that resolve, a sentence with one citation fewer is a sentence, and a
# level of confidence is a number the conventions know. `manuscript-guard reworded` sees
# them, because it compares the text with what it was.
# --------------------------------------------------------------------------------------


def after_a_language_pass(project: Path, old: str, new: str):
    """The example's main text after one edit, compared with what it was. The edit is
    written to the file, so that the gates can be asked about it too."""
    from manuscript_guard.reworded import compare

    before = main_md(project).read_text(encoding="utf-8")
    assert before.count(old) == 1, "the fixture changed under this test"
    after = before.replace(old, new)
    main_md(project).write_text(after, encoding="utf-8")
    return after, compare(before, after, main_md(project))


def test_a_language_pass_that_wrote_one_bound_for_the_other_is_caught(project: Path) -> None:
    after, report = after_a_language_pass(
        project, "{{results.ror.ci_high}}; 90% CI", "{{results.ror.ci_low}}; 90% CI"
    )
    assert gate_report(project).ok, "the gates see nothing wrong with it"
    assert [(f.code, f.severity) for f in report.findings] == [
        ("fact-lost", "fail"),
        ("fact-new", "fail"),
    ]
    lost, new = report.findings
    assert lost.message.startswith("the binding {{results.ror.ci_high}} stood twice before")
    assert new.message.startswith("the binding {{results.ror.ci_low}} stands 3 times now")
    assert new.line == line_of(after, "{{results.ror.ci_low}}; 90% CI")


def test_a_language_pass_that_made_two_counts_change_places_is_shown(project: Path) -> None:
    """Two bounds that change places G2 reports itself, where they were emitted as one
    interval. Two counts in a sentence it cannot know apart."""
    after, report = after_a_language_pass(
        project,
        "Of {{results.cohort.n_reports}} reports, {{results.case.n_cases}} described",
        "Of {{results.case.n_cases}} reports, {{results.cohort.n_reports}} described",
    )
    assert gate_report(project).ok, "the gates see nothing wrong with it"
    (finding,) = report.findings
    assert (finding.code, finding.severity) == ("order-changed", "warn")
    assert finding.line == line_of(after, "Of {{results.case.n_cases}} reports")
    assert finding.message.endswith(
        "before the edit {{results.cohort.n_reports}}, {{results.case.n_cases}}; "
        "now {{results.case.n_cases}}, {{results.cohort.n_reports}}"
    )


def test_a_language_pass_that_dropped_a_citation_is_caught(project: Path) -> None:
    _after, report = after_a_language_pass(
        project,
        "{{lit.background.class_ror}} reported previously [@fictionalClassSignal2019], although",
        "{{lit.background.class_ror}} reported previously, although",
    )
    assert gate_report(project).ok, "the gates see nothing wrong with it"
    (finding,) = report.findings
    assert finding.code == "fact-lost"
    assert finding.message.startswith("the citation @fictionalClassSignal2019 stood twice")


def test_a_language_pass_that_retyped_a_level_of_confidence_is_caught(project: Path) -> None:
    after, report = after_a_language_pass(
        project, "; 90% CI {{results.ror.ci90_low}}", "; 95% CI {{results.ror.ci90_low}}"
    )
    assert gate_report(project).ok, "the gates see nothing wrong with it"
    lost, new = report.findings
    assert (lost.code, new.code) == ("fact-lost", "fact-new")
    # The Methods name the 90% interval too, so the number is one of two that stood.
    assert lost.message.startswith("the number '90' stood twice before the edit, on lines ")
    assert new.message.startswith("the number '95' stands ")
    assert new.line == line_of(after, "; 95% CI {{results.ror.ci90_low}}")


def test_a_language_pass_that_only_reworded_passes(project: Path) -> None:
    before = main_md(project).read_text(encoding="utf-8")
    edits = (
        ("The database contained", "The database held"),
        ("Reporting of hepatic injury was disproportionate for example-drug, with", "For "
         "example-drug, hepatic injury was reported out of proportion, with"),
        ("can reconstruct it.", "can work it out again."),
    )
    after = before
    for old, new in edits:
        assert old in after, "the fixture changed under this test"
        after = after.replace(old, new)
    from manuscript_guard.reworded import compare

    report = compare(before, after, main_md(project))
    assert not report.findings, report.render(project)
    assert report.counts["reworded_bindings"] > 10
    assert report.counts["reworded_citations"] > 2


# A language pass that kept every fact and changed what a sentence claims. `check` passes
# each, and so does the comparison of facts; the words of the claim are compared too, and
# each move is a warning, since a list of words cannot know whether it was meant.


def _claim_moved(project: Path, old: str, new: str, opening: str) -> tuple[str, str]:
    """What is said of the one edit, which is placed on the line its sentence opens on."""
    after, report = after_a_language_pass(project, old, new)
    assert gate_report(project).ok, "the gates see nothing wrong with it"
    (finding,) = report.findings
    assert finding.severity == "warn" and report.ok
    assert finding.line == line_of(after, opening)
    return finding.code, finding.message.split(": ", 1)[1]


def test_a_language_pass_that_made_a_disproportion_a_cause_is_shown(project: Path) -> None:
    assert _claim_moved(
        project,
        "Reporting of hepatic injury is disproportionate for example-drug",
        "Example-drug causes disproportionate reporting of hepatic injury",
        "Example-drug causes",
    ) == ("claim-stronger", "'causes' (causation) is new")


def test_a_language_pass_that_hedged_a_comparison_is_shown(project: Path) -> None:
    assert _claim_moved(
        project,
        "The reporting odds ratio observed here exceeds",
        "The reporting odds ratio observed here appears to exceed",
        "The reporting odds ratio observed here appears",
    ) == ("claim-weaker", "'appears' is new")


def test_a_language_pass_that_dropped_a_not_is_shown(project: Path) -> None:
    assert _claim_moved(
        project,
        "specifically has not been examined.",
        "specifically has been examined.",
        "Whether the signal extends",
    ) == ("claim-negation", "'not' is gone")


def test_a_language_pass_that_hedged_a_claim_and_widened_it_is_shown(project: Path) -> None:
    assert _claim_moved(
        project,
        "is the only population-level figure available",
        "may be the sole population-level figure available",
        "rate. The cohort",
    ) == ("claim-moved", "'may' is new; 'only' is gone")


# --------------------------------------------------------------------------------------
# Parameters: a threshold the analysis declares is bound in the Methods, and read by the code.
# --------------------------------------------------------------------------------------


def _analysis(root: Path) -> Path:
    return root / "analysis" / "01_disproportionality.py"


def _rerun_disproportionality(root: Path) -> None:
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, str(_analysis(root))], capture_output=True, text=True, cwd=root
    )
    assert out.returncode == 0, out.stderr


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8", newline="")


def test_the_example_reads_the_parameters_it_declares(project: Path) -> None:
    namespace, *_ = load_namespace(load_project(project)[0])
    for key in ("results.param.alpha", "results.param.signal.min_cases"):
        assert namespace[key].role == "parameter" and namespace[key].read is True, key
    assert namespace["results.software.python"].role == "software"


@pytest.mark.parametrize(
    ("binding", "typed"),
    [("{{results.param.alpha}}", "0.05"), ("{{results.param.signal.min_cases}}", "3")],
)
def test_a_declared_threshold_typed_in_the_methods_fails(
    project: Path, binding: str, typed: str
) -> None:
    """Typed, it passes as a convention, and stays one after the code has moved on."""
    _replace_once(main_md(project), binding, typed)
    report = gate_report(project)
    found = [f for f in report.failures if f.code == "typed-parameter"]
    assert len(found) == 1, report.render(project)
    text = main_md(project).read_text(encoding="utf-8").splitlines()
    assert text[found[0].line - 1][found[0].col - 1 :].startswith(typed), found
    assert binding in found[0].hint


def test_a_typed_software_version_fails(project: Path) -> None:
    namespace, *_ = load_namespace(load_project(project)[0])
    version = namespace["results.software.python"].display
    _replace_once(main_md(project), "{{results.software.python}}", version)
    assert "typed-software-version" in codes(gate_report(project))


def _coded_with(root: Path, **releases: str) -> None:
    """Coding dictionaries in the example's results, as `em.dictionary` declares them."""
    fragment = next((root / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    for name, release in releases.items():
        document["values"][f"dictionary.{name}"] = {
            "value": release, "display": release, "label": True, "role": "dictionary",
        }  # fmt: skip
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)


@pytest.mark.parametrize(
    ("sentence", "typed"),
    [
        ("Events were coded with MedDRA version 26.1.", ["'26.1'"]),
        # Round 1 of #287: with a "v" before it.
        ("Events were coded with MedDRA v26.1.", ["'26.1'"]),
        # Round 1 of #351: a "v" that ends a word is no "v" before the release.
        ("Events were coded with MedDRA Rev26.1.", []),
        ("Drugs were coded with WHODrug Global B3 March 2025.", ["'Global B3 March 2025'"]),
        ("Diagnoses were coded with ICD-10 2019 codes.", ["'2019'"]),
        ("Events were coded with MedDRA version {{results.dictionary.meddra}}.", []),
        ("Diagnoses were coded with ICD-10 {{results.dictionary.icd_10}} codes.", []),
        # The release alone is not the dictionary's: the name has to stand before it.
        ("Reports received in 2019 were read again.", []),
        # Not as part of a longer word: "matched" holds "atc".
        ("Reports were matched by hand in 2025 to each other.", []),
    ],
)
def test_a_typed_dictionary_release_fails_and_only_beside_its_name(
    project: Path, sentence: str, typed: list[str]
) -> None:
    _coded_with(project, meddra="26.1", whodrug="Global B3 March 2025", icd_10="2019",
                atc="2025")  # fmt: skip
    main = main_md(project)
    main.write_text(main.read_text(encoding="utf-8") + "\n" + sentence + "\n", encoding="utf-8")
    found = [f for f in gate_report(project).failures if f.code == "typed-dictionary-release"]
    assert [f.message.split(" is ")[0] for f in found] == typed
    assert all("{{results.dictionary." in f.hint for f in found)


def test_a_parameter_declared_and_never_read_fails(project: Path) -> None:
    """The example's signal criterion before this check: stated, declared, bound, and
    applied nowhere. Binding the threshold printed the right number for a step that was not
    there."""
    _replace_once(_analysis(project), "a >= min_cases and low > 1", "a >= 3 and low > 1")
    _rerun_disproportionality(project)
    found = [f for f in gate_report(project).failures if f.code == "parameter-unread"]
    assert [f.message.split()[0] for f in found] == ["param.signal.min_cases"]


def test_a_changed_parameter_reaches_the_methods_and_a_typed_copy_is_named(
    project: Path,
) -> None:
    """Bound, the Methods print the value the code now runs with. Typed, the copy no longer
    equals the parameter, so it is named as a threshold no parameter has."""
    _replace_once(_analysis(project), '"signal.min_cases", 3)', '"signal.min_cases", 5)')
    _rerun_disproportionality(project)
    namespace, *_ = load_namespace(load_project(project)[0])
    assert namespace["results.param.signal.min_cases"].display == "5"
    assert gate_report(project).ok

    _replace_once(main_md(project), "{{results.param.signal.min_cases}}", "3")
    report = gate_report(project)
    assert "typed-parameter" not in codes(report)
    assert [f.code for f in report.warnings if f.code == "threshold-undeclared"] == [
        "threshold-undeclared"
    ]


def test_a_parameter_equal_to_a_name_is_not_a_typed_threshold(project: Path) -> None:
    """`2 x 2` names a structure, whatever a parameter equals: only the conventions that
    hold in the Methods alone are thresholds an analysis chooses."""
    _replace_once(
        _analysis(project),
        '    min_cases = em.parameter("signal.min_cases", 3)\n',
        '    min_cases = em.parameter("signal.min_cases", 3)\n'
        '    rows_per_table = em.parameter("rows_per_table", 2)\n'
        "    assert rows_per_table == 2\n",
    )
    _rerun_disproportionality(project)
    assert "typed-parameter" not in codes(gate_report(project))


_CRITERION = "interval of the reporting odds ratio above 1."
_OMEGA = "\N{GREEK CAPITAL LETTER OMEGA}"
_AT_LEAST = "\N{GREATER-THAN OR EQUAL TO}"


def _declare_a_parameter_of(root: Path, value: int) -> None:
    _replace_once(
        _analysis(root),
        '    min_cases = em.parameter("signal.min_cases", 3)\n',
        '    min_cases = em.parameter("signal.min_cases", 3)\n'
        f'    other = em.parameter("other", {value})\n'
        f"    assert other == {value}\n",
    )
    _rerun_disproportionality(root)


@pytest.mark.parametrize(
    ("typed", "name", "digits", "threshold"),
    [
        ("I2 > 50%", "I2", 2, "50%"),
        (f"X2 {_AT_LEAST} 4", "X2", 2, "4"),
        (f"{_OMEGA}025 > 0", f"{_OMEGA}025", 25, "0"),
    ],
)
def test_the_name_of_a_statistic_is_no_threshold_whatever_its_digits_equal(
    project: Path, typed: str, name: str, digits: int, threshold: str
) -> None:
    """The convention that accepts a published criterion covers the statistic's name with
    its threshold. The name was read from its first digit: with a parameter of 2 declared,
    `I2` failed as a typed copy of it, and with none it was a threshold no parameter has.
    Only the threshold beside the name is one."""
    _declare_a_parameter_of(project, digits)
    _replace_once(main_md(project), _CRITERION, f"{_CRITERION} Another rule asked for {typed}.")
    report = gate_report(project)
    said = [
        (f.code, f.message.split()[0])
        for f in report.findings
        if f.code in ("typed-parameter", "threshold-undeclared")
    ]
    assert said == [("threshold-undeclared", repr(threshold))], report.render(project)
    assert not any(repr(name) in f.message for f in report.findings), report.render(project)


def test_a_threshold_typed_against_the_name_of_its_statistic_is_still_read(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`I2>50%` is one atom. Its name states nothing and its 50 is the threshold, as the
    0.05 of `P<0.05` is: a declared parameter of 50 makes it a typed copy, in `check` and
    in `explain`, and the name alone is passed by both."""
    from manuscript_guard.cli import main

    _declare_a_parameter_of(project, 50)
    _replace_once(
        main_md(project),
        _CRITERION,
        f"{_CRITERION} One rule asked for I2>50% and another for I2 > 75%.",
    )
    report = gate_report(project)
    said = [
        (f.code, f.message.split()[0])
        for f in report.findings
        if f.code in ("typed-parameter", "threshold-undeclared")
    ]
    assert said == [("typed-parameter", "'I2>50%'"), ("threshold-undeclared", "'75%'")]
    typed = next(f for f in report.failures if f.code == "typed-parameter")
    assert "{{results.param.other}}" in typed.hint

    main(["explain", str(main_md(project))])
    rows = {line.split()[2]: line for line in capsys.readouterr().out.splitlines()}
    assert rows["I2>50%"].startswith("FAIL") and "typed: write" in rows["I2>50%"]
    assert rows["I2"].startswith("ok") and "typed" not in rows["I2"], rows["I2"]


@pytest.mark.parametrize(
    ("atom", "figure", "states"),
    [
        # A figure typed against a letter is part of a name.
        ("I2", None, None),
        ("X2", None, None),
        ("R2", None, None),
        ("IC025", None, None),
        ("EB05", None, None),
        ("\N{GREEK SMALL LETTER CHI}2", None, None),
        (f"{_OMEGA}025", None, None),
        ("omega025", None, None),
        # A figure after anything else is the atom's own.
        ("0.05", "0.05", 0.05),
        (".05", ".05", 0.05),
        ("P<0.05", "0.05", 0.05),
        ("p<.05", ".05", 0.05),
        ("n=3", "3", 3),
        (f"{_AT_LEAST}3", "3", 3),
        ("=3", "3", 3),
        ("50%", "50%", 50),
        ("alpha=0.05", "0.05", 0.05),
        ("\N{GREEK SMALL LETTER ALPHA}=0.05", "0.05", 0.05),
        ("SMD<0.1", "0.1", 0.1),
        ("PRR>2", "2", 2),
        ("1,000", "1,000", 1000),
        # After a name in the same atom, too.
        ("I2>50%", "50%", 50),
        ("IC025>0", "0", 0),
        (f"\N{GREEK SMALL LETTER CHI}2{_AT_LEAST}4", "4", 4),
        # A figure of its own that is not one number: a threshold still, and equal to none.
        ("1:1", "1:1", None),
        # The limit DESIGN.md writes down: a threshold typed against the word before it.
        ("power80%", None, None),
        ("caliper0.2", None, None),
    ],
)
def test_a_figure_typed_against_a_letter_is_part_of_a_name(
    atom: str, figure: str | None, states: float | None
) -> None:
    from manuscript_guard.gates.numbers import own_figure, stated_number

    assert own_figure(atom) == figure
    assert stated_number(atom) == states


def test_explain_says_a_declared_threshold_is_typed(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`explain` is what an author reads when a finding surprises them, so it fails what
    `check` fails, and names the binding to write."""
    from manuscript_guard.cli import main

    _replace_once(main_md(project), "{{results.param.alpha}}", "0.05")
    main(["explain", str(main_md(project))])
    row = next(line for line in capsys.readouterr().out.splitlines() if " 0.05 " in line)
    assert row.startswith("FAIL") and "typed: write {{results.param.alpha}}" in row, row


# --------------------------------------------------------------------------------------
# Models: the example's adjusted model is the model its variables call for.
# --------------------------------------------------------------------------------------


def _models_report(root: Path):
    from manuscript_guard.gates import check_models

    project, _ = load_project(root)
    _namespace, results, _literature, _loaded = load_namespace(project)
    return check_models(project, results)


def test_the_example_s_model_is_the_model_its_variables_call_for(project: Path) -> None:
    report = _models_report(project)
    assert not report.findings, report.render(project)
    assert report.counts["models"] == 1


def test_a_reference_moved_in_the_formula_and_not_in_the_declaration_fails(project: Path) -> None:
    _replace_once(_analysis(project), "C(sex, Treatment('F'))", "C(sex, Treatment('M'))")
    _rerun_disproportionality(project)
    found = [f for f in _models_report(project).failures if f.code == "model-reference"]
    assert [f.message for f in found] == [
        "model 'adjusted': 'sex' has reference 'M' in the fit and 'F' in its declaration"
    ]


def test_an_outcome_declared_continuous_under_a_logistic_model_fails(project: Path) -> None:
    _replace_once(
        _analysis(project),
        'em.variable("hepatic", "binary", label="hepatic injury", levels=[0, 1],',
        'em.variable("hepatic", "continuous", label="hepatic injury",',
    )
    _rerun_disproportionality(project)
    assert "model-outcome-kind" in {f.code for f in _models_report(project).failures}


_THE_FIT = "        fit = smf.glm(\n"

_BAND = """\
        codes = {"18-44": 1, "45-64": 2, "65-74": 3, "75+": 4}
        frame["band"] = frame["age_group"].map(codes).astype(float)
        frame.loc[0, "band"] = float("nan")
        em.variable("band", "ordinal", label="age band", levels=[1, 2, 3, 4], reference=1,
                    values=frame["band"])
"""


def test_a_reference_moved_on_a_category_of_float_codes_fails(project: Path) -> None:
    """An integer code with one missing value is a column of floats. Its columns in the fit
    are named "[T.2.0]" and its levels are written "2", so no reference was recorded for it
    and a reference other than the declared one passed."""
    _replace_once(_analysis(project), _THE_FIT, _BAND + _THE_FIT)
    _replace_once(
        _analysis(project), "C(age_group, Treatment('18-44'))", "C(band, Treatment(2))"
    )
    _rerun_disproportionality(project)
    assert sorted(f.message for f in _models_report(project).failures) == [
        "model 'adjusted': 'age band' has reference '2' in the fit and '1' in its declaration",
        "model 'adjusted': 1 of 4000 rows were dropped, for missing values, and the manuscript "
        "never says how many",
    ]


def test_a_variable_dichotomised_in_the_formula_is_not_held_to_its_levels(project: Path) -> None:
    """`I(age_group == '75+')` is true or false of each report, a binary term of its own. It
    was held to the four levels and the reference declared for the age group."""
    _replace_once(
        _analysis(project), "C(age_group, Treatment('18-44'))", "I(age_group == '75+')"
    )
    _rerun_disproportionality(project)
    report = _models_report(project)
    assert not report.findings, report.render(project)
    _replace_once(_analysis(project), "I(age_group == '75+')", "C(age_group == '75+')")
    _rerun_disproportionality(project)
    assert {f.code for f in _models_report(project).failures} == {
        "model-level-undeclared", "model-reference",
    }, "inside another call it is not known for a comparison"  # fmt: skip


def test_a_missing_value_of_a_nullable_column_is_not_a_level(project: Path) -> None:
    """pandas writes it NA, which is neither None nor a float: it was recorded as the level
    "<NA>", which no declaration has."""
    _replace_once(
        _analysis(project),
        'values=frame["exposed"])',
        'values=frame["exposed"].astype("Int64").mask(frame.index == 0))',
    )
    _rerun_disproportionality(project)
    report = _models_report(project)
    assert not report.findings, report.render(project)
    project_, _ = load_project(project)
    observed = load_namespace(project_)[1].variables["exposed"].observed
    assert observed == {"distinct": 2, "missing": 1, "levels": ["0", "1"]}


_THE_BOUNDS = "        bounds = fit.conf_int"

_GROUPED = """\
        table = frame.groupby(["age_group", "exposed"], as_index=False).agg(
            cases=("hepatic", "sum"), reports=("hepatic", "size")
        )
        table["others"] = table["reports"] - table["cases"]
        em.variable("cases", "count", label="reports of hepatic injury")
        em.variable("others", "count", label="other reports")
        grouped = smf.glm(
            "cases + others ~ exposed + C(age_group, Treatment('18-44'))",
            table,
            family=sm.families.Binomial(),
        ).fit()
        em.model("grouped", grouped, name="Grouped model")
"""


def test_a_grouped_model_counts_the_table_and_a_level_with_no_events_fails(project: Path) -> None:
    """The same reports as a table of eight rows, cases beside the others. The fit is of the
    proportion in each row, and the sum of the proportions was recorded as the events."""
    _replace_once(_analysis(project), _THE_BOUNDS, _GROUPED + _THE_BOUNDS)
    _rerun_disproportionality(project)
    report = _models_report(project)
    assert not report.findings, report.render(project)
    project_, _ = load_project(project)
    models = load_namespace(project_)[1].models
    each, grouped = models["adjusted"], models["grouped"]
    assert (grouped.events, grouped.trials) == (each.events, each.n_used) == (271, 4000)
    assert grouped.n_used == 8
    assert grouped.events_by_level == {"age_group": each.events_by_level["age_group"]}

    _replace_once(
        _analysis(project),
        '        table["others"] = ',
        '        table.loc[table["age_group"] == "75+", "cases"] = 0\n        table["others"] = ',
    )
    _rerun_disproportionality(project)
    failed = [f.message for f in _models_report(project).failures]
    assert (
        "model 'grouped': no events at level '75+' of 'age_group': its coefficient cannot be "
        "estimated (separation)"
    ) in failed, failed


def test_another_model_named_in_the_methods_is_not_the_fitted_kind_typed(project: Path) -> None:
    """"Conditional logistic regression" is not the logistic regression the example fitted,
    and binding the fitted kind there, as the hint said, would have misnamed it. A word that
    leaves the model what it is, "multivariable", still leaves the name a typed copy."""
    said = "S2 describes the model as it was fitted."
    _replace_once(
        main_md(project), said, said + " A conditional logistic regression was not needed."
    )
    report = _models_report(project)
    assert not report.findings, report.render(project)
    _replace_once(main_md(project), "A conditional logistic", "A multivariable logistic")
    assert [f.code for f in _models_report(project).findings] == ["typed-model-kind"]


# -------------------------------------------------------------- the Methods, pair by pair


def _methods_report(project: Path):
    from manuscript_guard.gates import check_methods

    loaded = load_project(project)[0]
    namespace, results, _literature, _loaded = load_namespace(loaded)
    return check_methods(loaded, namespace, results)


def _line_of(root: Path, text: str) -> int:
    lines = main_md(root).read_text(encoding="utf-8").splitlines()
    return next(n for n, line in enumerate(lines, 1) if text in line)


def test_the_example_s_methods_point_at_steps_that_ran_and_were_read(project: Path) -> None:
    report = _methods_report(project)
    assert report.ok and not report.findings, report.render(project)
    # Four steps, three texts: the estimate and its intervals share one paragraph.
    assert (report.counts["method_steps"], report.counts["method_claims"]) == (4, 3)
    assert report.counts["method_pairs_stale"] == 0


def test_a_change_inside_a_step_names_the_paragraph_to_read_again(project: Path) -> None:
    """The 90% interval's quantile moved. The file-level drift says a file changed; the pair
    says which paragraph of the Methods describes the code that did."""
    _replace_once(_analysis(project), "1.645 * se)\n        high90", "1.64 * se)\n        high90")
    _rerun_disproportionality(project)
    report = _methods_report(project)
    found = [f for f in report.failures if f.code == "method-step-changed"]
    assert [(f.message, f.line) for f in found] == [
        (
            "step 'ci' changed after the text pointing at it was last read against it",
            _line_of(project, "{{method.ci}}"),
        )
    ]
    assert found[0].context.startswith("The reporting odds ratio was computed")
    assert "methods-drift" in {f.code for f in report.failures}


def test_a_step_read_before_any_file_was_is_still_held_to_its_code(project: Path) -> None:
    """The example before anybody reconciled it, and one step read against its text first.
    The lock then holds that pair and no file, and it was taken for no lock: the same change
    to the step went by with a warning that the files had never been read."""
    from manuscript_guard.gates import reconcile

    (project / "methods.lock").unlink()
    reconcile(load_project(project)[0], steps=["ci"])
    _replace_once(_analysis(project), "1.645 * se)\n        high90", "1.64 * se)\n        high90")
    _rerun_disproportionality(project)
    report = _methods_report(project)
    assert [f.message for f in report.failures if f.code == "method-step-changed"] == [
        "step 'ci' changed after the text pointing at it was last read against it"
    ], report.render(project)
    unread = [f.message.split("'")[1] for f in report.failures if f.code == "method-pair-unread"]
    assert sorted(unread) == ["adjusted", "ror", "signal"]
    assert [f.code for f in report.warnings] == ["methods-never-reconciled"]


def test_an_anchor_moved_to_a_line_of_its_own_inside_a_paragraph_is_warned(project: Path) -> None:
    """The example's first anchor, on a line of its own after the sentence it is about. The
    line prints as an empty line, and the document ends the paragraph there."""
    _replace_once(main_md(project), "database. Confidence", "database.\n{{method.ror}}\nConfidence")
    _replace_once(main_md(project), "practice. {{method.ror}} {{method", "practice. {{method")
    report = _methods_report(project)
    found = [f for f in report.warnings if f.code == "method-anchor-line"]
    assert [f.line for f in found] == [_line_of(project, "{{method.ror}}")], report.render(project)


def test_a_comment_added_inside_a_step_leaves_its_pair_read(project: Path) -> None:
    _replace_once(_analysis(project), "        ror = (a / b) / (c / d)\n",
                  "        # the ratio of the two odds\n        ror = (a / b) / (c / d)\n")
    _rerun_disproportionality(project)
    report = _methods_report(project)
    assert not [f for f in report.findings if f.code.startswith("method-")], report.render(
        project
    )


def test_a_claim_about_a_branch_the_run_never_took_fails(project: Path) -> None:
    """A sensitivity analysis described in the Methods, whose code sits in a branch no run
    takes: the step is never recorded, and the anchor names nothing that ran."""
    _replace_once(
        _analysis(project),
        '    em.software("python")\n',
        '    if serious < 0:\n        with em.step("sensitivity"):\n'
        '            em.value("sensitivity.ror", ror, quoted=False)\n'
        '    em.software("python")\n',
    )
    _rerun_disproportionality(project)
    _replace_once(
        main_md(project),
        "The analysis was run in Python",
        "A sensitivity analysis left out the serious reports. {{method.sensitivity}}\n\n"
        "The analysis was run in Python",
    )
    report = _methods_report(project)
    found = [f for f in report.failures if f.code == "method-step-unknown"]
    assert [f.line for f in found] == [_line_of(project, "{{method.sensitivity}}")]


def test_a_methods_paragraph_reworded_is_named_with_what_it_said(project: Path) -> None:
    _replace_once(main_md(project), "odds ratio was computed from a 2 x 2 table",
                  "odds ratio was computed from a 2 by 2 table")
    report = _methods_report(project)
    found = [f for f in report.failures if f.code == "method-claim-changed"]
    assert [f.message.split("'")[1] for f in found] == ["ror", "ci"], report.render(project)
    assert all(
        f.context.startswith("was: The reporting odds ratio was computed from a 2 x 2 table")
        for f in found
    ), "one text, pointing at two steps, read against each"


def test_an_anchor_deleted_leaves_its_step_described_by_nothing(project: Path) -> None:
    _replace_once(main_md(project), "\n{{method.signal}}", "")
    report = _methods_report(project)
    assert [f.message for f in report.warnings if f.code == "method-step-undescribed"] == [
        "step 'signal' ran, and no text in the manuscript points at it"
    ]
