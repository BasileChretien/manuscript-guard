"""A channel's text as it would be posted, its digests, and an author's approval of it.

`communicate approve --as <author> <channel>` writes `communication/approvals/<channel>.yaml`:
who approved (`by`), when (`on`), the digest of the text (`text_sha256`), of what it attaches
(`attachments_sha256`), and that `communicate check` passed it then (`check_clean`). It
refuses while the check fails the text, the embargo apart, since a text is approved before
the embargo lifts and posted after.

**Who approves** (decision of 2026-10-29, as recommended, Basile to be asked): one author
`authors.yaml` names, the one whose account posts the text. Not every author, since a post
is one person's, under their name; not only the corresponding author, since a co-author
posts from their own account.

**What an approval is of.** `text_sha256` is the digest of the text's file as written, its
line ends made line feeds, and of each post as printed, each binding its display, each
anchor and each comment nothing, and of each image's alternative text as printed. So an
edit of the text, of a value it binds or of an alternative text makes the approval stale;
so does an edit of a file it attaches (`attachments_sha256`). `communicate publish --post`
posts only a text whose approval matches both digests now.

An approval is a person's statement, so the hooks put an agent's `communicate approve` to
the person, and refuse an agent's edit of `communication/approvals/`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path, PurePosixPath

import yaml

from manuscript_guard.communicate import Refused, folder
from manuscript_guard.communicate.adapters.net import IMAGE_TYPES, Image
from manuscript_guard.findings import FAIL, Finding

APPROVALS = "approvals"
SCHEMA = "manuscript-guard/communication-approval/1"
#: What `approve` does not hold against a text: the embargo, which lifts after it is approved.
NOT_HELD = frozenset({"comm-embargo"})
#: The channels whose text is posted by an adapter, and the service each posts to.
POSTED = {"bluesky": "bluesky", "bluesky-thread": "bluesky", "mastodon": "mastodon",
          "mastodon-thread": "mastodon"}  # fmt: skip

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SLOT = re.compile(r"<!--[ \t\n]*write:", re.IGNORECASE)
_SPACE_BEFORE = re.compile(r" ([.,;:!?)])")


@dataclass
class Prepared:
    """A channel's text as `approve` and `publish` read it."""

    channel: str
    path: Path
    raw: str
    posts: list[str]
    images: list[Image]
    language: str
    text_sha256: str
    attachments_sha256: str
    #: The digest of what is posted only: the language it is sent with, each post and each
    #: alternative text as printed, not the file they are printed from, so that a comment
    #: added to it does not change it.
    printed_sha256: str
    #: What the check fails the text with, and what else stops it being posted.
    failures: list[Finding] = field(default_factory=list)
    #: Why it cannot be posted as written, apart from the check: a slot, an image.
    unfit: list[str] = field(default_factory=list)


def text_path(project, channel: str) -> Path:
    from manuscript_guard.communicate.build import known

    if not known(channel):
        raise Refused(f"no channel {channel!r}: name one `communicate build` writes, as the "
                      "file under communication/ is named, `bluesky-thread`")  # fmt: skip
    path = folder(project) / f"{channel}.md"
    if not path.is_file():
        raise Refused(f"{path} does not exist: `communicate build --channels {channel}` "
                      "writes it")  # fmt: skip
    return path


def printed_posts(raw: str, namespace: dict) -> list[str]:
    """Each post of a text as it is posted: each binding its display, each anchor and each
    comment nothing, each line's spaces one, no space before a stop, blank lines one."""
    from manuscript_guard.communicate import texts
    from manuscript_guard.text.placeholders import substitute

    read = texts.read(raw)
    shown = {ref: value.display for ref, value in namespace.items()}
    out = []
    for low, high in read.posts:
        piece = _COMMENT.sub("", substitute(read.blanked[low:high], shown))
        lines = [" ".join(line.split()) for line in piece.split("\n")]
        text = _SPACE_BEFORE.sub(r"\1", "\n".join(lines))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            out.append(text)
    return out


def _digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", "surrogatepass") + b"\x00")
    return digest.hexdigest()


def _attached(root: Path, name: object) -> Path | None:
    """The file an attachment names under `communication/`, or None where it names none
    there: an absolute path, or one that climbs out."""
    if not isinstance(name, str) or not name.strip():
        return None
    relative = PurePosixPath(name.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or re.match(r"\A[A-Za-z]:", name):
        return None
    return root.joinpath(*relative.parts)


def _attachments(project, front: dict) -> tuple[str, list[tuple[str, Path | None]]]:
    """The digest of what a text attaches, each file's name and bytes, and each attachment
    with the file it is."""
    root = folder(project)
    named = front.get("attachments")
    listed = [one for one in named if isinstance(one, str)] if isinstance(named, list) else []
    found = [(name, _attached(root, name)) for name in listed]
    parts = []
    for name, path in sorted(found, key=lambda one: one[0]):
        held = (hashlib.sha256(path.read_bytes()).hexdigest()
                if path is not None and path.is_file() else "missing")  # fmt: skip
        parts.append(f"{name}\t{held}")
    return _digest(*parts), found


def prepare(project, channel: str) -> Prepared:
    """A channel's text read for approval and posting: its posts as printed, its images
    with their alternative text, its digests, and what fails it."""
    from manuscript_guard.communicate import checking, texts
    from manuscript_guard.contracts._schema import read_text

    path = text_path(project, channel)
    raw = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    context, _report = checking.context_of(project)
    read = texts.read(raw)
    language = read.front.get("language")
    language = language if isinstance(language, str) and language.strip() else "en"
    posts = printed_posts(raw, context.namespace)
    attachments_sha256, attached = _attachments(project, read.front)
    alts = read.front.get("alt") if isinstance(read.front.get("alt"), dict) else {}
    shown = {ref: value.display for ref, value in context.namespace.items()}
    images, unfit, failures = [], [], []
    from manuscript_guard.text.placeholders import substitute

    for name, file in attached:
        if file is None or not file.is_file():
            unfit.append(f"it attaches {name}, which is no file under communication/")
            continue
        if channel not in POSTED:
            continue
        kind = IMAGE_TYPES.get(file.suffix.lower())
        if kind is None:
            unfit.append(f"it attaches {name}, and a post carries only a PNG, JPEG, WebP or GIF "
                         "image: export it as one, attach that, and give its alternative text "
                         "under `alt:`")  # fmt: skip
            continue
        alt = alts.get(name)
        if not isinstance(alt, str) or not alt.strip():
            unfit.append(f"{name} has no alternative text: give it in the front matter, "
                         f"`alt: {{{name}: <what it shows>}}`")  # fmt: skip
            continue
        failures += checking._numbers(context, alt, path)
        failures += checking._bindings(context, alt, path, lambda _at: 1)
        images.append(Image(name, file.read_bytes(), kind,
                            " ".join(substitute(alt, shown).split())))  # fmt: skip
    unfit += _too_much(channel, images)
    if _SLOT.search(raw):
        unfit.append("a slot is still to write (`<!-- write: … -->`): fill it, or take it out")
    if channel in POSTED and not posts:
        unfit.append("it holds nothing to post")
    text_sha256 = _digest(raw, *posts, *(image.alt for image in images))
    # The language as it is sent: the same words under another language are another post.
    printed_sha256 = _digest(language, str(len(posts)), *posts,
                             *(image.alt for image in images))  # fmt: skip
    failures += _failures(project, path, attached, checking)
    return Prepared(channel, path, raw, posts, images, language, text_sha256,
                    attachments_sha256, printed_sha256, failures, unfit)  # fmt: skip


def _too_much(channel: str, images: list[Image]) -> list[str]:
    """Where a post carries more images than its service takes, or one larger."""
    from manuscript_guard.communicate.adapters import bluesky

    out = []
    if len(images) > bluesky.MAX_IMAGES:
        out.append(f"it attaches {len(images)} images, and a post carries "
                   f"{bluesky.MAX_IMAGES} at most")  # fmt: skip
    if POSTED.get(channel) == "bluesky":
        out += [f"{image.name} is {len(image.data)} bytes, and Bluesky takes an image of "
                f"{bluesky.MAX_IMAGE_BYTES} at most: make it smaller"
                for image in images if len(image.data) > bluesky.MAX_IMAGE_BYTES]  # fmt: skip
    return out


def _failures(project, path: Path, attached: list, checking) -> list[Finding]:
    """What `communicate check` fails that bears on this text: its own failures, the
    brief's and paper.yaml's, and the graphical abstract's where it attaches a file of it;
    not another text's."""
    from manuscript_guard.communicate import graphical_abstract_folder

    root = folder(project).resolve()
    drawing = graphical_abstract_folder(project).resolve()
    attaches_drawing = any(file is not None and drawing in file.resolve().parents
                           for _name, file in attached)  # fmt: skip
    mine = path.resolve()
    out = []
    for one in checking.check(project).failures:
        where = Path(one.path).resolve() if one.path is not None else None
        if where is not None and where != mine:
            if where.parent == root and where.suffix == ".md":
                continue  # another text's
            if (drawing == where or drawing in where.parents) and not attaches_drawing:
                continue
        out.append(one)
    return out


def blocking(prepared: Prepared, *, embargo: bool) -> list[str]:
    """Why the text cannot be approved (`embargo` False) or posted (True), as sentences."""
    said = [f"{one.code}: {one.message}" for one in prepared.failures
            if one.severity == FAIL and (embargo or one.code not in NOT_HELD)]  # fmt: skip
    return said + prepared.unfit


# ------------------------------------------------------------------------- the approval


def approval_path(project, channel: str) -> Path:
    return folder(project) / APPROVALS / f"{channel}.yaml"


def approve(project, channel: str, said_author: str) -> Path:
    """Write the named author's approval of a channel's text as it stands."""
    from manuscript_guard.approvals import NoSuchAuthor, find_author, name_of
    from manuscript_guard.communicate import lifecycle, require_enabled

    require_enabled(project)
    try:
        author = find_author(project, said_author)
    except NoSuchAuthor as exc:
        raise Refused(str(exc)) from None
    prepared = prepare(project, channel)
    stops = blocking(prepared, embargo=False)
    if stops:
        raise Refused(f"{prepared.path.name} is not approved while it cannot be posted as it "
                      "stands: " + "; ".join(stops[:5])
                      + ("; and more: `communicate check` lists them" if len(stops) > 5
                         else ""))  # fmt: skip
    record = {
        "schema": SCHEMA,
        "channel": channel,
        "by": name_of(author),
        **({"orcid": str(author["orcid"])} if author.get("orcid") else {}),
        "on": lifecycle.now().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "text_sha256": prepared.text_sha256,
        "attachments_sha256": prepared.attachments_sha256,
        "check_clean": True,
    }
    path = approval_path(project, channel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((
        "# Written by `manuscript-guard communicate approve`: this author's approval of the\n"
        f"# text of {channel}, bound to it as it stood. Approve again after a change; never\n"
        "# edit by hand.\n" + yaml.safe_dump(record, sort_keys=False, allow_unicode=True)
    ).encode("utf-8"))  # fmt: skip
    return path


def current_approval(project, prepared: Prepared) -> dict:
    """The approval of the text as it stands; `Refused` where there is none, or it is of
    another text, or by nobody `authors.yaml` lists."""
    from manuscript_guard.approvals import authors_of, name_of

    path = approval_path(project, prepared.channel)
    how = f"`manuscript-guard communicate approve --as <author> {prepared.channel}`"
    if not path.is_file():
        raise Refused(f"nobody has approved {prepared.path.name}: the author whose account posts "
                      f"it reads it and runs {how}")  # fmt: skip
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        document = None
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise Refused(f"{path} is no approval this can read: approve the text again, {how}")
    if document.get("by") not in {name_of(one) for one in authors_of(project)}:
        raise Refused(f"{path} is by {document.get('by')!r}, whom authors.yaml does not list: "
                      f"approve it again as an author, {how}")  # fmt: skip
    changed = [what for what, key in (("the text, a value it binds or an alternative text",
                                       "text_sha256"),
                                      ("a file it attaches", "attachments_sha256"))
               if document.get(key) != getattr(prepared, key)]  # fmt: skip
    if changed:
        raise Refused(f"{document['by']} approved {prepared.path.name} on {document.get('on')}, "
                      f"and {' and '.join(changed)} has changed since: the approval is stale. "
                      f"They read it again and approve it as it stands, {how}")  # fmt: skip
    if document.get("check_clean") is not True:
        raise Refused(f"{path} does not say the check passed the text: approve it again, {how}")
    return document
