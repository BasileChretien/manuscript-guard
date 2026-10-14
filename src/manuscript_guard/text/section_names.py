"""Which section a heading names, said once for every gate that reads a section by it.

G4 counts a required section present by its heading, and G2, G9, G14 and G15 each read a
section they find by its heading. Each had its own pattern, and they disagreed: G4 took
"2. Methods" and "Patients and methods" for the Methods, and G9 read neither, so a wrong
parameter in `methods.lock` was compared with nothing and nothing said so. A section that
counts as present is now a section that is read.

Nothing here imports the rest of the package, so `classify` and `text.sections` can both
use it.
"""

from __future__ import annotations

import re

#: A heading's number, which is no part of its name: "2", "2.", "2.1", "2.1.3.", "II.",
#: "A.", "2)", "(2)".
_NUMBER = re.compile(
    r"^\s*(?:\(\d+\)|\d+(?:\.\d+)*[.)]?|[IVXLC]+[.)]|[A-Z][.)])\s+", re.IGNORECASE
)
#: The Methods: a title the word heads, after a heading's number and its marks. "Methods",
#: "2. Methods", "Methods and analysis", "Methods: data sources", "Materials and methods",
#: "Patients and methods", "Statistical methods", "Method", "Methodology". A title that only
#: holds the word is not: "A method for signal detection", a paper's title written as a
#: heading, made G9 read the whole paper as its Methods, and "Limitations of existing
#: methods" an Introduction's subsection.
_METHODS = re.compile(
    r"(?:(?:[^\W\d_][\w',-]*\s+){1,4}?and\s+"
    r"|(?:statistical|study|research|experimental|analytical)\s+)?"
    r"(?:methods?|methodology)\b",
    re.IGNORECASE,
)
_ABSTRACT = re.compile(r"(?:structured\s+)?abstract\b", re.IGNORECASE)


def bare(title: str) -> str:
    """A heading's title without its number."""
    return _NUMBER.sub("", title, count=1).strip()


def names_methods(title: str) -> bool:
    """Whether a heading names the Methods."""
    return bool(_METHODS.match(bare(title).lstrip("*_")))


def names_abstract(title: str, named: str | None = None) -> bool:
    """Whether a heading names the abstract: "Abstract" or "Structured abstract", numbered
    or not, or the title a journal profile gives it (`structure.abstract_title`, "Summary"
    in The Lancet), as a whole title and in any case."""
    title = bare(title)
    if _ABSTRACT.match(title):
        return True
    return bool(named) and title.rstrip(" .:").casefold() == str(named).strip().casefold()


__all__ = ["bare", "names_abstract", "names_methods"]
