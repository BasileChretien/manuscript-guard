"""Zotero access, via Better BibTeX's JSON-RPC endpoint."""

from manuscript_guard.zotero.citations import CitationUse, find_citations
from manuscript_guard.zotero.client import (
    Lookup,
    Reference,
    ZoteroRefused,
    ZoteroUnavailable,
    available,
    export,
    library,
    lookup,
    reset_cache,
    rpc,
)

__all__ = [
    "CitationUse",
    "Lookup",
    "Reference",
    "ZoteroRefused",
    "ZoteroUnavailable",
    "available",
    "export",
    "find_citations",
    "library",
    "lookup",
    "reset_cache",
    "rpc",
]
