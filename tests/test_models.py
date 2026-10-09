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


@pytest.mark.parametrize(("seen", "fails"), [(["0", "1"], False), (["1", "2"], True)])
def test_a_binary_variable_entered_as_a_number_must_be_coded_0_and_1(
    tmp_path: Path, seen: list[str], fails: bool
) -> None:
    variables = copy.deepcopy(VARIABLES)
    observed = {"distinct": 2, "missing": 0, "levels": seen}
    variables["x"] = {"kind": "binary", "label": "exposed", "observed": observed}
    report, _ = judged(project_with(tmp_path, variables=variables))
    assert ("model-binary-as-number" in {f.code for f in report.failures}) is fails


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
