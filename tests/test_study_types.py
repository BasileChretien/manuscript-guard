"""The table of study designs: each design's plan sections, where each comes from, and the
guidelines its paper follows (src/manuscript_guard/data/study_types.yaml)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from manuscript_guard.gates.design import REQUIRED, study_types

SCHEMAS = Path(__file__).resolve().parent.parent / "src" / "manuscript_guard" / "contracts"


def test_the_designs_paper_yaml_takes_are_the_table_s() -> None:
    schema = json.loads((SCHEMAS / "schemas" / "paper.schema.json").read_text(encoding="utf-8"))
    assert set(schema["properties"]["study_type"]["enum"]) == set(study_types())


@pytest.mark.parametrize("design", sorted(study_types()))
def test_each_section_says_where_it_comes_from_and_when_it_was_read(design: str) -> None:
    entry = study_types()[design]
    assert entry["label"] and entry["guidelines"]
    ids = [section["id"] for section in entry["sections"]]
    assert len(ids) == len(set(ids)), ids
    assert not set(ids) & {name for name, _pattern, _purpose in REQUIRED}, ids
    for section in entry["sections"]:
        assert set(section) == {"id", "heading", "says", "source", "url", "read_on"}, section
        assert section["url"].startswith("https://"), section
        assert isinstance(section["read_on"], date), section
        # A heading named as the section is found by its pattern.
        assert re.search(section["heading"], section["id"].capitalize()), section["id"]


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
