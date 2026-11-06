"""Hold a built audit page to the command line, and open the site's landing page.

    python web/test/check.py --site _site --docx build/manuscript.docx \\
        --results results/01_disproportionality.json --markdown manuscript/main.md

For each case (the .docx against the results, the .docx alone, the Markdown alone, the
.docx against the results under names a reader may give them, outside ASCII and with
spaces, under names that start with "-", and against two outputs whose names the page once
made one), the command line's `audit` is run here, then the same command is run as the page
runs it, in Node (`parity.mjs`): its report, what it says on stderr, its exit code and its
`--json` must be the command line's. Then the site is opened in each browser named
(`browser.mjs`): the landing page must load its style and pictures and ask no other host,
and the audit page must start under its own policy, give the same report, notes and exit
code for each case from the files as chosen, send nothing, and refuse every request "Test the
rules" tries.

The command line here must be the one the wheel was built from, with the pandoc the page's
pandoc.wasm is (pins.json), which is what CI's `web` job and the Pages workflow install.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEST = Path(__file__).resolve().parent
#: The folder of the site the audit page is in (AUDIT in web/build.py).
AUDIT = "audit"
NODE = shutil.which("node") or "node"
#: A paper and an output named as a reader may name them. The page once wrote each file
#: under its name made ASCII, so two such names became one file (round 1 of #527).
PAPER, OUTPUT = "Mon article (v3).docx", "résultats 結果.json"
#: Names that start with "-", which the page gives the command as `./name`, and two outputs
#: that were one file under the names made ASCII (round 2 of #527).
DASHED_PAPER, DASHED_OUTPUT = "-paper.docx", "-results.json"
ALIKE = ("résultats.json", "rèsultats.json")


def argument(name: str) -> str:
    """A file's name as the page puts it in the command (worker.js)."""
    return "./" + name if name.startswith("-") else name


def native(folder: Path, arguments: list[str]) -> dict:
    done = subprocess.run([sys.executable, "-m", "manuscript_guard.cli", *arguments], cwd=folder,
                          capture_output=True, text=True, encoding="utf-8", timeout=600,
                          check=False)  # fmt: skip
    return {"code": done.returncode, "out": done.stdout, "err": done.stderr}


def in_node(site: Path, folder: Path, arguments: list[str]) -> dict:
    done = subprocess.run([NODE, str(TEST / "parity.mjs"), str(site), str(folder), "--",
                           *arguments], capture_output=True, text=True, encoding="utf-8",
                          timeout=900, check=False)  # fmt: skip
    if done.returncode != 0:
        raise SystemExit(f"parity.mjs failed:\n{done.stderr}")
    return json.loads(done.stdout)


def differences(said: dict, page: dict, as_json: bool) -> list[str]:
    """What the page said otherwise than the command line."""
    found = [part for part in ("code", "err") if said[part] != page[part]]
    same_out = (json.loads(said["out"]) == json.loads(page["out"]) if as_json
                else said["out"] == page["out"])  # fmt: skip
    return found if same_out else ["out", *found]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True, help="what web/build.py built")
    parser.add_argument("--docx", type=Path, required=True, help="the worked example, built")
    parser.add_argument("--results", type=Path, required=True, help="its results file")
    parser.add_argument("--markdown", type=Path, required=True, help="its manuscript/main.md")
    parser.add_argument("--browsers", default="chrome,firefox",
                        help="comma-separated, or none (default chrome,firefox)")  # fmt: skip
    args = parser.parse_args(argv)
    cases = [
        ("the .docx against its results", "paper.docx", ["results.json"]),
        ("the .docx alone", "paper.docx", []),
        ("the Markdown alone", "paper.md", []),
        ("names outside ASCII, with spaces", PAPER, [OUTPUT]),
        ("names that start with -", DASHED_PAPER, [DASHED_OUTPUT]),
        ("two outputs the page once named alike", "paper.docx", list(ALIKE)),
    ]
    failed = 0
    with tempfile.TemporaryDirectory(prefix="mg-page-") as scratch:
        folder = Path(scratch)
        for source, names in ((args.docx, ("paper.docx", PAPER, DASHED_PAPER)),
                              (args.results, ("results.json", OUTPUT, DASHED_OUTPUT, *ALIKE)),
                              (args.markdown, ("paper.md",))):  # fmt: skip
            for name in names:
                shutil.copyfile(source, folder / name)
        listed = []
        for number, (name, paper, against) in enumerate(cases):
            arguments = ["audit", argument(paper),
                         *(["--against", *map(argument, against)] if against else [])]
            said = native(folder, arguments)
            page = args.site / AUDIT
            wrong = [*differences(said, in_node(page, folder, arguments), False),
                     *(f"--json {part}" for part in differences(
                         native(folder, [*arguments, "--json"]),
                         in_node(page, folder, [*arguments, "--json"]), True))]  # fmt: skip
            print(f"node, {name}: {'same' if not wrong else 'DIFFERENT: ' + ', '.join(wrong)}",
                  flush=True)  # fmt: skip
            failed += bool(wrong)
            expect = f"expect-{number}.json"
            (folder / expect).write_text(json.dumps(said), encoding="utf-8")
            listed.append({"name": name, "paper": paper, "against": against, "expect": expect})
        (folder / "cases.json").write_text(json.dumps(listed), encoding="utf-8")
        for browser in [b for b in args.browsers.split(",") if b and b != "none"]:
            done = subprocess.run([NODE, str(TEST / "browser.mjs"), str(args.site), str(folder),
                                   browser], timeout=1800, check=False)  # fmt: skip
            failed += done.returncode != 0
    print("the page holds to the command line" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
