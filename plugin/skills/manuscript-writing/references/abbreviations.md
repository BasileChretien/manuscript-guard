# What G14 lets stand, and where else it finds a definition

Part of the manuscript-writing skill, read when an abbreviation finding is about something
that is not a definition in a sentence, or when `check` reports `no-headings`.

## Not reported

A chemical formula with a count in it (`CO2`, `CO~2~`, `NaHCO3`), the unit symbols shipped
(`MHz`, `GPa`) and a registration number (`NCT01234567`) are not reported and need no entry.
A formula with no count (`HCl`, `NaOH`) is reported like any abbreviation.

Nor are SD, ANOVA, RMSE and RMSD, which style manuals let stand, unless the journal's
profile asks for them (`abbreviations: define_statistics: true`, or by name under
`define:`). CI, OR, HR and IQR are reported: list them in `paper.yaml` only where the
journal lets them stand.

## A glossary and a caption

A list of abbreviations under a heading named Abbreviations, Glossary or Acronyms defines
each entry where it stands: "ROR: reporting odds ratio", one to a line, or a two-column
table. Expanding the abbreviation again at its first use in the text, as journals ask, is
not a second definition, and a table's caption or a figure's legend may restate one too.
An entry nothing else uses is reported as unused.

## No headings

A manuscript with no headings at all, its sections typed as bold lines, is read as one
text and reports no `abbreviation-redefined`. G14 says so in a note, `no-headings`, at the
drafting stage only, so its absence at a later stage does not mean the paper has headings.
Give the sections Markdown headings (`# Abstract`) to have the abstract read apart again.
