"""Render-and-read parity: anything a reader sees, a gate has read.

This harness exists because one bug family has produced five separate holes, and every one
of them was invisible to the whole test suite:

    front matter masked whole            the title and abstract went unread
    citation brackets masked whole       "[@key, ROR 9.99]" printed 9.99, unread
    fenced blocks masked                 a number in a listing printed, unread
    a closing fence longer than its opener   swallowed a whole paragraph of prose
    front matter *generated* by the build    subtitle and keywords never reached a gate

Each was found by a person, late, and each was fixed as a special case. None could have been
caught by the tests that existed, because those tests all asked "does the classifier handle
this string?" — never "does the document contain a number nobody looked at?"

So this asks the second question directly. For each case: render the manuscript with pandoc,
confirm the fabricated number **actually reaches the reader**, and require `check` to have
reported it. The first half is what stops the test being vacuous — a case that fails to
render proves nothing, and would otherwise quietly become a passing test that guards air.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from manuscript_guard.build import OFFLINE, assemble, build_document
from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.text.docx import read_docx

PANDOC = shutil.which("pandoc") is not None
pytestmark = pytest.mark.skipif(not PANDOC, reason="pandoc is not installed")

FENCE = "`" * 3
LONGER = "`" * 4

# A number that appears nowhere in the example's results, so any sighting of it in the
# rendered document is a fabrication that reached the reader.
FAKE = "9.99"


@dataclass(frozen=True)
class Route:
    """One way a number might reach the page without being read."""

    name: str
    body: str
    paper_yaml: dict | None = None


ROUTES = [
    Route("plain prose", f"\n\nThe reporting odds ratio was {FAKE} overall.\n"),
    Route(
        "citation suffix",
        f"\n\nShown [@fictionalClassSignal2019, which reported {FAKE}] here.\n",
    ),
    Route("inline code", f"\n\nThe reporting odds ratio was `{FAKE}`.\n"),
    Route("hand-written table", f"\n\n| Outcome | ROR |\n|---|---|\n| Hepatic | {FAKE} |\n"),
    Route(
        "fenced block, string literal",
        f"\n\n{FENCE}python\nprint(\"ROR {FAKE}\")\n{FENCE}\n",
    ),
    Route(
        "closing fence longer than its opener",
        f"\n\n{FENCE}python\nx = 1\n{LONGER}\n\nThe reporting odds ratio was {FAKE} overall.\n\n"
        f"{FENCE}python\ny = 2\n{FENCE}\n",
    ),
    Route(
        "raw openxml block",
        f"\n\n{FENCE}{{=openxml}}\n<w:p><w:r><w:t>The odds ratio was {FAKE}.</w:t></w:r></w:p>\n"
        f"{FENCE}\n",
    ),
    Route("front matter generated from paper.yaml", "\n", {"short_title": f"A {FAKE}-fold excess"}),
]


def render(project: Path) -> str:
    """Build the .docx the way `build --offline` does, and read back what it says."""
    loaded, _report = load_project(project)
    namespace, results, _literature, _r = load_namespace(loaded)
    assembled, _ = assemble(loaded, namespace, results)
    built = build_document(loaded, assembled, mode=OFFLINE)
    return read_docx(built.output)


def findings(project: Path) -> list:
    from manuscript_guard.cli import _run_gates

    report, _project, _stage, _deferred = _run_gates(project, stage="drafting")
    return list(report.findings)


@pytest.mark.parametrize("route", ROUTES, ids=lambda r: r.name)
def test_a_number_that_reaches_the_reader_has_been_read(project: Path, route: Route) -> None:
    if route.paper_yaml:
        import yaml

        path = project / "paper.yaml"
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        document.update(route.paper_yaml)
        path.write_text(
            yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )

    main = project / "manuscript" / "main.md"
    main.write_text(main.read_text(encoding="utf-8") + route.body, encoding="utf-8", newline="\n")

    # Half one: it really does render. Without this the case guards nothing.
    rendered = render(project)
    assert FAKE in rendered, (
        f"{route.name}: the fabricated number does not reach the document, so this case "
        f"proves nothing. Fix the case, do not delete the assertion."
    )

    # Half two: some gate said so.
    reported = [f for f in findings(project) if FAKE in (f.message or "") + (f.context or "")]
    assert reported, (
        f"{route.name}: {FAKE!r} is printed in the built document and no gate reported it. "
        f"That is the whole failure this harness exists to catch."
    )


def test_the_example_itself_has_no_unread_numbers(project: Path) -> None:
    """The worked example must not itself contain a number nobody looked at.

    Weaker than the routes above — it cannot know which numbers are bound — but it pins the
    fixture: if a future change starts hiding the example's own values from G2, the counts
    move and this notices.
    """
    from manuscript_guard.cli import _run_gates

    report, _project, _stage, _deferred = _run_gates(project, stage="drafting")
    assert report.ok, report.render(project)
    assert report.counts["numeric_atoms"] > 10, "G2 is reading far less than it used to"
    assert report.counts["bindings"] > 20
