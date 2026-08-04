"""Getting a red number out of the red.

`check` says a number is unbound and the annotated copy colours it red. Neither says what to
type next, and usually the answer is that the value is already in `results/` and the author
typed it instead of binding it.
"""

from __future__ import annotations

from pathlib import Path

from manuscript_guard.binding import apply, routes, unbound
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

    replaced, remaining = apply(items)
    assert replaced == 1
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

    replaced, remaining = apply(items)
    assert replaced == 0
    assert remaining == items, "an ambiguous literal is left exactly as it was"
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
    apply(items)
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
