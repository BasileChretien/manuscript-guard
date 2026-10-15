"""G3 — a figure that computes statistics while it draws.

G3 holds a figure's numbers to the results: the labels its script draws and the text in the
rendered file. The marks are another matter. `sns.barplot` draws a bootstrap confidence
interval of the mean unless it is told not to, `stat_summary` a mean and its standard error,
`geom_smooth` a fitted line and its band. None of these passes through the results file, so
the interval drawn can differ from the one the text quotes and ignores what the analysis
accounted for. A random one changes at every render, and the figure's review is stale each
time. The same holds for what the script computes, samples or drops itself: numpy's `std`
divides by n and pandas' by n - 1, and `dropna` can leave other rows than the analysis used.

So each call in `data/figure_estimates.yaml` found in a figure's script is a warning
(`figure-estimates`), unless an argument there tells it not to estimate, an argument settles
it (a seed, a divisor), a seed set in the script settles a random one, or the figure's
`<name>.guard.yaml` gives a reason under `allow_estimates`.

The calls are read from the script's tokens (`text/code.py`): a name followed by an opening
bracket, and the names given values at the top level of its arguments. A call made through
another name, a function of the script's own that wraps one, is not seen.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.text.code import Token, lex

GATE = "G3"
DATA = Path(__file__).parent.parent / "data" / "figure_estimates.yaml"

#: The calls that seed a script's random draws, by the last part of their name, in each
#: language: given an argument, each makes what follows reproducible.
SEEDS = {"python": ("seed", "default_rng", "RandomState"), "r": ("set.seed",)}
#: What an argument holds that sets nothing: `seed=None`, `seed = NA`.
NOT_GIVEN = (None, "None", "NA", "NULL")
#: What closes each bracket.
_CLOSES = {"(": ")", "[": "]", "{": "}"}


@dataclass(frozen=True)
class Estimating:
    """A call that estimates, samples, draws at random or drops rows, from the data file."""

    names: tuple[str, ...]
    prefixes: tuple[str, ...]
    what: str
    unless: dict[str, tuple[str, ...]]
    stated: str | None
    seeded: bool
    settle: str | None = None

    def calls(self, name: str) -> bool:
        return named(name, self.names) or name.startswith(self.prefixes)


def named(name: str, names: tuple[str, ...]) -> bool:
    """Whether a call's name is one of `names`, whole ("na.omit", "set.seed") or by its last
    part ("sns.barplot" is "barplot")."""
    return name in names or name.split(".")[-1] in names


@dataclass(frozen=True)
class Call:
    """A call in a script: its name, where it stands, and the value of each argument given
    by name at its top level, as the first token of that value."""

    name: str
    start: int
    arguments: dict[str, str]
    given: bool


@dataclass(frozen=True)
class Estimate:
    call: Call
    rule: Estimating


@lru_cache(maxsize=1)
def rules() -> dict[str, tuple[Estimating, ...]]:
    document = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return {
        language: tuple(
            Estimating(
                names=tuple(entry.get("names", ())),
                prefixes=tuple(entry.get("prefix", ())),
                what=" ".join(str(entry["what"]).split()),
                unless={key: tuple(map(str, values))
                        for key, values in (entry.get("unless") or {}).items()},
                stated=entry.get("stated"),
                seeded=bool(entry.get("seeded")),
                settle=entry.get("settle"),
            )
            for entry in document[language]
        )  # fmt: skip
        for language in ("python", "r")
    }


def calls_in(tokens: list[Token]) -> list[Call]:
    """Each call: a name followed by an opening bracket, with its named arguments."""
    code = [token for token in tokens if token.kind not in ("comment", "docstring")]
    found = []
    for index, token in enumerate(code[:-1]):
        if token.kind != "code" or not _is_name(token.text) or code[index + 1].text != "(":
            continue
        arguments, given = _arguments(code, index + 1)
        found.append(Call(token.text, token.start, arguments, given))
    return found


def _is_name(text: str) -> bool:
    return (text[0].isalpha() or text[0] in "_.") and text not in (".", "..")


def _arguments(code: list[Token], opening: int) -> tuple[dict[str, str], bool]:
    """The arguments given by name at the top level of the call whose bracket opens at
    `opening`, each with the first token of its value; and whether any argument is given."""
    arguments: dict[str, str] = {}
    stack = [")"]
    index = opening + 1
    given = False
    while index < len(code) and stack:
        text = code[index].text
        if code[index].kind == "code" and text in _CLOSES:
            stack.append(_CLOSES[text])
        elif code[index].kind == "code" and text == stack[-1]:
            stack.pop()
            if not stack:
                break
        elif len(stack) == 1:
            given = True
            following = code[index + 1 : index + 3]
            if (
                code[index].kind == "code"
                and _is_name(text)
                and following[:1]
                and following[0].text == "="
                and (len(following) < 2 or following[1].text != "=")
                and index + 2 < len(code)
            ):
                arguments[text] = code[index + 2].text
        index += 1
    return arguments, given


def estimates_in(text: str, language: str) -> list[Estimate]:
    """Each call in a script that estimates, samples, draws at random or drops rows, and
    has not been told not to."""
    tokens = lex(text, language)
    calls = calls_in(tokens)
    seeded = any(named(call.name, SEEDS[language]) and call.given for call in calls)
    found = []
    for call in calls:
        if named(call.name, SEEDS[language]):
            continue
        rule = next((rule for rule in rules()[language] if rule.calls(call.name)), None)
        if rule is None:
            continue
        if any(call.arguments.get(name) in values for name, values in rule.unless.items()):
            continue
        if rule.stated and call.arguments.get(rule.stated) not in NOT_GIVEN:
            continue
        if rule.seeded and seeded:
            continue
        found.append(Estimate(call, rule))
    return found


def check_figure_estimates(script: Path, text: str, language: str, allowed: dict[str, str]
                           ) -> Report:  # fmt: skip
    """A warning for each call in a figure's script that estimates while it draws."""
    findings = []
    for estimate in estimates_in(text, language):
        name = estimate.call.name
        if named(name, tuple(allowed)):
            continue
        line = text.count("\n", 0, estimate.call.start) + 1
        how = _how_to_settle(estimate.rule)
        findings.append(
            Finding(
                gate=GATE,
                code="figure-estimates",
                severity=WARN,
                message=f"{name}(...) {estimate.rule.what}",
                path=script,
                line=line,
                context=text.splitlines()[line - 1].strip()[:160] if text else "",
                hint="compute it in the analysis and emit it, so that the text and the figure "
                f"show one result{how}; or give the reason in {script.stem}.guard.yaml under "
                "allow_estimates",
            )
        )
    return Report(tuple(findings))


def _how_to_settle(rule: Estimating) -> str:
    ways = [f"{name}={values[0]}" for name, values in rule.unless.items()]
    if rule.stated:
        ways.append(rule.settle or f"give {rule.stated}")
    if rule.seeded:
        ways.append("set a seed in the script")
    return f"; or {' or '.join(ways)}" if ways else ""
