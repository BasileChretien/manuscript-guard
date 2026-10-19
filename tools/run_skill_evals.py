"""Run the skill routing suite in `evals/` against this checkout's plugin, by hand (item 52).

`claude plugin eval` reads its cases from a folder inside the plugin it runs, and refuses one
outside it ("--eval-dir must stay inside the plugin root", Claude Code 2.1.303). The suite
lives beside the plugin, so that installing the plugin copies none of it. So this copies the
plugin and the suite into a folder of their own and runs the command on that copy. The copy
is of the working tree as it is, uncommitted files included: run it on a clean checkout to
record a run. The results go into a new folder, `evals/results/<time>/`, which git ignores,
given to the command as an absolute path, and never into the copy, which is deleted when the
run ends; the report stays on this machine (`--no-publish`), and the copy is of this
repository's own plugin (`--trust-plugin`). Every other argument after `--` goes to `claude
plugin eval` as it is, and there must be some; `--output-dir` is refused, since the script
chooses the folder:

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
    """The arguments for `claude plugin eval`, those after `--`. Refused where there are
    none, since a run with none is a whole paid run on the command's defaults, and where
    they name a results folder, which the script chooses so that it is never in the copy
    (rounds 3 and 4 of #333)."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("passed", nargs=argparse.REMAINDER,
                        help="after --, the arguments for claude plugin eval")  # fmt: skip
    passed = parser.parse_args(argv).passed
    passed = passed[1:] if passed[:1] == ["--"] else passed
    if not passed:
        parser.error("give the arguments for claude plugin eval after --, at least --model")
    if any(given == "--output-dir" or given.startswith("--output-dir=") for given in passed):
        parser.error("--output-dir is not taken: the results go to evals/results/<time>/")
    return passed


def command(claude: str, plugin: Path, passed: list[str], results: Path) -> list[str]:
    """The command run: the copy, the fixed arguments, the results folder as an absolute
    path, so that it cannot be read against the copy, and the arguments given."""
    return [claude, "plugin", "eval", str(plugin), *FIXED, "--output-dir",
            str(results.resolve()), *passed]  # fmt: skip


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
    # A new folder each run, so that what is in it after the run is this run's.
    # Made here, and refused if it is there already, so that two runs never share one.
    results = repo / "evals" / "results" / datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")
    try:
        results.mkdir(parents=True)
    except FileExistsError:
        raise SystemExit(f"{results} exists already: run again") from None
    # A process the run started may still hold a file of the copy on Windows; the copy is
    # left to the system then, rather than the run's exit status lost to a traceback.
    try:
        with tempfile.TemporaryDirectory(prefix="mg-evals-", ignore_cleanup_errors=True) as tmp:
            plugin = stage(repo, Path(tmp))
            done = run(command(claude, plugin, passed, results), cwd=repo)
    finally:
        # A folder the run left empty, or a run that never started, leaves nothing behind.
        wrote = results.is_dir() and any(results.iterdir())
        if results.is_dir() and not wrote:
            results.rmdir()
    print(f"results in {results}" if wrote else "no results were written")
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main())
