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

    without_rejects = sorted(
        rule_id for rule_id, spec in DECLARED.items() if not spec.get("rejects")
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
            out.append(pytest.param(rule_id, case["text"], case["atom"], id=f"{rule_id}:{case['atom']}"))
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
