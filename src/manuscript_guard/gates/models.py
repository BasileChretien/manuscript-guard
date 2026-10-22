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
from bisect import bisect_right
from dataclasses import asdict, replace
from pathlib import Path

from manuscript_guard.classify import is_methods
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.models import (
    Engine,
    Model,
    Variable,
    engine_of,
    engines,
    other_model_words,
)
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.language import _hidden
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.sign_offs import Signable, digest_of, settle
from manuscript_guard.text.blocks import Unprinted
from manuscript_guard.text.reader import LATEX, bound_files, manuscript_format
from manuscript_guard.text.sections import chains_at, footnote_index, heading_index

GATE = "G15"

#: Events, or non-events where fewer, for each coefficient below which a binary-outcome model
#: is reported as fitted on few events. Ten is the rule of thumb Peduzzi and colleagues gave,
#: and the one reviewers ask about; it is a warning, since the literature has since argued
#: both for and against it.
EVENTS_PER_PARAMETER = 10

#: The levels a binary variable entered as a number may take: anything else is a code. The
#: two truth values are spelled as each language writes them, Python's and R's.
_BINARY_NUMBERS = frozenset({"0", "1", "False", "True", "FALSE", "TRUE"})

#: What a column of a grouped outcome may be declared: a count, of events or of trials, or
#: the proportion of one in the other.
_GROUPED_OUTCOME = ("count", "continuous")

#: What stands between a word that makes another model of a name and the name: spaces, or
#: one line break. A full stop, or the blank line of a new paragraph, ends what the word
#: was said of.
_BETWEEN = r"(?:[^\S\n]+|[^\S\n]*\n[^\S\n]*)"

#: How far before a model's name such a word is looked for.
_REACH = 80


def check_models(project: Project, results: Results) -> Report:
    """What G15 says of the models, with the warnings the statistician signed off, as they
    stand, reported as information that names them."""
    report = _raised(project, results)
    pending = signables(project, results, report)
    if not pending:
        return report
    # Each signable's findings go back where G15 raised the first of them (round 1 of #304:
    # appended, `models` printed a model's signed warnings after its other findings).
    first = {id(signable.findings[0]): signable for signable in pending}
    signed = {id(finding) for signable in pending for finding in signable.findings}
    findings: tuple[Finding, ...] = ()
    for finding in report.findings:
        if id(finding) in first:
            findings += settle(project, first[id(finding)])
        elif id(finding) not in signed:
            findings += (finding,)
    return Report(findings, report.counts)


def signables(project: Project, results: Results, report: Report | None = None) -> list[Signable]:
    """The warnings about a model that the statistician may sign off. Those of one code on
    one model are signed together, bound to what they say and to the card of each model they
    name, so that a refitted model, or a further variable entered the same way, wants a new
    sign-off."""
    if report is None:
        report = _raised(project, results)
    found: dict[str, list[Finding]] = {}
    for finding in report.warnings:
        for model in results.models.values():
            if finding.message.startswith(f"model {model.key!r}: "):
                found.setdefault(f"{GATE}/{finding.code}/{model.key}", []).append(finding)
                break
    return [
        Signable("statistician", key, _digest(key, said, results), tuple(said))
        for key, said in found.items()
    ]


def _digest(key: str, said: list[Finding], results: Results) -> str:
    """What a sign-off of these findings is bound to: what they say, and the card of each
    model they name, the file it came from by name so that a sign-off holds on another
    machine. Round 1 of #304: `models-on-different-rows` names the smaller model too, and
    bound to the larger one's card alone it kept its sign-off when the smaller was refitted
    on other rows."""
    messages = sorted(finding.message for finding in said)
    cards = {
        model.key: {**asdict(model), "source": model.source.name}
        for model in results.models.values()
        if any(repr(model.key) in message for message in messages)
    }
    return digest_of(key, messages, cards)


def _raised(project: Project, results: Results) -> Report:
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
    report = report.merge(Report(tuple(_rows_compared(models))))
    report = report.merge(_names_in_methods(project, models))
    if manuscript_format(project.path("manuscript")) == LATEX:
        report = _spelt_for_latex(report)
    return report.with_counts(models=len(models), model_variables=len(variables))


#: A binding a hint names, `{{results.model.adjusted.kind}}`.
_HINTED = re.compile(r"\{\{([a-z]+\.[^{}\s]*)\}\}")


def _spelt_for_latex(report: Report) -> Report:
    """Each hint's bindings as a LaTeX manuscript writes them, `\\mg{...}`, as G2 spells its
    own (round 2 of G15 in step 8)."""
    findings = tuple(replace(f, hint=_HINTED.sub(r"\\mg{\1}", f.hint)) if f.hint else f
                     for f in report.findings)  # fmt: skip
    return Report(findings, report.counts)


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


#: Covariance types that take the rows of one unit together, as statsmodels names them.
CLUSTERED = frozenset({"cluster", "hac-groupsum", "hac-panel"})
#: Fits whose structure accounts for rows of one unit: mixed models and estimating equations.
GROUPED_FITS = frozenset(
    {"MixedLM", "BinomialBayesMixedGLM", "PoissonBayesMixedGLM", "GEE", "OrdinalGEE",
     "NominalGEE", "lmerMod", "glmerMod", "geeglm"}
)  # fmt: skip


def _unit(model: Model) -> list[Finding]:
    """Several rows of one unit, fitted as if each row were a unit of its own.

    A model fitted on several rows per patient with ordinary standard errors is one of the
    commonest statistical errors in clinical papers: the intervals are too narrow, and
    nothing in the numbers shows it. Read from the fit, as everything here is: the unit the
    analysis declared, how many of them the rows used hold, and the covariance the fit used.
    """
    if not model.unit or model.unit.get("units", 0) >= model.n_used:
        return []
    clustered = (model.covariance or "").lower() in CLUSTERED
    if clustered or model.engine.get("class") in GROUPED_FITS:
        return []
    column, units = model.unit["column"], model.unit["units"]
    how = f"({model.covariance})" if model.covariance else "(no covariance type recorded)"
    return [
        _finding(
            model,
            "unit-rows-independent",
            f"it was fitted on {model.n_used} rows of {units} {column} values, and its "
            f"standard errors take each row as independent {how}",
            "fit standard errors clustered by the unit (in statsmodels, "
            ".fit(cov_type='cluster', cov_kwds={'groups': ...})), or a mixed model; and if "
            "each unit should have one row, find why the data hold more",
            warn=True,
        )
    ]


#: How a fit says its standard errors are the model's own, not made robust.
MODEL_BASED = frozenset({"nonrobust", "model-based"})


def _rows_compared(models: dict[str, Model]) -> list[Finding]:
    """Two models of one outcome, one's terms among the other's, fitted on different rows.

    A crude and an adjusted estimate are compared to say what the adjustment did. A
    covariate's missing values drop rows from the adjusted model only, and the change
    between the two is then partly the rows'. Equal counts can hide different rows, so the
    cards are compared by a digest of the rows each fit used. Models with the same terms on
    different rows are left alone: that is a subgroup, by design.
    """
    findings = []
    ordered = sorted(models.values(), key=lambda model: model.key)
    for larger in ordered:
        for smaller in ordered:
            if not (smaller.rows_sha256 and larger.rows_sha256):
                continue
            if smaller.rows_sha256 == larger.rows_sha256 or _modelled(smaller) != _modelled(larger):
                continue
            if not _terms(smaller) < _terms(larger):
                continue
            findings.append(
                _finding(
                    larger,
                    "models-on-different-rows",
                    f"its terms include all of {smaller.key!r}'s, for the same outcome, and the "
                    f"two were fitted on different rows ({larger.n_used} and {smaller.n_used} "
                    f"used): the change between their estimates is partly the rows'",
                    "fit both on the rows the larger model uses (drop the rows missing a "
                    "covariate before fitting either), or say in the Methods why they differ",
                    warn=True,
                )
            )
    return findings


def _modelled(model: Model) -> tuple:
    """The outcome a model is of: its variables, whether it is a comparison, and its
    expression without its spaces, so that `I(score > 5)` and `I(score > 10)` are two
    outcomes and not one (round 1 of #289)."""
    outcome = model.outcome
    expression = re.sub(r"\s+", "", str(outcome.get("expression") or ""))
    return tuple(outcome.get("variables", ())), outcome.get("comparison"), expression


def _terms(model: Model) -> frozenset[str]:
    return frozenset(str(term.get("term")) for term in model.terms)


def _poisson_of_binary(model: Model, engine, variables: dict[str, Variable]) -> list[Finding]:
    """A Poisson regression of a binary outcome with the model's own standard errors.

    Poisson regression of a binary outcome estimates a risk ratio, and its model-based
    variance overstates the error; a robust (sandwich) variance corrects it (Zou, Am J
    Epidemiol 2004;159:702-6). Read from the covariance the card records, so a variance made
    robust after the fit, outside it, is not seen. A fit with an offset or an exposure is a
    rate model of events over person-time, whose own variance is the right one (round 1 of
    #289), and is left alone.
    """
    if engine.kind != "Poisson regression" or (model.covariance or "") not in MODEL_BASED:
        return []
    if model.offset:
        return []
    binary = model.outcome.get("comparison") or any(
        name in variables and variables[name].kind == "binary"
        for name in model.outcome.get("variables", ())
    )
    if not binary:
        return []
    return [
        _finding(
            model,
            "poisson-binary-variance",
            f"a Poisson regression of a binary outcome with {model.covariance} standard "
            f"errors, which overstate the error of its risk ratio",
            "fit it with a robust (sandwich) variance, in statsmodels .fit(cov_type='HC0'), "
            "or a log-binomial model; in R the card cannot see a variance computed beside the "
            "fit (sandwich::vcovHC), so this stays for a modified Poisson model, and the fit "
            "it reads is glm(family = binomial(link = 'log')); Zou, Am J Epidemiol "
            "2004;159:702-6",
            warn=True,
        )
    ]


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

    if engine is not None:
        findings.extend(_outcome(model, engine, variables))
        findings.extend(_poisson_of_binary(model, engine, variables))

    for record in model.entered:
        if record.get("comparison"):
            # `I(stage == 'IV')` is a binary term of its own: the kind, the levels and the
            # reference of the variable it reads are not its own.
            continue
        for name in record["variables"]:
            if name in variables:
                findings.extend(_entered(model, record, variables[name]))

    findings.extend(_unit(model))

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
        # Grouped data have their trials; otherwise each row used is one.
        trials = model.n_used if model.trials is None else model.trials
        fewer = min(model.events, trials - model.events)
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


def _outcome(model: Model, engine: Engine, variables: dict[str, Variable]) -> list[Finding]:
    """The outcome against the kinds its model is for.

    A comparison written in the formula, `I(score > 5)`, is a binary outcome of its own and
    is not held to the kind of the variable it reads. The columns of grouped data are
    counts, or their proportion, under a model whose outcome is binary: the binary outcome
    is each trial's.
    """
    if model.outcome.get("comparison"):
        return []
    grouped = model.trials is not None and "binary" in engine.outcome
    findings = []
    for name in model.outcome["variables"]:
        declared = variables.get(name)
        if declared is None:
            continue
        if grouped and declared.kind not in _GROUPED_OUTCOME:
            findings.append(
                _finding(
                    model,
                    "model-outcome-kind",
                    f"a {engine.kind} of grouped data, where {declared.label!r} holds the "
                    f"events or the trials of each row; it is declared {declared.kind}",
                    "declare it a count: in grouped data the binary outcome is each "
                    "trial's, not this column's",
                )
            )
        elif not grouped and declared.kind not in engine.outcome:
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
    return findings


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
    """Every binding the manuscript holds, in either format (step 8)."""
    return {placeholder.ref for bound in bound_files(project) for placeholder in bound.placeholders}


def _names() -> re.Pattern[str]:
    """Every name `data/models.yaml` gives a kind of model, as whole words in any case, with
    a space, a hyphen or a line break between words either way, and in the plural."""
    names = sorted({name for entry in engines() for name in entry.synonyms}, key=len, reverse=True)
    words = [r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", name))) for name in names]
    return re.compile(r"(?<![\w-])(?:" + "|".join(words) + r")s?(?![\w-])", re.IGNORECASE)


def _other_model(hidden: str, start: int) -> bool:
    """Whether the name at `start` stands directly after a word that makes it the name of
    another model: "conditional" before "logistic regression". The words are those of
    `data/models.yaml`, as whole words in any case, with a space, a hyphen or a line break
    inside one either way, and spaces or one line break between the word and the name."""
    words = sorted(other_model_words(), key=len, reverse=True)
    spelled = [r"[\s-]+".join(map(re.escape, re.split(r"[\s-]+", word))) for word in words]
    before = re.compile(
        r"(?<![\w-])(?:" + "|".join(spelled) + ")" + _BETWEEN + r"\Z", re.IGNORECASE
    )
    return before.search(hidden, max(0, start - _REACH), start) is not None


def _kind_named(text: str) -> str | None:
    folded = " ".join(re.split(r"[\s-]+", text.casefold())).removesuffix("s")
    for entry in engines():
        names = (" ".join(re.split(r"[\s-]+", n.casefold())) for n in entry.synonyms)
        if any(name.removesuffix("s") == folded for name in names):
            return entry.kind
    return None


def _heading_lines(text: str, headings: list) -> list[tuple[int, int]]:
    """Where each printed heading's title line stands: an ATX line, or the line above a
    setext rule. A line shaped like a heading that pandoc prints as text is text."""
    lines = []
    for heading in headings:
        if type(heading.title) is Unprinted:
            continue
        end = text.find("\n", heading.start)
        lines.append((heading.start, len(text) if end < 0 else end))
    return lines


def named_in_methods(text: str) -> list[tuple[int, int, str]]:
    """Each model the Methods of `text` name: its offsets, and the kind it names. Read in the
    prose G14 reads words in, with listings, comments, inline code and equations hidden, and
    the Methods are where the headings above say they are, as G2 has them. A name after a
    word that makes it another model's ("conditional logistic regression") is not read, nor
    one in a heading, which names the analysis it heads: the running text is read."""
    headings, notes = heading_index(text), footnote_index(text)
    lines = _heading_lines(text, headings)
    starts = [start for start, _end in lines]

    def methods(start: int) -> bool:
        at = bisect_right(starts, start) - 1
        if at >= 0 and start <= lines[at][1]:
            return False
        return any(is_methods(chain) for chain in chains_at(headings, notes, start))

    return _named(_hidden(text), methods)


def named_in_latex(source) -> list[tuple[int, int, str]]:
    """Each model the Methods of a LaTeX file name, as `named_in_methods` reads Markdown: in
    the words G14 reads (`text/latex/words.py`), so not in a comment, maths, code or a
    figure's float, nor in a heading's title, under the headings the include tree gives at
    each place (step 8)."""
    from manuscript_guard.text.latex.views import chain

    return _named(_latex_words(source), lambda start: is_methods(chain(source, start)))


def _latex_words(source) -> str:
    """A LaTeX file's words as G14 reads them, a space wherever it reads none, and its
    headings' titles blanked, keeping the file's offsets and line breaks."""
    from manuscript_guard.text.latex.mask import NUL
    from manuscript_guard.text.latex.words import words

    out = list(words(source).text.replace(NUL, " "))
    for heading in source.reading.headings:
        for index in range(heading.start, max(heading.end, heading.start)):
            if out[index] != "\n":
                out[index] = " "
    return "".join(out)


def _named(hidden: str, methods) -> list[tuple[int, int, str]]:
    """Each name of a model in `hidden` where `methods` says the Methods are, after no word
    that makes it another model's, with the kind it names."""
    found = []
    for match in _names().finditer(hidden):
        if not methods(match.start()):
            continue
        if _other_model(hidden, match.start()):
            continue
        kind = _kind_named(match.group())
        if kind is not None:
            found.append((match.start(), match.end(), kind))
    return found


def _named_files(project: Project):
    """Each manuscript file, its text as typed, and the models its Methods name: a LaTeX file
    as the include tree reads it, the main text's document and then the supplement's."""
    folder = project.path("manuscript")
    if manuscript_format(folder) != LATEX:
        for path in source_files(folder):
            text = read_text(path)
            yield Path(path), text, named_in_methods(text)
        return
    from manuscript_guard.text.latex.structure import read_document

    for supplementary in (False, True):
        for source in read_document(folder, supplementary=supplementary).sources:
            yield folder / source.path, source.text, named_in_latex(source)


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
    for path, text, named in _named_files(project):
        for start, _end, kind in named:
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
