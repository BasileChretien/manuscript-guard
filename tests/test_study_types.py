"""The table of study designs: each design's plan sections, where each comes from, and the
guidelines its paper follows (src/manuscript_guard/data/study_types.yaml)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from manuscript_guard.gates.design import OTHER, REQUIRED, study_types

SCHEMAS = Path(__file__).resolve().parent.parent / "src" / "manuscript_guard" / "contracts"
TABLE = SCHEMAS.parent / "data" / "study_types.yaml"


def test_the_designs_paper_yaml_takes_are_the_table_s() -> None:
    schema = json.loads((SCHEMAS / "schemas" / "paper.schema.json").read_text(encoding="utf-8"))
    taken = schema["properties"]["study_type"]["enum"]
    # And `other`, last, for a design none of them is: it asks for the seven sections only.
    assert set(taken) == set(study_types()) | {OTHER} and taken[-1] == OTHER
    assert OTHER not in study_types()
    assert f"`{OTHER}`" in schema["properties"]["study_type"]["description"]


@pytest.mark.parametrize("design", sorted(study_types()))
def test_each_section_says_where_it_comes_from_and_when_it_was_read(design: str) -> None:
    entry = study_types()[design]
    assert entry["label"] and entry["guidelines"] and _sentence_part(entry["describes"])
    ids = [section["id"] for section in entry["sections"]]
    assert len(ids) == len(set(ids)), ids
    assert not set(ids) & {name for name, _pattern, _purpose in REQUIRED}, ids
    for section in entry["sections"]:
        assert set(section) == {"id", "heading", "says", "ask", "explain", "source", "url",
                                "read_on"}, section  # fmt: skip
        assert section["url"].startswith("https://"), section
        assert isinstance(section["read_on"], date), section
        # A heading named as the section is found by its pattern.
        assert re.search(section["heading"], section["id"].capitalize()), section["id"]
        _asked(section)


def _sentence_part(text: object) -> bool:
    """Words that run on from a label: a lower-case start, no full stop at the end."""
    return isinstance(text, str) and text[:1].islower() and not text.rstrip().endswith(".")


def _asked(section: dict) -> None:
    """A section's question for an author new to plans, and why a reader needs its answer:
    one question, ending in its mark, and sentences that end in theirs."""
    ask, explain = " ".join(section["ask"].split()), " ".join(section["explain"].split())
    assert ask.endswith("?") and ask[:1].isupper(), (section["id"], ask)
    assert explain.endswith(".") and explain[:1].isupper(), (section["id"], explain)


def test_starting_the_command_line_reads_no_table() -> None:
    """Round 1 of the first plan pull request: `REQUIRED` came from the table, and a module the
    command line imports at its start took the Deviations pattern from it there, so every
    command and every hook parsed `study_types.yaml`, about 120 ms without libyaml, where it
    had read nothing. The table is read when a gate first asks for it."""
    import subprocess
    import sys

    found = subprocess.run(
        [sys.executable, "-c", "import manuscript_guard.cli; from manuscript_guard.gates import "
         "design; print(design._table.cache_info().currsize)"],
        capture_output=True, text=True, timeout=120, check=True,
    )  # fmt: skip
    assert found.stdout.strip() == "0", found.stdout + found.stderr


def test_every_plan_s_seven_sections_are_read_from_the_table() -> None:
    """The seven sections every plan has are the table's `every_plan`, in their order, each
    asked and explained as a design's own are (DESIGN.md, "One set of plan questions"). A
    design's section never takes one of their ids, which `required_for` would then ask for
    twice."""
    from manuscript_guard.gates.design import every_plan

    table = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
    assert [section["id"] for section in table["every_plan"]] == [
        "question", "design", "population", "exposure", "outcome", "analysis", "deviations"]
    assert REQUIRED == every_plan() == tuple(
        (s["id"], s["heading"], s["says"]) for s in table["every_plan"])  # fmt: skip
    for section in table["every_plan"]:
        assert set(section) == {"id", "heading", "says", "ask", "explain"}, section
        assert re.search(section["heading"], section["id"].capitalize()), section["id"]
        _asked(section)


SKILLS = Path(__file__).resolve().parent.parent / "plugin" / "skills"


def test_the_reporting_skill_s_table_is_the_designs_table() -> None:
    """One table, not two: each design's row names the guidelines G5 holds it to."""
    text = (SKILLS / "reporting-checklist" / "SKILL.md").read_text(encoding="utf-8")
    rows = {
        cells[1]: cells[2] + " " + cells[3]
        for cells in (line.split("|") for line in text.splitlines() if line.startswith("| "))
        if len(cells) > 4
    }
    for design, entry in study_types().items():
        row = rows[f" {design} "]
        for name in entry["guidelines"] + entry.get("protocol", []):
            assert name in row, (design, name, row)


def test_the_plan_skill_says_what_each_design_s_section_answers() -> None:
    text = (SKILLS / "analysis-plan" / "references" / "study-designs.md").read_text(
        encoding="utf-8"
    )
    parts = dict(re.findall(r"^## (\S+)\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL))
    assert set(parts) == set(study_types())
    for design, entry in study_types().items():
        for section in entry["sections"]:
            assert f"**{section['id'].capitalize()}.**" in parts[design], (design, section["id"])
