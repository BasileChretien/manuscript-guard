"""Section 2 of the companion page (`companion.py`): the key findings and the evidence map.

The key findings are the abstract's own sentences that print a value, word for word with the
values in (Basile, 2026-10-28: nothing is summarised). The evidence map is BOUND.md's rows
(`bound.bound_rows`), each binding with what it prints, where the manuscript has it, and the
results file it is read from; each results file with its digest, the script that wrote it and
the digest of that script its record holds. A sentence that cites a work is shown with the
passage that supports it only by where the passage is in the work: its words are the work's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .companion import WITHHELD, Page, Texts, abstract_of, esc, filled, sentences


def anchor(namespace: str, key: str) -> str:
    return "ev-" + re.sub(r"[^A-Za-z0-9_.-]", "-", f"{namespace}-{key}")


def file_anchor(path: str) -> str:
    return "file-" + re.sub(r"[^A-Za-z0-9_.-]", "-", path)


#: A value binding in a sentence: its namespace and key.
_VALUE = re.compile(r"\{\{\s*(results|lit)\.([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)\s*\}\}")


def _link(ref: str) -> str:
    namespace, key = ref.split(".", 1)
    if namespace == "results":
        return f'<a href="#{anchor("results", key)}"><code>{esc(ref)}</code></a>'
    return f"<code>{esc(ref)}</code>"


def key_findings(page: Page, texts: Texts, passages: dict[str, list[dict]]) -> list[str]:
    """The abstract's sentences that carry a value binding, word for word, values in."""
    from manuscript_guard.literature.passages import statement_words

    abstract = abstract_of(texts.main) or ""
    out = ["<h3>Key findings</h3>",
           "<p>The sentences of the abstract that print a value of the analysis or of the "
           "literature, as the abstract has them.</p>"]  # fmt: skip
    rows = []
    for paragraph in re.split(r"\n[ \t]*\n", abstract):
        # A heading's line is no sentence; the text under it in the paragraph is.
        paragraph = "\n".join(line for line in paragraph.splitlines()
                              if not line.lstrip().startswith("#"))
        for sentence in sentences(paragraph):
            bound = list(dict.fromkeys(f"{ns}.{key}" for ns, key in _VALUE.findall(sentence)))
            if not bound:
                continue
            row = (f"<li>{page.prose.add(filled(page, sentence), inline=True)}"
                   f'<div class="from">From {", ".join(_link(ref) for ref in bound)}</div>')
            for found in passages.get(statement_words(sentence), []):
                row += (f'<div class="from">Cited: <a href="#{found["id"]}">'
                        f"{esc(found['work'])}, {esc(found['locator'])}</a></div>")
            rows.append(row + "</li>")
    if not rows:
        return [*out, "<p>No sentence of the abstract prints a value.</p>"]
    return [*out, "<ol>", *rows, "</ol>"]


@dataclass(frozen=True)
class Origin:
    """A results file the package holds, as the evidence map names it."""

    file: str
    sha256: str
    script: str
    script_sha256: str
    written: str


def origins(page: Page) -> dict[str, Origin]:
    from manuscript_guard.emit import read_digest

    found = {}
    for fragment in page.results.fragments:
        made = page.rel(fragment.path)
        if made in page.shown:
            found[made] = Origin(made, read_digest(fragment.path) or "", fragment.generated_by,
                                 fragment.generated_by_sha256 or "",
                                 str(fragment.generated_at or ""))  # fmt: skip
    return dict(sorted(found.items()))


def _from(page: Page, source, known: dict[str, Origin]) -> str:
    made = page.rel(source)
    if made in known:
        return f'<a href="#{file_anchor(made)}"><code>{esc(made)}</code></a>'
    return "not in this package" if made else ""


def _row(page: Page, row, known: dict[str, Origin]) -> tuple[str, str]:
    """What a binding prints, and where it is read from."""
    if row.namespace == "results":
        value = page.results.values.get(row.key)
        if value is None:
            return "not in the results", ""
        return (value.display if page.held(value.source) else WITHHELD,
                _from(page, value.source, known))
    if row.namespace == "table":
        table = page.results.tables.get(row.key)
        if table is None:
            return "not in the results", ""
        return (table.caption or "a table" if page.held(table.source) else WITHHELD,
                _from(page, table.source, known))
    return "a figure, in section 3", ""


def evidence_map(page: Page) -> list[str]:
    known = origins(page)
    rows: dict[bool, list[str]] = {False: [], True: []}
    named: set[str] = set()
    for row in page.rows:
        ref = anchor(row.namespace, row.key)
        at = "" if ref in named else f' id="{ref}"'
        named.add(ref)
        prints, source = _row(page, row, known)
        rows[row.supplement].append(
            f"<tr{at}><td><code>{esc(row.namespace)}.{esc(row.key)}</code></td>"
            f"<td>{esc(prints)}</td><td><code>{esc(row.file)}</code>, line {row.line}: "
            f"{esc(row.section)}</td><td>{source}</td></tr>")  # fmt: skip
    out = ["<h3>Evidence map</h3>",
           "<p>Each value, table and figure of the analysis that the manuscript binds: what it "
           "prints, where, and the results file it is read from.</p>"]  # fmt: skip
    head = ("<table><thead><tr><th>Binding</th><th>Prints</th><th>Where</th>"
            "<th>Read from</th></tr></thead><tbody>")  # fmt: skip
    for supplement, title in ((False, "Main text"), (True, "Supplement")):
        out.append(f"<h4>{title}</h4>")
        out += [head, *rows[supplement], "</tbody></table>"] if rows[supplement] else \
            ["<p>It binds nothing of the analysis.</p>"]  # fmt: skip
    out += ["<h4>The results files</h4>",
            "<p>Each with the SHA-256 of its bytes its <code>.sha256</code> file records, and "
            "the script that wrote it with the SHA-256 of that script the results file "
            "records.</p>"]  # fmt: skip
    if not known:
        return [*out, "<p>The package holds none.</p>"]
    out.append("<table><thead><tr><th>Results file</th><th>Written by</th><th>Written</th>"
               "</tr></thead><tbody>")
    for found in known.values():
        out.append(f'<tr id="{file_anchor(found.file)}"><td><code>{esc(found.file)}</code>'
                   f'<br><span class="digest">{esc(found.sha256 or "no digest recorded")}'
                   f"</span></td><td><code>{esc(found.script)}</code><br>"
                   f'<span class="digest">{esc(found.script_sha256 or "no digest recorded")}'
                   f"</span></td><td>{esc(found.written)}</td></tr>")  # fmt: skip
    return [*out, "</tbody></table>"]


def supporting_passages(page: Page) -> tuple[list[dict], dict[str, list[dict]]]:
    """Each cited sentence with a passage of a work it cites that was found in the work's
    stored copy and that a person judged to support the sentence as it now reads: where the
    sentence stands, the work and the place in it; and the same, by the sentence's words."""
    from manuscript_guard.gates.literature import _MODEL_NAME
    from manuscript_guard.gates.passages import survey_of
    from manuscript_guard.literature.passages import SUPPORTS, VERIFIED, statement_words

    found_survey, _report = survey_of(page.project)
    rows: list[dict] = []
    by_words: dict[str, list[dict]] = {}
    for index, cited in found_survey.statements:
        for key in cited.keys:
            for checked in found_survey.of(index, key):
                passage = checked.passage
                if (checked.found != VERIFIED or passage.support != SUPPORTS
                        or checked.stale is not None
                        or _MODEL_NAME.search(passage.judged_by or "")):  # fmt: skip
                    continue
                row = {"id": f"passage-{len(rows) + 1}", "file": page.rel(cited.path),
                       "line": cited.line, "sentence": cited.text, "work": f"@{key}",
                       "locator": passage.locator, "judged_on": passage.judged_on or ""}
                rows.append(row)
                by_words.setdefault(statement_words(cited.text), []).append(row)
    return rows, by_words


def passages_table(page: Page, rows: list[dict]) -> list[str]:
    out = ["<h4>Cited sentences and the passages that support them</h4>",
           "<p>Each sentence that cites a work, where a passage of the work was found word for "
           "word in its stored copy and a person judged that it supports the sentence as it "
           "reads now. The passage is named by where it is in the work; its words are the "
           "work's, and are not reproduced here.</p>"]  # fmt: skip
    if not rows:
        return [*out, "<p>None is recorded.</p>"]
    out.append("<table><thead><tr><th>Where</th><th>Sentence</th><th>Work</th>"
               "<th>Passage, in the work</th><th>Judged on</th></tr></thead><tbody>")
    for row in rows:
        out.append(f'<tr id="{row["id"]}"><td><code>{esc(row["file"])}</code>, paragraph at '
                   f'line {row["line"]}</td>'
                   f"<td>{page.prose.add(filled(page, row['sentence']), inline=True)}</td>"
                   f"<td><code>{esc(row['work'])}</code></td><td>{esc(row['locator'])}</td>"
                   f"<td>{esc(row['judged_on'])}</td></tr>")  # fmt: skip
    return [*out, "</tbody></table>"]


def evidence(page: Page, texts: Texts) -> list[str]:
    rows, by_words = supporting_passages(page)
    return ['<section id="evidence">', "<h2>2. Key findings and the evidence map</h2>",
            *key_findings(page, texts, by_words), *evidence_map(page),
            *passages_table(page, rows), "</section>"]  # fmt: skip


__all__ = ["anchor", "evidence", "file_anchor", "key_findings", "supporting_passages"]
