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
  state, and so each number above 1 of a box and of a graphical abstract's line, a graphical
  abstract's number that is not whole ("2.5") and its aspect ratio ("16:9"). A limit of 0 or
  1 is held to the page only, since its quote may say "no" or "a".
* `journal-rule-unquoted` (warning): the rules that carry no quote, named together.
* `journal-quote-names-no-rule` (warning): a quote for a rule the profile does not have.
* `journal-page-not-stored` (warning): the page is not there to hold the quotes to.
* `journal-page-changed` (warning): the page is not the text the profile recorded.
* `journal-manual-unsigned` (warning): the rules under `manual:`, which no gate checks, until
  the corresponding author signs them off (`manual_signable`). `submit` puts them in the pack
  as a checklist, `journal-checklist.md` (`journal_checklist`), with their quotes and the
  sign-off, so that a rule no gate holds is still held by a named person.

A box, the graphical abstract and the sharing policy may name a page of their own
(`page_file`), read apart from the instructions; their quotes are held to it (`pages_of`).

A profile a year old is read against the page again (`reread`, `journal --reread <file>`,
with `--page` for a block's page of its own, each read on its own):
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
    for name, value in (document.get("abbreviations") or {}).items():
        rules[f"abbreviations.{name}"] = value
    if document.get("reporting_guidelines"):
        rules["reporting_guidelines"] = document["reporting_guidelines"]
    for name, form in (document.get("pointers") or {}).items():
        rules[f"pointers.{name}"] = form
    # How the journal takes a LaTeX source, each part of it a rule of the page.
    for name, value in (document.get("latex") or {}).items():
        rules[f"latex.{name}"] = value
    # A graphical abstract's rules, each its own; a box's, one quote for the box; and what
    # may be shared of each version of the paper. Where a block was read, when, and the page
    # of its own it was stored as are no rules of the page (`PAGE_KEYS`).
    for name, value in (document.get("graphical_abstract") or {}).items():
        if name not in PAGE_KEYS:
            rules[f"graphical_abstract.{name}"] = value
    for box in document.get("boxes") or []:
        if isinstance(box, dict) and box.get("id"):
            rules[f"boxes.{box['id']}"] = box
    for name, value in (document.get("sharing") or {}).items():
        if name not in PAGE_KEYS:
            rules[f"sharing.{name}"] = value
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
        # A limit of none or of one is not held to its quote's number: a page writes it in
        # too many ways ("may not include figures", "Figures: none", "a single table") for
        # its words to say it, and each reading of them tried let a wrong limit through or
        # failed a right one. Its quote is still held to the page.
        for named, value in _numbers_of(str(key), rules.get(key)):
            if not (_states_ratio(quote, value) if isinstance(value, str)
                    else _states(quote, value)):  # fmt: skip
                findings.append(
                    _finding(
                        "journal-limit-not-in-quote",
                        FAIL,
                        f"{named} is {value}, and its quote does not say {value}: \"{quote}\"",
                        path,
                        "quote the words that state the limit, or correct the limit to what "
                        "the page says",
                    )
                )

    said = [(str(key), quote) for key, quote in quotes.items()]
    said += [(f"manual: {entry['rule']}", entry["quote"]) for entry in manual]
    for page in pages_of(project, slug, document):
        held = [(key, quote) for key, quote in said if page.holds(key)]
        findings += _held_to(project, page, held, path, bool(quotes or manual))
    return Report(tuple(findings))


#: The numbers of a box, each of which its quote has to state where it is above 1.
BOX_NUMBERS = ("items_min", "items_max", "item_max_chars", "item_max_words", "max_words")
#: What a block read from a page of its own says of that page, which is no rule of it.
PAGE_KEYS = ("page_file", "page_sha256", "source_url", "retrieved_on")


def _numbers_of(key: str, value: object) -> list[tuple[str, int | float | str]]:
    """Each number a rule states that its quote has to state, with what the finding calls
    it: a limit's, a line of the graphical abstract's, and each number of a box's. A whole
    number above 1; a number that is not whole, which a page can write only in digits
    (`max_file_mb: 2.5`); and the graphical abstract's aspect ratio, as its text ("16:9")."""

    def held(number: object) -> int | float | None:
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            return None
        if isinstance(number, float) and not number.is_integer():
            return number
        return int(number) if number > 1 else None

    if key == "graphical_abstract.aspect_ratio" and isinstance(value, str):
        return [(key, value)]
    if key.startswith(("limits.", "graphical_abstract.")):
        number = held(value)
        return [] if number is None else [(key, number)]
    if key.startswith("boxes.") and isinstance(value, dict):
        found = [(f"{key} {name}", held(value.get(name))) for name in BOX_NUMBERS]
        return [(named, number) for named, number in found if number is not None]
    return []


def _owner(key: str) -> str:
    """The block a quote belongs to, where a block may name a page of its own:
    `graphical_abstract`, `sharing` or `boxes.<id>`; "" for every other rule."""
    if key.startswith(("graphical_abstract.", "sharing.")):
        return key.split(".", 1)[0]
    return key if key.startswith("boxes.") else ""


@dataclass(frozen=True)
class Page:
    """A page the profile's quotes are held to: where it is stored, the digest the profile
    records of it, by each block that names it, where it was read, whether it is the
    instructions page, and the blocks whose quotes it holds: for a page of a block's own,
    those that name it (`page_file`); for the instructions page, every other, a block the
    profile does not have among them, as before blocks named pages (`elsewhere` are those it
    does not hold)."""

    path: Path
    recorded: tuple[tuple[str, str | None], ...]
    source: str
    instructions: bool
    blocks: tuple[str, ...] = ()
    elsewhere: tuple[str, ...] = ()

    def holds(self, key: str) -> bool:
        """Whether the quote filed under `key` is held to this page."""
        owner = _owner(key)
        if self.instructions:
            return owner not in self.elsewhere
        return owner != "" and owner in self.blocks

    @property
    def named(self) -> str:
        """What the page is called in a finding."""
        return "the stored page" if self.instructions else f"the page of {', '.join(self.blocks)}"


def pages_of(project: Project, slug: str, document: dict) -> list[Page]:
    """The instructions page, then each page of its own a block names (`page_file`), once
    each, two blocks naming one page sharing it. A block that names none is held to the
    instructions page, and so is one that names that page."""
    blocks = [(name, document[name]) for name in ("graphical_abstract", "sharing")
              if isinstance(document.get(name), dict)]  # fmt: skip
    blocks += [(f"boxes.{box['id']}", box) for box in document.get("boxes") or ()
               if isinstance(box, dict) and box.get("id")]  # fmt: skip
    instructions = page_path(project, slug, document)
    own: dict[Path, Page] = {}
    held_there: list[str] = []
    for name, block in blocks:
        where = project.root / str(block["page_file"]) if block.get("page_file") else None
        if where is None or where == instructions:
            held_there.append(name)
            continue
        known = own.get(where)
        own[where] = Page(
            where,
            (*(known.recorded if known else ()), (name, block.get("page_sha256"))),
            known.source if known else str(block.get("source_url") or f"the page of {name}"),
            False,
            (*(known.blocks if known else ()), name),
        )
    elsewhere = tuple(name for page in own.values() for name in page.blocks)
    first = Page(instructions, (("", document.get("page_sha256")),),
                 str(document.get("source_url") or "the instructions page"), True,
                 tuple(held_there), elsewhere)  # fmt: skip
    return [first, *own.values()]


def _held_to(project: Project, page: Page, said: list[tuple[str, str]], path: Path,
             quoted: bool) -> list[Finding]:  # fmt: skip
    """What the quotes held to `page` say of it: that it is not stored, that it is not the
    text the profile recorded, and each quote that is not on it."""
    try:
        text = page.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # The instructions page is said wherever the profile quotes anything, as before; a
        # page of a block's own only where a quote is held to it.
        if not (quoted if page.instructions else said):
            return []
        held = ("quote of the profile" if page.instructions
                else f"quote of {', '.join(page.blocks)}")  # fmt: skip
        return [_finding(
            "journal-page-not-stored",
            WARN,
            f"the journal's page is not stored at {_where(page.path, project)}, so no {held} "
            "can be held to it",
            path,
            f"save {page.source} there as text, as read on the date the profile records",
        )]  # fmt: skip
    findings: list[Finding] = []
    # Each block that names the page with a digest that is not its text, so that two blocks
    # naming one page with two digests have the stale one said (round 1 of #464: the first
    # block's digest was the page's, and the second's was never read).
    stale = [(name, recorded) for name, recorded in page.recorded
             if recorded != page_digest(text)]  # fmt: skip
    if stale:
        recorded = next((digest for _name, digest in stale if digest), None)
        said_of = (
            f"is not the text the profile recorded (page_sha256 {str(recorded)[:12]}...)"
            if recorded
            else "has no digest in the profile"
        )
        under = "" if page.instructions else f" under {', '.join(name for name, _ in stale)}"
        findings.append(
            _finding(
                "journal-page-changed",
                WARN,
                f"{_where(page.path, project)} {said_of}",
                path,
                f"once the profile is read against this text, record page_sha256: "
                f"{page_digest(text)}{under}",
            )
        )
    for key, quote in said:
        if not _on_page(text, quote):
            findings.append(
                _finding(
                    "journal-quote-not-on-page",
                    FAIL,
                    f"the quote for {key} is not on {page.named}: \"{quote}\"",
                    path,
                    "copy the words from the page as it writes them, or remove the rule: one "
                    "read wrong, or never on the page, fails as surely as it misleads",
                )
            )
    return findings


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
    #: The blocks whose page it is, where it is a page of their own: where its digest goes.
    blocks: tuple[str, ...] = ()


def reread(project: Project, new_text: str, page: str | None = None) -> Reread | None:
    """The target journal's stored page against `new_text`, the page read again; None where
    the project has no profile to read it for. `page` is a page of its own that a block names
    (`page_file`, as the profile writes it), read again in its place; without it, the
    instructions page. Only the quotes held to that page are read against it, so that the
    text of a policy kept on its own page is not taken for text gone from the instructions
    page. A rule whose quote is not on the new page is one the page may have changed, and is
    read again; the rest of the difference is for the author to read, a rule the page added
    among it. Raises LookupError where `page` is no page of the profile's, the instructions
    page among them, and ValueError, with what the schema says, where a block that may name
    a page of its own is not valid."""
    found = _target_profile(project)
    if found is None:
        return None
    slug, document, path = found
    wrong = _blocks_invalid(document)
    if wrong:
        raise ValueError(f"{_where(path, project)}: " + "; ".join(wrong))
    pages = pages_of(project, slug, document)
    chosen = pages[0] if page is None else next(
        (one for one in pages if _same(one.path, project.root / page)), None)  # fmt: skip
    if chosen is None:
        named = [_where(one.path, project) for one in pages]
        raise LookupError(f"{page} is no page of the profile; its pages: "
                          f"{', '.join(named)}")  # fmt: skip
    try:
        old = chosen.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        old = ""
    diff = tuple(difflib.unified_diff(
        old.splitlines(), new_text.splitlines(), "stored page", "page read again", n=1,
        lineterm="",
    ))  # fmt: skip
    said = [(str(key), str(quote)) for key, quote in (document.get("quotes") or {}).items()
            if chosen.holds(str(key))]  # fmt: skip
    if chosen.instructions:
        said += [(f"manual: {entry.get('rule')}", str(entry.get("quote", "")))
                 for entry in document.get("manual") or () if isinstance(entry, dict)]  # fmt: skip
    rules = tuple((key, _on_page(new_text, quote)) for key, quote in said)
    blocks = () if chosen.instructions else chosen.blocks
    return Reread(chosen.path, diff, rules, page_digest(new_text), blocks)


#: The blocks `pages_of` reads, which may each name a page of their own.
PAGED_BLOCKS = ("boxes", "graphical_abstract", "sharing")


def _blocks_invalid(document: dict) -> list[str]:
    """What the schema says is wrong with the blocks `pages_of` reads, and nothing else of
    the profile: a reread reads the page again for a profile the schema refuses elsewhere,
    as it did before blocks named pages (round 2 of #464), and is kept from a block it
    cannot read (`boxes: 3`, round 1)."""
    from jsonschema import Draft202012Validator

    from manuscript_guard.contracts._schema import load_schema

    validator = Draft202012Validator(load_schema("journal"))
    return [f"{'/'.join(str(p) for p in error.absolute_path)}: {error.message}"
            for error in validator.iter_errors(document)
            if error.absolute_path and error.absolute_path[0] in PAGED_BLOCKS]  # fmt: skip


def _same(one: Path, other: Path) -> bool:
    """Whether two paths name one file, written as they may be: `a/../b` and `b`."""
    try:
        return one.resolve() == other.resolve()
    except OSError:
        return one == other


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


#: A number that is not whole, as its digits: "2.5" or "2.50", or with a comma, "2,5" or
#: "2,50"; not inside a longer number, and not a comma before three digits, a separator of
#: thousands ("2,500").
_DECIMAL = r"(?<![0-9.,]){}(0*)(?![0-9]|[.,][0-9])"
#: The marks a page writes a decimal with: a point, or a comma (round 2 of #464).
_DECIMAL_MARKS = (".", ",")
#: Between the two parts of a ratio: a colon, a multiplication sign, an x or a slash, with
#: spaces or none, or "by" between spaces ("16:9", "16 : 9", "16 x 9", "16/9", "16 by 9").
_RATIO_SIGN = r"(?:[ \t]*[:x/" + chr(0xD7) + r"][ \t]*|[ \t]+by[ \t]+)"
#: Every sign of `_RATIO_SIGN` but the slash, which a date writes too.
_RATIO_MARK = r"(?:[ \t]*[:x" + chr(0xD7) + r"][ \t]*|[ \t]+by[ \t]+)"
#: An aspect ratio's two parts, in their order, neither inside a longer number nor a longer
#: ratio or date: "1:16:9", "16:9:4", "16/9/2026" and "2026/16/9" do not state 16:9. A
#: label's colon ("ratio:16:9") and a slash between two ratios ("4:3/16:9") do not hide it:
#: only a slash ratio is refused beside another slash (fix-only round of #464).
_RATIO = (r"(?:(?<![0-9.,])(?<![0-9]:){0}" + _RATIO_MARK.replace("{", "{{")
          + r"{1}(?![0-9]|[.,:][0-9])"
          r"|(?<![0-9.,])(?<![0-9][:/]){0}[ \t]*/[ \t]*{1}(?![0-9]|[.,:/][0-9]))")  # fmt: skip


def _decimal(value: float) -> str:
    """A number that is not whole as a page writes it in digits: 2.5, not 2.500000."""
    return f"{value:.10f}".rstrip("0")


def _states_ratio(quote: str, ratio: str) -> bool:
    """Whether a quote states an aspect ratio as the profile writes it ("16:9"): both its
    parts, in their order, with a colon, a multiplication sign, an x, a slash or "by" between
    them, neither inside a longer number or ratio. "5:2", "16:10" and "1:16:9" do not state
    16:9."""
    first, _colon, second = ratio.partition(":")
    pattern = _RATIO.format(re.escape(first), re.escape(second))
    return re.search(pattern, normalise(quote).lower()) is not None


def _states(quote: str, value: int | float) -> bool:
    """Whether a quote states a number: a whole one as digits, with or without a separator
    of thousands ("3500", "3,500", "3 500"), or as a word up to twenty; one that is not
    whole as its digits, with a point or a comma ("2.5", "2.50", "2,5")."""
    text = normalise(quote).lower()
    if isinstance(value, float) and not value.is_integer():
        point = _decimal(value)
        whole, _point, tenths = point.partition(".")
        for form in (f"{whole}{mark}{tenths}" for mark in _DECIMAL_MARKS):
            for found in re.finditer(_DECIMAL.format(re.escape(form)), text):
                after = len(tenths) + len(found.group(1))
                if "," not in form or after != 3:
                    return True
        return False
    value = int(value)
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
