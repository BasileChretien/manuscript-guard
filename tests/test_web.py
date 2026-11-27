"""The in-browser audit page's side of the package (`manuscript_guard.web`): pandoc.wasm in
place of the pandoc on PATH, poppler's pdftotext and pdfinfo in WebAssembly in place of
those on PATH, and the transport a page sends lookups with.

The page itself, in Pyodide with the real pandoc.wasm and poppler, is held by CI's `web` job
(`web/test/`). Here pandoc.wasm is stood in for by pandoc run on a defaults file, which is
the object pandoc.wasm takes, so that what the translation sends is what pandoc reads; and
the page's `subprocess.run` is held to the real one, run on a program that prints the same.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import pytest
import yaml

from manuscript_guard import from_word, web
from manuscript_guard.cli import main
from manuscript_guard.contracts._schema import ContractError
from manuscript_guard.lookup import http
from manuscript_guard.lookup.http import NoAnswer, Request

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


# ------------------------------------------------------------------- the flags translated


def test_the_command_lines_from_word_passes_are_translated(tmp_path: Path) -> None:
    paper = tmp_path / "Paper.DOCX"
    call = web.pandoc_options([str(paper), "-f", "docx", "-t", "json",
                               f"--extract-media={tmp_path / 'm'}"])  # fmt: skip
    assert call.options == {"input-files": ["input.docx"], "from": "docx", "to": "json",
                            "extract-media": (tmp_path / "m").as_posix()}  # fmt: skip
    assert (call.source, call.media) == (paper, tmp_path / "m")

    call = web.pandoc_options(["-f", "json", *from_word.WRITER])
    assert call.options == {"from": "json", "to": "markdown-simple_tables-multiline_tables",
                            "wrap": "none", "columns": 100000}  # fmt: skip
    assert (call.source, call.media) == (None, None)

    assert web.pandoc_options([str(paper), "-f", "docx+styles", "-t", "json"]).options == {
        "input-files": ["input.docx"], "from": "docx+styles", "to": "json"}  # fmt: skip


@pytest.mark.parametrize(
    "arguments",
    [
        ["-f", "json", "--lua-filter=x.lua"],
        ["-f", "docx", "-s"],
        ["a.docx", "--track-changes=all"],
        ["a.docx", "b.docx"],
        ["-t"],
    ],
)
def test_a_command_line_not_translated_is_refused_not_trimmed(arguments: list[str]) -> None:
    """A flag dropped would convert the paper otherwise than the command line does, and the
    page would say nothing of it."""
    with pytest.raises(ContractError, match="pandoc.wasm"):
        web.pandoc_options(arguments)


# ---------------------------------------------------------------- what pandoc.wasm returns


def test_a_failure_in_the_wasm_is_said_as_pandocs_and_quotes_no_input(tmp_path: Path) -> None:
    def trapped(options, stdin, files):
        raise RuntimeError("unreachable executed at 0x1f00 with the paper's words in it")

    run = web.runner_for(trapped)
    with pytest.raises(ContractError) as caught:
        run(["-f", "json", "-t", "markdown"], "{}", tmp_path / "paper.docx")
    assert str(caught.value) == ("pandoc.wasm could not convert paper.docx, so nothing was "
                                 "made (RuntimeError)")  # fmt: skip


def test_pandocs_complaint_with_nothing_printed_is_a_failure(tmp_path: Path) -> None:
    run = web.runner_for(lambda options, stdin, files: ("", "Unknown input format docy\n", {}))
    with pytest.raises(ContractError, match="nothing was made: Unknown input format docy$"):
        run(["-f", "json", "-t", "markdown"], "{}", tmp_path / "paper.docx")
    warned = web.runner_for(lambda options, stdin, files: ("text\n", "[WARNING] a note\n", {}))
    assert warned(["-f", "json", "-t", "markdown"], "{}", tmp_path / "paper.docx") == "text\n"


def test_a_silent_failure_of_the_wasm_is_said_as_g6_and_g14_not_run_from_json(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The audit page"): pandoc.wasm's exit status is not
    read, so a failure with nothing on stderr reaches `json.loads`, and its ValueError is the
    note that G6 and G14 were not run; with its complaint on stderr, pandoc's own words are
    said."""
    from manuscript_guard.build import document

    def absent() -> str:
        raise document.BuildError("pandoc is not on PATH")

    monkeypatch.setattr(document, "pandoc", absent)
    paper = tmp_path / "paper.docx"
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(paper, "w") as archive:
        archive.writestr("word/document.xml", f"<?xml version='1.0'?><w:document {ns}><w:body>"
                         "<w:p><w:r><w:t>The ROR was 2.5.</w:t></w:r></w:p></w:body></w:document>")
    for stderr, said in (("", "Expecting value: line 1 column 1 (char 0)"),
                         ("Unknown input format docy\n", "pandoc could not convert paper.docx, "
                          "so nothing was made: Unknown input format docy")):  # fmt: skip
        monkeypatch.setattr(from_word, "runner", web.runner_for(
            lambda options, stdin, files, stderr=stderr: ("", stderr, {})))  # fmt: skip
        assert main(["audit", str(paper), "--json"]) == 0
        found = json.loads(capsys.readouterr().out)["findings"]
        assert [f["message"] for f in found if f["code"] == "gates-not-run"] == [
            f"G6 and G14 were not run on paper.docx: {said}"]


def test_the_pictures_extracted_are_saved_and_none_outside_the_folder(tmp_path: Path) -> None:
    paper = tmp_path / "paper.docx"
    paper.write_bytes(b"PK\x03\x04")
    folder = tmp_path / "out"
    # As pandoc.wasm names them, from the root of its own file system.
    inside = folder.as_posix().lstrip("/")
    seen = {}

    def convert(options, stdin, files):
        seen.update(files)
        return "{}", "", {
            f"{inside}/media/image1.png": b"png",
            f"{inside}/../escaped.png": b"no",
            f"{inside}/media/../../../far.png": b"no",
            "media/image2.png": b"no",
        }  # fmt: skip

    run = web.runner_for(convert)
    assert run([str(paper), "-f", "docx", "-t", "json", f"--extract-media={folder}"], None,
               paper) == "{}"  # fmt: skip
    assert seen == {"input.docx": b"PK\x03\x04"}
    assert (folder / "media" / "image1.png").read_bytes() == b"png"
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.png")) == [
        "out/media/image1.png"]  # fmt: skip


# ------------------------------------------------- the audit through the translation, whole


def _through_defaults(options: dict, stdin: str | None, files: dict[str, bytes]):
    """pandoc.wasm's `convert`, stood in for by pandoc reading `options` as a defaults file."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="mg-wasm-") as folder:
        root = Path(folder)
        for name, data in files.items():
            (root / name).write_bytes(data)
        (root / "defaults.json").write_text(json.dumps(options), encoding="utf-8")
        done = subprocess.run([shutil.which("pandoc"), "--defaults", "defaults.json"], cwd=root,
                              input=(stdin or "").encode("utf-8"), capture_output=True,
                              timeout=120, check=False)  # fmt: skip
        # pandoc saves the pictures where `extract-media` says, itself: nothing to hand back.
        return done.stdout.decode("utf-8"), done.stderr.decode("utf-8"), {}


def _png() -> bytes:
    """A picture of one pixel, so that the paper has media to extract."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (len(data).to_bytes(4, "big") + kind + data
                + zlib.crc32(kind + data).to_bytes(4, "big"))  # fmt: skip

    header = (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))  # fmt: skip


@needs_pandoc
def test_audit_through_the_translation_says_what_it_says_through_pandoc(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A title page (read again with its styles), a picture (extracted) and words G14 reads:
    every call `from_word` makes goes through the translation, with no pandoc on PATH."""
    (tmp_path / "dot.png").write_bytes(_png())
    (tmp_path / "paper.md").write_text(
        "A study of twelve cases\n\nAnne Author, Some Hospital\n\n# Methods\n\n"
        "The ROR was 2.5 in 12 cases.\n\n![The figure.](dot.png)\n", encoding="utf-8")
    subprocess.run(["pandoc", "paper.md", "-o", "paper.docx"], cwd=tmp_path, check=True,
                   timeout=120)  # fmt: skip
    paper = str(tmp_path / "paper.docx")
    assert main(["audit", paper, "--json"]) == 0
    through_pandoc = json.loads(capsys.readouterr().out)

    from manuscript_guard.build import document

    def absent() -> str:
        raise document.BuildError("pandoc is not on PATH")

    calls: list[list[str]] = []
    run = web.runner_for(_through_defaults)
    monkeypatch.setattr(document, "pandoc", absent)
    monkeypatch.setattr(from_word, "runner",
                        lambda arguments, given, path: calls.append(arguments) or run(
                            arguments, given, path))  # fmt: skip
    assert main(["audit", paper, "--json"]) == 0
    through_wasm = json.loads(capsys.readouterr().out)

    assert through_wasm == through_pandoc
    assert any(f["gate"] == "G14" and "ROR" in f["message"] for f in through_wasm["findings"])
    assert {tuple(c[1:4]) for c in calls if c[0] == paper} >= {
        ("-f", "docx", "-t"), ("-f", "docx+styles", "-t")}  # fmt: skip
    assert any(c[0].startswith("--extract-media=") or c[-1].startswith("--extract-media=")
               for c in calls)  # fmt: skip


def test_with_a_runner_set_a_docx_is_converted_without_pandoc_on_path(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from manuscript_guard.build import document

    def absent() -> str:
        raise document.BuildError("pandoc is not on PATH")

    monkeypatch.setattr(document, "pandoc", absent)
    tree = {"pandoc-api-version": [1, 23, 1], "meta": {}, "blocks": [
        {"t": "Header", "c": [1, ["methods", [], []], [{"t": "Str", "c": "Methods"}]]},
        {"t": "Para", "c": [{"t": "Str", "c": "The"}, {"t": "Space"}, {"t": "Str", "c": "ROR"},
                            {"t": "Space"}, {"t": "Str", "c": "was"}, {"t": "Space"},
                            {"t": "Str", "c": "2.5."}]}]}  # fmt: skip

    def runner(arguments, given, path):
        return json.dumps(tree) if arguments[arguments.index("-t") + 1] == "json" else (
            "# Methods\n\nThe ROR was 2.5.\n")  # fmt: skip

    monkeypatch.setattr(from_word, "runner", runner)
    paper = tmp_path / "paper.docx"
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    with zipfile.ZipFile(paper, "w") as archive:
        archive.writestr("word/document.xml", f"<?xml version='1.0'?><w:document {ns}><w:body>"
                         "<w:p><w:r><w:t>The ROR was 2.5.</w:t></w:r></w:p></w:body></w:document>")
    assert main(["audit", str(paper), "--json"]) == 0
    found = json.loads(capsys.readouterr().out)["findings"]
    assert not any(f["code"] == "gates-not-run" for f in found), found
    assert any(f["gate"] == "G14" and "ROR" in f["message"] for f in found), found


# ------------------------------------------------------------------- lookups from a page


class FakeXHR:
    """XMLHttpRequest as `xhr_transport` uses it."""

    def __init__(self, status=200, headers="", text="", raises: Exception | None = None):
        self.status, self._headers, self.responseText, self._raises = status, headers, text, raises
        self.opened = None
        self.sent_headers: dict[str, str] = {}
        self.timeout = None

    def open(self, method: str, url: str, asynchronous: bool) -> None:
        self.opened = (method, url, asynchronous)

    def setRequestHeader(self, name: str, value: str) -> None:  # noqa: N802 - the DOM's name
        self.sent_headers[name] = value

    def send(self) -> None:
        if self._raises is not None:
            raise self._raises

    def getAllResponseHeaders(self) -> str:  # noqa: N802 - the DOM's name
        return self._headers


REQUEST = Request("https://api.crossref.org/works/10.1/x", {"q": "1"},
                  secret={"mailto": "someone@example.org"},
                  headers={"User-Agent": "manuscript-guard/0", "Accept": "application/json"})


def test_a_page_sends_one_synchronous_get_without_the_user_agent() -> None:
    xhr = FakeXHR(200, "content-type: application/json\r\nretry-after: 3\r\nx-api-pool: public\r\n",
                  '{"status": "ok", "é": 1}')  # fmt: skip
    answer = web.xhr_transport(REQUEST, 30.0, new_xhr=lambda: xhr)
    assert xhr.opened == ("GET", REQUEST.url, False) and xhr.timeout == 30000
    assert xhr.sent_headers == {"Accept": "application/json"}
    assert answer.status == 200 and answer.body == '{"status": "ok", "é": 1}'.encode()
    # Named as urllib names them, which is how `lookup` asks for them.
    assert answer.headers == {"Content-Type": "application/json", "Retry-After": "3",
                              "X-Api-Pool": "public"}  # fmt: skip


@pytest.mark.parametrize(
    ("xhr", "said"),
    [
        (FakeXHR(0), "no connection to api.crossref.org"),
        (FakeXHR(raises=RuntimeError("NetworkError: refused by the policy")),
         "no connection to api.crossref.org"),
        (FakeXHR(raises=RuntimeError("TimeoutError: the request timed out")),
         "no answer within 30 s"),
    ],
)
def test_what_the_browser_refuses_is_no_answer_and_quotes_no_url(xhr: FakeXHR, said: str) -> None:
    with pytest.raises(NoAnswer) as caught:
        web.xhr_transport(REQUEST, 30.0, new_xhr=lambda: xhr)
    assert str(caught.value) == said
    assert "someone@example.org" not in str(caught.value) and "works" not in str(caught.value)


def test_a_status_that_is_not_2xx_is_an_answer() -> None:
    xhr = FakeXHR(404, "", "Resource not found.")
    answer = web.xhr_transport(REQUEST, 30.0, new_xhr=lambda: xhr)
    assert (answer.status, answer.body) == (404, b"Resource not found.")


def test_a_429_from_a_page_with_no_retry_after_is_not_waited_out() -> None:
    """A known gap (DESIGN.md, Known gaps, "The audit page"): Crossref does not expose
    `Retry-After` to a page, so its 429 is asked once and taken as no answer; where the
    header is seen, the wait it names is waited and the request sent again."""
    from manuscript_guard.lookup import run as lookup
    from manuscript_guard.lookup import sources

    for headers, asked, waits in (("content-type: application/json\r\n", 1, []),
                                  ("content-type: application/json\r\nretry-after: 3\r\n", 2,
                                   [3.0])):  # fmt: skip
        sent: list[str] = []
        waited: list[float] = []

        def transport(request: Request, timeout: float, headers: str = headers,
                      sent: list[str] = sent):  # fmt: skip
            sent.append(request.url)
            return web.xhr_transport(request, timeout,
                                     new_xhr=lambda: FakeXHR(429, headers, "{}"))  # fmt: skip

        ask = lookup._asker(transport, lookup.Pacer(clock=lambda: 0.0, sleep=waited.append),
                            lookup.Credentials())  # fmt: skip
        found = sources.crossref("10.5555/x", ask, lookup.Services().crossref, None)
        assert found == {"status": "unresolvable",
                         "why": "throttled (HTTP 429): asked too often, or past the allowance"}
        assert len(sent) == asked and waited[:1] == waits


@pytest.mark.parametrize("key", [None, "secret-openalex-key"])
def test_a_page_s_lookup_sends_a_key_only_where_its_environment_names_one(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, key: str | None
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The audit page"): `audit --lookup` on a page asks
    through the page's transport and reads `OPENALEX_API_KEY` from the environment as the
    command line does, so no key is sent where, as on a page, none is named."""
    opened: list[str] = []
    monkeypatch.setattr(sys, "platform", "emscripten")
    monkeypatch.setattr(web, "_new_xhr", lambda: FakeXHR(404, "", "{}"))
    monkeypatch.setattr(FakeXHR, "open", lambda self, method, url, sync: opened.append(url))
    for name in ("OPENALEX_API_KEY", "NCBI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    if key:
        monkeypatch.setenv("OPENALEX_API_KEY", key)
    paper = tmp_path / "paper.md"
    paper.write_text("# Results\n\nOf 40, 12 had it [1].\n\n# References\n\n1. Smith J. A "
                     "cohort. Lancet. 2019;393:100-10. doi:10.5555/fictional.1\n",
                     encoding="utf-8")  # fmt: skip
    assert main(["audit", str(paper), "--lookup", "--json"]) == 0
    capsys.readouterr()
    asked = "https://api.openalex.org/works/doi:10.5555/fictional.1"
    assert (asked + (f"?api_key={key}" if key else "")) in opened, opened
    assert [url for url in opened if "key" in url] == ([] if key is None else
                                                       [f"{asked}?api_key={key}"])  # fmt: skip


def test_a_page_sends_nothing_but_https() -> None:
    sent = []
    with pytest.raises(NoAnswer, match="refused to send a request to http://example.org"):
        web.xhr_transport(Request("http://example.org/x"), 30.0,
                          new_xhr=lambda: sent.append(1) or FakeXHR())  # fmt: skip
    assert sent == []


def test_in_pyodide_the_default_transport_is_the_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    taken = []
    monkeypatch.setattr(web, "xhr_transport", lambda request, timeout: taken.append(
        (request, timeout)) or "answered")  # fmt: skip
    monkeypatch.setattr(sys, "platform", "emscripten")
    assert http.default_transport(REQUEST, 12.0) == "answered"
    assert taken == [(REQUEST, 12.0)]


# ------------------------------------------------------------ the page's pins and its policy

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def test_the_page_runs_the_pandoc_ci_pins() -> None:
    """The page's reports are compared word for word with the command line's, under the
    pandoc CI installs: its pandoc.wasm is that release's."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pinned = re.search(r'MANUSCRIPT_GUARD_REQUIRE_PANDOC: "([^"]+)"', ci).group(1)
    pandoc = json.loads((WEB / "pins.json").read_text(encoding="utf-8"))["pandoc"]
    assert pandoc["version"] == pinned
    assert f"/{pinned}/" in pandoc["wasm"]["url"] and f"/{pinned}/" in pandoc["licence"]["url"]
    npm = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    # A version with a build of its own, "26.11.0-1", is as exact.
    assert all(re.fullmatch(r"\d+(\.\d+)+(-\d+)?", v)
               for part in ("dependencies", "devDependencies")
               for v in npm[part].values()), "web/package.json pins each version exactly"


def test_the_pages_pdftotext_is_the_build_the_lock_pins_with_its_source() -> None:
    """The page's pdftotext and pdfinfo are the npm package pins.json names, at the version
    web/package.json pins and package-lock.json holds to its SHA-512, under its licence; the
    page links to the poppler release it is built from and to the recipe that built it, at a
    commit (Basile, 2026-11-26: the pinned npm build)."""
    poppler = json.loads((WEB / "pins.json").read_text(encoding="utf-8"))["poppler"]
    npm = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((WEB / "package-lock.json").read_text(encoding="utf-8"))
    assert npm["dependencies"][poppler["package"]] == poppler["version"]
    entry = lock["packages"][f"node_modules/{poppler['package']}"]
    assert entry["version"] == poppler["version"] and entry["integrity"].startswith("sha512-")
    assert entry["license"] == poppler["licence"] == "GPL-2.0-only OR GPL-3.0-only"
    assert poppler["version"].startswith(poppler["upstream"] + "-")
    assert poppler["source"] == (
        f"https://poppler.freedesktop.org/poppler-{poppler['upstream']}.tar.xz")
    assert re.fullmatch(r"https://github\.com/ai-ecoverse/homescoop/tree/[0-9a-f]{40}/packages/"
                        r"poppler", poppler["recipe"])  # fmt: skip


def _policy() -> tuple[str, dict[str, list[str]]]:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', page).group(1)
    return page, {d.split()[0]: d.split()[1:] for d in policy.split(";") if d.strip()}


def test_the_pages_policy_names_the_hosts_lookup_asks_and_no_others() -> None:
    """A registry `--lookup` asks that the policy does not name is refused by the browser, and
    the page then says the work could not be looked up; a host it names that `--lookup` does
    not ask is a place the page could send to for nothing."""
    from dataclasses import fields
    from urllib.parse import urlsplit

    from manuscript_guard.auditing import registration
    from manuscript_guard.lookup.run import Services

    asked = {f"https://{urlsplit(getattr(Services(), f.name)).hostname}" for f in fields(Services)}
    # And the registries of the paper's own registration numbers (`auditing.registration`).
    asked |= {f"https://{urlsplit(base).hostname}" for base in registration.asked_at()}
    page, policy = _policy()
    assert set(policy["connect-src"]) == {"'self'", *asked}
    assert policy["default-src"] == ["'none'"]
    assert policy["script-src"] == ["'self'", "'wasm-unsafe-eval'"]
    # A worker from a file would run under no policy at all (web/worker.js).
    assert policy["worker-src"] == ["blob:"]
    # The one frame is the report's PDF, made in the page (2026-11-12): nothing from elsewhere.
    assert policy["frame-src"] == ["blob:"]
    assert policy["form-action"] == ["'none'"] and policy["base-uri"] == ["'none'"]
    # Read before anything is loaded, or what loads first is under no policy.
    assert page.index("Content-Security-Policy") < min(page.index("<script"), page.index("<link"))


def test_the_pages_workflow_asks_after_the_job_publish_tags_with() -> None:
    """pages.yml deploys where that job of the release run succeeded, found by its name: a
    name changed in one file and not the other would leave every release without its page,
    and nothing would fail."""
    workflows = ROOT / ".github" / "workflows"
    pages = (workflows / "pages.yml").read_text(encoding="utf-8")
    named = re.search(r'select\(\.name == "([^"]+)"', pages).group(1)
    publish = yaml.safe_load((workflows / "publish.yml").read_text(encoding="utf-8"))
    assert named in {job.get("name") for job in publish["jobs"].values()}
    assert 'workflows: ["Publish to PyPI"]' in pages and publish["name"] == "Publish to PyPI"


def test_the_pages_workflow_deploys_the_newest_tag_a_limit_known_gaps_names() -> None:
    """A limit (DESIGN.md, Known gaps, the audit page; round 2 of #527): where the release run
    tagged, the page is built from the newest `v` tag, which may be a later run's. A change to
    how the tag is chosen updates that entry."""
    pages = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "git tag --list 'v*' --sort=-v:refname | head -n 1" in pages
    design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    gaps = design.split("\n## Known gaps", 1)[1].split("Closed since, and why", 1)[0]
    assert "*The release a page is built from.*" in gaps


def _fields() -> set[str]:
    """The name of each box on the page, as it shows it in bold."""
    page = (WEB / "index.html").read_text(encoding="utf-8")
    found = re.findall(r'<span class="field">([^<]+)</span>', page)
    return {" ".join(name.split()) for name in found}


def test_each_box_the_report_names_is_a_box_on_the_page() -> None:
    """The report sends a reader of the page to a box by its name: "Words to leave alone",
    "English of the paper". A box renamed on the page and not in the report would send the
    reader to nothing (the author's audit, 2026-11-11). Every place of every finding is in
    the PDF the page shows, which no box asks for (2026-11-12)."""
    from manuscript_guard.auditing import gates, summary

    said = [gates.KNOWN, summary.DETAILS, gates.for_an_audit("Set english_variant: en-GB")]
    box = re.compile(r'on the (?:web )?page, (?:the box )?"([^"]+)"')
    named = {name for text in said for name in box.findall(text)}
    assert named == {"Words to leave alone", "English of the paper"}
    assert named <= _fields()
    assert "the PDF of the report" in summary.DETAILS


def test_the_page_says_its_release_from_the_manifest_the_build_writes() -> None:
    """The page says at its top which release it is (app.js, from manifest.json), where a
    reader sees that it was built again for a new one, and links to what that release changed:
    the keys it reads are the ones web/build.py writes, and the link is the tag's release."""
    app = (WEB / "app.js").read_text(encoding="utf-8")
    build = (WEB / "build.py").read_text(encoding="utf-8")
    assert 'fetch("manifest.json")' in app and "manifest.manuscript_guard" in app
    assert 'manifest.sources["manuscript-guard"].replace("/tree/", "/releases/tag/")' in app
    assert '"manuscript_guard": version,' in build
    assert 'f"https://github.com/BasileChretien/manuscript-guard/tree/v{version}"' in build


PAPER_WITH_A_DOI = (
    "# Abstract\n\nOf 250 students, 164 (66%) took part.\n\n# Results\n\n164 took part [1].\n\n"
    "# References\n\n1. Martin L. A study. J Invented Educ. 2021;4:12-19. doi:10.1234/abc.5\n"
)


def test_an_audit_says_each_step_as_it_starts_and_the_page_names_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The page shows what a check is doing and how long is left (the author, 2026-11-12), from
    each step the audit says as it starts (`auditing.progress`): read, numbers, words, each
    reference looked up with how many of how many, and the report, in that order. The page
    names every step the audit says and the three it adds itself, the PDF, the copy and the
    copy with tracked changes (B2), which the worker says before making them."""
    from manuscript_guard.auditing import progress
    from manuscript_guard.cli import main

    paper = tmp_path / "paper.md"
    paper.write_text(PAPER_WITH_A_DOI, encoding="utf-8")
    told: list[tuple[str, int, int]] = []
    monkeypatch.setattr(progress, "STEP", lambda key, done, total: told.append((key, done, total)))
    assert main(["audit", str(paper), "--lookup", "--dry-run"]) == 0
    capsys.readouterr()
    keys = list(dict.fromkeys(key for key, _done, _total in told))
    assert keys == list(progress.STEPS)
    assert ("lookup", 0, 1) in told
    app = (WEB / "app.js").read_text(encoding="utf-8")
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    named = set(re.findall(r"^  (\w+): \[\"", re.search(r"const STEPS = \{(.*?)\n\};", app, re.S)
                           .group(0), re.M))  # fmt: skip
    assert named == {*progress.STEPS, "pdf", "copy", "tracked"}
    assert all(f'told("{key}", 0, 0)' in worker for key in ("pdf", "copy", "tracked"))
    assert "progress.STEP = TOLD" in worker


def test_the_loading_bar_counts_each_step_the_worker_says() -> None:
    """The worker says each step of its start (worker.js `step`), in order, and the page
    counts as many before the first is said: a step added in one file and not the other
    would leave the steps miscounted. The bar is a percentage."""
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    page = (WEB / "index.html").read_text(encoding="utf-8")
    steps = re.search(r"const BOOT_STEPS = \[(.*?)\];", worker, re.S).group(1)
    count = len(re.findall(r'"[^"]+"', steps))
    assert re.findall(r"\bstep\((\d)\)", worker) == [str(at) for at in range(count)]
    assert f"const loading = {{ at: 0, of: {count}," in app
    assert '<progress id="progress" max="100" value="0"' in page


def test_the_bar_counts_the_bytes_the_build_says_the_worker_fetches() -> None:
    """The percentage is of the bytes the worker fetches while it starts, which web/build.py
    writes to the manifest as `bytes`: every file of Pyodide's but the two the worker imports
    as modules, the wheel, pandoc.wasm and poppler's programs. CI's browser check holds the
    count to what the browser received; here, that each side names the other's."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("web_build", WEB / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    worker = (WEB / "worker.js").read_text(encoding="utf-8")
    imported = set(re.findall(r'import\(BASE \+ "pyodide/([^"]+)"\)', worker))
    # pyodide.mjs imports pyodide.asm.mjs itself.
    assert imported == {"pyodide.mjs"} and set(build.IMPORTED) == {"pyodide.mjs", "pyodide.asm.mjs"}
    assert set(build.IMPORTED) <= set(build.PYODIDE_CORE)
    written = (WEB / "build.py").read_text(encoding="utf-8")
    assert '"bytes": sum(path.stat().st_size for path in fetching),' in written
    # pandoc.wasm and poppler's programs, each fetched by the worker and counted by the build.
    for folder, name in (("pandoc", "pandoc.wasm"), ("poppler", build.POPPLER_WASM)):
        assert f'fetch(BASE + "{folder}/{name}")' in worker
    assert 'out / "pandoc" / "pandoc.wasm",' in written
    assert 'out / "poppler" / POPPLER_WASM]' in written
    assert "loading.expected = manifest.bytes || 0;" in worker
    assert "self.fetch = counted;" in worker and "self.fetch = ownFetch;" in worker


# ------------------------------------------------------- the names the page gives a command

NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_worker_gives_the_command_line_each_name_as_the_reader_chose_it() -> None:
    """worker.js, run in Node with a stand-in for Pyodide (web/test/names.mjs): each file is
    written under the name it was chosen by and named so in the command, a name that starts
    with "-" passed as `./name`, two names the page once made one kept apart, and a name
    chosen twice, or one no file can have, refused before anything is written (round 2 of
    #527: no case ran this code outside a browser, and none covered a refusal)."""
    cases = [
        {"paper": "Mon article (v3).docx", "against": ["résultats 結果.json"]},
        {"paper": "-paper.docx", "against": ["-results.json"]},
        {"paper": "paper.docx", "against": ["résultats.json", "rèsultats.json"]},
        {"paper": "paper.docx", "against": ["results.json", "results.json"]},
        {"paper": "paper.docx", "against": ["a/b.json"]},
        {"paper": "..", "against": []},
        {"paper": "paper.docx", "against": [], "english": "british",
         "known": ["CD", "-x", "licence"]},
        {"paper": "paper.docx", "against": [], "noAbstract": True, "noResults": True,
         "results": "-4. Electron temperature relations"},
        {"paper": "paper.docx", "against": [], "design": "trial",
         "wholeNumbers": ["Pain score", " ", "-x"], "binary": ["Female"],
         "nonNegative": ["Length of stay", "Weight"], "minimumCellCount": "11",
         "tracked": True},
        {"paper": "paper.md", "against": [], "design": "cohort", "minimumCellCount": "0",
         "tracked": True},
        {"paper": "paper.docx", "against": [], "minimumCellCount": "5; rm"},
    ]
    done = subprocess.run([NODE, str(WEB / "test" / "names.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    (kept, dashed, apart, twice, slash, dots, settings, answers, referee, not_docx,
     not_a_count) = json.loads(done.stdout)
    assert kept == {"args": ["audit", "Mon article (v3).docx", "--against", "résultats 結果.json"],
                    "written": ["/work/Mon article (v3).docx", "/work/résultats 結果.json"],
                    "corrected": False, "made": {}}
    assert dashed == {"args": ["audit", "./-paper.docx", "--against", "./-results.json"],
                      "written": ["/work/-paper.docx", "/work/-results.json"],
                      "corrected": False, "made": {}}
    assert apart["written"] == ["/work/paper.docx", "/work/résultats.json", "/work/rèsultats.json"]
    assert "two of the files chosen are named results.json" in twice["error"]
    assert 'cannot use a file named "a/b.json"' in slash["error"]
    assert 'cannot use a file named ".."' in dots["error"]
    assert twice["written"] == slash["written"] == dots["written"] == []
    # The English and the words to leave alone, a word that would be read as an option left
    # out (the author's audit, 2026-11-10).
    assert settings["args"] == ["audit", "paper.docx", "--english", "british", "--known", "CD",
                                "licence"]
    # The answers to the report's questions, a heading that starts with "-" joined to its
    # flag, so that it is read as the heading (decision 27).
    assert answers["args"] == ["audit", "paper.docx", "--no-abstract", "--no-results",
                               "--results=-4. Electron temperature relations"]
    # A referee's or an editor's: the design, each kind of row once with its labels, a blank
    # line and a label read as an option left out, the custodian's minimum; and for a .docx
    # the tracked copy asked for, which has the audit work out G14's corrections (B2).
    assert referee["args"] == ["audit", "paper.docx", "--design", "trial", "--whole-numbers",
                               "Pain score", "--binary", "Female", "--non-negative",
                               "Length of stay", "Weight", "--minimum-cell-count", "11"]
    assert referee["corrected"] is True
    # A design `audit` does not take, a count of 0, and a tracked copy of a paper that is no
    # .docx are not passed on; nor is anything but a whole number as the minimum.
    assert not_docx == {"args": ["audit", "paper.md"], "written": ["/work/paper.md"],
                        "corrected": False, "made": {}}
    assert not_a_count["args"] == ["audit", "paper.docx"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_worker_holds_the_paper_to_the_journal_the_form_or_a_file_describes() -> None:
    """The journal's form made into the files `--journal` and `--authors` read
    (`web.journal_files`), under the names the page gives them; a profile or an authors file
    of the reader's, under its own name and in place of the form; a file chosen under the
    name the form's would have, or a form that cannot make one, refused before anything is
    written."""
    form = {"name": "Journal of Tests", "date": "2026-11-25"}
    cases = [
        {"paper": "paper.docx", "against": [], "journal": form,
         "authors": {"authors": [{"given": "Ada", "family": "Example"}]}},
        {"paper": "paper.docx", "against": [], "journal": form, "journalFile": "-mine.yaml",
         "authors": {"authors": []}, "authorsFile": "people.yaml"},
        {"paper": "paper.docx", "against": ["journal.yaml"], "journal": form},
        {"paper": "paper.docx", "against": ["journal.yaml"], "authors": {"authors": []}},
        {"paper": "paper.docx", "against": [], "journal": {"name": "refused"}},
        {"paper": "paper.docx", "against": [], "journalFile": "results.json",
         "authorsFile": "results.json"},
    ]
    done = subprocess.run([NODE, str(WEB / "test" / "names.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    made, own, clash, beside, refused, twice = json.loads(done.stdout)
    assert made["args"] == ["audit", "paper.docx", "--journal", "journal.yaml", "--authors",
                            "authors.yaml"]
    assert made["written"] == ["/work/paper.docx", "/work/journal.yaml", "/work/authors.yaml"]
    assert made["made"] == {"journal.yaml": "profile\n", "authors.yaml": "authors\n"}
    assert own["args"] == ["audit", "paper.docx", "--journal", "./-mine.yaml", "--authors",
                           "people.yaml"]
    assert own["written"] == ["/work/paper.docx", "/work/-mine.yaml", "/work/people.yaml"]
    assert own["made"] == {}
    assert "a file chosen is named journal.yaml" in clash["error"]
    assert "journal's profile it makes" in clash["error"]
    # An output named journal.yaml is no clash where the form makes no profile.
    assert beside["args"] == ["audit", "paper.docx", "--against", "journal.yaml", "--authors",
                              "authors.yaml"]
    assert refused["error"] == "the journal's form: a test"
    assert "two of the files chosen are named results.json" in twice["error"]
    assert clash["written"] == refused["written"] == twice["written"] == []


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_worker_gives_the_audit_the_folder_an_archive_is_unpacked_into() -> None:
    """A LaTeX project as a .zip or a .tar.gz, written outside the folder the audit reads and
    unpacked into a folder of it named after the archive (`web.unpack_paper`): the audit is
    given that folder, as the command line is given the one the reader unpacks, and no copy
    of a .docx is asked for. An output named as that folder, or an archive refused, stops
    the run with its reason."""
    cases = [
        {"paper": "project.zip", "against": ["results.json"], "tracked": True},
        {"paper": "-paper.tar.gz", "against": []},
        {"paper": "project.tgz", "against": ["project"]},
        {"paper": "bad.zip", "against": []},
    ]
    done = subprocess.run([NODE, str(WEB / "test" / "names.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    zipped, dashed, clash, refused = json.loads(done.stdout)
    assert zipped["args"] == ["audit", "project", "--against", "results.json"]
    assert zipped["written"] == ["/upload/project.zip", "/work/results.json"]
    assert zipped["corrected"] is False
    assert dashed["args"] == ["audit", "./-paper"]
    assert "a file chosen is named project, the name of the folder project.tgz is unpacked" \
        in clash["error"]
    assert clash["written"] == []
    assert refused["error"] == "bad.zip: a test"


def test_each_statement_the_form_offers_is_a_box_on_the_page() -> None:
    """The page's ticks for the statements a journal requires are the ones `journal_form`
    makes a pattern for, no more and no fewer, each with its box for the heading the journal
    asks for, which offers the usual one (Basile, 2026-11-25)."""
    from manuscript_guard.journal_form import STATEMENTS

    page = (WEB / "index.html").read_text(encoding="utf-8")
    ticked = re.findall(r'name="jstatement" value="([^"]+)" id="jst-\1"', page)
    assert ticked == list(STATEMENTS)
    shown = re.findall(r'name="jstatement" value="[^"]+" id="[^"]+" disabled><span>([^<]+)<', page)
    assert shown == [statement.shown for statement in STATEMENTS.values()]
    offered = dict(re.findall(r'<input id="jsh-([^"]+)" type="text" value="([^"]+)"', page))
    assert offered == {key: one.heading for key, one in STATEMENTS.items()}


def test_the_page_makes_the_journal_files_or_says_why_not() -> None:
    """`web.journal_files`, which the worker calls: the text of each file asked for, as
    `journal_form` writes it, or why the form cannot make one."""
    from manuscript_guard import journal_form

    form = {"date": "2026-11-25", "statements": ["funding"]}
    people = {"authors": [{"given": "Ada", "family": "Example"}]}
    said = web.journal_files(form, people)
    assert said == {"profile": journal_form.as_text(journal_form.profile_of(form)),
                    "authors": journal_form.as_text(journal_form.authors_of(people))}
    assert web.journal_files(None, None) == {}
    assert web.journal_files({"date": "soon"}, None) == {
        "error": "the date the instructions were read on is no date: 'soon'"}


# ------------------------------------------------------ a link with the journal's rules


def _deflated(text: str) -> str:
    """`text` as web/rules.js `packed` writes a form: raw deflate, then base64url, unpadded."""
    import base64
    import zlib

    squeezer = zlib.compressobj(9, zlib.DEFLATED, -15)
    data = squeezer.compress(text.encode("utf-8")) + squeezer.flush()
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _rules(cases: list[dict]) -> list[dict]:
    done = subprocess.run([NODE, str(WEB / "test" / "rules.mjs")], input=json.dumps(cases),
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_link_carries_the_form_s_rules_and_nothing_else() -> None:
    """The form's values packed into the link after "#rules=" (web/rules.js; Basile,
    2026-11-26, "A link with the rules") come back as they were, as plain raw deflate in
    base64url, so that the link is read the same anywhere; and the page that opens it fills
    the form only from what the form has a box for."""
    import base64
    import zlib

    form = {"name": "Journal of Tests", "url": "https://example.org/authors",
            "date": "2026-11-27", "limits": {"abstract_words": "250", "figures": ""},
            "sections": ["Introduction", "Méthodes"], "abstract_headings": [],
            "statements": ["funding"], "headings": {"funding": "Funding or Financement"},
            "blinding": "double"}  # fmt: skip
    (packed,) = _rules([{"pack": form}])
    text = packed["text"]
    assert set(text) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    assert json.loads(zlib.decompress(raw, -15)) == form
    (back, made_here) = _rules([{"unpack": text}, {"unpack": _deflated(json.dumps(form))}])
    assert back == made_here == {"form": form}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_link_this_page_did_not_make_is_refused_with_why() -> None:
    """A link cut short, typed over, longer than any journal's rules, or unpacking to more
    than any form holds (a small link that unpacks to megabytes), fills nothing."""
    from_page = "it is not a link this page made"
    huge = _deflated(json.dumps({"name": " " * 70000}))
    assert len(huge) < 1000
    said = _rules([{"unpack": ""}, {"unpack": "abc$"}, {"unpack": "A"},
                   {"unpack": "AAAA" * 5000}, {"unpack": "eyJuYW1lIjoiYSJ9"},
                   {"unpack": _deflated("not json")}, {"unpack": huge}])
    assert said[:6] == [{"error": from_page}] * 6
    assert said[6] == {"error": "it holds more than any journal's rules"}
    # A form the page could fill packs short and unpacks to too much, which is why the button
    # holds a link to both (round 4 of #847).
    from manuscript_guard.journal_form import BLINDINGS, LIMITS, STATEMENTS

    long = {"date": "2026-11-27", "sections": ["a" * 2000] * 100}
    offered = {"limits": list(LIMITS), "statements": list(STATEMENTS),
               "blindings": list(BLINDINGS)}  # fmt: skip
    (packed, shape) = _rules([{"pack": long}, {"shape": long, "offered": offered}])
    assert shape == {"wrong": ""}, "the form's shape takes it, so only the byte count refuses it"
    assert len(packed["text"]) <= 16000 < 65536 < len(json.dumps(long).encode("utf-8"))
    assert _rules([{"unpack": packed["text"]}]) == [
        {"error": "it holds more than any journal's rules"}]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_a_link_s_rules_are_held_to_the_form_s_shape() -> None:
    """Only the boxes the form has, each holding what its box can hold, and the limits,
    statements and reviews it offers; the profile's schema is then the checker's to apply
    (`web.journal_files`, as for a profile the reader chooses)."""
    from manuscript_guard.journal_form import BLINDINGS, LIMITS, STATEMENTS

    offered = {"limits": list(LIMITS), "statements": list(STATEMENTS),
               "blindings": list(BLINDINGS)}  # fmt: skip
    good = {"name": "J", "date": "2026-11-27", "statements": ["funding"],
            "headings": {"funding": "Funding"}, "limits": {"tables": "4"}, "blinding": "open"}
    cases = [good, [], "text", {**good, "authors": [{"family": "Example"}]},
             {**good, "name": 7}, {**good, "sections": "Introduction"},
             {**good, "sections": ["x"] * 101}, {**good, "limits": {"pages": "10"}},
             {**good, "limits": {"tables": 4}}, {**good, "statements": ["secrets"]},
             {**good, "headings": {"ethics": "Ethics"}}, {**good, "blinding": "secret"},
             {**good, "name": "x" * 2001},
             # What a box would hold otherwise than given (round 1 of #847).
             {**good, "name": "A\nB"}, {**good, "limits": {"tables": " 4"}},
             {**good, "sections": ["Intro\nMethods"]}]
    said = [one["wrong"] for one in _rules([{"shape": case, "offered": offered}
                                            for case in cases])]  # fmt: skip
    assert said[0] == ""
    assert said[1] == said[2] == "it holds no journal's rules"
    assert said[3] == 'it holds "authors", which the form has no box for'
    assert said[4] == said[12] == said[13] == "its name is not a text the form can hold"
    assert said[5] == said[6] == said[15] == "its sections are not lines the form can hold"
    assert said[7] == 'it gives a limit on "pages", which the form has no box for'
    assert said[8] == said[14] == "a limit it gives is not a number the form can hold"
    assert said[9] == 'it asks for a statement "secrets", which the form has no box for'
    assert said[10] == 'it gives a heading for "ethics", a statement it does not ask for'
    assert said[11] == 'its review is "secret", which the form does not offer'


def test_the_page_offers_the_limits_and_reviews_the_profile_takes() -> None:
    """The boxes a link's rules are held to are the ones `journal_form` reads (app.js
    `LIMIT_BOXES`, the review's choices in index.html)."""
    from manuscript_guard.journal_form import BLINDINGS, LIMITS

    app = (WEB / "app.js").read_text(encoding="utf-8")
    boxes = re.search(r"const LIMIT_BOXES = \{([^}]*)\}", app)
    assert boxes is not None
    assert re.findall(r"(\w+): \"", boxes.group(1)) == list(LIMITS)
    page = (WEB / "index.html").read_text(encoding="utf-8")
    chosen = re.search(r'<select id="jblinding"[^>]*>(.*?)</select>', page, re.DOTALL)
    assert chosen is not None
    assert re.findall(r'<option value="(\w+)">', chosen.group(1)) == list(BLINDINGS)


def test_the_page_reads_its_address_for_the_rules_and_never_writes_it() -> None:
    """app.js reads "#rules=" from its own address and sets no part of it: no assignment to
    `location`, no `history` call, nothing kept in storage (docs/audit-page.md: the page's
    code does not set its address, and keeps nothing between visits)."""
    code = "\n".join((WEB / name).read_text(encoding="utf-8")
                     for name in ("app.js", "rules.js", "worker.js"))  # fmt: skip
    assert "location.hash" in code
    for written in (r"\blocation(\.\w+)?\s*=[^=]", r"\bhistory\.", r"localStorage",
                    r"sessionStorage", r"indexedDB", r"document\.cookie",
                    r"location\.(assign|replace)"):
        assert not re.search(written, code), written


# --------------------------------------------------------------------- a command, printed


def test_run_returns_the_exit_code_and_what_was_printed() -> None:
    from manuscript_guard import __version__

    assert web.run(["--version"]) == {"code": 0, "out": f"{__version__}\n", "err": ""}
    refused = web.run(["audit"])
    assert refused["code"] != 0 and "name a paper" in refused["err"]


def test_the_page_draws_the_report_its_text_is_printed_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page draws the report (`web.view`) from the very audit whose text it prints, so
    the two say one thing: what each check found, the findings on the words a fold per kind
    with every place in it, the other sections with something to show. A run asked for as
    JSON, or refused before its report was made, draws nothing, and the seam is let go."""
    import json

    from manuscript_guard import cli

    monkeypatch.chdir(tmp_path)
    undefined = ("ROR", "PRR", "EBGM", "SDR", "BCPNN", "MGPS", "OMOP", "FAERS", "VAERS", "ICSR")
    (tmp_path / "paper.md").write_text(
        "# Methods\n\n" + " ".join(f"The {short} was computed." for short in undefined)
        + " It was done, highlighting the importance of the method."
        # A kind of G14's, now the short forms never defined are a question (decision 30).
        + " The ICU was full. The intensive care unit (ICU) was busy."
        + "\n\n| Group | n |\n|---|---|\n| A | 3 |\n| B | 4 |\n| Total | 9 |\n",
        encoding="utf-8")  # fmt: skip
    result = web.view(["audit", "paper.md"])
    assert result["out"] == web.run(["audit", "paper.md"])["out"]
    view = json.loads(json.dumps(result))["view"]
    assert [name for name, _said in view["checks"]][:2] == ["Numbers in the outputs", "Arithmetic"]
    # One question for the ten short forms, asked apart with the other questions and no
    # kind of finding on the words, answered in the page's box (decision 30).
    assert not [kind for paper in view["words"] for kind in paper["kinds"]
                if kind["code"] == "abbreviation-undefined"]  # fmt: skip
    (asked,) = [said for heading, notes in view["notes"] if heading.startswith("Questions")
                for said in notes if "never defined" in said]  # fmt: skip
    assert asked.startswith("paper.md, line 3: 10 short forms are used and never defined")
    assert asked.endswith('give those they know in "Words to leave alone".'), asked
    headings = [heading for heading, _text in view["sections"]]
    assert "Arithmetic" in headings and not any("Language (G14)" in h for h in headings)
    assert web.view(["audit", "paper.md", "--json"])["view"] is None
    assert web.view(["audit"])["view"] is None
    assert cli.AUDITED is None
    # Round 1 of #601: the box draws every section; a run whose draft could not be written
    # printed no report and draws none; a view that cannot be drawn leaves the text.
    full = web.view(["audit", "paper.md", "--details"])["view"]
    assert {"Numbers in the outputs", "Small cells recoverable by subtraction"} <= {
        heading for heading, _text in full["sections"]}
    (tmp_path / "draft.md").write_text("here already\n", encoding="utf-8")
    assert web.view(["audit", "paper.md", "--report-draft", "draft.md"])["view"] is None
    from manuscript_guard.auditing import report as report_module

    def broken(*_args, **_kwargs):
        raise RuntimeError("no view")

    # Round 2: without the box a fold quotes G6's matched words only, G14's message naming
    # its word; with it, every context, as the text gives them.
    def contexts(drawn: dict, code: str) -> list:
        return [place["context"] for paper in drawn["words"] for kind in paper["kinds"]
                if kind["code"] == code for place in kind["places"]]  # fmt: skip

    assert contexts(view, "ai-phrasing") and all(contexts(view, "ai-phrasing"))
    assert contexts(view, "abbreviation-used-before-defined") == [None]
    assert all(contexts(full, "abbreviation-used-before-defined"))
    # Under DEBUG a view that cannot be drawn raises, as `main` does; without it, the text is
    # kept. A text that cannot be rendered draws no view either.
    drawn = report_module.view
    monkeypatch.setattr(report_module, "view", broken)
    with pytest.raises(RuntimeError, match="no view"):
        web.view(["audit", "paper.md"])
    assert cli.AUDITED is None
    monkeypatch.delenv("MANUSCRIPT_GUARD_DEBUG")
    kept = web.view(["audit", "paper.md"])
    assert kept["view"] is None and kept["out"] == result["out"]
    assert cli.AUDITED is None
    monkeypatch.setattr(report_module, "view", drawn)
    monkeypatch.setattr(report_module, "render", broken)
    unprinted = web.view(["audit", "paper.md"])
    assert unprinted["code"] != 0 and unprinted["view"] is None


def test_the_page_writes_the_commented_copy_from_the_audit_it_drew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page saves the paper with its findings as Word comments (`web.commented`), from
    the audit `view` ran, as `audit --commented` writes it; nothing for a paper that is no
    .docx, or before any audit."""
    from generated import word_package

    from manuscript_guard.docxtext import comment_ranges

    monkeypatch.chdir(tmp_path)
    web._AUDITED.clear()
    assert web.commented("paper.docx", "out.docx") == {"error": "no audit was run"}
    body = ("<w:p><w:pPr><w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Abstract</w:t></w:r>"
            "</w:p><w:p><w:r><w:t>Of the patients, 412 improved.</w:t></w:r></w:p><w:p><w:pPr>"
            "<w:pStyle w:val='Heading1'/></w:pPr><w:r><w:t>Results</w:t></w:r></w:p><w:p><w:r>"
            "<w:t>Of the patients, 40 improved.</w:t></w:r></w:p>")  # fmt: skip
    styles = ("<w:styles xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
              "<w:style w:type='paragraph' w:styleId='Heading1'><w:name w:val='heading 1'/>"
              "</w:style></w:styles>")  # fmt: skip
    with zipfile.ZipFile(tmp_path / "paper.docx", "w") as archive:
        for name, part in {**word_package(body), "word/styles.xml": styles}.items():
            archive.writestr(name, part)
    assert web.view(["audit", "paper.docx"])["view"] is not None
    said = web.commented("paper.docx", str(tmp_path / "out.docx"))
    assert said["placed"] >= 1, said
    assert "412" in comment_ranges(tmp_path / "out.docx").values()
    (tmp_path / "paper.md").write_text("# Results\n\nOf 40, 12.\n", encoding="utf-8")
    assert web.commented("paper.md", "out2.docx") == {"error": "paper.md is not a .docx"}


@needs_pandoc
def test_the_page_writes_the_tracked_copy_from_the_audit_it_drew(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """The copy the reader ticks the box for (B2): from the audit `view` ran with G14's
    corrections worked out, each a tracked change, as many as `audit --tracked` writes, the
    other findings comments worded for the page; the report the same as without them. An
    audit run without them gives no tracked copy, rather than one with none tracked."""
    from test_audit_tracked import docx, heading, para, read

    from manuscript_guard import cli

    monkeypatch.chdir(tmp_path)
    body = (heading("Methods")
            + para("The behaviour of the cohort was studied, and its colour was noted.")
            + heading("Results")
            + para("The change was seen (P=0.03) in the last of them."))  # fmt: skip
    paper = docx(tmp_path / "paper.docx", body)
    arguments = ["audit", "paper.docx", "--english", "american"]
    plain = web.view(arguments)
    assert web.commented("paper.docx", str(tmp_path / "none.docx"), tracked=True) == {
        "error": "the audit worked out no corrections"}
    drawn = web.view(arguments, corrected=True)
    assert cli.CORRECTED is False
    assert {k: drawn[k] for k in ("code", "out", "err")} == {
        k: plain[k] for k in ("code", "out", "err")}
    said = web.commented("paper.docx", str(tmp_path / "page.docx"), tracked=True)
    assert main([*arguments, "--tracked", str(tmp_path / "cli.docx")]) == 0
    err = capsys.readouterr().err
    assert f"{said['tracked']} corrections as tracked changes" in err, (said, err)
    assert said["tracked"] == 2 and said["left"] == 0
    assert read(tmp_path / "page.docx", accept=True) == read(tmp_path / "cli.docx", accept=True)
    assert read(tmp_path / "page.docx", accept=False) == read(paper)


# ---------------------------------------------------------- poppler's programs on the page

#: A program that writes what it is given, as bytes, and exits with the code given.
_CHILD = ("import sys\n"
          "sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))\n"
          "sys.stderr.buffer.write(bytes.fromhex(sys.argv[2]))\n"
          "sys.exit(int(sys.argv[3]))\n")  # fmt: skip
#: What a program prints that `subprocess.run` makes something of: line ends of each kind, a
#: form feed between pages, and bytes that are not UTF-8.
_PRINTED = (b"page one\r\nline\rlast\n\x0cpage two \xff\xfe\n", b"Syntax Warning: \xe9\r\n")


@pytest.mark.parametrize("options", [
    {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace"},
    {"capture_output": True},
    {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "encoding": "latin-1"},
    {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace",
     "check": True},
])  # fmt: skip
@pytest.mark.parametrize("code", [0, 3])
def test_the_pages_programs_give_what_subprocess_run_gives(options: dict, code: int) -> None:
    """What the package reads of a program on the page is what `subprocess.run` gives it of
    the program on a computer: its exit code, and what it printed, as bytes or decoded with
    each line end read as `subprocess.run` reads it, and a failure raised where `check` is
    set. Each of the ways the package calls pdftotext and pdfinfo is among these."""
    out, err = _PRINTED

    def program(name: str, args: list[str], cwd: str) -> tuple[int, bytes, bytes]:
        assert (name, args, cwd) == ("pdftotext", ["-enc", "UTF-8", "paper.pdf", "-"],
                                     os.getcwd())  # fmt: skip
        return code, out, err

    on_page = web.program_runner(program, fallback=None)
    command = [sys.executable, "-c", _CHILD, out.hex(), err.hex(), str(code)]
    try:
        expected = subprocess.run(command, timeout=60, **options)
    except subprocess.CalledProcessError as exc:
        expected = exc
    try:
        given = on_page(["pdftotext", "-enc", "UTF-8", "paper.pdf", "-"], timeout=60, **options)
    except subprocess.CalledProcessError as exc:
        given = exc
    assert type(given) is type(expected)
    assert (given.returncode, given.stdout, given.stderr) == (
        expected.returncode, expected.stdout, expected.stderr)


def test_another_program_goes_to_subprocess_run_and_one_found_elsewhere_too(
    tmp_path: Path,
) -> None:
    """Only pdftotext and pdfinfo, by their names or their files in the page's folder, are the
    page's: any other command is handed on as it was given, and so is a pdftotext found
    anywhere else, which is not the one the page runs."""
    handed = []

    def fallback(args, *rest, **options):
        handed.append((args, rest, options))
        return "handed"

    def program(name, args, cwd):
        # Text, as a program's arguments are, which the page hands over to JavaScript.
        assert all(type(arg) is str for arg in args), args
        return 0, name.encode(), b""

    run = web.program_runner(program, fallback, folder=str(tmp_path))
    assert run(["pandoc", "-v"], capture_output=True) == "handed"
    assert run("pdftotext -v", shell=True) == "handed"
    assert run([str(tmp_path / "other" / "pdftotext"), "-v"], capture_output=True) == "handed"
    assert handed == [(["pandoc", "-v"], (), {"capture_output": True}),
                      ("pdftotext -v", (), {"shell": True}),
                      ([str(tmp_path / "other" / "pdftotext"), "-v"], (),
                       {"capture_output": True})]  # fmt: skip
    assert run([str(tmp_path / "pdfinfo"), "x.pdf"], capture_output=True).stdout == b"pdfinfo"
    # The command as it was given, as `subprocess.run` keeps it; the program is given text.
    given = [Path("pdftotext"), Path("paper.pdf"), "-"]
    assert run(given, capture_output=True).args is given


@pytest.mark.parametrize("options, said", [
    ({"capture_output": True, "input": b"x"}, "takes no input"),
    ({"capture_output": True, "cwd": "/elsewhere"}, "takes no cwd"),
    ({"capture_output": True, "env": {}}, "takes no env"),
    ({}, "takes no output it does not capture"),
    ({"stdout": subprocess.PIPE}, "takes no output it does not capture"),
])  # fmt: skip
def test_a_run_the_page_cannot_give_as_a_computer_would_is_refused(options: dict,
                                                                  said: str) -> None:
    """A program run otherwise than the package runs it would be given what the page does not
    give it (its standard input, another folder, another environment) or print where nothing
    reads it: refused, as a program that cannot be run is, rather than run otherwise."""
    run = web.program_runner(lambda name, args, cwd: pytest.fail("it was run"), fallback=None)
    with pytest.raises(OSError, match=said):
        run(["pdftotext", "paper.pdf", "-"], **options)


def test_a_run_longer_than_its_timeout_is_said_as_one_once_it_ends() -> None:
    """The page cannot stop a program under way, which runs in its own thread: one that took
    longer than the command line waits is said as the command line says one it stopped."""
    import time

    def slow(name, args, cwd):
        time.sleep(0.05)
        return 0, b"text", b""

    run = web.program_runner(slow, fallback=None)
    with pytest.raises(subprocess.TimeoutExpired):
        run(["pdftotext", "paper.pdf", "-"], capture_output=True, timeout=0.01)
    assert run(["pdftotext", "paper.pdf", "-"], capture_output=True, timeout=60).stdout == b"text"


@pytest.mark.skipif(os.name == "nt", reason="shutil.which finds no file without an extension")
def test_with_the_programs_put_a_pdf_is_read_through_them_by_the_command_lines_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`put_programs` gives this Python pdftotext and pdfinfo as a computer has them: each found
    on PATH, first, as `shutil.which` finds a program, and run by `subprocess.run`. The code
    that reads a PDF is the command line's, unchanged: it asks which pdftotext it is, reads
    the PDF in both orders and asks pdfinfo its author, each with the arguments it gives the
    program on a computer, from the folder it runs in."""
    from manuscript_guard.auditing import pdf, pdf_layout

    monkeypatch.setattr(subprocess, "run", subprocess.run)
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    monkeypatch.delenv(pdf_layout.POPPLER, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.4\n% read by the stand-in\n")
    folder = tmp_path / "bin"
    calls = []

    def program(name: str, args: list[str], cwd: str) -> tuple[int, bytes, bytes]:
        calls.append((name, args, cwd))
        if args == ["-v"]:
            return 0, b"", (b"pdftotext version 26.11.0\nCopyright 2005-2026 The Poppler "
                            b"Developers - http://poppler.freedesktop.org\n")  # fmt: skip
        if name == "pdfinfo":
            return 0, b"Title:  A paper\nAuthor:  Ada Example\nPages:  1\n", b""
        page = ("Methods\nWe studied 120 patients.\n" if "-raw" in args else
                "Methods\nWe studied 120 patients.\nResults\nThe ROR was 2.5.\n")  # fmt: skip
        return 0, page.encode(), b""

    web.put_programs(program, str(folder))
    assert os.environ["PATH"].split(os.pathsep)[0] == str(folder)
    assert shutil.which("pdftotext") == str(folder / "pdftotext")
    assert shutil.which("pdfinfo") == str(folder / "pdfinfo")
    read = pdf.read_pdf(Path("paper.pdf"))
    assert read.reader == "pdftotext 26.11.0 (poppler), layout order"
    assert read.text == "Methods\nWe studied 120 patients.\nResults\nThe ROR was 2.5."
    assert pdf.author(Path("paper.pdf")) == ("Ada Example", "")
    assert calls == [("pdftotext", ["-v"], str(tmp_path)),
                     ("pdftotext", ["-enc", "UTF-8", "paper.pdf", "-"], str(tmp_path)),
                     ("pdftotext", ["-raw", "-enc", "UTF-8", "paper.pdf", "-"], str(tmp_path)),
                     ("pdfinfo", ["-enc", "UTF-8", "paper.pdf"], str(tmp_path))]  # fmt: skip


POPPLER_PACKAGE = WEB / "node_modules" / "@ai-ecoverse" / "wasm-poppler"


@pytest.mark.skipif(shutil.which("node") is None or not POPPLER_PACKAGE.is_dir(),
                    reason="node, or web/node_modules from `npm ci`, is not here")
def test_each_run_of_a_program_on_the_page_is_one_of_its_own(tmp_path: Path) -> None:
    """web/poppler.mjs, with the package's glue as web/build.py puts it in, run in Node: a
    program reads the file its argument names from the folder it is run in, and what one run's
    options set does not carry to the next, as it would in one instance (pdftotext's order
    after `-raw`); a program the page has not is refused, and a file it cannot open is said as
    pdftotext says it, with its exit code."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("web_build", WEB / "build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    (tmp_path / "poppler.mjs").write_text(build.poppler_module(
        (WEB / "poppler.mjs").read_text(encoding="utf-8"),
        (POPPLER_PACKAGE / build.POPPLER_GLUE).read_text(encoding="utf-8")), encoding="utf-8")
    sys.path.insert(0, str(ROOT / "tests"))
    import proof_pdf

    lines = [f"Left {index} of the first column" for index in range(3)]
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "paper.pdf").write_bytes(proof_pdf.typeset(lines, line_numbers=True))
    layout = ["pdftotext", "-enc", "UTF-8", "sub/paper.pdf", "-"]
    runs = [layout, ["pdftotext", "-raw", "-enc", "UTF-8", "sub/paper.pdf", "-"], layout,
            ["pdftotext", "-enc", "UTF-8", "missing.pdf", "-"]]
    given = {"module": str(tmp_path / "poppler.mjs"), "runs": runs,
             "wasm": str(POPPLER_PACKAGE / "bin" / build.POPPLER_WASM)}
    done = subprocess.run([shutil.which("node"), str(WEB / "test" / "runs.mjs")], cwd=tmp_path,
                          input=json.dumps(given), capture_output=True, text=True,
                          encoding="utf-8", timeout=120, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    told = json.loads(done.stdout)
    first, raw, after, missing = told["said"]
    assert first["code"] == raw["code"] == 0 and "Left 0 of the first column" in first["out"]
    # The margin's numbers: set apart as a column in the layout order, in front of each line
    # in the drawing order (auditing/pdf.py).
    assert raw["out"] != first["out"] and after == first
    assert missing["code"] == 1 and "missing.pdf" in missing["err"]
    assert told["refused"] == "no program pdftoppm here"
    assert told["programs"] == list(web.PROGRAMS)
    # The glue's exit sets Node's exit code, which each run puts back.
    assert told["code"] is None
