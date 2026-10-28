# Journal profiles: what the journal asks, quoted from its page

A journal profile is the journal's instructions for authors, read from its own page and
written down as data: `profiles/journals/<slug>.yaml` in the project, started from the
annotated [template](../src/manuscript_guard/profiles/journals/TEMPLATE.yaml)
(`manuscript-guard journal --template <slug>`) and filled by the
[journal-profile skill](../plugin/skills/journal-profile/SKILL.md) or by hand. No profile ships with the tool, because a journal's rules
change without notice and a rule compiled into the tool would go wrong silently. The
template says what each field means and what to do where the page is silent: delete the
line.

Every rule is quoted. The page is stored as text (`profiles/journals/sources/<slug>.txt`),
each rule carries the words it was read from under `quotes:`, and G4 fails a quote that is
not on the stored page. A limit above 1 must state its number in its quote, and so must
each number above 1 of a box and of a graphical abstract, each of a graphical abstract's
numbers that is not whole, and its aspect ratio. A rule no gate
checks goes under `manual:`, quoted, and the corresponding author signs it off.

Most of the profile is about the paper: word limits, required sections and statements, the
structured abstract, the reference style, the figures' artwork rules, the English, how a
pointer to a table is written. This page describes the three blocks about what the journal
prints and lets out beside the paper.

## Boxes beside the abstract

Highlights, key points, a research-in-context panel, a plain-language summary: short texts
the journal prints with the paper, often of a set number of items of a set length.

```yaml
boxes:
  - id: highlights
    heading: '^highlights$'
    required: true
    items_min: 3
    items_max: 5
    item_max_chars: 85
    file: separate
  - id: key-points
    heading: '^key points$'
    max_words: 100
    headings: [Question, Findings, Meaning]
quotes:
  boxes.highlights: "Include 3 to 5 highlights. Maximum 85 characters, including spaces, per highlight."
  boxes.key-points: "Key Points (75-100 words) under the headings Question, Findings and Meaning."
```

G4 looks for each box in the main text:

- in Markdown, a section whose heading `heading` matches, a regular expression searched in
  the title as printed (its number and its bold off), case-insensitively, with its
  subsections;
- in LaTeX, the box's environment (`\begin{highlights}`; `environment:` names it where it is
  not the id without its hyphens), or a section whose heading matches, as in Markdown.

An item is a line of the box's list, run on over the lines that follow it; where the box has
no list, a paragraph. What is printed is measured: a comment and a listing are passed over, a
binding counts as its value's display, and Markdown's marks and LaTeX's commands are taken off.

| Code | What it says |
|---|---|
| `box-missing` | no heading or environment of the main text is the box's |
| `box-items` | fewer items than `items_min`, or more than `items_max` |
| `box-item-long` | an item over `item_max_chars` characters, spaces included, or over `item_max_words` words |
| `box-over-limit` | the box over `max_words` words |
| `box-headings-missing` | a heading of `headings` the box does not carry |
| `box-heading-invalid` | a box's `heading` that is no regular expression (fails from internal review) |

Each is a warning until submission. At submission it fails where the box is `required: true`,
and stays a warning where the journal only asks for one. A box written only in the
supplement is not the box: a journal reads its boxes with the paper, and `box-missing` names
the supplement's file. `file: separate` is recorded for the submission pack; G4 reads the box
in the manuscript either way.

G8 reads a box as it reads the abstract: a number a box binds that the Methods and the
Results do not report, nor a table or a figure, is `summary-not-reported`.

## A graphical abstract

```yaml
graphical_abstract:
  required: true
  min_width_px: 1328
  min_height_px: 531
  formats: [tiff, png, jpg]
quotes:
  graphical_abstract.required: "A graphical abstract is mandatory for this journal."
  graphical_abstract.min_width_px: "a minimum of 1328 × 531 pixels (w × h)"
  graphical_abstract.min_height_px: "a minimum of 1328 × 531 pixels (w × h)"
```

Each line is a rule of its own, quoted under `quotes.graphical_abstract.<name>`: `required`,
the size (`width_px`, `height_px`, `min_width_px`, `min_height_px`), `aspect_ratio`,
`min_dpi`, `formats`, `max_file_mb`, `max_words`, `max_labels`, `alt_text_max_chars` and
`min_text_pt`. Where it is required, G4 notes `graphical-abstract-missing` until
`communication/graphical-abstract/` exists. Nothing checks the graphical abstract itself yet.

## What may be shared

```yaml
sharing:
  source_url: https://www.journal-of-examples.org/sharing
  retrieved_on: 2026-10-28
  preprint: {where: [personal-site, subject-repository]}
  accepted:
    where: [institutional-repository]
    embargo_months: 12
    licence: CC BY-NC-ND 4.0
  published: {where: [social-media-link]}
quotes:
  sharing.accepted: "The accepted manuscript may be deposited in an institutional repository 12 months after publication."
```

For each version of the paper (`preprint`, `accepted`, `published`), where it may be shared
(`personal-site`, `institutional-repository`, `subject-repository`, `academic-network`,
`social-media-link`), after how long, under which licence and with which statement. Each
version is quoted under `quotes.sharing.<version>`; where the policy was read, and when, are
no rules. It is read from the journal's own policy page, not from a summary of it such as
Sherpa Romeo, which needs a key besides. No gate reads the block yet, and without it nothing
is refused yet.

## Quotes and their numbers

A box's quote states each of its numbers above 1 (`items_min`, `items_max`,
`item_max_chars`, `item_max_words`, `max_words`), and so does each line of the graphical
abstract's, as a limit's quote states its number: G4 fails one that does not
(`journal-limit-not-in-quote`). A graphical abstract's number that is not whole
(`max_file_mb: 2.5`) is stated in digits, "2.5", "2.50" or "2,5". Its `aspect_ratio` is
stated with both its parts in their order, "16:9", "16 : 9", "16 × 9", "16 x 9", "16/9" or
"16 by 9": "5:2", "16:10" and "1:16:9" do not state 16:9, and a page that says "square" does
not state "1:1".

A box has one quote, and each of its numbers is looked for anywhere in it: `items_max: 3`
passes against "3 to 5 highlights", since 3 is there. Check that each number is the one the
page gives for that field.

## A page of its own

Where the journal gives a box, the graphical abstract or the sharing policy on a page apart
from its instructions, an artwork guide or a self-archiving policy, store that page as a
file of its own and name it in the block:

```yaml
sharing:
  source_url: https://www.journal-of-examples.org/sharing
  page_file: profiles/journals/sources/journal-of-examples-sharing.txt
  page_sha256: 9b1c...    # as check prints it
```

The block's quotes are then held to that page and no other, its digest is checked as the
instructions page's is, and it is read again on its own:

```bash
manuscript-guard journal --reread new-sharing.txt --page profiles/journals/sources/journal-of-examples-sharing.txt
```

Without `--page`, or with `--page` naming the instructions page's file, `--reread` reads the
instructions page again, against the quotes held to it alone. `--page` without `--reread` is
refused. A box names its page in its own entry; two blocks may name one page. See also
[DESIGN.md](../DESIGN.md).
