"""Reading the text of a stored source, whatever format it arrived in.

The ledger records a verbatim quote for every value taken from the literature. That field
is not decoration: it is the one part of a literature claim a machine can check. If the
quote is really in the source, and the value is really in the quote, then the chain from
manuscript to published sentence is verified end to end without anyone re-reading the
paper.

So this module exists to turn whatever the author saved — a PDF, a saved page, a pasted
abstract — into text that check can run against.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".rst", ".csv", ".json", ".xml", ".bib", ".nbib", ".ris"}
HTML_SUFFIXES = {".html", ".htm", ".xhtml"}
PDF_SUFFIXES = {".pdf"}

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")

# Typographic substitutions a publisher's HTML makes and a person copying a quote does not.
_EQUIVALENT = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    "ﬁ": "fi",
    "ﬂ": "fl",
}


class UnreadableSource(Exception):
    """The source exists but its text could not be extracted."""


def normalise(text: str) -> str:
    """Fold the differences that make a true quote look false.

    A quote copied from a rendered page and the same sentence extracted from a PDF differ
    in curly quotes, dash width, ligatures and line wrapping, none of which change what was
    written. Comparing without folding them produces failures that are all noise, and a
    check whose failures are noise gets switched off.
    """
    for source, target in _EQUIVALENT.items():
        text = text.replace(source, target)
    return _WHITESPACE.sub(" ", text).strip()


def read_source(path: Path) -> str:
    """Text of a stored source, normalised. Raises UnreadableSource when it cannot."""
    suffix = path.suffix.lower()

    if suffix in TEXT_SUFFIXES or suffix == "":
        return normalise(path.read_text(encoding="utf-8", errors="replace"))

    if suffix in HTML_SUFFIXES:
        raw = path.read_text(encoding="utf-8", errors="replace")
        return normalise(_TAG.sub(" ", _SCRIPT.sub(" ", raw)))

    if suffix in PDF_SUFFIXES:
        return normalise(_read_pdf(path))

    raise UnreadableSource(
        f"{path.name}: no reader for {suffix or 'a file with no extension'}; "
        f"save the passage as .txt alongside it"
    )


def _read_pdf(path: Path) -> str:
    """Poppler first, pypdf second, an honest failure third.

    Neither is a hard dependency. A toolkit that refuses to install without a PDF stack is
    a toolkit people do not install.
    """
    if shutil.which("pdftotext"):
        try:
            finished = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if finished.returncode == 0 and finished.stdout.strip():
                return finished.stdout
        except (OSError, subprocess.SubprocessError):
            pass

    try:
        import pypdf
    except ImportError as exc:
        raise UnreadableSource(
            f"{path.name}: cannot read PDFs. Install poppler's pdftotext, or "
            f"`pip install pypdf`, or save the passage as .txt alongside the PDF"
        ) from exc

    try:
        reader = pypdf.PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide variety
        raise UnreadableSource(f"{path.name}: pypdf could not read it: {exc}") from exc


def contains(haystack: str, needle: str) -> bool:
    """Whether a quote appears in a source, ignoring differences that are not differences."""
    return normalise(needle).lower() in normalise(haystack).lower()


def states_value(quote: str, display: str) -> bool:
    """Whether the quote states this value, as a whole number rather than as characters.

    `contains` is the right test for prose — a sentence either appears in the source or it
    does not. It is the wrong test for a value, because a short number is a substring of a
    longer one. A ledger entry of `3.4` was accepted against the verbatim quote

        "the reporting odds ratio for hepatic events was 13.42 (95% CI 9.10 to 19.80)"

    since "3.4" sits inside "13.42". Both checks passed and the manuscript went on to
    attribute an ROR of 3.4 to a paper reporting 13.42 — a misquotation of a real source,
    which is worse than an unsourced number because it looks checked. Digits adjacent to
    the match on either side, and a decimal separator or comma before it, now disqualify it.
    """
    text = normalise(quote).lower()
    value = normalise(display).lower()
    if not value:
        return False
    if not any(ch.isdigit() for ch in value):
        return value in text
    edged = re.compile(r"(?<![0-9.,])" + re.escape(value) + r"(?![0-9])")
    return edged.search(text) is not None


def filed_name(citekey: str, suffix: str) -> str:
    """The name a stored source should have: keyed to the citation, not to the download."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", citekey)
    return f"{safe}{suffix if suffix.startswith('.') else '.' + suffix}"
