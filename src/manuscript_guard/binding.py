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
from dataclasses import replace as _replaced
from pathlib import Path

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.values import Value
from manuscript_guard.gates.numbers import _hint_for, _is_latex, source_files
from manuscript_guard.text.masking import mask
from manuscript_guard.text.sections import chains_at, footnote_index, heading_index
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
    #: Whether the file is a LaTeX manuscript's, where a binding is `\\mg{key}` (step 12).
    latex: bool = False
    #: Why the one key that reads the same is not offered, where the reader would refuse the
    #: binding written there: in a siunitx command, or past the file's first refusal. The
    #: manuscript's folder, to read the edit in, for a LaTeX file (round 1 of step 12).
    not_offered: str = ""
    manuscript: Path | None = None

    @property
    def certain(self) -> str | None:
        """The one key this could be replaced by, when there is exactly one."""
        if self.not_offered:
            return None
        return self.candidates[0] if len(self.candidates) == 1 else None

    def binding(self, key: str) -> str:
        """`key` as a binding is written in this file."""
        return f"\\mg{{{key}}}" if self.latex else f"{{{{{key}}}}}"


def unbound(project: Project, namespace: dict[str, Value], *,
            offers: bool = True) -> list[Unbound]:  # fmt: skip
    """Every number in the manuscript that nothing accounts for, with its way out. Without
    `offers`, a LaTeX binding is not read in its file to see whether it can be offered, which
    the note on a saved file does not need (round 2 of step 12)."""
    classifier = Classifier.load(project.extra_conventions, project.extra_terms)

    # Display strings first, then the same with separators stripped, so a literal typed
    # `41200` still finds a value displayed `41,200`.
    by_display: dict[str, list[str]] = {}
    for key, value in namespace.items():
        for form in {value.display, value.display.replace(",", "").replace(" ", "")}:
            if form:
                by_display.setdefault(form, []).append(key)

    found: list[Unbound] = []
    if _is_latex(project):
        return _latex_unbound(project, classifier, by_display, offers=offers)
    for path in source_files(project.path("manuscript")):
        text = read_text(path)
        headings = heading_index(text)
        notes = footnote_index(text)
        scan = classifier.scan(text)
        for atom in find_atoms(text, mask(text)):
            chains = chains_at(headings, notes, atom.start)
            if classifier.classify_under(atom, chains, scan).kind != UNCLASSIFIED:
                continue
            found.append(_found(path, atom, by_display, _hint_for(atom)))
    return found


def _latex_unbound(project: Project, classifier: Classifier, by_display: dict[str, list[str]],
                   *, offers: bool = True) -> list[Unbound]:  # fmt: skip
    """Each file of a LaTeX manuscript as G2 reads it, through the include tree, with its
    rules' scan. A number with one key that reads the same is offered only where the reader
    reads the binding written there (round 1 of step 12)."""
    from manuscript_guard.gates.numbers import _latex_read
    from manuscript_guard.text.latex import views as latex_views

    manuscript = project.path("manuscript")
    found: list[Unbound] = []
    for file in latex_views.files(manuscript):
        read = _latex_read(file)
        refused = file.source.reading.refusals
        stop = refused[0].offset if refused else None
        scan = read.scan(classifier)
        for atom in find_atoms(read.text, read.masked):
            if classifier.classify_under(atom, read.chains(atom.start), scan).kind != UNCLASSIFIED:
                continue
            item = _found(read.path, atom, by_display, read.spell(_hint_for(atom)), latex=True,
                          manuscript=manuscript)  # fmt: skip
            if item.certain is None:
                found.append(item)
                continue
            if stop is not None and atom.start >= stop:
                why = ("it stands past the file's first refusal, where the reader reads the "
                       "file as typed")  # fmt: skip
            elif offers and not _reads(item, read.text):
                why = "the reader would refuse it there, as it refuses one in siunitx"
            else:
                why = ""
            found.append(_replaced(item, not_offered=why) if why else item)
    return found


def _found(path: Path, atom, by_display: dict[str, list[str]], hint: str, *,
           latex: bool = False, manuscript: Path | None = None) -> Unbound:  # fmt: skip
    """An unbound number, with the published values that read as it does."""
    plain = atom.text.replace(",", "").replace(" ", "")
    candidates = sorted({*by_display.get(atom.text, ()), *by_display.get(plain, ())})
    return Unbound(path=path, line=atom.line, start=atom.start, end=atom.end, text=atom.text,
                   hint=hint, candidates=tuple(candidates), latex=latex,
                   manuscript=manuscript)  # fmt: skip


def _reads(item: Unbound, text: str) -> bool:
    """Whether the reader reads `text` with `item`'s binding written in it as it reads it
    without: its file's first refusal, if it has one, no earlier, read in the include tree
    with the context it is input in (round 1 of step 12)."""
    binding = item.binding(item.candidates[0])
    changed = f"{text[: item.start]}{binding}{text[item.end :]}"
    before = _first_refusal(item, text)
    after = _first_refusal(item, changed)
    if before is None:
        return after is None
    # A refusal of the tree above the number, an `\\input` of a file set aside, stays where
    # it is; one below it moves with the binding (round 2 of step 12).
    if before < item.start:
        return after == before
    return after == before + len(binding) - (item.end - item.start)


def _first_refusal(item: Unbound, text: str) -> int | None:
    """Where the reader first refuses `item`'s file holding `text`, read in its document."""
    from manuscript_guard.gates.numbers import is_supplementary
    from manuscript_guard.text.latex.structure import (
        ENTRY,
        SUPPLEMENT_ENTRY,
        read_document,
        read_tree,
    )

    manuscript = item.manuscript
    supplementary = is_supplementary(manuscript, item.path)
    document = read_document(manuscript, supplementary=supplementary)
    relative = item.path.resolve().relative_to(manuscript.resolve()).as_posix()
    files = {source.path: source.text for source in document.sources
             if not source.path.lower().endswith(".sty")}  # fmt: skip
    packages = {source.path: source.text for source in document.sources
                if source.path.lower().endswith(".sty")}  # fmt: skip
    (packages if relative in packages else files)[relative] = text
    tree = read_tree(files, SUPPLEMENT_ENTRY if supplementary else ENTRY, packages=packages)
    return next((refusal.offset for path, refusal in tree.refusals if path == relative), None)


def typed_pointers(project: Project) -> list[Unbound]:
    """Each typed pointer to a table or a figure the document numbers, with the binding that
    prints it as it reads now: "Table 2" becomes `{{ref.table.<key>}}`, and in a list
    ("Tables 1 and 2") each number becomes `{{num.table.<key>}}`, its words kept.

    Offered only where the binding prints what is typed, character for character, so that
    accepting one changes no word of the paper: "Supplementary Table 1" under the form
    "Table S{n}" would print "S1", and is not offered. Nor is a range that names a table it
    does not write, "Tables 1-3", whose 2 no binding could stand for. A pointer to a kind the
    build cannot number (`crossref`) is not offered, nor one that points at nothing.
    """
    from manuscript_guard.crossref import NUMBER, Display, number_of
    from manuscript_guard.gates import pointers

    numbers, files = pointers._count(project)
    by_number = {
        (found.supplementary, found.kind, found.number): found
        for placed in numbers.placed.values()
        if len(placed) == 1
        for found in placed
    }
    offered: list[Unbound] = []
    for path, text in files:
        shown = pointers._scanned(text)
        for match in pointers._POINTER.finditer(shown):
            read = pointers._numbers(match)
            if any(at is None for _s, _n, at in read):
                continue
            kind = pointers._kind(match["kind"])
            elsewhere = bool(match["supp"] or match["e"] or match["after"])
            whole = " ".join(match.group().split())
            for s, number, at in read:
                found = by_number.get((elsewhere or s, kind, number))
                if not isinstance(found, Display) or numbers.uncounted(
                    found.supplementary, kind
                ):
                    continue
                form = numbers.forms[found.supplementary, kind]
                if len(read) == 1 and whole == form.replace(NUMBER, str(number)):
                    start, end, binding = match.start(), match.end(), "ref"
                else:
                    start = at - (1 if s else 0)
                    end = at + len(str(number))
                    if shown[start:end] != number_of(form, number):
                        continue
                    binding = "num"
                offered.append(
                    Unbound(
                        path=path,
                        line=shown.count("\n", 0, start) + 1,
                        start=start,
                        end=end,
                        text=text[start:end],
                        hint=f"{found.binding} is {kind} {shown[start:end]} of "
                        f"{'the supplement' if found.supplementary else 'the main text'}",
                        candidates=(f"{binding}.{kind}.{found.key}",),
                    )
                )
    return offered


def routes(item: Unbound) -> list[str]:
    """The ways to give this number a source, likeliest first."""
    out: list[str] = []
    if item.not_offered:
        out.append(f"{item.binding(item.candidates[0])} reads the same, but {item.not_offered}: "
                   "write it by hand where a binding can stand")  # fmt: skip
    elif item.certain:
        out.append(f"replace it with {item.binding(item.certain)}  — `bind --apply` does this")
    elif item.candidates:
        listed = ", ".join(item.binding(key) for key in item.candidates)
        out.append(
            f"{len(item.candidates)} published values read the same: {listed}. "
            f"Pick one by hand — guessing would write the wrong binding"
        )
    out += [
        f'emit it from the analysis:  em.value("<key>", {item.text})  '
        f"then write {item.binding('results.<key>')}",
        "record it from a source:    add an entry to literature/ledger.yaml, "
        f"then write {item.binding('lit.<key>')}",
        "attest it:                  add an entry to literature/attested.yaml if the "
        "source cannot be stored",
        "declare it a convention:    add it to `conventions:` in paper.yaml with a reason",
    ]
    return out


class SelectionError(Exception):
    """A selector names nothing, or names something that has no single answer."""


def label(item: Unbound, root: Path) -> str:
    """How a suggestion is named on the command line: `manuscript/main.md:42`.

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
    """The suggestions named by `--only manuscript/main.md:42 …`, or every certain one.

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
        refused = next((item for item in found if item.not_offered), None)
        if refused is not None:
            raise SelectionError(f"{selector} is not applied: {refused.not_offered}. Write the "
                                 "binding by hand where a binding can stand")  # fmt: skip
        undecided = [item for item in found if not item.certain]
        if undecided:
            listed = ", ".join(undecided[0].binding(key)
                               for key in undecided[0].candidates) or "nothing"  # fmt: skip
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
        text = read_text(path)
        for item in sorted(entries, key=lambda i: i.start, reverse=True):
            binding = item.binding(item.certain)
            # A LaTeX binding the reader would refuse is not written, each read with those
            # written after it in the file (round 1 of step 12).
            if item.latex and not _reads(item, text):
                accepted.discard((item.path, item.start))
                continue
            text = f"{text[: item.start]}{binding}{text[item.end :]}"
            applied.append((item, binding))
        path.write_text(text, encoding="utf-8", newline="\n")

    applied.sort(key=lambda pair: (pair[0].path.name, pair[0].start))
    return applied, [item for item in items if (item.path, item.start) not in accepted]

