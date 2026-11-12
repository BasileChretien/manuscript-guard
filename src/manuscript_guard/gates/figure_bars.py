"""G3 — a figure that draws bars of means and no points.

A bar graph of continuous data hides how the data are spread: many data sets, with an
outlier, two clusters or three observations, give the same bar (Weissgerber, Milic, Winham
and Garovic, PLoS Biol 2015;13:e1002128). Barzooka finds such bars in a published PDF; here
the script that draws them can be read.

So a figure's script is read for the calls in `data/figure_bars.yaml`:

- a bar the plot computes as the mean of each group (`sns.barplot`, `stat_summary(geom =
  "bar")`, `geom_bar(stat = "summary")`), with no layer in the script that draws the points
  of the data, is a warning (`figure-bars-of-means`);
- a bar drawn from values the script was given, with error bars on it (`ax.bar(x, m,
  yerr=s)`, `geom_col()` and `geom_errorbar()`) and no points, is a note
  (`figure-bars-with-errors`): the bar may be a proportion and its interval, which is right.

A bar of counts with no error bars says nothing. A reason in the figure's `<name>.guard.yaml`
under `allow_bars` stands both findings down.

This is a module of its own beside `figure_estimates` because it judges the script as a
whole: a bar is a finding only where no call anywhere in the script draws the points, where
an estimate is a finding by itself. It reads the calls as that module does, from the
script's tokens, so a call made through a function of the script's own is not seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.findings import INFO, WARN, Finding, Report
from manuscript_guard.gates.figure_estimates import NOT_GIVEN, Call, calls_in, named
from manuscript_guard.text.code import lex

GATE = "G3"
DATA = Path(__file__).parent.parent / "data" / "figure_bars.yaml"
#: The key of a figure's guard file whose reason stands the findings down.
KEY = "allow_bars"
#: The quotation marks a string's token keeps.
_QUOTES = "'\""


@dataclass(frozen=True)
class Drawing:
    """A call that draws a bar, an error bar or the points of the data, from the data file."""

    draws: str
    names: tuple[str, ...]
    what: str
    when: dict[str, tuple[str | None, ...]]
    unless: dict[str, tuple[str, ...]]
    summary: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def drawn_by(self, call: Call) -> bool:
        if not named(call.name, self.names):
            return False
        if any(value_of(call, name) not in values for name, values in self.when.items()):
            return False
        return not any(value_of(call, name) in values for name, values in self.unless.items())


@dataclass(frozen=True)
class Bar:
    """A bar in a script that is a finding: the call, what it draws, and its code."""

    call: Call
    rule: Drawing
    code: str


@lru_cache(maxsize=1)
def rules() -> tuple[tuple[str, ...], dict[str, tuple[Drawing, ...]]]:
    """The names of a mean, and the drawings of each language."""
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    drawings = {
        language: tuple(
            Drawing(
                draws=entry["draws"],
                names=tuple(entry["names"]),
                what=" ".join(str(entry["what"]).split()),
                when={key: tuple(None if v is None else str(v) for v in values)
                      for key, values in (entry.get("when") or {}).items()},
                unless={key: tuple(map(str, values))
                        for key, values in (entry.get("unless") or {}).items()},
                summary=tuple(entry.get("summary", ())),
                errors=tuple(entry.get("errors", ())),
            )
            for entry in document[language]
        )  # fmt: skip
        for language in ("python", "r")
    }
    return tuple(document["means"]), drawings


def value_of(call: Call, name: str) -> str | None:
    """The first token of the value given to `name`, without its quotation marks; None when
    the argument is not given by name."""
    value = call.arguments.get(name)
    return None if value is None else value.strip(_QUOTES)


def _shows_a_mean(call: Call, rule: Drawing, means: tuple[str, ...]) -> bool:
    given = [value_of(call, name) for name in rule.summary if name in call.arguments]
    return not given or any(value is not None and named(value, means) for value in given)


def _with_errors(call: Call, rule: Drawing) -> bool:
    return any(call.arguments.get(name) not in NOT_GIVEN for name in rule.errors)


def bars_in(text: str, language: str) -> list[Bar]:
    """Each bar in a script that is a finding: a bar of means, or a bar of given values with
    error bars on it; none where any call in the script draws the points of the data."""
    means, drawings = rules()
    drawn: list[tuple[Call, Drawing]] = []
    for call in calls_in(lex(text, language)):
        rule = next((rule for rule in drawings[language] if rule.drawn_by(call)), None)
        if rule is not None:
            drawn.append((call, rule))
    if any(rule.draws == "points" for _call, rule in drawn):
        return []
    layered = any(rule.draws == "errors" for _call, rule in drawn)
    found = []
    for call, rule in drawn:
        if rule.draws == "means" and _shows_a_mean(call, rule, means):
            found.append(Bar(call, rule, "figure-bars-of-means"))
        elif rule.draws == "given" and (layered or _with_errors(call, rule)):
            found.append(Bar(call, rule, "figure-bars-with-errors"))
    return found


def reason_in(sidecar: Path) -> str | None:
    """The reason the figure's guard file gives under `allow_bars`: a sentence, or None."""
    try:
        document = yaml.safe_load(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError):
        return None
    said = document.get(KEY) if isinstance(document, dict) else None
    if not isinstance(said, str):
        return None
    return said.strip() or None


def check_figure_bars(script: Path, text: str, language: str) -> Report:
    """A warning for each bar of means in a figure's script with no points, and a note for
    each bar of given values with error bars and no points."""
    sidecar = script.with_name(f"{script.stem}.guard.yaml")
    if reason_in(sidecar):
        return Report()
    findings = []
    lines = text.splitlines()
    for bar in bars_in(text, language):
        line = text.count("\n", 0, bar.call.start) + 1
        means = bar.code == "figure-bars-of-means"
        findings.append(
            Finding(
                gate=GATE,
                code=bar.code,
                severity=WARN if means else INFO,
                message=f"{bar.call.name}(...) {bar.rule.what}, "
                + ("and the script draws no point of the data: many data sets give the "
                   "same bar" if means else
                   "with error bars on it, and the script draws no point of the data"),
                path=script,
                line=line,
                context=lines[line - 1].strip()[:160] if line <= len(lines) else "",
                hint=("draw the points over the summary (geom_jitter, geom_beeswarm, "
                      "sns.stripplot, ax.scatter), or a box or dot plot in its place"
                      + ("" if means else "; a proportion and its interval can stay a bar")
                      + f"; or give the reason in {sidecar.name} under {KEY}"),
            )  # fmt: skip
        )
    return Report(tuple(findings))
