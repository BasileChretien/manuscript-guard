"""README.md of a package: what is in it, how to run it again, what `manuscript-guard verify`
checks and what it cannot, and what was left out and why."""

from __future__ import annotations

from pathlib import PurePosixPath

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.paths import LOCKFILES

from .plan import Entry, Input, settings

#: How each pinning file is restored, by its name.
RESTORE = {
    "renv.lock": "`Rscript -e \"renv::restore()\"`",
    "uv.lock": "`uv sync`",
    "poetry.lock": "`poetry install`",
    "environment.yml": "`conda env create -f environment.yml`",
}


def _restore(name: str) -> str:
    if name in RESTORE:
        return RESTORE[name]
    return f"`pip install -r {name}`" if name.startswith("requirements") else f"`{name}`"


def _run_line(script: str) -> str:
    from .texts import RUN

    template = RUN.get(PurePosixPath(script).suffix.lower())
    return f"`{template.format(script)}`" if template else f"`{script}`, as its language runs it"


def _authors(project: Project) -> str:
    listed = (project.authors or {}).get("authors") or []
    names = [" ".join(str(a.get(p) or "") for p in ("given", "family")).strip() for a in listed]
    names = [name for name in names if name]
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _top(project: Project) -> list[str]:
    title = project.paper.get("title", "")
    by = _authors(project)
    out = [f"# Code and results for \"{title}\"", "",
           "This package holds the analysis code of the paper, the results it wrote, what "
           "they were written with, and how to run it again"
           + (f". By {by}." if by else ".")]
    doi = settings(project).get("doi")
    if doi:
        out += ["", f"DOI: [{doi}](https://doi.org/{doi})"]
    if project.paper.get("demonstration"):
        out += ["", "The paper is a demonstration, and its data are synthetic: they describe "
                "no real person."]  # fmt: skip
    return out


def _rerun(
    results: Results, entries: list[Entry], sessions: list[str], versions: list[str]
) -> list[str]:
    scripts = sorted({fragment.generated_by for fragment in results.fragments})
    pins = sorted(e.path for e in entries if "/" not in e.path and any(
        PurePosixPath(e.path).match(pattern) for pattern in LOCKFILES))  # fmt: skip
    out = ["## Running it again", "", "The results were written by these scripts, with:", "",
           *sessions, ""]  # fmt: skip
    steps = [
        "Install the language versions above.",
        "Install manuscript-guard, which the scripts write their results with: "
        + (", ".join(f"`pip install manuscript-guard=={v}`" for v in versions) or
           "`pip install manuscript-guard`") + ".",
    ]
    if pins:
        restored = "; ".join(f"{_restore(name)} for `{name}`" for name in pins)
        steps.append(f"Install the packages the analysis was pinned to: {restored}.")
    else:
        steps.append("The project pinned no packages, so install the versions named above "
                     "where they are named, and the current ones otherwise.")  # fmt: skip
    steps.append("From this folder, run each script: "
                 + "; ".join(_run_line(script) for script in scripts) + ".")  # fmt: skip
    steps.append("Or have `manuscript-guard verify` run them all, from this folder, and "
                 "compare what they write with the results here.")  # fmt: skip
    out += [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    return out


VERIFY = [
    "## What `manuscript-guard verify` checks",
    "",
    "It copies this folder, empties `results/` in the copy, runs there each script a results "
    "file names as the one that wrote it, and compares what the script writes with the file "
    "here, value by value: each value and its display, and each table's rows, columns and "
    "caption. Two numbers agree when they share nine significant digits, and two displays "
    "when they are the same characters. A software version other than the one recorded is "
    "reported and not counted as a difference.",
    "",
    "What it cannot do: it does not draw the figures again (each `figures/*.render.json` holds "
    "the SHA-256 of what its script drew); it cannot run a script whose input is not in this "
    "package, and says so; it cannot make an analysis that is not deterministic agree with "
    "itself; and it proves nothing of an analysis written to tell that it is being run again.",
    "",
    "Without manuscript-guard, `sha256sum -c SHA256SUMS` checks that every file is as it was "
    "packaged.",
]


def _withheld(
    project: Project, inputs: list[Input], with_manuscript: bool, in_git: bool
) -> list[str]:
    out = ["## What is not here, and why", ""]
    away = [found for found in inputs if not found.included]
    if away:
        out.append("- Inputs the analysis read and this package does not hold: "
                   + ", ".join(f"`{found.path}` ({found.why})" for found in away)
                   + ". INPUTS.md gives the size and SHA-256 of each. To obtain them: "
                   + str(settings(project).get("request") or "not said") + "")  # fmt: skip
        readers = sorted({script for found in away for script in found.read_by})
        out.append("  The scripts that read them cannot be run again from this package "
                   "alone: " + ", ".join(f"`{script}`" for script in readers) + ".")  # fmt: skip
    if not with_manuscript:
        out.append("- The manuscript's text. BOUND.md lists every result it prints, and "
                   "where.")  # fmt: skip
    out += [
        "- Stored copies of the works the paper cites: they are their publishers' to "
        "distribute. `literature/ledger.yaml` quotes the passage each value is taken from, "
        "and `literature/references.bib` names each work.",
        "- The review records, the authors' details, the approvals and sign-offs, and the "
        "built documents: they name people, or are made again from what is here.",
        "- Any file git did not track, and any link: MANIFEST.yaml lists each file left out, "
        "with the reason." if in_git else
        "- Any link: MANIFEST.yaml lists each file left out, with the reason. The project is "
        "not a git repository, so every other file of the folders above was taken as it was "
        "on the disk.",
    ]
    return out


def readme_text(project: Project, results: Results, inputs: list[Input], entries: list[Entry],
                with_manuscript: bool, *, contents: list[str], sessions: list[str],
                versions: list[str], in_git: bool) -> str:  # fmt: skip
    from .texts import _licence_name

    found = settings(project).get("licence")
    named = found if isinstance(found, str) else " and ".join(str(one) for one in found or [])
    out = [
        *_top(project), "",
        "## What is here", "", *contents, "",
        *_rerun(results, entries, sessions, versions), "",
        *VERIFY, "",
        *_withheld(project, inputs, with_manuscript, in_git), "",
        "## Licence and citation", "",
        f"The package is under {named or 'its licence'} (see {_licence_name(entries)}). "
        "CITATION.cff says how to cite it; cite the paper too.",
    ]
    return "\n".join(out) + "\n"


__all__ = ["readme_text"]
