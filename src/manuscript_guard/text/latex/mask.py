"""A LaTeX file read as `masking.mask` reads a Markdown one: what is not prose blanked.

The contract is `mask`'s: the same length, every line break kept, and what is not prose
replaced by NUL, so that a finding names the `.tex` line. Two additions keep the length. A
sign TeX prints as a space is a space: `~`, `\\,`, `\\quad`, `\\\\`, and `&` in a table. An
escaped character is that character at the backslash's place, with a NUL after it, so that
`95\\%` reads as `95%`.

One pass, linear in the file, under TeX's default category codes. The preamble is blanked but
for `\\title`, `\\thanks`, and a definition's body and default argument, which print where it
is used; maths keeps what it holds but its commands, braces and delimiters,
as Markdown's `mask` keeps `$...$`; a comment, a listing, a label, a key and a binding are
blanked; a command not in `commands.py` has its name blanked and its arguments read. What the
reader cannot read exactly is refused (`Refusal`), and past the first refusal the rest of the
file is blanked: no gate reads source it did not understand as prose, and what reports on the
file says it was not read past there (Basile, 2026-11-11, "Read more, and be honest": read as
typed, its comments and commands were G6's and G14's findings). Two constructs in the body
have a bounded end, and are skipped to it rather than refused: a `\\makeatletter` to its
`\\makeatother`, and a conditional to its matching `\\fi`, neither branch read. Nothing in the
block is read, and the reading goes on past it (`Reading.skipped`); one with no such end in
the file is refused as before (Basile, 2026-11-13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from manuscript_guard.text.latex import pictures
from manuscript_guard.text.latex.commands import (
    ABSTRACT_COMMANDS,
    AMSMATH,
    CATEGORY,
    CITATIONS,
    CITEPROC,
    COMMANDS,
    ENVIRONMENTS,
    FIGURES,
    FLOATS,
    FRONT_MATTER,
    FRONT_MATTER_COMMANDS,
    IMPORTS,
    LISTINGS,
    MATHS,
    PACKAGE_COMMANDS,
    PARAMETERS,
    PICTURES,
    PLACED,
    POINTERS,
    PROVIDERS,
    RANGES,
    RAW,
    READ_IN_FRONT_MATTER,
    REFERENCE_MACHINERY,
    REFUSED,
    REFUSED_ENVIRONMENTS,
    SIUNITX,
    SPACES,
    SYMBOLS,
    TABLE_COMMANDS,
    TABLES,
    TYPED_TABLES,
)
from manuscript_guard.text.placeholders import NAMESPACES

NUL = "\x00"
#: The environment a reference list is typed in.
REFERENCES = "thebibliography"
#: The hooks whose body LaTeX runs where it stands, unlike a definition's.
HOOKS = frozenset({"AtBeginDocument", "AtEndDocument", "AfterEndPreamble", "AddToHook"})
PROSE, BLANK, MATHS_READ, PREAMBLE = "prose", "blank", "maths", "preamble"
#: Commands whose prose argument LaTeX prints though it stands in the preamble: the title, its
#: note, and a definition's default argument, printed at each use that omits it (round 1 of
#: #380: `\\newcommand{\\ci}[1][95]{...}` hid the 95). The abstract, as a command or an
#: environment, which a class such as PNAS's prints from the preamble (round 2 of #385: it
#: was refused, and so was `\\let\\oldabstract\\abstract`, which only names it), and a template's
#: `\\Abstract` (decision 17).
PRINTED_IN_PREAMBLE = frozenset(
    {"title", "thanks", "newcommand", "renewcommand", "providecommand", "newenvironment",
     "renewenvironment", "DeclareRobustCommand", "NewDocumentCommand", "RenewDocumentCommand",
     "ProvideDocumentCommand", "DeclareDocumentCommand"}
) | ABSTRACT_COMMANDS  # fmt: skip
#: Names that open no conditional though they start with `if`: a symbol and a command whose
#: branches are its arguments, both read.
NOT_CONDITIONALS = frozenset({"iff", "ifthenelse"})
_LETTERS = re.compile(r"[A-Za-z]+")
_LETTERS_AT = re.compile(r"[A-Za-z@]+")
_TEXT = re.compile(r"[^\\%{}\[\]$&~#`'\n\"]+")
#: A blank line, which ends a paragraph and any quotation left open in it.
_PARAGRAPH_END = re.compile(r"\n[ \t\r]*\n")
#: TeX's `\\par`, which ends a paragraph as a blank line does: not the letters after `\\\\`.
_PAR = re.compile(r"(?<!\\)(?:\\\\)*(?P<par>\\par)(?![A-Za-z@])")
#: A straight `"` before a letter, which closes no quotation: babel's German accent, `"a`.
_ACCENTED = re.compile(r'"[^\W\d_]')
_ENVIRONMENT_NAME = re.compile(r"[ \t]*\n?[ \t]*\{([^{}\n]*)\}")
_BRACED_NAME = re.compile(r"\{\s*\\([A-Za-z@]+|[^A-Za-z@\s])\s*\}")
#: A parameter token in a definition's body: `#1`, or `##1` in a definition inside it.
_PARAMETER = re.compile(r"#+\d")
#: How far a delimited definition's parameter text is looked through for its body's brace.
_DELIMITED_REACH = 300
#: What stands between `\\let`'s two commands: spaces and an equals sign, both optional.
_LET_GAP = re.compile(r"[ \t]*=?[ \t]*")
#: Commands the reader reads apart from the rest of their form, which no `\\let` makes one of
#: another: an input, an import, code the printed view passes over, and a binding (round 2).
_READ_APART = frozenset({"input", "include", "import", "subimport", "texttt", "mg"}) | PLACED
#: What TeX passes over after a control word: spaces, and one line's end with the spaces after.
_SKIPPED = re.compile(r"[ \t]*(?:\r?\n[ \t]*)?")
#: An input encoding set by a package's option or by `\\inputencoding`, a few hundred
#: characters at most, so that an option never closed is not read to the file's end.
_INPUTENC = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*\[([^\]]{0,300})\]\s*\{inputenc\}"
    r"|\\inputencoding\s*\{([^}]{0,40})\}"
)
#: What follows a preamble's `\\expandafter` that only redefines a command, as Scientific
#: WorkPlace writes `\\expandafter\\def\\expandafter\\normalsize\\expandafter{...}`: TeX's
#: `\\def` and its kin, then a command's name, past more `\\expandafter`s; not one built by
#: `\\csname`, which stays refused.
_EXPANDED_DEFINITION = re.compile(
    r"\s*\\[gex]?def(?![A-Za-z@])(?:\s*\\expandafter(?![A-Za-z@]))*\s*\\(?!csname(?![A-Za-z@]))"
)
#: The `\\expandafter`s such a definition holds before its name and before its body.
_EXPANDAFTERS = re.compile(r"(?:\s*\\expandafter(?![A-Za-z@]))*\s*")
_CONDITIONALS = re.compile(r"\\(?:if[A-Za-z]*|fi|else)(?![A-Za-z])")
_SPACES_ONLY = re.compile(r"\s*")
_DOCUMENT = re.compile(r"\\begin\s*\{document\}")


@dataclass(frozen=True)
class Refusal:
    """Why the reader stopped reading a file as LaTeX, and where; or, with an `end`, a block
    it skipped to its matching end and read on past (`Reading.skipped`)."""

    code: str
    offset: int
    message: str
    #: Where a skipped block ends, past its `\\makeatother` or `\\fi`; -1 where the reader
    #: stopped, and read nothing more of the file.
    end: int = -1


@dataclass(frozen=True)
class Input:
    """An `\\input` or `\\include` where the reader met it, with the state it stands in: the
    file it names starts in that state."""

    offset: int
    end: int
    path: str
    body: bool
    environments: tuple[str, ...]
    #: The command: `input` for `\\input` and `\\include`, the import package's `import` or
    #: `subimport`, whose folder is written before the file, or `subfile` or
    #: `includestandalone`, which place a part's document body (`commands.PLACED`).
    via: str = "input"
    folder: str = ""


@dataclass(frozen=True)
class Heading:
    """A heading where its command stands, its level as Markdown counts `#`, its title, and
    where its title's argument ends, or -1 where nothing of it is the title (an abstract)."""

    start: int
    level: int
    title: str
    end: int = -1


@dataclass(frozen=True)
class BindingUse:
    """A `\\mg` where it stands, to the brace that closes it, and what its braces hold: None
    where it is followed by none. Whether that is a binding is `views.py`'s to say."""

    start: int
    end: int
    inner: str | None


@dataclass(frozen=True)
class Listing:
    """What a listing holds, between its `\\begin` and its `\\end`, and the language an
    `lstlisting` names, or "" where it names none."""

    start: int
    end: int
    language: str


@dataclass(frozen=True)
class Cited:
    """One key a citation command names: the key, where it stands, whether the command prints
    the authors' names in the sentence, and the command to its keys' closing brace."""

    key: str
    offset: int
    narrative: bool
    start: int
    end: int


@dataclass(frozen=True)
class Reading:
    masked: str
    refusals: tuple[Refusal, ...]
    inputs: tuple[Input, ...] = ()
    headings: tuple[Heading, ...] = ()
    #: Where each abstract runs, `\\begin{abstract}` to its `\\end`, or `\\abstract{...}`, or a
    #: template's `\\Abstract{...}` (`ABSTRACT_COMMANDS`).
    abstracts: tuple[tuple[int, int], ...] = ()
    #: Each package loaded, where its `\\usepackage` stands.
    packages: tuple[tuple[int, str], ...] = ()
    #: Each `\\mg` read, outside a comment, a listing and siunitx's commands.
    bindings: tuple[BindingUse, ...] = ()
    #: What looks meant for a binding and is none: a near spelling of `\\mg`, `\\Mg{results.x}`,
    #: and a Markdown binding left in a `.tex`, `{{results.x}}`.
    suspects: tuple[tuple[int, int], ...] = ()
    #: Where each table the author typed runs, `\\begin{tabular}` to its `\\end`.
    tables: tuple[tuple[int, int], ...] = ()
    #: Each listing, read by G2's code check as a fenced block is.
    listings: tuple[Listing, ...] = ()
    #: Each key a citation command names, outside a definition's body.
    cited: tuple[Cited, ...] = ()
    #: Where each formula runs, and whether it is displayed rather than inline.
    maths: tuple[tuple[int, int, bool], ...] = ()
    #: Where each float runs, `\\begin{figure}` or `\\begin{table}` to its `\\end`.
    floats: tuple[tuple[int, int], ...] = ()
    #: Where the body starts: past `\\begin{document}`, 0 in a file that opens in it, or -1
    #: in one that never reaches it.
    body_start: int = 0
    #: Each code span, `\\verb` or `\\texttt`, from its opening delimiter to past its closing
    #: one: read as prose, and as Markdown's code span is where words are counted.
    code: tuple[tuple[int, int], ...] = ()
    #: What a journal's profile states of a LaTeX source, as the file states it: ("class",
    #: name), ("class_option", option), ("bst", style), and ("biblatex", its options).
    declared: tuple[tuple[str, str], ...] = ()
    #: Where each float that holds a figure runs (`commands.FIGURES`).
    figures: tuple[tuple[int, int], ...] = ()
    #: Where each reference list typed in `thebibliography` runs.
    references: tuple[tuple[int, int], ...] = ()
    #: Where `\\end{document}` stands, or -1 in a file that does not end the document.
    body_end: int = -1
    #: Where each definition's body runs, which prints only where the definition is used; not
    #: a hook's, which LaTeX runs where it stands.
    bodies: tuple[tuple[int, int], ...] = ()
    #: Where each cross-reference stands, `\\ref{...}` to its brace, outside a definition's
    #: body: what LaTeX prints there is a number only the compiled document knows (step 8).
    pointers: tuple[tuple[int, int], ...] = ()
    #: Where each comment runs, its `%` to its line's end, as the reader meets it (step 10).
    comments: tuple[tuple[int, int], ...] = ()
    #: What TeX reads past and never prints: an `\\iffalse` block's content, to its `\\fi` or
    #: `\\else`, and a `comment` environment's lines (step 10).
    unprinted: tuple[tuple[int, int], ...] = ()
    #: Each `\\includegraphics`, from the command to past its path's closing brace, and where
    #: its path's braces open (step 10).
    graphics: tuple[tuple[int, int, int], ...] = ()
    #: Each command the file defines with delimited parameters, `\\def\\x#1.{...}`, and each
    #: the reader knows that its preamble defines again, `\\def\\eqref#1{...}`, whose uses
    #: are refused where they would print, in this file and in the others of its tree.
    delimited: tuple[str, ...] = ()
    #: Each command of a class's front matter the file defines, which is then the author's.
    own: tuple[str, ...] = ()
    #: Each command the file defines with a parameter text and no parameter,
    #: `\\def\\eg/{e.g.}`, with that text: a use prints the body, and the text after it is
    #: passed over.
    literal: tuple[tuple[str, str], ...] = ()
    #: Where the file sets an input encoding other than UTF-8, accepted since it is ASCII: the
    #: tree refuses it where another of its files is not (`structure.py`).
    encodings: tuple[int, ...] = ()
    #: Each block in the body the reader skipped and read on past, a `\\makeatletter` to its
    #: `\\makeatother` and a conditional to its `\\fi`, nothing in it read (Basile,
    #: 2026-11-13): a refusal with its `end`, which the tree adds to its refusals.
    skipped: tuple[Refusal, ...] = ()


#: The level of each sectioning command, as Markdown's `#` counts it; a part stands over a
#: chapter (round 1 of #385: both were 0, and a chapter closed its part).
LEVELS = {"part": -1, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3,
          "paragraph": 4, "subparagraph": 5}  # fmt: skip
#: The commands whose prose argument opens a heading: the sectioning commands, and the abstract
#: given as a command, titled Abstract (`_close`).
_HEADING_COMMANDS = frozenset(LEVELS) | ABSTRACT_COMMANDS
#: A path in braces after `\input`, which TeX finds past spaces and one line break.
_BRACED_PATH = re.compile(r"[ \t]*(?:\r?\n[ \t]*)?\{([^{}\n]*)\}")
#: TeX's `\\input name` without braces: the name runs to a space, a brace, a command or a
#: comment, as `structure._LOADS` reads it in a class.
_BARE_PATH = re.compile(r"[ \t]+([^\s{}\\%]+)")
#: The options before `\\includestandalone`'s path, a few hundred characters at most.
_PLACE_OPTIONS = re.compile(r"[ \t]*(?:\r?\n[ \t]*)?\[[^\]]{0,300}\]")
#: Commands the reader knows that an author may define again, which it then reads as before:
#: `\abstract` was an unknown command, its arguments read, until it was given a heading, and
#: so was `\Abstract`, which the template that takes it defines in its class and prints as it
#: is given (decision 17: SelfArx.cls's `\newcommand{\Abstract}[1]{\def\@Abstract{#1}}`); a
#: class's front matter, `\keywords` among it, is passed over however it is defined; and
#: pandoc's citeproc commands, which its template defines; and a table's rules and colours.
_REDEFINABLE = ABSTRACT_COMMANDS | FRONT_MATTER_COMMANDS | CITEPROC | TABLE_COMMANDS
_PACKAGES = re.compile(r"\s*(?:\[([^\]]{0,300})\])?\s*\{([^{}]{0,300})\}")
_NAMESPACE = "(?:" + "|".join(NAMESPACES) + r")\."
#: What TeX passes over before an argument: spaces, and one line break (round 1 of #400).
_GAP = r"[ \t]*(?:\r?\n[ \t]*)?"
#: What follows a `\\mg`: its options, and its braces with what they hold, on one line.
_BINDING = re.compile(_GAP + r"(?:\[[^\]\n]*\])?" + _GAP + r"\{(?P<inner>[^{}\n]*)\}")
#: What makes a command, or a Markdown binding, look meant for one.
_LOOKS_BOUND = re.compile(_GAP + r"(?:\[[^\]\n]*\])?" + _GAP + r"\{[ \t]*" + _NAMESPACE)
_MARKDOWN_BINDING = re.compile(r"\{\{[ \t]*" + _NAMESPACE)
_KEYED = re.compile(r"[ \t]*" + _NAMESPACE)
#: The word after a `\\mg` that no braces follow, shown with it: `\\mg results.x`.
_BARE = re.compile(r"[ \t]*[^\s{}\\%]*")
#: A `\\mg` that names a key, which a listing or a `\\verb` prints as typed. One that names
#: none documents the command and is left alone (round 1 of #400).
_MG_USE = re.compile(r"\\mg(?![A-Za-z@])" + _LOOKS_BOUND.pattern)
_LISTING_OPTIONS = re.compile(r"[ \t]*\[([^\]\n]*)\]")
_LANGUAGE = re.compile(r"language\s*=\s*\{?\s*(?:\[[^\]]*\])?\s*([A-Za-z][A-Za-z0-9+#]*)")
_BOUND_IN_SIUNITX = ("a binding in a siunitx command is not read: siunitx parses its number, "
                     "and a value prints as text; write \\mg{...} outside it")  # fmt: skip
#: TikZ's old `\\tikzstyle{name} = [options]`: its name, and the sign before its options,
#: `=` or `+=`, or none.
_STYLE_NAME = re.compile(_GAP + r"\{[^{}\n]*\}[ \t]*\+?=?")


#: English words that hold `cite` and cite nothing, which an author may open a command's name
#: with: `\\excite`, `\\solicited`. Only as the name's start: inside a name the word is no
#: word of it, and `\\maincite` holds "incite" (round 2 of #442).
_CITE_WORDS = ("anthracite", "plebiscite", "excite", "incite", "recite", "solicite", "elicite",
               "lucite")  # fmt: skip
#: Class commands whose names hold `cite` and cite nothing, named whole: IEEE Computer
#: Society's thanks to the authors holds it in `compso` and `item`.
_CITE_NAMES = frozenset({"ieeecompsocitemizethanks"})
#: A reference list's helpers that hold `cite`, which BibTeX's styles write in its entries'
#: labels: REVTeX's `\\citenamefont`, harvard's and apacite's `\\citeauthoryear`.
_LIST_HELPERS = frozenset({"citenamefont", "citeauthoryear"})


def _cites(name: str) -> bool:
    """Whether a command's name is a citation's: it holds `cite`, as `\\citeA`, `\\mycite` and
    `\\mycitep` do, but in a word that cites nothing (`_CITE_WORDS`): IEEE's
    `\\IEEEcompsocitemizethanks` and an author's `\\excite` were refused (2026-10-23), and a
    rule for names that begin or end with `cite` let `\\mycitep` pass unread (round 1 of
    #442), as one that took the words out anywhere let `\\maincite` pass (round 2)."""
    low = name.lower()
    if low in _CITE_NAMES:
        return False
    word = next((word for word in _CITE_WORDS if low.startswith(word)), "")
    return "cite" in low[len(word) :]


def _near_binding(name: str) -> bool:
    """Whether a command's name is `mg` mistyped: another case, or one letter added, taken
    out, changed or swapped with its neighbour."""
    low = name.lower()
    if low == "mg":
        return name != "mg"
    if len(low) == 2:
        return low == "gm" or sum(a != b for a, b in zip(low, "mg", strict=True)) == 1
    if len(low) not in (1, 3):
        return False
    longer, shorter = (low, "mg") if len(low) == 3 else ("mg", low)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


@dataclass
class _Frame:
    kind: str  # "group", "arg", "opt", "env" or "maths"
    role: str
    start: int
    closer: str = ""
    rest: tuple[str, ...] = ()
    command: str = ""
    definition: bool = False
    table: bool = False
    #: A heading's level and where its command stands, for the argument that is its title.
    heading: int | None = None
    origin: int = -1
    #: An environment the file was input inside, which it may close and need not.
    inherited: bool = False
    #: An argument of a siunitx command.
    siunitx: bool = False
    #: What a letter was where a reference list opened, which its `\\end` puts back.
    letters: re.Pattern[str] | None = None
    #: Whether a reference list has reached its first `\\bibitem`, past its header.
    items: bool = False


def mask(text: str, *, body: bool | None = None) -> str:
    """`text` with what is not prose replaced by NUL. `body` says whether the file opens in
    the document's body, as a file input from it does; None reads it from the file."""
    return read(text, body=body).masked


def read(
    text: str,
    *,
    body: bool | None = None,
    environments: tuple[str, ...] = (),
    loose: bool = False,
    package: bool = False,
    delimited: frozenset[str] = frozenset(),
    own: frozenset[str] = frozenset(),
    literal: tuple[tuple[str, str], ...] = (),
    loaded: frozenset[str] = frozenset(),
) -> Reading:
    """The masked text, the first refusal, and what the file inputs, heads and loads. With
    `body` None, a file with a `\\begin{document}` outside a comment opens in the preamble,
    and one without opens in the body, so that none of it is hidden as preamble (round 1 of
    #380). One read to its end without reaching its `\\begin{document}`, which stood in a
    listing say, is read again as body; one refused in its preamble keeps that refusal (round
    2). A file input from another opens inside the `environments` its `\\input` stood in. A
    `loose` file, which nothing inputs, is body that accepts what a preamble accepts. A
    `package` of the author's is read as LaTeX reads a package, with `@` a letter. The tree
    tells each file of what the others define, `delimited`, `own` and `literal`, and of the
    packages they load, `loaded`. A file that opens in its preamble, as a part the paper
    places by `\\subfile` does, opens the `environments` at its `\\begin{document}`."""
    opens_in_body = not _has_document(text) if body is None else body
    told = (delimited, own, literal, loaded)
    opening = environments if opens_in_body else ()
    reader = _Reader(text, opens_in_body, opening, loose, package, *told,
                     later=() if opens_in_body else environments)  # fmt: skip
    reading = reader.run()
    if body is None and not reader.body and reader.refused is None:
        return _Reader(text, True, environments, loose, package, *told).run()
    return reading


def _has_document(text: str) -> bool:
    """Whether a `\\begin{document}` stands outside a comment, the text read forward once
    (round 3 of #380)."""
    scanned, comment = 0, False
    for match in _DOCUMENT.finditer(text):
        newline = text.rfind("\n", scanned, match.start())
        if newline >= 0:
            scanned, comment = newline + 1, False
        comment = comment or _opens_comment(text, scanned, match.start())
        if not comment:
            return True
        scanned = match.start()
    return False


def _verb_delimiter(text: str, at: int) -> str:
    """The character that opens and closes a `\\verb`: any but a letter, a space or a star."""
    character = text[at : at + 1]
    return "" if not character or character.isalpha() or character.isspace() else character


def _opens_comment(text: str, start: int, end: int) -> bool:
    """Whether an unescaped `%` stands between `start` and `end`, on one line."""
    at = text.find("%", start, end)
    while at >= 0:
        before = at - 1
        while before >= 0 and text[before] == "\\":
            before -= 1
        if (at - 1 - before) % 2 == 0:
            return True
        at = text.find("%", at + 1, end)
    return False


#: How far a multi-citation's global note is looked for, `\\cites(see)(p.~5){a}{b}`.
_NOTE_REACH = 300


def _key_list(keys: str) -> str:
    """A citation's keys with each comment in them blanked, at the same offsets: LaTeX drops
    `%` to the end of its line, so `\\citep{a,%` and `b}` on the next line cite a and b."""
    return re.sub(r"(?<!\\)%[^\n]*", lambda found: " " * len(found.group(0)), keys)


#: A brace group, with groups one deep inside it: `{\\normalfont\\large\\bfseries}`.
_GROUP = r"\{(?:[^{}]|\{[^{}]*\})*\}"
#: A sectioning command restyled the way LaTeX's classes define it, its whole body one
#: `\\@startsection` of its own name and five more groups (Basile, 2026-11-12: arxiv.sty's
#: and style.sty's `\\renewcommand\\section{\\@startsection{section}{1}{\\z@}...}`).
_RESTYLED_HEADING = re.compile(r"\s*\\@startsection\s*\{(?P<name>[a-z]+)\}(?:\s*"
                               + _GROUP + r"){5}\s*")  # fmt: skip
#: A cross-reference defined again as another of its own argument, with plain words, a tie
#: or a space beside it and parentheses round it or not (Basile, 2026-11-12: ICLR's
#: `\\def\\eqref#1{equation~\\ref{#1}}`).
_REFERENCE_AGAIN = re.compile(r"[A-Za-z.,:; ~]*(?P<open>\()?\s*\\(?P<inner>ref|eqref)\s*"
                              r"\{#1\}\s*(?(open)\))[A-Za-z.,:; ~]*")  # fmt: skip
#: A comment in a definition, to its line's end and the line break with it.
_DEFINITION_COMMENT = re.compile(r"(?<!\\)%[^\n]*\n?")


def _read_as_before(name: str, head: str, body: str) -> bool:
    """Whether a known command the preamble defines again is read as the reader reads it,
    its uses not refused: one of the two exact forms of Basile's answer of 2026-11-12. A
    sectioning command whose whole body is LaTeX's `\\@startsection` of its own name, with no
    parameter, prints the heading it did, restyled. A cross-reference of one parameter whose
    body is another cross-reference of it, among plain words, prints the number it did; the
    words the body prints beside it, "equation", are read once, at the definition, as any
    macro's are (DESIGN.md, Known gaps). `head` is what stands from the name to the body's
    brace, and `body` what the braces hold. Anything else, a font switch round the
    `\\@startsection` or a second command, is not, and is refused where it is used."""
    head = re.sub(r"\s+", "", _DEFINITION_COMMENT.sub("", head))
    body = _DEFINITION_COMMENT.sub("", body)
    named = re.escape(name)
    if name in LEVELS:
        restyled = _RESTYLED_HEADING.fullmatch(body)
        return (re.fullmatch(r"\{?\\" + named + r"\}?", head) is not None
                and restyled is not None and restyled["name"] == name)  # fmt: skip
    if name in POINTERS and name not in RANGES:
        again = _REFERENCE_AGAIN.fullmatch(body)
        return (re.fullmatch(r"\{?\\" + named + r"\}?(?:\[1\]|#1)", head) is not None
                and again is not None and again["inner"] != name)  # fmt: skip
    return False


def _redefined_said(name: str) -> str:
    """Why a use of a command whose uses are refused where they print is not read: the
    preamble defines again one the reader knows (2026-11-11), or it takes delimited
    parameters (2026-10-23)."""
    if name in COMMANDS:
        return ("the preamble defines it again, and what it prints here is the author's "
                "definition, not what the reader reads it as")
    return ("it is defined with delimited parameters, and what it prints is not read; define "
            "it with \\newcommand")


def _unread(text: str) -> str:
    """`text` as the reader gives what it did not read past a refusal: NUL, its line breaks
    kept, so that a finding past it names no line and no gate reads source as prose (round
    of 2026-11-11: read as typed, a template's comments were G6's findings)."""
    return re.sub(r"[^\r\n]", NUL, text)


def _before(reading: Reading, at: int) -> Reading:
    """`reading` with only what its run found before `at`, a refusal's offset: one of a
    construct left open is found at the run's end and placed where it opened, and what was
    found past it, a heading, a citation, an input, was kept and read by G7 and the sections
    though no text past it is (round 1 of #637)."""
    def spans(found: tuple) -> tuple:
        return tuple(one for one in found if one[0] < at)

    return replace(
        reading,
        inputs=tuple(put for put in reading.inputs if put.offset < at),
        headings=tuple(heading for heading in reading.headings if heading.start < at),
        abstracts=spans(reading.abstracts), packages=spans(reading.packages),
        bindings=tuple(found for found in reading.bindings if found.start < at),
        suspects=spans(reading.suspects), tables=spans(reading.tables),
        listings=tuple(listing for listing in reading.listings if listing.start < at),
        cited=tuple(cited for cited in reading.cited if cited.offset < at),
        maths=spans(reading.maths), floats=spans(reading.floats), code=spans(reading.code),
        figures=spans(reading.figures), references=spans(reading.references),
        bodies=spans(reading.bodies), pointers=spans(reading.pointers),
        comments=spans(reading.comments), unprinted=spans(reading.unprinted),
        graphics=spans(reading.graphics),
        encodings=tuple(where for where in reading.encodings if where < at),
        skipped=tuple(block for block in reading.skipped if block.offset < at),
    )


#: A token of a block the reader skips, as TeX's default category codes make one: a control
#: word or a control symbol, a comment to its line's end, or a brace.
_BLOCK_TOKEN = re.compile(r"\\(?:[A-Za-z]+|.)|%[^\n]*|[{}]", re.DOTALL)


def _opens_conditional(name: str) -> bool:
    """Whether a control word opens a TeX conditional that a `\\fi` closes: TeX's `\\if…`
    primitives and those `\\newif` makes, not `\\iff` and `\\ifthenelse`."""
    return name.startswith("if") and name not in COMMANDS and name not in NOT_CONDITIONALS


#: The commands that may define in a `\\makeatletter` block a command whose name holds `@`,
#: and not `\\@` alone, which the body never calls (Basile, 2026-11-13, after round 2 of
#: #674: the rule kept simple, rather than `@` followed through each branch).
_BLOCK_DEFINERS = frozenset({"def", "edef", "gdef", "xdef", "let", "newcommand", "renewcommand",
                             "providecommand"})  # fmt: skip
#: The commands whose definition refuses any block: what they define, an environment among
#: it, the body may call whatever its name, so that the reader would not see what changed.
#: With `\\@namedef`, `\\@` followed by `namedef` (`_block_end`).
_OTHER_DEFINERS = frozenset({
    "DeclareRobustCommand", "NewDocumentCommand", "RenewDocumentCommand",
    "ProvideDocumentCommand", "DeclareDocumentCommand", "newenvironment", "renewenvironment",
    "NewDocumentEnvironment", "RenewDocumentEnvironment", "ProvideDocumentEnvironment",
    "DeclareDocumentEnvironment", "newrobustcmd", "renewrobustcmd", "providerobustcmd",
    "newif",
})  # fmt: skip
#: The name a command of `_BLOCK_DEFINERS` defines, past a star and a brace,
#: `\\newcommand*{\\x}`, with `@` a letter in it, as it is in a `\\makeatletter` block.
_BLOCK_DEFINED = re.compile(r"\s*\*?\s*\{?\s*\\([A-Za-z@]+|.)")


def _defines(text: str, end: int, name: str) -> bool:
    """Whether the control word or symbol `name`, ending at `end`, defines anything: a
    command of `_BLOCK_DEFINERS` or of `_OTHER_DEFINERS`, or LaTeX's `\\@namedef`."""
    return (name in _BLOCK_DEFINERS or name in _OTHER_DEFINERS
            or (name == "@" and text.startswith("namedef", end)))  # fmt: skip


def _at_definition_end(text: str, end: int, name: str) -> int:
    """Where the name a definition in a `\\makeatletter` block defines ends, past it, where
    that name holds `@` and is not `\\@`, and the command is one of `_BLOCK_DEFINERS`; -1
    where the definition refuses the block."""
    if name not in _BLOCK_DEFINERS:
        return -1
    defined = _BLOCK_DEFINED.match(text, end)
    if defined is None or "@" not in defined.group(1) or defined.group(1) == "@":
        return -1
    return defined.end()


def _block_end(text: str, start: int, closer: str) -> int:
    """Where a block opened just before `start` ends, past its `closer`, or -1, and the block
    is refused as before, where it is not one the reader skips (Basile, 2026-11-13):

    - a `\\makeatletter` runs to its `\\makeatother`, and holds no `\\catcode`, no TeX
      conditional, and no definition but of a command whose name holds `@`, not `\\@`
      alone, by a command of `_BLOCK_DEFINERS`, `\\long\\def\\@ifdim` say, whose name is
      no conditional;
    - a conditional runs to its matching `\\fi`, each conditional inside opening a `\\fi` of
      its own, and holds no definition of any kind (`_defines`), no `\\makeatletter`, no
      `\\makeatother` and no `\\catcode`.

    A comment counts for nothing. A brace in the block that closes a group opened before
    it, or one it opens that it does not close by its end, refuses it too: TeX ends a
    `\\makeatletter` with the group it stands in, and the reader's groups would no longer be
    the file's. The file holding no such end refuses it."""
    at_block = closer == "makeatother"
    depth, braces, past = 0, 0, start
    for token in _BLOCK_TOKEN.finditer(text, start):
        if token.start() < past:
            continue  # the name a definition defines, read with it
        found = token.group(0)
        if found == "{":
            braces += 1
        elif found == "}":
            braces -= 1
            if braces < 0:
                return -1
        elif found[0] == "\\":
            name = found[1:]
            if name == "catcode":
                return -1
            if _defines(text, token.end(), name):
                past = _at_definition_end(text, token.end(), name) if at_block else -1
                if past < 0:
                    return -1
                # The brace a name is written in, `\newcommand{\my@x}`, opens a group.
                braces += text.count("{", token.end(), past)
            elif at_block:
                if name == "makeatother":
                    return token.end() if braces == 0 else -1
                if name == "fi" or _opens_conditional(name):
                    return -1
            elif name in ("makeatletter", "makeatother"):
                return -1
            elif name == "fi":
                if depth == 0:
                    return token.end() if braces == 0 else -1
                depth -= 1
            elif _opens_conditional(name):
                depth += 1
    return -1


def _comment_end(text: str, at: int) -> int:
    """Where a comment opened at `at` ends: before its line's break."""
    end = text.find("\n", at)
    return len(text) if end < 0 else end


def _parameter_tokens(text: str, start: int, end: int, word: bool) -> str:
    """A definition's parameter text, from past its command to its body's brace, as TeX
    reads it: past the spaces after a control word, and without its comments, each with its
    line's break and the next line's spaces (`_Reader._parameter_text`)."""
    if word:
        start = min(_SKIPPED.match(text, start).end(), end)
    return _IN_PARAMETERS.sub("", text[start:end])


#: A comment in a parameter text, with its line's break and the next line's spaces.
_IN_PARAMETERS = re.compile(r"(?<!\\)%[^\n]*(?:\n[ \t]*)?")


def _delimiter(written: str, letters: re.Pattern[str]) -> re.Pattern[str]:
    """What a use of a command defined with the parameter text `written` and no parameter is
    followed by, as TeX matches it token by token: a control word not run on by a letter and
    the spaces after it skipped, a run of spaces as one space, and a line break, not a blank
    line, as a space too. The spaces after a control word are no token, in the parameter text
    as at a use, so `\\def\\x\\relax /{a}` is followed by `\\relax/` (round 1 of #442)."""
    pattern, word = [], False
    for token in re.finditer(rf"\\{letters.pattern}|\\.|\s+|.", written, re.DOTALL):
        found = token.group(0)
        if found.isspace():
            if not word:
                pattern.append(r"(?:[ \t]+(?:\r?\n[ \t]*)?|\r?\n[ \t]*)")
        elif found.startswith("\\") and letters.fullmatch(found[1:]):
            pattern.append(re.escape(found) + f"(?!{letters.pattern[:-1]})" + _SKIPPED.pattern)
        else:
            pattern.append(re.escape(found))
        word = found.startswith("\\") and letters.fullmatch(found[1:]) is not None
    return re.compile("".join(pattern))


#: A comment, to its line's end, among what TeX passes over before an argument.
_COMMENT = re.compile(r"%[^\n]*")


def _before_argument(text: str, at: int) -> int:
    """Where TeX looks for the next argument from `at`: past spaces and one line break, and
    past a comment, whose line's break goes with it, and the next line's spaces; not past a
    blank line, which is a paragraph's end (2026-10-23: pandoc's
    `\\newenvironment{CSLReferences}[2] % #1 hanging-indent`, its body on the next line, was
    read as a group, and the brace after it closed nothing)."""
    line_start = False
    while at < len(text):
        character = text[at]
        if character == "\n":
            if line_start:
                return at
            line_start = True
        elif character == "%":
            at = _comment_end(text, at)
            line_start = True
        elif character not in " \t\r":
            return at
        at += 1
    return min(at, len(text))


def _maths_keeps(character: str) -> bool:
    """Whether maths keeps a character of its text: all of it, as Markdown's `mask` keeps
    `$...$`; its commands, braces and delimiters are blanked apart."""
    return True


def _sets_text(name: str) -> bool:
    """Whether an environment sets its body as text where maths holds it: a typed table's
    cells are text inside an equation too, and open maths of their own (corpus run of
    2026-11-11: 2103.00772 sets its cases as a `tabular` inside an equation)."""
    return name in TYPED_TABLES


def _note_role(kind: str) -> str:
    """How a citation's note or another prose argument is read."""
    return PROSE if kind == "p" else BLANK


class _Reader:
    def __init__(
        self,
        text: str,
        body: bool,
        environments: tuple[str, ...] = (),
        loose: bool = False,
        package: bool = False,
        delimited: frozenset[str] = frozenset(),
        own: frozenset[str] = frozenset(),
        literal: tuple[tuple[str, str], ...] = (),
        loaded: frozenset[str] = frozenset(),
        *,
        later: tuple[str, ...] = (),
    ) -> None:
        self.text = text
        self.n = len(text)
        #: The environments the file opens at its `\\begin{document}` (`read`).
        self.later = later
        self.out = list(text)
        self.pos = 0
        self.body = body
        self.loose = loose
        self.stack: list[_Frame] = []
        self.pending: tuple[str, ...] = ()
        self.command = ""
        self.refused: Refusal | None = None
        self.skipped: list[Refusal] = []
        #: Where the last `\\newif` the reader read ends, or -1.
        self.newif_end = -1
        self.letters = _LETTERS_AT if package else _LETTERS
        self.definitions = 0
        self.environments: list[str] = []
        self.inputs: list[Input] = []
        self.headings: list[Heading] = []
        self.abstracts: list[tuple[int, int]] = []
        self.packages: list[tuple[int, str]] = []
        self.bindings: list[BindingUse] = []
        self.suspects: list[tuple[int, int]] = []
        self.tables: list[tuple[int, int]] = []
        self.listings: list[Listing] = []
        self.cited: list[Cited] = []
        self.citation_at = -1
        self.maths: list[tuple[int, int, bool]] = []
        self.floats: list[tuple[int, int]] = []
        self.figures: list[tuple[int, int]] = []
        self.references: list[tuple[int, int]] = []
        self.body_end = -1
        self.bodies: list[tuple[int, int]] = []
        self.pointers: list[tuple[int, int]] = []
        self.pointer_at = -1
        self.comments: list[tuple[int, int]] = []
        self.unprinted: list[tuple[int, int]] = []
        self.graphics: list[tuple[int, int, int]] = []
        self.graphics_at = -1
        self.code: list[tuple[int, int]] = []
        self.declared: list[tuple[str, str]] = []
        self.body_start = 0 if body else -1
        self.siunitx = 0
        #: The command a definition being read defines, until its body opens.
        self.defining = ""
        #: Whether the `\\def` read next follows a preamble's `\\expandafter` passed over.
        self.expanding = False
        #: The commands defined with delimited parameters, here and in the files `delimited`
        #: names, each use of which is refused where it would print; and those defined here.
        self.delimited = set(delimited)
        self.defined_delimited: list[str] = []
        #: What the other files of the tree define so, which nothing here takes back.
        self.told_delimited = frozenset(delimited)
        #: A known command the preamble defines again, and where its name stands, until its
        #: body opens and is read for the forms read as before (`_read_as_before`).
        self.restyling: tuple[str, int] | None = None
        #: The front matter's commands the author defines, here and in the files `own` names,
        #: read as unknown commands are; and those defined here (round 1, part 2).
        self.own = set(own)
        self.defined_own: list[str] = []
        #: The commands defined with a parameter text and no parameter, here and in the files
        #: `literal` names, with what their uses are followed by; and those defined here.
        self.literal = {name: _delimiter(written, self.letters) for name, written in literal}
        self.defined_literal: list[tuple[str, str]] = []
        #: The packages the other files of the tree load.
        self.loaded = loaded
        self.encodings: list[int] = []
        self.heading_at = -1
        #: What a picture prints as text (`pictures.py`): each brace that opens one, with where
        #: its prose starts, and each text without braces.
        self.picture_text: dict[int, int] = {}
        self.picture_spans: list[tuple[int, int]] = []
        #: Where the prose's last ``` `` ``` stands while no `''` or `"` has closed it, or -1.
        self.quote_open = -1
        self._inherit(environments, 0)

    def _inherit(self, environments: tuple[str, ...], at: int) -> None:
        """Open the environments the file's input stood in, from `at`."""
        for name in environments:
            if name in PICTURES and self._role() == PROSE:
                self._picture_printed(at, self.n)
            role = MATHS_READ if name in MATHS else self._entered(name, self._role())
            self.stack.append(_Frame("env", role, 0, name, table=name in TABLES, inherited=True))
            self.environments.append(name)

    # -- running -----------------------------------------------------------------------
    def run(self) -> Reading:
        while self.pos < self.n and self.refused is None:
            if self.pending and self._argument():
                continue
            self._step()
        opened = [frame for frame in self.stack if not frame.inherited]
        if self.refused is None and opened:
            self._refuse("tex-unbalanced", opened[0].start, f"{_opened(opened[0])} is not closed")
        # A picture's text without braces, `label=above:Text`, is read as typed.
        for start, end in self.picture_spans:
            for index in range(start, end):
                if self.out[index] == NUL:
                    self.out[index] = self.text[index]
        masked = "".join(self.out)
        # A table the file was input inside and does not close runs to its end.
        tables = self.tables + [(0, self.n) for frame in self.stack
                                if frame.inherited and frame.closer in TYPED_TABLES]  # fmt: skip
        # So does a float or a displayed formula: a figure's file input inside `figure`.
        floats = self.floats + [(0, self.n) for frame in self.stack
                                if frame.inherited and frame.closer in FLOATS]  # fmt: skip
        maths = self.maths + [(0, self.n, True) for frame in self.stack
                              if frame.inherited and frame.closer in MATHS]  # fmt: skip
        figures = self.figures + [(0, self.n) for frame in self.stack
                                  if frame.inherited and frame.closer in FIGURES]  # fmt: skip
        references = self.references + [(0, self.n) for frame in self.stack
                                        if frame.inherited and frame.closer == REFERENCES]
        found = (tuple(self.inputs), tuple(self.headings), tuple(self.abstracts),
                 tuple(self.packages), tuple(self.bindings), tuple(self.suspects),
                 tuple(sorted(tables)), tuple(self.listings), tuple(self.cited),
                 tuple(sorted(maths)), tuple(sorted(floats)), self.body_start,
                 tuple(self.code), tuple(self.declared), tuple(sorted(figures)),
                 tuple(sorted(references)), self.body_end, tuple(self.bodies),
                 tuple(self.pointers), tuple(self.comments), tuple(self.unprinted),
                 tuple(self.graphics), tuple(self.defined_delimited),
                 tuple(self.defined_own), tuple(self.defined_literal),
                 tuple(self.encodings), tuple(self.skipped))  # fmt: skip
        if self.refused is None:
            return Reading(masked, (), *found)
        # Past the refusal nothing is read, its line breaks kept (`_unread`), and nothing the
        # run found there is kept (`_before`).
        at = self.refused.offset
        return _before(Reading(masked[:at] + _unread(self.text[at:]), (self.refused,), *found),
                       at)  # fmt: skip

    def _refuse(self, code: str, at: int, message: str) -> None:
        if self.refused is None:
            self.refused = Refusal(code, at, message)

    def _role(self) -> str:
        if self.stack:
            return self.stack[-1].role
        return PROSE if self.body else PREAMBLE

    def _reads(self) -> bool:
        return self._role() in (PROSE, MATHS_READ)

    def _blank(self, start: int, end: int) -> None:
        for index in range(start, min(end, self.n)):
            if self.out[index] not in "\n\r":
                self.out[index] = NUL

    def _keep_or_blank(self, start: int, end: int) -> None:
        role = self._role()
        if role == MATHS_READ:
            for index in range(start, min(end, self.n)):
                if not _maths_keeps(self.text[index]) and self.out[index] not in "\n\r":
                    self.out[index] = NUL
        elif role != PROSE:
            self._blank(start, end)

    # -- arguments -----------------------------------------------------------------------
    def _after_space(self, at: int) -> int:
        seen_break = False
        while at < self.n and self.text[at] in " \t\r\n":
            if self.text[at] == "\n":
                if seen_break:
                    return at
                seen_break = True
            at += 1
        return at

    def _argument(self) -> bool:
        """Take the next argument the last command expects where it stands. False where
        there is none, and the text is read on as it comes. In amsmath's environments, its
        cases and matrices among them, `\\\\` takes its length only where it follows at once:
        a `[0.5, 1.2]` opening the next row prints (rounds 1 and 4 of #380). Elsewhere it
        skips spaces before it, as the kernel's and a bare array's do, and `\\\\ [2pt]` in a
        table or an array is a length (rounds 2 and 3)."""
        amsmath = self.command == "\\" and bool(self.environments) and (
            self.environments[-1] in AMSMATH
        )
        start = self.pos
        at = self.pos if amsmath else _before_argument(self.text, self.pos)
        taken = self._take(at)
        if taken:
            # A comment passed over on the way is one, blanked and recorded where it stands.
            for comment in _COMMENT.finditer(self.text, start, at):
                self._blank(comment.start(), comment.end())
                self.comments.append(comment.span())
        return taken

    def _take(self, at: int) -> bool:
        """`_argument` at `at`, where TeX finds the next argument."""
        here = self.text[at : at + 1]
        while self.pending:
            spec = self.pending[0]
            if spec == "*":
                self.pending = self.pending[1:]
                if here == "*":
                    self._blank(at, at + 1)
                    self.pos = at + 1
                    return True
                continue
            if spec[0] == "[":
                if here == "[" and spec[1] == "o":
                    # An option list is blanked, a value read (`commands.py`, `[o]`).
                    close = self.text.find("]", at, at + 300)
                    listed = "=" in self.text[at : close if close >= 0 else at + 300]
                    self._open("opt", "b" if listed else "p", at, "]", siunitx=listed)
                    return True
                if here == "[":
                    self._open("opt", spec[1], at, "]")
                    return True
                self.pending = self.pending[1:]
                continue
            if spec[0] == "<":
                # apacite's prenote, `\citeA<see>[p.~3]{key}`, read as a citation's note is.
                if here == "<":
                    self._open("opt", spec[1], at, ">")
                    return True
                self.pending = self.pending[1:]
                continue
            if spec[0] == "(":
                # A trim such as `(lr)` is a few letters: looked for that far, on its line. A
                # multi-citation's global note is a phrase, and may wrap (round 1 of step 5).
                reach, stop = (_NOTE_REACH, "\n\n") if self.command in CITATIONS else (32, "\n")
                end = self.text.find(")", at, at + reach) if here == "(" else -1
                if end >= 0 and stop not in self.text[at:end]:
                    self._blank(at, end + 1)
                    self.pos = end + 1
                    self.pending = self.pending[1:]
                    return True
                if here == "(" and self.command in CITATIONS:
                    # Read past, the note would hide the keys after it (round 2 of step 5).
                    said = f"its global note is not closed within {_NOTE_REACH} characters"
                    self._refuse("tex-refused", at, f"\\{self.command} is not read: {said}")
                    return True
                self.pending = self.pending[1:]
                continue
            return self._mandatory(spec[1], at, here)
        return False

    def _mandatory(self, kind: str, at: int, here: str) -> bool:
        if kind == "c" and here in ("\\", "{"):
            named = _BRACED_NAME.match(self.text, at) if here == "{" else None
            end = named.end() if named else self._name_end(at) if here == "\\" else -1
            if end < 0:
                self._open("arg", "b", at, "}")
                return True
            self._defines(named.group(1) if named else self.text[at + 1 : end], at)
            self._blank(at, end)
            self.pos = end
            self.pending = self.pending[1:]
            return True
        if here != "{":
            self.pending = ()
            # A definition whose body is not there defines nothing a later body is of.
            self.defining, self.restyling = "", None
            return False
        if kind == "r":
            end = self._group_end(at)
            if end < 0:
                said = f"the argument of \\{self.command} is not closed"
                self._refuse("tex-unbalanced", at, said)
                return True
            self._blank(at, end)
            self.pos = end
            self.pending = self.pending[1:]
            return True
        self._open("arg", kind, at, "}")
        return True

    def _open(
        self, kind: str, spec: str, at: int, closer: str, *, siunitx: bool | None = None
    ) -> None:
        role = self._role()
        # A body prints where it is used, but a LaTeX parameter's is a size. What is being
        # defined is spent on the body that opens, whatever its role (round 2 of #400: left
        # set, it blanked the next body that defined nothing, `\AtBeginDocument`'s).
        parameter = spec == "d" and self.defining in PARAMETERS
        if spec == "d":
            self.defining = ""
            self._restyled(at)
        if role == BLANK or spec in "bc":
            chosen = BLANK
        elif spec == "d":
            chosen = BLANK if parameter else PROSE
        elif role == PREAMBLE:
            chosen = PROSE if self._printed_from_preamble(self.command) else PREAMBLE
        else:
            chosen = _note_role(spec)
        frame = _Frame(kind, chosen, at, closer, self.pending[1:], self.command, spec == "d",
                       siunitx=self.command in SIUNITX if siunitx is None else siunitx)  # fmt: skip
        self.siunitx += frame.siunitx
        heads = self.command in _HEADING_COMMANDS
        if kind == "arg" and spec == "p" and heads and not self.definitions and chosen == PROSE:
            frame.heading = LEVELS.get(self.command, 1)
            frame.origin = self.heading_at
        if kind == "arg" and spec == "b" and self.command in CITATIONS and not self.definitions:
            self._cite(at)
        # A range's span runs to its second label's group (corpus round, 2026-10-23).
        pointer = self.command in POINTERS and not self.definitions
        if kind == "arg" and spec == "b" and pointer and (
            self.command not in RANGES or not self.pending[1:]
        ):
            end = self._group_end(at, comments=True)
            if end >= 0:
                self.pointers.append((self.pointer_at, end))
        if kind == "arg" and self.command == "includegraphics":
            end = self._group_end(at)
            if end >= 0:
                self.graphics.append((self.graphics_at, end, at))
        self.definitions += frame.definition
        self.stack.append(frame)
        # A Markdown binding as a command's argument, `\\emph{{results.x}}` (round 1 of #400:
        # only one opening a group of its own was seen).
        # `\\mg{{results.x}}` is `\\mg`'s own, said once there (round 2 of #400), but in
        # siunitx, where `\\mg` records nothing (round 3).
        mg_says_it = self.command == "mg" and not self.siunitx
        if closer == "}" and not mg_says_it and _MARKDOWN_BINDING.match(self.text, at):
            self.suspects.append((at, self._suspect_end(at)))
        self._blank(at, at + 1)
        self.pos = at + 1
        self.pending = ()

    def _cite(self, at: int) -> None:
        """Record each key the citation's braces at `at` name, where it stands: split at the
        commas, as natbib and biblatex split them, a space round each taken off."""
        end = self._group_end(at, comments=True)
        if end < 0:
            return  # the brace left open is refused where it stands
        narrative = CITATIONS[self.command]
        offset = at + 1
        for part in _key_list(self.text[at + 1 : end - 1]).split(","):
            key = part.strip()
            if key:
                self.cited.append(Cited(key, offset + part.index(key), narrative,
                                        self.citation_at, end))  # fmt: skip
            offset += len(part) + 1

    def _group_end(self, at: int, *, comments: bool = False) -> int:
        """Where a brace group opened at `at` ends, read as characters: `%` and `#` are no
        signs in a URL. With `comments`, a brace in a comment is passed over, as LaTeX passes
        over a comment in a citation's keys."""
        depth, index = 0, at
        while index < self.n:
            character = self.text[index]
            index += 1
            if comments and character == "%" and self.text[index - 2] != "\\":
                index = _comment_end(self.text, index - 1)
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    return index
        return -1

    # -- one token -------------------------------------------------------------------------
    def _step(self) -> None:
        at, character = self.pos, self.text[self.pos]
        if character == "\\":
            self._control(at)
        elif character == "%":
            end = _comment_end(self.text, at)
            self._blank(at, end)
            self.comments.append((at, end))
            self.pos = end
        elif character == "{":
            if _MARKDOWN_BINDING.match(self.text, at):
                self.suspects.append((at, self._suspect_end(at)))
            # A picture's text, a node's say, is prose from where its prose starts.
            prose = self.picture_text.get(at, -1)
            self.stack.append(_Frame("group", PROSE if prose >= 0 else self._role(), at))
            self._blank(at, max(at + 1, prose))
            self.pos = max(at + 1, prose)
        elif character == "}":
            self._close_group(at)
        elif character in "]>" and self.stack and self.stack[-1].kind == "opt" and (
            self.stack[-1].closer == character
        ):
            self._close(at, 1)
        elif character == "$":
            self._dollar(at)
        elif character in "&~":
            self._space(at, 1, table_only=character == "&")
        elif character == "#" and self.definitions and _PARAMETER.match(self.text, at):
            end = _PARAMETER.match(self.text, at).end()
            self._blank(at, end)
            self.pos = end
        elif character in "`'" and self.text[at + 1 : at + 2] == character:
            self._quote(at, "\N{LEFT DOUBLE QUOTATION MARK}" if character == "`"
                        else "\N{RIGHT DOUBLE QUOTATION MARK}")  # fmt: skip
        elif character == '"' and self._closes_quote(at):
            self.out[at] = "\N{RIGHT DOUBLE QUOTATION MARK}"
            self.quote_open = -1
            self.pos = at + 1
        else:
            run = _TEXT.match(self.text, at)
            end = run.end() if run else at + 1
            if self.stack and self.stack[-1].closer == ">":
                # An apacite prenote ends at its `>`, which a run of text would pass.
                stop = self.text.find(">", at, end)
                end = stop if stop > at else end
            self._keep_or_blank(at, end)
            self.pos = end

    def _space(self, at: int, width: int, *, table_only: bool = False) -> None:
        if self._reads() and (not table_only or self._in_table()):
            self.out[at] = " "
            self._blank(at + 1, at + width)
        else:
            self._keep_or_blank(at, at + width)
        self.pos = at + width

    def _quote(self, at: int, mark: str) -> None:
        if self._role() == PROSE:
            self.out[at], self.out[at + 1] = mark, NUL
            self.quote_open = at if mark == "\N{LEFT DOUBLE QUOTATION MARK}" else -1
        else:
            self._keep_or_blank(at, at + 2)
        self.pos = at + 2

    def _closes_quote(self, at: int) -> bool:
        """Whether a straight `"` in prose closes the quotation a ``` `` ``` opened in its
        paragraph: ``` ``word" ``` prints as ``` ``word'' ``` does, the font's `"` being a
        closing mark (corpus round, 2026-10-23). Another `"` is the character typed, and so
        is one before a letter, which closes nothing and with babel's German is an accent,
        `"a`. A quotation whose paragraph has ended is closed, so that no paragraph is
        searched twice."""
        if self.quote_open < 0 or self._role() != PROSE or _ACCENTED.match(self.text, at):
            return False
        ended = self._paragraph_ended(self.quote_open, at)
        self.quote_open = -1
        return not ended

    def _paragraph_ended(self, start: int, end: int) -> bool:
        """Whether a paragraph ends between `start` and `end`: at a blank line, or at a
        `\\par` TeX reads, not one in a comment or what TeX passes over (Known gaps,
        2026-10-27: a quotation left open before a `\\par` was closed by a `"` after it)."""
        if _PARAGRAPH_END.search(self.text, start, end) is not None:
            return True
        passed = [*self.comments, *self.unprinted, *((s.offset, s.end) for s in self.skipped)]
        return any(not any(low <= found.start("par") < high for low, high in passed)
                   for found in _PAR.finditer(self.text, start, end))  # fmt: skip

    def _in_table(self) -> bool:
        """Whether the innermost environment is a table: kept apart from the stack, so that a
        file of braces and `&` is not read again for each `&` (round 1 of #380)."""
        return bool(self.environments) and self.environments[-1] in TABLES

    def _close_group(self, at: int) -> None:
        top = self.stack[-1] if self.stack else None
        if top is None or top.kind not in ("group", "arg"):
            self._refuse("tex-unbalanced", at, "this brace closes nothing that is open")
            return
        self._close(at, 1)

    def _close(self, at: int, width: int) -> None:
        frame = self.stack.pop()
        self.definitions -= frame.definition
        if frame.definition and frame.command not in HOOKS:
            self.bodies.append((frame.start, at + width))
        self.siunitx -= frame.siunitx
        self._blank(at, at + width)
        self.pos = at + width
        if frame.kind in ("arg", "opt"):
            self.pending, self.command = frame.rest, frame.command
        if frame.heading is not None:
            if frame.command in ABSTRACT_COMMANDS:
                self.headings.append(Heading(frame.origin, 1, "Abstract"))
                self.abstracts.append((frame.origin, at + width))
            else:
                title = " ".join("".join(self.out[frame.start + 1 : at]).replace(NUL, "").split())
                self.headings.append(Heading(frame.origin, frame.heading, title, at + width))
        if frame.kind == "maths":
            self.maths.append((frame.start, at + width, frame.closer in ("$$", "\\]")))
        if frame.kind == "arg" and frame.command == "texttt" and not self.definitions:
            self.code.append((frame.start, at + width))

    def _dollar(self, at: int) -> None:
        top = self.stack[-1] if self.stack else None
        # The maths that is open closes first: `$x$$y$` is two formulas (round 1 of #380).
        if top is not None and top.kind == "maths" and self.text.startswith(top.closer, at):
            self._close(at, len(top.closer))
            return
        closer = "$$" if self.text.startswith("$$", at) else "$"
        role = self._role()
        if role in (BLANK, PREAMBLE):
            self._blank(at, at + len(closer))
            self.pos = at + len(closer)
        elif role == MATHS_READ:
            self._refuse("tex-unbalanced", at, "maths is opened inside maths")
        else:
            self.stack.append(_Frame("maths", MATHS_READ, at, closer))
            self._blank(at, at + len(closer))
            self.pos = at + len(closer)

    # -- commands --------------------------------------------------------------------------
    def _name_end(self, at: int) -> int:
        if at + 1 >= self.n:
            return at + 1
        word = self.letters.match(self.text, at + 1)
        return word.end() if word else at + 2

    def _control(self, at: int) -> None:
        end = self._name_end(at)
        name = self.text[at + 1 : end]
        if not name:
            self._blank(at, end)
            self.pos = end
        elif self.letters.fullmatch(name):
            self._blank(at, end)
            self.pos = end
            self._word(name, at, end)
        else:
            self._symbol(name, at)

    def _symbol(self, symbol: str, at: int) -> None:
        reads = self._reads()
        self.pos = at + 2
        if symbol in "%$&#_{}":
            if reads:
                self.out[at], self.out[at + 1] = symbol, NUL
            else:
                self._blank(at, at + 2)
        elif symbol == "\\":
            self._space(at, 2)
            self.command, self.pending = "\\", COMMANDS["\\"]
        elif symbol in " ,;:>\n":
            self._space(at, 2 if symbol != "\n" else 1)
            self.pos = at + 2
        elif symbol in "([" and self._role() == PROSE:
            self.stack.append(_Frame("maths", MATHS_READ, at, "\\" + {"(": ")", "[": "]"}[symbol]))
            self._blank(at, at + 2)
        elif (symbol in ")]" and self.stack and self.stack[-1].kind == "maths"
              and self.stack[-1].closer == "\\" + symbol):  # fmt: skip
            self._close(at, 2)
        elif symbol in ")]" and self._reads():
            self._refuse("tex-unbalanced", at, f"\\{symbol} closes no maths that is open")
        else:
            self._blank(at, at + 2)

    def _word(self, name: str, at: int, end: int) -> None:
        if name == "newif":
            # Where the command TeX reads ends, not one in a comment or a `\\verb`, which the
            # reader never reads as a command (round 1 of #674).
            self.newif_end = end
        if name in REFUSED:
            if self._expands_a_definition(name, end):
                self.expanding = True
            elif not self._machinery(name):
                self._refuse("tex-refused", at, f"\\{name} is not read: {REFUSED[name]}")
        elif name in self.delimited and self._prints():
            # Before any command the reader reads by its name: one the preamble defined again
            # prints what the author wrote, not what the reader takes it to print.
            self._refuse("tex-refused", at, f"\\{name} is not read: {_redefined_said(name)}")
        elif name in ("makeatletter", "makeatother"):
            header = self._list_header()
            if name == "makeatletter" and self.body and not self.loose and not header:
                said = "\\makeatletter in the body changes how characters are read"
                self._skip_block(at, "makeatother", said)
                return
            self.letters = _LETTERS_AT if name == "makeatletter" else _LETTERS
        elif name == "iffalse":
            self._skip_false(at)
        elif _opens_conditional(name):
            # A reference list's header tests what is loaded, and both branches are read, as
            # in the preamble (2026-10-23: natbib's `\\ifx\\csname urlstyle\\endcsname`). One
            # `\\newif` names is defined, and opens nothing.
            if (self.body and not self.loose and not self._list_header()
                    and not self._named_by_newif(at)):  # fmt: skip
                said = "a conditional in the body prints one branch, and which is not read"
                self._skip_block(at, "fi", f"\\{name} is not read: {said}",
                                 f"\\{name} in the body opens a conditional, which prints one "
                                 "of its branches, and neither is read")  # fmt: skip
        elif name in ("input", "include") and not self.definitions:
            self._input(at, end)
        elif name in IMPORTS and not self.definitions:
            self._import(name, at, end)
        elif name in PLACED and not self.definitions:
            self._place(name, at, end)
        elif name == "verb":
            self._verb(at, end)
        elif name in ("begin", "end"):
            self._environment(name, at, end)
        elif name in ("def", "gdef", "edef", "xdef", "let"):
            self._definition(name, at, end)
        elif name in SPACES:
            if self._reads():
                self.out[at] = " "
        elif name in SYMBOLS:
            if self._reads():
                self.out[at] = SYMBOLS[name]
        elif name in ("usepackage", "RequirePackage", "inputencoding"):
            self._encoding(at)
            if name != "inputencoding":
                self._packages(at, end)
            if name in COMMANDS:
                self.command, self.pending = name, COMMANDS[name]
        elif name == "mg":
            self._binding(at, end)
            self.command, self.pending = name, COMMANDS[name]
        elif name == "tikzstyle" and (style := _STYLE_NAME.match(self.text, end)):
            # Its name passed over, then its options as a command's, past the sign between.
            self._blank(end, style.end())
            self.pos = style.end()
            self.command, self.pending = name, COMMANDS[name]
        elif name in COMMANDS and name not in self.own:
            if name in _HEADING_COMMANDS:
                self.heading_at = at
            if name in CITATIONS:
                self.citation_at = at
            if name in POINTERS:
                self.pointer_at = at
            if name == "bibitem":
                self._past_header()
            if name == "includegraphics":
                self.graphics_at = at
            if name in ("documentclass", "bibliographystyle"):
                self._declares(name, end)
            self.command, self.pending = name, COMMANDS[name]
        elif name in self.literal:
            self._past_delimiter(name, at, end)
        elif self._unknown_citation(name):
            # A citation command the reader does not know would hide its keys from G7 (DESIGN.md,
            # "Citations"); one an author defines is refused where it is used.
            said = ("a citation command the reader does not know, whose keys G7 would not see; "
                    "cite with \\cite or one of the natbib and biblatex commands it reads")
            self._refuse("tex-refused", at, f"\\{name} is not read: {said}")
        elif _near_binding(name) and _LOOKS_BOUND.match(self.text, end):
            self.suspects.append((at, self._suspect_end(at)))

    def _machinery(self, name: str) -> bool:
        """Whether a command refused elsewhere is accepted here: in a reference list typed in
        `thebibliography`, whose header BibTeX's styles write with `\\expandafter` and
        `\\csname`, and with `\\catcode` in a definition's body, which prints nothing where it
        stands (2026-10-23: natbib's and REVTeX's lists were refused at their header)."""
        if not self._list_header():
            return False
        return name in REFERENCE_MACHINERY or (name in CATEGORY and self.definitions > 0)

    def _restyled(self, at: int) -> None:
        """Read the body that opens at `at` of a known command the preamble defines again:
        where it is one of the two forms read as before (`_read_as_before`), its uses are
        not refused, unless another file of the tree defines it otherwise."""
        if self.restyling is None:
            return
        (name, start), self.restyling = self.restyling, None
        end = self._group_end(at)
        if end < 0 or name in self.told_delimited:
            return
        # `\@startsection` is one command only where `@` is a letter: in a package, or past
        # `\makeatletter`.
        if name in LEVELS and self.letters is not _LETTERS_AT:
            return
        if _read_as_before(name, self.text[start:at], self.text[at + 1 : end - 1]):
            self.delimited.discard(name)
            if name in self.defined_delimited:
                self.defined_delimited.remove(name)

    def _expands_a_definition(self, name: str, end: int) -> bool:
        """Whether an `\\expandafter` only redefines a command in the preamble, outside any
        definition's body, and is passed over: Scientific WorkPlace's
        `\\expandafter\\def\\expandafter\\normalsize\\expandafter{...}`, which adds to what a
        command does (2026-11-11: it was refused, and the rest of the file read as typed).
        The `\\def` is then read as any, the command it names defined again, whose uses are
        refused where they print if the reader knows it (`_defines`)."""
        return (name == "expandafter" and not self.body and not self.definitions
                and _EXPANDED_DEFINITION.match(self.text, end) is not None)  # fmt: skip

    def _past_delimiter(self, name: str, at: int, end: int) -> None:
        """Pass over what follows a use of a command defined with a parameter text and no
        parameter, `\\eg/`: TeX takes it with the command, and the body prints in its place.
        Where it does not follow, TeX stops at the use, which is refused where it prints, as
        a use of delimited parameters is (`\\def\\bSig\\mathbf{\\Sigma}`, then `$\\bSig$`)."""
        written = self.literal[name].match(self.text, _SKIPPED.match(self.text, end).end())
        if written is not None:
            self._blank(end, written.end())
            self.pos = written.end()
        elif self._prints():
            said = ("what its definition says follows it does not, and TeX stops there; "
                    "define it with \\newcommand")
            self._refuse("tex-refused", at, f"\\{name} is not read: {said}")

    def _past_header(self) -> None:
        """Mark the innermost reference list as past its header, at its first `\\bibitem`."""
        for frame in reversed(self.stack):
            if frame.kind == "env" and frame.closer == REFERENCES:
                frame.items = True
                return

    def _loaded(self, packages: tuple[str, ...]) -> bool:
        """Whether one of `packages` is loaded, before here in this file or in another file of
        the tree."""
        named = {name for _at, name in self.packages} | self.loaded
        return any(package in named for package in packages)

    def _prints(self) -> bool:
        """Whether what stands here prints where it stands: read, and in no definition's body,
        though it may be in a hook's, which LaTeX runs where it stands (round 1)."""
        return self._reads() and not any(frame.definition and frame.command not in HOOKS
                                         for frame in self.stack)  # fmt: skip

    def _unknown_citation(self, name: str) -> bool:
        """Whether a command the reader does not know is one that cites, where what it cites
        would print: its name is a citation's (`_cites`), outside a definition's body, outside
        the preamble, where natbib's and biblatex's settings stand, `\\setcitestyle` and
        `\\DeclareCiteCommand` among them (round 1 of step 5), and outside a reference list
        typed in `thebibliography`, whose labels REVTeX writes with `\\citenamefont` and
        harvard with `\\citeauthoryear`, and which cites nothing (2026-10-23)."""
        helper = name in _LIST_HELPERS and REFERENCES in self.environments
        return _cites(name) and not self.definitions and self._role() != PREAMBLE and not helper

    def _list_header(self) -> bool:
        """Whether this stands in a reference list's header, between `\\begin{thebibliography}`
        and its first `\\bibitem`, where BibTeX's styles write what the list needs (round 1 of
        #442: in the entries, a conditional was read through)."""
        for frame in reversed(self.stack):
            if frame.kind == "env" and frame.closer == REFERENCES:
                return not frame.items and not frame.inherited
        return False

    def _binding(self, at: int, end: int) -> None:
        """Record a `\\mg` where it stands, with what its braces hold. In a siunitx command
        `\\mg` is the milligram siunitx defines, `\\qty{5}{\\mg}`, and one that names a key is
        refused, since siunitx parses what it holds and a value's display is formatted text."""
        written = _BINDING.match(self.text, end)
        if self.siunitx:
            if written and _KEYED.match(written.group("inner")):
                self._refuse("tex-refused", at, _BOUND_IN_SIUNITX)
            return
        stop = written.end() if written else _BARE.match(self.text, end).end()
        self.bindings.append(BindingUse(at, stop, written.group("inner") if written else None))

    def _suspect_end(self, at: int) -> int:
        """Where something that looks meant for a binding ends: at the braces that close it,
        on its line."""
        line_end = self.text.find("\n", at)
        line_end = self.n if line_end < 0 else line_end
        close = self.text.find("}", at, line_end)
        if close < 0:
            return line_end
        while close < line_end and self.text[close] == "}":
            close += 1
        return close

    def _input(self, at: int, end: int) -> None:
        """Record an `\\input` with the state it stands in. Its path is read raw; one not
        written in braces, or holding a command, is refused where the tree is read. Its
        argument is then taken as any blanked argument is, so that the mask is the same with
        or without the tree (the old-against-new test of #385). In the preamble, TeX's
        `\\input macros` without braces names the file by the name up to a space, as
        `structure._LOADS` reads a class's (Known gaps, 2026-10-27: an author's `macros.tex`
        was read as a file nothing inputs); in the body it is refused as before."""
        braced = _BRACED_PATH.match(self.text, end)
        bare = None
        if braced is None and not self.body and self.text.startswith("\\input", at):
            bare = _BARE_PATH.match(self.text, end)
        found = braced or bare
        path = found.group(1) if found else ""
        stop = found.end() if found else end
        self.inputs.append(Input(at, stop, path, self.body, tuple(self.environments)))
        self.command, self.pending = "input", COMMANDS["input"]

    def _import(self, name: str, at: int, end: int) -> None:
        """Record the import package's `\\import{folder}{file}` or `\\subimport{folder}{file}`
        as an `\\input` of the file in that folder, which the tree finds (`structure.py`). A
        folder or a file not written in braces leaves the file unnamed, refused there. The
        starred forms are refused by name (round 1)."""
        if self.text.startswith("*", end):
            said = f"it is not followed; write \\{name} without the star"
            self._refuse("tex-refused", at, f"\\{name}* is not read: {said}")
            return
        folder = _BRACED_PATH.match(self.text, end)
        named = _BRACED_PATH.match(self.text, folder.end()) if folder else None
        path = named.group(1) if named else ""
        stop = named.end() if named else folder.end() if folder else end
        self.inputs.append(Input(at, stop, path, self.body, tuple(self.environments), name,
                                 folder.group(1) if folder else ""))  # fmt: skip
        self.command, self.pending = name, COMMANDS[name]

    def _place(self, name: str, at: int, end: int) -> None:
        """Record a `\\subfile{path}` or an `\\includestandalone[options]{path}` as an input
        of the file it places, past its options, which size a picture and print nothing; the
        tree reads that file's document body where the command stands (`structure.py`)."""
        options = _PLACE_OPTIONS.match(self.text, end) if name == "includestandalone" else None
        braced = _BRACED_PATH.match(self.text, options.end() if options else end)
        path = braced.group(1) if braced else ""
        stop = braced.end() if braced else end
        self.inputs.append(Input(at, stop, path, self.body, tuple(self.environments), name))
        self.command, self.pending = name, COMMANDS[name]

    def _packages(self, at: int, end: int) -> None:
        listed = _PACKAGES.match(self.text, end)
        if listed and not self.definitions:
            for name in listed.group(2).split(","):
                if name.strip():
                    self.packages.append((at, name.strip()))
                if name.strip() == "biblatex":
                    self.declared.append(("biblatex", listed.group(1) or ""))

    def _declares(self, name: str, end: int) -> None:
        """Record the class a `\\documentclass` names and its options, or the style a
        `\\bibliographystyle` names, as a journal's profile states them (G4)."""
        found = _PACKAGES.match(self.text, end)
        if found is None or self.definitions:
            return
        if name == "documentclass":
            self.declared.append(("class", found.group(2).strip()))
            for option in (found.group(1) or "").split(","):
                if option.strip():
                    self.declared.append(("class_option", option.strip()))
        else:
            self.declared.append(("bst", found.group(2).strip()))

    def _encoding(self, at: int) -> None:
        """Refuse an input encoding other than UTF-8, set by a package's option or by
        `\\inputencoding` (round 1 of #380: only `\\usepackage` was read), in a file that is
        not ASCII, which reads the same in each of them (2026-10-23: `latin9` was refused in a
        file all of ASCII). Where the file is, the tree holds the others to it."""
        found = _INPUTENC.match(self.text, at)
        named = (found.group(1) or found.group(2) or "") if found else ""
        if not found or {o.strip() for o in named.split(",")} & {"utf8", "utf8x"}:
            return
        if self.text.isascii():
            self.encodings.append(at)
            return
        self._refuse("tex-refused", at, "the input encoding is not UTF-8, in which the file is "
                     "read")  # fmt: skip

    def _skip_false(self, at: int) -> None:
        """Blank an `\\iffalse` block to its `\\fi`, or to its `\\else`, whose branch TeX
        prints and the reader reads (round 1 of #380). A conditional in a comment counts for
        nothing, and neither do `\\iff` and `\\ifthenelse`."""
        depth, scanned, comment = 1, self.pos, False
        for match in _CONDITIONALS.finditer(self.text, self.pos):
            start = match.start()
            # Read forward only, from the last conditional or the last line break, so that a
            # long line of conditionals is not read again for each.
            newline = self.text.rfind("\n", scanned, start)
            if newline >= 0:
                scanned, comment = newline + 1, False
            if not comment:
                comment = _opens_comment(self.text, scanned, start)
            scanned = start
            # `\\else` is a line break and a word, not `\else` (round 2 of #380).
            before = start - 1
            while before >= 0 and self.text[before] == "\\":
                before -= 1
            word = match.group(0)[1:]
            if comment or word in NOT_CONDITIONALS or (start - 1 - before) % 2:
                continue
            if word == "else":
                if depth == 1:
                    self.unprinted.append((self.pos, start))
                    self._blank(at, match.end())
                    self.pos = match.end()
                    return
                continue
            depth += -1 if word == "fi" else 1
            if depth == 0:
                self.unprinted.append((self.pos, start))
                self._blank(at, match.end())
                self.pos = match.end()
                return
        self._refuse("tex-unbalanced", at, "\\iffalse is not closed by \\fi")

    def _named_by_newif(self, at: int) -> bool:
        """Whether the conditional's name at `at` is the one a `\\newif` the reader read
        defines, with only spaces between: a definition, which opens nothing."""
        # Matched in place, so that a `\\newif` far back costs no copy of what follows it.
        return self.newif_end >= 0 and _SPACES_ONLY.fullmatch(self.text, self.newif_end,
                                                              at) is not None  # fmt: skip

    def _skip_block(self, at: int, closer: str, said: str, skipped: str = "") -> None:
        """Skip a block in the body that opens at `at` to its matching `closer`, blanked and
        nothing in it read, `skipped` why (`said` where none is given), and read on past it;
        where it has no such end in the file, refuse it, `said` why, and read nothing more
        (Basile, 2026-11-13: the reading stopped at a `\\makeatletter` and an `\\if` in three
        real papers' bodies, and with it their checks)."""
        end = _block_end(self.text, self.pos, closer)
        if end < 0:
            self._refuse("tex-refused", at, said)
            return
        self._blank(at, end)
        said = f"{skipped or said}, up to its \\{closer}"
        self.skipped.append(Refusal("tex-refused", at, said, end))
        self.pos = end

    def _verb(self, at: int, end: int) -> None:
        start = end + (self.text[end : end + 1] == "*")
        delimiter = _verb_delimiter(self.text, start)
        close = self.text.find(delimiter, start + 1) if delimiter else -1
        # A line break looked for between the delimiters only: looked for to the line's end,
        # a line of `\verb|x|` was read again for each (CI on #380, macOS and Windows).
        if close < 0 or self.text.find("\n", start + 1, close) >= 0:
            self._refuse("tex-unbalanced", at, "\\verb is not closed on its line")
            return
        self._blank(at, start + 1)
        self._keep_or_blank(start + 1, close)
        self._blank(close, close + 1)
        self.pos = close + 1
        if not self.definitions:
            self.code.append((start, close + 1))
        bound = _MG_USE.search(self.text, start + 1, close)
        if bound is not None:
            self._refuse("tex-refused", bound.start(), _bound_as_typed("\\verb"))

    def _definition(self, name: str, at: int, end: int) -> None:
        # The definer is this one, not the command read last, a `\providecommand` (`_defines`).
        self.command = name
        expanded, self.expanding = self.expanding, False
        start = self._after_space(end)
        if expanded:
            # The `\expandafter`s of `_expands_a_definition`, before the name and after it.
            start = _EXPANDAFTERS.match(self.text, start).end()
            self._blank(end, start)
        if self.text[start : start + 1] != "\\":
            return
        name_end = self._name_end(start)
        defined = self.text[start + 1 : name_end]
        if name == "let":
            self._let(defined, start, name_end)
            return
        self._defines(defined, start)
        self._blank(start, name_end)
        if expanded:
            past = _EXPANDAFTERS.match(self.text, name_end).end()
            if self.text[past : past + 1] == "{":
                self._blank(name_end, past)
                name_end = past
        self.pos = name_end
        word = bool(self.letters.match(defined))
        parameters, delimited = self._parameter_text(name_end, word)
        if parameters < 0:
            said = f"the body of \\{defined} is not found within {_DELIMITED_REACH} characters"
            self._refuse("tex-refused", at, f"\\{name} is not read: {said}")
            return
        written = _parameter_tokens(self.text, name_end, parameters, word)
        if delimited and not _PARAMETER.search(written):
            # A parameter text and no parameter, `\def\eg/{e.g.\@}`: each use prints the body,
            # a known text, and the text after it is passed over (2026-10-23: refused as
            # delimited parameters, though it takes nothing).
            self.literal[defined] = _delimiter(written, self.letters)
            self.defined_literal.append((defined, written))
        elif delimited:
            # Delimited parameters, `\def\x#1.{...}`: the definition is read, and each use
            # where it would print is refused, since what it takes there is not known.
            self.delimited.add(defined)
            if defined not in self.defined_delimited:
                self.defined_delimited.append(defined)
        self._blank(name_end, parameters)
        self.command = name
        self._open("arg", "d", parameters, "}")

    def _parameter_text(self, at: int, word: bool) -> tuple[int, bool]:
        """Where a definition's body opens, past its parameter text, and whether that text
        delimits its parameters, as TeX reads it: the spaces after a control word are skipped,
        a comment runs to its line's end and the next line's spaces with it, `#1` is a
        parameter, and anything else delimits, a control sequence such as `\\{` no brace.
        -1 where a closing brace comes first, or no brace is found within reach (round 1 of
        real templates: `\\def\\x {1}` and `\\def\\x%` with `{1}` on the next line were
        taken for delimited)."""
        stop, delimited = min(self.n, at + _DELIMITED_REACH), False
        if word:
            at = _SKIPPED.match(self.text, at).end()
        while at < stop:
            character = self.text[at]
            if character == "{":
                return at, delimited
            if character == "}":
                return -1, delimited
            if character == "%":
                end = _comment_end(self.text, at)
                self.comments.append((at, end))
                at = _SKIPPED.match(self.text, end).end()
                continue
            parameter = _PARAMETER.match(self.text, at)
            if parameter:
                at = parameter.end()
                continue
            delimited = True
            at = self._name_end(at) if character == "\\" else at + 1
        return -1, delimited

    def _let(self, defined: str, start: int, name_end: int) -> None:
        """`\\let\\a=\\b`: `\\a` comes to mean what `\\b` means. A command the reader reads, let
        to another it reads the same way, is read as before: with the endnotes package,
        `\\let\\footnote=\\endnote` prints each note at the end rather than at the foot, and
        its text is the same prose. Let to anything else, it is defined again."""
        gap = _LET_GAP.match(self.text, name_end).end()
        target_end = self._name_end(gap) if self.text[gap : gap + 1] == "\\" else -1
        target = self.text[gap + 1 : target_end] if target_end > 0 else ""
        # Not a heading, a citation or a cross-reference, of one form each but for what they
        # print, a level, a citation's kind, a name: `\let\chapter\section` (round 1); nor
        # a command the reader reads apart, an input, code or a binding (round 2).
        alias = (defined in COMMANDS and COMMANDS.get(target) == COMMANDS[defined]
                 and not {defined, target} & (set(LEVELS) | set(CITATIONS) | POINTERS
                                              | _READ_APART))  # fmt: skip
        if not alias:
            self._defines(defined, start)
        # A command let to another has no body of its own, read as before or not.
        self.defining, self.restyling = "", None
        stop = target_end if alias else name_end
        self._blank(start, stop)
        self.pos = stop

    def _printed_from_preamble(self, name: str) -> bool:
        """Whether what `name` takes is printed though it stands in the preamble: the title
        and a definition's default anywhere there, an abstract only outside any environment
        or argument (round 3 of #385: one in `filecontents` was read, and nothing prints it)."""
        if name not in ABSTRACT_COMMANDS:
            return name in PRINTED_IN_PREAMBLE
        return name in PRINTED_IN_PREAMBLE and all(f.kind == "group" for f in self.stack)

    def _defines(self, name: str, at: int) -> None:
        self.defining = name
        unloaded = name in PACKAGE_COMMANDS and not self._loaded(PACKAGE_COMMANDS[name])
        if name in FRONT_MATTER_COMMANDS or unloaded:
            # Told of it by the tree or not, the file that defines it says so (round 2). A
            # package's command where no package gives it is the author's too (2026-10-23).
            self.own.add(name)
            if name not in self.defined_own:
                self.defined_own.append(name)
        if name in _REDEFINABLE or unloaded:
            return
        if self.command in PROVIDERS and name in COMMANDS:
            # `\providecommand` of a command that is defined defines nothing (2026-10-23:
            # `\providecommand{\url}` in a reference list BibTeX wrote was refused).
            return
        if name in COMMANDS and not self.body:
            # In the preamble, a file input from it or the author's package the definition is
            # read, and each use refused where it prints, as a use of delimited parameters is
            # (Basile, 2026-11-11: ICLR's `\def\eqref#1{...}` and arxiv.sty's
            # `\renewcommand\section` were refused at the definition, the rest of each file
            # read as typed). The tree tells the other files of it, as of those.
            self.delimited.add(name)
            if name not in self.defined_delimited:
                self.defined_delimited.append(name)
            # Its body may be one of the two forms read as before (`_open`).
            self.restyling = (name, at) if name in LEVELS or name in POINTERS else None
            return
        if name in COMMANDS or name in ("begin", "end", "verb", "def"):
            self._refuse("tex-refused", at, f"\\{name} is defined again, and the reader reads "
                         "it as LaTeX defines it")  # fmt: skip

    def _environment(self, which: str, at: int, end: int) -> None:
        named = _ENVIRONMENT_NAME.match(self.text, end)
        if not named:
            return
        name = named.group(1).strip()
        self._blank(at, named.end())
        self.pos = named.end()
        if self.definitions and not self._picture_in_body(which, name):
            # In a definition's body an environment is text to be expanded at each use, not
            # one that opens here (round 1 of #380: `\newenvironment{tight}{\begin{itemize}}
            # {\end{itemize}}` was refused). Its arguments are still taken: a minipage's width
            # is no number of the paper's (round 2).
            if which == "begin":
                self.command, self.pending = "begin", ENVIRONMENTS.get(name, ())
            return
        if which == "end":
            self._end(name, at)
        elif name in REFUSED_ENVIRONMENTS:
            self._refuse("tex-refused", at, f"{name} is not read: {REFUSED_ENVIRONMENTS[name]}")
        elif name == "document":
            self.body = True
            self.body_start = self.pos
            self._inherit(self.later, self.pos)
            self.later = ()
        elif name in RAW:
            ending = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
            closing = ending.search(self.text, self.pos)
            if closing is None:
                self._refuse("tex-unbalanced", at, f"\\begin{{{name}}} is not closed")
                return
            if name in LISTINGS:
                self._listing(name, closing.start())
            elif name == "comment":
                # The comment package reads to an `\end{comment}` that opens a line, so what is
                # taken out runs from past the `\begin`, its line's rest among it, to that
                # line's break (step 10 and its round 1).
                last = self.text.rfind("\n", self.pos, closing.start())
                if last > self.pos:
                    self.unprinted.append((self.pos, last))
            self._blank(at, closing.end())
            self.pos = closing.end()
            bound = _MG_USE.search(self.text, at, closing.start()) if name in LISTINGS else None
            if bound is not None:
                self._refuse("tex-refused", bound.start(), _bound_as_typed(name))
        else:
            if name in PICTURES and self._role() == PROSE:
                self._picture_printed(self.pos, self._picture_end(name))
            role = self._entered(name, self._role())
            # `Abstract` is a template's command, and no environment printed from the preamble.
            if role == PREAMBLE and name != "Abstract" and self._printed_from_preamble(name):
                role = PROSE
            maths = name in MATHS and role in (PROSE, MATHS_READ)
            # A reference list is a group, which puts back what `\makeatletter` in it changed.
            letters = self.letters if name == REFERENCES else None
            self.stack.append(_Frame("env", MATHS_READ if maths else role, at, name,
                                     table=name in TABLES, letters=letters))  # fmt: skip
            self.environments.append(name)
            if name == "abstract" and role == PROSE:
                self.headings.append(Heading(at, 1, "Abstract"))
            self.command, self.pending = "begin", ENVIRONMENTS.get(name, ())

    def _picture_in_body(self, which: str, name: str) -> bool:
        """Whether a picture opens or closes in a definition's body as it does outside one:
        one whose `\\end` stands in the same body is a picture there, passed over, as
        2311.00579's `\\newcommand{\\redcircleletter}[1]{\\begin{tikzpicture}...}` draws one
        (2026-10-23). One opened in a body and closed in another is text expanded at each
        use, as any environment in a body is, so that nothing is left open."""
        if name not in PICTURES:
            return False
        top = self.stack[-1] if self.stack else None
        if which == "end":
            return top is not None and top.kind == "env" and top.closer == name
        body = next(frame for frame in reversed(self.stack) if frame.definition)
        ends = self._group_end(body.start, comments=True)
        return self._picture_end(name, max(ends, self.pos)) >= 0

    def _picture_end(self, name: str, stop: int | None = None) -> int:
        """Where the picture opened here ends, at its first `\\end` outside a comment before
        `stop`; -1 where there is none, or the file's end where `stop` is None."""
        ending = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
        for closing in ending.finditer(self.text, self.pos, self.n if stop is None else stop):
            # One in a comment closes nothing.
            line = self.text.rfind("\n", 0, closing.start()) + 1
            if not _opens_comment(self.text, max(line, self.pos), closing.start()):
                return closing.start()
        return self.n if stop is None else -1

    def _picture_printed(self, start: int, end: int) -> None:
        """Record what the picture from `start` to `end` prints as text, which is read as
        prose there though the picture is passed over (round 1 of #443)."""
        braces, spans = pictures.printed_in(self.text, start, end)
        self.picture_text.update(braces)
        self.picture_spans.extend(spans)

    def _entered(self, name: str, role: str) -> str:
        """How an environment opened where `role` is read is read: a class's front matter is
        passed over, and an abstract or highlights in it, inside environments and groups only,
        `{\\small ...}` say, are read as what holds the front matter is; not in an argument,
        which is blanked whatever holds it (round 2). A picture is passed over whole. A typed
        table opened inside maths is read as prose (`_sets_text`)."""
        if role == MATHS_READ and _sets_text(name):
            return PROSE
        if name in FRONT_MATTER or name in PICTURES:
            return BLANK
        if name not in READ_IN_FRONT_MATTER:
            return role
        for index in range(len(self.stack) - 1, -1, -1):
            frame = self.stack[index]
            if frame.kind not in ("env", "group"):
                return role
            if frame.kind == "env" and frame.closer in FRONT_MATTER:
                return self.stack[index - 1].role if index else PROSE if self.body else PREAMBLE
        return role

    def _end(self, name: str, at: int) -> None:
        opened = [frame for frame in self.stack if not frame.inherited]
        if name == "document":
            if opened:
                first = opened[0]
                self._refuse("tex-unbalanced", first.start, f"{_opened(first)} is not closed")
                return
            self.body_end = at
            self._blank(at, self.n)
            self.pos = self.n
            return
        top = self.stack[-1] if self.stack else None
        if top is None or top.kind != "env" or top.closer != name:
            self._refuse("tex-unbalanced", at, f"\\end{{{name}}} closes no \\begin{{{name}}}")
            return
        self.stack.pop()
        self.environments.pop()
        self.pending = ()
        if name == "abstract" and top.role == PROSE:
            self.abstracts.append((top.start, self.pos))
        if name in TYPED_TABLES:
            self.tables.append((0 if top.inherited else top.start, at))
        if name in MATHS:
            self.maths.append((0 if top.inherited else top.start, self.pos, True))
        if name in FLOATS:
            self.floats.append((0 if top.inherited else top.start, self.pos))
        if name in FIGURES:
            self.figures.append((0 if top.inherited else top.start, self.pos))
        if name == REFERENCES:
            self.references.append((0 if top.inherited else top.start, self.pos))
            if top.letters is not None:
                self.letters = top.letters

    def _listing(self, name: str, end: int) -> None:
        """Record what a listing holds, and the language an `lstlisting`'s options name."""
        start, language = self.pos, ""
        options = _LISTING_OPTIONS.match(self.text, start) if name == "lstlisting" else None
        if options is not None:
            start = options.end()
            named = _LANGUAGE.search(options.group(1))
            language = named.group(1).lower() if named else ""
        self.listings.append(Listing(start, end, language))


def _bound_as_typed(where: str) -> str:
    return (f"a binding in {where} is printed as typed, not as its value: bind the number "
            "outside it")  # fmt: skip


def _opened(frame: _Frame) -> str:
    if frame.kind == "env":
        return f"\\begin{{{frame.closer}}}"
    if frame.kind == "maths":
        return f"maths opened with {frame.closer}"
    if frame.kind in ("arg", "opt"):
        return f"an argument of \\{frame.command}"
    return "a brace"
