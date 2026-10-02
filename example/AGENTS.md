# Rules for working in this project

This paper is written with [manuscript-guard](https://github.com/BasileChretien/manuscript-guard),
which makes every number in the manuscript traceable to its source. The rules below hold for
a person and for any agent tool.

1. **Never edit a machine-written file.** `results/` is written by the analysis, `build/` by
   `manuscript-guard build`, `render`, `respond` and `submit`, and a checklist profile,
   `profiles/reporting/<NAME>.yaml`, by `manuscript-guard transcribe` from its recipe. To
   change one, change what it is made from (the analysis, the manuscript, the recipe in
   `profiles/reporting/recipes/`) and run the command again.
2. **Run `manuscript-guard check` before `manuscript-guard build`**, and after any change to
   the analysis or the manuscript. Report what it prints as it is. Before the manuscript
   goes to anyone, run `manuscript-guard check --submission`.
3. **Never decide for yourself that the manuscript is clean.** `check` decides, for the
   stage that `paper.yaml` declares. A failing check is not nearly clean, and nothing is
   changed only to make it pass: not a results file, not the stage, and not a convention in
   `paper.yaml` for a number that should have been bound.
4. **A finding is never typed.** A number from the analysis is a binding,
   `{{results.<key>}}`, and one from the literature is `{{lit.<key>}}`. `check`
   accepts a typed number only where it is a convention of writing (a 95% confidence
   interval) or a pointer (Table 1). `manuscript-guard bind` lists the numbers bound to
   nothing.
5. Only a person signs `literature/attested.yaml`.

The step-by-step guidance is in the skills that come with manuscript-guard, starting with
`project-setup`. If your agent tool shows none of them, say so to the author: the README at
the address above says which agent tools they can be installed in, and how.
