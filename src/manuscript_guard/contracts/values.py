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
    # The author saying "this string is a name or a period, not a measurement". Carried
    # through to the reader, because the annotated copy paints a bound value green — "traced
    # to a results value" — and a sentence published through the results file is prose that
    # nothing verified, wearing the strongest reassurance the document offers.
    label: bool = False
    # Another key this one is the same quantity as. G8 catches two keys holding the *same*
    # value with different displays, and goes quiet once they have actually diverged —
    # which is when it matters. Nothing in the file recorded that two keys were meant to
    # agree, so this is the author saying so.
    same_as: str | None = None
    # The estimate this value bounds, and which end it is. Three keys that happen to be
    # named ci_low, ci_high and point are three unrelated numbers as far as any check is
    # concerned — so `{{results.ror.ci_high}} to {{results.ror.ci_low}}` resolved cleanly
    # and printed the interval backwards. The table path has refused a typed composite cell
    # for exactly this reason since round two; prose had no equivalent.
    bounds: str | None = None
    bound: str | None = None
    # Which interval this bound belongs to, when one estimate carries more than one: "90%"
    # beside a 95% CI, or a credibility interval beside a frequentist one. Bounds are
    # compared within a level and never across, because a 90% interval nested inside a 95%
    # one is correct rather than a contradiction.
    level: str | None = None

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
        shown = f"{value:.{digits}f}"
        # A rounding that turns a real number into zero is not a rounding of it. A p-value of
        # 3.2e-9 emitted with digits=2 was published as "0.00": the emitter printing a number
        # that is not the number, silently, in the field a reader looks at first. An explicit
        # `display` is checked against its value, and a *derived* one was checked against
        # nothing at all.
        if float(value) != 0.0 and float(shown) == 0.0:
            raise DisplayError(
                f"{key}: rounding {value!r} to {digits} decimal place(s) gives {shown!r}, "
                f"which is not this number. Say what the paper should print: "
                f'display="<0.001" for a value too small to state, or display="3.2 × 10⁻⁹" '
                f"for one worth stating precisely — both are checked against the value"
            )
        return shown
    if isinstance(value, str):
        return value
    raise DisplayError(f"{key}: values of type {type(value).__name__} need an explicit `display`")


# A string value is its own display, and nothing checked what was in it. So the hole closed
# on the `display=` route stayed wide open one line away:
#
#     em.value("ror.headline", "12.34 (95% CI 8.00 to 19.00)")
#
# published a fabricated estimate and a fabricated interval, quoted through an ordinary
# binding, with every gate green. `_cell` already refused a numeric string in a table for
# exactly this reason; `value()` did not.
#
# Strings carrying digits are still wanted — "2015-2024" is a study period, "CYP2C19" a
# genotype — so the rule is an opt-in rather than a ban: say it is a label and it is one.
_LABELLIKE = re.compile(
    r"^\s*(?:"
    r"(?:19|20)\d{2}\s*[-–—/]\s*(?:19|20)?\d{2}"  # a period: 2015-2024, 2015-24
    r"|(?:19|20)\d{2}"  # a single year
    r")\s*$"
)


def check_string_value(key: str, value: str, *, label: bool) -> None:
    """Refuse a string value that carries an unexplained number.

    `label=True` is the author saying "this is a name or a period, not a measurement".
    Obvious period and year forms are accepted without it, because making every study period
    carry a flag would teach authors to set the flag everywhere, which is the same as not
    having it.
    """
    if label or not any(ch.isdigit() for ch in value):
        return
    if _LABELLIKE.match(value):
        return

    from manuscript_guard.classify import UNCLASSIFIED, Classifier
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.tokens import find_atoms

    classifier = Classifier.load()
    loose = [
        atom.text
        for atom in find_atoms(value, mask(value))
        if classifier.classify(atom, ("Value",)).kind == UNCLASSIFIED
    ]
    if loose:
        raise DisplayError(
            f"{key}: the string value {value!r} carries {', '.join(repr(t) for t in loose)}, "
            f"which no gate can trace. Emit each number as its own value so it can be quoted "
            f"and checked, or pass `label=True` if this really is a name rather than a "
            f"measurement"
        )


# Digits, one optional decimal part, optional exponent — with thousands separators and a
# leading sign allowed, and a unit or a percent sign allowed to trail. Anything else in a
# display string means it is not a rendering of this number.
_NUMERIC_DISPLAY = re.compile(
    r"""^\s*
    # A comparator, because a rounded p-value is written "<0.001" and that is the honest
    # rendering of a number too small to state. The value must still be on the stated side
    # of it, which `_check_display_matches` enforces separately.
    (?P<compare><|>|≤|≥|<=|>=)?\s*
    (?P<sign>[-+−])?
    (?P<number>\d{1,3}(?:[,    ]\d{3})+(?:\.\d+)?
              |\d+(?:\.\d+)?)
    # An exponent, in the two forms a paper is written in: 3.2e-9 as a programmer types it,
    # and "3.2 × 10⁻⁹" as a journal prints it. Without the second, a p-value worth stating
    # precisely could be written only in a notation no journal uses, and the alternative an
    # author reaches for is `digits=` — which used to round it silently to "0.00".
    (?:
        [eE](?P<exp>[-+]?\d+)
      | \s*[x×*]\s*10\s*(?:\^|\*\*)?\s*(?P<sup>[-+−]?[0-9]+|[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)
    )?
    # A unit carries no digits of its own. Without that, "(95% CI 2.10 to 7.02)" parses as
    # the unit of 3.84 and the whole interval is waved through as a rendering of one number.
    \s*(?P<unit>%|[^\s\d][^\d]*?)?
    \s*$""",
    re.VERBOSE,
)

#: Superscript digits, so "10⁻⁹" reads as an exponent rather than as a unit.
_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


def _exponent_of(match: re.Match) -> str:
    """The exponent a display carries, whichever of the two ways it was written."""
    if match.group("exp"):
        return match.group("exp")
    written = match.group("sup")
    if not written:
        return ""
    return written.translate(_SUPERSCRIPT).replace("−", "-")


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
    exponent_text = _exponent_of(match)
    if exponent_text:
        text = f"{text}e{exponent_text}"

    shown = float(text)
    compare = match.group("compare")
    if compare:
        # "<0.001" is true of any value below 0.001 and false of 0.4. Checking the direction
        # rather than the distance is the whole content of a comparator display.
        below = compare in ("<", "<=", "≤")
        satisfied = float(value) <= shown if below else float(value) >= shown
        if not satisfied:
            raise DisplayError(
                f"{key}: display {display!r} says the value is "
                f"{'below' if below else 'above'} {shown!r}, but it is {value!r}"
            )
        return

    # The display is a rounding, so it need only agree to its own precision: half a unit in
    # the last place *shown*, with a little slack for binary representation.
    #
    # "In the last place shown" has to account for the exponent. Computing it from the
    # mantissa alone gave a fixed ~0.005 absolute tolerance however small the number was, so
    # for anything with a negative exponent the check stopped meaning anything: a value of
    # 1.2e-6 accepted a display of "9.99e-6", of "1e-2", and even of "-9e-6". Large values
    # were fine only because the relative term dominates there.
    exponent = int(exponent_text or 0)
    decimals = len(text.partition(".")[2].split("e")[0])
    tolerance = 0.5 * (10 ** (exponent - decimals)) + abs(float(value)) * 1e-9
    if abs(shown - float(value)) > tolerance:
        raise DisplayError(
            f"{key}: display {display!r} reads as {shown!r}, but the value is {value!r}. "
            f"Round it with `digits=` rather than writing the number twice; if the display "
            f"is in different units, emit the value in those units and name them with `unit=`"
        )
