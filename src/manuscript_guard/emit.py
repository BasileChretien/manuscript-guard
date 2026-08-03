"""Writing a results fragment from Python.

The only supported way for an analysis to publish a number. Hand-editing a fragment
defeats the entire toolkit, so this writes the provenance block for you and there is no
API that omits it.

    from manuscript_guard.emit import Emitter

    em = Emitter(__file__, inputs=["data/raw/reports.csv"])
    em.value("cohort.n_total", 12043)
    em.value("ror.main", 3.4211, digits=2)
    em.value("model.aic", 918.2, digits=1, quoted=False)   # intermediate, not for prose
    em.write()
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.contracts.project import find_root
from manuscript_guard.contracts.values import DisplayError, derive_display

SCHEMA = "manuscript-guard/results/1"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


DIGEST_SUFFIX = ".sha256"


def write_digest(fragment: Path) -> Path:
    """Write `<fragment>.sha256` so that hand-editing a results file is detectable.

    Without it, the one file the whole toolkit trusts is the one file nothing checks.

    A sidecar rather than a field inside the fragment, because the digest has to be
    reproducible from every language that can emit results. Canonical-JSON agreement
    between Python and R is delicate — float formatting alone will break it — whereas
    "hash the bytes you just wrote" is the same operation everywhere.

    This detects accidents, not adversaries: anyone editing the fragment can recompute the
    sidecar. The point is that they cannot do it without noticing, so a hand-edit stops
    being something that happens quietly at 23:00 before a deadline.
    """
    digest = sha256_of(fragment)
    path = fragment.with_name(fragment.name + DIGEST_SUFFIX)
    path.write_text(f"{digest}  {fragment.name}\n", encoding="utf-8")
    return path


def read_digest(fragment: Path) -> str | None:
    path = fragment.with_name(fragment.name + DIGEST_SUFFIX)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").split()[0].strip()


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=10, check=False
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


@dataclass
class Emitter:
    """Collects values, then writes one fragment with its provenance.

    Mutable by design: an emitter is a builder used inside a single script run, not a
    value passed around. What it produces is immutable on disk.
    """

    script: str | Path
    inputs: list[str | Path] = field(default_factory=list)
    root: Path | None = None
    _values: dict[str, dict] = field(default_factory=dict, init=False)
    _tables: dict[str, dict] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.script = Path(self.script).resolve()
        self.root = Path(self.root).resolve() if self.root else find_root(self.script.parent)

    def value(
        self,
        key: str,
        value: object,
        *,
        display: str | None = None,
        digits: int | None = None,
        unit: str | None = None,
        quoted: bool = True,
        note: str | None = None,
    ) -> None:
        """Record one value. Raises immediately on a duplicate key or unformattable float."""
        if key in self._values:
            raise ValueError(f"{key!r} emitted twice by {self.script}")
        # Resolve the display string here rather than at read time, so the fragment is
        # self-describing: a figure script in any language reads one field and gets the
        # same string the prose will show. Failing here also puts the error in front of the
        # person who can fix it, while they are running the analysis.
        spec: dict = {"value": value, "display": derive_display(key, value, display, digits)}
        if digits is not None:
            spec["digits"] = digits
        if unit is not None:
            spec["unit"] = unit
        if not quoted:
            spec["quoted"] = False
        if note is not None:
            spec["note"] = note
        self._values[key] = spec

    def table(
        self,
        key: str,
        columns: list[str],
        rows: list[list[object]],
        *,
        caption: str | None = None,
        align: list[str] | None = None,
        quoted: bool = True,
    ) -> None:
        """Record a table. Cells are strings, formatted here rather than in the manuscript.

        Tables are emitted rather than written because a hand-typed table is the single
        most reliable place for a stale number to survive: it is long, it is boring to
        re-read, and nobody diffs it.
        """
        if key in self._tables:
            raise ValueError(f"table {key!r} emitted twice by {self.script}")
        width = len(columns)
        for index, row in enumerate(rows):
            if len(row) != width:
                raise ValueError(
                    f"table {key!r}: row {index} has {len(row)} cells, header has {width}"
                )
        spec: dict = {"columns": list(columns), "rows": [[str(c) for c in row] for row in rows]}
        if caption is not None:
            spec["caption"] = caption
        if align is not None:
            if len(align) != width:
                raise ValueError(f"table {key!r}: align has {len(align)} entries, need {width}")
            spec["align"] = list(align)
        if not quoted:
            spec["quoted"] = False
        self._tables[key] = spec

    def add_input(self, path: str | Path) -> None:
        self.inputs.append(path)

    def _provenance(self) -> dict:
        root = self.root
        assert root is not None
        inputs = []
        for raw in self.inputs:
            path = Path(raw)
            if not path.is_absolute():
                path = root / path
            if not path.exists():
                raise FileNotFoundError(f"declared input does not exist: {path}")
            inputs.append(
                {
                    "path": str(path.relative_to(root)).replace("\\", "/"),
                    "sha256": sha256_of(path),
                    "bytes": path.stat().st_size,
                }
            )

        sha = _git(root, "rev-parse", "HEAD")
        status = _git(root, "status", "--porcelain")
        vcs: dict = {}
        if sha:
            vcs["sha"] = sha
            vcs["dirty"] = bool(status)
            branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
            if branch:
                vcs["branch"] = branch

        return {
            "generated_by": str(Path(self.script).relative_to(root)).replace("\\", "/"),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": {"name": "manuscript-guard", "version": __version__},
            "vcs": vcs,
            "inputs": inputs,
            "session": {
                "language": "Python",
                "version": sys.version.split()[0],
                "platform": platform.platform(),
            },
        }

    def document(self) -> dict:
        document = {
            "schema": SCHEMA,
            "provenance": self._provenance(),
            "values": dict(self._values),
        }
        if self._tables:
            document["tables"] = dict(self._tables)
        return document

    def write(self, path: str | Path | None = None) -> Path:
        """Write the fragment. Defaults to results/<script stem>.json."""
        root = self.root
        assert root is not None
        if path is None:
            results_dir = root / "results"
            results_dir.mkdir(parents=True, exist_ok=True)
            path = results_dir / f"{Path(self.script).stem}.json"
        path = Path(path)
        if not path.is_absolute():
            path = root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.document(), indent=2, ensure_ascii=False, sort_keys=False)
        path.write_text(payload + "\n", encoding="utf-8")
        write_digest(path)
        return path


__all__ = [
    "DIGEST_SUFFIX",
    "DisplayError",
    "Emitter",
    "read_digest",
    "sha256_of",
    "write_digest",
]
