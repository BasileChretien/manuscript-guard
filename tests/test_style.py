"""`style`: the journal's citation style fetched once from the CSL style repository, and kept
for the offline build (item 51).

No test opens a connection to the repository. Most answer from a table; the real transport is
run against a server on a loopback port. The styles are written here, the fewest lines the
specification asks for: no style of the repository is committed to this one.
"""

from __future__ import annotations

import re
import shutil
import threading
import zipfile
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from manuscript_guard import journal_style
from manuscript_guard.cli import main
from manuscript_guard.contracts.project import load_project
from manuscript_guard.lookup import styles
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

TODAY = date(2026, 10, 17)
REPOSITORY = "https://styles.invalid/"
PARENT = "mg-test-numbers"
DEPENDENT = "mg-test-journal"

#: An independent style that prints a citation as [[1]], which pandoc's default never does.
PARENT_CSL = b"""<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">
  <info>
    <title>Test numbers</title>
    <id>http://www.zotero.org/styles/mg-test-numbers</id>
    <category citation-format="numeric"/>
    <updated>2026-10-17T00:00:00+00:00</updated>
    <rights license="http://creativecommons.org/licenses/by-sa/3.0/">CC BY-SA 3.0</rights>
  </info>
  <citation>
    <layout prefix="[[" suffix="]]" delimiter=","><text variable="citation-number"/></layout>
  </citation>
  <bibliography>
    <layout><text variable="citation-number" suffix=". "/><text variable="title"/></layout>
  </bibliography>
</style>
"""

#: A dependent style of it. Its link names a port nothing listens on, so a build that did not
#: find the parent beside it would fail rather than reach anywhere.
DEPENDENT_CSL = b"""<?xml version="1.0" encoding="utf-8"?>
<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0">
  <info>
    <title>Test journal</title>
    <id>http://www.zotero.org/styles/mg-test-journal</id>
    <link href="http://127.0.0.1:9/styles/mg-test-numbers" rel="independent-parent"/>
    <category citation-format="numeric"/>
    <updated>2026-10-17T00:00:00+00:00</updated>
  </info>
</style>
"""


class Table:
    """A transport that answers from the path asked for, and keeps what it was sent."""

    def __init__(self, files: dict[str, tuple[int, bytes]]) -> None:
        self.files = files
        self.sent: list[str] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        path = urlsplit(request.base).path
        self.sent.append(path)
        status, body = self.files.get(path, (404, b"404: Not Found"))
        return Response(status, {}, body)


def repository(**extra: tuple[int, bytes]) -> Table:
    """The repository as it lays itself out: independent styles at the root, dependent ones
    under dependent/."""
    files = {
        f"/{PARENT}.csl": (200, PARENT_CSL),
        f"/dependent/{DEPENDENT}.csl": (200, DEPENDENT_CSL),
    }
    return Table({**files, **{f"/{k}": v for k, v in extra.items()}})


def name_style(root: Path, csl: str | None, **references) -> None:
    """Give the example's journal profile this style, and these other `references` fields."""
    profile = root / "profiles" / "journals" / "demo-journal.yaml"
    document = yaml.safe_load(profile.read_text(encoding="utf-8"))
    block = {**document.get("references", {}), **references}
    if csl is not None:
        block["csl"] = csl
    document["references"] = block
    profile.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def keep_style(root: Path, name: str = DEPENDENT) -> dict:
    """The style named in the profile and kept, as `style` would, from the table."""
    name_style(root, name)
    project, _ = load_project(root)
    return styles.store(
        project, name, transport=repository(), base=REPOSITORY, today=lambda: TODAY
    )


def _stand_in(monkeypatch, table: Table) -> Table:
    monkeypatch.setattr(styles, "default_transport", table)
    monkeypatch.setattr(styles, "REPOSITORY", REPOSITORY)
    return table


# ------------------------------------------------------------------------------- fetching


def test_an_independent_style_is_kept_with_its_record(project: Path) -> None:
    record = keep_style(project, PARENT)
    folder = project / "profiles" / "journals" / "styles" / PARENT
    assert (folder / f"{PARENT}.csl").read_bytes() == PARENT_CSL
    assert record == {
        "schema": journal_style.SCHEMA,
        "style": PARENT,
        "title": "Test numbers",
        "file": f"{PARENT}.csl",
        "source_url": f"{REPOSITORY}{PARENT}.csl",
        "sha256": journal_style.digest(PARENT_CSL),
        "licence": "http://creativecommons.org/licenses/by-sa/3.0/",
        "retrieved_on": "2026-10-17",
        "citation_format": "numeric",
    }
    loaded, _ = load_project(project)
    assert journal_style.read_record(loaded, PARENT) == record
    kept = journal_style.stored(loaded, f"http://www.zotero.org/styles/{PARENT}")
    assert kept is not None and kept.path == folder / f"{PARENT}.csl" and kept.parent is None


def test_a_dependent_style_is_kept_with_the_style_it_depends_on(project: Path) -> None:
    """Asked for at the root, then under dependent/; its parent from the root."""
    table = repository()
    name_style(project, DEPENDENT)
    loaded, _ = load_project(project)
    record = styles.store(loaded, DEPENDENT, transport=table, base=REPOSITORY)
    assert table.sent == [f"/{DEPENDENT}.csl", f"/dependent/{DEPENDENT}.csl", f"/{PARENT}.csl"]
    assert record["source_url"] == f"{REPOSITORY}dependent/{DEPENDENT}.csl"
    assert record["parent"]["style"] == PARENT
    assert record["parent"]["sha256"] == journal_style.digest(PARENT_CSL)
    folder = project / "profiles" / "journals" / "styles"
    assert sorted(p.name for p in folder.iterdir()) == [DEPENDENT, f"{DEPENDENT}.yaml"]
    kept_files = sorted(p.name for p in (folder / DEPENDENT).iterdir())
    assert kept_files == [f"{DEPENDENT}.csl", f"{PARENT}.csl"]
    kept = journal_style.stored(loaded, DEPENDENT)
    assert kept is not None and kept.parent == folder / DEPENDENT / f"{PARENT}.csl"


def test_two_styles_that_share_a_parent_each_keep_their_own(project: Path) -> None:
    """Round 1 of #322: a second style of the same parent, fetched after the parent changed
    upstream, wrote it over the file the first style's record had pinned, and the first was
    `journal-style-changed` and not used, though nobody had edited anything."""
    keep_style(project, DEPENDENT)
    other = DEPENDENT_CSL.replace(b"mg-test-journal", b"mg-test-other")
    changed = PARENT_CSL.replace(b"Test numbers", b"Test numbers, revised")
    table = Table({"/dependent/mg-test-other.csl": (200, other), f"/{PARENT}.csl": (200, changed)})
    loaded, _ = load_project(project)
    styles.store(loaded, "mg-test-other", transport=table, base=REPOSITORY)
    first = journal_style.stored(loaded, DEPENDENT)
    second = journal_style.stored(loaded, "mg-test-other")
    assert first is not None and second is not None
    assert first.parent.read_bytes() == PARENT_CSL and second.parent.read_bytes() == changed


@pytest.mark.parametrize(
    ("files", "said"),
    [
        ({}, "has no style named mg-test-journal"),
        ({f"dependent/{DEPENDENT}.csl": (500, b"")}, "answered 500"),
        ({f"dependent/{DEPENDENT}.csl": (200, b"<html><body>gone</body></html>")},
         "is not a CSL style"),
        ({f"dependent/{DEPENDENT}.csl": (200, b'<!DOCTYPE s [<!ENTITY a "a">]><style/>')},
         "declares a DTD"),
        # An independent style that formats nothing.
        ({f"dependent/{DEPENDENT}.csl": (200, PARENT_CSL.replace(b"citation>", b"cite>"))},
         "independent style with no <citation>"),
        # The parent is gone from the root.
        ({PARENT + ".csl": (404, b"")}, "has no style named mg-test-numbers"),
        # A parent that depends on another.
        ({PARENT + ".csl": (200, DEPENDENT_CSL)}, "itself a dependent style"),
        ({f"dependent/{DEPENDENT}.csl": (200, DEPENDENT_CSL.replace(b"mg-test-numbers\" rel",
                                                                    b"Not_A_Name\" rel"))},
         "parent link names no style"),
    ],
)
def test_a_style_that_is_not_there_or_is_none_writes_nothing(
    project: Path, monkeypatch, capsys, files, said
) -> None:
    name_style(project, DEPENDENT)
    table = repository()
    for path, answer in files.items():
        table.files[f"/{path}"] = answer
    if not files:
        table.files.clear()
    _stand_in(monkeypatch, table)
    assert main(["style", str(project)]) == 1
    err = " ".join(capsys.readouterr().err.split())
    assert said in err and "nothing was written" in err, err
    assert not (project / "profiles" / "journals" / "styles").exists()


@pytest.mark.parametrize(
    "named",
    ["../evil", "Vancouver", "https://example.org/styles/x", "dependent/x", "a//b", ""],
)
def test_a_name_that_is_no_style_of_the_repository_is_not_asked_for(
    project: Path, monkeypatch, capsys, named
) -> None:
    name_style(project, named)
    table = _stand_in(monkeypatch, repository())
    assert main(["style", str(project)]) == 2
    assert table.sent == []
    assert "manuscript-guard:" in capsys.readouterr().err


def test_a_style_named_as_a_file_is_not_asked_for_with_its_suffix(
    project: Path, monkeypatch, capsys
) -> None:
    """Round 1 of #322: "vancouver.csl" was a name, and was asked for as vancouver.csl.csl."""
    from manuscript_guard.journal_style import style_name

    assert style_name("vancouver.csl") is None and style_name("vancouver") == "vancouver"
    name_style(project, f"{DEPENDENT}.csl")
    table = _stand_in(monkeypatch, repository())
    assert main(["style", str(project)]) == 2
    assert table.sent == []
    assert f"without its `.csl`: {DEPENDENT!r}" in " ".join(capsys.readouterr().err.split())
    # Round 1 of #349: what is left without the `.csl` is offered only where it is a name.
    for named in ("styles/vancouver.csl", "Vancouver.CSL"):
        name_style(project, named)
        assert main(["style", str(project)]) == 2
        assert "without its" not in capsys.readouterr().err


def test_style_says_what_it_kept_and_asks_once(project: Path, monkeypatch, capsys) -> None:
    name_style(project, DEPENDENT)
    table = _stand_in(monkeypatch, repository())
    assert main(["style", str(project), "--dry-run"]) == 0
    assert table.sent == [] and "nothing was sent" in capsys.readouterr().out
    assert main(["style", str(project)]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert f"stored {DEPENDENT}, and {PARENT}, the style it depends on," in out, out
    assert "creativecommons.org/licenses/by-sa/3.0" in out, out
    asked = len(table.sent)
    assert main(["style", str(project)]) == 0
    assert len(table.sent) == asked and "nothing was sent" in capsys.readouterr().out
    assert main(["style", str(project), "--again"]) == 0
    assert len(table.sent) == 2 * asked
    # A kept file edited since is fetched again without being asked to.
    kept = project / "profiles" / "journals" / "styles" / DEPENDENT / f"{PARENT}.csl"
    kept.write_bytes(PARENT_CSL.replace(b"[[", b"(("))
    assert main(["style", str(project)]) == 0
    assert kept.read_bytes() == PARENT_CSL


def test_style_without_a_style_to_fetch_says_why(project: Path, capsys) -> None:
    assert main(["style", str(project)]) == 2
    assert "names no style" in capsys.readouterr().err


# ------------------------------------------------------------- the real transport, on loopback


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        status, body = self.server.files.get(self.path, (404, b"404: Not Found"))
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


def test_the_real_transport_fetches_a_style_from_a_loopback_repository(
    project: Path, monkeypatch, capsys
) -> None:
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.files = {"/r/" + k.lstrip("/"): v for k, v in repository().files.items()}
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}/r/"
    try:
        try:
            default_transport(Request(base + "probe"), 5)
        except NoAnswer as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"loopback connections are not allowed here: {exc}")
        name_style(project, DEPENDENT)
        monkeypatch.setattr(styles, "REPOSITORY", base)
        assert main(["style", str(project)]) == 0, capsys.readouterr().err
    finally:
        httpd.shutdown()
        httpd.server_close()
    loaded, _ = load_project(project)
    record = journal_style.read_record(loaded, DEPENDENT)
    assert record is not None and record["parent"]["source_url"] == f"{base}{PARENT}.csl"


# -------------------------------------------------------------------------------- the build


def _printed(docx: Path) -> str:
    with zipfile.ZipFile(docx) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", xml)


@needs_pandoc
def test_an_offline_build_formats_with_the_kept_style_and_finds_its_parent_offline(
    project: Path, capsys
) -> None:
    """Item 51: the offline build used pandoc's default unless `--csl` was passed. A dependent
    style's parent is found beside it: its link names a port nothing listens on, and the
    build would fail had pandoc gone to fetch it."""
    assert main(["build", str(project), "--offline"]) == 0
    assert "[[1]]" not in _printed(project / "build" / "manuscript.docx")
    # Round 1 of #322: a style named and never fetched was said not to be kept as it was
    # fetched.
    name_style(project, DEPENDENT)
    capsys.readouterr()
    assert main(["build", str(project), "--offline"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert f"the journal's citation style {DEPENDENT} is not kept, so citations" in out, out
    keep_style(project, DEPENDENT)
    capsys.readouterr()
    assert main(["build", str(project), "--offline"]) == 0, capsys.readouterr()
    assert "[[1]]" in _printed(project / "build" / "manuscript.docx")
    # A kept file that is not what was fetched is not used; G4 says so.
    kept = project / "profiles" / "journals" / "styles" / DEPENDENT / f"{PARENT}.csl"
    kept.write_bytes(PARENT_CSL.replace(b"[[", b"(("))
    capsys.readouterr()
    assert main(["build", str(project), "--offline"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert f"the journal's citation style {DEPENDENT} is not kept as it was fetched" in out, out
    assert "((1]]" not in _printed(project / "build" / "manuscript.docx")


@needs_pandoc
def test_csl_given_by_hand_wins_over_the_kept_style(
    project: Path, tmp_path: Path, capsys
) -> None:
    keep_style(project, DEPENDENT)
    mine = tmp_path / "mine.csl"
    mine.write_bytes(PARENT_CSL.replace(b"[[", b"{{").replace(b"]]", b"}}"))
    assert main(["build", str(project), "--offline", "--csl", str(mine)]) == 0
    printed = _printed(project / "build" / "manuscript.docx")
    assert "{{1}}" in printed and "[[1]]" not in printed


@needs_pandoc
def test_a_document_built_in_the_kept_style_comes_back_through_import(
    project: Path, tmp_path: Path, capsys
) -> None:
    """The build records where the style was, and the comparison `import` builds finds it,
    and its parent beside it, there."""
    from test_roundtrip import PROSE_CITED, edit_docx

    keep_style(project, DEPENDENT)
    assert main(["build", str(project), "--offline"]) == 0
    built = project / "build" / "manuscript.docx"
    assert "[[1]]" in _printed(built)
    returned = edit_docx(built, tmp_path / "back.docx", {PROSE_CITED: "whole drug class"})
    capsys.readouterr()
    assert main(["import", str(returned), str(project), "--apply"]) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "NOT merged" not in out and "is the citation" not in out, out
    text = " ".join((project / "manuscript" / "main.md").read_text(encoding="utf-8").split())
    assert "whole drug class" in text
