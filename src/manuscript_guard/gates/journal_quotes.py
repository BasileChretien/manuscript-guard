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
* `journal-limit-not-in-quote` (fails): a limit whose number its quote does not state.
* `journal-rule-unquoted` (warning): the rules that carry no quote, named together.
* `journal-quote-names-no-rule` (warning): a quote for a rule the profile does not have.
* `journal-page-not-stored` (warning): the page is not there to hold the quotes to.
* `journal-page-changed` (warning): the page is not the text the profile recorded.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.findings import FAIL, WARN, Finding, Report
from manuscript_guard.literature.sources import contains, normalise

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
    for name in ("english_variant", "blinding"):
        if name in document:
            rules[name] = document[name]
    if document.get("reporting_guidelines"):
        rules["reporting_guidelines"] = document["reporting_guidelines"]
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
        if key.startswith("limits.") and isinstance(value, int) and not _states(quote, value):
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
                    f"the journal's page is not stored at {page.relative_to(project.root)}, "
                    "so no quote of the profile can be held to it",
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
                f"{page.relative_to(project.root)} {said}",
                path,
                f"once the profile is read against this text, record page_sha256: "
                f"{page_digest(text)}",
            )
        )
    said = [(key, quote) for key, quote in quotes.items()]
    said += [(f"manual: {entry['rule']}", entry["quote"]) for entry in manual]
    for key, quote in said:
        if not contains(text, quote):
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


#: A number's digits, not inside a longer number: 13500, 3500.5 and 3,5000 do not state 3500.
_DIGITS = r"(?<![0-9.,]){}(?![.,]?[0-9])"
#: A number's word, not inside a longer word: "fourteen" and "fourfold" do not state 4.
_WORD = r"\b{}\b"


def _forms(value: int) -> set[str]:
    """The ways a page writes a number in digits: with or without a separator of thousands."""
    return {str(value), f"{value:,}", f"{value:,}".replace(",", " ")}


def _states(quote: str, value: int) -> bool:
    """Whether a quote states a whole number: as digits, with or without a separator of
    thousands ("3500", "3,500", "3 500"), or as a word up to twenty."""
    text = normalise(quote).lower()
    if any(re.search(_DIGITS.format(re.escape(form)), text) for form in _forms(value)):
        return True
    if not 0 <= value < len(_WORDS):
        return False
    return re.search(_WORD.format(_WORDS[value]), text) is not None


def _finding(code: str, severity: str, message: str, path: Path, hint: str) -> Finding:
    return Finding(gate=GATE, code=code, severity=severity, message=message, path=path,
                   hint=hint)  # fmt: skip
