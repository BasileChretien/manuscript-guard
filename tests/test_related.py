"""This paper against the earlier outputs of the same data: `literature/related.yaml`, the
copy `related --take` keeps of an earlier project, and what G8 makes of the two.

Each test builds two projects from the example: the earlier one, a copy of the example
standing beside the paper, and the paper itself. A defect is planted in the earlier one, as
the analysis that made it would have left it, and the paper is held to it."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.gates.related import _printed, _same_printed, check_related
from manuscript_guard.gates.related_methods import folded_title, sections_compared
from manuscript_guard.literature.related import (
    SNAPSHOT_FILE,
    TakeError,
    load_related,
    read_snapshot,
    take,
)

FRAGMENT = Path("results") / "01_disproportionality.json"
CITED = "fictionalHepaticCohort2021"
SENTENCE = "The database was extracted again, with a later cut-off, for this analysis."


def _declare(root: Path, *outputs: dict) -> Path:
    path = root / "literature" / "related.yaml"
    document = {"schema": "manuscript-guard/related/1", "outputs": list(outputs)}
    path.write_bytes(yaml.safe_dump(document, sort_keys=False).encode("utf-8"))
    return path


def _entry(**rest) -> dict:
    return {"id": "abstract", "kind": "abstract", "title": "An abstract", "shares": ["data"],
            **rest}  # fmt: skip


def _set(root: Path, key: str, value: object, display: str, *, rename: str | None = None) -> None:
    """Change one value of a project's results, as a different run would have written it."""
    path = root / FRAGMENT
    document = json.loads(path.read_text(encoding="utf-8"))
    spec = document["values"].pop(key)
    spec["value"], spec["display"] = value, display
    document["values"][rename or key] = spec
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))


def _append(root: Path, text: str) -> None:
    main_md = root / "manuscript" / "main.md"
    main_md.write_bytes(main_md.read_bytes() + f"\n{text}\n".encode())


@pytest.fixture
def earlier(project: Path) -> Path:
    """The example as an earlier project, beside the paper: `../earlier` from its root."""
    root = project.parent / "earlier"
    shutil.copytree(project, root)
    return root


def _take(root: Path, output_id: str = "abstract") -> Path:
    project, _ = load_project(root)
    related, _ = load_related(project)
    (output,) = [o for o in related.outputs if o.id == output_id]
    return take(project, output)


def _check(root: Path, *, submission: bool = False):
    project, _ = load_project(root)
    namespace, results, _literature, _loaded = load_namespace(project)
    return check_related(project, namespace, results, submission=submission)


def _found(report) -> list[tuple[str, str]]:
    return [(f.code, f.severity) for f in report.findings]


# ---------------------------------------------------------------------- nothing declared


def test_a_project_with_no_record_is_told_nothing(project: Path) -> None:
    report = _check(project)
    assert report.findings == () and report.counts == {}


# ---------------------------------------------------------------------- numbers


def test_the_same_results_compare_clean(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    _take(project)
    report = _check(project)
    assert _found(report) == []
    assert report.counts["related_values_compared"] > 10
    assert report.counts["related_values_differ"] == 0


def test_a_changed_count_warns_and_fails_at_submission(project: Path, earlier: Path) -> None:
    _set(earlier, "cohort.n_reports", 4012, "4012")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == [("related-number-differs", WARN)]
    found = _check(project, submission=True)
    assert _found(found) == [("related-number-differs", FAIL)]
    assert "cohort.n_reports is 4012 there and 4000 here" in found.findings[0].message
    assert found.counts["related_values_differ"] == 1


def test_a_difference_is_explained_only_where_the_manuscript_says_it(
    project: Path, earlier: Path
) -> None:
    _set(earlier, "cohort.n_reports", 4012, "4012")
    pair = {"earlier": "cohort.n_reports", "here": "results.cohort.n_reports",
            "because": "a later cut-off", "manuscript_says": SENTENCE}  # fmt: skip
    _declare(project, _entry(project="../earlier", pairs=[pair]))
    _take(project)
    assert _found(_check(project, submission=True)) == [("related-reason-not-in-text", FAIL)]
    _append(project, f"<!-- {SENTENCE} -->")
    assert _found(_check(project)) == [("related-reason-not-in-text", WARN)], "a comment is unread"
    wrapped = "The database was extracted again,\nwith a *later* cut-off, for this analysis."
    _append(project, wrapped)
    assert _found(_check(project, submission=True)) == [("related-number-explained", INFO)]


def test_a_reason_alone_does_not_explain_a_number(project: Path, earlier: Path) -> None:
    _set(earlier, "case.n_cases", 80, "80")
    pair = {"earlier": "case.n_cases", "here": "case.n_cases", "because": "a later cut-off"}
    _declare(project, _entry(project="../earlier", pairs=[pair]))
    _take(project)
    (finding,) = _check(project).findings
    assert finding.code == "related-reason-not-in-text"
    assert "no sentence of the manuscript is given" in finding.message


def test_a_sentence_with_a_binding_is_read_filled_in(project: Path, earlier: Path) -> None:
    _set(earlier, "cohort.n_reports", 4012, "4012")
    said = "The database contained {{results.cohort.n_reports}} reports"
    pair = {"earlier": "cohort.n_reports", "here": "cohort.n_reports",
            "because": "a later cut-off", "manuscript_says": said}  # fmt: skip
    _declare(project, _entry(project="../earlier", pairs=[pair]))
    _take(project)
    assert _found(_check(project)) == [("related-number-explained", INFO)]


def test_a_renamed_key_is_compared_through_its_pair(project: Path, earlier: Path) -> None:
    _set(earlier, "case.n_cases", 79, "79", rename="n_cases")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == [], "a key one side does not emit compares nothing"
    _declare(project, _entry(project="../earlier",
                             pairs=[{"earlier": "n_cases", "here": "case.n_cases"}]))  # fmt: skip
    (finding,) = _check(project).findings
    assert finding.code == "related-number-differs"
    assert "n_cases (here case.n_cases) is 79 there and 77 here" in finding.message


def test_a_pair_naming_a_key_nobody_emits_says_so(project: Path, earlier: Path) -> None:
    pairs = [{"earlier": "n_cases", "here": "case.n_cases"},
             {"earlier": "case.n_cases", "here": "case.count"}]  # fmt: skip
    _declare(project, _entry(project="../earlier", pairs=pairs))
    _take(project)
    found = _check(project, submission=True).findings
    assert [(f.code, f.severity) for f in found] == [("related-pair-unmatched", FAIL)] * 2
    assert "the earlier project emits no n_cases" in found[0].message
    assert "this project emits no case.count" in found[1].message


def test_keys_that_are_not_the_same_quantity_are_set_apart(project: Path, earlier: Path) -> None:
    _set(earlier, "ror.point", 1.91, "1.91")
    apart = [{"keys": "ror.*", "because": "another drug of interest"}]
    _declare(project, _entry(project="../earlier", not_compared=apart))
    _take(project)
    assert _found(_check(project)) == []


def test_a_value_printed_by_one_paper_only_is_not_compared(project: Path, earlier: Path) -> None:
    _set(earlier, "table2x2.a", 70, "70")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == []


def test_the_same_value_printed_to_other_places_is_the_same(project: Path, earlier: Path) -> None:
    _set(earlier, "ror.point", 3.843972469205093, "3.8")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == []


# ---------------------------------------------------------------------- methods


def test_a_changed_parameter_is_a_method_that_warns_and_never_fails(
    project: Path, earlier: Path
) -> None:
    _set(earlier, "param.signal.min_cases", 5, "5")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project, submission=True)) == [("related-method-differs", WARN)]
    pair = {"earlier": "param.signal.min_cases", "here": "param.signal.min_cases",
            "because": "the signal criterion of the later guideline"}  # fmt: skip
    _declare(project, _entry(project="../earlier", pairs=[pair]))
    assert _found(_check(project, submission=True)) == [("related-method-explained", INFO)]


def test_a_dictionary_release_is_a_method_and_software_is_not_compared(
    project: Path, earlier: Path
) -> None:
    _set(earlier, "dictionary.generator_event_terms", "2", "2")
    _set(earlier, "software.statsmodels", "0.13.0", "0.13.0")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == [("related-method-differs", WARN)]


# ---------------------------------------------------------------------- disclosure


def test_an_overlap_of_data_and_authors_must_be_disclosed(project: Path) -> None:
    entry = _entry(citekey="earlier2025", shares=["data", "authors"], files_unavailable="lost")
    _declare(project, entry)
    assert _found(_check(project)) == [("related-undisclosed", WARN)]
    assert _found(_check(project, submission=True)) == [("related-undisclosed", FAIL)]
    _declare(project, {**entry, "citekey": CITED})
    assert _found(_check(project, submission=True)) == []


def test_a_citation_in_a_comment_discloses_nothing(project: Path) -> None:
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8").replace(f"@{CITED}", "@fictionalClassSignal2019")
    main_md.write_bytes((text + f"\n<!-- [@{CITED}] -->\n").encode("utf-8"))
    entry = _entry(citekey=CITED, shares=["study", "authors"], files_unavailable="lost")
    _declare(project, entry)
    assert _found(_check(project)) == [("related-undisclosed", WARN)]


def test_a_sentence_can_disclose_what_is_not_cited(project: Path) -> None:
    said = "Preliminary results were presented at a meeting of the society."
    entry = _entry(shares=["data", "authors"], files_unavailable="lost", disclosed_by=said)
    _declare(project, entry)
    (finding,) = _check(project).findings
    assert finding.code == "related-undisclosed" and "not in the manuscript" in finding.message
    _append(project, said)
    assert _found(_check(project, submission=True)) == []


def test_data_shared_without_authors_needs_no_disclosure(project: Path) -> None:
    _declare(project, _entry(citekey="someone2024", shares=["data"]))
    assert _found(_check(project, submission=True)) == []


# ---------------------------------------------------------------------- the supplement


def _supplement(root: Path, text: str) -> None:
    path = root / "manuscript" / "supplementary" / "s1.md"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def test_the_supplement_is_held_as_the_main_text_is(project: Path, earlier: Path) -> None:
    """A count printed only in an eTable is compared, and the sentence that explains it and
    the citation that discloses the overlap count where they stand in the supplement."""
    main_md = project / "manuscript" / "main.md"
    text = main_md.read_text(encoding="utf-8")
    text = text.replace("{{results.case.n_serious}} were flagged", "some were flagged")
    main_md.write_bytes(text.replace("@fictionalClassSignal2019", f"@{CITED}").encode("utf-8"))
    _supplement(project, "# eTable 1\n\nOf the cases, {{results.case.n_serious}} were serious.\n")
    _set(earlier, "case.n_serious", 30, "30")
    entry = _entry(project="../earlier", citekey="fictionalClassSignal2019",
                   shares=["data", "authors"])  # fmt: skip
    _declare(project, entry)
    _take(project)
    assert _found(_check(project, submission=True)) == [
        ("related-undisclosed", FAIL), ("related-number-differs", FAIL),
    ]  # fmt: skip
    pair = {"earlier": "case.n_serious", "here": "case.n_serious",
            "because": "a later cut-off", "manuscript_says": SENTENCE}  # fmt: skip
    _declare(project, {**entry, "pairs": [pair]})
    _supplement(project, f"# eTable 1\n\nOf the cases, {{{{results.case.n_serious}}}} were "
                f"serious [@fictionalClassSignal2019].\n\n{SENTENCE}\n")  # fmt: skip
    assert _found(_check(project, submission=True)) == [("related-number-explained", INFO)]


def test_a_value_may_be_quoted_from_the_earlier_output_s_supplement(project: Path) -> None:
    path = project / "literature" / "sources" / "abstract2025-supplement.txt"
    path.write_bytes(b"eTable 2. Of 28 serious reports, most were of older patients.")
    value = {"here": "case.n_serious", "value": "28",
             "source_file": "sources/abstract2025-supplement.txt",
             "quote": "Of 28 serious reports, most were of older patients."}  # fmt: skip
    _declare(project, _entry(values=[value]))
    assert _found(_check(project)) == []
    path.write_bytes(b"eTable 2. Of 30 serious reports, most were of older patients.")
    _declare(project, _entry(values=[{**value, "value": "30", "quote": value["quote"].replace(
        "28", "30")}]))  # fmt: skip
    assert _found(_check(project)) == [("related-number-differs", WARN)]


# ---------------------------------------------------------------------- asking for files


def test_an_output_of_our_own_authors_asks_for_its_files(project: Path) -> None:
    _declare(project, _entry(citekey=CITED, shares=["data", "authors"]))
    assert _found(_check(project, submission=True)) == [("related-files-missing", WARN)]
    _declare(project, _entry(citekey=CITED, shares=["data", "authors"],
                             files_unavailable="the sponsor"))  # fmt: skip
    assert _found(_check(project)) == []


def test_a_paper_of_our_own_authors_on_other_data_asks_for_nothing(project: Path) -> None:
    """Listed for the text it may share, it has no numbers to compare (round 1 of #391)."""
    _declare(project, _entry(citekey="ours2023", shares=["authors"]))
    assert _found(_check(project, submission=True)) == []


def test_a_named_output_file_must_be_there(project: Path) -> None:
    _declare(project, _entry(shares=["data", "authors"], citekey=CITED,
                             files=["related/abstract/files/counts.csv"]))  # fmt: skip
    assert _found(_check(project)) == [("related-file-missing", WARN)]


# ---------------------------------------------------------------------- methods as data


def _card(root: Path, change) -> None:
    """Change the adjusted model's card, as a different fit would have written it."""
    path = root / FRAGMENT
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document["models"]["adjusted"])
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))


def _plan(root: Path, old: str, new: str) -> None:
    """Change the earlier project's plan as it stood when its results were first written."""
    path = root / "design" / "plan.frozen.yaml"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert old in document["plan"], old
    document["plan"] = document["plan"].replace(old, new)
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))


def test_a_model_fitted_otherwise_is_a_method_said_and_never_failed(
    project: Path, earlier: Path
) -> None:
    def changed(card: dict) -> None:
        card["engine"]["family"] = "Poisson"
        card["terms"] = [t for t in card["terms"] if t["term"] != "C(sex, Treatment('F'))"]

    _card(earlier, changed)
    _declare(project, _entry(project="../earlier"))
    _take(project)
    (finding,) = _check(project, submission=True).findings
    assert (finding.code, finding.severity) == ("related-method-differs", WARN)
    assert "model adjusted: its family is Poisson/Logit there and Binomial/Logit here" in (
        finding.message
    )
    assert "it enters sex here and not there" in finding.message
    why = [{"model": "adjusted", "because": "the sex of each report is now recorded"}]
    _declare(project, _entry(project="../earlier", methods=why))
    assert _found(_check(project)) == [("related-method-explained", INFO)]


def test_a_reference_level_changed_is_said(project: Path, earlier: Path) -> None:
    def changed(card: dict) -> None:
        for term in card["terms"]:
            for entered in term["entered"]:
                if entered.get("reference") == "F":
                    entered["reference"] = "M"

    _card(earlier, changed)
    _declare(project, _entry(project="../earlier"))
    _take(project)
    (finding,) = _check(project).findings
    assert "sex has the reference M there and F here" in finding.message


def test_a_section_of_the_plan_worded_otherwise_is_a_method(project: Path, earlier: Path) -> None:
    _plan(earlier, "## Outcome\n\n", "## Outcome\n\nOnly serious reports counted. ")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    (finding,) = _check(project, submission=True).findings
    assert (finding.code, finding.severity) == ("related-method-differs", WARN)
    assert "the plan's Outcome: it reads 'only serious reports counted." in finding.message
    why = [{"plan_section": "2. OUTCOME", "because": "all reports, as the journal asked"}]
    _declare(project, _entry(project="../earlier", methods=why))
    assert _found(_check(project)) == [("related-method-explained", INFO)]


def test_a_plan_rewrapped_or_its_own_deviations_changed_reads_the_same(
    project: Path, earlier: Path
) -> None:
    path = earlier / "design" / "plan.frozen.yaml"
    document = json.loads(path.read_text(encoding="utf-8"))
    plan = document["plan"]
    outcome = plan.index("## Outcome\n\n") + len("## Outcome\n\n")
    end = plan.index("\n## ", outcome)
    body = plan[outcome:end].replace(" ", "\n", 3).replace("hepatic", "*hepatic*", 1)
    plan = plan[:outcome] + body.replace(" ", " <!-- reread --> ", 1) + plan[end:]
    document["plan"] = plan + "\nA deviation the abstract recorded.\n"
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == []


def test_a_copy_with_no_frozen_plan_reads_its_plan(project: Path, earlier: Path) -> None:
    (earlier / "design" / "plan.frozen.yaml").unlink()
    plan = earlier / "design" / "plan.md"
    plan.write_bytes(plan.read_bytes().replace(b"## Outcome\n\n", b"## Outcome\n\nNot so. "))
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == [("related-method-differs", WARN)]


def test_a_variable_or_an_outcome_entered_by_another_expression_is_said(
    project: Path, earlier: Path
) -> None:
    """Round 1 of #402: the expression is compared, and every way a variable is entered."""

    def changed(card: dict) -> None:
        card["outcome"]["expression"] = "I(hepatic > 0)"
        for term in card["terms"]:
            for entered in term["entered"]:
                if entered["expression"] == "exposed":
                    entered["expression"] = "np.log1p(exposed)"
        card["terms"].append({"term": "exposed:sex", "entered": [
            {"expression": "exposed:sex", "variables": ["exposed"], "as": "numerical"}]})

    _card(earlier, changed)
    _declare(project, _entry(project="../earlier"))
    _take(project)
    (finding,) = _check(project).findings
    assert "its outcome is I(hepatic > 0) there and hepatic here" in finding.message
    assert "exposed is entered as exposed:sex (numerical); np.log1p(exposed) (numerical) there" in (
        finding.message
    )
    assert "exposed:sex (numerical)" in finding.message


def test_a_reason_for_a_model_or_section_neither_has_is_said(
    project: Path, earlier: Path
) -> None:
    why = [{"model": "unadjusted", "because": "x"}, {"plan_section": "Comparator", "because": "y"}]
    _declare(project, _entry(project="../earlier", methods=why))
    _take(project)
    found = _check(project, submission=True)
    assert _found(found) == [("related-pair-unmatched", FAIL)] * 2
    assert found.counts["related_values_differ"] == 0


def test_this_plan_not_in_utf8_is_read_and_not_refused(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    _take(project)
    plan = project / "design" / "plan.md"
    plan.write_bytes(plan.read_bytes() + "\nA note of the caf\u00e9.\n".encode("cp1252"))
    assert _found(_check(project)) == []


def test_an_earlier_plan_frozen_with_crlf_reads_the_same(project: Path, earlier: Path) -> None:
    path = earlier / "design" / "plan.frozen.yaml"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["plan"] = chr(0xFEFF) + document["plan"].replace("\n", "\r\n")
    path.write_bytes(json.dumps(document, indent=2).encode("utf-8"))
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert _found(_check(project)) == []


def test_what_a_plan_s_planned_results_and_deviations_hold_is_not_compared() -> None:
    then = "# Plan\n\n## Planned results\n\n### Primary\n\n- `a.b`\n"
    now = "# Plan\n\n## Planned results\n\n### Primary\n\n- `c.d`\n"
    assert sections_compared(then, now) == []


def test_a_heading_is_matched_with_the_headings_above_it() -> None:
    then = ("# Plan\n\n## Exposure\n\n### Definition\n\nA drug.\n\n"
            "## Outcome\n\n### Definition\n\nAn event.\n")
    now = then.replace("An event.", "A serious event.")
    assert [found[0] for found in sections_compared(then, now)] == ["Outcome / Definition"]
    assert folded_title("2.1 Definition") == folded_title("Definition")
    assert folded_title("2019 cohort") != folded_title("2020 cohort")


def test_the_listing_shows_a_method_changed(project: Path, earlier: Path, capsys) -> None:
    _card(earlier, lambda card: card["engine"].update(link="Probit"))
    _declare(project, _entry(project="../earlier"))
    _take(project)
    assert main(["related", str(project)]) == 0
    assert "model adjusted: " in capsys.readouterr().out


# ---------------------------------------------------------------------- the copy


def test_a_project_named_and_not_copied_compares_nothing(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    assert _found(_check(project)) == [("related-not-taken", WARN)]
    assert _found(_check(project, submission=True)) == [("related-not-taken", FAIL)]


def test_a_copy_edited_by_hand_fails(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    record = _take(project)
    copied = record.parent / FRAGMENT
    copied.write_bytes(copied.read_bytes().replace(b'"4000"', b'"4001"'))
    found = _check(project).findings
    assert [(f.code, f.severity) for f in found] == [("related-snapshot-edited", FAIL)]
    assert "results/01_disproportionality.json" in found[0].message


def test_a_fragment_added_to_a_copy_is_an_edit(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    record = _take(project)
    (record.parent / "results" / "02_extra.json").write_bytes(b"{}")
    assert _found(_check(project)) == [("related-snapshot-edited", FAIL)]


def test_a_copy_of_another_revision_is_said(project: Path, earlier: Path) -> None:
    _git(earlier, "init", "-q")
    _git(earlier, "add", "-A")
    _git(earlier, "commit", "-qm", "earlier")
    _git(earlier, "tag", "v1")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    _declare(project, _entry(project="../earlier", revision="v1"))
    assert _found(_check(project)) == [("related-taken-elsewhere", WARN)]
    # Round 1: compared with another output than the one named, it does not go out so.
    assert _found(_check(project, submission=True)) == [("related-taken-elsewhere", FAIL)]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args], check=True)  # fmt: skip


def test_a_revision_is_copied_as_it_was_committed(project: Path, earlier: Path) -> None:
    _git(earlier, "init", "-q")
    _git(earlier, "add", "-A")
    _git(earlier, "commit", "-qm", "as submitted")
    _git(earlier, "tag", "submitted")
    _set(earlier, "cohort.n_reports", 4100, "4100")  # the work went on after the abstract
    _declare(project, _entry(project="../earlier", revision="submitted"))
    record = _take(project)
    manifest = yaml.safe_load(record.read_text(encoding="utf-8"))
    head = subprocess.run(["git", "-C", str(earlier), "rev-parse", "submitted"],
                          capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    assert manifest["commit"] == head and manifest["revision"] == "submitted"
    assert "uncommitted" not in manifest
    assert "design/plan.md" in manifest["files"] and "results/01_disproportionality.json" in (
        manifest["files"]
    )
    assert _found(_check(project)) == []
    _declare(project, _entry(project="../earlier"))
    record = _take(project)
    assert yaml.safe_load(record.read_text(encoding="utf-8"))["uncommitted"] is True
    assert _found(_check(project)) == [("related-number-differs", WARN)]


def test_a_copy_checked_out_with_other_line_endings_is_not_edited(
    project: Path, earlier: Path
) -> None:
    """Round 1: a plan saved with CRLF and committed under `eol=lf` is checked out with LF on
    every other machine, and that is no edit of the copy."""
    plan = earlier / "design" / "plan.md"
    plan.write_bytes(plan.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    _declare(project, _entry(project="../earlier"))
    record = _take(project)
    copied = record.parent / "design" / "plan.md"
    assert b"\r\n" in copied.read_bytes()
    copied.write_bytes(copied.read_bytes().replace(b"\r\n", b"\n"))
    assert _found(_check(project)) == []


def test_files_a_system_leaves_in_a_copy_are_not_edits(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    record = _take(project)
    (record.parent / "results" / ".DS_Store").write_bytes(b"\0\0\0\1Bud1")
    assert _found(_check(project)) == []
    _take(project)
    assert (record.parent / "results" / ".DS_Store").is_file()
    # A fragment is read whatever its name, so one added is an edit (round 2).
    (record.parent / "results" / ".extra.json").write_bytes(b"{}")
    assert _found(_check(project)) == [("related-snapshot-edited", FAIL)]


def test_a_revision_or_a_value_typed_as_a_number_is_read_as_typed(project: Path) -> None:
    """Round 1: YAML reads `1.50` as 1.5 and a short commit of digits as an integer."""
    quote = "an odds ratio of 1.50 (95% CI 1.20 to 1.90) in the abstract"
    _source(project, quote)
    (project / "literature" / "related.yaml").write_bytes(
        b"schema: manuscript-guard/related/1\n"
        b"outputs:\n"
        b"  - id: abstract\n"
        b"    kind: abstract\n"
        b"    title: An abstract\n"
        b"    shares: [data]\n"
        b"    project: ../earlier\n"
        b"    revision: 1.10\n"
        b"    values:\n"
        b"      - here: ror.point\n"
        b"        value: 1.50\n"
        b"        source_file: sources/abstract2025.txt\n"
        b"        quote: " + quote.encode() + b"\n"
    )
    loaded, _ = load_related(load_project(project)[0])
    (output,) = loaded.outputs
    assert (output.revision, output.values[0].value) == ("1.10", "1.50")
    found = [f for f in _check(project).findings if f.code != "related-not-taken"]
    assert [f.code for f in found] == ["related-number-differs"]
    assert "ror.point is 1.50 there" in found[0].message


def test_take_names_a_copy_outside_the_project_by_its_path(
    project: Path, earlier: Path, capsys
) -> None:
    shutil.move(project / "literature", project.parent / "lit")
    paper = project / "paper.yaml"
    # An absolute path: one relative to the project, `../lit`, is still printed from it.
    outside = (project.parent / "lit").as_posix()
    paper.write_bytes(paper.read_bytes() + f"\npaths:\n  literature: '{outside}'\n".encode())
    record = {"schema": "manuscript-guard/related/1", "outputs": [_entry(project="../earlier")]}
    (project.parent / "lit" / "related.yaml").write_bytes(yaml.safe_dump(record).encode())
    assert main(["related", str(project), "--take"]) == 0
    assert str(project.parent / "lit" / "related" / "abstract") in capsys.readouterr().out


def test_take_writes_over_nothing_it_did_not_write(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    folder = project / "literature" / "related" / "abstract" / "results"
    folder.mkdir(parents=True)
    (folder / "mine.json").write_bytes(b"{}")
    with pytest.raises(TakeError, match="was not written by"):
        _take(project)
    assert (folder / "mine.json").read_bytes() == b"{}"


def test_take_again_replaces_only_its_own_files(project: Path, earlier: Path) -> None:
    _declare(project, _entry(project="../earlier"))
    record = _take(project)
    kept = record.parent / "files" / "counts.csv"
    kept.parent.mkdir()
    kept.write_bytes(b"n\n4000\n")
    (earlier / "design" / "plan.frozen.yaml").unlink()
    record = _take(project)
    assert not (record.parent / "design" / "plan.frozen.yaml").exists()
    assert kept.read_bytes() == b"n\n4000\n"
    assert read_snapshot(load_project(project)[0], "abstract")[0].edited == ()


def test_a_folder_with_no_paper_yaml_is_not_copied(project: Path, tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    _declare(project, _entry(project="../scripts"))
    with pytest.raises(TakeError, match="not a manuscript-guard project"):
        _take(project)


def test_an_unknown_revision_is_refused(project: Path, earlier: Path) -> None:
    _git(earlier, "init", "-q")
    _declare(project, _entry(project="../earlier", revision="no-such-tag"))
    with pytest.raises(TakeError, match="no revision 'no-such-tag'"):
        _take(project)
    _declare(project, _entry(project="../earlier", revision="--output=x"))
    with pytest.raises(TakeError, match="is not a revision"):
        _take(project)


# ---------------------------------------------------------------------- from the text


def _source(project: Path, text: str) -> str:
    path = project / "literature" / "sources" / "abstract2025.txt"
    path.write_bytes(text.encode("utf-8"))
    return "sources/abstract2025.txt"


def test_a_value_from_the_text_is_held_to_its_quote_and_to_this_paper(project: Path) -> None:
    quote = "Of 4,012 reports in the database, 77 described hepatic injury."
    source = _source(project, f"Results. {quote} More text.")
    value = {"here": "cohort.n_reports", "value": "4,012", "source_file": source, "quote": quote}
    _declare(project, _entry(values=[value]))
    (finding,) = _check(project).findings
    assert finding.code == "related-number-differs"
    assert "cohort.n_reports is 4,012 there and 4000 here" in finding.message
    same = {**value, "here": "case.n_cases", "value": "77"}
    _declare(project, _entry(values=[same]))
    assert _found(_check(project)) == []


def test_a_value_whose_quote_is_not_in_its_source_fails(project: Path) -> None:
    source = _source(project, "Of 4,000 reports in the database, 77 described hepatic injury.")
    quote = "Of 4,012 reports in the database, 77 described hepatic injury."
    value = {"here": "cohort.n_reports", "value": "4,012", "source_file": source, "quote": quote}
    _declare(project, _entry(values=[value]))
    assert _found(_check(project)) == [("related-quote-not-in-source", FAIL)]
    _declare(project, _entry(values=[{**value, "value": "4,013", "quote": quote.replace(
        "4,012", "4,000")}]))  # fmt: skip
    assert _found(_check(project)) == [("related-value-not-in-quote", FAIL)]
    _declare(project, _entry(values=[{**value, "source_file": "sources/gone.pdf"}]))
    assert _found(_check(project)) == [("related-source-missing", FAIL)]


def test_a_value_from_the_text_of_a_key_this_paper_lacks_says_so(project: Path) -> None:
    quote = "Of 4,000 reports in the database, 77 described hepatic injury."
    source = _source(project, quote)
    value = {"here": "cohort.n_all", "value": "4,000", "source_file": source, "quote": quote}
    _declare(project, _entry(values=[value]))
    assert _found(_check(project)) == [("related-pair-unmatched", WARN)]


@pytest.mark.parametrize(
    ("printed", "display", "value", "same"),
    [
        ("4,000", "4000", 4000, True),
        ("4 000", "4000", 4000, True),
        ("4000", "4012", 4012, False),
        ("3.8", "3.84", 3.843972469205093, True),
        ("3.84", "3.8", 3.843972469205093, True),
        ("3.9", "3.84", 3.843972469205093, False),
        ("3" + chr(0x00B7) + "84", "3.84", 3.843972469205093, True),
        ("36.4%", "36.4", 36.36363636363637, True),
        (chr(0x2212) + "0.4", "-0.4", -0.4, True),
        (".45", "0.45", 0.45, True),
        ("-.45", "-0.45", -0.45, True),
        (".46", "0.45", 0.45, False),
        ("met", "met", "met", True),
        ("not met", "met", "met", False),
    ],
)
def test_a_printed_value_is_read_as_the_number_it_prints(
    printed: str, display: str, value: object, same: bool
) -> None:
    now = Value(key="k", value=value, display=display, origin="results")
    assert _same_printed(printed, now) is same


def test_a_printed_value_that_is_no_number_is_text() -> None:
    assert _printed("2.3 (1.9 to 2.8)") is None and _printed("1,23") is None
    assert _printed("-") is None and _printed("%") is None and _printed(".") is None


# ---------------------------------------------------------------------- the record


@pytest.mark.parametrize(
    ("entry", "said"),
    [
        (_entry(revision="v1"), "revision"),
        (_entry(pairs=[{"earlier": "a", "here": "b"}]), "'project' is a dependency of 'pairs'"),
        (_entry(project="../x", files_unavailable="lost"), "should not be valid"),
        (_entry(pairs=[{"earlier": "a", "here": "b", "manuscript_says": "It."}]), "because"),
        ({"id": "a", "kind": "abstract", "shares": ["data"]}, "any of the given schemas"),
        (_entry(shares=[]), "shares"),
    ],
)
def test_a_record_out_of_shape_is_refused(project: Path, entry: dict, said: str) -> None:
    _declare(project, entry)
    report = _check(project)
    assert {f.code for f in report.findings} == {"schema-violation"}
    assert said in " ".join(f.message for f in report.findings)


def test_two_outputs_of_one_id_are_refused(project: Path) -> None:
    _declare(project, _entry(), _entry())
    assert _found(_check(project)) == [("related-id-repeated", FAIL)]


def test_a_finding_points_at_its_entry(project: Path) -> None:
    path = _declare(project, _entry(project="../a"), _entry(id="second", project="../b"))
    lines = path.read_text(encoding="utf-8").splitlines()
    found = _check(project).findings
    assert [lines[f.line - 1].strip() for f in found] == ["- id: abstract", "- id: second"]


# ---------------------------------------------------------------------- the command


def test_related_take_and_list(project: Path, earlier: Path, capsys) -> None:
    _set(earlier, "cohort.n_reports", 4012, "4012")
    _declare(project, _entry(project="../earlier"))
    assert main(["related", str(project), "--take"]) == 0
    copied = "abstract: copied ../earlier into literature/related/abstract/"
    assert copied in capsys.readouterr().out
    assert (project / "literature" / "related" / "abstract" / SNAPSHOT_FILE).is_file()
    assert main(["related", str(project)]) == 0
    printed = capsys.readouterr().out
    assert "cohort.n_reports: 4012 there, 4000 here: differs" in printed
    assert "case.n_cases: 77 there, 77 here: same" in printed
    assert main(["related", str(project), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["outputs"][0]["copy"]["project"] == "../earlier"
    assert [f["code"] for f in said["findings"]] == ["related-number-differs"]


def test_related_without_a_record_or_with_an_unknown_id(project: Path, capsys) -> None:
    assert main(["related", str(project)]) == 2
    _declare(project, _entry())
    assert main(["related", str(project), "--take", "nope"]) == 2
    assert main(["related", str(project), "--take"]) == 2
    assert "names its project" in capsys.readouterr().err


def test_check_reports_the_difference_under_g8(project: Path, earlier: Path, capsys) -> None:
    _set(earlier, "cohort.n_reports", 4012, "4012")
    _declare(project, _entry(project="../earlier"))
    _take(project)
    main(["check", str(project), "--json", "--stage", "submission"])
    said = json.loads(capsys.readouterr().out)
    (found,) = [f for f in said["findings"] if f["code"].startswith("related-")]
    assert (found["gate"], found["code"], found["severity"]) == ("G8", "related-number-differs",
                                                                  "fail")  # fmt: skip
