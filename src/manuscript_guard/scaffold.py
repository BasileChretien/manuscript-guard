"""Creating a new manuscript project.

The first `manuscript-guard check` on a fresh project deliberately fails, and reads as a
to-do list: name your authors, run an analysis. Optional fields the author has not reached
yet are left out entirely rather than written empty, so the failures that do appear are all
real work rather than placeholder noise.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.contracts.project import (
    named,
    one_line,
    outside_maths,
    unprintable_character,
)

PAPER = """\
schema: manuscript-guard/paper/1
title: {quoted}
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
# target_journal: journal-of-examples

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
    # degrees: [MD, PhD]
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

BIBLIOGRAPHY = """\
% Written by `manuscript-guard sync-bib` from your Zotero library, and safe to commit:
% it is what CI and a co-author without your library format citations from.
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
{header}# Introduction

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

# Not cosmetic. Several of this toolkit's guarantees are byte-level: the .sha256 beside every
# results fragment, and the manuscript digest a review record is tied to. Git's default stores
# LF and hands Windows CRLF, so the same commit hashes differently on different machines and
# each of those checks reports a change nobody made. manuscript-guard's own repository hit
# exactly that — CI failing on Ubuntu and macOS while passing on the machine the digests were
# computed on — and fixed it with this file, which `init` then did not give to anyone else. A
# scaffolded project inherited the bug the toolkit had already cured for itself.
GITATTRIBUTES = """\
# Normalise line endings, and check them out as LF everywhere.
#
# manuscript-guard's digests are taken over file bytes. Without this, Git hands Windows CRLF
# and Linux LF for the same commit, the digests disagree across machines, and `check` reports
# an edit nobody made. `eol=lf` makes the working copy match the repository on every platform,
# so a digest computed anywhere is valid everywhere.
* text=auto eol=lf

# Binary: never touch these.
*.docx binary
*.pdf  binary
*.png  binary
*.jpg  binary
*.jpeg binary
*.tif  binary
*.tiff binary
*.eps  binary
*.xlsx binary
*.zip  binary
*.RData binary
"""

README = """\
# {title}

Checked by [manuscript-guard](https://github.com/BasileChretien/manuscript-guard).

    manuscript-guard check

Numbers in `manuscript/` are bindings into `results/` (written by the analysis) and
`literature/` (extracted from sources). Nothing is typed by hand, so nothing goes stale.
"""

# Several agent tools read an AGENTS.md at a project's root on their own, with or without the
# skills. It holds the rules the guarantee rests on, for an agent that has nothing else, and
# names no agent tool. Braces are doubled because every template here goes through format().
AGENTS = """\
# Rules for working in this project

This paper is written with [manuscript-guard](https://github.com/BasileChretien/manuscript-guard),
which makes every number in the manuscript traceable to its source. The rules below hold for
a person and for any agent tool.

1. **Never edit a machine-written file.** `results/` is written by the analysis, `build/` by
   `manuscript-guard build`, `render`, `respond` and `submit`, and a checklist profile,
   `profiles/reporting/<NAME>.yaml`, by `manuscript-guard transcribe` from its recipe. To
   change one, change what it is made from and run the command again: the analysis, the
   manuscript, or a recipe in `profiles/reporting/recipes/`, which is used in place of the
   one that ships with the tool.
2. **Run `manuscript-guard check` before `manuscript-guard build`**, and after any change to
   the analysis or the manuscript. Report what it prints as it is. Before the manuscript
   goes to anyone, run `manuscript-guard check --submission`.
3. **Never decide for yourself that the manuscript is clean.** `check` decides, for the
   stage that `paper.yaml` declares. A failing check is not nearly clean, and nothing is
   changed only to make it pass: not a results file, not the stage, and not a convention in
   `paper.yaml` for a number that should have been bound.
4. **A finding is never typed.** A number from the analysis is a binding,
   `{{{{results.<key>}}}}`, and one from the literature is `{{{{lit.<key>}}}}`. `check`
   accepts a typed number only where it is a convention of writing (a 95% confidence
   interval), a pointer (Table 1), or a label or a name (grade 3, ICD-10).
   `manuscript-guard bind` lists the numbers bound to nothing.
5. Only a person signs `literature/attested.yaml`.

The step-by-step guidance is in the skills that come with manuscript-guard, starting with
`project-setup`. If your agent tool shows none of them, say so to the author: the README at
the address above says which agent tools they can be installed in, and how.
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
    # Empty, but present. Without it `build --offline` refused a project that has no
    # citations at all, and told the author to run `sync-bib` with Zotero open - the one
    # thing `--offline` exists so they do not have to do.
    "literature/references.bib": BIBLIOGRAPHY,
    "manuscript/main.md": MANUSCRIPT,
    ".gitignore": GITIGNORE,
    ".gitattributes": GITATTRIBUTES,
    "README.md": README,
    "AGENTS.md": AGENTS,
}

_DIRS = ("analysis", "results", "literature/sources", "figures", "review", "build")


def _header(title: str) -> str:
    """The header `manuscript/main.md` opens with: the title, where the header can hold it.

    Two readers take the title from it. Pandoc reads the block as YAML, and refuses the
    manuscript where it cannot. The build takes what stands after `title:` and strips the
    quotation marks around it (`strip_front_matter`), and warns where that is not
    `paper.yaml`'s title. Between double quotation marks, as the title was always typed, a
    `"` ended it and a backslash began an escape: a title with TeX or a quotation in it left
    a new project that failed `check` on the header `init` had typed. So the title stands
    between the quotation marks under which both readers give it back as it is, double ones
    first, so that an ordinary title is typed as it always was. Where neither kind does,
    the header is left out: `paper.yaml` holds the title the document prints, and the
    header's was only ever compared with it. That is a title holding both kinds, and one
    that begins or ends with a quotation mark of either kind, `the patients'` for one,
    since the build's reading strips every one of them at either end.
    """
    from manuscript_guard.build.assemble import strip_front_matter

    for mark in ('"', "'"):
        block = f"---\ntitle: {mark}{title}{mark}\n---\n\n"
        try:
            read = yaml.safe_load(f"title: {mark}{title}{mark}")
        except yaml.YAMLError:
            continue
        if read == {"title": title} and strip_front_matter(block + "text")[1] == title:
            return block
    return ""


def init_project(root: Path, title: str = "Untitled manuscript") -> list[Path]:
    """Create the project layout. Existing files are never overwritten."""
    root = Path(root).resolve()
    created: list[Path] = []
    # On one line, and a tab as a space: what the build prints for each. Written into
    # `paper.yaml` as its escape, a tab before a letter is what `check` reports as a letter
    # lost, in a file the author did not type.
    title = one_line(title).replace("\t", " ")
    # Refused before anything is made. A lone surrogate is what Python makes of an argument
    # that is not in the terminal's encoding, and it cannot be written as UTF-8: the first
    # file was left empty, the command ended in a traceback, and a second `init` kept the
    # empty `paper.yaml`, since it writes over nothing. A control character and the two
    # code points that are no character can be written, into a project `check` then fails
    # or cannot read.
    character = unprintable_character(title)
    if character is not None:
        raise ContractError(
            f"the title holds {named(character)}, which no document can carry, so "
            "nothing was made; give the title again without it"
        )
    # So is TeX the document would be printed without, in the words of the finding `check`
    # would make of it: the title is typed into two files here, and a project made with it
    # opened on that finding in both.
    said = outside_maths(title)
    if said is not None:
        raise ContractError(f"the title cannot be printed whole, so nothing was made: {said}")

    for name in _DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)

    for name, template in _FILES.items():
        path = root / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        # The title is typed into `paper.yaml` as a JSON string, whose escapes are YAML's:
        # between quotation marks typed around it as it stood, a backslash in it began an
        # escape, which `check` refuses and the author never wrote, and a quotation mark
        # ended it. The manuscript's own header cannot take that form, since its title is
        # read by a plain split of the line: see `_header`.
        written = template.format(
            title=title,
            quoted=json.dumps(title, ensure_ascii=False),
            header=_header(title),
        )
        path.write_text(written, encoding="utf-8", newline="\n")
        created.append(path)

    keep = root / "results" / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8", newline="\n")

    return created


def rules_to_add(root: Path) -> str | None:
    """The rules for an agent, where the project's AGENTS.md does not have them.

    `init` never overwrites, so a repository that already has an AGENTS.md keeps its own. An
    agent working there would then read rules that say nothing of `results/`. The file is
    taken to have them if it names the toolkit at all, which a file written here does.
    """
    path = Path(root).resolve() / "AGENTS.md"
    try:
        present = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if "manuscript-guard" in present:
        return None
    return AGENTS.format(title="").split("\n", 1)[1].strip()
