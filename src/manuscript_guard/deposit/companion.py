"""ro-crate-preview.html: the package's companion page, one file a reader opens in a
browser, made from the records alone, and its copy index.html for a site.

It is self-contained: its style is in it, its pictures are data URIs, and the one script it
holds is the Schema.org description of the paper (`application/ld+json`), which no browser
runs. Its six sections are each made from what the project records, with no word written for
it by a model:

1. Overview and citation: the title, the authors, the abstract, how to cite the package, the
   history its records date, and the digests of its results and its files.
2. Key findings and the evidence map: the abstract's own sentences that carry a binding,
   word for word with the values in; each value, table and figure the manuscript binds, where,
   and the results file and script it comes from; each cited sentence whose supporting
   passage a person judged, with where in the work the passage is, never its words.
3. Figures, tables and models: a figure where its record of drawing matches it, its caption,
   its alternative text and where its review stands, naming no reviewer; each bound table;
   each model's card, as `models` prints it.
4. Methods and reproducibility: how to run each script again, what it ran with, the
   inputs, the Methods' claims and the steps they describe, and the last run of `verify`.
5. Limitations: the manuscript's section on them, the plan's Deviations as written, what G12
   says, and what no gate checks.
6. Co-author verification: who checked what, by author, and each author's approval.

No name is shown but the authors'. Of a results file the package withholds nothing is
shown, and a small count the data custodian has not signed off stops the package.

The bytes are a function of the records and of pandoc's version, which MANIFEST.yaml names:
no clock, no path of the computer and no version of this tool is written, and every list is
in the order the records give or sorted.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import quote

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results

from .plan import Entry, Input, PackageError, settings

COMPANION = "ro-crate-preview.html"
SITE = "index.html"
#: The files the digest of the package leaves out: this page and its copy, the crate and what
#: it does not state, which are made beside it, and the two written after every other.
UNDIGESTED = (COMPANION, SITE, "ro-crate-metadata.json", "RELATIONS.md", "MANIFEST.yaml",
              "SHA256SUMS")  # fmt: skip
WITHHELD = "[withheld]"
#: What stands in the page for a name it does not show.
A_READER = "a reader"


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


@dataclass
class Prose:
    """The Markdown the page shows, each piece a token in the page until pandoc has written
    them all (`prose.html_fragments`)."""

    texts: list[str] = field(default_factory=list)
    inline: list[bool] = field(default_factory=list)

    def add(self, markdown: str, *, inline: bool = False) -> str:
        # The character that marks a piece's place, and that a masked view may hold.
        self.texts.append(markdown.replace("\x00", ""))
        self.inline.append(inline)
        return f"\x00{len(self.texts) - 1}\x00"

    def fill(self, page: str) -> str:
        from .prose import ProseError, html_fragments
        from .prose import inline as unwrapped

        try:
            written = html_fragments(self.texts)
        except ProseError as exc:
            raise PackageError(f"--companion: {exc}") from None
        done = [unwrapped(text) if flat else text
                for text, flat in zip(written, self.inline, strict=True)]  # fmt: skip
        return re.sub("\x00(\\d+)\x00", lambda found: done[int(found[1])], page)


@dataclass
class Page:
    """What every section reads, gathered once."""

    project: Project
    results: Results
    entries: list[Entry]
    inputs: list[Input]
    prose: Prose
    #: The results files the package holds, from the root: of no other is anything shown.
    shown: frozenset[str]
    #: What each binding prints, a value of a results file the package withholds as WITHHELD.
    displays: dict[str, str]
    #: Each binding of a value, a table or a figure, as BOUND.md lists them (`bound_rows`).
    rows: list = field(default_factory=list)

    def rel(self, path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return path.relative_to(self.project.root).as_posix()
        except ValueError:
            return path.name

    def held(self, path: Path | None) -> bool:
        return self.rel(path) in self.shown


# --------------------------------------------------------------------------- the texts


@dataclass(frozen=True)
class Texts:
    """The manuscript as Markdown would print it, bindings in place and comments blanked:
    the main text and the supplement, a LaTeX one as `text/latex/printed.py` writes it."""

    main: str
    supplement: str


def manuscript_texts(project: Project) -> Texts:
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.numbers import is_supplementary, printed_order, source_files
    from manuscript_guard.text.masking import blank_comments, without_front_matter
    from manuscript_guard.text.reader import LATEX, manuscript_format

    folder = project.path("manuscript")
    if not folder.is_dir():
        return Texts("", "")
    if manuscript_format(folder) == LATEX:
        from manuscript_guard.text.latex.printed import printed_document

        return Texts(*(printed_document(folder, supplementary=part) for part in (False, True)))
    paths = source_files(folder)
    parts = []
    for supplementary in (False, True):
        mine = [p for p in paths if is_supplementary(folder, p) == supplementary]
        parts.append("\n\n".join(blank_comments(without_front_matter(read_text(p)))
                                 for p in printed_order(mine, supplementary=supplementary)))
    return Texts(*parts)


def filled(page: Page, markdown: str) -> str:
    """Markdown with each binding as it prints, a value the package withholds as WITHHELD."""
    from manuscript_guard.text.placeholders import substitute

    return substitute(markdown, page.displays)


#: A stop that may end a sentence: the mark, what closes after it, and a space before
#: something that is not a small letter.
_STOP = re.compile(
    "[.!?][)\\]\"'*_\N{RIGHT SINGLE QUOTATION MARK}\N{RIGHT DOUBLE QUOTATION MARK}]*"
    "(?=\\s+[^\\sa-z])"
)


def sentences(paragraph: str) -> list[str]:
    """A paragraph's sentences, its white space folded: cut after a stop, except after an
    abbreviation, an initial or a word with a stop inside it (`_ends_a_sentence`)."""
    from manuscript_guard.checking.produce import _ends_a_sentence

    flat = " ".join(paragraph.split())
    out, at = [], 0
    for found in _STOP.finditer(flat):
        if _ends_a_sentence(flat[: found.start() + 1]):
            out.append(flat[at : found.end()].strip())
            at = found.end()
    out.append(flat[at:].strip())
    return [piece for piece in out if piece]


def abstract_of(text: str) -> str | None:
    from manuscript_guard.text.sections import split_sections

    found = next((s for s in split_sections(text) if s.is_abstract), None)
    return None if found is None else (found.enclosed or found.body).strip()


def limitations_of(text: str) -> list[tuple[str, str]]:
    """Each section whose title names limitations, with what it encloses; one enclosed by
    another is the other's."""
    from manuscript_guard.text.sections import split_sections

    found: list[tuple[str, str]] = []
    for section in split_sections(text):
        if "limitation" not in section.title.casefold():
            continue
        body = (section.enclosed or section.body).strip()
        if body and not any(body in kept for _title, kept in found):
            found.append((" ".join(section.title.split()), body))
    return found


# ------------------------------------------------------------------- who may be named


def _authors(project: Project) -> list[str]:
    from manuscript_guard.approvals import authors_of, name_of

    return [name_of(author) for author in authors_of(project)]


def unnamed(project: Project) -> list[str]:
    """Every name a record holds of someone who is not an author: a role's holder, a
    reviewer of the panel, of a figure or of the design, a checker, a passage's judge, an
    attestor. The page shows none of them; the longest is replaced first."""
    from manuscript_guard.approvals import NoSuchAuthor
    from manuscript_guard.checking.store import read_decisions
    from manuscript_guard.sign_offs import ROLES, holder

    names: set[str] = set()
    roles = project.authors.get("roles") if isinstance(project.authors, dict) else None
    for role in ROLES:
        try:
            found = holder(project, role)
        except NoSuchAuthor:
            # A role naming someone `authors.yaml` does not list: the name as written.
            said = (roles or {}).get(role) if isinstance(roles, dict) else None
            names.add(str(said.get("author") if isinstance(said, dict) else said))
            continue
        if found is not None:
            names.add(found.name)
    keys = ("reviewed_by", "judged_by", "attested_by", "decided_by", "read_by", "signed_by",
            "person")  # fmt: skip
    for path in _records(project):
        names |= _named_in(path, keys)
    names |= {decision.by for decision in read_decisions(project.root)}
    allowed = set(_authors(project))
    return sorted({n.strip() for n in names if len(n.strip()) > 2} - allowed,
                  key=lambda name: (-len(name), name))  # fmt: skip


def _records(project: Project) -> list[Path]:
    """The records that name people: the panel's and the co-authors' comments, the figures'
    reviews, the passages and attestations, the design's records, the sign-offs."""
    found: list[Path] = []
    for place, pattern in ((project.root / "review", "*.yaml"),
                           (project.path("figures"), "*.review.yaml"),
                           (project.root / "design", "*.yaml"),
                           (project.root / "approvals", "*.yaml")):  # fmt: skip
        if place.is_dir():
            found += sorted(p for p in place.rglob(pattern) if p.is_file())
    for name in ("passages.yaml", "attested.yaml"):
        if (project.path("literature") / name).is_file():
            found.append(project.path("literature") / name)
    return found


def _named_in(path: Path, keys: tuple[str, ...]) -> set[str]:
    from manuscript_guard.contracts._schema import ContractError, read_structured

    try:
        document = read_structured(path)
    except (ContractError, OSError, ValueError):
        return set()
    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, str):
                    found.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(document)
    return found


def scrubbed(text: str, names: list[str], root: Path) -> str:
    """`text` with no name of `unnamed` and no path of the computer the package was made on.
    A picture's data URI is left as it is: its base64 is no text."""
    parts = re.split(r'(data:[^"]*)', text)
    roots = sorted({str(root), root.as_posix(), esc(str(root)), esc(root.as_posix())},
                   key=len, reverse=True)  # fmt: skip
    for at in range(0, len(parts), 2):
        for name in names:
            for form in {name, esc(name)}:
                parts[at] = parts[at].replace(form, A_READER)
        for form in roots:
            if len(form) > 3:
                parts[at] = parts[at].replace(form, ".")
    return "".join(parts)


# ------------------------------------------------------------------------ the head


def json_ld(project: Project, crate: bool) -> str:
    """The Schema.org description of the paper, for the page's head: every `<` written as
    an escape, so that nothing in it closes the script."""
    from manuscript_guard.gates.revision import rounds

    from .metadata import data_dois, keywords, people
    from .texts import licences

    authors = []
    for person in people(project):
        entity: dict = {"@type": "Person", "name": person.name or "An author"}
        if person.orcid:
            entity["@id"] = f"https://orcid.org/{quote(person.orcid, safe='')}"
        if person.given:
            entity["givenName"] = person.given
        if person.family:
            entity["familyName"] = person.family
        if person.affiliations:
            entity["affiliation"] = [{"@type": "Organization", "name": text}
                                     for _key, text in person.affiliations]  # fmt: skip
        authors.append(entity)
    document: dict = {"@context": "https://schema.org", "@type": "ScholarlyArticle",
                      "headline": str(project.paper.get("title", "")), "author": authors,
                      "version": str(len(rounds(project)) + 1)}  # fmt: skip
    words = keywords(project)
    if words:
        document["keywords"] = words
    found = [f"https://spdx.org/licenses/{quote(one, safe='')}" for one in licences(project)]
    if found:
        document["license"] = found[0] if len(found) == 1 else found
    doi = settings(project).get("doi")
    based = [{"@id": f"https://doi.org/{doi}"}] if doi else []
    based += [{"@id": "ro-crate-metadata.json"}] if crate else []
    based += [{"@id": f"https://doi.org/{one}"} for one in data_dois(project)]
    if based:
        document["isBasedOn"] = based
    if doi:
        document["identifier"] = [f"https://doi.org/{doi}"]
    text = json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ------------------------------------------------------------------ 1. overview


def citation_line(project: Project) -> str:
    """How to cite the package: its authors, title, year where `package.date` says it, and
    DOI where one is recorded."""
    from .metadata import people, title

    names = []
    for person in people(project):
        initials = "".join(part[0] for part in person.given.replace("-", " ").split() if part)
        names.append(" ".join(part for part in (person.family, initials) if part))
    said = ", ".join(n for n in names if n) or "The authors of the paper"
    line = f"{esc(said)}. {esc(title(project))}."
    date = settings(project).get("date")
    if date:
        line += f" {esc(str(date)[:4])}."
    doi = settings(project).get("doi")
    if doi:
        link = f"https://doi.org/{doi}"
        line += f' <a href="{esc(link)}">{esc(link)}</a>'
    return line


def history(page: Page) -> list[tuple[str, str]]:
    """Each dated event the records hold, by date: the plan frozen, each results file
    written, each revision round received, and the package's date."""
    from manuscript_guard.contracts._schema import ContractError, read_structured
    from manuscript_guard.gates.revision import rounds

    events: list[tuple[str, str]] = []
    frozen = page.project.root / "design" / "plan.frozen.yaml"
    try:
        record = read_structured(frozen) if frozen.is_file() else None
    except ContractError:
        record = None
    if isinstance(record, dict) and record.get("frozen_at"):
        events.append((str(record["frozen_at"]), "the analysis plan was kept as it stood, "
                       "when the first results were written"))  # fmt: skip
    for fragment in page.results.fragments:
        if fragment.generated_at and page.held(fragment.path):
            events.append((str(fragment.generated_at), f"`{fragment.generated_by}` wrote "
                           f"`{page.rel(fragment.path)}`"))  # fmt: skip
    for number, path in rounds(page.project):
        try:
            document = read_structured(path)
        except ContractError:
            continue
        if isinstance(document, dict) and document.get("received_on"):
            decision = str(document.get("decision") or "a decision")
            events.append((str(document["received_on"]), f"revision round {number} received: "
                           f"{decision.replace('-', ' ')}"))  # fmt: skip
    date = settings(page.project).get("date")
    if date:
        events.append((str(date), "the date the package gives itself (`package.date`)"))
    return sorted(set(events))


def package_digest(entries: list[Entry]) -> str:
    """The SHA-256 of the lines SHA256SUMS holds for every file but those UNDIGESTED."""
    lines = "".join(f"{entry.sha256}  {entry.path}\n" for entry in
                    sorted(entries, key=lambda e: e.path) if entry.path not in UNDIGESTED)
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()


def results_digest(page: Page) -> str:
    """`fragments_digest`, of the results files the package holds as they are here."""
    digest = hashlib.sha256()
    for entry in sorted(page.entries, key=lambda e: e.path):
        if entry.path in page.shown and entry.path.endswith(".json"):
            data = entry.data if entry.data is not None else entry.source.read_bytes()
            digest.update(entry.path.rsplit("/", 1)[-1].encode("utf-8") + b"\0" + data + b"\0")
    return digest.hexdigest()


def overview(page: Page, texts: Texts) -> list[str]:
    from manuscript_guard.gates.revision import rounds

    out = ['<section id="overview">', "<h2>1. Overview and citation</h2>"]
    abstract = abstract_of(texts.main)
    out.append("<h3>Abstract</h3>")
    out.append(page.prose.add(filled(page, abstract)) if abstract
               else "<p>The manuscript has no section titled Abstract.</p>")  # fmt: skip
    out += ["<h3>How to cite the package</h3>", f"<p>{citation_line(page.project)}</p>"]
    if not settings(page.project).get("doi"):
        out.append("<p>No DOI is recorded yet: once the repository gives one, it is written "
                   "in <code>paper.yaml</code> as <code>package.doi</code>.</p>")  # fmt: skip
    found = len(rounds(page.project))
    out.append(f"<p>Version {found + 1}: " + ("the manuscript before any revision round."
               if not found else f"the manuscript after {found} revision round"
               f"{'s' if found > 1 else ''}.") + "</p>")  # fmt: skip
    out.append("<h3>History, as the records date it</h3>")
    events = history(page)
    if events:
        out.append('<table><thead><tr><th>When</th><th>What</th></tr></thead><tbody>')
        out += [f"<tr><td>{esc(when)}</td><td>{page.prose.add(what, inline=True)}</td></tr>"
                for when, what in events]  # fmt: skip
        out.append("</tbody></table>")
    else:
        out.append("<p>No record of the project holds a date.</p>")
    out += [
        "<h3>Digests</h3>", "<dl>",
        "<dt>The results files</dt>",
        f"<dd><code>{results_digest(page)}</code>: the SHA-256 of their names and bytes, as "
        "<code>check</code> and <code>verify</code> take it.</dd>",
        "<dt>The files of the package</dt>",
        f"<dd><code>{package_digest(page.entries)}</code>: the SHA-256 of the lines of "
        "<code>SHA256SUMS</code> for every file but "
        + ", ".join(f"<code>{name}</code>" for name in UNDIGESTED) + ", which are made beside "
        "or after the others.</dd>", "</dl>",
        "</section>",
    ]  # fmt: skip
    return out


# ----------------------------------------------------------------------- the page


CSS = """
:root { --ink: #1d232a; --muted: #5a6470; --paper: #ffffff; --line: #d9dee4;
  --band: #f3f5f7; --accent: #1f5f8b; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e6e9ec; --muted: #a3acb6; --paper: #15191d; --line: #333b44;
    --band: #1e242a; --accent: #7fb8e0; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.55 Georgia, "Times New Roman", serif; }
header, main, nav { max-width: 60rem; margin: 0 auto; padding: 0 16px; }
header { padding-top: 2rem; }
h1 { font-size: 1.7rem; line-height: 1.25; margin: 0 0 .75rem; }
h2 { font-size: 1.35rem; margin: 2.5rem 0 .75rem; padding-top: 1rem;
  border-top: 1px solid var(--line); }
h3 { font-size: 1.1rem; margin: 1.75rem 0 .5rem; }
h4 { font-size: 1rem; margin: 1.25rem 0 .5rem; color: var(--muted); }
h5, h6 { font-size: 1rem; margin: 1rem 0 .4rem; }
a { color: var(--accent); }
nav ol { display: flex; flex-wrap: wrap; gap: .25rem 1.25rem; padding: 0; list-style: none;
  font: 14px/1.4 system-ui, sans-serif; }
.authors, .from, .note, dd, .digest, table { font-family: system-ui, sans-serif; }
.authors { margin: 0 0 .5rem; } .note, .from { color: var(--muted); font-size: 14px; }
.digest { font: 12px/1.3 ui-monospace, Consolas, monospace; color: var(--muted);
  overflow-wrap: anywhere; }
code, pre { font: 13px/1.4 ui-monospace, Consolas, monospace; }
code { overflow-wrap: anywhere; }
pre { background: var(--band); padding: .75rem; overflow-x: auto; white-space: pre; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin: .5rem 0 1rem;
  display: block; overflow-x: auto; }
th, td { border-bottom: 1px solid var(--line); padding: .35rem .5rem; text-align: left;
  vertical-align: top; }
thead th { background: var(--band); }
figure { margin: 1rem 0 2rem; } figure img { max-width: 100%; height: auto;
  background: #fff; }
figcaption { font-size: 15px; } dl dt { font-weight: bold; margin-top: .5rem; }
dl dd { margin: 0 0 .5rem 0; }
ol li { margin-bottom: .5rem; }
footer { max-width: 60rem; margin: 3rem auto 2rem; padding: 0 16px; color: var(--muted);
  font: 13px/1.4 system-ui, sans-serif; }
""".strip()

SECTIONS = (("overview", "Overview and citation"), ("evidence", "Key findings and evidence"),
            ("displays", "Figures, tables and models"),
            ("methods", "Methods and reproducibility"), ("limitations", "Limitations"),
            ("verification", "Co-author verification"))  # fmt: skip


def _byline(project: Project) -> list[str]:
    from .metadata import people

    found = people(project)
    places: dict[str, int] = {}
    names = []
    for person in found:
        marks = []
        for key, _text in person.affiliations:
            marks.append(str(places.setdefault(key, len(places) + 1)))
        name = esc(person.name or "An author")
        if person.orcid:
            link = f"https://orcid.org/{quote(person.orcid, safe='')}"
            name = f'<a href="{esc(link)}">{name}</a>'
        names.append(name + (f"<sup>{','.join(marks)}</sup>" if marks else ""))
    texts = {key: text for person in found for key, text in person.affiliations}
    out = [f'<p class="authors">{", ".join(names)}</p>'] if names else []
    if places:
        out.append('<ol class="note">' + "".join(
            f"<li>{esc(texts[key])}</li>" for key, _n in sorted(places.items(),
                                                                 key=lambda item: item[1]))
            + "</ol>")  # fmt: skip
    return out


def companion_html(project: Project, results: Results, entries: list[Entry],
                   inputs: list[Input], *, crate: bool = True) -> str:  # fmt: skip
    """The page, from the records, and the files the package holds besides it."""
    from manuscript_guard.gates.revision import displays

    from .bound import bound_rows
    from .companion_evidence import evidence
    from .companion_parts import displays_section, limitations, methods, verification

    results = _ordered(results)
    entries = sorted(entries, key=lambda entry: entry.path)
    inputs = sorted(inputs, key=lambda found: found.path)
    held = {entry.path for entry in entries}
    shown = frozenset(page_rel for f in results.fragments
                      if (page_rel := _rel(project, f.path)) in held)  # fmt: skip
    printed = dict(displays(project))
    for key, value in results.values.items():
        if f"results.{key}" in printed and _rel(project, value.source) not in shown:
            printed[f"results.{key}"] = WITHHELD
    page = Page(project, results, entries, inputs, Prose(), shown, printed,
                bound_rows(project))  # fmt: skip
    _small_counts_held(project, results, shown, held)
    texts = manuscript_texts(project)
    body = [*overview(page, texts), *evidence(page, texts), *displays_section(page, texts),
            *methods(page), *limitations(page, texts), *verification(page)]  # fmt: skip
    title = esc(project.paper.get("title", ""))
    language = esc(project.paper.get("english_variant") or "en")
    nav = "".join(f'<li><a href="#{key}">{number}. {name}</a></li>'
                  for number, (key, name) in enumerate(SECTIONS, 1))  # fmt: skip
    demonstration = ('<p class="note">A demonstration: the data of this paper are synthetic, '
                     "and its results describe no real population.</p>"
                     if project.paper.get("demonstration") is True else "")  # fmt: skip
    page_text = "\n".join([
        "<!DOCTYPE html>", f'<html lang="{language}">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        f'<script type="application/ld+json">\n{json_ld(project, crate)}\n</script>',
        f"<style>\n{CSS}\n</style>", "</head>", "<body>", "<header>", f"<h1>{title}</h1>",
        *_byline(project), demonstration,
        '<p class="note">The companion of this package: each part of it is made from what '
        "the project records, and none is written for it.</p>", "</header>",
        f'<nav aria-label="Sections"><ol>{nav}</ol></nav>', "<main>", *body, "</main>",
        '<footer>Made by <code>manuscript-guard package --companion</code> from the records '
        "the package holds. MANIFEST.yaml names the version of the tool and of pandoc it was "
        "made with.</footer>", "</body>", "</html>",
    ])  # fmt: skip
    page_text = page.prose.fill(page_text)
    page_text = scrubbed(page_text, unnamed(project), project.root)
    return page_text.replace("\r\n", "\n").rstrip("\n") + "\n"


def _rel(project: Project, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(project.root).as_posix()
    except ValueError:
        return path.name


def _ordered(results: Results) -> Results:
    """The results in one order whatever order they were read in: by file, and by key."""
    return replace(
        results,
        fragments=tuple(sorted(results.fragments, key=lambda f: f.path.as_posix())),
        values=dict(sorted(results.values.items())),
        tables=dict(sorted(results.tables.items())),
        models=dict(sorted(results.models.items())),
        variables=dict(sorted(results.variables.items())),
        steps=dict(sorted(results.steps.items())),
    )


def _small_counts_held(project: Project, results: Results, shown: frozenset[str],
                       held: set[str]) -> None:  # fmt: skip
    """Every count below the custodian's minimum in what the page shows is one the package
    holds already, and so one its own check refuses until the custodian signs it off. One that
    is not would be a count nobody was asked about."""
    from .counts import small_counts

    every = frozenset(_rel(project, f.path) for f in results.fragments)
    deposited = small_counts(project, results, every - frozenset(held))
    shown_small = small_counts(project, results, every - shown)
    left = [small for small in shown_small if small not in deposited]
    if left:
        first = left[0]
        raise PackageError(f"--companion would show {first.fragment}: {first.where}, "
                           f"{first.count}, a count below the data custodian's minimum that "
                           "the package does not deposit")  # fmt: skip


def companion_entries(project: Project, results: Results, entries: list[Entry],
                      inputs: list[Input]) -> list[Entry]:  # fmt: skip
    """ro-crate-preview.html and index.html, the same bytes."""
    from .plan import generated

    text = companion_html(project, results, entries, inputs)
    return [generated(COMPANION, text, "the companion page: the package as a reader sees it"),
            generated(SITE, text, "the companion page, as a site's front page")]  # fmt: skip


__all__ = ["COMPANION", "SITE", "UNDIGESTED", "companion_entries", "companion_html",
           "manuscript_texts", "package_digest", "sentences"]  # fmt: skip
