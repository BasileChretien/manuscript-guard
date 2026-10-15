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

#: The statement's heading where the profile names none.
HEADING = r"(?i)^\W*(data availability|availability of data|data sharing)\b"

#: What names a dataset so that it can be found again: a DOI, an accession number of the
#: archives clinical and biomedical data go to, a handle or an ARK, and a page archived by a
#: web archive. A profile adds the journal's own with `identifier_patterns`.
IDENTIFIERS = (
    r"\b10\.\d{4,9}/[^\s,;)\]>]+",  # a DOI, bare or in a doi.org link
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

_DOI = re.compile(r"\b10\.\d{4,9}/[^\s,;)\]>]+")


def statement_text(text: str, heading: str | None = None) -> str | None:
    """The text under the Data availability heading, comments and listings blanked, or None
    where the manuscript has no such heading."""
    wanted = re.compile(heading or HEADING)
    for section in split_sections(scannable(text)):
        if section.title and wanted.search(section.title):
            return section.enclosed
    return None


def judge_statement(statement: str, policy: dict, cited: set[str], path: Path) -> Report:
    """What the journal's data policy says of one statement."""
    report = Report()
    for rule in policy.get("forbidden") or []:
        found = re.search(rule["pattern"], statement)
        if found is None or (rule.get("unless") and re.search(rule["unless"], statement)):
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
    return written.rstrip(".").lower()


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


def check_data_statement(document: dict, text: str, path: Path, project: Project) -> Report:
    """The statement held to the profile's data policy, where the profile declares one."""
    policy = document.get("data_availability")
    if not isinstance(policy, dict):
        return Report()
    statement = statement_text(text, policy.get("heading"))
    if statement is None:
        return Report()  # the required statement's own check says it is missing
    return judge_statement(statement, policy, cited_dois(project), path)
