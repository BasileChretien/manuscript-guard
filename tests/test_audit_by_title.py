"""The audit's entries with no DOI and no PMID: sorted, and the articles and books looked up
in Crossref by their title (the author's decision of 2026-11-12). Every answer comes from a
table the test gives as the transport: no test opens a connection to a registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.audit import audit
from manuscript_guard.auditing import by_title
from manuscript_guard.auditing.reader import for_a_reader
from manuscript_guard.cli import main
from manuscript_guard.lookup import http
from manuscript_guard.lookup import run as lookup
from manuscript_guard.lookup.http import Response

#: The seven entries of the author's paper with neither a DOI nor a PMID (2026-11-12), the
#: articles given the volume and pages a journal prints, and one entry with a DOI.
SEVEN = (
    "# Results\n\nIt rose [1], as before [2-8].\n\n# References\n\n"
    "1. Ross KL. Ghosts in the classroom: Passive disengagement and its implications for "
    "teachers. Teach Teach. 2019;25(3):312-25.\n"
    "2. Børte K, Nesje K, Lillejord S. Barriers to student active learning in higher education. "
    "Teach High Educ. 2023;28(3):597-615.\n"
    "3. Bandura A. Social foundations of thought and action. Englewood Cliffs, NJ. 1986\n"
    "4. Accueil | Moodle.org. https://moodle.org/. Accessed 5 Aug 2025.\n"
    "5. Comment accéder aux études de santé ? | Parcoursup. 2023. "
    "https://www.parcoursup.fr/sante\n"
    "6. Arrêté du 21 décembre 2021 relatif à la formation. "
    "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000044\n"
    "7. Education and Socioeconomic Status Factsheet. "
    "https://www.apa.org/pi/ses/resources/publications/education\n"
    "8. Smith J. A cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1\n"
)
ROSS = "10.1080/13540602.2019.1598847"
#: Crossref's record of the article of entry 1, its title in two parts and in other case,
#: as Crossref keeps it.
GHOSTS = {"DOI": ROSS.upper(), "type": "journal-article", "title": ["Ghosts in the classroom"],
          "subtitle": ["passive disengagement and its implications for teachers"],
          "author": [{"family": "Ross", "given": "Kyle L."}],
          "published-online": {"date-parts": [[2019, 4, 2]]},
          "issued": {"date-parts": [[2019, 4]]}}  # fmt: skip


def _json(status: int, body: object) -> Response:
    return Response(status, {"Content-Type": "application/json"}, json.dumps(body).encode())


class Registries:
    """A table that answers as the registries would: Crossref's search with `items`, each
    DOI with a record, and a retraction on those `retracted` names."""

    def __init__(self, items: list[dict] | None = None, *, search_status: int = 200,
                 retracted: tuple[str, ...] = ()) -> None:  # fmt: skip
        self.items = [GHOSTS] if items is None else items
        self.search_status = search_status
        self.retracted = retracted
        self.seen: list[str] = []

    def __call__(self, request, timeout):  # noqa: ARG002 - the transport's signature
        self.seen.append(request.shown)
        if "query.bibliographic" in request.params:
            if self.search_status != 200:
                return _json(self.search_status, {})
            return _json(200, {"status": "ok", "message-type": "work-list",
                               "message": {"items": self.items}})  # fmt: skip
        if "/works/doi:" in request.base:
            doi = request.base.rsplit("doi:", 1)[1].lower()
            return _json(200, {"id": "W1", "is_retracted": doi in self.retracted})
        if "/works/" in request.base:
            doi = request.base.rsplit("/works/", 1)[1].lower()
            notices = ([{"type": "retraction", "DOI": "10.5555/notice",
                         "updated": {"date-parts": [[2022, 1, 2]]}}]
                       if doi in self.retracted else [])  # fmt: skip
            return _json(200, {"status": "ok", "message-type": "work", "message": {
                "DOI": doi, "type": "journal-article", "title": ["A work"],
                "updated-by": notices}})  # fmt: skip
        return _json(404, {"responseCode": 100})

    @property
    def searched(self) -> list[str]:
        return [shown for shown in self.seen if "query.bibliographic" in shown]


_PACER = lookup.Pacer


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch) -> Registries:
    """The audit's transport answered from a table, and its pace without a wait."""
    table = Registries()
    monkeypatch.setattr(http, "default_transport", table)
    monkeypatch.setattr(lookup, "Pacer", lambda: _PACER(sleep=lambda seconds: None))
    return table


def _paper(tmp_path: Path, text: str = SEVEN) -> Path:
    paper = tmp_path / "paper.md"
    paper.write_text(text, encoding="utf-8")
    return paper


def _section(out: str) -> str:
    return out.split("=== References (G7)")[1].split("\n\n")[0]


# ------------------------------------------------------------------------------ sorting


def test_the_author_s_seven_entries_are_sorted_by_their_shape(tmp_path: Path) -> None:
    """The articles and the book are to be looked up by their title; the web pages and the
    decree are no DOI expected, each with why."""
    census = audit([_paper(tmp_path)], None).references[0]
    sorted_ = by_title.unasked(census)
    assert [(one.entry.label, one.sorted.kind) for one in sorted_] == [
        ("entry 1", by_title.ARTICLE), ("entry 2", by_title.ARTICLE),
        ("entry 3", by_title.BOOK), ("entry 4", by_title.WEB), ("entry 5", by_title.WEB),
        ("entry 6", by_title.LEGAL), ("entry 7", by_title.WEB)]  # fmt: skip
    assert [one.sorted.why for one in sorted_][3:] == [
        "it says when it was accessed",
        "it gives a web address and nothing a journal or a publisher adds",
        'it opens with "Arrêté"',
        "it gives a web address and nothing a journal or a publisher adds"]  # fmt: skip
    assert [(c.title, c.family, c.year) for c in (one.cited for one in sorted_[:3])] == [
        ("Ghosts in the classroom: Passive disengagement and its implications for teachers",
         "Ross", 2019),
        ("Barriers to student active learning in higher education", "Børte", 2023),
        ("Social foundations of thought and action", "Bandura", 1986)]  # fmt: skip


@pytest.mark.parametrize(("text", "kind"), [
    # An author-year article, and Harvard's with its title in quotes.
    ("Ross, K. L. (2019). Ghosts in the classroom. Teachers and Teaching, 25(3), 312-325.",
     by_title.ARTICLE),
    ("Ross, K. (2019) 'Ghosts in the classroom', Teachers and Teaching, 25, 312-325.",
     by_title.ARTICLE),
    ("Smith J. A chapter of things. In: Jones K, editor. A book. London: Press; 2019. p. 1-9.",
     by_title.CHAPTER),
    ("Smith J. Hepatic injury in reports. 2nd ed. London: Example Press; 2019.", by_title.BOOK),
    ("World Example Agency. Hepatic injury [Internet]. Geneva: Example Agency; 2020 [cited "
     "2025 Mar 5]. Available from: https://example.org/x", by_title.WEB),
    ("Regulation (EU) 2016/679 of the European Parliament. Official Journal of the European "
     "Union. 2016.", by_title.LEGAL),
    # A person named Ley is no law.
    ("Ley J. A book of things. London: Example Press; 2019.", by_title.BOOK),
    ("Smith J. Personal communication. 2019.", by_title.OTHER),
    # An article with no volume and no pages is not sorted (DESIGN.md, Known gaps).
    ("Ross KL. Ghosts in the classroom. Teachers College Record.", by_title.OTHER),
    ("Ross KL. Ghosts in the classroom. Teachers College Record. 2019.", by_title.OTHER),
])  # fmt: skip
def test_each_shape_is_sorted(text: str, kind: str) -> None:
    assert by_title.sort(text).kind == kind


def test_a_title_is_read_past_initials_and_an_abbreviation() -> None:
    """"Ross K. L." ends at its last initial, and "U.S." ends no title; an author-year
    entry's title follows its year, and Harvard's quoted title is the quoted part."""
    for text in ("Ross K. L. Ghosts in the U.S. classroom. Teach. 2019;1:2.",
                 "Ross K.L. Ghosts in the U.S. classroom. Teach. 2019;1:2.",
                 "Ross, K. L., & Smith, J. (2019). Ghosts in the U.S. classroom. Teach, 1(2), "
                 "3-4.",
                 "Ross, K.L. (2019) 'Ghosts in the U.S. classroom', Teach, 1(2), pp. 3-4."):
        said = by_title.cited(text)
        assert (said.title, said.family, said.year) == (
            "Ghosts in the U.S. classroom", "Ross", 2019), text
    # A quoted title closes at the quote after it, not at an apostrophe inside a word; and a
    # given name first, as a BibTeX style prints it, leaves the family name.
    quoted = by_title.cited("Ross, K. (2019) 'Children's ghosts', Teach, 1(2), pp. 3-4.")
    assert (quoted.title, quoted.family) == ("Children's ghosts", "Ross")
    given = by_title.cited("K. L. Ross. Ghosts in the classroom. Teach, 25(3):312-325, 2019.")
    assert (given.title, given.family, given.year) == ("Ghosts in the classroom", "Ross", 2019)


# ---------------------------------------------------------------------- the near match


def _cited() -> tuple[by_title.Cited, str]:
    text = ("Børte K, Nesje K. Barriers to student active learning: a review. Teach High Educ. "
            "2023;28(3):597-615.")  # fmt: skip
    return by_title.cited(text), by_title.fold(text)


def _work(**changed) -> dict:
    work = {"doi": "10.1/x", "title": "BARRIERS TO STUDENT ACTIVE LEARNING", "subtitle": "A review",
            "authors": [{"family": "Borte", "given": "Kari"}], "years": {"issued": 2023}}
    return {**work, **changed}


@pytest.mark.parametrize(("changed", "taken"), [
    ({}, True),
    ({"years": {"print": 2022, "online": 2023}}, True),
    ({"years": {"issued": 2021}}, False),
    ({"authors": [{"family": "Nesje"}, {"family": "Børte"}]}, False),
    ({"authors": [{"group": "Example Group"}]}, False),
    ({"authors": []}, False),
    ({"subtitle": "A systematic review"}, False),
    ({"title": "Barriers to active learning", "subtitle": "A review"}, False),
])  # fmt: skip
def test_a_work_is_taken_only_when_near_exact(changed: dict, taken: bool) -> None:
    """The same title, case, punctuation and accents folded; the same first author; and one
    of the work's years the cited one."""
    said, opening = _cited()
    assert by_title.near_exact(said, opening, _work(**changed)) is taken


# ------------------------------------------------------------------------ the audit


def test_an_article_found_by_its_title_is_looked_up_by_its_doi(tmp_path: Path, registries,
                                                               capsys) -> None:  # fmt: skip
    """Entry 1 is found by its title, and its DOI looked up as an entry's own: a retraction
    is said of it. Entries 2 and 3 Crossref does not have; the web pages and the decree are
    asked of nobody."""
    registries.retracted = (ROSS,)
    assert main(["audit", str(_paper(tmp_path)), "--lookup", "--details"]) == 0
    out = capsys.readouterr().out
    section = _section(out)
    assert (f"        an article, found by its title: DOI {ROSS}, then looked up as the "
            "others") in section  # fmt: skip
    assert ("      line 8: entry 2: Børte K, Nesje K, Lillejord S. Barriers to student active "
            "learning in higher education. Te…\n        an article with no DOI given, and none "
            "found by its title: check it by hand") in section  # fmt: skip
    assert ("        a book with no DOI given, and none found by its title: check it by "
            "hand") in section  # fmt: skip
    assert "        no DOI expected: a legal or official text (it opens with \"Arrêté\")" in section
    assert ("    line 7: entry 1 is retracted, by what Crossref and OpenAlex say (notice "
            "doi:10.5555/notice, 2022-01-02)") in section  # fmt: skip
    assert len(registries.searched) == 3
    assert not any("moodle" in shown or "Parcoursup" in shown for shown in registries.seen)
    assert ("8 entries read, 1 with a DOI; 2 works looked up, 1 of them found by title; 4 "
            "entries with no DOI expected and 2 entries to check by hand, with no DOI or PMID "
            "found: see below") in out  # fmt: skip


def test_the_json_findings_name_the_entries_to_check(tmp_path: Path, registries, capsys) -> None:
    assert main(["audit", str(_paper(tmp_path)), "--lookup", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)["findings"]
    assert [(f["code"], f["line"]) for f in said if f["code"] == "not-found-by-title"] == [
        ("not-found-by-title", 8), ("not-found-by-title", 9)]
    assert any(f["code"] == "looked-up" and "which gave doi:" + ROSS in f["message"]
               and f["line"] == 7 for f in said)  # fmt: skip


def test_two_works_of_the_title_are_neither_taken(tmp_path: Path, registries, capsys) -> None:
    registries.items = [GHOSTS, {**GHOSTS, "DOI": "10.1080/other"}]
    assert main(["audit", str(_paper(tmp_path)), "--lookup", "--details"]) == 0
    section = _section(capsys.readouterr().out)
    assert ("an article with no DOI given; Crossref has 2 works of its title, first author and "
            f"year (doi:{ROSS}, doi:10.1080/other): check it by hand") in section  # fmt: skip


def test_a_notice_of_the_title_is_no_work(tmp_path: Path, registries, capsys) -> None:
    """A peer review filed under the article's title is not the article."""
    registries.items = [{**GHOSTS, "type": "peer-review"}]
    assert main(["audit", str(_paper(tmp_path)), "--lookup", "--details"]) == 0
    section = _section(capsys.readouterr().out)
    assert ", found by its title" not in section
    assert "entry 1: Ross KL" in section


def test_a_search_that_did_not_answer_is_said_and_not_kept(tmp_path: Path, registries,
                                                           capsys) -> None:  # fmt: skip
    registries.search_status = 503
    kept = tmp_path / "kept"
    assert main(["audit", str(_paper(tmp_path)), "--lookup", "--details", "--lookup-cache",
                 str(kept)]) == 0  # fmt: skip
    section = _section(capsys.readouterr().out)
    assert ("an article with no DOI given; Crossref did not answer (HTTP 503), so it was not "
            "looked up by its title: check it by hand") in section  # fmt: skip
    assert not list(kept.glob("title_*.json"))


def test_a_dry_run_says_what_it_would_ask_and_sends_nothing(tmp_path: Path, registries,
                                                            capsys) -> None:  # fmt: skip
    assert main(["audit", str(_paper(tmp_path)), "--lookup", "--dry-run", "--details"]) == 0
    out = capsys.readouterr().out
    assert registries.seen == []
    assert ('        an article: would ask Crossref for the title "Ghosts in the classroom: '
            'Passive disengagement and its implications for teachers", first author Ross, '
            "2019") in out  # fmt: skip
    assert "3 entries to be looked up by title and 4 entries with no DOI expected" in out


def test_without_lookup_nothing_is_asked_and_the_reader_is_told_plainly(
    tmp_path: Path, registries, capsys
) -> None:
    assert main(["audit", str(_paper(tmp_path)), "--details"]) == 0
    out = capsys.readouterr().out
    assert registries.seen == []
    line = ("        an article: looked up in Crossref by its title only when the references are "
            "looked up (--lookup)")  # fmt: skip
    assert line in out
    assert for_a_reader(line).endswith("only when the references are looked up")
    assert "Crossref for the title of an article or a book that gives neither" in out


def test_a_title_kept_is_not_asked_again(tmp_path: Path, registries, capsys) -> None:
    kept = tmp_path / "kept"
    paper = _paper(tmp_path)
    assert main(["audit", str(paper), "--lookup", "--lookup-cache", str(kept)]) == 0
    assert len(list(kept.glob("title_*.json"))) == 3
    registries.seen.clear()
    assert main(["audit", str(paper), "--lookup", "--lookup-cache", str(kept), "--details"]) == 0
    assert registries.seen == []
    assert f"found by its title: DOI {ROSS}" in capsys.readouterr().out


def test_a_bibitem_is_sorted_with_its_tex_taken_out(tmp_path: Path) -> None:
    from manuscript_guard.auditing.references import Census, Entry

    entry = Entry("\\bibitem{ross}", 3, key="ross", text=(
        "K.~L. Ross. \\newblock \\emph{Ghosts in the classroom}. \\newblock Teach Teach, "
        "25(3):312--325, 2019."))  # fmt: skip
    census = Census(tmp_path / "paper.tex", (entry,), style="keyed")
    (one,) = by_title.unasked(census)
    assert one.sorted.kind == by_title.ARTICLE
    assert one.cited.title == "Ghosts in the classroom"
