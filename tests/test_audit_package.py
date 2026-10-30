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
    tmp_path, capsys, name: str
) -> None:
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
