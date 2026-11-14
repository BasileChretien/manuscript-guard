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
#: The Discussion by the words a title opens with: "Discussion", "5. General discussion",
#: "**Discussion and conclusions**", and the section that holds it with the Results, "Results
#: and discussion". Not anywhere in it: "Methods for discussion groups" is the Methods'.
_DISCUSSION = re.compile(
    r"(?:general\s+)?discussion\b|(?:results?|findings)\s+(?:and|&)\s+discussion\b",
    re.IGNORECASE,
)

#: The names of the statements a journal asks for, and of the lists, that are the same from
#: paper to paper: a pattern to put in another, of no flags, to be read ignoring case. G7's
#: comparison with earlier papers reads a statement's heading by it, and a reference list
#: under a bold line ends at one standing alone as a paragraph.
STATEMENT_NAMES = (
    r"(?:"
    r"funding(?:\s+(?:sources?|information))?|sources?\s+of\s+funding|(?:financial\s+)?support"
    r"|financial\s+disclosures?|sponsors?(?:hip)?"
    r"|role\s+of\s+the\s+(?:funders?|sponsors?|funding\s+sources?)"
    r"|(?:declarations?\s+of\s+)?(?:competing|conflicting)\s+interests?"
    r"|(?:potential\s+)?conflicts?\s+of\s+interests?|declarations?(?:\s+of\s+interests?)?"
    r"|declarations?\s+of\s+(?:the\s+use\s+of\s+)?generative\s+ai\b[\w\s-]*"
    r"|disclosures?(?:\s+of\s+interests?)?|acknowledge?ments?"
    r"|data\s+(?:availability|sharing|access)"
    r"|availability\s+of\s+(?:data(?:\s+and\s+materials?)?|materials?)"
    r"|(?:code|software|materials?)\s+availability"
    r"|ethics(?:\s+(?:committee\s+)?approval)?"
    r"|ethical(?:\s+(?:approval|considerations|standards|aspects))?"
    r"|(?:informed\s+|patient\s+)?consent(?:\s+(?:for|to)\s+(?:publication|participate))?"
    r"|patient\s+and\s+public\s+involvement|provenance\s+and\s+peer\s+review"
    r"|authors?['\N{RIGHT SINGLE QUOTATION MARK}]?\s+contributions?|contributors(?:hip)?"
    r"|credit(?:\s+author(?:ship)?)?(?:\s+contributions?)?|transparency"
    r"|(?:list\s+of\s+)?abbreviations|statements?\s+and\s+declarations?"
    r"|additional\s+contributions|article\s+information"
    r")(?:\s+(?:statements?|declarations?|disclosures?|section))?"
)
#: A statement's heading: its whole title names one or several, "Funding", "Data
#: availability statement", "Ethics approval and consent to participate", "Funding/Support",
#: "CRediT author statement". A title that only opens with such a word is the paper's own
#: matter: "Funding sources of the included trials", "Data sharing in pharmacovigilance".
#: G7 sets a statement's text apart by it, and G8 reports nothing under one.
STATEMENT_TITLE = re.compile(
    rf"(?:the\s+)?{STATEMENT_NAMES}"
    rf"(?:\s*(?:,\s*(?:and\b)?|;|&|/|\band\b)\s*{STATEMENT_NAMES})*\W*$",
    re.IGNORECASE,
)
#: The opening of a paper by the word its title opens with: "Introduction", "1. Background",
#: "Rationale and objectives". G7 reads the Introduction by it, and G8 reports nothing under it.
INTRODUCTION_TITLE = re.compile(r"(?:introduction|background|rationale)\b", re.IGNORECASE)


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


def names_discussion(title: str) -> bool:
    """Whether a heading names the Discussion, numbered, marked or not: "Discussion", "5.
    General discussion", "Discussion and conclusions", "Results and discussion"."""
    return bool(_DISCUSSION.match(plain(title)))


def names_introduction(title: str) -> bool:
    """Whether a heading's title opens with the word for the opening of a paper, numbered,
    marked or not: "Introduction", "1. Background", "Rationale and objectives"."""
    return bool(INTRODUCTION_TITLE.match(plain(title)))


#: Sections that hold the Introduction's material under a name of their own, whole titles in
#: small letters: what other papers found, which the audit's Abstract against Results does
#: not search, as it does not search the Introduction (round 1 of #641). A closed list.
INTRODUCTION_MATERIAL = frozenset({
    "related work", "prior work", "literature review", "theoretical framework", "hypotheses",
})  # fmt: skip
#: Summaries of the paper beside its Abstract, whole titles in small letters, which restate
#: its numbers: PLOS's "Author summary", PNAS's "Significance", a plain-language or lay
#: summary, a graphical abstract's text, a box of highlights or key points, The Lancet's
#: "Research in context", and the Abstract in the languages `REFERENCE_TITLES_ELSEWHERE`
#: names (round 1 of #641). A closed list.
PAPER_SUMMARIES = frozenset({
    "author summary", "significance", "significance statement", "plain language summary",
    "plain-language summary", "lay summary", "graphical abstract", "highlights",
    "key points", "key messages", "key findings", "what this study adds",
    "research in context",
    "resumen", "resumo", "résumé", "zusammenfassung", "riassunto", "özet", "abstrak",
})  # fmt: skip


def _whole(title: str) -> str:
    return " ".join(plain(title).rstrip(" .:").casefold().split())


def names_introduction_material(title: str) -> bool:
    """Whether a heading's whole title, numbered, marked or not, is one of
    `INTRODUCTION_MATERIAL`: "Related work", "2. Literature review"."""
    return _whole(title) in INTRODUCTION_MATERIAL


def names_paper_summary(title: str) -> bool:
    """Whether a heading's whole title, numbered, marked or not, is one of `PAPER_SUMMARIES`:
    "Author summary", "Highlights", "Resumen"."""
    return _whole(title) in PAPER_SUMMARIES


def names_statement(title: str) -> bool:
    """Whether a heading's whole title names one or several of the statements a journal asks
    for, or a list of the back matter: "Funding", "Acknowledgements", "Author contributions",
    "Ethics approval and consent to participate", "Abbreviations"."""
    return bool(STATEMENT_TITLE.match(plain(title)))


#: The singular, which names the Methods only as the whole title, numbered, marked or not:
#: "Method", as APA titles it and a machine-learning paper often does, "Methodology", and
#: "Materials and method" or "Method and materials". Read anywhere in a title, the word took
#: "Performance of the proposed method" under "Results and discussion" for a Methods, and
#: the Results over it were no longer the Results (round 1 of #624).
_METHOD_TITLE = re.compile(
    r"(?:materials?\s+(?:and|&)\s+)?method(?:ology)?(?:\s+(?:and|&)\s+materials?)?[\s.:]*",
    re.IGNORECASE,
)


def names_methods(title: str) -> bool:
    """Whether a heading can be the Methods: its title holds "methods", the test G4 has
    counted a required Methods section present by since it was written, or is the singular
    alone (`_METHOD_TITLE`). "2. Methods", "**2. Methods**", "Materials & methods",
    "Patients and methods", "Statistical methods", "eMethods 1", "Method", "3. Methodology";
    not "Methodological notes" nor "Performance of the proposed method". A paper with a
    "Method" heading had no Methods to the audit and the gates, so a number of its Abstract
    reported there was not found (cs-lg of the real-paper corpus, 2026-11-11). Which of
    several such headings is the paper's Methods is `methods_sections`'s to say."""
    return "methods" in title.lower() or _METHOD_TITLE.fullmatch(plain(title)) is not None


def names_abstract(title: str, named: str | None = None) -> bool:
    """Whether a heading names the abstract: "Abstract" or "Structured abstract", numbered
    or not, or the title a journal profile gives it (`structure.abstract_title`, "Summary"
    in The Lancet), as a whole title and in any case; in a span or not, as pandoc writes an
    underlined one, "[Abstract]{.underline}" (`without_spans`)."""
    from manuscript_guard.text.attributes import without_spans

    title = bare(without_spans(title))
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


#: The names a title standing alone is read as a section's heading by, in any case, where
#: nothing marks a heading: a line of a PDF (`auditing.pdf`), and a Word paragraph wholly in
#: bold in a document with no paragraph in a heading style (`from_word`, `text.docx`).
SECTION_NAMES = frozenset({
    "abstract", "summary", "structured abstract", "introduction", "background",
    "methods", "method", "methodology", "materials and methods", "material and methods",
    "methods and materials", "patients and methods", "subjects and methods",
    "participants and methods", "results", "findings", "results and discussion",
    "discussion", "general discussion", "discussion and conclusions", "conclusion",
    "conclusions", "limitations", "strengths and limitations", "references", "bibliography",
    "literature cited", "works cited", "acknowledgements", "acknowledgments",
    "acknowledgement", "acknowledgment", "funding", "conflicts of interest",
    "conflict of interest", "competing interests", "declaration of competing interest",
    "author contributions", "data availability", "data availability statement", "ethics",
    "ethics statement", "ethical approval", "abbreviations", "appendix",
    "supplementary material", "supplementary materials", "tables", "figures",
    "figure legends", "figure captions",
    # Back matter that docx-socio-A2 of the real-paper corpus types in bold between its
    # Abstract and its Acknowledgments, its authors' addresses under it (Basile, 2026-11-14).
    "author information",
    # The Results in the singular, as "Method" stands beside "Methods": "RESULT:" in
    # docx-med-A3 and "Result:" in docx-med-A2, typed, and "3. Result" in pdf-psych-B3 of the
    # real-paper corpus (Basile, 2026-11-15). A structured abstract's part too.
    "result",
    # The back matter as BMC's journals title it: one "Declarations" over its statements.
    "declarations", "declaration", "list of abbreviations", "authors' contributions",
    "authors\N{RIGHT SINGLE QUOTATION MARK} contributions", "consent for publication",
    "availability of data and materials", "ethics approval and consent to participate",
})  # fmt: skip
#: The names a structured abstract's own headings have where they stand alone, under its
#: Abstract.
ABSTRACT_PARTS = frozenset({
    "background", "methods", "method", "methodology", "materials and methods",
    "material and methods", "methods and materials", "patients and methods",
    "subjects and methods", "participants and methods", "results", "result", "findings",
    "results and discussion", "discussion", "conclusion", "conclusions", "limitations",
})  # fmt: skip
#: Where each of `ABSTRACT_PARTS` stands in the order a structured abstract's parts keep, and
#: a main text's too: what it was for, how, what was found, what it means. A paper's main
#: text opens where that order starts again, a second "Background" after "Conclusions", or
#: "Methods" after "Results".
_PART_ORDER = {
    "background": 1, "methods": 2, "method": 2, "methodology": 2, "materials and methods": 2,
    "material and methods": 2, "methods and materials": 2, "patients and methods": 2,
    "subjects and methods": 2, "participants and methods": 2, "results": 3, "result": 3,
    "findings": 3, "results and discussion": 3, "discussion": 4, "limitations": 4.5,
    "conclusion": 5, "conclusions": 5,
}  # fmt: skip
# "Limitations" after the Discussion goes on in the order: at one place, it started the
# order again, and a main text's Background to Discussion were the Abstract's (round 2 of
# #598).
#: Titles a structured abstract may hold among its parts in any place: the Lancet's Summary
#: ends on its Funding, and some abstracts on their Abbreviations.
_ANYWHERE_IN_AN_ABSTRACT = frozenset({"abbreviations", "funding"})
#: The names of an abstract, and of the Lancet's "Summary".
_ABSTRACTS = frozenset({"abstract", "structured abstract", "summary"})
#: A section's number in front of its name standing alone: "2 ", "2. ", "2.1 ", "II. ".
_ALONE_NUMBER = re.compile(r"(?:\d{1,2}(?:\.\d{1,2})*\.?|[IVX]{1,5}\.)\s+")


def section_name_alone(text: str) -> str | None:
    """The section's name `text` holds alone, its number taken off, or None: the whole text,
    less a number in front and a colon or a stop after, is one of `SECTION_NAMES`, and its
    first letter is a capital."""
    text = " ".join(text.split())
    found = _ALONE_NUMBER.match(text)
    if found is not None:
        text = text[found.end() :]
    text = text.rstrip(":.").strip()
    if not text[:1].isupper() or _key(text) not in SECTION_NAMES:
        return None
    return text


def _key(title: str) -> str:
    return " ".join(title.casefold().split())


def section_levels(
    titles: Sequence[str], worded: Sequence[bool] | None = None
) -> tuple[int, ...] | None:
    """The level of each title of `section_name_alone`'s, in order, where they can be placed
    exactly; else None. A structured abstract's headings standing alone are the Abstract's,
    level 2, where the title after the Abstract's is one of `ABSTRACT_PARTS`: they run to an
    Introduction, or to where the order of parts starts again (`_PART_ORDER`), as BMC's
    journals open the main text on a second "Background" after the abstract's
    "Conclusions"; an "Abbreviations" or a "Funding" among them is the Abstract's too. A
    title no abstract holds, "References" or "Appendix", before either, and none of the two
    after them: where they end is not read. A name twice among the rest is not placed
    either.

    `worded` says, for each title, whether words stand under it before the next. Where the
    titles after the Abstract's cannot be placed as its parts, and words stand under the
    Abstract's own title, the abstract is one or more paragraphs and the title after it the
    main text's, as a paper opens its main text on "Background" after an abstract of one
    paragraph. Not where they can be: the BMJ's parts "Objectives" and "Design", which name
    no section, stand under its Abstract as words."""
    keys = [_key(title) for title in titles]
    nested: set[int] = set()
    first = next((at for at, key in enumerate(keys) if key in _ABSTRACTS), None)
    if first is not None:
        end = _abstract_end(keys, first, worded)
        if end is None:
            return None
        nested = set(range(first + 1, end))
    for group in (nested, set(range(len(keys))) - nested):
        names = [keys[at] for at in group]
        if len(names) != len(set(names)):
            return None
    return tuple(2 if at in nested else 1 for at in range(len(keys)))


def abstract_end(titles: Sequence[str], worded: Sequence[bool]) -> int | None:
    """Where the Abstract titled by `titles[0]` ends among the titles of `section_name_alone`
    after it, as `section_levels` places them: the index of the first that is no part of it,
    `len(titles)` where none is, and None where that is not read. `worded` says, for each,
    whether words stand under it before the next."""
    return _abstract_end([_key(title) for title in titles], 0, worded)


def _abstract_end(keys: list[str], first: int, worded: Sequence[bool] | None) -> int | None:
    """The index of the first title after the Abstract's at `first` that is no part of it."""
    if first + 1 >= len(keys) or keys[first + 1] not in ABSTRACT_PARTS:
        return first + 1
    opening = _parts_end(keys, first)
    if opening is not None:
        return opening
    return first + 1 if _one_paragraph(worded, first) else None


#: A paragraph that opens on the Abstract's run-in label and goes on: "Abstract: This review
#: explores", "ABSTRACT. We read" (Basile, 2026-11-14, docx-med-B3 of the real-paper corpus).
#: Not "Abstracts were screened", nor "Abstract:" with nothing after it.
_RUN_IN_ABSTRACT = re.compile(r"\s*((?:Abstract|ABSTRACT) ?[:.])\s+(?=\S)")


def run_in_abstract(text: str) -> str | None:
    """The run-in label a paragraph opens on, as typed, "Abstract:", "Abstract :", with the
    rest of it the Abstract's text; None where it opens on none (`_RUN_IN_ABSTRACT`)."""
    found = _RUN_IN_ABSTRACT.match(text)
    return found.group(1) if found is not None else None


def abstract_alone(text: str) -> bool:
    """Whether a line's words are the Abstract's name alone, as `section_name_alone` reads a
    title: "Abstract", "ABSTRACT", "1. Abstract", "Abstract:"; not "Structured abstract" nor
    "Summary", which name it elsewhere, nor "Abstracts were screened by two reviewers"."""
    name = section_name_alone(text)
    return name is not None and _key(name) == "abstract"


def _parts_end(keys: list[str], first: int) -> int | None:
    """Where the parts of the abstract titled at `first` end: at an Introduction, or at the
    first title whose place in the order of parts is not after the one before it; None where
    a title no abstract holds comes first, or neither comes (round 1 of #598: ended at the
    first name again, the main text's "Background" and "Methods" before a second "Results"
    were the Abstract's)."""
    before = 0
    for at in range(first + 1, len(keys)):
        if keys[at] == "introduction":
            return at
        if keys[at] in _ANYWHERE_IN_AN_ABSTRACT:
            continue
        place = _PART_ORDER.get(keys[at])
        if place is None:
            return None
        if place <= before:
            return at
        before = place
    return None


def _one_paragraph(worded: Sequence[bool] | None, first: int) -> bool:
    """Whether words stand under the Abstract's own title, so that it is no structured
    abstract's: known only where `worded` is given."""
    return worded is not None and worded[first]


__all__ = [
    "ABSTRACT_PARTS",
    "SECTION_NAMES",
    "bare",
    "methods_sections",
    "names_abstract",
    "names_conclusion",
    "names_discussion",
    "names_introduction",
    "names_introduction_material",
    "names_paper_summary",
    "names_methods",
    "names_results",
    "names_statement",
    "plain",
    "section_levels",
    "section_name_alone",
]
