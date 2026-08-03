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

Sites read 2026-08-03. **These are notes, not legal advice.** Confirm the terms yourself
before relying on them, particularly before redistributing anything.

Five of these said "unconfirmed" in an earlier pass, meaning nobody had opened the page. All
five have now been read and the relevant sentence quoted, which is a different and much
smaller claim than "we have decided this is fine".

The one that mattered most turned out to be the one that reads least like a problem. TRIPOD
is a **free article under ordinary copyright**, not an openly licensed one — and an earlier
note recording it as merely "unconfirmed" would have let a reader assume it was like the
others. Free to read is not free to redistribute, and the distinction is invisible unless
someone looks for it.

| Guideline | Licence as found | Where |
|---|---|---|
| RECORD | **CC BY**, stated explicitly: *"The explanatory document and checklist are protected on a Creative Common Attribution (CC BY) license."* | record-statement.org/checklist.php |
| RECORD-PE | **CC BY 4.0**, commercial use permitted. The site's CC BY notice does not say whether it reaches the PE extension, but the RECORD-PE paper itself carries the BMJ open-access statement: *"an Open Access article distributed in accordance with the terms of the Creative Commons Attribution (CC BY 4.0) license, which permits others to distribute, remix, adapt and build upon this work, for commercial use, provided the original work is properly cited."* | PMC6234471 (*The BMJ* 2018;363:k3532) |
| STROBE | **CC BY** — the statement carrying this checklist was published in *PLoS Medicine* under the Creative Commons Attribution License. The STROBE site itself states only a bare copyright | strobe-statement.org, PMC2020495 |
| PRISMA 2020 | **CC BY 4.0**, commercial use permitted, via the statement paper — same BMJ open-access wording as RECORD-PE. The site itself states only *"Copyright © 2024-2026 the PRISMA Executive"* and has no terms page (`/terms` is a 404) | PMC8005924 (*BMJ* 2021;372:n71) |
| ARRIVE 2.0 | **CC BY** for the explanation and elaboration (*PLOS Biology*). The checklist's own terms are not separately stated | arriveguidelines.org |
| CONSORT 2025 | **Download and copying explicitly permitted**, with a condition and a restriction, quoted in full below | consort-spirit.org/terms-of-use |
| SPIRIT 2025 | As CONSORT — same site, same terms page | consort-spirit.org/terms-of-use |
| READUS-PV | **CC BY-NC** — non-commercial. Cannot be redistributed from an MIT repository | Europe PMC |
| TRIPOD 2015 | **All rights reserved — free to read, not openly licensed.** The site states only *"Copyright 2020 - Julius Centrum"*. The statement itself carries *"© BMJ Publishing Group Ltd 2014"*, is marked a free article, has no Creative Commons licence and is not deposited in PMC; the explanation and elaboration is *"freely available only on www.annals.org"* with copyright held by *Annals of Internal Medicine*. Free to read is not free to redistribute | tripod-statement.org, PMID 25569120 |

CONSORT and SPIRIT are worth quoting rather than summarising, because the permission is
explicit and the condition is the operative part:

> The materials contained in the site may be downloaded or copied provided that ALL copies
> retain the copyright and any other proprietary notices contained on the materials.

and:

> No material may be modified, edited or taken out of context such that its use creates a
> false or misleading statement or impression as to the positions, statements or actions of
> the SPIRIT–CONSORT Group.

What this toolkit does sits inside both. The download is the user's own, made from the
publisher's address on request. The generated profile records `source_url`, `licence` and
`source_file`, so the notices travel with it. And the transcription is verified item by item
against the document's own text — a profile that drifted from the source is a build failure,
which is close to the opposite of taking material out of context.

Each recipe under `profiles/reporting/recipes/` carries its own finding, and
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
