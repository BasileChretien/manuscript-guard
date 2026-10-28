"""The `communicate` group: what is said of the paper outside it, held to the paper.

A post, a press release, a plain-language summary or a graphical abstract restates the
paper's findings for readers who will not read the paper. Each is a place where a number
can be retyped wrong, a hedge dropped, an association turned into a cause or a limitation
left out. So what these texts say is drawn from a brief of the paper's own sentences
(`brief.py`), and `communicate check` holds every text to that brief and the brief to the
manuscript (`checking.py`).

The group is opt-in: `communication.enabled: true` in paper.yaml turns it on, and nothing
here runs without it. `check` never reads `communication/`, so a draft post can never fail
the paper's own gates. Nothing here sends anything or opens a connection.
"""

from __future__ import annotations

from pathlib import Path

#: Where the group keeps what it makes, under the project's root.
FOLDER = "communication"
BRIEF_FILE = "brief.yaml"
#: Where the graphical abstract is made: the folder G4 looks for (`gates/journal_boxes.py`).
GRAPHICAL_ABSTRACT = "graphical-abstract"
#: The gate every finding of `communicate check` is given under.
GATE = "COMM"


class Refused(Exception):
    """A `communicate` command that cannot run here. The message is written for the
    author, and says what to do."""


def folder(project) -> Path:
    return project.root / FOLDER


def brief_path(project) -> Path:
    return folder(project) / BRIEF_FILE


def graphical_abstract_folder(project) -> Path:
    return folder(project) / GRAPHICAL_ABSTRACT


def enabled(project) -> bool:
    """Whether paper.yaml turns the group on (`communication.enabled: true`)."""
    setting = project.setting("communication")
    return isinstance(setting, dict) and setting.get("enabled") is True


def require_enabled(project) -> None:
    if not enabled(project):
        raise Refused(
            "communication is off for this paper: write `communication: {enabled: true}` in "
            "paper.yaml to turn the communicate commands on. `check` never reads "
            f"{FOLDER}/, whether they are on or not"
        )
