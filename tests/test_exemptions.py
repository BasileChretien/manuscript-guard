"""Every exemption must prove itself.

The recurring defect of this project is not a wrong regex. It is an escape hatch whose first
version *believed its own claim*: `composed` exempted a cell without checking the exemption
described it, `Verbatim` said a script could not build one, `file_sha256` scoping was a way
to review one file and pass, and composed `parts` whitelisted their strings project-wide.
Each was found by a reviewer or by opening the file, never by a test, because nothing
required an exemption to be self-verifying.

This is the same countermeasure `tests/data/rule_cases.yaml` applies to classifier rules,
raised to the whole toolkit: an exemption cannot be added without someone writing down the
test that abuses it.

The check is deliberately two-directional. Declaring an exemption with no abuse test fails,
*and* an exemption present in the code but missing from the inventory fails — a list that
only grows when someone remembers to add to it is the kind of "not checked looks like
checked" this repository keeps finding.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
INVENTORY = REPO / "tests" / "data" / "exemptions.yaml"

DECLARED = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))["exemptions"]

#: Skip reasons that are about the machine rather than about coverage. Anything else means
#: an exemption went unguarded and the run would have said otherwise.
EXTERNAL = re.compile(r"(?i)pandoc|Rscript|\bR is not\b|Zotero|jsonlite|digest")

#: How each exemption is spelled where it is granted. The inventory is checked against the
#: source, so an exemption cannot be quietly *removed* from the list while the code still
#: grants it.
#:
#: This mapping is open-world, and that is a real limit rather than an oversight: a brand
#: new escape hatch, spelled some way nobody has written down here, enters neither `unlisted`
#: nor `stale` and so bypasses the inventory and its abuse test both. Closing it properly
#: means routing every grant through one registry — `exempt("composed-cell")` at the point
#: of the decision — so the set is discoverable rather than enumerated. Worth doing; not
#: done. Recorded in DESIGN under Known gaps, because a harness whose limits are
#: undocumented gets trusted past them exactly like a gate does.
IN_SOURCE = {
    "project-conventions": r"extra_conventions",
    "project-terms": r"extra_terms",
    "value-label": r'"label"|label: bool',
    "value-unquoted": r"quoted: bool|\"quoted\"",
    "audit-only-rule": r"audit_only",
    "composed-cell": r'"composed"|_composed',
    "composed-parts": r'"parts"|parts_by_cell',
    "code-list-cell": r'"codes"|_Verbatim',
    "review-file-scope": r"file_sha256",
    "finding-overridden": r'"overridden"|overridden',
    "figure-presentational": r"presentational|declared",
    "build-skip-checks": r"skip_checks",
    "submit-skip-checks": r"skip_checks",
    "import-force": r"args\.force",
}


def test_every_exemption_names_a_test_that_abuses_it() -> None:
    """The point of the file. Adding an escape hatch without one fails here."""
    missing = [entry["id"] for entry in DECLARED if not entry.get("abuse")]
    assert not missing, (
        f"exemptions with no abuse test: {missing}. Every place the toolkit agrees not to "
        f"look needs a test proving that claiming it falsely is caught."
    )


def test_every_abuse_test_exists() -> None:
    """A named test that does not exist is worse than no name: it reads as covered."""
    absent = []
    for entry in DECLARED:
        path, _, name = entry["abuse"].partition("::")
        source = REPO / path
        if not source.exists() or f"def {name}(" not in source.read_text(encoding="utf-8"):
            absent.append(f"{entry['id']} -> {entry['abuse']}")
    assert not absent, "abuse tests named in the inventory but not found:\n  " + "\n  ".join(absent)


def test_every_abuse_test_passes() -> None:
    """Run them. A named test that fails leaves the exemption unguarded either way."""
    named = sorted({entry["abuse"] for entry in DECLARED})
    finished = subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q", "--no-header",
            "-p", "no:cacheprovider", "-rs", *named,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert finished.returncode == 0, finished.stdout[-3000:]

    # A skipped abuse test exits 0 and guards nothing. On a machine without pandoc several
    # of these skip, and "the exemptions are covered" would be true of a run that checked
    # none of them - which is the exact shape this file exists to refuse.
    # A skipped abuse test exits 0 and guards nothing, so skips are read rather than
    # ignored - but a missing external tool is an environment fact, not missing coverage.
    # CI has no pandoc, and three of these need it; failing there would say the exemptions
    # are unguarded when what is true is narrower and worth printing instead.
    reasons = re.findall(r"^SKIPPED \[\d+\] ([^\n]+)$", finished.stdout, re.MULTILINE)
    unexplained = [
        line for line in reasons if not EXTERNAL.search(line)
    ]
    assert not unexplained, (
        "abuse test(s) skipped for a reason inside our control, so the exemption they "
        "guard went unchecked:\n  " + "\n  ".join(unexplained)
    )
    if reasons:
        print(f"{len(reasons)} abuse test(s) skipped for a missing tool: {reasons}")


def test_the_inventory_covers_what_the_code_grants() -> None:
    """The other direction, which is the one that rots.

    A list that only grows when someone remembers is the same "not checked looks like
    checked" this repository keeps finding. So the spelling of each exemption is looked for
    in the source: if the code grants it, the inventory has to say so.
    """
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPO / "src" / "manuscript_guard").rglob("*.py")
    )
    listed = {entry["id"] for entry in DECLARED}

    unlisted = [
        name
        for name, pattern in IN_SOURCE.items()
        if re.search(pattern, source) and name not in listed
    ]
    assert not unlisted, f"granted by the code, missing from the inventory: {unlisted}"

    stale = [name for name, pattern in IN_SOURCE.items() if not re.search(pattern, source)]
    assert not stale, (
        f"in the inventory, no longer in the code: {stale}. An exemption that was removed "
        f"should leave the list too, or the list stops describing the toolkit."
    )


def test_every_exemption_says_what_it_stops_checking() -> None:
    """`why` alone reads as a justification. `grants` is the part a reader needs."""
    vague = [entry["id"] for entry in DECLARED if len(entry.get("grants", "")) < 20]
    assert not vague, f"exemptions that do not say what they stop checking: {vague}"
