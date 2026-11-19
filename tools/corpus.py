"""Run manuscript-guard over a corpus of real papers whose findings were judged, measure what
became of each judged finding, and gate a change on the true findings it loses.

Run by hand or by a session, never by pytest or CI: the corpus is the user's own, kept outside
the repository, and found through `MANUSCRIPT_GUARD_CORPUS` or `--corpus`.

    python tools/corpus.py run <commit> [--name NAME]   # install that commit, run every paper
    python tools/corpus.py measure <run> [--out F.md] [--json F.json] [--no-ledger]
    python tools/corpus.py gate <base-run> <new-run> [--out F.md] [--json F.json]

The layout of a corpus, and how its findings are judged, are in docs/corpus.md. Every judged
finding is in one of four states in a run: reported (its gate and code, as a warning or a
failure), asked (its gate and code as a note, or a question at its place), elsewhere (another
code's warning or failure at its place, or for G14 about the same short form), or gone. The
ledger, `report/ledger.yaml`, holds the author's decisions that re-judge a finding or name the
findings that took over from one; nothing here writes to it.

The corpus holds downloaded files. `run` is in `tools/corpus_run.py`: every command it runs
has a time limit, none runs with its working folder inside `corpus/`, and the build reads the
papers under `python -I`.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus_run  # noqa: E402 - beside this file, in tools/, which is no package
from corpus_run import CorpusError, load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV = "MANUSCRIPT_GUARD_CORPUS"
REPORTS = ("audit", "audit-pdf", "check", "compare")
STATES = ("reported", "asked", "elsewhere", "gone")
VERDICTS = ("true", "false")
LOUD = frozenset({"warn", "fail", "warning", "error"})
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
#: A short form a G14 finding is about, where its message opens on it.
FORM = re.compile(r"^(?:Language \(G14\): )?(\S+) is (?:used|defined)")
QUOTED = re.compile(
    "[\"'`\N{LEFT DOUBLE QUOTATION MARK}]([^\"'`\N{RIGHT DOUBLE QUOTATION MARK}]{1,40})"
)
ABSOLUTE = re.compile(r"(?:(?<![\w/])[A-Za-z]:/|(?<![\w.:/])/(?=[^\s/]+/))(?:[^\s/:'\"]+/)+")
RUN_DIR = re.compile(r"runs/[^/\s]+/")
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?|\.\d+)")
#: The part of the paper a G14 finding names, which tells two findings of one form apart.
REGION = re.compile(r"\bin the (abstract|main text|supplement)\b", re.IGNORECASE)


# --- the corpus -------------------------------------------------------------------------


def corpus_root(given: str | None) -> Path:
    text = given or os.environ.get(ENV)
    if not text:
        raise CorpusError(f"name the corpus with --corpus or {ENV}")
    root = Path(text).resolve()
    if root.is_relative_to(ROOT):
        raise CorpusError(f"{root} is inside the manuscript-guard checkout: keep the corpus, "
                          "its papers and its runs outside it (docs/corpus.md)")  # fmt: skip
    if not (root / "report").is_dir():
        raise CorpusError(f"{root} has no report/ folder: it is not a corpus (docs/corpus.md)")
    return root


def findings_of(report: object) -> list[dict]:
    if not isinstance(report, dict):
        return []
    if "findings" in report:
        return [f for f in report["findings"] if isinstance(f, dict)]
    return [f for g in report.get("gates", []) for f in g.get("findings", [])]


@dataclass
class Judged:
    slug: str
    report: str
    index: int
    verdict: str
    finding: dict
    judged: str = ""
    rejudged_by: str = ""
    #: The only finding of its gate and code in the judged run's report (the packet's totals).
    alone: bool = False

    @property
    def code(self) -> str:
        return f"{self.finding.get('gate')}/{self.finding.get('code')}"

    @property
    def notice(self) -> bool:
        return self.finding.get("code") in NOTICES

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.slug, self.report, self.index)


def load_judged(root: Path) -> tuple[list[Judged], collections.Counter]:
    """Each verdict with the finding it judged, and a count of those left out, by reason."""
    packets: dict[str, dict] = {}
    for path in sorted((root / "report" / "packets").glob("*.json")):
        for paper in load_json(path) or []:
            packets[paper["slug"]] = paper
    judged, skipped = [], collections.Counter()
    for path in sorted((root / "report" / "judged").glob("*.json")):
        for entry in load_json(path) or []:
            verdict = str(entry.get("verdict")).lower()
            if verdict not in VERDICTS:
                skipped[f"verdict {verdict}"] += 1
                continue
            try:
                paper = packets[entry["slug"]]
                old = paper["reports"][entry["report"]]["findings"][int(entry["index"])]
            except (KeyError, IndexError, TypeError, ValueError):
                skipped["no finding in the packet at its index"] += 1
                continue
            totals = paper["reports"][entry["report"]].get("totals") or {}
            alone = totals.get(f"{old.get('gate')}/{old.get('code')}") == 1
            judged.append(Judged(entry["slug"], entry["report"], int(entry["index"]), verdict,
                                 old, judged=verdict, alone=alone))  # fmt: skip
    if not judged:
        raise CorpusError(f"{root / 'report'} holds no judged finding (docs/corpus.md)")
    return judged, skipped


# --- the ledger -------------------------------------------------------------------------


@dataclass
class Decision:
    id: str
    date: str
    by: str
    what: str
    source: str
    verdict: str = ""
    keys: set = field(default_factory=set)
    matchers: list = field(default_factory=list)
    successor_from: str = ""
    successor_to: tuple = ()

    def rejudges(self, item: Judged) -> bool:
        if item.key in self.keys:
            return True
        return any(_matches(m, item) for m in self.matchers)


MATCHER_KEYS = {"slug", "report", "gate", "code", "message"}


def _matches(matcher: dict, item: Judged) -> bool:
    old = item.finding
    for name in ("slug", "report"):
        if name in matcher and matcher[name] != getattr(item, name):
            return False
    for name in ("gate", "code"):
        if name in matcher and matcher[name] != old.get(name):
            return False
    return "message" not in matcher or bool(re.search(matcher["message"], norm(old.get("message"))))


def _required(entry: dict, name: str, where: str) -> str:
    value = entry.get(name)
    if value is None or str(value).strip() == "":
        raise CorpusError(f"{where}: `{name}` is missing")
    return str(value)


def _verdict(value: object, where: str) -> str:
    text = str(value).lower()
    if text not in VERDICTS:
        raise CorpusError(f"{where}: verdict must be true or false, not {value!r}")
    return text


def _rejudge(decision: Decision, body: object, where: str) -> None:
    if not isinstance(body, dict) or set(body) - {"verdict", "findings", "match"}:
        raise CorpusError(f"{where}: rejudge holds verdict, findings and match only")
    decision.verdict = _verdict(body.get("verdict"), where)
    for key in body.get("findings") or []:
        if not isinstance(key, dict) or set(key) != {"slug", "report", "index"}:
            raise CorpusError(f"{where}: a finding is named by slug, report and index")
        try:
            decision.keys.add((str(key["slug"]), str(key["report"]), int(key["index"])))
        except (TypeError, ValueError):
            raise CorpusError(f"{where}: a finding's index is a number, not {key['index']!r}"
                              ) from None  # fmt: skip
    for matcher in body.get("match") or []:
        if not isinstance(matcher, dict) or not matcher or set(matcher) - MATCHER_KEYS:
            raise CorpusError(f"{where}: a matcher holds {sorted(MATCHER_KEYS)} only")
        try:
            re.compile(str(matcher.get("message", "")))
        except re.error as exc:
            raise CorpusError(f"{where}: its message is no regular expression: {exc}") from None
        decision.matchers.append({k: str(v) for k, v in matcher.items()})
    if not decision.keys and not decision.matchers:
        raise CorpusError(f"{where}: rejudge names no finding")


def _successor(decision: Decision, body: object, where: str) -> None:
    if not isinstance(body, dict) or set(body) != {"from", "to", "scope"}:
        raise CorpusError(f"{where}: successor holds from, to and scope")
    if body["scope"] != "paper":
        raise CorpusError(f"{where}: the one scope a successor has is paper")
    targets = body["to"] if isinstance(body["to"], list) else [body["to"]]
    codes = [str(body["from"]), *map(str, targets)]
    if not targets or any(code.count("/") != 1 for code in codes):
        raise CorpusError(f"{where}: from and to are gate/code")
    decision.successor_from, decision.successor_to = codes[0], tuple(codes[1:])


def load_ledger(path: Path) -> list[Decision]:
    if not path.is_file():
        return []
    try:
        document = yaml.safe_load(path.read_text("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorpusError(f"{path} is not YAML: {exc}") from None
    entries = document.get("decisions") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise CorpusError(f"{path}: the ledger is a list under `decisions`")
    decisions, seen = [], set()
    for number, entry in enumerate(entries, 1):
        where = f"{path.name}, decision {number}"
        if not isinstance(entry, dict):
            raise CorpusError(f"{where} is not a mapping")
        kinds = [k for k in ("rejudge", "successor") if k in entry]
        extra = set(entry) - {"id", "date", "by", "what", "source", "rejudge", "successor"}
        if len(kinds) != 1 or extra:
            raise CorpusError(f"{where}: one of rejudge or successor, and no other key")
        decision = Decision(*(_required(entry, k, where) for k in ("id", "date", "by", "what",
                                                                     "source")))  # fmt: skip
        if decision.id in seen:
            raise CorpusError(f"{where}: the id {decision.id} is used twice")
        seen.add(decision.id)
        (_rejudge if kinds[0] == "rejudge" else _successor)(decision, entry[kinds[0]], where)
        decisions.append(decision)
    return decisions


def rejudged(judged: list[Judged], decisions: list[Decision]) -> list[Judged]:
    """The verdicts with the ledger's re-judgements applied; the last decision wins."""
    out = []
    for item in judged:
        new = replace(item, verdict=item.judged, rejudged_by="")
        for decision in decisions:
            if decision.verdict and decision.rejudges(item):
                new.verdict, new.rejudged_by = decision.verdict, decision.id
        out.append(new)
    return out


# --- the four states --------------------------------------------------------------------


def norm(text: object) -> str:
    """A message without the folders a run was made in, which differ from run to run."""
    plain = str(text or "").replace("\\", "/")
    return RUN_DIR.sub("runs/", ABSOLUTE.sub("", plain))


def form_of(finding: dict) -> str | None:
    hit = FORM.match(str(finding.get("message") or ""))
    return hit.group(1) if hit else None


def forms_named(finding: dict) -> set[str]:
    named = {f.get("form") for f in finding.get("forms") or [] if isinstance(f, dict)}
    return {*named, form_of(finding)} - {None}


def loud(finding: dict) -> bool:
    return str(finding.get("severity")).lower() in LOUD


def is_question(finding: dict) -> bool:
    if finding.get("question") is True or str(finding.get("code", "")).startswith("question"):
        return True
    return str(finding.get("severity")).lower() == "info" and "?" in str(finding.get("message"))


def relative(path: object, slug: str) -> str | None:
    """A finding's file as a path inside the paper's folder or its project, wherever the run
    was made; None where the finding names no file."""
    if not path:
        return None
    text = str(path).replace("\\", "/")
    for marker in (f"/{slug}/project/", f"/{slug}/files/"):
        if slug and marker in text:
            return text.rsplit(marker, 1)[1]
    return text.removeprefix("./")


def same_place(old: dict, new: dict, slug: str = "") -> bool:
    """The same line of the same file; a finding that names no file is at the place of one
    that names none."""
    line = old.get("line")
    if line is None or new.get("line") != line:
        return False
    return relative(old.get("path"), slug) == relative(new.get("path"), slug)


def key_of(old: dict) -> re.Pattern | None:
    """What a finding is about, to be found in another's message: its short form, else its
    first quoted words, else its first number of two characters or more (a single digit, a
    degree of freedom or a count of two, stands in too many messages to tell one apart)."""
    message = str(old.get("message") or "")
    word = form_of(old) or next(iter(QUOTED.findall(message)), None)
    if word:
        return re.compile(rf"(?<!\w){re.escape(word)}(?!\w)")
    number = next((n for n in NUMBER.findall(message) if len(n) >= 2), None)
    return re.compile(rf"(?<![\w.]){re.escape(number)}(?![\w]|\.\d)") if number else None


def region(message: object) -> str | None:
    hit = REGION.search(str(message or ""))
    return hit.group(1).lower() if hit else None


def _same_code(old: dict, new: dict) -> bool:
    return new.get("gate") == old.get("gate") and new.get("code") == old.get("code")


def _by_message(old: dict, new: dict, slug: str, place: bool) -> bool:
    return norm(new.get("message")) == norm(old.get("message")) and (
        not place or same_place(old, new, slug))


def _by_context(old: dict, new: dict, slug: str, place: bool) -> bool:
    context = norm(old.get("context"))
    return bool(context) and norm(new.get("context")) == context and (
        not place or same_place(old, new, slug))


def _about(old: dict, new: dict, slug: str, form: bool = False) -> bool:
    """The same word, at the same place or in the same part of the paper. A form a finding
    lists stands for that form in the part its message names, or in the paper where neither
    names one."""
    key = key_of(old)
    if key is None or not key.search(str(new.get("message") or "")):
        return False
    part = region(old.get("message"))
    return same_place(old, new, slug) or ((form or part is not None)
                                          and part == region(new.get("message")))


def subject_of(old: dict) -> str | None:
    """The short form or the quoted name a finding is about, as a question's `forms` give it."""
    return form_of(old) or next(iter(QUOTED.findall(str(old.get("message") or ""))), None)


def _entry(finding: dict, entry: dict) -> dict:
    """One form of a finding that lists several, with its own place and message."""
    return {**finding, **{k: entry[k] for k in ("line", "path", "message") if k in entry}}


def match(olds: list[dict], new: list[dict], slug: str = "",
          alone: frozenset[int] = frozenset()) -> dict[int, tuple[int, bool]]:  # fmt: skip
    """Each old finding's own finding among a report's new ones, one to one: for every old
    one first the same message at the same place, then the same message, then the same
    context at the same place, then the same context, then the same word at the same place
    or in the same part of the paper; a finding taken by one is not taken by another. A
    finding that lists forms gives each form once. An old finding that was the only one of
    its code in its report (`alone`) is the only one of its code in the new report too, where
    that names its word. Says (new index, whether by a form)."""
    taken: set[tuple] = set()
    found: dict[int, tuple[int, bool]] = {}

    def token(i: int, old: dict) -> tuple:
        return (i, "whole", subject_of(old)) if new[i].get("forms") else (i,)

    def free(i: int, old: dict) -> bool:
        return (i,) not in taken and token(i, old) not in taken

    def take(k: int, i: int, old: dict, entry: int | None = None) -> None:
        found[k] = (i, entry is not None)
        taken.add(token(i, old) if entry is None else (i, "form", entry))

    passes = [lambda o, f: _by_message(o, f, slug, True),
              lambda o, f: _by_message(o, f, slug, False),
              lambda o, f: _by_context(o, f, slug, True),
              lambda o, f: _by_context(o, f, slug, False)]  # fmt: skip
    for test in passes:
        for k, old in enumerate(olds):
            if k not in found:
                i = next((i for i, f in enumerate(new) if _same_code(old, f) and free(i, old)
                          and test(old, f)), None)  # fmt: skip
                if i is not None:
                    take(k, i, old)
    for k, old in enumerate(olds):
        for i, f in enumerate(new):
            if k in found or not _same_code(old, f) or not free(i, old):
                continue
            entries = [e for e in f.get("forms") or [] if isinstance(e, dict)]
            single = k in alone and sum(_same_code(old, g) for g in new) == 1 and bool(
                (key := key_of(old)) and key.search(str(f.get("message") or "")))
            if not entries and (single or _about(old, f, slug)):
                take(k, i, old)
            j = next((j for j, e in enumerate(entries) if (i, "form", j) not in taken
                      and e.get("form") == subject_of(old)
                      and _about(old, _entry(f, e), slug, True)), None)  # fmt: skip
            if k not in found and j is not None:
                take(k, i, old, j)
    return found


def states(olds: list[dict], new: list[dict], slug: str = "",
           alone: frozenset[int] = frozenset()) -> list[tuple[str, list[int]]]:  # fmt: skip
    """Each judged finding's state among a report's findings, and the findings that make it
    so. A question or a warning at its place counts only where it names what the old one
    was about (`key_of`)."""
    matched = match(olds, new, slug, alone)
    out = []
    for k, old in enumerate(olds):
        if k in matched:
            i = matched[k][0]
            quiet = new[i].get("question") or not loud(new[i])
            out.append(("asked" if quiet else "reported", [i]))
            continue
        key = key_of(old)
        here = [i for i, f in enumerate(new) if key and same_place(old, f, slug)
                and key.search(str(f.get("message") or ""))]  # fmt: skip
        asked = [i for i in here if is_question(new[i])]
        louder = [i for i in here if loud(new[i])]
        form = form_of(old) if old.get("gate") == "G14" else None
        about = [i for i, f in enumerate(new) if form and f.get("gate") == "G14"
                 and f.get("code") != old.get("code") and form in forms_named(f)]
        if asked:
            out.append(("asked", asked))
        elif louder:
            out.append(("elsewhere", louder))
        elif [i for i in about if loud(new[i])]:
            out.append(("elsewhere", [i for i in about if loud(new[i])]))
        elif about:
            out.append(("asked", about))
        else:
            out.append(("gone", []))
    return out


def state(old: dict, new: list[dict], slug: str = "") -> tuple[str, list[int]]:
    """One judged finding's state among a report's findings (`states`)."""
    return states([old], new, slug)[0]


@dataclass
class Fate:
    item: Judged
    state: str
    successor_by: str = ""
    missing: bool = False


def run_folder(root: Path, run: str) -> Path:
    folder = Path(run) if Path(run).is_absolute() else root / "runs" / run
    if not folder.is_dir():
        raise CorpusError(f"no run {run}: {folder} is not a folder")
    return folder


class Run:
    """A run's reports, read once each."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.name = folder.name
        self._reports: dict[tuple[str, str], list[dict] | None] = {}
        self.used: dict[tuple[str, str], set[int]] = collections.defaultdict(set)

    def findings(self, slug: str, report: str) -> list[dict] | None:
        key = (slug, report)
        if key not in self._reports:
            data = load_json(self.folder / slug / f"{report}.json")
            self._reports[key] = findings_of(data) if isinstance(data, dict) else None
        return self._reports[key]

    def all_reports(self):
        for paper in sorted(p for p in self.folder.iterdir() if p.is_dir()):
            for report in REPORTS:
                found = self.findings(paper.name, report)
                if found is not None:
                    yield paper.name, report, found


def fates(judged: list[Judged], run: Run, decisions: list[Decision]) -> list[Fate]:
    successors = [d for d in decisions if d.successor_from]
    groups: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
    for n, item in enumerate(judged):
        groups[(item.slug, item.report)].append(n)
    found_of: dict[int, tuple[str, list[int]]] = {}
    for (slug, report), members in groups.items():
        alone = frozenset(k for k, n in enumerate(members) if judged[n].alone)
        said = states([judged[n].finding for n in members], run.findings(slug, report) or [],
                      slug, alone)  # fmt: skip
        found_of.update(zip(members, said, strict=True))
    out = []
    for n, item in enumerate(judged):
        new = run.findings(item.slug, item.report)
        found, used = found_of[n]
        fate = Fate(item, found, missing=new is None)
        run.used[(item.slug, item.report)].update(used)
        if found == "gone" and new:
            for decision in successors:
                if decision.successor_from == item.code:
                    hit = [i for i, f in enumerate(new)
                           if f"{f.get('gate')}/{f.get('code')}" in decision.successor_to]
                    if hit:
                        fate.state, fate.successor_by = "asked", decision.id
                        run.used[(item.slug, item.report)].update(hit)
                        break
        out.append(fate)
    return out


def unjudged(run: Run) -> collections.Counter:
    """Warnings and failures in a run that no judged finding accounts for, by code."""
    counts = collections.Counter()
    for slug, report, found in run.all_reports():
        used = run.used.get((slug, report), set())
        for i, f in enumerate(found):
            if i not in used and loud(f):
                counts[f"{f.get('gate')}/{f.get('code')}"] += 1
    return counts


# --- measure ----------------------------------------------------------------------------


def _row(fate: Fate) -> dict:
    item = fate.item
    return {"slug": item.slug, "report": item.report, "index": item.index, "code": item.code,
            "verdict": item.verdict, "judged": item.judged, "rejudged_by": item.rejudged_by,
            "notice": item.notice, "state": fate.state, "successor_by": fate.successor_by,
            "report_missing": fate.missing,
            "message": norm(item.finding.get("message"))[:160]}  # fmt: skip


def _table(rows: list[dict]) -> dict:
    return {v: {s: sum(1 for r in rows if r["verdict"] == v and r["state"] == s) for s in STATES}
            for v in VERDICTS}  # fmt: skip


def _precision(table: dict, states: tuple[str, ...]) -> float | None:
    true = sum(table["true"][s] for s in states)
    total = true + sum(table["false"][s] for s in states)
    return round(true / total, 3) if total else None


def measure(root: Path, run_name: str, ledger: bool = True) -> dict:
    judged, skipped = load_judged(root)
    path = root / "report" / "ledger.yaml"
    decisions = load_ledger(path) if ledger else []
    run = Run(run_folder(root, run_name))
    rows = [_row(f) for f in fates(rejudged(judged, decisions), run, decisions)]
    codes = {}
    for code in sorted({r["code"] for r in rows}):
        table = _table([r for r in rows if r["code"] == code])
        codes[code] = {"notice": code.split("/", 1)[1] in NOTICES, **table,
                       "precision_reported": _precision(table, ("reported",))}  # fmt: skip
    papers, notices = [r for r in rows if not r["notice"]], [r for r in rows if r["notice"]]
    return {
        "run": run.name, "ledger": str(path) if decisions else None,
        "decisions": [{"id": d.id, "matched": sum(r["rejudged_by"] == d.id for r in rows),
                       "changed": sum(r["rejudged_by"] == d.id and r["judged"] != r["verdict"]
                                      for r in rows),
                       "successor": sum(r["successor_by"] == d.id for r in rows)}
                      for d in decisions],
        "skipped": dict(skipped), "totals": _table(rows), "paper": _table(papers),
        "notices": _table(notices),
        "precision_loud": _precision(_table(papers), ("reported", "elsewhere")),
        "codes": codes, "findings": rows,
    }  # fmt: skip


def _counts(title: str, table: dict) -> list[str]:
    head = ["| " + title + " | " + " | ".join(STATES) + " | all |",
            "| --- |" + " ---: |" * (len(STATES) + 1)]
    return head + [f"| {v} | " + " | ".join(str(table[v][s]) for s in STATES)
                   + f" | {sum(table[v].values())} |" for v in VERDICTS]  # fmt: skip


def _line(row: dict) -> str:
    extra = " (no report in this run)" if row["report_missing"] else ""
    by = f" [re-judged {row['judged']} -> {row['verdict']}: {row['rejudged_by']}]" \
        if row["rejudged_by"] else ""  # fmt: skip
    return f"- {row['slug']} {row['report']} {row['code']}: {row['message']}{extra}{by}"


def render_measure(result: dict) -> str:
    rows = result["findings"]
    rejudged_n = sum(1 for r in rows if r["rejudged_by"])
    asked_n = sum(1 for r in rows if r["successor_by"])
    lines = [f"# Judged findings in {result['run']}", "",
             f"{len(rows)} judged findings. Left out: {result['skipped'] or 'none'}. Ledger: "
             + (f"{len(result['decisions'])} decisions, {rejudged_n} findings re-judged, "
                f"{asked_n} asked by a successor." if result["ledger"] else "not applied."),
             "", *_counts("verdict", result["totals"]), "",
             "About the paper (reading notices apart):", "", *_counts("verdict", result["paper"]),
             "", "Reading notices:", "", *_counts("verdict", result["notices"]), "",
             f"Precision of the paper findings still loud (reported or elsewhere): "
             f"{result['precision_loud']}.", "", "## By code", "",
             "| code | T reported | T asked | T elsewhere | T gone | F reported | F asked "
             "| F elsewhere | F gone | precision reported |",
             "| --- |" + " ---: |" * 9]  # fmt: skip
    order = sorted(result["codes"].items(), key=lambda kv: -sum(
        sum(kv[1][v].values()) for v in VERDICTS))
    for code, c in order:
        mark = " (notice)" if c["notice"] else ""
        cells = " | ".join(str(c[v][s]) for v in VERDICTS for s in STATES)
        precision = "-" if c["precision_reported"] is None else c["precision_reported"]
        lines.append(f"| {code}{mark} | {cells} | {precision} |")

    def by_code(row: dict) -> tuple[str, str]:
        return row["code"], row["slug"]

    gone = [r for r in rows if r["verdict"] == "true" and r["state"] == "gone"]
    for title, part in (("about the paper", [r for r in gone if not r["notice"]]),
                        ("reading notices", [r for r in gone if r["notice"]])):
        lines += ["", f"## True findings gone, {title} ({len(part)})", ""]
        lines += [_line(r) for r in sorted(part, key=by_code)]
    still = [r for r in rows if r["verdict"] == "false" and r["state"] in ("reported", "elsewhere")]
    lines += ["", f"## False findings still loud ({len(still)})", ""]
    lines += [_line(r) + f" ({r['state']})" for r in sorted(still, key=by_code)]
    return "\n".join(lines) + "\n"


# --- gate -------------------------------------------------------------------------------

KEPT = ("reported", "asked", "elsewhere")
QUIET = ("asked", "gone")
#: A list longer than this, other than the losses, is folded in the Markdown, for a PR body.
FOLD = 10


def gate(root: Path, base_name: str, new_name: str) -> dict:
    judged, skipped = load_judged(root)
    decisions = load_ledger(root / "report" / "ledger.yaml")
    items = rejudged(judged, decisions)
    base, new = Run(run_folder(root, base_name)), Run(run_folder(root, new_name))
    pairs = list(zip(fates(items, base, decisions), fates(items, new, decisions), strict=True))

    def rows(test) -> list[dict]:
        return [{**_row(n), "base": b.state} for b, n in pairs if test(b, n)]

    lost = rows(lambda b, n: n.item.verdict == "true" and not n.item.notice
                and b.state in KEPT and n.state == "gone")
    base_loud, new_loud = unjudged(base), unjudged(new)
    return {
        "base": base.name, "new": new.name, "ok": not lost, "skipped": dict(skipped),
        "decisions": len(decisions),
        "totals": {"base": _table([_row(b) for b, _ in pairs]),
                   "new": _table([_row(n) for _, n in pairs])},
        "lost": lost,
        "recovered": rows(lambda b, n: n.item.verdict == "true" and not n.item.notice
                          and b.state == "gone" and n.state in KEPT),
        "quieter": rows(lambda b, n: n.item.verdict == "true" and b.state == "reported"
                        and n.state == "asked"),
        "notices": rows(lambda b, n: n.item.notice and b.state != n.state),
        "false_loud": rows(lambda b, n: n.item.verdict == "false" and b.state in QUIET
                           and n.state not in QUIET),
        "unjudged": {code: {"base": base_loud[code], "new": new_loud[code]}
                     for code in sorted(set(base_loud) | set(new_loud))},
    }  # fmt: skip


def render_gate(result: dict) -> str:
    verdict = ("**Passes**: no true finding about the paper is lost." if result["ok"] else
               f"**Fails**: {len(result['lost'])} true findings about the paper are kept in "
               f"{result['base']} and gone in {result['new']}, and no decision of the ledger "
               "covers them.")  # fmt: skip
    lines = [f"## Corpus gate: {result['base']} -> {result['new']}", "", verdict, "",
             f"Ledger applied: {result['decisions']} decisions. Judged findings left out: "
             f"{result['skipped'] or 'none'}.", "",
             "| verdict | run | " + " | ".join(STATES) + " |", "| --- | --- |" + " ---: |" * 4]
    for v in VERDICTS:
        for side in ("base", "new"):
            lines.append(f"| {v} | {result[side]} | "
                         + " | ".join(str(result["totals"][side][v][s]) for s in STATES) + " |")
    sections = (("True findings lost (these block)", "lost"),
                ("True findings about the paper back", "recovered"),
                ("True findings reported before, asked now", "quieter"),
                ("Reading notices that changed", "notices"),
                ("False findings now loud", "false_loud"))  # fmt: skip
    for title, key in sections:
        part = result[key]
        lines += ["", f"### {title} ({len(part)})", ""]
        listed = [_line(r) + f" ({r['base']} -> {r['state']})" for r in part] or ["None."]
        if len(part) > FOLD and key != "lost":
            listed = ["<details><summary>The list</summary>", "", *listed, "", "</details>"]
        lines += listed
    changed = {c: n for c, n in result["unjudged"].items() if n["base"] != n["new"]}
    lines += ["", "### Warnings and failures no judged finding accounts for", "",
              f"In all: {sum(n['base'] for n in result['unjudged'].values())} -> "
              f"{sum(n['new'] for n in result['unjudged'].values())}. By code, where it changed:",
              "", "| code | base | new |", "| --- | ---: | ---: |"]
    lines += [f"| {c} | {n['base']} | {n['new']} |" for c, n in changed.items()] or ["| none | | |"]
    return "\n".join(lines) + "\n"


# --- the command line -------------------------------------------------------------------


def _outside_the_checkout(*paths: str | None) -> None:
    """The reports quote the corpus's papers, which are not this repository's to publish: a
    file of them inside the checkout is one `git add` from a commit, so none is written."""
    for path in filter(None, paths):
        if Path(path).resolve().is_relative_to(ROOT):
            raise CorpusError(f"{path} is inside the manuscript-guard checkout, and what it "
                              "would hold quotes the corpus's papers: write it in the corpus "
                              "folder (its runs/ is ignored by git) or elsewhere")  # fmt: skip


def _write(text: str, data: dict, out: str | None, as_json: str | None) -> None:
    _outside_the_checkout(out, as_json)
    if out:
        Path(out).write_text(text, "utf-8")
    else:
        sys.stdout.write(text)
    if as_json:
        Path(as_json).write_text(json.dumps(data, indent=1, ensure_ascii=False), "utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="corpus.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus", help=f"the corpus folder (default: ${ENV})")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="install a commit and run the reports on every paper")
    p_run.add_argument("commit")
    p_run.add_argument("--name", help="the run's folder under runs/ (default: the sha's 9)")
    p_run.add_argument("--repo", default=str(ROOT), help="the git checkout to build from")
    p_run.add_argument("--jobs", type=int, default=4)
    p_run.add_argument("--only", nargs="*", help="these papers' slugs only")
    p_measure = sub.add_parser("measure", help="the four states of every judged finding")
    p_measure.add_argument("run")
    p_measure.add_argument("--no-ledger", action="store_true")
    p_gate = sub.add_parser("gate", help="fail on true findings kept at base and gone at new")
    p_gate.add_argument("base")
    p_gate.add_argument("new")
    for p in (p_measure, p_gate):
        p.add_argument("--out", help="write the Markdown here, not to standard output")
        p.add_argument("--json", help="write the same as JSON here")
    args = parser.parse_args(argv)
    try:
        root = corpus_root(args.corpus)
        if args.command == "run":
            corpus_run.run(root, args.commit, args.name, Path(args.repo), args.jobs, args.only)
            return 0
        if args.command == "measure":
            result = measure(root, args.run, ledger=not args.no_ledger)
            _write(render_measure(result), result, args.out, args.json)
            return 0
        result = gate(root, args.base, args.new)
        _write(render_gate(result), result, args.out, args.json)
        return 0 if result["ok"] else 1
    except CorpusError as exc:
        print(f"corpus.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
