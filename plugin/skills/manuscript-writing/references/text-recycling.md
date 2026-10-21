# Words from your own earlier papers

Part of the manuscript-writing skill, read when `check` reports `recycled-text`,
`recycled-methods-cited`, `recycled-statement`, `recycled-quotation`,
`recycled-earlier-version` or `earlier-output-not-compared`.

The journal's similarity check (iThenticate) shows every run of words the manuscript shares
with a published paper, the authors' own included. G7 finds those runs first, on this
machine, in the earlier outputs `literature/related.yaml` lists as sharing authors with this
paper (`shares: [authors]`), each with a citation key and its own copy stored as
`literature/sources/<key>.pdf` (or `.txt`, `.html`). The copy is read here and sent nowhere.

What the norms say (the Text Recycling Research Project's best practices, 2021, and COPE's
guidelines for editors): a standard description may be reused in the Methods where the
earlier paper is cited; overlap in the Results, the Discussion or the conclusions is unlikely
to be acceptable; reuse of one's own preprint or conference abstract is commonly accepted
where it is disclosed, and a results paper repeats its protocol's methods; the journal's
policy decides.

| Code | What happened | What to do |
|---|---|---|
| `recycled-methods-cited` | the Methods repeat a description of the earlier paper and cite it in the paragraph | nothing in the text; say in the covering letter that the description is reused, and from where |
| `recycled-text` | a passage of twelve words or more repeats the earlier paper anywhere else, or in the Methods without citing it | in the Methods, cite the paper in that paragraph or rewrite; elsewhere, write the passage afresh from what this paper found |
| `recycled-statement` | a funding, ethics, competing-interests or similar statement repeats the earlier paper's | keep it if it is still true of this paper; a journal expects it to be the same |
| `recycled-quotation` | the earlier paper is quoted, in quotation marks | keep it if the quotation is the point, and cite the paper there |
| `recycled-earlier-version` | the manuscript repeats a preprint, an abstract or a protocol of this same study | name it in the covering letter; check the journal's policy on preprints |
| `earlier-output-not-compared` | an earlier output has no citation key, or no stored copy that can be read | store the authors' own copy under its key |

Write afresh from a blank line, not by changing words in the old sentence: a synonym here and
there leaves the passage in the similarity report, and the check still finds it. Ask the
author before rewriting a passage of the Discussion: the claim is theirs, and the new
sentence has to say what this paper found, not what the last one did.
