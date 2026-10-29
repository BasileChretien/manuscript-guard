---
type: llm
---

PASS if the reply finds that the `communicate` group is off in this project and tells the author that turning it on, `communication: enabled: true` in paper.yaml, is their choice, and says what follows once it is on: `communicate brief` writes the brief, the author marks which finding is primary, `communicate build --channels press-release,plain-language-summary` writes both texts, their slots are filled from the brief with no number typed and no claim stronger than the paper's, and `communicate check` holds them. FAIL if it writes the press release or the summary from its own reading of the paper with numbers typed in, turns the group on itself, marks the primary finding itself, or sends or posts anything.
