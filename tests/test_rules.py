"""Every classifier rule, tested in both directions — and a build failure if one is not.

This file is a response to a specific, repeated failure. Six shipped rules have had to be
corrected for the same mistake: matching a *shape* rather than naming specific *values*, and
so absorbing a real measurement.

    rate-denominator        `per \\d[\\d\\s,]*`        took "12 per 83,214 patients treated"
    age-band                unit optional            took "enrolled 500+ patients"
    categorical-label       `arm|cohort … \\d+`       took "the exposed arm 47 hepatic events"
    time-label              `years? … \\d+`           took "over the study years 1204 reports"
    author-year-citation    a whole parenthetical    took "(Smith 2019, n = 412)"
    software-version        "3+ components"          took "95% CI 2.10-7.02"

Every one was found by a person reading the regex. None was found by a test, because each
rule only ever had cases proving what it *accepts*. The last one was introduced by the commit
that fixed the fifth, while its message claimed the mistake had been caught.

So the discipline is enforced here rather than remembered: `test_every_rule_declares_what_it_
must_not_absorb` fails if any shipped rule has no `rejects` case. A new rule cannot reach
main without someone writing down, in `tests/data/rule_cases.yaml`, a real measurement it
must leave alone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.text.masking import mask
from manuscript_guard.text.tokens import find_atoms

DATA = Path(__file__).parent.parent / "src" / "manuscript_guard" / "data"
CASES = yaml.safe_load((Path(__file__).parent / "data" / "rule_cases.yaml").read_text("utf-8"))

SECTIONS = {"conventions": "conventions", "structural": "structural"}


def shipped_rules() -> dict[str, dict]:
    """Every rule id in the shipped tables, with its own spec."""
    out: dict[str, dict] = {}
    for filename, key in (("conventions.yaml", "conventions"), ("structural.yaml", "structural")):
        document = yaml.safe_load((DATA / filename).read_text(encoding="utf-8"))
        for item in document[key]:
            out[item["id"]] = {**item, "_table": key}
    return out


def declared_cases() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for table in ("conventions", "structural"):
        for rule_id, spec in (CASES.get(table) or {}).items():
            out[rule_id] = {**spec, "_table": table}
    return out


RULES = shipped_rules()
DECLARED = declared_cases()


def classify(text: str, atom_text: str, *, rule: dict):
    classifier = Classifier.load(rendered=bool(rule.get("audit_only")))
    section = tuple(rule.get("section") or ()) or None
    found = [a for a in find_atoms(text, mask(text)) if a.text == atom_text]
    assert found, f"no atom {atom_text!r} in {text!r} — the case itself is wrong"
    return classifier.classify(found[0], section)


# ---------------------------------------------------------------- the meta-test


def test_every_rule_declares_what_it_must_not_absorb() -> None:
    """The point of this whole file. Adding a rule without a negative case fails here."""
    missing_entirely = sorted(set(RULES) - set(DECLARED))
    assert not missing_entirely, (
        f"rules with no cases in tests/data/rule_cases.yaml: {missing_entirely}. "
        f"Every shipped rule needs both what it accepts and a real measurement it must not."
    )

    # A reject naming no atom tests the pattern's shape, not a measurement, so it does not
    # count: every rule needs one real number it must leave alone.
    without_rejects = sorted(
        rule_id
        for rule_id, spec in DECLARED.items()
        if not any(case.get("atom") is not None for case in spec.get("rejects") or [])
    )
    assert not without_rejects, (
        f"rules with no `rejects` case: {without_rejects}. Six rules have already had to be "
        f"corrected for absorbing a real number; a rule with no negative case is that mistake "
        f"waiting to happen again."
    )


def test_no_case_names_a_rule_that_no_longer_exists() -> None:
    """A renamed or deleted rule must not leave its cases quietly passing."""
    orphans = sorted(set(DECLARED) - set(RULES))
    assert not orphans, f"cases for rules that are not shipped: {orphans}"


# ---------------------------------------------------------------- the cases


def _flatten(kind: str):
    out = []
    for rule_id, spec in sorted(DECLARED.items()):
        for case in spec.get(kind) or []:
            if case.get("atom") is None:
                continue
            label = f"{rule_id}:{case['atom']}"
            out.append(pytest.param(rule_id, case["text"], case["atom"], id=label))
    return out


@pytest.mark.parametrize(("rule_id", "text", "atom"), _flatten("accepts"))
def test_a_rule_accepts_what_it_is_for(rule_id: str, text: str, atom: str) -> None:
    verdict = classify(text, atom, rule=DECLARED[rule_id])
    assert verdict.kind != UNCLASSIFIED, f"{atom!r} should classify"
    assert verdict.rule == rule_id, f"{atom!r} classified by {verdict.rule!r}, expected {rule_id!r}"


@pytest.mark.parametrize(("rule_id", "text", "atom"), _flatten("rejects"))
def test_a_rule_leaves_a_real_measurement_alone(rule_id: str, text: str, atom: str) -> None:
    """A number that is a claim must stay unclassified — by *any* rule, not just this one.

    Checked against the whole rule set rather than the one under test, because the failures
    that matter are exactly the ones where the wrong rule reaches out and takes a number.
    `2.10-7.02` was absorbed by `software-version`, which nobody would have thought to test.
    """
    verdict = classify(text, atom, rule=DECLARED[rule_id])
    assert verdict.kind == UNCLASSIFIED, (
        f"{atom!r} in {text!r} was absorbed by {verdict.rule!r} as {verdict.kind}. "
        f"It is a measurement and must be bound to a source."
    )


@pytest.mark.parametrize(
    ("text", "escapes"),
    [
        pytest.param(r"p \< 0.05 and ROR \> 2", [2, 18], id="escaped"),
        pytest.param(r"a \\> 3", [], id="a-backslash-printed-before-it"),
        pytest.param(r"a \\\> 3", [4], id="a-backslash-printed-then-an-escape"),
        pytest.param(r"`a \> 3` and \> 3", [13], id="printed-in-code"),
        pytest.param("```\na \\> 3\n```", [], id="printed-in-a-listing"),
        # A backtick after an odd run of backslashes is printed and opens no code span, as
        # `import` writes one typed in Word; inside code a backslash before the closing run
        # prints, and the run closes it.
        pytest.param(r"(\` ROR \> 2 \`)", [8], id="between-escaped-backticks"),
        pytest.param(r"\``a \> 3` and \> 3", [15], id="an-escaped-backtick-then-code"),
        pytest.param(r"x\\`a \> 3` y", [], id="a-backslash-printed-then-code"),
        pytest.param(r"`a\` \> 3", [5], id="a-backslash-printed-in-code-before-its-end"),
        pytest.param(r"`a` \` \> 1 `b`", [7], id="an-escaped-backtick-between-code"),
    ],
)
def test_only_a_backslash_that_prints_nothing_escapes_a_comparison(
    text: str, escapes: list[int]
) -> None:
    from manuscript_guard.text.masking import comparison_escapes

    assert comparison_escapes(text) == escapes


def _shapes(kind: str):
    """The cases that name no atom: a rule for a line with no number in it, such as a
    table's separator row, has none to classify. They used to be skipped, so the one such
    rule was never tested at all."""
    out = []
    for rule_id, spec in sorted(DECLARED.items()):
        for number, case in enumerate(spec.get(kind) or []):
            if case.get("atom") is None:
                out.append(pytest.param(rule_id, case["text"], id=f"{rule_id}:{number}"))
    return out


@pytest.mark.parametrize(("rule_id", "text"), _shapes("accepts"))
def test_a_rule_matches_the_shape_it_is_for(rule_id: str, text: str) -> None:
    pattern = re.compile(RULES[rule_id]["pattern"], re.MULTILINE)
    assert pattern.fullmatch(text), f"{rule_id} should match {text!r}"


@pytest.mark.parametrize(("rule_id", "text"), _shapes("rejects"))
def test_a_rule_does_not_match_what_it_is_not_for(rule_id: str, text: str) -> None:
    pattern = re.compile(RULES[rule_id]["pattern"], re.MULTILINE)
    found = pattern.search(text)
    assert found is None, f"{rule_id} matched {found.group()!r} in {text!r}"


# ------------------------------------------------------------- a TeX length, in LaTeX


def _latex_verdicts(text: str) -> dict[str, str]:
    """Each number of a LaTeX file as G2 judges it there, by the rule that lets it through."""
    from manuscript_guard.gates.numbers import _latex_read
    from manuscript_guard.text.latex.mask import read
    from manuscript_guard.text.latex.structure import Source
    from manuscript_guard.text.latex.views import File, bindings, markdown_view

    source = Source("main.tex", text, read(text))
    good, malformed = bindings(source)
    found = _latex_read(File(Path("main.tex"), source, tuple(good), tuple(malformed),
                             markdown_view(source, good)))  # fmt: skip
    classifier = Classifier.load()
    scan = found.scan(classifier)
    return {atom.text + "@" + str(atom.line): classifier.classify_under(
                atom, found.chains(atom.start), scan).rule or UNCLASSIFIED
            for atom in find_atoms(found.text, found.masked)}  # fmt: skip


def test_a_tex_length_in_a_definition_s_body_is_layout_and_in_the_text_a_number() -> None:
    """2601.04966's `\\def\\bibhang{24pt}` and 2412.11273's `\\lower.5ex` in the preamble were
    numbers bound to nothing (2026-10-23). A length in a unit TeX measures the page in, typed
    as TeX reads one, is layout in a definition's body; in the text it is a number like any
    other, since "24 pt" may be a font or points of a scale; and a length in millimetres,
    centimetres or inches may be the paper's own measure anywhere. So may one in TeX's big
    points, Cicero and picas, a paper's base pairs, cubic centimetres and parsecs, in a
    definition's body too (round 1 of #443)."""
    text = ("\\documentclass{article}\n\\def\\bibhang{24pt}%\n"
            "\\def\\simgt{\\lower.5ex\\hbox{$>$}}\n\\newcommand{\\back}{\\kern-3.5em}\n"
            "\\def\\jump{\\hskip 0.2in}\n\\newcommand{\\n}{4100}\n"
            "\\newcommand{\\frag}{500bp, 20cc and 8pc}\n\\begin{document}\n"
            "Set in 24pt type, a 24 pt font, fragments of 500bp and 12mu.\n"
            "\\end{document}\n")  # fmt: skip
    assert _latex_verdicts(text) == {
        "24pt@2": "tex-length", ".5ex@3": "tex-length", "-3.5em@4": "tex-length",
        "0.2in@5": UNCLASSIFIED, "4100@6": UNCLASSIFIED, "500bp@7": UNCLASSIFIED,
        "20cc@7": UNCLASSIFIED, "8pc@7": UNCLASSIFIED, "24pt@9": UNCLASSIFIED,
        "24@9": UNCLASSIFIED, "500bp@9": UNCLASSIFIED, "12mu@9": UNCLASSIFIED,
    }  # fmt: skip


@pytest.mark.parametrize("title", ["Results", "3. Results", "III. Results", "IV) Discussion"])
def test_a_part_that_reports_is_not_the_methods_however_it_is_numbered(title: str) -> None:
    """`NOT_METHODS_SECTIONS` took an Arabic number before the name but not a Roman one,
    as `METHODS_SECTIONS` does, so "III. Results" was not set aside (Known gaps, 11544)."""
    from manuscript_guard.classify import NOT_METHODS_SECTIONS

    assert NOT_METHODS_SECTIONS.match(title.lower())
