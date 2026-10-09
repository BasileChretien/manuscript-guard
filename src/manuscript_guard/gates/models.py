"""G15 — each model is the model the variables call for, and the Methods name the model fitted.

The analysis records each model as the fit describes itself (`em.model`) and each variable
with the kind it is meant to be (`em.variable`). Most of what goes wrong between the two is
then a comparison, not a judgement: a binary outcome fitted with a linear model, a nominal
code entered as one slope, a reference level that is not the one declared, a level of a
categorical term with no events, a fit that did not converge. What a comparison cannot
settle (whether the adjustment set is right, whether an assumption holds) is left to the
people who read the model card, and this gate does not pretend otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.classify import is_methods
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.models import Model, Variable, engine_of, engines
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.language import _hidden
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.text.placeholders import parse
from manuscript_guard.text.sections import chains_at, footnote_index, heading_index

GATE = "G15"

#: Events, or non-events where fewer, for each coefficient below which a binary-outcome model
#: is reported as fitted on few events. Ten is the rule of thumb Peduzzi and colleagues gave,
#: and the one reviewers ask about; it is a warning, since the literature has since argued
#: both for and against it.
EVENTS_PER_PARAMETER = 10

#: The levels a binary variable entered as a number may take: anything else is a code.
_BINARY_NUMBERS = frozenset({"0", "1", "False", "True"})


def check_models(project: Project, results: Results) -> Report:
    report = Report()
    variables, models = results.variables, results.models
    if not variables and not models:
        # Nothing declared, nothing to say, and no counts either: a project that fits no
        # model reads exactly as it did before there was a G15.
        return report
    for name, variable in sorted(variables.items()):
        report = report.merge(_observed(name, variable))
    if not models:
        return report.with_counts(models=0, model_variables=len(variables))
    referenced = _referenced(project)
    for model in models.values():
        report = report.merge(_model(model, variables, referenced))
    report = report.merge(_names_in_methods(project, models))
    return report.with_counts(models=len(models), model_variables=len(variables))


def _finding(model: Model, code: str, message: str, hint: str, *, warn: bool = False) -> Finding:
    return Finding(
        gate=GATE,
        code=code,
        message=f"model {model.key!r}: {message}",
        path=model.source,
        hint=hint,
        **({"severity": WARN} if warn else {}),
    )


def _observed(name: str, variable: Variable) -> Report:
    """What the data held against what the analysis said the variable is."""
    observed = variable.observed or {}
    findings = []
    seen = observed.get("levels")
    if variable.levels is not None and seen is not None:
        extra = [level for level in seen if level not in variable.levels]
        if extra:
            findings.append(
                Finding(
                    gate=GATE,
                    code="variable-level-undeclared",
                    message=f"variable {name!r} takes {', '.join(map(repr, extra))} in the "
                    f"data, which its declared levels do not include",
                    path=variable.source,
                    hint="declare the level, or recode it before the model reads the data",
                )
            )
    if variable.kind == "binary" and observed.get("distinct", 0) > 2:
        findings.append(
            Finding(
                gate=GATE,
                code="variable-not-binary",
                message=f"variable {name!r} is declared binary and takes "
                f"{observed['distinct']} distinct values in the data",
                path=variable.source,
                hint="declare the kind it is, or derive the binary variable the model means",
            )
        )
    return Report(tuple(findings))


def _model(model: Model, variables: dict[str, Variable], referenced: set[str]) -> Report:
    findings: list[Finding] = []
    engine = engine_of(model.engine)
    if engine is None:
        findings.append(
            _finding(
                model,
                "model-engine-unknown",
                f"no entry in the toolkit's list of models describes this fit "
                f"({', '.join(f'{k}={v}' for k, v in sorted(model.engine.items()))})",
                "its outcome cannot be checked against its kind; the list is "
                "src/manuscript_guard/data/models.yaml",
                warn=True,
            )
        )

    undeclared = [name for name in model.variables() if name not in variables]
    for name in undeclared:
        findings.append(
            _finding(
                model,
                "model-variable-undeclared",
                f"{name!r} is read by the model and never declared",
                "declare it with variable(), with the kind it is meant to be: the kind is "
                "what everything else here is checked against",
            )
        )

    for name in model.outcome["variables"]:
        declared = variables.get(name)
        if engine is not None and declared is not None and declared.kind not in engine.outcome:
            findings.append(
                _finding(
                    model,
                    "model-outcome-kind",
                    f"a {engine.kind} of {declared.label!r}, which is declared "
                    f"{declared.kind}; a {engine.kind} is for a "
                    f"{' or '.join(engine.outcome)} outcome",
                    "fit a model for this kind of outcome, or declare the kind the outcome is",
                )
            )

    for record in model.entered:
        for name in record["variables"]:
            if name in variables:
                findings.extend(_entered(model, record, variables[name]))

    if not model.converged:
        findings.append(
            _finding(
                model,
                "model-not-converged",
                "the fit did not converge, so its estimates are not estimates",
                "look for separation or a sparse level, then refit",
            )
        )
    for name, levels in sorted(model.events_by_level.items()):
        for level, events in levels.items():
            if events == 0:
                findings.append(
                    _finding(
                        model,
                        "model-empty-level",
                        f"no events at level {level!r} of {name!r}: its coefficient cannot be "
                        f"estimated (separation)",
                        "merge the level with a neighbour, or say how the model handles it",
                    )
                )
    if model.events is not None and model.parameters:
        fewer = min(model.events, model.n_used - model.events)
        if fewer / model.parameters < EVENTS_PER_PARAMETER:
            findings.append(
                _finding(
                    model,
                    "model-few-events",
                    f"{fewer} events for {model.parameters} coefficient(s), fewer than "
                    f"{EVENTS_PER_PARAMETER} each",
                    "the estimates may be unstable; fewer terms, or a penalised fit, and say so",
                    warn=True,
                )
            )
    if model.n_dropped and f"results.model.{model.key}.n_dropped" not in referenced:
        findings.append(
            _finding(
                model,
                "model-rows-dropped",
                f"{model.n_dropped} of {model.n_input} rows were dropped, for missing values, "
                f"and the manuscript never says how many",
                f"bind {{{{results.model.{model.key}.n_dropped}}}} where the Methods or the "
                f"Results say how missing data were handled",
            )
        )
    return Report(tuple(findings))


def _entered(model: Model, record: dict, variable: Variable) -> list[Finding]:
    """How a term took a variable, against the kind the variable was declared."""
    label, kind = variable.label, variable.kind
    if record["as"] == "categorical":
        findings = []
        if kind in ("continuous", "count"):
            findings.append(
                _finding(
                    model,
                    "model-number-as-categories",
                    f"{label!r} is declared {kind} and entered as categories",
                    "if the categories are meant, declare the cut points and say why",
                    warn=True,
                )
            )
        if variable.levels is not None:
            extra = [level for level in record["levels"] if level not in variable.levels]
            if extra:
                findings.append(
                    _finding(
                        model,
                        "model-level-undeclared",
                        f"{label!r} entered with level(s) {', '.join(map(repr, extra))}, which "
                        f"it is not declared to have",
                        "declare the level, or recode it before the fit",
                    )
                )
        fitted = record.get("reference")
        if variable.reference is not None and fitted is not None and fitted != variable.reference:
            findings.append(
                _finding(
                    model,
                    "model-reference",
                    f"{label!r} has reference {fitted!r} in the fit and {variable.reference!r} "
                    f"in its declaration",
                    "set the reference in the formula, e.g. C(x, Treatment('level')) or relevel()",
                )
            )
        return findings
    if kind == "categorical":
        return [
            _finding(
                model,
                "model-categories-as-number",
                f"{label!r} is declared categorical and entered as a number, as one slope "
                f"across codes that have no order",
                "enter it as categories: C(x) in a formula, or factor(x) in R",
            )
        ]
    if kind == "ordinal":
        return [
            _finding(
                model,
                "model-ordinal-as-trend",
                f"{label!r} is ordinal and entered as a number: a linear trend across its "
                f"levels, equally spaced",
                "if a trend is meant, the Methods should say so; otherwise enter it as categories",
                warn=True,
            )
        ]
    if kind == "binary":
        seen = (variable.observed or {}).get("levels")
        if seen is not None and not set(seen) <= _BINARY_NUMBERS:
            return [
                _finding(
                    model,
                    "model-binary-as-number",
                    f"{label!r} is binary and entered as a number, and its values "
                    f"({', '.join(map(repr, seen))}) are not 0 and 1",
                    "enter it as categories, or code it 0 and 1",
                )
            ]
    return []


def _referenced(project: Project) -> set[str]:
    refs: set[str] = set()
    for path in source_files(project.path("manuscript")):
        placeholders, _ = parse(read_text(path))
        refs |= {placeholder.ref for placeholder in placeholders}
    return refs


def _names() -> re.Pattern[str]:
    """Every name `data/models.yaml` gives a kind of model, as whole words in any case, with
    a space, a hyphen or a line break between words either way, and in the plural."""
    names = sorted({name for entry in engines() for name in entry.synonyms}, key=len, reverse=True)
    words = [r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", name))) for name in names]
    return re.compile(r"(?<![\w-])(?:" + "|".join(words) + r")s?(?![\w-])", re.IGNORECASE)


def _kind_named(text: str) -> str | None:
    folded = " ".join(re.split(r"[\s-]+", text.casefold())).removesuffix("s")
    for entry in engines():
        names = (" ".join(re.split(r"[\s-]+", n.casefold())) for n in entry.synonyms)
        if any(name.removesuffix("s") == folded for name in names):
            return entry.kind
    return None


def named_in_methods(text: str) -> list[tuple[int, int, str]]:
    """Each model the Methods of `text` name: its offsets, and the kind it names. Read in the
    prose G14 reads words in, with listings, comments, inline code and equations hidden, and
    the Methods are where the headings above say they are, as G2 has them."""
    hidden = _hidden(text)
    headings, notes = heading_index(text), footnote_index(text)
    found = []
    for match in _names().finditer(hidden):
        if not any(is_methods(chain) for chain in chains_at(headings, notes, match.start())):
            continue
        kind = _kind_named(match.group())
        if kind is not None:
            found.append((match.start(), match.end(), kind))
    return found


def _names_in_methods(project: Project, models: dict[str, Model]) -> Report:
    """A kind of model the Methods name, typed. The kind of a model the analysis fitted is
    bound, as a parameter is, because a typed copy is what stays behind when the model is
    changed; a kind it did not fit is a warning, being either that copy already left behind
    or a model the paper mentions and did not use."""
    fitted: dict[str, list[str]] = {}
    for model in models.values():
        if model.kind is not None:
            fitted.setdefault(model.kind, []).append(model.key)
    findings = []
    for path in source_files(project.path("manuscript")):
        text = read_text(path)
        for start, _end, kind in named_in_methods(text):
            where = {
                "path": Path(path),
                "line": text.count("\n", 0, start) + 1,
                "col": start - (text.rfind("\n", 0, start) + 1) + 1,
            }
            if kind in fitted:
                bindings = " or ".join(
                    f"{{{{results.model.{key}.kind}}}}" for key in fitted[kind]
                )
                findings.append(
                    Finding(
                        gate=GATE,
                        code="typed-model-kind",
                        message=f"the Methods type {kind!r}, the kind of a model the analysis "
                        f"fitted, rather than bind it",
                        hint=f"write {bindings}: a typed name stays behind when the model "
                        "is changed",
                        **where,
                    )
                )
                continue
            findings.append(
                Finding(
                    gate=GATE,
                    code="model-kind-unfitted",
                    message=f"the Methods name a {kind}, and the analysis fitted none",
                    severity=WARN,
                    hint="if the paper fitted it, record it with em.model(); if it names a model "
                    "the paper did not use, there is nothing to do",
                    **where,
                )
            )
    return Report(tuple(findings))
