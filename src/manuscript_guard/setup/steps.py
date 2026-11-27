"""What comes once the project is written from the answers: `after`.

Some decisions are made in one answer and done in many steps: a journal named is a profile
to fill from the journal's own page, a design is a plan to write section by section, data not
yet obtained are a search. Each such step goes to the skill that does it, in the order the
work needs it, upstream first; a step only a person may take (registering the vault) is said
to be theirs.
"""

from __future__ import annotations

from manuscript_guard.setup.answers import MISSING, answer, journal_slug
from manuscript_guard.setup.folder import Folder
from manuscript_guard.setup.questions import AUTHOR, Step


def _journal_step(folder: Folder, answers: dict) -> Step | None:
    journal = answer(answers, "journal")
    if isinstance(journal, dict):
        slug = journal.get("slug") or journal_slug(journal["name"])
        return Step("journal-profile", f"Fill the profile of {journal['name']}",
                    f"profiles/journals/{slug}.yaml is the annotated template until its "
                    "limits, sections and statements are read from the journal's own "
                    "instructions page")  # fmt: skip
    if journal == "help":
        return Step("journal-profile", "Choose the journal", "the authors' criteria first, "
                    "then a shortlist from the journals that publish papers like this one; "
                    "they choose")  # fmt: skip
    return None


def _data_steps(folder: Folder, answers: dict) -> list[Step]:
    where = "vault" if folder.vault else answer(answers, "data.where")
    if where == "not-yet":
        return [Step("data-sources", "Find the data", "which datasets could answer the "
                     "question, how each is reached and on what terms, before choosing")]
    if where == "vault" and not folder.vault:
        return [Step(None, "Register the data held apart", "`manuscript-guard vault init "
                     "FOLDER FILE...`, run by a person where the data can be read: it records "
                     "each file by its digest, and the agent's tool is then kept from the "
                     "folder (docs/vault.md)", AUTHOR)]  # fmt: skip
    if where == "site":
        return [Step("results-binding", "Take in what the site's run writes", "the code is "
                     "run where the data are held; `harvest` takes its output tables in, and "
                     "`verify --receipt SITE` is the site's record (docs/harvest.md)")]
    return []


def after(folder: Folder, answers: dict) -> tuple[Step, ...]:
    """The steps after `apply`, in the order the work needs them."""
    steps: list[Step | None] = [_journal_step(folder, answers), *_data_steps(folder, answers)]
    stage = answer(answers, "stage")
    if stage in (MISSING, "design", "analysis"):
        steps.append(Step("analysis-plan", "Write the analysis plan", "design/plan.md, "
                          "section by section with the authors, before the analysis runs"))
    guidelines = answer(answers, "reporting_guideline")
    if isinstance(guidelines, list) and guidelines:
        steps.append(Step("reporting-checklist", "Retrieve the checklists",
                          f"{', '.join(guidelines)}: each from its own published document, "
                          "and transcribed, so that every item can be answered by a quote"))
    if answer(answers, "earlier_work") is True:
        steps.append(Step("related-outputs", "Record the earlier outputs", "each abstract, "
                          "preprint or article on these data, compared with this paper"))
    if answer(answers, "analysis") in ("python", "r"):
        steps.append(Step("results-binding", "Write the first analysis script", "with the "
                          f"{'Python' if answer(answers, 'analysis') == 'python' else 'R'} "
                          "emitter, once the plan says what it computes"))  # fmt: skip
    return tuple(step for step in steps if step is not None)
