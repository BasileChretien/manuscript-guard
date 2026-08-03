"""The literature chain: quote in source, value in quote, and who may sign an attestation.

This is the strongest claim the toolkit can make about a number it did not compute, so it
gets tested the same way the number gate does — by breaking each link and requiring the
break to be reported.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from manuscript_guard.contracts import load_namespace, load_project
from manuscript_guard.gates import check_literature_chain
from manuscript_guard.literature import (
    UnreadableSource,
    contains,
    normalise,
    read_source,
    states_value,
)

LEDGER = Path("literature") / "ledger.yaml"
ATTESTED = Path("literature") / "attested.yaml"


def chain_report(root: Path):
    project, _ = load_project(root)
    _ns, _results, literature, _ = load_namespace(project)
    return check_literature_chain(project, literature)


def codes(report) -> set[str]:
    return {f.code for f in report.failures}


def edit_yaml(path: Path, mutate) -> None:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True), encoding="utf-8")


# ---------------------------------------------------------------- the chain holds


def test_the_example_chain_verifies(project: Path) -> None:
    report = chain_report(project)
    assert report.ok, report.render(project)
    assert report.counts["literature_verified"] == 2, "both ledger quotes must be checked"
    assert report.counts["literature_unverifiable"] == 0


def test_an_abstract_only_value_is_noted_but_does_not_fail(project: Path) -> None:
    report = chain_report(project)
    assert report.ok
    assert any(f.code == "value-from-abstract" for f in report.findings)


# ---------------------------------------------------------------- breaking each link


def test_a_quote_that_is_not_in_the_source_is_caught(project: Path) -> None:
    def mutate(document):
        document["entries"][0]["quote"] = "The prevalence was 99 per 100 000 person-years."

    edit_yaml(project / LEDGER, mutate)
    assert "quote-not-in-source" in codes(chain_report(project))


def test_a_retyped_quote_that_drifts_is_caught(project: Path) -> None:
    """Close is not the same. A paraphrase is not evidence."""

    def mutate(document):
        document["entries"][0]["quote"] = (
            "The crude incidence of hepatic injury was 14 per 100 000 person-years."
        )  # "drug-induced" dropped

    edit_yaml(project / LEDGER, mutate)
    assert "quote-not-in-source" in codes(chain_report(project))


def test_a_value_missing_from_its_own_quote_is_caught(project: Path) -> None:
    def mutate(document):
        document["entries"][0]["value"] = 17.0
        document["entries"][0]["display"] = "17"

    edit_yaml(project / LEDGER, mutate)
    assert "value-not-in-quote" in codes(chain_report(project))


def test_a_replaced_source_is_caught(project: Path) -> None:
    source = project / "literature" / "sources" / "fictionalHepaticCohort2021.txt"
    source.write_text("A different paper entirely.\n", encoding="utf-8")
    assert "quote-not-in-source" in codes(chain_report(project))


def test_an_unreadable_source_warns_rather_than_passing(project: Path) -> None:
    def mutate(document):
        document["entries"][0]["source_file"] = "sources/fictionalHepaticCohort2021.docx"

    sources = project / "literature" / "sources"
    (sources / "fictionalHepaticCohort2021.docx").write_bytes(b"PK\x03\x04")
    edit_yaml(project / LEDGER, mutate)
    report = chain_report(project)
    assert any(f.code == "source-unreadable" for f in report.warnings)
    assert report.counts["literature_unverifiable"] == 1


# ---------------------------------------------------------------- attestations


def test_a_model_may_not_sign_an_attestation(project: Path) -> None:
    """The file exists to record that a person vouched for the value."""

    def mutate(document):
        document["entries"][0]["attested_by"] = "claude-opus-5"

    edit_yaml(project / ATTESTED, mutate)
    report = chain_report(project)
    assert "attestation-not-human" in codes(report)
    assert any("a named person must sign it" in (f.hint or "") for f in report.failures)


@pytest.mark.parametrize("name", ["GPT-5", "Gemini", "an AI assistant", "the bot", "OpenAI"])
def test_model_names_are_recognised_in_several_forms(project: Path, name: str) -> None:
    def mutate(document):
        document["entries"][0]["attested_by"] = name

    edit_yaml(project / ATTESTED, mutate)
    assert "attestation-not-human" in codes(chain_report(project))


@pytest.mark.parametrize(
    "name", ["Ai Tanaka", "Aiko Sato", "Mai Nakamura", "Alain Dubois", "Raina Aikens"]
)
def test_a_real_name_is_not_mistaken_for_a_model(name: str) -> None:
    """`ai\\b` was on the deny-list, so `attested_by: "Ai Tanaka"` was refused.

    Ai is a common Japanese given name, and this toolkit is written at a Japanese
    university. Refusing a co-author's signature is a worse failure than the one the entry
    guarded against — the acronym is now matched case-sensitively, because AI is a machine
    and Ai is a person.
    """
    from manuscript_guard.gates.literature import _MODEL_NAME

    assert not _MODEL_NAME.search(name)


@pytest.mark.parametrize("name", ["AI", "A.I.", "an AI assistant", "a bot", "Claude", "GPT-4"])
def test_a_model_is_still_recognised(name: str) -> None:
    from manuscript_guard.gates.literature import _MODEL_NAME

    assert _MODEL_NAME.search(name)


def test_a_person_may_sign_an_attestation(project: Path) -> None:
    def mutate(document):
        document["entries"][0]["attested_by"] = "Basile Chrétien"

    edit_yaml(project / ATTESTED, mutate)
    assert chain_report(project).ok


def test_a_thin_attestation_warns(project: Path) -> None:
    def mutate(document):
        document["entries"][0]["statement"] = "Read it."

    edit_yaml(project / ATTESTED, mutate)
    report = chain_report(project)
    assert any(f.code == "attestation-thin" for f in report.warnings)


def test_an_attestation_needs_no_stored_source(project: Path) -> None:
    report = chain_report(project)
    assert not any("agency.withdrawn_estimate" in f.message for f in report.failures)


# ---------------------------------------------------------------- reading sources


@pytest.mark.parametrize(
    ("stored", "quoted"),
    [
        ("The prevalence was 12.4%.", "The prevalence was 12.4%."),
        ("It rose by 3–4 points.", "It rose by 3-4 points."),          # en dash vs hyphen
        ("The authors’ view", "The authors' view"),                    # curly apostrophe
        ("a “clear” signal", 'a "clear" signal'),                      # curly quotes
        ("wrapped over\ntwo lines", "wrapped over two lines"),         # line wrapping
        ("the ﬁnal ﬁgure", "the final figure"),                        # ligatures
    ],
)
def test_typographic_differences_do_not_break_a_true_quote(stored: str, quoted: str) -> None:
    """A quote copied from a rendered page and the same text from a PDF differ cosmetically."""
    assert contains(stored, quoted)


def test_a_genuinely_different_quote_is_not_forgiven() -> None:
    assert not contains("The prevalence was 12.4%.", "The prevalence was 12.5%.")


QUOTE = "the reporting odds ratio for hepatic events was 13.42 (95% CI 9.10 to 19.80)"


@pytest.mark.parametrize("display", ["3.4", "13.4", "9.1", "1", "3.42"])
def test_a_value_hiding_inside_a_longer_number_is_not_stated_by_the_quote(display: str) -> None:
    """`contains` is a substring test, which is right for prose and wrong for a value.

    A ledger entry of 3.4 passed against this quote because "3.4" sits inside "13.42".
    Both literature checks went green and the manuscript attributed an ROR of 3.4 to a
    paper reporting 13.42 — a misquotation of a real source, which is worse than an
    unsourced number because it carries a citation and looks checked.
    """
    assert contains(QUOTE, display), "the substring really is there; that is the problem"
    assert not states_value(QUOTE, display)


@pytest.mark.parametrize("display", ["13.42", "9.10", "19.80", "95%"])
def test_a_value_the_quote_really_states_still_passes(display: str) -> None:
    assert states_value(QUOTE, display)


def test_html_sources_are_read_as_text(tmp_path: Path) -> None:
    path = tmp_path / "page.html"
    path.write_text(
        "<html><style>p{color:red}</style><body><p>The rate was <b>7.2</b> per 1000.</p>"
        "<script>var x = 99;</script></body></html>",
        encoding="utf-8",
    )
    text = read_source(path)
    assert "7.2" in text
    assert "99" not in text, "script contents are not the article"
    assert "color:red" not in text


def test_an_unsupported_format_says_what_to_do(tmp_path: Path) -> None:
    path = tmp_path / "scan.tiff"
    path.write_bytes(b"II*\x00")
    with pytest.raises(UnreadableSource, match="save the passage as .txt"):
        read_source(path)


def test_normalise_is_idempotent() -> None:
    once = normalise("  a  “b”  –  c  ")
    assert normalise(once) == once
