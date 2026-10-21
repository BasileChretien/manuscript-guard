"""A co-author's Word comments, filed by `import` as findings the author answers.

`import` used to print each comment and keep nothing, so a comment nobody transcribed was
lost to the checks. It now files each one in `review/comments/<document>-<build>/
<commenter>.yaml` (`filed_comments`), and G11 reports it until it has a resolution or an
override (`gates/comments.py`).

Three documents here were made by Word 16 itself, over COM on 2026-10-20, from the
example's build: comments by two people, one with a reply, one on a heading, one on a
caption and one running into the next paragraph (`comments-word.docx`); the same saved again
with a comment added above the others, which made Word renumber every `w:id`
(`comments-word-again.docx`); and the first converted from compatibility mode, the only way
Word would resolve a thread in a pandoc build, with the first thread resolved
(`comments-word-resolved.docx`). The person who saved them is renamed `Ana Author` in their
core properties; nothing else was changed. The rest are XML made the way Word writes it.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
import yaml

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")

WORD_SAVED = Path(__file__).parent / "data" / "word"
FIRST, AGAIN, RESOLVED = (
    WORD_SAVED / "comments-word.docx",
    WORD_SAVED / "comments-word-again.docx",
    WORD_SAVED / "comments-word-resolved.docx",
)
W14_NS = "http://schemas.microsoft.com/office/word/2010/wordml"
W15_NS = "http://schemas.microsoft.com/office/word/2012/wordml"
W16CID_NS = "http://schemas.microsoft.com/office/word/2016/wordml/cid"


def run(*argv: str) -> tuple[int, str]:
    from manuscript_guard.cli import main

    printed = StringIO()
    with redirect_stdout(printed):
        code = main(list(argv))
    return code, printed.getvalue()


def built(project: Path) -> Path:
    code, said = run("build", str(project), "--offline")
    assert code == 0, said
    return project / "build" / "manuscript.docx"


def restamped(word_saved: Path, build: Path, target: Path) -> Path:
    """A document Word saved, carrying the properties of `build`: its source stamp and its
    record of paragraphs. Word saved it from a build of the same source on another machine,
    whose results may print otherwise; the properties say which build it is."""
    with zipfile.ZipFile(build) as fresh:
        custom = fresh.read("docProps/custom.xml")
    with zipfile.ZipFile(word_saved) as zin, zipfile.ZipFile(target, "w") as zout:
        for item in zin.infolist():
            data = custom if item.filename == "docProps/custom.xml" else zin.read(item.filename)
            zout.writestr(item, data)
    return target


def records(project: Path) -> dict[str, dict]:
    root = project / "review" / "comments"
    return {
        f"{path.parent.name}/{path.name}": yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*/*.yaml"))
    }


def by_commenter(project: Path) -> dict[str, list[dict]]:
    return {doc["commenter"]: doc["findings"] for doc in records(project).values()}


# ------------------------------------------------------------ comments made the way Word writes


def _text_of(paragraph: str) -> str:
    return "".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", paragraph))


def commented(source: Path, target: Path, notes: list[dict]) -> Path:
    """`source` with each of `notes` written as Word 16 writes a comment: its range in
    `document.xml` over the paragraph whose text starts with `on`, its words in
    `comments.xml` with a `w14:paraId`, a lasting id in `commentsIds.xml`, and in
    `commentsExtended.xml` whether it is resolved and, for a reply (`reply_to`, the index of
    the note it answers), its parent. A note may say `id`, `durable`, `date`, `done` and
    `paragraphs` (its text as several paragraphs)."""
    with zipfile.ZipFile(source) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
        infos = archive.infolist()
    xml = parts["word/document.xml"].decode("utf-8")
    paragraphs = re.findall(r"<w:p\b(?:(?!<w:p\b).)*?</w:p>", xml, re.DOTALL)
    bodies, extended, lasting = [], [], []
    for index, note in enumerate(notes):
        ident = str(note.get("id", 10 + index))
        para = f"{0x10000 + index:08X}"
        if "on" in note:
            paragraph = next(p for p in paragraphs if _text_of(p).startswith(note["on"]))
            at = xml.index(paragraph)
            opened = (
                paragraph.find(
                    ">", paragraph.find("</w:pPr>") + 1 if "</w:pPr>" in paragraph else 0
                )
                + 1
            )
            marked = (
                paragraph[:opened]
                + f'<w:commentRangeStart w:id="{ident}"/>'
                + paragraph[opened : -len("</w:p>")]
                + f'<w:commentRangeEnd w:id="{ident}"/><w:r><w:commentReference w:id="{ident}"/>'
                "</w:r></w:p>"
            )
            xml = xml[:at] + marked + xml[at + len(paragraph) :]
            paragraphs = re.findall(r"<w:p\b(?:(?!<w:p\b).)*?</w:p>", xml, re.DOTALL)
        lines = note.get("paragraphs") or [note["text"]]
        # Word names a comment by its last paragraph's id, in commentsExtended and commentsIds.
        ids = [f"{0x20000 + 10 * index + n:08X}" for n in range(len(lines) - 1)] + [para]
        inner = "".join(
            f'<w:p w14:paraId="{ids[n]}">'
            f'<w:r><w:t xml:space="preserve">{line}</w:t></w:r></w:p>'
            for n, line in enumerate(lines)
        )
        bodies.append(
            f'<w:comment w:id="{ident}" w:author="{note.get("author", "Ann Coauthor")}" '
            f'w:date="{note.get("date", "2026-10-19T10:00:00Z")}" w:initials="AC">{inner}'
            "</w:comment>"
        )
        parent = notes[note["reply_to"]] if "reply_to" in note else None
        parent_para = f"{0x10000 + notes.index(parent):08X}" if parent is not None else ""
        extended.append(
            f'<w15:commentEx w15:paraId="{para}"'
            + (f' w15:paraIdParent="{parent_para}"' if parent_para else "")
            + f' w15:done="{1 if note.get("done") else 0}"/>'
        )
        if note.get("durable", True):
            durable = (
                note["durable"] if isinstance(note.get("durable"), str) else f"{0x5000 + index:08X}"
            )
            lasting.append(
                f'<w16cid:commentId w16cid:paraId="{para}" w16cid:durableId="{durable}"/>'
            )
    parts["word/document.xml"] = xml.encode("utf-8")
    parts["word/comments.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f'xmlns:w14="{W14_NS}">{"".join(bodies)}</w:comments>'
    ).encode()
    parts["word/commentsExtended.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w15:commentsEx '
        f'xmlns:w15="{W15_NS}">{"".join(extended)}</w15:commentsEx>'
    ).encode()
    parts["word/commentsIds.xml"] = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w16cid:commentsIds '
        f'xmlns:w16cid="{W16CID_NS}">{"".join(lasting)}</w16cid:commentsIds>'
    ).encode()
    names = [info.filename for info in infos]
    with zipfile.ZipFile(target, "w") as out:
        for name in names:
            out.writestr(name, parts[name])
        for name in ("word/commentsExtended.xml", "word/commentsIds.xml"):
            if name not in names:
                out.writestr(name, parts[name])
        if "word/comments.xml" not in names:
            out.writestr("word/comments.xml", parts["word/comments.xml"])
    return target


# --------------------------------------------------------------- what Word saved, read as threads


def _threads(document: Path):
    from manuscript_guard.docxtext import paragraphs_of
    from manuscript_guard.filed_comments import threads_of

    names = {n for p in paragraphs_of(document) for n in p.names}
    return threads_of(document, vouched={n: n for n in names}, sources={n: n for n in names})


def test_what_word_saved_is_read_as_threads() -> None:
    threads = _threads(FIRST)
    assert [(t.author, t.block, t.text) for t in threads] == [
        ("Ann Coauthor", "paragraph", "Is there a newer reference for this?"),
        ("Ann Coauthor", "heading", "Rename to Methods and data?"),
        ("Ann Coauthor", "paragraph", "These two sentences repeat each other."),
        ("Ben Second", "caption", "Say which years."),
    ]
    first = threads[0]
    assert [(r.by, r.text) for r in first.replies] == [
        ("Ben Second", "Agreed, there is one from 2024.")
    ]
    assert first.anchored == "the signal extends to"
    assert first.where.startswith("mg-p-") and not first.resolved
    assert threads[1].anchored == "Methods" and threads[1].where == ""
    # The range ran on into the next paragraph; it is anchored where it starts.
    assert threads[2].anchored.startswith("heckable. The reporting")
    assert all(t.key.startswith("durable:") for t in threads)


def test_a_second_save_renumbers_the_comments_and_keeps_their_keys() -> None:
    """Word renumbers `w:id` on every save: keyed on it, a copy saved again would file every
    comment a second time."""
    from manuscript_guard.docxtext import word_comments

    ids = {c.text: c.identifier for c in word_comments(FIRST)}
    again = {c.text: c.identifier for c in word_comments(AGAIN)}
    assert all(again[text] != ident for text, ident in ids.items())
    first = {t.text: t.key for t in _threads(FIRST)}
    second = {t.text: t.key for t in _threads(AGAIN)}
    assert {text: second[text] for text in first} == first
    assert set(second) - set(first) == {"Cite the 2023 review here."}


def test_a_thread_resolved_in_word_reads_as_resolved() -> None:
    assert [t.resolved for t in _threads(RESOLVED)] == [True, False, False, False]
    assert [t.resolved for t in _threads(FIRST)] == [False] * 4


def test_a_comment_of_several_paragraphs_keeps_them_and_is_known_with_its_spaces_folded(
    tmp_path: Path,
) -> None:
    """Stored with a line break between its paragraphs, as written. A panel's comment is
    known by the digest of its words with their spaces folded, as the document of
    suggestions records it: by its words as stored here, one of two paragraphs would not
    have been known, and would have been filed as a co-author's."""
    from manuscript_guard.docxtext import paragraphs_of
    from manuscript_guard.filed_comments import threads_of
    from manuscript_guard.suggestions import short_digest

    returned = commented(FIRST, tmp_path / "two.docx", [
        {"on": "Whether the signal extends", "paragraphs": ["First line.", "Second line."]},
    ])  # fmt: skip
    names = {n for p in paragraphs_of(returned) for n in p.names}
    kept = dict(vouched={n: n for n in names}, sources={n: n for n in names})
    (thread,) = threads_of(returned, **kept)
    assert thread.text == "First line.\nSecond line."
    panel = [{"author": "Ann Coauthor", "comment": short_digest("First line. Second line.")}]
    assert threads_of(returned, **kept, panel=panel) == []


def test_the_panel_s_comments_are_known_by_what_they_are_not_by_their_words(
    tmp_path: Path,
) -> None:
    """Round 1 of #375: the panel's comments and the replies to them were left out by their
    author and words wherever they stood, so a co-author's "Agreed." of their own went with
    the one they wrote under the panel's comment."""
    from manuscript_guard.docxtext import paragraphs_of
    from manuscript_guard.filed_comments import threads_of
    from manuscript_guard.suggestions import short_digest

    finding = "Finding r8-pe-02 is about the wording."
    returned = commented(FIRST, tmp_path / "panel.docx", [
        {"on": "Whether the signal extends", "author": "Panel Reader", "text": finding},
        {"on": "Whether the signal", "author": "Ana Author", "text": "Agreed.", "reply_to": 0},
        {"on": "Drug-induced hepatic injury", "author": "Ana Author", "text": "Agreed."},
    ])  # fmt: skip
    names = {n for p in paragraphs_of(returned) for n in p.names}
    kept = dict(vouched={n: n for n in names}, sources={n: n for n in names})
    panel = [{"author": "Panel Reader", "comment": short_digest(finding)}]
    threads = threads_of(returned, **kept, panel=panel)
    assert [(t.author, t.text, t.replies) for t in threads] == [("Ana Author", "Agreed.", ())]
    # Where the edit moves a claim, the comment Word holds says so after the finding, and
    # the document records its digest as `written` (#367): that is the one it is known by.
    moved = [{"author": "Panel Reader", "comment": short_digest("the finding alone"),
              "written": short_digest(finding)}]  # fmt: skip
    assert [t.text for t in threads_of(returned, **kept, panel=moved)] == ["Agreed."]


@needs_pandoc
def test_a_comment_with_no_words_is_filed_and_reported(project: Path, tmp_path: Path) -> None:
    """Round 1 of #375: a comment that is a picture alone, with a reply, was filed with an
    empty `finding` the schema refused, and every `check` then failed. Without a reply it
    was not filed at all."""
    returned = commented(built(project), tmp_path / "back.docx", [
        {"on": "Whether the signal extends", "text": ""},
        {"on": "Whether the signal", "author": "Ben Second", "text": "What do you mean?",
         "reply_to": 0},
        {"on": "Whether the signal", "author": "Ann Coauthor", "text": "", "reply_to": 0},
        {"on": "Drug-induced hepatic injury", "author": "Ben Second", "text": ""},
    ])  # fmt: skip
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    assert "(no words" in said
    filed = by_commenter(project)
    assert [(f["finding"], [r["text"] for r in f.get("replies", [])]) for f in
            filed["Ann Coauthor"]] == [("", ["What do you mean?", ""])]  # fmt: skip
    assert "  reply from Ann Coauthor (2026-10-19), quoted:\n    (no words" in said
    assert [f["finding"] for f in filed["Ben Second"]] == [""]
    code, said = run("check", str(project))
    assert code == 0, said
    assert said.count("(no words: a picture, or nothing Word keeps as text)") == 2


def test_an_unreadable_manuscript_file_does_not_hide_the_comments(project: Path) -> None:
    """`check` reports the file once and stops the gates that read it as text. G11 reads it
    only to say whether a comment's paragraph changed, so the comments are still reported."""
    from manuscript_guard.contracts import load_project
    from manuscript_guard.filed_comments import Thread, plan_filing, write_filing
    from manuscript_guard.gates import check_review

    loaded = load_project(project)[0]
    thread = Thread(key="durable:00000001", author="Ann Coauthor", date="2026-10-19",
                    text="Is there a newer reference?", block="paragraph", anchored="words",
                    where="mg-p-main-8", paragraph_sha256="0" * 64)  # fmt: skip
    (filing,) = plan_filing(loaded, [thread], stamp="a" * 64, printed=None,
                            supplementary=False, today="2026-10-20")  # fmt: skip
    write_filing(filing)
    (project / "manuscript" / "notes.md").write_bytes("Café".encode("cp1252"))
    report = check_review(loaded, submission=True)
    (found,) = [f for f in report.failures if f.code == "comment-unanswered"]
    assert "has changed since" not in found.message
    (project / "manuscript" / "notes.md").unlink()
    (found,) = [f for f in check_review(loaded, submission=True).failures
                if f.code == "comment-unanswered"]  # fmt: skip
    assert "[the paragraph has changed since]" in found.message


# ------------------------------------------------------------------------- import files them


@needs_pandoc
def test_import_files_each_comment_and_g11_holds_it_until_it_is_answered(
    project: Path, tmp_path: Path
) -> None:
    returned = restamped(FIRST, built(project), tmp_path / "back.docx")
    code, said = run("import", str(returned), str(project))
    assert "--apply files in review/comments/manuscript-" in said, said
    assert not (project / "review" / "comments").exists(), "a preview wrote a record"

    code, said = run("import", str(returned), str(project), "--apply")
    assert "filed in review/comments/manuscript-" in said, said
    filed = by_commenter(project)
    assert [f["block"] for f in filed["Ann Coauthor"]] == ["paragraph", "heading", "paragraph"]
    assert [f["block"] for f in filed["Ben Second"]] == ["caption"]
    first = filed["Ann Coauthor"][0]
    assert first["severity"] == "comment"
    assert first["where"].startswith("mg-p-") and len(first["paragraph_sha256"]) == 64
    assert first["replies"] == [
        {"by": "Ben Second", "date": "2026-10-20", "text": "Agreed, there is one from 2024."}
    ]
    (document,) = [d for d in records(project).values() if d["commenter"] == "Ann Coauthor"]
    from manuscript_guard.roundtrip import stamp_of

    assert document["built_from"] == stamp_of(returned) and document["document"] == "manuscript"

    code, said = run("check", str(project))
    assert code == 0, said
    assert "Ann Coauthor (manuscript-" in said and "Rename to Methods and data?" in said
    assert "recorded:    4 comments from Word filed, 4 of them unanswered" in said
    code, said = run("check", str(project), "--submission")
    assert code == 1
    assert "[FAIL] G11 review" in said and "Say which years." in said

    # Answered: one resolved, the others overridden with a reason, by a person.
    for path in (project / "review" / "comments").glob("*/*.yaml"):
        record = yaml.safe_load(path.read_text(encoding="utf-8"))
        for finding in record["findings"]:
            if finding["block"] == "caption":
                finding["resolution"] = "The caption now gives the years."
                finding["resolved_on"] = "2026-10-21"
            else:
                finding["overridden"] = "Kept as it is; discussed by e-mail."
                finding["overridden_by"] = "Ana Author"
        path.write_text(
            yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    code, said = run("check", str(project), "--submission")
    assert code == 0, said


@needs_pandoc
def test_importing_the_same_document_again_files_nothing_twice(
    project: Path, tmp_path: Path
) -> None:
    build = built(project)
    first = restamped(FIRST, build, tmp_path / "back.docx")
    assert "filed in" in run("import", str(first), str(project), "--apply")[1]
    before = {
        name: (project / "review" / "comments" / name).read_bytes() for name in records(project)
    }

    code, said = run("import", str(first), str(project), "--apply")
    assert "nothing new" in said and "filed in" not in said, said
    assert {
        n: (project / "review" / "comments" / n).read_bytes() for n in records(project)
    } == before

    # Saved again in Word with one comment added above the others: every w:id moved.
    again = restamped(AGAIN, build, tmp_path / "again.docx")
    code, said = run("import", str(again), str(project), "--apply")
    filed = by_commenter(project)
    assert [f["finding"] for f in filed["Ben Second"]] == [
        "Say which years.",
        "Cite the 2023 review here.",
    ]
    assert [f["id"] for f in filed["Ben Second"]] == ["c1", "c2"]
    assert len(filed["Ann Coauthor"]) == 3

    # Resolved in Word since: marked, and still open.
    resolved = restamped(RESOLVED, build, tmp_path / "resolved.docx")
    code, said = run("import", str(resolved), str(project), "--apply")
    assert "Resolve added to c1" in said, said
    first_thread = by_commenter(project)["Ann Coauthor"][0]
    assert first_thread["resolved_in_word"] is True and "resolution" not in first_thread
    code, said = run("check", str(project))
    assert "[resolved in Word]" in said


@needs_pandoc
def test_a_comment_on_a_paragraph_the_import_refused_is_still_filed(
    project: Path, tmp_path: Path
) -> None:
    """The co-author changed a number in the paragraph they commented on: the rewording is
    refused, and the comment is the most useful thing left of it."""
    build = built(project)
    with zipfile.ZipFile(build) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    (paragraph,) = [
        p
        for p in re.findall(r"<w:p\b(?:(?!<w:p\b).)*?</w:p>", xml, re.DOTALL)
        if _text_of(p).startswith("The database contained")
    ]
    assert "4000" in paragraph
    edited = tmp_path / "edited.docx"
    with zipfile.ZipFile(build) as zin, zipfile.ZipFile(edited, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                changed = paragraph.replace("4000", "4100", 1)
                data = xml.replace(paragraph, changed, 1).encode("utf-8")
            zout.writestr(item, data)
    returned = commented(
        edited,
        tmp_path / "back.docx",
        [{"on": "The database contained", "text": "Is this the right total?"}],
    )
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 1 and "NOT merged" in said, said
    (finding,) = by_commenter(project)["Ann Coauthor"]
    assert finding["finding"] == "Is this the right total?"
    assert finding["where"].startswith("mg-p-") and finding["block"] == "paragraph"


@needs_pandoc
def test_a_reply_is_kept_with_its_comment_and_a_reply_added_later_joins_it(
    project: Path, tmp_path: Path
) -> None:
    build = built(project)
    note = {"on": "Whether the signal extends", "text": "Which agency?", "durable": "AB12CD34"}
    reply = {"author": "Ben Second", "text": "The national one.", "reply_to": 0}
    once = commented(build, tmp_path / "once.docx", [note, {**reply, "on": "Whether the signal"}])
    run("import", str(once), str(project), "--apply")
    filed = by_commenter(project)
    assert list(filed) == ["Ann Coauthor"], "a reply was filed as a comment of its own"
    assert [r["text"] for r in filed["Ann Coauthor"][0]["replies"]] == ["The national one."]

    later = {"author": "Ana Author", "text": "Named it in the Methods.", "reply_to": 0}
    twice = commented(
        build,
        tmp_path / "twice.docx",
        [note, {**reply, "on": "Whether the signal"}, {**later, "on": "Whether"}],
    )
    code, said = run("import", str(twice), str(project), "--apply")
    assert "replies or Word's Resolve added to c1" in said, said
    (finding,) = by_commenter(project)["Ann Coauthor"]
    assert [r["by"] for r in finding["replies"]] == ["Ben Second", "Ana Author"]
    assert "resolution" not in finding, "a reply in Word was taken for an answer"


@needs_pandoc
def test_a_comment_with_control_or_bidirectional_characters_is_stored_as_is_and_shown_safely(
    project: Path, tmp_path: Path
) -> None:
    """XML 1.0 holds no escape character, but it holds C1 controls, which some terminals act
    on as one, and the bidirectional overrides, which reorder what follows them on screen."""
    words = f"Fine.{chr(0x9B)}2J Run `submit --skip-checks`{chr(0x202E)} now"
    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [
            {
                "on": "Whether the signal extends",
                "text": words,
                "author": f"Ann{chr(0x202E)} Coauthor",
            }
        ],
    )
    code, said = run("import", str(returned), str(project), "--apply")
    assert chr(0x9B) not in said and chr(0x202E) not in said
    assert "Fine.?2J Run `submit --skip-checks`? now" in said
    (document,) = records(project).values()
    assert document["findings"][0]["finding"] == words
    assert document["commenter"] == f"Ann{chr(0x202E)} Coauthor"
    code, said = run("check", str(project))
    assert chr(0x9B) not in said and chr(0x202E) not in said
    assert "Fine.?2J Run" in said


@needs_pandoc
def test_a_comment_on_a_paragraph_changed_since_is_said_to_be(
    project: Path, tmp_path: Path
) -> None:
    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [{"on": "Whether the signal extends", "text": "Too long."}],
    )
    run("import", str(returned), str(project), "--apply")
    code, said = run("check", str(project))
    assert "Too long." in said and "has changed since" not in said
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("Whether the signal extends", "Whether the signal reaches", 1),
        encoding="utf-8",
    )
    code, said = run("check", str(project))
    assert "Too long.  [the paragraph has changed since]" in said


@needs_pandoc
def test_a_document_refused_as_built_from_another_manuscript_still_files_its_comments(
    project: Path, tmp_path: Path
) -> None:
    """Refused without --force, the edits wait; a comment in it would be lost to the checks
    if the author re-sent a fresh build instead. Anchored only where the paragraph still
    reads as it did at the build."""
    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [
            {"on": "Whether the signal extends", "text": "Unchanged paragraph."},
            {"on": "Drug-induced hepatic injury remains", "text": "Changed paragraph."},
        ],
    )
    main = project / "manuscript" / "main.md"
    text = main.read_text(encoding="utf-8")
    main.write_text(
        text.replace("remains among the commonest", "is among the commonest", 1), encoding="utf-8"
    )
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 1 and "different version of the manuscript" in said
    assert "the comments are filed all the same" in said, said
    found = {f["finding"]: f for f in by_commenter(project)["Ann Coauthor"]}
    assert found["Unchanged paragraph."]["where"].startswith("mg-p-")
    changed = found["Changed paragraph."]
    assert "where" not in changed and changed["unmatched"] is True
    code, said = run("check", str(project))
    assert "made on a paragraph not matched to the source" in said


@needs_pandoc
def test_a_journal_reviewer_s_point_seeded_in_a_revision_round_is_not_filed_again(
    project: Path, tmp_path: Path
) -> None:
    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [
            {
                "on": "Whether the signal extends",
                "text": "Justify the comparator.",
                "author": "Reviewer 2",
            },
        ],
    )
    code, said = run("respond", str(project), "--open", "--from", str(returned))
    assert code == 0, said
    code, said = run("import", str(returned), str(project), "--apply")
    assert "is a point of revision round" in said, said
    assert records(project) == {}


@needs_pandoc
def test_two_commenters_get_two_records_and_the_supplement_its_own(
    project: Path, tmp_path: Path
) -> None:
    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [
            {"on": "Whether the signal extends", "text": "One.", "author": "Dr. Tanaka"},
            {"on": "Whether the signal extends", "text": "Two.", "author": "Dr Tanaka"},
            {"on": "Drug-induced hepatic injury", "text": "Three.", "author": "Ben Second"},
        ],
    )
    run("import", str(returned), str(project), "--apply")
    names = sorted(records(project))
    assert [name.split("/")[1] for name in names] == ["ben-second.yaml", "dr-tanaka.yaml"]
    assert all(name.startswith("manuscript-") for name in names)
    back = commented(
        project / "build" / "supplementary.docx",
        tmp_path / "supplement.docx",
        [{"on": "The case definition belongs here", "text": "Four."}],
    )
    run("import", str(back), str(project), "--apply")
    (supplementary,) = [d for n, d in records(project).items() if n.startswith("supplementary-")]
    assert supplementary["document"] == "supplementary"
    assert [f["finding"] for f in supplementary["findings"]] == ["Four."]


@needs_pandoc
def test_the_panel_s_own_comments_are_not_filed(project: Path, tmp_path: Path) -> None:
    """A review panel's suggested edits carry its findings as comments, and the author's
    reply to one is that finding's answer: both are in the panel's record already."""
    from suggesting import offered_round
    from word_edits import decide

    document = offered_round(project)
    returned = decide(
        document,
        tmp_path / "back.docx",
        {1: "accept", 2: "reject", 3: "reject"},
        replies={3: "The aim reads as a question already."},
    )
    code, said = run("import", str(returned), str(project), "--apply")
    assert code == 0, said
    assert records(project) == {}


@needs_pandoc
def test_nothing_of_a_comment_reaches_the_submission_pack(project: Path, tmp_path: Path) -> None:
    """The records are internal: a co-author's name and words stay out of every document
    the journal gets, the pack's manifest included."""
    returned = commented(
        built(project),
        tmp_path / "back.docx",
        [
            {
                "on": "Whether the signal extends",
                "text": "Private remark xyzzy.",
                "author": "Zelda Quokka",
            },
        ],
    )
    run("import", str(returned), str(project), "--apply")
    code, said = run("submit", str(project), "--offline", "--skip-checks")
    assert code == 0, said
    pack = project / "build" / "submission"
    for path in pack.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                data = b"".join(archive.read(name) for name in archive.namelist())
        assert b"xyzzy" not in data and b"Quokka" not in data, path.name
