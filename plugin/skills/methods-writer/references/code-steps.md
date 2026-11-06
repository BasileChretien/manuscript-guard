# Code steps: Methods pointing at code an earlier run executed

Part of the methods-writer skill, read when the analysis that produced the results ran before
the emitting script, and that script only renders those results again: models fitted by the
study's own runners on data that cannot be re-run casually, each result file pinned to the
commit or tag of the run that produced it. Also read when `check` reports
`method-code-changed`, `method-code-missing` or `method-code-unchecked`.

A `step()` in such a script marks the script's own code, which fitted nothing, and every
Methods paragraph stays "no code is linked to this text" on the co-authors' checking page.
A code step names the code that did the work, in another file of the project:

```python
em = Emitter(__file__, inputs=declared)
em.code_step("model.stacked", "code/analysis.py", "fit_stacked", at="results-review8-v2")
em.code_step("model.sensitivity", "code/planned_sensitivity.py", "Sensitivity.run",
             at="results-review8-v2")
```

```markdown
The stacked model was fitted by maximum likelihood with a random intercept for each
athlete. {{method.model.stacked}}
```

## What may be named

- **The file** is a Python file of the project, by its path from the project's root. A file
  outside the project, or one that is not Python, is refused. An R analysis marks its code
  with `em$step()` where it runs; there is no R code step.
- **The function** is a function or a class at the top level of the file, or a method through
  its class, as `Model.fit`. Not a line range: lines move with any edit above them, and the
  same range at the commit and in the working tree would name different code with nothing to
  say so. Not a function defined inside another function, which nobody can find by its name.
- **The functions of the same file that it calls** are part of its digest, as a step's are,
  and the checking page shows each beside it. A function from another module, or one called
  as a method (`self.helper()`), is not followed: name it in a code step of its own if the
  Methods describe it.
- **`at`** is the commit or tag the results came from: the one `paper.lock.json`, or the
  results file's own record, pins. Use the tag of the run that produced the result the
  paragraph describes, one code step per run where they differ.

## What is checked, and when

When the script runs where a git repository holds the file, the function's code at `at` must
be the code in the working tree, read as code: a comment, a docstring or a re-wrapped line
since then changes nothing; any other change, to it or to a function it calls, is refused, as
is an `at` that names nothing, a file not in that commit, or a function not defined there. The
step records the commit `at` named.

Where no repository holds the file (`manuscript-guard verify` re-runs the script in a copy of
the project without `.git`), the file is read as it is, the step records that the commit was
not checked, and the run goes on: verify compares the values, which a code step does not
change. A fragment written that way in the project itself is warned of
(`method-code-unchecked`): run the script again in the repository.

`check` then holds the function in the file to the digest the run recorded: edited, it
reports `method-code-changed`; renamed, moved to another file or deleted,
`method-code-missing`. Both fail from `internal-review`, as `method-step-changed` does, and are
not yet due while drafting. The checking page marks its code as not the code that produced the
results.

## When the results are made again

New code, a new run, a new tag: point the code step at the new tag and run the script again.
The step's digest changes, so G9 reports each pair pointing at it as `method-step-changed`.
Read the paragraph against the new code, then `manuscript-guard methods --reconcile
model.stacked`, as for any step.
