"""`manuscript-guard setup`: a paper started in conversation with its authors.

An agent that starts a project asks its authors what the project needs: how the manuscript
is written, its title and English, the study's design and reporting guideline, the journal,
the authors, the analysis language, where the data are, the repository. Asked from what the
agent remembers, a question is left out or asked twice, and the settings it then writes by
hand are what it understood rather than what was chosen. So the package decides what is
asked and writes what was answered, and the agent only puts the questions and records the
answers (DESIGN.md, "A paper started in conversation: `setup`").

- `setup questions` reads the folder and `design/setup.yaml`, the answers so far, and says
  which decisions are still open, each with its question, why it matters, its options and,
  where one follows from the folder, the option recommended. It writes nothing.
- `setup apply` writes the project from the answers, once none is open: `init` where there
  is no project, then each setting into the file that holds it, each only where it is blank.
  It never replaces a value: a change is `set`'s, with its guard. `--dry-run` says what it
  would write and writes nothing.

`design/setup.yaml` stays in the project as the record of what was chosen at the start.
`paper.yaml` and `authors.yaml` hold the settings, and every check reads them; nothing is
checked against the record.
"""

from __future__ import annotations

from manuscript_guard.setup.answers import ANSWERS_FILE, SCHEMA, load_answers
from manuscript_guard.setup.apply import Applied, apply_answers
from manuscript_guard.setup.folder import Folder, read_folder
from manuscript_guard.setup.questions import Asked, Option, Question, ask
from manuscript_guard.setup.say import applied_json, applied_text, asked_json, asked_text

__all__ = [
    "ANSWERS_FILE",
    "SCHEMA",
    "Applied",
    "Asked",
    "Folder",
    "Option",
    "Question",
    "applied_json",
    "applied_text",
    "apply_answers",
    "ask",
    "asked_json",
    "asked_text",
    "load_answers",
    "read_folder",
]
