# Binding in a LaTeX manuscript

Part of the results-binding skill, read when the manuscript is LaTeX (`main.tex`).

In a LaTeX manuscript, a binding is one command: `\mg{results.key}`, `\mg{lit.key}`,
`\mg{table.key}` inside the float you caption, `\mg[width=\linewidth]{figure.key}` with
`\includegraphics`'s options, and `\mg{method.step}`. Point at a table or a figure with
`\ref`. `manuscript-guard values` writes `mgvalues.sty` from the results, so that the `.tex`
compiles in any editor with the numbers in: run it after the analysis and commit it; `check`
fails a stale one. A number in a siunitx command, `\num{0.42}`, cannot be bound, since
siunitx parses a number and a value prints as text: type the unit beside the binding.
