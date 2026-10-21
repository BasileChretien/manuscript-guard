"""What each LaTeX command the reader knows takes, and what each of its arguments is.

An argument is written as its delimiters around one letter:

- `*` a star, taken where it follows;
- `[p]` an optional argument read as prose, `[b]` one blanked;
- `[o]` one that is an option list, `key=value`, and blanked, or that holds no `=` and is
  read as prose: a name two packages give, siunitx's `\\qty[round-precision=1]` and the
  units package's `\\unit[250]{mg}` (round 2 of #400);
- `(b)` an optional argument in parentheses, blanked (booktabs' `\\cmidrule(lr)`);
- `{p}` a mandatory argument read as prose, `{b}` one blanked;
- `{r}` one blanked and read raw, with `%` and `#` as characters (a URL);
- `{d}` a definition's body: prose, with its parameters `#1` to `#9` blanked;
- `{c}` the command a definition defines, braced or not.

A command not here has its name blanked and its arguments read as prose: a command the table
lacks shows up as an unclassified number, never as a hidden claim.
"""

from __future__ import annotations

import re

_ITEM = re.compile(r"\*|\[[pbo]\]|\(b\)|\{[pbrdc]\}")


def _specs(table: dict[str, str]) -> dict[str, tuple[str, ...]]:
    return {name: tuple(_ITEM.findall(spec)) for name, spec in table.items()}


_CITE = "*[p][p]{b}"
_REF = "{b}"
_SECTION = "*[p]{p}"
_DEFINE = "*{c}[b][p]{d}"

#: Commands and their arguments.
COMMANDS = _specs(
    {
        # Text that prints, read as prose.
        **dict.fromkeys(
            (
                "emph", "textbf", "textit", "textsc", "textsf", "texttt", "textrm", "textup",
                "textmd", "textsl", "textnormal", "underline", "mbox", "fbox", "textsuperscript",
                "textsubscript", "enquote", "text", "intertext",
            ),
            "{p}",
        ),
        **dict.fromkeys(
            ("part", "chapter", "section", "subsection", "subsubsection", "paragraph",
             "subparagraph"),
            _SECTION,
        ),
        "title": "[p]{p}",
        "thanks": "{p}",
        # A class's `\\abstract{...}`: a section titled Abstract, as the environment is.
        "abstract": "{p}",
        "caption": "[p]{p}",
        "footnote": "[b]{p}",
        "footnotetext": "[b]{p}",
        "item": "[p]",
        "bibitem": "[p]{b}",
        "makebox": "[b][b]{p}",
        "framebox": "[b][b]{p}",
        "multicolumn": "{b}{b}{p}",
        "multirow": "[b]{b}[b]{b}[b]{p}",
        "resizebox": "*{b}{b}{p}",
        "scalebox": "{b}[b]{p}",
        "raisebox": "{b}[b][b]{p}",
        "textcolor": "[b]{b}{p}",
        "colorbox": "[b]{b}{p}",
        "hyperref": "[b]{p}",
        "href": "{r}{p}",
        # Hooks whose argument LaTeX prints, read as the body is, in the preamble too.
        "AtBeginDocument": "{d}",
        "AtEndDocument": "{d}",
        "AfterEndPreamble": "{d}",
        "AddToHook": "{b}[b]{d}",
        # Machinery, blanked.
        **dict.fromkeys(
            ("label", "ref", "eqref", "pageref", "autoref", "nameref", "cref", "Cref", "vref",
             "cpageref", "labelcref", "input", "include", "includeonly", "bibliography",
             "bibliographystyle", "graphicspath", "linespread", "hypersetup", "geometry",
             "newgeometry", "pagestyle", "thispagestyle", "pagenumbering", "nocite", "cline",
             "newlength", "date"),
            _REF,
        ),
        "url": "{r}",
        "author": "[b]{b}",
        "includegraphics": "*[b][b]{b}",
        "addbibresource": "[b]{b}",
        "usepackage": "[b]{b}[b]",
        "RequirePackage": "[b]{b}[b]",
        "documentclass": "[b]{b}[b]",
        **dict.fromkeys(("setlength", "addtolength", "setcounter", "addtocounter",
                         "numberwithin"), "{b}{b}"),
        **dict.fromkeys(("vspace", "hspace"), "*{b}"),
        # Layout that takes a size: its numbers are no claims (round 1 of #400, now that G2
        # reads them).
        "fontsize": "{b}{b}",
        "addlinespace": "[b]",
        **dict.fromkeys(("setstretch", "enlargethispage"), "*{b}"),
        "captionsetup": "[b]{b}",
        "color": "[b]{b}",
        "cmidrule": "[b](b){b}",
        "rule": "[b]{b}{b}",
        "\\": "*[b]",
        # A binding: the value it prints is the results', not the author's.
        "mg": "[b]{b}",
        # siunitx: its number read as prose, its options and units blanked. A binding in one
        # is refused, since siunitx parses what it holds, and `\\mg` in one is the milligram
        # siunitx defines there (`mask.py`). `\\qty` and `\\unit` are other packages' too,
        # physics' brackets and units' `\\unit[250]{mg}`, so what their brackets hold is read
        # where it is no option list (round 1 of #400: it was blanked, and 250 passed; round
        # 2: read whole, siunitx's `round-precision=1` failed G2).
        **dict.fromkeys(("num", "numlist", "numproduct", "ang", "tablenum", "complexnum"),
                        "[b]{p}"),
        "numrange": "[b]{p}{p}",
        "SI": "[b]{p}[b]{b}",
        "qty": "[o]{p}[b]{b}",
        **dict.fromkeys(("qtylist", "SIlist", "qtyproduct", "complexqty"), "[b]{p}{b}"),
        **dict.fromkeys(("qtyrange", "SIrange"), "[b]{p}{p}{b}"),
        "si": "[b]{b}",
        "unit": "[o]{b}",
        # Citations: the notes are read, the keys are not.
        **dict.fromkeys(
            ("cite", "citep", "citet", "citealt", "citealp", "citeauthor", "citeyear",
             "citeyearpar", "citenum", "Citep", "Citet", "Citealt", "Citealp", "Citeauthor",
             "parencite", "Parencite", "textcite", "Textcite", "autocite", "Autocite",
             "footcite", "footcitetext", "smartcite", "Smartcite", "supercite", "fullcite",
             "citetitle"),
            _CITE,
        ),
        # Definitions: what they define is checked, their bodies read where they stand.
        **dict.fromkeys(("newcommand", "renewcommand", "providecommand",
                         "DeclareRobustCommand"), _DEFINE),
        **dict.fromkeys(("newenvironment", "renewenvironment"), "*{b}[b][p]{d}{d}"),
        "DeclareMathOperator": "*{c}{d}",
        # xparse's: the name, the argument specification, read as its defaults print
        # (`O{95}`, round 4 of #380), and the body.
        **dict.fromkeys(("NewDocumentCommand", "RenewDocumentCommand", "ProvideDocumentCommand",
                         "DeclareDocumentCommand"), "{c}{p}{d}"),
        # xparse's processors in a specification, whose arguments print nothing.
        "SplitArgument": "{b}{b}",
        "SplitList": "{b}",
    }
)  # fmt: skip

#: Commands that print a space, written as one.
SPACES = frozenset({"quad", "qquad", "enspace", "thinspace", "space", "enskip", "nobreakspace"})

#: Environments and the arguments `\\begin` takes for them.
ENVIRONMENTS = _specs(
    {
        **dict.fromkeys(("figure", "figure*", "table", "table*", "tablenotes", "enumerate"),
                        "[b]"),
        "minipage": "[b][b][b]{b}",
        **dict.fromkeys(("multicols", "multicols*"), "{b}[p][b]"),
        "wrapfigure": "[b]{b}[b]{b}",
        "subfigure": "[b]{b}",
        "thebibliography": "{b}",
        "tabular": "[b]{b}",
        "tabular*": "{b}[b]{b}",
        "tabularx": "{b}{b}",
        "tabulary": "{b}{b}",
        "longtable": "[b]{b}",
        "array": "[b]{b}",
        "alignat": "{b}",
        "alignat*": "{b}",
    }
)  # fmt: skip

#: Environments whose `&` and `\\\\` separate cells: each is a space.
TABLES = frozenset(
    {"tabular", "tabular*", "tabularx", "tabulary", "longtable", "array", "align", "align*",
     "alignat", "alignat*", "flalign", "flalign*", "eqnarray", "eqnarray*", "matrix", "pmatrix",
     "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "cases", "split", "aligned",
     "gathered", "alignedat"}
)  # fmt: skip

#: Environments that are maths.
MATHS = frozenset(
    {"equation", "equation*", "align", "align*", "gather", "gather*", "multline", "multline*",
     "eqnarray", "eqnarray*", "displaymath", "math", "flalign", "flalign*", "alignat",
     "alignat*"}
)  # fmt: skip

#: amsmath's environments, whose `\\\\` takes a length only where it follows at once: its
#: cases and matrices too, which set amsmath's `\\\\` before their array (round 4 of #380).
AMSMATH = frozenset(
    {"align", "align*", "gather", "gather*", "multline", "multline*", "flalign", "flalign*",
     "alignat", "alignat*", "split", "aligned", "gathered", "alignedat", "cases", "matrix",
     "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix"}
)  # fmt: skip

#: Environments read to their `\\end` as characters and blanked whole: a listing, read by G2's
#: code check as a fenced block is, and a comment.
RAW = frozenset({"verbatim", "verbatim*", "Verbatim", "lstlisting", "comment"})
#: The listings among them, which print what they hold as typed.
LISTINGS = RAW - {"comment"}

#: Tables an author types: a number in one is `hand-authored-table`, as one in a Markdown
#: table's row is. Maths' alignments separate cells too, and are no tables.
TYPED_TABLES = frozenset({"tabular", "tabular*", "tabularx", "tabulary", "longtable"})

#: LaTeX's own parameters an author sets by defining them again, whose body is a size and
#: prints nothing: `\\renewcommand{\\arraystretch}{1.5}` (round 1 of #400: its 1.5 failed G2).
PARAMETERS = frozenset(
    {"arraystretch", "baselinestretch", "topfraction", "bottomfraction", "textfraction",
     "floatpagefraction", "dbltopfraction", "dblfloatpagefraction"}
)  # fmt: skip

#: siunitx's commands, in which `\\mg` is its milligram and a binding is refused.
SIUNITX = frozenset(
    {"num", "numlist", "numproduct", "ang", "tablenum", "complexnum", "numrange", "qty", "SI",
     "qtylist", "SIlist", "qtyproduct", "complexqty", "qtyrange", "SIrange", "unit", "si"}
)  # fmt: skip

#: Why a command is refused, by the command. Past a refusal the rest of the file is read as
#: prose, so that nothing the reader did not understand is hidden.
_CATEGORY = "it changes how characters are read"
_FILE = "it prints a file no gate reads; bind a table with \\mg{table.key} instead"
REFUSED = {
    **dict.fromkeys(("catcode", "csname", "expandafter", "uccode", "lccode", "mathcode",
                     "scantokens"), _CATEGORY),
    **dict.fromkeys(("lstinputlisting", "verbatiminput", "VerbatimInput", "csvautotabular",
                     "csvautobooktabular", "csvreader", "pgfplotstabletypeset", "DTLloaddb",
                     "DTLdisplaydb", "DTLdisplaylongdb", "includepdf"), _FILE),
    **dict.fromkeys(("import", "subimport", "subfile", "InputIfFileExists"),
                    "its file is not followed; \\input it by a path written out in full"),
    "inputminted": "it needs shell escape, which the build does not allow",
}  # fmt: skip

#: Environments refused, and why.
REFUSED_ENVIRONMENTS = {"minted": "it needs shell escape, which the build does not allow"}
