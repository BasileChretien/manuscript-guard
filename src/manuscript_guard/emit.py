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
from manuscript_guard.tables import HEADER_ROW, TABLE_SECTION, problems_in

SCHEMA = "manuscript-guard/results/1"

# A cell that is a number written as text. This is the shape that used to slip through:
# str() accepted it, nothing compared it to anything, and a hand-typed table number was
# indistinguishable from a computed one.
_NUMERIC_TEXT = re.compile(r"^\s*[-+−]?[\d,  ]*\d(?:[.,]\d+)?\s*%?\s*$")

# Numbers inside a composite cell such as "3.84 (2.10 to 7.02)". Each must be traceable.
_NUMBER_IN_TEXT = re.compile(r"\d[\d,  ]*(?:\.\d+)?")

__all__ = ["TABLE_SECTION", "Composed", "Emitter", "read_digest", "sha256_of", "write_digest"]


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
    parts: tuple[tuple[object, int | None, str | None], ...]

    def render(self, where: str) -> tuple[str, list[str]]:
        shown = [
            derive_display(where, value, display, digits) for value, digits, display in self.parts
        ]
        return self.template.format(*shown), shown


@dataclass(frozen=True)
class _Verbatim:
    """Text the emitter itself assembled from structured data, not prose from the script.

    The one thing a cell can be that is neither a number nor typed text. `code_list()`
    builds these by joining a list of codes it was handed, so the cell is emitter output.

    Underscored, because the previous version said "a script cannot make one, which is what
    stops it becoming a way to type anything into a table" and that was simply false: it was
    an ordinary importable dataclass, and `Verbatim("mortality 4281003.55%")` put arbitrary
    fabricated prose into a table that `check` then passed. The name is not the fix — the
    fix is that a verbatim cell now records itself as `{}` filled with its own text, so the
    gate rebuilds it and judges that text like any other. The underscore only stops it
    looking like API.
    """

    text: str


def _part(part: object) -> tuple[object, int | None, str | None]:
    """Normalise one `cell()` argument: a number, `(number, digits)` or `(number, display)`."""
    if not isinstance(part, tuple):
        return (part, None, None)
    if len(part) != 2:
        raise DisplayError(
            f"{part!r}: a cell part is a number, a (number, digits) pair, or a "
            f"(number, display) pair"
        )
    value, second = part
    if isinstance(second, str):
        return (value, None, second)
    return (value, second, None)


def _cell(
    key: str,
    row: int,
    column: int,
    cell: object,
    digits: int | dict | None,
    computed: set[str],
    composed: set[tuple[str, int, int]],
    literals: dict[tuple[str, int, int], str],
    parts_by_cell: dict[tuple[str, int, int], list[str]],
    verbatim: set[tuple[str, int, int]],
) -> str:
    """Format one table cell, refusing a number that was typed rather than computed."""
    where = f"table {key!r} row {row} column {column}"

    if isinstance(cell, Composed):
        text, parts = cell.render(where)
        computed.update(parts)
        composed.add((key, row, column))
        literals[(key, row, column)] = cell.template
        parts_by_cell[(key, row, column)] = list(parts)
        return text
    if isinstance(cell, _Verbatim):
        composed.add((key, row, column))
        literals[(key, row, column)] = ""
        parts_by_cell[(key, row, column)] = []
        verbatim.add((key, row, column))
        return cell.text
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
        # Recorded like a composed cell, because that is what it is: a number the emitter
        # formatted. Only the emitter knew that, so a fragment's plain numeric cells were
        # indistinguishable from typed ones the moment the check moved off the emitter —
        # and the alternative, letting the gate accept any cell that is a single number,
        # would wave through a 9999 typed straight into the file.
        composed.add((key, row, column))
        literals[(key, row, column)] = "{}"
        parts_by_cell[(key, row, column)] = [shown]
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
    # Which cells the emitter itself composed, via `cell()`, keyed by position rather than
    # by the text produced. A typed string and a composed one are the same characters by the
    # time they are checked, so something has to record which was which — and keying on the
    # text meant the exemption was shared: a stale copy-paste of group A's interval into
    # group B's row passed, with group B's own values never used.
    _composed: set[tuple[str, int, int]] = field(default_factory=set, init=False)
    # The literal text of each composed cell's template, keyed the same way. What the
    # emitter formatted is exempt from the emitted-value check; what the script typed
    # around it is not.
    _literals: dict[tuple[str, int, int], str] = field(default_factory=dict, init=False)
    # The rendered parts of each composed cell, so the fragment can publish them. Once the
    # cell check reads a fragment rather than this object, the parts are the only record
    # that the numbers inside a composed template were formatted here.
    _parts: dict[tuple[str, int, int], list[str]] = field(default_factory=dict, init=False)
    # Cells the emitter joined from a published code list, checked against that list.
    _verbatim: set[tuple[str, int, int]] = field(default_factory=set, init=False)
    # Code lists as data, beside the table that prints them: RECORD 6.1 asks for the list,
    # and a list is more useful to a reader and to a later check than its rendering.
    _code_lists: dict[str, list[dict]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.script = Path(self.script).resolve()
        self.root = Path(self.root).resolve() if self.root else find_root(self.script.parent)

    @staticmethod
    def cell(template: str, *parts: object) -> Composed:
        """A table cell composed from numbers, e.g. the ubiquitous "n (%)".

            em.cell("{} ({})", n, (100 * n / total, 1))

        Each part is a number, a `(number, digits)` pair when it needs rounding, or a
        `(number, display)` pair when the number is not written as itself — the same rules
        as `value()`, because they are the same rules. `em.cell("{}", (p, "<0.001"))` is how
        a p-value too small to state goes into a table: the display is checked against the
        value, so it can only say "below 0.001" of something that is.

        Use this rather than an f-string: a formatted string arrives here indistinguishable
        from a typed one, so the emitter has to be the thing that formats it.
        """
        return Composed(template=template, parts=tuple(_part(p) for p in parts))

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
        bounds: str | None = None,
        bound: str | None = None,
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
        if bounds is not None:
            if bound not in ("low", "high"):
                raise ValueError(f"{key!r} declares bounds without bound='low' or 'high'")
            spec["bounds"] = bounds
            spec["bound"] = bound
        self._values[key] = spec

    def interval(
        self,
        key: str,
        point: float,
        low: float,
        high: float,
        *,
        digits: int | None = None,
        unit: str | None = None,
        quoted: bool = True,
    ) -> None:
        """Publish an estimate and its interval as one thing.

            em.interval("ror", 3.8439, 2.1032, 7.0210, digits=2)

        Writes `ror.point`, `ror.ci_low` and `ror.ci_high`, checks that the bounds really do
        bracket the estimate, and records which end each bound is.

        That last part is the point. Three keys named point, ci_low and ci_high are three
        unrelated numbers as far as any check is concerned, so
        `{{results.ror.ci_high}} to {{results.ror.ci_low}}` resolved cleanly, passed every
        gate, and printed "3.84 (95% CI 7.02 to 2.10)". The table path has refused a typed
        composite cell since round two because "a point estimate and its bounds can be
        transposed and still pass"; prose had no equivalent, and for a paper whose result is
        one ratio and one interval that is the sentence that matters.
        """
        if not low <= point <= high:
            raise DisplayError(
                f"{key}: the interval does not bracket the estimate — {low!r} to {high!r} "
                f"around {point!r}. Check the order of the arguments"
            )
        self.value(f"{key}.point", point, digits=digits, unit=unit, quoted=quoted)
        self.value(
            f"{key}.ci_low", low, digits=digits, unit=unit, quoted=quoted,
            bounds=f"{key}.point", bound="low",
        )
        self.value(
            f"{key}.ci_high", high, digits=digits, unit=unit, quoted=quoted,
            bounds=f"{key}.point", bound="high",
        )

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
            # Headers go through `_cell` too. "Exposed (n = 412)" is where a group size is
            # normally written, and a header was `list[str]`, so the only way to put the
            # count there was to type it — which the header check then refused, leaving no
            # way to write an ordinary table header at all. Passing a `Composed` used to
            # fail with "'Composed' object is not iterable" three frames away.
            "columns": [
                _cell(
                    key, HEADER_ROW, column, text, None, self._computed, self._composed,
                    self._literals, self._parts,
                    self._verbatim,
                )
                for column, text in enumerate(columns)
            ],
            "rows": [
                [
                    _cell(
                        key, index, column, cell, digits, self._computed, self._composed,
                        self._literals, self._parts,
                        self._verbatim,
                    )
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

    def code_list(
        self,
        key: str,
        entries: list[dict],
        *,
        caption: str | None = None,
        columns: tuple[str, str, str] = ("Concept", "Coding system", "Codes"),
    ) -> None:
        """The table of codes RECORD 6.1 asks for, built from the lists the analysis used.

            em.code_list("outcome_codes", [
                {"concept": "Hepatic injury", "system": "ICD-10",
                 "codes": ["K71.0", "K71.1", "K71.9"]},
                {"concept": "Hepatic injury", "system": "MedDRA PT",
                 "codes": ["10019663", "10019708"]},
            ])

        RECORD 6.1 requires the code lists to be published, and this toolkit made that
        impossible: a cell reading "10019663, 10019708" was refused as "a number written as
        text", and even spelled out one code per row the numeric codes would not classify,
        because the system that names them is in the next column and the check reads one
        cell at a time. A reporting guideline the toolkit ships could not be complied with
        using the toolkit.

        Passing the codes as a list rather than a string is what makes them traceable: the
        emitter joins them, so the cell is its output rather than the script's prose, and
        the same list is available to the analysis that selected on it. A code list is a
        definition, not a measurement — nothing upstream to check it against — so what is
        worth guaranteeing is that the paper prints the list the code actually used.
        """
        rows: list[list[object]] = []
        structured = []
        for index, entry in enumerate(entries):
            missing = {"concept", "system", "codes"} - set(entry)
            if missing:
                raise DisplayError(
                    f"code list {key!r} entry {index}: missing {', '.join(sorted(missing))}"
                )
            codes = [str(code) for code in entry["codes"]]
            if not codes:
                raise DisplayError(
                    f"code list {key!r} entry {index}: no codes. An empty list published as a "
                    f"definition says the concept matched nothing, which is a finding, not a "
                    f"formatting choice"
                )
            rows.append([str(entry["concept"]), str(entry["system"]), _Verbatim(", ".join(codes))])
            structured.append(
                {"concept": str(entry["concept"]), "system": str(entry["system"]), "codes": codes}
            )

        self.table(key, list(columns), rows, caption=caption)
        self._code_lists[key] = structured

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
            document["tables"] = {
                key: {**spec, **self._composition_of(key)} for key, spec in self._tables.items()
            }
        if self._code_lists:
            # Beside the table that prints them, not instead of it. The table is what
            # RECORD 6.1 asks the reader for; the list is what a later check, or the next
            # study reusing the definition, actually wants.
            document["code_lists"] = dict(self._code_lists)
        return document

    def _composition_of(self, key: str) -> dict:
        """The `composed` block for one table, as the fragment publishes it.

        Without this the check could never move off the emitter: a composed cell and a typed
        one are the same characters by the time anyone reads the file. The literal is the
        part of the template the script typed, and the parts are the displays the emitter
        derived — the only record, once the emitter object is gone, that the numbers inside
        the template were formatted here rather than keyed in.
        """
        entries = []
        for (table, row, column), template in sorted(self._literals.items()):
            if table != key:
                continue
            entry: dict = {"column": column, "template": template}
            if row != HEADER_ROW:
                entry["row"] = row
            parts = self._parts.get((table, row, column))
            if parts:
                entry["parts"] = list(parts)
            if (table, row, column) in self._verbatim:
                entry["codes"] = True
            entries.append(entry)
        return {"composed": entries} if entries else {}

    def _check_composite_cells(self) -> None:
        """Every *claim* inside a text cell must be a value this analysis emitted.

        `table()` refuses a bare numeric string, but a composite one — "3.84 (2.10 to 7.02)"
        — is how a confidence interval is actually written in a results table, and demanding
        three emitted values and a compose step for every row is the friction that gets a
        tool abandoned. So the cell stays a string, and the numbers in it must be numbers
        this fragment published. A typed interval fails; a composed one passes.

        The rule itself lives in `tables.py`, because G2 applies the same one to whatever is
        on disk. Here it raises, naming the call that was just made; there it reports,
        naming a file. One implementation either way: this check has been the only thing
        standing behind "tables are emitted, not written", and it was reachable only from
        the Python emitter.

        Checked at write time rather than in `table()` because it needs every value, and a
        table may legitimately be emitted before the values it quotes.
        """
        known = {spec["display"] for spec in self._values.values()} | self._computed
        known |= {shown.replace(",", "") for shown in known}
        classifier = self._classifier()
        for key, spec in self._tables.items():
            merged = {**spec, **self._composition_of(key)}
            for problem in problems_in(key, merged, known, classifier, self._code_lists):
                raise DisplayError(f"{problem.where}: {problem.message}")

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
