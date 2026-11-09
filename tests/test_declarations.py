"""What the plan declares in a YAML block: its controls and its held-out data (items 5 and 11).

DESIGN.md, "Controls the plan declares, and data held out until the model is fixed". The
reader is held over generated plans in `tests/test_properties.py`; these pin each part of
the form, and each refusal, by name.
"""

from __future__ import annotations

import pytest

from manuscript_guard.gates.declarations import read_declarations, without_declarations

GOOD = """\
# Plan

## Control analyses

```yaml
controls:
  - key: control.shuffled
    kind: simulated
    of: ror.*
    expected: 1
    rule: holds-expected
  - key: control.headache
    kind: negative
    of: results.ror.point
    expected: 1
    rule: holds-null
  - key: control.bleeding
    kind: positive
    of: ror.point
    expected: 3.2
    rule: within
    distance: 1.0
held_out:
  - input: ./data/validation.csv
    validated_by: analysis/03_validate.py
    model: [models/a.pkl, models/b.pkl]
    read_by: analysis/02_describe.py
```
"""


def _control(**fields: object) -> str:
    entry = {"key": "control.x", "kind": "negative", "of": "ror.*", "expected": 1,
             "rule": "holds-null", **fields}  # fmt: skip
    lines = [f"    {name}: {value}" for name, value in entry.items() if value is not None]
    lines[0] = "  - " + lines[0].lstrip()
    return "```yaml\ncontrols:\n" + "\n".join(lines) + "\n```\n"


def test_each_part_of_the_form_is_read() -> None:
    read = read_declarations(GOOD)
    assert read.declared and not read.unreadable
    assert [(c.key, c.kind, c.of, c.group, c.expected, c.rule, c.distance)
            for c in read.controls] == [
        ("control.shuffled", "simulated", "ror", True, 1.0, "holds-expected", None),
        ("control.headache", "negative", "ror.point", False, 1.0, "holds-null", None),
        ("control.bleeding", "positive", "ror.point", False, 3.2, "within", 1.0),
    ]  # fmt: skip
    (held,) = read.held_out
    assert (held.input, held.validated_by, held.model, held.read_by) == (
        "data/validation.csv", "analysis/03_validate.py", ("models/a.pkl", "models/b.pkl"),
        ("analysis/02_describe.py",))  # fmt: skip
    assert held.readers() == ("analysis/03_validate.py", "analysis/02_describe.py")
    lines = GOOD.splitlines()
    assert [c.line for c in read.controls] == [
        lines.index("  - key: " + key) + 1
        for key in ("control.shuffled", "control.headache", "control.bleeding")
    ]


def test_a_plan_with_no_block_declares_nothing() -> None:
    read = read_declarations("# Plan\n\n## Analysis\n\n```yaml\nmodel: glm\n```\n")
    assert not read.declared and not read.controls and not read.unreadable


@pytest.mark.parametrize(
    ("fields", "said"),
    [
        ({"kind": "placebo"}, "kind"),
        ({"rule": "close-enough"}, "rule"),
        ({"expected": ".inf"}, "not a number"),
        ({"expected": ".nan"}, "not a number"),
        ({"expected": "true"}, "not a number"),
        ({"expected": "1e-3"}, "not a number"),
        ({"rule": "holds-null", "expected": 2}, "expects the null"),
        ({"rule": "within"}, "distance"),
        ({"rule": "within", "distance": 0}, "distance"),
        ({"rule": "within", "distance": ".inf"}, "distance"),
        ({"distance": 1.0}, "only with the rule within"),
        ({"key": "Control.X"}, "not one the emitter takes"),
        ({"of": "ror point"}, "names no result"),
        ({"of": None}, "gives no of"),
        ({"colour": "red"}, "not a field"),
        # Round 3 of #590: a control whose values fall under its own `of`.
        ({"key": "ror.shuffled"}, "stand beside itself"),
        ({"key": "ror"}, "stand beside itself"),
        ({"key": "ror", "of": "results.ror.point"}, "stand beside itself"),
    ],
)
def test_an_entry_that_breaks_the_form_is_said_at_its_line_and_left_out(
    fields: dict, said: str
) -> None:
    plan = "# Plan\n\n" + _control(**fields)
    read = read_declarations(plan)
    assert read.declared and not read.controls
    (problem,) = read.unreadable
    assert said in problem.message, problem.message
    lines = plan.splitlines()
    # A field the form does not have is said at its own line; the rest, at the entry's.
    at = "    colour: red" if "colour" in fields else "  - key: " + str(fields.get("key",
                                                                          "control.x"))  # fmt: skip
    assert lines[problem.line - 1] == at


def test_a_field_given_twice_is_said_where_yaml_would_drop_the_first() -> None:
    plan = "# Plan\n\n" + _control().replace("    rule:", "    kind: positive\n    rule:")
    (problem,) = read_declarations(plan).unreadable
    assert "kind is given twice" in problem.message
    assert plan.splitlines()[problem.line - 1] == "    kind: positive"


def test_a_key_or_an_input_declared_twice_is_read_in_neither_place() -> None:
    twice = GOOD.replace("control.headache", "control.shuffled")
    read = read_declarations(twice)
    assert [c.key for c in read.controls] == ["control.bleeding"]
    assert [p.message for p in read.unreadable] == ["the control control.shuffled is declared "
                                                    "twice"]  # fmt: skip
    again = GOOD + ("\n```yaml\nheld_out:\n  - input: data/other.csv\n"
                    "    validated_by: analysis/x.py\n```\n")  # fmt: skip
    read = read_declarations(again)
    assert [h.input for h in read.held_out] == ["data/validation.csv"]
    (problem,) = read.unreadable
    assert "declared in another block" in problem.message
    assert again.splitlines()[problem.line - 1] == "held_out:"


def test_a_block_that_is_not_yaml_is_said_where_it_seems_to_declare() -> None:
    plan = "# Plan\n\n```yaml\nheld_out: [ {input: x\n```\n\n```yaml\nnot: [ yaml\n```\n"
    read = read_declarations(plan)
    assert read.declared
    (problem,) = read.unreadable
    assert problem.message.startswith("the block is not YAML")


@pytest.mark.parametrize(
    "fence",
    ["```yaml\n{body}```\n", "~~~yaml\n{body}~~~\n", "```` yaml\n{body}````\n",
     "``` {{.yaml}}\n{body}```\n", "```YAML\n{body}```\n"],  # fmt: skip
)
def test_a_block_is_found_as_pandoc_finds_a_fenced_yaml_block(fence: str) -> None:
    body = GOOD.split("```yaml\n", 1)[1].rsplit("```", 1)[0]
    read = read_declarations("# Plan\n\n" + fence.format(body=body))
    assert len(read.controls) == 3 and len(read.held_out) == 1


def test_a_block_commented_out_or_in_the_front_matter_or_of_another_language_is_not_read() -> None:
    body = GOOD.split("```yaml\n", 1)[1].rsplit("```", 1)[0]
    for plan in (
        f"# Plan\n\n<!--\n```yaml\n{body}```\n-->\n",
        f"---\ntitle: x\n{body}---\n\n# Plan\n",
        f"# Plan\n\n```python\n{body}```\n",
        f"# Plan\n\n```\n{body}```\n",
    ):
        assert not read_declarations(plan).declared, plan


def test_the_deviations_are_read_without_the_blocks_their_lines_kept() -> None:
    """Round 1 of #590: a block under the Deviations named its own keys there."""
    plan = GOOD.replace("## Control analyses", "## Deviations from the plan")
    left = without_declarations(plan)
    assert "control.shuffled" not in left and "validation.csv" not in left
    assert left.count("\n") == plan.count("\n")
    assert without_declarations("# Plan\n\n```yaml\nmodel: glm\n```\n") == \
        "# Plan\n\n```yaml\nmodel: glm\n```\n"  # fmt: skip


def test_a_block_that_does_not_read_is_left_out_of_the_deviations_too() -> None:
    """Round 2 of #590: one that is not YAML still named what it held."""
    plan = "## Deviations from the plan\n\n```yaml\ncontrols:\n  - of: ror.point\n  - [\n```\n"
    assert "ror.point" not in without_declarations(plan)
