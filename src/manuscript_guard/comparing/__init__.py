"""`compare OLD NEW`: two versions of a manuscript side by side, for an editor or a referee
reading a revision (DESIGN.md, "A revision read beside the version before it").

Both versions are read as `audit` reads a paper (`versions`), and set side by side
(`differences`): the sections matched by their titles, the tables by their label and caption
and then cell by cell, the numbers, citation keys and bindings gone, new or changed, and the
sentences whose claim moved. The new version is audited, each finding marked new in it or
standing in the version before (`report`). A response letter's quotations are looked for in
both versions, and the tables, figures and sections it names are said to have changed or not;
a referee's own comments are matched to the new version only by what they quote or name
(`letters`). Nothing here says whether a comment was answered, and nothing is sent.
"""

#: What `compare` says on stderr every time it runs: the manuscript is someone else's, sent
#: in confidence, and the report quotes it (decision 5 of the editor and referee layer).
NOTICE = (
    "manuscript-guard: a manuscript sent to you in confidence is read here and nothing is "
    "sent; the report quotes it, so keep the report out of a chat with a model and away from "
    "an agent"
)
