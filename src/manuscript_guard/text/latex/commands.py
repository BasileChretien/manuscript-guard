"""What each LaTeX command the reader knows takes, and what each of its arguments is.

An argument is written as its delimiters around one letter:

- `*` a star, taken where it follows;
- `[p]` an optional argument read as prose, `[b]` one blanked;
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

_ITEM = re.compile(r"\*|\[[pb]\]|\(b\)|\{[pbrdc]\}")


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
        "captionsetup": "[b]{b}",
        "color": "[b]{b}",
        "cmidrule": "[b](b){b}",
        "rule": "[b]{b}{b}",
        "\\": "*[b]",
        # A binding: the value it prints is the results', not the author's.
        "mg": "[b]{b}",
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
