"""The items a project offers a co-author, found by the toolkit itself.

Four of them need nothing a project has to write:

* **every value quoted from the literature** — the ledger holds the value, the quote it came
  from, the source and the locator, and the manuscript says where it is used;
* **every sentence that cites something** — the sentence is the claim, and whether the cited
  paper supports it is the judgement no gate can make;
* **every reference** — the record as `references.bib` holds it, and whether a copy is stored;
* **every author** — their name, degrees, identifier, affiliations and roles.

A fifth kind, a number transcribed from a table in a source document, is not here and cannot be:
only the project knows that this value came from row 14 of that workbook, which is what its own
tracing records. A project contributes those by writing `checks/items.json`, and they are merged
with these — its groups first, because a project that went to the trouble knows what it wants
asked first.

Nothing here renders a picture. A page image needs a PDF renderer, which this toolkit does not
depend on and will not start depending on for this; what a checker reads is the quote, and the
quote is text the ledger already holds. A project that can render a page of a PDF puts those
items in its own file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from manuscript_guard.checking.items import SCHEMA

#: What is asked of each kind, in words needing no instructions.
GROUPS = (
    {
        "id": "literature",
        "title": "Numbers from the literature",
        "ask": "Does the quoted passage say this number?",
        "seconds": 25,
    },
    {
        "id": "claim",
        "title": "Cited statements",
        "ask": "Does the cited source say what this sentence says?",
        "seconds": 40,
    },
    {
        "id": "reference",
        "title": "References",
        "ask": "Is this reference right, and does it exist?",
        "seconds": 15,
    },
    {
        "id": "author",
        "title": "Authors",
        "ask": "Is this author's name, affiliation and role right?",
        "seconds": 20,
    },
)

#: A binding, as the manuscript writes it.
BINDING = re.compile(r"\{\{\s*(?P<key>[a-z][a-z0-9_.]*)\s*\}\}")
#: A citation as the manuscript writes it, bracketed or narrative.
CITEKEY = re.compile(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)")
#: One sentence, ended by a stop and a space. Good enough to show a reader the claim in context;
#: nothing here depends on the split being exactly right.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")

#: A reference's fields as a reader wants them, each under every name a .bib file calls it.
#: Better BibTeX exports biblatex (`journaltitle`, `date`) and a hand-kept file is often plain
#: BibTeX (`journal`, `year`); a co-author shown a reference with no journal and no year cannot
#: tell whether it is right, which is the whole question being put to them.
REFERENCE_FIELDS = (
    ("Kind of record", ("type",)),
    ("Authors", ("author", "editor")),
    ("Title", ("title",)),
    ("Journal", ("journaltitle", "journal", "booktitle", "institution", "organization")),
    ("Date", ("date", "year")),
    ("Volume", ("volume",)),
    ("Issue", ("number", "issue")),
    ("Pages", ("pages",)),
    ("DOI", ("doi",)),
    ("URL", ("url",)),
)
#: The shorter form shown beside a cited sentence: enough to recognise the paper.
CITED_FIELDS = (
    ("Reference", ("title",)),
    ("Authors", ("author", "editor")),
    ("Journal", ("journaltitle", "journal", "booktitle")),
    ("Date", ("date", "year")),
    ("DOI", ("doi",)),
)


#: The TeX a .bib file writes that a reader should not be shown. Deliberately small: these are
#: what a real bibliography holds in the fields a co-author reads — a page range's dash, and the
#: escapes a journal name needs. Anything more belongs to a .bib parser, which this is not.
TEX_IN_FIELDS = (
    ("---", "—"),
    ("--", "–"),
    ("~", " "),
    ("\\&", "&"),
    ("\\%", "%"),
    ("\\_", "_"),
    ("\\$", "$"),
    ("\\#", "#"),
)
#: Fields left exactly as written: a dash turned into an en dash would break the link, and a few
#: DOIs really do carry a double hyphen.
VERBATIM_FIELDS = frozenset({"doi", "url", "eprint"})


def _readable(name: str, value: str) -> str:
    if name in VERBATIM_FIELDS:
        return value
    for tex, plain in TEX_IN_FIELDS:
        value = value.replace(tex, plain)
    return " ".join(value.split())


def _field(record: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        if record.get(name):
            return _readable(name, record[name])
    return ""


def _rows_for(record: dict[str, str], fields) -> list[list[str]]:
    rows = []
    for label, names in fields:
        found = _field(record, names)
        if found:
            rows.append([label, found])
    return rows


def _short(text: str, limit: int = 110) -> str:
    """A title for the list down the side, said to be cut where it is cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1].rstrip() + "…"


def _identifier(*parts: str) -> str:
    """Stable across runs and across machines, so an answer keeps meaning."""
    import hashlib

    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _sentences_of(text: str) -> list[tuple[int, str]]:
    """Each sentence with the line it starts on."""
    out: list[tuple[int, str]] = []
    line = 1
    for paragraph in text.split("\n\n"):
        start = line
        flat = " ".join(paragraph.split())
        if flat:
            offset = start
            for sentence in SENTENCE_END.split(flat):
                if sentence.strip():
                    out.append((offset, sentence.strip()))
        line += paragraph.count("\n") + 2
    return out


def _without_bindings(sentence: str) -> str:
    """A sentence as a reader sees it: a binding stands for the value, which a co-author checking
    the claim does not need resolved and could not check from here."""
    return BINDING.sub(lambda found: f"[{found.group('key').split('.')[-1]}]", sentence)


def _plain(fact: Any) -> str:
    """A field as a reader should see it, whatever shape the file holds it in.

    `degrees: [PharmD, MSc]` is a list in the file and "PharmD, MSc" to the person whose degrees
    they are, and `corresponding: true` is "yes". A co-author shown `['PharmD', 'MSc']` is being
    asked to check the project's data structures, which is not their job.
    """
    if isinstance(fact, bool):
        return "yes" if fact else "no"
    if isinstance(fact, (list, tuple)):
        return ", ".join(_plain(part) for part in fact)
    return str(fact)


#: One manuscript file: its path, its text, and its sentences with the line each starts on.
Document = tuple[Path, str, list[tuple[int, str]]]


def _manuscript(project) -> list[Document]:
    """Every manuscript file, split into sentences once.

    Once, because every value's uses are looked for in these: splitting inside that loop is a
    whole manuscript re-read per key, and a real paper has a hundred or more of them.
    """
    from manuscript_guard.gates.numbers import source_files

    documents: list[Document] = []
    for path in source_files(project.path("manuscript")):
        body = path.read_text(encoding="utf-8", errors="replace")
        documents.append((path, body, _sentences_of(body)))
    return documents


def _uses_of(key: str, documents: list[Document]) -> list[dict]:
    """Where the manuscript uses one binding, as sentences a reader can judge."""
    wanted = "{{" + key + "}}"
    found: list[dict] = []
    for path, text, sentences in documents:
        if wanted not in text:
            continue
        for line, sentence in sentences:
            if wanted in sentence:
                found.append(
                    {
                        "text": _without_bindings(sentence),
                        "section": path.name,
                        "line": line,
                    }
                )
    return found[:8]


def _bib_records(project) -> dict[str, dict[str, str]]:
    """Every entry of `references.bib`, as fields.

    A small reader rather than a dependency: a .bib entry is `@type{key, field = {value},}`, and
    what a co-author checks is the fields as they are written. Nested braces are counted, so a
    title holding `{SANRA}` comes out whole.

    The entry is cut at the commas that are **outside** every brace and quote, and only then is
    each piece split at its first `=`. Looking for `name =` anywhere instead found one inside a
    value and made a field of it: on the bibliography this was tried against, four entries in
    fifty-eight gained a field no line of the file declares — `tstat` out of a URL's query
    string, `n` out of "(n = 866)" in an abstract, `given` and `family` out of a biblatex
    extended name — and a URL carrying `&title=` overwrote the entry's real title, which a
    co-author would have been shown as the thing to check.
    """
    path = project.path("literature") / "references.bib"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    records: dict[str, dict[str, str]] = {}
    for start in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        kind, key = start.group(1), start.group(2)
        depth, index = 1, start.end()
        while index < len(text) and depth:
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            index += 1
        fields: dict[str, str] = {"type": kind}
        for piece in _entry_pieces(text[start.end() : index - 1]):
            name, sign, value = piece.partition("=")
            name = name.strip().lower()
            if not sign or not name.isidentifier():
                continue
            value = value.strip()
            if (value[:1], value[-1:]) in {("{", "}"), ('"', '"')}:
                value = value[1:-1]
            fields[name] = " ".join(value.replace("{", "").replace("}", "").split())
        records[key] = fields
    return records


def _entry_pieces(body: str) -> list[str]:
    """One .bib entry's body, cut at the commas outside every brace and quote."""
    pieces: list[str] = []
    current: list[str] = []
    depth = 0
    quoted = False
    for char in body:
        if char == '"' and depth == 0:
            quoted = not quoted
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0 and not quoted:
            pieces.append("".join(current))
            current = []
            continue
        current.append(char)
    pieces.append("".join(current))
    return pieces


def _literature_items(project, literature, documents) -> list[dict]:
    items = []
    for key, value in sorted(literature.values.items()):
        detail = value.detail or {}
        quote = str(detail.get("quote") or "")
        shown = str(value.display or value.value)
        facts = [["Value as printed", shown]]
        wanted = (
            ("Unit", "unit"),
            ("Cited", "citekey"),
            ("Source", "source"),
            ("Where in the source", "locator"),
        )
        for label, field in wanted:
            if detail.get(field):
                facts.append([label, _plain(detail[field])])
        evidence: list[dict] = []
        if quote:
            evidence.append(
                {
                    "kind": "quote",
                    "caption": f"{detail.get('citekey', 'the source')}"
                    + (f", {detail['locator']}" if detail.get("locator") else ""),
                    "text": quote,
                    "mark": [shown],
                    "note": "the sentence this value was taken from, as the source prints it",
                }
            )
        if detail.get("source_file"):
            evidence.append(
                {
                    "kind": "facts",
                    "caption": "the stored copy",
                    "rows": [["File", str(detail["source_file"])],
                             ["Read at", str(detail.get("depth") or "")]],
                }
            )
        if detail.get("statement"):
            # An attested value has no quote and no stored file, by definition: it rests on a
            # person having read something the toolkit could not keep. That person's statement
            # is what there is to check, and a co-author should be told it is all there is.
            rows = [["Attested by", _plain(detail.get("attested_by") or "")]]
            if detail.get("attested_on"):
                rows.append(["Attested on", _plain(detail["attested_on"])])
            evidence.append(
                {
                    "kind": "facts",
                    "caption": "no stored source — the author's attestation",
                    "rows": rows,
                    "note": _plain(detail["statement"]),
                }
            )
        items.append(
            {
                "id": _identifier("lit", key),
                "group": "literature",
                "title": f"{shown} — lit.{key}",
                "facts": facts,
                "sentences": _uses_of(f"lit.{key}", documents),
                "evidence": evidence or [{"kind": "none"}],
            }
        )
    return items


def _claim_items(project, literature, documents) -> list[dict]:
    from manuscript_guard.zotero import find_citations

    quoted: dict[str, list[dict]] = {}
    for value in literature.values.values():
        detail = value.detail or {}
        if detail.get("citekey") and detail.get("quote"):
            quoted.setdefault(str(detail["citekey"]), []).append(
                {"quote": str(detail["quote"]), "locator": str(detail.get("locator") or ""),
                 "value": str(value.display or value.value)}
            )

    records = _bib_records(project)
    items = []
    for path, text, sentences in documents:
        # The toolkit's own reader says whether this file cites anything at all, and which keys
        # it knows; which of them a given sentence carries is read from the sentence, because a
        # citation group can span lines and a line can hold two sentences.
        known = {use.citekey for use in find_citations(text, path)}
        if not known:
            continue
        for line, sentence in sentences:
            keys = sorted(
                {
                    found.group(1)
                    for found in CITEKEY.finditer(sentence)
                    if found.group(1) in known
                }
            )
            if not keys:
                continue
            facts = [["Cites", ", ".join("@" + k for k in keys)]]
            evidence: list[dict] = []
            for key in keys:
                record = records.get(key, {})
                rows = _rows_for(record, CITED_FIELDS)
                if rows:
                    evidence.append({"kind": "facts", "caption": f"@{key}", "rows": rows})
                for held in quoted.get(key, [])[:4]:
                    evidence.append(
                        {
                            "kind": "quote",
                            "caption": f"@{key}, quoted in the ledger"
                            + (f": {held['locator']}" if held["locator"] else ""),
                            "text": held["quote"],
                            "note": f"for the value {held['value']}",
                        }
                    )
            items.append(
                {
                    # The identifier is keyed on the sentence as written, so a binding's value
                    # changing does not invalidate an answer about what the sentence claims.
                    "id": _identifier("claim", str(path.name), str(line), sentence[:80]),
                    "group": "claim",
                    "title": _short(_without_bindings(sentence)),
                    "facts": facts,
                    "sentences": [
                        {
                            "text": _without_bindings(sentence),
                            "section": path.name,
                            "line": line,
                        }
                    ],
                    "evidence": evidence or [{"kind": "none"}],
                }
            )
    return items


def _reference_items(project, literature) -> list[dict]:
    cited = {
        str((value.detail or {}).get("citekey"))
        for value in literature.values.values()
        if (value.detail or {}).get("citekey")
    }
    items = []
    for key, record in sorted(_bib_records(project).items()):
        facts = _rows_for(record, REFERENCE_FIELDS)
        stored = sorted(
            path.name
            for path in (project.path("literature") / "sources").glob(f"{key}.*")
        ) if (project.path("literature") / "sources").is_dir() else []
        rows = [["Stored copy", ", ".join(stored) or "none in the project"]]
        if key in cited:
            rows.append(["Quoted from", "yes — a value in the ledger comes from this source"])
        items.append(
            {
                "id": _identifier("ref", key),
                "group": "reference",
                "title": _short(f"{key}: {_field(record, ('title',))}"),
                "facts": facts,
                "evidence": [{"kind": "facts", "caption": "what the project holds", "rows": rows}],
            }
        )
    return items


def _author_items(project) -> list[dict]:
    document = project.authors or {}
    people = document.get("authors") or []
    # An author's affiliations are ids in the file, and the text is held once at the top. The
    # person asked to check their own affiliation needs the text, not the id.
    texts = {
        str(place.get("id")): str(place.get("text") or "")
        for place in document.get("affiliations") or []
    }
    items = []
    for person in people:
        name = " ".join(str(person.get(part, "")) for part in ("given", "family")).strip()
        facts = []
        for label, field in (("Degrees", "degrees"), ("ORCID", "orcid"), ("Email", "email"),
                             ("Corresponding author", "corresponding")):
            if person.get(field):
                facts.append([label, _plain(person[field])])
        for which in person.get("affiliations") or []:
            facts.append(["Affiliation", texts.get(str(which)) or _plain(which)])
        if person.get("credit"):
            facts.append(["CRediT roles", _plain(person["credit"])])
        if person.get("competing_interests"):
            facts.append(["Competing interests", _plain(person["competing_interests"])])
        items.append(
            {
                "id": _identifier("author", name),
                "group": "author",
                "title": name or "an author with no name",
                "facts": facts,
                "evidence": [
                    {
                        "kind": "none",
                        "caption": "the project's record of this author",
                        "note": "Nothing is stored to check this against: it is what the "
                        "submission will say about this person, and the person is the source. "
                        "Say what is wrong in the box.",
                    }
                ],
            }
        )
    return items


def produce(project) -> dict[str, Any]:
    """Everything the toolkit can offer a co-author for this project, as an items document."""
    from manuscript_guard.contracts.literature import load_literature

    literature, _report = load_literature(project.path("literature"))
    documents = _manuscript(project)

    items = (
        _literature_items(project, literature, documents)
        + _claim_items(project, literature, documents)
        + _reference_items(project, literature)
        + _author_items(project)
    )
    return {
        "schema": SCHEMA,
        "title": str(project.paper.get("short_title") or project.paper.get("title") or ""),
        "groups": [dict(group) for group in GROUPS],
        "items": items,
    }


def merge(
    produced: dict[str, Any], contributed: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, int]]:
    """A project's own items in front of the toolkit's, and its groups first.

    Returns the merged document and, per group, how many of the toolkit's items were left out
    because the project supplies that group itself.

    **A group the project fills is the project's, whole.** Not item by item: the two producers
    make their ids from different inputs, so the same value gets two ids and a co-author is asked
    twice. The project that wrote its own literature items traced each to a row of a source
    document, which is more than the toolkit can see, and it did not do that for the toolkit's
    version to be asked beside it. So a group with one contributed item in it takes none of the
    toolkit's, and the build says how many it left out, because that is a thing worth noticing
    rather than a thing to discover from a co-author.
    """
    offered = contributed or {}
    groups = list(offered.get("groups") or [])
    known = {group["id"] for group in groups}
    groups += [group for group in produced["groups"] if group["id"] not in known]

    items = list(offered.get("items") or [])
    taken = {item["id"] for item in items}
    owned = {item["group"] for item in items}
    # A group is how the page asks its question, so an item in a group nothing declares has no
    # question to put and is not sent. This runs whether or not a project contributed anything:
    # a producer with a group it forgot to declare should fail the same way in both.
    kinds = {group["id"] for group in groups}
    skipped: dict[str, int] = {}
    for item in produced["items"]:
        if item["id"] in taken or item["group"] not in kinds:
            continue
        if item["group"] in owned:
            skipped[item["group"]] = skipped.get(item["group"], 0) + 1
            continue
        items.append(item)
    document = {
        "schema": SCHEMA,
        "title": offered.get("title") or produced.get("title") or "",
        "groups": groups,
        "items": items,
    }
    return document, skipped
