"""G15: each model is the model its variables call for, and the Methods name the model fitted.

Most tests write a model card and its variables straight into a fragment, through the
emitter so that the fragment is signed as an analysis would sign it, and change one thing
from a card that passes. Reading a card from a real fit is tested at the end, in Python, and
in tests/test_r_emitter.py, in R.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.contracts.models import describe, engine_of, table_rows
from manuscript_guard.emit import Emitter
from manuscript_guard.gates import check_models

CARD = {
    "name": "Adjusted model",
    "description": "The primary analysis.",
    "engine": {
        "language": "Python", "package": "statsmodels", "class": "GLM",
        "family": "Binomial", "link": "Logit",
    },
    "formula": "y ~ x + C(g)",
    "outcome": {"expression": "y", "variables": ["y"]},
    "terms": [
        {"term": "x", "entered": [{"expression": "x", "variables": ["x"], "as": "numerical"}]},
        {
            "term": "C(g)",
            "entered": [
                {
                    "expression": "C(g)", "variables": ["g"], "as": "categorical",
                    "levels": ["a", "b", "c"], "reference": "a",
                }
            ],
        },
    ],
    "parameters": 3,
    "n_input": 1000,
    "n_used": 1000,
    "n_dropped": 0,
    "converged": True,
    "events": 300,
    "events_by_level": {"g": {"a": 100, "b": 100, "c": 100}},
}  # fmt: skip

VARIABLES = {
    "y": {"kind": "binary", "label": "the outcome", "levels": ["0", "1"]},
    "x": {"kind": "continuous", "label": "dose"},
    "g": {"kind": "categorical", "label": "group", "levels": ["a", "b", "c"], "reference": "a"},
}

METHODS = (
    "# Methods\n\nWe fitted a {{results.model.adjusted.kind}}, described in the table.\n\n"
    "{{table.model_adjusted}}\n"
)


def project_with(
    root: Path, card: dict | None = None, variables: dict | None = None, text: str = METHODS
) -> Path:
    (root / "manuscript").mkdir(parents=True, exist_ok=True)
    (root / "analysis").mkdir(exist_ok=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "M"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "manuscript" / "main.md").write_text(text, encoding="utf-8")
    script = root / "analysis" / "fit.py"
    script.write_text("# fits the model\n", encoding="utf-8")
    em = Emitter(script, root=root)
    em._variables.update(copy.deepcopy(VARIABLES if variables is None else variables))
    em._models["adjusted"] = copy.deepcopy(CARD if card is None else card)
    em.write()
    return root


def judged(root: Path):
    project, _ = load_project(root)
    _namespace, results, _literature, loaded = load_namespace(project)
    assert loaded.ok, loaded.render(root)
    return check_models(project, results), results


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


def changed(**changes) -> dict:
    card = copy.deepcopy(CARD)
    card.update(changes)
    return card


def test_a_card_that_matches_its_variables_passes(tmp_path: Path) -> None:
    report, results = judged(project_with(tmp_path))
    assert not report.findings, report.render(tmp_path)
    assert results.models["adjusted"].kind == "logistic regression"


# ------------------------------------------------------------------- the outcome and the fit


@pytest.mark.parametrize("kind", ["continuous", "count", "categorical"])
def test_a_logistic_model_of_an_outcome_that_is_not_binary_fails(tmp_path: Path, kind) -> None:
    variables = copy.deepcopy(VARIABLES)
    variables["y"] = {"kind": kind, "label": "the outcome"}
    report, _ = judged(project_with(tmp_path, variables=variables))
    assert "model-outcome-kind" in {f.code for f in report.failures}


def test_a_linear_model_of_a_binary_outcome_fails(tmp_path: Path) -> None:
    card = changed(engine={"language": "R", "package": "stats", "class": "lm"})
    card.pop("events"), card.pop("events_by_level")
    report, _ = judged(project_with(tmp_path, card))
    found = [f for f in report.failures if f.code == "model-outcome-kind"]
    assert found and "linear regression" in found[0].message, report.render(tmp_path)


def test_a_fit_no_entry_describes_is_a_warning_and_the_rest_is_still_read(tmp_path: Path) -> None:
    card = changed(engine={"language": "Python", "class": "QuantReg"})
    variables = copy.deepcopy(VARIABLES)
    del variables["x"]
    report, _ = judged(project_with(tmp_path, card, variables))
    assert "model-engine-unknown" in {f.code for f in report.warnings}
    assert "model-variable-undeclared" in {f.code for f in report.failures}


def test_a_variable_the_model_reads_and_nobody_declared_fails(tmp_path: Path) -> None:
    variables = copy.deepcopy(VARIABLES)
    del variables["g"]
    report, _ = judged(project_with(tmp_path, variables=variables))
    found = [f for f in report.failures if f.code == "model-variable-undeclared"]
    assert [f.message for f in found] == [
        "model 'adjusted': 'g' is read by the model and never declared"
    ]


# --------------------------------------------------------- how each variable entered the model


def _entered_g(**record) -> dict:
    card = copy.deepcopy(CARD)
    card["terms"][1]["entered"][0].update(record)
    return card


def test_a_categorical_variable_entered_as_a_number_fails(tmp_path: Path) -> None:
    card = _entered_g(**{"as": "numerical", "expression": "g"})
    for key in ("levels", "reference"):
        card["terms"][1]["entered"][0].pop(key)
    card.pop("events_by_level")
    report, _ = judged(project_with(tmp_path, card))
    assert "model-categories-as-number" in {f.code for f in report.failures}


def test_an_ordinal_variable_entered_as_a_number_is_a_warning(tmp_path: Path) -> None:
    variables = copy.deepcopy(VARIABLES)
    variables["x"] = {"kind": "ordinal", "label": "grade"}
    report, _ = judged(project_with(tmp_path, variables=variables))
    assert "model-ordinal-as-trend" in {f.code for f in report.warnings}
    assert report.ok


def test_a_continuous_variable_entered_as_categories_is_a_warning(tmp_path: Path) -> None:
    variables = copy.deepcopy(VARIABLES)
    variables["g"] = {"kind": "continuous", "label": "group"}
    report, _ = judged(project_with(tmp_path, variables=variables))
    assert "model-number-as-categories" in {f.code for f in report.warnings}
    assert report.ok


def test_a_reference_other_than_the_one_declared_fails(tmp_path: Path) -> None:
    report, _ = judged(project_with(tmp_path, _entered_g(reference="b")))
    found = [f for f in report.failures if f.code == "model-reference"]
    assert found and "'b' in the fit and 'a'" in found[0].message


def test_a_level_the_variable_is_not_declared_to_have_fails(tmp_path: Path) -> None:
    card = _entered_g(levels=["a", "b", "c", "d"])
    report, _ = judged(project_with(tmp_path, card))
    assert "model-level-undeclared" in {f.code for f in report.failures}


@pytest.mark.parametrize(
    ("seen", "fails"),
    [
        (["0", "1"], False),
        (["False", "True"], False),
        (["FALSE", "TRUE"], False),
        (["1", "2"], True),
        (["no", "yes"], True),
    ],
)
def test_a_binary_variable_entered_as_a_number_must_be_coded_0_and_1(
    tmp_path: Path, seen: list[str], fails: bool
) -> None:
    """Or true and false, as either language writes them: R enters a logical column as a
    number and writes its values FALSE and TRUE."""
    variables = copy.deepcopy(VARIABLES)
    observed = {"distinct": 2, "missing": 0, "levels": seen}
    variables["x"] = {"kind": "binary", "label": "exposed", "observed": observed}
    report, _ = judged(project_with(tmp_path, variables=variables))
    assert ("model-binary-as-number" in {f.code for f in report.failures}) is fails


# ------------------------------------------------------- a comparison is a term of its own

#: `I(g == 'c')` as each language enters it: Python as categories False and True, R as a
#: number. Beside each, what the same record fails without the mark of a comparison.
_COMPARED = [
    (
        {"expression": "I(g == 'c')", "levels": ["False", "True"], "reference": "False"},
        "model-level-undeclared",
    ),
    ({"expression": 'I(g == "c")', "as": "numerical"}, "model-categories-as-number"),
]


def _comparing_g(record: dict, *, marked: bool) -> dict:
    card = _entered_g(**record, **({"comparison": True} if marked else {}))
    if record.get("as") == "numerical":
        for key in ("levels", "reference"):
            card["terms"][1]["entered"][0].pop(key)
    card.pop("events_by_level")
    return card


@pytest.mark.parametrize(("record", "otherwise"), _COMPARED)
def test_a_comparison_is_not_held_to_the_variable_it_reads(
    tmp_path: Path, record: dict, otherwise: str
) -> None:
    report, _ = judged(project_with(tmp_path, _comparing_g(record, marked=True)))
    assert not report.findings, report.render(tmp_path)
    report, _ = judged(project_with(tmp_path, _comparing_g(record, marked=False)))
    assert otherwise in {f.code for f in report.failures}, "the mark is what it is known by"


def test_the_variable_a_comparison_reads_must_still_be_declared(tmp_path: Path) -> None:
    variables = copy.deepcopy(VARIABLES)
    del variables["g"]
    card = _comparing_g(_COMPARED[0][0], marked=True)
    report, _ = judged(project_with(tmp_path, card, variables))
    assert [f.code for f in report.findings] == ["model-variable-undeclared"]


def test_an_outcome_that_is_a_comparison_is_not_held_to_the_variable_it_reads(
    tmp_path: Path,
) -> None:
    variables = copy.deepcopy(VARIABLES)
    variables["y"] = {"kind": "continuous", "label": "the score"}
    outcome = {"expression": "I(y > 5)", "variables": ["y"]}
    report, _ = judged(project_with(tmp_path, changed(outcome=outcome), variables))
    assert "model-outcome-kind" in {f.code for f in report.failures}
    report, _ = judged(
        project_with(tmp_path, changed(outcome={**outcome, "comparison": True}), variables)
    )
    assert not report.findings, report.render(tmp_path)


def test_a_comparison_is_printed_as_its_expression_and_lends_no_levels(tmp_path: Path) -> None:
    """Python enters it as categories False and True, which are not the levels of the
    variable it reads and are not printed as that variable's."""
    variables = copy.deepcopy(VARIABLES)
    variables["g"] = {"kind": "categorical", "label": "group"}
    _report, results = judged(
        project_with(tmp_path, _comparing_g(_COMPARED[0][0], marked=True), variables)
    )
    model = results.models["adjusted"]
    assert table_rows(model, results.variables)[2] == ["group", "categorical", "I(g == 'c')", "-"]
    assert "group (I(g == 'c'))" in describe(model, results.variables)


# ------------------------------------------------------------------------- the health of a fit


def test_a_fit_that_did_not_converge_fails(tmp_path: Path) -> None:
    report, _ = judged(project_with(tmp_path, changed(converged=False)))
    assert "model-not-converged" in {f.code for f in report.failures}


def test_a_level_with_no_events_fails(tmp_path: Path) -> None:
    card = changed(events_by_level={"g": {"a": 150, "b": 150, "c": 0}})
    report, _ = judged(project_with(tmp_path, card))
    found = [f for f in report.failures if f.code == "model-empty-level"]
    assert found and "'c' of 'g'" in found[0].message


@pytest.mark.parametrize(("events", "warned"), [(29, True), (30, False), (971, True)])
def test_few_events_for_each_coefficient_is_a_warning(tmp_path: Path, events, warned) -> None:
    """Ten for each of three coefficients: 29 events is short of it, and so are 971 events
    out of 1000, where the non-events are 29."""
    card = changed(events=events)
    card.pop("events_by_level")
    report, _ = judged(project_with(tmp_path, card))
    assert ("model-few-events" in {f.code for f in report.warnings}) is warned


# ---------------------------------------------------------------- grouped data: events of trials

#: The card of the same model fitted to a table of four rows, 300 events in 1000 trials.
_GROUPED = {
    "outcome": {"expression": "s + f", "variables": ["f", "s"]},
    "n_input": 4, "n_used": 4, "events": 300, "trials": 1000,
}  # fmt: skip


def _grouped_variables(kind: str = "count") -> dict:
    variables = copy.deepcopy(VARIABLES)
    del variables["y"]
    variables["s"] = {"kind": kind, "label": "cases"}
    variables["f"] = {"kind": "count", "label": "non-cases"}
    return variables


@pytest.mark.parametrize("kind", ["count", "continuous"])
def test_a_grouped_card_passes_with_its_columns_declared_counts(tmp_path: Path, kind: str) -> None:
    """Or continuous, for the proportion R fits with the trials as weights. The events for
    each coefficient are counted among the trials: four rows are not four observations."""
    report, results = judged(project_with(tmp_path, changed(**_GROUPED), _grouped_variables(kind)))
    assert not report.findings, report.render(tmp_path)
    model = results.models["adjusted"]
    assert describe(model, results.variables).endswith("; 4 of 4 rows, 300 events in 1000 trials.")


@pytest.mark.parametrize("kind", ["binary", "categorical", "ordinal"])
def test_a_column_of_a_grouped_outcome_declared_anything_but_a_number_fails(
    tmp_path: Path, kind: str
) -> None:
    report, _ = judged(project_with(tmp_path, changed(**_GROUPED), _grouped_variables(kind)))
    found = [f for f in report.failures if f.code == "model-outcome-kind"]
    assert [f.message for f in found] == [
        "model 'adjusted': a logistic regression of grouped data, where 'cases' holds the "
        f"events or the trials of each row; it is declared {kind}"
    ]


@pytest.mark.parametrize(("events", "warned"), [(29, True), (30, False), (970, False), (971, True)])
def test_few_events_of_grouped_data_are_counted_among_the_trials(
    tmp_path: Path, events: int, warned: bool
) -> None:
    card = changed(**{**_GROUPED, "events": events})
    card.pop("events_by_level")
    report, _ = judged(project_with(tmp_path, card, _grouped_variables()))
    assert ("model-few-events" in {f.code for f in report.warnings}) is warned


def test_the_trials_of_grouped_data_can_be_bound_and_others_have_none(tmp_path: Path) -> None:
    project_with(tmp_path, changed(**_GROUPED), _grouped_variables())
    namespace, *_ = load_namespace(load_project(tmp_path)[0])
    assert namespace["results.model.adjusted.trials"].display == "1000"
    assert namespace["results.model.adjusted.events"].display == "300"
    project_with(tmp_path)
    namespace, *_ = load_namespace(load_project(tmp_path)[0])
    assert "results.model.adjusted.trials" not in namespace


def test_rows_dropped_and_never_stated_fail_and_stated_pass(tmp_path: Path) -> None:
    card = changed(n_used=980, n_dropped=20)
    report, _ = judged(project_with(tmp_path, card))
    assert "model-rows-dropped" in {f.code for f in report.failures}

    stated = METHODS + "\n{{results.model.adjusted.n_dropped}} reports lacked a value.\n"
    report, _ = judged(project_with(tmp_path, card, text=stated))
    assert "model-rows-dropped" not in codes(report)


# ------------------------------------------------------------- what the data were found to hold


def test_a_level_in_the_data_that_the_variable_does_not_declare_fails(tmp_path: Path) -> None:
    variables = copy.deepcopy(VARIABLES)
    variables["g"]["observed"] = {"distinct": 4, "missing": 0, "levels": ["a", "b", "c", "z"]}
    report, _ = judged(project_with(tmp_path, variables=variables))
    found = [f for f in report.failures if f.code == "variable-level-undeclared"]
    assert found and "'z'" in found[0].message


def test_a_binary_variable_with_three_values_in_the_data_fails(tmp_path: Path) -> None:
    variables = copy.deepcopy(VARIABLES)
    variables["y"]["observed"] = {"distinct": 3, "missing": 0, "levels": ["0", "1", "9"]}
    report, _ = judged(project_with(tmp_path, variables=variables))
    assert {"variable-not-binary", "variable-level-undeclared"} <= {
        f.code for f in report.failures
    }


# --------------------------------------------------------------------- the model the Methods name


def test_a_model_the_methods_name_and_the_analysis_did_not_fit_is_a_warning(tmp_path) -> None:
    text = METHODS + "\nA Poisson regression was considered.\n"
    report, _ = judged(project_with(tmp_path, text=text))
    found = [f for f in report.warnings if f.code == "model-kind-unfitted"]
    assert [(f.line, f.col) for f in found] == [(7, 3)]


def test_the_kind_of_the_model_fitted_typed_in_the_methods_fails(tmp_path: Path) -> None:
    """Typed, it is the copy that stays behind when the model is changed, as a typed
    threshold is; bound, it follows the fit."""
    text = METHODS + "\nThe logistic-regression model was the primary analysis.\n"
    report, _ = judged(project_with(tmp_path, text=text))
    found = [f for f in report.failures if f.code == "typed-model-kind"]
    assert [(f.line, f.col) for f in found] == [(7, 5)], report.render(tmp_path)
    assert "{{results.model.adjusted.kind}}" in found[0].hint
    assert not judged(project_with(tmp_path))[0].findings


@pytest.mark.parametrize(
    "heading",
    [
        "### Logistic regression",
        "## Logistic regression models ##",
        "Logistic regression\n-------------------",
    ],
)
def test_a_model_named_in_a_heading_is_not_read(tmp_path: Path, heading: str) -> None:
    """A heading of the Methods names the analysis it heads; the running text is where a
    typed copy of the fitted kind is read, and the same words under the heading fail."""
    text = f"# Methods\n\n{heading}\n\nWe fitted a {{{{results.model.adjusted.kind}}}}.\n"
    text += "\n{{table.model_adjusted}}\n"
    report, _ = judged(project_with(tmp_path, text=text))
    assert not report.findings, report.render(tmp_path)
    text = text.replace("{{results.model.adjusted.kind}}", "logistic regression")
    report, _ = judged(project_with(tmp_path, text=text))
    found = [(f.code, f.line) for f in report.findings]
    assert found == [("typed-model-kind", 5 + heading.count("\n"))], report.render(tmp_path)


@pytest.mark.parametrize("heading", ["## Poisson regression", "Poisson regression\n------"])
def test_a_model_not_fitted_named_in_a_heading_is_not_read(tmp_path: Path, heading: str) -> None:
    text = METHODS.replace("# Methods\n", f"# Methods\n\n{heading}\n")
    report, _ = judged(project_with(tmp_path, text=text))
    assert not report.findings, report.render(tmp_path)
    report, _ = judged(project_with(tmp_path, text=text + "\nPoisson regression was not used.\n"))
    assert [f.code for f in report.findings] == ["model-kind-unfitted"]


def test_a_line_shaped_like_a_heading_that_prints_as_text_is_read(tmp_path: Path) -> None:
    """With no blank line above it, `## logistic regression` is a line of the paragraph to
    pandoc, and so text."""
    text = METHODS + "\nWe fitted\n## logistic regression.\n"
    report, _ = judged(project_with(tmp_path, text=text))
    assert [f.code for f in report.findings] == ["typed-model-kind"], report.render(tmp_path)


#: The words `data/models.yaml` lists as making the name after them another model's. Written
#: out, so that a word taken off the list fails here.
_OTHER_MODEL_WORDS = {
    "conditional", "exact", "multinomial", "polytomous", "ordinal", "ordered", "cumulative",
    "proportional-odds", "mixed", "mixed-effects", "random-effects", "multilevel",
    "hierarchical", "penalised", "penalized", "regularised", "regularized", "lasso", "ridge",
    "elastic-net", "Firth", "Bayesian", "zero-inflated", "hurdle", "truncated", "generalised",
    "generalized",
}  # fmt: skip


def _named(sentence: str) -> list[str]:
    from manuscript_guard.gates.models import named_in_methods

    return [kind for _start, _end, kind in named_in_methods(f"# Methods\n\n{sentence}\n")]


def test_the_words_that_make_another_model_are_the_listed_ones() -> None:
    from manuscript_guard.contracts.models import engines, other_model_words

    assert set(other_model_words()) == _OTHER_MODEL_WORDS
    assert len(other_model_words()) == len(_OTHER_MODEL_WORDS), "a word is listed once"
    # No name of a model opens with one, or the longer name could never be read as itself.
    opening = {name.split()[0].casefold() for entry in engines() for name in entry.synonyms}
    assert not opening & {word.casefold() for word in _OTHER_MODEL_WORDS}


@pytest.mark.parametrize("word", sorted(_OTHER_MODEL_WORDS))
@pytest.mark.parametrize("name", ["logistic regression", "Poisson models"])
def test_a_name_after_a_word_that_makes_it_another_model_is_not_read(word: str, name: str) -> None:
    assert _named(f"We fitted a {word} {name} to the matched sets.") == []
    assert _named(f"{word.upper()}\n{name} was used.") == [], "any case, and a line break"
    assert _named(f"We fitted a {word.replace('-', ' ')} {name}.") == [], "a space for the hyphen"


@pytest.mark.parametrize(
    ("sentence", "kinds"),
    [
        # Words that leave the model the fit it is: the name is read, and fails or warns.
        ("A multivariable logistic regression was fitted.", ["logistic regression"]),
        ("A multivariate logistic regression was fitted.", ["logistic regression"]),
        ("Univariable logistic regression came first.", ["logistic regression"]),
        ("The adjusted logistic regression is in Table 2.", ["logistic regression"]),
        ("A crude logistic model was fitted.", ["logistic regression"]),
        ("A weighted logistic regression was fitted.", ["logistic regression"]),
        ("A stratified logistic regression was fitted.", ["logistic regression"]),
        ("Modified Poisson regression gave the risk ratios.", ["Poisson regression"]),
        ("A robust Poisson regression gave the risk ratios.", ["Poisson regression"]),
        # A listed word that does not stand directly before the name.
        ("The analysis was unconditional logistic regression.", ["logistic regression"]),
        ("The sets were conditional. Logistic regression was used.", ["logistic regression"]),
        ("It was conditional, and logistic regression was used.", ["logistic regression"]),
        ("The sets were conditional\n\nLogistic regression was used.", ["logistic regression"]),
        ("A mixed `lme4` logistic regression was fitted.", ["logistic regression"]),
        # A longer name on the list of names is still itself, and still another after a word.
        ("A negative binomial regression was fitted.", ["negative binomial regression"]),
        ("A quasi-Poisson regression was fitted.", ["quasi-Poisson regression"]),
        ("A zero-inflated negative binomial model was fitted.", []),
        ("Multilevel mixed-effects logistic regression was fitted.", []),
        ("A conditional-logistic regression was fitted.", []),
    ],
)
def test_any_other_word_before_a_name_leaves_it_read(sentence: str, kinds: list[str]) -> None:
    assert _named(sentence) == kinds


def test_another_model_named_in_the_methods_is_neither_typed_nor_unfitted(tmp_path: Path) -> None:
    """With a logistic model fitted, "conditional logistic regression" is not its kind typed,
    and "zero-inflated Poisson model" is not a Poisson regression the analysis did not fit.
    "Multivariable logistic regression" is the fitted kind, typed."""
    text = METHODS + (
        "\nA conditional logistic regression was fitted to the matched sets, and a\n"
        "zero-inflated Poisson model to the counts.\n"
    )
    report, _ = judged(project_with(tmp_path, text=text))
    assert not report.findings, report.render(tmp_path)
    text = METHODS + "\nA multivariable logistic regression was fitted.\n"
    report, _ = judged(project_with(tmp_path, text=text))
    assert [f.code for f in report.findings] == ["typed-model-kind"]


# ------------------------------------------------------------------- what is made from the card


def test_the_name_the_sentence_and_the_table_are_made_from_the_card(tmp_path: Path) -> None:
    project_with(tmp_path)
    project, _ = load_project(tmp_path)
    namespace, results, _literature, _loaded = load_namespace(project)
    model = results.models["adjusted"]
    assert namespace["results.model.adjusted.kind"].display == "logistic regression"
    assert namespace["results.model.adjusted.name"].display == "Adjusted model"
    assert namespace["results.model.adjusted.n_dropped"].display == "0"
    assert describe(model, results.variables) == (
        "Logistic regression of the outcome on dose (a number), group (categories, "
        "reference a); 1000 of 1000 rows, 300 events."
    )
    assert table_rows(model, results.variables) == [
        ["the outcome", "binary", "outcome", "0, 1"],
        ["dose", "continuous", "a number", "-"],
        ["group", "categorical", "categories, reference a", "a (reference), b, c"],
    ]
    table = results.tables["model_adjusted"]
    assert table.generated and table.caption.startswith("Adjusted model. Logistic regression")


def test_a_model_table_nobody_places_is_reported_like_any_table(tmp_path: Path) -> None:
    from manuscript_guard.gates import check_numbers

    project_with(tmp_path, text="# Methods\n\nA {{results.model.adjusted.kind}}.\n")
    project, _ = load_project(tmp_path)
    namespace, results, literature, _loaded = load_namespace(project)
    report = check_numbers(project, namespace, results, literature)
    assert "unplaced-table" in {f.code for f in report.findings}
    assert "hand-authored-table" not in {f.code for f in report.findings}


def test_a_value_emitted_under_a_models_key_is_refused(tmp_path: Path) -> None:
    project_with(tmp_path)
    fragment = tmp_path / "results" / "fit.json"
    em = Emitter(tmp_path / "analysis" / "fit.py", root=tmp_path)
    em.value("model.adjusted.kind", "probit regression", label=True)
    em.write(tmp_path / "results" / "other.json")
    project, _ = load_project(tmp_path)
    _namespace, _results, _literature, loaded = load_namespace(project)
    assert "duplicate-key" in {f.code for f in loaded.findings}, fragment


@pytest.mark.parametrize(
    ("engine", "kind"),
    [
        ({"language": "Python", "class": "Logit", "family": "Binomial", "link": "Logit"},
         "logistic regression"),
        ({"language": "R", "class": "glm", "family": "poisson", "link": "log"},
         "Poisson regression"),
        ({"language": "R", "class": "lm"}, "linear regression"),
        ({"language": "Python", "class": "OLS"}, "linear regression"),
        ({"language": "Python", "class": "GLM", "family": "Gamma", "link": "Log"},
         "gamma regression"),
        ({"language": "R", "class": "glm", "family": "binomial", "link": "cauchit"}, None),
    ],
)  # fmt: skip
def test_a_fit_is_named_by_the_list_and_by_nothing_else(engine: dict, kind: str | None) -> None:
    found = engine_of(engine)
    assert (found.kind if found else None) == kind


# --------------------------------------------------------------------------- a card from a fit


def _fitted(tmp_path: Path, formula: str, *, reference: str = "a") -> dict:
    pd = pytest.importorskip("pandas")
    sm = pytest.importorskip("statsmodels.api")
    smf = pytest.importorskip("statsmodels.formula.api")
    import random

    draw = random.Random(1)
    rows = [
        {"y": int(draw.random() < 0.3), "x": float(i % 10), "g": "abc"[i % 3]} for i in range(300)
    ]
    data = pd.DataFrame(rows)
    data.loc[5, "x"] = float("nan")
    fit = smf.glm(formula, data, family=sm.families.Binomial()).fit()
    em = Emitter(tmp_path / "fit.py", root=tmp_path)
    em.variable("g", "categorical", label="group", levels=["a", "b", "c"], reference=reference,
                values=data["g"])  # fmt: skip
    em.model("adjusted", fit, name="Adjusted model")
    return em.document()


def test_a_card_is_read_from_a_statsmodels_fit(tmp_path: Path) -> None:
    (tmp_path / "fit.py").write_text("#\n", encoding="utf-8")
    document = _fitted(tmp_path, "y ~ x + C(g, Treatment('b'))")
    card = document["models"]["adjusted"]
    assert card["engine"]["class"] == "GLM" and card["engine"]["link"] == "Logit"
    assert (card["n_input"], card["n_used"], card["n_dropped"]) == (300, 299, 1)
    entered = {r["variables"][0]: r for t in card["terms"] for r in t["entered"]}
    assert entered["x"]["as"] == "numerical"
    assert entered["g"]["as"] == "categorical" and entered["g"]["reference"] == "b"
    assert entered["g"]["levels"] == ["a", "b", "c"]
    assert sum(card["events_by_level"]["g"].values()) == card["events"]
    assert card["parameters"] == 3
    assert document["variables"]["g"]["observed"] == {
        "distinct": 3, "missing": 0, "levels": ["a", "b", "c"],
    }  # fmt: skip
    json.dumps(document)


def _binomial(formula: str, data, **weights) -> dict:
    """The card of a binomial fit of `formula` on `data`, with numpy in reach of the formula."""
    np = pytest.importorskip("numpy")  # noqa: F841 - a formula below calls it by this name
    sm = pytest.importorskip("statsmodels.api")
    smf = pytest.importorskip("statsmodels.formula.api")
    import warnings

    from manuscript_guard.emit import read_statsmodels

    with warnings.catch_warnings():
        # A level with no events does not converge quietly, and that is what is fitted here.
        warnings.simplefilter("ignore")
        fit = smf.glm(formula, data, family=sm.families.Binomial(), **weights).fit()
    return read_statsmodels(fit)


def _coded(levels: list, *, events_at: dict | None = None, rows: int = 60):
    """A frame of `rows` rows for each level of `g`, with an outcome that occurs in a third
    of each, or in as many rows as `events_at` says for the level so written."""
    pd = pytest.importorskip("pandas")
    g, y = [], []
    for level in levels:
        events = (events_at or {}).get(str(level), rows // 3)
        g += [level] * rows
        y += [1] * events + [0] * (rows - events)
    return pd.DataFrame({"y": y, "g": pd.Series(g, dtype=object if _mixed(levels) else None)})


def _mixed(levels: list) -> bool:
    return len({type(level) for level in levels}) > 1


def test_a_category_of_float_codes_has_its_reference_and_its_events_read(tmp_path: Path) -> None:
    """An integer code with a missing value is a float column. patsy names its columns
    "[T.2.0]" where the levels are written "2": read apart, no level was left over for the
    reference, nothing was recorded, and a fit on another reference than the declared one
    passed."""
    data = _coded([1, 2, 3], events_at={"2": 0})
    whole = _binomial("y ~ C(g, Treatment(3))", data)
    data["g"] = data["g"].astype(float)
    data.loc[0, "g"] = float("nan")
    card = _binomial("y ~ C(g, Treatment(3))", data)
    assert card["terms"][0]["entered"] == [
        {
            "expression": "C(g, Treatment(3))", "variables": ["g"], "as": "categorical",
            "levels": ["1", "2", "3"], "reference": "3",
        }
    ]  # fmt: skip
    assert card["terms"] == whole["terms"], "as the same code in an integer column"
    assert card["events_by_level"] == {"g": {"1": 19, "2": 0, "3": 20}}
    assert whole["events_by_level"] == {"g": {"1": 20, "2": 0, "3": 20}}

    variables = {
        "y": VARIABLES["y"],
        "g": {"kind": "ordinal", "label": "grade", "levels": ["1", "2", "3"], "reference": "1"},
    }
    text = METHODS + "\n{{results.model.adjusted.n_dropped}} row lacked a grade.\n"
    report, _ = judged(project_with(tmp_path, {**card, "name": "Adjusted model"}, variables, text))
    failed = [f.message for f in report.failures if f.code != "model-not-converged"]
    assert sorted(failed) == [
        "model 'adjusted': 'grade' has reference '3' in the fit and '1' in its declaration",
        "model 'adjusted': no events at level '2' of 'g': its coefficient cannot be estimated "
        "(separation)",
    ]


@pytest.mark.parametrize(
    ("levels", "coding", "reference"),
    [
        ([1, 2, 3], "Treatment(2)", "2"),
        ([1, 2, 3], "", "1"),
        (["a", "b", "c"], "Treatment('b')", "b"),
        ([False, True], "", "False"),
        ([False, True], "Treatment(True)", "True"),
        (["a]b", "v1.5", "[T.c]"], "Treatment('v1.5')", "v1.5"),
        ([0.5, 1.5, 2.5], "Treatment(1.5)", "1.5"),
        ([1.0, 2.0, 3.0], "", "1"),
        # Not a treatment coding: no level is the reference, and none is recorded.
        (["a", "b", "c"], "Sum", None),
        # 1 the number beside "1" the text are two levels written alike: the level left over
        # could be either, so no reference is recorded and no events by level.
        ([1, "1", 2], "", None),
        ([1.0, "1", 2.0], "Treatment('1')", None),
    ],
)
def test_the_reference_is_the_level_no_column_stands_for(
    levels: list, coding: str, reference: str | None
) -> None:
    from manuscript_guard.emit import _level

    data = _coded(levels)
    card = _binomial(f"y ~ C(g, {coding})" if coding else "y ~ C(g)", data)
    record = card["terms"][0]["entered"][0]
    assert sorted(record["levels"]) == sorted(_level(level) for level in levels)
    assert record.get("reference") == reference
    if reference is None:
        assert "events_by_level" not in card
    else:
        assert card["events_by_level"] == {"g": dict.fromkeys(record["levels"], 20)}


@pytest.mark.parametrize(
    ("code", "compares"),
    [
        ("stage == 'IV'", True),
        ("I(stage == 'IV')", True),
        ("stage != 'IV'", True),
        ("age < 65", True),
        ("I(age <= 65)", True),
        ("age > 65", True),
        ("I(age >= 65)", True),
        ("stage in ('III', 'IV')", True),
        ("I(stage not in ('III', 'IV'))", True),
        ("I( ~(stage == 'IV'))", True),
        ("~I(stage == 'IV')", True),
        ("not (stage == 'IV')", True),
        ("I((age > 65))", True),
        ("stage", False),
        ("I(stage)", False),
        ("C(stage)", False),
        ("C(stage == 'IV')", False),
        ("np.log(age)", False),
        ("np.where(age > 65, 1, 0)", False),
        ("(age > 65) & (stage == 'IV')", False),
        ("(age > 65) + 0", False),
        ("I(age > 65, stage)", False),
        ("I(x=age > 65)", False),
        ("np.I(age > 65)", False),
        ("age is None", False),
        ("-(age > 65)", False),
        ("Q('age group')", False),
        ("age >", False),
    ],
)
def test_a_comparison_is_known_at_the_top_of_an_expression(code: str, compares: bool) -> None:
    from manuscript_guard.emit import _is_comparison

    assert _is_comparison(code) is compares


def _staged():
    pd = pytest.importorskip("pandas")
    rows = [
        {"y": int(i % 3 == 0), "stage": ("I", "II", "III", "IV")[i % 4], "code": 1 + i % 4,
         "score": float(i % 11)}
        for i in range(240)
    ]  # fmt: skip
    return pd.DataFrame(rows)


_STAGED = {
    "y": {"kind": "binary", "label": "the outcome", "levels": ["0", "1"]},
    "stage": {
        "kind": "ordinal", "label": "stage", "levels": ["I", "II", "III", "IV"], "reference": "I",
    },
    "code": {"kind": "categorical", "label": "site", "levels": ["1", "2", "3", "4"]},
    "score": {"kind": "continuous", "label": "score"},
}  # fmt: skip


@pytest.mark.parametrize(
    ("formula", "comparisons", "codes"),
    [
        # A variable dichotomised in the formula is a binary term of its own.
        ("y ~ I(stage == 'IV')", 1, set()),
        ("y ~ stage == 'IV'", 1, set()),
        ("y ~ I(~(stage == 'IV')) + I(score > 5)", 2, set()),
        # Everything else is held to the variable it reads, as before.
        ("y ~ C(stage)", 0, set()),
        ("y ~ C(stage, Treatment('II'))", 0, {"model-reference"}),
        ("y ~ np.log(code)", 0, {"model-categories-as-number"}),
        ("y ~ code", 0, {"model-categories-as-number"}),
        ("y ~ C(stage == 'IV')", 0, {"model-level-undeclared", "model-reference"}),
        ("y ~ np.where(stage == 'IV', 1, 0)", 0, {"model-ordinal-as-trend"}),
    ],
)
def test_a_variable_dichotomised_in_the_formula_is_a_term_of_its_own(
    tmp_path: Path, formula: str, comparisons: int, codes: set[str]
) -> None:
    card = _binomial(formula, _staged())
    entered = [record for term in card["terms"] for record in term["entered"]]
    assert sum(record.get("comparison", False) for record in entered) == comparisons
    assert all(record["variables"] for record in entered), "each still reads its variable"
    report, _ = judged(project_with(tmp_path, {**card, "name": "Adjusted model"}, _STAGED))
    assert {f.code for f in report.findings} == codes, report.render(tmp_path)


def test_what_is_missing_is_not_a_level() -> None:
    """pandas writes a missing value of a nullable column as NA, of a date as NaT, and
    numpy has floats that are not Python's. None is a level, and each is counted missing."""
    from manuscript_guard.emit import _observed

    pd = pytest.importorskip("pandas")
    np = pytest.importorskip("numpy")
    binary = {"distinct": 2, "missing": 1, "levels": ["0", "1"]}
    assert _observed(pd.array([1, None, 0], dtype="Int64"), "binary") == binary
    assert _observed(pd.array([True, None, False], dtype="boolean"), "binary") == {
        **binary, "levels": ["False", "True"],
    }  # fmt: skip
    assert _observed(pd.array(["a", None, "b"], dtype="string"), "categorical") == {
        **binary, "levels": ["a", "b"],
    }  # fmt: skip
    dates = _observed(pd.Series(pd.to_datetime(["2020-01-01", None, "2021-01-01"])), "continuous")
    assert (dates["distinct"], dates["missing"]) == (2, 1)
    narrow = _observed(np.array([1.0, float("nan"), 0.0], dtype="float32"), "continuous")
    assert (narrow["distinct"], narrow["missing"]) == (2, 1)
    assert _observed([1, None, float("nan"), 0, np.datetime64("NaT")], "binary") == {
        **binary, "missing": 3,
    }  # fmt: skip
    assert _observed(iter([1, None, 0]), "binary") == binary, "read once, in one pass"
    cells = _observed([np.array([1, 2]), "a"], "categorical")
    assert cells["missing"] == 0, "an array in a cell is a value, whatever it is unequal to"


#: A table of six groups, 85 events in 600 trials, with none at level c.
_TABLE = {
    "s": [10, 20, 30, 25, 0, 0], "f": [90, 80, 70, 75, 100, 100],
    "x": [0, 1, 0, 1, 0, 1], "g": ["a", "a", "b", "b", "c", "c"],
}  # fmt: skip


def test_grouped_binomial_data_are_read_as_events_among_trials(tmp_path: Path) -> None:
    """`s + f ~ x` is fitted to the proportion of each row, and the sum of the proportions
    was recorded as the events: 1, of a table that holds 85."""
    pd = pytest.importorskip("pandas")
    card = _binomial("s + f ~ x + C(g)", pd.DataFrame(_TABLE))
    assert card["outcome"] == {"expression": "s + f", "variables": ["f", "s"]}
    assert (card["events"], card["trials"], card["n_used"]) == (85, 600, 6)
    assert card["events_by_level"] == {"g": {"a": 30, "b": 55, "c": 0}}

    variables = {
        "s": {"kind": "count", "label": "cases"},
        "f": {"kind": "count", "label": "non-cases"},
        "x": {"kind": "binary", "label": "exposure", "levels": ["0", "1"]},
        "g": {"kind": "categorical", "label": "group", "levels": ["a", "b", "c"]},
    }
    report, _ = judged(project_with(tmp_path, {**card, "name": "Adjusted model"}, variables))
    found = {f.code for f in report.findings} - {"model-not-converged"}
    assert found == {"model-empty-level"}, report.render(tmp_path)


def test_a_proportion_whose_trials_are_weights_has_no_events_recorded() -> None:
    """statsmodels fits a proportion with the trials as `var_weights`, which may be any
    other weight as well: the events are not read from them, and none are recorded."""
    pd = pytest.importorskip("pandas")
    table = pd.DataFrame(_TABLE)
    table["n"] = table["s"] + table["f"]
    table["p"] = table["s"] / table["n"]
    card = _binomial("p ~ x + C(g)", table, var_weights=table["n"])
    assert card["outcome"] == {"expression": "p", "variables": ["p"]}
    assert not {"events", "trials", "events_by_level"} & set(card)


def test_an_outcome_of_two_levels_is_one_variable_and_no_table_of_counts() -> None:
    """A text or a comparison as the outcome reaches statsmodels as a column for each level,
    and it takes the first for the event. That is one observation a row, not grouped data;
    the card names the variable the outcome reads, and counts what the fit modelled."""
    data = _staged()
    data["answer"] = ["no" if y == 0 else "yes" for y in data["y"]]
    card = _binomial("answer ~ score", data)
    assert card["outcome"] == {"expression": "answer", "variables": ["answer"]}
    assert "trials" not in card and card["events"] == int((data["y"] == 0).sum())
    card = _binomial("I(score > 5) ~ C(stage)", data)
    assert card["outcome"] == {
        "expression": "I(score > 5)", "variables": ["score"], "comparison": True,
    }  # fmt: skip
    assert "trials" not in card and card["events"] == int((data["score"] <= 5).sum())
    assert sum(card["events_by_level"]["stage"].values()) == card["events"]


def test_a_fit_made_without_a_formula_is_refused(tmp_path: Path) -> None:
    sm = pytest.importorskip("statsmodels.api")
    (tmp_path / "fit.py").write_text("#\n", encoding="utf-8")
    fit = sm.OLS([1.0, 2.0, 3.0], [[1.0], [2.0], [3.5]]).fit()
    with pytest.raises(ValueError, match="formula API"):
        Emitter(tmp_path / "fit.py", root=tmp_path).model("plain", fit, name="Plain")


@pytest.mark.parametrize(
    ("call", "refusal"),
    [
        (lambda em: em.variable("g", "nominal", label="group"), "kind is one of"),
        (lambda em: em.variable("g", "categorical", label="g", levels=["a"], reference="b"),
         "is not a level"),
        (lambda em: em.model("Bad-Key", object(), name="M"), "lowercase letters"),
    ],
)  # fmt: skip
def test_what_the_emitter_refuses(tmp_path: Path, call, refusal: str) -> None:
    (tmp_path / "fit.py").write_text("#\n", encoding="utf-8")
    with pytest.raises(ValueError, match=refusal):
        call(Emitter(tmp_path / "fit.py", root=tmp_path))


def test_models_prints_the_card_a_co_author_reads(tmp_path: Path, capsys) -> None:
    from manuscript_guard.cli import main

    project_with(tmp_path, _entered_g(reference="b"))
    assert main(["models", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Adjusted model  (model.adjusted, fit.json)" in out
    assert "fitted:      logistic regression" in out
    assert "author says: The primary analysis." in out
    assert "categorical  categories, reference b" in out
    assert "[FAIL] 'group' has reference 'b' in the fit and 'a' in its declaration" in out


def test_models_prints_every_finding_its_exit_code_counts(tmp_path: Path, capsys) -> None:
    """A level the data hold and a model's kind typed in the Methods are findings of no one
    card. They were counted in the exit code and printed nowhere."""
    from manuscript_guard.cli import main

    variables = copy.deepcopy(VARIABLES)
    variables["g"]["observed"] = {"distinct": 4, "missing": 0, "levels": ["a", "b", "c", "z"]}
    text = METHODS + "\nThe logistic regression was the primary analysis.\n"
    project_with(tmp_path, variables=variables, text=text)
    assert main(["models", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL] variable 'g' takes 'z' in the data, which its declared levels do not" in out
    assert "[FAIL] main.md:7: the Methods type 'logistic regression', the kind of a model" in out
