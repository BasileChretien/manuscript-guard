"""`sync-sources`: each cited work's copy taken from Zotero, against a fake Better BibTeX.

The fake answers `item.attachments` in the shapes Better BibTeX 9.0.71 (Zotero 9.0.6) gave
when probed on a real library on 2026-10-20: a list of `{open, path}`, `open` a
`zotero://open-pdf/library/items/<KEY>` link and `path` the file's absolute path, or `false`
for a link to a page or an attachment with no file; null for an item with no attachment; and
the JSON-RPC error -32602 "<key> not found" for a key the library does not hold. Of the 193
items of two title searches in that library, 69 had a file on this computer, 32 had only the
`.zotero-ft-cache` Zotero keeps of a file it has not downloaded here, and 92 had neither.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_project
from manuscript_guard.literature import copies
from manuscript_guard.zotero import ZoteroRefused, ZoteroUnavailable, client, reset_cache

PDF = b"%PDF-1.4\nthe article as published\n%%EOF\n"


@pytest.fixture(autouse=True)
def _fresh_client():
    reset_cache()
    yield
    reset_cache()


class Storage:
    """A Zotero data folder: `storage/<attachment key>/<file>`, as Zotero lays it out."""

    def __init__(self, root: Path) -> None:
        self.root = root / "Zotero" / "storage"
        self.count = 0

    def _item(self) -> tuple[str, Path]:
        self.count += 1
        item = f"ITEM{self.count:04d}"
        folder = self.root / item
        folder.mkdir(parents=True)
        return item, folder

    @staticmethod
    def _open(item: str) -> str:
        return f"zotero://open-pdf/library/items/{item}"

    def file(self, name: str, data: bytes) -> dict:
        item, folder = self._item()
        (folder / name).write_bytes(data)
        return {"open": self._open(item), "path": str(folder / name)}

    def text_only(self, name: str, text: str) -> dict:
        """A file Zotero has not downloaded to this computer: only its text is here."""
        item, folder = self._item()
        (folder / ".zotero-ft-cache").write_bytes(text.encode("utf-8"))
        return {"open": self._open(item), "path": str(folder / name)}

    def absent(self, name: str) -> dict:
        """A file Zotero has neither downloaded nor indexed here."""
        item, folder = self._item()
        return {"open": self._open(item), "path": str(folder / name)}

    def link(self) -> dict:
        item, _ = self._item()
        return {"open": self._open(item), "path": False}


class FakeBBT:
    """Answers `rpc(method, params, timeout)` for `item.attachments` and `user.groups`.

    `held` maps a library id (1 is the user's own) to the keys it holds and their answer.
    """

    def __init__(self, held: dict[int, dict[str, list | None]]) -> None:
        self.held = held
        self.calls: list[tuple[str, object]] = []

    def __call__(self, method: str, params, timeout: int = 20):
        self.calls.append((method, params))
        if method == "user.groups":
            return [{"id": i, "name": f"Library {i}"} for i in sorted({1, *self.held})]
        if method == "item.attachments":
            key = params[0]
            library = params[1] if len(params) > 1 else 1
            if key not in self.held.get(library, {}):
                error = {"code": -32602, "message": f"{key} not found"}
                raise ZoteroRefused(f"Better BibTeX refused {method}: {error}", error)
            return self.held[library][key]
        raise AssertionError(f"unexpected call {method}")


@pytest.fixture
def paper(tmp_path: Path) -> Path:
    root = tmp_path / "paper"
    assert main(["init", str(root)]) == 0
    for page in (root / "manuscript").rglob("*.md"):
        page.unlink()
    return root


def cite(root: Path, *keys: str) -> None:
    sentences = "\n\n".join(f"This was reported before [@{key}]." for key in keys)
    (root / "manuscript" / "main.md").write_text(f"# Introduction\n\n{sentences}\n", "utf-8")


def sync(root: Path, monkeypatch, fake: FakeBBT, *, dry_run: bool = False):
    monkeypatch.setattr(client, "rpc", fake)
    return copies.sync(load_project(root)[0], dry_run=dry_run, today=date(2026, 10, 20))


def run(root: Path, monkeypatch, fake: FakeBBT, *extra: str) -> int:
    monkeypatch.setattr(client, "rpc", fake)
    return main(["sync-sources", str(root), *extra])


def sources(root: Path) -> Path:
    return root / "literature" / "sources"


def record(root: Path) -> dict:
    return yaml.safe_load((root / "literature" / copies.RECORD).read_text("utf-8"))


def by_key(outcomes) -> dict[str, list[copies.Outcome]]:
    found: dict[str, list[copies.Outcome]] = {}
    for one in outcomes:
        found.setdefault(one.key, []).append(one)
    return found


def test_a_cited_works_pdf_is_copied_under_its_key_and_recorded(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    attachment = zotero.file("Smith et al. - 2020 - A cohort.pdf", PDF)
    sync(paper, monkeypatch, FakeBBT({1: {"smith2020": [attachment]}}))

    assert (sources(paper) / "smith2020.pdf").read_bytes() == PDF
    held = record(paper)
    assert held["schema"] == copies.SCHEMA
    assert held["files"]["smith2020.pdf"] == {
        "key": "smith2020",
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "bytes": len(PDF),
        "from": "zotero",
        "attachment": "ITEM0001",
        "copied": "2026-10-20",
    }
    text = (paper / "literature" / copies.RECORD).read_text("utf-8")
    assert str(tmp_path) not in text and "Zotero" + "/" not in text, "no path on this computer"


def test_a_saved_page_is_copied_beside_the_pdf(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    page = b"<html><body><p>The article as a page.</p></body></html>"
    held = [zotero.file("article.pdf", PDF), zotero.file("Snapshot.html", page)]
    sync(paper, monkeypatch, FakeBBT({1: {"smith2020": held}}))

    assert (sources(paper) / "smith2020.pdf").read_bytes() == PDF
    assert (sources(paper) / "smith2020.html").read_bytes() == page
    assert set(record(paper)["files"]) == {"smith2020.pdf", "smith2020.html"}


def test_zoteros_text_stands_in_for_a_file_not_on_this_computer(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "jones2019")
    attachment = zotero.text_only("Jones - 2019.pdf", "The incidence was 2.6 per 1000.")
    (outcome,) = sync(paper, monkeypatch, FakeBBT({1: {"jones2019": [attachment]}}))

    stored = sources(paper) / "jones2019.txt"
    assert stored.read_text("utf-8") == "The incidence was 2.6 per 1000."
    assert record(paper)["files"]["jones2019.txt"]["from"] == "zotero-text"
    assert outcome.status == copies.COPIED and "Zotero's text" in outcome.said


def test_a_work_with_no_copy_is_listed_and_nothing_is_written(paper, tmp_path, monkeypatch, capsys):
    zotero = Storage(tmp_path)
    cite(paper, "linked2018", "bare2017", "away2016", "unknown2015")
    fake = FakeBBT(
        {1: {"linked2018": [zotero.link()], "bare2017": None, "away2016": [zotero.absent("a.pdf")]}}
    )
    assert run(paper, monkeypatch, fake) == 0

    assert not list(sources(paper).iterdir())
    assert not (paper / "literature" / copies.RECORD).exists()
    out = capsys.readouterr().out
    listed = out.split("No copy for 4 cited works")[1]
    for key, why in (
        ("linked2018", "a link"),
        ("bare2017", "no attachment"),
        ("away2016", "not on this computer"),
        ("unknown2015", "not in Zotero"),
    ):
        assert f"@{key}" in listed and why in listed, (key, why, out)


def test_a_key_held_by_a_group_library_is_copied_from_there(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "group2020")
    fake = FakeBBT({1: {}, 4: {"group2020": [zotero.file("g.pdf", PDF)]}})
    sync(paper, monkeypatch, fake)

    assert (sources(paper) / "group2020.pdf").read_bytes() == PDF
    assert ("item.attachments", ["group2020", 4]) in fake.calls


def test_the_group_libraries_are_not_asked_for_a_key_in_the_users_own(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    fake = FakeBBT({1: {"smith2020": [zotero.file("s.pdf", PDF)]}})
    sync(paper, monkeypatch, fake)
    assert [method for method, _ in fake.calls] == ["item.attachments"]


def test_a_file_put_there_by_hand_is_never_written_over(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    mine = b"%PDF-1.4\nthe copy the author saved from the publisher\n"
    sources(paper).mkdir(parents=True, exist_ok=True)
    (sources(paper) / "smith2020.pdf").write_bytes(mine)
    (outcome,) = sync(paper, monkeypatch, FakeBBT({1: {"smith2020": [zotero.file("s.pdf", PDF)]}}))

    assert (sources(paper) / "smith2020.pdf").read_bytes() == mine
    assert outcome.status == copies.KEPT
    assert not (paper / "literature" / copies.RECORD).exists()


def test_an_authors_file_the_same_as_zoteros_is_never_claimed(paper, tmp_path, monkeypatch):
    """Round 1 of #361: an author's copy with Zotero's bytes was found unchanged and entered in
    the record as the command's, so that a later change in Zotero replaced it."""
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    attachment = zotero.file("s.pdf", PDF)
    sources(paper).mkdir(parents=True, exist_ok=True)
    (sources(paper) / "smith2020.pdf").write_bytes(PDF)
    fake = FakeBBT({1: {"smith2020": [attachment]}})
    (first,) = sync(paper, monkeypatch, fake)
    assert first.status == copies.UNCHANGED
    assert not (paper / "literature" / copies.RECORD).exists(), "found in place, not written"

    Path(attachment["path"]).write_bytes(PDF + b"% the accepted manuscript instead\n")
    (second,) = sync(paper, monkeypatch, fake)
    assert second.status == copies.KEPT
    assert (sources(paper) / "smith2020.pdf").read_bytes() == PDF


def test_an_existing_file_that_cannot_be_read_is_said_and_left(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    sources(paper).mkdir(parents=True, exist_ok=True)
    (sources(paper) / "smith2020.pdf").write_bytes(b"%PDF-1.4\nthe author's\n")
    hashed = copies.digest

    def locked(path):
        if path.parent == sources(paper):
            raise PermissionError(13, "The process cannot access the file")
        return hashed(path)

    monkeypatch.setattr(copies, "digest", locked)
    (outcome,) = sync(paper, monkeypatch, FakeBBT({1: {"smith2020": [zotero.file("s.pdf", PDF)]}}))
    assert outcome.status == copies.KEPT and "could not be read" in outcome.said


def test_a_copy_it_wrote_is_replaced_when_zoteros_changes(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    attachment = zotero.file("s.pdf", PDF)
    fake = FakeBBT({1: {"smith2020": [attachment]}})
    sync(paper, monkeypatch, fake)
    newer = PDF + b"% with the correction the journal published\n"
    Path(attachment["path"]).write_bytes(newer)
    reset_cache()
    (outcome,) = sync(paper, monkeypatch, fake)

    assert outcome.status == copies.UPDATED
    assert (sources(paper) / "smith2020.pdf").read_bytes() == newer
    assert record(paper)["files"]["smith2020.pdf"]["sha256"] == hashlib.sha256(newer).hexdigest()


def test_a_copy_changed_since_it_was_written_is_kept(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    attachment = zotero.file("s.pdf", PDF)
    fake = FakeBBT({1: {"smith2020": [attachment]}})
    sync(paper, monkeypatch, fake)
    (sources(paper) / "smith2020.pdf").write_bytes(b"%PDF-1.4\nreplaced by hand\n")
    Path(attachment["path"]).write_bytes(PDF + b"% newer in Zotero\n")
    reset_cache()
    (outcome,) = sync(paper, monkeypatch, fake)

    assert outcome.status == copies.KEPT
    assert (sources(paper) / "smith2020.pdf").read_bytes() == b"%PDF-1.4\nreplaced by hand\n"


def test_a_second_run_changes_nothing(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    fake = FakeBBT({1: {"smith2020": [zotero.file("s.pdf", PDF)]}})
    sync(paper, monkeypatch, fake)
    before = (paper / "literature" / copies.RECORD).read_bytes()
    reset_cache()
    (outcome,) = sync(paper, monkeypatch, fake)

    assert outcome.status == copies.UNCHANGED
    assert (paper / "literature" / copies.RECORD).read_bytes() == before


def test_two_files_of_one_kind_are_refused_rather_than_one_guessed(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "two2014", "twins2013")
    fake = FakeBBT(
        {
            1: {
                "two2014": [zotero.file("article.pdf", PDF), zotero.file("supp.pdf", b"%PDF s")],
                "twins2013": [zotero.file("a.pdf", PDF), zotero.file("b.pdf", PDF)],
            }
        }
    )
    found = by_key(sync(paper, monkeypatch, fake))

    assert not (sources(paper) / "two2014.pdf").exists()
    (refused,) = found["two2014"]
    assert refused.status == copies.NO_COPY and "2 .pdf files" in refused.said
    assert (sources(paper) / "twins2013.pdf").read_bytes() == PDF, "one file twice is one file"


def test_a_file_check_cannot_read_is_not_copied(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "book2012")
    fake = FakeBBT({1: {"book2012": [zotero.file("b.epub", b"PK")]}})
    (outcome,) = sync(paper, monkeypatch, fake)

    assert outcome.status == copies.NO_COPY and ".epub" in outcome.said
    assert not list(sources(paper).iterdir())


def test_zoteros_text_is_taken_for_a_file_check_cannot_read(paper, tmp_path, monkeypatch):
    """Round 1 of #361: the same attachment gave its text when its file was absent and nothing
    when its file was here in a kind check cannot read."""
    zotero = Storage(tmp_path)
    cite(paper, "book2012")
    attachment = zotero.file("b.epub", b"PK")
    (Path(attachment["path"]).parent / ".zotero-ft-cache").write_text("Chapter one.", "utf-8")
    (outcome,) = sync(paper, monkeypatch, FakeBBT({1: {"book2012": [attachment]}}))

    assert outcome.status == copies.COPIED
    assert (sources(paper) / "book2012.txt").read_text("utf-8") == "Chapter one."
    # Round 2 of #361: the line said the file was not on this computer, and it was.
    assert "not on this computer" not in outcome.said and ".epub" in outcome.said


@pytest.mark.parametrize("indexed", [False, True], ids=["alone", "with Zotero's text"])
@pytest.mark.parametrize("kind", [".csv", ".json", ".xml", ".bib", ".ris", ".nbib"])
def test_a_data_or_citation_file_is_not_copied_as_the_work(
    paper, tmp_path, monkeypatch, kind, indexed
):
    """Round 1 of #361: G7 reads these suffixes, and a supplementary table or a citation file
    attached in Zotero was copied as the work's text. Round 2: nor through Zotero's text of it,
    which is taken only for a file not here or an EPUB."""
    zotero = Storage(tmp_path)
    cite(paper, "data2011")
    attachment = zotero.file("table" + kind, b"a,b\n1,2\n")
    if indexed:
        (Path(attachment["path"]).parent / ".zotero-ft-cache").write_text("a b 1 2", "utf-8")
    (outcome,) = sync(paper, monkeypatch, FakeBBT({1: {"data2011": [attachment]}}))

    assert outcome.status == copies.NO_COPY and kind in outcome.said
    assert not list(sources(paper).iterdir())


def test_an_entry_whose_file_is_gone_does_not_make_a_new_file_the_commands(
    paper, tmp_path, monkeypatch
):
    """Round 2 of #361: the command copied A, the author deleted it, Zotero stopped offering
    it, the author saved A again by hand, and Zotero then offered C: the stale entry matched
    the author's file, and C replaced it."""
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    held: dict[str, list] = {"smith2020": [zotero.file("a.pdf", PDF)]}
    fake = FakeBBT({1: held})
    sync(paper, monkeypatch, fake)
    (sources(paper) / "smith2020.pdf").unlink()
    held["smith2020"] = None
    sync(paper, monkeypatch, fake)
    assert "smith2020.pdf" not in record(paper)["files"], "the entry goes with its file"

    (sources(paper) / "smith2020.pdf").write_bytes(PDF)
    held["smith2020"] = [zotero.file("c.pdf", PDF + b"% another version\n")]
    (outcome,) = sync(paper, monkeypatch, fake)
    assert outcome.status == copies.KEPT
    assert (sources(paper) / "smith2020.pdf").read_bytes() == PDF


def test_a_dry_run_writes_nothing(paper, tmp_path, monkeypatch, capsys):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    fake = FakeBBT({1: {"smith2020": [zotero.file("s.pdf", PDF)]}})
    assert run(paper, monkeypatch, fake, "--dry-run") == 0

    assert not list(sources(paper).iterdir())
    assert not (paper / "literature" / copies.RECORD).exists()
    assert "would copy" in capsys.readouterr().out


def test_a_work_stored_by_hand_is_not_listed_as_having_no_copy(paper, monkeypatch, capsys):
    cite(paper, "printed2010")
    sources(paper).mkdir(parents=True, exist_ok=True)
    (sources(paper) / "printed2010.txt").write_text("Read from the printed report.", "utf-8")
    assert run(paper, monkeypatch, FakeBBT({1: {"printed2010": None}})) == 0

    out = capsys.readouterr().out
    assert "No copy for" not in out
    assert "@printed2010" in out and "printed2010.txt" in out


def test_a_key_with_a_colon_is_filed_under_the_name_the_gate_reads(paper, tmp_path, monkeypatch):
    zotero = Storage(tmp_path)
    cite(paper, "smith:2020")
    sync(paper, monkeypatch, FakeBBT({1: {"smith:2020": [zotero.file("s.pdf", PDF)]}}))
    assert (sources(paper) / "smith_2020.pdf").read_bytes() == PDF
    assert record(paper)["files"]["smith_2020.pdf"]["key"] == "smith:2020"


def test_nothing_cited_exits_2_and_asks_zotero_nothing(paper, monkeypatch, capsys):
    fake = FakeBBT({1: {}})
    assert run(paper, monkeypatch, fake) == 2
    assert fake.calls == []
    assert "cites nothing" in capsys.readouterr().err


def test_a_zotero_that_does_not_answer_exits_2_and_writes_nothing(paper, monkeypatch, capsys):
    cite(paper, "smith2020")

    def down(method, params, timeout=20):
        raise ZoteroUnavailable("could not reach Better BibTeX. Is Zotero running?")

    assert run(paper, monkeypatch, down) == 2
    assert "Is Zotero running?" in capsys.readouterr().err
    assert not list(sources(paper).iterdir())


def test_what_was_copied_before_zotero_stopped_is_recorded(paper, tmp_path, monkeypatch, capsys):
    zotero = Storage(tmp_path)
    cite(paper, "first2020", "second2019")
    answered = FakeBBT({1: {"first2020": [zotero.file("f.pdf", PDF)]}})

    def stops(method, params, timeout=20):
        if params[0] == "second2019":
            raise ZoteroUnavailable("Better BibTeX did not answer item.attachments within 300 s")
        return answered(method, params, timeout)

    assert run(paper, monkeypatch, stops) == 2
    assert (sources(paper) / "first2020.pdf").read_bytes() == PDF
    assert set(record(paper)["files"]) == {"first2020.pdf"}, "a later run may replace it"


def test_a_file_that_cannot_be_written_is_said_and_left(paper, tmp_path, monkeypatch):
    """Windows refuses to replace a PDF a viewer holds open."""
    zotero = Storage(tmp_path)
    cite(paper, "open2020")

    def held_open(source, target):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(copies.os, "replace", held_open)
    (outcome,) = sync(paper, monkeypatch, FakeBBT({1: {"open2020": [zotero.file("o.pdf", PDF)]}}))

    assert outcome.status == copies.KEPT and "could not be written" in outcome.said
    assert not list(sources(paper).iterdir()), "nothing left behind, half-written or whole"
    assert not (paper / "literature" / copies.RECORD).exists()


def test_a_record_that_is_not_one_stops_the_command(paper, tmp_path, monkeypatch, capsys):
    zotero = Storage(tmp_path)
    cite(paper, "smith2020")
    (paper / "literature" / copies.RECORD).write_text("files: [not, a, mapping]\n", "utf-8")
    fake = FakeBBT({1: {"smith2020": [zotero.file("s.pdf", PDF)]}})
    assert run(paper, monkeypatch, fake) == 2

    assert copies.RECORD in capsys.readouterr().err
    assert not list(sources(paper).iterdir())


def test_better_bibtexs_not_found_is_told_apart_from_other_refusals(monkeypatch):
    """At the wire: the error object rides on the exception, so "not found" moves on to the
    group libraries and an unknown method is raised."""
    answers = {
        "item.attachments": {"code": -32602, "message": "nobody2000 not found"},
        "user.groups": None,
    }

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        method = json.loads(request.data)["method"]
        if answers[method] is None:
            return Reply(json.dumps({"result": [{"id": 1, "name": "My Library"}]}).encode())
        return Reply(json.dumps({"error": answers[method]}).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    assert client.attachments("nobody2000") is None

    answers["item.attachments"] = {"code": -32601, "message": "method not found"}
    reset_cache()
    with pytest.raises(ZoteroRefused):
        client.attachments("nobody2000")
