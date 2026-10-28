"""The parts of `audit` that need no outputs (DESIGN.md, "Auditing existing papers, and saying
what the audit is worth"): a LaTeX paper read through its include tree (`latex`), the gates
that read the words, G6 and G14, run on a project made for the paper (`gates`), the reference
list counted and, when asked, looked up (`references`), and the report in sections
(`report`). `manuscript_guard.audit` reads the numbers and compares them with the outputs."""
