"""The `communicate` group: the brief, the graphical abstract, and `communicate check`.

Each code `communicate check` reports is made to fire on a text, a brief or a graphical
abstract that has the fault, and to stay silent on the one without it; the brief's scaffold,
the SVG's bytes and attributes and the alternative text are pinned; and `check` is shown to
read nothing under `communication/` while the group is off.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from manuscript_guard import claims
from manuscript_guard.cli import main
from manuscript_guard.communicate import brief as brief_module
from manuscript_guard.communicate import checking, svg, templates, texts
from manuscript_guard.communicate.brief import Brief, Statement
from manuscript_guard.contracts import load_project
from manuscript_guard.findings import FAIL, INFO, WARN


def enable(root: Path) -> None:
    with (root / "paper.yaml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("\ncommunication:\n  enabled: true\n")


def brief_file(root: Path) -> Path:
    return root / "communication" / "brief.yaml"


def edit_brief(root: Path, change) -> None:
    path = brief_file(root)
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(document)
    path.write_bytes(brief_module.dump(document).encode("utf-8"))


def mark_primary(root: Path, statement: str = "findings.2") -> None:
    def change(document: dict) -> None:
        for finding in document["findings"]:
            finding["primary"] = finding["id"] == statement

    edit_brief(root, change)


@pytest.fixture
def ready(project: Path) -> Path:
    """The example with the group on, its brief written and findings.2 marked primary."""
    enable(project)
    assert main(["communicate", "brief", str(project)]) == 0
    mark_primary(project)
    return project


def found(root: Path, only: str | None = None) -> list[tuple[str, str]]:
    project, _ = load_project(root)
    report = checking.check(project, only=only)
    return [(one.code, one.severity) for one in report.findings]


def text(root: Path, name: str, body: str, front: str = "channel: bluesky") -> Path:
    path = root / "communication" / name
    path.write_text(f"---\n{front}\n---\n{body}\n", encoding="utf-8", newline="\n")
    return path


def codes(root: Path, only: str | None = None, severity: str | None = None) -> set[str]:
    return {code for code, said in found(root, only) if severity is None or said == severity}


# ------------------------------------------------------------------------------- opt-in


@pytest.mark.parametrize("verb", ["brief", "graphical-abstract", "check"])
def test_every_verb_refuses_while_paper_yaml_leaves_the_group_off(
    project: Path, verb: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["communicate", verb, str(project)]) == 2
    said = capsys.readouterr().err
    assert "communication" in said and "enabled: true" in said, said
    assert not (project / "communication").exists()


def test_check_reads_nothing_under_communication_while_the_group_is_off(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A brief that is no brief, a text full of faults and a graphical abstract that is no
    SVG change nothing `check` says, and not one of them is opened."""
    assert main(["check", str(project), "--json"]) in (0, 1)
    before = json.loads(capsys.readouterr().out)
    folder = project / "communication"
    (folder / "graphical-abstract").mkdir(parents=True)
    (folder / "brief.yaml").write_text("schema: [not a brief\n", encoding="utf-8")
    (folder / "bluesky.md").write_text("The drug caused 99 deaths. As an AI, oaicite.\n",
                                       encoding="utf-8")  # fmt: skip
    (folder / "graphical-abstract" / "concept-1.svg").write_text("<svg", encoding="utf-8")
    opened: list[str] = []
    real_open, real_io_open = builtins.open, io.open

    def watched(opener):
        def open_(file, *args, **kwargs):
            if "communication" in Path(str(file)).parts:
                opened.append(str(file))
            return opener(file, *args, **kwargs)

        return open_

    monkeypatch.setattr(builtins, "open", watched(real_open))
    monkeypatch.setattr(io, "open", watched(real_io_open))
    assert main(["check", str(project), "--json"]) in (0, 1)
    after = json.loads(capsys.readouterr().out)
    assert opened == []
    assert after["ok"] == before["ok"]
    assert [(f["code"], f["severity"]) for f in after["findings"]] == [
        (f["code"], f["severity"]) for f in before["findings"]
    ]


# ------------------------------------------------------------------------------ the brief


def test_the_brief_is_scaffolded_from_the_plan_and_the_manuscript_the_same_every_time(
    project: Path,
) -> None:
    enable(project)
    assert main(["communicate", "brief", str(project)]) == 0
    written = brief_file(project).read_bytes()
    document = yaml.safe_load(written)
    assert document["schema"] == "communication-brief/1"
    ids = {part: [one["id"] for one in document.get(part, [])] for part in brief_module.SECTIONS}
    assert ids == {
        "question": ["question.1"], "design": ["design.1"], "population": ["population.1"],
        "methods": ["methods.1"], "primary_outcome": ["primary_outcome.1"],
        "findings": ["findings.1", "findings.2"],
        "limitations": ["limitations.1", "limitations.2", "limitations.3", "limitations.4"],
        "conclusion": ["conclusion.1", "conclusion.2"],
    }  # fmt: skip
    assert document["question"][0]["from"] == {
        "file": "design/plan.md",
        "quote": "Is hepatic injury reported disproportionately often for example-drug, "
        "relative to all other drugs in the same database?",
    }
    # The plan's own title, "Analysis plan", is not its Analysis.
    assert document["methods"][0]["text"].startswith("Reporting odds ratio from the 2 x 2")
    second = document["findings"][1]
    assert second["from"]["file"] == "manuscript/main.md"
    assert second["keys"] == ["results.ror.point", "results.ror.ci_low", "results.ror.ci_high"]
    # Nothing infers the primary finding.
    assert [one["primary"] for one in document["findings"]] == [False, False]
    assert all(one["text"] == one["from"]["quote"] for part in brief_module.SECTIONS
               for one in document.get(part, []))  # fmt: skip
    assert document["conclusion"][1]["from"]["quote"] == (
        "Disproportionality is not incidence and cannot establish risk."
    )
    # The label "**Results.**" opens the part and is no part of the quote.
    assert document["findings"][0]["from"]["quote"].startswith("Of {{results.cohort.n_reports}}")
    # Written again with --force, the same bytes; without it, refused.
    assert main(["communicate", "brief", str(project)]) == 2
    assert main(["communicate", "brief", str(project), "--force"]) == 0
    assert brief_file(project).read_bytes() == written
    # What the scaffold wrote passes its own quote check.
    assert "brief-quote-not-in-source" not in codes(project, "brief")


def test_a_quote_its_file_does_not_hold_fails_and_one_rewrapped_passes(ready: Path) -> None:
    assert codes(ready, "brief", FAIL) == set()

    def rewrap(document: dict) -> None:
        quote = document["conclusion"][0]["from"]["quote"]
        document["conclusion"][0]["from"]["quote"] = quote.replace(" ", "\n  ", 2)

    edit_brief(ready, rewrap)
    assert "brief-quote-not-in-source" not in codes(ready, "brief")

    def misquote(document: dict) -> None:
        document["conclusion"][0]["from"]["quote"] = "Reporting is disproportionate."

    edit_brief(ready, misquote)
    assert "brief-quote-not-in-source" in codes(ready, "brief", FAIL)

    def elsewhere(document: dict) -> None:
        document["question"][0]["from"]["file"] = "README.md"

    edit_brief(ready, elsewhere)
    assert ("brief-quote-not-in-source", FAIL) in found(ready, "brief")


def test_a_brief_with_no_primary_finding_fails_and_one_that_is_no_brief_is_said(
    project: Path,
) -> None:
    enable(project)
    assert codes(project, "brief") == {"brief-missing"}
    main(["communicate", "brief", str(project)])
    assert "comm-primary-missing" in codes(project, "brief", FAIL)
    mark_primary(project)
    assert "comm-primary-missing" not in codes(project, "brief")
    brief_file(project).write_text("schema: communication-brief/1\nfindings: [{id: x}]\n",
                                   encoding="utf-8")  # fmt: skip
    assert codes(project, "brief", FAIL) == {"brief-invalid"}


def test_a_brief_text_that_claims_more_than_its_quote_fails(ready: Path) -> None:
    def stronger(document: dict) -> None:
        document["conclusion"][0]["text"] = "Example-drug caused hepatic injury."

    edit_brief(ready, stronger)
    assert "comm-claim-stronger" in codes(ready, "brief", FAIL)

    def shorter(document: dict) -> None:
        document["conclusion"][0]["text"] = "Reporting of hepatic injury is disproportionate."

    edit_brief(ready, shorter)
    assert codes(ready, "brief", FAIL) == set()


# ------------------------------------------------------------------------------ the texts

CLEAN = (
    "The reporting odds ratio was {{results.ror.point}} (95% CI {{results.ror.ci_low}} to "
    "{{results.ror.ci_high}}) [](#brief:findings.2). Nobody here says more."
)


def test_a_clean_text_is_told_nothing(ready: Path) -> None:
    text(ready, "bluesky.md", CLEAN)
    assert [one for one in found(ready, "texts") if one[1] != INFO] == []


#: Each code a text can be told, the text that has the fault, its channel, and whether it
#: fails or warns.
TEXT_CASES = {
    "comm-number-unbound": ("The reporting odds ratio was 3.84 [](#brief:findings.2).",
                            "channel: bluesky", FAIL),
    "comm-binding-unknown": ("It was {{results.no_such_key}} [](#brief:findings.2).",
                             "channel: bluesky", FAIL),
    "comm-claim-unanchored": ("Use was associated with hepatic injury.", "channel: bluesky",
                              FAIL),
    "comm-anchor-unknown": (CLEAN.replace("findings.2", "findings.9"), "channel: bluesky", FAIL),
    "comm-fact-not-in-source": (
        "The reporting odds ratio was {{results.ror.point}} in {{results.cohort.n_reports}} "
        "reports [](#brief:findings.2).", "channel: bluesky", FAIL),
    "comm-claim-stronger": (
        "Example-drug caused hepatic injury, with a reporting odds ratio of "
        "{{results.ror.point}} [](#brief:findings.2).", "channel: bluesky", FAIL),
    "comm-claim-weaker": (
        "The reporting odds ratio may have been {{results.ror.point}} [](#brief:findings.2).",
        "channel: bluesky", WARN),
    "comm-claim-moved": (
        "Example-drug may have caused hepatic injury, with a reporting odds ratio of "
        "{{results.ror.point}} [](#brief:findings.2).", "channel: bluesky", FAIL),
    "comm-limitation-dropped": (CLEAN, "channel: press-release", FAIL),
    "comm-primary-missing": (
        "Of {{results.cohort.n_reports}} reports, {{results.case.n_cases}} described hepatic "
        "injury with example-drug [](#brief:findings.1). Several limitations follow from the "
        "design [](#brief:limitations.1).", "channel: press-release", FAIL),
    "comm-secondary-as-primary": (
        "Of {{results.cohort.n_reports}} reports, {{results.case.n_cases}} described hepatic "
        "injury with example-drug [](#brief:findings.1). " + CLEAN, "channel: bluesky", WARN),
    "comm-status-ahead": ("Our paper is published. " + CLEAN, "channel: bluesky", FAIL),
    "comm-doi-malformed": ("Read it at doi:10.12/abc. " + CLEAN, "channel: bluesky", FAIL),
    "comm-link-temporary": ("The code is at https://drive.google.com/abc. " + CLEAN,
                            "channel: bluesky", WARN),
    "comm-over-limit": ("Read the paper. " * 25 + CLEAN, "channel: bluesky", FAIL),
    "comm-front-matter": (CLEAN, "channel: [bluesky", FAIL),
    "comm-allow-unused": (CLEAN, "channel: bluesky\nallow:\n  - sentence: words nowhere\n"
                          "    reason: a reason", WARN),
    "model-artefact": ("[insert the date] " + CLEAN, "channel: bluesky", FAIL),
}  # fmt: skip


@pytest.mark.parametrize("code", sorted(TEXT_CASES))
def test_each_code_a_text_is_told_fires_on_its_fault_and_not_on_a_clean_text(
    ready: Path, code: str
) -> None:
    body, front, severity = TEXT_CASES[code]
    text(ready, "post.md", CLEAN)
    assert code not in codes(ready, "texts")
    text(ready, "post.md", body, front)
    assert (code, severity) in found(ready, "texts"), found(ready, "texts")


def test_a_value_the_paper_reports_nowhere_fails(ready: Path) -> None:
    project, _ = load_project(ready)
    from manuscript_guard.contracts import load_namespace
    from manuscript_guard.gates.reported import _shows

    namespace, results, _lit, _report = load_namespace(project)
    reported = checking._reported_keys(project, results)
    printed = checking._printed_elsewhere(project, results)
    key = next(ref for ref, value in sorted(namespace.items())
               if ref.startswith("results.") and ref not in reported
               and not _shows(printed, value.display))  # fmt: skip
    text(ready, "post.md", f"It was {{{{{key}}}}} [](#brief:findings.2).")
    assert ("comm-not-reported", FAIL) in found(ready, "texts")
    text(ready, "post.md", CLEAN)
    assert "comm-not-reported" not in codes(ready, "texts")


def _allowing(sentence: str, reason: str = "so it is") -> str:
    return f"channel: bluesky\nallow:\n  - sentence: '{sentence}'\n    reason: '{reason}'"


_STRONGER = (
    "Example-drug caused hepatic injury, with a reporting odds ratio of "
    "{{results.ror.point}}"
)


def test_a_sentence_the_front_matter_allows_with_a_reason_is_a_note(ready: Path) -> None:
    body, _front, _severity = TEXT_CASES["comm-claim-stronger"]
    text(ready, "post.md", body, _allowing(_STRONGER + "."))
    told = found(ready, "texts")
    assert ("comm-claim-stronger", INFO) in told and ("comm-claim-stronger", FAIL) not in told
    assert "comm-allow-unused" not in {code for code, _ in told}
    # With no reason, nothing is allowed, and that is said.
    text(ready, "post.md", body, _allowing(_STRONGER, ""))
    told = found(ready, "texts")
    assert ("comm-claim-stronger", FAIL) in told and ("comm-allow-no-reason", WARN) in told


def test_an_allowed_sentence_is_the_whole_sentence_and_only_that_one(ready: Path) -> None:
    """Round 1 of #470: an entry of a few words allowed every sentence that held them."""
    body, _front, _severity = TEXT_CASES["comm-claim-stronger"]
    second = body.replace("Example-drug", "Example-drug alone")
    text(ready, "post.md", f"{body}\n\n{second}", _allowing(_STRONGER))
    told = found(ready, "texts")
    assert ("comm-claim-stronger", INFO) in told and ("comm-claim-stronger", FAIL) in told
    text(ready, "post.md", body, _allowing("caused hepatic injury"))
    told = found(ready, "texts")
    assert ("comm-claim-stronger", FAIL) in told and ("comm-allow-unused", WARN) in told
    # An entry for a sentence that claims no more than its statement allowed nothing.
    clean_sentence = CLEAN.split(" Nobody")[0].replace(" [](#brief:findings.2)", "")
    text(ready, "post.md", CLEAN, _allowing(clean_sentence))
    assert ("comm-allow-unused", WARN) in found(ready, "texts")


def test_a_published_paper_may_be_linked_and_said_published(ready: Path) -> None:
    with (ready / "paper.yaml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("publication:\n  status: accepted\n  doi: 10.1234/demo.5678\n")
    text(ready, "post.md", "Read it at https://doi.org/10.1234/demo.5678. " + CLEAN)
    assert "comm-status-ahead" in codes(ready, "texts", FAIL)
    paper = (ready / "paper.yaml").read_text(encoding="utf-8")
    (ready / "paper.yaml").write_text(paper.replace("status: accepted",
                                                    "status: published-online"),
                                      encoding="utf-8")  # fmt: skip
    text(ready, "post.md", "Our paper is published at https://doi.org/10.1234/demo.5678. "
         + CLEAN)  # fmt: skip
    assert codes(ready, "texts", FAIL) == set()


def test_a_limit_paper_yaml_gives_is_the_one_held(ready: Path) -> None:
    body = "Read the paper. " * 40 + CLEAN
    text(ready, "post.md", body, "channel: mastodon")
    assert "comm-over-limit" in codes(ready, "texts", FAIL)
    with (ready / "paper.yaml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("  limits:\n    mastodon: 5000\n")
    assert "comm-over-limit" not in codes(ready, "texts")
    # A thread is held post by post.
    thread = "\n\n---\n\n".join(["Read the paper. " * 12] * 3 + [CLEAN])
    text(ready, "post.md", thread, "channel: bluesky")
    assert "comm-over-limit" not in codes(ready, "texts")


def test_graphemes_count_what_a_reader_sees() -> None:
    assert checking.graphemes("cafe" + chr(0x301)) == 4
    family = chr(0x1F468) + chr(0x200D) + chr(0x1F469) + chr(0x200D) + chr(0x1F467)
    assert checking.graphemes(family) == 1
    assert checking.graphemes("ok" + chr(0x1F44D) + chr(0x1F3FD)) == 3


# --------------------------------------------------------------------------- the anchors


def test_an_anchor_belongs_to_its_sentence_after_its_stop_or_opening_a_paragraph() -> None:
    read = texts.read(
        "---\nchannel: x\n---\n"
        "Use was associated with it [](#brief:a.1). The ratio was {{results.r}}. "
        "[](#brief:b.1)\nNothing here.\n\n[](#brief:c.1) Signals need care. "
        "`[](#brief:d.1)` was 12 days.\n<!-- brief: e.1, e.2 -->\n\n<!-- not brief: f.1 -->\n"
    )
    assert [(s.line, bool(s.why), s.anchors) for s in read.sentences] == [
        (4, True, ("a.1",)),
        (4, True, ("b.1",)),
        (5, False, ()),
        (7, False, ("c.1",)),
        (7, True, ("e.1", "e.2")),
    ]
    assert [one.id for one in read.anchors] == ["a.1", "b.1", "c.1", "e.1", "e.2"]


def test_compare_pair_reads_a_paraphrase_against_its_source_whole() -> None:
    source = "Use was associated with a higher rate. It may reflect reporting."
    said = "Use was linked to a higher rate, which may reflect reporting."
    assert claims.compare_pair(source, said) is None
    # Read whole: the hedge of the second sentence dropped is a claim made stronger.
    assert claims.compare_pair(source, "Use was linked to a higher rate.").code == (
        claims.STRONGER
    )
    assert claims.compare_pair(source, "Use caused a higher rate.").code == claims.STRONGER
    assert claims.compare_pair("It was not seen.", "It was seen.").code == claims.NEGATION
    assert claims.compare_pair("Use increased it.", "Use was associated with it.").code == (
        claims.WEAKER
    )
    assert claims.compare_pair(source, "") is None


# ------------------------------------------------------------------- the graphical abstract


def _small_brief() -> Brief:
    path = Path("communication/brief.yaml")
    quote = "Use was associated with injury ({{results.ror}})."
    return Brief(path, (
        Statement("question.1", "question", "Is use linked to injury?", "design/plan.md",
                  "Is use linked to injury?"),
        Statement("design.1", "design", "A cohort study.", "design/plan.md", "A cohort study."),
        Statement("findings.1", "findings", quote, "manuscript/main.md", quote,
                  ("results.ror",), True),
        Statement("findings.2", "findings", "Few were *serious*.", "manuscript/main.md",
                  "Few were *serious*.", (), False),
        Statement("conclusion.1", "conclusion", "Use may matter.", "manuscript/main.md",
                  "Use may matter."),
    ))  # fmt: skip


class _Shown:
    def __init__(self, display: str) -> None:
        self.display = display


def test_the_concepts_are_the_same_bytes_from_the_same_brief_and_name_what_they_print() -> None:
    brief = _small_brief()
    template = templates.TEMPLATES["observational"]
    size = svg.size_of({})
    assert (size.width, size.height, size.default) == (1328, 531, True)
    namespace = {"results.ror": _Shown("1.85")}
    colours = ["#0072b2", "#e69f00", "#009e73"]
    one = svg.concept_1(brief, template, size, colours, namespace)
    assert one == svg.concept_1(brief, template, size, colours, namespace)
    # The bytes, pinned: a change of the drawing is seen here, and made on purpose.
    two = svg.concept_2(brief, template, size, colours, namespace)
    assert [hashlib.sha256(drawn).hexdigest() for drawn in (one, two)] == [
        "92e081630683aea152aa8955cee1f3566f6db138fe40aec4436c21d5b8cbb2fe",
        "70ab4e03ec4a6017246c1946dd88e7567007f5d989faf5e50eadbe8bb093df26",
    ]
    assert one.startswith(b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns=')
    root = ET.fromstring(one)
    assert (root.get("width"), root.get("height"), root.get("viewBox")) == (
        "1328", "531", "0 0 1328 531")  # fmt: skip
    drawn = root.findall("{http://www.w3.org/2000/svg}text")
    assert all("data-statement" in node.attrib and "data-binding" in node.attrib
               for node in drawn)  # fmt: skip
    by_statement: dict[str, list[ET.Element]] = {}
    for node in drawn:
        by_statement.setdefault(node.get("data-statement"), []).append(node)
    assert [node.text for node in by_statement[""]] == list(template.headings)
    primary = by_statement["findings.1"]
    secondary = by_statement["findings.2"]
    assert "1.85" in " ".join(node.text for node in primary)
    assert [node.get("data-binding") for node in primary if "1.85" in node.text] == [
        "results.ror"
    ]
    assert int(primary[0].get("font-size")) > int(secondary[0].get("font-size"))
    assert all(node.get("font-weight") == "bold" for node in primary)
    # Emphasis is the brief's Markdown, not the picture's words.
    assert "serious" in secondary[-1].text and "*" not in secondary[-1].text
    painted = {node.get("stroke") for node in root.iter() if node.get("stroke")}
    assert painted <= set(colours) and {node.get("fill") for node in drawn} == {"#000000"}
    two = ET.fromstring(svg.concept_2(brief, template, size, colours, namespace))
    assert {node.get("data-statement") for node in two.iter("{http://www.w3.org/2000/svg}text")
            } >= {"question.1", "findings.1", "findings.2", "conclusion.1"}  # fmt: skip


def test_the_size_is_the_journals_where_its_profile_gives_one() -> None:
    def sized(rules: dict) -> tuple[int, int, bool]:
        size = svg.size_of(rules)
        return size.width, size.height, size.default

    assert sized({"width_px": 1200, "height_px": 600}) == (1200, 600, False)
    assert sized({"aspect_ratio": "16:9", "width_px": 1600}) == (1600, 900, False)
    assert sized({"min_width_px": 2000}) == (2000, 531, False)
    assert sized({"aspect_ratio": "1:1"}) == (1328, 1328, False)


def test_the_alternative_text_is_written_from_the_brief_with_its_bindings() -> None:
    brief = _small_brief()
    said = svg.alt_text(brief, templates.TEMPLATES["rct"])
    assert said == (
        "Graphical abstract. The trial: Is use linked to injury? The result: Use was "
        "associated with injury ({{results.ror}}). What it means: Use may matter.\n"
    )


def test_the_template_follows_the_study_type() -> None:
    assert templates.chosen(None, "trial")[0].name == "rct"
    assert templates.chosen(None, "cohort")[0].name == "observational"
    assert templates.chosen(None, "prediction-model")[0].name == "computational"
    assert templates.chosen("lab", "trial")[0].name == "lab"
    assert templates.chosen(None, None)[0].name == templates.DEFAULT


def test_the_graphical_abstract_is_drawn_and_its_report_is_what_check_says(ready: Path) -> None:
    assert main(["communicate", "graphical-abstract", str(ready)]) == 0
    folder = ready / "communication" / "graphical-abstract"
    assert sorted(path.name for path in folder.iterdir()) == [
        "alt-text.md", "concept-1.svg", "concept-2.svg", "concept.md", "validation-report.md",
    ]  # fmt: skip
    project, _ = load_project(ready)
    report = checking.check(project, only="graphical-abstract")
    assert (folder / "validation-report.md").read_text(encoding="utf-8") == checking.render(
        report, ready, "communicate check --only graphical-abstract"
    )
    assert [(one.code, one.severity) for one in report.findings] == [
        ("comm-ga-size-default", INFO)
    ]
    first = (folder / "concept-1.svg").read_bytes()
    assert main(["communicate", "graphical-abstract", str(ready)]) == 0
    assert (folder / "concept-1.svg").read_bytes() == first
    assert "{{results.ror.point}}" in (folder / "alt-text.md").read_text(encoding="utf-8")


def test_the_graphical_abstract_is_refused_without_a_primary_finding(project: Path) -> None:
    enable(project)
    main(["communicate", "brief", str(project)])
    assert main(["communicate", "graphical-abstract", str(project)]) == 2


def _drawn(root: Path) -> Path:
    assert main(["communicate", "graphical-abstract", str(root)]) == 0
    return root / "communication" / "graphical-abstract" / "concept-1.svg"


def test_a_line_whose_value_changed_or_whose_words_were_edited_fails(ready: Path) -> None:
    concept = _drawn(ready)
    drawn = concept.read_text(encoding="utf-8")
    assert codes(ready, "graphical-abstract", FAIL) == set()
    concept.write_text(drawn.replace("ratio was 3.84", "ratio was"), encoding="utf-8")
    assert "comm-ga-stale" in codes(ready, "graphical-abstract", FAIL)
    concept.write_text(drawn.replace(">The reporting odds<", ">The striking odds<"),
                       encoding="utf-8")  # fmt: skip
    assert "comm-ga-text-not-in-statement" in codes(ready, "graphical-abstract", FAIL)
    concept.write_text(drawn.replace('data-statement="findings.2"', 'data-statement="x.9"', 1),
                       encoding="utf-8")  # fmt: skip
    assert "comm-anchor-unknown" in codes(ready, "graphical-abstract", FAIL)
    concept.write_text(drawn.replace('data-binding="results.ror.point"',
                                     'data-binding="results.nope"'), encoding="utf-8")  # fmt: skip
    assert "comm-binding-unknown" in codes(ready, "graphical-abstract", FAIL)
    label = ('<text x="5" y="5" font-size="20" data-statement="" data-binding="">'
             "12 sites</text></svg>")  # fmt: skip
    concept.write_text(drawn.replace("</svg>", label), encoding="utf-8")
    told = codes(ready, "graphical-abstract", FAIL)
    assert {"comm-number-unbound", "comm-claim-unanchored"} <= told


def test_a_graphical_abstract_that_draws_no_primary_finding_fails(ready: Path) -> None:
    concept = _drawn(ready)
    drawn = concept.read_text(encoding="utf-8")
    kept = re.sub(r'\s*<text[^>]*data-statement="findings\.2"[^>]*>[^<]*</text>', "", drawn)
    concept.write_text(kept, encoding="utf-8")
    assert "comm-primary-missing" in codes(ready, "graphical-abstract", FAIL)
    concept.write_text(drawn, encoding="utf-8")
    mark_primary(ready, "findings.1")
    assert ("comm-secondary-as-primary", WARN) in found(ready, "graphical-abstract")


def test_the_graphical_abstract_is_held_to_the_journals_rules(ready: Path) -> None:
    _drawn(ready)
    profile = ready / "profiles" / "journals" / "demo-journal.yaml"
    rules = ("\ngraphical_abstract:\n  width_px: 1000\n  height_px: 500\n  aspect_ratio: '2:1'"
             "\n  max_words: 10\n  max_labels: 2\n  alt_text_max_chars: 50\n")  # fmt: skip
    profile.write_text(profile.read_text(encoding="utf-8") + rules, encoding="utf-8")
    told = found(ready, "graphical-abstract")
    for code in ("comm-ga-size", "comm-ga-aspect", "comm-ga-words", "comm-ga-labels",
                 "comm-alt-long"):  # fmt: skip
        assert (code, WARN) in told, (code, told)
    assert "comm-ga-size-default" not in {code for code, _ in told}
    # Drawn again, at the journal's size.
    _drawn(ready)
    told = {code for code, _ in found(ready, "graphical-abstract")}
    assert not told & {"comm-ga-size", "comm-ga-aspect"}, told


def test_an_alternative_text_missing_or_with_a_typed_number_is_told(ready: Path) -> None:
    _drawn(ready)
    alt = ready / "communication" / "graphical-abstract" / "alt-text.md"
    alt.write_text("The odds ratio was 3.84.\n", encoding="utf-8")
    assert ("figure-alt-number", FAIL) in found(ready, "graphical-abstract")
    alt.unlink()
    assert ("comm-alt-missing", WARN) in found(ready, "graphical-abstract")


def test_colours_that_one_reader_cannot_tell_apart_are_warned(ready: Path) -> None:
    concept = _drawn(ready)
    drawn = concept.read_text(encoding="utf-8")
    added = ('<rect x="1" y="1" width="5" height="5" fill="#d62728" />'
             '<rect x="9" y="1" width="5" height="5" fill="#2ca02c" /></svg>')  # fmt: skip
    concept.write_text(drawn.replace("</svg>", added), encoding="utf-8")
    assert "figure-colours-confused" in codes(ready, "graphical-abstract", WARN)


def test_the_json_lists_failures_apart_from_warnings(
    ready: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text(ready, "post.md", TEXT_CASES["comm-claim-weaker"][0])
    shutil.rmtree(ready / "communication" / "graphical-abstract", ignore_errors=True)
    assert main(["communicate", "check", str(ready), "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["ok"] is True and said["failures"] == []
    assert [one["code"] for one in said["warnings"]] == ["comm-claim-weaker"]
    assert said["warnings"][0]["path"] == "communication/post.md"
    text(ready, "post.md", TEXT_CASES["comm-claim-stronger"][0])
    assert main(["communicate", "check", str(ready)]) == 1
    assert main(["communicate", "check", str(ready), "--only", "brief"]) == 0
    assert main(["communicate", "brief", str(ready), "--json"]) == 2


# ------------------------------------------------------------------- round 1 of #470


def test_an_anchor_opening_its_line_before_a_sentence_is_that_sentences() -> None:
    """Finding 1: as docs/communicate.md writes it, a comment opening a line is the anchor
    of the sentence after it on that line; one after a stop on the stop's line is the
    sentence's before."""
    read = texts.read("A was associated [](#brief:f.1).\n<!-- brief: l.1 --> B caused it.")
    assert [s.anchors for s in read.sentences] == [("f.1",), ("l.1",)]
    read = texts.read("A was associated. [](#brief:f.1)\nB caused it.")
    assert [s.anchors for s in read.sentences] == [("f.1",), ()]


@pytest.mark.parametrize(
    ("before", "code"),
    [
        # Finding 2: a mention and a hashtag are no citation and no number.
        ("With @alice.bsky.social and #covid19 in mind: ", "comm-fact-not-in-source"),
        ("With @alice.bsky.social and #covid19 in mind: ", "comm-number-unbound"),
        # Finding 3: "published" said of other work.
        ("Previously published studies differ. ", "comm-status-ahead"),
        ("Published reports differ. ", "comm-status-ahead"),
        ("See https://example.org/published/1 too. ", "comm-status-ahead"),
        # Finding 4: a thread's counter.
        ("1/3 " + chr(0x1F9F5) + " ", "comm-number-unbound"),
        ("1/3 ", "comm-claim-unanchored"),
    ],
)
def test_what_a_post_holds_and_the_paper_does_not_is_no_fault(
    ready: Path, before: str, code: str
) -> None:
    text(ready, "post.md", before + CLEAN)
    assert code not in codes(ready, "texts")


def test_a_counter_at_the_end_of_a_post_is_no_number_and_a_fraction_is_one(ready: Path) -> None:
    text(ready, "post.md", CLEAN + " 2/3")
    assert codes(ready, "texts", FAIL) == set()
    text(ready, "post.md", CLEAN + " It was 3/4")
    assert "comm-number-unbound" in codes(ready, "texts", FAIL)


def test_this_paper_said_published_or_its_url_linked_is_ahead(ready: Path) -> None:
    with (ready / "paper.yaml").open("a", encoding="utf-8", newline="\n") as handle:
        handle.write("publication:\n  status: accepted\n  url: https://journal.example/a/1\n")
    for said in ("Our study is published today. ", "We have just published it. ",
                 "Read it at https://journal.example/a/1 now. ",
                 # A headline that says it is out.
                 "Published: hepatic injury and example-drug. ", "Now published in X. ",
                 "Just published! ", chr(0x1F389) + " Out now! ", "**Out today.** ",
                 "Published in X this week. "):  # fmt: skip
        text(ready, "post.md", said + CLEAN)
        assert "comm-status-ahead" in codes(ready, "texts", FAIL), said
    for said in ("Our study will be published soon. ", "Published reports differ. ",
                 "Previously published studies differ. ", "Out of the sites, none. "):  # fmt: skip
        text(ready, "post.md", said + CLEAN)
        assert "comm-status-ahead" not in codes(ready, "texts"), said


def test_a_thread_is_parted_at_a_rule_after_a_blank_line_and_not_at_an_underline() -> None:
    """Finding 11."""
    assert len(texts.read("Title\n---\nA post.\n").posts) == 1
    assert len(texts.read("A post.\n\n---\n\nAnother.\n").posts) == 2
    assert len(texts.read("A post.\n\n***\n\nStill it.\n").posts) == 1


def test_a_drawn_line_left_without_its_negation_claims_more_than_its_statement(
    ready: Path,
) -> None:
    """Finding 5: each line is in its statement, and the lines left draw a claim the paper
    does not make."""
    concept = _drawn(ready)
    drawn = concept.read_text(encoding="utf-8")
    lines = re.findall(r'\s*<text[^>]*data-statement="conclusion\.2"[^>]*>[^<]*</text>', drawn)
    holding = [line for line in lines if "cannot" in line]
    assert holding and not any("cannot" in line and " not " in line for line in lines)
    concept.write_text(drawn.replace(holding[0], ""), encoding="utf-8")
    told = found(ready, "graphical-abstract")
    assert ("comm-claim-stronger", FAIL) in told
    assert "comm-ga-text-not-in-statement" not in {code for code, _ in told}


def test_a_heading_line_is_no_statement(project: Path) -> None:
    """Finding 6: a heading over the limitations, and one over the abstract's conclusion."""
    paper = project / "manuscript" / "main.md"
    written = paper.read_text(encoding="utf-8")
    written = written.replace("**Conclusions.** ", "### Conclusions\n\n").replace(
        "Several limitations follow", "## Limitations\n\nSeveral limitations follow")
    paper.write_text(written, encoding="utf-8")
    enable(project)
    assert main(["communicate", "brief", str(project)]) == 0
    document = yaml.safe_load(brief_file(project).read_text(encoding="utf-8"))
    said = [one["text"] for part in brief_module.SECTIONS for one in document.get(part, [])]
    assert not [one for one in said if one.lstrip().startswith("#")], said
    assert document["limitations"][0]["text"] == "Several limitations follow from the design."
    assert document["conclusion"][0]["text"].startswith("Reporting of hepatic injury")


def test_a_label_this_does_not_know_ends_the_conclusion(project: Path) -> None:
    """Finding 7: a trial's registration and the funding after the conclusion are neither
    conclusion nor result."""
    paper = project / "manuscript" / "main.md"
    written = paper.read_text(encoding="utf-8")
    added = ("cannot establish risk.\n**Funding.** None was received.\n"
             "Trial Registration ClinicalTrials.gov Identifier: NCT01234567.\n")  # fmt: skip
    paper.write_text(written.replace("cannot establish risk.\n", added, 1), encoding="utf-8")
    enable(project)
    assert main(["communicate", "brief", str(project)]) == 0
    document = yaml.safe_load(brief_file(project).read_text(encoding="utf-8"))
    assert [one["id"] for one in document["conclusion"]] == ["conclusion.1", "conclusion.2"]
    assert brief_module.opening("**Results**. Of 4000 reports")[1] == "results"


def test_a_quote_cut_from_inside_a_sentence_fails(ready: Path) -> None:
    """Finding 8: "cannot establish risk" of "Disproportionality is not incidence and cannot
    establish risk." is no sentence of the paper."""
    def cut(document: dict) -> None:
        document["conclusion"][1]["from"]["quote"] = "cannot establish risk."
        document["conclusion"][1]["text"] = "cannot establish risk."

    edit_brief(ready, cut)
    assert "brief-quote-not-in-source" in codes(ready, "brief", FAIL)

    def two(document: dict) -> None:
        both = ("Reporting of hepatic injury is disproportionate for example-drug in these "
                "synthetic data. Disproportionality is not incidence and cannot establish risk.")
        source = {"file": "manuscript/main.md", "quote": both}
        document["conclusion"] = [{"id": "conclusion.1", "text": both, "from": source}]

    edit_brief(ready, two)
    assert "brief-quote-not-in-source" not in codes(ready, "brief")


def test_the_limitations_are_the_discussions_not_the_introductions(project: Path) -> None:
    """Finding 16."""
    paper = project / "manuscript" / "main.md"
    written = paper.read_text(encoding="utf-8")
    paper.write_text(written.replace(
        "Whether the signal extends", "Earlier studies had limitations of their own.\n\n"
        "Whether the signal extends", 1), encoding="utf-8")  # fmt: skip
    enable(project)
    assert main(["communicate", "brief", str(project)]) == 0
    document = yaml.safe_load(brief_file(project).read_text(encoding="utf-8"))
    assert document["limitations"][0]["text"] == "Several limitations follow from the design."


def test_a_statement_is_drawn_as_printed_without_its_markup() -> None:
    """Finding 13: a citation, a list's marker and emphasis are not drawn, and a pointer is
    the number the build gives it."""
    shown = {"ref.table.t": svg.Shown("Table 2"), "results.r": _Shown("1.85")}
    said = svg.printed("- Use was *linked* [@smith2020] to it ({{ref.table.t}}), "
                       "{{results.r}}.", shown)  # fmt: skip
    assert said == "Use was linked to it (Table 2), 1.85."
    brief = Brief(Path("b.yaml"), (
        Statement("question.1", "question", "> Is it? See {{num.table.t}}.", "f", "q"),
        Statement("findings.1", "findings", "It was {{results.r}} @smith2020.", "f", "q",
                  ("results.r",), True),
    ))  # fmt: skip
    alt = svg.alt_text(brief, templates.TEMPLATES["rct"], {"num.table.t": svg.Shown("2")})
    assert alt == ("Graphical abstract. The trial: Is it? See 2. The result: It was "
                   "{{results.r}}.\n")  # fmt: skip
