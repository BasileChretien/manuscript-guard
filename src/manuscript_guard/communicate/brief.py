"""The brief: the paper's own sentences that every communication of it restates.

`communicate brief` writes `communication/brief.yaml` (schema `communication-brief/1`):

    schema: communication-brief/1
    question: [statement]
    design: [statement]
    population: [statement]
    methods: [statement]
    primary_outcome: [statement]
    findings: [statement, with keys: [results.key, ...] and primary: true or false]
    limitations: [statement]
    conclusion: [statement]

Each statement is `{id, text, from: {file, quote}}`. `quote` is a sentence of the manuscript,
or of the analysis plan, word for word; `text` is what a communication may restate, the
quote itself until the author shortens it, and it is held to the quote as any text is.

The scaffold is made the same way every time from the same files, and reads nothing it
guesses at:

- the question, the design, the population, the methods and the primary outcome: the first
  sentence under the plan's heading for each, as G12 finds those headings;
- the findings: each sentence of the Abstract's results that binds a value (under a
  "Results" or "Findings" heading or label, or the whole Abstract where it has neither),
  else of the Results; each with the values it binds as `keys`;
- the limitations: each sentence of the first paragraph outside the Abstract that names a
  limitation, or that stands under a heading that does;
- the conclusion: the sentences of the Abstract's conclusion, else the first paragraph
  under a heading that names one.

Every finding is written `primary: false`. Which finding is the paper's primary one is the
author's to mark, and nothing here infers it: a scaffold that picked the first finding would
put its guess on every post.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from manuscript_guard.claims import sentence_spans
from manuscript_guard.communicate import GATE, brief_path
from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, read_text, validate
from manuscript_guard.findings import Finding, Report
from manuscript_guard.text.placeholders import VALUE_NAMESPACES, parse
from manuscript_guard.text.section_names import names_abstract, names_conclusion, names_results
from manuscript_guard.text.sections import chain_at, heading_index

SCHEMA = "communication-brief/1"
#: The parts of a brief, in the order it is written.
SECTIONS = (
    "question",
    "design",
    "population",
    "methods",
    "primary_outcome",
    "findings",
    "limitations",
    "conclusion",
)
#: The parts read from the analysis plan, each with the key of G12's heading for it.
_FROM_PLAN = (
    ("question", "question"),
    ("design", "design"),
    ("population", "population"),
    ("methods", "analysis"),
    ("primary_outcome", "outcome"),
)
#: A label that opens a part of a structured abstract written without headings,
#: "**Results.**", "Conclusions:".
_LABEL = re.compile(
    r"\A(?:\*\*|__|\*|_)?[ \t]*(?P<label>[A-Za-z]+(?:[ \t]+(?:and|of|&)[ \t]+[A-Za-z]+)?)"
    r"[ \t]*[.:][ \t]*(?:\*\*|__|\*|_)?[ \t\n]*"
)
_PARTS = {
    "background": "other", "introduction": "other", "aim": "other", "aims": "other",
    "objective": "other", "objectives": "other", "purpose": "other", "context": "other",
    "importance": "other", "methods": "other", "design": "other", "setting": "other",
    "participants": "other", "exposure": "other", "exposures": "other",
    "results": "results", "findings": "results",
    "conclusion": "conclusion", "conclusions": "conclusion", "interpretation": "conclusion",
    "conclusions and relevance": "conclusion",
    "limitations": "other", "discussion": "other",
}  # fmt: skip
_LIMITATION = re.compile(r"(?i)\blimitations?\b")
_PARAGRAPH = re.compile(r"\n[ \t]*\n")
_HEADER = """\
# The paper's own sentences that every communication of it restates: written by
# `manuscript-guard communicate brief`, and the author's from then on.
#
# Each statement's `quote` is a sentence of the manuscript, or of the analysis plan, word
# for word; `communicate check` holds it to that file. Its `text` is what a post, a summary
# or the graphical abstract may say for it: shorten it if you like, and it is held to the
# quote as they are. Delete what no communication should say, and add what one should,
# quoted the same way.
#
# Mark the paper's primary finding `primary: true`. Nothing infers it.
#
# A sentence of a communication names the statement it restates by an anchor, which
# prints nothing: [](#brief:findings.1), or <!-- brief: findings.1 -->.
"""


@dataclass(frozen=True)
class Statement:
    id: str
    section: str
    text: str
    file: str
    quote: str
    keys: tuple[str, ...] = ()
    #: Of a finding, whether the author marked it primary; None for the other parts.
    primary: bool | None = None


@dataclass(frozen=True)
class Brief:
    path: Path
    statements: tuple[Statement, ...] = field(default=())

    @property
    def by_id(self) -> dict[str, Statement]:
        return {statement.id: statement for statement in self.statements}

    def of(self, section: str) -> list[Statement]:
        return [one for one in self.statements if one.section == section]

    @property
    def primary(self) -> list[Statement]:
        return [one for one in self.of("findings") if one.primary]


def fold(text: str) -> str:
    """Every run of white space one space, as a quote is compared."""
    return " ".join(text.split())


# ---------------------------------------------------------------------------- reading


def load(project) -> tuple[Brief | None, Report]:
    """The brief as written, and what is wrong with its shape; None where there is none, or
    none that can be read."""
    path = brief_path(project)
    if not path.is_file():
        return None, Report()
    try:
        document = read_structured(path)
    except ContractError as exc:
        return None, Report((_invalid(path, str(exc)),))
    report = validate(document, "communication-brief", path, gate=GATE, code="brief-invalid")
    if not report.ok:
        return None, report
    statements = []
    for section in SECTIONS:
        for entry in document.get(section) or ():
            keys = tuple(entry.get("keys") or ()) if section == "findings" else ()
            primary = entry.get("primary") if section == "findings" else None
            statements.append(
                Statement(entry["id"], section, entry["text"], entry["from"]["file"],
                          entry["from"]["quote"], keys, primary)  # fmt: skip
            )
    seen: set[str] = set()
    for statement in statements:
        if statement.id in seen:
            report = report.with_findings(
                _invalid(path, f"two statements are named {statement.id!r}: an anchor names one")
            )
        seen.add(statement.id)
    return Brief(path, tuple(statements)), report


def _invalid(path: Path, why: str) -> Finding:
    return Finding(GATE, "brief-invalid", f"{path.name}: {why}", path=path,
                   hint="put it right by hand, or write it again with `communicate brief "
                   "--force`")  # fmt: skip


# ------------------------------------------------------------------- the paper's sources


@dataclass(frozen=True)
class Document:
    """One text the scaffold reads, and where each offset of it comes from: a Markdown file,
    or a LaTeX manuscript's printed view."""

    text: str
    #: Each offset's file, relative to the project's root, and line.
    place: object


def _markdown_documents(project) -> list[Document]:
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files

    folder = project.path("manuscript")
    paths = [p for p in source_files(folder) if not is_supplementary(folder, p)]
    found = []
    for path in printed_order(paths, supplementary=False):
        name = path.relative_to(project.root).as_posix()
        found.append(Document(read_text(path).replace("\r\n", "\n"), lambda _at, n=name: n))
    return found


def _latex_documents(project) -> list[Document]:
    from manuscript_guard.text.latex.printed import printed_of

    folder = project.path("manuscript")
    view = printed_of(folder, supplementary=False, quoting=True)
    base = folder.relative_to(project.root).as_posix()
    entry = f"{base}/main.tex"

    def place(at: int) -> str:
        where = view.place(at)
        return entry if where is None else f"{base}/{Path(where[0].path).as_posix()}"

    return [Document(view.text, place)]


def manuscript_documents(project) -> list[Document]:
    from manuscript_guard.text.reader import LATEX, manuscript_format

    if manuscript_format(project.path("manuscript")) == LATEX:
        return _latex_documents(project)
    return _markdown_documents(project)


def plan_file(project) -> Path:
    from manuscript_guard.gates.design import PLAN

    return project.root / PLAN


# ------------------------------------------------------------------------ the scaffold


@dataclass(frozen=True)
class _Read:
    """A sentence of the manuscript as the scaffold reads it."""

    quote: str
    file: str
    abstract: bool
    part: str
    chain: tuple[str, ...]
    paragraph: tuple[int, int]
    keys: tuple[str, ...]


def _sentences(document: Document, named: str | None, number: int) -> list[_Read]:
    text = document.text
    index = heading_index(text)
    paragraphs = [found.end() for found in _PARAGRAPH.finditer(text)]
    out = []
    part = ""
    in_abstract = False
    for _piece, first, end in sentence_spans(text):
        chain = tuple(chain_at(index, first).printed)
        abstract_at = next((i for i, title in enumerate(chain) if names_abstract(title, named)),
                           None)  # fmt: skip
        if abstract_at is None:
            in_abstract, part = False, ""
        else:
            if not in_abstract:
                part = ""
            in_abstract = True
            deeper = chain[abstract_at + 1 :]
            if deeper:
                part = _part_of(deeper[-1])
        raw = text[first:end]
        label = _LABEL.match(raw)
        if label is not None and " ".join(label["label"].lower().split()) in _PARTS:
            if in_abstract:
                part = _PARTS[" ".join(label["label"].lower().split())]
            raw = raw[label.end() :]
        quote = fold(raw)
        if not re.search(r"[^\W\d_]", quote):
            continue
        keys = tuple(dict.fromkeys(p.ref for p in parse(raw)[0]
                                   if p.namespace in VALUE_NAMESPACES))  # fmt: skip
        out.append(
            _Read(quote, str(document.place(first)), in_abstract, part, chain,
                  (number, bisect_right(paragraphs, first)), keys)  # fmt: skip
        )
    return out


def _part_of(title: str) -> str:
    if names_results(title):
        return "results"
    if names_conclusion(title):
        return "conclusion"
    return "other"


def _statement(section: str, number: int, read: _Read) -> dict:
    return {"id": f"{section}.{number}", "text": read.quote,
            "from": {"file": read.file, "quote": read.quote}}  # fmt: skip


def _from_plan(project) -> dict[str, list[dict]]:
    from manuscript_guard.gates.design import REQUIRED, _plan_sections

    path = plan_file(project)
    if not path.is_file():
        return {}
    sections = _plan_sections(read_text(path).replace("\r\n", "\n"))
    patterns = {key: pattern for key, pattern, _what in REQUIRED}
    name = path.relative_to(project.root).as_posix()
    out: dict[str, list[dict]] = {}
    for part, key in _FROM_PLAN:
        section = next((s for s in sections if s.title and re.search(patterns[key], s.title)),
                       None)  # fmt: skip
        if section is None:
            continue
        for _piece, first, end in sentence_spans(section.body):
            quote = fold(section.body[first:end])
            if re.search(r"[^\W\d_]", quote):
                out[part] = [{"id": f"{part}.1", "text": quote,
                              "from": {"file": name, "quote": quote}}]  # fmt: skip
                break
    return out


def scaffold(project) -> dict:
    """The brief `communicate brief` writes for `project`, the same every time from the same
    files."""
    from manuscript_guard.gates.journal import abstract_title

    named = abstract_title(project)
    read = [one for number, document in enumerate(manuscript_documents(project))
            for one in _sentences(document, named, number)]  # fmt: skip
    document: dict = {"schema": SCHEMA}
    document.update(_from_plan(project))
    abstract = [one for one in read if one.abstract]
    parted = any(one.part for one in abstract)
    findings = [one for one in abstract if one.keys and (one.part == "results" or not parted)]
    if not findings:
        findings = [one for one in read if not one.abstract and one.keys
                    and any(names_results(title) for title in one.chain)]  # fmt: skip
    document["findings"] = [
        {**_statement("findings", number, one), "keys": list(one.keys), "primary": False}
        for number, one in enumerate(findings, 1)
    ]
    limited = next((one.paragraph for one in read if not one.abstract
                    and (_LIMITATION.search(one.quote)
                         or any(_LIMITATION.search(title) for title in one.chain[-1:]))),
                   None)  # fmt: skip
    limitations = [one for one in read if one.paragraph == limited and not one.abstract]
    document["limitations"] = [_statement("limitations", number, one)
                               for number, one in enumerate(limitations, 1)]  # fmt: skip
    conclusion = [one for one in abstract if one.part == "conclusion"]
    if not conclusion:
        closing = next((one.paragraph for one in read if not one.abstract
                        and any(names_conclusion(title) for title in one.chain)), None)  # fmt: skip
        conclusion = [one for one in read if one.paragraph == closing and not one.abstract]
    document["conclusion"] = [_statement("conclusion", number, one)
                              for number, one in enumerate(conclusion, 1)]  # fmt: skip
    return {key: document[key] for key in ("schema", *SECTIONS) if key in document}


def dump(document: dict) -> str:
    """The brief as `communicate brief` writes it: its header, then the YAML."""
    body = yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True, width=10**6, default_flow_style=False
    )
    return _HEADER + "\n" + body


# -------------------------------------------------------------------------- the quotes


def _sources(project) -> dict[str, str]:
    """Each file a quote may come from, relative to the project's root, with its text
    folded: the manuscript's files, the analysis plan, and for a LaTeX manuscript each
    `.tex` file as its document prints it."""
    from manuscript_guard.text.reader import LATEX, manuscript_files, manuscript_format

    out: dict[str, str] = {}
    folder = project.path("manuscript")
    printed = ""
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.printed import printed_document

        printed = " ".join(fold(printed_document(folder, supplementary=supplementary,
                                                 quoting=True))
                           for supplementary in (False, True))  # fmt: skip
    for path in manuscript_files(project):
        text = fold(read_text(path))
        out[path.relative_to(project.root).as_posix()] = f"{text} {printed}" if printed else text
    plan = plan_file(project)
    if plan.is_file():
        out[plan.relative_to(project.root).as_posix()] = fold(read_text(plan))
    return out


def quote_findings(project, brief: Brief) -> list[Finding]:
    """`brief-quote-not-in-source` for each statement whose quote its file does not hold,
    or that names a file that is neither the manuscript's nor the analysis plan."""
    sources = _sources(project)
    found = []
    for statement in brief.statements:
        held = sources.get(Path(statement.file).as_posix())
        if held is None:
            why = (f"names {statement.file}, which is no file of the manuscript and not the "
                   "analysis plan")  # fmt: skip
        elif fold(statement.quote) not in held:
            why = f"quotes a sentence {statement.file} does not hold"
        else:
            continue
        found.append(
            Finding(GATE, "brief-quote-not-in-source", f"statement {statement.id} {why}",
                    path=brief.path, context=fold(statement.quote)[:160],
                    hint="copy the sentence from the file as it stands now, or write the "
                    "brief again (`communicate brief --force`) after the manuscript changed")
        )  # fmt: skip
    return found
