"""The gates.

Every gate is a pure function from loaded contracts to a `Report`. None of them prints,
exits, or reads configuration of its own, which is what lets the same code back the CLI, a
git hook and a CI job without any of the three disagreeing about the verdict.
"""

from manuscript_guard.gates.citations import check_citations, sync_bib
from manuscript_guard.gates.consistency import check_consistency
from manuscript_guard.gates.design import check_design
from manuscript_guard.gates.figure_review import check_figure_reviews, review_path
from manuscript_guard.gates.figure_source import check_figure_source
from manuscript_guard.gates.figures import check_figures, content_digest
from manuscript_guard.gates.freshness import check_freshness
from manuscript_guard.gates.journal import check_journal
from manuscript_guard.gates.literature import check_literature_chain
from manuscript_guard.gates.methods import check_methods, reconcile
from manuscript_guard.gates.numbers import check_numbers, source_files
from manuscript_guard.gates.reporting import (
    available_checklists,
    check_reporting,
    scaffold_completion,
)
from manuscript_guard.gates.review import (
    check_review,
    manuscript_digest,
    open_panel,
    panels,
)
from manuscript_guard.gates.revision import check_revision, rounds
from manuscript_guard.gates.writing import check_writing

GATES = {
    "G1": "results freshness",
    "G2": "number classification and coverage",
    "G3": "figure sources and rendered figures",
    "G4": "journal guidelines",
    "G5": "reporting checklist completeness",
    "G6": "signs of machine-written prose",
    "G7": "citation integrity",
    "G8": "cross-artefact consistency",
    "G9": "the Methods still describe the code",
    "G10": "figures have a current review",
    "G11": "the manuscript has been reviewed by a recorded panel",
    "G12": "there was an analysis plan before there was an analysis",
}

__all__ = [
    "check_revision",
    "rounds",
    "GATES",
    "check_citations",
    "check_consistency",
    "check_design",
    "check_figure_reviews",
    "check_figure_source",
    "check_figures",
    "available_checklists",
    "check_freshness",
    "check_journal",
    "check_literature_chain",
    "check_methods",
    "check_numbers",
    "reconcile",
    "check_reporting",
    "check_review",
    "check_writing",
    "manuscript_digest",
    "open_panel",
    "panels",
    "scaffold_completion",
    "content_digest",
    "review_path",
    "source_files",
    "sync_bib",
]
