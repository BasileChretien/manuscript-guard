"""A real DOI with an invented title, the commonest fabricated citation (item 7b of the
editor's list; Basile, 2026-11-26, "warn on few shared words"): under `audit --lookup`, each
entry whose DOI's record is of a work whose title, with its subtitle, holds under half the
searched words of the title the entry gives. Every answer comes from a table the test gives as
the transport: no test opens a connection to a registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from manuscript_guard.cli import main
from manuscript_guard.lookup import http
from manuscript_guard.lookup import run as lookup
from manuscript_guard.lookup.http import Response

GIVEN = "Weekly outcome counts in a regional cohort of older adults"


def _paper(title: str = GIVEN, doi: str = "10.5555/given.1") -> str:
    return ("# Results\n\nIt rose [1].\n\n# References\n\n"
            f"1. Smith A, Lee B. {title}. J Test. 2020;12(3):45-56. doi:{doi}\n")


class Registries:
    """Crossref and OpenAlex answering for each DOI of `records` with its title and
    subtitle, OpenAlex with the title `openalex` gives where it gives one, 404 for any
    other."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[str, str]] = {}
        self.openalex: dict[str, str] = {}

    def __call__(self, request, timeout):  # noqa: ARG002 - the transport's signature
        body: dict = {}
        if "/works/doi:" in request.base:
            doi = request.base.rsplit("doi:", 1)[1].lower()
            if doi in self.records:
                title, subtitle = self.records[doi]
                body = {"id": "W1", "is_retracted": False, "type": "article",
                        "title": self.openalex.get(doi, title), "publication_year": 2020}
        elif "/works/" in request.base:
            doi = request.base.rsplit("/works/", 1)[1].lower()
            if doi in self.records:
                title, subtitle = self.records[doi]
                body = {"status": "ok", "message-type": "work", "message": {
                    "DOI": doi, "type": "journal-article", "title": [title],
                    "subtitle": [subtitle] if subtitle else [], "updated-by": []}}  # fmt: skip
        if not body:
            return Response(404, {}, b"Resource not found.")
        return Response(200, {"Content-Type": "application/json"}, json.dumps(body).encode())


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch) -> Registries:
    table = Registries()
    monkeypatch.setattr(http, "default_transport", table)
    paced = lookup.Pacer
    monkeypatch.setattr(lookup, "Pacer", lambda: paced(sleep=lambda seconds: None))
    return table


def _differs(tmp_path: Path, capsys, text: str) -> list[dict]:
    paper = tmp_path / "paper.md"
    paper.write_text(text, encoding="utf-8")
    main(["audit", str(paper), "--lookup", "--json"])
    return [f for f in json.loads(capsys.readouterr().out)["findings"]
            if f["code"] == "reference-title-differs"]  # fmt: skip


def test_a_doi_of_another_work_is_said_with_both_titles(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    registries.records["10.5555/given.1"] = ("Mitochondrial dynamics in yeast", "")
    (said,) = _differs(tmp_path, capsys, _paper())
    assert said["gate"] == "G7"
    for words in ("10.5555/given.1", "Mitochondrial dynamics in yeast", GIVEN, "0 of the"):
        assert words in said["message"], (words, said["message"])


def test_it_is_a_note_with_its_record_on_published_papers(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """Right in 1 of the 6 notes two readers judged on 100 PMC papers (2026-11-27), the rest
    titles given in translation: under half, so a note, its record said with it (Basile,
    2026-11-27), in `--json` and in the report as text."""
    from manuscript_guard.auditing.references import TITLE_RECORD

    registries.records["10.5555/given.1"] = ("Mitochondrial dynamics in yeast", "")
    (said,) = _differs(tmp_path, capsys, _paper())
    assert said["severity"] == "info" and said["hint"] == TITLE_RECORD
    assert "1 of the 6" in TITLE_RECORD and "translation" in TITLE_RECORD
    paper = tmp_path / "paper.md"
    main(["audit", str(paper), "--lookup"])
    text = capsys.readouterr().out
    # A note of a title is no word on the work's standing, which is still said (round 1 of
    # #846).
    assert TITLE_RECORD in text and "no registry said a work was retracted" in text
    cited = tmp_path / "cited.md"
    main(["audit", str(paper), "--lookup", "--cited", str(cited)])
    capsys.readouterr()
    listed = cited.read_text(encoding="utf-8")
    assert "no registry said it was retracted" in listed
    assert "a note: entry 1: its DOI" in listed and TITLE_RECORD in listed


def test_each_record_is_counted_alone_and_the_one_counted_is_quoted(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """Crossref's title shares 1 of the 7 searched words, OpenAlex's 3: each under half, so
    the DOI is said, and the finding quotes OpenAlex's title with its own count. Counted in
    both at once they shared 4 of 7, and the entry was cleared, or said with a count that
    was not the quoted title's (round 1 of #846)."""
    registries.records["10.5555/given.1"] = (
        "Conteos semanales de resultados en una cohorte regional", "")
    registries.openalex["10.5555/given.1"] = "Weekly counts in a cohort"
    (said,) = _differs(tmp_path, capsys, _paper())
    assert '"Weekly counts in a cohort", which has 3 of the 7' in said["message"], said


def test_a_title_that_holds_its_record_s_and_more_is_held_to_it(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """The record's title is looked for outside the title read, never within it: a title
    that holds the record's and as many words again is held to the record (round 1 of
    #846)."""
    registries.records["10.5555/given.1"] = ("Statin therapy and fracture risk", "")
    given = "Statin therapy and fracture risk in older women with chronic kidney disease"
    (said,) = _differs(tmp_path, capsys, _paper(given))
    assert "4 of the 9" in said["message"], said
    # The record's whole title with a subtitle it does not hold is the record's (round 2).
    given = "Statin therapy and fracture risk: a cohort of older women with kidney disease"
    assert _differs(tmp_path, capsys, _paper(given)) == []
    # A record whose own title holds a colon (round 3).
    registries.records["10.5555/given.1"] = ("COVID-19: lessons learned", "")
    given = "COVID-19: lessons learned: a review of hospital outcomes in five countries"
    assert _differs(tmp_path, capsys, _paper(given)) == []


@pytest.mark.parametrize("journal", ["Sci. China Life Sci.", "Proc. Natl Acad Sci."])
def test_an_entry_that_holds_its_record_s_title_word_for_word_is_not_said(
    tmp_path: Path, capsys, registries: Registries, journal: str
) -> None:
    """A list that puts the title between commas, "Z.C. Dong, Y. Chen, Transcriptomics:
    advances and approaches, Sci. China Life Sci. 56 (2013)": the entry's reader took "China
    Life Sci" for its title, and the DOI was said to be another work's (2 of the 9 notes on
    100 PMC papers, 2026-11-27). An entry holding its record's title, folded, word for word
    names that work."""
    registries.records["10.5555/given.1"] = (GIVEN.upper(), "")
    text = (f"# Results\n\nIt rose [1].\n\n# References\n\n[1] A. Smith, B. Lee, {GIVEN}, "
            f"{journal} 56 (2013) 960-967, https://doi.org/10.5555/given.1.\n")  # fmt: skip
    assert _differs(tmp_path, capsys, text) == []
    registries.records["10.5555/given.1"] = ("Mitochondrial dynamics in budding yeast", "")
    assert len(_differs(tmp_path, capsys, text)) == 1


@pytest.mark.parametrize("marker", ["[Article in Spanish]", "(in Portuguese)",
                                    "(in Japanese with English abstract)",
                                    "[Article in German, French]", "(in Estonian)",
                                    "[Article in English, Portuguese]"])  # fmt: skip
def test_an_entry_that_says_its_title_is_a_translation_is_not_compared(
    tmp_path: Path, capsys, registries: Registries, marker: str
) -> None:
    """A registry holds the title in the language the work was written in, which shares no
    words with its translation: PubMed marks it "[Article in Spanish]" (2026-11-27)."""
    registries.records["10.5555/given.1"] = ("Normativa sobre la utilización de fármacos", "")
    assert _differs(tmp_path, capsys, _paper(f"{GIVEN} {marker}")) == []
    assert len(_differs(tmp_path, capsys, _paper(f"{GIVEN} (in press)"))) == 1
    assert len(_differs(tmp_path, capsys, _paper(f"{GIVEN} (in English)"))) == 1


@pytest.mark.parametrize("record", [
    (GIVEN, ""),                                                     # the same
    ("WEEKLY OUTCOME COUNTS", "in a regional cohort of older adults"),  # title and subtitle
    ("Weekly outcome counts in a regional cohort of older adults: a cohort study", ""),
    ("Weekly outcome counts in a regional cohort", ""),             # cut short
    ("Wöchentliche outcome counts in regional cohort of older adults", ""),  # half and more
], ids=["same", "subtitle", "longer", "cut", "half"])  # fmt: skip
def test_a_title_the_record_holds_most_of_is_not_said(
    tmp_path: Path, capsys, registries: Registries, record: tuple[str, str]
) -> None:
    registries.records["10.5555/given.1"] = record
    assert _differs(tmp_path, capsys, _paper()) == []


@pytest.mark.parametrize("given", [
    "Plant 8 (6) (2015) 871-884, https://doi.org/10.5555/given.1",
    "Available from: https://doi.org/10.5555/GIVEN.1",
    "J Exp Med (1996) 184:1845-56",
    "Bull World Health Organ (2006) 84:673-6",
], ids=["volume-and-link", "available-from", "year-volume-pages", "journal-tail"])  # fmt: skip
def test_a_title_read_as_the_journal_s_part_or_a_link_is_not_compared(
    tmp_path: Path, capsys, registries: Registries, given: str
) -> None:
    """On 100 PMC papers (2026-11-27) the entry's reader took a journal's volume and pages,
    or a link, for the title of 10 entries in one style, and each was said to differ: a
    title that holds a link or a DOI, or a year in brackets with a volume and pages, is the
    citation's tail read wrong, never a title."""
    registries.records["10.5555/given.1"] = ("Mitochondrial dynamics in yeast", "")
    text = (f"# Results\n\nIt rose [1].\n\n# References\n\n1. Smith A, Lee B. {given}. "
            "doi:10.5555/given.1\n")  # fmt: skip
    assert _differs(tmp_path, capsys, text) == []


def test_a_record_title_whose_markup_runs_words_together_is_read_word_by_word(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    """Crossref keeps "Recombinant<i>Mycobacterium bovis</i>BCG": the tags taken out with no
    space ran its words together, and the title was said to differ (2026-11-27)."""
    given = "Recombinant Mycobacterium bovis BCG expressing the Sm14 antigen of Schistosoma"
    registries.records["10.5555/given.1"] = (
        "Recombinant<i>Mycobacterium bovis</i>BCG Expressing the Sm14 Antigen of"
        "<i>Schistosoma mansoni</i>Protects Mice", "")
    assert _differs(tmp_path, capsys, _paper(given)) == []


def test_a_title_of_too_few_searched_words_is_not_compared(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    registries.records["10.5555/given.1"] = ("Mitochondrial dynamics in yeast", "")
    assert _differs(tmp_path, capsys, _paper("Osteoporosis")) == []


def test_a_doi_no_registry_knows_is_not_said_to_be_of_another_work(
    tmp_path: Path, capsys, registries: Registries
) -> None:
    assert _differs(tmp_path, capsys, _paper()) == []


def test_without_lookup_nothing_is_compared(tmp_path: Path, capsys, registries: Registries) -> None:
    registries.records["10.5555/given.1"] = ("Mitochondrial dynamics in yeast", "")
    paper = tmp_path / "paper.md"
    paper.write_text(_paper(), encoding="utf-8")
    main(["audit", str(paper), "--json"])
    said = json.loads(capsys.readouterr().out)["findings"]
    assert not [f for f in said if f["code"] == "reference-title-differs"]


def test_the_editor_s_report_asks_it_of_the_authors_with_its_record() -> None:
    """Under "Ask the authors", beside the DOIs no registry knows, its 1 of 6 shown as too few
    to rate (Basile, 2026-11-27); the letter asks it."""
    from manuscript_guard.auditing import editor, letter

    (kind,) = [kind for kind in editor.KINDS if ("G7", "reference-title-differs") in kind.codes]
    assert kind.part == editor.ASK and kind.record == (1, 6)
    assert editor.record_said(kind) == ("Right in 1 of 6 judged on published papers: too few "
                                        "to rate it.")  # fmt: skip
    assert "translation" in letter.sentences().kinds[kind.name]
