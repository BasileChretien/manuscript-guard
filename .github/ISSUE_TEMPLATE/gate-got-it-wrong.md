---
name: A gate got it wrong
about: A number it flagged that is fine, or a defect it let through
labels: gate
---

**Which direction**
- [ ] It flagged something that is not a defect
- [ ] It let a defect through  ← more useful

**The smallest text that shows it**

```markdown
paste the manuscript source, results fragment, or table cell here
```

**What manuscript-guard said** — the output of `manuscript-guard check`, or
`manuscript-guard explain <file>` if it is about how a number was classified.

**What it should have said, and why.** If this is a convention of your field rather than a
bug, say which field and where the convention is written down.

**Version** — `manuscript-guard --version`, and your OS and Python version.
