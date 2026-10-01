"""Reading what a model answered: one JSON object of the agreed shape, or nothing.

A reply is untrusted input. It is accepted when it is exactly one JSON object that fits the
reply schema, bare or inside a single code fence, and refused otherwise with a message that
says what was wrong. Nothing is repaired: prose around the object is not trimmed away, a
truncated object is not closed, a verdict outside the vocabulary is not mapped to the nearest
one, and a missing field is not filled in. Each of those would be this tool writing part of
the review, and a review nobody wrote must not be filed.
"""

from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import load_schema

SCHEMA = "review_reply"
SHOWN_ERRORS = 5

#: The whole reply inside one fence. A second fence anywhere inside means two blocks, and
#: which of them is the review would be a guess.
_FENCED = re.compile(r"```(?:json)?[ \t]*\r?\n(?P<inside>.*)\r?\n```", re.DOTALL)


class ReplyRefused(Exception):
    """The reply cannot be filed, and the reason is in the message."""


def _no_repeats(pairs: list[tuple[str, object]]) -> dict:
    found: dict = {}
    for key, value in pairs:
        if key in found:
            raise ReplyRefused(
                f"the reply gives {key!r} twice; a parser would keep the second and say "
                "nothing, and which one was meant is a guess"
            )
        found[key] = value
    return found


def _unfenced(text: str) -> str:
    fenced = _FENCED.fullmatch(text)
    if fenced is None:
        return text
    inside = fenced.group("inside")
    if "```" in inside:
        raise ReplyRefused(
            "the reply holds more than one code block; which of them is the review is a guess"
        )
    return inside


def parse_reply(text: str) -> dict:
    """The reply as a validated dict, or `ReplyRefused`."""
    body = _unfenced(text.strip())
    if not body.strip():
        raise ReplyRefused("the reply is empty")
    try:
        document = json.loads(body, object_pairs_hook=_no_repeats)
    except ValueError as exc:
        raise ReplyRefused(
            f"the reply is not one JSON object and nothing else ({exc}); text before or "
            "after the object is not trimmed away"
        ) from None
    if not isinstance(document, dict):
        raise ReplyRefused("the reply is JSON, but not an object")

    validator = Draft202012Validator(load_schema(SCHEMA))
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        said = [
            f"{'/'.join(str(part) for part in error.absolute_path) or '(root)'}: "
            f"{error.message[:200]}"
            for error in errors[:SHOWN_ERRORS]
        ]
        more = f" (and {len(errors) - SHOWN_ERRORS} more)" if len(errors) > SHOWN_ERRORS else ""
        raise ReplyRefused("the reply does not fit the review schema: " + "; ".join(said) + more)
    return document


__all__ = ["ReplyRefused", "parse_reply"]
