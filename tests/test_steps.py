"""G9, pair by pair: a step of the code, and the Methods text that points at it.

The analysis marks a step (`with em.step("ci"):`) and the Methods end the text describing it
with `{{method.ci}}`, which prints nothing. The tests hold what that can and cannot say: that
the anchor names a step the run recorded, and that neither the step's code nor its text has
changed since a person last read the two together. Whether the text describes the code
correctly is the person's to say, and nothing here pretends to check it.
"""

from __future__ import annotations

import runpy
import shutil
import zipfile
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.emit import Emitter
from manuscript_guard.gates import check_methods, reconcile
from manuscript_guard.gates.methods import (
    anchor_lines,
    anchored,
    claims_in,
    explain_methods,
    lock_path,
)
from manuscript_guard.policy import BINDS_AT, INTERNAL_REVIEW
from manuscript_guard.text.placeholders import parse, substitute

PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")

SCRIPT = '''\
import math
from pathlib import Path

from manuscript_guard.emit import Emitter


def half(x):
    """Halves."""
    return x / 2


em = Emitter(__file__, root=Path(__file__).parent.parent)
a, b = 10, 20
with em.step("ror"):
    # the ratio
    ror = a / b
with em.step("ci"):
    se = half(math.sqrt(1 / a + 1 / b))
em.value("ror", ror, digits=2)
em.value("se", se, digits=3)
em.write()
'''

METHODS = (
    "# Methods\n\n"
    "The ratio was computed from two counts. {{method.ror}}\n\n"
    "Its standard error is half the usual one. {{method.ci}}\n\n"
    "Nothing in the code backs this paragraph.\n\n"
    "# Results\n\nThe ratio was {{results.ror}}.\n"
)


def make(root: Path, script: str = SCRIPT, methods: str = METHODS) -> Path:
    (root / "manuscript").mkdir(parents=True, exist_ok=True)
    (root / "analysis").mkdir(exist_ok=True)
    (root / "paper.yaml").write_text(
        'schema: manuscript-guard/paper/1\ntitle: "M"\nenglish_variant: en-GB\n', encoding="utf-8"
    )
    (root / "manuscript" / "main.md").write_text(methods, encoding="utf-8")
    run(root, script)
    return root


def run(root: Path, script: str) -> dict:
    path = root / "analysis" / "a.py"
    path.write_text(script, encoding="utf-8")
    runpy.run_path(str(path))
    fragment = yaml.safe_load((root / "results" / "a.json").read_text(encoding="utf-8"))
    return fragment.get("steps", {})


def judged(root: Path):
    project, _ = load_project(root)
    namespace, results, _literature, loaded = load_namespace(project)
    assert loaded.ok, loaded.render(root)
    return check_methods(project, namespace, results)


def codes(report) -> set[str]:
    return {f.code for f in report.findings}


def edit(root: Path, relative: str, was: str, now: str) -> None:
    path = root / relative
    text = path.read_text(encoding="utf-8")
    assert was in text, was
    path.write_text(text.replace(was, now, 1), encoding="utf-8")


# ------------------------------------------------------------------------ what a step records


def test_a_step_records_the_lines_of_its_block_and_a_digest_of_its_code(tmp_path: Path) -> None:
    steps = run(make(tmp_path), SCRIPT)
    assert set(steps) == {"ror", "ci"}
    assert steps["ror"]["lines"] == [16, 16], "the body, not the comment above it"
    assert steps["ci"]["lines"] == [18, 18]
    assert all(len(step["digest"]) == 64 for step in steps.values())


@pytest.mark.parametrize(
    ("was", "now"),
    [
        ("    # the ratio\n", "    # the ratio, as counts\n"),
        ("    ror = a / b\n", "    ror = (a /\n           b)\n"),
        ("    ror = a / b\n", "    ror = a / b  # a over b\n\n"),
        ('    """Halves."""\n', '    """Divides by two."""\n'),
    ],
    ids=["comment", "re-wrapped", "trailing comment", "docstring"],
)
def test_a_step_is_read_as_code_so_layout_and_comments_change_nothing(
    tmp_path: Path, was: str, now: str
) -> None:
    before = run(make(tmp_path), SCRIPT)
    after = run(tmp_path, SCRIPT.replace(was, now, 1))
    assert [s["digest"] for s in after.values()] == [s["digest"] for s in before.values()]


def test_a_change_to_the_code_of_a_step_changes_its_digest_and_no_other(tmp_path: Path) -> None:
    before = run(make(tmp_path), SCRIPT)
    after = run(tmp_path, SCRIPT.replace("ror = a / b", "ror = b / a"))
    assert after["ror"]["digest"] != before["ror"]["digest"]
    assert after["ci"]["digest"] == before["ci"]["digest"]


def test_a_function_of_the_script_a_step_calls_is_part_of_its_digest(tmp_path: Path) -> None:
    before = run(make(tmp_path), SCRIPT)
    assert before["ci"]["follows"] == ["half"], "a function of the script is followed"
    assert "follows" not in before["ror"], "math.sqrt is a package's, and is not followed"
    after = run(tmp_path, SCRIPT.replace("return x / 2", "return x / 3"))
    assert after["ci"]["digest"] != before["ci"]["digest"]


def test_a_function_is_followed_through_the_functions_it_calls(tmp_path: Path) -> None:
    script = SCRIPT.replace(
        '    """Halves."""\n    return x / 2\n',
        '    """Halves."""\n    return third(x) * 1.5\n\n\ndef third(x):\n    return x / 3\n',
    )
    steps = run(make(tmp_path, script), script)
    assert steps["ci"]["follows"] == ["half", "third"]


def test_a_step_in_a_branch_the_run_did_not_take_is_not_recorded(tmp_path: Path) -> None:
    script = SCRIPT.replace('with em.step("ci"):', 'if a > b:\n  with em.step("ci"):')
    script = script.replace('em.value("se", se, digits=3)\n', "")
    steps = run(make(tmp_path, script), script)
    assert set(steps) == {"ror"}


@pytest.mark.parametrize(
    "line",
    [
        'name = "ror"\nwith em.step(name):',
        'em.step("ror")\nif True:',
    ],
    ids=["name not written out", "not a with statement"],
)
def test_a_step_whose_block_cannot_be_read_is_refused(tmp_path: Path, line: str) -> None:
    script = SCRIPT.replace('with em.step("ror"):', line)
    make(tmp_path)
    with pytest.raises(ValueError, match="write the name out"):
        run(tmp_path, script)


def test_a_step_marked_where_there_is_no_script_says_that_is_why(tmp_path: Path) -> None:
    """A notebook cell and `python -c` are no file to read the block from. The refusal said
    to write the name out, which it was."""
    cell = compile(
        'with em.step("ci"):\n    pass\n', "<ipython-input-3-0123456789ab>", "exec"
    )
    with pytest.raises(ValueError, match="no file the block can be read from") as refused:
        exec(cell, {"em": Emitter(tmp_path / "a.py", root=tmp_path)})
    assert "write the name out" not in str(refused.value)


def test_one_name_for_two_blocks_is_refused_and_one_block_run_twice_is_not(
    tmp_path: Path,
) -> None:
    make(tmp_path)
    looped = SCRIPT.replace('with em.step("ror"):', 'for _ in range(3):\n  with em.step("ror"):')
    looped = looped.replace("    # the ratio\n    ror = a / b", "      ror = a / b")
    assert set(run(tmp_path, looped)) == {"ror", "ci"}
    twice = SCRIPT.replace('with em.step("ci"):', 'with em.step("ror"):')
    with pytest.raises(ValueError, match="marks two different blocks"):
        run(tmp_path, twice)


@pytest.mark.parametrize("name", ["CI", "1st", "a-b", "", "a..b"])
def test_a_step_name_the_methods_could_not_bind_is_refused(tmp_path: Path, name: str) -> None:
    em = Emitter(tmp_path / "a.py", root=tmp_path)
    with pytest.raises(ValueError, match="so that the Methods can bind it"):
        em.step(name)


def test_two_scripts_marking_one_step_are_refused_when_the_results_are_read(
    tmp_path: Path,
) -> None:
    make(tmp_path)
    other = tmp_path / "analysis" / "b.py"
    other.write_text(
        SCRIPT.replace("em.value", "pass  # em.value").replace(
            'with em.step("ci")', 'with em.step("ci2")'
        ),
        encoding="utf-8",
    )
    runpy.run_path(str(other))
    project, _ = load_project(tmp_path)
    _namespace, results, _literature, loaded = load_namespace(project)
    assert "duplicate-step" in codes(loaded)


# ------------------------------------------------------------------------- what a claim is


def test_an_anchor_claims_the_text_back_to_the_anchor_before_it(tmp_path: Path) -> None:
    text = "# Methods\n\nFirst we counted. {{method.a}} Then we divided. {{method.b}}\n"
    found, bare = claims_in(text)
    claimed = [(steps, text[start:end].strip()) for steps, start, end, _at in found]
    assert claimed == [(("a",), "First we counted."), (("b",), "Then we divided.")]
    assert bare == []


def test_anchors_side_by_side_claim_the_same_text(tmp_path: Path) -> None:
    text = "One sentence for both. {{method.a}} {{method.b}}\n"
    found, _ = claims_in(text)
    assert [(steps, text[s:e].strip()) for steps, s, e, _ in found] == [
        (("a", "b"), "One sentence for both.")
    ]


def test_a_claim_ends_at_a_blank_line_and_a_heading_and_not_at_a_comment(tmp_path: Path) -> None:
    text = (
        "An earlier paragraph.\n\n## Statistics\nThe first line\n<!-- a note -->\n"
        "and the second. {{method.a}}\n"
    )
    found, bare = claims_in(text)
    (steps, start, end, _at), = found
    assert " ".join(text[start:end].split()) == "The first line <!-- a note --> and the second."
    assert len(bare) == 1, "the earlier paragraph, which points at no step"
    project = make(tmp_path, methods="# Methods\n\n" + text)
    claims = [claim.text for claim in anchored(load_project(project)[0])[0]]
    assert claims == ["The first line and the second."], "the comment is not claimed"


def test_an_anchor_that_opens_its_paragraph_claims_nothing_and_fails(tmp_path: Path) -> None:
    root = make(tmp_path, methods=METHODS.replace(
        "Its standard error is half the usual one. {{method.ci}}",
        "{{method.ci}} Its standard error is half the usual one.",
    ))
    report = judged(root)
    assert "method-claim-empty" in {f.code for f in report.failures}


# ------------------------------------------------------------------------ the gate, unlocked


def test_without_a_lock_only_what_is_wrong_already_is_reported(tmp_path: Path) -> None:
    report = judged(make(tmp_path))
    assert codes(report) == {"methods-never-reconciled"}, report.render(tmp_path)
    assert report.counts["method_steps"] == 2
    assert report.counts["method_claims"] == 2
    assert report.counts["methods_open"] == 1


def test_an_anchor_naming_a_step_that_never_ran_fails(tmp_path: Path) -> None:
    root = make(tmp_path, methods=METHODS.replace("{{method.ci}}", "{{method.sensitivity}}"))
    report = judged(root)
    found = [f for f in report.failures if f.code == "method-step-unknown"]
    assert [f.line for f in found] == [5], report.render(tmp_path)
    assert "{{method.sensitivity}}" in found[0].message
    warned = [f for f in report.warnings if f.code == "method-step-undescribed"]
    assert [f.message for f in warned] == [
        "step 'ci' ran, and no text in the manuscript points at it"
    ]
    assert warned[0].line == 18


def test_an_anchor_is_no_value_binding(tmp_path: Path) -> None:
    from manuscript_guard.gates import check_numbers

    root = make(tmp_path)
    project, _ = load_project(root)
    namespace, results, literature, _ = load_namespace(project)
    report = check_numbers(project, namespace, results, literature)
    assert not {"unresolved-binding", "malformed-placeholder"} & codes(report)


def test_an_anchor_in_capitals_is_a_malformed_binding(tmp_path: Path) -> None:
    from manuscript_guard.gates import check_numbers

    root = make(tmp_path, methods=METHODS.replace("{{method.ci}}", "{{method.CI}}"))
    project, _ = load_project(root)
    namespace, results, literature, _ = load_namespace(project)
    assert "malformed-placeholder" in codes(check_numbers(project, namespace, results, literature))


def test_an_anchor_prints_nothing(tmp_path: Path) -> None:
    assert substitute("Counted. {{method.a}}", {}) == "Counted. "
    placeholders, malformed = parse("Counted. {{method.a.b}}")
    assert [p.is_anchor for p in placeholders] == [True] and not malformed


def test_a_project_with_no_steps_and_no_anchors_reads_as_before(tmp_path: Path) -> None:
    script = SCRIPT.replace('with em.step("ror"):', "if True:").replace(
        'with em.step("ci"):', "if True:"
    )
    root = make(tmp_path, script, METHODS.replace(" {{method.ror}}", "").replace(
        " {{method.ci}}", ""
    ))
    report = judged(root)
    assert not any(key.startswith("method") for key in report.counts), report.counts


# ---------------------------------------------------------------------- what an anchor prints


@pytest.mark.parametrize(
    ("written", "printed"),
    [
        ("A.\n{{method.a}}\nB. {{method.b}}\n", "A.\n\nB. \n"),
        ("A.\n{{method.a}} {{method.b}}\n\nB.\n", "A.\n \n\nB.\n"),
        ("A. {{method.a}}\nB.\n", "A. \nB.\n"),
        ("A.\n<!-- {{method.a}} -->\nB.\n", "A.\n<!-- {{method.a}} -->\nB.\n"),
    ],
    ids=["a line of its own", "ending the paragraph", "at the end of a line", "in a comment"],
)
def test_an_anchor_prints_nothing_and_leaves_its_line(written: str, printed: str) -> None:
    """A line of nothing but anchors prints as an empty line, which ends a paragraph:
    `check` warns of it where the source has none (`method-anchor-line`)."""
    assert substitute(written, {}) == printed


INSIDE = (
    "# Methods\n\n"
    "The ratio was computed from two counts.\n{{method.ror}}\n"
    "Its standard error is half the usual one.\n{{method.ci}}\n\n"
    "# Results\n\nThe ratio was {{results.ror}}.\n"
)


def _doors(root: Path) -> dict[str, str]:
    """`main.md` as each thing that prints it prints it: the build, the annotated copy,
    `render` and a review panel's prompt."""
    from manuscript_guard.annotate import annotate
    from manuscript_guard.build.assemble import assemble
    from manuscript_guard.classify import Classifier
    from manuscript_guard.panel.prompt import _as_read

    project, _ = load_project(root)
    namespace, results, _literature, _loaded = load_namespace(project)
    text = (root / "manuscript" / "main.md").read_text(encoding="utf-8")
    (built,), _report = assemble(project, namespace, results)
    assert main(["render", str(root)]) == 0
    return {
        "build": built.text,
        "annotated": annotate(text, namespace, Classifier.load(), counter=[0])[0],
        "render": (root / "build" / "rendered" / "main.md").read_text(encoding="utf-8"),
        "prompt": _as_read(text, namespace, results)[0] + "\n",
    }


def test_an_anchors_own_line_prints_as_an_empty_line_wherever_it_is_printed(
    tmp_path: Path,
) -> None:
    for door, printed in _doors(make(tmp_path, methods=INSIDE)).items():
        gap = printed[printed.index("two counts.") + 11 : printed.index("Its standard")]
        assert gap.replace(" ", "").replace("\t", "") == "\n\n", (door, gap)
        assert "{{method" not in printed, door


def _blocks_read(markdown: str) -> list:
    """The kinds of block pandoc reads in `markdown`."""
    import json
    import subprocess

    read = subprocess.run(
        [PANDOC, "-f", "markdown", "-t", "json"],
        input=markdown.encode("utf-8"),
        capture_output=True,
        check=True,
        timeout=120,
    )
    return [block["t"] for block in json.loads(read.stdout)["blocks"]]


@needs_pandoc
@pytest.mark.parametrize(
    ("written", "read"),
    [
        ("One.\n{{method.a}}\nTwo.\n", ["Para", "Para"]),
        ("One.\n{{method.a}}\n- two\n- three\n", ["Para", "BulletList"]),
        ("One.\n{{method.a}}\n| a | b |\n|---|---|\n| 1 | 2 |\n", ["Para", "Table"]),
        ("One.\n{{method.a}}\n## Two\n", ["Para", "Header"]),
    ],
    ids=["a sentence", "a list", "a pipe table", "a heading"],
)
def test_what_stands_under_an_anchors_own_line_prints_as_what_it_is(
    written: str, read: list[str]
) -> None:
    """The empty line ends the paragraph, so a list, a table or a heading under it is one in
    the document, and a sentence under it is a paragraph of its own. Nothing tells which was
    meant, and `check` warns of each."""
    assert _blocks_read(substitute(written, {})) == read
    assert anchor_lines(written) == [2]


# ------------------------------------------------------------------- an anchor's own line


@pytest.mark.parametrize(
    ("written", "warned"),
    [
        ("A.\n{{method.a}}\nB. {{method.b}}\n", [2]),
        ("A.\n{{method.a}}\n- b\n- c\n", [2]),
        ("A.\n \t{{method.a}} {{method.b}}\t \nB.\n", [2]),
        ("A.\r\n{{method.a}}\r\nB.\r\n", [2]),
        ("A.\n<!-- a note -->\n{{method.a}}\nB.\n", [3]),
        ("A.\n{{method.a}}\n## B\n", [2]),
        ("A.\n{{method.a}}\n{{method.b}}\nC.\n", [2]),
        ("A.\r\n{{method.a}}\r\n{{method.b}}\r\nC.\r\n", [2]),
        ("A.\n{{method.a}}\n{{method.b}}\n\nB.\n", []),
        ("A.\n{{method.a}}\n{{method.b}}\n{{method.c}}\n\nB.\n", []),
        ("A.\r\n{{method.a}}\r\n{{method.b}}\r\n\r\nB.\r\n", []),
        ("A.\n{{method.a}}\n{{method.b}}", []),
        ("A.\r\n{{method.a}}\r\n{{method.b}}", []),
        ("A.\n{{method.a}}\n\nB.\n", []),
        ("A.\n{{method.a}}\r\n\r\nB.\r\n", []),
        ("A.\n{{method.a}}", []),
        ("A.\n{{method.a}}\n", []),
        ("{{method.a}}\nA.\n", []),
        ("A.\n\n{{method.a}}\nB.\n", []),
        ("## A\n{{method.a}}\nB.\n", []),
        ("> A.\n> {{method.a}}\n> B.\n", []),
        ("- A.\n- {{method.a}}\n- B.\n", []),
        ("A.\n{{method.a}} <!-- a note -->\nB.\n", []),
        ("A.\n<!-- {{method.a}} -->\nB.\n", []),
        ("A. {{method.a}}\nB.\n", []),
        ("A.\n{{results.x}}\nB.\n", []),
    ],
    ids=[
        "inside a paragraph", "over a list", "two, with spaces", "ended as Windows does",
        "under a comment line", "over a heading", "two lines of them, once",
        "two lines of them, as Windows ends them", "two ending their paragraph, a line each",
        "three ending their paragraph", "two ending their paragraph, as Windows ends them",
        "two ending the file, not ended", "two ending the file, as Windows ends them",
        "ending its paragraph", "ending its paragraph, as Windows does", "the last line, not ended",
        "the last line", "the first line", "opening its paragraph", "under a heading",
        "behind a quotation's mark", "behind a list's mark", "beside a comment", "in a comment",
        "at the end of a line", "a value's own line",
    ],
)  # fmt: skip
def test_an_anchors_own_line_inside_a_paragraph_is_found(written: str, warned: list[int]) -> None:
    """Lines of nothing but anchors one under the other are one run, and the run is warned
    of once, at its first line, where the paragraph ends in the document. Anchors one to a
    line at the end of a paragraph end nothing it does not end already."""
    assert anchor_lines(written) == warned


def test_an_anchors_own_line_inside_a_paragraph_is_warned_at_every_stage(
    tmp_path: Path,
) -> None:
    report = judged(make(tmp_path, methods=INSIDE))
    found = [f for f in report.warnings if f.code == "method-anchor-line"]
    assert [f.line for f in found] == [4], report.render(tmp_path)
    assert "prints as an empty line" in found[0].message
    assert "end of the line above" in found[0].hint and "blank line" in found[0].hint
    assert "method-anchor-line" not in BINDS_AT, "a warning, whatever the stage"
    assert not [f for f in judged(make(tmp_path / "b")).findings if f.code == "method-anchor-line"]


# ------------------------------------------------------------------------ the gate, locked


def test_a_reconciled_project_is_quiet(tmp_path: Path) -> None:
    root = make(tmp_path)
    path, _ = reconcile(load_project(root)[0])
    pairs = yaml.safe_load(path.read_text(encoding="utf-8"))["pairs"]
    assert [(p["step"], p["claim"]) for p in pairs] == [
        ("ci", "Its standard error is half the usual one."),
        ("ror", "The ratio was computed from two counts."),
    ]
    report = judged(root)
    assert not report.findings, report.render(tmp_path)
    assert report.counts["method_pairs_stale"] == 0


def test_a_pair_never_read_fails_once_the_lock_exists(tmp_path: Path) -> None:
    root = make(tmp_path)
    reconcile(load_project(root)[0])
    edit(root, "manuscript/main.md", "Nothing in the code backs this paragraph.",
         "Nothing in the code backs this paragraph. {{method.ror}}")
    report = judged(root)
    found = [f for f in report.failures if f.code == "method-pair-unread"]
    assert [f.line for f in found] == [7], report.render(tmp_path)
    assert BINDS_AT["method-pair-unread"] == INTERNAL_REVIEW


def test_a_step_whose_code_changed_names_the_text_to_read_again(tmp_path: Path) -> None:
    root = make(tmp_path)
    reconcile(load_project(root)[0])
    run(root, SCRIPT.replace("ror = a / b", "ror = (a + 0.5) / (b + 0.5)"))
    report = judged(root)
    found = [f for f in report.failures if f.code == "method-step-changed"]
    assert len(found) == 1, report.render(tmp_path)
    assert "'ror'" in found[0].message and found[0].line == 3
    assert found[0].context == "The ratio was computed from two counts."
    assert "--reconcile ror" in found[0].hint
    assert "methods-drift" in codes(report), "the file changed too"


def test_a_comment_in_a_step_leaves_its_pair_read(tmp_path: Path) -> None:
    root = make(tmp_path)
    reconcile(load_project(root)[0])
    run(root, SCRIPT.replace("    # the ratio\n", "    # the ratio, a over b\n"))
    report = judged(root)
    assert not {"method-step-changed", "method-pair-unread"} & codes(report)
    assert "methods-drift" in codes(report), "the file is still another file"


def test_a_text_that_changed_says_what_it_was(tmp_path: Path) -> None:
    root = make(tmp_path)
    reconcile(load_project(root)[0])
    edit(root, "manuscript/main.md", "computed from two counts", "computed from three counts")
    report = judged(root)
    found = [f for f in report.failures if f.code == "method-claim-changed"]
    assert len(found) == 1, report.render(tmp_path)
    assert found[0].context == "was: The ratio was computed from two counts."


def test_a_text_re_wrapped_is_the_same_text(tmp_path: Path) -> None:
    root = make(tmp_path)
    reconcile(load_project(root)[0])
    edit(root, "manuscript/main.md", "computed from two counts.",
         "computed\nfrom   two\tcounts.")
    assert not judged(root).findings


def test_reconciling_one_step_records_its_pairs_and_leaves_the_rest(tmp_path: Path) -> None:
    root = make(tmp_path)
    project = load_project(root)[0]
    reconcile(project)
    before = yaml.safe_load(lock_path(project).read_text(encoding="utf-8"))
    edit(root, "manuscript/main.md", "computed from two counts", "computed from three counts")
    edit(root, "manuscript/main.md", "half the usual one", "a half of the usual one")
    run(root, SCRIPT.replace("ror = a / b", "ror = b / a"))
    path, count = reconcile(project, steps=["ror"])
    after = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert count == 1
    assert after["analysis"] == before["analysis"], "the files were not read again"
    assert after["reconciled_on"] == before["reconciled_on"]
    ci = [p for p in after["pairs"] if p["step"] == "ci"]
    assert ci == [p for p in before["pairs"] if p["step"] == "ci"]
    report = judged(root)
    assert {f.code for f in report.failures} == {"methods-drift", "method-claim-changed"}
    assert [f.line for f in report.failures if f.code == "method-claim-changed"] == [5]


def test_reconciling_a_step_no_text_points_at_is_refused(tmp_path: Path) -> None:
    root = make(tmp_path)
    with pytest.raises(ValueError, match="no text points at a step named 'sensitivity'"):
        reconcile(load_project(root)[0], steps=["sensitivity"])
    assert main(["methods", str(root), "--reconcile", "sensitivity"]) == 2


def test_the_command_reconciles_one_step(tmp_path: Path, capsys) -> None:
    root = make(tmp_path)
    assert main(["methods", str(root), "--reconcile"]) == 0
    edit(root, "manuscript/main.md", "computed from two counts", "computed from three counts")
    assert main(["methods", str(root)]) == 1
    assert main(["methods", str(root), "--reconcile", "ror"]) == 0
    assert "recorded 1 pair(s) of step ror" in capsys.readouterr().out
    assert main(["methods", str(root)]) == 0


def _one_step_first(root: Path) -> Path:
    """A project nobody has reconciled, in which one step is read against its text first."""
    make(root)
    assert not lock_path(load_project(root)[0]).exists()
    assert main(["methods", str(root), "--reconcile", "ror"]) == 0
    return root


def test_one_step_reconciled_first_is_a_lock_for_the_pairs(tmp_path: Path, capsys) -> None:
    """The lock then holds one pair and no file. It was taken for no lock at all, and every
    pair was passed over: the step's code could change and nothing but the warning said so."""
    root = _one_step_first(tmp_path)
    assert "recorded 1 pair(s) of step ror" in capsys.readouterr().out
    project = load_project(root)[0]
    lock = yaml.safe_load(lock_path(project).read_text(encoding="utf-8"))
    assert [pair["step"] for pair in lock["pairs"]] == ["ror"] and lock["analysis"] == {}
    assert "reconciled_on" not in lock, "no file was read against the Methods, on any day"
    report = judged(root)
    assert [(f.code, f.line) for f in report.failures] == [("method-pair-unread", 5)]
    assert [f.code for f in report.warnings] == ["methods-never-reconciled"]
    assert report.counts["method_pairs_stale"] == 1
    said = "\n".join(explain_methods(project))
    assert "read          manuscript/main.md:3  step ror" in said
    assert "never read    manuscript/main.md:5  step ci" in said
    # The files are read next, and the pair already recorded is recorded again with the rest.
    assert main(["methods", str(root), "--reconcile"]) == 0
    assert not judged(root).findings
    assert "reconciled_on" in yaml.safe_load(lock_path(project).read_text(encoding="utf-8"))


def test_a_step_reconciled_first_is_held_to_its_code(tmp_path: Path) -> None:
    root = _one_step_first(tmp_path)
    run(root, SCRIPT.replace("ror = a / b", "ror = b / a"))
    report = judged(root)
    assert [(f.code, f.line) for f in report.failures] == [
        ("method-step-changed", 3),
        ("method-pair-unread", 5),
    ], report.render(tmp_path)
    assert [f.code for f in report.warnings] == ["methods-never-reconciled"], "once, of the files"


def test_a_step_reconciled_first_is_held_to_its_text(tmp_path: Path) -> None:
    root = _one_step_first(tmp_path)
    edit(root, "manuscript/main.md", "computed from two counts", "computed from three counts")
    report = judged(root)
    found = [f for f in report.failures if f.code == "method-claim-changed"]
    assert [f.context for f in found] == ["was: The ratio was computed from two counts."]
    assert codes(report) == {
        "method-claim-changed", "method-pair-unread", "methods-never-reconciled"
    }  # fmt: skip


def test_a_project_given_for_a_step_is_refused_and_says_where_it_goes(
    tmp_path: Path, capsys
) -> None:
    """`methods --reconcile <project>` reconciled that project before steps had names. It is
    read as a step's name now, and the refusal was for whatever folder the command ran in."""
    root = make(tmp_path)
    assert main(["methods", "--reconcile", str(root)]) == 2
    said = capsys.readouterr().err
    assert "takes the names of steps" in said and f"methods {root} --reconcile" in said
    assert not lock_path(load_project(root)[0]).exists()


def test_explain_lists_every_claim_what_backs_it_and_what_nothing_backs(
    tmp_path: Path, capsys
) -> None:
    root = make(tmp_path, methods=METHODS.replace("{{method.ci}}", "{{method.ci2}}"))
    reconcile(load_project(root)[0])
    edit(root, "manuscript/main.md", "computed from two counts", "computed from three counts")
    lines = explain_methods(load_project(root)[0])
    text = "\n".join(lines)
    assert "text changed  manuscript/main.md:3  step ror  analysis/a.py:16" in text
    assert "was: The ratio was computed from two counts." in text
    assert "no such step  manuscript/main.md:5  step ci2  no step of that name ran" in text
    assert "open          manuscript/main.md:7  no step points here" in text
    assert "undescribed   step ci  analysis/a.py:18  no text points at it" in text
    assert lines[-1] == (
        "2 pair(s): 1 text changed, 1 no such step; 1 Methods paragraph(s) point at no step; "
        "1 step(s) described by nothing."
    )
    assert main(["methods", str(root), "--explain"]) == 0
    assert capsys.readouterr().out.splitlines() == lines


# ------------------------------------------------------------------------ the Word round trip


def test_an_anchor_ending_its_paragraph_is_set_aside_and_one_inside_it_is_not() -> None:
    from manuscript_guard.roundtrip import anchors_apart

    assert anchors_apart("Counted. {{method.a}}") == ("Counted.", " {{method.a}}")
    assert anchors_apart("Counted. {{method.a}}\n{{method.b}} ") == (
        "Counted.",
        " {{method.a}}\n{{method.b}} ",
    )
    assert anchors_apart("Counted. {{method.a}} Divided.") is None
    assert anchors_apart("No anchor, {{results.x}}.") == ("No anchor, {{results.x}}.", "")
    assert anchors_apart("A note. <!-- {{method.a}} -->") == ("A note. <!-- {{method.a}} -->", "")


def _source(tmp_path: Path, paragraph: str) -> dict:
    path = tmp_path / "main.md"
    text = f"# Methods\n\n{paragraph}\n"
    path.write_text(text, encoding="utf-8")
    return {"m": (path, paragraph, text.index(paragraph))}


def test_a_reworded_paragraph_keeps_the_anchor_that_ends_it(tmp_path: Path) -> None:
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    source = "The ratio was computed from two counts. {{method.ror}}"
    was, now = "The ratio was computed from two counts.", "We divided one count by the other."
    known = _source(tmp_path, source)
    heading = Block((), "Methods", role="heading")
    plan = plan_import(known, [heading, Block(("m",), was)], [heading, Block(("m",), now)])
    assert not plan.refused, plan.refused
    assert plan.merged["m"] == "We divided one count by the other. {{method.ror}}"


def test_a_reworded_paragraph_with_an_anchor_inside_it_is_refused_and_says_why(
    tmp_path: Path,
) -> None:
    from manuscript_guard.docxtext import Block
    from manuscript_guard.merge import plan_import

    source = "First we counted. {{method.a}} Then we divided. {{method.b}}"
    was = "First we counted. Then we divided."
    now = "First we counted the reports. Then we divided."
    known = _source(tmp_path, source)
    heading = Block((), "Methods", role="heading")
    plan = plan_import(known, [heading, Block(("m",), was)], [heading, Block(("m",), now)])
    assert not plan.merged
    (refusal,) = plan.refused
    assert "Methods anchor" in refusal.why[0] and "Make the edit in the .md" in refusal.why[0]


ENDS = "signal-detection practice. {{method.ror}} {{method.ci}}"


def _reworded_in_word(document: Path, returned: Path, was: str, now: str) -> None:
    """A copy of `document` in which a co-author typed `now` over `was`."""
    with zipfile.ZipFile(document) as zin, zipfile.ZipFile(returned, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                assert was in xml and "{{method" not in xml
                data = xml.replace(was, now, 1).encode("utf-8")
            zout.writestr(item, data)


@needs_pandoc
@pytest.mark.parametrize(
    "ends",
    [ENDS, ENDS.replace(". {{", ".\n{{"), ENDS.replace(". {{", ".\n{{").replace("}} {{", "}}\n{{")],
    ids=["on its last line", "on a line of their own", "on a line each"],
)
def test_an_edit_in_word_comes_back_with_the_anchor_and_the_binding(
    project: Path, tmp_path: Path, ends: str
) -> None:
    """The example's paragraph on the estimate and its intervals holds a binding and ends
    with two anchors. A co-author's rewording in Word comes back into it with all three
    where they were, on whichever lines the anchors stand."""
    source = project / "manuscript" / "main.md"
    source.write_bytes(source.read_bytes().replace(ENDS.encode(), ends.encode()))
    assert main(["build", str(project), "--offline"]) == 0
    returned = tmp_path / "returned.docx"
    _reworded_in_word(
        project / "build" / "manuscript.docx",
        returned,
        "Confidence intervals were derived",
        "Intervals were derived",
    )
    assert main(["import", str(returned), str(project), "--apply"]) == 0
    text = source.read_text(encoding="utf-8")
    assert "Intervals were derived from the standard error" in text
    paragraph = text[text.index("Intervals were derived") :].split("\n\n")[0]
    assert "{{results.param.alpha}}" in paragraph
    assert paragraph.rstrip().endswith(ends)
