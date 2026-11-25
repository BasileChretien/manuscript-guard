"""The ledger's `accepted` and `moved` decisions in `tools/corpus.py`, on a made-up mini corpus.

The author's rules (2026-11-25, "Two new kinds"): an `accepted` decision names judged findings
whose loss the author accepts, and the gate lists such a loss apart and does not fail on it;
a `moved` decision names the key that carries a judged finding now, in a run of that key's
scheme, and the judged finding takes that finding's state there. Neither changes a verdict.
"""

from __future__ import annotations

import importlib.util
import json
import re
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


def finding(gate: str, code: str, message: str, severity: str = "warn", line: int = 10,
            key: str | None = None, **extra) -> dict:  # fmt: skip
    said = {"gate": gate, "code": code, "message": message, "severity": severity, "line": line,
            "path": "paper.pdf", "context": None, **extra}
    return {**said, "key": key} if key is not None else said


K_ABSTRACT = "G14|abbreviation-unused|MESO@abstract|-"
K_MAIN = "G14|abbreviation-unused|MESO@main|-"
K_SPELL = "G14|spelling-variant|color|-"
K_ENTRY = "G7|entry-never-cited|~0a1b2c3d4e5f|-"
K_PHRASE = "G6|ai-phrasing|delve into|1234567890ab"

#: The judged findings: a short form the new run reads in another part, a spelling kept, an
#: entry of the reference list the new run no longer gives, and a false finding.
JUDGED = [
    (finding("G14", "abbreviation-unused", "MESO is defined in the Abstract and not used "
             "there", line=4), "true"),  # fmt: skip
    (finding("G14", "spelling-variant", "'color' is the American spelling", line=9), "true"),
    (finding("G7", "entry-never-cited", "entry 3 of the reference list is never cited",
             line=80), "true"),  # fmt: skip
    (finding("G6", "ai-phrasing", "'delve into' is a phrase models favour", line=12), "false"),
]
TIED = [finding(**{k: f[k] for k in ("gate", "code", "message", "line")}, key=key)
        for (f, _), key in zip(JUDGED, (K_ABSTRACT, K_SPELL, K_ENTRY, K_PHRASE), strict=True)]
MOVED_FINDING = finding("G14", "abbreviation-unused", "MESO is defined in the main text and "
                        "not used there", line=4, key=K_MAIN)  # fmt: skip
#: The new run: the short form under the main text's key, the entry gone.
NEW = [MOVED_FINDING, TIED[1], TIED[3]]

PLACE = {"slug": "paper-a", "report": "audit-pdf"}
ACCEPT = {"id": "entry-no-citation", "date": "2026-11-25", "by": "the author",
          "what": "the text cites nothing by number", "source": "#782",
          "accepted": {"findings": [{**PLACE, "index": 2}]}}
MOVE = {"id": "abstract-ends-at-keywords", "date": "2026-11-25", "by": "the author",
        "what": "the Abstract ends at its Keywords line", "source": "#783",
        "moved": {"findings": [{**PLACE, "index": 0, "to": K_MAIN, "scheme": 1}]}}


def write_run(root: Path, name: str, found: list[dict]) -> None:
    folder = root / "runs" / name / "paper-a"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "audit-pdf.json").write_text(json.dumps({"findings": found}), "utf-8")


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus-root"
    (root / "report" / "packets").mkdir(parents=True)
    (root / "report" / "judged").mkdir()
    packet = [{"slug": "paper-a", "text": "made up",
               "reports": {"audit-pdf": {"findings": [f for f, _ in JUDGED]}}}]
    verdicts = [{**PLACE, "index": i, "verdict": v} for i, (_, v) in enumerate(JUDGED)]
    (root / "report" / "packets" / "f.json").write_text(json.dumps(packet))
    (root / "report" / "judged" / "f.json").write_text(json.dumps(verdicts))
    write_run(root, "judged", [f for f, _ in JUDGED])
    write_run(root, "tied", TIED)
    write_run(root, "new", NEW)
    assert tool.tie(root, "judged", "tied")["tied"] == 4
    return root


def with_ledger(root: Path, *decisions: dict) -> Path:
    (root / "report" / "ledger.yaml").write_text(
        yaml.safe_dump({"decisions": list(decisions)}), "utf-8")
    return root


def lost(result: dict) -> list[tuple[str, int]]:
    return [(r["code"], r["index"]) for r in result["lost"]]


def test_without_the_ledger_both_findings_are_lost(corpus: Path) -> None:
    result = tool.gate(corpus, "tied", "new")
    assert not result["ok"] and result["keys"]["by_key"] == 4
    assert lost(result) == [("G14/abbreviation-unused", 0), ("G7/entry-never-cited", 2)]
    assert result["accepted"] == [] and result["moved"] == []
    # The finding under the main text's key is no judged one's: unjudged, and fresh.
    assert result["unjudged"]["G14/abbreviation-unused"] == {"base": 0, "new": 1}
    assert result["fresh"]["by_code"] == {"G14/abbreviation-unused": 1}


# --- accepted ---------------------------------------------------------------------------


def check_accepted(root: Path) -> None:
    result = tool.gate(with_ledger(root, ACCEPT), "tied", "new")
    assert lost(result) == [("G14/abbreviation-unused", 0)]
    assert [(r["code"], r["base"], r["state"], r["accepted_by"]) for r in result["accepted"]
            ] == [("G7/entry-never-cited", "reported", "gone", "entry-no-citation")]  # fmt: skip
    assert "lost, accepted by entry-no-citation" in tool.render_gate(result)


def test_an_accepted_loss_is_listed_apart_and_does_not_block(corpus: Path) -> None:
    check_accepted(corpus)
    result = tool.gate(with_ledger(corpus, ACCEPT, MOVE), "tied", "new")
    assert result["ok"] and result["lost"] == []
    text = tool.render_gate(result)
    assert "**Passes**" in text and "1 loss the ledger accepts" in text
    assert "### True findings lost, accepted by the ledger (1)" in text
    assert tool.main(["--corpus", str(corpus), "gate", "tied", "new"]) == 0


def test_an_accepted_finding_keeps_its_verdict_and_its_state(corpus: Path) -> None:
    rows = {r["index"]: r for r in tool.measure(with_ledger(corpus, ACCEPT), "new")["findings"]}
    assert (rows[2]["verdict"], rows[2]["rejudged_by"], rows[2]["state"]) == ("true", "", "gone")
    measured = tool.measure(corpus, "new")
    assert measured["decisions"] == [{"id": "entry-no-citation", "kind": "accepted",
                                      "matched": 1, "changed": 0, "successor": 0, "moved": 0}]
    assert measured["totals"] == tool.measure(corpus, "new", ledger=False)["totals"]


def test_an_accepted_decision_of_a_mistyped_place_accepts_nothing(corpus: Path) -> None:
    wrong = {**ACCEPT, "accepted": {"findings": [{**PLACE, "index": 7}]}}
    assert lost(tool.gate(with_ledger(corpus, wrong, MOVE), "tied", "new")) == [
        ("G7/entry-never-cited", 2)]
    assert tool.measure(corpus, "new")["decisions"][0]["matched"] == 0
    batch = {**ACCEPT, "accepted": {"findings": [{**PLACE, "index": 2, "batch": "b1"}]}}
    assert not tool.gate(with_ledger(corpus, batch, MOVE), "tied", "new")["ok"]


# --- moved ------------------------------------------------------------------------------


def check_moved(root: Path) -> None:
    result = tool.gate(with_ledger(root, MOVE), "tied", "new")
    assert lost(result) == [("G7/entry-never-cited", 2)]
    assert [(r["index"], r["base"], r["state"], r["moved_by"]) for r in result["moved"]] == [
        (0, "reported", "reported", "abstract-ends-at-keywords")]
    # The finding that carries it is accounted for: neither unjudged nor fresh.
    assert "G14/abbreviation-unused" not in result["unjudged"]
    assert result["fresh"]["count"] == 0


def test_a_moved_finding_takes_the_state_of_the_key_that_carries_it(corpus: Path) -> None:
    check_moved(corpus)
    measured = tool.measure(corpus, "new")
    row = next(r for r in measured["findings"] if r["index"] == 0)
    assert (row["state"], row["moved_by"], row["verdict"]) == (
        "reported", "abstract-ends-at-keywords", "true")
    assert measured["decisions"] == [{"id": "abstract-ends-at-keywords", "kind": "moved",
                                      "matched": 1, "changed": 0, "successor": 0, "moved": 1}]
    text = tool.render_measure(measured)
    assert "1 moved to the key that carries them now" in text
    assert "| abstract-ends-at-keywords | moved | 1 | 0 | 0 | 1 |" in text


@pytest.mark.parametrize(("now", "state"), [
    ({"severity": "info"}, "asked"),
    ({"question": True}, "asked"),
    ({"code": "abbreviation-redefined", "key": "G14|abbreviation-redefined|MESO@main|-"},
     "elsewhere"),
])  # fmt: skip
def test_a_moved_finding_is_asked_or_elsewhere_as_its_carrier_is(corpus: Path, now: dict,
                                                                  state: str) -> None:  # fmt: skip
    write_run(corpus, "new", [{**MOVED_FINDING, **now}, *NEW[1:]])
    move = {**MOVE, "moved": {"findings": [{**PLACE, "index": 0, "to": now.get("key", K_MAIN),
                                            "scheme": 1}]}}  # fmt: skip
    rows = tool.measure(with_ledger(corpus, move), "new")["findings"]
    assert next(r["state"] for r in rows if r["index"] == 0) == state


def test_a_form_a_list_holds_under_the_key_asks_it(corpus: Path) -> None:
    question = finding("G14", "abbreviation-unused", "2 short forms are defined and not used: "
                       "MESO, then TLA", "info", key="G14|abbreviation-unused|-|-",
                       question=True, forms=[{"form": "MESO", "key": K_MAIN},
                                             {"form": "TLA", "key": "G14|x|TLA@main|-"}])
    write_run(corpus, "new", [question, *NEW[1:]])
    rows = tool.measure(with_ledger(corpus, MOVE), "new")["findings"]
    assert next((r["state"], r["moved_by"]) for r in rows if r["index"] == 0) == (
        "asked", "abstract-ends-at-keywords")


def check_other_scheme(root: Path) -> None:
    other = {**MOVE, "moved": {"findings": [{**PLACE, "index": 0, "to": K_MAIN, "scheme": 2}]}}
    result = tool.gate(with_ledger(root, other), "tied", "new")
    assert lost(result)[0] == ("G14/abbreviation-unused", 0) and result["moved"] == []
    assert result["unjudged"]["G14/abbreviation-unused"]["new"] == 1
    measured = tool.measure(root, "new")
    assert measured["decisions"][0]["matched"] == 1 and measured["decisions"][0]["moved"] == 0


def test_a_move_of_another_scheme_moves_nothing(corpus: Path) -> None:
    check_other_scheme(corpus)


def test_a_move_to_a_key_no_finding_has_moves_nothing(corpus: Path) -> None:
    absent = {**MOVE, "moved": {"findings": [{**PLACE, "index": 0, "scheme": 1,
                                              "to": "G14|abbreviation-unused|MESO@supplement|-"}]}}
    result = tool.gate(with_ledger(corpus, absent), "tied", "new")
    assert lost(result)[0] == ("G14/abbreviation-unused", 0) and result["moved"] == []
    assert tool.measure(corpus, "new")["decisions"][0]["moved"] == 0


def test_a_move_of_a_mistyped_place_moves_nothing(corpus: Path) -> None:
    wrong = {**MOVE, "moved": {"findings": [{**PLACE, "index": 5, "to": K_MAIN, "scheme": 1}]}}
    assert lost(tool.gate(with_ledger(corpus, wrong), "tied", "new"))[0] == (
        "G14/abbreviation-unused", 0)
    assert tool.measure(corpus, "new")["decisions"][0]["matched"] == 0


def test_a_finding_still_there_is_not_moved(corpus: Path) -> None:
    write_run(corpus, "new", [TIED[0], MOVED_FINDING, *NEW[1:]])
    result = tool.gate(with_ledger(corpus, MOVE), "tied", "new")
    assert result["moved"] == []
    assert result["unjudged"]["G14/abbreviation-unused"]["new"] == 1


def test_a_run_with_no_keys_moves_nothing(corpus: Path) -> None:
    write_run(corpus, "plain", [{k: v for k, v in f.items() if k != "key"} for f in NEW])
    rows = tool.measure(with_ledger(corpus, MOVE), "plain")["findings"]
    assert next(r["moved_by"] for r in rows if r["index"] == 0) == ""


def test_a_finding_another_judged_one_took_carries_no_move(corpus: Path) -> None:
    # The judged spelling finding takes its key; a move onto that key moves nothing.
    onto = {**MOVE, "moved": {"findings": [{**PLACE, "index": 0, "to": K_SPELL, "scheme": 1}]}}
    rows = tool.measure(with_ledger(corpus, onto), "new")["findings"]
    assert next(r["state"] for r in rows if r["index"] == 0) == "gone"


# --- the rules broken -------------------------------------------------------------------


def _accepted_ignored(decisions):
    return {}


def _moves_ignored(decisions, run):
    return {}


def _moves_across_schemes(decisions, run):
    return {place: (d.id, to) for d in decisions for place, (to, _scheme) in d.moves.items()}


@pytest.mark.parametrize(("name", "broken", "check"), [
    ("_accepted_by", _accepted_ignored, check_accepted),
    ("_moves", _moves_ignored, check_moved),
    ("_moves", _moves_across_schemes, check_other_scheme),
])  # fmt: skip
def test_each_rule_broken_fails_its_check(corpus: Path, monkeypatch, name: str, broken,
                                          check) -> None:  # fmt: skip
    monkeypatch.setattr(tool, name, broken)
    with pytest.raises(AssertionError):
        check(corpus)


# --- the ledger as written --------------------------------------------------------------

HEAD = {"id": "x", "date": "d", "by": "b", "what": "w", "source": "s"}
ONE = {**PLACE, "index": 0}


@pytest.mark.parametrize(("body", "says"), [
    ({"accepted": {"findings": [ONE]}, "moved": {"findings": []}},
     "one of rejudge, successor, accepted or moved"),
    ({"accepted": {"findings": [ONE], "match": [{"code": "c"}]}}, "accepted holds findings"),
    ({"accepted": [ONE]}, "accepted holds findings"),
    ({"accepted": {"findings": []}}, "accepted names no finding"),
    ({"accepted": {"findings": [{"slug": "paper-a", "index": 0}]}},
     "named by slug, report and index"),
    ({"accepted": {"findings": [{**ONE, "verdict": "true"}]}}, "named by slug, report and index"),
    ({"accepted": {"findings": [ONE, ONE]}}, "names paper-a audit-pdf 0 twice"),
    ({"accepted": {"findings": [{**ONE, "index": "two"}]}}, "index is a number"),
    ({"moved": {"findings": [ONE]}}, "with the key that carries it now (`to`)"),
    ({"moved": {"findings": [{**ONE, "to": K_MAIN}]}}, "and that key's scheme (`scheme`)"),
    ({"moved": {"findings": [{**ONE, "to": K_MAIN, "scheme": 1, "why": "w"}]}}, "(`to`)"),
    ({"moved": {"findings": [{**ONE, "to": "G14/abbreviation-unused", "scheme": 1}]}},
     "`to` is a finding's key, gate|code|subject|digest"),
    ({"moved": {"findings": [{**ONE, "to": "|x|MESO@main|-", "scheme": 1}]}}, "`to` is a"),
    ({"moved": {"findings": [{**ONE, "to": K_MAIN, "scheme": "two"}]}},
     "`scheme` is a whole number from 1"),
    ({"moved": {"findings": [{**ONE, "to": K_MAIN, "scheme": True}]}}, "`scheme` is a whole"),
    ({"moved": {"findings": [{**ONE, "to": K_MAIN, "scheme": 0}]}}, "`scheme` is a whole"),
    ({"moved": {"findings": []}}, "moved names no finding"),
    ({"moved": {"findings": [ONE], "scope": "paper"}}, "moved holds findings"),
    ({"moved": {"findings": [{**ONE, "to": K_MAIN, "scheme": 1}, {**ONE, "to": K_SPELL,
                                                                  "scheme": 1}]}},
     "names paper-a audit-pdf 0 twice"),
    ({"moved": {"findings": [{**ONE, "batch": "../b", "to": K_MAIN, "scheme": 1}]}},
     "a batch is named by its name"),
])  # fmt: skip
def test_a_malformed_accepted_or_moved_decision_is_refused(corpus: Path, body: dict,
                                                           says: str) -> None:  # fmt: skip
    with pytest.raises(tool.CorpusError, match=re.escape(says)):
        tool.measure(with_ledger(corpus, {**HEAD, **body}), "new")


@pytest.mark.parametrize("field", ["id", "date", "by", "what", "source"])
def test_an_accepted_or_moved_decision_needs_who_when_what_and_why(corpus: Path,
                                                                   field: str) -> None:  # fmt: skip
    for decision in (ACCEPT, MOVE):
        with pytest.raises(tool.CorpusError, match=f"`{field}` is missing"):
            tool.measure(with_ledger(corpus, {k: v for k, v in decision.items() if k != field}),
                         "new")
