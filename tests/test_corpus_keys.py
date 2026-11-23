"""`tools/corpus.py` pairing judged findings by their keys, and `tie`, on a made-up mini corpus.

Basile's rules (2026-11-19): where both runs carry keys a judged finding is paired by its key
alone; only keys unique in both runs pair, and a repeated key whose count fell loses every
judged finding under it; the judged set is tied to keys once, and what does not tie one to
one by the strongest passes goes to him. A run with no keys keeps #705's matcher.
"""

from __future__ import annotations

import importlib.util
import json
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
keys = tool.corpus_keys


def finding(gate: str, code: str, message: str, severity: str = "warn", line: int | None = 10,
            key: str | None = None, **extra) -> dict:  # fmt: skip
    said = {"gate": gate, "code": code, "message": message, "severity": severity, "line": line,
            "path": "paper.docx", "context": extra.pop("context", None), **extra}
    return {**said, "key": key} if key is not None else said


K_SPELL = "G14|spelling-variant|color|-"
K_P = "G8|p-inconsistent|t(29)=2.05|0a1b2c3d4e5f"
K_HR = "G14|abbreviation-undefined|HR@main|-"
K_CTX = "G12|plan-section-empty|~9f8e7d6c5b4a|-"


# --- the state by key -------------------------------------------------------------------


def test_a_key_reads_reported_asked_elsewhere_or_gone_by_itself() -> None:
    def state(new: list[dict], base: int = 1, codes: tuple = ()) -> str:
        return keys.key_state(K_P, keys.Keys(new), base, codes).state

    assert state([finding("G8", "p-inconsistent", "reworded entirely", key=K_P)]) == "reported"
    assert state([finding("G8", "p-inconsistent", "x", "info", key=K_P)]) == "asked"
    # Another code with its subject and digest, at a warning: elsewhere.
    other = "audit|does-not-fit|t(29)=2.05|0a1b2c3d4e5f"
    assert state([finding("audit", "does-not-fit", "x", key=other)]) == "elsewhere"
    # The same message under another key is not it: the key decides alone.
    assert state([finding("G8", "p-inconsistent", "t(29) = 2.05", key=K_P + "x")]) == "gone"
    successor = [finding("audit", "question-no-abstract", "Where?", "info", key="a|b|c|d")]
    assert state(successor, codes=("audit/question-no-abstract",)) == "elsewhere"
    assert state(successor) == "gone"


def test_a_question_whose_forms_carry_the_key_asks_it() -> None:
    question = finding("G14", "abbreviation-undefined", "2 short forms ... Do any need defining?",
                       "info", key="G14|abbreviation-undefined|-|-", question=True,
                       forms=[{"form": "HR", "key": K_HR}, {"form": "OR", "key": "G14|x|OR|-"}])
    assert keys.key_state(K_HR, keys.Keys([question]), 1).state == "asked"
    assert keys.key_state("G14|abbreviation-undefined|CI@main|-", keys.Keys([question]),
                          1).state == "gone"  # fmt: skip


def test_a_repeated_key_whose_count_fell_is_gone_and_one_that_held_is_kept() -> None:
    one = finding("G14", "spelling-variant", "'color' is American", key=K_SPELL)
    fell = keys.key_state(K_SPELL, keys.Keys([one]), base_count=2)
    assert (fell.state, fell.repeated, fell.fell) == ("gone", True, True)
    held = keys.key_state(K_SPELL, keys.Keys([one, {**one, "line": 40}]), base_count=2)
    assert (held.state, held.repeated, held.fell) == ("reported", True, False)
    grew = keys.key_state(K_SPELL, keys.Keys([one, {**one, "line": 40}]), base_count=1)
    assert (grew.state, grew.repeated, grew.fell) == ("reported", True, False)
    unique = keys.key_state(K_SPELL, keys.Keys([one]), base_count=1)
    assert (unique.state, unique.repeated) == ("reported", False)


def test_a_key_from_the_context_is_told_apart() -> None:
    assert keys.from_context(K_CTX) and not keys.from_context(K_P)


# --- the mini corpus --------------------------------------------------------------------

JUDGED = [
    (finding("G14", "spelling-variant", "'color' is the American spelling", line=5), "true"),
    (finding("G8", "p-inconsistent", "t(29) = 2.05 gives a P of 0.049", line=8), "true"),
    (finding("G12", "plan-section-empty", "the plan's outcome section is empty", line=3,
             context="## Outcome"), "true"),  # fmt: skip
    (finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=12), "false"),
]
#: The keyed run the judged set is tied to: each judged finding there, with its key.
TIED = [
    finding("G14", "spelling-variant", "'color' is the American spelling", line=5, key=K_SPELL),
    finding("G8", "p-inconsistent", "t(29) = 2.05 gives a P of 0.049", line=8, key=K_P),
    finding("G12", "plan-section-empty", "the plan's outcome section is empty", line=3,
            context="## Outcome", key=K_CTX),  # fmt: skip
    finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=12,
            key="G6|ai-phrasing|delve into|1234567890ab"),  # fmt: skip
]


def write_run(root: Path, name: str, found: list[dict]) -> None:
    folder = root / "runs" / name / "paper-a"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "check.json").write_text(json.dumps({"findings": found}), "utf-8")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus-root"
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    packet = [{"slug": "paper-a", "text": "made up",
               "reports": {"check": {"findings": [f for f, _ in JUDGED]}}}]
    verdicts = [{"slug": "paper-a", "report": "check", "index": i, "verdict": v}
                for i, (_, v) in enumerate(JUDGED)]  # fmt: skip
    (root / "report" / "packets" / "f.json").write_text(json.dumps(packet))
    (root / "report" / "judged" / "f.json").write_text(json.dumps(verdicts))
    write_run(root, "judged", [f for f, _ in JUDGED])
    write_run(root, "tied", TIED)
    return root


def states_of(result: dict) -> list[str]:
    return [r["state"] for r in result["findings"]]


def test_tie_writes_the_one_to_one_ties_and_measure_then_pairs_by_key(corpus: Path) -> None:
    said = tool.tie(corpus, "judged", "tied")
    assert (said["tied"], said["ambiguous"], said["fallback"]) == (4, 0, 1)
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    assert document["run"] == "tied"
    assert [(t["index"], t["key"], t["how"]) for t in document["ties"]][:2] == [
        (0, K_SPELL, "message+place"), (1, K_P, "message+place")]
    # Every message reworded and every line moved: by key, each is still there.
    write_run(corpus, "keyed", [{**f, "message": "said otherwise", "line": 99} for f in TIED])
    result = tool.measure(corpus, "keyed", ledger=False)
    assert states_of(result) == ["reported"] * 4
    assert result["keys"] == {"by_key": 4, "fallback": 1, "repeated": 0, "fell": 0,
                              "by_matcher": 0}  # fmt: skip
    assert "Paired by a key from the context (1)" in tool.render_measure(result)
    # And with the message the same but the key another, the key decides: gone.
    write_run(corpus, "keyed", [{**f, "key": f["key"] + "-moved"} for f in TIED])
    assert states_of(tool.measure(corpus, "keyed", ledger=False)) == ["gone"] * 4


def test_a_run_with_no_keys_keeps_the_matcher(corpus: Path) -> None:
    tool.tie(corpus, "judged", "tied")
    write_run(corpus, "plain", [f for f, _ in JUDGED])
    result = tool.measure(corpus, "plain", ledger=False)
    assert states_of(result) == ["reported"] * 4 and result["keys"]["by_key"] == 0
    (corpus / "report" / "ties.yaml").unlink()
    assert states_of(tool.measure(corpus, "plain", ledger=False)) == states_of(result)


def test_the_gate_by_key_loses_a_repeated_key_whose_count_fell(corpus: Path) -> None:
    tool.tie(corpus, "judged", "tied")
    two = [*TIED, {**TIED[0], "line": 40}]
    write_run(corpus, "base", two)
    write_run(corpus, "new", TIED)
    result = tool.gate(corpus, "base", "new")
    assert not result["ok"]
    assert [(r["code"], r["base"], r["state"], r["fell"]) for r in result["lost"]] == [
        ("G14/spelling-variant", "reported", "gone", True)]
    assert [r["code"] for r in result["repeated"]] == ["G14/spelling-variant"]
    # Kept at its count, it is not lost; and a keyed run gated to itself loses nothing.
    assert tool.gate(corpus, "base", "base")["ok"]
    assert tool.gate(corpus, "tied", "tied")["ok"]
    assert tool.main(["--corpus", str(corpus), "gate", "base", "new"]) == 1


def test_the_gate_uses_the_matcher_where_either_run_has_no_keys(corpus: Path) -> None:
    tool.tie(corpus, "judged", "tied")
    write_run(corpus, "plain", [{**f, "line": 99} for f, _ in JUDGED])
    result = tool.gate(corpus, "tied", "plain")
    assert result["keys"]["by_key"] == 0


# --- what does not tie ------------------------------------------------------------------


def tie_kinds(olds: list[dict], new: list[dict]) -> list[str]:
    return [kind for kind, _how, _c in keys.tie_group(olds, new, "paper-a")]


def test_each_kind_of_finding_that_does_not_tie_goes_to_the_author() -> None:
    old = finding("G6", "vague-attribution", "'Studies show' with no citation nearby", line=5,
                  context="Studies show that")  # fmt: skip
    k1, k2 = "G6|vague-attribution|studies show|aaaaaaaaaaaa", "G6|vague-attribution|x|b"
    assert tie_kinds([old], [{**old, "key": k1}]) == ["tie"]
    # No candidate.
    assert tie_kinds([old], [finding("G2", "typed", "42", line=80, key="G2|t|42|c")]) == ["none"]
    # Several: two at its place with its context, naming its words.
    near = {**old, "message": "'Studies show' and no citation", "key": k2}
    assert tie_kinds([old], [{**old, "key": k1}, near]) == ["several"]
    # Taken: another judged finding, not its twin, has it.
    other_one = {**old, "message": "'Studies show' with a citation far off"}
    assert tie_kinds([old, other_one], [{**old, "key": k1}]) == ["tie", "taken"]
    # Twins of the judged run at one place, one candidate: no pass may say which is which.
    assert tie_kinds([old, {**old}], [{**old, "key": k1}]) == ["several", "several"]
    # A weaker pass: the same message at another line.
    assert tie_kinds([old], [{**old, "line": 9, "context": "moved", "key": k1}]) == ["weaker"]
    # Another code at its place, naming its words.
    other = finding("G6", "ai-phrasing", "'Studies show' is a phrase", line=5, key="G6|a|s|d")
    assert tie_kinds([old], [other]) == ["cross-code"]
    # Its candidate's key stands twice in the keyed run: it ties to that key as a family,
    # whose count the count rule then reads (rule 1).
    repeated = [{**old, "key": k1}, {**old, "line": 60, "context": "x", "key": k1}]
    [(kind, how, listed)] = keys.tie_group([old], repeated, "paper-a")
    assert (kind, how, listed[0]["key"]) == ("tie", "key family", k1)


def test_a_form_a_list_holds_ties_to_the_form_s_key_never_the_list_s() -> None:
    sentence = "the HR and the OR were estimated"
    old = finding("G14", "abbreviation-undefined", "HR is used once in the main text and not "
                  "defined there", line=20, context=sentence)  # fmt: skip
    question = finding("G14", "abbreviation-undefined", "2 short forms are used and never "
                       "defined: 'HR' here, then OR. Do any need defining?", "info", line=20,
                       context=sentence, question=True, key="G14|abbreviation-undefined|-|-",
                       forms=[{"form": "HR", "key": K_HR, "message": old["message"]},
                              {"form": "OR", "key": "G14|abbreviation-undefined|OR@main|-"}])
    [(kind, how, listed)] = keys.tie_group([old], [question], "paper-a")
    assert (kind, how, listed[0]["key"]) == ("tie", "short form, any pass", K_HR)
    twice = {**question, "forms": [question["forms"][0], question["forms"][0]]}
    assert keys.tie_group([old], [twice], "paper-a")[0][0] == "several"


def test_the_ambiguous_list_is_laid_out_for_the_author(corpus: Path) -> None:
    write_run(corpus, "tied", [{**f, "line": 77, "context": "elsewhere"} for f in TIED])
    said = tool.tie(corpus, "judged", "tied")
    assert said["tied"] == 0 and said["ambiguous"] == 4
    # Paired only by a weaker pass, they are left untied, apart from what the author settles.
    page = (corpus / "report" / "ties-untied.md").read_text("utf-8")
    assert "**paper-a check 0** (true, G14/spelling-variant, paired by message)" in page
    assert f"`{K_SPELL}`" in page
    asked = (corpus / "report" / "ties-ambiguous.md").read_text("utf-8")
    assert "for the author to tie: 0" in asked and "report/ties-decided.yaml" in asked
    # The verdicts and the ledger are not touched.
    assert not (corpus / "report" / "ledger.yaml").exists()
    verdicts = json.loads((corpus / "report" / "judged" / "f.json").read_text("utf-8"))
    assert [v["verdict"] for v in verdicts] == ["true", "true", "true", "false"]


def test_a_tie_needs_a_keyed_run_and_well_formed_ties(corpus: Path) -> None:
    with pytest.raises(tool.CorpusError, match="carries no keys"):
        tool.tie(corpus, "judged", "judged")
    (corpus / "report" / "ties.yaml").write_text("run: tied\nties: [{slug: a}]\n", "utf-8")
    with pytest.raises(tool.CorpusError, match="slug, report, index, key and how"):
        keys.load_ties(corpus)


# --- the two exact rules (Basile, 2026-11-20) -------------------------------------------


def test_a_finding_with_no_line_ties_by_its_one_message() -> None:
    old = finding("G11", "no-review", "no review panel is recorded", line=None)
    key = "G11|no-review|~0123456789ab|-"
    [(kind, how, listed)] = keys.tie_group([old], [{**old, "key": key}], "paper-a")
    assert (kind, how, listed[0]["key"]) == ("tie", "message, no line", key)
    # Two of that message in the keyed run, or in the judged run: which is which is the
    # author's to say.
    twice = [{**old, "key": key}, {**old, "key": key + "x"}]
    assert keys.tie_group([old], twice, "paper-a")[0][0] == "several"
    # Where the keyed run has one and the judged run two, one is lost already: which cannot
    # be told, so neither ties, whatever their verdicts (no family of one for two).
    assert keys.tie_group([old], [{**old, "key": key}], "paper-a",
                          judged_all=[old, {**old}])[0][0] == "several"  # fmt: skip
    assert [kind for kind, _h, _l in keys.tie_group(
        [old, {**old}], [{**old, "key": key}], "paper-a",
        verdicts=["true", "false"])] == ["several", "several"]
    # Two versions' line-less findings of one message are told apart by their files.
    v1, v2 = {**old, "path": "v1/paper.tex"}, {**old, "path": "latest/paper.tex"}
    said = keys.tie_group([v1, v2], [{**v1, "key": "c|v|v1|-"}, {**v2, "key": "c|v|v2|-"}],
                          "paper-a", judged_all=[v1, v2])  # fmt: skip
    assert [listed[0]["key"] for _k, _h, listed in said] == ["c|v|v1|-", "c|v|v2|-"]
    # Its candidate's key repeated in the keyed run: a family too.
    other = {**old, "message": "another message", "key": key}
    assert keys.tie_group([old], [{**old, "key": key}, other], "paper-a")[0][:2] == (
        "tie", "key family")


def short_form(form: str, scope: str, line: int) -> dict:
    said = {"main": "the main text", "abstract": "the abstract"}[scope]
    return {"form": form, "line": line, "path": "paper.docx",
            "key": f"G14|abbreviation-undefined|{form}@{scope}|-",
            "message": f"{form} is used once in {said} as G14 reads it, and not defined there"}


def test_a_short_form_paired_with_a_list_s_entry_ties_to_its_form_and_scope() -> None:
    old = finding("G14", "abbreviation-undefined", "HR is used once in the main text and not "
                  "defined there", line=20)  # fmt: skip
    question = finding("G14", "abbreviation-undefined", "2 short forms are used and never "
                       "defined: 'OR' here, then HR. Do any need defining?", "info", line=3,
                       question=True, key="G14|abbreviation-undefined|-|-",
                       forms=[short_form("OR", "main", 3), short_form("HR", "abstract", 2),
                              short_form("HR", "main", 40)])  # fmt: skip
    [(kind, how, listed)] = keys.tie_group([old], [question], "paper-a")
    assert (kind, how, listed[0]["key"]) == ("tie", "form entry",
                                             "G14|abbreviation-undefined|HR@main|-")  # fmt: skip
    # The same form in two scopes, and a judged message that names neither: the author's.
    unscoped = finding("G14", "abbreviation-undefined", "HR is used and not defined", line=2)
    assert keys.tie_group([unscoped], [question], "paper-a")[0][0] == "several"
    # Two judged findings of that form and scope in the judged run.
    assert keys.tie_group([old], [question], "paper-a",
                          judged_all=[old, {**old, "line": 30}])[0][0] == "several"  # fmt: skip
    # A name in code has no scope to hold it to: it stays untied.
    name = finding("G14", "code-name-in-prose", "'k_B' is written with underscores", line=8)
    grouped = finding("G14", "code-name-in-prose", "1 name ...: 'k_B' here", "info", line=8,
                      question=True, key="G14|code-name-in-prose|-|-",
                      forms=[{"form": "k_B", "line": 8, "key": "G14|code-name-in-prose|k_B|-",
                              "message": "'k_B' is written with underscores, the way ..."}])
    assert keys.tie_group([name], [grouped], "paper-a")[0][0] != "tie"


# --- the three exact rules of 2026-11-20, second round ----------------------------------

XXXX = "G6|model-artefact|placeholder-word: xxxx#{}|51b279a01b51"


def test_candidates_of_one_key_family_tie_to_the_family() -> None:
    old = finding("G6", "model-artefact", "'xxxx' — Unfilled placeholder text", line=5)
    new = [{**old, "key": XXXX.format(n)} for n in (1, 2, 3, 4)]
    said = keys.tie_group([old, {**old}, {**old}, {**old}], new, "paper-a",
                          verdicts=["false"] * 4)  # fmt: skip
    family = "G6|model-artefact|placeholder-word: xxxx|51b279a01b51"
    assert [(kind, how, listed[0]["key"]) for kind, how, listed in said] == [
        ("tie", "key family", family)] * 4
    # Candidates that differ by more than the ordinal are no family.
    other = [{**old, "key": XXXX.format(1)}, {**old, "key": XXXX.format(2).replace("51b2", "aaaa")}]
    assert keys.tie_group([old], other, "paper-a")[0][0] == "several"


def test_the_count_rule_reads_a_family_s_count(corpus: Path) -> None:
    old = finding("G6", "model-artefact", "'xxxx' — Unfilled placeholder text", line=5)
    family = "G6|model-artefact|placeholder-word: xxxx|51b279a01b51"
    four = [{**old, "key": XXXX.format(n)} for n in (1, 2, 3, 4)]
    (corpus / "report" / "packets" / "f.json").write_text(json.dumps([{
        "slug": "paper-a", "reports": {"check": {"findings": [old, old]}}}]))
    (corpus / "report" / "judged" / "f.json").write_text(json.dumps([
        {"slug": "paper-a", "report": "check", "index": i, "verdict": "true"} for i in (0, 1)]))
    write_run(corpus, "tied", four)
    write_run(corpus, "judged", [old, old])
    said = tool.tie(corpus, "judged", "tied")
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    assert said["by_pass"] == {"key family": 2}
    assert [(t["key"], t["family"]) for t in document["ties"]] == [(family, True)] * 2
    # One of the four gone: both judged findings under the family are lost; all four kept,
    # or more, none is.
    write_run(corpus, "new", four[:3])
    result = tool.gate(corpus, "tied", "new")
    assert len(result["lost"]) == 2 and all(r["fell"] for r in result["lost"])
    write_run(corpus, "new", [*four, {**old, "key": XXXX.format(5)}])
    assert tool.gate(corpus, "tied", "new")["ok"]


def test_twins_of_one_verdict_tie_one_to_one_in_order() -> None:
    old = finding("G6", "ai-phrasing", "An -ing tail asserting significance", line=7)
    new = [{**old, "key": "G6|ai-phrasing|tail: reflecting the|e13", "col": 90},
           {**old, "key": "G6|ai-phrasing|tail: reflecting a|f84", "col": 12}]
    said = keys.tie_group([old, {**old}], new, "paper-a", verdicts=["true", "true"])
    assert [(kind, how, listed[0]["key"]) for kind, how, listed in said] == [
        ("tie", "twins", "G6|ai-phrasing|tail: reflecting a|f84"),
        ("tie", "twins", "G6|ai-phrasing|tail: reflecting the|e13")]
    # With no column, by key; their verdicts differ, or their numbers do: refused.
    lineless = [{**c, "col": None} for c in new]
    assert keys.tie_group([old, {**old}], lineless, "paper-a",
                          verdicts=["true", "true"])[0][2][0]["key"].endswith("a|f84")
    assert [kind for kind, _h, _l in keys.tie_group(
        [old, {**old}], new, "paper-a", verdicts=["true", "false"])] == ["several"] * 2
    third = {**old, "key": "G6|ai-phrasing|tail: reflecting it|0c1", "col": 50}
    assert [kind for kind, _h, _l in keys.tie_group(
        [old, {**old}], [*new, third], "paper-a", verdicts=["true", "true"])] == ["several"] * 2


def test_a_short_form_ties_to_its_entry_in_its_scope_whatever_the_pass() -> None:
    sentence = "AYUSH guidelines were followed"
    old = finding("G14", "abbreviation-undefined", "AYUSH is used 31 times in the abstract "
                  "and not defined there", line=4, context=sentence)  # fmt: skip
    question = finding("G14", "abbreviation-undefined", "88 short forms are used and never "
                       "defined: 'AYUSH' here, then COVID. Do any need defining?", "info",
                       line=4, context=sentence, question=True,
                       key="G14|abbreviation-undefined|-|-",
                       forms=[short_form("AYUSH", "abstract", 4),
                              short_form("AYUSH", "main", 60)])  # fmt: skip
    [(kind, how, listed)] = keys.tie_group([old], [question], "paper-a")
    assert (kind, how, listed[0]["key"]) == ("tie", "short form, any pass",
                                             "G14|abbreviation-undefined|AYUSH@abstract|-")
    # In two scopes, and the judged message names neither: the author's.
    unscoped = {**old, "message": "AYUSH is used and not defined"}
    assert keys.tie_group([unscoped], [question], "paper-a")[0][0] == "several"


def test_the_author_s_decisions_are_read_as_ties_and_checked(corpus: Path) -> None:
    write_run(corpus, "tied", [{**f, "line": 77, "context": "elsewhere"} for f in TIED])
    tool.tie(corpus, "judged", "tied")
    write_run(corpus, "keyed", [{**f, "message": "said otherwise", "line": 99} for f in TIED])
    assert tool.measure(corpus, "keyed", ledger=False)["keys"]["by_key"] == 0
    decided = corpus / "report" / "ties-decided.yaml"
    decided.write_text(yaml.safe_dump([
        {"slug": "paper-a", "report": "check", "index": 0, "key": K_SPELL, "by": "the author",
         "date": "2026-11-20"},
        {"slug": "paper-a", "report": "check", "index": 1, "key": None, "by": "the author",
         "date": "2026-11-20"}]), "utf-8")  # fmt: skip
    result = tool.measure(corpus, "keyed", ledger=False)
    rows = {r["index"]: r for r in result["findings"]}
    assert (rows[0]["by_key"], rows[0]["state"]) == (True, "reported")
    assert (rows[1]["by_key"], rows[1]["state"]) == (True, "gone")
    for bad, says in (({"index": 9}, "is no judged finding"),
                      ({"key": "G9|nothing|x|-"}, "is not in tied's paper-a check"),
                      ({"by": None, "date": None, "who": "x"}, "a decision is")):
        entry = {"slug": "paper-a", "report": "check", "index": 0, "key": K_SPELL,
                 "by": "the author", "date": "2026-11-20", **bad}
        entry = {k: v for k, v in entry.items() if v is not None}
        decided.write_text(yaml.safe_dump([entry]), "utf-8")
        with pytest.raises(tool.CorpusError, match=says):
            tool.measure(corpus, "keyed", ledger=False)


# --- round 1 of #708 ------------------------------------------------------------------


def test_a_family_gone_where_a_successor_stands_reads_elsewhere(corpus: Path) -> None:
    family = "G6|model-artefact|placeholder-word: xxxx|51b279a01b51"
    question = finding("audit", "question-no-abstract", "Where is the Abstract?", "info",
                       key="audit|question-no-abstract|-|-")  # fmt: skip
    said = keys.family_state(family, keys.Keys([question]), 2, ("audit/question-no-abstract",))
    assert said.state == "elsewhere"
    assert keys.family_state(family, keys.Keys([question]), 2).state == "gone"
    # And so does a repeated key gone whole.
    k2 = "G7|citation-unresolved|~ceca1c0200bd|-"
    assert keys.key_state(k2, keys.Keys([question]), 2, ("audit/question-no-abstract",)
                          ).state == "elsewhere"  # fmt: skip
    # Through the gate: tied to a family, gone at new, the ledger's successor stands.
    old = finding("G6", "model-artefact", "'xxxx' — Unfilled placeholder text", line=5)
    (corpus / "report" / "packets" / "f.json").write_text(json.dumps([{
        "slug": "paper-a", "reports": {"check": {"findings": [old]}}}]))
    (corpus / "report" / "judged" / "f.json").write_text(json.dumps([
        {"slug": "paper-a", "report": "check", "index": 0, "verdict": "true"}]))
    write_run(corpus, "judged", [old])
    write_run(corpus, "tied", [{**old, "key": XXXX.format(n)} for n in (1, 2)])
    tool.tie(corpus, "judged", "tied")
    write_run(corpus, "new", [question])
    ledger = {"decisions": [{"id": "s", "date": "2026-11-20", "by": "the author", "what": "w",
                             "source": "#1", "successor": {
                                 "from": "G6/model-artefact",
                                 "to": ["audit/question-no-abstract"], "scope": "paper"}}]}
    (corpus / "report" / "ledger.yaml").write_text(yaml.safe_dump(ledger), "utf-8")
    result = tool.gate(corpus, "tied", "new")
    assert result["ok"] and result["keys"]["by_key"] == 1


def test_the_scheme_of_a_commit_is_read_from_its_text() -> None:
    def reader(text):
        return lambda cmd: text

    assert tool.corpus_run.scheme_of(REPO, "abc", reader(b"SCHEME = 2  # #709\n")) == 2
    assert tool.corpus_run.scheme_of(REPO, "abc", reader(b"NONE = '-'\n")) == 1

    # A commit with no keys.py, as ls-tree lists none: 1, whatever language git speaks.
    def git(listed: bytes):
        def read(cmd):
            if "ls-tree" in cmd:
                return listed
            if "show" in cmd:
                raise tool.CorpusError("git show failed: fatal: le chemin "
                                       "'src/manuscript_guard/keys.py' n'existe pas dans 'abc'")
            return b"abc\n"
        return read

    assert tool.corpus_run.scheme_of(REPO, "abc", git(b"")) == 1

    # An unknown commit, or any other failure of git, is refused.
    def unknown(cmd):
        raise tool.CorpusError("git rev-parse failed: fatal: Needed a single revision")

    with pytest.raises(tool.CorpusError, match="Needed a single revision"):
        tool.corpus_run.scheme_of(REPO, "abc", unknown)
    with pytest.raises(tool.CorpusError, match="n'existe pas"):
        tool.corpus_run.scheme_of(REPO, "abc", git(b"src/manuscript_guard/keys.py\n"))
    asked = []
    tool.corpus_run.scheme_of(REPO, "abc", lambda cmd: asked.append(cmd[3]) or b"SCHEME = 2")
    assert asked == ["rev-parse", "ls-tree", "show"]


@pytest.mark.parametrize(("text", "scheme"), [
    (b"SCHEME: int = 2\n", 2),
    (b"SCHEME = (2)\n", 2),
    (b"SCHEME = 2\nSCHEME = 3\n", 3),
    (b'"""The keys.\n\nSCHEME = 1\n"""\nSCHEME = 2\n', 2),
    (b'"""The keys.\nSCHEME = 4\n"""\n', 1),
    (b"def f():\n    SCHEME = 9\n", 1),
    (b"class K:\n    SCHEME = 9\nSCHEME = 2\n", 2),
    (b"\xef\xbb\xbfSCHEME = 2\n", 2),  # a UTF-8 byte order mark
])  # fmt: skip
def test_the_scheme_is_the_last_module_level_assignment(text: bytes, scheme: int) -> None:
    assert tool.corpus_run.scheme_of(REPO, "abc", lambda cmd: text) == scheme


@pytest.mark.parametrize("text", [
    b"SCHEME = '2'\n", b"SCHEME = 2.0\n", b"SCHEME = (\n",
    b"try:\n    SCHEME = 2\nexcept ImportError:\n    pass\n",
    b"if True:\n    SCHEME = 2\n", b"with open('x') as f:\n    SCHEME = 2\n",
    b"SCHEME = 2\nSCHEME += 1\n", b"SCHEME, OTHER = 2, 3\n", b"for SCHEME in (2,):\n    pass\n",
])  # fmt: skip
def test_a_scheme_that_is_no_int_or_does_not_parse_is_refused(text: bytes) -> None:
    with pytest.raises(tool.CorpusError, match="SCHEME no int|does not parse|stores to SCHEME"):
        tool.corpus_run.scheme_of(REPO, "abc", lambda cmd: text)


def test_a_run_s_scheme_is_the_one_it_recorded_or_1(corpus: Path, monkeypatch) -> None:
    folder = corpus / "runs" / "tied"

    def never(*args, **kwargs):
        raise AssertionError("git was asked")

    monkeypatch.setattr(tool.corpus_run, "scheme_of", never)
    (folder / "run.json").write_text(json.dumps({"sha": "no-such-commit"}), "utf-8")
    assert tool.Run(folder).scheme == 1
    (folder / "run.json").write_text(json.dumps({"sha": "abc", "scheme": 3}), "utf-8")
    assert tool.Run(folder).scheme == 3
    assert tool.Run(corpus / "runs" / "judged").scheme == 1


def scheme(root: Path, run: str, number: int) -> None:
    (root / "runs" / run / "run.json").write_text(json.dumps({"scheme": number}), "utf-8")


def test_a_change_of_scheme_gates_by_message_and_one_scheme_by_key(corpus: Path) -> None:
    tool.tie(corpus, "judged", "tied")
    assert yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))["scheme"] == 1
    # Every key moved by a scheme-raising change, and nothing else.
    write_run(corpus, "new", [{**f, "key": f["key"] + "-moved"} for f in TIED])
    scheme(corpus, "tied", 1)
    scheme(corpus, "new", 2)
    result = tool.gate(corpus, "tied", "new")
    assert result["ok"] and result["keys"]["by_key"] == 0
    assert result["scheme_note"] == ("keys changed scheme (1 \N{RIGHTWARDS ARROW} 2): paired "
                                     "by message; tie again after this merges")  # fmt: skip
    assert result["scheme_note"] in tool.render_gate(result)
    # On one scheme, the keys decide: moved, they are lost.
    scheme(corpus, "new", 1)
    result = tool.gate(corpus, "tied", "new")
    assert not result["ok"] and result["keys"]["by_key"] == 4 and not result["scheme_note"]
    # measure likewise keeps to the matcher for a run of another scheme.
    scheme(corpus, "new", 2)
    measured = tool.measure(corpus, "new", ledger=False)
    assert measured["keys"]["by_key"] == 0 and measured["scheme_note"]


def test_a_key_that_is_no_string_is_refused(corpus: Path) -> None:
    old = finding("G6", "vague-attribution", "'Studies show' with no citation", line=5)
    assert [kind for kind, _h, _l in keys.tie_group([old], [{**old}], "paper-a")] == ["none"]
    (corpus / "report" / "ties.yaml").write_text(yaml.safe_dump({"run": "tied", "ties": [
        {"slug": "paper-a", "report": "check", "index": 0, "key": None, "how": "x"}]}), "utf-8")
    with pytest.raises(tool.CorpusError, match="a tie's key is a string"):
        keys.load_ties(corpus)
    # A run with no keys never reads the ties, malformed or not.
    write_run(corpus, "plain", [f for f, _ in JUDGED])
    assert tool.measure(corpus, "plain", ledger=False)["keys"]["by_key"] == 0


def test_a_judged_finding_decided_twice_is_refused(corpus: Path) -> None:
    entry = {"slug": "paper-a", "report": "check", "index": 0, "key": K_SPELL,
             "by": "the author", "date": "2026-11-20"}
    (corpus / "report" / "ties-decided.yaml").write_text(yaml.safe_dump([entry, entry]), "utf-8")
    with pytest.raises(tool.CorpusError, match="decided twice"):
        keys.load_decided(corpus)
    (corpus / "report" / "ties-decided.yaml").write_text(
        yaml.safe_dump([{**entry, "key": 7}]), "utf-8")
    with pytest.raises(tool.CorpusError, match="a string or null"):
        keys.load_decided(corpus)


def test_the_note_names_each_scheme_where_only_the_ties_differ(corpus: Path) -> None:
    write_run(corpus, "new", TIED)
    for tied, runs in ((1, 2), (2, 1)):
        scheme(corpus, "tied", tied)
        tool.tie(corpus, "judged", "tied")
        write_run(corpus, "base", TIED)
        scheme(corpus, "base", runs)
        scheme(corpus, "new", runs)
        result = tool.gate(corpus, "base", "new")
        assert result["keys"]["by_key"] == 0
        assert result["scheme_note"] == (
            f"the ties are of key scheme {tied} and the runs of scheme {runs}: paired by "
            f"message; tie again against a run of scheme {runs}")
    # Base and new apart, the ties on neither's side: each is named.
    scheme(corpus, "base", 1)
    scheme(corpus, "new", 3)
    assert tool.gate(corpus, "base", "new")["scheme_note"] == (
        "keys changed scheme (1 \N{RIGHTWARDS ARROW} 3) (the ties are of scheme 2): paired by "
        "message; tie again after this merges")


def test_the_ties_error_names_every_key_allowed_and_the_count_rule_its_exception(
        corpus: Path) -> None:  # fmt: skip
    (corpus / "report" / "ties.yaml").write_text("run: tied\nties: []\nwho: x\n", "utf-8")
    with pytest.raises(tool.CorpusError, match="`judged_run`, `scheme` and `batches`"):
        keys.load_ties(corpus)
    exception = "unless none is left and it stands elsewhere"
    assert exception in (REPO / "docs" / "corpus.md").read_text("utf-8")
    assert exception in " ".join(keys.key_state.__doc__.split())


# --- a paper removed after judging ------------------------------------------------------


def test_tie_leaves_out_a_removed_paper_and_a_decision_on_it_refuses_nothing(
        corpus: Path) -> None:  # fmt: skip
    why = {"by": "the author", "date": "2026-11-23", "why": "a data readme"}
    other = finding("G7", "doi-unresolved", "10.1/abc does not resolve", line=4)
    for name, entry in (("packets", {"slug": "paper-b", "text": "made up",
                                     "reports": {"check": {"findings": [other]}}}),
                        ("judged", {"slug": "paper-b", "report": "check", "index": 0,
                                    "verdict": "true"})):  # fmt: skip
        path = corpus / "report" / name / "f.json"
        path.write_text(json.dumps([*json.loads(path.read_text("utf-8")), entry]), "utf-8")
    for run, found in (("judged", other), ("tied", {**other, "key": "G7|doi-unresolved|a|-"})):
        folder = corpus / "runs" / run / "paper-b"
        folder.mkdir()
        (folder / "check.json").write_text(json.dumps({"findings": [found]}), "utf-8")
    assert tool.tie(corpus, "judged", "tied")["tied"] == 5
    (corpus / "corpus" / "paper-b").mkdir(parents=True)
    meta = {"slug": "paper-b", "format": "pdf", "main": "p.pdf", "removed": why}
    (corpus / "corpus" / "paper-b" / "meta.json").write_text(json.dumps(meta), "utf-8")
    said = tool.tie(corpus, "judged", "tied")
    assert said["tied"] == 4 and said["removed"] == [{"slug": "paper-b", **why, "verdicts": 1}]
    document = yaml.safe_load((corpus / "report" / "ties.yaml").read_text("utf-8"))
    assert {t["slug"] for t in document["ties"]} == {"paper-a"}
    told = keys.render_tie(said)
    assert "paper-b" in told and "a data readme" in told
    # The author's tie of its finding, made before it left, is read nowhere and refused nowhere.
    (corpus / "report" / "ties-decided.yaml").write_text(yaml.safe_dump([
        {"slug": "paper-b", "report": "check", "index": 0, "key": None, "by": "the author",
         "date": "2026-11-20"}]), "utf-8")  # fmt: skip
    result = tool.measure(corpus, "tied", ledger=False)
    assert {r["slug"] for r in result["findings"]} == {"paper-a"}
