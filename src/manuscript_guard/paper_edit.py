"""`manuscript-guard set`: one setting of `paper.yaml` written, and every other byte kept.

`paper.yaml` is the author's file, and most of it is comments: what each setting means,
why a convention was added, what the stage ladder is. A YAML library that loads it and
writes it back drops every one of them. So `set` edits the text, in one of three ways:

- the key is written at the top level: its value, and nothing else, is replaced, and a
  comment after it on the same line stays;
- it is not, and one line at the left margin reads `# key: ...`, the commented example
  `init` writes: that line becomes the setting;
- neither: the setting is added at the end of the file.

Then the result is read back. It has to be the settings that were there with that one key
changed, and the schema must find nothing in it that it did not find before. Only then is
the file written, and atomically. Whatever the edit could get wrong is refused before it:
a file of one mapping between braces, anchors and aliases (an edit of one place can change
another), a key written twice (YAML keeps the second, and which one was meant is not for
`set` to guess), and a value over several lines, other than a list of names one to a line
with nothing between them.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import _not_utf8, _plain, load_schema

#: The keys `set` writes, and of them the one that holds a list.
KEYS = ("stage", "target_journal", "english_variant", "reporting_guideline", "study_type")
LIST_KEYS = frozenset({"reporting_guideline"})

#: What is written without quotation marks: a name, read back by YAML as the same text.
_PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
#: What a YAML 1.2 reader types as other than text, by the core schema's own patterns: a
#: name PyYAML, a YAML 1.1 reader, keeps as text (`1e3`, `0o17`) is quoted all the same,
#: since another tool that reads the file may take it for a number.
_YAML_12 = re.compile(
    r"(?:null|Null|NULL|~|true|True|TRUE|false|False|FALSE"
    r"|[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+"
    r"|[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))\Z"
)
_BOM = chr(0xFEFF)
#: What one edit could reach another setting through.
_UNSAFE = (yaml.AnchorToken, yaml.AliasToken)
#: What PyYAML reads as the end of a line and an editor, or this module, may not: a file
#: that holds one has lines `set` cannot count as YAML does.
_OTHER_BREAKS = {chr(0x85): "U+0085", chr(0x2028): "U+2028", chr(0x2029): "U+2029"}


class Refused(Exception):
    """Why `set` wrote nothing, in a sentence for the author."""


@dataclass(frozen=True)
class Edited:
    """The file's text after the edit, how the key was written, and what it held."""

    text: str
    how: str  # "replaced", "uncommented", "appended" or "unchanged"
    before: Any


def written(value: Any) -> str:
    """A value as `set` writes it: a name plain, other text in single quotation marks, a
    list between brackets."""
    if isinstance(value, list):
        return "[" + ", ".join(written(entry) for entry in value) + "]"
    plain = _PLAIN.match(value) and not _YAML_12.match(value)
    if plain and yaml.safe_load(f"k: {value}") == {"k": value}:
        return value
    return "'" + value.replace("'", "''") + "'"


def _loaded(text: str) -> dict:
    try:
        document = _plain(yaml.safe_load(text))
    except Exception as exc:  # noqa: BLE001 - whatever the parser raises is about the text
        raise Refused(f"it cannot be read as YAML: {exc}") from exc
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise Refused("it holds no settings, one `key: value` to a line")
    return document


def _structure(text: str) -> tuple[yaml.Node | None, list[tuple[int, int]]]:
    """The file as YAML composes it, and where each scalar stands; refused where an edit
    of one line cannot be trusted."""
    try:
        tokens = list(yaml.scan(text, Loader=yaml.SafeLoader))
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise Refused(f"it cannot be read as YAML: {exc}") from exc
    for token in tokens:
        if isinstance(token, _UNSAFE):
            raise Refused(
                f"line {token.start_mark.line + 1} holds an anchor or an alias, through which "
                "one edit can change another setting; write the value out where it is used"
            )
    if root is not None and not isinstance(root, yaml.MappingNode):
        raise Refused("it holds no settings, one `key: value` to a line")
    if root is not None and root.flow_style:
        raise Refused(
            "its settings are one mapping between braces, which cannot be edited a line at a "
            "time; write them one `key: value` to a line"
        )
    _no_key_twice(root)
    scalars = [
        (token.start_mark.index, token.end_mark.index)
        for token in tokens
        if isinstance(token, yaml.ScalarToken)
    ]
    return root, scalars


def _no_key_twice(root: yaml.Node | None) -> None:
    stack = [root] if root is not None else []
    while stack:
        node = stack.pop()
        if isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
        if not isinstance(node, yaml.MappingNode):
            continue
        seen: dict[str, int] = {}
        for key, value in node.value:
            line = key.start_mark.line + 1
            if isinstance(key, yaml.ScalarNode) and key.value in seen:
                raise Refused(
                    f"`{key.value}` is written twice, on lines {seen[key.value]} and {line}: "
                    "YAML keeps the second, and which one is meant is not for `set` to "
                    "guess; take one out"
                )
            if isinstance(key, yaml.ScalarNode):
                seen[key.value] = line
            stack += [key, value]


def _line_start(text: str, at: int) -> int:
    return max(text.rfind("\n", 0, at), text.rfind("\r", 0, at)) + 1


def _line_end(text: str, at: int) -> int:
    ends = [found for found in (text.find("\n", at), text.find("\r", at)) if found >= 0]
    return min(ends, default=len(text))


def _line_break(text: str) -> str:
    found = re.search(r"\r\n|\n|\r", text)
    return found[0] if found else "\n"


def _replaced(text: str, key: yaml.Node, value: yaml.Node, new: Any) -> str:
    """The text with the value `key` holds replaced by `new`."""
    start, end = value.start_mark.index, value.end_mark.index
    one_line = value.start_mark.line == value.end_mark.line
    if isinstance(value, yaml.ScalarNode) and value.style not in ("|", ">") and one_line:
        if start == end:  # nothing after the colon: what follows it on the line is kept
            return text[:start] + " " + written(new) + text[start:]
        return text[:start] + written(new) + text[end:]
    if isinstance(value, yaml.SequenceNode) and value.flow_style and one_line:
        return text[:start] + written(new) + text[end:]
    if isinstance(value, yaml.SequenceNode) and not value.flow_style and isinstance(new, list):
        return _block_replaced(text, key, value, new)
    raise Refused(
        f"`{key.value}` holds a value over several lines, which `set` does not rewrite; "
        "put it on one line, or edit it by hand"
    )


def _block_replaced(text: str, key: yaml.Node, value: yaml.SequenceNode, new: list) -> str:
    """A list written one entry to a line, replaced by `new` in the same layout: each
    entry a name on its own line, one after another, with nothing between them."""
    items = value.value
    lines = []
    for item in items:
        if not isinstance(item, yaml.ScalarNode) or item.start_mark.line != item.end_mark.line:
            lines = []
            break
        begin = _line_start(text, item.start_mark.index)
        finish = _line_end(text, item.end_mark.index)
        raw = re.escape(text[item.start_mark.index : item.end_mark.index])
        if not re.fullmatch(rf"[ \t]*-[ \t]+{raw}[ \t]*", text[begin:finish]):
            lines = []
            break
        lines.append((begin, finish))
    key_end = _line_end(text, key.end_mark.index)
    after_key = text[key_end : key_end + 2]
    breaks = ("\r\n",) if after_key == "\r\n" else (after_key[:1],)
    joined = lines and all(
        text[previous_end:next_begin] in breaks
        for previous_end, next_begin in zip(
            [key_end, *(end for _begin, end in lines[:-1])],
            [begin for begin, _end in lines],
            strict=True,
        )
    )
    if not joined:
        raise Refused(
            f"`{key.value}` is a list with a comment, a blank line or an entry over several "
            "lines among its entries, which `set` would lose; edit it by hand"
        )
    first, last = lines[0][0], lines[-1][1]
    if new:
        prefix = text[first : items[0].start_mark.index]
        entries = breaks[0].join(prefix + written(entry) for entry in new)
        return text[:first] + entries + text[last:]
    colon = text.index(":", key.end_mark.index)
    return text[: colon + 1] + " []" + text[colon + 1 : key_end] + text[last:]


def _uncommented(text: str, key: str, new: Any, scalars: list[tuple[int, int]]) -> str | None:
    """The text with the one line `# key: ...` at the left margin made the setting, or
    None where there is no such line or more than one."""
    pattern = re.compile(rf"^#[ \t]?{re.escape(key)}:(?=[ \t\r\n]|\Z)[^\r\n]*", re.MULTILINE)
    found = [
        line
        for line in pattern.finditer(text)
        if not any(start < line.start() < end for start, end in scalars)
    ]
    if len(found) != 1:
        return None
    line = found[0]
    # The line without its `#`, read as a setting, has its value replaced as a setting's
    # is: a note after it on the line stays. Where it is not one line of YAML, it is left.
    rest = line[0][1:]
    inner = rest[1:] if rest[:1] in (" ", "\t") else rest
    try:
        entry = yaml.compose(inner, Loader=yaml.SafeLoader)
        name, value = entry.value[0]
        made = _replaced(inner, name, value, new)
    except (yaml.YAMLError, AttributeError, IndexError, TypeError, Refused):
        return None
    return text[: line.start()] + made + text[line.end() :]


def _appended(text: str, key: str, new: Any) -> str:
    end = _line_break(text)
    body = text if not text or text.endswith(("\n", "\r")) else text + end
    return f"{body}{key}: {written(new)}{end}"


_VALIDATOR = Draft202012Validator(load_schema("paper"))


def _errors(document: dict) -> set[tuple[str, str]]:
    return {
        ("/".join(str(part) for part in error.absolute_path), error.message)
        for error in _VALIDATOR.iter_errors(document)
    }


def edit(text: str, key: str, new: Any) -> Edited:
    """`text`, a `paper.yaml`, with `key` set to `new`; `Refused` where that cannot be done
    with nothing else changed."""
    if key not in KEYS:
        raise Refused(f"`set` writes {', '.join(KEYS)}, and not `{key}`")
    held = Draft202012Validator(load_schema("paper")["properties"][key])
    wrong = next(iter(held.iter_errors(new)), None)
    if wrong is not None:
        raise Refused(f"`{key}` cannot be {written(new)}: {wrong.message}")
    other = next((name for character, name in _OTHER_BREAKS.items() if character in text), None)
    if other is not None:
        raise Refused(
            f"it holds {other}, which YAML reads as the end of a line where an editor may show "
            "none, so the lines `set` would edit are not the lines YAML reads; take it out, "
            "or write it as an escape between double quotation marks"
        )
    root, scalars = _structure(text)
    before = _loaded(text)
    if key in before and before[key] == new:
        return Edited(text, "unchanged", before[key])
    present = [
        (name, value)
        for name, value in (root.value if root is not None else ())
        if isinstance(name, yaml.ScalarNode) and name.value == key
    ]
    if present:
        tries = [("replaced", _replaced(text, *present[0], new))]
    else:
        uncommented = _uncommented(text, key, new, scalars)
        tries = [("uncommented", uncommented)] if uncommented is not None else []
        # Where the commented line stands inside another setting's block, made a setting it
        # would end that block: it is left, and the setting is added at the end instead.
        tries.append(("appended", _appended(text, key, new)))
    expected = {**before, key: new}
    for how, candidate in tries:
        try:
            after = _loaded(candidate)
            _structure(candidate)
        except Refused:
            continue
        if after == expected:
            written_as = how
            break
    else:
        raise Refused(
            f"the file, written, would not read back as its settings with only `{key}` "
            "changed; edit it by hand"
        )
    added = _errors(after) - _errors(before)
    if added:
        where, said = sorted(added)[0]
        raise Refused(f"the schema would refuse the file: {where or '(root)'}: {said}")
    return Edited(candidate, written_as, before.get(key))


# --------------------------------------------------------------------------- the file


def read(path: Path) -> tuple[str, str]:
    """The text of `paper.yaml` with its line endings as they are, and a byte-order mark
    taken off and given apart."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise Refused(f"it cannot be read: {exc.strerror or exc}") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        said = _not_utf8(data, exc)[0].replace("cannot read as", "it cannot be read as", 1)
        raise Refused(said) from exc
    return (_BOM, text[1:]) if text.startswith(_BOM) else ("", text)


def write(path: Path, text: str) -> None:
    """Replace `path` by `text` at once: a file in the same folder, then a rename over it,
    so that a reader sees the old file or the new one and never half of one."""
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".paper.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(text.encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        # `mkstemp` makes the file readable by its owner only: the old file's mode is kept.
        shutil.copymode(path, temporary)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _one_file(path: Path) -> None:
    """Refuse a `paper.yaml` that is a link: replacing it would write a file of its own in
    its place, and the file it points to, or shares its contents with, would keep the old
    text."""
    if path.is_symlink():
        raise Refused(
            "it is a symbolic link, which `set` would replace by a file; run it on the file "
            "the link points to"
        )
    try:
        links = path.stat().st_nlink
    except OSError:
        return  # `read` says why it cannot be read
    if links > 1:
        raise Refused(
            "it has more than one hard link, and `set` would write a new file under this "
            "name only; edit it by hand"
        )


def value_of(key: str, words: list[str]) -> Any:
    """What the words given on the command line set `key` to."""
    for word in words:
        if not word or word != word.strip() or not word.isprintable():
            raise Refused(
                f"{word!r} is not a name: a value is one line of text, with no space before "
                "or after it"
            )
    if key in LIST_KEYS:
        twice = sorted({word for word in words if words.count(word) > 1})
        if twice:
            raise Refused(f"{', '.join(twice)} is given twice")
        return list(words)
    if len(words) != 1:
        raise Refused(f"`{key}` takes one value, and {len(words)} were given")
    return words[0]


def journals(root: Path) -> list[str]:
    """The journals `target_journal` can name: each profile the project or the toolkit
    holds, and each profile the shortlist gives one of its candidates."""
    from manuscript_guard.contracts import ContractError, Project, read_structured
    from manuscript_guard.gates.journal import available_profiles
    from manuscript_guard.shortlist import shortlist_path

    project = Project(root, {}, None)  # neither reads a setting
    named = set(available_profiles(project))
    try:
        shortlist = read_structured(shortlist_path(project))
    except ContractError:
        shortlist = None  # the shortlist's own check says what is wrong with it
    candidates = shortlist.get("candidates") if isinstance(shortlist, dict) else None
    for candidate in candidates if isinstance(candidates, list) else ():
        profile = candidate.get("profile") if isinstance(candidate, dict) else None
        if isinstance(profile, str) and profile:
            named.add(profile)
    return sorted(named)


def _choices(root: Path, key: str) -> list[str] | None:
    """The values `key` may take in this project, or None where any name will do."""
    from manuscript_guard.policy import STAGES

    if key == "stage":
        return list(STAGES)
    if key == "target_journal":
        return journals(root)
    if key in ("english_variant", "study_type"):
        return list(load_schema("paper")["properties"][key]["enum"])
    return None


def set_key(path: Path, key: str, words: list[str]) -> Edited:
    """Set `key` of the `paper.yaml` at `path` from the words given, and write the file;
    `Refused`, with the file as it was, where that cannot be done."""
    new = value_of(key, words)
    # Before the file is read: the choices are the policy's, the schema's, and for a
    # journal the profiles and the shortlist of the project, none of them in paper.yaml.
    choices = _choices(path.parent, key)
    if choices is not None and new not in choices:
        said = (
            f"it takes one of {', '.join(choices)}"
            if choices
            else "no journal profile is in this project or the toolkit, and the shortlist "
            "names none"
        )
        if key == "target_journal":
            said += (
                f"; start a profile with `manuscript-guard journal --template {new}`, or give "
                "the journal's candidate in journals/shortlist.yaml its `profile`"
            )
        raise Refused(f"`{key}` cannot be {new!r}: {said}")
    _one_file(path)
    mark, text = read(path)
    done = edit(text, key, new)
    if done.how != "unchanged":
        try:
            write(path, mark + done.text)
        except OSError as exc:
            raise Refused(f"it could not be written: {exc.strerror or exc}") from exc
    return done


__all__ = [
    "KEYS",
    "LIST_KEYS",
    "Edited",
    "Refused",
    "edit",
    "journals",
    "read",
    "set_key",
    "value_of",
    "write",
]
