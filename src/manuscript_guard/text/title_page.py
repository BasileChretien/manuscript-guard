"""Where a manuscript's title page is, so that G14 does not read its abbreviations.

A title page names departments, units and institutions, "INSERM U1237", "UMR-S", "CHU de
Caen Normandie", none of which a paper defines (Basile, 2026-11-12). So the abbreviation
reading passes over it: nothing on it is a definition, nor a use of one the text gives; its
words are a use only of an entry of the list of abbreviations, which covers the title page
too (`gates/language.py`). The paper is read from where the title page ends, as before.

Not every paper has an abstract: a letter has none, and opens with "Dear Editor". So the
end is not looked for by one word. The text is read from its opening, block by block, a
paragraph or a heading, and each is put in one of five kinds:

* `SIGNAL`, a line only a title page holds: an affiliation (`_an_affiliation`), an e-mail
  address, an ORCID iD, authors with their degrees or the marks of their affiliations, or a
  label, "Corresponding author", "Running title", "Word count", "Keywords" (`_LABEL`);
* `NEUTRAL`, a line that may stand on one and says nothing either way: names with no mark,
  a date, a note under a mark, "\\*These authors contributed equally";
* `OPENING`, the paper's opening: a heading or a paragraph that is only the name of a
  section a paper opens on, the Abstract, the Introduction, the Methods and the rest
  (`_OPENING_NAMES`), a run-in label of one, "Background: ...", or a letter's salutation;
* `OTHER`, another heading: a back matter's name, or one past the first that names nothing;
* `PROSE`, a paragraph with a word a sentence is made of and an affiliation is not, "we",
  "was", "this", "a" (`_SENTENCE`), "the" twice, or one sentence ending before another.

The title page runs from the opening to the first block of the last three kinds, and is
the title page only where it holds a line only a title page holds: one where the paper's
opening ends it, two where anything else does, and no more than 600 words in all, which is
what `init --from` sets aside as one. The first block is the title, which may read as prose
where it is short, a sentence at most and with no stop at its end, and whose institution
is no affiliation.

Where nothing marks a title page there is none, and the whole text is read. That is the
side to be wrong on: a title page found where there is none hides real findings in the
paper's opening. DESIGN.md, under "Known gaps", says what this does not find.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from manuscript_guard.text.blocks import Heading
from manuscript_guard.text.masking import NUL
from manuscript_guard.text.section_names import (
    ABSTRACT_PARTS,
    SECTION_NAMES,
    plain,
    section_name_alone,
)

#: The most words a title page holds, as `init --from` sets one aside
#: (`from_word.TITLE_PAGE_WORDS`): a title, a long list of authors with their affiliations,
#: and the corresponding author's address come to less.
MOST_WORDS = 600
#: The most lines and words of a first paragraph read as the title where it reads as prose.
TITLE_LINES = 3
TITLE_WORDS = 40
#: A paragraph of more lines than this, opening the text, is read line by line, where none
#: of its lines holds a sentence: the lines of a PDF stand in one paragraph, and so do those
#: of a title page typed a line to each. A paragraph of prose wrapped over several lines is
#: one block, whose lines are read together.
SPLIT_LINES = 3

SIGNAL = "signal"
NEUTRAL = "neutral"
OPENING = "opening"
OTHER = "other"
PROSE = "prose"

#: The names a paper's own text opens on, of `SECTION_NAMES`: an abstract, the parts of a
#: structured one, and the Introduction. With the names that open a letter, a summary box
#: or a structured abstract's first part and are no heading `SECTION_NAMES` reads alone; and
#: an abstract's name in French, Spanish, Portuguese, German and Italian. A list of
#: abbreviations opens the paper too (`_opens_a_list`).
_OPENING_NAMES = frozenset({
    "abstract", "structured abstract", "summary", "introduction", *ABSTRACT_PARTS,
    "main text", "letter", "research letter", "letter to the editor", "highlights",
    "key points", "research in context", "plain language summary", "lay summary",
    "simple summary", "graphical abstract", "objective", "objectives", "aim", "aims",
    "purpose", "importance", "context", "rationale",
    "résumé", "resumen", "resumo", "zusammenfassung", "riassunto",
})  # fmt: skip

#: A label only a title page holds, at the paragraph's start in bold or not, with a colon
#: after it or the paragraph ending on it: "Corresponding author:", "**Running title**",
#: "Word count: 3,412", "Keywords: ...", "E-mail: ...". "Corresponding author" and
#: "Correspondence" are read with anything after them, "Correspondence to Dr ...", and so
#: are their French, "Correspondance", "Auteur correspondant"; "Mots-clés", "Palabras
#: clave" and "Schlüsselwörter" are keywords.
_LABEL = re.compile(
    r"[*_\s]*(?:"
    r"(?:\*?corresponding\s+authors?|correspondence|address\s+(?:for\s+)?correspondence"
    r"|correspondance|auteurs?\s+correspondants?)\b"
    r"|(?:(?:short|running)\s+(?:title|head)|title\s+page"
    r"|(?:abstract\s+|main\s+text\s+|total\s+|text\s+)?word\s+counts?"
    r"|key\s*-?\s*words?|mots[\s-]+cl[ée]s|palabras\s+clave|schl[üu]sselw[öo]rter"
    r"|parole\s+chiave|e-?mails?(?:\s+address(?:es)?)?|tel(?:ephone)?|phone|fax"
    r"|orcid(?:\s+i[dD]s?)?|affiliations?|authors?(?:\s+(?:names?|list|information|details))?"
    r"|(?:number|no\.?)\s+of\s+(?:tables|figures|references|words)"
    r"|article\s+type|type\s+of\s+(?:article|manuscript|paper)|manuscript\s+type"
    r")\.?[*_\s]*(?::|$))",
    re.IGNORECASE,
)
#: An e-mail address and an ORCID iD.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ORCID = re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{3}[\dX]\b|\borcid\b", re.IGNORECASE)
#: What names an institution in an affiliation, in the languages papers are most often
#: written in: "Department of Pharmacology", "Université de Caen", "INSERM U1237",
#: "UMR-S 1237", "Centre hospitalier universitaire", "Graduate School of Medicine",
#: "Département", "Departamento", "Dipartimento", "Abteilung", "Service de Pharmacologie".
_INSTITUTION = re.compile(
    r"(?<![\w-])(?:"
    r"departments?|dept\.?|d[ée]partements?|departamentos?|dipartimento|abteilung"
    r"|servic(?:e|io)\s+de|facult(?:y|ies|é|e|ad|ade|à)|universit(?:y|ies|é|à|ät|at|ad|ade|eit)"
    r"|univ\.|institut(?:e|es|o|s)?|istituto|hospitals?|hôpital|hôpitaux|hospitali(?:er|ère)"
    r"|klinik(?:um)?|clinics?|clinique|cl[ií]nica|schools?|[ée]cole|colleges?|coll[eè]ge"
    r"|laborator(?:y|ies)|laboratoire|labs?|cent(?:re|er|res|ers|ro|rum)|zentrum|units?|unité"
    r"|unidad|division|inserm|cnrs|umr(?:-s)?|inrae?|chu|chru|ap-hp|graduate\s+school"
    r")(?![\w-])",
    re.IGNORECASE,
)
#: A degree after a name, "Jane Doe, MD, PhD", or a title before one, "Dr. Jane Doe".
_DEGREES = re.compile(
    r",\s*(?:MD|M\.D\.|PhD|Ph\.D\.?|PharmD|Pharm\.D\.?|MSc|M\.Sc\.?|BSc|MPH|MBBS|MBChB|MBA"
    r"|DPhil|DrPH|ScD|DSc|RN|BSN|MSN|DNP|FRCP\w*|FRACP|FACP|DDS|DMD|DVM|MRes|MPhil|MMed"
    r"|MS|MA|BA|BS)\b"
    r"|^(?:Dr|Prof|Professor)\.?\s+[A-Z]"
)
#: A name with the mark of an affiliation after it: "DUMONT\\*^1^", "Smith^2,3^",
#: "Lee<sup>a</sup>", and, as a PDF prints a superscript, "Doe1,2".
_MARKED = re.compile(
    r"[^\W\d_]{2}(?:\\?\*|[\N{DAGGER}\N{DOUBLE DAGGER}\N{SECTION SIGN}\N{PILCROW SIGN}])*"
    r"(?:\^[^\s^]{1,20}\^|<sup>[^<]{1,20}</sup>)"
)
_PRINTED_MARKS = re.compile(r"[a-z]{2}\d{1,2}(?:,\d{1,2})*\*?(?=[,;\s]|$)")
#: A note under a mark, as a title page has one: "\\*These authors contributed equally",
#: "\N{DAGGER}Deceased", "^a^ Present address: ...".
_NOTE = re.compile(
    r"(?:\\\*|\*(?!\*)|[\N{DAGGER}\N{DOUBLE DAGGER}\N{SECTION SIGN}\N{PILCROW SIGN}]"
    r"|\^[^\s^]{1,10}\^)"
)
_NOTE_WORDS = 30
#: A letter's salutation: "Dear Editor,", "Dear Sir or Madam,", "Dear Dr Smith,", "To the
#: Editor:", "Sir,", and what opens a letter to nobody in particular; in French, "Madame,
#: Monsieur,", "Cher collègue,", in Spanish, "Estimado editor:", in German, "Sehr geehrte".
_SALUTATION = re.compile(
    r"[*_\s]*(?:dear\s+(?:editors?|sirs?|madam|colleagues?|dr\b|prof|professor|mr\b|mrs\b"
    r"|ms\b)|dear\s+[^\n,:]{1,60}[,:]\s*$|to\s+the\s+editors?\b|sirs?\s*[,:\N{EM DASH}]"
    r"|madam\s*[,:]|to\s+whom\s+it\s+may\s+concern"
    r"|madame,?\s+monsieur\s*[,:]|monsieur\s*[,:]|madame\s*[,:]|ch[eè]re?s?\s+[^\n,:]{1,60}[,:]"
    r"|estimad[oa]s?\s+[^\n,:]{1,60}[,:]|sehr\s+geehrte)",
    re.IGNORECASE,
)
#: The words a sentence is made of and an affiliation or a list of names is not: pronouns,
#: the forms of "be" and "have", articles. In small letters, and the few that open a
#: sentence in capitals. Not "do", "i" or "e", which name institutions in Portuguese,
#: Catalan and Italian ("Universidade do Porto", "Hospital de la Santa Creu i Sant Pau").
_SENTENCE_WORDS = (
    "a an we our us was were is are be been being has have had this these those that "
    "which who whom whose it its they their them there not than can could would should "
    "will did does because however although while when if how what also such between "
    "among into using used he she his her you your here but nous est sont ont une cette "
    "qui que"
)
_SENTENCE = frozenset(_SENTENCE_WORDS.split())
_SENTENCE_OPENING_WORDS = (
    "We Our This These Those It Its They Their There However Although Here"
)
_SENTENCE_OPENING = frozenset(_SENTENCE_OPENING_WORDS.split())
#: "the" twice makes a sentence too: an affiliation has it once at most.
_THE_TWICE = 2
#: The most words between two commas or semicolons of an affiliation, less the small words
#: of `_SMALL`: "Brigham and Women's Hospital and Harvard Medical School" has six, "Institut
#: national de la santé et de la recherche médicale (INSERM)" six. A sentence that names a
#: university runs longer between its commas.
_PIECE_WORDS = 10
_PIECES = re.compile(r"[,;\n]")
#: The small words a name or an affiliation keeps in small letters, which do not count
#: towards a line's share of small letters.
_SMALL_WORDS = (
    "of de du des la le les et and for the à au aux d l y del della di der die das und "
    "für van von da do dos e en in on at"
)
_SMALL = frozenset(_SMALL_WORDS.split())
#: A paragraph of prose by its share of words in small letters, where it holds none of the
#: words of `_SENTENCE`: at least this many words, and this share of them.
_PROSE_WORDS = 8
_PROSE_SHARE = 0.6
#: A sentence's end inside a paragraph, before the next sentence's capital: after a word
#: that is no initial, no short form in capitals ("MSc. Paul"), and none of the words a
#: title page shortens with a stop (`_SHORTENED`).
_SENTENCE_BREAK = re.compile(
    r"(?P<word>[^\W\d_]+)[.!?][\"'\N{RIGHT DOUBLE QUOTATION MARK})]*\s+[A-Z]"
)
_SHORTENED_WORDS = (
    "dr mr mrs ms st prof univ dept inst hosp inc ltd ave str blvd jr sr no vol fig"
)
_SHORTENED = frozenset(_SHORTENED_WORDS.split())
_WORD = re.compile(r"[^\W\d_][\w'\N{RIGHT SINGLE QUOTATION MARK}-]*")
#: Marks a word count passes over: a superscript, a subscript, a tag.
_RAISED = re.compile(r"\^[^\s^]{1,20}\^|~[^\s~]{1,20}~|<[^<>\n]{1,40}>")
_ESCAPE = re.compile(r"\\(.)")
#: A list's or a quotation's mark at a line's start.
_LIST_MARK = re.compile(r"[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\(?\d{1,3}[.)]|[a-z][.)])[ \t]+)?")
#: A run-in label at a paragraph's start: "**Abstract**", "Background:", "__Methods.__".
_RUN_IN = re.compile(
    r"[*_]{0,3}(?P<name>[^\W\d_][^*_:.\n]{0,40}?)[*_]{0,3}[ \t]*(?:[:.]|(?<=[*_])(?=\s))"
)


@dataclass(frozen=True)
class _Block:
    start: int
    text: str
    heading: Heading | None = None


def title_page_end(
    seen: str, headings: Sequence[Heading], abstract_title: str | None = None
) -> int | None:
    """Where the title page that opens `seen` ends, or None where it opens with none.

    `seen` is the file as G14 reads it, everything that is no sentence nor heading, the
    front matter among them, blanked with NUL or spaces and its offsets kept; `headings`
    are the file's. `abstract_title` is the abstract's name in the journal's profile,
    "Summary" in The Lancet."""
    signals = words = 0
    end, kind = len(seen), OTHER
    for at, block in enumerate(_blocks(seen.replace(NUL, " "), headings)):
        found = _kind(block, abstract_title, first=at == 0)
        if found in (SIGNAL, NEUTRAL):
            signals += found == SIGNAL
            words += len(_words(block.text))
            if words > MOST_WORDS:
                return None
            continue
        end, kind = block.start, found
        break
    needed = 1 if kind == OPENING else 2
    return end if signals >= needed else None


def _blocks(seen: str, headings: Sequence[Heading]) -> Iterator[_Block]:
    """The blocks of `seen` in order: each heading, and each run of lines between blank
    lines and headings. The first, where it has more lines than `SPLIT_LINES`, a line to
    each block."""
    titled = {heading.start: heading for heading in headings}
    lines: list[tuple[int, str]] = []
    at = 0
    for line in seen.split("\n"):
        lines.append((at, line))
        at += len(line) + 1
    paragraph: list[tuple[int, str]] = []
    first = True
    skip = 0

    def flushed() -> Iterator[_Block]:
        nonlocal first
        if not paragraph:
            return
        if first and len(paragraph) > SPLIT_LINES and not any(
                _a_sentence(_words(line), line) for _start, line in paragraph):  # fmt: skip
            yield from (_Block(start, line) for start, line in paragraph)
        else:
            yield _Block(paragraph[0][0], "\n".join(line for _start, line in paragraph))
        first = False
        paragraph.clear()

    for index, (start, line) in enumerate(lines):
        if index < skip:
            continue
        heading = titled.get(start)
        if heading is not None:
            yield from flushed()
            first = False
            skip = index + (2 if heading.setext else 1)
            yield _Block(start, line, heading)
            continue
        if not line.strip():
            yield from flushed()
            continue
        paragraph.append((start, line))
    yield from flushed()


def _kind(block: _Block, abstract_title: str | None, *, first: bool) -> str:
    """Which of the five kinds `block` is (`SIGNAL`, `NEUTRAL`, `OPENING`, `OTHER`,
    `PROSE`); `first` where it opens the text, and may be the title."""
    if block.heading is not None:
        return _heading_kind(block.heading.title, abstract_title, first=first)
    text = _ESCAPE.sub(r"\1", "\n".join(_LIST_MARK.sub("", line, count=1)
                                        for line in block.text.split("\n")))  # fmt: skip
    joined = " ".join(text.split())
    named = _named(joined, abstract_title, first=first)
    if named is not None:
        return named
    if _SALUTATION.match(joined):
        return OPENING
    if _LABEL.match(joined):
        return SIGNAL
    found = _paragraph_kind(block.text, joined, first=first)
    if found == PROSE and first and _a_title(block.text, joined):
        return NEUTRAL
    return found


def _heading_kind(title: str, abstract_title: str | None, *, first: bool) -> str:
    """A heading's kind: the paper's opening where it names a section a paper opens on, or
    any other section where it names one, a line of the title page where it names a label
    of one, "Corresponding author", and else the title where it opens the text."""
    bare = " ".join(plain(title).split())
    named = _named(bare, abstract_title, first=first)
    if named is not None:
        return named
    if _LABEL.match(bare):
        return SIGNAL
    return NEUTRAL if first else OTHER


def _named(text: str, abstract_title: str | None, *, first: bool = False) -> str | None:
    """`OPENING` where `text` is a section's name a paper opens on, alone or as a run-in
    label; `OTHER` where it is another section's name alone; None where it is neither.
    The whole name, not its first word: "Abstract word count: 250" is a title page's line,
    which `names_abstract` would take for the Abstract."""
    alone = plain(text).rstrip(" :.")
    if _opens(alone, abstract_title) or (not first and _opens_a_list(text)):
        return OPENING
    if (section_name_alone(alone) is not None or _key(alone) in SECTION_NAMES) \
            and not _labels_a_title_page(text):  # fmt: skip
        return OTHER
    label = _RUN_IN.match(text)
    if label is not None and _opens(label.group("name"), abstract_title):
        return OPENING
    return None


def _labels_a_title_page(text: str) -> bool:
    """Whether a section's name is a label a title page holds too (`_LABEL`), "**Author
    information**" over the affiliations, which ends no title page: made a section's name for
    docx-socio-A2 (Basile, 2026-11-14), it ended one, and G14 read the affiliations as prose
    (round 2 of #683). Read as written and as `plain` reads it, so an underline's markup,
    "**[Author Information]{.underline}**", hides no label (round 3)."""
    return _LABEL.match(text) is not None or _LABEL.match(plain(text)) is not None


def _opens_a_list(text: str) -> bool:
    """Whether `text`, a heading's title or a paragraph, opens a list of abbreviations as
    G14's glossary reads one: a heading it takes for a glossary's (`glossary.is_glossary`), or
    a paragraph opening with the words a glossary with no title opens with
    (`glossary.opens_one`), "**Abbreviations and acronyms**", "Glossary of terms". A journal
    may ask for the list on the title page itself (Pediatrics, "Abbreviations: Food and Drug
    Administration (FDA); ..."): it defines, and is read. The title page ends where the
    glossary's pattern or titles would open a list, "List of acronyms", or "Abréviations"."""
    from manuscript_guard.gates import glossary

    return glossary.is_glossary(plain(text)) or glossary.opens_one(text) or bool(
        re.match(r"[*_\s]*(?:liste\s+des\s+)?abr[ée]viations\b", text, re.IGNORECASE))


def _opens(name: str, abstract_title: str | None) -> bool:
    """Whether `name`, a number before it or none, is one a paper opens on."""
    key = _key(plain(name).rstrip(" :."))
    return key in _OPENING_NAMES or (bool(abstract_title) and key == _key(str(abstract_title)))


def _paragraph_kind(raw: str, joined: str, *, first: bool = False) -> str:
    """The kind of a paragraph that is no section's name, salutation or label. `first`
    where it opens the text and may be the title, whose institution, "Burnout among
    nurses of a university hospital", is no affiliation."""
    words = _words(joined)
    if _a_sentence(words, joined):
        return NEUTRAL if _NOTE.match(raw.lstrip()) and len(words) <= _NOTE_WORDS else PROSE
    if _EMAIL.search(joined) or _ORCID.search(joined) or _DEGREES.search(joined):
        return SIGNAL
    if _MARKED.search(raw) or len(_PRINTED_MARKS.findall(joined)) >= 2:
        return SIGNAL
    if not first and _an_affiliation(raw):
        return SIGNAL
    counted = [word for word in words if word.lower() not in _SMALL]
    small = sum(1 for word in counted if word[0].islower())
    if len(words) >= _PROSE_WORDS and counted and small / len(counted) >= _PROSE_SHARE:
        return PROSE
    return NEUTRAL


def two_sentences(text: str) -> bool:
    """Whether a paragraph's text holds two sentences, one ending before another, the one
    sign of `_a_sentence`'s that no heading has (`_broken`): a word only a sentence has, or
    "the" twice, is in "Strengths and limitations of this study" too (round 2 of #688)."""
    return _broken(text)


def _a_sentence(words: list[str], joined: str) -> bool:
    """Whether a paragraph holds a sentence: a word of `_SENTENCE`, "the" twice, or one
    sentence ending before another."""
    return (any(word in _SENTENCE or word in _SENTENCE_OPENING for word in words)
            or words.count("the") >= _THE_TWICE or _broken(joined))  # fmt: skip


def _broken(joined: str) -> bool:
    """Whether one sentence ends in `joined` before another opens (`_SENTENCE_BREAK`)."""
    for found in _SENTENCE_BREAK.finditer(joined):
        word = found.group("word")
        if len(word) > 1 and word.casefold() not in _SHORTENED and word[1:].islower():
            return True
    return False


def _an_affiliation(raw: str) -> bool:
    """Whether a paragraph names an institution (`_INSTITUTION`) in pieces no longer than
    an affiliation's, between commas, semicolons and line breaks."""
    if not _INSTITUTION.search(raw):
        return False
    return all(len([word for word in _words(piece) if word.lower() not in _SMALL])
               <= _PIECE_WORDS for piece in _PIECES.split(raw))  # fmt: skip


def _a_title(raw: str, joined: str) -> bool:
    """Whether the paragraph opening the text may be its title, though it reads as prose:
    a few lines, a few words, one sentence at most and no stop at its end."""
    ending = joined.rstrip(" *_")
    return (len(raw.split("\n")) <= TITLE_LINES and len(_words(joined)) <= TITLE_WORDS
            and not _broken(joined) and not ending.endswith("."))  # fmt: skip


def _words(text: str) -> list[str]:
    return _WORD.findall(_RAISED.sub(" ", text))


def _key(name: str) -> str:
    return " ".join(name.casefold().split())


__all__ = ["MOST_WORDS", "title_page_end", "two_sentences"]
