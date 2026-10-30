"""`audit --package` and `--report-draft`: a package held to its own manifest, and the draft
of a referee's report (docs/refereeing.md, "A package"; DESIGN.md, "A package held to its own
manifest").

The package is opened as an untrusted archive: each refusal is tested with nothing written
outside the temporary folder. What `--strict` counts is held both ways, a whole package
passing and each exact fault failing, a consistent rewrite of the manifest among them, which
only the results' own records can catch. The draft is held to its first line, its sections,
its "read none" and to giving the same bytes twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.auditing import READER_FLAGS
from manuscript_guard.auditing.draft import FIRST
from manuscript_guard.auditing.package import WORDING
from manuscript_guard.auditing.unpack import Refused, members
from manuscript_guard.cli import main
from manuscript_guard.emit import source_digest, write_digest

PAPER = (
    "# Introduction\n\nThe colour of the urine was recorded in every patient.\n\n"
    "# Methods\n\nWe counted the patients seen in each month.\n\n"
    "# Results\n\nOf 412 patients, 37 had dark urine at the first visit.\n\n"
    "# Discussion\n\nDark urine was common among the patients seen.\n"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sign(root: Path, *, checks: str = "passed", leave_out: tuple[str, ...] = ()) -> None:
    """MANIFEST.yaml and SHA256SUMS for every file of `root` but those named, as `package`
    writes them."""
    for old in ("MANIFEST.yaml", "SHA256SUMS"):
        (root / old).unlink(missing_ok=True)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    entries = [{"file": p.relative_to(root).as_posix(), "bytes": p.stat().st_size,
                "sha256": _sha(p)} for p in files
               if p.relative_to(root).as_posix() not in leave_out]  # fmt: skip
    manifest = root / "MANIFEST.yaml"
    manifest.write_text(yaml.safe_dump({"schema": "manuscript-guard/package/1",
                                        "packaged_with": "manuscript-guard 0.0.0",
                                        "checks": checks, "files": entries,
                                        "withheld": [{"path": "data/raw.csv",
                                                      "why": "the custodian keeps it"}]},
                                       sort_keys=False), encoding="utf-8", newline="\n")
    named = sorted([(e["file"], e["sha256"]) for e in entries]
                   + [("MANIFEST.yaml", _sha(manifest))])  # fmt: skip
    (root / "SHA256SUMS").write_text("".join(f"{sha}  {path}\n" for path, sha in named),
                                     encoding="utf-8", newline="\n")  # fmt: skip


def small_package(folder: Path) -> Path:
    """A package of one script and the results it wrote: 412 patients, 37 with dark urine."""
    root = folder / "pkg"
    script = root / "analysis" / "count.py"
    script.parent.mkdir(parents=True)
    script.write_text("print(412, 37)\n", encoding="utf-8", newline="\n")
    result = root / "results" / "count.json"
    result.parent.mkdir()
    result.write_text(json.dumps({
        "provenance": {"generated_by": "analysis/count.py", "generated_at": "2026-01-01",
                       "generated_by_sha256": source_digest(script)},
        "values": {"patients": {"value": 412}, "dark": {"value": 37}},
    }, indent=2), encoding="utf-8", newline="\n")  # fmt: skip
    write_digest(result)
    sign(root)
    return root


def zipped(root: Path, archive: Path, extra: list[tuple[zipfile.ZipInfo | str, bytes]] = ()
           ) -> Path:  # fmt: skip
    with zipfile.ZipFile(archive, "w") as out:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                out.write(path, f"{root.name}/{path.relative_to(root).as_posix()}")
        for name, data in extra:
            out.writestr(name, data)
    return archive


def audited(capsys, *argv: str) -> tuple[int, dict, str]:
    code = main(["audit", *argv, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def codes(report: dict, counted: bool | None = None) -> list[str]:
    return [f["code"] for f in report["findings"]
            if f["section"] == "Package" and (counted is None or f["counted"] is counted)]


# ----------------------------------------------------------------------- a whole package


def test_a_whole_package_passes_strict_and_says_what_it_is_worth(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    for given in (root, zipped(root, tmp_path / "pkg.zip")):
        code, report, err = audited(capsys, "--package", str(given), "--strict")
        assert code == 0, report
        assert report["ok"] and codes(report, True) == []
        assert report["counts"]["package_results_by_script"] == 1
        assert report["package_said"] == WORDING and WORDING in err
        assert "package-withheld" in codes(report)
    main(["audit", "--package", str(root)])
    out = capsys.readouterr().out
    assert WORDING in out and "whole as written" in out and "container" in out


def test_the_package_command_writes_what_the_audit_reads_as_whole(project: Path, capsys) -> None:
    """A package `package` wrote, folder and .zip, passes: the schema and the writer agree."""
    (project / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    assert main(["package", str(project)]) == 0, capsys.readouterr().out
    capsys.readouterr()
    (folder,) = [p for p in (project / "build" / "package").iterdir() if p.is_dir()]
    for given in (folder, folder.with_suffix(".zip")):
        code, report, _err = audited(capsys, "--package", str(given), "--strict")
        assert code == 0 and codes(report, True) == [], report["findings"]
        assert "package-file-unlisted" not in codes(report)
        assert report["counts"]["package_results"] >= 1
        assert report["counts"]["package_results_by_script"] == report["counts"][
            "package_results"]


# ------------------------------------------------------------------------- what it finds


def test_a_file_changed_or_gone_since_the_manifest_is_counted(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "analysis" / "count.py").write_text("print(413, 37)\n", encoding="utf-8")
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 1 and "package-file-changed" in codes(report, True)
    (root / "analysis" / "count.py").unlink()
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 1 and "package-file-missing" in codes(report, True)


def test_a_consistent_rewrite_passes_the_manifest_and_not_the_results(tmp_path, capsys) -> None:
    """The manifest is the authors': rewritten with the files, it is whole again. A result's
    own records are what is left to say that the script or the result changed."""
    root = small_package(tmp_path)
    (root / "analysis" / "count.py").write_text("print(413, 37)\n", encoding="utf-8")
    sign(root)
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 1
    assert codes(report, True) == ["package-result-not-by-script"]
    root = small_package(tmp_path / "again")
    result = root / "results" / "count.json"
    result.write_text(result.read_text(encoding="utf-8").replace("412", "421"), encoding="utf-8")
    sign(root)
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 1 and codes(report, True) == ["package-result-edited"]


def test_what_is_warned_of_is_not_counted(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "notes.txt").write_text("left here\n", encoding="utf-8")
    sign(root, checks="SKIPPED - packaged with --skip-checks", leave_out=("notes.txt",))
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 0
    assert {"package-file-unlisted", "package-checks-skipped"} <= set(codes(report, False))
    (root / "SHA256SUMS").unlink()
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 0 and "package-sums-missing" in codes(report, False)


def test_a_manifest_that_is_not_one_is_counted(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "MANIFEST.yaml").write_text("schema: something/else\nfiles: []\n", encoding="utf-8")
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 1 and "package-manifest-invalid" in codes(report, True)


def test_a_script_not_packaged_or_a_result_with_no_digest_warns(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "analysis" / "count.py").unlink()
    (root / "results" / "count.json.sha256").unlink()
    sign(root)
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 0
    assert {"package-script-missing", "package-result-no-digest"} <= set(codes(report, False))


def test_verification_json_is_quoted_and_its_results_digest_held(tmp_path, capsys) -> None:
    from manuscript_guard.assurance import results_digest

    root = small_package(tmp_path)
    record = {"check": {"passed": False, "gates": {"G2": {"failing": 1}, "G6": {"failing": 0}}},
              "digests": {"results_sha256": results_digest(root / "results")}}
    (root / "VERIFICATION.json").write_text(json.dumps(record), encoding="utf-8")
    sign(root)
    _code, report, _ = audited(capsys, "--package", str(root))
    quoted = [f for f in report["findings"] if f["code"] == "package-verification-quoted"]
    assert quoted and "did not pass, failing in G2" in quoted[0]["message"]
    assert "package-verification-differs" not in codes(report)
    record["digests"]["results_sha256"] = "0" * 64
    (root / "VERIFICATION.json").write_text(json.dumps(record), encoding="utf-8")
    sign(root)
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 0 and "package-verification-differs" in codes(report, False)


def test_a_receipt_not_packaged_or_not_the_one_harvested_under_is_said(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    result = root / "results" / "count.json"
    document = json.loads(result.read_text(encoding="utf-8"))
    document["provenance"]["harvested"] = {
        "output": "output/count.csv", "sha256": "a" * 64, "spec": {"key": "count"},
        "receipt": {"path": "receipts/site.receipt.json", "sha256": "b" * 64, "site": "site"}}
    result.write_text(json.dumps(document), encoding="utf-8")
    write_digest(result)
    sign(root)
    _code, report, _ = audited(capsys, "--package", str(root))
    assert "package-receipt-not-packaged" in codes(report)
    (root / "receipts").mkdir()
    (root / "receipts" / "site.receipt.json").write_text("{}", encoding="utf-8")
    sign(root)
    _code, report, _ = audited(capsys, "--package", str(root))
    assert "package-receipt-differs" in codes(report)


# --------------------------------------------------------------------- with the paper


def test_a_paper_is_held_to_the_packaged_results(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    code, report, _ = audited(capsys, str(paper), "--package", str(root), "--strict")
    assert report["compared"] and report["counts"]["outputs"] == 1
    assert report["counts"]["matched"] >= 2 and code == 0, report["findings"]
    paper.write_text(PAPER.replace("37 had", "38 had"), encoding="utf-8")
    code, report, _ = audited(capsys, str(paper), "--package", str(root), "--strict")
    assert code == 1 and any(f["code"] == "not-found" and "38" in f["message"]
                             for f in report["findings"])  # fmt: skip


def test_an_option_that_reads_a_paper_wants_a_paper(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    assert main(["audit", "--package", str(root), "--design", "observational"]) == 2
    assert "reads a paper" in capsys.readouterr().err
    assert main(["audit"]) == 2
    assert "--package" in capsys.readouterr().err


# ------------------------------------------------------------------------ the archive


@pytest.mark.parametrize("name", ["../escape.txt", "/escape.txt", "C:escape.txt",
                                  "pkg/a\\..\\..\\escape.txt", "pkg/CON.txt"])
def test_a_member_that_could_land_outside_is_refused_before_anything_is_written(
    tmp_path, capsys, monkeypatch, name: str
) -> None:
    from manuscript_guard.auditing import unpack

    monkeypatch.setattr(unpack, "windows", lambda: True)  # `CON` is a device's on Windows
    root = small_package(tmp_path)
    archive = zipped(root, tmp_path / "bad.zip", [(name, b"x")])
    with pytest.raises(Refused, match="nothing was unpacked"):
        members(archive)
    code, report, err = audited(capsys, "--package", str(archive))
    assert code == 2 and not report["ok"] and "nothing was unpacked" in err


def test_a_link_an_encrypted_member_or_two_names_in_one_case_are_refused(tmp_path) -> None:
    root = small_package(tmp_path)
    link = zipfile.ZipInfo("pkg/link")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    for extra, said in (([(link, b"/etc/passwd")], "is a link"),
                        ([("pkg/README.md", b"a"), ("pkg/readme.md", b"b")], "one name")):
        archive = zipped(root, tmp_path / "bad.zip", extra)
        with pytest.raises(Refused, match=said):
            members(archive)
        archive.unlink()


def test_an_archive_past_the_limits_is_refused(tmp_path, monkeypatch) -> None:
    from manuscript_guard.auditing import unpack

    archive = zipped(small_package(tmp_path), tmp_path / "pkg.zip")
    monkeypatch.setattr(unpack, "MAX_MEMBERS", 2)
    with pytest.raises(Refused, match="members"):
        members(archive)
    monkeypatch.setattr(unpack, "MAX_MEMBERS", 50)
    monkeypatch.setattr(unpack, "MAX_BYTES", 10)
    with pytest.raises(Refused, match="bytes"):
        members(archive)


def test_a_folder_holding_a_link_or_no_manifest_is_refused(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "MANIFEST.yaml").unlink()
    code, _report, err = audited(capsys, "--package", str(root))
    assert code == 2 and "MANIFEST.yaml" in err
    root = small_package(tmp_path / "linked")
    try:
        (root / "outside").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("this system makes no symbolic link without privileges")
    code, _report, err = audited(capsys, "--package", str(root))
    assert code == 2 and "link" in err


# ------------------------------------------------------------------------ the draft


def test_the_draft_has_its_parts_and_is_the_same_twice(tmp_path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    first, second = tmp_path / "one.md", tmp_path / "two.md"
    for target in (first, second):
        assert main(["audit", str(paper), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = first.read_text(encoding="utf-8")
    assert text == second.read_text(encoding="utf-8")
    assert text.splitlines()[0] == FIRST
    for heading in ("## What was read", "### What was not checked", "## Exact findings",
                    "## Further findings", "## References", "## Language and notation",
                    "## Checks that ran and found nothing"):
        assert heading in text, heading
    assert "reporting checklist" in text and "The models" in text
    assert "Table totals and categories against their n: read none." in text
    assert "no problems" not in text.lower()
    assert "Tests, intervals and n (%) against the numbers beside them: read none." in text


def test_the_draft_lists_an_exact_finding_with_its_place(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "analysis" / "count.py").write_text("print(413)\n", encoding="utf-8")
    target = tmp_path / "draft.md"
    assert main(["audit", "--package", str(root), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    exact = text.split("## Exact findings")[1].split("## Further findings")[0]
    assert "analysis/count.py" in exact and "SHA-256" in exact
    assert WORDING in text


def test_the_draft_never_writes_over_a_file(tmp_path, capsys) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    target = tmp_path / "draft.md"
    target.write_text("my own words\n", encoding="utf-8")
    assert main(["audit", str(paper), "--report-draft", str(target)]) == 2
    assert target.read_text(encoding="utf-8") == "my own words\n"
    assert "there already" in capsys.readouterr().err
    assert main(["audit", str(paper), "--report-draft", str(tmp_path / "draft.txt")]) == 2
    assert main(["audit", str(paper), "--report-draft", str(paper)]) == 2


def test_compare_writes_a_draft_with_v2_s_exact_findings(tmp_path, capsys) -> None:
    old = tmp_path / "v1.md"
    old.write_text(PAPER, encoding="utf-8")
    new = tmp_path / "v2.md"
    new.write_text(PAPER.replace("We counted", "We counted all").replace(
        "# Discussion", "| Group | n |\n|---|---|\n| A | 3 |\n| B | 4 |\n| Total | 9 |\n\n"
        "# Discussion"), encoding="utf-8")  # fmt: skip
    target = tmp_path / "draft.md"
    assert main(["compare", str(old), str(new), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    assert text.splitlines()[0] == FIRST
    exact = text.split("## Exact findings")[1].split("## Further findings")[0]
    assert "[new in v2]" in exact and "sum" in exact.lower() or "total" in exact.lower()
    assert "Whether a change answers a comment" in text
    assert "addressed" not in text.lower()


def test_the_hook_asks_before_an_agent_reads_a_package_or_writes_a_draft() -> None:
    from manuscript_guard.hooks import _reads_in_confidence

    assert {"--package", "--report-draft"} <= set(READER_FLAGS)
    for command in ("manuscript-guard audit --package pkg.zip",
                    "mguard audit paper.docx --report-draft=draft.md"):
        assert _reads_in_confidence(command) is not None, command


# ------------------------------------------------------------------- review round 1


def test_v2_audited_is_not_said_to_find_nothing_where_its_findings_are_exact(
    tmp_path, capsys
) -> None:
    """Round 1 of #487: v2's counted findings go to the exact findings, and "v2 audited"
    found them all the same."""
    v1 = ("# Abstract\n\nWe saw the patients of the clinic.\n\n# Methods\n\nWe counted them.\n\n"
          "# Results\n\nWe saw them all.\n\n# Discussion\n\nThey were seen.\n")
    v2 = v1.replace("We saw them all.\n", "We saw them all.\n\n| Group | n |\n|---|---|\n"
                    "| A | 3 |\n| B | 4 |\n| Total | 9 |\n")  # fmt: skip
    (tmp_path / "v1.md").write_text(v1, encoding="utf-8")
    (tmp_path / "v2.md").write_text(v2, encoding="utf-8")
    target = tmp_path / "draft.md"
    assert main(["compare", str(tmp_path / "v1.md"), str(tmp_path / "v2.md"),
                 "--report-draft", str(target)]) == 0  # fmt: skip
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    exact = text.split("## Exact findings")[1].split("## Further findings")[0]
    nothing = text.split("## Checks that ran and found nothing")[1]
    assert "[new in v2]" in exact
    assert "v2 audited" not in nothing


def test_an_edited_manifest_is_one_changed_file(tmp_path, capsys) -> None:
    """Round 1 of #487: SHA256SUMS lists MANIFEST.yaml, and the manifest was checked twice."""
    root = small_package(tmp_path)
    with (root / "MANIFEST.yaml").open("a", encoding="utf-8") as handle:
        handle.write("# edited\n")
    code, report, _ = audited(capsys, "--package", str(root), "--strict")
    assert code == 1
    assert codes(report, True) == ["package-file-changed"]
    assert report["counts"]["package_counted"] == 1


@pytest.mark.parametrize("name", ["pkg/a?.json", "pkg/a*b", "pkg/a<b", "pkg/a|b", 'pkg/a"b',
                                  "pkg/x.", "pkg/x ", "pkg/./a", "pkg/a" + chr(7),
                                  "pkg/COM" + chr(0xB9), "pkg/LPT" + chr(0xB3) + ".txt",
                                  "pkg/CON .txt"])
def test_a_name_a_file_system_cannot_hold_is_refused(tmp_path, capsys, monkeypatch,
                                                     name: str) -> None:  # fmt: skip
    """On Windows: elsewhere the names Windows cannot hold are written, or refused when the
    file system cannot hold one (round 2 of #487)."""
    from manuscript_guard.auditing import unpack

    monkeypatch.setattr(unpack, "windows", lambda: True)
    archive = zipped(small_package(tmp_path), tmp_path / "bad.zip", [(name, b"x")])
    with pytest.raises(Refused, match="nothing was unpacked"):
        members(archive)
    code, report, _err = audited(capsys, "--package", str(archive))
    assert code == 2 and not report["ok"]


def test_a_name_both_a_file_and_a_folder_is_refused(tmp_path, capsys) -> None:
    archive = zipped(small_package(tmp_path), tmp_path / "bad.zip",
                     [("pkg/a", b"x"), ("pkg/a/b", b"y")])  # fmt: skip
    with pytest.raises(Refused, match="a file and a folder"):
        members(archive)
    code, _report, _err = audited(capsys, "--package", str(archive))
    assert code == 2


def test_a_member_that_cannot_be_written_is_a_refusal(tmp_path, capsys, monkeypatch) -> None:
    from manuscript_guard.auditing import unpack

    archive = zipped(small_package(tmp_path), tmp_path / "pkg.zip")

    def cannot(*_args, **_kwargs):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(unpack.Path, "open", cannot)
    code, report, err = audited(capsys, "--package", str(archive))
    assert code == 2 and not report["ok"] and "cannot be written" in err


@pytest.mark.parametrize("record", [
    [], {"check": [], "digests": {}}, {"check": {"gates": []}, "digests": {}},
    {"check": {"passed": True, "gates": {}}, "digests": []},
    {"check": {"passed": True, "gates": {"G1": []}}, "digests": {"results_sha256": 3}},
])  # fmt: skip
def test_a_verification_record_of_another_shape_is_unreadable(tmp_path, capsys, record) -> None:
    root = small_package(tmp_path)
    (root / "VERIFICATION.json").write_text(json.dumps(record), encoding="utf-8")
    sign(root)
    code, report, _ = audited(capsys, "--package", str(root))
    assert code == 0
    assert {"package-verification-unreadable", "package-verification-quoted",
            "package-verification-differs"} & set(codes(report))  # fmt: skip


def test_a_folder_where_a_results_file_is_crashes_nothing(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "results" / "odd.json").mkdir()
    (root / "results" / "odd.json.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    record = {"check": {"passed": True, "gates": {}}, "digests": {"results_sha256": "0" * 64}}
    (root / "VERIFICATION.json").write_text(json.dumps(record), encoding="utf-8")
    sign(root)
    code, report, _ = audited(capsys, "--package", str(root))
    assert code == 0 and report["counts"]["package_results"] == 1


def test_packaged_results_that_load_as_no_output_are_refused_with_a_paper(
    tmp_path, capsys
) -> None:
    root = small_package(tmp_path)
    (root / "results" / "count.json").write_bytes(b"{\x00}")
    sign(root)
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    code, report, err = audited(capsys, str(paper), "--package", str(root))
    assert code == 2 and not report["ok"]
    assert "--package" in err and "nothing it can read" in err


def test_the_json_says_the_wording_with_a_paper_too(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    _code, report, _ = audited(capsys, str(paper), "--package", str(root))
    assert report["package_said"] == WORDING


def test_a_manifest_that_lists_no_file_is_not_said_to_be_whole(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "MANIFEST.yaml").write_text("schema: manuscript-guard/package/1\nfiles: []\n",
                                        encoding="utf-8")  # fmt: skip
    (root / "SHA256SUMS").unlink()
    main(["audit", "--package", str(root)])
    out = capsys.readouterr().out
    assert "the manifest lists no file" in out
    assert "Each file listed was read" not in out


# ------------------------------------------------------------------- review round 2


def test_a_dry_run_draft_says_the_registries_were_not_asked(tmp_path, capsys) -> None:
    """Round 2 of #487: under --lookup --dry-run the draft said the entries were asked about
    and nothing was reported; what would be asked is listed, each once."""
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER + "\n# References\n\n1. Example A. A study of urine. J Ex. "
                     "2019;1:1-9. doi:10.1000/example.1\n", encoding="utf-8")  # fmt: skip
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--lookup", "--dry-run", "--report-draft",
                 str(target)]) == 0  # fmt: skip
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    assert "asked about" not in text
    assert "not looked up (dry run)" in text
    references = text.split("## References")[1].split("## Language and notation")[0]
    assert references.count("would ask") == 1


def test_an_abstract_matched_only_as_a_rounding_is_not_said_to_find_nothing(
    tmp_path, capsys
) -> None:
    """Round 2 of #487: a rounded match is a note the check reported."""
    paper = tmp_path / "paper.md"
    paper.write_text("# Abstract\n\nOf the patients, 12% had dark urine.\n\n# Methods\n\nWe "
                     "counted them.\n\n# Results\n\nOf the patients, 12.3% had dark urine.\n",
                     encoding="utf-8")  # fmt: skip
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    assert "abstract" in text.split("## Further findings")[1].lower()
    assert "Abstract against Results" not in text.split("## Checks that ran and found nothing")[1]


def test_a_name_only_windows_cannot_hold_is_refused_only_on_windows(
    tmp_path, monkeypatch
) -> None:
    """Round 2 of #487: a Linux project's `analysis/aux.R` packages, and its package is read
    on Linux; Windows cannot write it, and says so before anything is unpacked."""
    from manuscript_guard.auditing import unpack

    archive = zipped(small_package(tmp_path), tmp_path / "pkg.zip",
                     [("pkg/analysis/aux.R", b"x"), ("pkg/data/a:b?.csv", b"y")])  # fmt: skip
    monkeypatch.setattr(unpack.os, "name", "posix")
    assert len(members(archive)) > 2
    monkeypatch.setattr(unpack.os, "name", "nt")
    with pytest.raises(Refused, match="Windows"):
        members(archive)
    # Wherever it is read, a drive is refused, and a backslash, where zipfile leaves one in a
    # name: on Windows it reads each as a "/".
    monkeypatch.setattr(unpack.os, "name", "posix")
    names = ["C:pkg/a"] + (["pkg/a" + chr(92) + "b"] if os.sep == "/" else [])
    for at, name in enumerate(names):
        member = zipfile.ZipInfo("placeholder")
        member.filename = name  # as written, not as Windows' zipfile turns a backslash
        bad = zipped(small_package(tmp_path / str(at)), tmp_path / f"{at}.zip",
                     [(member, b"x")])  # fmt: skip
        with pytest.raises(Refused):
            members(bad)


def test_a_package_with_a_name_windows_keeps_is_read_as_the_system_can(
    project: Path, capsys
) -> None:
    """The example packaged with `analysis/aux.R`: read whole where the system can hold the
    name, and refused with the Windows sentence where it cannot."""
    import os

    (project / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    if os.name != "nt":
        (project / "analysis" / "aux.R").write_text("# helpers\n", encoding="utf-8")
    assert main(["package", str(project)]) == 0, capsys.readouterr().out
    capsys.readouterr()
    (folder,) = [p for p in (project / "build" / "package").iterdir() if p.is_dir()]
    archive = folder.with_suffix(".zip")
    if os.name == "nt":
        with zipfile.ZipFile(archive, "a") as out:
            out.writestr(f"{folder.name}/analysis/aux.R", "# helpers\n")
        code, _report, err = audited(capsys, "--package", str(archive), "--strict")
        assert code == 2 and "Windows keeps for a device" in err
    else:
        code, report, _err = audited(capsys, "--package", str(archive), "--strict")
        assert code == 0, report["findings"]
        assert "package-file-unlisted" not in codes(report)


def test_a_receipt_warning_is_not_said_to_find_nothing(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    result = root / "results" / "count.json"
    document = json.loads(result.read_text(encoding="utf-8"))
    document["provenance"]["harvested"] = {
        "output": "output/count.csv", "sha256": "a" * 64, "spec": {"key": "count"},
        "receipt": {"path": "receipts/site.receipt.json", "sha256": "b" * 64, "site": "site"}}
    result.write_text(json.dumps(document), encoding="utf-8")
    write_digest(result)
    (root / "receipts").mkdir()
    (root / "receipts" / "site.receipt.json").write_text("{}", encoding="utf-8")
    sign(root)
    target = tmp_path / "d.md"
    assert main(["audit", "--package", str(root), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    nothing = target.read_text(encoding="utf-8").split("## Checks that ran and found nothing")[1]
    assert "Package results" not in nothing


def test_a_folder_named_as_a_results_file_is_not_an_output(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    (root / "results" / "odd.json").mkdir()
    sign(root)
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER, encoding="utf-8")
    code, report, _ = audited(capsys, str(paper), "--package", str(root))
    assert code == 0 and report["counts"]["outputs"] == 1


# ------------------------------------------------------------------ fix-only round


REFERENCED = PAPER + ("\n# References\n\n1. Example A. A study of urine. J Ex. 2019;1:1-9. "
                      "doi:10.1000/example.1\n")


@pytest.mark.parametrize(("came", "said"), [
    ("kept", "1 entry looked up, 1 answered from the records kept"),
    ("asked", "1 entry asked about"),
])  # fmt: skip
def test_a_lookup_draft_lists_no_asked_bullet(tmp_path, capsys, monkeypatch, came, said) -> None:
    """Fix-only round of #487: what was asked is the report's to list, not the draft's."""
    import dataclasses

    from manuscript_guard.auditing import references

    real = references.look_up

    def kept(censuses, **kwargs):
        return [dataclasses.replace(one, came=came)
                for one in real(censuses, **{**kwargs, "dry_run": True})]

    monkeypatch.setattr(references, "look_up", kept)
    paper = tmp_path / "paper.md"
    paper.write_text(REFERENCED, encoding="utf-8")
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--lookup", "--report-draft", str(target)]) == 0
    capsys.readouterr()
    text = target.read_text(encoding="utf-8")
    assert "asked doi" not in text and "asked Crossref" not in text
    # Answered from the records kept, it was not asked about this time.
    assert f"The registries (--lookup): {said}" in text


@pytest.mark.parametrize(("tail", "said"), [
    ("", "no reference list was read"),
    ("\n# References\n\n", "no reference gives a DOI or a PMID"),  # a list, no entry read
])  # fmt: skip
def test_a_lookup_draft_with_no_reference_list_says_so(tmp_path, capsys, tail, said) -> None:
    paper = tmp_path / "paper.md"
    paper.write_text(PAPER + tail, encoding="utf-8")
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--lookup", "--report-draft", str(target)]) == 0
    capsys.readouterr()
    assert f"not asked, since {said}" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("dry_run", [False, True])
def test_a_lookup_with_nothing_to_ask_says_so(tmp_path, capsys, dry_run: bool) -> None:
    paper = tmp_path / "paper.md"
    unidentified = "\n# References\n\n1. Example A. A study of urine. J Ex. 2019;1:1-9.\n"
    paper.write_text(PAPER + unidentified, encoding="utf-8")
    target = tmp_path / "d.md"
    assert main(["audit", str(paper), "--lookup", *(["--dry-run"] if dry_run else []),
                 "--report-draft", str(target)]) == 0  # fmt: skip
    capsys.readouterr()
    unchecked = target.read_text(encoding="utf-8").split("### What was not checked")[1]
    assert "no reference gives a DOI or a PMID" in unchecked.split("## Exact findings")[0]


@pytest.mark.parametrize("code", [10, 13, 11, 12, 0x1C, 0x1D, 0x1E, 0x85, 0x2028, 0x2029])
def test_a_name_with_a_line_break_is_refused_everywhere(monkeypatch, code: int) -> None:
    from manuscript_guard.auditing import unpack

    monkeypatch.setattr(unpack, "windows", lambda: False)
    assert "line break" in unpack._unsafe("pkg/a" + chr(code) + "b.json")


def test_a_drive_is_said_to_be_a_drive(monkeypatch) -> None:
    from manuscript_guard.auditing import unpack

    monkeypatch.setattr(unpack, "windows", lambda: False)
    for name in ("x:notes", "C:x"):
        said = unpack._unsafe(name)
        assert "Windows drive" in said and "root" not in said, name
    assert "root" in unpack._unsafe("/x")


def test_a_verification_digest_that_differs_is_found_in_the_draft(tmp_path, capsys) -> None:
    root = small_package(tmp_path)
    record = {"check": {"passed": True, "gates": {}}, "digests": {"results_sha256": "0" * 64}}
    (root / "VERIFICATION.json").write_text(json.dumps(record), encoding="utf-8")
    sign(root)
    target = tmp_path / "d.md"
    assert main(["audit", "--package", str(root), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    nothing = target.read_text(encoding="utf-8").split("## Checks that ran and found nothing")[1]
    assert "Package results" not in nothing


def test_a_verification_record_that_holds_leaves_the_results_row_clean(tmp_path, capsys) -> None:
    # The record is quoted in a note whenever there is one; the quote is not a finding.
    from manuscript_guard.assurance import results_digest

    root = small_package(tmp_path)
    digest = results_digest(root / "results")
    record = {"check": {"passed": True, "gates": {}}, "digests": {"results_sha256": digest}}
    (root / "VERIFICATION.json").write_text(json.dumps(record), encoding="utf-8")
    sign(root)
    target = tmp_path / "d.md"
    assert main(["audit", "--package", str(root), "--report-draft", str(target)]) == 0
    capsys.readouterr()
    nothing = target.read_text(encoding="utf-8").split("## Checks that ran and found nothing")[1]
    assert "Package results" in nothing
