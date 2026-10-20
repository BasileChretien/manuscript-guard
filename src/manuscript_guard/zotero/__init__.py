"""Zotero access, via Better BibTeX's JSON-RPC endpoint."""

from manuscript_guard.zotero.citations import CitationUse, find_citations
from manuscript_guard.zotero.client import (
    Attachment,
    Lookup,
    Reference,
    ZoteroRefused,
    ZoteroUnavailable,
    attachments,
    available,
    export,
    library,
    lookup,
    reset_cache,
    rpc,
)

__all__ = [
    "Attachment",
    "CitationUse",
    "Lookup",
    "Reference",
    "ZoteroRefused",
    "ZoteroUnavailable",
    "attachments",
    "available",
    "export",
    "find_citations",
    "library",
    "lookup",
    "reset_cache",
    "rpc",
]
