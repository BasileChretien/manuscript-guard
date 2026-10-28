"""The Methods against the code: does this Methods text describe what this code does?

G9 records that someone read a claim of the Methods against the step of the analysis it points
at, and names the pair when either changes. Whether the text describes the code correctly is
still a person's to say, and it is a question a co-author who wrote the analysis, or reviewed
it, can answer where the author cannot see their own slip. So each G9 claim is an item:

* **one item per claim**, exactly as `gates/methods.anchored` reads them. Anchors side by side
  claim one text, and that text is one item showing every step it points at. A claim naming a
  step the run never recorded, and one that claims no text, are not sent: `build` prints a line
  for each, since G9 fails the first and there is nothing to ask of the second.
* **one item per Methods paragraph that points at no step** (decision 2 (a) of Task 1): what G9
  counts as open, a paragraph in a section G9 reads as the Methods, the main text's or the
  supplement's, holding no anchor. It is asked with "no code is linked to this text", so the
  co-author can say which code it describes, or that none does.

**The identifier** is the file, relative to `manuscript/`, the steps, and the claim's place
among the claims of those steps in that file: not the words. Editing the text then makes the
answer about it stale, which keeps its note and asks again, rather than leaving it about an
item the project no longer has.

**The digest** covers the claim with its values filled in, each `results.` value it binds with
the value as printed, the steps, the script each is in, and each step's code digest as G9
reads it (decision 1 (a)): the code read as code, so a comment edited or a call re-wrapped, and
the run made again, keeps the answers, and a change to what the code does stales them. The lines
of code shown are not in it, nor where they stand, nor the warning that the script changed since
the run (`items._words_of`): those are how to read the code and the state of one machine's
files, and the code digest already says whether the code is the code that was answered about.

**Not shown**: how the pair stands in `methods.lock`. "Read on 2026-10-02, code unchanged" is
the answer given before the co-author has read anything.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.contracts.results import Step
from manuscript_guard.text.placeholders import parse

GROUP = {
    "id": "methods",
    "title": "Methods against the code",
    "ask": "Does this Methods text describe what this code does?",
    "seconds": 60,
    "answers": [
        {"status": "ok", "label": "Text matches the code"},
        {"status": "wrong", "label": "Text needs changing"},
        {"status": "code", "label": "Code needs changing"},
        {"status": "unsure", "label": "Not sure"},
    ],
}
#: What an open paragraph's item says in place of its steps.
NO_CODE = "no code is linked to this text"
#: The note on each block of a script that changed since the run that recorded the step.
CHANGED = (
    "this script has changed since the run that recorded this step, so the code shown may not "
    "be what ran"
)
UNRECORDED = (
    "the run did not record a digest of this script, so whether the code shown is what ran "
    "cannot be told"
)


@dataclass(frozen=True)
class Ran:
    """What the build knows of the code each step ran: the steps the results record, where the
    scripts are, and which scripts differ from the ones the runs recorded."""

    steps: dict[str, Step]
    root: Path
    #: Scripts, as the fragments name them, whose content is not what the run recorded.
    changed: frozenset[str] = field(default_factory=frozenset)
    #: Scripts whose fragment records no digest of them.
    unrecorded: frozenset[str] = field(default_factory=frozenset)


def ran_of(project, results) -> Ran:
    """The steps of `results`, each script held to the digest its fragment recorded."""
    from manuscript_guard.emit import source_digest_matches

    fragments = {fragment.path: fragment for fragment in results.fragments}
    changed: set[str] = set()
    unrecorded: set[str] = set()
    for step in results.steps.values():
        script = project.root / step.script
        if not script.is_file():
            continue  # the evidence says it cannot be read
        fragment = fragments.get(step.source)
        declared = fragment.generated_by_sha256 if fragment is not None else None
        if not declared:
            unrecorded.add(step.script)
        elif not source_digest_matches(script, declared):
            changed.add(step.script)
    return Ran(dict(results.steps), project.root, frozenset(changed), frozenset(unrecorded))


def _identifier(*parts: str) -> str:
    from manuscript_guard.checking.produce import _identifier as made

    return made(*parts)


def _short(text: str) -> str:
    from manuscript_guard.checking.produce import _short as cut

    return cut(text, 100)


def _section(path: Path, folder: Path) -> str:
    """The file as a co-author is told it: relative to `manuscript/`, so a supplement's Methods
    say they are the supplement's."""
    try:
        return Path(path).relative_to(folder).as_posix()
    except ValueError:
        return Path(path).name


def bound(text: str, shown: dict[str, str]) -> tuple[str, list[str], list[list[str]]]:
    """A claim as a co-author reads it: each value it binds filled in, a binding nothing
    resolves by its name in brackets, and anchors gone; the values to mark; and each `results.`
    value it binds, once, with the value as printed, for the facts."""
    placeholders, _ = parse(text)
    out = text
    for found in sorted(placeholders, key=lambda p: p.start, reverse=True):
        said = "" if found.is_anchor else shown.get(found.ref, f"[{found.ref}]")
        out = out[: found.start] + said + out[found.end :]
    marks: list[str] = []
    facts: list[list[str]] = []
    for found in placeholders:
        if found.is_anchor or found.ref not in shown and not found.ref.startswith("results."):
            continue
        if found.ref in shown and shown[found.ref] not in marks:
            marks.append(shown[found.ref])
        if found.ref.startswith("results.") and all(row[0] != found.ref for row in facts):
            facts.append([found.ref, shown.get(found.ref, "not in the results")])
    return " ".join(out.split()), marks, facts


def method_items(
    claims, open_, *, folder: Path, ran: Ran, shown: dict[str, str]
) -> tuple[list[dict], list[str]]:
    """The items of the methods group, in the order of the files and of their lines, and the
    lines `build` prints: for each claim not sent, and for each script that changed since its
    run."""
    notes: list[str] = []
    placed: dict[str, list[tuple[int, dict]]] = {}
    count: dict[tuple[str, tuple[str, ...]], int] = {}
    used: dict[str, list[str]] = {}

    def nth(section: str, steps: tuple[str, ...]) -> int:
        n = count.get((section, steps), 0)
        count[(section, steps)] = n + 1
        return n

    for claim in claims:
        section = _section(claim.path, folder)
        n = nth(section, claim.steps)
        anchors = "".join(f"{{{{method.{step}}}}}" for step in claim.steps)
        unknown = [step for step in claim.steps if step not in ran.steps]
        if unknown:
            notes.append(
                f"methods: {section}:{claim.anchor_line}: "
                + ", ".join(f"{{{{method.{step}}}}}" for step in unknown)
                + " names no step the analysis ran, so its text is not sent"
            )
            continue
        if not claim.text:
            notes.append(f"methods: {section}:{claim.anchor_line}: {anchors} claims no text, "
                         "so nothing is sent for it")  # fmt: skip
            continue
        for step in claim.steps:
            used.setdefault(ran.steps[step].script, []).append(step)
        item = _claim_item(claim, section, n, ran, shown)
        placed.setdefault(section, []).append((claim.line, item))
    for paragraph in open_:
        section = _section(paragraph.path, folder)
        item = _open_item(paragraph, section, nth(section, ()), shown)
        placed.setdefault(section, []).append((paragraph.line, item))

    for script in sorted(used):
        said = ", ".join(dict.fromkeys(used[script]))
        if script in ran.changed:
            notes.append(f"methods: {script} has changed since the run that recorded step(s) "
                         f"{said}, so the code a co-author is shown may not be what ran; run it "
                         "again before sending the round")  # fmt: skip
    items = [item for section in placed for _line, item in sorted(placed[section],
             key=lambda pair: pair[0])]  # fmt: skip
    return items, notes


def _claim_item(claim, section: str, n: int, ran: Ran, shown: dict[str, str]) -> dict:
    text, marks, values = bound(claim.text, shown)
    facts = [["Steps", ", ".join(claim.steps)]]
    evidence: list[dict] = []
    for name in claim.steps:
        step = ran.steps[name]
        facts.append([f"Step {name}", f"{step.script} (code digest {step.digest[:16]})"])
        evidence += code_blocks(step, ran)
    return {
        "id": _identifier("method", section, "+".join(claim.steps), str(n)),
        "group": GROUP["id"],
        "title": _short(f"{'+'.join(claim.steps)}: {text}"),
        "facts": facts + values,
        "sentences": [{"text": text, "section": section, "line": claim.line, "mark": marks}],
        "evidence": evidence,
    }


def _open_item(paragraph, section: str, n: int, shown: dict[str, str]) -> dict:
    text, marks, values = bound(paragraph.text, shown)
    return {
        # No steps: an open paragraph's place among the open paragraphs of its file.
        "id": _identifier("method", section, "", str(n)),
        "group": GROUP["id"],
        "title": _short(f"no code: {text}"),
        "facts": [["Steps", f"none: {NO_CODE}"], *values],
        "sentences": [{"text": text, "section": section, "line": paragraph.line,
                       "mark": marks}],  # fmt: skip
        "evidence": [
            {
                "kind": "none",
                "caption": NO_CODE,
                "note": "No step of the analysis is marked as what this text describes. Say "
                "whether it describes the analysis as you know it, and, if you know, which "
                "code it describes, or that it describes no code (an ethics approval, a data "
                "source).",
            }
        ],
    }


def code_blocks(step: Step, ran: Ran) -> list[dict]:
    """The code of one step as a co-author reads it, read from the script on disk: its body,
    and for a Python script each function it calls that the script defines, as the run
    followed them, each a block of numbered lines. R gives its body only."""
    script = ran.root / step.script
    caption = f"step {step.name}, in {step.script}"
    warning = (CHANGED if step.script in ran.changed
               else UNRECORDED if step.script in ran.unrecorded else None)  # fmt: skip
    try:
        source = script.read_text(encoding="utf-8", errors="replace")
    except OSError:
        unread = f"{step.script} cannot be read here, so its code is not shown"
        return [{"kind": "code", "caption": caption, "lines": [], "note": unread}]
    lines = source.splitlines()
    blocks = [_block(caption, lines, step.lines, warning,
                     "the run recorded no lines for this step")]  # fmt: skip
    if script.suffix.lower() == ".py":
        spans = functions_in(source)
        for name in step.follows:
            blocks.append(_block(f"function {name}, which step {step.name} calls, in "
                                 f"{step.script}", lines, spans.get(name), warning,
                                 f"{name} is not defined in the script as it is now"))  # fmt: skip
    return blocks


def _block(caption: str, lines: list[str], span: tuple[int, int] | None,
           warning: str | None, missing: str) -> dict:  # fmt: skip
    block: dict = {"kind": "code", "caption": caption, "lines": []}
    if span is None:
        block["note"] = missing
        return block
    first, last = span
    block["lines"] = [[number, lines[number - 1]] for number in range(first, last + 1)
                      if 0 < number <= len(lines)]  # fmt: skip
    if warning:
        block["note"] = warning
    return block


def functions_in(source: str) -> dict[str, tuple[int, int]]:
    """Where each function the script defines at its top level stands, decorators included:
    the functions `emit.step_code` follows a step into."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return {}
    return {
        node.name: (min([node.lineno, *(d.lineno for d in node.decorator_list)]),
                    node.end_lineno or node.lineno)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }  # fmt: skip
