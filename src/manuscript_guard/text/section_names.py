"""Which section a heading names, said once for every gate that reads a section by it.

G4 counts a required section present by its heading, and G2, G9, G14 and G15 each read a
section they find by its heading. Each had its own pattern, and they disagreed: G4 took
"2. Methods" and "Patients and methods" for the Methods, and G9 read neither, so a wrong
parameter in `methods.lock` was compared with nothing and nothing said so. A section that
counts as present is now a section that is read.

Two attempts to say it by the words of a title failed review: each left out headings G4 had
always taken ("Materials & methods", "**2. Methods**") or took a paper's title written as a
heading over the whole paper for its Methods. So the words are G4's own, a title holding
"methods", and what decides between such titles is where they stand, not what else they say.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from manuscript_guard.text.sections import Section

#: A heading's number, which is no part of its name: "2", "2.", "2.1", "2.1.3.", "II.",
#: "A.", "2)", "(2)".
_NUMBER = re.compile(
    r"^\s*(?:\(\d+\)|\d+(?:\.\d+)*[.)]?|[IVXLC]+[.)]|[A-Z][.)])\s+", re.IGNORECASE
)
_ABSTRACT = re.compile(r"(?:structured\s+)?abstract\b", re.IGNORECASE)
#: The Results by the word a title opens with: "Results", "3. Results and discussion",
#: "**Findings**". Not anywhere in it: "Comparison with earlier results" is the Discussion's.
_RESULTS = re.compile(r"(?:results?|findings)\b", re.IGNORECASE)
#: A conclusion: "Conclusions", "5. Conclusion and implications", "Concluding remarks", and
#: a "Summary" that is the whole title, as a paper's last section is often called.
_CONCLUSION = re.compile(
    r"conclu(?:sions?|ding\s+remarks)\b|summary(?:\s+and\s+conclusions?)?\W*$", re.IGNORECASE
)


#: The reference list's title in the languages besides English that papers are most often
#: written in, lower case. Each is the title pandoc 3.9.0.2 gives a reference list and a
#: bibliography in that language (`data/translations/<code>.yaml`, the keys `References`
#: and `Bibliography`), and Indonesian's "Daftar pustaka" is the list in full (Indonesian
#: Wikipedia, "Daftar pustaka"). Unknown, a list under "Kaynakça" was read as prose, and the
#: audit fell back to telling its entries by their shape.
REFERENCE_TITLES_ELSEWHERE = (
    "referencias", "bibliografía",                # Spanish (es)
    "referências", "bibliografia",                # Portuguese (pt); Italian's Bibliography
    "références", "bibliographie",                # French (fr)
    "literatur", "literaturverzeichnis",          # German (de)
    "riferimenti bibliografici",                  # Italian (it)
    "kaynaklar", "kaynakça",                      # Turkish (tr)
    "pustaka", "daftar pustaka", "bibliografi",   # Indonesian (id)
)  # fmt: skip

#: `REFERENCE_TITLES_ELSEWHERE` as one alternation for a pattern: longest first, so that
#: "literaturverzeichnis" is not read as "literatur", and any space between words.
REFERENCE_WORDS_ELSEWHERE = "|".join(
    re.escape(title).replace(r"\ ", r"\s+")
    for title in sorted(REFERENCE_TITLES_ELSEWHERE, key=len, reverse=True)
)


def bare(title: str) -> str:
    """A heading's title without its number."""
    return _NUMBER.sub("", title, count=1).strip()


def plain(title: str) -> str:
    """A title as a reader of the built document sees it, without its number."""
    from manuscript_guard.classify import _unmarked

    return bare(_unmarked(title))


def names_results(title: str) -> bool:
    """Whether a heading's title opens with the word for the Results, numbered, marked or
    not: "Results", "3. Results", "**Findings**", "Results and discussion"."""
    return bool(_RESULTS.match(plain(title)))


def names_conclusion(title: str) -> bool:
    """Whether a heading names a conclusion: "Conclusions", "6. Conclusion and
    implications", "Concluding remarks", "Summary and conclusions", or "Summary" alone."""
    return bool(_CONCLUSION.match(plain(title)))


def names_methods(title: str) -> bool:
    """Whether a heading can be the Methods: its title holds "methods", the test G4 has
    counted a required Methods section present by since it was written. "2. Methods",
    "**2. Methods**", "Materials & methods", "Patients and methods", "Statistical methods".
    Which of several such headings is the paper's Methods is `methods_sections`'s to say."""
    return "methods" in title.lower()


def names_abstract(title: str, named: str | None = None) -> bool:
    """Whether a heading names the abstract: "Abstract" or "Structured abstract", numbered
    or not, or the title a journal profile gives it (`structure.abstract_title`, "Summary"
    in The Lancet), as a whole title and in any case."""
    title = bare(title)
    if _ABSTRACT.match(title):
        return True
    return bool(named) and title.rstrip(" .:").casefold() == str(named).strip().casefold()


def methods_sections(
    sections: Sequence[Section], abstract_title: str | None = None
) -> list[Section]:
    """The sections of one file that are the paper's Methods, the likeliest first.

    A heading that holds "methods" (`names_methods`) and stands where the Methods stand:
    not inside the abstract, whose own "Methods" are the abstract's; not under a heading
    that names another part of the paper, the Introduction, the Results, the Discussion
    (`classify.rules_out_methods`), as "Limitations of existing methods" under the
    Introduction; and not over one, as a paper's title written as a heading over the whole
    paper, "# Statistical methods for signal detection", is over its Results. Of those, a
    heading whose name is one of `METHODS_SECTIONS`' ("Methods", "2. Methods", "Materials
    and methods") comes before one that only holds the word. The name is read here as a
    reader sees it, `plain` and with "&" for "and", so "(3) Methods", "**2. Methods**" and
    "Materials & methods" come first too (round 3 of #246: they came after "Limitations of
    existing methods"). G2's `is_methods` reads the title as it is typed."""
    from manuscript_guard.classify import METHODS_SECTIONS, rules_out_methods

    found: list[Section] = []
    chain: list[Section] = []
    for index, section in enumerate(sections):
        while chain and chain[-1].level >= section.level:
            chain.pop()
        above = list(chain)
        chain.append(section)
        if not names_methods(section.title):
            continue
        if any(s.names_abstract(abstract_title) or rules_out_methods(s.title) for s in above):
            continue
        below = []
        for later in sections[index + 1 :]:
            if later.level <= section.level:
                break
            below.append(later)
        if any(rules_out_methods(s.title) for s in below):
            continue
        found.append(section)
    def by_name(section: Section) -> bool:
        return METHODS_SECTIONS.match(plain(section.title).replace("&", " and ")) is None

    return sorted(found, key=by_name)


__all__ = [
    "bare",
    "methods_sections",
    "names_abstract",
    "names_conclusion",
    "names_methods",
    "names_results",
    "plain",
]
