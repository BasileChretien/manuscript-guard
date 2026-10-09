"""The models an analysis fitted and the variables it declared, as the results record them.

The emitters write what a fit says of itself and nothing else. What a model is called, the
sentence that describes it and the table that prints it are derived here, from those facts
and from `data/models.yaml`, once for both languages: a name typed by the author is the
thing G15 compares with the fit, not the thing it trusts.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import yaml

from manuscript_guard.contracts.values import RESULTS, Value

#: What an outcome or a term is, when the analysis did not declare it.
UNDECLARED = "undeclared"


@dataclass(frozen=True)
class Engine:
    """One entry of `data/models.yaml`: a kind of model, and the fits that are one."""

    kind: str
    synonyms: tuple[str, ...]
    outcome: tuple[str, ...]
    fits: tuple[dict, ...]

    def matches(self, engine: dict) -> bool:
        return any(all(engine.get(k) == v for k, v in fit.items()) for fit in self.fits)


@functools.cache
def engines() -> tuple[Engine, ...]:
    text = files("manuscript_guard.data").joinpath("models.yaml").read_text(encoding="utf-8")
    return tuple(
        Engine(
            kind=entry["kind"],
            synonyms=tuple(entry["synonyms"]),
            outcome=tuple(entry["outcome"]),
            fits=tuple(entry["fits"]),
        )
        for entry in yaml.safe_load(text)["engines"]
    )


def engine_of(engine: dict) -> Engine | None:
    """The kind of model a fit is, or None for a fit no entry describes."""
    return next((entry for entry in engines() if entry.matches(engine)), None)


@dataclass(frozen=True)
class Variable:
    name: str
    kind: str
    label: str
    source: Path
    levels: tuple[str, ...] | None = None
    reference: str | None = None
    unit: str | None = None
    observed: dict | None = None


@dataclass(frozen=True)
class Model:
    key: str
    name: str
    engine: dict
    formula: str
    outcome: dict
    terms: tuple[dict, ...]
    parameters: int
    n_input: int
    n_used: int
    n_dropped: int
    converged: bool
    source: Path
    description: str | None = None
    events: int | None = None
    events_by_level: dict = field(default_factory=dict)

    @property
    def kind(self) -> str | None:
        found = engine_of(self.engine)
        return found.kind if found else None

    @property
    def entered(self) -> list[dict]:
        """Every variable as a term entered it, in the order the formula has them."""
        return [record for term in self.terms for record in term["entered"]]

    def variables(self) -> list[str]:
        """The variables the model reads, outcome first, each once."""
        read = [v for record in self.entered for v in record["variables"]]
        return list(dict.fromkeys([*self.outcome["variables"], *read]))


def read_variables(document: dict, path: Path) -> dict[str, Variable]:
    return {
        name: Variable(
            name=name,
            kind=spec["kind"],
            label=spec["label"],
            source=path,
            levels=tuple(spec["levels"]) if "levels" in spec else None,
            reference=spec.get("reference"),
            unit=spec.get("unit"),
            observed=spec.get("observed"),
        )
        for name, spec in (document.get("variables") or {}).items()
    }


def read_models(document: dict, path: Path) -> dict[str, Model]:
    return {
        key: Model(
            key=key,
            name=spec["name"],
            engine=dict(spec["engine"]),
            formula=spec["formula"],
            outcome=dict(spec["outcome"]),
            terms=tuple(spec["terms"]),
            parameters=spec["parameters"],
            n_input=spec["n_input"],
            n_used=spec["n_used"],
            n_dropped=spec["n_dropped"],
            converged=spec["converged"],
            source=path,
            description=spec.get("description"),
            events=spec.get("events"),
            events_by_level=dict(spec.get("events_by_level") or {}),
        )
        for key, spec in (document.get("models") or {}).items()
    }


def _label(name: str, variables: dict[str, Variable]) -> str:
    return variables[name].label if name in variables else name


def _entered_as(record: dict) -> str:
    """How a term took a variable, in words: as categories, as a number, or as an expression."""
    if record["as"] == "categorical":
        reference = record.get("reference")
        return f"categories, reference {reference}" if reference else "categories"
    if record["variables"] == [record["expression"]]:
        return "a number"
    return record["expression"]


def describe(model: Model, variables: dict[str, Variable]) -> str:
    """The sentence a reader could check the model against, made from the fit alone.

    "Logistic regression of hepatic injury on exposure (a number), age group (categories,
    reference 18-44); 4000 of 4000 rows, 400 events." It changes only when the fit does.
    """
    kind = model.kind
    if kind is None:
        engine = model.engine
        bits = ", ".join(engine[k] for k in ("family", "link") if k in engine)
        kind = f"{engine['class']} model" + (f" ({bits})" if bits else "")
    head = kind[0].upper() + kind[1:]
    outcome = " and ".join(_label(v, variables) for v in model.outcome["variables"]) or (
        model.outcome["expression"]
    )
    terms = []
    for term in model.terms:
        parts = [
            f"{' and '.join(_label(v, variables) for v in r['variables']) or r['expression']} "
            f"({_entered_as(r)})"
            for r in term["entered"]
        ]
        terms.append(" × ".join(parts))
    on = ", ".join(terms) if terms else "an intercept alone"
    tail = f"{model.n_used} of {model.n_input} rows"
    if model.events is not None:
        tail += f", {model.events} events"
    return f"{head} of {outcome} on {on}; {tail}."


def values_of(model: Model) -> dict[str, Value]:
    """What a manuscript can bind of a model: its names, and the rows it used and dropped."""

    def value(name: str, content: object, *, label: bool = False) -> tuple[str, Value]:
        key = f"model.{model.key}.{name}"
        return key, Value(
            key=key, value=content, display=str(content), origin=RESULTS, source=model.source,
            quoted=False, label=label,
        )  # fmt: skip

    out = dict(
        [
            value("name", model.name, label=True),
            value("n_used", model.n_used),
            value("n_dropped", model.n_dropped),
        ]
    )
    if model.kind is not None:
        out.update([value("kind", model.kind, label=True)])
    if model.events is not None:
        out.update([value("events", model.events)])
    return out


def table_rows(model: Model, variables: dict[str, Variable]) -> list[list[str]]:
    """One row for the outcome and one for each variable a term reads."""
    rows = []
    for name in model.variables():
        declared = variables.get(name)
        records = [r for r in model.entered if name in r["variables"]]
        if name in model.outcome["variables"] and not records:
            entered = "outcome"
        else:
            entered = "; ".join(dict.fromkeys(_entered_as(r) for r in records))
        levels = declared.levels if declared and declared.levels else None
        if levels is None:
            categorical = next((r for r in records if r["as"] == "categorical"), None)
            levels = tuple(categorical["levels"]) if categorical else None
        reference = declared.reference if declared else None
        shown = (
            ", ".join(f"{lv} (reference)" if lv == reference else lv for lv in levels)
            if levels
            else "-"
        )
        rows.append(
            [_label(name, variables), declared.kind if declared else UNDECLARED, entered, shown]
        )
    return rows
