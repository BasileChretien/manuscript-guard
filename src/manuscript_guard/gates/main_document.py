"""G4: the main document goes to the journal in a format it takes.

Royal Society Open Science says "Please submit a PDF as your main document", and `submit`
packed the .docx the build makes: the profile had no field to say it, so the pack offered
the wrong file and nothing checked it. The study that found it could only list the rule
under `manual:`. A profile now says it under `submission.main_document`, quoted from the
page under `quotes.submission.main_document` as every rule is, and

* `submit` records the main document and its format in MANIFEST.yaml and, where the journal
  does not take it, says so with the pack and in journal-checklist.md, with how to make the
  one it takes (`build/submission.py`);
* G4 says so (`main-document-format`) of the last pack's main document, as its manifest
  records it, or, before a pack records one, of the one `submit` will pack: a Markdown
  manuscript's .docx, a LaTeX manuscript's PDF with its source in latex/.

A warning at submission and a note before it, and not a failure, as a figure in a format the
journal does not take is (`figure-format`): `submit` refuses while the check fails, and
`submit --latex`, the route that makes a Markdown manuscript's PDF, runs that same check, so
a failure would refuse the remedy along with the fault. A .docx saved as PDF from Word is
the author's step, outside the pack, which no gate sees.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import INFO, WARN, Finding, Report

GATE = "G4"
CODE = "main-document-format"
RULE = "submission.main_document"

#: Each format a profile may name, as the pack's messages name it.
NAMES = {
    "pdf": "PDF",
    "docx": "Word (.docx)",
    "doc": "Word (.doc)",
    "rtf": "RTF",
    "odt": "OpenDocument (.odt)",
    "tex": "LaTeX source",
}
#: What `submit` packs as the main document: the build's .docx for a Markdown manuscript,
#: and for a LaTeX one, or `submit --latex`, the PDF LaTeX makes with its source in latex/.
WORD_ROUTE = ("docx",)
LATEX_ROUTE = ("pdf", "tex")
#: The folder of the pack a LaTeX source is packed in.
LATEX_FOLDER = "latex/"


def wanted(document: dict | None) -> tuple[str, ...]:
    """The formats the journal takes its main document in, as the profile says; none where
    it says nothing, and then nothing is judged."""
    said = ((document or {}).get("submission") or {}).get("main_document") or ()
    return tuple(str(name).lower() for name in said)


def packed_formats(main: Path, packed_names: Iterable[str]) -> tuple[str, ...]:
    """The formats a pack's main document `main` is sent in: its own, and the LaTeX source
    where the pack holds one in latex/ (`packed_names`, each file's name in the pack)."""
    own = main.suffix.lower().lstrip(".") or main.name
    source = any(name.replace("\\", "/").startswith(LATEX_FOLDER) for name in packed_names)
    return (own, *(("tex",) if source and own != "tex" else ()))


def names(formats: Sequence[str]) -> str:
    """The formats in words: "PDF", "PDF or Word (.docx)"."""
    said = [NAMES.get(name, name) for name in formats]
    return said[0] if len(said) == 1 else ", ".join(said[:-1]) + " or " + said[-1]


def how_to(takes: Sequence[str], formats: Sequence[str], *, latex_manuscript: bool) -> str:
    """How to make the main document the journal takes from the one the pack holds."""
    if latex_manuscript:
        return (f"manuscript-guard makes no {names(takes)} of a LaTeX source: ask the journal "
                "whether it takes the PDF, or convert the source in latex/ and read the "
                "result against the PDF before sending it")
    if set(takes) & set(LATEX_ROUTE) and "pdf" not in formats:
        return ("run `manuscript-guard submit --latex`, which packs the PDF LaTeX makes, with "
                "its source in latex/; or open the .docx, refresh its citations (Zotero: "
                "Refresh), save it as PDF and send that PDF as the main document, which the "
                "manifest's checksums do not cover")
    if "docx" in takes:
        return "run `manuscript-guard submit` without `--latex`, which packs the .docx"
    # .doc, RTF or OpenDocument: Word saves the .docx as each, and no route here makes one.
    return (f"open the .docx, refresh its citations (Zotero: Refresh), save it as "
            f"{names(takes)} and send that as the main document, which the manifest's "
            "checksums do not cover")


def last_pack(project: Project) -> tuple[str, tuple[str, ...]] | None:
    """The main document of the pack last made, and its formats, as its MANIFEST.yaml
    records them; None where there is no pack, or none whose manifest records it (a pack
    made before the manifest did), or a pack for another journal than the target: what it
    holds says nothing of what this journal will get."""
    manifest = project.path("build") / "submission" / "MANIFEST.yaml"
    if not manifest.is_file():
        return None
    try:
        document = read_structured(manifest)
    except (ContractError, OSError):
        return None
    if not isinstance(document, dict):
        return None
    if document.get("journal", project.target_journal) != project.target_journal:
        return None
    main = document.get("main_document")
    if not isinstance(main, dict) or not isinstance(main.get("formats"), list):
        return None
    return str(main.get("file") or "the main document"), tuple(map(str, main["formats"]))


def check_main_document(project: Project, stage: str) -> Report:
    """`main-document-format` where the main document the pack holds, or will hold, is in no
    format the target journal's profile says it takes: a warning at submission, a note
    before."""
    from manuscript_guard.gates.journal import _profile, profile_path
    from manuscript_guard.policy import SUBMISSION
    from manuscript_guard.text.reader import LATEX, manuscript_format

    document = _profile(project)
    takes = wanted(document)
    if not takes:
        return Report()  # nothing said, or G4's check of the profile says why
    latex = manuscript_format(project.path("manuscript")) == LATEX
    packed = last_pack(project)
    if packed is None:
        formats = LATEX_ROUTE if latex else WORD_ROUTE
        message = (f"the journal takes its main document as {names(takes)}, and `submit` "
                   f"packs this manuscript as {names(formats[:1])}")
    else:
        file, formats = packed
        message = (f"the journal takes its main document as {names(takes)}, and the pack's, "
                   f"{file}, is {names(formats[:1])}")
    if set(formats) & set(takes):
        return Report()
    quote = ((document or {}).get("quotes") or {}).get(RULE)
    hint = how_to(takes, formats, latex_manuscript=latex) + (
        f". The journal's words: \"{quote}\"" if quote else "")  # fmt: skip
    return Report((
        Finding(gate=GATE, code=CODE, severity=WARN if stage == SUBMISSION else INFO,
                message=message, path=profile_path(project, project.target_journal),
                hint=hint),
    ))  # fmt: skip


def gap(document: dict | None, main: Path, packed_names: Iterable[str], *,
        latex_manuscript: bool) -> tuple[dict, str | None]:  # fmt: skip
    """What the manifest records of the pack's main document `main`, and the sentence that
    says the journal does not take it, with how to make the one it does; None where it does,
    or the profile says nothing of it."""
    formats = packed_formats(main, packed_names)
    record: dict = {"file": main.name, "formats": list(formats)}
    takes = wanted(document)
    if not takes:
        return record, None
    meets = bool(set(formats) & set(takes))
    record.update(journal_takes=list(takes), as_the_journal_asks=meets)
    if meets:
        return record, None
    quote = ((document or {}).get("quotes") or {}).get(RULE)
    said = (f"the journal takes its main document as {names(takes)}, and this pack's is "
            f"{main.name}, {names(formats[:1])}: "
            + how_to(takes, formats, latex_manuscript=latex_manuscript)
            + (f". The journal's words: \"{quote}\"" if quote else ""))
    return record, said
