"""The passage of a cited work that supports a sentence citing it.

A number taken from the literature carries the sentence of its source that states it, in the
ledger, and G7 holds the two together. A sentence that cites a work for what it says, with no
number in it, carried nothing: whether the work says it was answered from memory, by whoever
was asked. `literature/passages.yaml` holds, for such a sentence and one work it cites, the
passage of that work that supports it, copied from the stored source, and where it stands.
G7 looks for each passage in the work's stored files as it looks for a quotation in the prose
(`quoted_in`), and the co-author checker shows it beside the sentence.

A passage belongs to its sentence by the sentence's words and the citation key, never by a
file or a line (DESIGN.md, "What the digest covers"): a sentence that moves keeps its passage,
and one that is reworded leaves it stale, since a passage chosen for other words need not
support these. The words are folded first (`statement_words`), so that what is no difference
to a reader, a citation group added or taken out, the case, the line breaks, a curly quote, a
final stop, is no difference here.

A person may record whether the passage supports the sentence: `support`, with `judged_by`
and `judged_on`. An agent may draft a passage; only a person judges it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.checking.produce import CitedSentence
from manuscript_guard.contracts import ContractError
from manuscript_guard.contracts._schema import read_structured, validate
from manuscript_guard.findings import Finding, Report
from manuscript_guard.literature.sources import (
    UnreadableSource,
    normalise,
    read_source,
    stored_files,
)
from manuscript_guard.text.placeholders import PLACEHOLDER
from manuscript_guard.zotero.citations import bracketed

PASSAGES_FILE = "passages.yaml"
SCHEMA = "manuscript-guard/passages/1"

SUPPORTS = "supports"
PARTLY = "partly"
DOES_NOT = "does-not"

#: What G7 finds of a passage in the work's stored files.
VERIFIED = "verified"
ABSENT = "not in its source"
NO_SOURCE = "no stored copy"
UNREADABLE = "no stored copy can be read"

#: Why a passage belongs to no sentence of the manuscript.
UNCITED = "uncited"
CHANGED = "changed"
GONE = "gone"
#: The share of a passage's sentence's words that a sentence citing the same work has to
#: share for the stale passage to be said to be of that sentence, changed. It decides what the
#: note says, and nothing else.
NEAR = 0.5

#: A space before a mark that closes a clause or a bracket: what a citation group taken out
#: of "rose [@a]." leaves.
_BEFORE_MARK = re.compile(r"\s+([.,;:!?)\]])")


@dataclass(frozen=True)
class Passage:
    """One entry of `passages.yaml`, numbered from 1 in the order the file gives them."""

    number: int
    sentence: str
    citekey: str
    passage: str
    locator: str
    support: str | None = None
    judged_by: str | None = None
    judged_on: str | None = None

    @property
    def named(self) -> str:
        """How a finding names the entry: its number, its work and its sentence's opening."""
        opening = " ".join(self.sentence.split())
        opening = opening if len(opening) <= 60 else opening[:57] + "..."
        return f"passage {self.number} (@{self.citekey}, {opening!r})"


def read_passages(literature_dir: Path) -> tuple[tuple[Passage, ...], Report]:
    """The passages of `passages.yaml`, and what stopped them being read.

    No file is no passages and no finding: a project may record none. A file that cannot be
    parsed, or does not fit its schema, gives no passages and says why."""
    path = literature_dir / PASSAGES_FILE
    try:
        document = read_structured(path)
    except ContractError as exc:
        return (), Report((
            Finding(gate="G0", code="schema-violation", message=str(exc), path=path,
                    hint="see the passages schema"),
        ))  # fmt: skip
    if document is None:
        return (), Report()
    report = validate(document, "passages", path)
    if not report.ok or not isinstance(document, dict):
        return (), report
    passages = tuple(
        Passage(
            number=number,
            sentence=str(entry["sentence"]),
            citekey=str(entry["citekey"]).strip(),
            passage=str(entry["passage"]),
            locator=str(entry["locator"]).strip(),
            support=entry.get("support"),
            judged_by=_text_or_none(entry.get("judged_by")),
            judged_on=_text_or_none(entry.get("judged_on")),
        )
        for number, entry in enumerate(document.get("passages") or [], start=1)
    )
    return passages, report


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value).strip()


def statement_words(sentence: str) -> str:
    """The words a passage is matched on: the sentence with each citation group taken out,
    its typography, white space and case folded, a space before a closing mark dropped, and a
    final stop taken off.

    A group (`[@a; @b, p. 4]`, read as `zotero/citations.py` reads one) is not words of the
    claim: a work added beside the one cited, or a page number changed, leaves a passage
    where it was. A narrative citation is ("@smith2020 showed"), and stays. A binding is
    written as the renderer reads it, `{{ lit.x }}` as `{{lit.x}}` (round 1 of #374)."""
    text = unicodedata.normalize("NFC", sentence)
    for group in reversed(list(bracketed(text))):
        text = text[: group.start()] + " " + text[group.end() :]
    text = PLACEHOLDER.sub(lambda found: f"{{{{{found['ns']}.{found['key']}}}}}", text)
    folded = _BEFORE_MARK.sub(r"\1", normalise(text).casefold())
    return folded.rstrip(" .!?")


class Belonging:
    """Which passages belong to which cited sentences: those whose folded sentence is the
    sentence's, and whose work the sentence cites."""

    def __init__(self, passages: tuple[Passage, ...] | list[Passage]) -> None:
        self._by_words: dict[str, list[Passage]] = {}
        for passage in passages:
            self._by_words.setdefault(statement_words(passage.sentence), []).append(passage)

    def of(self, cited: CitedSentence, key: str, words: str | None = None) -> list[Passage]:
        """The passages of work `key` recorded for this sentence, in the file's order.
        `words` is the sentence's `statement_words`, where they are known already."""
        if key not in cited.keys:
            return []
        held = self._by_words.get(statement_words(cited.text) if words is None else words, [])
        return [passage for passage in held if passage.citekey == key]


@dataclass(frozen=True)
class Checked:
    """One passage as G7 finds it: in the work's stored files or not, and the sentences it
    belongs to. None of those is a stale passage, and `stale` says why; `near` is the
    sentence citing the work that holds most of its words, where one holds most."""

    passage: Passage
    found: str
    looked_in: tuple[str, ...]
    why: str | None
    sentences: tuple[CitedSentence, ...]
    stale: str | None = None
    near: CitedSentence | None = None


@dataclass(frozen=True)
class Survey:
    """The cited sentences of the manuscript and the passages of `passages.yaml`, matched."""

    sentences: tuple[CitedSentence, ...]
    passages: tuple[Checked, ...]
    _held: dict[tuple[int, str], list[Checked]] = field(default_factory=dict, repr=False)

    def of(self, index: int, key: str) -> list[Checked]:
        """The current passages of work `key` for the `index`th sentence."""
        return self._held.get((index, key), [])

    @property
    def statements(self) -> list[tuple[int, CitedSentence]]:
        """Each cited sentence once: one written twice in one file is one statement."""
        seen: set[tuple[Path, str]] = set()
        out = []
        for index, cited in enumerate(self.sentences):
            if (cited.path, cited.text) in seen:
                continue
            seen.add((cited.path, cited.text))
            out.append((index, cited))
        return out

    def carries(self, index: int) -> bool:
        """Whether a sentence has a passage of one of the works it cites."""
        return any(self.of(index, key) for key in self.sentences[index].keys)


def survey(
    sources: Path, sentences: list[CitedSentence], passages: tuple[Passage, ...]
) -> Survey:
    """Each passage matched to the sentences it belongs to and looked for in the stored
    files of its work, each file read once."""
    belonging = Belonging(passages)
    words = [statement_words(cited.text) for cited in sentences]
    belongs: dict[tuple[int, str], list[Passage]] = {}
    sentences_of: dict[int, list[CitedSentence]] = {}
    for index, cited in enumerate(sentences):
        for key in cited.keys:
            mine = belonging.of(cited, key, words[index])
            if mine:
                belongs[(index, key)] = mine
            for passage in mine:
                sentences_of.setdefault(passage.number, []).append(cited)
    read: dict[Path, str | UnreadableSource] = {}
    checked = []
    for passage in passages:
        found, looked_in, why = looked_for(sources, passage.citekey, passage.passage, read)
        mine = tuple(sentences_of.get(passage.number, ()))
        stale, near = (None, None) if mine else _why_stale(passage, sentences, words)
        checked.append(Checked(passage, found, looked_in, why, mine, stale, near))
    by_number = {one.passage.number: one for one in checked}
    held = {
        place: [by_number[passage.number] for passage in mine]
        for place, mine in belongs.items()
    }
    return Survey(tuple(sentences), tuple(checked), held)


def looked_for(
    sources: Path, citekey: str, words: str, read: dict[Path, str | UnreadableSource]
) -> tuple[str, tuple[str, ...], str | None]:
    """What the stored files of work `citekey` say of `words`: verified where one holds them,
    with the files read and, where none does, what stands in the way. `read` keeps each file
    read, for the next passage. A methods review's passages are looked for here too."""
    from manuscript_guard.gates.quotations import _ELIDED, _SIC, _as_words, quoted_in

    if not passage_words(words):
        # All elision, "[...]" or "...": nothing to look for, which `quoted_in` finds
        # anywhere (round 1 of #374). A number is something (round 2).
        return ABSENT, (), "it holds nothing to look for"
    files = stored_files(sources, citekey)
    if not files:
        return NO_SOURCE, (), None
    texts = []
    for path in files:
        if path not in read:
            try:
                read[path] = read_source(path)
            except UnreadableSource as exc:
                read[path] = exc
        texts.append((path, read[path]))
    readable = [(path, text) for path, text in texts if isinstance(text, str)]
    if not readable:
        return UNREADABLE, (), "; ".join(str(text) for _path, text in texts)
    names = tuple(path.name for path, _text in readable)
    # With nothing left out, as words of their own, as each piece of an elided one is: "6,
    # 95%" is no part of "2.6, 95%" (the post-budget round of #374).
    whole = normalise(_SIC.sub("", words)).lower()
    if any(quoted_in(text, words) if _ELIDED.search(words)
           else _as_words(normalise(text).lower(), whole, 0) >= 0
           for _path, text in readable):  # fmt: skip
        return VERIFIED, names, None
    why = None
    if len(readable) == 1 and not _ELIDED.search(words):
        from manuscript_guard.literature.placement import why_not_found

        why = why_not_found(readable[0][0], words)
    return ABSENT, names, why


def _why_stale(
    passage: Passage, sentences: list[CitedSentence], words: list[str]
) -> tuple[str, CitedSentence | None]:
    """Why a passage belongs to no sentence: its sentence is there and no longer cites the
    work, or a sentence citing the work holds most of its words, changed, or neither.
    `words` are the sentences' `statement_words`, in their order."""
    wanted = statement_words(passage.sentence)
    for cited, theirs in zip(sentences, words, strict=True):
        if theirs == wanted:
            return UNCITED, cited
    mine = set(wanted.split())
    best, near = 0.0, None
    for cited, theirs in zip(sentences, words, strict=True):
        if passage.citekey not in cited.keys:
            continue
        # The share of the old sentence's words the new one holds, as `NEAR` says: a
        # rewording that kept every word and added as many was said to be gone (round 1 of
        # #374, which measured it against the words of both).
        shared = len(mine & set(theirs.split())) / max(len(mine), 1)
        if shared > best:
            best, near = shared, cited
    return (CHANGED, near) if near is not None and best >= NEAR else (GONE, None)


def listing(found: Survey, root: Path, sources: Path, *, missing: bool = False) -> dict:
    """What `manuscript-guard passages` prints: each cited statement, once, with each work it
    cites, the stored files of that work and its passages; and the stale passages. With
    `missing`, only the statements that carry no passage of any work they cite."""
    statements = []
    for index, cited in found.statements:
        if missing and found.carries(index):
            continue
        try:
            shown = cited.path.relative_to(root).as_posix()
        except ValueError:  # `paths:` can put the manuscript outside the project
            shown = str(cited.path)
        statements.append({
            "file": shown,
            "line": cited.line,
            "sentence": cited.text,
            "cites": [
                {
                    "key": key,
                    "stored": [path.name for path in stored_files(sources, key)],
                    "passages": [_listed(one) for one in found.of(index, key)],
                }
                for key in cited.keys
            ],
        })  # fmt: skip
    stale = [
        {**_listed(one), "why": one.stale, "sentence": one.passage.sentence}
        for one in found.passages
        if one.stale is not None
    ]
    carrying = sum(found.carries(index) for index, _cited in found.statements)
    return {
        "statements": statements,
        "stale": stale,
        "counts": {"cited_statements": len(found.statements), "with_passage": carrying},
    }


def _listed(checked: Checked) -> dict:
    passage = checked.passage
    return {
        "number": passage.number,
        "key": passage.citekey,
        "locator": passage.locator,
        "found": checked.found,
        "support": passage.support,
        "judged_by": passage.judged_by,
    }


def rendered(listed: dict) -> str:
    """The listing as `passages` prints it without `--json`."""
    lines = []
    for statement in listed["statements"]:
        lines.append(f"{statement['file']}, paragraph at line {statement['line']}")
        lines.append(f"  {statement['sentence']}")
        for cited in statement["cites"]:
            stored = ", ".join(cited["stored"]) or "no stored copy"
            if not cited["passages"]:
                lines.append(f"  @{cited['key']}: no passage ({stored})")
            for one in cited["passages"]:
                judged = f", judged {one['support']} by {one['judged_by']}" if one["support"] \
                    else ""  # fmt: skip
                lines.append(
                    f"  @{cited['key']}: passage {one['number']}, {one['locator']}: "
                    f"{one['found']}{judged}"
                )
        lines.append("")
    for one in listed["stale"]:
        lines.append(
            f"stale: passage {one['number']} (@{one['key']}), {one['why']}: {one['sentence']}"
        )
    counts = listed["counts"]
    lines.append(
        "cited statements with a passage of a work they cite: "
        f"{counts['with_passage']} of {counts['cited_statements']}; stale passages: "
        f"{len(listed['stale'])}"
    )
    return "\n".join(lines)


def passage_words(passage: str) -> int:
    """How many words a passage holds, less what marks words left out: a word is a run
    between spaces with a letter or a digit in it, so that "2.6, 95%" is two."""
    from manuscript_guard.gates.quotations import _ELIDED, _SIC

    kept = _ELIDED.sub(" ", _SIC.sub(" ", passage))
    return sum(any(c.isalnum() for c in word) for word in kept.split())
