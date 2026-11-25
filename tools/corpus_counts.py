"""The counts the false-alarm page is drawn from, `docs/false-alarms.yaml`, made from a run of
the corpus and its verdicts.

`python tools/corpus.py counts <run>` writes them; `tools/false_alarms.py` draws
`docs/false-alarms.md` from them, with no corpus. This is the one file the corpus tool
writes inside the checkout, and it holds counts only: for each paper, report and code of the
run, the warnings the run gave and, among them, the judged ones that were true and false. A
paper is named by its slug, its format and its field, never by its title or its text, and no
finding's message, context or sentence is read into it. The verdicts quote the papers, and
the papers are not this repository's to publish (docs/corpus.md).

The held-out set is counted at a milestone only (Basile, 2026-11-23), and its section is
kept as it stands when the tuning corpus is counted again. Its papers are numbered, not named,
and its rows name no code: builders never see its papers, and a row by code would point them
at the codes it fails on (Basile, 2026-11-25).
"""

from __future__ import annotations

import collections
import datetime
import re
from pathlib import Path

import yaml
from corpus_judging import EXPECTED_IN_NEW_PROJECT, NOTICES, code_of
from corpus_match import loud
from corpus_run import CorpusError, load_json

#: What a stratum is counted by: its paper, its report and its code.
REPORTS = ("audit", "audit-pdf", "check", "compare")
#: A code as a run's findings give it, gate and code; and a paper's format and field.
CODE = re.compile(r"[A-Za-z0-9]+/[a-z0-9][a-z0-9-]*")
WORD = re.compile(r"[a-z0-9][a-z0-9-]*")
SOURCE = re.compile(r"[a-z0-9][a-z0-9-]*(:[a-z0-9][a-z0-9-]*)?")
FORMATS = ("docx", "pdf", "latex", "markdown")

HEADER = """\
# The counts docs/false-alarms.md is drawn from. Written by `python tools/corpus.py counts`
# from a run of the corpus and its verdicts, and never edited by hand: docs/corpus.md, "The
# false-alarm page". Counts only: no paper's title or text, no finding's message.
#
# papers   each paper of the run: its format, its field and where it was found
# given    the warnings and failures about the paper the run gave, by report and code, in
#          every paper
# strata   [paper, report, code, warnings, judged true, judged false], where a judged warning
#          of that code stands in that paper's report: warnings counts all of them there
# heldout  the held-out papers at their last milestone, numbered, each with its format alone;
#          each row is one report and code of one paper, [paper, report, warnings, judged
#          true, judged false], the code unnamed
"""


def warnings(found: list[dict], report: str) -> collections.Counter:
    """The warnings and failures about the paper in a report, by code: a note, a question or
    a reading notice accuses nothing, and in `check` the codes every new project gives
    before anyone writes in it say nothing of the paper."""
    return collections.Counter(code_of(f) for f in found if loud(f) and not f.get("question")
                               and f.get("code") not in NOTICES and not (
                                   report == "check"
                                   and f.get("code") in EXPECTED_IN_NEW_PROJECT))  # fmt: skip


def strata(run, rows: list[dict]) -> tuple[dict, list[list]]:
    """The warnings of a run by report and code, and one row for each paper, report and code
    that holds a judged warning: the judged findings `measure` reports under their own code,
    the rest left out (asked, elsewhere and gone accuse nothing under it)."""
    given: dict[str, collections.Counter] = {}
    at = {}
    for slug, report, found in run.all_reports():
        said = warnings(found, report)
        given.setdefault(report, collections.Counter()).update(said)
        at.update({(slug, report, code): n for code, n in said.items()})
    judged: dict[tuple, list[int]] = collections.defaultdict(lambda: [0, 0])
    for row in rows:
        if row["state"] == "reported" and not row["notice"]:
            judged[(row["slug"], row["report"], row["code"])][row["verdict"] == "false"] += 1
    out = []
    for where in sorted(judged):
        true, false = judged[where]
        if true + false > at.get(where, 0):
            raise CorpusError(f"{' '.join(where)}: {true + false} judged warnings, more than the "
                              f"{at.get(where, 0)} the run gave there")  # fmt: skip
        out.append([*where, at[where], true, false])
    return {report: dict(sorted(given[report].items())) for report in REPORTS
            if given.get(report)}, out


def papers(root: Path, run) -> dict[str, list[str]]:
    """Each paper of the run, removed ones apart, with its format, its field and where it was
    found, as its meta.json names them."""
    out = {}
    for folder in sorted(p for p in run.folder.iterdir() if p.is_dir()):
        if folder.name in run.removed:
            continue
        meta = load_json(root / "corpus" / folder.name / "meta.json")
        if not isinstance(meta, dict):
            raise CorpusError(f"{folder.name}: no corpus/{folder.name}/meta.json to give its "
                              "format, field and source")  # fmt: skip
        said = [str(meta.get(k, "")) for k in ("format", "field", "source")]
        if said[0] not in FORMATS or not WORD.fullmatch(said[1]) or not SOURCE.fullmatch(said[2]):
            raise CorpusError(f"{folder.name}: its meta.json names no format of {FORMATS}, or no "
                              "field or source in lower-case letters, digits, '-' and "
                              "':'")  # fmt: skip
        out[folder.name] = said
    return out


def made(run) -> dict:
    """The commit and version the run's `run.json` names."""
    said = load_json(run.folder / "run.json")
    if not isinstance(said, dict) or not said.get("sha") or not said.get("version"):
        raise CorpusError(f"{run.name}: its run.json names no sha or version")
    return {"run": run.name, "commit": str(said["sha"]), "version": str(said["version"])}


#: The reasons the corpus tool leaves a verdict out for, kept by name: any other verdict word
#: is a judge's own, counted as "verdict other" so that its words go nowhere.
REASONS = ("verdict miss", "verdict unclear", "paper removed after judging",
           "no finding in the packet at its index")  # fmt: skip


def verdicts(rows: list[dict], skipped: dict) -> dict:
    """How many verdicts were read, the first packets' and the batches', and those left out."""
    left = collections.Counter({reason: n for reason, n in skipped.items() if reason in REASONS})
    left["verdict other"] += sum(n for reason, n in skipped.items() if reason not in REASONS)
    return {"first": sum(not r["batch"] for r in rows), "batches": sum(bool(r["batch"])
            for r in rows), "left_out": dict(sorted((+left).items()))}  # fmt: skip


def tuning(root: Path, run, result: dict) -> dict:
    """The tuning corpus's section: the run, the papers, the warnings and the strata."""
    given, rows = strata(run, result["findings"])
    return {**made(run), "date": datetime.date.today().isoformat(),
            "verdicts": verdicts(result["findings"], result["skipped"]),
            "papers": papers(root, run), "given": given, "strata": rows}  # fmt: skip


def heldout(root: Path, run, result: dict, milestone: int) -> dict:
    """The held-out set's section: its papers numbered in the order of their slugs, each with
    its format alone, since a field and a source beside it could name the paper; and one row
    for each report and code of a paper, its report named and its code not."""
    named = papers(root, run)
    number = {slug: f"h{n:02d}" for n, slug in enumerate(named, 1)}
    _, rows = strata(run, result["findings"])
    return {**made(run), "milestone": milestone,
            "papers": {number[slug]: said[0] for slug, said in named.items()},
            "strata": [[number[slug], report, n, true, false]
                       for slug, report, _code, n, true, false in rows]}  # fmt: skip


def write(path: Path, document: dict) -> None:
    """The counts, in the order the page reads them, a row to a line."""

    class Rows(yaml.SafeDumper):
        pass

    def row(dumper: yaml.SafeDumper, data: list) -> yaml.Node:
        flow = not any(isinstance(item, (list, dict)) for item in data)
        return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)

    Rows.add_representer(list, row)
    text = yaml.dump(document, Dumper=Rows, sort_keys=False, allow_unicode=False, width=100)
    path.write_text(HEADER + text, "utf-8", newline="\n")


def read(path: Path) -> dict:
    if not path.is_file():
        return {}
    said = yaml.safe_load(path.read_text("utf-8"))
    return said if isinstance(said, dict) else {}
