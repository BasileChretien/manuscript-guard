"""`tools/corpus.py unjudged` and `agree`, and the reading of a batch's verdicts, on a made-up
mini corpus written in `tmp_path`.

Basile's decision (2026-11-21): two judges judge the loud findings no verdict accounts for,
once those of the codes not settled, then at each pull request's gate those its run adds;
their agreements count as judged, the rest go to him, with a sample of 20 agreements.
"""

from __future__ import annotations

import importlib.util
import io
import json
import random
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent


def _tool():
    spec = importlib.util.spec_from_file_location("corpus_tool", REPO / "tools" / "corpus.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["corpus_tool"] = module
    spec.loader.exec_module(module)
    return module


tool = _tool()
judging = tool.corpus_judging


def finding(gate: str, code: str, message: str, subject: str | None = None,
            severity: str = "warn", line: int | None = 10, **extra) -> dict:  # fmt: skip
    said = {"gate": gate, "code": code, "message": message, "severity": severity, "line": line,
            "path": extra.pop("path", "paper.docx"), "context": extra.pop("context", None),
            **extra}  # fmt: skip
    return {**said, "key": f"{gate}|{code}|{subject}|-"} if subject else said


def vague(n: int, subject: str | None = None) -> dict:
    return finding("G6", "vague-attribution", f"'Studies show {n}' with no citation nearby",
                   subject, line=10 + n)  # fmt: skip


SPELL = ("G14", "spelling-variant", "'color' is the American spelling of 'colour'")
#: The judged findings of the first packet, from a run with no keys, all true: ten of a code
#: that is settled, and one of a code that is not.
FIRST = [vague(n) for n in range(10)] + [finding(*SPELL, line=60)]
#: The run measured: the judged findings again, with keys, and the loud ones no verdict
#: accounts for. The comments say which `unjudged` packs, with no base and with `r0`.
R1 = {
    ("paper-a", "audit"): [
        *(vague(n, f"s{n}") for n in range(10)), finding(*SPELL, "color", line=60),
        finding("G6", "vague-attribution", "'It is known' with no citation nearby", "known",
                line=99),  # settled code; loud in r0: never  # fmt: skip
        finding("G14", "spelling-variant", "'behavior' is the American spelling", "behavior",
                line=98),  # unsettled: packed; loud in r0: not with the base  # fmt: skip
        finding("G14", "notation-percent", "'%' stands after a space", "pct", "info"),  # quiet
        finding("G2", "typed-number", "42 is typed", "42", line=30),  # packed by both
        finding("G6", "vague-attribution", "'Many argue' with no citation nearby", "many",
                line=97),  # settled: not without the base; new against r0: packed  # fmt: skip
    ],
    ("paper-a", "check"): [
        finding("G12", "plan-section-empty", "the plan's question section is empty", "plan"),
        finding("G2", "typed-number", "42 is typed", "42c", line=30),  # the audit's: left out
        finding("G3", "figure-colours-confused", "fig1.png: colours that are one colour to a "
                "reader with deuteranopia", "fig1", line=None),  # fmt: skip
        finding("G3", "figure-colours-confused", "a figure's colours are one colour to a "
                "reader with protanopia", "fig", line=None),  # names no file: all of them
        finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", "delve",
                line=70),  # packed without the base; loud in r0  # fmt: skip
    ],
    ("paper-b", "audit"): [
        finding("G7", "doi-unresolved", "10.1/abc does not resolve", "10.1/abc", line=4),
    ],
}
R0 = {
    ("paper-a", "audit"): [
        finding("G6", "vague-attribution", "'It is known' ...", "known", line=99),
        finding("G14", "spelling-variant", "'behavior' ...", "behavior", line=98),
        finding("G2", "typed-number", "42 is typed", "42", "info", line=30),  # quiet in r0
    ],
    ("paper-a", "check"): [finding("G6", "ai-phrasing", "'delve into' ...", "delve", line=70)],
    ("paper-b", "audit"): [],
}


def write_run(root: Path, name: str, reports: dict, scheme: int | None = 2) -> Path:
    for (slug, report), found in reports.items():
        folder = root / "runs" / name / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{report}.json").write_text(json.dumps({"findings": found}), "utf-8")
    if scheme is not None:
        (root / "runs" / name / "run.json").write_text(json.dumps({"scheme": scheme}), "utf-8")
    return root / "runs" / name


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus-root"
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    packet = [{"slug": "paper-a", "text": "an old scratch folder", "title": "A", "format": "docx",
               "window": "A", "reports": {"audit": {"findings": FIRST}}}]
    (root / "report" / "packets" / "field.json").write_text(json.dumps(packet), "utf-8")
    verdicts = [{"slug": "paper-a", "report": "audit", "index": i, "verdict": "true"}
                for i in range(len(FIRST))]  # fmt: skip
    (root / "report" / "judged" / "field.json").write_text(json.dumps(verdicts), "utf-8")
    for slug, fmt, main in (("paper-a", "docx", "paper.docx"), ("paper-b", "pdf", "paper.pdf")):
        (root / "corpus" / slug).mkdir(parents=True)
        (root / "corpus" / slug / "meta.json").write_text(json.dumps(
            {"slug": slug, "format": fmt, "main": main, "title": f"Paper {slug}",
             "window": "B"}), "utf-8")  # fmt: skip
    r1 = write_run(root, "r1", R1)
    project = r1 / "paper-a" / "project"
    for name in ("figures/fig1.png", "figures/fig2.png", "manuscript/media/image1.png",
                 "manuscript/main.md"):
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_text("made up", "utf-8")
    r0 = write_run(root, "r0", R0)
    (r0 / "paper-b" / "paper.txt").write_text("made up", "utf-8")
    return root


def pack(root: Path, name: str = "b1", base: str | None = None, of: str = "r1",
         **flags) -> dict:  # fmt: skip
    run = tool.Run(tool.run_folder(root, of))
    rows = tool.measure(root, of, run=run)["findings"]
    other = tool.Run(tool.run_folder(root, base)) if base else None
    return judging.pack(root, run, rows, name, other, **flags)


def packed(root: Path, name: str = "b1") -> list[tuple[str, str, str]]:
    papers = json.loads((root / "report" / "packets" / f"{name}.json").read_text("utf-8"))
    return [(p["slug"], r, f["message"]) for p in papers
            for r, part in p["reports"].items() for f in part["findings"]]  # fmt: skip


def messages(reports: dict, *where: tuple[str, str, int]) -> list[tuple[str, str, str]]:
    return [(slug, report, reports[(slug, report)][i]["message"]) for slug, report, i in where]


# --- unjudged ---------------------------------------------------------------------------


def test_unjudged_packs_the_loud_findings_of_codes_not_settled(corpus: Path) -> None:
    result = pack(corpus)
    assert packed(corpus) == messages(R1, ("paper-a", "audit", 12), ("paper-a", "audit", 14),
                                      ("paper-a", "check", 2), ("paper-a", "check", 3),
                                      ("paper-a", "check", 4), ("paper-b", "audit", 0))
    assert result["settled"] == {"G6/vague-attribution": (10, 10)}
    assert result["by_code"]["G3/figure-colours-confused"] == 2 and result["findings"] == 6


def test_unjudged_packs_every_loud_finding_where_nothing_is_judged_yet(corpus: Path,
                                                                       capsys) -> None:
    """A corpus judged for the first time, a held-out set say, holds no verdict: `unjudged`
    packs every loud finding of the run, no code being settled (Basile, 2026-11-23)."""
    for verdicts in (corpus / "report" / "judged").glob("*.json"):
        verdicts.unlink()
    (corpus / "report" / "packets" / "field.json").unlink()
    with pytest.raises(tool.CorpusError, match="holds no judged finding"):
        tool.measure(corpus, "r1")  # the measure still asks for verdicts
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "first"]) == 0
    loud = [(slug, report, f["message"]) for (slug, report), found in R1.items()
            for f in found if f["severity"] in ("warn", "fail")]  # fmt: skip
    # As with verdicts: not a check's finding every new project gives, nor one repeating
    # the same paper's audit.
    left_out = {("paper-a", "check", "the plan's question section is empty"),
                ("paper-a", "check", "42 is typed")}
    assert sorted(packed(corpus, "first")) == sorted(set(loud) - left_out)
    assert "of every code, nothing in the corpus being judged yet" in capsys.readouterr().out


def test_a_verdict_file_that_cannot_be_read_is_no_corpus_with_no_verdict(corpus: Path,
                                                                        capsys) -> None:
    """Only empty verdict files make a corpus not judged yet: one that is not JSON is refused,
    as before, rather than packing every loud finding."""
    for verdicts in (corpus / "report" / "judged").glob("*.json"):
        verdicts.unlink()
    (corpus / "report" / "judged" / "b0.json").write_text('[{"slug": "paper-a",}', "utf-8")
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "x"]) == 2
    assert "holds no judged finding" in capsys.readouterr().err
    assert not (corpus / "report" / "packets" / "x.json").exists()
    (corpus / "report" / "judged" / "b0.json").write_text("[]", "utf-8")
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "x"]) == 0


def test_a_markdown_paper_s_text_is_the_paper_itself(corpus: Path) -> None:
    """A Markdown paper is audited only, and a judge reads the paper's own file."""
    (corpus / "corpus" / "paper-c" / "files").mkdir(parents=True)
    (corpus / "corpus" / "paper-c" / "files" / "paper.md").write_text("# A\n", "utf-8")
    (corpus / "corpus" / "paper-c" / "meta.json").write_text(json.dumps(
        {"slug": "paper-c", "format": "markdown", "main": "paper.md", "title": "C",
         "window": "B"}), "utf-8")  # fmt: skip
    write_run(corpus, "r1", {("paper-c", "audit"): [
        finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", "delve2")]})
    pack(corpus)
    papers = {p["slug"]: p for p in json.loads(
        (corpus / "report" / "packets" / "b1.json").read_text("utf-8"))}  # fmt: skip
    assert papers["paper-c"]["text"] == str(corpus / "corpus" / "paper-c" / "files" / "paper.md")


def test_the_thresholds_of_a_settled_code_are_flags(corpus: Path, capsys) -> None:
    assert pack(corpus, "loose", share=0.5, least=1)["settled"] == {
        "G6/vague-attribution": (10, 10), "G14/spelling-variant": (1, 1)}
    assert ("paper-a", "audit", R1[("paper-a", "audit")][12]["message"]) not in packed(
        corpus, "loose")  # fmt: skip
    # Eleven needed: no code is settled, and the settled code's own new findings are packed.
    # (Each packet set aside first, since a finding a batch holds is not packed again.)
    (corpus / "report" / "packets" / "loose.json").unlink()
    assert pack(corpus, "strict", least=11)["settled"] == {}
    assert len(packed(corpus, "strict")) == 8
    (corpus / "report" / "packets" / "strict.json").unlink()
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "cli",
                      "--min-judged", "1", "--settled", "0.5"]) == 0  # fmt: skip
    out = capsys.readouterr().out
    assert "2 settled left out" in out and "| G3/figure-colours-confused | 2 |" in out


def test_with_a_base_only_keys_not_loud_there_are_packed_of_every_code(corpus: Path) -> None:
    pack(corpus, base="r0")
    assert packed(corpus) == messages(R1, ("paper-a", "audit", 14), ("paper-a", "audit", 15),
                                      ("paper-a", "check", 2), ("paper-a", "check", 3),
                                      ("paper-b", "audit", 0))
    (corpus / "runs" / "r0" / "run.json").write_text(json.dumps({"scheme": 1}), "utf-8")
    with pytest.raises(tool.CorpusError, match="r0 keys by scheme 1 and r1 by 2"):
        pack(corpus, "other", base="r0")


def test_a_packet_keeps_each_finding_whole_with_its_key_text_and_figures(corpus: Path) -> None:
    pack(corpus)
    papers = {p["slug"]: p for p in json.loads(
        (corpus / "report" / "packets" / "b1.json").read_text("utf-8"))}  # fmt: skip
    a, b = papers["paper-a"], papers["paper-b"]
    assert (a["run"], a["scheme"], a["title"], a["format"]) == ("r1", 2, "Paper paper-a", "docx")
    project = corpus / "runs" / "r1" / "paper-a" / "project"
    assert a["text"] == str(project / "manuscript" / "main.md")
    # A PDF's text, pdftotext's, as the harness left it beside another run's reports.
    assert b["text"] == str(corpus / "runs" / "r0" / "paper-b" / "paper.txt")
    assert b["original"] == str(corpus / "corpus" / "paper-b" / "files" / "paper.pdf")
    audit = a["reports"]["audit"]
    assert audit["findings"][0] == R1[("paper-a", "audit")][12]  # every field, its key too
    assert audit["totals"]["G6/vague-attribution"] == 12
    check = a["reports"]["check"]["findings"]
    assert check[0]["figure_files"] == [str(project / "figures" / "fig1.png")]
    assert check[1]["figure_files"] == [str(project / f) for f in (
        "figures/fig1.png", "figures/fig2.png", "manuscript/media/image1.png")]
    assert "figure_files" not in check[2]


def test_a_packet_there_already_is_never_overwritten(corpus: Path) -> None:
    pack(corpus)
    before = (corpus / "report" / "packets" / "b1.json").read_bytes()
    with pytest.raises(tool.CorpusError, match="there already"):
        pack(corpus)
    assert (corpus / "report" / "packets" / "b1.json").read_bytes() == before
    with pytest.raises(tool.CorpusError, match="cannot name a batch"):
        pack(corpus, "x-author")


def test_a_batch_is_never_named_as_a_verdict_file_is(corpus: Path) -> None:
    # The first verdicts, under a name a batch could take: they would read its packet.
    judged = corpus / "report" / "judged"
    (judged / "field.json").rename(judged / "b1.json")
    before = tool.measure(corpus, "r1")
    with pytest.raises(tool.CorpusError, match="report/judged/b1.json is there already"):
        pack(corpus, "b1")
    assert not (corpus / "report" / "packets" / "b1.json").exists()
    assert tool.measure(corpus, "r1") == before
    # Measured first: the loader itself refuses an author's file with no batch packet.
    run = tool.Run(tool.run_folder(corpus, "r1"))
    rows = tool.measure(corpus, "r1", run=run)["findings"]
    (judged / "b2-author.json").write_text("[]", "utf-8")
    with pytest.raises(tool.CorpusError, match="report/judged/b2-author.json is there already"):
        judging.pack(corpus, run, rows, "b2")
    assert not (corpus / "report" / "packets" / "b2.json").exists()


def test_a_first_packet_whose_papers_name_a_run_is_still_a_first_one(corpus: Path) -> None:
    before = tool.measure(corpus, "r1")
    path = corpus / "report" / "packets" / "field.json"
    papers = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps([{**p, "run": "main-2235bfe54"} for p in papers]), "utf-8")
    after = tool.measure(corpus, "r1")
    assert after == before and not any(r["batch"] for r in after["findings"])
    # What marks a batch is its name on each of its papers.
    pack(corpus)
    batch = json.loads((corpus / "report" / "packets" / "b1.json").read_text("utf-8"))
    assert {p["batch"] for p in batch} == {"b1"}


# --- agree ------------------------------------------------------------------------------

#: The two judges on b1, in packet order: paper-a audit 0-1, check 0-2, paper-b audit 0.
A = ["true", "false", "true", "true", "false", "unclear"]
B = ["true", "false", "true", "true", "true", "true"]


def places(root: Path, name: str = "b1") -> list[tuple[str, str, int]]:
    papers = json.loads((root / "report" / "packets" / f"{name}.json").read_text("utf-8"))
    return [(p["slug"], r, i) for p in papers
            for r, part in p["reports"].items() for i in range(len(part["findings"]))]


def judge(root: Path, name: str, who: str, said: list[str], where=None) -> None:
    folder = root / "report" / "judges" / name
    folder.mkdir(parents=True, exist_ok=True)
    entries = [{"slug": s, "report": r, "index": i, "verdict": v, "kind": f"kind-{who}",
                "why": f"{who} says {v}", "useful": True}
               for (s, r, i), v in zip(where or places(root, name), said, strict=True)]
    (folder / f"{who}.json").write_text(json.dumps(entries), "utf-8")


def agreed(corpus: Path) -> dict:
    pack(corpus)
    judge(corpus, "b1", "a", A)
    judge(corpus, "b1", "b", B)
    return judging.agree(corpus, "b1")


def test_agree_writes_the_agreements_and_gives_the_rest_to_the_author(corpus: Path) -> None:
    result = agreed(corpus)
    assert (result["agreed"], result["true"], result["disagreed"], result["unclear"]) == (4, 3,
                                                                                         2, 1)
    judged = corpus / "report" / "judged"
    entries = json.loads((judged / "b1.json").read_text("utf-8"))
    assert [(e["slug"], e["report"], e["index"], e["verdict"]) for e in entries] == [
        ("paper-a", "audit", 0, "true"), ("paper-a", "audit", 1, "false"),
        ("paper-a", "check", 0, "true"), ("paper-a", "check", 1, "true")]
    kept = ("why_a", "why_b", "kind_a", "kind_b", "useful_a", "judges")
    assert {k: entries[1][k] for k in kept} == {
        "why_a": "a says false", "why_b": "b says false", "kind_a": "kind-a",
        "kind_b": "kind-b", "useful_a": True, "judges": 2}
    told = (judged / "b1-disagreements.md").read_text("utf-8")
    assert "### 1. paper-a check 2: G6/ai-phrasing" in told
    assert "### 2. paper-b audit 0: G7/doi-unresolved" in told and "### 3." not in told
    assert "- Judge A: unclear (kind-a): a says unclear" in told
    assert "- Judge B: true (kind-b): b says true" in told
    assert "- Message: 'delve into' is a phrase models favour" in told
    assert "b1-author.json" in told
    sample = (judged / "b1-sample.md").read_text("utf-8")
    assert sample.count("\n### ") == 4  # fewer than 20 agreements: all of them


def test_agree_refuses_a_finding_missing_doubled_or_not_in_the_packet(corpus: Path) -> None:
    pack(corpus)
    where = places(corpus)
    judge(corpus, "b1", "a", A)
    judge(corpus, "b1", "b", B[:-1], where[:-1])
    with pytest.raises(tool.CorpusError, match="1 findings of the packet are not judged"):
        judging.agree(corpus, "b1")
    judge(corpus, "b1", "b", [*B, "true"], [*where, where[0]])
    with pytest.raises(tool.CorpusError, match="paper-a audit 0 is judged twice"):
        judging.agree(corpus, "b1")
    judge(corpus, "b1", "b", B, [*where[:-1], ("paper-b", "audit", 9)])
    with pytest.raises(tool.CorpusError, match="paper-b audit 9 is no finding of the packet"):
        judging.agree(corpus, "b1")
    judge(corpus, "b1", "b", [*B[:-1], "maybe"])
    with pytest.raises(tool.CorpusError, match="true, false or unclear"):
        judging.agree(corpus, "b1")
    assert not (corpus / "report" / "judged" / "b1.json").exists()


def test_agree_never_overwrites_what_it_wrote(corpus: Path) -> None:
    agreed(corpus)
    sample = corpus / "report" / "judged" / "b1-sample.md"
    sample.write_text("the author's notes", "utf-8")
    (corpus / "report" / "judged" / "b1.json").unlink()
    with pytest.raises(tool.CorpusError, match="there already"):
        judging.agree(corpus, "b1")
    assert sample.read_text("utf-8") == "the author's notes"
    assert not (corpus / "report" / "judged" / "b1.json").exists()


def test_the_sample_is_twenty_agreements_drawn_the_same_each_time(tmp_path: Path) -> None:
    texts = []
    for name in ("one", "two"):
        root = tmp_path / name
        found = [finding("G6", "x", f"message {n}", f"s{n}", line=n) for n in range(25)]
        (root / "report" / "packets").mkdir(parents=True)
        (root / "report" / "packets" / "big.json").write_text(json.dumps([{
            "slug": "p", "batch": "big", "run": "r", "scheme": 2,
            "reports": {"audit": {"findings": found}}}]))
        where = [("p", "audit", n) for n in range(25)]
        # The last both find unclear: no agreement, and the author's to answer.
        judge(root, "big", "a", ["true"] * 24 + ["unclear"], where)
        judge(root, "big", "b", ["true"] * 24 + ["unclear"], where)
        said = judging.agree(root, "big")
        assert (said["agreed"], said["disagreed"], said["unclear"], said["sample"]) == (24, 1,
                                                                                       1, 20)
        told = (root / "report" / "judged" / "big-disagreements.md").read_text("utf-8")
        assert "### 1. p audit 24:" in told
        texts.append((root / "report" / "judged" / "big-sample.md").read_text("utf-8"))
    assert texts[0] == texts[1] and texts[0].count("\n### ") == 20
    drawn = random.Random("big").sample(range(24), 20)
    assert [f"### {k}. p audit {n}:" in texts[0] for k, n in enumerate(drawn, 1)] == [True] * 20


# --- the verdicts of a batch, read ------------------------------------------------------


def first_rows(result: dict) -> list[dict]:
    return [r for r in result["findings"] if not r["batch"]]


def test_a_batch_beside_the_first_packets_changes_no_first_verdict(corpus: Path) -> None:
    before = tool.measure(corpus, "r1")
    agreed(corpus)
    after = tool.measure(corpus, "r1")
    assert first_rows(after) == before["findings"] and len(before["findings"]) == len(FIRST)
    # The batch's paper-a audit 0 is not the first packet's paper-a audit 0.
    batch = [r for r in after["findings"] if r["batch"] == "b1"]
    assert [(r["index"], r["code"]) for r in batch if r["report"] == "audit"] == [
        (0, "G14/spelling-variant"), (1, "G2/typed-number")]


def test_a_batch_verdict_is_paired_by_its_key_and_counts(corpus: Path) -> None:
    run = tool.Run(tool.run_folder(corpus, "r1"))
    tool.measure(corpus, "r1", run=run)
    before = sum(tool.unjudged(run).values())
    agreed(corpus)
    run = tool.Run(tool.run_folder(corpus, "r1"))
    result = tool.measure(corpus, "r1", run=run)
    batch = [r for r in result["findings"] if r["batch"]]
    assert [(r["by_key"], r["state"]) for r in batch] == [(True, "reported")] * 4
    assert sum(tool.unjudged(run).values()) == before - 4
    assert result["codes"]["G3/figure-colours-confused"]["true"]["reported"] == 2
    # Packed again, nothing: those the judges agreed on are paired, and the two they did not
    # wait for the author in b1, so are not packed a second time.
    again = pack(corpus, "b2")
    assert (again["written"], again["packed_already"]) == (False, 2)
    assert not (corpus / "report" / "packets" / "b2.json").exists()


def test_a_finding_a_batch_holds_is_not_packed_again(corpus: Path, capsys) -> None:
    agreed(corpus)  # b1: two findings wait for the author
    result = pack(corpus, "b2", least=11)  # no code settled: something is left to pack
    assert packed(corpus, "b2") == messages(R1, ("paper-a", "audit", 11),
                                            ("paper-a", "audit", 15))  # fmt: skip
    assert result["packed_already"] == 2
    print(judging.render_pack(result))
    assert "2 left out as a batch holds them already" in capsys.readouterr().out
    # A batch of another scheme holds other keys: its findings are packed.
    (corpus / "report" / "packets" / "b2.json").unlink()
    path = corpus / "report" / "packets" / "b1.json"
    path.write_text(json.dumps([{**p, "scheme": 1} for p in json.loads(
        path.read_text("utf-8"))]), "utf-8")  # fmt: skip
    assert pack(corpus, "b3", least=11)["packed_already"] == 0
    assert len(packed(corpus, "b3")) == 4


def test_a_key_a_batch_holds_once_leaves_out_one_finding_under_it(corpus: Path) -> None:
    agreed(corpus)  # b1 holds 'delve into' once, waiting for the author
    check = R1[("paper-a", "check")]
    write_run(corpus, "r1", {("paper-a", "check"): [*check, {**check[4], "line": 80}]})
    result = pack(corpus, "b2")
    assert packed(corpus, "b2") == [("paper-a", "check", check[4]["message"])]
    papers = json.loads((corpus / "report" / "packets" / "b2.json").read_text("utf-8"))
    assert papers[0]["reports"]["check"]["findings"][0]["line"] == 80  # the second, in order
    assert result["packed_already"] == 2


def test_agree_refuses_a_packet_that_is_no_batch_s(corpus: Path) -> None:
    with pytest.raises(tool.CorpusError, match="field.json is not a batch's packet"):
        judging.agree(corpus, "field")


def test_the_author_s_answers_are_read_against_their_batch(corpus: Path) -> None:
    agreed(corpus)
    answers = [{"slug": "paper-a", "report": "check", "index": 2, "verdict": "false",
                "by": "the author", "date": "2026-11-22", "source": "b1-disagreements.md, 1"},
               {"slug": "paper-b", "report": "audit", "index": 0, "verdict": "true",
                "by": "the author", "date": "2026-11-22", "source": "b1-disagreements.md, 2"}]
    path = corpus / "report" / "judged" / "b1-author.json"
    path.write_text(json.dumps(answers), "utf-8")
    rows = [r for r in tool.measure(corpus, "r1")["findings"] if r["batch"] == "b1"]
    assert len(rows) == 6
    assert sorted((r["slug"], r["report"], r["index"], r["code"], r["verdict"]) for r in rows
                  if (r["report"], r["index"]) in (("check", 2), ("audit", 0))) == [
        ("paper-a", "audit", 0, "G14/spelling-variant", "true"),
        ("paper-a", "check", 2, "G6/ai-phrasing", "false"),
        ("paper-b", "audit", 0, "G7/doi-unresolved", "true")]
    path.write_text(json.dumps([{**answers[0], "by": ""}]), "utf-8")
    with pytest.raises(tool.CorpusError, match="lacks by"):
        tool.measure(corpus, "r1")
    path.write_text(json.dumps([{**answers[0], "slug": "paper-a", "report": "audit",
                                 "index": 0}]), "utf-8")  # fmt: skip
    with pytest.raises(tool.CorpusError, match="paper-a audit 0 b1 is judged twice"):
        tool.measure(corpus, "r1")
    path.rename(corpus / "report" / "judged" / "b9-author.json")
    with pytest.raises(tool.CorpusError, match="no report/packets/b9.json"):
        tool.measure(corpus, "r1")
    # Nor are two judges' verdicts read by slug where their packet is gone.
    (corpus / "report" / "judged" / "b9-author.json").unlink()
    (corpus / "report" / "packets" / "b1.json").rename(corpus / "b1.json")
    with pytest.raises(tool.CorpusError, match="two judges' verdicts, with no report/packets/b1"):
        tool.measure(corpus, "r1")


def test_a_batch_of_another_scheme_is_paired_by_the_matcher(corpus: Path) -> None:
    agreed(corpus)
    (corpus / "runs" / "r1" / "run.json").write_text(json.dumps({"scheme": 3}), "utf-8")
    batch = [r for r in tool.measure(corpus, "r1")["findings"] if r["batch"]]
    assert [(r["by_key"], r["state"]) for r in batch] == [(False, "reported")] * 4


def test_a_batch_verdict_s_count_is_held_to_its_own_run(corpus: Path) -> None:
    check = R1[("paper-a", "check")]
    write_run(corpus, "r2", {**R1, ("paper-a", "check"): [*check, check[2]]})
    pack(corpus, "b2", of="r2")
    where = places(corpus, "b2")
    judge(corpus, "b2", "a", ["true"] * len(where))
    judge(corpus, "b2", "b", ["true"] * len(where))
    judging.agree(corpus, "b2")

    def fig1(run: str) -> list[tuple[str, bool]]:
        return [(r["state"], r["fell"]) for r in tool.measure(corpus, run)["findings"]
                if r["batch"] == "b2" and r["message"].startswith("fig1.png")]

    # Its key stands twice in the run it was judged in: once is a count that fell.
    assert fig1("r2") == [("reported", False)] * 2
    assert fig1("r1") == [("gone", True)] * 2


def test_a_batch_s_run_is_found_by_its_folder_wherever_it_is(corpus: Path) -> None:
    check = R1[("paper-a", "check")]
    elsewhere = corpus.parent / "other-runs"
    folder = write_run(elsewhere, "rx", {**R1, ("paper-a", "check"): [*check, check[2]]})
    folder = folder.rename(elsewhere / "rx-run")  # its folder is not runs/<its name>
    pack(corpus, "bx", of=str(folder))
    papers = json.loads((corpus / "report" / "packets" / "bx.json").read_text("utf-8"))
    assert {(p["run"], p["folder"]) for p in papers} == {("rx-run", str(folder))}
    where = places(corpus, "bx")
    judge(corpus, "bx", "a", ["true"] * len(where))
    judge(corpus, "bx", "b", ["true"] * len(where))
    judging.agree(corpus, "bx")
    rows = [(r["state"], r["fell"]) for r in tool.measure(corpus, "r1")["findings"]
            if r["batch"] == "bx" and r["message"].startswith("fig1.png")]
    assert rows == [("gone", True)] * 2  # held to its own run's two, not to r1's one


def test_the_first_verdicts_are_paired_before_a_batch_s_by_the_matcher(corpus: Path) -> None:
    # A batch judged a twin of a first verdict's finding, from a run that gave it twice.
    audit = R1[("paper-a", "audit")]
    write_run(corpus, "twice", {**R1, ("paper-a", "audit"): [*audit, audit[10]]})
    (corpus / "runs" / "r1" / "run.json").write_text(json.dumps({"scheme": 3}), "utf-8")
    before = tool.measure(corpus, "r1")["findings"]
    pack(corpus, "dup", of="twice")
    where = places(corpus, "dup")
    judge(corpus, "dup", "a", ["true"] * len(where))
    judge(corpus, "dup", "b", ["true"] * len(where))
    judging.agree(corpus, "dup")
    # In a run of another scheme, which has the finding once, the first verdict keeps it.
    after = tool.measure(corpus, "r1")["findings"]
    assert first_rows({"findings": after}) == before
    twin = [r for r in after if r["batch"] and r["message"].startswith("'color'")]
    assert [(r["by_key"], r["state"]) for r in twin] == [(False, "gone")]


# --- a batch tied to a keyed run of another scheme (Basile, 2026-11-21) -----------------


def rekeyed(reports: dict, digest: str = "k3") -> dict:
    """The reports as a build of another scheme gives them: the same findings, other keys."""
    return {where: [{**f, "key": f["key"].rsplit("|", 1)[0] + f"|{digest}"} if "key" in f
                    else f for f in found] for where, found in reports.items()}  # fmt: skip


def reworded(reports: dict, slug: str, report: str, index: int) -> dict:
    """The reports with one finding's message changed and its key kept."""
    found = list(reports[(slug, report)])
    found[index] = {**found[index], "message": f"{found[index]['message']}, said otherwise"}
    return {**reports, (slug, report): found}


def b1_row(rows: list[dict], report: str, index: int) -> dict:
    return next(r for r in rows if r["batch"] == "b1" and (r["report"], r["index"]) == (
        report, index))  # fmt: skip


def test_a_batch_tied_to_a_run_of_another_scheme_is_paired_by_its_tied_key(
        corpus: Path) -> None:  # fmt: skip
    agreed(corpus)  # b1, from r1, of scheme 2; its check 0 is the G3 finding on fig1.png
    k3 = rekeyed(R1)
    write_run(corpus, "k3", k3, scheme=3)
    write_run(corpus, "pr", reworded(k3, "paper-a", "check", 2), scheme=3)  # its key kept
    lost = tool.gate(corpus, "k3", "pr")["lost"]
    assert [(r["batch"], r["report"], r["index"]) for r in lost] == [("b1", "check", 0)]
    said = tool.tie(corpus, "r1", "k3")
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    batch = document["batches"]["b1"]
    assert (batch["judged_run"], batch["scheme"]) == ("r1", 2)
    assert ("check", 0, k3[("paper-a", "check")][2]["key"]) in {
        (t["report"], t["index"], t["key"]) for t in batch["ties"]}
    assert said["batches"]["b1"]["tied"] == len(batch["ties"]) == 4  # its four agreements
    assert "b1 (scheme 2, judged in r1): 4 tied" in tool.corpus_keys.render_tie(said)
    # The first verdicts are tied as before, beside the batch's.
    assert len(document["ties"]) == said["tied"]
    result = tool.gate(corpus, "k3", "pr")
    assert result["ok"] and not result["lost"]
    row = b1_row(tool.measure(corpus, "pr")["findings"], "check", 0)
    assert (row["by_key"], row["state"]) == (True, "reported")


def test_a_batch_verdict_no_rule_ties_goes_to_the_author_and_is_decided(corpus: Path) -> None:
    agreed(corpus)  # b1's audit 0 is the G14 'behavior' finding
    k3 = rekeyed(R1)
    audit = k3[("paper-a", "audit")]
    twin = {**audit[12], "key": "G14|spelling-variant|behaviour|k3"}
    write_run(corpus, "k3", {**k3, ("paper-a", "audit"): [*audit, twin]}, scheme=3)
    said = tool.tie(corpus, "r1", "k3")
    assert said["batches"]["b1"]["ambiguous"] == 1
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    tied = {(t["report"], t["index"]) for t in document["batches"]["b1"]["ties"]}
    assert ("audit", 0) not in tied
    told = (corpus / "report" / "ties-ambiguous.md").read_text("utf-8")
    assert "- **b1 paper-a audit 0** (true, G14/spelling-variant" in told
    assert "`batch: B`" in told
    assert "to tie: 1: 0 of the first verdicts, 1 of batches" in told
    assert "judged in its batch's run against the same keyed run: b1 in r1." in told
    untied = (corpus / "report" / "ties-untied.md").read_text("utf-8")
    # No batch's verdict is left untied: that file's counts are as they always were.
    assert untied.startswith("# Judged findings left untied: 0\n") and "b1" not in untied
    decided = corpus / "report" / "ties-decided.yaml"
    entry = {"slug": "paper-a", "report": "audit", "index": 0, "batch": "b1",
             "key": audit[12]["key"], "by": "the author", "date": "2026-11-21"}
    decided.write_text(yaml.safe_dump([entry]), "utf-8")
    rows = tool.measure(corpus, "k3")["findings"]
    row = b1_row(rows, "audit", 0)
    assert (row["by_key"], row["state"]) == (True, "reported")
    # The decision names the batch's verdict, not the first verdict at that place.
    assert set(tool.corpus_keys.load_decided(corpus)) == {("paper-a", "audit", 0, "b1")}
    first = next(r for r in rows if not r["batch"] and (r["report"], r["index"]) == ("audit", 0))
    assert (first["code"], first["state"]) == ("G6/vague-attribution", "reported")
    decided.write_text(yaml.safe_dump([{**entry, "batch": "b9"}]), "utf-8")
    with pytest.raises(tool.CorpusError, match="paper-a audit 0 b9 is no judged finding"):
        tool.measure(corpus, "k3")


def test_a_ledger_names_a_batch_verdict_by_its_batch(corpus: Path) -> None:
    """A ledger's finding names a batch's verdict by its batch as well as its slug, report
    and index; without one it names the first verdict at that place, and never the batch's
    (Basile, 2026-11-22: a decision covered a batch's verdict the ledger could not name)."""
    agreed(corpus)

    def verdicts(*findings: dict) -> list[tuple[str, int, str, str]]:
        ledger = {"decisions": [{"id": "d", "date": "2026-11-22", "by": "the author",
                                 "what": "w", "source": "s",
                                 "rejudge": {"verdict": "false", "findings": list(findings)}}]}
        (corpus / "report" / "ledger.yaml").write_text(yaml.safe_dump(ledger), "utf-8")
        rows = tool.measure(corpus, "r1")["findings"]
        return sorted((r["batch"], r["index"], r["verdict"], r["rejudged_by"]) for r in rows
                      if (r["slug"], r["report"], r["index"]) == ("paper-a", "audit", 0))

    place = {"slug": "paper-a", "report": "audit", "index": 0}
    assert verdicts({**place, "batch": "b1"}) == [("", 0, "true", ""), ("b1", 0, "false", "d")]
    assert verdicts(place) == [("", 0, "false", "d"), ("b1", 0, "true", "")]
    # A name YAML reads as a number or a date is read as the decided file reads it.
    assert verdicts({**place, "batch": 7}) == [("", 0, "true", ""), ("b1", 0, "true", "")]
    for bad in ("", None, " b1", "b1 ", "b/1"):
        (corpus / "report" / "ledger.yaml").write_text(yaml.safe_dump({"decisions": [
            {"id": "d", "date": "2026-11-22", "by": "a", "what": "w", "source": "s",
             "rejudge": {"verdict": "false", "findings": [{**place, "batch": bad}]}}]}), "utf-8")
        with pytest.raises(tool.CorpusError, match="a batch is named by its name"):
            tool.measure(corpus, "r1")


def test_a_batch_of_the_keyed_run_s_scheme_is_not_tied(corpus: Path) -> None:
    agreed(corpus)
    write_run(corpus, "k2", reworded(R1, "paper-a", "check", 2), scheme=2)
    before = [r for r in tool.measure(corpus, "k2")["findings"] if r["batch"]]
    said = tool.tie(corpus, "r1", "k2")
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    assert "batches" not in document and said["batches"] == {}
    assert said["own_scheme"] == ["b1"]
    assert "b1 keys by the keyed run's scheme 2: paired by its own keys" in (
        tool.corpus_keys.render_tie(said))
    after = [r for r in tool.measure(corpus, "k2")["findings"] if r["batch"]]
    assert after == before
    assert (b1_row(after, "check", 0)["by_key"], b1_row(after, "check", 0)["state"]) == (
        True, "reported")
    # A decision on such a batch's verdict would be read nowhere: it is refused.
    (corpus / "report" / "ties-decided.yaml").write_text(yaml.safe_dump([
        {"slug": "paper-a", "report": "check", "index": 0, "batch": "b1",
         "key": R1[("paper-a", "check")][2]["key"], "by": "the author",
         "date": "2026-11-22"}]), "utf-8")  # fmt: skip
    with pytest.raises(tool.CorpusError, match="names batch b1, which keys by the ties' own"):
        tool.measure(corpus, "k2")


def test_a_batch_whose_run_is_gone_is_left_for_the_matcher(corpus: Path) -> None:
    agreed(corpus)
    write_run(corpus, "k3", rekeyed(R1), scheme=3)
    (corpus / "runs" / "r1").rename(corpus.parent / "r1-moved")
    said = tool.tie(corpus, "r0", "k3")
    assert (said["no_run"], said["batches"], said["tied"]) == (["b1"], {}, len(FIRST))
    assert "- b1 not tied: its run is neither at the folder its packet names" in (
        tool.corpus_keys.render_tie(said))
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    assert "batches" not in document and len(document["ties"]) == len(FIRST)
    # The list of those left untied names it, its four verdicts counted with the batches'.
    untied = (corpus / "report" / "ties-untied.md").read_text("utf-8")
    assert untied.startswith("# Judged findings left untied: 4: 0 of the first verdicts, "
                             "4 of batches\n")  # fmt: skip
    assert ("- Batch b1, 4 verdicts: not tied, as its run is neither at the folder its packet "
            "names nor under runs/; the matcher pairs them.") in untied
    assert "Batch b1" not in (corpus / "report" / "ties-ambiguous.md").read_text("utf-8")
    rows = [r for r in tool.measure(corpus, "k3")["findings"] if r["batch"]]
    assert rows and not any(r["by_key"] for r in rows)


def test_a_batch_s_ties_are_refused_where_its_packet_names_another_run(corpus: Path) -> None:
    agreed(corpus)
    write_run(corpus, "k3", rekeyed(R1), scheme=3)
    tool.tie(corpus, "r1", "k3")
    path = corpus / "report" / "packets" / "b1.json"
    papers = json.loads(path.read_text("utf-8"))
    for changed, says in (({"run": "r9"}, "names run r9 at scheme 2"),
                          ({"scheme": 1}, "names run r1 at scheme 1")):
        path.write_text(json.dumps([{**p, **changed} for p in papers]), "utf-8")
        with pytest.raises(tool.CorpusError, match=f"made from run r1 at scheme 2, .*{says}"):
            tool.measure(corpus, "k3")
    path.write_text(json.dumps(papers), "utf-8")
    assert any(r["by_key"] for r in tool.measure(corpus, "k3")["findings"] if r["batch"])


def test_a_malformed_batch_entry_in_the_ties_is_refused(corpus: Path) -> None:
    (corpus / "report" / "ties.yaml").write_text(yaml.safe_dump(
        {"run": "k3", "scheme": 3, "ties": [], "batches": {"b1": {"ties": "x"}}}), "utf-8")
    with pytest.raises(tool.CorpusError, match="a batch's ties are"):
        tool.corpus_keys.load_ties(corpus)


# --- the gate and the output ------------------------------------------------------------


def test_the_gate_counts_the_new_loud_findings_with_no_verdict(corpus: Path) -> None:
    result = tool.gate(corpus, "r0", "r1")
    assert result["fresh"]["count"] == 5
    text = tool.render_gate(result)
    assert ("whose key is not loud in the base, with no verdict: 5. To pack them for two "
            "judges: `python tools/corpus.py unjudged r1 --name r1-added --base r0`") in text
    (corpus / "runs" / "r0" / "run.json").write_text(json.dumps({"scheme": 1}), "utf-8")
    assert "not counted, as r0 keys by scheme 1 and r1 by 2" in tool.render_gate(
        tool.gate(corpus, "r0", "r1"))


def test_the_gate_says_why_it_cannot_count_before_it_measures(corpus: Path) -> None:
    # A base with no keys, and ties of a run that is gone: measuring the new run would fail.
    unkeyed = {where: [{k: v for k, v in f.items() if k != "key"} for f in found]
               for where, found in R0.items()}  # fmt: skip
    write_run(corpus, "r0", unkeyed, scheme=None)
    (corpus / "runs" / "r0" / "run.json").unlink()
    (corpus / "report" / "ties.yaml").write_text(json.dumps(
        {"run": "no-such-run", "scheme": 2, "ties": []}), "utf-8")  # fmt: skip
    result = tool.gate(corpus, "r0", "r1")
    assert result["fresh"] == {"count": None, "note": "r0 carries no keys"}
    assert "not counted, as r0 carries no keys" in tool.render_gate(result)


def test_the_gate_counts_what_the_command_it_prints_packs(corpus: Path) -> None:
    # A first verdict tied to a key that stands twice in the run of the ties, once quietly
    # in the base and once in the new run: the gate holds its count to the base, and kept
    # it; `measure`, and so `unjudged`, to the run of the ties, and lost it.
    color = R1[("paper-a", "audit")][10]
    write_run(corpus, "rt", {("paper-a", "audit"): [color, {**color, "line": 61}]})
    write_run(corpus, "r0", {**R0, ("paper-a", "audit"): [
        *R0[("paper-a", "audit")], {**color, "severity": "info"}]})
    (corpus / "report" / "ties.yaml").write_text(json.dumps({"run": "rt", "scheme": 2, "ties": [
        {"slug": "paper-a", "report": "audit", "index": 10, "key": color["key"],
         "how": "message+place"}]}), "utf-8")  # fmt: skip
    counted = tool.gate(corpus, "r0", "r1")["fresh"]
    result = pack(corpus, "r1-added", base="r0")
    assert counted["count"] == result["findings"] == 6
    assert counted["by_code"] == result["by_code"]


def test_the_markdown_is_written_in_utf8_whatever_the_stream_s_encoding(monkeypatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    tool._write("keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n", {}, None, None)
    assert raw.getvalue().decode("utf-8") == "keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n"


def test_a_terminal_is_written_text_in_its_own_encoding(monkeypatch) -> None:
    class Terminal(io.BytesIO):
        def isatty(self) -> bool:
            return True

    raw = Terminal()
    stream = io.TextIOWrapper(raw, encoding="utf-16-le", newline="")  # the terminal's
    monkeypatch.setattr(sys, "stdout", stream)
    tool._write("keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n", {}, None, None)
    stream.flush()
    assert raw.getvalue().decode("utf-16-le") == "keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n"


def test_a_terminal_that_cannot_write_a_character_gets_a_stand_in(monkeypatch) -> None:
    class Terminal(io.BytesIO):
        def isatty(self) -> bool:
            return True

    raw = Terminal()
    stream = io.TextIOWrapper(raw, encoding="latin-1", newline="")
    monkeypatch.setattr(sys, "stdout", stream)
    tool._write("keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n", {}, None, None)
    stream.flush()
    assert raw.getvalue().decode("latin-1") == "keys changed scheme (1 ? 2)\n"


def test_a_stream_with_a_buffer_and_no_isatty_gets_the_bytes(monkeypatch) -> None:
    class Stream:
        def __init__(self) -> None:
            self.buffer = io.BytesIO()

        def write(self, text: str) -> None:
            raise AssertionError("written as text")

        def flush(self) -> None:
            pass

    stream = Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    tool._write("keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n", {}, None, None)
    assert stream.buffer.getvalue().decode("utf-8") == (
        "keys changed scheme (1 \N{RIGHTWARDS ARROW} 2)\n")


def test_agree_from_the_command_line(corpus: Path, capsys) -> None:
    pack(corpus)
    judge(corpus, "b1", "a", A)
    judge(corpus, "b1", "b", B)
    assert tool.main(["--corpus", str(corpus), "agree", "b1"]) == 0
    assert "4 agreed (3 true, 1 false), 2 for the author" in capsys.readouterr().out
    assert tool.main(["--corpus", str(corpus), "agree", "b1"]) == 2
    assert "there already" in capsys.readouterr().err


# --- a paper removed after judging ------------------------------------------------------

WHY = {"by": "the author", "date": "2026-11-23", "why": "a preregistration template"}


def mark_removed(root: Path, slug: str) -> None:
    path = root / "corpus" / slug / "meta.json"
    meta = json.loads(path.read_text("utf-8"))
    path.write_text(json.dumps({**meta, "removed": WHY}), "utf-8")


def test_unjudged_packs_nothing_of_a_removed_paper(corpus: Path, capsys) -> None:
    mark_removed(corpus, "paper-b")
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "b1"]) == 0
    assert {slug for slug, _r, _m in packed(corpus)} == {"paper-a"}
    assert "Not packed, as removed after judging: paper-b." in capsys.readouterr().out
    (corpus / "report" / "packets" / "b1.json").unlink()
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "b2",
                      "--base", "r0"]) == 0  # fmt: skip
    assert {slug for slug, _r, _m in packed(corpus, "b2")} == {"paper-a"}


def test_a_removed_paper_s_batch_verdicts_are_left_out(corpus: Path) -> None:
    pack(corpus)
    judge(corpus, "b1", "a", ["true"] * 6)
    judge(corpus, "b1", "b", ["true"] * 6)
    judging.agree(corpus, "b1")
    before = tool.measure(corpus, "r1")
    assert any(r["batch"] and r["slug"] == "paper-b" for r in before["findings"])
    mark_removed(corpus, "paper-b")
    after = tool.measure(corpus, "r1")
    assert after["findings"] == [r for r in before["findings"] if r["slug"] == "paper-a"]
    assert after["skipped"] == {"paper removed after judging": 1}
    assert after["removed"] == [{"slug": "paper-b", **WHY, "verdicts": 1}]


def test_the_gate_s_count_of_new_findings_leaves_a_removed_paper_out(corpus: Path) -> None:
    assert "G7/doi-unresolved" in tool.gate(corpus, "r0", "r1")["fresh"]["by_code"]
    mark_removed(corpus, "paper-b")
    result = tool.gate(corpus, "r0", "r1")
    assert "G7/doi-unresolved" not in result["fresh"]["by_code"]
    assert "G7/doi-unresolved" not in result["unjudged"]


def test_a_corpus_whose_every_verdict_is_of_a_removed_paper_says_so(corpus: Path) -> None:
    mark_removed(corpus, "paper-a")
    with pytest.raises(tool.CorpusError, match="11 verdicts are of papers removed"):
        tool.measure(corpus, "r1")


def test_unjudged_packs_as_a_first_time_corpus_where_only_removed_verdicts_are_held(
        corpus: Path, capsys) -> None:  # fmt: skip
    mark_removed(corpus, "paper-a")
    assert tool.main(["--corpus", str(corpus), "unjudged", "r1", "--name", "b1"]) == 0
    assert {slug for slug, _r, _m in packed(corpus)} == {"paper-b"}
    assert "nothing in the corpus being judged yet" in capsys.readouterr().out


def test_one_verdict_of_a_removed_paper_is_said_in_the_singular(corpus: Path) -> None:
    path = corpus / "report" / "judged" / "field.json"
    path.write_text(json.dumps(json.loads(path.read_text("utf-8"))[:1]), "utf-8")
    mark_removed(corpus, "paper-a")
    with pytest.raises(tool.CorpusError, match="1 verdict is of a paper removed"):
        tool.measure(corpus, "r1")


def test_agree_puts_no_disagreement_of_a_removed_paper_before_the_author(corpus: Path) -> None:
    pack(corpus)
    judge(corpus, "b1", "a", A)
    judge(corpus, "b1", "b", B)
    mark_removed(corpus, "paper-b")
    result = judging.agree(corpus, "b1")
    told = (corpus / "report" / "judged" / "b1-disagreements.md").read_text("utf-8")
    assert "paper-b" not in told and "### 1. paper-a check 2" in told and "### 2." not in told
    assert "did not agree on (1)" in told
    assert "paper removed after judging: the two judges' verdicts on 1 finding" in told
    assert result["disagreed"] == 1 and result["unclear"] == 0
    assert "1 disagreement left out" in judging.render_agree(result)


def test_agree_draws_no_sample_slot_for_a_removed_paper(corpus: Path) -> None:
    pack(corpus)
    judge(corpus, "b1", "a", ["true"] * 6)
    judge(corpus, "b1", "b", ["true"] * 6)
    mark_removed(corpus, "paper-b")
    result = judging.agree(corpus, "b1")
    judged = corpus / "report" / "judged"
    # Its JSON is as it was: the measure is what leaves the verdict out.
    assert sum(e["slug"] == "paper-b" for e in
               json.loads((judged / "b1.json").read_text("utf-8"))) == 1  # fmt: skip
    sample = (judged / "b1-sample.md").read_text("utf-8")
    assert "paper-b" not in sample and sample.count("\n### ") == 5 and result["sample"] == 5
    assert "paper removed after judging: 1 agreed verdict" in sample
    assert "1 agreed verdict left out" in judging.render_agree(result)


def test_agree_speaks_of_removal_only_where_a_paper_is_removed(corpus: Path) -> None:
    result = agreed(corpus)
    judged = corpus / "report" / "judged"
    names = ("b1.json", "b1-disagreements.md", "b1-sample.md")
    for name in names[1:]:
        assert "removed after judging" not in (judged / name).read_text("utf-8")
    assert "left out" not in judging.render_agree(result)
    for name in names:
        (judged / name).unlink()
    mark_removed(corpus, "paper-b")
    assert "left out" in judging.render_agree(judging.agree(corpus, "b1"))
