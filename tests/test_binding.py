"""Getting a red number out of the red.

`check` says a number is unbound and the annotated copy colours it red. Neither says what to
type next, and usually the answer is that the value is already in `results/` and the author
typed it instead of binding it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from manuscript_guard.binding import SelectionError, apply, label, routes, select, unbound
from manuscript_guard.contracts import load_namespace, load_project


def loaded(root: Path):
    project, _ = load_project(root)
    namespace, _results, _lit, _r = load_namespace(project)
    return project, namespace


def test_a_clean_manuscript_has_nothing_to_bind(project: Path) -> None:
    assert unbound(*loaded(project)) == []


def test_a_typed_result_is_recognised_and_replaceable(project: Path) -> None:
    """The common case: the number is already published, and was typed instead of bound."""
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    typed_in = text.replace("{{results.ror.point}} (95% CI", "3.84 (95% CI", 1)
    path.write_text(typed_in, encoding="utf-8")
    items = unbound(*loaded(project))
    typed = [item for item in items if item.text == "3.84"]
    assert typed, "the typed literal must be reported"
    assert typed[0].certain == "results.ror.point"
    assert "replace it with {{results.ror.point}}" in routes(typed[0])[0]

    applied, remaining = apply(select(items, [], project))
    assert [binding for _item, binding in applied] == ["{{results.ror.point}}"]
    assert not remaining
    assert "{{results.ror.point}}" in path.read_text(encoding="utf-8")
    assert unbound(*loaded(project)) == []


def test_two_values_that_read_the_same_are_not_guessed_between(project: Path) -> None:
    """The collision case. Quietly picking the first would write the wrong binding into the
    manuscript, which is worse than leaving the number red."""
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    typed_in = text.replace("{{results.case.n_cases}} of these", "77 of these", 1)
    path.write_text(typed_in, encoding="utf-8")
    items = unbound(*loaded(project))
    typed = next(item for item in items if item.text == "77")
    assert len(typed.candidates) > 1
    assert typed.certain is None
    assert "Pick one by hand" in routes(typed)[0]

    applied, remaining = apply(select(items, [], project))
    assert applied == []
    assert remaining == [], "nothing was selected, so nothing is outstanding from the apply"
    assert "77 of these" in path.read_text(encoding="utf-8")


def test_a_number_nothing_published_gets_the_four_routes(project: Path) -> None:
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nA rate of 4.7 was noted.\n", encoding="utf-8"
    )
    item = next(i for i in unbound(*loaded(project)) if i.text == "4.7")
    assert item.certain is None and not item.candidates
    offered = " ".join(routes(item))
    for route in ("em.value", "ledger.yaml", "attested.yaml", "conventions:"):
        assert route in offered


def test_replacement_is_by_offset_not_by_text(project: Path) -> None:
    """"Replace 1 with a binding" would be a catastrophe done by search-and-replace, and a
    paper is full of 1s."""
    _project, namespace = loaded(project)
    shown = namespace["results.cohort.n_years"].display

    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("{{results.cohort.n_years}}", shown, 1)
    text += f"\n\nSee Table {shown} and item {shown}.\n"
    path.write_text(text, encoding="utf-8")

    items = unbound(*loaded(project))
    assert any(i.certain == "results.cohort.n_years" for i in items)
    apply(select(items, [], project))
    after = path.read_text(encoding="utf-8")
    assert f"See Table {shown} and item {shown}." in after, "the structural ones stay put"
    assert after.count("{{results.cohort.n_years}}") == 1


def test_a_separator_form_still_finds_its_value(project: Path) -> None:
    """A value displayed 41,200 and typed 41200 is the same number to an author."""
    from manuscript_guard.contracts.values import Value

    project_, namespace = loaded(project)
    namespace["results.big"] = Value(
        key="big", value=987654, display="987,654", origin="results", quoted=True
    )
    path = project / "manuscript" / "main.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\n\nAltogether 987654 records.\n", encoding="utf-8"
    )
    item = next(i for i in unbound(project_, namespace) if i.text == "987654")
    assert item.certain == "results.big"


# ---------------------------------------------------------------- accepting a subset


def _two_typed(project: Path) -> list:
    """Two literals, each matching exactly one published value, in one file."""
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("{{results.ror.point}} (95% CI", "3.84 (95% CI", 1)
    text = text.replace("{{results.cohort.n_drug_reports}}", "426", 1)
    path.write_text(text, encoding="utf-8")
    items = [i for i in unbound(*loaded(project)) if i.certain]
    assert {i.text for i in items} == {"3.84", "426"}, [i.text for i in items]
    return sorted(items, key=lambda i: i.start)


def test_one_suggestion_can_be_accepted_without_the_others(project: Path) -> None:
    """All-or-nothing meant a single wrong guess could only be avoided by declining every
    right one — and a suggestion is a guess from a matching value, never evidence."""
    items = _two_typed(project)
    first, second = items[0], items[1]

    applied, _rest = apply(select(items, [label(first, project)], project))
    assert [item.text for item, _b in applied] == [first.text]

    after = (project / "manuscript" / "main.md").read_text(encoding="utf-8")
    assert f"{{{{{first.certain}}}}}" in after
    assert second.text in after, "the suggestion nobody accepted is untouched"


def test_a_selector_that_names_nothing_is_an_error(project: Path) -> None:
    """Silently applying less than the author asked for is the divergence between intention
    and file that this command exists to close."""
    items = _two_typed(project)
    with pytest.raises(SelectionError, match="nothing to bind"):
        select(items, ["main.md:99999"], project)


def test_an_ambiguous_suggestion_cannot_be_selected(project: Path) -> None:
    """Naming it explicitly must not be a way to make the tool guess."""
    path = project / "manuscript" / "main.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("{{results.case.n_cases}} of these", "77 of these", 1), "utf-8")
    items = unbound(*loaded(project))
    ambiguous = next(i for i in items if i.text == "77")

    with pytest.raises(SelectionError, match="no single answer"):
        select(items, [label(ambiguous, project)], project)
    assert "77 of these" in path.read_text(encoding="utf-8")


def test_the_command_names_what_it_replaced(project: Path, capsys) -> None:
    """"replaced 7 literal(s)" says nothing about which seven, and each one rewrote a
    sentence on the strength of a guess."""
    from manuscript_guard.cli import main

    items = _two_typed(project)
    main(["bind", str(project), "--apply", "--only", label(items[0], project)])
    out = capsys.readouterr().out
    assert f"{items[0].text!r} -> {{{{{items[0].certain}}}}}" in out
    assert "replaced 1 literal(s)" in out


def test_the_command_refuses_an_unknown_selector(project: Path, capsys) -> None:
    from manuscript_guard.cli import main

    _two_typed(project)
    assert main(["bind", str(project), "--apply", "--only", "main.md:99999"]) == 2
    assert "nothing to bind" in capsys.readouterr().err
