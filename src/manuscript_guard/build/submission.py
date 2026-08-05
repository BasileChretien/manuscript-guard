"""Assembling everything a journal asks for, from what the project already knows.

A submission is not one file. It is the manuscript, a title page carrying information the
manuscript deliberately does not, a CRediT statement, three or four declarations, the
completed reporting checklist, the figures in the format the publisher wants, and a
covering letter. Assembling that by hand, at the end, is where the last mistakes get made:
the title page lists an author who left the paper two revisions ago, the funding statement
contradicts the acknowledgements, the checklist points at a section that was renamed.

Everything except the covering letter is already recorded somewhere in the project, so
none of it is written twice. `authors.yaml` becomes the title page, the CRediT statement and
the declarations; the reporting completion file is copied as it stands; the build produces
the document. The manifest lists what went out, with checksums, because the question
"which version did we actually send" has no good answer six months later otherwise.

The pack refuses to assemble while the submission check fails. That is the point of having
the check.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project
from manuscript_guard.text.sections import measure

CREDIT_ORDER = (
    "Conceptualization",
    "Data curation",
    "Formal analysis",
    "Funding acquisition",
    "Investigation",
    "Methodology",
    "Project administration",
    "Resources",
    "Software",
    "Supervision",
    "Validation",
    "Visualization",
    "Writing – original draft",
    "Writing – review & editing",
)


class SubmissionError(Exception):
    """The pack could not be assembled."""


@dataclass(frozen=True)
class Pack:
    directory: Path
    files: tuple[Path, ...]
    manifest: Path


def _initials(author: dict) -> str:
    given = "".join(part[0] + "." for part in str(author["given"]).replace("-", " ").split())
    return f"{given}{author['family'][0]}."


def _superscripts(author: dict, order: list[str]) -> str:
    return ",".join(str(order.index(a) + 1) for a in author["affiliations"] if a in order)


def title_page(project: Project) -> str:
    """Everything the manuscript itself leaves out, in the order journals ask for it."""
    authors = project.authors
    if not authors:
        raise SubmissionError("authors.yaml is required for a title page")

    order = [a["id"] for a in authors["affiliations"]]
    paper = project.paper
    lines = [f"# {paper['title']}", ""]

    short = paper.get("short_title")
    if short:
        lines += [f"**Running title.** {short}", ""]

    names = []
    for author in authors["authors"]:
        degrees = ", ".join(author.get("degrees", []))
        name = f"{author['given']} {author['family']}"
        if degrees:
            name += f", {degrees}"
        marks = _superscripts(author, order)
        if marks:
            name += f"^{marks}^"
        if author.get("equal_contribution"):
            name += "\\*"
        names.append(name)
    lines += ["**Authors.** " + "; ".join(names), ""]

    lines.append("**Affiliations.**")
    lines.append("")
    for index, affiliation in enumerate(authors["affiliations"], start=1):
        lines.append(f"{index}. {affiliation['text']}")
    lines.append("")

    equal = [a for a in authors["authors"] if a.get("equal_contribution")]
    if equal:
        note = authors.get("equal_contribution_note") or (
            ", ".join(_initials(a) for a in equal) + " contributed equally to this work."
        )
        lines += [f"\\* {note}", ""]

    corresponding = [a for a in authors["authors"] if a.get("corresponding")]
    if corresponding:
        lines.append("**Corresponding author.**")
        lines.append("")
        for author in corresponding:
            block = [f"{author['given']} {author['family']}"]
            for identifier in author["affiliations"]:
                match = next((a for a in authors["affiliations"] if a["id"] == identifier), None)
                if match:
                    block.append(match["text"])
            if author.get("email"):
                block.append(author["email"])
            if author.get("orcid"):
                block.append(f"ORCID {author['orcid']}")
            lines.append("  \n".join(block))
        lines.append("")

    orcids = [
        f"{a['given']} {a['family']}: {a['orcid']}" for a in authors["authors"] if a.get("orcid")
    ]
    if orcids:
        lines += ["**ORCID.**", ""] + [f"- {o}" for o in orcids] + [""]

    keywords = paper.get("keywords")
    if keywords:
        lines += ["**Keywords.** " + "; ".join(keywords), ""]

    counts = _counts(project)
    lines += [
        f"**Word count.** Abstract {counts.abstract_words}; main text "
        f"{counts.main_text_words}. Tables {counts.tables}; figures {counts.figures}.",
        "",
    ]
    return "\n".join(lines)


def _counts(project: Project):
    """What the title page declares to the editor: the main text, not the supplement."""
    from manuscript_guard.gates.numbers import source_files

    text = "\n\n".join(
        p.read_text(encoding="utf-8")
        for p in source_files(project.path("manuscript"), main_text_only=True)
    )
    return measure(text)


def credit_statement(project: Project) -> str:
    """CRediT roles, grouped by role rather than by author, as journals print them."""
    authors = project.authors
    if not authors:
        raise SubmissionError("authors.yaml is required for a CRediT statement")

    by_role: dict[str, list[str]] = {}
    for author in authors["authors"]:
        for role in author.get("credit", []):
            by_role.setdefault(role, []).append(_initials(author))

    if not by_role:
        return (
            "# CRediT author statement\n\nNo CRediT roles are recorded in authors.yaml. "
            "Most journals now require them.\n"
        )

    lines = ["# CRediT author statement", ""]
    for role in CREDIT_ORDER:
        if role in by_role:
            lines.append(f"**{role}:** {', '.join(by_role[role])}")
    extra = sorted(set(by_role) - set(CREDIT_ORDER))
    lines += [f"**{role}:** {', '.join(by_role[role])}" for role in extra]
    lines.append("")
    return "\n".join(lines)


def declarations(project: Project) -> str:
    """Funding and competing interests, from the one place they are recorded."""
    authors = project.authors
    if not authors:
        raise SubmissionError("authors.yaml is required for declarations")

    lines = ["# Declarations", ""]

    funding = []
    for author in authors["authors"]:
        for grant in author.get("funding", []):
            funding.append(f"{_initials(author)}: {grant}")
    lines += ["## Funding", ""]
    lines.append("\n".join(f"- {f}" for f in funding) if funding else "No funding is recorded.")
    lines.append("")

    lines += ["## Competing interests", ""]
    stated = [
        f"{a['given']} {a['family']}: {a['competing_interests']}"
        for a in authors["authors"]
        if str(a.get("competing_interests", "")).strip()
    ]
    unstated = [
        f"{a['given']} {a['family']}"
        for a in authors["authors"]
        if not str(a.get("competing_interests", "")).strip()
    ]
    if stated:
        lines += [f"- {s}" for s in stated]
    if unstated:
        # An empty field is not a declaration of none, and journals ask per author.
        lines.append("")
        lines.append(
            "No declaration is recorded for: " + ", ".join(unstated) + ". "
            "An empty field is not a declaration of none."
        )
    lines.append("")
    return "\n".join(lines)


def _escape_cell(text: str) -> str:
    """A pipe inside a cell ends the cell, so a checklist item containing one has to say so."""
    return " ".join(str(text).split()).replace("|", "\\|")


def checklist_table(project: Project, completion: Path) -> str:
    """A completed checklist as a journal reads it: item, where it is addressed, or why not.

    The pack shipped `reporting/*.yaml` and nothing else, so what a journal received in
    answer to "attach your completed STROBE checklist" was a serialisation. Generated rather
    than maintained, so it cannot drift from the file the gate checks — and the item text
    comes from the transcribed guideline, not from the completion, so an item nobody answered
    still appears with the answer blank rather than vanishing from the table.
    """
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.reporting import checklist_path

    answers = read_structured(completion) or {}
    name = str(answers.get("guideline") or completion.stem)
    source = checklist_path(project, name)
    published = (read_structured(source) or {}) if source else {}
    items = published.get("items") or []

    lines = [f"# {name} checklist", ""]
    if source is None:
        lines += [
            f"The {name} item list is not in this project, so this table can only show the "
            "answers, not the items they answer.",
            "",
        ]
    if licence := published.get("licence"):
        lines += [f"Item text reproduced from the published {name} checklist ({licence}).", ""]
    lines += [
        "| Item | Recommendation | Addressed in | Not applicable because |",
        "|---|---|---|---|",
    ]

    answered = {str(entry.get("id")): entry for entry in answers.get("items", [])}
    ids = [str(item["id"]) for item in items] or sorted(answered)
    text_of = {str(item["id"]): item.get("text", "") for item in items}

    for identifier in ids:
        entry = answered.get(identifier, {})
        lines.append(
            f"| {_escape_cell(identifier)} | {_escape_cell(text_of.get(identifier, ''))} "
            f"| {_escape_cell(entry.get('where', ''))} "
            f"| {_escape_cell(entry.get('not_applicable', ''))} |"
        )

    extra = sorted(set(answered) - set(ids))
    for identifier in extra:
        entry = answered[identifier]
        lines.append(
            f"| {_escape_cell(identifier)} | *not in the published checklist* "
            f"| {_escape_cell(entry.get('where', ''))} "
            f"| {_escape_cell(entry.get('not_applicable', ''))} |"
        )
    return "\n".join(lines) + "\n"


def assemble_pack(project: Project, document: Path, *, checked: bool = True) -> Pack:
    """Copy or generate every part of the submission into build/submission/.

    `checked=False` records in the manifest that the submission check was overridden. A
    pack assembled with `--skip-checks` was previously byte-indistinguishable from one that
    passed — same files, same checksums, nothing anywhere saying which it was. Six months
    later nobody can tell, and the manifest's whole purpose is to be the thing you can tell
    from.
    """
    from manuscript_guard.gates.numbers import SUPPLEMENTARY, is_supplementary, source_files

    directory = project.path("build") / "submission"
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)

    files: list[Path] = []

    if document.exists():
        target = directory / document.name
        shutil.copy2(document, target)
        files.append(target)

    for name, text in (
        ("title-page.md", title_page(project)),
        ("credit-statement.md", credit_statement(project)),
        ("declarations.md", declarations(project)),
    ):
        target = directory / name
        target.write_text(text, encoding="utf-8", newline="\n")
        files.append(target)

    # The supplement, as its own file. Welded into the manuscript it counted against the
    # word limit and could not be uploaded to the "supplementary material" slot every
    # submission system has.
    #
    # Gated on the project still having supplementary sources, not on the file existing: a
    # `supplementary.docx` left in build/ from a layout the author has since abandoned would
    # otherwise be sent to a journal with nothing in the project to check it against.
    supplement = document.parent / f"{SUPPLEMENTARY}.docx"
    has_supplement = any(
        is_supplementary(project.path("manuscript"), p)
        for p in source_files(project.path("manuscript"))
    )
    if has_supplement and supplement.exists() and supplement != document:
        target = directory / supplement.name
        shutil.copy2(supplement, target)
        files.append(target)

    checklists = project.root / "reporting"
    if checklists.exists():
        for path in sorted(checklists.glob("*.yaml")):
            # The YAML, because it is the record and it diffs. And a table beside it,
            # because the YAML is what the pack used to offer a journal and a journal cannot
            # read it: an editor asking for a completed STROBE checklist wants to see the
            # items and where each is addressed, not a serialisation of them.
            target = directory / f"checklist-{path.name}"
            shutil.copy2(path, target)
            files.append(target)

            table = directory / f"checklist-{path.stem}.md"
            table.write_text(checklist_table(project, path), encoding="utf-8", newline="\n")
            files.append(table)

    figures = project.path("figures")
    if figures.exists():
        figure_dir = directory / "figures"
        figure_dir.mkdir(exist_ok=True)
        for path in sorted(figures.iterdir()):
            if path.is_file() and path.suffix.lower() in {".png", ".pdf", ".tif", ".tiff", ".eps"}:
                target = figure_dir / path.name
                shutil.copy2(path, target)
                files.append(target)

    manifest = _write_manifest(project, directory, files, checked=checked)
    return Pack(directory=directory, files=tuple(files), manifest=manifest)


def _write_manifest(
    project: Project, directory: Path, files: list[Path], *, checked: bool = True
) -> Path:
    from manuscript_guard.gates.review import manuscript_digest

    entries = []
    for path in files:
        data = path.read_bytes()
        entries.append(
            {
                "file": str(path.relative_to(directory)).replace("\\", "/"),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    document = {
        "schema": "manuscript-guard/submission/1",
        "title": project.paper.get("title", ""),
        "journal": project.target_journal or "(none chosen)",
        "assembled_on": date.today().isoformat(),
        "checks": (
            "passed"
            if checked
            else "SKIPPED — assembled with --skip-checks while the submission check "
            "was failing. Do not send this without re-running `manuscript-guard "
            "check --submission`."
        ),
        "manuscript_sha256": manuscript_digest(project),
        "files": entries,
    }
    path = directory / "MANIFEST.yaml"
    header = (
        "# What was sent, and exactly which bytes. Six months from now the only reliable\n"
        "# answer to \"which version did the journal get\" is a list of checksums.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return path
