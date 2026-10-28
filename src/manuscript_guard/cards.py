"""Each model the analysis fitted as its card, with what G15 says of it: what `models` prints,
and what a package holds as MODELS.md.

The card is what a co-author reads to say whether the model is the right one: what it is
called, what the author says it is for, the sentence made from the fit, and each variable
with the kind it was declared and how it entered. One function writes it for both, so that
the package's copy is the command's word for word.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import replace
from pathlib import Path

from manuscript_guard.contracts.project import Project
from manuscript_guard.contracts.results import Results
from manuscript_guard.findings import Report


def model_cards(project: Project, results: Results, *,
                cards_only: bool = False) -> tuple[list[str], Report]:  # fmt: skip
    """The lines `models` prints, and what G15 says, whose failures set its exit code. With
    `cards_only`, what G15 says under no card is left out: of the Methods' wording against
    the models fitted, and of a variable's data."""
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
    for finding in () if cards_only else report.findings:
        if not finding.message.startswith(under_a_card):
            where = f"{finding.path.name}:{finding.line}: " if finding.line else ""
            lines.append(f"[{finding.severity.upper()}] {where}{finding.message}")
    return lines, report


def _held(results: Results, root: Path, packaged: Collection[str]) -> Results:
    """The results with only the models of the fragments `packaged` names: a card of a
    fragment the package withholds would publish its counts, which no sign-off of the
    custodian's has read. The variables stay whole, so that a held model whose variable a
    withheld fragment declares is not read as entering one nobody declared: a card prints a
    variable's kind and levels, and none of its counts."""
    def kept(source: Path) -> bool:
        try:
            return source.relative_to(root).as_posix() in packaged
        except ValueError:
            return False

    return replace(results, models={k: m for k, m in results.models.items() if kept(m.source)})


def models_text(project: Project, results: Results,
                packaged: Collection[str] | None = None) -> str | None:  # fmt: skip
    """MODELS.md: the cards as `models` prints them, or None where no model was fitted. With
    `packaged`, the paths of the files a package holds, only the models of the results files
    it holds are printed, and how many were left out is said."""
    if not results.models:
        return None
    shown = results if packaged is None else _held(results, project.root, packaged)
    withheld = [m.source for k, m in results.models.items() if k not in shown.models]
    away = sorted({(p.relative_to(project.root) if p.is_relative_to(project.root) else
                    Path(p.name)).as_posix() for p in withheld})  # fmt: skip
    left = len(withheld)
    out = [
        "# The models the analysis fitted", "",
        "Each model the results of this package record, as `manuscript-guard models` prints "
        "it: its name, what was fitted, the sentence made from the fit, what the author says "
        "it is for, each variable with the kind it was declared and how it entered, and what "
        "the model check (G15) said of it when the package was made.", "",
    ]  # fmt: skip
    if left:
        out += [f"{left} model(s) left out: withheld with its results ("
                + ", ".join(f"`{path}`" for path in away) + ").", ""]  # fmt: skip
    if packaged is not None:
        # Held to the models of this package alone, G15's reading of the Methods would say
        # a model they name was fitted by none, where a withheld fragment holds it.
        out += ["What the model check says of the Methods' wording and of each variable's "
                "data is left out: `manuscript-guard check` says it of the whole project.", ""]
    if shown.models:
        lines, _report = model_cards(project, shown, cards_only=packaged is not None)
        body = "\n".join(line.rstrip() for line in lines).strip("\n")
        # A fence longer than any run of backticks an author's words hold.
        fence = "`" * max([3, *(len(run) + 1 for run in re.findall("`+", body))])
        out += [f"{fence}text", body, fence]
    return "\n".join(out).rstrip("\n") + "\n"


__all__ = ["model_cards", "models_text"]
