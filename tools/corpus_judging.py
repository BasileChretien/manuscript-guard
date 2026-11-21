"""Packing the loud findings no verdict accounts for, for two judges, and setting the two
judges' verdicts side by side: the part of `tools/corpus.py` behind `unjudged` and `agree`,
and the reading of the packets the verdicts are indexed into (docs/corpus.md, "Judging").

Basile's decision (2026-11-21): two judges judge the findings with no verdict, once the
stock of codes not settled, then at every pull request's gate what its run adds. What they
agree on counts as judged; what they differ on, or either finds unclear, goes to him, and he
looks once at 20 agreements drawn at random.
"""

from __future__ import annotations

import collections
import json
import random
import re
from dataclasses import dataclass, replace
from pathlib import Path

from corpus_match import key_of, loud, norm
from corpus_run import SLUG, CorpusError, load_json

PACKETS = Path("report") / "packets"
JUDGED = Path("report") / "judged"
JUDGES = Path("report") / "judges"
#: The suffix of the file of the author's answers on a batch's disagreements.
AUTHOR = "-author"
VERDICTS = ("true", "false")
SAID = (*VERDICTS, "unclear")
#: The check findings the harness that wrote the first packets left out (its
#: `EXPECTED_IN_NEW_PROJECT`, in the corpus's `harness/tools/summarise.py`): codes every
#: project `init` makes gives before anyone writes in it. `leaves_out` also leaves out, as
#: it did, a check finding whose gate, code and message the same paper's audit gave.
EXPECTED_IN_NEW_PROJECT = frozenset({
    "plan-section-empty", "authors-incomplete", "unclassified-number", "pointers-unchecked",
    "no-analysis-plan", "journal-profile-missing",
})  # fmt: skip
#: A code is settled where this share of its judged findings loud in the run is true...
SETTLED = 0.9
#: ... and they number at least this.
MIN_JUDGED = 10
#: The agreements the author looks at once.
SAMPLE = 20
FIGURE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".tif", ".tiff",
                             ".eps", ".webp", ".bmp"})  # fmt: skip
#: Where a run's project holds figures: `figures/` those an analysis renders, `manuscript/`
#: those `init` took from the paper (media/ of a Word file, the source's folders of LaTeX).
FIGURE_FOLDERS = ("figures", "manuscript")


# --- the packets ------------------------------------------------------------------------


def is_batch(papers: object) -> bool:
    """Whether a packet is a batch `unjudged` wrote: its papers carry the batch's name, which
    no packet of the harness's does (a `run` field some might)."""
    return isinstance(papers, list) and any(isinstance(p, dict) and "batch" in p for p in papers)


def read_packets(root: Path) -> tuple[dict, dict]:
    """The first packets' papers by slug, the later of two of one slug winning as before
    batches were made, and each batch's papers by slug, by the batch's name."""
    first, batches = {}, {}
    for path in sorted((root / PACKETS).glob("*.json")):
        papers = load_json(path) or []
        if is_batch(papers):
            batches[path.stem] = {p["slug"]: p for p in papers}
        else:
            for paper in papers:
                first[paper["slug"]] = paper
    return first, batches


def packet_of(path: Path, batches: dict, entries: list) -> str | None:
    """The batch a verdict file is indexed into: `<batch>.json` and `<batch>-author.json`
    into `report/packets/<batch>.json`; None for a file of the first packets, read by slug.
    Refused where a file that is a batch's has no batch packet to read it by, since a
    verdict must never read another packet's finding at its index."""
    stem = path.stem
    if stem in batches:
        return stem
    if stem.endswith(AUTHOR):
        if stem[: -len(AUTHOR)] in batches:
            return stem[: -len(AUTHOR)]
        raise CorpusError(f"{path}: the author's answers on a batch, with no "
                          f"{PACKETS.as_posix()}/{stem[: -len(AUTHOR)]}.json to read them by")
    if any(isinstance(e, dict) and "judges" in e for e in entries):
        raise CorpusError(f"{path}: two judges' verdicts, with no {PACKETS.as_posix()}/"
                          f"{stem}.json to read them by")  # fmt: skip
    return None


def check_author(entry: dict, path: Path) -> None:
    """An answer of the author's names who gave it, when, and where it was given."""
    if path.stem.endswith(AUTHOR):
        missing = [k for k in ("by", "date", "source") if not str(entry.get(k) or "").strip()]
        if missing:
            raise CorpusError(f"{path}: an answer of the author's gives by, date and source; "
                              f"{entry.get('slug')} {entry.get('report')} {entry.get('index')} "
                              f"lacks {', '.join(missing)}")  # fmt: skip


# --- the verdicts -----------------------------------------------------------------------

#: Findings about the tool's own reading rather than about the paper: a part it did not read,
#: or how it read one. docs/corpus.md lists each with what it says; a test holds the two equal
#: and each code one the package writes.
NOTICES = frozenset({
    "abbreviations-passed-over", "abstract-not-compared", "causal-words-not-read",
    "displays-not-compared", "document-unreadable", "headings-read", "lookup-missing",
    "no-headings", "not-audited", "nothing-read",
    "passed-over", "reference-unchecked", "script-not-read", "statements-without-passage",
    "table-not-read", "tables-read-as-prose", "tex-refused", "tex-words-not-read",
    "unreadable", "version-not-numbered",
})  # fmt: skip


@dataclass
class Judged:
    slug: str
    report: str
    index: int
    verdict: str
    finding: dict
    judged: str = ""
    rejudged_by: str = ""
    #: The only finding of its gate and code in the judged run's report (the packet's
    #: `totals`), and about something that tells it from others of its code (`telling`).
    alone: bool = False
    #: The batch whose packet holds it (`unjudged`), that run's key scheme, the run's folder
    #: and the run's name as the packet gives it.
    batch: str = ""
    scheme: int = 0
    source: Path | None = None
    run: str = ""

    @property
    def code(self) -> str:
        return f"{self.finding.get('gate')}/{self.finding.get('code')}"

    @property
    def notice(self) -> bool:
        return self.finding.get("code") in NOTICES

    @property
    def key(self) -> tuple:
        """Its identity: the ledger and the ties name a first verdict by slug, report and
        index, which a batch's finding of the same place does not share."""
        return (self.slug, self.report, self.index, *([self.batch] if self.batch else []))


def telling(old: dict, messages: list[str]) -> bool:
    """Whether what a finding is about (`key_of`) tells it from others of its code: some
    finding of its code in the packets does not name it. "%" names every `notation-percent`."""
    key = key_of(old)
    return key is not None and not all(key.search(m) for m in messages)


def _messages(papers) -> dict[str, list[str]]:
    messages: dict[str, list[str]] = collections.defaultdict(list)
    for paper in papers:
        for report in paper.get("reports", {}).values():
            for f in report.get("findings", []):
                messages[f"{f.get('gate')}/{f.get('code')}"].append(str(f.get("message") or ""))
    return messages


def load_judged(root: Path) -> tuple[list[Judged], collections.Counter]:
    """Each verdict with the finding it judged, and a count of those left out, by reason. A
    batch's verdicts read its own packet (`packet_of`), and a finding judged twice in one
    batch is refused; the first ones read the first packets by slug, as before batches."""
    first, batches = read_packets(root)
    messages = _messages(first.values())
    every = _messages([*first.values(), *(p for b in batches.values() for p in b.values())])
    judged, skipped, seen = [], collections.Counter(), set()
    for path in sorted((root / "report" / "judged").glob("*.json")):
        entries = load_json(path) or []
        batch = packet_of(path, batches, entries)
        for entry in entries:
            check_author(entry, path)
            verdict = str(entry.get("verdict")).lower()
            if verdict not in VERDICTS:
                skipped[f"verdict {verdict}"] += 1
                continue
            try:
                paper = (batches[batch] if batch else first)[entry["slug"]]
                old = paper["reports"][entry["report"]]["findings"][int(entry["index"])]
            except (KeyError, IndexError, TypeError, ValueError):
                skipped["no finding in the packet at its index"] += 1
                continue
            totals = paper["reports"][entry["report"]].get("totals") or {}
            code = f"{old.get('gate')}/{old.get('code')}"
            alone = totals.get(code) == 1 and telling(old, (every if batch else messages)[code])
            item = Judged(entry["slug"], entry["report"], int(entry["index"]), verdict, old,
                          judged=verdict, alone=alone)  # fmt: skip
            if batch:
                # The run's folder as `unjudged` found it, else runs/<its name>, else none:
                # its counts are then held to the run measured.
                folders = [Path(str(paper["folder"]))] if paper.get("folder") else []
                folders.append(root / "runs" / str(paper.get("run")))
                item = replace(item, batch=batch, scheme=int(paper.get("scheme") or 1),
                               source=next((f for f in folders if f.is_dir()), None),
                               run=str(paper.get("run") or ""))
                if item.key in seen:
                    raise CorpusError(f"{path}: {' '.join(map(str, item.key))} is judged twice")
                seen.add(item.key)
            judged.append(item)
    if not judged:
        raise CorpusError(f"{root / 'report'} holds no judged finding (docs/corpus.md)")
    return judged, skipped


# --- unjudged ---------------------------------------------------------------------------


def code_of(finding: dict) -> str:
    return f"{finding.get('gate')}/{finding.get('code')}"


def settled_codes(rows: list[dict], share: float, least: int) -> dict[str, tuple[int, int]]:
    """The codes whose judged findings loud in the run (reported or elsewhere) number `least`
    or more, `share` of them true or more: each with its true and its loud count."""
    counts: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for row in rows:
        if row["state"] in ("reported", "elsewhere"):
            counts[row["code"]][0] += row["verdict"] == "true"
            counts[row["code"]][1] += 1
    return {code: (t, n) for code, (t, n) in counts.items() if n >= least and t / n >= share}


def leaves_out(report: str, finding: dict, audited: set) -> bool:
    return report == "check" and (finding.get("code") in EXPECTED_IN_NEW_PROJECT or (
        finding.get("gate"), finding.get("code"), finding.get("message")) in audited)


def loud_keys(run, slug: str, report: str) -> set[str]:
    return {f["key"] for f in run.findings(slug, report) or []
            if loud(f) and isinstance(f.get("key"), str)}  # fmt: skip


def base_problem(run, base) -> str | None:
    """Why the keys of two runs cannot be set side by side, or None where they can."""
    if not (run.keyed and base.keyed):
        return f"{base.name if run.keyed else run.name} carries no keys"
    if run.scheme != base.scheme:
        return f"{base.name} keys by scheme {base.scheme} and {run.name} by {run.scheme}"
    return None


def picked(run, keep) -> list[tuple[str, str, list[dict], list[int]]]:
    """Each report's loud findings that no judged finding accounts for (`run.used`, filled by
    pairing the judged set with the run), less those the harness left out, that `keep`
    takes."""
    out = []
    for slug, report, found in run.all_reports():
        used = run.used.get((slug, report), set())
        audited = {(f.get("gate"), f.get("code"), f.get("message"))
                   for f in run.findings(slug, "audit") or []} if report == "check" else set()
        chosen = [i for i, f in enumerate(found) if i not in used and loud(f)
                  and not leaves_out(report, f, audited) and keep(slug, report, f)]
        if chosen:
            out.append((slug, report, found, chosen))
    return out


def held_keys(root: Path, scheme: int) -> collections.Counter:
    """How many times the batch packets of a scheme hold each key, by paper and report:
    findings packed already, whose verdicts may wait for the author."""
    _first, batches = read_packets(root)
    return collections.Counter(
        (slug, report, f["key"]) for papers in batches.values()
        for slug, paper in papers.items() if paper.get("scheme") == scheme
        for report, part in paper.get("reports", {}).items()
        for f in part.get("findings", []) if isinstance(f.get("key"), str))  # fmt: skip


def select(root: Path, run, rows: list[dict], base=None, share: float = SETTLED,
           least: int = MIN_JUDGED) -> dict:  # fmt: skip
    """What `unjudged` packs, written nowhere: the loud findings of `run` no judged finding
    accounts for (`rows`, the measure of the judged set in it, has filled `run.used`), of a
    code not settled, or with `base` of every code those whose key is not loud in the base's
    same paper and report; less, either way, those the harness left out and those a batch
    packet of the run's scheme holds already, which are counted."""
    settled = {} if base is not None else settled_codes(rows, share, least)
    if base is not None and base_problem(run, base):
        raise CorpusError(f"--base sets keys side by side, and {base_problem(run, base)}")
    held, again = held_keys(root, run.scheme), collections.Counter()

    def keep(slug: str, report: str, f: dict) -> bool:
        if (f.get("key") in loud_keys(base, slug, report) if base is not None
                else code_of(f) in settled):  # fmt: skip
            return False
        # As many under a key as the batches hold, in order: the rest are new.
        where = (slug, report, f.get("key"))
        if again[where] < held[where]:
            again[where] += 1
            return False
        return True

    found = picked(run, keep)
    return {"found": found, "settled": settled, "packed_already": sum(again.values())}


def fresh(root: Path, run, rows: list[dict], base) -> dict:
    """For the gate: the count by code of what `unjudged <run> --base <base>` packs, by the
    same selection (`select`), and that command."""
    problem = base_problem(run, base)
    if problem:
        return {"count": None, "note": problem}
    found = select(root, run, rows, base)["found"]
    codes = collections.Counter(code_of(f[i]) for _s, _r, f, chosen in found for i in chosen)
    return {"count": sum(codes.values()), "by_code": dict(codes.most_common()),
            "command": f"python tools/corpus.py unjudged {run.name} --name {run.name}-added "
                       f"--base {base.name}"}  # fmt: skip


def render_fresh(said: dict) -> list[str]:
    if said["count"] is None:
        return ["", f"Loud findings new against the base with no verdict: not counted, as "
                f"{said['note']}."]  # fmt: skip
    return ["", f"Loud findings of the new run whose key is not loud in the base, with no "
            f"verdict: {said['count']}. To pack them for two judges: `{said['command']}`."]


def judge_text(root: Path, run, slug: str, meta: dict) -> str | None:
    """The text a judge reads, as the harness chose it (`judge_text` in summarise.py): the
    run's `main.md` of a Word paper, the source of a LaTeX one, pdftotext's text of a PDF.
    That text is the PDF's whatever the build, so the text the harness wrote beside another
    run's reports serves; nothing is run on the paper here. None where no such file is."""
    here = run.folder / slug
    if meta.get("format") == "docx":
        found = [here / "project" / "manuscript" / "main.md"]
    elif meta.get("format") == "latex":
        found = [root / "corpus" / slug / "files" / str(meta.get("main"))]
    else:
        runs = root / "runs"
        found = [here / "paper.txt", *sorted(p / slug / "paper.txt" for p in
                                             (runs.iterdir() if runs.is_dir() else ()))]
    return next((str(p) for p in found if p.is_file()), None)


def figure_files(project: Path, finding: dict) -> list[str]:
    """For a G3 finding, the figure files of the run's project its message names, by their
    path in the project or their name; all of them where it names none."""
    files = sorted(p for folder in FIGURE_FOLDERS if (project / folder).is_dir()
                   for p in (project / folder).rglob("*")
                   if p.is_file() and p.suffix.lower() in FIGURE_SUFFIXES)  # fmt: skip
    message = str(finding.get("message") or "").replace("\\", "/")
    by_path = [p for p in files if p.relative_to(project).as_posix() in message]
    by_name = [p for p in files
               if re.search(rf"(?<![\w.-]){re.escape(p.name)}(?![\w-])", message)]  # fmt: skip
    return [str(p) for p in by_path or by_name or files]


def _paper(root: Path, run, slug: str, first: dict, name: str) -> dict:
    meta = load_json(root / "corpus" / slug / "meta.json")
    meta = {**{k: first.get(k) for k in ("title", "format", "window")},
            **(meta if isinstance(meta, dict) else {})}  # fmt: skip
    main = meta.get("main")
    return {"slug": slug, "title": meta.get("title"), "format": meta.get("format"),
            "window": meta.get("window"), "text": judge_text(root, run, slug, meta),
            "original": str(root / "corpus" / slug / "files" / main) if main else None,
            "batch": name, "run": run.name, "folder": str(run.folder), "scheme": run.scheme,
            "reports": {}}  # fmt: skip


def pack(root: Path, run, rows: list[dict], name: str, base=None,
         share: float = SETTLED, least: int = MIN_JUDGED) -> dict:  # fmt: skip
    """Write `report/packets/<name>.json`, what `select` takes. Refused where the packet is
    there already, or a verdict file of its name, which `packet_of` would read against it."""
    if not SLUG.fullmatch(name) or ".." in name or name.endswith(AUTHOR):
        raise CorpusError(f"{name!r} cannot name a batch: letters, digits, '.', '_' and '-', "
                          f"not ending in {AUTHOR}")  # fmt: skip
    path = root / PACKETS / f"{name}.json"
    if path.exists():
        raise CorpusError(f"{path} is there already: name the batch otherwise")
    for verdicts in (JUDGED / f"{name}.json", JUDGED / f"{name}{AUTHOR}.json"):
        if (root / verdicts).exists():
            raise CorpusError(f"{verdicts.as_posix()} is there already, and would be read "
                              "against the batch's packet: name the batch otherwise")
    selection = select(root, run, rows, base, share, least)
    found, settled = selection["found"], selection["settled"]
    first, _batches = read_packets(root)
    papers: dict[str, dict] = {}
    for slug, report, every, chosen in found:
        if slug not in papers:
            papers[slug] = _paper(root, run, slug, first.get(slug, {}), name)
        paper = papers[slug]
        project = run.folder / slug / "project"
        paper["reports"][report] = {
            "totals": dict(collections.Counter(code_of(f) for f in every)),
            "findings": [{**every[i], "figure_files": figure_files(project, every[i])}
                         if every[i].get("gate") == "G3" else dict(every[i]) for i in chosen]}
    codes = collections.Counter(code_of(f) for p in papers.values()
                                for r in p["reports"].values() for f in r["findings"])
    if papers:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(list(papers.values()), indent=1, ensure_ascii=False), "utf-8")
    return {"name": name, "run": run.name, "scheme": run.scheme, "path": str(path),
            "written": bool(papers), "papers": len(papers), "findings": sum(codes.values()),
            "base": base.name if base is not None else None, "by_code": dict(codes.most_common()),
            "settled": settled, "no_text": sorted(s for s, p in papers.items() if not p["text"]),
            "packed_already": selection["packed_already"]}


def render_pack(result: dict) -> str:
    which = (f"of every code, whose key is not loud in {result['base']}" if result["base"] else
             f"of the codes not settled ({len(result['settled'])} settled left out)")
    said = (f"Wrote {result['path']}: {result['findings']} loud findings of {result['run']} "
            f"with no verdict, {which}, in {result['papers']} papers."
            if result["written"] else f"Nothing to pack: no loud finding of {result['run']} "
            f"with no verdict, {which}. No packet written.")  # fmt: skip
    lines = [f"## Batch {result['name']}", "", said, ""]
    if result["packed_already"]:
        lines += [f"{result['packed_already']} left out as a batch holds them already.", ""]
    if result["no_text"]:
        lines += [f"No text for a judge found for: {', '.join(result['no_text'])}.", ""]
    lines += ["| code | findings |", "| --- | ---: |"]
    lines += [f"| {c} | {n} |" for c, n in result["by_code"].items()] or ["| none | |"]
    return "\n".join(lines) + "\n"


# --- agree ------------------------------------------------------------------------------


def _verdicts(path: Path, wanted: dict) -> dict:
    entries = load_json(path)
    if not isinstance(entries, list):
        raise CorpusError(f"{path}: no list of verdicts there")
    out = {}
    for entry in entries:
        try:
            where = (str(entry["slug"]), str(entry["report"]), int(entry["index"]))
        except (KeyError, TypeError, ValueError):
            raise CorpusError(f"{path}: a verdict names its slug, report and index") from None
        if where not in wanted:
            raise CorpusError(f"{path}: {' '.join(map(str, where))} is no finding of the packet")
        if where in out:
            raise CorpusError(f"{path}: {' '.join(map(str, where))} is judged twice")
        verdict = str(entry.get("verdict")).lower()
        if verdict not in SAID:
            raise CorpusError(f"{path}: {' '.join(map(str, where))}: a verdict is true, false "
                              f"or unclear, not {entry.get('verdict')!r}")  # fmt: skip
        out[where] = {**entry, "verdict": verdict}
    missing = [w for w in wanted if w not in out]
    if missing:
        raise CorpusError(f"{path}: {len(missing)} findings of the packet are not judged, "
                          f"first {' '.join(map(str, missing[0]))}")  # fmt: skip
    return out


def _item(n: int, where: tuple, finding: dict, a: dict, b: dict) -> list[str]:
    slug, report, index = where
    place = f"{finding.get('path') or 'no file'}, line {finding.get('line') or '-'}"
    lines = [f"### {n}. {slug} {report} {index}: {code_of(finding)}", "",
             f"- Message: {norm(finding.get('message'))}",
             f"- Sentence: {norm(finding.get('context')) or 'none given'}",
             f"- Where: {norm(place)}"]
    for name, said in (("A", a), ("B", b)):
        lines.append(f"- Judge {name}: {said.get('verdict')} ({said.get('kind') or 'no kind'}): "
                     f"{said.get('why') or 'no reason given'}")  # fmt: skip
    return [*lines, ""]


def agree(root: Path, batch: str) -> dict:
    """Set the two judges' verdicts on a batch side by side: write the agreements as its
    verdicts, the rest for the author, and a sample of 20 agreements, refusing to overwrite
    any of the three."""
    packet = load_json(root / PACKETS / f"{batch}.json")
    if not isinstance(packet, list):
        raise CorpusError(f"no packet {PACKETS.as_posix()}/{batch}.json to read the verdicts by")
    if not is_batch(packet):
        raise CorpusError(f"{PACKETS.as_posix()}/{batch}.json is not a batch's packet: `agree` "
                          "reads two judges' verdicts on a batch `unjudged` wrote")  # fmt: skip
    wanted = {(p["slug"], report, i): f for p in packet
              for report, part in p.get("reports", {}).items()
              for i, f in enumerate(part.get("findings", []))}  # fmt: skip
    a, b = (_verdicts(root / JUDGES / batch / f"{j}.json", wanted) for j in ("a", "b"))
    out = [root / JUDGED / f"{batch}{end}" for end in (".json", "-disagreements.md", "-sample.md")]
    there = [str(p) for p in out if p.exists()]
    if there:
        raise CorpusError(f"{', '.join(there)} there already: nothing written")
    agreed, split = [], []
    for where, finding in wanted.items():
        if a[where]["verdict"] == b[where]["verdict"] and a[where]["verdict"] in VERDICTS:
            entry = {"slug": where[0], "report": where[1], "index": where[2],
                     "verdict": a[where]["verdict"], "gate": finding.get("gate"),
                     "code": finding.get("code"), "judges": 2}  # fmt: skip
            for name in ("kind", "why", "useful", "message_quality"):
                entry |= {f"{name}_a": a[where].get(name), f"{name}_b": b[where].get(name)}
            agreed.append(entry)
        else:
            split.append(where)
    drawn = random.Random(batch).sample(agreed, min(SAMPLE, len(agreed)))
    answer = (f"Answer by number, true or false and why. Each answer goes in "
              f"`{JUDGED.as_posix()}/{batch}{AUTHOR}.json`, a list of `{{slug, report, index, "
              "verdict, why, by, date, source}`.")  # fmt: skip
    lines = [f"# {batch}: the findings the two judges did not agree on ({len(split)})", "",
             "Those they judged differently, and those either judged unclear.", "", answer, ""]
    for n, where in enumerate(split, 1):
        lines += _item(n, where, wanted[where], a[where], b[where])
    sample = [f"# {batch}: {len(drawn)} agreements drawn at random", "",
              f"Drawn with `random.Random({batch!r})`, so the same each time. Does each verdict "
              "hold?", ""]  # fmt: skip
    for n, entry in enumerate(drawn, 1):
        where = (entry["slug"], entry["report"], entry["index"])
        sample += _item(n, where, wanted[where], a[where], b[where])
    out[0].parent.mkdir(parents=True, exist_ok=True)
    out[0].write_text(json.dumps(agreed, indent=1, ensure_ascii=False), "utf-8")
    out[1].write_text("\n".join(lines), "utf-8")
    out[2].write_text("\n".join(sample), "utf-8")
    unclear = sum("unclear" in (a[w]["verdict"], b[w]["verdict"]) for w in split)
    return {"batch": batch, "findings": len(wanted), "agreed": len(agreed),
            "true": sum(e["verdict"] == "true" for e in agreed), "disagreed": len(split),
            "unclear": unclear, "sample": len(drawn), "paths": [str(p) for p in out]}


def render_agree(result: dict) -> str:
    return (f"## Batch {result['batch']}: two judges\n\n{result['findings']} findings: "
            f"{result['agreed']} agreed ({result['true']} true, "
            f"{result['agreed'] - result['true']} false), {result['disagreed']} for the author "
            f"({result['unclear']} of them unclear to a judge), {result['sample']} agreements "
            f"drawn for him. Wrote {', '.join(result['paths'])}.\n")
