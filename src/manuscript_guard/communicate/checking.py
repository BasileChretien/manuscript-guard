"""`communicate check`: every communication text held to the brief, and the brief to the paper.

What is read, all under `communication/`: the brief (`brief.yaml`), each text (`*.md`, with
front matter naming its channel), and the graphical abstract (`graphical-abstract/`). A
failure is listed apart from a warning, and the command exits 1 on a failure.

**The brief.** Each statement's quote is a sentence of the file it names
(`brief-quote-not-in-source`); its text says no more than its quote, as a text says no more
than its statement; one finding is marked primary (`comm-primary-missing`).

**The numbers.** A number typed into a text that is no convention fails, as G2 fails one in
the paper (`comm-number-unbound`); a binding names a value the analysis emits
(`comm-binding-unknown`) that the paper reports, in its Methods or Results, its supplement,
a table or a figure (`comm-not-reported`). A text that tells the whole finding states the
primary one (`comm-primary-missing`), and one that leads with a secondary finding is warned
(`comm-secondary-as-primary`).

**Fidelity.** A sentence that claims (`texts.py`) is anchored to the statement it restates
(`comm-claim-unanchored`, decision 2 of 2026-10-28). An anchored sentence states no fact,
binding, citation or number its statements do not (`comm-fact-not-in-source`), and claims
no more than they do (`claims.compare_pair`): a hedge or a limit dropped, a word moved up
the ladder, a negation gone or new, fails (`comm-claim-stronger`), and a move both ways
fails too (`comm-claim-moved`), unless the text's front matter allows the sentence with a
reason (decision 1); a claim made weaker is a warning (`comm-claim-weaker`). A press
release, a plain-language summary and a pitch state a limitation (`comm-limitation-dropped`).

**The paper's status** (`status.py`): `comm-status-ahead`, `comm-doi-malformed`,
`comm-link-temporary`.

**The graphical abstract.** Each image is held to the journal's `graphical_abstract` rules
as G4 holds a figure (format, file size, smallest text), and to its size, aspect ratio,
words and labels (`comm-ga-size`, `comm-ga-aspect`, `comm-ga-words`, `comm-ga-labels`, each
a warning as G4's are), with a note where the journal gives no size (`comm-ga-size-default`);
its colours as G3 holds a figure's; each line of an SVG to the statement it names
(`comm-ga-text-not-in-statement`) and each value it prints to the results now
(`comm-ga-stale`); its numbers as a text's; and its alternative text, `alt-text.md`, as G3
holds a figure's (`comm-alt-missing`, `comm-alt-long`, and G3's `figure-alt-number` and
`figure-alt-binding`).

**The words.** G6 reads each text as printed, each binding its display: a model's artefact
fails, the rest warns.

**The platform.** A post longer than its channel takes fails (`comm-over-limit`), by the
limits of `data/channels.yaml` or paper.yaml's `communication.limits`.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard import claims
from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.communicate import (
    GATE,
    folder,
    graphical_abstract_folder,
    require_enabled,
)
from manuscript_guard.communicate import texts as texts_module
from manuscript_guard.communicate.brief import Brief, fold, load, quote_findings
from manuscript_guard.communicate.status import paper_doi_findings, status_findings
from manuscript_guard.contracts import load_namespace
from manuscript_guard.contracts._schema import read_text
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.reworded import facts
from manuscript_guard.text.masking import mask
from manuscript_guard.text.placeholders import VALUE_NAMESPACES, parse, substitute
from manuscript_guard.text.tokens import find_atoms

CHANNELS = Path(__file__).parent.parent / "data" / "channels.yaml"
#: What `--only` takes.
PARTS = ("brief", "texts", "graphical-abstract")
ALT_TEXT = "alt-text.md"
VALIDATION_REPORT = "validation-report.md"
CONCEPT = "concept.md"
#: The files under the graphical abstract's folder that are text the group writes, not
#: images.
_WRITTEN = frozenset({ALT_TEXT, VALIDATION_REPORT, CONCEPT})
_IMAGES = (".svg", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf", ".eps")
_URL = re.compile(r"https?://\S+")
#: How far a drawn aspect ratio may stand from the journal's and still be it: a pixel of
#: rounding.
_ASPECT_TOLERANCE = 0.01
#: The code each way `claims.compare_pair` tells a claim moved is given: a negation gone or
#: new turns the claim round, which says more than the paper did (decision 1 of 2026-10-28).
CLAIM_CODES = {
    claims.STRONGER: "comm-claim-stronger",
    claims.NEGATION: "comm-claim-stronger",
    claims.WEAKER: "comm-claim-weaker",
    claims.MOVED: "comm-claim-moved",
}


@lru_cache(maxsize=1)
def channels() -> dict:
    document = yaml.safe_load(CHANNELS.read_text(encoding="utf-8"))
    return document["channels"]


@dataclass(frozen=True)
class Context:
    project: object
    namespace: dict
    brief: Brief | None
    classifier: Classifier
    reported: frozenset[str]
    printed_elsewhere: str


def _finding(code: str, message: str, path: Path, *, line: int | None = None,
             severity: str = FAIL, context: str | None = None, hint: str | None = None
             ) -> Finding:  # fmt: skip
    return Finding(GATE, code, message, severity, path, line, None, context, hint)


# --------------------------------------------------------------------------- the entry


def check(project, only: str | None = None) -> Report:
    """Every finding of `communicate check`, or of one part of it (`only`)."""
    require_enabled(project)
    namespace, results, _literature, _load = load_namespace(project)
    brief, report = load(project)
    context = Context(
        project,
        namespace,
        brief,
        Classifier.load(project.extra_conventions, project.extra_terms),
        _reported_keys(project, results),
        _printed_elsewhere(project, results),
    )
    if only in (None, "brief"):
        report = report.merge(_brief_report(context))
    if only in (None, "texts"):
        paper = project.root / "paper.yaml"
        report = report.merge(Report(tuple(paper_doi_findings(project, paper))))
        report = report.merge(_texts_report(context))
    if only in (None, "graphical-abstract"):
        report = report.merge(_graphical_abstract_report(context))
    return report


def _reported_keys(project, results) -> frozenset[str]:
    """Every value the paper binds, main text and supplement, and each declared the same
    quantity as one it binds."""
    from manuscript_guard.text.reader import bound_files

    bound = {p.ref for one in bound_files(project) for p in one.placeholders
             if p.namespace in VALUE_NAMESPACES}  # fmt: skip
    same = {f"results.{value.same_as}" for key, value in results.values.items()
            if value.same_as and f"results.{key}" in bound}  # fmt: skip
    same |= {f"results.{key}" for key, value in results.values.items()
             if value.same_as and f"results.{value.same_as}" in bound}  # fmt: skip
    return frozenset(bound | same)


def _printed_elsewhere(project, results) -> str:
    """The text of every table and figure the paper places, as G8 reads it."""
    from manuscript_guard.gates.reported import _printed
    from manuscript_guard.text.reader import bound_files

    placed: dict[str, set[str]] = {"table": set(), "figure": set()}
    for one in bound_files(project):
        for p in one.placeholders:
            if p.namespace in placed:
                placed[p.namespace].add(p.key)
    return _printed(project, results, placed)


# ---------------------------------------------------------------------- what is shared


def _bindings(context: Context, text: str, path: Path, line_of) -> list[Finding]:
    """`comm-binding-unknown` and `comm-not-reported` for each binding of `text`."""
    from manuscript_guard.gates.reported import _shows

    placeholders, malformed = parse(text)
    found = []
    for placeholder in placeholders:
        if placeholder.is_anchor:
            continue
        line = line_of(placeholder.start)
        if placeholder.namespace not in VALUE_NAMESPACES:
            found.append(_finding("comm-binding-unknown",
                                  f"{placeholder.raw} prints no value: a table, a figure or a "
                                  "pointer has no place in a communication", path, line=line,
                                  hint="quote a value, {{results.key}} or {{lit.key}}"))
            continue
        value = context.namespace.get(placeholder.ref)
        if value is None:
            found.append(_finding("comm-binding-unknown",
                                  f"{placeholder.raw} names a value nothing emits", path,
                                  line=line, hint="`manuscript-guard bind` lists the keys"))
        elif (placeholder.namespace == "results" and placeholder.ref not in context.reported
              and not _shows(context.printed_elsewhere, value.display)):  # fmt: skip
            found.append(_finding(
                "comm-not-reported",
                f"{placeholder.raw} is a value the paper reports nowhere: no file of the "
                "manuscript binds it, and no table or figure it places prints it",
                path, line=line,
                hint="a communication says what the paper says: report the value in the "
                "paper first, or leave it out",
            ))  # fmt: skip
    found += [_finding("comm-binding-unknown", f"{raw} is not a binding", path, line=line,
                       hint="a binding is {{results.key}} or {{lit.key}}")
              for raw, _start, line in malformed]  # fmt: skip
    return found


def _numbers(context: Context, text: str, path: Path) -> list[Finding]:
    """`comm-number-unbound` for each number typed into `text` that no rule accepts."""
    scan = context.classifier.scan(text)
    found = []
    for atom in find_atoms(text, mask(text)):
        if context.classifier.classify(atom, None, scan).kind != UNCLASSIFIED:
            continue
        found.append(_finding(
            "comm-number-unbound",
            f"{atom.text!r} is typed, and bound to nothing: a number a communication gives "
            "is the paper's, and is quoted by binding",
            path, line=atom.line, context=atom.line_text.strip()[:160],
            hint="write {{results.key}} for the value, so the text cannot disagree with the "
            "analysis; a number that is no result is declared in paper.yaml, as in the paper",
        ))  # fmt: skip
    return found


def _facts(text: str) -> set[tuple[str, str]]:
    return {fact.key for fact in facts(text)}


def _shown(keys: set[tuple[str, str]]) -> str:
    return ", ".join(text if kind == "number" else ("{{" + text + "}}" if kind == "binding"
                                                    else "@" + text)
                     for kind, text in sorted(keys))  # fmt: skip


def _fidelity(context: Context, said: str, source: str, ids: str, path: Path, line: int,
              allowed: str | None) -> list[Finding]:  # fmt: skip
    """What a sentence restating `source` says beyond it: facts, and a claim made
    stronger, weaker or moved."""
    found = []
    beyond = _facts(said) - _facts(source)
    if beyond:
        found.append(_finding(
            "comm-fact-not-in-source",
            f"it gives {_shown(beyond)}, which {ids} does not",
            path, line=line, context=fold(said)[:160],
            hint="say only what the statement says, or anchor the sentence to the statement "
            "that gives it",
        ))  # fmt: skip
    return found + _claimed(said, source, ids, path, line, allowed)


def _claimed(said: str, source: str, ids: str, path: Path, line: int | None,
             allowed: str | None) -> list[Finding]:  # fmt: skip
    """How strongly `said` claims against `source` (`claims.compare_pair`), as a finding."""
    found = []
    moved = claims.compare_pair(source, said)
    if moved is not None:
        parts = moved.message.split(": ", 1)[-1]
        code = CLAIM_CODES[moved.code]
        what = {"comm-claim-stronger": "it claims more than",
                "comm-claim-weaker": "it claims less than",
                "comm-claim-moved": "it claims otherwise than"}[code]  # fmt: skip
        severity = WARN if code == "comm-claim-weaker" else FAIL
        hint = ("keep the words that set how strongly the paper claims: its hedges, its "
                "limits, its negations, and association where it found an association")
        if severity == FAIL and allowed is not None:
            severity, hint = INFO, f"allowed in the text's front matter: {allowed}"
        elif severity == FAIL:
            hint += ("; where the stronger words are right, allow the sentence in the text's "
                     "front matter, `allow: [{sentence: <its words>, reason: <why>}]`")
        found.append(_finding(code, f"{what} {ids}: {parts}", path, line=line,
                              severity=severity, context=fold(said)[:160], hint=hint))  # fmt: skip
    return found


# ------------------------------------------------------------------------------ the brief


def _brief_report(context: Context) -> Report:
    brief = context.brief
    project = context.project
    from manuscript_guard.communicate import brief_path

    if brief is None:
        path = brief_path(project)
        if path.is_file():
            return Report()  # the brief's shape was reported where it was read
        return Report((_finding("brief-missing", "there is no brief: every communication "
                                "is held to it", path,
                                hint="write it with `manuscript-guard communicate brief`, "
                                "then mark the primary finding"),))  # fmt: skip
    found = quote_findings(project, brief)
    line_of = _brief_lines(brief.path)
    for statement in brief.statements:
        line = line_of(statement.id)
        found += _bindings(context, statement.text, brief.path, lambda _at, n=line: n)
        found += [replace(one, line=line) for one in _numbers(context, statement.text,
                                                                brief.path)]  # fmt: skip
        found += _fidelity(context, statement.text, statement.quote,
                           f"its quote ({statement.id})", brief.path, line, None)  # fmt: skip
        for key in statement.keys:
            if key not in context.namespace:
                found.append(_finding("comm-binding-unknown",
                                      f"{statement.id} lists {key}, a value nothing emits",
                                      brief.path, line=line))  # fmt: skip
    if brief.of("findings") and not brief.primary:
        found.append(_finding(
            "comm-primary-missing",
            "no finding of the brief is marked primary, so nothing can say which result "
            "is the paper's main one",
            brief.path,
            hint="mark the paper's primary finding `primary: true`: the author's choice, "
            "which nothing infers",
        ))  # fmt: skip
    return Report(tuple(found))


def _brief_lines(path: Path):
    """The line each statement's id is written on, for a finding to point at."""
    lines: dict[str, int] = {}
    for number, line in enumerate(read_text(path).splitlines(), 1):
        found = re.match(r"\s*-?\s*id:\s*['\"]?([^'\"\s]+)", line)
        if found:
            lines.setdefault(found.group(1), number)
    return lambda statement_id: lines.get(statement_id)


# ---------------------------------------------------------------------------- the texts


def text_files(project) -> list[Path]:
    """Each communication text: every `.md` directly under `communication/`."""
    root = folder(project)
    return sorted(path for path in root.glob("*.md") if path.is_file()) if root.is_dir() else []


def _texts_report(context: Context) -> Report:
    report = Report()
    for path in text_files(context.project):
        report = report.merge(Report(tuple(_text_findings(context, path))))
    return report.with_counts(communication_texts=len(text_files(context.project)))


@dataclass(frozen=True)
class _Allow:
    """An entry of a text's `allow:`: the sentence it names, as compared, and its reason."""

    sentence: str
    reason: str
    shown: str


def _compared(sentence: str) -> str:
    """A sentence as an `allow:` entry is compared with it: its anchors taken out, its white
    space one space, no space before a mark, and no closing stop."""
    sentence = _ANCHOR_WRITTEN.sub(" ", texts_module.LINK.sub(" ", sentence))
    return _SPACE_BEFORE.sub(r"\1", fold(sentence)).rstrip(".!?").rstrip()


#: An anchor written as a comment, as an `allow:` entry may copy it.
_ANCHOR_WRITTEN = re.compile(r"<!--[ \t\n]*brief:[^>]*-->")


_SPACE_BEFORE = re.compile(r" ([.,;:!?)])")


def _allows(front: dict, path: Path) -> tuple[list[_Allow], list[Finding]]:
    """The entries of `allow:` that name a sentence and give a reason, and a warning for
    each that names one and gives none, which allows nothing."""
    allowed = front.get("allow")
    if not isinstance(allowed, list):
        return [], []
    out, unreasoned = [], []
    for entry in allowed:
        if not isinstance(entry, dict):
            continue
        sentence, reason = entry.get("sentence"), entry.get("reason")
        if not isinstance(sentence, str) or not sentence.strip():
            continue
        if isinstance(reason, str) and reason.strip():
            out.append(_Allow(_compared(sentence), reason.strip(), fold(sentence)))
        else:
            unreasoned.append(_finding(
                "comm-allow-no-reason",
                f"the front matter allows '{fold(sentence)}' and gives no reason, so it allows "
                "nothing", path, line=1, severity=WARN,
                hint="give the reason under `reason:`, why the stronger words are right",
            ))  # fmt: skip
    return out, unreasoned


def _text_findings(context: Context, path: Path) -> list[Finding]:
    raw = read_text(path)
    read = texts_module.read(raw)
    text = read.blanked
    found: list[Finding] = []
    if read.front_error:
        found.append(_finding("comm-front-matter", f"{path.name}: {read.front_error}", path,
                              line=1, hint="write it as YAML between two lines of ---"))
    channel = read.front.get("channel")
    channel = channel if isinstance(channel, str) else ""
    rules = channels().get(channel, {})
    starts = [0, *(at.end() for at in re.finditer("\n", text))]

    def line_of(at: int) -> int:
        return sum(1 for start in starts if start <= at)

    def in_place(whole: str) -> str:
        # The body, the front matter blanked in place so that every offset and line holds.
        head = "".join(char if char == "\n" else " " for char in whole[: read.body_start])
        return head + whole[read.body_start :]

    in_body = in_place(text)
    found += _bindings(context, in_body, path, line_of)
    found += _numbers(context, in_place(read.readable), path)
    brief = context.brief
    statements = brief.by_id if brief is not None else {}
    allows, unreasoned = _allows(read.front, path)
    found += unreasoned
    used: set[str] = set()
    anchored: list[str] = []
    for anchor in read.anchors:
        if anchor.id not in statements:
            found.append(_finding(
                "comm-anchor-unknown",
                f"an anchor names {anchor.id}, which is no statement of the brief",
                path, line=line_of(anchor.start),
                hint="name a statement's id as brief.yaml writes it, `findings.1`",
            ))  # fmt: skip
    for sentence in read.sentences:
        ids = [one for one in sentence.anchors if one in statements]
        anchored += ids
        if sentence.claims and not sentence.anchors:
            found.append(_finding(
                "comm-claim-unanchored",
                f"this sentence claims ({sentence.why}) and names no statement of the brief "
                "it restates",
                path, line=sentence.line, context=sentence.text[:160],
                hint="anchor it to the statement it restates, [](#brief:findings.1), which "
                "prints nothing; or say it without the claim",
            ))  # fmt: skip
        if not ids:
            continue
        source = " ".join(statements[one].quote for one in ids)
        said = read.readable[sentence.start : sentence.end]
        entry = next((one for one in allows if one.sentence == _compared(sentence.text)), None)
        told = _fidelity(context, said, source, f"the brief's {', '.join(ids)}", path,
                         sentence.line, None if entry is None else entry.reason)  # fmt: skip
        if entry is not None and any(one.severity == INFO for one in told):
            used.add(entry.sentence)
        found += told
    for entry in allows:
        if entry.sentence not in used:
            found.append(_finding(
                "comm-allow-unused", f"the front matter allows '{entry.shown}', and no "
                "anchored sentence that is those words claims more than its statement",
                path, line=1, severity=WARN,
                hint="take the entry out, or copy the whole sentence into it as it stands",
            ))  # fmt: skip
    found += _story(context, path, rules, anchored, channel)
    printed = _printed(context, in_body)
    found += status_findings(context.project, path, printed)
    found += _words(path, printed)
    found += _limits(context, path, channel, rules, read)
    return found


def _printed(context: Context, text: str) -> str:
    """`text` as printed: each binding its display, each anchor nothing."""
    return substitute(text, {ref: value.display for ref, value in context.namespace.items()})


def _story(context: Context, path: Path, rules: dict, anchored: list[str], channel: str
           ) -> list[Finding]:  # fmt: skip
    """The primary finding stated where the text tells the whole finding, not led by a
    secondary one, and a limitation stated where the channel asks for one."""
    brief = context.brief
    if brief is None:
        return []
    found = []
    primary = {one.id for one in brief.primary}
    findings = {one.id for one in brief.of("findings")}
    if rules.get("long_form") and primary and not primary & set(anchored):
        found.append(_finding(
            "comm-primary-missing",
            f"a {channel} tells the whole finding, and this one states no primary finding of "
            f"the brief ({', '.join(sorted(primary))})",
            path, hint="state the primary finding, anchored to its statement",
        ))  # fmt: skip
    first = next((one for one in anchored if one in findings), None)
    if primary and first is not None and first not in primary:
        found.append(_finding(
            "comm-secondary-as-primary",
            f"the first finding it states is {first}, a secondary one, and a reader takes "
            "the first for the main result",
            path, severity=WARN,
            hint=f"lead with the primary finding ({', '.join(sorted(primary))})",
        ))  # fmt: skip
    limits = {one.id for one in brief.of("limitations")}
    if rules.get("limitations") and not limits & set(anchored):
        found.append(_finding(
            "comm-limitation-dropped",
            f"a {channel} states a limitation of the study, and this one anchors none of the "
            "brief's",
            path, hint="say what the study cannot show, anchored to its statement in the brief",
        ))  # fmt: skip
    return found


def _words(path: Path, printed: str) -> list[Finding]:
    """What G6 says of the text as printed: a model's artefact fails, the rest warns."""
    from manuscript_guard.gates.writing import judge_texts

    report, _totals = judge_texts([(path, printed)])
    return [replace(one, gate=GATE, severity=FAIL if one.code == "model-artefact" else WARN)
            for one in report.findings if one.severity in (FAIL, WARN)]  # fmt: skip


def graphemes(text: str) -> int:
    """How many characters a reader sees in `text`: a combining mark, a variation selector,
    a skin tone and what a zero-width joiner joins count with the character before them.
    Close to Unicode's grapheme clusters, not the same (DESIGN.md, Known gaps)."""
    count = 0
    joined = False
    for char in text:
        point = ord(char)
        if joined:
            joined = False
            continue
        if point == 0x200D:
            joined = True
            continue
        if unicodedata.combining(char) or 0xFE00 <= point <= 0xFE0F or 0x1F3FB <= point <= 0x1F3FF:
            continue
        count += 1
    return count


def _limits(context: Context, path: Path, channel: str, rules: dict, read) -> list[Finding]:
    """Each post of a text against its channel's length, as printed: each binding its
    display, each anchor and each comment nothing."""
    setting = context.project.setting("communication") or {}
    own = (setting.get("limits") or {}).get(channel) if isinstance(setting, dict) else None
    limit = own if isinstance(own, int) and not isinstance(own, bool) else rules.get("limit")
    if not isinstance(limit, int):
        return []
    from manuscript_guard.text.masking import blank_comments

    found = []
    for number, (low, high) in enumerate(read.posts, 1):
        post = _printed(context, read.blanked[low:high])
        post = blank_comments(post) if "<!--" in post else post
        post = post.replace("\x00", "").strip()
        if not post:
            continue
        if rules.get("url_counts_as"):
            post = _URL.sub("x" * int(rules["url_counts_as"]), post)
        length = graphemes(post) if rules.get("unit") == "graphemes" else len(post)
        if length > limit:
            unit = rules.get("unit") or "characters"
            whence = "paper.yaml's communication.limits" if own == limit else (
                f"{rules.get('source', 'data/channels.yaml')}, "
                + (f"read {rules['read_on']}" if rules.get("verified") and rules.get("read_on")
                   else "not read on that page")
            )  # fmt: skip
            found.append(_finding(
                "comm-over-limit",
                f"post {number} is {length} {unit} printed, and {channel} takes {limit} "
                f"({whence})",
                path, hint="shorten it, or part it into a thread at a line of --- after a "
                "blank line",
            ))  # fmt: skip
    return found


# ------------------------------------------------------------------- the graphical abstract


def images(project) -> list[Path]:
    root = graphical_abstract_folder(project)
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir()
                  if path.is_file() and path.suffix.lower() in _IMAGES)  # fmt: skip


def journal_rules(project) -> tuple[dict, Path | None]:
    """The target journal's `graphical_abstract` rules, and its profile's path."""
    from manuscript_guard.gates.journal import _profile, profile_path

    document = _profile(project)
    slug = project.target_journal
    path = profile_path(project, slug) if slug and document is not None else None
    rules = (document or {}).get("graphical_abstract")
    return (rules if isinstance(rules, dict) else {}), path


def _as_figure_rules(rules: dict) -> dict:
    """The graphical abstract's rules in the shape G4 holds a figure to."""
    out = {key: rules[key] for key in ("formats", "max_file_mb", "min_text_pt") if key in rules}
    if "min_dpi" in rules:
        out["min_dpi"] = dict.fromkeys(("halftone", "combination", "line_art"), rules["min_dpi"])
    return out


def _graphical_abstract_report(context: Context) -> Report:
    project = context.project
    drawn = images(project)
    if not drawn:
        return Report()
    rules, profile = journal_rules(project)
    from manuscript_guard.gates.figure_files import check_file
    from manuscript_guard.gates.journal import figure_rules

    grey = figure_rules(project).get("print") == "greyscale"
    found: list[Finding] = []
    if not any(key in rules for key in ("width_px", "height_px", "min_width_px",
                                        "min_height_px", "aspect_ratio")):  # fmt: skip
        from manuscript_guard.communicate.svg import DEFAULT_HEIGHT, DEFAULT_WIDTH

        found.append(_finding(
            "comm-ga-size-default",
            "the journal's profile gives no size for a graphical abstract, so its size is "
            f"not checked; the concepts are drawn at the default, {DEFAULT_WIDTH} by "
            f"{DEFAULT_HEIGHT} pixels",
            graphical_abstract_folder(project), severity=INFO,
            hint="where the journal states a size, record it under graphical_abstract in its "
            "profile, quoted (the journal-profile skill)",
        ))  # fmt: skip
    figure = _as_figure_rules(rules)
    for path in drawn:
        found += [replace(one, gate=GATE)
                  for one in check_file(path, figure, profile or path)]  # fmt: skip
        found += _dimensions(path, rules)
        from manuscript_guard.gates.figure_colours import colour_findings

        coloured = colour_findings(path, "graphical abstract", greyscale=grey)
        found += [replace(one, gate=GATE) for one in coloured or ()]
        if path.suffix.lower() == ".svg":
            found += _svg_text(context, path, rules)
        elif path.suffix.lower() == ".pdf":
            found += _pdf_text(context, path)
    found += _alt(context, rules)
    return Report(tuple(found)).with_counts(graphical_abstract_images=len(drawn))


def _pixels(path: Path) -> tuple[float, float] | None:
    from manuscript_guard.gates.figure_files import raster_of
    from manuscript_guard.gates.figure_svg import _length

    if path.suffix.lower() == ".svg":
        try:
            root = ET.fromstring(read_text(path))
        except (ET.ParseError, ValueError):
            return None
        width, height = root.get("width"), root.get("height")
        sized = (_length(width, 0) if width else None, _length(height, 0) if height else None)
        if None not in sized:
            return sized  # type: ignore[return-value]
        view = (root.get("viewBox") or "").replace(",", " ").split()
        if len(view) == 4:
            try:
                return float(view[2]), float(view[3])
            except ValueError:
                return None
        return None
    raster = raster_of(path)
    return (float(raster.width), float(raster.height)) if raster is not None else None


def _dimensions(path: Path, rules: dict) -> list[Finding]:
    from manuscript_guard.communicate.svg import _ratio

    size = _pixels(path)
    if size is None:
        return []
    width, height = size
    hint = "draw it again at the journal's size (`communicate graphical-abstract`)"
    found = []
    for key, value, what in (("width_px", width, "wide"), ("height_px", height, "high")):
        wanted = rules.get(key)
        if isinstance(wanted, int) and round(value) != wanted:
            found.append(_finding("comm-ga-size", f"{path.name} is {value:g} pixels {what}, and "
                                  f"the journal asks for {wanted}", path, severity=WARN,
                                  hint=hint))  # fmt: skip
    for key, value, what in (("min_width_px", width, "wide"), ("min_height_px", height, "high")):
        least = rules.get(key)
        if isinstance(least, int) and value < least:
            found.append(_finding("comm-ga-size", f"{path.name} is {value:g} pixels {what}, and "
                                  f"the journal asks for at least {least}", path,
                                  severity=WARN, hint=hint))  # fmt: skip
    ratio = _ratio(rules.get("aspect_ratio"))
    if ratio and height and abs(width / height - ratio) / ratio > _ASPECT_TOLERANCE:
        found.append(_finding("comm-ga-aspect", f"{path.name} is {width:g} by {height:g} "
                              f"pixels, and the journal asks for {rules['aspect_ratio']}",
                              path, severity=WARN, hint=hint))  # fmt: skip
    return found


@dataclass(frozen=True)
class _Drawn:
    text: str
    statement: str
    refs: tuple[str, ...]
    size: float


def drawn_texts(path: Path) -> list[_Drawn] | None:
    """Each `<text>` of an SVG, with what it names; None where the file cannot be read."""
    from manuscript_guard.gates.figures import _svg_content_nodes

    try:
        root = ET.fromstring(read_text(path))
    except (ET.ParseError, ValueError):
        return None
    found = []
    for node in _svg_content_nodes(root):
        if node.tag.rsplit("}", 1)[-1] != "text":
            continue
        words = " ".join("".join(node.itertext()).split())
        if not words:
            continue
        try:
            size = float(str(node.get("font-size", "16")).rstrip("px") or 16)
        except ValueError:
            size = 16.0
        found.append(_Drawn(words, node.get("data-statement", "").strip(),
                            tuple((node.get("data-binding") or "").split()), size))  # fmt: skip
    return found


def _svg_text(context: Context, path: Path, rules: dict) -> list[Finding]:
    from manuscript_guard.communicate.svg import pointers, printed

    drawn = drawn_texts(path)
    if drawn is None:
        return [_finding("comm-ga-unreadable", f"{path.name} is no SVG that can be read",
                         path, hint="draw it again")]  # fmt: skip
    statements = context.brief.by_id if context.brief is not None else {}
    shown = {**context.namespace, **pointers(context.project)}
    found: list[Finding] = []
    for one in drawn:
        for ref in one.refs:
            value = context.namespace.get(ref)
            if value is None:
                found.append(_finding("comm-binding-unknown", f"a line of {path.name} prints "
                                      f"{ref}, a value nothing emits", path,
                                      context=one.text[:160]))  # fmt: skip
            elif value.display not in one.text:
                found.append(_finding(
                    "comm-ga-stale",
                    f"a line of {path.name} prints {ref}, whose value is {value.display} now, "
                    "and the line does not hold it",
                    path, context=one.text[:160],
                    hint="draw it again from the results as they stand "
                    "(`communicate graphical-abstract`)",
                ))  # fmt: skip
        if one.statement:
            statement = statements.get(one.statement)
            if statement is None:
                found.append(_finding("comm-anchor-unknown", f"a line of {path.name} names "
                                      f"{one.statement}, which is no statement of the brief",
                                      path, context=one.text[:160]))  # fmt: skip
            elif fold(one.text) not in fold(printed(statement.text, shown)):
                found.append(_finding(
                    "comm-ga-text-not-in-statement",
                    f"a line of {path.name} names {one.statement}, which does not say it",
                    path, context=one.text[:160],
                    hint="change the statement's text in the brief and draw it again, rather "
                    "than the words in the SVG",
                ))  # fmt: skip
        else:
            label = texts_module.read(one.text)
            if any(sentence.claims for sentence in label.sentences):
                why = next(s.why for s in label.sentences if s.claims)
                found.append(_finding(
                    "comm-claim-unanchored",
                    f"a label of {path.name} claims ({why}) and names no statement of the "
                    "brief", path, context=one.text[:160],
                    hint="draw it from a statement of the brief (data-statement), or say it "
                    "without the claim",
                ))  # fmt: skip
    # Each statement's lines read together against its quote, as a post's sentence is: a
    # negation left off a line, or a hedge, draws a claim the paper does not make.
    for name in dict.fromkeys(one.statement for one in drawn if one.statement in statements):
        said = " ".join(one.text for one in drawn if one.statement == name)
        found += _claimed(said, statements[name].quote, f"the brief's {name}", path, None,
                          None)  # fmt: skip
    found += _drawn_numbers(context, path, "\n".join(one.text for one in drawn))
    found += _drawn_story(context, path, drawn)
    words = sum(len(one.text.split()) for one in drawn)
    most = rules.get("max_words")
    if isinstance(most, int) and words > most:
        found.append(_finding("comm-ga-words", f"{path.name} holds {words} words, and the "
                              f"journal takes {most}", path, severity=WARN,
                              hint="shorten the statements' text in the brief"))  # fmt: skip
    labels = len({one.statement for one in drawn if one.statement}) + sum(
        1 for one in drawn if not one.statement)
    most = rules.get("max_labels")
    if isinstance(most, int) and labels > most:
        found.append(_finding("comm-ga-labels", f"{path.name} holds {labels} labels (a "
                              "statement drawn, or a text of its own), and the journal takes "
                              f"{most}", path, severity=WARN,
                              hint="leave statements out of the brief's panels"))  # fmt: skip
    return found


def _drawn_numbers(context: Context, path: Path, text: str) -> list[Finding]:
    """`comm-number-unbound` for a number of the image's text that is no value's display
    and no convention, as G3 reads a figure's."""
    from manuscript_guard.gates.figures import _allowed, _signed

    allowed = _allowed(value.display for value in context.namespace.values())
    scan = context.classifier.scan(text, lines_are_blocks=True)
    found = []
    for atom in find_atoms(text, text):
        signed = _signed(atom.text)
        if signed in allowed or signed.replace(",", "") in allowed:
            continue
        if context.classifier.classify(atom, None, scan).kind != UNCLASSIFIED:
            continue
        found.append(_finding("comm-number-unbound", f"{atom.text!r} is drawn in {path.name} "
                              "and is no value of the results", path,
                              context=atom.line_text.strip()[:160],
                              hint="draw it from a statement that binds the value"))  # fmt: skip
    return found


def _drawn_story(context: Context, path: Path, drawn: list[_Drawn]) -> list[Finding]:
    brief = context.brief
    if brief is None or not any(one.statement for one in drawn):
        return []
    primary = {one.id for one in brief.primary}
    if not primary:
        return []
    found = []
    named = {one.statement for one in drawn}
    if not primary & named:
        found.append(_finding("comm-primary-missing", f"{path.name} draws no primary finding "
                              f"of the brief ({', '.join(sorted(primary))})", path,
                              hint="draw it again (`communicate graphical-abstract`)"))  # fmt: skip
    findings = {one.id for one in brief.of("findings")}
    largest = max((one for one in drawn if one.statement in findings),
                  key=lambda one: one.size, default=None)  # fmt: skip
    if largest is not None and largest.statement not in primary and not any(
            one.size >= largest.size for one in drawn if one.statement in primary):  # fmt: skip
        found.append(_finding("comm-secondary-as-primary", f"{path.name} draws "
                              f"{largest.statement}, a secondary finding, larger than the "
                              "primary one", path, severity=WARN,
                              hint="the primary finding is the one a reader sees first"))
    return found


def _pdf_text(context: Context, path: Path) -> list[Finding]:
    from manuscript_guard.gates.figures import _extract_text

    text = _extract_text(path)
    if not text:
        return []
    return _drawn_numbers(context, path, text)


def _alt(context: Context, rules: dict) -> list[Finding]:
    from manuscript_guard.gates.figure_alt import alt_text_findings, printed_alt

    path = graphical_abstract_folder(context.project) / ALT_TEXT
    if not path.is_file() or not read_text(path).strip():
        return [_finding("comm-alt-missing", "the graphical abstract has no alternative text, "
                         "and a screen reader reads nothing else of it", path, severity=WARN,
                         hint="write it in alt-text.md: what it shows and its main message, "
                         "the values by binding; `communicate graphical-abstract` writes one")]
    raw = read_text(path)
    found = [replace(one, gate=GATE) for one in alt_text_findings(
        "graphical abstract", raw, path, context.classifier, context.namespace)]  # fmt: skip
    longest = rules.get("alt_text_max_chars")
    shown = printed_alt(raw, context.namespace)
    if isinstance(longest, int) and len(shown) > longest:
        found.append(_finding("comm-alt-long", f"the graphical abstract's alternative text is "
                              f"{len(shown)} characters printed, and the journal takes "
                              f"{longest}", path, severity=WARN, context=shown[:120],
                              hint="say what it shows and its main message, no more"))  # fmt: skip
    return found


# ---------------------------------------------------------------------------- the report


def render(report: Report, root: Path, title: str = "communicate check") -> str:
    """The report as Markdown, failures listed apart from warnings and notes, each place
    written from the project's root with forward slashes: the same text on every system."""
    lines = [f"# {title}", ""]
    failures = [one for one in report.sorted().findings if one.severity == FAIL]
    warned = len(report.warnings)
    lines.append(f"{len(failures)} failure{'' if len(failures) == 1 else 's'}, "
                 f"{warned} warning{'' if warned == 1 else 's'}.")
    for severity, heading in ((FAIL, "Failures"), (WARN, "Warnings"), (INFO, "Notes")):
        mine = [one for one in report.sorted().findings if one.severity == severity]
        if not mine:
            continue
        lines += ["", f"## {heading}", ""]
        for one in mine:
            where = _where(one, root)
            lines.append(f"- `{one.code}` {where}: {one.message}")
            if one.context:
                lines.append(f"  > {one.context}")
            if one.hint:
                lines.append(f"  hint: {one.hint}")
    return "\n".join(lines) + "\n"


def _where(finding: Finding, root: Path) -> str:
    if finding.path is None:
        return "-"
    try:
        shown = Path(finding.path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        shown = Path(finding.path).as_posix()
    return f"{shown}:{finding.line}" if finding.line else shown


def as_json(report: Report, root: Path) -> str:
    import json

    def entry(one: Finding) -> dict:
        out = one.as_dict()
        out["path"] = _where(replace(one, line=None), root) if one.path is not None else None
        return out

    findings = report.sorted().findings
    return json.dumps(
        {
            "ok": report.ok,
            "counts": report.counts,
            "failures": [entry(one) for one in findings if one.severity == FAIL],
            "warnings": [entry(one) for one in findings if one.severity == WARN],
            "notes": [entry(one) for one in findings if one.severity == INFO],
        },
        indent=2,
        ensure_ascii=True,
    )
