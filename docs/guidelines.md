# The guidelines a study answers to

A study answers to more than its journal: the reporting guideline of its design, the
recommendations every medical journal follows, its registration, the norms on reusing one's
own text, the standards its methods are judged by, and the rules of whoever holds its data.
Each row of the README's [table](../README.md#the-guidelines-it-answers-to) is set out here:
where the guideline is read from, what the check holds, and what it leaves to a reader.

Two things hold for all of them. Each is read from its source, a document or a page kept in
the project, and never from memory: a checklist whose items are roughly right gives
confident coverage of the wrong things. And each is checked on every run, from the stage at
which it starts to matter ([stages](stages.md)), so that what a guideline asks is found
while there is time to do it rather than at submission. How much time that saves has not
been measured.

## Reporting checklists

The package ships a recipe for each of these, and no checklist itself, since each has its own
licence:

| Recipe | For |
|---|---|
| CONSORT (2025) | randomised controlled trials |
| SPIRIT-2025 | clinical trial protocols |
| STROBE | cohort, case-control and cross-sectional studies |
| RECORD, RECORD-PE | studies of routinely collected health data, and their pharmacoepidemiology; with STROBE |
| PRISMA-2020, PRISMA-2020-abstracts | systematic reviews, and their abstracts |
| TRIPOD+AI, TRIPOD+AI-abstracts (2024) | studies developing or evaluating a clinical prediction model |
| TRIPOD-development, TRIPOD-validation, TRIPOD-development-validation (2015) | the same, replaced by TRIPOD+AI |
| STARD-2015 | studies of diagnostic accuracy |
| CHEERS-2022 | health economic evaluations |
| ARRIVE-2.0 | in vivo animal experiments |
| MDAR | papers in the life sciences: their materials, design, analysis and reporting |
| SAGER-2022-human, SAGER-2022-other | how sex and gender are reported, in studies with human participants and in other studies (animals, cells, the applied sciences); beside the design's own guideline |
| READUS-PV, READUS-PV-abstracts | disproportionality analyses of spontaneous reports |
| SANRA (2019) | narrative reviews: a rating scale, which no reporting guideline covers |

```bash
manuscript-guard fetch STROBE --url <link> --save-url   # the guideline's own document, and its licence
manuscript-guard transcribe                             # the items, made from that document by its recipe
manuscript-guard checklist STROBE                       # the completion file to fill in
```

`paper.yaml` names the guideline (`reporting_guideline`) and the study's design
(`study_type`). G5 holds that every item of the checklist says where in the manuscript it is
addressed, or why it does not apply ("n/a" is not a reason), and warns where the place it
names is no heading of the manuscript. It warns where a declared design has none of its
guidelines: a trial is reported with CONSORT, a cohort study with STROBE, RECORD or TARGET, a
case-control or self-controlled study with STROBE or RECORD, a disproportionality analysis
with READUS-PV, a systematic review with PRISMA and a prediction model with TRIPOD;
`study_type: other` is a design none of these is. MDAR and SAGER belong to no one design, so
no design asks for them: a project that follows one names it in `reporting_guideline` beside
its design's guideline. It warns too when the manuscript says it
followed a guideline that `paper.yaml` does not name, and when a recipe records that the
guideline's authors replaced it, as TRIPOD 2015's recipes do for TRIPOD+AI.
TARGET has no recipe yet.

A new edition of a guideline is a new recipe, and the items are made again from the new
document by `transcribe`; a generated checklist is never edited by hand, so it stays what
the published document says. A guideline with no recipe can have one written in the
project's own `profiles/reporting/recipes/` (the reporting-checklist skill says how).

G5 does not judge whether the text at that place does what the item asks. That is a
reader's question, and the starter panel of a review round has a reporting-guideline
reviewer for it ([review panel](review-panel.md)).

## The journal's instructions for authors

A journal profile holds the journal's rules, each quoted from the journal's page as stored
in the project, and G4 holds the manuscript to them: the word limits, the required sections
and statements, the Data availability statement against the journal's data policy, the
figure files against its artwork rules, the boxes it prints beside the abstract, and the
citation style it names. A rule no gate can check is signed off by the corresponding
author. `journal --reread` reads the page again and shows which rules changed since it was
stored. A journal chosen from the shortlist is looked up in the NLM Catalog and DOAJ
(`lookup --journals`). [Journal profiles](journal-profiles.md) has the rest, and the
journal-profile skill chooses the journal with the author.

A statement the journal asks for on the use of AI in preparing the manuscript is a required
statement of its profile, held like the others. Nothing here writes it.

## ICMJE's recommendations

Two of them are checked. The main text's tables and figures are each cited, and numbered in
the order of their first citation (G2). And an earlier output of the same data, an abstract,
a preprint or an article, listed in `literature/related.yaml`, is held to this paper value
by value, and an overlap of data and authors that the manuscript does not disclose warns,
and fails at submission (G8).

## The study's registration

`paper.yaml` lists the study's registrations, and `lookup --registrations` asks
ClinicalTrials.gov, the EU PAS register, OSF or ISRCTN about each once, keeping the answer
in `design/registrations/`. G12 then holds that each is given in the manuscript, is known to
its registry, and was made before the study started and before the first results, or is
said to be retrospective; and that each registered outcome is quoted in the registry's words
and role, and reported as a planned result or its absence said under Deviations from the
plan (a warning until submission).

## Text recycling

The norms are the Text Recycling Research Project's best practices for researchers, and
COPE and BioMed Central's text recycling guidelines for editors: a standard description of a
method may be reused in the Methods where the earlier paper is cited, and overlap in the
results, discussion or conclusions is unlikely to be acceptable; the journal's policy
decides. G7 compares the manuscript with the stored copy of each earlier output of the same
authors that `literature/related.yaml` lists, on this machine, and names each passage of
twelve shared words or more with the part of the paper it is in: a note in Methods that cite
the output, in a statement the journal asks for, or where the output is a preprint, abstract
or protocol of this study, and elsewhere a warning from internal review. It reads only the
outputs listed, and is no search of other people's papers.

## Methods standards

Before the analysis, the methods of similar studies can be appraised in
`design/methods_review.yaml` against a published standard. Built in: the ENCePP Guide on
Methodological Standards in Pharmacoepidemiology, target trial emulation, ROBINS-I, ROBINS-E,
self-controlled case series methods, immortal time bias, READUS-PV, STROBE with its
explanation and elaboration, RECORD-PE, RoB 2, PROBAST+AI and ROBIS; a project can add its
own. G12 holds that each appraisal names its standard and the standard's domain, that each
decision to take a method is a person's (a model's name may not sign it), and that a method
taken is cited in the plan with its standard. The methods-review skill does the appraising
with the author.

## The data custodian's rules

Where `paper.yaml` declares the custodian's minimum cell count (`custodian:
minimum_cell_count`), G2 fails a bound count below it from internal review, and a count
held back ("<5") beside a sum the analysis declares that gives it away. An input the custodian keeps is not in git (G1),
`package` never packs it, and `deposit` runs the same checks before it stages anything. The
data can also be held in a folder the operating system keeps from the agent
([the vault](vault.md)). Whether a setup meets the custodian's terms is for the custodian to
say.

[Back to the README](../README.md)
