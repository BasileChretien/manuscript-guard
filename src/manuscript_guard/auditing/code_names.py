"""The names from the code a paper audited prints, said in one finding.

G14 gives `check` a warning for each name written as a name in code is (`gates/code_names.py`),
which a project's author answers one at a time. Run on 52 real preprints, the audit gave 369,
and judges found 82% of a sample false: 198 came from one paper's survey variables, 98 from
another's table of series. The table's cells and the maths the reader did not know for maths
are no longer read; what is left, an ethics committee's reference, a model's checkpoint, a
tissue's label, is told from a name in code only by a guess. So the audit says the names in one
finding for the paper (the author's decision 13, 2026-11-13), as it says the short forms left
undefined (#640, `auditing.undefined`): the names in the order G14 gives them, at the first use
of the first, with `--known` as the remedy. Each name keeps the warning G14 gave it, its place,
its count and its quote, which `--json` gives under the finding and `--details` lists. `check`
is unchanged: its warnings are G14's, one for each name.
"""

from __future__ import annotations

import re

from manuscript_guard.auditing.undefined import Listed, gathered
from manuscript_guard.findings import Finding
from manuscript_guard.gates.code_names import CODE, GATE

#: G14's message for one name, "'hr_adj' is written with underscores, ...", "'age_group' is
#: the name of a variable in the data dictionary, ...", "'ror.point' is a key of the results
#: ...": the name. A name is letters, digits, underscores and dots, so no quote is in it.
#: `tests/test_audit_code_names.py` holds that it matches what the gate writes.
_SAID = re.compile(r"^'(?P<name>[^'\s]+)' is (?:written with underscores|the name of a "
                   r"variable in the data dictionary|a key of the results)")
#: What `--details` titles the list of the names with.
EACH = "Each name written the way a name in code is, where it is first used:"
#: What the finding asks for, in the audit's own words (`auditing.gates.KNOWN`).
HINT = ("write what each is in words, and set a function's or a package's name as code; give "
        "the ones the paper is right to print to the audit as known words (on the page, "
        '"Words to leave alone"; on the command line, --known)')  # fmt: skip


def one_finding(found: list[Finding]) -> list[Finding]:
    """`found`, G14's findings on one paper audited in the order G14 gave them, with its
    warnings on the names from the code made one (`Listed`) where the first of them stood. A
    warning whose message is not G14's for one name is left as it is."""
    return gathered(found, _name, _made)


def _name(finding: Finding) -> str | None:
    """The name G14's warning on one name from the code names; None for any other finding."""
    said = _SAID.match(finding.message) if finding.code == CODE else None
    return said["name"] if said and finding.gate == GATE else None


def _message(names: list[str]) -> str:
    """"3 names are written the way names in code are, as G14 reads the paper: 'x_a' here,
    then y_b, z_c": the first quoted, so that a comment on the .docx is anchored on it
    (`auditing.commented.words_of`)."""
    count = len(names)
    said = ("names are written the way names in code are" if count != 1
            else "name is written the way a name in code is")  # fmt: skip
    message = f"{count} {said}, as G14 reads the paper: '{names[0]}' here"
    return message + (", then " + ", ".join(names[1:]) if names[1:] else "")


def _made(mine: list[tuple[str, Finding]]) -> Listed:
    first = mine[0][1]
    names = list(dict.fromkeys(name for name, _finding in mine))
    return Listed(gate=GATE, code=CODE, message=_message(names), severity=first.severity,
                  path=first.path, line=first.line, col=first.col, context=first.context,
                  hint=HINT, forms=tuple(mine), each=EACH)  # fmt: skip


__all__ = ["CODE", "EACH", "HINT", "one_finding"]
