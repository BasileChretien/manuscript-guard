"""`references --comments`: each proposed change nobody answered, as a Word comment on its
citing sentence, in a copy of the manuscript for the authors.

A proposal is an entry of `literature/currency.yaml` whose decision is `replace` or `add`,
with no answer, that the manuscript has not accepted by citing the work. Its comment says
what is proposed, the work (its DOI or PMID, title and year, from its works record), the
decision's reason and rule ids, a quote of the readings for each of R1 to R3, and how to
answer it. The document is built offline into `build/currency/`, as `review --suggestions`
builds its own, and the comment is written alone, with no tracked change
(`tracked.Placement.comment_only`), on the sentence's words as the build printed them.

**A comment is placed exactly, or not at all.** The sentence is found once in its
paragraph's source, read as Word shows it with each value and citation as the build printed
it (`anchor`), and those words are found once in the paragraph the build printed. A sentence
whose words are there twice, an entry no sentence matches, or a paragraph the build does not
mark, gets no comment, and the command says why.

What the document records of each comment is a list in its own custom property
(`tracked.CURRENCY_PROPERTY`): the entry, a digest of the decision it shows, the comment's
author and a digest of its words, and the day. `import` knows a currency comment by those, and
files a reply to it under `literature/currency/replies/` (`currency/replies.py`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.currency import records, rules
from manuscript_guard.currency.records import Entry

#: Who a currency comment is by: the tool, never a person or a model.
AUTHOR = "manuscript-guard (references)"
#: Where the documents are written: a folder of the build, for the authors alone.
FOLDER = "currency"
#: How a comment ends.
ANSWER_LINE = ("To accept, cite this work (add it in Zotero, then run sync-bib). To refuse, "
               "reply with your reason.")  # fmt: skip
#: How much of a quote a comment shows.
QUOTE_LIMIT = 200
#: The fields a comment quotes, one quote each, as R1 to R3 name them.
QUOTED = (("R1", "level"), ("R2", "population"), ("R2", "exposure"), ("R2", "outcome"),
          ("R3", "stance"))  # fmt: skip


def document_path(project: Project, *, supplementary: bool = False) -> Path:
    name = "suggestions" + ("-supplementary" if supplementary else "")
    return project.path("build") / FOLDER / f"{name}.docx"


def decision_digest(decision: dict | None) -> str:
    """Sixteen hex digits that say which proposal a decision is: its action, its candidate
    and its rule ids. A comment records it, and so does a reply to the comment, so that a
    reply to a proposal that has changed since is known for one."""
    from manuscript_guard.suggestions import short_digest

    decision = decision or {}
    said = {"action": decision.get("action"), "candidate": decision.get("candidate"),
            "rules": list(decision.get("rules") or [])}  # fmt: skip
    return short_digest(json.dumps(said, sort_keys=True))


def is_proposal(entry: Entry) -> bool:
    return (entry.decision or {}).get("action") in (rules.REPLACE, rules.ADD)


@dataclass(frozen=True)
class Proposal:
    """One entry that proposes a change nobody answered, with its comment, or why it gets
    none."""

    entry: Entry
    where: str = ""
    comment: str = ""
    dropped: str = ""
    paragraph: str = ""
    supplementary: bool = False
    #: The sentence's words as the build printed them, which the comment is over.
    shown: str = ""


@dataclass(frozen=True)
class Outcome:
    documents: tuple[Path, ...]
    proposals: tuple[Proposal, ...]
    report: object = None


def _identifier(work: str) -> str:
    kind, _colon, value = work.partition(":")
    return f"DOI {value}" if kind == "doi" else f"PMID {value}"


def _cut(text: str, limit: int = QUOTE_LIMIT) -> str:
    folded = " ".join(text.split())
    return folded if len(folded) <= limit else folded[:limit].rstrip() + "\N{HORIZONTAL ELLIPSIS}"


def comment_text(entry: Entry, reason: str, work: dict, quotes: dict[str, str]) -> str:
    """What the comment on a proposal says, a line for each part: what is proposed, the work,
    why, the readings' quotes, and how to answer."""
    decision = entry.decision or {}
    candidate = str(decision["candidate"])
    named = _identifier(candidate)
    if decision["action"] == rules.REPLACE:
        head = f"Suggestion ({entry.id}): replace @{entry.citekey} in this sentence with {named}."
    else:
        head = f"Suggestion ({entry.id}): add {named} beside @{entry.citekey} in this sentence."
    title = " ".join(str(work.get("title") or "").split()) or "untitled"
    year = str(work.get("published") or "")[:4] or "no year"
    lines = [head, f"The work: {title} ({year}), {named}.",
             f"Why: {reason} ({', '.join(decision['rules'])})."]  # fmt: skip
    for rule, name in QUOTED:
        if quotes.get(name):
            lines.append(f"{rule} {name}: \N{LEFT DOUBLE QUOTATION MARK}{_cut(quotes[name])}"
                         "\N{RIGHT DOUBLE QUOTATION MARK}")  # fmt: skip
    lines.append(ANSWER_LINE)
    return "\n".join(lines)


def _quotes(usable: list[dict], candidate: str) -> dict[str, str]:
    """One quote for each field of the candidate, from the first reading that names it."""
    for record in usable:
        for one in record.get("candidates") or []:
            if records.fold_work(str(one["work"])) == candidate:
                return {name: str(one[name]["quote"]) for _rule, name in QUOTED
                        if isinstance(one.get(name), dict) and one[name].get("quote")}
    return {}


def _reason(entry: Entry, usable: list[dict], held, bib: dict) -> str:
    """The decision's reason: a person's `why`, or what the rules give in words; empty where
    the rules no longer give this decision, which G7 reports as a mismatch."""
    from manuscript_guard.gates.currency import rules_decision

    decision = entry.decision or {}
    if decision.get("by") != "rules":
        return str(decision.get("why") or "")
    given = rules_decision(entry, usable, held, bib)
    if given is None or (given.action, given.candidate, tuple(given.rules)) != (
            decision["action"], decision.get("candidate"), tuple(decision["rules"])):  # fmt: skip
        return ""
    scale = usable[0]["scale"] if usable else ""
    return given.why + (f", on the scale {scale}" if scale else "")


def proposals(project: Project) -> list[Proposal]:
    """Each proposal nobody answered and the manuscript has not accepted, with its comment's
    words, or why it can have none."""
    from manuscript_guard.currency.survey import survey
    from manuscript_guard.gates.currency import _bib, _fitting, _Records, missing_works

    found, report = survey(project)
    if report.failures:
        from manuscript_guard.currency.command import Refused

        raise Refused("; ".join(finding.message for finding in report.failures))
    held = _Records(project)
    bib = _bib(project)
    from manuscript_guard.currency.hierarchy import hierarchies

    known = hierarchies(project)
    out = []
    for entry in found.entries:
        if not is_proposal(entry) or entry.answer or entry.id in found.accepted:
            continue
        candidate = str(entry.decision["candidate"])
        usable = [read.record for read in held.readings.get(entry.id, []) if read.problem is None]
        usable, _unfit = _fitting(usable, entry, known, bib)
        sentence = found.placed.get(entry.id)
        if sentence is None:
            out.append(Proposal(entry, dropped="no sentence of the manuscript matches it "
                                "(unplaced): `references --mark ... --id` puts it back"))
            continue
        where = f"{_relative(project, sentence.path)}:{sentence.line}"
        work = held.good_work(candidate)
        absent = missing_works(entry, usable, held, bib) if entry.decision["by"] == "rules" \
            else ([] if work is not None else [candidate])  # fmt: skip
        if work is None or absent:
            out.append(Proposal(entry, where, dropped="the works store holds no record of "
                                f"{', '.join(absent or [candidate])}, so the proposal cannot "
                                "be shown with its work and reason here"))  # fmt: skip
            continue
        reason = _reason(entry, usable, held, bib)
        if not reason:
            out.append(Proposal(entry, where, dropped="the rules no longer give this decision "
                                "from its readings (currency-decision-mismatch)"))
            continue
        out.append(Proposal(entry, where, comment_text(entry, reason, work,
                                                       _quotes(usable, candidate))))
    return out


def _relative(project: Project, path: Path) -> str:
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return str(path)


# ------------------------------------------------------------------- where the comment goes


def sentence_in(source: str, sentence: str) -> list[tuple[int, int]]:
    """Where a citing sentence, as `cited_sentences` gives it (its spaces folded), is in its
    paragraph's source, its comments blanked: every place, each as a span of the source."""
    from manuscript_guard.text.masking import blank_comments

    words = sentence.split()
    if not words:
        return []
    pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
    text = blank_comments(source)
    found, at = [], 0
    while (match := pattern.search(text, at)) is not None:
        found.append(match.span())
        at = match.start() + 1
    return found


def anchor(source: str, start: int, end: int, printed: str,
           tokens: Sequence[tuple[int, int]] | None) -> tuple[int, int] | str:  # fmt: skip
    """Where the words `source[start:end]` of a paragraph's source stand in `printed`, what
    the build printed of the paragraph with its values and citations at `tokens`; or why
    they cannot be found exactly.

    The words are read as Word shows them (`roundtrip._read`), each value and citation as the
    build printed it, and those are found once in `printed`, as typed or as pandoc typesets
    them (`suggestions.pattern_of`). Nothing is guessed: words that run into a value or a
    citation, that do not read on their own as they read in the paragraph, or that are in
    the printed paragraph twice, are found nowhere."""
    from manuscript_guard.roundtrip import _checked, _read, _tokens, anchors_apart
    from manuscript_guard.suggestions import _starts, pattern_of

    apart = anchors_apart(source)
    if apart is None:
        return "its paragraph ends in a way the comment cannot be placed in"
    bare = apart[0]
    if not 0 <= start < end <= len(bare):
        return "its sentence runs into the anchors that end its paragraph"
    found = _tokens(bare)
    whole = _read(bare)
    spans = _checked(tokens, len(whole.protected), len(printed)) if whole.protected else []
    if spans is None or len(found) != len(whole.protected):
        return "its values and citations could not be lined up with the build"
    inside = []
    for index, token in enumerate(found):
        if start < token.to and token.at < end and not (start <= token.at and token.to <= end):
            return "its sentence runs into a value or a citation"
        if start <= token.at and token.to <= end:
            inside.append(index)
    renderings = [printed[spans[index][0] : spans[index][1]] for index in inside]
    alone = _read(source[start:end], renderings)
    if alone.protected != [whole.protected[index] for index in inside]:
        return "its sentence does not read on its own as it reads in its paragraph"
    shown = alone.whole
    if not shown or not shown[:1].strip():
        return "its sentence prints nothing"
    places = _starts(pattern_of(shown), printed)
    if len(places) != 1:
        return (f"its words are in the paragraph {len(places)} times as the build printed it"
                if places else "its words are not in the paragraph as the build printed it")
    return places[0].span()


def _placed(project: Project, proposal: Proposal, sentence, paragraphs: dict,
            printed: dict[str, str], extents: dict[str, tuple],
            supplement: frozenset[str]) -> Proposal:  # fmt: skip
    """The proposal with its paragraph and its printed words, or dropped with the reason."""
    candidates = []
    for name, (path, text, _start) in paragraphs.items():
        if path != sentence.path:
            continue
        for span in sentence_in(text, sentence.text):
            candidates.append((name, text, span))
    if not candidates:
        return replace(proposal, dropped="its sentence is not in a paragraph the build marks "
                       "(a heading, a list, a table, a caption or a quotation)")  # fmt: skip
    if len(candidates) > 1:
        where = "its paragraph" if len({name for name, _t, _s in candidates}) == 1 \
            else "the manuscript"  # fmt: skip
        return replace(proposal, dropped=f"its sentence is in {where} {len(candidates)} times")
    name, text, (start, end) = candidates[0]
    if name not in printed:
        return replace(proposal, dropped="its paragraph is not in the document as built")
    span = anchor(text, start, end, printed[name], extents.get(name))
    if isinstance(span, str):
        return replace(proposal, dropped=span)
    return replace(proposal, paragraph=name, supplementary=name in supplement,
                   shown=printed[name][span[0] : span[1]])  # fmt: skip


def write_comments(project: Project, *, csl: Path | None, date: str) -> Outcome:
    """Write each proposal's comment into a copy of the document, built offline into
    `build/currency/`, and a supplement's into its own where one of them is in it. A
    document no comment could be placed in is not kept."""
    import tempfile

    from manuscript_guard import tracked
    from manuscript_guard.build import OFFLINE, BuildError, assemble, build_document
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.currency.survey import survey
    from manuscript_guard.docxtext import blocks
    from manuscript_guard.findings import Report
    from manuscript_guard.gates.numbers import is_supplementary
    from manuscript_guard.roundtrip import tagged_paragraphs
    from manuscript_guard.suggestions import short_digest

    listed = proposals(project)
    if not any(not one.dropped for one in listed):
        return Outcome((), tuple(listed), Report())
    found, _report = survey(project)
    paragraphs = tagged_paragraphs(project)
    manuscript_dir = project.path("manuscript")
    supplement = frozenset(name for name, (path, _t, _s) in paragraphs.items()
                           if is_supplementary(manuscript_dir, path))  # fmt: skip
    kinds = {False} | {is_supplementary(manuscript_dir, found.placed[one.entry.id].path)
                       for one in listed if not one.dropped}  # fmt: skip
    namespace, results, _literature, _r = load_namespace(project)
    assembled, _ar = assemble(project, namespace, results)
    marked_assembly, _mr = assemble(project, namespace, results, mark=True)
    printed: dict[str, str] = {}
    extents: dict[str, tuple] = {}
    outputs: dict[bool, Path] = {}
    report = Report()
    from manuscript_guard.currency.command import Refused

    try:
        for supplementary in sorted(kinds):
            output = document_path(project, supplementary=supplementary)
            output.parent.mkdir(parents=True, exist_ok=True)
            built = build_document(project, assembled, mode=OFFLINE, csl=csl, output=output,
                                   supplementary=supplementary)  # fmt: skip
            report = report.merge(built.report)
            outputs[supplementary] = output
            these = {b.names[0]: b.text for b in blocks(output) if b.names and not b.table}
            printed.update(these)
            with tempfile.TemporaryDirectory() as scratch:
                marked = Path(scratch) / "marked.docx"
                build_document(project, marked_assembly, mode=OFFLINE, csl=csl, output=marked,
                               supplementary=supplementary, verify_reading=False, sent=True)
                for block in blocks(marked):
                    name = block.names[0] if block.names and not block.table else None
                    nbsp = "\N{NO-BREAK SPACE}"
                    if name in these and these[name].replace(nbsp, " ") == block.text.replace(
                            nbsp, " "):  # fmt: skip
                        extents[name] = block.tokens
    except BuildError as exc:
        raise Refused(f"the document could not be built: {exc}") from None

    placed = [one if one.dropped else _placed(project, one, found.placed[one.entry.id],
                                              paragraphs, printed, extents, supplement)
              for one in listed]  # fmt: skip
    numbered = {id(one): n for n, one in enumerate((p for p in placed if not p.dropped), 1)}
    final: dict[int, Proposal] = {}
    kept = []
    for supplementary, output in outputs.items():
        mine = [p for p in placed if not p.dropped and p.supplementary == supplementary]
        placements = [tracked.Placement(numbered[id(p)], p.paragraph, p.shown, p.shown, AUTHOR,
                                        date, p.comment, comment_only=True) for p in mine]
        offered = [{"n": numbered[id(p)], "entry": p.entry.id,
                    "decision": decision_digest(p.entry.decision), "author": AUTHOR,
                    "written": short_digest(p.comment), "date": date[:10]} for p in mine]
        written = tracked.write(output, output, placements, offered,
                                listed_as=tracked.CURRENCY_PROPERTY) if placements else []
        said = {w.number: w.dropped for w in written}
        for p in mine:
            why = said.get(numbered[id(p)], "")
            final[id(p)] = replace(p, dropped=why) if why else p
        if any(not w.dropped for w in written):
            kept.append(output)
        else:
            for stale in (output, output.with_name(output.name + ".source.sha256")):
                stale.unlink(missing_ok=True)
    return Outcome(tuple(kept), tuple(final.get(id(p), p) for p in placed), report)


__all__ = ["ANSWER_LINE", "AUTHOR", "FOLDER", "Outcome", "Proposal", "anchor",
           "comment_text", "decision_digest", "document_path", "is_proposal", "proposals",
           "sentence_in", "write_comments"]
