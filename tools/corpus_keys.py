"""Pairing a judged finding by its key, and tying the judged set to keys once: the part of
`tools/corpus.py` that reads the `key` every finding of `--json` carries (DESIGN.md, "A
finding's key pairs two runs"; docs/corpus.md says how a corpus uses it).

Basile's rules (2026-11-19): where both runs carry keys, a judged finding is paired by its
key alone; only a key unique in both runs pairs, and where a repeated key's count falls from
the base to the new run, every judged finding under it is gone; the judged set, from a run
before the keys, is tied to keys once (`tie`), and what does not tie one to one by the
strongest passes, or by the two exact rules of 2026-11-20 (`_lineless`, `_form_entry`),
goes to the author where it has several candidates or a repeated key, and is left for the
matcher otherwise.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from corpus_match import STRONG, form_of, loud, match, norm, region, states, subject_of
from corpus_run import CorpusError

#: What a key's subject is where it stands for a list, and its digest where it stands for no
#: sentence (`manuscript_guard.keys.NONE`).
NONE = "-"
TIES = Path("report") / "ties.yaml"
AMBIGUOUS = Path("report") / "ties-ambiguous.md"
UNTIED = Path("report") / "ties-untied.md"
#: The kinds the author settles by hand; the others stay untied, for #705's matcher.
TO_DECIDE = ("several", "repeated")
#: The proposed record of the author's decision on one of them (not read by any command yet).
DECIDED = Path("report") / "ties-decided.yaml"
#: The part of the paper a G14 message names, as a key's scope writes it (`HR@main`).
SCOPES = {"abstract": "abstract", "main text": "main", "supplement": "supplement"}
#: Why a judged finding was not tied, in the order the author reads them.
KINDS = {
    "none": "no candidate: no finding of its code in the keyed run is it",
    "several": "several candidates: more than one finding of its code could be it, or the "
               "judged run has two like it",
    "taken": "its candidate is another judged finding's",
    "weaker": "paired only by a weaker pass than the same message or context at its place",
    "cross-code": "paired only with a finding of another code",
    "repeated": "its candidate's key is repeated in the keyed run",
}  # fmt: skip


def parts(key: str) -> tuple[str, str, str, str]:
    """A key's gate, code, subject and digest; a subject holds no `|` (`keys.subject`)."""
    gate, code, subject, digest = (key.split("|") + ["", "", "", ""])[:4]
    return gate, code, subject, digest


def from_context(key: str) -> bool:
    """Whether a key falls back on a digest of its context (`"key_from": "context"`)."""
    return parts(key)[2].startswith("~")


def keyed(findings: list[dict]) -> bool:
    return any(isinstance(f.get("key"), str) for f in findings)


@dataclass
class Keys:
    """A report's findings by key, a form's key under the finding that lists it counted too."""

    findings: list[dict]
    at: dict[str, list[int]] = field(default_factory=lambda: collections.defaultdict(list))
    forms: dict[str, list[int]] = field(default_factory=lambda: collections.defaultdict(list))

    def __post_init__(self) -> None:
        for i, f in enumerate(self.findings):
            if isinstance(f.get("key"), str):
                self.at[f["key"]].append(i)
            for entry in f.get("forms") or []:
                if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                    self.forms[entry["key"]].append(i)

    def count(self, key: str) -> int:
        return len(self.at.get(key, ())) + len(self.forms.get(key, ()))


@dataclass
class ByKey:
    state: str
    used: list[int]
    #: The key stands more than once in the base or the new run.
    repeated: bool = False
    #: Its count fell from the base to the new run.
    fell: bool = False


def key_state(key: str, new: Keys, base_count: int, successor_codes: tuple = ()) -> ByKey:
    """A judged finding's state by its key alone: reported where its key stands at a warning
    or a failure, asked where it stands as a note or a question or a form a question lists,
    elsewhere where another code has its subject and digest at a warning or a failure or a
    successor of its code stands in the report, gone otherwise. Under a key that is repeated
    in either run, a count that fell from the base reads gone (Basile, 2026-11-19)."""
    count = new.count(key)
    repeated = base_count > 1 or count > 1
    if repeated and count < base_count:
        return ByKey("gone", [], repeated=True, fell=True)
    here = new.at.get(key, [])
    if here:
        quiet = all(new.findings[i].get("question") or not loud(new.findings[i]) for i in here)
        return ByKey("asked" if quiet else "reported", list(here), repeated)
    if new.forms.get(key):
        return ByKey("asked", list(new.forms[key]), repeated)
    gate, code, subject, digest = parts(key)
    if subject != NONE and not subject.startswith("~"):
        other = [i for i, f in enumerate(new.findings) if loud(f) and isinstance(f.get("key"), str)
                 and parts(f["key"])[2:] == (subject, digest)
                 and parts(f["key"])[:2] != (gate, code)]  # fmt: skip
        if other:
            return ByKey("elsewhere", other, repeated)
    hit = [i for i, f in enumerate(new.findings)
           if f"{f.get('gate')}/{f.get('code')}" in successor_codes]  # fmt: skip
    if hit:
        return ByKey("elsewhere", hit, repeated)
    return ByKey("gone", [], repeated)


# --- ties -------------------------------------------------------------------------------


def load_ties(root: Path) -> dict | None:
    """`report/ties.yaml`: the keyed run the judged set was tied in, and each tie by its
    judged finding's slug, report and index. None where there is none."""
    path = root / TIES
    if not path.is_file():
        return None
    try:
        document = yaml.safe_load(path.read_text("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CorpusError(f"{path} is not YAML: {exc}") from None
    if not isinstance(document, dict) or not isinstance(document.get("ties"), list) \
            or not isinstance(document.get("run"), str):  # fmt: skip
        raise CorpusError(f"{path}: the ties are a list under `ties`, the run they name `run`")
    out = {}
    for entry in document["ties"]:
        if not isinstance(entry, dict) or set(entry) != {"slug", "report", "index", "key", "how"}:
            raise CorpusError(f"{path}: a tie is slug, report, index, key and how")
        try:
            out[(str(entry["slug"]), str(entry["report"]), int(entry["index"]))] = str(entry["key"])
        except (TypeError, ValueError):
            raise CorpusError(f"{path}: a tie's index is a number, not {entry['index']!r}"
                              ) from None  # fmt: skip
    return {"run": document["run"], "ties": out}


def _listed_key(finding: dict, entry: int | None) -> str:
    """A finding's key, or the key of one of the forms it lists."""
    if entry is not None:
        return str((finding.get("forms") or [])[entry].get("key"))
    return str(finding.get("key"))


def _candidates(new: list[dict], indices: list[int], forms: dict[int, int]) -> list[dict]:
    out = []
    for i in dict.fromkeys(indices):
        f = new[i]
        entry = (f.get("forms") or [])[forms[i]] if i in forms else None
        said = entry if isinstance(entry, dict) else f
        out.append({"key": str(said.get("key")), "code": f"{f.get('gate')}/{f.get('code')}",
                    "message": norm(said.get("message"))[:200]})  # fmt: skip
    return out


Said = tuple[str, str, list[dict]]


def _code(f: dict) -> tuple:
    return f.get("gate"), f.get("code")


def _lineless(old: dict, new: list[dict], judged_all: list[dict], counts: Keys) -> Said | None:
    """Rule 1 (Basile, 2026-11-20): a judged finding with no line ties to the keyed finding
    of its gate and code whose message is the same, where that message is the only one of
    its code so in the judged run's report and in the keyed run's, and its key is not
    repeated. None where no keyed finding of its code has its message."""
    said = norm(old.get("message"))
    same = [i for i, f in enumerate(new)
            if _code(f) == _code(old) and norm(f.get("message")) == said]  # fmt: skip
    if not same:
        return None
    listed = _candidates(new, same, {})
    twins = sum(_code(f) == _code(old) and norm(f.get("message")) == said for f in judged_all)
    if len(same) > 1 or twins > 1:
        return "several", "message, no line", listed
    if counts.count(str(new[same[0]].get("key"))) > 1:
        return "repeated", "message, no line", listed
    return "tie", "message, no line", listed


def _form_entry(old: dict, new: list[dict], judged_all: list[dict], counts: Keys,
                i: int, j: int) -> Said | None:  # fmt: skip
    """Rule 2 (Basile, 2026-11-20): a judged finding the matcher paired with a form a list
    holds ties to that form's own key, where its short form and its scope (`HR@main`) are
    the same and the only ones of its code so in the judged run's report, and the key is
    not repeated in the keyed run. None where the form's key has no scope to hold it to."""
    entry = new[i]["forms"][j]
    key = str(entry.get("key"))
    subject = parts(key)[2]
    form, scope = form_of(old), SCOPES.get(region(old.get("message")) or "")
    if "@" not in subject or not form:
        return None
    listed = _candidates(new, [i], {i: j})
    scopes = {parts(str(e.get("key")))[2] for f in new if _code(f) == _code(old)
              for e in f.get("forms") or [] if isinstance(e, dict) and e.get("form") == form}
    if scope is None:
        return ("several" if len(scopes) > 1 else "weaker"), "form entry", listed
    if subject != f"{form}@{scope}":
        return "weaker", "form entry", listed
    twins = sum(_code(f) == _code(old) and form_of(f) == form
                and region(f.get("message")) == region(old.get("message")) for f in judged_all)
    if twins > 1:
        return "several", "form entry", listed
    if counts.count(key) > 1:
        return "repeated", "form entry", listed
    return "tie", "form entry", listed


def tie_group(olds: list[dict], new: list[dict], slug: str,
              alone: frozenset[int] = frozenset(),
              judged_all: list[dict] | None = None) -> list[Said]:  # fmt: skip
    """For each judged finding of one report, `("tie", how, [its finding])` where #705's
    matcher pairs it one to one, with its gate and code, by the same message or context at
    its place, its candidate the only one so and its key unique in the keyed run; else the
    kind of ambiguity and the candidates for the author to choose from."""
    how: dict = {}
    strong: dict = {}
    found = match(olds, new, slug, alone, how, strong)
    said = states(olds, new, slug, alone)
    counts = Keys(new)
    out = []
    for k in range(len(olds)):
        by_rule = None
        if olds[k].get("line") is None:
            by_rule = _lineless(olds[k], new, judged_all or olds, counts)
        if by_rule is None and how.get(k, "").startswith("form:"):
            by_rule = _form_entry(olds[k], new, judged_all or olds, counts, found[k][0],
                                  int(how[k].split(":")[1]))  # fmt: skip
        if by_rule is not None:
            out.append(by_rule)
            continue
        candidates, forms = list(strong.get(k, [])), {}
        if k in found:
            i = found[k][0]
            candidates.insert(0, i)
            if how[k].startswith("form:"):
                forms[i] = int(how[k].split(":")[1])
        kind = None
        if k in found and how[k] in STRONG and new[found[k][0]].get("forms"):
            # A finding that lists forms keys the list; the judged one is one form of it,
            # whose own key the list's entry for it carries.
            entries = [j for j, e in enumerate(new[found[k][0]]["forms"])
                       if isinstance(e, dict) and e.get("form") == subject_of(olds[k])]
            if len(entries) == 1:
                forms[found[k][0]] = entries[0]
            else:
                kind = "several" if entries else "weaker"
        if kind is None and k not in found:
            state, used = said[k]
            kind = "cross-code" if used else "taken" if candidates else "none"
            candidates += used
        elif kind is None and how[k] not in STRONG:
            kind = "weaker"
        elif kind is None and len(strong.get(k, [])) > 1:
            kind = "several"
        elif kind is None and counts.count(
                _listed_key(new[found[k][0]], forms.get(found[k][0]))) > 1:  # fmt: skip
            kind = "repeated"
        listed = _candidates(new, candidates, forms)
        if kind is None:
            out.append(("tie", how[k], listed[:1]))
        else:
            if kind == "none":
                code = (olds[k].get("gate"), olds[k].get("code"))
                listed = _candidates(new, [i for i, f in enumerate(new)
                                           if (f.get("gate"), f.get("code")) == code][:3], {})
            out.append((kind, how.get(k, ""), listed))
    return out


def render_ambiguous(rows: list[dict], judged_run: str, keyed_run: str,
                     kinds: tuple = TO_DECIDE) -> str:  # fmt: skip
    """The judged findings of `kinds` not tied, each with its candidates: those the author
    settles by hand (`TO_DECIDE`), or, with the other kinds, the list of those left untied."""
    rows = [row for row in rows if row["kind"] in kinds]
    if kinds == TO_DECIDE:
        lines = [f"# Judged findings for the author to tie: {len(rows)}", "",
                 f"To record a decision, add a line to `{DECIDED.as_posix()}`: `- {{slug: S, "
                 "report: R, index: N, key: 'K', by: NAME, date: YYYY-MM-DD}`, where K is the "
                 "key it is, or `key: null` where none is.", "",
                 f"The judged run {judged_run} against the keyed run {keyed_run}: the findings "
                 "with more than one candidate, and those whose candidate's key is repeated.",
                 ""]  # fmt: skip
    else:
        lines = [f"# Judged findings left untied: {len(rows)}", "",
                 f"The judged run {judged_run} against the keyed run {keyed_run}: no rule ties "
                 "these, and #705's matcher pairs them in `measure` and `gate`.", ""]
    by_kind = collections.defaultdict(list)
    for row in rows:
        by_kind[row["kind"]].append(row)
    for kind, title in KINDS.items():
        if kind not in kinds:
            continue
        part = by_kind.get(kind, [])
        lines += [f"## {title} ({len(part)})", ""]
        for row in part:
            by = f", paired by {row['how']}" if row.get("how") else ""
            lines.append(f"- **{row['slug']} {row['report']} {row['index']}** ({row['verdict']}, "
                         f"{row['code']}{by}): {row['message']}")  # fmt: skip
            lines += [f"  - `{c['key']}` ({c['code']}): {c['message']}"
                      for c in row["candidates"]] or ["  - no finding of its code"]
        lines.append("")
    return "\n".join(lines)
