"""A paper's project as an archive, which the audit page unpacks into a folder of its own and
audits (`auditing.unpack.unpack_archive`, `web.unpack_paper`): a .zip, as Overleaf downloads
one, a .tar.gz or .tgz, as arXiv gives a paper's source, and arXiv's one gzipped file; each
held to the checks a package's .zip is held to, and in a tar no member but a file or a
folder."""

from __future__ import annotations

import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from manuscript_guard import web
from manuscript_guard.auditing.unpack import Refused, archive_stem, unpack_archive

PAPER = (b"\\documentclass{article}\n\\begin{document}\n\\section{Results}\n"
         b"Of 40 patients, 12 improved.\n\\end{document}\n")  # fmt: skip


def tarred(path: Path, members: list[tuple[str, bytes | None]], *, kind: bytes = tarfile.REGTYPE,
           link: str = "") -> Path:  # fmt: skip
    """A .tar.gz of `members`, each a file with its bytes, or a folder where the bytes are
    None; the last of them of `kind`, pointing at `link`, where one is given."""
    with tarfile.open(path, "w:gz") as archive:
        for at, (name, data) in enumerate(members):
            info = tarfile.TarInfo(name)
            if data is None:
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
                continue
            if at == len(members) - 1 and kind != tarfile.REGTYPE:
                info.type, info.linkname = kind, link
                archive.addfile(info)
                continue
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def zipped(path: Path, members: list[tuple[str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members:
            archive.writestr(name, data)
    return path


@pytest.mark.parametrize("name", ["project.zip", "project.tar.gz", "project.TGZ"])
def test_an_archive_of_a_latex_project_is_unpacked_into_a_folder_named_after_it(
    tmp_path: Path, name: str
) -> None:
    members = [("main.tex", PAPER), ("sections/methods.tex", b"Methods.\n")]
    archive = tmp_path / name
    if name.endswith(".zip"):
        zipped(archive, members)
    else:
        tarred(archive, [("./", None), ("./sections", None),
                         *((f"./{one}", data) for one, data in members)])  # fmt: skip
    into = tmp_path / "work"
    into.mkdir()
    assert web.unpack_paper(str(archive), str(into)) == {"folder": "project"}
    assert (into / "project" / "main.tex").read_bytes() == PAPER
    assert (into / "project" / "sections" / "methods.tex").read_bytes() == b"Methods.\n"


def test_one_gzipped_file_as_arxiv_gives_a_paper_is_its_own_tex(tmp_path: Path) -> None:
    archive = tmp_path / "2301.01234.tar.gz"
    archive.write_bytes(gzip.compress(PAPER))
    assert web.unpack_paper(str(archive), str(tmp_path)) == {"folder": "2301.01234"}
    assert (tmp_path / "2301.01234" / "2301.01234.tex").read_bytes() == PAPER


def test_the_audit_reads_the_folder_as_the_command_line_reads_the_one_unpacked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page gives the audit the folder the archive is unpacked into, and says what the
    command line says of the same folder unpacked by hand."""
    monkeypatch.chdir(tmp_path)
    by_hand = tmp_path / "hand" / "project"
    by_hand.mkdir(parents=True)
    (by_hand / "main.tex").write_bytes(PAPER)
    zipped(tmp_path / "project.zip", [("main.tex", PAPER)])
    (tmp_path / "page").mkdir()
    said = web.unpack_paper(str(tmp_path / "project.zip"), str(tmp_path / "page"))
    assert said == {"folder": "project"}
    monkeypatch.chdir(tmp_path / "page")
    page = web.run(["audit", "project"])
    monkeypatch.chdir(tmp_path / "hand")
    assert page == web.run(["audit", "project"])
    assert page["code"] == 0 and "Audited 1 file(s)" in page["out"], page


@pytest.mark.parametrize(("members", "kind", "said"), [
    ([("../escape.tex", b"x")], tarfile.REGTYPE, "has .. among its parts"),
    ([("/etc/escape.tex", b"x")], tarfile.REGTYPE, "is named from the root"),
    ([("main.tex", PAPER), ("link.tex", b"")], tarfile.SYMTYPE, "is a link"),
    ([("main.tex", PAPER), ("hard.tex", b"")], tarfile.LNKTYPE, "is a link"),
    ([("main.tex", PAPER), ("device", b"")], tarfile.CHRTYPE, "is neither a file nor a folder"),
    ([("main.tex", PAPER), ("fifo", b"")], tarfile.FIFOTYPE, "is neither a file nor a folder"),
    ([("Main.tex", PAPER), ("main.tex", PAPER)], tarfile.REGTYPE, "one name"),
    ([("figures", b"x"), ("figures/a.pdf", b"y")], tarfile.REGTYPE, "both a file and a folder"),
])  # fmt: skip
def test_a_tar_member_that_could_land_outside_or_is_no_file_is_refused_and_nothing_is_left(
    tmp_path: Path, members: list, kind: bytes, said: str
) -> None:
    archive = tarred(tmp_path / "bad.tar.gz", members, kind=kind, link="/etc/passwd")
    with pytest.raises(Refused, match=said):
        unpack_archive(archive, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
    assert said in web.unpack_paper(str(archive), str(tmp_path))["error"]


def test_an_archive_past_the_limits_is_refused(tmp_path: Path) -> None:
    archive = tarred(tmp_path / "big.tar.gz", [("main.tex", PAPER), ("b.tex", b"b")])
    with pytest.raises(Refused, match="members"):
        unpack_archive(archive, tmp_path / "one", max_members=1)
    with pytest.raises(Refused, match="bytes"):
        unpack_archive(archive, tmp_path / "two", max_bytes=10)
    one = tmp_path / "one.tar.gz"
    one.write_bytes(gzip.compress(b"x" * 100))
    with pytest.raises(Refused, match="more than the 10 bytes"):
        unpack_archive(one, tmp_path / "three", max_bytes=10)
    zipped_one = zipped(tmp_path / "z.zip", [("main.tex", PAPER)])
    with pytest.raises(Refused, match="bytes"):
        unpack_archive(zipped_one, tmp_path / "four", max_bytes=10)
    assert not any((tmp_path / name).exists() for name in ("one", "two", "three", "four"))


def test_what_is_no_archive_or_cannot_be_read_is_refused(tmp_path: Path) -> None:
    (tmp_path / "paper.docx").write_bytes(b"x")
    assert web.unpack_paper(str(tmp_path / "paper.docx"), str(tmp_path)) == {
        "error": "paper.docx is not a .zip or a .tar.gz"}
    (tmp_path / "broken.tar.gz").write_bytes(b"not gzip at all")
    assert "is not a .tar.gz the audit can read" in web.unpack_paper(
        str(tmp_path / "broken.tar.gz"), str(tmp_path))["error"]
    (tmp_path / "broken.zip").write_bytes(b"not a zip")
    assert "is not a .zip the audit can read" in web.unpack_paper(
        str(tmp_path / "broken.zip"), str(tmp_path))["error"]
    zipped(tmp_path / "there.zip", [("main.tex", PAPER)])
    (tmp_path / "there").mkdir()
    assert "the folder there is there already" in web.unpack_paper(
        str(tmp_path / "there.zip"), str(tmp_path))["error"]


def test_an_archive_s_stem_is_its_name_without_its_suffix() -> None:
    assert archive_stem("project.zip") == archive_stem("project.tar.gz") == "project"
    assert archive_stem("Paper v2.TGZ") == "Paper v2"
    assert archive_stem(".zip") == archive_stem("paper.docx") == archive_stem("x.gz") == ""
