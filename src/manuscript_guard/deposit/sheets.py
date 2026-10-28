"""The submission sheets of a preprint: what arXiv's and medRxiv's forms ask, with what the
project records for each, or "not recorded".

Neither server has an interface the tool uploads through, so the author fills the form, and
the sheet is what they fill it from. What a sheet says of a server's rules is the rule as the
sheet names it, written down when the tool was, and not a fact the tool checked: the forms
and the rules are the servers', and change. A number the sheet reports, the abstract's
length or the archive's size, is the tool's own count.
"""

from __future__ import annotations

from manuscript_guard.contracts.project import Project

#: arXiv's limit on an abstract, in characters, as the sheet names it.
ARXIV_ABSTRACT = 1920
#: arXiv's limit on a submission's size, in megabytes, as the sheet names it.
ARXIV_MEGABYTES = 50
NOT_RECORDED = "not recorded"
RULES = ("The rules below are named as this sheet was written; the server's own pages are "
         "what holds, and its moderators decide what it takes.")  # fmt: skip


def _authors(project: Project) -> list[str]:
    from .metadata import people

    listed = (project.authors or {}).get("authors") or []
    lines = []
    for author, person in zip(listed, people(project), strict=False):
        if not person.name:
            continue
        said = person.name + (f", ORCID {person.orcid}" if person.orcid
                              else f", ORCID {NOT_RECORDED}")  # fmt: skip
        named = [text for _id, text in person.affiliations]
        known = {identifier for identifier, _text in person.affiliations}
        given = author.get("affiliations") if isinstance(author, dict) else None
        # An id `affiliations` does not list is said, not dropped (round 1 of #460).
        named += [f"affiliation `{identifier}`: {NOT_RECORDED}, authors.yaml lists no "
                  "affiliation of this id with its text" for identifier in map(str, given or [])
                  if identifier not in known]  # fmt: skip
        if named:
            said += "; " + "; ".join(named)
        lines.append(f"- {said}")
    return lines or [f"- {NOT_RECORDED}: authors.yaml lists no author"]


def _abstract(project: Project) -> tuple[str | None, list[str]]:
    from manuscript_guard.build.submission import abstract_text

    text, why = abstract_text(project)
    if text is None:
        return None, [f"{NOT_RECORDED}: {why or 'the manuscript has no abstract the tool finds'}"]
    return text.strip(), ["```text", text.strip(), "```"]


def arxiv_sheet(project: Project, *, files: list[str], size: int, pdf: str,
                engine: str) -> str:  # fmt: skip
    """arxiv_submission_sheet.md: what arXiv's form asks, and what the source holds."""
    from manuscript_guard.build.latex_pack import _GRAPHICS

    text, shown = _abstract(project)
    length = f"{len(text)} characters" if text is not None else NOT_RECORDED
    over = text is not None and len(text) > ARXIV_ABSTRACT
    pictures = [name for name in files if name.endswith(_GRAPHICS)]
    bbl = any(name.endswith(".bbl") for name in files)
    lines = [
        f"# arXiv submission sheet: {project.paper.get('title', '')}", "",
        "Written by `manuscript-guard deposit --target arxiv --bundle preprint`. Nothing has "
        "been uploaded: arXiv has no interface the tool sends through, and the form is yours "
        "to fill. " + RULES, "",
        "## Title", "", str(project.paper.get("title", "")) or NOT_RECORDED, "",
        "## Authors", "", *_authors(project), "",
        "## Abstract", "", f"Length: {length}. arXiv's rule, as this sheet names it: at most "
        f"{ARXIV_ABSTRACT:,} characters." + (" **This abstract is longer: shorten it for the "
                                            "form.**" if over else ""),
        "", *shown, "",
        "## The source", "",
        f"- `{len(files)}` files in the archive, at its top level; the main document is "
        "`manuscript.tex`.",
        f"- The bibliography LaTeX made, `manuscript.bbl`: {'included' if bbl else 'none'}. "
        "arXiv does not run BibTeX or Biber, as this sheet names its rule, so a document that "
        "cites needs it.",
        f"- Figures: {len(pictures)} picture file(s). Pages: not counted by the tool; the PDF "
        f"the folder compiled to alone, with {engine}, is `{pdf}`.",
        f"- Size: {size:,} bytes compressed. arXiv's rule, as this sheet names it: a "
        f"submission of at most {ARXIV_MEGABYTES} MB.",
        "- arXiv compiles the source with its own TeX Live, which may not be the one it "
        "compiled with here.",
        "- The supplement is not in the archive: arXiv compiles one document a submission. Put "
        "it in the paper as an appendix, or deposit it elsewhere.", "",
        "## Left to you", "",
        f"- Licence: {NOT_RECORDED}. arXiv asks which licence the preprint is under when it is "
        "submitted; `package.licence` is the code's.",
        f"- Categories: {NOT_RECORDED}. The primary category is yours to choose; a first "
        "submission to a category may need an endorsement by an author arXiv knows, which "
        "arXiv asks for when it does.",
        "- Research on human health: arXiv's rule, as this sheet names it, sends clinical and "
        "health research to medRxiv; `--target medrxiv --bundle preprint` stages it for there.",
        "",
    ]  # fmt: skip
    return "\n".join(lines)


def _declared(project: Project, key: str) -> list[str]:
    from .metadata import people

    listed = (project.authors or {}).get("authors") or []
    out = []
    for author, person in zip(listed, people(project), strict=False):
        said = author.get(key) if isinstance(author, dict) else None
        if key == "funding":
            said = "; ".join(str(grant) for grant in said or []) or None
        text = str(said).strip() if said else ""
        out.append(f"- {person.name}: {text or NOT_RECORDED}")
    return out or [f"- {NOT_RECORDED}"]


def _corresponding(project: Project) -> str:
    listed = (project.authors or {}).get("authors") or []
    marked = [a for a in listed if isinstance(a, dict) and a.get("corresponding") is True]

    def name_of(author: dict) -> str:
        return " ".join(str(author.get(k) or "") for k in ("given", "family")).strip()

    if not marked:
        return f"{NOT_RECORDED}: authors.yaml marks no author `corresponding: true`"
    if len(marked) > 1:
        return (f"authors.yaml marks {len(marked)} authors `corresponding: true`, "
                f"{', '.join(name_of(a) for a in marked)}; medRxiv's form names one, yours to "
                "choose")  # fmt: skip
    author = marked[0]
    name = name_of(author)
    return f"{name}, whose e-mail address authors.yaml records" if author.get("email") else name


def _statement(project: Project) -> list[str]:
    from manuscript_guard.build.document import BuildError
    from manuscript_guard.build.submission import plain_passage
    from manuscript_guard.gates.data_statement import HEADING, _profile_heading, _statements
    from manuscript_guard.gates.revision import displays
    from manuscript_guard.text.placeholders import substitute

    found = _statements(project, [_profile_heading(project) or HEADING])
    if not found:
        return [f"{NOT_RECORDED}: the manuscript has no Data availability statement"]
    # Its bindings as the build prints them, as the abstract's are; and nothing of it where
    # what is left is not plain text (round 1 of #460).
    try:
        said = plain_passage(substitute(found[0][0], displays(project)))
    except BuildError:  # pandoc refused it, or gave nothing in its time
        said = None
    if said is None:
        return ["Copy it from the document: the statement holds what plain text cannot show "
                "as the document prints it (a citation, a reference, a footnote or maths), or "
                "pandoc, which writes it as plain text, is not on PATH."]  # fmt: skip
    return ["As the document prints it:", "", "```text", said, "```"]


def medrxiv_sheet(project: Project, *, files: list[str]) -> str:
    """medrxiv_submission_sheet.md: each question of medRxiv's form, as the sheet names it,
    with the answer the project records, or "not recorded"."""
    _text, shown = _abstract(project)
    registrations = [str(r.get("id")) for r in project.paper.get("registration") or []
                     if isinstance(r, dict) and r.get("id")]  # fmt: skip
    guidelines = [str(g) for g in project.paper.get("reporting_guideline") or []]
    checklists = [name for name in files if name.startswith(("checklist-", "scale-"))]
    lines = [
        f"# medRxiv submission sheet: {project.paper.get('title', '')}", "",
        "Written by `manuscript-guard deposit --target medrxiv --bundle preprint`. Nothing has "
        "been uploaded: medRxiv has no interface the tool sends through, and the form is "
        "yours to fill. Each question is named as this sheet names it, with what the project "
        "records. " + RULES, "",
        "## Title", "", str(project.paper.get("title", "")) or NOT_RECORDED, "",
        "## Authors, their affiliations and ORCID iDs", "", *_authors(project), "",
        "## Corresponding author", "", _corresponding(project), "",
        "## Abstract", "", *shown, "",
        "## Subject area", "", f"{NOT_RECORDED}: medRxiv's list; yours to choose.", "",
        "## Competing interests", "", *_declared(project, "competing_interests"), "",
        "## Funding", "", *_declared(project, "funding"), "",
        "## Ethics: approval by an IRB or ethics committee, or exemption, and its name", "",
        f"{NOT_RECORDED}: the project keeps no record of ethics approval.", "",
        "## Consent of the participants", "",
        f"{NOT_RECORDED}: the project keeps no record of consent.", "",
        "## Registration of a clinical trial or other prospective study", "",
        ", ".join(registrations) if registrations
        else f"{NOT_RECORDED}: paper.yaml lists no registration.", "",
        "## Reporting guidelines followed (EQUATOR)", "",
        (", ".join(guidelines) + (f"; the completed checklist(s): {', '.join(checklists)}"
                                  if checklists else "")) if guidelines
        else f"{NOT_RECORDED}: paper.yaml declares no reporting guideline.", "",
        "## Data availability", "", *_statement(project), "",
        "## Licence of the preprint", "",
        f"{NOT_RECORDED}: chosen on medRxiv's form; `package.licence` is the code's.", "",
        "## Files in this folder", "", *[f"- `{name}`" for name in files], "",
    ]  # fmt: skip
    return "\n".join(lines)


__all__ = ["ARXIV_ABSTRACT", "ARXIV_MEGABYTES", "arxiv_sheet", "medrxiv_sheet"]
