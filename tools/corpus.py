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
ledger, `report/ledger.yaml`, holds the author's decisions that re-judge a finding, name the
findings that took over from one, accept a finding's loss, or name the key that carries a
finding now; nothing here writes to it.

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
    kind: str = ""
    #: An `accepted` decision's judged findings, by `Judged.key`: losses the author accepts.
    accepts: set = field(default_factory=set)
    #: A `moved` decision's judged findings, by `Judged.key`, each to the key that carries
    #: it now and that key's scheme.
    moves: dict = field(default_factory=dict)

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


PLACE = {"slug", "report", "index"}
NAMED = "a finding is named by slug, report and index, and a batch's verdict by its batch too"


def _place(key: object, where: str, says: str = NAMED, more: frozenset = frozenset()) -> tuple:
    """A judged finding as `Judged.key` names it, from a decision's entry that holds its
    place and the keys `more`, and no other."""
    if not isinstance(key, dict) or set(key) - {"batch"} != PLACE | more:
        raise CorpusError(f"{where}: {says}")
    # Read as the ties' decided file reads it (`str`), so that a name YAML takes for a
    # number or a date is the same name; it must be one `unjudged` could have given.
    batch = "" if key.get("batch") in (None, "") else str(key["batch"])
    if "batch" in key and not corpus_run.SLUG.fullmatch(batch):
        raise CorpusError(f"{where}: a batch is named by its name, letters, digits, '.', "
                          f"'_' and '-', not {key['batch']!r}")  # fmt: skip
    # A whole number as YAML writes one: never a fraction cut short, nor `true` read as 1.
    if isinstance(key["index"], bool) or not isinstance(key["index"], int):
        raise CorpusError(f"{where}: a finding's index is a number, not {key['index']!r}")
    place = (str(key["slug"]), str(key["report"]), key["index"])
    # As `Judged.key`: a batch's verdict is told from the first verdict at its place.
    return (*place, batch) if batch else place


def _named_once(place: tuple, named: set | dict, where: str) -> tuple:
    if place in named:
        raise CorpusError(f"{where}: it names {' '.join(map(str, place))} twice")
    return place


def _findings(body: object, kind: str, where: str) -> list:
    """The `findings` of an `accepted` or a `moved` decision, which hold nothing else."""
    if not isinstance(body, dict) or set(body) != {"findings"} or not isinstance(
            body["findings"], list):  # fmt: skip
        raise CorpusError(f"{where}: {kind} holds findings only, a list")
    if not body["findings"]:
        raise CorpusError(f"{where}: {kind} names no finding")
    return body["findings"]


def _rejudge(decision: Decision, body: object, where: str) -> None:
    if not isinstance(body, dict) or set(body) - {"verdict", "findings", "match"}:
        raise CorpusError(f"{where}: rejudge holds verdict, findings and match only")
    decision.verdict = _verdict(body.get("verdict"), where)
    for key in body.get("findings") or []:
        decision.keys.add(_place(key, where))
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


def _accepted(decision: Decision, body: object, where: str) -> None:
    """Judged findings whose loss the author accepts: the gate lists it apart and does not
    fail on it. Their verdicts and their states stay as they are."""
    for key in _findings(body, "accepted", where):
        decision.accepts.add(_named_once(_place(key, where), decision.accepts, where))


MOVED = (NAMED + ", with the key that carries it now (`to`) and that key's scheme (`scheme`)")


def _moved(decision: Decision, body: object, where: str) -> None:
    """Judged findings carried now by a finding of another key, each with that key and its
    scheme, as `keys.SCHEME` and the runs record it."""
    for entry in _findings(body, "moved", where):
        place = _named_once(_place(entry, where, MOVED, frozenset({"to", "scheme"})),
                            decision.moves, where)  # fmt: skip
        to, scheme = entry["to"], entry["scheme"]
        if not isinstance(to, str) or to.count("|") != 3 or not all(corpus_keys.parts(to)):
            raise CorpusError(f"{where}: `to` is a finding's key, gate|code|subject|digest, "
                              f"not {to!r}")  # fmt: skip
        if isinstance(scheme, bool) or not isinstance(scheme, int) or scheme < 1:
            raise CorpusError(f"{where}: `scheme` is a whole number from 1, the scheme of the "
                              f"key `to`, not {scheme!r}")  # fmt: skip
        decision.moves[place] = (to, scheme)


LEDGER_KINDS = {"rejudge": _rejudge, "successor": _successor, "accepted": _accepted,
                "moved": _moved}  # fmt: skip


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
        kinds = [k for k in LEDGER_KINDS if k in entry]
        extra = set(entry) - {"id", "date", "by", "what", "source", *LEDGER_KINDS}
        if len(kinds) != 1 or extra:
            raise CorpusError(f"{where}: one of rejudge, successor, accepted or moved, and no "
                              "other key")  # fmt: skip
        decision = Decision(*(_required(entry, k, where) for k in ("id", "date", "by", "what",
                                                                     "source")))  # fmt: skip
        if decision.id in seen:
            raise CorpusError(f"{where}: the id {decision.id} is used twice")
        seen.add(decision.id)
        decision.kind = kinds[0]
        LEDGER_KINDS[kinds[0]](decision, entry[kinds[0]], where)
        decisions.append(decision)
    return decisions


def _accepted_by(decisions: list[Decision]) -> dict[tuple, str]:
    """The judged findings whose loss the ledger accepts, each with the decision; the last
    decision wins."""
    return {place: d.id for d in decisions for place in d.accepts}


def _moves(decisions: list[Decision], run: Run) -> dict[tuple, tuple[str, str]]:
    """The judged findings the ledger moves in `run`, each with the decision and the key:
    only in a run that carries keys of the scheme the decision names. The last decision
    wins."""
    if not run.keyed:
        return {}
    return {place: (d.id, to) for d in decisions for place, (to, scheme) in d.moves.items()
            if scheme == run.scheme}  # fmt: skip


def _moved_to(item: Judged, to: str, new: list[dict], claimed: set[int], whole: set[int],
              taken_keys: set[str]) -> tuple | None:  # fmt: skip
    """The state a judged finding gone from a report takes from the finding that carries it
    now under the key `to`: reported where that finding is loud and of its gate and code,
    elsewhere where loud and of another, asked where it is a note or a question or a form a
    question lists. None where no finding of the report has that key, or where another judged
    finding took it. A finding taken at all (`claimed`) carries no move by its own key, a list
    of forms either; a list taken whole (`whole`: by its own key, by the matcher, a successor
    or as elsewhere) carries none by a form; and a list taken form by form carries none by a
    form another took (`taken_keys`), its other forms open."""
    if to in taken_keys:
        return None
    keys = corpus_keys.Keys(new)
    at = [i for i in keys.at.get(to, []) if i not in claimed]
    if at:
        quiet = all(new[i].get("question") or not loud(new[i]) for i in at)
        same = "/".join(corpus_keys.parts(to)[:2]) == item.code
        return ("asked" if quiet else "reported" if same else "elsewhere"), at
    forms = [i for i in keys.forms.get(to, []) if i not in whole]
    return ("asked", forms) if forms else None


def _by_form(tie: corpus_keys.Tie, state: str, found: dict) -> bool:
    """Whether a judged finding paired by its key took a list of forms by one of its forms,
    and not as a whole: by its own key, or as elsewhere."""
    if state == "elsewhere" or not found.get("forms") or tie.key is None:
        return False
    own = found.get("key")
    return not isinstance(own, str) or (corpus_keys.family_of(own) if tie.family
                                         else own) != tie.key  # fmt: skip


def _keys_taken(tie: corpus_keys.Tie, state: str, keys: corpus_keys.Keys) -> set[str]:
    """The keys a judged finding paired by its key took in a report: its own where it stands
    there, as a finding or as a form a list holds, or its family's."""
    if tie.key is None or state not in ("reported", "asked"):
        return set()
    if not tie.family:
        return {tie.key}
    return {k for k in (*keys.at, *keys.forms) if corpus_keys.family_of(k) == tie.key}


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
    #: The `moved` decision whose key's finding gave it its state.
    moved_by: str = ""
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
    """A run's reports, read once each. `removed` names the papers removed after judging,
    which a run made before may hold: `all_reports`, and so all a run is counted by, passes
    them over."""

    def __init__(self, folder: Path, removed: frozenset[str] = frozenset()) -> None:
        self.folder = folder
        self.name = folder.name
        self.removed = removed
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
        for paper in sorted(p for p in self.folder.iterdir()
                            if p.is_dir() and p.name not in self.removed):  # fmt: skip
            for report in REPORTS:
                found = self.findings(paper.name, report)
                if found is not None:
                    yield paper.name, report, found


def open_run(root: Path, name: str) -> Run:
    """A run of the corpus, which passes over the papers removed from it after judging."""
    return Run(run_folder(root, name), frozenset(corpus_run.removed_papers(root)))


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
    `held` where that keys so too and to the batch's run otherwise; where not, by the key
    `tie` tied it to where the ties hold one, as a first verdict is, and by the matcher
    otherwise. The first verdicts are paired first, so that no batch changes their fates.
    Last, a judged finding still gone that a `moved` decision of the run's scheme names takes
    the state of the finding under the decision's key, and that finding is accounted for."""
    successors = [d for d in decisions if d.successor_from]
    ties, base = keyed if keyed is not None and run.keyed else ({}, run)
    scheme = run.scheme if run.keyed else None
    held_scheme = held.scheme if held is not None and held.keyed else None
    sources: dict[Path, Run] = {}
    # The findings of the run this call's judged findings took, apart from `run.used`, which
    # outlives the call.
    claimed: dict[tuple[str, str], set[int]] = collections.defaultdict(set)
    # And the keys they took, by which a form of a list is claimed (`_moved_to`).
    taken_keys: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    # And those taken whole, which a move by a form passes over too.
    whole: dict[tuple[str, str], set[int]] = collections.defaultdict(set)

    def claim(where: tuple[str, str], used, by_form: bool = False) -> None:
        claimed[where].update(used)
        run.used[where].update(used)
        if not by_form:
            whole[where].update(used)

    def tie_of(item: Judged) -> tuple[corpus_keys.Tie | None, Run]:
        if not item.batch or (scheme != item.scheme and item.key in ties):
            # A first verdict, or a batch's of another scheme `tie` tied in a run of this
            # one: by its tied key, its count held as a first verdict's.
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
                    for i in used:
                        claim((slug, report), [i], _by_form(tie, by_key[n].state, new[i]))
                    taken_keys[(slug, report)].update(
                        _keys_taken(tie, by_key[n].state, run.keys(slug, report)))
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
        claim((item.slug, item.report), used)
        if found == "gone" and new:
            for decision in successors:
                if decision.successor_from == item.code:
                    hit = [i for i, f in enumerate(new)
                           if f"{f.get('gate')}/{f.get('code')}" in decision.successor_to]
                    if hit:
                        fate.state, fate.successor_by = "asked", decision.id
                        claim((item.slug, item.report), hit)
                        break
        out.append(fate)
    moves = _moves(decisions, run)
    for fate in out:
        where = (fate.item.slug, fate.item.report)
        if fate.state != "gone" or fate.item.key not in moves:
            continue
        by, to = moves[fate.item.key]
        new = run.findings(*where) or []
        said = _moved_to(fate.item, to, new, claimed[where], whole[where], taken_keys[where])
        if said is not None:
            fate.state, fate.moved_by = said[0], by
            # By the list's own key a move takes it whole, by a form only that form.
            claim(where, said[1], by_form=all(new[i].get("key") != to for i in said[1]))
            taken_keys[where].add(to)
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
            "moved_by": fate.moved_by, "report_missing": fate.missing, "by_key": fate.by_key,
            "fallback": fate.fallback, "repeated": fate.repeated, "fell": fate.fell,
            "batch": item.batch, "message": norm(item.finding.get("message"))[:160]}  # fmt: skip


def _place_of(row: dict) -> tuple:
    """A row's judged finding as `Judged.key` names it."""
    return (row["slug"], row["report"], row["index"], *([row["batch"]] if row["batch"] else []))


def _decision_counts(decision: Decision, rows: list[dict]) -> dict:
    """What a decision matched among the rows: the findings it re-judges, accepts or moves
    (the findings it names, wherever they stand), and those a successor or a move kept."""
    named = decision.accepts | set(decision.moves)
    return {"id": decision.id, "kind": decision.kind,
            "matched": sum(r["rejudged_by"] == decision.id or _place_of(r) in named
                           for r in rows),
            "changed": sum(r["rejudged_by"] == decision.id and r["judged"] != r["verdict"]
                           for r in rows),
            "successor": sum(r["successor_by"] == decision.id for r in rows),
            "moved": sum(r["moved_by"] == decision.id for r in rows)}  # fmt: skip


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
    tied = open_run(root, ties["run"])
    judged = load_judged(root)[0]
    corpus_keys.check_batches(ties["batches"], {item.batch: (item.run, item.scheme)
                                                for item in judged if item.batch})
    return {**ties["ties"], **decided(root, judged, tied, tied_scheme)}, tied


def decided(root: Path, judged: list[Judged], tied: Run, scheme: int) -> dict:
    """`report/ties-decided.yaml`, each decision checked against the judged set, the run of
    the ties and the batches of their scheme (`corpus_keys.check_decided`). A decision on a
    paper removed after judging stays in the file and is read nowhere."""
    own = frozenset(item.batch for item in judged if item.batch and item.scheme == scheme)
    held = {where: said for where, said in corpus_keys.load_decided(root).items()
            if where[0] not in tied.removed}  # fmt: skip
    return corpus_keys.check_decided(held, {i.key for i in judged}, tied.name,
                                     lambda slug, report: tied.keys(slug, report),
                                     own)  # fmt: skip


def _table(rows: list[dict]) -> dict:
    return {v: {s: sum(1 for r in rows if r["verdict"] == v and r["state"] == s) for s in STATES}
            for v in VERDICTS}  # fmt: skip


def _precision(table: dict, states: tuple[str, ...]) -> float | None:
    true = sum(table["true"][s] for s in states)
    total = true + sum(table["false"][s] for s in states)
    return round(true / total, 3) if total else None


def measure(root: Path, run_name: str, ledger: bool = True, run: Run | None = None) -> dict:
    judged, skipped, removed = corpus_judging.read_judged(root)
    path = root / "report" / "ledger.yaml"
    decisions = load_ledger(path) if ledger else []
    run = run or open_run(root, run_name)
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
        "decisions": [_decision_counts(d, rows) for d in decisions],
        "skipped": dict(skipped), **({"removed": removed} if removed else {}),
        "totals": _table(rows), "paper": _table(papers), "notices": _table(notices),
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
    moved = f" [moved by {row['moved_by']}]" if row.get("moved_by") else ""
    return f"- {row['slug']} {row['report']} {row['code']}: {row['message']}{extra}{by}{moved}"


def render_measure(result: dict) -> str:
    rows = result["findings"]
    rejudged_n = sum(1 for r in rows if r["rejudged_by"])
    asked_n = sum(1 for r in rows if r["successor_by"])
    moved_n = sum(1 for r in rows if r["moved_by"])
    lines = [f"# Judged findings in {result['run']}", "",
             f"{len(rows)} judged findings. Left out: {result['skipped'] or 'none'}. Ledger: "
             + (f"{len(result['decisions'])} decisions, {rejudged_n} findings re-judged, "
                f"{asked_n} kept by a successor (asked by message, elsewhere by key), "
                f"{moved_n} moved to the key that carries them now."
                if result["ledger"] else "not applied."),
             *corpus_run.render_removed(result.get("removed", [])),
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
    if result["ledger"]:
        lines += ["", "## The ledger's decisions", "",
                  "| decision | kind | matched | changed | successor | moved |",
                  "| --- | --- |" + " ---: |" * 4]  # fmt: skip
        lines += [f"| {d['id']} | {d['kind']} | {d['matched']} | {d['changed']} | "
                  f"{d['successor']} | {d['moved']} |" for d in result["decisions"]]
    return "\n".join(lines) + "\n"


# --- gate -------------------------------------------------------------------------------

KEPT = ("reported", "asked", "elsewhere")
QUIET = ("asked", "gone")
#: A list longer than this, other than the losses, is folded in the Markdown, for a PR body.
FOLD = 10


def gate(root: Path, base_name: str, new_name: str) -> dict:
    judged, skipped, removed = corpus_judging.read_judged(root)
    decisions = load_ledger(root / "report" / "ledger.yaml")
    items = rejudged(judged, decisions)
    base, new = open_run(root, base_name), open_run(root, new_name)
    # By key where both runs carry keys, the base's counts held to the run of the ties and
    # the new run's to the base's; by #705's matcher, both of them, otherwise.
    against = keyed_against(root, base, new)
    ties = against if isinstance(against, tuple) else None
    pairs = list(zip(fates(items, base, decisions, ties),
                     fates(items, new, decisions, ties and (ties[0], base), base), strict=True))

    def rows(test) -> list[dict]:
        return [{**_row(n), "base": b.state} for b, n in pairs if test(b, n)]

    every_loss = rows(lambda b, n: n.item.verdict == "true" and not n.item.notice
                      and b.state in KEPT and n.state == "gone")
    # A loss the author accepts is listed apart and blocks nothing.
    accepted = _accepted_by(decisions)
    lost = [r for r in every_loss if _place_of(r) not in accepted]
    base_loud, new_loud = unjudged(base), unjudged(new)
    return {
        "base": base.name, "new": new.name, "ok": not lost, "skipped": dict(skipped),
        **({"removed": removed} if removed else {}), "decisions": len(decisions),
        "totals": {"base": _table([_row(b) for b, _ in pairs]),
                   "new": _table([_row(n) for _, n in pairs])},
        "lost": lost,
        "accepted": [{**r, "accepted_by": accepted[_place_of(r)]} for r in every_loss
                     if _place_of(r) in accepted],
        # Where a move placed a finding, at the base, the new run or both: a base state a
        # move made shows beside a loss.
        "moved": [{**_row(n), "base": b.state, "base_moved_by": b.moved_by,
                   "moved_in": ("both" if b.moved_by and n.moved_by
                                else "base" if b.moved_by else "new")}
                  for b, n in pairs if b.moved_by or n.moved_by],  # fmt: skip
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
        "fallback": rows(lambda b, n: n.fallback), "fresh": fresh(root, new_name, base),
    }  # fmt: skip


def _how(row: dict, key: str) -> str:
    """A gate row's line: its state at both runs, the decision that accepts its loss, and in
    which run a move placed it."""
    said = f"; lost, accepted by {row['accepted_by']}" if key == "accepted" else ""
    if key == "moved":
        base, new = row["base_moved_by"], row["moved_by"]
        said = (f"; moved in {row['moved_in']} by {base or new}" if row["moved_in"] != "both"
                or base == new else f"; moved in base by {base}, in new by {new}")  # fmt: skip
        row = {**row, "moved_by": ""}  # named once, here
    return _line(row) + f" ({row['base']} -> {row['state']}{said})"


def render_gate(result: dict) -> str:
    accepted = len(result.get("accepted", []))
    losses = f"{accepted} loss{'es' if accepted != 1 else ''}"
    passing = f", but for {losses} the ledger accepts" if accepted else ""
    failing = f"; the ledger accepts {losses} more" if accepted else ""
    verdict = (f"**Passes**: no true finding about the paper is lost{passing}." if result["ok"]
               else f"**Fails**: {len(result['lost'])} true findings about the paper are kept "
               f"in {result['base']} and gone in {result['new']}, and no decision of the "
               f"ledger covers them{failing}.")  # fmt: skip
    lines = [f"## Corpus gate: {result['base']} -> {result['new']}", "", verdict, "",
             f"Ledger applied: {result['decisions']} decisions. Judged findings left out: "
             f"{result['skipped'] or 'none'}.",
             *corpus_run.render_removed(result.get("removed", [])), "",
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
                ("True findings lost, accepted by the ledger", "accepted"),
                ("Judged findings the ledger moves to the key that carries them", "moved"),
                ("True findings about the paper back", "recovered"),
                ("True findings reported before, asked now", "quieter"),
                ("Reading notices that changed", "notices"),
                ("False findings now loud", "false_loud"),
                ("Judged findings under a key repeated in either run", "repeated"),
                ("Judged findings paired by a key from the context", "fallback"))  # fmt: skip
    for title, key in sections:
        part = result.get(key, [])
        lines += ["", f"### {title} ({len(part)})", ""]
        listed = [_how(r, key) for r in part] or ["None."]
        if len(part) > FOLD and key not in ("lost", "accepted"):
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


def _tie_set(judged: list[Judged], run: Run, before: Run) -> tuple[list[dict], list[dict]]:
    """One judged set's ties to `run`, report by report, the judged run `before`, and the
    judged findings not tied, a batch's with its name."""
    groups: dict[tuple[str, str], list[Judged]] = collections.defaultdict(list)
    for item in judged:
        groups[(item.slug, item.report)].append(item)
    ties, ambiguous = [], []
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
                ambiguous.append({**where, **({"batch": item.batch} if item.batch else {}),
                                  "kind": kind, "how": how, "verdict": item.verdict,
                                  "code": item.code, "candidates": candidates[:5],
                                  "message": norm(item.finding.get("message"))[:200]})
    return ties, ambiguous


def _tie_batches(batches: list[Judged], run: Run) -> tuple[dict, list[dict], dict[str, int]]:
    """Each batch's verdicts of another scheme than `run`'s tied to it as the first ones are,
    the batch's own run, where its packet found it, standing for the judged run; and the
    batches whose run is not there, left untied, for the matcher."""
    by_batch: dict[str, list[Judged]] = collections.defaultdict(list)
    for item in batches:
        by_batch[item.batch].append(item)
    tied, ambiguous, no_run = {}, [], {}
    for name, items in sorted(by_batch.items()):
        sources = {item.source for item in items}
        if None in sources or len(sources) != 1:
            no_run[name] = len(items)
            continue
        ties, left = _tie_set(items, run, Run(sources.pop()))
        to_decide = sum(row["kind"] in corpus_keys.TO_DECIDE for row in left)
        tied[name] = {"judged_run": items[0].run, "scheme": items[0].scheme, "ties": ties,
                      "ambiguous": len(left), "to_decide": to_decide}  # fmt: skip
        ambiguous += left
    return tied, ambiguous, no_run


def tie(root: Path, judged_run: str, keyed_run: str) -> dict:
    """Tie each judged finding to its key in a keyed run of the same papers, once: where
    #705's matcher pairs it one to one by the same message or context at its place
    (`corpus_keys.tie_group`); and each batch's verdicts the same way where the batch keys
    by another scheme than the keyed run, its own run standing for the judged run (Basile,
    2026-11-21). Writes `report/ties.yaml`, a batch's ties under `batches` by its name, and,
    for the author to settle by hand, `report/ties-ambiguous.md`. The verdicts and the
    ledger are not touched."""
    every, skipped, removed = corpus_judging.read_judged(root)
    judged = [item for item in every if not item.batch]
    run_folder(root, judged_run)
    run = open_run(root, keyed_run)
    if not run.keyed:
        raise CorpusError(f"{keyed_run} carries no keys: tie to a run of a build from #706 on")
    batches, by_batch, no_run = _tie_batches([item for item in every if item.batch
                                              and item.scheme != run.scheme], run)  # fmt: skip
    own = sorted({item.batch for item in every if item.batch and item.scheme == run.scheme})
    ties, ambiguous = _tie_set(judged, run, open_run(root, judged_run))
    document = {"judged_run": judged_run, "run": keyed_run, "scheme": run.scheme, "ties": ties}
    if batches:
        document["batches"] = {name: {k: b[k] for k in ("judged_run", "scheme", "ties")}
                               for name, b in batches.items()}  # fmt: skip
    kinds = collections.Counter(row["kind"] for row in ambiguous)
    ambiguous += by_batch
    (root / corpus_keys.TIES).write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100), "utf-8")
    runs = {name: b["judged_run"] for name, b in batches.items()}
    (root / corpus_keys.AMBIGUOUS).write_text(
        corpus_keys.render_ambiguous(ambiguous, judged_run, keyed_run, batches=runs), "utf-8")
    untied = tuple(k for k in corpus_keys.KINDS if k not in corpus_keys.TO_DECIDE)
    (root / corpus_keys.UNTIED).write_text(
        corpus_keys.render_ambiguous(ambiguous, judged_run, keyed_run, untied, runs, no_run),
        "utf-8")
    return {"judged_run": judged_run, "run": keyed_run, "scheme": run.scheme,
            "tied": len(ties), "by_pass": dict(collections.Counter(row["how"] for row in ties)),
            "ambiguous": len(ambiguous) - len(by_batch),
            "by_kind": {k: kinds[k] for k in corpus_keys.KINDS},
            "fallback": sum(corpus_keys.from_context(row["key"]) for row in ties),
            "batches": {name: {"judged_run": b["judged_run"], "scheme": b["scheme"],
                               "tied": len(b["ties"]), "ambiguous": b["ambiguous"],
                               "to_decide": b["to_decide"]} for name, b in batches.items()},
            "own_scheme": own, "no_run": list(no_run),
            **({"removed": removed, "skipped": dict(skipped)} if removed else {})}  # fmt: skip


# --- the command line -------------------------------------------------------------------


def judging(root: Path, args: argparse.Namespace) -> str:
    """`unjudged`, the run measured as `measure` measures it, or `agree`, in Markdown."""
    if args.command == "agree":
        return corpus_judging.render_agree(corpus_judging.agree(root, args.batch))
    base = open_run(root, args.base) if args.base else None
    # A corpus judged for the first time, a held-out set, holds no verdict to measure: no code
    # is settled, and every loud finding is packed (Basile, 2026-11-23, item 6).
    measured = (_measured(root, args.run) if corpus_judging.has_verdicts(root)
                else (open_run(root, args.run), []))  # fmt: skip
    return corpus_judging.render_pack(corpus_judging.pack(
        root, *measured, args.name, base, args.settled, args.min_judged))


def _measured(root: Path, name: str) -> tuple[Run, list[dict]]:
    """A run, with the judged set paired in it as `measure` pairs it, and the rows."""
    run = open_run(root, name)
    return run, measure(root, name, run=run)["findings"]


def fresh(root: Path, new_name: str, base: Run) -> dict:
    """The gate's count of the new run's loud findings with no verdict, new against the
    base: the new run measured as `unjudged` measures it, and `unjudged --base`'s selection,
    so that the count is what the command it prints packs; where the keys of the two cannot
    be set side by side, why, and the new run is not measured."""
    problem = corpus_judging.base_problem(open_run(root, new_name), base)
    if problem:
        return {"count": None, "note": problem}
    return corpus_judging.fresh(root, *_measured(root, new_name), base)


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
    elif not getattr(sys.stdout, "isatty", lambda: False)() and hasattr(sys.stdout, "buffer"):
        sys.stdout.flush()  # UTF-8, as a file is
        sys.stdout.buffer.write(text.encode("utf-8"))
        sys.stdout.buffer.flush()
    else:  # a terminal: its own encoding, a character it cannot show replaced
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.write(text.encode(enc, "replace").decode(enc))
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
