"""A declared input must survive a git checkout.

The digest chain did not. An analysis writing CSVs on Windows records CRLF digests;
`.gitattributes` normalises the blob to LF; a fresh clone then mismatches every declared
input, on every platform including the one the digests were computed on. Measured on the
project this came from: 0 failing in the author's working copy, 35 failing in a clone of the
same commit — and the `.gitattributes` had been added to prevent exactly that, which is what
made it certain. It normalised what git stores while the digests went on being taken over
what sits on disk.

The fix is the one already used for scripts: hash a text input's content, not its line
endings, and on checking accept any spelling of unchanged content. Binary inputs — .xlsx,
.zip, .pdf — stay byte-exact, because there a CR is content.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import (
    Emitter,
    input_digest,
    input_digest_matches,
    sha256_of,
    source_digest,
    write_digest,
)
from manuscript_guard.gates import check_freshness


def codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def rewrite(path: Path, ending: bytes) -> None:
    """Rewrite a file with one line ending, changing nothing else."""
    lf = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    path.write_bytes(lf.replace(b"\n", ending) if ending != b"\n" else lf)


# --- the digest itself -------------------------------------------------------


# .txt and .sql are deliberately absent: see the byte-exact test below. They were in the
# first version of this and were removed once it was shown that normalisation collides
# genuinely different content in a format where a CR can sit inside a value.
@pytest.mark.parametrize("suffix", [".csv", ".json", ".yaml", ".md", ".tsv", ".bib"])
def test_a_text_input_hashes_its_content_not_its_line_endings(tmp_path: Path, suffix: str) -> None:
    lf, crlf = tmp_path / f"a{suffix}", tmp_path / f"b{suffix}"
    lf.write_bytes(b"one,two\n1,2\n")
    crlf.write_bytes(b"one,two\r\n1,2\r\n")
    assert input_digest(lf) == input_digest(crlf)


@pytest.mark.parametrize("suffix", [".xlsx", ".zip", ".pdf", ".png"])
def test_a_binary_input_is_hashed_byte_for_byte(tmp_path: Path, suffix: str) -> None:
    """Where a CR is content, normalising it would hide a real change."""
    a, b = tmp_path / f"a{suffix}", tmp_path / f"b{suffix}"
    a.write_bytes(b"\x01\r\n\x02")
    b.write_bytes(b"\x01\n\x02")
    assert input_digest(a) != input_digest(b)
    assert input_digest(a) == sha256_of(a)


def test_changed_content_still_fails(tmp_path: Path) -> None:
    """The point is to admit three spellings of one file, not a second file."""
    path = tmp_path / "d.csv"
    path.write_bytes(b"one,two\n1,2\n")
    recorded = input_digest(path)
    path.write_bytes(b"one,two\n1,3\n")
    assert not input_digest_matches(path, recorded)


@pytest.mark.parametrize(
    "written, checked_out",
    [(b"\n", b"\r\n"), (b"\r\n", b"\n"), (b"\r", b"\n")],
)
def test_any_spelling_of_unchanged_content_matches(
    tmp_path: Path, written: bytes, checked_out: bytes
) -> None:
    """Including digests recorded before this existed, which is what makes it non-breaking."""
    path = tmp_path / "d.csv"
    path.write_bytes(b"one,two\n1,2\n".replace(b"\n", written))
    recorded = sha256_of(path)          # the raw byte digest an older emitter would record
    rewrite(path, checked_out)
    assert input_digest_matches(path, recorded)


def test_a_script_is_still_a_script(tmp_path: Path) -> None:
    """`source_digest` keeps its narrower suffix set; a .csv is not a script."""
    data = tmp_path / "d.csv"
    data.write_bytes(b"a\r\nb\r\n")
    assert source_digest(data) == sha256_of(data)
    assert input_digest(data) != sha256_of(data)


# --- and the gate that reads it ----------------------------------------------


def test_a_checked_out_input_does_not_trip_G1(project: Path) -> None:
    """The regression, end to end: flip every declared text input's line endings and the
    freshness gate must stay silent, because nothing about the data changed."""
    flipped = 0
    for path in sorted((project / "results").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for declared in doc.get("provenance", {}).get("inputs", []):
            target = project / declared["path"]
            if target.exists() and target.suffix.lower() in {".csv", ".json", ".tsv", ".md"}:
                rewrite(target, b"\r\n")
                flipped += 1
    assert flipped, "the example project declares no text inputs to flip"

    project_obj, _, results_after, _lit2 = _loaded(project)
    assert "input-changed" not in codes(check_freshness(project_obj, results_after))


def test_a_genuinely_edited_input_still_trips_G1(project: Path) -> None:
    """The other direction, so the test above cannot pass by the gate having stopped looking."""
    edited = 0
    for path in sorted((project / "results").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for declared in doc.get("provenance", {}).get("inputs", []):
            target = project / declared["path"]
            if target.exists() and target.suffix.lower() == ".csv":
                target.write_text(target.read_text(encoding="utf-8") + "\n99,99,99\n",
                                  encoding="utf-8")
                edited += 1
                break
        if edited:
            break
    assert edited, "the example project declares no CSV input to edit"
    project_obj, _, results_after, _lit2 = _loaded(project)
    assert "input-changed" in codes(check_freshness(project_obj, results_after))


def test_the_fragment_itself_is_still_byte_exact(tmp_path: Path) -> None:
    """The one digest that must NOT be normalised: a fragment's own sidecar has to be
    reproducible from any language that can emit results, and "hash the bytes you just wrote"
    is the only operation meaning the same thing everywhere."""
    (tmp_path / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "t"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    script = tmp_path / "a.py"
    script.write_text("# x\n", encoding="utf-8")
    em = Emitter(script, root=tmp_path)
    em.value("k.v", 1)
    written = Path(em.write())
    recorded = (written.parent / (written.name + ".sha256")).read_text(encoding="utf-8").split()[0]
    assert recorded == sha256_of(written)


def _loaded(root: Path):
    project, _ = load_project(root)
    namespace, results, literature, _ = load_namespace(project)
    return project, namespace, results, literature


# --- the regression the first version of this shipped ------------------------


def test_a_mixed_ending_file_that_nobody_touched_still_matches(tmp_path: Path) -> None:
    """The defect that made this change a fail-swap rather than a fix.

    Trying only the three canonical spellings — all-LF, all-CRLF, all-CR — misses any file
    that is not uniformly one ending, which is what you get from appending CRLF rows to an LF
    header or from a partially normalised repository. Such a file matched none of the
    candidates, so an untouched input that had been passing began to fail, and the commit
    claiming to be non-breaking was not. The file's actual bytes are now tried first.
    """
    path = tmp_path / "mixed.csv"
    path.write_bytes(b"id,value\n1,10\r\n2,20\r\n")
    recorded = sha256_of(path)          # what an emitter predating this recorded
    assert input_digest_matches(path, recorded)


# --- formats where a CR is content, and are therefore not normalised ---------


@pytest.mark.parametrize("suffix", [".sql", ".txt"])
def test_a_format_that_can_carry_a_cr_inside_a_value_is_byte_exact(
    tmp_path: Path, suffix: str
) -> None:
    """Normalisation rewrites every CR in the stream, not only the ones ending lines. For a
    format where a CR can sit inside a value, two different contents would collide."""
    a, b = tmp_path / f"a{suffix}", tmp_path / f"b{suffix}"
    a.write_bytes(b"INSERT INTO t VALUES ('x\ry');")
    b.write_bytes(b"INSERT INTO t VALUES ('x\ny');")
    assert input_digest(a) != input_digest(b)


def _g1_after(tmp_path: Path, name: str, written: bytes, now: bytes) -> set[str]:
    """G1's codes for a project whose analysis read `name` holding `written`, once the file
    holds `now`."""
    (tmp_path / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "t"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (tmp_path / "analysis").mkdir()
    script = tmp_path / "analysis" / "run.py"
    script.write_text("# x\n", encoding="utf-8")
    data = tmp_path / "data" / name
    data.parent.mkdir()
    data.write_bytes(written)
    em = Emitter(script, root=tmp_path, inputs=[f"data/{name}"])
    em.value("k.v", 1)
    em.write()
    data.write_bytes(now)
    project, _, results, _literature = _loaded(tmp_path)
    return codes(check_freshness(project, results))


@pytest.mark.parametrize(("name", "said"), [("notes.txt", {"input-changed"}), ("notes.csv", set())])
def test_a_txt_input_checked_out_with_crlf_reads_as_changed(
    tmp_path: Path, name: str, said: set[str]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The emitters"): a `.txt` input is digested as
    its bytes, so the same text checked out with CRLF line ends is `input-changed`, where a
    `.csv` of the same bytes passes. The 2026-11-09 triage planned a fix (F07), which will
    change this test."""
    assert _g1_after(tmp_path, name, b"a\nb\n", b"a\r\nb\r\n") == said


@pytest.mark.skipif(sys.platform != "linux", reason="a file system that tells case apart")
@pytest.mark.parametrize(("spelt", "said"), [("DATA/X.csv", {"input-missing"}),
                                             ("data/x.csv", set())])
def test_a_path_recorded_in_another_case_names_no_file_on_linux(
    tmp_path: Path, spelt: str, said: set[str]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "The emitters"): Windows records a path in the case
    it was written in, so results written there from `DATA/X.csv`, cloned on Linux where the
    file is `data/x.csv`, name no file: `input-missing`. Spelt as on the disk, nothing."""
    _g1_after(tmp_path, "x.csv", b"a\n1\n", b"a\n1\n")
    fragment = tmp_path / "results" / "run.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    document["provenance"]["inputs"][0]["path"] = spelt
    fragment.write_text(json.dumps(document, indent=2), encoding="utf-8")
    write_digest(fragment)
    project, _, results, _literature = _loaded(tmp_path)
    assert codes(check_freshness(project, results)) == said


def test_utf16_is_not_normalised(tmp_path: Path) -> None:
    """In UTF-16, 0x0D and 0x0A are bytes of ordinary characters. Rewriting them corrupts
    text rather than reformatting it: U+340D and U+340A would become the same file. Excel's
    Unicode export and many Japanese-Windows CSV exports are UTF-16, so this is not exotic."""
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"\xff\xfe" + "\u340d".encode("utf-16-le"))
    b.write_bytes(b"\xff\xfe" + "\u340a".encode("utf-16-le"))
    assert input_digest(a) != input_digest(b)


@pytest.mark.parametrize(("bom", "said"), [(b"", set()), (b"\xff\xfe", {"input-changed"})])
def test_utf16_without_a_bom_is_normalised_as_8_bit_text(
    tmp_path: Path, bom: bytes, said: set[str]
) -> None:
    """A known gap (DESIGN.md, Known gaps, "A UTF-16 input without a BOM is normalised as if
    it were 8-bit text"): with no BOM, U+4E0D (bytes 0D 4E) swapped for U+4E0A (0A 4E) leaves
    the digest unchanged and passes G1. With a BOM the same edit is `input-changed`."""
    written = bom + "\u4e0d,1\n".encode("utf-16-le")
    now = bom + "\u4e0a,1\n".encode("utf-16-le")
    assert _g1_after(tmp_path, "export.csv", written, now) == said


def test_a_utf16_file_does_not_crash_and_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "u.csv"
    path.write_bytes(b"\xff\xfe" + "a,b\r\n".encode("utf-16-le"))
    assert input_digest(path) == sha256_of(path)
    assert input_digest_matches(path, sha256_of(path))


def test_an_embedded_nul_does_not_crash(tmp_path: Path) -> None:
    """It never did in Python; it did in R, which is why this is asserted on both sides."""
    path = tmp_path / "z.csv"
    path.write_bytes(b"a\x00b\r\n")
    assert len(input_digest(path)) == 64


# --- and the two languages must agree ---------------------------------------


def _rscript() -> str | None:
    """The newest R on this machine, rather than whatever is on PATH."""
    import os
    roots = sorted(Path(r"C:\Program Files\R").glob("R-*")) if os.name == "nt" else []
    for root in reversed(roots):
        exe = root / "bin" / "x64" / "Rscript.exe"
        if exe.exists():
            return str(exe)
    return shutil.which("Rscript")


CASES = {
    "empty.csv": b"",
    "no_newline.csv": b"a,b",
    "mixed.csv": b"id,value\n1,10\r\n2,20\r\n",
    "lone_cr_eof.csv": b"a,b\rc,d\r",
    "latin1.csv": b"name\n caf\xe9\n",
    "embedded_nul.csv": b"a\x00b\r\n",
    "utf16.csv": b"\xff\xfe" + "a,b\r\n".encode("utf-16-le"),
    "binary.xlsx": b"PK\x03\x04\r\n\x00rest",
    # Hashed byte for byte on both sides; R once still normalised them (#113's review).
    "notes.txt": b"a\r\nb\r\n",
    "query.sql": b"select 1;\r\n",
}


@pytest.mark.skipif(_rscript() is None, reason="R is not installed")
def test_the_r_emitter_agrees_byte_for_byte(tmp_path: Path) -> None:
    """`mg_input_digest` mirrors `input_digest` and must keep mirroring it.

    There was no such test when the input digest changed, and the R side then crashed on two
    of these cases — anything with an embedded NUL, because it converted to a string before
    normalising. A rule enforced on one side only is a rule an author steps around by
    switching language.
    """
    for name, data in CASES.items():
        (tmp_path / name).write_bytes(data)
    emit_r = Path(__file__).resolve().parent.parent / "r" / "manuscriptguard" / "R" / "emit.R"
    script = tmp_path / "probe.R"
    # The MISSING_DEPS guard of test_r_emitter.py: CI's windows-latest runners have R but not
    # `digest`. Only that condition skips; any other failure of emit.R still fails the test.
    script.write_text(
        'if (!requireNamespace("digest", quietly = TRUE)) {\n'
        '  cat("MISSING_DEPS\\n"); quit(status = 3)\n'
        "}\n"
        f'source({str(emit_r)!r})\n'
        f'for (n in c({", ".join(repr(n) for n in CASES)})) '
        f'cat(n, mg_input_digest(file.path({str(tmp_path)!r}, n)), "\n")\n',
        encoding="utf-8",
    )
    out = subprocess.run([_rscript(), str(script)], capture_output=True, text=True, timeout=180)
    if "MISSING_DEPS" in out.stdout:
        pytest.skip("R is present but digest is not installed")
    assert out.returncode == 0, out.stderr
    from_r = dict(line.split() for line in out.stdout.strip().splitlines() if line.strip())
    for name in CASES:
        assert from_r[name] == input_digest(tmp_path / name), f"{name} differs between R and Python"


# --- each file read once in a run --------------------------------------------
#
# `check` read every declared input whole, twice for a binary one (its bytes, then its digest),
# and again for each fragment that declared it. A study declaring seven gigabytes of a
# pharmacovigilance extract, several files in two fragments, waited over two minutes and held
# a whole file in memory for each. A run now takes each file's digests once, streamed where
# its line endings are content, and the memo ends with the run.


def _declared_by_two(project: Path, name: str, size: int) -> Path:
    """An input of `size` bytes, declared by two fragments of two scripts."""
    target = project / "data" / name
    target.write_bytes(bytes(range(256)) * (size // 256))
    for stem in ("09_first", "09_second"):
        script = project / "analysis" / f"{stem}.py"
        script.write_text("# reads the shared input\n", encoding="utf-8")
        em = Emitter(script, inputs=[target], root=project)
        em.value(f"{stem.replace('09_', 'shared_')}.n", 1)
        em.write(project / "results" / f"{stem}.json")
    return target


def _opened(monkeypatch: pytest.MonkeyPatch, target: Path) -> list[str]:
    """The modes `target` is opened in from now on, in order."""
    import pathlib

    opened: list[str] = []
    real = pathlib.Path.open
    wanted = target.resolve()

    def counting(self, mode="r", *args, **kwargs):
        if Path(self).resolve() == wanted:
            opened.append(mode)
        return real(self, mode, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", counting)
    return opened


@pytest.mark.parametrize("name", ["shared.parquet", "shared.csv"])
def test_a_check_reads_an_input_two_fragments_declare_once(
    project: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    from manuscript_guard.cli import _gate_run

    target = _declared_by_two(project, name, 64 * 1024)
    opened = _opened(monkeypatch, target)
    report, *_ = _gate_run(project)
    assert "input-changed" not in codes(report)
    assert len(opened) == 1, f"{name} was opened {len(opened)} times in one check: {opened}"


def test_a_binary_input_is_streamed_never_read_whole(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its bytes are its content, so nothing needs them all in memory at once: a reading of
    the whole of a 1.4 GB file is 1.4 GB held while it is hashed."""
    import pathlib

    from manuscript_guard.cli import _gate_run

    target = _declared_by_two(project, "shared.parquet", 64 * 1024)
    recorded = input_digest(target)
    real = pathlib.Path.read_bytes
    wanted = target.resolve()

    def refusing(self):
        if Path(self).resolve() == wanted:
            raise AssertionError(f"{self} was read whole")
        return real(self)

    monkeypatch.setattr(pathlib.Path, "read_bytes", refusing)
    assert input_digest(target) == recorded == sha256_of(target)
    assert input_digest_matches(target, recorded)
    report, *_ = _gate_run(project)
    assert "input-changed" not in codes(report)


def _recorded_as(project: Path, stem: str, name: str, digest: str) -> None:
    """Fragment `stem` records `digest` for the input `name`, its own sidecar kept true: what
    a fragment written before the input changed, or by an older emitter, records."""
    import json

    from manuscript_guard.emit import write_digest

    fragment = project / "results" / f"{stem}.json"
    document = json.loads(fragment.read_text(encoding="utf-8"))
    for declared in document["provenance"]["inputs"]:
        if declared["path"].endswith(name):
            declared["sha256"] = digest
    fragment.write_bytes(json.dumps(document, indent=2).encode("utf-8"))
    write_digest(fragment)


def test_a_stale_record_of_a_binary_input_reads_it_no_more(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A binary input has one digest: once the run has it, a second fragment recording
    another, written before the data were refreshed, is told from it without a read."""
    from manuscript_guard.cli import _gate_run

    target = _declared_by_two(project, "shared.parquet", 64 * 1024)
    _recorded_as(project, "09_second", "shared.parquet", "0" * 64)
    opened = _opened(monkeypatch, target)
    report, *_ = _gate_run(project)
    changed = [f for f in report.findings if f.code == "input-changed"]
    assert [f.path.name for f in changed] == ["09_second.json"]
    assert len(opened) == 1, f"opened {len(opened)} times in one check: {opened}"


def test_a_text_input_recorded_in_two_spellings_is_read_once(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One fragment records a CSV's content with LF, as the emitter does, and another its
    CRLF bytes, as an emitter before line endings were left out did: both match, from the
    one reading of the file."""
    from manuscript_guard.cli import _gate_run

    target = _declared_by_two(project, "shared.csv", 64 * 1024)
    target.write_bytes(b"id,value\r\n" + b"1,10\r\n" * 4096)
    for stem in ("09_first", "09_second"):
        _recorded_as(project, stem, "shared.csv", input_digest(target))
    _recorded_as(project, "09_second", "shared.csv", sha256_of(target))
    assert input_digest(target) != sha256_of(target)
    opened = _opened(monkeypatch, target)
    report, *_ = _gate_run(project)
    assert "input-changed" not in codes(report)
    assert len(opened) == 1, f"opened {len(opened)} times in one check: {opened}"


def test_the_digests_a_run_takes_end_with_the_run(project: Path) -> None:
    """A file rewritten between two checks, to the same size and the same modification time,
    is read again by the second: nothing a run learnt is kept for the next one."""
    import os

    from manuscript_guard.cli import _gate_run

    target = _declared_by_two(project, "shared.parquet", 64 * 1024)
    first, *_ = _gate_run(project)
    assert "input-changed" not in codes(first)
    stamp = target.stat()
    target.write_bytes(bytes(reversed(target.read_bytes())))
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert target.stat().st_size == stamp.st_size
    assert target.stat().st_mtime_ns == stamp.st_mtime_ns
    second, *_ = _gate_run(project)
    assert "input-changed" in codes(second)


@pytest.mark.parametrize("data", [
    b"id,value\n1,10\n", b"id,value\r\n1,10\r\n", b"id,value\r1,10\r",
    b"id,value\n1,10\r\n2,20\r\n", b"\xff\xfe" + "a,b\r\n".encode("utf-16-le"), b"",
], ids=["lf", "crlf", "cr", "mixed", "utf16", "empty"])
def test_a_run_answers_as_a_single_call_does(tmp_path: Path, data: bytes) -> None:
    """Inside a run and outside one, the same file matches the same digests and no other."""
    from manuscript_guard.emit import digests_once

    path = tmp_path / "input.csv"
    path.write_bytes(data)
    lf = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    spellings = {sha256_of(path)} | {
        __import__("hashlib").sha256(text).hexdigest()
        for text in (lf, lf.replace(b"\n", b"\r\n"), lf.replace(b"\n", b"\r"))
    }
    tried = spellings | {"0" * 64}
    outside = {digest: input_digest_matches(path, digest) for digest in tried}
    with digests_once(), digests_once():
        inside = {digest: input_digest_matches(path, digest) for digest in tried}
        assert input_digest(path) == input_digest(path)
        normal = input_digest(path)
    assert inside == outside
    assert normal == input_digest(path)
    assert not outside["0" * 64]
