"""G2: the label written beside an interval or a spread is the one the analysis emitted.

`em.interval` records the level of each interval on its bounds, its own `level` or the
script's `ci_level`, and `em.value(..., spread="sd")` whether a dispersion is a standard
deviation or a standard error. Nothing compared either with the text: "(90% CI
{{results.ror.ci_low}} to {{results.ror.ci_high}})" over a 95% interval, and "(SE
{{results.age.sd}})" over a standard deviation, printed without a word.

What is read is the label nearest a binding, in its own sentence and on its own side of
any other binding: the text from the binding before it in the sentence, or the sentence's
start, to the binding, and for a spread the few characters after it as well ("12.3 (SD)").
The label read there is compared with the one recorded, and a difference is a warning. A
bound of an interval with no level recorded at all is said once, where the interval is
first quoted, as a warning that asks for it. Nothing is said where no label is written.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts.values import Value
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.text.masking import blank_comments

GATE = "G2"
_SPACE = r"[ \t\u00a0\u2009\u202f]"
_NUMBER = r"(\d{1,2}(?:\.\d+)?)"
_WORDS = r"(?:" + _SPACE + r"*[\w-]+){0,3}"
_LETTERS = r"(?:CIs?|CrIs?|UIs?|intervals?)\b"
#: A level written before the letters, "95% CI", "90% two-sided confidence interval", or
#: after them, "CI 95%".
_LEVEL = re.compile(
    r"(?<![\w.])" + _NUMBER + _SPACE + r"?%" + _WORDS + _SPACE + r"*" + _LETTERS
    + r"|(?<![\w-])(?:CIs?|CrIs?|UIs?)" + _SPACE + r"*" + _NUMBER + _SPACE + r"?%"
)  # fmt: skip
#: How a text labels each kind of dispersion: an abbreviation as it is written, or the words.
_SPREADS = {
    "sd": re.compile(r"(?<![\w.])(?:SDs?|s\.d\.)(?![\w])|(?i:\bstandard deviations?\b)"),
    "se": re.compile(
        r"(?<![\w.])(?:SEs?|SEMs?|s\.e\.(?:m\.)?)(?![\w])|(?i:\bstandard errors?\b)"
    ),
}
_NAMES = {"sd": "a standard deviation", "se": "a standard error"}
#: How far after a spread's binding its label is looked for: "12.3 (SD)", "12.3 SD".
_AFTER = 12
_STOPS = ".!?"
_SENTENCE_END = re.compile(rf"[{re.escape(_STOPS)}](?:\s|$)")


def labelled(files: list[tuple[Path, str, list]], namespace: dict[str, Value]) -> Report:
    """Each interval's level and each spread's kind, as the text labels them beside their
    bindings, against what was emitted."""
    report = Report()
    asked: set[str] = set()
    for path, text, located in files:
        read = blank_comments(text) if "<!--" in text else text
        stops = [match.start() for match in _SENTENCE_END.finditer(read)]
        bindings = sorted(((p.start, p.end, p.ref, s) for p, s in located), key=lambda b: b[0])
        for index, (start, end, ref, _sentence) in enumerate(bindings):
            value = namespace.get(ref)
            if value is None or not (value.bounds or value.spread):
                continue
            line = text.count("\n", 0, start) + 1
            before = _before(read, stops, bindings, index)
            if value.bounds and value.bound in ("low", "high"):
                estimate = f"{value.namespace}.{value.bounds}"
                if not value.level:
                    if estimate not in asked:
                        asked.add(estimate)
                        report = report.with_findings(_undeclared(estimate, path, line))
                    continue
                stated = _stated_level(before)
                if stated is not None and not _same_level(stated, value.level):
                    report = report.with_findings(
                        _level_differs(value, estimate, stated, path, line)
                    )
            if value.spread in _SPREADS:
                after = _after(read, bindings, index, end)
                said = _stated_spread(before, after)
                if said is not None and said != value.spread:
                    report = report.with_findings(_spread_differs(value, said, path, line))
    return report


def _before(read: str, stops: list[int], bindings: list, index: int) -> str:
    """The text a binding's label stands in, before it: from the binding before it in the
    same sentence, or from the sentence's start. Sentences are G2's own (`in_sentences`):
    the one numbered `n` opens after the stop that ends the one before it."""
    start, _end, _ref, sentence = bindings[index]
    previous = [b for b in bindings[:index] if b[3] == sentence]
    if previous:
        return read[previous[-1][1] : start]
    opens = stops[sentence - 1] + 1 if 0 < sentence <= len(stops) else 0
    return read[opens:start] if opens <= start else ""


def _after(read: str, bindings: list, index: int, end: int) -> str:
    """The few characters after a binding, up to the next binding or the sentence's end."""
    following = bindings[index + 1][0] if index + 1 < len(bindings) else len(read)
    window = read[end : min(following, end + _AFTER)]
    stop = _SENTENCE_END.search(window)
    return window[: stop.start()] if stop else window


def _stated_level(before: str) -> str | None:
    """The level the text writes nearest a bound, before it: the last one."""
    found = None
    for match in _LEVEL.finditer(before):
        found = match.group(1) or match.group(2)
    return found


def _same_level(stated: str, recorded: str) -> bool:
    """Whether "95" and "95%" (or "95.0") are one level."""
    number = re.match(r"\s*(\d{1,2}(?:\.\d+)?)\s*%", recorded)
    return number is not None and float(number.group(1)) == float(stated)


def _stated_spread(before: str, after: str) -> str | None:
    """The kind of dispersion the text labels a binding: the label nearest it before, or
    else the first just after."""
    nearest: tuple[int, str] | None = None
    for kind, pattern in _SPREADS.items():
        for match in pattern.finditer(before):
            if nearest is None or match.start() > nearest[0]:
                nearest = (match.start(), kind)
    if nearest is not None:
        return nearest[1]
    first: tuple[int, str] | None = None
    for kind, pattern in _SPREADS.items():
        match = pattern.search(after)
        if match and (first is None or match.start() < first[0]):
            first = (match.start(), kind)
    return first[1] if first else None


def _undeclared(estimate: str, path: Path, line: int) -> Finding:
    return Finding(
        gate=GATE,
        code="interval-level-undeclared",
        severity=WARN,
        message=f"the interval of {estimate} is quoted, and its level was not emitted",
        path=path,
        line=line,
        hint='say it where the analysis emits it: Emitter(..., ci_level="95%") for every '
        'interval of the script, mg_emitter(..., ci_level = "95%") in R',
    )


def _level_differs(value: Value, estimate: str, stated: str, path: Path, line: int) -> Finding:
    return Finding(
        gate=GATE,
        code="interval-level-differs",
        severity=WARN,
        message=f"{value.namespace}.{value.key} bounds the {value.level} interval of "
        f"{estimate}, and the text calls it a {stated}% interval",
        path=path,
        line=line,
        hint="write the level the analysis emitted, or bind the bounds of the interval the "
        "text means",
    )


def _spread_differs(value: Value, said: str, path: Path, line: int) -> Finding:
    return Finding(
        gate=GATE,
        code="spread-label-differs",
        severity=WARN,
        message=f"{value.namespace}.{value.key} is {_NAMES[value.spread]}, and the text "
        f"labels it {_NAMES[said]}",
        path=path,
        line=line,
        hint="write the label of what the analysis emitted, or bind the value the text means",
    )


__all__ = ["labelled"]
