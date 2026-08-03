"""Talking to a running Zotero through Better BibTeX.

Zotero's own local API is off by default, and turning it on is a step every user would have
to be talked through. Better BibTeX's JSON-RPC endpoint is available whenever BBT is
installed, returns CSL-JSON including citation keys, and can export a bibliography — which
is everything this toolkit needs.

Two practical notes, both learned the hard way:

* Zotero answers HTTP/1.0 with a close-delimited body. Some HTTP clients reject that
  outright ("the response ended prematurely"); `urllib` handles it, so this module uses it
  rather than anything more capable.
* Zotero must be running. Nothing here should be on the critical path of a build that has
  to work in CI, which is why the committed `.bib` exists.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

ENDPOINT = "http://127.0.0.1:23119/better-bibtex/json-rpc"
PING = "http://127.0.0.1:23119/connector/ping"
# Two budgets, because the two callers want opposite things.
#
# A gate must not stall a build: Zotero indexing a large library can leave item.search
# unanswered for minutes, and a check that hangs is worse than one that says "I could not
# read Zotero, using the committed bibliography". An explicit `sync-bib` is the opposite —
# the author asked for it and will wait.
GATE_TIMEOUT = 20
LONG_TIMEOUT = 300


class ZoteroUnavailable(Exception):
    """Zotero is not running, or Better BibTeX is not answering."""


@dataclass(frozen=True)
class Reference:
    citekey: str
    csl: dict

    @property
    def title(self) -> str:
        return str(self.csl.get("title", ""))

    @property
    def pinned(self) -> bool:
        """Whether the citation key is pinned in the item's Extra field.

        An unpinned key is derived from metadata, so correcting an author's initials or a
        year silently renames it and breaks every citation that used it. BBT records a
        pinned key as `Citation Key: xyz` in Extra, which surfaces here as `note`.
        """
        note = str(self.csl.get("note", ""))
        return "citation key:" in note.lower()


# Once Zotero has failed to answer, stop asking. A gate that retries a 20 second timeout
# for every check in a run turns a two second command into a two minute one, and the
# answer is not going to change within the process.
_unreachable = False


def available() -> bool:
    if _unreachable:
        return False
    try:
        with urllib.request.urlopen(PING, timeout=5) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def rpc(method: str, params, timeout: int = GATE_TIMEOUT) -> object:
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1})
    request = urllib.request.Request(
        ENDPOINT, data=payload.encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        global _unreachable
        _unreachable = True
        raise ZoteroUnavailable(
            f"could not reach Better BibTeX at {ENDPOINT}: {exc}. Is Zotero running?"
        ) from exc
    if "error" in body:
        raise ZoteroUnavailable(f"Better BibTeX refused {method}: {body['error']}")
    return body.get("result")


@lru_cache(maxsize=4)
def library(timeout: int = GATE_TIMEOUT) -> dict[str, Reference]:
    """Every item that has a citation key, indexed by key.

    Fetched once per process: a build resolves many keys and the library does not change
    underneath it.
    """
    result = rpc("item.search", [""], timeout=timeout)
    if not isinstance(result, list):
        raise ZoteroUnavailable("item.search did not return a list")
    found: dict[str, Reference] = {}
    for item in result:
        key = item.get("citation-key")
        if key:
            found[key] = Reference(citekey=key, csl=item)
    return found


def export(citekeys: list[str], translator: str = "biblatex") -> str:
    """A bibliography for the given keys, as text.

    Written to `literature/references.bib` and committed, so that a build works for a
    co-author who has no Zotero, and in CI where there is certainly none.
    """
    result = rpc("item.export", [sorted(citekeys), translator], timeout=LONG_TIMEOUT)
    if isinstance(result, str):
        return result
    if isinstance(result, list) and result and isinstance(result[0], str):
        return result[0]
    raise ZoteroUnavailable(f"item.export returned {type(result).__name__}, expected text")


def reset_cache() -> None:
    global _unreachable
    _unreachable = False
    library.cache_clear()
