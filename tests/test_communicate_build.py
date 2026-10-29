"""`communicate build`, `communicate status`, the sharing checks and the paper's own DOI.

Each text the build writes is held to `communicate check` as written; the sharing policy,
the embargo and the kept Crossref answer are made to fail and to pass; the triggers are read
against the publication's dates; and the DOI is asked of a loopback server only.
"""

from __future__ import annotations

import json
import threading
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from manuscript_guard.cli import main
from manuscript_guard.communicate import brief as brief_module
from manuscript_guard.communicate import build as build_module
from manuscript_guard.communicate import checking, lifecycle, own_doi
from manuscript_guard.contracts import load_project
from manuscript_guard.findings import FAIL, INFO, WARN
from manuscript_guard.lookup import paper_doi
from manuscript_guard.lookup.http import NoAnswer, Request, Response, default_transport
from manuscript_guard.lookup.run import Services

LIMITATION = "Several limitations follow from the design."
DOI = "10.1234/demo.5678"
TITLE = ("Reporting of hepatic injury with example-drug: a disproportionality analysis of a "
         "synthetic spontaneous reporting database")  # fmt: skip


def append(root: Path, text: str) -> None:
    with (root / "paper.yaml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def edit_brief(root: Path, change) -> None:
    path = root / "communication" / "brief.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(document)
    path.write_bytes(brief_module.dump(document).encode("utf-8"))


def _primary_and_limitation(document: dict) -> None:
    for finding in document["findings"]:
        finding["primary"] = finding["id"] == "findings.2"
    document["limitations"] = [{"id": "limitations.1", "text": LIMITATION,
                                "from": {"file": "manuscript/main.md", "quote": LIMITATION}}]


@pytest.fixture
def ready(project: Path) -> Path:
    """The example with the group on, its brief written, findings.2 primary and a
    limitation quoted from the Discussion."""
    append(project, "\ncommunication:\n  enabled: true\n")
    assert main(["communicate", "brief", str(project)]) == 0
    edit_brief(project, _primary_and_limitation)
    return project


@pytest.fixture
def out(ready: Path) -> Path:
    append(ready, f"publication:\n  status: published-online\n  published_on: 2026-10-01\n"
                  f"  doi: {DOI}\n")  # fmt: skip
    return ready


def found(root: Path, only: str | None = "texts") -> list[tuple[str, str, str]]:
    project, _ = load_project(root)
    return [(one.code, one.severity, Path(one.path).name if one.path else "")
            for one in checking.check(project, only=only).findings]  # fmt: skip


def failures(root: Path) -> list[tuple[str, str, str]]:
    return [one for one in found(root) if one[1] == FAIL]


def write(root: Path, name: str, body: str, front: str) -> Path:
    path = root / "communication" / name
    path.write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8", newline="\n")
    return path


CLEAN = ("The reporting odds ratio was {{results.ror.point}} (95% CI {{results.ror.ci_low}} "
         "to {{results.ror.ci_high}}) [](#brief:findings.2).")  # fmt: skip


@pytest.fixture
def at(monkeypatch: pytest.MonkeyPatch):
    """Set the moment the embargo and the follow-ups are read against."""

    def setting(moment: datetime) -> None:
        monkeypatch.setattr(lifecycle, "now", lambda: moment)

    return setting


# ------------------------------------------------------------------------------- the build


@pytest.mark.parametrize("verb", ["build", "status"])
def test_build_and_status_refuse_while_the_group_is_off(project: Path, verb: str) -> None:
    assert main(["communicate", verb, str(project)]) == 2
    assert not (project / "communication").exists()


def test_the_build_needs_a_brief_with_a_primary_finding(project: Path,
                                                         capsys: pytest.CaptureFixture[str]
                                                         ) -> None:  # fmt: skip
    append(project, "\ncommunication:\n  enabled: true\n")
    assert main(["communicate", "build", str(project)]) == 2
    assert main(["communicate", "brief", str(project)]) == 0
    capsys.readouterr()
    assert main(["communicate", "build", str(project)]) == 2
    assert "primary: true" in capsys.readouterr().err


def test_every_text_the_build_writes_passes_the_check_as_written(ready: Path) -> None:
    assert main(["communicate", "build", str(ready)]) == 1  # the deposit has no DOI
    written = sorted(path.name for path in (ready / "communication").glob("*.md"))
    expected = sorted(f"{name}.md" for name in [*build_module.DETERMINISTIC,
                                                *build_module.SCAFFOLDED]
                      if name != "data-announcement")  # fmt: skip
    assert written == expected
    assert failures(ready) == []
    # The same brief and results give the same bytes.
    before = {p.name: p.read_bytes() for p in (ready / "communication").rglob("*") if p.is_file()}
    assert main(["communicate", "build", str(ready), "--force"]) == 1
    after = {p.name: p.read_bytes() for p in (ready / "communication").rglob("*") if p.is_file()}
    assert after == before


def test_each_text_says_what_it_is_in_its_front_matter(ready: Path) -> None:
    main(["communicate", "build", str(ready), "--channels", "bluesky,press-release"])
    from manuscript_guard.communicate.texts import front_matter

    raw = (ready / "communication" / "bluesky.md").read_text(encoding="utf-8")
    front, error = front_matter(raw)
    assert not error
    assert list(front) == ["channel", "audience", "version_shared", "links", "attachments"]
    assert front["channel"] == "bluesky" and front["version_shared"] == "none"
    assert front["links"] == [] and front["attachments"] == []
    assert "[](#brief:findings.2)" in raw and "{{results.ror.point}}" in raw
    release = (ready / "communication" / "press-release.md").read_text(encoding="utf-8")
    assert "<!-- write:" in release and "[](#brief:limitations.1)" in release


def test_a_text_that_states_a_limitation_is_not_written_from_a_brief_with_none(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    edit_brief(ready, lambda document: document.update(limitations=[]))
    assert main(["communicate", "build", str(ready), "--channels",
                 "press-release,pitch,bluesky"]) == 1  # fmt: skip
    said = capsys.readouterr().out
    assert "press-release: not written" in said and "the brief holds none" in said
    assert not (ready / "communication" / "press-release.md").exists()
    assert (ready / "communication" / "bluesky.md").exists()


def test_the_build_writes_over_no_text_without_force(ready: Path) -> None:
    path = write(ready, "bluesky.md", CLEAN + " Written by hand.", "channel: bluesky")
    kept = path.read_bytes()
    assert main(["communicate", "build", str(ready), "--channels", "bluesky"]) == 0
    assert path.read_bytes() == kept
    assert main(["communicate", "build", str(ready), "--channels", "bluesky", "--force"]) == 0
    assert path.read_bytes() != kept


def test_an_unknown_channel_is_refused(ready: Path) -> None:
    assert main(["communicate", "build", str(ready), "--channels", "myspace"]) == 2
    assert main(["communicate", "check", str(ready), "--channels", "bluesky"]) == 2


def test_a_channel_paper_yaml_lists_and_the_build_does_not_write_is_passed_over(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    append(ready, "  channels: [bluesky, blog]\n")
    assert main(["communicate", "build", str(ready)]) == 0
    assert "blog: the build writes no text for it" in capsys.readouterr().out
    assert {p.name for p in (ready / "communication").glob("*.md")} == {"bluesky.md"}


def test_the_paper_is_linked_once_it_is_online_and_not_before(ready: Path) -> None:
    append(ready, f"publication:\n  status: accepted\n  doi: {DOI}\n")
    main(["communicate", "build", str(ready), "--channels", "bluesky,bluesky-thread"])
    for name in ("bluesky.md", "bluesky-thread.md"):
        text = (ready / "communication" / name).read_text(encoding="utf-8")
        assert DOI not in text and "version_shared: none" in text, name
    assert failures(ready) == []
    paper = (ready / "paper.yaml").read_text(encoding="utf-8")
    (ready / "paper.yaml").write_text(paper.replace("status: accepted",
                                                    "status: published-online"),
                                      encoding="utf-8")  # fmt: skip
    main(["communicate", "build", str(ready), "--channels", "bluesky,bluesky-thread", "--force"])
    for name in ("bluesky.md", "bluesky-thread.md"):
        text = (ready / "communication" / name).read_text(encoding="utf-8")
        assert f"https://doi.org/{DOI}" in text and "version_shared: published" in text, name
    assert failures(ready) == []


def test_a_post_drops_the_conclusion_to_fit_and_a_thread_too_long_is_not_written(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    append(ready, "  limits:\n    bluesky: 100\n")
    assert main(["communicate", "build", str(ready), "--channels",
                 "bluesky,bluesky-thread"]) == 1  # fmt: skip
    post = (ready / "communication" / "bluesky.md").read_text(encoding="utf-8")
    assert "[](#brief:findings.2)" in post and "conclusion" not in post
    assert "bluesky-thread: not written: comm-over-limit" in capsys.readouterr().out


def test_the_deposit_is_announced_only_with_its_doi_licence_and_manifest(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    channels = ["--channels", "data-announcement"]
    assert main(["communicate", "build", str(ready), *channels]) == 1
    assert "package gives no DOI" in capsys.readouterr().out
    paper = (ready / "paper.yaml").read_text(encoding="utf-8")
    (ready / "paper.yaml").write_text(paper.replace("  licence: MIT\n", "  licence: MIT\n  doi: "
                                                    "10.5281/zenodo.1234567\n"),
                                      encoding="utf-8")  # fmt: skip
    assert main(["communicate", "build", str(ready), *channels]) == 1
    assert "manifest" in capsys.readouterr().out
    manifest = ready / "build" / "package" / "demo" / "MANIFEST.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("schema: manuscript-guard/package/1\n", encoding="utf-8")
    assert main(["communicate", "build", str(ready), *channels]) == 0
    text = (ready / "communication" / "data-announcement.md").read_text(encoding="utf-8")
    assert "https://doi.org/10.5281/zenodo.1234567" in text and "`MIT`" in text
    assert failures(ready) == []


def test_the_overview_slide_names_what_it_prints_and_is_held_to_the_results(ready: Path) -> None:
    assert main(["communicate", "build", str(ready), "--channels", "overview"]) == 0
    slide = ready / "communication" / "overview.svg"
    root = ET.fromstring(slide.read_text(encoding="utf-8"))
    assert root.get("viewBox") == "0 0 1920 1080"
    named = {node.get("data-statement") for node in root.iter() if node.tag.endswith("text")}
    assert {"question.1", "findings.2", "conclusion.1"} <= named
    assert failures(ready) == []
    # A value edited in the slide by hand no longer prints what the results hold.
    project, _ = load_project(ready)
    from manuscript_guard.contracts import load_namespace

    shown = load_namespace(project)[0]["results.ror.point"].display
    slide.write_text(slide.read_text(encoding="utf-8").replace(shown, "9.99"), encoding="utf-8")
    assert ("comm-ga-stale", FAIL, "overview.svg") in found(ready)


def test_a_translation_has_a_slot_for_each_statement_and_is_held_to_its_numbers(
    ready: Path,
) -> None:
    assert main(["communicate", "build", str(ready), "--channels", "translation-ja"]) == 0
    path = ready / "communication" / "translation-ja.md"
    scaffold = path.read_text(encoding="utf-8")
    assert "language: ja" in scaffold
    assert "<!-- source, findings.2: The reporting odds ratio was {{results.ror.point}}" in scaffold
    assert "keep {{results.ror.point}}, {{results.ror.ci_low}}, {{results.ror.ci_high}}" in scaffold
    assert failures(ready) == []
    japanese = ("報告オッズ比は {{results.ror.point}} (95% CI {{results.ror.ci_low}} to "
                "{{results.ror.ci_high}}) であった [](#brief:findings.2)。")  # fmt: skip
    write(ready, "translation-ja.md", japanese, "channel: translation-ja\nlanguage: ja")
    assert [one for one in found(ready) if one[1] in (FAIL, WARN)] == []
    write(ready, "translation-ja.md", japanese.replace("{{results.ror.point}}", "3.84"),
          "channel: translation-ja\nlanguage: ja")  # fmt: skip
    assert ("comm-number-unbound", FAIL, "translation-ja.md") in found(ready)


def test_the_preview_prints_every_text_as_read(ready: Path) -> None:
    main(["communicate", "build", str(ready), "--channels", "bluesky-thread,press-release"])
    page = (ready / "communication" / "preview.html").read_text(encoding="utf-8")
    project, _ = load_project(ready)
    from manuscript_guard.contracts import load_namespace

    shown = load_namespace(project)[0]["results.ror.point"].display
    assert "bluesky-thread.md" in page and "press-release.md" in page
    assert shown in page and "{{results" not in page and "#brief:" not in page
    assert "[to write:" in page and "of 300 graphemes" in page


def test_the_guides_are_written_beside_the_texts_and_are_no_texts(ready: Path) -> None:
    main(["communicate", "build", str(ready), "--channels", "bluesky"])
    guides = ready / "communication" / "guides"
    assert {p.name for p in guides.iterdir()} == {"lifecycle.md", "researchgate-steps.md"}
    project, _ = load_project(ready)
    assert guides / "lifecycle.md" not in checking.text_files(project)


# ------------------------------------------------------------------------------ sharing

_UPLOAD = "channel: researchgate\nversion_shared: {version}\nattachments: [{name}]"


def _sharing(root: Path, block: str) -> None:
    profile = root / "profiles" / "journals" / "demo-journal.yaml"
    profile.write_text(profile.read_text(encoding="utf-8") + block, encoding="utf-8")


def test_with_no_sharing_policy_a_doi_link_is_allowed_and_an_upload_refused(out: Path) -> None:
    write(out, "researchgate.md", f"Read it at https://doi.org/{DOI}. " + CLEAN,
          "channel: researchgate\nversion_shared: published")  # fmt: skip
    assert failures(out) == []
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="accepted", name="paper.pdf"))
    assert ("comm-sharing-unknown", FAIL, "researchgate.md") in found(out)
    # An image is no version of the paper.
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="accepted", name="figure.png"))
    assert failures(out) == []


def test_an_upload_is_held_to_the_version_and_place_the_policy_allows(out: Path) -> None:
    _sharing(out, "sharing:\n  source_url: https://journal.example/sharing\n"
                  "  accepted:\n    where: [institutional-repository]\n"
                  "  published:\n    where: [academic-network]\n")  # fmt: skip
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="accepted", name="paper.pdf"))
    assert ("comm-sharing-not-allowed", FAIL, "researchgate.md") in found(out)
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="published", name="paper.pdf"))
    assert failures(out) == []
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="preprint", name="paper.pdf"))
    assert ("comm-sharing-unknown", FAIL, "researchgate.md") in found(out)
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="none", name="paper.pdf"))
    assert ("comm-sharing-unknown", FAIL, "researchgate.md") in found(out)
    # A channel that puts it at no place a policy names.
    write(out, "pitch.md", CLEAN + " [](#brief:limitations.1)",
          "channel: pitch\nversion_shared: published\nattachments: [paper.pdf]")  # fmt: skip
    assert ("comm-sharing-unknown", FAIL, "pitch.md") in found(out)


def test_an_upload_waits_for_the_months_the_policy_gives(out: Path, at) -> None:
    _sharing(out, "sharing:\n  published:\n    where: [academic-network]\n"
                  "    embargo_months: 12\n")  # fmt: skip
    write(out, "researchgate.md", CLEAN, _UPLOAD.format(version="published", name="paper.pdf"))
    at(datetime(2027, 9, 30, tzinfo=timezone.utc))
    assert ("comm-sharing-not-allowed", FAIL, "researchgate.md") in found(out)
    at(datetime(2027, 10, 1, tzinfo=timezone.utc))
    assert failures(out) == []
    paper = (out / "paper.yaml").read_text(encoding="utf-8")
    (out / "paper.yaml").write_text(paper.replace("  published_on: 2026-10-01\n", ""),
                                    encoding="utf-8")  # fmt: skip
    assert ("comm-sharing-unknown", FAIL, "researchgate.md") in found(out)


# ------------------------------------------------------------------------------ the embargo


def test_nothing_is_shared_before_the_embargo_lifts(ready: Path, at) -> None:
    append(ready, "publication:\n  status: accepted\n  embargo_until: 2026-12-01T00:01Z\n")
    write(ready, "post.md", CLEAN, "channel: bluesky")
    at(datetime(2026, 12, 1, 0, 0, tzinfo=timezone.utc))
    assert ("comm-embargo", FAIL, "post.md") in found(ready)
    at(datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc))
    assert "comm-embargo" not in {code for code, _s, _p in found(ready)}


def test_the_build_writes_before_the_embargo_and_the_check_holds_it(ready: Path, at,
                                                                    capsys) -> None:  # fmt: skip
    append(ready, "publication:\n  status: accepted\n  embargo_until: 2026-12-01\n")
    at(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert main(["communicate", "build", str(ready), "--channels", "bluesky"]) == 0
    assert "embargo holds until 2026-12-01 12:00 UTC" in capsys.readouterr().out
    assert [code for code, _s, _p in failures(ready)] == ["comm-embargo"]


@pytest.mark.parametrize(("written", "lifts"), [
    ("2026-12-01T00:01Z", datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc)),
    ("2026-12-01T09:01+09:00", datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc)),
    ("2026-12-01T00:01 GMT", datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc)),
    # With no zone, where the time comes last: twelve hours behind UTC.
    ("2026-12-01T00:01", datetime(2026, 12, 1, 12, 1, tzinfo=timezone.utc)),
    ("2026-12-01", datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)),
    (date(2026, 12, 1), datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)),
    ("1 December 2026", None), ("2026-02-30", None),
])  # fmt: skip
def test_an_embargo_is_read_where_it_lifts_last(written, lifts) -> None:
    assert lifecycle.lifted_at(written) == lifts


def test_an_embargo_that_cannot_be_read_holds(ready: Path) -> None:
    append(ready, "publication:\n  embargo_until: '1 December, 00:01 London time'\n")
    write(ready, "post.md", CLEAN, "channel: bluesky")
    assert ("comm-embargo", FAIL, "post.md") in found(ready)


# ------------------------------------------------------------------------------- status


def test_status_says_what_is_due_given_the_publication_and_its_dates(
    ready: Path, at, capsys: pytest.CaptureFixture[str]
) -> None:
    append(ready, "  triggers:\n    accepted: [press-release]\n"
                  "    published: [bluesky-thread]\n"
                  "    followups:\n      - {after_days: 30, channels: [bluesky]}\n"
                  "publication:\n  status: accepted\n")  # fmt: skip
    at(datetime(2026, 10, 29, tzinfo=timezone.utc))
    project, _ = load_project(ready)
    held = lifecycle.standing(project)
    states = {(one.channel, one.when): one.state for one in held.due}
    assert states == {("press-release", "accepted"): lifecycle.TO_WRITE,
                      ("bluesky-thread", "published"): lifecycle.WAITS,
                      ("bluesky", "30 days after publication"): lifecycle.WAITS}  # fmt: skip
    assert main(["communicate", "status", str(ready), "--prepare"]) == 0
    assert (ready / "communication" / "press-release.md").exists()
    assert not (ready / "communication" / "bluesky-thread.md").exists()
    # Online, the thread is due; thirty days on, the follow-up.
    paper = (ready / "paper.yaml").read_text(encoding="utf-8")
    (ready / "paper.yaml").write_text(paper.replace(
        "status: accepted", "status: published-online\n  published_on: 2026-10-01"),
        encoding="utf-8")  # fmt: skip
    project, _ = load_project(ready)
    states = {(one.channel, one.when): one.state for one in lifecycle.standing(project).due}
    assert states[("bluesky-thread", "published")] == lifecycle.TO_WRITE
    assert states[("bluesky", "30 days after publication")] == lifecycle.WAITS
    at(datetime(2026, 10, 31, tzinfo=timezone.utc))
    states = {(one.channel, one.when): one.state for one in lifecycle.standing(project).due}
    assert states[("bluesky", "30 days after publication")] == lifecycle.TO_WRITE
    capsys.readouterr()
    assert main(["communicate", "status", str(ready)]) == 0
    said = capsys.readouterr().out
    assert "to write:" in said and "bluesky (30 days after publication, from 2026-10-31)" in said


def test_a_text_written_before_the_paper_was_online_is_said_to_be(ready: Path) -> None:
    append(ready, "  channels: [bluesky]\npublication:\n  status: accepted\n")
    main(["communicate", "build", str(ready)])
    paper = (ready / "paper.yaml").read_text(encoding="utf-8")
    (ready / "paper.yaml").write_text(paper.replace("status: accepted", "status: in-issue"),
                                      encoding="utf-8")  # fmt: skip
    project, _ = load_project(ready)
    [due] = lifecycle.standing(project).due
    assert (due.channel, due.state) == ("bluesky", lifecycle.BEFORE_OUT)


# -------------------------------------------------------------------------- the paper's DOI


def _crossref(title: str = TITLE, status: int = 200) -> Response:
    body = {"status": "ok", "message-type": "work",
            "message": {"DOI": DOI, "title": [title], "type": "journal-article",
                        "author": [{"family": "Example", "given": "A."}]}}  # fmt: skip
    return Response(status, {}, json.dumps(body).encode())


def _ask(answer: Response, sent: list):
    def transport(request: Request, timeout: float) -> Response:
        sent.append(request)
        return answer

    return transport


def _looked_up(root: Path, answer: Response) -> list:
    sent: list = []
    project, _ = load_project(root)
    paper_doi.run(project, transport=_ask(answer, sent), services=Services(
        crossref="https://crossref.invalid/works/"), today=date(2026, 10, 29),
        said=lambda _: None)  # fmt: skip
    return sent


def test_the_papers_doi_is_asked_of_crossref_only_when_asked_and_read_offline(out: Path) -> None:
    assert ("comm-doi-not-looked-up", INFO, "crossref.yaml") in found(out)
    sent = _looked_up(out, _crossref(f"<i>{TITLE.upper()}</i>"))
    [request] = sent
    assert request.base == f"https://crossref.invalid/works/{DOI}"
    record = yaml.safe_load(own_doi.record_path(load_project(out)[0]).read_text(encoding="utf-8"))
    assert record["crossref"] == {"status": "found", "doi": DOI, "title": f"<i>{TITLE.upper()}</i>",
                                  "type": "journal-article"}  # fmt: skip
    assert not {"comm-doi-not-looked-up", "comm-doi-unknown",
                "comm-doi-title-differs"} & {code for code, _s, _p in found(out)}  # fmt: skip


def test_a_doi_crossref_does_not_know_or_of_another_title_warns(out: Path) -> None:
    _looked_up(out, _crossref("Grapefruit juice and statins"))
    assert ("comm-doi-title-differs", WARN, "crossref.yaml") in found(out)
    _looked_up(out, Response(404, {}, b"Resource not found."))
    assert ("comm-doi-unknown", WARN, "crossref.yaml") in found(out)
    assert failures(out) == []


def test_an_edited_record_or_another_dois_answers_for_nothing(out: Path) -> None:
    _looked_up(out, _crossref("Grapefruit juice and statins"))
    path = own_doi.record_path(load_project(out)[0])
    path.write_text(path.read_text(encoding="utf-8").replace("Grapefruit juice and statins",
                                                             TITLE), encoding="utf-8")  # fmt: skip
    assert ("comm-doi-not-looked-up", INFO, "crossref.yaml") in found(out)
    _looked_up(out, _crossref())
    paper = (out / "paper.yaml").read_text(encoding="utf-8")
    (out / "paper.yaml").write_text(paper.replace(DOI, "10.1234/other.1"), encoding="utf-8")
    assert ("comm-doi-not-looked-up", INFO, "crossref.yaml") in found(out)


def test_lookup_paper_asks_only_what_is_due_and_refuses_without_a_doi(
    ready: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["lookup", str(ready), "--paper"]) == 2
    append(ready, f"publication:\n  doi: {DOI}\n")
    sent: list = []
    monkeypatch.setattr(paper_doi, "default_transport", _ask(_crossref(), sent))
    assert main(["lookup", str(ready), "--paper", "--dry-run"]) == 0
    assert sent == [] and "nothing was sent" in capsys.readouterr().out
    assert main(["lookup", str(ready), "--paper"]) == 0
    assert len(sent) == 1
    assert main(["lookup", str(ready), "--paper"]) == 0
    assert len(sent) == 1 and "up to date" in capsys.readouterr().out
    assert main(["lookup", str(ready), "--paper", "--again"]) == 0
    assert len(sent) == 2
    assert main(["lookup", str(ready), "--paper", "--journals"]) == 2


def test_lookup_paper_refuses_while_the_group_is_off(project: Path) -> None:
    append(project, f"publication:\n  doi: {DOI}\n")
    assert main(["lookup", str(project), "--paper"]) == 2
    assert not (project / "communication").exists()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - the name http.server looks for
        answer = _crossref()
        self.server.seen.append(self.path)
        self.send_response(answer.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer.body)))
        self.end_headers()
        self.wfile.write(answer.body)
        self.close_connection = True

    def log_message(self, *args) -> None:
        pass


def test_the_real_transport_asks_crossref_on_loopback(out: Path) -> None:
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"cannot listen on a loopback port: {exc}")
    httpd.seen = []
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        try:
            default_transport(Request(url + "/probe"), 5)
        except NoAnswer as exc:  # pragma: no cover - depends on the machine
            pytest.skip(f"loopback connections are not allowed here: {exc}")
        project, _ = load_project(out)
        record, _path = paper_doi.run(project, services=Services(crossref=f"{url}/works/"),
                                      today=date(2026, 10, 29), said=lambda _: None)  # fmt: skip
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert record["crossref"]["status"] == "found"
    assert httpd.seen[-1].startswith(f"/works/{DOI}")


@pytest.mark.parametrize(("ours", "theirs", "subtitle", "same"), [
    (TITLE, TITLE, None, True),
    (TITLE, TITLE.upper(), None, True),
    ("Café au lait: a study", "Cafe au lait - a study", None, True),
    ("Main title: the subtitle", "Main title", "The subtitle", True),
    ("A &amp; B", "A & B", None, True),
    ("<i>In vitro</i> work", "In vitro work", None, True),
    (TITLE, "Grapefruit juice and statins", None, False),
    ("Main title", "Main title", "The subtitle", True),
    ("Main title", "Main", None, False),
])  # fmt: skip
def test_two_titles_are_one_whatever_their_case_markup_and_marks(ours, theirs, subtitle,
                                                                 same) -> None:  # fmt: skip
    answer = {"title": theirs, **({"subtitle": subtitle} if subtitle else {})}
    assert own_doi.same_title(ours, answer) is same


def test_the_triggers_go_in_paper_yaml_and_a_wrong_one_is_a_schema_finding(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    append(ready, "  channels: [bluesky]\n"
                  "  triggers:\n    followups:\n      - {after_days: 0, channels: [bluesky]}\n")
    capsys.readouterr()
    assert main(["check", str(ready), "--json"]) == 1
    said = json.loads(capsys.readouterr().out)
    assert any(one["code"] == "schema-violation" and "after_days" in one["message"]
               for one in said["findings"])  # fmt: skip
    project, _ = load_project(ready)
    # What the schema refuses is not read: the channels are due once the paper is online.
    assert lifecycle.triggers(project) == {"published": ["bluesky"]}


def test_now_is_this_moment_in_utc() -> None:
    moment = lifecycle.now()
    assert moment.tzinfo is not None and abs(moment - datetime.now(timezone.utc)) < timedelta(1)
