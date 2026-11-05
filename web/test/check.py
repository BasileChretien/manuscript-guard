"""Hold a built audit page to the command line.

    python web/test/check.py --site _site --docx build/manuscript.docx \\
        --results results/01_disproportionality.json --markdown manuscript/main.md

For each case (the .docx against the results, the .docx alone, the Markdown alone), the
command line's `audit` is run here, then the same command is run as the page runs it, in Node
(`parity.mjs`), and its `--json` and its report must be the command line's. Then the page is
opened in each browser named (`browser.mjs`): it must start under its own policy, print the
same reports, send nothing, and refuse every request "Test the rules" tries.

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
NODE = shutil.which("node") or "node"


def native(folder: Path, arguments: list[str]) -> str:
    done = subprocess.run([sys.executable, "-m", "manuscript_guard.cli", *arguments], cwd=folder,
                          capture_output=True, text=True, encoding="utf-8", timeout=600,
                          check=False)  # fmt: skip
    return done.stdout


def in_node(site: Path, folder: Path, arguments: list[str]) -> dict:
    done = subprocess.run([NODE, str(TEST / "parity.mjs"), str(site), str(folder), "--",
                           *arguments], capture_output=True, text=True, encoding="utf-8",
                          timeout=900, check=False)  # fmt: skip
    if done.returncode != 0:
        raise SystemExit(f"parity.mjs failed:\n{done.stderr}")
    return json.loads(done.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True)
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
    ]
    failed = 0
    with tempfile.TemporaryDirectory(prefix="mg-page-") as scratch:
        folder = Path(scratch)
        shutil.copyfile(args.docx, folder / "paper.docx")
        shutil.copyfile(args.results, folder / "results.json")
        shutil.copyfile(args.markdown, folder / "paper.md")
        listed = []
        for number, (name, paper, against) in enumerate(cases):
            arguments = ["audit", paper, *(["--against", *against] if against else [])]
            text, as_json = native(folder, arguments), native(folder, [*arguments, "--json"])
            page_text = in_node(args.site, folder, arguments)["out"]
            page_json = in_node(args.site, folder, [*arguments, "--json"])["out"]
            same = page_text == text and json.loads(page_json) == json.loads(as_json)
            print(f"node, {name}: {'same' if same else 'DIFFERENT'}", flush=True)
            if not same:
                failed += 1
                print(f"--- command line\n{text}\n--- page\n{page_text}", file=sys.stderr)
            (folder / f"expect-{number}.txt").write_text(text, encoding="utf-8", newline="\n")
            listed.append({"name": name, "paper": paper, "against": against,
                           "expect": f"expect-{number}.txt"})  # fmt: skip
        (folder / "cases.json").write_text(json.dumps(listed), encoding="utf-8")
        for browser in [b for b in args.browsers.split(",") if b and b != "none"]:
            done = subprocess.run([NODE, str(TEST / "browser.mjs"), str(args.site), str(folder),
                                   browser], timeout=1800, check=False)  # fmt: skip
            failed += done.returncode != 0
    print("the page holds to the command line" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
