"""G4: what the Data availability statement says, where the journal's profile declares it.

G4 found the statement's heading and read nothing under it. A journal's policy says more:
Springer Nature asks that data which cannot be shared openly say why and how they can be had,
and PLOS that data be in a repository by the time of publication, named with a persistent
identifier. Those rules differ from one journal to the next, and a universal one would fail
this toolkit's own example, whose statement names no identifier. So each rule is the
profile's, read from the journal's own page and dated, and nothing is checked where the
profile declares none:

- a phrasing the journal does not accept, unless the statement also gives what makes it
  acceptable, a reason or a route (`data-statement-forbidden`);
- no persistent identifier, where the journal requires one and the statement is none of the
  journal's own forms for having no data (`data-identifier-missing`).

And two warnings wherever the profile declares a policy: a link to storage that is neither
persistent nor archived, a shared drive or a bare repository on a code host
(`data-link-temporary`), and a DOI in the statement that the reference list does not cite
(`data-doi-uncited`), since data the conclusions rest on are cited like any other source.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.text.sections import scannable, split_sections

GATE = "G4"
BIB_FILE = "references.bib"

#: The statement's heading where the profile names none, numbered or not: "7. Data
#: availability", "Data and code availability".
HEADING = (
    r"(?i)^[\W\d]*(?:data (?:and code |and materials )?availability|availability of data"
    r"|data sharing)\b"
)

#: What names a dataset so that it can be found again: a DOI, an accession number of the
#: archives clinical and biomedical data go to, a handle or an ARK, and a page archived by a
#: web archive. A profile adds the journal's own with `identifier_patterns`.
IDENTIFIERS = (
    r"\b10\.\d{4,9}/\S",  # a DOI, bare or in a doi.org link
    r"\bGS[EM]\d{3,}\b",  # GEO series and samples
    r"\b[SED]R[APRSXZ]\d{6,}\b",  # SRA, ENA and DDBJ studies, runs and samples
    r"\bPRJ[EDN][A-Z]\d+\b",  # BioProject
    r"\bEGA[SD]\d{11}\b",  # European Genome-phenome Archive
    r"\bE-[A-Z]{4}-\d+\b",  # ArrayExpress and BioStudies
    r"\bphs\d{6}(?:\.v\d+)?\b",  # dbGaP
    r"\bhdl\.handle\.net/\S+",
    r"\bark:/\d+/\S+",
    r"\bzenodo\.org/records?/\d+",
    r"\bosf\.io/[a-z0-9]{5}\b",
    r"\bweb\.archive\.org/web/\d+",
    r"\bperma\.cc/\S+",
)

#: Storage that is neither persistent nor archived: a shared drive, and a repository on a
#: code host linked bare, which its owner can rewrite or delete. A release, a tag or a commit
#: of one is a fixed version, and is not here.
TEMPORARY = re.compile(
    r"https?://(?:www\.)?(?:drive\.google\.com|docs\.google\.com|dropbox\.com"
    r"|dl\.dropboxusercontent\.com|1drv\.ms|onedrive\.live\.com|(?:[\w-]+\.)?box\.com"
    r"|wetransfer\.com|we\.tl)\S*"
    r"|https?://(?:www\.)?(?:github|gitlab)\.com/[\w.-]+/[\w.-]+/?(?![\w/-])",
    re.IGNORECASE,
)

#: A DOI as a statement writes it: a parenthesis inside it is the DOI's own, "10.1016/
#: S0140-6736(20)30183-5", and the marks of emphasis or quotation round it are not.
_DOI = re.compile(r"\b10\.\d{4,9}/(?:[^\s,;()<>\[\]\"\u201d*]|\([^\s()]*\))+")


def statement_text(text: str, heading: str | None = None) -> str | None:
    """The text under the Data availability heading, comments and listings blanked, or None
    where the manuscript has no such heading. Of several headings that match, the outermost:
    "### Data sharing between sites" in the Methods is not the statement (round 1 of #269)."""
    wanted = re.compile(heading or HEADING, re.IGNORECASE)
    found = [s for s in split_sections(scannable(text)) if s.title and wanted.search(s.title)]
    if not found:
        return None
    return min(found, key=lambda section: section.level).enclosed


def judge_statement(statement: str, policy: dict, cited: set[str], path: Path) -> Report:
    """What the journal's data policy says of one statement."""
    report = Report()
    for rule in policy.get("forbidden") or []:
        found = re.search(rule["pattern"], statement, re.IGNORECASE)
        unless = rule.get("unless")
        if found is None or (unless and re.search(unless, statement, re.IGNORECASE)):
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="data-statement-forbidden",
                message=f"the data availability statement says {found.group(0)!r}, which "
                f"the journal does not accept as it stands",
                path=path,
                context=" ".join(statement.split())[:160],
                hint=rule.get("why") or f"the profile forbids {rule['pattern']!r}",
            )
        )
    if policy.get("identifier_required") and not _identified(statement, policy):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="data-identifier-missing",
                message="the data availability statement names no persistent identifier, "
                "and the journal requires one",
                path=path,
                context=" ".join(statement.split())[:160],
                hint="name the repository and the dataset's DOI or accession number, or use "
                "one of the journal's own forms for an article with no data",
            )
        )
    for link in TEMPORARY.finditer(statement):
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="data-link-temporary",
                severity=WARN,
                message=f"{link.group(0)!r} is storage that is neither persistent nor archived",
                path=path,
                hint="deposit the data in a repository that gives a DOI or an accession "
                "number, or link a release or an archived copy",
            )
        )
    for doi in sorted({_plain_doi(found.group(0)) for found in _DOI.finditer(statement)}):
        if doi not in cited:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="data-doi-uncited",
                    severity=WARN,
                    message=f"the dataset {doi} is named in the statement and not cited",
                    path=path,
                    hint="cite the dataset in the reference list as well, with its creator, "
                    "title, repository, year and DOI",
                )
            )
    return report


def _identified(statement: str, policy: dict) -> bool:
    patterns = list(IDENTIFIERS) + list(policy.get("identifier_patterns") or [])
    patterns += list(policy.get("no_data") or [])
    return any(re.search(pattern, statement, re.IGNORECASE) for pattern in patterns)


def _plain_doi(written: str) -> str:
    return written.rstrip(".:").lower()


def cited_dois(project: Project) -> set[str]:
    """The DOIs of every entry of the committed reference list, as the statement's are read."""
    from manuscript_guard.gates.identifiers import normal_doi
    from manuscript_guard.literature.bibfile import read_entries

    path = project.path("literature") / BIB_FILE
    if not path.is_file():
        return set()
    return {
        _plain_doi(normal_doi(fields["doi"]))
        for fields in read_entries(path).values()
        if fields.get("doi")
    }


def cited_in(statement: str, project: Project) -> str:
    """The DOIs of the datasets the statement cites by key, as the reference list prints them:
    a dataset cited as `[@doe2024]`, which is how a data citation is meant to be made, is named
    by its DOI (round 1 of #269). Only an entry of type `dataset` is one: a cohort profile or a
    methods paper cited in the statement names no data (round 2). BibTeX has no `@dataset`,
    so `@misc` with a `type = {dataset}` field is one too (round 1 of #345)."""
    from manuscript_guard.gates.identifiers import normal_doi
    from manuscript_guard.literature.bibfile import TYPE_FIELD, read_entries
    from manuscript_guard.zotero import find_citations

    path = project.path("literature") / BIB_FILE
    keys = {use.citekey for use in find_citations(statement, path)}
    if not keys or not path.is_file():
        return ""
    entries = read_entries(path)
    return " ".join(
        normal_doi(fields["doi"])
        for fields in (entries.get(key, {}) for key in sorted(keys))
        if fields.get("doi")
        and "dataset" in (fields.get("type", "").lower(), fields.get(TYPE_FIELD, "").lower())
    )


def names_doi(text: str, doi: str) -> bool:
    """Whether a statement names this DOI: as one of the DOIs it writes, bare or in a link,
    in any case, and not as the start of a longer one ("10.5281/zenodo.12345678" does not
    name 10.5281/zenodo.1234567)."""
    from manuscript_guard.gates.identifiers import normal_doi

    wanted = _plain_doi(normal_doi(doi))
    return any(_plain_doi(found.group(0)) == wanted for found in _DOI.finditer(text))


def _cited_dois(statement: str, project: Project) -> str:
    """The DOIs of every work the statement cites by key, whatever its type: a package cited
    as `[@doe2026code]` is named by its DOI, whether the entry calls it software or data."""
    from manuscript_guard.literature.bibfile import read_entries
    from manuscript_guard.zotero import find_citations

    path = project.path("literature") / BIB_FILE
    if not path.is_file():
        return ""
    keys = {use.citekey for use in find_citations(statement, path)}
    entries = read_entries(path)
    return " ".join(str(entries[key]["doi"]) for key in sorted(keys)
                    if entries.get(key, {}).get("doi"))  # fmt: skip


def _profile_heading(project: Project) -> str | None:
    """The heading the journal's profile gives the statement, where it gives one."""
    from manuscript_guard.contracts._schema import ContractError, read_structured
    from manuscript_guard.gates.journal import profile_path

    slug = project.target_journal
    path = profile_path(project, slug) if slug else None
    try:
        document = read_structured(path) if path is not None and path.is_file() else None
    except ContractError:
        return None  # G4 says the profile cannot be read
    policy = document.get("data_availability") if isinstance(document, dict) else None
    return policy.get("heading") if isinstance(policy, dict) else None


def check_package_doi(project: Project, *, submission: bool = False) -> Report:
    """Where `paper.yaml` names the DOI of the deposited package (`package.doi`), the Data
    availability statement names it: a warning while the paper is written, a failure at
    submission."""
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.findings import FAIL
    from manuscript_guard.gates.numbers import source_files

    package = project.setting("package")
    doi = package.get("doi") if isinstance(package, dict) else None
    if not doi:
        return Report()
    severity = FAIL if submission else WARN
    heading = _profile_heading(project)
    folder = project.path("manuscript")
    for path in source_files(folder, main_text_only=True) if folder.is_dir() else ():
        statement = statement_text(read_text(path), heading)
        if statement is None:
            continue
        if names_doi(f"{statement}\n{_cited_dois(statement, project)}", str(doi)):
            return Report()
        return Report().with_findings(Finding(
            gate=GATE, code="package-doi-not-named", severity=severity, path=path,
            message=f"the data availability statement does not name {doi}, the DOI paper.yaml "
            "gives the deposited package",
            context=" ".join(statement.split())[:160],
            hint="name the deposit and its DOI in the statement, and cite it in the reference "
            "list; or put package.doi right if the deposit has another",
        ))  # fmt: skip
    return Report().with_findings(Finding(
        gate=GATE, code="package-doi-not-named", severity=severity, path=folder,
        message=f"the manuscript has no data availability statement, and paper.yaml gives the "
        f"deposited package the DOI {doi}",
        hint="add the statement, under a heading such as `# Data availability`, and name the "
        "deposit and its DOI in it",
    ))  # fmt: skip


def check_data_statement(document: dict, text: str, path: Path, project: Project) -> Report:
    """The statement held to the profile's data policy, where the profile declares one."""
    policy = document.get("data_availability")
    if not isinstance(policy, dict):
        return Report()
    statement = statement_text(text, policy.get("heading"))
    if statement is None:
        return Report()  # the required statement's own check says it is missing
    printed = f"{statement}\n{cited_in(statement, project)}"
    return judge_statement(printed, policy, cited_dois(project), path)
