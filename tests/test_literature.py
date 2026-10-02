"""The literature chain: quote in source, value in quote, and who may sign an attestation.

This is the strongest claim the toolkit can make about a number it did not compute, so it
gets tested the same way the number gate does — by breaking each link and requiring the
break to be reported.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import types
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
    sources,
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


FF = "\N{LATIN SMALL LIGATURE FF}"
FFI = "\N{LATIN SMALL LIGATURE FFI}"
FFL = "\N{LATIN SMALL LIGATURE FFL}"


@pytest.mark.parametrize(
    ("stored", "quoted"),
    [
        (f"the coe{FFI}cient of the e{FF}ect", "the coefficient of the effect"),
        (f"the result was ba{FFL}ing", "the result was baffling"),
        ("drug\N{HYPHEN}induced injury", "drug-induced injury"),
        ("a non\N{NON-BREAKING HYPHEN}inferiority margin", "a non-inferiority margin"),
        ("and so on\N{HORIZONTAL ELLIPSIS} at 7.2", "and so on... at 7.2"),
    ],
    ids=["ff-ffi", "ffl", "hyphen", "non-breaking-hyphen", "ellipsis"],
)
def test_what_a_pdf_reader_may_or_may_not_fold_is_folded_here(stored: str, quoted: str) -> None:
    """Writing Latin-1, the pdftotext of Xpdf spelt these out itself; asked for UTF-8 it hands
    them over as they are, as poppler does for a ligature a font names through its ToUnicode
    map. Only fi and fl were folded here, so a typed quote holding "effect" or "coefficient"
    was refused against a source that says exactly that."""
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


# ---------------------------------------------------------------- reading a PDF

# In PDF's own octal escapes, \223 and \224 are the curly quotes of WinAnsi.
CURLY_LINE = rb"The rate was \223high\224 at 7.2 per 1000."
CURLY_TEXT = "The rate was “high” at 7.2 per 1000.\n"
READ = 'The rate was "high" at 7.2 per 1000.'
NOT_UTF8 = b"The rate was 7.2 \xff per 1000.\n"
READ_NOT_UTF8 = "The rate was 7.2 \N{REPLACEMENT CHARACTER} per 1000."


def one_page_pdf(line: bytes) -> bytes:
    """A PDF of one page holding one line of text, small enough to write out here."""
    stream = b"BT /F1 12 Tf 72 720 Td (" + line + b") Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + content + b"\nendobj\n"
    table = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objects) + 1)
    return body + b"startxref\n%d\n%%%%EOF\n" % table


def stand_in_for_pdftotext(monkeypatch: pytest.MonkeyPatch, output: bytes) -> list[list[str]]:
    """A program that writes `output` where pdftotext would run, on a cp1252 machine.

    The child process is real, so the bytes are decoded by `subprocess` as they are in use
    and not by a model of it. A call that names no encoding gets the one a Western European
    Windows would choose. Returns the commands that were asked for.
    """
    real_run = subprocess.run
    child = [sys.executable, "-c", f"import sys; sys.stdout.buffer.write({output!r})"]
    commands: list[list[str]] = []

    def run(command, **options):
        commands.append([str(part) for part in command])
        if options.get("text") and "encoding" not in options:
            options["encoding"] = "cp1252"
        return real_run(child, **options)

    monkeypatch.setattr(sources.shutil, "which", lambda name: name)
    monkeypatch.setattr(sources.subprocess, "run", run)
    return commands


def no_pypdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdf", None)


def pypdf_that_reads(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    class Reader:
        def __init__(self, _path: str) -> None:
            self.pages = [types.SimpleNamespace(extract_text=lambda: text)]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=Reader))


@pytest.mark.skipif(
    not shutil.which("pdftotext") and importlib.util.find_spec("pypdf") is None,
    reason="neither pdftotext nor pypdf is installed",
)
def test_a_pdf_with_curly_quotes_is_read(tmp_path: Path) -> None:
    """The PDF every publisher sends, read by whatever reader this machine has."""
    path = tmp_path / "paper.pdf"
    path.write_bytes(one_page_pdf(CURLY_LINE))
    assert read_source(path) == READ


@pytest.mark.parametrize(
    ("output", "read"),
    [
        (CURLY_TEXT.encode("utf-8"), READ),
        (NOT_UTF8, READ_NOT_UTF8),
    ],
    ids=["utf-8", "not-utf-8"],
)
def test_pdftotext_is_read_as_utf8_whatever_the_locale(
    output: bytes, read: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The call named no encoding, so Python decoded pdftotext's output with the locale.

    On Windows that is cp1252. A closing curly quote is E2 80 9D in UTF-8 and 9D is
    unassigned in cp1252, so the decode failed in the thread `subprocess` reads with,
    `stdout` came back as None, and `.strip()` on it raised AttributeError past an `except`
    that names two other errors. `check` reported "could not run: AttributeError: 'NoneType'
    object has no attribute 'strip'" for any ledger entry whose source was such a PDF,
    which is most PDFs, and pypdf was never tried.
    """
    commands = stand_in_for_pdftotext(monkeypatch, output)
    no_pypdf(monkeypatch)
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4")

    assert read_source(path) == read
    (command,) = commands
    assert command[command.index("-enc") + 1] == "UTF-8", (
        "the pdftotext of Xpdf, which Git for Windows ships, writes Latin-1 unless asked"
    )


def finished(returncode: int, stdout: str | None) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["pdftotext"], returncode, stdout, "")


@pytest.mark.parametrize(
    "outcome",
    [
        finished(0, None),
        finished(0, " \n\x0c"),
        finished(1, "Syntax Error: Couldn't find trailer dictionary"),
        subprocess.TimeoutExpired("pdftotext", 120),
        OSError("not a valid Win32 application"),
    ],
    ids=["no-output", "blank", "failed", "timed-out", "would-not-start"],
)
def test_a_pdftotext_that_gives_nothing_leaves_the_pdf_to_pypdf(
    outcome, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whatever goes wrong with the first reader, the second is asked before giving up."""

    def run(*_args, **_options):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(sources.shutil, "which", lambda name: name)
    monkeypatch.setattr(sources.subprocess, "run", run)
    path = tmp_path / "paper.pdf"
    path.write_bytes(b"%PDF-1.4")

    pypdf_that_reads(monkeypatch, CURLY_TEXT)
    assert read_source(path) == READ

    no_pypdf(monkeypatch)
    with pytest.raises(UnreadableSource, match="cannot read PDFs"):
        read_source(path)


def test_a_ledger_entry_with_a_pdf_source_is_verified(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same failure from where it was met: the gate did not run at all."""
    stand_in_for_pdftotext(monkeypatch, CURLY_TEXT.encode("utf-8"))
    no_pypdf(monkeypatch)
    (project / "literature" / "sources" / "paper.pdf").write_bytes(b"%PDF-1.4")

    def mutate(document):
        entry = document["entries"][0]
        entry.update(source_file="sources/paper.pdf", value=7.2, display="7.2", quote=READ)

    edit_yaml(project / LEDGER, mutate)
    report = chain_report(project)
    assert report.ok, report.render(project)
    assert report.counts["literature_verified"] == 2


# A line of an article set by pdfLaTeX with no ToUnicode map, as Xpdf writes it in UTF-8.
LIGATURES = (
    f"In the treated group the e{FF}ect on e{FFI}cacy was di{FF}erent: the coe{FFI}cient "
    "was 0.42 (95% CI 0.21\N{EN DASH}0.63).\n"
)


@pytest.mark.parametrize(
    ("quote", "found"),
    [
        ("the effect on efficacy was different: the coefficient was 0.42", True),
        ("the effect on efficacy was similar: the coefficient was 0.42", False),
    ],
    ids=["true-quote", "false-quote"],
)
def test_a_typed_quote_is_found_in_a_pdf_set_with_ligatures(
    quote: str, found: bool, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking pdftotext for UTF-8 took away the folding Xpdf did while it wrote Latin-1, and
    the true quote was reported `quote-not-in-source` where `main` had verified it."""
    stand_in_for_pdftotext(monkeypatch, LIGATURES.encode("utf-8"))
    no_pypdf(monkeypatch)
    (project / "literature" / "sources" / "paper.pdf").write_bytes(b"%PDF-1.4")

    def mutate(document):
        entry = document["entries"][0]
        entry.update(source_file="sources/paper.pdf", value=0.42, display="0.42", quote=quote)

    edit_yaml(project / LEDGER, mutate)
    report = chain_report(project)
    assert ("quote-not-in-source" not in codes(report)) is found, report.render(project)
    assert report.counts["literature_verified"] == (2 if found else 1)


def test_normalise_is_idempotent() -> None:
    once = normalise("  a  “b”  –  c  ")
    assert normalise(once) == once
