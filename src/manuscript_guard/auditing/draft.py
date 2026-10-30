"""`--report-draft FILE.md` of `audit` and of `compare`: the findings and their places as the
start of a referee's or an editor's report, in Markdown, with no opinion in it.

Its first line says so (`FIRST`). Then, in this order: what was read and what was not checked;
the exact findings, those `--strict` counts; the further findings, by section; the references;
language and notation (G6 and G14, grouped by code); and the checks that ran and found nothing,
each with what it read, "read none" where it read nothing. It never says a paper has no
problems: a check that found nothing says what it read. The same report gives the same bytes:
nothing reads a clock, and the file is written once (mode "x"), never over one there.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.auditing import report as sections
from manuscript_guard.auditing.report import Item
from manuscript_guard.findings import INFO

FIRST = (f"Draft from manuscript-guard {__version__}: findings and their places only; the "
         "judgement is yours.")  # fmt: skip
#: The sections a finding goes to the References or the Language part of the draft from.
REFERENCE_SECTIONS = frozenset({sections.REFERENCES, sections.CITED, sections.SELF_CITATION})
LANGUAGE_SECTIONS = frozenset({sections.WRITING, sections.LANGUAGE})
#: The notes "What was not checked" says, left out of the further findings.
UNCHECKED_CODES = frozenset({"journal-not-checked", "abstract-not-compared"})
#: The places listed for one code under Language and notation.
FIRST_PLACES = 3
#: What a draft always lists as not checked, whatever was given.
NEVER_CHECKED = (
    "The reporting checklist (CONSORT, STROBE and the rest): it needs the authors' completed "
    "checklist, which a manuscript does not hold.",
    "The models: the model checks read the analysis's model cards, which a manuscript does not "
    "hold.",
    "Citations by author and year: they are not held to the reference list, and a citation's "
    "number is held to it only in a numbered list.",
)
_KINDS = {".docx": "Word", ".md": "Markdown", ".markdown": "Markdown", ".txt": "plain text",
          ".tex": "LaTeX", ".pdf": "PDF", ".svg": "SVG figure"}  # fmt: skip

Show = Callable[[Path], str]


def refused(target: Path, given: Iterable[Path]) -> str:
    """Why the draft cannot be written to `target`, or ""."""
    if target.suffix.lower() not in (".md", ".markdown"):
        return f"--report-draft writes Markdown: name a file ending .md, not {target.name}"
    if target.exists():
        return (f"--report-draft {target}: the file is there already, and may hold your own "
                "words; name another, or move it away")  # fmt: skip
    if not target.parent.is_dir():
        return f"--report-draft {target}: its folder does not exist"
    if any(target.resolve() == path.resolve() for path in given):
        return f"--report-draft {target}: that is a file the command reads"
    return ""


def write(target: Path, text: str) -> None:
    """Write the draft, never over a file: `FileExistsError` where one appeared meanwhile."""
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _n(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


def _code(text: str) -> str:
    """`text` as inline code, its fence longer than any run of backticks in it."""
    text = " ".join(text.split())
    longest = current = 0
    for char in text:
        current = current + 1 if char == "`" else 0
        longest = max(longest, current)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _place(item: Item, show: Show) -> str:
    if item.path is None:
        return ""
    return f"{show(item.path)}" + (f" line {item.line}" if item.line else "")


def _bullet(item: Item, show: Show, mark: str = "") -> list[str]:
    place = _place(item, show)
    tag = f"[{mark}] " if mark else ""
    note = " (a note)" if item.severity == INFO else ""
    lines = [f"- {place + ': ' if place else ''}{tag}{item.message}{note}"]
    if item.context:
        lines.append(f"  {_code(item.context)}")
    return lines


def _by_section(found: list[tuple[Item, str]], show: Show) -> list[str]:
    """Warnings first, then notes, under a heading for each section in its order."""
    order: list[str] = []
    for item, _mark in found:
        if item.section not in order:
            order.append(item.section)
    lines: list[str] = []
    for section in order:
        mine = [(i, m) for i, m in found if i.section == section]
        mine = ([(i, m) for i, m in mine if i.severity != INFO]
                + [(i, m) for i, m in mine if i.severity == INFO])  # fmt: skip
        lines += ["", f"### {section}", ""]
        for item, mark in mine:
            lines += _bullet(item, show, mark)
    return lines


def _language(found: list[Item], show: Show) -> list[str]:
    """G6 and G14 grouped by code: how many, and the first places."""
    groups: dict[tuple[str, str, str], list[Item]] = {}
    for item in found:
        groups.setdefault((item.gate, item.code, item.severity), []).append(item)
    lines = []
    for (gate, code, severity), mine in groups.items():
        places = [p for p in (_place(item, show) for item in mine[:FIRST_PLACES]) if p]
        more = f", and {len(mine) - FIRST_PLACES} more" if len(mine) > FIRST_PLACES else ""
        lines.append(f"- `{code}` ({gate}, {severity.lower()}): {len(mine)}"
                     + (f", at {'; '.join(places)}{more}" if places else ""))  # fmt: skip
        lines.append(f"  e.g. {mine[0].message}")
    return lines or ["- G6 and G14 reported nothing in what they read."]


def _ran(checks: list[tuple[str, str, int]]) -> list[str]:
    """Each check that ran and reported nothing, with what it read."""
    lines = []
    for name, said, found in checks:
        if found:
            continue
        lines.append(f"- {name}: {said}, and it reported nothing." if said
                     else f"- {name}: read none.")  # fmt: skip
    return lines or ["- Each check that ran reported something: see the findings above."]


def _compose(read: list[str], unchecked: list[str], exact: list[tuple[Item, str]],
             further: list[tuple[Item, str]], references: list[str], language: list[str],
             nothing: list[str], show: Show) -> str:  # fmt: skip
    lines = [FIRST, "", "## What was read", "", *read, "", "### What was not checked", "",
             *(f"- {line}" for line in unchecked), "", "## Exact findings", "",
             "Those `--strict` counts: exact arithmetic, an unreadable input, and the like "
             "(docs/refereeing.md).", ""]  # fmt: skip
    for item, mark in exact:
        lines += _bullet(item, show, mark)
    if not exact:
        lines.append("- None of what was read gave a finding `--strict` counts.")
    lines += ["", "## Further findings", "", "Warnings, then notes, by section; none counted "
              "by `--strict`."]  # fmt: skip
    lines += _by_section(further, show) if further else ["", "- None."]
    lines += ["", "## References", "", *references, "", "## Language and notation", "",
              *language, "", "## Checks that ran and found nothing", "", *nothing, ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------------- audit


def _read_of_audit(report, flags: list[str], show: Show) -> list[str]:
    counts = report.read
    lines = [f"- {show(path)} ({_KINDS.get(path.suffix.lower(), path.suffix or 'a file')})"
             for path in report.papers]  # fmt: skip
    entries = sum(len(census.entries) for census in report.references)
    lines.append(f"- {_n(counts.get('headings', 0), 'heading')}, "
                 f"{_n(counts.get('tables', 0), 'table')} and "
                 f"{_n(entries, 'reference entry', 'reference entries')} read; "
                 f"{_n(report.examined, 'number')}")  # fmt: skip
    if report.package is not None:
        from manuscript_guard.auditing.package import WORDING, summary

        lines.append(f"- the package {show(report.package.given)}: {summary(report.package)}. "
                     f"{WORDING}")  # fmt: skip
    lines.append("- options given: " + (", ".join(f"`{flag}`" for flag in flags) or "none"))
    return lines


def _unchecked_of_audit(report) -> list[str]:
    found = list(NEVER_CHECKED)
    if not report.compared:
        found.append("The results: no number was compared with the analysis's outputs "
                     "(`--against` or `--package` names them).")  # fmt: skip
    else:
        found.append("The results ledger: each number is only looked for among the outputs "
                     "given, not bound to the place the analysis put it.")  # fmt: skip
    if not any(path.suffix.lower() in (".svg", ".pdf") for path in report.papers):
        found.append("Figures: none was given (`--figures`), so no figure's numbers were read.")
    if report.abstract is not None and not report.abstract.compared:
        found.append(f"The Abstract against Results: not compared, {report.abstract.why_not}.")
    if report.lookups is None:
        found.append("The registries: the references were not looked up (`--lookup`).")
    found += [f"The journal's rules read from a project: {what}." for what in
              getattr(report.journal, "skipped", [])]  # fmt: skip
    if report.package is not None:
        found.append("The package's analysis: nothing in it was run; `verify` re-runs it, in a "
                     "container or a virtual machine.")  # fmt: skip
    return found


def _references_of_audit(report, items: list[Item], show: Show) -> list[str]:
    lines = []
    for census in report.references:
        if census.note:
            lines.append(f"- {show(census.path)}: {census.note}")
        else:
            lines.append(f"- {show(census.path)}: {len(census.entries)} entries, {census.dois} "
                         f"with a DOI, {census.pmids} with a PMID; {census.style}")  # fmt: skip
    shown = [item for item in items if item.section in REFERENCE_SECTIONS
             and item.code not in ("looked-up", "would-ask")]  # fmt: skip
    for item in shown:
        lines += _bullet(item, show)
    return lines or ["- No reference list was read."]


def _read(count: int, one: str, many: str | None = None, more: str = "read") -> str:
    """"3 tables read", or "" where none was, which the draft says as "read none"."""
    return f"{_n(count, one, many)} {more}" if count else ""


def _checks_of_audit(report, items: list[Item]) -> list[tuple[str, str, int]]:
    read, abstract = report.read, report.abstract
    tables = read.get("tables", 0)
    checks: list[tuple[str, str, int]] = []
    if report.compared:
        compared = len(report.matched) + len(report.unmatched) + len(report.reference_like)
        among = _n(len(report.backing_files), "output")
        checks.append(("Numbers against the outputs",
                       _read(compared, "number", more=f"looked for among {among}"),
                       len(report.unmatched) + len(report.reference_like)))  # fmt: skip
    beside = read.get("tests", 0) + read.get("intervals", 0) + read.get("shares", 0)
    checks += [
        ("Tests, intervals and n (%) against the numbers beside them",
         f"{_n(read.get('tests', 0), 'test')}, {_n(read.get('intervals', 0), 'interval')} and "
         f"{read.get('shares', 0)} n (%) read" if beside else "", len(report.disagreements)),
        ("Table totals and categories against their n", _read(tables, "table"),
         len(report.sums_off) + len(report.over_n)),
        ("Counts held back that a total gives away", _read(tables, "table"),
         len(report.recovered) + len(report.recovered_by_n)),
        ("Flows printed as lists", _read(report.flows_read, "flow"),
         len(report.flows_broken) + len(report.flow_notes)),
    ]  # fmt: skip
    if abstract is not None and abstract.compared:
        checks.append(("Abstract against Results",
                       _read(abstract.numbers, "number", more="of the Abstract read"),
                       len(abstract.conflicts) + len(abstract.not_found)))  # fmt: skip
    for run in report.gates:
        if not run.note:
            checks += [(f"{name} on {run.paper.name}", "its words read", len(found))
                       for name, found in (("Writing (G6)", run.writing),
                                           ("Language (G14)", run.language))]  # fmt: skip
    entries = sum(len(census.entries) for census in report.references)
    checks.append(("The reference list (G7)", _read(entries, "entry", "entries"),
                   sum(len(census.problems) for census in report.references)))  # fmt: skip
    if report.lookups:
        checks.append(("The registries (--lookup)",
                       _read(len(report.lookups), "entry", "entries", "asked about"),
                       sum(len(one.problems) for one in report.lookups)))  # fmt: skip
    checks += _reader_checks(report, items)
    return checks


def _reader_checks(report, items: list[Item]) -> list[tuple[str, str, int]]:
    checks: list[tuple[str, str, int]] = []
    run = report.journal
    if run is not None and not run.note:
        checks.append(("The journal's profile (G4)", f"{run.paper.name} held to it",
                       len(run.findings)))  # fmt: skip
    if run is not None and run.looked:
        checks.append(("Authors named where the review is blind", "each document given read",
                       len(run.named)))  # fmt: skip
    if report.causal is not None:
        causal = report.causal
        checks.append(("Causal words (--design)", f"{_n(causal.read, 'sentence')} read"
                       if causal.read else "", len(causal.found)))  # fmt: skip
    if report.package is not None:
        checks += _package_checks(report.package)
    return checks


def _package_checks(package) -> list[tuple[str, str, int]]:
    on_files = [i for i in package.found if i.code in (
        "package-manifest-invalid", "package-file-missing", "package-file-changed",
        "package-file-unlisted", "package-sums-differ", "package-sums-missing")]  # fmt: skip
    on_results = [i for i in package.found if i.code.startswith("package-result")
                  or i.code == "package-script-missing"]  # fmt: skip
    return [
        ("Package files against MANIFEST.yaml and SHA256SUMS", f"{_n(package.files, 'file')} read"
         if package.files else "", len(on_files)),
        ("Package results against their scripts", f"{_n(package.results, 'results file')} read"
         if package.results else "", len(on_results)),
    ]  # fmt: skip


def for_package(package, flags: list[str], show: Show) -> str:
    """The draft of `audit --package` with no paper: the package alone."""
    from manuscript_guard.auditing.package import WORDING, summary

    read = [f"- the package {show(package.given)}: {summary(package)}. {WORDING}",
            "- options given: " + (", ".join(f"`{flag}`" for flag in flags) or "none")]
    unchecked = ["No manuscript was read: name one before `--package` to have its numbers "
                 "looked for among the package's results.",
                 "The package's analysis: nothing in it was run; `verify` re-runs it, in a "
                 "container or a virtual machine."]  # fmt: skip
    exact = [(item, "") for item in package.found if item.counted]
    further = [(item, "") for item in package.found if not item.counted]
    return _compose(read, unchecked, exact, further, ["- No manuscript was read."],
                    ["- No manuscript was read."], _ran(_package_checks(package)), show)


def for_audit(report, flags: list[str], show: Show) -> str:
    """The draft of an audit's report (`auditing.report.items`)."""
    items = sections.items(report)
    exact = [(item, "") for item in items if item.counted]
    unchecked = _unchecked_of_audit(report)
    further = [(item, "") for item in items if not item.counted
               and item.section not in REFERENCE_SECTIONS | LANGUAGE_SECTIONS
               and item.code not in UNCHECKED_CODES]  # fmt: skip
    language = _language([item for item in items if item.section in LANGUAGE_SECTIONS], show)
    return _compose(_read_of_audit(report, flags, show), unchecked, exact, further,
                    _references_of_audit(report, items, show), language,
                    _ran(_checks_of_audit(report, items)), show)  # fmt: skip


# --------------------------------------------------------------------------------- compare


def for_compare(found, flags: list[str], show: Show) -> str:
    """The draft of a comparison (`comparing.report.Comparison`)."""
    from manuscript_guard.comparing import differences
    from manuscript_guard.comparing.report import AUDITED, VERSIONS

    read = []
    for name, version in (("v1", found.old), ("v2", found.new)):
        read.append(f"- {name}: {show(version.path)} ({version.kind}), "
                    f"{_n(sum(1 for h in version.sections if h.level), 'section')}, "
                    f"{_n(len(version.tables), 'table')}, "
                    f"{_n(len(version.figures), 'figure')}")  # fmt: skip
    read += [f"- {what}: {show(path)}" for what, path in (("the response letter", found.letter),
             ("your comments", found.comments)) if path is not None]  # fmt: skip
    read.append("- options given: " + (", ".join(f"`{flag}`" for flag in flags) or "none"))
    unchecked = [*NEVER_CHECKED,
                 "The results: no number was compared with the analysis's outputs.",
                 "The figures' pictures: a figure is compared by its caption only.",
                 "Whether a change answers a comment: that is yours to read."]  # fmt: skip
    exact = list(found.exact)
    exact_ids = {id(item) for item, _mark in exact}
    same = {f"{part}-same" for part in ("section", "table", "figure")}
    rest = [(item, mark) for item, mark in found.items if item.section != VERSIONS
            and item.code not in same and id(item) not in exact_ids]  # fmt: skip
    further = [(item, mark) for item, mark in rest
               if not (item.section == AUDITED and item.gate in ("G6", "G14", "G7"))]
    language = _language([item for item, _m in rest if item.section == AUDITED
                          and item.gate in ("G6", "G14")], show)  # fmt: skip
    references = [line for item, mark in rest if item.section == AUDITED and item.gate == "G7"
                  for line in _bullet(item, show, mark)] or [
        "- v2's audit reported nothing of its reference list."]
    counted = {section: sum(1 for item, _m in rest if item.section == section)
               for section in (differences.SECTIONS, differences.TABLES, differences.FIGURES,
                               differences.NUMBERS, differences.CLAIMS, AUDITED)}  # fmt: skip
    old, new = found.old, found.new

    def both(of: Callable) -> str:
        n1, n2 = of(old), of(new)
        return f"{n1} in v1 and {n2} in v2 read" if n1 or n2 else ""

    checks = [
        ("Sections", both(lambda v: sum(1 for h in v.sections if h.level)),
         counted[differences.SECTIONS]),
        ("Tables, cell by cell", both(lambda v: len(v.tables)), counted[differences.TABLES]),
        ("Figures, by their captions", both(lambda v: len(v.figures)),
         counted[differences.FIGURES]),
        ("Numbers, citations and bindings of the prose", "the prose of both versions read",
         counted[differences.NUMBERS]),
        ("Claims made stronger, weaker or turned round", "the changed sentences read",
         counted[differences.CLAIMS]),
        ("v2 audited", "v2 read as `audit` reads a paper", counted[AUDITED]),
    ]  # fmt: skip
    return _compose(read, unchecked, exact, further, references, language, _ran(checks), show)


__all__ = ["FIRST", "for_audit", "for_compare", "for_package", "refused", "write"]
