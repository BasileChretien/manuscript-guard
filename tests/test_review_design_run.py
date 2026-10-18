"""A design round read by the models: the plan is sent, and the manuscript is not.

`review --design --run` plans and sends a design round as `review --run` does a manuscript
round, from `review/design/`. What differs is what is read: the facts about the paper, the
plan as the build would print it, with only the feasibility results printed into it, and the
feasibility results themselves. Each reply is filed as a design reading, with the digest of
the plan, and G12 reads it.

No test here opens a connection: the transport is the one `test_review_run` replaces.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from test_corruption import _feasibility_said, _plan_edited
from test_review_run import KEY_A, KEY_B, MODEL_A, MODEL_B, Providers, answer, configure, reply_text

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.gates.design_review import check_design_rounds, plan_digest
from manuscript_guard.panel import client

#: A result the analysis has emitted that is not a feasibility one. A design round reads the
#: plan before there are results, so the plan's binding to it is sent as written.
OTHER = "ror.point"


@pytest.fixture
def providers(monkeypatch) -> Providers:
    transport = Providers()
    monkeypatch.setattr(client, "default_transport", transport)
    monkeypatch.setenv("OPENAI_API_KEY", KEY_A)
    monkeypatch.setenv("MISTRAL_API_KEY", KEY_B)
    return transport


@pytest.fixture
def planned(project: Path) -> Path:
    """The example, to be read by two models, with a plan that binds a feasibility result
    and a result of the analysis."""
    configure(project, MODEL_A, MODEL_B)
    _feasibility_said(project, "design", feasibility__n_reports=4000)
    _plan_edited(
        project, "## Outcome",
        "## Outcome\n\nAbout {{results.feasibility.n_reports}} reports; the ratio is "
        f"{{{{results.{OTHER}}}}}.\n",
    )  # fmt: skip
    return project


def design_run(root: Path, *flags: str) -> int:
    return main(["review", str(root), "--design", "--run", *flags])


def design_readings(root: Path, number: int = 1) -> list[Path]:
    return sorted((root / "review" / "design" / f"round-{number}").glob("*.*.yaml"))


def test_a_design_dry_run_sends_the_plan_and_the_feasibility_results(
    planned: Path, capsys
) -> None:
    """Item 46: `review --run` sent the manuscript, and nothing sent the plan."""
    assert design_run(planned, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "Design round 1: 2 reviewers x 2 models = 4 calls" in out
    assert "There is no review/design/panel-1.yaml" in out
    assert "Not sent: the manuscript, results other than feasibility.*" in out
    folder = planned / "build" / "review" / "design" / "round-1" / "dry-run"
    assert sorted(path.name for path in folder.glob("*.json")) == sorted(
        f"{reviewer}.{model}.json" for reviewer in ("design-methods", "statistics")
        for model in ("openai-model-a", "mistral-model-b")
    )  # fmt: skip
    text = (folder / "as-text.txt").read_text(encoding="utf-8")
    assert "What design round 1 of the panel would be sent." in text
    assert "reviewing the analysis plan of a study before its analysis is run" in text
    assert "About 4000 reports; the ratio is {{results." + OTHER + "}}." in text
    assert "feasibility.n_reports: 4000" in text
    assert "# The manuscript" not in text and "<<<BEGIN manuscript/" not in text
    # A dry run files nothing, and names no reader.
    assert not (planned / "review" / "design").exists()


def test_a_design_round_asks_what_the_declared_study_design_needs(
    planned: Path, capsys
) -> None:
    """Item 46: the remits name the risks of the study type. The design's own sections
    (`data/study_types.yaml`) are sent with their sources where paper.yaml declares one, and
    nothing of them where it declares none."""
    folder = planned / "build" / "review" / "design" / "round-1" / "dry-run"
    assert design_run(planned, "--dry-run") == 0
    capsys.readouterr()
    assert "What this study design needs" not in (folder / "as-text.txt").read_text("utf-8")
    paper = planned / "paper.yaml"
    paper.write_text(paper.read_text(encoding="utf-8") + "\nstudy_type: cohort\n",
                     encoding="utf-8")  # fmt: skip
    assert design_run(planned, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "study type: cohort" in out, out
    text = (folder / "as-text.txt").read_text(encoding="utf-8")
    assert "# What this study design needs" in text
    assert "The plan is for a cohort study (study_type: cohort)" in text
    for section in ("time zero and follow-up", "confounding", "missing data"):
        assert f"- {section}: " in text, section


def test_a_table_the_plan_binds_is_sent_as_written(planned: Path, capsys) -> None:
    """Round 1 of #316: a value binding was printed only for a feasibility result, and a
    table binding for any table the analysis had emitted. No table is a feasibility one."""
    import json

    from manuscript_guard.emit import write_digest

    fragment = next((planned / "results").glob("*.json"))
    document = json.loads(fragment.read_text(encoding="utf-8"))
    table = {"columns": ["Group", "Reports"], "rows": [["Exposed", "SECRET-ROW-426"]]}
    document.setdefault("tables", {})["baseline"] = table
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    _plan_edited(planned, "## Outcome", "## Outcome\n\nTable 1 will be {{table.baseline}}.\n")
    assert design_run(planned, "--dry-run") == 0
    assert "would be sent as written" in capsys.readouterr().out
    folder = planned / "build" / "review" / "design" / "round-1" / "dry-run"
    text = (folder / "as-text.txt").read_text(encoding="utf-8")
    assert "Table 1 will be {{table.baseline}}." in text
    assert "SECRET-ROW-426" not in text


def test_the_design_instructions_name_no_manuscript() -> None:
    """Round 1 of #316: three places still pointed the reader at a manuscript it is not
    sent."""
    from manuscript_guard.panel.prompt import DESIGN_SYSTEM

    assert "manuscript" not in DESIGN_SYSTEM.lower()


def test_a_design_run_files_a_design_reading_for_each_reviewer_and_model(
    planned: Path, providers: Providers, capsys
) -> None:
    assert design_run(planned, "--yes") == 0
    assert len(providers.requests) == 4
    assert all(b"About 4000 reports" in request.body for request in providers.requests)
    assert not any(b"<<<BEGIN manuscript/" in request.body for request in providers.requests)

    filed = design_readings(planned)
    assert [path.name for path in filed] == sorted(
        f"{reviewer}.{model}.yaml" for reviewer in ("design-methods", "statistics")
        for model in ("mistral-model-b", "openai-model-a")
    )  # fmt: skip
    digest = plan_digest(load_project(planned)[0])
    for path in filed:
        document = read_structured(path)
        assert validate(document, "design-review", path).ok, path.name
        assert document["plan_sha256"] == digest
        assert document["reader"] in (MODEL_A, MODEL_B)
        assert "reading_sha256" in document and "manuscript_sha256" not in document
        assert [finding["id"] for finding in document["findings"]] == ["d1-01"]
    panel = yaml.safe_load((planned / "review" / "design" / "panel-1.yaml").read_text("utf-8"))
    assert panel["rationale"].startswith("Starter design panel")
    assert [reviewer["readers"] for reviewer in panel["reviewers"]] == [[MODEL_A, MODEL_B]] * 2
    # G12 reads every one of them, and has nothing to say of a minor finding.
    assert check_design_rounds(load_project(planned)[0]).findings == ()
    assert "Filed 4 of 4 readings in review/design/round-1/." in capsys.readouterr().out

    # The round asked for again sends nothing: every reading is on file. The next round
    # needs a panel of its own, which the run says, sending nothing either.
    providers.requests.clear()
    assert design_run(planned, "--yes", "--round", "1") == 0
    assert "already on file" in capsys.readouterr().out
    assert design_run(planned, "--yes") == 2
    assert providers.requests == []


def test_a_design_major_from_a_model_is_said_until_it_is_answered(
    planned: Path, providers: Providers
) -> None:
    major = [{"severity": "major", "finding": "Time before the first prescription is "
              "counted as exposed, which is immortal time."}]  # fmt: skip
    providers.default = lambda request: answer(reply_text("major-revision", major))
    assert design_run(planned, "--yes", "--one-each") == 0
    said = check_design_rounds(load_project(planned)[0]).findings
    assert [(f.code, f.severity) for f in said] == [("design-major-open", "warn")] * 2
    assert said[0].message.startswith("design round 1: design-methods (openai/model-a) d1-01:")


def test_a_later_design_round_needs_a_panel_of_its_own(planned: Path, capsys) -> None:
    assert design_run(planned, "--round", "2", "--dry-run") == 2
    assert "design round 2 has no panel, and only the first has a starter" in (
        capsys.readouterr().err
    )


def test_a_design_round_with_no_plan_sends_nothing(planned: Path, capsys) -> None:
    (planned / "design" / "plan.md").unlink()
    assert design_run(planned, "--dry-run") == 2
    assert "there is no design/plan.md to review" in capsys.readouterr().err


def test_a_design_round_does_not_list_the_providers(planned: Path, capsys) -> None:
    assert main(["review", str(planned), "--design", "--providers"]) == 2
    assert "--design is a design round" in capsys.readouterr().err
