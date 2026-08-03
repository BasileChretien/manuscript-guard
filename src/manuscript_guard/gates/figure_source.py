"""G3s — the same rules, applied to figure source code.

Checking rendered output alone leaves a hole that is easy to fall into and impossible to
see: a script that reads the results file *and also* types one annotation by hand passes
both the output check, because the typed number happens to equal the right value today,
and the script check, because the script does read the results. Tomorrow the analysis
changes and the annotation does not.

So the classifier runs over the script itself, with two rules:

* **Numbers inside string literals are judged exactly as prose.** A string in a figure
  script is usually text that will be drawn, so it gets the shipped conventions, structural
  patterns and terms — "95% CI" and "per 100 000 person-years" pass, a bare 3.42 does not.
* **Numbers in code are judged by their syntactic position.** A number sitting under a
  presentation parameter or inside a plotting call is layout; anything else is a candidate
  claim and has to be justified.

Escape hatches are per figure and written down: `<name>.guard.yaml` carries an
`allow_source` list, each entry with a reason.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from manuscript_guard.classify import UNCLASSIFIED, Classifier
from manuscript_guard.findings import Finding, Report
from manuscript_guard.text.code import CodeNumber, language_of, numbers_in
from manuscript_guard.text.masking import mask
from manuscript_guard.text.tokens import find_atoms

GATE = "G3"
DATA_DIR = Path(__file__).parent.parent / "data"

# Numeric content in a string that is plainly machinery rather than a claim.
_MACHINERY = re.compile(
    r"""
    %[-+ #0-9.]*[a-zA-Z]           # printf: %.2f, %05d
    | \{[^}]*:[^}]*\}              # format spec: {:.1f}, {value:>3}
    | \{\d+\}                      # positional format: {0}
    | \#[0-9a-fA-F]{3,8}\b         # colour: #1f77b4
    | \b\d+(?:\.\d+)?(?:px|pt|em|rem|in|cm|mm|%)\b   # CSS-ish length
    | \b[\w./\\-]+\.[a-z]{2,4}\b   # a filename or path
    | \bversion\s*[\d.]+           # a version string
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class PlotVocabulary:
    parameters: frozenset[str]
    function_patterns: tuple[re.Pattern[str], ...]
    data_constructors: frozenset[str]
    machinery_parameters: frozenset[str]
    tick_label_functions: frozenset[str]

    def machinery(self, names: tuple[str, ...]) -> bool:
        return any(name in self.machinery_parameters for name in names)

    def tick_label(self, names: tuple[str, ...]) -> bool:
        return any(
            name in self.tick_label_functions or name.split(".")[-1] in self.tick_label_functions
            for name in names
        )

    def presentation(self, names: tuple[str, ...]) -> str | None:
        for name in names:
            if name in self.parameters:
                return name
            for pattern in self.function_patterns:
                if pattern.search(name):
                    return name
        return None

    def data_constructor(self, names: tuple[str, ...]) -> str | None:
        for name in names:
            if name in self.data_constructors:
                return name
        return None


@lru_cache(maxsize=1)
def load_vocabulary() -> PlotVocabulary:
    document = yaml.safe_load((DATA_DIR / "plot_params.yaml").read_text(encoding="utf-8"))
    return PlotVocabulary(
        parameters=frozenset(document["parameters"]),
        function_patterns=tuple(re.compile(p) for p in document["function_patterns"]),
        data_constructors=frozenset(document["data_constructors"]),
        machinery_parameters=frozenset(document["machinery_parameters"]),
        tick_label_functions=frozenset(document["tick_label_functions"]),
    )


def source_allowlist(script: Path) -> dict[str, str]:
    """Declared exemptions for this script, from `<stem>.guard.yaml`."""
    sidecar = script.with_name(f"{script.stem}.guard.yaml")
    if not sidecar.exists():
        return {}
    document = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
    return {
        str(item["value"]): item.get("why", "")
        for item in document.get("allow_source", [])
        if "value" in item
    }


def check_figure_source(script: Path, classifier: Classifier) -> Report:
    language = language_of(script.suffix)
    if language is None:
        return Report()

    text = script.read_text(encoding="utf-8", errors="replace")
    vocabulary = load_vocabulary()
    declared = source_allowlist(script)
    report = Report()
    counts = {"checked": 0, "presentation": 0, "declared": 0, "string_ok": 0}

    for number in numbers_in(text, language):
        counts["checked"] += 1

        if number.text in declared:
            counts["declared"] += 1
            continue

        if number.in_string:
            if vocabulary.machinery(number.names) or vocabulary.tick_label(number.names):
                counts["string_ok"] += 1
                continue
            verdict = _judge_string_number(number, classifier)
            if verdict is None:
                counts["string_ok"] += 1
                continue
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-source-text-number",
                    message=f"{number.text!r} is written into text that the figure draws",
                    path=script,
                    line=number.line,
                    context=number.line_text.strip()[:160],
                    hint="read the value from the results file and format it into the "
                    "label, so the figure cannot disagree with the manuscript",
                )
            )
            continue

        constructor = vocabulary.data_constructor(number.names)
        if constructor is not None:
            report = report.with_findings(
                Finding(
                    gate=GATE,
                    code="figure-source-hardcoded-data",
                    message=f"{number.text!r} is data typed into {constructor}(…)",
                    path=script,
                    line=number.line,
                    context=number.line_text.strip()[:160],
                    hint="a figure script may read results/ and the raw data; it may not "
                    "contain the data",
                )
            )
            continue

        if vocabulary.presentation(number.names) is not None:
            counts["presentation"] += 1
            continue

        report = report.with_findings(
            Finding(
                gate=GATE,
                code="figure-source-unclassified-number",
                message=f"{number.text!r} is not obviously layout, and is bound to nothing",
                path=script,
                line=number.line,
                context=f"in {number.context}: {number.line_text.strip()[:120]}",
                hint=f"read it from the results file, or declare it in "
                f"{script.stem}.guard.yaml under allow_source with a reason",
            )
        )

    return report.with_counts(
        figure_source_numbers=counts["checked"],
        figure_source_presentation=counts["presentation"],
        figure_source_declared=counts["declared"],
    )


def _judge_string_number(number: CodeNumber, classifier: Classifier) -> str | None:
    """None when the number in this string is acceptable, otherwise the reason it is not.

    The string's content is run through the prose classifier, because a string in a figure
    script is usually an axis title, a legend entry or an annotation, and the rules that
    govern those in the manuscript should govern them here too.

    Everything here is decided by *position* in the line, never by matching the digit
    string. Matched by text, a line like

        ax.annotate("OR 3", xy=(1, 2))  # cf. Table 3 for the full comparison

    offered two candidates containing "3", and the trailing comment's "Table 3" classified
    as structural — which cleared the hardcoded annotation. Any unrelated digit anywhere on
    the line could excuse a real claim.
    """
    fragment = number.line_text
    if _MACHINERY.search(fragment):
        # Machinery may sit on the same line as a claim, so only forgive the exact span.
        for match in _MACHINERY.finditer(fragment):
            if match.start() <= number.col < match.end():
                return None
    covering = [
        a for a in find_atoms(fragment, mask(fragment)) if a.start <= number.col < a.end
    ]
    if not covering:
        # The literal sits inside something masking removed — a DOI, a URL, inline code.
        # Those are not claims, and reporting them is how a figure gate gets switched off.
        return None
    if all(classifier.classify(atom).kind == UNCLASSIFIED for atom in covering):
        return "unclassified"
    return None
