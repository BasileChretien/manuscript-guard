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
import shutil
import time
import zipfile
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
    assert report.ok, report.render(project)


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


# --------------------------------------------------------------------- the journal gate
# A journal's limits, sections and statements are about the document the editor receives,
# and the build strips every file's front matter before printing it.


def _journal(root: Path):
    from manuscript_guard.gates import check_journal

    project, _ = load_project(root)
    return check_journal(project)


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
def test_a_forced_import_does_not_write_over_a_neighbouring_paragraph(
    project: Path, tmp_path: Path
) -> None:
    """Identifiers are positional. With a paragraph added to the source since the build,
    above the one a co-author edited, every identifier after it named the paragraph before,
    and `import --apply --force` wrote three edits over their neighbours and printed "merged
    3 reworded paragraph(s), bindings intact". The plan showed what each edit became, never
    which paragraph it replaced, so reading every hunk could not have caught it."""
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
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "# Introduction\n\n", "# Introduction\n\nA paragraph added after the build.\n\n", 1
        ),
        encoding="utf-8",
    )
    source = path.read_text(encoding="utf-8")

    assert main(["import", str(returned), str(project), "--apply", "--force"]) == 1
    assert path.read_text(encoding="utf-8") == source, "an edit landed in another paragraph"


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
_IN_RESULTS = "are shown in Table 2."
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
            "[^n]: A note.\n\nSignificance was set at p < 0.05.\n",
        ),
        (
            (_IN_RESULTS,),
            _IN_METHODS,
            "[^n]: A note.\n\n   Significance was set at p < 0.05.\n",
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
        "The CO~2~ level was read over a 3 m^2^ area, with the `x2` variable.\n"
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
    assert sum('"2"' in m for m in marked) == 2, marked
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
