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
| ARRIVE 2.0 | **Not stated** for the guidelines PDF the recipe reads; the site carries only a copyright line of the NC3Rs. The statement and the explanation and elaboration (*PLOS Biology* 2020) are **CC0 1.0** in their Europe PMC records and in Crossref, though the site calls the second CC-BY; an earlier pass recorded that CC-BY here. Read 2026-10-16 | arriveguidelines.org, PMC7360023, PMC7360025 |
| STARD 2015 | **CC BY 4.0**, via the statement paper's licence in its Europe PMC full text; Crossref records only the publisher's text-and-data-mining terms. The Word checklist the EQUATOR Network serves states no terms of its own. Read 2026-10-16 | PMC4623764 (*BMJ* 2015, doi:10.1136/bmj.h5527) |
| CHEERS 2022 | **CC BY 4.0**, via the licence of The BMJ's copy of the statement in its Europe PMC full text and in Crossref, with the same contradictory copyright line as TRIPOD+AI's. The statement was published in several journals at once, and one copy is CC BY-NC. Read 2026-10-16 | PMC8749494 (*BMJ* 2022, doi:10.1136/bmj-2021-067975) |
| TRIPOD+AI | **CC BY 4.0**, via the statement paper's licence in its Europe PMC full text and in Crossref. The XML's copyright line also carries the publisher's no-commercial-reuse wording, which the licence it states contradicts. Read 2026-10-16 | PMC11019967 (*BMJ* 2024, doi:10.1136/bmj-2023-078378) |
| CONSORT 2025 | **Download and copying explicitly permitted**, with a condition and a restriction, quoted in full below | consort-spirit.org/terms-of-use |
| SPIRIT 2025 | As CONSORT — same site, same terms page | consort-spirit.org/terms-of-use |
| READUS-PV | **CC BY-NC** — non-commercial. Cannot be redistributed from an MIT repository | Europe PMC |
| SANRA | **CC BY 4.0**, via the scale's paper (Baethge C, Goldbeck-Wood S, Mertens S, *Research Integrity and Peer Review* 2019;4:5), which carries the Creative Commons Attribution 4.0 wording and states that SANRA and its explanations document are available open access. The form itself is served from aerzteblatt.de and states no terms of its own | PMC6434870, aerzteblatt.de/down.asp?id=22862 |
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

All eighteen recipes carry a direct `download_url`. The first thirteen were verified the
only way worth doing: fetched into an empty directory and checked against the sha256 the
recipe records, then transcribed. Thirteen fetched, thirteen checksums matched, thirteen
profiles built; SANRA, the fourteenth, was added later and verified the same way against
the form served by `down.asp?id=22862`. STARD 2015, added with CHEERS 2022 and the two
TRIPOD+AI recipes on 2026-10-16, was fetched and transcribed from the EQUATOR Network's
Word checklist when it was written; the other three read their statement paper, below. Anyone with the recipes and a network connection gets the same documents and the same
profiles.

The two TRIPOD+AI recipes and the CHEERS 2022 recipe, added on 2026-10-16, read the statement
paper itself: its full text from Europe PMC (`/rest/<PMCID>/fullTextXML`). They record a digest of the table's rows
rather than of the file, because Europe PMC can regenerate the XML with nothing in the table
changed, and `fetch` refuses an answer that is not a JATS article.

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
RECORD or TRIPOD+AI profile could in principle ship with this toolkit, provided the attribution
is correct and the licence travels with the file.

It still isn't done, for two reasons. A uniform rule is easier to keep right than a
per-guideline judgement that has to be re-made whenever a guideline is revised or added. And
the fetch route costs the user one command, which is a small price for never having to
reason about it again.

If you fork this and decide otherwise, confirm the current terms first — the notes above are
a snapshot of one afternoon's reading, and none of them replaces the guideline's own words.

# Rules adapted from other projects

## Writing Guard: the residue of a revision

The `residue` rules of `src/manuscript_guard/data/ai_writing.yaml`, which G6 reads for words
written to the reviewers or to a model and left in the manuscript, take their idea and part
of their lists from the `process_residue` rules of [Writing
Guard](https://github.com/xmutfyh/dsh-plugin-writing-guard) (`src/rules.ts`, read on
2026-10-20 on its `master` branch). Taken from it: that the words of a reply to the
reviewers are an error in the paper and none in the letter; "as requested", "as suggested
by" and "in response to" the reviewer; "we have (now) updated, modified, corrected,
clarified, expanded, rewritten, replaced or revised"; "the previous, original or earlier
version, manuscript, draft or submission"; and that "revised" in a name, the Revised
Cardiac Risk Index, is no residue. None of its patterns is copied: each was written again
and narrowed against 399 papers by people (DESIGN.md). Its "to address the concern" and its
defensive purpose, "to avoid confusion", were not taken, since papers by people write them
as prose.

Writing Guard is under the MIT licence:

```text
MIT License

Copyright (c) 2026 dsh-plugin-writing-guard contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

# Third-party data

Three files in the package are made from somebody else's work and **are** redistributed. The
first is `src/manuscript_guard/data/spelling_variants.tsv`, the list G14 reads to tell
British spelling from American. The second, `src/manuscript_guard/data/claim_strength.yaml`,
is under [The claim-strength ladder](#the-claim-strength-ladder) at the end of this file. The
third, `src/manuscript_guard/data/palettes.json`, the palettes, is under
[The palettes](#the-palettes), after it.

It is derived from **VarCon** (Variant Conversion Info) by Kevin Atkinson and Benjamin
Titze, which is published with the SCOWL word lists at <http://wordlist.aspell.net/> and
<https://github.com/en-wl/wordlist>. The source is one file, `varcon/varcon.txt`, at commit
`1605448f6522e9dd432287eff44dfa7232b39c94`: VarCon 2020.12.07 with the changes made to it
up to 2024-07-22. `tools/derive_spelling_variants.py` names that file by its SHA-256 and
refuses any other, so the list in the package is a function of a known source and of a
script that is in this repository.

**The derived file is a modified version of VarCon's data, not VarCon's own file.** It
keeps about 8,400 of its words, in three columns of this project's. What was left out,
and why, is written at the top of the script: the clusters VarCon has not verified, but
for a few regular correspondences; the words above SCOWL level 80; words of fewer than
four letters; names and possessives; a spelling both usages have as a variant; and a short
list of words that scientific writing spells one way in any English, or that a line of
VarCon pairs wrongly. For anything but this one check, take VarCon from its authors.

VarCon's terms were read on 2026-10-06 in the README that travels with the file. **These
are notes, not legal advice.** They permit use, copying, modification and distribution for
any purpose, on the condition that the copyright notice is in every copy and that the
copyright and permission notices are in the supporting documentation. Part of VarCon comes
from the Ispell word lists, whose terms add that a modified version is marked as one. So:

- the derived file opens with the notices below, in full, and says in its first lines that
  it is a modified version. `tests/test_spelling.py` fails if either goes;
- the notices are repeated here, which is the supporting documentation they ask for;
- the wheel carries the derived file, and so carries the notices with it.

The notices, as VarCon's README gives them, in a block so that the numbers of the
clauses stay as written:

```text
Copyright 2000-2020 by Kevin Atkinson (kevina@gnu.org) and Benjamin Titze
(btitze@protonmail.ch).

Copyright 2000-2019 by Kevin Atkinson

Permission to use, copy, modify, distribute and sell this array, the associated
software, and its documentation for any purpose is hereby granted without fee, provided
that the above copyright notice appears in all copies and that both that copyright
notice and this permission notice appear in supporting documentation. Kevin Atkinson
makes no representations about the suitability of this array for any purpose. It is
provided "as is" without express or implied warranty.

Copyright 2016 by Benjamin Titze

Permission to use, copy, modify, distribute and sell this array, the associated
software, and its documentation for any purpose is hereby granted without fee, provided
that the above copyright notice appears in all copies and that both that copyright
notice and this permission notice appear in supporting documentation. Benjamin Titze
makes no representations about the suitability of this array for any purpose. It is
provided "as is" without express or implied warranty.

Since the original words lists come from the Ispell distribution:

Copyright 1993, Geoff Kuenning, Granada Hills, CA
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are
permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this list of
   conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list
   of conditions and the following disclaimer in the documentation and/or other
   materials provided with the distribution.
3. All modifications to the source code must be clearly marked as such. Binary
   redistributions based on modified source code must be clearly marked as modified
   versions in the documentation and/or other materials provided with the distribution.
(clause 4 removed with permission from Geoff Kuenning)
5. The name of Geoff Kuenning may not be used to endorse or promote products derived
   from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY GEOFF KUENNING AND CONTRIBUTORS ``AS IS'' AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL
GEOFF KUENNING OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## The claim-strength ladder

`src/manuscript_guard/data/claim_strength.yaml` holds the words `manuscript-guard reworded`
reads to tell whether an edit changed how strongly a sentence claims. It is adapted from the
**Claim-Strength Contract** of [Awesome Research
Skills](https://github.com/Yila-AI/awesome-research-skills) by the Yila-AI contributors, in
`skills/science-research-writing/references/certainty-and-claim-strength.md`, read on
2026-10-20 at commit `0609e85b6dbfdae8a48ba66c332d340265d7b3e5`. That repository is under the
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0), whose text, as that
repository ships it, is beside the data file in the package:
`src/manuscript_guard/data/claim_strength_LICENSE.txt`. The repository has no NOTICE file.
The document asks that the contract or its ladder be credited where it is reused or
adapted, and this is that credit.

Taken from it: the ladder's six rungs and their order, from "is consistent with" and "may
suggest" through "is associated with", "predicts", "contributes to" and "affects" to
"causes" and "demonstrates that"; and its certainty markers, read as hedges ("may",
"might", "could", "appears", "suggests", which is on the ladder's first rung here),
negations ("did not") and limits ("only", "within this sample", "under these
conditions").

Changed, on 2026-10-20: each rung is named, holds synonyms the contract does not list
("correlated", "linked to", "increased", "reduced", "prevented" and others) and lists the
inflections it is read in; the hedges, negations and limits are lists of their own, with
words the contract does not name ("possibly", "seems", "no", "never", "non-significant",
"in this sample"); and the rules for reading them are this project's (whole words, a
capital only where a sentence opens, a word in a compound or a participle after an article
not read). The contract's other parts, on null findings and on asking the author before a
claim is moved, are not used; the file's own comments say how each word is read.

## The palettes

`src/manuscript_guard/data/palettes.json`, which `manuscript_guard.palettes`, the R package's
`mg_palette()` and `manuscript-guard palettes` read, holds the colours of other people's
palettes. `tools/derive_palettes.py` reads each collection's colours from the collection's own
file, at a commit it names, and refuses a file whose SHA-256 is not the one written beside it;
it writes the R package's copy (`r/manuscriptguard/inst/extdata/palettes.json`) the same. Each
collection's licence, in the words of its own files, is beside the data:
`src/manuscript_guard/data/palettes_LICENSES.txt`, written by the same script from those files.

| Collection | By | Licence | Read from |
|---|---|---|---|
| [MetBrewer](https://github.com/BlakeRMills/MetBrewer) | Blake Robert Mills | CC0 1.0 | `R/PaletteCode.R` at `58839e5a` |
| [MoMAColors](https://github.com/BlakeRMills/MoMAColors) | MoMAColors authors | MIT | `R/Colors.R` at `854a8dae` |
| [NatParksPalettes](https://github.com/kevinsblake/NatParksPalettes) | Kevin S. Blake | MIT | `R/NatParksPalettes.R` at `21512883` |
| [PNWColors](https://github.com/jakelawlor/PNWColors) | Jake Lawlor | CC0 1.0 | `R/PNWColors.R` at `f16a14fc` |
| [wesanderson](https://github.com/karthik/wesanderson) | Karthik Ram | MIT | `R/colors.R` at `02e4129c` |
| [ColorBrewer](https://colorbrewer2.org) | Cynthia A. Brewer, Mark Harrower and The Pennsylvania State University | Apache 2.0 | `export/colorbrewer.json` of [axismaps/colorbrewer](https://github.com/axismaps/colorbrewer) at `7d135fc4` |
| [viridis, magma, inferno, plasma](https://github.com/BIDS/colormap) | Nathaniel J. Smith and Stefan van der Walt | CC0 1.0 | `colormaps.py` at `bc549477` |
| [cividis](https://github.com/pnnl/cmaputil) | Battelle Memorial Institute (Nuñez, Anderton and Renslow, PLoS ONE 2018) | BSD-style, Battelle | `colormaps/cividis.txt` at `a153df50` |
| [Scientific colour maps 8.0](https://doi.org/10.5281/zenodo.8409685) | Fabio Crameri | MIT | `cmcrameri/cmaps/*.txt` of [cmcrameri](https://github.com/callumrollo/cmcrameri) at `78f02a08` |
| [Okabe and Ito](https://jfly.uni-koeln.de/color/) | Masataka Okabe and Kei Ito, Color Universal Design (2008) | published values | the eight RGB values their page gives |

ColorBrewer's notice, which its licence asks to be kept: This product includes color
specifications and designs developed by Cynthia Brewer (http://colorbrewer.org/). Its
licence, beside the export the colours are read from, is copyright (c) 2002 Cynthia
Brewer, Mark Harrower, and The Pennsylvania State University; the palettes here are named
`brewer/<scheme>`, and nothing here is called ColorBrewer, which that licence reserves.

**The derived file changes how the colours are written, not the colours.** ColorBrewer's are
written as hex codes where its file writes `rgb()`; viridis's, cividis's and Crameri's as hex
codes where theirs write numbers from 0 to 1, rounded to 8 bits a channel. Beside each palette
the file records what this project's colour check says of it (`distinct`, `lightness`,
`lightness_kept`) and whether the collection calls the palette colour-blind friendly
(`claims_cvd`): as MetBrewer's, MoMAColors' and NatParksPalettes' files mark each palette, and
as the makers of viridis, cividis, Crameri's maps and Okabe and Ito's colours say of all of
theirs. Those fields are this project's. Two of MoMAColors'
palettes write one more position in their order than they have colours; the extra position
is dropped. MetBrewer's Tsimshian gives rank 1 twice and no rank 2, and is kept as written:
one colour of it is two, as `met.brewer` gives it. For anything but choosing a palette for a figure here, take the palettes from
their makers' packages, which also cite them as their makers ask.
