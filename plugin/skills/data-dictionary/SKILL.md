---
name: data-dictionary
description: Decide with the author exactly what a study will collect, and write it in design/data_dictionary.yaml from the analysis plan, one entry per variable with its definition, codes and reason, and the form it is collected on. Use when the data a question needs do not exist yet (a survey, a chart review, a prospective cohort, a trial, a case series, a systematic review's extraction form), when an existing dataset's variables are described for the data checks, or when check reports dictionary-invalid, plan-variable-undefined, dictionary-entry-unused, dictionary-codes-undecided, dictionary-derivation-unsaid, dictionary-input-undefined, dictionary-derivation-cycle, dictionary-reporting-item-unknown or dictionary-reporting-unchecked.
---

# Deciding what to collect, before collecting it

A study that collects its own data has one chance to collect them. A confounder the plan
adjusts for and nobody recorded is found when the data come in, and cannot be recovered. A
variable recorded two ways at two sites cannot be pooled. And a variable nobody needed is
still a variable to collect, to clean, to explain to an ethics committee and to protect.

So the collection plan is written from the analysis plan, before the first record, and held
to it: every variable the plan names has an entry with its definition, and every entry is
there because something needs it. G12 checks both, and warns; it never blocks.

## Where it lives

`design/data_dictionary.yaml`, beside `design/plan.md`, in UTF-8. A project with no
dictionary is asked for none. One that does not read, by its schema or by what the schema
cannot say (a name given twice, a reference to a form or a list of codes that is not there,
codes on a type that has none), is `dictionary-invalid`, which fails at every stage: the
data checks and the export read the same file and would read it wrong.

```yaml
schema: manuscript-guard/data-dictionary/1

forms:                       # the parts of the form, in order
  - {id: baseline, label: Baseline visit, timing: at enrolment, recorded_by: research nurse}

code_lists:                  # lists of codes several variables share
  yes_no:
    - {code: 1, label: "Yes"}
    - {code: 0, label: "No"}

variables:
  - name: sex
    label: Sex
    definition: Sex recorded at birth, as stated by the participant.
    type: categorical        # binary, categorical, ordinal, continuous, count,
                             # date, datetime, time, text or identifier
    values: [{code: 1, label: Male}, {code: 2, label: Female}]
    missing: [{code: 9, label: not stated}]
    required: true
    form: baseline
    source: participant
  - name: pregnant
    label: Pregnant
    definition: Pregnant on the day of enrolment, by the participant's report.
    type: binary
    code_list: yes_no
    applies_if: {variable: sex, in: [2]}
    form: baseline
```

The schema has the rest: `unit`, `range`, `question` (the wording on the form, where it is
not the label), `timing` and `recorded_by` for one variable, `derived_from` and
`derivation`, `instrument` and `item`, `standard`, `reporting`, `reason`, and for the data
checks `datasets`, `study_period`, `pattern`, `within_study_period` and `rules`.

YAML reads some plain values as something else: `010` as the number 8, `8:30` as 510, an
unquoted `No` as false. Put codes with a leading zero, times and words such as Yes and No
in quotes. The loader refuses each misreading at its line and says what to write.

## Start from the plan

Read `design/plan.md` with the author, section by section, and list what each one needs:

- the population: each eligibility criterion that has to be recorded to be applied;
- the exposure and the comparator, as the plan will code them;
- the outcome, with the definition the plan chose;
- each covariate, confounder and effect modifier the analysis names;
- what the design itself needs: time zero and the end of follow-up of a cohort, the risk
  windows of a self-controlled design, the randomisation and the intercurrent events of a
  trial, the fields an extraction form takes from each included study;
- each planned result, and what it is computed from.

Name each variable in the plan in backticks, exactly as its entry names it, `sex`, where the
plan uses it. That is how G12 reads the plan: a name in backticks outside the Deviations
section is a variable, and one the dictionary does not define is `plan-variable-undefined`.
Write code otherwise, `glm()` or `stats::glm`, so that it is not taken for a variable, and a
result's key keeps its dot, `ror.point`.

Then write one entry for each. A derived variable (age from two dates, a score from its
items) names what it is computed from and how, and each input is an entry of its own: that
is what makes sure the input is collected.

## An entry worth having

The test of a definition is whether two people recording the same patient from the same
record would write the same value. "Smoking status" is a label. "Smoked any tobacco in the
30 days before enrolment, by the participant's report; former smokers who stopped earlier
are 0" is a definition. Write, for each:

- what is recorded, from which source, at which visit, by whom;
- the codes, in the order of the scale where it has one, and the codes that mean missing,
  each with what it means (not asked, not known, refused);
- the unit, and the range a plausible value lies in;
- whether a record without it is incomplete, and where it is asked only of some records.

Where the author has not decided the codes yet, leave `values` out: G12 warns
(`dictionary-codes-undecided`) until they are decided, which is better than codes made up
to quiet it.

## Definitions that already exist

Where a validated instrument or a standard terminology defines the variable, use it rather
than a new one, and say which:

- **An instrument** (a symptom scale, a quality-of-life questionnaire, a causality
  assessment) goes under `instruments` with its name, its version, the citation key of the
  paper that validated it, and its `licence`: the terms of use as the holder states them,
  read on the holder's own page, or "not known: ask <holder>". Each variable that records an
  item names the instrument and the item number. **Never write an instrument's items, its
  wording or its response options from memory.** They come from the licensed copy the
  author holds; until then, leave `question` out. A scale reworded is a different scale.
- **A terminology** goes under `standard`: its system (MedDRA, CTCAE, ICD-10, ATC, LOINC,
  SNOMED CT), the version the protocol uses, the level where it has levels, and the term.
  Give a `code` only where it was copied from the terminology itself. Some terminologies are
  licensed: say so to the author, who checks the terms that apply to them; do not state the
  terms yourself.

## The form

`forms` are the parts of the instrument in the order they are filled in: the pages of a case
report form, the sections of a survey, the parts of an extraction form. Give each variable
its form and, where it differs, its own timing. `applies_if` is the skip a form makes: a
question asked only where another coded variable holds one of these codes. One condition on
one variable is all it says; a question asked under two conditions is written without one
and the condition put in its definition.

## Nothing that nothing needs

Each entry is needed by the plan (it names it, or a variable it names is derived from it or
asked under it), by a reporting-checklist item (`reporting: {STROBE: [13a]}`, held to the
checklist where the project has it), or by a reason the author gives (`reason:`). Anything
else is `dictionary-entry-unused`. The record's own identifier needs its reason too. Ask
the author for each reason; a reason written to quiet the warning is worse than the warning.

Collect the least that identifies a person. A pseudonymous record number, not a name; an
age or a month, where the analysis needs no date of birth.

## Data that already exist

The same file describes a dataset the study reads rather than collects: `datasets` names its
tables, and each variable's `name` is the column's, capitals and dots allowed. The data
checks hold the data to it. What the study does not use needs its reason here as well, or
leave it out of the dictionary.

## What check reports

| Code | What to do |
|---|---|
| `dictionary-invalid` | put right what the message names, at its line; it fails at every stage |
| `plan-variable-undefined` | add the entry, or write the code as code; a name the dictionary spells otherwise is named in the hint |
| `dictionary-entry-unused` | name it in the plan, give its reporting item or its reason, or take it out |
| `dictionary-codes-undecided` | decide the codes with the author |
| `dictionary-derivation-unsaid` | give both `derived_from` and `derivation` |
| `dictionary-input-undefined` | add the input, so that it is collected |
| `dictionary-derivation-cycle` | say which of the variables is recorded |
| `dictionary-reporting-item-unknown` | give the item as the checklist numbers it |
| `dictionary-reporting-unchecked` | a note: the checklist is not in the project; the reporting-checklist skill retrieves it |

## If you are a model doing this

Draft; the author decides. Propose the entries the plan implies and ask about each one you
are unsure of, the definition before anything else. Do not invent codes, items, licences or
reasons, and do not copy a definition from a paper you have not read in full. An entry left
for the author to complete is worth more than one completed by guessing, because nobody
will check a guess once it reads well.
