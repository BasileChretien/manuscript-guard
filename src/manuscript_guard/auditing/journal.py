"""G4 on a paper that is in no project: the editor's triage, with the journal's profile.

An editor keeps one profile for their journal (`journal` starts one from the annotated
template) and holds each submission to it: `audit PAPER --journal PROFILE.yaml`. The paper
is put into a project made for it, as G6 and G14 are (`auditing.gates`), with the profile as
its target journal, and G4 runs there on what reads the manuscript's text and the profile
alone (`check_journal(records=False)`): the word and display-item limits, the abstract found
and structured, the required sections and statements, the data availability statement's
phrasing and identifiers, the boxes printed beside the abstract, and the profile's age. What
G4 reads from a project's records is not run, and the report names each part
(`gates.journal.FROM_RECORDS`, and the graphical abstract, a file of its own); the profile's
rules no gate checks are printed as the editor's checklist, each with its quote.

The main document is the first paper named: a journal counts its words and its display items,
and a supplement's are not. Every other paper is audited as the rest of the submission, and
named as not held to the journal's limits.

With `--authors`, where the profile says the journal's review is double- or triple-blind, the
authors' names, ORCID iDs, e-mail addresses and institutions are looked for in each document
of the submission, where the build looks for them (`build.blinding`): in a .docx its text,
comments, tracked deletions, author fields, link addresses and pictures' text, read from the
file as sent; in Markdown its text; in LaTeX each file of its tree and the PDF and SVG
pictures of its folder (`look_for_authors`). Each one found is counted by `--strict`. A
referee never passes `--authors`.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from manuscript_guard.findings import Finding

#: The `--english` value a profile's English stands for.
ENGLISH_OF = {"en-GB": "british", "en-US": "american"}
#: What the graphical abstract check reads, which a submission sends as a file of its own.
GRAPHICAL = "the graphical abstract, which a submission sends as a file of its own"


@dataclass
class JournalRun:
    """G4 on the main document of a submission, and the blinding check, or why not."""

    paper: Path
    profile: Path
    findings: list[Finding] = field(default_factory=list)
    #: Each place an author is named in a document the journal reviews blind.
    named: list[Finding] = field(default_factory=list)
    #: The profile's rules no gate checks, each `(rule, quote)`.
    manual: list[tuple[str, str]] = field(default_factory=list)
    #: What G4 did not check here, each a sentence.
    skipped: list[str] = field(default_factory=list)
    #: The papers read as the rest of the submission, not held to the journal's limits.
    others: list[Path] = field(default_factory=list)
    #: Why G4 did not run, where it did not.
    note: str = ""
    #: What the blinding check said where it did not look: --authors given and a review not
    #: blind, a blind review and no --authors, or a document it could not read.
    blind_note: str = ""
    #: How the journal's review is blinded, where the authors were looked for; None where
    #: they were not, a review that is not blind among them.
    looked: str | None = None
    #: Whether the lines are lines of the text pandoc converted a .docx to.
    converted: bool = False


def read_profile(path: Path) -> tuple[dict | None, list[str]]:
    """The profile at `path`, or what is wrong with it: each error of the journal schema."""
    from manuscript_guard.contracts._schema import ContractError, read_structured, validate

    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, [str(exc)]
    if not isinstance(document, dict):
        return None, [f"{path.name} is not a journal profile: no mapping of its rules"]
    report = validate(document, "journal", path, gate="G4")
    if not report.ok:
        return None, [f"{f.message}" + (f" ({f.hint})" if f.hint else "")
                      for f in report.findings]  # fmt: skip
    return document, []


def read_authors(path: Path) -> tuple[dict | None, str]:
    """The authors `--authors` names, in authors.yaml's shape, or why they cannot be read:
    `authors`, a list of people each with a `given` and a `family` name, and an `orcid` and an
    `email` where known; `affiliations`, a list each with its `text`, where known."""
    from manuscript_guard.contracts._schema import ContractError, read_structured

    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, str(exc)
    people = document.get("authors") if isinstance(document, dict) else None
    if not isinstance(people, list) or not people:
        return None, f"{path.name} lists no authors: give `authors:`, a list of people"
    for number, person in enumerate(people, 1):
        if not isinstance(person, dict) or not all(
                str(person.get(key) or "").strip() for key in ("given", "family")):  # fmt: skip
            return None, (f"{path.name}: author {number} has no `given` and `family` name, "
                          "which is how a name is looked for")  # fmt: skip
    affiliations = document.get("affiliations") or []
    if not isinstance(affiliations, list) or not all(
            isinstance(one, dict) and str(one.get("text") or "").strip()
            for one in affiliations):  # fmt: skip
        return None, f"{path.name}: each of `affiliations` needs its `text`"
    return document, ""


def english_of(profile: dict) -> str | None:
    """The `--english` value the profile's English stands for, None for "either" or none."""
    return ENGLISH_OF.get(str(profile.get("english_variant") or ""))


def _slug(profile: Path) -> str:
    """The name the profile is staged under: its own where that is a plain name."""
    return profile.stem if re.fullmatch(r"[A-Za-z0-9_.-]+", profile.stem) else "journal"


def run_journal(
    paper: Path, profile_path: Path, profile: dict, tree=None, *, english: str | None = None,
    cited: set[str] | None = None,
) -> JournalRun:  # fmt: skip
    """G4 on `paper`, its LaTeX tree given where it is one, held to `profile`."""
    from manuscript_guard.auditing.gates import _putting_back, _stage, audit_project
    from manuscript_guard.gates.journal import FROM_RECORDS, check_journal
    from manuscript_guard.gates.journal_boxes import check_boxes
    from manuscript_guard.policy import SUBMISSION

    run = JournalRun(paper, profile_path)
    run.manual = [(str(rule.get("rule", "")), str(rule.get("quote", "")))
                  for rule in profile.get("manual") or [] if isinstance(rule, dict)]  # fmt: skip
    run.skipped = [*FROM_RECORDS, GRAPHICAL]
    if cited is None and isinstance(profile.get("data_availability"), dict):
        run.skipped.append(UNCITED)
    try:
        staged = _stage(paper, tree)
    except ValueError as exc:
        run.note = f"G4 was not run on {paper.name}: {exc}"
        return run
    run.converted = staged.converted
    if _html_tables(staged, profile):
        run.skipped.append(HTML_TABLES)
    slug = _slug(profile_path)
    with tempfile.TemporaryDirectory(prefix="mg-audit-") as folder:
        root = Path(folder).resolve()
        project = audit_project(root, staged, english)
        staged_profile = root / "profiles" / "journals" / f"{slug}.yaml"
        staged_profile.parent.mkdir(parents=True)
        staged_profile.write_bytes(profile_path.read_bytes())
        project = replace(project, paper={**project.paper, "target_journal": slug})
        put_back = _putting_back(root / "manuscript", staged.back)
        try:
            found = [*check_journal(project, records=False, cited=cited).sorted().findings,
                     *check_boxes(project, {}, SUBMISSION).sorted().findings]  # fmt: skip
        except Exception as exc:  # noqa: BLE001 - a gate that raised is said, not hidden
            run.note = f"G4 could not run on {paper.name}: {type(exc).__name__}: {exc}"
            return run
        for finding in found:
            if finding.code == "graphical-abstract-missing":
                continue  # a file of its own, said under what was not checked
            if finding.path is not None and Path(finding.path).resolve() == staged_profile:
                run.findings.append(replace(finding, path=profile_path))
            else:
                run.findings.append(put_back(finding))
    return run


#: Said under what was not checked where no reference list was read, so that no DOI of the
#: data availability statement can be said to be cited or not.
UNCITED = ("whether each DOI the data availability statement names is cited: no reference "
           "list was read, as in a LaTeX paper whose list is in its .bib")
#: Said where the main document holds a table written in HTML, which is not counted.
HTML_TABLES = ("the tables written in HTML, which are not counted toward the journal's limits "
               "on tables and display items")


def _html_tables(staged, profile: dict) -> bool:
    """Whether a Markdown main document, as staged, prints a table written in HTML, and the
    profile limits its tables."""
    from manuscript_guard.text.sections import scannable

    limits = profile.get("limits") or {}
    if not ({"tables", "display_items"} & set(limits)) or "main.md" not in staged.files:
        return False
    return re.search(r"(?i)<table\b", scannable(staged.files["main.md"])) is not None


def look_for_authors(run: JournalRun, papers: list[tuple[Path, object]], profile: dict,
                     authors: dict | None) -> None:  # fmt: skip
    """Each place an author is named in each document of the submission, `papers` each with
    its LaTeX tree where it is one, where the profile says the review is blind and the
    authors are given; else why nobody was looked for. A review that is not blind, with no
    authors given, is said nothing of."""
    from manuscript_guard.build.blinding import BLIND, found_in, sought

    kind = profile.get("blinding")
    if kind not in BLIND:
        if authors is not None:
            run.blind_note = (f"the profile says the journal's review is "
                              f"{kind or 'not blind'}, so the authors were not looked for")
        return
    if authors is None:
        run.blind_note = (f"the journal's review is {kind}-blind, and the authors were not "
                          "looked for: --authors names them; the names Word keeps are listed "
                          "in the Document section")  # fmt: skip
        return
    run.looked = kind
    unread = []
    for paper, tree in papers:
        places = _places(paper, tree)
        if isinstance(places, str):
            unread.append(places)
            continue
        wanted = sought(authors, latex=paper.suffix.lower() == ".tex")
        run.named += [replace(f, gate="audit", hint=NAMED_HINT) for f in
                      found_in(places, wanted, kind, paper).findings]  # fmt: skip
    run.blind_note = "; ".join(unread)


#: What a tracked change deleted is called among the places a name is looked for.
DELETED = "the text a tracked change deleted"


def _places(paper: Path, tree) -> list[tuple[str, str]] | str:
    """Where in one document a name can be, the reference list left out as the audit finds
    it (`audit.read_paper`), where a blind journal's authors cite their own work in the third
    person; or why the document could not be read.

    A .docx: its text as the audit reads it, its list cut; what a tracked change deleted
    outside a list styled "Bibliography"; and the rest the build reads, its notes, comments,
    headers, author fields, links and pictures (`build.blinding.docx_places`). A LaTeX
    paper: each file its tree reads, its `thebibliography` left out, and the pictures it
    places (`_placed_pictures`). Markdown: its text, its list cut."""
    from manuscript_guard.audit import read_paper
    from manuscript_guard.build.blinding import deleted_text, docx_places, latex_places
    from manuscript_guard.safexml import UnsafeDocument
    from manuscript_guard.text.docx import NotADocx

    try:
        if tree is not None:
            files = [path for path, _source in tree.files]
            return latex_places(list(dict.fromkeys([*files, *_placed_pictures(tree)])))
        text = read_paper(paper)[0]
        if paper.suffix.lower() != ".docx":
            return [("the text", text)]
        return [*docx_places(paper, body=False), ("the text", text),
                (DELETED, deleted_text(paper))]
    except (UnsafeDocument, NotADocx, OSError, ValueError) as exc:
        return f"{paper.name} could not be read for the authors' names: {exc}"


#: `\includegraphics[options]{name}`, and the comment that ends a LaTeX line.
_GRAPHIC = re.compile(r"\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
_COMMENT = re.compile(r"(?<!\\)%.*")


def _placed_pictures(tree) -> list[Path]:
    """The PDF and SVG pictures the files of `tree` place with `\\includegraphics`, found
    from the entry's folder as LaTeX finds them, a name with no extension as `.pdf` or `.svg`
    there; not every picture in the folder, where a compiled copy of the paper may be."""
    from manuscript_guard.contracts._schema import ContractError, read_text

    found: list[Path] = []
    for path, _source in tree.files:
        try:
            text = read_text(path)
        except (ContractError, OSError):
            continue  # a file the tree read once and cannot now: its own reading says so
        written = "\n".join(_COMMENT.sub("", line) for line in text.split("\n"))
        for match in _GRAPHIC.finditer(written):
            name = match[1].strip().strip('"')
            for folder in dict.fromkeys((tree.folder, path.parent)):
                given = folder / name
                tried = [given] if given.suffix else [given.with_name(given.name + suffix)
                                                      for suffix in (".pdf", ".svg")]
                hit = next((p for p in tried if p.is_file()), None)
                if hit is not None:
                    if hit.suffix.lower() in (".pdf", ".svg"):
                        found.append(hit)
                    break
    return found


#: What an editor does about an author named in a document the journal reviews blind: the
#: build's hints tell the author how to build it again.
NAMED_HINT = ("the reviewers would read it: ask the authors for a file without it, or remove it "
              "before the paper is sent for review")
