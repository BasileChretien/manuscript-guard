"""Which claims are in the scope of reference currency, and which entry each has.

An entry of `currency.yaml` is matched to the manuscript as a passage is: by the sentence's
folded words (`literature.passages.statement_words`) and the citation key, never by a file or
a line. Where no sentence citing the key has the same words, the sentence citing it that
holds the most of the entry's words is taken, where it holds at least `NEAR` of them: a
sentence reworded a little keeps its entry. With neither, the entry is unplaced.

In scope, as G7 reads it: each claim an entry marks, and each citing sentence that cites a
work whose lookup record says a later version, or a published version of a preprint, has come
since (`gates.lookups.currency_facts`). The sentences are those of the main text and of
`manuscript/supplementary/`, Markdown or LaTeX (`gates.passages.citing_documents`).

A proposed `replace` or `add` nobody answered, or answered only by a refusal read from a
reply in Word (the manuscript wins), counts as accepted once the entry's own
sentence cites a key whose DOI or PMID in `references.bib` is the candidate's (design 2.5):
the author cited the work, in Zotero and then `sync-bib`. Nothing is written. The entry's own
sentence is, first, the one sentence whose folded words are the entry's, whichever of the old
work and the candidate it cites now; it accepts if and only if it cites the candidate, and
the entry is placed on it. Where two or more such sentences cite either, none accepts. Only
where no sentence has the entry's words does `NEAR` decide: the sentence citing the old work
that holds most of them is the entry's, and accepts if it cites the candidate too; failing
that, the one citing the candidate that holds most of them accepts, and the entry is placed
on it (Basile, "exact words first", round 4 of #499).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.checking.produce import CitedSentence, cited_sentences
from manuscript_guard.contracts.project import Project
from manuscript_guard.currency.records import Entry, is_work, read_entries
from manuscript_guard.findings import Report
from manuscript_guard.literature.passages import NEAR, statement_words


@dataclass(frozen=True)
class Claim:
    """A sentence and one work it cites, in scope: the entry it has, if any, and what the
    lookup record says came after the work, if anything."""

    sentence: CitedSentence
    citekey: str
    entry: Entry | None
    facts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Survey:
    """The entries, where each is placed, and the claims in scope."""

    entries: tuple[Entry, ...]
    placed: dict[str, CitedSentence]
    claims: tuple[Claim, ...]
    sentences: tuple[CitedSentence, ...]
    #: The entries whose proposed change a sentence accepts by citing the candidate.
    accepted: dict[str, CitedSentence] = field(default_factory=dict)

    @property
    def unplaced(self) -> tuple[Entry, ...]:
        return tuple(entry for entry in self.entries if entry.id not in self.placed)


def place(entry_sentence: str, citekey: str, sentences: list[CitedSentence],
          words: list[str]) -> CitedSentence | None:  # fmt: skip
    """The sentence an entry belongs to: one citing `citekey` with the same folded words,
    else the one citing it that holds most of the entry's words, at least `NEAR` of them."""
    wanted = statement_words(entry_sentence)
    for cited, theirs in zip(sentences, words, strict=True):
        if theirs == wanted and citekey in cited.keys:
            return cited
    mine = set(wanted.split())
    best, near = 0.0, None
    for cited, theirs in zip(sentences, words, strict=True):
        if citekey not in cited.keys:
            continue
        shared = len(mine & set(theirs.split())) / max(len(mine), 1)
        if shared > best:
            best, near = shared, cited
    return near if near is not None and best >= NEAR else None


def survey(project: Project) -> tuple[Survey, Report]:
    """The entries placed on the manuscript and the claims in scope, with what stopped
    `currency.yaml` being read."""
    from manuscript_guard.gates.lookups import currency_facts
    from manuscript_guard.gates.passages import citing_documents
    from manuscript_guard.literature.bibfile import read_entries as read_bib

    entries, report = read_entries(project)
    sentences = cited_sentences(citing_documents(project))
    words = [statement_words(cited.text) for cited in sentences]
    placed: dict[str, CitedSentence] = {}
    for entry in entries:
        found = place(entry.sentence, entry.citekey, sentences, words)
        if found is not None:
            placed[entry.id] = found
    bib = project.path("literature") / "references.bib"
    fields = read_bib(bib) if bib.is_file() else {}
    accepted, moved = _accepted(entries, fields, sentences, words, placed)
    placed = {**placed, **moved}
    keys = sorted({key for cited in sentences for key in cited.keys})
    facts = {key: tuple(currency_facts(project, key, fields.get(key))) for key in keys
             if key in fields}  # fmt: skip
    claims: list[Claim] = []
    taken: set[tuple[Path, str, str]] = set()
    for entry in entries:
        cited = placed.get(entry.id)
        if cited is not None:
            claims.append(Claim(cited, entry.citekey, entry, facts.get(entry.citekey, ())))
            taken.add((cited.path, statement_words(cited.text), entry.citekey))
    for cited, theirs in zip(sentences, words, strict=True):
        for key in cited.keys:
            if facts.get(key) and (cited.path, theirs, key) not in taken:
                taken.add((cited.path, theirs, key))
                claims.append(Claim(cited, key, None, facts[key]))
    return Survey(entries, placed, tuple(claims), tuple(sentences), accepted), report


def _accepted(entries: tuple[Entry, ...], fields: dict[str, dict[str, str]],
              sentences: list[CitedSentence], words: list[str],
              placed: dict[str, CitedSentence]
              ) -> tuple[dict[str, CitedSentence], dict[str, CitedSentence]]:  # fmt: skip
    """Each proposal its sentence accepts, unanswered or refused only by a reply in Word,
    with that sentence, and the entries
    placed anew: on their own sentence found by its words, or on the candidate's.

    Exact words first (Basile, round 4 of #499). The one sentence whose folded words are
    the entry's, citing the old work, the candidate or both, is the entry's own: it accepts
    if and only if it cites the candidate, and the entry is placed on it. Two or more such
    sentences accept nothing. With none, the entry's placement by `NEAR` on a sentence
    citing the old work decides (round 3): it accepts if it cites the candidate too, and a
    copy elsewhere citing the candidate does not. Only where that fails is the candidate's
    own placement read, and the entry placed on it."""
    accepted: dict[str, CitedSentence] = {}
    moved: dict[str, CitedSentence] = {}
    for entry in entries:
        decision = entry.decision or {}
        candidate = decision.get("candidate")
        # A refusal read from a reply in Word gives way to the manuscript (Basile,
        # 2026-11-05): citing the work accepts it all the same. A person's own answer stands.
        answered = entry.answer and not entry.answer.get("reply")
        if decision.get("action") not in ("replace", "add") or not candidate or answered:
            continue
        keys = {key for key, one in fields.items() if is_work(one, candidate)}
        wanted = statement_words(entry.sentence)
        exact = [cited for cited, theirs in zip(sentences, words, strict=True)
                 if theirs == wanted and (entry.citekey in cited.keys or keys & set(cited.keys))]
        if len(exact) > 1:
            continue  # several sentences say it: none is taken for the entry's own
        if exact:
            own = exact[0]
            moved[entry.id] = own
            if keys & set(own.keys):
                accepted[entry.id] = own
            continue
        own = placed.get(entry.id)
        if own is not None:
            if keys & set(own.keys):
                accepted[entry.id] = own
            continue
        for key in sorted(keys):
            cited = place(entry.sentence, key, sentences, words)
            if cited is not None:
                accepted[entry.id] = cited
                moved[entry.id] = cited
                break
    return accepted, moved

def find_sentence(words: str, citekey: str, sentences: tuple[CitedSentence, ...]
                  ) -> list[CitedSentence]:  # fmt: skip
    """The citing sentences of `citekey` whose folded words hold `words`, folded, each once:
    what `references --mark` places an entry on."""
    wanted = statement_words(words)
    found: dict[tuple[Path, str], CitedSentence] = {}
    for cited in sentences:
        if citekey in cited.keys and wanted and wanted in statement_words(cited.text):
            found.setdefault((cited.path, statement_words(cited.text)), cited)
    return list(found.values())


__all__ = ["Claim", "Survey", "find_sentence", "place", "survey"]
