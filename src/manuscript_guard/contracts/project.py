"""Project discovery and the paper/authors configuration.

A project is any directory containing `paper.yaml`. Commands walk upwards to find it, so
they work from anywhere inside the tree, the way git does.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

import yaml
from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import (
    ContractError,
    Unreadable,
    load_schema,
    read_structured,
    read_text,
    validate,
)
from manuscript_guard.findings import Finding, Report, merge_all
from manuscript_guard.text.tex import Tex, tex_outside_maths

PAPER_FILE = "paper.yaml"
AUTHORS_FILE = "authors.yaml"

DEFAULT_PATHS = {
    "analysis": "analysis",
    "results": "results",
    "literature": "literature",
    "manuscript": "manuscript",
    "figures": "figures",
    "build": "build",
}


@dataclass(frozen=True)
class Project:
    root: Path
    paper: dict
    authors: dict | None

    def path(self, which: str) -> Path:
        configured = self.paper.get("paths", {}).get(which, DEFAULT_PATHS[which])
        return self.root / configured

    def setting(self, key: str) -> Any:
        """What a gate reads of one key of `paper.yaml`: its value as far as the schema
        accepts it. Of a list, and of settings under a key, the entries the schema accepts;
        of anything else, the value or None.

        The schema reports a wrong shape as a finding that names the key and fails at every
        stage, and the gate that read the value raised on it all the same: `terms: 5` was
        also "G2 could not run: TypeError: 'int' object is not iterable", under a hint that
        begins with a bug in the tool. So a gate reads only what the schema let through and
        runs as if the rest were not set. An entry of `conventions` or `terms` that is not
        read exempts nothing, so that reading is the stricter one. A `rounds_required` that
        is not read is the default, which can be fewer rounds than was meant: `"3"` in
        quotes was read as three. The schema's finding stands in either case.

        Entry by entry, because one mistake should not take what is right with it: a
        convention written correctly beside one that is not, or the rounds a paper asks for
        beside a mistyped key.
        """
        if key not in self.paper:
            return None
        return _accepted(load_schema("paper")["properties"][key], self.paper[key])

    @property
    def keywords(self) -> tuple[str, ...]:
        """The keywords as the build prints them: each entry of the list as text. Of
        settings, their names, which is what colons typed where the dashes belong make of
        a list. One word typed where a list is expected is that one keyword. None where
        `keywords` is a number, a yes or no, or nothing.

        Not through `setting`. A build under `--skip-checks` prints what the author typed,
        and `2019`, which YAML reads as a number, was printed before: it must not leave the
        document without a word. Nor must three keywords written with colons, nor one word
        written without a dash, which was printed letter by letter. What a number raised,
        `TypeError` for `keywords: 5`, is not printed.
        """
        value = self.paper.get("keywords")
        if isinstance(value, str):
            # Text with nothing in it is no keyword: the title page printed "Keywords."
            # with nothing after it.
            return (value,) if value.strip() else ()
        return tuple(str(entry) for entry in value) if isinstance(value, (list, dict)) else ()

    @property
    def english_variant(self) -> str:
        return self.paper.get("english_variant", "en-GB")

    @property
    def target_journal(self) -> str | None:
        return self.paper.get("target_journal")

    @property
    def reporting_guidelines(self) -> tuple[str, ...]:
        return tuple(self.setting("reporting_guideline") or ())

    @property
    def extra_conventions(self) -> tuple[dict, ...]:
        """The conventions a classifier can be built from: those the schema accepts, less
        any whose pattern does not compile or whose name names nothing, which
        `load_project` reports."""
        return tuple(
            entry
            for entry in self.setting("conventions") or ()
            if _not_a_pattern(entry["pattern"]) is None
            and ("id" not in entry or _not_a_name(entry["id"]) is None)
        )

    @property
    def extra_terms(self) -> tuple[str, ...]:
        return tuple(self.setting("terms") or ())

    @property
    def known_abbreviations(self) -> tuple[str, ...]:
        """Short forms this paper uses without defining them. Read past a setting in the
        wrong shape: the schema reports that, and G14 still has a manuscript to read."""
        language = self.paper.get("language")
        listed = language.get("known_abbreviations") if isinstance(language, dict) else None
        return tuple(str(entry) for entry in listed) if isinstance(listed, list) else ()


def _accepted(schema: dict, value: Any) -> Any:
    """`value` as far as `schema` accepts it; see `Project.setting`."""
    kind = schema.get("type")
    if kind == "array":
        if not isinstance(value, list):
            return None
        accepts = Draft202012Validator(schema["items"]).is_valid
        return [entry for entry in value if accepts(entry)]
    if kind == "object":
        if not isinstance(value, dict):
            return None
        known = schema.get("properties", {})
        return {
            name: entry
            for name, entry in value.items()
            if name in known and Draft202012Validator(known[name]).is_valid(entry)
        }
    return value if Draft202012Validator(schema).is_valid(value) else None


def _not_a_pattern(pattern: str) -> str | None:
    """Why a convention's pattern cannot be compiled, or None where it can."""
    try:
        re.compile(pattern, re.MULTILINE)
    except Exception as exc:  # noqa: BLE001 - whatever the compiler raises is about the pattern
        # Not only its own error. `(?a)(?u)x` is a `ValueError`, a repeat too large an
        # `OverflowError`. This runs where the project is loaded, before any gate, so one
        # that got past ended every command in a traceback and the hooks in silence.
        return str(exc)
    return None


#: What YAML and pandoc read as the end of a line, and nothing else: a line split takes
#: the vertical tab, the form feed and three separators for one too. Those are control
#: characters, which YAML makes of `\v` and `\f` between double quotation marks, the
#: start of TeX's `\varepsilon` and `\frac`: folded into a space, the letter after
#: each was lost from the document, and nothing was refused.
LINE_BREAK = re.compile(r"\r\n|[\r\n\x85\u2028\u2029]")


#: The characters `LINE_BREAK` folds, for taking the breaks off the end of a value.
_BREAKS = "".join(chr(code) for code in (0x0A, 0x0D, 0x85, 0x2028, 0x2029))


def one_line(text: str) -> str:
    """`text` with its lines folded into one, as YAML folded them between quotation marks.

    The break a value closes with is taken off, not folded. A block ends with one, and as
    a space it stood after `al.` and `vs.`, where pandoc reads a space as a no-break space:
    a title written as a block was printed with one after it. After a closing backslash it
    became one too. Stripped, not matched by a pattern: one anchored at the end tried every
    break of a run in the middle as its start, and a run of 16,000 took seconds.
    """
    return " ".join(LINE_BREAK.split(text.rstrip(_BREAKS)))


def named(character: str) -> str | None:
    """What a finding calls a character no document can carry, or None where one can.

    It is what YAML calls not printable and XML no character, so pandoc refuses a header
    that holds one, or Word the document: a control character other than a tab; a
    surrogate, half of a pair, which two escapes make where they are written as JSON writes
    a character past U+FFFF; and U+FFFE and U+FFFF, which are no character.
    """
    code = ord(character)
    if character != "\t" and unicodedata.category(character) == "Cc":
        kind = "the control character"
    elif 0xD800 <= code <= 0xDFFF:
        kind = "the surrogate"
    elif code in (0xFFFE, 0xFFFF):
        kind = "the non-character"
    else:
        return None
    return f"{kind} U+{code:04X}"


def advice(character: str) -> str:
    """How to write what was meant, for a character `named` names."""
    code = ord(character)
    if 0xD800 <= code <= 0xDFFF:
        return (
            "a character past U+FFFF is itself in YAML, or one `\\U` escape of eight digits; "
            "two `\\u` escapes, as JSON writes it, are read as two halves"
        )
    if code in (0xFFFE, 0xFFFF):
        return "it is no character; take the escape out"
    return (
        "between double quotation marks YAML reads a backslash as the start of an escape, "
        "`\\a` as U+0007; write the value between single quotation marks, where a backslash "
        "is a backslash"
    )


def unprintable_character(text: str) -> str | None:
    """The first character of `text` that no document can carry (`named`), once its lines
    are folded into one as the build folds them (`one_line`). None where there is none."""
    return next((character for character in one_line(text) if named(character)), None)


#: What YAML reads between double quotation marks as the end of a line or as a tab. Before a
#: letter each begins a word of TeX, `\nu`, `\rho`, `\tau`, `\Nu`, `\Lambda`, `\Pi`, and takes
#: its first letter. The other escapes that begin one are refused already: they make a
#: control character (`\alpha`, `\beta`, `\epsilon`, `\varepsilon`, `\frac`), or YAML does not
#: read them at all (`\delta`, `\xi`, `\upsilon`).
_TAKES_A_LETTER = {
    "n": "the end of a line",
    "r": "the end of a line",
    "N": "the end of a line",
    "L": "the end of a line",
    "P": "the end of a line",
    "t": "a tab",
}
#: A backslash and what follows it, so that a doubled backslash is passed over as one.
_ESCAPE = re.compile(r"\\(.)", re.DOTALL)
_LETTERS = re.compile("[A-Za-z]+")


class LostLetter(NamedTuple):
    """An escape in `paper.yaml` that takes the first letter of a word the build prints."""

    where: str
    line: int
    said: str


def _printed_nodes(root: yaml.Node) -> list[tuple[str, yaml.Node]]:
    """The values of `paper.yaml` that the build prints, as the file writes them, each with
    the place a finding names: `_printed_settings`, before YAML has read them."""
    # Of a key written twice YAML keeps the last, and so does this.
    kept: dict[str, yaml.Node] = {}
    for key, value in root.value if isinstance(root, yaml.MappingNode) else ():
        if isinstance(key, yaml.ScalarNode) and key.value in ("title", "short_title", "keywords"):
            kept[key.value] = value
    out: list[tuple[str, yaml.Node]] = []
    for name, value in kept.items():
        if isinstance(value, yaml.ScalarNode):
            out.append((name, value))
        elif name == "keywords" and isinstance(value, yaml.SequenceNode):
            out += [(f"keywords/{index}", entry) for index, entry in enumerate(value.value)]
        elif name == "keywords" and isinstance(value, yaml.MappingNode):
            out += [("keywords", entry) for entry, _held in value.value]
    return out


def lost_letters(path: Path) -> list[LostLetter]:
    """Each escape in `paper.yaml` that takes the first letter of a word in the title, the
    short title or a keyword, where the value stands between double quotation marks.

    `"The $\\nu$ frequency"` is `The $`, the end of a line, and `u$ frequency`. The build folds
    the line, and the title was printed `The $ u$ frequency`, through `check` and a checked
    build. What YAML made of it is a real line break, which a title may hold and which
    cannot be refused, so this reads the file as it is written: the quotation marks a value
    stands between, and the escape inside them. Nothing where the file cannot be read or is
    not YAML, which is said elsewhere.
    """
    try:
        text = read_text(path)
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        # Where each value opens, by where it closes. A node begins at its anchor or its
        # tag, and a comment between that and the value was read as the value.
        opens = {
            token.end_mark.index: token.start_mark.index
            for token in yaml.scan(text, Loader=yaml.SafeLoader)
            if isinstance(token, yaml.ScalarToken)
        }
    except (Unreadable, yaml.YAMLError):
        return []
    found = []
    for where, node in _printed_nodes(root):
        if not isinstance(node, yaml.ScalarNode) or node.style != '"':
            continue
        start = opens.get(node.end_mark.index, node.start_mark.index)
        raw = text[start : node.end_mark.index]
        for escape in _ESCAPE.finditer(raw):
            reads_as = _TAKES_A_LETTER.get(escape[1])
            rest = _LETTERS.match(raw, escape.end())
            if reads_as is None or rest is None:
                continue
            found.append(
                LostLetter(
                    where,
                    text.count("\n", 0, start + escape.start()) + 1,
                    f"`{escape[0]}{rest[0]}` between double quotation marks is {reads_as} "
                    f"and then `{rest[0]}`, so the document loses the `{escape[1]}`",
                )
            )
    return found


#: What to do about a `LostLetter`.
# The first two keep a backslash, which pandoc then reads as the start of TeX: where a
# break was meant and not TeX, either one loses the word after it, so the third is named.
KEEP_THE_LETTER = (
    "write the value between single quotation marks, where a backslash is a backslash, or "
    "double the backslash; where a line break or a tab was meant, write a space"
)


def _lost_letters(path: Path) -> Report:
    """`lost_letters` as findings, under the schema's code, which fails at every stage."""
    return Report(
        tuple(
            Finding(
                gate="G0",
                code="schema-violation",
                message=f"{lost.where}: {lost.said}",
                path=path,
                line=lost.line,
                hint=KEEP_THE_LETTER,
            )
            for lost in lost_letters(path)
        )
    )


def _printed_settings(paper: dict) -> list[tuple[str, str]]:
    """What the build prints of `paper.yaml`, each with the place a finding names."""
    out = [(key, paper[key]) for key in ("title", "short_title") if isinstance(paper.get(key), str)]
    keywords = paper.get("keywords")
    if isinstance(keywords, str):
        out.append(("keywords", keywords))
    elif isinstance(keywords, list):
        out += [(f"keywords/{index}", str(entry)) for index, entry in enumerate(keywords)]
    elif isinstance(keywords, dict):
        out += [("keywords", str(entry)) for entry in keywords]
    return out


def _unprintable(paper: dict, path: Path) -> Report:
    """A finding for each title or keyword holding a character no document can carry.

    Between double quotation marks YAML reads a backslash as the start of an escape, so
    `"\\alpha-blockers"` is the control character U+0007 and then `lpha-blockers`. The build
    wrote it into the document's properties, and Word would not open the document; `check`
    and a checked build had both passed it. An escape can also make a character that is no
    control character and that no document can carry either (`named`): `check` passed those,
    pandoc refused one in its own words about a file of the build's, and on a surrogate the
    build ended in a traceback, since it cannot be written as UTF-8.
    """
    findings = []
    for where, text in _printed_settings(paper):
        character = unprintable_character(text)
        if character is None:
            continue
        findings.append(
            Finding(
                gate="G0",
                code="schema-violation",
                message=f"{where}: holds {named(character)}, which no document can carry",
                path=path,
                hint=advice(character),
            )
        )
    return Report(tuple(findings))


#: What a finding calls each sign past which no maths is read (`text.tex`).
_SIGN = {
    "`": "a backtick",
    "<": "a `<`",
    "[": "a `[`",
    "@": "an `@`",
    "~": "a `~`",
    "^": "a `^`",
}

#: What to know about TeX in a title or a keyword, for a finding's hint and the build's
#: refusal. Not every backslash before a letter was meant as TeX, and not every dollar sign
#: as maths: the rest is for italics, a superscript, a character, money and a path.
KEEP_THE_TEX = (
    "pandoc keeps TeX only as maths, between dollar signs, and outside them it leaves out "
    "the command with the number or the braces that follow it; for italics write "
    "`*in vivo*`, for a superscript `^18^`, a character can be typed as itself, write "
    "`\\$` for a dollar sign that is only one, and a backslash meant as one is written "
    "twice, between single quotation marks"
)

#: For a dollar sign that was no maths: what every such sentence ends on.
_MONEY = "write `\\$` for a dollar sign that is only one"
#: Why a `$` before a command opened no maths (`Tex.unread`): what a finding says of the
#: command, and what to do about it. The next `$` may be the one meant to close the maths
#: or a dollar amount further on, and the sentence does not say which.
_UNREAD = {
    "digit": (
        "stands after a `$` that opens no maths, since a digit follows the next `$`",
        f"put the digit inside the dollar signs or a space before it, or {_MONEY}",
    ),
    "space": (
        "stands after a `$` that opens no maths, since a space stands before the next `$`",
        f"close the maths before that space, or {_MONEY}",
    ),
    "open": (
        "stands after a `$` that opens no maths, since no `$` follows to close it",
        f"close the maths with a `$`, or {_MONEY}",
    ),
    "paired": (
        "stands after a `$` that closes maths an earlier `$` opens, so it is outside that "
        "maths",
        f"{_MONEY}, or open maths for the command",
    ),
}
#: The remedy for a keyword, whatever stands around the command.
_AS_TEXT = "write it as text and not as maths"
_KEYWORD = (
    f"{_AS_TEXT}, the character itself for a letter or a sign, since a keyword is printed "
    "in the document's properties only, where maths is written as its TeX"
)


def _past_a_sign(found: Tex, keyword: bool) -> str:
    """The sentence for a command past a sign after which no maths is read: pandoc may
    well print it, so it says "may", and its remedies are the ones that hold there. With
    the sign escaped the maths is read, which is no use to a keyword; and a command with
    braces stands for no character."""
    remedies = [] if keyword else ["where the sign is only itself put a backslash before it"]
    if not found.braces:
        remedies.append("type the character the command stands for")
    elif keyword:
        remedies.append(_AS_TEXT)
    return (
        f"`{found.command}` stands after {_SIGN[found.after]}, past which this check reads "
        f"no maths, so the document may be printed without it; {', or '.join(remedies)}"
    )


def outside_maths(text: str, *, keyword: bool = False) -> str | None:
    """What a finding says of TeX in `text` that the document would be printed without, or
    None where there is none, once its lines are folded into one as the build folds them.
    `keyword` is for a keyword, whose remedy is another.

    Pandoc reads a title, a short title and a keyword as Markdown, and the Word writer
    keeps TeX only as maths: `IFN-\\gamma release assays` passed `check` and a checked build
    and was printed `IFN-release assays`. A command takes what follows it as TeX would, so
    `12 \\pm 3 months` is printed without its `3`.

    The sentence has to be true of the value it is printed for, and its remedy has to work.
    Two rounds of review found ways neither held, each a kind of sentence now:

    - Past a sign that can hold a dollar sign which opens no maths, the rule reads none
      (`text.tex`), and reports TeX that pandoc may well keep: "outside dollar signs" would
      be false of `[18F]FDG and TGF-$\\beta$`. It names the sign and says "may".
    - A command can stand after a `$` that opens no maths: `TGF-$\\beta$1` is printed
      `TGF-$$1`, for the digit after the next `$`. It says why, since "write `$\\beta$`" is
      what the author wrote. That holds for every command up to that `$`, the second in
      `$p \\leq$0.05` too.
    - Where braces follow the command, dollar signs around the command alone are no
      remedy: `$\\textit${in vivo}` is printed as typed. It gives none, and the hint has
      the ones that work. Where none follow, a path for one, it says "if it is maths".
    - An `&` that a `;` follows, where a subscript or a superscript can hold it, is
      reported as what may be a character reference: the rule does not read it to see
      whether it is one, and `R^2^&RMSE; model fit` was told that `&RMSE;` is a reference
      in a superscript, where it is neither. A space before the `&` mends that one, and
      would undo the superscript of `x^&alpha;^`, so it is named for an `&` after the script.
    """
    found = tex_outside_maths(one_line(text))
    if found is None:
        return None
    command = f"`{found.command}`"
    if found.reference:
        return (
            f"{command} may be a character reference where a subscript or a superscript can "
            "hold it: pandoc resolves one there and reads the result again, so it can make "
            "TeX that the document is printed without; type the character itself, or, where "
            "it stands after the script, put a space before the `&`"
        )
    if found.after:
        return _past_a_sign(found, keyword)
    if found.unread:
        how, remedy = _UNREAD[found.unread]
        said = f"{command} {how}, and the document is printed without it"
    elif found.braces:
        said = (
            f"{command} stands outside dollar signs, and the document is printed without it "
            "and what its braces hold"
        )
        remedy = ""
    else:
        said = f"{command} stands outside dollar signs, and the document is printed without it"
        remedy = f"if it is maths, write `${found.command}$`"
    remedy = _KEYWORD if keyword else remedy
    return f"{said}; {remedy}" if remedy else said


def _tex_outside_maths(paper: dict, path: Path) -> Report:
    """A finding for each title or keyword holding TeX the document would be printed
    without (`outside_maths`), under the schema's code, which fails at every stage."""
    findings = []
    for where, text in _printed_settings(paper):
        said = outside_maths(text, keyword=where.startswith("keywords"))
        if said is None:
            continue
        findings.append(
            Finding(
                gate="G0",
                code="schema-violation",
                message=f"{where}: {said}",
                path=path,
                hint=KEEP_THE_TEX,
            )
        )
    return Report(tuple(findings))


def _not_a_name(name: str) -> str | None:
    """Why a convention's `id` names nothing a report can cite, or None where it does."""
    if not name.strip():
        return "it holds nothing but spaces"
    if name.splitlines()[0] != name:
        return "it runs over more than one line"
    return None


def _unusable_conventions(paper: dict, path: Path) -> Report:
    """A finding for each convention whose pattern is not a regular expression, or whose
    name names nothing.

    The schema can only say that a pattern is text. One that does not compile raised where
    the classifier was built, so it was "G2 could not run: error: unterminated character set
    at position 0" with no entry named, and a traceback from `explain` and `bind`. And a
    name of spaces was cited as `project:   `, one over two lines split the row `explain`
    prints and the report's count. Said here, under the schema's code, which fails at every
    stage, and the entry is not read.
    """
    conventions = paper.get("conventions")
    findings = []
    for index, entry in enumerate(conventions if isinstance(conventions, list) else ()):
        if not isinstance(entry, dict):  # the schema's to report
            continue
        pattern, name = entry.get("pattern"), entry.get("id")
        # Not text: the schema's to report.
        why = _not_a_pattern(pattern) if isinstance(pattern, str) else None
        if why is not None:
            findings.append(
                Finding(
                    gate="G0",
                    code="schema-violation",
                    message=f"conventions/{index}/pattern: {pattern!r} is not a regular "
                    f"expression: {why}",
                    path=path,
                    hint="a pattern is a Python regular expression; a bracket meant as a "
                    "character is written with a backslash before it",
                )
            )
        why = _not_a_name(name) if isinstance(name, str) and name else None
        if why is not None:
            findings.append(
                Finding(
                    gate="G0",
                    code="schema-violation",
                    message=f"conventions/{index}/id: {name!r} is not a name: {why}",
                    path=path,
                    hint="the report and `explain` cite the convention by its name, as "
                    "`project:<id>`; give it a word or two on one line, or leave it out",
                )
            )
    return Report(tuple(findings))


def find_root(start: Path) -> Path:
    """Walk upwards for the directory holding paper.yaml."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / PAPER_FILE).exists():
            return candidate
    raise ContractError(
        f"no {PAPER_FILE} found in {start} or any parent directory; "
        f"run `manuscript-guard init` to create a project"
    )


def _held(value: object) -> str:
    """What YAML made of a value, in the words an author would use for it."""
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "a yes or no"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "settings"
    return "something else"


def _settings(paper: object, path: Path) -> dict:
    """The parsed `paper.yaml`, once it is known to be what `Project` reads it as.

    The schema reports a wrong shape as a finding, but `Project` is asked where the results
    are before there is a report to print, and a list or a line of text has no `paths` to
    ask: `check` ended in `AttributeError`, the finding was never seen, and the hooks took
    the traceback for a fault of the tool. So the two things every command needs of this
    file are held here, and said in a sentence: that it is settings, and that each folder it
    names is named in text. Everything else in it is still the schema's to report.
    """
    if paper is None:  # an empty file: nothing set yet, and the schema says what to add
        return {}
    if not isinstance(paper, dict):
        cause = (
            " (a line such as `title:My paper`, with no space after the colon, is read as text)"
            if isinstance(paper, str)
            else ""
        )
        raise ContractError(
            f"{path}: holds {_held(paper)} where the settings of the paper are expected, "
            f"one `key: value` to a line{cause}"
        )
    if "paths" not in paper:
        return paper
    paths = paper["paths"]
    if not isinstance(paths, dict):
        raise ContractError(
            f"{path}: `paths` holds {_held(paths)} where a folder is expected for each name "
            f"it changes, as in `results: output`, indented on a line of its own"
        )
    for which in DEFAULT_PATHS:
        if which in paths and not isinstance(paths[which], str):
            raise ContractError(
                f"{path}: `paths.{which}` holds {_held(paths[which])} where the name of a "
                f"folder is expected, as in `{which}: {DEFAULT_PATHS[which]}`"
            )
    return paper


def load_project(start: Path | None = None) -> tuple[Project, Report]:
    root = find_root(start or Path.cwd())
    reports: list[Report] = []

    paper_path = root / PAPER_FILE
    paper = _settings(read_structured(paper_path), paper_path)
    reports.append(validate(paper, "paper", paper_path))
    reports.append(_unusable_conventions(paper, paper_path))
    reports.append(_unprintable(paper, paper_path))
    reports.append(_lost_letters(paper_path))
    reports.append(_tex_outside_maths(paper, paper_path))

    authors_path = root / AUTHORS_FILE
    authors = read_structured(authors_path)
    if authors is not None:
        # A distinct code, because an unfinished author block is a to-do rather than a
        # broken contract, and the stage policy defers it until the manuscript exists.
        reports.append(validate(authors, "authors", authors_path, code="authors-incomplete"))

    return Project(root, paper, authors), merge_all(reports)
