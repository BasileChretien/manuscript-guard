"""The graphical abstract's templates: what each of its three panels is headed.

A template is chosen by the paper's design (`study_type` in paper.yaml), or named with
`communicate graphical-abstract --template`. It changes the panels' headings and nothing
else: what a panel holds is the brief's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Template:
    name: str
    #: The headings of the three panels: what was asked and how, what was found, what it
    #: means.
    headings: tuple[str, str, str]


TEMPLATES = {
    "rct": Template("rct", ("The trial", "The result", "What it means")),
    "observational": Template("observational", ("The study", "The finding", "What it means")),
    "lab": Template("lab", ("The experiment", "The result", "What it means")),
    "computational": Template("computational", ("The model", "How it performs", "What it means")),
    "systematic-review": Template(
        "systematic-review", ("The evidence", "The pooled result", "What it means")
    ),
    "methods": Template("methods", ("The method", "What it shows", "What it means")),
}
#: The template each design of paper.yaml's `study_type` takes.
BY_STUDY_TYPE = {
    "trial": "rct",
    "cohort": "observational",
    "case-control": "observational",
    "self-controlled": "observational",
    "disproportionality": "observational",
    "systematic-review": "systematic-review",
    "prediction-model": "computational",
}
#: The template of a paper that declares no design.
DEFAULT = "observational"


def chosen(named: str | None, study_type: str | None) -> tuple[Template, str]:
    """The template to draw, and why it is that one."""
    if named:
        return TEMPLATES[named], "named with --template"
    if study_type in BY_STUDY_TYPE:
        return TEMPLATES[BY_STUDY_TYPE[study_type]], f"the template for study_type {study_type}"
    return TEMPLATES[DEFAULT], "paper.yaml declares no study_type; --template names another"
