"""Loading the results namespace from one or more machine-written fragments.

A real project has several analysis scripts, so results live in a directory of fragments
rather than a single file. Each fragment carries its own provenance, which is what lets the
freshness gate say *which* script is stale rather than merely that something is.

A key defined by two fragments is an error. Last-one-wins would make the value of a number
depend on filesystem ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.models import (
    Model,
    Variable,
    describe,
    read_models,
    read_variables,
    table_rows,
    values_of,
)
from manuscript_guard.contracts.values import RESULTS, DisplayError, Value, derive_display
from manuscript_guard.findings import Finding, Report, merge_all

FRAGMENT_GLOB = "*.json"

#: How an analysis publishes its results, in the words every message uses. Three messages
#: said "emit()", which exists in neither language.
HOW_TO_EMIT = (
    "Emitter(__file__, inputs=[...]) and .write() in Python, "
    "mg_emitter(script, inputs) and em$write() in R"
)


@dataclass(frozen=True)
class Fragment:
    path: Path
    generated_by: str
    generated_at: str
    inputs: tuple[dict, ...]
    vcs: dict
    session: dict
    # Digest of the analysis script as it stood when it wrote this fragment. Optional
    # because fragments written before the field existed do not carry it; G1 falls back to
    # comparing modification times for those, which is what it always did.
    generated_by_sha256: str | None = None


@dataclass(frozen=True)
class Table:
    key: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    caption: str | None
    align: tuple[str, ...]
    quoted: bool
    source: Path
    # Which cells the emitter composed, and the literal text of each template. Carried so
    # G2 can apply the emitter's own cell rule to a fragment whoever wrote it — the rule
    # used to be reachable only from inside the Python emitter, which made it a rule an
    # author stepped around by switching language.
    composed: tuple[dict, ...] = ()
    # Made by this package from a model card rather than emitted by an analysis: every cell
    # is a fact the fit recorded, so the check of typed cells has nothing to hold it to.
    generated: bool = False


@dataclass(frozen=True)
class Step:
    """A step of the analysis that ran, marked with `step()`: where its code is, and a digest
    of that code read as code. The Methods point at it with `{{method.<name>}}`."""

    name: str
    script: str
    digest: str
    source: Path
    lines: tuple[int, int] | None = None
    follows: tuple[str, ...] = ()

    @property
    def where(self) -> str:
        """The script and its lines, as an editor opens them: `analysis/a.py:12-15`."""
        if self.lines is None:
            return self.script
        first, last = self.lines
        return f"{self.script}:{first}" + (f"-{last}" if last != first else "")


@dataclass(frozen=True)
class Results:
    values: dict[str, Value]
    fragments: tuple[Fragment, ...]
    tables: dict[str, Table] = field(default_factory=dict)
    # Published code lists, keyed by the table that prints them. G2 checks a code-list cell
    # against these: it is the only independent anchor such a cell has.
    code_lists: dict[str, list] = field(default_factory=dict)
    # The variables the analysis declared and the models it fitted, as `contracts.models`
    # reads them. G15 holds the two to each other.
    variables: dict[str, Variable] = field(default_factory=dict)
    models: dict[str, Model] = field(default_factory=dict)
    # The steps that ran, which the Methods point at; G9 holds each to its claim.
    steps: dict[str, Step] = field(default_factory=dict)

    def get(self, key: str) -> Value | None:
        return self.values.get(key)

    @property
    def quoted_keys(self) -> frozenset[str]:
        return frozenset(k for k, v in self.values.items() if v.quoted)

    @property
    def quoted_tables(self) -> frozenset[str]:
        return frozenset(k for k, t in self.tables.items() if t.quoted)


def load_results(results_dir: Path) -> tuple[Results, Report]:
    """Read and merge every fragment in `results_dir`."""
    if not results_dir.exists():
        return Results({}, ()), Report(
            (
                Finding(
                    gate="G0",
                    code="no-results-dir",
                    message=f"results directory not found: {results_dir}",
                    path=results_dir,
                    hint="run the analysis, or set paths.results in paper.yaml",
                ),
            )
        )

    paths = sorted(results_dir.glob(FRAGMENT_GLOB))
    if not paths:
        return Results({}, ()), Report(
            (
                Finding(
                    gate="G0",
                    code="no-results",
                    message=f"no results fragments in {results_dir}",
                    path=results_dir,
                    hint=f"an analysis script writes one: {HOW_TO_EMIT}",
                ),
            )
        )

    reports: list[Report] = []
    values: dict[str, Value] = {}
    owner: dict[str, Path] = {}
    fragments: list[Fragment] = []
    tables: dict[str, Table] = {}
    code_lists: dict[str, list] = {}
    table_owner: dict[str, Path] = {}
    variables: dict[str, Variable] = {}
    models: dict[str, Model] = {}
    steps: dict[str, Step] = {}

    for path in paths:
        document = read_structured(path)
        report = validate(document, "results", path)
        reports.append(report)
        if not report.ok or not isinstance(document, dict):
            continue

        prov = document["provenance"]
        fragments.append(
            Fragment(
                path=path,
                generated_by=prov["generated_by"],
                generated_at=prov["generated_at"],
                inputs=tuple(prov.get("inputs", ())),
                vcs=prov.get("vcs", {}),
                session=prov.get("session", {}),
                generated_by_sha256=prov.get("generated_by_sha256"),
            )
        )

        for key, spec in document["values"].items():
            if key in owner:
                reports.append(
                    Report(
                        (
                            Finding(
                                gate="G0",
                                code="duplicate-key",
                                message=f"results key {key!r} is defined twice",
                                path=path,
                                context=f"also defined in {owner[key].name}",
                                hint="rename one, or have a single script own the key",
                            ),
                        )
                    )
                )
                continue
            try:
                display = derive_display(
                    key, spec["value"], spec.get("display"), spec.get("digits")
                )
            except DisplayError as exc:
                reports.append(
                    Report((Finding(gate="G0", code="no-display", message=str(exc), path=path),))
                )
                continue
            owner[key] = path
            values[key] = Value(
                key=key,
                value=spec["value"],
                display=display,
                origin=RESULTS,
                source=path,
                unit=spec.get("unit"),
                quoted=spec.get("quoted", True),
                label=bool(spec.get("label", False)),
                same_as=spec.get("same_as"),
                bounds=spec.get("bounds"),
                bound=spec.get("bound"),
                level=spec.get("level"),
                role=spec.get("role"),
                read=spec.get("read"),
            )

        for key, spec in document.get("tables", {}).items():
            if key in table_owner:
                reports.append(
                    Report(
                        (
                            Finding(
                                gate="G0",
                                code="duplicate-table",
                                message=f"table {key!r} is defined twice",
                                path=path,
                                context=f"also defined in {table_owner[key].name}",
                            ),
                        )
                    )
                )
                continue
            table_owner[key] = path
            columns = tuple(spec["columns"])
            code_lists.update(document.get("code_lists") or {})
            tables[key] = Table(
                key=key,
                columns=columns,
                rows=tuple(tuple(row) for row in spec.get("rows", ())),
                caption=spec.get("caption"),
                align=tuple(spec.get("align") or ["left"] * len(columns)),
                quoted=spec.get("quoted", True),
                source=path,
                composed=tuple(spec.get("composed") or ()),
            )
        reports.append(_read_cards(document, path, variables, models))
        reports.append(_read_steps(document, path, steps))

    models_report, values, tables = _models_into(
        models, variables, values, tables
    )
    reports.append(models_report)

    merged = merge_all(reports).with_counts(
        results_fragments=len(fragments),
        results_values=len(values),
        results_tables=len(tables),
    )
    results = Results(values, tuple(fragments), tables, code_lists, variables, models, steps)
    return results, merged


def _read_steps(document: dict, path: Path, steps: dict[str, Step]) -> Report:
    """A fragment's steps, into the project's. A step's name is one step: the Methods could
    not say which of two they describe."""
    findings = []
    script = document["provenance"]["generated_by"]
    for name, spec in (document.get("steps") or {}).items():
        if name in steps:
            findings.append(
                Finding(
                    gate="G0",
                    code="duplicate-step",
                    message=f"step {name!r} is marked by two scripts",
                    path=path,
                    context=f"also marked by {steps[name].script}",
                    hint="give each step its own name: {{method.<name>}} points at one",
                )
            )
            continue
        lines = spec.get("lines")
        steps[name] = Step(
            name=name,
            script=script,
            digest=spec["digest"],
            source=path,
            lines=(lines[0], lines[1]) if lines else None,
            follows=tuple(spec.get("follows") or ()),
        )
    return Report(tuple(findings))


def _read_cards(
    document: dict,
    path: Path,
    variables: dict[str, Variable],
    models: dict[str, Model],
) -> Report:
    """A fragment's variables and models, into the project's. A variable two scripts both
    declare must be declared alike; a model key is one model."""
    findings = []
    for name, variable in read_variables(document, path).items():
        known = variables.get(name)
        if known is not None and (known.kind, known.label, known.levels, known.reference) != (
            variable.kind, variable.label, variable.levels, variable.reference,
        ):  # fmt: skip
            findings.append(
                Finding(
                    gate="G0",
                    code="variable-declared-twice",
                    message=f"variable {name!r} is declared differently by two scripts",
                    path=path,
                    context=f"also declared in {known.source.name}",
                    hint="declare it the same way in both, or in one",
                )
            )
            continue
        variables.setdefault(name, variable)
    for key, model in read_models(document, path).items():
        if key in models:
            findings.append(
                Finding(
                    gate="G0",
                    code="duplicate-model",
                    message=f"model {key!r} is recorded twice",
                    path=path,
                    context=f"also recorded in {models[key].source.name}",
                )
            )
            continue
        models[key] = model
    return Report(tuple(findings))


def _models_into(
    models: dict[str, Model],
    variables: dict[str, Variable],
    values: dict[str, Value],
    tables: dict[str, Table],
) -> tuple[Report, dict[str, Value], dict[str, Table]]:
    """Each model's bindable values and its table, derived from its card.

    `{{results.model.<key>.kind}}` is the name the fit goes by, and `{{table.model_<key>}}`
    the outcome and each variable with the kind it was declared and how it entered: the
    model as the paper describes it is the model as it was fitted, not a retyping of it.
    """
    findings = []
    values, tables = dict(values), dict(tables)
    for model in models.values():
        for key, value in values_of(model).items():
            if key in values:
                findings.append(
                    Finding(
                        gate="G0",
                        code="duplicate-key",
                        message=f"{value.key!r} is a value of model {model.key!r} and is also "
                        f"emitted",
                        path=model.source,
                        hint=f"keys under model.{model.key}. are the model's own",
                    )
                )
                continue
            values[key] = value
        key = f"model_{model.key}"
        if key in tables:
            findings.append(
                Finding(
                    gate="G0",
                    code="duplicate-table",
                    message=f"table {key!r} is model {model.key!r}'s and is also emitted",
                    path=model.source,
                )
            )
            continue
        tables[key] = Table(
            key=key,
            columns=("Variable", "Declared as", "Entered as", "Levels"),
            rows=tuple(tuple(row) for row in table_rows(model, variables)),
            caption=f"{model.name}. {describe(model, variables)}",
            align=("left", "left", "left", "left"),
            quoted=True,
            source=model.source,
            generated=True,
        )
    return Report(tuple(findings)), values, tables
