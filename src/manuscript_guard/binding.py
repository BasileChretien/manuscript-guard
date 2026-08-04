"""What to do about a number the gate refused.

`check` says a number is unbound. The annotated copy colours it red. Neither tells an author
what to type next, and the four routes out — emit it from the analysis, record it from the
literature, attest it, or declare it a convention — are not equally likely: usually the
number is already in `results/` and the author simply typed it instead of binding it.

So this looks for that case. If a literal equals a value the analysis published, it says so
and offers to make the replacement.

**That is a suggestion, never evidence.** The gate deliberately refuses to accept a number
because it *matches* one — nothing may pass by coincidence, which is the whole reason a
results-derived number cannot be a literal at all. Offering a match as a fix is a different
act: the author accepts it, the literal becomes a binding, and the binding is then checked
structurally like every other. The value comparison decides what to suggest, never what is
true.

And where two keys share a display the suggestion is refused rather than guessed. That is
the same collision that makes a lone table cell weaker than a composed one: with two
candidates, matching on the value cannot say which was meant, and quietly picking the first
would write the wrong binding into the manuscript.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.values import Value
from manuscript_guard.gates.numbers import _hint_for, source_files
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import chain_at, heading_index
from manuscript_guard.text.tokens import find_atoms


@dataclass(frozen=True)
class Unbound:
    """One number the gate refused, and what could be done about it."""

    path: Path
    line: int
    start: int
    end: int
    text: str
    hint: str
    candidates: tuple[str, ...]

    @property
    def certain(self) -> str | None:
        """The one key this could be replaced by, when there is exactly one."""
        return self.candidates[0] if len(self.candidates) == 1 else None


def unbound(project: Project, namespace: dict[str, Value]) -> list[Unbound]:
    """Every number in the manuscript that nothing accounts for, with its way out."""
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)

    # Display strings first, then the same with separators stripped, so a literal typed
    # `41200` still finds a value displayed `41,200`.
    by_display: dict[str, list[str]] = {}
    for key, value in namespace.items():
        for form in {value.display, value.display.replace(",", "").replace(" ", "")}:
            if form:
                by_display.setdefault(form, []).append(key)

    found: list[Unbound] = []
    for path in source_files(project.path("manuscript")):
        text = path.read_text(encoding="utf-8")
        headings = heading_index(text)
        scan = classifier.scan(text)
        for atom in find_atoms(text, mask(text)):
            if classifier.classify(atom, chain_at(headings, atom.start), scan).kind != UNCLASSIFIED:
                continue
            plain = atom.text.replace(",", "").replace(" ", "")
            candidates = sorted({*by_display.get(atom.text, ()), *by_display.get(plain, ())})
            found.append(
                Unbound(
                    path=path,
                    line=atom.line,
                    start=atom.start,
                    end=atom.end,
                    text=atom.text,
                    hint=_hint_for(atom),
                    candidates=tuple(candidates),
                )
            )
    return found


def routes(item: Unbound) -> list[str]:
    """The ways to give this number a source, likeliest first."""
    out: list[str] = []
    if item.certain:
        out.append(f"replace it with {{{{{item.certain}}}}}  — `bind --apply` does this")
    elif item.candidates:
        listed = ", ".join(f"{{{{{key}}}}}" for key in item.candidates)
        out.append(
            f"{len(item.candidates)} published values read the same: {listed}. "
            f"Pick one by hand — guessing would write the wrong binding"
        )
    out += [
        f'emit it from the analysis:  em.value("<key>", {item.text})  '
        f"then write {{{{results.<key>}}}}",
        "record it from a source:    add an entry to literature/ledger.yaml, "
        "then write {{lit.<key>}}",
        "attest it:                  add an entry to literature/attested.yaml if the "
        "source cannot be stored",
        "declare it a convention:    add it to `conventions:` in paper.yaml with a reason",
    ]
    return out


def apply(items: list[Unbound]) -> tuple[int, list[Unbound]]:
    """Replace every unambiguous literal with its binding. Returns how many, and the rest.

    Rewritten from the end of each file backwards, by offset. Replacing by text search
    would rewrite every occurrence of a string that may legitimately appear elsewhere —
    and in a paper full of 1s and 2s, "replace 1 with a binding" is a catastrophe.
    """
    replaced = 0
    remaining = [item for item in items if not item.certain]
    by_file: dict[Path, list[Unbound]] = {}
    for item in items:
        if item.certain:
            by_file.setdefault(item.path, []).append(item)

    for path, entries in by_file.items():
        text = path.read_text(encoding="utf-8")
        for item in sorted(entries, key=lambda i: i.start, reverse=True):
            text = f"{text[: item.start]}{{{{{item.certain}}}}}{text[item.end :]}"
            replaced += 1
        path.write_text(text, encoding="utf-8", newline="\n")
    return replaced, remaining
