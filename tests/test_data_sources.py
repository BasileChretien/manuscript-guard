"""The record of the datasets considered, and what the paper says of the one chosen.

The record, `design/data_sources.yaml`, is written here for two fictional sources: an archive
anyone may download, and a claims database a committee decides on, whose custodian forbids
a count below eleven and any sending of its data. Their access pages are stored as text, as
the data-sources skill stores the pages it reads. What each finding catches is in
`tests/test_corruption.py`; here are the record's shape, the readings of the statement's
words, and the skill's place among the others.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from manuscript_guard.contracts._schema import validate
from manuscript_guard.data_sources import (
    ON_REQUEST,
    OPENLY,
    named,
    route_differs,
    says,
    sentences,
)

OPEN, CLAIMS = "ora", "encd"
OPEN_NAME = "Open Reports Archive"
CLAIMS_NAME = "Example National Claims Database"

#: The two access pages, as stored. Fictional, and written for these tests.
PAGES = {
    "ora-access.txt": (
        "Open Reports Archive\n\nQuarterly extracts of all reports are free to download by "
        "anyone,\nwithout registration. Data are released under the CC BY 4.0 licence.\nNew "
        "extracts appear within three months of each quarter's end.\n"
    ),
    "encd-access.txt": (
        "Access to the Example National Claims Database\n\nResearchers apply to the "
        "scientific committee, which meets every two months. A fee of 2,000 EUR is charged "
        "per extraction.\nNo cell with fewer than 11 patients may be published. The data may "
        "not be transferred to any third party, cloud and AI services included.\n"
    ),
}


def _read(about, claim: str, quote: str, page: str) -> dict[str, Any]:
    return {"about": about, "claim": claim, "source_url": f"https://{page[:3]}.invalid/access",
            "read_on": "2026-10-21", "quote": quote, "page": page}  # fmt: skip


def record() -> dict[str, Any]:
    """A whole record: two candidates, each claim sourced, the open archive chosen."""
    return copy.deepcopy(
        {
            "schema": "manuscript-guard/data-sources/1",
            "question": {
                "stated_by": "A. Author",
                "stated_on": "2026-10-21",
                "question": "Is example-drug associated with reports of hepatic injury?",
                "needs": {
                    "population": "reports naming example-drug",
                    "period": "2015 onwards",
                    "variables": ["drug", "reaction", "age", "sex"],
                },
            },
            "candidates": [
                {
                    "id": OPEN,
                    "name": OPEN_NAME,
                    "also_known_as": ["ORA"],
                    "custodian": "Example Medicines Agency",
                    "landing_page": "https://ora.invalid/",
                    "identifiers": [{"scheme": "doi", "id": "10.5555/ora.2026"}],
                    "covers": {
                        "population": "spontaneous reports",
                        "variables": [
                            {"name": "drug", "provided": "yes"},
                            {"name": "age", "provided": "partly", "note": "often missing"},
                        ],
                    },
                    "access": {"route": "open-download", "cost": "free",
                               "delay": "three months after each quarter"},  # fmt: skip
                    "terms": {"licence": "CC BY 4.0"},
                    "claims": [
                        _read(["route", "cost"], "anyone may download it, free",
                              "free to download by anyone, without registration",
                              "ora-access.txt"),
                        _read("licence", "CC BY 4.0",
                              "released under the CC BY 4.0 licence", "ora-access.txt"),
                        _read("delay", "a quarter's extract three months after it",
                              "New extracts appear within three months of each quarter's end",
                              "ora-access.txt"),
                    ],  # fmt: skip
                },
                {
                    "id": CLAIMS,
                    "name": CLAIMS_NAME,
                    "also_known_as": ["ENCD"],
                    "custodian": "Example Health Insurance Fund",
                    "access": {"route": "application", "cost": "2,000 EUR per extraction",
                               "delay": "about four months"},  # fmt: skip
                    "terms": {"minimum_cell_count": 11, "restricts_sending": True},
                    "claims": [
                        _read("route", "a committee decides",
                              "Researchers apply to the scientific committee", "encd-access.txt"),
                        _read("cost", "2,000 EUR an extraction",
                              "A fee of 2,000 EUR is charged per extraction", "encd-access.txt"),
                        _read("minimum_cell_count", "no cell under 11",
                              "No cell with fewer than 11 patients may be published",
                              "encd-access.txt"),
                        _read("restricts_sending", "no third party, AI services included",
                              "may not be transferred to any third party, cloud and AI services "
                              "included", "encd-access.txt"),
                        {"about": "delay", "claim": "about four months from application",
                         "stated_by": "A. Author", "stated_on": "2026-10-21"},
                    ],  # fmt: skip
                },
            ],
            "ranking": [
                {"source": OPEN, "why": "open, and covers the period"},
                {"source": CLAIMS, "why": "exposure measured better, four months away"},
            ],
            "decision": {"chosen": [OPEN], "decided_by": "A. Author",
                         "decided_on": "2026-10-21", "why": "no wait"},  # fmt: skip
        }
    )


def write_record(root: Path, document: dict[str, Any] | None = None, *, pages: bool = True) -> Path:
    """Write the record, and the pages its claims were read from."""
    path = root / "design" / "data_sources.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(record() if document is None else document, sort_keys=False,
                          allow_unicode=True)  # fmt: skip
    path.write_bytes(text.encode("utf-8"))
    if pages:
        folder = root / "design" / "data_sources" / "pages"
        folder.mkdir(parents=True, exist_ok=True)
        for name, page in PAGES.items():
            (folder / name).write_bytes(page.encode("utf-8"))
    return path


def name_in_plan(root: Path, words: str) -> None:
    """Put words in the plan's Population and data source section, after its first line."""
    plan = root / "design" / "plan.md"
    text = plan.read_bytes().decode("utf-8")
    heading = "## Population and data source\n\n"
    assert heading in text
    plan.write_bytes(text.replace(heading, f"{heading}{words}\n\n", 1).encode("utf-8"))


def set_statement(root: Path, statement: str) -> None:
    """Make the manuscript's Data availability statement say this, and nothing else."""
    main = root / "manuscript" / "main.md"
    text = main.read_bytes().decode("utf-8")
    start = text.index("# Data availability\n")
    end = text.index("\n# ", start + 1)
    main.write_bytes((text[:start] + f"# Data availability\n\n{statement}\n" + text[end:]).encode())


# -------------------------------------------------------------------------------- the record


def test_the_record_written_here_holds_to_its_schema() -> None:
    report = validate(record(), "data-sources", Path("design/data_sources.yaml"))
    assert report.ok, report.render()


@pytest.mark.parametrize(
    "change",
    [
        # A claim read from a page with nothing to hold it to, and one said by a person that
        # also carries a quote: each is either read or said.
        lambda d: d["candidates"][0]["claims"][0].pop("page"),
        lambda d: d["candidates"][1]["claims"][4].update(quote="four months"),
        lambda d: d["candidates"][0]["claims"][0].update(stated_by="A. Author"),
        # A route that is none of the six, a page outside the folder, an id that is no slug.
        lambda d: d["candidates"][0]["access"].update(route="ask nicely"),
        lambda d: d["candidates"][0]["claims"][0].update(page="../plan.md"),
        lambda d: d["candidates"][0].update(id="Open Archive"),
        # The question asked first, with who stated it; a decision with who made it.
        lambda d: d["question"].pop("stated_by"),
        lambda d: d["decision"].pop("decided_by"),
        lambda d: d["decision"].update(chosen=[]),
        lambda d: d["candidates"][1]["terms"].update(minimum_cell_count=1),
    ],
)
def test_a_record_out_of_shape_is_refused(change) -> None:
    document = record()
    change(document)
    assert not validate(document, "data-sources", Path("x")).ok


# ------------------------------------------------------------------ what the statement says


def test_a_source_is_named_by_any_of_its_names_as_the_words_they_are() -> None:
    source = record()["candidates"][0]
    assert named("Reports came from the open reports\narchive.", source)
    assert named("We used ORA extracts.", source)
    assert named("doi:10.5555/ORA.2026.", source)
    assert not named("We used CORA extracts.", source)  # the end of a longer word
    assert not named("We used ORAL extracts.", source)  # nor the start of one


def test_a_statement_is_read_sentence_by_sentence() -> None:
    text = "Data are open.  They\nwrap, e.g. here. 2 more\n\nA new paragraph"
    assert sentences(text) == ["Data are open.", "They wrap, e.g. here.", "2 more",
                               "A new paragraph"]  # fmt: skip


@pytest.mark.parametrize(
    ("sentence", "phrase", "said"),
    [
        ("Data are available on reasonable request.", ON_REQUEST, True),
        ("Data are available upon request to the custodian.", ON_REQUEST, True),
        ("Data are available from the corresponding author.", ON_REQUEST, True),
        ("Data are available by contacting the corresponding author.", ON_REQUEST, True),
        ("The data are publicly available.", OPENLY, True),
        ("The data are available for download.", OPENLY, True),
        ("The data are freely accessible.", OPENLY, True),
        ("The data are not publicly available.", OPENLY, False),
        ("The data cannot be made publicly available.", OPENLY, False),
        ("The data aren't publicly available.", OPENLY, False),
        ("Neither the data nor the code are publicly available.", OPENLY, False),
        # A negation in another clause is that clause's.
        ("The data cannot be shared, but summaries are publicly available.", OPENLY, True),
        ("The data are not ours to share; they are available on request.", ON_REQUEST, True),
        # Far before the phrase, a negation is not its own.
        ("Not one of the files that we drew from the archive is publicly available.", OPENLY,
         True),
    ],
)  # fmt: skip
def test_a_phrase_is_said_unless_its_clause_denies_it(sentence: str, phrase, said: bool) -> None:
    assert says(sentence, phrase) is said


def _sources(*routes: str) -> list[dict[str, Any]]:
    found = []
    for number, route in enumerate(routes):
        found.append({"id": f"s{number}", "name": f"Source {'AB'[number]}",
                      "access": {"route": route}})  # fmt: skip
    return found


@pytest.mark.parametrize(
    ("statement", "routes", "differs"),
    [
        ("The data are available on request.", ("open-download",), [("s0", "on request")]),
        ("The data are available on request.", ("application",), []),
        ("The data are publicly available.", ("data-use-agreement",), [("s0", "publicly")]),
        ("The data are publicly available.", ("registration",), []),
        ("The data are not publicly available. They are available on application.",
         ("application",), []),
        # Said openly elsewhere, "on request" is of something else: the analysis files.
        ("Source A is publicly available. The analysis files are available on request.",
         ("open-download",), []),
        # A sentence about the code alone is about no data.
        ("The code is available on request.", ("open-download",), []),
        # Each sentence of its own source.
        ("Source A is publicly available. Source B data are available on request.",
         ("open-download", "application"), []),
        ("Source A data are available on request. Source B is publicly available.",
         ("open-download", "application"), [("s0", "on request"), ("s1", "publicly")]),
        # A sentence that names none, of sources on two sides: of neither.
        ("The data are publicly available.", ("open-download", "application"), []),
        # A source whose route is not known is held to nothing.
        ("Source A data are available on request.", (), []),
    ],
)  # fmt: skip
def test_the_statement_is_held_to_each_source_s_route(statement, routes, differs) -> None:
    sources = _sources(*routes) if routes else [{"id": "s0", "name": "Source A"}]
    assert route_differs(statement, sources) == differs
