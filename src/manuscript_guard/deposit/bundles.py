"""What each bundle `deposit` stages holds, and which target takes which bundle.

A bundle is a list of files, each with its digest and why it goes, made from the records as
`package` makes its own (`plan.Entry`); the folder and the archive are written from the list
(`archive.stage`), once the custodian's checks pass (`preflight`):

- `preregistration`: the analysis plan, the data dictionary and its plain CSV, the record of
  the data sources, a README, CITATION.cff and .zenodo.json. A plan the first results have
  already been written from is refused as a pre-registration, and deposited only with
  `--retrospective "<why>"`, labelled as a plan deposited after them.
- `release`: the package with its crate and its companion page (`package --companion`), with
  VERIFICATION.md and VERIFICATION.json (`verification.py`), the data dictionary's exports
  and each reporting checklist as a table. Refused while `check --stage submission` fails.
- `preprint`: for arXiv, the LaTeX source as one folder that compiles alone, as a .tar.gz,
  and for medRxiv, the built documents and what its form asks (`preprint.py`).
- for `gh-pages`, the release's companion page as `index.html`, and `.nojekyll`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import yaml

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import Finding, Report

from .plan import Entry, PackageError, Withheld, copied, generated

TARGETS = ("zenodo", "zenodo-sandbox", "osf", "arxiv", "medrxiv", "gh-pages")
BUNDLES = ("preregistration", "release", "preprint")
#: The bundles each target takes. A preprint server takes a preprint only, a site the
#: release's page only, and a repository of records the plan or the release.
PAIRS = {
    "zenodo": ("preregistration", "release"),
    "zenodo-sandbox": ("preregistration", "release"),
    "osf": ("preregistration", "release"),
    "arxiv": ("preprint",),
    "medrxiv": ("preprint",),
    "gh-pages": ("release",),
}
#: Why a pair makes no sense, by the target.
WHY_NOT = {
    "arxiv": "arXiv takes a preprint, the paper's LaTeX source",
    "medrxiv": "medRxiv takes a preprint, the paper's built documents",
    "gh-pages": "a site publishes the release's companion page, `--bundle release`",
}
#: The package's findings a deposit asks again in its own preflight: the small counts of what
#: it carries, and the custodian's sign-off of what it sends.
ASKED_AGAIN = frozenset({"package-small-count", "package-not-authorised"})
PLAN = "design/plan.md"
FROZEN = "design/plan.frozen.yaml"
SOURCES = "design/data_sources.yaml"


class DepositError(Exception):
    """The bundle cannot be made: the message says why, and the status is the exit code.
    An empty message is one the command has printed already."""

    def __init__(self, message: str, status: int = 1) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Bundle:
    target: str
    bundle: str
    entries: tuple[Entry, ...]
    withheld: tuple[Withheld, ...] = ()
    #: The results files the bundle carries, or shows, named from the project's root.
    carried: frozenset[str] = frozenset()
    report: Report = field(default_factory=Report)
    #: The files the .tar.gz holds, where the target reads one; otherwise the .zip is of all.
    tarred: tuple[str, ...] | None = None
    notes: tuple[str, ...] = ()
    #: The files the custodian signs off by what they are made from rather than their bytes,
    #: each with that digest: a PDF the author's TeX compiled (`preprint.built_from`).
    signed_as: tuple[tuple[str, str], ...] = ()

    @property
    def name(self) -> str:
        return f"{self.target}-{self.bundle}"


def pair_refusal(target: str, bundle: str) -> str | None:
    """Why the target does not take the bundle, or None where it does."""
    if bundle in PAIRS[target]:
        return None
    why = WHY_NOT.get(target, f"{target} keeps a record of the plan or of the release; a "
                              "preprint goes to arxiv or medrxiv")  # fmt: skip
    return f"--target {target} does not take --bundle {bundle}: {why}"


def retrospective_refusal(bundle: str, retrospective: str | None) -> str | None:
    """Why `--retrospective` is refused with this bundle, or None where it is taken: it
    labels a plan, and a release or a preprint has none to label (round 1 of #460)."""
    if retrospective is None or bundle == "preregistration":
        return None
    return (f"--retrospective labels an analysis plan deposited after its first results, and "
            f"--bundle {bundle} deposits no plan; leave the option out")  # fmt: skip


def frozen_at(project: Project) -> str | None:
    """When the first results were written from the plan, as plan.frozen.yaml records it,
    "a date not recorded" where it records none, or None where there is no such record."""
    path = project.root / FROZEN
    if not path.is_file():
        return None
    try:
        record = read_structured(path)
    except ContractError:
        return "a date not recorded"
    said = record.get("frozen_at") if isinstance(record, dict) else None
    return str(said) if said else "a date not recorded"


def _label(project: Project, retrospective: str | None) -> list[str]:
    when = frozen_at(project)
    if when is None:
        return ["An analysis plan, deposited before any results were written from it: the "
                f"project held no `{FROZEN}`, which the first results write. The day it is "
                "published is the repository's to record."]  # fmt: skip
    return [f"**Analysis plan, deposited after results were first written on {when}.** It is "
            "not a pre-registration.", "", f"Why it is deposited now, as the authors gave it: "
            f"{' '.join(str(retrospective).split())}"]  # fmt: skip


def _plan_readme(project: Project, entries: list[Entry], retrospective: str | None) -> str:
    from .metadata import people

    title = project.paper.get("title", "")
    authors = ", ".join(person.name for person in people(project) if person.name)
    lines = [f"# Analysis plan: {title}", "", *([authors, ""] if authors else []),
             *_label(project, retrospective), "", "| File | What it is |", "|---|---|"]  # fmt: skip
    lines += [f"| `{e.path}` | {e.why} |" for e in sorted(entries, key=lambda e: e.path)]
    lines += ["", "A deposit of these files is a file with a date, not an entry in a registry "
              "of studies: a registration is made with the registry."]  # fmt: skip
    return "\n".join(lines) + "\n"


def _plan_citation(project: Project) -> str:
    from .texts import citation

    record = yaml.safe_load(citation(project))
    record["message"] = "If you use this plan, cite it as below, and cite the paper it is for."
    record["title"] = f"Analysis plan for \"{project.paper.get('title', '')}\""
    # A plan is no software; CITATION.cff knows only software and datasets.
    record["type"] = "dataset"
    # `package.doi` is the package's, not the plan's.
    record.pop("doi", None)
    return yaml.safe_dump(record, sort_keys=False, allow_unicode=True, width=1000)


def _plan_zenodo(project: Project, retrospective: bool) -> str:
    from .metadata import zenodo

    record = json.loads(zenodo(project))
    title = project.paper.get("title", "")
    record["title"] = f"Analysis plan for \"{title}\""
    record["upload_type"], record["publication_type"] = "publication", "other"
    record["description"] = (
        f"The analysis plan of the paper \"{title}\", with its data dictionary and the record "
        "of its data sources where it has them. README.md says when it was deposited."
        + (f" It was deposited after results were first written, on {frozen_at(project)}, "
           "and is not a pre-registration." if retrospective else "")
    )  # fmt: skip
    return json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def _design_record(project: Project, at: str, why: str, entries: list[Entry],
                   withheld: list[Withheld]) -> bool:  # fmt: skip
    path = project.root / at
    if path.is_file():
        entries.append(copied(path, at, why))
        return True
    withheld.append(Withheld(at, "not in the project"))
    return False


def _dictionary_exports(project: Project, entries: list[Entry], notes: list[str],
                        *, redcap: bool) -> None:  # fmt: skip
    """The data dictionary as a plain CSV, and with `redcap` as REDCap's data dictionary,
    where it reads and the shape holds it; a note for each left out."""
    from manuscript_guard.contracts.dictionary import load_dictionary
    from manuscript_guard.dictionary_export import ExportRefused, plain_csv
    from manuscript_guard.dictionary_export import redcap as as_redcap

    dictionary, _report = load_dictionary(project)
    if dictionary is None:
        notes.append("no CSV of the data dictionary: it does not read, as `check` says")
        return
    made = [("design/data_dictionary.csv", plain_csv, "the data dictionary, one row a variable")]
    if redcap:
        made.append(("design/data_dictionary.redcap.csv", as_redcap,
                     "the data dictionary as REDCap reads one"))  # fmt: skip
    for at, make, why in made:
        try:
            entries.append(generated(at, make(dictionary).text, why))
        except ExportRefused as refused:
            notes.append(f"{at} is not written: {refused}")


def preregistration(project: Project, retrospective: str | None) -> Bundle:
    """The plan and the records it rests on, as the plan stands."""
    from manuscript_guard.contracts.dictionary import DICTIONARY

    if not (project.root / PLAN).is_file():
        raise DepositError(f"there is no {PLAN}: a pre-registration deposits the analysis plan, "
                           "and the analysis-plan skill says how to write one", 2)  # fmt: skip
    when = frozen_at(project)
    if when is not None and retrospective is None:
        raise DepositError(
            f"{FROZEN} records that results were first written from the plan on {when}, so it "
            "is no pre-registration now. Deposit it as what it is with --retrospective "
            "\"<why it is deposited now>\": it is then labelled as a plan deposited after the "
            "results were first written.")  # fmt: skip
    if when is None and retrospective is not None:
        raise DepositError(f"--retrospective labels a plan deposited after results were "
                           f"written from it, and there is no {FROZEN}: no results have been; "
                           "deposit it without the option", 2)  # fmt: skip
    if retrospective is not None and not retrospective.strip():
        raise DepositError("--retrospective needs the reason the plan is deposited now", 2)
    entries: list[Entry] = []
    withheld: list[Withheld] = []
    notes: list[str] = []
    entries.append(copied(project.root / PLAN, PLAN, "the analysis plan"))
    if when is not None:
        entries.append(copied(project.root / FROZEN, FROZEN, "the plan as it stood when the "
                              "first results were written, kept by the analysis"))  # fmt: skip
    if _design_record(project, DICTIONARY.as_posix(), "the data dictionary", entries, withheld):
        _dictionary_exports(project, entries, notes, redcap=False)
    _design_record(project, SOURCES, "the record of the data sources considered and chosen",
                   entries, withheld)  # fmt: skip
    entries.append(generated("CITATION.cff", _plan_citation(project), "how to cite the plan"))
    entries.append(generated(".zenodo.json", _plan_zenodo(project, when is not None),
                             "the metadata of a Zenodo record of the plan"))  # fmt: skip
    entries.append(generated("README.md", _plan_readme(project, entries, retrospective),
                             "what the deposit is, and when it was made"))  # fmt: skip
    return Bundle("", "preregistration", tuple(sorted(entries, key=lambda e: e.path)),
                  tuple(withheld), notes=tuple(notes))  # fmt: skip


def _package(project: Project, results: Results):
    """The package with its crate and its page, and the findings that stop it which the
    deposit does not ask again itself."""
    from .plan import plan_package

    try:
        plan = plan_package(project, results, companion=True)
    except PackageError as exc:
        raise DepositError(str(exc), 2) from None
    kept = tuple(f for f in plan.report.findings if f.code not in ASKED_AGAIN)
    return plan, Report(kept)


def _carried(plan) -> frozenset[str]:
    return frozenset(e.path for e in plan.entries if e.path.startswith("results/")
                     and e.path.endswith(".json"))  # fmt: skip


def _checklists(project: Project) -> list[Entry]:
    """Each reporting checklist the project completed, as the table `submit` packs (G5)."""
    from manuscript_guard.build.submission import _is_scale, checklist_table

    found = []
    folder = project.root / "reporting"
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        prefix = "scale" if _is_scale(project, path) else "checklist"
        found.append(generated(f"{prefix}-{path.stem}.md", checklist_table(project, path),
                               "a reporting checklist, each item and where it is answered"))
    return found


def release(project: Project, results: Results, checked: Report) -> Bundle:
    """The package with its crate and page, and what says how it was checked."""
    from .verification import verification
    from .write import MANIFEST, manifest_text

    plan, report = _package(project, results)
    entries = list(plan.entries)
    notes: list[str] = []
    entries.append(generated(MANIFEST, manifest_text(project, plan, checked=True),
                             "every file of the package and its SHA-256"))  # fmt: skip
    markdown, record = verification(project, checked)
    entries.append(generated("VERIFICATION.md", markdown, "how the paper was checked, as "
                             "`check --stage submission` and the records say"))  # fmt: skip
    entries.append(generated("VERIFICATION.json", record, "the same, for a machine"))
    if (project.root / "design" / "data_dictionary.yaml").is_file():
        _dictionary_exports(project, entries, notes, redcap=True)
    entries += _checklists(project)
    return Bundle("", "release", tuple(sorted(entries, key=lambda e: e.path)), plan.withheld,
                  _carried(plan), report, notes=tuple(notes))  # fmt: skip


def gh_pages(project: Project, results: Results) -> Bundle:
    """The release's companion page as a site: index.html, and .nojekyll, which tells GitHub
    Pages to serve the files as they are."""
    plan, report = _package(project, results)
    (page,) = [entry for entry in plan.entries if entry.path == "index.html"]
    nojekyll = generated(".nojekyll", "", "tells GitHub Pages to serve the page as it is")
    return Bundle("", "release", (nojekyll, page), carried=_carried(plan), report=report)


def name_taken(entries: tuple[Entry, ...]) -> list[Finding]:
    """Two files of a bundle at one name, in the case a system that ignores case reads it."""
    seen: dict[str, str] = {}
    found = []
    for entry in entries:
        key = entry.path.casefold()
        if key in seen:
            found.append(Finding("DEPOSIT", "deposit-name-taken", f"{entry.path} ({entry.why}) "
                                 f"would be written over {seen[key]}"))  # fmt: skip
        seen.setdefault(key, entry.path)
    return found


__all__ = ["BUNDLES", "PAIRS", "TARGETS", "Bundle", "DepositError", "frozen_at", "gh_pages",
           "name_taken", "pair_refusal", "preregistration", "release",
           "retrospective_refusal"]  # fmt: skip
