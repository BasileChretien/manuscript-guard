# Rules for working in this project

This paper is written with [manuscript-guard](https://github.com/BasileChretien/manuscript-guard),
which makes every number in the manuscript traceable to its source. The rules below hold for
a person and for any agent tool.

1. **Never edit a machine-written file.** `results/` is written by the analysis, `build/` by
   `manuscript-guard build`, `respond` and `submit`, and `profiles/reporting/*.yaml` by
   `manuscript-guard transcribe`. To change one, change what writes it and run that again.
2. **Run `manuscript-guard check` before `manuscript-guard build`**, and after any change to
   the analysis or the manuscript. Report the codes it prints as they are.
3. **Never decide for yourself that the manuscript is clean.** `check` decides. A failing
   check is not nearly clean, and nothing is changed only to make it pass: not a results
   file, and not a convention in `paper.yaml` for a number that should have been bound.
4. A number in `manuscript/` is a binding, `{{results.<key>}}` or `{{lit.<key>}}`,
   never a typed literal. `manuscript-guard bind` lists the ones bound to nothing.
5. Only a person signs `literature/attested.yaml`.

The step-by-step guidance is in the skills that come with manuscript-guard, starting with
`project-setup`. If your agent tool shows none of them, say so to the author: the README at
the address above says how to install them.
