# LaTeX manuscripts

A manuscript can be written in LaTeX instead of Markdown. The gates read it as they read a
Markdown one: each number is bound, cited or a convention, and the check says where one is
not. A few commands do not read LaTeX yet ("Not yet for LaTeX" below). This page says what
changes. The design, and every known limit, is in [DESIGN.md](../DESIGN.md), under "LaTeX
manuscripts".

## Starting

```bash
manuscript-guard init my-paper --title "Working title" --latex
```

This writes `manuscript/main.tex`, which declares its class and loads `mgvalues`, and
`manuscript/mgvalues.sty` beside it. A manuscript is LaTeX when `manuscript/main.tex`
declares a class and there is no `main.md` beside it, which `check` fails (`two-formats`). It
is one format or the other: `init --latex` makes nothing where
`manuscript/` holds Markdown, and `check` fails a Markdown file in a LaTeX manuscript
(`other-format-file`). A supplement is `manuscript/supplementary/main.tex`, a document of
its own.

A paper already written goes in `manuscript/` as it is, the file that holds `\documentclass`
named `main.tex`, with its class, style and picture files where they were. Its citations
are checked against the library, `literature/references.bib`, which `build` puts beside the
entry file as `references.bib` and compiles with. Bring the paper's `.bib` into it, through
Zotero and `sync-bib` or by copying the file there, and have the document name it,
`\bibliography{references}`. Then run `check`: a refusal names a line the reader cannot
read exactly ("What the reader reads" below).

A `.tex` file that the class or a package you load inputs, such as a list of journals a
journal's class keeps in its own folder, is the class's: `check` does not read it. One that
a class or a package inputs only inside a command's definition, as
`\newcommand{\abstracttext}{\input{abstract}}` does, is printed where the paper uses the
command, and is read. A `.tex` file that nothing inputs is read as main text and warned of
(`tex-not-input`), and so is a picture in the `standalone` class, which the paper places
with `\includestandalone`: its text is read, though not where the paper places it. A part in
the `subfiles` class is read the same way, though `\subfile` itself is refused. One that
is a document of its own, with its own `\begin{document}`, is never read as part of the main
text: `check` fails it (`tex-second-document`). If it is the supplement, make it
`manuscript/supplementary/main.tex`, with its paths to pictures written from that folder;
if it is not, move it out of `manuscript/` or into a folder whose name starts with `_`.

## Bindings

| Markdown | LaTeX |
|---|---|
| `{{results.key}}`, `{{lit.key}}` | `\mg{results.key}`, `\mg{lit.key}` |
| `{{table.key}}` | `\mg{table.key}`, inside the float you caption |
| `{{figure.key}}` | `\mg[width=\linewidth]{figure.key}`, the options `\includegraphics`'s |
| `{{method.step}}` | `\mg{method.step}`, which prints nothing |

Put each table and figure in a float with a `\caption` and a `\label`: LaTeX numbers it by
its caption, and a `\mg{table.key}` outside a float is a table it does not number. Point at
one with `\ref` to its label, or type "Table 2": G2 holds a typed pointer to what the
document's captions number, and the main text's tables and figures to the order ICMJE asks
for, a `\ref` counting as a citation. A range, `Figures~\ref{a}--\ref{b}` with any dash,
`Figures~\ref{a} to~\ref{b}`, or cleveref's `\crefrange{a}{b}`, cites every figure from a
to b, as "Figures 2-4" and "Figures 2 to 4" do; after "Figure", "to" joins nothing, as in
"Figure 2 to 4", and the two cite their ends only. The floats of a `subfigures` or a
`subtables` (the subfloat package's) of its kind are one figure or table, Figure 3a and 3b,
in the group's file or each in a file it inputs, and a `\ref` to the label after `\begin` or
to one of the floats' cites it; a table in a `subfigures` is numbered as any table. A table or figure in the appendix, after `\appendix`
or IEEEtran's `\appendices`, or in an `appendices` or `appendix` environment, is the
supplement's, and so is one under a heading whose title names a supplement ("Supplementary
material", "Appendix A", "Supporting information", "Additional file 1") up to the next
heading of its level or the reference list. It is held neither to that order nor to being
cited, and a pointer typed to it is still held to its place among the document's. A heading
that only uses the word, "Supplementary analyses", holds the main text's tables. A figure's legend is its caption, and G4 holds it to the journal's limit on a
legend's words.

`manuscript-guard values` writes `mgvalues.sty` from the results. The entry file loads it
with `\usepackage{mgvalues}`, so the `.tex` compiles in any editor with the numbers in.
Commit it, and run `values` again after the analysis. `check` compares it with what `values`
would write and fails a stale one, as it fails a stale results file. Do not edit it by hand.

`manuscript-guard explain manuscript/main.tex` shows how each number of a file was
classified. `manuscript-guard bind` lists each unbound number and offers `\mg{...}` where
it reads as one published value, and `bind --apply --only manuscript/main.tex:42` writes
those of one line. A number in a siunitx command is not offered, since siunitx parses a
number and a value prints as text.

## What the reader reads

The reader reads LaTeX under TeX's default category codes, one pass per file, through the
include tree that `\input`, `\include` and the import package's `\import` and `\subimport`
make. What it cannot read exactly, it refuses, naming the line. A conditional in the body,
`\makeatletter` in the body and a citation command the reader does not know, one whose name
holds `cite` such as `\mycitep`, are refused: cite with `\cite` or natbib's, biblatex's,
apacite's or chicago's commands. So
is a command defined with `\def` and delimited parameters, `\def\x#1.{...}`, where the
document prints it, since what it takes there is not known: define it with `\newcommand`.
One whose parameter text holds no parameter, `\def\eg/{e.g.\@}`, takes nothing and is read,
the `/` after each use passed over. A reference list BibTeX wrote, pasted into
`thebibliography`, is read with its header, the conditionals and `\makeatletter` before
its first `\bibitem` too. `\providecommand` of a command already defined defines
nothing. A command a package gives, siunitx's `\unit` say, is yours where you define it
and no file loads that package. A comment between a command and its argument is passed over,
as TeX passes it. An input encoding other than UTF-8 is refused, unless every file is plain
ASCII, which reads the same in all of them. A command the
reader reads may be let to another it reads the same way, as `\let\footnote=\endnote` lets
the endnotes package's note stand for the footnote, but not between headings, citations or
cross-references, which print a level, a kind of citation or a name of their own, nor
where either is an input, an import, `\texttt` or `\mg`; defined again otherwise, it is
refused.
A journal class's front matter in the body, Elsevier's `frontmatter` with its title,
authors, addresses and keywords, or Wiley's issue and dates, is passed over as a Markdown
manuscript's YAML header is; an abstract or Elsevier's highlights in it are read. A command
of that front matter you define yourself, `\keywords` say, is read as your own.
Past a refusal the rest of the file is read as typed, so nothing it did not understand is
hidden. Write a number the reader cannot see as a binding, or move the construct to the
preamble.

## Building and submitting

`build` compiles the PDF with latexmk, in a copy under `build/latex/`, with no shell escape
and no write outside the copy. It needs TeX Live or MiKTeX, with latexmk. The engine is the
one the journal's profile names under `latex: {engine: ...}`, pdfLaTeX otherwise. An error
is named at the manuscript's file and line, and an undefined citation or reference fails at
`--submission`. Under MiKTeX the build turns its installer off, so a package that is not
installed stops the compile and is named, rather than installed then.

BUILD's checks of the Markdown build do not run on a LaTeX manuscript, whose build is
checked by its compile.

`submit` packs the source a journal compiles, in one folder, `latex/` in the pack, where
`check --submission` passes, as it packs a Markdown manuscript:

- each document is one file, `manuscript.tex` and `supplementary.tex`, with its inputs
  written in, its values written in and the text of its comments taken out;
- each picture and file it reads is in the folder under its own name;
- `references.bib` holds the cited entries only, with the `.bbl` beside it.

The folder is compiled alone, in an empty folder, before it is packed, and refused if it
needs anything outside itself. The PDFs are at the pack's root. Where the journal's review
is blind, a name, an address, an ORCID iD or an institution of `authors.yaml` fails the pack
where it stands in the folder's `.tex` or `.sty` files, as LaTeX types it too, or in a PDF or
SVG picture's text; a reference list typed in `thebibliography` is passed over.

## From Markdown to LaTeX

A Markdown manuscript can be sent as LaTeX too:

```bash
manuscript-guard build --latex     # build/latex/submission/ and the PDF
manuscript-guard submit --latex    # the pack, with the source in latex/
```

Pandoc writes it, with the class and the citation package the journal's profile names. The
build then checks what pandoc wrote: the LaTeX reader must not refuse it, and the digits it
prints must be the ones the gates read in the Markdown. A difference stops the build and
names the line of each.

## Reviews and revisions

A review panel (`review --run`) is sent each document as the submission folder writes it,
from its `\begin{document}`, with no comment's text. The preamble stays on the machine, and
each name, address, ORCID iD and institution of `authors.yaml` is sent as `[withheld]` where
the body holds it, a reference list typed in `thebibliography` apart. `respond --open` keeps
that source of the round in `revision/round-N/submitted/latex/`, beside the printed copy G13
reads; where the submission folder's writer refuses the source, it says so and keeps the
printed copy only.

## Not yet for LaTeX

Every check reads a LaTeX manuscript. A check added later that reads Markdown only says so
with `not-read-in-latex`, a note before `submission` and a failure from it, so that a
manuscript only part of the checks read is never passed for submission.

These commands read Markdown only, and refuse a LaTeX manuscript with a sentence: `render`,
`reworded`, `checker`, `import` (the Word round trip), `proof`, `impact`, `audit` of a `.tex`
file, `respond --open --from` a returned Word document, `review --suggestions`, and
`build --annotated` and `--marked-up`, which make Word copies.
