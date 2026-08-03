"""The one value type every source of numbers resolves to.

Results, the literature ledger and author attestations all produce `Value` objects in a
single namespace-qualified space, so the substitution engine and the classifier never need
to know where a number came from — only the reporting does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

RESULTS = "results"
LITERATURE = "literature"
ATTESTED = "attested"


class DisplayError(Exception):
    """A value cannot be rendered without the author deciding how."""


@dataclass(frozen=True)
class Value:
    key: str
    value: object
    display: str
    origin: str
    source: Path | None = None
    unit: str | None = None
    quoted: bool = True
    detail: dict | None = None

    @property
    def namespace(self) -> str:
        return "results" if self.origin == RESULTS else "lit"

    @property
    def reference(self) -> str:
        """How this value is written in manuscript source."""
        return f"{{{{{self.namespace}.{self.key}}}}}"


def derive_display(key: str, value: object, display: str | None, digits: int | None) -> str:
    """Work out the prose form of a value, or refuse.

    A float with neither an explicit display string nor a digit count is rejected rather
    than formatted with some default. Implicit rounding is exactly how the same quantity
    comes to be written 4.3 in the abstract and 4.28 in a table, and no downstream check
    can recover the author's intent once it is lost.
    """
    if display is not None:
        _check_display_matches(key, value, display)
        return display
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if digits is None:
            raise DisplayError(
                f"{key}: a float needs `display` or `digits` so that every place it is "
                f"quoted rounds it identically"
            )
        return f"{value:.{digits}f}"
    if isinstance(value, str):
        return value
    raise DisplayError(f"{key}: values of type {type(value).__name__} need an explicit `display`")


# Digits, one optional decimal part, optional exponent — with thousands separators and a
# leading sign allowed, and a unit or a percent sign allowed to trail. Anything else in a
# display string means it is not a rendering of this number.
_NUMERIC_DISPLAY = re.compile(
    r"""^\s*
    (?P<sign>[-+−])?
    (?P<number>\d{1,3}(?:[,    ]\d{3})+(?:\.\d+)?
              |\d+(?:\.\d+)?)
    (?:[eE](?P<exp>[-+]?\d+))?
    # A unit carries no digits of its own. Without that, "(95% CI 2.10 to 7.02)" parses as
    # the unit of 3.84 and the whole interval is waved through as a rendering of one number.
    \s*(?P<unit>%|[^\s\d][^\d]*?)?
    \s*$""",
    re.VERBOSE,
)


def _check_display_matches(key: str, value: object, display: str) -> None:
    """An explicit `display` must be a rendering of its own value.

    Nothing used to compare the two, so a single call could publish a fabricated estimate
    and a fabricated interval at once:

        em.value("ror.point", 0.9487, display="3.84 (95% CI 2.10 to 7.02)")

    The manuscript then quoted `{{results.ror.point}}` and read 3.84, with every gate green,
    because the binding resolved and the number in prose was not a literal. `display` fixes
    *where* a number is formatted; this fixes that the formatting is of that number.

    Only numbers are checked. A string value is its own display, and a label like
    "2015-2024" is a value rather than a rounding of one.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return

    match = _NUMERIC_DISPLAY.match(display)
    if match is None:
        raise DisplayError(
            f"{key}: display {display!r} is not a rendering of {value!r}. A display carries "
            f"one number, optionally with a unit — an interval or a sentence belongs in "
            f"separate keys, so each part can be quoted and checked on its own"
        )

    text = match.group("number")
    for separator in (",", " ", " ", " ", " "):
        text = text.replace(separator, "")
    if match.group("sign") in ("-", "−"):
        text = f"-{text}"
    if match.group("exp"):
        text = f"{text}e{match.group('exp')}"

    shown = float(text)
    # The display is a rounding, so it need only agree to its own precision. Half a unit in
    # the last place shown, with a little slack for binary representation.
    decimals = len(text.partition(".")[2].split("e")[0])
    tolerance = 0.5 * (10**-decimals) + abs(float(value)) * 1e-9
    if abs(shown - float(value)) > tolerance:
        raise DisplayError(
            f"{key}: display {display!r} reads as {shown!r}, but the value is {value!r}. "
            f"Round it with `digits=` rather than writing the number twice; if the display "
            f"is in different units, emit the value in those units and name them with `unit=`"
        )
