"""What the EU PAS register says of one study, read from its pages.

The register is now the HMA-EMA Catalogue of real-world data studies, and it has no API: it
serves its records as web pages only (Drupal 11; a `?_format=json` is redirected back to the
page). So its pages are read, by the labels and classes they carry, as they were on
2026-10-21:

* `/study/<n>` answers 302 for the study whose Study ID is `<n>`, to
  `/node/<k>/administrative-details`, and 404 for a Study ID it does not have. A number of
  the scheme the catalogue began in 2024 (EUPAS1000000417) is its Study ID; an older one
  (EUPAS11379, Study ID 23396) is not, and is found by the catalogue's search,
  `/search?search_api_fulltext=EUPAS11379`, whose results link `/study/<n>`.
* The administrative page holds the title (`h1.content-banner-title`), the date the record
  was first published (`.form-item-published-date-field .field-content`, dd/mm/yyyy), the
  EU PAS number (`.darwin-study__field-darwin-eu-pas-number .field__item`), and the
  timeline, each date a `<time datetime>` under a class of its own: the actual start of data
  collection (`-data-col-start-act`) and of data analysis (`-data-ana-start-act`).
* The methodological page holds each field as a `dl.description-list-item`, its label in
  `dt` and its words in `dd`: the study type, the design, the population, the main
  objective, the comparators, the outcomes and the data analysis plan.

A page without the title, the date and the number is not of that shape, and the answer is
`unresolvable`: never read as the study having none. The page given for a number must give
that number, or it is another study's.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from manuscript_guard.lookup.http import Request
from manuscript_guard.lookup.sources import ABSENT, FOUND, Ask, _ask, _status_only, unresolvable

PAGE = "a page not of the shape the catalogue's pages had on 2026-10-21"
#: The first number of the catalogue's own scheme: from it on, the EU PAS number is the
#: Study ID.
OWN_SCHEME = 1_000_000_000
#: Study pages read from one search, at most: a number names one study.
CANDIDATES = 5
_VOID = frozenset(
    ["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
     "source", "track", "wbr"]
)  # fmt: skip
_NODE = re.compile(r"^(?:https://[^/]+)?/node/(\d+)/administrative-details$")
_STUDY = re.compile(r'href="/study/(\d+)"')
_DAY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


class _Element:
    __slots__ = ("attrs", "children", "tag")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[Any] = []

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        """Its words, a line break where the page breaks a line, spacing folded."""
        parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, str):
                parts.append(node)
                return
            if node.tag in ("br", "p", "div", "li"):
                parts.append("\n")
            for child in node.children:
                walk(child)

        walk(self)
        lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
        return "\n".join(line for line in lines if line)

    def walk(self):
        for child in self.children:
            if isinstance(child, _Element):
                yield child
                yield from child.walk()


class _Tree(HTMLParser):
    """The page as a tree, enough to find an element by its class and read its words. An
    end tag closes the nearest open element of its name, and a stray one is ignored."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Element("root", {})
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
            return
        element = _Element(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(element)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return

    def handle_data(self, data):
        if not self.skip:
            self.stack[-1].children.append(data)


def _tree(body: bytes) -> _Element:
    parser = _Tree()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return parser.root


def _first(root: _Element, cls: str) -> _Element | None:
    return next((e for e in root.walk() if cls in e.classes), None)


def _iso(text: str | None) -> str | None:
    found = _DAY.search(text or "")
    return f"{found.group(3)}-{found.group(2)}-{found.group(1)}" if found else None


def _time(root: _Element, cls: str) -> str | None:
    """The day a `<time datetime>` under the class gives, read from its attribute."""
    holder = _first(root, cls)
    if holder is None:
        return None
    stamp = next((e.attrs.get("datetime", "") for e in holder.walk() if e.tag == "time"), "")
    return stamp[:10] if re.match(r"\d{4}-\d{2}-\d{2}", stamp) else None


def _administrative(body: bytes) -> dict[str, Any] | None:
    root = _tree(body)
    title = next(
        (e for e in root.walk() if e.tag == "h1" and "content-banner-title" in e.classes), None
    )
    published = _first(root, "form-item-published-date-field")
    updated = _first(root, "form-item-update-date-field")
    number = _first(root, "darwin-study__field-darwin-eu-pas-number")

    def value(holder: _Element | None, cls: str) -> str | None:
        inner = _first(holder, cls) if holder is not None else None
        return inner.text() if inner is not None else None

    registered = _iso(value(published, "field-content"))
    said = value(number, "field__item")
    if title is None or registered is None or not said:
        return None
    status = _first(root, "darwin-study__status")
    return {
        "title": title.text(),
        "number": said.strip(),
        "registered": registered,
        "updated": _iso(value(updated, "field-content")),
        "status": status.text() if status is not None else None,
        "study_start": _time(root, "darwin-study__field-darwin-data-col-start-act"),
        "analysis_start": _time(root, "darwin-study__field-darwin-data-ana-start-act"),
    }


def _methodological(body: bytes) -> list[dict[str, Any]] | None:
    root = _tree(body)
    sections = []
    for item in root.walk():
        if item.tag != "dl" or "description-list-item" not in item.classes:
            continue
        label = next((e for e in item.walk() if e.tag == "dt"), None)
        words = next((e for e in item.walk() if e.tag == "dd"), None)
        if label is None or words is None:
            continue
        name, text = label.text(), words.text()
        if name and text:
            section = {"label": name, "text": text}
            if name.casefold() == "outcomes":
                section["role"] = "outcomes"
            sections.append(section)
    return sections or None


def _node(ask: Ask, base: str, study: str) -> str | dict[str, Any] | None:
    """The page a Study ID redirects to, None for a Study ID the catalogue does not have, or
    the record's answer where no answer came."""
    answer = _ask(ask, Request(f"{base}/study/{study}", headers={"Accept": "text/html"}))
    if isinstance(answer, dict):
        return answer
    if answer.status == 404:
        return None
    if answer.status in (301, 302):
        location = answer.headers.get("Location", "")
        parts = urlsplit(location)
        if parts.hostname not in (None, urlsplit(base).hostname):
            return unresolvable("the catalogue redirected to another site, and it was not followed")
        found = _NODE.match(parts.path if parts.hostname else location)
        return found.group(1) if found else unresolvable(PAGE)
    return _status_only(answer) or unresolvable(PAGE)


def _page(ask: Ask, base: str, node: str, tab: str) -> bytes | dict[str, Any]:
    answer = _ask(ask, Request(f"{base}/node/{node}/{tab}", headers={"Accept": "text/html"}))
    if isinstance(answer, dict):
        return answer
    return _status_only(answer) or answer.body


def _study(ask: Ask, base: str, node: str, wanted: str) -> dict[str, Any] | None:
    """The record a study's pages give, None where they give another EU PAS number."""
    admin = _page(ask, base, node, "administrative-details")
    if isinstance(admin, dict):
        return admin
    header = _administrative(admin)
    if header is None:
        return unresolvable(PAGE)
    if header["number"].upper() != wanted:
        return None
    method = _page(ask, base, node, "methodological-aspects")
    if isinstance(method, dict):
        return method
    sections = _methodological(method)
    if sections is None:
        return unresolvable(PAGE)
    said = {s["label"].casefold(): s["text"] for s in sections}
    kind = said.get("study type", "").casefold()
    if "non-interventional" in kind:
        study_type = "observational"
    elif "interventional" in kind or "clinical trial" in kind:
        study_type = "interventional"
    else:
        study_type = None
    record = {
        "status": FOUND,
        "title": header["title"],
        "dates": {k: header[k] for k in ("registered", "study_start", "analysis_start", "updated")
                  if header[k]},  # fmt: skip
        "study_type": study_type,
        "design": said.get("non-interventional study design"),
        "sections": sections,
    }
    return {k: v for k, v in record.items() if v not in (None, "", [])}


def eu_pas(identifier: str, ask: Ask, base: str) -> dict[str, Any]:
    """The catalogue's record of one EU PAS number."""
    digits = identifier.removeprefix("EUPAS")
    first = _node(ask, base, digits)
    if isinstance(first, dict):
        return first
    if first is not None:
        found = _study(ask, base, first, identifier)
        if found is not None:
            return found
    if int(digits) >= OWN_SCHEME:
        return {"status": ABSENT, "why": f"the catalogue has no study {identifier}"}
    # An older number is not the Study ID: the catalogue's search finds the study it names.
    answer = _ask(ask, Request(f"{base}/search", params={"search_api_fulltext": identifier},
                               headers={"Accept": "text/html"}))  # fmt: skip
    if isinstance(answer, dict):
        return answer
    said = _status_only(answer)
    if said:
        return said
    page = answer.body.decode("utf-8", errors="replace")
    candidates = [n for n in dict.fromkeys(_STUDY.findall(page)) if n != digits][:CANDIDATES]
    for study in candidates:
        node = _node(ask, base, study)
        if isinstance(node, dict):
            return node
        if node is None:
            continue
        found = _study(ask, base, node, identifier)
        if found is not None:
            return found
    if not candidates and "results" not in page:
        return unresolvable(PAGE)
    return {"status": ABSENT, "why": f"no study page of the catalogue gives {identifier}"}


__all__ = ["CANDIDATES", "OWN_SCHEME", "PAGE", "eu_pas"]
