"""Where the toolkit's own data lives, and where a user's copy of it goes.

Two kinds of file were being kept in one place, and the wheel could only carry one of them.

**Shipped and read-only** — the checklist recipes and any journal profiles distributed with
the toolkit. These belong beside the code, inside the package, so `pip install` carries
them. They used to sit in a `profiles/` directory at the repository root, resolved as
`Path(__file__).resolve().parents[2]`. From a source checkout that is the repository; from
`<venv>/Lib/site-packages/manuscript_guard/` it is `<venv>/Lib`, which holds nothing. So
`manuscript-guard fetch STROBE` — the second command in the README's own walkthrough —
answered "no recipe for 'STROBE'" for everyone who installed the package as documented.

**Fetched and generated** — the official checklist documents a user downloads and the
profiles transcribed from them. These must never be written inside the installed package:
site-packages is not the user's, may be read-only, and is replaced on upgrade. They go to
the project being worked on, which is also where the gates already look first.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).parent

# What counts as an analysis source file. One definition, because it was three: G1's
# freshness scan, G9's methods ledger and G12 (which reads G9's) each spelled out the same
# nine suffixes, and G3 a different five. Adding `.stan` or `.m` to one and not the others
# would make the gates disagree about what an analysis is, with no test to notice.
SOURCE_SUFFIXES = frozenset(
    {".r", ".rmd", ".qmd", ".py", ".ipynb", ".sql", ".jl", ".do", ".sas"}
)

# The subset that can also draw a figure. Narrower on purpose: a figure is produced by a
# plotting script, not by a SQL query.
FIGURE_SCRIPT_SUFFIXES = frozenset({".r", ".rmd", ".qmd", ".py", ".jl"})

SHIPPED = PACKAGE / "profiles"
SHIPPED_RECIPES = SHIPPED / "reporting" / "recipes"
SHIPPED_CHECKLISTS = SHIPPED / "reporting"
SHIPPED_JOURNALS = SHIPPED / "journals"


def workspace(explicit: Path | None = None, start: Path | None = None) -> Path:
    """The directory whose `profiles/` holds downloaded documents and built profiles.

    `--root` when given, otherwise the project you are standing in, otherwise the working
    directory. Running from a source checkout with no project around you lands on the
    checkout itself, which is where these files have always gone during development.
    """
    if explicit is not None:
        return Path(explicit)

    from manuscript_guard.contracts import ContractError, find_root

    here = Path(start) if start is not None else Path.cwd()
    try:
        return find_root(here)
    except (ContractError, OSError):
        return here


__all__ = [
    "FIGURE_SCRIPT_SUFFIXES",
    "PACKAGE",
    "SOURCE_SUFFIXES",
    "SHIPPED",
    "SHIPPED_CHECKLISTS",
    "SHIPPED_JOURNALS",
    "SHIPPED_RECIPES",
    "workspace",
]
