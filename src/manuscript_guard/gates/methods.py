"""G9 — does the Methods section still describe what the code does?

Methods sections go stale in a particular way. The analysis is written, the Methods are
written to match, and then the analysis changes: a filter is added, a model is swapped, a
threshold moves. Nothing forces the prose to follow, and nobody re-reads their own Methods
once they are written. The result is a paper that describes an analysis nobody ran.

No checker can read code and prose and decide whether they agree. What it can do is notice
that the code changed after the prose was last reconciled with it, and refuse to let that
pass silently. So this gate is a **reconciliation ledger**: `methods.lock` records the
analysis files as they stood when someone last read the Methods against them, and the gate
compares.

That makes the claim modest and true. It does not verify that the Methods are correct. It
verifies that somebody looked, and that nothing has changed since they did.

A whole file is a coarse thing to have looked at, so the reading can also be kept pair by
pair. The analysis marks a step of its code (`with em.step("ci"):`), and the Methods end the
text that describes it with an anchor that prints nothing, `{{method.ci}}`. What the anchor
claims is the text before it, back to the anchor before it or the start of its paragraph:
its extent is where the author put the anchors, and nothing guesses where a sentence ends.
The lock then records each step and its claim as a pair, with a digest of the step's code
read as code and the claim as written, and the report names the pair whose code or whose
text changed since it was read. An anchor that names no step the run recorded fails, which
is how a claim about a branch the analysis never took is caught.

Two additions make the prompt useful rather than annoying. The report names *which* files
changed, so the reconciliation is targeted. And a handful of parameters that must agree —
the significance threshold, the software versions — are extracted from both sides and
compared directly, because those are checkable and they are what reviewers query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard.classify import is_methods
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results, Step
from manuscript_guard.contracts.values import Value
from manuscript_guard.emit import sha256_of
from manuscript_guard.findings import WARN, Finding, Report
from manuscript_guard.gates.numbers import source_files
from manuscript_guard.paths import SOURCE_SUFFIXES
from manuscript_guard.text.masking import blank_comments
from manuscript_guard.text.placeholders import parse, substitute
from manuscript_guard.text.sections import (
    chains_at,
    footnote_index,
    heading_index,
    split_sections,
)

GATE = "G9"
LOCK = "methods.lock"

_METHODS_HEADING = re.compile(r"^\s*(?:materials and )?methods\b", re.IGNORECASE)


@dataclass(frozen=True)
class Drift:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]

    @property
    def any(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def describe(self) -> str:
        parts = []
        for label, names in (
            ("changed", self.changed),
            ("added", self.added),
            ("removed", self.removed),
        ):
            if names:
                shown = ", ".join(sorted(names)[:4])
                more = f" (+{len(names) - 4} more)" if len(names) > 4 else ""
                parts.append(f"{label}: {shown}{more}")
        return "; ".join(parts)


@dataclass(frozen=True)
class Claim:
    """The text one run of anchors claims: what stands before them, back to the anchor before
    them or the start of their paragraph, its spaces and line breaks each read as one space.
    Several anchors side by side claim the same text."""

    steps: tuple[str, ...]
    text: str
    path: Path
    #: Where the claim starts, and where its anchors stand.
    line: int
    anchor_line: int


@dataclass(frozen=True)
class Paragraph:
    """A paragraph with no anchor in it: in the Methods, text that points at no step."""

    text: str
    path: Path
    line: int


#: A line that ends a paragraph and starts no claim: blank, or an ATX heading.
_HEADING = re.compile(r"[ ]{0,3}#{1,6}(?:[ \t]|$)")


def _paragraphs(text: str) -> list[tuple[int, int]]:
    """Where each paragraph of `text` starts and ends, by its lines: a blank line ends one,
    and a heading is a line of its own. Read on the text as written, so a comment on a line of
    its own inside a paragraph, which pandoc keeps in the paragraph, does not end it."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    at = 0
    # A line ends at a line feed and nowhere else, as `placeholders.parse` counts lines.
    for line in re.findall(r"[^\n]*\n|[^\n]+\Z", text):
        bare = line.rstrip("\r\n")
        if not bare.strip() or _HEADING.match(bare):
            if start is not None:
                spans.append((start, at))
                start = None
        elif start is None:
            start = at
        at += len(line)
    if start is not None:
        spans.append((start, at))
    return spans


#: A paragraph that says nothing a step could back: a table or figure placed by its binding,
#: a fenced listing, a pipe table, a fenced div.
_NOT_PROSE = re.compile(r"\{\{[^}]*\}\}$|```|~~~|\||:::")


def _collapsed(text: str) -> str:
    return " ".join(text.split())


Span = tuple[int, int]


def claims_in(text: str) -> tuple[list[tuple[tuple[str, ...], int, int, int]], list[Span]]:
    """The claims of one file, and its paragraphs that hold no anchor.

    Each claim is its steps, where its text starts and ends, and where its anchors start.
    The text is read with comments blanked, so a comment inside a claim is not part of it,
    and the claim is empty where its anchors open their paragraph.
    """
    anchors = [found for found in parse(text)[0] if found.is_anchor]
    shown = blank_comments(text) if "<!--" in text else text
    claims, bare = [], []
    for start, end in _paragraphs(text):
        inside = [a for a in anchors if start <= a.start < end]
        if not inside:
            bare.append((start, end))
            continue
        runs: list[list] = []
        for anchor in inside:
            if runs and not shown[runs[-1][-1].end : anchor.start].strip():
                runs[-1].append(anchor)
            else:
                runs.append([anchor])
        before = start
        for run in runs:
            claims.append((tuple(a.key for a in run), before, run[0].start, run[0].start))
            before = run[-1].end
    return claims, bare


def anchored(project: Project) -> tuple[list[Claim], list[Paragraph]]:
    """Every claim in the manuscript, and every Methods paragraph that points at no step."""
    claims: list[Claim] = []
    open_: list[Paragraph] = []
    for path in source_files(project.path("manuscript")):
        found, bare = _anchored_in(path, read_text(path))
        claims += found
        open_ += bare
    return claims, open_


def _anchored_in(path: Path, text: str) -> tuple[list[Claim], list[Paragraph]]:
    found, bare = claims_in(text)
    shown = blank_comments(text) if "<!--" in text else text
    headings, notes = heading_index(text), footnote_index(text)

    def methods(at: int) -> bool:
        return any(is_methods(chain) for chain in chains_at(headings, notes, at))

    def line(at: int) -> int:
        return text.count("\n", 0, at) + 1

    claims = [
        Claim(
            steps=steps,
            text=_collapsed(shown[start:end]),
            path=path,
            # Where its first word is: after the anchor before it, a line break can come first.
            line=line(start + len(shown[start:end]) - len(shown[start:end].lstrip())),
            anchor_line=line(at),
        )
        for steps, start, end, at in found
    ]
    open_ = []
    for start, end in bare:
        words = _collapsed(shown[start:end])
        if words and methods(start) and not _NOT_PROSE.match(words):
            open_.append(Paragraph(words, path, line(start)))
    return claims, open_


def analysis_digests(project: Project) -> dict[str, str]:
    directory = project.path("analysis")
    if not directory.exists():
        return {}
    out = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            out[str(path.relative_to(project.root)).replace("\\", "/")] = sha256_of(path)
    return out


def lock_path(project: Project) -> Path:
    return project.root / LOCK


def read_lock(project: Project) -> dict:
    path = lock_path(project)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compare(current: dict[str, str], recorded: dict[str, str]) -> Drift:
    return Drift(
        added=tuple(sorted(set(current) - set(recorded))),
        removed=tuple(sorted(set(recorded) - set(current))),
        changed=tuple(sorted(k for k in set(current) & set(recorded) if current[k] != recorded[k])),
    )


def methods_text(project: Project) -> str:
    for path in source_files(project.path("manuscript")):
        for section in split_sections(read_text(path)):
            if _METHODS_HEADING.match(section.title):
                return section.enclosed
    return ""


def check_methods(
    project: Project,
    namespace: dict[str, Value] | None = None,
    results: Results | None = None,
) -> Report:
    if namespace is None or results is None:
        from manuscript_guard.contracts import load_namespace

        loaded = load_namespace(project)
        namespace = namespace if namespace is not None else loaded[0]
        results = results if results is not None else loaded[1]
    current = analysis_digests(project)
    lock = read_lock(project)
    pairs = _pairs(project, results, lock if current and lock.get("analysis") else None)
    if not current:
        return pairs.with_counts(analysis_files=0)

    recorded = lock.get("analysis", {})

    if not recorded:
        return pairs.with_findings(
            Finding(
                gate=GATE,
                code="methods-never-reconciled",
                severity=WARN,
                message=f"the Methods have never been read against the {len(current)} "
                f"analysis file(s)",
                path=lock_path(project),
                hint="read the Methods against the code, then run "
                "`manuscript-guard methods --reconcile`",
            ),
        ).with_counts(analysis_files=len(current))

    drift = compare(current, recorded)
    report = pairs
    if drift.any:
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="methods-drift",
                message="the analysis changed after the Methods were last reconciled with it",
                path=lock_path(project),
                context=drift.describe(),
                hint="re-read the Methods against those files, then "
                "`manuscript-guard methods --reconcile`",
            )
        )

    report = report.merge(_compare_parameters(project, lock, namespace))
    return report.with_counts(
        analysis_files=len(current),
        analysis_changed=len(drift.changed) + len(drift.added) + len(drift.removed),
    )


@dataclass(frozen=True)
class Pair:
    """One step and one claim pointing at it, and how they stand against the lock."""

    step: str
    claim: Claim
    found: Step | None
    #: unknown, unread, code, claim or read; see `_judged`.
    standing: str
    read_on: str | None = None
    was: str | None = None


def _locked(lock: dict) -> list[dict]:
    pairs = lock.get("pairs") or []
    return [pair for pair in pairs if isinstance(pair, dict)]


def _judged(claims: list[Claim], steps: dict[str, Step], locked: list[dict] | None) -> list[Pair]:
    """Every pair of a step and a claim pointing at it, in the order of the claims, and where
    each stands: its step never ran (`unknown`); never read (`unread`); its code (`code`) or
    its text (`claim`) changed since it was read; or `read`, as it was.

    A pair is the lock's when its step and its text are the lock's. A text is a changed one
    only where it is all that is left: one text of the step that the lock does not hold, and
    one text the lock holds that no claim does now. A second text pointing at a step is a new
    pair, never read, rather than the first one changed.
    """
    pairs = [(step, claim) for claim in claims for step in claim.steps]
    if locked is None:
        return [
            Pair(step, claim, steps.get(step), "unread" if step in steps else "unknown")
            for step, claim in pairs
        ]
    now = {(step, claim.text) for step, claim in pairs}
    left: dict[str, list[dict]] = {}
    for entry in locked:
        if (entry.get("step"), entry.get("claim")) not in now:
            left.setdefault(entry.get("step"), []).append(entry)
    new: dict[str, set[str]] = {}
    held = {(entry.get("step"), entry.get("claim")): entry for entry in locked}
    for step, claim in pairs:
        if (step, claim.text) not in held:
            new.setdefault(step, set()).add(claim.text)
    out = []
    for step, claim in pairs:
        found = steps.get(step)
        if found is None:
            out.append(Pair(step, claim, found, "unknown"))
            continue
        entry = held.get((step, claim.text))
        if entry is not None:
            standing = "read" if entry.get("code") == found.digest else "code"
            out.append(Pair(step, claim, found, standing, entry.get("read_on")))
        elif len(new[step]) == 1 and len(left.get(step, ())) == 1:
            was = left[step][0]
            standing = "claim" if was.get("code") == found.digest else "unread"
            out.append(Pair(step, claim, found, standing, was.get("read_on"), was.get("claim")))
        else:
            out.append(Pair(step, claim, found, "unread"))
    return out


def pairs_of(project: Project, results: Results, lock: dict | None) -> list[Pair]:
    """Every step and claim pointing at it, in the order the manuscript has them."""
    claims, _open = anchored(project)
    return _judged(claims, results.steps, _locked(lock) if lock is not None else None)


def _excerpt(text: str, width: int = 90) -> str:
    return text if len(text) <= width else text[: width - 3].rstrip() + "..."


def _pairs(project: Project, results: Results, lock: dict | None) -> Report:
    """The anchors and the steps, and each pair against the lock where there is one.

    Nothing at all, not even a count, for a project with neither: it reads as it did before
    there were steps.
    """
    claims, open_ = anchored(project)
    if not claims and not results.steps:
        return Report()
    findings = []
    locked = _locked(lock) if lock is not None else None
    for claim in claims:
        if not claim.text:
            findings.append(
                Finding(
                    gate=GATE,
                    code="method-claim-empty",
                    message=f"{_anchors(claim.steps)} claims no text: nothing stands before it "
                    f"in its paragraph",
                    hint="put the anchor at the end of the text that describes the step",
                    path=claim.path,
                    line=claim.anchor_line,
                )
            )
    pairs = _judged(claims, results.steps, locked)
    described = {pair.step for pair in pairs}
    stale = 0
    for pair in pairs:
        # Without a lock every pair is unread, and `methods-never-reconciled` says so once.
        if locked is None and pair.found is not None:
            continue
        finding = _pair_finding(pair, {"path": pair.claim.path, "line": pair.claim.anchor_line})
        if finding is not None:
            stale += pair.standing in ("code", "claim", "unread")
            findings.append(finding)
    for name, step in sorted(results.steps.items()):
        if name in described:
            continue
        findings.append(
            Finding(
                gate=GATE,
                code="method-step-undescribed",
                severity=WARN,
                message=f"step {name!r} ran, and no text in the manuscript points at it",
                path=project.root / step.script,
                line=step.lines[0] if step.lines else None,
                hint=f"end the Methods text that describes it with {{{{method.{name}}}}}, or "
                "take the mark off the code",
            )
        )
    return Report(tuple(findings)).with_counts(
        method_steps=len(results.steps),
        method_claims=len(claims),
        method_pairs_stale=stale,
        methods_open=len(open_),
    )


def _anchors(steps: tuple[str, ...]) -> str:
    return "".join(f"{{{{method.{step}}}}}" for step in steps)


def _pair_finding(pair: Pair, where: dict) -> Finding | None:
    step, claim = pair.step, pair.claim
    reconcile_hint = (
        f"read it against {pair.found.where if pair.found else ''}, then "
        f"`manuscript-guard methods --reconcile {step}`"
    )
    if pair.standing == "unknown":
        return Finding(
            gate=GATE,
            code="method-step-unknown",
            message=f"{{{{method.{step}}}}} names no step the analysis ran",
            hint=f'mark the code with `with em.step("{step}"):` (R: `em$step("{step}", {{ ... '
            "})`) and run it again; a step in a branch the run did not take is not recorded",
            **where,
        )
    if pair.standing == "unread":
        return Finding(
            gate=GATE,
            code="method-pair-unread",
            message=f"the text pointing at step {step!r} has never been read against its code",
            context=_excerpt(claim.text),
            hint=reconcile_hint,
            **where,
        )
    if pair.standing == "code":
        return Finding(
            gate=GATE,
            code="method-step-changed",
            message=f"step {step!r} changed after the text pointing at it was last read "
            f"against it",
            context=_excerpt(claim.text),
            hint="re-" + reconcile_hint,
            **where,
        )
    if pair.standing == "claim":
        return Finding(
            gate=GATE,
            code="method-claim-changed",
            message=f"the text pointing at step {step!r} changed after it was last read "
            f"against the code",
            context=f"was: {_excerpt(pair.was or '')}",
            hint="re-" + reconcile_hint,
            **where,
        )
    return None


#: What `methods --explain` calls each standing, in a column wide enough for the longest.
_SAID = {
    "read": "read",
    "code": "code changed",
    "claim": "text changed",
    "unread": "never read",
    "unknown": "no such step",
}


def explain_methods(project: Project, results: Results | None = None) -> list[str]:
    """Each claim in the manuscript with the step it points at and how the pair stands, then
    the Methods paragraphs that point at no step, then the steps no text points at. What a
    person reads to check the Methods against the code: every claim beside the lines that
    back it, and what nothing backs."""
    import textwrap

    if results is None:
        from manuscript_guard.contracts import load_namespace

        results = load_namespace(project)[1]
    lock = read_lock(project)
    claims, open_ = anchored(project)
    locked = _locked(lock) if lock.get("analysis") else None
    root = project.root

    def at(path: Path, line: int) -> str:
        return f"{path.relative_to(root).as_posix()}:{line}"

    def said(text: str) -> list[str]:
        return textwrap.wrap(text, width=88, initial_indent=" " * 14, subsequent_indent=" " * 14)

    out = ["The Methods against the code, claim by claim.", ""]
    tally: dict[str, int] = {}
    described: set[str] = set()
    judged = _judged(claims, results.steps, locked)
    for claim in claims:
        for pair in (pair for pair in judged if pair.claim is claim):
            described.add(pair.step)
            tally[pair.standing] = tally.get(pair.standing, 0) + 1
            when = f", read {pair.read_on}" if pair.read_on else ""
            where = pair.found.where if pair.found else "no step of that name ran"
            out.append(
                f"{_SAID[pair.standing]:<13} {at(claim.path, claim.line)}  step "
                f"{pair.step}  {where}{when}"
            )
            if pair.standing == "claim":
                out += said(f"was: {pair.was}")
        out += said(claim.text or "(nothing stands before the anchor)")
        out.append("")
    for paragraph in open_:
        out.append(f"{'open':<13} {at(paragraph.path, paragraph.line)}  no step points here")
        out += said(paragraph.text)
        out.append("")
    alone = [step for name, step in sorted(results.steps.items()) if name not in described]
    for step in alone:
        out.append(f"{'undescribed':<13} step {step.name}  {step.where}  no text points at it")
    if alone:
        out.append("")
    counted = ", ".join(f"{n} {_SAID[k]}" for k, n in sorted(tally.items()) if n)
    out.append(
        f"{sum(tally.values())} pair(s){': ' + counted if counted else ''}; "
        f"{len(open_)} Methods paragraph(s) point at no step; "
        f"{len(alone)} step(s) described by nothing."
    )
    return out


def _compare_parameters(project: Project, lock: dict, namespace: dict[str, Value] | None) -> Report:
    """The few things both sides state explicitly, and where disagreement is checkable.

    Read as the Methods print: a value bound there, `{{results.param.alpha}}`, is stated in
    them, and the source alone does not hold the number.
    """
    report = Report()
    prose = methods_text(project)
    if not prose:
        return report
    if namespace is None:
        from manuscript_guard.contracts import load_namespace

        namespace = load_namespace(project)[0]
    prose = substitute(prose, {ref: value.display for ref, value in namespace.items()})

    declared = lock.get("parameters", {})
    for name, expected in declared.items():
        if str(expected).lower() in prose.lower():
            continue
        report = report.with_findings(
            Finding(
                gate=GATE,
                code="methods-parameter-absent",
                severity=WARN,
                message=f"the Methods do not mention {name} = {expected}",
                path=lock_path(project),
                hint="either the Methods should state it, or it should not be in the lock",
            )
        )
    return report


def reconcile(
    project: Project,
    *,
    parameters: dict | None = None,
    steps: list[str] | None = None,
    results: Results | None = None,
) -> tuple[Path, int]:
    """Record the analysis as it stands. Run after reading the Methods against the code.

    With `steps`, only the pairs of those steps are recorded, each with its claims as they
    now read and its code as it now stands: the files, and every other pair, stay as the lock
    has them, since nobody has re-read those.
    """
    if results is None:
        from manuscript_guard.contracts import load_namespace

        results = load_namespace(project)[1]
    existing = read_lock(project)
    today = date.today().isoformat()
    current = [pair for pair in pairs_of(project, results, None) if pair.found is not None]
    if steps is None:
        analysis = analysis_digests(project)
        reconciled_on = today
        kept: list[dict] = []
        fresh = current
    else:
        unknown = sorted(set(steps) - {pair.step for pair in current})
        if unknown:
            raise ValueError(
                f"no text points at a step named {', '.join(map(repr, unknown))} that the "
                f"analysis ran, so there is no pair to record"
            )
        analysis = existing.get("analysis", {})
        reconciled_on = existing.get("reconciled_on", today)
        kept = [pair for pair in _locked(existing) if pair.get("step") not in steps]
        fresh = [pair for pair in current if pair.step in steps]
    recorded = kept + [
        {"step": pair.step, "claim": pair.claim.text, "code": pair.found.digest, "read_on": today}
        for pair in fresh
        if pair.found is not None
    ]
    document = {
        "schema": "manuscript-guard/methods-lock/1",
        "reconciled_on": reconciled_on,
        "parameters": parameters if parameters is not None else existing.get("parameters", {}),
        "analysis": analysis,
    }
    if recorded:
        unique = {(p["step"], p["claim"]): p for p in recorded}
        document["pairs"] = sorted(unique.values(), key=lambda p: (p["step"], p["claim"]))
    path = lock_path(project)
    header = (
        "# Records the analysis as it stood when the Methods were last read against it.\n"
        "# Written by `manuscript-guard methods --reconcile`. Re-run it after you have\n"
        "# re-read the Methods, not merely after the code changed: the point of the file\n"
        "# is that a person looked.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
        newline="\n",
    )
    return path, len(analysis) if steps is None else len(fresh)
