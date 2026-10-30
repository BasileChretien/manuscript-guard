"""The report a person reads, edits and posts about a failure of the tool's own.

Nothing here sends anything. `from_record` writes the body from a record (`crashes`), and
`general` from a title and a note; `links` gives the address of GitHub's new-issue page with
the report filled in, and of a search for the same fingerprint, so that a fault already
reported is found first. The person reads the body in the terminal and again on the page, and
their click on Submit there is what posts it.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

#: GitHub may refuse a longer address; the body then goes by file and paste.
LONGEST_LINK = 7500
#: The label a report asks for. GitHub applies a label from the address only for people
#: who may triage the repository; for anyone else it is ignored, and nothing fails.
LABEL = "bug"
#: Put before the fingerprint in a title, so that a search for it finds the report.
MARK = "mg-"
HEAD = ("<!-- Written by `manuscript-guard report-issue`. Everything below is what would be "
        "posted: read it, edit it, and only then submit. -->")  # fmt: skip
SHORTENED = ("The report was too long for a link. Paste it here: `manuscript-guard "
             "report-issue` printed it whole in the terminal.")  # fmt: skip
#: A browser may cut an address it is handed past about this length (Windows' ShellExecute),
#: so `--open` opens the page with the title only past it, and the body is pasted.
LONGEST_OPENED = 2000
#: GitHub refuses a title past 256 characters.
LONGEST_TITLE = 200
#: And a title of 200 characters in another script is 1,800 encoded.
LONGEST_ENCODED_TITLE = 600
_SHORTEST_PREFIX = 4
_FINGERPRINT_REPORT = re.compile(r"^[0-9a-f]{12}\.md$")
_GENERAL_REPORT = re.compile(r"^report-\d{8}-\d{6}-[0-9a-f]{6}\.md$")
_KEPT_GENERAL = 20


@dataclass(frozen=True)
class Links:
    #: The new-issue page with the title and the body filled in, or with the title only and
    #: `SHORTENED` where the whole would be past `LONGEST_LINK`.
    new: str
    #: The new-issue page with the title and `SHORTENED`, for a browser that cuts long addresses.
    short: str
    #: The search of the issues for the report's fingerprint, where it has one.
    search: str | None
    #: Whether `new` carries `SHORTENED` rather than the body.
    shortened: bool


@dataclass(frozen=True)
class Report:
    title: str
    body: str
    #: The file's name, without its folder.
    name: str
    fingerprint: str | None = None
    #: The label the issue page is asked for: `bug`, or `gate` for a report about a gate.
    label: str = LABEL


def from_record(record: dict, *, with_message: bool, installed: str,
                note: str | None = None) -> Report:  # fmt: skip
    """The report of one recorded failure. Its message is left out unless asked for, since it
    can quote the author's files."""
    fingerprint = record["fingerprint"]
    parts = [
        HEAD,
        f"**What failed:** {_what(record)}: `{record['exception']}`.",
        f"**Fingerprint:** `{MARK}{fingerprint}`, met {_times(record['count'])} "
        f"between {record['first_seen'][:10]} and {record['last_seen'][:10]}.",
        f"**Version:** manuscript-guard {record['version']}, Python {record['python']}, "
        f"{record['system']}.",
        f"**Flags given:** {_flags(record)} (their values are never recorded).",
        "**Where, innermost last:**\n\n" + fenced("\n".join(_frame(f) for f in record["frames"])),
        _message(record, with_message),
        "**What I was doing** (what you ran and what you expected; not your manuscript's own "
        "text):\n\n" + (note.strip() if note else ""),
    ]
    if record["version"] != installed:
        parts.insert(2, f"**Note:** recorded under {record['version']}; the version installed "
                        f"when this report was written is {installed}.")  # fmt: skip
    return Report(title=_title(record), body="\n\n".join(parts).rstrip() + "\n",
                  name=f"{fingerprint}.md", fingerprint=fingerprint)  # fmt: skip


def general(title: str, note: str | None, *, installed: str) -> Report:
    """A report of anything else: something that went wrong without an error, or a
    suggestion."""
    from manuscript_guard.diagnostics.crashes import python_version, system_name

    python, system = python_version(), system_name()
    text = note.strip() if note else (
        "(What happened, what you expected, and the smallest text that shows it, made up for "
        "the report rather than taken from your manuscript.)"
    )
    body = "\n\n".join([HEAD, f"**Summary:** {title.strip()}", text,
                        f"**Version:** manuscript-guard {installed}, Python {python}, {system}."])
    return Report(title=title.strip(), body=body + "\n", name=stamped_name())


def stamped_name() -> str:
    """The name of a report that has no record: the time it was written and a random tail,
    since the clock alone can give two reports the same name. `write` keeps the newest
    twenty of these."""
    return f"report-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.md"


def issues_page() -> str | None:
    """The project's issues page, from the installed package's metadata (`project.urls`)."""
    try:
        from importlib.metadata import metadata

        listed = metadata("manuscript-guard").get_all("Project-URL") or []
    except Exception:  # noqa: BLE001 - a source run on PYTHONPATH has no metadata
        return None
    for entry in listed:
        label, _, url = entry.partition(",")
        if label.strip().lower() == "issues" and url.strip().startswith("https://"):
            return url.strip().rstrip("/")
    return None


def links(report: Report, page: str | None) -> Links | None:
    """The addresses of the report's issue page, or None where the project's page is not
    known (a source run with no package metadata)."""
    if page is None:
        return None

    def asking(body: str) -> str:
        asked = {"title": cut_title(report.title), "body": body, "labels": report.label}
        return f"{page}/new?{urlencode(asked, quote_via=quote)}"

    whole, short = asking(report.body), asking(SHORTENED)
    shortened = len(whole) > LONGEST_LINK
    search = None
    if report.fingerprint:
        asked_for = {"q": f"is:issue {MARK}{report.fingerprint}"}
        search = f"{page}?{urlencode(asked_for, quote_via=quote)}"
    return Links(new=short if shortened else whole, short=short, search=search,
                 shortened=shortened)  # fmt: skip


def cut_title(title: str) -> str:
    """`title` within GitHub's limit, and short enough encoded that the address `--open`
    hands the browser stays within `LONGEST_OPENED`: a title in another script grows up to
    nine times when encoded. Cut after the scrub, so that the scrub reads it whole."""
    title = printable(title)
    if len(title) <= LONGEST_TITLE and len(quote(title, safe="")) <= LONGEST_ENCODED_TITLE:
        return title
    kept = title[: LONGEST_TITLE - 1]
    while kept and (len(quote(kept + "…", safe="")) > LONGEST_ENCODED_TITLE
                    or _joins(title[len(kept)])):  # a letter keeps its mark
        kept = kept[:-1]
    return kept.rstrip() + "…"


def _joins(character: str) -> bool:
    """Whether `character` belongs to the one before it: a mark (an accent, a vowel sign), a
    zero-width joiner or a variation selector."""
    import unicodedata

    return (unicodedata.category(character).startswith("M")
            or character == "\N{ZERO WIDTH JOINER}"
            or "\N{VARIATION SELECTOR-1}" <= character <= "\N{VARIATION SELECTOR-16}")


def printable(text: str) -> str:
    """`text` with what UTF-8 cannot write (a lone surrogate, from bytes that were not UTF-8
    in a command's arguments) written as `?`, so that it can be printed and encoded."""
    return text.encode("utf-8", "replace").decode("utf-8")


def find(records: list[dict], wanted: str) -> tuple[dict | None, str | None]:
    """The record `wanted` names, by its fingerprint or its first characters; or why none."""
    wanted = wanted.strip().lower().removeprefix(MARK)
    if len(wanted) < _SHORTEST_PREFIX:
        return None, f"give at least {_SHORTEST_PREFIX} characters of the fingerprint"
    found = [r for r in records if r["fingerprint"].startswith(wanted)]
    if len(found) == 1:
        return found[0], None
    if not found:
        return None, f"no record's fingerprint starts with {wanted!r}"
    return None, f"{len(found)} records' fingerprints start with {wanted!r}: give more of it"


def listing(records: list[dict]) -> str:
    """One line per record, the one met last first."""
    lines = []
    for record in records:
        lines.append(f"{record['fingerprint']}  {record['last_seen'][:10]}  "
                     f"x{record['count']:<3} {record['version']:<9} {_what(record)}: "
                     f"{record['exception']}")  # fmt: skip
    return "\n".join(lines)


def write(report: Report, folder: Path) -> Path:
    """The report written beside the records, and the reports no longer needed removed: one
    whose record is gone, and the general ones past the newest twenty. Only files of these
    two names are ever removed."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / report.name
    path.write_text(report.body, encoding="utf-8", newline="\n")
    general = sorted(p for p in folder.iterdir() if _GENERAL_REPORT.match(p.name))
    for old in general[:-_KEPT_GENERAL]:
        old.unlink(missing_ok=True)
    for kept in folder.iterdir():
        if _FINGERPRINT_REPORT.match(kept.name) and not kept.with_suffix(".json").exists():
            kept.unlink(missing_ok=True)
    return path


def _what(record: dict) -> str:
    command = f"`{record['command']}`" if record.get("command") else "the command"
    name = record.get("name")
    if record["kind"] == "gate":
        return f"gate {name} could not run during {command}"
    if record["kind"] == "hook":
        return f"the hook `{name}` failed, and kept out of the agent's way"
    if name:
        return f"{command} could not read {name}"
    if record.get("from_system"):
        return f"{command} stopped on an error from the system it did not expect"
    return f"{command} stopped on an error in manuscript-guard itself"


def _title(record: dict) -> str:
    inner = next((f for f in reversed(record["frames"]) if "file" in f), None)
    where = (f" in {inner['file'].removeprefix('manuscript_guard/')}:{inner['function']}"
             if inner else "")  # fmt: skip
    what = record.get("name") or record.get("command") or record["kind"]
    short = record["exception"].rsplit(".", 1)[-1]
    return f"[{MARK}{record['fingerprint']}] {what}: {short}{where}"


def _times(count: int) -> str:
    return "once" if count == 1 else f"{count} times"


def _flags(record: dict) -> str:
    flags = ", ".join(f"`{flag}`" for flag in record["flags"]) or "none"
    words = record.get("other_words", 0)
    return f"{flags}, and {words} other word{'s' if words != 1 else ''}"


def _frame(frame: dict) -> str:
    if "file" in frame:
        return f"{frame['file']}:{frame['line']} {frame['function']}"
    return f"({frame['module']})"


def _message(record: dict, with_message: bool) -> str:
    if not with_message:
        return ("**The error's message:** left out, since it can quote your files. "
                f"`manuscript-guard report-issue {record['fingerprint']} --with-message` adds "
                "it, with your folders, e-mail addresses and authors' names as written in "
                "authors.yaml replaced.")  # fmt: skip
    return ("**The error's message** (read it: it can quote your files, and only folders, "
            "e-mail addresses, credentials and authors' names were replaced):\n\n"
            + fenced(record["message"]))  # fmt: skip


def fenced(text: str, language: str = "text") -> str:
    """`text` in a code fence longer than any run of backticks inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"
