"""The emitter's side of items 5 and 11: `control()`, and the record of first reads.

DESIGN.md, "Controls the plan declares, and data held out until the model is fixed". The R
emitter is held to the same in `tests/test_r_emitter.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_results
from manuscript_guard.contracts.values import DisplayError
from manuscript_guard.emit import FIRST_READS, Emitter, record_first_reads

PLAN = (
    "# Plan\n\n## Validation\n\n```yaml\nheld_out:\n  - input: data/validation.csv\n"
    "    validated_by: analysis/validate.py\n    model: models/model.txt\n```\n"
)


def _project(tmp_path: Path, plan: str | None = PLAN) -> Path:
    root = tmp_path / "paper"
    for folder in ("analysis", "data", "design", "models"):
        (root / folder).mkdir(parents=True)
    (root / "paper.yaml").write_text("schema: manuscript-guard/paper/1\ntitle: P\n",
                                     encoding="utf-8")  # fmt: skip
    if plan is not None:
        (root / "design" / "plan.md").write_bytes(plan.encode("utf-8"))
    for name in ("real.csv", "simulated.csv", "validation.csv"):
        (root / "data" / name).write_text(f"{name}\n1\n", encoding="utf-8")
    (root / "models" / "model.txt").write_text("beta 1.2\n", encoding="utf-8")
    for name in ("analysis.py", "validate.py", "develop.py"):
        (root / "analysis" / name).write_text("# script\n", encoding="utf-8")
    return root


def test_a_control_is_published_as_an_interval_and_named(tmp_path: Path) -> None:
    root = _project(tmp_path)
    em = Emitter(root / "analysis" / "analysis.py", inputs=["data/real.csv"], root=root)
    em.interval("ror", 3.84, 2.10, 7.02, digits=2)
    em.control("control.shuffled", 1.04, 0.81, 1.33, inputs=["data/simulated.csv"], digits=2)
    em.control("control.headache", 0.97, 0.70, 1.35, digits=2)
    document = json.loads(em.write().read_text(encoding="utf-8"))
    assert document["controls"] == {"control.shuffled": {"inputs": ["data/simulated.csv"]},
                                    "control.headache": {"inputs": []}}  # fmt: skip
    values = document["values"]
    assert values["control.shuffled.point"]["display"] == "1.04"
    assert values["control.shuffled.ci_low"]["bounds"] == "control.shuffled.point"
    assert values["control.headache.ci_high"].get("quoted", True) is True, "quoted"
    inputs = {i["path"]: i for i in document["provenance"]["inputs"]}
    assert inputs["data/simulated.csv"]["synthetic"] is True
    assert inputs["data/simulated.csv"]["control"] == "control.shuffled"
    assert "control" not in inputs["data/real.csv"] and "synthetic" not in inputs["data/real.csv"]
    results, report = load_results(root / "results")
    assert report.ok, report.findings
    assert results.fragments[0].controls == document["controls"]


@pytest.mark.parametrize(
    ("call", "refusal"),
    [
        (lambda em: em.control("Control", 1, 0, 2), "a key is lower case"),
        (lambda em: (em.control("c.x", 1, 0, 2), em.control("c.x", 1, 0, 2)), "emitted once"),
        (lambda em: em.control("c.x", 3, 0, 2), "does not bracket"),
        (lambda em: em.control("c.x", 1, 0, 2, inputs=["data/real.csv"]), "an input of the run"),
        (lambda em: (em.control("c.x", 1, 0, 2, inputs=["data/simulated.csv"]),
                     em.control("c.y", 1, 0, 2, inputs=["data/simulated.csv"])),
         "control c.x's data"),  # fmt: skip
        (lambda em: (em.control("c.x", 1, 0, 2, inputs=["data/simulated.csv"]),
                     em.add_input("data/simulated.csv")), "control c.x's data"),  # fmt: skip
        # Round 1: declared synthetic again, it kept the control's mark.
        (lambda em: (em.control("c.x", 1, 0, 2, inputs=["data/simulated.csv"]),
                     em.add_input("data/simulated.csv", synthetic=True)),
         "control c.x's data"),  # fmt: skip
    ],
)
def test_a_control_refuses_what_it_cannot_record(tmp_path: Path, call, refusal: str) -> None:
    """A control's own data are read by nothing else in the run: declared also as the run's,
    the run's other results could not be told from the control's."""
    root = _project(tmp_path)
    em = Emitter(root / "analysis" / "analysis.py", inputs=["data/real.csv"], root=root)
    with pytest.raises((DisplayError, ValueError), match=refusal):
        call(em)


def _reads(root: Path) -> list[tuple[str, str]]:
    record = json.loads((root / FIRST_READS).read_text(encoding="utf-8"))
    return [(read["script"], read["input"]) for read in record["reads"]]


def test_each_script_s_first_read_of_each_input_is_recorded_once(tmp_path: Path) -> None:
    """Item 11: a fragment is written again on every run; the record keeps the first read,
    with the digests of the run's inputs and the plan it was written under."""
    root = _project(tmp_path)
    validate = Emitter(root / "analysis" / "validate.py",
                       inputs=["data/validation.csv", "models/model.txt"], root=root)  # fmt: skip
    validate.value("auc", 0.71, digits=2)
    validate.write()
    record = json.loads((root / FIRST_READS).read_text(encoding="utf-8"))
    first = record["reads"][0]
    assert _reads(root) == [("analysis/validate.py", "data/validation.csv"),
                            ("analysis/validate.py", "models/model.txt")]  # fmt: skip
    assert {i["path"] for i in first["inputs"]} == {"data/validation.csv", "models/model.txt"}
    assert record["plans"] == {first["plan"]: PLAN}

    (root / "models" / "model.txt").write_text("beta 9.9\n", encoding="utf-8")
    plan = root / "design" / "plan.md"
    plan.write_bytes((PLAN + "\nA sentence added.\n").encode("utf-8"))
    validate.write()
    assert json.loads((root / FIRST_READS).read_text(encoding="utf-8")) == record, \
        "an entry is never rewritten"  # fmt: skip

    develop = Emitter(root / "analysis" / "develop.py", inputs=["data/real.csv"], root=root)
    develop.add_input("data/simulated.csv", synthetic=True)
    develop.value("n", 2)
    develop.write()
    later = json.loads((root / FIRST_READS).read_text(encoding="utf-8"))
    assert _reads(root)[2:] == [("analysis/develop.py", "data/real.csv")], \
        "an input declared synthetic is no first read"  # fmt: skip
    assert later["reads"][:2] == record["reads"]
    assert len(later["plans"]) == 2 and later["reads"][2]["plan"] != first["plan"]


@pytest.mark.parametrize(
    "line",
    ["held_out:", "  held_out:", '"held_out":', "'held_out' :", "\theld_out :"],
)
def test_the_record_is_kept_once_a_line_opens_with_held_out(tmp_path: Path, line: str) -> None:
    root = _project(tmp_path, f"# Plan\n\n```yaml\n{line}\n  - input: x\n```\n")
    assert record_first_reads(root, "analysis/a.py", [{"path": "x", "sha256": "0" * 64}])
    assert _reads(root) == [("analysis/a.py", "x")]


@pytest.mark.parametrize(
    "plan",
    [None, "# Plan\n\n## Analysis\n\nNothing is held out.\n", "# Plan\n\nheld_out_data: x\n"],
)
def test_no_record_is_kept_where_the_plan_holds_no_held_out_line(tmp_path: Path, plan) -> None:
    root = _project(tmp_path, plan)
    em = Emitter(root / "analysis" / "analysis.py", inputs=["data/real.csv"], root=root)
    em.value("n", 1)
    em.write()
    assert not (root / FIRST_READS).exists()


def test_a_record_that_does_not_read_is_left_as_it_is(tmp_path: Path) -> None:
    """Never rewritten: a record edited by hand is the author's, and G12 says it is unread."""
    root = _project(tmp_path)
    record = root / FIRST_READS
    for written in ("not json", json.dumps({"schema": "other", "plans": {}, "reads": []})):
        record.write_text(written, encoding="utf-8")
        assert record_first_reads(root, "analysis/a.py", [{"path": "x", "sha256": "0" * 64}]) \
            is None  # fmt: skip
        assert record.read_text(encoding="utf-8") == written


def test_a_harvested_output_s_inputs_are_first_read_when_harvested(tmp_path: Path) -> None:
    from manuscript_guard.harvest.config import Entry
    from manuscript_guard.harvest.fragment import document_of, write_fragment

    root = _project(tmp_path)
    (root / "out.csv").write_text("name,value\nauc,0.71\n", encoding="utf-8")
    entry = Entry.from_spec({"key": "val", "output": "out.csv", "script": "analysis/validate.py",
                             "inputs": [{"path": "data/validation.csv"}],
                             "row_key": "name"})  # fmt: skip
    write_fragment(root, entry, document_of(root, entry, root / "out.csv"))
    assert _reads(root) == [("analysis/validate.py", "data/validation.csv")]
