"""Sections 3 to 6 of the companion page (`companion.py`): the figures, tables and models;
the methods and how to run them again; the limitations; and the co-authors' checking.

Each is made from a record, as the rest of the page is: a figure is shown only where its
record of drawing matches it, a review says where it stands and not who made it, and a G12
finding is G12's words.
"""

from __future__ import annotations

import re
from pathlib import Path

from .companion import WITHHELD, Page, Texts, esc, filled, limitations_of

#: The picture of a figure the page shows: its vector drawing, which is the one G3 reads.
PICTURES = (".svg",)
#: Where a figure's review stands, by G10's finding.
REVIEW_SAID = {
    "figure-unreviewed": "not reviewed",
    "figure-review-stale": "the figure has changed since it was reviewed",
    "figure-review-incomplete": "reviewed, with a required check not performed",
    "figure-review-check-failed": "reviewed, and a check did not pass",
    "figure-review-finding": "reviewed, and the review recorded a finding",
    "figure-review-concerns": "reviewed, and the review raised concerns",
    "schema-violation": "its review record cannot be read",
}
#: Where a claim of the Methods stands against the step it describes (`gates/methods.py`).
STANDING = {
    "read": "read against the code on {on}, and neither has changed since",
    "code": "the code has changed since the sentence was read against it",
    "claim": "the sentence has changed since it was read against the code",
    "unread": "never read against the code",
    "unknown": "no step of that name ran",
}


# ---------------------------------------------------------- 3. figures, tables, models


def _figures(page: Page) -> list[tuple[str, bool, object]]:
    """Each figure the manuscript binds, once, whether only the supplement does, and the
    first row binding it."""
    seen: dict[str, list] = {}
    for row in page.rows:
        if row.namespace == "figure":
            seen.setdefault(row.key, []).append(row)
    return [(key, all(r.supplement for r in rows), rows[0]) for key, rows in seen.items()]


def _matches(path: Path) -> bool:
    """Whether the figure's `*.render.json` records this file as drawn by the script beside
    it, both as they are now."""
    from manuscript_guard.emit import sha256_of, source_digest_matches
    from manuscript_guard.render import read

    document = read(path)
    if not isinstance(document, dict) or not isinstance(document.get("outputs"), dict):
        return False
    script, recorded = document.get("rendered_by"), document.get("rendered_by_sha256")
    if document["outputs"].get(path.name) != sha256_of(path) or not script or not recorded:
        return False
    drawn_by = path.with_name(str(script))
    return drawn_by.is_file() and source_digest_matches(drawn_by, str(recorded))


def _picture(page: Page, key: str) -> str:
    from manuscript_guard.checking.bundle import BundleError, _data_uri

    folder = page.project.path("figures")
    held = {entry.path for entry in page.entries}
    for suffix in PICTURES:
        path = folder / f"{key}{suffix}"
        if not path.is_file() or page.rel(path) not in held or not _matches(path):
            continue
        try:
            uri = _data_uri(path)
        except BundleError:
            return f'<p class="note"><code>{esc(page.rel(path))}</code> is too large to be ' \
                "shown in the page; it is in the package.</p>"  # fmt: skip
        return f'<img src="{uri}" alt="">'
    return ('<p class="note">Not shown: the package holds no SVG of it that its '
            "<code>*.render.json</code> records as drawn by the script beside it, as both "
            "are now.</p>")  # fmt: skip


def _markdown_caption(page: Page, row) -> str | None:
    from manuscript_guard.contracts._schema import read_text
    from manuscript_guard.gates.figure_files import _legend_after
    from manuscript_guard.text.masking import blank_comments
    from manuscript_guard.text.placeholders import parse

    text = blank_comments(read_text(page.project.root / row.file))
    for placeholder in parse(text)[0]:
        if placeholder.ref == f"figure.{row.key}" and placeholder.line == row.line:
            return _legend_after(text, placeholder.end)
    return None


def latex_captions(page: Page) -> dict[str, str]:
    """Each figure of a LaTeX manuscript held in a float of its own with one caption: the
    caption as the view prints it. A float of several figures or captions gives none."""
    from manuscript_guard.text.latex.printed import captions_in
    from manuscript_guard.text.latex.structure import read_document
    from manuscript_guard.text.latex.views import bindings

    found: dict[str, str] = {}
    folder = page.project.path("manuscript")
    for supplementary in (False, True):
        sources = [s for s in read_document(folder, supplementary=supplementary).sources
                   if not s.loose and not s.path.lower().endswith(".sty")]  # fmt: skip
        captions = captions_in(sources)
        for source in sources:

            def line(at: int, text: str = source.text) -> int:
                return text.count("\n", 0, at) + 1

            keys = [p for p in bindings(source)[0] if p.namespace == "figure"]
            for start, end in source.reading.figures:
                inside = [p.key for p in keys if start <= p.start < end]
                said = [text for path, at, text in captions
                        if path == source.path and line(start) <= at <= line(end)]  # fmt: skip
                if len(inside) == 1 and len(said) == 1:
                    found.setdefault(inside[0], said[0])
    return found


def _reviews(page: Page) -> dict[str, list[str]]:
    """What G10 says of each figure, by its name: the codes of its findings."""
    from manuscript_guard.gates.figure_review import REVIEW_SUFFIX, check_figure_reviews
    from manuscript_guard.gates.figures import content_digest

    said: dict[str, list[str]] = {}
    for finding in check_figure_reviews(page.project, content_digest).findings:
        if finding.path is None:
            continue
        name = Path(finding.path).name
        stem = name[: -len(REVIEW_SUFFIX)] if name.endswith(REVIEW_SUFFIX) else Path(name).stem
        said.setdefault(stem, []).append(finding.code)
    return said


def _review_line(page: Page, key: str, said: dict[str, list[str]]) -> str:
    from manuscript_guard.contracts._schema import ContractError, read_structured

    codes = said.get(key, [])
    if codes:
        return "; ".join(dict.fromkeys(REVIEW_SAID.get(code, code) for code in codes))
    path = page.project.path("figures") / f"{key}.review.yaml"
    try:
        record = read_structured(path) if path.is_file() else None
    except ContractError:
        record = None
    if not isinstance(record, dict):
        return "no review is recorded"
    when = f" on {record['reviewed_on']}" if record.get("reviewed_on") else ""
    return f"reviewed{when}, and every required check passed"


def figures(page: Page) -> list[str]:
    from manuscript_guard.gates.figure_alt import raw_alt
    from manuscript_guard.gates.figure_files import _files_of
    from manuscript_guard.text.reader import LATEX, manuscript_format

    latex = manuscript_format(page.project.path("manuscript")) == LATEX
    captions = latex_captions(page) if latex else {}
    said = _reviews(page)
    parts: dict[bool, list[str]] = {False: [], True: []}
    for key, supplementary, row in _figures(page):
        caption = captions.get(key) if latex else _markdown_caption(page, row)
        alt = raw_alt(page.project, key)
        files = ", ".join(f"<code>{esc(page.rel(p))}</code>"
                          for p in _files_of(page.project.path("figures"), key)) or "none"
        parts[supplementary] += [
            f'<figure id="figure-{esc(key)}">', f"<h5><code>figure.{esc(key)}</code></h5>",
            _picture(page, key),
            "<figcaption>" + (page.prose.add(filled(page, caption)) if caption else
                              '<p class="note">The manuscript gives it no caption the page '
                              "can read.</p>")  # fmt: skip
            + (f"<p><strong>Alternative text.</strong> "
               f"{esc(' '.join(filled(page, alt).split()))}</p>" if alt else
               '<p class="note">No alternative text is recorded.</p>')
            + f'<p class="note">Files: {files}. Review: {esc(_review_line(page, key, said))}.'
            "</p></figcaption>", "</figure>",
        ]  # fmt: skip
    return _parted("Figures", parts, "The manuscript binds no figure.")


def _parted(title: str, parts: dict[bool, list[str]], none: str) -> list[str]:
    out = [f"<h3>{title}</h3>"]
    if not parts[False] and not parts[True]:
        return [*out, f"<p>{none}</p>"]
    out += parts[False]
    if parts[True]:
        out += ["<h4>Supplement</h4>", *parts[True]]
    return out


def tables(page: Page) -> list[str]:
    seen: dict[str, bool] = {}
    for row in page.rows:
        if row.namespace == "table":
            seen[row.key] = seen.get(row.key, True) and row.supplement
    parts: dict[bool, list[str]] = {False: [], True: []}
    for key, supplementary in seen.items():
        table = page.results.tables.get(key)
        head = f"<h5><code>table.{esc(key)}</code></h5>"
        if table is None or not page.held(table.source):
            said = "not in the results" if table is None else WITHHELD
            parts[supplementary] += [head, f'<p class="note">{said}</p>']
            continue
        cells = "".join(f"<th>{esc(c)}</th>" for c in table.columns)
        body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
                       for row in table.rows)  # fmt: skip
        parts[supplementary] += [
            head, f"<p>{esc(table.caption or '')}</p>" if table.caption else "",
            f"<table><thead><tr>{cells}</tr></thead><tbody>{body}</tbody></table>",
            f'<p class="note">From <code>{esc(page.rel(table.source))}</code>.</p>'
        ]  # fmt: skip
    return _parted("Tables", parts, "The manuscript binds no table.")


def models(page: Page) -> list[str]:
    from dataclasses import replace

    from manuscript_guard.cards import model_cards

    held = {key: model for key, model in page.results.models.items()
            if page.held(model.source)}  # fmt: skip
    out = ["<h3>Models</h3>"]
    if not held:
        return [*out, "<p>The analysis recorded no model this package holds.</p>"]
    lines, _report = model_cards(page.project, replace(page.results, models=held))
    text = "\n".join(line.rstrip() for line in lines).strip("\n")
    # A sign-off's holder is named by the role alone.
    text = re.sub(r"; signed off by .+?, (the [a-z ]+), on ", r"; signed off by \1, on ", text)
    return [*out, "<p>Each model as <code>manuscript-guard models</code> prints it, with what "
            "the model check (G15) said of it when the package was made.</p>",
            f"<pre>{esc(text)}</pre>"]  # fmt: skip


def displays_section(page: Page, texts: Texts) -> list[str]:
    return ['<section id="displays">', "<h2>3. Figures, tables and models</h2>",
            *figures(page), *tables(page), *models(page), "</section>"]


# ------------------------------------------------------- 4. methods and reproducibility


def _session(fragment) -> str:
    session = fragment.session or {}
    said = f"{session.get('language', 'an unknown language')} {session.get('version', '')}"
    parts = [said.strip()]
    if session.get("platform"):
        parts.append(f"on {session['platform']}")
    line = ", ".join(parts)
    packages = session.get("packages")
    if isinstance(packages, dict) and packages:
        line += "; R packages " + ", ".join(f"{n} {v}" for n, v in sorted(packages.items()))
    return line


def _runs(page: Page) -> list[str]:
    from .texts import RUN

    out = ["<h3>How to run it again</h3>",
           "<p><code>README.md</code> says what to install and in which order to run them; "
           "<code>manuscript-guard verify</code> runs each in a copy and compares what it "
           "writes with the results here.</p>", "<table><thead><tr><th>Script</th>"
           "<th>Run as</th><th>Wrote</th><th>Ran with</th></tr></thead><tbody>"]  # fmt: skip
    for fragment in sorted(page.results.fragments, key=lambda f: (f.generated_by,
                                                                   f.path.as_posix())):
        if not page.held(fragment.path):
            continue
        suffix = Path(fragment.generated_by).suffix.lower()
        command = RUN.get(suffix, "{}").format(fragment.generated_by)
        out.append(f"<tr><td><code>{esc(fragment.generated_by)}</code></td>"
                   f"<td><code>{esc(command)}</code></td>"
                   f"<td><code>{esc(page.rel(fragment.path))}</code></td>"
                   f"<td>{esc(_session(fragment))}</td></tr>")  # fmt: skip
    return [*out, "</tbody></table>"]


def _lockfiles(page: Page) -> list[str]:
    held = [entry for entry in page.entries if entry.why == "what the analysis ran with"]
    out = ["<h3>What it ran with</h3>"]
    if not held:
        return [*out, "<p>The project pins no packages: no requirements file or lockfile is "
                "at its root.</p>"]  # fmt: skip
    out.append("<table><thead><tr><th>File</th><th>SHA-256</th><th>Recorded by the runs"
               "</th></tr></thead><tbody>")
    for entry in held:
        recorded = sorted({str(record.get("sha256")) for fragment in page.results.fragments
                           if page.held(fragment.path) for record in fragment.environment or ()
                           if isinstance(record, dict) and record.get("path") == entry.path})
        said = ("the same" if recorded == [entry.sha256] else "another digest" if recorded
                else "not recorded")  # fmt: skip
        out.append(f"<tr><td><code>{esc(entry.path)}</code></td>"
                   f'<td><span class="digest">{esc(entry.sha256)}</span></td>'
                   f"<td>{said}</td></tr>")
    return [*out, "</tbody></table>"]


def _inputs(page: Page) -> list[str]:
    out = ["<h3>The inputs</h3>"]
    if not page.inputs:
        return [*out, "<p>The analysis declared no input.</p>"]
    out.append("<table><thead><tr><th>Input</th><th>Bytes</th><th>SHA-256</th>"
               "<th>In the package</th></tr></thead><tbody>")
    for found in page.inputs:
        here = f"yes: {found.why}" if found.included else f"no: {found.why}"
        out.append(f"<tr><td><code>{esc(found.path)}</code></td>"
                   f"<td>{'' if found.size is None else found.size}</td>"
                   f'<td><span class="digest">{esc(found.sha256)}</span></td>'
                   f"<td>{esc(here)}</td></tr>")  # fmt: skip
    out.append("</tbody></table>")
    from .plan import settings

    if any(not found.included for found in page.inputs):
        request = settings(page.project).get("request") or "Not said."
        out += ["<p><strong>How to obtain the inputs that are not here.</strong></p>",
                page.prose.add(str(request))]  # fmt: skip
    return out


def _pairs(page: Page) -> list[str]:
    from manuscript_guard.gates.methods import _reconciled, pairs_of, read_lock

    lock = read_lock(page.project)
    pairs = pairs_of(page.project, page.results, lock if _reconciled(lock) else None)
    out = ["<h3>The Methods and the code they describe</h3>"]
    if lock.get("reconciled_on"):
        out.append(f"<p>The Methods were last read against the code on "
                   f"{esc(lock['reconciled_on'])} (<code>methods.lock</code>).</p>")
    if not pairs:
        return [*out, "<p>No sentence of the Methods points at a step of the code.</p>"]
    out.append("<table><thead><tr><th>Step</th><th>Code</th><th>Sentence</th>"
               "<th>Standing</th></tr></thead><tbody>")
    for pair in pairs:
        where = pair.found.where if pair.found is not None else ""
        standing = STANDING.get(pair.standing, pair.standing).format(on=pair.read_on or "a "
                                                                     "date not recorded")
        out.append(f"<tr><td><code>{esc(pair.step)}</code></td><td><code>{esc(where)}</code>"
                   f"</td><td>{page.prose.add(filled(page, pair.claim.text), inline=True)}</td>"
                   f"<td>{esc(standing)}</td></tr>")  # fmt: skip
    return [*out, "</tbody></table>"]


def _verify(page: Page) -> list[str]:
    from manuscript_guard.assurance import VERIFIED, VERIFIED_SCHEMA, fragments_digest
    from manuscript_guard.contracts._schema import ContractError, read_structured

    out = ["<h3>The last run of <code>verify</code></h3>"]
    path = page.project.path("build") / VERIFIED
    try:
        record = read_structured(path) if path.is_file() else None
    except ContractError:
        record = None
    if not isinstance(record, dict) or record.get("schema") != VERIFIED_SCHEMA:
        return [*out, "<p>No run of <code>verify</code> is recorded where the package was "
                "made.</p>"]  # fmt: skip
    said = (f"On {record.get('ran_on', 'a date not recorded')}, it re-ran the analysis and "
            f"reproduced {record.get('reproduced', 0)} of {record.get('values', 0)} values")
    left = record.get("not_rerun")
    if isinstance(left, list) and left:
        said += f"; {len(left)} results file(s) were not re-run"
    said += "; it passed" if record.get("ok") else "; it did not pass"
    if fragments_digest(page.project) != record.get("results_sha256"):
        said += "; the results have changed since"
    return [*out, f"<p>{esc(said)}.</p>"]


def methods(page: Page) -> list[str]:
    return ['<section id="methods">', "<h2>4. Methods and reproducibility</h2>",
            *_runs(page), *_lockfiles(page), *_inputs(page), *_pairs(page), *_verify(page),
            "</section>"]  # fmt: skip


# ------------------------------------------------------------------ 5. limitations


def _deviations(page: Page) -> str | None:
    from manuscript_guard.gates.design import REQUIRED, _plan_sections, _read_plan, plan_path

    path = plan_path(page.project)
    if not path.is_file():
        return None
    text = _read_plan(path)[0]
    pattern = {name: rule for name, rule, _purpose in REQUIRED}["deviations"]
    for section in _plan_sections(text):
        if re.search(pattern, section.title):
            return (section.enclosed or section.body).strip() or None
    return None


def _g12(page: Page) -> list[tuple[str, str]]:
    """What G12 says of the plan, the design's review, the registration, the data sources,
    the datasets and the methods of similar studies, as `check` runs it."""
    from manuscript_guard.gates.data_sources import check_data_sources, check_declared_datasets
    from manuscript_guard.gates.design import check_design
    from manuscript_guard.gates.design_review import check_design_rounds
    from manuscript_guard.gates.methods_review import check_methods_review
    from manuscript_guard.gates.registration import check_registration
    from manuscript_guard.policy import resolve_stage

    project, results = page.project, page.results
    stage = resolve_stage(project, None, False)
    checks = (
        lambda: check_design(project, results, stage), lambda: check_design_rounds(project),
        lambda: check_registration(project, results, stage),
        lambda: check_data_sources(project, stage),
        lambda: check_declared_datasets(project, results),
        lambda: check_methods_review(project),
    )  # fmt: skip
    found: list[tuple[str, str]] = []
    for check in checks:
        try:
            report = check()
        except Exception as exc:  # noqa: BLE001 - said on the page, as `check` says gate-errored
            found.append(("fail", f"a check of G12 stopped ({type(exc).__name__}); run "
                          "`manuscript-guard check` to see it"))  # fmt: skip
            continue
        for finding in report.findings:
            if finding.gate == "G12":
                found.append((finding.severity, finding.message))
    return list(dict.fromkeys(found))


def limitations(page: Page, texts: Texts) -> list[str]:
    from manuscript_guard.assurance import DIMENSIONS

    out = ['<section id="limitations">', "<h2>5. Limitations</h2>",
           "<h3>As the manuscript states them</h3>"]
    stated = [(False, *found) for found in limitations_of(texts.main)]
    stated += [(True, *found) for found in limitations_of(texts.supplement)]
    if not stated:
        out.append("<p>No section of the manuscript is titled for its limitations.</p>")
    for supplementary, title, body in stated:
        out.append(f"<h4>{esc(title)}{' (supplement)' if supplementary else ''}</h4>")
        out.append(page.prose.add(filled(page, body)))
    out.append("<h3>Deviations from the analysis plan, as the plan records them</h3>")
    said = _deviations(page)
    out.append(page.prose.add(said) if said else "<p>The plan records no section of its "
               "deviations.</p>")  # fmt: skip
    out.append("<h3>What the design check (G12) says</h3>")
    found = _g12(page)
    out += (["<ul>"] + [f"<li><strong>{esc(severity)}</strong>: {esc(message)}</li>"
                        for severity, message in found] + ["</ul>"]) if found else \
        ["<p>Nothing.</p>"]  # fmt: skip
    out += ["<h3>What no check decides</h3>", "<ul>"]
    out += [f"<li><strong>{esc(d.name)}</strong>: {esc(d.unchecked)}</li>" for d in DIMENSIONS]
    return [*out, "</ul>", "</section>"]


# ----------------------------------------------------------- 6. co-author verification


def _checking(page: Page) -> list[str]:
    from manuscript_guard.approvals import authors_of, name_of
    from manuscript_guard.checking.items import ItemsError
    from manuscript_guard.checking.store import STATUSES, status
    from manuscript_guard.cli import _checking_items

    out = ["<h3>What the co-authors checked</h3>"]
    try:
        standing = status(page.project.root, _checking_items(page.project, None))
    except ItemsError as exc:
        return [*out, f"<p>Nothing could be offered to check: {esc(exc)}</p>"]
    if not standing.by_person:
        return [*out, "<p>No co-author has recorded a check (<code>manuscript-guard checker"
                "</code>).</p>"]  # fmt: skip
    authors = [name_of(author) for author in authors_of(page.project)]
    head = "".join(f"<th>{esc(said)}</th>" for said in STATUSES)
    out.append(f"<table><thead><tr><th>Who</th>{head}</tr></thead><tbody>")
    for author in authors:
        counts = standing.by_person.get(author, {})
        out.append(f"<tr><td>{esc(author)}</td>"
                   + "".join(f"<td>{counts.get(s, 0)}</td>" for s in STATUSES) + "</tr>")
    others = [counts for person, counts in standing.by_person.items() if person not in authors]
    if others:
        out.append("<tr><td>others, not authors</td>" + "".join(
            f"<td>{sum(c.get(s, 0) for c in others)}</td>" for s in STATUSES) + "</tr>")
    out.append("</tbody></table>")
    out.append(f"<p>{standing.outstanding} item(s) nobody has answered; "
               f"{len(standing.stale)} answer(s) are of text that has changed since.</p>")
    return out


def _approvals(page: Page) -> list[str]:
    from manuscript_guard.approvals import DIRECTORY, authors_of, check_approvals, name_of, slug_of
    from manuscript_guard.contracts._schema import ContractError, read_structured

    by_path = {Path(f.path).name: f.code for f in check_approvals(page.project).findings
               if f.path is not None}  # fmt: skip
    out = ["<h3>The authors' approval of the manuscript</h3>", "<ul>"]
    for author in authors_of(page.project):
        name = f"{slug_of(author)}.yaml"
        code = by_path.get(name)
        try:
            path = page.project.root / DIRECTORY / name
            record = read_structured(path) if path.is_file() else None
        except ContractError:
            record = None
        when = record.get("approved_on") if isinstance(record, dict) else None
        if code == "approval-missing":
            said = "has not approved it"
        elif code == "approval-stale":
            said = f"approved it on {when}, and it has changed since"
        elif code is not None or not when:
            said = "an approval that cannot be read"
        else:
            said = f"approved it on {when}, as it stands"
        out.append(f"<li>{esc(name_of(author))}: {esc(said)}</li>")
    return [*out, "</ul>"]


def verification(page: Page) -> list[str]:
    return ['<section id="verification">', "<h2>6. Co-author verification</h2>",
            *_checking(page), *_approvals(page), "</section>"]


__all__ = ["displays_section", "latex_captions", "limitations", "methods", "verification"]
