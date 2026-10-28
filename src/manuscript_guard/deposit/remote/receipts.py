"""What a host answered when the author sent it something: the receipt of each bundle, and the
history of every action.

`deposit/receipts/<target>-<bundle>.yaml` is the one deposit of that bundle at that place: the
host, the deposit's id there, its DOI, the date of each action, and the digests of the files
sent and of the bundle they were staged from. It is what `--stage` and `--publish` read back,
and what G4 holds `package.doi` to. `deposit/history.yaml` is each action, one entry
appended at a time and never rewritten. Both are the tool's to write, and the hooks refuse an
edit of either by an agent (`hooks.FORBIDDEN`). Neither holds a token, a link with one in
it, or anything a host said that is not an identifier.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from pathlib import Path

import yaml

from manuscript_guard.contracts.project import Project

from ..plan import Entry
from ..write import MANIFEST

HOME = "deposit"
RECEIPTS = "deposit/receipts"
HISTORY = "deposit/history.yaml"
#: The prefix DataCite gives test DOIs, which Zenodo's sandbox mints: never a paper's DOI.
TEST_PREFIX = "10.5072/"
_DOI = re.compile(r"^10\.\d{4,9}/\S+$")


class ReceiptError(Exception):
    """A receipt that cannot be read as the tool wrote it."""


def receipt_path(project: Project, target: str, bundle: str) -> Path:
    return project.root / RECEIPTS / f"{target}-{bundle}.yaml"


def read(project: Project, target: str, bundle: str) -> dict | None:
    """The receipt of the bundle at the target, or None where nothing was sent there yet."""
    path = receipt_path(project, target, bundle)
    if not path.is_file():
        return None
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ReceiptError(f"{path.name} cannot be read: {exc}") from None
    if not isinstance(document, dict) or document.get("target") != target \
            or document.get("bundle") != bundle:  # fmt: skip
        raise ReceiptError(f"{RECEIPTS}/{path.name} is not the receipt the tool wrote for "
                           f"{target} and {bundle}")  # fmt: skip
    return document


def every(project: Project) -> list[dict]:
    """Every receipt that reads, in the order of their names."""
    folder = project.root / RECEIPTS
    found = []
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else ():
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        if isinstance(document, dict) and f"{document.get('target')}-" \
                f"{document.get('bundle')}" == path.stem:  # fmt: skip
            found.append(document)
    return found


def now() -> str:
    """When an action was taken, in UTC to the second: a receipt records the day the host
    answered, which only the clock can say."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bundle_digest(target: str, bundle: str, entries: tuple[Entry, ...],
                  signed_as: tuple[tuple[str, str], ...] = ()) -> str:  # fmt: skip
    """The bundle as its files and their digests, as the custodian signs it: MANIFEST.yaml
    left out, since it names the commit and whether the tree is clean, which writing the
    receipt changes, and every file it lists is here by its own digest."""
    by_source = dict(signed_as)
    listed = sorted((entry.path, by_source.get(entry.path, entry.sha256)) for entry in entries
                    if entry.path != MANIFEST)  # fmt: skip
    text = "".join(f"{sha}  {path}\n" for path, sha in listed)
    return hashlib.sha256(f"{target}\n{bundle}\n{text}".encode()).hexdigest()


def _dump(document: dict) -> str:
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)


def write(project: Project, receipt: dict) -> Path:
    """Write the receipt, replacing the one there: a file beside it, then a rename."""
    path = receipt_path(project, str(receipt["target"]), str(receipt["bundle"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(("# Written by `manuscript-guard deposit` from what the host "
                           "answered; not edited by hand.\n" + _dump(receipt)).encode())
    temporary.replace(path)
    return path


def append_history(project: Project, receipt: dict, action: str, on: str) -> Path:
    """Append one entry to deposit/history.yaml: what was done, where, and to what."""
    path = project.root / HISTORY
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"on": on, "action": action, "target": receipt["target"],
             "bundle": receipt["bundle"], "host": receipt["host"], "id": receipt.get("id"),
             "doi": receipt.get("doi"),
             "bundle_sha256": receipt.get("bundle_sha256")}  # fmt: skip
    text = _dump([entry])
    with path.open("ab") as out:
        if out.tell() == 0:
            out.write(b"# Every deposit action, appended by `manuscript-guard deposit`; never "
                      b"rewritten.\n")  # fmt: skip
        out.write(text.encode("utf-8"))
    return path


def is_test_doi(doi: object) -> bool:
    return isinstance(doi, str) and doi.lower().startswith(TEST_PREFIX)


def plausible_doi(doi: object) -> bool:
    return isinstance(doi, str) and _DOI.fullmatch(doi) is not None


__all__ = ["HISTORY", "RECEIPTS", "TEST_PREFIX", "ReceiptError", "append_history",
           "bundle_digest", "every", "is_test_doi", "now", "plausible_doi", "read",
           "receipt_path", "write"]  # fmt: skip
