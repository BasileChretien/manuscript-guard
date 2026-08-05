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


class SelectionError(Exception):
    """A selector names nothing, or names something that has no single answer."""


def label(item: Unbound, root: Path) -> str:
    """How a suggestion is named on the command line: `main.md:42`.

    Positional rather than ordinal. Numbering the list 1..n and taking `--apply 3` would mean
    that editing the file between reading the list and accepting a suggestion applies a
    different one — and each of these writes a binding that changes what the paper says.
    """
    try:
        where = item.path.relative_to(root).as_posix()
    except ValueError:
        where = item.path.name
    return f"{where}:{item.line}"


def select(items: list[Unbound], wanted: list[str], root: Path) -> list[Unbound]:
    """The suggestions named by `--apply main.md:42 …`, or every certain one if none is named.

    An unmatched selector is an error rather than a silent no-op. The author has said what
    they want applied; applying less than that without saying so is exactly the quiet
    divergence between intention and file that this command exists to close.
    """
    if not wanted:
        return [item for item in items if item.certain]

    by_label: dict[str, list[Unbound]] = {}
    for item in items:
        by_label.setdefault(label(item, root), []).append(item)

    chosen: list[Unbound] = []
    for selector in wanted:
        found = by_label.get(selector)
        if not found:
            near = ", ".join(sorted(by_label)[:6]) or "none"
            raise SelectionError(f"nothing to bind at {selector!r}. Suggestions here: {near}")
        undecided = [item for item in found if not item.certain]
        if undecided:
            listed = ", ".join(f"{{{{{key}}}}}" for key in undecided[0].candidates) or "nothing"
            raise SelectionError(
                f"{selector} has no single answer ({listed}), so it cannot be applied. "
                f"Write the binding you mean by hand"
            )
        chosen += found
    return chosen


def apply(items: list[Unbound]) -> tuple[list[tuple[Unbound, str]], list[Unbound]]:
    """Replace the given literals with their bindings. Returns what changed, and what did not.

    Rewritten from the end of each file backwards, by offset. Replacing by text search
    would rewrite every occurrence of a string that may legitimately appear elsewhere —
    and in a paper full of 1s and 2s, "replace 1 with a binding" is a catastrophe.

    Takes the items to apply rather than choosing them here, so accepting eight suggestions
    out of ten is one command. It used to take everything `unbound()` found and replace every
    unambiguous one, which made a single wrong suggestion — a `12` that happens to equal a
    published value while meaning twelve months of follow-up — something an author could only
    avoid by declining the other nine.
    """
    applied: list[tuple[Unbound, str]] = []
    accepted = {(item.path, item.start) for item in items if item.certain}
    by_file: dict[Path, list[Unbound]] = {}
    for item in items:
        if item.certain:
            by_file.setdefault(item.path, []).append(item)

    for path, entries in by_file.items():
        text = path.read_text(encoding="utf-8")
        for item in sorted(entries, key=lambda i: i.start, reverse=True):
            binding = f"{{{{{item.certain}}}}}"
            text = f"{text[: item.start]}{binding}{text[item.end :]}"
            applied.append((item, binding))
        path.write_text(text, encoding="utf-8", newline="\n")

    applied.sort(key=lambda pair: (pair[0].path.name, pair[0].start))
    return applied, [item for item in items if (item.path, item.start) not in accepted]
