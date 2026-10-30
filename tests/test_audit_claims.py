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


def make_docx(path: Path, paragraphs: list[tuple[str, bool | int]]) -> Path:
    """A .docx of paragraphs, each styled as a heading where its flag says so, of level 1, or
    of the level it gives."""
    styles = (f"<w:styles xmlns:w='{W}'>" + "".join(
        f"<w:style w:type='paragraph' w:styleId='Heading{n}'><w:name w:val='heading {n}'/>"
        "</w:style>" for n in (1, 2)) + "</w:styles>")  # fmt: skip
    body = "".join(
        "<w:p>" + (f"<w:pPr><w:pStyle w:val='Heading{int(heading)}'/></w:pPr>" if heading
                   else "")  # fmt: skip
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


def _causal(capsys, paper: Path) -> list[tuple[int, str]]:
    _code, report, _err = audited(capsys, str(paper), "--design", "observational")
    return [(f["line"], f["message"].split(" in the ")[1].split(",")[0])
            for f in section(report, "Causal words") if f["code"] == "causal-word-observational"]


@pytest.mark.parametrize("title", ["Abstract", "Summary"])
@pytest.mark.parametrize("background", [True, False])
def test_every_heading_of_a_structured_abstract_is_the_abstract_s(
    tmp_path: Path, capsys, title: str, background: bool
) -> None:
    """Round 1 of #482: an Abstract with a Background heading under it was taken for a title
    over the paper, and its Results were then the Results, not read; the Lancet's "Summary"
    was a conclusion. Every heading under the Abstract is the Abstract's."""
    text = (f"# A cohort\n\n## {title}\n\n" + ("### Background\n\n" if background else "")
            + "Smoking causes cancer.\n\n### Methods\n\nWe drew a causal diagram.\n\n"
            "### Findings\n\nStatins caused fewer deaths.\n\n### Interpretation\n\n"
            "Coffee causes alertness.\n\n## Methods\n\nWe drew a causal diagram.\n\n"
            "## Summary\n\nTea causes calm.\n")  # fmt: skip
    found = _causal(capsys, paper_md(tmp_path, text))
    first = 7 if background else 5
    assert found == [(first, "Abstract"), (first + 4, "Abstract"), (first + 8, "Abstract"),
                     (first + 12, "Abstract"), (first + 20, "Conclusion")]  # fmt: skip


@pytest.mark.parametrize(
    "marker", ["[3]", "[3,4]", "[3-5]", "[3, 4]"],
)
def test_a_citation_directly_after_a_stop_ends_the_sentence_it_cites_for(
    tmp_path: Path, capsys, marker: str
) -> None:
    """Round 1 of #482: `.[3]` was read on into the sentence after, which then passed as
    cited."""
    text = (f"## Discussion\n\nStatins caused fewer deaths.{marker} Coffee causes alertness.\n\n"
            "## References\n\n" + "".join(f"{n}. Author{n} A. A study. J. 2019;1:1-2.\n"
                                          for n in range(1, 6)))  # fmt: skip
    paper = paper_md(tmp_path, text)
    assert _causal(capsys, paper) == [(3, "Discussion")]
    table = tmp_path / "cited.md"
    assert main(["audit", str(paper), "--cited", str(table)]) == 0
    capsys.readouterr()
    assert (f"| 1 | paper.md:3 | Discussion | Statins caused fewer deaths.{marker} | {marker} |"
            in table.read_text(encoding="utf-8"))


@pytest.mark.parametrize("tie", ["", "~"])
def test_a_latex_cite_directly_after_a_stop_ends_the_sentence(
    tmp_path: Path, capsys, tie: str
) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(
        f"{BS}documentclass{{article}}\n{BS}begin{{document}}\n{BS}section{{Discussion}}\n"
        f"Statins caused fewer deaths.{tie}{BS}cite{{a}} Coffee causes alertness.\n"
        f"{BS}begin{{thebibliography}}{{9}}\n{BS}bibitem{{a}} A.\n{BS}end{{thebibliography}}\n"
        f"{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    _code, report, _err = audited(capsys, str(paper), "--design", "observational")
    assert [f["context"] for f in section(report, "Causal words")] == [
        "Coffee causes alertness."]


@pytest.mark.parametrize(
    ("front", "said"),
    [("abstract: Smoking causes cancer. It may harm [1].\n", "Abstract"),
     ("abstract: |\n  Smoking causes cancer.\n  It may harm [1].\n", "Abstract"),
     ("abstract:\n  - Smoking causes cancer [1].\n", None)],
    ids=["one line", "a block", "a list"],
)  # fmt: skip
def test_an_abstract_in_the_front_matter_is_read_as_the_abstract(
    tmp_path: Path, capsys, front: str, said: str | None
) -> None:
    """Round 1 of #482: a Markdown abstract in the YAML header was placed under no heading
    and never read. A plain string is read as the Abstract, at its key's line; any other
    value is said not to be read."""
    text = (f"---\ntitle: A cohort\n{front}---\n\n# Methods\n\nWe drew a causal diagram.\n\n"
            "# References\n\n1. Smith J. A cohort. Lancet. 2019;393:100-10.\n")  # fmt: skip
    paper = paper_md(tmp_path, text)
    table = tmp_path / "cited.md"
    _code, report, _err = audited(capsys, str(paper), "--design", "observational",
                                  "--cited", str(table))  # fmt: skip
    found = section(report, "Causal words")
    if said is None:
        assert {f["code"] for f in found} == {"causal-words-not-read"}
        assert any("front matter's abstract is a list or a mapping" in f["message"]
                   for f in found)
        assert "| 1 |" not in table.read_text(encoding="utf-8")
        return
    assert [(f["line"], f["context"]) for f in found] == [(3, "Smoking causes cancer.")]
    assert "| 1 | paper.md:3 | Abstract | It may harm [1]. | [1] |" in (
        table.read_text(encoding="utf-8"))


def test_a_file_that_appears_before_the_table_is_written_is_not_written_over(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The table is written only where no file is: one made after the check, between the
    audit's start and its end, is refused, exit 2."""
    from manuscript_guard import cli

    table = tmp_path / "cited.md"
    table.write_text("my judgements\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_cited_refused", lambda target, given: "")
    code = main(["audit", str(paper_md(tmp_path)), "--cited", str(table)])
    assert code == 2 and "is there already" in capsys.readouterr().err
    assert table.read_text(encoding="utf-8") == "my judgements\n"


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


def test_pubmed_s_qualifier_after_a_journal_s_name_is_no_part_of_it(
    tmp_path: Path, registries, capsys
) -> None:
    """Round 1 of #482: PubMed's full name is "BMJ (Clinical research ed.)", and the BMJ's
    own papers were not counted."""
    path = profile(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("Journal of Examples", "BMJ"),
                    encoding="utf-8")  # fmt: skip
    answer = registries.answers["pubmed"][1]
    answer["result"]["31000001"]["fulljournalname"] = "BMJ (Clinical research ed.)"
    _code, report, _err = audited(capsys, str(paper_md(tmp_path)), "--journal", str(path),
                                  "--lookup")  # fmt: skip
    assert report["counts"]["self_citation_journal"] == 1
    assert folded_title("BMJ (Clinical research ed.)") == folded_title("BMJ")
    assert folded_title("Science (New York, N.Y.)") == "science"


@pytest.mark.parametrize(
    ("given", "read"),
    [("P<0.05 and age>65 in the cohort", "P<0.05 and age>65 in the cohort"),
     ("P&lt;0.05 and age&gt;65", "P<0.05 and age>65"),
     ("<h4>Background</h4>Smoking <i>in vivo</i> rose<sup>2</sup>.<br/>It fell",
      "Background Smoking in vivo rose^2. It fell"),
     ("<p class='x'>A <span style=\"color:red\">red</span> word.</p>", "A red word."),
     ("A < B and C > D", "A < B and C > D")],
)  # fmt: skip
def test_an_abstract_loses_its_markup_and_keeps_its_signs(given: str, read: str) -> None:
    """Round 1 of #482: every `<...>` was taken for a tag, and "P<0.05 and age>65" lost the
    words between its signs."""
    assert search._abstract(given) == read


# ------------------------------------------------------------------- round 2 of #482


REFERENCES = "## References\n\n" + "".join(f"{n}. Author{n} A. A study. J. 2019;1:1-2.\n"
                                            for n in range(1, 9))  # fmt: skip


def _rows(capsys, tmp_path: Path, *papers: Path) -> list[str]:
    table = tmp_path / "cited.md"
    if table.exists():
        table.unlink()
    assert main(["audit", *map(str, papers), "--cited", str(table)]) == 0
    capsys.readouterr()
    return [line for line in table.read_text(encoding="utf-8").splitlines()
            if line.startswith("| ") and not line.startswith("| #")]  # fmt: skip


def test_a_citation_after_an_abbreviation_s_stop_stays_in_its_sentence(
    tmp_path: Path, capsys
) -> None:
    """Round 2 of #482: "Smith et al. [3] showed that X causes Y" gave [3] to "Smith et
    al." and warned of the rest as uncited."""
    text = ("## Discussion\n\nSmith et al. [3] showed that smoking causes cancer.\n"
            "Earlier cohorts, e.g. [4], showed that tea causes calm.\n"
            "Others (cf. [5]) found that coffee causes alertness.\n"
            "As in Fig. [6] statins caused fewer deaths.\n\n" + REFERENCES)  # fmt: skip
    paper = paper_md(tmp_path, text)
    assert _causal(capsys, paper) == []
    rows = _rows(capsys, tmp_path, paper)
    assert [row.split(" | ")[3] for row in rows] == [
        "Smith et al. [3] showed that smoking causes cancer.",
        "Earlier cohorts, e.g. [4], showed that tea causes calm.",
        "Others (cf. [5]) found that coffee causes alertness.",
        "As in Fig. [6] statins caused fewer deaths.",
    ]


@pytest.mark.parametrize("tie", [" ", "~", ""])
def test_a_latex_cite_after_et_al_stays_in_its_sentence(tmp_path: Path, capsys, tie: str) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(
        f"{BS}documentclass{{article}}\n{BS}begin{{document}}\n{BS}section{{Discussion}}\n"
        f"Smith et al.{tie}{BS}cite{{a}} showed that smoking causes cancer.\n"
        f"{BS}begin{{thebibliography}}{{9}}\n{BS}bibitem{{a}} A.\n{BS}end{{thebibliography}}\n"
        f"{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    _code, report, _err = audited(capsys, str(paper), "--design", "observational")
    assert section(report, "Causal words") == []


@pytest.mark.parametrize(
    ("given", "read"),
    [("10<sup>9</sup> cells and 10<sup>-8</sup> M", "10^9 cells and 10^-8 M"),
     ("CO<sub>2</sub> <i>in vivo</i>", "CO_2 in vivo")],
)  # fmt: skip
def test_a_superscript_and_a_subscript_keep_what_they_mean(given: str, read: str) -> None:
    """Round 2 of #482: "10<sup>9</sup>" read as "109"."""
    assert search._abstract(given) == read


@pytest.mark.parametrize(
    "heading",
    ["### Causes of death\n", "Causes of death\n---------------\n"],
    ids=["atx", "setext"],
)
def test_a_heading_is_no_sentence_of_its_part(tmp_path: Path, capsys, heading: str) -> None:
    text = (f"## Discussion\n\n{heading}\nTea was common.\n\n" + REFERENCES)
    assert _causal(capsys, paper_md(tmp_path, text)) == []


def test_a_latex_or_word_heading_is_no_sentence_of_its_part(tmp_path: Path, capsys) -> None:
    paper = tmp_path / "paper.tex"
    paper.write_text(
        f"{BS}documentclass{{article}}\n{BS}begin{{document}}\n{BS}section{{Discussion}}\n"
        f"{BS}subsection{{Causes of death}}\nTea was common.\n{BS}end{{document}}\n",
        encoding="utf-8")  # fmt: skip
    assert _causal(capsys, paper) == []
    docx = make_docx(tmp_path / "paper.docx", [("Discussion", True), ("Causes of death", 2),
                                                ("Tea was common.", False)])
    assert _causal(capsys, docx) == []


@pytest.mark.parametrize(("run", "warned"), [("[3] [4] Coffee", True), ("[3]~[4] Coffee", True),
                                              ("[3] [4] and coffee", False)])  # fmt: skip
def test_markers_typed_together_after_a_stop_are_one_run(
    tmp_path: Path, capsys, run: str, warned: bool
) -> None:
    text = (f"## Discussion\n\nStatins caused fewer deaths.{run} causes alertness.\n\n"
            + REFERENCES)
    found = _causal(capsys, paper_md(tmp_path, text))
    assert found == ([(3, "Discussion")] if warned else [])


def test_an_entry_is_known_by_its_file_as_well(tmp_path: Path, registries, capsys) -> None:
    """Round 2 of #482: entry 1 of two files, at one line in each, was one entry."""
    main_text = ("## Discussion\n\nSmoking was common [1].\n\n## References\n\n"
                 f"1. Smith J. A cohort. Lancet. 2019;393:100-10. doi:{DOI}\n")
    supplement = ("## Discussion\n\nDiet was common [1].\n\n## References\n\n"
                  "1. Jones K. A trial. BMJ 2020;370:m1. PMID: 31000001\n")
    papers = [paper_md(tmp_path, main_text), paper_md(tmp_path, supplement, "supplement.md")]
    table = tmp_path / "cited.md"
    assert main(["audit", *map(str, papers), "--cited", str(table), "--lookup"]) == 0
    capsys.readouterr()
    rows = [line for line in table.read_text(encoding="utf-8").splitlines()
            if line.startswith("| 1 ") or line.startswith("| 2 ")]  # fmt: skip
    assert "| A cohort |" in rows[0] and "| A trial. |" in rows[1]


def test_the_rows_follow_the_files_in_the_order_given(tmp_path: Path, capsys) -> None:
    """Round 2 of #482: a Markdown paper's rows came before a LaTeX paper named first; and a
    front matter's abstract comes before its file's body."""
    tex = tmp_path / "main.tex"
    tex.write_text(
        f"{BS}documentclass{{article}}\n{BS}begin{{document}}\n{BS}section{{Discussion}}\n"
        f"Tea was common~{BS}cite{{a}}.\n{BS}begin{{thebibliography}}{{9}}\n"
        f"{BS}bibitem{{a}} A.\n{BS}end{{thebibliography}}\n{BS}end{{document}}\n",
        encoding="utf-8")  # fmt: skip
    supplement = paper_md(tmp_path, "---\nabstract: Diet was rare [2].\n---\n\n"
                          "## Discussion\n\nSalt was common [1].\n\n" + REFERENCES)
    rows = _rows(capsys, tmp_path, tex, supplement)
    assert [row.split(" | ")[1] for row in rows] == ["main.tex:4", "paper.md:2", "paper.md:7"]


def test_a_nocite_and_a_commented_citation_cite_nothing(tmp_path: Path, capsys) -> None:
    """Round 2 of #482: `\\nocite` and a citation inside a comment passed a causal claim as
    cited."""
    paper = paper_md(tmp_path, "## Discussion\n\nSmoking causes cancer. "
                     "<!-- (Smith et al., 2019) -->\n\n" + REFERENCES)
    assert _causal(capsys, paper) == [(3, "Discussion")]
    tex = tmp_path / "paper.tex"
    tex.write_text(
        f"{BS}documentclass{{article}}\n{BS}begin{{document}}\n{BS}section{{Discussion}}\n"
        f"Smoking causes cancer. {BS}nocite{{a}}\nTea causes calm. % (Smith et al., 2019)\n"
        f"{BS}begin{{thebibliography}}{{9}}\n{BS}bibitem{{a}} A.\n{BS}end{{thebibliography}}\n"
        f"{BS}end{{document}}\n", encoding="utf-8")  # fmt: skip
    assert _causal(capsys, tex) == [(4, "Discussion"), (5, "Discussion")]


def test_a_word_document_s_notes_are_in_no_part(tmp_path: Path, capsys) -> None:
    """Round 2 of #482: a footnote, read after the body, was placed under its last
    heading."""
    paper = make_docx(tmp_path / "paper.docx", [("Discussion", True),
                                                 ("Tea was common.", False)])  # fmt: skip
    notes = (f"<?xml version='1.0'?><w:footnotes xmlns:w='{W}'><w:footnote w:id='1'><w:p><w:r>"
             "<w:t>Smoking causes cancer.</w:t></w:r></w:p></w:footnote></w:footnotes>")
    with zipfile.ZipFile(paper, "a") as archive:
        archive.writestr(zipfile.ZipInfo("word/footnotes.xml", (2020, 1, 1, 0, 0, 0)), notes)
    from manuscript_guard.text.docx import read_docx_text

    assert "Smoking causes cancer." in read_docx_text(paper).notes
    assert _causal(capsys, paper) == []


def test_a_journal_s_subtitle_after_a_colon_is_no_part_of_its_name() -> None:
    from manuscript_guard.auditing.selfcite import same_journal

    assert same_journal("Journal of Examples : official journal of the Society",
                        "Journal of Examples")  # fmt: skip
    assert same_journal("The Journal of Examples", "Journal of Examples")
    assert not same_journal("Journal of Other Examples", "Journal of Examples")


def test_a_closing_summary_is_the_conclusion(tmp_path: Path, capsys) -> None:
    """Round 2 of #482: a Summary after the Introduction, with headings under it, is the
    paper's last section, not its abstract."""
    text = ("# A cohort\n\n## Introduction\n\nTea was common.\n\n## Summary\n\n"
            "### Background\n\nSmoking causes cancer.\n")
    assert _causal(capsys, paper_md(tmp_path, text)) == [(11, "Conclusion")]


# --------------------------------------------------------- fix-only round on e5826ad0


@pytest.mark.parametrize("heading", ["## Discussion\n", "Discussion\n----------\n"],
                         ids=["atx", "setext"])  # fmt: skip
def test_a_sentence_typed_directly_under_a_heading_is_read(
    tmp_path: Path, capsys, heading: str
) -> None:
    """The heading is no sentence, and the text on the line after it is its own (round 3 of
    #482: the heading's piece took it with it)."""
    line = heading.count("\n") + 1
    text = f"{heading}Smoking causes cancer.\nTea was common [3].\n\n{REFERENCES}"
    paper = paper_md(tmp_path, text)
    assert _causal(capsys, paper) == [(line, "Discussion")]
    assert [row.split(" | ")[1:4] for row in _rows(capsys, tmp_path, paper)] == [
        [f"paper.md:{line + 1}", "Discussion", "Tea was common [3]."]]


def test_calcium_is_no_abbreviation_of_circa(tmp_path: Path, capsys) -> None:
    text = f"## Discussion\n\nWe measured serum Ca. [3] Statins cause fewer deaths.\n\n{REFERENCES}"
    assert _causal(capsys, paper_md(tmp_path, text)) == [(3, "Discussion")]
