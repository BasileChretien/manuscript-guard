"""The files a package writes for its reader: README.md, CITATION.cff, BOUND.md, INPUTS.md,
and the project file `verify` reads.

Each is made from the project's records, and none holds a date, a clock or the commit: two
packages of an unchanged project are the same bytes, and a sign-off of one by the data
custodian holds for the other. The commit and the version of the tool that packaged it are
in MANIFEST.yaml, which nobody signs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Fragment, Results
from manuscript_guard.text.sections import split_sections

from .plan import Entry, Input, generated, settings

#: How each script is run from the package's root, by its suffix, as `verify` runs it.
RUN = {
    ".py": "python {}",
    ".r": "Rscript --vanilla {}",
    ".rmd": 'Rscript --vanilla -e "rmarkdown::render(\'{}\')"',
    ".qmd": "quarto render {}",
}

#: What `paper.yaml` keeps in the package: what `verify` and a reader need, and none of the
#: journal, the review panel or the models.
PAPER_KEYS = ("schema", "title", "short_title", "english_variant", "demonstration", "paths",
              "custodian")  # fmt: skip

#: Rows of the table of contents, by the first part of a path, in the order they are shown.
FOLDERS = (
    ("analysis/", "the scripts the analysis is made of"),
    ("results/", "the results, one file for each script that wrote any, each with the "
     "SHA-256 of its bytes in the `.sha256` file beside it"),
    ("figures/", "the scripts that draw the figures from the results, the figures drawn, "
     "and what each drew (`*.render.json`)"),
    ("design/", "the analysis plan, and the copy of it kept when the first results were "
     "written"),
    ("literature/", "the values taken from the literature, each with its quotation "
     "(`ledger.yaml`), and the reference list"),
    ("manuscript/", "the manuscript's source"),
)


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _documents(results: Results) -> dict[Path, dict]:
    from .counts import read_fragment

    return {f.path: read_fragment(f.path) for f in results.fragments}


def licences(project: Project) -> list[str]:
    said = settings(project).get("licence")
    return [str(said)] if isinstance(said, str) else [str(one) for one in said or []]


def citation(project: Project) -> str:
    """CITATION.cff: the authors as `authors.yaml` lists them, with their ORCID iDs and
    affiliations and without their addresses."""
    authors = project.authors or {}
    places = {a.get("id"): a.get("text") for a in authors.get("affiliations") or []}
    people = []
    for author in authors.get("authors") or []:
        person = {"family-names": str(author.get("family", "")),
                  "given-names": str(author.get("given", ""))}  # fmt: skip
        if author.get("orcid"):
            person["orcid"] = f"https://orcid.org/{author['orcid']}"
        named = [str(places[a]) for a in author.get("affiliations") or [] if places.get(a)]
        if named:
            person["affiliation"] = "; ".join(named)
        people.append(person)
    record: dict = {
        "cff-version": "1.2.0",
        "message": "If you use this package, cite it as below, and cite the paper it supports.",
        "type": "software",
        "title": f"Code and results for \"{project.paper.get('title', '')}\"",
        "authors": people or [{"name": "The authors of the paper"}],
    }
    found = licences(project)
    if found:
        record["license"] = found[0] if len(found) == 1 else found
    doi = settings(project).get("doi")
    if doi:
        record["doi"] = str(doi)
    return yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000)


def project_file(project: Project) -> str:
    kept = {key: project.paper[key] for key in PAPER_KEYS if key in project.paper}
    return (
        "# The project file of this package, for `manuscript-guard verify`: the paper's own,\n"
        "# with what verify and a reader need and nothing else.\n"
        + yaml.safe_dump(kept, sort_keys=False, allow_unicode=True)
    )


def _section_at(text: str, line: int) -> str:
    title = ""
    for section in split_sections(text):
        if section.line <= line:
            title = section.title
    return title or "before the first heading"


def bound(project: Project, results: Results) -> str:
    """BOUND.md: each results value, table and figure the manuscript binds, what it prints,
    and where."""
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.placeholders import parse

    rows: dict[str, list[str]] = {"results": [], "table": [], "figure": []}
    folder = project.path("manuscript")
    for path in source_files(folder) if folder.is_dir() else ():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        shown = path.relative_to(project.root).as_posix()
        for placeholder in parse(text)[0]:
            if placeholder.namespace not in rows:
                continue
            where = f"{shown}, {_cell(_section_at(text, placeholder.line))}"
            rows[placeholder.namespace].append(_bound_row(project, results, placeholder, where))
    printed = len({row.split(" | ")[0] for row in rows["results"]})
    out = ["# The results the paper prints", "",
           "Each value, table and figure of the results that the manuscript binds, with what "
           "it prints and where. The manuscript is not in this package unless it was asked "
           "for; the place is given all the same.", ""]  # fmt: skip
    for namespace, heading, columns in (
        ("results", "Values", "| Key | Prints | Results file | Where |"),
        ("table", "Tables", "| Key | Caption | Results file | Where |"),
        ("figure", "Figures", "| Key | | | Where |"),
    ):
        if rows[namespace]:
            out += [f"## {heading}", "", columns, "|---|---|---|---|", *rows[namespace], ""]
    out.append(f"Of the {len(results.values)} values the results hold, the manuscript binds "
               f"{printed}.")  # fmt: skip
    return "\n".join(out) + "\n"


def _bound_row(project: Project, results: Results, placeholder, where: str) -> str:
    key = placeholder.key
    if placeholder.namespace == "results":
        value = results.values.get(key)
        if value is None:
            return f"| `{key}` | not in the results | | {where} |"
        source = value.source.relative_to(project.root).as_posix() if value.source else ""
        return f"| `{key}` | {_cell(value.display)} | {source} | {where} |"
    if placeholder.namespace == "table":
        table = results.tables.get(key)
        if table is None:
            return f"| `table.{key}` | not in the results | | {where} |"
        source = table.source.relative_to(project.root).as_posix()
        return f"| `table.{key}` | {_cell(table.caption or '')} | {source} | {where} |"
    return f"| `figure.{key}` | | | {where} |"


def inputs_text(project: Project, inputs: list[Input]) -> str:
    """INPUTS.md: every input the analysis declared, its size and digest, and whether it is
    here; and how to obtain the ones that are not."""
    out = ["# The inputs the analysis read", "",
           "Every file the analysis declared it read, with the SHA-256 of its bytes when the "
           "results were written. A copy obtained elsewhere is the one the results were "
           "computed from when `sha256sum` gives the same digest.", "",
           "| Input | Bytes | SHA-256 | Read by | In this package |",
           "|---|---|---|---|---|"]
    for found in inputs:
        here = f"yes: {found.why}" if found.included else f"no: {found.why}"
        size = "" if found.size is None else str(found.size)
        readers = ", ".join(f"`{script}`" for script in found.read_by)
        out.append(f"| `{found.path}` | {size} | {found.sha256} | {readers} | {here} |")
    if any(not found.included for found in inputs):
        out += ["", "## How to obtain the inputs that are not here", "",
                str(settings(project).get("request") or "Not said.")]  # fmt: skip
    return "\n".join(out) + "\n"


def _session_line(fragment: Fragment, document: dict, results: Results) -> str:
    session = fragment.session or {}
    said = f"{session.get('language', 'an unknown language')} {session.get('version', '')}"
    tool = (document.get("provenance") or {}).get("tool") or {}
    parts = [said.strip()]
    if session.get("platform"):
        parts.append(f"on {session['platform']}")
    if tool.get("version"):
        parts.append(f"with manuscript-guard {tool['version']}")
    line = f"- `{fragment.generated_by}`: " + ", ".join(parts)
    packages = session.get("packages")
    if isinstance(packages, dict) and packages:
        line += "; R packages " + ", ".join(f"{n} {v}" for n, v in sorted(packages.items()))
    software = sorted(
        (key.removeprefix("software."), value.display) for key, value in results.values.items()
        if value.role == "software" and value.source == fragment.path
    )  # fmt: skip
    if software:
        line += "; the software it declared: " + ", ".join(f"{name} {version}"
                                                         for name, version in software)  # fmt: skip
    return line + "."


def _licence_name(entries: list[Entry]) -> str:
    """The name of the licence file the package holds, as the project calls it."""
    return next((entry.path for entry in entries if entry.why == "the licence"), "LICENSE")


def _contents(entries: list[Entry]) -> list[str]:
    out = ["| Folder or file | What it holds |", "|---|---|"]
    for prefix, said in FOLDERS:
        if any(entry.path.startswith(prefix) for entry in entries):
            out.append(f"| `{prefix}` | {said} |")
    data = sorted({entry.path.split("/")[0] + "/" for entry in entries
                   if entry.why.startswith("an input") and "/" in entry.path})  # fmt: skip
    for prefix in data:
        if prefix not in dict(FOLDERS):
            out.append(f"| `{prefix}` | inputs the analysis read that may be shared |")
    out += [
        "| `BOUND.md` | the results the paper prints, and where |",
        "| `INPUTS.md` | every input the analysis read, whether it is here, and how to obtain "
        "the rest |",
        "| `paper.yaml` | the project file `manuscript-guard verify` reads |",
        "| `MANIFEST.yaml`, `SHA256SUMS` | every file and its SHA-256 |",
        f"| `{_licence_name(entries)}`, `CITATION.cff` | the terms of reuse, and how to "
        "cite this package |",
    ]
    return out


def readme(project: Project, results: Results, inputs: list[Input], entries: list[Entry],
           with_manuscript: bool, in_git: bool) -> str:  # fmt: skip
    from .readme import readme_text

    documents = _documents(results)
    sessions = [_session_line(f, documents[f.path], results)
                for f in sorted(results.fragments, key=lambda f: f.generated_by)]  # fmt: skip
    tools = [(d.get("provenance") or {}).get("tool") or {} for d in documents.values()]
    versions = sorted({str(tool["version"]) for tool in tools if tool.get("version")})
    return readme_text(project, results, inputs, entries, with_manuscript,
                       contents=_contents(entries), sessions=sessions, versions=versions,
                       in_git=in_git)


def generated_entries(project: Project, results: Results, inputs: list[Input],
                      entries: list[Entry], with_manuscript: bool, *,
                      in_git: bool) -> list[Entry]:  # fmt: skip
    told = readme(project, results, inputs, entries, with_manuscript, in_git)
    return [
        generated("README.md", told, "how to run it again"),
        generated("CITATION.cff", citation(project), "how to cite it"),
        generated("BOUND.md", bound(project, results), "the results the paper prints"),
        generated("INPUTS.md", inputs_text(project, inputs), "the inputs, and where they are"),
        generated("paper.yaml", project_file(project), "the project file verify reads"),
    ]


__all__ = ["RUN", "bound", "citation", "generated_entries", "inputs_text", "project_file"]
