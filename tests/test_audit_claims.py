"""`audit` for a reader who did not write the paper, part 2: what is claimed and what is cited.

`--design observational` warns of a causal word where the paper sums up (decision 6),
`--cited FILE` lists each citation beside its sentence, with the work's abstract from Europe
PMC under `--lookup` (decision 7), and with `--journal`, `--authors` and `--lookup` the
references of the authors and of the journal are counted. None of it is counted by `--strict`
(decision 8). The registries are asked only on a loopback port here, and nowhere else.
"""

from __future__ import annotations

import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from manuscript_guard.auditing import NOTICE, READER_FLAGS
from manuscript_guard.auditing.cited import YOURS
from manuscript_guard.auditing.selfcite import NOT_LOOKED_UP, folded_title
from manuscript_guard.cli import main
from manuscript_guard.lookup import run as lookup
from manuscript_guard.lookup import search
from manuscript_guard.lookup.http import NoAnswer, Request, default_transport
from manuscript_guard.text.section_names import names_discussion

BS = chr(92)
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

PAPER = (
    "# A cohort of smokers\n\n"
    "## Abstract\n\n"
    "Smoking causes lung cancer in this cohort. It may cause harm too.\n\n"
    "## Methods\n\n"
    "We drew a causal diagram of 40 patients.\n\n"
    "## Results\n\n"
    "Of 40 patients, 12 (30%) had cancer [1].\n\n"
    "## Discussion\n\n"
    "Statins caused fewer deaths. Exercise causes health [2]. We cannot prove that it works.\n"
    "Coffee causes alertness. [1, 2] The rate was stable.\n"
    "Tea causes calm (Smith et al., 2019).\n\n"
    "## References\n\n"
    "1. Smith J. A cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1\n"
    "2. Jones K. A trial. BMJ 2020;370:m1. PMID: 31000001\n"
)


def paper_md(tmp_path: Path, text: str = PAPER, name: str = "paper.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def audited(capsys, *argv: str) -> tuple[int, dict, str]:
    code = main(["audit", *argv, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def section(report: dict, name: str) -> list[dict]:
    return [f for f in report["findings"] if f["section"] == name]


@pytest.mark.parametrize(
    ("title", "named"),
    [("Discussion", True), ("4. Discussion", True), ("**General discussion**", True),
     ("Discussion and conclusions", True), ("Results and discussion", True),
     ("Methods for discussion groups", False), ("Conclusions", False)],
)  # fmt: skip
def test_a_discussion_is_named_by_the_words_its_title_opens_with(title: str, named: bool) -> None:
    assert names_discussion(title) is named


def test_the_new_options_are_reader_options() -> None:
    assert {"--design", "--cited"} <= set(READER_FLAGS)


# ------------------------------------------------------------------------ causal words


def test_a_causal_word_where_the_paper_sums_up_is_a_warning_and_not_counted(
    tmp_path: Path, capsys
) -> None:
    """Decision 6: the Abstract's and the Discussion's unhedged, unnegated and uncited
    causal claims are said; the Methods' causal diagram, a hedge, a negation and a citation
    (inside the stop, after it, by author and year) are not. `--strict` counts none."""
    code, report, err = audited(capsys, str(paper_md(tmp_path)), "--design", "observational",
                                "--strict")  # fmt: skip
    assert code == 0 and report["ok"]
    assert NOTICE in err
    found = section(report, "Causal words")
    assert [(f["code"], f["line"], f["context"]) for f in found] == [
        ("causal-word-observational", 5, "Smoking causes lung cancer in this cohort."),
        ("causal-word-observational", 17, "Statins caused fewer deaths."),
    ]
    assert all(not f["counted"] and f["severity"] == "warn" for f in found)
    assert "'causes' in the Abstract" in found[0]["message"]
    assert report["counts"]["causal_words"] == 2


def test_the_text_report_says_what_it_read_and_passed_over(tmp_path: Path, capsys) -> None:
    assert main(["audit", str(paper_md(tmp_path)), "--design", "observational"]) == 0
    out = capsys.readouterr().out
    assert "=== Causal words (--design observational; not counted by --strict) ===" in out
    assert "with a causal word passed over: 1 hedged, 1 negated, 3 cited" in out


def test_a_file_with_no_heading_that_names_a_part_is_said_to_be_unread(
    tmp_path: Path, capsys
) -> None:
    paper = paper_md(tmp_path, "Smoking causes lung cancer in 40 patients.\n")
    _code, report, _err = audited(capsys, str(paper), "--design", "observational")
    assert [f["code"] for f in section(report, "Causal words")] == ["causal-words-not-read"]


def make_docx(path: Path, paragraphs: list[tuple[str, bool]]) -> Path:
    """A .docx of paragraphs, each styled as a heading where its flag says so."""
    styles = (f"<w:styles xmlns:w='{W}'><w:style w:type='paragraph' w:styleId='Heading1'>"
              "<w:name w:val='heading 1'/></w:style></w:styles>")  # fmt: skip
    body = "".join(
        "<w:p>" + ("<w:pPr><w:pStyle w:val='Heading1'/></w:pPr>" if heading else "")
        + f"<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"
        for text, heading in paragraphs
    )
    document = (f"<?xml version='1.0'?><w:document xmlns:w='{W}'><w:body>{body}</w:body>"
                "</w:document>")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("word/document.xml", (2020, 1, 1, 0, 0, 0)), document)
        archive.writestr(zipfile.ZipInfo("word/styles.xml", (2020, 1, 1, 0, 0, 0)), styles)
    return path


DOCX = [
    ("Abstract", True), ("Smoking causes lung cancer in 40 patients", False),
    ("Methods", True), ("We drew a causal diagram.", False),
    ("Discussion", True), ("Statins caused fewer deaths", False),
    ("Exercise causes health [1].", False), ("[2] Coffee may cause alertness.", False),
    ("References", True),
    ("[1] Smith J. A cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1", False),
    ("[2] Jones K. A trial. BMJ 2020;370:m1. PMID: 31000001", False),
]


def test_a_word_document_is_read_a_paragraph_a_sentence_by_its_heading_styles(
    tmp_path: Path, capsys
) -> None:
    """A paragraph with no stop ends its sentence, and a citation opening a paragraph is
    that paragraph's: Word's paragraphs are blocks of their own."""
    paper = make_docx(tmp_path / "paper.docx", DOCX)
    table = tmp_path / "cited.md"
    _code, report, _err = audited(capsys, str(paper), "--design", "observational",
                                  "--cited", str(table))  # fmt: skip
    found = section(report, "Causal words")
    assert [(f["line"], f["context"]) for f in found] == [
        (3, "Smoking causes lung cancer in 40 patients"), (7, "Statins caused fewer deaths")]
    written = table.read_text(encoding="utf-8")
    assert "| 1 | paper.docx:8 | Discussion | Exercise causes health [1]. | [1] |" in written
    assert "| 2 | paper.docx:9 | Discussion | [2] Coffee may cause alertness. | [2] |" in written


# --------------------------------------------------------------------- cited sentences


def test_the_cited_sentences_are_written_to_the_file_and_counted_on_stdout(
    tmp_path: Path, capsys
) -> None:
    """Decision 7: a row for each work each citation names, beside its sentence; a
    citation after the stop belongs to the sentence before it; the last column is empty;
    what is not read is said in the file; stdout gives counts and quotes no sentence."""
    table = tmp_path / "cited.md"
    assert main(["audit", str(paper_md(tmp_path)), "--cited", str(table)]) == 0
    captured = capsys.readouterr()
    assert NOTICE in captured.err
    assert "Coffee causes alertness" not in captured.out
    assert ("4 rows, one for each work a citation names, in 3 sentences; 4 with its entry of "
            "the reference list, 0 with none; written to") in captured.out
    written = table.read_text(encoding="utf-8")
    assert "This file quotes the manuscript" in written
    assert "a citation by author and year" in written and "Word's citation fields" in written
    assert f"| {YOURS} |" in written
    rows = [line for line in written.splitlines() if line.startswith("| ") and "|---" not in line]
    assert rows[1:] == [
        "| 1 | paper.md:13 | Results | Of 40 patients, 12 (30%) had cancer [1]. | [1] | entry 1: "
        "1. Smith J. A cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1 "
        "[doi:10.5555/fictional.1] |  |",
        "| 2 | paper.md:17 | Discussion | Exercise causes health [2]. | [2] | entry 2: 2. Jones "
        "K. A trial. BMJ 2020;370:m1. PMID: 31000001 [PMID 31000001] |  |",
        "| 3 | paper.md:18 | Discussion | Coffee causes alertness. | [1, 2] | entry 1: 1. Smith "
        "J. A cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1 "
        "[doi:10.5555/fictional.1] |  |",
        "| 4 | paper.md:18 | Discussion | Coffee causes alertness. | [1, 2] | entry 2: 2. Jones "
        "K. A trial. BMJ 2020;370:m1. PMID: 31000001 [PMID 31000001] |  |",
    ]


def test_the_html_table_escapes_what_it_quotes(tmp_path: Path, capsys) -> None:
    text = PAPER.replace("Exercise causes health [2].", "Exercise <b>causes</b> health [2].")
    table = tmp_path / "cited.html"
    assert main(["audit", str(paper_md(tmp_path, text)), "--cited", str(table)]) == 0
    written = table.read_text(encoding="utf-8")
    assert written.startswith("<!doctype html>")
    assert "Exercise &lt;b&gt;causes&lt;/b&gt; health [2]." in written
    assert f"<th>{YOURS}</th>" in written


@pytest.mark.parametrize(
    ("name", "said"),
    [("cited.txt", "writes Markdown (.md) or HTML (.html)"),
     ("there.md", "the file is there already"),
     ("absent/cited.md", "its folder does not exist"),
     ("paper.md", "the file is there already")],
)  # fmt: skip
def test_the_cited_file_is_refused_where_it_cannot_be_written(
    tmp_path: Path, capsys, name: str, said: str
) -> None:
    """A file already there may hold a referee's judgements, and is not written over."""
    paper = paper_md(tmp_path)
    (tmp_path / "there.md").write_text("my judgements\n", encoding="utf-8")
    code, report, _err = audited(capsys, str(paper), "--cited", str(tmp_path / name))
    assert code == 2 and said in report["error"]
    assert (tmp_path / "there.md").read_text(encoding="utf-8") == "my judgements\n"


def test_a_latex_cite_is_listed_and_a_bib_list_is_said_unread(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(
        f"{BS}documentclass{{article}}\n{BS}begin{{document}}\n{BS}section{{Discussion}}\n"
        f"Statins caused fewer deaths~{BS}cite{{smith}}.\n{BS}bibliography{{refs}}\n"
        f"{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    table = tmp_path / "cited.md"
    assert main(["audit", str(paper), "--cited", str(table)]) == 0
    capsys.readouterr()
    written = table.read_text(encoding="utf-8")
    assert (f"| 1 | paper.tex:4 | Discussion | Statins caused fewer deaths~{BS}{BS}cite{{smith}}"
            f". | {BS}{BS}cite{{smith}} | smith: the list BibTeX or biber makes from a .bib is not "
            "read, so the entry is not shown |  |") in written


def test_numbers_in_brackets_beside_an_unnumbered_list_are_said_not_listed(
    tmp_path: Path, capsys
) -> None:
    text = PAPER.replace("1. Smith J.", "Smith J.").replace("2. Jones K.", "Jones K.")
    table = tmp_path / "cited.md"
    _code, report, _err = audited(capsys, str(paper_md(tmp_path, text)), "--cited", str(table))
    notes = [f["message"] for f in section(report, "Cited sentences")
             if f["code"] == "cited-not-listed"]  # fmt: skip
    assert notes == ["3 numbers in brackets not listed: the reference list does not number its "
                     "entries, so a number in brackets is not read as a citation"]
    assert "No citation was read." in table.read_text(encoding="utf-8")


# ------------------------------------------------------------- the registries, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        self.server.seen.append(self.path)
        name = self.path.strip("/").split("/")[0].split("?")[0]
        answer = self.server.answers.get(name, (404, {}))
        status, data = answer(self.path) if callable(answer) else answer
        payload = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


DOI = "10.5555/fictional.1"
PACER = lookup.Pacer
ABSTRACT = "<h4>Background</h4>Smoking was common.<h4>Results</h4>It rose &amp; fell."


def _europepmc(path: str) -> tuple[int, dict]:
    """Europe PMC's search, by the identifier asked: a work of the DOI, and of the PMID."""
    query = parse_qs(urlsplit(path).query)["query"][0]
    if DOI in query:
        item = {"id": "1", "source": "MED", "doi": DOI, "title": "A cohort.",
                "pubYear": "2019", "abstractText": ABSTRACT}  # fmt: skip
    else:
        item = {"id": "31000001", "source": "MED", "pmid": "31000001", "title": "A trial."}
    return 200, {"hitCount": 1, "resultList": {"result": [item]}}


CROSSREF = {
    "status": "ok", "message-type": "work",
    "message": {"DOI": DOI, "type": "journal-article", "title": ["A cohort"],
                "container-title": ["The Journal of Examples"],
                "issued": {"date-parts": [[2019, 3]]},
                "author": [{"family": "Example", "given": "Ada"},
                           {"family": "Example", "given": "Bob"},
                           {"family": "Berg", "given": "M. A."}]},
}  # fmt: skip


@pytest.fixture
def registries(monkeypatch: pytest.MonkeyPatch):
    """A loopback server standing in for Crossref, OpenAlex, PubMed and Europe PMC."""
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []
    httpd.answers = {
        "crossref": (200, CROSSREF),
        "openalex": (200, {"id": "W1", "is_retracted": False, "title": "A cohort"}),
        "pubmed": (200, {"header": {"type": "esummary"}, "result": {"uids": ["31000001"],
                   "31000001": {"uid": "31000001", "title": "A trial.", "sortpubdate":
                                "2020/01/01 00:00", "fulljournalname": "BMJ", "authors": [
                                    {"name": "Jones K", "authtype": "Author"}],
                                "pubtype": ["Journal Article"], "articleids": []}}}),
        "europepmc": _europepmc,
    }  # fmt: skip
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        default_transport(Request(url + "/probe"), 5)
    except NoAnswer as exc:  # pragma: no cover - depends on the machine
        httpd.shutdown()
        pytest.skip(f"loopback connections are not allowed here: {exc}")
    httpd.seen.clear()
    services = lookup.Services(crossref=f"{url}/crossref/", openalex=f"{url}/openalex/doi:",
                               datacite=f"{url}/datacite/", doi_org=f"{url}/doi_org/",
                               pubmed=f"{url}/pubmed/esummary.fcgi")  # fmt: skip
    monkeypatch.setattr(lookup, "Services", lambda: services)
    found = search.Services(europepmc=f"{url}/europepmc/search")
    monkeypatch.setattr(search, "Services", lambda: found)
    monkeypatch.setattr(lookup, "Pacer", lambda: PACER(sleep=lambda seconds: None))
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _asked_of_europepmc(seen: list[str]) -> list[str]:
    return [parse_qs(urlsplit(path).query)["query"][0] for path in seen
            if path.startswith("/europepmc/")]  # fmt: skip


def test_with_lookup_each_cited_work_gains_its_title_standing_and_abstract(
    tmp_path: Path, registries, capsys
) -> None:
    """Decision 7: Europe PMC is asked once for each work a row names, by its PMID, else
    its DOI, and sent nothing else; the abstract is shown without its markup."""
    table = tmp_path / "cited.md"
    assert main(["audit", str(paper_md(tmp_path)), "--cited", str(table), "--lookup"]) == 0
    out = capsys.readouterr().out
    assert sorted(_asked_of_europepmc(registries.seen)) == [f'DOI:"{DOI}"',
                                                            "EXT_ID:31000001 AND SRC:MED"]
    assert "Europe PMC asked of 2 works, 1 with an abstract" in out
    written = table.read_text(encoding="utf-8")
    assert "| Registry title | Year | Standing | Abstract (Europe PMC) |" in written
    assert ("| A cohort | 2019 | no registry said it was retracted, withdrawn or under "
            "concern | Background Smoking was common. Results It rose & fell. |  |") in written
    assert "Europe PMC holds the work and no abstract" in written
    assert not list(tmp_path.rglob("europepmc__*.json")), "nothing is kept without a cache"


def test_a_dry_run_lists_what_europe_pmc_would_be_asked_and_sends_nothing(
    tmp_path: Path, registries, capsys
) -> None:
    table = tmp_path / "cited.md"
    assert main(["audit", str(paper_md(tmp_path)), "--cited", str(table), "--lookup",
                 "--dry-run"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert registries.seen == []
    assert f"would ask Europe PMC for doi:{DOI} (entry 1)" in out
    assert "would ask Europe PMC for PMID 31000001 (entry 2)" in out


def test_an_abstract_is_kept_only_in_the_cache_and_read_from_it(
    tmp_path: Path, registries, capsys
) -> None:
    paper = paper_md(tmp_path)
    cache = tmp_path / "kept"
    argv = ["audit", str(paper), "--lookup", "--lookup-cache", str(cache)]
    assert main([*argv, "--cited", str(tmp_path / "one.md")]) == 0
    assert sorted(p.name for p in cache.glob("europepmc__*")) == [
        "europepmc__doi_10.5555_fictional.1.json", "europepmc__pmid_31000001.json"]
    asked = len(registries.seen)
    assert main([*argv, "--cited", str(tmp_path / "two.md")]) == 0
    capsys.readouterr()
    assert len(registries.seen) == asked, "a kept answer is read, not asked for again"
    assert "It rose & fell." in (tmp_path / "two.md").read_text(encoding="utf-8")


def test_europe_pmc_s_work_under_another_identifier_is_none(registries) -> None:
    from manuscript_guard.lookup.run import Credentials, _asker

    ask = _asker(default_transport, PACER(sleep=lambda seconds: None), Credentials())
    services = search.Services()
    assert search.europepmc_work(DOI, None, ask, services)["abstract"].startswith("Background ")
    assert search.europepmc_work("10.5555/other", None, ask, services) == {"status": "absent"}
    registries.answers["europepmc"] = (500, {})
    assert search.europepmc_work(DOI, None, ask, services)["status"] == "unresolvable"
    registries.answers["europepmc"] = (200, {"hitCount": 0, "resultList": {"result": []}})
    assert search.europepmc_work(DOI, None, ask, services) == {"status": "absent"}


# -------------------------------------------------------------------------- self-citation


def profile(tmp_path: Path) -> Path:
    path = tmp_path / "journal.yaml"
    path.write_text("schema: manuscript-guard/journal/1\nname: Journal of Examples\n"
                    "source_url: https://example.org/authors\nretrieved_on: 2026-10-01\n",
                    encoding="utf-8")  # fmt: skip
    return path


def authors(tmp_path: Path) -> Path:
    path = tmp_path / "authors.yaml"
    path.write_text("authors:\n  - given: Ada\n    family: Example\n"
                    "  - given: Carl\n    family: van der Berg\n"
                    "  - given: Kim\n    family: Jones\n", encoding="utf-8")  # fmt: skip
    return path


def test_the_references_of_each_author_and_of_the_journal_are_counted(
    tmp_path: Path, registries, capsys
) -> None:
    """A family name folded as G7 folds one and the first initial: "Example, Ada" is Ada
    Example and so, since only initials are held, is a namesake; "Berg, M. A." is not Carl
    van der Berg. The journal by its folded name: "The Journal of Examples" is "Journal of
    Examples". Counts and the entries, never a ratio, and none counted by --strict."""
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                  str(profile(tmp_path)), "--authors", str(authors(tmp_path)),
                                  "--lookup")  # fmt: skip
    said = [(f["code"], f["message"]) for f in section(report, "Self-citation")]
    assert said == [
        ("self-citation-read", "2 entries looked up, 0 of them with no author list from a "
         "registry and 0 with no journal; 0 not looked up, having no DOI or PMID, and not "
         "counted"),
        ("self-citation-author", "Ada Example: 1 reference (entry 1), whose registry record "
         "lists an author of that family name and first initial"),
        ("self-citation-author", "Carl van der Berg: 0 references, whose registry record "
         "lists an author of that family name and first initial"),
        ("self-citation-author", "Kim Jones: 1 reference (entry 2), whose registry record "
         "lists an author of that family name and first initial"),
        ("self-citation-journal", "Journal of Examples: 1 reference (entry 1), published in "
         "it by what the registries say"),
    ]
    assert not any(f["counted"] for f in section(report, "Self-citation"))
    assert report["counts"]["self_citation_journal"] == 1


def test_without_lookup_nothing_is_counted_and_the_reference_text_is_not_read(
    tmp_path: Path, capsys
) -> None:
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                  str(profile(tmp_path)), "--authors", str(authors(tmp_path)))
    assert [f["message"] for f in section(report, "Self-citation")] == [NOT_LOOKED_UP]


def test_a_dry_run_counts_nothing(tmp_path: Path, registries, capsys) -> None:
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal",
                                  str(profile(tmp_path)), "--authors", str(authors(tmp_path)),
                                  "--lookup", "--dry-run")  # fmt: skip
    assert registries.seen == []
    assert [f["code"] for f in section(report, "Self-citation")] == ["self-citation-not-counted"]


@pytest.mark.parametrize(
    ("one", "other"),
    [("The Journal of Examples", "journal of examples"), ("J. Exámples & Co", "j examples and co")],
)  # fmt: skip
def test_a_journal_s_name_is_folded(one: str, other: str) -> None:
    assert folded_title(one) == folded_title(other)
