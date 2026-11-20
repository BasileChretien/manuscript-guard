"""Run manuscript-guard over a corpus of real papers whose findings were judged, measure what
became of each judged finding, and gate a change on the true findings it loses.

Run by hand or by a session, never by pytest or CI: the corpus is the user's own, kept outside
the repository, and found through `MANUSCRIPT_GUARD_CORPUS` or `--corpus`.

    python tools/corpus.py run <commit> [--name NAME]   # install that commit, run every paper
    python tools/corpus.py measure <run> [--out F.md] [--json F.json] [--no-ledger]
    python tools/corpus.py gate <base-run> <new-run> [--out F.md] [--json F.json]
    python tools/corpus.py tie <judged-run> <keyed-run>   # once: report/ties.yaml
    python tools/corpus.py unjudged <run> --name BATCH [--base RUN]   # a packet for two judges
    python tools/corpus.py agree <batch>   # the two judges' verdicts side by side

The layout of a corpus, and how its findings are judged, are in docs/corpus.md. Every judged
finding is in one of four states in a run: reported (its gate and code, as a warning or a
failure), asked (its gate and code as a note, or a question at its place), elsewhere (another
code's warning or failure at its place, or for G14 about the same short form), or gone. The
ledger, `report/ledger.yaml`, holds the author's decisions that re-judge a finding or name the
findings that took over from one; nothing here writes to it.

The corpus holds downloaded files. `run` is in `tools/corpus_run.py`: every command it runs
has a time limit, none runs with its working folder inside `corpus/`, and the build reads the
papers under `python -I`. The matching of the four states is in `tools/corpus_match.py`,
and the pairing by the key every finding carries from #706 on, with `tie`, in
`tools/corpus_keys.py`; the packing of the findings with no verdict for two judges, and
the reading of their verdicts, in `tools/corpus_judging.py`.
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
import corpus_judging  # noqa: E402 - beside this file, in tools/, which is no package
import corpus_keys  # noqa: E402
import corpus_match  # noqa: E402,F401 - the matching, which the tests reach through this
import corpus_run  # noqa: E402
from corpus_judging import NOTICES, Judged, load_judged  # noqa: E402
from corpus_match import (  # noqa: E402
    loud,
    norm,
    states,
)
from corpus_run import CorpusError, checkouts, in_a_checkout, load_json  # noqa: E402,F401

ROOT = Path(__file__).resolve().parent.parent
ENV = "MANUSCRIPT_GUARD_CORPUS"
REPORTS = ("audit", "audit-pdf", "check", "compare")
STATES = ("reported", "asked", "elsewhere", "gone")
VERDICTS = ("true", "false")
# --- the corpus -------------------------------------------------------------------------


def corpus_root(given: str | None) -> Path:
    text = given or os.environ.get(ENV)
    if not text:
        raise CorpusError(f"name the corpus with --corpus or {ENV}")
    root = Path(text).resolve()
    if in_a_checkout(root):
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


@dataclass
class Fate:
    item: Judged
    state: str
    successor_by: str = ""
    missing: bool = False
    #: Paired by its key (`tools/corpus_keys.py`), by one from its context, under a key
    #: repeated in either run, whose count fell.
    by_key: bool = False
    fallback: bool = False
    repeated: bool = False
    fell: bool = False


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

    @property
    def keyed(self) -> bool:
        """Whether the run's findings carry keys, as every build from #706 on gives them."""
        if not hasattr(self, "_keyed"):
            self._keyed = any(corpus_keys.keyed(found) for _s, _r, found in self.all_reports())
        return self._keyed

    @property
    def scheme(self) -> int:
        """The scheme of the run's keys, as `run` recorded it (`corpus_run.scheme_of`); 1,
        the scheme of every key before #709, where it recorded none, as no run did before
        the scheme was read, and git is not asked."""
        made = load_json(self.folder / "run.json")
        scheme = made.get("scheme") if isinstance(made, dict) else None
        return scheme if isinstance(scheme, int) else 1

    def keys(self, slug: str, report: str) -> corpus_keys.Keys:
        return corpus_keys.Keys(self.findings(slug, report) or [])

    def all_reports(self):
        for paper in sorted(p for p in self.folder.iterdir() if p.is_dir()):
            for report in REPORTS:
                found = self.findings(paper.name, report)
                if found is not None:
                    yield paper.name, report, found


def _by_key(item: Judged, tie: corpus_keys.Tie, run: Run, base: Run,
            successors: list[Decision]) -> tuple[Fate, list[int]]:  # fmt: skip
    """A judged finding's fate by its key in `run`, its count held to the one in `base`; by
    its key family's count where it is tied to a family; gone where the author decided no
    keyed finding is it."""
    missing = run.findings(item.slug, item.report) is None
    if tie.key is None:
        return Fate(item, "gone", missing=missing, by_key=True), []
    key, new = tie.key, run.keys(item.slug, item.report)
    codes = tuple(c for d in successors if d.successor_from == item.code for c in d.successor_to)
    held = base.keys(item.slug, item.report).count(key, family=tie.family)
    state = corpus_keys.family_state if tie.family else corpus_keys.key_state
    said = state(key, new, held, codes)
    fate = Fate(item, said.state, missing=missing, by_key=True,
                fallback=corpus_keys.from_context(key), repeated=said.repeated,
                fell=said.fell)  # fmt: skip
    if said.state == "elsewhere" and codes and said.used and all(
            f"{run.findings(item.slug, item.report)[i].get('gate')}/"
            f"{run.findings(item.slug, item.report)[i].get('code')}" in codes
            for i in said.used):  # fmt: skip
        fate.successor_by = next(d.id for d in successors if d.successor_from == item.code)
    return fate, said.used


def fates(judged: list[Judged], run: Run, decisions: list[Decision],
          keyed: tuple[dict, Run] | None = None, held: Run | None = None) -> list[Fate]:
    """Each judged finding's fate in `run`. With `keyed`, the ties and the run its counts are
    held to, a tied finding is paired by its key alone and the rest by #705's matcher, among
    the findings no key took; without, all by the matcher, as #705 had it. A batch's verdict
    is paired by its finding's key where `run` keys by its packet's scheme, its count held to
    `held` where that keys so too and to the batch's run otherwise, and by the matcher where
    not; the first verdicts are paired first, so that no batch changes their fates."""
    successors = [d for d in decisions if d.successor_from]
    ties, base = keyed if keyed is not None and run.keyed else ({}, run)
    scheme = run.scheme if run.keyed else None
    held_scheme = held.scheme if held is not None and held.keyed else None
    sources: dict[Path, Run] = {}

    def tie_of(item: Judged) -> tuple[corpus_keys.Tie | None, Run]:
        if not item.batch:
            return ties.get(item.key), base
        key = item.finding.get("key")
        counts = held if held_scheme == item.scheme else (
            sources.setdefault(item.source, Run(item.source)) if item.source else run)
        return (corpus_keys.Tie(key) if scheme == item.scheme and isinstance(key, str)
                else None), counts  # fmt: skip

    groups: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
    for n, item in enumerate(judged):
        groups[(item.slug, item.report)].append(n)
    found_of: dict[int, tuple[str, list[int]]] = {}
    by_key: dict[int, Fate] = {}
    for (slug, report), members in groups.items():
        new = run.findings(slug, report) or []
        taken: set[int] = set()
        for part in ([n for n in members if not judged[n].batch],
                     [n for n in members if judged[n].batch]):  # fmt: skip
            for n in part:
                tie, counts = tie_of(judged[n])
                if tie is not None:
                    by_key[n], used = _by_key(judged[n], tie, run, counts, successors)
                    # A finding that lists forms stays for the matcher: its other forms are
                    # other judged findings'.
                    taken.update(i for i in used if not new[i].get("forms"))
                    run.used[(slug, report)].update(used)
            rest = [n for n in part if n not in by_key]
            left = [i for i in range(len(new)) if i not in taken]
            alone = frozenset(k for k, n in enumerate(rest) if judged[n].alone)
            said = states([judged[n].finding for n in rest], [new[i] for i in left], slug, alone)
            for n, (state, used) in zip(rest, said, strict=True):
                found_of[n] = (state, [left[i] for i in used])
                taken.update(found_of[n][1])
    out = []
    for n, item in enumerate(judged):
        if n in by_key:
            out.append(by_key[n])
            continue
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
            "report_missing": fate.missing, "by_key": fate.by_key, "fallback": fate.fallback,
            "repeated": fate.repeated, "fell": fate.fell, "batch": item.batch,
            "message": norm(item.finding.get("message"))[:160]}  # fmt: skip


def _key_counts(rows: list[dict]) -> dict:
    return {"by_key": sum(r["by_key"] for r in rows), "fallback": sum(r["fallback"] for r in rows),
            "repeated": sum(r["repeated"] for r in rows), "fell": sum(r["fell"] for r in rows),
            "by_matcher": sum(not r["by_key"] for r in rows)}  # fmt: skip


def _key_line(keys: dict) -> str:
    return (f"Paired by key: {keys['by_key']} ({keys['fallback']} by a key from the context, "
            f"{keys['repeated']} under a key repeated in either run, {keys['fell']} of them "
            f"whose count fell); by #705's matcher: {keys['by_matcher']}.")


def keyed_against(root: Path, *runs: Run) -> tuple[dict, Run] | str | None:
    """The ties, the author's decided ones over them, and the run they were made in, where
    every run carries keys of the ties' scheme; None, for #705's matcher, where one carries
    none or the corpus has no ties; and what to say, for the matcher too, where one keys by
    another scheme."""
    if not all(run.keyed for run in runs):
        return None
    ties = corpus_keys.load_ties(root)
    if ties is None:
        return None
    tied_scheme, schemes = ties["scheme"], [run.scheme for run in runs]
    if len({tied_scheme, *schemes}) > 1:
        return corpus_keys.scheme_note(tied_scheme, schemes)
    tied = Run(run_folder(root, ties["run"]))
    return {**ties["ties"], **decided(root, tied)}, tied


def decided(root: Path, tied: Run) -> dict:
    """`report/ties-decided.yaml`, each decision checked against the judged set and the run
    of the ties (`corpus_keys.check_decided`)."""
    judged = {item.key for item in load_judged(root)[0]}
    return corpus_keys.check_decided(corpus_keys.load_decided(root), judged, tied.name,
                                     lambda slug, report: tied.keys(slug, report))  # fmt: skip


def _table(rows: list[dict]) -> dict:
    return {v: {s: sum(1 for r in rows if r["verdict"] == v and r["state"] == s) for s in STATES}
            for v in VERDICTS}  # fmt: skip


def _precision(table: dict, states: tuple[str, ...]) -> float | None:
    true = sum(table["true"][s] for s in states)
    total = true + sum(table["false"][s] for s in states)
    return round(true / total, 3) if total else None


def measure(root: Path, run_name: str, ledger: bool = True, run: Run | None = None) -> dict:
    judged, skipped = load_judged(root)
    path = root / "report" / "ledger.yaml"
    decisions = load_ledger(path) if ledger else []
    run = run or Run(run_folder(root, run_name))
    against = keyed_against(root, run)
    keyed = against if isinstance(against, tuple) else None
    rows = [_row(f) for f in fates(rejudged(judged, decisions), run, decisions, keyed)]
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
        "codes": codes, "findings": rows, "keys": _key_counts(rows),
        "scheme_note": against if isinstance(against, str) else None,
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
                f"{asked_n} kept by a successor (asked by message, elsewhere by key)."
                if result["ledger"] else "not applied."),
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
    if result.get("scheme_note"):
        lines += ["", f"**Note**: {result['scheme_note']}."]
    if result["keys"]["by_key"]:
        lines += ["", "## Pairing by key", "", _key_line(result["keys"])]
        for title, test in (("Under a key repeated in either run", "repeated"),
                            ("Paired by a key from the context", "fallback")):
            part = [r for r in rows if r[test]]
            lines += ["", f"### {title} ({len(part)})", ""]
            lines += [_line(r) + f" ({r['state']}{', its count fell' if r['fell'] else ''})"
                      for r in sorted(part, key=by_code)]  # fmt: skip
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
    # By key where both runs carry keys, the base's counts held to the run of the ties and
    # the new run's to the base's; by #705's matcher, both of them, otherwise.
    against = keyed_against(root, base, new)
    ties = against if isinstance(against, tuple) else None
    pairs = list(zip(fates(items, base, decisions, ties),
                     fates(items, new, decisions, ties and (ties[0], base), base), strict=True))

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
        "keys": _key_counts([_row(n) for _, n in pairs]),
        "scheme_note": against if isinstance(against, str) else None,
        "repeated": rows(lambda b, n: n.repeated or b.repeated),
        "fallback": rows(lambda b, n: n.fallback), "fresh": corpus_judging.fresh(new, base),
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
    if result["keys"]["by_key"]:
        lines += ["", _key_line(result["keys"])]
    if result.get("scheme_note"):
        lines += ["", f"**Note**: {result['scheme_note']}."]
    sections = (("True findings lost (these block)", "lost"),
                ("True findings about the paper back", "recovered"),
                ("True findings reported before, asked now", "quieter"),
                ("Reading notices that changed", "notices"),
                ("False findings now loud", "false_loud"),
                ("Judged findings under a key repeated in either run", "repeated"),
                ("Judged findings paired by a key from the context", "fallback"))  # fmt: skip
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
    return "\n".join(lines + corpus_judging.render_fresh(result["fresh"])) + "\n"


# --- tie -------------------------------------------------------------------------------


def tie(root: Path, judged_run: str, keyed_run: str) -> dict:
    """Tie each judged finding to its key in a keyed run of the same papers, once: where
    #705's matcher pairs it one to one by the same message or context at its place
    (`corpus_keys.tie_group`). Writes `report/ties.yaml` and, for the author to settle by
    hand, `report/ties-ambiguous.md`. The verdicts and the ledger are not touched."""
    judged = [item for item in load_judged(root)[0] if not item.batch]  # a batch's are keyed
    run_folder(root, judged_run)
    run = Run(run_folder(root, keyed_run))
    if not run.keyed:
        raise CorpusError(f"{keyed_run} carries no keys: tie to a run of a build from #706 on")
    groups: dict[tuple[str, str], list[Judged]] = collections.defaultdict(list)
    for item in judged:
        groups[(item.slug, item.report)].append(item)
    ties, ambiguous = [], []
    before = Run(run_folder(root, judged_run))
    for (slug, report), members in groups.items():
        alone = frozenset(k for k, item in enumerate(members) if item.alone)
        said = corpus_keys.tie_group([item.finding for item in members],
                                     run.findings(slug, report) or [], slug, alone,
                                     before.findings(slug, report),
                                     [item.verdict for item in members])  # fmt: skip
        for item, (kind, how, candidates) in zip(members, said, strict=True):
            where = {"slug": slug, "report": report, "index": item.index}
            if kind == "tie":
                family = {"family": True} if how == "key family" else {}
                ties.append({**where, "key": candidates[0]["key"], "how": how, **family})
            else:
                ambiguous.append({**where, "kind": kind, "how": how, "verdict": item.verdict,
                                  "code": item.code, "candidates": candidates[:5],
                                  "message": norm(item.finding.get("message"))[:200]})
    document = {"judged_run": judged_run, "run": keyed_run, "scheme": run.scheme, "ties": ties}
    (root / corpus_keys.TIES).write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100), "utf-8")
    (root / corpus_keys.AMBIGUOUS).write_text(
        corpus_keys.render_ambiguous(ambiguous, judged_run, keyed_run), "utf-8")
    untied = tuple(k for k in corpus_keys.KINDS if k not in corpus_keys.TO_DECIDE)
    (root / corpus_keys.UNTIED).write_text(
        corpus_keys.render_ambiguous(ambiguous, judged_run, keyed_run, untied), "utf-8")
    kinds = collections.Counter(row["kind"] for row in ambiguous)
    return {"judged_run": judged_run, "run": keyed_run, "tied": len(ties),
            "by_pass": dict(collections.Counter(row["how"] for row in ties)),
            "ambiguous": len(ambiguous), "by_kind": {k: kinds[k] for k in corpus_keys.KINDS},
            "fallback": sum(corpus_keys.from_context(row["key"]) for row in ties)}  # fmt: skip


# --- the command line -------------------------------------------------------------------


def judging(root: Path, args: argparse.Namespace) -> str:
    """`unjudged`, the run measured as `measure` measures it, or `agree`, in Markdown."""
    if args.command == "agree":
        return corpus_judging.render_agree(corpus_judging.agree(root, args.batch))
    run = Run(run_folder(root, args.run))
    base = Run(run_folder(root, args.base)) if args.base else None
    rows = measure(root, args.run, run=run)["findings"]
    return corpus_judging.render_pack(corpus_judging.pack(
        root, run, rows, args.name, base, args.settled, args.min_judged))


def _outside_the_checkout(*paths: str | None) -> None:
    """The reports quote the corpus's papers, which are not this repository's to publish: a
    file of them inside the checkout is one `git add` from a commit, so none is written."""
    for path in filter(None, paths):
        if in_a_checkout(Path(path)):
            raise CorpusError(f"{path} is inside the manuscript-guard checkout, and what it "
                              "would hold quotes the corpus's papers: write it in the corpus "
                              "folder (its runs/ is ignored by git) or elsewhere")  # fmt: skip


def _write(text: str, data: dict, out: str | None, as_json: str | None) -> None:
    _outside_the_checkout(out, as_json)
    if out:
        Path(out).write_text(text, "utf-8")
    elif hasattr(sys.stdout, "buffer"):  # UTF-8, whatever the console's or a file's encoding
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.flush()
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
    p_tie = sub.add_parser("tie", help="tie the judged findings to keys, once (report/ties.yaml)")
    p_tie.add_argument("judged_run")
    p_tie.add_argument("keyed_run")
    p_un = sub.add_parser("unjudged", help="pack the loud findings with no verdict for judges")
    p_un.add_argument("run")
    p_un.add_argument("--name", required=True, help="the batch: report/packets/<name>.json")
    p_un.add_argument("--base", help="only those whose key is not loud in this run, every code")
    p_un.add_argument("--settled", type=float, default=corpus_judging.SETTLED)
    p_un.add_argument("--min-judged", type=int, default=corpus_judging.MIN_JUDGED)
    sub.add_parser("agree", help="set two judges' verdicts side by side").add_argument("batch")
    for p in (p_measure, p_gate, p_tie):
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
        if args.command == "tie":
            _outside_the_checkout(args.out, args.json)
            result = tie(root, args.judged_run, args.keyed_run)
            _write(corpus_keys.render_tie(result), result, args.out, args.json)
            return 0
        if args.command in ("unjudged", "agree"):
            _write(judging(root, args), {}, None, None)
            return 0
        result = gate(root, args.base, args.new)
        _write(render_gate(result), result, args.out, args.json)
        return 0 if result["ok"] else 1
    except CorpusError as exc:
        print(f"corpus.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
