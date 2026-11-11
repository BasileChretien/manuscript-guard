"""G14, its fourth reading — one notation.

"P = 0.03" in the Methods, "p=0.04" in the Results and "*P* <0.001" in a table's note are
one statistic written three ways, and a reader of a paper is entitled to wonder whether
they are three. Which way is right is a journal's to say: one house prints a capital
italic *P* and another a lower-case p, one joins the bounds of an interval with "to" and
another with an en dash. That the manuscript writes each thing **one** way is a fact about
the manuscript, the same in any field, and that is what this reading checks:

* `notation-p-symbol`: the symbol of a P value, "P", "p", "*P*" or "*p*".
* `notation-sign-spacing`: the spaces around the sign after `P` or `n`: "P = 0.03" or
  "P=0.03". A space on one side only, "P= 0.03", is reported whatever the rest does.
* `notation-interval`: what joins the two bounds of a confidence interval: "to", an en
  dash, a hyphen, a comma.
* `notation-percent`: "5%" or "5 %".

For each, the form the manuscript uses most is taken for its convention, and each other
form is reported once, where it first stands, with both counts. Where two forms are level
the later one is shown, and the finding says so.

Two findings are not about consistency:

* `notation-unit`: a number that runs into its unit, "5mg". The SI Brochure sets a space
  between the two, so this is reported wherever it stands, in a manuscript that always
  writes it so too. "%" is left to consistency above, because journals differ on it more
  than on any unit; where one prints "37°C", the warning is that journal's to overrule.
* `notation-space-missing`: a number typed against the word after it, "0.41points",
  "10hours", "2ndyear", or a word typed against a signed number, "to+0.77". No house style
  writes these: a space was left out (the author's Abstract, 2026-11-10, eight times).

**A value is a value, typed or bound.** In a manuscript of this toolkit the numbers are
bindings, `{{results.ror.point}}`, so the notation is read with each binding that stands in
a sentence taken for a number: "(95% CI {{…}} to {{…}})" is an interval joined by "to".

**Only what is typed is read.** How a bound value is printed, its decimals and its leading
zero, is the emitter's and the journal's, and is not this reading's.

All of it is a warning: a `p` can be a proportion, and a count is a majority, not a rule.

**What has one answer is an edit, at every place** (`notation_edits`): each other form of a
sign's spacing, an interval's join or a "%" made the manuscript's own, and each number run
into its unit or a word spaced, for the audit's copy in Track Changes. Not the P's symbol,
and nothing where two forms are used as often.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from manuscript_guard.corrections import Edit
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.spelling import opens_a_sentence
from manuscript_guard.gates.vocabulary import Passage, context, own_words
from manuscript_guard.text.masking import NUL

GATE = "G14"

#: What a binding that stands in a sentence is written as, for the patterns below: a run
#: of this character as long as the binding, so that every offset stays the text's.
VALUE = "\x01"
#: How many examples the finding on units quotes.
EXAMPLES = 4

_BINDING = re.compile(r"\{\{[^}\n]*\}\}")
# A space, of any width, and at most one line break: a sentence is wrapped where the
# editor wraps it.
_SPACE = "[ \t\u00a0\u2009\u202f]"
_GAP = _SPACE + "*(?:\n" + _SPACE + "*)?"
# A number as it is typed, or a bound value.
_TYPED = r"(?:\d+(?:[.,\u00b7]\d+)*|\.\d+)"
_NUMBER = r"(?:[-+\u2212]?" + _TYPED + "|" + VALUE + "+)"
# Nothing of a word, a number or a value may stand before a number that is read whole.
_NOT_INSIDE = r"(?<![\w.,\u00b7" + VALUE + "])"
# The sign of a comparison, with the escape `mask` blanks before `<` and `>`.
_SIGN = NUL + r"?[=<>\u2264\u2265]"
# What follows the figures of a number written as a power of ten: 3.2 x 10-9, 5e-8.
_POWER_OF_TEN = re.compile(
    r"[ \u00a0\u2009]?[x*\u00d7\u00b7\u22c5][ \u00a0\u2009]?10"
    r"|[eE][-+\u2212]?\d"
)
# What follows a ten that is itself raised to a negative power, "P < 10^-5^": a minus
# sign after a caret, raised, or after the tag that raises it, or a true minus sign
# alone. Not a hyphen alone, which makes "10-15 mmHg" a range, and no power above
# nought: "P = 10^3^ Pa" is a pressure.
_RAISED = re.compile(
    r"\^[-\u2212]\d|\u2212\d|\u207b[\u2070\u00b9\u00b2\u00b3\u2074-\u2079]|<sup>[-\u2212]\d"
)
# A typed number above 1: its whole part, and whether anything but zeros follows it.
_WHOLE_AND_REST = re.compile(
    r"[-+\u2212]?(?P<whole>\d*)(?:[.,\u00b7](?P<rest>[\d.,\u00b7]*))?"
)

# "P = 0.03", "*p*<0.001", "p-value of", "P {{…}}" where the binding prints its own sign.
_P = re.compile(
    r"(?<![\w\\" + VALUE + r"])(?P<mark>[*_]{0,2})(?P<symbol>[Pp])(?P=mark)(?![\w*_])"
    r"(?P<word>[- ]values?\b)?(?:~[^~\n]{1,24}~)?"
    r"(?:(?P<before>" + _GAP + r")(?P<sign>" + _SIGN + r")(?P<after>" + _GAP + r")"
    r"(?P<value>" + _NUMBER + r")"
    r"|(?P<bare>[ ]+)(?P<bound>" + VALUE + r"+))?"
)
# "n = 12", "(N=120)".
_N = re.compile(
    r"(?<![\w\\" + VALUE + r"])(?P<mark>[*_]{0,2})[nN](?P=mark)"
    r"(?P<before>" + _GAP + r")=(?P<after>" + _GAP + r")(?P<value>" + _NUMBER + r")"
)
# "95% CI 1.2 to 3.4", "(95% CI, 1.2-3.4)", "confidence interval of {{…}} to {{…}}".
_INTERVAL = re.compile(
    r"(?<![\w" + VALUE + r"])"
    r"(?:CIs?|CrIs?|(?:confidence|credible|credibility|compatibility)" + _GAP + r"intervals?)\b"
    # Each thing that may stand before the first bound brings its own gap. Three gaps in a
    # row shared a run of spaces out among themselves in every way: 800 spaces after
    # "CI" took 24 seconds.
    r"(?:" + _GAP + r"[\[(](?:CI|CrI)s?[\])])?"  # "confidence interval (CI)"
    # "CI 95%". Not where a bound in percent follows the percent sign after a hyphen or a
    # minus sign: in "CI 80%-93%; 12 studies" the 80% is the first bound. Taken for a level,
    # it left "-93" for a bound and the semicolon for the join. A level hard against a
    # negative bound, "CI 95%-0.3 to 0.4", is still a level.
    r"(?:" + _GAP + r"\d{2}(?:\.\d)?" + _SPACE + r"?%(?![-\u2212]\d[\d.,]*" + _SPACE + r"?%))?"
    r"(?:" + _GAP + r"(?:(?:of|from|was|were|is|are)\b|[:,=]))?"
    r"(?:" + _GAP + r"[\[(])?"
    + _GAP + r"(?P<low>" + _NUMBER + r")(?P<percent>" + _SPACE + r"?%)?"
    r"(?P<join>" + _GAP + r"to\b" + _GAP
    + r"|" + _SPACE + r"*(?:[\u2013\u2014]|-{2,3})" + _SPACE + r"*"
    + r"|" + _SPACE + r"?-" + _SPACE + r"?(?=[\d." + VALUE + r"])"
    + r"|" + _SPACE + r"*[,;]" + _SPACE + r"*)"
    r"(?P<high>" + _NUMBER + r")"
)
# A level of confidence stated before the letters: "95% CI", "95% two-sided Wald CI".
_LEVEL_BEFORE = re.compile(
    r"\d{2}(?:\.\d)?" + _SPACE + r"?%" + _GAP + r"(?:[\w-]+" + _GAP + r"){0,3}\Z"
)
#: The levels one states. Standing with a "%" right after the letters, and none before
#: them, such a number is the level and no bound: "a confidence interval of 95%, 5%
#: margin of error".
_LEVELS = ("80", "90", "95", "99", "99.9")
_JOINS = {
    "t": "'to'",
    "\u2013": "an en dash",
    "\u2014": "an em dash",
    "-": "a hyphen",
    # pandoc prints two hyphens as an en dash and three as an em dash
    "--": "an en dash",
    "---": "an em dash",
    ",": "a comma",
    ";": "a semicolon",
}
_PERCENT = re.compile(
    _NOT_INSIDE + r"(?P<value>" + _NUMBER + r")(?P<gap>" + _SPACE + r"*)%"
)

#: The unit symbols a number is not to run into. Of the symbols of one letter only `g` and
#: `h` are here: "5m" is as often five months, "1L" a first line of treatment, "30s" an
#: age, "5M" five million and "3A" a grade. And those two are not read where a number and
#: a letter are a name or a force: `_a_name` and `_a_force`.
UNITS = (
    "kg", "mg", "\u00b5g", "\u03bcg", "mcg", "ng", "pg", "g",
    "mL", "ml", "dL", "dl", "\u00b5L", "\u03bcL", "\u00b5l", "\u03bcl", "nL",
    "km", "cm", "mm", "\u00b5m", "\u03bcm", "nm",
    "ms", "min", "h",
    "mol", "mmol", "\u00b5mol", "\u03bcmol", "nmol", "pmol",
    "mM", "\u00b5M", "\u03bcM", "nM", "pM",
    "Hz", "kHz", "MHz", "GHz",
    "Pa", "kPa", "MPa", "hPa", "mmHg",
    "kJ", "kcal", "mV", "kV", "mA",
    "Gy", "mGy", "cGy", "Sv", "mSv", "\u00b5Sv", "\u03bcSv", "Bq", "kBq", "MBq", "GBq",
    "IU", "kDa", "Da", "bp", "kb", "ppm", "ppb", "mEq", "mOsm", "rpm", "bpm",
    "\u00b0C", "\u00baC", "\u2103", "\u00b0F", "\u00baF",
)  # fmt: skip
_UNIT = re.compile(
    r"(?<![\w.,\u00b7/" + VALUE + r"])(?P<value>" + _TYPED + "|" + VALUE + r"+)"
    r"(?P<unit>" + "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True)) + r")"
    # with its power, as it is typed: cm2, cm\u00b2 in the source, cm^2^
    r"(?:[\u00b2\u00b3]|\^?[-\u2212]?[123]\^?)?"
    r"(?![\w\u00b0])"
)
#: The units in lower case of three letters or more, which `_UNIT` reads and a space left
#: out does not: "30min". Not their plurals, which `_UNIT` does not read: "5mins" is a
#: space left out (round 1 of #613).
_LOWER_UNITS = frozenset(unit for unit in UNITS if len(unit) >= 3 and unit.islower())
#: A space left out: a number typed against a word of three lower-case letters or more,
#: "0.41points", "10hours", with an ordinal's suffix between them or not, "2ndyear"
#: (`_NUMBER_THEN_WORD`); and a word typed against a signed number, "to+0.77"
#: (`_WORD_THEN_NUMBER`). Not a name a number stands inside, "p53mutant", "COVID19cases",
#: which the letter before the number tells; not a unit, which `_UNIT` reads
#: (`_LOWER_UNITS`); and not a number in hexadecimal (`_HEXADECIMAL`).
_NUMBER_THEN_WORD = re.compile(
    r"(?<![\w.,\N{MIDDLE DOT}/" + VALUE + r"])(?:" + _TYPED + "|" + VALUE + r"+)"
    r"(?:st|nd|rd|th)?(?P<word>[a-z]{3,})\b"
)
#: A bound value is read after the word too, and a sentence's stop ends the number, "to+0.77."
#: (round 1 of #613); a stop before a digit does not.
_WORD_THEN_NUMBER = re.compile(
    r"\b[a-z]{2,}[+\N{MINUS SIGN}](?:" + _TYPED + "|" + VALUE + r"+)(?!\w|\.\d)"
)
_HEXADECIMAL = re.compile(r"0x[0-9a-f]+")
# What may stand between such a word and the number: the rest of its sentence. A full stop
# ends it only before a capital, so that "Fig. 2f vs. 2g" is one, and a line may be
# wrapped in it.
_SAME_SENTENCE = r"(?:[^.;\n]|\.(?![ \t\n]+(?-i:[A-Z]))|\n(?!\n))*\Z"
# The words after which a number and a letter name a part of something: Figure 3g, Table
# 2h. Looked for back to the start of the sentence, so that "Figures 2g and 3h" is two
# panels.
_PANEL = re.compile(
    r"\b(?:figs?\.?|figures?|tables?|panels?|schemes?)(?!\w)" + _SAME_SENTENCE, re.IGNORECASE
)
# The words after which they name a member of a series: compound 4g, products 5g and 6h.
# These are words of ordinary prose too, "each compound was incubated for 24h", so the
# name has to stand against its word, alone or in a list of its kind.
_SERIES = re.compile(
    r"\b(?:compounds?|products?|analogues?|analogs?|derivatives?|intermediates?|ligands?"
    r"|substrates?|entry|entries)"
    r"(?:[\s,*_\u2013-]|\b(?:and|or|to)\b|\b\d{1,3}[a-z]{0,2}\b)*\Z",
    re.IGNORECASE,
)
# A relative centrifugal force is written closed, "centrifuged at 12,000g": that g is no
# gram. It is known by a word of centrifuging before it in its sentence, or by its size:
# nobody types twelve kilograms as 12,000g.
_SPUN = re.compile(
    r"(?:centrifug|\bspun\b|\bspin(?:s|ning)?\b|\bpellet|\bsediment)" + _SAME_SENTENCE,
    re.IGNORECASE,
)
#: How far back that word is looked for.
_BACK = 80
#: From this many figures before its decimal point, a number before `g` is a force
#: wherever it stands. Four took a birth weight, "2500g", for one.
FORCE = 5


@dataclass(frozen=True)
class _Use:
    """One place a notation stands: the passage's place in the reading, the offset, the
    passage, and how long the words are."""

    place: int
    offset: int
    passage: Passage
    length: int
    #: The stretches of the passage's text an edit would change, each (start, end): the
    #: spaces around a sign, what joins two bounds, the space before "%", or the place a
    #: space is left out, where start and end are one.
    pieces: tuple[tuple[int, int], ...] = ()
    #: Whether a bound of an interval is negative, which a dash would read as its sign.
    negative: bool = False
    #: Whether the reading cannot be sure what it read: two or three hyphens against the
    #: high bound after a negative or bound low one, "-1.2--0.3", are pandoc's dash or a
    #: hyphen and the bound's minus sign.
    doubtful: bool = False

    @property
    def key(self) -> tuple[int, int]:
        return (self.place, self.offset)

    @property
    def words(self) -> str:
        """As the manuscript writes it, on one line, a binding shortened to `{{…}}`."""
        text = self.passage.text[self.offset : self.offset + self.length]
        return " ".join(_BINDING.sub("{{\N{HORIZONTAL ELLIPSIS}}}", text).split())


@dataclass
class _Family:
    """The forms one thing is written in, each with the places it stands."""

    forms: dict[str, list[_Use]] = field(default_factory=dict)

    def add(self, form: str, use: _Use) -> None:
        self.forms.setdefault(form, []).append(use)

    @property
    def uses(self) -> int:
        return sum(len(found) for found in self.forms.values())


def _counted(passage: Passage) -> str:
    """The passage's own words, with each value bound in a sentence written as a run of
    `VALUE`. A binding with something hidden on both sides of it stands in a listing, a
    comment or an equation, and stays hidden."""
    printed = own_words(passage.printed)
    if "{{" not in passage.text:
        return printed
    chars = list(printed)
    for found in _BINDING.finditer(passage.text):
        start, end = found.span()
        if printed[start] != NUL or printed[end - 1] != NUL:
            continue
        before = printed[start - 1] if start else " "
        after = printed[end] if end < len(printed) else " "
        if before == NUL and after == NUL:
            continue
        chars[start:end] = VALUE * (end - start)
    return "".join(chars)


def _above_one(value: str) -> bool:
    """Is this typed number greater than 1? A P value never is, so "P = 40 mmHg" is a
    pressure and "p = 10 predictors" a count. A bound value cannot be asked."""
    found = _WHOLE_AND_REST.fullmatch(value)
    if found is None:
        return False
    # Read as figures and never made a number: Python refuses to convert more than 4,300
    # digits, and a gate does not raise on what a manuscript holds.
    whole = (found["whole"] or "").lstrip("0")
    if whole in ("", "1"):
        return whole == "1" and any(char in "123456789" for char in found["rest"] or "")
    return True


def _negative(bound: str) -> bool:
    return bound[:1] in ("-", "\u2212")


def _a_name(text: str, start: int, end: int) -> bool:
    """Is the number and letter at `start` a name and no quantity: a panel, a compound of
    a series, or the two alone between marks of emphasis, as a compound is set?"""
    before = text[max(0, start - _BACK) : start]
    if before[-1:] in ("*", "_") and text[end : end + 1] in ("*", "_"):
        return True
    return _PANEL.search(before) is not None or _SERIES.search(before) is not None


def _a_force(value: str, before: str) -> bool:
    """Is this number before `g` a relative centrifugal force: one of five figures or more
    before its decimal point, or one in a sentence that has spoken of centrifuging?"""
    figures = sum(char.isdigit() for char in value.partition(".")[0])
    return figures >= FORCE or _SPUN.search(before) is not None


def _spacing(before: str, after: str) -> str:
    if before and after:
        return "spaced"
    return "lopsided" if before or after else "closed"


def _quoted(words: str) -> str:
    return f"'{words}'"


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _finding(code: str, use: _Use, message: str, hint: str) -> Finding:
    return Finding(
        gate=GATE,
        code=code,
        severity=WARN,
        message=message,
        path=use.passage.path,
        line=use.passage.line_of(use.offset),
        context=context(use.passage.text, use.offset, use.length),
        hint=hint,
    )


def _apart(family: _Family) -> list[tuple[str, list[_Use], str, list[_Use], bool]]:
    """Each form that is not the manuscript's own, with the form that is: the one used
    most, and of two used as often the one met first. `level` says they were as often."""
    if len(family.forms) < 2:
        return []
    ranked = sorted(
        family.forms.items(), key=lambda item: (-len(item[1]), min(use.key for use in item[1]))
    )
    most, kept = ranked[0]
    return [
        (form, found, most, kept, len(found) == len(kept)) for form, found in ranked[1:]
    ]


_KEEP = (
    "The journal's instructions say which form it prints; where they say nothing, keep "
    "the one the manuscript uses most. The place given is the first use of the other form"
)


def _hint(level: bool) -> str:
    return _KEEP + (", or the later of the two, since they are level" if level else "")


@dataclass
class _Read:
    """What the reading found before it judges: the forms of each thing, the numbers run
    into their unit, each with the unit, and the spaces left out."""

    symbols: _Family = field(default_factory=_Family)
    signs: _Family = field(default_factory=_Family)
    joins: _Family = field(default_factory=_Family)
    percents: _Family = field(default_factory=_Family)
    closed: list[tuple[_Use, str]] = field(default_factory=list)
    run_on: list[_Use] = field(default_factory=list)


def _doubtful(join: str, low: str) -> bool:
    """Are two or three hyphens against the high bound pandoc's dash or a hyphen and the
    bound's minus sign? Not after a positive low bound, where a minus sign would make the
    high bound the lower: "1.2--3.4" is the dash (rounds 1 and 2 of #636)."""
    return (join.strip() in ("--", "---") and join.endswith("-")
            and (_negative(low) or VALUE in low))  # fmt: skip


def _letters_before(found: re.Match[str]) -> int:
    """Where the sign stands in "to+0.77": after the word's letters."""
    typed = found.group(0)
    return found.start() + len(typed) - len(typed.lstrip("abcdefghijklmnopqrstuvwxyz"))


def _read(passages: Iterable[Passage]) -> _Read:
    """Each place the notation stands, over the whole manuscript in the order it is read."""
    read = _Read()
    symbols, signs, joins, percents = read.symbols, read.signs, read.joins, read.percents
    closed, run_on = read.closed, read.run_on

    for place, passage in enumerate(passages):
        text = _counted(passage)

        for found in _P.finditer(text):
            sign, word, bare = found["sign"], found["word"], found["bare"]
            if sign is None and word is None and bare is None:
                continue
            symbol = found["symbol"]
            if sign is not None and _above_one(found["value"]):
                ten = found["value"] == "10" and _RAISED.match(text, found.end())
                if not ten and not _POWER_OF_TEN.match(text, found.end()):
                    # A pressure, a partition coefficient, a number of predictors. Not
                    # "P = 3.2 x 10-9" or "P < 10^-5^", whose figures are above 1 and
                    # whose value is not.
                    continue
            use = _Use(place, found.start(), passage, found.end() - found.start(),
                       (found.span("before"), found.span("after")) if sign else ())
            if sign is not None:
                signs.add(_spacing(found["before"], found["after"]), use)
            if symbol == "P" and not found["mark"] and opens_a_sentence(text, found.start()):
                # "P values were two-sided." and "P < 0.05 was taken as significant." have
                # their capital from the sentence, in a paper that writes p too.
                continue
            mark = "*" * len(found["mark"])
            symbols.add(f"{mark}{symbol}{mark}", use)

        for found in _N.finditer(text):
            use = _Use(place, found.start(), passage, found.end() - found.start(),
                       (found.span("before"), found.span("after")))
            signs.add(_spacing(found["before"], found["after"]), use)

        for found in _INTERVAL.finditer(text):
            join = found["join"].strip()
            if join == "to" and (_negative(found["low"]) or _negative(found["high"])):
                # A house that joins with a dash writes "to" before a negative bound, so
                # that the dash is not read as its sign: this one says nothing of the rest.
                continue
            if (
                join in (",", ";")
                and found["percent"]
                and found["low"] in _LEVELS
                and not _LEVEL_BEFORE.search(text[max(0, found.start() - _BACK) : found.start()])
            ):
                continue  # "a confidence interval of 95%, 5% margin": the level, no bound
            typed = found["join"]
            use = _Use(place, found.start(), passage, found.end() - found.start(),
                       (found.span("join"),),
                       _negative(found["low"]) or _negative(found["high"]),
                       _doubtful(typed, found["low"]))  # fmt: skip
            joins.add(_JOINS["t" if join == "to" else join], use)

        for found in _PERCENT.finditer(text):
            use = _Use(place, found.start(), passage, found.end() - found.start(),
                       (found.span("gap"),))  # fmt: skip
            percents.add("spaced" if found["gap"] else "closed", use)

        for found in _UNIT.finditer(text):
            unit = found["unit"]
            if len(unit) == 1 and _a_name(text, found.start(), found.end()):
                continue  # "Figure 3g" is a panel and "compound 3g" a compound
            before = text[max(0, found.start() - _BACK) : found.start()]
            if unit == "g" and _a_force(found["value"], before):
                continue  # "centrifuged at 12,000g" is a force, not twelve kilograms
            between = found.end("value")
            use = _Use(place, found.start(), passage, found.end() - found.start(),
                       ((between, between),))  # fmt: skip
            closed.append((use, unit))

        for found in _NUMBER_THEN_WORD.finditer(text):
            word = found["word"]
            if word in _LOWER_UNITS:
                continue  # "30min": a unit, which `notation-unit` reports
            if _HEXADECIMAL.fullmatch(found.group(0)):
                continue  # "0xff", a number written in hexadecimal
            between = found.start("word")
            run_on.append(_Use(place, found.start(), passage, found.end() - found.start(),
                               ((between, between),)))  # fmt: skip
        for found in _WORD_THEN_NUMBER.finditer(text):
            between = _letters_before(found)
            run_on.append(_Use(place, found.start(), passage, found.end() - found.start(),
                               ((between, between),)))  # fmt: skip
    return read


def judge_notation(passages: Iterable[Passage]) -> Report:
    """The findings of the notation reading, over the whole manuscript in the order it is
    read. It takes no setting: the manuscript is held to itself, and to the SI Brochure
    for the space before a unit."""
    read = _read(passages)
    symbols, signs, joins, percents = read.symbols, read.signs, read.joins, read.percents
    closed, run_on = read.closed, read.run_on
    findings: list[Finding] = []

    for form, found, most, kept, level in _apart(symbols):
        first = min(found, key=lambda use: use.key)
        findings.append(
            _finding(
                "notation-p-symbol",
                first,
                f"the P value is written {_quoted(form)} {_times(len(found))}; the manuscript "
                f"writes {_quoted(most)} {_times(len(kept))}",
                _hint(level),
            )
        )

    lopsided = signs.forms.pop("lopsided", None)
    said = {
        "spaced": "a space on each side of it",
        "closed": "no space around it",
    }
    for form, found, most, kept, level in _apart(signs):
        first = min(found, key=lambda use: use.key)
        findings.append(
            _finding(
                "notation-sign-spacing",
                first,
                f"the sign after P or n has {said[form]} {_times(len(found))}, as in "
                f"{_quoted(first.words)}; the manuscript writes it with {said[most]} "
                f"{_times(len(kept))}, as in "
                + _quoted(min(kept, key=lambda use: use.key).words),
                _hint(level),
            )
        )
    if lopsided:
        first = min(lopsided, key=lambda use: use.key)
        findings.append(
            _finding(
                "notation-sign-spacing",
                first,
                f"the sign after P or n has a space on one side only {_times(len(lopsided))}, "
                f"as in {_quoted(first.words)}",
                "set a space on both sides or on neither, as the rest of the manuscript "
                "does. This is the first place it stands so",
            )
        )

    for form, found, most, kept, level in _apart(joins):
        first = min(found, key=lambda use: use.key)
        findings.append(
            _finding(
                "notation-interval",
                first,
                f"the two bounds of an interval are joined by {form} {_times(len(found))}, "
                f"as in {_quoted(first.words)}; the manuscript joins them by {most} "
                f"{_times(len(kept))}",
                _hint(level),
            )
        )

    stands = {"spaced": "after a space", "closed": "against its number"}
    for form, found, most, kept, level in _apart(percents):
        first = min(found, key=lambda use: use.key)
        findings.append(
            _finding(
                "notation-percent",
                first,
                f"'%' stands {stands[form]} {_times(len(found))}, as in {_quoted(first.words)}; "
                f"the manuscript sets it {stands[most]} {_times(len(kept))}",
                _hint(level),
            )
        )

    if closed:
        first, _ = min(closed, key=lambda item: item[0].key)
        shown = list(dict.fromkeys(use.words for use, _ in closed))[:EXAMPLES]
        findings.append(
            _finding(
                "notation-unit",
                first,
                f"a number runs into its unit {_times(len(closed))}: "
                + ", ".join(map(_quoted, shown)),
                "the SI Brochure sets a space between a number and its unit: '5 mg', "
                "'37 \N{DEGREE SIGN}C'. A non-breaking space keeps the two on one line. "
                "This is the first place one stands so; the count is of the whole "
                "manuscript",
            )
        )

    if run_on:
        run_on.sort(key=lambda use: use.key)
        first = run_on[0]
        shown = list(dict.fromkeys(use.words for use in run_on))[:EXAMPLES]
        findings.append(
            _finding(
                "notation-space-missing",
                first,
                f"a number and a word run together {_times(len(run_on))}: "
                + ", ".join(map(_quoted, shown)),
                "type a space between them: '0.41 points', '10 hours', '2nd year', "
                "'to +0.77'. This is the first place one stands so; the count is of the "
                "whole manuscript",
            )
        )

    return Report(
        tuple(findings),
        {
            "notation_p_values": symbols.uses,
            "notation_signs": signs.uses + len(lopsided or ()),
            "notation_intervals": joins.uses,
            "notation_percents": percents.uses,
            "notation_units_closed": len(closed),
            "notation_spaces_missing": len(run_on),
        },
    )


#: What an edit writes for the form the manuscript keeps: the spaces either side of a
#: sign, and the space before "%".
_SIGN_SPACES = {"spaced": (" ", " "), "closed": ("", "")}
_PERCENT_SPACE = {"spaced": " ", "closed": ""}
#: The joins a negative bound is not to be put after: its minus sign would read as one.
_DASHES = frozenset({"an en dash", "an em dash", "a hyphen"})


def notation_edits(passages: Iterable[Passage]) -> list[Edit]:
    """What the reading would change, at every place: each sign after P or n spaced as the
    manuscript spaces most of them, each interval joined and each "%" set as most are, and
    a space between a number and the unit or the word run into it. Nothing of the P's
    symbol, which is the journal's to say, nor where two forms are used as often; and no
    dash put before or after a negative bound, whose sign it would read as; and nothing of
    an interval whose hyphens may hold its high bound's sign, "-1.2--0.3" (round 1 of
    #636)."""
    read = _read(passages)
    edits: list[Edit] = []
    kept = _kept(read.signs, ("spaced", "closed"))
    if kept is not None:
        for form, uses in read.signs.forms.items():
            if form != kept:
                edits += _set(uses, "notation-sign-spacing", _SIGN_SPACES[kept])
    kept = _kept(read.joins)
    if kept is not None:
        join = _join_of(read.joins.forms[kept])
        for form, uses in read.joins.forms.items():
            if form != kept:
                allowed = [use for use in uses if not (kept in _DASHES and use.negative)]
                edits += _set(allowed, "notation-interval", (join,))
    kept = _kept(read.percents)
    if kept is not None:
        for form, uses in read.percents.forms.items():
            if form != kept:
                edits += _set(uses, "notation-percent", (_PERCENT_SPACE[kept],))
    edits += _set([use for use, _unit in read.closed], "notation-unit", (" ",))
    edits += _set(read.run_on, "notation-space-missing", (" ",))
    return edits


def _kept(family: _Family, among: tuple[str, ...] | None = None) -> str | None:
    """The form the manuscript keeps, of `among` where it is given: the one used most.
    None where it writes none of them, or two as often."""
    forms = [(form, uses) for form, uses in family.forms.items()
             if among is None or form in among]  # fmt: skip
    ranked = sorted(forms, key=lambda item: -len(item[1]))
    if not ranked or (len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1])):
        return None
    return ranked[0][0]


def _join_of(uses: list[_Use]) -> str:
    """What joins the bounds as the kept form is typed where it first stands, set evenly:
    " to ", ", ", and a dash with a space either side or none, so that a dash typed with a
    space on one side, "1.2 -3.4", is not copied to read as a minus sign (round 1 of #636)."""
    first = min(uses, key=lambda use: use.key)
    start, end = first.pieces[0]
    typed = first.passage.text[start:end]
    core = typed.strip()
    if core == "to":
        return " to "
    if core in (",", ";"):
        return core + " "
    return f" {core} " if typed[:1].isspace() and typed[-1:].isspace() else core


def _sure(use: _Use) -> bool:
    """Whether the reading is sure enough of what it read to edit it."""
    return not use.doubtful


def _set(uses: Iterable[_Use], code: str, news: tuple[str, ...]) -> list[Edit]:
    """An edit of each piece of each use to its counterpart in `news`, where it differs;
    none of a use the reading is not sure of."""
    edits = []
    for use in uses:
        if not _sure(use):
            continue
        within = (use.offset, use.offset + use.length)
        for (start, end), new in zip(use.pieces, news, strict=True):
            if use.passage.text[start:end] != new:
                edits.append(Edit(code, use.passage, start, end, new, within))
    return edits
