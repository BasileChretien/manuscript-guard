"""A report about a gate or a command that got something wrong: it flagged what is not a
defect, or let one through.

The person gives the smallest text that shows it, and it goes into the report as they wrote
it, the scrub aside: nothing here rewrites or masks a word of it. For `audit`, G6 and G14,
which read a text with no project around it, the text is read again here, on this machine,
alone (`check`), and the report says whether it alone shows the fault, so that the person can
cut it down or change its words and see at once whether the fault survives. The reading runs
in a temporary folder of its own and neither reads nor writes the person's project. The
report ends with a test to start from, in the file and the shape the suite already uses for
that gate (`skeleton`), marked as a starting point.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.diagnostics import issue

#: The gates a report may be about. A command is named by its own name.
GATES = tuple(f"G{number}" for number in range(17))
#: What reads a text with no project around it, and so can be checked on the snippet alone.
CHECKED_HERE = ("audit", "G6", "G14")
LABEL = "gate"
FLAGGED = "It flagged something that is not a defect"
MISSED = "It let a defect through"
#: How many of the snippet's words the title carries where no code was named.
TITLE_WORDS = 8
#: A piece of a line of the snippet in the test, so that the test's lines stay readable.
PIECE = 72
_CODE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: Where the suite tests each reading, and how.
_AUDIT, _WRITING, _LANGUAGE, _CORRUPTION = (
    "tests/test_audit.py", "tests/test_writing.py", "tests/test_language.py",
    "tests/test_corruption.py",
)  # fmt: skip


@dataclass(frozen=True)
class Asked:
    """What the person reports: about which gate or command, in which direction, the finding's
    code where they give one, and the text."""

    about: str
    flagged: bool
    code: str | None
    snippet: str
    said: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Checked:
    #: The sentence said in the terminal and in the report.
    line: str
    #: Whether the snippet alone shows the fault; None where it was not checked, where no code
    #: was named to check it by, or where the code is not among the snippet's findings, since
    #: no list of the codes a gate can give is kept and the code may be misspelt.
    reproduced: bool | None = None
    #: Whether the snippet was read here at all.
    read: bool = False


def named(about: str, commands: Iterable[str]) -> str:
    """The gate or command `about` names, as the tool spells it. Raises ValueError where it
    names neither."""
    given = about.strip()
    if given.upper() in GATES:
        return given.upper()
    by_name = {command.casefold(): command for command in commands}
    if given.casefold() in by_name:
        return by_name[given.casefold()]
    raise ValueError(f"--about names a gate (G0 to G16) or a command, such as audit or check; "
                     f"{about!r} is neither")  # fmt: skip


def is_code(code: str) -> bool:
    """Whether `code` is written as a finding's code is: `unclassified-number`."""
    return bool(_CODE.match(code))


def check(asked: Asked) -> Checked:
    """Whether the snippet alone shows the fault, read as `audit` reads a paper, here."""
    if asked.about not in CHECKED_HERE:
        return Checked("not checked here: a snippet is read again on its own only for audit, "
                       "G6 and G14, which need no project around it")  # fmt: skip
    try:
        found = _read_alone(asked.about, asked.snippet)
    except _NotRun as exc:
        return Checked(f"not checked: {exc}")
    except Exception as exc:  # noqa: BLE001 - the report is still written, and says why
        from manuscript_guard.diagnostics import crashes

        recorded = crashes.record(exc, kind=crashes.GATE, name=asked.about)
        then = (f" (`manuscript-guard report-issue {recorded.stem}` reports that)"
                if recorded else "")  # fmt: skip
        return Checked(f"not checked: {asked.about} stopped on {type(exc).__name__} reading "
                       f"the snippet alone{then}")  # fmt: skip
    return _verdict(asked, found)


def _verdict(asked: Asked, found: set[str]) -> Checked:
    """What the codes the snippet gave say of the fault. Only a code found is a verdict: no
    list of the codes a gate can give is kept, so a code not found may be one the gate never
    gives, or misspelt, and "reproduced" would claim what was not shown."""
    listed = ", ".join(f"`{code}`" for code in sorted(found)) or "no finding"
    if asked.code is None:
        return Checked(f"checked: the snippet alone gives {listed}; with no code named, which "
                       "of these is the fault is for the report to say", read=True)  # fmt: skip
    code = f"`{asked.code}`"
    if asked.code in found:
        if asked.flagged:
            return Checked(f"reproduced: the snippet alone gives {code}", True, read=True)
        return Checked(f"not reproduced: the snippet alone gives {code}; the report says so",
                       False, read=True)  # fmt: skip
    return Checked(f"{code} is not found in the snippet's findings (it gives {listed}); no "
                   f"list of the codes {asked.about} can give is kept here, so check its "
                   "spelling against what manuscript-guard printed", read=True)  # fmt: skip


class _NotRun(Exception):
    pass


def _read_alone(about: str, snippet: str) -> set[str]:
    """The codes `about` gives on the snippet as a paper of its own, in a temporary folder."""
    from manuscript_guard.auditing.gates import run_gates

    with tempfile.TemporaryDirectory(prefix="mg-report-") as folder:
        paper = Path(folder) / "paper.md"
        paper.write_text(snippet, encoding="utf-8", newline="\n")
        run = run_gates(paper)
        if run.note:
            raise _NotRun(run.note)
        if about == "G6":
            return {finding.code for finding in run.writing}
        if about == "G14":
            return {finding.code for finding in run.language}
        from manuscript_guard.audit import audit
        from manuscript_guard.auditing.report import items

        report = audit([paper], None)
        report.gates = [run]
        return {item.code for item in items(report)}


def report(asked: Asked, checked: Checked, *, installed: str) -> issue.Report:
    """The report, under the headings of the issue template `gate-got-it-wrong.md`."""
    from manuscript_guard.diagnostics.crashes import python_version, system_name

    direction = "flagged" if asked.flagged else "missed"
    code = f": `{asked.code}`" if asked.code else ""
    said = (issue.fenced(asked.said.strip()) if asked.said and asked.said.strip() else
            "(Not given: paste what `manuscript-guard check` printed, or what `manuscript-guard "
            "explain <file>` says if it is about how a number was classified.)")  # fmt: skip
    should = (asked.note.strip() if asked.note and asked.note.strip() else
              "(Say what it should have said and why. If this is a convention of your field "
              "rather than a fault, say which field and where the convention is written down.)")
    parts = [
        issue.HEAD,
        f"**About:** {_called(asked.about)}{_described(asked.about)}.",
        "**Which direction**\n\n"
        f"- [{'x' if asked.flagged else ' '}] {FLAGGED}{code if asked.flagged else ''}\n"
        f"- [{' ' if asked.flagged else 'x'}] {MISSED}{'' if asked.flagged else code}",
        "**The smallest text that shows it**\n\n"
        + issue.fenced(asked.snippet.rstrip("\n"), "markdown"),
        f"**Does the snippet alone show it?** {checked.line}.",
        "**What manuscript-guard said**\n\n" + said,
        "**What it should have said, and why.**\n\n" + should,
        f"**Version:** manuscript-guard {installed}, Python {python_version()}, "
        f"{system_name()}.",
        f"**A test to start from**, for `{file_for(asked.about)}`: written by `report-issue` "
        "as a starting point, not a finished test. Read it, cut it down, and check that it "
        "fails before the fix and passes after.\n\n" + issue.fenced(skeleton(asked), "python"),
    ]
    title = f"[{asked.about}] {direction}: {asked.code or _first_words(asked.snippet)}"
    return issue.Report(title=title, body="\n\n".join(parts) + "\n", name=issue.stamped_name(),
                        label=LABEL)  # fmt: skip


def _called(about: str) -> str:
    return f"`{about}`" if about in GATES else f"`manuscript-guard {about}`"


def _described(about: str) -> str:
    from manuscript_guard.gates import GATES as DESCRIBED

    return f", {DESCRIBED[about]}" if about in DESCRIBED else ""


def _first_words(snippet: str) -> str:
    words = snippet.split()
    shown = " ".join(words[:TITLE_WORDS])
    return shown + ("…" if len(words) > TITLE_WORDS else "")


def file_for(about: str) -> str:
    """The file of the suite that the test to start from belongs in."""
    return {"audit": _AUDIT, "G6": _WRITING, "G14": _LANGUAGE}.get(about, _CORRUPTION)


def named_test(asked: Asked) -> str:
    """`test_reported_g6_flagged_model_artefact_<12 hex of the snippet's SHA-256>`, the code
    left out where none was named."""
    words = [asked.about, "flagged" if asked.flagged else "missed", asked.code or ""]
    named = re.sub(r"[^a-z0-9]+", "_", "_".join(word for word in words if word).lower())
    digest = hashlib.sha256(asked.snippet.encode("utf-8")).hexdigest()[:12]
    return f"test_reported_{named}_{digest}"


def skeleton(asked: Asked) -> str:
    """A test of the snippet, in the shape `file_for(asked.about)` uses: the snippet, the
    reading, and an assertion on the code, absent where the gate flagged it wrongly and present
    where it let the defect through. Where the snippet is added to the example, which may give
    the code already, it is held to what the snippet adds: as often as before where the gate
    flagged it wrongly, more often where it let the defect through. With no code, the
    assertion is left to write."""
    about = asked.about
    text = _literal(asked.snippet)
    counted = False
    if about == "audit":
        head = f"def {named_test(asked)}(tmp_path: Path) -> None:"
        body = [
            "from manuscript_guard.auditing.gates import run_gates",
            "from manuscript_guard.auditing.report import items",
            "",
            *text,
            'paper = tmp_path / "paper.md"',
            'paper.write_text(text, encoding="utf-8")',
            "report = audit([paper], None)",
            "report.gates = [run_gates(paper)]",
            "found = {item.code for item in items(report)}",
        ]
    elif about in ("G6", "G14"):
        head = f"def {named_test(asked)}(project: Path) -> None:"
        body = [*text, "found = codes(written(project, text))"]
    elif about in GATES or about == "check":
        head = f"def {named_test(asked)}(project: Path) -> None:"
        which = f' if finding.gate == "{about}"' if about in GATES else ""
        counted = True
        body = [
            "from manuscript_guard.cli import _run_gates",
            "",
            "def counted() -> list[str]:",
            "    report, _project, _chosen, _deferred = _run_gates(project)",
            f"    return [finding.code for finding in report.findings{which}]",
            "",
            *text,
            "before = counted()",
            *_appended(),
            "found = counted()",
            "# The example may give the code already: the test is of what the snippet adds.",
        ]
    else:
        head = f"def {named_test(asked)}(project: Path, monkeypatch, capsys) -> None:"
        counted = True
        body = [
            "from manuscript_guard.cli import main",
            "",
            "def counted() -> str:",
            f'    main(["{about}"])  # TODO: add the words you gave `{about}` after its name',
            "    said = capsys.readouterr()",
            "    return said.out + said.err",
            "",
            *text,
            "monkeypatch.chdir(project)",
            "before = counted()",
            *_appended(),
            "found = counted()",
            "# The example may print the code already: the test is of what the snippet adds.",
        ]
    inside = [f'"""{_docstring(asked)}"""', *body, *_assertion(asked, counted)]
    return "\n".join([head, *(f"    {line}" if line else "" for line in inside)])


def _docstring(asked: Asked) -> str:
    direction = "--flagged" if asked.flagged else "--missed"
    code = f" {asked.code}" if asked.code else ""
    return (f"Reported with `manuscript-guard report-issue --about {asked.about} "
            f"{direction}{code}`.")  # fmt: skip


def _appended() -> list[str]:
    return [
        "path = main_md(project)",
        'path.write_text(path.read_text(encoding="utf-8") + "\\n\\n" + text + "\\n",',
        '                encoding="utf-8")',
    ]


def _assertion(asked: Asked, counted: bool) -> list[str]:
    code = asked.code or "<code>"
    if counted:
        holds = "==" if asked.flagged else ">"
        said = f'found.count("{code}") {holds} before.count("{code}")'
    else:
        said = f'"{code}" {"not in" if asked.flagged else "in"} found'
    if asked.code is None:
        which = "should not have given" if asked.flagged else "should have given"
        return [
            f"# TODO: no finding's code was named. Name the one it {which}:",
            f"#     assert {said}",
            'pytest.fail("TODO: assert on the code of the finding")',
        ]
    return [f"assert {said}"]


def _literal(snippet: str) -> list[str]:
    """`text = ...`: the snippet as a Python string, a piece to a line."""
    pieces = [
        line[start:start + PIECE]
        for line in snippet.splitlines(keepends=True)
        for start in range(0, len(line), PIECE)
    ]  # fmt: skip
    if len(pieces) == 1:
        return [f"text = {_quoted(pieces[0])}"]
    return ["text = (", *(f"    {_quoted(piece)}" for piece in pieces), ")"]


def _quoted(piece: str) -> str:
    """`piece` as a Python string in double quotes. JSON writes one that Python reads as the
    same string, escapes and all."""
    return json.dumps(piece, ensure_ascii=False)
