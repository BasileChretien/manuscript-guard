"""How often the review panel finds the defects we know, and how it rates them (item 53).

Run by hand, never by pytest or CI. It produces a report, never a gate.

The example's round-1 panel recorded four major findings, all fixed later. The manuscript it
read is the example's first, at commit `PREFIX`: its records and the fixes came in together
in the next commit (34c55537), and the records were stamped again with each change after,
so the digest they give now, bcb8549c..., is of a version that has the fixes (834361a6; the
first run of this measurement took that one, and is not reported). This builds four copies of
the example, each with that round's panel and nothing else in `review/`:

* **pre-fix**, the version the panel read, asked twice over (`SAMPLES` replies each time),
  so that a difference between versions no larger than the spread between the two is noise;
* **current**, the fixed version: what the panel still calls major there, and whether it
  raises a fixed defect again;
* **blank**, the pre-fix version cut to its title and abstract: a reviewer can raise
  "duplicate reports" without reading the paper, and that is no evidence of reading. Its
  reviewers are sent what every reviewer is besides the manuscript: the paper's facts from
  paper.yaml, the journal's profile and the reporting checklist, DEMO-OBS, whose item 3 asks
  how records were selected;
* **minor**, the current version with two minor defects planted (`PLANTED`), to count how
  often a minor defect is rated major, which forces an answer from the author in G11.

Steps, each reading and writing under one working folder, which `prepare` wants empty:

    python tools/panel_measure.py prepare --work DIR   # the copies and every request
    python tools/panel_measure.py answer --work DIR --model opus   # or answer them another way
    (each DIR/requests/<id>.json, its system and user text, answered in DIR/replies/<id>.txt)
    python tools/panel_measure.py score --work DIR     # settles what it can; DIR/adjudicate.yaml
    python tools/panel_measure.py adjudicate --work DIR --model opus
    (or fill in each item's `defects` in DIR/adjudicate.yaml by hand, not knowing where it
    came from: the ids it raises, separated by commas, or none)
    python tools/panel_measure.py report --work DIR    # DIR/report.md, written by this script only

A request is exactly what `review --run --dry-run` writes for the copy, so a reply may come
from a provider's API, the panel's own `review --run`, or any other way of putting the text
to a model. The ids are random, and the adjudication file is shuffled and carries nothing that
says which copy, reviewer or sample a finding came from, not even the finding's `where`
("Abstract" would say which copy). Findings of known grade are mixed in, to measure the
adjudicator. Defects are those of `tools/data/panel-rubric.yaml`, written before any reply
was read. Each defect is counted on every copy, in the replies of the reviewers whose remit
the rubric says asks about it; the report marks the copies that do not show it, where a
count is a false finding or, as often, another finding in the defect's words. Recall, and
what is counted on the clean version, are reported, never precision, since planted defects
have no real prevalence.

A finding settled by words is given the one defect whose words it uses, and not another it
raises in other words. The adjudicator does not see a finding's `where`, so a defect named
only there ("Methods, DEMO-OBS item 3") cannot be given to it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import uuid
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from manuscript_guard.panel.reply import ReplyRefused, parse_reply  # noqa: E402

RUBRIC = ROOT / "tools" / "data" / "panel-rubric.yaml"
#: The commit whose example manuscript the round-1 panel read (manuscript_sha256 bcb8549c...).
PREFIX = "e6a8cca6"
SAMPLES = 3
#: The copies, each from a source and each asked `SAMPLES` times; pre-fix twice over.
COPIES = {"pre-fix": "pre-fix", "pre-fix-repeat": "pre-fix", "current": "current",
          "blank": "pre-fix", "minor": "current"}  # fmt: skip
#: The two minor defects put into the current example: each an exact replacement, which
#: has to apply once or the copy is refused.
PLANTED = (
    ("manuscript/main.md", "Each record carries a unique report identifier",
     "Each record carries a unique ICSR identifier"),
    ("results/01_disproportionality.json", "Reports by drug group. Values are n (%) unless stated.",
     "Reports by drug group."),
)  # fmt: skip
#: Any model of any listed provider: only the request bodies are used.
MODEL = "anthropic/claude-opus-5-5"


# ------------------------------------------------------------------------------ prepare


def example_at(revision: str, into: Path, repo: Path = ROOT) -> Path:
    """`repo`'s example/ as it was at `revision`, written under `into`."""
    archive = subprocess.run(["git", "archive", revision, "example"], cwd=repo,
                             capture_output=True, check=True).stdout  # fmt: skip
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(into, filter="data")
        else:  # Python before 3.10.12, which has no filters; the archive is our own
            tar.extractall(into)
    return into / "example"


def _round_one_panel(source: Path) -> str:
    return (source / "review" / "panel-1.yaml").read_text(encoding="utf-8")


def _cut_to_abstract(project: Path) -> None:
    """The manuscript as its title and abstract alone: the first file to the end of the
    section headed Abstract, every other manuscript file gone."""
    folder = project / "manuscript"
    main = folder / "main.md"
    text = main.read_text(encoding="utf-8")
    start = re.search(r"(?m)^#{1,2}\s+Abstract\b.*$", text)
    if start is None:
        raise SystemExit(f"{main}: no Abstract heading to cut to")
    after = re.search(r"(?m)^#{1,2}\s+\S", text[start.end():])
    kept = text[: start.end() + (after.start() if after else len(text) - start.end())]
    for path in folder.rglob("*"):
        if path.is_file() and path != main:
            path.unlink()
    main.write_text(kept.rstrip() + "\n", encoding="utf-8", newline="\n")


def _plant(project: Path) -> None:
    for relative, old, new in PLANTED:
        path = project / relative
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"{relative}: the planted defect does not apply once")
        path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
        if path.suffix == ".json":
            import hashlib

            digest = path.with_name(path.name + ".sha256")
            if digest.exists():
                digest.write_text(hashlib.sha256(path.read_bytes()).hexdigest() + "\n",
                                  encoding="utf-8", newline="\n")  # fmt: skip


def make_copy(name: str, source: Path, panel: str, into: Path) -> Path:
    """One copy of the example: `source`'s files, the round-1 panel alone in review/, a
    model to build requests for, and the copy's own change."""
    project = into / name
    shutil.copytree(source, project)
    shutil.rmtree(project / "review", ignore_errors=True)
    shutil.rmtree(project / "build", ignore_errors=True)
    (project / "review").mkdir()
    (project / "review" / "panel-1.yaml").write_text(panel, encoding="utf-8", newline="\n")
    paper = project / "paper.yaml"
    text = paper.read_text(encoding="utf-8")
    if re.search(r"(?m)^review:", text):
        raise SystemExit(f"{paper}: already has a review: block")
    paper.write_text(text.rstrip() + f"\n\nreview:\n  models: [{MODEL}]\n", encoding="utf-8",
                     newline="\n")  # fmt: skip
    if name == "blank":
        _cut_to_abstract(project)
    if name == "minor":
        _plant(project)
    return project


def requests_of(project: Path) -> list[tuple[str, dict]]:
    """Each reviewer's request, as `review --run --dry-run` writes it for `project`: the
    system text and the user text."""
    code = "import sys; from manuscript_guard.cli import main; sys.exit(main(sys.argv[1:]))"
    # This tree's package, not whichever one is installed.
    path = os.pathsep.join(filter(None, [str(ROOT / "src"), os.environ.get("PYTHONPATH")]))
    run = subprocess.run([sys.executable, "-c", code, "review", "--run", "--dry-run"],
                         cwd=project, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": path})  # fmt: skip
    if run.returncode != 0:
        said = run.stdout + run.stderr
        raise SystemExit(f"{project.name}: review --run --dry-run failed:\n{said}")
    found = []
    for path in sorted((project / "build" / "review" / "round-1" / "dry-run").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        user = body["messages"][0]["content"]
        found.append((path.name.split(".", 1)[0], {"system": body["system"], "user": user}))
    return found


def prepare(work: Path, sources: dict[str, Path], seed: int | None = None) -> dict:
    """The copies under `work`, and each request under `work`/requests, by a random id; the
    key from id to copy, reviewer and sample in `work`/key.yaml."""
    made = [name for name in ("key.yaml", "requests", "replies", "copies")
            if (work / name).exists()]  # fmt: skip
    if made:
        raise SystemExit(f"{work}: already prepared, or in part ({', '.join(made)}); "
                         "prepare in an empty folder")  # fmt: skip
    # The round-1 panel, unchanged since it was written; the first version has none.
    panel = _round_one_panel(sources["current"])
    (work / "requests").mkdir(parents=True)
    (work / "replies").mkdir()
    rng = random.Random(seed)
    key = {}
    for name, source in COPIES.items():
        project = make_copy(name, sources[source], panel, work / "copies")
        for reviewer, request in requests_of(project):
            for sample in range(1, SAMPLES + 1):
                ident = uuid.UUID(int=rng.getrandbits(128)).hex[:12]
                key[ident] = {"copy": name, "reviewer": reviewer, "sample": sample}
                (work / "requests" / f"{ident}.json").write_text(
                    json.dumps(request, ensure_ascii=False, indent=1), encoding="utf-8")
    _dump(work / "key.yaml", key)
    return key


# ------------------------------------------------------------------------------- answer


def _json_object(out: str) -> dict:
    """What Claude Code printed, as the JSON object it should be, or empty: cut short or
    garbled output is a failed call, which the caller refuses with the output itself."""
    try:
        said = json.loads(out)
    except json.JSONDecodeError:
        return {}
    return said if isinstance(said, dict) else {}


def answer_with_claude_code(work: Path, model: str, claude: list[str]) -> dict:
    """Each request not yet answered put to `model` through Claude Code's headless mode, as
    the panel would put it: its system text as the whole system prompt, no tools, and
    `--safe-mode`, so that no CLAUDE.md, memory, skill or plugin of the machine reaches the
    reviewer. Billed as the account running it is. The tokens and the cost Claude Code
    reports at API prices are kept in `work`/usage.yaml."""
    usage_path = work / "usage.yaml"
    usage = _load(usage_path) if usage_path.exists() else {}
    for path in sorted((work / "requests").glob("*.json")):
        reply = work / "replies" / f"{path.stem}.txt"
        if reply.exists():
            continue
        request = json.loads(path.read_text(encoding="utf-8"))
        system = work / "system.txt"
        system.write_text(request["system"], encoding="utf-8", newline="\n")
        run = subprocess.run(
            [*claude, "-p", "--safe-mode", "--system-prompt-file", str(system), "--tools", "",
             "--model", model, "--output-format", "json", "--max-turns", "1"],
            # Bytes, not text: in text mode Windows writes each line end as CRLF, and the
            # request would not be the panel's byte for byte.
            input=request["user"].encode("utf-8"), capture_output=True,
            cwd=work, timeout=600,
        )  # fmt: skip
        out, err = run.stdout.decode("utf-8", "replace"), run.stderr.decode("utf-8", "replace")
        said = _json_object(out)
        if run.returncode != 0 or said.get("is_error") or "result" not in said:
            failed = out[-400:] + err[-400:]
            raise SystemExit(f"{path.stem}: claude -p failed: {failed}")
        reply.write_text(said["result"], encoding="utf-8", newline="\n")
        tokens = said.get("usage") or {}
        usage[path.stem] = {
            "input": tokens.get("input_tokens", 0) + tokens.get("cache_creation_input_tokens", 0)
            + tokens.get("cache_read_input_tokens", 0),
            "output": tokens.get("output_tokens", 0),
            "cost_usd": said.get("total_cost_usd"),
        }  # fmt: skip
        _dump(usage_path, usage)
    return {"answered": len(usage), "cost_usd": round(sum(u["cost_usd"] or 0 for u in
                                                          usage.values()), 4)}  # fmt: skip


# -------------------------------------------------------------------------------- score


def _dump(path: Path, document: object) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100),
                    encoding="utf-8", newline="\n")  # fmt: skip


def _load(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def matched(finding: dict, rubric: dict) -> list[str]:
    """The defects whose words a finding uses, in its `where` or its text."""
    said = f"{finding.get('where') or ''} {finding.get('finding') or ''}"
    return [defect["id"] for defect in rubric["defects"]
            if any(re.search(words, said, re.IGNORECASE) for words in defect["words"])]  # fmt: skip


#: What scoring writes, and what is adjudicated from it: a second scoring would shuffle the
#: blind file anew, and adjudications already made would be read against other findings.
_SCORED = ("adjudicate.yaml", "adjudication-key.yaml", "adjudicate-model.yaml", "check.yaml")


def score(work: Path, rubric: dict, seed: int | None = None) -> dict:
    """Each reply read: its major and minor findings settled by the rubric's words where
    exactly one defect matches, and the rest, with the controls, shuffled into
    `work`/adjudicate.yaml, where each may be given several defects. A comment is
    never settled by its words: it may praise what a defect would lack ("the 2 x 2 table
    lets a reader recompute the estimate"), which the words cannot tell from saying it is
    missing. (The first scoring of the 2026-10-19 run settled comments too, and 20 were
    taken as raising a defect; this was changed before any finding was adjudicated.)"""
    done = [name for name in _SCORED if (work / name).exists()]
    if done:
        raise SystemExit(f"{work}: already scored ({', '.join(done)}); remove these to score "
                         "again, and adjudicate again after")  # fmt: skip
    key = _load(work / "key.yaml")
    readings: dict[str, dict] = {}
    blind: list[dict] = []
    for ident in key:
        path = work / "replies" / f"{ident}.txt"
        if not path.exists():
            raise SystemExit(f"{path}: no reply yet")
        try:
            parsed = parse_reply(path.read_text(encoding="utf-8"))
        except ReplyRefused as exc:
            readings[ident] = {"refused": str(exc), "findings": []}
            continue
        findings = []
        for at, finding in enumerate(parsed.get("findings") or []):
            settled = matched(finding, rubric)
            if finding.get("severity") not in ("major", "minor"):
                settled = []
            findings.append({"severity": finding.get("severity"),
                             "defects": settled if len(settled) == 1 else None})  # fmt: skip
            if len(settled) != 1:
                text = " ".join(str(finding.get("finding") or "").split())
                blind.append({"from": [ident, at], "finding": text})
        readings[ident] = {"verdict": parsed.get("verdict"), "findings": findings}
    for at, control in enumerate(rubric["controls"]):
        blind.append({"from": ["control", at], "finding": control["finding"]})
    random.Random(seed).shuffle(blind)
    items = [{"item": n, "finding": b["finding"], "defects": ""}
             for n, b in enumerate(blind, start=1)]  # fmt: skip
    _dump(work / "adjudicate.yaml", {
        "about": "For each finding, write the ids of the defects it raises, separated by "
                 "commas, or none. Defects: "
                 + "; ".join(f"{d['id']}: {d['about']}" for d in rubric["defects"]),
        "items": items,
    })  # fmt: skip
    _dump(work / "adjudication-key.yaml", {n: b["from"] for n, b in enumerate(blind, start=1)})
    _dump(work / "readings.yaml", readings)
    return {"replies": len(readings), "settled": sum(f["defects"] is not None for r in
            readings.values() for f in r["findings"]), "to_adjudicate": len(items)}  # fmt: skip


# ----------------------------------------------------------------- adjudicated by a model

#: How many findings one call to the adjudicating model is given.
BATCH = 40
#: How many of the model's adjudications a person checks, beside the controls.
CHECKED = 40
_ADJUDICATOR = (
    "You adjudicate findings of reviewers of a manuscript against a fixed list of defects. "
    "For each finding, say which defects it raises, if any: a finding raises a defect only "
    "where it says the thing is missing or wrong, not where it praises it or mentions it. "
    "Answer with one JSON list and nothing else, one object per finding, in order: "
    '[{{"item": <its number>, "defects": [<the ids it raises; none, an empty list>]}}]. '
    "The defects:\n{defects}"
)


def defects_of(answer: object, known: set[str], where: str) -> list[str]:
    """An adjudication as a list of defect ids: a list, or ids separated by commas, or
    "none", which is the empty list. Blank, or naming no defect of the rubric, is refused."""
    said = answer if isinstance(answer, list) else str(answer or "").split(",")
    ids = [str(one).strip() for one in said if str(one).strip()]
    if ids == ["none"] or (isinstance(answer, list) and not ids):
        return []
    wrong = [one for one in ids if one not in known] or ([] if ids else ["(blank)"])
    if wrong:
        raise SystemExit(f"{where}: {', '.join(map(repr, wrong))} is no defect id or none")
    return sorted(set(ids))


def _model_said(run: subprocess.CompletedProcess, batch: list[dict], known: set[str]) -> dict:
    """The adjudicating model's answers for `batch`, from Claude Code's output; a call that
    failed, or an answer that is no list of the batch's items, is refused with what it said."""
    out, err = run.stdout.decode("utf-8", "replace"), run.stderr.decode("utf-8", "replace")
    said = _json_object(out)
    items = f"items {batch[0]['item']} to {batch[-1]['item']}"
    if run.returncode != 0 or said.get("is_error") or "result" not in said:
        raise SystemExit(f"{items}: claude -p failed: {out[-400:]}{err[-400:]}")
    text = str(said["result"])
    start, end = text.find("["), text.rfind("]")
    try:
        given = json.loads(text[start:end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError:
        given = None
    asked = {i["item"] for i in batch}
    if not isinstance(given, list) or not all(
            isinstance(a, dict) and a.get("item") in asked for a in given):  # fmt: skip
        raise SystemExit(f"{items}: the model's answer is no list of them: {text[:400]}")
    return {a["item"]: defects_of(a.get("defects"), known, f"item {a['item']}") for a in given}


def adjudicate_with_model(work: Path, rubric: dict, model: str, claude: list[str],
                          seed: int | None = None) -> dict:  # fmt: skip
    """Every blind finding adjudicated by `model`, through Claude Code as `answer` puts the
    requests, into `work`/adjudicate-model.yaml; and `work`/check.yaml, a random `CHECKED`
    of them with the controls, shuffled and blank, for a person to adjudicate as a check on
    the model (chosen by Basile on 2026-10-19 in place of scoring all of them himself)."""
    items = _load(work / "adjudicate.yaml")["items"]
    known = {d["id"] for d in rubric["defects"]}
    defects = "\n".join(f"- {d['id']}: {d['about']}" for d in rubric["defects"])
    system = work / "adjudicator.txt"
    system.write_text(_ADJUDICATOR.format(defects=defects), encoding="utf-8", newline="\n")
    answers: dict[int, list[str]] = {}
    for start in range(0, len(items), BATCH):
        batch = [{"item": i["item"], "finding": i["finding"]}
                 for i in items[start:start + BATCH]]  # fmt: skip
        run = subprocess.run(
            [*claude, "-p", "--safe-mode", "--system-prompt-file", str(system), "--tools", "",
             "--model", model, "--output-format", "json", "--max-turns", "1"],
            input=json.dumps(batch, ensure_ascii=False).encode("utf-8"), capture_output=True,
            cwd=work, timeout=900,
        )  # fmt: skip
        answers.update(_model_said(run, batch, known))
    missing = {i["item"] for i in items} - set(answers)
    if missing:
        raise SystemExit(f"the model adjudicated no answer for items {sorted(missing)}")
    _dump(work / "adjudicate-model.yaml", dict(sorted(answers.items())))
    key = _load(work / "adjudication-key.yaml")
    rng = random.Random(seed)
    findings = [i for i in items if key[i["item"]][0] != "control"]
    controls = [i for i in items if key[i["item"]][0] == "control"]
    checked = rng.sample(findings, min(CHECKED, len(findings))) + controls
    rng.shuffle(checked)
    _dump(work / "check.yaml", {
        "about": _load(work / "adjudicate.yaml")["about"],
        "items": [{**i, "defects": ""} for i in checked],
    })  # fmt: skip
    return {"adjudicated": len(answers), "to_check": len(checked)}


# ------------------------------------------------------------------------------- report


def _answers(path: Path, rubric: dict) -> dict[int, list[str]]:
    known = {d["id"] for d in rubric["defects"]}
    return {item["item"]: defects_of(item.get("defects"), known, f"{path.name} item {item['item']}")
            for item in _load(path)["items"]}  # fmt: skip


def _filled(path: Path) -> bool:
    """Whether a person has begun the adjudication file at `path`."""
    return path.exists() and any(i.get("defects") not in ("", None)
                                 for i in _load(path)["items"])  # fmt: skip


def _control(rubric: dict, at: int) -> list[str]:
    defect = rubric["controls"][at]["defect"]
    return [] if defect == "none" else [defect]


def _adjudicated(work: Path, rubric: dict) -> tuple[dict, float]:
    """The readings with each blind finding's defects filled in, and the adjudicator's
    agreement with the controls: a person's, from `adjudicate.yaml`, or, where a model
    adjudicated, the model's, from `adjudicate-model.yaml`."""
    readings = _load(work / "readings.yaml")
    key = _load(work / "adjudication-key.yaml")
    model = work / "adjudicate-model.yaml"
    known = {d["id"] for d in rubric["defects"]}
    answers = ({int(k): defects_of(v, known, f"{model.name} item {k}")
                for k, v in _load(model).items()} if model.exists()
               else _answers(work / "adjudicate.yaml", rubric))  # fmt: skip
    agreed, controls = 0, 0
    for item, (source, at) in key.items():
        if item not in answers:
            raise SystemExit(f"item {item} has no adjudication")
        if source == "control":
            controls += 1
            agreed += answers[item] == _control(rubric, at)
        else:
            readings[source]["findings"][at]["defects"] = answers[item]
    return readings, agreed / controls if controls else float("nan")


def tally(readings: dict, key: dict, rubric: dict) -> dict:
    """For each copy and defect: of the replies from reviewers asked about it, how many
    raised it, and how many rated it major, in all and by reviewer; and the major findings
    per reply."""
    def counts() -> defaultdict:
        return defaultdict(lambda: [0, 0, 0])

    by_copy: dict[str, dict] = defaultdict(counts)
    by_reviewer: dict[tuple[str, str], dict] = defaultdict(counts)
    majors: dict[str, list[int]] = defaultdict(list)
    for ident, reading in readings.items():
        where = key[ident]
        raised: dict[str, str] = {}
        for finding in reading["findings"]:
            for defect in finding["defects"] or []:
                worst = raised.get(defect)
                raised[defect] = "major" if "major" in (worst, finding["severity"]) \
                    else finding["severity"]  # fmt: skip
        majors[where["copy"]].append(sum(f["severity"] == "major" for f in reading["findings"]))
        for defect in rubric["defects"]:
            if where["reviewer"] not in defect["asked"]:
                continue
            for total in (by_copy[where["copy"]][defect["id"]],
                          by_reviewer[where["copy"], defect["id"]][where["reviewer"]]):  # fmt: skip
                total[0] += 1
                total[1] += defect["id"] in raised
                total[2] += raised.get(defect["id"]) == "major"
    reviewers: dict[str, dict] = defaultdict(dict)
    for (copy, defect), each in by_reviewer.items():
        reviewers[copy][defect] = {r: list(v) for r, v in sorted(each.items())}
    return {"defects": {c: {d: list(v) for d, v in ds.items()} for c, ds in by_copy.items()},
            "by_reviewer": dict(reviewers), "majors": dict(majors)}  # fmt: skip


def checked(work: Path, rubric: dict) -> tuple[int, int, int, int]:
    """Of the findings a person checked, how many the model's adjudication agrees with;
    and of the controls, how many the person got right."""
    key = _load(work / "adjudication-key.yaml")
    known = {d["id"] for d in rubric["defects"]}
    model = {int(k): defects_of(v, known, f"item {k}")
             for k, v in _load(work / "adjudicate-model.yaml").items()}  # fmt: skip
    agree = seen = right = controls = 0
    for item, answer in _answers(work / "check.yaml", rubric).items():
        source, at = key[item]
        if source == "control":
            controls += 1
            right += answer == _control(rubric, at)
        else:
            seen += 1
            agree += answer == model[item]
    return agree, seen, right, controls


def report(work: Path, rubric: dict) -> str:
    readings, agreement = _adjudicated(work, rubric)
    key = _load(work / "key.yaml")
    counted = tally(readings, key, rubric)
    by_model = (work / "adjudicate-model.yaml").exists()
    lines = ["# The review panel against defects we know", "",
             f"Replies: {len(readings)}, of which refused unread: "
             f"{sum('refused' in r for r in readings.values())}. "
             f"The blind findings were adjudicated by {'a model' if by_model else 'a person'}; "
             f"agreement with the controls: {agreement:.0%}."]  # fmt: skip
    if by_model:
        if _filled(work / "check.yaml"):
            agree, seen, right, controls = checked(work, rubric)
            lines.append(f"A person checked {seen} of the model's adjudications and "
                         f"agreed with {agree}, and got {right} of {controls} controls "
                         f"right.")  # fmt: skip
        else:
            lines.append("No person checked the model's adjudications: its agreement with "
                         "the controls is the only measure of it.")  # fmt: skip
    lines.append("")
    for copy in COPIES:
        shown = {d["id"] for d in rubric["defects"] if COPIES[copy] in d["seen_in"] or
                 copy in d["seen_in"]}  # fmt: skip
        if copy == "blank":
            shown = {d["id"] for d in rubric["defects"] if "pre-fix" in d["seen_in"]}
        lines += [f"## {copy}", "", "| Defect | Asked | Raised | Rated major |",
                  "|---|---|---|---|"]  # fmt: skip
        for defect, (asked, raised, major) in sorted(counted["defects"].get(copy, {}).items()):
            note = "" if defect in shown else " (not in this copy)"
            lines.append(f"| {defect}{note} | {asked} | {raised} | {major} |")
            # A defect several remits ask about, by reviewer: a remit that does not reach it
            # would otherwise hide the one that does.
            each = counted["by_reviewer"][copy][defect]
            if len(each) > 1:
                lines += [f"| {defect}: {reviewer} | {a} | {r} | {m} |"
                          for reviewer, (a, r, m) in each.items()]  # fmt: skip
        each = counted["majors"].get(copy, [])
        lines += ["", f"Major findings per reply: {each} (mean "
                  f"{sum(each) / len(each) if each else float('nan'):.1f}).", ""]  # fmt: skip
    text = "\n".join(lines)
    (work / "report.md").write_text(text, encoding="utf-8", newline="\n")
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=("prepare", "answer", "score", "adjudicate", "report"))
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--model", help="answer: the model Claude Code puts each request to")
    args = parser.parse_args(argv)
    rubric = _load(RUBRIC)
    if args.step == "prepare":
        if args.work.exists() and any(args.work.iterdir()):
            raise SystemExit(f"{args.work}: not empty; prepare in an empty folder")
        sources = {"pre-fix": example_at(PREFIX, args.work / "sources" / "pre-fix"),
                   "current": example_at("HEAD", args.work / "sources" / "current")}  # fmt: skip
        key = prepare(args.work, sources)
        print(f"{len(key)} requests in {args.work / 'requests'}")
    elif args.step == "answer":
        claude = shutil.which("claude")
        if claude is None or not args.model:
            raise SystemExit("answer needs claude on PATH and --model")
        print(answer_with_claude_code(args.work, args.model, [claude]))
    elif args.step == "adjudicate":
        claude = shutil.which("claude")
        if claude is None or not args.model:
            raise SystemExit("adjudicate needs claude on PATH and --model")
        print(adjudicate_with_model(args.work, rubric, args.model, [claude]))
    elif args.step == "score":
        print(score(args.work, rubric))
    else:
        print(report(args.work, rubric))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
