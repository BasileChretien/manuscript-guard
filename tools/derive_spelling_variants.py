"""Derive `src/manuscript_guard/data/spelling_variants.tsv` from VarCon's `varcon.txt`.

VarCon (Variant Conversion Info, Kevin Atkinson and Benjamin Titze) records, for each word
English spells in more than one way, which spelling American, British and Oxford usage
prefer and which others each of them accepts. G14's spelling reading needs a small part of
that: the words one side of the Atlantic writes and the other does not, and the words
British usage writes with `-ise` or with `-ize`.

The source file is not in this repository. To derive the data again:

    python tools/derive_spelling_variants.py path/to/varcon.txt

The file must be the one pinned below, by its SHA-256, so that the committed data is a
function of a known source and of this script, and of nothing else. To move to a later
VarCon, change `SOURCE` here, run this, and read the diff of the data file.

What is kept, and why each rule is there:

* A spelling is **accepted** by a usage when VarCon marks it preferred, equal or a variant
  there (no indicator, `.` or `v`). A seldom-used variant (`V`), a possible one (`-`) and
  an improper one (`x`) are not accepted. With no `Z` tag on a line, `B` stands for `Z`,
  as VarCon's README says.
* Acceptance is gathered over **every** line a word stands on, in every cluster. "meter"
  is the American spelling of the unit and everybody's spelling of the instrument, so it
  is accepted in British usage and is never reported. That is the conservative side: a
  word is reported only when no line of VarCon accepts it for the paper's English.
* A word is written out only where its line has a preferred spelling for the other usage
  that differs from it, so every row can say what to write instead. The column numbers
  VarCon gives some lines are not read, so a derived form is paired with its line's
  preferred spelling and not with its own column's: "amebae" is told "amoebas".
* A spelling both usages have as a variant is neither's. On the line that gives
  "embedding" to both and "imbedding" as a variant in British usage and a seldom-used one
  in American, "imbedding" is not the British spelling of anything, and writes no row.
* Clusters above SCOWL level 80 are read for acceptance and write no rows: VarCon says of
  them that the headword "may not even be a legal word".
* VarCon marks the clusters it has checked against dictionaries as `<verified>`, and says
  of the rest that they held numerous errors. They do: one gives "et" as the American
  spelling of "aet", another "micelle" as that of "micellae". So a cluster that is not
  verified is read for acceptance, and writes a row only for a correspondence the
  spelling itself shows: a verb in `-ise` and its noun in `-isation`, never one of the
  verbs that are `-ise` in any English (`ONLY_ISE`); and the combining forms British
  spelling writes with a digraph (`DIGRAPHS`), `haem-` and `-aemia` among them. Without
  those, "haemodynamic", "bacteraemia" and "anonymise" would not be in the list. The
  letters of a form can be another root's: `ped-` is the child's and also the soil's, and
  `paed-` gave the "pedogenic" of soil science to American usage as a spelling of
  "paedogenic"; `amoeb-` respelt a genus, "Entamoeba". Where a line of VarCon pairs such
  a word through a form, the word is named in `EVERYWHERE` and the form stays, since
  without it "pedodontics" and "amebiasis" pass in a British paper. The British halves
  of the same lines are named too where American usage writes them: "amoebiasis"
  beside the "amoebic" VarCon verified for both, and the zoologist's "paedomorphosis".
* A word of fewer than four letters writes no row. "ax" and "mom" are spellings, and in
  a manuscript a word that short is more often a symbol or a variable.
* Only words of lower-case ASCII letters are written. Possessives repeat their base word,
  and a proper name keeps its own spelling whatever the paper's.
* VarCon records general usage, and science writes a few words one way everywhere. Those
  write no row: `EVERYWHERE` names them, each with its authority, and every word with
  `sulf` in it is taken out of the American rows, since "sulfur" and what derives from it
  is IUPAC's spelling in any English. These are the only places where this script knows
  better than its source, and the list is meant to stay short.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: The file this data is a function of.
SOURCE = {
    "name": "varcon.txt",
    "version": "VarCon 2020.12.07, as changed up to 2024-07-22",
    "repository": "https://github.com/en-wl/wordlist",
    "commit": "1605448f6522e9dd432287eff44dfa7232b39c94",
    "path": "varcon/varcon.txt",
    "sha256": "75af63da46ec12d7eb14b9f1ba8d3898d484dd6872755b73c921b215875a3629",
}

TARGET = Path(__file__).resolve().parent.parent / "src/manuscript_guard/data/spelling_variants.tsv"

#: Clusters above this SCOWL level write no rows.
HIGHEST_LEVEL = 80
#: The variant indicators that count as accepted: none, equal, variant.
ACCEPTED = ("", ".", "v")
USAGES = ("A", "B", "Z")

#: Words VarCon gives to one usage and scientific writing spells this way in both, or that
#: a line of VarCon pairs wrongly, with the reason for each. No row is written for them, so
#: the check never reports them. Each one here takes a row out of the list: a test holds
#: that, so the table does not gather words that were never in it.
EVERYWHERE = {
    "acknowledgment": "British dictionaries give it beside acknowledgement, and it heads "
    "the section in journals of either usage",
    "acknowledgments": "as acknowledgment",
    "adaptor": "the spelling of molecular biology in either English, and of the MeSH "
    "heading for adaptor proteins",
    "adaptors": "as adaptor",
    "amoeban": "as amoebiasis",
    "amoebean": "as amoebiasis",
    "amoebiases": "as amoebiasis",
    "amoebiasis": "American usage writes amoeb- too: VarCon's verified lines give "
    "amoeba, amoebic and amoeboid to both usages, and only its unverified ones call "
    "this British",
    "amoebiform": "as amoebiasis",
    "amoebocyte": "as amoebiasis",
    "amoebocytes": "as amoebiasis",
    "blaise": "a given name, and nobody writes the verb VarCon has",
    "diethylstilbestrol": "as estradiol",
    "endamoeba": "as entamoeba",
    "endamoebae": "as entamoeba",
    "endamoebas": "as entamoeba",
    "entamoeba": "a genus, Entamoeba, whose name is Latin and is not respelt",
    "entamoebae": "as entamoeba",
    "entamoebas": "as entamoeba",
    "estradiol": "the recommended International Nonproprietary Name, which British "
    "medicine has used since 2003 in place of oestradiol",
    "estradiols": "as estradiol",
    "estriol": "as estradiol",
    "estriols": "as estradiol",
    "estrone": "as estradiol",
    "estrones": "as estradiol",
    "flyer": "American dictionaries give it beside flier, and it is the usual spelling of "
    "a leaflet in either English",
    "flyers": "as flyer",
    "hematite": "the name the International Mineralogical Association gives the mineral",
    "hematites": "as hematite",
    "hematitic": "as hematite",
    "myxamoeba": "as amoebiasis",
    "paedogeneses": "as paedomorphosis",
    "paedogenesis": "as paedomorphosis",
    "paedogenetic": "as paedomorphosis",
    "paedogenic": "as paedomorphosis",
    "paedomorphic": "as paedomorphosis",
    "paedomorphism": "as paedomorphosis",
    "paedomorphisms": "as paedomorphosis",
    "paedomorphoses": "as paedomorphosis",
    "paedomorphosis": "a zoologist's word that American zoology writes so too",
    "pedagogism": "British usage writes pedagogy and pedagogue, and this like them",
    "pederastic": "British usage prefers pederast, by VarCon's own verified line",
    "pederastically": "as pederastic",
    "pedogeneses": "as pedogenesis",
    "pedogenesis": "the forming of soil, from the Greek for ground: no word of the "
    "child's root, and spelt so in any English",
    "pedogenetic": "as pedogenesis",
    "pedogenic": "as pedogenesis",
    "pedological": "as pedogenesis: of pedology, the study of soils",
    "pedologist": "as pedological",
    "pedologists": "as pedological",
    "porer": "one who pores, which a line of VarCon pairs with pourer, one who pours",
    "pourer": "as porer",
    "pyrolyses": "the plural of pyrolysis, which VarCon has only as a form of the verb",
    "rigor": "the clinical sign, and rigor mortis, are spelt so in British medicine",
    "rigors": "as rigor",
    "scapaed": "the word nobody writes that the form paed- pairs with scaped",
    "scaped": "having a scape, which the form paed- pairs with a word nobody writes",
    "specialty": "the word of British medicine for a branch of practice",
    "specialties": "as specialty",
    "stilbestrol": "as estradiol",
    "stilbestrols": "as estradiol",
}
#: IUPAC's spelling of sulfur, and of every name made from it, in any English.
IUPAC = "sulf"

#: The shortest word that writes a row.
SHORTEST = 4

#: From a cluster VarCon has not verified: the combining forms British spelling writes
#: with a digraph, and what American spelling writes for each. Two of them reach words
#: they should not respell, which `EVERYWHERE` names: `paed-` the soil's "pedogenic", and
#: `amoeb-` the genus "Entamoeba" and the spellings American usage writes too.
DIGRAPHS = {
    "aemi": "emi",
    "aetiol": "etiol",
    "amoeb": "ameb",
    "anaesth": "anesth",
    "coeli": "celi",
    "gynaec": "gynec",
    "haem": "hem",
    "oedem": "edem",
    "oesoph": "esoph",
    "oestr": "estr",
    "paed": "ped",
    "palaeo": "paleo",
    "pnoea": "pnea",
    "rrhoea": "rrhea",
}
#: From a cluster VarCon has not verified: a verb in -ise, and its noun in -isation.
_VERB = re.compile(r"(?P<stem>[a-z]{3,}is)(?:e|ed|es|ing|ation|ations)")
#: The verbs that are -ise in any English, as far as their s: a word that ends in one of
#: them is not taken from a cluster nobody verified. New Hart's Rules gives the list. The
#: last is no verb: "-wise" makes adverbs, "weftwise", "stepwise".
ONLY_ISE = (
    "advertis", "advis", "chastis", "circumcis", "compromis", "demis", "despis", "devis",
    "disguis", "excis", "exercis", "franchis", "improvis", "incis", "merchandis", "premis",
    "pris", "promis", "revis", "supervis", "surmis", "televis", "wis",
)  # fmt: skip

_HEADER = re.compile(r"# .*\(level (?P<level>\d+)\)")
_VERIFIED = "<verified>"
_TAG = re.compile(r"(?P<usage>[ABZCD_])(?P<indicator>[.vV\-x]?)\d*$")
_WORD = re.compile(r"[a-z]+")

NOTICE = """\
# Spelling variants, derived from VarCon. THIS IS A MODIFIED VERSION of VarCon's data: a
# selection of its words, in another format. It is not VarCon's own file.
#
# Derived by tools/derive_spelling_variants.py from:
#   {name}, {version}
#   {repository}, commit {commit}, {path}
#   SHA-256 {sha256}
#
# Columns, separated by tabs:
#   word     a spelling, in lower case
#   kind     us   accepted in American usage and not in British
#            gb   accepted in British usage and not in American
#            ise  the British spelling with -ise of a word that Oxford and American usage
#                 write with -ize
#   A few words VarCon gives to one usage are left out, because science writes them so in
#   both: the script names each and its authority.
#   instead  what the other usage writes: for `us`, the spelling British usage prefers
#            (and Oxford's after a slash, where it differs); for `gb`, the spelling
#            American usage prefers; for `ise`, the spelling with -ize
#
# Never edit this file by hand: change the script and run it.
#
# VarCon's notices, which its terms ask to travel with every copy:
#
# Copyright 2000-2020 by Kevin Atkinson (kevina@gnu.org) and Benjamin Titze
# (btitze@protonmail.ch).
#
# Copyright 2000-2019 by Kevin Atkinson
#
# Permission to use, copy, modify, distribute and sell this array, the associated
# software, and its documentation for any purpose is hereby granted without fee, provided
# that the above copyright notice appears in all copies and that both that copyright
# notice and this permission notice appear in supporting documentation. Kevin Atkinson
# makes no representations about the suitability of this array for any purpose. It is
# provided "as is" without express or implied warranty.
#
# Copyright 2016 by Benjamin Titze
#
# Permission to use, copy, modify, distribute and sell this array, the associated
# software, and its documentation for any purpose is hereby granted without fee, provided
# that the above copyright notice appears in all copies and that both that copyright
# notice and this permission notice appear in supporting documentation. Benjamin Titze
# makes no representations about the suitability of this array for any purpose. It is
# provided "as is" without express or implied warranty.
#
# Since the original words lists come from the Ispell distribution:
#
# Copyright 1993, Geoff Kuenning, Granada Hills, CA
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are
# permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of
#    conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list
#    of conditions and the following disclaimer in the documentation and/or other
#    materials provided with the distribution.
# 3. All modifications to the source code must be clearly marked as such. Binary
#    redistributions based on modified source code must be clearly marked as modified
#    versions in the documentation and/or other materials provided with the distribution.
# (clause 4 removed with permission from Geoff Kuenning)
# 5. The name of Geoff Kuenning may not be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY GEOFF KUENNING AND CONTRIBUTORS ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL
# GEOFF KUENNING OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
# TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""


@dataclass
class Line:
    """One line of VarCon: for each usage, the spelling it prefers, those it accepts, and
    those the line tags for it at all, a seldom-used variant included."""

    level: int
    verified: bool = False
    preferred: dict[str, str] = field(default_factory=dict)
    accepted: dict[str, set[str]] = field(default_factory=dict)
    tagged: dict[str, set[str]] = field(default_factory=dict)


def read_line(text: str, level: int, verified: bool = False) -> Line | None:
    """A data line of varcon.txt, or None for one with no American or British tag."""
    body = text.split(" | ")[0].split(" # ")[0].strip()
    entries: list[tuple[dict[str, str], str]] = []
    for entry in body.split(" / "):
        tags, colon, word = entry.rpartition(": ")
        if not colon:
            return None
        marks: dict[str, str] = {}
        for token in tags.split():
            found = _TAG.match(token)
            if found is not None:
                marks[found["usage"]] = found["indicator"]
        entries.append((marks, word.strip()))
    if not any(usage in marks for marks, _ in entries for usage in ("A", "B", "Z")):
        return None
    # "If there are no tags with the 'Z' spelling category on the line then 'B' implies 'Z'."
    if not any("Z" in marks for marks, _ in entries):
        for marks, _ in entries:
            if "B" in marks:
                marks["Z"] = marks["B"]
    line = Line(level, verified)
    for marks, word in entries:
        for usage in USAGES:
            if usage in marks:
                line.tagged.setdefault(usage, set()).add(word)
            if marks.get(usage) in ACCEPTED:
                line.accepted.setdefault(usage, set()).add(word)
                if marks[usage] == "":
                    line.preferred.setdefault(usage, word)
    return line


def read(text: str) -> list[Line]:
    lines: list[Line] = []
    level = 0
    verified = False
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("##"):
            continue
        if raw.startswith("#"):
            header = _HEADER.match(raw)
            level = int(header["level"]) if header else HIGHEST_LEVEL + 1
            verified = _VERIFIED in raw
            continue
        line = read_line(raw, level, verified)
        if line is not None:
            lines.append(line)
    return lines


def _one_letter_apart(ise: str, ize: str) -> bool:
    """`organise` and `organize`: the same word but for an `is` where the other has `iz`.
    Not `hydrolysate` and `hydrolyzate`: `-yse` is not an ending British usage chooses."""
    if len(ise) != len(ize):
        return False
    apart = [at for at, (a, b) in enumerate(zip(ise, ize, strict=True)) if a != b]
    if len(apart) != 1:
        return False
    (at,) = apart
    return at > 0 and ise[at - 1 : at + 1] == "is" and ize[at] == "z"


def _regular(word: str, kind: str, instead: str) -> bool:
    """Is this row one of the correspondences taken from a cluster nobody verified?"""
    if kind == "ise":
        verb = _VERB.fullmatch(word)
        return verb is not None and not verb["stem"].endswith(ONLY_ISE)
    british, american = (word, [instead]) if kind == "gb" else (instead, [word])
    return any(
        form in spelling and spelling.replace(form, without) in american
        for spelling in british.split("/")
        for form, without in DIGRAPHS.items()
    )


def derive(lines: list[Line]) -> list[tuple[str, str, str]]:
    """The rows: (word, kind, instead), sorted by word."""
    accepted: dict[str, set[str]] = {usage: set() for usage in USAGES}
    for line in lines:
        for usage, words in line.accepted.items():
            accepted[usage].update(words)

    rows: dict[str, tuple[str, str, str]] = {}
    for line in lines:
        if line.level > HIGHEST_LEVEL or len(line.preferred) < len(USAGES):
            continue
        american, british, oxford = (line.preferred[usage] for usage in USAGES)
        if not all(_WORD.fullmatch(word) for word in (american, british, oxford)):
            continue
        for word in sorted({*line.accepted["A"], *line.accepted["B"], *line.accepted["Z"]}):
            if not _WORD.fullmatch(word) or len(word) < SHORTEST:
                continue
            if word in rows or word in EVERYWHERE:
                continue
            in_a, in_b, in_z = (word in accepted[usage] for usage in USAGES)
            ise = word == british and oxford == american and _one_letter_apart(british, oxford)
            if in_a and not in_b and not in_z and IUPAC in word:
                continue
            if british == american and all(word in line.tagged.get(usage, ()) for usage in "AB"):
                continue  # a variant in both usages, and the spelling of neither
            if in_a and not in_b and not in_z and word != british:
                instead = british if oxford == british else f"{british}/{oxford}"
                row = (word, "us", instead)
            elif in_b and not in_z and not in_a and ise:
                row = (word, "ise", oxford)
            elif (in_b or in_z) and not in_a and word != american:
                row = (word, "gb", american)
            else:
                continue
            if line.verified or _regular(*row):
                rows[word] = row
    return sorted(rows.values())


def render(rows: list[tuple[str, str, str]]) -> str:
    table = "".join("\t".join(row) + "\n" for row in rows)
    return NOTICE.format(**SOURCE) + "\n" + "word\tkind\tinstead\n" + table


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    data = Path(argv[1]).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SOURCE["sha256"]:
        print(
            f"{argv[1]} is not the pinned source: its SHA-256 is {digest}, and this script "
            f"expects {SOURCE['sha256']} ({SOURCE['repository']} at {SOURCE['commit']}, "
            f"{SOURCE['path']}).",
            file=sys.stderr,
        )
        return 1
    # varcon.txt is Latin-1: four of its lines hold an accented letter. Words with one are
    # not written, so the encoding decides nothing here but whether the file can be read.
    rows = derive(read(data.decode("latin-1")))
    TARGET.write_bytes(render(rows).encode("utf-8"))
    kinds = {kind: sum(1 for row in rows if row[1] == kind) for kind in ("us", "gb", "ise")}
    print(f"wrote {TARGET.name}: {len(rows)} words, {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
