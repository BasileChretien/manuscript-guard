"""The contracts: the files a project must supply, and how they are read.

Everything else in the package depends on these and on nothing else, so a project that
validates here is guaranteed to be readable by every gate.
"""

from manuscript_guard.contracts._schema import ContractError, read_structured, validate
from manuscript_guard.contracts.literature import (
    ABSTRACT_ONLY,
    FULL_TEXT,
    USER_ATTESTED,
    Literature,
    load_literature,
)
from manuscript_guard.contracts.project import Project, find_root, load_project
from manuscript_guard.contracts.results import Fragment, Results, load_results
from manuscript_guard.contracts.values import ATTESTED, LITERATURE, RESULTS, Value

__all__ = [
    "ABSTRACT_ONLY",
    "ATTESTED",
    "FULL_TEXT",
    "LITERATURE",
    "RESULTS",
    "USER_ATTESTED",
    "ContractError",
    "Fragment",
    "Literature",
    "Project",
    "Results",
    "Value",
    "find_root",
    "load_literature",
    "load_project",
    "load_results",
    "read_structured",
    "validate",
]


def load_namespace(project: Project) -> tuple[dict[str, Value], Results, Literature, "object"]:
    """Load results and literature into the single `{{ns.key}}` lookup used by the engine."""
    from manuscript_guard.findings import merge_all

    results, results_report = load_results(project.path("results"))
    literature, literature_report = load_literature(project.path("literature"))

    namespace: dict[str, Value] = {}
    for key, value in results.values.items():
        namespace[f"results.{key}"] = value
    for key, value in literature.values.items():
        namespace[f"lit.{key}"] = value

    return namespace, results, literature, merge_all([results_report, literature_report])
