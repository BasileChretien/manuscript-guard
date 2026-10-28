"""`manuscript-guard next`: what to do now, read from one run of the gates.

`check` says what is wrong; it does not say which of forty findings to start with, nor that a
choice is due that no finding names. `next` reads the project once (`inspect`), then decides
in a pure function (`decide`) what to do, in a fixed order: what stops the check first, then
the results everything else rests on, the plan, the choices due, the numbers' sources, the
other failures, the co-authors' checks, the warnings, the next stage, and last the steps an
author may take once nothing fails. Each action names the skill that deals with it and the
command that does it, as `argv` beside the command as it is shown, so that an agent runs the
words given and not its reading of a sentence.

It is advice, and `check` decides: the order is upstream first, and nothing here makes a
finding pass or fail. It writes nothing, and every call runs every gate again, with no cache,
so that what it says is about the files as they are (DESIGN.md, "`next` says what to do now").
"""

from __future__ import annotations

from manuscript_guard.guide.model import (
    AGENT,
    ASK,
    AUTHOR,
    AUTHORS_ONLY,
    NO_PROJECT,
    PROJECT,
    SCHEMA,
    UNREADABLE,
    Action,
    Checker,
    Choice,
    Option,
    State,
    argv,
    shown,
)
from manuscript_guard.guide.reading import inspect
from manuscript_guard.guide.routes import NO_ACTION, ROUTES, Route, route_of
from manuscript_guard.guide.rules import RULES, Rule, decide
from manuscript_guard.guide.say import render, to_dict, to_json

__all__ = [
    "AGENT",
    "ASK",
    "AUTHOR",
    "AUTHORS_ONLY",
    "NO_ACTION",
    "NO_PROJECT",
    "PROJECT",
    "ROUTES",
    "RULES",
    "SCHEMA",
    "UNREADABLE",
    "Action",
    "Checker",
    "Choice",
    "Option",
    "Route",
    "Rule",
    "State",
    "argv",
    "decide",
    "inspect",
    "render",
    "route_of",
    "shown",
    "to_dict",
    "to_json",
]
