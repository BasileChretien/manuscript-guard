"""A package an author deposits for reproducibility: the code, the results it wrote, what it
ran with and how to run it again, and never the data a custodian keeps. `plan` decides what
goes in and what stops it, `counts` reads the custodian's minimum across a whole fragment,
`texts` and `readme` write what the package says of itself, and `write` makes the folder and
the .zip. Uploading is the author's: nothing here sends anything anywhere."""

from manuscript_guard.deposit.counts import SMALL_COUNTS, count_in_cell, small_counts
from manuscript_guard.deposit.plan import (
    DEPOSIT,
    Entry,
    Input,
    PackageError,
    Plan,
    Withheld,
    deposit_id,
    package_signables,
    plan_package,
)
from manuscript_guard.deposit.write import Written, deposit_steps, write_package

__all__ = [
    "DEPOSIT",
    "SMALL_COUNTS",
    "Entry",
    "Input",
    "PackageError",
    "Plan",
    "Withheld",
    "Written",
    "count_in_cell",
    "deposit_id",
    "deposit_steps",
    "package_signables",
    "plan_package",
    "small_counts",
    "write_package",
]
