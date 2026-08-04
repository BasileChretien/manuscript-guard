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
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from manuscript_guard import __version__
from manuscript_guard.contracts.project import find_root
from manuscript_guard.contracts.values import DisplayError, check_string_value, derive_display

SCHEMA = "manuscript-guard/results/1"

# A cell that is a number written as text. This is the shape that used to slip through:
# str() accepted it, nothing compared it to anything, and a hand-typed table number was
# indistinguishable from a computed one.
_NUMERIC_TEXT = re.compile(r"^\s*[-+−]?[\d,  ]*\d(?:[.,]\d+)?\s*%?\s*$")

# Numbers inside a composite cell such as "3.84 (2.10 to 7.02)". Each must be traceable.
_NUMBER_IN_TEXT = re.compile(r"\d[\d,  ]*(?:\.\d+)?")

# The heading chain claimed for table text. A table is not a Methods section and not a figure
# legend, so `methods_only` rules must not apply to what is written in one.
TABLE_SECTION = ("Table",)


@dataclass(frozen=True)
class Composed:
    """A cell built from several numbers, formatted by the emitter rather than the script.

    `"77 (12.3)"` and `f"{n} ({pct:.1f})"` are the same string by the time `table()` sees
    them, so no check can tell a computed cell from a typed one. The difference has to be
    made at the API: hand over the numbers and a template, and the emitter does the
    formatting — which is the same reason `display` is resolved at emit time rather than
    read time. Build one with `Emitter.cell()`.
    """

    template: str
    parts: tuple[tuple[object, int | None], ...]

    def render(self, where: str) -> tuple[str, list[str]]:
        shown = [derive_display(where, value, None, digits) for value, digits in self.parts]
        return self.template.format(*shown), shown


def _cell(
    key: str,
    row: int,
    column: int,
    cell: object,
    digits: int | dict | None,
    computed: set[str],
    composed: set[str],
) -> str:
    """Format one table cell, refusing a number that was typed rather than computed."""
    where = f"table {key!r} row {row} column {column}"

    if isinstance(cell, Composed):
        text, parts = cell.render(where)
        computed.update(parts)
        composed.add(text)
        return text
    if isinstance(cell, bool):
        return str(cell)
    if isinstance(cell, (int, float)):
        wanted = digits.get(column) if isinstance(digits, dict) else digits
        try:
            shown = derive_display(where, cell, None, wanted)
        except DisplayError as exc:
            raise DisplayError(
                f"{exc}. Pass `digits=` to table() — an int for every column, or a "
                f"{{column: digits}} mapping"
            ) from exc
        computed.add(shown)
        return shown
    if isinstance(cell, str):
        if _NUMERIC_TEXT.match(cell) and any(ch.isdigit() for ch in cell):
            raise DisplayError(
                f"{where}: {cell!r} is a number written as text. Pass the number itself so "
                f"it is formatted here and traceable to this analysis; a numeric string is "
                f"typed by hand and compared to nothing"
            )
        return cell
    raise DisplayError(f"{where}: cells must be numbers or text, not {type(cell).__name__}")


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
    path.write_text(f"{digest}  {fragment.name}\n", encoding="utf-8", newline="\n")
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
    # Display strings this emitter formatted itself, inside a Composed cell. They are
    # traceable for the same reason an emitted value is: the emitter did the rounding.
    _computed: set[str] = field(default_factory=set, init=False)
    # Cell texts the emitter itself composed, via `cell()`. A typed string and a composed
    # one are the same characters by the time they are checked; only this records which
    # was which.
    _composed: set[str] = field(default_factory=set, init=False)

    def __post_init__(self) -> None:
        self.script = Path(self.script).resolve()
        self.root = Path(self.root).resolve() if self.root else find_root(self.script.parent)

    @staticmethod
    def cell(template: str, *parts: object) -> Composed:
        """A table cell composed from numbers, e.g. the ubiquitous "n (%)".

            em.cell("{} ({})", n, (100 * n / total, 1))

        Each part is a number, or a `(number, digits)` pair when it needs rounding — the
        same rule as `value()`, because it is the same rule. Use this rather than an
        f-string: a formatted string arrives here indistinguishable from a typed one, so
        the emitter has to be the thing that formats it.
        """
        pairs = tuple(
            (part[0], part[1]) if isinstance(part, tuple) else (part, None) for part in parts
        )
        return Composed(template=template, parts=pairs)

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
        same_as: str | None = None,
        label: bool = False,
    ) -> None:
        """Record one value. Raises immediately on a duplicate key or unformattable float.

        `same_as` names another key this one is the same quantity as, and G8 then fails if
        the two ever disagree. Worth using whenever a number has to appear under a second
        key — a headline figure repeated for an abstract, a value recomputed by a second
        script. G8 otherwise notices two keys only while they still *agree*, and goes quiet
        at the moment they diverge.
        """
        if key in self._values:
            raise ValueError(f"{key!r} emitted twice by {self.script}")
        # Resolve the display string here rather than at read time, so the fragment is
        # self-describing: a figure script in any language reads one field and gets the
        # same string the prose will show. Failing here also puts the error in front of the
        # person who can fix it, while they are running the analysis.
        if isinstance(value, str):
            check_string_value(key, value, label=label)
        spec: dict = {"value": value, "display": derive_display(key, value, display, digits)}
        if label:
            spec["label"] = True
        if digits is not None:
            spec["digits"] = digits
        if unit is not None:
            spec["unit"] = unit
        if not quoted:
            spec["quoted"] = False
        if note is not None:
            spec["note"] = note
        if same_as is not None:
            if same_as == key:
                raise ValueError(f"{key!r} declares same_as itself")
            spec["same_as"] = same_as
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
        digits: int | dict[int, int] | None = None,
    ) -> None:
        """Record a table. Cells are formatted here rather than in the manuscript.

        Tables are emitted rather than written because a hand-typed table is the single
        most reliable place for a stale number to survive: it is long, it is boring to
        re-read, and nobody diffs it.

        A numeric cell must be a number, and it is formatted by the same rules as
        `value()` — pass a float and you must say how to round it. What is refused is a
        *numeric string*: `"9999"` typed into a cell was previously passed through `str()`
        and compared to nothing at all, so "tables are emitted, not written" was satisfied
        by *calling* the emitter while the numbers were still typed by hand. Text cells
        (labels, group names, "n/a") are unaffected.
        """
        if key in self._tables:
            raise ValueError(f"table {key!r} emitted twice by {self.script}")
        width = len(columns)
        for index, row in enumerate(rows):
            if len(row) != width:
                raise ValueError(
                    f"table {key!r}: row {index} has {len(row)} cells, header has {width}"
                )
        spec: dict = {
            "columns": list(columns),
            "rows": [
                [
                    _cell(key, index, column, cell, digits, self._computed, self._composed)
                    for column, cell in enumerate(row)
                ]
                for index, row in enumerate(rows)
            ],
        }
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
            # The script's own digest. G1 compared modification times to decide whether an
            # analysis had changed since it last wrote — and an mtime is set by `touch`, so
            # editing the script and stamping the fragment forward made the edit invisible.
            # G1's own docstring says hashes are used "because timestamps lie"; that was
            # true of the inputs and not of the code that read them.
            "generated_by_sha256": sha256_of(Path(self.script)),
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
        self._check_composite_cells()
        document = {
            "schema": SCHEMA,
            "provenance": self._provenance(),
            "values": dict(self._values),
        }
        if self._tables:
            document["tables"] = dict(self._tables)
        return document

    def _check_composite_cells(self) -> None:
        """Every *claim* inside a text cell must be a value this analysis emitted.

        `table()` refuses a bare numeric string, but a composite one — "3.84 (2.10 to 7.02)"
        — is how a confidence interval is actually written in a results table, and demanding
        three emitted values and a compose step for every row is the friction that gets a
        tool abandoned. So the cell stays a string, and the numbers in it must be numbers
        this fragment published. A typed interval fails; a composed one passes.

        Which numbers count as claims is decided by the same classifier the manuscript uses,
        because a table cell is not a different kind of writing: "Age 18-44" and "Grade 3"
        are labels in a table for exactly the reason they are labels in a sentence, and a
        rule that made an author emit `18` as a result would be answered by not using
        tables. One definition of a claim, applied everywhere.

        Checked here rather than in `table()` because it needs every value, and a table may
        legitimately be emitted before the values it quotes.
        """
        from manuscript_guard.classify import UNCLASSIFIED
        from manuscript_guard.text.masking import mask
        from manuscript_guard.text.tokens import find_atoms

        known = {spec["display"] for spec in self._values.values()} | self._computed
        known |= {shown.replace(",", "") for shown in known}
        classifier = self._classifier()

        for key, spec in self._tables.items():
            # Captions and column headers are part of the table and are rendered with it, and
            # neither was looked at: a caption reading "the reporting odds ratio of 12.34
            # (95% CI 8.00 to 19.00)" and a header reading "Hepatic injury (n = 9999)" both
            # went into the document unchecked, and survived a re-signed-fragment edit
            # because `verify` did not compare them either.
            places = [(f"caption of table {key!r}", spec.get("caption") or "")]
            places += [
                (f"table {key!r} column {column} header", text)
                for column, text in enumerate(spec["columns"])
            ]
            places += [
                (f"table {key!r} row {row} column {column}", cell)
                for row, cells in enumerate(spec["rows"])
                for column, cell in enumerate(cells)
            ]

            for where, cell in places:
                # Two or more claims in one cell must have been composed, not typed.
                #
                # Membership of the emitted set is not enough on its own: it says each
                # number came from this analysis, and nothing about which is which. So
                # "ROR 5.12 (95% CI 3.84 to 2.89)" passed when 5.12, 3.84 and 2.89 were all
                # emitted — a point estimate and both bounds, transposed. That is precisely
                # the coincidental-match weakness this design claims not to have.
                #
                # One number is left as a set-membership check: a lone "77" that equals an
                # emitted display has nowhere to be transposed to, and demanding `em.cell()`
                # for every single-value cell would be friction with nothing behind it.
                claims = [
                    atom
                    for atom in find_atoms(cell, mask(cell))
                    if classifier.classify(atom, TABLE_SECTION).kind == UNCLASSIFIED
                ]
                if len(claims) > 1 and cell not in self._composed:
                    raise DisplayError(
                        f"{where}: {cell!r} carries several numbers that were typed rather "
                        f"than composed. Each being an emitted value says nothing about "
                        f"which is which — a point estimate and its bounds can be "
                        f"transposed and still pass. Build it with `em.cell(...)`: "
                        f'em.cell("{{}} ({{}} to {{}})", point, low, high)'
                    )

                for atom in find_atoms(cell, mask(cell)):
                    if atom.text in known or atom.text.replace(",", "") in known:
                        continue
                    # A results table is not a figure legend. Classifying with no section at
                    # all let every `methods_only` rule apply, so `p < 0.001` typed straight
                    # into a cell was accepted as a pre-specified threshold — in the one
                    # place a *reported* p-value is most likely to be written.
                    if classifier.classify(atom, TABLE_SECTION).kind != UNCLASSIFIED:
                        continue
                    raise DisplayError(
                        f"{where}: {atom.text!r} in {cell!r} is not a value this analysis "
                        f"emitted. Build it with `em.cell(...)` so the emitter formats it, "
                        f"or emit {atom.text} as a value of its own"
                    )

    def _classifier(self):
        """The project's classifier when there is a project, the shipped one otherwise."""
        from manuscript_guard.classify import Classifier

        try:
            from manuscript_guard.contracts import load_project

            project, _report = load_project(self.root)
            return Classifier.load(project.extra_conventions, project.extra_terms)
        except Exception:  # noqa: BLE001 - a half-configured project must not stop an analysis
            return Classifier.load()

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
        path.write_text(payload + "\n", encoding="utf-8", newline="\n")
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
