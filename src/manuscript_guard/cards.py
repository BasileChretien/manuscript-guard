"""Each model the analysis fitted as its card, with what G15 says of it: what `models` prints,
and what a package holds as MODELS.md.

The card is what a co-author reads to say whether the model is the right one: what it is
called, what the author says it is for, the sentence made from the fit, and each variable
with the kind it was declared and how it entered. One function writes it for both, so that
the package's copy is the command's word for word.
"""

from __future__ import annotations

import re

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import Report


def model_cards(project: Project, results: Results) -> tuple[list[str], Report]:
    """The lines `models` prints, and what G15 says, whose failures set its exit code."""
    from manuscript_guard.contracts.models import describe, table_rows
    from manuscript_guard.gates.models import check_models

    report = check_models(project, results)
    lines: list[str] = []
    for key, model in results.models.items():
        lines.append(f"{model.name}  (model.{key}, {model.source.name})")
        lines.append(f"  fitted:      {model.kind or 'a model the toolkit has no name for'}")
        lines.append(f"  formula:     {model.formula}")
        lines.append(f"  from fit:    {describe(model, results.variables)}")
        lines.append(f"  author says: {model.description or '(nothing)'}")
        rows = [["Variable", "Declared as", "Entered as", "Levels"]]
        rows += table_rows(model, results.variables)
        widths = [max(len(row[i]) for row in rows) for i in range(4)]
        for row in rows:
            cells = zip(row, widths, strict=True)
            lines.append("    " + "  ".join(cell.ljust(width) for cell, width in cells))
        lines.append(f"  converged:   {'yes' if model.converged else 'NO'}")
        mine = [f for f in report.findings if f.message.startswith(f"model {key!r}:")]
        for finding in mine:
            lines.append(f"  [{finding.severity.upper()}] {finding.message.split(': ', 1)[1]}")
        lines.append("")
    # What G15 says of no one model, of a variable's data or of a name typed in the Methods,
    # counts in the exit code and so is printed.
    under_a_card = tuple(f"model {key!r}:" for key in results.models)
    for finding in report.findings:
        if not finding.message.startswith(under_a_card):
            where = f"{finding.path.name}:{finding.line}: " if finding.line else ""
            lines.append(f"[{finding.severity.upper()}] {where}{finding.message}")
    return lines, report


def models_text(project: Project, results: Results) -> str | None:
    """MODELS.md: the cards as `models` prints them, or None where no model was fitted."""
    if not results.models:
        return None
    lines, _report = model_cards(project, results)
    body = "\n".join(line.rstrip() for line in lines).strip("\n")
    # A fence longer than any run of backticks an author's words hold.
    fence = "`" * max([3, *(len(run) + 1 for run in re.findall("`+", body))])
    return (
        "# The models the analysis fitted\n\n"
        "Each model the results record, as `manuscript-guard models` prints it: its name, what "
        "was fitted, the sentence made from the fit, what the author says it is for, each "
        "variable with the kind it was declared and how it entered, and what the model check "
        "(G15) said of it when the package was made.\n\n"
        f"{fence}text\n{body}\n{fence}\n"
    )


__all__ = ["model_cards", "models_text"]
