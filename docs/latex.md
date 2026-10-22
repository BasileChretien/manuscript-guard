# LaTeX manuscripts

A manuscript can be written in LaTeX instead of Markdown. The gates read it as they read a
Markdown one: each number is bound, cited or a convention, and the check says where one is
not. This page says what changes. The design, and every known limit, is in
[DESIGN.md](../DESIGN.md), under "LaTeX manuscripts".

## Starting

```bash
manuscript-guard init my-paper --title "Working title" --latex
```

This writes `manuscript/main.tex`, which declares its class and loads `mgvalues`, and
`manuscript/mgvalues.sty` beside it. A manuscript is LaTeX when `manuscript/main.tex`
declares a class. It is one format or the other: `init --latex` makes nothing where
`manuscript/` holds Markdown, and `check` fails a Markdown file in a LaTeX manuscript
(`other-format-file`). A supplement is `manuscript/supplementary/main.tex`, a document of
its own.

## Bindings

| Markdown | LaTeX |
|---|---|
| `{{results.key}}`, `{{lit.key}}` | `\mg{results.key}`, `\mg{lit.key}` |
| `{{table.key}}` | `\mg{table.key}`, inside the float you caption |
| `{{figure.key}}` | `\mg[width=\linewidth]{figure.key}`, the options `\includegraphics`'s |
| `{{method.step}}` | `\mg{method.step}`, which prints nothing |

A table or a figure is pointed at with `\ref`, since LaTeX numbers them itself; G2's check of
typed pointers is Markdown's only.

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
include tree that `\input` and `\include` make. What it cannot read exactly, it refuses,
naming the line. A conditional in the body, `\makeatletter` in the body and a macro that
prints a citation are refused. Past a refusal the rest of the file is read as typed, so
nothing it did not understand is hidden. Write a number the reader cannot see as a binding,
or move the construct to the preamble.

## Building and submitting

`build` compiles the PDF with latexmk, in a copy under `build/latex/`, with no shell escape
and no write outside the copy. It needs TeX Live or MiKTeX, with latexmk. The engine is the
one the journal's profile names under `latex: {engine: ...}`, pdfLaTeX otherwise. An error
is named at the manuscript's file and line, and an undefined citation or reference fails at
`--submission`.

`submit` packs the source a journal compiles, in one folder, `latex/` in the pack:

- each document is one file, `manuscript.tex` and `supplementary.tex`, with its inputs
  written in, its values written in and the text of its comments taken out;
- each picture and file it reads is in the folder under its own name;
- `references.bib` holds the cited entries only, with the `.bbl` beside it.

The folder is compiled alone, in an empty folder, before it is packed, and refused if it
needs anything outside itself. The PDFs are at the pack's root. Where the journal's review
is blind, a name, an address, an ORCID iD or an institution of `authors.yaml` in the
folder's files fails the pack, a reference list typed in `thebibliography` apart.

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
the body holds it. `respond --open` keeps that source of the round in
`revision/round-N/submitted/latex/`, beside the printed copy G13 reads.

## Not yet for LaTeX

These read Markdown only, and refuse a LaTeX manuscript with a sentence: `render`,
`reworded`, `checker`, `import` (the Word round trip), `proof`, `impact`, `audit` of a `.tex`
file, `respond --open --from` a returned Word document, `review --suggestions`, and
`build --annotated` and `--marked-up`, which make Word copies.
