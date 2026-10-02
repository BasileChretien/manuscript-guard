"""Reading what a model answered: one JSON object of the agreed shape, or nothing.

A reply is untrusted input. It is accepted when it is exactly one JSON object that fits the
reply schema, bare or inside a single code fence, and refused otherwise with a message that
says what was wrong. Nothing is repaired: prose around the object is not trimmed away, a
truncated object is not closed, a verdict outside the vocabulary is not mapped to the nearest
one, and a missing field is not filled in. Each of those would be this tool writing part of
the review, and a review nobody wrote must not be filed.

One thing is read as what it plainly says. A finding's `where` may be left out, and a model
that leaves a key out often writes `null` for it. Null says what absence says, so the key is
taken as absent. No other key may be null.
"""

from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator

from manuscript_guard.contracts._schema import load_schema

SCHEMA = "review_reply"
SHOWN_ERRORS = 5

#: The whole reply inside one fence: an opening line, a closing line, and between them what
#: has to be the one JSON object. Two fenced blocks do not parse as one object, so they are
#: refused by the parser rather than by looking for a second fence, which also refused a
#: reply that only quoted three backticks inside a finding.
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


def _unwritable(node: object) -> bool:
    """Whether any string in the reply holds a character a record cannot be written with: a
    NUL, or half of a surrogate pair, which is not text and cannot be encoded as UTF-8."""
    if isinstance(node, str):
        return any(ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF for char in node)
    if isinstance(node, dict):
        return any(_unwritable(key) or _unwritable(value) for key, value in node.items())
    if isinstance(node, list):
        return any(_unwritable(item) for item in node)
    return False


def parse_reply(text: str) -> dict:
    """The reply as a validated dict, or `ReplyRefused`."""
    body = text.strip()
    fenced = _FENCED.fullmatch(body)
    if fenced is not None:
        body = fenced.group("inside")
    if not body.strip():
        raise ReplyRefused("the reply is empty")
    try:
        document = json.loads(body, object_pairs_hook=_no_repeats)
    except RecursionError:
        raise ReplyRefused("the reply is nested too deeply to be a review") from None
    except ValueError as exc:
        raise ReplyRefused(
            f"the reply is not one JSON object and nothing else ({exc}); text before or "
            "after the object is not trimmed away"
        ) from None
    if not isinstance(document, dict):
        raise ReplyRefused("the reply is JSON, but not an object")
    if _unwritable(document):
        raise ReplyRefused(
            "the reply holds a character that is not text (a NUL, or half of a surrogate "
            "pair), so it cannot be written to a record"
        )

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

    document["findings"] = [
        {key: value for key, value in finding.items() if not (key == "where" and value is None)}
        for finding in document["findings"]
    ]
    return document


__all__ = ["ReplyRefused", "parse_reply"]
