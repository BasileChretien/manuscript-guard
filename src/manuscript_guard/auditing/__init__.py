"""The parts of `audit` that need no outputs (DESIGN.md, "Auditing existing papers, and saying
what the audit is worth"): a LaTeX paper read through its include tree (`latex`), the gates
that read the words, G6 and G14, run on a project made for the paper (`gates`), the reference
list counted and, when asked, looked up (`references`), and the report in sections
(`report`). `manuscript_guard.audit` reads the numbers and compares them with the outputs.

For an editor or a referee, who did not write the paper (DESIGN.md, "A paper read by its
editor or a referee"): G4 held to the journal's profile and the blinding check (`journal`),
what a Word file holds besides its text (`document`), the causal words of an observational
study (`causal`), each citation beside its sentence (`cited`, read through `sentences`), and
the references of the authors' and of the journal (`selfcite`). A PDF manuscript is read
through `pdftotext`, each place in it a page and a line (`pdf`)."""

#: The options that make `audit` an editor's or a referee's reading of a paper someone else
#: wrote. With one, the audit says the manuscript is not to reach a model (`NOTICE`), and the
#: hook asks the person before an agent runs it (`hooks._reads_in_confidence`).
READER_FLAGS = ("--journal", "--authors", "--design", "--cited")

#: What the audit says on stderr when a reader flag is given.
NOTICE = (
    "manuscript-guard: a manuscript sent to you in confidence is read here and nothing is sent "
    "(--lookup sends its DOIs and PMIDs); the report quotes it, so keep the report out of a "
    "chat with a model and away from an agent"
)
