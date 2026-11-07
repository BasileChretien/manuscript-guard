# Names from the code

Part of the manuscript-writing skill, read when `check` reports `code-name-in-prose`.

`code-name-in-prose` is a name from the analysis standing in a sentence, where the reader
has never seen it: a key of the results (`ror.point`, or `results.ror.point`, a binding that
lost its braces), a variable of the data dictionary (`age_group`), or any word written with
underscores (`hr_adj_main`). It warns while the paper is written and fails at submission.

- Say what the thing is. For a variable, the finding gives the dictionary's label: "patients
  with chronic kidney disease", not "patients with `ckd_flag`".
- For a value, bind it: `{{results.ror.point}}` prints the number, and the sentence says
  what the number is.
- A subscript is typed `C~max~`, or written in maths, not `C_max`.
- A function's or a package's name goes in a code span, where only a key or a dictionary
  variable is read.
- A word that is right with its underscores, a taxon as GTDB writes it (`g__Bacteroides`) or
  a variable a data paper documents on purpose, goes under `language: code_names_kept:` in
  `paper.yaml`, one word to an entry, exactly as printed. Ask the author before listing one.

A key or a variable that is a word of the prose, `sex`, `BMI` or `eGFR`, is not read. Nor is
a path, a file's name, an address, a citation key, a binding or maths.

