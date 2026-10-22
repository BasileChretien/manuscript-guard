"""G4 — each rule of a journal profile is on the page it was read from.

A profile is filled from the journal's instructions page, by a person or by an agent, and
the journal-profile skill warns that a guessed limit produces confident failures about a
rule that does not exist. Nothing checked that a rule in the profile was on the page. An
agent could invent one or misread one, and a rule it skipped was lost without a trace.

So the page is stored in the project when the profile is filled, as text
(`profiles/journals/sources/<name>.txt`, or `page_file`), and each rule carries the words it
was read from (`quotes:`, keyed by the rule), as a value in the literature ledger carries its
quote. A rule no gate checks goes under `manual:` with its quote, rather than nowhere.

* `journal-quote-not-on-page` (fails): a quote that is not in the stored page.
* `journal-limit-not-in-quote` (fails): a limit above 1 whose number its quote does not
  state. A limit of 0 or 1 is held to the page only, since its quote may say "no" or "a".
* `journal-rule-unquoted` (warning): the rules that carry no quote, named together.
* `journal-quote-names-no-rule` (warning): a quote for a rule the profile does not have.
* `journal-page-not-stored` (warning): the page is not there to hold the quotes to.
* `journal-page-changed` (warning): the page is not the text the profile recorded.
* `journal-manual-unsigned` (warning): the rules under `manual:`, which no gate checks, until
  the corresponding author signs them off (`manual_signable`). `submit` puts them in the pack
  as a checklist, `journal-checklist.md` (`journal_checklist`), with their quotes and the
  sign-off, so that a rule no gate holds is still held by a named person.

A profile a year old is read against the page again (`reread`, `journal --reread <file>`):
what changed between the stored page and the new one, and which rules' quotes are no longer
on it, which are the rules to read again.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, INFO, WARN, Finding, Report
from manuscript_guard.literature.sources import normalise
from manuscript_guard.sign_offs import CORRESPONDING, Signable, digest_of, settle

GATE = "G4"
#: Where the page is stored where the profile does not say: beside the project's profiles.
PAGES = Path("profiles") / "journals" / "sources"
#: Numbers a page may write as words: "no more than five figures".
_WORDS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
]  # fmt: skip


def page_path(project: Project, slug: str, document: dict) -> Path:
    """Where the profile's page is stored: `page_file`, from the project's root, or else
    `profiles/journals/sources/<slug>.txt`."""
    named = document.get("page_file")
    return project.root / (named if named else PAGES / f"{slug}.txt")


def page_digest(text: str) -> str:
    """The digest a profile records of its page (`page_sha256`): of its text, line endings
    as LF, so that a checkout changes nothing."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def rules_of(document: dict) -> dict[str, object]:
    """Every rule the profile states, by the key its quote is filed under."""
    rules: dict[str, object] = {}
    for name, value in (document.get("limits") or {}).items():
        rules[f"limits.{name}"] = value
    structure = document.get("structure") or {}
    if structure.get("required_sections"):
        rules["structure.required_sections"] = structure["required_sections"]
    for name in ("abstract_structured", "abstract_headings", "abstract_title"):
        if name in structure:
            rules[f"structure.{name}"] = structure[name]
    for statement in document.get("required_statements") or []:
        rules[f"required_statements.{statement['id']}"] = statement
    if document.get("references"):
        rules["references"] = document["references"]
    for name in ("english_variant", "blinding", "text_recycling"):
        if name in document:
            rules[name] = document[name]
    if document.get("reporting_guidelines"):
        rules["reporting_guidelines"] = document["reporting_guidelines"]
    for name, form in (document.get("pointers") or {}).items():
        rules[f"pointers.{name}"] = form
    return rules


def check_quotes(project: Project, slug: str, document: dict, path: Path) -> Report:
    """Each rule of the profile, held to the words it was read from, and those words to the
    stored page."""
    quotes: dict[str, str] = document.get("quotes") or {}
    manual: list[dict] = document.get("manual") or []
    rules = rules_of(document)
    findings: list[Finding] = []

    unquoted = [key for key in rules if key not in quotes]
    if unquoted:
        findings.append(
            _finding(
                "journal-rule-unquoted",
                WARN,
                f"{len(unquoted)} rule(s) of the profile carry no quote from the journal's page: "
                f"{', '.join(unquoted)}",
                path,
                "under `quotes:`, give each the words of the page it was read from, as the "
                "page writes them; a rule that is not on the page is not a rule",
            )
        )
    for key in quotes:
        if key not in rules:
            findings.append(
                _finding(
                    "journal-quote-names-no-rule",
                    WARN,
                    f"`quotes:` names {key}, which the profile does not state",
                    path,
                    "correct the key, or remove the quote with the rule it was for",
                )
            )

    for key, quote in quotes.items():
        value = rules.get(key)
        # A limit of none or of one is not held to its quote's number: a page writes it in
        # too many ways ("may not include figures", "Figures: none", "a single table") for
        # its words to say it, and each reading of them tried let a wrong limit through or
        # failed a right one. Its quote is still held to the page.
        if (
            str(key).startswith("limits.")
            and isinstance(value, int)
            and value > 1
            and not _states(quote, value)
        ):
            findings.append(
                _finding(
                    "journal-limit-not-in-quote",
                    FAIL,
                    f"{key} is {value}, and its quote does not say {value}: \"{quote}\"",
                    path,
                    "quote the words that state the limit, or correct the limit to what the "
                    "page says",
                )
            )

    page = page_path(project, slug, document)
    try:
        text = page.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        if quotes or manual:
            findings.append(
                _finding(
                    "journal-page-not-stored",
                    WARN,
                    f"the journal's page is not stored at {_where(page, project)}, so no "
                    "quote of the profile can be held to it",
                    path,
                    f"save {document.get('source_url', 'the instructions page')} there as "
                    "text, as read on the date the profile records",
                )
            )
        return Report(tuple(findings))

    recorded = document.get("page_sha256")
    if recorded != page_digest(text):
        said = (
            f"is not the text the profile recorded (page_sha256 {str(recorded)[:12]}...)"
            if recorded
            else "has no digest in the profile"
        )
        findings.append(
            _finding(
                "journal-page-changed",
                WARN,
                f"{_where(page, project)} {said}",
                path,
                f"once the profile is read against this text, record page_sha256: "
                f"{page_digest(text)}",
            )
        )
    said = [(key, quote) for key, quote in quotes.items()]
    said += [(f"manual: {entry['rule']}", entry["quote"]) for entry in manual]
    for key, quote in said:
        if not _on_page(text, quote):
            findings.append(
                _finding(
                    "journal-quote-not-on-page",
                    FAIL,
                    f"the quote for {key} is not on the stored page: \"{quote}\"",
                    path,
                    "copy the words from the page as it writes them, or remove the rule: one "
                    "read wrong, or never on the page, fails as surely as it misleads",
                )
            )
    return Report(tuple(findings))


def manual_signable(slug: str, document: dict, path: Path) -> Signable | None:
    """The profile's `manual:` rules, which no gate checks, as one finding the corresponding
    author signs off, bound to the rules, their quotes and the page they were read from: a
    rule added, a quote changed or the page read again wants it signed again."""
    manual = [entry for entry in document.get("manual") or () if isinstance(entry, dict)]
    if not manual:
        return None
    key = f"{GATE}/journal-manual/{slug}"
    rules = [str(entry.get("rule")) for entry in manual]
    raised = _finding(
        "journal-manual-unsigned", WARN,
        f"{len(rules)} rule(s) of the {slug} profile are checked by no gate: "
        f"{'; '.join(rules)}", path,
        "each is in the submission pack's journal-checklist.md (`manuscript-guard submit`); "
        "the corresponding author checks them against the paper and signs them off",
    )  # fmt: skip
    rules_and_quotes = [[entry.get("rule"), entry.get("quote")] for entry in manual]
    digest = digest_of(key, rules_and_quotes, document.get("page_sha256"))
    return Signable(CORRESPONDING, key, digest, (raised,))


def _target_profile(project: Project) -> tuple[str, dict, Path] | None:
    """The target journal's profile, read, or None where there is none to read: the gate
    says why."""
    from manuscript_guard.gates.journal import profile_path

    slug = project.target_journal
    path = profile_path(project, slug) if slug else None
    if path is None:
        return None
    try:
        document = read_structured(path)
    except ContractError:
        return None
    return (slug, document, path) if isinstance(document, dict) else None


def manual_signables(project: Project) -> list[Signable]:
    """What `manuscript-guard sign` may sign of the journal's rules."""
    found = _target_profile(project)
    signable = manual_signable(*found) if found else None
    return [signable] if signable else []


def journal_checklist(project: Project) -> str | None:
    """The pack's checklist of the journal's rules no gate checks, each with the words of
    the page it was read from, and who signed them off; None where the profile has none."""
    found = _target_profile(project)
    signable = manual_signable(*found) if found else None
    if found is None or signable is None:
        return None
    slug, document, _path = found
    source = document.get("source_url") or "the journal's instructions page"
    read_on = document.get("retrieved_on")
    lines = [
        "# The journal's rules that no check holds",
        "",
        f"From the {slug} profile, read from {source}"
        + (f" on {read_on}" if read_on else "")
        + ". Each is checked by hand against the paper before it is submitted.",
        "",
        "| Checked | Rule | The journal's words |",
        "|---|---|---|",
    ]
    for entry in document.get("manual") or ():
        if isinstance(entry, dict):
            cells = [str(entry.get("rule", "")), str(entry.get("quote", ""))]
            lines.append("| [ ] | " + " | ".join(_cell(cell) for cell in cells) + " |")
    # The last of what `settle` says: a sign-off it cannot read comes with a finding of its
    # own first (round 1 of #318: unpacked as one, it raised while the pack was assembled).
    said = settle(project, signable)[-1]
    # Who signed is after the rules, which may themselves hold "; " (round 1 of #318).
    _rules, _marker, signed = said.message.rpartition("; signed off by ")
    lines += [
        "",
        f"Signed off by {signed}." if said.severity == INFO and _marker
        else "Not signed off yet by the corresponding author.",
    ]  # fmt: skip
    return "\n".join(lines) + "\n"


#: How many lines of the difference `journal --reread` prints at the most.
DIFF_LINES = 200


@dataclass(frozen=True)
class Reread:
    """The stored page against the page read again."""

    stored: Path
    #: The difference, line by line, unified.
    diff: tuple[str, ...]
    #: Each rule, `manual:` ones as "manual: <rule>", and whether its quote is on the new page.
    rules: tuple[tuple[str, bool], ...]
    digest: str


def reread(project: Project, new_text: str) -> Reread | None:
    """The target journal's stored page against `new_text`, the page read again; None where
    the project has no profile to read it for. A rule whose quote is not on the new page is
    one the page may have changed, and is read again; the rest of the difference is for the
    author to read, a rule the page added among it."""
    found = _target_profile(project)
    if found is None:
        return None
    slug, document, _path = found
    stored = page_path(project, slug, document)
    try:
        old = stored.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        old = ""
    diff = tuple(difflib.unified_diff(
        old.splitlines(), new_text.splitlines(), "stored page", "page read again", n=1,
        lineterm="",
    ))  # fmt: skip
    said = list((document.get("quotes") or {}).items())
    said += [(f"manual: {entry.get('rule')}", str(entry.get("quote", "")))
             for entry in document.get("manual") or () if isinstance(entry, dict)]  # fmt: skip
    rules = tuple((str(key), _on_page(new_text, str(quote))) for key, quote in said)
    return Reread(stored, diff, rules, page_digest(new_text))


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _where(page: Path, project: Project) -> str:
    """The page's path as said: from the project's root where it is in the project."""
    try:
        return page.relative_to(project.root).as_posix()
    except ValueError:
        return page.as_posix()


def _on_page(page: str, quote: str) -> bool:
    """Whether a quote is on the page as the words it is, folded as G7 folds a quote
    (`contains`): not the end of a longer number or word, nor the start of one. "50 words" is
    in "250 words" as characters, and is not what the page says."""
    haystack, needle = normalise(page).lower(), normalise(quote).lower()
    if not needle:
        return False
    at = haystack.find(needle)
    while at >= 0:
        before = haystack[at - 1] if at else ""
        after = haystack[at + len(needle) : at + len(needle) + 1]
        if not (needle[0].isalnum() and before.isalnum()) and not (
            needle[-1].isalnum() and after.isalnum()
        ):
            return True
        at = haystack.find(needle, at + 1)
    return False


#: A number's digits, not inside a longer number: 13500, 3500.5 and 3,5000 do not state 3500.
_DIGITS = r"(?<![0-9.,]){}(?![.,]?[0-9])"
#: A group of one or two digits and a space, before a group of three: "3 500" and "12 500"
#: are thousands, and do not state 500. "3500 250" and "900 150", a limits table saved as
#: text, state 250 and 150: no journal's limit runs to 100,000.
_GROUP_BEFORE = re.compile(r"(?:\A|[^0-9.,])[0-9]{1,2} \Z")
#: A number's word, not inside a longer word: "fourteen" and "fourfold" do not state 4.
_WORD = r"\b{}\b"


def _forms(value: int) -> set[str]:
    """The ways a page writes a number in digits: with or without a separator of thousands."""
    return {str(value), f"{value:,}", f"{value:,}".replace(",", " ")}


def _states(quote: str, value: int) -> bool:
    """Whether a quote states a whole number: as digits, with or without a separator of
    thousands ("3500", "3,500", "3 500"), or as a word up to twenty."""
    text = normalise(quote).lower()
    for form in _forms(value):
        for found in re.finditer(_DIGITS.format(re.escape(form)), text):
            three = len(form) == 3 and form.isdigit()
            if not (three and _GROUP_BEFORE.search(text[: found.start()])):
                return True
    if not 0 <= value < len(_WORDS):
        return False
    return re.search(_WORD.format(_WORDS[value]), text) is not None


def _finding(code: str, severity: str, message: str, path: Path, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=severity, message=message, path=path,
                   hint=hint)  # fmt: skip
