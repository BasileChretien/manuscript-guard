"""Assembling everything a journal asks for, from what the project already knows.

A submission is not one file. It is the manuscript, a title page carrying information the
manuscript deliberately does not, a CRediT statement, three or four declarations, the
completed reporting checklist, the figures in the format the publisher wants, and a
covering letter. Assembling that by hand, at the end, is where the last mistakes get made:
the title page lists an author who left the paper two revisions ago, the funding statement
contradicts the acknowledgements, the checklist points at a section that was renamed.

Everything except the covering letter is already recorded somewhere in the project, so
none of it is written twice. `authors.yaml` becomes the title page, the CRediT statement and
the declarations; the reporting completion file is copied as it stands; the build produces
the document. The manifest lists what went out, with checksums, because the question
"which version did we actually send" has no good answer six months later otherwise.

The pack refuses to assemble while the submission check fails. That is the point of having
the check.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from manuscript_guard import __version__
from manuscript_guard.contracts._schema import ContractError, read_structured
from manuscript_guard.contracts.project import Project
from manuscript_guard.text.sections import measure

CREDIT_ORDER = (
    "Conceptualization",
    "Data curation",
    "Formal analysis",
    "Funding acquisition",
    "Investigation",
    "Methodology",
    "Project administration",
    "Resources",
    "Software",
    "Supervision",
    "Validation",
    "Visualization",
    "Writing – original draft",
    "Writing – review & editing",
)


class SubmissionError(Exception):
    """The pack could not be assembled."""


@dataclass(frozen=True)
class Pack:
    directory: Path
    files: tuple[Path, ...]
    manifest: Path
    #: What the pack left out, and why: said by `submit` with the list of files.
    notes: tuple[str, ...] = ()


def _initials(author: dict) -> str:
    given = "".join(part[0] + "." for part in str(author["given"]).replace("-", " ").split())
    return f"{given}{author['family'][0]}."


def _superscripts(author: dict, order: list[str]) -> str:
    return ",".join(str(order.index(a) + 1) for a in author["affiliations"] if a in order)


def title_page(project: Project) -> str:
    """Everything the manuscript itself leaves out, in the order journals ask for it."""
    lines = _front_lines(project)
    counts = _counts(project)
    lines += [
        f"**Word count.** Abstract {counts.abstract_words}; main text "
        f"{counts.main_text_words}. Tables {counts.tables}; figures {counts.figures}.",
        "",
    ]
    return "\n".join(lines)


def printed_front(project: Project) -> str:
    """What the title page prints of `paper.yaml` and `authors.yaml`: all of it but the word
    counts, which the manuscript decides. An author's approval holds its digest (#284)."""
    return "\n".join(_front_lines(project))


def _front_lines(project: Project) -> list[str]:
    authors = project.authors
    if not authors:
        raise SubmissionError("authors.yaml is required for a title page")

    order = [a["id"] for a in authors["affiliations"]]
    paper = project.paper
    lines = [f"# {paper['title']}", ""]
    if paper.get("demonstration") is True:
        # The paper says what its numbers are not: results of real data (item 42).
        lines += ["**A demonstration.** The data of this paper are synthetic; its "
                  "results describe no real population.", ""]  # fmt: skip

    short = paper.get("short_title")
    if short:
        lines += [f"**Running title.** {short}", ""]

    names = []
    for author in authors["authors"]:
        degrees = ", ".join(author.get("degrees", []))
        name = f"{author['given']} {author['family']}"
        if degrees:
            name += f", {degrees}"
        marks = _superscripts(author, order)
        if marks:
            name += f"^{marks}^"
        if author.get("equal_contribution"):
            name += "\\*"
        names.append(name)
    lines += ["**Authors.** " + "; ".join(names), ""]

    lines.append("**Affiliations.**")
    lines.append("")
    for index, affiliation in enumerate(authors["affiliations"], start=1):
        lines.append(f"{index}. {affiliation['text']}")
    lines.append("")

    equal = [a for a in authors["authors"] if a.get("equal_contribution")]
    if equal:
        note = authors.get("equal_contribution_note") or (
            ", ".join(_initials(a) for a in equal) + " contributed equally to this work."
        )
        lines += [f"\\* {note}", ""]

    corresponding = [a for a in authors["authors"] if a.get("corresponding")]
    if corresponding:
        lines.append("**Corresponding author.**")
        lines.append("")
        for author in corresponding:
            block = [f"{author['given']} {author['family']}"]
            for identifier in author["affiliations"]:
                match = next((a for a in authors["affiliations"] if a["id"] == identifier), None)
                if match:
                    block.append(match["text"])
            if author.get("email"):
                block.append(author["email"])
            if author.get("orcid"):
                block.append(f"ORCID {author['orcid']}")
            lines.append("  \n".join(block))
        lines.append("")

    orcids = [
        f"{a['given']} {a['family']}: {a['orcid']}" for a in authors["authors"] if a.get("orcid")
    ]
    if orcids:
        lines += ["**ORCID.**", ""] + [f"- {o}" for o in orcids] + [""]

    keywords = project.keywords
    if keywords:
        lines += ["**Keywords.** " + "; ".join(keywords), ""]
    return lines


def response_letter(project: Project) -> str | None:
    """The point-by-point response, or `None` if this is not a resubmission.

    Generated here rather than read out of `build/`, so the pack carries the letter that
    matches the revision records rather than whatever `respond` last happened to write. A
    response is made almost entirely of claims about the paper — "we have revised the
    Methods" — and G13 checks each of them against the baseline the round recorded. Sending a
    stale letter would mean a checked set of claims and an unchecked document making them.
    """
    from manuscript_guard.gates.revision import rounds

    found = rounds(project)
    if not found:
        return None

    from manuscript_guard.gates.revision import displays
    from manuscript_guard.text.placeholders import substitute

    # The authors' words with every binding filled in, as the manuscript prints them.
    rendered = displays(project)

    def filled(text: str) -> str:
        return substitute(text, rendered)

    lines = ["# Response to reviewers", ""]
    for number, path in found:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            continue
        lines += [f"## Round {number} — {document.get('journal', '')}".rstrip(), ""]
        lines += [
            "We thank the reviewers for their comments. Each point is answered below, with "
            "what changed in the manuscript.",
            "",
        ]
        for reviewer in document.get("reviewers", []):
            lines += [f"### {reviewer['id'].replace('-', ' ').title()}", ""]
            for point in reviewer.get("points", []):
                lines += [f"**{point['id']}.** {point['comment'].strip()}", ""]
                response = filled(str(point.get("response", "")).strip())
                lines += [response or "_No response recorded._", ""]
                rebutted = filled(str(point.get("rebutted", "")).strip())
                if rebutted:
                    lines += [f"We have not made this change: {rebutted}", ""]
                for entry in point.get("changed") or []:
                    # Filled in as the reply is, since G2 holds its numbers to the results
                    # (round 1 of #349: a binding went to the journal as typed).
                    note = f" — {filled(str(entry['note']))}" if entry.get("note") else ""
                    if entry["kind"] == "text":
                        place = f" ({entry['section']})" if entry.get("section") else ""
                        quote = filled(str(entry["quote"]))
                        lines += [f"- The text now reads{place}: “{quote}”{note}"]
                        continue
                    lines += [f"- Changed: {entry['kind']} `{entry['name']}`{note}"]
                if point.get("changed"):
                    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _counts(project: Project):
    """What the title page declares to the editor: the main text, not the supplement.

    The same text the journal gate measures, so the count declared is the count checked.
    """
    from manuscript_guard.gates.journal import main_text

    return measure(main_text(project))


def credit_statement(project: Project) -> str:
    """CRediT roles, grouped by role rather than by author, as journals print them."""
    authors = project.authors
    if not authors:
        raise SubmissionError("authors.yaml is required for a CRediT statement")

    by_role: dict[str, list[str]] = {}
    for author in authors["authors"]:
        for role in author.get("credit", []):
            by_role.setdefault(role, []).append(_initials(author))

    if not by_role:
        return (
            "# CRediT author statement\n\nNo CRediT roles are recorded in authors.yaml. "
            "Most journals now require them.\n"
        )

    lines = ["# CRediT author statement", ""]
    for role in CREDIT_ORDER:
        if role in by_role:
            lines.append(f"**{role}:** {', '.join(by_role[role])}")
    extra = sorted(set(by_role) - set(CREDIT_ORDER))
    lines += [f"**{role}:** {', '.join(by_role[role])}" for role in extra]
    lines.append("")
    return "\n".join(lines)


def declarations(project: Project) -> str:
    """Funding and competing interests, from the one place they are recorded."""
    authors = project.authors
    if not authors:
        raise SubmissionError("authors.yaml is required for declarations")

    lines = ["# Declarations", ""]

    funding = []
    for author in authors["authors"]:
        for grant in author.get("funding", []):
            funding.append(f"{_initials(author)}: {grant}")
    lines += ["## Funding", ""]
    lines.append("\n".join(f"- {f}" for f in funding) if funding else "No funding is recorded.")
    lines.append("")

    lines += ["## Competing interests", ""]
    stated = [
        f"{a['given']} {a['family']}: {a['competing_interests']}"
        for a in authors["authors"]
        if str(a.get("competing_interests", "")).strip()
    ]
    unstated = [
        f"{a['given']} {a['family']}"
        for a in authors["authors"]
        if not str(a.get("competing_interests", "")).strip()
    ]
    if stated:
        lines += [f"- {s}" for s in stated]
    if unstated:
        # An empty field is not a declaration of none, and journals ask per author.
        lines.append("")
        lines.append(
            "No declaration is recorded for: " + ", ".join(unstated) + ". "
            "An empty field is not a declaration of none."
        )
    lines.append("")
    return "\n".join(lines)


def _escape_cell(text: str) -> str:
    """A pipe inside a cell ends the cell, so a checklist item containing one has to say so."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _is_scale(project: Project, completion: Path) -> bool:
    """Whether the guideline this completion answers is an appraisal scale.

    Read from the transcribed profile, which records what the recipe said it was, so the pack
    cannot call one thing by the other's name.
    """
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.reporting import checklist_path

    answers = read_structured(completion) or {}
    source = checklist_path(project, str(answers.get("guideline") or completion.stem))
    published = (read_structured(source) or {}) if source else {}
    return str(published.get("kind") or "").strip() == "scale"


def _published_text(item: dict, is_scale: bool) -> str:
    """What the pack prints for one item.

    For a scale, the item's own name, the clarifying line the form prints under some titles,
    and the options in the order the page has them — statement, then score. The profile's
    `text` joins them the other way round for a reader of the profile, and that string is in
    no document.
    """
    if not is_scale:
        return str(item.get("text", ""))
    head = " — ".join(
        part
        for part in (str(item.get("topic") or ""), str(item.get("clarification") or ""))
        if part
    )
    scored = "; ".join(
        f"{option.get('statement', '')} ({option.get('score', '')})"
        for option in item.get("options") or ()
    )
    return " — ".join(part for part in (head, scored) if part)


def checklist_table(project: Project, completion: Path) -> str:
    """A completed checklist as a journal reads it: item, where it is addressed, or why not.

    The pack shipped `reporting/*.yaml` and nothing else, so what a journal received in
    answer to "attach your completed STROBE checklist" was a serialisation. Generated rather
    than maintained, so it cannot drift from the file the gate checks — and the item text
    comes from the transcribed guideline, not from the completion, so an item nobody answered
    still appears with the answer blank rather than vanishing from the table.
    """
    from manuscript_guard.contracts._schema import read_structured
    from manuscript_guard.gates.reporting import checklist_path

    answers = read_structured(completion) or {}
    name = str(answers.get("guideline") or completion.stem)
    source = checklist_path(project, name)
    published = (read_structured(source) or {}) if source else {}
    items = published.get("items") or []
    # An appraisal scale is not a reporting checklist, and a journal reads the heading on the
    # file it is sent. Presented as one, SANRA arrived as a "checklist" whose scoring anchors
    # sat in a column called "Recommendation", which is the opposite of what adopting a scale
    # claims. The profile says which it is; `kind` is absent for every reporting guideline.
    is_scale = str(published.get("kind") or "").strip() == "scale"
    what = "appraisal scale" if is_scale else "checklist"

    lines = [f"# {name}, completed {what}" if is_scale else f"# {name} checklist", ""]
    if source is None:
        lines += [
            f"The {name} item list is not in this project, so this table can only show the "
            "answers, not the items they answer.",
            "",
        ]
    if is_scale:
        lines += [
            f"{published.get('long_name') or name} is an instrument for appraising a "
            "manuscript, not a reporting guideline: its items are what an editor or a reviewer "
            "scores, and the options below are the scores they choose between. This table says "
            "where each item is addressed; the scoring is the reader's to do.",
            "",
        ]
        if applies := published.get("applies_to"):
            lines += [f"The published scale applies to: {applies}.", ""]
    if licence := published.get("licence"):
        lines += [f"Item text reproduced from the published {name} {what} ({licence}).", ""]
    lines += (
        [
            "| Item | Scoring options | Addressed in | Not applicable because |",
            "|---|---|---|---|",
        ]
        if is_scale
        else [
            "| Item | Recommendation | Addressed in | Not applicable because |",
            "|---|---|---|---|",
        ]
    )

    answered = {str(entry.get("id")): entry for entry in answers.get("items", [])}
    ids = [str(item["id"]) for item in items] or sorted(answered)
    text_of = {str(item["id"]): _published_text(item, is_scale) for item in items}

    for identifier in ids:
        entry = answered.get(identifier, {})
        lines.append(
            f"| {_escape_cell(identifier)} | {_escape_cell(text_of.get(identifier, ''))} "
            f"| {_escape_cell(entry.get('where', ''))} "
            f"| {_escape_cell(entry.get('not_applicable', ''))} |"
        )

    extra = sorted(set(answered) - set(ids))
    for identifier in extra:
        entry = answered[identifier]
        lines.append(
            f"| {_escape_cell(identifier)} | *not in the published "
            f"{'scale' if is_scale else 'checklist'}* "
            f"| {_escape_cell(entry.get('where', ''))} "
            f"| {_escape_cell(entry.get('not_applicable', ''))} |"
        )
    return "\n".join(lines) + "\n"


def supplement_for(project: Project, document: Path) -> Path:
    """The supplement to pack with `document`: the one beside it, or else the one the build
    made. A document edited elsewhere, `--document final/manuscript.docx`, has none beside
    it, and its pack went without one."""
    from manuscript_guard.gates.numbers import SUPPLEMENTARY

    beside = document.parent / f"{SUPPLEMENTARY}.docx"
    return beside if beside.exists() else project.path("build") / beside.name


#: The longest pandoc is given to turn the abstract into plain text.
PANDOC_SECONDS = 60


#: What an abstract may hold and still be written as plain text that says what the
#: document says: words, their emphasis, sub- and superscripts as `_script` writes them,
#: quotation marks, and a link that shows its own address. Anything else, a citation, a
#: footnote, maths, code, an image, a table, a link with words of its own, is formatted by
#: the build, and plain text written another way would not be what the document prints.
_PLAIN_INLINES = frozenset({
    "Str", "Space", "SoftBreak", "LineBreak", "Emph", "Strong", "Underline",
    "Superscript", "Subscript", "SmallCaps", "Span", "Quoted",
})  # fmt: skip
#: What a sub- or superscript may hold for the plain writer to print it as one in Unicode.
_SCRIPTABLE = re.compile(r"[0-9+\-\N{MINUS SIGN}=() ]*")
#: What is written as its letters: a subscript of letters alone, a label ("C~max~"), and an
#: ordinal's superscript ("2^nd^"). Any other script the plain writer cannot print as one
#: (`2^k^`, `e^x^`, `10^0.5^`) leaves the abstract out: written flat it would be another
#: number.
_LETTERS = re.compile(r"[A-Za-z]+")
_ORDINAL = re.compile(r"st|nd|rd|th")


def _script(item: dict) -> str:
    """What becomes of a sub- or superscript: "kept" for the plain writer to print as one,
    "flat" as its letters, "refused"."""
    words = item["c"]
    if not all(isinstance(n, dict) and n.get("t") in ("Str", "Space") for n in words):
        return "refused"
    said = _text(words)
    if _SCRIPTABLE.fullmatch(said):
        return "kept"
    label = _LETTERS if item["t"] == "Subscript" else _ORDINAL
    return "flat" if label.fullmatch(said) else "refused"


def _refused_script(node: object) -> bool:
    if isinstance(node, dict):
        if node.get("t") in ("Subscript", "Superscript") and _script(node) == "refused":
            return True
        return any(_refused_script(value) for value in node.values())
    if isinstance(node, list):
        return any(_refused_script(item) for item in node)
    return False
_PLAIN_BLOCKS = frozenset({"Para", "Plain", "Header"})
#: A table or a figure placed by its binding, which `substitute` leaves as it is written, and
#: a ref or num binding the count cannot number.
_DISPLAY = re.compile(r"\{\{\s*(?:table|figure|ref|num)\.")
#: The label that opens an abstract's keywords, as a heading or at a paragraph's start.
_KEYWORDS_HEADING = re.compile(r"\s*key[\s-]?words?\s*:?\s*", re.IGNORECASE)
_KEYWORDS_LABEL = re.compile(r"\s*key[\s-]?words?\s*:", re.IGNORECASE)
_KEYWORDS_ANYWHERE = re.compile(r"\bkey[\s-]?words?\s*:", re.IGNORECASE)
_ABSTRACT_TITLE = re.compile(r"\s*(?:\d+[.)]?\s*)?(?:structured\s+)?abstract\b", re.IGNORECASE)


def _pandoc(*args: str, given: str) -> str:
    import subprocess

    from manuscript_guard.build.document import BuildError, pandoc

    try:
        finished = subprocess.run(
            [pandoc(), *args], input=given, capture_output=True, text=True, encoding="utf-8",
            timeout=PANDOC_SECONDS, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        raise BuildError(f"pandoc gave no plain abstract within {PANDOC_SECONDS} s") from None
    if finished.returncode != 0:
        raise BuildError(f"pandoc could not write the abstract as text:\n{finished.stderr}")
    return finished.stdout


def _text(node: object) -> str:
    """What a piece of pandoc's tree says, as text."""
    if isinstance(node, list):
        return "".join(_text(item) for item in node)
    if not isinstance(node, dict):
        return ""
    kind, content = node.get("t"), node.get("c")
    if kind == "Str":
        return content
    if kind in ("Space", "SoftBreak", "LineBreak"):
        return " "
    if kind in ("RawInline", "RawBlock"):
        return ""
    return _text(content)


def _plain(node: object) -> bool:
    """Whether a piece of the tree is plain text the plain writer prints as the build does.
    An HTML comment, which neither prints, is allowed."""
    if isinstance(node, list):
        return all(_plain(item) for item in node)
    if not isinstance(node, dict) or "t" not in node:
        return True
    kind, content = node["t"], node.get("c")
    if kind in ("RawInline", "RawBlock"):
        return content[0] == "html" and content[1].lstrip().startswith("<!--")
    if kind == "Link":
        attr, words, (target, _title) = content
        return _plain(words) and _text(words).strip() == target.strip()
    if kind == "Header":
        return _plain(content[2])
    if kind == "Span":
        return _plain(content[1])
    if kind == "Quoted":
        return _plain(content[1])
    if kind in _PLAIN_INLINES or kind in _PLAIN_BLOCKS:
        return _plain(content)
    return False


def _unscripted(node: object) -> object:
    """The tree with each label in a subscript and each ordinal's superscript written as its
    own letters: `C~max~` as "Cmax", `2^nd^` as "2nd"."""
    if isinstance(node, dict):
        return {key: _unscripted(value) for key, value in node.items()}
    if not isinstance(node, list):
        return node
    out: list = []
    for item in node:
        if (
            isinstance(item, dict)
            and item.get("t") in ("Subscript", "Superscript")
            and _script(item) == "flat"
        ):
            out.extend(_unscripted(item["c"]))
        else:
            out.append(_unscripted(item))
    return out


def _abstract_blocks(blocks: list) -> list | None:
    """The blocks under the main text's heading "Abstract", up to the next heading of its
    level or above, or None where no heading names it."""
    for at, block in enumerate(blocks):
        if block.get("t") == "Header" and _ABSTRACT_TITLE.match(_text(block["c"][2])):
            level = block["c"][0]
            out = []
            for later in blocks[at + 1 :]:
                if later.get("t") == "Header" and later["c"][0] <= level:
                    break
                out.append(later)
            return out
    return None


def _until_keywords(blocks: list) -> list:
    """The abstract up to its keywords: a heading that names them, or a block that opens
    with their label ("Keywords:", "**Keywords:**")."""
    for at, block in enumerate(blocks):
        said = _text(block["c"][2] if block.get("t") == "Header" else block.get("c"))
        if block.get("t") == "Header" and _KEYWORDS_HEADING.fullmatch(said):
            return blocks[:at]
        if block.get("t") in ("Para", "Plain") and _KEYWORDS_LABEL.match(said):
            return blocks[:at]
    return blocks


def alt_texts(project: Project) -> str | None:
    """Each figure's alternative text, for a submission system that asks for it in a box of
    its own: as the build writes it into the picture, each binding its display. None where
    the manuscript places no figure."""
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.gates.figure_alt import printed_alt, raw_alt
    from manuscript_guard.gates.figure_files import _files_of, _placed

    placed = _placed(project)
    if not placed:
        return None
    namespace = load_namespace(project)[0]
    lines = [
        "# Alternative text",
        "",
        "Each figure's alternative text, for a submission system that asks for it apart. The "
        "document carries the same text in each picture.",
    ]
    for name, supplementary in placed:
        files = ", ".join(path.name for path in _files_of(project.path("figures"), name))
        raw = raw_alt(project, name)
        lines += [
            "",
            f"## {name}{' (supplementary)' if supplementary else ''}",
            "",
            f"Files: {files or 'none rendered'}",
            "",
            printed_alt(raw, namespace) if raw is not None
            else f"None: write it in figures/{name}.guard.yaml under `alt:`.",
        ]
    return "\n".join(lines) + "\n"


_LEFT_OUT = "abstract.txt is not written: "


def abstract_text(project: Project) -> tuple[str | None, str | None]:
    """The abstract for a submission portal's box, and why there is none where there is
    none: every binding filled in with the value the build prints, and no Markdown, as
    pandoc writes plain text, up to its keywords.

    The main text is read whole, as pandoc reads it, so that a footnote defined at its end
    is a footnote. The abstract is written only where everything in it is plain text the
    plain writer prints as the build does; anything else, and a keywords label inside a
    paragraph, leaves it out with the reason, rather than write it otherwise than the
    document says it."""
    import json

    from manuscript_guard.gates.journal import main_text
    from manuscript_guard.gates.revision import displays
    from manuscript_guard.text.placeholders import substitute
    from manuscript_guard.text.sections import split_sections

    text = main_text(project)
    if not any(section.is_abstract for section in split_sections(text)):
        return None, None
    if shutil.which("pandoc") is None:
        return None, _LEFT_OUT + "pandoc is not on PATH"
    filled = substitute(text, displays(project))
    document = json.loads(_pandoc("-f", "markdown", "-t", "json", given=filled))
    blocks = _abstract_blocks(document["blocks"])
    if not blocks:
        return None, None
    blocks = _until_keywords(blocks)
    said = _text(blocks)
    if not _plain(blocks) or _DISPLAY.search(said):
        return None, _LEFT_OUT + (
            "the abstract holds what the build formats and plain text cannot (a citation, a "
            "footnote, maths, code, an image, a table, a figure, a link with words of its "
            "own, or a block other than a paragraph or a heading); copy it from the document"
        )
    if _refused_script(blocks):
        return None, _LEFT_OUT + (
            "the abstract holds a sub- or superscript plain text cannot show (a power such "
            "as 10^-3, a unit such as kg^-1); copy it from the document"
        )
    if _KEYWORDS_ANYWHERE.search(said):
        return None, _LEFT_OUT + (
            "a keywords label stands inside a paragraph of the abstract; put the keywords in "
            "a paragraph of their own"
        )
    document["blocks"] = _unscripted(blocks)
    plain = _pandoc("-f", "json", "-t", "plain", "--wrap=none", given=json.dumps(document))
    return (plain.strip() + "\n", None) if plain.strip() else (None, None)


def assemble_pack(
    project: Project,
    document: Path,
    *,
    checked: bool = True,
    extra: Sequence[tuple[Path, str]] = (),
) -> Pack:
    """Copy or generate every part of the submission into build/submission/.

    `extra` is further documents to pack, each under the name given: at a revision, the
    marked-up copies that show what changed since the round's document.

    `checked=False` records in the manifest that the submission check was overridden. A
    pack assembled with `--skip-checks` was previously byte-indistinguishable from one that
    passed — same files, same checksums, nothing anywhere saying which it was. Six months
    later nobody can tell, and the manifest's whole purpose is to be the thing you can tell
    from.
    """
    from manuscript_guard.gates.numbers import is_supplementary, source_files

    # Before the old pack is taken away: a pandoc that fails here leaves it as it was.
    abstract, left_out = abstract_text(project)
    directory = project.path("build") / "submission"
    # The pack is made afresh, and a document inside it, a co-author's edited copy passed as
    # `--document build/submission/manuscript.docx`, was deleted before it was copied.
    if document.resolve().is_relative_to(directory.resolve()):
        raise SubmissionError(
            f"{document} is inside {directory}, which every pack replaces; move it "
            "elsewhere and pass that path"
        )
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)

    files: list[Path] = []

    if document.exists():
        target = directory / document.name
        shutil.copy2(document, target)
        files.append(target)
    for path, name in extra:
        target = directory / name
        shutil.copy2(path, target)
        files.append(target)

    from manuscript_guard.gates.journal_quotes import journal_checklist

    generated = [
        ("title-page.md", title_page(project)),
        ("credit-statement.md", credit_statement(project)),
        ("declarations.md", declarations(project)),
        # The document a resubmission is judged on as much as the manuscript, and the pack
        # left it out entirely: `respond` wrote it to build/ and nothing collected it, so the
        # one artefact whose claims G13 checks was the one not sent.
        ("response-to-reviewers.md", response_letter(project)),
        # For the portal's abstract box: pasted from the .docx it carries whatever Word
        # and the clipboard make of it; this is the checked numbers and nothing else.
        ("abstract.txt", abstract),
        # The journal's rules no gate checks, for the corresponding author to tick and sign.
        ("journal-checklist.md", journal_checklist(project)),
        # For the portal's box for each figure's alternative text, where it has one.
        ("alt-text.md", alt_texts(project)),
    ]
    for name, text in generated:
        if text is None:
            continue
        target = directory / name
        target.write_text(text, encoding="utf-8", newline="\n")
        files.append(target)

    # The supplement, as its own file. Welded into the manuscript it counted against the
    # word limit and could not be uploaded to the "supplementary material" slot every
    # submission system has.
    #
    # Gated on the project still having supplementary sources, not on the file existing: a
    # `supplementary.docx` left in build/ from a layout the author has since abandoned would
    # otherwise be sent to a journal with nothing in the project to check it against.
    supplement = supplement_for(project, document)
    has_supplement = any(
        is_supplementary(project.path("manuscript"), p)
        for p in source_files(project.path("manuscript"))
    )
    if has_supplement and supplement.exists() and supplement != document:
        target = directory / supplement.name
        shutil.copy2(supplement, target)
        files.append(target)

    checklists = project.root / "reporting"
    if checklists.exists():
        for path in sorted(checklists.glob("*.yaml")):
            # The YAML, because it is the record and it diffs. And a table beside it,
            # because the YAML is what the pack used to offer a journal and a journal cannot
            # read it: an editor asking for a completed STROBE checklist wants to see the
            # items and where each is addressed, not a serialisation of them.
            prefix = "scale" if _is_scale(project, path) else "checklist"
            target = directory / f"{prefix}-{path.name}"
            shutil.copy2(path, target)
            files.append(target)

            table = directory / f"{prefix}-{path.stem}.md"
            table.write_text(checklist_table(project, path), encoding="utf-8", newline="\n")
            files.append(table)

    figures = project.path("figures")
    if figures.exists():
        figure_dir = directory / "figures"
        figure_dir.mkdir(exist_ok=True)
        for path in sorted(figures.iterdir()):
            if path.is_file() and path.suffix.lower() in {".png", ".pdf", ".tif", ".tiff", ".eps"}:
                target = figure_dir / path.name
                shutil.copy2(path, target)
                files.append(target)

    manifest = _write_manifest(project, directory, files, checked=checked)
    notes = (left_out,) if left_out else ()
    return Pack(directory=directory, files=tuple(files), manifest=manifest, notes=notes)


#: The longest `git` is waited for. A repository on a network drive, or one with a file
#: system monitor that hangs, would otherwise hold the pack up for good.
GIT_SECONDS = 30


def _git(root: Path, *args: str) -> str | None:
    """`git` in the project, or None where it is not a repository or git did not answer.
    The file system monitor is turned off for the call: started by it, it can outlive it."""
    try:
        done = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            capture_output=True,
            # git writes UTF-8 whatever the locale: a path in a message, read as cp932 or
            # cp1252, would otherwise raise.
            encoding="utf-8",
            errors="replace",
            timeout=GIT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _commit(project: Project) -> dict[str, str]:
    """The commit the project was at, and whether anything in its folder differs from that
    commit: a changed file, or one git has not been told to ignore and has not been given.
    The build folder is left out, since the pack being written is in it."""
    root = project.root
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return {"commit": "none: not a git repository, one with no commit yet, or git could not "
                "be run", "tree": "unknown"}
    build = project.path("build")
    outside = [] if not build.is_relative_to(root) else [
        f":(exclude){build.relative_to(root).as_posix()}"
    ]
    # Each file of a folder git has not been given, not the folder as one (round 1 of #250).
    status = _git(root, "status", "--porcelain", "--untracked-files=all", "--", ".", *outside)
    if status is None:
        return {"commit": head.strip(), "tree": "unknown: git could not say"}
    changed = len([line for line in status.splitlines() if line.strip()])
    tree = "clean" if not changed else f"{changed} file(s) changed or not committed"
    return {"commit": head.strip(), "tree": tree}


def _journal_profile(project: Project) -> Path | None:
    from manuscript_guard.gates.journal import profile_path

    slug = project.target_journal
    return profile_path(project, slug) if slug else None


def _checklist_profile(project: Project, name: str) -> Path | None:
    from manuscript_guard.gates.reporting import checklist_path

    return checklist_path(project, name)


def _retrieved_on(path: Path | None) -> str:
    """When the guidelines in a profile were read from their source, as the profile says."""
    if path is None:
        return "no profile"
    try:
        document = read_structured(path)
    except ContractError:
        return "unreadable"
    found = document.get("retrieved_on") if isinstance(document, dict) else None
    return str(found) if found else "not stated"


def _write_manifest(
    project: Project, directory: Path, files: list[Path], *, checked: bool = True
) -> Path:
    from manuscript_guard.gates.review import manuscript_digest, overrides

    entries = []
    for path in files:
        data = path.read_bytes()
        entries.append(
            {
                "file": str(path.relative_to(directory)).replace("\\", "/"),
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    from manuscript_guard.gates.revision import rounds

    # Which submission this is. A pack for a revision and a pack for a first submission were
    # indistinguishable, and "which version did the journal get" is a question about a round
    # as much as about a checksum.
    revisions = rounds(project)
    document = {
        "schema": "manuscript-guard/submission/1",
        "title": project.paper.get("title", ""),
        "journal": project.target_journal or "(none chosen)",
        "submission": (
            f"revision {max(n for n, _p in revisions)}" if revisions else "first submission"
        ),
        "assembled_on": date.today().isoformat(),
        "checks": (
            "passed"
            if checked
            else "SKIPPED — assembled with --skip-checks while the submission check "
            "was failing. Do not send this without re-running `manuscript-guard "
            "check --submission`."
        ),
        # What made it, so that a fix to the tool can say which packs to check again, and
        # a pack can be traced to the commit, the guidelines and the decisions behind it.
        "checked_with": f"manuscript-guard {__version__}",
        **_commit(project),
        "journal_profile_retrieved_on": _retrieved_on(_journal_profile(project)),
        "checklists": [
            {"guideline": name, "retrieved_on": _retrieved_on(_checklist_profile(project, name))}
            for name in project.reporting_guidelines
        ],
        "overrides": overrides(project),
        "manuscript_sha256": manuscript_digest(project),
        "files": entries,
    }
    path = directory / "MANIFEST.yaml"
    header = (
        "# What was sent, and exactly which bytes. Six months from now the only reliable\n"
        "# answer to \"which version did the journal get\" is a list of checksums.\n\n"
    )
    path.write_text(
        header + yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return path
