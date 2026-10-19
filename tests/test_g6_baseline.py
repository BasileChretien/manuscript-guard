"""`tools/g6_baseline.py`, which measures how often G6 fires on papers written by people.

The script reads Europe PMC; these tests give it a fake transport and never open a
connection. What they hold is what the record says: which papers count, how a threshold is
set, whether the held-out papers keep to the budget, and what is written into the rules.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PANDOC = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(PANDOC is None, reason="pandoc is not installed")


def _tool():
    spec = importlib.util.spec_from_file_location("g6_baseline", REPO / "tools" / "g6_baseline.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _tool()

#: A research article under CC BY: its type and licence as JATS writes them.
JATS = (
    '<?xml version="1.0"?><article article-type="{kind}" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta><permissions>'
    '<license xlink:href="https://creativecommons.org/licenses/{licence}/4.0/"/>'
    "</permissions></article-meta></front><body><sec><title>Introduction</title>"
    "<p>{text}</p></sec></body></article>"
)
#: Clean prose, with an em dash and "robust" in its technical sense, as people write it.
PROSE = (
    "We enrolled the patients who were admitted to the ward during the study period and we "
    "followed them until discharge or death. The cohort was described by age, sex and the "
    "reason for admission — the last taken from the chart, with a robust variance estimator. "
)


def _markdown(words: int = 1200) -> str:
    repeated = PROSE * (words // len(PROSE.split()) + 1)
    references = "# References\n\n1. Smith J. A title, a journal. 2019.\n"
    return f"# Introduction\n\n{repeated}\n\n{references}"


def test_the_body_runs_from_the_first_heading_to_the_reference_list() -> None:
    text = "Received 2014 Sep 4.\n\n# Introduction\n\nText.\n\n## References {#r}\n\n1. A.\n"
    assert tool.body_of(text) == "# Introduction\n\nText.\n\n"
    assert tool.body_of("No heading at all.\n") is None


@pytest.mark.parametrize(
    ("kind", "licence", "status"),
    [("research-article", "by", "used"), ("review-article", "by", "excluded"),
     ("research-article", "by-nc", "excluded")],
)  # fmt: skip
def test_only_a_research_article_under_cc_by_is_used(kind: str, licence: str, status: str) -> None:
    xml = JATS.format(kind=kind, licence=licence, text="x").encode()
    assert tool.measure_one({"pmcid": "PMC1"}, xml, _markdown())["status"] == status


@pytest.mark.parametrize(
    ("stated", "licences"),
    [
        ("This is an open-access article distributed under the terms of the Creative Commons "
         "Attribution License, which permits unrestricted use.", {"by"}),
        ("distributed under the Creative Commons\n  Attribution Licence", {"by"}),
        ("under the Creative Commons Attribution License (CC BY-NC), Non-Commercial use", set()),
        ("under the Creative Commons Attribution-NonCommercial License", set()),
        ("All rights reserved.", set()),
        # Round 1 of #339: a version, "International" or "(CC BY)" before "License".
        ("under a Creative Commons Attribution 4.0 International License", {"by"}),
        ("distributed under the Attribution (CC BY) license", {"by"}),
        ("under a Creative Commons Attribution-NonCommercial 4.0 International License", set()),
        # Round 2 of #339: CC 3.0's own titles of its further terms.
        ("under a Creative Commons Attribution-Noncommercial-Share Alike 3.0 Unported License",
         set()),
        ("under a Creative Commons Attribution-Noncommercial-No Derivative Works 3.0 Unported "
         "License", set()),
    ],
)  # fmt: skip
def test_a_licence_stated_in_words_is_read(stated: str, licences: set[str]) -> None:
    """The first measurement excluded 69 articles whose CC BY licence is named in words, with
    no link, as stating none."""
    assert tool.licences_of(f"<license><license-p>{stated}</license-p></license>") == licences


def test_a_short_or_unread_paper_is_said_so() -> None:
    xml = JATS.format(kind="research-article", licence="by", text="x").encode()
    assert tool.measure_one({"pmcid": "PMC1"}, xml, _markdown(300))["status"] == "too-short"
    assert tool.measure_one({"pmcid": "PMC1"}, xml, None)["status"] == "garbled"
    assert tool.measure_one({"pmcid": "PMC1"}, xml, "no heading\n")["status"] == "garbled"


def test_a_paper_used_records_its_rates_and_findings_and_not_its_text() -> None:
    xml = JATS.format(kind="research-article", licence="by", text="x").encode()
    measured = tool.measure_one({"pmcid": "PMC1"}, xml, _markdown())
    assert measured["status"] == "used" and measured["words"] >= 1000
    # Every rule counted by rate, the two phrases counted so since 2026-10-19 among them.
    assert set(measured["rates"]) == {"ai-vocabulary", "em-dash", "boldface", "rule-of-three",
                                      "copula-avoidance", "negative-parallelism",
                                      "plays-a-role"}  # fmt: skip
    assert measured["rates"]["em-dash"] > 0
    # "A robust variance estimator" is a technical sense, exempt from the vocabulary rate.
    assert measured["rates"]["ai-vocabulary"] == 0
    assert "We enrolled" not in json.dumps(measured)


def test_years_share_the_papers_in_proportion_and_add_up() -> None:
    shares = tool._shares({2010: 10, 2011: 30, 2012: 60}, 7)
    assert sum(shares.values()) == 7 and shares == {2010: 1, 2011: 2, 2012: 4}


def test_the_draw_is_seeded_sets_papers_aside_and_opens_no_connection() -> None:
    """A fake Europe PMC that answers every year with a count and every day with articles of
    its own: the draw takes `CANDIDATES` of them, `HELD_OUT` held out, the same each time."""
    import urllib.parse

    def fake(url: str) -> bytes:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
        day = query.rsplit("FIRST_PDATE:[", 1)[1].split(" TO ")[0]
        listed = [{"pmcid": f"PMC{day.replace('-', '')}{n}", "doi": None,
                   "firstPublicationDate": day} for n in range(3)]  # fmt: skip
        return json.dumps({"hitCount": 100, "resultList": {"result": listed}}).encode()

    first = tool.draw(fake)
    assert len(first["candidates"]) == tool.CANDIDATES
    assert sum(c["set"] == "held-out" for c in first["candidates"]) == tool.HELD_OUT
    assert len({c["pmcid"] for c in first["candidates"]}) == tool.CANDIDATES
    assert tool.draw(fake)["candidates"] == first["candidates"]


def test_a_full_text_that_cannot_be_had_is_unreadable(tmp_path: Path) -> None:
    def fake(url: str) -> bytes:
        if "PMC2" in url:
            raise OSError("404")
        return b"<article/>"

    corpus = {"candidates": [{"pmcid": "PMC1", "set": "tune"}, {"pmcid": "PMC2", "set": "tune"}]}
    fetched = tool.fetch_all(corpus, tmp_path / "cache", fake, pause=0)
    assert fetched["candidates"][0]["xml_sha256"] and "status" not in fetched["candidates"][0]
    assert fetched["candidates"][1]["status"] == "unreadable"


def _corpus(tune: int = 300, held: int = 100, warn: int = 0, fail: int = 0) -> dict:
    """A measured corpus: tuning papers whose em-dash rates run 0.0 to 2.99, and held-out
    papers, `warn` of them with three phrases and `fail` with an artefact."""
    def paper(n: int, part: str, phrases: int = 0, failures: int = 0) -> dict:
        rates = {"em-dash": n / 100, "ai-vocabulary": 1.0}
        return {"pmcid": f"PMC{part}{n}", "set": part, "status": "used", "xml_sha256": "x",
                "rates": rates, "failures": failures, "phrase_findings": phrases,
                "vague_findings": 0, "other_warnings": 0, "fired": {}}  # fmt: skip

    return {
        "percentile": 99, "budget": {"failures": 0, "warnings": 2, "share": 0.95},
        "minimum": {"tune": 250, "held-out": 80}, "drawn_on": "2026-10-19",
        "candidates": [paper(n, "tune") for n in range(tune)]
        + [paper(n, "held-out", 3 if n < warn else 0, 1 if n < fail else 0) for n in range(held)],
    }  # fmt: skip


def test_a_threshold_is_the_stated_percentile_rounded_up_to_a_tenth() -> None:
    """Of 300 rates 0.00 to 2.99, the nearest-rank 99th percentile is the 297th, 2.96, and
    the threshold 3.0: no more than 1% of the tuning papers lie above it."""
    assert tool.percentile([0.01 * n for n in range(300)], 99) == pytest.approx(2.96)
    assert tool.thresholds(_corpus())["em-dash"] == 3.0
    assert tool.thresholds(_corpus())["ai-vocabulary"] == 1.0


def test_the_held_out_papers_are_held_to_the_budget() -> None:
    assert tool.judge(_corpus())["budget_met"] is True
    assert tool.judge(_corpus(warn=6))["budget_met"] is False
    assert tool.judge(_corpus(fail=1))["budget_met"] is False


def test_nothing_is_reported_from_too_few_papers_or_an_unmeasured_one() -> None:
    with pytest.raises(SystemExit, match="too few"):
        tool.judge(_corpus(tune=200))
    unmeasured = _corpus()
    del unmeasured["candidates"][0]["status"]
    with pytest.raises(SystemExit, match="does not add up"):
        tool.judge(unmeasured)


def test_the_accounting_adds_up_to_the_candidates() -> None:
    corpus = _corpus()
    corpus["candidates"][0].update(status="excluded")
    corpus["candidates"][1].update(status="too-short")
    counted = tool.accounting(corpus)
    assert counted["tune"]["used"] == 298 and counted["tune"]["excluded"] == 1
    assert sum(sum(part.values()) for part in counted.values()) == 400


def test_apply_writes_each_threshold_with_where_it_came_from(tmp_path: Path) -> None:
    """Written once above a rule that had none, and replaced, not doubled, the next time.
    The rules are the shipped ones with the measured thresholds' notes taken out."""
    shipped = (REPO / "src" / "manuscript_guard" / "data" / "ai_writing.yaml").read_text(
        encoding="utf-8")  # fmt: skip
    noted = r"(?m)^    # The \d+th percentile.*\n    # \(tools/g6_baseline\.py.*\n"
    assert re.findall(noted, shipped), "the shipped rules carry no measured threshold"
    rules = tmp_path / "ai_writing.yaml"
    rules.write_text(re.sub(noted, "", shipped), encoding="utf-8")
    corpus = _corpus()
    judged = tool.judge(corpus)
    tool.apply({"em-dash": 3.0, "copula-avoidance": 0.4}, judged, corpus, rules)
    tool.apply({"em-dash": 3.1, "copula-avoidance": 0.4}, judged, corpus, rules)
    text = rules.read_text(encoding="utf-8")
    assert "  - id: em-dash\n    # The 99th percentile of 300 papers by people\n" in text
    assert "    per_1000: 3.1\n" in text and "    per_1000: 3.0\n" not in text
    assert text.count("# (tools/g6_baseline.py, corpus") == 2
    assert "verbs: [serves as" in text and "    per_1000: 0.4\n" in text


@needs_pandoc
def test_a_paper_is_read_through_pandoc_s_jats_reader(tmp_path: Path) -> None:
    path = tmp_path / "paper.xml"
    path.write_text(JATS.format(kind="research-article", licence="by", text="Some text."),
                    encoding="utf-8")  # fmt: skip
    markdown = tool.to_markdown(path, PANDOC)
    assert markdown is not None and tool.body_of(markdown).startswith("# Introduction")


@needs_pandoc
def test_a_paper_s_dashes_are_kept_and_its_tables_left_out(tmp_path: Path) -> None:
    """Round 1 of #339: pandoc's Markdown wrote an em dash as "---", which G6 does not
    count, so the first measurement saw one in 18 papers of 384; and a table's bold, which a
    manuscript's emitted tables never show G6, counted towards the rate."""
    table = ("<table-wrap><label>Table 1</label><caption><title><bold>Table 1.</bold> "
             "Cohort</title></caption><table><tr><td><bold>0.03</bold></td>"
             "<td><bold>0.04</bold></td></tr></table><table-wrap-foot><p><bold>Bold</bold> "
             "values differ.</p></table-wrap-foot></table-wrap>")  # fmt: skip
    text = "The cohort \N{EM DASH} all adults \N{EM DASH} was followed for 1\N{EN DASH}2 years."
    path = tmp_path / "paper.xml"
    path.write_text(JATS.format(kind="research-article", licence="by", text=text)
                    .replace("</sec>", table + "</sec>"), encoding="utf-8")  # fmt: skip
    body = tool.body_of(tool.to_markdown(path, PANDOC))
    assert body.count("\N{EM DASH}") == 2 and "\N{EN DASH}" in body and "---" not in body
    # Round 2 of #339: the caption and the foot of a table are kept outside it, in the
    # table-wrap, and were counted.
    assert "0.03" not in body and "**" not in body and "values differ" not in body


def test_a_pandoc_that_does_not_finish_marks_the_paper_garbled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 1 of #339: a timeout raised, and the run was lost with every paper in it. It is
    now a paper pandoc could not read, as any other failure of pandoc's."""
    import subprocess

    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 120)

    monkeypatch.setattr(tool.subprocess, "run", slow)
    assert tool.to_markdown(tmp_path / "paper.xml", "pandoc") is None
    xml = JATS.format(kind="research-article", licence="by", text="Some text.").encode()
    assert tool.measure_one({"pmcid": "PMC1"}, xml, None) == {
        "status": "garbled", "why": "pandoc failed"
    }
