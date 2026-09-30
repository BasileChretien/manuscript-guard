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
from pathlib import Path

import pytest

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import (
    Emitter,
    input_digest,
    input_digest_matches,
    sha256_of,
    source_digest,
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


def test_utf16_is_not_normalised(tmp_path: Path) -> None:
    """In UTF-16, 0x0D and 0x0A are bytes of ordinary characters. Rewriting them corrupts
    text rather than reformatting it: U+340D and U+340A would become the same file. Excel's
    Unicode export and many Japanese-Windows CSV exports are UTF-16, so this is not exotic."""
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_bytes(b"\xff\xfe" + "\u340d".encode("utf-16-le"))
    b.write_bytes(b"\xff\xfe" + "\u340a".encode("utf-16-le"))
    assert input_digest(a) != input_digest(b)


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
    script.write_text(
        f'source({str(emit_r)!r})\n'
        f'for (n in c({", ".join(repr(n) for n in CASES)})) '
        f'cat(n, mg_input_digest(file.path({str(tmp_path)!r}, n)), "\n")\n',
        encoding="utf-8",
    )
    out = subprocess.run([_rscript(), str(script)], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    from_r = dict(line.split() for line in out.stdout.strip().splitlines() if line.strip())
    for name in CASES:
        assert from_r[name] == input_digest(tmp_path / name), f"{name} differs between R and Python"
