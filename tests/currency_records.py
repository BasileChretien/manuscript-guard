"""A worked case of reference currency on a copy of the example, for the tests that need one.

The example's sentence citing @fictionalClassSignal2019 is marked; the work is given a DOI;
the works store holds it and one candidate, a randomized trial at a stronger level; and two
readings are filed, by a person and by a model, which agree. The rules then propose to
replace the citation (D1), and nobody has answered. The sentence quotes a value the ledger
records from the cited work, so a synthesis would not be proposed in its place (K5): the
candidate is a primary study.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from manuscript_guard.contracts import load_project
from manuscript_guard.currency import command, records

CITED_KEY = "fictionalClassSignal2019"
CITED = "doi:10.5555/class.signal.2019"
CANDIDATE = "doi:10.5555/class.trial.2023"
#: Words of the example's sentence that cites the work, and of no other.
MARKED = "a disproportionality signal has been reported"
TRIAL_ABSTRACT = (
    "This randomized trial enrolled adults exposed to the drug class. "
    "Hepatic injury was the outcome of the trial. The class was associated with hepatic "
    "injury in the pooled analysis of both arms. Follow-up ended in March 2023."
)


def work(identifier: str, **fields) -> dict:
    """A works record's fields, as the tool would write them."""
    kind, _colon, value = identifier.partition(":")
    return {
        "work": identifier,
        "identifiers": {kind: value},
        "fetched_on": "2026-11-01",
        "sources": ["crossref", "pubmed"],
        "integrity": {"retracted": False, "withdrawn": False, "under_concern": False},
        **fields,
    }


def reading(reader: str, *, level: int = 2, stance: str = "supports",
            quote: str = "The class was associated with hepatic injury",
            provenance: dict | None = None, candidate: str = CANDIDATE) -> dict:  # fmt: skip
    """A reading of the case's entry: the cited work at level 4 on the scale of rare harms,
    and the review as `level`, the same question, and `stance`."""
    said = {
        "schema": "manuscript-guard/currency-reading/1",
        "entry": "c1",
        "reader": reader,
        "read_on": "2026-11-02",
        "hierarchy": "ocebm-2011",
        "scale": "harms-rare",
        "cited": {"work": CITED, "level": {
            "value": 4, "quote": "A signal was detected for the class as a whole"}},
        "candidates": [{
            "work": candidate,
            "level": {"value": level, "quote": "This randomized trial"},
            "population": {"value": "same", "quote": "adults exposed to the drug class"},
            "exposure": {"value": "same", "quote": "exposed to the drug class"},
            "outcome": {"value": "same", "quote": "Hepatic injury was the outcome"},
            "stance": {"value": stance, "quote": quote},
        }],
    }  # fmt: skip
    if provenance:
        said["provenance"] = provenance
    return said


def given_a_doi(root: Path) -> None:
    bib = root / "literature" / "references.bib"
    text = bib.read_text(encoding="utf-8")
    old = "  volume  = {7},\n"
    assert old in text
    bib.write_text(text.replace(old, old + "  doi     = {10.5555/class.signal.2019},\n", 1),
                   encoding="utf-8")  # fmt: skip


def stored(root: Path, candidate: str = CANDIDATE) -> None:
    """The works store: the cited work and the trial."""
    project = load_project(root)[0]
    records.write_work(project, work(
        CITED, title="A disproportionality signal for a fictional drug class",
        published="2019-03", publication_types=["Journal Article"],
        abstract="A signal was detected for the class as a whole (ROR 2.6, 95% CI 2.1-3.2)."))
    records.write_work(project, work(
        candidate, title="Hepatic injury with the drug class: a randomized trial",
        published="2023-06-01", publication_types=["Randomized Controlled Trial"],
        abstract=TRIAL_ABSTRACT))  # fmt: skip


def file(root: Path, said: dict, name: str) -> str:
    """File a reading through `references --reading`, as a reader would."""
    path = root / f"{name}.yaml"
    path.write_text(yaml.safe_dump(said, sort_keys=False), encoding="utf-8")
    return command.file_reading(load_project(root)[0], path)


def case(root: Path, *, readings: bool = True, candidate: str = CANDIDATE) -> Path:
    """The worked case on the project at `root`; its currency.yaml's path. `candidate` is
    the trial's id in the works store and the readings."""
    given_a_doi(root)
    stored(root, candidate)
    command.mark(load_project(root)[0], MARKED, "@" + CITED_KEY, "Ada Example")
    if readings:
        file(root, reading("Ada Example", candidate=candidate), "first")
        file(root, reading("gpt-test", provenance={"provider": "test", "model": "gpt-test"},
                           candidate=candidate), "second")  # fmt: skip
    return root / "literature" / "currency.yaml"


def decision(root: Path) -> dict:
    document = yaml.safe_load((root / "literature" / "currency.yaml").read_text("utf-8"))
    return document["entries"][0].get("decision")


#: The reply the tests file to the case's comment, and words of it a reader quotes.
REPLY = "Kept: the trial enrolled another population, so it does not replace the signal."
REFUSING = "the trial enrolled another population"


def replied(root: Path, by: str = "Ada Example", text: str = REPLY,
            day: str = "2026-11-06") -> Path:  # fmt: skip
    """A reply to the case's comment in Word, filed as `import` files it, without the
    document: the comment as `references --comments` records it, and the reply."""
    from manuscript_guard.currency import replies
    from manuscript_guard.currency.comments import AUTHOR, decision_digest

    project = load_project(root)[0]
    offered = {"n": 1, "entry": "c1", "decision": decision_digest(decision(root)),
               "author": AUTHOR, "written": "0123456789abcdef", "date": "2026-11-05"}
    found = replies.Found(offered, by, day, text)
    said = replies.file_replies(project, root / "suggestions.docx", [found], applying=True)
    assert said and "filed as" in said[-1], said
    return sorted(replies.folder(project).glob("c1.*.yaml"))[-1]
