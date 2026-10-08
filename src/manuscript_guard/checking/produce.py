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
from manuscript_guard.text.placeholders import PLACEHOLDER

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

#: A binding, as the manuscript writes it. The toolkit's own pattern, from
#: `text/placeholders.py`: it accepts `{{ lit.x }}` with spaces, which the renderer resolves and
#: an exact-string search here did not, so that value's sentences were neither shown nor digested.
BINDING = PLACEHOLDER
#: A citation as the manuscript writes it, bracketed or narrative.
CITEKEY = re.compile(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)")
#: A stop, then a space, then something that can start a sentence. The opening bracket matters:
#: a numbered-citation style writes "Okada et al. [@key]." and the stop in "al." is not an end.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")
#: Words that end in a stop and do not end a sentence. Lower-cased, without their stops. Short on
#: purpose: each one is a word a manuscript really writes before a citation or a figure.
NOT_AN_END = frozenset({
    "al", "e.g", "i.e", "cf", "ca", "approx", "ibid", "viz", "vs", "etc", "fig", "figs",
    "tab", "tabs", "eq", "eqs", "ref", "refs", "no", "nos", "vol", "vols", "pp", "ed", "eds",
    "st", "dr", "prof", "mr", "mrs", "ms", "sr", "jr", "inc", "ltd", "dept", "univ",
})
#: The last word before a stop, with any stops of its own: "al." of "et al.", "e.g." whole.
LAST_WORD = re.compile(r"([A-Za-z][A-Za-z.]*)\.$")

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


def _ends_a_sentence(before: str) -> bool:
    """Whether the stop at the end of `before` ends a sentence.

    It does not after "et al.", "e.g." or "Fig.", nor after a single initial — and the split that
    matters most is exactly there, because a numbered-citation style writes "described by Okada
    et al. [@key]." and cutting it leaves one item reading "[@key]." with no claim in it.
    """
    found = LAST_WORD.search(before)
    if found is None:
        return True
    word = found.group(1).rstrip(".").lower()
    return not (word in NOT_AN_END or len(word) == 1)


def _split(flat: str) -> list[str]:
    """One paragraph's sentences.

    Two rules beyond the stop: a stop after an abbreviation is not an end, and a piece carrying
    no word of its own belongs to the piece before it — so a citation left alone by a split this
    reader did not foresee is put back rather than shown to a co-author as a claim to judge.
    """
    pieces: list[str] = []
    at = 0
    for found in SENTENCE_END.finditer(flat):
        if not _ends_a_sentence(flat[:found.start()]):
            continue
        pieces.append(flat[at : found.start()])
        at = found.end()
    pieces.append(flat[at:])

    joined: list[str] = []
    for piece in (p.strip() for p in pieces):
        if not piece:
            continue
        if joined and not any(ch.isalpha() for ch in CITEKEY.sub("", piece)):
            joined[-1] = f"{joined[-1]} {piece}"
            continue
        joined.append(piece)
    return joined


def _sentences_of(text: str) -> list[tuple[int, str]]:
    """Each sentence of each paragraph, with the line the **paragraph** starts on.

    The paragraph's line, not the sentence's: it is how a reader finds the passage, and nothing
    is keyed on it.
    """
    out: list[tuple[int, str]] = []
    line = 1
    for paragraph in text.split("\n\n"):
        for sentence in _split(" ".join(paragraph.split())):
            out.append((line, sentence))
        line += paragraph.count("\n") + 2
    return out


def _without_bindings(sentence: str) -> str:
    """A sentence as a reader sees it: a binding stands for the value, which a co-author checking
    the claim does not need resolved and could not check from here."""
    return BINDING.sub(lambda found: f"[{found.group('key').split('.')[-1]}]", sentence)


def _uses_binding(text: str, key: str) -> bool:
    """Whether this text writes that binding, however it spaces it."""
    return any(
        f"{found.group('ns')}.{found.group('key')}" == key for found in BINDING.finditer(text)
    )


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
    """Every manuscript file, split into sentences once, with its comments blanked.

    Once, because every value's uses are looked for in these: splitting inside that loop is a
    whole manuscript re-read per key, and a real paper has a hundred or more of them.

    Blanked, with `text/masking.py`'s own function, because a sentence a draft has commented out
    is not a sentence of the paper — and a co-author sent "Dropped from this draft: the risk
    doubles in adults over 65 [@key]" as a claim to check has been asked about nothing. Blanking
    keeps every offset and line ending, so the lines a reader is pointed at stay right.
    """
    from manuscript_guard.gates.numbers import source_files
    from manuscript_guard.text.masking import blank_comments

    documents: list[Document] = []
    for path in source_files(project.path("manuscript")):
        body = blank_comments(path.read_text(encoding="utf-8", errors="replace"))
        documents.append((path, body, _sentences_of(body)))
    return documents


def _uses_of(key: str, documents: list[Document]) -> list[dict]:
    """Where the manuscript uses one binding, as sentences a reader can judge."""
    found: list[dict] = []
    for path, text, sentences in documents:
        if not _uses_binding(text, key):
            continue
        for line, sentence in sentences:
            if _uses_binding(sentence, key):
                found.append(
                    {
                        "text": _without_bindings(sentence),
                        "section": path.name,
                        "line": line,
                    }
                )
    return found[:8]


#: What a CSL record calls the fields this page shows, and what this module calls them. pandoc
#: writes CSL JSON, which is the same information under other names.
FROM_CSL = (
    ("type", "type"),
    ("title", "title"),
    ("container-title", "journaltitle"),
    ("volume", "volume"),
    ("issue", "number"),
    ("page", "pages"),
    ("DOI", "doi"),
    ("URL", "url"),
)


def _name_of(person: dict) -> str:
    """One CSL name as a bibliography prints it: "van der Eijk, Yvette"."""
    if person.get("literal"):
        return str(person["literal"])
    family = " ".join(
        part for part in (person.get("non-dropping-particle"), person.get("family")) if part
    )
    given = " ".join(
        part for part in (person.get("given"), person.get("suffix")) if part
    )
    return f"{family}, {given}".strip().strip(",") if given else family


def _date_of(issued: dict) -> str:
    """A CSL date as the year, or the year and month, or the whole of it."""
    if issued.get("literal"):
        return str(issued["literal"])
    parts = (issued.get("date-parts") or [[]])[0]
    return "-".join(f"{int(part):02d}" if n else str(int(part)) for n, part in enumerate(parts))


def _records_from_pandoc(path: Path) -> dict[str, dict[str, str]] | None:
    """Every entry, parsed by pandoc, or `None` where pandoc cannot be used.

    `pandoc -f biblatex -t csljson` understands the format properly: `M{\"u}ller` comes back as
    Müller, a biblatex extended name as its parts, a `@string` macro expanded, and an `@` inside
    a value as what it is. The reader below this does none of that and says so.
    """
    import json
    import shutil
    import subprocess

    found = shutil.which("pandoc")
    if not found:
        return None
    try:
        done = subprocess.run(
            [found, "-f", "biblatex", "-t", "csljson", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not (done.stdout or "").strip():
        # A bibliography pandoc refuses is read by the small reader instead, which shows the
        # fields as written rather than nothing at all.
        return None
    try:
        entries = json.loads(done.stdout)
    except ValueError:
        return None
    if not isinstance(entries, list):
        return None

    records: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        fields: dict[str, str] = {}
        for csl, ours in FROM_CSL:
            value = entry.get(csl)
            if isinstance(value, str) and value.strip():
                fields[ours] = " ".join(value.split())
            elif isinstance(value, (int, float)):
                fields[ours] = str(value)
        for csl, ours in (("author", "author"), ("editor", "editor")):
            people = [
                _name_of(person) for person in entry.get(csl) or [] if isinstance(person, dict)
            ]
            if any(people):
                fields[ours] = " and ".join(name for name in people if name)
        issued = entry.get("issued")
        if isinstance(issued, dict):
            said = _date_of(issued)
            if said:
                fields["date"] = said
        records[str(entry["id"])] = fields
    return records


def _bib_records(project) -> dict[str, dict[str, str]]:
    """Every entry of `references.bib`, as fields, by pandoc where there is one.

    Two readers, and the better one is not always there. `checker build` must work in a project
    that has no pandoc, so `_records_read_here` stays; where pandoc is on the path it parses
    instead, because what it reads is the format and what the small reader reads is the shape
    that format usually takes.

    **The two do not agree in every detail, and pandoc's reading is the one to prefer**: it gives
    a page range as `425-440` where the small reader keeps the file's en dash, and a title in the
    sentence case biblatex stores rather than the title case the file types. Both identify the
    same work, which is what a co-author is asked about, and the printed bibliography is pandoc's
    reading of the same file under a style.
    """
    path = project.path("literature") / "references.bib"
    if not path.is_file():
        return {}
    parsed = _records_from_pandoc(path)
    if parsed is not None:
        return parsed
    return _records_read_here(path)


def _records_read_here(path: Path) -> dict[str, dict[str, str]]:
    """Every entry of a `.bib` file, read without pandoc: the fields as they are written.

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

    What it does not do, where pandoc does: decode a TeX accent, expand a `@string` macro, join
    a `#` concatenation, or read a biblatex extended name into its parts. DESIGN.md's Known gaps
    carries that.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    records: dict[str, dict[str, str]] = {}
    # Anchored at a line start, so an `@` inside a value is not the start of an entry, and
    # `@comment` is skipped: both were entries of their own before.
    for start in re.finditer(r"^@(\w+)\s*\{\s*([^,\s]+)\s*,", text, re.MULTILINE):
        kind, key = start.group(1), start.group(2)
        if kind.lower() in {"comment", "preamble", "string"}:
            continue
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
    seen: set[str] = set()
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
                    # `.rstrip(".,;:")` as `zotero/citations.py` does it: a narrative citation
                    # that ends a sentence is written "as @key." and the stop is not part of the
                    # key, so without this the sentence was on no item at all.
                    found.group(1).rstrip(".,;:")
                    for found in CITEKEY.finditer(sentence)
                    if found.group(1).rstrip(".,;:") in known
                }
            )
            if not keys:
                continue
            if not any(ch.isalpha() for ch in CITEKEY.sub("", sentence)):
                # A paragraph that is nothing but a citation — the splitter joins a claimless
                # piece to the one before it, but a whole paragraph has nothing before it. There
                # is no claim in it to judge, so nobody is asked about it.
                continue
            identifier = _identifier("claim", str(path.name), sentence)
            if identifier in seen:
                # One sentence written twice in a file is one claim, and asking it twice would
                # also give two items one id, which the schema refuses for the whole build.
                continue
            seen.add(identifier)
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
                    # Keyed on the file and the sentence as written, and on nothing else.
                    # The line was in it, so adding one paragraph to the Introduction threw away
                    # every claim answer below — the case DESIGN.md said had been removed, which
                    # had been removed from the digest and left here. The sentence is taken whole
                    # rather than cut at 80 characters, so two long sentences with the same
                    # opening are two items.
                    "id": identifier,
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
                # Name, identifier and address: two authors of one name would otherwise share an
                # id, and the schema refuses the whole build for it.
                "id": _identifier(
                    "author",
                    name,
                    str(person.get("orcid") or ""),
                    str(person.get("email") or ""),
                ),
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


def produce(project) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Everything the toolkit can offer a co-author for this project, and what it could not read.

    The second half matters: one ledger entry that fails its schema takes **every** literature
    value out of the round, because the contract reads the file as a whole. That used to happen
    in silence — a page with two items instead of a hundred and thirty, and three ordinary lines
    of output. The warnings come back with the document now, and `build` prints them.
    """
    from manuscript_guard.contracts.literature import load_literature

    literature, report = load_literature(project.path("literature"))
    unread = tuple(f"{finding.code}: {finding.message}" for finding in report.failures)
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
    }, unread


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
