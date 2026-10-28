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

_ITEM = re.compile(r"\*|\[[pbo]\]|\(b\)|<p>|\{[pbrdc]\}")


def _specs(table: dict[str, str]) -> dict[str, tuple[str, ...]]:
    return {name: tuple(_ITEM.findall(spec)) for name, spec in table.items()}


_CITE = "*<p>[p][p]{b}"
#: natbib's and biblatex's citation commands, and whether each prints the authors' names in
#: the sentence (narrative), as `@key` does in Markdown; `\\cite` does not. Each has a
#: capitalised form.
_CITATIONS = {
    "cite": False, "nocite": False, "citep": False, "citet": True, "citealt": True,
    "citealp": False, "citeauthor": True, "citeyear": False, "citeyearpar": False,
    "citenum": False, "parencite": False, "textcite": True, "autocite": False,
    "footcite": False, "footcitetext": False, "smartcite": False, "supercite": False,
    "fullcite": False, "citetitle": False, "citetalias": True, "citepalias": False,
    "citefullauthor": True, "footfullcite": False, "citeurl": False, "citedate": False,
    "citeurldate": False, "notecite": False, "pnotecite": False, "fnotecite": False,
}  # fmt: skip
#: apacite's and chicago's, read from their `.sty` (apacite 6.03, chicago of 1992 in MiKTeX
#: 24.4): apacite's take a prenote in angle brackets, `\\citeA<see>[p.~3]{key}`
#: (2026-10-23, round 1 of #442: they were refused, then passed unread).
_APACITE_CITATIONS = {
    "citeA": True, "citeNP": False, "citeauthorNP": True, "citeyearNP": False,
    "shortcite": False, "shortciteA": True, "shortciteNP": False, "shortciteauthor": True,
    "shortciteauthorNP": True, "fullciteA": True, "fullciteNP": False, "fullciteauthor": True,
    "fullciteauthorNP": True, "nocitemeta": False, "citeN": True, "citeANP": True,
    "shortciteN": True, "shortciteANP": True,
}  # fmt: skip
_MULTI_CITATIONS = {
    "cites": False, "parencites": False, "textcites": True, "autocites": False,
    "footcites": False, "footcitetexts": False, "smartcites": False, "supercites": False,
}  # fmt: skip
#: Every citation command the reader reads, the multi-citation forms among them.
_TABLES = (_CITATIONS, _APACITE_CITATIONS, _MULTI_CITATIONS)
CITATIONS = {
    **{name: narrative for table in _TABLES for name, narrative in table.items()},
    **{name[0].upper() + name[1:]: narrative for table in _TABLES
       for name, narrative in table.items() if not name.startswith("nocite")},
}  # fmt: skip
_CITATION_NAMES = [name for name in CITATIONS
                   if name[0].lower() + name[1:] not in _MULTI_CITATIONS]  # fmt: skip
_MULTI_CITATION_NAMES = [name for name in CITATIONS
                         if name[0].lower() + name[1:] in _MULTI_CITATIONS]  # fmt: skip
_REF = "{b}"
_SECTION = "*[p]{p}"
_DEFINE = "*{c}[b][p]{d}"

#: The commands of the front matter of the major journals' classes, which the title page
#: prints and Markdown keeps in its YAML header: addresses, affiliations, notes on the
#: authors, keywords, and Wiley's, Oxford's and Springer's issue, dates and running heads,
#: each argument passed over, as that header is (Basile, 2026-10-23).
_FRONT_MATTER_SPECS = {
    **dict.fromkeys(("altaffiliation", "cortext", "fntext", "tnotetext", "ead", "email",
                     "homepage", "corresp"), "[b]{b}"),
    # Elsevier's CAS classes take an option list after an address, `\\affiliation[1]{...}
    # [...]`, `O{} m O{}` in their `cas-common.sty`; and give marks that number a note on the
    # title page, `\\cormark[1]`, `\\fnmark[2]`, `\\tnotemark[1]`, `O{}`, the CRediT roles
    # `\\credit{...}` prints in a statement of its own, a note with no mark and the running
    # heads, `m` (2026-10-23, from 2604.24157). elsarticle's `\\fnref`, `\\corref` and
    # `\\tnoteref` name a note's label inside `\\author` and `\\title`, as its template writes
    # them. acmart's `\\ccsdesc[300]{...}` is a CCS concept the title page prints, with its
    # weight, `\\newcommand\\ccsdesc[2][100]` in acmart.cls (from 2311.00579).
    **dict.fromkeys(("address", "affiliation"), "[b]{b}[b]"),
    **dict.fromkeys(("cormark", "fnmark", "tnotemark"), "[b]"),
    **dict.fromkeys(("credit", "nonumnote", "shorttitle", "shortauthors", "fnref", "corref",
                     "tnoteref"), "{b}"),
    "ccsdesc": "[b]{b}",
    "affil": "*[b]{b}",
    **dict.fromkeys(("keywords", "journal", "institute", "titlerunning", "authorrunning",
                     "orcidID", "inst", "equalcont", "corres", "pacs", "DOIsuffix", "Volume",
                     "Issue", "Year", "Receiveddate", "Reviseddate", "Accepteddate",
                     "Dateposted", "dedicatory", "pretitle", "DOI", "journaltitle",
                     "copyrightyear", "pubyear", "access", "appnotes", "firstpage",
                     "authormark", "editor"), "{b}"),
    "pagespan": "{b}{b}",
}  # fmt: skip
#: cleveref's cross-references to a range, which print the numbers of two labels with a word
#: between, "Figures 2 to 4" (corpus round, 2026-10-23).
RANGES = frozenset({"crefrange", "Crefrange", "cpagerefrange", "Cpagerefrange"})
#: Commands and their arguments.
COMMANDS = _specs(
    {
        # Text that prints, read as prose.
        **dict.fromkeys(
            (
                "emph", "textbf", "textit", "textsc", "textsf", "texttt", "textrm", "textup",
                "textmd", "textsl", "textnormal", "underline", "mbox", "fbox", "textsuperscript",
                "textsubscript", "enquote", "text", "intertext", "citetext",
            ),
            "{p}",
        ),
        **dict.fromkeys(
            ("part", "chapter", "section", "subsection", "subsubsection", "paragraph",
             "subparagraph"),
            _SECTION,
        ),
        # The title is read. Its option is the short title of a running head, which
        # Springer's `sn-jnl` and amsart print over the pages, or an option list, Elsevier's
        # CAS `\\title[mode = title]{...}`: passed over as `\\titlerunning` is (2026-10-23,
        # from 2112.07039, which read the title twice, and 2604.24157).
        "title": "[b]{p}",
        "thanks": "{p}",
        # A class's `\\abstract{...}`: a section titled Abstract, as the environment is.
        "abstract": "{p}",
        "caption": "[p]{p}",
        "footnote": "[b]{p}",
        "footnotetext": "[b]{p}",
        # The endnotes package's, which prints the note at the end of the document.
        "endnote": "[b]{p}",
        "endnotetext": "[b]{p}",
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
             "setcitestyle", "citereset", "defcitealias",
             "bibliographystyle", "graphicspath", "linespread", "hypersetup", "geometry",
             "newgeometry", "pagestyle", "thispagestyle", "pagenumbering", "nocite",
             "nocitemeta", "cline",
             "newlength", "date"),
            _REF,
        ),
        # cleveref's ranges, `\crefrange{a}{b}`: the two labels the range runs between.
        **dict.fromkeys(RANGES, "{b}{b}"),
        # The import package's: a folder and a file, followed as an input is (`IMPORTS`).
        **dict.fromkeys(("import", "subimport"), "{b}{b}"),
        # A part the paper places, followed as an input is, its document body read (`PLACED`).
        "subfile": "{b}",
        "includestandalone": "[b]{b}",
        "url": "{r}",
        # Springer's `\\author*[1]{...}`, its star the corresponding author's, and Elsevier's
        # CAS `\\author[1]{...}[orcid=...]`, with an option list after the name (2026-10-23).
        "author": "*[b]{b}[b]",
        # TikZ's and pgfplots' settings, which style a picture and print nothing where they
        # stand (2026-10-23, from 2401.04687). The old `\\tikzstyle{name} = [...]` has an
        # equals sign between its name and its options, and `mask.py` takes the name first.
        **dict.fromkeys(("tikzset", "pgfplotsset", "usetikzlibrary", "usepgfplotslibrary"),
                        "{b}"),
        "tikzstyle": "[b]",
        **_FRONT_MATTER_SPECS,
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
        # What pandoc writes round a heading and a table, measured against pandoc 3.9 (step
        # 11): a heading's text for the PDF's bookmarks and its entry in the contents, which
        # the page does not print where the command stands; a link's anchor, whose content
        # prints; and a column's width.
        "texorpdfstring": "{p}{b}",
        "addcontentsline": "{b}{b}{b}",
        "hypertarget": "{b}{p}",
        "real": "{b}",
        "color": "[b]{b}",
        "cmidrule": "[b](b){b}",
        # A table's rules and colours, booktabs' and xcolor's `table` option's: a rule's
        # width, a colour's model and its name or values, which print nothing in the cell
        # (round 1 of #463: `\\cellcolor[rgb]{0.9,0.9,0.9}4` was read "0.9,0.9,0.94").
        # A row's and a column's colour take colortbl's overhangs after it, `[2pt][2pt]`
        # (round 2 of #463). Each is a package's, an author's own where none gives it, and
        # defined again where one does (`TABLE_COMMANDS`).
        **dict.fromkeys(("toprule", "midrule", "bottomrule"), "[b]"),
        **dict.fromkeys(("rowcolor", "columncolor"), "[b]{b}[b][b]"),
        **dict.fromkeys(("cellcolor", "arrayrulecolor"), "[b]{b}"),
        "rowcolors": "*[b]{b}{b}{b}",
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
        # Citations: the notes are read, the keys are not (`CITATIONS`).
        **dict.fromkeys((name for name in _CITATION_NAMES if not name.startswith("nocite")),
                        _CITE),
        # pandoc's, under citeproc, measured against pandoc 3.9: `\\citeproc{ref-key}{Smith
        # 2020, 3}` is a citation as citeproc printed it, its key the typed list's and not
        # the library's, and `\\citeproctext` the empty label of each `\\bibitem`. pandoc's
        # template defines both (`CITEPROC`).
        "citeproc": "{b}{b}",
        "citeproctext": "",
        # The multi-citation forms: a global prenote and postnote in parentheses, blanked,
        # then groups of notes and keys, as many as follow.
        **dict.fromkeys(_MULTI_CITATION_NAMES, "(b)(b)" + "[p][p]{b}" * 16),
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

#: The front matter of the major journals' classes, which the title page prints: Elsevier's
#: `frontmatter` and BMC's `fmbox`, whose content is passed over but for an abstract, as
#: Markdown passes over its YAML header and reads the abstract; and a list of keywords
#: (Basile, 2026-10-23).
FRONT_MATTER = frozenset({"frontmatter", "fmbox", "keyword", "keywords", "IEEEkeywords"})
#: What the front matter holds that the paper prints as its text, read as it is outside it:
#: the abstract, and Elsevier's highlights, the paper's claims with its numbers, and graphical
#: abstract (round 1 of real templates, part 2).
READ_IN_FRONT_MATTER = frozenset({"abstract", "highlights", "graphicalabstract"})
#: The commands of that front matter, each argument passed over. An author may define one
#: again, as an article's preamble often defines `\\keywords`, and it is then the author's
#: command, read as an unknown command is, as it was before the table held it.
FRONT_MATTER_COMMANDS = frozenset(_FRONT_MATTER_SPECS)
#: The import package's commands the include tree follows, each a folder and a file:
#: `\\import`'s folder is the manuscript's, and `\\subimport`'s is under the folder the
#: file it stands in was imported from (`structure.py`).
IMPORTS = frozenset({"import", "subimport"})
#: The commands that place a file's document body where they stand, followed as an input is:
#: the subfiles package's `\\subfile{path}` and the standalone package's
#: `\\includestandalone[options]{path}`. A file in the `subfiles` or the `standalone` class is
#: read past its preamble, under the heading and inside the environments the command stands
#: in (`structure.py`).
PLACED = frozenset({"subfile", "includestandalone"})
#: Commands that print a space, written as one.
SPACES = frozenset({"quad", "qquad", "enspace", "thinspace", "space", "enskip", "nobreakspace"})
#: The commands that print one character, which the mask writes where the command stands: a
#: quotation with an ellipsis or a dash is then the words its source holds (round 1 of G7 in
#: step 8).
SYMBOLS = {"ldots": "\u2026", "dots": "\u2026", "textellipsis": "\u2026",
           "textendash": "\u2013", "textemdash": "\u2014"}  # fmt: skip

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
        "tikzpicture": "[b]",
    }
)  # fmt: skip

#: A picture drawn in the source, passed over whole, its options, its code and its nodes'
#: text, as `\\includegraphics` passes over a picture's file (2026-10-23: a TikZ picture's
#: sizes and shifts were numbers of the text).
PICTURES = frozenset({"tikzpicture"})

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
#: code check as a fenced block is, and a comment: the comment package's, and acmart's
#: `CCSXML`, the XML of the CCS concepts, which the class excludes as one (2026-10-23, from
#: 2311.00579, whose concepts' ids were numbers of the text).
COMMENTS = frozenset({"comment", "CCSXML"})
RAW = frozenset({"verbatim", "verbatim*", "Verbatim", "lstlisting"}) | COMMENTS
#: The listings among them, which print what they hold as typed.
LISTINGS = RAW - COMMENTS

#: The cross-references, which print a number only the compiled document knows (step 8).
POINTERS = frozenset({"ref", "eqref", "pageref", "autoref", "nameref", "cref", "Cref", "vref",
                      "cpageref", "labelcref", *RANGES})  # fmt: skip
#: Tables an author types: a number in one is `hand-authored-table`, as one in a Markdown
#: table's row is. Maths' alignments separate cells too, and are no tables.
TYPED_TABLES = frozenset({"tabular", "tabular*", "tabularx", "tabulary", "longtable"})

#: Floats: a journal does not count their words against the text's limit, as it counts a
#: table or a figure as a display item.
FLOATS = frozenset(
    {"figure", "figure*", "table", "table*", "wrapfigure", "wraptable", "sidewaysfigure",
     "sidewaystable"}
)  # fmt: skip
#: The floats that hold a figure, whose caption G14 does not read, as it does not read an
#: image's caption in Markdown.
FIGURES = frozenset({"figure", "figure*", "wrapfigure", "sidewaysfigure"})

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

#: The packages that give each of the commands above that LaTeX itself does not: one of
#: them is the reader's only where a package that gives it is loaded, and an author's
#: definition of it elsewhere makes it the author's command, read as an unknown one is
#: (2026-10-23: an article's own `\\unit`, with no siunitx, was refused as defined again).
PACKAGE_COMMANDS = {
    **dict.fromkeys(SIUNITX, ("siunitx",)),
    "unit": ("siunitx", "units"),
    "qty": ("siunitx", "physics"),
    **dict.fromkeys(("toprule", "midrule", "bottomrule"), ("booktabs",)),
    **dict.fromkeys(("rowcolor", "cellcolor", "columncolor", "arrayrulecolor"),
                    ("colortbl", "xcolor")),
    "rowcolors": ("xcolor",),
}  # fmt: skip
#: A table's rules and colours, which the reader blanks the arguments of but an author may
#: define again where the package is loaded too, `\\renewcommand{\\toprule}{\\hline}`: read
#: then as before, never refused as defined again (round 2 of #463: an author's own
#: `\\let\\toprule\\hline` was refused, and the rest of the file read as typed).
TABLE_COMMANDS = frozenset({"toprule", "midrule", "bottomrule", "rowcolor", "cellcolor",
                            "columncolor", "arrayrulecolor", "rowcolors"})  # fmt: skip
#: The definers that define nothing where the command is defined already.
PROVIDERS = frozenset({"providecommand", "ProvideDocumentCommand"})
#: pandoc's commands under citeproc, which its template defines.
CITEPROC = frozenset({"citeproc", "citeproctext"})
#: The commands that change how characters are read or what a name means, accepted in a
#: reference list typed in `thebibliography`, whose header BibTeX's styles write with them:
#: `\\expandafter\\ifx\\csname urlstyle\\endcsname` (natbib's), REVTeX's `\\makeatletter`. The
#: others of `REFUSED`'s first row only in a definition's body there, where they print
#: nothing (2026-10-23).
REFERENCE_MACHINERY = frozenset({"expandafter", "csname"})

#: Why a command is refused, by the command. Past a refusal the rest of the file is read as
#: prose, so that nothing the reader did not understand is hidden.
_CATEGORY = "it changes how characters are read"
#: The commands refused as `_CATEGORY` says.
CATEGORY = frozenset({"catcode", "csname", "expandafter", "uccode", "lccode", "mathcode",
                      "scantokens"})  # fmt: skip
_FILE = "it prints a file no gate reads; bind a table with \\mg{table.key} instead"
REFUSED = {
    **dict.fromkeys(sorted(CATEGORY), _CATEGORY),
    **dict.fromkeys(("lstinputlisting", "verbatiminput", "VerbatimInput", "csvautotabular",
                     "csvautobooktabular", "csvreader", "pgfplotstabletypeset", "DTLloaddb",
                     "DTLdisplaydb", "DTLdisplaylongdb", "includepdf"), _FILE),
    **dict.fromkeys(("InputIfFileExists", "inputfrom", "subinputfrom", "includefrom",
                     "subincludefrom"),
                    "its file is not followed; \\input it by a path written out in full"),
    "inputminted": "it needs shell escape, which the build does not allow",
}  # fmt: skip

#: Environments refused, and why.
REFUSED_ENVIRONMENTS = {"minted": "it needs shell escape, which the build does not allow"}
