# A cited reference that G7 cannot find

Part of the manuscript-writing skill, read when G7 reports a reference with no DOI or PMID
that `lookup` searched for by its title.

`lookup` searches PubMed, Crossref and OpenAlex by its title for a reference with no DOI and
no PMID, and G7 reads the answer:

| Code | What it means | What to do |
|---|---|---|
| `reference-found` (a note) | a registry has the work, with the identifier given | the author adds that DOI or PMID in Zotero, then `sync-bib` and `lookup` |
| `reference-not-found` | no registry has a work of that title and year | find the work and its identifier; if it cannot be found, say so to the author and do not cite it |
| `reference-authors-disjoint` | the title is real, and none of the cited people wrote it | the entry's authors are another work's, or made up: correct them from the registry's record |
| `reference-authors-differ` (a warning) | some cited people, or the first, are not on the record | check against the version cited |

Never add a DOI, a PMID or authors you did not read from a registry's record of the work.
A real work no registry indexes, an internal report or a regional journal, is the author's
to declare under `lookup.not_indexed` in `paper.yaml`, with the reason; do not write that
entry yourself to make a finding go away.
