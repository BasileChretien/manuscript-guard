# Boxes, a graphical abstract, and what may be shared

Part of the journal-profile skill, read when the journal's page asks for highlights, key
points or another box beside the abstract, says anything of a graphical abstract or of
what its authors may share, or when `check` reports `box-missing`, `box-items`,
`box-item-long`, `box-over-limit`, `box-headings-missing`, `box-heading-invalid` or
`graphical-abstract-missing`.

Three blocks record what the page says beside the paper itself. Fill each from the page, as
every other rule, and leave out what it does not say. Each value is quoted, and the quotes
are held to the stored page like the rest: where the journal gives one of these on a page of
its own (an artwork guide, a self-archiving policy), save that page's text with the
instructions page in the stored file, and record the digest `check` then prints.

`boxes` is the short texts the journal prints beside the abstract: highlights, key points,
research in context, a plain-language summary. One entry for each the page asks for:

```yaml
boxes:
  - id: highlights              # key-points, research-in-context, plain-language-summary, or your own
    heading: '^highlights$'     # a regular expression for the heading it goes under
    required: true              # only where the page requires it; leave out where it asks
    items_min: 3                # "3 to 5 bullet points"
    items_max: 5
    item_max_chars: 85          # "maximum 85 characters, including spaces"
    file: separate              # where the page says it is uploaded as a file of its own
  - id: key-points
    heading: '^key points$'
    max_words: 100              # the whole box
    headings: [Question, Findings, Meaning]
quotes:
  boxes.highlights: "Include 3 to 5 highlights. Maximum 85 characters, including spaces, per highlight."
```

Quote each box once, under `quotes.boxes.<id>`, with the words that state its numbers. Write
`environment:` only where the journal's LaTeX class writes the box in an environment whose
name is not the id without its hyphens (Elsevier's is `highlights`). G4 then looks for each
box in the main text and warns, until submission, where it is missing (`box-missing`), has too
few or too many items (`box-items`), an item too long (`box-item-long`), too many words
(`box-over-limit`) or lacks a heading the page names (`box-headings-missing`); at submission a
required box fails. A box written only in the supplement is not the box. G8 reads a number in
a box as it reads one in the abstract: one the Methods and the Results do not report is
`summary-not-reported`.

`graphical_abstract` is what the page says of a graphical abstract, each line its own rule
quoted under `quotes.graphical_abstract.<name>`: `required` (true where required, false where
asked for), its size in pixels (`width_px`, `height_px`, or `min_width_px` and
`min_height_px`), `aspect_ratio` ("5:2"), `min_dpi`, `formats`, `max_file_mb`, `max_words`,
`max_labels`, `alt_text_max_chars` and `min_text_pt`. Where it is required, G4 notes
`graphical-abstract-missing` until `communication/graphical-abstract/` exists.

`sharing` is what the journal lets its authors share of each version, read from its sharing
or self-archiving policy, with that page's address and the day you read it. Give a version
only where the page states it; quote each under `quotes.sharing.<version>`:

```yaml
sharing:
  source_url: https://www.journal-of-examples.org/sharing
  retrieved_on: 2026-10-28
  preprint: {where: [personal-site, subject-repository]}
  accepted:
    where: [institutional-repository]
    embargo_months: 12
    licence: CC BY-NC-ND 4.0
    set_statement: "This is the accepted manuscript of ..."
  published: {where: [social-media-link]}
quotes:
  sharing.accepted: "Authors may deposit the accepted manuscript in an institutional repository 12 months after publication."
```

`where` takes `personal-site`, `institutional-repository`, `subject-repository`,
`academic-network` and `social-media-link`; an empty list is nowhere. Nothing reads the
block yet, and without it nothing is refused yet. Do not take a policy from Sherpa Romeo or
any other summary of it: the journal's own page is the source.
