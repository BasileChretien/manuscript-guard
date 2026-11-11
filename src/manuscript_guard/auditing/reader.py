"""The report as a reader of the page or of the PDF is given it: without what only a script
and its command line need.

The text the command line prints says, for a script, what `--strict` counts and which flag
would have run a check: "(not counted by --strict)", "(--against)". A reader of the page runs
no script and types no flag, and a reader of the PDF may never have seen the command line
(the author's audit, 2026-11-11: "still hard to read and not user friendly"). The view the
page and the PDF draw (`report.view`) says the same things without them; the text keeps them,
word for word, since the page and CI hold it to the command line's.
"""

from __future__ import annotations

import re

#: What a reader is told of a finding `--strict` counts. Not that the audit failed: without
#: `--strict` it ends as having run (round 1 of #631).
FAILS = "(counted as an error)"

#: What the text says for a script, and what a reader is told instead. In order: a longer
#: form before the shorter it holds.
_FOR_A_READER: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r" \(a note, not counted by --strict\)"), " (a note)"),
    (re.compile(r" \(--design ([^;()]+); not counted by --strict\)"), r" (the design given: \1)"),
    (re.compile(r" \(not counted by --strict\)"), ""),
    (re.compile(r" \(counted by --strict\)"), f" {FAILS}"),
    (re.compile(r", whose faults --strict counts\."), ", whose faults are counted as errors."),
    (re.compile(r" \(--(?:against|lookup|minimum-cell-count|whole-numbers|design|dry-run)\)"),
     ""),
    (re.compile(r"Nothing was looked up: --lookup asks"), "Nothing was looked up. A look-up asks"),
    (re.compile(r", and --lookup --dry-run shows what would be sent\."), "."),
    (re.compile(r"Point --against at the analysis outputs"), "Give the analysis outputs"),
    # The label as `repr` writes it, whatever quotes it holds (round 2 of #631).
    (re.compile(r"--whole-numbers (.+?): (?=no mean was read)"),
     r"The label \1, given as whole numbers: "),
    (re.compile(r"--dry-run sent nothing"), "nothing was sent"),
    (re.compile(r"--authors names them"), "no authors were given to the audit"),
    (re.compile(r"or to the one --english chooses\)"), "or to the one chosen for the paper)"),
    (re.compile(r", as `init --from` makes them;"), ";"),
    (re.compile(r", as `init --from` writes it\b"), ""),
    (re.compile(r'--details \(on the web page, the box ("[^"]+")\)'), r"the box \1"),
    (re.compile(r"give --against the outputs to compare them\b"),
     "give the audit the analysis outputs to compare them with"),
    (re.compile(r"--against names the outputs to compare the numbers with\."),
     "no analysis outputs were given to compare the numbers with."),
)  # fmt: skip

#: Markdown's marks of emphasis around words, which a .docx's converted text has where the
#: document prints bold or italics: "**CBL**", "*p*", "_et al._". Not inside a word, so that
#: a name from code, "code_names_kept", keeps its underscores; nor inside a code span,
#: "`__init__`", which is quoted as typed (round 1 of #631). A context the gate cut inside a
#: code span pairs its lone backtick with the next (DESIGN.md, Known gaps).
_STARRED = re.compile(r"(?<![\w*])(\*\*|\*)(?=[^\s*])(.+?)(?<=[^\s*])\1(?![\w*])")
_UNDERSCORED = re.compile(r"(?<![\w_])(__|_)(?=[^\s_])(.+?)(?<=[^\s_])\1(?![\w_])")
_CODE = re.compile(r"(`+)[^`]+?\1")
#: A character of Unicode's private use, which no context holds, standing in for a code span.
_HOLD = chr(0xE000)
_HELD = re.compile(f"{_HOLD}(\\d+){_HOLD}")
#: How deep one emphasis may stand in another, "*a **b** c*", and still be taken off.
_NESTED = 3


def for_a_reader(text: str) -> str:
    """`text` without what it says only for a script or its command line (`_FOR_A_READER`)."""
    for pattern, said in _FOR_A_READER:
        text = pattern.sub(said, text)
    return text


def _unmarked(text: str) -> str:
    for _depth in range(_NESTED):
        plain = _UNDERSCORED.sub(r"\2", _STARRED.sub(r"\2", text))
        if plain == text:
            break
        text = plain
    return text


def excerpt(context: str) -> str:
    """A finding's context as the document prints it: Markdown's marks of emphasis taken off,
    outside its code spans. Its ends are not marked as cut: whether the gate cut it there is
    the gate's to say (round 1 of #631: an end it did not cut, and a list of samples, are
    no cut quote)."""
    if _HOLD in context:
        return _unmarked(context)
    # Each code span set aside under a stand-in while the marks around it are taken off, so
    # that "**`x_y`**" loses its stars and keeps its underscore.
    codes: list[str] = []

    def held(found: re.Match[str]) -> str:
        codes.append(found.group(0))
        return f"{_HOLD}{len(codes) - 1}{_HOLD}"

    plain = _unmarked(_CODE.sub(held, context))
    return _HELD.sub(lambda found: codes[int(found.group(1))], plain)


def _place(place: dict) -> dict:
    return {**place, "message": for_a_reader(place["message"]),
            "hint": place["hint"] and for_a_reader(place["hint"]),
            "context": place["context"] and excerpt(place["context"])}  # fmt: skip


def _kind(kind: dict) -> dict:
    return {**kind, "hint": kind["hint"] and for_a_reader(kind["hint"]),
            "places": [_place(place) for place in kind["places"]]}  # fmt: skip


def readable(view: dict) -> dict:
    """The view the page and the PDF draw, said for a reader: every line of it through
    `for_a_reader`, and every finding's context as an excerpt. With the phrases that name
    `--strict` said otherwise, the line that says what it counts is left out too: the page
    draws that line only where the view gives it (round 1 of #627)."""
    return {
        **view,
        "strict": None,
        "header": [for_a_reader(line) for line in view["header"]],
        "notes": [[for_a_reader(heading), [for_a_reader(item) for item in said]]
                  for heading, said in view["notes"]],
        "checks": [[name, for_a_reader(said)] for name, said in view["checks"]],
        "words": [{**paper, "note": paper["note"] and for_a_reader(paper["note"]),
                   "kinds": [_kind(kind) for kind in paper["kinds"]]}
                  for paper in view["words"]],
        "sections": [[for_a_reader(heading), for_a_reader(text)]
                     for heading, text in view["sections"]],
        "closing": for_a_reader(view["closing"]),
    }  # fmt: skip
