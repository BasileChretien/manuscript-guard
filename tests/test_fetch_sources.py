"""`sync-sources` on the web: each cited work Zotero has no copy of, its open copy, else its PDF
through this computer's access, else its abstract; and `--inbox`, the PDFs the user saved.

No test opens a connection to a service. The registries and the publishers answer from a table
keyed by URL, in the shapes OpenAlex and Crossref document, with fictional works; the real
transport is run against a server on a loopback port. The PDFs are written here
(`tests/proof_pdf.py`), so that what is read as their first pages is known.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.literature import copies, fetching, inbox, matching
from manuscript_guard.lookup import download
from manuscript_guard.lookup.http import NoAnswer, Request, Response
from manuscript_guard.zotero import client, reset_cache

sys.path.insert(0, str(Path(__file__).parent))
from proof_pdf import Piece, pdf  # noqa: E402

pytest.importorskip("pypdf", reason="the first pages of a PDF are read with pypdf here")

DOI = "10.5555/fictional.2021.001"
OTHER = "10.5555/fictional.2019.002"
TITLE = "Hepatic injury in a fictional national cohort"
CONTACT = "author@example.org"
TODAY = date(2026, 11, 6)
PLACES = fetching.Places(
    openalex="https://api.test/openalex/doi:",
    crossref="https://api.test/crossref/",
    europepmc="https://pmc.test/render",
    arxiv="https://arxiv.test/pdf/",
    resolver="https://doi.test/",
)


@pytest.fixture(autouse=True)
def _fresh_client():
    reset_cache()
    yield
    reset_cache()


def article(*lines: str, pages: int = 1) -> bytes:
    """A PDF whose first page sets `lines`, one under another, and `pages - 1` pages after."""
    first = [Piece(56, 780 - 12 * at, text) for at, text in enumerate(lines)]
    rest = [[Piece(56, 780, f"Page {n}: the results, at length.")] for n in range(2, pages + 1)]
    return pdf([first, *rest])


THE_WORK = article("Journal of Examples 12 (2021) 101-109", "Hepatic injury in a fictional",
                   "national cohort", f"https://doi.org/{DOI}")  # fmt: skip
#: The work with its title and no DOI, as a copy at PubMed Central or arXiv may be.
TITLE_ONLY = article("Journal of Examples 12 (2021) 101-109", "Hepatic injury in a fictional",
                     "national cohort", "A. Fictional and B. Fictional")  # fmt: skip
ANOTHER = article("Imaginary Drug Safety Reports 7 (2019) 45-52",
                  "A disproportionality signal for a fictional drug class",
                  f"https://doi.org/{OTHER}")  # fmt: skip


def answer(status: int = 200, body: bytes | str | dict = b"", **headers: str) -> Response:
    if isinstance(body, dict):
        body = json.dumps(body)
    if isinstance(body, str):
        body = body.encode("utf-8")
    return Response(status, {k.replace("_", "-"): v for k, v in headers.items()}, body)


def pdf_answer(body: bytes) -> Response:
    return answer(200, body, Content_Type="application/pdf")


def page(body: str) -> Response:
    return answer(200, f"<html><head>{body}</head><body>Sign in</body></html>",
                  Content_Type="text/html; charset=utf-8")  # fmt: skip


class Table:
    """A transport that answers from a table of URLs, and keeps what it was sent. A URL it does
    not know is a 404, so that a test says every place a work is looked for."""

    def __init__(self, answers: dict[str, Response]) -> None:
        self.answers = answers
        self.sent: list[Request] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        self.sent.append(request)
        return self.answers.get(request.base, answer(404, b"not here"))

    @property
    def asked(self) -> list[str]:
        return [request.base for request in self.sent]


def openalex(*, pdf_url: str | None = None, landing: str | None = None,
             version: str = "publishedVersion", pmcid: str | None = None,
             abstract: dict | None = None, is_oa: bool = True) -> Response:  # fmt: skip
    location = {"is_oa": is_oa, "pdf_url": pdf_url, "landing_page_url": landing,
                "version": version}  # fmt: skip
    record = {
        "id": "https://openalex.org/W1",
        "doi": f"https://doi.org/{DOI}",
        "title": TITLE,
        "open_access": {"is_oa": is_oa, "oa_url": (pdf_url or landing) if is_oa else None},
        "best_oa_location": location if is_oa else None,
        "locations": [location],
        "ids": {"pmcid": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}"} if pmcid else {},
        "abstract_inverted_index": abstract,
    }
    return answer(200, record)


def crossref(abstract: str | None) -> Response:
    message = {"DOI": DOI, "title": [TITLE], **({"abstract": abstract} if abstract else {})}
    return answer(200, {"status": "ok", "message-type": "work", "message": message})


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    for one in (root / "manuscript").rglob("*.md"):
        one.unlink()
    return root


def cite(root: Path, **entries: dict[str, str]) -> None:
    """Cite each key, and write `references.bib` with its fields."""
    sentences = "\n\n".join(f"This was reported before [@{key}]." for key in entries)
    (root / "manuscript" / "main.md").write_text(f"# Introduction\n\n{sentences}\n", "utf-8")
    written = []
    for key, fields in entries.items():
        body = "".join(f"  {name} = {{{value}}},\n" for name, value in fields.items())
        written.append(f"@article{{{key},\n{body}  year = {{2021}},\n}}\n")
    (root / "literature" / "references.bib").write_text("\n".join(written), "utf-8")


def empty_zotero(method: str, params, timeout: int = 20):
    """Better BibTeX for a library whose item has no attachment, as `test_sync_sources` has
    it: null for `item.attachments`."""
    return [{"id": 1, "name": "Mine"}] if method == "user.groups" else None


def sources(root: Path) -> Path:
    return root / "literature" / "sources"


def record(root: Path) -> dict:
    return yaml.safe_load((root / "literature" / copies.RECORD).read_text("utf-8"))["files"]


def sync(root: Path, table: Table, *, dry_run: bool = False):
    """`sync-sources` with Zotero holding nothing, and the web answering from `table`."""
    project = load_project(root)[0]
    works = fetching.works_of(project, copies.wanted_keys(project))
    with fetching.Fetcher(works, transport=table, places=PLACES) as web:
        outcomes = copies.sync(project, dry_run=dry_run, today=TODAY, fetch=lambda key: None,
                               web=web)  # fmt: skip
        wanted = fetching.still_wanted(project, copies.wanted_keys(project), web)
    return outcomes, wanted


# --------------------------------------------------------------- is the PDF the work?


def test_a_pdf_that_gives_the_doi_on_its_first_page_is_the_work() -> None:
    text = "Journal of Examples\nhttps://doi.org/10.5555/\nfictional.2021.001\nReceived 2020"
    assert matching.judged(b"%PDF-1.4", text, DOI, None).by == "doi"


def test_a_title_broken_across_lines_and_hyphens_is_found() -> None:
    text = "HEPATIC IN-\nJURY in a fictional\nnational  cohort\nA. Fictional"
    assert matching.judged(b"%PDF-1.4", text, None, "Hepatic injury in a fictional "
                           "{N}ational cohort").by == "title"  # fmt: skip


def test_a_doi_is_not_found_as_the_start_of_a_longer_one() -> None:
    text = f"doi: {DOI}2 and nothing else"
    assert matching.judged(b"%PDF-1.4", text, DOI, None).by is None


def test_a_doi_at_the_end_of_a_line_is_found_whatever_the_next_line_begins_with() -> None:
    assert matching.doi_in(f"See {DOI}\n{OTHER}", DOI)
    assert matching.doi_in("https://doi.org/10.5555/\nfictional.2021.001\n2021", DOI)


def test_another_paper_is_not_the_work(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(ANOTHER)
    shown = matching.shows(path, DOI, TITLE)
    assert shown.by is None and f"another DOI ({OTHER})" in shown.why


def test_metadata_that_names_another_doi_is_not_outweighed_by_the_doi_in_the_text() -> None:
    raw = b"%PDF-1.7\n<x:xmpmeta><prism:doi>10.5555/a.review</prism:doi></x:xmpmeta>"
    shown = matching.judged(raw, f"As reported ({DOI})", DOI, TITLE)
    assert shown.by is None and "10.5555/a.review" in shown.why
    raw_ours = raw.replace(b"10.5555/a.review", DOI.encode())
    assert matching.judged(raw_ours, "", DOI, TITLE).by == "doi"


def test_a_short_title_is_no_evidence() -> None:
    assert matching.title_key("Editorial") is None
    assert matching.judged(b"%PDF-1.4", "Editorial", None, "Editorial").by is None


def test_a_page_saved_under_a_pdf_name_is_not_a_pdf(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"<html>Sign in</html>")
    assert "not a PDF" in matching.shows(path, DOI, TITLE).why


# --------------------------------------------------------------- the download itself


def test_redirects_are_followed_over_https_and_refused_to_http() -> None:
    table = Table({
        "https://doi.test/a": answer(302, Location="https://publisher.test/a"),
        "https://publisher.test/a": answer(301, Location="/a.pdf"),
        "https://publisher.test/a.pdf": pdf_answer(THE_WORK),
        "https://doi.test/b": answer(302, Location="http://publisher.test/b.pdf"),
    })  # fmt: skip
    got = download.get("https://doi.test/a", table)
    assert got.url == "https://publisher.test/a.pdf" and got.body == THE_WORK
    with pytest.raises(NoAnswer, match="not https"):
        download.get("https://doi.test/b", table)
    assert "http://publisher.test/b.pdf" not in table.asked


def test_a_redirect_loop_is_cut_off() -> None:
    table = Table({"https://loop.test/": answer(302, Location="https://loop.test/")})
    with pytest.raises(NoAnswer, match="more than"):
        download.get("https://loop.test/", table)
    assert len(table.sent) == download.MAX_HOPS + 1


def test_the_real_transport_sends_nothing_while_the_suite_forbids_it() -> None:
    with pytest.raises(download.Offline):
        download.default_transport(Request("https://example.org/"), 1.0)


def test_the_real_transport_caps_the_size_and_names_no_one(monkeypatch) -> None:
    seen: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the name http.server calls
            seen.append(dict(self.headers))
            body = b"%PDF-1.4\n" + b"x" * 4096
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.delenv(download.NO_NETWORK, raising=False)
    monkeypatch.setattr(download, "MAX_BYTES", 1024)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/a.pdf"
        with pytest.raises(NoAnswer, match="over the"):
            download.get(url, download.session(local=True), local=True)
        monkeypatch.setattr(download, "MAX_BYTES", 1 << 20)
        assert download.get(url, download.session(local=True),
                            local=True).body.startswith(b"%PDF-")
    finally:
        server.shutdown()
    agent = {k.lower(): v for k, v in seen[0].items()}["user-agent"]
    assert agent == download.AGENT and "@" not in agent and "mailto" not in agent


# --------------------------------------------------------------- an open copy


def test_an_open_copy_is_downloaded_filed_and_recorded(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    table = Table({
        PLACES.openalex + DOI: openalex(pdf_url="https://repository.test/hepatic.pdf"),
        "https://repository.test/hepatic.pdf": pdf_answer(THE_WORK),
    })  # fmt: skip
    (outcome,), wanted = sync(paper, table)

    assert outcome.status == copies.COPIED and "downloaded" in outcome.said
    assert "an open copy (published version), from repository.test" in outcome.said
    assert (sources(paper) / "hepatic2021.pdf").read_bytes() == THE_WORK
    entry = record(paper)["hepatic2021.pdf"]
    assert {k: entry[k] for k in ("key", "from", "url", "doi", "matched", "version")} == {
        "key": "hepatic2021", "from": "open", "url": "https://repository.test/hepatic.pdf",
        "doi": DOI, "matched": "doi", "version": "published"}  # fmt: skip
    assert wanted == []
    assert not any(PLACES.resolver in url for url in table.asked), "no publisher asked"


def test_a_landing_page_is_followed_to_the_pdf_it_names_once(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    meta = '<meta content="/files/hepatic.pdf" name="citation_pdf_url">'
    table = Table({
        PLACES.openalex + DOI: openalex(landing="https://repository.test/record/1"),
        "https://repository.test/record/1": page(meta),
        "https://repository.test/files/hepatic.pdf": pdf_answer(THE_WORK),
    })  # fmt: skip
    (outcome,), _ = sync(paper, table)
    assert outcome.status == copies.COPIED
    assert record(paper)["hepatic2021.pdf"]["url"] == "https://repository.test/record/1"


def test_a_pubmed_central_copy_is_taken_by_the_pmcid(paper: Path) -> None:
    """The copy prints the work's DOI, as a PMC copy does (round 2 of #565: a copy was given
    with no DOI on it, which hid the copy's own DOI being refused)."""
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI, "pmcid": "PMC1234567"})
    url = f"{PLACES.europepmc}?accid=PMC1234567&blobtype=pdf"
    table = Table({url: pdf_answer(THE_WORK), PLACES.crossref + DOI: crossref(None)})
    (outcome,), _ = sync(paper, table)
    assert outcome.status == copies.COPIED and "from pmc.test" in outcome.said
    assert record(paper)["hepatic2021.pdf"]["matched"] == "doi"


def test_a_copy_with_no_doi_is_taken_by_its_title(paper: Path) -> None:
    cite(paper, nodoi2020={"title": TITLE, "pmcid": "PMC1234567"})
    url = f"{PLACES.europepmc}?accid=PMC1234567&blobtype=pdf"
    table = Table({url: pdf_answer(TITLE_ONLY)})
    (outcome,), _ = sync(paper, table)
    assert outcome.status == copies.COPIED
    assert record(paper)["nodoi2020.pdf"]["matched"] == "title"
    assert "doi" not in record(paper)["nodoi2020.pdf"]


def test_an_arxiv_copy_is_taken_by_its_identifier(paper: Path) -> None:
    cite(paper, preprint2021={"title": TITLE, "eprint": "2101.01234", "archiveprefix": "arXiv"})
    table = Table({PLACES.arxiv + "2101.01234": pdf_answer(TITLE_ONLY)})
    (outcome,), _ = sync(paper, table)
    assert outcome.status == copies.COPIED and "submitted version" in outcome.said
    assert record(paper)["preprint2021.pdf"]["version"] == "submitted"


def test_an_open_copy_that_is_another_paper_is_not_kept(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    table = Table({
        PLACES.openalex + DOI: openalex(pdf_url="https://repository.test/wrong.pdf"),
        "https://repository.test/wrong.pdf": pdf_answer(ANOTHER),
        PLACES.crossref + DOI: crossref(None),
    })  # fmt: skip
    (outcome,), wanted = sync(paper, table)
    assert outcome.status == copies.NO_COPY
    assert "not shown to be the work" in outcome.said
    assert not (sources(paper) / "hepatic2021.pdf").exists()
    assert [one.key for one in wanted] == ["hepatic2021"]


# --------------------------------------------------------------- the publisher, from here


def test_the_publishers_pdf_is_kept_where_this_computer_has_access(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI, "pages": "101--109"})
    table = Table({
        PLACES.openalex + DOI: openalex(is_oa=False),
        PLACES.resolver + DOI: answer(302, Location="https://publisher.test/article/1"),
        "https://publisher.test/article/1": page(
            '<meta name="citation_pdf_url" content="https://publisher.test/article/1.pdf">'),
        "https://publisher.test/article/1.pdf": pdf_answer(article(TITLE, DOI, pages=9)),
    })  # fmt: skip
    (outcome,), wanted = sync(paper, table)
    assert outcome.status == copies.COPIED and "through this computer's access" in outcome.said
    entry = record(paper)["hepatic2021.pdf"]
    assert entry["from"] == "publisher" and entry["url"] == PLACES.resolver + DOI
    assert wanted == []


def test_a_paywall_page_is_not_kept_and_the_abstract_is_written(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    abstract = ("<jats:title>Abstract</jats:title><jats:p>Liver injury was rare &amp; "
                "mostly mild.</jats:p>")  # fmt: skip
    table = Table({
        PLACES.openalex + DOI: openalex(is_oa=False),
        PLACES.resolver + DOI: answer(302, Location="https://publisher.test/article/1"),
        "https://publisher.test/article/1": page("<title>Purchase this article</title>"),
        PLACES.crossref + DOI: crossref(abstract),
    })  # fmt: skip
    (outcome,), wanted = sync(paper, table)

    assert not (sources(paper) / "hepatic2021.pdf").exists()
    written = (sources(paper) / "hepatic2021.abstract.txt").read_text("utf-8")
    assert written == f"{TITLE}\n\nLiver injury was rare & mostly mild.\n"
    assert outcome.status == copies.COPIED and "abstract only, as Crossref" in outcome.said
    entry = record(paper)["hepatic2021.abstract.txt"]
    assert entry["from"] == "abstract" and entry["url"] == PLACES.crossref + DOI
    (one,) = wanted
    assert one.abstract and one.link == f"https://doi.org/{DOI}"
    assert any("gave a page, not the PDF" in why for why in one.why)
    lines = fetching.asked(wanted)
    assert "--inbox" in lines[0] and f"@hepatic2021: https://doi.org/{DOI}" in lines[1]


def test_a_first_page_preview_is_not_kept(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI, "pages": "101--109"})
    table = Table({
        PLACES.openalex + DOI: openalex(is_oa=False),
        PLACES.resolver + DOI: pdf_answer(THE_WORK),
    })  # fmt: skip
    (outcome,), _ = sync(paper, table)
    assert outcome.status == copies.NO_COPY and "a preview, most likely" in outcome.said


def test_openalex_s_abstract_stands_in_where_crossref_has_none(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    index = {"Liver": [0], "injury": [1], "was": [2], "rare.": [3]}
    table = Table({
        PLACES.openalex + DOI: openalex(is_oa=False, abstract=index),
        PLACES.crossref + DOI: crossref(None),
    })  # fmt: skip
    sync(paper, table)
    text = (sources(paper) / "hepatic2021.abstract.txt").read_text("utf-8")
    assert text.endswith("Liver injury was rare.\n")
    assert table.asked.count(PLACES.openalex + DOI) == 1, "OpenAlex is asked once a work"


# --------------------------------------------------------------- what is never done


def test_a_work_with_a_copy_is_not_looked_for_again(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    table = Table({
        PLACES.openalex + DOI: openalex(pdf_url="https://repository.test/hepatic.pdf"),
        "https://repository.test/hepatic.pdf": pdf_answer(THE_WORK),
    })  # fmt: skip
    sync(paper, table)
    again = Table({})
    (outcome,), _ = sync(paper, again)
    assert again.sent == [] and outcome.status == copies.STORED


def test_an_authors_abstract_is_never_written_over(paper: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    sources(paper).mkdir(parents=True, exist_ok=True)
    mine = sources(paper) / "hepatic2021.abstract.txt"
    mine.write_text("The abstract as I copied it.", "utf-8")
    table = Table({PLACES.crossref + DOI: crossref("<jats:p>Another text.</jats:p>")})
    outcomes, _ = sync(paper, table)
    assert mine.read_text("utf-8") == "The abstract as I copied it."
    assert any(one.status == copies.KEPT for one in outcomes)
    assert record(paper)["hepatic2021.abstract.txt"]["from"] == copies.FROM_AUTHOR


def test_with_no_network_allowed_nothing_more_is_asked(paper: Path) -> None:
    cite(paper, one2021={"title": TITLE, "doi": DOI}, two2019={"title": TITLE, "doi": OTHER})

    class Refusing(Table):
        def __call__(self, request, timeout):
            self.sent.append(request)
            raise download.Offline("no request may leave")

    table = Refusing({})
    outcomes, wanted = sync(paper, table)
    assert len(table.sent) == 1
    assert all("not looked for on the web: no request may leave" in o.said for o in outcomes)
    assert [one.key for one in wanted] == ["one2021", "two2019"]


def test_a_dry_run_asks_the_web_nothing(paper: Path, monkeypatch, capsys) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    table = Table({})
    monkeypatch.setattr(download, "session", lambda: table)
    monkeypatch.setattr(client, "rpc", empty_zotero)
    assert main(["sync-sources", str(paper), "--dry-run"]) == 0
    assert "Nothing was looked for on the web (--dry-run)" in capsys.readouterr().out
    assert main(["sync-sources", str(paper), "--no-fetch"]) == 0
    assert table.sent == []


def test_sync_sources_fetches_by_default_and_sends_no_address(paper, monkeypatch, capsys):
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    monkeypatch.setenv("MANUSCRIPT_GUARD_CONTACT", CONTACT)
    table = Table({
        "https://api.openalex.org/works/doi:" + DOI:
            openalex(pdf_url="https://repository.test/hepatic.pdf"),
        "https://repository.test/hepatic.pdf": pdf_answer(THE_WORK),
    })  # fmt: skip
    monkeypatch.setattr(download, "session", lambda: table)
    monkeypatch.setattr(client, "rpc", empty_zotero)
    assert main(["sync-sources", str(paper)]) == 0
    assert (sources(paper) / "hepatic2021.pdf").read_bytes() == THE_WORK
    assert "downloaded literature/sources/hepatic2021.pdf" in capsys.readouterr().out
    for sent in table.sent:
        assert CONTACT not in sent.url and CONTACT not in repr(dict(sent.headers))


# --------------------------------------------------------------- the inbox


def inbox_sync(root: Path, folder: Path):
    project = load_project(root)[0]
    offered = inbox.offer(project, folder)
    return copies.sync(project, today=TODAY, offered=offered), offered


def test_a_saved_pdf_is_filed_under_the_work_it_shows(paper: Path, tmp_path: Path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI}, signal2019={"title": "x", "doi": OTHER})
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "1-s2.0-S0000000000000001-main.pdf").write_bytes(THE_WORK)
    (downloads / "unrelated.pdf").write_bytes(article("Minutes of a meeting about nothing"))
    (downloads / "login.pdf").write_bytes(b"<html>Sign in</html>")
    (downloads / "older").mkdir()
    (downloads / "older" / "signal.pdf").write_bytes(ANOTHER)
    outcomes, offered = inbox_sync(paper, downloads)

    assert (sources(paper) / "hepatic2021.pdf").read_bytes() == THE_WORK
    entry = record(paper)["hepatic2021.pdf"]
    assert (entry["from"], entry["matched"], entry["doi"]) == ("inbox", "doi", DOI)
    assert not (sources(paper) / "signal2019.pdf").exists(), "a subfolder is not read"
    lines = copies.report(outcomes, offered=offered)
    assert any("1 PDF in the folder shows no cited work" in line for line in lines)
    assert any("login.pdf does not begin with %PDF-" in line for line in lines)


def test_a_saved_pdf_that_shows_two_cited_works_is_filed_for_neither(paper, tmp_path) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI}, signal2019={"title": "x", "doi": OTHER})
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "review.pdf").write_bytes(article("A review", DOI, OTHER))
    outcomes, _ = inbox_sync(paper, downloads)
    assert not list(sources(paper).glob("*.pdf"))
    assert all("another DOI" in one.said or "several cited works" in one.said
               for one in outcomes), outcomes


def test_the_inbox_flag_needs_a_folder(paper: Path, capsys) -> None:
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    assert main(["sync-sources", str(paper), "--inbox", str(paper / "nowhere"), "--no-fetch"]) == 2
    assert "is not a folder" in capsys.readouterr().err


# --------------------------------------------------------------- what reads the copies


def test_a_fetched_copy_is_read_as_the_works_by_g7_and_the_checker_page(paper: Path) -> None:
    from manuscript_guard.checking.produce import _reference_items
    from manuscript_guard.contracts.literature import load_literature
    from manuscript_guard.literature.sources import stored_files

    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    table = Table({PLACES.openalex + DOI: openalex(is_oa=False),
                   PLACES.crossref + DOI: crossref("<jats:p>Liver injury was rare.</jats:p>")})
    sync(paper, table)
    folder = sources(paper)
    assert [p.name for p in stored_files(folder, "hepatic2021")] == ["hepatic2021.abstract.txt"]
    project = load_project(paper)[0]
    literature, _ = load_literature(project.path("literature"))
    items = _reference_items(project, literature)
    (item,) = [one for one in items if "hepatic2021" in one["title"]]
    rows = dict(item["evidence"][0]["rows"])
    assert rows["Stored copy"] == "hepatic2021.abstract.txt"



# --------------------------------------------------------------- round 1 of #565


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:23119/better-bibtex/json-rpc", "http://127.0.0.1:9/x",
    "https://127.0.0.1/x.pdf", "https://localhost/x.pdf", "https://[::1]/x.pdf",
    "https://192.168.1.1/x.pdf", "https://10.0.0.5/x.pdf", "https://169.254.169.254/latest",
    "https://[fe80::1]/x.pdf", "http://publisher.test/x.pdf", "https://[x/a.pdf",
])  # fmt: skip
def test_no_link_to_this_machine_or_its_network_is_asked(url: str) -> None:
    """Round 1 of #565: plain http to this machine, which is how the tests answer, and https
    to any address were allowed, so a publisher's redirect could reach Zotero's port or a
    router. The tests' exception is a flag now, and no address of this machine or its network
    is asked for."""
    assert not download.allowed(url)


def test_this_machine_is_asked_only_where_a_test_says_so() -> None:
    assert download.allowed("http://127.0.0.1:8000/a.pdf", local=True)
    assert not download.allowed("http://127.0.0.1:8000/a.pdf")


def test_a_redirect_to_this_machine_is_not_followed() -> None:
    table = Table({"https://doi.test/b": answer(302, Location="http://127.0.0.1:9/x"),
                   "https://doi.test/c": answer(302, Location="https://10.1.2.3/x")})
    for url in ("https://doi.test/b", "https://doi.test/c"):
        with pytest.raises(NoAnswer):
            download.get(url, table)
    assert table.asked == ["https://doi.test/b", "https://doi.test/c"]


def test_a_name_that_resolves_to_this_network_is_not_asked(monkeypatch) -> None:
    """The name is resolved before each request, every hop, and a private, loopback or
    link-local address refused: `allowed` sees only the name."""
    import socket

    monkeypatch.delenv(download.NO_NETWORK, raising=False)
    asked: list[str] = []

    def resolve(host, *args, **kwargs):
        asked.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.20.30.40", 443))]

    def no_connection(*args, **kwargs):
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket, "create_connection", no_connection)
    with pytest.raises(NoAnswer, match="this computer's own network"):
        download.default_transport(Request("https://intranet.example/x.pdf"), 1.0)
    assert asked == ["intranet.example"]


@pytest.mark.parametrize("bad", ["pdf_url", "location", "meta"])
def test_a_malformed_link_lists_the_work_as_wanted_and_the_run_goes_on(paper, bad) -> None:
    """Round 1 of #565: `https://[x/a.pdf` raised ValueError out of `urlsplit` and stopped the
    run, and the works after it were not tried."""
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI}, other2019={"title": TITLE, "doi": OTHER})
    broken = "https://[x/a.pdf"
    answers = {PLACES.crossref + DOI: crossref(None)}
    if bad == "pdf_url":
        answers[PLACES.openalex + DOI] = openalex(pdf_url=broken)
    elif bad == "location":
        answers[PLACES.openalex + DOI] = openalex(pdf_url="https://repository.test/a.pdf")
        answers["https://repository.test/a.pdf"] = answer(302, Location=broken)
    else:
        answers[PLACES.openalex + DOI] = openalex(landing="https://repository.test/r")
        answers["https://repository.test/r"] = page(f'<meta name="citation_pdf_url" '
                                                    f'content="{broken}">')
    table = Table(answers)
    outcomes, wanted = sync(paper, table)
    assert [one.key for one in wanted] == ["hepatic2021", "other2019"]
    assert any(PLACES.openalex + OTHER == url for url in table.asked), "the next work is tried"


def test_a_title_in_the_running_text_is_not_the_title() -> None:
    """Round 1 of #565: a title anywhere on the first two pages was evidence, so a paper whose
    abstract used the cited review's title as a phrase was filed as the review."""
    text = ("Journal of Other Things\nA cohort of adults\nBackground: we studied hepatic "
            "injury in a fictional national cohort of adults, and found little.\n")
    assert matching.judged(b"%PDF-1.4", text, None, TITLE).by is None


def test_a_title_is_no_evidence_where_the_metadata_names_another_doi() -> None:
    raw = b"%PDF-1.7\n<prism:doi>10.5555/someone.else</prism:doi>"
    text = "Hepatic injury in a fictional\nnational cohort\nA. Fictional"
    shown = matching.judged(raw, text, DOI, TITLE)
    assert shown.by is None and "10.5555/someone.else" in shown.why


def test_a_title_is_no_evidence_where_the_first_page_gives_another_doi() -> None:
    text = "Hepatic injury in a fictional\nnational cohort\nhttps://doi.org/10.5555/someone.else"
    assert matching.judged(b"%PDF-1.4", text, DOI, TITLE).by is None
    assert matching.judged(b"%PDF-1.4", text, None, TITLE).by is None


def test_a_lancet_doi_in_the_metadata_is_read_whole() -> None:
    doi = "10.1016/s0140-6736(20)30183-5"
    raw = b"%PDF-1.7\n<prism:doi>10.1016/S0140-6736(20)30183-5</prism:doi>"
    assert matching.metadata_dois(raw) == {doi}
    assert matching.judged(raw, "", doi, None).by == "doi"


def test_a_supplements_doi_is_not_the_works() -> None:
    """PLoS names a supplement `<doi>.s001`: that is another DOI, not the work's."""
    assert not matching.doi_in(f"https://doi.org/{DOI}.s001", DOI)
    assert matching.doi_in(f"doi: {DOI}.\nReceived 2020", DOI)


@pytest.mark.parametrize("head", [
    "Supplementary Appendix", "Supplement to: Fictional A. Hepatic injury.",
    "Supporting Information", "Correction to: Hepatic injury in a fictional national cohort",
    "Erratum", "In reply", "Reply to the letter by Smith",
])  # fmt: skip
def test_a_document_about_the_work_is_not_filed_as_the_work(paper, tmp_path, head) -> None:
    """Round 1 of #565: a supplement, a correction or a reply shows the work's DOI and title,
    and was filed as its full text. Import refuses rather than guesses."""
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI})
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "appendix.pdf").write_bytes(article(head, "Hepatic injury in a fictional",
                                                     "national cohort", f"doi: {DOI}"))
    outcomes, _ = inbox_sync(paper, downloads)
    assert not (sources(paper) / "hepatic2021.pdf").exists()
    assert any("not the work itself" in one.said for one in outcomes), outcomes


def test_a_work_whose_own_title_says_reply_is_still_filed(paper, tmp_path) -> None:
    title = "In reply: hepatic injury in a fictional national cohort"
    cite(paper, reply2021={"title": title, "doi": DOI})
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "r.pdf").write_bytes(article("In reply: hepatic injury in a fictional",
                                              "national cohort", f"doi: {DOI}"))
    inbox_sync(paper, downloads)
    assert (sources(paper) / "reply2021.pdf").exists()


def test_a_preview_saved_in_the_inbox_is_not_filed(paper, tmp_path) -> None:
    """Round 1 of #565: the half-the-pages rule held only for the publisher's fetch."""
    cite(paper, hepatic2021={"title": TITLE, "doi": DOI, "pages": "101--109"})
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "preview.pdf").write_bytes(THE_WORK)
    outcomes, _ = inbox_sync(paper, downloads)
    assert not (sources(paper) / "hepatic2021.pdf").exists()
    assert any("a preview, most likely" in one.said for one in outcomes)
    (downloads / "preview.pdf").write_bytes(article(TITLE, f"doi: {DOI}", pages=9))
    inbox_sync(paper, downloads)
    assert (sources(paper) / "hepatic2021.pdf").exists()



# --------------------------------------------------------------- round 2 of #565


@pytest.mark.parametrize(("raw", "doi"), [
    (rb"<</doi(10.1038/s41598-018-33980-0)/Author(Adrien Fictional)/Title(x)>>",
     "10.1038/s41598-018-33980-0"),
    (rb"<</doi(10.1186/s12888-019-2190-5)/CrossMarkDomains[1](springer.com)>>",
     "10.1186/s12888-019-2190-5"),
    (rb"<</doi(10.1016/j.bbr.2020.112345)/robots(noindex)>>", "10.1016/j.bbr.2020.112345"),
    (rb"<</doi(10.1016/S0140-6736\(20\)30183-5)/Title(x)>>", "10.1016/s0140-6736(20)30183-5"),
    (rb"<</doi(10.1016/S0140-6736(20)30183-5)/Title(x)>>", "10.1016/s0140-6736(20)30183-5"),
    (rb"<</doi (doi:10.1000/abc.1) /Subject(x)>>", "10.1000/abc.1"),
    (b"<prism:doi>10.1016/S0140-6736(20)30183-5</prism:doi>", "10.1016/s0140-6736(20)30183-5"),
])  # fmt: skip
def test_an_info_dictionarys_doi_is_read_to_the_bracket_that_closes_it(raw, doi) -> None:
    """Round 2 of #565: Nature, BMC and Elsevier write the Info dictionary with no space
    between its keys, `/doi(...)/Author(...)`, and the DOI ran on into the next key, so the
    work's own PDF was refused as naming another DOI."""
    assert matching.metadata_dois(b"%PDF-1.7\n" + raw) == {doi}
    assert matching.judged(b"%PDF-1.7\n" + raw, "", doi, None).by == "doi"


@pytest.mark.parametrize("beside", [
    "Data Availability: https://doi.org/10.5061/dryad.abc123",
    "See Online/Comment https://doi.org/10.1016/S0140-6736(20)30183-5",
    "This article is a reply to doi:10.5555/another.2020.9",
])  # fmt: skip
def test_another_doi_printed_beside_the_works_own_does_not_refuse_it(beside: str) -> None:
    """Round 2 of #565: any other DOI on page 1 refused the PDF, though the work's own DOI
    was there too. Another DOI refuses a title match only."""
    text = f"Journal of Examples\nhttps://doi.org/{DOI}\nA study\n{beside}\n"
    assert matching.judged(b"%PDF-1.4", text, DOI, TITLE).by == "doi"


def test_the_works_doi_with_a_word_glued_on_is_still_the_works() -> None:
    """`-layout` set the next word against the DOI, `10.1177/25152459221106366deffner`, and
    the work's own DOI was read as another."""
    doi = "10.1177/25152459221106366"
    text = f"Advances in Examples\nhttps://doi.org/{doi}deffner et al.\nA study\n"
    assert matching.judged(b"%PDF-1.4", text, doi, None).by == "doi"


def test_a_preprint_printing_its_own_doi_is_not_taken_by_the_title() -> None:
    """A bioRxiv copy of the cited article prints the preprint's DOI and the article's
    title: the title is not evidence beside another DOI, and it is refused."""
    text = ("bioRxiv preprint\nHepatic injury in a fictional\nnational cohort\n"
            "doi: 10.1101/2020.01.01.123")
    shown = matching.judged(b"%PDF-1.4", text, DOI, TITLE)
    assert shown.by is None and "10.1101/2020.01.01.123" in shown.why


@pytest.mark.parametrize("cited", ["10.5555/fictional.\n2018.777", "10.5555/fictional.2020.123"])
def test_a_doi_in_another_papers_references_is_not_the_works(cited: str) -> None:
    """Round 3 of #565: a reference's DOI cut at a line break, or the work's on page 2."""
    text = ("Imaginary Drug Safety Reports\nhttps://doi.org/10.5555/fictional.2019.002\n"
            f"A signal\n\fReferences\n[3] Smith. https://doi.org/{cited}\n")
    assert matching.judged(b"%PDF-1.4\n", text, "10.5555/fictional.2020.123", None).by is None
