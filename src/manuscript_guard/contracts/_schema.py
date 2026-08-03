"""Schema loading and validation, shared by every contract.

Validation errors are turned into findings rather than exceptions so that a project with
three malformed files reports all three, instead of stopping at the first.
"""

from __future__ import annotations

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
    """A contract file could not be read at all (missing, unparseable)."""


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


def read_structured(path: Path) -> Any:
    """Read a .json, .yaml or .yml file. Returns None when the file does not exist."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return _plain(yaml.safe_load(text))
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
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
