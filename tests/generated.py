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

import math
import os
from collections.abc import Callable, Iterable
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal
from fractions import Fraction
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

#: Pointer words and the numbers after them: a pointer, a list of them, and a count after a
#: word that points at nothing G2 can check, which only looks like one.
POINTED = (
    "Table 2", "Tables 1 and 2", "Figures 2-4", "Figure S1", "step 3", "step 1204", "Box 47",
    "item 25", "panel 2A",
)  # fmt: skip

#: The files of each document a generated paper places its tables and figures in, in the order
#: the build prints them: `main.md` first and the rest by name, so `1_methods.md` prints after
#: `main.md` though its path sorts before it; the supplement's by name.
DISPLAY_FILES = {
    False: ("main.md", "1_methods.md", "3_results.md"),
    True: ("supplementary/S1.md", "supplementary/S2.md"),
}
#: The words a num binding of each kind of each document may follow, the number it prints
#: holding the supplement's `S`.
_NUM_WORDS = {
    (False, "table"): ("Table",),
    (False, "figure"): ("Figure", "Fig."),
    (True, "table"): ("Table", "Supplementary Table"),
    (True, "figure"): ("Figure", "Supplementary Figure"),
}


@st.composite
def numbered_displays(
    draw: st.DrawFn,
) -> tuple[dict[str, str], dict[tuple[str, int], str], set[tuple[str, str, int]]]:
    """Tables and figures placed by their bindings across the files of the main text and of
    the supplement, in a drawn order, each cited just before it is placed by a ref or by a
    num after its word, and the main text's tables listed once more, by num, at the end of
    `main.md`. Four pointers are planted there too, one of each kind in every example, in a
    drawn order: a ref to a key nothing places, a ref that calls a table a figure, a num after
    a figure's word, and a num after the supplement's words. `main.md` and `1_methods.md`
    each place one of the main text's tables, so that numbering them in the order of their
    paths would give the two the other's number, and the supplement places a table.

    Returns each file's text by its path under `manuscript/`; what each ref and num binding
    prints, by its file and the offset it starts at; and the findings the planted pointers
    make, by code, file and line."""

    def words() -> str:
        return " ".join(draw(st.lists(st.sampled_from(FILLER), min_size=1, max_size=4)))

    counts = {
        (False, "table"): draw(st.integers(2, 4)),
        (False, "figure"): draw(st.integers(0, 2)),
        (True, "table"): draw(st.integers(1, 2)),
        (True, "figure"): draw(st.integers(0, 2)),
    }
    keys = iter(draw(st.permutations([f"k{index}" for index in range(12)])))
    placed: dict[str, list[tuple[str, str]]] = {
        file: [] for files in DISPLAY_FILES.values() for file in files
    }
    for (supplementary, kind), count in counts.items():
        files = DISPLAY_FILES[supplementary]
        for index in range(count):
            spread = not supplementary and kind == "table" and index < 2
            file = files[index] if spread else draw(st.sampled_from(files))
            placed[file].append((kind, next(keys)))
    numbers: dict[tuple[str, str], tuple[bool, int]] = {}
    seen: dict[tuple[bool, str], int] = {}
    for supplementary, files in DISPLAY_FILES.items():
        for file in files:
            placed[file] = draw(st.permutations(placed[file]))
            for kind, key in placed[file]:
                number = seen[supplementary, kind] = seen.get((supplementary, kind), 0) + 1
                numbers[kind, key] = (supplementary, number)

    def alone(kind: str, key: str) -> str:
        supplementary, number = numbers[kind, key]
        return f"{'S' if supplementary else ''}{number}"

    def whole(kind: str, key: str) -> str:
        return f"{kind.capitalize()} {alone(kind, key)}"

    texts: dict[str, str] = {}
    prints: dict[tuple[str, int], str] = {}
    planted: set[tuple[str, str, int]] = set()

    def write(file: str, parts: list[tuple[str, str | None, str | None]]) -> None:
        """`parts` as (text, binding, what it prints): each binding's offset recorded."""
        out = ""
        for text, binding, printed in parts:
            out += text
            if binding is not None:
                prints[file, len(out)] = str(printed)
                out += binding
        texts[file] = out

    for supplementary, files in DISPLAY_FILES.items():
        for file in files:
            parts: list[tuple[str, str | None, str | None]] = [("# Results\n\n", None, None)]
            for kind, key in placed[file]:
                how = draw(st.sampled_from(("ref", "num")))
                lead = f"{words().capitalize()} in "
                if how == "ref":
                    parts.append((lead, f"{{{{ref.{kind}.{key}}}}}", whole(kind, key)))
                else:
                    word = draw(st.sampled_from(_NUM_WORDS[supplementary, kind]))
                    parts.append((f"{lead}{word} ", f"{{{{num.{kind}.{key}}}}}", alone(kind, key)))
                parts.append((f".\n\n{{{{{kind}.{key}}}}}\n\n", None, None))
            if file == "main.md":
                listed = sorted(
                    (key for kind, key in numbers if kind == "table" and not numbers[kind, key][0]),
                    key=lambda key: numbers["table", key][1],
                )
                parts.append((f"{words().capitalize()} in Tables ", None, None))
                for index, key in enumerate(listed):
                    join = "" if index == 0 else " and " if index == len(listed) - 1 else ", "
                    parts.append((join, f"{{{{num.table.{key}}}}}", alone("table", key)))
                parts.append((".\n\n", None, None))
                table = draw(st.sampled_from(listed))
                plants = [
                    ("unresolved-binding", "", "{{ref.table.nothing}}", None),
                    ("unresolved-binding", "", f"{{{{ref.figure.{table}}}}}", None),
                    ("pointer-word-mismatch", "Figure ", f"{{{{num.table.{table}}}}}",
                     alone("table", table)),
                    ("pointer-word-mismatch", "Supplementary Table ",
                     f"{{{{num.table.{table}}}}}", alone("table", table)),
                ]  # fmt: skip
                for code, word, binding, printed in draw(st.permutations(plants)):
                    line = "".join(part[0] + (part[1] or "") for part in parts).count("\n") + 1
                    planted.add((code, file, line))
                    lead = f"{words().capitalize()} in {word}"
                    printing = (lead, binding, printed)
                    parts.append(printing if printed else (lead + binding, None, None))
                    parts.append((".\n\n", None, None))
            write(file, parts)
    return texts, prints, planted

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


# ------------------------------------------------------------------------------- LaTeX

#: LaTeX as an author writes it, each piece whole: numbers as LaTeX writes them, the commands
#: the reader knows and one it does not, citations, a binding, a label, listings, a comment,
#: maths and a table. Whole, so that one drawn among others reads as it reads alone.
_LATEX_WHOLE = (
    "95\\% ", "$p<0.05$ ", "3--5 ", "Table~\\ref{t} ", "\\cite[p.~33]{smith2019} ",
    "\\citep{a,b} ", "\\mg{results.ror.point} ", "\\label{sec:2} ", "\\verb|x=1| ",
    "% note 12\n", "\\url{http://a.b/1%2} ", "\\footnote{seen 3} ", "\\emph{7 words} ",
    "\\section{Results 2}\n", "\\unknown{4 days} ", "``quoted 6'' ", "$\\beta = 0.42$ ",
    "\\begin{tabular}{lc}a & 7 \\\\ b & 8 \\\\\\end{tabular}\n", "\\iffalse 9 \\fi ",
    "\\begin{verbatim}\nx <- 55\n\\end{verbatim}\n", "\\[ x = 1 \\] ", "10\\,000 ", "\n\n",
)  # fmt: skip
#: The signs of LaTeX bare, opened and closed by nobody: what a scanner mishandles.
_LATEX_SIGNS = (
    "\\", "%", "{", "}", "[", "]", "$", "$$", "&", "#", "^", "_", "~", "``", "''",
    "\\begin{verbatim}", "\\end{equation}", "\\[", "\\]", "\\(", "\\)", "\\iffalse", "\\fi",
    "\\input{", "\\verb", "\\begin{document}", "\\end{document}", "\\catcode", "\\def\\x",
    "\\makeatletter", "\\ifx", "\n", "\r\n", " ", "12", "\\begin{comment}", "\\url{",
)  # fmt: skip
_PREAMBLE = "\\documentclass{article}\n\\begin{document}\n"


def latex_texts() -> st.SearchStrategy[str]:
    """A LaTeX file, drawn as `texts` draws a Markdown one: whole pieces among words, and the
    bare signs once each. Some open with a preamble and `\\begin{document}`."""
    pool = (*_spaced(FILLER) * 2, *_spaced(_NUMBERS), *_LATEX_WHOLE * 3, *_LATEX_SIGNS)
    return st.tuples(
        st.sampled_from(("", "", _PREAMBLE)), _in_a_row(pool, few=20, many=70)
    ).map("".join)


#: Where a number stands in LaTeX, and whether the reader reads it there: each `{}` holds a
#: number, and its flag says whether it is read. A comment's line is followed by a line
#: that is read, so that a comment that runs past its line is seen.
LATEX_PLACES = (
    ("prose {} ", (True,)),
    ("\\emph{{{} words}} ", (True,)),
    ("\\footnote{{seen {}}} ", (True,)),
    ("\\caption{{Cases {}}} ", (True,)),
    ("\\cite[p.~{}]{{smith2019}} ", (True,)),
    ("$x = {}$ ", (True,)),
    ("\\verb+{}+ ", (True,)),
    ("\\section{{Part {}}}\n", (True,)),
    ("\\unknown{{{} days}} ", (True,)),
    ("\\newcommand{{\\cases}}{{{}}} ", (True,)),
    ("95\\% then {} ", (True,)),
    ("\\textbf{{a {{b}} {}}} ", (True,)),
    ("% note {}\n{} ", (False, True)),
    ("\\label{{s{}}} ", (False,)),
    ("\\label{{a{{b}}{}}} ", (False,)),
    ("\\cite{{key{}}} ", (False,)),
    ("\\mg{{results.r{}}} ", (False,)),
    ("\\url{{http://a.b/{}}} ", (False,)),
    ("\\begin{{verbatim}}\n{}\n\\end{{verbatim}}\n", (False,)),
    ("\\iffalse {} \\fi ", (False,)),
    ("\\vspace{{{}pt}} ", (False,)),
    # What round 1 of #380 found blanked though it prints.
    ("\\iffalse {} \\else {} \\fi ", (False, True)),
    ("\\begin{{align}}a &= b \\\\\n[{}] &= c\\end{{align}}\n", (True,)),
    ("\\href{{http://a.b/{}}}{{text {}}} ", (False, True)),
    ("\\begin{{tabular}}{{ll}}{} & \\multicolumn{{1}}{{c}}{{m {}}} \\\\\\end{{tabular}}\n",
     (True, True)),
    ("$x$${}$ ", (True,)),
)  # fmt: skip
#: Where a number stands in the preamble, before `\\begin{document}`.
LATEX_PREAMBLE_PLACES = (
    ("\\begin{{filecontents}}{{x.bib}}\nkept {}\n\\end{{filecontents}}\n", (False,)),
    ("\\title{{T {}}}\n", (True,)),
    ("\\newcommand{{\\ci}}[1][{}]{{#1 CI}}\n", (True,)),
    ("\\usepackage[opt{}]{{x}}\n", (False,)),
    ("\\author{{A {}}}\n", (False,)),
    # An abstract a class prints from the preamble, and a restyling that names the command
    # (round 2 of #385: the first was refused, and so was the second).
    ("\\let\\oldabstract\\abstract\n\\abstract{{Of {}}}\n", (True,)),
    ("\\begin{{abstract}}Of {}\\end{{abstract}}\n", (True,)),
)  # fmt: skip


@st.composite
def latex_planted(draw: st.DrawFn) -> tuple[str, list[tuple[int, str, bool]]]:
    """A LaTeX document with a number in every place of `LATEX_PLACES`, in an order drawn,
    among whole pieces; and where each number stands, and whether it is read there. Every
    place is in every document, so that a rule broken for one kind is seen in each."""
    filler = (*_spaced(FILLER), *_LATEX_WHOLE)
    order = draw(st.permutations(range(len(LATEX_PLACES))))
    between = draw(st.lists(st.sampled_from(filler), min_size=len(order) + 1,
                            max_size=len(order) + 1))  # fmt: skip
    text, planted, count = "\\documentclass{article}\n", [], 0

    def plant(template: str, flags: tuple[bool, ...]) -> None:
        nonlocal text, count
        pieces = [piece.replace("{{", "{").replace("}}", "}") for piece in template.split("{}")]
        for piece, read in zip(pieces, flags, strict=False):
            number = str(4101 + count)
            count += 1
            text += piece
            planted.append((len(text), number, read))
            text += number
        text += pieces[-1]

    for template, flags in LATEX_PREAMBLE_PLACES:
        plant(template, flags)
    text += "\\begin{document}\n"
    for piece, index in zip(between, order, strict=False):
        text += piece
        plant(*LATEX_PLACES[index])
    text += between[-1] + "\\end{document}\n"
    plant("after {}\n", (False,))
    return text, planted


_SECTIONING = {-1: "part", 0: "chapter", 1: "section", 2: "subsection", 3: "subsubsection"}


@st.composite
def latex_trees(
    draw: st.DrawFn,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    """A LaTeX manuscript of a few files that input one another, with no file inputting
    itself; the titles each file starts under; and the titles in force at a word written
    after each heading. Both are worked out apart from the reader: a heading of a file input
    reaches the text after its `\\input`, as LaTeX prints it.

    The entry file opens under a part, a chapter and a section, inputs a file that opens a
    subsection, writes a subsubsection right after that `\\input`, and inputs another file.
    So every manuscript has a file that starts under a heading, a part a chapter does not
    close, and a heading where an `\\input` ends, which stands over the text after it (round
    2 of #385). Nothing but a heading's word follows a line break, so an `\\input` stands
    against what comes next."""
    count = draw(st.integers(min_value=3, max_value=5))
    names = ["main.tex", *(f"part{index}.tex" for index in range(1, count))]
    items: dict[str, list[tuple[str, object]]] = {}
    for index, name in enumerate(names):
        drawn = draw(st.lists(st.one_of(
            st.tuples(st.just("heading"), st.integers(min_value=-1, max_value=3)),
            st.tuples(st.just("input"), st.integers(min_value=index + 1, max_value=count)),
            st.tuples(st.just("words"), st.sampled_from(FILLER)),
        ), max_size=8))  # fmt: skip
        inputs = [("input", child) for kind, child in drawn if kind == "input" and child < count]
        rest = [item for item in drawn if item[0] != "input"]
        opening = [("heading", -1), ("heading", 0), ("heading", 1), ("input", 1),
                   ("heading", 3), ("input", 2)]  # fmt: skip
        planted = {0: opening, 1: [("heading", 2)]}
        items[name] = planted.get(index, []) + rest + inputs
    files, under, marks, seen, counter = {}, {}, {}, {"main.tex"}, [0]

    def visit(name: str, chain: list[tuple[int, str]]) -> list[tuple[int, str]]:
        under[name] = [title for _, title in chain]
        text = "\\documentclass{article}\n\\begin{document}\n" if name == "main.tex" else ""
        for kind, value in items[name]:
            if kind == "heading":
                counter[0] += 1
                title = f"Part {counter[0]}"
                chain = [kept for kept in chain if kept[0] < value] + [(value, title)]
                marks[f"mark{counter[0]}"] = [title for _, title in chain]
                text += f"\\{_SECTIONING[value]}{{{title}}}\nmark{counter[0]} "
            elif kind == "input":
                child = names[value]
                text += f"\\input{{{child[:-4]}}}"
                if child not in seen:
                    seen.add(child)
                    chain = visit(child, chain)
            else:
                text += f"{value} "
        files[name] = text + ("\n\\end{document}\n" if name == "main.tex" else "")
        return chain

    visit("main.tex", [])
    for name in names:
        files.setdefault(name, "")
    return files, under, marks


#: The headings of the parts of a paper, each written more than one way, and bindings to
#: put under them: what G8 reads to find a number a summary gives and the paper does not.
SUMMARIES = (
    "\n\n# Abstract\n\n", "\n\n# 1. Summary\n\n", "\n\n## Results\n\n", "\n\n# 3. Results\n\n",
    "\n\nFindings\n========\n\n", "\n\n# **Results and discussion**\n\n", "\n\n# Conclusions\n\n",
    "\n\n## 5.1 Concluding remarks\n\n", "\n\n# Discussion\n\n", "\n\n# Methods\n\n",
    "\n\n# Introduction\n\n", "{{results.ror.point}}", "{{results.case.n_cases}}",
    "{{ results.ror.ci_low }}", "{{lit.incidence}}", "{{results.ror.point}}",
)  # fmt: skip


def summaries() -> st.SearchStrategy[str]:
    """A manuscript holding every heading and binding of `SUMMARIES`, in an order and among
    pieces of the pool drawn each time: a rule broken for one way of writing a heading is
    seen whatever the seed."""
    between = _in_a_row(_pool(()), few=3, many=10)
    return st.permutations(SUMMARIES).flatmap(
        lambda order: st.tuples(*(between for _ in order)).map(
            lambda gaps: "".join(gap + piece for gap, piece in zip(gaps, order, strict=True))
        )
    )


#: Quotations as a sentence writes them, with the citation that says whose words they are.
_OPEN, _CLOSE = "\N{LEFT DOUBLE QUOTATION MARK}", "\N{RIGHT DOUBLE QUOTATION MARK}"
QUOTED = (
    _OPEN + "the risk was acceptable in all but the frailest" + _CLOSE + " [@agency2019]",
    '"four words stand in here" [@a]',
    _OPEN + "It was low. It was acceptable." + _CLOSE + " [@b; @c]",
    '"so-called" [@d]',
)


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


# ------------------------------------------------------------ passages of cited works

#: How a person writes a cited sentence into `passages.yaml` and means the same sentence:
#: each is no difference to a reader, and none may be one to G7.
FOLDED = (
    "citations dropped", "citations added", "capitals", "wrapped", "no final stop", "typed",
    "no-break space", "space before a comma", "binding spaced",
)  # fmt: skip
#: The binding a planted claim holds, as the manuscript writes it.
_CLAIMED = "{{results.cohort.n}}"
#: How it is written and means another sentence, or another work, and belongs to none.
UNFOLDED = ("last word changed", "word added", "work not cited")


_EN_DASH = "\N{EN DASH}"


def _written(sentence: str, group: str, how: str) -> str:
    """`sentence`, whose citation group is `group`, written into `passages.yaml` as `how`."""
    return {
        "citations dropped": lambda: sentence.replace(f" {group}", ""),
        "citations added": lambda: sentence.replace(group, "[@z9, p. 4] " + group),
        "capitals": sentence.upper,
        "wrapped": lambda: sentence.replace(" ", "\n    ", 3),
        "no final stop": lambda: sentence.rstrip("."),
        "typed": lambda: typed(sentence),
        "no-break space": lambda: sentence.replace(" ", "\N{NO-BREAK SPACE}", 2),
        "space before a comma": lambda: sentence.replace(",", " ,", 1),
        "binding spaced": lambda: sentence.replace(_CLAIMED, "{{ results.cohort.n }}"),
        "last word changed": lambda: sentence.replace(" age ", " sex "),
        "word added": lambda: sentence.replace(" rate ", " rate never "),
        "work not cited": lambda: sentence,
    }[how]()


@st.composite
def passage_files(draw: st.DrawFn) -> tuple[dict[str, Any], list[tuple[int, str]]]:
    """A manuscript of cited claims, each its own paragraph among drawn text, and the entries
    of a `passages.yaml` for them: for each claim, its sentence written each way of `FOLDED`
    and of `UNFOLDED`, in an order drawn each time. With each entry, the claim it belongs
    to and how it was written; an `UNFOLDED` one belongs to none.

    Every way in each example, so that a rule broken for one of them fails under any seed. A
    claim's last word before its citation is the one changed, so that a rule matching on a
    sentence's opening words is wrong in every example. Drawn text opens no comment, which
    would hide the claims after it: what is held here is how a passage finds its sentence."""
    claims = draw(st.integers(1, 3))
    noise = texts().map(lambda text: text.replace("<!--", "<!-"))
    pieces, entries = [], []
    for n in range(1, claims + 1):
        verb = draw(st.sampled_from(("rose", "fell", "doubled", "persisted")))
        group = draw(st.sampled_from((f"[@k{n}]", f"[@k{n}; @shared]", f"[see @k{n}, p. 3]")))
        sentence = (
            f"Claim {n}: in the {_OPEN}older{_CLOSE} cohort of {_CLAIMED}, the "
            f"drug{_EN_DASH}induced injury rate {verb} with age {group}."
        )
        pieces.append(sentence)
        for how in FOLDED + UNFOLDED:
            key = f"k{n}x" if how == "work not cited" else f"k{n}"
            entries.append((
                {"sentence": _written(sentence, group, how), "citekey": key,
                 "passage": "words of the work", "locator": "p. 1"},
                (n, how),
            ))  # fmt: skip
    pieces = draw(st.permutations(pieces))
    text = "".join(f"{draw(noise)}\n\n{piece}\n\n" for piece in pieces) + draw(noise)
    entries = draw(st.permutations(entries))
    return {"text": text, "entries": [entry for entry, _n in entries]}, [n for _e, n in entries]


# ---------------------------------------------------------------------- a vector figure

#: Each kind of text a vector figure holds: what G4 reads the size of.
TEXT_KINDS = ("unset", "pt", "mm", "em", "tspan", "use", "turned", "weight", "class")


def _composed(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    """Two linear maps, (a, b, c, d) as SVG writes a matrix's first four, one after the
    other: the parent's, then the child's."""
    a, b, c, d = left
    e, f, g, h = right
    return (a * e + c * f, b * e + d * f, a * g + c * h, b * g + d * h)


@st.composite
def _transforms(draw: st.DrawFn) -> tuple[str, tuple[float, ...]]:
    """A transform as an SVG writes it, and its linear part."""
    import math

    kind = draw(st.sampled_from(("scale", "scale2", "rotate", "matrix", "translate")))
    one, two = (draw(st.integers(250, 3000)) / 1000 for _ in range(2))
    if kind == "scale":
        return f"scale({one})", (one, 0.0, 0.0, one)
    if kind == "scale2":
        return f"scale({one} {two})", (one, 0.0, 0.0, two)
    if kind == "rotate":
        angle = draw(st.integers(-180, 180))
        turn = math.radians(angle)
        return f"rotate({angle} 5 5)", (math.cos(turn), math.sin(turn), -math.sin(turn),
                                        math.cos(turn))  # fmt: skip
    if kind == "matrix":
        skew = draw(st.integers(-500, 500)) / 1000
        return f"matrix({one} 0 {skew} {two} 3 4)", (one, 0.0, skew, two)
    return f"translate({one} {two})", (1.0, 0.0, 0.0, 1.0)


@st.composite
def vector_figures(draw: st.DrawFn) -> tuple[str, dict[str, float], list[float]]:
    """An SVG figure with a text of every kind in it, each under transforms drawn at random:
    a size not set, in pt, in mm, in em of its group's, a tspan in percent of its text's,
    a text drawn through `<use>`, and one turned inside a scale that is not the same both
    ways; and a line beside each. With the height each text is drawn at in units, and the
    width of each line, worked out from the matrices."""
    import math

    texts: dict[str, float] = {}
    lines: list[float] = []
    defs, body, rules = [], [], []
    for number, kind in enumerate(draw(st.permutations(TEXT_KINDS))):
        label = f"t{number}"
        drawn = draw(st.lists(_transforms(), max_size=3))
        linear = (1.0, 0.0, 0.0, 1.0)
        for _written, part in drawn:
            linear = _composed(linear, part)
        size = draw(st.integers(4, 24))
        inner = f'<text x="1" y="1" font-size="{size}">{label}</text>'
        units = float(size)
        # The transforms inside the drawn ones that the kind itself puts on its text.
        own = (1.0, 0.0, 0.0, 1.0)
        if kind == "unset":
            inner, units = f'<text x="1" y="1">{label}</text>', 16.0
        elif kind == "pt":
            inner, units = f'<text x="1" y="1" font-size="{size}pt">{label}</text>', size * 4 / 3
        elif kind == "mm":
            inner = f'<text x="1" y="1" style="font-size: {size}mm">{label}</text>'
            units = size * 96 / 25.4
        elif kind == "em":
            group, em = draw(st.integers(6, 20)), draw(st.integers(5, 20)) / 10
            text = f'<text x="1" y="1" font-size="{em}em">{label}</text>'
            inner, units = f'<g font-size="{group}">{text}</g>', group * em
        elif kind == "tspan":
            share = draw(st.integers(40, 90))
            inner = (f'<text x="1" y="1" font-size="{size}">{label}'
                     f'<tspan font-size="{share}%">s{number}</tspan></text>')  # fmt: skip
            texts[f"s{number}"] = size * share / 100 * math.hypot(linear[2], linear[3])
        elif kind == "use":
            scale = draw(st.integers(250, 3000)) / 1000
            defs.append(f'<text id="u{number}" x="1" y="1" font-size="{size}">{label}</text>')
            inner = f'<use xlink:href="#u{number}" transform="scale({scale})"/>'
            own = (scale, 0.0, 0.0, scale)
        elif kind == "weight":
            # A bold text, its weight before its size, as matplotlib writes it.
            inner = f"<text x=\"1\" y=\"1\" style=\"font: 700 {size}px sans-serif\">{label}</text>"
        elif kind == "class":
            # A size set through a class, as Illustrator writes it, over the attribute.
            rules.append(f".c{number} {{ font-size: {size}px }}")
            inner = f'<text x="1" y="1" class="c{number}" font-size="99">{label}</text>'
        elif kind == "turned":
            inner = (f'<g transform="scale(2 0.5)"><g transform="rotate(90)">'
                     f'<text x="1" y="1" font-size="{size}">{label}</text></g></g>')  # fmt: skip
            # Turned a quarter inside it, the text stands along the scale's 2, not its 0.5.
            own = _composed((2.0, 0.0, 0.0, 0.5), (0.0, 1.0, -1.0, 0.0))
        width = draw(st.integers(1, 30)) / 10
        line = f'<path d="M0 0L1 1" stroke="black" stroke-width="{width}"/>'
        if kind == "class":
            # A line stroked by the stylesheet alone, as svglite strokes a black one.
            line = f'<path class="stroked" d="M0 0L1 1" style="stroke-width: {width}"/>'
        whole = _composed(linear, own)
        texts[label] = units * math.hypot(whole[2], whole[3])
        lines.append(width * math.sqrt(abs(linear[0] * linear[3] - linear[1] * linear[2])))
        for written, _part in reversed(drawn):
            inner, line = (f'<g transform="{written}">{inner}</g>',
                           f'<g transform="{written}">{line}</g>')  # fmt: skip
        body += [inner, line]
    document = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        'width="400pt" height="300pt" viewBox="0 0 400 300">'
        f"<style>.stroked {{ stroke: #000000 }} {' '.join(rules)}</style>"
        f"<defs>{''.join(defs)}</defs>{''.join(body)}</svg>"
    )
    return document, texts, sorted(lines)


# --------------------------------------------------------------------------- a PDF figure


def pdf_document(
    content: bytes,
    fonts: dict[str, bytes] | None = None,
    forms: dict[str, tuple[bytes, str]] | None = None,
    *,
    width: float = 216,
    compress: bool = True,
    packed: bool = False,
    split: bool = False,
) -> bytes:
    """A PDF of one page that draws `content`, with `fonts` (a name and the font's own
    dictionary, which may refer to the objects after it as `{n}`) and `forms` (a name, and
    the form's content and `/Matrix`). Its fonts are packed in an object stream where
    `packed` is set, and its content in a stream for each line where `split` is. No
    cross-reference table: what reads it reads its objects."""
    fonts = fonts or {"F1": b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    forms = forms or {}
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def stream(data: bytes, extra: bytes = b"") -> bytes:
        import zlib

        if compress:
            data = zlib.compress(data)
            extra += b" /Filter /FlateDecode"
        return b"<< /Length %d%s >>\nstream\n" % (len(data), extra) + data + b"\nendstream"

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 /MediaBox [0 0 %g 144] >>" % width)
    add(b"")  # the page, once its resources are known
    pieces = content.split(b"\n") if split else [content]
    for piece in pieces:
        add(stream(piece))
    font_refs, packed_bodies = [], []
    for name, body in fonts.items():
        number = len(objects) + 1 if not packed else 100 + len(packed_bodies)
        body = body.replace(b"{n}", b"%d" % (number + 1))
        if packed:
            packed_bodies.append((number, body))
        else:
            add(body)
        font_refs.append(b"/%s %d 0 R" % (name.encode(), number))
    if packed:
        header = b" ".join(b"%d %d" % (n, sum(len(b) + 1 for _m, b in packed_bodies[:i]))
                           for i, (n, _b) in enumerate(packed_bodies))  # fmt: skip
        body = b"\n".join(b for _n, b in packed_bodies)
        add(stream(header + b"\n" + body, b" /Type /ObjStm /N %d /First %d"
                   % (len(packed_bodies), len(header) + 1)))  # fmt: skip
    form_refs = []
    for name, (data, matrix) in forms.items():
        number = add(stream(data, b" /Type /XObject /Subtype /Form /BBox [0 0 216 144] "
                                  b"/Matrix [" + matrix.encode() + b"]"))  # fmt: skip
        form_refs.append(b"/%s %d 0 R" % (name.encode(), number))
    contents = b"[" + b" ".join(b"%d 0 R" % (4 + i) for i in range(len(pieces))) + b"]"
    objects[2] = (b"<< /Type /Page /Parent 2 0 R /Contents " + contents
                  + b" /Resources << /Font << "
                  + b" ".join(font_refs) + b" >> /XObject << " + b" ".join(form_refs)
                  + b" >> >> >>")  # fmt: skip
    out = b"%PDF-1.5\n"
    for number, body in enumerate(objects, 1):
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    return out + b"%%EOF\n"


def _row(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    """Two PDF matrices, (a, b, c, d, e, f), `left` then `right`, a point a row vector."""
    a, b, c, d, e, f = left
    g, h, i, j, k, m = right
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j,
            e * g + f * i + k, e * h + f * j + m)  # fmt: skip


@st.composite
def pdf_figures(draw: st.DrawFn) -> tuple[bytes, list[float], list[float]]:
    """A PDF figure whose page draws texts and lines under transforms drawn at random:
    `cm` inside `q` and `Q`, a text matrix set by `Tm` and moved by `Td`, and a form drawn
    by `Do` under its own `/Matrix`; and a path that is filled, which is no line. With the
    height of each text and the width of each line, worked out from the matrices."""
    import math

    def matrix() -> tuple[float, ...]:
        kind = draw(st.sampled_from(("scale", "scale2", "turn", "skew", "move")))
        one, two = (draw(st.integers(250, 3000)) / 1000 for _ in range(2))
        if kind == "scale":
            return (one, 0.0, 0.0, one, 3.0, 4.0)
        if kind == "scale2":
            return (one, 0.0, 0.0, two, 0.0, 0.0)
        if kind == "turn":
            return (0.0, one, -one, 0.0, 5.0, 5.0)
        if kind == "skew":
            return (one, 0.0, draw(st.integers(-500, 500)) / 1000, two, 0.0, 0.0)
        return (1.0, 0.0, 0.0, 1.0, one, two)

    def written(m: tuple[float, ...]) -> bytes:
        return b" ".join(b"%g" % x for x in m)

    def drawing(ctm: tuple[float, ...]) -> tuple[bytes, list[float], list[float]]:
        """Some texts and lines, each under transforms of its own, inside q and Q."""
        content, texts, lines = b"", [], []
        for _ in range(draw(st.integers(1, 3))):
            around = [matrix() for _ in range(draw(st.integers(0, 2)))]
            inner = ctm
            for m in around:
                inner = _row(m, inner)
            size = draw(st.integers(4, 24))
            tm = matrix()
            moved = (1.0, 0.0, 0.0, 1.0, *(draw(st.integers(-20, 20)) for _ in range(2)))
            text = _row(_row(moved, tm), inner)
            width = draw(st.integers(1, 30)) / 10
            shows = draw(st.sampled_from((b"(t) Tj", b"[(t) -20 (u)] TJ", b"(t) '")))
            # A line stroked at its width, and a path filled, which draws no line.
            strokes = b" ET %g w 0 0 m 10 10 l S 2 w 0 0 m 5 5 l f Q\n" % width
            content += (b"q " + b" ".join(written(m) + b" cm" for m in around)
                        + b" BT /F1 %d Tf " % size + written(tm) + b" Tm %g %g Td " % moved[4:]
                        + shows + strokes)  # fmt: skip
            texts.append(size * math.hypot(text[2], text[3]))
            lines.append(width * math.sqrt(abs(inner[0] * inner[3] - inner[1] * inner[2])))
        return content, texts, lines

    # The whole page under a transform that one content stream opens and another closes,
    # as an editor wraps a page: the streams draw as one.
    wrap = matrix()
    content, texts, lines = drawing(wrap)
    # A transform left open by a q that a Q closes: what follows is drawn without it.
    content = b"q " + written(matrix()) + b" cm Q\n" + content
    form_matrix, placed = matrix(), matrix()
    # A form draws under its /Matrix, and that under the page's transform where `Do` is;
    # and with the line width set before `Do`, until it sets one of its own.
    inner = _row(form_matrix, _row(placed, wrap))
    form_drawn, form_texts, form_lines = drawing(inner)
    inherited = draw(st.integers(1, 30)) / 10
    form_drawn = b"0 0 m 3 3 l S\n" + form_drawn
    form_lines.append(inherited * math.sqrt(abs(inner[0] * inner[3] - inner[1] * inner[2])))
    content += b"q " + written(placed) + b" cm %g w /X1 Do Q\n" % inherited
    content = b"q " + written(wrap) + b" cm\n" + content.rstrip(b"\n").replace(b"\n", b" ") + b"\nQ"
    document = pdf_document(content, forms={"X1": (form_drawn, written(form_matrix).decode())},
                            split=True)  # fmt: skip
    return document, sorted(texts + form_texts), sorted(lines + form_lines)


# ------------------------------------------------------------- a figure's alternative text

#: What pandoc's Markdown reads as markup in a picture's description unless each mark in it
#: is escaped: emphasis, a link, a citation, maths, code, raw HTML and a comment, quotation
#: marks and dashes it would curl and join, a sub- and superscript, a struck word, a
#: backslash that would escape the bracket closing the description, and a binding left as
#: written. Every alternative text drawn holds each, so that one mark left unescaped is read
#: as markup under every seed.
ALT_MARKUP = (
    "*emphasis*", "**strong**", "_under_", "[a link](x.png)", "![a picture](y.png)",
    "@citekey", "[@citekey]", "$x^2$", "`code`", "<b>bold</b>", "<!-- comment -->", "&amp;",
    '"quoted"', "'single'", "--", "...", "^up^", "~down~", "~~struck~~", "\\", "\\*",
    "{{results.key}}", "#", "|", "50%",
)  # fmt: skip
#: Words with no markup, some beyond ASCII.
ALT_WORDS = (*FILLER[:12], "\N{PLUS-MINUS SIGN}2", "caf\N{LATIN SMALL LETTER E WITH ACUTE}",
             "\N{GREATER-THAN OR EQUAL TO}", "0.5\N{EN DASH}2")  # fmt: skip
#: What may stand between two pieces: nothing, a space, a run of them, a line break, a
#: blank line, a tab, a no-break space. Each is drawn once in every text.
ALT_SPACES = ("", " ", "   ", "\n", "\n \n", "\t", "\N{NO-BREAK SPACE}")


@st.composite
def alt_texts(draw: st.DrawFn) -> str:
    """An alternative text as an author may write it in a figure's guard file: every piece
    of `ALT_MARKUP` and some words, in an order drawn, each kind of `ALT_SPACES` between two
    of them at least once."""
    words = draw(st.lists(st.sampled_from(ALT_WORDS), max_size=6))
    pieces = draw(st.permutations([*ALT_MARKUP, *words]))
    extra = draw(st.lists(st.sampled_from(ALT_SPACES), min_size=len(pieces) - 1 - len(ALT_SPACES),
                          max_size=len(pieces) - 1 - len(ALT_SPACES)))  # fmt: skip
    spaces = draw(st.permutations([*ALT_SPACES, *extra]))
    joined = zip(spaces, pieces[1:], strict=True)
    return pieces[0] + "".join(space + piece for space, piece in joined)


# -------------------------------------------------------------- the results a plan promises

_STEMS = ("ror", "case", "cohort", "hr", "events")
_LEAVES = ("point", "ci_low", "n", "pct_serious", "n-dropped")
#: Code in a list item that is not a key: no dot in it.
_CODE = ("glm", "R", "lme4", "n_cases")
_MARKERS = ("- ", "* ", "+ ", "1. ")


@st.composite
def planned_plans(draw: st.DrawFn) -> tuple[str, list[tuple[str, bool]]]:
    """A plan whose Planned results section lists results in each way an item holds one,
    with the keys it lists, in order, as (key, whether it is a group).

    Each example holds one item of every kind, in an order drawn each time: a key; a key as
    the manuscript binds it; a key with no dot, bound; a group of keys; words and no code;
    code that is not a key; a key nested under an item that has none; and an item with no
    key followed, past a blank line, by prose that holds one. Then a subsection with a key of
    its own. The section
    comes before the drawn text, which an open fence would otherwise swallow it into."""
    words = st.lists(st.sampled_from(FILLER), min_size=1, max_size=6).map(" ".join)
    marker = st.sampled_from(_MARKERS)

    def key() -> str:
        return f"{draw(st.sampled_from(_STEMS))}.{draw(st.sampled_from(_LEAVES))}"

    def wrapped() -> str:
        return draw(st.sampled_from((" ", "\n  "))).join((draw(words), draw(words)))

    kinds: list[tuple[str, list[tuple[str, bool]]]] = []
    plain, bound, stem = key(), key(), draw(st.sampled_from(_STEMS))
    kinds.append((f"{draw(marker)}`{plain}`: {wrapped()}\n", [(plain, False)]))
    kinds.append((f"{draw(marker)}`results.{bound}` {wrapped()}\n", [(bound, False)]))
    undotted = draw(st.sampled_from(_STEMS))
    kinds.append((f"{draw(marker)}`results.{undotted}`: {draw(words)}\n", [(undotted, False)]))
    kinds.append((f"{draw(marker)}`{stem}.*`: {wrapped()}\n", [(stem, True)]))
    kinds.append((f"{draw(marker)}{wrapped()}\n", []))
    kinds.append((f"{draw(marker)}`{draw(st.sampled_from(_CODE))}` {draw(words)}\n", []))
    nested = key()
    kinds.append((f"- {draw(words)}\n\n  - `{nested}`: {draw(words)}\n", [(nested, False)]))
    kinds.append((f"- {draw(words)}\n\n{draw(words)} `{key()}` {draw(words)}.\n", []))
    order = draw(st.permutations(range(len(kinds))))
    items = "\n".join(kinds[index][0] for index in order)
    listed = [found for index in order for found in kinds[index][1]]
    secondary = key()
    plan = (
        f"# Analysis plan\n\n## Planned results\n\n{items}\n"
        f"### Secondary\n\n{draw(marker)}`{secondary}`: {draw(words)}\n\n"
        f"## Outcome\n\n{draw(texts())}\n"
    )
    return plan, [*listed, (secondary, False)]


# ------------------------------------------------------------ the variables a plan names

#: Names a dictionary gives its variables, a dotted one and one with capitals among them,
#: and names it does not give.
DEFINED = ("age", "sex", "bmi_kg", "visit2", "smoker", "dose_mg", "Sex_at_birth", "x1")
UNDEFINED = ("weight", "eGFR", "height_cm", "alt", "site_id", "n_prior")
#: Headings of a plan's Deviations section, as G12 reads them.
_DEVIATION_TITLES = ("Deviations from the plan", "Changes to the plan", "Protocol amendments")
#: Code and values in backticks, which are not variables.
_NOT_VARIABLES = ("glm()", "stats::glm", "lme4::glmer()", "NA", "TRUE", "results.dose")


@st.composite
def collection_plans(
    draw: st.DrawFn,
) -> tuple[str, list[str], list[tuple[str, int]], list[tuple[str, int]], int]:
    """A plan that names variables in backticks in each way a plan holds one, the names the
    dictionary has, the dictionary's variables the plan names and the names it gives that the
    dictionary lacks, each at the line of its first mention, and the plan's last line before
    the drawn text that ends it.

    Each example holds one section of every kind, in an order drawn each time: a variable the
    dictionary has; one with a dot in its name; a name it lacks; a Deviations section, under a
    heading drawn among its names, naming one of each with a subsection under it naming
    another; code and values; a Planned results item naming a variable after its key; a fence
    and a comment holding names; a variable named in a subsection; a variable written in
    another case; a list headed "Planned results and amendments", which is not the
    Deviations; a section headed "Changes to the planned results", which is; a section
    naming again a variable and a name named elsewhere; and a Deviations subsection of
    another section, followed by a subsection that is read. All under a title that names an
    amendment, which heads the plan and not its Deviations."""
    words = st.lists(st.sampled_from(FILLER), min_size=1, max_size=5).map(" ".join)
    defined = draw(st.permutations(DEFINED))
    undefined = draw(st.permutations(UNDEFINED))
    dotted = "BEN.SEX"
    cased = defined[6][0].swapcase() + defined[6][1:]
    deviation = draw(st.sampled_from(_DEVIATION_TITLES))
    # Each section: its text, then the names it uses and the names it lacks, as written.
    kinds = [
        (f"## Analysis\n\n{draw(words)} `{defined[0]}` {draw(words)}.\n", [defined[0]], []),
        (f"## Population\n\n{draw(words)} `{dotted}` {draw(words)}.\n", [dotted], []),
        (f"## Exposure\n\n{draw(words)} `{undefined[0]}` {draw(words)}.\n", [], [undefined[0]]),
        (f"## {deviation}\n\n{draw(words)} `{defined[1]}` and `{undefined[1]}`.\n\n"
         f"### Later\n\n`{defined[2]}` {draw(words)}.\n", [], []),
        (f"## Outcome\n\n{draw(words)} " + " ".join(f"`{code}`" for code in _NOT_VARIABLES)
         + f" {draw(words)}.\n", [], []),
        (f"## Planned results\n\n- `ror.point`: {draw(words)} `{defined[3]}`\n", [defined[3]],
         []),
        (f"## Sensitivity analyses\n\n```r\nfit(`{undefined[2]}`)\n```\n\n"
         f"<!-- `{undefined[3]}` -->\n", [], []),
        (f"## Covariates\n\n{draw(words)}.\n\n### Adjustment\n\n`{defined[4]}` {draw(words)}.\n",
         [defined[4]], []),
        (f"## Outcome measures\n\n`{cased}` {draw(words)}.\n", [], [cased]),
        (f"## Planned results and amendments\n\n- `ror.n`: `{defined[5]}`\n", [defined[5]], []),
        (f"## Changes to the planned results\n\n`{undefined[4]}` {draw(words)}.\n", [], []),
        (f"## Repeated\n\n`{defined[0]}` and `{undefined[0]}` {draw(words)}.\n",
         [defined[0]], [undefined[0]]),
        (f"## Exposure details\n\n{draw(words)}.\n\n### {deviation}\n\n`{undefined[5]}` "
         f"{draw(words)}.\n\n### Timing\n\n`{defined[7]}` {draw(words)}.\n", [defined[7]], []),
    ]  # fmt: skip
    order = draw(st.permutations(range(len(kinds))))
    # A title that names an amendment encloses the plan, and is not its Deviations.
    plan = f"# Statistical analysis plan (amendment {draw(st.integers(1, 9))})\n\n"
    first: dict[str, dict[str, int]] = {"used": {}, "undefined": {}}
    for index in order:
        text, used, lacked = kinds[index]
        for kind, names in (("used", used), ("undefined", lacked)):
            for name in names:
                line = plan.count("\n") + text[: text.index(f"`{name}`")].count("\n") + 1
                first[kind].setdefault(name, line)
        plan += text + "\n"
    last = plan.count("\n")
    plan += f"## Notes\n\n{draw(texts())}\n"
    ordered = {kind: sorted(found.items(), key=lambda pair: pair[1])
               for kind, found in first.items()}  # fmt: skip
    return plan, [*defined, dotted], ordered["used"], ordered["undefined"], last


#: What can stand in a stored source between two words of a quote taken from it: line
#: numbers, figures, a column's or a header's words, a hyphen at the end of a line, a symbol.
INTERRUPTIONS = (
    "\n12\n", " 41 42 ", "  Table 2  ", "\nRunning head\n", "-\n", "\N{SOFT HYPHEN}",
    "\N{MIDDLE DOT}", "/", " & ",
)  # fmt: skip


@st.composite
def nearly_quoted(draw: st.DrawFn) -> dict[str, str]:
    """A source and a quote of it, with something put into the source anywhere, inside the
    quote or beside it, as the text read from a PDF puts it there."""
    source, quote = draw(quotations())
    at = draw(st.integers(0, len(source)))
    put = draw(st.sampled_from(INTERRUPTIONS))
    return {"source": source[:at] + put + source[at:], "quote": quote}


# ----------------------------------------------------------------------- suggested edits

#: Words a reviewer's edit is made of, each as an edit types it and as pandoc prints it: a
#: plain word, one that stands inside a longer one ("the" in "other", "port" in "reports"),
#: and each thing pandoc typesets, an apostrophe, quotation marks, dashes and an ellipsis.
EDIT_WORDS = (
    ("the", "the"), ("other", "other"), ("reports", "reports"), ("port", "port"),
    ("week", "week"), ("weeks", "weeks"), ("cohort", "cohort"),
    ("drug's", "drug\N{RIGHT SINGLE QUOTATION MARK}s"),
    ("'probable'", "\N{LEFT SINGLE QUOTATION MARK}probable\N{RIGHT SINGLE QUOTATION MARK}"),
    ('"serious"', "\N{LEFT DOUBLE QUOTATION MARK}serious\N{RIGHT DOUBLE QUOTATION MARK}"),
    ("1990--2000", "1990\N{EN DASH}2000"), ("so---it", "so\N{EM DASH}it"),
    ("and...", "and\N{HORIZONTAL ELLIPSIS}"),
)  # fmt: skip
#: What stands between two of those words, as typed and as printed: Markdown reads a run of
#: spaces with one line break in it as one space, and pandoc puts a no-break space after
#: an abbreviation it knows.
EDIT_GAPS = (
    (" ", " "), ("  ", " "), ("\n", " "), (" \n  ", " "), ("\t", " "),
    (" ", "\N{NO-BREAK SPACE}"),
)  # fmt: skip


@st.composite
def suggested_edits(draw: st.DrawFn) -> dict[str, str]:
    """A manuscript file and an edit: a few of its words, or words it may not hold, and
    words to put in their place, some of them markup or two lines."""
    text = draw(texts(tuple(typed for typed, _printed in EDIT_WORDS)))
    words = text.split()
    if words and draw(st.booleans()):
        start = draw(st.integers(0, len(words) - 1))
        old = " ".join(words[start : start + draw(st.integers(1, 3))])
    else:
        old = draw(st.sampled_from(tuple(typed for typed, _printed in EDIT_WORDS) + FILLER))
    new = draw(st.sampled_from((*FILLER[:6], "*held*", "two\nlines", "{{results.x}}", " ")))
    return {"text": text, "old": old, "new": new}


#: Words of a paragraph a suggestion is written into, each used once so that a run of them
#: is found once: letters only, so that none is a number to `reworded`, and none a word of
#: the link's address.
PARAGRAPH_WORDS = (
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india",
    "juliet", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo",
    "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu", "amber",
    "basil", "cedar", "dune", "ember", "fern", "grove", "heath", "iris", "jade", "kelp",
    "larch", "moss", "nettle",
)  # fmt: skip
#: Each kind of stretch a paragraph's words stand in: how it is typed around them, and
#: whether a suggestion is written inside it. Emphasis is prose with marks around it, and
#: Word shows the new words in it; "lines" is prose with a hard line break between each two
#: words, which a suggestion is written beside and not across. Code and a link's text Word
#: shows without their markup, and a comment not at all: it also holds a copy of the
#: paragraph's first word, which prints once.
STRETCHES = {
    "plain": ("", "", True),
    "em": ("*", "*", True),
    "strong": ("**", "**", True),
    "under": ("_", "_", True),
    "lines": ("", "", True),
    "code": ("`", "`", False),
    "link": ("[", "](https://example.invalid/page)", False),
    "comment": ("<!-- ", " -->", False),
}
#: What each value of the analysis prints, in the order the values stand, and what each
#: citation prints.
RENDERED = ("12", "345", "6.7", "89", "1,234")
CITED = ("(Doe 2019)", "(Roe 2020)", "(Poe 2021)", "(Moe 2022)")
#: What a hard line break is typed as, and what lies between a stretch's other words.
HARD_BREAK = "  \n"
#: The words written in place of a run: shorter, longer, and two with a double space
#: between them, which Word shows as one.
WRITTEN_WORDS = ("plainly", "the revised wording here", "kept  apart", "so")


@st.composite
def suggestion_paragraphs(draw: st.DrawFn) -> dict[str, Any]:
    """A paragraph holding every kind of stretch a suggestion can be written beside or
    inside, in an order drawn each time: words alone, in each kind of emphasis, across hard
    line breaks, in code, in a link's text and in a comment, with values of the analysis and
    citations between them. Each kind is there at least once. The paragraph opens with words,
    so that no comment opens it as a block, and ends with a value and words after it, so
    that some words always stand before a value. As its stretches and the spaces between
    them, for `laid_out` to type and print."""
    tokens = ("binding", "cite")
    kinds = [*STRETCHES, *tokens]
    kinds += draw(st.lists(st.sampled_from([*STRETCHES, *tokens]), max_size=3))
    # At most five values and four citations, which `RENDERED` and `CITED` print, and
    # thirteen stretches of words, which forty words fill.
    kinds = ["plain", *draw(st.permutations(kinds)), "binding", "plain"]
    words = iter(draw(st.permutations(PARAGRAPH_WORDS)))
    stretches = []
    for kind in kinds:
        # Across a line break needs two words; every other kind takes one to three.
        count = 0 if kind in tokens else draw(st.integers(2 if kind == "lines" else 1, 3))
        stretches.append([kind, [next(words) for _ in range(count)]])
    space = st.sampled_from((" ", "\n"))
    return {
        "stretches": stretches,
        "between": draw(st.lists(space, min_size=len(kinds) - 1, max_size=len(kinds) - 1)),
        "inside": draw(st.lists(space, min_size=3 * len(kinds), max_size=3 * len(kinds))),
    }


def laid_out(paragraph: dict[str, Any]) -> tuple[str, str, list, list, list]:
    """A `suggestion_paragraphs` paragraph as typed in the source and as Word shows it:
    `(source, printed, words, tokens, renderings)`. Each word is `(word, kind, its stretch's
    place, (start, end) in the source, (start, end) in what Word shows or None, how many
    values and citations stand before it)`, and `tokens` is where each value and citation
    prints. Word shows a line break as a space, emphasis, code and a link by their text, and
    a comment not at all."""
    source, printed = "", ""
    words, tokens, renderings = [], [], []
    inside = iter(paragraph["inside"])
    first = paragraph["stretches"][0][1][0]
    values = citations = 0
    for index, (kind, stretch) in enumerate(paragraph["stretches"]):
        shows = kind != "comment"
        if index:
            # A space before a comment: at the start of a line it opens an HTML block.
            source += paragraph["between"][index - 1] if shows else " "
            printed += " " if shows else ""
        if kind in ("binding", "cite"):
            if kind == "binding":
                rendering = RENDERED[values]
                source += "{{results.value_" + "abcde"[values] + "}}"
                values += 1
            else:
                rendering = CITED[citations]
                source += "[@key_" + "abcd"[citations] + "]"
                citations += 1
            tokens.append((len(printed), len(printed) + len(rendering)))
            renderings.append(rendering)
            printed += rendering
            continue
        opening, closing, prose = STRETCHES[kind]
        source += opening
        for at, word in enumerate(stretch):
            if at:
                # A soft line break inside code or a link's text is left out: what it does
                # there is not what this generator is about.
                source += HARD_BREAK if kind == "lines" else next(inside) if prose else " "
                printed += " " if shows else ""
            typed = (len(source), len(source) + len(word))
            shown = (len(printed), len(printed) + len(word)) if shows else None
            words.append((word, kind, index, typed, shown, len(tokens)))
            source += word
            printed += word if shows else ""
        source += f" {first}{closing}" if kind == "comment" else closing
    return source, printed, words, tokens, renderings


@st.composite
def suggestion_writes(draw: st.DrawFn) -> dict[str, Any]:
    """One run of a `suggestion_paragraphs` paragraph's words to write over, which may cross
    from one stretch into the next, and words to write, some of them markup."""
    source, printed, words, tokens, _renderings = laid_out(draw(suggestion_paragraphs()))
    first = draw(st.integers(0, len(words) - 1))
    run = words[first : first + draw(st.integers(1, 2))]
    return {
        "source": source,
        "printed": printed,
        "tokens": [list(token) for token in tokens],
        "old": " ".join(word for word, *_rest in run),
        "new": draw(st.sampled_from((*WRITTEN_WORDS, "*held*", "two\nlines"))),
    }


# ---------------------------------------------------------------------------- spellings

#: Words one English writes and the other does not, with a name's capital, in capitals,
#: and inside an identifier: what the spelling reading must tell apart.
SPELT = (
    "color", "colour", "center", "centre", "tumor", "tumour", "analyzed", "analysed",
    "organization", "organisation", "randomized", "randomised", "program", "Color",
    "COLOR", "color_2", "color.csv", "info@color-lab.org",
)  # fmt: skip


#: The bindings of statistics that say what they belong to, as `whole_namespace` in
#: tests/readings.py declares them: what the reading of a statistic quoted whole sorts.
WHOLE = (
    "{{results.or.point}}", "{{results.or.ci_low}}", "{{results.or.ci_high}}",
    "{{results.or.p}}", "{{results.hr.p}}", "{{results.female.pct}}",
    "{{results.female.n}}", "{{results.cohort.n}}",
)  # fmt: skip

#: The bindings of intervals and spreads, as `labels_namespace` in tests/readings.py
#: declares them, and the labels a text writes beside them: what the reading of the label
#: beside a binding compares.
LABELLED = (
    "{{results.or.point}}", "{{results.or.ci_low}}", "{{results.or.ci_high}}",
    "{{results.or.ci90_low}}", "{{results.or.ci90_high}}", "{{results.hr.ci_low}}",
    "{{results.hr.ci_high}}", "{{results.age.mean}}", "{{results.age.sd}}",
    "{{results.age.se}}", "95% CI", "90% CI", "95.0% CI", "CI 95%", "SD", "SE", "SEM",
    "standard error", "standard deviation", "(SD)", "±", "s.d.", "s.e.", "(s.d.)",
)  # fmt: skip


#: The bindings of dates, as `data_dates_namespace` in tests/readings.py declares them, and
#: the words a sentence dates the data with: what the reading of a typed date compares.
DATED = (
    "{{results.old.extracted}}", "{{results.old.label}}", "{{results.dataset.vb.extracted}}",
    "{{results.param.start}}", "{{results.cohort.first_year}}", "{{results.n}}", "extracted",
    "downloaded", "covering", "up to", "until", "retrieved", "snapshot", "<!-- extracted -->",
    "{{results.dictionary.icd_10}}", "{{method.extraction}}", "[@extracted2020]", "queries",
    "obtaining", "locked", "through",
)  # fmt: skip


#: What names a dataset, one of each kind the data statement rule knows; links to storage
#: that is neither persistent nor archived, one of each kind; and links to a fixed version of
#: a repository, which are neither. What the data statement reading must tell apart.
DATA_IDENTIFIERS = (
    "10.5281/zenodo.1234567", "GSE123456", "SRP123456", "PRJNA123456", "EGAS00001000001",
    "E-MTAB-1234", "phs000001.v1", "hdl.handle.net/10000/1", "ark:/13030/qt1",
    "https://zenodo.org/records/123", "https://osf.io/ab3cd",
    "https://web.archive.org/web/2020/x", "https://perma.cc/AB12-CD34",
)  # fmt: skip
TEMPORARY_LINKS = (
    "https://drive.google.com/file/x", "https://www.dropbox.com/s/x", "https://1drv.ms/u/x",
    "https://github.com/someone/study", "https://gitlab.com/someone/study/",
)  # fmt: skip
FIXED_LINKS = (
    "https://github.com/someone/study/releases/tag/v1.0",
    "https://github.com/someone/study/tree/4f2a9c1",
)


#: A placeholder of each kind G6 reads, as it is typed and as the rule finds it; the words
#: that are one in the manuscript only, in lower case; and what looks like one and is prose:
#: a karyotype, a syndrome, a link, a title translated into English in brackets, a phrase
#: that goes on, a kinase. What the placeholder reading must tell apart. With round 2 of
#: #262's shapes: a phrase before a list item, an instruction marked or linked, a slot that
#: is a whole field of a cited entry.
PLACEHOLDERS = (
    ("XXXX", "XXXX"), ("[TO BE COMPLETED]", "[TO BE COMPLETED]"),
    ("[Repository]", "[Repository]"), ("[describe the cohort]", "[describe the cohort]"),
    ("lorem ipsum", "lorem ipsum"), ("fill in later.", "fill in later"), ("TODO", "TODO"),
    ("2025-XX-XX", "2025-XX"), ("INSERT_SOURCE_URL", "INSERT_SOURCE_URL"),
    ("[insert the\nname]", "[insert the\nname]"), ("1,XXX", "XXX"),
    ("Dose: fill in later\n- Route: oral", "fill in later"),
    ("[insert the date]{.mark}", "[insert the date]"), ("[insert link](#)", "[insert link]"),
    ("[DOI]", "[DOI]"),
)  # fmt: skip
LOWERED = (("tbd", "tbd"), ("fixme", "fixme"), ("Todo", "Todo"))
LOOKALIKES = (
    "47,XXX", "XXX syndrome", "[repository](https://example.org)",
    "[Add-on therapy in epilepsy]", "replace later lines", "replace later\nlines",
    "TK inhibitors", "[SJS/TEN]", "[HIV/AIDS]",
)  # fmt: skip

#: Words to the reviewers or to a model left in a paper, each a sentence, with the rule of
#: G6 that finds it and the words it finds: one of each rule, a phrase cut by a hard wrap,
#: and the plural beside the singular. And what reads like them and is prose: a name, the
#: contributions, the acknowledgements with a title's stop in them, a regulatory dossier, a
#: retrotransposon, an invitation, and a phrase cut by a blank line. What the residue
#: reading must tell apart.
RESIDUE = (
    ("As requested by Reviewer 2, we added a table.", "reviewer-answered",
     "As requested by Reviewer 2"),
    ("In reply to the\nreviewer, we added a table.", "reviewer-answered",
     "In reply to the reviewer"),
    ("In response to the reviewers' comments, a table was added.", "reviewers-answered",
     "In response to the reviewers"),
    ("Done. As requested, we added the dates.", "as-requested", "As requested,"),
    ("In our original submission, the cohort was larger.", "earlier-version",
     "our original submission"),
    ("The revised manuscript reports the median.", "earlier-version-unnamed",
     "The revised manuscript"),
    ("We have now clarified the exposure.", "we-have-now", "We have now clarified"),
    ("We have expanded the Discussion.", "text-edited", "We have expanded the Discussion"),
    ("These points have now been discussed.", "text-edited-unnamed",
     "These points have now been discussed"),
    ("It is on page 4, lines 120-125.", "lines-cited", "page 4, lines 120"),
    ("It was moved (lines 120-125).", "lines-cited-alone", "(lines 120-125)"),
    ("The revised text is highlighted in yellow.", "changes-marked",
     "The revised text is highlighted"),
    # After a stop, since "in" before either is the stricter rule's.
    ("Done. Tracked changes were accepted.", "tracked-changes", "Tracked changes"),
    ("See the response letter.", "response-letter", "See the response letter"),
    ("Done. The response letter lists them.", "response-letter-unnamed", "response letter"),
    ("I have shortened the abstract.", "model-addressed", "I have shortened the abstract"),
)  # fmt: skip
RESIDUE_LOOKALIKES = (
    "Risk was scored with the Revised Cardiac Risk Index.",
    "All authors approved the revised manuscript.",
    "The authors are grateful to Dr. Simon and Dr. Sampaio for their critical review in the "
    "original manuscript.",
    "The original submission of the dossier to the agency was rejected.",
    "Methylation of the element (LINE 1) was stable.",
    "It was written in response to the editor's invitation.",
    "To address this concern, we used an active comparator.",
    "Reviewer 1 and Reviewer 2 independently extracted the data.",
    "as suggested by\n\nReviewer 2 independently, a heading and a paragraph.",
    # Round 1 of #377: a thanks that names what it is for, a label's history, a Delphi
    # panel's draft.
    "We thank the referee for pointing out an error in the estimator.",
    "This has now been included in the SmPC.",
    "Our initial draft comprised 45 items.",
)  # fmt: skip


#: A statistic in each of the ways one is written, typed and bound, and a number with
#: its unit: what the notation reading must count apart.
#: Bindings with a unit written after them, each way a unit is written.
BOUND_UNITS = (
    "{{results.dose}} mg",
    "{{results.dose}}\N{NO-BREAK SPACE}\N{MICRO SIGN}g/kg",
    "{{results.share}}%",
    "{{results.share}} \N{PER MILLE SIGN}", "{{results.level}}\nmmol/L", "{{results.t}} min",
    "{{results.t}} minutes",
    "{{results.area}} cm\N{SUPERSCRIPT TWO}",
    "{{results.temp}} \N{DEGREE SIGN}C",
)  # fmt: skip

#: A journal's limit as its page may write it, and numbers and words it is not.
QUOTED_LIMITS = (
    "3500", "3,500", "3 500", "3500-word", "13500", "3500.5", "3,5000", "35000", "four",
    "fourteen", "fourfold", "Four", "4", "14", "4.5",
)  # fmt: skip

NOTATED = (
    "P = 0.03", "p=0.04", "*P* < 0.001", "p-value", "n = 12", "n=3", "N= 40",
    "95% CI 1.2 to 3.4", "95% CI 1.2-3.4", "(95% CI {{results.low}} to {{results.high}})",
    "P = {{results.p}}", "5%", "5 %", "5mg", "5 mg", "{{results.dose}}mL",
    "(95% CI 80%-93%; 12 studies)", "2500g", "16,000g", "(CI 95%-0.3 to 0.4)",
)  # fmt: skip

#: A coding dictionary's release typed beside its name and elsewhere, and its name inside a
#: longer word: what G2 finds typed where it should be bound.
RELEASED = (
    "MedDRA version 26.1", "MedDRA 26.1", "26.1", "WHODrug Global B3 March 2025",
    "Global B3 March 2025", "ICD-10 2019", "ICD 10 version 2019", "in 2019", "micd_10ed 2019",
    "{{results.dictionary.meddra}}", "MedDRA" + chr(10) + "26.1",
)  # fmt: skip


#: A test statistic and its P in each of the ways a results sentence writes them, right and
#: wrong, and what a sentence says of a test that is not the textbook one: what the reading
#: of reported tests finds and judges.
REPORTED = (
    "t(23) = 2.45, p = .022", "t(23) = 2.45, p = .41", "*t*(40) = \N{MINUS SIGN}2.1, *P* < 0.05",
    "t = 2.45, df = 23, P = 0.022", "F(2, 45) = 3.21, p = .05", "_F_(1,234) = 5.6; P = .40",
    "\N{GREEK SMALL LETTER CHI}2(1, N = 90) = 4.5, p < .05",
    "\N{GREEK SMALL LETTER CHI}^2^(3) = 0.5, *P* \\< 0.001", "chi-square(2) = 9.1, p = .011",
    "z = 4.10, P = 4.1e-5", "Z = 4.10, P = 4.1 x 10^-5^", "z = 1.2, p\n= .23", "one-sided",
    "Welch's", "after Bonferroni adjustment", "{{results.t}}", "p = {{results.p}}", "t(",
)  # fmt: skip

#: An estimate and its interval in each of the ways a results sentence writes them, right
#: and wrong, with a P and without, and what a sentence says of an interval or a P that is
#: not the plain one: what the reading of reported intervals finds and judges.
ESTIMATES = (
    "OR 2.6 (95% CI 2.1 to 3.2)", "OR 2.6 (95% CI 1.2-3.2)", "HR 0.80; 95% CI: 0.70, 0.91",
    "the odds ratio was 1.9 (95% CI 1.2\N{EN DASH}3.0), P = 0.40", "aOR = 1.5 [CI 95% 1.1, 2.0]",
    "MD \N{MINUS SIGN}0.4 (95% CI \N{MINUS SIGN}0.9 to 0.1), P = 0.01",
    "mean difference 0.4 (95% CI -0.9--0.1)", "RR 1.50 (90% CI 1.05 to 2.14), P = 0.07",
    "(95% profile-likelihood CI", "Bonferroni-adjusted P = 0.40", "P = 0.40 for interaction",
    "and 1.1 (95% CI 0.8 to 1.5)", "hazard ratio\n2.1 (95% CI", "{{results.or}}",
    "(95% CI {{results.lo}} to {{results.hi}})", "P = {{results.p}}", "CI 3.2 to 2.1",
)  # fmt: skip


# ------------------------------------------------------------------------ a table's shares

#: What the rows of a table of shares are about. None names a statistic, a note or an n.
CHARACTERISTICS = (
    "Diabetes", "Hypertension", "Female sex", "Current smoker", "Prior stroke",
    "Heart failure", "Statin use", "Chronic kidney disease",
)  # fmt: skip
#: The categories of a characteristic, and the characteristics that have them.
CATEGORIES = ("North", "South", "East", "West")
SPLIT_BY = ("Region", "Education", "Season of entry")
#: How a header names its column's denominator.
HEADED = (
    "{arm} (n = {n})", "{arm} (N={n})", "{arm}, n = {n}",
    "{arm}\N{NO-BREAK SPACE}(n\N{NO-BREAK SPACE}=\N{NO-BREAK SPACE}{n})",
)  # fmt: skip
#: A footnote marker, and whether it ends the label rather than following its words.
MARKERS = (
    ("^a^", False), ("[^1]", False), ("\N{DAGGER}", False), ("\N{DOUBLE DAGGER}", False),
    ("*", True), ("\N{SUPERSCRIPT ONE}", True),
)  # fmt: skip
#: Rows that name another statistic, which are never read as shares, although each says %.
NOT_SHARES = ("HbA1c, %, mean (SD)", "Ejection fraction, %, median (IQR)",
              "Adherence, %, median (range)")  # fmt: skip
#: Rows whose label gives a unit, a "%", and whose mean (SD) is printed as whole numbers:
#: never read as shares either (round 1 of #314).
UNITS = ("Oxygen saturation, %", "LVEF, %", "Haematocrit, %")
#: What a characteristic's own label row holds beside it: nothing, or its P value.
P_VALUES = ("", "0.04", "<0.001", "P = 0.12", "0.81*")
#: The kinds of row each table of `share_tables` holds one of.
SHARE_ROWS = (
    "right", "wrong", "mean", "unit", "noted", "group", "summed", "subtypes", "own",
    "of the row",
)  # fmt: skip

#: A share as the reading finds it: its line, count, share as printed, denominator, whether
#: it is uncertain, and whether it is off.
Shared = tuple[int, int, str, "int | None", bool, bool]


def _printed(count: int, over: int, places: int) -> str:
    """`count` of `over` as a share, rounded half up to `places`."""
    step = Decimal(1).scaleb(-places)
    return str((Decimal(100 * count) / Decimal(over)).quantize(step, rounding=ROUND_HALF_UP))


def _about_100(percents: list[str]) -> bool:
    """Whether a row's shares could be shares of its total: they add up to 100 within what
    their rounding allows."""
    slack = sum(Decimal(5).scaleb(-len(p.partition(".")[2]) - 1) for p in percents)
    return abs(sum(Decimal(p) for p in percents) - 100) <= slack


def _wrong(draw: st.DrawFn, percents: list[str], which: int, places: int) -> list[str]:
    """`percents` with the one at `which` put a few units off, and off far enough that the
    row's shares do not add up to 100 either."""
    step = Decimal(1).scaleb(-places)
    units = draw(st.integers(3, 60)) * draw(st.sampled_from((1, -1)))
    for tried in (units, -units, *(way * more for more in range(3, 200) for way in (1, -1))):
        value = Decimal(percents[which]) + tried * step
        moved = [*percents[:which], str(value.quantize(step)), *percents[which + 1 :]]
        if 0 <= value <= 100 and not _about_100(moved):
            return moved
    raise AssertionError(f"no share off from {percents}")  # pragma: no cover


@st.composite
def share_tables(draw: st.DrawFn) -> tuple[str, list[Shared]]:
    """A paper with a table of shares, a row of each kind of `SHARE_ROWS` in an order drawn:
    shares right under a label that says n (%), and one wrong among cells that say %; a mean
    (SD), under a label that names it, and under one whose "%" is a unit; a share wrong
    under a label with a footnote marker; the categories of a characteristic under a label
    that says n (%), and those of one under a label that says nothing, whose shares add up
    to 100; a row and its subtypes, shares of that row's count; a count with its own
    denominator, one right and one wrong; and a row of shares of its own total, which are
    not their column's. Then a table
    whose header names no denominator, the first table's wrong share in a fenced listing,
    and a count and its share in a sentence, none of which is held to anything. With each
    share the reading finds (`Shared`), in the order it finds them."""
    places = draw(st.integers(0, 2))
    grouped = draw(st.booleans())
    sizes = [draw(st.integers(40, 5000)) for _arm in range(2)]
    sentence = st.lists(st.sampled_from(FILLER), min_size=2, max_size=6).map(" ".join)
    name = st.sampled_from(CHARACTERISTICS)
    lines: list[str] = [draw(sentence).capitalize() + ".", ""]
    expected: list[Shared] = []

    def count(number: int) -> str:
        return f"{number:,}" if grouped else str(number)

    def row(label: str, cells: list[str], p: str = "") -> None:
        """A row, with a P value in the last column or nothing."""
        lines.append("| " + " | ".join([label, *cells, p]) + " |")

    def shares(label: str, counts: list[int], percents: list[str], overs: list[Any], *,
               wrong: int | None = None, sign: str = "", noted: bool = False,
               own: bool = False, read: tuple[int, ...] = (0, 1)) -> None:  # fmt: skip
        """A row of shares, and what the reading finds in it, in the columns it reads."""
        drawn = list(zip(counts, percents, overs, strict=True))
        row(label, [f"{count(c)}/{count(d)} ({p}{sign})" if own else f"{count(c)} ({p}{sign})"
                    for c, p, d in drawn])  # fmt: skip
        expected.extend((len(lines), c, p, d, noted, column == wrong)
                        for column, (c, p, d) in enumerate(drawn) if column in read)  # fmt: skip

    def counted(overs: list[int]) -> tuple[list[int], list[str]]:
        counts = [draw(st.integers(0, n)) for n in overs]
        return counts, [_printed(c, n, places) for c, n in zip(counts, overs, strict=True)]

    def cut(totals: list[int], read: tuple[int, ...] = (0, 1)) -> None:
        """Categories under a label of their own, each arm's total cut among them, so that
        their shares of it add up to 100, read in the columns `read` names."""
        parts = draw(st.integers(2, 4))
        edges = [[0, *sorted(draw(st.lists(st.integers(0, n), min_size=parts - 1,
                                           max_size=parts - 1))), n] for n in totals]
        for at, category in enumerate(CATEGORIES[:parts]):
            counts = [edge[at + 1] - edge[at] for edge in edges]
            percents = [_printed(c, n, places) for c, n in zip(counts, totals, strict=True)]
            shares(category, counts, percents, sizes, read=read)

    # The first arm's header says its numbers are n (%), as a table that gives the other
    # statistics in its labels does; the second's says nothing, so that what else says a
    # cell is a share is drawn too.
    headers = [draw(st.sampled_from(HEADED)).format(arm=arm, n=count(n))
               for arm, n in zip(("Exposed", "Unexposed"), sizes, strict=True)]  # fmt: skip
    row("Characteristic", [f"{headers[0]}, n (%)", headers[1]], "P")
    lines.append("|---|---|---|---|")
    fenced = ""
    for kind in draw(st.permutations(SHARE_ROWS)):
        if kind == "right":
            shares(f"{draw(name)}, n (%)", *counted(sizes), sizes)
        elif kind in ("wrong", "noted"):
            counts, percents = counted(sizes)
            which = draw(st.integers(0, 1))
            percents = _wrong(draw, percents, which, places)
            if kind == "wrong":
                shares(draw(name), counts, percents, sizes, wrong=which, sign="%")
                fenced = "\n".join([*lines[2:4], lines[-1]])
            else:
                marker, last = draw(st.sampled_from(MARKERS))
                label = draw(name)
                label = f"{label}, n (%){marker}" if last else f"{label}{marker}, n (%)"
                shares(label, counts, percents, sizes, wrong=which, noted=True)
        elif kind in ("mean", "unit"):
            row(draw(st.sampled_from(NOT_SHARES if kind == "mean" else UNITS)),
                [f"{draw(st.integers(1, 99))} ({draw(st.integers(1, 40))})" for _arm in sizes])
        elif kind == "group":
            label = f"{draw(st.sampled_from(SPLIT_BY))}, n (%)"
            row(label, ["", ""], draw(st.sampled_from(P_VALUES)))
            for category in CATEGORIES[: draw(st.integers(2, 4))]:
                shares(category, *counted(sizes), sizes)
            # The next characteristic straight after them, its label saying n (%).
            shares(f"{draw(name)}, n (%)", *counted(sizes), sizes)
        elif kind == "summed":
            row(draw(st.sampled_from(SPLIT_BY)), ["", ""], draw(st.sampled_from(P_VALUES)))
            cut(sizes)
            row("Age, years", ["54.2 (12.1)", "55.0 (11.8)"])
        elif kind == "subtypes":
            # A row, and the subtypes of what it counts: shares of that count, which is at
            # most half its arm's, so that the largest subtype is not its column's share.
            parent = draw(name)
            within = [draw(st.integers(10, n // 2)) for n in sizes]
            shares(f"{parent}, n (%)", within,
                   [_printed(c, n, places) for c, n in zip(within, sizes, strict=True)], sizes)
            # Its label with a P beside it or bare (round 3 of #314: always a P, so the bare
            # label was held by a corruption case alone).
            row(f"{parent} type", ["", ""], draw(st.sampled_from(P_VALUES)))
            # The run with the row after them does not add up to 100, so nothing says the
            # subtypes are shares where the header does not (round 3 of #314); where it does,
            # they are let off as shares of their own total.
            cut(within, read=(0,))
            # The next characteristic straight after them, with nothing in its label to say
            # it holds shares: read where its header says so, and not one of the subtypes
            # (round 2 of #314). A tenth of its arm or more, so that it cannot be.
            counts = [draw(st.integers(n // 10, n)) for n in sizes]
            percents = [_printed(c, n, places) for c, n in zip(counts, sizes, strict=True)]
            row(draw(name), [f"{count(c)} ({p})" for c, p in zip(counts, percents, strict=True)])
            expected.append((len(lines), counts[0], percents[0], sizes[0], False, False))
        elif kind == "own":
            owns = [draw(st.integers(10, 900)) for _arm in sizes]
            counts, percents = counted(owns)
            which = draw(st.integers(0, 1))
            percents = _wrong(draw, percents, which, places)
            shares(f"{draw(name)}, n/N (%)", counts, percents, owns, wrong=which, own=True)
        else:
            # Shares of the row's own total, which is at most half the smaller arm's, so
            # that neither is its column's share.
            total = draw(st.integers(10, min(sizes) // 2))
            first = draw(st.integers(-(-total // 5), total * 4 // 5))
            counts = [first, total - first]
            shares(f"{draw(name)}, n (%)", counts,
                   [_printed(c, total, places) for c in counts], sizes)
    lines += ["", draw(sentence).capitalize() + ".", ""]
    # A table whose header names no denominator: its shares are read, and held to nothing.
    lines += ["| Outcome | Cases | Controls | P |", "|---|---|---|---|"]
    shares(f"{draw(name)}, n (%)", *counted(sizes), [None, None])
    lines += ["", "```", fenced, "```", ""]
    shown = f"{count(sizes[0] // 3)} ({draw(st.integers(1, 99))}.0%)"
    lines += [f"{draw(sentence).capitalize()} {shown} {draw(sentence)}.", ""]
    return "\n".join(lines), expected


# ------------------------------------------------------- a table's means of whole numbers

#: Rows of means of whole numbers, as an auditor names them: a scale's score, a count.
WHOLE_LABELS = (
    "Pain score", "Number of visits", "Days in hospital", "Items endorsed",
    "Satisfaction rating", "Falls in the year",
)  # fmt: skip
#: Rows of means that are not of whole numbers, which nobody names.
MEASURES = ("Age, years", "Body mass index, kg/m2", "Systolic pressure, mmHg")
#: The kinds of row each table of `mean_tables` holds one of.
MEAN_ROWS = ("right", "wrong", "noted", "own", "zero", "change", "unnamed", "inside")

#: A mean as the reading finds it: its line, the mean as printed with an ASCII minus, its
#: n, whether it can be the mean of n whole numbers (None where every mean printed to its
#: places can), and whether it is uncertain.
Meant = tuple[int, str, int, "bool | None", bool]


def _a_mean(total: int, count: int, places: int, rounding: str = ROUND_HALF_UP) -> str:
    """`total` over `count`, rounded to `places`."""
    step = Decimal(1).scaleb(-places)
    return str((Decimal(total) / Decimal(count)).quantize(step, rounding=rounding))


def _fits(printed: str, count: int) -> bool:
    """Whether some whole total over `count` is within half a unit of `printed`'s last
    place, tried total by total."""
    value = Fraction(Decimal(printed))
    half = Fraction(1, 2 * 10 ** len(printed.partition(".")[2]))
    first = math.floor((value - half) * count) - 1
    return any(abs(Fraction(total, count) - value) <= half
               for total in range(first, first + int(2 * half * count) + 4))  # fmt: skip


@cache
def _every_mean_fits(count: int, places: int) -> bool:
    """Whether every mean printed to `places` is a whole total over `count`, tried mean by
    mean over one unit: so for 10 to the power of the places or more, and for a few just
    under, 96 at two places (round 1 of #331)."""
    step = Decimal(1).scaleb(-places)
    return all(_fits(str((k * step).quantize(step)), count) for k in range(10**places))


def _testable(count: int, places: int) -> int:
    """`places`, or one more where every mean printed to it fits `count`."""
    return places + 1 if _every_mean_fits(count, places) else places


def _no_mean(draw: st.DrawFn, count: int, places: int) -> str:
    """A mean printed to `places` that no whole total over `count` gives, near one that
    some total does. Some mean printed to `places` is none, so there is one."""
    assert not _every_mean_fits(count, places)
    step = Decimal(1).scaleb(-places)
    start = Decimal(_a_mean(draw(st.integers(count, 6 * count)), count, places))
    way = draw(st.sampled_from((1, -1)))
    for moved in range(1, 10**places):
        printed = str((start + way * moved * step).quantize(step))
        if not printed.startswith("-") and not _fits(printed, count):
            return printed
    raise AssertionError(f"every mean fits {count}")  # pragma: no cover


@st.composite
def mean_tables(draw: st.DrawFn) -> tuple[str, list[str], list[Meant]]:
    """A paper with a table of means, whose header names each arm's n, the first under 100
    and the second 100 or more, a row of each kind of `MEAN_ROWS` in an order drawn: means
    of whole numbers that a total gives, and one that none does, with a plus-minus sign; a
    row whose label carries a footnote marker, and one whose label names an n of its own;
    means printed to two places that end in a nought; a change, negative, with a minus
    sign; a row of means of a measure that nobody names, one of which no total gives; and a
    row whose label holds a named one inside a word. Then a table of two arms of a multiple
    of 8 each, headed by the name of the scale its row holds, whose means are half a unit
    from a total, one rounded down and one up; a table whose header names no n; the wrong
    row in a fenced listing; and a mean in a sentence, none of which is held to anything but
    the first. With the labels an auditor names, as they would type them, and each mean the
    reading finds (`Meant`), in order."""
    sizes = [draw(st.integers(10, 99)), draw(st.integers(100, 999))]
    labels = list(draw(st.permutations(WHOLE_LABELS)))
    kinds = ("right", "wrong", "noted", "own", "zero", "change")
    named = dict(zip(kinds, labels, strict=True))
    sentence = st.lists(st.sampled_from(FILLER), min_size=2, max_size=6).map(" ".join)
    lines: list[str] = [draw(sentence).capitalize() + ".", ""]
    expected: list[Meant] = []

    def spread() -> str:
        return f"{draw(st.integers(0, 9))}.{draw(st.integers(0, 9))}"

    def row(label: str, cells: list[str]) -> None:
        lines.append("| " + " | ".join([label, *cells]) + " |")

    def found(means: list[str], counts: list[int], *, uncertain: bool = False,
              wrong: int | None = None) -> None:  # fmt: skip
        """What the reading finds in the row just written."""
        for at, (mean, count) in enumerate(zip(means, counts, strict=True)):
            places = len(mean.partition(".")[2])
            verdict = None if _every_mean_fits(count, places) else at != wrong
            expected.append((len(lines), mean.replace("\N{MINUS SIGN}", "-"), count,
                             verdict, uncertain))  # fmt: skip

    def right(counts: list[int], places: int) -> list[str]:
        return [_a_mean(draw(st.integers(0, 6 * n)), n, places) for n in counts]

    headers = [draw(st.sampled_from(HEADED)).format(arm=arm, n=n)
               for arm, n in zip(("Treated", "Control"), sizes, strict=True)]  # fmt: skip
    row("Characteristic", headers)
    lines.append("|---|---|---|")
    fenced = ""
    for kind in draw(st.permutations(MEAN_ROWS)):
        places = draw(st.integers(1, 3))
        if kind == "right":
            means = right(sizes, places)
            row(f"{named[kind]}, mean (SD)", [f"{m} ({spread()})" for m in means])
            found(means, sizes)
        elif kind == "wrong":
            wrong = _no_mean(draw, sizes[0], _testable(sizes[0], max(places, 2)))
            means = [wrong, right(sizes[1:], places)[0]]
            row(named[kind], [f"{m} \N{PLUS-MINUS SIGN} {spread()}" for m in means])
            found(means, sizes, wrong=0)
            fenced = "\n".join([*lines[2:4], lines[-1]])
        elif kind == "noted":
            marker, last = draw(st.sampled_from(MARKERS))
            label = f"{named[kind]}, mean{marker}" if last else f"{named[kind]}{marker}, mean"
            means = right(sizes, places)
            row(label, means)
            found(means, sizes, uncertain=True)
        elif kind == "own":
            means = right(sizes, 2)
            row(f"{named[kind]} (n = {draw(st.integers(5, 90))})",
                [f"{m} ({spread()})" for m in means])  # fmt: skip
            found(means, sizes, uncertain=True)
        elif kind == "zero":
            # Two places, the second a nought: 2.50 is two places, not one. Three where n
            # has every mean at two.
            n, at = sizes[0], _testable(sizes[0], 2)
            totals = [t for t in range(n, 6 * n) if _a_mean(t, n, at).endswith("0")]
            means = [_a_mean(draw(st.sampled_from(totals)), n, at), right(sizes[1:], 2)[0]]
            row(named[kind], [f"{m} [{spread()}]" for m in means])
            found(means, sizes)
        elif kind == "change":
            means = [_a_mean(-draw(st.integers(1, 3 * n)), n, max(places, 2)) for n in sizes]
            row(f"Change in {named[kind].lower()}",
                [f"{m.replace('-', chr(0x2212))} ({spread()})" for m in means])  # fmt: skip
            found(means, sizes)
        elif kind == "unnamed":
            wrong = _no_mean(draw, sizes[0], _testable(sizes[0], 2))
            cells = [f"{wrong} ({spread()})", right(sizes[1:], 1)[0]]
            row(draw(st.sampled_from(MEASURES)), cells)
        else:
            row(f"Re{labels[0].lower()}", [f"{m} ({spread()})" for m in right(sizes, 2)])
    lines += ["", draw(sentence).capitalize() + ".", ""]
    # Two arms of a multiple of 8, whose means are half a unit from a total: odd/8 is a
    # third place of 5. Printed rounded down in the first and up in the second.
    # Not 80 or 96, at which every mean fits: the ties would say nothing.
    eighths = 8 * draw(st.sampled_from((1, 2, 3, 4, 5, 6, 7, 8, 9, 11)))
    odd = [eighths // 8 * (2 * draw(st.integers(0, 20)) + 1) for _arm in range(2)]
    # Its header's first cell is the scale's name, a named label: still a header, whose n
    # holds for the columns under it (round 1 of #331).
    lines += [f"| {labels[1]} | First (n = {eighths}) | Second (n = {eighths}) |",
              "|---|---|---|"]  # fmt: skip
    means = [_a_mean(odd[0], eighths, 2, ROUND_HALF_DOWN), _a_mean(odd[1], eighths, 2)]
    row(labels[1], means)
    found(means, [eighths, eighths])
    # A table of 80 or 96, at which every mean printed to two places is possible though
    # either is under 100: not assessable (round 2 of #331).
    every = draw(st.sampled_from((80, 96)))
    lines += ["", f"| {labels[2]} | All (n = {every}) |", "|---|---|"]
    means = right([every], 2)
    row(labels[2], means)
    found(means, [every])
    # A table whose header names no n: its means are held to nothing.
    lines += ["", "| Outcome | Cases | Controls |", "|---|---|---|"]
    row(labels[0], right(sizes, 2))
    lines += ["", "```", fenced, "```", ""]
    said = _no_mean(draw, sizes[0], _testable(sizes[0], 2))
    lines += [f"{draw(sentence).capitalize()} {said} {draw(sentence)}.", ""]
    # The labels as an auditor would type them: in lower case, one of them the label of
    # the rows inside whose words it stands.
    return "\n".join(lines), [label.lower() for label in labels], expected


# ------------------------------------------------- a number an earlier output printed

#: The ways a paper prints one number that this one prints otherwise: as it is, its
#: thousands grouped, a middle dot for the point, a percent sign after it, a minus sign
#: before it, to fewer or more places than this paper, and below one with no zero before its
#: point (".45").
PRINTINGS = ("as it is", "grouped", "middle dot", "percent", "minus", "coarser", "finer",
             "no leading zero")  # fmt: skip
#: What a paper groups thousands with: a comma, a space, a thin space, a no-break space and
#: a narrow no-break one, by code point since each looks like a space.
GROUPS = (",", " ", chr(0x2009), chr(0x00A0), chr(0x202F))


def _grouped(text: str, by: str) -> str:
    whole, point, fraction = text.partition(".")
    sign, digits = ("-", whole[1:]) if whole.startswith("-") else ("", whole)
    parts = []
    while len(digits) > 3:
        digits, parts = digits[:-3], [digits[-3:], *parts]
    return sign + by.join([digits, *parts]) + point + fraction


def _printed_as(text: str, kind: str, by: str) -> str:
    if kind == "grouped":
        return _grouped(text, by)
    if kind == "middle dot":
        return text.replace(".", chr(0x00B7))
    if kind == "percent":
        return text + "%"
    if kind == "minus":
        return text.replace("-", chr(0x2212))
    if kind == "no leading zero" and text.lstrip("-").startswith("0."):
        return text.replace("0.", ".", 1)
    return text


@st.composite
def printings(draw: st.DrawFn) -> list[dict[str, Any]]:
    """One number of this paper, printed by an earlier output in each of the ways a paper
    prints one, and the same printing of a number a unit and a half of the coarser
    printing away. The first is the value; the second is not, however it was rounded:
    each side is at most half a unit from what it rounds."""
    cases = []
    for kind in PRINTINGS:
        here = draw(st.integers(1 if kind == "coarser" else 0, 3))
        if kind == "coarser":
            there = draw(st.integers(0, here - 1))
        elif kind == "finer":
            there = draw(st.integers(here + 1, 4))
        else:
            there = draw(st.integers(1 if kind == "no leading zero" else 0, 3))
        low, high = {"grouped": (1000.0, 1e7), "no leading zero": (0.001, 0.94)}.get(
            kind, (0.001, 999.0)
        )
        value = draw(st.floats(low, high, allow_nan=False, allow_infinity=False))
        if kind == "minus" or (kind != "grouped" and draw(st.booleans())):
            value = -value
        unit = 10.0 ** -min(here, there)
        moved = value + draw(st.sampled_from((1.5, -1.5))) * unit
        by = draw(st.sampled_from(GROUPS))
        cases.append({
            "kind": kind,
            "value": value,
            "display": f"{value:.{here}f}",
            "printed": _printed_as(f"{value:.{there}f}", kind, by),
            "moved": _printed_as(f"{moved:.{there}f}", kind, by),
        })  # fmt: skip
    return cases


# ---------------------------------------------------------------------- what an edit holds

#: A binding, a citation and a number in each of the ways one is written: what `reworded`
#: holds to its place. A sign of comparison before a number or a binding is part of it.
HELD = (
    "{{results.ror.point}}", "{{ results.n.total }}", "{{lit.agency.count}}", "[@smith2020]",
    "[@smith2020; @lee2019, p. 12]", "@doe2018", "-@lee2019", "3.84", "-0.5", "1,200", "77",
    "(n = 12)", "5 %", "(P < 0.05)", "P \N{LESS-THAN OR EQUAL TO} {{results.p}}", "age >= 18",
    "P \\> 0.2",
)  # fmt: skip


#: What names them, written as a manuscript writes it, for `texts` to plant.
NAMED = (
    "Ada Example", "A. Example", "Example, A.", "Mary Ann van der Berg", "M. van der Berg",
    "0000-0002-1825-0097", "ada.example@invalid.example", "Department of Clinical Pharmacology",
)  # fmt: skip


@st.composite
def edits(draw: st.DrawFn) -> tuple[str, str]:
    """A manuscript and what an edit made of it: the same text, one of its paragraphs moved
    to the end, one taken out, another manuscript altogether, or sentences whose claim was
    made stronger, weaker or turned round (`claim_edits`)."""
    kind = draw(st.sampled_from(("the same", "moved", "cut", "another", "claims")))
    if kind == "claims":
        before, after, _told = draw(claim_edits())
        return before, after
    before = draw(texts(HELD))
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


# ------------------------------------------------------------- how strongly a sentence claims

#: Words that set how strongly a sentence claims, by what each is: a class, or the rung of
#: the ladder counted from consistency. Written here and not read from the data file, so
#: that a rule broken in reading the file does not draw its own inputs.
CLAIMED: dict[str | int, tuple[str, ...]] = {
    "hedge": ("may", "might", "could", "possibly", "appears", "seemed"),
    "limit": ("only", "in this sample", "under these conditions"),
    "negation": (
        "not", "no", "never", "didn't", "didn\N{RIGHT SINGLE QUOTATION MARK}t", "cannot",
        "non-significant",
    ),
    0: ("consistent with", "suggests", "suggestive of"),
    1: ("associated", "correlated", "related to", "linked to"),
    2: ("predicts", "predicted", "predictive of"),
    3: ("contributes to", "contributed to"),
    4: ("increased", "reduces", "led to", "affects", "resulted in"),
    5: ("caused", "causes", "causal", "demonstrated that"),
}  # fmt: skip
_RUNGS = tuple(kind for kind in CLAIMED if isinstance(kind, int))
#: What looks like a word of those and is not read as one: a word in a compound, joined
#: before or after; a participle after an article; a capital that marks a name, of a word
#: read in lower case only too; a word in code or in a comment.
UNCLAIMED = (
    "drug-induced", "all-cause", "cause-specific", "an increased", "the associated",
    "a reduced", "the predicted", "in May", "the Only", "the Never", "Causes", "`may`",
    "<!-- not -->",
)  # fmt: skip
#: What an edit does to one sentence's claim, and what that is told as: nothing, a claim
#: made stronger or weaker, moved both ways, or turned round; "" where the code is drawn
#: with the edit. A sentence added, deleted, moved, split, joined or only rewrapped is told
#: nothing, nor is a month that opens a sentence. The front matter's abstract and an item
#: of a list are edited as one of `_SIMPLE`.
CLAIM_EDITS = {
    "reworded": None, "synonyms": None, "look-alikes gone": None, "look-alikes new": None,
    "added": None, "deleted": None, "moved": None, "rewrapped": None, "split": None,
    "joined": None, "opening month": None,
    "hedge gone": "claim-stronger", "hedge new": "claim-weaker",
    "limit gone": "claim-stronger", "limit new": "claim-weaker",
    "negation gone": "claim-negation", "negation new": "claim-negation",
    "opening negation gone": "claim-negation",
    "up": "claim-stronger", "down": "claim-weaker",
    "lowest up": "claim-stronger", "lowest down": "claim-weaker",
    "lowest kept": "claim-moved",
    "rung came": "", "rung left": "", "both ways": "claim-moved", "list item": "",
}  # fmt: skip
_SIMPLE = (
    "hedge gone", "hedge new", "limit gone", "limit new", "negation gone", "negation new",
)  # fmt: skip
#: What opens a line that opens a block: an item of a list, unordered or ordered, a heading,
#: a quotation, a row, and a line that holds only a comment, which is blanked and so a
#: blank line. "2)" is the ordered item no stop also cuts: "1." is one.
_BLOCK_OPENERS = ("- ", "* ", "+ ", "1. ", "2) ", "# ", "> ", "| ", "<!-- a note -->\n")
_PLAIN = tuple(word for word in FILLER if word != "the")


@st.composite
def claim_edits(draw: st.DrawFn) -> tuple[str, str, list[tuple[str, int]]]:
    """A text, what an edit made of it, and what is to be told: each finding's code and the
    line of the text after that it stands on.

    Every edit of `CLAIM_EDITS` is in every example, in a paragraph of its own and in an
    order drawn each time, so that a rule broken for one kind is seen under any seed, and
    every example opens with front matter whose abstract is edited. Each paragraph is
    followed by one that does not change, and a sentence that changes stands between two
    that do not: those line the texts up around what changed. The words around a claim's
    words are drawn again for the text after. That is the rewording, and it is free."""
    marks = iter(f"x{''.join(chr(97 + int(d)) for d in str(at))}" for at in range(10_000))

    def word(kind: str | int) -> str:
        return draw(st.sampled_from(CLAIMED[kind]))

    def stable() -> list[str]:
        return [word(kind) for kind in draw(st.lists(st.sampled_from(tuple(CLAIMED)), max_size=2))]

    def written(
        claims: list[str], mark: str, opening: str = "", *, stop: bool = True, wrap: bool = True
    ) -> str:
        """A sentence of filler words with `claims` among them, each after a word that is
        no article, and its mark, which makes it a sentence no other is. Ended by a stop
        or not, and wrapped over lines or on one."""
        tokens = [opening] if opening else []
        tokens += [draw(st.sampled_from(_PLAIN)), mark]
        for claim in claims:
            tokens += [draw(st.sampled_from(_PLAIN)), *claim.split(" ")]
        tokens.append(draw(st.sampled_from(_PLAIN)))
        breaks = (" ", " ", " ", "\n") if wrap else (" ",)
        gaps = [draw(st.sampled_from(breaks)) for _ in tokens[1:]]
        text = tokens[0] + "".join(gap + token for gap, token in zip(gaps, tokens[1:], strict=True))
        return text[0].upper() + text[1:] + ("." if stop else "")

    def ladder(*rungs: int) -> list[str]:
        return [word(rung) for rung in rungs]

    def pair(did: str) -> tuple[list[str], list[str], str]:
        """The claim words of one sentence before and after, and the code it is told with."""
        kept = stable()
        told = CLAIM_EDITS[did] or ""
        if did in ("reworded", "rewrapped", "opening negation gone", "opening month"):
            return kept, list(draw(st.permutations(kept))), told
        if did == "synonyms":
            kinds = ("hedge", "limit", "negation", *_RUNGS)
            was = [word(kind) for kind in kinds]
            now = [draw(st.sampled_from([other for other in CLAIMED[kind] if other != one]))
                   for kind, one in zip(kinds, was, strict=True)]  # fmt: skip
            return was, now, told
        if did.startswith("look-alikes"):
            planted = list(draw(st.permutations(UNCLAIMED)))
            return (planted, [], told) if did.endswith("gone") else ([], planted, told)
        kind = did.split()[0]
        if kind in ("hedge", "limit", "negation"):
            claim = word(kind)
            if did.endswith("gone"):
                return [*kept, claim], kept, told
            return kept, [*kept, claim], told
        plain = [one for one in kept if not any(one in CLAIMED[rung] for rung in _RUNGS)]
        low, high = sorted(draw(st.lists(st.sampled_from(_RUNGS), min_size=2, max_size=2,
                                         unique=True)))  # fmt: skip
        rung = draw(st.sampled_from(_RUNGS))
        if did == "up":
            return kept + ladder(low), kept + ladder(high), told
        if did == "down":
            return kept + ladder(high), kept + ladder(low), told
        if did == "lowest up":
            return plain + ladder(low, high), plain + ladder(high), told
        if did == "lowest down":
            return plain + ladder(high), plain + ladder(low, high), told
        if did == "lowest kept":
            return plain + ladder(low, high), plain + ladder(low), told
        if did == "rung came":
            return plain, plain + ladder(rung), "claim-weaker" if rung == 0 else "claim-stronger"
        if did == "rung left":
            return plain + ladder(rung), plain, "claim-stronger" if rung == 0 else "claim-weaker"
        # Both ways: a hedge new, and a word moved up the ladder.
        return ladder(low), [word("hedge"), *ladder(high)], told

    # The front matter: its title stands, and its abstract is edited. Each value is on one
    # line, as YAML has a plain value.
    title = written(stable(), next(marks), wrap=False)
    was, now, told = pair(draw(st.sampled_from(_SIMPLE)))
    mark = next(marks)
    ahead = f"---\ntitle: {title}\nabstract: "
    before: list[str] = [f"{ahead}{written(was, mark, wrap=False)}\n---"]
    #: The paragraphs after, each with the code it is told with and the text in front of
    #: the sentence told, where one is.
    after: list[tuple[str, str, str]] = [(f"{ahead}{written(now, mark, wrap=False)}\n---",
                                          told, ahead)]  # fmt: skip
    unchanged = written(stable(), next(marks))
    before.append(unchanged)
    after.append((unchanged, "", ""))
    moved = ""
    for did in draw(st.permutations(tuple(CLAIM_EDITS))):
        first, last = written(stable(), next(marks)), written(stable(), next(marks))
        gap = draw(st.sampled_from((" ", "\n")))
        if did in ("added", "deleted", "moved"):
            claims = [*stable(), word(draw(st.sampled_from(tuple(CLAIMED))))]
            paragraph = written(claims, next(marks))
            if did != "added":
                before.append(paragraph)
            if did == "added":
                after.append((paragraph, "", ""))
            elif did == "moved":
                moved = paragraph
        elif did in ("split", "joined"):
            # One sentence made two, or two made one, with the same words of their claim:
            # an unequal stretch, read whole.
            one, other = stable(), [*stable(), word(draw(st.sampled_from(tuple(CLAIMED))))]
            mark, second = next(marks), next(marks)
            whole = written([*one, *other], mark)
            halves = f"{written(one, mark)}{gap}{written(other, second)}"
            was_, now_ = (whole, halves) if did == "split" else (halves, whole)
            before.append(f"{first}{gap}{was_}{gap}{last}")
            after.append((f"{first}{gap}{now_}{gap}{last}", "", ""))
        elif did == "list item":
            # Lines that open blocks, with no stop at their ends: only the lines cut them.
            # One paragraph for each way a line opens one, the edited line opened so, since
            # a rule broken for one of them is seen only there. The lines around it stand.
            for opener in draw(st.permutations(_BLOCK_OPENERS)):
                was, now, told = pair(draw(st.sampled_from(_SIMPLE)))
                mark = next(marks)
                top = "- " + written(stable(), next(marks), stop=False)
                low = "- " + written(stable(), next(marks), stop=False)
                item_was = opener + written(was, mark, stop=False)
                item_now = opener + written(now, mark, stop=False)
                before.append(f"{top}\n{item_was}\n{low}")
                after.append((f"{top}\n{item_now}\n{low}", told, f"{top}\n{opener}"))
        else:
            was, now, told = pair(did)
            mark = next(marks)
            opening = {"opening negation gone": "not", "opening month": "May"}.get(did, "")
            sentence = written(was, mark, opening)
            # Rewrapped, the sentence is its words on one line.
            edited = " ".join(sentence.split()) if did == "rewrapped" else written(now, mark)
            before.append(f"{first}{gap}{sentence}{gap}{last}")
            after.append((f"{first}{gap}{edited}{gap}{last}", told, f"{first}{gap}"))
        unchanged = written(stable(), next(marks))
        before.append(unchanged)
        after.append((unchanged, "", ""))
    if moved:
        after.append((moved, "", ""))
    expected = []
    line = 1
    for paragraph, told, ahead in after:
        if told:
            expected.append((told, line + ahead.count("\n")))
        line += paragraph.count("\n") + 2
    return (
        "\n\n".join(before) + "\n",
        "\n\n".join(paragraph for paragraph, _, _ in after) + "\n",
        expected,
    )


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
    "prose quotations": texts(QUOTED),
    "passages": passage_files().map(lambda drawn: drawn[0]),
    "mask": texts(TERMS),
    "latex mask": latex_texts(),
    "latex refusals": latex_texts(),
    "latex sections": latex_texts(),
    "hidden": texts(TERMS),
    "own words": texts(TERMS),
    "spans": texts(),
    "sections": texts(),
    "summaries": st.fixed_dictionaries(
        {"text": summaries(), "abstract title": st.sampled_from((None, "Summary"))}
    ),
    "numbers": st.fixed_dictionaries(
        {
            "text": texts(POINTED),
            "terms": st.lists(
                st.sampled_from(("CYP3A4", "COVID-19", "CO2", "HbA1c", "1,3-BDG")), max_size=2
            ),
        }
    ),
    "interval order": intervals(),
    "pointers": numbered_displays().map(lambda drawn: {"files": drawn[0]}),
    "quoted whole": texts(WHOLE),
    "labels": texts(LABELLED),
    "data dates": texts(DATED),
    "deviations": texts(),
    "planned results": planned_plans().map(lambda drawn: drawn[0]),
    "plan variables": collection_plans().map(lambda drawn: {"plan": drawn[0],
                                                            "names": drawn[1]}),
    "vocabulary": st.fixed_dictionaries({"text": texts(TERMS), "entries": vocabularies()}),
    "vector figure": vector_figures().map(lambda drawn: drawn[0]),
    # As text, a byte a character, so that the bytes pass to a reader as they are.
    "pdf figure": pdf_figures().map(lambda drawn: drawn[0].decode("latin-1")),
    "quote words": st.fixed_dictionaries(
        {"quote": texts(), "value": st.sampled_from(("2.6", "14", "1 in 4", "0.05", "IgG4"))}
    ),
    "quote placement": nearly_quoted(),
    "suggested edit": suggested_edits(),
    "suggestion written": suggestion_writes(),
    "spelling": st.fixed_dictionaries(
        {
            "text": texts(SPELT),
            "variant": st.sampled_from(("en-GB", "en-US")),
            "accepted": st.lists(st.sampled_from(("color", "Tumour", "centre")), max_size=2),
        }
    ),
    "notation": texts(NOTATED),
    "reply numbers": texts(NOTATED),
    "quoted": texts(),
    "data statement": texts(DATA_IDENTIFIERS + TEMPORARY_LINKS + FIXED_LINKS),
    "placeholders": texts(
        tuple(written for written, _found in PLACEHOLDERS + LOWERED) + LOOKALIKES
    ),
    "residue": texts(tuple(written for written, _rule, _found in RESIDUE) + RESIDUE_LOOKALIKES),
    "typed releases": texts(RELEASED),
    "reported tests": texts(REPORTED),
    "reported intervals": texts(ESTIMATES),
    "table shares": share_tables().map(lambda drawn: drawn[0]),
    "whole-number means": mean_tables().map(
        lambda drawn: {"text": drawn[0], "labels": drawn[1]}
    ),
    "printed value": printings(),
    "units after": texts(BOUND_UNITS),
    "limit stated": st.fixed_dictionaries(
        {"text": texts(QUOTED_LIMITS), "value": st.sampled_from((3500, 4, 14, 35000, 500))}
    ),
    "abbreviations": st.fixed_dictionaries(
        {"text": texts(), "known": st.lists(st.sampled_from(("ROR", "CI", "II")), max_size=2)}
    ),
    "tex outside maths": lines(),
    "title": lines(),
    "title held": st.fixed_dictionaries({"cited": lines(), "registered": lines()}),
    "blind names": texts(NAMED),
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
