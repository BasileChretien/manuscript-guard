"""Generated manuscripts, vocabularies, lines and quotations.

A rule that reads text is right on the examples its author thought of. The independent
reviews of this repository kept finding the ones nobody thought of, by generating inputs:
vocabularies with manuscripts for G14, lines of Markdown signs for the TeX rule, typed
quotations for the literature chain. Each review built its generator from scratch and threw
it away. These are the generators, kept, and `tests/test_properties.py` and
`tests/test_differential.py` are what is held over them.

Three things make a generated test fit to run in CI, and all three are decided here, once.

**The same examples every time.** `generated` runs a test derandomized: Hypothesis seeds it
from the test's own source, so a commit that changed nothing draws what the last one drew.
That is not the whole of it. Hypothesis also takes about one value in twenty from the
constants it reads out of every local module that happens to be imported, so a test run
alone and the same test run after the rest of the suite drew different examples, and a
failure in CI did not come back when the test was run by itself. The pool is emptied below,
and `test_the_examples_do_not_depend_on_what_is_imported` holds that it stays so.

Seeded from its source, a test draws other examples when a word of it changes, docstring
included. That costs nothing where a test holds a rule over whatever is drawn. It matters
where a test draws few and is also held to what they are, as the twelve sessions of
`tests/test_generated_sessions.py`: that test names a seed (`pinned`) and is drawn from it.

**A bounded number of them.** Each test says how many it draws. No example has a deadline:
a time limit on one example fails a healthy rule on a busy machine, which this suite has
had enough of. What bounds the time is the count, the size of what is drawn, and the hard
limit `stopped_if_stuck` puts on the whole test.

**More when somebody wants more.** `MANUSCRIPT_GUARD_MORE_EXAMPLES=50` draws fifty times as
many, and `MANUSCRIPT_GUARD_SEED=7` draws them from another seed. That is the campaign a
reviewer used to write a script for: the suite's own generators, run longer, by whoever
wants to look harder at a change.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from functools import cache
from typing import Any, TypeVar

from hypothesis import HealthCheck, Phase, given, seed, settings
from hypothesis import strategies as st
from hypothesis.internal.conjecture import providers
from readings import INTERVALS, SAYS, TAGS

Test = TypeVar("Test", bound=Callable[..., Any])

#: How many times the stated number of examples to draw. A whole number, 1 or more.
MORE = "MANUSCRIPT_GUARD_MORE_EXAMPLES"
#: A whole number to seed the examples from, in place of the test's own source.
SEED = "MANUSCRIPT_GUARD_SEED"

# The pool of local constants, emptied. It is an internal of Hypothesis, which is why the
# version is pinned to the day in pyproject.toml: a release that moves it must fail here,
# where the reason is written, and not as examples that quietly differ again.
if not hasattr(providers, "_get_local_constants"):
    raise RuntimeError(
        "this Hypothesis has no `_get_local_constants` to replace, so the examples it draws "
        "would depend on which modules are imported; see tests/generated.py"
    )
_NO_CONSTANTS = providers.Constants()
providers._get_local_constants = lambda: _NO_CONSTANTS


def _whole(name: str, least: int) -> int | None:
    """The whole number in the environment under `name`, or None where it is not set."""
    typed = os.environ.get(name, "").strip()
    if not typed:
        return None
    if not typed.isascii() or not typed.isdigit() or int(typed) < least:
        raise ValueError(f"{name}={typed!r} is not a whole number of {least} or more")
    return int(typed)


def times() -> int:
    """How many times the stated number of examples this run draws."""
    return _whole(MORE, 1) or 1


def generated(
    examples: int, *, cut_down: bool = True, pinned: int | None = None
) -> Callable[[Test], Test]:
    """Run a `@given` test on `examples` generated inputs, the same ones on every run.
    With `cut_down` false it stops at the first input that fails and reports that one,
    without looking for a smaller.

    `pinned` is a seed to draw from in place of the test's own source. It is for a test
    that draws few inputs and is held to what they contain: seeded from its source, such a
    test draws others whenever a word of it changes, docstring included, and then fails on
    a rule nobody touched. `MANUSCRIPT_GUARD_SEED` still draws from another seed."""
    # Both read here and not when the test is wrapped, so that a value typed wrongly is
    # refused wherever `generated` is called, a test's own body included.
    chosen, count = _whole(SEED, 0), examples * times()
    drawn_from = pinned if chosen is None else chosen
    phases = tuple(Phase) if cut_down else (Phase.explicit, Phase.generate)

    def configure(test: Test) -> Test:
        configured = settings(
            max_examples=count,
            derandomize=drawn_from is None,
            deadline=None,
            # The one health check that reads a clock. The others say a strategy is wrong.
            suppress_health_check=[HealthCheck.too_slow],
            print_blob=True,
            phases=phases,
        )(test)
        # Either way nothing an earlier run failed on is kept and played first: Hypothesis
        # keeps no examples for a derandomized test, nor for one given a seed.
        return configured if drawn_from is None else seed(drawn_from)(configured)

    return configure


def holds(
    examples: int, *given_each: st.SearchStrategy[Any], pinned: int | None = None
) -> Callable[[Test], Test]:
    """A property: the test is run on `examples` inputs, each drawn from `given_each`.

    The test it returns has a twin, `at_first_failure`, on the same inputs: for the test
    that breaks a rule and has to see this property fail. Looking for the smallest failing
    input is most of the time a failure costs, and that test wants only the failure.

    `pinned` is as `generated` has it."""

    def wrap(test: Test) -> Test:
        held = generated(examples, pinned=pinned)(given(*given_each)(test))
        held.at_first_failure = generated(examples, cut_down=False, pinned=pinned)(
            given(*given_each)(test)
        )
        return held

    return wrap


# ------------------------------------------------------------------------------- words

#: Words that are nobody's term, no abbreviation, and spelt one way in both Englishes.
#: `tests/test_properties.py` holds them to that against the lists the gates read.
FILLER = (
    "reports", "records", "were", "was", "are", "included", "excluded", "after", "before",
    "review", "the", "of", "and", "in", "by", "with", "from", "each", "both", "cohort",
    "events", "observed", "among", "exposed", "women", "men", "older", "younger", "data",
    "site", "sites", "week", "weeks", "shows", "given", "found", "study", "period", "onset",
    "date", "missing", "second", "reader", "first", "result",
)  # fmt: skip

#: Terms a vocabulary is made of. Singular beside plural, a term inside a longer one, an
#: abbreviation beside the word it spells, a term with a mark of emphasis inside it, one
#: with a hyphen, a Greek abbreviation: each is here because a review found a reading of
#: G14 that got it wrong.
TERMS = (
    "subject", "subjects", "patient", "patients", "participant", "participants",
    "adverse drug reaction", "drug reaction", "liver injury", "liver injury score",
    "in vitro", "in-vitro", "OR", "ORs", "CI", "cis", "WHO", "who", "phase II trial",
    "odds ratio", "CYP2D6*4", "R_0", "SARS-CoV-2", "SARS-Cov-2", "Covid-19", "COVID-19",
    "follow up", "follow-up", "case-control", "\N{GREEK CAPITAL LETTER ALPHA}"
    "\N{GREEK CAPITAL LETTER SIGMA}", "\N{MICRO SIGN}g",
)  # fmt: skip

#: Spaces a manuscript holds that are not the space bar's.
SPACES = (
    "\t", "\N{NO-BREAK SPACE}", "\N{THIN SPACE}", "\N{NARROW NO-BREAK SPACE}", "\x0c", "\x0b",
    "\N{LINE SEPARATOR}",
)  # fmt: skip


def renderings(term: str) -> tuple[str, ...]:
    """`term` as a manuscript may write it: in another case, in the plural, with a hyphen,
    a space or a line break between its words, in italics."""
    words = term.replace("-", " ").split(" ")
    return tuple(
        sorted(
            {
                term,
                term.capitalize(),
                term.upper(),
                term.lower(),
                f"{term}s",
                f"{term.upper()}S",
                " ".join(words),
                "-".join(words),
                "\n".join(words),
                " ".join(word.capitalize() for word in words),
                f"*{term}*",
                f"_{term}_",
            }
        )
    )


# -------------------------------------------------------------------------- manuscripts

_NUMBERS = (
    "12", "3.4", "95%", "0.05", "1,234", "13.42", "2019", "p < 0.05", "(95% CI 1.2 to 3.4)",
    "10^6^", "CO~2~", "HbA~1c~", "m^2^", "n = 412", "-0.5", "\N{MINUS SIGN}1.0", "1/2",
    "\N{VULGAR FRACTION ONE HALF}", "3\N{EN DASH}5", "4100", "COVID-19", "CYP3A4",
    "(n = 412)", "3.84).", "[12]", "1,3-BDG", "Table 2", "5 mg/kg",
)  # fmt: skip

_MACHINERY = (
    "`code 3.84`", "``a ` b``", "[@smith2020]", "[@smith2020, p. 33]", "@jones2019",
    "[see 42; @key]", "[text](https://example.org/a_b)", "[text][label]",
    "<https://example.org>", "{{results.cohort.n_reports}}", "{{lit.incidence}}",
    "{{ results.x }}", "[^1]", "<!-- hidden 7 -->", "<span class=\"x\">", "</span>",
    "$x = 1$", "$\\beta$", "![a figure](fig.png)", "{.unnumbered}", "{#sec:one}",
    "\\>", "\\<", "\\*", "\\$", "doi:10.1000/xyz123", "www.example.org/a",
)  # fmt: skip

_ABBREVIATIONS = (
    "ROR", "(ROR)", "reporting odds ratio (ROR)", "CI", "ORs", "WHO", "MedDRA",
    "confidence interval (CI)", "II", "DNA",
)  # fmt: skip

# Several words at one draw, so that a manuscript of thirty pieces has sentences in it.
_PHRASES = (
    "reports were included after review ", "the cohort of exposed women ",
    "each site shows the onset date ", "records with a missing date were excluded ",
    "Both readers found the same result. ", "Events were observed among older men. ",
    "data from the first week of the study period ", "The second reader was given each record. ",
)  # fmt: skip

# What ends a sentence or a paragraph.
_BREAKS = ("\n\n", "\n\n", "\n\n", "\n", "\n", ".\n\n", ". ", ". ", ", ", "; ", ": ", "(", ") ")

_FENCE = "`" * 3

# What opens a block and what closes one, each with the line break it needs before it.
# Some have a blank line before them and some have not, which is where a block that cannot
# interrupt a paragraph is read as one that can. Nothing pairs an opener with its closer:
# a listing left open and a comment never closed are among what is drawn.
_OPENERS = (
    "\n\n# ", "\n\n## ", "\n# ", "\n\n####### ", "\n\n#", "\n=====\n\n", "\n--\n\n", "\n\n> ",
    "\n> ", "\n>", "\n\n- ", "\n- ", "\n\n1. ", "\n2) ", "\n\n| ", "\n\n    ", f"\n\n{_FENCE}\n",
    f"\n{_FENCE}\n\n", f"\n\n{_FENCE}{{.r}}\n", f"\n{_FENCE * 2}\n", "\n\n~~~\n", "\n~~~\n\n",
    "\n\n<!--\n", "\n-->\n\n", "\n\n::: {.note}\n", "\n:::\n\n", "\n\n$$\n", "\n$$\n\n",
    "\n\n<div>\n", "\n</div>\n\n", "\n\n---\n\n", "\n\n***\n\n", "\n\n- - -\n\n", "\n___\n",
    "\n\n: ", "\n\n[^1]: ", "\n\n[label]: https://example.org ", "\n:   ", "\n \n",
)  # fmt: skip

# Whole blocks, written as an author writes them.
_WHOLE = (
    "\n\n# Methods\n\n",
    "\n\n# Results\n\n",
    "\n\n# Abstract\n\n",
    "\n\n# References\n\n",
    "\n\n## Statistical analysis\n\n",
    # Sections whose wording is somebody else's: G14 reports no undefined abbreviation
    # in them and does not read their spelling.
    "\n\n# Acknowledgements\n\n",
    "\n\n## Funding\n\n",
    f"\n\n{_FENCE}r\nset.seed(20240115)\nx <- 1.96\n{_FENCE}\n\n",
    "\n\n<!--\nA note of 12 words.\n-->\n\n",
    "\n\n| Group | Reports |\n|---|---|\n| exposed | 412 |\n\n",
    "\n\nAge  Group\n-----  -----\n> 65  12 subjects\n-----  -----\n\n",
    "\n\n---\nkeywords: [liver injury, 2019]\n---\n\n",
    "\n\n---\nabstract: |\n  Of 4100 reports, half were excluded.\n...\n\n",
    "\n\nTerm\n:   its definition in 3 words\n\n",
    # A line that opens with `>` in each place one can stand: after a blank line, under a
    # heading, a rule and a fenced div's line, where it is a quotation, and under a
    # paragraph's line, where it is the paragraph's.
    "\n\n> The subjects were told of 12 events.\n> A second quoted line.\n\n",
    "\n\n## Results in patients\n> Quoted under a heading.\n\n",
    "\n\n---\n> Quoted under a rule.\n\n",
    "\n\n::: {.note}\n> Quoted in a div.\n:::\n\n",
    "\n\nThe limit was passed where ALT was\n> 3 times its upper bound.\n\n",
)

_HEADERS = (
    "---\ntitle: A study of 412 reports\n---\n\n",
    "---\ntitle: \"A <!-- title\"\nabstract: |\n  Of 4100 reports, half were excluded.\n---\n\n",
    "---\nauthor: [one, two]\n...\n\n",
    "---\ntitle: [unclosed\n---\n\n",
)


def _spaced(pieces: Iterable[str]) -> tuple[str, ...]:
    return tuple(f"{piece} " for piece in pieces)


def _in_a_row(pool: tuple[str, ...], *, few: int, many: int) -> st.SearchStrategy[str]:
    """Pieces of `pool` one after another: up to `few` of them, or, twice as often, from
    `few` to `many`.

    A list drawn in one go is five long on average, however long it is allowed to be, and
    five pieces are a sentence: nothing in it is far enough from anything else for two
    rules to meet. A list that must be long cannot be cut down to the one piece that
    fails. So both are drawn, the long one more often, and a failure found in a long one
    is cut down into a short one."""
    piece = st.sampled_from(pool)
    short = st.lists(piece, max_size=few)
    long = st.lists(piece, min_size=few, max_size=many)
    return st.one_of(short, long, long).map("".join)


# The signs the readers look for, bare: what a line is made of when nothing about it is
# meant. In a manuscript they are what a scanner mishandles; alone (`signs`) they are text
# nobody would write, which a gate still has to come back from.
_SIGNS = (
    "`", _FENCE, "~~~", "<!--", "-->", "--", "$", "$$", "\\", "[", "]", "(", ")", "{", "}",
    "{{", "}}", "@", "^", "~", "*", "_", ">", "#", "-", "=", ":", ":::", "|", "<", "&",
    ";", "\n", "\n\n", " ", "    ", "\t", "\r\n", "word", "Word", "AB", "12", "0.5", "%",
    "\N{NO-BREAK SPACE}", "\x0c", "\N{GREEK CAPITAL LETTER SIGMA}", "\N{LATIN SMALL LIGATURE FI}",
    "é", "\N{COMBINING ACUTE ACCENT}", "---", "...", "1.", "</div>", "<div>", "[^1]:", "](",
    "{.x}", "!", "'", '"', "\N{CJK UNIFIED IDEOGRAPH-4E2D}", "\U0001f600",
)  # fmt: skip


@cache
def _pool(terms: tuple[str, ...]) -> tuple[str, ...]:
    """Everything a manuscript is drawn from, each piece as often as it should come up:
    words most of all, then what ends a sentence, then numbers, citations, bindings and
    code, then what opens a block, and the bare signs once each."""
    return (
        *_spaced(FILLER) * 2,
        *FILLER,
        *_spaced(word.capitalize() for word in FILLER),
        *_PHRASES * 4,
        *_spaced(written for term in terms for written in renderings(term)),
        *_spaced(_NUMBERS) * 2,
        *_spaced(_MACHINERY) * 2,
        *_spaced(_ABBREVIATIONS) * 2,
        *_BREAKS * 6,
        *_OPENERS * 3,
        *_WHOLE * 3,
        *SPACES,
        *_SIGNS,
    )


def texts(terms: tuple[str, ...] = ()) -> st.SearchStrategy[str]:
    """A manuscript file, with `terms` written into it in every way a term is written.

    Drawn piece by piece from one pool, as the reviews drew their lines from an alphabet,
    and not block by block from a grammar of Markdown. A grammar writes only what its
    author knew to be a block; the pool writes a heading under a paragraph's last line and
    a quotation mark inside a listing nobody closed, which is where the readings have gone
    wrong. It is also one draw for each piece, where a grammar took twenty. Some open with
    a header of settings, and some have the line ends of Windows.

    One strategy, and not a choice between this and `signs`: asked for two of one and one
    of the other, Hypothesis drew two of the other."""

    def file(drawn: tuple[str, str, str]) -> str:
        header, body, line_end = drawn
        return (header + body.lstrip("\n")).replace("\n", line_end)

    return st.tuples(
        st.sampled_from(("", "", "", "", *_HEADERS)),
        _in_a_row(_pool(terms), few=20, many=70),
        st.sampled_from(("\n", "\n", "\n", "\r\n")),
    ).map(file)


def signs() -> st.SearchStrategy[str]:
    """Text nobody would write: the signs of Markdown in any order."""
    return _in_a_row(_SIGNS, few=12, many=50)


def bindings() -> st.SearchStrategy[str]:
    """A manuscript with a binding where a line begins: after a line end, of Windows or
    not, and in some texts as the first thing in the file.

    A binding there stands exactly at the start of its line, the one place where a lookup
    among the starts of the lines can be a line out. Left to chance, a manuscript seldom
    holds one: under 27 of the seeds 0 to 299, a rule that put such a binding on the line
    before was wrong in none of a property's 200 examples, and went unnoticed. Planted, the
    fewest examples that show that rule under any of those seeds is 131 of 200."""
    written = ("{{results.cohort.n_reports}}", "{{ lit.incidence }}", "{{oops}}", "{{lit.cut}")
    opening = tuple(f"{end}{binding}" for end in ("\n", "\r\n") for binding in written)
    planted = st.sampled_from(("", *written)), st.sampled_from(("", *opening * 2))
    return st.tuples(planted[0], texts(), planted[1], texts()).map("".join)


# What stands between two bounds of an interval: words, and a stop with a space after it,
# a line break, or nothing.
_BETWEEN = (
    " to ", " to ", " and ", ", ", "; ", " (95% CI ", "; 90% CI ", ") ", ". ", ". ", ".\n",
    ".\r\n", ".\N{NO-BREAK SPACE}", ".", "!", "? ", "\n", "\n\n", " 3.5 ", " e.g. ",
    "It ran ", "The upper bound was ", " <!-- ", " --> ",
)  # fmt: skip


def intervals() -> st.SearchStrategy[str]:
    """A text that quotes the bounds of `INTERVALS` in any order and in any sentence, with
    an estimate that is no bound and a binding that resolves to nothing among them.

    Most texts also hold three sentences that chance draws too seldom, with shorter runs
    of the rest between them than a text had before they were planted, so that it stays
    about as long. The first, in six texts of seven, has a stop typed against its upper
    bound: that stop ends a sentence for a search that stops at the binding and none for
    one that reads the whole text, and left to chance it changed a finding in so few texts
    that a reading which lost it went unnoticed under three seeds of twelve. The second,
    in twelve texts of thirteen, quotes every interval backwards, in each order they can
    be quoted in: the findings have to come in that order, which a set keeps for few of
    the six. The third, in six of seven, quotes an interval backwards with a comment
    between its bounds that holds a stop, which ends no sentence."""
    # Imported here, not at the top, to keep clear of the import block other branches edit.
    from itertools import permutations

    bounds = _bounds()
    quoted = (*(bound for both in bounds for bound in both), "{{results.ror.point}}")
    stopped = tuple(f". It ran.{high} to {low}. " for low, high in bounds)
    backwards = tuple(
        ". It ran " + ", ".join(f"{high} to {low}" for low, high in order) + ". "
        for order in permutations(bounds)
    )
    noted = tuple(f". It ran {high} <!-- was 7.02. --> to {low}. " for low, high in bounds)
    around = _in_a_row((*quoted * 3, "{{results.absent}}", *_BETWEEN), few=4, many=20)
    planted = [st.sampled_from(("", *kind * 2)) for kind in (stopped, backwards, noted)]
    return st.tuples(around, planted[0], around, planted[1], around, planted[2]).map("".join)


def _bounds() -> list[tuple[str, str]]:
    """The lower and the upper bound of each interval of `INTERVALS`, as bindings."""
    return [
        (f"{{{{results.{low}}}}}", f"{{{{results.{high}}}}}")
        for _estimate, _level, low, high in INTERVALS
    ]


@st.composite
def commented(draw: st.DrawFn) -> tuple[str, str]:
    """A text that quotes the bounds of intervals with HTML comments typed into it, and
    the same text with white space where each comment stands and its line breaks kept:
    what G2 has to read the first as. A comment holds what the text around it holds,
    stops and bounds among it, and nothing that would end it before its own `-->`.

    Somewhere in each, an interval is quoted backwards with a comment between its bounds
    that holds two stops. Left to chance, a comment changed a finding in so few texts that
    a reading which read the comments went unnoticed under six seeds of twelve."""
    quoted = [bound for both in _bounds() for bound in both]
    said = _in_a_row((*quoted * 3, *(p for p in _BETWEEN if "--" not in p)), few=3, many=8)
    parts = draw(st.lists(st.tuples(st.booleans(), said), max_size=6))
    low, high = draw(st.sampled_from(_bounds()))
    at = draw(st.integers(0, len(parts)))
    between = [(False, f". It ran {high} "), (True, "was 7.02. Check."), (False, f" to {low}. ")]
    parts[at:at] = between
    typed = [f"<!-- {part} -->" if hidden else part for hidden, part in parts]
    blanked = [
        "".join(c if c == "\n" else " " for c in part) if hidden else part
        for (hidden, _said), part in zip(parts, typed, strict=True)
    ]
    return "".join(typed), "".join(blanked)


# ------------------------------------------------------------------------ vocabularies


#: Entries that agree with one another, whichever of them a vocabulary holds.
AGREED = (
    {"use": "participants", "avoid": ["subjects", "patients"]},
    {"use": "adverse drug reaction", "avoid": ["side effect", "drug reaction"]},
    {"use": "odds ratio", "avoid": ["OR"]},
    {"use": "in vitro", "avoid": ["test tube"]},
    {"use": "liver injury score", "avoid": ["hepatic score"]},
    {"use": "COVID-19", "avoid": ["Covid-19"]},
    {"use": "follow-up", "avoid": ["CYP2D6*4", "R_0"]},
)


def vocabularies() -> st.SearchStrategy[list[dict[str, Any]]]:
    """Entries of `language: vocabulary:` as the schema accepts them. Two in three agree
    with one another, so that their terms are looked for. The third need not: what the
    entries disagree about is the other half of what the reading reports."""
    term = st.sampled_from(TERMS)
    entry = st.fixed_dictionaries(
        {"use": term, "avoid": st.lists(term, min_size=1, max_size=3)}
    )
    agreed = st.lists(st.sampled_from(AGREED), max_size=4, unique_by=lambda e: e["use"])
    return st.one_of(agreed, agreed, st.lists(entry, max_size=4))


# ------------------------------------------------------------------------------- lines

# One line of a title or a keyword, for the rule that reads TeX outside maths: what opens
# maths and what only looks as if it did, the signs past which pandoc reads none, a
# subscript and a superscript, a character reference in each of its spellings.
_LINE = (
    "\\gamma", "\\alpha", "\\textit{in vivo}", "\\pm", "\\Users", "\\", "\\\\", "\\ ", "\\$",
    "\\~", "\\^", "$", "$", "$$", "~", "^", "`", "<", ">", "[", "]", "@", "{", "}", "%",
    "&bsol;", "&amp;", "&#92;", "&#x5c;", "&#13;", "&alpha;", "&", ";", "bsol;", "gamma",
    "IFN-", "TNF", "release", "assays", "x", "5", "50,000", " ", " ", " ", "\t",
    "\N{NO-BREAK SPACE}", "\N{THIN SPACE}", "*", "\"", "é", "\U0002ebf0",
    "$\\gamma$", "$\\beta$1", "$p \\leq$", "$ \\gamma $", "$5", "[18F]", "CD4^+^", "CO~2~",
)  # fmt: skip


def lines() -> st.SearchStrategy[str]:
    """One line as `paper.yaml` holds a title, a short title or a keyword."""
    return _in_a_row(_LINE, few=6, many=18)


# -------------------------------------------------------------------------- quotations

#: What a publisher's page or a PDF holds where a person copying the sentence types
#: something else, with what they type.
TYPOGRAPHY = {
    "\N{LEFT SINGLE QUOTATION MARK}": "'",
    "\N{RIGHT SINGLE QUOTATION MARK}": "'",
    "\N{LEFT DOUBLE QUOTATION MARK}": '"',
    "\N{RIGHT DOUBLE QUOTATION MARK}": '"',
    "\N{EN DASH}": "-",
    "\N{EM DASH}": "-",
    "\N{MINUS SIGN}": "-",
    "\N{HYPHEN}": "-",
    "\N{NON-BREAKING HYPHEN}": "-",
    "\N{NO-BREAK SPACE}": " ",
    "\N{THIN SPACE}": " ",
    "\N{NARROW NO-BREAK SPACE}": " ",
    "\N{LATIN SMALL LIGATURE FI}": "fi",
    "\N{LATIN SMALL LIGATURE FL}": "fl",
    "\N{LATIN SMALL LIGATURE FF}": "ff",
    "\N{LATIN SMALL LIGATURE FFI}": "ffi",
    "\N{LATIN SMALL LIGATURE FFL}": "ffl",
    "\N{HORIZONTAL ELLIPSIS}": "...",
}

SOURCE_WORDS = (
    "the", "reporting", "odds", "ratio", "for", "hepatic", "events", "was", "effect",
    "coefficient", "different", "efficacy", "per", "100", "000", "person-years", "13.42",
    "3.4", "0.42", "(95%", "CI", "9.10", "to", "19.80)", "0.21", "0.63", "14", "412",
    "e\N{LATIN SMALL LIGATURE FF}ect", "coe\N{LATIN SMALL LIGATURE FFI}cient",
    "signi\N{LATIN SMALL LIGATURE FI}cant", "0.21\N{EN DASH}0.63", "\N{MINUS SIGN}0.5",
    "\N{LEFT DOUBLE QUOTATION MARK}serious\N{RIGHT DOUBLE QUOTATION MARK}",
    "patients\N{RIGHT SINGLE QUOTATION MARK}", "\N{HORIZONTAL ELLIPSIS}", "non\N{HYPHEN}serious",
    "\N{GREEK CAPITAL LETTER ALPHA}\N{GREEK CAPITAL LETTER SIGMA}",
    "\N{LEFT SINGLE QUOTATION MARK}probable\N{RIGHT SINGLE QUOTATION MARK}",
    "events\N{EM DASH}all", "non\N{NON-BREAKING HYPHEN}fatal",
    "in\N{LATIN SMALL LIGATURE FL}ammation", "ba\N{LATIN SMALL LIGATURE FFL}ed",
)  # fmt: skip


#: What stands between two words of a source.
SOURCE_GAPS = (
    " ", " ", " ", " ", "\n", "  ", " \n ", "\N{NO-BREAK SPACE}", "\N{THIN SPACE}",
    "\N{NARROW NO-BREAK SPACE}",
)  # fmt: skip


def sources() -> st.SearchStrategy[str]:
    """The text of a stored source, as it is read from a page or out of a PDF."""
    return st.lists(
        st.tuples(st.sampled_from(SOURCE_WORDS), st.sampled_from(SOURCE_GAPS)),
        min_size=1,
        max_size=14,
    ).map(lambda drawn: "".join(word + gap for word, gap in drawn))


def typed(copied: str) -> str:
    """`copied` as a person types it from the page: the keyboard's characters for the
    typographer's, and one space wherever the page has white space."""
    for printed, keyed in TYPOGRAPHY.items():
        copied = copied.replace(printed, keyed)
    return " ".join(copied.split())


@st.composite
def quotations(draw: st.DrawFn) -> tuple[str, str]:
    """A source, and some whole words of it in a row."""
    source = draw(sources())
    words = source.split()
    first = draw(st.integers(0, len(words) - 1))
    last = draw(st.integers(first, len(words) - 1))
    return source, " ".join(words[first : last + 1])


# ---------------------------------------------------------------------------- spellings

#: Words one English writes and the other does not, with a name's capital, in capitals,
#: and inside an identifier: what the spelling reading must tell apart.
SPELT = (
    "color", "colour", "center", "centre", "tumor", "tumour", "analyzed", "analysed",
    "organization", "organisation", "randomized", "randomised", "program", "Color",
    "COLOR", "color_2", "color.csv", "info@color-lab.org",
)  # fmt: skip


#: A statistic in each of the ways one is written, typed and bound, and a number with
#: its unit: what the notation reading must count apart.
NOTATED = (
    "P = 0.03", "p=0.04", "*P* < 0.001", "p-value", "n = 12", "n=3", "N= 40",
    "95% CI 1.2 to 3.4", "95% CI 1.2-3.4", "(95% CI {{results.low}} to {{results.high}})",
    "P = {{results.p}}", "5%", "5 %", "5mg", "5 mg", "{{results.dose}}mL",
    "(95% CI 80%-93%; 12 studies)", "2500g", "16,000g", "(CI 95%-0.3 to 0.4)",
)  # fmt: skip


# ---------------------------------------------------------------------- what an edit holds

#: A binding, a citation and a number in each of the ways one is written: what `reworded`
#: holds to its place.
HELD = (
    "{{results.ror.point}}", "{{ results.n.total }}", "{{lit.agency.count}}", "[@smith2020]",
    "[@smith2020; @lee2019, p. 12]", "@doe2018", "-@lee2019", "3.84", "-0.5", "1,200", "77",
    "(n = 12)", "5 %",
)  # fmt: skip


@st.composite
def edits(draw: st.DrawFn) -> tuple[str, str]:
    """A manuscript and what an edit made of it: the same text, one of its paragraphs moved
    to the end, one taken out, or another manuscript altogether."""
    before = draw(texts(HELD))
    kind = draw(st.sampled_from(("the same", "moved", "cut", "another")))
    if kind == "the same":
        return before, before
    if kind == "another":
        return before, draw(texts(HELD))
    paragraphs = before.split("\n\n")
    at = draw(st.integers(0, len(paragraphs) - 1))
    if kind == "moved":
        paragraphs.append(paragraphs.pop(at))
    else:
        del paragraphs[at]
    return before, "\n\n".join(paragraphs)


# ------------------------------------------------------------------- a project's settings

# Lines typed at the end of a new project's `paper.yaml`. Half are settings as the schema
# takes them. The other half are what a hand makes of them: a word where a list belongs, a
# number where a word does, a list left open. `check` reports those and reads on.
_SETTINGS = (
    "",
    "",
    "language:\n  vocabulary:\n    - use: participants\n      avoid: [subjects, patients]\n",
    "language:\n  vocabulary:\n    - use: \"OR\"\n      avoid: [odds ratio]\n"
    "    - use: participant\n      avoid: [subject]\n",
    "language:\n  known_abbreviations: [\"ROR\", \"CI\"]\n  accepted_spellings: [color]\n",
    "language:\n  vocabulary:\n    - use: subjects\n      avoid: [subjects]\n",
    "language: 5\n",
    "language: [a, b]\n",
    "language:\n",
    "language:\n  vocabulary: subjects\n",
    "language:\n  vocabulary:\n    - use: 5\n      avoid: x\n    - [a]\n    - use: on\n",
    "language:\n  known_abbreviations: {a: b}\n  accepted_spellings: [1, two words]\n",
    "language: [unclosed\n",
    "keywords: 2019\n",
    "keywords: [liver injury, 'TNF$\\alpha$', 'IFN-\\gamma release']\n",
    "short_title: \"Injury in 412 reports\"\n",
    "terms: [\"CYP3A4\", \"COVID-19\"]\n",
    "conventions:\n  - pattern: '\\b412\\b'\n    why: the size of the cohort\n",
    "target_journal: journal-of-examples\n",
)


def settings_typed() -> st.SearchStrategy[str]:
    return st.sampled_from(_SETTINGS)


# ----------------------------------------------------------------------------- sessions


@st.composite
def sessions(draw: st.DrawFn) -> dict[str, Any]:
    """A paper, what a co-author did to it in Word, and what its author did meanwhile.

    The paper is three to seven blocks that read alike, each a paragraph, a heading, a
    quotation, a list item, a table's caption, a line block or a div, and each with a word
    of its own (`tests/readings.py` has what they say). The co-author rewords or deletes one
    to four of them. In some sessions the author has since reworded a block in the source,
    removed one or added a paragraph, and the import has to be forced. One in three is
    what is asked for; a choice between strategies is not drawn in the proportions it is
    written in, and how many of a given twelve it is changes with the twelve."""
    tags = draw(st.lists(st.sampled_from(TAGS), min_size=3, max_size=7, unique=True))
    kind = st.sampled_from(("paragraph",) * 4 + ("second paragraph",) * 2 + tuple(SAYS))
    did = st.sampled_from(("reworded",) * 4 + ("deleted", "deleted and gone"))
    touched = draw(st.lists(st.sampled_from(tags), min_size=1, max_size=4, unique=True))
    since = st.tuples(
        st.sampled_from(("reworded", "removed", "added above")), st.sampled_from(tags)
    ).map(list)
    return {
        "blocks": [{"tag": tag, "kind": draw(kind)} for tag in tags],
        "in_word": [[tag, draw(did)] for tag in touched],
        "since": draw(st.one_of(st.none(), st.none(), since)),
    }


# ------------------------------------------------------------------------------ inputs


def _quotation_asked(drawn: tuple[tuple[str, str], str, str]) -> dict[str, str]:
    """A source and a quotation of it: as it stands there, as a person types it, or with
    a word the source does not have, which is the quotation that must not be found."""
    (source, quote), how, value = drawn
    if how == "typed":
        quote = typed(quote)
    elif how == "misquoted":
        quote = f"{quote} similar"
    return {"source": source, "quote": quote, "value": value}


#: What each reading of `tests/readings.py` is given, by the reading's name.
INPUTS: dict[str, st.SearchStrategy[Any]] = {
    "checker sentences": texts(),
    "mask": texts(TERMS),
    "hidden": texts(TERMS),
    "own words": texts(TERMS),
    "spans": texts(),
    "sections": texts(),
    "numbers": st.fixed_dictionaries(
        {
            "text": texts(),
            "terms": st.lists(
                st.sampled_from(("CYP3A4", "COVID-19", "CO2", "HbA1c", "1,3-BDG")), max_size=2
            ),
        }
    ),
    "interval order": intervals(),
    "vocabulary": st.fixed_dictionaries({"text": texts(TERMS), "entries": vocabularies()}),
    "spelling": st.fixed_dictionaries(
        {
            "text": texts(SPELT),
            "variant": st.sampled_from(("en-GB", "en-US")),
            "accepted": st.lists(st.sampled_from(("color", "Tumour", "centre")), max_size=2),
        }
    ),
    "notation": texts(NOTATED),
    "abbreviations": st.fixed_dictionaries(
        {"text": texts(), "known": st.lists(st.sampled_from(("ROR", "CI", "II")), max_size=2)}
    ),
    "tex outside maths": lines(),
    "title": lines(),
    "quotation": st.tuples(
        quotations(),
        st.sampled_from(("as it stands", "typed", "typed", "misquoted")),
        st.sampled_from(("3.4", "13.42", "14", "0.42", "-0.5", "CI")),
    ).map(_quotation_asked),
    "check": st.fixed_dictionaries(
        {
            "text": texts(TERMS + SPELT),
            "settings": settings_typed(),
            "stage": st.sampled_from(("design", "drafting", "submission")),
        }
    ),
    "import": sessions(),
    "reworded": edits(),
}
