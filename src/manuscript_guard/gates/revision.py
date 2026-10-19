"""G13 — the response to the reviewers says what actually happened.

Every other gate checks the manuscript. This one checks the letter that goes with it.

A point-by-point response is a document made almost entirely of claims: "we have revised the
Methods", "the analysis has been rerun", "Table 2 now reports the counts". Each is a
statement about the paper that nobody verifies — not the journal, which cannot see the
diff, and not the authors, who wrote it from memory at the end of a long revision. The
commonest failure is not dishonesty. It is a response written before the change, and the
change then made differently, or not at all.

So a revision round records the manuscript as the journal received it, one digest per file,
and each response names what changed because of it. A claim that a file was revised is
checked against whether that file differs from what went out. A claim that a results key
changed is checked against whether the key exists. A point with neither a change nor a
recorded rebuttal is unanswered.

Severity follows the same rule as the internal panel: an author mid-revision must be able to
build a document to read, so ordinary work warns. Resubmitting with an unanswered point, or
with a claimed revision that did not happen, fails.

A response that says the text "now reads" something names it in `changed`, as a `text` entry
with the `quote`, and the section where it stands if the response names one. The quote is
looked for in the manuscript as it renders now, and in the copy of the manuscript as the
journal received it, which `respond --open` writes beside the round: in the first, or the
response quotes text the paper does not hold; not in the second, or nothing changed.

And the letter is a document that goes to the journal, so what the authors wrote in it is
read as such: G6's artefacts, the tool's own words and codes, a binding left unfilled, a
place in the source files, the marker the `reviewer-response` skill leaves where the author
still has to write, and the template's own text.
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, read_text, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.gates.review import file_digests
from manuscript_guard.roundtrip import _INLINE_HTML

GATE = "G13"
REVISION_DIR = "revision"
#: Where `respond --open` writes the manuscript as the journal received it, rendered.
SUBMITTED_DIR = "submitted"
#: What the `reviewer-response` skill writes where the author still has to supply something.
MARKER = re.compile(r"\[AUTHOR:[^\]\n]*\]")
#: The text `respond --open` puts in a new round for the reviewer's words.
TEMPLATE_COMMENT = "Quote the reviewer here, in their words."


def rounds(project: Project) -> list[tuple[int, Path]]:
    root = project.root / REVISION_DIR
    if not root.exists():
        return []
    found = []
    for path in sorted(root.glob("round-*.yaml")):
        try:
            found.append((int(path.stem.split("-", 1)[1]), path))
        except (IndexError, ValueError):
            continue
    return sorted(found)


def check_revision(project: Project, *, submission: bool = False) -> Report:
    """`submission` raises every warning here to a failure."""
    severity = FAIL if submission else WARN
    found = rounds(project)
    if not found:
        # No revision round is the ordinary state of a paper that has not been submitted.
        # Saying nothing is right; inventing a finding would teach an author to ignore G13.
        return Report(counts={"revision_rounds": 0})

    report = Report()
    current = file_digests(project)
    answered = 0
    total = 0
    # What `_anchor_unchanged` reads the manuscript for, read once for every point.
    seen: dict = {}

    for number, path in found:
        document = read_structured(path)
        schema_report = validate(document, "revision", path, gate=GATE)
        report = report.merge(schema_report)
        if not schema_report.ok or not isinstance(document, dict):
            continue

        submitted = document.get("submitted_files") or {}
        paragraphs = document.get("submitted_paragraphs") or {}
        for reviewer in document["reviewers"]:
            for point in reviewer["points"]:
                total += 1
                report, ok = _check_point(
                    report, project, number, reviewer["id"], point, submitted, current,
                    severity, paragraphs, seen,
                )
                answered += int(ok)
                report = report.merge(
                    _reply(path, number, reviewer["id"], point, severity)
                )

    return report.with_counts(
        revision_rounds=len(found),
        revision_points=total,
        revision_points_answered=answered,
    )


def _check_point(
    report: Report,
    project: Project,
    number: int,
    reviewer: str,
    point: dict,
    submitted: dict,
    current: dict,
    severity: str,
    paragraphs: dict,
    seen: dict,
) -> tuple[Report, bool]:
    where = f"round {number}, {reviewer} point {point['id']}"
    response = str(point.get("response", "")).strip()
    rebutted = str(point.get("rebutted", "")).strip()
    changed = point.get("changed") or []

    if not response:
        return (
            report.with_findings(
                Finding(
                    gate=GATE,
                    code="point-unanswered",
                    severity=severity,
                    message=f"{where} has no response",
                    context=str(point["comment"])[:140],
                    hint="every point gets an answer; a reasoned disagreement is one, and "
                    "belongs in `rebutted`",
                )
            ),
            False,
        )

    if not changed and not rebutted:
        return (
            report.with_findings(
                Finding(
                    gate=GATE,
                    code="response-claims-nothing",
                    severity=severity,
                    message=f"{where} answers without naming a change or a reason for none",
                    context=response[:140],
                    hint="list what changed in `changed`, or say in `rebutted` why nothing "
                    "did; a response that does neither cannot be checked against the paper",
                )
            ),
            False,
        )

    ok = True
    anchor = point.get("where")
    claims_manuscript = any(entry["kind"] == "manuscript" for entry in changed)
    if anchor and paragraphs and anchor not in paragraphs and claims_manuscript:
        # Only a round written by hand, or by an older version, has one: nothing now records
        # an anchor the round's own baseline does not hold. Skipped, it passed unchecked.
        ok = False
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="anchor-unrecorded",
                severity=severity,
                message=f"{where}: the paragraph this point was attached to ({anchor}) is not "
                f"among the paragraphs the round recorded as submitted, so whether it changed "
                f"cannot be checked",
                context=response[:140],
                hint="read that paragraph against the reviewer's comment yourself. Then delete "
                "`where` from the point: the claimed change is checked against the whole file",
            )
        )
    anchored = _anchor_unchanged(project, point, paragraphs, changed, seen)
    if anchored:
        ok = False
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="claimed-change-missed-the-point",
                severity=severity,
                message=f"{where}: {anchored}",
                context=response[:140],
                hint="the reviewer commented on a particular paragraph. Revising elsewhere "
                "in the same file may well be the right answer - say so in `rebutted` "
                "rather than letting the response imply the paragraph was addressed",
            )
        )

    for entry in changed:
        if entry["kind"] == "text":
            report, quoted = _quoted(report, project, number, where, entry, severity, seen)
            ok = ok and quoted
            continue
        problem = _unverified(project, entry, submitted, current)
        if problem is None:
            continue
        ok = False
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="claimed-change-did-not-happen",
                severity=severity,
                message=f"{where}: {problem}",
                context=response[:140],
                hint="the response tells a journal this changed. Make the change, or say in "
                "`rebutted` that it was not made and why",
            )
        )
    return report, ok


def _anchor_unchanged(
    project: Project, point: dict, paragraphs: dict, changed: list, seen: dict
) -> str | None:
    """Whether the paragraph the reviewer actually commented on is still as it was.

    A response claiming a manuscript revision is satisfied by *any* difference in the file,
    and a paper's Methods is one file. When the point came from a comment attached to a
    paragraph, the tighter question is available and worth asking: the reviewer objected to
    that paragraph, and it is unchanged.

    The paragraph is found by its text, not by its identifier. The identifier is
    positional: a paragraph added above it during the revision, or a release that numbers
    paragraphs by other rules, pointed it at a neighbour, whose text differed, and a
    paragraph nobody touched passed as revised. The round keeps a hash of the text the
    reviewer read. If the manuscript still holds that text anywhere, it was not revised,
    wherever it now sits. Of two identical paragraphs, one revised, the other still reads as
    the unrevised one: a false alarm, which is the direction to be wrong in.
    """
    where = point.get("where")
    if not where or not paragraphs or where not in paragraphs:
        return None
    if not any(entry["kind"] == "manuscript" for entry in changed):
        return None

    if "passages" not in seen:
        seen["passages"] = _passages(project)
    if paragraphs[where] in seen["passages"]:
        return (
            f"the paragraph this point was attached to ({where}) is unchanged, though the "
            f"response says the manuscript was revised"
        )
    return None


#: A line that ends one run of a paragraph's lines and starts another wherever it stands: a
#: code fence or div marker, or a line that is a whole HTML tag - one pandoc reads as a block.
#: A `<span>` or `<br>` alone on a line is inside the paragraph, and taken for a boundary it
#: left the old text standing as one half of a revised paragraph.
_MARKER = re.compile(
    rf"^[ ]{{0,3}}(?::::|```|~~~)"
    rf"|^[ \t]*</?(?!(?:{_INLINE_HTML})(?![\w-]))[A-Za-z][^>]*>[ \t]*$",
    re.IGNORECASE,
)
#: A heading, which pandoc reads only where a paragraph could start: first in a block, or
#: straight after a marker. Anywhere else a `#` line is part of the paragraph.
_ATX = re.compile(r"^[ ]{0,3}#{1,6}(?:[ \t]|$)")
_UNDERLINE = re.compile(r"^[ ]{0,3}(?:=+|-+)[ \t]*$")
#: A line that is a whole HTML comment prints nothing, so a paragraph reads as if it were not
#: there, wherever it stands.
_COMMENT_LINE = re.compile(r"^[ \t]*<!--.*-->[ \t]*$")


def _passages(project: Project) -> set[str]:
    """The hash of every stretch of the manuscript that could be a paragraph a reviewer read.

    Each block between blank lines, and each run of a block's lines between the headings and
    markers inside it, with any line that is a whole HTML comment left out. The tagged
    paragraphs alone missed one the revision had written a heading straight above, put a div
    or a comment round, or run on under its heading by dropping a blank line: still in the
    manuscript, printed the same, and passed as revised.
    """
    import hashlib

    from manuscript_guard.build.assemble import strip_front_matter
    from manuscript_guard.gates.numbers import source_files

    found: set[str] = set()

    def keep(lines: list[str]) -> None:
        text = "\n".join(lines).strip()
        if text:
            found.add(hashlib.sha256(text.encode("utf-8")).hexdigest())

    for path in source_files(project.path("manuscript")):
        text, _title = strip_front_matter(read_text(path))
        for block in re.split(r"\n\s*\n", text):
            keep(block.split("\n"))
            # A run starts where a heading could: the block's first line, or straight after a
            # marker or another heading.
            run: list[str] = []
            for line in block.split("\n"):
                if _COMMENT_LINE.match(line):
                    continue
                if _MARKER.match(line) or (not run and _ATX.match(line)):
                    keep(run)
                    run = []
                elif len(run) == 1 and _UNDERLINE.match(line):
                    run = []  # a setext heading: its title and its underline
                else:
                    run.append(line)
            keep(run)
    return found


def displays(project: Project) -> dict[str, str]:
    """What each binding prints, as the build fills it in."""
    from manuscript_guard.contracts import load_namespace

    return {ref: value.display for ref, value in load_namespace(project)[0].items()}


def rendered_manuscript(project: Project, rendered: dict[str, str] | None = None) -> str:
    """The manuscript's files, joined in order, with every binding filled in: the text a
    quote of it is looked for in, and what `respond --open` keeps as submitted."""
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.placeholders import substitute

    rendered = displays(project) if rendered is None else rendered
    return "\n\n".join(
        substitute(read_text(path), rendered)
        for path in source_files(project.path("manuscript"))
    )


def submitted_copy(project: Project, number: int) -> str | None:
    """The manuscript as the journal received it in round `number`, or None where the round
    was opened without a copy."""
    folder = project.root / REVISION_DIR / f"round-{number}" / SUBMITTED_DIR
    if not folder.is_dir():
        return None
    return "\n\n".join(
        path.read_text(encoding="utf-8") for path in sorted(folder.rglob("*.md"))
    )


#: What a quote is compared without: comments, the marks of emphasis and code, and how the
#: lines are wrapped. A response quotes the sentence, not its Markdown.
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def as_quoted(text: str) -> str:
    """Text as a quote of it is compared: no comments, no `*` or backtick, and every run of
    space, line ends included, one space."""
    text = _COMMENT.sub(" ", text).replace("*", "").replace("`", "")
    return " ".join(text.split())


def _in_section(text: str, quote: str, section: str) -> bool:
    """Whether `quote` stands in a section whose title holds the words of `section`."""
    from manuscript_guard.text.sections import split_sections

    wanted = re.findall(r"\w+", section.casefold())
    for found in split_sections(text):
        words = re.findall(r"\w+", found.title.casefold())
        held = any(words[at : at + len(wanted)] == wanted for at in range(len(words)))
        if held and quote in as_quoted(found.enclosed):
            return True
    return False


def _quoted(
    report: Report,
    project: Project,
    number: int,
    where: str,
    entry: dict,
    severity: str,
    seen: dict,
) -> tuple[Report, bool]:
    """A claim that the text now reads a quote: in the manuscript now, not in what the
    journal received, and in the section the response names."""
    from manuscript_guard.text.placeholders import substitute

    if "rendered" not in seen:
        seen["displays"] = displays(project)
        seen["rendered"] = rendered_manuscript(project, seen["displays"])
    # A quote may hold a binding, as the sentence it quotes does: it is read filled in.
    quote = as_quoted(substitute(str(entry.get("quote", "")), seen["displays"]))
    now = seen["rendered"]
    problem = None
    if quote not in as_quoted(now):
        problem = ("quoted-text-absent", "the manuscript does not now read it")
    elif entry.get("section") and not _in_section(now, quote, str(entry["section"])):
        problem = ("quoted-text-elsewhere", f"it is not in the {entry['section']}")
    if problem is not None:
        code, said = problem
        return (
            report.with_findings(
                Finding(
                    gate=GATE,
                    code=code,
                    severity=severity,
                    message=f"{where}: the response says the text now reads this, and {said}",
                    context=quote[:140],
                    hint="quote the sentence as the paper now prints it, or make the change",
                )
            ),
            False,
        )
    before = submitted_copy(project, number)
    if before is None:
        return (
            report.with_findings(
                Finding(
                    gate=GATE,
                    code="quoted-text-unchecked",
                    severity=INFO,
                    message=f"{where}: whether the quoted text is new cannot be told: round "
                    f"{number} was opened without a copy of the manuscript as submitted",
                    context=quote[:140],
                    hint="a round opened with this version of `respond --open` keeps one",
                )
            ),
            True,
        )
    if quote in as_quoted(before):
        return (
            report.with_findings(
                Finding(
                    gate=GATE,
                    code="quoted-text-not-new",
                    severity=severity,
                    message=f"{where}: the response offers this as a change, and the "
                    f"manuscript the journal received already read it",
                    context=quote[:140],
                    hint="make the change, or say in `rebutted` that the text already said "
                    "this, and where",
                )
            ),
            False,
        )
    return report, True


#: What must never reach a journal in a letter: the tool's name, a gate with a finding code
#: of the tool's, and a place in the source files the journal never sees.
_TOOL_NAME = re.compile(r"\b(?:manuscript[-_]guard|mguard)\b", re.IGNORECASE)
#: A gate is said only with one of the tool's own finding codes after a colon, "G13:
#: point-unanswered": "G1 (well-differentiated)" is a tumour's grade and "G2/M" a phase of the
#: cell cycle.
def _gate_code() -> re.Pattern[str]:
    from manuscript_guard.policy import BINDS_AT

    codes = "|".join(sorted((re.escape(code) for code in BINDS_AT), key=len, reverse=True))
    return re.compile(rf"\bG(?:1[0-5]|[1-9])r?[ \t]*:[ \t]*(?:{codes})\b")


_SOURCE_PLACE = re.compile(r"\b[\w./-]+\.md(?::\d+|,?[ \t]+lines?[ \t]+\d+)", re.IGNORECASE)


def _reply(path: Path, number: int, reviewer: str, point: dict, severity: str) -> Report:
    """What the authors wrote in this point, read as text that goes to the journal."""
    from manuscript_guard.gates.writing import load_rules

    where = f"round {number}, {reviewer} point {point['id']}"
    report = Report()
    if str(point.get("comment", "")).strip() == TEMPLATE_COMMENT:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="response-placeholder",
                severity=severity,
                message=f"{where} still holds the template's text where the reviewer's words go",
                path=path,
                hint="quote the reviewer, in their words",
            )
        )
    rules = load_rules()
    # A changed entry's `note` is printed in the letter after the change, and read with the
    # reply (round 1 of #266: it went to the journal unread).
    written = [(field, str(point.get(field, "") or "")) for field in ("response", "rebutted")]
    written += [
        (f"changed[{at}].note", str(entry.get("note") or ""))
        for at, entry in enumerate(point.get("changed") or [])
        if isinstance(entry, dict)
    ]
    for field, text in written:
        found: list[tuple[str, str, str]] = [
            ("response-placeholder", m.group(0), "a place the author still has to write")
            for m in MARKER.finditer(text)
        ]
        for rule in rules.artefacts:
            # "Certainly, we have revised the Methods" opens many a reply to a reviewer: in a
            # letter the assistant's register is the authors' own.
            if rule["id"] == "assistant-voice":
                continue
            flags = re.MULTILINE | (re.IGNORECASE if rule.get("any_case_in_manuscript") else 0)
            found += [
                ("response-artefact", m.group(0), rule["why"])
                for m in re.finditer(rule["pattern"], text, flags)
            ]
        found += [
            ("response-leak", m.group(0), why)
            for pattern, why in (
                (_TOOL_NAME, "the name of the tool that checked it"),
                (_gate_code(), "a gate of the tool that checked it"),
                (_SOURCE_PLACE, "a place in the source files, which the journal never sees"),
            )
            for m in pattern.finditer(text)
        ]
        for code, shown, why in found:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code=code,
                    severity=severity,
                    message=f"{where}, `{field}`: {shown[:60]!r} - {why}",
                    path=path,
                    context=text[:140],
                    hint="the letter goes to the journal as written; take it out or "
                    "write what it stands for",
                )
            )
    return report


def _unverified(project: Project, entry: dict, submitted: dict, current: dict) -> str | None:
    """Why this claimed change cannot be confirmed, or None if it can."""
    kind, name = entry["kind"], entry["name"]

    if kind == "manuscript":
        if name not in current:
            return f"the response names {name}, which is not a manuscript file"
        if not submitted:
            return None  # nothing to compare against; the round was opened without a baseline
        if name not in submitted:
            # Absent from a baseline that lists other files. `.get` returning None is never
            # equal to a digest, so falling through read as "verified" - a claimed revision
            # of any file the baseline happened not to list passed unconditionally, which is
            # the one thing this function exists to refuse.
            return (
                f"the response says {name} was revised, and the round's baseline does not "
                f"record what it looked like when it was submitted, so nothing can confirm it"
            )
        if submitted[name] == current[name]:
            return f"the response says {name} was revised, and it is byte-identical to what "\
                   f"was submitted"
        return None

    if kind == "results":
        from manuscript_guard.contracts import load_results

        results, _report = load_results(project.path("results"))
        if name not in results.values and name not in results.tables:
            return f"the response names results key {name}, which nothing emits"
        return None

    # Contained, not merely joined. `Path / "C:/Windows/win.ini"` discards the left side
    # entirely, and `../paper.yaml` walks out of the directory - so "does this artefact
    # exist" was satisfiable by naming any file on the machine.
    root = project.path("figures" if kind == "figure" else "analysis").resolve()
    try:
        path = (root / name).resolve()
        inside = path.is_relative_to(root)
    except (OSError, ValueError):
        return f"the response names {kind} {name}, which is not a usable path"
    if not inside:
        return f"the response names {kind} {name}, which is outside {root.name}/"
    if not path.exists():
        return f"the response names {kind} {name}, which does not exist"
    return None
