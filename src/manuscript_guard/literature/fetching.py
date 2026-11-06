"""`sync-sources`, for a cited work Zotero holds no copy of: its open copy, else its PDF
through this computer's own access, else its abstract, and a list of what to ask the user for.

Basile, 2026-11-06, running the study paper through the toolkit with none of its 54 references
in Zotero: "The package should always fetch the open ones, and try to connect to the
paywalled ones through the user browser (who might be inside the university) in order to
download them if they are available. In the case that they are not download the abstract and
ask for the pdf to the user if he can give it to you". So, in this order, and only for a work
with no full text stored:

1. **An open copy.** OpenAlex is asked for the work by its DOI: `best_oa_location`, then each
   other open location, with its PDF link before its landing page; then PubMed Central, by the
   PMCID `references.bib` or OpenAlex gives (through Europe PMC's PDF service, which answers
   a plain client where PMC's own pages ask for a browser); then arXiv, by its identifier. A
   landing page is read for the one link a publisher's page gives a citation manager,
   `<meta name="citation_pdf_url">`, and that link is tried once. Nothing else on a page is
   followed, and nothing on it is run.
2. **The publisher's PDF through this computer's access.** `https://doi.org/<doi>` is asked
   from here, following the publisher's redirects over https, and its `citation_pdf_url` once.
   On a university's network, or through its proxy as the environment names it, that is the
   university's access, as it is for the user's browser; elsewhere the publisher answers with
   its paywall page, which is not kept. A CLI cannot drive the user's own browser, signed in
   through their library: the works left are listed with their DOI links, for the user, or an
   agent driving that browser, to save, and `sync-sources --inbox <folder>` files what was
   saved (`literature/inbox.py`).
3. **Its abstract,** where no full text could be had: Crossref's, which the publisher
   deposited, then OpenAlex's, rebuilt from its index of the abstract's words. Written as
   `<key>.abstract.txt`, the name G7 and the checker page read an abstract by, and the work
   is still listed as one to ask the user for.

Every PDF is held to being the work before it is kept (`literature/matching.py`): it begins
with `%PDF-`, its first pages give the work's DOI or its title, and one from a publisher has
at least half the pages `references.bib` gives the work, since a first-page preview passes the
other two tests. A publisher's landing page, a preview, or another paper under the key would be
worse than no copy: G7 would hold quotes to it, and a co-author would read it as the work.

What leaves this computer: the DOI, PMCID or arXiv identifier asked about, and a User-Agent
naming the toolkit. No e-mail address goes to any of these services, the contact address
`lookup` sends Crossref and NCBI included; OpenAlex's key goes where the environment sets one,
as `lookup` sends it.
"""

from __future__ import annotations

import html
import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from manuscript_guard.contracts.project import Project
from manuscript_guard.gates.identifiers import BIB_FILE, doi_of
from manuscript_guard.literature import matching
from manuscript_guard.literature.bibfile import read_entries
from manuscript_guard.literature.copies import (
    FROM_ABSTRACT,
    FROM_OPEN,
    FROM_PUBLISHER,
    Candidate,
    digest,
)
from manuscript_guard.literature.sources import filed_name
from manuscript_guard.lookup import download
from manuscript_guard.lookup.http import NoAnswer, Request, Response, Transport

#: The most places a work's open copy is looked for at: OpenAlex lists a copy at every
#: repository that holds one, and the first few are the best it knows.
MOST_PLACES = 6
_PMCID = re.compile(r"PMC\d{1,9}", re.IGNORECASE)
_ARXIV_DOI = re.compile(r"10\.48550/arxiv\.(.+)", re.IGNORECASE)
_ARXIV = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]*(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?")
_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"""([a-zA-Z_:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_TAG = re.compile(r"<[^>]+>")
_PAGES = re.compile(r"^\s*(\d{1,5})\s*[-–]{1,2}\s*(\d{1,5})\s*$")
#: A PDF first, a page to find its PDF link on second.
ACCEPT = "application/pdf,text/html;q=0.8,*/*;q=0.5"
#: What OpenAlex calls the versions of a copy, as the record keeps them.
VERSIONS = {"publishedVersion": "published", "acceptedVersion": "accepted",
            "submittedVersion": "submitted"}  # fmt: skip


@dataclass(frozen=True)
class Places:
    """Where each service is asked. The tests point every one at a host of their own."""

    openalex: str = "https://api.openalex.org/works/doi:"
    crossref: str = "https://api.crossref.org/works/"
    europepmc: str = "https://europepmc.org/backend/ptpmcrender.fcgi"
    arxiv: str = "https://arxiv.org/pdf/"
    resolver: str = "https://doi.org/"


@dataclass(frozen=True)
class Work:
    """What `references.bib` says a cited work can be found by."""

    key: str
    doi: str | None = None
    pmcid: str | None = None
    arxiv: str | None = None
    title: str | None = None
    #: The pages its entry gives it, "101--109" being 9; None where it gives no range.
    pages: int | None = None

    @property
    def link(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None


@dataclass(frozen=True)
class Place:
    """A URL a copy may be at, what it is said to be, and how it is described."""

    url: str
    kind: str
    version: str | None = None


def works_of(project: Project, keys: list[str]) -> dict[str, Work]:
    """The works of `keys` that `references.bib` holds."""
    bib = project.path("literature") / BIB_FILE
    entries = read_entries(bib) if bib.is_file() else {}
    return {key: work_of(key, entries[key]) for key in keys if key in entries}


def work_of(key: str, fields: dict[str, str]) -> Work:
    kind = (fields.get("eprinttype") or fields.get("archiveprefix") or "").lower()
    eprint = fields.get("eprint", "").strip()
    pmcid = fields.get("pmcid", "").strip() or (eprint if kind == "pmc" else "")
    doi = doi_of(fields)
    arxiv = re.sub(r"(?i)^arxiv:", "", eprint) if kind == "arxiv" else ""
    if not arxiv and doi and (found := _ARXIV_DOI.fullmatch(doi)):
        arxiv = found.group(1)
    return Work(
        key=key,
        doi=doi,
        pmcid=pmcid.upper() if _PMCID.fullmatch(pmcid) else None,
        arxiv=arxiv if _ARXIV.fullmatch(arxiv) else None,
        title=fields.get("title") or None,
        pages=_page_range(fields.get("pages", "")),
    )


def _page_range(pages: str) -> int | None:
    found = _PAGES.match(pages)
    if not found:
        return None
    first, last = int(found.group(1)), int(found.group(2))
    return last - first + 1 if 0 < first <= last and last - first < 500 else None


def has_full_text(folder: Path, key: str) -> bool:
    """Whether a file of the work other than its abstract is stored."""
    from manuscript_guard.literature.sources import stored_files

    return any(".abstract." not in path.name for path in stored_files(folder, key))


@dataclass
class Fetcher:
    """Finds each work's copy on the web, staging what it downloads in a folder of its own
    until `sync` files it. Used as a context manager, which removes that folder."""

    works: dict[str, Work]
    transport: Transport = field(default_factory=download.session)
    places: Places = field(default_factory=Places)
    openalex_key: str | None = None
    pace: Callable[[str], None] = lambda host: None
    #: Why each work asked about has no full text, for the list of what to ask the user for.
    why: dict[str, list[str]] = field(default_factory=dict)
    #: Set when no request may leave the machine: nothing more is asked.
    offline: str | None = None
    _scratch: tempfile.TemporaryDirectory | None = None
    _records: dict[str, dict[str, Any] | None] = field(default_factory=dict)

    def __enter__(self) -> Fetcher:
        self._scratch = tempfile.TemporaryDirectory(prefix="manuscript-guard-fetch-")
        return self

    def __exit__(self, *exc: object) -> None:
        if self._scratch is not None:
            self._scratch.cleanup()
            self._scratch = None

    def __call__(self, key: str) -> tuple[list[Candidate], list[str]]:
        """The copy to file for the work, or its abstract, or nothing, and why it has no full
        text where it has none."""
        work = self.works.get(key)
        if work is None:
            said = [f"not in {BIB_FILE}, so there is nothing to look for it on the web by"]
            self.why[key] = said
            return [], said
        said: list[str] = []
        found = self._full_text(work, said)
        if found is not None:
            self.why.pop(key, None)
            return [found], []
        if self.offline:
            said = [f"not looked for on the web: {self.offline}"]
            self.why[key] = said
            return [], said
        abstract = self._abstract(work, said)
        self.why[key] = said
        return ([abstract] if abstract else []), said

    # ---------------------------------------------------------------- the full text

    def _full_text(self, work: Work, said: list[str]) -> Candidate | None:
        if self.offline:
            return None
        if not (work.doi or work.pmcid or work.arxiv):
            said.append("no DOI, PMCID or arXiv identifier to look for a copy by")
            return None
        record = self._openalex(work, said) if work.doi else None
        if self.offline:
            return None
        places = self._open_places(work, record)
        if not places and not self.offline:
            said.append("no open copy known to OpenAlex" if record is not None
                        else "no open copy found")  # fmt: skip
        for place in places[:MOST_PLACES]:
            found = self._try(work, place, said)
            if found is not None or self.offline:
                return found
        if work.doi:
            return self._try(work, Place(self.places.resolver + work.doi, FROM_PUBLISHER), said)
        return None

    def _open_places(self, work: Work, record: dict[str, Any] | None) -> list[Place]:
        """Where an open copy may be, best first, each once."""
        found: list[Place] = []
        oa = record.get("open_access") if isinstance(record, dict) else None
        best = record.get("best_oa_location") if isinstance(record, dict) else None
        locations = [best] if isinstance(best, dict) else []
        locations += [one for one in (record or {}).get("locations") or [] if isinstance(one, dict)]
        open_ones = [one for one in locations if one.get("is_oa") is True]
        for one in open_ones:
            found.append(_place(one.get("pdf_url"), one.get("version")))
        ids = record.get("ids") if isinstance(record, dict) else None
        pmcid = work.pmcid or _pmcid(ids.get("pmcid") if isinstance(ids, dict) else None)
        if pmcid:
            found.append(_place(f"{self.places.europepmc}?accid={pmcid}&blobtype=pdf", None))
        if work.arxiv:
            found.append(_place(self.places.arxiv + work.arxiv, "submittedVersion"))
        for one in open_ones:
            found.append(_place(one.get("landing_page_url"), one.get("version")))
        if isinstance(oa, dict) and oa.get("is_oa") is True:
            found.append(_place(oa.get("oa_url"), None))
        kept: dict[str, Place] = {}
        for place in found:
            if place is not None and download.allowed(place.url):
                kept.setdefault(place.url, place)
        return list(kept.values())

    def _try(self, work: Work, place: Place, said: list[str]) -> Candidate | None:
        """The PDF at a place, or on the page there by its `citation_pdf_url`, where it is the
        work's; None, with the reason said, where it is not."""
        host = urlsplit(place.url).hostname or "?"
        where = "the publisher's site, asked from this computer" if place.kind == FROM_PUBLISHER \
            else host  # fmt: skip
        fetched = self._get(place.url, said, where)
        if fetched is None:
            return None
        if fetched.status != 200:
            said.append(f"{where} answered HTTP {fetched.status}")
            return None
        if not fetched.body.startswith(matching.PDF_HEADER):
            link = citation_pdf_url(fetched.body, fetched.url)
            if link is None:
                said.append(f"{where} gave a page, not the PDF, and the page names no PDF")
                return None
            fetched = self._get(link, said, where)
            if fetched is None:
                return None
            if fetched.status != 200 or not fetched.body.startswith(matching.PDF_HEADER):
                status = f"HTTP {fetched.status}" if fetched.status != 200 else "a page"
                said.append(f"{where} named a PDF on its page, and gave {status} for it")
                return None
        return self._kept(work, place, fetched, said, where)

    def _kept(self, work: Work, place: Place, fetched: download.Fetched, said: list[str],
              where: str) -> Candidate | None:  # fmt: skip
        staged = self._stage(work.key, ".pdf", fetched.body)
        shown = matching.shows(staged, work.doi, work.title)
        if shown.by is None:
            said.append(f"the PDF {where} gave is not shown to be the work: {shown.why}")
            return None
        if place.kind == FROM_PUBLISHER and work.pages:
            counted = matching.page_count(staged)
            if counted is not None and counted * 2 < work.pages:
                said.append(f"the PDF {where} gave has {counted} page"
                            f"{'' if counted == 1 else 's'} where {BIB_FILE} gives the work "
                            f"{work.pages}: a preview, most likely")  # fmt: skip
                return None
        sha, size = digest(staged)
        version = VERSIONS.get(place.version or "") if place.kind == FROM_OPEN else None
        if place.kind == FROM_PUBLISHER:
            about = ("the publisher's PDF, through this computer's access, matched by its "
                     f"{shown.by}")
        else:
            about = (f"an open copy{f' ({version} version)' if version else ''}, from {where}, "
                     f"matched by its {shown.by}")  # fmt: skip
        # The URL asked, not the one the redirects ended at, which can carry a token.
        return Candidate(filed_name(work.key, ".pdf"), staged, place.kind, None, sha, size,
                         about=about, doi=work.doi, url=place.url, matched=shown.by,
                         version=version)  # fmt: skip

    # ---------------------------------------------------------------- the registries

    def _api(self, url: str, secret: dict[str, str], said: list[str], name: str) -> Any:
        """One registry's JSON answer, or None with the reason said."""
        self.pace(urlsplit(url).hostname or "")
        request = Request(url, secret=secret,
                          headers={"User-Agent": download.AGENT, "Accept": "application/json"})
        try:
            response: Response = self.transport(request, download.TIMEOUT_SECONDS)
        except download.Offline as exc:
            self.offline = str(exc)
            return None
        except NoAnswer as exc:
            said.append(f"{name} did not answer ({exc})")
            return None
        if response.status == 404:
            said.append(f"{name} does not know the DOI")
            return None
        if response.status != 200:
            said.append(f"{name} answered HTTP {response.status}")
            return None
        try:
            return json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            said.append(f"{name} answered with something other than JSON")
            return None

    def _openalex(self, work: Work, said: list[str]) -> dict[str, Any] | None:
        """OpenAlex's record of the work, asked once: its open copies and its abstract."""
        if work.key in self._records:
            return self._records[work.key]
        assert work.doi
        data = self._api(self.places.openalex + quote(work.doi, safe="/"),
                         {"api_key": self.openalex_key or ""}, said, "OpenAlex")  # fmt: skip
        record = data if isinstance(data, dict) and isinstance(data.get("id"), str) else None
        if data is not None and record is None:
            said.append("OpenAlex answered in a shape it does not document")
        self._records[work.key] = record
        return record

    def _get(self, url: str, said: list[str], where: str) -> download.Fetched | None:
        try:
            return download.get(url, self._paced, accept=ACCEPT)
        except download.Offline as exc:
            self.offline = str(exc)
            return None
        except NoAnswer as exc:
            said.append(f"{where}: {exc}")
            return None

    def _paced(self, request: Request, timeout: float) -> Response:
        self.pace(urlsplit(request.base).hostname or "")
        return self.transport(request, timeout)

    # ---------------------------------------------------------------- the abstract

    def _abstract(self, work: Work, said: list[str]) -> Candidate | None:
        """The work's abstract, Crossref's first, then OpenAlex's; None where neither has it."""
        if not work.doi:
            return None
        url = self.places.crossref + quote(work.doi, safe="/")
        data = self._api(url, {}, [], "Crossref")
        message = data.get("message") if isinstance(data, dict) else None
        text = jats_text(message.get("abstract")) if isinstance(message, dict) else None
        title = _title(message) if isinstance(message, dict) else None
        registry = "Crossref"
        if not text and not self.offline:
            url = self.places.openalex + quote(work.doi, safe="/")
            record = self._openalex(work, [])
            text = inverted_abstract(record.get("abstract_inverted_index")) if record else None
            title = title or (record or {}).get("title")
            registry = "OpenAlex"
        if not text:
            said.append("no abstract in Crossref or OpenAlex")
            return None
        heading = " ".join(str(title or work.title or "").split())
        body = (f"{heading}\n\n" if heading else "") + text + "\n"
        staged = self._stage(work.key, ".abstract.txt", body.encode("utf-8"))
        sha, size = digest(staged)
        return Candidate(filed_name(work.key, ".abstract.txt"), staged, FROM_ABSTRACT, None, sha,
                         size, about=f"its abstract only, as {registry} holds it",
                         doi=work.doi, url=url)  # fmt: skip

    def _stage(self, key: str, suffix: str, body: bytes) -> Path:
        if self._scratch is None:
            raise RuntimeError("a Fetcher stages its downloads only inside `with`")
        folder = Path(self._scratch.name)
        path = folder / filed_name(key, suffix)
        path.write_bytes(body)
        return path


def for_project(project: Project) -> Fetcher:
    """The fetcher `sync-sources` uses: each host asked at `lookup`'s pace, OpenAlex's key
    where the environment sets one, and never the contact address `lookup` sends Crossref."""
    from manuscript_guard.literature.copies import wanted_keys
    from manuscript_guard.lookup.run import Credentials, Pacer

    return Fetcher(
        works_of(project, wanted_keys(project)),
        transport=download.session(),
        openalex_key=Credentials.from_environment(project).openalex_key,
        pace=Pacer().wait,
    )


def _place(url: object, version: object) -> Place | None:
    if not isinstance(url, str) or not url.strip():
        return None
    return Place(url.strip(), FROM_OPEN, version if isinstance(version, str) else None)


def _pmcid(value: object) -> str | None:
    found = _PMCID.search(value) if isinstance(value, str) else None
    return found.group().upper() if found else None


def _title(message: dict[str, Any]) -> str | None:
    title = message.get("title")
    if isinstance(title, list):
        title = next((t for t in title if isinstance(t, str) and t.strip()), None)
    return title if isinstance(title, str) else None


def citation_pdf_url(body: bytes, base: str) -> str | None:
    """The PDF a page names for citation managers, `<meta name="citation_pdf_url"
    content="...">`, made absolute; None where it names none, or one that is not https."""
    page = body[: 2 << 20].decode("utf-8", errors="replace")
    for tag in _META.findall(page):
        attributes = {name.lower(): double or single
                      for name, double, single in _ATTRIBUTE.findall(tag)}  # fmt: skip
        if attributes.get("name", "").lower() == "citation_pdf_url" and attributes.get("content"):
            link = urljoin(base, html.unescape(attributes["content"].strip()))
            return link if download.allowed(link) else None
    return None


def jats_text(value: object) -> str | None:
    """Crossref's abstract, JATS XML, as plain text: its tags taken off, its heading too."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(html.unescape(_TAG.sub(" ", value)).split())
    text = re.sub(r"^(?:Abstract|Summary)\b[\s:.]*", "", text, flags=re.IGNORECASE)
    return text or None


def inverted_abstract(index: object) -> str | None:
    """OpenAlex's abstract, which it gives as each word with the positions it stands at."""
    if not isinstance(index, dict) or not index:
        return None
    placed: dict[int, str] = {}
    for word, positions in index.items():
        if isinstance(word, str) and isinstance(positions, list):
            for at in positions:
                if isinstance(at, int) and not isinstance(at, bool) and 0 <= at < 100_000:
                    placed[at] = word
    return " ".join(placed[at] for at in sorted(placed)) or None


@dataclass(frozen=True)
class Wanted:
    """A cited work whose full text is still to be had: from the user, or their browser."""

    key: str
    link: str | None
    title: str | None
    abstract: bool
    why: tuple[str, ...]
    in_bib: bool = True


def still_wanted(project: Project, keys: list[str], fetcher: Fetcher | None) -> list[Wanted]:
    """The works with no full text stored, in the order cited, each with its DOI link and why
    none was had. A copy the record lists that is on another computer counts as had."""
    from manuscript_guard.literature.copies import FOLDER, read_record

    folder = project.path("literature") / FOLDER
    try:
        recorded = read_record(project)
    except Exception:  # noqa: BLE001 - `sync` has read it already; a list is no place to fail
        recorded = {}
    elsewhere = {entry["key"] for name, entry in recorded.items() if ".abstract." not in name}
    works = fetcher.works if fetcher is not None else works_of(project, keys)
    wanted = []
    for key in keys:
        if has_full_text(folder, key) or key in elsewhere:
            continue
        work = works.get(key)
        abstract = (folder / filed_name(key, ".abstract.txt")).is_file()
        why = tuple(fetcher.why.get(key, ())) if fetcher is not None else ()
        title = " ".join((work.title or "").split()) if work else ""
        wanted.append(Wanted(key, work.link if work else None, title or None, abstract, why,
                             in_bib=work is not None))  # fmt: skip
    return wanted


def asked(wanted: list[Wanted], *, zotero: bool = True) -> list[str]:
    """What `sync-sources` prints for the works whose full text is still wanted; `zotero`
    where the copies were asked of Zotero, whose Connector is then a way to give them."""
    if not wanted:
        return []
    many = len(wanted) != 1
    lines = [
        f"Full text still wanted for {len(wanted)} cited work{'s' if many else ''}. Open "
        f"{'each' if many else 'its'} link in your browser, signed in through your library "
        "where it gives you access, and save the PDF where the page offers it; then run "
        "`manuscript-guard sync-sources --inbox <the folder it was saved to>`, which files "
        "each PDF that shows a cited work's DOI or title."
        + (" Or save it into Zotero with the Zotero Connector and run this again."
           if zotero else "")
    ]
    for one in wanted:
        where = one.link or (f'no DOI; find it by its title, "{one.title}"' if one.title
                             else "no DOI and no title to find it by" if one.in_bib
                             else f"not in {BIB_FILE}: add it, or find it by hand")  # fmt: skip
        # The reasons of a work with nothing stored are in the list of works with no copy
        # above; those of one with its abstract are said nowhere else.
        held = ("; ".join(("only its abstract is stored", *one.why)) if one.abstract
                else "nothing is stored")  # fmt: skip
        lines.append(f"  @{one.key}: {where} ({held})")
    return lines


__all__ = [
    "MOST_PLACES",
    "Fetcher",
    "Place",
    "Places",
    "Wanted",
    "Work",
    "asked",
    "citation_pdf_url",
    "for_project",
    "has_full_text",
    "inverted_abstract",
    "jats_text",
    "still_wanted",
    "work_of",
    "works_of",
]
