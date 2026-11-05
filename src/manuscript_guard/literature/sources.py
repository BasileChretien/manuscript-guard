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

import html
import itertools
import re
import shutil
import subprocess
import unicodedata
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
    # What the pdftotext of Xpdf spelt out itself while it wrote Latin-1. Asked for UTF-8 it
    # hands them over as they are, and so does poppler for a ligature a font names through
    # its ToUnicode map. Without these a typed "effect" is not found in a source that says it.
    "\N{LATIN SMALL LIGATURE FF}": "ff",
    "\N{LATIN SMALL LIGATURE FFI}": "ffi",
    "\N{LATIN SMALL LIGATURE FFL}": "ffl",
    "\N{HYPHEN}": "-",
    "\N{NON-BREAKING HYPHEN}": "-",
    "\N{HORIZONTAL ELLIPSIS}": "...",
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


def read_in_reading_order(path: Path) -> str:
    """The text of a stored source as a reader reads it, a PDF's pages parted by a form feed,
    nothing folded: for comparing runs of words with a manuscript, not for finding a quote.

    `pdftotext` is asked for the reading order, without `-layout`. Laid out, each line of a
    page of two columns holds a line of each, and a sentence of the left column is cut by
    every line of the right; in reading order one column is read after the other. An HTML
    page loses its tags and keeps its lines, so that a line it gives is the page's."""
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES or suffix == "":
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix in HTML_SUFFIXES:
        raw = path.read_text(encoding="utf-8", errors="replace")

        def kept(found: re.Match[str]) -> str:
            return " " + "\n" * found.group().count("\n")

        return html.unescape(_TAG.sub(kept, _SCRIPT.sub(kept, raw)))
    if suffix in PDF_SUFFIXES:
        return _read_pdf(path, layout=False)
    raise UnreadableSource(
        f"{path.name}: no reader for {suffix or 'a file with no extension'}; "
        f"save its text as .txt alongside it"
    )


def _read_pdf(path: Path, *, layout: bool = True) -> str:
    """Poppler first, pypdf second, an honest failure third.

    Neither is a hard dependency. A toolkit that refuses to install without a PDF stack is
    a toolkit people do not install. Out of layout, pypdf's pages are parted by a form feed,
    as pdftotext parts them.
    """
    text = _pdftotext(path, layout=layout)
    if text is not None:
        return text

    try:
        import pypdf
    except ImportError as exc:
        raise UnreadableSource(
            f"{path.name}: cannot read PDFs. Install poppler's pdftotext, or "
            f"`pip install pypdf`, or save the passage as .txt alongside the PDF"
        ) from exc

    try:
        reader = pypdf.PdfReader(str(path))
        between = "\n" if layout else "\f"
        return between.join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide variety
        raise UnreadableSource(f"{path.name}: pypdf could not read it: {exc}") from exc


def _pdftotext(path: Path, *, layout: bool = True) -> str | None:
    """What `pdftotext` reads from the PDF, or None when it gave nothing to use: laid out as
    the page is, or in reading order where `layout` is false.

    The encoding is stated at both ends. Left unstated, poppler writes UTF-8, the pdftotext
    of Xpdf writes Latin-1, and Python decodes with the locale, which on Windows is cp1252.
    A closing curly quote is E2 80 9D in UTF-8 and 9D is unassigned in cp1252, so the
    decode failed in the thread `subprocess` reads with, `stdout` came back as None, and
    `.strip()` on it raised AttributeError past the `except` here. The literature chain
    was reported as `gate-errored` and pypdf was never asked.

    None when pdftotext is absent, fails, times out or gives nothing, so that the caller
    goes on to pypdf. Output that is not UTF-8 although it was asked for is kept, with each
    byte that cannot be read replaced: a quote the damage does not touch still verifies.
    """
    if not shutil.which("pdftotext"):
        return None
    try:
        finished = subprocess.run(
            ["pdftotext", *(["-layout"] if layout else []), "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0 or not (finished.stdout or "").strip():
        return None
    return finished.stdout


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


#: The fewest words a quote holds beside its value for it to show what the value is of.
WORDS_BESIDE = 4

#: The scripts written without spaces between words, each as the letters in a row that count
#: as one word and the blocks of code points that hold it. Han, Hiragana and Katakana, two:
#: the segmented corpora of Chinese average 1.6 to 1.7 characters a word (SIGHAN 2005: PKU
#: 1.83 million characters in 1.11 million words, MSR 4.05 million in 2.37 million), and
#: Japanese, whose particles (の, は, が) are words of one letter, has words as short. Thai,
#: four: the BEST 2009 corpus holds 20.9 million characters in 5.8 million words, 3.6 a
#: word, its vowel and tone marks being characters of their own. Lao, Khmer and Myanmar are
#: written as Thai is and counted as it is; no corpus of them was measured. Each size is
#: rounded up and each count down, so that a quote of average words is counted no longer
#: than a person would count it and a short one is still warned of; one of long words, a
#: long Katakana loanword or a Thai compound, counts longer (DESIGN.md, Known gaps). A run
#: between spaces that holds a letter is one word at the least, rounded down or not, as
#: every such run was before these scripts were counted by their letters.
UNSPACED: tuple[tuple[int, tuple[tuple[int, int], ...]], ...] = (
    (
        2,
        (
            (0x3005, 0x3007),  # 々, 〆, 〇
            (0x3040, 0x30FF),  # Hiragana, Katakana
            (0x31F0, 0x31FF),  # small Katakana for Ainu
            (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
            (0x4E00, 0x9FFF),  # CJK Unified Ideographs
            (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
            (0xFF66, 0xFF9F),  # half-width Katakana
            (0x20000, 0x323AF),  # CJK Unified Ideographs Extensions B to H
        ),
    ),
    (4, ((0x0E00, 0x0EFF), (0x1000, 0x109F), (0x1780, 0x17FF))),  # Thai, Lao; Myanmar; Khmer
)


def _letters_to_a_word(ch: str) -> int:
    """How many letters of `ch`'s script in a row count as a word, 0 where words are spaced.
    Only a letter or a mark counts: a stop, a bracket or a digit of these scripts does not."""
    if unicodedata.category(ch)[0] not in "LM":
        return 0
    code = ord(ch)
    for size, blocks in UNSPACED:
        if any(low <= code <= high for low, high in blocks):
            return size
    return 0


def _words_of(piece: str) -> list[str]:
    """The words of a run between spaces. A run in it of a script written without spaces is
    cut into words of its size, a shorter piece left at its end counting for none; what
    stands between such runs is a word if it holds a letter, as a run between spaces is.
    A run between spaces that holds a letter is a word at the least, as it always was, so
    that Chinese set with spaces around its numbers ("纳入 120 例") counts no fewer words
    than before (round 1 of #505)."""
    words = []
    for size, letters in itertools.groupby(piece, _letters_to_a_word):
        run = "".join(letters)
        if size:
            words.extend(run[at : at + size] for at in range(0, len(run) - size + 1, size))
        elif any(ch.isalpha() for ch in run):
            words.append(run)
    if not words and any(ch.isalpha() for ch in piece):
        return [piece]
    return words


def words_beside(quote: str, display: str) -> list[str]:
    """The words of a quote once the value is taken out of it, as `states_value` finds it: a
    word is a run between spaces that holds a letter. "2.6" quoted alone proves only that
    those digits are somewhere in the source; "ROR 2.6" says little more.

    Chinese, Japanese and Thai put no space between words, and a whole sentence of them was
    a word or two. In those scripts a word is counted for every two letters in a row of Han,
    Hiragana or Katakana and every four of Thai, Lao, Khmer or Myanmar, rounded down (see
    `UNSPACED` for why), and Latin words and digits among them are counted as before:
    "薬剤群全体のROR 2.6" holds four words beside 2.6, "報告オッズ比2.6" three."""
    text = normalise(quote)
    value = normalise(display)
    if value:
        edges = (r"(?<![0-9.,])", r"(?![0-9])") if any(c.isdigit() for c in value) else ("", "")
        found = re.search(edges[0] + re.escape(value) + edges[1], text, re.IGNORECASE)
        if found:
            text = text[: found.start()] + " " + text[found.end() :]
    return [word for piece in text.split() for word in _words_of(piece)]


def filed_name(citekey: str, suffix: str) -> str:
    """The name a stored source should have: keyed to the citation, not to the download."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", citekey)
    return f"{safe}{suffix if suffix.startswith('.') else '.' + suffix}"


def stored_files(sources: Path, citekey: str) -> list[Path]:
    """Every stored file of a work: its full text in each form kept, and its abstract,
    `<key>.abstract.txt` as the literature skill names it (round 1 of #282: the first file
    alone was read, so a quotation of a PDF beside an HTML abstract was said to be absent,
    and an abstract so named was never found)."""
    suffixes = sorted(TEXT_SUFFIXES | HTML_SUFFIXES | PDF_SUFFIXES)
    names = [filed_name(citekey, s) for s in suffixes] + [filed_name(citekey, ".abstract" + s)
                                                           for s in suffixes]  # fmt: skip
    return [sources / name for name in names if (sources / name).is_file()]
