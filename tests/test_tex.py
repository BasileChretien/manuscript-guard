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
THIN_SPACE = chr(0x2009)
TAB = chr(9)
E_ACUTE = chr(0xE9)
#: A letter since Unicode 15.1, which pandoc 3.9 knows and Python before 3.13 does not, and
#: a code point no Unicode has named.
NEW_LETTER = chr(0x2EBF0)
UNNAMED = chr(0x50000)

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
    "a digit after maths in a name": (f"TGF-${B}beta$1 signalling", B + "beta"),
    "a dollar amount that pairs with the opening dollar sign": (
        f"Costs at $50,000 per QALY of TNF-${B}alpha$ inhibitors",
        B + "alpha",
    ),
    "a letter this Python may not know": (
        f"Outcomes {B}{NEW_LETTER}x and after",
        B + NEW_LETTER + "x",
    ),
    # Each of these five was passed by the rule with one line of it changed, and by every
    # test then: a space that is no ASCII space after the opening dollar sign, a tab before
    # the closing one, a brace after a backslash in a text group, and four dollar signs
    # where display maths would open.
    "a thin space after the opening dollar sign": (f"${THIN_SPACE}{G}$", G),
    "a tab before the closing dollar sign": (f"${G}{TAB}$", G),
    "a brace after a backslash in a text group": (f"${B}text{{${B}}}{G}$ x", G),
    "four dollar signs where display maths would open": (f"$$$$$$ $${B}g$$", B + "g"),
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
    "an escaped space in a subscript": (f"~a{B} {B}{G}~", G, "~"),
}

#: A character reference in what a subscript or a superscript can hold. Pandoc resolves the
#: references and escapes there and reads the result as Markdown, once more for each script
#: around it, and leaves a carriage return out as it does: so a reference can make a
#: backslash, the letter after one, the sign of another script, or nothing at all between
#: a backslash and a letter. Resolving them once passed a script in a script, and a
#: reference for a carriage return. The reference is the finding, and nothing is resolved.
#: Each line, the reference named, and the sign of the script that holds it.
REFERENCE = {
    "for the backslash in a superscript": ("IFN-^&bsol;gamma^ release assays", "&bsol;", "^"),
    "numbered, in a subscript": ("x~&#92;gamma~ y", "&#92;", "~"),
    "in hexadecimal": ("x^&#x5c;gamma^ y", "&#x5c;", "^"),
    "for the letter": (f"~{B}{B}&#103;amma~", "&#103;", "~"),
    "for a Greek letter": (f"TNF~{B}{B}&alpha;~ signalling", "&alpha;", "~"),
    "in a superscript past a bracket": ("[a] x^&bsol;gamma^ y", "&bsol;", "^"),
    "a subscript in a superscript, the ampersand by reference": (
        "^~&amp;bsol;gamma~^",
        "&amp;",
        "^",
    ),
    "the ampersand numbered": ("~^&#x26;#x5c;gamma^~", "&#x26;", "~"),
    "an escape inside the reference": (f"^~&{B}#92;gamma~^", f"&{B}#92;", "^"),
    "an escaped semicolon": (f"^~&bsol{B};gamma~^", f"&bsol{B};", "^"),
    "the letter by two references": (f"^~{B * 4}&amp;#103;amma~^", "&amp;", "^"),
    "the inner signs escaped": (f"^{B}~&amp;bsol;gamma{B}~^", "&amp;", "^"),
    "the inner signs by reference": ("^&#126;&amp;bsol;gamma&#126;^", "&#126;", "^"),
    "two scripts past a bracket": ("[a] x^~&amp;bsol;gamma~^ y", "&amp;", "^"),
    "two scripts after a subscript that holds a dollar sign": (
        "~$~ x^~&amp;bsol;gamma~^",
        "&amp;",
        "^",
    ),
    "three scripts": ("^~&Hat;&amp;amp;bsol;gamma&Hat;~^", "&Hat;", "^"),
    "a carriage return between the backslash and the letter": (
        "IFN-^&bsol;&#13;gamma^ release assays",
        "&bsol;",
        "^",
    ),
    "a carriage return after a doubled backslash": (f"~{B}{B}&#13;x~", "&#13;", "~"),
    "a carriage return in hexadecimal": (f"x~{B}{B}&#xd;gamma~ y", "&#xd;", "~"),
    "a carriage return past a bracket": (f"[a] x^{B}{B}&#13;gamma^", "&#13;", "^"),
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
    "a reference for a backslash outside a subscript": "x &bsol;gamma y",
    "one past a bracket and outside a subscript": "[a] &bsol;gamma and R&D; more",
    "an ampersand and a semicolon in a superscript's stretch, the wrong way round": "x^a;b&c^",
    "a dollar amount escaped before maths": (
        f"Costs at {B}$50,000 per QALY of TNF-${B}alpha$ inhibitors"
    ),
    "a digit inside the dollar signs, after a space and as a subscript": (
        f"TGF-${B}beta_1$ and ${B}geq$ 65 and ${B}beta$~1~"
    ),
    "two dollar amounts": "Costs of $5 and $10 per dose",
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
    "a comment sign in a command's braces": (
        f"A {B}textbf{{50% reduction}} in LDL",
        B + "textbf",
        "",
    ),
    "an end with no beginning": (f"The {B}end of the trial", B + "end", ""),
    "a code point no Unicode has named": (
        f"Outcomes {B}{UNNAMED}x and after",
        B + UNNAMED + "x",
        "",
    ),
    # A reference in a subscript or a superscript is reported whatever it stands for.
    "two references for backslashes in a superscript": ("^&bsol;&bsol;gamma^", "&bsol;", "^"),
    "a reference for an ampersand in a superscript": ("x^&amp;bsol;gamma^", "&amp;", "^"),
    "a reference for a Greek letter in a superscript": ("x^&alpha;^", "&alpha;", "^"),
    # It is not read to see whether it is a reference at all.
    "an ampersand that a semicolon follows in a subscript's stretch": (
        "H~2~O&CO;x",
        "&CO;",
        "~",
    ),
}


@pytest.mark.parametrize("case", list(OUTSIDE))
def test_tex_outside_maths_is_named(case: str) -> None:
    line, command = OUTSIDE[case]
    found = tex_outside_maths(line)
    assert found is not None
    assert (found.command, found.after) == (command, "")


@pytest.mark.parametrize("case", list(PAST_A_SIGN))
def test_tex_past_a_sign_that_can_hold_a_dollar_sign_is_named_with_the_sign(case: str) -> None:
    line, command, sign = PAST_A_SIGN[case]
    found = tex_outside_maths(line)
    assert found is not None
    assert (found.command, found.after, found.reference) == (command, sign, False)


@pytest.mark.parametrize("case", list(REFERENCE))
def test_a_reference_in_a_subscript_or_a_superscript_is_the_finding(case: str) -> None:
    line, reference, sign = REFERENCE[case]
    found = tex_outside_maths(line)
    assert found is not None
    assert (found.command, found.after, found.reference) == (reference, sign, True)


@pytest.mark.parametrize("case", list(INSIDE))
def test_tex_in_maths_and_a_backslash_that_is_no_tex_are_passed(case: str) -> None:
    assert tex_outside_maths(INSIDE[case]) is None


@pytest.mark.parametrize("case", list(OVER))
def test_where_the_rule_reports_what_pandoc_keeps(case: str) -> None:
    """Pinned so that a change in what the rule over-reports is seen, and DESIGN.md's
    account of it kept true."""
    line, command, sign = OVER[case]
    found = tex_outside_maths(line)
    assert found is not None
    assert (found.command, found.after) == (command, sign)
    assert found.reference is command.startswith("&")


#: Why the dollar sign directly before a command opened no maths, which the finding says:
#: the command stands between dollar signs, and "outside dollar signs" would be false.
UNREAD = {
    "a digit after the closing one": (f"TGF-${B}beta$1 signalling", "digit"),
    "a digit after it, the command first in the line": (f"${B}alpha$1-antitrypsin", "digit"),
    "a space before the closing one": (f"${G} $ after", "space"),
    "a tab before it": (f"${G}{TAB}$", "space"),
    "nothing closes it": (f"${B}alpha{B}", "open"),
    "an earlier dollar sign pairs with it": (
        f"Costs at $50,000 per QALY of TNF-${B}alpha$ inhibitors",
        "paired",
    ),
    "one in brackets pairs with it": (f"Costs ($) of TNF-${B}alpha$ inhibitors", "paired"),
    # The reason holds for every command up to the dollar sign that would have closed the
    # maths, and for none past it: only the one directly after the `$` was given it.
    "second after the dollar sign, a digit after the next": (
        f"Risk at $p {B}leq$0.05",
        "digit",
    ),
    "after a digit, a digit after the next": (f"The $2{B}alpha$4 chain", "digit"),
    "second, a space before the next": (f"Dose $x {B}pm $ y", "space"),
    "after a letter, nothing closing": (f"IFN-$x{G} release assays", "open"),
    "far after a dollar sign that nothing closes": (f"costs $5 and {G}", "open"),
    "past the dollar sign that would have closed, and after maths": (f"$a $b$ x {G}", ""),
    "past the dollar sign a digit follows, and after maths": (f"$a$5x$ {G}", ""),
    # No dollar sign that was tried stands before these.
    "an escaped dollar sign before the command": (f"{B}${G}{B}$", ""),
    "a space after the opening dollar sign": (f"x$ {G} $y", ""),
    "no dollar sign": (f"IFN-{G} release", ""),
}


@pytest.mark.parametrize("case", list(UNREAD))
def test_a_command_between_dollar_signs_that_are_no_maths_says_why(case: str) -> None:
    line, why = UNREAD[case]
    found = tex_outside_maths(line)
    assert found is not None
    assert found.unread == why


#: Whether a brace follows the command, where `$...$` around the command alone would be
#: no remedy: `$\textit${in vivo}` is printed as typed.
BRACES = {
    "a text command": (f"A {B}textit{{in vivo}} study", True),
    "an accent": (f"Beh{B}c{{c}}et disease", True),
    "a superscript as TeX writes it": (f"{B}textsuperscript{{18}}F-FDG PET", True),
    "a Greek letter": (f"IFN-{G} release", False),
    "a sign before a number": (f"12 {B}pm 3 months", False),
}


@pytest.mark.parametrize("case", list(BRACES))
def test_a_command_with_braces_after_it_is_known(case: str) -> None:
    line, braces = BRACES[case]
    found = tex_outside_maths(line)
    assert found is not None
    assert found.braces is braces


def test_a_finding_is_the_command_alone_where_nothing_else_is_known() -> None:
    assert tex_outside_maths(f"IFN-{G} release") == Tex(G)


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
    lost = [row[0] for row in (*OUTSIDE.values(), *PAST_A_SIGN.values(), *UNREAD.values())]
    lost += [row[0] for row in REFERENCE.values()]
    lost += [row[0] for row in BRACES.values()]
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
    + ["&bsol;", "&#92;", "&#103;", "&alpha;", "&dollar;", NEW_LETTER, THIN_SPACE]
    + ["&amp;", "&#13;", "&#126;", "&Hat;", "bsol;", "~", "^", B + "~", B + ";", B + "#"]
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
    "ampersands in a superscript": lambda n: "^" + "a&b" * n,
    "references past a bracket": lambda n: "[" + "&bsol; " * n,
    "superscripts past a bracket": lambda n: "[" + "^a& " * n,
    "circumflexes past a bracket": lambda n: "[" + "^" * n,
}


@pytest.mark.parametrize("case", list(LONG))
def test_a_long_line_takes_time_in_proportion(case: str, assert_linear) -> None:
    """The first draft of the rule read ahead from each one to the end of the line: 16,000
    tildes took 17 seconds and 4,000 `text` groups five, in what `check` runs and the hook
    at the start of a session with it."""
    assert tex_outside_maths(LONG[case](50)) is None
    assert_linear(LONG[case], tex_outside_maths, 2000, case)
