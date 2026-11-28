"""Which decisions are still open, and how each is put: `ask`.

Each question is one decision, named by the place in `design/setup.yaml` its answer is
written at (`language`, `data.where`). It is open where neither the answers nor the folder
settle it; it waits where it turns on another that is open (the guideline on the design);
and it is not asked where it does not apply (the data's folder when the data are held
elsewhere). Its options are the values that may be written there, each with what it changes,
and the option recommended only where one follows from the folder or a rule: a Word paper in
the folder, the one guideline of a design. The authors decide; nothing here picks for them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manuscript_guard.setup.answers import LATER, MISSING, answer, problems
from manuscript_guard.setup.folder import Folder

AGENT, AUTHOR = "agent", "author"


@dataclass(frozen=True)
class Option:
    value: Any
    label: str
    effect: str


@dataclass(frozen=True)
class Question:
    """One decision: `kind` is `choice` (one option), `several` (any of the options),
    `text`, `number`, `yes-no` or `authors`. `other` says what an answer outside the options
    is, where one is taken; `shortlist`, how many options to offer once the author has
    described the study in their words."""

    id: str
    question: str
    why: str
    kind: str
    options: tuple[Option, ...] = ()
    recommended: Any = None
    other: str | None = None
    shortlist: int | None = None
    example: str | None = None
    problem: str | None = None


@dataclass(frozen=True)
class Known:
    """A decision the folder has made already, and where it says so."""

    id: str
    value: Any
    said: str


@dataclass(frozen=True)
class Step:
    """What comes once the project is written: the skill that takes it on, or the author."""

    skill: str | None
    title: str
    why: str
    who: str = AGENT


@dataclass(frozen=True)
class Asked:
    folder: Folder
    answers: dict
    questions: tuple[Question, ...]
    waiting: tuple[tuple[str, tuple[str, ...]], ...]
    known: tuple[Known, ...]
    after: tuple[Step, ...]

    @property
    def ready(self) -> bool:
        """Nothing is open: `apply` may write the project."""
        return not self.questions and not self.waiting


class _Wait:
    def __init__(self, *on: str) -> None:
        self.on = on


def _given(answers: dict, place: str) -> Any:
    return answer(answers, place)


def _study_type(folder: Folder, answers: dict) -> Any:
    held = folder.setting("study_type")
    return held if held is not None else _given(answers, "study_type")


# ------------------------------------------------------------------------- the questions


def _start(folder: Folder, answers: dict):
    if folder.is_project:
        return None
    words = [name for name in folder.candidates if name.lower().endswith(".docx")]
    tex = [name for name in folder.candidates if name.lower().endswith(".tex")]
    options = [Option(name, f"Bring {name} in from Word", "its text becomes "
                      "manuscript/main.md, each table a pipe table, its pictures kept")
               for name in words]  # fmt: skip
    options += [
        Option("markdown", "Markdown", "the manuscript is manuscript/main.md, built into a "
               ".docx; the Word round trip with co-authors, their checker and the proof "
               "check read Markdown"),
        Option("latex", "LaTeX", "the manuscript is manuscript/main.tex, compiled into a PDF "
               "with latexmk"),
    ]  # fmt: skip
    recommended = words[0] if len(words) == 1 else ("latex" if tex and not words else None)
    return Question("start", "How will the manuscript be written?", "A project is Markdown "
                    "or LaTeX from the first day; a paper written in Word is brought in as "
                    "Markdown.", "choice", tuple(options), recommended)  # fmt: skip


def _title(folder: Folder, answers: dict):
    from manuscript_guard.scaffold import UNTITLED

    if folder.is_project and folder.setting("title") not in (None, "", UNTITLED):
        return Known("title", folder.setting("title"), "paper.yaml")
    word = str(_given(answers, "start")).lower().endswith(".docx")
    return Question("title", "What is the paper's working title?", "It goes into paper.yaml "
                    "and the manuscript's header; it can change later."
                    + (" Leave it empty to keep the title the Word paper's Title style holds."
                       if word else ""), "text", example='title: "The working title"')  # fmt: skip


def _language(folder: Folder, answers: dict):
    from manuscript_guard.guide.rules import ENGLISH_NAMES

    held = folder.setting("english_variant")
    if held is not None:
        return Known("language", held, "paper.yaml")
    options = tuple(
        Option(code, name, f"G14 holds the manuscript's spelling to {name}, and the "
               "document is built in it")
        for code, name in ENGLISH_NAMES.items()
    ) + (Option("other", "Another language", "no English is declared: the numbers, the "
                "citations and the sources are checked as in English, and the writing checks "
                "(G6, G14 and the abbreviation rules), which read English, do not "
                "apply"),)  # fmt: skip
    return Question("language", "Which language is the manuscript written in?", "The "
                    "spelling check holds the paper to one English; a journal may ask for "
                    "one.", "choice", options)  # fmt: skip


def _design(folder: Folder, answers: dict):
    from manuscript_guard.gates.design import OTHER, study_types
    from manuscript_guard.guide.rules import _OTHER_STUDIES, _either

    held = folder.setting("study_type")
    if held is not None:
        return Known("study_type", held, "paper.yaml")
    options = tuple(
        Option(key, entry["label"], f"{entry['describes']}; the plan is asked for the "
               f"sections this design needs, and it is reported with "
               f"{_either(entry['guidelines']) if entry.get('guidelines') else 'none'}")
        for key, entry in study_types().items()
    ) + (Option(OTHER, "None of these", f"{_OTHER_STUDIES}: the plan is asked for the "
                "seven sections every plan has"),)  # fmt: skip
    return Question("study_type", "What kind of study is this?", "The design decides which "
                    "sections the analysis plan needs and which reporting guideline fits.",
                    "choice", options, shortlist=3)  # fmt: skip


def _recipe_meta(path: Path) -> dict:
    """A recipe's `meta`, read as YAML and nothing more; empty where the file is no readable
    mapping that holds one. Read as `transcribe` reads it, a half-written recipe of the
    project's raised what `setup questions` stopped on (round 1 of #856): setup offers it
    by its file's name all the same, and `transcribe` says what is wrong with it."""
    import yaml

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):  # a file not in UTF-8 is a ValueError
        return {}
    meta = document.get("meta") if isinstance(document, dict) else None
    return meta if isinstance(meta, dict) else {}


def _recipes_for(name: str, root: Path) -> list[tuple[str, dict]]:
    """The recipes of one of a design's guidelines, each by the name its profile is written
    under (`meta.name`, which `transcribe` names the profile by, else the file's), with its
    `meta`: those whose name is the guideline's or goes on from it with a hyphen or a plus
    (CARE-2013, RECORD-PE, TRIPOD+AI), the project's own among them, the current editions
    first."""
    from manuscript_guard.paths import recipes

    found = []
    for stem, path in recipes(root).items():
        meta = _recipe_meta(path)
        recipe = str(meta.get("name") or stem)
        rest = recipe[len(name):]
        if recipe.upper().startswith(name.upper()) and rest[:1] in ("", "-", "+"):
            found.append((recipe, meta))
    return sorted(found, key=lambda one: (bool(one[1].get("superseded_by")), one[0]))


def _guideline_options(names: tuple[str, ...], root: Path) -> tuple[Option, ...]:
    """Each of a design's guidelines as paper.yaml must name it to find its checklist: by
    its recipes' names, each with what its recipe says it covers, quoted as written, or by
    its own name where no recipe is there for it. Offered the design's short names, "CARE"
    or "STARD", an author found no profile of that name and was told the checklist was not
    retrieved (round 1 of #851; Basile, 2026-11-28)."""
    options: list[Option] = []
    for name in names:
        found = _recipes_for(name, root)
        if not found:
            options.append(Option(name, name, f"paper.yaml declares {name}, which has no "
                                  "recipe yet, so its checklist is not retrieved until one "
                                  "is written (the reporting-checklist skill says how)"))
        for recipe, meta in found:
            covers = " ".join(str(meta.get("applies_to") or "").split())
            replaced = meta.get("superseded_by")
            options.append(Option(recipe, recipe, f"paper.yaml declares {recipe}"
                                  + (f', for "{covers}"' if covers else "")
                                  + (f"; replaced by {replaced}" if replaced else "")
                                  + "; its checklist is then retrieved, and each item "
                                  "answered by a quoted sentence"))
    return tuple({option.value: option for option in options}.values())


def _recommended(names: tuple[str, ...], root: Path) -> list[str] | None:
    """The guideline a rule picks: the one of a design that has one, by its one current
    recipe that is not an abstract's (PRISMA: PRISMA-2020; TRIPOD: TRIPOD+AI), or by its
    own name where it has no recipe; none where the design has several."""
    if len(names) != 1:
        return None
    found = _recipes_for(names[0], root)
    if not found:
        return [names[0]]
    current = [recipe for recipe, meta in found if not meta.get("superseded_by")
               and not recipe.lower().endswith("-abstracts")]  # fmt: skip
    return current if len(current) == 1 else None


def _guideline(folder: Folder, answers: dict):
    from manuscript_guard.gates.design import study_types

    if folder.setting("reporting_guideline"):
        return Known("reporting_guideline", folder.setting("reporting_guideline"), "paper.yaml")
    design = _study_type(folder, answers)
    if design is MISSING:
        return _Wait("study_type")
    names = tuple((study_types().get(design) or {}).get("guidelines") or ())
    options = _guideline_options(names, folder.root)
    return Question("reporting_guideline", "Which reporting guidelines does the paper "
                    "follow?", "Each guideline's checklist is held to the manuscript from "
                    "internal review on. An empty list puts it off.", "several", options,
                    recommended=_recommended(names, folder.root),
                    other="a guideline's name as its recipe is named, as STROBE or "
                    "CARE-2013",
                    example="reporting_guideline: [STROBE]")  # fmt: skip


def _journal(folder: Folder, answers: dict):
    if folder.setting("target_journal"):
        return Known("journal", folder.setting("target_journal"), "paper.yaml")
    options = tuple(Option(slug, f"The profile {slug}", f"paper.yaml names {slug}, and G4 "
                           "holds the paper to its rules") for slug in folder.profiles)
    options += (
        Option("help", "Help me choose", "the journal-profile skill draws up a shortlist "
               "with the authors' criteria; nothing is set until they choose"),
        Option(LATER, "Decide later", "nothing is written; `next` asks again at drafting"),
    )  # fmt: skip
    return Question("journal", "Which journal is the paper for?", "Its own instructions "
                    "page sets the word limits, the sections and the statements G4 holds the "
                    "paper to.", "choice", options,
                    other="the journal's full name: its profile is started, to be filled "
                    "from its instructions page",
                    example='journal: {name: "BMJ Open"}')  # fmt: skip


def _authors(folder: Folder, answers: dict):
    if not folder.authors_blank:
        return Known("authors", "authors.yaml", "authors.yaml")
    return Question("authors", "Who are the authors, in the order of the byline?", "Each "
                    "name and affiliation goes on the title page as given; the corresponding "
                    "author is the one the journal writes to.", "authors",
                    example='authors: [{given: Ada, family: Byron, affiliations: '
                    '["Department, Institution, City, Country"], corresponding: true, '
                    'orcid: 0000-0002-1825-0097, email: ada@example.org}]')  # fmt: skip


def _declarations(folder: Folder, answers: dict):
    if not folder.authors_blank:
        return None
    if _given(answers, "authors") is MISSING:
        return _Wait("authors")
    return Question("declarations", "Give each author's funding, competing interests and "
                    "CRediT roles now?", "Once given, G4 holds the manuscript's Funding, "
                    "Competing interests and Author contributions to them.", "choice", (
                        Option("given", "Now", "each is written in the author's entry as "
                               "they give it"),
                        Option(LATER, "Later", "none is written; the authors add them before "
                               "drafting the declarations"),
                    ))  # fmt: skip


def _named(authors: Any) -> tuple[Option, ...]:
    """Each author answered, as an option a role may name them by: the family name, or the
    full name where two authors share one."""
    people = [a for a in authors if isinstance(a, dict)] if isinstance(authors, list) else []
    families = [str(person.get("family", "")) for person in people]
    return tuple(
        Option(name, name, "the author named")
        for person, family in zip(people, families, strict=True)
        for name in [family if families.count(family) == 1
                     else f"{person.get('given', '')} {family}".strip()]
    )  # fmt: skip


def _role(place: str, question: str, why: str, extra: tuple[Option, ...], other: str,
          *, authors_are_options: bool):  # fmt: skip
    def build(folder: Folder, answers: dict):
        if not folder.authors_blank:
            return None
        authors = _given(answers, "authors")
        if authors is MISSING:
            return _Wait("authors")
        named = _named(authors) if authors_are_options else ()
        return Question(place, question, why, "choice",
                        (*named, *extra, Option(LATER, "Later", "nothing is written now")),
                        other=other)  # fmt: skip
    return build


def _analysis(folder: Folder, answers: dict):
    if folder.languages:
        return Known("analysis", " and ".join(folder.languages), "the scripts in analysis/")
    return Question("analysis", "Which language will the analysis be written in?", "Each "
                    "script publishes its results through the emitter of its language.",
                    "choice", (
                        Option("python", "Python", "the emitter comes with this package"),
                        Option("r", "R", "the emitter is the R package manuscriptguard, which "
                               "needs jsonlite and digest; setup checks R for them"),
                        Option("other", "Another (Stata, SAS, SPSS)", "its output tables are "
                               "taken in with `harvest`"),
                        Option("undecided", "Not decided", "asked again when the analysis "
                               "starts"),
                    ))  # fmt: skip


def _data_where(folder: Folder, answers: dict):
    if folder.vault:
        return Known("data.where", "vault", "design/vault.yaml")
    return Question("data.where", "Where are the data?", "Where they are decides who may "
                    "read them: the agent, a person only, or a site's own staff.", "choice", (
                        Option("project", "In this project's folder", "the agent reads them; "
                               "setup keeps them out of git unless they may be published"),
                        Option("vault", "Held apart from the agent", "the data stay in a "
                               "folder the agent cannot read; the analysis is written against "
                               "a synthetic copy and run by a person"),
                        Option("site", "At a site or research environment", "the code is run "
                               "there and its outputs taken in with the site's receipt"),
                        Option("not-yet", "Not obtained yet", "the data-sources skill finds "
                               "with the authors which data could answer the question"),
                    ))  # fmt: skip


def _data_part(place: str, applies: tuple[str, ...], build: Callable[[dict], Question]):
    def ask_it(folder: Folder, answers: dict):
        where = "vault" if folder.vault else _given(answers, "data.where")
        if where is MISSING:
            return _Wait("data.where")
        return build(answers) if where in applies else None
    return ask_it


def _registration(folder: Folder, answers: dict):
    if folder.setting("registration"):
        return Known("registration", folder.setting("registration"), "paper.yaml")
    return Question("registration", "Is the study registered (ClinicalTrials.gov, PROSPERO, "
                    "OSF, the EU PAS register)?", "G12 holds the paper to its registration: "
                    "the identifier in the text, registered before the study and its first "
                    "results.", "choice", (
                        Option("none", "Not registered", "nothing is written"),
                        Option(LATER, "Decide later", "nothing is written now"),
                    ), other="each identifier, as the registry writes it",
                    example="registration: [NCT01234567]")  # fmt: skip


def _stage(folder: Folder, answers: dict):
    if folder.is_project and folder.setting("stage") not in (None, "design"):
        return None
    word = str(_given(answers, "start")).lower().endswith(".docx")
    if not (word or folder.languages or folder.has_results):
        return None
    from manuscript_guard.policy import DESCRIPTIONS

    options = tuple(Option(stage, stage, DESCRIPTIONS[stage])
                    for stage in ("design", "analysis", "drafting", "internal-review"))
    recommended = "drafting" if word or folder.has_results else "analysis"
    return Question("stage", "Where has the work got to?", "Each finding is due from a "
                    "stage: earlier ones are listed as not due rather than failed.",
                    "choice", options, recommended)  # fmt: skip


def _repo_git(folder: Folder, answers: dict):
    if folder.repository is not None:
        return None
    return Question("repository.git", "Keep the project in a git repository?", "History "
                    "dates the plan before the results, and lets co-authors and CI read the "
                    "same files.", "yes-no", (
                        Option(True, "Yes", "the folder becomes a git repository"),
                        Option(False, "No", "nothing is made"),
                    ))  # fmt: skip


def _repo_visibility(folder: Folder, answers: dict):
    return Question("repository.visibility", "Where will the repository be shared?", "A "
                    "public repository publishes every file committed.", "choice", (
                        Option("public", "On a public site", "the stored copies of cited "
                               "works, paywalled papers among them, stay out of git"),
                        Option("private", "On a private site", "the stored copies may be "
                               "committed; asked next"),
                        Option("none", "Nowhere", "nothing is written"),
                    ))  # fmt: skip


def _repo_sources(folder: Folder, answers: dict):
    if (folder.setting("literature") or {}).get("sources_in_git") is not None:
        return None
    visibility = _given(answers, "repository.visibility")
    if visibility is MISSING:
        return _Wait("repository.visibility")
    if visibility != "private":
        return None
    return Question("repository.sources_in_git", "Commit the stored copies of the cited "
                    "works to the private repository?", "Committed, CI holds every quote to "
                    "its source; a repository made public later would publish them.",
                    "yes-no", (
                        Option(False, "No", "they stay out of git, and CI notes a quote it "
                               "cannot hold to its copy"),
                        Option(True, "Yes", "paper.yaml says so, and .gitignore stops "
                               "leaving them out"),
                    ), recommended=False)  # fmt: skip


def _repo_actions(folder: Folder, answers: dict):
    if folder.workflow:
        return None
    visibility = _given(answers, "repository.visibility")
    if visibility is MISSING:
        return _Wait("repository.visibility")
    if visibility == "none":
        return None
    return Question("repository.github_actions", "Is it on GitHub, and should check run on "
                    "each push?", "The workflow runs check and builds the documents where it "
                    "passes.", "yes-no", (
                        Option(True, "Yes", "the workflow is written"),
                        Option(False, "No", "nothing is written"),
                    ))  # fmt: skip


def _earlier(folder: Folder, answers: dict):
    if folder.related:
        return None
    return Question("earlier_work", "Have the authors published on these data before (an "
                    "abstract, a preprint, an article)?", "Each earlier output is compared "
                    "with this paper, and the overlap disclosed.", "yes-no", (
                        Option(True, "Yes", "the related-outputs skill records each one"),
                        Option(False, "No", "nothing is written"),
                    ))  # fmt: skip


_data_folder = _data_part("data.folder", ("project",), lambda answers: Question(
    "data.folder", "Which folder of the project holds the data?", "It is named so that it "
    "can be kept out of git.", "text", options=(Option("data", "data/", "the usual name"),),
    recommended="data", other="the folder's name, inside the project",
    example="data: {folder: data}"))  # fmt: skip
_data_publishable = _data_part("data.publishable", ("project",), lambda answers: Question(
    "data.publishable", "May the data be published with the repository?", "Data about "
    "people, or under a data-use agreement, usually may not.", "yes-no", (
        Option(False, "No", "the folder goes into .gitignore, so no commit holds them"),
        Option(True, "Yes", "the folder is committed with the rest"),
    )))  # fmt: skip
_data_minimum = _data_part("data.minimum_cell_count", ("vault", "site"), lambda answers:
    Question("data.minimum_cell_count", "What is the smallest count the data's custodian "
             "lets be published?", "A count the manuscript binds below it fails G2 from "
             "internal review; registering a vault needs it said.", "number",
             other="a whole number; 1 where the custodian sets no rule",
             example="data: {minimum_cell_count: 5}"))  # fmt: skip

_statistician = _role(
    "statistician", "Who is the statistician?", "A G15 warning left standing is theirs to "
    "sign off, and only theirs.", (),
    "someone who is not an author, as `statistician: {name: <their name>}`",
    authors_are_options=True)  # fmt: skip
_ethics_lead = _role(
    "ethics_lead", "Who holds the ethics approval, and what is its reference?", "G4 holds the "
    "manuscript's ethics statement to the approval named.",
    (Option("none", "No approval is needed", "nothing is written"),),
    "the author who holds it and the approval's reference, as "
    "`ethics_lead: {author: <family name>, approval: <reference>}`",
    authors_are_options=False)  # fmt: skip

#: The questions in the order they are put, each by the place its answer is written at.
QUESTIONS: tuple[tuple[str, Callable[[Folder, dict], Any]], ...] = (
    ("start", _start),
    ("title", _title),
    ("language", _language),
    ("study_type", _design),
    ("reporting_guideline", _guideline),
    ("journal", _journal),
    ("authors", _authors),
    ("declarations", _declarations),
    ("statistician", _statistician),
    ("ethics_lead", _ethics_lead),
    ("analysis", _analysis),
    ("data.where", _data_where),
    ("data.folder", _data_folder),
    ("data.publishable", _data_publishable),
    ("data.minimum_cell_count", _data_minimum),
    ("registration", _registration),
    ("stage", _stage),
    ("repository.git", _repo_git),
    ("repository.visibility", _repo_visibility),
    ("repository.sources_in_git", _repo_sources),
    ("repository.github_actions", _repo_actions),
    ("earlier_work", _earlier),
)


def ask(folder: Folder, answers: dict) -> Asked:
    """What is still open for `folder`, given `answers`; a pure function of the two."""
    from manuscript_guard.setup.steps import after

    wrong = problems(answers, folder)
    # A question that turns on another reads only answers that can be taken: a design given
    # as a list is no design to offer guidelines for (round 1 of #844).
    usable = _without(answers, wrong)
    questions: list[Question] = []
    waiting: list[tuple[str, tuple[str, ...]]] = []
    known: list[Known] = []
    for place, build in QUESTIONS:
        if _given(answers, place) is not MISSING and place not in wrong:
            continue
        made = build(folder, usable)
        if isinstance(made, Known):
            known.append(made)
        elif isinstance(made, _Wait):
            waiting.append((place, made.on))
        elif isinstance(made, Question):
            questions.append(_with_problem(made, wrong.get(place)))
    # A problem of an answer no question asks now (`authors` where authors.yaml is filled)
    # still stops `apply`: it is put as the question it answers.
    asked = {question.id for question in questions} | {place for place, _ in waiting}
    for place, said in wrong.items():
        if place not in asked:
            questions.append(Question(place, f"The answer at `{place}` cannot be taken.",
                                      said, "text", problem=said))  # fmt: skip
    ready = not questions and not waiting
    steps = after(folder, answers) if ready else ()
    return Asked(folder, answers, tuple(questions), tuple(waiting), tuple(known), steps)


def _without(answers: dict, places) -> dict:
    """`answers` less the answers at `places`, the ones that cannot be taken."""
    import copy

    kept = copy.deepcopy(answers)
    for place in places:
        first, _, rest = place.partition(".")
        if rest and isinstance(kept.get(first), dict):
            kept[first].pop(rest, None)
        else:
            kept.pop(first, None)
    return kept


def _with_problem(question: Question, problem: str | None) -> Question:
    if problem is None:
        return question
    from dataclasses import replace

    return replace(question, problem=problem)
