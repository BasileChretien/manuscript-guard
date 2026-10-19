"""Run the skill routing suite in `evals/` against this checkout's plugin, by hand (item 52).

`claude plugin eval` reads its cases from a folder inside the plugin it runs, and refuses one
outside it ("--eval-dir must stay inside the plugin root", Claude Code 2.1.303). The suite
lives beside the plugin, so that installing the plugin copies none of it. So this copies the
plugin and the suite into a folder of their own, runs the command on that copy, and copies
its results back into `evals/results/`, which git ignores. The report stays on this machine
(`--no-publish`), and the copy is of this repository's own plugin (`--trust-plugin`). Every
argument after `--` goes to `claude plugin eval` as it is:

    python tools/run_skill_evals.py -- --ablation with-without --runs 3 --model <model>

A run is paid at API prices, or counts against a subscription's usage. Run one case once
first to measure it (`-- --case <name> --runs 1 --ablation none`).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
#: What `claude plugin eval` is always given: the copy's suite, a local report, and the
#: trust a copy of this repository's own plugin needs to run without asking each time.
FIXED = ("--eval-dir", "evals", "--no-publish", "--trust-plugin")


def stage(repo: Path, into: Path) -> Path:
    """A copy of `repo`'s plugin with the suite inside it, its past results left out."""
    plugin = into / "plugin"
    shutil.copytree(repo / "plugin", plugin)
    shutil.copytree(repo / "evals", plugin / "evals", ignore=shutil.ignore_patterns("results"))
    return plugin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("passed", nargs=argparse.REMAINDER,
                        help="after --, the arguments for claude plugin eval")  # fmt: skip
    args = parser.parse_args(argv)
    passed = args.passed[1:] if args.passed[:1] == ["--"] else args.passed
    claude = shutil.which("claude")
    if claude is None:
        raise SystemExit("claude is not on PATH")
    with tempfile.TemporaryDirectory(prefix="mg-evals-") as folder:
        plugin = stage(REPO, Path(folder))
        run = subprocess.run([claude, "plugin", "eval", str(plugin), *FIXED, *passed], cwd=REPO)
        results = plugin / "evals" / "results"
        if results.is_dir():
            shutil.copytree(results, REPO / "evals" / "results", dirs_exist_ok=True)
            print(f"results copied into {REPO / 'evals' / 'results'}")
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
