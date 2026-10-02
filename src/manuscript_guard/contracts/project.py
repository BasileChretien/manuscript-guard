"""Project discovery and the paper/authors configuration.

A project is any directory containing `paper.yaml`. Commands walk upwards to find it, so
they work from anywhere inside the tree, the way git does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import (
    ContractError,
    load_schema,
    read_structured,
    validate,
)
from manuscript_guard.findings import Finding, Report, merge_all

PAPER_FILE = "paper.yaml"
AUTHORS_FILE = "authors.yaml"

DEFAULT_PATHS = {
    "analysis": "analysis",
    "results": "results",
    "literature": "literature",
    "manuscript": "manuscript",
    "figures": "figures",
    "build": "build",
}


@dataclass(frozen=True)
class Project:
    root: Path
    paper: dict
    authors: dict | None

    def path(self, which: str) -> Path:
        configured = self.paper.get("paths", {}).get(which, DEFAULT_PATHS[which])
        return self.root / configured

    def setting(self, key: str) -> Any:
        """What a gate reads of one key of `paper.yaml`: its value as far as the schema
        accepts it. Of a list, and of settings under a key, the entries the schema accepts;
        of anything else, the value or None.

        The schema reports a wrong shape as a finding that names the key and fails at every
        stage, and the gate that read the value raised on it all the same: `terms: 5` was
        also "G2 could not run: TypeError: 'int' object is not iterable", under a hint that
        begins with a bug in the tool. So a gate reads only what the schema let through and
        runs as if the rest were not set. An entry of `conventions` or `terms` that is not
        read exempts nothing, so that reading is the stricter one. A `rounds_required` that
        is not read is the default, which can be fewer rounds than was meant: `"3"` in
        quotes was read as three. The schema's finding stands in either case.

        Entry by entry, because one mistake should not take what is right with it: a
        convention written correctly beside one that is not, or the rounds a paper asks for
        beside a mistyped key.
        """
        if key not in self.paper:
            return None
        return _accepted(load_schema("paper")["properties"][key], self.paper[key])

    @property
    def keywords(self) -> tuple[str, ...]:
        """The keywords as the build prints them: each entry of the list as text, and none
        where `keywords` is not a list.

        Not through `setting`. A build under `--skip-checks` prints what the author typed,
        and `2019`, which YAML reads as a number, was printed before: it must not leave the
        document without a word. What changes is what raised or was garbled: `keywords: 5`
        ended the build in `TypeError`, and one word where a list is expected was printed
        letter by letter.
        """
        value = self.paper.get("keywords")
        return tuple(str(entry) for entry in value) if isinstance(value, list) else ()

    @property
    def english_variant(self) -> str:
        return self.paper.get("english_variant", "en-GB")

    @property
    def target_journal(self) -> str | None:
        return self.paper.get("target_journal")

    @property
    def reporting_guidelines(self) -> tuple[str, ...]:
        return tuple(self.setting("reporting_guideline") or ())

    @property
    def extra_conventions(self) -> tuple[dict, ...]:
        """The conventions a classifier can be built from: those the schema accepts, less
        any whose pattern does not compile, which `load_project` reports."""
        return tuple(
            entry
            for entry in self.setting("conventions") or ()
            if _not_a_pattern(entry["pattern"]) is None
        )

    @property
    def extra_terms(self) -> tuple[str, ...]:
        return tuple(self.setting("terms") or ())


def _accepted(schema: dict, value: Any) -> Any:
    """`value` as far as `schema` accepts it; see `Project.setting`."""
    kind = schema.get("type")
    if kind == "array":
        if not isinstance(value, list):
            return None
        accepts = Draft202012Validator(schema["items"]).is_valid
        return [entry for entry in value if accepts(entry)]
    if kind == "object":
        if not isinstance(value, dict):
            return None
        known = schema.get("properties", {})
        return {
            name: entry
            for name, entry in value.items()
            if name in known and Draft202012Validator(known[name]).is_valid(entry)
        }
    return value if Draft202012Validator(schema).is_valid(value) else None


def _not_a_pattern(pattern: str) -> str | None:
    """Why a convention's pattern cannot be compiled, or None where it can."""
    try:
        re.compile(pattern, re.MULTILINE)
    except Exception as exc:  # noqa: BLE001 - whatever the compiler raises is about the pattern
        # Not only its own error. `(?a)(?u)x` is a `ValueError`, a repeat too large an
        # `OverflowError`. This runs where the project is loaded, before any gate, so one
        # that got past ended every command in a traceback and the hooks in silence.
        return str(exc)
    return None


def _patterns(paper: dict, path: Path) -> Report:
    """A finding for each convention whose pattern is not a regular expression.

    The schema can only say that a pattern is text. One that does not compile raised where
    the classifier was built, so it was "G2 could not run: error: unterminated character set
    at position 0" with no entry named, and a traceback from `explain` and `bind`. Said
    here, under the schema's code, which fails at every stage, and the entry is not read.
    """
    conventions = paper.get("conventions")
    findings = []
    for index, entry in enumerate(conventions if isinstance(conventions, list) else ()):
        pattern = entry.get("pattern") if isinstance(entry, dict) else None
        why = _not_a_pattern(pattern) if isinstance(pattern, str) else None
        if why is None:  # it compiles, or it is not text, which is the schema's to report
            continue
        findings.append(
            Finding(
                gate="G0",
                code="schema-violation",
                message=f"conventions/{index}/pattern: {pattern!r} is not a regular "
                f"expression: {why}",
                path=path,
                hint="a pattern is a Python regular expression; a bracket meant as a "
                "character is written with a backslash before it",
            )
        )
    return Report(tuple(findings))


def find_root(start: Path) -> Path:
    """Walk upwards for the directory holding paper.yaml."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / PAPER_FILE).exists():
            return candidate
    raise ContractError(
        f"no {PAPER_FILE} found in {start} or any parent directory; "
        f"run `manuscript-guard init` to create a project"
    )


def _held(value: object) -> str:
    """What YAML made of a value, in the words an author would use for it."""
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "a yes or no"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "settings"
    return "something else"


def _settings(paper: object, path: Path) -> dict:
    """The parsed `paper.yaml`, once it is known to be what `Project` reads it as.

    The schema reports a wrong shape as a finding, but `Project` is asked where the results
    are before there is a report to print, and a list or a line of text has no `paths` to
    ask: `check` ended in `AttributeError`, the finding was never seen, and the hooks took
    the traceback for a fault of the tool. So the two things every command needs of this
    file are held here, and said in a sentence: that it is settings, and that each folder it
    names is named in text. Everything else in it is still the schema's to report.
    """
    if paper is None:  # an empty file: nothing set yet, and the schema says what to add
        return {}
    if not isinstance(paper, dict):
        cause = (
            " (a line such as `title:My paper`, with no space after the colon, is read as text)"
            if isinstance(paper, str)
            else ""
        )
        raise ContractError(
            f"{path}: holds {_held(paper)} where the settings of the paper are expected, "
            f"one `key: value` to a line{cause}"
        )
    if "paths" not in paper:
        return paper
    paths = paper["paths"]
    if not isinstance(paths, dict):
        raise ContractError(
            f"{path}: `paths` holds {_held(paths)} where a folder is expected for each name "
            f"it changes, as in `results: output`, indented on a line of its own"
        )
    for which in DEFAULT_PATHS:
        if which in paths and not isinstance(paths[which], str):
            raise ContractError(
                f"{path}: `paths.{which}` holds {_held(paths[which])} where the name of a "
                f"folder is expected, as in `{which}: {DEFAULT_PATHS[which]}`"
            )
    return paper


def load_project(start: Path | None = None) -> tuple[Project, Report]:
    root = find_root(start or Path.cwd())
    reports: list[Report] = []

    paper_path = root / PAPER_FILE
    paper = _settings(read_structured(paper_path), paper_path)
    reports.append(validate(paper, "paper", paper_path))
    reports.append(_patterns(paper, paper_path))

    authors_path = root / AUTHORS_FILE
    authors = read_structured(authors_path)
    if authors is not None:
        # A distinct code, because an unfinished author block is a to-do rather than a
        # broken contract, and the stage policy defers it until the manuscript exists.
        reports.append(validate(authors, "authors", authors_path, code="authors-incomplete"))

    return Project(root, paper, authors), merge_all(reports)
