"""`communicate publish <channel> [--post]`: what a text would send, and, when asked, sending it.

**Without `--post` nothing is sent.** It writes the exact bodies of the requests `--post`
would send to `communication/outbox/<channel>.json`, what the service answers and the moment
of posting in angle brackets and no credential, and writes `preview.html` again.

**`--post`** sends a Bluesky or Mastodon text only when every one of these holds, in this
order, and says which does not:

1. the journal's embargo has lifted (`comm-embargo`);
2. `communicate check` fails nothing of the text: its own findings, the brief's and
   paper.yaml's, and the graphical abstract's where the text attaches it; no slot is left to
   write, and each image is one the service takes, with its alternative text;
3. an author's approval of the text as it stands (`approval.py`): its digests now;
4. the text, by its digests, was not posted on that channel before; nor were the same posts,
   as printed, in the same language, with the same files attached (`printed_sha256`), in a
   thread posted whole or abandoned part-way, so that a comment added to the file and
   approved again does not post them twice;
5. no thread on that channel stopped part-way, unless it is this text's, resumed: an edited
   thread posted whole would leave the first one's posts up beside it. `--abandon` records
   that the author leaves the stopped one as it is (the hooks put it to the person).

Then the credentials, from the environment only: `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD`,
or `MASTODON_BASE_URL` and `MASTODON_TOKEN`. Where they are not set, it prints what to paste
where, and exits 0 having posted nothing.

**What was posted** is recorded in `communication/published/<channel>.yaml` as the service
answered it, each post's URI or id and its link, and when; each post as it is posted, and a
post's key before it is sent. A thread that stops part-way (decision of 2026-10-29, as
recommended, Basile to be asked) is recorded as far as it went; posting it again is refused,
and `--post --resume` posts the rest, the first of them replying to the last post recorded.
A post whose answer was lost is asked for by its key first (Bluesky) or sent again with its
`Idempotency-Key` (Mastodon), so that it is not made twice. Mastodon keeps a key for an hour:
past `mastodon.KEY_LIFETIME` after the post was sent, `--resume` refuses until the author has
looked at the account's page and says `--was-posted <link or id>` or `--not-posted`.

LinkedIn's adapter is deferred: `publish linkedin` prints the text to paste. ResearchGate's
steps are by hand: `publish researchgate` prints them, and `--done` records that the author
took them. A press release, a pitch or a newsletter is an e-mail's draft, and nothing sends
one. The hooks refuse an agent's `--post`: it posts in public under the author's name.
"""

from __future__ import annotations

import json
import os
from datetime import timezone
from pathlib import Path

import yaml

from manuscript_guard.communicate import Refused, folder, require_enabled
from manuscript_guard.communicate.adapters import bluesky, linkedin, mastodon, researchgate
from manuscript_guard.communicate.adapters.net import RemoteError
from manuscript_guard.communicate.approval import (
    POSTED,
    blocking,
    current_approval,
    prepare,
)

PUBLISHED = "published"
OUTBOX = "outbox"
PUBLISHED_SCHEMA = "manuscript-guard/communication-published/1"
OUTBOX_SCHEMA = "manuscript-guard/communication-outbox/1"
SERVICES = {"bluesky": bluesky, "mastodon": mastodon}
#: What is not sent by anything here, and why.
BY_HAND = ("nothing posts or sends it: it is yours to paste or to send. A press release, a "
           "pitch and a newsletter are drafts of an e-mail, and nothing sends an e-mail")


def published_path(project, channel: str) -> Path:
    return folder(project) / PUBLISHED / f"{channel}.yaml"


def outbox_path(project, channel: str) -> Path:
    return folder(project) / OUTBOX / f"{channel}.json"


def _now_written() -> str:
    from manuscript_guard.communicate import lifecycle

    return lifecycle.now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------- the record of it


def read_published(project, channel: str) -> dict:
    """What was posted on a channel: every publication, each its digests and its posts.
    `Refused` where the record cannot be read, since then nothing can say what was posted."""
    path = published_path(project, channel)
    if not path.is_file():
        return {"schema": PUBLISHED_SCHEMA, "channel": channel, "publications": []}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        document = None
    if (not isinstance(document, dict) or document.get("schema") != PUBLISHED_SCHEMA
            or not isinstance(document.get("publications"), list)):  # fmt: skip
        raise Refused(f"{path} cannot be read as the record of what was posted, so nothing "
                      "is posted: look at the account's page for what it holds")  # fmt: skip
    return document


def write_published(project, channel: str, document: dict) -> Path:
    path = published_path(project, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = ("# Written by `manuscript-guard communicate publish` from what the service "
            "answered.\n# A post nobody made cannot be recorded by hand; never edit it.\n"
            + yaml.safe_dump(document, sort_keys=False, allow_unicode=True))  # fmt: skip
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(text.encode("utf-8"))
    os.replace(partial, path)
    return path


def _same(entry: object, prepared) -> bool:
    return (isinstance(entry, dict) and entry.get("text_sha256") == prepared.text_sha256
            and entry.get("attachments_sha256") == prepared.attachments_sha256)  # fmt: skip


# ----------------------------------------------------------------------------- the outbox


def write_outbox(project, prepared) -> Path:
    service = POSTED[prepared.channel]
    if service == "bluesky":
        requests = bluesky.planned(prepared.posts, prepared.images, [prepared.language])
    else:
        requests = mastodon.planned(prepared.posts, prepared.images, prepared.language,
                                    prepared.text_sha256, prepared.attachments_sha256)
    document = {
        "schema": OUTBOX_SCHEMA,
        "channel": prepared.channel,
        "service": service,
        "text_sha256": prepared.text_sha256,
        "attachments_sha256": prepared.attachments_sha256,
        "note": "What `communicate publish --post` would send, request by request, and nothing "
                "has been sent. What the service answers, and the moment a post is sent, are "
                "in angle brackets; no credential is written here.",
        "requests": requests,
    }  # fmt: skip
    path = outbox_path(project, prepared.channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return path


def _preview(project) -> Path:
    from manuscript_guard.communicate import build, checking

    context, _report = checking.context_of(project)
    return build.write_preview(project, context)


# ------------------------------------------------------------------------------ publish


def publish(project, channel: str, *, post: bool = False, resume: bool = False,
            done: bool = False, by: str | None = None, was_posted: str | None = None,
            not_posted: bool = False, abandon: bool = False) -> int:  # fmt: skip
    """What `communicate publish` does for one channel; the exit code."""
    require_enabled(project)
    if resume and not post:
        raise Refused("--resume goes with --post: it posts the rest of a thread")
    if was_posted is not None or not_posted:
        _said_of_a_lost_post(channel, resume, was_posted, not_posted)
    if abandon:
        if post or channel not in POSTED:
            raise Refused("--abandon goes alone, with a Bluesky or Mastodon channel: it records "
                          "that a thread stopped part-way is left as it is")  # fmt: skip
        return _abandon(project, channel)
    if done and channel != "researchgate":
        raise Refused("--done records that the author took ResearchGate's steps, and belongs "
                      "to `communicate publish researchgate`")  # fmt: skip
    if channel == "researchgate":
        return _researchgate(project, done, by, post)
    if by is not None:
        raise Refused("--as goes with `communicate approve`, and with `publish researchgate "
                      "--done`")  # fmt: skip
    if channel == "linkedin":
        return _linkedin(project)
    if channel not in POSTED:
        prepare(project, channel)  # refuses a channel that is not, or a text not written
        raise Refused(f"{channel}: {BY_HAND}")
    prepared = prepare(project, channel)
    if not post:
        return _dry(project, prepared)
    return _post(project, prepared, resume, was_posted, not_posted)


def _said_of_a_lost_post(channel: str, resume: bool, was_posted: str | None,
                         not_posted: bool) -> None:  # fmt: skip
    """`Refused` where `--was-posted` or `--not-posted` is given where it says nothing."""
    if not resume:
        raise Refused("--was-posted and --not-posted go with --post --resume: they say what "
                      "became of a post whose answer was lost")  # fmt: skip
    if was_posted is not None and not_posted:
        raise Refused("--was-posted and --not-posted say opposite things: give the one you "
                      "found on the account's page")  # fmt: skip
    if POSTED.get(channel) != "mastodon":
        raise Refused("--was-posted and --not-posted are Mastodon's: Bluesky is asked for a "
                      "post whose answer was lost by its key, and says itself")  # fmt: skip


def _dry(project, prepared) -> int:
    path = write_outbox(project, prepared)
    print(f"wrote {path}: what --post would send, and nothing was sent")
    print(f"wrote {_preview(project)}")
    stops = blocking(prepared, embargo=True)
    if stops:
        print(f"--post would be refused: {stops[0]}"
              + (f"; and {len(stops) - 1} more" if len(stops) > 1 else ""))  # fmt: skip
        return 0
    try:
        approved = current_approval(project, prepared)
    except Refused as exc:
        print(f"--post would be refused: {exc}")
        return 0
    print(f"approved by {approved['by']} on {approved['on']}; the author posts it, at a "
          f"terminal: `manuscript-guard communicate publish {prepared.channel} --post`")
    return 0


def _post(project, prepared, resume: bool, was_posted: str | None = None,
          not_posted: bool = False) -> int:  # fmt: skip
    from manuscript_guard.communicate import lifecycle

    held = lifecycle.embargo_findings(project, prepared.path)
    if held:
        raise Refused(f"{held[0].message}: nothing is posted")
    stops = blocking(prepared, embargo=True)
    if stops:
        raise Refused(f"{prepared.path.name} is not posted while `communicate check` fails it "
                      "or it cannot be posted as written: " + "; ".join(stops[:5]))
    approved = current_approval(project, prepared)
    document = read_published(project, prepared.channel)
    entry = _entry(document, prepared, approved, resume)
    module = SERVICES[POSTED[prepared.channel]]
    if module is mastodon:
        _lost_post(prepared, entry, was_posted, not_posted, lifecycle.now())
    missing = module.missing()
    if missing:
        print(module.manual(prepared.posts, prepared.images), end="")
        verb = "is" if len(missing) == 1 else "are"
        print(f"\nNothing was posted: {' and '.join(missing)} {verb} not set. Set them in the "
              "environment, never in a file, to post it from here; or paste it as above.")
        return 0
    if entry not in document["publications"]:
        document["publications"].append(entry)

    def keep(_entry: dict) -> None:
        write_published(project, prepared.channel, document)

    return _send(project, prepared, module, document, entry, keep,
                 {"was_posted": was_posted, "not_posted": not_posted})


def _lost_post(prepared, entry: dict, was_posted: str | None, not_posted: bool,
               moment) -> None:  # fmt: skip
    """`Refused` where a Mastodon post whose answer was lost cannot be sent again with its key,
    which the instance may no longer keep, and the author has not said what became of it."""
    pending = entry.get("pending")
    if not isinstance(pending, dict):
        if was_posted is not None or not_posted:
            raise Refused(f"no post of {prepared.path.name} is waiting for an answer: "
                          "--was-posted and --not-posted say what became of one")  # fmt: skip
        return
    if was_posted is not None or not_posted or not mastodon.expired(pending, moment):
        return
    when = pending.get("pending_at") or "a moment not recorded"
    channel = prepared.channel
    minutes = int(mastodon.KEY_LIFETIME.total_seconds() // 60)
    raise Refused(
        f"post {pending.get('index')} of {prepared.path.name} was sent to {entry.get('account')} "
        f"on {when} (UTC), and no answer came back. It may have been posted. Mastodon keeps "
        f"the key it was sent with for an hour (taken as {minutes} minutes here), and that has "
        "passed: sent again now, it could be posted twice, so nothing is sent. Look at your "
        f"account's page on {entry.get('account')} for a post made then. If it is there, "
        f"`manuscript-guard communicate publish {channel} --post --resume --was-posted "
        "<its link or id>` records it and posts the rest; if it is not, `manuscript-guard "
        f"communicate publish {channel} --post --resume --not-posted` sends it again, under a "
        "new key")


def _entry(document: dict, prepared, approved: dict, resume: bool) -> dict:
    """The publication the posts are recorded under: a new one, or, with `--resume`, the
    one left part-way; `Refused` where the text, or the same posts, were posted already, or
    another thread on the channel stopped part-way."""
    channel = prepared.channel
    held = [one for one in document["publications"] if isinstance(one, dict)]
    same = [one for one in held if _same(one, prepared)]
    whole = next((one for one in same if one.get("complete") is True), None)
    if whole is not None:
        raise Refused(f"{prepared.path.name} as it stands was posted on {channel} already, on "
                      f"{_when(whole)} ({published_path_name(channel)}); the same text is not "
                      "posted twice")  # fmt: skip
    printed = next((one for one in held if one.get("complete") is True
                    and one.get("printed_sha256") == prepared.printed_sha256
                    and one.get("attachments_sha256") == prepared.attachments_sha256), None)
    if printed is not None:
        raise Refused(f"the posts of {prepared.path.name}, as printed, with the same files "
                      f"attached, were posted on {channel} already, on {_when(printed)} "
                      f"({published_path_name(channel)}): its file has changed since, a comment "
                      "or a note, and nothing it posts; the same posts are not posted twice")
    left = next((one for one in held if one.get("complete") is not True
                 and one.get("abandoned_on")
                 and one.get("printed_sha256") == prepared.printed_sha256
                 and one.get("attachments_sha256") == prepared.attachments_sha256), None)
    if left is not None:
        raise Refused(f"the posts of {prepared.path.name}, as printed, with the same files "
                      f"attached, were begun on {channel} on {left.get('begun_on')}, and that "
                      f"thread was left part-way on {left.get('abandoned_on')} "
                      f"({published_path_name(channel)}): its posts are up, and the same posts "
                      "are not posted twice. Change the text, and approve it again, to post it "
                      "as a new thread")  # fmt: skip
    stopped = [one for one in held if one.get("complete") is not True
               and not one.get("abandoned_on")]  # fmt: skip
    if stopped and not _same(stopped[-1], prepared):
        raise Refused(f"a thread of {channel} begun on {stopped[-1].get('begun_on')} stopped "
                      f"part-way, {len(stopped[-1].get('posts') or [])} of its posts posted "
                      f"({published_path_name(channel)}), and {prepared.path.name} is not "
                      "the text it was begun with: posted whole, it would stand beside the "
                      "first one's posts. Put the text back as it was approved, approve it "
                      f"again, and `communicate publish {channel} --post --resume` posts the "
                      f"rest; or `communicate publish {channel} --abandon` records that the "
                      "stopped thread is left as it is, its posts up, and a new one may "
                      "begin")  # fmt: skip
    partial = next((one for one in same if one.get("complete") is not True
                    and not one.get("abandoned_on")), None)  # fmt: skip
    if partial is not None and not resume:
        posted = len(partial.get("posts") or [])
        raise Refused(f"{posted} of the {len(prepared.posts)} posts of {prepared.path.name} were "
                      f"posted on {partial.get('begun_on')}, and then it stopped "
                      f"({published_path_name(channel)}); it is not posted again whole: "
                      f"`communicate publish {channel} --post --resume` posts the rest, "
                      "replying to the last post recorded")  # fmt: skip
    if partial is not None:
        return partial
    if resume:
        raise Refused(f"no thread of {prepared.path.name} as it stands was left part-way: there "
                      "is nothing to resume")  # fmt: skip
    return {
        "service": POSTED[channel],
        "text_sha256": prepared.text_sha256,
        "attachments_sha256": prepared.attachments_sha256,
        "printed_sha256": prepared.printed_sha256,
        "approved_by": approved["by"],
        "approved_on": approved["on"],
        "begun_on": _now_written(),
        "complete": False,
        "posts": [],
    }


def _when(publication: dict) -> object:
    return (publication.get("posts") or [{}])[0].get("posted_on") or publication.get("begun_on")


def published_path_name(channel: str) -> str:
    return f"communication/{PUBLISHED}/{channel}.yaml"


def _send(project, prepared, module, document: dict, entry: dict, keep,
          lost: dict | None = None) -> int:  # fmt: skip
    from manuscript_guard.communicate import lifecycle

    entry.pop("failure", None)
    try:
        try:
            if module is bluesky:
                bluesky.send(prepared.posts, prepared.images, [prepared.language], entry, keep,
                             lifecycle.now)  # fmt: skip
            else:
                mastodon.send(prepared.posts, prepared.images, prepared.language,
                              (prepared.text_sha256, prepared.attachments_sha256), entry, keep,
                              lifecycle.now, **(lost or {}))  # fmt: skip
        except RemoteError as exc:
            return _stopped(project, prepared, document, entry, keep, exc)
        entry["complete"] = True
        keep(entry)
    except OSError as exc:
        # Whatever was written of the record stays as it is: nothing is written over it.
        print(f"POSTS OF {prepared.path.name} MAY HAVE BEEN MADE, AND THEY COULD NOT BE "
              f"RECORDED ({exc.strerror or type(exc).__name__}). Do not post it again: look at "
              "the account's page first.", flush=True)  # fmt: skip
        return 1
    for one in entry["posts"]:
        print(f"posted {one['index']} of {len(prepared.posts)}: {one.get('url') or one.get('uri')}")
    print(f"recorded in {published_path(project, prepared.channel)}")
    return 0


def _stopped(project, prepared, document: dict, entry: dict, keep, exc: RemoteError) -> int:
    """A request refused or unanswered: what was posted is recorded, and how to go on."""
    posted = len(entry.get("posts") or [])
    channel = prepared.channel
    if posted == 0 and "pending" not in entry:
        # Nothing was sent that can have posted anything: no record is kept of it.
        document["publications"] = [one for one in document["publications"] if one is not entry]
        print(f"nothing was posted: {exc}")
        try:
            if document["publications"] or published_path(project, channel).is_file():
                write_published(project, channel, document)
        except OSError as error:
            print(f"{published_path(project, channel)} could not be written again "
                  f"({error.strerror or type(error).__name__}), so it may still list this "
                  "text as begun, with nothing posted: `manuscript-guard communicate publish "
                  f"{channel} --post --resume` sends it from its first post")  # fmt: skip
            return 1
        return 1
    entry["failure"] = str(exc)
    keep(entry)
    from manuscript_guard.communicate import lifecycle

    resume = f"`manuscript-guard communicate publish {channel} --post --resume`"
    on = (f" {resume} posts the rest, replying to the last post recorded." if "pending" not in entry
          else _lost_said(entry, lifecycle.now(), resume))  # fmt: skip
    print(f"{posted} of the {len(prepared.posts)} posts were posted, and then: {exc}. It is "
          f"recorded in {published_path(project, channel)}.{on}")  # fmt: skip
    return 1


def _lost_said(entry: dict, moment, resume: str) -> str:
    """What becomes of a post sent whose answer was lost, on the service it was sent to, at
    `moment` (on Mastodon, within `KEY_LIFETIME` of its sending or past it), and how to go
    on; `resume` is the command that resumes the thread."""
    pending = entry["pending"]
    index = pending.get("index")
    rest = f" {resume} posts the rest, replying to the last post recorded."
    if entry.get("service") != "mastodon":
        return (f" Post {index} was sent and no answer came back: --resume asks Bluesky for it "
                f"by its key before it sends it again.{rest}")  # fmt: skip
    minutes = int(mastodon.KEY_LIFETIME.total_seconds() // 60)
    when = pending.get("pending_at") or "a moment not recorded"
    if mastodon.expired(pending, moment):
        return (f" Post {index} was sent at {when} (UTC) and no answer came back, more than "
                f"{minutes} minutes ago, so Mastodon may no longer keep the key it was sent "
                "with, and it is not sent again with it. Look at your account's page for a "
                f"post made then. If it is there, {resume[:-1]} --was-posted <its link or id>` "
                f"records it and posts the rest; if it is not, {resume[:-1]} --not-posted` "
                "sends it again, under a new key.")  # fmt: skip
    return (f" Post {index} was sent at {when} (UTC) and no answer "
            f"came back: --resume within {minutes} minutes of that sends it again with the same "
            "Idempotency-Key, and Mastodon answers with the post if it was made. After that, "
            f"--resume asks you to look at the account's page first.{rest}")  # fmt: skip


def _abandon(project, channel: str) -> int:
    """`publish <channel> --abandon`: the thread stopped part-way recorded as left as it is."""
    document = read_published(project, channel)
    stopped = [one for one in document["publications"] if isinstance(one, dict)
               and one.get("complete") is not True and not one.get("abandoned_on")]  # fmt: skip
    if not stopped:
        raise Refused(f"no thread of {channel} stopped part-way: there is nothing to abandon")
    entry = stopped[-1]
    entry["abandoned_on"] = _now_written()
    path = write_published(project, channel, document)
    posted = len(entry.get("posts") or [])
    maybe = ("" if "pending" not in entry else
             f", and post {entry['pending'].get('index')} may have been made too")  # fmt: skip
    print(f"recorded in {path} that the thread begun on {entry.get('begun_on')} is left as it "
          f"is: {posted} of its posts are up{maybe}, and stay up unless you delete them on the "
          f"account's page. `communicate publish {channel} --post` may now post the text as it "
          "stands, as a new thread")  # fmt: skip
    return 0


def _linkedin(project) -> int:
    prepared = prepare(project, "linkedin")
    print(linkedin.manual(prepared.posts, prepared.images), end="")
    stops = blocking(prepared, embargo=True)
    if stops:
        print(f"\nBefore you paste it: {stops[0]}"
              + (f"; and {len(stops) - 1} more (`communicate check`)" if len(stops) > 1 else ""))
    print("\nNothing was posted: LinkedIn's adapter is deferred, with --post or without.")
    return 0


def _researchgate(project, done: bool, by: str | None, post: bool) -> int:
    print(researchgate.steps(project), end="")
    if post:
        print("\nNothing was posted: ResearchGate has no interface a tool may post through.")
    if not done:
        if by is not None:
            raise Refused("--as goes with --done here: who took the steps")
        print("\nOnce you have taken them, `manuscript-guard communicate publish researchgate "
              "--done` records it.")  # fmt: skip
        return 0
    from manuscript_guard.approvals import NoSuchAuthor, find_author, name_of
    from manuscript_guard.communicate.approval import _digest
    from manuscript_guard.contracts._schema import read_text

    text = folder(project) / "researchgate.md"
    if not text.is_file():
        raise Refused(f"{text} does not exist, so there is no text the steps were taken with: "
                      "`communicate build --channels researchgate` writes it")  # fmt: skip
    record = {"done_on": _now_written()}
    if by is not None:
        try:
            record["by"] = name_of(find_author(project, by))
        except NoSuchAuthor as exc:
            raise Refused(str(exc)) from None
    record["text_sha256"] = _digest(read_text(text).replace("\r\n", "\n"))
    document = read_published(project, "researchgate")
    document["publications"].append(record)
    path = write_published(project, "researchgate", document)
    print(f"\nrecorded in {path} that the steps were taken; nothing was sent")
    return 0


def orcid(project) -> int:
    """`communicate orcid`: whether the paper's DOI is on each author's public ORCID record."""
    from manuscript_guard.approvals import authors_of, name_of
    from manuscript_guard.communicate.adapters import orcid as orcid_module
    from manuscript_guard.communicate.status import publication

    require_enabled(project)
    doi = publication(project).get("doi")
    if not doi:
        raise Refused("paper.yaml gives no publication.doi: there is nothing to look for")
    asked = [(name_of(author), orcid_module.bare(str(author["orcid"])))
             for author in authors_of(project) if author.get("orcid")]  # fmt: skip
    if not asked:
        raise Refused("authors.yaml gives no author an ORCID iD: there is no record to read")
    print(orcid_module.render(orcid_module.ask(asked, str(doi)), str(doi)), end="")
    return 0
