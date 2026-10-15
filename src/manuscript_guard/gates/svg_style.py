"""The rules of an SVG figure's own stylesheet, as far as its texts and lines need them.

An SVG may set a text's size or a line's stroke in a `<style>` element rather than on the
element: svglite, which R's `ggsave()` writes SVG with, strokes every black line from its
stylesheet (`.svglite line, .svglite path, ... { stroke: #000000 }`), and Illustrator's
default export sets every size through a class (`.st0 { font-size: 5px }`). Without these
rules a figure's lines are not seen and its texts are read at SVG's default.

A rule's selector is read where it is made of type, class and id selectors joined by
descendant or child combinators (`.svglite g.glyphgroup path`); one with a pseudo-class,
an attribute selector or a sibling combinator is not, and its rule does not apply. Rules
apply by specificity, then in the order they are written; a presentation attribute gives
way to them, and an element's own `style` overrides them, as CSS has it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

SVG = "{http://www.w3.org/2000/svg}"
#: The properties the figure checks read; the rest of a rule is not kept.
READ = ("font-size", "font", "stroke", "stroke-width", "display", "visibility")

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
#: A rule: its selectors, and its declarations between braces. An at-rule's block is not
#: one, and what is inside it is read as rules of its own.
_RULE = re.compile(r"([^{}@;]+)\{([^{}]*)\}")
_COMPOUND = re.compile(r"(?P<tag>\*|[A-Za-z][\w-]*)?(?P<rest>(?:[.#][\w-]+)*)")
_IMPORTANT = re.compile(r"\s*!\s*important\s*$", re.IGNORECASE)

Compound = tuple[str, frozenset[str], str]


@dataclass(frozen=True)
class Rule:
    """One selector of a rule, with what the rule declares."""

    selector: tuple[Compound, ...]
    specificity: tuple[int, int, int]
    order: int
    declared: dict[str, str]


def declarations(text: str) -> dict[str, str]:
    """`a: b; c: d` as properties and their values, the properties in lower case."""
    said: dict[str, str] = {}
    for part in text.split(";"):
        key, _, value = part.partition(":")
        key, value = key.strip().lower(), _IMPORTANT.sub("", value.strip())
        if key and value:
            said[key] = value
    return said


def _tag(node: ET.Element) -> str:
    return node.tag.removeprefix(SVG) if isinstance(node.tag, str) else ""


def _selector(text: str) -> tuple[Compound, ...] | None:
    """A selector as its compounds, the last the element's own; None where it is one this
    does not read."""
    if any(mark in text for mark in "+~:[]()"):
        return None
    compounds = []
    for part in text.replace(">", " ").split():
        match = _COMPOUND.fullmatch(part)
        if match is None or not part:
            return None
        rest = re.findall(r"[.#][\w-]+", match.group("rest"))
        tag = match.group("tag") or ""
        classes = frozenset(r[1:] for r in rest if r[0] == ".")
        ids = [r[1:] for r in rest if r[0] == "#"]
        if len(ids) > 1:
            return None
        compounds.append(("" if tag == "*" else tag, classes, ids[0] if ids else ""))
    return tuple(compounds) or None


class Sheet:
    """The rules of every `<style>` in a figure, and what applies to each element."""

    def __init__(self, root: ET.Element) -> None:
        self.parents = {child: parent for parent in root.iter() for child in parent}
        self.rules: list[Rule] = []
        for node in root.iter():
            if _tag(node) != "style":
                continue
            text = _COMMENT.sub(" ", "".join(node.itertext()))
            for match in _RULE.finditer(text):
                declared = {
                    k: v for k, v in declarations(match.group(2)).items() if k in READ
                }
                if not declared:
                    continue
                for written in match.group(1).split(","):
                    selector = _selector(written)
                    if selector is None:
                        continue
                    specificity = (
                        sum(1 for _t, _c, i in selector if i),
                        sum(len(c) for _t, c, _i in selector),
                        sum(1 for t, _c, _i in selector if t),
                    )
                    self.rules.append(Rule(selector, specificity, len(self.rules), declared))

    def declared(self, node: ET.Element) -> dict[str, str]:
        """What the stylesheet declares of `node`, the stronger rule last."""
        said: dict[str, str] = {}
        applying = [rule for rule in self.rules if self._matches(node, rule.selector)]
        for rule in sorted(applying, key=lambda rule: (rule.specificity, rule.order)):
            said.update(rule.declared)
        return said

    def _matches(self, node: ET.Element, selector: tuple[Compound, ...]) -> bool:
        if not _compound_matches(node, selector[-1]):
            return False
        wanted = len(selector) - 2
        ancestor = self.parents.get(node)
        while wanted >= 0 and ancestor is not None:
            if _compound_matches(ancestor, selector[wanted]):
                wanted -= 1
            ancestor = self.parents.get(ancestor)
        return wanted < 0


def _compound_matches(node: ET.Element, compound: Compound) -> bool:
    tag, classes, ident = compound
    if tag and _tag(node) != tag:
        return False
    if ident and node.get("id") != ident:
        return False
    return classes <= frozenset((node.get("class") or "").split())
