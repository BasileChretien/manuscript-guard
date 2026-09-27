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
"""

from __future__ import annotations

import re
from pathlib import Path

from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.gates.review import file_digests
from manuscript_guard.roundtrip import _INLINE_HTML

GATE = "G13"
REVISION_DIR = "revision"


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
        text, _title = strip_front_matter(path.read_text(encoding="utf-8"))
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
