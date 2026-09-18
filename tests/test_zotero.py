"""The Zotero client and G7 against a fake Better BibTeX.

Every test here runs without Zotero. The fake answers the three JSON-RPC calls G7 makes in
the shapes Better BibTeX 9.0.64 (Zotero 9.0.6) returned when probed on a real library of
4,688 items: `item.pandoc_filter` reports an unresolvable key with the number of items that
carry it, `item.search` with a condition returns only the matching items, and a pinned key
comes back in `note` spelled `citation-key: xyz`, not `Citation Key: xyz` as it is typed in
Extra.
"""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.gates import check_citations
from manuscript_guard.zotero import (
    Lookup,
    Reference,
    ZoteroRefused,
    ZoteroUnavailable,
    client,
    find_citations,
    lookup,
    reset_cache,
)

HEPATIC = "fictionalHepaticCohort2021"
CLASS = "fictionalClassSignal2019"


def csl(key: str, pinned: bool, library: int = 1) -> dict:
    item = {"citation-key": key, "title": key, "type": "article-journal", "library": library}
    if pinned:
        item["note"] = f"citation-key: {key}"
    return item


class FakeBBT:
    """Answers `rpc(method, params, timeout)` like Better BibTeX, from a list of items.

    Library 1 is the user's own library; any other number is a group library.
    """

    def __init__(self, items: list[dict], refuse: set[str] = frozenset()) -> None:
        self.items = items
        self.refuse = refuse
        self.calls: list[tuple[str, object]] = []

    def __call__(self, method: str, params, timeout: int = 20):
        self.calls.append((method, params))
        if method in self.refuse:
            raise ZoteroRefused(f"Better BibTeX refused {method}: method not found")
        if method == "user.groups":
            ids = sorted({1} | {i["library"] for i in self.items})
            return [{"id": i, "name": "My Library" if i == 1 else f"Group {i}"} for i in ids]
        if method == "item.pandoc_filter":
            keys = params[0]
            library = params[2] if len(params) > 2 else 1
            result = {"errors": {}, "items": {}}
            for key in keys:
                carrying = [
                    i for i in self.items if i["citation-key"] == key and i["library"] == library
                ]
                if len(carrying) == 1:
                    result["items"][key] = dict(carrying[0], id=key)
                else:
                    result["errors"][key] = len(carrying)
            return result
        if method == "item.search":
            query = params[0]
            if query == "":
                return list(self.items)
            if isinstance(query, list):  # the pinned-items condition
                return [i for i in self.items if Reference(i["citation-key"], i).pinned]
            return [i for i in self.items if query in i["citation-key"]]
        raise AssertionError(f"unexpected call {method}")


@pytest.fixture(autouse=True)
def fresh_cache():
    reset_cache()
    yield
    reset_cache()


def online(monkeypatch, fake: FakeBBT) -> FakeBBT:
    monkeypatch.setattr(client, "rpc", fake)
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: True)
    return fake


def g7(root: Path):
    project, _ = load_project(root)
    _namespace, _results, literature, _ = load_namespace(project)
    return check_citations(project, literature)


def failure_codes(report) -> set[str]:
    return {f.code for f in report.failures}


def all_codes(report) -> set[str]:
    return {f.code for f in report.findings}


# ---------------------------------------------------------------- what counts as pinned


@pytest.mark.parametrize(
    "note",
    [
        "citation-key: wadaHistoryCurrentState2011",  # what Better BibTeX returns
        "Citation Key: wadaHistoryCurrentState2011",  # what the author types in Extra
        "PMID: 1\ncitation-key: wadaHistoryCurrentState2011",
        "  CITATION KEY:wadaHistoryCurrentState2011",
    ],
)
def test_a_pin_is_recognised_in_either_spelling(note: str) -> None:
    assert Reference("wadaHistoryCurrentState2011", {"note": note}).pinned


@pytest.mark.parametrize(
    "note",
    ["", "Japanese title: 犯罪白書", "the citation-key: field is empty", "citation-key:"],
)
def test_a_note_without_a_pin_line_is_not_a_pin(note: str) -> None:
    assert not Reference("k", {"note": note}).pinned


# ---------------------------------------------------------------- lookup


def test_lookup_asks_about_the_cited_keys_only(monkeypatch) -> None:
    fake = FakeBBT([csl("a", True), csl("b", False), csl("d", True), csl("d", False)])
    monkeypatch.setattr(client, "rpc", fake)

    found = lookup(("a", "b", "c", "d"))

    assert found.found == {"a", "b"}
    assert found.pinned == {"a"}
    assert found.unpinned == {"b"}
    assert found.missing == {"c"}
    assert found.ambiguous == {"d": 2}
    assert ("item.search", [""]) not in fake.calls


def test_a_key_held_by_a_group_library_is_found_there(monkeypatch) -> None:
    fake = FakeBBT([csl("mineKey2019", True), csl("groupKey2020", True, library=7)])
    monkeypatch.setattr(client, "rpc", fake)
    result = lookup(("groupKey2020", "mineKey2019"))
    assert result.found == {"groupKey2020", "mineKey2019"}
    assert result.pinned == result.found
    assert not result.missing
    assert ("item.pandoc_filter", [["groupKey2020"], True, 7]) in fake.calls


def test_the_number_of_calls_does_not_grow_with_the_number_of_keys(monkeypatch) -> None:
    """A first version searched once per unresolved key: 3,000 cited keys Zotero did not hold
    (tests/test_robustness.py) kept a check waiting on Zotero for twenty minutes."""
    fake = FakeBBT([csl("a", True), csl("g", True, library=7)])
    monkeypatch.setattr(client, "rpc", fake)
    result = lookup(tuple(f"missingKey{i}" for i in range(3000)) + ("a",))
    assert len(result.missing) == 3000 and result.found == {"a"}
    # the user library, the list of libraries, the one group library, the pinned search
    assert len(fake.calls) == 4


def test_a_better_bibtex_without_the_fast_calls_falls_back_to_the_library(monkeypatch) -> None:
    fake = FakeBBT([csl("a", True), csl("b", False)], refuse={"item.pandoc_filter"})
    monkeypatch.setattr(client, "rpc", fake)
    result = lookup(("a", "b", "c"))
    assert result == Lookup(found=frozenset("ab"), pinned=frozenset("a"), missing=frozenset("c"))
    assert ("item.search", [""]) in fake.calls


def test_a_timeout_says_zotero_is_busy_not_that_it_is_not_running(monkeypatch) -> None:
    def slow(*_args, **_kwargs):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(client.urllib.request, "urlopen", slow)
    with pytest.raises(ZoteroUnavailable) as caught:
        client.rpc("item.search", [""], timeout=1)
    assert "did not answer" in str(caught.value)
    assert "Is Zotero running" not in str(caught.value)


def test_a_refused_connection_asks_whether_zotero_is_running(monkeypatch) -> None:
    def refused(*_args, **_kwargs):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))

    monkeypatch.setattr(client.urllib.request, "urlopen", refused)
    with pytest.raises(ZoteroUnavailable) as caught:
        client.rpc("item.search", [""], timeout=1)
    assert "Is Zotero running" in str(caught.value)


# ---------------------------------------------------------------- G7 with Zotero running


def test_pins_spelled_as_better_bibtex_spells_them_pass(project: Path, monkeypatch) -> None:
    """The false positive that failed all 57 citations of a real paper, every one pinned."""
    online(monkeypatch, FakeBBT([csl(HEPATIC, True), csl(CLASS, True)]))
    report = g7(project)
    assert not failure_codes(report)
    assert "pinning-unchecked" not in all_codes(report)


def test_g7_asks_zotero_about_the_cited_keys_only(project: Path, monkeypatch) -> None:
    fake = online(monkeypatch, FakeBBT([csl(HEPATIC, True), csl(CLASS, True)]))
    g7(project)
    assert ("item.search", [""]) not in fake.calls
    assert ("item.pandoc_filter", [[CLASS, HEPATIC], True]) in fake.calls


def test_a_zotero_that_cannot_be_read_is_not_called_absent(project: Path, monkeypatch) -> None:
    def busy(*_args, **_kwargs):
        raise ZoteroUnavailable("Better BibTeX did not answer item.pandoc_filter within 20 s")

    monkeypatch.setattr(client, "rpc", busy)
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: True)
    report = g7(project)
    messages = " ".join(f.message for f in report.findings)
    assert "zotero-unreadable" in all_codes(report)
    assert "could not be read" in messages
    assert "not running" not in messages


def test_nothing_cited_means_nothing_to_warn_about(project: Path, monkeypatch) -> None:
    """An empty references.bib in a new project is not a problem until something is cited."""
    main = project / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8").replace("@", "at-"), encoding="utf-8")
    (project / "literature" / "references.bib").write_text("", encoding="utf-8")
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: False)
    assert "no-reference-source" not in all_codes(g7(project))


def test_an_empty_bib_is_called_empty_not_absent(project: Path, monkeypatch) -> None:
    (project / "literature" / "references.bib").write_text("", encoding="utf-8")
    monkeypatch.setattr("manuscript_guard.gates.citations.available", lambda: False)
    report = g7(project)
    [finding] = [f for f in report.findings if f.code == "no-reference-source"]
    assert finding.message.startswith("references.bib is empty")


# ---------------------------------------------------------------- citations in source


def test_a_citation_group_wrapped_onto_a_new_line_keeps_its_first_key() -> None:
    """The first key of a wrapped group used to be found by neither pattern."""
    text = "x [@alphaKey2022;\n@betaKey2023]. y [@gammaKey2019; @deltaKey2020].\n"
    uses = find_citations(text, Path("m.md"))
    expected = {"alphaKey2022", "betaKey2023", "gammaKey2019", "deltaKey2020"}
    assert {u.citekey for u in uses} == expected
    assert not any(u.narrative for u in uses)
    assert {u.citekey: u.line for u in uses}["betaKey2023"] == 2


def test_a_blank_line_ends_a_citation_group() -> None:
    """A stray "[" must not swallow the next paragraph's citations into a group."""
    text = "see [the note\n\nAs @jonesKey2021 showed [@smithKey2020].\n"
    uses = {u.citekey: u.narrative for u in find_citations(text, Path("m.md"))}
    assert uses == {"jonesKey2021": True, "smithKey2020": False}
