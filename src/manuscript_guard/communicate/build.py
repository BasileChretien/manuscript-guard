"""`communicate build [--channels …]`: the texts of each channel written from the brief.

Each channel is written to `communication/<channel>.md` (`drafts.py`), and held to
`communicate check` before it is written: a text the check would fail is not written, and
the build says why, so that what it writes passes as written, apart from its slots. Only
the embargo is not held against it, since a text is drafted before the embargo lifts and
shared after (`comm-embargo` still fails it in the check until then).

What it writes besides:

- `communication/overview.svg`, the overview slide, where the `overview` channel is built;
- `communication/guides/lifecycle.md`, what is shared when (`lifecycle.py`), and
  `communication/guides/researchgate-steps.md`, the steps ResearchGate takes by hand: the
  guides are no texts, and the check does not read them;
- `communication/preview.html`, every text as it would be read (`preview.py`).

A text that exists is not written over without `--force`: it may hold what an author or an
agent wrote into its slots. The guides and the preview are written each time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from manuscript_guard.communicate import Refused, folder, require_enabled
from manuscript_guard.communicate import drafts as drafts_module
from manuscript_guard.communicate.status import OUT, publication
from manuscript_guard.findings import FAIL

#: Who each channel's text is for, and how it is made: by the tool alone, or with slots.
AUDIENCES = {
    "bluesky": "researchers and the public who follow the authors on Bluesky",
    "bluesky-thread": "researchers and the public who follow the authors on Bluesky",
    "mastodon": "researchers and the public who follow the authors on Mastodon",
    "mastodon-thread": "researchers and the public who follow the authors on Mastodon",
    "overview": "the audience of a talk",
    "poster": "the visitors of a conference's poster session",
    "storyboard": "whoever films or animates the summary",
    "data-announcement": "researchers who may reuse the code and the results",
    "linkedin": "colleagues and the profession, on LinkedIn",
    "researchgate": "researchers on ResearchGate",
    "press-release": "journalists, and through them the public",
    "pitch": "one journalist or editor",
    "newsletter": "the readers of a department's or a society's newsletter",
    "plain-language-summary": "the public",
    "plain-language-patients": "patients and their carers",
    "plain-language-clinicians": "clinicians",
    "plain-language-policymakers": "those who decide policy",
    "video-script": "the viewers of a sixty-second video",
}
DETERMINISTIC = ("bluesky", "bluesky-thread", "mastodon", "mastodon-thread", "overview",
                 "poster", "storyboard", "data-announcement")  # fmt: skip
SCAFFOLDED = tuple(drafts_module.SCAFFOLDS)
#: A translation's channel: `translation-` and a language's tag, `translation-ja`.
TRANSLATION = re.compile(r"\Atranslation-(?P<language>[a-z]{2,3}(?:-[a-z0-9]{2,8})*)\Z")
GUIDES = "guides"
PREVIEW = "preview.html"
OVERVIEW = "overview.svg"
#: What the build does not hold against a text it writes: the embargo is the day's, and the
#: text is drafted before it lifts.
NOT_HELD = frozenset({"comm-embargo"})


def known(channel: str) -> bool:
    return channel in AUDIENCES or TRANSLATION.match(channel) is not None


@dataclass
class Built:
    written: list[Path] = field(default_factory=list)
    #: Each channel not written, and why.
    refused: list[tuple[str, str]] = field(default_factory=list)
    #: Each channel whose text exists and was not written over.
    kept: list[str] = field(default_factory=list)
    #: Each channel paper.yaml lists that the build does not write, a blog: the author's.
    passed: list[str] = field(default_factory=list)
    #: Each channel built with the rest and not due, and why: no deposit to announce.
    not_due: list[tuple[str, str]] = field(default_factory=list)


def chosen(project, named: list[str] | None) -> list[str]:
    """The channels to build: those named, else paper.yaml's `communication.channels`, else
    every channel the build writes. A channel named that the build does not write is
    refused; one paper.yaml lists, a blog, is the author's to write, and is passed over."""
    if named:
        wanted = list(dict.fromkeys(named))
        unknown = [one for one in wanted if not known(one)]
        if unknown:
            raise Refused(
                f"no channel {', '.join(unknown)}: the build writes "
                f"{', '.join([*DETERMINISTIC, *SCAFFOLDED])} and translation-<language>"
            )
        return wanted
    setting = project.setting("communication") or {}
    listed = setting.get("channels") if isinstance(setting, dict) else None
    return [one for one in listed if known(one)] if listed else [*DETERMINISTIC, *SCAFFOLDED]


def not_built(project) -> list[str]:
    """The channels paper.yaml lists that the build does not write."""
    setting = project.setting("communication") or {}
    listed = setting.get("channels") if isinstance(setting, dict) else None
    return [one for one in listed or () if not known(one)]


def paper_link(project) -> str | None:
    """The link to the paper, its DOI's or its URL, once it is online; None before."""
    said = publication(project)
    if said.get("status") not in OUT:
        return None
    if said.get("doi"):
        return f"https://doi.org/{said['doi']}"
    return str(said["url"]) if said.get("url") else None


class NotDue(str):
    """Why a channel's text is not due, rather than refused: the data announcement with no
    deposit to announce. Built with the rest, it is passed over; named, it is refused."""


def _package(project) -> tuple[str, list[str]] | str:
    """The deposit's DOI and its licences, or why there is no deposit to announce."""
    from manuscript_guard.deposit.write import MANIFEST

    package = project.setting("package") or {}
    package = package if isinstance(package, dict) else {}
    doi, licence = package.get("doi"), package.get("licence")
    if not doi:
        return NotDue("paper.yaml's package gives no DOI")
    if not licence:
        return NotDue("paper.yaml's package gives no licence")
    if not list((project.path("build") / "package").glob(f"*/{MANIFEST}")):
        return NotDue("there is no deposit's manifest: `manuscript-guard package` writes it")
    licences = [licence] if isinstance(licence, str) else licence
    if not isinstance(licences, list) or not all(
        isinstance(one, str) and _SPDX.fullmatch(one) for one in licences
    ):
        return "paper.yaml's package.licence is not an SPDX identifier, or a list of them"
    return str(doi), list(licences)


#: An SPDX identifier, as paper.yaml's schema takes one.
_SPDX = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")


def _compose(project, channel: str, parts, link: str | None) -> list[tuple[str, dict]] | str:
    """The ways to write a channel's text, the first that passes the check to be written,
    each with what it attaches; or why it cannot be written."""
    from manuscript_guard.communicate import drafts as d
    from manuscript_guard.communicate.checking import channel_rules

    found = TRANSLATION.match(channel)
    language = found["language"] if found is not None else None
    audience = AUDIENCES.get(channel, f"readers of {language}")

    def text(body: str, *, attached: list[str] | None = None, extra: dict | None = None) -> str:
        links = linked(body)
        version = "published" if link and link in links else "none"
        return d.front_matter(channel, audience, version=version, links=links,
                              attachments=attached, extra=extra) + body  # fmt: skip

    if channel_rules(channel).get("limitations") and not parts.limitations:
        return (f"a {channel} states a limitation of the study, and the brief holds none: "
                "write one into it, quoted from the paper, and build again")  # fmt: skip
    if channel in ("bluesky", "mastodon"):
        return [(text(d.post(parts, link, True)), {}), (text(d.post(parts, link, False)), {})]
    if channel in ("bluesky-thread", "mastodon-thread"):
        return [(text(d.thread(parts, link)), {})]
    if channel == "overview":
        return [(text(d.overview_note(), attached=[OVERVIEW]), {OVERVIEW: "overview"})]
    if channel == "poster":
        return [(text(d.poster(parts, str(project.paper.get("title") or ""))), {})]
    if channel == "storyboard":
        return [(text(d.storyboard(parts)), {})]
    if channel == "data-announcement":
        package = _package(project)
        if isinstance(package, str):
            return package
        doi, licences = package
        return [(text(d.announcement(doi, licences, link)), {})]
    if language is not None:
        return [(text(d.translation(parts, language), extra={"language": language}), {})]
    return [(text(d.scaffold(channel, parts, link)), {})]


_URL = re.compile(r"https?://[^\s<>\"]+")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def linked(body: str) -> list[str]:
    """Each link a text's body prints, in order, once: its comments are not printed."""
    found = (one.rstrip(".,;:!?)") for one in _URL.findall(_COMMENT.sub(" ", body)))
    return list(dict.fromkeys(found))


def _attachment(kind: str, brief, context) -> bytes:
    from manuscript_guard.communicate.svg import overview, pointers
    from manuscript_guard.palettes import colours

    palette = colours("okabe-ito")
    shown = {**context.namespace, **pointers(context.project)}
    return overview(brief, [palette[5], palette[1], palette[3]], shown)


def _brief(project):
    from manuscript_guard.communicate import brief as brief_module

    brief, report = brief_module.load(project)
    if brief is None:
        why = report.findings[0].message if report.findings else "there is no brief"
        raise Refused(f"{why}: write it with `communicate brief`, and mark the primary finding")
    if not report.ok:
        raise Refused(f"{brief.path} is not a brief that can be read: {report.findings[0].message}")
    if not brief.primary:
        raise Refused(f"no finding of {brief.path} is marked `primary: true`: every text "
                      "states the primary finding, and which one it is is yours to say")
    # A statement that binds a value nothing emits stops only the texts that carry it: the
    # check fails each of them (`comm-binding-unknown`), and the rest are written.
    return brief


def build(project, channels: list[str] | None = None, *, force: bool = False,
          asked: bool | None = None) -> Built:  # fmt: skip
    """Write each channel's text that passes the check, the guides and the preview.

    `asked` says the person named the channels, so that one not yet due (the data
    announcement with no deposit) is refused; by default, whenever `channels` is given.
    `status --prepare` names the channels its triggers make due, which nobody asked for
    one by one, and passes over one that is not due as a plain build does."""
    asked = bool(channels) if asked is None else asked
    from manuscript_guard.communicate import checking

    require_enabled(project)
    brief = _brief(project)
    wanted = chosen(project, channels)
    context, _report = checking.context_of(project)
    parts = drafts_module.Parts.of(brief)
    link = paper_link(project)
    root = folder(project)
    root.mkdir(parents=True, exist_ok=True)
    built = Built(passed=[] if channels else not_built(project))
    for channel in wanted:
        path = root / f"{channel}.md"
        if path.exists() and not force:
            built.kept.append(channel)
            continue
        ways = _compose(project, channel, parts, link)
        if isinstance(ways, NotDue) and not asked:
            built.not_due.append((channel, str(ways)))
            continue
        if isinstance(ways, str):
            built.refused.append((channel, str(ways)))
            continue
        why = _write_first(channel, ways, path, brief, context, built, force)
        if why:
            built.refused.append((channel, why))
    built.written += write_guides(project)
    built.written.append(write_preview(project, context))
    return built


def _write_first(channel: str, ways: list[tuple[str, dict]], path: Path, brief, context,
                 built: Built, force: bool = False) -> str:  # fmt: skip
    """Write the first way of the text the check passes, with what it attaches; or say why
    none passes."""
    from manuscript_guard.communicate import checking

    why = ""
    for body, attached in ways:
        before, kept = _place(path.parent, attached, brief, context, force)
        failed = [one for one in checking.text_findings(context, path, body)
                  if one.severity == FAIL and one.code not in NOT_HELD]  # fmt: skip
        if not failed:
            path.write_bytes(body.encode("utf-8"))
            built.written += [path, *before]
            built.kept += kept
            return ""
        _unplace(before)
        why = "; ".join(f"{one.code}: {one.message}" for one in failed[:3])
    return why


def _place(root: Path, attached: dict, brief, context, force: bool = False
           ) -> tuple[dict[Path, bytes | None], list[str]]:  # fmt: skip
    """Write what a text attaches, so that the check reads it beside the text; and what
    each file held before, to put back where the text is not written. A file that exists
    is kept without `force`, as a text is: it may have been edited by hand, and the check
    reads it as it stands."""
    placed: dict[Path, bytes | None] = {}
    kept: list[str] = []
    for name, kind in attached.items():
        target = root / name
        if target.exists() and not force:
            kept.append(name)
            continue
        placed[target] = target.read_bytes() if target.is_file() else None
        target.write_bytes(_attachment(kind, brief, context))
    return placed, kept


def _unplace(placed: dict[Path, bytes | None]) -> None:
    for path, was in placed.items():
        if was is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(was)


def write_guides(project) -> list[Path]:
    from manuscript_guard.communicate import guides

    home = folder(project) / GUIDES
    home.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in (("lifecycle.md", guides.lifecycle(project)),
                       ("researchgate-steps.md", guides.researchgate(project))):  # fmt: skip
        (home / name).write_bytes(text.encode("utf-8"))
        written.append(home / name)
    return written


def write_preview(project, context) -> Path:
    from manuscript_guard.communicate import checking, preview
    from manuscript_guard.contracts._schema import read_text

    found = {path: checking.text_findings(context, path, read_text(path))
             for path in checking.text_files(project)}  # fmt: skip
    target = folder(project) / PREVIEW
    target.write_bytes(preview.page(project, context, found).encode("utf-8"))
    return target
