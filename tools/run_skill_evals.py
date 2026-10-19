"""Run the skill routing suite in `evals/` against this checkout's plugin, by hand (item 52).

`claude plugin eval` reads its cases from a folder inside the plugin it runs, and refuses one
outside it ("--eval-dir must stay inside the plugin root", Claude Code 2.1.303). The suite
lives beside the plugin, so that installing the plugin copies none of it. So this copies the
plugin and the suite into a folder of their own and runs the command on that copy. The copy
is of the working tree as it is, uncommitted files included: run it on a clean checkout to
record a run. The results go into `evals/results/<time>/`, which git ignores, and not into
the copy, which is deleted when the run ends; the report stays on this machine
(`--no-publish`), and the copy is of this repository's own plugin (`--trust-plugin`). Every
argument after `--` goes to `claude plugin eval` as it is, and there must be some:

    python tools/run_skill_evals.py -- --ablation with-without --runs 3 --model <model>

A run is paid at API prices, or counts against a subscription's usage. Run one case once
first to measure it (`-- --case <name> --runs 1 --ablation none`).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
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


def arguments(argv: list[str]) -> list[str]:
    """The arguments for `claude plugin eval`, those after `--`; refused where there are
    none, since a run with none is a whole paid run on the command's defaults."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("passed", nargs=argparse.REMAINDER,
                        help="after --, the arguments for claude plugin eval")  # fmt: skip
    passed = parser.parse_args(argv).passed
    passed = passed[1:] if passed[:1] == ["--"] else passed
    if not passed:
        parser.error("give the arguments for claude plugin eval after --, at least --model")
    return passed


def output_dir(passed: list[str]) -> str | None:
    """The results folder the arguments name, as `--output-dir x` or `--output-dir=x`."""
    for at, given in enumerate(passed):
        if given == "--output-dir" and at + 1 < len(passed):
            return passed[at + 1]
        if given.startswith("--output-dir="):
            return given.split("=", 1)[1]
    return None


def command(claude: str, plugin: Path, passed: list[str], results: Path) -> list[str]:
    """The command run: the copy, the fixed arguments, the results written into the
    repository unless the arguments name where, and the arguments given."""
    out = [] if output_dir(passed) is not None else ["--output-dir", str(results)]
    return [claude, "plugin", "eval", str(plugin), *FIXED, *out, *passed]


def main(
    argv: list[str] | None = None,
    *,
    repo: Path = REPO,
    claude: str | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    passed = arguments(sys.argv[1:] if argv is None else argv)
    claude = claude or shutil.which("claude")
    if claude is None:
        raise SystemExit("claude is not on PATH")
    named = output_dir(passed)
    # The run's folder is the repository, so a folder the arguments name is under it.
    results = repo / named if named is not None else (
        repo / "evals" / "results" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S"))  # fmt: skip
    # A process the run started may still hold a file of the copy on Windows; the copy is
    # left to the system then, rather than the run's exit status lost to a traceback.
    with tempfile.TemporaryDirectory(prefix="mg-evals-", ignore_cleanup_errors=True) as folder:
        plugin = stage(repo, Path(folder))
        done = run(command(claude, plugin, passed, results), cwd=repo)
    print(f"results in {results}" if results.exists() else "no results were written")
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
