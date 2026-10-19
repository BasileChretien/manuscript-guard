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
  "duplicate reports" without reading anything, and that is no evidence of reading;
* **minor**, the current version with two minor defects planted (`PLANTED`), to count how
  often a minor defect is rated major, which forces an answer from the author in G11.

Steps, each reading and writing under one working folder:

    python tools/panel_measure.py prepare --work DIR   # the copies and every request
    python tools/panel_measure.py answer --work DIR --model opus   # or answer them another way
    (each DIR/requests/<id>.json, its system and user text, answered in DIR/replies/<id>.txt)
    python tools/panel_measure.py score --work DIR     # settles what it can; DIR/adjudicate.yaml
    (fill in each item's `defect` in DIR/adjudicate.yaml, not knowing where it came from)
    python tools/panel_measure.py report --work DIR    # DIR/report.md, written by this script only

A request is exactly what `review --run --dry-run` writes for the copy, so a reply may come
from a provider's API, the panel's own `review --run`, or any other way of putting the text
to a model. The ids are random, and the adjudication file is shuffled and carries nothing that
says which copy, reviewer or sample a finding came from. Findings of known grade are mixed in,
to measure the adjudicator. Defects are those of `tools/data/panel-rubric.yaml`, written
before any reply was read. Only a defect the copy shows and the reviewer's remit asks about is
scored; recall and false findings on the clean version are reported, never precision, since
planted defects have no real prevalence.
"""

from __future__ import annotations

import argparse
import io
import json
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
        tar.extractall(into, filter="data")
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
    run = subprocess.run([sys.executable, "-c", code, "review", "--run", "--dry-run"],
                         cwd=project, capture_output=True, text=True)  # fmt: skip
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
    if (work / "key.yaml").exists():
        raise SystemExit(f"{work}: already prepared")
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
        system.write_text(request["system"], encoding="utf-8")
        run = subprocess.run(
            [*claude, "-p", "--safe-mode", "--system-prompt-file", str(system), "--tools", "",
             "--model", model, "--output-format", "json", "--max-turns", "1"],
            # Bytes, not text: in text mode Windows writes each line end as CRLF, and the
            # request would not be the panel's byte for byte.
            input=request["user"].encode("utf-8"), capture_output=True,
            cwd=work, timeout=600,
        )  # fmt: skip
        out, err = run.stdout.decode("utf-8", "replace"), run.stderr.decode("utf-8", "replace")
        said = json.loads(out) if out.strip().startswith("{") else {}
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


def score(work: Path, rubric: dict, seed: int | None = None) -> dict:
    """Each reply read: its major and minor findings settled by the rubric's words where
    exactly one defect matches, and the rest, with the controls, shuffled into
    `work`/adjudicate.yaml. A comment is never settled by its words: it may praise what
    a defect would lack ("the 2 x 2 table lets a reader recompute the estimate"), which
    the words cannot tell from saying it is missing. (The first scoring of the 2026-10-19
    run settled comments too, and 20 were taken as raising a defect; this was changed
    before any finding was adjudicated.)"""
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
                             "defect": settled[0] if len(settled) == 1 else None})  # fmt: skip
            if len(settled) != 1:
                text = " ".join(str(finding.get("finding") or "").split())
                blind.append({"from": [ident, at], "where": finding.get("where") or "",
                              "finding": text})  # fmt: skip
        readings[ident] = {"verdict": parsed.get("verdict"), "findings": findings}
    for at, control in enumerate(rubric["controls"]):
        blind.append({"from": ["control", at], "where": control["where"],
                      "finding": control["finding"]})  # fmt: skip
    random.Random(seed).shuffle(blind)
    items = [{"item": n, "where": b["where"], "finding": b["finding"], "defect": ""}
             for n, b in enumerate(blind, start=1)]  # fmt: skip
    _dump(work / "adjudicate.yaml", {
        "about": "For each finding, write the id of the defect it raises, or none. Defects: "
                 + "; ".join(f"{d['id']}: {d['about']}" for d in rubric["defects"]),
        "items": items,
    })  # fmt: skip
    _dump(work / "adjudication-key.yaml", {n: b["from"] for n, b in enumerate(blind, start=1)})
    _dump(work / "readings.yaml", readings)
    return {"replies": len(readings), "settled": sum(f["defect"] is not None for r in
            readings.values() for f in r["findings"]), "to_adjudicate": len(items)}  # fmt: skip


# ----------------------------------------------------------------- adjudicated by a model

#: How many findings one call to the adjudicating model is given.
BATCH = 40
#: How many of the model's adjudications a person checks, beside the controls.
CHECKED = 40
_ADJUDICATOR = (
    "You adjudicate findings of reviewers of a manuscript against a fixed list of defects. "
    "For each finding, say which one defect it raises, or none: a finding raises a defect "
    "only where it says the thing is missing or wrong, not where it praises it or mentions "
    "it. Answer with one JSON list and nothing else, one object per finding, in order: "
    '[{{"item": <its number>, "defect": "<one id or none>"}}]. The defects:\n{defects}'
)


def adjudicate_with_model(work: Path, rubric: dict, model: str, claude: list[str],
                          seed: int | None = None) -> dict:  # fmt: skip
    """Every blind finding adjudicated by `model`, through Claude Code as `answer` puts the
    requests, into `work`/adjudicate-model.yaml; and `work`/check.yaml, a random `CHECKED`
    of them with the controls, shuffled and blank, for a person to adjudicate as a check on
    the model (chosen by Basile on 2026-10-19 in place of scoring all of them himself)."""
    items = _load(work / "adjudicate.yaml")["items"]
    known = {d["id"] for d in rubric["defects"]} | {"none"}
    defects = "\n".join(f"- {d['id']}: {d['about']}" for d in rubric["defects"])
    system = work / "adjudicator.txt"
    system.write_text(_ADJUDICATOR.format(defects=defects), encoding="utf-8")
    answers: dict[int, str] = {}
    for start in range(0, len(items), BATCH):
        batch = [{"item": i["item"], "where": i["where"], "finding": i["finding"]}
                 for i in items[start:start + BATCH]]  # fmt: skip
        run = subprocess.run(
            [*claude, "-p", "--safe-mode", "--system-prompt-file", str(system), "--tools", "",
             "--model", model, "--output-format", "json", "--max-turns", "1"],
            input=json.dumps(batch, ensure_ascii=False).encode("utf-8"), capture_output=True,
            cwd=work, timeout=900,
        )  # fmt: skip
        said = json.loads(run.stdout.decode("utf-8", "replace") or "{}")
        text = str(said.get("result", "")).strip().removeprefix("```json").strip("`\n ")
        for answer in json.loads(text):
            if answer["defect"] not in known:
                raise SystemExit(f"item {answer['item']}: {answer['defect']!r} is no defect")
            answers[int(answer["item"])] = answer["defect"]
    missing = {i["item"] for i in items} - set(answers)
    if missing:
        raise SystemExit(f"the model adjudicated no answer for items {sorted(missing)}")
    _dump(work / "adjudicate-model.yaml", answers)
    key = _load(work / "adjudication-key.yaml")
    rng = random.Random(seed)
    findings = [i for i in items if key[i["item"]][0] != "control"]
    controls = [i for i in items if key[i["item"]][0] == "control"]
    checked = rng.sample(findings, min(CHECKED, len(findings))) + controls
    rng.shuffle(checked)
    _dump(work / "check.yaml", {
        "about": _load(work / "adjudicate.yaml")["about"],
        "items": [{**i, "defect": ""} for i in checked],
    })  # fmt: skip
    return {"adjudicated": len(answers), "to_check": len(checked)}


# ------------------------------------------------------------------------------- report


def _answers(path: Path) -> dict[int, str]:
    return {item["item"]: str(item.get("defect") or "").strip()
            for item in _load(path)["items"]}  # fmt: skip


def _adjudicated(work: Path, rubric: dict) -> tuple[dict, float]:
    """The readings with each blind finding's defect filled in, and the adjudicator's
    agreement with the controls: a person's, from `adjudicate.yaml`, or, where a model
    adjudicated, the model's, from `adjudicate-model.yaml`."""
    readings = _load(work / "readings.yaml")
    key = _load(work / "adjudication-key.yaml")
    model = work / "adjudicate-model.yaml"
    answers = ({int(k): v for k, v in _load(model).items()} if model.exists()
               else _answers(work / "adjudicate.yaml"))  # fmt: skip
    known = {d["id"] for d in rubric["defects"]} | {"none"}
    agreed, controls = 0, 0
    for item, (source, at) in key.items():
        answer = answers.get(item, "")
        if answer not in known:
            raise SystemExit(f"adjudicate.yaml item {item}: {answer!r} is no defect id or none")
        if source == "control":
            controls += 1
            agreed += answer == rubric["controls"][at]["defect"]
        else:
            readings[source]["findings"][at]["defect"] = None if answer == "none" else answer
    return readings, agreed / controls if controls else float("nan")


def tally(readings: dict, key: dict, rubric: dict) -> dict:
    """For each copy and defect: of the replies from reviewers asked about it, how many
    raised it, and how many rated it major; and the major findings per reply."""
    by_copy: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    majors: dict[str, list[int]] = defaultdict(list)
    for ident, reading in readings.items():
        where = key[ident]
        raised: dict[str, str] = {}
        for finding in reading["findings"]:
            if finding["defect"]:
                worst = raised.get(finding["defect"])
                raised[finding["defect"]] = "major" if "major" in (worst, finding["severity"]) \
                    else finding["severity"]  # fmt: skip
        majors[where["copy"]].append(sum(f["severity"] == "major" for f in reading["findings"]))
        for defect in rubric["defects"]:
            if where["reviewer"] not in defect["asked"]:
                continue
            counts = by_copy[where["copy"]][defect["id"]]
            counts[0] += 1
            counts[1] += defect["id"] in raised
            counts[2] += raised.get(defect["id"]) == "major"
    return {"defects": {c: {d: list(v) for d, v in ds.items()} for c, ds in by_copy.items()},
            "majors": dict(majors)}  # fmt: skip


def checked(work: Path, rubric: dict) -> tuple[int, int, int, int]:
    """Of the findings a person checked, how many the model's adjudication agrees with;
    and of the controls, how many the person got right."""
    key = _load(work / "adjudication-key.yaml")
    model = {int(k): v for k, v in _load(work / "adjudicate-model.yaml").items()}
    person = _answers(work / "check.yaml")
    known = {d["id"] for d in rubric["defects"]} | {"none"}
    agree = seen = right = controls = 0
    for item, answer in person.items():
        if answer not in known:
            raise SystemExit(f"check.yaml item {item}: {answer!r} is no defect id or none")
        source, at = key[item]
        if source == "control":
            controls += 1
            right += answer == rubric["controls"][at]["defect"]
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
        person = work / "check.yaml"
        if person.exists() and any(_answers(person).values()):
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
