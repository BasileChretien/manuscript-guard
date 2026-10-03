"""TeX outside maths in one line of Markdown, against what pandoc makes of the line.

Pandoc reads a title, a short title and a keyword as Markdown. A backslash directly before
a letter is TeX to it wherever it stands, and the Word writer keeps TeX only as maths,
between dollar signs: `IFN-\\gamma release assays` passed `check` and a checked build, and
was printed `IFN-release assays`. With a number after it the number goes too: `12 \\pm 3
months` is printed without its `3`.

`tex_outside_maths` is a model of that reading, and what it disagrees with is pandoc, so the
tables below are held to pandoc itself where it is installed. The rule may report TeX that
pandoc keeps (`OVER` says where). It must never pass TeX that pandoc drops.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess

import pytest

from manuscript_guard.text.tex import Tex, tex_outside_maths

PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")

#: A backslash, written so that no tool between the author of a test and this file can
#: halve it or read it as the start of an escape.
B = chr(92)
G = B + "gamma"
NBSP = chr(0xA0)
E_ACUTE = chr(0xE9)

#: Lines pandoc drops TeX from, each with the command the rule names.
OUTSIDE = {
    "a Greek letter in prose": (f"IFN-{G} release assays", G),
    "a symbol before a number": (f"Outcomes at 12 {B}pm 3 months", B + "pm"),
    "a text command": (f"A {B}textit{{in vivo}} study", B + "textit"),
    "a path": (f"C:{B}Users{B}name", B + "Users"),
    "a letter that is not ASCII": (f"caf{B}{E_ACUTE}tude", B + E_ACUTE + "tude"),
    "after a doubled backslash": (f"IFN-{B}{B}{G} release", G),
    "between two pieces of maths": (f"$a$ {G} $b$", G),
    "a space after the opening dollar sign": (f"x$ {G} $y", G),
    "a no-break space after it": (f"${NBSP}{G}$", G),
    "a space before the closing one": (f"${G} $ after", G),
    "a digit after the closing one": (f"${G}$5 mg", G),
    "escaped dollar signs": (f"{B}${G}{B}$", G),
    "one dollar sign": (f"costs $5 and {G}", G),
    "maths never closed": (f"${B}alpha{B}", B + "alpha"),
    "two dollar signs never closed": (f"$${G}", G),
    "emphasis": (f"*{G}*", G),
}

#: Lines pandoc drops TeX from where a simpler reading of dollar signs sees maths: the
#: sign holds a `$` that opens nothing, or what it holds is read on its own. The command,
#: and the sign past which the rule reads no maths.
PAST_A_SIGN = {
    "code around the dollar signs": (f"`$` {G} `$`", G, "`"),
    "a tag holding one": (f'<span title="$">{G}</span>$x$', G, "<"),
    "a link's address holding one": (f"[a](http://x/$) {G} [b](http://y/$)", G, "["),
    "a citation key holding one": (f"@a$b {G} @c$d", G, "@"),
    "a subscript holding one": (f"~a${G}~ x$", G, "~"),
    "a superscript holding one": (f"^a${G}^ x$", G, "^"),
    "a doubled backslash in a subscript": (f"~a{B}{G}~", G, "~"),
    "a doubled backslash in a superscript": (f"x^{B}{G};^", G, "^"),
}

#: Lines pandoc drops nothing from, and the rule reports nothing in.
INSIDE = {
    "inline maths": f"IFN-${G}$ release assays",
    "maths opening on a digit": f"cost $5 and {G}$ after",
    "display maths": f"$$ {G} $$ display",
    "an escaped dollar sign in maths": f"$a{B}$ {G}$",
    "a dollar sign in a text group": f"${B}text{{a $ b}} {G}$ x",
    "a dollar sign that opens nothing before maths": f"a $x $y {G}$",
    "a no-break space after maths": f"${G}${NBSP}mg",
    "a no-break space before the closing dollar sign": f"${G}{NBSP}$",
    "a dollar sign after maths": f"${G}$$",
    "a dollar sign before maths": f"$${G}$",
    "a doubled backslash": f"IFN-{B}{G} release",
    "a backslash before a digit": f"x {B}1 y",
    "escaped signs": f"x {B}_ y {B}* z {B}$ w {B}% v",
    "a closing backslash": f"Outcomes of Foo{B}",
    "a subscript before maths": f"HbA~1c~ and TGF-${B}beta$",
    "a superscript before maths": f"x^2^ and ${G}$",
    "a tilde in maths": f"a ${G}~2~$ b",
    "emphasis around maths": f"*a ${G}* x$",
    "a bracket, a tag's sign and an at sign in maths": f"$[{G}]$ and $a<{G}$ and $a@{G}$",
    "quotation marks around maths": f'"a ${G}" x$',
    "an escaped bracket before maths": f"{B}[18F{B}]FDG and TGF-${B}beta$",
    "an escaped tilde before maths": f"{B}~$ and ${G}$",
    "no backslash": "A plain title",
    "nothing": "",
}

#: Lines pandoc drops nothing from and the rule reports all the same: past a sign after
#: which it reads no maths, and where it does not try a command as pandoc does. The
#: command and the sign, which is empty where there is none.
OVER = {
    "code": (f"`{G}` in code", G, "`"),
    "maths after a bracket": (f"[18F]FDG and TGF-${B}beta$", B + "beta", "["),
    "maths after a backtick": (f"`x` and ${G}$", G, "`"),
    "maths after an at sign": (f"a @ b ${G}$", G, "@"),
    "maths after a tag's sign": (f"p < 5 and ${G}$", G, "<"),
    "a doubled backslash after a bracket": (f"[a] {B}{G}", G, "["),
    "a doubled backslash after a circumflex": (f"x^{B}{G}", G, "^"),
    "maths in a superscript": (f"x^${G}$^", G, "^"),
    "maths after a subscript that holds a dollar sign": (f"~$~ ${G}$", G, "~"),
    "a brace never closed": (f"a {B}textbf{{unclosed study", B + "textbf", ""),
}


@pytest.mark.parametrize("case", list(OUTSIDE))
def test_tex_outside_maths_is_named(case: str) -> None:
    line, command = OUTSIDE[case]
    assert tex_outside_maths(line) == Tex(command, "")


@pytest.mark.parametrize("case", list(PAST_A_SIGN))
def test_tex_past_a_sign_that_can_hold_a_dollar_sign_is_named_with_the_sign(case: str) -> None:
    line, command, sign = PAST_A_SIGN[case]
    assert tex_outside_maths(line) == Tex(command, sign)


@pytest.mark.parametrize("case", list(INSIDE))
def test_tex_in_maths_and_a_backslash_that_is_no_tex_are_passed(case: str) -> None:
    assert tex_outside_maths(INSIDE[case]) is None


@pytest.mark.parametrize("case", list(OVER))
def test_where_the_rule_reports_what_pandoc_keeps(case: str) -> None:
    """Pinned so that a change in what the rule over-reports is seen, and DESIGN.md's
    account of it kept true."""
    line, command, sign = OVER[case]
    assert tex_outside_maths(line) == Tex(command, sign)


def readings(lines: list[str]) -> list[dict]:
    """Pandoc's reading of each line as a field of a header the build would write: a JSON
    string, which is how the build writes a title."""
    header = ["---"]
    header += [f"v{at}: {json.dumps(line, ensure_ascii=False)}" for at, line in enumerate(lines)]
    header += ["---", "", "text", ""]
    finished = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=chr(10).join(header).encode("utf-8"),
        capture_output=True,
        check=True,
    )
    meta = json.loads(finished.stdout)["meta"]
    return [meta[f"v{at}"] for at in range(len(lines))]


def dropped(reading: object) -> list[str]:
    """The raw TeX in a reading: what the Word writer leaves out."""
    if isinstance(reading, list):
        return [raw for item in reading for raw in dropped(item)]
    if not isinstance(reading, dict):
        return []
    if reading.get("t") in ("RawInline", "RawBlock") and reading["c"][0] in ("tex", "latex"):
        return [reading["c"][1]]
    return [raw for value in reading.values() for raw in dropped(value)]


@needs_pandoc
def test_the_tables_say_what_pandoc_does() -> None:
    lost = [row[0] for row in (*OUTSIDE.values(), *PAST_A_SIGN.values())]
    for line, reading in zip(lost, readings(lost), strict=True):
        assert dropped(reading), f"pandoc keeps the TeX of {line!r}"
    kept = [*INSIDE.values(), *(row[0] for row in OVER.values())]
    for line, reading in zip(kept, readings(kept), strict=True):
        assert not dropped(reading), f"pandoc drops TeX from {line!r}"


#: What a random line is made of: the signs pandoc reads maths, escapes, code, tags, links,
#: citations, subscripts and emphasis by, around a command and a few letters.
PIECES = (
    ["$"] * 10
    + [B] * 8
    + [" "] * 6
    + ["a", "g", "x", "5", "0", G, B + "text{", "text{", "{", "}", "}"]
    + [NBSP, chr(9), E_ACUTE, chr(0x3B1), chr(0x301), chr(0xB2)]
    + list("`<>[]()@*_^~\"'-.&!#=:/|%;,+?")
    + ["$$", B + "$", B + B, "~", "^"]
)
#: The same without the four signs after which the rule stops reading maths, so that most
#: lines try its reading of maths.
PLAIN = [piece for piece in PIECES if not set(piece) & set("`<[@")]


@needs_pandoc
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_the_rule_never_passes_a_line_pandoc_drops_tex_from(seed: int) -> None:
    """The rule is a model of pandoc's reading, and its last part came from lines like
    these: a subscript is read on its own, with its escapes read once already, so that
    maths cannot run past its end and a doubled backslash in it is one. Three such lines
    were passed before that, in the first 26,000 tried."""
    rng = random.Random(seed)
    lines = [
        "".join(
            rng.choice(PLAIN if rng.random() < 0.7 else PIECES)
            for _ in range(rng.randint(1, 8 + 4 * seed))
        )
        for _ in range(1000)
    ]
    missed = [
        line
        for line, reading in zip(lines, readings(lines), strict=True)
        if any(raw.startswith(B) for raw in dropped(reading)) and tex_outside_maths(line) is None
    ]
    assert missed == []


#: Lines the rule reads to their end, each made of what it reads ahead from: a dollar sign
#: that opens nothing, a `text` group in maths whose brace never closes, and a subscript.
LONG = {
    "dollar signs that open nothing": lambda n: "$ a" * n,
    "text groups never closed, in maths": lambda n: "$" + (B + "text{") * n + "$",
    "tildes": lambda n: "~" * n,
    "circumflexes": lambda n: "^a" * n + " x",
}


@pytest.mark.parametrize("case", list(LONG))
def test_a_long_line_takes_time_in_proportion(case: str, assert_linear) -> None:
    """The first draft of the rule read ahead from each one to the end of the line: 16,000
    tildes took 17 seconds and 4,000 `text` groups five, in what `check` runs and the hook
    at the start of a session with it."""
    assert tex_outside_maths(LONG[case](50)) is None
    assert_linear(LONG[case], tex_outside_maths, 2000, case)
