"""What makes a table cell trustworthy, in one place.

The rule that every number in an emitted table is either a value this analysis published,
a recognised convention, or a cell the emitter composed itself used to live inside the
Python emitter and nowhere else. That was fine while Python was the only language that
could emit a table, and stopped being fine the moment the R package grew `table()`: a rule
enforced in one emitter is a rule an author steps around by switching language, and the
results fragment is supposed to be a cross-language contract.

So the check moved here, reads a fragment rather than an emitter's private state, and runs
twice — once at emit time, where it raises with a message about the call you just made, and
once in G2, where it reports findings about whatever is on disk whoever wrote it. The second
is what makes the guarantee verifiable instead of trusted: a fragment written by hand, or by
an emitter in a language nobody has written yet, is judged the same way.

For that to be possible the fragment has to say which cells were composed, because a
composed cell and a typed one are the same characters by the time anyone reads the file.
That is the `composed` block, and it carries each template's literal text so the part the
script typed can still be checked.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The heading chain claimed for table text. A table is not a Methods section and not a
#: figure legend, so `methods_only` rules must not apply to what is written in one.
TABLE_SECTION = ("Table",)

#: A composed cell whose row is this is a column header. Fragments say `header`; this is the
#: internal key, kept off the wire.
HEADER_ROW = -2
CAPTION_ROW = -1


@dataclass(frozen=True)
class Problem:
    """One thing wrong with one cell."""

    where: str
    text: str
    code: str
    message: str


def composition_of(spec: dict) -> dict[tuple[int, int], dict]:
    """The `(row, column) -> entry` map a fragment records.

    A header entry omits `row`. Anything malformed is dropped rather than guessed at: an
    unreadable claim of composition must not become an exemption, which would make a
    corrupt fragment safer than a correct one.
    """
    found: dict[tuple[int, int], dict] = {}
    for entry in spec.get("composed") or ():
        if not isinstance(entry, dict) or not isinstance(entry.get("column"), int):
            continue
        row = entry.get("row", HEADER_ROW)
        if not isinstance(row, int):
            continue
        found[(row, entry["column"])] = entry
    return found


def rebuilt(entry: dict) -> str | None:
    """The cell this entry claims to describe, rebuilt from its own template and parts.

    The exemption has to prove itself. Checking the *declared* literal instead of the cell
    meant an entry with an empty literal exempted whatever the cell actually said: zero
    atoms were scanned, so a cell reading "True mortality rate: 4281003.55% (fabricated)"
    passed with nothing reported. That was reachable without touching a fragment, by
    importing `Verbatim` — whose own docstring claimed a script could not build one.

    Rebuilding closes it. A composed cell is accepted only when the emitter's template,
    filled with the emitter's own parts, is exactly the text on the page; anything else is
    a claim of composition that does not describe the cell it is attached to.
    """
    template = entry.get("template")
    if not isinstance(template, str):
        return None
    parts = [str(part) for part in entry.get("parts") or ()]
    if template.count("{}") != len(parts):
        return None
    out = template.split("{}")
    return "".join(piece + part for piece, part in zip(out, [*parts, ""], strict=True))


def _joined_codes(code_lists: dict | None, key: str, row: int) -> str | None:
    entries = (code_lists or {}).get(key)
    if not isinstance(entries, list) or not 0 <= row < len(entries):
        return None
    codes = entries[row].get("codes") if isinstance(entries[row], dict) else None
    return ", ".join(str(code) for code in codes) if isinstance(codes, list) else None


def places_in(key: str, spec: dict) -> list[tuple[str, str, int, int]]:
    """Every piece of text a table renders: caption, headers, cells.

    Captions and column headers are part of the table and were once looked at by nothing: a
    caption reading "the reporting odds ratio of 12.34 (95% CI 8.00 to 19.00)" and a header
    reading "Hepatic injury (n = 9999)" both went into the document unchecked.
    """
    places = [(f"caption of table {key!r}", spec.get("caption") or "", CAPTION_ROW, -1)]
    places += [
        (f"table {key!r} column {column} header", str(text), HEADER_ROW, column)
        for column, text in enumerate(spec.get("columns") or ())
    ]
    places += [
        (f"table {key!r} row {row} column {column}", str(cell), row, column)
        for row, cells in enumerate(spec.get("rows") or ())
        for column, cell in enumerate(cells)
    ]
    return places


def problems_in(
    key: str, spec: dict, known: set[str], classifier, code_lists: dict | None = None
) -> list[Problem]:
    """Every claim in one table that nothing accounts for.

    `code_lists` is the fragment's published code lists, which is the only independent
    anchor a verbatim cell has: it holds no number the emitter derived, so rebuilding it
    from its own declared part proves nothing at all.
    """
    from manuscript_guard.classify import UNCLASSIFIED
    from manuscript_guard.text.masking import mask
    from manuscript_guard.text.tokens import find_atoms

    composed = composition_of(spec)
    found: list[Problem] = []

    for where, cell, row, column in places_in(key, spec):
        # A cell the emitter composed is checked on its template, not its result.
        #
        # Every part of a composed cell went through `derive_display`, so the numbers in it
        # are traceable by construction — but the rendered text is not, because a template
        # can glue them into something the tokenizer reads as one atom. `{}/{}` over 77 and
        # 412 renders `77/412`, which is neither "77" nor "412", so the commonest cell
        # format in medicine could not be emitted at all.
        #
        # What still has to be checked is the literal part of the template, since that is
        # the part the script typed: `"{} (n = 412)"` would otherwise smuggle a count in
        # under the exemption.
        entry = composed.get((row, column))
        was_composed = False
        text = cell
        if entry is not None and entry.get("codes"):
            # A code list cell. Its content is a join of the codes the analysis selected on,
            # so it is checked against those and nothing else. Rebuilding it from its own
            # declared part would prove nothing — the part *is* the text — which is how
            # arbitrary prose passed inside a verbatim cell.
            expected = _joined_codes(code_lists, key, row)
            if expected is not None and expected == cell:
                continue
            found.append(
                Problem(
                    where=where,
                    text=cell,
                    code="code-list-does-not-match",
                    message=f"{cell!r} is recorded as a code list cell, but the fragment's "
                    f"code list for this row is {expected!r}. A cell claiming to be a list "
                    f"of codes must be that list",
                )
            )
            continue
        if entry is not None:
            claimed = rebuilt(entry)
            if claimed == cell:
                # Verified: the cell is this template filled with these parts, so the only
                # text left to judge is the template's own literal wording.
                was_composed = True
                text = str(entry.get("template", "")).replace("{}", " ")
            else:
                found.append(
                    Problem(
                        where=where,
                        text=cell,
                        code="composition-does-not-match",
                        message=f"the fragment says {cell!r} was composed, but the template "
                        f"and parts it records rebuild to {claimed!r}. A claim of "
                        f"composition that does not describe the cell it is attached to is "
                        f"not an exemption",
                    )
                )
                continue

        atoms = find_atoms(text, mask(text))
        scan = classifier.scan(text)

        # Two or more claims in one cell must have been composed, not typed.
        #
        # Membership of the emitted set is not enough on its own: it says each number came
        # from this analysis, and nothing about which is which. "ROR 5.12 (95% CI 3.84 to
        # 2.89)" passed when 5.12, 3.84 and 2.89 were all emitted — a point estimate and
        # both bounds, transposed. One number is left as a set-membership check: a lone "77"
        # has nowhere to be transposed to, and demanding a composed cell for every
        # single-value cell would be friction with nothing behind it.
        claims = [
            atom
            for atom in atoms
            if classifier.classify(atom, TABLE_SECTION, scan).kind == UNCLASSIFIED
        ]
        if len(claims) > 1 and not was_composed:
            found.append(
                Problem(
                    where=where,
                    text=cell,
                    code="typed-composite-cell",
                    message=f"{cell!r} carries several numbers that were typed rather than "
                    f"composed. Each being an emitted value says nothing about which is "
                    f"which — a point estimate and its bounds can be transposed and still "
                    f'pass. Build it with a composed cell: cell("{{}} ({{}} to {{}})", '
                    f"point, low, high)",
                )
            )
            continue

        for atom in atoms:
            if atom.text in known or atom.text.replace(",", "") in known:
                continue
            # A results table is not a figure legend. Classifying with no section at all let
            # every `methods_only` rule apply, so `p < 0.001` typed straight into a cell was
            # accepted as a pre-specified threshold — in the one place a *reported* p-value
            # is most likely to be written.
            if classifier.classify(atom, TABLE_SECTION, scan).kind != UNCLASSIFIED:
                continue
            found.append(
                Problem(
                    where=where,
                    text=cell,
                    code="unemitted-table-number",
                    message=f"{atom.text!r} in {cell!r} is not a value this analysis "
                    f"emitted. Build it with a composed cell so the emitter formats it, or "
                    f"emit {atom.text} as a value of its own",
                )
            )
    return found


def displays_of(document: dict) -> set[str]:
    """Every display string a fragment published as a *value*.

    Composed cells contribute nothing here, and that is the fix for a real leak: folding
    `composed[*].parts` into one project-wide set meant a single entry anywhere — in another
    table, in another fragment, in a table with no rows at all — whitelisted its strings
    everywhere. A phantom entry declaring `parts: ["777777"]` made an unrelated, unmarked
    cell reading "777777" pass. A composed cell's parts now excuse that cell and nothing
    else, which is what `rebuilt` verifies them against.
    """
    known = {
        str(spec.get("display", ""))
        for spec in (document.get("values") or {}).values()
        if isinstance(spec, dict)
    }
    known.discard("")
    return known | {shown.replace(",", "") for shown in known}
