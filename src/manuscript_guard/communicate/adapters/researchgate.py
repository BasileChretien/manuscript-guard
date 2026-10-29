"""ResearchGate: the steps, by hand.

ResearchGate has no interface a tool may post through, so `communicate publish researchgate`
prints the steps (`guides.researchgate`, the same as `communication/guides/
researchgate-steps.md`), and `--done` records that the author took them, with the day and the
digest of the text as it stood, in `communication/published/researchgate.yaml`. Nothing is
sent.
"""

from __future__ import annotations


def steps(project) -> str:
    from manuscript_guard.communicate.guides import researchgate

    return researchgate(project)
