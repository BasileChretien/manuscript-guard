"""Pairing a judged finding by its key, and tying the judged set to keys once: the part of
`tools/corpus.py` that reads the `key` every finding of `--json` carries (DESIGN.md, "A
finding's key pairs two runs"; docs/corpus.md says how a corpus uses it).

Basile's rules (2026-11-19): where both runs carry keys, a judged finding is paired by its
key alone; only a key unique in both runs pairs, and where a repeated key's count falls from
the base to the new run, every judged finding under it is gone; the judged set, from a run
before the keys, is tied to keys once (`tie`), and what does not tie one to one by the
strongest passes, or by the exact rules of 2026-11-20 (`_lineless`, `_form_entry`,
`_families`, `_twins`), goes to the author where it has several candidates or a repeated
key, and is left for the matcher otherwise.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from corpus_match import (
    STRONG,
    form_of,
    loud,
    match,
    norm,
    region,
    relative,
    states,
    subject_of,
)
from corpus_run import CorpusError

#: What a key's subject is where it stands for a list, and its digest where it stands for no
#: sentence (`manuscript_guard.keys.NONE`).
NONE = "-"
#: The ordinal `keys.assign` gives two findings of one subject in one sentence.
ORDINAL = re.compile(r"#\d+$")
TIES = Path("report") / "ties.yaml"
AMBIGUOUS = Path("report") / "ties-ambiguous.md"
UNTIED = Path("report") / "ties-untied.md"
#: The kinds the author settles by hand; the others stay untied, for #705's matcher.
TO_DECIDE = ("several", "repeated")
#: The author's decisions on them, which `measure` and `gate` read over the ties.
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


def family_of(key: str) -> str:
    """A key with the ordinal of its subject taken off, `xxxx#2` read `xxxx`: the group of
    findings of one subject in one sentence that only their order tells apart."""
    gate, code, subject, digest = parts(key)
    return "|".join((gate, code, ORDINAL.sub("", subject), digest))


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
    #: Each key family's findings, a form under a list counted with its list's index.
    family: dict[str, list[int]] = field(default_factory=lambda: collections.defaultdict(list))

    def __post_init__(self) -> None:
        for i, f in enumerate(self.findings):
            if isinstance(f.get("key"), str):
                self.at[f["key"]].append(i)
                self.family[family_of(f["key"])].append(i)
            for entry in f.get("forms") or []:
                if isinstance(entry, dict) and isinstance(entry.get("key"), str):
                    self.forms[entry["key"]].append(i)
                    self.family[family_of(entry["key"])].append(i)

    def count(self, key: str, family: bool = False) -> int:
        if family:
            return len(self.family.get(key, ()))
        return len(self.at.get(key, ())) + len(self.forms.get(key, ()))


@dataclass
class ByKey:
    state: str
    used: list[int]
    #: The key stands more than once in the base or the new run.
    repeated: bool = False
    #: Its count fell from the base to the new run.
    fell: bool = False


def _elsewhere(key: str, new: Keys, successor_codes: tuple, family: bool) -> list[int]:
    """Where a key gone from a report stands under another code: its subject and digest at a
    warning or a failure of another code (a family's, its ordinal aside), or a successor of
    its code. A paper-level key's digest is `-`, so another paper-level code about its
    subject counts too, whatever it says of it (docs/corpus.md)."""
    gate, code, subject, digest = parts(key)
    if subject != NONE and not subject.startswith("~"):
        def alike(other: str) -> bool:
            them = parts(family_of(other) if family else other)
            return them[2:] == (subject, digest) and them[:2] != (gate, code)

        other = [i for i, f in enumerate(new.findings) if loud(f)
                 and isinstance(f.get("key"), str) and alike(f["key"])]  # fmt: skip
        if other:
            return other
    return [i for i, f in enumerate(new.findings)
            if f"{f.get('gate')}/{f.get('code')}" in successor_codes]  # fmt: skip


def family_state(key: str, new: Keys, base_count: int, successor_codes: tuple = ()) -> ByKey:
    """A judged finding tied to a key family: kept while the family's count does not fall
    from the base, reported where one of it stands at a warning or a failure; gone, with
    every judged finding tied to the family, where its count fell (Basile, 2026-11-20).
    Where none of it is left, elsewhere as `key_state` reads it."""
    here = new.family.get(key, [])
    if here and len(here) < base_count:
        return ByKey("gone", [], repeated=True, fell=True)
    if here:
        quiet = all(new.findings[i].get("question") or not loud(new.findings[i]) for i in here)
        return ByKey("asked" if quiet else "reported", list(dict.fromkeys(here)), repeated=True)
    other = _elsewhere(key, new, successor_codes, family=True)
    if other:
        return ByKey("elsewhere", other, repeated=True)
    return ByKey("gone", [], repeated=True, fell=base_count > 0)


def key_state(key: str, new: Keys, base_count: int, successor_codes: tuple = ()) -> ByKey:
    """A judged finding's state by its key alone: reported where its key stands at a warning
    or a failure, asked where it stands as a note or a question or a form a question lists,
    elsewhere where another code has its subject and digest at a warning or a failure or a
    successor of its code stands in the report, gone otherwise. Under a key that is repeated
    in either run, a count that fell from the base reads gone, unless none is left and it
    stands elsewhere (Basile, 2026-11-19)."""
    count = new.count(key)
    repeated = base_count > 1 or count > 1
    if repeated and 0 < count < base_count:
        return ByKey("gone", [], repeated=True, fell=True)
    here = new.at.get(key, [])
    if here:
        quiet = all(new.findings[i].get("question") or not loud(new.findings[i]) for i in here)
        return ByKey("asked" if quiet else "reported", list(here), repeated)
    if new.forms.get(key):
        return ByKey("asked", list(new.forms[key]), repeated)
    other = _elsewhere(key, new, successor_codes, family=False)
    if other:
        return ByKey("elsewhere", other, repeated)
    return ByKey("gone", [], repeated, fell=repeated and count < base_count)


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
            or not isinstance(document.get("run"), str) \
            or set(document) - {"judged_run", "run", "scheme", "ties"}:  # fmt: skip
        raise CorpusError(f"{path}: the ties are a list under `ties`, the run they name `run`, "
                          "and nothing but `judged_run` and `scheme` beside them")
    out = {}
    for entry in document["ties"]:
        if not isinstance(entry, dict) or not {"slug", "report", "index", "key", "how"} \
                <= set(entry) <= {"slug", "report", "index", "key", "how", "family"}:  # fmt: skip
            raise CorpusError(f"{path}: a tie is slug, report, index, key and how, and family")
        if not isinstance(entry["key"], str):
            raise CorpusError(f"{path}: a tie's key is a string, not {entry['key']!r}")
        out[_where(entry, path)] = Tie(entry["key"], bool(entry.get("family")))
    scheme = document.get("scheme", 1)
    if not isinstance(scheme, int):
        raise CorpusError(f"{path}: the scheme of the ties' keys is a number, not {scheme!r}")
    return {"run": document["run"], "ties": out, "scheme": scheme}


@dataclass(frozen=True)
class Tie:
    """A judged finding's key, or its key family's (`family`); no key where the author
    decided no finding of the keyed run is it."""

    key: str | None
    family: bool = False


def _where(entry: dict, path: Path) -> tuple[str, str, int]:
    try:
        return str(entry["slug"]), str(entry["report"]), int(entry["index"])
    except (TypeError, ValueError):
        raise CorpusError(f"{path}: a tie's index is a number, not {entry['index']!r}") from None


def load_decided(root: Path) -> dict[tuple[str, str, int], Tie]:
    """`report/ties-decided.yaml`: the author's ties, each `{slug, report, index, key, by,
    date}`, the key null where no keyed finding is the judged one, `family: true` for a key
    family. Read beside the ties, over them; checked against the judged set and the run of
    the ties by `check_decided`. A judged finding decided twice is refused."""
    path = root / DECIDED
    if not path.is_file():
        return {}
    try:
        document = yaml.safe_load(path.read_text("utf-8")) or []
    except yaml.YAMLError as exc:
        raise CorpusError(f"{path} is not YAML: {exc}") from None
    if not isinstance(document, list):
        raise CorpusError(f"{path}: the decisions are a list")
    out = {}
    for entry in document:
        needed = {"slug", "report", "index", "key", "by", "date"}
        if not isinstance(entry, dict) or not needed <= set(entry) <= needed | {"family"}:
            raise CorpusError(f"{path}: a decision is slug, report, index, key, by and date")
        key, where = entry["key"], _where(entry, path)
        if key is not None and not isinstance(key, str):
            raise CorpusError(f"{path}: a decision's key is a string or null, not {key!r}")
        if where in out:
            raise CorpusError(f"{path}: {' '.join(map(str, where))} is decided twice")
        out[where] = Tie(key, bool(entry.get("family")))
    return out


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
        if not isinstance(said.get("key"), str):
            continue  # no key, no candidate: never the string "None"
        out.append({"key": str(said.get("key")), "code": f"{f.get('gate')}/{f.get('code')}",
                    "message": norm(said.get("message"))[:200], "line": said.get("line"),
                    "col": said.get("col")})  # fmt: skip
    return out


Said = tuple[str, str, list[dict]]


def _code(f: dict) -> tuple:
    return f.get("gate"), f.get("code")


def _lineless(old: dict, new: list[dict], judged_all: list[dict], counts: Keys,
              slug: str) -> Said | None:  # fmt: skip
    """Rule 1 (Basile, 2026-11-20): a judged finding with no line ties to the keyed finding
    of its gate and code whose message is the same, in the same file where it names one (a
    line-less finding's place is its file), where that message is the only one of its code
    so in the judged run's report and in the keyed run's, and its key is not repeated. None
    where no keyed finding of its code has its message."""
    said, path = norm(old.get("message")), relative(old.get("path"), slug)

    def alike(f: dict) -> bool:
        return _code(f) == _code(old) and norm(f.get("message")) == said and (
            path is None or relative(f.get("path"), slug) == path)

    same = [i for i, f in enumerate(new) if alike(f)]
    if not same:
        return None
    listed = _candidates(new, same, {})
    twins = sum(alike(f) for f in judged_all)
    if len(same) > 1 or twins > 1:
        return "several", "message, no line", listed
    if counts.count(str(new[same[0]].get("key"))) > 1:
        return "repeated", "message, no line", listed
    return "tie", "message, no line", listed


def _form_entry(old: dict, new: list[dict], judged_all: list[dict], counts: Keys,
                i: int, by_form_pass: bool) -> Said | None:  # fmt: skip
    """Rules 2 (form pass) and 3 (any pass) of Basile's of 2026-11-20: a judged short form
    whose candidate is a list naming that form ties to the list's entry for it in the same
    scope (`HR@main`), where that entry is the only one so, the form and scope are the only
    ones of its code so in the judged run's report, and the key is not repeated in the keyed
    run. None where the list's entries for the form carry no scope to hold it to."""
    form, scope = form_of(old), SCOPES.get(region(old.get("message")) or "")
    entries = [(j, e) for j, e in enumerate(new[i].get("forms") or [])
               if isinstance(e, dict) and e.get("form") == form]  # fmt: skip
    if not form or not entries or not all("@" in parts(str(e.get("key")))[2] for _, e in entries):
        return None
    how = "form entry" if by_form_pass else "short form, any pass"
    listed = _candidates(new, [i], {i: entries[0][0]})
    scopes = {parts(str(e.get("key")))[2] for f in new if _code(f) == _code(old)
              for e in f.get("forms") or [] if isinstance(e, dict) and e.get("form") == form}
    if scope is None:
        return ("several" if len(scopes) > 1 else "weaker"), how, listed
    mine = [j for j, e in entries if parts(str(e.get("key")))[2] == f"{form}@{scope}"]
    if len(mine) != 1:
        return ("several" if mine else "weaker"), how, listed
    listed = _candidates(new, [i], {i: mine[0]})
    twins = sum(_code(f) == _code(old) and form_of(f) == form
                and region(f.get("message")) == region(old.get("message")) for f in judged_all)
    if twins > 1:
        return "several", how, listed
    if counts.count(listed[0]["key"]) > 1:
        return "repeated", how, listed
    return "tie", how, listed


def _families(out: list[Said], olds: list[dict], judged_all: list[dict], counts: Keys,
              slug: str) -> list[Said]:  # fmt: skip
    """Rule 1 (Basile, 2026-11-20): a judged finding with several candidates, or one whose
    candidate's key is repeated, ties to the key family where every candidate is of one
    family, its keys alike but for the subject's ordinal; never where they differ by more,
    nor where the keyed run holds fewer of the family than there are judged findings with
    it as their one family, or findings like them in the judged run: one of those is lost
    already, and which cannot be told."""
    only: dict[int, str] = {}
    for k, (kind, how, listed) in enumerate(out):
        families = {family_of(c["key"]) for c in listed}
        if kind in TO_DECIDE and listed and len(families) == 1 and "form" not in how:
            only[k] = families.pop()
    wanted = collections.Counter(only.values())
    for k, family in only.items():
        wanted[family] = max(wanted[family], sum(_alike(olds[k], f, slug) for f in judged_all))
    tied = list(out)
    for k, family in only.items():
        if counts.count(family, family=True) >= wanted[family]:
            tied[k] = ("tie", "key family", [{**out[k][2][0], "key": family}])
    return tied


def _alike(old: dict, other: dict, slug: str) -> bool:
    """Two findings of one code, message and place: told apart by nothing but their order."""
    return _code(other) == _code(old) and norm(other.get("message")) == norm(
        old.get("message")) and other.get("line") == old.get("line") and relative(
        other.get("path"), slug) == relative(old.get("path"), slug)  # fmt: skip


def _twins(out: list[Said], olds: list[dict], verdicts: list[str], slug: str) -> list[Said]:
    """Rule 2 (Basile, 2026-11-20): judged findings of one report alike in gate, code,
    message and place, of one verdict, with several candidates, as many distinct keys among
    them as there are twins, tie one to one, the candidates in order of their place (or of
    their keys where one has no column), the twins in order of index. Their verdict is one,
    so the order changes no measure. Never where their verdicts differ, nor the numbers."""
    groups: dict[tuple, list[int]] = collections.defaultdict(list)
    for k, (kind, _how, _listed) in enumerate(out):
        if kind == "several":
            old = olds[k]
            groups[(_code(old), norm(old.get("message")), old.get("line"),
                    relative(old.get("path"), slug))].append(k)  # fmt: skip
    out = list(out)
    for members in groups.values():
        candidates = list({c["key"]: c for k in members for c in out[k][2]}.values())
        if len(members) < 2 or len(candidates) != len(members) \
                or len({verdicts[k] for k in members}) != 1:  # fmt: skip
            continue
        placed = all(c.get("col") is not None for c in candidates)
        candidates.sort(key=lambda c: (c.get("line") or 0, c.get("col") or 0, c["key"])
                        if placed else (c["key"],))  # fmt: skip
        for k, candidate in zip(sorted(members), candidates, strict=True):
            out[k] = ("tie", "twins", [candidate])
    return out


def tie_group(olds: list[dict], new: list[dict], slug: str,
              alone: frozenset[int] = frozenset(), judged_all: list[dict] | None = None,
              verdicts: list[str] | None = None) -> list[Said]:  # fmt: skip
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
            by_rule = _lineless(olds[k], new, judged_all or olds, counts, slug)
        if by_rule is None and k in found and new[found[k][0]].get("forms"):
            by_rule = _form_entry(olds[k], new, judged_all or olds, counts, found[k][0],
                                  how[k].startswith("form:"))  # fmt: skip
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
        if kind in (None, "taken") and sum(_alike(olds[k], f, slug)
                                           for f in judged_all or olds) > 1:  # fmt: skip
            # Twins of the judged run at one place: which is which is no pass's to say.
            kind = "several"
        if kind is None and not listed:
            kind = "none"  # its one candidate carries no key
        if kind is None:
            out.append(("tie", how[k], listed[:1]))
        else:
            if kind == "none":
                code = (olds[k].get("gate"), olds[k].get("code"))
                listed = _candidates(new, [i for i, f in enumerate(new)
                                           if (f.get("gate"), f.get("code")) == code][:3], {})
            out.append((kind, how.get(k, ""), listed))
    families = _families(out, olds, judged_all or olds, counts, slug)
    return _twins(families, olds, verdicts or ["true"] * len(olds), slug)


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


def check_decided(found: dict, judged: set, tied: str, keys_of) -> dict:
    """The author's decisions, each refused unless its judged finding is one of the judged
    set and its key is in the run of the ties (a family's where it says `family`), or null."""
    for (slug, report, index), tie in found.items():
        if (slug, report, index) not in judged:
            raise CorpusError(f"{DECIDED.as_posix()}: {slug} {report} {index} is no judged "
                              "finding")  # fmt: skip
        if tie.key is not None and not keys_of(slug, report).count(tie.key, tie.family):
            raise CorpusError(f"{DECIDED.as_posix()}: {tie.key} is not in {tied}'s {slug} "
                              f"{report}")  # fmt: skip
    return found


def render_tie(result: dict) -> str:
    to_decide = sum(result["by_kind"][k] for k in TO_DECIDE)
    lines = [f"## Ties: {result['judged_run']} to {result['run']}", "",
             f"Tied: {result['tied']} ({result['fallback']} to a key from the context), by "
             f"{result['by_pass']}. Not tied: {result['ambiguous']}, of them {to_decide} for "
             f"the author ({AMBIGUOUS.as_posix()}) and the rest for the matcher "
             f"({UNTIED.as_posix()}).", "",
             "| why not tied | judged findings |", "| --- | ---: |"]  # fmt: skip
    lines += [f"| {KINDS[k]} | {n} |" for k, n in result["by_kind"].items()]
    return "\n".join(lines) + "\n"


def scheme_note(tied: int, schemes: list[int]) -> str:
    """What the gate or the measure says where the keys' schemes differ, naming each."""
    if len(set(schemes)) == 1:
        return (f"the ties are of key scheme {tied} and the run{'s' * (len(schemes) > 1)} of "
                f"scheme {schemes[0]}: paired by message; tie again against a run of scheme "
                f"{schemes[0]}")  # fmt: skip
    base, new = schemes
    ties = "" if tied == base else f" (the ties are of scheme {tied})"
    return (f"keys changed scheme ({base} \N{RIGHTWARDS ARROW} {new}){ties}: paired by "
            "message; tie again after this merges")  # fmt: skip
