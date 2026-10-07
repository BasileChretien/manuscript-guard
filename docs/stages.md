# Stages: you do not have to satisfy every gate on day one

A checker that demands everything from the first day is a checker that gets switched off on
the second. So each finding declares the **stage at which it starts to matter**:

| Stage | What you are doing |
|---|---|
| `design` | writing the analysis plan |
| `analysis` | writing and running the analysis; the manuscript can wait |
| `drafting` | writing the manuscript against results that exist |
| `internal-review` | draft complete; panels, checklists and the journal's rules apply |
| `submission` | the version you send anywhere |

Set `stage:` in `paper.yaml`, or pass `--stage` for a single run:

```bash
manuscript-guard check --stage analysis
manuscript-guard stages                  # what binds where
```

**Every gate still runs at every stage.** Only the severity changes: a finding that is not
due yet is printed as `INFO` with `[not due until drafting]`, counted, and summarised at the
end. Nothing is skipped, because a check that quietly stopped looking would be worse than no
check. And a finding this policy does not know about fails at every stage — a new gate has
to opt in to being deferred. A gate that *crashes* reports `gate-errored`, which is in no
deferral list and so fails everywhere: a checker that could not check is not a pass. A
manuscript file that cannot be read as UTF-8, one saved in a code page or as UTF-16, is
reported once as `manuscript-unreadable`, at the file and the line, with the gates that read
the manuscript and so did not run. It fails everywhere too, and the other gates still report.

The stage is declared in `paper.yaml`, not detected. Writing `stage: analysis` genuinely
does demote the drafting findings, so it is an opt-out for anyone who wants one — which is
the point, since the tool is for an author who wants it. What it is not is a hiding place:
every deferred finding is printed and counted.

[Back to the README](../README.md)
