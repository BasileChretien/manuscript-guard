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

# Third-party data

One file in the package is made from somebody else's work and **is** redistributed:
`src/manuscript_guard/data/spelling_variants.tsv`, the list G14 reads to tell British
spelling from American.

It is derived from **VarCon** (Variant Conversion Info) by Kevin Atkinson and Benjamin
Titze, which is published with the SCOWL word lists at <http://wordlist.aspell.net/> and
<https://github.com/en-wl/wordlist>. The source is one file, `varcon/varcon.txt`, at commit
`1605448f6522e9dd432287eff44dfa7232b39c94`: VarCon 2020.12.07 with the changes made to it
up to 2024-07-22. `tools/derive_spelling_variants.py` names that file by its SHA-256 and
refuses any other, so the list in the package is a function of a known source and of a
script that is in this repository.

**The derived file is a modified version of VarCon's data, not VarCon's own file.** It
keeps about 8,600 of its words, in three columns of this project's. What was left out,
and why, is written at the top of the script: the clusters VarCon has not verified, but
for a few regular correspondences; the words above SCOWL level 80; words of fewer than
four letters; names and possessives; and a short list of words that scientific writing
spells one way in any English. For anything but this one check, take VarCon from its
authors.

VarCon's terms were read on 2026-10-06 in the README that travels with the file. **These
are notes, not legal advice.** They permit use, copying, modification and distribution for
any purpose, on the condition that the copyright notice is in every copy and that the
copyright and permission notices are in the supporting documentation. Part of VarCon comes
from the Ispell word lists, whose terms add that a modified version is marked as one. So:

- the derived file opens with the notices below, in full, and says in its first lines that
  it is a modified version. `tests/test_spelling.py` fails if either goes;
- the notices are repeated here, which is the supporting documentation they ask for;
- the wheel carries the derived file, and so carries the notices with it.

The notices, as VarCon's README gives them:

> Copyright 2000-2020 by Kevin Atkinson (kevina@gnu.org) and Benjamin Titze
> (btitze@protonmail.ch).
>
> Copyright 2000-2019 by Kevin Atkinson
>
> Permission to use, copy, modify, distribute and sell this array, the associated
> software, and its documentation for any purpose is hereby granted without fee, provided
> that the above copyright notice appears in all copies and that both that copyright
> notice and this permission notice appear in supporting documentation. Kevin Atkinson
> makes no representations about the suitability of this array for any purpose. It is
> provided "as is" without express or implied warranty.
>
> Copyright 2016 by Benjamin Titze
>
> Permission to use, copy, modify, distribute and sell this array, the associated
> software, and its documentation for any purpose is hereby granted without fee, provided
> that the above copyright notice appears in all copies and that both that copyright
> notice and this permission notice appear in supporting documentation. Benjamin Titze
> makes no representations about the suitability of this array for any purpose. It is
> provided "as is" without express or implied warranty.
>
> Since the original words lists come from the Ispell distribution:
>
> Copyright 1993, Geoff Kuenning, Granada Hills, CA
> All rights reserved.
>
> Redistribution and use in source and binary forms, with or without modification, are
> permitted provided that the following conditions are met:
>
> 1. Redistributions of source code must retain the above copyright notice, this list of
>    conditions and the following disclaimer.
> 2. Redistributions in binary form must reproduce the above copyright notice, this list
>    of conditions and the following disclaimer in the documentation and/or other
>    materials provided with the distribution.
> 3. All modifications to the source code must be clearly marked as such. Binary
>    redistributions based on modified source code must be clearly marked as modified
>    versions in the documentation and/or other materials provided with the distribution.
> (clause 4 removed with permission from Geoff Kuenning)
> 5. The name of Geoff Kuenning may not be used to endorse or promote products derived
>    from this software without specific prior written permission.
>
> THIS SOFTWARE IS PROVIDED BY GEOFF KUENNING AND CONTRIBUTORS ``AS IS'' AND ANY EXPRESS OR
> IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
> MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL
> GEOFF KUENNING OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
> EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
> SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
> HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
> TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
> SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
