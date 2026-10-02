"""Schema loading and validation, shared by every contract.

Validation errors are turned into findings rather than exceptions so that a project with
three malformed files reports all three, instead of stopping at the first.
"""

from __future__ import annotations

import codecs
import json
from datetime import date, datetime
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from manuscript_guard.findings import Finding, Report

SCHEMA_DIR = Path(__file__).parent / "schemas"


class ContractError(Exception):
    """A contract file could not be used at all: missing, unreadable, unparseable, or of a
    shape that leaves the project nowhere to look. The message is written for the author."""


@cache
def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    if not path.exists():
        raise ContractError(f"no such schema: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _plain(node: Any) -> Any:
    """Turn YAML's native dates back into ISO strings.

    PyYAML helpfully parses `2026-08-03` into a `datetime.date`, which then fails a schema
    that asks for a string with `format: date`. Requiring authors to quote every date would
    be a trap that catches everyone once; normalising here costs nothing and keeps the
    schemas honest about what they describe.
    """
    if isinstance(node, dict):
        return {key: _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(value) for value in node]
    if isinstance(node, (date, datetime)):
        return node.isoformat()
    return node


# Longest first: the UTF-32 little-endian mark begins with the UTF-16 one.
_OTHER_ENCODINGS = (
    (codecs.BOM_UTF32_LE, "UTF-32"),
    (codecs.BOM_UTF32_BE, "UTF-32"),
    (codecs.BOM_UTF16_LE, "UTF-16"),
    (codecs.BOM_UTF16_BE, "UTF-16"),
)


def _not_utf8(path: Path, data: bytes, error: UnicodeDecodeError) -> str:
    """What is wrong with a file that did not decode, and where an author would look for it.

    A byte-order mark names the encoding outright: Windows PowerShell 5 writes UTF-16 for
    `>`, and Notepad for "Unicode". Without one the usual cause is a code page and an
    accented name, and the line it is on is what an editor can be asked for.
    """
    named = next((name for mark, name in _OTHER_ENCODINGS if data.startswith(mark)), None)
    if named:
        what = f"the file is {named}"
    else:
        # Lines as the text below is given them: ended by LF, by CR, or by the two together.
        before = data[: error.start]
        line = before.count(b"\n") + before.count(b"\r") - before.count(b"\r\n") + 1
        what = f"the byte 0x{data[error.start]:02x} on line {line} is not UTF-8"
    return f"{path}: cannot read as UTF-8: {what}. Save the file as UTF-8."


def read_structured(path: Path) -> Any:
    """Read a .json, .yaml or .yml file. Returns None when the file does not exist.

    Whatever stops the file being read is raised as `ContractError`, in a sentence that names
    the file. It is the one error `check` prints and exits 2 on, and the one the hooks pass
    on: a file that was not UTF-8, or that the system would not open, once ended in a
    traceback, which a hook takes for a fault of the tool and meets with silence.
    """
    if not path.exists():
        return None
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"{path}: cannot read: {exc.strerror or exc}") from exc
    try:
        # Line endings as `read_text` gave them, which is what was parsed before.
        text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        raise ContractError(_not_utf8(path, data, exc)) from exc
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return _plain(yaml.safe_load(text))
    except Exception as exc:  # noqa: BLE001 - whatever the parser raises is about this file
        # Not only the parsers' own two errors. `verified_on: 2026-09-31` is a date to YAML
        # until the date is made, and that fails with a plain `ValueError`; a list that holds
        # itself ends in `RecursionError`. Each was a traceback, and silence from the hooks.
        raise ContractError(f"{path}: cannot parse: {exc}") from exc


def validate(
    document: Any, schema_name: str, path: Path, gate: str = "G0", code: str = "schema-violation"
) -> Report:
    """Validate a parsed document, returning one finding per schema violation.

    `code` exists so a contract that is merely unfinished can be told apart from one that is
    malformed. A freshly scaffolded authors.yaml is a to-do list, and failing a build over it
    on day one teaches the author to stop running the check.
    """
    validator = Draft202012Validator(load_schema(schema_name))
    findings = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        findings.append(
            Finding(
                gate=gate,
                code=code,
                message=f"{where}: {error.message}",
                path=path,
                hint=f"see the {schema_name} schema",
            )
        )
    return Report(tuple(findings), {f"{schema_name}_files": 1})
