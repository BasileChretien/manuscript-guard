"""What the plan declares in a YAML block: its controls, and its held-out data.

A control shows that the analysis can find an answer: data simulated with a known effect, a
positive control (an association known to exist) or a negative control (an exposure or an
outcome where no effect is expected), each put through the analysis that gives the result
it stands beside. A held-out input is data kept from the model's development, read only by
the script that validates the model on it. Both are declared in `design/plan.md`, before the
first results, so that the frozen copy of the plan shows what was chosen before they were
known (DESIGN.md, "Controls the plan declares, and data held out until the model is fixed").

They are written in a fenced block whose language is `yaml`, anywhere in the plan, under
`controls:` and `held_out:`. A block with neither key is the author's and is not read. The
block is found as pandoc finds a fenced block (`text.fences.fenced_spans`), after the front
matter and outside HTML comments, which pandoc drops; it is read with PyYAML's safe loader,
as `paper.yaml` is, and a key YAML would read twice is said, since YAML keeps the second
and says nothing. Each entry that breaks the form below is said at its line and left out;
the others are read.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from manuscript_guard.contracts.project import Project

#: The kinds of control (D5.1).
KINDS = ("simulated", "positive", "negative")
#: The rules that pass a control (D5.2): the interval holds the expected value; the interval
#: holds the null, which the expected value then is; the estimate is within a distance of it.
HOLDS_EXPECTED, HOLDS_NULL, WITHIN = "holds-expected", "holds-null", "within"
RULES = (HOLDS_EXPECTED, HOLDS_NULL, WITHIN)
#: The nulls a `holds-null` control may expect: of a difference and of a ratio.
NULLS = (0, 1)

#: A key as the emitter takes one (`results.schema.json`, `values`).
_KEY = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*")
#: The result a control stands beside, as Planned results write a key: as emitted, bound
#: (`results.dose`), or a group (`ror.*`, `results.ror.*`).
_OF = re.compile(r"(?:results\.)?([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)(\.\*)?")

_CONTROL_KEYS = {"key", "kind", "of", "expected", "rule", "distance"}
_CONTROL_NEEDS = ("key", "kind", "of", "expected", "rule")
_HELD_OUT_KEYS = {"input", "validated_by", "model", "read_by"}
_HELD_OUT_NEEDS = ("input", "validated_by")
_SECTIONS = ("controls", "held_out")
#: A line that opens with either key: what says a block that is not YAML meant to declare.
_DECLARING = re.compile(r"(?m)^[ \t]*[\"']?(?:controls|held_out)[\"']?[ \t]*:")


@dataclass(frozen=True)
class Control:
    """A control the plan declares, at the line its entry opens on."""

    key: str
    kind: str
    of: str  # the key, or the stem of a group, without `results.`
    group: bool
    expected: float
    rule: str
    distance: float | None
    line: int

    def said(self) -> tuple:
        """What the control is, without where it is written: what a frozen copy is held to."""
        return (self.kind, self.of, self.group, self.expected, self.rule, self.distance)


@dataclass(frozen=True)
class HeldOut:
    """A held-out input, the script that validates on it, and the model's files, if any."""

    input: str
    validated_by: str
    model: tuple[str, ...]
    read_by: tuple[str, ...]
    line: int

    def said(self) -> tuple:
        return (self.validated_by, self.model, self.read_by)

    def readers(self) -> tuple[str, ...]:
        """The scripts the plan lets read the input: the validator, and the others named."""
        return (self.validated_by, *self.read_by)


@dataclass(frozen=True)
class Unreadable:
    """An entry or a block that does not say what the form asks, at its line."""

    line: int
    message: str


@dataclass(frozen=True)
class Declarations:
    controls: tuple[Control, ...] = ()
    held_out: tuple[HeldOut, ...] = ()
    unreadable: tuple[Unreadable, ...] = ()
    #: Whether any block holds `controls` or `held_out`, read or not.
    declared: bool = False


@dataclass(frozen=True)
class _Block:
    start: int  # where the fence opens, in the text with its line ends made LF
    end: int  # just past the block
    first: int  # the line its body starts on
    root: yaml.MappingNode | None  # its YAML, where it is YAML
    error: Unreadable | None  # why it is not, where it is not and seems to declare


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _blocks(text: str) -> list[_Block]:
    """Each fenced `yaml` block that declares controls or held-out data: one whose mapping
    holds either key, or one that is not YAML and has a line opening with either."""
    from manuscript_guard.text.fences import fenced_spans
    from manuscript_guard.text.masking import fenced_blocks, front_matter_end, html_comments

    comments = html_comments(text, fenced_blocks(text))
    found = []
    for fence in fenced_spans(text, front_matter_end(text)):
        if fence.language != "yaml" or any(a <= fence.start < b for a, b in comments):
            continue
        first = text.count("\n", 0, fence.body_start) + 1
        body = text[fence.body_start : fence.body_end]
        try:
            root = yaml.compose(body, Loader=yaml.SafeLoader)
        except yaml.YAMLError as exc:
            if _DECLARING.search(body):
                mark = getattr(exc, "problem_mark", None)
                at = first + (mark.line if mark is not None else 0)
                error = Unreadable(at, f"the block is not YAML: {_problem(exc)}")
                found.append(_Block(fence.start, fence.end, first, None, error))
            continue
        if isinstance(root, yaml.MappingNode) and any(
            isinstance(name, yaml.ScalarNode) and name.value in _SECTIONS
            for name, _value in root.value
        ):
            found.append(_Block(fence.start, fence.end, first, root, None))
    return found


def without_declarations(text: str) -> str:
    """The text with each block that declares controls or held-out data blanked, its line
    ends kept. What the Deviations say is read from this: a block declares and says nothing
    of a deviation, and one under the Deviations heading would otherwise name there every
    key it declares (round 1 of #590)."""
    text = _lf(text)
    for block in reversed(_blocks(text)):
        gap = text[block.start : block.end]
        text = text[: block.start] + "\n" * gap.count("\n") + text[block.end :]
    return text


def frozen_plan(project: Project) -> tuple[str | None, bool]:
    """The plan's text as its frozen copy keeps it, and whether the copy marks an
    all-synthetic first run: None where there is no copy that reads (G12 says why). What a
    control or a held-out input declared before the first results is read from."""
    from manuscript_guard.contracts._schema import ContractError, read_structured
    from manuscript_guard.emit import FROZEN_PLAN

    frozen = project.root / FROZEN_PLAN
    if not frozen.is_file():
        return None, False
    try:
        record = read_structured(frozen)
    except ContractError:
        return None, False
    if not isinstance(record, dict) or not isinstance(record.get("plan"), str):
        return None, False
    return record["plan"].removeprefix("﻿"), record.get("synthetic") is True


def read_declarations(text: str) -> Declarations:
    """The controls and the held-out inputs the plan's YAML blocks declare."""
    text = _lf(text)
    controls: list[Control] = []
    held_out: list[HeldOut] = []
    unreadable: list[Unreadable] = []
    seen: dict[str, int] = {}
    blocks = _blocks(text)
    for block in blocks:
        if block.root is None:
            unreadable.append(block.error or Unreadable(block.first, "the block is not YAML"))
            continue
        first = block.first
        sections = [(name, value) for name, value in block.root.value
                    if isinstance(name, yaml.ScalarNode) and name.value in _SECTIONS]  # fmt: skip
        for name, value in sections:
            at = first + name.start_mark.line
            if name.value in seen:
                unreadable.append(Unreadable(at, f"{name.value} is declared in another block "
                                             f"too, at line {seen[name.value]}; one block "
                                             "holds each"))  # fmt: skip
                continue
            seen[name.value] = at
            if not isinstance(value, yaml.SequenceNode):
                unreadable.append(Unreadable(at, f"{name.value} is not a list of entries"))
                continue
            for item in value.value:
                line = first + item.start_mark.line
                read = _control(item, line) if name.value == "controls" else _held_out(item, line)
                if isinstance(read, Unreadable):
                    unreadable.append(read)
                elif isinstance(read, Control):
                    controls.append(read)
                else:
                    held_out.append(read)
    controls, held_out, twice = _once(controls, held_out)
    return Declarations(tuple(controls), tuple(held_out), tuple(unreadable + twice),
                        bool(blocks))  # fmt: skip


def _problem(exc: yaml.YAMLError) -> str:
    problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
    return str(problem)


def _fields(
    node: yaml.Node, line: int, known: set[str], needs: tuple[str, ...], what: str
) -> dict[str, object] | Unreadable:
    """The entry's fields as values, or what is wrong with it. `line` is the entry's."""
    if not isinstance(node, yaml.MappingNode):
        return Unreadable(line, f"each entry is a mapping of {', '.join(needs)}")
    fields: dict[str, object] = {}
    for name, value in node.value:
        said = name.value if isinstance(name, yaml.ScalarNode) else None
        at = line + name.start_mark.line - node.start_mark.line
        if said not in known:
            return Unreadable(at, f"{said!r} is not a field of the {what}: one of "
                                  f"{', '.join(sorted(known))}")  # fmt: skip
        if said in fields:
            return Unreadable(at, f"{said} is given twice; YAML reads the second and drops the "
                                  "first")  # fmt: skip
        fields[said] = _value(value)
    missing = [need for need in needs if need not in fields]
    if missing:
        return Unreadable(line, f"the {what} gives no {' and no '.join(missing)}")
    return fields


def _value(node: yaml.Node) -> object:
    """A node's value, as the safe loader builds it."""
    loader = yaml.SafeLoader("")
    try:
        return loader.construct_object(node, deep=True)
    finally:
        loader.dispose()


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(value)  # fmt: skip


def _control(node: yaml.Node, line: int) -> Control | Unreadable:
    fields = _fields(node, line, _CONTROL_KEYS, _CONTROL_NEEDS, "control")
    if isinstance(fields, Unreadable):
        return fields
    key, kind, of, rule = fields["key"], fields["kind"], fields["of"], fields["rule"]
    expected, distance = fields["expected"], fields.get("distance")
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        return Unreadable(line, f"the control's key {key!r} is not one the emitter takes: "
                                "lower case, digits and underscores, joined by dots")  # fmt: skip
    if kind not in KINDS:
        return Unreadable(line, f"{key}: its kind {kind!r} is none of {', '.join(KINDS)}")
    written = _OF.fullmatch(of) if isinstance(of, str) else None
    if written is None:
        return Unreadable(line, f"{key}: of {of!r} names no result: a key, `ror.point`, or a "
                                "group, `ror.*`")  # fmt: skip
    if _own(key, written.group(1), bool(written.group(2))):
        return Unreadable(line, f"{key}: its values fall under the result it stands beside, "
                                f"{of}, so it would stand beside itself")  # fmt: skip
    if not _number(expected):
        return Unreadable(line, f"{key}: the expected value {expected!r} is not a number "
                                "(YAML reads 1e-3 as words; write 0.001)")  # fmt: skip
    if rule not in RULES:
        return Unreadable(line, f"{key}: its rule {rule!r} is none of {', '.join(RULES)}")
    if rule == WITHIN:
        if distance is None or not _number(distance) or distance <= 0:
            return Unreadable(line, f"{key}: a control passed within a distance gives that "
                                    "distance, a number above nought")  # fmt: skip
    elif distance is not None:
        return Unreadable(line, f"{key}: a distance is given only with the rule {WITHIN}")
    if rule == HOLDS_NULL and expected not in NULLS:
        return Unreadable(line, f"{key}: a control that holds the null expects the null, 0 "
                                f"or 1, not {expected!r}")  # fmt: skip
    return Control(key, kind, written.group(1), bool(written.group(2)), float(expected), rule,
                   None if distance is None else float(distance), line)  # fmt: skip


#: What a control publishes under its key, as `Emitter.interval` names an estimate's parts.
PARTS = ("point", "ci_low", "ci_high")


def _own(key: str, of: str, group: bool) -> bool:
    """Whether a control's values fall under the result it names, or that result under the
    control: `ror.shuffled` of `ror.*`, `ror` of `ror.*` (its `ror.point` is under it), or
    `ror` of `ror.point`. It would then stand beside its own values (round 3 of #590)."""
    values = [f"{key}.{part}" for part in PARTS]
    if group:
        return any(value.startswith(f"{of}.") for value in values) or of.startswith(f"{key}.") \
            or of == key  # fmt: skip
    return of in values or of == key or of.startswith(f"{key}.")


def _path(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _held_out(node: yaml.Node, line: int) -> HeldOut | Unreadable:
    fields = _fields(node, line, _HELD_OUT_KEYS, _HELD_OUT_NEEDS, "held-out input")
    if isinstance(fields, Unreadable):
        return fields
    given, script = fields["input"], fields["validated_by"]
    if not _path(given):
        return Unreadable(line, f"the held-out input {given!r} is not a path")
    if not _path(script):
        return Unreadable(line, f"{given}: validated_by {script!r} is not a script's path")
    paths: dict[str, tuple[str, ...]] = {}
    for name in ("model", "read_by"):
        written = fields.get(name, [])
        listed = [written] if isinstance(written, str) else written
        if not isinstance(listed, list) or not all(_path(m) for m in listed):
            return Unreadable(line, f"{given}: {name} {written!r} is not a path or a list of "
                                    "paths")  # fmt: skip
        paths[name] = tuple(_posix(m) for m in listed)
    return HeldOut(_posix(given), _posix(script), paths["model"], paths["read_by"], line)


def _posix(path: str) -> str:
    """A path as the emitters record one: with forward slashes, from the project's root."""
    return path.replace("\\", "/").removeprefix("./")


def _once(
    controls: list[Control], held_out: list[HeldOut]
) -> tuple[list[Control], list[HeldOut], list[Unreadable]]:
    """Each key and each input once: one declared twice is said at the second, and neither is
    read, since which was meant cannot be told."""
    twice: list[Unreadable] = []
    keys = [c.key for c in controls]
    inputs = [h.input for h in held_out]
    for name, entries, of in (("control", controls, keys), ("held-out input", held_out, inputs)):
        for index, entry in enumerate(entries):
            said = of[index]
            if of.index(said) != index:
                twice.append(Unreadable(entry.line, f"the {name} {said} is declared twice"))
    controls = [c for c in controls if keys.count(c.key) == 1]
    held_out = [h for h in held_out if inputs.count(h.input) == 1]
    return controls, held_out, twice
