"""G4: the AI-use statement names the models the records hold.

More journals ask which AI tools were used and for what, and part of the answer is on file:
a record of a model's work names the model (DESIGN.md, "The AI-use statement names the
models the records hold"). What no record holds the authors declare under `ai_use` in
`authors.yaml`. The statement is then held to both, by the names alone (`text/model_names`):

- `ai-use-model-unnamed`: a statement is found, by the profile's `kind: ai_use` entry or
  under a heading of the default kind, and a model on record or a tool declared is not
  named in it. A warning, and a failure at submission where the profile's entry found it.
- `ai-use-not-stated`: the profile has no such entry, no heading of the default kind is in
  the main text or the supplement, and a model or a tool is named nowhere in the manuscript
  (a note, D6.3).
- `ai-use-undeclared`: the profile has such an entry and `authors.yaml` has no `ai_use`
  (a note).

A record says a model made it by a `provenance` with a `model`, or by its maker's name
written `provider/model` (D6.4). Seven kinds of record are read (D6.7), each known by its
`schema` line. A refused reply is not, nor anything a record does not say a model made.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured, read_text, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.text.blocks import find_headings, scannable
from manuscript_guard.text.model_names import named

GATE = "G4"
KIND = "ai_use"
UNNAMED = "ai-use-model-unnamed"
NOT_STATED = "ai-use-not-stated"
UNDECLARED = "ai-use-undeclared"

#: The words `import --apply` writes at the head of a finding's resolution when a suggested
#: edit was accepted in Word (`suggestions._answer`).
TAKEN = "Edited in Word as"

#: A maker's name written as a model's: no white space, a provider, a slash and a model.
_MODEL_NAME = re.compile(r"[^\s/]+/\S*[^\s/]")

#: What each kind of record says a model did, the keys that name its maker, its date's key
#: and the key of its round or number.
_KINDS = {
    "manuscript-guard/review/1": ("read the manuscript", ("reader", "reviewed_by"),
                                  "reviewed_on", "round"),
    "manuscript-guard/design-review/1": ("read the analysis plan", ("reader", "reviewed_by"),
                                         "reviewed_on", "round"),
    "manuscript-guard/currency-reading/1": ("read a cited work for its currency", ("reader",),
                                            "read_on", "number"),
    "manuscript-guard/currency-assessment/1": ("read a reply in Word", ("reader",),
                                               "assessed_on", "number"),
    "manuscript-guard/figure-review/1": ("read a figure", ("reviewed_by",), "reviewed_on",
                                         None),
    "manuscript-guard/currency-search/1": ("wrote a literature search's terms", ("terms_by",),
                                           "searched_on", "number"),
}  # fmt: skip
APPRAISED = "appraised a similar study's method"

#: A heading of the default kind holds a word for the tool and a word for the statement,
#: each singular or plural.
_TOOL = re.compile(
    r"\b(?:AIs?|artificial intelligences?|generative|language models?|LLMs?|chatbots?)\b",
    re.IGNORECASE,
)
_STATEMENT = re.compile(
    r"\b(?:uses?|used|using|statements?|declarations?|disclosures?|assisted|assistances?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Work:
    """One record of a model's work."""

    provider: str | None
    #: The model as it was asked for, without the provider a `provider/model` name gave.
    model: str
    #: The model as the provider named it in its answer, where the record has it.
    reported: str | None
    #: What the model did, as `review --ai-use` says it.
    did: str
    #: The record, relative to the project's folder, with forward slashes.
    record: str
    number: int | None = None
    on: str | None = None
    #: The findings of the reading whose suggested wording `import` took.
    taken: int = 0

    @property
    def key(self) -> str:
        """The model, as one: its name after any slash, case folded."""
        return self.model.rsplit("/", 1)[-1].casefold()


def made_by(name: object, provenance: object) -> tuple[str | None, str, str | None] | None:
    """(provider, model, model reported) where a record says a model made it, else None: a
    `provenance` with a `model` (D6.7), or a maker's name written `provider/model` (D6.4)."""
    if isinstance(provenance, dict):
        model = provenance.get("model")
        if isinstance(model, str) and model.strip():
            provider, reported = provenance.get("provider"), provenance.get("model_reported")
            return (provider.strip() if isinstance(provider, str) and provider.strip() else None,
                    model.strip(),
                    reported.strip() if isinstance(reported, str) and reported.strip()
                    else None)  # fmt: skip
    if isinstance(name, str) and _MODEL_NAME.fullmatch(name.strip()):
        provider, model = name.strip().split("/", 1)
        return provider, model, None
    return None


def _read(path: Path) -> object:
    try:
        return read_structured(path)
    except (ContractError, OSError, UnicodeDecodeError):
        return None


def _shown(project: Project, path: Path) -> str:
    """A record's path as the findings name it: from the project's folder, with forward
    slashes, or whole where a configured folder lies outside it."""
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return path.as_posix()


def _whole(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dated(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _work(project: Project, path: Path, document: object) -> Work | None:
    if not isinstance(document, dict) or document.get("schema") not in _KINDS:
        return None
    did, makers, dated, numbered = _KINDS[document["schema"]]
    name = next((document.get(key) for key in makers if document.get(key)), None)
    found = made_by(name, document.get("provenance"))
    if found is None:
        return None
    findings = document.get("findings") if isinstance(document.get("findings"), list) else []
    taken = sum(
        1 for finding in findings
        if isinstance(finding, dict)
        and str(finding.get("resolution") or "").lstrip().startswith(TAKEN)
    )  # fmt: skip
    return Work(*found, did, _shown(project, path),
                _whole(document.get(numbered)) if numbered else None,
                _dated(document.get(dated)), taken)  # fmt: skip


def _candidates(project: Project) -> Iterator[Path]:
    """The files a model's work may be filed in, in a stable order."""
    from manuscript_guard.currency.records import folder as currency
    from manuscript_guard.gates.design_review import design_root
    from manuscript_guard.gates.review import review_root

    rounds = [review_root(project), design_root(project)]
    for root in rounds:
        if root.is_dir():
            for folder in sorted(root.glob("round-*")):
                if folder.is_dir():
                    yield from sorted(folder.glob("*.yaml"))
    for name in ("readings", "replies", "searches"):
        where = currency(project) / name
        if where.is_dir():
            yield from sorted(where.glob("*.yaml"))
    figures = project.path("figures")
    if figures.is_dir():
        yield from sorted(figures.rglob("*.review.yaml"))


def _appraisals(project: Project) -> Iterator[Work]:
    """The appraisals of `design/methods_review.yaml` a model proposed."""
    from manuscript_guard.methods_review import review_path

    path = review_path(project)
    document = _read(path) if path.is_file() else None
    if not isinstance(document, dict):
        return
    record = _shown(project, path)
    for study in document.get("studies") or []:
        for method in (study.get("methods") or []) if isinstance(study, dict) else []:
            appraisal = method.get("appraisal") if isinstance(method, dict) else None
            if not isinstance(appraisal, dict):
                continue
            found = made_by(appraisal.get("proposed_by"), None)
            if found is not None:
                yield Work(*found, APPRAISED, record, None, _dated(appraisal.get("proposed_on")))


def model_work(project: Project) -> list[Work]:
    """Every record of a model's work in the project, of the seven kinds the check reads."""
    found = [work for path in _candidates(project)
             if (work := _work(project, path, _read(path))) is not None]  # fmt: skip
    return found + list(_appraisals(project))


@dataclass(frozen=True)
class Named:
    """A model on record, or a tool the authors declare: what must be named."""

    shown: str
    spellings: tuple[str, ...]
    #: Where it comes from: the records, or the authors' `ai_use`.
    sources: tuple[str, ...]
    provider: str | None = None


def models(works: Iterable[Work]) -> list[Named]:
    """Each model on record once, with every spelling the records give it."""
    grouped: dict[str, list[Work]] = {}
    for work in works:
        grouped.setdefault(work.key, []).append(work)
    out = []
    for group in grouped.values():
        spellings = tuple(dict.fromkeys(s for w in group for s in (w.model, w.reported) if s))
        provider = next((w.provider for w in group if w.provider), None)
        out.append(Named(group[0].model, spellings, tuple(dict.fromkeys(w.record for w in group)),
                         provider))  # fmt: skip
    return out


def declaration(project: Project) -> dict | None:
    """The authors' `ai_use`, where `authors.yaml` has one."""
    block = (project.authors or {}).get("ai_use") if isinstance(project.authors, dict) else None
    return block if isinstance(block, dict) else None


def declared(project: Project) -> list[Named]:
    """Each tool the authors declare."""
    block = declaration(project) or {}
    uses = block.get("uses") if isinstance(block.get("uses"), list) else []
    out: dict[str, Named] = {}
    for use in uses:
        tool = use.get("tool") if isinstance(use, dict) else None
        if isinstance(tool, str) and tool.strip() and tool.strip().casefold() not in out:
            provider = use.get("provider") if isinstance(use.get("provider"), str) else None
            out[tool.strip().casefold()] = Named(tool.strip(), (tool.strip(),),
                                                 ("authors.yaml, ai_use",), provider)  # fmt: skip
    return list(out.values())


def wanted(project: Project) -> list[Named]:
    """Everything the statement must name (D6.5): each model on record, then each tool the
    authors declare that names no model on record."""
    on_record = models(model_work(project))
    tools = [tool for tool in declared(project)
             if not any(named(tool.shown, model.spellings) for model in on_record)]  # fmt: skip
    return on_record + tools


# ------------------------------------------------------------------- the statement's text


def ai_use_entries(document: object) -> list[dict]:
    """The profile's required statements of `kind: ai_use`."""
    if not isinstance(document, dict):
        return []
    return [entry for entry in document.get("required_statements") or []
            if isinstance(entry, dict) and entry.get("kind") == KIND]  # fmt: skip


def _profile(project: Project) -> tuple[list[dict], Path | None]:
    from manuscript_guard.gates.journal import profile_path

    slug = project.target_journal
    path = profile_path(project, slug) if slug else None
    if path is None:
        return [], None
    document = _read(path)
    if not validate(document, "journal", path, gate=GATE).ok:
        return [], path
    return ai_use_entries(document), path


_BLANK = re.compile(r"\n[ \t\r]*\n")


def _paragraph(written: str, at: int) -> tuple[int, int]:
    """The paragraph `at` is in: between the blank lines of the text as written around it."""
    start, end = 0, len(written)
    for blank in _BLANK.finditer(written):
        if blank.end() <= at:
            start = blank.end()
        elif blank.start() >= at:
            end = blank.start()
            break
    return start, end


def _section(printed: str, headings: list, index: int) -> tuple[int, int]:
    """A heading's own line and its section, to the next heading of its level or above."""
    heading = headings[index]
    closes = next((later.start for later in headings[index + 1 :]
                   if later.level <= heading.level), len(printed))  # fmt: skip
    return heading.start, closes


def places(text: str, pattern: str) -> list[str]:
    """What each match of `pattern` in `text` is in (DESIGN.md, "Where the statement is
    read"): a heading's line and section where the match starts on a heading's line, the
    paragraph otherwise. Comments and fenced listings are blanked, as G4 reads every
    required statement. In the order the text holds them, each once."""
    printed = scannable(text)
    headings = find_headings(printed)
    spans: dict[tuple[int, int], None] = {}
    for match in re.finditer(pattern, printed, re.IGNORECASE | re.MULTILINE):
        at = match.start()
        on = next((index for index, heading in enumerate(headings)
                   if heading.start <= at <= _line_end(printed, heading.start)), None)  # fmt: skip
        span = _section(printed, headings, on) if on is not None else _paragraph(text, at)
        spans[span] = None
    return [printed[start:end] for start, end in sorted(spans)]


def _places(text: str, pattern: object) -> list[str]:
    """`places`, or none where the profile's pattern is no regular expression: G4's own
    check of the statements reads it first, and reports it there."""
    if not isinstance(pattern, str):
        return []
    try:
        return places(text, pattern)
    except re.error:
        return []


def _line_end(text: str, at: int) -> int:
    end = text.find("\n", at)
    return len(text) if end < 0 else end


def default_places(text: str) -> list[str]:
    """Each heading of the default kind in `text`, with its line and its section."""
    printed = scannable(text)
    headings = find_headings(printed)
    return [printed[slice(*_section(printed, headings, index))]
            for index, heading in enumerate(headings)
            if _TOOL.search(heading.title) and _STATEMENT.search(heading.title)]  # fmt: skip


def supplement_text(project: Project) -> str:
    """The supplement as G4 reads the main text (`journal.main_text`): every supplementary
    source in the order the build prints it, less its front matter; a LaTeX supplement's
    printed view."""
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
    from manuscript_guard.text.masking import without_front_matter
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if not folder.is_dir():
        return ""
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.printed import printed_view
        from manuscript_guard.text.latex.structure import read_document

        if not any(is_supplementary(folder, path)
                   for path in source_files(folder, glob="*.tex")):  # fmt: skip
            return ""
        document = read_document(folder, supplementary=True)
        return printed_view([source for source in document.sources if not source.loose
                             and not source.path.lower().endswith(".sty")])  # fmt: skip
    sources = [path for path in source_files(folder) if is_supplementary(folder, path)]
    return "\n\n".join(without_front_matter(read_text(path))
                       for path in printed_order(sources, supplementary=True))  # fmt: skip


# ------------------------------------------------------------------------------- the check


def check_ai_use(project: Project, stage: str | None = None) -> Report:
    """G4's AI-use check on the project, at `stage` (see the module's docstring)."""
    from manuscript_guard.gates.journal import main_text
    from manuscript_guard.policy import SUBMISSION

    entries, profile = _profile(project)
    report = Report()
    if entries and declaration(project) is None:
        report = report.with_findings(Finding(
            gate=GATE, code=UNDECLARED, severity=INFO, path=profile,
            message="the journal asks for an AI-use statement, and authors.yaml declares "
            "nothing of the AI use no record shows",
            hint="add `ai_use` to authors.yaml with what an AI tool did outside the records "
            "(help with drafting or editing, analysis code, translation), or `uses: []` with "
            "your name and the date; the submission-pack skill asks you",
        ))  # fmt: skip
    must = wanted(project)
    if not must:
        return report
    main = main_text(project)
    supplement = supplement_text(project)
    if entries:
        found = [place for entry in entries for place in _places(main, entry.get("pattern"))]
        if not found:
            # No statement: `missing-required-statement`, from the journal's own check.
            return report
        severity = FAIL if stage == SUBMISSION else WARN
        return report.with_findings(*_unnamed(must, found, supplement, severity, profile))
    found = default_places(main) + default_places(supplement)
    if found:
        return report.with_findings(*_unnamed(must, found, "", WARN, None))
    whole = [scannable(main), scannable(supplement)]
    missing = [item for item in must if not _in_any(item, whole)]
    if not missing:
        return report
    return report.with_findings(Finding(
        gate=GATE, code=NOT_STATED, severity=INFO,
        message=f"the records show AI use the manuscript does not state: {_listed(missing)}",
        hint="write a statement under a heading such as \"Use of AI\" that names each of "
        f"them{_from(missing)}; the submission-pack skill drafts it from `manuscript-guard "
        "review --ai-use`",
    ))  # fmt: skip


def _in_any(item: Named, places: Iterable[str]) -> bool:
    return any(named(place, item.spellings) for place in places)


def _unnamed(must: list[Named], found: list[str], supplement: str, severity: str,
             profile: Path | None) -> tuple[Finding, ...]:  # fmt: skip
    missing = [item for item in must if not _in_any(item, found)]
    if not missing:
        return ()
    elsewhere = [item.shown for item in missing if supplement and _in_any(item, [supplement])]
    hint = f"name each as the records spell it{_from(missing)}"
    if elsewhere:
        hint += (f"; {', '.join(elsewhere)} named in the supplement, where the journal does "
                 "not read its statements")  # fmt: skip
    return (Finding(gate=GATE, code=UNNAMED, severity=severity, path=profile,
                    message=f"the AI-use statement does not name {_listed(missing)}",
                    hint=hint),)  # fmt: skip


def _listed(items: list[Named]) -> str:
    return ", ".join(f"{item.shown} ({item.provider})" if item.provider else item.shown
                     for item in items)  # fmt: skip


def _from(items: list[Named]) -> str:
    said = "; ".join(f"{item.shown}: {item.sources[0]}"
                     + (f" and {len(item.sources) - 1} more" if len(item.sources) > 1 else "")
                     for item in items)  # fmt: skip
    return f" ({said})"


def statement_hint(project: Project) -> str:
    """What `missing-required-statement` adds for an `ai_use` entry: the models on record."""
    must = wanted(project)
    if not must:
        return ""
    return (f"; the records show {_listed(must)}, and `manuscript-guard review --ai-use` lists "
            "what each did")  # fmt: skip


# ----------------------------------------------------------------- review --ai-use


def describe(project: Project) -> list[str]:
    """What `review --ai-use` prints: each model on record and what it did, then each use
    the authors declare. Writes nothing."""
    works = model_work(project)
    lines = []
    if not works:
        lines.append("No record shows a model's work.")
    for model in models(works):
        mine = [work for work in works if work.key == model.shown.rsplit("/", 1)[-1].casefold()]
        names = ", ".join(model.spellings)
        lines.append(f"{model.shown}" + (f", from {model.provider}" if model.provider else "")
                     + (f" (spelt {names})" if len(model.spellings) > 1 else ""))  # fmt: skip
        for did in dict.fromkeys(work.did for work in mine):
            done = [work for work in mine if work.did == did]
            numbers = sorted({w.number for w in done if w.number is not None})
            dates = sorted({w.on for w in done if w.on})
            said = f"  {did}: {len(done)} record(s)"
            if numbers:
                said += f", round or number {', '.join(map(str, numbers))}"
            if dates:
                said += f", {dates[0]}" + (f" to {dates[-1]}" if dates[-1] != dates[0] else "")
            lines.append(said)
        taken = sum(work.taken for work in mine)
        if taken:
            lines.append(f"  its suggested wording taken in {taken} finding(s)")
    block = declaration(project)
    if block is None:
        lines.append("authors.yaml declares no AI use outside the records (no `ai_use`).")
        return lines
    uses = block.get("uses") if isinstance(block.get("uses"), list) else []
    who = f"{block.get('declared_by', 'nobody named')}, {block.get('declared_on', 'undated')}"
    if not uses:
        lines.append(f"authors.yaml: no AI use outside the records ({who}).")
    for use in uses:
        if isinstance(use, dict):
            lines.append(f"declared ({who}): {use.get('tool')}, {use.get('purpose')}: "
                         f"{' '.join(str(use.get('what', '')).split())}")  # fmt: skip
    return lines


__all__ = [
    "GATE", "KIND", "NOT_STATED", "TAKEN", "UNDECLARED", "UNNAMED", "Named", "Work",
    "ai_use_entries", "check_ai_use", "declaration", "declared", "default_places", "describe",
    "made_by", "model_work", "models", "places", "statement_hint", "supplement_text", "wanted",
]  # fmt: skip
