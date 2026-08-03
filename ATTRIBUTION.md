# Third-party guidelines

manuscript-guard **does not redistribute** any reporting guideline, checklist or journal
document. It ships *recipes*: instructions for reading a document you obtain yourself from
the body that publishes it. `manuscript-guard fetch` downloads on your request, to your
machine, from the publisher's own address; `manuscript-guard transcribe` then builds a
profile locally. Neither the documents nor the transcribed item text is committed to this
repository or included in the distributed package.

That is a deliberate structure, not an oversight. Reporting guidelines are published under
a patchwork of terms — one of those below is explicitly non-commercial, several state no
reuse licence at all — and a repository that shipped their text would have to satisfy the
strictest of them. Fetching on request avoids the question entirely: you obtain the document
exactly as you would by clicking the link.

The guidelines below are the work of their respective groups. Nothing here claims any right
in them, and citing the guideline you followed remains your responsibility as an author.

## Licence findings

Read on 2026-08-03. **These are notes, not legal advice.** Confirm the terms yourself before
relying on them, particularly before redistributing anything.

| Guideline | Licence as found | Where |
|---|---|---|
| RECORD | **CC BY**, stated explicitly | record-statement.org |
| STROBE | **CC BY** — the statement carrying this checklist was published in *PLoS Medicine* under the Creative Commons Attribution License. The STROBE site itself states only a bare copyright | strobe-statement.org, PMC2020495 |
| ARRIVE 2.0 | **CC BY** for the explanation and elaboration (*PLOS Biology*). The checklist's own terms are not separately stated | arriveguidelines.org |
| READUS-PV | **CC BY-NC** — non-commercial. Cannot be redistributed from an MIT repository | Europe PMC |
| RECORD-PE | Unconfirmed. The RECORD family states CC BY, but RECORD-PE was published separately (*The BMJ*, 2018) | record-statement.org |
| CONSORT 2025 | Unconfirmed. No licence on the site; a terms-of-use page exists | consort-spirit.org |
| SPIRIT 2025 | Unconfirmed. As CONSORT | consort-spirit.org |
| PRISMA 2020 | Unconfirmed. Site states only "Copyright © 2024-2026 the PRISMA Executive" | prisma-statement.org |
| TRIPOD 2015 | Unconfirmed. Site states only "Copyright 2020 - Julius Centrum" | tripod-statement.org |

Each recipe under `profiles/reporting/recipes/` carries the same finding, and
`manuscript-guard fetch` prints it before downloading anything, so the terms are seen rather
than buried in a file nobody opens.

## Download links

All thirteen recipes carry a direct `download_url`, and every one has been verified the only
way worth doing: fetched into an empty directory and checked against the sha256 the recipe
records, then transcribed. Thirteen fetched, thirteen checksums matched, thirteen profiles
built. Anyone with the recipes and a network connection gets the same documents and the same
profiles.

Two of those links took a second attempt, and both failures are the kind that would
otherwise pass unnoticed:

- **PRISMA** is served from `www.prisma-statement.org`, not `prismastatement.org`. The
  shorter host answers, but with an HTML page — so a naive fetch saved a 1 KB error document
  under a `.docx` name.
- **STROBE**'s combined checklist is the "wide" variant; the plainer `/download/…` address
  returns a landing page.

`fetch` now checks magic bytes — a `.docx` must begin `PK`, a `.pdf` must begin `%PDF` — and
refuses to save a web page wearing a document's extension, saying so at the point it
happens rather than three steps later.

The CONSORT recipe was rewritten against the copy `fetch` retrieves, rather than a
differently formatted edition of the same checklist, so that everyone who runs the command
gets the profile the recipe describes.

## If you want to redistribute a profile

Some of these would permit it. CC BY allows redistribution with attribution, so a STROBE,
RECORD or ARRIVE profile could in principle ship with this toolkit, provided the attribution
is correct and the licence travels with the file.

It still isn't done, for two reasons. A uniform rule is easier to keep right than a
per-guideline judgement that has to be re-made whenever a guideline is revised or added. And
the fetch route costs the user one command, which is a small price for never having to
reason about it again.

If you fork this and decide otherwise, confirm the current terms first — the notes above are
a snapshot of one afternoon's reading, and none of them replaces the guideline's own words.
