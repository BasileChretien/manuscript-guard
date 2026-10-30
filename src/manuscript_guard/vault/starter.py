"""The profile script `vault init` starts: `analysis/00_profile.py`, or `.R` in a project
whose analysis is in R.

It reads each registered file with a reader the author may change, as the analysis reads it,
and hands the table to `em.profile` (`em$profile`). The script reads the data, never the
tool. It is run by `vault run`, which gives it the vault's folder in
`MANUSCRIPT_GUARD_VAULT`, and what it writes leaves the vault when a person releases it. A
file that is already there is never written over.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from manuscript_guard.vault import VARIABLE

SCRIPT = PurePosixPath("analysis/00_profile")

_PYTHON_HEAD = f'''"""The profile of each file of the vault, for the synthetic copy the agent uses.

Started by `manuscript-guard vault init`. `vault run` runs it on the real data, with the
vault's folder in {VARIABLE}, and what it writes, profiles/data/<file>.profile.json, leaves
the vault when a person releases it. `vault synthesize` then draws data/synthetic/<file>
from the profile alone. Read each file as the analysis reads it: change the reader here,
never the profile, and tell `read_as` how the file is written where it is not plain CSV.
"""

import csv
import os
from pathlib import Path

from manuscript_guard.emit import Emitter

if not os.environ.get("{VARIABLE}"):
    raise SystemExit("this script reads the data in the vault: run it with "
                     "`manuscript-guard vault run`")
VAULT = Path(os.environ["{VARIABLE}"])
em = Emitter(__file__)
'''

_PYTHON_FILE = '''
with open(VAULT / {label!r}, newline="", encoding="utf-8") as handle:
    em.profile(list(csv.DictReader(handle{delimiter})), name={label!r},
               read_as={{"header_of": VAULT / {label!r}}})
'''

_PYTHON_OTHER = '''
# {label}: read it as the analysis does (pandas.read_excel, pyreadstat, ...), then
# em.profile(table, name={label!r}). `vault synthesize` writes CSV and TSV only: export
# it to CSV inside the vault, register that, and profile it, for a synthetic copy.
'''

_R_HEAD = f'''# The profile of each file of the vault, for the synthetic copy the agent works on.
#
# Started by `manuscript-guard vault init`. `vault run` runs it on the real data, with the
# vault's folder in {VARIABLE}, and what it writes, profiles/data/<file>.profile.json, leaves
# the vault when a person releases it. `vault synthesize` then draws data/synthetic/<file>
# from the profile alone. Read each file as the analysis reads it: change the reader here,
# never the profile, and tell `read_as` how the file is written where it is not plain CSV.

library(manuscriptguard)

vault <- Sys.getenv("{VARIABLE}")
if (!nzchar(vault)) {{
  stop("this script reads the data in the vault: run it with `manuscript-guard vault run`")
}}
em <- mg_emitter("analysis/00_profile.R")
'''

_R_FILE = '''
em$profile(read.csv(file.path(vault, {quoted}), colClasses = "character",
                    check.names = FALSE, encoding = "UTF-8"{delimiter}),
           name = {quoted}, read_as = list(header_of = file.path(vault, {quoted})))
'''

_R_OTHER = '''
# {label}: read it as the analysis does (readxl::read_excel, haven::read_sas, ...), then
# em$profile(table, name = {quoted}). `vault synthesize` writes CSV and TSV only: export
# it to CSV inside the vault, register that, and profile it, for a synthetic copy.
'''


def _in_r(root: Path) -> bool:
    """Whether the analysis is in R: more R scripts than Python ones in `analysis/`."""
    folder = root / "analysis"
    if not folder.is_dir():
        return False
    count = {suffix: sum(1 for path in folder.iterdir() if path.suffix.lower() == suffix)
             for suffix in (".r", ".py")}  # fmt: skip
    return count[".r"] > count[".py"]


def text(labels: list[str], *, r: bool) -> str:
    head, plain, other = (_R_HEAD, _R_FILE, _R_OTHER) if r else (
        _PYTHON_HEAD, _PYTHON_FILE, _PYTHON_OTHER)  # fmt: skip
    parts = [head]
    for label in labels:
        suffix = PurePosixPath(label).suffix.lower()
        if suffix in (".csv", ".tsv"):
            tab = suffix == ".tsv"
            delimiter = (', sep = "\\t"' if r else ', delimiter="\\t"') if tab else ""
            parts.append(plain.format(label=label, quoted=json.dumps(label), delimiter=delimiter))
        else:
            parts.append(other.format(label=label, quoted=json.dumps(label)))
    return "".join(parts)


def write(root: Path, labels: list[str]) -> Path | None:
    """Write the starter script where there is none, and say where; None where one is there."""
    r = _in_r(root)
    path = root.joinpath(*SCRIPT.parent.parts, SCRIPT.name + (".R" if r else ".py"))
    if any(root.joinpath(*SCRIPT.parent.parts, SCRIPT.name + ext).exists()
           for ext in (".R", ".r", ".py")):  # fmt: skip
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text(labels, r=r).encode("utf-8"))
    return path
