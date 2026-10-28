"""`deposit --reserve-doi`, `--stage` and `--publish`: what is sent, and only when asked.

- `--reserve-doi` (Zenodo) makes a draft with its DOI reserved and records it. For a release
  at Zenodo itself, the DOI is then written into `paper.yaml` as `package.doi`, every comment
  kept (`paper_edit.set_package_doi`), once the author says yes at the terminal or gave
  `--yes`. A DOI of the sandbox is a test DOI and is never written there.
- `--stage` stages the bundle as `deposit` does, every check of it first, then sends it: to
  the Zenodo draft the DOI was reserved for, or as a private OSF project. Each file's md5 is
  checked against the host's, and the first that differs stops it.
- `--publish` (Zenodo) publishes the draft only when the bundle, planned again now, is the
  one staged, by its digest; the draft holds exactly the files sent; for a release, every
  author's approval is of the manuscript as it stands; and the author, at a terminal, types
  the DOI. `--yes` answers none of that: a record once published cannot be deleted.

Each action is recorded in `deposit/receipts/<target>-<bundle>.yaml` and appended to
`deposit/history.yaml`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from manuscript_guard.contracts.project import Project

from . import osf, receipts, zenodo
from .http import Client, RemoteError, Transport, default_transport

#: The transport every client is given; a test puts its own in its place.
TRANSPORT: Transport = default_transport
#: The targets each action is taken at, and why one is refused elsewhere.
ZENODO = ("zenodo", "zenodo-sandbox")
NO_API = ("arXiv and medRxiv have no interface to send a submission through, and a site is "
          "published with git: the bundle is staged in build/deposit/ for you to upload")


def ask_at_terminal(prompt: str) -> str | None:
    """What the person at the terminal types, or None where nobody is there to ask: standard
    input that is not a terminal is a script's or an agent's, and answers nothing here."""
    stream = sys.stdin
    if stream is None or not stream.isatty():
        return None
    try:
        return input(prompt)
    except EOFError:
        return None


def refusal(args: argparse.Namespace) -> str | None:
    """Why the actions asked cannot be taken at this target, or together, or None."""
    if args.dry_run:
        return ("--dry-run sends nothing, and --reserve-doi, --stage and --publish send: run "
                "the dry run on its own first")  # fmt: skip
    if args.publish and (args.stage or args.reserve_doi):
        return ("--publish is run on its own, once the staged draft has been looked at on the "
                "host's page")  # fmt: skip
    if args.target not in (*ZENODO, "osf"):
        return f"--target {args.target} takes nothing sent by the tool: {NO_API}"
    if args.target == "osf" and args.reserve_doi:
        return f"--reserve-doi at OSF: {osf.REFUSED['reserve']}"
    if args.target == "osf" and args.publish:
        return f"--publish at OSF: {osf.REFUSED['publish']}"
    return None


def _an_id(target: str, found: object) -> bool:
    """Whether a receipt's id is one the host gives, and so safe to put in a URL: Zenodo's a
    number, OSF's letters and digits."""
    if target == "osf":
        return isinstance(found, str) and found.isascii() and found.isalnum()
    return isinstance(found, int) and not isinstance(found, bool)


def _client(target: str) -> Client:
    return osf.client(TRANSPORT) if target == "osf" else zenodo.client(target, TRANSPORT)


def _record(project: Project, receipt: dict, action: str) -> dict:
    on = receipts.now()
    receipt = {**receipt, f"{action}_on": on}
    receipts.write(project, receipt)
    receipts.append_history(project, receipt, action, on)
    return receipt


def _reserve(project: Project, args: argparse.Namespace, api: Client,
             receipt: dict | None) -> dict:  # fmt: skip
    if receipt is not None:
        raise RemoteError(f"a draft was made for this bundle already, {receipt.get('id')} at "
                          f"{receipt.get('host')} with the DOI {receipt.get('doi')} "
                          f"({receipts.RECEIPTS}/{args.target}-{args.bundle}.yaml); a second "
                          "would reserve a second DOI")  # fmt: skip
    draft = zenodo.reserve(api, args.target)
    made = {"target": args.target, "bundle": args.bundle, "host": zenodo.HOSTS[args.target],
            **draft}  # fmt: skip
    made = _record(project, made, "reserved")
    print(f"{api.name} reserved the DOI {draft['doi']} for draft {draft['id']}"
          f"{' (' + draft['page'] + ')' if draft['page'] else ''}.")  # fmt: skip
    _write_doi(project, args, str(draft["doi"]))
    return made


def _write_doi(project: Project, args: argparse.Namespace, doi: str) -> None:
    """`package.doi` written into paper.yaml, for a release at Zenodo itself, once the author
    says yes; never a test DOI."""
    from manuscript_guard.paper_edit import Refused, set_package_doi

    if args.target != "zenodo" or receipts.is_test_doi(doi):
        print(f"{doi} is a test DOI, the sandbox's: it is in the receipt, and never written "
              "into paper.yaml.")  # fmt: skip
        return
    if args.bundle != "release":
        print("It is the plan's DOI, in the receipt: `package.doi` in paper.yaml is the "
              "release's.")  # fmt: skip
        return
    if not args.yes:
        said = ask_at_terminal(f"Write package.doi: {doi} into paper.yaml? Type yes to write "
                               "it: ")  # fmt: skip
        if (said or "").strip().lower() != "yes":
            print(f"paper.yaml is as it was. Name the DOI under `package:` as `doi: {doi}`, so "
                  "that the statement and the package can carry it.")  # fmt: skip
            return
    path = project.root / "paper.yaml"
    try:
        done = set_package_doi(path, doi)
    except Refused as exc:
        print(f"paper.yaml is as it was, since {exc}. Add `doi: {doi}` under `package:` "
              "yourself.")  # fmt: skip
        return
    if done.how != "unchanged":
        print(f"{path}: package.doi is now {doi}; build the package again before staging it, "
              "so that it carries the DOI.")  # fmt: skip


def _files(staged) -> list[tuple[str, bytes]]:
    """What is sent of a staged bundle: its archive, and each file at its top level, which a
    reader opens on the record's page without unpacking anything."""
    top = sorted(path for path in Path(staged.directory).iterdir() if path.is_file())
    return [(staged.archive.name, staged.archive.read_bytes())] + \
        [(path.name, path.read_bytes()) for path in top]  # fmt: skip


class Unfit(RemoteError):
    """The bundle cannot be sent as it is: nothing was sent, and the exit is 2."""


def _metadata(staged) -> dict:
    """The bundle's `.zenodo.json`, read before anything is sent: a draft is described by it,
    and a bundle without one, or with one that is not a JSON object, is not sent at all."""
    path = Path(staged.directory) / ".zenodo.json"
    if not path.is_file():
        raise Unfit("the bundle holds no .zenodo.json to describe the draft by; nothing was "
                    "sent")  # fmt: skip
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise Unfit(f"the bundle's .zenodo.json cannot be read as JSON ({type(exc).__name__}); "
                    "nothing was sent") from None  # fmt: skip
    if not isinstance(document, dict):
        raise Unfit("the bundle's .zenodo.json is not a JSON object; nothing was sent")
    return document


def _built(args: argparse.Namespace) -> tuple[Project, object, str] | int:
    """The bundle staged as `deposit` stages it, and its digest; the exit code where it is
    refused."""
    from ..command import planned, written

    found = planned(args)
    if isinstance(found, int):
        return found
    project, made, every = found
    staged = written(project, made, every)
    if isinstance(staged, int):
        return staged
    return project, staged, receipts.bundle_digest(made.target, made.bundle, made.entries,
                                                   made.signed_as)  # fmt: skip


def _stage(args: argparse.Namespace, api: Client, receipt: dict | None) -> int:
    if receipt is not None and receipt.get("published_on"):
        raise RemoteError(f"the draft was published on {receipt['published_on']}, and a "
                          "published record's files cannot be changed: a new version is made "
                          "on the host's page")  # fmt: skip
    if args.target == "osf" and receipt is not None and receipt.get("private") is False:
        raise osf.not_private(str(receipt.get("id")))
    if args.target == "osf" and receipt is not None:
        raise RemoteError(f"the bundle was sent to OSF project {receipt.get('id')} already; OSF "
                          "keeps a file sent again as a new version of it, which the tool does "
                          "not do: change the files on the project's page")  # fmt: skip
    if args.target in ZENODO and receipt is None:
        raise RemoteError("no draft was made for this bundle yet: reserve its DOI first, "
                          "`--reserve-doi` (it may be given with `--stage`)")  # fmt: skip
    built = _built(args)
    if isinstance(built, int):
        return built
    project, staged, digest = built
    files = _files(staged)
    if args.target == "osf":
        title = f"{project.paper.get('title') or 'Deposit'} ({args.bundle})"
        # Recorded before its answer is judged: the project exists either way, and a run
        # again must not make a second one.
        receipt = _record(project, {"target": args.target, "bundle": args.bundle,
                                    "host": osf.HOSTS["api"], **osf.create(api, str(title))},
                          "created")  # fmt: skip
        if not receipt["private"]:
            raise osf.not_private(receipt["id"])
        sent = osf.upload(api, receipt["id"], files)
    else:
        metadata = _metadata(staged)
        sent = zenodo.upload(api, receipt, files)
        zenodo.compare(api, zenodo.held(api, args.target, receipt["id"]), sent)
        zenodo.describe(api, args.target, receipt, metadata)
    hashes = {name: {"md5": sent[name], "sha256": _sha256(data)} for name, data in files}
    receipt = _record(project, {**receipt, "bundle_sha256": digest, "files": hashes}, "staged")
    where = receipt.get("page") or f"{api.name}, {receipt['id']}"
    print(f"Staged {len(files)} files at {where}, each checked by its md5; nothing is "
          "published.")  # fmt: skip
    if args.target in ZENODO:
        print("Look at the draft on its page, then publish it yourself, at a terminal: "
              f"`manuscript-guard deposit --target {args.target} --bundle {args.bundle} "
              "--publish`.")  # fmt: skip
    return 0


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _approved(project: Project) -> None:
    from manuscript_guard.approvals import check_approvals

    found = check_approvals(project).findings
    if found:
        said = "; ".join(finding.message for finding in found)
        raise RemoteError(f"a release is public with the manuscript's words on its page, and "
                          f"every author approves the manuscript as it stands first: {said}")


def _publish(args: argparse.Namespace, api: Client, receipt: dict | None) -> int:
    from ..command import planned

    if receipt is None or not receipt.get("staged_on"):
        raise RemoteError("nothing was staged for this bundle: `--stage` first")
    if receipt.get("published_on"):
        raise RemoteError(f"it was published on {receipt['published_on']}")
    if receipt.get("publish_sent_on"):
        raise RemoteError(f"a publication was sent on {receipt['publish_sent_on']}, and the "
                          f"host answered: {receipt.get('publish_answer')}. It is not sent "
                          "again: look at the draft's page, where it may be published "
                          "already")  # fmt: skip
    found = planned(args)
    if isinstance(found, int):
        return found
    project, made, _every = found
    now = receipts.bundle_digest(made.target, made.bundle, made.entries, made.signed_as)
    if now != receipt.get("bundle_sha256"):
        raise RemoteError(f"the bundle is not the one staged on {receipt['staged_on']}: a "
                          "file of it has changed since. Stage it again, look at the draft, "
                          "and publish that")  # fmt: skip
    sent = {name: str(held.get("md5")) for name, held in (receipt.get("files") or {}).items()
            if isinstance(held, dict)}  # fmt: skip
    zenodo.compare(api, zenodo.held(api, args.target, receipt["id"]), sent)
    if args.bundle == "release":
        _approved(project)
    doi = str(receipt.get("doi"))
    typed = ask_at_terminal(f"Publishing draft {receipt['id']} at {api.name} makes it public, "
                            f"and it cannot be deleted. Type its DOI, {doi}, to publish it: ")
    if typed is None:
        raise RemoteError("--publish asks the author at a terminal, and there is none here: "
                          "run it yourself, at one")  # fmt: skip
    if typed.strip() != doi:
        raise RemoteError("what was typed is not the draft's DOI; nothing is published")
    return _published(project, api, args, receipt, doi)


def _published(project: Project, api: Client, args: argparse.Namespace, receipt: dict,
               doi: str) -> int:  # fmt: skip
    """Send the publication, and record that it was sent, with the host's answer, before
    anything can raise: a run again must never publish twice."""
    try:
        answer = zenodo.request_publish(api, args.target, receipt)
        fields, problem = zenodo.published(api, receipt, answer)
    except RemoteError as exc:
        fields, problem = {}, str(exc)
    said = problem or f"published, with the DOI {fields.get('doi')}"
    receipt = _record(project, {**receipt, "publish_answer": said}, "publish_sent")
    if problem is not None:
        raise RemoteError(f"the publication was sent, and the host answered: {problem}. It is "
                          "recorded, and not sent again: look at the draft's page")  # fmt: skip
    receipt = _record(project, {**receipt, **{k: v for k, v in fields.items() if v}},
                      "published")  # fmt: skip
    print(f"Published {doi}{' at ' + receipt['page'] if receipt.get('page') else ''}.")
    return 0


def run(args: argparse.Namespace) -> int:
    from manuscript_guard.contracts import load_project

    why = refusal(args)
    if why is not None:
        print(f"manuscript-guard deposit: {why}", file=sys.stderr)
        return 2
    try:
        api = _client(args.target)
    except RemoteError as exc:
        print(f"manuscript-guard deposit: {exc}", file=sys.stderr)
        return 2
    project, _ = load_project(args.path)
    try:
        receipt = receipts.read(project, args.target, args.bundle)
        if receipt is not None and not _an_id(args.target, receipt.get("id")):
            raise receipts.ReceiptError(f"{receipts.RECEIPTS}/{args.target}-{args.bundle}.yaml "
                                        "names no deposit id the host gave")  # fmt: skip
        if args.reserve_doi:
            receipt = _reserve(project, args, api, receipt)
        if args.stage:
            return _stage(args, api, receipt)
        if args.publish:
            return _publish(args, api, receipt)
    except Unfit as exc:
        print(f"manuscript-guard deposit: {exc}", file=sys.stderr)
        return 2
    except (RemoteError, receipts.ReceiptError) as exc:
        print(f"manuscript-guard deposit: {exc}", file=sys.stderr)
        return 1
    return 0


__all__ = ["TRANSPORT", "ask_at_terminal", "refusal", "run"]
