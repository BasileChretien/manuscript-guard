"""ro-crate-preview.html: the package's companion page, one file a reader opens in a
browser, made from the records alone, and its copy index.html for a site.

It is self-contained: its style is in it, its pictures are data URIs, and the one script it
holds is the Schema.org description of the paper (`application/ld+json`), which no browser
runs. Its six sections are each made from what the project records, with no word written for
it by a model:

1. Overview and citation: the title, the authors, the abstract, how to cite the package, the
   history its records date, and the digests of the results files and of the package's files.
2. Key findings and the evidence map: the abstract's own sentences that print a value, word
   for word with the values in; each value, table and figure the manuscript binds, where, and
   the results file and script it comes from; each cited sentence whose supporting passage a
   person judged, with where in the work the passage is, never its words.
3. Figures, tables and models: a figure's SVG where its record of drawing matches it and no
   record ties it to a file the package withholds, its caption, its alternative text and
   where its review stands; each bound table; each held model's card, as MODELS.md prints
   it, and G15's findings under the cards by their code.
4. Methods and reproducibility: how to run each script again, what it ran with, the
   inputs, the Methods' claims and the steps they describe, and the last run of `verify`.
5. Limitations: the manuscript's sections on them, the plan's Deviations as written, G12's
   findings by their code, and what no gate checks.
6. Co-author verification: what each author checked, anyone else counted together, and each
   author's approval.

The page names nobody from a record but the authors `authors.yaml` lists, in the byline,
the citation, the checking and beside their approvals: a reviewer, a judge of a passage, a
checker or a role's holder is said by the role, counted or dated, and a gate's finding by
its code, at the project's stage, and its place where that is a file of the package, the
manuscript, the plan or paper.yaml (a review record by its round's folder), since a
message, and a record's file name, may name someone. The manuscript's prose and the plan's
Deviations are the authors' text, published with the paper and the package, and are printed
as written. Of a results file the package withholds no value, table, card or run is shown,
nor a figure a record says was drawn from a withheld file; a figure is drawn by a script
whose reads are otherwise not recorded, and the results' digest covers every results file.

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


#: What marks a piece of prose's place in the page until pandoc has written it. `esc` and
#: `Prose.add` take the character out of every record's text, so none can hold the mark.
MARK = "\x00"


def esc(text: object) -> str:
    return html.escape(str(text).replace(MARK, ""), quote=True)


@dataclass
class Prose:
    """The Markdown the page shows, each piece a token in the page until pandoc has written
    them all (`prose.html_fragments`)."""

    texts: list[str] = field(default_factory=list)
    inline: list[bool] = field(default_factory=list)

    def add(self, markdown: str, *, inline: bool = False) -> str:
        # The character that marks a piece's place, and that a masked view may hold.
        self.texts.append(markdown.replace(MARK, ""))
        self.inline.append(inline)
        return f"{MARK}{len(self.texts) - 1}{MARK}"

    def fill(self, page: str) -> str:
        from .prose import ProseError, html_fragments
        from .prose import inline as unwrapped

        try:
            written = html_fragments(self.texts)
        except ProseError as exc:
            raise PackageError(f"--companion: {exc}") from None
        done = [unwrapped(text) if flat else text
                for text, flat in zip(written, self.inline, strict=True)]  # fmt: skip
        return re.sub(f"{MARK}(\\d+){MARK}", lambda found: done[int(found[1])], page)


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
    """The digest of the files `fragments_digest` reads: every results file of the project by
    name and bytes, those the package withholds too (their digest, not what they hold), taken
    in the order of their names as POSIX writes them, so that it is one on every system.
    Where two names differ only in case, `fragments_digest` on Windows orders them otherwise."""
    digest = hashlib.sha256()
    results = page.project.path("results")
    found = results.glob("*.json") if results.is_dir() else []
    for path in sorted(found, key=lambda p: p.as_posix()):
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
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
        f"<dd><code>{results_digest(page)}</code>: the SHA-256 of the names and bytes of "
        "every results file of the project, those the package withholds too, in the order of "
        "their names, as <code>check</code> and <code>verify</code> take it.</dd>",
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
    shows_nothing_withheld(project, results, shown, inputs)
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


def withheld_results(project: Project, results: Results, inputs: list[Input]) -> frozenset[str]:
    """The results files the package withholds, as the plan decides them: each declared as an
    input that does not go (`plan_package`'s `withheld_results`)."""
    from .plan import _key

    produced = {_key(_rel(project, f.path)): _rel(project, f.path) for f in results.fragments}
    return frozenset(produced[_key(found.path)] for found in inputs
                     if not found.included and _key(found.path) in produced)  # fmt: skip


def shows_nothing_withheld(project: Project, results: Results, shown: frozenset[str],
                           inputs: list[Input]) -> None:  # fmt: skip
    """The page shows no results file the package withholds. What it shows is read from the
    files the package holds; this holds that to the plan's own reading of the inputs, so that
    a file held by mistake is a refusal and not a page. A count below the custodian's minimum
    in what the page shows is then one of the package's own, which its small-count check
    refuses until the custodian signs it off."""
    both = sorted(shown & withheld_results(project, results, inputs))
    if both:
        raise PackageError(f"--companion would show {both[0]}, a results file the package "
                           "withholds")  # fmt: skip


def companion_entries(project: Project, results: Results, entries: list[Entry],
                      inputs: list[Input]) -> list[Entry]:  # fmt: skip
    """ro-crate-preview.html and index.html, the same bytes. A record the page reads that
    cannot be read stops the page with what stopped it, not with a traceback."""
    from manuscript_guard.contracts._schema import ContractError

    from .plan import generated
    from .prose import ProseError

    try:
        text = companion_html(project, results, entries, inputs)
    except (ContractError, ProseError, OSError, UnicodeDecodeError) as exc:
        raise PackageError(f"--companion: the page cannot be made: {exc}") from None
    except Exception as exc:  # noqa: BLE001 - a hand-edited record: said, with its kind
        raise PackageError(f"--companion: the page cannot be made: {type(exc).__name__}: "
                           f"{exc}") from None
    return [generated(COMPANION, text, "the companion page: the package as a reader sees it"),
            generated(SITE, text, "the companion page, as a site's front page")]  # fmt: skip


__all__ = ["COMPANION", "SITE", "UNDIGESTED", "companion_entries", "companion_html",
           "manuscript_texts", "package_digest", "sentences"]  # fmt: skip
