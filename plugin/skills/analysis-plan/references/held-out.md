# Data held out from the model

A prediction model validated on data held out from its development is validated
independently only where nothing that built or tuned the model read those data first.
Declare the held-out files in one `held_out:` list of a `yaml` block, the controls' block or
another, each with the script that validates on it, the model's files that script reads,
and any script that only describes the data:

```yaml
held_out:
  - input: data/validation.csv
    validated_by: analysis/03_validate.py
    model: models/final.pkl
    read_by: analysis/02_describe.py
```

From then on the emitters keep `design/first_reads.yaml`, each script's first read of each
input. Commit it beside the plan, and never edit it. G1 fails a script that read the
held-out data when the plan did not name it as the validator or a reader, and G12 fails a
model written again after the validation first read the data: both from the analysis stage,
since a leak changes the result. Name a describing script in `read_by` before it first runs.
If the data have been read, the validation is not independent: validate on data nobody has
read, or take the declaration out and say why under the Deviations.

G12 also warns, and fails at submission, where it cannot hold the data to the plan.
`held-out-order-unknown`: no first read of the validation is recorded, or the model is not
among the files it declares, so commit the record, run each script through an emitter, and
declare the model's files as the validation's inputs. Where the plan names no `model` and the
script builds the model itself, the order cannot be told, and G12 says so in a note.
`held-out-unread`: the validation never declared the input. `held-out-declared-late`: the
block came after the first results, and reads before it were not recorded.
`held-out-changed`: the entry is gone since the frozen copy, or names another script, model
or reader. Answer these three under the Deviations, naming the input by its path.
`first-reads-unreadable`: the record does not read as the emitters write it; restore it from
git rather than by hand. Under `vault run` the scripts keep the record in the vault's copy,
and `vault release` brings their first reads into the project's.
