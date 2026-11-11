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

#: What a reader is told of a finding `--strict` counts.
FAILS = "(the audit fails on it)"

#: What the text says for a script, and what a reader is told instead. In order: a longer
#: form before the shorter it holds.
_FOR_A_READER: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r" \(a note, not counted by --strict\)"), " (a note)"),
    (re.compile(r" \(--design ([^;()]+); not counted by --strict\)"), r" (the design given: \1)"),
    (re.compile(r" \(not counted by --strict\)"), ""),
    (re.compile(r" \(counted by --strict\)"), f" {FAILS}"),
    (re.compile(r" \(--(?:against|lookup|minimum-cell-count|whole-numbers)\)"), ""),
    (re.compile(r"Nothing was looked up: --lookup asks"), "Nothing was looked up. A look-up asks"),
    (re.compile(r", and --lookup --dry-run shows what would be sent\."), "."),
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
#: a name from code, "code_names_kept", keeps its underscores.
_STARRED = re.compile(r"(?<![\w*])(\*\*|\*)(?=[^\s*])(.+?)(?<=[^\s*])\1(?![\w*])")
_UNDERSCORED = re.compile(r"(?<![\w_])(__|_)(?=[^\s_])(.+?)(?<=[^\s_])\1(?![\w_])")

#: What marks the ends of a quote cut from its paragraph.
CUT = "…"


def for_a_reader(text: str) -> str:
    """`text` without what it says only for a script or its command line (`_FOR_A_READER`)."""
    for pattern, said in _FOR_A_READER:
        text = pattern.sub(said, text)
    return text


def excerpt(context: str) -> str:
    """A finding's context as a quote from its paragraph: Markdown's marks of emphasis taken
    off, and its ends marked as cut, since the words around a finding are cut from the
    paragraph without regard to where a word ends."""
    text = _UNDERSCORED.sub(r"\2", _STARRED.sub(r"\2", context))
    return f"{CUT}{text}{CUT}"


def _place(place: dict) -> dict:
    return {**place, "message": for_a_reader(place["message"]),
            "hint": place["hint"] and for_a_reader(place["hint"]),
            "context": place["context"] and excerpt(place["context"])}  # fmt: skip


def _kind(kind: dict) -> dict:
    return {**kind, "hint": kind["hint"] and for_a_reader(kind["hint"]),
            "places": [_place(place) for place in kind["places"]]}  # fmt: skip


def readable(view: dict) -> dict:
    """The view the page and the PDF draw, said for a reader: every line of it through
    `for_a_reader`, and every finding's context as an excerpt. With no line naming `--strict`
    left, nor the line that says what it counts: the page draws that line where the view gives
    it (round 1 of #627)."""
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
