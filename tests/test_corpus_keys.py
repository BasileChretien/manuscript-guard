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
    # Taken: another judged finding has it.
    assert tie_kinds([old, {**old}], [{**old, "key": k1}]) == ["tie", "taken"]
    # A weaker pass: the same message at another line.
    assert tie_kinds([old], [{**old, "line": 9, "context": "moved", "key": k1}]) == ["weaker"]
    # Another code at its place, naming its words.
    other = finding("G6", "ai-phrasing", "'Studies show' is a phrase", line=5, key="G6|a|s|d")
    assert tie_kinds([old], [other]) == ["cross-code"]
    # Its candidate's key stands twice in the keyed run.
    assert tie_kinds([old], [{**old, "key": k1}, {**old, "line": 60, "context": "x",
                                                  "key": k1}]) == ["repeated"]  # fmt: skip


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
    assert (kind, how, listed[0]["key"]) == ("tie", "context+place", K_HR)
    twice = {**question, "forms": [question["forms"][0], {**question["forms"][0],
                                                         "key": K_HR + "#2"}]}  # fmt: skip
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
    assert keys.tie_group([old], [{**old, "key": key}], "paper-a",
                          judged_all=[old, {**old}])[0][0] == "several"  # fmt: skip
    # Its candidate's key repeated in the keyed run.
    other = {**old, "message": "another message", "key": key}
    assert keys.tie_group([old], [{**old, "key": key}, other], "paper-a")[0][0] == "repeated"


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
