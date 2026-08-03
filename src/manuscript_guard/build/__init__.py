"""Producing documents from manuscript source.

Everything here is regeneration. The .docx is never edited and never patched; it is thrown
away and rebuilt, which is what makes a stale number impossible rather than merely
unlikely.
"""

from manuscript_guard.build.assemble import Assembled, assemble, find_figure, render_table
from manuscript_guard.build.document import (
    LIVE,
    OFFLINE,
    BuildError,
    BuildResult,
    build_document,
    ensure_zotero_lua,
)
from manuscript_guard.build.submission import (
    Pack,
    SubmissionError,
    assemble_pack,
    credit_statement,
    declarations,
    title_page,
)

__all__ = [
    "LIVE",
    "OFFLINE",
    "Assembled",
    "BuildError",
    "BuildResult",
    "Pack",
    "SubmissionError",
    "assemble",
    "assemble_pack",
    "build_document",
    "credit_statement",
    "declarations",
    "ensure_zotero_lua",
    "find_figure",
    "render_table",
    "title_page",
]
