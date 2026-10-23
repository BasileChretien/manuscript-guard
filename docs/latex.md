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
for, a `\ref` counting as a citation. A figure's legend is its caption, and G4 holds it to
the journal's limit on a legend's words.

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
`\makeatletter` in the body and a macro that prints a citation are refused. So is a command
defined with `\def` and delimited parameters, `\def\x#1.{...}`, where the document prints
it, since what it takes there is not known: define it with `\newcommand`. A command the
reader reads may be let to another it reads the same way, as `\let\footnote=\endnote` lets
the endnotes package's note stand for the footnote, but not between headings, citations or
cross-references, which print a level, a kind of citation or a name of their own; defined
again otherwise, it is refused.
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
