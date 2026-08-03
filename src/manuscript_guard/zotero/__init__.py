"""Zotero access, via Better BibTeX's JSON-RPC endpoint."""

from manuscript_guard.zotero.citations import CitationUse, find_citations
from manuscript_guard.zotero.client import (
    Reference,
    ZoteroUnavailable,
    available,
    export,
    library,
    reset_cache,
    rpc,
)

__all__ = [
    "CitationUse",
    "Reference",
    "ZoteroUnavailable",
    "available",
    "export",
    "find_citations",
    "library",
    "reset_cache",
    "rpc",
]
