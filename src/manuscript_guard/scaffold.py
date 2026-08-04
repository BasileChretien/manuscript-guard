"""Creating a new manuscript project.

The first `manuscript-guard check` on a fresh project deliberately fails, and reads as a
to-do list: name your authors, run an analysis. Optional fields the author has not reached
yet are left out entirely rather than written empty, so the failures that do appear are all
real work rather than placeholder noise.
"""

from __future__ import annotations

from pathlib import Path

PAPER = """\
schema: manuscript-guard/paper/1
title: "{title}"
english_variant: en-GB

# Where the work has got to. Move it along as you go; `manuscript-guard stages` lists what
# each one starts to enforce. Written here rather than left to the default, because the
# default is `drafting` — so a project on its first day was held to drafting standards, which
# is the wall of red the stage ladder exists to prevent.
#   design           the analysis plan; no analysis or manuscript yet
#   analysis         writing and running the analysis
#   drafting         writing the manuscript against results that exist
#   internal-review  draft complete; panels, checklists and the journal's rules apply
#   submission       the version you send anywhere
stage: design

# Set once you have chosen a journal; enables the journal gate.
# target_journal: drug-safety

reporting_guideline: []

# Numbers that are writing conventions rather than findings. Every addition needs a
# reason, because an allowlist that grows without argument eventually swallows the
# numbers it was meant to police.
conventions: []

# Tokens containing digits that are names, not claims.
terms: []
"""

AUTHORS = """\
schema: manuscript-guard/authors/1

affiliations:
  - id: a1
    text: "Department, Institution, City, Country"

authors:
  - given: ""
    family: ""
    affiliations: [a1]
    corresponding: true
    equal_contribution: false
    # Optional, and omitted until you have them. Many journals now require both.
    # degrees: [PharmD, MSc]
    # orcid: 0000-0000-0000-0000
    # email: you@institution.example
    # credit: [Conceptualization, Formal analysis, Writing – original draft]
    # competing_interests: "None declared."
"""

LEDGER = """\
schema: manuscript-guard/ledger/1

# Numbers taken from published work, each bound to a source stored under sources/.
# Values you verified in a source that could not be stored belong in attested.yaml.
entries: []
"""

ATTESTED = """\
schema: manuscript-guard/attested/1

# Values you personally read in a source the toolkit could not retrieve and store.
# Kept separate from the ledger so the set resting on a person's word stays reviewable.
#
# entries:
#   - key: agency2019.exposure_estimate
#     value: 41200
#     display: "41 200"
#     source: "National Agency annual report 2019, print edition, no online copy"
#     locator: "Table 14, p. 88"
#     statement: "Read from the printed report held at the hospital library; the agency
#                 withdrew the PDF in 2021 and no archive copy exists."
#     attested_by: ""
#     attested_on: 2026-01-01
entries: []
"""

MANUSCRIPT = """\
---
title: "{title}"
---

# Introduction

<!--
Write here. Any number you quote must be a binding: {{{{results.some_key}}}} for something
your analysis computed, or {{{{lit.some_key}}}} for something taken from the literature.
A bare number in this file is a defect unless it is a recognised convention such as
p < 0.05, or a pointer such as Table 1.

An HTML comment for two reasons. It does not reach the built document, so scaffolding left
in place cannot be published by an author who forgot it was there — and it is masked, so
this paragraph's own "p < 0.05" does not trip the gate it is describing. That example is a
convention only where the manuscript describes its own method; here in the Introduction it
would be a reported finding, and reporting one means binding it.
-->

# Methods

# Results

# Discussion
"""

GITIGNORE = """\
build/
.Rproj.user/
__pycache__/
"""

README = """\
# {title}

Checked by [manuscript-guard](https://github.com/BasileChretien/manuscript-guard).

    manuscript-guard check

Numbers in `manuscript/` are bindings into `results/` (written by the analysis) and
`literature/` (extracted from sources). Nothing is typed by hand, so nothing goes stale.
"""

PLAN = """\
# Analysis plan

Agreed <date>, before the analysis was written.

Write down what you intend to do before you do it. Not because deviating is wrong — most
real analyses deviate — but because a deviation that was declared is a decision, and one
nobody recorded is indistinguishable from having tried several things and reported the best.

## Research question

## Design

## Population and data source

## Exposure

## Outcome

## Analysis

## Sample size

## Sensitivity analyses

## Deviations from the plan

None so far.
"""

_FILES = {
    "paper.yaml": PAPER,
    "design/plan.md": PLAN,
    "authors.yaml": AUTHORS,
    "literature/ledger.yaml": LEDGER,
    "literature/attested.yaml": ATTESTED,
    "manuscript/main.md": MANUSCRIPT,
    ".gitignore": GITIGNORE,
    "README.md": README,
}

_DIRS = ("analysis", "results", "literature/sources", "figures", "review", "build")


def init_project(root: Path, title: str = "Untitled manuscript") -> list[Path]:
    """Create the project layout. Existing files are never overwritten."""
    root = Path(root).resolve()
    created: list[Path] = []

    for name in _DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)

    for name, template in _FILES.items():
        path = root / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(template.format(title=title), encoding="utf-8", newline="\n")
        created.append(path)

    keep = root / "results" / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8", newline="\n")

    return created
