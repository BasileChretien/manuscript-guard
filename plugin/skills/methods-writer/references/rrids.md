# RRIDs: naming the resources the Methods used

Part of the methods-writer skill, read when the Methods name an antibody, a cell line, an
organism, a plasmid or a tool, and when `check` reports `rrid-not-looked-up`,
`rrid-unresolved` or `cell-line-problematic`.

Cite each resource by its RRID, typed as the resolver writes it:
`Anti-NeuN (Millipore Cat# MAB377, RRID:AB_2298772)`. Then run
`manuscript-guard lookup --resources`, which asks the RRID resolver about each one, and
Cellosaurus about a cell line, and keeps the answers in `literature/rrids/`.

- `rrid-not-looked-up`: there is no record. An answer that did not come is not recorded, and
  the next run asks again.
- `rrid-unresolved`: the resolver does not know the RRID. Check it with the author against
  the resource's own page; never guess one.
- `cell-line-problematic`: Cellosaurus marks the line problematic, and the finding quotes
  why. That is the author's to answer: say in the Methods how the line was authenticated, or
  change the line.

Only the RRIDs the manuscript types are checked. Ask the author for a resource's RRID rather
than look one up and type it yourself.
