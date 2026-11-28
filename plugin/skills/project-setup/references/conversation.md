# Each question of the setup conversation

What each question of `manuscript-guard setup questions` needs from the author, beyond the
`question`, `why` and `options` the command gives. Ask it in the author's own terms; write the
answer into `design/setup.yaml` at the question's `id` exactly as they gave it, never from what
you know of them or of anyone.

## How the manuscript is written (`start`)

Markdown, LaTeX, or a Word paper the folder holds. A Word paper is brought in as Markdown;
once `apply` has run, read with the authors what the conversion left as typed (the tables
left as grid tables, the citations and references it could not match), which the notes of
`apply` list. For LaTeX, say that a few commands read Markdown only: the Word round trip, the
co-author checker and the proof check (docs/latex.md).

## The title (`title`)

The working title, which can change later. TeX in it is kept only between dollar signs:
`IFN-$\gamma$`. With a Word paper, an empty title keeps the one its Title style holds.

## The language (`language`)

British (`en-GB`) or American (`en-US`) English, or another language. Ask; do not infer it
from the author's name, country or the way they type to you. A journal may ask for one; once
its profile is filled, `next` says so. For another language, say what the notes of `apply`
say: the numbers, citations and sources are checked, and the writing checks read English.

## The design (`study_type`)

`shortlist: 3`. Ask the author first to describe the study in a sentence or two: who is
studied, what is compared, and how the data were or will be gathered. Then offer the three
options whose `label` and `effect` fit that description best, and "None of these", which
lists the rest by number. A study that fits none is `other`. You pick only which three to
show; the author picks the design, and may pick one you did not show.

## The reporting guidelines (`reporting_guideline`)

The options are the design's guidelines; more than one may apply (STROBE and RECORD for a
cohort study of routinely collected data). Put it as a question several of whose options may be picked.
Another guideline is written by its name. An empty list, `[]`, puts the choice off.

## The journal (`journal`)

A profile the project already has; a journal the author names, written as
`journal: {name: "<the name>"}`, whose profile `apply` starts as the annotated template; `help`,
which hands the choice to the journal-profile skill once the project is written; or `later`.
Do not suggest a journal here: choosing one is the journal-profile skill's conversation, with
the author's criteria first.

## The authors (`authors`)

Ask for the list in byline order, then for each author: the given and family names as they
write them, each affiliation's full text as it is printed ("Department, Institution, City,
Country"), and which author is the corresponding one. An ORCID iD, an e-mail address and
degrees where they have them; an iD is written bare, `0000-0002-1825-0097`. Equal contribution
where two or more contributed equally (`equal_contribution: true`). Take every one of these
from the author: never from memory, from a CV or a web page they did not give you, or from
the name of someone you know. Read the list back before writing it.

```yaml
authors:
  - given: Ada
    family: Byron
    affiliations: ["Department of Pharmacology, University of Examples, Caen, France"]
    corresponding: true
    orcid: 0000-0002-1825-0097
    email: ada@example.org
```

## The declarations (`declarations`, `statistician`, `ethics_lead`)

`later` is a full answer: nothing is asked or written now. Where the author gives them now
(`given`), write in each author's entry their `funding`, each grant with its identifier
("Agence Nationale de la Recherche (ANR-20-CE17-0001)"), their `competing_interests` ("None
declared." where there are none; an empty one is not a declaration of none) and their `credit`
roles, as the CRediT taxonomy writes them ("Writing – original draft", with its dash). Once
filled, G4 holds the manuscript's statements to them, so an entry guessed is one the paper is
held to.

The statistician signs off a G15 warning left standing, and only they may: an author, by the
name the options give, or `{name: <their name>}` for someone else. The ethics lead is the
author who holds the approval, with its reference: `{author: <family name>, approval:
<reference>}`, or `none` where the study needs no approval.

## The analysis language (`analysis`)

Python, R, another language whose tables `harvest` takes in, or not decided. `apply` says
what this machine lacks for it; ask before installing anything.

## The data (`data.where`, `data.folder`, `data.publishable`, `data.minimum_cell_count`)

- In the project's folder: its name (`data`), and whether the data may be published with the
  repository. Data about people, or under a data-use agreement, usually may not; the author
  says.
- Held apart from the agent: the custodian's smallest publishable count, from the data-use
  agreement, never guessed; 1 where it sets none. The vault is registered by a person, where
  the data can be read: say so, and that the agent then works on a synthetic copy
  (docs/vault.md).
- At a site or research environment: the same count, and the outputs come back through the
  site's receipt (docs/harvest.md).
- Not obtained yet: the data-sources skill takes it on once the project is written.

## The registration (`registration`)

Each identifier as the registry writes it (`NCT01234567`, `CRD42020123456`, an OSF
registration's address), `none`, or `later`. The analysis-plan skill holds the paper to it afterwards.

## The stage (`stage`)

Asked only of a paper written already or an analysis under way. The recommended stage follows
from the folder: drafting for a Word paper or results written, analysis for scripts alone.

## The repository (`repository.*`)

Whether the folder becomes a git repository, where it is not one; where it will be shared; in
a private repository, whether the stored copies of the cited works are committed, paywalled
papers among them; and whether the workflow that runs check on each push is written.

## Earlier work (`earlier_work`)

Whether the authors have published on these data before: an abstract, a preprint, an
article. Yes hands to the related-outputs skill, which records each one and compares it.
