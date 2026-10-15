"""G8 — the arithmetic the analysis declares between its results holds.

The rest of G8 holds one quantity to itself. Nothing held different quantities to each
other: the start of a cohort less its exclusions and the cohort analysed, the subgroups and
their total, a rate and its events over person-time, a difference and its two parts. Each
was bound and each passed, and a flow diagram's counts were typed by hand. The analysis
declares these relations when it emits (`em.relation`, `em.flow`), so nothing here searches
the prose for numbers that might be related.

* `relation-broken`: the values break a declared relation, exactly where they are whole
  numbers and to the last bits of a float where they are not. It fails: the analysis's own
  numbers disagree with each other.
* `relation-rounding`: the values hold it, and the printed numbers do not: a reader who
  takes 1.1 from the printed 2.4 gets 1.3, and the difference is printed 1.2. A warning,
  since rounding each key on its own does this routinely; the text may want one more digit
  or a sentence saying so. The printed key is allowed half a unit of its last place. A
  display is read only where it is a rounding of its own value, so "<0.001", or a rate
  printed per 1,000 of a value held per person, is left to the values.
* `relation-unresolved`: a relation or a flow names a key nothing emits, or a value that is
  not a number (for `in_order`, not a date either), or a count that is not whole.
* `flow-broken`: a stage less its exclusions is not the next stage, the arms do not sum to
  the last stage, or the record has not one set of exclusions for each step. It fails.
"""

from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal, DivisionByZero, InvalidOperation

from manuscript_guard.contracts.results import Results
from manuscript_guard.contracts.values import Value
from manuscript_guard.emit import flow_problem
from manuscript_guard.findings import FAIL, WARN, Finding, Report

GATE = "G8"
#: How near two floats are taken to be equal. The values are the analysis's own, unrounded,
#: so a relation between them holds to the last bits the arithmetic leaves.
TOLERANCE = 1e-9
#: The first number in a display, with its thousands separators and its sign.
_NUMBER = re.compile(r"[-\N{MINUS SIGN}]?\d[\d,]*(?:\.\d+)?")
_FLOW_HINT = (
    "a flow's counts come from one computation; find the step whose count is not the one "
    "that step produced"
)
_BROKEN_HINT = (
    "the analysis's own numbers disagree: correct the computation, or the declaration if it "
    "names the wrong keys. Emit values unrounded; the display does the rounding"
)


def check_relations(results: Results) -> Report:
    """Each declared relation and flow, held to the values and to their displays."""
    findings: list[Finding] = []
    for relation in results.relations:
        findings += _relation(relation, results.values)
    for key, flow in sorted(results.flows.items()):
        findings += _flow(key, flow, results.values)
    checked = len(results.relations) + len(results.flows)
    return Report(tuple(findings), {"relations_checked": checked})


def _relation(relation: dict, values: dict[str, Value]) -> list[Finding]:
    kind, key, of = relation["kind"], relation["key"], list(relation["of"])
    source = relation.get("source")
    missing = [name for name in (key, *of) if name not in values]
    if missing:
        return [_unresolved(f"a {kind} declared of {key} names {', '.join(missing)}, which "
                            "nothing emits", source)]  # fmt: skip
    if kind in ("at_most", "in_order"):
        return _order(kind, key, of[0], values, source)
    numbers = [_number(values[name].value) for name in (key, *of)]
    if None in numbers:
        named = [name for name, n in zip((key, *of), numbers, strict=True) if n is None]
        return [_unresolved(f"a {kind} of {key} holds {', '.join(named)}, which is no number",
                            source)]  # fmt: skip
    result, *parts = numbers
    scale = float(relation.get("scale", 1))
    computed = _apply(kind, parts, scale)
    # A sum or a difference of whole numbers is whole and exact; a ratio's is a float.
    exact = kind != "ratio" and all(_whole(values[name].value) for name in (key, *of))
    if computed is None or not _equal(result, computed, exact):
        said = "undefined, the denominator being 0" if computed is None else _say(computed)
        return [
            _finding(
                "relation-broken",
                f"{key} is {values[key].display}, and the {kind} of {', '.join(of)} is {said}",
                source,
                FAIL,
                _BROKEN_HINT,
            )
        ]
    return _printed(kind, key, of, relation.get("scale", 1), values, source)


def _equal(result: float, computed: float, exact: bool) -> bool:
    if exact:
        return result == computed
    return math.isclose(result, computed, rel_tol=TOLERANCE, abs_tol=TOLERANCE)


def _apply(kind: str, parts: list, scale):
    """The relation's arithmetic, on floats or on Decimals alike; None for a zero divisor."""
    if kind == "sum":
        return math.fsum(parts) if isinstance(parts[0], float) else sum(parts)
    if kind == "difference":
        return parts[0] - parts[1]
    if kind == "ratio":
        return None if parts[1] == 0 else parts[0] / parts[1] * scale
    return None


def _printed(
    kind: str, key: str, of: list[str], scale, values: dict[str, Value], source
) -> list[Finding]:
    """The arithmetic a reader can do on the printed numbers, against the printed key."""
    shown = [_shown(values[name]) for name in (key, *of)]
    if None in shown:
        return []
    (printed, half), *parts = shown
    try:
        computed = _apply(kind, [number for number, _half in parts], Decimal(str(scale)))
    except (InvalidOperation, DivisionByZero):
        return []
    if computed is None or abs(computed - printed) <= half:
        return []
    printed_parts = ", ".join(values[name].display for name in of)
    return [
        _finding(
            "relation-rounding",
            f"{key} is printed {values[key].display}, and the {kind} of the printed "
            f"{printed_parts} is {_say(float(computed))}",
            source,
            WARN,
            "a reader doing the arithmetic gets another number: print one more digit, or say "
            "in the text that each number is rounded on its own",
        )
    ]


def _shown(value: Value) -> tuple[Decimal, Decimal] | None:
    """The number a display prints, on the value's scale, and half a unit of its last place.

    None where the display is not a rounding of the value: no number in it, a bound such as
    "<0.001", or a value printed on another scale. A whole number printed whole is exact."""
    match = _NUMBER.search(value.display)
    number = _number(value.value)
    if match is None or number is None:
        return None
    try:
        printed = Decimal(match.group(0).replace(",", "").replace("\N{MINUS SIGN}", "-"))
    except InvalidOperation:
        return None
    exponent = printed.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    half = Decimal(5) * Decimal(10) ** (exponent - 1)
    percent = value.unit == "%" or value.display.rstrip().endswith("%")
    if percent and abs(number) <= 1 < abs(printed):
        # A share held as a fraction and printed as a percentage.
        printed, half = printed / 100, half / 100
    if _whole(value.value) and printed == Decimal(int(number)):
        return printed, Decimal(0)
    if not float(printed - half) <= number <= float(printed + half):
        return None
    return printed, half


def _order(kind: str, key: str, other: str, values: dict[str, Value], source) -> list[Finding]:
    first, second = _comparable(values[key].value), _comparable(values[other].value)
    if first is None or second is None or type(first) is not type(second):
        what = "dates or numbers" if kind == "in_order" else "numbers"
        return [_unresolved(f"{kind} of {key} and {other}: {values[key].display} and "
                            f"{values[other].display} are not both {what}", source)]  # fmt: skip
    if kind == "at_most" and isinstance(first, date):
        return [_unresolved(f"at_most of {key} and {other}: dates are put in order by "
                            "in_order", source)]  # fmt: skip
    if first <= second:
        return []
    word = "after" if kind == "in_order" else "more than"
    return [
        _finding(
            "relation-broken",
            f"{key} ({values[key].display}) is {word} {other} ({values[other].display})",
            source,
            FAIL,
            _BROKEN_HINT,
        )
    ]


def _comparable(value: object) -> float | date | None:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return _number(value)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _flow(key: str, flow: dict, values: dict[str, Value]) -> list[Finding]:
    source = flow.get("source")
    entries = [*flow["stages"], *(e for step in flow["exclusions"] for e in step),
               *flow.get("arms", ())]  # fmt: skip
    missing = [entry["key"] for entry in entries if entry["key"] not in values]
    if missing:
        return [_unresolved(f"flow {key} names {', '.join(missing)}, which nothing emits",
                            source)]  # fmt: skip
    if len(flow["exclusions"]) != len(flow["stages"]) - 1:
        return [_finding("flow-broken", f"flow {key} has {len(flow['stages'])} stages and "
                         f"{len(flow['exclusions'])} sets of exclusions, where each step "
                         "has one", source, FAIL, _FLOW_HINT)]  # fmt: skip
    counted = {e["key"]: values[e["key"]].value for e in entries}
    wrong = [name for name, n in counted.items() if not _whole(n)]
    if wrong:
        return [_unresolved(f"flow {key}: {', '.join(wrong)} is not a whole number", source)]

    def counts(step: list[dict]) -> list[int]:
        return [counted[entry["key"]] for entry in step]

    problem = flow_problem(
        counts(flow["stages"]),
        [counts(step) for step in flow["exclusions"]],
        counts(flow.get("arms", [])),
        bool(flow.get("overlapping")),
    )
    if problem is None:
        return []
    return [_finding("flow-broken", f"flow {key}: {problem}", source, FAIL, _FLOW_HINT)]


def _say(number: float) -> str:
    return f"{number:.6g}"


def _unresolved(message: str, source) -> Finding:
    return _finding(
        "relation-unresolved",
        message,
        source,
        FAIL,
        "emit the key, or correct the name in em.relation or em.flow",
    )


def _finding(code: str, message: str, path, severity: str, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=severity, message=message, path=path,
                   hint=hint)  # fmt: skip
