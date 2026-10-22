"""The pieces a proof is compared with what was sent by: numbers, words and marks.

A typesetter changes a number in one of a few ways: a digit, a decimal mark, a sign, a
place. Each is read here from the number as printed, with its sign read where a sign can
stand, as `audit` reads one: a hyphen or an en dash after a space or a bracket is a minus,
after a digit it joins a range. What a proof changes and means the same is told apart from
what it changes and means something else: "19 950" for "19950", ".001" for "0.001" and a
true minus for a hyphen are typography; "3,84" for "3.84" and "0.51" for "-0.51" are not.

Both texts are read in Unicode's compatibility form (NFKC) first, as a reader sees them: a
ligature is its letters, a superscript two is a two, a micro sign is a mu, and a thin or a
no-break space is a space.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from manuscript_guard.audit import _SIGN_MAY_FOLLOW
from manuscript_guard.gates.notation import UNITS

#: The glyphs a sign is set in. U+2212 is always a minus; the others are one only where a
#: sign can stand (`_SIGN_MAY_FOLLOW`), as `audit` reads them. The hyphens of U+2010 and
#: U+2011 are here because a proof sets a minus in them, which is a fault of typography and
#: not a positive number.
_DASHES = "-‐‑‒–"
_SIGN = rf"(?:(?<![^{_SIGN_MAY_FOLLOW}‐‑‒])[{_DASHES}+]|−)"
#: Digits in groups of three after a comma, a no-break space or a thin space, then a decimal
#: part after a point, a comma or a middle dot (the Lancet's); or a decimal part alone, as a
#: style that drops the leading zero prints a P, ".001", where no word or point is before it.
_DIGITS = (
    r"(?:\d+(?:[,   ]\d{3}(?!\d))*(?:[.,·]\d+)?"
    r"|(?<![\w.,·])[.·]\d+)"
)
_TOKEN = re.compile(
    rf"(?P<number>{_SIGN}?{_DIGITS})|(?P<word>[^\W\d_]+)|(?P<mark>\S)"
)

#: Marks read as one another: the quotation marks, the dashes between words, the times sign.
_FOLDED = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-", "×": "x",
})  # fmt: skip

NUMBER, WORD, MARK = "number", "word", "mark"

#: The units G14 knows, as words in their compatibility form: "\N{MICRO SIGN}g" is "μg". A
#: unit of time spelt out is a word: taken for a unit, "12 wk" printed for "12 weeks", as
#: the AMA sets it, was a correction (round 2 of #397).
_UNIT_WORDS = frozenset(
    unicodedata.normalize("NFKC", unit) for unit in UNITS
    if unicodedata.normalize("NFKC", unit).isalpha()
)  # fmt: skip
#: The units of time spelt out, each read as its singular. One printed as another beside a
#: number, "12 weeks" as "12 months", is a correction; printed as "12 wk" or "12 week", a
#: copy-edit.
_TIME_WORDS = {
    spelling: unit
    for unit in ("second", "minute", "hour", "day", "week", "fortnight", "month", "year", "decade")
    for spelling in (unit, unit + "s")
}  # fmt: skip
#: The symbols beside a number that change what it says.
SYMBOLS = frozenset("%‰‱°")
COMPARATORS = frozenset("<>=≤≥≦≧±≈~≠")


def _unit_key(raw: str) -> str | None:
    """A unit's spelling compared with case kept, "mM" not being "mm", and a litre's two
    spellings and microgram's two read as one."""
    if raw not in _UNIT_WORDS:
        return None
    if raw.endswith("l") and raw[:-1] + "L" in _UNIT_WORDS:
        raw = raw[:-1] + "L"
    return {"mcg": "μg"}.get(raw, raw)


def is_unit(raw: str) -> bool:
    """A unit, a percent or degree sign, or a comparator: what changes the number beside it."""
    return raw in SYMBOLS or raw in COMPARATORS or _unit_key(raw) is not None


def time_units(found: list[Token]) -> set[str]:
    """The units of time the tokens spell out."""
    return {_TIME_WORDS[t.raw.casefold()] for t in found if t.raw.casefold() in _TIME_WORDS}


@dataclass(frozen=True)
class Token:
    """One piece of a text: what it prints, what it is compared by, and where it is."""

    raw: str
    #: What the alignment compares: "#" for every number, so that a number changed in
    #: place lines up with the number it was, and the words folded as `key` folds them.
    key: str
    kind: str
    #: Whether nothing stands between it and the piece before it.
    glued: bool
    #: Where it comes from: the index of its part in what was sent, or of its line in the
    #: proof.
    where: int
    #: The piece of text it was read from, and where in it: what a sign beside it is
    #: read against.
    before: str = ""


def prepared(text: str) -> str:
    """The text as it is compared: in its compatibility form, with no soft hyphen."""
    return unicodedata.normalize("NFKC", text).replace("­", "")


def key(raw: str) -> str:
    unit = _unit_key(raw)
    return unit if unit is not None else raw.casefold().translate(_FOLDED)


def tokens(text: str, where: int) -> list[Token]:
    """The pieces of a text, which must already be `prepared`."""
    found = []
    for match in _TOKEN.finditer(text):
        kind = match.lastgroup or MARK
        raw = match.group(0)
        start = match.start()
        glued = start > 0 and not text[start - 1].isspace()
        before = text[start - 1] if start > 0 else ""
        found.append(Token(raw, "#" if kind == NUMBER else key(raw), kind, glued, where,
                           before))  # fmt: skip
    return found


@dataclass(frozen=True)
class Number:
    """A number as it is printed, read into what a typesetter can change."""

    negative: bool
    #: The sign's glyph, "" where there is none.
    sign: str
    #: The digits before the decimal mark, with no separator and no leading zero.
    whole: str
    #: The digits after it, "" where there is none.
    decimals: str
    #: The decimal mark: ".", "," or the middle dot, "" where there is none.
    mark: str
    #: The separators between groups of three, in order.
    groups: str


def read_number(raw: str) -> Number:
    sign = raw[0] if raw[0] in _DASHES + "+−" else ""
    body = raw[len(sign):]
    decimal = re.search(r"[.,·](\d+)$", body)
    # A comma before exactly three digits groups them: "4,000" is four thousand.
    if decimal and body[decimal.start()] == "," and len(decimal.group(1)) == 3:
        decimal = None
    whole_part = body[: decimal.start()] if decimal else body
    groups = "".join(ch for ch in whole_part if not ch.isdigit())
    whole = "".join(ch for ch in whole_part if ch.isdigit()).lstrip("0")
    return Number(
        negative=sign not in ("", "+"),
        sign=sign,
        whole=whole,
        decimals=decimal.group(1) if decimal else "",
        mark=body[decimal.start()] if decimal else "",
        groups=groups,
    )


#: What a change to a number is, from what a reader takes the number to be.
DIGITS, SIGN, DECIMAL_MARK = "digits", "sign", "decimal mark"
#: And what it is when the reader takes it to be the same number.
SAME, TYPOGRAPHY = "same", "typography"


def compare_numbers(sent: Token, printed: Token) -> tuple[str, str]:
    """What changed between a number as sent and as printed, and how to say it: `SAME`,
    `TYPOGRAPHY` (the same number set otherwise), or one of `DIGITS`, `SIGN`,
    `DECIMAL_MARK`."""
    if sent.raw == printed.raw:
        return SAME, ""
    one, two = read_number(sent.raw), read_number(printed.raw)
    if (one.whole, one.decimals) != (two.whole, two.decimals):
        return DIGITS, ""
    if one.negative != two.negative:
        # A sign glued to a digit or a letter may be an exponent's or a range's, read one
        # way in one text and the other in the other: "10-3" and "10\N{MINUS SIGN}3".
        if _ambiguous(sent) or _ambiguous(printed):
            return TYPOGRAPHY, "the sign is set differently beside the number before it"
        return SIGN, ""
    if one.mark != two.mark and "," in (one.mark, two.mark):
        return DECIMAL_MARK, ""
    said = []
    if one.sign != two.sign and two.negative and two.sign != "−":
        said.append("the minus is set as a hyphen or a dash")
    if one.mark != two.mark:
        said.append(f"the decimal mark is set as {two.mark!r}")
    if one.groups != two.groups:
        said.append("the digits are grouped differently")
    if (sent.raw.lstrip(_DASHES + "+−").startswith("0")
            != printed.raw.lstrip(_DASHES + "+−").startswith("0")):  # fmt: skip
        said.append("the leading zero is dropped or added")
    return (TYPOGRAPHY, "; ".join(said)) if said else (SAME, "")


def _ambiguous(token: Token) -> bool:
    return bool(token.raw) and token.raw[0] in _DASHES + "−" and (
        token.before.isalnum()
    )


def digits_of(found: list[Token]) -> str:
    """The digits of every number in a run, in order, each with its sign where it can only
    be a sign: what is the same in "19950" and "19 950", and in "10-3" and "10" with a true
    minus and "3" after it."""
    out = []
    for token in found:
        if token.kind != NUMBER:
            continue
        number = read_number(token.raw)
        before_mark = token.raw.rsplit(number.mark, 1)[0] if number.mark else token.raw
        whole = "".join(c for c in before_mark if c.isdigit())
        sign = "-" if number.negative and not _ambiguous(token) else ""
        mark = {"·": "."}.get(number.mark, number.mark)
        out.append(sign + whole + mark + number.decimals)
    return "".join(out)


def spelled(found: list[Token]) -> str:
    """A run of tokens written out as it was printed, near enough: each with the space
    before it that it had."""
    out = []
    for index, token in enumerate(found):
        if index and not token.glued:
            out.append(" ")
        out.append(token.raw)
    return "".join(out)
