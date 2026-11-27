"""Whether this machine has what the chosen analysis language needs: `prerequisites`.

Asked once the project is written, so that an R analysis does not meet a missing package on
its first run. Python needs nothing more: the emitter is part of this package. R needs
`Rscript`, the packages `jsonlite` and `digest`, and the R emitter `manuscriptguard`, which
is not on CRAN. R is asked with a time limit, as every program the tool runs is, and a
machine where it does not answer in time is said to be one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from manuscript_guard.verify import RSCRIPT_VARIABLE

#: Seconds R is given to say which packages it has.
R_LIMIT = 60
R_PACKAGES = ("jsonlite", "digest", "manuscriptguard")
_ASK_R = (
    "cat(R.version$major, R.version$minor, "
    "sapply(c('jsonlite', 'digest', 'manuscriptguard'), requireNamespace, quietly = TRUE))"
)
INSTALL_EMITTER = ('remotes::install_github("BasileChretien/manuscript-guard", '
                   'subdir = "r/manuscriptguard")')  # fmt: skip


@dataclass(frozen=True)
class Tool:
    name: str
    found: bool
    said: str


def _r(run: Callable, which: Callable, env: Mapping[str, str]) -> Tool:
    rscript = env.get(RSCRIPT_VARIABLE) or which("Rscript")
    if not rscript:
        return Tool("R", False, f"no Rscript is on PATH: install R, or name the Rscript to run "
                    f"with {RSCRIPT_VARIABLE} where PATH gives another")  # fmt: skip
    try:
        done = run([rscript, "--vanilla", "-e", _ASK_R], capture_output=True, text=True,
                   timeout=R_LIMIT, check=False)  # fmt: skip
    except subprocess.TimeoutExpired:
        return Tool("R", False, f"{rscript} did not answer in {R_LIMIT} seconds")
    except OSError as exc:
        return Tool("R", False, f"{rscript} could not be run: {exc.strerror or exc}")
    words = (done.stdout or "").split()
    if done.returncode != 0 or len(words) != 2 + len(R_PACKAGES):
        return Tool("R", False, f"{rscript} did not say which packages it has "
                    f"(exit {done.returncode})")  # fmt: skip
    version = f"{words[0]}.{words[1]}"
    missing = [name for name, held in zip(R_PACKAGES, words[2:], strict=True) if held != "TRUE"]
    if not missing:
        return Tool("R", True, f"R {version} at {rscript}, with jsonlite, digest and the "
                    "emitter manuscriptguard")  # fmt: skip
    advice = []
    plain = [name for name in missing if name != "manuscriptguard"]
    if plain:
        advice.append(f"install.packages(c({', '.join(repr(name) for name in plain)}))")
    if "manuscriptguard" in missing:
        advice.append(INSTALL_EMITTER)
    return Tool("R", False, f"R {version} at {rscript} lacks {', '.join(missing)}: in R, "
                f"{'; then '.join(advice)}")  # fmt: skip


def prerequisites(analysis: object, *, run: Callable = subprocess.run,
                  which: Callable = shutil.which,
                  env: Mapping[str, str] | None = None) -> tuple[Tool, ...]:  # fmt: skip
    """What the analysis language answered needs, and whether this machine has it."""
    if analysis == "python":
        return (Tool("Python", True, f"Python {sys.version.split()[0]}: the emitter is part "
                     "of this package"),)  # fmt: skip
    if analysis == "r":
        return (_r(run, which, os.environ if env is None else env),)
    if analysis == "other":
        return (Tool("harvest", True, "the analysis's output tables are taken in with "
                     "`manuscript-guard harvest` (docs/harvest.md)"),)  # fmt: skip
    return ()
