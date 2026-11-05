"""The in-browser audit page's side of the package (`manuscript_guard.web`): pandoc.wasm in
place of the pandoc on PATH, and the transport a page sends lookups with.

The page itself, in Pyodide with the real pandoc.wasm, is held by CI's `web` job
(`web/test/`). Here pandoc.wasm is stood in for by pandoc run on a defaults file, which is
the object pandoc.wasm takes, so that what the translation sends is what pandoc reads.
"""

from __future__ import annotations

import json
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
    assert all(re.fullmatch(r"\d+(\.\d+)+", v) for part in ("dependencies", "devDependencies")
               for v in npm[part].values()), "web/package.json pins each version exactly"


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

    from manuscript_guard.lookup.run import Services

    asked = {f"https://{urlsplit(getattr(Services(), f.name)).hostname}" for f in fields(Services)}
    page, policy = _policy()
    assert set(policy["connect-src"]) == {"'self'", *asked}
    assert policy["default-src"] == ["'none'"]
    assert policy["script-src"] == ["'self'", "'wasm-unsafe-eval'"]
    # A worker from a file would run under no policy at all (web/worker.js).
    assert policy["worker-src"] == ["blob:"]
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


# --------------------------------------------------------------------- a command, printed


def test_run_returns_the_exit_code_and_what_was_printed() -> None:
    from manuscript_guard import __version__

    assert web.run(["--version"]) == {"code": 0, "out": f"{__version__}\n", "err": ""}
    refused = web.run(["audit"])
    assert refused["code"] != 0 and "name a paper" in refused["err"]
