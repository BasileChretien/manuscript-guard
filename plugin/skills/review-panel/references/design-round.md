# A design round, before the analysis

Part of the review-panel skill, read before the analysis is run, when a design round reads
the plan, and when `check` reports a G12 design-… finding.

The panel above reads the manuscript, once there are results. A design round reads the
plan, `design/plan.md`, and the feasibility results, while the analysis can still change.
Give it one or two reviewers whose remits ask whether the design supports the inference the
plan intends, naming the risks of the study type: confounding, selection, immortal time,
missing data, multiplicity, leakage. Where `paper.yaml` declares one of the table's designs as
`study_type`, each reviewer is also sent what a plan for that design has to settle, with its
sources; declare it before the round. The models in `review.models` can read it, as they
read the manuscript: `manuscript-guard review --design --run --dry-run` shows what would be
sent (the plan and the feasibility results, never the manuscript), and the author runs
`review --design --run` and answers yes. Never add `--yes` for them. Or file each reading by
hand:

```bash
manuscript-guard review --record methodologist --design --round 1 --verdict major-revision \
  --remit "Whether the design supports the inference the plan intends"
manuscript-guard review --seal methodologist --design --round 1   # once the findings are in
```

A remit read by more than one reader, a person and a model or two models, takes a reading
from each: `--reading <reader>` on both commands files it as
`review/design/round-1/methodologist.<reader>.yaml` and lists the reader in the panel. Each
reading's majors are answered on their own.

```bash
manuscript-guard review --record methodologist --design --round 1 --reading "Dr Tanaka" \
  --verdict minor-revision
```

G12 says a major finding not answered (a warning until submission), and a reading of a plan
that has changed since. Answer a finding with what the plan now does, in `resolution:`. An
objection left standing, `overridden:` with a reason, is the statistician's to accept: they
sign it with `manuscript-guard sign`, as the warning's hint says. Never run `sign` for them.
