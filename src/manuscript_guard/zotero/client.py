"""Talking to a running Zotero through Better BibTeX.

Zotero's own local API is off by default, and turning it on is a step every user would have
to be talked through. Better BibTeX's JSON-RPC endpoint is available whenever BBT is
installed, returns CSL-JSON including citation keys, and can export a bibliography — which
is everything this toolkit needs.

Three practical notes, all learned the hard way:

* Zotero answers HTTP/1.0 with a close-delimited body. Some HTTP clients reject that
  outright ("the response ended prematurely"); `urllib` handles it, so this module uses it
  rather than anything more capable.
* Zotero must be running. Nothing here should be on the critical path of a build that has
  to work in CI, which is why the committed `.bib` exists.
* Never ask for the whole library. `item.search("")` serialises every item as CSL; on a
  library of 4,688 items it took 51 seconds, so a gate with a 20 second budget passed or
  failed depending on how busy Zotero was. The gate asks about the keys the manuscript cites
  and the items whose key is pinned, which takes well under a second (`lookup`).
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache

ENDPOINT = "http://127.0.0.1:23119/better-bibtex/json-rpc"
PING = "http://127.0.0.1:23119/connector/ping"
# Two budgets, because the two callers want opposite things.
#
# A gate must not stall a build: Zotero indexing a large library can leave a search
# unanswered for minutes, and a check that hangs is worse than one that says "I could not
# read Zotero, using the committed bibliography". An explicit `sync-bib` is the opposite —
# the author asked for it and will wait.
GATE_TIMEOUT = 20
LONG_TIMEOUT = 300

# A key is pinned by the line `Citation Key: xyz` in the item's Extra field. Better BibTeX
# hands Extra back as the CSL `note`, and on the way rewrites the field name to its CSL
# spelling, `citation-key: xyz`. Both spellings are the same pin.
PIN_LINE = re.compile(r"^\s*citation[ -]key\s*:\s*\S", re.IGNORECASE | re.MULTILINE)
# A Zotero search condition, which Better BibTeX's item.search accepts in place of a query
# string: every item whose Extra carries a pin. Zotero's "contains" ignores case.
PINNED_CONDITION = [["extra", "contains", "Citation Key:"]]


class ZoteroUnavailable(Exception):
    """Zotero is not running, or Better BibTeX is not answering."""


class ZoteroRefused(ZoteroUnavailable):
    """Better BibTeX answered with an error: an unknown method, bad arguments, a duplicate."""


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
        pinned key as `Citation Key: xyz` in Extra, which surfaces here in `note` as
        `citation-key: xyz`; either spelling counts.
        """
        return PIN_LINE.search(str(self.csl.get("note", ""))) is not None


@dataclass(frozen=True)
class Lookup:
    """What Zotero says about the keys a manuscript cites.

    `found` holds the keys that name exactly one item and `pinned` those of them whose key
    is pinned. `missing` holds the keys no item carries, and `ambiguous` the keys several
    items carry, with how many: Better BibTeX refuses to export such a key, so `sync-bib`
    stops on it.
    """

    found: frozenset[str] = frozenset()
    pinned: frozenset[str] = frozenset()
    missing: frozenset[str] = frozenset()
    ambiguous: dict[str, int] = field(default_factory=dict)

    @property
    def unpinned(self) -> frozenset[str]:
        return self.found - self.pinned


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


def _timed_out(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, TimeoutError) or "timed out" in str(reason)


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
        if _timed_out(exc):
            # Zotero is up (the ping answered) but busy: say so, rather than asking whether
            # it is running, which sends the author to look for a problem that is not there.
            raise ZoteroUnavailable(
                f"Better BibTeX did not answer {method} within {timeout} s; Zotero is running "
                "but busy (indexing, syncing, or a very large request)"
            ) from exc
        raise ZoteroUnavailable(
            f"could not reach Better BibTeX at {ENDPOINT}: {exc}. Is Zotero running?"
        ) from exc
    if "error" in body:
        raise ZoteroRefused(f"Better BibTeX refused {method}: {body['error']}")
    return body.get("result")


@lru_cache(maxsize=4)
def library(timeout: int = GATE_TIMEOUT) -> dict[str, Reference]:
    """Every item that has a citation key, indexed by key.

    Slow on a real library (see the module docstring): the gate uses `lookup` instead, and
    falls back to this only when Better BibTeX is too old to answer `lookup`'s questions.
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


def _pinned_keys(timeout: int) -> frozenset[str]:
    """The keys of every item whose citation key is pinned, from one condition search."""
    result = rpc("item.search", [PINNED_CONDITION], timeout=timeout)
    if not isinstance(result, list):
        raise ZoteroRefused("item.search with a condition did not return a list")
    return frozenset(
        item["citation-key"]
        for item in result
        if item.get("citation-key") and Reference(item["citation-key"], item).pinned
    )


USER_LIBRARY = 1  # Zotero's own library; group libraries have other IDs


def _resolve(keys: list[str], library_id: int | None, timeout: int) -> tuple[set, dict]:
    """One `item.pandoc_filter` call: the keys it resolved, and its count for the rest.

    Better BibTeX reports a key it cannot resolve with the number of items carrying it: 0
    for none, 2 or more for a duplicate.
    """
    params: list = [keys, True] if library_id is None else [keys, True, library_id]
    result = rpc("item.pandoc_filter", params, timeout=timeout)
    if not isinstance(result, dict):
        raise ZoteroRefused("item.pandoc_filter did not return an object")
    resolved = set((result.get("items") or {}).keys()) & set(keys)
    counts = {str(k): int(v) for k, v in (result.get("errors") or {}).items()}
    return resolved, counts


def _group_libraries(timeout: int) -> list[int]:
    try:
        groups = rpc("user.groups", [], timeout=timeout)
    except ZoteroRefused:
        return []
    return [
        g["id"]
        for g in (groups if isinstance(groups, list) else [])
        if isinstance(g, dict) and g.get("id") not in (None, USER_LIBRARY)
    ]


@lru_cache(maxsize=8)
def lookup(citekeys: tuple[str, ...], timeout: int = GATE_TIMEOUT) -> Lookup:
    """Resolve the cited keys and say which are pinned, without reading the whole library.

    `item.pandoc_filter`, the call Better BibTeX's own pandoc filter makes, resolves the keys
    in the user's library; the keys it cannot find there are asked of each group library in
    turn. Pinning comes from a single search for items whose Extra holds a pin. The number
    of calls depends on the number of libraries, never on the number of keys: a first
    version searched for each unresolved key separately, and a manuscript citing 3,000 keys
    that Zotero did not hold kept a check waiting for twenty minutes.
    """
    keys = tuple(sorted(set(citekeys)))
    if not keys:
        return Lookup()
    try:
        found, counts = _resolve(list(keys), None, timeout)
        unresolved = sorted(k for k, n in counts.items() if n == 0)
        for library_id in _group_libraries(timeout) if unresolved else []:
            more, more_counts = _resolve(unresolved, library_id, timeout)
            found |= more
            counts.update({k: n for k, n in more_counts.items() if n > 1})
            unresolved = sorted(k for k, n in more_counts.items() if n == 0)
            if not unresolved:
                break
        pinned = _pinned_keys(timeout)
    except ZoteroRefused:
        # A Better BibTeX without item.pandoc_filter or condition searches: fall back to
        # the whole library, which is slow but gives the same answers.
        index = library(timeout)
        in_index = frozenset(k for k in keys if k in index)
        return Lookup(
            found=in_index,
            pinned=frozenset(k for k in in_index if index[k].pinned),
            missing=frozenset(keys) - in_index,
        )
    ambiguous = {k: n for k, n in counts.items() if n > 1 and k not in found}
    # Keys pandoc_filter neither returned nor reported count as unresolved rather than pass.
    missing = set(keys) - found - set(ambiguous)
    return Lookup(
        found=frozenset(found),
        pinned=frozenset(found) & pinned,
        missing=frozenset(missing),
        ambiguous=ambiguous,
    )


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
    lookup.cache_clear()
