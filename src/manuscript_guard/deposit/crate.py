"""ro-crate-metadata.json and RELATIONS.md: the package described as an RO-Crate 1.1, a
Process Run Crate, from the records alone, and what the description leaves out and why.

Every entity is made from a record: the authors and their affiliations from `authors.yaml`
(an ORCID iD where one is given, and never an address), each file of the package with its
SHA-256 and size, each run of a script that wrote results from its fragment, each drawing of
a figure from its `*.render.json`, each input the package withholds from the digest the run
recorded, with how to obtain it.

Every action names its instrument, which the Process Run Crate profile requires: the script
in the package, or, where the package does not hold it, a contextual entity with the path
and the digest the record gives. That a script is the one its record names is checked
(`generated_by_sha256`, line endings left out as G1 compares it, or `rendered_by_sha256`),
and where it is not, RELATIONS.md says so. Every other relationship goes into `@graph` only
where it holds now, as the files here show it:

- each input a run read, where the file here, or on this computer for one the package
  withholds, has the digest the run recorded;
- the results a run wrote, where the fragment here has the digest of its `.sha256` file;
- each file a figure's script drew, where it has the digest its `*.render.json` recorded.

Each other relationship is in RELATIONS.md, as not as recorded or as not recorded: which
results a figure was drawn from is never recorded, and so never stated. Nothing reads the
clock: `datePublished` is `package.date`, or the day the latest results were written, and a
crate with neither is refused, since RO-Crate 1.1 requires the date.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.emit import input_digest_matches, read_digest, sha256_of
from manuscript_guard.emit import source_digest_matches as script_matches

from .metadata import Person, description, keywords, people, title
from .plan import Entry, Input, settings

CRATE = "ro-crate-metadata.json"
RELATIONS = "RELATIONS.md"
SPEC = "https://w3id.org/ro/crate/1.1"
CONTEXT = [
    f"{SPEC}/context",
    # Not a term of RO-Crate 1.1's own context: the Workflow Run Crate's, for a file's digest.
    {"sha256": "https://w3id.org/ro/terms/workflow-run#sha256"},
]
PROFILE = "https://w3id.org/ro/wfrun/process/0.5"
UNVERIFIED = "unverified"
NOT_RECORDED = "not recorded"
#: What a figure is, by its suffix, for the figures no `*.render.json` names.
PICTURES = (".svg", ".png", ".pdf", ".jpg", ".jpeg", ".tif", ".tiff", ".eps")


def file_id(path: str) -> str:
    return quote(path, safe="/")


def input_id(path: str) -> str:
    return "#input-" + quote(path, safe="/")


class _Crate:
    """The entities and the relations left out, gathered once."""

    def __init__(self, project: Project, entries: list[Entry]) -> None:
        self.project = project
        self.files = {entry.path: entry for entry in entries}
        self.entities: dict[str, dict] = {}
        self.left: list[tuple[str, str, str, str, str]] = []  # kind, from, relation, to, why

    def leave(self, kind: str, source: str, relation: str, target: str, why: str) -> None:
        self.left.append((kind, source, relation, target, why))

    def matches(self, path: str, check) -> bool | None:
        """Whether the file the package holds at `path` passes `check`, or None where the
        package does not hold it."""
        entry = self.files.get(path)
        if entry is None:
            return None
        if entry.source is not None:
            return bool(check(entry.source))
        return False


def date_published(project: Project, results: Results) -> str | None:
    """`package.date`, or the day the latest results were written, as their records say."""
    said = settings(project).get("date")
    if said:
        return str(said)
    latest: tuple[datetime, str] | None = None
    for fragment in results.fragments:
        written = str(fragment.generated_at or "")
        try:
            when = datetime.fromisoformat(written.replace("Z", "+00:00"))
        except ValueError:
            continue
        instant = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        if latest is None or (instant, written) > latest:
            latest = (instant, written)
    return latest[1][:10] if latest else None


def _people(crate: _Crate, found: list[Person]) -> list[dict]:
    """Each author as a Person, and each affiliation as an Organization; their ids."""
    ids, taken = [], set()
    for number, person in enumerate(found, 1):
        if person.orcid:
            at = f"https://orcid.org/{quote(person.orcid, safe='')}"
        else:
            at = f"#person-{number}"
        if at in taken:  # an ORCID iD given twice: the second author is named by place
            at = f"#person-{number}"
        taken.add(at)
        entity: dict = {"@id": at, "@type": "Person", "name": person.name or "An author"}
        if person.given:
            entity["givenName"] = person.given
        if person.family:
            entity["familyName"] = person.family
        if person.affiliations:
            entity["affiliation"] = [{"@id": f"#org-{quote(key, safe='')}"}
                                     for key, _text in person.affiliations]  # fmt: skip
            for key, text in person.affiliations:
                crate.entities[f"#org-{quote(key, safe='')}"] = {
                    "@id": f"#org-{quote(key, safe='')}", "@type": "Organization", "name": text}
        crate.entities[at] = entity
        ids.append({"@id": at})
    return ids


def _files(crate: _Crate, scripts: set[str]) -> None:
    for path, entry in crate.files.items():
        kind = ["File", "SoftwareSourceCode"] if path in scripts else "File"
        crate.entities[file_id(path)] = {
            "@id": file_id(path), "@type": kind, "name": PurePosixPath(path).name,
            "description": entry.why, "contentSize": str(entry.size), "sha256": entry.sha256}


def _withheld(crate: _Crate, inputs: list[Input]) -> None:
    access = str(settings(crate.project).get("request") or "Not said.")
    for found in inputs:
        if found.included:
            continue
        entity: dict = {"@id": input_id(found.path), "@type": "CreativeWork",
                        "name": found.path, "description": f"an input the analysis read, not "
                        f"in this package: {found.why}", "conditionsOfAccess": access}
        if found.sha256:
            entity["sha256"] = found.sha256
        if found.size is not None:
            entity["contentSize"] = str(found.size)
        crate.entities[input_id(found.path)] = entity


def _input_link(crate: _Crate, run: str, record: dict, inputs: dict[str, Input]) -> dict | None:
    from .plan import canonical

    path = canonical(str(record.get("path")))
    recorded = record.get("sha256")
    if not recorded:
        crate.leave(NOT_RECORDED, run, "object", path, "the run recorded no digest of it")
        return None
    held = crate.matches(path, lambda source: input_digest_matches(source, str(recorded)))
    if held is True:
        return {"@id": file_id(path)}
    if held is False:
        crate.leave(UNVERIFIED, run, "object", path, "the file here is not the one the run "
                    "read: its digest is another")  # fmt: skip
        return None
    found = inputs.get(path)
    if found is None or found.included:
        crate.leave(UNVERIFIED, run, "object", path, "the file is not in this package")
        return None
    on_disk = crate.project.root / path
    from .plan import inside

    if not inside(path) or not on_disk.is_file():
        crate.leave(UNVERIFIED, run, "object", path, "withheld, and not on the computer "
                    "that made the package, so its digest could not be compared")  # fmt: skip
        return None
    if input_digest_matches(on_disk, str(recorded)):
        return {"@id": input_id(path)}
    crate.leave(UNVERIFIED, run, "object", path, "withheld, and the copy on the computer "
                "that made the package is not the one the run read")  # fmt: skip
    return None


def _script_check(recorded: str):
    """Whether a script is the one `recorded` was taken from, line endings left out."""
    return lambda source: script_matches(source, recorded)


def _bytes_check(recorded: str):
    """Whether a file's bytes have the digest `recorded`."""
    return lambda source: sha256_of(source) == recorded


def _instrument(crate: _Crate, script: str, recorded: str | None) -> dict:
    """What a run names as its instrument, which a Process Run Crate requires of every
    action: the script in the package, whether or not it is the one the record's digest
    names (RELATIONS.md says which), or, where the package does not hold it, a contextual
    entity naming the path and the digest the record gives."""
    if script in crate.files:
        return {"@id": file_id(script)}
    at = "#script-" + quote(script, safe="/")
    said = (f"; its SHA-256, line endings left out, was recorded as {recorded}" if recorded
            else "")  # fmt: skip
    crate.entities[at] = {"@id": at, "@type": "SoftwareSourceCode", "name": script,
                          "description": f"the script a record names, not in this package{said}"}
    return {"@id": at}


def _unnamed_script(crate: _Crate, record: str, stem: str) -> dict:
    """The instrument of a drawing whose record names no script."""
    at = "#script-of-" + quote(record, safe="/")
    crate.entities[at] = {"@id": at, "@type": "SoftwareSourceCode",
                          "name": f"the script that drew {stem}",
                          "description": f"{record} does not name it"}
    return {"@id": at}


def _runs(crate: _Crate, results: Results, inputs: list[Input]) -> list[dict]:
    by_path = {found.path: found for found in inputs}
    actions = []
    for fragment in sorted(results.fragments, key=lambda f: f.path.as_posix()):
        try:
            made = fragment.path.relative_to(crate.project.root).as_posix()
        except ValueError:
            continue  # a results file outside the project, which refuses the package
        run = f"#run-{file_id(made)}"
        action: dict = {"@id": run, "@type": "CreateAction",
                        "name": f"The run of {fragment.generated_by} that wrote {made}"}
        if fragment.generated_at:
            action["endTime"] = str(fragment.generated_at)
        script, recorded = fragment.generated_by, fragment.generated_by_sha256
        held = crate.matches(script, _script_check(recorded)) if recorded else None
        action["instrument"] = _instrument(crate, script, recorded)
        if not recorded:
            crate.leave(NOT_RECORDED, run, "instrument", script, "the results were written "
                        "before the emitter recorded the script's digest")  # fmt: skip
        elif held is False:
            crate.leave(UNVERIFIED, run, "instrument", script, "the script here has changed "
                        "since it wrote these results")  # fmt: skip
        elif held is None:
            crate.leave(UNVERIFIED, run, "instrument", script, "the script is not in this "
                        "package")  # fmt: skip
        objects = [link for record in fragment.inputs if isinstance(record, dict)
                   and record.get("path") and (link := _input_link(crate, run, record, by_path))]
        if objects:
            action["object"] = sorted({o["@id"]: o for o in objects}.values(),
                                      key=lambda o: o["@id"])  # fmt: skip
        sidecar = read_digest(fragment.path)
        wrote = crate.files.get(made)
        if wrote is not None and sidecar and wrote.sha256 == sidecar:
            action["result"] = [{"@id": file_id(made)}]
        elif wrote is None:
            crate.leave(UNVERIFIED, run, "result", made, "the results file is not in this "
                        "package")  # fmt: skip
        else:
            crate.leave(UNVERIFIED, run, "result", made, "the results file is not the one its "
                        "`.sha256` file names" if sidecar else "no `.sha256` file records "
                        "its digest")  # fmt: skip
        crate.entities[run] = action
        actions.append({"@id": run})
    return actions


def _renders(crate: _Crate) -> tuple[list[dict], set[str], set[str]]:
    """Each drawing a `*.render.json` records; the scripts and the files it names."""
    from manuscript_guard.render import SUFFIX

    actions, scripts, drawn = [], set(), set()
    for path in sorted(p for p in crate.files if p.endswith(SUFFIX)):
        entry = crate.files[path]
        try:
            document = json.loads((entry.data or entry.source.read_bytes()).decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, AttributeError):
            document = None
        folder = PurePosixPath(path).parent
        run = f"#render-{file_id(path)}"
        stem = PurePosixPath(path).name[: -len(SUFFIX)]
        action: dict = {"@id": run, "@type": "CreateAction",
                        "name": f"The drawing of the figure {stem}, as {path} records it"}
        if not isinstance(document, dict):
            action["instrument"] = _unnamed_script(crate, path, stem)
            crate.leave(UNVERIFIED, run, "instrument", path, "it cannot be read as a record "
                        "of a drawing")  # fmt: skip
            crate.entities[run] = action
            actions.append({"@id": run})
            continue
        named, recorded = document.get("rendered_by"), document.get("rendered_by_sha256")
        if isinstance(named, str) and named:
            script = (folder / named).as_posix()
            scripts.add(script)
            held = crate.matches(script, _script_check(str(recorded))) if recorded else None
            action["instrument"] = _instrument(crate, script, str(recorded) if recorded else None)
            if not recorded:
                crate.leave(NOT_RECORDED, run, "instrument", script, "no digest of the script")
            elif held is not True:
                crate.leave(UNVERIFIED, run, "instrument", script, "the script here has changed "
                            "since it drew the figure" if held is False else "the script is "
                            "not in this package")  # fmt: skip
        else:
            action["instrument"] = _unnamed_script(crate, path, stem)
            crate.leave(NOT_RECORDED, run, "instrument", path, "it names no script")
        outputs = document.get("outputs") if isinstance(document.get("outputs"), dict) else {}
        made = []
        for name, digest in sorted(outputs.items()):
            out = (folder / str(name)).as_posix()
            drawn.add(out)
            held = crate.matches(out, _bytes_check(str(digest)))
            if held is True:
                made.append({"@id": file_id(out)})
            else:
                crate.leave(UNVERIFIED, run, "result", out, "the file here is not the one it "
                            "drew" if held is False else "the file is not in this package")
        if made:
            action["result"] = made
        crate.leave(NOT_RECORDED, run, "object", f"the results {stem} was drawn from",
                    "`*.render.json` does not record them")  # fmt: skip
        crate.entities[run] = action
        actions.append({"@id": run})
    return actions, scripts, drawn


def _unrecorded(crate: _Crate, drawn: set[str]) -> None:
    """What no record ties to anything: a figure no `*.render.json` names, and what the data
    dictionary and the record of the data sources describe."""
    try:
        figures = crate.project.path("figures").relative_to(crate.project.root).as_posix() + "/"
    except ValueError:
        figures = "figures/"
    for path in sorted(crate.files):
        if (path.startswith(figures) and path.lower().endswith(PICTURES)
                and path not in drawn):  # fmt: skip
            crate.leave(NOT_RECORDED, path, "created by", "", "no `*.render.json` records "
                        "what drew it")  # fmt: skip
    for record in ("design/data_dictionary.yaml", "design/data_sources.yaml"):
        if record in crate.files:
            crate.leave(NOT_RECORDED, record, "about", "the inputs", "which of the inputs it "
                        "describes: the record does not name their files")  # fmt: skip


def relations_text(left: list[tuple[str, str, str, str, str]]) -> str:
    out = ["# What ro-crate-metadata.json does not state", "",
           "ro-crate-metadata.json names the script of every run and every drawing, and "
           "states any other relationship only where the files of this package show that it "
           "holds: an input and a results file have the digests the run recorded, a file a "
           "figure's script drew has the digest its `*.render.json` recorded. Each script that "
           "is not the one its record names, and each relationship the crate does not state, "
           "is here, with why.", ""]  # fmt: skip
    for kind, heading, said in (
        (UNVERIFIED, "Not as recorded", "The record names it, and the files here do not show "
         "that it holds."),
        (NOT_RECORDED, "Not recorded", "No record says it."),
    ):
        rows = sorted({row[1:] for row in left if row[0] == kind})
        out += [f"## {heading}", "", said, ""]
        if rows:
            out += ["| From | Relation | To | Why |", "|---|---|---|---|"]
            out += [f"| {_cell(a)} | {_cell(b)} | {_cell(c)} | {_cell(d)} |"
                    for a, b, c, d in rows]  # fmt: skip
        else:
            out.append("None.")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _root(project: Project, results: Results, authors: list[dict], parts: list[str],
          mentions: list[dict]) -> dict:  # fmt: skip
    from .texts import licences

    root: dict = {"@id": "./", "@type": "Dataset", "name": title(project),
                  "description": description(project), "conformsTo": {"@id": PROFILE},
                  "hasPart": [{"@id": file_id(path)} for path in parts],
                  "mentions": mentions}  # fmt: skip
    when = date_published(project, results)
    if when:
        root["datePublished"] = when
    found = [{"@id": f"https://spdx.org/licenses/{quote(one, safe='')}"} for one in
             licences(project)]  # fmt: skip
    if found:
        root["license"] = found[0] if len(found) == 1 else found
    if authors:
        root["author"] = authors
    words = keywords(project)
    if words:
        root["keywords"] = ", ".join(words)
    doi = settings(project).get("doi")
    if doi:
        root["identifier"] = f"https://doi.org/{doi}"
    return root


def crate_files(project: Project, results: Results, entries: list[Entry], inputs: list[Input],
                with_manuscript: bool) -> tuple[str, str]:  # fmt: skip
    """The text of RELATIONS.md and of ro-crate-metadata.json, which names it with its
    digest: every other file of the package is in `entries`."""
    from .texts import licences

    crate = _Crate(project, entries)
    authors = _people(crate, people(project))
    runs = _runs(crate, results, inputs)
    renders, figure_scripts, drawn = _renders(crate)
    _unrecorded(crate, drawn)
    relations = relations_text(crate.left)
    data = relations.encode("utf-8")
    crate.files[RELATIONS] = Entry(RELATIONS, "what ro-crate-metadata.json does not state, and "
                                   "why", hashlib.sha256(data).hexdigest(), len(data), data=data)
    scripts = {fragment.generated_by for fragment in results.fragments} | figure_scripts
    _files(crate, {script for script in scripts if script in crate.files})
    _withheld(crate, inputs)
    if "MODELS.md" in crate.files:
        held = sorted({model.source.relative_to(project.root).as_posix()
                       for model in results.models.values()} & set(crate.files))  # fmt: skip
        if held:
            crate.entities[file_id("MODELS.md")]["about"] = [{"@id": file_id(p)} for p in held]
    for one in licences(project):
        at = f"https://spdx.org/licenses/{quote(one, safe='')}"
        crate.entities[at] = {"@id": at, "@type": "CreativeWork", "name": one}
    crate.entities[PROFILE] = {"@id": PROFILE, "@type": "CreativeWork",
                               "name": "Process Run Crate", "version": "0.5"}  # fmt: skip
    crate.entities[SPEC] = {"@id": SPEC, "@type": "CreativeWork", "name": "RO-Crate",
                            "version": "1.1"}  # fmt: skip
    paper: dict = {"@id": "#paper", "@type": "ScholarlyArticle",
                   "name": str(project.paper.get("title", "")), "isBasedOn": {"@id": "./"}}
    if authors:
        paper["author"] = authors
    if with_manuscript:
        held = sorted(path for path in crate.files if path.startswith("manuscript/"))
        if held:
            paper["hasPart"] = [{"@id": file_id(path)} for path in held]
    crate.entities["#paper"] = paper
    root = _root(project, results, authors, sorted(crate.files),
                 [*runs, *renders, {"@id": "#paper"}])  # fmt: skip
    descriptor = {"@id": CRATE, "@type": "CreativeWork", "conformsTo": {"@id": SPEC},
                  "about": {"@id": "./"}}  # fmt: skip
    graph = [descriptor, root, *(crate.entities[key] for key in sorted(crate.entities))]
    document = {"@context": CONTEXT, "@graph": graph}
    return relations, json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


__all__ = ["CRATE", "RELATIONS", "crate_files", "date_published", "file_id", "input_id",
           "relations_text"]  # fmt: skip
